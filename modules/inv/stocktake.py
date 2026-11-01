"""按货位盘点（v2.52）：按区 / 货架 / 货位开盘点单，手机一个货位一个货位数，差异汇总，确认后调整库存。

  用的还是库存的盘点单（inv_docs kind=stocktake，ref = "area:A1"）：单子上每个物品一行（账面 = 物品总数）。
  每个货位数到的数记在 inv_loc_count（单号, 货位, 物品）；哪些货位数完了记在 inv_loc_count_locs。
  物品这一行的实盘数 = 现在的总数 − 数过的货位上现在的数 + 数过的货位上数到的数（没数的货位、待上架照原样）。
  确认：库存按「实盘 − 账面」调整（盘点单原来的逻辑），数过的货位上的数改成数到的数。
"""
import json

from core import db
from core import inventory as inv
from core.inventory import units

from . import locations as L
from . import flows, wms


def is_loc_doc(doc_id, c=None):
    c = c or db.conn()
    return bool(c.execute("SELECT 1 FROM inv_loc_count_locs WHERE doc_id=? LIMIT 1", (int(doc_id),)).fetchone())


def start(area, user="", note="", category=""):
    """开一张按货位盘点的单：area 是区 / 货架 / 货位（或几个货位用逗号分开）。"""
    c = db.conn()
    parts = [x.strip() for x in str(area or "").replace("，", ",").split(",") if x.strip()]
    if not parts:
        raise ValueError("选要盘点的区、货架或货位")
    codes = []
    for p in parts:
        codes += [x for x in L.area_codes(p) if x not in codes]
    locs = [L.get_loc(x) for x in codes]
    pairs = []
    for l in locs:
        ids = {r["item_id"] for r in wms._qty_rows(c, loc_id=l["id"])}
        ids |= {r[0] for r in c.execute("SELECT id FROM inv_items WHERE active=1 AND location=?", (l["code"],))}
        if l.get("fixed_item"):
            ids.add(int(l["fixed_item"]))
        for iid in ids:
            it = wms._item(c, iid)
            if it and it["active"] and (not category or it["category"] == category):
                pairs.append((l, iid))       # v2.55：按料卷管的耗材也在货位盘点里：数这个货位上有几卷，或者一卷一卷称重
    item_ids = sorted({iid for _l, iid in pairs})
    label = ",".join(L.norm_code(p) for p in parts)
    d = inv.stocktake_start(category or "", user, note, label, item_ids=item_ids, allow_empty=True)
    for l in locs:
        c.execute("INSERT OR IGNORE INTO inv_loc_count_locs(doc_id, loc_id, code, done) VALUES(?,?,?,0)", (d["id"], l["id"], l["code"]))
    for l, iid in pairs:
        c.execute("INSERT OR IGNORE INTO inv_loc_count(doc_id, loc_id, item_id, expected, counted) VALUES(?,?,?,?,NULL)",
                  (d["id"], l["id"], iid, wms.loc_qty(c, iid, l["id"])))
    c.commit()
    return summary(d["id"])


def _doc(c, doc_id):
    d = c.execute("SELECT * FROM inv_docs WHERE id=?", (int(doc_id),)).fetchone()
    if not d or d["kind"] != "stocktake":
        raise ValueError("没有这张盘点单")
    return d


def count(doc_id, code, counts, user="", complete=True):
    """数完一个货位：counts {物品id 或 物品编码: 数量}。complete = 这个货位上没写到的物品算 0（扫完一个货位就是这样）。"""
    c = db.conn()
    d = _doc(c, doc_id)
    if d["status"] != "draft":
        raise ValueError("这张盘点单已经确认了")
    loc = L.get_loc(code)
    if not loc:
        raise ValueError(f"没有货位 {code}")
    if not c.execute("SELECT 1 FROM inv_loc_count_locs WHERE doc_id=? AND loc_id=?", (d["id"], loc["id"])).fetchone():
        raise ValueError(f"{loc['code']} 不在这张盘点单的范围里")
    got, extras = {}, {}
    lst = units.loc_stats(c)
    for k, v in (counts or {}).items():
        r = c.execute("SELECT * FROM inv_items WHERE id=? OR UPPER(code)=UPPER(?)", (int(k) if str(k).isdigit() else -1, str(k))).fetchone()
        if not r:
            raise ValueError(f"没有物品 {k}")
        if not isinstance(v, dict) and flows.spool_item(c, r["id"]):
            raise ValueError(f"{r['code']} 是按卷管的耗材：要数卷数或者称重，不能直接填克数")
        if isinstance(v, dict):                  # v2.55：耗材数卷 {rolls: n} / 称重 {weigh: [{code, gross}]}
            here = (lst.get((r["material"], r["color"])) or {}).get(loc["id"]) or {"rolls": 0, "grams": 0.0, "loaded": 0, "shelf": 0}
            q, ex = inv.resolve_count(dict(r), v, wms.loc_qty(c, r["id"], loc["id"]), here["shelf"])     # 账面卷数 = 架子上的（在机上的拿不走，不算）
            if q is None:
                continue
            got[r["id"]] = q
            if ex:
                extras[r["id"]] = ex
            continue
        try:
            q = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"数量「{v}」要填数字")
        if q != q or q < 0 or q == float("inf"):
            raise ValueError(f"数量「{v}」要填 0 或正数")
        got[r["id"]] = q
    for iid, q in got.items():
        c.execute("INSERT INTO inv_loc_count(doc_id, loc_id, item_id, expected, counted) VALUES(?,?,?,?,?) "
                  "ON CONFLICT(doc_id, loc_id, item_id) DO UPDATE SET counted=excluded.counted",
                  (d["id"], loc["id"], iid, wms.loc_qty(c, iid, loc["id"]), q))
        if not c.execute("SELECT 1 FROM inv_doc_lines WHERE doc_id=? AND item_id=?", (d["id"], iid)).fetchone():
            it = wms._item(c, iid)                 # 盘到了单子上没有的物品（放错货位的）：加一行
            c.execute("INSERT INTO inv_doc_lines(doc_id, item_id, expected) VALUES(?,?,?)", (d["id"], iid, it["qty"] or 0))
    for iid, ex in extras.items():               # 这一行是怎么数的（卷数 / 称重）记在盘点单行上，确认时按这个改料卷
        ln = c.execute("SELECT id, extra FROM inv_doc_lines WHERE doc_id=? AND item_id=?", (d["id"], iid)).fetchone()
        old = json.loads(ln["extra"]) if ln and ln["extra"] else {}
        if old.get("mode") != ex["mode"]:
            old = {}
        if ex["mode"] == "rolls":
            by = old.get("by_loc") or {}
            by[str(loc["id"])] = [ex["rolls"], ex["sys_rolls"]]
            ex = {"mode": "rolls", "by_loc": by, "delta_rolls": sum(a - b for a, b in by.values())}
        else:
            sp = {e["code"]: e for e in old.get("spools") or []}
            sp.update({e["code"]: e for e in ex["spools"]})
            ex = {"mode": "weigh", "spools": list(sp.values())}
        c.execute("UPDATE inv_doc_lines SET extra=? WHERE id=?", (json.dumps(ex), ln["id"]))
    if complete:
        for r in c.execute("SELECT item_id FROM inv_loc_count WHERE doc_id=? AND loc_id=? AND counted IS NULL", (d["id"], loc["id"])).fetchall():
            if not flows.spool_item(c, r["item_id"]):          # 按卷管的耗材没数 = 没盘，不算 0（算 0 会把这个货位上的料卷全扣掉）
                c.execute("UPDATE inv_loc_count SET counted=0 WHERE doc_id=? AND loc_id=? AND item_id=?", (d["id"], loc["id"], r["item_id"]))
    c.execute("UPDATE inv_loc_count_locs SET done=1, counted_by=?, counted_at=? WHERE doc_id=? AND loc_id=?",
              (user, wms._now(), d["id"], loc["id"]))
    _sync_lines(c, d["id"])
    c.commit()
    return summary(d["id"])


def _sync_lines(c, doc_id):
    """把货位上数到的数算成物品这一行的实盘数。"""
    per = {}
    for r in c.execute("SELECT loc_id, item_id, counted FROM inv_loc_count WHERE doc_id=? AND counted IS NOT NULL", (doc_id,)):
        per.setdefault(r["item_id"], []).append((r["loc_id"], r["counted"]))
    for iid, rows in per.items():
        it = wms._item(c, iid)
        tot = float(it["qty"] or 0) - sum(wms.loc_qty(c, iid, lid) for lid, _q in rows) + sum(q for _l, q in rows)
        c.execute("UPDATE inv_doc_lines SET counted=? WHERE doc_id=? AND item_id=?", (round(max(0.0, tot), 6), doc_id, iid))


def summary(doc_id):
    """盘点单 + 每个货位：数没数、每个物品 账面（现在这个货位上的数）/ 实盘 / 差异。"""
    c = db.conn()
    d = inv.doc(doc_id)
    if not d:
        raise ValueError("没有这张盘点单")
    items = {r["id"]: r for r in c.execute("SELECT id, code, name_zh, name_th, unit, avg_cost, category, material, color FROM inv_items")}
    bylocs = {}
    for r in c.execute("SELECT item_id, extra FROM inv_doc_lines WHERE doc_id=? AND extra LIKE '%by_loc%'", (d["id"],)):
        try:
            bylocs[r["item_id"]] = (json.loads(r["extra"]) or {}).get("by_loc") or {}
        except ValueError:
            pass
    locs = []
    lst = units.loc_stats(c)
    for r in c.execute("SELECT * FROM inv_loc_count_locs WHERE doc_id=?", (d["id"],)):
        rows = []
        for x in c.execute("SELECT * FROM inv_loc_count WHERE doc_id=? AND loc_id=?", (d["id"], r["loc_id"])):
            it = items.get(x["item_id"])
            if not it:
                continue
            book = x["expected"] if d["status"] != "draft" else wms.loc_qty(c, x["item_id"], r["loc_id"])
            row = {"item_id": x["item_id"], "code": it["code"], "name_zh": it["name_zh"], "name_th": it["name_th"], "unit": it["unit"],
                   "book": book, "counted": x["counted"], "diff": None if x["counted"] is None else round(x["counted"] - book, 6),
                   "amount": None if x["counted"] is None else round((x["counted"] - book) * float(it["avg_cost"] or 0), 2)}
            if it["category"] == "filament":                   # v2.55：耗材这个货位上账面几卷（可以数卷、可以称重）
                here = (lst.get((it["material"], it["color"])) or {}).get(r["loc_id"]) or {"rolls": 0, "grams": 0.0, "loaded": 0, "shelf": 0}
                was = (bylocs.get(x["item_id"]) or {}).get(str(r["loc_id"]))
                if was and d["status"] == "draft" and int(was[1]) != here["shelf"]:      # 填数以后这个货位的账面变了
                    row["sys_changed"] = {"was": int(was[1]), "now": here["shelf"]}
                row.update(fil=True, material=it["material"], color=it["color"], book_rolls=here["shelf"], book_loaded=here["loaded"],
                           book_text_zh=units.loc_text(it["material"], here["rolls"], book)[0], book_text_th=units.loc_text(it["material"], here["rolls"], book)[1])
            rows.append(row)
        rows.sort(key=lambda x: x["code"])
        locs.append({"code": r["code"], "loc_id": r["loc_id"], "done": bool(r["done"]), "by": r["counted_by"] or "", "at": r["counted_at"],
                     "rows": rows, "diffs": sum(1 for x in rows if x["diff"])})
    locs.sort(key=lambda x: L.sort_key(x["code"]))
    d["locs"] = locs
    d["by_location"] = bool(locs)
    d["progress"] = {"done": sum(1 for x in locs if x["done"]), "total": len(locs),
                     "diffs": sum(x["diffs"] for x in locs), "plus": sum(x["diff"] for l in locs for x in l["rows"] if (x["diff"] or 0) > 0),
                     "minus": sum(x["diff"] for l in locs for x in l["rows"] if (x["diff"] or 0) < 0),
                     # v2.53：差异折成钱（盘盈 / 盘亏，按平均单价；没有金额权限的人看不到）
                     "amount": {"plus": round(sum(x["amount"] for l in locs for x in l["rows"] if (x["amount"] or 0) > 0), 2),
                                "minus": round(sum(x["amount"] for l in locs for x in l["rows"] if (x["amount"] or 0) < 0), 2)}}
    return d


def _confirm_loc_rolls(c, it, ex, d, user):
    """按货位数卷的确认（v2.55.0）：每个数过的货位，按「确认这一刻这个货位架子上的卷数」算多 / 少几卷。
    少了：只拿这个货位上的那几卷（先整卷，再剩得少的），在机上的不动；多了：新建的料卷直接放进数的这个货位（不进待上架）。"""
    import logging
    from core import materials
    changed = False
    for lid_s, (cnt, sys0) in (ex.get("by_loc") or {}).items():
        lid = int(lid_s)
        loc = c.execute("SELECT code FROM inv_locations WHERE id=?", (lid,)).fetchone()
        rows = c.execute("SELECT s.code FROM spools s JOIN inv_spool_loc l ON l.spool_id=s.id WHERE l.loc_id=? AND s.material=? AND s.color=? "
                         "AND s.status IN ('sealed','open') AND (s.status='sealed' OR s.remaining_g>0) "
                         "ORDER BY CASE s.status WHEN 'sealed' THEN 0 ELSE 1 END, CASE s.status WHEN 'open' THEN s.remaining_g ELSE 0 END, s.id",
                         (lid, it["material"], it["color"])).fetchall()
        cur = len(rows)
        delta = int(cnt) - cur
        if int(sys0) != cur and not ex.get("warn"):
            ex["warn"] = {"was": int(sys0), "now": cur, "done": True}
        if delta < 0:
            materials.take_rolls(it["material"], it["color"], 0, [r["code"] for r in rows[:-delta]], user, f"盘点 {d['no']} {loc['code']} 少")
            changed = True
        elif delta > 0:
            codes = materials.receive(it["material"], it["color"], delta, units.roll_g_of(it), "", None, user,
                                      reason=f"盘点 {d['no']} {loc['code']} 多 {delta} 卷")
            changed = True
            for cd in codes:
                try:
                    flows.spool_put(cd, loc["code"], user)
                except Exception as e:  # noqa: BLE001  放不进去（停用 / 打印机槽位）就留在待上架
                    logging.getLogger("3dops").warning("盘点多出来的 %s 没能放进 %s：%s", cd, loc["code"], e)
    return changed


def confirm(doc_id, user=""):
    """确认：库存按实盘调整（盘点单原来的逻辑），数过的货位上的数改成数到的数。"""
    c = db.conn()
    d = _doc(c, doc_id)
    if d["status"] != "draft":
        raise ValueError("这张盘点单已经确认了")
    _sync_lines(c, d["id"])
    rows = [dict(r) for r in c.execute("SELECT * FROM inv_loc_count WHERE doc_id=? AND counted IS NOT NULL", (d["id"],))]
    for r in rows:                               # 记下确认时货位上的账面数（以后看单子用）
        c.execute("UPDATE inv_loc_count SET expected=? WHERE doc_id=? AND loc_id=? AND item_id=?",
                  (wms.loc_qty(c, r["item_id"], r["loc_id"]), d["id"], r["loc_id"], r["item_id"]))
    c.commit()
    ids = {r["item_id"] for r in rows}
    moded = {r[0] for r in c.execute("SELECT item_id FROM inv_doc_lines WHERE doc_id=? AND extra LIKE '%\"mode\"%'", (d["id"],))}
    with wms.quiet(ids - moded):                 # v2.55：按卷数 / 称重盘的耗材，货位上的数由料卷自己跟（不用 quiet）
        out = inv.stocktake_confirm(d["id"], user, loc_hook=_confirm_loc_rolls)
    code_of = {r["id"]: r["code"] for r in c.execute("SELECT id, code FROM inv_locations")}
    ids -= moded
    rows = [r for r in rows if r["item_id"] not in moded]
    for r in rows:
        old = wms.loc_qty(c, r["item_id"], r["loc_id"])
        if abs(old - r["counted"]) > 1e-9:
            wms._set(c, r["item_id"], r["loc_id"], r["counted"])
            wms._log(c, r["item_id"], code_of.get(r["loc_id"], ""), code_of.get(r["loc_id"], ""), r["counted"] - old, "count", user, d["no"])
    for iid in ids:
        wms.reconcile(c, iid, user, "count")
    c.commit()
    return summary(out["id"])
