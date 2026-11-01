"""「随机颜色」变体的商品图角标（v2.54.1）。

随机颜色没有固定的真实颜色：模型用中性浅灰（codes.NEUTRAL_HEX）渲染，图片右下角加一个小角标——
一排小圆点（颜色表里最常用的几种颜色）+ 文字「随机颜色」/「สีสุ่ม」。
设置 → 图片 →「随机颜色加标识」（random_badge，默认开）可以关；random_badge_lang = thai / chinese / bilingual。
"""
import os

from PIL import Image, ImageDraw, ImageFont

from . import codes

TEXT = {"th": "สีสุ่ม", "zh": "随机颜色"}
FONT_DIRS = ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]
THAI_FONTS = ["Loma", "Garuda", "Kinnari", "Norasi", "Waree", "Umpush", "Laksaman", "NotoSansThai", "Kanit", "Prompt", "FreeSans"]
CJK_FONTS = ["NotoSansCJK", "NotoSansSC", "wqy-zenhei", "wqy-microhei", "DroidSansFallback", "SourceHanSans", "unifont"]
LAST_FONTS = ["DejaVuSans-Bold", "DejaVuSans", "LiberationSans-Bold"]
_cache = {}


def _scan():
    if "files" not in _cache:
        dirs = list(FONT_DIRS)
        try:
            from . import adimg
            dirs.append(adimg.FONT_DIR)
        except Exception:  # noqa: BLE001
            pass
        files = []
        for d in dirs:
            for root, _dn, fn in os.walk(d):
                files += [os.path.join(root, f) for f in fn if f.lower().endswith((".ttf", ".otf", ".ttc"))]
        _cache["files"] = sorted(files)
    return _cache["files"]


def find_font(kind, px):
    """kind=th / zh；找不到专用字体就退到 DejaVu（至少不报错）。"""
    key = (kind, px)
    if key in _cache:
        return _cache[key]
    f = None
    for nm in (THAI_FONTS if kind == "th" else CJK_FONTS) + LAST_FONTS:
        for fp in _scan():
            if os.path.basename(fp).lower().startswith(nm.lower()):
                try:
                    f = ImageFont.truetype(fp, px)
                    break
                except Exception:  # noqa: BLE001
                    continue
        if f:
            break
    f = f or ImageFont.load_default()
    _cache[key] = f
    return f


def _label(lang):
    if lang in ("bilingual", "both"):
        return [("th", TEXT["th"]), ("zh", TEXT["zh"])]
    k = "zh" if lang in ("chinese", "zh") else "th"
    return [(k, TEXT[k])]


def dots_for(cfg, n=5):
    """角标上的小圆点颜色：颜色表里用得最多的几种真实颜色。"""
    prods = []
    try:
        from . import store
        for row in store.list_products()[:400]:
            try:
                prods.append(store.load(row["id"]))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return [c["hex"] for c in codes.popular_colors(cfg, n, prods)]


def draw_badge(img, dots, lang="th"):
    """在图片右下角画角标，返回新图（RGB）。dots：十六进制颜色列表。"""
    img = img.convert("RGB")
    W, H = img.size
    S = min(W, H)
    scale = 3                                              # 超采样抗锯齿
    unit = S * 0.034                                       # 圆点直径
    pad = unit * 0.55
    gap = unit * 0.32
    fpx = max(10, int(unit * 1.05))
    parts = _label(lang)
    fonts = [find_font(k, fpx * scale) for k, _t in parts]
    tmp = ImageDraw.Draw(Image.new("L", (4, 4)))
    tw = [tmp.textlength(t, font=f) / scale for (_k, t), f in zip(parts, fonts)]
    sep = unit * 0.5
    text_w = sum(tw) + sep * (len(tw) - 1)
    dots = list(dots or [])[:6]
    dots_w = len(dots) * unit + max(0, len(dots) - 1) * (gap * 0.5)
    bw = pad * 2 + dots_w + (gap * 1.4 if dots else 0) + text_w
    bh = unit + pad * 2
    margin = S * 0.025
    x0, y0 = W - margin - bw, H - margin - bh
    layer = Image.new("RGBA", (int(bw * scale) + 2, int(bh * scale) + 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([0, 0, bw * scale, bh * scale], radius=bh * scale / 2, fill=(255, 255, 255, 235),
                        outline=(190, 186, 178, 255), width=scale)
    cx = pad * scale
    cy = bh * scale / 2
    r = unit * scale / 2
    for h in dots:
        d.ellipse([cx, cy - r, cx + 2 * r, cy + r], fill=codes.valid_hex(h) or "#bbbbbb", outline=(120, 120, 120, 255), width=max(1, scale // 2))
        cx += unit * scale + gap * 0.5 * scale
    if dots:
        cx += gap * 0.9 * scale
    for (_k, t), f, w in zip(parts, fonts, tw):
        d.text((cx, cy), t, font=f, fill=(60, 60, 60, 255), anchor="lm")
        cx += (w + sep) * scale
    layer = layer.resize((max(1, int(bw)), max(1, int(bh))), Image.LANCZOS)
    out = img.copy()
    out.paste(layer, (int(x0), int(y0)), layer)
    return out


def apply(img, cfg, enabled=None):
    """按设置给图片加角标；enabled=None 看设置 random_badge（默认开）。返回 (图, 是否加了)。"""
    on = cfg.get("random_badge", True) if enabled is None else enabled
    if not on:
        return img, False
    return draw_badge(img, dots_for(cfg), cfg.get("random_badge_lang") or "thai"), True
