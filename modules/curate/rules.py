"""规则（从「3D选品工具」搬过来）：许可证初判、泰国市场的排除规则、类目先验、品牌 / 动漫角色词、颜色词和营销词、
候选打分（六项加权）、估算校准。都是纯函数（不碰数据库），测试直接调。

打分的六项（每项 0–100，权重在「设置 → 商品 → 选品」）：
  demand 泰国需求 · production 生产效率（时长 / 克数 / 单色 / 零件数）· profit 利润（ERP 成本价 vs 估计售价）
  competition 竞争少 · popularity 原站热度 · listing 上架难度
命中排除规则的（儿童玩具（TISI）、宗教、武器、接触食物、成人、品牌 / 动漫角色、打印太久）标红，不推荐。
v2.52：多色不再排除（有拓竹 P1S + AMS 能打多色）：标「多色（需要 AMS）」，生产效率和利润分扣一些（换色冲刷废料、时间长、只能上 AMS 机）。
"""
import math
import re

from core import copyrules

# ---------------- 许可证初判（只是初判，转产品前必须人工核验） ----------------
LIC_OK, LIC_NO, LIC_UNKNOWN = "可考虑商用", "禁止商用", "许可不明"
LIC_TH = {LIC_OK: "อาจใช้เชิงพาณิชย์ได้", LIC_NO: "ห้ามใช้เชิงพาณิชย์", LIC_UNKNOWN: "ไม่ทราบสัญญาอนุญาต"}


def classify_license(name, url=""):
    """返回 (结论, 说明)：可考虑商用 / 禁止商用 / ""（看不出来）。"""
    text = f"{name or ''} {url or ''}".lower().strip()
    short = (name or "").lower().strip()
    if not text:
        return "", ""
    if "standard digital file" in text:
        return LIC_NO, "MakerWorld 标准数字文件许可：仅个人使用"
    if "all rights reserved" in text:
        return LIC_NO, "保留所有权利"
    if re.search(r"(?:^|[\s(/-])nc(?:$|[\s)/-])|non-?commercial|by-nc", text):
        return LIC_NO, "含 NC（非商业）条款"
    if re.search(r"\bcc0\b|public\s*domain|publicdomain|/zero/", text):
        return LIC_OK, "公共领域 / CC0"
    if (re.search(r"\bcc[\s-]?by\b", text) or "creativecommons.org/licenses/by" in text
            or ("creative commons" in text and "attribution" in text)
            or re.fullmatch(r"by(?:[\s-](?:sa|nd))*(?:\s*\d(?:\.\d)?)?", short)):
        note = "CC BY 系列：商用需署名"
        if re.search(r"(?:^|[\s-])nd(?:$|[\s/-])|by-nd|no\s*deriv", text):
            note += "，ND 不可修改"
        return LIC_OK, note + "，请人工复核"
    if re.search(r"\b(?:gpl|lgpl|mit|bsd|apache)\b", text):
        return LIC_OK, "开源许可，请人工复核"
    return "", ""


# ---------------- 类目先验 / 排除规则 ----------------
CATEGORY_WORDS = [   # (类目, 先验需求分, 关键词)
    ("车和摩托配件", 85, r"\bcar\b|vehicle|motorcycle|motorbike|scooter|honda|yamaha|toyota|isuzu|hilux|d-?max|\bpcx\b|click ?1[256]0|wave ?1[01]0|helmet|dashboard|cup ?holder|\bvent\b|汽车|摩托|车载|รถยนต์|มอเตอร์ไซค์"),
    ("替换件适配件", 80, r"replacement|spare|adapter|adaptor|knob|clip|bracket|repair|\bfix\b|hose|vacuum|connector|mount for|转接|替换|配件|卡扣|旋钮"),
    ("收纳整理", 75, r"organi[sz]er|storage|holder|hook|hanger|rack|drawer|divider|cable|tray|\bbox\b|收纳|挂钩|置物|理线|ที่เก็บ|ที่แขวน"),
    ("宠物", 75, r"\bcat\b|kitten|\bdog\b|\bpet\b|feeder|litter|aquarium|猫|狗|宠物|แมว|หมา"),
    ("植物园艺", 70, r"planter|\bpot\b|plant|succulent|cactus|garden|seed|watering|花盆|植物|园艺|กระถาง"),
    ("桌面办公", 65, r"desk|\bpen\b|pencil|office|monitor|keyboard|stand|note|桌面|笔筒|显示器"),
    ("手机电脑配件", 60, r"phone|iphone|android|tablet|ipad|laptop|switch|controller|headphone|earbuds|charger|usb|手机|平板|耳机"),
    ("厨房卫浴", 55, r"kitchen|bathroom|soap|toothbrush|towel|sink|spice|厨房|浴室"),
    ("装饰摆件", 40, r"decor|vase|lamp|sculpture|statue|ornament|wall art|摆件|装饰"),
    ("玩具手办", 20, r"\btoy|figure|figurine|miniature|fidget|articulated|dragon|手办|玩具|模型人偶"),
]
CATEGORY_TH = {"车和摩托配件": "อุปกรณ์รถยนต์และมอเตอร์ไซค์", "替换件适配件": "อะไหล่และตัวแปลง", "收纳整理": "จัดเก็บ",
               "宠物": "สัตว์เลี้ยง", "植物园艺": "ต้นไม้และสวน", "桌面办公": "โต๊ะทำงาน", "手机电脑配件": "อุปกรณ์มือถือและคอมพิวเตอร์",
               "厨房卫浴": "ครัวและห้องน้ำ", "装饰摆件": "ของตกแต่ง", "玩具手办": "ของเล่นและฟิกเกอร์", "其他": "อื่นๆ"}
# 排除规则和品牌 / 动漫词跟 ERP 的上架检查用同一份（core/copyrules.py）
EXCLUDE = copyrules.SENSITIVE
EX_KIDS = EXCLUDE[0][0]
EX_IP = "可能侵权（品牌 / 动漫角色）"
EX_MULTI = "需要多色打印"            # v2.52 起不再用来排除，只留着给旧数据显示
FLAG_MULTI = "多色（需要 AMS）"
FLAG_TH = {FLAG_MULTI: "หลายสี (ต้องมี AMS)"}
MULTI_PROD_PENALTY = 25     # 生产效率扣分（换色慢、只能上 AMS 机）
MULTI_PROFIT_PENALTY = 10   # 利润扣分（冲刷废料、时间长）
REASON_TH = {EX_KIDS: "ของเล่นเด็ก (ต้องมี มอก.)", "宗教造型（佛像等，敏感）": "รูปทรงทางศาสนา (อ่อนไหว)", "类似武器": "คล้ายอาวุธ",
             "接触食物（打印件不卫生）": "สัมผัสอาหาร (ไม่ถูกสุขอนามัย)", "成人用品": "สินค้าผู้ใหญ่", EX_IP: "อาจละเมิดลิขสิทธิ์ (แบรนด์ / ตัวการ์ตูน)",
             EX_MULTI: "ต้องพิมพ์หลายสี"}
IP_TERMS = copyrules.IP_TERMS


banned_words = copyrules.words_in


def ip_hits(*texts):
    return banned_words(" ".join(str(t or "") for t in texts), IP_TERMS)


PART_KEYS = ("demand", "production", "profit", "competition", "popularity", "listing")
PART_ZH = {"demand": "泰国需求", "production": "生产效率", "profit": "利润", "competition": "竞争少", "popularity": "原站热度", "listing": "上架难度"}

DEFAULT_PREFS = {"cur_max_minutes": 240, "cur_max_grams": 80, "cur_exclude_kids": True,
                 "cur_w_demand": 30, "cur_w_production": 25, "cur_w_profit": 15, "cur_w_competition": 10, "cur_w_popularity": 15, "cur_w_listing": 5,
                 "cur_priority": "车和摩托配件,收纳整理,宠物,植物园艺,桌面办公,手机电脑配件,替换件适配件", "cur_calibrate": True}


def tf(v, d=0.0):
    try:
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def num(v):
    """'1.3K' / '2,104' / '1.2万' → 数字。"""
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v or "").strip().lower().replace(",", "")
    m = re.match(r"([\d.]+)\s*([km万]?)", t)
    if not m:
        return 0.0
    return tf(m.group(1)) * {"k": 1000, "m": 1_000_000, "万": 10_000}.get(m.group(2), 1)


def _clamp(x, lo=0, hi=100):
    return max(lo, min(hi, x))


def prefs(cfg):
    return {k: cfg.get(k, d) if cfg.get(k) not in (None, "") else d for k, d in DEFAULT_PREFS.items()}


def exclusion(text, author="", p=None, ai=None):
    """排除原因（空 = 不排除）。"""
    p = p or DEFAULT_PREFS
    for why, pat in EXCLUDE:
        if re.search(pat, text or "", re.I):
            if why == EX_KIDS and not p.get("cur_exclude_kids", True):
                continue
            return why
    if ip_hits(text, author):
        return EX_IP
    if ai and ai.get("exclude"):
        return str(ai["exclude"])[:60]
    return ""


def category_of(text):
    for name, score, pat in CATEGORY_WORDS:
        if re.search(pat, text or "", re.I):
            return name, score
    return "", 50


def parts(c, ai, cfg, real=None, calib=None, cost_fn=None, fee=0.2):
    """各项得分（0-100）、排除原因、类目。
    c: {title, author, metrics}；ai: AI 判断（可以是空字典）；real: 采集后实测 {minutes, grams}；calib: 校准系数 {m, g}；
    cost_fn(grams, hours) → ERP 单件成本（core/pricing）。"""
    p = prefs(cfg)
    ai = ai or {}
    text = f"{c.get('title') or ''} {ai.get('category') or ''}".lower()
    excluded = exclusion(text, c.get("author"), p, ai)
    cat, prior = category_of(text)
    cat = ai.get("category") or cat
    if cat and cat in str(p["cur_priority"] or ""):
        prior = max(prior, 70) + 5
    demand = _clamp(tf(ai.get("demand"), prior))
    mins, grams = tf(ai.get("est_minutes")), tf(ai.get("est_grams"))
    if real and (tf(real.get("minutes")) or tf(real.get("grams"))):
        mins, grams = tf(real.get("minutes")), tf(real.get("grams"))
    elif calib and p["cur_calibrate"] and (mins or grams):
        mins, grams = mins * calib.get("m", 1.0), grams * calib.get("g", 1.0)
    mx_m, mx_g = tf(p["cur_max_minutes"], 240) or 240, tf(p["cur_max_grams"], 80) or 80
    if mins or grams:
        pm = 100 if mins <= 120 else _clamp(100 - (mins - 120) / max(mx_m - 120, 1) * 60)
        pg = 100 if grams <= 30 else _clamp(100 - (grams - 30) / max(mx_g - 30, 1) * 60)
        production = pm * 0.6 + pg * 0.4
        if mins > mx_m and not excluded:
            excluded = f"打印时间太长（约 {mins / 60:.1f} 小时，上限 {mx_m / 60:.1f}）"
    else:
        production = 55
    multi = ai.get("single_color") is False
    if multi:                                # v2.52：不排除，只扣分（见 flags()）
        production -= MULTI_PROD_PENALTY
    production -= min(30, max(0, int(tf(ai.get("parts"), 1)) - 2) * 6)
    if ai.get("needs_hardware"):
        production -= 15
    production = _clamp(production)
    lo, hi = tf(ai.get("price_low")), tf(ai.get("price_high"))
    profit = 50
    if (lo or hi) and (mins or grams) and cost_fn:
        mid = (lo + hi) / 2 if lo and hi else (lo or hi)
        cost = cost_fn(grams or 30, (mins or 60) / 60)
        margin = (mid * (1 - fee) - cost) / mid if mid else 0
        profit = _clamp(margin * 160)
    if multi:
        profit = _clamp(profit - MULTI_PROFIT_PENALTY)
    comp = {"low": 100, "medium": 60, "high": 20}.get(str(ai.get("competition") or ""), 50)
    m = c.get("metrics") or {}
    heat = num(m.get("makes")) * 3 + num(m.get("downloads")) + num(m.get("likes")) * 1.5 + num(m.get("boosts")) * 2 + num(m.get("collects"))
    if not heat:
        heat = max([num(v) for k, v in m.items() if str(k).startswith("n")] or [0])
    popularity = _clamp(22 * math.log10(1 + heat))
    listing = _clamp(tf(ai.get("listing"), 60))
    out = {"demand": demand, "production": production, "profit": profit, "competition": comp, "popularity": popularity, "listing": listing}
    return {k: round(v) for k, v in out.items()}, excluded, cat


def flags(ai):
    """提示标签（不排除）：多色 → 「多色（需要 AMS）」。"""
    return [FLAG_MULTI] if (ai or {}).get("single_color") is False else []


def score(pp, cfg):
    p = prefs(cfg)
    w = {k: tf(p["cur_w_" + k]) for k in PART_KEYS}
    tot = sum(w.values()) or 1
    return round(sum(pp.get(k, 0) * w[k] for k in w) / tot, 1)


def calib_from_pairs(pairs, min_n=5):
    """pairs: [(估算分钟, 实测分钟, 估算克, 实测克)] → {m, g, n}（实测 ÷ 估算的中位数，夹在 0.5–3；样本不到 5 个就是 1）。"""
    rm = [r / e for e, r, _a, _b in pairs if e and r]
    rg = [b / a for _e, _r, a, b in pairs if a and b]
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 1.0  # noqa: E731
    return {"m": round(max(0.5, min(3.0, med(rm))), 2) if len(rm) >= min_n else 1.0,
            "g": round(max(0.5, min(3.0, med(rg))), 2) if len(rg) >= min_n else 1.0,
            "n": max(len(rm), len(rg))}
