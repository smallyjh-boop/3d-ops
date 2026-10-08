"""文案用的事实和原文清理（v2.30 从搜索优化里分出来，AI 写文案、关键词、搜索优化都用）。
  clean_source(text)   选品原文里去掉作者宣传、打赏、社交账号、许可证、外链（不进 AI，也不进详情）
  promo_left(text)     还剩下的宣传内容
  facts(p)             系统里能确定的事实（规格尺寸、件数、颜色、材质、重量），AI 只能用这些数字
"""
import re

_PROMO = re.compile(
    r"(boost|tip\s*jar|donat|support (me|my|helps)|buy me a coffee|ko-?fi|patreon|follow me|subscribe|"
    r"insta(gram)?|tiktok|youtube|facebook|twitter|thingiverse|printables|makerworld|cults3d|thangs|"
    r"\b(cc[- ]?by|creative commons|licen[cs]e|remix|attribution|non-?commercial|commercial use)\b|"
    r"thank you|thanks for|my (personal|latest|other) |check out my|see my|link in|https?://|www\.|"
    r"关注我|打赏|支持一下|支持我|我的主页|作者|许可证|授权|转载|ขอบคุณที่สนับสนุน|ติดตาม(ฉัน|เรา))", re.I)
_HANDLE = re.compile(r"(?<![\w.])@[A-Za-z0-9_.]{2,}")


def clean_source(text):
    """去掉作者宣传 / 打赏 / 社交账号 / 许可证 / 外链。按句子过滤，产品本身的信息留下。"""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "\n", str(text))
    out = []
    for line in re.split(r"[\n\r]+", text):
        parts = re.split(r"(?<=[.!?])\s+|(?<=[。！？；])", line)
        keep = [s for s in parts if s.strip() and not _PROMO.search(s) and not _HANDLE.search(s)]
        s = " ".join(keep).strip()
        if s:
            out.append(s)
    return "\n".join(out)


def promo_left(text):
    """文案里还残留的宣传 / 外链（检查用）。"""
    t = re.sub(r"<[^>]+>", " ", text or "")
    m = _PROMO.search(t) or _HANDLE.search(t)
    return m.group(0) if m else ""


# ---------------- 系统里的事实 ----------------
def _fmt_size(size):
    try:
        s = sorted((float(x) for x in size), reverse=True)
        return "×".join(f"{x / 10:.1f}".rstrip("0").rstrip(".") for x in s) + " cm"
    except (TypeError, ValueError):
        return ""


def facts(p):
    """AI 写详情只能用这些数字（尺寸、件数、重量…），不让它编。"""
    vs = p.get("variants") or []
    colors, specs_ = [], []
    for v in vs:
        c, s = (v.get("opt1_zh") or "").strip(), (v.get("opt2_zh") or "").strip()
        if c and c not in colors:
            colors.append(c)
        if s and s not in specs_:
            specs_.append(s)
    out = {"name": p.get("name_zh", ""), "material": p.get("material", ""), "size_text": p.get("size_text", ""),
           "colors": colors, "specs": []}
    sizes = {}
    try:
        from . import specmodel
        for s in specs_:
            e = specmodel.entry_for(p, s)
            if e and (e.get("info") or {}).get("size"):
                sizes[s] = _fmt_size(e["info"]["size"])
        main = ((p.get("model") or {}).get("metrics") or {}).get("size")
        if main:
            out["main_size"] = _fmt_size(main)
    except Exception:  # noqa: BLE001  没有模型也能写
        pass
    meta = {x.get("name_zh"): x for x in p.get("specs") or []}
    for s in specs_:
        m = meta.get(s) or {}
        g = next((v.get("grams") for v in vs if (v.get("opt2_zh") or "").strip() == s and v.get("grams")), None)
        out["specs"].append({k: v for k, v in {"name": s, "size": sizes.get(s) or (m.get("size_mm") and _fmt_size(m["size_mm"])) or "",
                                               "pieces": m.get("pack_qty") or "", "parts": m.get("parts") or "",
                                               "grams": round(float(g)) if g else ""}.items() if v})
    gs = [float(v.get("grams")) for v in vs if v.get("grams")]
    if gs and not specs_:
        out["grams"] = round(max(gs))
    pc = (p.get("copy") or {}).get("package_content_th")
    if pc:
        out["package_content_th"] = pc
    return out
