"""每日利润（只有老板能看）。

每单利润 = 收入 − 平台费用 − 材料 − 机时（电费+房租人工折旧分摊）− 包材 − 失败损耗
每日利润 = 当天各订单利润之和 − 当天的其他支出（广告费、运费补贴、杂费等，在利润页手动记）
平台费用：导入的表格里有佣金/手续费就用真实数，没有就按设置里的扣点估算（标「估」）。
"""
import datetime as dt
import time

from . import db, pricing
from .config import load_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, kind TEXT, amount REAL, note TEXT, username TEXT, created_at REAL
);
CREATE INDEX IF NOT EXISTS expenses_day ON expenses(day);
"""
EXCLUDE = ("cancelled", "returned", "unpaid", "quote", "delivery_failed")


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()


def _day(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def order_profit(cfg, o, items):
    tpg = pricing.thb_per_gram(cfg) * (1 + cfg.get("material_loss_rate", 0))
    mh = pricing.machine_hour_cost(cfg)
    revenue = o["order_total"] if o["order_total"] is not None else sum((i["item_total"] or 0) for i in items)
    revenue = revenue or 0
    rate = cfg.get("shopee_fee_rate") if o["platform"] == "shopee" and cfg.get("shopee_fee_rate") else cfg.get("platform_fee_rate", 0)
    if o["platform"] in ("manual",):
        rate = 0
    keys0 = o.keys() if hasattr(o, "keys") else []
    g = (lambda k: o[k] if k in keys0 else None)
    parts = {k: g(k) for k in ("commission", "service_fee", "payment_fee")}
    fee_src = "estimate"
    if g("settlement") is not None and revenue:
        # 有结算金额（实际到账）：平台扣掉的 = 订单金额 − 到账（佣金、服务费、手续费、卖家优惠都在里面）
        fee, fee_src = revenue - g("settlement"), "settlement"
    elif any(v is not None for v in parts.values()):
        fee, fee_src = sum(abs(v or 0) for v in parts.values()) + abs(g("seller_discount") or 0), "detail"
    elif o["platform_fee"] is not None:
        fee, fee_src = abs(o["platform_fee"]), "import"
    else:
        fee = revenue * rate
    fee_est = fee_src == "estimate"
    grams = sum((i["grams"] or 0) * (i["qty"] or 1) for i in items)
    hours = sum((i["hours"] or 0) * (i["qty"] or 1) for i in items)
    from .fleet import is_resin
    keys = items[0].keys() if items else []
    resin_g = sum((i["grams"] or 0) * (i["qty"] or 1) for i in items if "material" in keys and is_resin(i["material"]))
    material = (grams - resin_g) * tpg + resin_g * pricing.thb_per_gram(cfg, "RESIN") * (1 + cfg.get("material_loss_rate", 0))
    machine = hours * mh
    # v2.40：「每件包材」按件数算（以前每单只算一次）
    packaging = (cfg.get("packaging_per_item", 0) or 0) * sum((i["qty"] or 1) for i in items) if items else 0
    failure = (material + machine) * cfg.get("failure_rate", 0)
    cost = material + machine + packaging + failure
    # v2.40：开了 VAT、价格含税 → 利润按不含税收入算（和损益表一致）
    vr = float(cfg.get("fin_vat_rate", 0.07) or 0)
    out_vat = revenue * vr / (1 + vr) if cfg.get("fin_vat_on") and cfg.get("fin_prices_incl_vat", True) else 0.0
    profit = revenue - out_vat - fee - cost
    missing = any(not i["product_id"] or not i["grams"] for i in items)
    return {"revenue": round(revenue, 2), "out_vat": round(out_vat, 2), "fee": round(fee, 2), "fee_estimated": fee_est, "fee_source": fee_src,
            "fee_detail": {k: v for k, v in {**parts, "seller_discount": g("seller_discount"),
                                              "platform_discount": g("platform_discount"),
                                              "settlement": g("settlement")}.items() if v is not None},
            "material": round(material, 2),
            "machine": round(machine, 2), "packaging": round(packaging, 2), "failure": round(failure, 2),
            "cost": round(cost, 2), "profit": round(profit, 2), "grams": round(grams, 1), "hours": round(hours, 2),
            "missing_data": missing}


def report(days=30):
    cfg = load_config()
    c = db.conn()
    since = time.time() - int(days) * 86400
    orders = c.execute(f"SELECT * FROM orders WHERE order_time>=? AND status NOT IN ({','.join('?' * len(EXCLUDE))})",
                       (since, *EXCLUDE)).fetchall()
    items = {}
    if orders:
        ids = [o["id"] for o in orders]
        for it in c.execute(f"SELECT * FROM order_items WHERE order_id IN ({','.join('?' * len(ids))})", ids):
            items.setdefault(it["order_id"], []).append(it)
    daily, by_sku, by_platform = {}, {}, {}
    total = {"orders": 0, "revenue": 0, "fee": 0, "cost": 0, "expenses": 0, "profit": 0}
    missing = 0
    for o in orders:
        its = items.get(o["id"], [])
        pr = order_profit(cfg, o, its)
        d = _day(o["order_time"])
        row = daily.setdefault(d, {"day": d, "orders": 0, "revenue": 0, "out_vat": 0, "fee": 0, "material": 0, "machine": 0,
                                   "packaging": 0, "failure": 0, "expenses": 0, "profit": 0})
        row["orders"] += 1
        for k in ("revenue", "out_vat", "fee", "material", "machine", "packaging", "failure", "profit"):     # v2.40：含 VAT，行能对上账
            row[k] += pr[k]
        missing += pr["missing_data"]
        plat = by_platform.setdefault(o["platform"] or "其他", {"platform": o["platform"] or "其他", "orders": 0, "revenue": 0, "profit": 0})
        plat["orders"] += 1; plat["revenue"] += pr["revenue"]; plat["profit"] += pr["profit"]
        # 按 SKU 分摊（按商品金额比例）
        tot_items = sum((i["item_total"] or 0) for i in its) or 1
        for i in its:
            share = (i["item_total"] or 0) / tot_items if tot_items else 1 / max(1, len(its))
            s = by_sku.setdefault(i["sku"] or "?", {"sku": i["sku"] or "?", "name": i["name"] or "", "qty": 0, "revenue": 0, "profit": 0})
            s["qty"] += i["qty"] or 1
            s["revenue"] += pr["revenue"] * share
            s["profit"] += pr["profit"] * share
        total["orders"] += 1; total["revenue"] += pr["revenue"]; total["fee"] += pr["fee"]
        total["cost"] += pr["cost"]; total["profit"] += pr["profit"]
    # 售后损失（退款、补发成本、退回运费、罚款、报废），按登记日期算到当天
    total["aftersales"] = 0
    from . import extras
    for a in extras.as_losses(since):
        d = _day(a["created_at"])
        row = daily.setdefault(d, {"day": d, "orders": 0, "revenue": 0, "out_vat": 0, "fee": 0, "material": 0, "machine": 0,
                                   "packaging": 0, "failure": 0, "expenses": 0, "profit": 0})
        row["aftersales"] = row.get("aftersales", 0) + a["loss"]
        row["profit"] -= a["loss"]
        total["aftersales"] += a["loss"]
        total["profit"] -= a["loss"]
    for e in c.execute("SELECT day, SUM(amount) AS a FROM expenses WHERE day>=? AND COALESCE(deleted,0)=0 "
                       "AND COALESCE(direction,'out')='out' GROUP BY day", (_day(since),)):
        row = daily.setdefault(e["day"], {"day": e["day"], "orders": 0, "revenue": 0, "fee": 0, "material": 0, "machine": 0,
                                          "packaging": 0, "failure": 0, "expenses": 0, "profit": 0})
        row["expenses"] += e["a"] or 0
        row["profit"] -= e["a"] or 0
        total["expenses"] += e["a"] or 0
        total["profit"] -= e["a"] or 0
    rnd = lambda d: {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}
    return {"days": [rnd(r) for r in sorted(daily.values(), key=lambda r: r["day"], reverse=True)],
            "skus": [rnd(r) for r in sorted(by_sku.values(), key=lambda r: -r["profit"])],
            "platforms": [rnd(r) for r in by_platform.values()],
            "total": rnd(total), "missing_data_orders": missing,
            "margin": round(total["profit"] / total["revenue"] * 100, 1) if total["revenue"] else None}


def _fin():
    from . import modules
    m = modules.public("fin")
    if not m:
        raise ValueError("「财务」模块没有打开（设置 → 模块管理）")
    return m


def add_expense(day, kind, amount, note="", user=""):
    """（旧接口）记一笔支出：v2.21 起在财务模块里（v2.30 起 modules/fin）。"""
    fin = _fin()
    return fin.save_expense({"day": day, "category": kind, "amount": amount, "note": note}, user)


def list_expenses(days=60):
    fin = _fin()
    since = _day(time.time() - int(days) * 86400)
    return [dict(r, kind=r["category"]) for r in fin.expenses(start=since, direction="out")]


def delete_expense(eid, user=""):
    fin = _fin()
    fin.delete_expense(eid, user)
