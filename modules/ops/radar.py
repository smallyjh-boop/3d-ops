"""爆款雷达（第二期，从运营分析系统 modules/radar 搬过来）：关键词 → 搜索结果（需求、竞争、价格）
→ AI 判断能不能打印 / 侵权风险 / 小爆潜力 → 机会分 0–100（有侵权风险直接 0 分）。

数据来源：
  - 插件半自动巡逻：人在电脑前点「开始今日巡逻」，插件按清单低频打开搜索页、竞品页、竞店（每天有上限、每页随机停留、遇验证码停）
  - 自己打开搜索页点「采集搜索结果」
  - 卖家后台关键词工具页面（店铺后台数据识别后转过来）：关键词近 30 天搜索量
和 ERP 的「搜索优化」（core/keywords.py）的关系：产品的买家搜索词（keyword_plan）存在产品里，雷达不再存一份；
「从产品搜索词导入」把每个产品的主关键词加进雷达巡逻，雷达里每个词也会显示「我们哪些产品已经用了这个词」。
"""
import json
import math
import re
import statistics
import time
from urllib.parse import parse_qs, quote, urlparse

from core import db
from core.config import load_config

from . import mkt_db
from .mkt_util import AiError, ai_json, ai_on, card_numbers, clean_img, fee_rate, parse_count, parse_url, sku_rows, tf, ti, today, unit_cost

DAY = 86400

ASSESS_SYS = """你是 3D 打印电商的选品顾问。用户在泰国电商平台（Lazada / Shopee / TikTok）搜索了一个关键词，给你搜索结果前几名商品的标题和价格。
我们的设备：FDM 打印机（拓竹 P1S 256mm、Creality K1 Max 300mm、K1C 220mm 打印尺寸）和一台树脂打印机；材料 PLA、PETG、TPU、树脂。
我们不囤货、按单打印，要的是利润高、竞争少的冷门「小爆款」。我们只做自己的版本（用允许商用的模型或自己建模），不仿冒品牌、角色、专利外观。
判断这一类商品，只回复 JSON：
{"printable": 0到1（我们能不能用 3D 打印做出同类自己的版本，尺寸放不下、需要电子件 / 金属件 / 布料等的给低分）,
 "printable_reason": "一句话",
 "grams": 一件大约多少克耗材, "hours": 一件大约打印几小时, "material": "PLA"|"PETG"|"TPU"|"RESIN",
 "ip_risk": true/false（这一类商品主要是不是品牌、动漫游戏角色、受保护的外观设计）, "ip_reason": "一句话",
 "potential": 0到1（有没有变体、套装、定制空间，适不适合拍短视频做小爆）, "potential_reason": "一句话",
 "design_idea": "我们自己的版本可以怎么做出差异（一两句）",
 "summary": "一句话结论"}"""


def _c():
    return mkt_db.conn()


# ---------------- 关键词 ----------------
def add_keywords(platform, text, note="", source="manual", product_id=None):
    plat = (platform or "lazada").lower()
    if plat not in ("lazada", "shopee", "tiktok"):
        plat = "lazada"
    added = 0
    c = _c()
    for kw in re.split(r"[\n,，]+", text or ""):
        kw = kw.strip()[:80]
        if not kw:
            continue
        cur = c.execute("INSERT OR IGNORE INTO ops_radar_keywords(platform, keyword, note, created_at, source, product_id) VALUES(?,?,?,?,?,?)",
                        (plat, kw, (note or "")[:200], time.time(), source, product_id))
        added += cur.rowcount
    c.commit()
    return added


def import_from_products(platform="lazada", cfg=None):
    """从产品的买家搜索词（搜索优化做的 keyword_plan）导入：每个在售产品的标题主词 + 前 2 个核心词。返回加了几个。"""
    added, seen = 0, set()
    for r in _products(cfg):
        p = r["product"]
        if p["id"] in seen or r["draft"]:
            continue
        seen.add(p["id"])
        plan = p.get("keyword_plan") or {}
        words = [plan.get("title_core")] + list((plan.get("core") or [])[:2])
        words = [w for w in dict.fromkeys(str(w or "").strip() for w in words) if w]
        if words:
            added += add_keywords(platform, "\n".join(words), note=f"产品 {p['id']}", source="product", product_id=p["id"])
    return added


def _products(cfg=None):
    from .dash import price_rows
    return price_rows(cfg)


def product_hits(cfg=None):
    """{小写关键词: [产品编号…]}：哪些产品的买家搜索词或泰文标题里已经有这个词。"""
    from core import keywords
    out = {}
    seen = set()
    for r in _products(cfg):
        p = r["product"]
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        terms = keywords.all_terms(p.get("keyword_plan") or {}) + [plan_core for plan_core in [(p.get("keyword_plan") or {}).get("title_core")] if plan_core]
        for t in terms:
            out.setdefault(str(t).strip().lower(), set()).add(p["id"])
        out.setdefault("\0title", {})[p["id"]] = (p.get("title_th") or "").lower()
    return out


def _hits_for(kw, hits):
    k = (kw or "").strip().lower()
    ids = set(hits.get(k, set()))
    for pid, title in (hits.get("\0title") or {}).items():
        if k and k in title:
            ids.add(pid)
    return sorted(ids)[:12]


def keyword(kid):
    r = _c().execute("SELECT * FROM ops_radar_keywords WHERE id=?", (kid,)).fetchone()
    return dict(r) if r else None


def update_keyword(kid, data):
    sets = {k: data[k] for k in ("active", "status", "note") if k in data}
    if "active" in sets:
        sets["active"] = 1 if sets["active"] in (True, 1, "1", "true") else 0
    if "status" in sets and sets["status"] not in ("new", "want", "skip", "watch", "done"):
        sets.pop("status")
    if sets:
        _c().execute(f"UPDATE ops_radar_keywords SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), kid))
        _c().commit()


def delete_keyword(kid):
    c = _c()
    c.execute("DELETE FROM ops_radar_keywords WHERE id=?", (kid,))
    c.execute("DELETE FROM ops_radar_searches WHERE keyword_id=?", (kid,))
    c.commit()


def search_url(platform, kw):
    if platform == "lazada":
        return "https://www.lazada.co.th/catalog/?q=" + quote(kw)
    if platform == "shopee":
        return "https://shopee.co.th/search?keyword=" + quote(kw)
    return None


def keyword_from_url(url):
    u = urlparse(url or "")
    q = parse_qs(u.query)
    kw = (q.get("q") or q.get("keyword") or [""])[0].strip()
    plat = "lazada" if "lazada" in u.netloc else "shopee" if "shopee" in u.netloc else "tiktok" if "tiktok" in u.netloc else ""
    return plat, kw


# ---------------- 巡逻 ----------------
def patrol_done_today():
    return _c().execute("SELECT COUNT(*) FROM ops_patrol_log WHERE day=?", (today().isoformat(),)).fetchone()[0]


def log_patrol(kind, url, ok, note="", who=""):
    c = _c()
    c.execute("INSERT INTO ops_patrol_log(ts, day, kind, url, ok, note, who) VALUES(?,?,?,?,?,?,?)",
              (time.time(), today().isoformat(), (kind or "")[:20], (url or "")[:500], 1 if ok else 0, (note or "")[:200], (who or "")[:40]))
    c.execute("DELETE FROM ops_patrol_log WHERE ts < ?", (time.time() - 90 * DAY,))
    c.commit()


def patrol_plan(cfg=None):
    """今天的巡逻清单：先关键词搜索页（20 小时内没巡逻过的），再盯着的店铺，再竞品商品页（超过 20 小时没更新的）。"""
    from . import comp, shops
    cfg = cfg or load_config()
    cap = max(1, ti(cfg.get("oa_patrol_daily_cap"), 60))
    done = patrol_done_today()
    left = max(0, cap - done)
    items = []
    cutoff = time.time() - 20 * 3600
    for k in _c().execute("SELECT * FROM ops_radar_keywords WHERE active=1 AND status!='skip' ORDER BY COALESCE(last_patrol,0)"):
        if (k["last_patrol"] or 0) > cutoff:
            continue
        u = search_url(k["platform"], k["keyword"])
        if u:
            items.append({"kind": "search", "url": u, "ref": k["id"], "label": k["keyword"], "platform": k["platform"]})
    items += shops.patrol_items(cfg)
    if cfg.get("oa_patrol_competitors", True) not in (False, "0", 0, "false"):
        for r in comp.listing(cfg):
            last = r["est"].get("last_ts") or 0
            if r.get("url") and last < cutoff and r.get("platform") in ("lazada", "shopee", "tiktok"):
                items.append({"kind": "product", "url": r["url"], "ref": r["id"], "label": (r.get("title") or "")[:40], "platform": r["platform"]})
    wmin = max(5, ti(cfg.get("oa_patrol_wait_min"), 20))
    wmax = max(wmin, ti(cfg.get("oa_patrol_wait_max"), 60))
    return {"items": items[:left], "total": len(items), "cap": cap, "done": done, "left": left, "wait": [wmin, wmax]}


# ---------------- 搜索结果 ----------------
TOTAL_RE = [r"([\d,\.]+\s*(?:k|K|พัน|หมื่น)?)\s*(?:items? found|results?|รายการ|ผลลัพธ์|件商品|个结果)",
            r"(?:พบ|found|共)\s*([\d,\.]+\s*(?:k|K|พัน|หมื่น)?)"]


def parse_total(text):
    for p in TOTAL_RE:
        m = re.search(p, text or "", re.I)
        if m:
            v, _ = parse_count(m.group(1).replace(" ", ""))
            if v:
                return v
    return None


def record_search(cfg, body, who=""):
    """插件发来的搜索结果页：每张商品卡片的排名、价格、已售 + 结果总数。"""
    url = (body.get("url") or "").strip()
    plat, kw = keyword_from_url(url)
    kid = body.get("ref")
    c = _c()
    k = keyword(int(kid)) if str(kid or "").isdigit() else None
    if not k:
        if not kw:
            raise ValueError("认不出搜索关键词（网址里没有 q= 或 keyword=）")
        add_keywords(plat or "lazada", kw, source="ext")
        k = dict(c.execute("SELECT * FROM ops_radar_keywords WHERE platform=? AND keyword=?", (plat or "lazada", kw[:80])).fetchone())
    now = time.time()
    cards, seen = [], set()
    for card in (body.get("cards") or [])[:80]:
        p, key = parse_url(card.get("url") or "")
        if not key or key in seen or key == (card.get("url") or "").split("?")[0]:
            continue
        seen.add(key)
        nums = card_numbers(card.get("text") or "")
        sold, _g = parse_count(nums.get("sold_text"))
        cards.append({"key": key, "platform": p, "url": (card.get("url") or "").split("?")[0][:500], "title": (card.get("title") or "")[:200],
                      "image": clean_img(card.get("image")), "rank": len(cards) + 1, "price": nums.get("price"), "sold": sold,
                      "sold_text": nums.get("sold_text")})
    if not cards:
        log_patrol("search", url, False, "页面上没认出商品卡片", who)
        raise ValueError("页面上没认出商品卡片（可能还没加载完，或者是验证码页面）")
    for cd in cards:
        c.execute("""INSERT INTO ops_radar_items(item_key, platform, url, title, keyword_id, best_rank, first_seen, last_seen, image) VALUES(?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(item_key) DO UPDATE SET title=excluded.title, url=excluded.url, last_seen=excluded.last_seen,
                     best_rank=MIN(best_rank, excluded.best_rank), image=COALESCE(excluded.image, image)""",
                  (cd["key"], cd["platform"], cd["url"], cd["title"], k["id"], cd["rank"], now, now, cd["image"]))
        c.execute("INSERT INTO ops_radar_item_snaps(item_key, ts, keyword_id, rank, price, sold_total, sold_text) VALUES(?,?,?,?,?,?,?)",
                  (cd["key"], now, k["id"], cd["rank"], cd["price"], cd["sold"], cd["sold_text"]))
    top = cards[:10]
    prices = [x["price"] for x in top if x["price"]]
    solds = sorted((x["sold"] or 0 for x in top), reverse=True)
    sold10 = sum(solds)
    total = parse_total(body.get("total_text") or "") or parse_total(body.get("text") or "")
    c.execute("""INSERT INTO ops_radar_searches(keyword_id, ts, url, total_results, total_text, n_cards, price_median, sold_top10, top3_share)
                 VALUES(?,?,?,?,?,?,?,?,?)""",
              (k["id"], now, url[:500], total, (body.get("total_text") or "")[:80], len(cards),
               statistics.median(prices) if prices else None, sold10, round(sum(solds[:3]) / sold10, 3) if sold10 else None))
    c.execute("UPDATE ops_radar_keywords SET last_patrol=? WHERE id=?", (now, k["id"]))
    c.commit()
    log_patrol("search", url, True, f"{len(cards)} 个商品", who)
    if ai_on(cfg) and (not k.get("ai_ts") or now - k["ai_ts"] > 7 * DAY):
        try:
            assess(cfg, k["id"])
        except (AiError, ValueError):
            pass
    return {"keyword_id": k["id"], "keyword": k["keyword"], "cards": len(cards), "total_results": total,
            "opportunity": opportunity(cfg, keyword(k["id"]))}


def keyword_volumes(platform, rows, period_text=""):
    """卖家后台关键词工具：关键词近 30 天搜索量（店铺后台数据识别后转过来）。"""
    c = _c()
    n = 0
    for r in rows or []:
        kw = str(r.get("keyword") or "").strip()[:80]
        vol, _ = parse_count(r.get("search_volume"))
        if not kw or vol is None:
            continue
        bid, _ = parse_count(r.get("bid"))
        c.execute("INSERT INTO ops_radar_volumes(platform, keyword, ts, volume, bid, period_text) VALUES(?,?,?,?,?,?)",
                  (platform or "", kw, time.time(), vol, bid, (period_text or "")[:60]))
        n += 1
    c.commit()
    return n


# ---------------- AI 判断 ----------------
def assess(cfg, kid):
    k = keyword(kid)
    if not k:
        raise ValueError("没有这个关键词")
    s = latest_search(kid)
    its = top_items(kid, 10)
    if not its:
        raise ValueError("还没有搜索结果：先巡逻或打开搜索页采集一次")
    lines = "\n".join(f"{i['rank']}. {i['title']}（฿{i['price'] or '?'}，已售 {i['sold_text'] or '?'}）" for i in its)
    user = f"平台：{k['platform']}\n关键词：{k['keyword']}\n搜索结果商品数：{(s or {}).get('total_results') or '未知'}\n\n前几名：\n{lines}"
    r = ai_json(cfg, ASSESS_SYS, user)
    keep = ("printable", "printable_reason", "grams", "hours", "material", "ip_risk", "ip_reason", "potential", "potential_reason",
            "design_idea", "summary")
    data = {x: r.get(x) for x in keep}
    if isinstance(data.get("ip_risk"), str):
        data["ip_risk"] = data["ip_risk"].strip().lower() in ("true", "yes", "1", "是")
    _c().execute("UPDATE ops_radar_keywords SET ai=?, ai_ts=? WHERE id=?", (json.dumps(data, ensure_ascii=False), time.time(), kid))
    _c().commit()
    return data


# ---------------- 指标和机会分 ----------------
def latest_search(kid):
    r = _c().execute("SELECT * FROM ops_radar_searches WHERE keyword_id=? ORDER BY ts DESC LIMIT 1", (kid,)).fetchone()
    return dict(r) if r else None


def item_velocity(key):
    """单个商品的日销：两次记录的累计已售差值 ÷ 天数（约数精度不够时返回 None）。"""
    ss = [dict(r) for r in _c().execute("SELECT ts, sold_total, sold_text FROM ops_radar_item_snaps WHERE item_key=? AND sold_total IS NOT NULL ORDER BY ts", (key,))]
    if len(ss) < 2:
        return None
    last = ss[-1]
    older = [s for s in ss if last["ts"] - s["ts"] >= 0.8 * DAY]
    if not older:
        return None
    base = next((s for s in reversed(older) if last["ts"] - s["ts"] >= 6.5 * DAY), older[0])
    days = (last["ts"] - base["ts"]) / DAY
    delta = last["sold_total"] - base["sold_total"]
    g = max(parse_count(last["sold_text"])[1] or 1, parse_count(base["sold_text"])[1] or 1)
    if delta < 0 or (g > 1 and delta < g):
        return None
    return round(delta / days, 2)


def top_items(kid, n=10):
    s = latest_search(kid)
    if not s:
        return []
    rows = _c().execute("""SELECT i.item_key, i.url, i.title, i.platform, i.image, sn.rank, sn.price, sn.sold_total, sn.sold_text
        FROM ops_radar_item_snaps sn JOIN ops_radar_items i ON i.item_key=sn.item_key
        WHERE sn.keyword_id=? AND sn.ts=? ORDER BY sn.rank LIMIT ?""", (kid, s["ts"], n)).fetchall()
    return [{**dict(r), "daily": item_velocity(r["item_key"])} for r in rows]


def _clamp(x):
    return max(0.0, min(100.0, x))


def _w(cfg, k, d):
    return max(0.0, tf(cfg.get(f"oa_radar_w_{k}"), d))


def opportunity(cfg, k):
    """机会分 0–100 + 各项分数 + 依据（中文 notes / 泰文 notes_th）。缺数据的项按 50 分算并标出来；有侵权风险直接 0 分。"""
    s = latest_search(k["id"])
    its = top_items(k["id"], 10)
    try:
        aiv = json.loads(k["ai"]) if k.get("ai") else {}
    except ValueError:
        aiv = {}
    parts, notes = {}, []
    vel = [i["daily"] for i in its if i["daily"] is not None]
    if len(vel) >= 3:
        daily, dconf = sum(vel), "实测"
    elif s and s.get("sold_top10"):
        daily, dconf = s["sold_top10"] / 180, "估"          # 没有两次记录时，按累计已售 ÷ 约半年粗估
    else:
        daily, dconf = None, None
    vol = _c().execute("SELECT volume FROM ops_radar_volumes WHERE lower(keyword)=lower(?) ORDER BY ts DESC LIMIT 1", (k["keyword"],)).fetchone()
    if daily is not None:
        parts["demand"] = _clamp(25 * math.log2(1 + daily))
        if vol and vol["volume"]:
            parts["demand"] = round(0.6 * parts["demand"] + 0.4 * _clamp(20 * math.log10(1 + vol["volume"])), 1)
    else:
        parts["demand"] = 50.0
        notes.append(("需求数据不够", "ข้อมูลความต้องการยังไม่พอ"))
    if s and s.get("total_results"):
        cp = 100 - 20 * math.log10(s["total_results"] + 1)
        if (s.get("top3_share") or 0) > 0.7:
            cp -= 15
            notes.append(("销量集中在前 3 家", "ยอดขายกระจุกอยู่ 3 ร้านแรก"))
        parts["competition"] = _clamp(cp)
    else:
        parts["competition"] = 50.0
        notes.append(("没读到搜索结果总数", "ไม่ได้จำนวนผลการค้นหา"))
    parts["printable"] = _clamp(tf(aiv.get("printable"), 0) * 100) if aiv else 50.0
    parts["potential"] = _clamp(tf(aiv.get("potential"), 0) * 100) if aiv else 50.0
    if not aiv:
        notes.append(("AI 还没评估", "AI ยังไม่ได้ประเมิน"))
    price = (s or {}).get("price_median")
    uc = unit_cost(tf(aiv.get("grams"), 0), tf(aiv.get("hours"), 0), str(aiv.get("material") or "").upper() == "RESIN", cfg) if aiv else None
    rate, _z, _t = fee_rate(k["platform"], cfg)
    profit = margin = None
    if price and uc is not None:
        profit = round(price * (1 - rate) - uc, 2)
        margin = profit / price
        parts["profit"] = _clamp(margin * 150)
        if profit < 40:
            parts["profit"] = min(parts["profit"], 40.0)
            notes.append(("单件利润不到 ฿40", "กำไรต่อชิ้นไม่ถึง ฿40"))
    else:
        parts["profit"] = 50.0
        notes.append(("利润还算不出", "ยังคำนวณกำไรไม่ได้"))
    w = {"demand": _w(cfg, "demand", 25), "competition": _w(cfg, "competition", 20), "printable": _w(cfg, "printable", 20),
         "profit": _w(cfg, "profit", 25), "potential": _w(cfg, "potential", 10)}
    tw = sum(w.values()) or 1
    score = sum(parts[x] * w[x] for x in w) / tw
    ip = bool(aiv.get("ip_risk"))
    if ip:
        score = 0
        notes.insert(0, ("侵权风险：" + (aiv.get("ip_reason") or "品牌 / 角色 / 外观设计"),
                         "เสี่ยงละเมิดลิขสิทธิ์: " + (aiv.get("ip_reason") or "แบรนด์ / ตัวละคร / การออกแบบ")))
    return {"score": round(score), "parts": {x: round(v) for x, v in parts.items()}, "notes": [n[0] for n in notes], "notes_th": [n[1] for n in notes],
            "ip_risk": ip, "daily_top10": round(daily, 1) if daily is not None else None, "demand_conf": dconf,
            "volume": vol["volume"] if vol else None, "total_results": (s or {}).get("total_results"), "price_median": price,
            "unit_cost": uc, "fee_rate": rate, "profit_unit": profit, "margin": round(margin * 100, 1) if margin is not None else None,
            "top3_share": (s or {}).get("top3_share"), "thumbs": [i["image"] for i in its if i.get("image")][:3],
            "n_cards": (s or {}).get("n_cards"), "searched_at": (s or {}).get("ts"), "ai": aiv}


def board(cfg=None):
    cfg = cfg or load_config()
    hits = product_hits(cfg)
    rows = []
    for k in _c().execute("SELECT * FROM ops_radar_keywords ORDER BY id DESC"):
        k = dict(k)
        k["opp"] = opportunity(cfg, k)
        k["products"] = _hits_for(k["keyword"], hits)
        rows.append(k)
    rows.sort(key=lambda r: (r["status"] == "skip", not r["active"], -r["opp"]["score"]))
    plan = patrol_plan(cfg)
    log = [dict(r) for r in _c().execute("SELECT * FROM ops_patrol_log ORDER BY id DESC LIMIT 30")]
    return {"rows": rows, "patrol": {k: plan[k] for k in ("total", "cap", "done", "left", "wait")}, "log": log,
            "alert_score": ti(cfg.get("oa_radar_alert_score"), 70)}


def report_text(cfg=None, b=None):
    cfg = cfg or load_config()
    thr = ti(cfg.get("oa_radar_alert_score"), 70)
    b = b or board(cfg)
    good = [r for r in b["rows"] if r["active"] and r["status"] in ("new", "watch", "want") and r["opp"]["score"] >= thr - 10][:5]
    if not good:
        return None
    lines = [f"🔭 爆款雷达日报（{today().isoformat()}）"]
    for r in good:
        o = r["opp"]
        lines.append(f"· {r['keyword']}（{r['platform']}）{o['score']} 分"
                     + (f"，到手价中位 ฿{o['price_median']:.0f}" if o["price_median"] else "")
                     + (f"，单件利润 ฿{o['profit_unit']:.0f}" if o["profit_unit"] is not None else "")
                     + (f" — {o['ai'].get('summary')}" if o["ai"].get("summary") else ""))
    lines.append(f"今天已巡逻 {b['patrol']['done']} / {b['patrol']['cap']} 页")
    return "\n".join(lines)


def daily_report(cfg=None, force=False):
    """每天到点（oa_radar_report_hour，本机时间）推一次机会日报（LINE / Telegram，和手机提醒同一个渠道）。返回推送的文字或 None。"""
    import datetime as dt
    from . import alerts
    cfg = cfg or load_config()
    now = dt.datetime.now()
    day = now.date().isoformat()
    if not force and (now.hour < ti(cfg.get("oa_radar_report_hour"), 8) or db.kv_get("oa_radar_report_day") == day):
        return None
    mkt_db.ensure()
    db.kv_set("oa_radar_report_day", day)
    text = report_text(cfg)
    if text:
        alerts.send(text, cfg)
    return text
