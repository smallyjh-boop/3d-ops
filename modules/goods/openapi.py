"""给运营分析系统的商品图片（v2.32.1，接口需求单「skus 接口加商品主图 + 只读图片下载接口」）。

  sku_image(p, v)     GET /api/v1/skus 每条的 image：这个 SKU 自己的图（变体选的图）→ 产品封面（第 1 张）→ None
  resolve(image_id)   图片编号 → 产品图片文件路径（只认产品资料里登记的图片，编号对不上一律 None）
  thumb(path, iid)    长边 ≤ 400px 的小图（缓存在 data/cache/thumbs/）
图片编号 = 产品编号-文件指纹（文件名 + 处理状态 + 修改时间 + 大小），换图 / 重新处理图片编号就变；
图片怎么改都会存产品资料（更新产品 updated_at），分析系统按 since 增量就能拉到。
"""
import hashlib
import os
import re

from core import store
from core.config import DATA_DIR

ID_RE = re.compile(r"^([A-Za-z0-9_]{1,40})-([0-9a-f]{10})$")
THUMB_DIR = os.path.join(DATA_DIR, "cache", "thumbs")
THUMB_PX = 400


def _path(pid, img):
    if not isinstance(img, dict) or not img.get("file"):
        return None
    name = os.path.basename(str(img["file"]))
    p = os.path.join(store.image_dir(pid, "out" if img.get("processed") else "raw"), name)
    return p if os.path.isfile(p) else None


def _fp(pid, img):
    p = _path(pid, img)
    if not p:
        return None, None
    st = os.stat(p)
    h = hashlib.sha1(f"{img['file']}|{bool(img.get('processed'))}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()[:10]
    return f"{pid}-{h}", int(st.st_mtime)


def _info(pid, img, kind):
    iid, mt = _fp(pid, img)
    if not iid:
        return None
    return {"id": iid, "url": f"/api/v1/images/{iid}", "updated_at": mt, "for": kind}


def sku_image(p, v):
    imgs = [i for i in (p.get("images") or []) if isinstance(i, dict)]
    if v.get("image"):
        own = next((i for i in imgs if v["image"] in (i.get("raw"), i.get("file"))), None)
        if own:
            r = _info(p["id"], own, "sku")
            if r:
                return r
    for i in imgs:                     # 产品封面 = 图片顺序里的第 1 张（还在的）
        r = _info(p["id"], i, "product")
        if r:
            return r
    return None


def resolve(image_id):
    m = ID_RE.match(str(image_id or ""))
    if not m:
        return None
    pid = m.group(1)
    try:
        p = store.load(pid)
    except (FileNotFoundError, ValueError, OSError):
        return None
    for i in p.get("images") or []:
        if isinstance(i, dict) and _fp(pid, i)[0] == image_id:
            return _path(pid, i)
    return None


def thumb(path, image_id):
    """小图：长边不超过 400px；有透明的存 PNG，其他存 JPEG。返回 (路径, mimetype)。"""
    from PIL import Image
    os.makedirs(THUMB_DIR, exist_ok=True)
    for ext, mt in ((".jpg", "image/jpeg"), (".png", "image/png")):
        cp = os.path.join(THUMB_DIR, image_id + ext)
        if os.path.isfile(cp):
            return cp, mt
    with Image.open(path) as im:
        im.thumbnail((THUMB_PX, THUMB_PX))
        alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        cp = os.path.join(THUMB_DIR, image_id + (".png" if alpha else ".jpg"))
        tmp = cp + f".{os.getpid()}.tmp"
        if alpha:
            im.save(tmp, "PNG", optimize=True)
        else:
            im.convert("RGB").save(tmp, "JPEG", quality=82, optimize=True)
        os.replace(tmp, cp)
    return cp, ("image/png" if alpha else "image/jpeg")
