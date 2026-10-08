"""托盘图标：底图 + 右下角状态小圆点（绿 = 在线，黄 = 连接中，灰 = 暂停，红 = 出错 / 连不上）。"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
COLORS = {"在线": (34, 197, 94), "连接中": (245, 158, 11), "暂停": (148, 163, 184), "未配对": (148, 163, 184)}
_cache = {}


def image(base, state):
    from PIL import Image, ImageDraw
    key = (base, state)
    if key in _cache:
        return _cache[key]
    im = Image.open(os.path.join(HERE, base)).convert("RGBA").resize((64, 64))
    col = COLORS.get(state, (239, 68, 68))
    d = ImageDraw.Draw(im)
    d.ellipse([40, 40, 63, 63], fill=(19, 32, 58, 255))
    d.ellipse([44, 44, 59, 59], fill=col + (255,))
    _cache[key] = im
    return im
