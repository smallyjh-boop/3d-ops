"""一张图 → 一个很小的特征（几百个数），用来在参考图里快速找最像的（第一步，NAS 上不用显卡）。

1. 抠出产品（前景）：图片带透明通道（服务器画的 3D 参考图）就直接用；照片按「边上的颜色是背景」估计背景
   （边缘像素聚成几类颜色，离这些颜色都远的就是产品），去小碎块、补洞，选靠中间最大的那块；抠不出来就用中间的椭圆。
2. 颜色：产品像素的色相直方图（有颜色的）+ 明暗直方图（白 / 灰 / 黑这类没颜色的），先粗略校正曝光。
3. 形状：轮廓按「到重心的距离 × 角度」分格，每一圈沿角度做傅里叶变换取幅度 → 转多少度都一样；加上 Hu 不变矩、长宽比、饱满度。
4. 纹理 / 细节：产品里面的边缘按同样的极坐标分格（耳朵、字、花纹）。

similarity(q, refs) 返回和每张参考图的相似度（0..1）：颜色、形状、细节分开算再按权重加起来。
局限：同一个形状同一个颜色的两个产品分不开（交给 AI 看图或者人选）；白色产品放在白桌子上抠图会差。
"""
import io
import os
import threading

import numpy as np
from PIL import Image, ImageFilter, ImageOps

WORK = 128                 # 抠图、算形状用的尺寸
RINGS, SECTORS, HARM = 8, 32, 8
HUE_BINS = 24
ACH_BINS = 4
VERSION = 3                # 特征算法改了就加一（参考图会自动重算）

# 各部分的长度（拼成一个向量存）
N_COL = HUE_BINS + ACH_BINS
N_SHP = RINGS * HARM
N_GEO = 10
N_EDG = RINGS * HARM
DIM = N_COL + N_SHP + N_GEO + N_EDG
WEIGHTS = {"col": 0.42, "shp": 0.33, "geo": 0.10, "edg": 0.15}


# ---------------- 读图 ----------------
def open_image(src):
    """bytes / 路径 / PIL 图 → PIL 图（按手机照片的方向转正）。"""
    if isinstance(src, Image.Image):
        im = src
    else:
        im = Image.open(io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src)
    try:
        im = ImageOps.exif_transpose(im)
    except Exception:  # noqa: BLE001
        pass
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
    return im


def _small(im, side=WORK):
    w, h = im.size
    s = side / max(w, h)
    if s < 1:
        im = im.resize((max(8, round(w * s)), max(8, round(h * s))), Image.BILINEAR)
    return im


# ---------------- 抠图 ----------------
def _opp(a):
    """RGB → (亮度, 红绿, 黄蓝)：亮度差的权重小一点（影子、明暗不太算前景）。"""
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return np.stack([(r + g + b) / 3 * 0.55, (r - g), (r + g) / 2 - b], -1)


def _kmeans(x, k=4, it=8):
    if len(x) <= k:
        return x.copy()
    idx = np.linspace(0, len(x) - 1, k).astype(int)
    c = x[np.argsort(x[:, 0])][idx].copy()
    for _ in range(it):
        d = ((x[:, None, :] - c[None]) ** 2).sum(-1)
        lab = d.argmin(1)
        for j in range(k):
            m = lab == j
            if m.any():
                c[j] = x[m].mean(0)
    return c


def _label(mask):
    """四连通区域编号（纯 numpy + 一点 python，128×128 很快）。返回 (编号图, 区域数)。"""
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    n = 0
    ys, xs = np.nonzero(mask)
    for y0, x0 in zip(ys, xs):
        if lab[y0, x0]:
            continue
        n += 1
        stack = [(y0, x0)]
        lab[y0, x0] = n
        while stack:
            y, x = stack.pop()
            for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = n
                    stack.append((yy, xx))
    return lab, n


def _otsu(v):
    v = v[np.isfinite(v)]
    if not len(v):
        return 0.0
    hist, edges = np.histogram(v, 64)
    p = hist / max(1, hist.sum())
    w0 = np.cumsum(p)
    mu = np.cumsum(p * edges[:-1])
    mt = mu[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        sb = (mt * w0 - mu) ** 2 / (w0 * (1 - w0))
    sb[~np.isfinite(sb)] = 0
    return float(edges[int(sb.argmax())])


def _clean(mask):
    im = Image.fromarray((mask * 255).astype(np.uint8))
    im = im.filter(ImageFilter.MedianFilter(5))
    m = np.asarray(im) > 127
    h, w = m.shape
    lab, n = _label(m)
    if not n:
        return m
    yy, xx = np.mgrid[0:h, 0:w]
    best, best_s = 0, -1.0
    areas = np.bincount(lab.ravel())
    for i in range(1, n + 1):
        a = areas[i]
        if a < 12:
            continue
        cy, cx = yy[lab == i].mean(), xx[lab == i].mean()
        dc = np.hypot((cy - h / 2) / h, (cx - w / 2) / w)
        s = a * (1.2 - dc)
        if s > best_s:
            best, best_s = i, s
    if not best:
        return m
    keep = lab == best
    by, bx = np.nonzero(keep)
    y0, y1, x0, x1 = by.min(), by.max(), bx.min(), bx.max()
    py, px = (y1 - y0) * 0.15 + 2, (x1 - x0) * 0.15 + 2
    for i in range(1, n + 1):                       # 同一个产品被分成几块（例如颜色不同的部分）：靠近主块的也要
        if i == best or areas[i] < areas[best] * 0.12:
            continue
        cy, cx = yy[lab == i].mean(), xx[lab == i].mean()
        if y0 - py <= cy <= y1 + py and x0 - px <= cx <= x1 + px:
            keep |= lab == i
    # 补洞：不连到边上的背景块
    blab, bn = _label(~keep)
    edge = set(np.unique(np.concatenate([blab[0], blab[-1], blab[:, 0], blab[:, -1]]))) - {0}
    for i in range(1, bn + 1):
        if i not in edge:
            keep |= blab == i
    return keep


def _skin(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    cb = 128 - 0.1687 * r - 0.3313 * g + 0.5 * b
    cr = 128 + 0.5 * r - 0.4187 * g - 0.0813 * b
    return (cr > 136) & (cr < 175) & (cb > 85) & (cb < 128) & (r > g) & (r > 60)


def _ellipse(h, w, frac=0.62):
    yy, xx = np.mgrid[0:h, 0:w]
    return (((yy - h / 2) / (h * frac / 2)) ** 2 + ((xx - w / 2) / (w * frac / 2)) ** 2) <= 1


# ---------------- 可选：小的抠图模型（u2netp，4.6 MB，CPU 上 0.1~0.3 秒） ----------------
U2_NAME = "u2netp.onnx"
U2_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx"
U2_SHA256 = "309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8"
_u2 = {"sess": None, "path": None, "err": ""}
_u2_lock = threading.Lock()


def model_dirs():
    from core.config import DATA_DIR
    out = [os.path.join(DATA_DIR, "models")]
    if os.environ.get("U2NET_HOME"):
        out.append(os.environ["U2NET_HOME"])
    out += [os.path.join(DATA_DIR, ".runtime", "u2net"), os.path.expanduser("~/.u2net")]
    return out


def model_file():
    if os.environ.get("LH_RECOG_NO_MODEL") == "1":
        return None
    for d in model_dirs():
        p = os.path.join(d, U2_NAME)
        if os.path.isfile(p) and os.path.getsize(p) > 1_000_000:
            return p
    return None


def model_status():
    p = model_file()
    try:
        import importlib.util
        ort = importlib.util.find_spec("onnxruntime") is not None
    except Exception:  # noqa: BLE001
        ort = False
    return {"onnxruntime": ort, "model": bool(p), "path": p or "", "active": bool(p and ort), "error": _u2["err"]}


def _u2_session():
    p = model_file()
    if not p:
        return None
    with _u2_lock:
        if _u2["sess"] is not None and _u2["path"] == p:
            return _u2["sess"]
        try:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = 2               # NAS 上别把 CPU 占满
            _u2["sess"] = ort.InferenceSession(p, so, providers=["CPUExecutionProvider"])
            _u2["path"], _u2["err"] = p, ""
        except Exception as e:  # noqa: BLE001  没装 onnxruntime / 模型坏了：用不了就算了
            _u2["sess"], _u2["err"] = None, str(e)[:200]
        return _u2["sess"]


def _u2_mask(im, shape):
    sess = _u2_session()
    if sess is None:
        return None
    x = np.asarray(im.convert("RGB").resize((320, 320), Image.BILINEAR), np.float32)
    x = x / max(float(x.max()), 1.0)
    x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    try:
        with _u2_lock:
            out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
    except Exception as e:  # noqa: BLE001
        _u2["err"] = str(e)[:200]
        return None
    out = (out - out.min()) / max(float(out.max() - out.min()), 1e-6)
    m = Image.fromarray((out * 255).astype(np.uint8)).resize((shape[1], shape[0]), Image.BILINEAR)
    return np.asarray(m, np.float32) / 255.0


def segment(im, model=True):
    """返回 (rgb float32 HxWx3, 前景 bool HxW, 怎么抠的)。"""
    im = _small(im)
    a = np.asarray(im, dtype=np.float32)
    if a.shape[-1] == 4:
        alpha = a[..., 3]
        rgb = a[..., :3]
        m = alpha > 127
        if 0.003 < m.mean() < 0.995:
            return rgb, m, "alpha"
        a = rgb
    rgb = a[..., :3]
    h, w = rgb.shape[:2]
    if model:
        sal = _u2_mask(im, (h, w))
        if sal is not None:
            m = sal > 0.5
            if 0.01 < m.mean() < 0.95:
                return rgb, _clean(m), "model"
    o = _opp(rgb)
    bw = max(2, int(round(min(h, w) * 0.05)))
    border = np.concatenate([o[:bw].reshape(-1, 3), o[-bw:].reshape(-1, 3), o[:, :bw].reshape(-1, 3), o[:, -bw:].reshape(-1, 3)])
    c = _kmeans(border, 6)
    # 产品碰到画面边上时，边上也有产品的颜色：只把占边缘大多数的几类颜色当背景
    lab = np.sqrt(((border[:, None, :] - c[None]) ** 2).sum(-1)).argmin(1)
    cnt = np.bincount(lab, minlength=len(c)).astype(float) / len(lab)
    keep, acc = [], 0.0
    for j in np.argsort(-cnt):
        keep.append(j)
        acc += cnt[j]
        if acc >= 0.85 and cnt[j] < 0.12:
            break
    c = c[keep]
    d = np.sqrt(((o[..., None, :] - c[None, None]) ** 2).sum(-1)).min(-1)
    db = np.sqrt(((border[:, None, :] - c[None]) ** 2).sum(-1)).min(-1)
    noise = float(np.percentile(db, 80))
    thr = max(_otsu(d), noise * 1.6 + 6, 14.0)
    m = d > thr
    sk = _skin(rgb)
    if sk.any():                                   # 手拿着拍：连到画面边上的肤色当背景（粉色产品在中间不受影响）
        slab, sn = _label(sk & m)
        edge = set(np.unique(np.concatenate([slab[0], slab[-1], slab[:, 0], slab[:, -1]]))) - {0}
        if edge:
            hand = np.isin(slab, list(edge))
            if (m & ~hand).mean() > 0.02:
                m = m & ~hand
    frac = m.mean()
    how = "border"
    if frac < 0.015 or frac > 0.9:
        return rgb, _ellipse(h, w), "center"
    m = _clean(m)
    frac = m.mean()
    if frac < 0.012 or frac > 0.92:
        return rgb, _ellipse(h, w), "center"
    return rgb, m, how


# ---------------- 特征 ----------------
def _exposure(rgb):
    """粗略校正曝光：整张图最亮的那部分拉到 ~235（暗的照片、过曝的照片颜色判断更稳）。"""
    hi = float(np.percentile(rgb.max(-1), 98))
    g = np.clip(235.0 / max(hi, 1.0), 0.75, 2.4)
    return np.clip(rgb * g, 0, 255)


def _hsv(rgb):
    r, g, b = rgb[..., 0] / 255, rgb[..., 1] / 255, rgb[..., 2] / 255
    mx, mn = np.maximum(np.maximum(r, g), b), np.minimum(np.minimum(r, g), b)
    v = mx
    dlt = mx - mn
    s = np.where(mx > 1e-6, dlt / np.maximum(mx, 1e-6), 0)
    hh = np.zeros_like(mx)
    nz = dlt > 1e-6
    rc = np.where(nz, (mx - r) / np.where(nz, dlt, 1), 0)
    gc = np.where(nz, (mx - g) / np.where(nz, dlt, 1), 0)
    bc = np.where(nz, (mx - b) / np.where(nz, dlt, 1), 0)
    hh = np.where(r == mx, bc - gc, np.where(g == mx, 2.0 + rc - bc, 4.0 + gc - rc))
    hh = (hh / 6.0) % 1.0
    return hh, s, v


def _soft_hist(vals, weights, bins, circular):
    pos = vals * bins - 0.5
    lo = np.floor(pos).astype(int)
    f = pos - lo
    hi = lo + 1
    if circular:
        lo, hi = lo % bins, hi % bins
    else:
        lo, hi = np.clip(lo, 0, bins - 1), np.clip(hi, 0, bins - 1)
    h = np.bincount(lo, weights * (1 - f), bins) + np.bincount(hi, weights * f, bins)
    return h


def color_feat(rgb, m):
    px = _exposure(rgb)[m]
    if not len(px):
        return np.zeros(N_COL, np.float32)
    hh, s, v = _hsv(px)
    chrom = (s >= 0.22) & (v >= 0.18)
    w = np.where(chrom, np.clip((s - 0.12) * 2, 0, 1), 0)
    hue = _soft_hist(hh[chrom], w[chrom], HUE_BINS, True)
    ach_w = 1 - w
    ach = _soft_hist(np.clip(v, 0, 0.999), ach_w, ACH_BINS, False)
    tot = hue.sum() + ach.sum()
    out = np.concatenate([hue, ach]) / max(tot, 1e-6)
    return out.astype(np.float32)


def _polar(weight, m):
    """按重心的极坐标分格，每圈沿角度做傅里叶幅度（转多少度都一样）。"""
    h, w = m.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = m.sum()
    if a < 5:
        return np.zeros(RINGS * HARM, np.float32), 1.0
    cy, cx = yy[m].mean(), xx[m].mean()
    dy, dx = yy - cy, xx - cx
    r = np.hypot(dy, dx)
    rg = float(np.sqrt((r[m] ** 2).mean())) or 1.0
    rn = r / (1.7 * rg)
    ang = (np.arctan2(dy, dx) / (2 * np.pi)) % 1.0
    ring = np.clip((rn * RINGS).astype(int), 0, RINGS)            # RINGS = 超出范围
    sec = np.clip((ang * SECTORS).astype(int), 0, SECTORS - 1)
    ok = ring < RINGS
    idx = ring[ok] * SECTORS + sec[ok]
    tot = np.bincount(idx, weight[ok], RINGS * SECTORS).reshape(RINGS, SECTORS)
    cnt = np.bincount(idx, None, RINGS * SECTORS).reshape(RINGS, SECTORS)
    occ = tot / np.maximum(cnt, 1)
    f = np.abs(np.fft.rfft(occ, axis=1))[:, :HARM] / SECTORS
    return f.reshape(-1).astype(np.float32), rg


def _hu(m):
    h, w = m.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    a = m.sum()
    if a < 5:
        return np.zeros(7)
    cy, cx = yy[m].mean(), xx[m].mean()
    y, x = yy[m] - cy, xx[m] - cx

    def eta(p, q):
        return (x ** p * y ** q).sum() / a ** (1 + (p + q) / 2)
    n20, n02, n11 = eta(2, 0), eta(0, 2), eta(1, 1)
    n30, n03, n21, n12 = eta(3, 0), eta(0, 3), eta(2, 1), eta(1, 2)
    h1 = n20 + n02
    h2 = (n20 - n02) ** 2 + 4 * n11 ** 2
    h3 = (n30 - 3 * n12) ** 2 + (3 * n21 - n03) ** 2
    h4 = (n30 + n12) ** 2 + (n21 + n03) ** 2
    h5 = (n30 - 3 * n12) * (n30 + n12) * ((n30 + n12) ** 2 - 3 * (n21 + n03) ** 2) + \
        (3 * n21 - n03) * (n21 + n03) * (3 * (n30 + n12) ** 2 - (n21 + n03) ** 2)
    h6 = (n20 - n02) * ((n30 + n12) ** 2 - (n21 + n03) ** 2) + 4 * n11 * (n30 + n12) * (n21 + n03)
    h7 = (3 * n21 - n03) * (n30 + n12) * ((n30 + n12) ** 2 - 3 * (n21 + n03) ** 2) - \
        (n30 - 3 * n12) * (n21 + n03) * (3 * (n30 + n12) ** 2 - (n21 + n03) ** 2)
    hu = np.array([h1, h2, h3, h4, abs(h5), abs(h6), abs(h7)])
    return -np.sign(hu) * np.log10(np.abs(hu) + 1e-12)


def geo_feat(m):
    """Hu 不变矩（压到 0..1 左右）+ 长短轴比 + 饱满度 + 周长比。"""
    hu = _hu(m)
    hu = np.clip(hu / 12.0, 0, 1.5)
    h, w = m.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    if m.sum() < 5:
        return np.zeros(N_GEO, np.float32)
    y, x = yy[m] - yy[m].mean(), xx[m] - xx[m].mean()
    cov = np.cov(np.stack([x, y]))
    ev = np.sort(np.linalg.eigvalsh(cov))
    elong = float(np.sqrt(max(ev[0], 1e-9) / max(ev[1], 1e-9)))
    r = np.hypot(x, y)
    fill = float(m.sum() / (np.pi * max(r.max(), 1) ** 2))
    edge = m ^ np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3))) > 127
    comp = float(np.clip(edge.sum() / (2 * np.sqrt(np.pi * m.sum())) / 3.0, 0, 1.5))
    return np.concatenate([hu, [elong, fill, comp]]).astype(np.float32)


def edge_feat(rgb, m):
    g = rgb.mean(-1)
    gy, gx = np.gradient(g)
    mag = np.hypot(gx, gy)
    inner = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(5))) > 127
    mag = np.where(inner, mag, 0)
    s = float(np.percentile(mag[inner], 90)) if inner.any() else 1.0
    mag = np.clip(mag / max(s, 1.0), 0, 1)
    f, _rg = _polar(mag.astype(np.float32), m)
    return f


def _crop_square(rgb, m, pad=0.08):
    ys, xs = np.nonzero(m)
    if not len(ys):
        return rgb, m
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    s = int(max(y1 - y0, x1 - x0) * (1 + 2 * pad)) + 2
    cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
    H, W = m.shape
    out_rgb = np.zeros((s, s, 3), np.float32)
    out_m = np.zeros((s, s), bool)
    sy0, sx0 = cy - s // 2, cx - s // 2
    a0, a1 = max(0, sy0), min(H, sy0 + s)
    b0, b1 = max(0, sx0), min(W, sx0 + s)
    out_rgb[a0 - sy0:a1 - sy0, b0 - sx0:b1 - sx0] = rgb[a0:a1, b0:b1]
    out_m[a0 - sy0:a1 - sy0, b0 - sx0:b1 - sx0] = m[a0:a1, b0:b1]
    im = Image.fromarray(np.clip(out_rgb, 0, 255).astype(np.uint8)).resize((96, 96), Image.BILINEAR)
    mm = Image.fromarray((out_m * 255).astype(np.uint8)).resize((96, 96), Image.BILINEAR)
    return np.asarray(im, np.float32), np.asarray(mm) > 127


def describe(src, with_mask=False, model=True):
    """图 → 特征向量（float32，长度 DIM）。with_mask=True 时另外返回抠图结果（调试 / 生成 AI 看的小图用）。"""
    im = open_image(src)
    rgb, m, how = segment(im, model)
    col = color_feat(rgb, m)
    crgb, cm = _crop_square(rgb, m)
    shp, _rg = _polar(cm.astype(np.float32), cm)
    geo = geo_feat(cm)
    edg = edge_feat(crgb, cm)
    v = np.concatenate([col, shp, geo, edg]).astype(np.float32)
    if with_mask:
        return v, {"mask": m, "how": how, "size": m.shape}
    return v


def _vec(rgb, m, col=None):
    col = color_feat(rgb, m) if col is None else col
    crgb, cm = _crop_square(rgb, m)
    shp, _rg = _polar(cm.astype(np.float32), cm)
    return np.concatenate([col, shp, geo_feat(cm), edge_feat(crgb, cm)]).astype(np.float32)


def _grayworld(rgb, m):
    """按背景（产品以外）校正白平衡：背景的平均颜色拉成灰色（桌面、白纸多半是灰白的；木纹桌子会校过头，所以只是「多一种假设」）。"""
    bg = rgb[~m] if (~m).sum() > 50 else rgb.reshape(-1, 3)
    mean = bg.reshape(-1, 3).mean(0)
    g = np.clip(mean.mean() / np.maximum(mean, 1.0), 0.75, 1.33)
    return np.clip(rgb * g, 0, 255)


def describe_query(src):
    """员工拍的照片 → 好几种「假设」的特征（每行一个）：抠图模型的结果、按边缘颜色抠的结果、白平衡校正后的颜色。
    比对时每张参考图取最像的那个假设（抠图偶尔失败、灯光偏色时不至于全错）。"""
    im = open_image(src)
    rows, masks = [], []
    rgb, m, how = segment(im, True)
    rows.append(_vec(rgb, m))
    masks.append(m)
    if how == "model":
        rgb2, m2, how2 = segment(im, False)
        if how2 != "center" and np.logical_xor(m2, m).mean() > 0.04 * max(m.mean(), 0.05):
            rows.append(_vec(rgb2, m2))
            masks.append(m2)
    rows.append(_vec(rgb, m, color_feat(_grayworld(rgb, m), m)))
    return np.array(rows, np.float32)


# ---------------- 比较 ----------------
def _parts(a):
    a = np.atleast_2d(a)
    i = 0
    out = {}
    for k, n in (("col", N_COL), ("shp", N_SHP), ("geo", N_GEO), ("edg", N_EDG)):
        out[k] = a[:, i:i + n]
        i += n
    return out


def part_sims(q, refs):
    """每一部分的相似度（0..1），refs: (n, DIM)。"""
    qp, rp = _parts(q), _parts(refs)
    # 颜色：Bhattacharyya 系数（两个直方图重叠多少）
    col = np.sqrt(np.clip(qp["col"], 0, None) * np.clip(rp["col"], 0, None)).sum(1)
    # 形状：L1 距离 → 相似度
    shp = np.exp(-np.abs(qp["shp"] - rp["shp"]).sum(1) / 1.6)
    geo = np.exp(-np.abs(qp["geo"] - rp["geo"]).sum(1) / 0.6)
    edg = np.exp(-np.abs(qp["edg"] - rp["edg"]).sum(1) / 1.6)
    return {"col": col, "shp": shp, "geo": geo, "edg": edg}


def similarity(q, refs, weights=None):
    if len(refs) == 0:
        return np.zeros(0, np.float32)
    w = weights or WEIGHTS
    s = part_sims(q, refs)
    return sum(w[k] * s[k] for k in w) / sum(w.values())
