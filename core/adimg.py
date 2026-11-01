"""卖点图（商品图上加广告词）：AI 只负责「推荐」卖点文字，位置和内容由人在编辑器里确认 / 修改。

- suggest(product)       AI 根据产品资料推荐：大标题、角标、5–8 条短卖点（泰语 + 中文意思 + 图标），不会自动放到图上
- 设计稿保存在 product["ad_designs"][id] = {base, template, theme, font, layers, file}，以后可以再打开修改
- thai_css()             泰语字体（Kanit / Prompt，开源免费可商用）：第一次用时从 Google Fonts 下载到 data/fonts，
                         之后都从本机读取；下载不了时用系统自带泰语字体，不影响使用
"""
import hashlib
import json
import os
import re
import threading
import time

import requests

from . import ai_copy
from .config import DATA_DIR

FONT_DIR = os.path.join(DATA_DIR, "fonts")
FONT_CSS = os.path.join(FONT_DIR, "thai2.css")   # v2.14：字体多了，换个文件名重新下载一次
GOOGLE_CSS = ("https://fonts.googleapis.com/css2?family=Kanit:wght@400;500;700;800&family=Prompt:wght@400;600;800"
              "&family=Sarabun:wght@400;600;800&family=Mitr:wght@400;500;700&family=Chakra+Petch:wght@500;700&display=swap")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
ICONS = ["check", "truck", "star", "ruler", "palette", "gift", "shield", "heart", "sparkle", "clock", "box", "leaf", "home", "tag"]

SYSTEM = """You write short selling-point text for e-commerce product images on Shopee / Lazada / TikTok Thailand.
Rules:
- Thai, very short and punchy: each point 2-6 words (max ~22 Thai characters), no full sentences, no emoji.
- Facts only from the seller data (size, material, colours, use). Never invent specs, certificates or awards.
- NEVER mention how the product is made: no 3D printing, printers, filament, layer lines, handmade, made to order.
- NEVER use third-party brand, character, anime or game names.
- No price claims, no "cheapest", no "best in Thailand", no medical/safety claims (food safe, non-toxic) unless
  the seller data says so.
- Output ONLY JSON:
{"headline_th": "main headline 2-6 words", "headline_zh": "...",
 "sub_th": "one short supporting line", "sub_zh": "...",
 "badge_th": ["2-4 short badge words options, e.g. ขายดี, ใหม่, พร้อมส่ง, สั่งทำได้"],
 "points": [{"th": "...", "zh": "...", "icon": "one of ICONS", "kind": "feature|size|color|use|gift|service"}]}
Give 6-8 points covering: main benefit, use scenes, size (with the real number if given), colours/options,
gift idea, and service points from the shop policy (e.g. custom name/colour, fast shipping time if given)."""


def suggest(cfg, product, shop_policy=""):
    sizes = (product.get("model") or {}).get("metrics", {}).get("size")
    size_txt = product.get("size_text") or ""
    if not size_txt and isinstance(sizes, (list, tuple)) and len(sizes) == 3:
        size_txt = " × ".join(f"{float(x) / 10:.1f}" for x in sizes) + " ซม."
    colors = []
    for v in product.get("variants", []):
        for k in ("opt1_zh", "opt2_zh"):
            val = (v.get(k) or "").strip()
            if val and val not in colors:
                colors.append(val)
    copy = product.get("copy") or {}
    user = json.dumps({
        "ICONS": ICONS,
        "产品名称": product.get("name_zh", ""), "泰文标题": copy.get("title_th", ""),
        "卖点/用途": product.get("features_zh", ""), "AI 文案里的卖点": copy.get("highlights_th") or [],
        "材料": product.get("material", ""), "尺寸": size_txt, "颜色/选项": colors[:12],
        "店铺服务（可以作为卖点）": shop_policy,
    }, ensure_ascii=False)
    d = ai_copy.extract_json(ai_copy.call(ai_copy.tcfg(cfg, "adtext"), SYSTEM, user))
    pts = []
    for p in d.get("points") or []:
        th = str(p.get("th") or "").strip()
        if not th or ai_copy.mentions_process(th):
            continue
        pts.append({"th": th[:40], "zh": str(p.get("zh") or "")[:60],
                    "icon": p.get("icon") if p.get("icon") in ICONS else "check", "kind": str(p.get("kind") or "")})
    badges = [str(b).strip()[:16] for b in (d.get("badge_th") or []) if str(b).strip() and not ai_copy.mentions_process(str(b))]
    return {"headline_th": _clean(d.get("headline_th")), "headline_zh": str(d.get("headline_zh") or ""),
            "sub_th": _clean(d.get("sub_th")), "sub_zh": str(d.get("sub_zh") or ""),
            "badges": badges[:4], "points": pts[:8], "icons": ICONS}


def _clean(t):
    t = str(t or "").strip()
    return "" if ai_copy.mentions_process(t) else t[:60]


def save_design(product, design, image_file):
    """记下设计稿（以后可以再改），返回设计 id。"""
    designs = product.setdefault("ad_designs", {})
    did = design.get("id") or hashlib.md5(f"{time.time()}".encode()).hexdigest()[:10]
    keep = {k: design.get(k) for k in ("base", "template", "theme", "font", "layers", "img", "palette") if k in design}
    keep.update(id=did, file=image_file, updated=time.time())
    designs[did] = keep
    return did


# ---------------- 泰语字体（本机缓存） ----------------
_font_lock = threading.Lock()
_font_try = {"t": 0}


def thai_css():
    """返回本机缓存的字体 CSS；没有时后台去下载一次（10 分钟内不重复尝试）。"""
    if os.path.exists(FONT_CSS):
        with open(FONT_CSS, encoding="utf-8") as f:
            return f.read()
    if time.time() - _font_try["t"] > 600:
        _font_try["t"] = time.time()
        threading.Thread(target=_download_fonts, daemon=True, name="fonts").start()
    return "/* 泰语字体还没有下载好，暂时用系统字体 */"


def _download_fonts():
    with _font_lock:
        try:
            css = requests.get(GOOGLE_CSS, headers={"User-Agent": UA}, timeout=15).text
            urls = re.findall(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", css)
            if not urls:
                return
            os.makedirs(FONT_DIR, exist_ok=True)
            for u in dict.fromkeys(urls):
                name = hashlib.md5(u.encode()).hexdigest()[:16] + os.path.splitext(u.split("?")[0])[1]
                path = os.path.join(FONT_DIR, name)
                if not os.path.exists(path):
                    r = requests.get(u, headers={"User-Agent": UA}, timeout=30)
                    r.raise_for_status()
                    with open(path + ".tmp", "wb") as f:
                        f.write(r.content)
                    os.replace(path + ".tmp", path)
                css = css.replace(u, "/fonts/f/" + name)
            with open(FONT_CSS + ".tmp", "w", encoding="utf-8") as f:
                f.write(css)
            os.replace(FONT_CSS + ".tmp", FONT_CSS)
        except Exception as e:  # noqa: BLE001  没网等：用系统字体
            print("泰语字体下载失败（不影响使用）：", e)
