"""文件管理：所有产品的 3D 模型文件、切片文件集中在一个地方查看、下载、替换、删除。

- 模型文件放在 data/products/<编号>/model/，替换时旧文件移到 model_history/（保留最近 5 个，可以下载找回）。
- 切片文件在 data/print_files/（见 print_files.py）。替换 = 上传新版本，旧版本自动停用（不删除，可以恢复）。
- 模型换了以后，这个产品已有的切片文件全部退回「草稿」，提醒重新切片 / 重新复核。
"""
import io
import os
import re
import shutil
import time
import zipfile

import numpy as np

from . import db, print_files, slicer, store
from .config import load_config

KEEP_HISTORY = 5


def _hist_dir(pid):
    d = os.path.join(store.product_dir(pid), "model_history")
    os.makedirs(d, exist_ok=True)
    return d


def model_path(p):
    m = p.get("model")
    if not m:
        return None
    path = os.path.join(store.image_dir(p["id"], "model"), m["file"])
    return path if os.path.exists(path) else None


def metrics(tris):
    """体积、表面积、尺寸（给克数 / 时长估算用，和编辑页里浏览器算的一样）。"""
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    vol = float(abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6.0)
    area = float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2.0)
    p = tris.reshape(-1, 3)
    size = (p.max(0) - p.min(0)).round(2).tolist()
    return {"volume_mm3": round(vol, 1), "area_mm2": round(area, 1), "size": [size[0], size[1], size[2]]}


def set_model(pid, src_path, orig_name, user="", reset_files=True):
    """给产品放（或替换）模型文件：旧的进历史；算体积和估算克数；已有切片文件退回草稿。"""
    ext = os.path.splitext(orig_name or src_path)[1].lower()
    if ext not in (".stl", ".3mf"):
        raise ValueError("只支持 .stl 或 .3mf 模型文件")
    # 读不了会报错，不会把坏文件存进去。大文件交给电脑读（v2.20，core/kernels）
    from . import kernels
    p = store.load(pid)
    summ = kernels.mesh_summary(src_path, p.get("material", "PLA"), loader="mesh", orients=False, parts=False)
    d = store.image_dir(pid, "model")
    replaced = False
    old = p.get("model")
    if old:
        op = os.path.join(d, old["file"])
        if os.path.exists(op):
            ts = time.strftime("%Y%m%d_%H%M%S")
            keep = re.sub(r"[^\w.\-]+", "_", old.get("orig_name") or old["file"], flags=re.ASCII)[-60:]
            shutil.move(op, os.path.join(_hist_dir(pid), f"{ts}__{keep}"))
            replaced = True
    for n in os.listdir(d):
        try:
            os.remove(os.path.join(d, n))
        except OSError:
            pass
    name = "model" + ext
    shutil.copyfile(src_path, os.path.join(d, name))
    hs = sorted(os.listdir(_hist_dir(pid)))
    for n in hs[:-KEEP_HISTORY]:
        os.remove(os.path.join(_hist_dir(pid), n))
    m = summ["metrics"]
    cfg = load_config()
    try:
        est = slicer.estimate(cfg, m, p.get("material", "PLA"))
    except Exception:  # noqa: BLE001
        est = None
    p["model"] = {"file": name, "ext": ext[1:], "orig_name": os.path.basename(orig_name or name)[:120],
                  "uploaded_at": int(time.time()), "uploaded_by": user, "metrics": m, "triangles": summ["triangles"]}
    if est:
        p["model"]["estimate"] = est
    if replaced and p.get("recipe"):
        p["recipe"]["capacity_learned"] = {}     # 模型变了，一盘能放几个要重新学
    store.save(p)
    n_reset = 0
    if replaced and reset_files:
        c = db.conn()
        n_reset = c.execute("UPDATE print_files SET status='draft', note=? WHERE product_id=? AND active=1 AND status!='draft'",
                            (f"模型已更换（{time.strftime('%m-%d %H:%M')}），请重新切片或重新复核", pid)).rowcount
        c.commit()
    from . import preview
    preview.warm(os.path.join(d, name))          # 后台先算好 3D 预览用的精简模型
    return {"product": p, "replaced": replaced, "files_reset": n_reset}


def model_history(pid):
    d = os.path.join(store.product_dir(pid), "model_history")
    if not os.path.isdir(d):
        return []
    out = []
    for n in sorted(os.listdir(d), reverse=True):
        fp = os.path.join(d, n)
        ts, _, orig = n.partition("__")
        out.append({"name": n, "orig_name": orig or n, "size": os.path.getsize(fp), "replaced_at": ts})
    return out


def history_path(pid, name):
    fp = os.path.join(store.product_dir(pid), "model_history", os.path.basename(name))
    return fp if os.path.exists(fp) else None


def restore_model(pid, name, user=""):
    fp = history_path(pid, name)
    if not fp:
        raise ValueError("找不到这个历史文件")
    tmp = os.path.join(store.product_dir(pid), "_restore_" + os.path.basename(name))
    shutil.copyfile(fp, tmp)
    try:
        orig = name.partition("__")[2] or name
        return set_model(pid, tmp, orig, user)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def delete_model(pid):
    p = store.load(pid)
    if p.get("model"):
        fp = model_path(p)
        if fp:
            ts = time.strftime("%Y%m%d_%H%M%S")
            shutil.move(fp, os.path.join(_hist_dir(pid), f"{ts}__{p['model'].get('orig_name') or p['model']['file']}"))
        p["model"] = None
        store.save(p)
    return p


def overview(q="", kind="", status="", printer=""):
    """每个产品一行：模型文件 + 切片文件列表。"""
    q = (q or "").strip().lower()
    files_by = {}
    for f in print_files.list_files(None, full=False):
        files_by.setdefault(f["product_id"], []).append(f)
    rows = []
    tot = {"products": 0, "models": 0, "model_bytes": 0, "slices": 0, "slice_bytes": 0}
    for item in store.list_products():
        try:
            p = store.load(item["id"])
        except Exception:  # noqa: BLE001
            continue
        fs = files_by.pop(p["id"], [])
        if printer:
            fs = [f for f in fs if f["printer"] in (printer, "*")]
        if status:
            fs = [f for f in fs if (f.get("status") or "draft") == status and f.get("active")]
        hay = " ".join([p["id"], p.get("name_zh", ""), (p.get("copy") or {}).get("title_th", ""),
                        " ".join(v.get("sku") or "" for v in p.get("variants") or []),
                        (p.get("model") or {}).get("orig_name", "")] + [f["filename"] for f in fs]).lower()
        if q and q not in hay:
            continue
        mp = model_path(p)
        m = None
        if mp:
            m = dict(p["model"])
            m["size"] = os.path.getsize(mp)
            m["history"] = len(model_history(p["id"]))
        if kind == "nomodel" and m:
            continue
        if kind == "model" and not m:
            continue
        if kind == "noslice" and any(f.get("active") and f.get("status") in ("reviewed", "verified") for f in fs):
            continue
        if kind == "slice" and not fs:
            continue
        if status and not fs:
            continue
        thumb = next((f"/files/{p['id']}/{'out' if im.get('processed') else 'raw'}/{im['file']}"
                      for im in p.get("images", []) if im.get("file")), "")
        slim = [{k: f.get(k) for k in ("id", "filename", "printer", "per_plate", "version", "status", "status_zh", "active",
                                       "size", "created_at", "username", "grams", "hours", "source", "sku", "color", "kind", "note")}
                | {"material": ((f.get("report") or {}).get("params") or {}).get("material")} for f in fs]
        from . import modellib
        rows.append({"id": p["id"], "name_zh": p.get("name_zh", ""), "title_th": (p.get("copy") or {}).get("title_th", ""),
                     "material": p.get("material") or "PLA", "thumb": thumb, "model": m, "slices": slim,
                     "lib_count": modellib.count(p)})
        tot["products"] += 1
        if m:
            tot["models"] += 1
            tot["model_bytes"] += m["size"]
        tot["slices"] += len(slim)
        tot["slice_bytes"] += sum(int(f.get("size") or 0) for f in slim)
    return {"rows": rows, "totals": tot}


def zip_products(pids, include_inactive=False):
    """把几个产品的模型 + 切片文件打成一个 zip（每个产品一个文件夹）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for pid in pids:
            try:
                p = store.load(pid)
            except FileNotFoundError:
                continue
            folder = re.sub(r"[^\w\-]+", "_", f"{p['id']}_{p.get('name_zh', '')}")[:60]
            mp = model_path(p)
            if mp:
                z.write(mp, f"{folder}/model_{p['model'].get('orig_name') or p['model']['file']}")
            # 模型库里的全部文件（选品工具推过来的、自己上传的、合并出来的）
            for d in ("models", "source_files"):
                fd = os.path.join(store.product_dir(pid), d)
                if os.path.isdir(fd):
                    for n in sorted(os.listdir(fd)):
                        if not n.startswith((".", "_")) and os.path.isfile(os.path.join(fd, n)):
                            z.write(os.path.join(fd, n), f"{folder}/模型库/{n}")
            for f in print_files.list_files(pid):
                if not f.get("active") and not include_inactive:
                    continue
                fp = print_files.path_of(f)
                if os.path.exists(fp):
                    z.write(fp, f"{folder}/slice_{f['printer'].replace(' ', '_')}_x{f['per_plate']}_v{f.get('version') or 1}_{f['filename']}")
    buf.seek(0)
    return buf


def match_model_file(filename):
    """批量上传模型：按文件名里的产品编号对应（例如 3DP0001.stl、3DP0001_cat_v2.3mf）。"""
    base = os.path.basename(filename).upper()
    ids = sorted((i["id"] for i in store.list_products()), key=len, reverse=True)
    for pid in ids:
        if re.match(re.escape(pid.upper()) + r"(?![0-9])", base):
            return pid
    return None


def replace_slice(fid, src_path, filename, user=""):
    """切片文件替换：同一个产品 / 打印机 / 一盘数量 / SKU 上传新版本，旧版本停用。"""
    old = print_files.get(fid)
    if not old:
        raise ValueError("文件不存在")
    from . import recipes
    try:
        p = store.load(old["product_id"])
    except FileNotFoundError:
        p = {"material": "PLA"}
    cfg = load_config()
    names = [x.get("name") for x in cfg.get("printers") or []]
    pidx = names.index(old["printer"]) if old["printer"] in names else 0
    new = print_files.add(src_path, filename, old["product_id"], old["printer"], old.get("sku") or "", old["per_plate"],
                          old.get("color") or "", f"替换 v{old.get('version') or 1}", user, p.get("material") or "PLA",
                          move=True, source="upload", bed=recipes.bed_size(pidx))
    rec = recipes.get(p) if p.get("id") else dict(recipes.DEFAULT)
    rec["per_plate"] = new["per_plate"]
    new = print_files.set_checks(new["id"], recipes.check(rec, None, new.get("report"), p.get("material") or "PLA"))
    print_files.update(fid, active=0)
    return new


# ---------------- 上传电脑上切好的文件（自动认打印机、一盘几个） ----------------
def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def detect_printer(params):
    """从切片文件里的打印机配置名认出是哪台打印机（例如「Creality K1 Max (0.4 nozzle)」→ Creality K1 Max）。"""
    prof = _norm((params or {}).get("printer_profile"))
    if not prof:
        return None
    best = None
    for p in load_config().get("printers") or []:
        cands = [_norm(p.get("orca_machine")), _norm(p.get("name"))]
        for c in cands:
            if c and (c == prof or c in prof or prof in c):
                score = len(c) + (100 if c == prof else 0)
                if not best or score > best[0]:
                    best = (score, p.get("name"))
    return best[1] if best else None


def _count_objects(path, kind):
    """一盘几个：3MF 看盘里的零件数；G-code 看 EXCLUDE_OBJECT_DEFINE（Klipper / K1）。"""
    from . import toolpath
    try:
        if kind == "3mf":
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if "Metadata/plate_1.json" in names:
                    import json as _j
                    n = len(_j.loads(z.read("Metadata/plate_1.json")).get("bbox_objects") or [])
                    if n:
                        return n
                if "Metadata/slice_info.config" in names:
                    n = len(re.findall(r"<object ", z.read("Metadata/slice_info.config").decode("utf-8", "ignore")))
                    if n:
                        return n
        text = toolpath.read_gcode(path, kind)
        n = len(set(re.findall(r"^EXCLUDE_OBJECT_DEFINE NAME=(\S+)", text, re.M)))
        if n:
            return n
        n = len(set(re.findall(r"^; printing object (.+)$", text, re.M)))
        return n or None
    except Exception:  # noqa: BLE001
        return None


def _upload_resin(src_path, filename, p, user, printer, per_plate, sku, color, note, hours, ml, spec=None):
    """光固化文件：机型按扩展名 / 唯一的光固化机型认；一盘几个读不出来，没填时先按 1 个（之后在文件卡片里改）。"""
    from . import fleet, resinfile
    cfg = load_config()
    detected = {}
    resin_models = list(dict.fromkeys(x.get("name") for x in cfg.get("printers") or [] if fleet.tech_of(x) == "resin"))
    if not printer or printer == "auto":
        guess = resinfile.model_from_ext(filename)
        printer = guess if guess in resin_models else (resin_models[0] if len(resin_models) == 1 else "*")
        detected["printer"] = printer
    try:
        n = max(1, int(per_plate))
    except (TypeError, ValueError):
        n = 1
        detected["per_plate_unknown"] = True
    grams = None
    try:
        grams = round(float(ml) * float(cfg.get("resin_density") or 1.1), 1) if ml not in (None, "") else None
    except ValueError:
        pass
    try:
        hrs = float(hours) if hours not in (None, "") else None
    except ValueError:
        hrs = None
    r = print_files.add(src_path, filename, p["id"], printer, sku or "", n, color or "", note or "", user,
                        p.get("material") or "RESIN", grams=grams, hours=hrs, move=True, source="upload",
                        spec=slice_spec(p, filename, sku, spec))
    detected["resin"] = (r.get("report") or {}).get("resin") or {}
    if not r.get("hours") or not r.get("grams"):
        detected["need_manual"] = True
    r["detected"] = detected
    return r


def slice_spec(p, filename, sku="", spec=None):
    """v2.22.1：切片文件是哪个规格的。指定了就用；否则按 SKU、再按文件名里出现的规格名认。只有「有自己模型」的规格才单独算，其他 = 主模型（空）。"""
    from . import specmodel
    if spec is None or spec == "auto":
        spec = specmodel.spec_of_sku(p, sku) if sku else ""
        if not spec:
            low = (filename or "").lower()
            hits = [s for s in specmodel.specs(p) if s and s.lower() in low]
            hits.sort(key=len, reverse=True)
            spec = hits[0] if hits else ""
    spec = (spec or "").strip()
    return spec if spec and specmodel.own(p, spec) else ""


def upload_slice(src_path, filename, product_id, user="", printer="auto", per_plate="auto", sku="", color="", note="",
                 hours=None, ml=None, spec=None):
    """上传一个切好的文件：没指定打印机 / 数量时从文件里自动认。返回新文件记录（含 detected 说明）。"""
    from . import recipes
    kind = print_files._kind(filename)
    p = store.load(product_id)
    if kind == "resin":
        return _upload_resin(src_path, filename, p, user, printer, per_plate, sku, color, note, hours, ml, spec)
    params = recipes.params_from(src_path, kind)
    detected = {}
    if printer and printer not in ("auto", "*"):     # v2.32：手动选的机型和文件里写的机型不一样 → 不让上传
        from modules.prod import slicecheck
        fm = slicecheck.model_of_profile(params.get("printer_profile"))
        if fm and _norm(fm) != _norm(printer):
            raise ValueError(f"这是「{fm}」的切片文件，不能登记成「{printer}」用的。请用「{printer}」重新切片，或者选「自动识别」")
    if not printer or printer == "auto":
        printer = detect_printer(params) or "*"
        detected["printer"] = printer
    n = None
    if not per_plate or str(per_plate) == "auto":
        n = _count_objects(src_path, kind) or 1
        detected["per_plate"] = n
    else:
        n = max(1, int(per_plate))
    names = [x.get("name") for x in load_config().get("printers") or []]
    pidx = names.index(printer) if printer in names else 0
    sp = slice_spec(p, filename, sku, spec)
    if sp:
        detected["spec"] = sp
    r = print_files.add(src_path, filename, product_id, printer, sku or "", n, color or "", note or "", user,
                        p.get("material") or "PLA", move=True, source="upload", bed=recipes.bed_size(pidx), spec=sp)
    rec = recipes.get(p)
    rec["per_plate"] = r["per_plate"]
    r = print_files.set_checks(r["id"], recipes.check(rec, None, r.get("report"), p.get("material") or "PLA"))
    r["detected"] = detected
    return r
