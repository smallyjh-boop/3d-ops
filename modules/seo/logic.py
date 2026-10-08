"""搜索优化（v2.23；v2.30 起是「搜索优化」模块的逻辑，modules/seo/logic.py）：从买家的角度找词，标题以泰文为主、英文只放几个关键词，详情重写成简短清楚的固定结构。

流程：
  clean_source(text)   选品原文里去掉作者宣传、打赏、社交账号、许可证、外链（不进 AI，也不进详情）
  facts(p)             系统里能确定的事实（规格尺寸、件数、颜色、材质、重量），AI 只能用这些数字
  score(p)             搜索分 0-100 + 每一项检查（中文 / 泰文说明），编辑页和产品库显示
  propose(cfg, p)      AI 重新找词 + 重写标题 / 详情 / 标签 / 变体名 / 包装内容 → 存成「待确认的优化」，不直接改
  apply(p, fields)     人勾选确认后才替换；已上架的商品记录改标题时间（默认 14 天内只建议改一次）
"""
import re
import time

from core import ai_copy

TITLE_MIN, TITLE_MAX = 60, 150          # Lazada 泰文标题建议长度（字符）
SHOPEE_MAX = 120
FRONT = 40                              # 手机搜索结果大约只显示前 40 个字符
TAGS_MIN, TAGS_MAX = 12, 18
EN_MAX_WORDS = 8                        # 泰文标题里英文最多几个词（泰国买家英文一般，只放关键词）
RECHANGE_DAYS = 14
DESC_MIN, DESC_MAX = 250, 1600          # 泰文详情纯文字长度：太短没信息，太长没人看

# ---------------- 原文清洗 ----------------
from core.copyfacts import clean_source, promo_left, facts, _fmt_size  # noqa: F401,E402


# ---------------- 打分 ----------------
def _plain(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _en_words(t):
    return re.findall(r"[A-Za-z][A-Za-z0-9'-]*", t or "")


def _dup_words(t):
    seen, dup = set(), []
    for w in re.split(r"\s+", (t or "").lower()):
        w = w.strip("•·,|/-")
        if len(w) < 2:
            continue
        if w in seen and w not in dup:
            dup.append(w)
        seen.add(w)
    return dup


def _first_core(plan, title):
    core = [x for x in ([plan.get("title_core")] if plan.get("title_core") else []) + (plan.get("core") or []) if x]
    head = re.sub(r"\s+", "", (title or "")[:FRONT]).lower()
    return any(re.sub(r"\s+", "", c).lower() in head for c in core) if core else None


def score(p):
    """搜索分：每一项 (权重, 通过, 中文说明, 泰文说明)。返回 {score, level, items}。"""
    c = p.get("copy") or {}
    plan = p.get("keyword_plan") or {}
    vs = p.get("variants") or []
    t = (c.get("title_th") or "").strip()
    ts = (c.get("title_shopee_th") or "").strip() or t[:SHOPEE_MAX]
    items = []

    def add(w, ok, zh, th, fix=""):
        items.append({"w": w, "ok": bool(ok), "zh": zh, "th": th, "fix": fix})

    add(10, t, "有泰文标题", "มีชื่อสินค้าภาษาไทย")
    add(10, TITLE_MIN <= len(t) <= TITLE_MAX, f"Lazada 标题长度 {len(t)} 字（建议 {TITLE_MIN}-{TITLE_MAX}，字数用足才能放进更多搜索词）",
        f"ความยาวชื่อ Lazada {len(t)} ตัวอักษร (แนะนำ {TITLE_MIN}-{TITLE_MAX})")
    fc = _first_core(plan, t)
    if fc is not None:
        add(12, fc, f"标题前 {FRONT} 字里有主搜索词（手机搜索结果只显示这一段）", f"มีคำค้นหลักใน {FRONT} ตัวอักษรแรกของชื่อ")
    fs = _first_core(plan, ts)
    if fs is not None:
        add(6, fs, f"Shopee 标题前 {FRONT} 字里有主搜索词", f"ชื่อ Shopee มีคำค้นหลักใน {FRONT} ตัวอักษรแรก")
    add(4, len(ts) <= SHOPEE_MAX, f"Shopee 标题 {len(ts)} 字（最多 {SHOPEE_MAX}）", f"ชื่อ Shopee {len(ts)} ตัวอักษร (สูงสุด {SHOPEE_MAX})")
    en = _en_words(t)
    add(6, 1 <= len(en) <= EN_MAX_WORDS, f"泰文标题里带 1-{EN_MAX_WORDS} 个英文关键词（现在 {len(en)} 个）",
        f"ชื่อภาษาไทยมีคำภาษาอังกฤษ 1-{EN_MAX_WORDS} คำ (ตอนนี้ {len(en)})")
    dup = _dup_words(t)
    add(6, not dup, "标题里没有重复堆词" + (f"（重复：{'、'.join(dup[:4])}）" if dup else ""),
        "ไม่มีคำซ้ำในชื่อ" + (f" (ซ้ำ: {', '.join(dup[:4])})" if dup else ""))
    bad = [w for w in (plan.get("avoid") or []) if w and w.lower() in (t + " " + _plain(c.get("description_th"))).lower()]
    proc = ai_copy.mentions_process(t + " " + _plain(c.get("description_th")))
    add(8, not bad and not proc, "没有品牌 / 角色名、制造方式等禁用词" + (f"（{'、'.join(bad[:3])}）" if bad else ""),
        "ไม่มีชื่อแบรนด์/ตัวละคร หรือคำต้องห้าม")
    pl = promo_left((c.get("description_th") or "") + " " + (c.get("description_en") or ""))
    add(8, not pl, "详情里没有原作者宣传、社交账号、外链" + (f"（还有：{pl}）" if pl else ""),
        "รายละเอียดไม่มีข้อความโปรโมตของผู้ออกแบบ / โซเชียล / ลิงก์")
    dl = len(_plain(c.get("description_th")))
    add(8, DESC_MIN <= dl <= DESC_MAX, f"泰文详情 {dl} 字（建议 {DESC_MIN}-{DESC_MAX}：简短清楚）",
        f"รายละเอียดภาษาไทย {dl} ตัวอักษร (แนะนำ {DESC_MIN}-{DESC_MAX})")
    tags = [x for x in re.split(r"\s+", c.get("hashtags_shopee") or "") if x.startswith("#")]
    add(6, TAGS_MIN <= len(tags) <= TAGS_MAX, f"Shopee 标签 {len(tags)} 个（建议 {TAGS_MIN}-{TAGS_MAX}）",
        f"แท็ก Shopee {len(tags)} อัน (แนะนำ {TAGS_MIN}-{TAGS_MAX})")
    add(4, c.get("title_en"), "有英文标题（外国客户 / Lazada 英文站）", "มีชื่อภาษาอังกฤษ")
    add(3, c.get("description_en"), "有英文详情", "มีรายละเอียดภาษาอังกฤษ")
    add(3, c.get("package_content_th"), "有包装内容", "มีรายการในกล่อง")
    need_v1 = any(v.get("opt1_zh") for v in vs)
    need_v2 = any(v.get("opt2_zh") for v in vs)
    if need_v1 or need_v2:
        ok = (not need_v1 or (c.get("variation1_name_th") or "").strip()) and (not need_v2 or (c.get("variation2_name_th") or "").strip())
        add(3, ok, "变体名称有泰文", "ชื่อกลุ่มตัวเลือกเป็นภาษาไทย")
    if plan:
        from core import keywords
        cov = keywords.coverage(plan, t + " " + ts, c.get("description_th") or "", (c.get("hashtags_shopee") or "") + " " + (c.get("title_en") or ""))
        add(6, cov["any_pct"] >= 60, f"关键词用上了 {cov['any_pct']}%（标题 + 详情 + 标签，建议 ≥ 60%）",
            f"ใช้คำค้นแล้ว {cov['any_pct']}% (แนะนำ ≥ 60%)")
    else:
        add(6, False, "还没做买家搜索词分析", "ยังไม่ได้วิเคราะห์คำค้นของผู้ซื้อ")
    total = sum(x["w"] for x in items) or 1
    sc = round(sum(x["w"] for x in items if x["ok"]) / total * 100)
    return {"score": sc, "level": "good" if sc >= 80 else "ok" if sc >= 60 else "bad", "items": items}


def quick_score(p):
    try:
        return score(p)["score"]
    except Exception:  # noqa: BLE001
        return None


# ---------------- 提案 / 确认 ----------------
FIELDS = ("title_th", "title_shopee_th", "title_en", "description_th", "description_en", "highlights_th", "hashtags_shopee",
          "package_content_th", "variation1_name_th", "variation2_name_th", "title_zh", "description_zh", "search_keywords_th")
LABELS = {"title_th": "泰文标题（Lazada）", "title_shopee_th": "泰文标题（Shopee）", "title_en": "英文标题",
          "description_th": "泰文详情", "description_en": "英文详情", "highlights_th": "卖点", "hashtags_shopee": "Shopee 标签",
          "package_content_th": "包装内容", "variation1_name_th": "变体1名称（泰文）", "variation2_name_th": "变体2名称（泰文）",
          "title_zh": "标题中文回译", "description_zh": "详情中文回译", "search_keywords_th": "泰文搜索词", "options_th": "选项泰文",
          "keyword_plan": "买家搜索词"}


def recently_changed(p, days=RECHANGE_DAYS):
    """已上架、而且最近改过标题：返回还要等几天（0 = 可以改）。"""
    if not p.get("exported_at") and not p.get("shopee_exported_at"):
        return 0
    at = p.get("title_changed_at") or 0
    left = days - (time.time() - at) / 86400
    return max(0, int(left + 0.999)) if at else 0


def propose(cfg, p, category_name="", user=""):
    """AI 重新找词 + 重写。结果存 p["copy_proposal"]，返回它（不改现在的文案）。"""
    from core import keywords
    plan = keywords.research(cfg, p, category_name)
    custom = ((p.get("keyword_plan") or {}).get("custom")) or []
    plan["custom"] = custom
    data = ai_copy.generate_copy(cfg, p, plan)
    new = {k: data[k] for k in FIELDS if data.get(k)}
    opts = {k: v for k, v in (data.get("options_th") or {}).items() if str(v).strip()}
    if opts:
        new["options_th"] = opts
    before = score(p)
    q = dict(p)
    q["copy"] = {**(p.get("copy") or {}), **new}
    q["keyword_plan"] = plan
    after = score(q)
    prop = {"fields": new, "plan": plan, "score_before": before["score"], "score_after": after["score"],
            "at": time.time(), "by": user, "wait_days": recently_changed(p)}
    p["copy_proposal"] = prop
    return prop


def apply(p, fields=None, user=""):
    """把「待确认的优化」里勾选的字段换进去（fields 空 = 全部）。"""
    prop = p.get("copy_proposal")
    if not prop:
        raise ValueError("没有待确认的优化")
    f = prop["fields"]
    keys = [k for k in (fields or list(f) + ["keyword_plan"]) if k in f or k == "keyword_plan"]
    c = p.setdefault("copy", {})
    changed = []
    for k in keys:
        if k == "keyword_plan":
            p["keyword_plan"] = prop["plan"]
            changed.append(k)
        elif k == "options_th":
            c["options_th"] = {**(c.get("options_th") or {}), **f[k]}
            changed.append(k)
        elif f.get(k) and f[k] != c.get(k):
            c[k] = f[k]
            changed.append(k)
    # 换了泰文标题 / 详情：回译跟着换
    if "title_th" in changed and "title_zh" in f and "title_zh" not in changed:
        c["title_zh"] = f["title_zh"]
    if "description_th" in changed and "description_zh" in f and "description_zh" not in changed:
        c["description_zh"] = f["description_zh"]
    if any(k in changed for k in ("title_th", "title_shopee_th")) and (p.get("exported_at") or p.get("shopee_exported_at")):
        p["title_changed_at"] = time.time()
        p["copy_dirty_after_export"] = time.time()       # 平台上的标题要重新导出 / 更新
    p.pop("copy_proposal", None)
    p.setdefault("seo_log", []).append({"at": time.time(), "by": user, "fields": changed})
    p["seo_log"] = p["seo_log"][-20:]
    return changed


def optimize(cfg, p, category_name="", user=""):
    """v2.24：一键搜索优化，直接生效（不用确认）：买家角度找词 + 重写标题 / 详情 / 标签 / 变体名 / 包装内容，
    关键词合并进①「关键词」。改之前存一份，可以「撤销」。已上架、14 天内改过标题的：这次不换标题（其他照换）。"""
    import copy as _copy
    from core import keywords
    before = score(p)["score"]
    snap = {"copy": _copy.deepcopy(p.get("copy") or {}), "keyword_plan": _copy.deepcopy(p.get("keyword_plan")),
            "keywords": p.get("keywords") or "", "at": time.time(), "score": before}
    prop = propose(cfg, p, category_name, user)
    wait = recently_changed(p)
    fields = [k for k in prop["fields"] if not (wait and k in ("title_th", "title_shopee_th", "title_zh"))]
    changed = apply(p, fields + ["keyword_plan"], user)
    mine = [x.strip() for x in str(snap["keywords"]).replace("，", ",").split(",") if x.strip()]
    allk = list(mine)
    for t in keywords.all_terms(p.get("keyword_plan") or {}):
        if t.lower() not in {x.lower() for x in allk}:
            allk.append(t)
    p["keywords"] = ", ".join(allk[:60])
    p["seo_undo"] = snap
    after = score(p)["score"]
    return {"changed": changed, "score_before": before, "score_after": after, "kept_titles": bool(wait), "wait_days": wait}


def undo(p):
    snap = p.get("seo_undo")
    if not snap:
        raise ValueError("没有可以撤销的优化")
    p["copy"] = snap["copy"]
    p["keyword_plan"] = snap["keyword_plan"]
    p["keywords"] = snap["keywords"]
    p.pop("seo_undo", None)
    return p


# ---------------- v2.24：AI 打分和建议 ----------------
REVIEW_SYSTEM = """You are a senior Lazada / Shopee Thailand search (SEO) and conversion reviewer.
Review this listing from two angles: (1) the BUYER - would a Thai shopper searching for what they want find it, understand it in
3 seconds and want to click? (2) the PLATFORM search ranking - main keyword early in the title, valuable synonyms, attributes,
variation names, Shopee hashtags, no keyword stuffing / repetition, no banned or IP words, title length well used.
Be concrete: for each problem give a short fix and, when useful, the full improved text for that field (Thai for Thai fields).
Never use brand / character / anime names or words about 3D printing / made to order. Never invent sizes or numbers.
Write the explanations in Simplified Chinese (problem_zh, suggestion_zh) and Thai (problem_th). Output ONLY JSON."""


def review(cfg, p):
    """AI 打分 + 具体建议（每条可以一键采用）。返回 {score, summary_zh, summary_th, items: [{field, level, problem_zh, problem_th, suggestion_zh, new_value}]}。"""
    import json as _json
    c = p.get("copy") or {}
    plan = p.get("keyword_plan") or {}
    info = {"product_zh": p.get("name_zh", ""), "facts": facts(p),
            "listing": {k: c.get(k) for k in ("title_th", "title_shopee_th", "title_en", "description_th", "hashtags_shopee",
                                               "package_content_th", "variation1_name_th", "variation2_name_th", "options_th")},
            "keyword_plan": {k: plan.get(k) for k in ("title_core", "need", "core", "synonym", "english", "scene", "audience", "longtail", "avoid") if plan.get(k)},
            "rule_checks_failed": [x["zh"] for x in score(p)["items"] if not x["ok"]]}
    user = (_json.dumps(info, ensure_ascii=False) + "\n\nReturn JSON: {\"score\": 0-100, \"summary_zh\": \"一两句总评\", \"summary_th\": \"...\", "
            "\"items\": [{\"field\": \"title_th|title_shopee_th|title_en|description_th|hashtags_shopee|package_content_th|variation1_name_th|variation2_name_th|other\", "
            "\"level\": \"高|中|低\", \"problem_zh\": \"问题\", \"problem_th\": \"...\", \"suggestion_zh\": \"怎么改\", "
            "\"new_value\": \"改好的完整内容（字段是 description_th 时用简单 HTML；只是建议、不好直接替换时留空）\"}]} — at most 8 items, most important first.")
    d = ai_copy.extract_json(ai_copy.call(cfg, REVIEW_SYSTEM, user))
    ok_fields = {"title_th", "title_shopee_th", "title_en", "description_th", "hashtags_shopee", "package_content_th",
                 "variation1_name_th", "variation2_name_th", "other"}
    items = []
    for x in d.get("items") or []:
        if not isinstance(x, dict) or not (x.get("problem_zh") or x.get("suggestion_zh")):
            continue
        f = x.get("field") if x.get("field") in ok_fields else "other"
        nv = str(x.get("new_value") or "").strip()
        if nv and (ai_copy.mentions_process(nv) or promo_left(nv)):
            nv = ""
        if f == "title_shopee_th":
            nv = nv[:SHOPEE_MAX]
        items.append({"field": f, "label": LABELS.get(f, "其他"), "level": x.get("level") if x.get("level") in ("高", "中", "低") else "中",
                      "problem_zh": str(x.get("problem_zh") or "")[:300], "problem_th": str(x.get("problem_th") or "")[:300],
                      "suggestion_zh": str(x.get("suggestion_zh") or "")[:400], "new_value": nv if f != "other" else ""})
    try:
        sc = max(0, min(100, int(float(d.get("score") or 0))))
    except (TypeError, ValueError):
        sc = None
    return {"score": sc, "summary_zh": str(d.get("summary_zh") or "")[:400], "summary_th": str(d.get("summary_th") or "")[:400],
            "items": items[:8], "at": time.time(), "rule_score": score(p)["score"]}
