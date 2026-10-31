"""AI 生成 Lazada 泰文/英文上架文案，并回译中文供核对。"""
import json
import re

import requests

SYSTEM_PROMPT = """You are an expert Lazada / Shopee Thailand listing copywriter and SEO specialist for a small product shop.
Write natural, native Thai (not machine-translated style). Goal: be found by as many relevant searches as
possible AND read smoothly for a human buyer. Rules:
- NEVER mention how the product is made: no "3D printing / 3D printed / พิมพ์ 3D / ปริ้น 3D / ปริ้นท์",
  no "made to order / ผลิตตามออร์เดอร์ / handmade", no layer lines, printers or filament. Present it simply
  as a finished product. This applies to titles, highlights, descriptions, keywords, hashtags and package content.
- NEVER use third-party brand, character, anime, game or team names unless the seller explicitly says
  they hold a licence. If the product resembles such IP, describe it generically.
- All facts (size, weight, material, options) must come from the seller input. Do not invent specs.
SEARCH OPTIMISATION (use the keyword plan provided; think about what the buyer wants):
- Lazada Thai title (title_th): 80-150 characters. Mostly Thai. Start with the main keyword. Then the most valuable
  Thai synonyms, the key attribute / size, the main use or what the buyer wants, built as ONE natural readable phrase
  (segments separated by single spaces, no "|" or "/" chains, no comma lists). END the title with 2-4 English
  keywords (single words or very short terms Thai buyers / foreign residents type, e.g. "Fidget Clicker Keycap"),
  at most 8 English words in total, never the same English word twice (not "Magic Box Magic Trick Box").
  Never repeat the same word. No emoji, no ALL CAPS, no exaggerated claims. Material only when it is a selling point.
- Shopee Thai title (title_shopee_th): max 110 characters, same rules, the most searched words in the first 40 characters,
  1-3 English keywords at the end.
- English title (title_en): 60-150 characters, natural English, for foreign buyers.
- Thai description (description_th): SHORT, CLEAR, easy to scan on a phone (about 400-1200 characters of text).
  Do NOT translate the seller's source text sentence by sentence; rewrite from the facts. Never mention the designer,
  donations, social media, links or licences. Use ONLY the facts given (sizes, pieces, colours, weight) - never invent
  numbers. Simple HTML only (<p>, <ul>, <li>, <strong>, <br>), in this order:
  1) <p> one sentence: what it is + what the buyer gets (main keyword + 1-2 synonyms, natural)</p>
  2) <p><strong>จุดเด่น</strong></p><ul> 3-5 bullets, each one short line of what the buyer cares about</ul>
  3) <p><strong>ขนาด / ตัวเลือก</strong></p><ul> one bullet per size / option with its size from the facts</ul>
     (if there are no sizes in the facts, give the overall size or skip this block)
  4) <p><strong>ในกล่องมี</strong></p><p> what is in the box; say if simple assembly is needed</p>
  5) <p><strong>เหมาะสำหรับ</strong></p><p> one or two lines: who / which occasion (use scene & audience words)</p>
  6) <p><strong>ข้อควรรู้</strong></p><ul> 2-3 short care notes (keep away from heat / direct sun in a car, etc.)</ul>{extras}
- English description (description_en): the same structure and facts in short natural English.
- highlights_th: the same 3-5 bullets as the จุดเด่น block.
- Shopee hashtags: 14-18 hashtags from the plan, mostly Thai plus a few English, no spaces inside a tag, each starting with #.
- Output ONLY one JSON object, no markdown fences."""

EXTRA_LEAD = "\n  Add one short line with the shipping time from the seller input (จัดส่งภายใน N วัน), without explaining why."
EXTRA_NO_LEAD = "\n  Do NOT mention any shipping or delivery time."
EXTRA_CUSTOM = "\n  Add one short line that custom orders are welcome (e.g. ปรับขนาด/สี/ข้อความได้ ทักแชทสอบถาม)."
EXTRA_WHOLESALE = "\n  Add one short line that wholesale / bulk orders are welcome (สั่งจำนวนมาก/ราคาส่ง ทักแชท)."

USER_TEMPLATE = """Seller input (Chinese or Thai):
产品名称: {name}
用途/卖点/描述（原文，只取产品信息）: {features}
系统里确定的事实（尺寸、件数、颜色、重量，只能用这些数字）: {facts}
关键词: {keywords}
材料: {material}
尺寸: {size}
重量: {weight}
变体1名称: {v1}
变体2名称: {v2}
变体选项: {options}
{lead_line}店铺: {shop}

Keyword plan (search terms Thai buyers use for this product):
{kw_block}

Return JSON with exactly these keys:
{{
 "title_th": "...",
 "title_shopee_th": "...",
 "title_en": "...",
 "highlights_th": ["4-6 short bullet points in Thai"],
 "description_th": "<p>...</p>",
 "description_en": "<p>...</p>",
 "hashtags_shopee": ["exactly 18 hashtags Thai buyers search on Shopee (Thai and English, no spaces inside a tag)"],
 "package_content_th": "always fill, e.g. 1 x ... (each item in the box)",
 "variation1_name_th": "Thai for 变体1名称 (empty if none)",
 "variation2_name_th": "Thai for 变体2名称 (empty if none)",
 "options_th": {{"<each Chinese option value>": "<Thai>"}},
 "title_zh": "Chinese back-translation of title_th",
 "description_zh": "Chinese back-translation of the Thai description (plain text, keep the section headings)",
 "search_keywords_th": ["10-20 most important Thai search terms used"]
}}"""

# 文案里不应出现的生产方式词（检查用）
PROCESS_WORDS = re.compile(
    r"3\s*d\s*print|3d打印|3d列印|พิมพ์\s*3\s*d|ปริ้น(?:ท์|ต์)?\s*3\s*d|3\s*d\s*ปริ้น|ผลิตตาม(?:ออร์เดอร์|สั่ง)|made\s*to\s*order|filament|เส้นพลาสติก",
    re.I)


def mentions_process(text):
    return bool(PROCESS_WORDS.search(text or ""))


class AIError(Exception):
    pass


def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise AIError("AI 没有返回 JSON，请重试")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise AIError(f"AI 返回的 JSON 无法解析：{e}") from e


def call(cfg, system, user, image_b64=None):
    """image_b64：可选的 JPEG 图片（base64），让 AI 看图。模型不支持看图时自动退回纯文字。"""
    if image_b64:
        try:
            return _request(cfg, system, user, image_b64)
        except AIError as e:
            if not re.search(r"\b4\d\d\b", str(e)):
                raise
    return _request(cfg, system, user, None)


def _request(cfg, system, user, image_b64):
    key = (cfg.get("ai_api_key") or "").strip()
    if not key:
        raise AIError("还没有填写 AI 接口密钥（设置页）")
    provider = cfg.get("ai_provider", "anthropic")
    model = cfg.get("ai_model")
    try:
        if provider == "anthropic":
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": model, "max_tokens": 4000, "system": system,
                      "messages": [{"role": "user", "content": user if not image_b64 else [
                          {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                          {"type": "text", "text": user}]}]},
                timeout=120,
            )
            if r.status_code != 200:
                raise AIError(f"AI 接口错误 {r.status_code}: {r.text[:300]}")
            data = r.json()
            return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        base = (cfg.get("ai_base_url") or "").rstrip("/")
        if provider == "deepseek":         # v2.50：DeepSeek 单独一个选项（OpenAI 兼容接口，地址固定）
            if not base or "deepseek" not in base:
                base = "https://api.deepseek.com"
            if not model or str(model).lower().startswith("claude"):
                raise AIError("接口类型选了 DeepSeek：请在「模型名称」里填 DeepSeek 的模型名（DeepSeek 开放平台的模型列表里有）")
        url = base + ("/chat/completions" if base.endswith("/v1") or "deepseek" in base else "/v1/chat/completions")
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {key}", "content-type": "application/json"},
            json={"model": model, "temperature": 0.7,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user if not image_b64 else [
                                   {"type": "text", "text": user},
                                   {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_b64}}]}]},
            timeout=120,
        )
        if r.status_code != 200:
            raise AIError(f"AI 接口错误 {r.status_code}: {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"]
    except requests.RequestException as e:
        raise AIError(f"连接 AI 接口失败：{e}") from e


def generate_copy(cfg, product, plan=None):
    opts = []
    for v in product.get("variants", []):
        for k in ("opt1_zh", "opt2_zh"):
            val = (v.get(k) or "").strip()
            if val and val not in opts:
                opts.append(val)
    grams = [float(v.get("grams") or 0) for v in product.get("variants", []) if v.get("grams")]
    weight = (f"约 {round(max(grams))} 克" if len(set(grams)) == 1 else
              f"约 {round(min(grams))}-{round(max(grams))} 克（按选项不同）") if grams else "未知"
    lead_on = bool(cfg.get("copy_mention_lead_time", False))
    extras = (EXTRA_LEAD if lead_on else EXTRA_NO_LEAD) + (EXTRA_CUSTOM if cfg.get("copy_mention_custom", True) else "") + \
             (EXTRA_WHOLESALE if cfg.get("copy_mention_wholesale", True) else "")
    system = SYSTEM_PROMPT.replace("{extras}", extras)
    from . import copyfacts as seo
    user = USER_TEMPLATE.format(
        weight=weight,
        name=product.get("name_zh", ""),
        features=seo.clean_source(product.get("features_zh", ""))[:3000],
        facts=json.dumps(seo.facts(product), ensure_ascii=False),
        keywords=product.get("keywords", ""),
        material=product.get("material", ""),
        size=product.get("size_text", ""),
        v1=product.get("variation1_name_zh", "") if any(v.get("opt1_zh") for v in product.get("variants", [])) else "",
        v2=product.get("variation2_name_zh", "") if any(v.get("opt2_zh") for v in product.get("variants", [])) else "",
        options="、".join(opts) or "无",
        lead_line=f"发货时间: 下单后 {cfg.get('lead_time_days', 3)} 天内发货\n" if lead_on else "",
        shop=cfg.get("shop_name_th", ""),
        kw_block=_kw_block(plan) or "(none - infer the best search terms yourself)",
    )
    data = extract_json(call(cfg, system, user))
    # 把卖点合进详情开头，方便直接用
    hl = data.get("highlights_th") or []
    if hl and "<ul>" not in (data.get("description_th") or "")[:200]:
        bullets = "".join(f"<li>{h}</li>" for h in hl)
        data["description_th"] = f"<ul>{bullets}</ul>" + (data.get("description_th") or "")
    data.setdefault("options_th", {})
    tags = []
    for t in data.get("hashtags_shopee") or []:
        t = "#" + re.sub(r"[\s#]+", "", str(t))
        if len(t) > 1 and t not in tags and not mentions_process(t):
            tags.append(t)
    data["hashtags_shopee"] = " ".join(tags[:18])
    return data


def _kw_block(plan):
    from . import keywords
    return keywords.prompt_block(plan) if plan else ""


def back_translate(cfg, title_th, description_th, with_en=True):
    """你手动改了泰文后，可以重新回译成中文核对；同时按泰文生成英文标题和英文详情（v2.22，Lazada 要英文）。"""
    keys = '{"title_zh": ..., "description_zh": ...' + (', "title_en": ..., "description_en": ...' if with_en else "") + "}"
    user = ("Translate the following Thai e-commerce text faithfully. title_zh / description_zh: Simplified Chinese "
            "(description as plain text, for the seller to check). "
            + ("title_en: natural English product title for Lazada (max 255 chars, no 3D printing / made-to-order words). "
               "description_en: the same description in English as simple HTML (<p>, <ul><li>), keep all facts. " if with_en else "")
            + f"Return JSON {keys}.\n\nTITLE: {title_th}\n\nDESCRIPTION:\n{description_th}")
    d = extract_json(call(cfg, "You are a precise Thai e-commerce translator. Output only JSON.", user))
    if with_en:
        _clean_en(d)
    return d


def _clean_en(d):
    d["title_en"] = re.sub(r"\s+", " ", str(d.get("title_en") or "")).strip()[:255]
    d["description_en"] = str(d.get("description_en") or "").strip()
    if d["description_en"] and "<" not in d["description_en"]:
        d["description_en"] = "".join(f"<p>{x.strip()}</p>" for x in d["description_en"].split("\n") if x.strip())
    return d


COPY_KEYS = ("title_th", "title_shopee_th", "title_en", "description_th", "description_en", "highlights_th", "hashtags_shopee",
             "package_content_th", "variation1_name_th", "variation2_name_th")


def missing_copy(product):
    """哪些文案字段还空着（只算这个产品用得上的：没有第二个选项就不要变体2名称）。另外返回还没有泰文的选项值。"""
    c = product.get("copy") or {}
    vs = product.get("variants") or []
    miss = [k for k in COPY_KEYS if not (c.get(k) if not isinstance(c.get(k), str) else c.get(k).strip())]
    if not any(v.get("opt1_zh") for v in vs) and "variation1_name_th" in miss:
        miss.remove("variation1_name_th")
    if not any(v.get("opt2_zh") for v in vs) and "variation2_name_th" in miss:
        miss.remove("variation2_name_th")
    have = c.get("options_th") or {}
    opts = []
    for v in vs:
        for k in ("opt1_zh", "opt2_zh"):
            x = (v.get(k) or "").strip()
            if x and x not in opts and not (have.get(x) or "").strip():
                opts.append(x)
    return miss, opts


def complete_copy(cfg, product, plan=None):
    """把空着的文案字段补完整（v2.22：增加被搜索的机会）。已经有的不动。返回 {字段: 新内容}（options_th 只含新加的）。"""
    miss, opts = missing_copy(product)
    if not miss and not opts:
        return {}
    c = product.get("copy") or {}
    if "title_th" in miss and "description_th" in miss:
        d = generate_copy(cfg, product, plan)          # 泰文都没有：整份生成，只取空着的
    else:
        want = {k: v for k, v in {
            "title_th": "Thai title for Lazada (max 255 chars, main search keywords first)",
            "title_shopee_th": "Thai title for Shopee (max 120 chars)",
            "title_en": "English title for Lazada (max 255 chars)",
            "description_th": "<p>Thai description HTML</p>",
            "description_en": "<p>English description HTML, same facts as Thai</p>",
            "highlights_th": ["4-6 short Thai bullet points"],
            "hashtags_shopee": ["exactly 18 hashtags Thai buyers search on Shopee"],
            "package_content_th": "what is in the box, e.g. 1 x ...",
            "variation1_name_th": f"Thai name for option group 「{product.get('variation1_name_zh') or '颜色'}」",
            "variation2_name_th": f"Thai name for option group 「{product.get('variation2_name_zh') or '规格'}」",
        }.items() if k in miss}
        if opts:
            want["options_th"] = {o: "<Thai>" for o in opts}
        from . import copyfacts as seo
        info = {"产品名称": product.get("name_zh", ""), "用途卖点": seo.clean_source(product.get("features_zh", ""))[:3000], "尺寸": product.get("size_text", ""),
                "系统事实（只能用这些数字）": seo.facts(product),
                "材料": product.get("material", ""), "关键词": product.get("keywords", ""),
                "现有泰文标题": c.get("title_th", ""), "现有泰文详情": (c.get("description_th") or "")[:4000],
                "现有英文标题": c.get("title_en", ""), "关键词计划": _kw_block(plan) or ""}
        user = ("Fill ONLY these missing fields of a Thai e-commerce listing (Lazada / Shopee Thailand), consistent with the existing text. "
                "Use the search terms Thai buyers use so the listing is found more often. No 3D printing / made-to-order / filament words.\n"
                + json.dumps(info, ensure_ascii=False) + "\n\nReturn JSON with exactly these keys:\n" + json.dumps(want, ensure_ascii=False))
        d = extract_json(call(cfg, "You are a Thai e-commerce listing expert. Output only JSON.", user))
    out = {k: d[k] for k in miss if d.get(k)}
    if "hashtags_shopee" in out:
        tags = []
        raw = out["hashtags_shopee"]
        for t in (raw if isinstance(raw, list) else str(raw).split()):
            t = "#" + re.sub(r"[\s#]+", "", str(t))
            if len(t) > 1 and t not in tags and not mentions_process(t):
                tags.append(t)
        out["hashtags_shopee"] = " ".join(tags[:18])
    if "highlights_th" in out and not isinstance(out["highlights_th"], list):
        out["highlights_th"] = [x.strip() for x in str(out["highlights_th"]).split("\n") if x.strip()]
    if "title_en" in out or "description_en" in out:
        en = _clean_en({"title_en": out.get("title_en", ""), "description_en": out.get("description_en", "")})
        for k in ("title_en", "description_en"):
            if k in out:
                out[k] = en[k]
    if "title_shopee_th" in out:
        out["title_shopee_th"] = str(out["title_shopee_th"]).strip()[:120]
    new_opts = {k: str(v).strip() for k, v in (d.get("options_th") or {}).items() if k in opts and str(v).strip() and "<" not in str(v)}
    if new_opts:
        out["options_th"] = new_opts
    return out


def apply_completion(product, out):
    """把 complete_copy 的结果合进产品（只填空的；选项泰文合并）。"""
    c = product.setdefault("copy", {})
    for k, v in out.items():
        if k == "options_th":
            c["options_th"] = {**(c.get("options_th") or {}), **v}
        elif not c.get(k):
            c[k] = v
    return product


def to_english(cfg, product):
    """按泰文（没有泰文就按中文资料）生成英文标题和英文详情。"""
    c = product.get("copy") or {}
    th_t, th_d = c.get("title_th") or "", c.get("description_th") or ""
    src = (f"THAI TITLE: {th_t}\n\nTHAI DESCRIPTION:\n{th_d}" if th_t or th_d else
           f"产品名称: {product.get('name_zh', '')}\n用途/卖点: {product.get('features_zh', '')}\n尺寸: {product.get('size_text', '')}\n材料: {product.get('material', '')}")
    user = ("Write the English version of this Thai e-commerce listing for Lazada Thailand. Keep the same facts, sizes, options "
            "and selling points; natural English, no 3D printing / made-to-order / filament words. "
            'Return JSON {"title_en": "max 255 chars", "description_en": "simple HTML: <ul><li> highlights then <p> paragraphs"}.\n\n' + src)
    return _clean_en(extract_json(call(cfg, "You are an e-commerce copywriter. Output only JSON.", user)))


# 兼容旧名称
_call = call
_extract_json = extract_json
