"""图床上传：Lazada / Shopee 导入表格只接受图片网址，所以先把处理好的图片传到图床拿到网址。
v2.43.1：上传前把大图压一下（imgbb 传大图很慢，Lazada 接口限 1MB），超时短一点、失败重试一次。"""
import base64
import io
import os

import requests


class HostError(Exception):
    pass


def prepare(path, max_bytes=1_500_000, max_side=2000, min_side=330):
    """图片 → (字节, 扩展名)。已经够小的原样返回；大的缩到 max_side 以内、转 JPEG 压到 max_bytes 以内。
    透明背景铺白（平台都要白底）。太小（短边 < min_side）的放大到 min_side（Lazada 要求至少 330）。"""
    with open(path, "rb") as f:
        raw = f.read()
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "jpg"
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as e:  # noqa: BLE001
        raise HostError(f"读不了图片 {os.path.basename(path)}：{e}") from e
    small = min(img.size) < min_side
    if len(raw) <= max_bytes and max(img.size) <= max_side and not small and ext in ("jpg", "jpeg", "png"):
        return raw, ("jpg" if ext == "jpeg" else ext)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    if small:
        k = min_side / min(img.size)
        img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    for q in (90, 85, 80, 72, 65, 55):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= max_bytes:
            return buf.getvalue(), "jpg"
        if q == 72 and max(img.size) > 1200:
            img.thumbnail((1200, 1200), Image.LANCZOS)
    return buf.getvalue(), "jpg"


def upload_imgbb(api_key, path, retries=1):
    if not api_key:
        raise HostError("还没有填写 imgbb 图床密钥（设置页）")
    data, _ext = prepare(path)
    b64 = base64.b64encode(data).decode()
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.post(
                "https://api.imgbb.com/1/upload",
                data={"key": api_key, "image": b64, "name": os.path.splitext(os.path.basename(path))[0]},
                timeout=60,
            )
        except requests.RequestException as e:
            last = HostError(f"连接图床失败：{e}")
            continue
        if r.status_code != 200:
            last = HostError(f"图床错误 {r.status_code}: {r.text[:200]}")
            if r.status_code in (400, 401, 403):         # 密钥不对之类：重试没用
                break
            continue
        url = (r.json().get("data") or {}).get("url")
        if url:
            return url
        last = HostError("图床没有返回网址")
    raise last or HostError("上传图床失败")
