"""识别测试用的假数据：程序生成的 3D 模型（各种形状）、「手机照片」（不同背景、角度、光线、模糊、压缩……）、
货位牌 / 面单文字图。测试（t_recog.py）和准确率评估（eval_recog.py）共用。"""
import io
import math

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from modules.recog import render


# ---------------- 3D 形状 ----------------
def _quad(a, b, c, d):
    return [[a, b, c], [a, c, d]]


def lathe(profile, seg=40):
    """轮廓 [(r, z)] 绕 z 轴转一圈。"""
    t = []
    for i in range(seg):
        a0, a1 = 2 * math.pi * i / seg, 2 * math.pi * (i + 1) / seg
        for (r0, z0), (r1, z1) in zip(profile, profile[1:]):
            p = lambda r, z, a: (r * math.cos(a), r * math.sin(a), z)  # noqa: E731
            t += _quad(p(r0, z0, a0), p(r0, z0, a1), p(r1, z1, a1), p(r1, z1, a0))
    return np.array(t, dtype=np.float64)


def extrude(poly, h, z0=0.0):
    """多边形 [(x, y)]（凸或星形，以重心扇形三角化）拉高 h。"""
    cx, cy = np.mean([p[0] for p in poly]), np.mean([p[1] for p in poly])
    t = []
    n = len(poly)
    for i in range(n):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % n]
        t += [[(cx, cy, z0), (x1, y1, z0), (x0, y0, z0)], [(cx, cy, z0 + h), (x0, y0, z0 + h), (x1, y1, z0 + h)]]
        t += _quad((x0, y0, z0), (x1, y1, z0), (x1, y1, z0 + h), (x0, y0, z0 + h))
    return np.array(t, dtype=np.float64)


def box(sx, sy, sz, x=0, y=0, z=0):
    return extrude([(x - sx / 2, y - sy / 2), (x + sx / 2, y - sy / 2), (x + sx / 2, y + sy / 2), (x - sx / 2, y + sy / 2)], sz, z)


def sphere(r, z=0.0, x=0.0, seg=28):
    prof = [(r * math.sin(math.pi * i / 16), z - r * math.cos(math.pi * i / 16)) for i in range(17)]
    t = lathe(prof, seg)
    t[..., 0] += x
    return t


def torus(R, r, seg=36, tseg=16):
    t = []
    for i in range(seg):
        for j in range(tseg):
            def p(i, j):
                u, v = 2 * math.pi * i / seg, 2 * math.pi * j / tseg
                return ((R + r * math.cos(v)) * math.cos(u), (R + r * math.cos(v)) * math.sin(u), r * math.sin(v) + r)
            t += _quad(p(i, j), p(i + 1, j), p(i + 1, j + 1), p(i, j + 1))
    return np.array(t, dtype=np.float64)


def star(n=5, ro=30, ri=13):
    return [(ro if k % 2 == 0 else ri) * np.array([math.cos(math.pi * k / n + math.pi / 2), math.sin(math.pi * k / n + math.pi / 2)]) for k in range(2 * n)]


def heart():
    pts = []
    for k in range(48):
        t = 2 * math.pi * k / 48
        pts.append((16 * math.sin(t) ** 3 * 1.8, (13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)) * 1.8))
    return pts


def gear(teeth=14, ro=30, ri=24):
    pts = []
    for k in range(teeth * 4):
        a = 2 * math.pi * k / (teeth * 4)
        r = ro if (k % 4) in (1, 2) else ri
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def shapes(cat_stl=None):
    """{名字: 三角面}"""
    S = {
        "cube": box(40, 40, 40),
        "tallbox": box(22, 22, 70),
        "cylinder": lathe([(0, 0), (20, 0), (20, 45), (0, 45)]),
        "hexprism": extrude([(20 * math.cos(math.pi * k / 3), 20 * math.sin(math.pi * k / 3)) for k in range(6)], 45),
        "cone": lathe([(0, 0), (22, 0), (0, 55)]),
        "sphere": sphere(24, 24),
        "snowman": np.concatenate([sphere(20, 20), sphere(13, 50), lathe([(0, 62), (6, 62), (0, 75)])]),
        "ring": torus(26, 7),
        "vase": lathe([(0, 0), (16, 0), (22, 12), (14, 35), (9, 50), (13, 62), (0, 62)]),
        "star": extrude(star(), 10),
        "heart": extrude(heart(), 10),
        "gear": extrude(gear(), 12),
        "cup": np.concatenate([lathe([(0, 0), (20, 0), (21, 42), (0, 42)]), torus(10, 3)[:, :, [0, 2, 1]] + np.array([26, 0, 10])]),
        "pyramid": np.concatenate([extrude([(-25, -25), (25, -25), (25, 25), (-25, 25)], 0.1),
                                   np.array([[(-25, -25, 0), (25, -25, 0), (0, 0, 40)], [(25, -25, 0), (25, 25, 0), (0, 0, 40)],
                                             [(25, 25, 0), (-25, 25, 0), (0, 0, 40)], [(-25, 25, 0), (-25, -25, 0), (0, 0, 40)]], float)]),
        "bracket": np.concatenate([box(50, 30, 8), box(8, 30, 50, x=-21)]),
        "keychain": np.concatenate([extrude([(-30, -12), (22, -12), (30, 0), (22, 12), (-30, 12)], 4), torus(5, 1.5) + np.array([-22, 0, 4])]),
        "stand": np.concatenate([box(60, 50, 6), box(6, 50, 45, x=10, z=6)]),
        "tower": np.concatenate([box(36, 36, 15), box(26, 26, 15, z=15), box(16, 16, 15, z=30), box(8, 8, 15, z=45)]),
    }
    if cat_stl is not None:
        S["cat"] = cat_stl
    return S


PALETTE = {"白色": (244, 244, 242), "黑色": (32, 33, 36), "灰色": (138, 141, 145), "红色": (214, 47, 47), "粉色": (242, 155, 184),
           "紫色": (138, 79, 191), "蓝色": (36, 86, 199), "天蓝色": (108, 184, 232), "绿色": (46, 157, 79), "黄色": (245, 205, 46),
           "橙色": (240, 127, 34), "金色": (212, 169, 55), "荧光绿": (100, 240, 90)}

# 产品 → 颜色（同形状不同色、同色不同形状都有；白色的最多，最难）
CATALOG = {
    "cube": ["白色", "黑色", "红色"], "tallbox": ["白色"], "cylinder": ["白色", "蓝色"], "hexprism": ["白色"], "cone": ["橙色"],
    "sphere": ["白色", "粉色"], "snowman": ["白色"], "ring": ["绿色", "黄色"], "vase": ["白色", "紫色"], "star": ["黄色", "红色"],
    "heart": ["红色", "粉色"], "gear": ["灰色", "黑色"], "cup": ["白色", "天蓝色"], "pyramid": ["金色"], "bracket": ["黑色"],
    "keychain": ["蓝色", "绿色", "橙色"], "stand": ["白色", "黑色"], "tower": ["灰色"], "cat": ["白色", "粉色", "荧光绿"],
}


# ---------------- 背景 ----------------
def background(kind, w, h, rng):
    if kind == "white":
        base = np.full((h, w, 3), rng.uniform(225, 250), np.float32) + rng.normal(0, 2, (1, 1, 3))
        yy = np.linspace(0, 1, h)[:, None, None]
        return np.clip(base - 18 * yy, 0, 255)
    if kind == "table":
        c = np.array(rng.choice([(150, 150, 150), (95, 100, 110), (200, 195, 185), (60, 62, 66)]), np.float32)
        a = np.tile(c, (h, w, 1)) + rng.normal(0, 3, (h, w, 3))
        return np.clip(a, 0, 255)
    if kind == "wood":
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        ang = rng.uniform(0, math.pi)
        u = xx * math.cos(ang) + yy * math.sin(ang)
        g = np.sin(u / rng.uniform(6, 14) + 3 * np.sin(u / 90 + yy / 70)) * 0.5 + 0.5
        c1, c2 = np.array([160, 110, 65], np.float32), np.array([120, 75, 40], np.float32)
        a = c1[None, None] * (1 - g[..., None]) + c2[None, None] * g[..., None] + rng.normal(0, 4, (h, w, 3))
        return np.clip(a, 0, 255)
    if kind == "hand":                             # 手拿着：大块肤色 + 后面杂乱
        a = background("table", w, h, rng)
        yy, xx = np.mgrid[0:h, 0:w]
        skin = np.array(rng.choice([(224, 172, 140), (198, 134, 100), (150, 100, 70)]), np.float32)
        cx, cy = w * rng.uniform(0.35, 0.65), h * rng.uniform(0.75, 1.0)
        m = ((xx - cx) / (w * 0.32)) ** 2 + ((yy - cy) / (h * 0.30)) ** 2 < 1
        a[m] = skin + rng.normal(0, 5, (m.sum(), 3))
        return a
    if kind == "clutter":
        a = background("table", w, h, rng)
        im = Image.fromarray(a.astype(np.uint8))
        d = ImageDraw.Draw(im)
        for _ in range(6):
            x0, y0 = rng.uniform(0, w), rng.uniform(0, h)
            cut = rng.uniform(0.05, 0.2) * w
            if not (w * 0.25 < x0 < w * 0.75 and h * 0.25 < y0 < h * 0.75):
                d.rectangle([x0, y0, x0 + cut, y0 + cut * rng.uniform(0.5, 2)], fill=tuple(int(x) for x in rng.integers(0, 255, 3)))
        return np.asarray(im, np.float32)
    raise ValueError(kind)


BGS = ["white", "table", "wood", "hand", "clutter"]


# ---------------- 「手机照片」 ----------------
def photo(tris, rgb, rng, vary=(), size=480, prepared=None):
    """模拟员工用手机拍的照片。vary：要加强的变化（rotate / tilt / scale / crop / bg / light / wb / blur / jpeg / noise / color）。
    每种变化没点名时也有一点点（真实照片总有一点）。返回 JPEG bytes。"""
    t = prepared if prepared is not None else render.prepare(tris)
    full = "all" in vary                            # 全部一起（每样都中等强度，像真实拍照）
    V = lambda k: full or k in vary  # noqa: E731
    M = lambda lo, hi, mlo, mhi: rng.uniform(mlo, mhi) if full else rng.uniform(lo, hi)  # noqa: E731
    az = rng.uniform(0, 360)
    el = rng.uniform(8, 65) if V("tilt") else rng.uniform(15, 45)
    roll = rng.uniform(0, 360) if V("rotate") else rng.uniform(-8, 8)
    persp = rng.uniform(0.15, 0.4) if V("tilt") else rng.uniform(0, 0.08)
    light = (rng.uniform(-1, 1), rng.uniform(-1, -0.2), rng.uniform(0.2, 1))
    px = 256
    sh, m = render.shade_view(t, az, el, px, light=light, roll=roll, persp=persp)
    col = np.array(rgb, np.float32)
    if V("color"):                                  # 3D 渲染的颜色 ≠ 实物耗材颜色：色相、饱和度、亮度都偏一点
        hsv = np.asarray(Image.fromarray(np.uint8([[col]])).convert("HSV"), np.float32)[0, 0]
        hsv[0] = (hsv[0] + rng.uniform(-10, 10)) % 255
        hsv[1] = np.clip(hsv[1] * rng.uniform(0.75, 1.15), 0, 255)
        hsv[2] = np.clip(hsv[2] * rng.uniform(0.8, 1.05), 0, 255)
        col = np.asarray(Image.fromarray(np.uint8([[hsv]]), "HSV").convert("RGB"), np.float32)[0, 0]
    obj = render.colorize(sh, m, col, spec=rng.uniform(0.05, 0.2))
    W = H = size
    bgk = rng.choice(BGS) if V("bg") else rng.choice(["white", "table"])
    bg = background(bgk, W, H, rng)
    scale = M(0.3, 1.0, 0.4, 0.9) if V("scale") else rng.uniform(0.55, 0.85)
    osz = int(W * scale)
    o = obj.resize((osz, osz), Image.BILINEAR)
    ox = int((W - osz) / 2 + rng.uniform(-0.1, 0.1) * (W - osz * 0.7))
    oy = int((H - osz) / 2 + rng.uniform(-0.1, 0.1) * (H - osz * 0.7))
    im = Image.fromarray(bg.astype(np.uint8))
    # 影子
    shadow = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shadow)
    sd.ellipse([ox + osz * 0.15, oy + osz * 0.75, ox + osz * 0.95, oy + osz * 0.98], fill=int(rng.uniform(40, 110)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(osz * 0.05 + 1))
    im = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, shadow)
    im.paste(o, (ox, oy), o)
    if V("crop"):                                   # 只拍到一部分（产品被画面切掉 10~30%）
        f = M(0.1, 0.3, 0.05, 0.15)
        side = rng.integers(0, 4)
        if side == 0:
            box_ = (int(ox + osz * f), 0, W, H)
        elif side == 1:
            box_ = (0, 0, int(ox + osz * (1 - f)), H)
        elif side == 2:
            box_ = (0, int(oy + osz * f), W, H)
        else:
            box_ = (0, 0, W, int(oy + osz * (1 - f)))
        im = im.crop(box_)
    if V("light"):
        im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.45, 1.5))
        im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.7, 1.2))
    else:
        im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.92, 1.08))
    a = np.asarray(im, np.float32)
    if V("wb"):                                     # 白平衡偏（黄灯 / 白光 / 阴天）
        g = np.array([rng.uniform(0.8, 1.2), 1.0, rng.uniform(0.75, 1.2)], np.float32)
        a = a * g
    if V("noise"):
        a = a + rng.normal(0, rng.uniform(6, 14), a.shape)
    else:
        a = a + rng.normal(0, 2, a.shape)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if V("blur"):
        im = im.filter(ImageFilter.GaussianBlur(rng.uniform(1.5, 4)))
    q = int(rng.uniform(25, 55)) if V("jpeg") else 85
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    return buf.getvalue()


def ref_image(tris, rgb, az=30, el=25, px=600, bg=(255, 255, 255)):
    """「产品主图」：白底、斜上方（像上架用的渲染图），JPEG bytes。"""
    t = render.prepare(tris)
    sh, m = render.shade_view(t, az, el, 256)
    o = render.colorize(sh, m, rgb).resize((px, px), Image.BILINEAR)
    im = Image.new("RGB", (px, px), bg)
    im.paste(o, (0, 0), o)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


# ---------------- 文字（货位牌、面单） ----------------
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
         "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf", "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
         "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf", "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf"]


def _font(size, k=0):
    for p in FONTS[k % len(FONTS):] + FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def text_image(text, rng, angle=0, blur=0.0, glare=False, dark=False, barcode=False, size=64, font=0):
    """货位牌 / 标签：白底黑字，可以转一点角度、模糊、反光、暗、上面有一个坏掉的条码。返回 JPEG bytes。"""
    f = _font(size, font)
    w = int(f.getlength(text)) + 60
    h = size + 50 + (90 if barcode else 0)
    im = Image.new("RGB", (w, h), (250, 250, 245))
    d = ImageDraw.Draw(im)
    y = 20
    if barcode:
        x = 30
        while x < w - 30:
            bw = int(rng.integers(1, 5))
            if rng.random() < 0.55:
                d.rectangle([x, 15, x + bw, 90], fill=(10, 10, 10))
            x += bw + int(rng.integers(1, 4))
        d.rectangle([w * 0.3, 30, w * 0.55, 70], fill=(250, 250, 245))     # 条码被划坏一块
        y = 100
    d.text((30, y), text, fill=(15, 15, 15), font=f)
    bg = Image.new("RGB", (w + 120, h + 120), (120, 110, 100))
    bg.paste(im, (60, 60))
    im = bg.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(120, 110, 100))
    a = np.asarray(im, np.float32)
    if glare:
        yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
        g = np.exp(-(((xx - a.shape[1] * 0.4) / (a.shape[1] * 0.18)) ** 2 + ((yy - a.shape[0] * 0.5) / (a.shape[0] * 0.3)) ** 2))
        a = a + 150 * g[..., None]
    if dark:
        a = a * 0.35 + rng.normal(0, 8, a.shape)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70)
    return buf.getvalue()


# ---------------- 在测试数据里建产品（3D 模型 + 颜色规格，可选白底产品图） ----------------
COLOR_CODE = {"白色": "WH", "黑色": "BK", "灰色": "GY", "红色": "RD", "粉色": "PK", "紫色": "PU", "蓝色": "BL", "天蓝色": "SB",
              "绿色": "GN", "黄色": "YL", "橙色": "OR", "金色": "GD", "荧光绿": "C1",
              "透明": "CL", "随机颜色": "RND", "多色": "MC"}


def make_product(pid, name, tris, colors, image_colors=(), extra_images=()):
    """建一个产品：data/products/<pid>/model/model.stl + 每个颜色一个规格（SKU = pid-颜色代码）；
    image_colors：这些颜色另外放一张白底产品图（像上架用的主图）。返回产品资料。"""
    import os
    from core import mesh, store
    p = store.blank_product(pid)
    p["name_zh"] = name
    p["variants"] = [{"opt1_zh": c, "opt2_zh": "", "sku": f"{pid}-{COLOR_CODE.get(c, 'X')}", "image": "", "grams": 10, "hours": 1,
                      "manual_price": None, "stock": None} for c in colors]
    d = store.image_dir(pid, "model")
    mesh.write_stl(np.asarray(tris, dtype=np.float64), os.path.join(d, "model.stl"))
    p["model"] = {"file": "model.stl", "ext": "stl"}
    for k, c in enumerate(image_colors):
        fn = f"img_{k}.jpg"
        with open(os.path.join(store.image_dir(pid, "out"), fn), "wb") as f:
            f.write(ref_image(tris, PALETTE[c], az=30 + 40 * k))
        p["images"].append({"file": fn, "raw": fn, "processed": True, "color": c})
        for v in p["variants"]:
            if v["opt1_zh"] == c and not v["image"]:
                v["image"] = fn
    for fn, data, c in extra_images:
        with open(os.path.join(store.image_dir(pid, "out"), fn), "wb") as f:
            f.write(data)
        p["images"].append({"file": fn, "raw": fn, "processed": True, "color": c})
    store.save(p)
    return p
