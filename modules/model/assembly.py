"""展示模型（给商品页用）：多零件模型「组装好」的样子 —— 用哪些零件、每个几个、每个的位置和旋转。

v2.53：展示和打印完全分开。
- 展示有自己的「零件选择」（模型库里任意文件 / 文件里的组件，带数量，例如 4 条腿），和主模型 / 打印方案无关；
  「合并成一套（设为模型）」只影响打印，不影响展示。
- 每个规格（规格不只是大小：款式、带不带盖、2 个装、不同零件组合…）有自己的展示：零件、数量、组装姿势；
  没设置的规格：有自己模型的用自己的模型，没有的跟着主模型；「按主模型缩放 N%」的规格 = 主模型的展示整体缩放。
- 没有明确选零件、主模型又是「合并出来的」（origin = merged，记着 parts_of）时：自动拆回原来的零件（老产品读取时就这样，不用迁移）。

数据（产品资料 product["display"]）：
  {"v": 2, "specs": {规格（"" = 主模型）: {
      "items": [{"uid", "id": 模型库文件, "part": 组件序号或 None（整个文件）, "qty": 几个}],
      "parts": [{"key": "<uid>.<第几个>", "pos": [x, y, z], "rot": [rx, ry, rz]（度，XYZ 顺序）, "colour", "hidden"}],
      "scale": 百分比（只在「按主模型缩放」的规格上）, "updated_at", "updated_by", "ai": 上次是不是 AI 摆的, "auto": 自动组合的置信度}}}
  v2.52 的旧格式 {"source", "parts": [{"index", ...}]} 读的时候自动转成规格 "" 的这份。
  坐标：Z 朝上，毫米；pos = 零件外框中心的位置。没保存姿势的零件：同一个文件里的组件用文件里原来的位置，其他排成一排。

「自动组合」：按几何形状把零件叠 / 插到一起（mating.py），给置信度；置信度低时可以再用「AI 按图片组装」，
AI 的结果再按几何往下落到贴合（两者结合）。都只是初稿，员工可以手动调。
"""
import base64
import copy
import hashlib
import io
import json
import math
import os
import re
import time
import uuid

import numpy as np

from core import modellib, store
from core.config import load_config

from . import mating

LOW_CONF = 0.6          # 自动组合置信度低于这个：建议用 AI / 手动


# ---------------- 读 / 转换存储 ----------------
def _lib(p):
    return {e["id"]: e for e in p.get("model_lib") or [] if isinstance(e, dict) and e.get("id")}


def _parts_n(e):
    pl = ((e or {}).get("info") or {}).get("parts") or []
    return len(pl) if len(pl) > 1 else 1


def _is_model(pid, e):
    fp = modellib.path_of(pid, e) if e else None
    return bool(fp) and os.path.splitext(fp)[1].lower() in modellib.MODEL_EXT


def _store(p):
    """{规格: 展示}（旧格式转成新的；只在内存里，保存时才写回）。"""
    d = p.get("display")
    if not isinstance(d, dict):
        return {}
    if isinstance(d.get("specs"), dict):
        return copy.deepcopy(d["specs"])
    # v2.52 旧格式：一份，零件来自 source 文件
    lib = _lib(p)
    e = lib.get(d.get("source")) or lib.get((p.get("model") or {}).get("lib_id"))
    if not e:
        return {}
    if e.get("origin") == "merged" and e.get("parts_of"):
        return {"": {"items": _expand(p, e), "parts": [], "updated_at": d.get("updated_at"), "migrated": True}}
    n = _parts_n(e)
    if n > 1:
        items = [{"uid": f"o{i}", "id": e["id"], "part": i, "qty": 1} for i in range(n)]
    else:
        items = [{"uid": "o0", "id": e["id"], "part": None, "qty": 1}]
    parts = []
    for x in d.get("parts") or []:
        try:
            i = int(x.get("index"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(items):
            parts.append({"key": f"{items[i]['uid']}.0", "pos": x.get("pos"), "rot": x.get("rot"),
                          **({"colour": x["colour"]} if x.get("colour") else {}), **({"hidden": True} if x.get("hidden") else {})})
    return {"": {"items": items, "parts": parts, "updated_at": d.get("updated_at"), "updated_by": d.get("updated_by"),
                 "ai": bool(d.get("ai")), "migrated": True}}


def _write(p, st):
    p["display"] = {"v": 2, "specs": st}


def _expand(p, e, mult=1, depth=0):
    """合并出来的模型 → 原来的零件（parts_of；嵌套的合并也拆开）。打印方案合并的一盘出好几套时只要一套。"""
    lib = _lib(p)
    agg = {}
    sets = max(1, int(e.get("parts_sets") or 1))
    for dsc in e.get("parts_of") or []:
        se = lib.get(dsc.get("id"))
        if not se:
            continue
        q = max(1, int(dsc.get("qty") or 1)) * mult
        part = dsc.get("part")
        if part in (None, "") and se.get("origin") == "merged" and se.get("parts_of") and depth < 4:
            for it in _expand(p, se, q, depth + 1):
                k = (it["id"], it["part"])
                agg[k] = agg.get(k, 0) + it["qty"]
            continue
        k = (se["id"], None if part in (None, "") else int(part))
        agg[k] = agg.get(k, 0) + q
    out = []
    for n, ((eid, part), q) in enumerate(agg.items()):
        out.append({"uid": f"m{n}", "id": eid, "part": part, "qty": max(1, int(math.ceil(q / sets))) if depth == 0 else q})
    return out


def _auto_items(p, e):
    """一个模型库文件当展示用的零件：合并出来的拆回原来的零件；多组件的每个组件一件；否则整个文件一件。"""
    if not e:
        return []
    if e.get("origin") == "merged" and e.get("parts_of"):
        items = _expand(p, e)
        if items:
            return items
    n = _parts_n(e)
    if n > 1:
        return [{"uid": f"a{i}", "id": e["id"], "part": i, "qty": 1} for i in range(n)]
    return [{"uid": "a0", "id": e["id"], "part": None, "qty": 1}]


def _main_entry(p):
    lib = _lib(p)
    e = lib.get((p.get("model") or {}).get("lib_id"))
    if e:
        return e
    return next((x for x in lib.values() if (x.get("info") or {}).get("ok") and _is_model(p["id"], x)), None)


def resolve(p, spec=""):
    """这个规格的展示用哪些零件、什么姿势（不读模型文件，快）。
    返回 {"spec", "mode", "items", "poses": {key: pose}, "scale": 倍数, "from": 零件来自哪个规格, "stored": 存的那份}
    mode：explicit 自己选的零件 / merged 主模型是合并出来的，自动拆回零件 / auto 按主模型 / own 按规格自己的模型 /
          inherit 跟着主模型 / scale 按主模型缩放"""
    from core import specmodel
    spec = (spec or "").strip()
    st = _store(p)
    D = st.get(spec) or {}
    if spec and D.get("scale"):
        base = resolve(p, "")
        return dict(base, spec=spec, mode="scale", scale=float(D["scale"]) / 100.0, stored=D, base_mode=base["mode"])
    poses = {x.get("key"): x for x in D.get("parts") or [] if x.get("key")}
    if D.get("items"):
        return {"spec": spec, "mode": "explicit", "items": D["items"], "poses": poses, "scale": 1.0, "from": spec, "stored": D}
    if spec:
        e = specmodel.entry_for(p, spec)
        if e:
            mode = "merged" if e.get("origin") == "merged" and e.get("parts_of") else "own"
            return {"spec": spec, "mode": mode, "items": _auto_items(p, e), "poses": poses, "scale": 1.0, "from": spec, "stored": D}
        base = resolve(p, "")
        return dict(base, spec=spec, mode="inherit", stored=D, base_mode=base["mode"])
    e = _main_entry(p)
    mode = "merged" if e and e.get("origin") == "merged" and e.get("parts_of") else "auto"
    return {"spec": "", "mode": mode, "items": _auto_items(p, e), "poses": poses, "scale": 1.0, "from": "", "stored": D}


def instances(items):
    """[(key, item, 第几个)]"""
    out = []
    for it in items or []:
        for k in range(max(1, int(it.get("qty") or 1))):
            out.append((f"{it['uid']}.{k}", it, k))
    return out


def is_plain(p, r):
    """展示 = 主模型文件本身（没选别的零件、没摆过、没缩放）：3D 预览直接用主模型（快）。"""
    if r["mode"] not in ("auto",) and not (r["mode"] == "inherit" and r.get("base_mode") == "auto"):
        return False
    if r["poses"]:
        return False
    e = _main_entry(p)
    if not e or not all(it["id"] == e["id"] and int(it.get("qty") or 1) == 1 for it in r["items"]):
        return False
    # v2.56（T37）：多个组件的文件不直接用文件本身（文件里是摆盘位置）：要按作者装配 / 平铺图拼
    return len(r["items"]) <= 1


def token(p, r):
    """展示的版本号（3D 预览 / 缩略图缓存用）：零件、姿势、缩放、文件改动时间。"""
    lib = _lib(p)
    mt = []
    for it in r["items"]:
        e = lib.get(it["id"])
        fp = modellib.path_of(p["id"], e) if e else None
        mt.append(round(os.path.getmtime(fp)) if fp else 0)
    raw = json.dumps([r["mode"], r["items"], sorted(r["poses"].items(), key=lambda kv: kv[0]), r.get("scale"), mt], sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()[:10]


def summary(p, spec=""):
    """概览用（不读模型文件）：{mode, parts（显示几个零件）, items, set: 有没有自己设置, scale, plain, token, updated_at}"""
    try:
        r = resolve(p, spec)
    except Exception:  # noqa: BLE001
        return {"mode": "none", "parts": 0, "items": 0, "set": False}
    inst = instances(r["items"])
    hidden = sum(1 for k, _it, _n in inst if (r["poses"].get(k) or {}).get("hidden"))
    D = r.get("stored") or {}
    return {"mode": r["mode"], "parts": len(inst) - hidden, "items": len(r["items"]), "set": bool(D.get("items") or D.get("scale") or D.get("parts")),
            "posed": bool(r["poses"]), "scale": round(r["scale"] * 100) if r["mode"] == "scale" else None,
            "plain": is_plain(p, r), "token": token(p, r), "updated_at": D.get("updated_at"), "ai": bool(D.get("ai")),
            "auto": D.get("auto")}


# ---------------- 零件几何 ----------------
def _file(pid, p, eid):
    e = _lib(p).get(eid)
    if not e:
        raise ValueError("模型库里没有这个文件（可能被删了），刷新一下")
    fp = modellib.path_of(pid, e)
    if not fp or os.path.splitext(fp)[1].lower() not in modellib.MODEL_EXT:
        raise ValueError(f"「{e.get('orig_name') or e['file']}」不能组装（要 STL、3MF 或 OBJ）")
    return e, fp


def piece(pid, p, eid, part):
    """(名字, 三角面（文件里原来的坐标）)。part None = 整个文件。"""
    e, fp = _file(pid, p, eid)
    parts = modellib.load_parts(fp)
    if part in (None, ""):
        if len(parts) == 1:
            return e.get("orig_name") or e["file"], parts[0][1]
        return e.get("orig_name") or e["file"], np.concatenate([t for _n, t in parts])
    i = int(part)
    if not 0 <= i < len(parts):
        raise ValueError(f"「{e.get('orig_name')}」没有第 {i + 1} 个组件")
    return parts[i][0], parts[i][1]


def part_tris(pid, eid, part=None, max_tris=150_000):
    """一个零件的三角面（原来的坐标，给浏览器显示），太多时隔几个取一个。"""
    p = store.load(pid)
    _n, t = piece(pid, p, eid, part)
    t = np.asarray(t, dtype=np.float32)
    if len(t) > max_tris:
        t = t[:: int(math.ceil(len(t) / max_tris))]
    return t


def _geo(pid, p, items):
    """{(id, part): {name, tris, center, size}}"""
    out = {}
    for it in items:
        k = (it["id"], it.get("part"))
        if k in out:
            continue
        name, t = piece(pid, p, it["id"], it.get("part"))
        t = np.asarray(t, dtype=np.float64)
        v = t.reshape(-1, 3)
        mn, mx = v.min(0), v.max(0)
        out[k] = {"name": name, "tris": t, "center": (mn + mx) / 2, "size": mx - mn}
    return out


class _Poses(dict):
    source = "layout"          # author 作者装配 / file 文件里的组装位置 / layout 零件平铺图


_AUTHOR = {}


def author_of(pid, e):
    """v2.56（T37 ①）：3MF 里作者的「装配视图」位置（Bambu Studio / Orca 的 assemble_item），和摆盘位置不同才算。
    返回 {组件序号: (R, t)}（从文件里的摆盘位置到装配位置）或 None。按文件改动时间缓存。"""
    fp = modellib.path_of(pid, e) if e else None
    if not fp or not fp.lower().endswith(".3mf") or not os.path.exists(fp):
        return None
    key = (fp, os.path.getmtime(fp))
    if key not in _AUTHOR:
        from core import mesh
        try:
            with open(fp, "rb") as f:
                d = mesh.assembly_3mf(f.read())
        except Exception:  # noqa: BLE001  读不了就当没有
            d = None
        out = None
        if d and any(x is not None and (np.abs(x[0] - np.eye(3)).max() > 1e-3 or np.abs(x[1]).max() > 0.5) for x in d):
            out = {i: x for i, x in enumerate(d) if x is not None}
        if len(_AUTHOR) > 100:
            _AUTHOR.clear()
        _AUTHOR[key] = out
    return _AUTHOR[key]


def _author_for(pid, p, items):
    """这些展示零件里有作者装配位置的：{(文件, 组件序号): (R, t)}"""
    lib = _lib(p)
    out = {}
    for it in items or []:
        if it.get("part") in (None, ""):
            continue
        a = author_of(pid, lib.get(it["id"]))
        if a and int(it["part"]) in a:
            out[(it["id"], int(it["part"]))] = a[int(it["part"])]
    return out


def _bbox_overlap(geo, keys):
    """文件里原来的位置不像摆盘（零件有的悬空 / 俯视外框互相重叠很多）→ 文件里本来就是组装好的样子。
    摆盘的零件都放在热床上（最低点 z≈0）、互相不重叠。"""
    bs = [(geo[k]["center"] - geo[k]["size"] / 2, geo[k]["center"] + geo[k]["size"] / 2) for k in keys]
    if any(float(lo[2]) > 1.0 for lo, _hi in bs):
        return True
    for i in range(len(bs)):
        for j in range(i + 1, len(bs)):
            d = np.minimum(bs[i][1], bs[j][1])[:2] - np.maximum(bs[i][0], bs[j][0])[:2]
            if (d > 0).all():
                small = min(float(np.prod(np.maximum(bs[i][1] - bs[i][0], 1e-6)[:2])), float(np.prod(np.maximum(bs[j][1] - bs[j][0], 1e-6)[:2])))
                if float(np.prod(d)) > 0.2 * small:
                    return True
    return False


def _default_poses(items, geo, author=None):
    """没保存姿势时（v2.56 T37 ③：不再默认显示几何 / AI 猜的组装）：
    1. 作者装配（3MF 的装配视图位置）→ 直接用（最高优先）
    2. 同一个文件里的不同组件、文件里的位置零件互相穿插（本来就是组装好的）→ 文件里的位置
    3. 其它 → 零件平铺图（整齐排开，底面放地上；界面上带零件名）"""
    from . import mating as _m
    inst = instances(items)
    out = _Poses()
    if author and all((it["id"], it.get("part")) in author for _k, it, _n in inst):
        for k, it, _n in inst:
            g = geo[(it["id"], it.get("part"))]
            R, t = author[(it["id"], it.get("part"))]
            c = np.asarray(g["center"], dtype=np.float64)
            out[k] = {"pos": [round(float(x), 2) for x in c @ R + t], "rot": [round(float(x), 2) for x in _m.euler_of(R.T)]}
        out.source = "author"
        return out
    same = len({it["id"] for _k, it, _n in inst}) == 1 and all(int(it.get("qty") or 1) == 1 for it in items) \
        and len({it.get("part") for it in items}) == len(items)
    if same and len(inst) > 1 and _bbox_overlap(geo, [(it["id"], it.get("part")) for _k, it, _n in inst]):
        for k, it, _n in inst:
            g = geo[(it["id"], it.get("part"))]
            out[k] = {"pos": [round(float(x), 2) for x in g["center"]], "rot": [0.0, 0.0, 0.0]}
        out.source = "file"
        return out
    # 零件平铺图：按网格排开（每行约 √n 个），零件之间留 8 mm
    sizes = [geo[(it["id"], it.get("part"))]["size"] for _k, it, _n in inst]
    n = len(inst)
    cols = max(1, int(math.ceil(math.sqrt(n))))
    rows = [list(range(i, min(n, i + cols))) for i in range(0, n, cols)]
    gap = 8.0
    y = 0.0
    depth_total = sum(max(float(sizes[i][1]) for i in r) for r in rows) + gap * max(0, len(rows) - 1)
    y = depth_total / 2
    for r in rows:
        dmax = max(float(sizes[i][1]) for i in r)
        width = sum(float(sizes[i][0]) for i in r) + gap * (len(r) - 1)
        x = -width / 2
        for i in r:
            k = inst[i][0]
            s_ = sizes[i]
            out[k] = {"pos": [round(x + float(s_[0]) / 2, 3), round(y - dmax / 2, 3), round(float(s_[2]) / 2, 3)], "rot": [0.0, 0.0, 0.0]}
            x += float(s_[0]) + gap
        y -= dmax + gap
    out.source = "layout"
    return out


def _library(p, pid):
    main = (p.get("model") or {}).get("lib_id")
    out = []
    for e in p.get("model_lib") or []:
        info = e.get("info") or {}
        if not info.get("ok") or not _is_model(pid, e):
            continue
        out.append({"id": e["id"], "name": e.get("orig_name") or e["file"], "merged": e.get("origin") == "merged", "main": e["id"] == main,
                    "variant": e.get("variant") or "", "size": info.get("size"), "thumb": bool(info.get("thumb")),
                    "parts": [{"index": x.get("index"), "name": x.get("name"), "size": x.get("size")} for x in info.get("parts") or []]
                    if len(info.get("parts") or []) > 1 else []})
    return out


def get(pid, spec=""):
    p = store.load(pid)
    if modellib._sync(p):
        store.save(p)
    r = resolve(p, spec)
    if not r["items"]:
        raise ValueError("还没有模型文件（先上传 3D 模型）")
    geo = _geo(pid, p, r["items"])
    dflt = _default_poses(r["items"], geo, _author_for(pid, p, r["items"]))
    rows = []
    lib = _lib(p)
    for n, (k, it, _i) in enumerate(instances(r["items"])):
        g = geo[(it["id"], it.get("part"))]
        q = r["poses"].get(k) or {}
        d = dflt[k]
        rows.append({"index": n, "key": k, "uid": it["uid"], "id": it["id"], "part": it.get("part"), "name": g["name"],
                     "file": (lib.get(it["id"]) or {}).get("orig_name") or "",
                     "size": [round(float(x), 1) for x in g["size"]], "center": [round(float(x), 2) for x in g["center"]],
                     "pos": q.get("pos") or d["pos"], "rot": q.get("rot") or d["rot"], "colour": q.get("colour") or "",
                     "hidden": bool(q.get("hidden")), "saved": bool(q)})
    D = r.get("stored") or {}
    first = lib.get(r["items"][0]["id"]) or {}
    from core import specmodel
    return {"spec": r["spec"], "mode": r["mode"], "scale": round(r["scale"] * 100) if r["mode"] == "scale" else None,
            "items": r["items"], "parts": rows, "library": _library(p, pid), "specs": specmodel.specs(p),
            "has_pose": bool(r["poses"]), "plain": is_plain(p, r), "token": token(p, r),
            "updated_at": D.get("updated_at"), "updated_by": D.get("updated_by"), "ai": bool(D.get("ai")), "auto": D.get("auto"),
            "source": first.get("id"), "source_name": first.get("orig_name") or first.get("file") or "",
            "main_merged": bool((_main_entry(p) or {}).get("origin") == "merged"),
            # v2.56（T37）：没保存过姿势时显示的是什么：author 作者装配 / file 文件里的组装位置 / layout 零件平铺图
            "default_source": dflt.source, "saved_pose": bool(r["poses"])}


# ---------------- 保存 ----------------
def _vec(v, n=3, lim=5000):
    out = []
    for x in (v or [])[:n]:
        try:
            f = float(x)
        except (TypeError, ValueError):
            f = 0.0
        if not math.isfinite(f):
            f = 0.0
        out.append(round(max(-lim, min(lim, f)), 3))
    return out + [0.0] * (n - len(out))


def _check_spec(p, spec):
    from core import specmodel
    if spec and spec not in specmodel.specs(p):
        raise ValueError(f"这个产品没有规格「{spec}」")


def clean_items(p, items):
    lib = _lib(p)
    out, seen = [], set()
    for it in (items or [])[:60]:
        e = lib.get(it.get("id"))
        if not e:
            raise ValueError("选的零件里有模型库里没有的文件（可能被删了），刷新一下")
        if not _is_model(p["id"], e):
            raise ValueError(f"「{e.get('orig_name')}」不能组装（要 STL、3MF 或 OBJ）")
        part = it.get("part")
        part = None if part in (None, "") else int(part)
        if part is not None and not 0 <= part < max(_parts_n(e), 1):
            raise ValueError(f"「{e.get('orig_name')}」没有第 {part + 1} 个组件")
        try:
            qty = max(1, min(50, int(it.get("qty") or 1)))
        except (TypeError, ValueError):
            qty = 1
        uid = re.sub(r"[^\w]", "", str(it.get("uid") or ""))[:10] or ("u" + uuid.uuid4().hex[:6])
        while uid in seen:
            uid = "u" + uuid.uuid4().hex[:6]
        seen.add(uid)
        out.append({"uid": uid, "id": e["id"], "part": part, "qty": qty})
    if sum(x["qty"] for x in out) > 120:
        raise ValueError("展示最多 120 个零件")
    return out


def save(pid, data, user="", spec=None):
    """保存这个规格的展示：data = {"items"（可以不传 = 现在的零件）, "parts": [{key 或 index, pos, rot, colour, hidden}], "ai", "auto"}"""
    p = store.load(pid)
    modellib._sync(p)
    spec = ((data.get("spec") if spec is None else spec) or "").strip()
    _check_spec(p, spec)
    r = resolve(p, spec)
    if r["mode"] == "scale" and data.get("items") is None:
        raise ValueError("这个规格是「按主模型缩放」的，展示跟着主模型；要单独改先取消缩放")
    items = clean_items(p, data["items"]) if data.get("items") is not None else clean_items(p, r["items"])
    if not items:
        raise ValueError("至少选一个零件")
    inst = instances(items)
    keys = {k for k, _it, _n in inst}
    rows = []
    for x in data.get("parts") or []:
        k = x.get("key")
        if not k and x.get("index") not in (None, ""):
            try:
                i = int(x["index"])
            except (TypeError, ValueError):
                continue
            k = inst[i][0] if 0 <= i < len(inst) else None
        if k not in keys:
            continue
        rows.append({"key": k, "pos": _vec(x.get("pos")), "rot": [((v + 180) % 360) - 180 for v in _vec(x.get("rot"), lim=100000)],
                     **({"colour": str(x["colour"])[:30]} if x.get("colour") else {}), **({"hidden": True} if x.get("hidden") else {})})
    st = _store(p)
    auto = data.get("auto")
    st[spec] = {"items": items, "parts": rows, "updated_at": time.time(), "updated_by": user, "ai": bool(data.get("ai")),
                **({"auto": {"conf": float(auto.get("conf") or 0)}} if isinstance(auto, dict) else {})}
    _write(p, st)
    store.save(p)
    return get(pid, spec)


def reset(pid, user="", spec=""):
    """这个规格回到默认（主模型：按主模型、合并的自动拆回零件；规格：自己的模型或跟着主模型）。"""
    p = store.load(pid)
    st = _store(p)
    st.pop((spec or "").strip(), None)
    _write(p, st)
    store.save(p)
    return get(pid, spec)


def copy_from(pid, spec, src, user=""):
    """「从某个规格复制」：零件、数量、姿势一起复制过来，再自己改。"""
    p = store.load(pid)
    spec, src = (spec or "").strip(), (src or "").strip()
    _check_spec(p, spec)
    _check_spec(p, src)
    if spec == src:
        raise ValueError("不能从自己复制")
    r = resolve(p, src)
    if not r["items"]:
        raise ValueError("那个规格还没有展示零件")
    st = _store(p)
    st[spec] = {"items": copy.deepcopy(r["items"]), "parts": [dict(v, key=k) for k, v in r["poses"].items()],
                "updated_at": time.time(), "updated_by": user, "copied_from": src}
    _write(p, st)
    store.save(p)
    return get(pid, spec)


def set_scale(pid, spec, pct, user=""):
    """展示：「按主模型缩放 N%」（pct 空 / 0 = 取消）。打印方案那边由 printplan.set_scale 一起改。"""
    p = store.load(pid)
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("主模型不能按自己缩放")
    _check_spec(p, spec)
    st = _store(p)
    if pct:
        pct = float(pct)
        if not 5 <= pct <= 1000:
            raise ValueError("缩放要在 5% 到 1000% 之间")
        st[spec] = {"scale": round(pct, 1), "updated_at": time.time(), "updated_by": user}
    else:
        D = st.get(spec) or {}
        D.pop("scale", None)
        if D.get("items"):
            st[spec] = D
        else:
            st.pop(spec, None)
    _write(p, st)
    store.save(p)
    return get(pid, spec)


# ---------------- 组装好的整体 ----------------
def assembled_tris(pid, spec=""):
    """按展示（零件 + 姿势 + 缩放）拼好的整个模型，给 3D 预览 / 商品图用。展示就是主模型文件本身时返回 None（直接用主模型）。"""
    p = store.load(pid)
    r = resolve(p, spec)
    if not r["items"] or is_plain(p, r):
        return None
    return _assemble(pid, p, r)


def _assemble(pid, p, r, poses=None, offsets=None):
    geo = _geo(pid, p, r["items"])
    poses = poses if poses is not None else r["poses"]
    dflt = _default_poses(r["items"], geo, _author_for(pid, p, r["items"]))
    out = []
    for k, it, _n in instances(r["items"]):
        q = poses.get(k) or {}
        if q.get("hidden"):
            continue
        g = geo[(it["id"], it.get("part"))]
        pos = np.array(q.get("pos") or dflt[k]["pos"], dtype=np.float64)
        if offsets and k in offsets:
            pos = pos + np.array(offsets[k])
        out.append(mating.posed(g["tris"], g["center"], pos, q.get("rot") or dflt[k]["rot"]))
    if not out:
        return None
    t = np.concatenate(out)
    v = t.reshape(-1, 3)
    mn, mx = v.min(0), v.max(0)
    t = t - np.array([(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]])
    if r.get("scale") and abs(r["scale"] - 1) > 1e-6:
        t = t * float(r["scale"])
    return t


_THUMB_LOCK = {}


def thumb_path(pid, spec=""):
    """展示的缩略图（服务器画，按版本缓存）。没有零件时 None。"""
    p = store.load(pid)
    r = resolve(p, spec)
    if not r["items"]:
        return None
    tok = token(p, r)
    tag = hashlib.md5((spec or "").encode()).hexdigest()[:6]
    d = os.path.join(store.product_dir(pid), "models")
    os.makedirs(d, exist_ok=True)
    fp = os.path.join(d, f"_disp_{tag}_{tok}.png")
    if os.path.exists(fp):
        return fp
    t = _assemble(pid, p, r)
    if t is None:
        return None
    for n in os.listdir(d):
        if n.startswith(f"_disp_{tag}_"):
            try:
                os.remove(os.path.join(d, n))
            except OSError:
                pass
    modellib.render_thumb(t, fp, px=200)
    return fp


# ---------------- 自动选零件 ----------------
_SKIP = re.compile(r"support|brim|test|calib|spare|backup|支撑|测试|校准|备用|ซัพพอร์ต|ทดสอบ|สำรอง", re.I)
_QTY = [re.compile(r"(?:^|[\s_\-(\[])(?:x|×)\s?(\d{1,2})[)\]]?$", re.I), re.compile(r"^(\d{1,2})\s?(?:x|×|pcs|pc)[\s_\-]", re.I),
        re.compile(r"[\s_\-(\[](\d{1,2})\s?(?:pcs|pc|个|只|件|ชิ้น)[)\]]?$", re.I)]
_PACK = re.compile(r"(\d{1,2})\s*(?:个装|件装|只装|入|pcs|pack|ชิ้น|ชุด)|(?:pack of|x|×)\s*(\d{1,2})$|^(\d{1,2})\s*(?:x|×)$", re.I)
_NO = re.compile(r"(?:无|不带|没有|without|no\s|ไม่มี)\s*([^\s,，、]+)", re.I)
_SYN = {"盖": r"lid|cap|cover|top|盖|ฝา", "lid": r"lid|cap|cover|盖|ฝา", "ฝา": r"lid|cap|cover|盖|ฝา", "cap": r"lid|cap|cover|盖|ฝา",
        "底座": r"base|stand|底座|ฐาน", "base": r"base|stand|底座|ฐาน", "ฐาน": r"base|stand|底座|ฐาน",
        "头": r"head|头|หัว", "head": r"head|头|หัว"}


def _stem(name):
    n = str(name or "").split(" / ")[-1]
    return re.sub(r"\.(stl|3mf|obj)$", "", n, flags=re.I).strip()


def name_qty(name):
    """零件名里的数量：leg_x4、4x leg、leg (4pcs) → 4；没有 → 1。"""
    s = _stem(name)
    for rx in _QTY:
        m = rx.search(s)
        if m:
            q = int(m.group(1))
            if 1 <= q <= 20:
                return q
    return 1


def _norm(s):
    s = str(s or "").lower().replace("×", "x").replace("*", "x")
    s = re.sub(r"\.(stl|3mf|obj|step)$", "", s)
    return re.sub(r"[\s_\-]+", "", s)


def auto_select(pid, spec=""):
    """「自动选零件」：按规格对应的模型、文件 / 零件名选一套展示零件（不保存）。
    规格有自己的模型 → 用它（合并出来的拆回零件）；文件名 / 零件名里有规格名 → 用那些；否则按主模型。
    零件名里的数量（x4）、规格名里的「2 个装」、「无盖」（去掉盖子）、支撑 / 测试件不要。返回 {items, note_zh, note_th}。"""
    from core import specmodel
    p = store.load(pid)
    if modellib._sync(p):
        store.save(p)
    spec = (spec or "").strip()
    lib = _lib(p)
    files = [e for e in lib.values() if (e.get("info") or {}).get("ok") and _is_model(pid, e)]
    why_zh, why_th = "", ""
    items = []
    e = specmodel.entry_for(p, spec) if spec else None
    if e:
        items = _auto_items(p, e)
        why_zh, why_th = f"按规格「{spec}」对应的模型「{e.get('orig_name')}」", f"ตามโมเดลของแบบ「{spec}」"
    if not items and spec:
        key = _norm(spec)
        pat = re.compile(r"(?<![0-9.])" + re.escape(key) + r"(?![0-9])") if key else None
        if pat:
            for f in files:
                if f.get("origin") == "merged":
                    continue
                if pat.search(_norm(f.get("orig_name"))) or (f.get("variant") or "") == spec:
                    items += _auto_items(p, f)
                    continue
                for x in ((f.get("info") or {}).get("parts") or []) if _parts_n(f) > 1 else []:
                    if pat.search(_norm(x.get("name"))):
                        items.append({"uid": "", "id": f["id"], "part": x["index"], "qty": 1})
        if items:
            why_zh, why_th = f"文件名 / 零件名里有「{spec}」", f"ชื่อไฟล์ / ชิ้นงานมี「{spec}」"
    if not items:
        me = _main_entry(p)
        items = _auto_items(p, me)
        if me and me.get("origin") == "merged":
            why_zh, why_th = "主模型是合并出来的打印盘：拆回原来的零件", "โมเดลหลักเป็นถาดที่รวมไว้: แยกกลับเป็นชิ้นเดิม"
        elif me:
            why_zh, why_th = f"按主模型「{me.get('orig_name')}」", "ตามโมเดลหลัก"
    # 零件名：去掉支撑 / 测试件、读数量
    names = {}
    for it in items:
        f = lib.get(it["id"]) or {}
        if it.get("part") is None:
            names[id(it)] = f.get("orig_name") or ""
        else:
            pl = (f.get("info") or {}).get("parts") or []
            names[id(it)] = next((x.get("name") for x in pl if x.get("index") == it["part"]), "") or ""
    kept = [it for it in items if not _SKIP.search(names[id(it)])] or items
    if len(kept) < len(items):
        why_zh += f"；去掉 {len(items) - len(kept)} 个支撑 / 测试件"
        why_th += f" ตัดชิ้นซัพพอร์ต/ทดสอบ {len(items) - len(kept)} ชิ้น"
    items = kept
    for it in items:
        q = name_qty(names[id(it)])
        if q > 1 and int(it.get("qty") or 1) == 1:
            it["qty"] = q
    # 规格名：「无盖」→ 去掉盖子；「2 个装」→ 数量 × 2
    m = _NO.search(spec)
    if m:
        w = m.group(1).lower()
        rx = re.compile(_SYN.get(w, re.escape(w)), re.I)
        left = [it for it in items if not rx.search(names[id(it)])]
        if left and len(left) < len(items):
            why_zh += f"；规格是「{spec}」：去掉 {len(items) - len(left)} 个"
            why_th += f" แบบ「{spec}」: เอาออก {len(items) - len(left)} ชิ้น"
            items = left
    m = _PACK.search(spec)
    if m:
        k = int(next(g for g in m.groups() if g))
        if 2 <= k <= 10:
            for it in items:
                it["qty"] = int(it.get("qty") or 1) * k
            why_zh += f"；「{spec}」= {k} 套"
            why_th += f" 「{spec}」= {k} ชุด"
    for n, it in enumerate(items):
        it["uid"] = f"s{n}"
    return {"items": clean_items(p, items) if items else [], "note_zh": why_zh.strip("；"), "note_th": why_th.strip()}


# ---------------- 自动组合（几何）/ 沉降 / 爆炸图 ----------------
def _draft(pid, spec, items=None, poses=None):
    p = store.load(pid)
    r = resolve(p, spec)
    if items is not None:
        r = dict(r, items=clean_items(p, items), poses={})
    if poses is not None:
        r["poses"] = {x["key"]: x for x in poses if x.get("key")}
    return p, r


def auto_assemble(pid, spec="", items=None, poses=None):
    """按几何形状自动组合（不保存）：返回 {parts: [{key, index, pos, rot}], confidence, low, steps, note_zh, note_th}。"""
    p, r = _draft(pid, spec, items, poses)
    inst = instances(r["items"])
    if len(inst) < 2:
        raise ValueError("只有一个零件，不用组合")
    if len(inst) > 30:
        raise ValueError("零件太多（超过 30 个），自动组合只做 30 个以内；请手动摆")
    geo = _geo(pid, p, r["items"])
    hidden = {k for k, _it, _n in inst if (r["poses"].get(k) or {}).get("hidden")}
    parts = [{"key": k, "name": geo[(it["id"], it.get("part"))]["name"], "tris": geo[(it["id"], it.get("part"))]["tris"],
              "shape": f"{it['id']}/{it.get('part')}"} for k, it, _n in inst if k not in hidden]
    res = mating.auto_assemble(parts)
    order = {k: i for i, (k, _it, _n) in enumerate(inst)}
    rows = [{"key": k, "index": order[k], **v} for k, v in res["poses"].items()]
    rows.sort(key=lambda x: x["index"])
    conf = res["confidence"]
    low = conf < LOW_CONF
    if low:
        nz = f"自动组合置信度低（{round(conf * 100)}%）：零件之间没找到明显的贴合 / 插接结构，建议再用「AI 按图片组装」或手动调整"
        nt = f"ความมั่นใจต่ำ ({round(conf * 100)}%): ไม่พบจุดต่อที่ชัดเจน แนะนำใช้ AI ประกอบตามรูป หรือปรับเอง"
    else:
        nz = f"按形状自动组合，置信度 {round(conf * 100)}%（盖子 / 插销对上了），可以再手动微调"
        nt = f"ประกอบอัตโนมัติตามรูปทรง ความมั่นใจ {round(conf * 100)}% ปรับเพิ่มเองได้"
    return {"parts": rows, "confidence": conf, "low": low, "steps": res["steps"], "base": res["base"], "note_zh": nz, "note_th": nt}


def settle(pid, spec, items, poses):
    """姿势（例如 AI 初稿）里每个零件往下落到贴着下面的零件 / 地面。返回 [{key, pos, rot}]。"""
    p, r = _draft(pid, spec, items, poses)
    geo = _geo(pid, p, r["items"])
    parts = [{"key": k, "tris": geo[(it["id"], it.get("part"))]["tris"], "center": geo[(it["id"], it.get("part"))]["center"]}
             for k, it, _n in instances(r["items"]) if not (r["poses"].get(k) or {}).get("hidden")]
    pz = {k: {"pos": v.get("pos"), "rot": v.get("rot")} for k, v in r["poses"].items()}
    out = mating.settle(parts, pz)
    return [{"key": k, **v} for k, v in out.items()]


def explode(pid, spec="", items=None, poses=None, factor=1.0):
    """爆炸图：每个零件要挪多少（沿组装方向拉开），{key: [dx, dy, dz]}。没传姿势用保存的 / 默认的。"""
    p, r = _draft(pid, spec, items, poses)
    geo = _geo(pid, p, r["items"])
    dflt = _default_poses(r["items"], geo, _author_for(pid, p, r["items"]))
    parts, pz = [], {}
    for k, it, _n in instances(r["items"]):
        q = r["poses"].get(k) or {}
        if q.get("hidden"):
            continue
        g = geo[(it["id"], it.get("part"))]
        parts.append({"key": k, "tris": g["tris"], "center": g["center"]})
        pz[k] = {"pos": q.get("pos") or dflt[k]["pos"], "rot": q.get("rot") or dflt[k]["rot"]}
    return mating.explode(parts, pz, factor)


# ---------------- AI 按图片组装 ----------------
AI_SYSTEM = """你是 3D 打印产品的装配工程师。用户有一个分成几个零件打印的产品，要在网店里展示「组装好」的样子。
你会看到一张对照图：左边（或第一格）是商品主图（组装好的实物照片），后面每一格是一个零件从几个角度的渲染图（格子上写着零件编号）。
再给你每个零件的外框尺寸（毫米）。请判断每个零件在组装好的产品里的位置和朝向。
坐标系：Z 朝上，单位毫米，原点在组装好的整个产品底面中心；pos = 零件外框中心的位置；rot = 绕 X、Y、Z 轴依次旋转的角度（度，XYZ 顺序），
零件的「原始朝向」就是渲染图里的样子。零件之间要贴合，不要互相穿插、不要悬空。只输出 JSON。"""


def _sheet(product_img, renders):
    """拼一张对照图：商品主图 + 每个零件的几张渲染图（每行一个零件，左边写编号）。返回 JPEG base64。"""
    from PIL import Image, ImageDraw
    cell = 220
    rows = []
    for idx in sorted(renders, key=lambda k: int(k)):
        ims = []
        for u in renders[idx][:4]:
            try:
                raw = base64.b64decode(u.split(",", 1)[1] if "," in u else u)
                ims.append(Image.open(io.BytesIO(raw)).convert("RGB"))
            except Exception:  # noqa: BLE001
                continue
        if ims:
            rows.append((int(idx), ims))
    if not rows:
        raise ValueError("没有零件的渲染图")
    cols = max(len(r[1]) for r in rows)
    left = 0
    prod = None
    if product_img is not None:
        prod = product_img.convert("RGB")
        prod.thumbnail((cell * 2, cell * 2))
        left = cell * 2 + 20
    W = left + 60 + cols * cell
    H = max(len(rows) * cell, prod.size[1] if prod else 0) + 30
    sheet = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    if prod:
        sheet.paste(prod, (0, 30))
        d.text((4, 6), "PRODUCT PHOTO", fill=(200, 0, 0))
    for r, (idx, ims) in enumerate(rows):
        y = 30 + r * cell
        d.text((left + 4, y + cell // 2), f"PART {idx}", fill=(0, 0, 200))
        for c, im in enumerate(ims):
            im = im.copy()
            im.thumbnail((cell - 8, cell - 8))
            sheet.paste(im, (left + 60 + c * cell + 4, y + 4))
    if W > 1800:
        sheet.thumbnail((1800, 1800))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _main_image(p):
    """商品主图（第 1 张；处理过的在 out/，原图在 raw/）。"""
    from PIL import Image
    for x in p.get("images") or []:
        if not isinstance(x, dict):
            continue
        for sub, key in (("out", "file"), ("raw", "raw"), ("raw", "file")):
            name = x.get(key)
            fp = os.path.join(store.product_dir(p["id"]), sub, os.path.basename(str(name))) if name else ""
            if fp and os.path.exists(fp):
                try:
                    return Image.open(fp)
                except Exception:  # noqa: BLE001
                    return None
        break
    return None


def ai_assemble(pid, renders, user="", product_image=None, spec="", items=None, snap=True):
    """renders = {零件序号: [dataURL...]}（浏览器画好的几个角度）。返回 {parts: [{index, key, pos, rot}], note, has_photo}（不保存）。
    snap：AI 的位置再按几何往下落到贴合（AI + 几何结合）。"""
    from core import ai_copy
    cfg = load_config()
    from core import ai
    ok, why = ai.can(cfg, "assembly", "vision")
    if not ok:
        raise ValueError(f"「AI 按图片组装」用不了：{why}。也可以直接用鼠标拖动零件组装，或者用「自动组合」")
    p, r = _draft(pid, spec, items)
    inst = instances(r["items"])
    if len(inst) < 2:
        raise ValueError("这个模型只有一个零件，不用组装")
    geo = _geo(pid, p, r["items"])
    img = None
    if product_image:
        try:
            from PIL import Image
            raw = base64.b64decode(product_image.split(",", 1)[1] if "," in product_image else product_image)
            img = Image.open(io.BytesIO(raw))
        except Exception:  # noqa: BLE001
            img = None
    if img is None:
        img = _main_image(p)
    sheet = _sheet(img, renders or {})
    info = [{"index": i, "name": geo[(it["id"], it.get("part"))]["name"],
             "size_mm": [round(float(x), 1) for x in geo[(it["id"], it.get("part"))]["size"]]} for i, (_k, it, _n) in enumerate(inst)]
    user_msg = ("产品：" + (p.get("name_zh") or p["id"]) + ("" if img is not None else "（没有商品主图，按常识组装）") +
                "\n零件（外框尺寸 = X 宽 × Y 深 × Z 高，毫米，是渲染图里的原始朝向）：\n" + json.dumps(info, ensure_ascii=False) +
                '\n\n输出 JSON：{"parts": [{"index": 0, "pos": [x, y, z], "rot": [rx, ry, rz]}], "note_zh": "一句话说明", "note_th": "..."}')
    data = ai_copy.extract_json(ai_copy.call(ai_copy.tcfg(cfg, "assembly"), AI_SYSTEM, user_msg, image_b64=sheet))
    out = []
    n = len(inst)
    for x in data.get("parts") or []:
        try:
            i = int(x.get("index"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < n:
            out.append({"index": i, "key": inst[i][0], "pos": _vec(x.get("pos")), "rot": _vec(x.get("rot"), lim=720)})
    if not out:
        raise ValueError("AI 没有给出零件位置，请重试或手动组装")
    snapped = False
    if snap:
        try:
            parts = [{"key": k, "tris": geo[(it["id"], it.get("part"))]["tris"], "center": geo[(it["id"], it.get("part"))]["center"]}
                     for k, it, _n in inst]
            st = mating.settle(parts, {x["key"]: {"pos": x["pos"], "rot": x["rot"]} for x in out})
            for x in out:
                if x["key"] in st:
                    x["pos"] = [round(float(v), 3) for v in st[x["key"]]["pos"]]
            snapped = True
        except Exception:  # noqa: BLE001  落不下去就用 AI 原来的
            snapped = False
    return {"parts": out, "note_zh": str(data.get("note_zh") or "")[:300], "note_th": str(data.get("note_th") or "")[:300],
            "has_photo": img is not None, "snapped": snapped}
