"""参考图库：每个产品 / SKU 用来比对的特征。

参考图从哪来（每个产品一个文件 data/recog/refs/<产品编号>.npz，产品改了自动重算）：
  img     产品图（data/products/<编号>/out 或 raw）：按图片的颜色 / 规格的图片对到 SKU，对不上算整个产品的
  render  3D 模型从 17 个角度画出来（服务器画，见 render.py），每个颜色的规格各上一次色
  photo   员工拍照识别后点了「就是它」的照片（data/recog/learned/<编号>/）：系统越用越准
展示用的小图：每个 SKU 一张（有产品图用产品图，没有就用 3D 画的正面图），给手机上的结果和 AI 看。

对外：ensure(pid) / build_all(force) 后台建；index() 内存里的总表；add_photo(pid, sku, 图) 学习；status()。
"""
import hashlib
import io
import json
import os
import shutil
import threading
import time

import numpy as np
from PIL import Image

from core import codes, store
from core.config import DATA_DIR, load_config

from . import descriptor as D
from . import render

ROOT = os.path.join(DATA_DIR, "recog")
REF_DIR = os.path.join(ROOT, "refs")
DISP_DIR = os.path.join(ROOT, "disp")
LEARN_DIR = os.path.join(ROOT, "learned")
MAX_IMGS = 16
MAX_LEARN = 24             # 每个 SKU 最多留几张员工确认过的照片（多了删最老的）
NO_COLOR = ("RND", "MC", "RB")      # 随机 / 多色 / 彩虹：3D 图上不了准确的颜色
_lock = threading.RLock()
_idx = {"key": None, "vecs": np.zeros((0, D.DIM), np.float32), "meta": [], "colw": np.zeros(0, np.float32)}
JOB = {"running": False, "done": 0, "total": 0, "error": "", "started": 0, "finished": 0, "current": ""}


def _dirs():
    for d in (REF_DIR, DISP_DIR, LEARN_DIR):
        os.makedirs(d, exist_ok=True)


def _model_path(p):
    try:
        from core import filemgr
        fp = filemgr.model_path(p)
        if fp:
            return fp
    except Exception:  # noqa: BLE001
        pass
    try:
        from core import modellib
        cur = (p.get("model") or {}).get("lib_id")
        e = next((x for x in p.get("model_lib") or [] if x.get("id") == cur), None)
        return modellib.path_of(p["id"], e) if e else None
    except Exception:  # noqa: BLE001
        return None


def _img_path(pid, img):
    for kind, name in (("out", img.get("file")), ("raw", img.get("raw") or img.get("file"))):
        if not name:
            continue
        fp = os.path.join(store.product_dir(pid), kind, os.path.basename(name))
        if os.path.isfile(fp):
            return fp
    return None


def _learned(pid):
    d = os.path.join(LEARN_DIR, store.safe_id(pid))
    if not os.path.isdir(d):
        return []
    out = []
    for n in sorted(os.listdir(d)):
        if n.endswith(".jpg") and "__" in n:
            out.append((n.split("__")[0], os.path.join(d, n)))
    return out


def _color_rgb(cfg, name):
    row = codes.find_color(cfg, name) if name else None
    if not row or row[1] in NO_COLOR:
        return None, None
    hexes = codes.color_hex(cfg)
    return row[1], render.hex_rgb((hexes.get(row[0]) or {}).get("hex") or codes.COLOR_HEX.get(row[1]))


def _signature(p, cfg):
    mp = _model_path(p)
    parts = [D.VERSION, len(render.VIEWS), p.get("updated_at"), mp, os.path.getmtime(mp) if mp else 0,
             [(v.get("sku"), v.get("opt1_zh"), v.get("image")) for v in p.get("variants") or []],
             [(i.get("file"), i.get("color")) for i in p.get("images") or []],
             [n for _s, n in _learned(p["id"])], json.dumps(codes.color_hex(cfg), sort_keys=True, ensure_ascii=False),
             D.model_file() is not None]
    return hashlib.sha1(json.dumps(parts, default=str, ensure_ascii=False).encode()).hexdigest()[:16]


def _variant_skus(p):
    """[(sku, 颜色名, 图片文件)]"""
    return [(str(v.get("sku")), v.get("opt1_zh") or "", v.get("image") or "") for v in p.get("variants") or [] if v.get("sku")]


def _save_disp(pid, sku, im):
    _dirs()
    d = os.path.join(DISP_DIR, store.safe_id(pid))
    os.makedirs(d, exist_ok=True)
    im = im.convert("RGBA") if im.mode != "RGBA" else im
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, (0, 0), im)
    bg.thumbnail((360, 360))
    fn = _safe_name(sku) + ".jpg"
    bg.save(os.path.join(d, fn), "JPEG", quality=85)
    return fn


def _safe_name(s):
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(s))[:60] or "x"


def build_product(pid, cfg=None, force=False):
    """算一个产品的参考特征；没变就不算。返回 (是否重算了, 参考图张数)。"""
    _dirs()
    cfg = cfg or load_config()
    p = store.load(pid)
    sig = _signature(p, cfg)
    out = os.path.join(REF_DIR, store.safe_id(pid) + ".npz")
    if not force and os.path.isfile(out):
        try:
            with np.load(out, allow_pickle=False) as z:
                if str(z["sig"]) == sig:
                    return False, int(len(z["vecs"]))
        except Exception:  # noqa: BLE001  坏了就重算
            pass
    vs = _variant_skus(p)
    all_skus = [s for s, _c, _i in vs]
    vecs, meta, colw = [], [], []
    disp = {}

    def add(vec, skus, kind, src, cw=1.0):
        vecs.append(vec)
        meta.append({"skus": skus, "kind": kind, "src": src})
        colw.append(cw)

    # 1) 产品图
    color_of_file = {}
    for s, col, img in vs:
        if img:
            color_of_file.setdefault(img, []).append(s)
    for img in (p.get("images") or [])[:MAX_IMGS]:
        fp = _img_path(pid, img)
        if not fp:
            continue
        skus = list(color_of_file.get(img.get("file")) or color_of_file.get(img.get("raw")) or [])
        if not skus and img.get("color"):
            skus = [s for s, col, _i in vs if col and col == img.get("color")]
        try:
            im = D.open_image(fp)
            add(D.describe(im), skus or all_skus, "img", os.path.basename(fp))
            for s in skus:
                if s not in disp:
                    disp[s] = ("img", im)
        except Exception:  # noqa: BLE001  图坏了跳过
            continue
    # 2) 3D 模型从几个角度画
    mp = _model_path(p)
    if mp:
        try:
            from core import mesh
            tris = mesh.load(mp)
            colors, skus_of = {}, {}
            for s, col, _i in vs:
                code, rgb = _color_rgb(cfg, col)
                key = code or "_grey"
                colors[key] = rgb or render.hex_rgb(codes.NEUTRAL_HEX)
                skus_of.setdefault(key, []).append(s)
            if not colors:
                colors, skus_of = {"_grey": render.hex_rgb(codes.NEUTRAL_HEX)}, {"_grey": all_skus}
            for (az, el), ims in render.views(tris, colors):
                for key, im in ims.items():
                    add(D.describe(im), skus_of[key], "render", f"{az}/{el}/{key}", 0.0 if key == "_grey" else 1.0)
                    if az == 0 and el == render.VIEWS[0][1]:
                        for s in skus_of[key]:
                            if s not in disp:
                                disp[s] = ("render", im)
        except Exception as e:  # noqa: BLE001  模型读不了：只用图片
            meta.append({"skus": [], "kind": "error", "src": str(e)[:120]})
            vecs.append(np.zeros(D.DIM, np.float32))
            colw.append(0.0)
    # 3) 员工确认过的照片
    for s, fp in _learned(pid):
        try:
            add(D.describe(fp), [s] if s in all_skus else all_skus, "photo", os.path.basename(fp))
        except Exception:  # noqa: BLE001
            continue
    disp_files = {}
    for s in all_skus:
        if s in disp:
            disp_files[s] = _save_disp(pid, s, disp[s][1])
    V = np.array(vecs, np.float32) if vecs else np.zeros((0, D.DIM), np.float32)
    tmp = out + ".tmp.npz"
    np.savez_compressed(tmp, vecs=V, colw=np.array(colw, np.float32), sig=np.array(sig),
                        meta=np.array(json.dumps({"meta": meta, "disp": disp_files, "skus": all_skus}, ensure_ascii=False)))
    os.replace(tmp, out)
    with _lock:
        _idx["key"] = None
    return True, len(V)


def _product_ids():
    try:
        return [n[:-5] for n in sorted(os.listdir(store.PRODUCTS_DIR)) if n.endswith(".json")]
    except OSError:
        return []


def build_all(force=False, pids=None):
    """把所有产品的参考图建好（已经是最新的跳过）。后台线程里跑；JOB 里看进度。"""
    if JOB["running"]:
        return dict(JOB)
    ids = pids or _product_ids()
    JOB.update(running=True, done=0, total=len(ids), error="", started=time.time(), finished=0, current="", changed=0)
    cfg = load_config()
    try:
        for pid in ids:
            JOB["current"] = pid
            try:
                ch, _n = build_product(pid, cfg, force)
                JOB["changed"] += int(ch)
            except FileNotFoundError:
                pass
            except Exception as e:  # noqa: BLE001  一个产品出错不影响别的
                JOB["error"] = f"{pid}: {e}"[:200]
            JOB["done"] += 1
        # 删掉已经没有的产品
        have = set(_product_ids())
        for n in os.listdir(REF_DIR) if os.path.isdir(REF_DIR) else []:
            if n.endswith(".npz") and n[:-4] not in have:
                try:
                    os.remove(os.path.join(REF_DIR, n))
                except OSError:
                    pass
    finally:
        JOB.update(running=False, finished=time.time(), current="")
        with _lock:
            _idx["key"] = None
    return dict(JOB)


def start_build(force=False, pids=None):
    if JOB["running"]:
        return False
    threading.Thread(target=build_all, args=(force, pids), daemon=True, name="recog-build").start()
    return True


def index():
    """内存里的总表：vecs (n, DIM)、colw (n,)、meta [{pid, skus, kind, src}]、disp {sku: (pid, 文件)}。文件变了自动重读。"""
    _dirs()
    files = sorted(n for n in os.listdir(REF_DIR) if n.endswith(".npz") and not n.endswith(".tmp.npz"))
    key = tuple((n, os.path.getmtime(os.path.join(REF_DIR, n))) for n in files)
    with _lock:
        if _idx["key"] == key:
            return _idx
        vecs, colw, meta, disp, skus = [], [], [], {}, {}
        for n in files:
            pid = n[:-4]
            try:
                with np.load(os.path.join(REF_DIR, n), allow_pickle=False) as z:
                    v, cw, info = z["vecs"], z["colw"], json.loads(str(z["meta"]))
            except Exception:  # noqa: BLE001
                continue
            if len(v) and v.shape[1] != D.DIM:
                continue
            for m_, row, c_ in zip(info["meta"], v, cw):
                if m_.get("kind") == "error" or not m_.get("skus"):
                    continue
                vecs.append(row)
                colw.append(c_)
                meta.append({"pid": pid, **m_})
            for s, fn in (info.get("disp") or {}).items():
                disp[s] = (pid, fn)
            for s in info.get("skus") or []:
                skus[s] = pid
        _idx.update(key=key, vecs=np.array(vecs, np.float32) if vecs else np.zeros((0, D.DIM), np.float32),
                    colw=np.array(colw, np.float32), meta=meta, disp=disp, skus=skus)
        return _idx


def disp_path(pid, fn):
    p = os.path.join(DISP_DIR, store.safe_id(pid), os.path.basename(fn))
    return p if os.path.isfile(p) else None


def add_photo(pid, sku, raw):
    """员工确认的照片存成这个 SKU 的参考图，马上算进去（不用等重建）。"""
    _dirs()
    d = os.path.join(LEARN_DIR, store.safe_id(pid))
    os.makedirs(d, exist_ok=True)
    im = D.open_image(raw).convert("RGB")
    im.thumbnail((800, 800))
    fn = f"{_safe_name(sku)}__{int(time.time() * 1000)}.jpg"
    im.save(os.path.join(d, fn), "JPEG", quality=85)
    mine = sorted(n for n in os.listdir(d) if n.startswith(_safe_name(sku) + "__"))
    for old in mine[:-MAX_LEARN]:
        try:
            os.remove(os.path.join(d, old))
        except OSError:
            pass
    try:
        build_product(pid)
    except Exception:  # noqa: BLE001  产品删了之类：照片留着
        pass
    return fn


def _learn_path(pid, fn):
    fn = os.path.basename(str(fn or ""))
    if not fn.endswith(".jpg") or "__" not in fn:
        return None
    p = os.path.join(LEARN_DIR, store.safe_id(pid), fn)
    return p if os.path.isfile(p) else None


def list_learned(pid=None, sku=None):
    """员工确认过的参考照片：[{pid, sku, file, at, url}]（新的在前）。pid / sku 可以只看一个产品 / 一个 SKU。"""
    out = []
    if not os.path.isdir(LEARN_DIR):
        return out
    pids = [store.safe_id(pid)] if pid else sorted(os.listdir(LEARN_DIR))
    for p_ in pids:
        d = os.path.join(LEARN_DIR, p_)
        if not os.path.isdir(d):
            continue
        for n in os.listdir(d):
            if not n.endswith(".jpg") or "__" not in n:
                continue
            s_ = n.split("__")[0]
            if sku and s_.upper() != _safe_name(sku).upper():
                continue
            try:
                at = int(n.split("__")[1].split(".")[0][:13]) // 1000
            except (ValueError, IndexError):
                at = int(os.path.getmtime(os.path.join(d, n)))
            out.append({"pid": p_, "sku": s_, "file": n, "at": at, "url": f"/api/recog/learned/{p_}/{n}"})
    out.sort(key=lambda x: -x["at"])
    return out


def delete_learned(pid, fn, rebuild=True):
    p = _learn_path(pid, fn)
    if not p:
        raise ValueError("这张参考照片找不到了")
    os.remove(p)
    if rebuild:
        _rebuild(pid)
    return True


def move_learned(pid, fn, new_pid, new_sku):
    """认错了：把照片挪到正确的 SKU（可以是别的产品）。"""
    p = _learn_path(pid, fn)
    if not p:
        raise ValueError("这张参考照片找不到了")
    d = os.path.join(LEARN_DIR, store.safe_id(new_pid))
    os.makedirs(d, exist_ok=True)
    nf = f"{_safe_name(new_sku)}__{fn.split('__', 1)[1]}"
    shutil.move(p, os.path.join(d, nf))
    _rebuild(pid)
    if new_pid != pid:
        _rebuild(new_pid)
    return nf


def _rebuild(pid):
    try:
        build_product(pid)
    except FileNotFoundError:          # 产品删了：只删掉它的特征
        try:
            os.remove(os.path.join(REF_DIR, store.safe_id(pid) + ".npz"))
        except OSError:
            pass
        with _lock:
            _idx["key"] = None


def learned_count():
    n = 0
    if os.path.isdir(LEARN_DIR):
        for d in os.listdir(LEARN_DIR):
            n += len([x for x in os.listdir(os.path.join(LEARN_DIR, d)) if x.endswith(".jpg")])
    return n


def status():
    ix = index()
    kinds = {}
    for m in ix["meta"]:
        kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
    built = len([n for n in os.listdir(REF_DIR) if n.endswith(".npz")]) if os.path.isdir(REF_DIR) else 0
    return {"products": len(_product_ids()), "built": built, "refs": len(ix["meta"]), "skus": len(ix.get("skus") or {}),
            "kinds": kinds, "learned": learned_count(), "job": dict(JOB), "model": D.model_status()}
