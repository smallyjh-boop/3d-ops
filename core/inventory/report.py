"""库存统计：支出（出库、损耗按金额，按分类 / 类型 / 物品 / 打印机 / 月份）、低于补货线提醒、总览。"""
import datetime as dt

from .. import db
from . import ledger


def expense(start=None, end=None, group="category"):
    """支出 = 计入支出的流水（生产消耗、损耗、失败、领用、报废、盘亏）的金额。盘盈算负支出。"""
    kinds = [k for k, v in ledger.KINDS.items() if v[1]]
    now = ledger._now()
    start = float(start) if start else now - 30 * 86400
    end = float(end) if end else now + 1
    rows = db.conn().execute(
        f"SELECT m.*, i.category, i.code, i.name_zh, i.name_th, i.unit FROM inv_moves m JOIN inv_items i ON i.id=m.item_id "
        f"WHERE m.ts>=? AND m.ts<? AND m.kind IN ({','.join('?' * len(kinds))})", (start, end, *kinds)).fetchall()
    out = {}
    total = 0.0
    for r in rows:
        if group == "kind":
            k, zh = r["kind"], ledger.KINDS[r["kind"]][0]
        elif group == "item":
            k, zh = r["code"], r["name_zh"]
        elif group == "printer":
            k = zh = r["printer"] or "-"
        elif group == "month":
            k = zh = dt.datetime.fromtimestamp(r["ts"]).strftime("%Y-%m")
        else:
            cat = ledger.CATEGORIES.get(r["category"])
            k, zh = r["category"], cat[0] if cat else r["category"]
        g = out.setdefault(k, {"key": k, "label": zh, "amount": 0.0, "qty": 0.0, "unit": r["unit"] if group == "item" else "",
                               "label_th": (r["name_th"] if group == "item" else (ledger.CATEGORIES.get(r["category"], ("", zh))[1]
                                                                                    if group == "category" else ""))})
        amt = -float(r["amount"] or 0)
        g["amount"] += amt
        g["qty"] += -float(r["qty"] or 0)
        total += amt
    items = sorted(out.values(), key=lambda x: -x["amount"])
    for x in items:
        x["amount"] = round(x["amount"], 2)
        x["qty"] = round(x["qty"], 1)
    return {"start": start, "end": end, "group": group, "rows": items, "total": round(total, 2)}


def alerts():
    out = []
    for r in db.conn().execute("SELECT * FROM inv_items WHERE active=1 AND reorder_point IS NOT NULL AND qty<=reorder_point ORDER BY category, code"):
        it = ledger.item_row(r)
        out.append({"item_id": it["id"], "code": it["code"], "name_zh": it["name_zh"], "name_th": it["name_th"], "qty": it["qty"],
                    "unit": it["unit"], "reorder_point": it["reorder_point"]})
    return out


def overview():
    out = {}
    for r in db.conn().execute("SELECT category, COUNT(*) n, SUM(qty*avg_cost) v, SUM(CASE WHEN reorder_point IS NOT NULL AND qty<=reorder_point "
                               "THEN 1 ELSE 0 END) low FROM inv_items WHERE active=1 GROUP BY category"):
        out[r["category"]] = {"items": r["n"], "value": round(r["v"] or 0, 2), "low": r["low"] or 0}
    return out
