"""采购分析（v2.51）：花了多少钱（按月 / 分类 / 供应商，按到货的到手成本算）、付款按月、耗材每公斤价格走势、每个物品最便宜的供应商。"""
import datetime as dt
import time

from core import db
from core.inventory import ledger

from . import links as _links


def _month_keys(n=12):
    d = dt.date.today().replace(day=1)
    out = []
    for _ in range(n):
        out.append(d.strftime("%Y-%m"))
        d = (d - dt.timedelta(days=1)).replace(day=1)
    return list(reversed(out))


def overview(months=12):
    _links.ensure()
    c = db.conn()
    keys = _month_keys(months)
    start = dt.datetime.strptime(keys[0] + "-01", "%Y-%m-%d").timestamp()
    rows = c.execute("SELECT m.ts, m.qty, m.amount, i.category, i.id item_id, i.code, i.name_zh, i.name_th, i.material, d.ref "
                     "FROM inv_moves m JOIN inv_items i ON i.id=m.item_id LEFT JOIN inv_docs d ON d.id=m.doc_id "
                     "WHERE m.kind='purchase' AND m.ts>=?", (start,)).fetchall()
    po_sup = {r["no"]: (r["sid"], r["sname"]) for r in c.execute(
        "SELECT p.no, s.id sid, s.name sname FROM inv_po p LEFT JOIN inv_suppliers s ON s.id=p.supplier_id")}
    by_month = {k: 0.0 for k in keys}
    by_cat, by_sup = {}, {}
    fil = {k: [0.0, 0.0] for k in keys}                 # 每月耗材 [金额, 克]
    fil_mat = {}
    for r in rows:
        mk = time.strftime("%Y-%m", time.localtime(r["ts"]))
        amt = float(r["amount"] or 0)
        if mk in by_month:
            by_month[mk] += amt
        by_cat[r["category"]] = by_cat.get(r["category"], 0.0) + amt
        ref = r["ref"] or ""
        sid, sname = po_sup.get(ref[3:], (None, None)) if ref.startswith("po:") else (None, None)
        key = sid or 0
        g = by_sup.setdefault(key, {"id": sid, "name": sname or "", "amount": 0.0})
        g["amount"] += amt
        if r["category"] == "filament" and mk in fil:
            fil[mk][0] += amt
            fil[mk][1] += float(r["qty"] or 0)
            fm = fil_mat.setdefault(r["material"] or "?", [0.0, 0.0])
            fm[0] += amt
            fm[1] += float(r["qty"] or 0)
    pay = {k: 0.0 for k in keys}
    for r in c.execute("SELECT substr(day,1,7) m, SUM(amount) a FROM inv_payments WHERE day>=? GROUP BY m", (keys[0] + "-01",)):
        if r["m"] in pay:
            pay[r["m"]] = float(r["a"] or 0)
    cats = {k: v for k, v in ledger.CATEGORIES.items()}
    out = {
        "months": [{"month": k, "spend": round(by_month[k], 2), "paid": round(pay[k], 2)} for k in keys],
        "by_category": sorted([{"key": k, "zh": (cats.get(k) or (k,))[0], "th": (cats.get(k) or (k, k))[1], "spend": round(v, 2)}
                               for k, v in by_cat.items() if abs(v) > 0.005], key=lambda x: -x["spend"]),
        "by_supplier": sorted([{"id": g["id"], "name": g["name"], "spend": round(g["amount"], 2)} for g in by_sup.values()
                               if abs(g["amount"]) > 0.005], key=lambda x: -x["spend"])[:12],
        "filament_kg": [{"month": k, "thb_kg": round(v[0] / v[1] * 1000, 1) if v[1] > 0 else None, "kg": round(v[1] / 1000, 1)}
                        for k, v in fil.items()],
        "filament_by_material": sorted([{"material": k, "thb_kg": round(v[0] / v[1] * 1000, 1), "kg": round(v[1] / 1000, 1)}
                                        for k, v in fil_mat.items() if v[1] > 0], key=lambda x: -x["kg"]),
        "cheapest": cheapest(),
    }
    out["total_12m"] = round(sum(by_month.values()), 2)
    return out


def cheapest(limit=40):
    """有两个以上供应商（有价格）的物品：每个供应商的到手单价（泰铢），最便宜的是哪个、首选的贵多少。"""
    c = db.conn()
    last = {}
    for r in c.execute("SELECT item_id, supplier_id, landed, ts FROM pur_prices WHERE supplier_id IS NOT NULL AND landed>0 ORDER BY ts, id"):
        last[(r["item_id"], r["supplier_id"])] = r["landed"]
    al = _links.all_links()
    out = []
    for iid, ls in al.items():
        opts = []
        for x in ls:
            v = last.get((iid, x["supplier_id"]))
            v = v if v is not None else x.get("price_thb")
            if v:
                opts.append({"supplier_id": x["supplier_id"], "name": (x.get("supplier") or {}).get("name") or "", "landed": round(v, 4),
                             "preferred": x["preferred"]})
        if len(opts) < 2:
            continue
        opts.sort(key=lambda o: o["landed"])
        it = c.execute("SELECT code, name_zh, name_th, unit, category FROM inv_items WHERE id=?", (iid,)).fetchone()
        if not it:
            continue
        pref = next((o for o in opts if o["preferred"]), None)
        out.append({"item_id": iid, "code": it["code"], "name_zh": it["name_zh"], "name_th": it["name_th"], "unit": it["unit"],
                    "category": it["category"], "options": opts, "best": opts[0],
                    "saving_pct": round((pref["landed"] - opts[0]["landed"]) / pref["landed"] * 100, 1) if pref and pref["landed"] else None})
    out.sort(key=lambda x: -(x["saving_pct"] or 0))
    return out[:limit]
