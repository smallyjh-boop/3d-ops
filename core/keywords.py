"""关键词扩展：按 Lazada / Shopee 泰国站的搜索习惯，把一个产品能被搜到的词尽量找全，再交给文案生成使用。

平台搜索机制要点（写进提示词）：
- 标题权重最高：最重要的搜索词放标题前 30-40 个字符；同义词放标题后半段；同一个词不要重复。
- 详情、属性、变体名（颜色等）也会被检索：标题放不下的同义词、场景词、人群词自然地写进详情。
- 泰国买家常同时用泰文和英文搜（phone stand / ที่วางมือถือ），也常用口语和不同写法（มือถือ/โทรศัพท์，ตกแต่ง/แต่ง）。
- Shopee 详情里的 #标签 会被搜索（最多 18 个）；Lazada 不看标签。
- 禁止：品牌/动漫/IP 名、制造方式词、与产品无关的热门词（会被平台判定为关键词堆砌而降权）。
"""
import re

from . import ai_copy, copyfacts as seo

GROUPS = [
    ("need", "买家想要什么"), ("core", "核心词"), ("synonym", "同义词/口语"), ("english", "英文词"), ("attribute", "属性词"),
    ("scene", "场景/用途"), ("audience", "人群/送礼"), ("longtail", "长尾词"), ("custom", "自己添加"),
]

SYSTEM = """You are a Thai e-commerce SEO specialist for Lazada Thailand and Shopee Thailand.
Think like the BUYER first: what does a Thai shopper want, feel or need when they end up buying this product?
(relieve stress, decorate a desk, a cute gift for a friend, keep cables tidy, something for kids to play with ...)
Then list the words they would actually type into the search box to find it - Thai first, colloquial Thai and
common alternative spellings; English only for the few terms Thai buyers and foreign residents really type in
English (fidget, keycap, phone stand ...). Keep everything 100% relevant (irrelevant words get the listing demoted).
How the platforms rank: title words weigh most (first ~40 characters most), then attributes, variation names
and description text.
Rules:
- Only terms that truly describe THIS product, its real uses, real buyers and real occasions.
- NO brand / character / anime / game / team names (IP risk). NO words about how it is made
  (3D print, พิมพ์ 3D, ปริ้น, handmade, made to order, filament).
- Each term short and natural as typed in the search box (1-4 words for Thai, 1-3 words for English).
- Output ONLY JSON."""

USER = """Product (seller notes may be Chinese or Thai):
- Name: {name}
- Uses / selling points: {features}
- Seller keywords: {keywords}
- Material: {material}
- Size: {size}
- Colours / options: {options}
- Category: {category}

Return JSON:
{{
 "need": ["4-8 short Thai phrases of what the buyer wants / the problem solved / the feeling (คลายเครียด, แต่งโต๊ะทำงาน, ของขวัญให้เพื่อน ...)"],
 "core": ["3-6 main product nouns buyers search, most searched first (Thai)"],
 "synonym": ["6-12 Thai synonyms, colloquial words, alternative spellings"],
 "english": ["2-5 short English terms Thai buyers / foreign residents really type (no long phrases)"],
 "attribute": ["5-10 attribute words: style, shape, material only if a selling point, size words like มินิ/ใหญ่, colour words"],
 "scene": ["5-10 use / place / scene words: ตั้งโต๊ะ, ห้องนอน, ในรถ, ออฟฟิศ ..."],
 "audience": ["4-8 buyer / gift / occasion words: ของขวัญวันเกิด, ของขวัญปีใหม่, สำหรับเด็ก ..."],
 "longtail": ["6-10 natural 3-6 word Thai search phrases combining the above"],
 "title_core": "the single best main keyword to start the title with (Thai)",
 "avoid": ["words that must NOT be used: IP/brand names it resembles, misleading terms"],
 "notes_zh": "一两句中文说明：这个产品在泰国平台主要被怎么搜",
 "notes_th": "the same note in Thai for Thai staff"
}}"""


def _clean_list(v, n):
    out, seen = [], set()
    for x in v or []:
        x = re.sub(r"\s+", " ", str(x)).strip(" ,，#")
        if not x or len(x) > 60 or ai_copy.mentions_process(x):
            continue
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out[:n]


def research(cfg, product, category_name=""):
    opts = []
    for v in product.get("variants", []):
        for k in ("opt1_zh", "opt2_zh"):
            val = (v.get(k) or "").strip()
            if val and val not in opts:
                opts.append(val)
    user = USER.format(
        name=product.get("name_zh", ""), features=seo.clean_source(product.get("features_zh", ""))[:3000],
        keywords=product.get("keywords", ""), material=product.get("material", ""),
        size=product.get("size_text", ""), options="、".join(opts) or "-", category=category_name or "-")
    d = ai_copy.extract_json(ai_copy.call(cfg, SYSTEM, user))
    plan = {k: _clean_list(d.get(k), 14) for k, _ in GROUPS}
    plan["title_core"] = str(d.get("title_core") or (plan["core"][0] if plan["core"] else "")).strip()
    plan["avoid"] = _clean_list(d.get("avoid"), 10)
    plan["notes_zh"] = str(d.get("notes_zh") or "")
    plan["notes_th"] = str(d.get("notes_th") or "")
    return plan


def all_terms(plan):
    out = []
    for k, _ in GROUPS:
        for t in plan.get(k) or []:
            if t not in out:
                out.append(t)
    return out


def _norm(s):
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", " ", s or "")).lower()


def coverage(plan, title, description, extra=""):
    """每个词出现在哪里：title / desc / none。"""
    t, d = _norm(title), _norm(description) + _norm(extra)
    res = {}
    for term in all_terms(plan):
        n = _norm(term)
        res[term] = "title" if n and n in t else ("desc" if n and n in d else "none")
    total = len(res) or 1
    return {"terms": res, "title_pct": round(sum(v == "title" for v in res.values()) / total * 100),
            "any_pct": round(sum(v != "none" for v in res.values()) / total * 100)}


def prompt_block(plan):
    """给文案生成用的关键词说明。"""
    if not plan:
        return ""
    lines = [f"Main keyword to start the title: {plan.get('title_core', '')}"]
    names = {"core": "Core nouns", "synonym": "Thai synonyms / colloquial", "english": "English terms",
             "attribute": "Attributes", "scene": "Uses / scenes", "audience": "Buyers / gifts / occasions",
             "longtail": "Long-tail phrases", "custom": "Seller's own must-use terms", "need": "What the buyer wants / feels"}
    for k, _ in GROUPS:
        if plan.get(k):
            lines.append(f"{names[k]}: " + ", ".join(plan[k]))
    if plan.get("avoid"):
        lines.append("NEVER use: " + ", ".join(plan["avoid"]))
    return "\n".join(lines)


def keywords_field(plan, limit=40):
    """填进①「关键词」的内容（逗号分隔）。"""
    return ", ".join(all_terms(plan)[:limit])
