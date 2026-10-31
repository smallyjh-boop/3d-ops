"""竞店（第二期，从运营分析系统 modules/shops 搬过来）：我的店铺 + 竞店。只读买家也能看到的店铺页面
（粉丝、好评率、回复率、在售商品的价格和已售）。

数据来源：
  - 插件在店铺页点「🏪 采集店铺」；插件巡逻（盯着的店铺，每 N 天一次）
  - 采竞品时顺手记下它的店铺（先不盯，列在「候选」里，点「盯这家」才巡逻）
  - 我的店铺另外直接用 ERP 的数：订单（实际日销、销售额）和第一期 Lazada 店铺表现（回复率、好评率等）
推算：
  - 店铺日销（下限）= 采到的商品两次「累计已售」相减 ÷ 天数，加起来；只看得到店铺页上展示的那些商品
  - 上新：最近 7 天第一次出现的商品；新品起量：14 天内新出现、日销 ≥ 1 的
"""
import datetime as dt
import re
import statistics
import time
from urllib.parse import parse_qs, urlparse

from core import db
from core.config import load_config

from . import mkt_db
from .mkt_util import AiError, ai_json, ai_on, card_numbers, clean_img, day_start_ts, parse_count, parse_url, ti, today

DAY = 86400
SHOPEE_RESERVED = {"search", "product", "cart", "user", "buyer", "m", "mall", "flash_sale", "daily_discover", "shop", "verify",
                   "checkout", "buyer_login", "seller", "events3", "deals", "top_products", "find_similar_products", "promotions"}

EXTRACT_SYS = """你是泰国电商数据录入助手。用户粘贴的是 Lazada / Shopee 店铺页面的文字。只提取页面上真实出现的数字，不要猜，没有填 null。只回复 JSON：
{"name": 店铺名, "followers": 粉丝数（原文，如 "1.2พัน"）, "positive_pct": 好评率 / 店铺评分百分比（数字 0-100）,
 "rating": 店铺评分 0-5, "reviews": 评价数（原文）, "products": 商品数, "response_rate": 聊天回复率（数字 0-100）,
 "response_time": 回复时间（原文简短）, "ship_on_time": 准时发货率（数字 0-100）, "joined_text": 开店 / 加入时间（原文简短）,
 "main_category": 主营类目}"""


def _c():
    return mkt_db.conn()


# ---------------- 网址 ----------------
def parse_shop(url):
    """店铺网址 → (平台, 店铺唯一键, 名字里的标识)。认不出返回 (平台, None, None)。"""
    u = urlparse((url or "").strip())
    host, path = u.netloc.lower(), u.path or "/"
    q = parse_qs(u.query)
    if "lazada" in host:
        m = re.match(r"^/shop/([^/?#]+)", path)
        if m:
            return "lazada", f"lazada:{m.group(1).lower()}", m.group(1)
        seg = [s for s in path.split("/") if s]
        if len(seg) == 1 and (q.get("from") == ["wangpu"] or "All-Products" in (q.get("q") or [""])[0]):
            return "lazada", f"lazada:{seg[0].lower()}", seg[0]
        return "lazada", None, None
    if "shopee" in host:
        m = re.match(r"^/shop/(\d+)", path)
        if m:
            return "shopee", f"shopee:shop:{m.group(1)}", m.group(1)
        seg = [s for s in path.split("/") if s]
        if len(seg) == 1 and seg[0].lower() not in SHOPEE_RESERVED and not re.search(r"-i\.\d+\.\d+|-cat\.|\.html$", seg[0]):
            return "shopee", f"shopee:{seg[0].lower()}", seg[0]
        return "shopee", None, None
    return "", None, None


def patrol_urls(shop):
    slug = shop["shop_key"].split(":")[-1]
    if shop["platform"] == "lazada":
        return [("profile", f"https://www.lazada.co.th/shop/{slug}?path=profile.htm&pageTypeId=3"),
                ("items", f"https://www.lazada.co.th/{slug}/?q=All-Products&from=wangpu&langFlag=th&pageTypeId=2")]
    if shop["shop_key"].startswith("shopee:shop:"):
        return [("home", f"https://shopee.co.th/shop/{slug}?sortBy=sales")]
    return [("home", f"https://shopee.co.th/{slug}?sortBy=sales")]


# ---------------- 读写 ----------------
def get(sid):
    r = _c().execute("SELECT * FROM ops_shops WHERE id=?", (sid,)).fetchone()
    return dict(r) if r else None


def by_key(key):
    r = _c().execute("SELECT * FROM ops_shops WHERE shop_key=?", (key,)).fetchone()
    return dict(r) if r else None


def ensure(url, name="", watch=None, mine=None):
    """按网址找到或新建店铺；watch / mine 传了才改。返回店铺 dict。"""
    plat, key, slug = parse_shop(url)
    if not key:
        raise ValueError("认不出店铺网址：请用 Lazada / Shopee 的店铺首页链接")
    c = _c()
    s = by_key(key)
    if not s:
        c.execute("INSERT INTO ops_shops(platform, shop_key, name, url, is_mine, watch, created_at) VALUES(?,?,?,?,?,?,?)",
                  (plat, key, (name or slug)[:120], url.split("#")[0][:500], 1 if mine else 0, 1 if watch else 0, time.time()))
    else:
        sets = {}
        if watch is not None:
            sets["watch"] = 1 if watch else 0
        if mine is not None:
            sets["is_mine"] = 1 if mine else 0
        if name and (not s["name"] or s["name"] == slug):
            sets["name"] = name[:120]
        if sets:
            c.execute(f"UPDATE ops_shops SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), s["id"]))
    c.commit()
    return by_key(key)


def sync_mine(cfg):
    """设置里的「我的店铺前台链接」→ is_mine。"""
    urls = [u for u in re.split(r"\s+", cfg.get("oa_my_shop_urls") or "") if u.startswith("http")]
    keys = set()
    for u in urls:
        try:
            keys.add(ensure(u, mine=True, watch=True)["shop_key"])
        except ValueError:
            continue
    c = _c()
    for r in c.execute("SELECT id, shop_key FROM ops_shops WHERE is_mine=1").fetchall():
        if r["shop_key"] not in keys:
            c.execute("UPDATE ops_shops SET is_mine=0 WHERE id=?", (r["id"],))
    c.commit()


def update(sid, data):
    sets = {}
    if "watch" in data:
        sets["watch"] = 1 if data["watch"] in (True, 1, "1", "true") else 0
    if "note" in data:
        sets["note"] = str(data["note"] or "")[:300]
    if "erp_shop" in data:
        sets["erp_shop"] = str(data["erp_shop"] or "")[:120] or None
    if sets:
        _c().execute(f"UPDATE ops_shops SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), sid))
        _c().commit()


def delete(sid):
    c = _c()
    for t in ("ops_shop_snaps", "ops_shop_items", "ops_shop_item_snaps", "ops_shop_comp_links"):
        c.execute(f"DELETE FROM {t} WHERE shop_id=?", (sid,))
    c.execute("DELETE FROM ops_shops WHERE id=?", (sid,))
    c.commit()


def seen(url, comp_id=None, name=""):
    """采竞品时顺手记下它的店铺（不盯，进候选）。"""
    try:
        s = ensure(url, name=name)
    except ValueError:
        return None
    if comp_id:
        _c().execute("INSERT OR IGNORE INTO ops_shop_comp_links(shop_id, comp_id) VALUES(?,?)", (s["id"], comp_id))
        _c().commit()
    return s["id"]


# ---------------- 识别店铺页面文字 ----------------
def _pct(v):
    n = parse_count(v)[0] if v is not None else None
    return n if n is not None and 0 <= n <= 100 else None


def parse_text(text):
    """规则识别（Lazada / Shopee 店铺页常见写法）。"""
    raw = text or ""
    t = re.sub(r"\s+", " ", raw)
    out = {}
    m = (re.search(r"([\d.,]+\s*(?:k|K|M|พัน|หมื่น|แสน)?)\s*(?:Followers|ผู้ติดตาม)", t)
         or re.search(r"(?:ผู้ติดตาม|Followers)\s*[:：]?\s*([\d.,]+\s*(?:k|K|M|พัน|หมื่น|แสน)?)", t))
    if m:
        out["followers"] = m.group(1).replace(" ", "")
    m = re.search(r"(\d{1,3}(?:\.\d)?)\s*%\s*(?:คะแนนร้านค้าเชิงบวก|Positive Seller Ratings)", t) or re.search(r"คะแนนร้านค้า\s*(\d{1,3})\s*%", t)
    if m:
        out["positive_pct"] = m.group(1)
    m = re.search(r"คะแนน\s*[:：]?\s*([0-5](?:\.\d)?)\s*\(\s*([\d.,]+\s*(?:k|K|พัน|หมื่น)?)", t)
    if m:
        out["rating"], out["reviews"] = m.group(1), m.group(2).replace(" ", "")
    m = re.search(r"(?:รายการสินค้า|สินค้าทั้งหมด|Products)\s*[:：]?\s*([\d.,]+\s*(?:k|K|พัน)?)(?!\s*%)", t)
    if m:
        out["products"] = m.group(1).replace(" ", "")
    m = re.search(r"อัตราการตอบกลับ[^%]{0,40}?(\d{1,3})\s*%", t) or re.search(r"(?:Chat Response Rate|Response Rate)\s*[:：]?\s*(\d{1,3})\s*%", t)
    if m:
        out["response_rate"] = m.group(1)
    m = re.search(r"(?:เวลาในการตอบกลับ|Response Time)\s*[:：]?\s*((?:ภายใน|within)?\s*[^\s]{0,12}\s*(?:นาที|ชั่วโมง|ชม\.?|วัน|minutes?|hours?|days?))", t)
    if m:
        out["response_time"] = m.group(1).strip()
    m = re.search(r"(?:ส่งสินค้าตรงเวลา|ส่งตรงเวลา|Ship on Time)\s*[:：]?\s*(\d{1,3})\s*%", t)
    if m:
        out["ship_on_time"] = m.group(1)
    m = re.search(r"(?:สมัครสมาชิกเมื่อ|เข้าร่วม(?:เมื่อ)?|Joined)\s*[:：]?\s*([\d\s+]+\s*(?:ปี|เดือน|วัน|years?|months?|days?)(?:ที่แล้ว)?)", t)
    if m:
        out["joined_text"] = re.sub(r"\s+", "", m.group(1)).replace("+", "+ ")
    m = re.search(r"หมวดหมู่หลัก\s+(.{2,60}?)\s+(?:สมัครสมาชิก|Chat|แชท)", t)
    if m:
        out["main_category"] = m.group(1).strip()
    lines = [x.strip() for x in raw.splitlines() if x.strip()]
    for i, ln in enumerate(lines[1:], 1):
        if re.match(r"^[\d.,]+\s*(?:k|K|M|พัน|หมื่น)?\s*(?:Followers|ผู้ติดตาม)", ln):
            out["name"] = lines[i - 1][:120]
            break
    return out


def extract(cfg, text, title=""):
    data = parse_text(text)
    how = "rules"
    if ai_on(cfg) and len((text or "").strip()) > 80 and not (data.get("followers") or data.get("positive_pct") or data.get("rating")):
        try:
            r = ai_json(cfg, EXTRACT_SYS, (text or "")[:6000])
            data = {k: v for k, v in r.items() if v not in (None, "")} | {k: v for k, v in data.items() if v not in (None, "")}
            how = "ai"
        except AiError:
            pass
    if not data.get("name") and title:
        data["name_from_title"] = re.split(r"\s*[|｜]\s*", title)[0].replace("ร้านค้าออนไลน์อย่างเป็นทางการ", "").replace(" ประเทศไทย", "").strip()[:120]
    return data, how


# ---------------- 采集 ----------------
def record(cfg, body):
    """插件发来的店铺页面：店铺数字 + 页面上的商品卡片。"""
    url = (body.get("url") or "").strip()
    ref = body.get("ref")
    s = get(int(ref)) if str(ref or "").isdigit() else None
    if not s:
        s = ensure(url, watch=True if body.get("watch", True) else None)
    data, how = extract(cfg, body.get("text") or "", body.get("title") or "")
    c = _c()
    now = time.time()
    stats = {"followers": parse_count(data.get("followers"))[0], "positive_pct": _pct(data.get("positive_pct")),
             "rating": parse_count(data.get("rating"))[0], "reviews": parse_count(data.get("reviews"))[0],
             "products": parse_count(data.get("products"))[0], "response_rate": _pct(data.get("response_rate")),
             "response_time": (str(data.get("response_time") or "")[:40] or None), "ship_on_time": _pct(data.get("ship_on_time")),
             "joined_text": (str(data.get("joined_text") or "")[:40] or None), "main_category": (str(data.get("main_category") or "")[:80] or None)}
    if stats["rating"] is not None and not 0 <= stats["rating"] <= 5:
        stats["rating"] = None
    has_stats = any(v is not None for v in stats.values())
    if has_stats:
        last = c.execute("SELECT * FROM ops_shop_snaps WHERE shop_id=? ORDER BY ts DESC LIMIT 1", (s["id"],)).fetchone()
        if last and now - last["ts"] < 1800:            # 半小时内（巡逻连看两页）：合并到同一条
            sets = {k: v for k, v in stats.items() if v is not None}
            c.execute(f"UPDATE ops_shop_snaps SET {', '.join(k + '=?' for k in sets)}, ts=? WHERE id=?", (*sets.values(), now, last["id"]))
        else:
            c.execute(f"INSERT INTO ops_shop_snaps(shop_id, ts, how, {', '.join(stats)}) VALUES(?,?,?,{','.join('?' * len(stats))})",
                      (s["id"], now, how, *stats.values()))
    n = 0
    seen_keys = set()
    for card in (body.get("cards") or [])[:120]:
        _p, key = parse_url(card.get("url") or "")
        if not key or key in seen_keys or key == (card.get("url") or "").split("?")[0]:
            continue
        seen_keys.add(key)
        nums = card_numbers(card.get("text") or "")
        sold, _g = parse_count(nums.get("sold_text"))
        c.execute("""INSERT INTO ops_shop_items(shop_id, item_key, url, title, image, first_seen, last_seen) VALUES(?,?,?,?,?,?,?)
                     ON CONFLICT(shop_id, item_key) DO UPDATE SET url=excluded.url, title=excluded.title, last_seen=excluded.last_seen,
                     image=COALESCE(excluded.image, image)""",
                  (s["id"], key, (card.get("url") or "").split("?")[0][:500], (card.get("title") or "")[:200], clean_img(card.get("image")), now, now))
        last = c.execute("SELECT ts FROM ops_shop_item_snaps WHERE shop_id=? AND item_key=? ORDER BY ts DESC LIMIT 1", (s["id"], key)).fetchone()
        if last and now - last["ts"] < 1800:
            c.execute("DELETE FROM ops_shop_item_snaps WHERE shop_id=? AND item_key=? AND ts=?", (s["id"], key, last["ts"]))
        c.execute("INSERT INTO ops_shop_item_snaps(shop_id, item_key, ts, price, sold_total, sold_text) VALUES(?,?,?,?,?,?)",
                  (s["id"], key, now, nums.get("price"), sold, nums.get("sold_text")))
        n += 1
    if not has_stats and not n:
        c.commit()
        raise ValueError("页面上没认出店铺数据和商品（可能还没加载完，或者是验证码页面）")
    name = data.get("name")
    slug = s["shop_key"].split(":")[-1]
    if not name and data.get("name_from_title") and (not s["name"] or s["name"] == slug) and "All-Products" not in data["name_from_title"]:
        name = data["name_from_title"]
    logo = clean_img(body.get("logo")) if has_stats else None
    c.execute("UPDATE ops_shops SET last_capture=?, name=COALESCE(?, name), logo=COALESCE(?, logo) WHERE id=?",
              (now, str(name)[:120] if name and len(str(name)) > 1 else None, logo, s["id"]))
    c.commit()
    return {"shop_id": s["id"], "how": how, "items": n, "stats": has_stats, "metrics": metrics(get(s["id"]))}


# ---------------- 推算 ----------------
def _velocity(sn):
    ss = [x for x in sn if x["sold_total"] is not None]
    if len(ss) < 2:
        return None
    last = ss[-1]
    older = [x for x in ss if last["ts"] - x["ts"] >= 0.8 * DAY]
    if not older:
        return None
    base = next((x for x in reversed(older) if last["ts"] - x["ts"] >= 6.5 * DAY), older[0])
    g = max(parse_count(last["sold_text"])[1] or 1, parse_count(base["sold_text"])[1] or 1)
    delta = last["sold_total"] - base["sold_total"]
    if delta < 0 or (g > 1 and delta < g):
        return None
    return round(delta / ((last["ts"] - base["ts"]) / DAY), 2)


def items(sid, limit=200):
    c = _c()
    sn = {}
    for r in c.execute("SELECT item_key, ts, price, sold_total, sold_text FROM ops_shop_item_snaps WHERE shop_id=? ORDER BY ts", (sid,)):
        sn.setdefault(r["item_key"], []).append(dict(r))
    out = []
    for r in c.execute("SELECT * FROM ops_shop_items WHERE shop_id=? ORDER BY last_seen DESC LIMIT ?", (sid, limit)):
        ss = sn.get(r["item_key"]) or []
        last = ss[-1] if ss else {}
        out.append({**dict(r), "price": last.get("price"), "sold_total": last.get("sold_total"), "sold_text": last.get("sold_text"),
                    "daily": _velocity(ss)})
    return out


def metrics(s):
    """一家店铺的推算结果。"""
    c = _c()
    now = time.time()
    sn = [dict(r) for r in c.execute("SELECT * FROM ops_shop_snaps WHERE shop_id=? ORDER BY ts", (s["id"],))]
    last = sn[-1] if sn else {}
    wk = next((x for x in reversed(sn) if last and last["ts"] - x["ts"] >= 6 * DAY), None)
    its = items(s["id"])
    live = [i for i in its if i["last_seen"] >= now - 4 * DAY] or its
    vel = [i["daily"] for i in live if i["daily"] is not None]
    prices = sorted(i["price"] for i in live if i["price"])
    tracked_days = (now - s["created_at"]) / DAY if s.get("created_at") else 0
    new7 = [i for i in its if i["first_seen"] >= now - 7 * DAY] if tracked_days >= 7 else None
    hot_new = sorted([i for i in its if i["first_seen"] >= now - 14 * DAY and tracked_days >= 3 and (i["daily"] or 0) >= 1],
                     key=lambda i: -(i["daily"] or 0))
    daily = round(sum(vel), 1) if vel else None
    rev30 = round(sum((i["daily"] or 0) * (i["price"] or 0) for i in live) * 30) if vel else None
    by = sorted(((i["daily"] or 0) for i in live), reverse=True) if vel else sorted(((i["sold_total"] or 0) for i in live), reverse=True)
    tot = sum(by)
    top = sorted(live, key=lambda i: (-(i["daily"] or -1), -(i["sold_total"] or 0)))[:5]
    pick = ("item_key", "url", "title", "image", "price", "sold_text", "daily")
    return {
        "followers": last.get("followers"),
        "followers_7d": round(last["followers"] - wk["followers"]) if wk and last.get("followers") is not None and wk.get("followers") is not None else None,
        "positive_pct": last.get("positive_pct"), "rating": last.get("rating"), "reviews": last.get("reviews"),
        "products": last.get("products"), "items_seen": len(live), "response_rate": last.get("response_rate"),
        "response_time": last.get("response_time"), "ship_on_time": last.get("ship_on_time"), "joined_text": last.get("joined_text"),
        "main_category": last.get("main_category"), "daily": daily, "daily_n": len(vel), "rev_30d": rev30,
        "conf": "实测" if vel else None, "top3_share": round(sum(by[:3]) / tot, 3) if tot else None,
        "new_7d": len(new7) if new7 is not None else None,
        "price_min": prices[0] if prices else None, "price_median": statistics.median(prices) if prices else None,
        "price_max": prices[-1] if prices else None, "sold_sum": sum(i["sold_total"] or 0 for i in live) or None,
        "top": [{k: i[k] for k in pick} for i in top], "hot_new": [{k: i[k] for k in pick} for i in hot_new[:5]],
        "last_ts": last.get("ts") or s.get("last_capture"), "n_snaps": len(sn),
    }


BENCH = ("followers", "positive_pct", "response_rate", "items_seen", "daily", "new_7d")
GAP_LABEL = {"positive_pct": ("好评率", "คะแนนร้านเชิงบวก", "%"), "response_rate": ("聊天回复率", "อัตราตอบแชท", "%"),
             "followers": ("粉丝", "ผู้ติดตาม", ""), "items_seen": ("在售商品", "สินค้าที่ขาย", ""), "new_7d": ("近 7 天上新", "สินค้าใหม่ 7 วัน", "")}


def erp_mine(days=30):
    """我的店铺在 ERP 里的真实数字：按订单里的店铺名，近 N 天订单数、件数、销售额、每天几单；
    Lazada 店铺加上第一期拉下来的店铺表现（回复率、好评率等）。"""
    from core.finance import EXCLUDE
    since = day_start_ts(today() - dt.timedelta(days=days - 1))
    c = db.conn()
    rows = c.execute(f"""SELECT LOWER(o.platform) platform, COALESCE(o.shop,'') shop, COUNT(DISTINCT o.id) n, SUM(i.qty) units,
                         SUM(i.item_total) revenue FROM orders o LEFT JOIN order_items i ON i.order_id=o.id
                         WHERE o.order_time>=? AND o.status NOT IN ({','.join('?' * len(EXCLUDE))})
                         AND LOWER(o.platform) IN ('lazada','shopee','tiktok') GROUP BY LOWER(o.platform), COALESCE(o.shop,'')
                         ORDER BY n DESC""", (since, *EXCLUDE)).fetchall()
    perf = {}
    try:
        from . import lazada
        for p in lazada.performance():
            perf[(p["shop"] or "").strip().lower()] = p
    except Exception:  # noqa: BLE001
        perf = {}
    out = []
    for r in rows:
        p = perf.get(r["shop"].strip().lower()) if r["platform"] == "lazada" else None
        if p is None and r["platform"] == "lazada" and len(perf) == 1 and not r["shop"]:
            p = next(iter(perf.values()))
        rr = pr = None
        for m in (p or {}).get("metrics") or []:
            nm = f"{m.get('name') or ''} {m.get('type') or ''}".lower()
            val = parse_count(str(m.get("value") or "").replace("%", ""))[0]
            if rr is None and "response" in nm and "rate" in nm:
                rr = val
            if pr is None and ("positive" in nm or "rating" in nm):
                pr = val
        out.append({"platform": r["platform"], "shop": r["shop"], "orders": r["n"], "units": r["units"] or 0,
                    "revenue": round(r["revenue"] or 0, 2), "daily_orders": round(r["n"] / days, 2), "daily_units": round((r["units"] or 0) / days, 2),
                    "perf": (p or {}).get("metrics") or [], "perf_at": (p or {}).get("at"), "response_rate": rr, "positive": pr})
    return out


def board(cfg=None):
    cfg = cfg or load_config()
    sync_mine(cfg)
    c = _c()
    rows = []
    links = {r["shop_id"]: r["n"] for r in c.execute("SELECT shop_id, COUNT(*) n FROM ops_shop_comp_links GROUP BY shop_id")}
    for s in c.execute("SELECT * FROM ops_shops ORDER BY is_mine DESC, watch DESC, id DESC"):
        s = dict(s)
        rows.append({**s, "comps": links.get(s["id"], 0), "m": metrics(s)})
    watched = [r for r in rows if r["watch"] and not r["is_mine"]]
    bench = {}
    for k in BENCH:
        v = [r["m"][k] for r in watched if r["m"][k] is not None and r["m"]["last_ts"]]
        bench[k] = round(statistics.median(v), 1) if v else None
    erp = erp_mine()
    gaps = []
    for r in [r for r in rows if r["is_mine"]]:
        m = r["m"]
        for k, (zh, th, unit) in GAP_LABEL.items():
            if m[k] is not None and bench[k] is not None and m[k] < bench[k] * 0.9:
                gaps.append({"shop_id": r["id"], "shop": r["name"], "key": k, "label": zh, "label_th": th, "mine": m[k], "bench": bench[k], "unit": unit})
    # 我的店铺的 ERP 实际日销 vs 竞店日销（下限）的中位
    erp_daily = sum(e["daily_units"] for e in erp)
    if bench["daily"] is not None and erp and erp_daily < bench["daily"] * 0.9:
        gaps.append({"shop_id": None, "shop": "ERP", "key": "daily", "label": "每天卖出件数（ERP 实际）", "label_th": "ชิ้นที่ขายต่อวัน (ERP จริง)",
                     "mine": round(erp_daily, 1), "bench": bench["daily"], "unit": ""})
    return {"rows": rows, "bench": bench, "gaps": gaps, "n_watch": len(watched), "erp": erp, "erp_daily_units": round(erp_daily, 2),
            "mine_set": bool((cfg.get("oa_my_shop_urls") or "").strip())}


def patrol_items(cfg):
    """给巡逻清单：盯着的店铺（含我的店铺），超过「每隔几天」没采集的。"""
    sync_mine(cfg)
    every = max(1, ti(cfg.get("oa_shop_patrol_days"), 1)) * DAY - 4 * 3600
    out = []
    for s in _c().execute("SELECT * FROM ops_shops WHERE watch=1 OR is_mine=1 ORDER BY is_mine DESC, COALESCE(last_capture,0)"):
        if time.time() - (s["last_capture"] or 0) < every:
            continue
        for step, u in patrol_urls(dict(s)):
            out.append({"kind": "shop", "url": u, "ref": s["id"], "label": (s["name"] or s["shop_key"])[:40] + ("（我的）" if s["is_mine"] else ""),
                        "platform": s["platform"], "step": step})
    return out


def detail(sid):
    s = get(sid)
    if not s:
        return None
    sn = [dict(r) for r in _c().execute("SELECT * FROM ops_shop_snaps WHERE shop_id=? ORDER BY ts DESC LIMIT 60", (sid,))]
    comps = [dict(r) for r in _c().execute("SELECT c.id, c.title, c.platform FROM ops_shop_comp_links l JOIN ops_comp c ON c.id=l.comp_id "
                                           "WHERE l.shop_id=?", (sid,))]
    return {"shop": s, "m": metrics(s), "snaps": sn, "items": items(sid, 300), "comps": comps}


def ext_known(urls):
    keys = {}
    for u in urls or []:
        _p, k, _s = parse_shop(u)
        if k:
            keys[u] = k
    if not keys:
        return {}
    ks = list(set(keys.values()))
    rows = {r["shop_key"]: dict(r) for r in _c().execute(
        f"SELECT id, shop_key, watch, is_mine FROM ops_shops WHERE shop_key IN ({','.join('?' * len(ks))})", ks)}
    return {u: rows[k] for u, k in keys.items() if k in rows}
