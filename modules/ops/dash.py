"""运营看板（从运营分析系统 modules/sync/metrics.py 搬过来，改成直接读 ERP 的表）。

口径和财务模块一致：
  · 计入销售的订单 = 不是 取消 / 退货 / 未付款 / 报价 / 拒收（core.finance.EXCLUDE，和损益表、利润分析一样）
  · 每单利润用 core.finance.order_profit（财务模块、每单利润页、/api/v1 用的同一个函数）：有结算到账按真实扣费，没有按扣点估算（标「估」）
  · 按平台、按 SKU 的数优先直接用财务模块的 breakdown()；30 天净利润（含支出、固定费用、售后损失）用财务模块的 pl()
  · 日期按本机时间的自然日（和财务模块一样）
"""
import datetime as dt
import time

from core import db, store
from core.config import load_config


def day_start(days_ago=0):
    d = dt.datetime.combine(dt.date.today(), dt.time()) - dt.timedelta(days=days_ago)
    return d.timestamp()


def day_of(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _excl():
    from core.finance import EXCLUDE
    return EXCLUDE


def profits(since, until=None, cfg=None):
    """[(订单, 商品行, 利润拆分)]：since 之后下的、计入销售的订单。"""
    from core.finance import order_profit
    cfg = cfg or load_config()
    ex = _excl()
    c = db.conn()
    orders = c.execute(f"SELECT * FROM orders WHERE order_time>=? AND order_time<? AND status NOT IN ({','.join('?' * len(ex))})",
                       (since, until or time.time() + 86400, *ex)).fetchall()
    items = {}
    ids = [o["id"] for o in orders]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for it in c.execute(f"SELECT * FROM order_items WHERE order_id IN ({','.join('?' * len(chunk))})", chunk):
            items.setdefault(it["order_id"], []).append(it)
    return [(o, items.get(o["id"], []), order_profit(cfg, o, items.get(o["id"], []))) for o in orders]


def _sum(rows, since, until=None):
    until = until or time.time() + 86400
    s = {"n": 0, "revenue": 0.0, "fee": 0.0, "cost": 0.0, "profit": 0.0, "fee_estimated": 0}
    for o, _i, p in rows:
        if since <= (o["order_time"] or 0) < until:
            s["n"] += 1
            for k in ("revenue", "fee", "cost", "profit"):
                s[k] += p[k]
            s["fee_estimated"] += 1 if p["fee_estimated"] else 0
    s = {k: round(v, 2) if isinstance(v, float) else v for k, v in s.items()}
    s["margin"] = round(s["profit"] / s["revenue"] * 100, 1) if s["revenue"] else None
    s["aov"] = round(s["revenue"] / s["n"], 2) if s["n"] else None
    return s


def summary(rows):
    today, yday = day_start(0), day_start(1)
    return {"today": _sum(rows, today), "yesterday": _sum(rows, yday, today), "d7": _sum(rows, day_start(6)),
            "prev7": _sum(rows, day_start(13), day_start(6)), "d30": _sum(rows, day_start(29))}


def daily(rows, days=30):
    out = {day_of(day_start(i)): {"day": day_of(day_start(i)), "orders": 0, "revenue": 0.0, "profit": 0.0} for i in range(days)}
    for o, _i, p in rows:
        d = out.get(day_of(o["order_time"] or 0))
        if d:
            d["orders"] += 1
            d["revenue"] += p["revenue"]
            d["profit"] += p["profit"]
    return [{**v, "revenue": round(v["revenue"], 2), "profit": round(v["profit"], 2)} for v in sorted(out.values(), key=lambda x: x["day"])]


def _own_breakdown(rows, by):
    agg = {}
    for o, its, p in rows:
        if by == "platform":
            parts = [(o["platform"] or "其他", 1.0, sum((i["qty"] or 1) for i in its), "")]
        else:
            tot = sum((i["item_total"] or 0) for i in its)
            parts = [((i["sku"] or "?"), ((i["item_total"] or 0) / tot) if tot else 1 / max(1, len(its)), i["qty"] or 1, i["name"] or "")
                     for i in its]
        for k, share, qty, name in parts:
            a = agg.setdefault(k, {"key": k, "name": name, "orders": 0, "qty": 0, "revenue": 0.0, "fee": 0.0, "cost": 0.0, "profit": 0.0})
            a["orders"] += 1
            a["qty"] += qty
            for f in ("revenue", "fee", "cost", "profit"):
                a[f] += p[f] * share
    out = []
    for a in agg.values():
        a = {k: round(v, 2) if isinstance(v, float) else v for k, v in a.items()}
        a["margin"] = round(a["profit"] / a["revenue"] * 100, 1) if a["revenue"] else None
        out.append(a)
    return sorted(out, key=lambda x: -x["revenue"])


def breakdowns(rows):
    """按平台、按 SKU（30 天）。财务模块开着就用它的 breakdown（同一个口径，只是不再自己算一遍）。"""
    from core import modules
    fin = modules.public("fin")
    if fin:
        s, e = dt.date.today() - dt.timedelta(days=29), dt.date.today() + dt.timedelta(days=1)
        try:
            return fin.breakdown(s, e, "platform")["rows"], fin.breakdown(s, e, "sku")["rows"], "fin"
        except Exception:  # noqa: BLE001  财务模块出错：自己算（同一个利润函数）
            pass
    return _own_breakdown(rows, "platform"), _own_breakdown(rows, "sku"), "ops"


def fin_net_30d():
    """财务口径的 30 天净利润（扣了支出、固定费用、售后损失）。财务模块关着返回 None。"""
    from core import modules
    fin = modules.public("fin")
    if not fin:
        return None
    s, e = dt.date.today() - dt.timedelta(days=29), dt.date.today() + dt.timedelta(days=1)
    try:
        sm = fin.pl(s, e)["summary"]
    except Exception:  # noqa: BLE001
        return None
    return {k: sm.get(k) for k in ("revenue", "gross", "net", "net_margin", "opex", "fee_rate", "fee_estimated")}


def loss_orders(rows, limit=50):
    out = []
    for o, _i, p in rows:
        if p["profit"] < 0:
            out.append({"id": o["id"], "platform": o["platform"] or "", "order_no": o["order_no"], "order_time": o["order_time"],
                        "revenue": p["revenue"], "fee": p["fee"], "cost": p["cost"], "profit": p["profit"],
                        "fee_estimated": p["fee_estimated"], "fee_source": p["fee_source"], "missing_data": p["missing_data"]})
    return sorted(out, key=lambda x: x["profit"])[:limit]


def shipping(warn_hours=12):
    """待发货订单的发货时效 + 近 30 天发货准时率（有最晚发货时间和发货时间的订单）。"""
    now = time.time()
    c = db.conn()
    rows = [dict(r) for r in c.execute(
        "SELECT id, platform, order_no, order_time, ship_by, COALESCE(hold,0) hold FROM orders WHERE status='to_ship' ORDER BY ship_by")]
    overdue = [r for r in rows if r["ship_by"] and r["ship_by"] < now]
    soon = [r for r in rows if r["ship_by"] and now <= r["ship_by"] < now + warn_hours * 3600]
    for r in overdue + soon:
        r["hours_left"] = round((r["ship_by"] - now) / 3600, 1)
    done = c.execute("SELECT order_time, ship_by, shipped_at FROM orders WHERE shipped_at IS NOT NULL AND order_time>=?",
                     (day_start(29),)).fetchall()
    with_deadline = [r for r in done if r["ship_by"]]
    late = sum(1 for r in with_deadline if r["shipped_at"] > r["ship_by"])
    hours = [(r["shipped_at"] - r["order_time"]) / 3600 for r in done if r["order_time"] and r["shipped_at"] >= r["order_time"]]
    return {"to_ship": len(rows), "overdue": overdue[:50], "overdue_n": len(overdue), "soon": soon[:50], "soon_n": len(soon),
            "no_deadline": sum(1 for r in rows if not r["ship_by"]), "on_hold": sum(1 for r in rows if r["hold"]),
            "shipped_30d": len(done), "late_30d": late,
            "on_time_rate": round((len(with_deadline) - late) / len(with_deadline) * 100, 1) if with_deadline else None,
            "avg_ship_hours": round(sum(hours) / len(hours), 1) if hours else None}


def cod_stats(days=30):
    """货到付款拒收率 = 货到付款订单里「拒收 / 派送失败」的比例。"""
    c = db.conn()
    rows = c.execute("SELECT status, payment, cod FROM orders WHERE order_time>=?", (day_start(days - 1),)).fetchall()
    from core.orders import is_cod
    cod = [r for r in rows if is_cod(dict(r))]
    failed = sum(1 for r in cod if r["status"] == "delivery_failed")
    return {"cod_orders": len(cod), "cod_failed": failed, "cod_fail_rate": round(failed / len(cod) * 100, 1) if cod else None,
            "delivery_failed": sum(1 for r in rows if r["status"] == "delivery_failed"), "orders": len(rows)}


def aftersales(days=30):
    """售后损失（退款、补发、退回运费、罚款、报废）——和损益表「售后损失」同一个算法（core.extras.as_losses）。"""
    from core import extras
    since = day_start(days - 1)
    losses = extras.as_losses(since)
    n = db.conn().execute("SELECT COUNT(*) FROM aftersales WHERE created_at>=?", (since,)).fetchone()[0]
    return {"count": n, "loss": round(sum(a["loss"] for a in losses), 2)}


_floor_cache = {"at": 0, "rows": None, "key": None}


def price_rows(cfg=None):
    """每个 SKU 的 ERP 售价、最低价、成本（和产品页同一个定价函数）。看板、待办、生命周期都要用：
    产品文件和设置都没改过就用上次算好的。"""
    import os
    from core import pricing
    from core.config import CONFIG_PATH
    cfg = cfg or load_config()
    try:
        files = tuple(sorted((e.name, e.stat().st_mtime_ns) for e in os.scandir(store.PRODUCTS_DIR) if e.name.endswith(".json")))
    except OSError:
        files = ()
    try:
        cst = os.stat(CONFIG_PATH).st_mtime_ns
    except OSError:
        cst = None
    key = (store.PRODUCTS_DIR, files, cst)
    if _floor_cache["rows"] is not None and _floor_cache["key"] == key:
        return _floor_cache["rows"]
    out = []
    for it in store.list_products():
        try:
            p = store.load(it["id"])
            prices = pricing.price_product(cfg, p)
        except Exception:  # noqa: BLE001
            continue
        for v, pr in zip(p.get("variants") or [], prices):
            if not v.get("sku"):
                continue
            out.append({"sku": v["sku"].strip().upper(), "product_id": p["id"], "name": p.get("name_zh") or "",
                        "variant": " ".join(x for x in (v.get("opt1_zh"), v.get("opt2_zh")) if x),
                        "price": pr["final_price"], "floor_price": pr["floor_price"], "unit_cost": pr["cost"]["total"],
                        "grams": v.get("grams"), "hours": v.get("hours"), "draft": bool(p.get("draft")),
                        "active": p.get("active", True) is not False, "product": p})
    _floor_cache.update(at=time.time(), rows=out, key=key)
    return out


def pricing_issues(cfg=None):
    """售价低于最低价（最低加价率对应的价格）：ERP 里的售价，或者平台上实际在卖的价（在线商品，有促销价按促销价）。"""
    from core import modules
    lst = modules.public("listing")
    online = {}
    if lst and hasattr(lst, "online_skus"):
        try:
            online = lst.online_skus()
        except Exception:  # noqa: BLE001
            online = {}
    out = []
    for r in price_rows(cfg):
        if r["draft"] or not r["floor_price"]:
            continue
        plat = [(o["platform"], o["price"]) for o in online.get(r["sku"], []) if o.get("price") and o.get("status") == "live"]
        low_plat = [(pl, pr) for pl, pr in plat if pr < r["floor_price"] - 0.01]
        if r["price"] < r["floor_price"] - 0.01 or low_plat:
            out.append({"sku": r["sku"], "product_id": r["product_id"], "name": r["name"], "variant": r["variant"],
                        "price": r["price"], "floor_price": r["floor_price"], "unit_cost": r["unit_cost"],
                        "erp_low": r["price"] < r["floor_price"] - 0.01,
                        "platform_prices": [{"platform": pl, "price": pr} for pl, pr in low_plat]})
    return out


def data_health(rows, cfg=None):
    c = db.conn()
    since = day_start(29)
    pr = price_rows(cfg)
    fee_src = {}
    for _o, _i, p in rows:
        fee_src[p["fee_source"]] = fee_src.get(p["fee_source"], 0) + 1
    unknown = [r[0] for r in c.execute("SELECT DISTINCT i.sku FROM order_items i JOIN orders o ON o.id=i.order_id "
                                       "WHERE o.order_time>=? AND i.product_id IS NULL AND COALESCE(i.sku,'')!='' LIMIT 20", (since,))]
    return {"skus": len(pr), "skus_missing_cost": sum(1 for r in pr if not r["grams"] or not r["hours"]),
            "orders_missing_data": sum(1 for _o, _i, p in rows if p["missing_data"]),
            "orders_fee_estimated": sum(1 for _o, _i, p in rows if p["fee_estimated"]), "orders_30d": len(rows),
            "fee_source": fee_src, "unknown_skus": unknown}


def production():
    """生产排队和待打包（生产模块关着返回 None）。"""
    from core import modules
    if modules.is_loaded() and not modules.enabled("prod"):
        return None
    c = db.conn()
    try:
        q = c.execute("SELECT COUNT(*) n, SUM(qty-COALESCE(qty_done,0)) pcs, SUM((qty-COALESCE(qty_done,0))*COALESCE(hours_each,0)) h "
                      "FROM jobs WHERE status='todo'").fetchone()
        post = c.execute("SELECT COUNT(*) FROM jobs WHERE status='post'").fetchone()[0]
    except Exception:  # noqa: BLE001  还没有生产表
        return None
    cfg = load_config()
    try:
        cap = float(cfg.get("printer_count") or 0) * float(cfg.get("hours_per_day_each") or 0)
    except (TypeError, ValueError):
        cap = 0
    return {"queue_jobs": q["n"] or 0, "queue_pcs": q["pcs"] or 0, "queue_hours": round(q["h"] or 0, 1), "post": post,
            "capacity_hours_per_day": round(cap, 1) or None,
            "days_of_work": round((q["h"] or 0) / cap, 1) if cap else None}


def materials_low():
    from core import modules
    if modules.is_loaded() and not modules.enabled("prod"):
        return []
    try:
        from core import materials
        return [{"material": m["material"], "color": m["color"], "kg": m.get("kg"), "days_left": m.get("days_left"), "short": m.get("short")}
                for m in materials.plan()["rows"] if m.get("urgent") or m.get("short")][:20]
    except Exception:  # noqa: BLE001
        return []


def dashboard():
    cfg = load_config()
    rows = profits(day_start(29), cfg=cfg)
    plats, skus, src = breakdowns(rows)
    imgs = {r["sku"]: r["product_id"] for r in price_rows(cfg)}
    for s in skus:
        s["product_id"] = imgs.get(str(s.get("key") or "").upper())
    summ = summary(rows)
    af = aftersales(30)
    summ["d30"]["aftersales"] = af["loss"]
    summ["d30"]["profit_after_aftersales"] = round(summ["d30"]["profit"] - af["loss"], 2)
    from . import lazada
    try:
        warn_h = float(cfg.get("oa_ship_warn_hours") or 12)
    except (TypeError, ValueError):
        warn_h = 12
    return {"summary": summ, "daily": daily(rows), "platforms": plats, "skus": sorted(skus, key=lambda x: -x["profit"])[:20],
            "breakdown_source": src, "fin_net": fin_net_30d(), "loss_orders": loss_orders(rows), "shipping": shipping(warn_h),
            "cod": cod_stats(30), "aftersales": af, "pricing": pricing_issues(cfg)[:50], "health": data_health(rows, cfg),
            "production": production(), "materials": materials_low(), "lazada": lazada.summary(),
            "fee_rate_setting": cfg.get("platform_fee_rate"), "market": market_summary(cfg)}


def market_summary(cfg=None):
    """v2.48：看板上的「市场」卡片：卖家后台流量（访客最多 / 转化最低）、近 7 天竞品动态、计划进度、下一个大促。"""
    out = {}
    try:
        from . import campaigns, comp, plans, traffic
        out["traffic"] = traffic.summary()
        out["comp_events"] = comp.events(7, 8)
        ps = plans.listing(cfg, include_closed=False)
        out["plans"] = [{"id": p["id"], "sku": p["sku"], "platform": p["platform"], "kind_label": p["kind_label"], "kind_th": p["kind_th"],
                         "status": p["progress"]["status"], "status_label": p["progress"]["status_label"], "status_th": p["progress"]["status_th"],
                         "cum_actual": p["progress"]["cum_actual"], "cum_target": p["progress"]["cum_target"]} for p in ps]
        nxt = [e for e in campaigns.big_events(cfg, 30) if e["days_left"] >= 0]
        out["next_campaign"] = {k: nxt[0][k] for k in ("name", "name_th", "start", "days_left", "expected_orders", "over_capacity")} if nxt else None
    except Exception as e:  # noqa: BLE001  第二期的表出问题不影响看板
        out["error"] = str(e)[:200]
    return out
