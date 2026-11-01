"""模型库（v2.13）：一个产品可以有很多模型文件（选品工具推过来的、自己上传的、多规格各一份、套件里好几个组件），
都放在这个产品自己的文件夹里，列出每个文件的尺寸、体积、估算克数 / 时长、组件数、能不能放进哪台打印机，
员工自己选：
- 选一个文件当「3D 模型」（切片、估算、3D 预览都用它）；
- 勾选好几个文件 / 组件（每个可以填数量），合并成一套摆在一盘上，一起切片；
- 需要人工摆盘的：下载这些文件到切片软件里摆好切片，把整盘的切片文件上传（文件管理「⬆ 上传切片文件」）。

文件位置：data/products/<编号>/models/（自己上传的、合并出来的）和 data/products/<编号>/source_files/（选品工具推过来的）。
索引：产品资料里的 model_lib 列表（文件信息 + 分析结果）。
v2.53：合并出来的模型（origin = merged）只管打印，记着 parts_of（原来的零件）；展示（modules/model/assembly.py）用到它时自动拆回零件。
"""
import io
import os
import re
import shutil
import time
import uuid
import zipfile

import numpy as np

from . import fleet, mesh, slicer, store
from .config import load_config

DIRS = ("models", "source_files")
MODEL_EXT = (".stl", ".3mf", ".obj")          # 能读尺寸、能当 3D 模型的
KEEP_EXT = MODEL_EXT + (".step", ".stp", ".zip", ".f3d", ".blend", ".scad", ".gcode")
MAX_UPLOAD = 500 * 1024 * 1024
LAYOUT_GAP = 8.0
LAYOUT_WIDTH = 240.0


def _dir(pid, kind="models"):
    d = os.path.join(store.product_dir(pid), kind)
    os.makedirs(d, exist_ok=True)
    return d


def path_of(pid, e):
    fp = os.path.join(store.product_dir(pid), e.get("dir") or "models", os.path.basename(e["file"]))
    return fp if os.path.exists(fp) else None


# ---------------- 读模型（按组件分开） ----------------
def _parts_3mf(data):
    try:                                     # v2.23：按盘上的摆放（transform）读零件
        sc = mesh.scene_3mf(data)
    except (zipfile.BadZipFile, KeyError, ValueError):
        sc = None
    if sc:
        return sc
    z = zipfile.ZipFile(io.BytesIO(data))
    out = []
    for n in z.namelist():
        if not n.lower().endswith(".model"):
            continue
        buf = z.read(n)
        pos = 0
        while True:                          # 一个个 <object>（用 find 定位，大文件也快）
            r = mesh._between(buf, rb"object", pos)
            if not r:
                break
            a, b = r
            head = buf[buf.rfind(b"<", 0, a):a]
            pos = b + 1
            if b"mesh" not in buf[a:min(b, a + 400)] and not re.search(rb"<(?:\w+:)?mesh[\s>]", buf[a:min(b, a + 4000)]):
                continue
            nm = re.search(rb'\bname="([^"]*)"', head)
            for tris in mesh._parse_3mf_model(buf[a:b]):
                name = nm.group(1).decode("utf-8", "ignore") if nm else ""
                out.append((name or f"组件 {len(out) + 1}", tris))
    if not out:
        tris = mesh._load_3mf(data)
        out = [("组件 1", tris)]
    return out


def _parts_obj(text):
    verts, parts, cur, name = [], [], [], "组件 1"
    for line in text.splitlines():
        if line.startswith("v "):
            verts.append([float(x) for x in line.split()[1:4]])
        elif line.startswith(("o ", "g ")) and cur:
            parts.append((name, cur)); cur = []
            name = line[2:].strip() or f"组件 {len(parts) + 1}"
        elif line.startswith(("o ", "g ")):
            name = line[2:].strip() or name
        elif line.startswith("f "):
            idx = [int(t.split("/")[0]) for t in line.split()[1:]]
            idx = [i - 1 if i > 0 else len(verts) + i for i in idx]
            for k in range(1, len(idx) - 1):
                cur.append((idx[0], idx[k], idx[k + 1]))
    if cur:
        parts.append((name, cur))
    v = np.array(verts, dtype=np.float64)
    out = [(n, v[np.array(f, dtype=np.int64)]) for n, f in parts if f]
    if not out:
        raise ValueError("OBJ 里没有面")
    return out


def load_parts(path):
    """[(组件名, 三角面数组)]（读过的有缓存，见 mesh.cached）"""
    return list(mesh.cached(path, _load_parts_file))


def _load_parts_file(path):
    with open(path, "rb") as f:
        data = f.read()
    low = path.lower()
    if low.endswith(".3mf") or data[:2] == b"PK":
        return _parts_3mf(data)
    if low.endswith(".obj"):
        return _parts_obj(data.decode("utf-8", "ignore"))
    return [("整个模型", mesh._load_stl(data))]


# ---------------- 缩略图（服务器画，不靠浏览器 3D） ----------------
def render_thumb(tris, out_path, px=240):
    """斜上方看过去的灰色模型图（画家算法，三角面多时只画面积大的那些）。"""
    from PIL import Image, ImageDraw
    t = np.asarray(tris, dtype=np.float64)
    if len(t) > 120000:
        a = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
        t = t[np.argsort(-a)[:120000]]
    # 视角：从前右上方看（和切片软件默认差不多）
    az, el = np.radians(-35), np.radians(28)
    rz = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(el), -np.sin(el)], [0, np.sin(el), np.cos(el)]])
    v = t.reshape(-1, 3) @ (rx @ rz).T
    v = v.reshape(-1, 3, 3)
    x, depth, z = v[..., 0], v[..., 1], v[..., 2]
    mn = np.array([x.min(), z.min()])
    span = max(x.max() - mn[0], z.max() - mn[1], 1e-6)
    sc = (px * 0.86) / span
    ox = (px - (x.max() - mn[0]) * sc) / 2
    oy = (px - (z.max() - mn[1]) * sc) / 2
    sx = (x - mn[0]) * sc + ox
    sy = px - ((z - mn[1]) * sc + oy)
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    ln = np.linalg.norm(n, axis=1)
    ln[ln == 0] = 1
    n = n / ln[:, None]
    light = np.array([0.35, -0.75, 0.55])
    light = light / np.linalg.norm(light)
    shade = np.clip(np.abs(n @ light), 0, 1)
    order = np.argsort(-depth.mean(1))           # 远的先画
    img = Image.new("RGB", (px, px), (246, 248, 251))
    d = ImageDraw.Draw(img)
    for i in order:
        g = int(95 + 140 * shade[i])
        d.polygon([(sx[i, 0], sy[i, 0]), (sx[i, 1], sy[i, 1]), (sx[i, 2], sy[i, 2])], fill=(g, g, min(255, g + 12)))
    img.save(out_path, "PNG")
    return out_path


# ---------------- 摆放方向 + 空打风险 ----------------
def orient_risks(st, material="PLA"):
    """按几何数据判断这个方向打印容易出什么问题（空打 / 打飞 / 垂丝 / 倒）。
    每条：level、code + vars（界面按编号翻译成中文 / 泰文）、text（中文，给 AI 和日志用）。阈值见 RISK（可以按实际打印结果校准）。"""
    from . import calib
    R = calib.risk_thresholds()
    out = []
    c, ov, h, tr = st.get("contact_cm2") or 0, st.get("overhang_cm2") or 0, st.get("height_mm") or 0, st.get("tall_ratio") or 0

    def add(level, code, text, **v):
        out.append({"level": level, "code": code, "vars": v, "text": text})
    if c < R["contact_bad"]:
        add("bad", "risk.contact_bad", f"贴平台面积只有 {c} cm²，几乎是点接触，很容易打飞变成空打：换个方向，或开支撑 + 帽檐", c=c)
    elif c < R["contact_warn"]:
        add("warn", "risk.contact_warn", f"贴平台面积小（{c} cm²），容易翘边或被喷嘴撞掉：建议加帽檐（brim）", c=c)
    if ov > R["overhang_bad"]:
        add("bad" if c < R["contact_warn"] else "warn", "risk.overhang_bad", f"悬空面积 {ov} cm²，不开支撑会垂丝、塌陷甚至空打：一定要开支撑（推荐树状支撑）", o=ov)
    elif ov > R["overhang_warn"]:
        add("warn", "risk.overhang_warn", f"悬空 {ov} cm²，需要开支撑", o=ov)
    if tr > R["tall_warn"] or (tr > R["tall_warn"] * 0.625 and c < 3):
        add("warn" if tr <= R["tall_bad"] else "bad", "risk.tall", f"细高（高 {h} mm，高 / 底 ≈ {tr}），打高了容易晃动、被撞倒：降速、加帽檐，或换成躺着打", h=h, r=tr)
    if str(material).upper().startswith(("ABS", "ASA")) and (st.get("footprint_mm") or [0, 0])[0] > 150:
        add("warn", "risk.abs", "ABS / ASA 大件容易翘边：要关门（封闭仓）、加帽檐")
    return out


RISK_CODES = ("risk.contact_bad", "risk.contact_warn", "risk.overhang_bad", "risk.overhang_warn", "risk.tall", "risk.abs")


def risk_label(code, vars_=None, lang="zh"):
    """v2.52：空打风险编号 → 中文 / 泰文整句（和前台 static/i18n_keys.js 同一份）。没有这个编号时返回编号本身。"""
    import json
    global _RISK_KEYS
    if _RISK_KEYS is None:
        try:
            src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "i18n_keys.js"), encoding="utf-8").read()
            body = src[src.index("{", src.index("I18N_KEYS")):src.rindex("}") + 1]
            _RISK_KEYS = {k: v for k, v in json.loads(body).items() if k.startswith("risk.")}
        except (OSError, ValueError):
            _RISK_KEYS = {}
    e = _RISK_KEYS.get(code)
    if not e:
        return code
    s = e.get("th" if lang == "th" else "zh") or e.get("zh") or code
    for k, v in (vars_ or {}).items():
        s = s.replace("{" + k + "}", str(v))
    return s


_RISK_KEYS = None


def orient_table(tris, material="PLA"):
    rows = mesh.analyze_all(tris)
    for r in rows:
        r["risks"] = orient_risks(r, material)
        r["level"] = "bad" if any(x["level"] == "bad" for x in r["risks"]) else "warn" if r["risks"] else "ok"
    best = min(rows, key=lambda r: ({"ok": 0, "warn": 1, "bad": 2}[r["level"]], r["score"]))["key"]
    return rows, best


def _beds():
    """配置里每种机型的打印范围。"""
    out = {}
    models = {m["name"]: m for m in fleet.MODELS}
    for p in load_config().get("printers") or []:
        if p.get("enabled", True) is False:
            continue
        m = models.get(p.get("name"))
        if m and m.get("bed"):
            out[p.get("name")] = m["bed"]
    return out


def _fit(size, beds):
    """能放进哪些打印机（允许转 90°）。"""
    ok, no = [], []
    for name, b in beds.items():
        fits = size[2] <= b[2] and ((size[0] <= b[0] and size[1] <= b[1]) or (size[1] <= b[0] and size[0] <= b[1]))
        (ok if fits else no).append(name)
    return {"ok": ok, "too_big": no}


def _est(cfg, m, material):
    """估算克数 + 时长（时长取第一台 FDM 打印机的）。"""
    try:
        est = slicer.estimate(cfg, m, material)
    except Exception:  # noqa: BLE001
        return None
    pp = [x for x in est.get("per_printer") or []]
    fdm = [x for i, x in enumerate(pp) if fleet.tech_of((cfg.get("printers") or [{}] * (i + 1))[i]) != "resin"] if cfg.get("printers") else pp
    first = (fdm or pp or [{}])[0]
    return {"grams": est.get("grams"), "hours": first.get("hours"), "printer": first.get("name")}


INFO_VER = 4   # 分析内容有变化就加 1：旧的分析结果会自动重新分析（2 = 摆放方向 / 空打风险 / STL 缩略图；3 = 3MF 按 transform 摆放 + 多色；4 = 多色 3MF 每种耗材用量）


def _color_names(ci):
    """耗材颜色 → 颜色表里最接近的中文名（告诉员工装什么颜色）。"""
    from . import codes
    cmap = codes.color_hex(load_config())

    def rgb(h):
        h = (h or "").lstrip("#")
        try:
            return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return None
    for f in ci.get("filaments") or []:
        t = rgb(f.get("hex"))
        best = None
        for zh, inf in cmap.items():
            c = rgb(inf.get("hex"))
            if t and c:
                d = sum((a - b) ** 2 for a, b in zip(t, c)) ** 0.5
                if best is None or d < best[1]:
                    best = (zh, d)
        f["name"] = best[0] if best and best[1] < 120 else ""
    return ci


def analyze(pid, e):
    """读尺寸、体积、组件、估算克数 / 时长、缩略图、是不是带切片数据的项目文件。"""
    fp = path_of(pid, e)
    from . import calib
    info = {"ok": False, "analyzed_at": time.time(), "v": INFO_VER, "rk": calib.risk_key()}
    if not fp:
        info["reason"] = "文件不见了"
        return info
    ext = os.path.splitext(fp)[1].lower()
    if ext not in MODEL_EXT:
        info["reason"] = {".step": "STEP 文件这里读不了尺寸，可以在切片软件或 CAD 里打开",
                          ".stp": "STEP 文件这里读不了尺寸，可以在切片软件或 CAD 里打开",
                          ".zip": "压缩包，下载后解压再上传里面的模型"}.get(ext, "这种文件这里读不了尺寸")
        return info
    cfg = load_config()
    p = store.load(pid)
    mat = p.get("material", "PLA")
    # 3MF 自带缩略图就不用自己画
    has_png = False
    if ext == ".3mf":                   # v2.23：多色（耗材颜色、每个零件用哪一槽）
        try:
            with open(fp, "rb") as f:
                ci = mesh.colors_3mf(f.read())
            if ci:
                try:                         # v2.52：带切片数据的多色 3MF：每种耗材用了多少克（slice_info）
                    with zipfile.ZipFile(fp) as z0:
                        if "Metadata/slice_info.config" in z0.namelist():
                            fl = slicer.slice_info_filaments(z0.read("Metadata/slice_info.config").decode("utf-8", "ignore"))
                            if fl:
                                ci["usage"] = [{"slot": f["slot"], "grams": f["grams"]} for f in fl]
                except (zipfile.BadZipFile, OSError, KeyError):
                    pass
                info["colors"] = _color_names(ci)
        except (zipfile.BadZipFile, OSError, ValueError):
            pass
    if ext == ".3mf":
        try:
            has_png = any(n.lower().endswith(".png") and "metadata" in n.lower() for n in zipfile.ZipFile(fp).namelist())
        except (zipfile.BadZipFile, OSError):
            pass
    tname = f"_thumb_{e['id']}.png"
    tpath = os.path.join(_dir(pid, "models"), tname)
    # 读模型、算尺寸 / 方向 / 零件、画缩略图：大文件交给电脑做（v2.20，core/kernels）
    from . import kernels
    try:
        sm = kernels.mesh_summary(fp, mat, orients=True, parts=True, thumb_to=None if has_png else tpath)
    except Exception as e2:  # noqa: BLE001
        info["reason"] = f"读不了：{str(e2)[:120]}"
        return info
    m = sm["metrics"]
    est = _est(cfg, m, mat)
    beds = _beds()
    info.update(ok=True, size=m["size"], volume_cm3=round(m["volume_mm3"] / 1000, 2), area_cm2=round(m["area_mm2"] / 100, 1),
                triangles=sm["triangles"], est=est, fit=_fit(m["size"], beds))
    if sm.get("orients"):
        info["orients"], info["best"] = sm["orients"], sm.get("best")
    if sm.get("parts"):
        pl = []
        for r in sm["parts"]:
            pm = r["metrics"]
            row = {"index": r["index"], "name": r["name"], "size": pm["size"], "volume_cm3": round(pm["volume_mm3"] / 1000, 2),
                   "triangles": r["triangles"], "est": _est(cfg, pm, mat), "fit": _fit(pm["size"], beds)}
            if r.get("orients"):
                row["orients"], row["best"] = r["orients"], r.get("best")
            pl.append(row)
        info["parts"] = pl
    if sm.get("thumb"):
        info["thumb"] = tname
    if ext == ".3mf":
        try:
            z = zipfile.ZipFile(fp)
            names = z.namelist()
            pngs = sorted([n for n in names if n.lower().endswith(".png") and "metadata" in n.lower()],
                          key=lambda n: (0 if "plate_1" in n.lower() and "small" not in n.lower() else 1, len(n)))
            if pngs:
                tdir = _dir(pid, "models")
                tname = f"_thumb_{e['id']}.png"
                with open(os.path.join(tdir, tname), "wb") as f:
                    f.write(z.read(pngs[0]))
                info["thumb"] = tname
            if any("slice_info" in n.lower() or n.lower().endswith(".gcode") for n in names):
                info["sliced"] = True
                try:
                    r = slicer.parse_sliced_file(fp, p.get("material", "PLA"))
                    if r and (r.get("grams") or r.get("hours")):
                        info["sliced_result"] = {k: r.get(k) for k in ("grams", "hours", "printer", "per_plate") if r.get(k) is not None}
                except Exception:  # noqa: BLE001
                    pass
        except zipfile.BadZipFile:
            pass
    from . import preview
    preview.warm(fp)                      # 后台先算好 👁 预览用的精简模型
    return info


# ---------------- 索引 ----------------
def _sync(p):
    """把文件夹里还没登记的文件登记进来（选品工具推过来的、旧版本的当前模型）。返回是否有变化。"""
    if not isinstance(p.get("model_lib"), list):     # 编辑页保存时可能存成了 null（v2.18 修）
        p["model_lib"] = []
    lib = p["model_lib"]
    known = {(e.get("dir"), e["file"]) for e in lib}
    changed = False
    src = {x.get("name"): x for x in (p.get("source_files") or [])}
    for d in DIRS:
        folder = os.path.join(store.product_dir(p["id"]), d)
        if not os.path.isdir(folder):
            continue
        for n in sorted(os.listdir(folder)):
            if n.startswith((".", "_")) or (d, n) in known:
                continue
            if os.path.splitext(n)[1].lower() not in KEEP_EXT:
                continue
            s = src.get(n) or {}
            lib.append({"id": "m" + uuid.uuid4().hex[:8], "file": n, "dir": d, "orig_name": s.get("orig_name") or n,
                        "bytes": os.path.getsize(os.path.join(folder, n)), "ext": os.path.splitext(n)[1].lower().lstrip("."),
                        "origin": "curator" if d == "source_files" else "upload", "variant": s.get("variant") or "",
                        "added_at": s.get("added_at") or os.path.getmtime(os.path.join(folder, n)), "added_by": s.get("added_by") or ""})
            changed = True
    # 当前 3D 模型不在库里（2.13 以前上传的）：复制一份进模型库，以后切换回来不会丢
    cur = p.get("model")
    if cur and not cur.get("lib_id"):
        mp = os.path.join(store.product_dir(p["id"]), "model", cur["file"])
        same = None
        if os.path.exists(mp):
            sz = os.path.getsize(mp)
            same = next((e for e in lib if e.get("bytes") == sz and (e.get("orig_name") or "").lower() == (cur.get("orig_name") or "").lower()), None)
        if same:
            cur["lib_id"] = same["id"]
            changed = True
        elif os.path.exists(mp):
            name = _free_name(p["id"], cur.get("orig_name") or cur["file"])
            shutil.copyfile(mp, os.path.join(_dir(p["id"]), name))
            e = {"id": "m" + uuid.uuid4().hex[:8], "file": name, "dir": "models", "orig_name": cur.get("orig_name") or name,
                 "bytes": os.path.getsize(mp), "ext": os.path.splitext(name)[1].lower().lstrip("."), "origin": "upload",
                 "variant": "", "added_at": cur.get("uploaded_at") or time.time(), "added_by": cur.get("uploaded_by") or ""}
            lib.append(e)
            cur["lib_id"] = e["id"]
            changed = True
    # 文件被删掉的条目去掉
    keep = [e for e in lib if path_of(p["id"], e)]
    if len(keep) != len(lib):
        p["model_lib"] = keep
        changed = True
    return changed


def _free_name(pid, name):
    name = re.sub(r"[\\/:*?\"<>|]+", "_", os.path.basename(name or "model.stl"))[:120] or "model.stl"
    d = _dir(pid)
    if not os.path.exists(os.path.join(d, name)):
        return name
    stem, ext = os.path.splitext(name)
    for i in range(2, 999):
        cand = f"{stem}_{i}{ext}"
        if not os.path.exists(os.path.join(d, cand)):
            return cand
    return f"{uuid.uuid4().hex[:6]}_{name}"


def library(pid, reanalyze=False):
    from . import calib
    rk = calib.risk_key()
    p = store.load(pid)
    changed = _sync(p)
    for e in p.get("model_lib") or []:
        inf = e.get("info") or {}
        if (reanalyze or not inf or inf.get("analyzed_at", 0) < os.path.getmtime(path_of(pid, e))
                or (inf.get("ok") and (inf.get("v", 1) < INFO_VER or inf.get("rk") != rk))):
            e["info"] = analyze(pid, e)
            changed = True
    if changed:
        store.save(p)
    # 选品工具建档时记的「规格 → 文件名」：对上模型库里的条目
    by_file = {e["file"]: e for e in p.get("model_lib") or []}
    for v in p.get("variants") or []:
        if v.get("model_file") and not v.get("model_lib_id") and v["model_file"] in by_file:
            v["model_lib_id"] = by_file[v["model_file"]]["id"]
            if not by_file[v["model_file"]].get("variant"):
                by_file[v["model_file"]]["variant"] = v.get("opt2_zh") or ""
            changed = True
    if changed:
        store.save(p)
    cur = (p.get("model") or {}).get("lib_id")
    used = {}
    for v in p.get("variants") or []:
        if v.get("model_lib_id") and v.get("opt2_zh"):
            used.setdefault(v["model_lib_id"], set()).add(v["opt2_zh"])
    items = []
    for e in p.get("model_lib") or []:
        d = dict(e)
        d["current"] = e["id"] == cur
        d["spec_models"] = sorted(used.get(e["id"], []))
        items.append(d)
    items.sort(key=lambda d: (not d["current"], d.get("origin") == "merged", -(d.get("added_at") or 0)))
    specs = list(dict.fromkeys((v.get("opt2_zh") or "").strip() for v in p.get("variants") or [] if (v.get("opt2_zh") or "").strip()))
    return {"items": items, "current": p.get("model"), "specs": specs, "beds": _beds(), "material": p.get("material") or "PLA"}


def count(p):
    """文件管理列表里显示的数量（不分析，只数文件）。"""
    n = 0
    for d in DIRS:
        folder = os.path.join(store.product_dir(p["id"]), d)
        if os.path.isdir(folder):
            n += sum(1 for x in os.listdir(folder) if not x.startswith((".", "_")) and os.path.splitext(x)[1].lower() in KEEP_EXT)
    if p.get("model") and not (p["model"] or {}).get("lib_id"):
        n += 1
    return n


def _entry(p, eid):
    e = next((x for x in p.get("model_lib") or [] if x["id"] == eid), None)
    if not e:
        raise ValueError("模型库里没有这个文件（可能刚被删除，刷新一下）")
    return e


class SavedFile:
    """已经存到临时文件的上传文件（后台任务里用，接口和 werkzeug 的 FileStorage 一样有 filename / save）。"""

    def __init__(self, path, filename):
        self.path, self.filename = path, filename

    def save(self, dest):
        shutil.move(self.path, dest)

    def cleanup(self):
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass


def upload(pid, files, user="", variant=""):
    p = store.load(pid)
    _sync(p)
    added = []
    for f in files:
        orig = os.path.basename(f.filename or "model")
        ext = os.path.splitext(orig)[1].lower()
        if ext not in KEEP_EXT:
            raise ValueError(f"「{orig}」不是模型文件（支持 STL、3MF、OBJ，也可以存 STEP、ZIP）")
        name = _free_name(pid, orig)
        dest = os.path.join(_dir(pid), name)
        f.save(dest)
        if os.path.getsize(dest) > MAX_UPLOAD:
            os.remove(dest)
            raise ValueError(f"「{orig}」太大了（最大 500MB）")
        e = {"id": "m" + uuid.uuid4().hex[:8], "file": name, "dir": "models", "orig_name": orig[:120], "bytes": os.path.getsize(dest),
             "ext": ext.lstrip("."), "origin": "upload", "variant": variant or "", "added_at": time.time(), "added_by": user}
        p.setdefault("model_lib", []).append(e)
        e["info"] = analyze(pid, e)
        added.append(e)
    store.save(p)
    return added


def set_spec(pid, eid, spec, user=""):
    """这个文件对应哪个规格（空 = 整个产品）。"""
    p = store.load(pid)
    _sync(p)
    e = _entry(p, eid)
    specs = {(v.get("opt2_zh") or "").strip() for v in p.get("variants") or []}
    if spec and spec not in specs:
        raise ValueError(f"这个产品没有规格「{spec}」")
    e["variant"] = spec or ""
    for v in p.get("variants") or []:
        if (v.get("opt2_zh") or "").strip() == spec and spec:
            v["model_lib_id"] = eid
            v["model_file"] = e["file"]
            v["model_note"] = ""
        elif v.get("model_lib_id") == eid and (v.get("opt2_zh") or "").strip() != spec:
            v.pop("model_lib_id", None)
    store.save(p)
    return library(pid)


def remove(pid, eid, user=""):
    p = store.load(pid)
    _sync(p)
    e = _entry(p, eid)
    if (p.get("model") or {}).get("lib_id") == eid:
        raise ValueError("这个文件是现在的 3D 模型，先换成别的再删除")
    fp = path_of(pid, e)
    if fp:
        trash = os.path.join(store.product_dir(pid), "model_history")
        os.makedirs(trash, exist_ok=True)
        shutil.move(fp, os.path.join(trash, f"{time.strftime('%Y%m%d_%H%M%S')}__{os.path.basename(fp)}"))
    th = (e.get("info") or {}).get("thumb")
    if th and os.path.exists(os.path.join(_dir(pid), th)):
        os.remove(os.path.join(_dir(pid), th))
    p["model_lib"] = [x for x in p.get("model_lib") or [] if x["id"] != eid]
    for v in p.get("variants") or []:
        if v.get("model_lib_id") == eid:
            v.pop("model_lib_id", None)
    store.save(p)
    return library(pid)


def place(tris, x, y, rot=0.0):
    """v2.52 手动摆盘：零件（已经按方向转好）绕竖直轴转 rot 度，外框中心放到热床 (x, y)，底面 z=0。"""
    t = np.asarray(tris, dtype=np.float64)
    v = t.reshape(-1, 3)
    mn, mx = v.min(0), v.max(0)
    t = t - np.array([(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]])
    a = np.radians(float(rot or 0))
    if a:
        rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
        t = (t.reshape(-1, 3) @ rz.T).reshape(-1, 3, 3)
    return t + np.array([float(x), float(y), 0.0])


def _layout(pieces, width=LAYOUT_WIDTH, gap=LAYOUT_GAP):
    """把组件按外框一排排摆开（不重叠），底面都放到 z=0。pieces: [(tris, qty)] 或 [(tris, qty, (x, y, rot))]。
    v2.52：每件都带位置（打印方案里手动摆好的盘）时，按位置放，不自动排。"""
    if pieces and all(len(pc) > 2 and pc[2] for pc in pieces):
        return np.concatenate([place(t, *pos) for t, qty, pos in pieces for _ in range(int(qty))])
    boxes = []
    for pc in pieces:
        tris, qty = pc[0], pc[1]
        t = tris - tris.reshape(-1, 3).min(0)
        s = t.reshape(-1, 3).max(0)
        for _ in range(int(qty)):
            boxes.append((t, s))
    boxes.sort(key=lambda b: -b[1][1])
    out, x, y, row_h = [], 0.0, 0.0, 0.0
    for t, s in boxes:
        if x > 0 and x + s[0] > width:
            x, y, row_h = 0.0, y + row_h + gap, 0.0
        out.append(t + np.array([x, y, 0.0]))
        x += s[0] + gap
        row_h = max(row_h, s[1])
    return np.concatenate(out)


def _norm_sel(selection):
    sel = [s for s in selection or [] if s.get("id") and int(s.get("qty") or 1) > 0]
    for s_ in sel:
        if s_.get("orient") not in mesh.ORIENT_ZH:
            s_["orient"] = "bottom"
    if not sel:
        raise ValueError("请先勾选文件或组件")
    if sum(int(s.get("qty") or 1) for s in sel) > 200:
        raise ValueError("一次最多 200 件")
    return sel


def _pos(s):
    """选择里带了位置（打印方案手动摆的盘）→ (x, y, rot)；没有 → None。"""
    try:
        if s.get("x") is not None and s.get("y") is not None:
            return (float(s["x"]), float(s["y"]), float(s.get("rot") or 0))
    except (TypeError, ValueError):
        pass
    return None


def _posd(s):
    p = _pos(s)
    return {"x": p[0], "y": p[1], "rot": p[2]} if p else {}


def _pieces(pid, p, sel):
    """按勾选的文件 / 组件、数量、方向读出要摆的零件。返回 (pieces, desc)。"""
    pieces, desc = [], []
    for s in sel:
        e = _entry(p, s["id"])
        fp = path_of(pid, e)
        if os.path.splitext(fp)[1].lower() not in MODEL_EXT:
            raise ValueError(f"「{e['orig_name']}」不能合并（要 STL、3MF 或 OBJ）")
        parts = load_parts(fp)
        qty = max(1, int(s.get("qty") or 1))
        try:                                   # v2.53：按主模型缩放的规格（打印方案里每个零件带 scale）
            k = float(s.get("scale") or 1)
        except (TypeError, ValueError):
            k = 1.0
        k = k if 0.01 <= k <= 20 else 1.0
        if s.get("part") not in (None, ""):
            i = int(s["part"])
            if not 0 <= i < len(parts):
                raise ValueError(f"「{e['orig_name']}」没有第 {i + 1} 个组件")
            pieces.append((mesh.rotate(np.asarray(parts[i][1]) * k, s["orient"]), qty, _pos(s)))
            desc.append({"id": e["id"], "part": i, "qty": qty, "orient": s["orient"], "label": f"{e['orig_name']} / {parts[i][0]}", **_posd(s)})
        else:
            pieces.append((mesh.rotate(np.concatenate([t for _n, t in parts]) * k, s["orient"]), qty, _pos(s)))
            desc.append({"id": e["id"], "part": None, "qty": qty, "orient": s["orient"], "label": e["orig_name"], **_posd(s)})
    return pieces, desc


def _width(bed_w):
    try:
        w = float(bed_w or 0)
    except (TypeError, ValueError):
        w = 0
    return max(60.0, w - 16) if w else LAYOUT_WIDTH


def layout_preview(pid, selection, bed_w=None):
    """按勾选的零件和方向排一盘，返回三角面（不保存），给「预览摆盘」用。"""
    p = store.load(pid)
    _sync(p)
    sel = _norm_sel(selection)
    pieces, _desc = _pieces(pid, p, sel)
    return _layout(pieces, width=_width(bed_w))


def make_entry(pid, selection, user="", name="", bed_w=None, variant="", sets=1):
    """v2.23：把勾选的文件 / 组件（按数量）摆在一起存成模型库里的一个组合模型，不改主模型。返回库条目。
    给「规格只用 3MF 里的某几个组件」用。"""
    p = store.load(pid)
    _sync(p)
    sel = _norm_sel(selection)
    pieces, desc = _pieces(pid, p, sel)
    tris = _layout(pieces, width=_width(bed_w))
    nm = (name or "").strip() or ("组合_" + "+".join(f"{os.path.splitext(d['label'].split(' / ')[-1])[0][:12]}x{d['qty']}" for d in desc[:4]))
    fname = _free_name(pid, re.sub(r"[^\w一-鿿\-+x×]+", "_", nm)[:60] + ".stl")
    mesh.write_stl(tris, os.path.join(_dir(pid), fname))
    e = {"id": "m" + uuid.uuid4().hex[:8], "file": fname, "dir": "models", "orig_name": fname, "bytes": os.path.getsize(os.path.join(_dir(pid), fname)),
         "ext": "stl", "origin": "merged", "variant": variant, "added_at": time.time(), "added_by": user, "parts_of": desc,
         **({"parts_sets": int(sets)} if int(sets or 1) > 1 else {})}       # v2.53：一盘出几套（展示拆回零件时只要一套）
    p.setdefault("model_lib", []).append(e)
    e["info"] = analyze(pid, e)
    store.save(p)
    return e


def make_current(pid, selection, user="", name="", bed_w=None, sets=1):
    """selection: [{"id": 库文件 id, "part": 组件序号或 null, "qty": 数量}]
    只选一个文件、没选组件、数量 1：直接把这个文件设为 3D 模型；
    其他情况：把选中的文件 / 组件按数量摆在一起，存成一个组合模型（也进模型库），再设为 3D 模型。"""
    from . import filemgr
    p = store.load(pid)
    _sync(p)
    sel = _norm_sel(selection)
    if len(sel) == 1 and sel[0].get("part") in (None, "") and int(sel[0].get("qty") or 1) == 1 and sel[0]["orient"] == "bottom":
        e = _entry(p, sel[0]["id"])
        fp = path_of(pid, e)
        ext = os.path.splitext(fp)[1].lower()
        if ext not in MODEL_EXT:
            raise ValueError("这种文件不能当 3D 模型（要 STL、3MF 或 OBJ）")
        if ext == ".obj":         # 3D 模型只收 STL / 3MF：OBJ 转成 STL
            tris = np.concatenate([t for _n, t in load_parts(fp)])
            tmp = os.path.join(_dir(pid), f"_tmp_{uuid.uuid4().hex[:6]}.stl")
            mesh.write_stl(tris, tmp)
            try:
                r = filemgr.set_model(pid, tmp, os.path.splitext(e["orig_name"])[0] + ".stl", user)
            finally:
                os.remove(tmp)
        else:
            r = filemgr.set_model(pid, fp, e["orig_name"], user)
        p = store.load(pid)
        p["model"]["lib_id"] = e["id"]
        p["model"]["parts_of"] = None
        store.save(p)
        return {"product": p, "replaced": r["replaced"], "files_reset": r["files_reset"], "merged": None}
    pieces, desc = _pieces(pid, p, sel)
    tris = _layout(pieces, width=_width(bed_w))
    nm = (name or "").strip() or ("组合_" + "+".join(f"{os.path.splitext(d['label'].split(' / ')[-1])[0][:12]}x{d['qty']}" for d in desc[:4]))
    fname = _free_name(pid, re.sub(r"[^\w一-鿿\-+x]+", "_", nm)[:60] + ".stl")
    mesh.write_stl(tris, os.path.join(_dir(pid), fname))
    e = {"id": "m" + uuid.uuid4().hex[:8], "file": fname, "dir": "models", "orig_name": fname, "bytes": os.path.getsize(os.path.join(_dir(pid), fname)),
         "ext": "stl", "origin": "merged", "variant": "", "added_at": time.time(), "added_by": user, "parts_of": desc,
         **({"parts_sets": int(sets)} if int(sets or 1) > 1 else {})}
    p.setdefault("model_lib", []).append(e)
    e["info"] = analyze(pid, e)
    store.save(p)
    r = filemgr.set_model(pid, os.path.join(_dir(pid), fname), fname, user)
    p = store.load(pid)
    p["model"]["lib_id"] = e["id"]
    p["model"]["parts_of"] = desc
    store.save(p)
    return {"product": p, "replaced": r["replaced"], "files_reset": r["files_reset"], "merged": e}


# ---------------- AI 检查摆盘（空打 / 打飞风险） ----------------
AI_SYSTEM = """你是资深 FDM 3D 打印工程师。用户要把几个零件摆在同一盘一起打印（拓竹 P1S / 创想 K1 系列，0.4 喷嘴）。
根据每个零件在所选摆放方向下的几何数据，判断打印失败的风险，特别是「空打」（零件打飞、脱离平台后喷嘴在空中吐丝、出现炒面）、
翘边、垂丝塌陷、细高件被撞倒、零件之间互相影响。给出风险等级（低 / 中 / 高）、原因和具体可执行的改法
（换哪个方向、开什么支撑、帽檐、降速、温度、要不要分开打）。只输出 JSON，说明同时给中文(zh)和泰文(th)，简短直接。"""


def ai_check(pid, selection, user=""):
    from . import ai_copy
    p = store.load(pid)
    _sync(p)
    rows = []
    for s in selection or []:
        e = _entry(p, s.get("id"))
        info = e.get("info") or {}
        src = info
        name = e["orig_name"]
        if s.get("part") not in (None, ""):
            src = (info.get("parts") or [])[int(s["part"])]
            name = f"{e['orig_name']} / {src.get('name')}"
        orient = s.get("orient") if s.get("orient") in mesh.ORIENT_ZH else "bottom"
        st = next((o for o in src.get("orients") or [] if o["key"] == orient), None)
        if not st:
            continue
        rows.append({"name": name, "qty": int(s.get("qty") or 1), "orient": orient, "orient_zh": mesh.ORIENT_ZH[orient],
                     "size_mm": st.get("size_mm"), "contact_cm2": st.get("contact_cm2"), "overhang_cm2": st.get("overhang_cm2"),
                     "steep_cm2": st.get("steep_cm2"), "height_mm": st.get("height_mm"), "tall_ratio": st.get("tall_ratio"),
                     "best_orient": src.get("best"), "rule_risks": [r["text"] for r in st.get("risks") or []]})
    if not rows:
        raise ValueError("先勾选要一起打的文件或组件")
    import json as _json
    user_msg = ("材料：" + (p.get("material") or "PLA") + "\n零件（摆放方向下的几何数据；contact_cm2=贴平台面积，overhang_cm2=超过45°悬空面积，"
                "tall_ratio=高/最小底边）：\n" + _json.dumps(rows, ensure_ascii=False) +
                '\n\n输出 JSON：{"overall": {"level": "低|中|高", "zh": "整盘结论一两句", "th": "..."}, '
                '"items": [{"name": "零件名", "level": "低|中|高", "risk_zh": "主要风险", "fix_zh": "怎么改", "risk_th": "...", "fix_th": "...", '
                '"suggest_orient": "bottom|top|front|back|left|right 或空"}], "settings_zh": "整盘建议的支撑 / 帽檐 / 速度设置", "settings_th": "..."}')
    data = ai_copy.extract_json(ai_copy.call(ai_copy.tcfg(load_config(), "print_advice"), AI_SYSTEM, user_msg))
    data["checked"] = rows
    return data
