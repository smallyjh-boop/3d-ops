"""图片处理：转 1:1 方图、白底、压缩到 Lazada 限制以内；可选 AI 去背景（rembg）。"""
import io
import os

from PIL import Image, ImageOps

MAX_BYTES = 1_900_000  # Lazada 单张 ≤2MB



def rembg_available():
    try:
        import rembg  # noqa: F401
        return True
    except Exception:
        return False


def _remove_bg(img):
    """去背景：和图片编辑器的抠图用同一套（电脑在线时交给电脑做，v2.20）。"""
    from . import imgtools
    return imgtools.remove_bg(img, "isnet")


def _save_jpeg(img, dst):
    for q in (92, 88, 84, 80, 75, 70, 65):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= MAX_BYTES:
            break
    with open(dst, "wb") as f:
        f.write(buf.getvalue())


def process(src, dst, size=1200, remove_bg=False, fill_ratio=0.85):
    """生成方形白底主图。去背景时会自动裁到产品轮廓并居中。"""
    img = Image.open(src)
    img = ImageOps.exif_transpose(img)
    if remove_bg:
        img = _remove_bg(img.convert("RGB"))
    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    if has_alpha:
        img = img.convert("RGBA")
        bbox = img.getchannel("A").point(lambda a: 255 if a > 10 else 0).getbbox()
        if bbox:
            img = img.crop(bbox)
        target = int(size * fill_ratio)
        scale = target / max(img.width, img.height)
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
        canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
    else:
        img = img.convert("RGB")
        scale = size / max(img.width, img.height)
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
        canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    _save_jpeg(canvas, dst)
    return dst
