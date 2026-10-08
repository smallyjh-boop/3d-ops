"""财务 → 订单明细（v2.32）：每一单一行——收入拆分、平台费用拆分、到账、生产成本、利润、回款状态。

口径和损益表一样：按下单日期，不含取消 / 退款 / 未付款 / 报价单。
回款状态：settled 已回款（导入过结算表，有到账金额）/ overdue 超时未回款（已发货或已完成超过设置的天数）/ pending 待回款。
费用来源：settlement 结算表（实际到账反推）/ detail 订单表里的费用明细 / import 订单表里的平台费 / estimate 按扣点估算。
"""
import datetime as dt
import io
import time

from core import db
from core.config import load_config
from .common import period, r2, settings, ts

SETTLE_ZH = {"settled": "已回款", "pending": "待回款", "overdue": "超时未回款"}
FEE_SRC_ZH = {"settlement": "结算表", "detail": "费用明细", "import": "导入的平台费", "estimate": "按扣点估算", "none": "无平台费（手工单）"}
PLAT_ZH = {"lazada": "Lazada", "shopee": "Shopee", "tiktok": "TikTok", "manual": "手工单", "other": "其他"}
MONEY = ("order_total", "shipping_fee", "buyer_shipping", "platform_discount", "seller_discount", "commission", "service_fee",
         "payment_fee", "platform_fee", "settlement")


def _settle_state(o, st, now):
    if o["settlement"] is not None:
        return "settled"
    shipped = o["shipped_at"] if "shipped_at" in o.keys() else None
    if o["status"] in ("shipped", "completed") and (shipped or o["order_time"] or now) < now - st["settle_days"] * 86400:
        return "overdue"
    return "pending"


def rows(start=None, end=None, month=None, platform="", shop="", settle="", q=""):
    """返回 {period, rows: [...], total: {...}, counts: {settled, pending, overdue}}。"""
    from core.finance import EXCLUDE, order_profit
    if start is None:
        start, end, label = period(month)
    else:
        label = f"{start.isoformat()} ~ {(end - dt.timedelta(days=1)).isoformat()}"
    cfg = load_config()
    st = settings(cfg)
    c = db.conn()
    sql = (f"SELECT * FROM orders WHERE order_time>=? AND order_time<? AND status NOT IN ({','.join('?' * len(EXCLUDE))})")
    args = [ts(start), ts(end), *EXCLUDE]
    if platform:
        sql += " AND platform=?"; args.append(platform)
    if shop:
        sql += " AND shop=?"; args.append(shop)
    if q:
        sql += " AND (order_no LIKE ? OR tracking_no LIKE ? OR buyer LIKE ?)"; args += [f"%{q}%"] * 3
    orders = c.execute(sql + " ORDER BY order_time DESC", args).fetchall()
    items = {}
    ids = [o["id"] for o in orders]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for it in c.execute(f"SELECT * FROM order_items WHERE order_id IN ({','.join('?' * len(chunk))})", chunk):
            items.setdefault(it["order_id"], []).append(it)
    now = time.time()
    out, counts = [], {"settled": 0, "pending": 0, "overdue": 0}
    tot = {k: 0.0 for k in ("revenue", "fee", "net", "material", "machine", "packaging", "failure", "cost", "profit")}
    for o in orders:
        its = items.get(o["id"], [])
        p = order_profit(cfg, o, its)
        s = _settle_state(o, st, now)
        counts[s] += 1
        if settle and s != settle:
            continue
        net = o["settlement"] if o["settlement"] is not None else p["revenue"] - p["fee"]
        row = {"id": o["id"], "order_no": o["order_no"], "platform": o["platform"], "shop": o["shop"] or "", "status": o["status"],
               "order_time": o["order_time"], "items": sum((i["qty"] or 0) for i in its),
               "skus": ", ".join(f"{i['sku']}×{i['qty']}" for i in its if i["sku"])[:200],
               **{k: (r2(o[k]) if o[k] is not None else None) for k in MONEY if k in o.keys()},
               "revenue": r2(p["revenue"]), "fee": r2(p["fee"]), "fee_source": "none" if o["platform"] == "manual" and not p["fee"] else (p.get("fee_source") or ("estimate" if p.get("fee_estimated") else "")),
               "net": r2(net), "net_estimated": o["settlement"] is None,
               "material": r2(p["material"]), "machine": r2(p["machine"]), "packaging": r2(p["packaging"]), "failure": r2(p["failure"]),
               "cost": r2(p["cost"]), "profit": r2(p["profit"]),
               "margin": round(p["profit"] / p["revenue"] * 100, 1) if p["revenue"] else None,
               "grams": r2(p.get("grams")), "hours": r2(p.get("hours")), "missing_data": bool(p.get("missing_data")), "settle": s}
        out.append(row)
        for k in tot:
            tot[k] += row[k] or 0
    tot = {k: r2(v) for k, v in tot.items()}
    tot["orders"] = len(out)
    tot["margin"] = round(tot["profit"] / tot["revenue"] * 100, 1) if tot["revenue"] else None
    return {"period": label, "rows": out, "total": tot, "counts": counts, "settle_days": st["settle_days"],
            "settle_zh": SETTLE_ZH, "fee_src_zh": FEE_SRC_ZH}


COLS = [("order_no", "订单号"), ("platform", "平台"), ("shop", "店铺"), ("order_time", "下单时间"), ("status", "订单状态"), ("skus", "商品"),
        ("order_total", "订单金额"), ("buyer_shipping", "买家运费"), ("platform_discount", "平台优惠"), ("seller_discount", "店铺优惠"),
        ("commission", "佣金"), ("service_fee", "服务费"), ("payment_fee", "支付手续费"), ("fee", "平台扣费合计"), ("fee_source", "扣费来源"),
        ("settlement", "实际到账"), ("net", "到账（没结算的为估算）"), ("material", "材料"), ("machine", "机时（电费+分摊）"),
        ("packaging", "包材"), ("failure", "失败损耗"), ("cost", "生产成本"), ("profit", "利润"), ("margin", "利润率 %"), ("settle", "回款状态")]


def export_xlsx(**kw):
    import openpyxl
    from openpyxl.styles import Font
    d = rows(**kw)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "订单明细"
    ws.append([z for _k, z in COLS])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for r in d["rows"]:
        line = []
        for k, _z in COLS:
            v = r.get(k)
            if k == "order_time" and v:
                v = dt.datetime.fromtimestamp(v).strftime("%Y-%m-%d %H:%M")
            elif k == "fee_source":
                v = FEE_SRC_ZH.get(v, v)
            elif k == "platform":
                v = PLAT_ZH.get(v, v)
            elif k == "status":
                from core.orders import STATUS_ZH
                v = STATUS_ZH.get(v, v)
            elif k == "settle":
                v = SETTLE_ZH.get(v, v)
            line.append(v)
        ws.append(line)
    t = d["total"]
    ws.append(["合计", "", "", "", "", f"{t['orders']} 单"] + [""] * 7 + [t["fee"], "", "", t["net"], t["material"], t["machine"],
              t["packaging"], t["failure"], t["cost"], t["profit"], t["margin"], ""])
    for col, w in zip("ABCDEFG", (22, 9, 14, 17, 10, 36, 11)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf, d["period"]
