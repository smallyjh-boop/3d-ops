"""补货建议（v2.51，按真实用量算）。

每个物品：
  每天用量   耗材 = 近 30 天出库（打印扣料、损耗、领用……）÷ 30；另外还没打的生产任务要用的克数（一次性的需求）
            包材 = 近 30 天出库 ÷ 30 × 订单量变化（近 7 天每天订单 ÷ 近 30 天每天订单，0.5~2 倍），
                   和「发货扣包材规则」× 每天订单 / 件数，取大的
            其他 = 近 30 天出库 ÷ 30
  可用      = 库存 + 在途 − 生产任务要用的
  还能用几天 = 可用 ÷ 每天用量
  到货天数   = 首选供应商这个物品写的 → 供应商写的 → 耗材用「耗材从下单到收货几天」→ 设置里的默认
  该买多少   = 每天用量 × (到货天数 + 安全天数 + 一次买够几天) + 生产任务要用的 − 库存 − 在途；
              低于补货线的至少补「每次补多少」；再按起订量、包装数（耗材按整卷）往上取整
  紧急程度   red 红 = 现在下单也来不及（还能用的天数 < 到货天数，或者已经不够生产任务）
            yellow 黄 = 该下单了（还能用的天数 < 到货天数 + 安全天数，或者低于补货线）
            green 绿 = 不急
"""
import datetime as dt
import math
import time

from core import db, inventory as inv
from core.config import load_config
from core.inventory import purchase as _kp

from . import links as _links

OUT_KINDS = ("production", "loss", "fail", "issue", "scrap", "pack", "ship", "sale")      # 盘点调整不算用量


def _num(cfg, k, d):
    try:
        v = cfg.get(k)
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def params(cfg=None):
    cfg = cfg or load_config()
    return {"safety_days": _num(cfg, "pur_safety_days", 5), "cover_days": _num(cfg, "pur_cover_days", 30),
            "lead_days": _num(cfg, "pur_default_lead_days", 7), "filament_lead_days": _num(cfg, "filament_lead_days", 10),
            "spool_g": _num(cfg, "filament_spool_kg", 1.0) * 1000 or 1000}


def _usage(c, days):
    now = time.time()
    out = {}
    for r in c.execute(f"SELECT item_id, SUM(-qty) q FROM inv_moves WHERE ts>=? AND qty<0 AND kind IN ({','.join('?' * len(OUT_KINDS))}) "
                       "GROUP BY item_id", (now - days * 86400, *OUT_KINDS)):
        out[r["item_id"]] = max(0.0, r["q"] or 0)
    return out


def _orders(c):
    """(近 30 天每天订单数, 近 7 天每天订单数, 近 30 天每天件数)。"""
    now = time.time()
    try:
        o30 = c.execute("SELECT COUNT(*) FROM orders WHERE order_time>=? AND status NOT IN ('cancelled','unpaid','quote')",
                        (now - 30 * 86400,)).fetchone()[0]
        o7 = c.execute("SELECT COUNT(*) FROM orders WHERE order_time>=? AND status NOT IN ('cancelled','unpaid','quote')",
                       (now - 7 * 86400,)).fetchone()[0]
        i30 = c.execute("SELECT COALESCE(SUM(i.qty),0) FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.order_time>=? "
                        "AND o.status NOT IN ('cancelled','unpaid','quote')", (now - 30 * 86400,)).fetchone()[0]
    except Exception:  # noqa: BLE001  没有订单表
        return 0.0, 0.0, 0.0
    return o30 / 30.0, o7 / 7.0, (i30 or 0) / 30.0


def _pending():
    """还没打的生产任务要用多少耗材：{(材料, 颜色): 克}。"""
    try:
        from core import materials
        d, _ = materials._job_demand()
        return {k: v * 1000.0 for k, v in d.items()}
    except Exception:  # noqa: BLE001
        return {}


def round_qty(need, link, is_fil, spool_g):
    """按起订量、包装数取整。耗材：按整卷（每卷克数看供应商写的，没写用设置的），起订量按卷。返回 (数量, 卷数, 每卷克数)。"""
    link = link or {}
    if need <= 0:
        return 0.0, None, None
    if is_fil:
        net = float(link.get("net_g") or spool_g or 1000)
        rolls = max(1, math.ceil(need / net - 1e-9))
        if link.get("moq"):
            rolls = max(rolls, int(math.ceil(float(link["moq"]))))
        if link.get("pack_qty"):              # 一箱几卷
            p = float(link["pack_qty"])
            rolls = int(math.ceil(rolls / p - 1e-9) * p)
        return rolls * net, rolls, net
    q = need
    if link.get("moq"):
        q = max(q, float(link["moq"]))
    if link.get("pack_qty"):
        p = float(link["pack_qty"])
        q = math.ceil(q / p - 1e-9) * p
    else:
        q = math.ceil(q - 1e-9)
    return float(q), None, None


def compute(include_all=False):
    """补货建议列表（红 → 黄 → 绿，同级按还能用的天数）。include_all：没有建议的物品（有用量的）也列出来。"""
    _links.ensure()
    cfg = load_config()
    p = params(cfg)
    c = db.conn()
    tr = inv.in_transit()
    links = _links.all_links()
    sups = {r["id"]: dict(r) for r in c.execute("SELECT * FROM inv_suppliers")}
    u30, u7 = _usage(c, 30), _usage(c, 7)
    pend = _pending()
    od30, od7, items_day = _orders(c)
    trend = min(2.0, max(0.5, od7 / od30)) if od30 > 0 and od7 > 0 else 1.0
    rules = {}
    for r in inv.pack_rules(cfg):
        rules[r["item_id"]] = rules.get(r["item_id"], 0) + r["qty"] * (items_day if r["per"] == "item" else od30)
    today = dt.date.today()
    stocked = {r[0] for r in c.execute("SELECT DISTINCT item_id FROM inv_moves")}
    rows = []
    for r in c.execute("SELECT * FROM inv_items WHERE active=1 AND category!='goods'"):
        it = dict(r)
        iid = it["id"]
        is_fil = it["category"] == "filament"
        qty = float(it["qty"] or 0)
        transit = float(tr.get(iid, 0) or 0)
        pending = pend.get(((it.get("material") or "").upper(), it.get("color") or ""), 0.0) if is_fil else 0.0
        use30 = u30.get(iid, 0.0)
        rate = use30 / 30.0
        why = []
        if it["category"] == "pack":
            r_mv = rate * trend
            r_rule = rules.get(iid, 0.0)
            rate = max(r_mv, r_rule)
            if rate > 0:
                why.append("orders")
        elif rate > 0:
            why.append("usage")
        if pending > 0:
            why.append("production")
        ls = links.get(iid) or []
        link = next((x for x in ls if x["supplier_id"] == it.get("supplier_id")), None) or (ls[0] if ls else None)
        sid = (link or {}).get("supplier_id") or it.get("supplier_id")
        sup = sups.get(sid) if sid else None
        lead = (link or {}).get("lead_days")
        if lead is None and sup and sup.get("lead_days") is not None:
            lead = sup["lead_days"]
        if lead is None:
            lead = p["filament_lead_days"] if is_fil else p["lead_days"]
        lead = float(lead)
        avail = qty + transit - pending
        days = (avail / rate) if rate > 0 else (None if avail >= 0 else 0.0)
        target = rate * (lead + p["safety_days"] + p["cover_days"]) + pending
        need = max(0.0, target - qty - transit)
        below = it.get("reorder_point") is not None and qty + transit <= float(it["reorder_point"])
        if below:
            why.append("reorder")
            rq = it.get("reorder_qty") or max(float(it["reorder_point"]) * 2 - qty - transit, 1)
            need = max(need, float(rq))
        if avail < -1e-9:
            why.append("short")
            need = max(need, -avail)
        if avail < -1e-9 or (days is not None and rate > 0 and days < lead):
            urgency = "red"
        elif (days is not None and rate > 0 and days < lead + p["safety_days"]) or below:
            urgency = "yellow"
        else:
            urgency = "green"
        if urgency == "green":
            need = 0.0 if not include_all else need
        sq, rolls, net = round_qty(need, link, is_fil, p["spool_g"])
        if not include_all and urgency == "green":
            continue
        if not include_all and iid not in stocked and transit <= 0 and pending <= 0:
            continue          # 建了档、从来没入过库的物品（常用物品清单）不在默认列表里刷屏，看「全部」
        if not include_all and sq <= 0:
            continue
        if include_all and sq <= 0 and rate <= 0 and not below:
            continue
        cur = (link or {}).get("currency") or (sup or {}).get("currency") or "THB"
        price = (link or {}).get("price")
        fx = _kp.default_fx() if cur == "CNY" else 1.0
        if price is None:
            unit_thb = float(it.get("avg_cost") or 0)
            price = unit_thb / fx if unit_thb else None
        unit_price = price                     # 和物品的单位一样（耗材是每克）
        order_by = None
        if days is not None and rate > 0:
            order_by = (today + dt.timedelta(days=max(0, int(math.floor(days - lead - p["safety_days"]))))).isoformat()
        rows.append({
            "item": {k: it.get(k) for k in ("id", "code", "name_zh", "name_th", "category", "unit", "material", "color", "qty",
                                            "reorder_point", "reorder_qty", "supplier_id", "avg_cost")},
            "transit": round(transit, 3), "pending": round(pending, 1), "use30": round(use30, 3), "daily": round(rate, 4),
            "available": round(avail, 3), "days": None if days is None else round(days, 1), "lead": lead,
            "safety": p["safety_days"], "order_by": order_by, "urgency": urgency, "why": why,
            "need": round(need, 3), "qty": round(sq, 3), "rolls": rolls, "net_g": net,
            "supplier_id": sid, "supplier": (sup or {}).get("name") if sup else None, "currency": cur,
            "link": {k: link.get(k) for k in ("id", "urls", "platforms", "moq", "pack_qty", "net_g", "price", "currency")} if link else None,
            "unit_price": None if unit_price is None else round(unit_price, 6),
            "est_cost": None if unit_price is None else round(sq * unit_price * fx, 2),
        })
    order = {"red": 0, "yellow": 1, "green": 2}
    rows.sort(key=lambda x: (order[x["urgency"]], x["days"] if x["days"] is not None else 1e9, x["item"]["code"]))
    return {"rows": rows, "params": p, "trend": round(trend, 2), "orders_per_day": round(od30, 2)}


def create_pos(sel, user=""):
    """选中的建议 → 采购单草稿，按供应商分开（每个供应商一张；没设供应商的放一张）。
    sel：[{item_id, qty?（按物品单位；耗材按克）, rolls?, supplier_id?}]，不给数量就用建议的数量。"""
    rows = {r["item"]["id"]: r for r in compute(include_all=True)["rows"]}
    c = db.conn()
    p = params()
    groups = {}
    for s in sel or []:
        try:
            iid = int(s.get("item_id"))
        except (TypeError, ValueError):
            continue
        r = rows.get(iid)
        it = inv.get_item(iid)
        if not it:
            continue
        sid = s.get("supplier_id") or (r or {}).get("supplier_id") or it.get("supplier_id")
        sid = int(sid) if sid not in (None, "") else None
        link = c.execute("SELECT * FROM pur_item_sup WHERE item_id=? AND supplier_id=?", (iid, sid)).fetchone() if sid else None
        is_fil = it["category"] == "filament"
        net = float((link["net_g"] if link else None) or (r or {}).get("net_g") or p["spool_g"])
        if s.get("rolls") not in (None, ""):
            rolls = int(s["rolls"])
            q = rolls * net
        elif s.get("qty") not in (None, ""):
            q = float(s["qty"])
            rolls = int(math.ceil(q / net - 1e-9)) if is_fil else None
        else:
            q = float((r or {}).get("qty") or 0)
            rolls = (r or {}).get("rolls")
        if q <= 0:
            continue
        sup = c.execute("SELECT * FROM inv_suppliers WHERE id=?", (sid,)).fetchone() if sid else None
        cur = (link["currency"] if link and link["currency"] else None) or (sup["currency"] if sup else None) or "THB"
        price = link["price"] if link and link["price"] is not None else None
        fx = _kp.default_fx()
        if price is None and it.get("avg_cost"):
            price = it["avg_cost"] / (fx if cur == "CNY" else 1)       # 到手成本折回下单货币（耗材是每克）
        ln = {"item_id": iid, "qty": q, "unit_cost": price}
        if is_fil:
            ln.update(rolls=rolls or int(math.ceil(q / net)), net_g=net)
        g = groups.setdefault((sid, cur), {"lines": [], "lead": 0})
        g["lines"].append(ln)
        g["lead"] = max(g["lead"], float((r or {}).get("lead") or p["lead_days"]))
    out = []
    for (sid, cur), g in groups.items():
        exp = (dt.date.today() + dt.timedelta(days=int(math.ceil(g["lead"])))).isoformat()
        out.append(inv.save_po({"supplier_id": sid, "currency": cur, "lines": g["lines"], "expected_date": exp,
                                "note": "按补货建议生成", "source": "suggest"}, user))
    return out
