"""编码规则。

产品编码（SPU）：前缀 + 4 位顺序号，例如 3DP0001、3DP0002……新建时自动分配，永不重复使用。
SKU 编码：SPU-颜色代码[-规格代码]，例如 3DP0001-WH、3DP0001-BK-L。
  - 颜色代码来自颜色字典（设置页可增改），一眼就能看出颜色，排产时也直接用。
  - 规格代码：小/中/大 → S/M/L；10cm → 10CM；其他按出现顺序 O1、O2……
  - 一旦导出过 Lazada，SKU 就锁定不再自动变化（防止平台上的 SellerSKU 对不上）。
"""
import re

# 中文, 代码, 泰文, 英文
DEFAULT_COLORS = [
    ("白色", "WH", "สีขาว", "White"),
    ("黑色", "BK", "สีดำ", "Black"),
    ("灰色", "GY", "สีเทา", "Grey"),
    ("银色", "SV", "สีเงิน", "Silver"),
    ("金色", "GD", "สีทอง", "Gold"),
    ("红色", "RD", "สีแดง", "Red"),
    ("粉色", "PK", "สีชมพู", "Pink"),
    ("紫色", "PU", "สีม่วง", "Purple"),
    ("蓝色", "BL", "สีน้ำเงิน", "Blue"),
    ("天蓝色", "SB", "สีฟ้า", "Sky Blue"),
    ("绿色", "GN", "สีเขียว", "Green"),
    ("黄色", "YL", "สีเหลือง", "Yellow"),
    ("橙色", "OR", "สีส้ม", "Orange"),
    ("棕色", "BR", "สีน้ำตาล", "Brown"),
    ("米色", "BG", "สีเบจ", "Beige"),
    ("透明", "CL", "สีใส", "Clear"),
    ("木纹", "WD", "ลายไม้", "Wood"),
    ("大理石纹", "MB", "ลายหินอ่อน", "Marble"),
    ("夜光", "GW", "เรืองแสง", "Glow in the Dark"),
    ("彩虹渐变", "RB", "สีรุ้ง", "Rainbow"),
    ("多色", "MC", "หลายสี", "Multicolor"),
    ("随机颜色", "RND", "สีสุ่ม (คละสี)", "Random"),
]
RANDOM_CODE = "RND"          # 随机颜色：客人不挑颜色，接单时系统按耗材自动选（v2.16）
RANDOM_ROW = ("随机颜色", "RND", "สีสุ่ม (คละสี)", "Random")

SIZE_CODES = {"迷你": "XS", "特小": "XS", "小": "S", "小号": "S", "中": "M", "中号": "M",
              "大": "L", "大号": "L", "特大": "XL", "加大": "XL", "超大": "XXL"}


def color_table(cfg):
    rows = cfg.get("color_table") or []
    out = []
    for r in rows:
        if isinstance(r, (list, tuple)) and len(r) >= 2 and r[0] and r[1]:
            out.append((str(r[0]).strip(), str(r[1]).strip().upper(),
                        str(r[2]).strip() if len(r) > 2 else "", str(r[3]).strip() if len(r) > 3 else ""))
    out = out or list(DEFAULT_COLORS)
    if not any(r[1] == RANDOM_CODE for r in out):     # 设置里自己改过颜色表的，也总有「随机颜色」
        out = list(out) + [RANDOM_ROW]
    return out


def is_random(cfg, name):
    c = find_color(cfg, name)
    return bool(c and c[1] == RANDOM_CODE)


# 渲染商品图用的颜色（按颜色代码），设置页颜色表第 5 列可以覆盖
COLOR_HEX = {
    "WH": "#f4f4f2", "BK": "#202124", "GY": "#8a8d91", "SV": "#c7c9cc", "GD": "#d4a937", "RD": "#d62f2f",
    "PK": "#f29bb8", "PU": "#8a4fbf", "BL": "#2456c7", "SB": "#6cb8e8", "GN": "#2e9d4f", "YL": "#f5cd2e",
    "OR": "#f07f22", "BR": "#7a4b2a", "BG": "#e3d3b5", "CL": "#d9eef5", "WD": "#a0703f", "MB": "#e9e7e3",
    "GW": "#c9f2b8", "RB": "#ff6b6b", "MC": "#ff6b6b", "RND": "#ff6b6b",
}


def color_hex(cfg):
    """颜色中文名 → 渲染颜色。"""
    out = {}
    raw = {str(r[0]).strip(): (str(r[4]).strip() if isinstance(r, (list, tuple)) and len(r) > 4 else "")
           for r in (cfg.get("color_table") or []) if r}
    for zh, code, th, en in color_table(cfg):
        out[zh] = {"code": code, "hex": raw.get(zh) or COLOR_HEX.get(code, "#bbbbbb"), "th": th, "en": en}
    return out


def _norm(s):
    s = re.sub(r"\s+", "", str(s or "")).lower()
    return s[2:] if s.startswith("สี") and len(s) > 2 else s  # 泰文“สีชมพู”和“ชมพู”视为相同


def find_color(cfg, name):
    """按中文/泰文/英文/代码匹配颜色；“白”也能匹配“白色”。"""
    n = _norm(name)
    if not n:
        return None
    table = color_table(cfg)
    for row in table:
        zh, code, th, en = row
        if n in (_norm(zh), _norm(code), _norm(th), _norm(en)):
            return row
    for row in table:
        if _norm(row[0]).rstrip("色") == n.rstrip("色"):
            return row
    return None


def option_code(text):
    t = str(text or "").strip()
    if not t:
        return ""
    if t in SIZE_CODES:
        return SIZE_CODES[t]
    a = re.sub(r"[^A-Za-z0-9]", "", t).upper()
    return a[:8]


def ensure_skus(cfg, product):
    """给每个变体生成 SKU；已导出过的产品保持原 SKU 不变。"""
    pid = product["id"]
    locked = bool(product.get("exported_at"))
    spec_en = {x.get("spec_id"): x.get("name_en") for x in product.get("specs") or [] if x.get("name_en")}
    # v2.38：已导出产品先把所有锁定的 SKU 记下，新生成的不会和排在后面的旧 SKU 重复
    used = {v["sku"] for v in product.get("variants", []) if v.get("sku")} if locked else set()
    fallback = {}
    for i, v in enumerate(product.get("variants", [])):
        if locked and v.get("sku"):
            continue
        parts = [pid]
        c = find_color(cfg, v.get("opt1_zh"))
        if c:
            parts.append(c[1])
        elif (v.get("opt1_zh") or "").strip():
            code = option_code(v["opt1_zh"])
            if not code:
                key = ("1", v["opt1_zh"].strip())
                code = fallback.setdefault(key, f"C{len([k for k in fallback if k[0] == '1']) + 1}")
            parts.append(code)
        o2 = (v.get("opt2_zh") or "").strip()
        sp = spec_en.get(v.get("spec_id")) if v.get("spec_id") else None
        if o2:
            code = option_code(sp) if sp else option_code(o2)     # 选品工具给了英文规格名（name_en）优先用
            if not code:
                key = ("2", o2)
                code = fallback.setdefault(key, f"O{len([k for k in fallback if k[0] == '2']) + 1}")
            parts.append(code)
        sku = "-".join(parts)
        if len(product.get("variants", [])) > 1 and sku == pid:
            sku = f"{pid}-{i + 1:02d}"
        base, n = sku, 2
        while sku in used:
            sku = f"{base}-{n}"
            n += 1
        used.add(sku)
        v["sku"] = sku
    return product


def option_th(cfg, product, zh):
    """选项泰文：颜色优先用字典（统一），其次用选品工具 / AI / 自己填的选项泰文。找不到返回原文（上架检查会拦住带中文的）。"""
    c = find_color(cfg, zh)
    if c and c[2]:
        return c[2]
    t = (product.get("copy", {}).get("options_th") or {}).get(zh)
    if t:
        return t
    for s in product.get("specs") or []:
        if s.get("name_zh") == zh and s.get("name_th"):
            return s["name_th"]
    return zh


# 变体名称（「颜色」「规格」）的泰文：没填时用这些常用说法
VAR_NAME_TH = {"颜色": "สี", "色": "สี", "规格": "ตัวเลือก", "尺寸": "ขนาด", "大小": "ขนาด", "款式": "แบบ", "型号": "รุ่น",
               "套装": "ชุด", "数量": "จำนวน", "材质": "วัสดุ", "图案": "ลาย"}


def variation_name_th(product, n):
    """变体 1 / 2 名称的泰文：自己填的 → 常用说法对照 → 原文（带中文时上架检查会拦住）。"""
    c = product.get("copy", {})
    th = (c.get(f"variation{n}_name_th") or "").strip()
    if th:
        return th
    zh = (product.get(f"variation{n}_name_zh") or "").strip()
    return VAR_NAME_TH.get(zh) or (("สี" if n == 1 else "ตัวเลือก") if not zh else zh)
