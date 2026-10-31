"""需求 ↔ 供给：运营模块的爆款雷达（泰国平台上的搜索词、日销、结果数、到手价）和选品（模型网站上的模型）连起来。

  · 候选卡片 / 选品库：标题或 AI 给的泰文搜索词里有雷达关键词时，显示那个词在泰国的需求、竞争、价格（matcher）
  · 爆款雷达的高分关键词「去模型站找」：建关注巡逻（每个模型网站一个关键词搜索），扩展巡逻后新模型进候选池（from_radar）
运营模块关着时什么都不显示（modules.public("ops") 是 None）。
"""
import re

from core import modules


def _ops():
    try:
        return modules.public("ops")
    except Exception:  # noqa: BLE001
        return None


def keywords():
    o = _ops()
    if not o or not hasattr(o, "market_keywords"):
        return []
    try:
        return o.market_keywords()
    except Exception:  # noqa: BLE001  运营模块的数据有问题不影响选品
        return []


def matcher(kws=None):
    """返回 f(标题, 泰文搜索词列表) → 对上的雷达关键词（分最高的一个）或 None。"""
    kws = keywords() if kws is None else kws
    kws = [k for k in kws if (k.get("keyword") or "").strip()]

    def f(title, thai=()):
        if not kws:
            return None
        hay = " ".join([str(title or "")] + [str(x) for x in thai or []]).lower()
        hits = [k for k in kws if k["keyword"].lower() in hay or any(k["keyword"].lower() == str(x).lower() for x in thai or [])]
        if not hits:
            return None
        k = max(hits, key=lambda x: x.get("score") or 0)
        return {key: k.get(key) for key in ("id", "keyword", "platform", "score", "daily_top10", "total_results", "price_median", "ip_risk", "comps")}
    return f


def english_term(cfg, kw):
    """雷达关键词多是泰文；模型网站要英文。有 AI 时翻成 2–4 个英文词，没有就原样。"""
    if re.fullmatch(r"[\x00-\x7f]+", kw or ""):
        return kw.strip()
    from .cand import ai_json, ai_on
    if ai_on(cfg):
        try:
            d = ai_json(cfg, "You translate a Thai e-commerce search keyword into a short English search term (2-4 words) that would find "
                             "matching 3D-printable models on MakerWorld / Printables. Output only JSON {\"en\": \"...\"}.", {"keyword": kw})
            en = str(d.get("en") or "").strip()
            if en:
                return en[:60]
        except Exception:  # noqa: BLE001
            pass
    return kw.strip()


def from_radar(cfg, kid=None, keyword="", who=""):
    """爆款雷达的关键词 → 每个启用的模型网站建一个「关键词」关注（已经有的不重复建）。返回 {term, added:[…], existing}。"""
    from . import sites, watch
    kw = (keyword or "").strip()
    if kid:
        o = _ops()
        k = o.market_keyword(int(kid)) if o and hasattr(o, "market_keyword") else None
        if not k:
            raise ValueError("爆款雷达里没有这个关键词")
        kw = k["keyword"]
    if not kw:
        raise ValueError("缺少关键词")
    term = english_term(cfg, kw)
    added, existing = [], 0
    seen = set()
    for sid, _name, _url in sites.search_entries():
        s = next((x for x in sites.load().values() if any(e["id"] == sid for e in x.get("search") or [])), None)
        if not s or s["id"] in seen:          # 一个网站只建一个（MakerWorld 有国际站和中国站两个搜索入口）
            continue
        seen.add(s["id"])
        try:
            w = watch.add({"kind": "keyword", "site": sid, "value": term, "label": f"{kw} → {term}" if term != kw else kw, "source": "radar"}, who)
            added.append(w)
        except ValueError:
            existing += 1
    return {"term": term, "keyword": kw, "added": added, "existing": existing}
