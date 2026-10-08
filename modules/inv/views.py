"""库存页的几种看法（v2.32，按 ERP 同行的做法把「库存」和「物品资料」分开）。

  stock    库存（默认）：有库存、有在途、或者入过库后低于补货线的物品。从没入过库的不出现在这里
  all      物品资料：所有启用的物品（包括没入过库的），在这里建档、改资料
  zero     没有库存的物品（从没入过库 / 用完了）
  inactive 已停用的物品
低于补货线的提醒只算「入过库的」物品（刚建档、还没买过的不提醒）。
"""
from core import db
from core import inventory as inv

VIEWS = ("stock", "all", "zero", "inactive")


def _stocked_ids():
    return {r[0] for r in db.conn().execute("SELECT DISTINCT item_id FROM inv_moves")}


def is_low(it, stocked):
    return it.get("reorder_point") is not None and (it.get("qty") or 0) <= it["reorder_point"] and it["id"] in stocked


def listing(view="stock", category="", q=""):
    view = view if view in VIEWS else "stock"
    rows = inv.items(category, q, False, view == "inactive")
    stocked = _stocked_ids()
    out = []
    for it in rows:
        it["stocked"] = it["id"] in stocked
        it["low"] = is_low(it, stocked)
        has = abs(it.get("qty") or 0) > 1e-9 or (it.get("transit") or 0) > 0
        if view == "inactive" and it.get("active"):
            continue
        if view == "stock" and not (has or it["low"]):
            continue
        if view == "zero" and has:
            continue
        out.append(it)
    return out


def counts():
    """每个分类：库存里有几样、物品资料一共几样、没库存的几样、入过库后低于补货线的几样、库存金额。"""
    stocked = _stocked_ids()
    out = {}
    for it in inv.items("", "", False, False):
        c = out.setdefault(it["category"], {"stock": 0, "all": 0, "zero": 0, "low": 0, "value": 0.0})
        has = abs(it.get("qty") or 0) > 1e-9 or (it.get("transit") or 0) > 0
        low = is_low(it, stocked)
        c["all"] += 1
        c["stock" if (has or low) else "zero"] += 1
        c["low"] += 1 if low else 0
        c["value"] += it.get("value") or 0
    return out


def alerts():
    stocked = _stocked_ids()
    return [a for a in inv.alerts() if a["item_id"] in stocked]


def box_stats():
    """纸箱页（v2.35）：每种邮政标准纸箱——有没有建档、库存、最近 30 天 / 本月用了多少、平均每天、还够几天、补货线。"""
    import datetime as dt
    import time
    from core.inventory import boxes
    c = db.conn()
    now = time.time()
    month0 = dt.datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    out = []
    for b in boxes.catalog():
        it = c.execute("SELECT * FROM inv_items WHERE code=?", (b["item_code"],)).fetchone()
        row = {**b, "item": None, "used30": 0, "used_month": 0, "daily": 0, "days_left": None}
        if it:
            used30 = -(c.execute("SELECT COALESCE(SUM(qty),0) FROM inv_moves WHERE item_id=? AND qty<0 AND kind IN ('pack','issue') AND ts>=?",
                                 (it["id"], now - 30 * 86400)).fetchone()[0] or 0)
            used_m = -(c.execute("SELECT COALESCE(SUM(qty),0) FROM inv_moves WHERE item_id=? AND qty<0 AND kind IN ('pack','issue') AND ts>=?",
                                 (it["id"], month0)).fetchone()[0] or 0)
            daily = used30 / 30.0
            row.update(item={"id": it["id"], "qty": it["qty"] or 0, "reorder_point": it["reorder_point"], "location": it["location"] or "",
                             "active": it["active"]},
                       used30=used30, used_month=used_m, daily=round(daily, 2),
                       days_left=(max(0, round((it["qty"] or 0) / daily)) if daily > 0 else None))
        out.append(row)
    return out
