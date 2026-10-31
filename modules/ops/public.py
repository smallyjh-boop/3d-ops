"""运营分析模块给别的模块用的（modules.public("ops")，模块关着时拿到 None）。"""


def dashboard():
    """运营看板的全部数字（和 /api/oa/dashboard 一样）。"""
    from . import dash
    return dash.dashboard()


def lifecycle():
    """商品生命周期：{rows:[{sku, platform, stage, stage_label, action, qty_30d, …}], counts, rules}。"""
    from . import lifecycle as lc
    return lc.board()


def lazada_fee_rates(days=30):
    """Lazada 真实扣点（财务流水算出来的）：{item_amount, deducted, rate(%), fees:[…]}。"""
    from . import lazada
    return lazada.fee_rates(days)


def notify(text):
    """发一条手机提醒（LINE / Telegram，按运营分析的设置）。返回 (成功?, 错误)。"""
    from . import alerts
    return alerts.send(text)


def market_keywords():
    """爆款雷达的关键词和机会分（v2.50 选品模块：候选卡片上显示泰国市场的需求 / 竞争 / 价格）：
    [{id, keyword, platform, score, daily_top10, total_results, price_median, ip_risk, status, comps}]，comps = 竞品标题里有这个词的条数。"""
    from core.config import load_config
    from . import mkt_db, radar
    mkt_db.ensure()
    cfg = load_config()
    c = mkt_db.conn()
    titles = [str(r["title"] or "").lower() for r in c.execute("SELECT title FROM ops_comp WHERE status='active'")]
    out = []
    for k in c.execute("SELECT * FROM ops_radar_keywords ORDER BY id DESC LIMIT 500").fetchall():
        k = dict(k)
        o = radar.opportunity(cfg, k)
        kw = (k["keyword"] or "").lower()
        out.append({"id": k["id"], "keyword": k["keyword"], "platform": k["platform"], "score": o["score"], "daily_top10": o["daily_top10"],
                    "total_results": o["total_results"], "price_median": o["price_median"], "ip_risk": o["ip_risk"], "status": k["status"],
                    "ai": o.get("ai") or {}, "comps": sum(1 for t in titles if kw and kw in t)})
    return out


def market_keyword(kid):
    """一个雷达关键词（选品「去模型站找」用）：{id, keyword, platform, ai, …}，没有返回 None。"""
    from . import mkt_db, radar
    mkt_db.ensure()
    return radar.keyword(kid)
