"""店铺后台数据（第二期，从运营分析系统 modules/traffic 搬过来）：员工自己登录的卖家中心页面（商品数据 / 流量 / 关键词），
插件采集后 AI 识别成每个商品的曝光、访客、浏览、加购、订单、转化率，按卖家 SKU 对上 ERP 的 SKU。
不保存平台账号密码、cookie，不保存买家信息（AI 提示词要求忽略，入库字段里也没有）。
关键词工具页面的搜索量转给爆款雷达（radar.keyword_volumes）。商品生命周期和运营看板会显示这些数。
"""
import re
import time

from . import mkt_db
from .mkt_util import AiError, ai_json, ai_on, parse_count, sku_rows

BACKEND_SYS = """你是泰国电商卖家后台的数据录入助手。用户会给你 Lazada Seller Center / Shopee 卖家中心 / TikTok Shop 卖家后台某个页面的
表格和文字（泰文、英文、中文都有）。提取「按商品」的经营数据，只要页面上真实出现的数字，不要猜，没有的填 null。
忽略任何买家姓名、电话、地址、订单收件信息。只回复 JSON：
{"kind": "页面类型：product_performance（商品数据/流量）| keyword_tool（关键词工具 / 搜索词数据）| shop_overview（店铺总览）| other",
 "period_text": "统计周期原文，如 '最近7天' 'Last 30 days' '2026-10-01 ~ 2026-10-06'",
 "period_days": 统计周期天数（数字，看不出填 null）,
 "rows": [{"name": 商品名, "seller_sku": 卖家SKU, "item_id": 平台商品ID, "impressions": 曝光, "visitors": 访客数, "views": 浏览量,
           "add_to_cart": 加购人数或件数, "orders": 订单数, "units": 件数, "revenue": 销售额（泰铢）, "conversion": 转化率（百分数，如 2.5 表示 2.5%）}]}
rows 最多 100 条；店铺总览页没有按商品的数据时 rows 给空数组。
关键词工具 / 搜索词页面另外给 "keywords": [{"keyword": 关键词原文, "search_volume": 搜索量（数字，可以是 "1.2k"）, "bid": 建议出价（泰铢）}]，最多 200 条；没有就给空数组。"""

NUM_FIELDS = ("impressions", "visitors", "views", "add_to_cart", "orders", "units", "revenue", "conversion")


def _c():
    return mkt_db.conn()


def _n(v):
    if v in (None, "") or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    val, _ = parse_count(str(v).replace("%", ""))
    return val


def match_sku(seller_sku, skus, online=None, item_id=None):
    """卖家 SKU → ERP SKU：完全一样 > 产品编号 > 里面带 3DPxxxx-… > 在线商品（上架模块拉回来的）里同一个平台商品编号的卖家 SKU。"""
    s = (seller_sku or "").strip().upper()
    if not s:
        it = online.get(str(item_id or "").strip()) if online and item_id else None
        return it if it in skus else None
    if s in skus:
        return s
    for k, v in skus.items():
        if v.get("product_id") and str(v["product_id"]).upper() == s:
            return k
    m = re.search(r"[A-Z0-9]{2,6}\d{3,5}(?:-[A-Z0-9]+)+", s)
    if m and m.group(0) in skus:
        return m.group(0)
    it = online.get(str(item_id or "").strip()) if online and item_id else None
    return it if it in skus else None


def _online_map():
    """在线商品（上架模块拉回来的）：平台商品编号 → 卖家 SKU。"""
    from core import modules
    lst = modules.public("listing")
    out = {}
    if lst and hasattr(lst, "online_skus"):
        try:
            for sku, its in (lst.online_skus() or {}).items():
                for o in its:
                    if o.get("item_id"):
                        out.setdefault(str(o["item_id"]), sku)
        except Exception:  # noqa: BLE001
            pass
    return out


def capture_backend(cfg, body):
    url = (body.get("url") or "").strip()
    tables = (body.get("tables") or "")[:14000]
    text = (body.get("text") or "")[:max(2000, 16000 - len(tables))]
    if not (tables or text):
        raise ValueError("没收到页面内容")
    if not ai_on(cfg):
        raise AiError("后台页面要用 AI 识别：先到「设置 → AI」填接口密钥")
    host = re.sub(r"^https?://", "", url).split("/")[0]
    plat = "lazada" if "lazada" in host else "shopee" if "shopee" in host else "tiktok" if "tiktok" in host else ""
    r = ai_json(cfg, BACKEND_SYS, f"页面地址：{url}\n页面标题：{body.get('title') or ''}\n\n表格：\n{tables}\n\n页面文字：\n{text}")
    rows = [x for x in (r.get("rows") or [])[:100] if isinstance(x, dict) and (x.get("name") or x.get("seller_sku"))]
    c = _c()
    now = time.time()
    cur = c.execute("INSERT INTO ops_backend_pages(ts, platform, url, title, kind, period_text, n_rows, how) VALUES(?,?,?,?,?,?,?,?)",
                    (now, plat, url[:500], (body.get("title") or "")[:200], str(r.get("kind") or "other")[:30],
                     str(r.get("period_text") or "")[:60], len(rows), "ai"))
    pid = cur.lastrowid
    skus = sku_rows(cfg)
    online = _online_map()
    matched = 0
    for x in rows:
        sku = match_sku(x.get("seller_sku"), skus, online, x.get("item_id"))
        matched += 1 if sku else 0
        c.execute(f"""INSERT INTO ops_backend_rows(page_id, ts, platform, period_text, period_days, sku, seller_sku, item_id, name, {', '.join(NUM_FIELDS)})
                      VALUES(?,?,?,?,?,?,?,?,?,{','.join('?' * len(NUM_FIELDS))})""",
                  (pid, now, plat, str(r.get("period_text") or "")[:60], _n(r.get("period_days")), sku,
                   str(x.get("seller_sku") or "")[:60], str(x.get("item_id") or "")[:40], str(x.get("name") or "")[:200],
                   *[_n(x.get(k)) for k in NUM_FIELDS]))
    c.commit()
    kws = [x for x in (r.get("keywords") or [])[:200] if isinstance(x, dict) and x.get("keyword")]
    n_kw = 0
    if kws:
        from . import radar
        n_kw = radar.keyword_volumes(plat, kws, r.get("period_text") or "")
    return {"page_id": pid, "kind": r.get("kind"), "period_text": r.get("period_text"), "rows": len(rows), "matched": matched,
            "preview": [{k: x.get(k) for k in ("name", "seller_sku", "visitors", "orders", "conversion")} for x in rows[:5]], "keywords": n_kw}


def latest(limit=300):
    """每个商品（SKU 或商品名）× 平台最新的一条后台数据。"""
    rows = _c().execute("""SELECT r.* FROM ops_backend_rows r JOIN (
            SELECT COALESCE(sku, name) k, platform, MAX(ts) m FROM ops_backend_rows GROUP BY COALESCE(sku, name), platform) t
            ON COALESCE(r.sku, r.name)=t.k AND r.platform=t.platform AND r.ts=t.m ORDER BY r.ts DESC LIMIT ?""", (limit,)).fetchall()
    return [_derive(dict(r)) for r in rows]


def _derive(r):
    """补算：转化率没给时 = 订单 ÷ 访客；每天访客。"""
    if r.get("conversion") is None and r.get("orders") is not None and r.get("visitors"):
        r["conversion"] = round(r["orders"] / r["visitors"] * 100, 2)
    days = r.get("period_days") or None
    r["visitors_per_day"] = round(r["visitors"] / days, 1) if r.get("visitors") is not None and days else None
    return r


def get(sku, platform=None):
    q = "SELECT * FROM ops_backend_rows WHERE sku=?" + (" AND platform=?" if platform else "") + " ORDER BY ts DESC LIMIT 1"
    r = _c().execute(q, (sku, platform) if platform else (sku,)).fetchone()
    return _derive(dict(r)) if r else None


def by_sku():
    """{(SKU, 平台): 最新一条}（商品生命周期用）。"""
    out = {}
    for r in latest(2000):
        if r.get("sku"):
            out.setdefault((r["sku"], r["platform"]), r)
    return out


def pages(limit=30):
    return [dict(r) for r in _c().execute("SELECT * FROM ops_backend_pages ORDER BY ts DESC LIMIT ?", (limit,))]


def summary():
    """看板用：最近采集时间、对上 SKU 的商品数、访客最多 / 转化最低的几个。"""
    rows = latest(500)
    if not rows:
        return None
    mine = [r for r in rows if r.get("sku")]
    top = sorted([r for r in rows if r.get("visitors") is not None], key=lambda r: -(r["visitors"] or 0))[:5]
    low = sorted([r for r in rows if (r.get("visitors") or 0) >= 50 and r.get("conversion") is not None], key=lambda r: r["conversion"])[:5]
    keep = ("sku", "name", "platform", "period_text", "visitors", "orders", "conversion", "add_to_cart", "impressions")
    return {"last_ts": max(r["ts"] for r in rows), "n": len(rows), "matched": len(mine),
            "top": [{k: r.get(k) for k in keep} for r in top], "low_conv": [{k: r.get(k) for k in keep} for r in low]}
