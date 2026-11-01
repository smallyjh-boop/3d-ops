"""服务器画识别用的参考图（不用显卡、不用浏览器）：把产品的 3D 模型从好几个角度画出来。

画法：画家算法（远的三角面先画，近的盖上去），用 Pillow 画多边形；面太多先用 core/preview 的顶点聚类精简到 1.5 万面。
一个角度只画一次「明暗图 + 轮廓」，每个颜色再按明暗上色（颜色多的产品也很快）。
输出 RGBA（背景透明）：识别时轮廓直接用透明通道，不用再抠图。
"""
import numpy as np
from PIL import Image, ImageDraw

MAX_TRIS = 15000
# 参考图的角度：方位角 8 个 × 仰角 2 个 + 正上方（员工拍照一般是斜上方、正面、侧面）
VIEWS = [(az, el) for el in (18, 42) for az in range(0, 360, 45)] + [(0, 85)]


def prepare(tris):
    """精简 + 居中，返回 float32 的 (n,3,3)。"""
    t = np.asarray(tris, dtype=np.float64).reshape(-1, 3, 3)
    if len(t) > MAX_TRIS:
        try:
            from core import preview
            v, idx, _r = preview.simplify(t, MAX_TRIS)
            t = np.asarray(v, dtype=np.float64)[np.asarray(idx, dtype=np.int64)]
        except Exception:  # noqa: BLE001  精简不了就只画面积大的
            a = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
            t = t[np.argsort(-a)[:MAX_TRIS]]
    p = t.reshape(-1, 3)
    c = (p.max(0) + p.min(0)) / 2
    return (t - c).astype(np.float32)


def _rot(az, el, roll=0.0):
    az, el, roll = np.radians(az), np.radians(el), np.radians(roll)
    rz = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(el), -np.sin(el)], [0, np.sin(el), np.cos(el)]])
    ry = np.array([[np.cos(roll), 0, np.sin(roll)], [0, 1, 0], [-np.sin(roll), 0, np.cos(roll)]])
    return ry @ rx @ rz


def shade_view(tris, az, el, px=192, light=(0.35, -0.8, 0.6), fill=0.86, roll=0.0, persp=0.0):
    """一个角度的明暗图（0..1，float32）和轮廓（bool）。屏幕 x = 模型 x，屏幕上 = 模型 z，看的方向 = +y。
    persp>0：近大远小（0.15 左右像手机拍近处的东西）。"""
    v = tris.reshape(-1, 3) @ _rot(az, el, roll).T
    v = v.reshape(-1, 3, 3)
    x, depth, z = v[..., 0], v[..., 1], v[..., 2]
    if persp:
        span0 = float(max(np.ptp(x), np.ptp(z), np.ptp(depth), 1e-6))
        f = 1.0 / (1.0 + persp * (depth / span0))
        x, z = x * f, z * f
    mnx, mnz = x.min(), z.min()
    span = max(x.max() - mnx, z.max() - mnz, 1e-6)
    sc = (px * fill) / span
    sx = (x - mnx) * sc + (px - (x.max() - mnx) * sc) / 2
    sy = px - ((z - mnz) * sc + (px - (z.max() - mnz) * sc) / 2)
    n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    ln = np.linalg.norm(n, axis=1)
    ln[ln == 0] = 1
    n = n / ln[:, None]
    lv = np.asarray(light, dtype=np.float64)
    lv = lv / np.linalg.norm(lv)
    lam = np.abs(n @ lv)                          # 双面（STL 法线方向不一定对）
    view = np.abs(n[:, 1])                        # 正对镜头的面亮一点（像相机闪光 / 环境光）
    shade = np.clip(0.18 + 0.62 * lam + 0.2 * view, 0, 1)
    order = np.argsort(-depth.mean(1))            # 远的先画
    img = Image.new("L", (px, px), 0)
    d = ImageDraw.Draw(img)
    g = (1 + np.round(shade * 254)).astype(int)
    for i in order:
        d.polygon([(sx[i, 0], sy[i, 0]), (sx[i, 1], sy[i, 1]), (sx[i, 2], sy[i, 2])], fill=int(g[i]))
    a = np.asarray(img, dtype=np.float32)
    mask = a > 0
    return np.clip((a - 1) / 254.0, 0, 1), mask


def colorize(shade, mask, rgb, spec=0.12):
    """明暗图 + 颜色 → RGBA 图。spec：高光（PLA 有一点反光）。"""
    c = np.asarray(rgb, dtype=np.float32).reshape(1, 1, 3)
    s = shade[..., None]
    out = c * (0.25 + 0.85 * s) + 255 * spec * np.clip(s - 0.75, 0, 1) * 4
    out = np.clip(out, 0, 255)
    alpha = (mask * 255).astype(np.uint8)
    return Image.fromarray(np.dstack([out.astype(np.uint8), alpha]), "RGBA")


def hex_rgb(h, default=(187, 187, 187)):
    h = str(h or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return default


def views(tris, colors, px=192, view_list=None):
    """[(视角, {颜色: RGBA 图})]，每个角度只算一次明暗。"""
    t = prepare(tris)
    out = []
    for az, el in view_list or VIEWS:
        sh, m = shade_view(t, az, el, px)
        out.append(((az, el), {k: colorize(sh, m, rgb) for k, rgb in colors.items()}))
    return out
