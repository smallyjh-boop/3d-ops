"""库存页的几种看法（v2.32，按 ERP 同行的做法把「库存」和「物品资料」分开）。

  stock    库存（默认）：有库存、有在途、或者入过库后低于补货线的物品。从没入过库的不出现在这里
  all      物品资料：所有启用的物品（包括没入过库的），在这里建档、改资料
  zero     没有库存的物品（从没入过库 / 用完了）
  inactive 已停用的物品
低于补货线的提醒只算「入过库的」物品（刚建档、还没买过的不提醒）。
"""
from core import db
from core import inventory as inv
from core.inventory import units

VIEWS = ("stock", "all", "zero", "inactive")


def _stocked_ids():
    return {r[0] for r in db.conn().execute("SELECT DISTINCT item_id FROM inv_moves")}


def is_low(it, stocked):
    """入过库、并且低于补货线（耗材按补货线的单位：按卷的数卷，按公斤 / 克的比重量，见 core/inventory/units.py）。"""
    return it["id"] in stocked and it.get("reorder_point") is not None and units.below(it)


def _split():
    """v2.53：每个物品放在哪些货位：{物品id: [{code, qty, ztype, zone}]}（拣货区在前、按走路顺序）。
    v2.55：耗材每个货位另外带 rolls（几卷）、grams、text_zh / text_th（「A1-01-01：1 卷 · 1.0 kg」「PR2-01-01（打印机上）：1 卷 · 973 g」）。"""
    from . import locations as L, wms
    c = db.conn()
    try:
        locs = wms._locs(c, active=False)
        rows = wms._qty_rows(c)
    except Exception:  # noqa: BLE001  货位表还没建
        return {}
    lstat = units.loc_stats(c)
    fil = {r["id"]: (r["material"], r["color"]) for r in c.execute("SELECT id, material, color FROM inv_items WHERE category='filament'")}
    out = {}
    for r in rows:
        l = locs.get(r["loc_id"])
        if l:
            x = {"code": l["code"], "qty": round(r["qty"], 6), "ztype": l["ztype"], "zone": l["zone"]}
            k = fil.get(r["item_id"])
            if k:
                st = (lstat.get(k) or {}).get(r["loc_id"]) or {"rolls": 0, "grams": r["qty"]}
                x["rolls"], x["grams"] = st["rolls"], round(st["grams"], 1)
                zh, th = units.loc_text(k[0], st["rolls"], st["grams"])
                on = l["ztype"] == "production"
                x["text_zh"] = f"{l['code']}{'（打印机上）' if on else ''}：{zh}"
                x["text_th"] = f"{l['code']}{' (บนเครื่องพิมพ์)' if on else ''}: {th}"
            out.setdefault(r["item_id"], []).append(x)
    for v in out.values():
        v.sort(key=lambda x: (0 if x["ztype"] == "pick" else 1, L.sort_key(x["code"])))
    return out


def zone_options():
    """库存页「区」筛选：[{value, ztype, zone, name}]（区类型 + 每个区）"""
    from . import wms
    try:
        zs, _wn, _d = wms.zinfo()
        have = {r[0] for r in db.conn().execute("SELECT DISTINCT zone FROM inv_locations WHERE active=1")}
    except Exception:  # noqa: BLE001
        return []
    types = sorted({(zs.get(z) or {}).get("ztype", "pick") for z in have}, key=lambda t: list(wms.ZTYPES).index(t) if t in wms.ZTYPES else 99)
    return ([{"value": "t:" + t, "ztype": t} for t in types] +
            [{"value": "z:" + z, "zone": z, "ztype": (zs.get(z) or {}).get("ztype", "pick"), "name": (zs.get(z) or {}).get("name", "")}
             for z in sorted(have)])


def listing(view="stock", category="", q="", zone="", loc=""):
    """zone（v2.53）：t:区类型 / z:区字母 / unplaced 待上架；loc：货位编号开头（A1、A1-02 …）"""
    view = view if view in VIEWS else "stock"
    rows = inv.items(category, q, False, view == "inactive")
    stocked = _stocked_ids()
    split = _split()
    loc = str(loc or "").strip().upper()
    out = []
    for it in rows:
        where = split.get(it["id"], [])
        placed = sum(x["qty"] for x in where)
        it["stocked"] = it["id"] in stocked
        it["loc_n"] = len(where)
        it["locs"] = where
        it["unplaced"] = round(max(0.0, (it.get("qty") or 0) - placed), 6) if where or it.get("location") else 0
        if it.get("units"):                       # v2.55：还没上架的是几卷
            it["unplaced_rolls"] = max(0, it["units"]["rolls"] - sum(x.get("rolls", 0) for x in where))
        it["low"] = is_low(it, stocked)
        has = abs(it.get("qty") or 0) > 1e-9 or (it.get("transit") or 0) > 0
        if view == "inactive" and it.get("active"):
            continue
        if view == "stock" and not (has or it["low"]):
            continue
        if view == "zero" and has:
            continue
        if zone == "unplaced" and it["unplaced"] <= 1e-9 and not (has and not where):
            continue
        if zone.startswith("t:") and not any(x["ztype"] == zone[2:] for x in where):
            continue
        if zone.startswith("z:") and not any(x["zone"] == zone[2:] for x in where):
            continue
        if loc and not any(x["code"].startswith(loc) for x in where):
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
