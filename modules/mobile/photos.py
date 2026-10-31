"""订单的打包照片（验货完成时拍一张，有纠纷时当证据）。

存在 data/order_photos/<订单 id>/：照片缩到长边 1600 像素的 JPG；index.json 记谁、什么时候、什么用途。
对外：add(oid, files, user, kind)  list_photos(oid)  path_of(oid, name)
"""
import io
import json
import os
import re
import secrets
import threading
import time

from core import orders as orders_mod
from core.config import DATA_DIR

ROOT = os.path.join(DATA_DIR, "order_photos")
NAME_RE = re.compile(r"^[0-9]{10}_[a-f0-9]{8}\.jpg$")
MAX_SIDE = 1600
MAX_FILES = 6
KINDS = {"pack": "打包照片", "other": "照片"}
_lock = threading.Lock()


def _dir(oid):
    return os.path.join(ROOT, str(int(oid)))


def _index(oid):
    try:
        with open(os.path.join(_dir(oid), "index.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _save_index(oid, rows):
    p = os.path.join(_dir(oid), "index.json")
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    os.replace(p + ".tmp", p)


def list_photos(oid):
    d = _dir(oid)
    if not os.path.isdir(d):
        return []
    meta = {r.get("name"): r for r in _index(oid)}
    out = []
    for n in sorted(os.listdir(d)):
        if NAME_RE.match(n):
            m = meta.get(n) or {}
            out.append({"name": n, "at": m.get("at") or int(n.split("_")[0]), "user": m.get("user") or "", "kind": m.get("kind") or "pack",
                        "url": f"/api/mobile/orders/{int(oid)}/photos/{n}"})
    return out


def path_of(oid, name):
    name = os.path.basename(str(name or ""))
    if not NAME_RE.match(name):
        return None
    p = os.path.join(_dir(oid), name)
    return p if os.path.isfile(p) else None


def _to_jpg(data):
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)          # 手机竖着拍的照片转正
    except Exception as e:  # noqa: BLE001
        raise ValueError("这不是照片（只能传 JPG / PNG / WebP 照片）") from e
    im = im.convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82, optimize=True)
    return buf.getvalue()


def add(oid, files, user="", kind="pack"):
    """存照片（一次最多 6 张）。返回这个订单所有照片。"""
    o = orders_mod.get_order(int(oid))
    if not o:
        raise ValueError("订单不存在")
    files = [f for f in files or [] if f and getattr(f, "filename", "")]
    if not files:
        raise ValueError("请选择照片")
    if len(files) > MAX_FILES:
        raise ValueError(f"一次最多 {MAX_FILES} 张")
    kind = kind if kind in KINDS else "pack"
    blobs = [_to_jpg(f.read()) for f in files]
    with _lock:
        os.makedirs(_dir(oid), exist_ok=True)
        rows = _index(oid)
        for b in blobs:
            name = f"{int(time.time())}_{secrets.token_hex(4)}.jpg"
            with open(os.path.join(_dir(oid), name), "wb") as f:
                f.write(b)
            rows.append({"name": name, "at": int(time.time()), "user": user, "kind": kind})
        _save_index(oid, rows)
    orders_mod.log(int(oid), user, "上传" + KINDS[kind], f"{len(blobs)} 张")
    return list_photos(oid)
