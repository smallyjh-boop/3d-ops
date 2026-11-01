"""库存页的几种看法（v2.32，按 ERP 同行的做法把「库存」和「物品资料」分开）。

  stock    库存（默认）：有库存、有在途、或者入过库后低于补货线的物品。从没入过库的不出现在这里
  all      物品资料：所有启用的物品（包括没入过库的），在这里建档、改资料
  zero     没有库存的物品（从没入过库 / 用完了）
  inactive 已停用的物品
低于补货线的提醒只算「入过库的」物品（刚建档、还没买过的不提醒）。
"""
from core import db
from core import inventory as inv
from core.inventory import ledger, units

VIEWS = ("stock", "all", "zero", "inactive")


def _stocked_ids():
    return {r[0] for r in db.conn().execute("SELECT DISTINCT item_id FROM inv_moves")}


def is_low(it, stocked):
    """入过库、并且低于补货线（耗材按补货线的单位：按卷的数卷，按公斤 / 克的比重量，见 core/inventory/units.py）。"""
    return it["id"] in stocked and it.get("reorder_point") is not None and units.below(it)


def _split(ids=None):
    """v2.53：每个物品放在哪些货位：{物品id: [{code, qty, ztype, zone}]}（拣货区在前、按走路顺序）。
    v2.55：ids = 只查这些物品（分页时用）；耗材每个货位另外带 rolls（几卷）、grams、text_zh / text_th
    （「A1-01-01：1 卷 · 1.0 kg」「PR2-01-01（打印机上）：1 卷 · 973 g」）。"""
    from . import locations as L, wms
    c = db.conn()
    out = {}
    try:
        if ids is not None:
            if not ids:
                return {}
            ids = list(ids)
            rows = c.execute(f"SELECT q.item_id, q.loc_id, q.qty, l.code, l.zone, COALESCE(NULLIF(g.ztype,''),'pick') ztype FROM inv_loc_qty q JOIN inv_locations l ON l.id=q.loc_id "
                             f"LEFT JOIN inv_loc_groups g ON g.code=l.zone AND g.kind='zone' WHERE q.qty>1e-9 AND q.item_id IN ({','.join('?' * len(ids))})", ids).fetchall()
            rows = [{"item_id": r["item_id"], "loc_id": r["loc_id"], "qty": r["qty"], "code": r["code"], "zone": r["zone"], "ztype": r["ztype"]} for r in rows]
            locs = None
        else:
            locs = wms._locs(c, active=False)
            rows = wms._qty_rows(c)
    except Exception:  # noqa: BLE001  货位表还没建
        return {}
    # 耗材：只有请求的物品里有耗材才查料卷货位（分页时每页最多几十个物品）
    item_ids = {r["item_id"] for r in rows}
    fil = {}
    try:
        q = "SELECT id, material, color FROM inv_items WHERE category='filament'"
        if ids is not None:
            q += f" AND id IN ({','.join('?' * len(ids))})"
            fil = {r["id"]: (r["material"], r["color"]) for r in c.execute(q, ids)}
        else:
            fil = {r["id"]: (r["material"], r["color"]) for r in c.execute(q)}
    except Exception:  # noqa: BLE001
        fil = {}
    lstat = units.loc_stats(c) if any(i in fil for i in item_ids) else {}
    for r in rows:
        if locs is not None:
            l = locs.get(r["loc_id"])
            if not l:
                continue
            code, zone, ztype = l["code"], l["zone"], l["ztype"]
        else:
            code, zone, ztype = r["code"], r["zone"], r["ztype"]
        x = {"code": code, "qty": round(r["qty"], 6), "ztype": ztype, "zone": zone, "loc_id": r["loc_id"]}
        k = fil.get(r["item_id"])
        if k:
            st = (lstat.get(k) or {}).get(r["loc_id"]) or {"rolls": 0, "grams": r["qty"]}
            x["rolls"], x["grams"] = st["rolls"], round(st["grams"], 1)
            zh, th = units.loc_text(k[0], st["rolls"], st["grams"])
            on = ztype == "production"
            x["text_zh"] = f"{code}{'（打印机上）' if on else ''}：{zh}"
            x["text_th"] = f"{code}{' (บนเครื่องพิมพ์)' if on else ''}: {th}"
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


# ---------------- v2.55：服务端分页 / 筛选 / 排序 / 搜索（1 万+ 物品也快）----------------
ITEM_SORTS = {"code": "i.code", "name": "COALESCE(NULLIF(i.name_zh,''), i.name_th), i.code", "category": "i.category, i.code", "qty": "i.qty",
              "reorder": "i.reorder_point", "cost": "i.avg_cost", "value": "(i.qty*COALESCE(i.avg_cost,0))", "loc": "i.location, i.code",
              "locs": "COALESCE(p.n,0)"}
MONEY_SORTS = ("cost", "value")
_PLACED = "LEFT JOIN (SELECT item_id, SUM(qty) s, COUNT(*) n FROM inv_loc_qty WHERE qty>1e-9 GROUP BY item_id) p ON p.item_id=i.id"
_STOCKED = "LEFT JOIN (SELECT DISTINCT item_id FROM inv_moves) st ON st.item_id=i.id"


def _like(s):
    return "%" + str(s).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _has_sql(tr_ids):
    return "(ABS(i.qty)>1e-9" + (f" OR i.id IN ({','.join('?' * len(tr_ids))})" if tr_ids else "") + ")", list(tr_ids)


def listing_page(view="stock", category="", q="", zone="", loc="", sort="", desc=False, page=1, size=50):
    """listing 的分页版：{items, total, page, pages, size}。条件和 listing 一样，只是在数据库里筛、排、分页，每页再补分布 / 货位。"""
    from . import qtytext
    from .locviews import _split_order
    view = view if view in VIEWS else "stock"
    c = db.conn()
    trm = inv.in_transit()
    tr_ids = [k for k, v in trm.items() if (v or 0) > 0]
    has, has_args = _has_sql(tr_ids)
    low = "(i.reorder_point IS NOT NULL AND i.qty<=i.reorder_point AND st.item_id IS NOT NULL)"
    w, args = [("i.active=0" if view == "inactive" else "i.active=1")], []
    if category:
        w.append("i.category=?")
        args.append(category)
    q = str(q or "").strip()
    if q:
        w.append("(i.code LIKE ? ESCAPE '\\' OR i.name_zh LIKE ? ESCAPE '\\' OR i.name_th LIKE ? ESCAPE '\\' OR i.brand LIKE ? ESCAPE '\\' OR i.spec LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 5
    if view == "stock":
        w.append(f"({has} OR {low})")
        args += has_args
    elif view == "zero":
        w.append(f"NOT {has}")
        args += has_args
    zone = str(zone or "")
    zjoin = "JOIN inv_locations l ON l.id=qq.loc_id"
    if zone.startswith("t:"):
        w.append(f"i.id IN (SELECT qq.item_id FROM inv_loc_qty qq {zjoin} LEFT JOIN inv_loc_groups g ON g.code=l.zone AND g.kind='zone' "
                 "WHERE qq.qty>1e-9 AND COALESCE(NULLIF(g.ztype,''),'pick')=?)")
        args.append(zone[2:])
    elif zone.startswith("z:"):
        w.append(f"i.id IN (SELECT qq.item_id FROM inv_loc_qty qq {zjoin} WHERE qq.qty>1e-9 AND l.zone=?)")
        args.append(zone[2:])
    elif zone == "unplaced":
        w.append(f"((i.qty-COALESCE(p.s,0)>1e-9 AND (COALESCE(p.n,0)>0 OR COALESCE(i.location,'')<>'')) OR ({has} AND COALESCE(p.n,0)=0))")
        args += has_args
    loc = str(loc or "").strip().upper()
    if loc:
        w.append(f"i.id IN (SELECT qq.item_id FROM inv_loc_qty qq {zjoin} WHERE qq.qty>1e-9 AND l.code LIKE ?)")
        args.append(loc + "%")
    where = " AND ".join(w)
    frm = f"FROM inv_items i {_PLACED} {_STOCKED}"
    total = c.execute(f"SELECT COUNT(*) {frm} WHERE {where}", args).fetchone()[0]
    size = size if size in (50, 100, 200) else 50
    pages = max(1, -(-total // size))
    page = max(1, min(int(page or 1), pages))
    order = ITEM_SORTS.get(sort) or "i.category, i.code"
    if desc and sort in ITEM_SORTS:
        order = ", ".join(f"{p.strip()} DESC" for p in _split_order(order))
    rows = c.execute(f"SELECT i.* {frm} WHERE {where} ORDER BY {order}, i.id LIMIT ? OFFSET ?", args + [size, (page - 1) * size]).fetchall()
    ids = [r["id"] for r in rows]
    stocked = {r[0] for r in c.execute(f"SELECT DISTINCT item_id FROM inv_moves WHERE item_id IN ({','.join('?' * len(ids))})", ids)} if ids else set()
    split = _split(ids)
    items = [ledger.item_row(r) for r in rows]
    for it in items:
        it["transit"] = trm.get(it["id"], 0)
    units.decorate(items, c)                      # 耗材：units（几卷）、按补货线单位重算 low、补货线文字
    qc = qtytext.Ctx(c)
    out = []
    for it in items:
        where_ = split.get(it["id"], [])
        placed = sum(x["qty"] for x in where_)
        it["stocked"] = it["id"] in stocked
        it["loc_n"] = len(where_)
        it["locs"] = where_
        it["unplaced"] = round(max(0.0, (it.get("qty") or 0) - placed), 6) if where_ or it.get("location") else 0
        if it.get("units"):                       # 还没上架的是几卷
            it["unplaced_rolls"] = max(0, it["units"]["rolls"] - sum(x.get("rolls", 0) for x in where_))
        it["low"] = is_low(it, stocked)
        it.update(qtytext.both(it.get("qty") or 0, it.get("unit") or "", it, qc))
        for x in where_:
            x.update(qtytext.both(x["qty"], it.get("unit") or "", it, qc, x["loc_id"]))
        out.append(it)
    return {"items": out, "total": total, "page": page, "pages": pages, "size": size}


def counts_sql():
    """counts 的数据库版：每个分类 stock / all / zero / low / value。"""
    c = db.conn()
    tr_ids = [k for k, v in inv.in_transit().items() if (v or 0) > 0]
    has, has_args = _has_sql(tr_ids)
    low = "(i.reorder_point IS NOT NULL AND i.qty<=i.reorder_point AND st.item_id IS NOT NULL)"
    out = {}
    for r in c.execute(f"SELECT i.category, COUNT(*) n, SUM(CASE WHEN {has} OR {low} THEN 1 ELSE 0 END) stock, SUM(CASE WHEN {low} THEN 1 ELSE 0 END) low, "
                       f"COALESCE(SUM(i.qty*COALESCE(i.avg_cost,0)),0) value FROM inv_items i {_STOCKED} WHERE i.active=1 GROUP BY i.category", has_args):
        out[r["category"]] = {"stock": r["stock"], "all": r["n"], "zero": r["n"] - r["stock"], "low": r["low"], "value": round(r["value"], 2)}
    # 补货线按「卷」的耗材：用真实卷数比（SQL 只比克数），少数几个物品单独校正
    rr = [ledger.item_row(r) for r in c.execute("SELECT i.*, (st.item_id IS NOT NULL) stocked FROM inv_items i " + _STOCKED +
                                                 " WHERE i.active=1 AND i.reorder_unit='roll' AND i.reorder_point IS NOT NULL")] if _has_col(c, "reorder_unit") else []
    if rr:
        units.decorate(rr, c)
        for it in rr:
            sql_low = bool(it["stocked"] and (it.get("qty") or 0) <= (it.get("reorder_point") or 0))
            real = bool(it["stocked"] and units.below(it))
            has_ = abs(it.get("qty") or 0) > 1e-9 or it["id"] in tr_ids
            o = out[it["category"]]
            if sql_low != real:
                o["low"] += 1 if real else -1
                if not has_:
                    o["stock"] += 1 if real else -1
                    o["zero"] -= 1 if real else -1
    return out


def _has_col(c, col):
    return any(r[1] == col for r in c.execute("PRAGMA table_info(inv_items)"))
