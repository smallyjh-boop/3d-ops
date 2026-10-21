"""采购（v2.18）：供应商、采购单（草稿 → 已下单·在途 → 部分到货 → 已到货；可取消）、到货入库、付款、补货建议。

到货入库：生成一张「采购入库」单据（库存 + 流水），运费 / 其他费用按金额分摊进单价（到手成本）。
付款：记在采购单上，同时记一条财务事件（fin_events，给财务模块读）。
"""
import datetime as dt
import json
import math

from .. import db
from ..config import load_config
from . import docs, finance, ledger

SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_suppliers (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, contact TEXT, phone TEXT, platform TEXT, link TEXT, lead_days REAL,
  note TEXT, active INTEGER DEFAULT 1, created_at REAL
);
CREATE TABLE IF NOT EXISTS inv_po (
  id INTEGER PRIMARY KEY AUTOINCREMENT, no TEXT UNIQUE, supplier_id INTEGER, status TEXT, expected_date TEXT,
  ship_fee REAL DEFAULT 0, other_fee REAL DEFAULT 0, note TEXT, created_by TEXT, created_at REAL, ordered_at REAL,
  received_at REAL, cancelled_at REAL, tracking TEXT
);
CREATE TABLE IF NOT EXISTS inv_po_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT, po_id INTEGER, item_id INTEGER, qty REAL, unit_cost REAL, received REAL DEFAULT 0,
  rolls INTEGER, net_g REAL, brand TEXT, note TEXT
);
CREATE INDEX IF NOT EXISTS inv_po_lines_po ON inv_po_lines(po_id);
CREATE TABLE IF NOT EXISTS inv_payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, po_id INTEGER, ts REAL, day TEXT, amount REAL, method TEXT, note TEXT, username TEXT
);
"""
STATUS = {"draft": "草稿", "ordered": "已下单·在途", "partial": "部分到货", "received": "已到货", "cancelled": "已取消"}
METHODS = ["转账", "现金", "信用卡", "平台付款", "其他"]


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(inv_items)")}
    for col, typ in (("supplier_id", "INTEGER"), ("reorder_qty", "REAL")):
        if col not in cols:
            c.execute(f"ALTER TABLE inv_items ADD COLUMN {col} {typ}")
    c.commit()


# ---------------- 供应商 ----------------
def suppliers(include_inactive=False):
    return [dict(r) for r in db.conn().execute("SELECT * FROM inv_suppliers" + ("" if include_inactive else " WHERE active=1") + " ORDER BY name")]


def save_supplier(d, user=""):
    c = db.conn()
    name = str(d.get("name") or "").strip()
    if not name:
        raise ValueError("请填写供应商名称")
    vals = {k: (str(d.get(k) or "").strip()[:300]) for k in ("contact", "phone", "platform", "link", "note")}
    lead = d.get("lead_days")
    vals["lead_days"] = float(lead) if lead not in (None, "") else None
    if d.get("id"):
        vals["active"] = 1 if d.get("active", 1) not in (0, "0", False) else 0
        c.execute("UPDATE inv_suppliers SET name=?, " + ", ".join(f"{k}=?" for k in vals) + " WHERE id=?", (name, *vals.values(), int(d["id"])))
        sid = int(d["id"])
    else:
        sid = c.execute("INSERT INTO inv_suppliers(name, " + ", ".join(vals) + ", active, created_at) VALUES(?," + ",".join("?" * len(vals)) + ",1,?)",
                        (name, *vals.values(), ledger._now())).lastrowid
    c.commit()
    db.audit(user, "库存·供应商", name, "")
    return dict(c.execute("SELECT * FROM inv_suppliers WHERE id=?", (sid,)).fetchone())


# ---------------- 采购单 ----------------
def _no(c):
    pre = "CG" + dt.datetime.now().strftime("%Y%m%d")
    n = c.execute("SELECT COUNT(*) FROM inv_po WHERE no LIKE ?", (pre + "%",)).fetchone()[0] + 1
    no = f"{pre}-{n:02d}"
    while c.execute("SELECT 1 FROM inv_po WHERE no=?", (no,)).fetchone():
        n += 1
        no = f"{pre}-{n:02d}"
    return no


def _clean_lines(lines):
    out = []
    for i, ln in enumerate(lines or []):
        it = ledger.get_item(ln.get("item_id"))
        if not it:
            raise ValueError(f"第 {i + 1} 行：没有这个物品")
        try:
            rolls = int(ln["rolls"]) if ln.get("rolls") not in (None, "") else None
            net = float(ln.get("net_g") or 1000) if rolls else None
            q = rolls * net if rolls and it["category"] == "filament" else float(ln.get("qty") or 0)
            uc = float(ln["unit_cost"]) if ln.get("unit_cost") not in (None, "") else (it["avg_cost"] or 0)
        except (TypeError, ValueError):
            raise ValueError(f"第 {i + 1} 行：数量 / 单价不对")
        if not (math.isfinite(q) and math.isfinite(uc)):      # v2.39
            raise ValueError(f"第 {i + 1} 行：数量 / 单价不对")
        if q <= 0 or uc < 0:
            raise ValueError(f"第 {i + 1} 行：数量要大于 0、单价不能是负数")
        out.append({"item_id": it["id"], "qty": q, "unit_cost": uc, "rolls": rolls if it["category"] == "filament" else None,
                    "net_g": net if it["category"] == "filament" else None, "brand": str(ln.get("brand") or "")[:40],
                    "note": str(ln.get("note") or "")[:200]})
    if not out:
        raise ValueError("至少要有一行")
    return out


def save_po(d, user=""):
    """新建 / 修改采购单（只有草稿能改行）。"""
    c = db.conn()
    fees = {}
    for k in ("ship_fee", "other_fee"):
        try:
            fees[k] = float(d.get(k) or 0)
            if not math.isfinite(fees[k]):      # v2.39
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("运费 / 其他费用要是数字")
    sup = int(d["supplier_id"]) if d.get("supplier_id") not in (None, "") else None
    info = (sup, str(d.get("expected_date") or "")[:10], fees["ship_fee"], fees["other_fee"], str(d.get("note") or "")[:500])
    if d.get("id"):
        po = c.execute("SELECT * FROM inv_po WHERE id=?", (int(d["id"]),)).fetchone()
        if not po:
            raise ValueError("没有这张采购单")
        if po["status"] in ("received", "cancelled"):
            raise ValueError("已到货 / 已取消的采购单不能改")
        c.execute("UPDATE inv_po SET supplier_id=?, expected_date=?, ship_fee=?, other_fee=?, note=? WHERE id=?", (*info, po["id"]))
        if "lines" in d:
            if po["status"] != "draft":
                raise ValueError("已下单的采购单不能改明细（可以取消后重开）")
            lines = _clean_lines(d["lines"])
            c.execute("DELETE FROM inv_po_lines WHERE po_id=?", (po["id"],))
            _ins_lines(c, po["id"], lines)
        pid = po["id"]
    else:
        lines = _clean_lines(d.get("lines"))
        pid = c.execute("INSERT INTO inv_po(no, supplier_id, expected_date, ship_fee, other_fee, note, status, created_by, created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?)", (_no(c), *info, "draft", user, ledger._now())).lastrowid
        _ins_lines(c, pid, lines)
    c.commit()
    return get_po(pid)


def _ins_lines(c, pid, lines):
    for ln in lines:
        c.execute("INSERT INTO inv_po_lines(po_id, item_id, qty, unit_cost, rolls, net_g, brand, note) VALUES(?,?,?,?,?,?,?,?)",
                  (pid, ln["item_id"], ln["qty"], ln["unit_cost"], ln["rolls"], ln["net_g"], ln["brand"], ln["note"]))


def _po(c, pid):
    po = c.execute("SELECT * FROM inv_po WHERE id=? OR no=?", (int(pid) if str(pid).isdigit() else -1, str(pid))).fetchone()
    if not po:
        raise ValueError("没有这张采购单")
    return po


def set_status(pid, action, user="", tracking=None):
    """order 下单（变在途）/ cancel 取消（已到货的部分不退）/ close 结单（剩下的不要了）。"""
    c = db.conn()
    po = _po(c, pid)
    now = ledger._now()
    if action == "order":
        if po["status"] != "draft":
            raise ValueError("只有草稿能下单")
        c.execute("UPDATE inv_po SET status='ordered', ordered_at=?, tracking=COALESCE(?, tracking) WHERE id=?", (now, tracking, po["id"]))
    elif action == "cancel":
        if po["status"] in ("received", "cancelled"):
            raise ValueError("已到货 / 已取消的不能取消")
        c.execute("UPDATE inv_po SET status='cancelled', cancelled_at=? WHERE id=?", (now, po["id"]))
    elif action == "close":
        if po["status"] != "partial":
            raise ValueError("只有部分到货的单可以结单")
        c.execute("UPDATE inv_po SET status='received', received_at=? WHERE id=?", (now, po["id"]))
    elif action == "tracking":
        c.execute("UPDATE inv_po SET tracking=? WHERE id=?", (str(tracking or "")[:100], po["id"]))
    else:
        raise ValueError("操作不对")
    c.commit()
    db.audit(user, "库存·采购单", po["no"], action)
    return get_po(po["id"])


def receive(pid, qtys=None, user="", note=""):
    """到货入库。qtys：{行id: 到货数量}（耗材按卷的行填卷数）；不给 = 剩下的全部到货。运费等按金额分摊进单价。"""
    c = db.conn()
    po = _po(c, pid)
    if po["status"] not in ("ordered", "partial"):
        raise ValueError("要先「下单」，到货后才能入库")
    lines = c.execute("SELECT * FROM inv_po_lines WHERE po_id=?", (po["id"],)).fetchall()
    goods_total = sum((ln["qty"] or 0) * (ln["unit_cost"] or 0) for ln in lines) or 1.0
    fee_rate = ((po["ship_fee"] or 0) + (po["other_fee"] or 0)) / goods_total
    doc_lines, got = [], {}
    for ln in lines:
        left = (ln["qty"] or 0) - (ln["received"] or 0)
        if left <= 1e-9:
            continue
        if qtys is None:
            q = left
        else:
            v = qtys.get(str(ln["id"]), qtys.get(ln["id"]))
            if v in (None, "", 0, "0"):
                continue
            if ln["rolls"] and abs(float(v) - round(float(v))) > 1e-9:      # v2.39：按卷的耗材只能整卷到货
                raise ValueError("按卷采购的耗材，到货要填整数卷")
            q = float(v) * (ln["net_g"] or 1000) if ln["rolls"] else float(v)
        if q <= 0:
            continue
        if qtys is not None and q > left + 1e-6:      # v2.39：不能比还没到的多（以前能收成 14/10）
            it = ledger.get_item(ln["item_id"]) or {}
            unit = "卷" if ln["rolls"] else (it.get("unit") or "")
            left_show = left / (ln["net_g"] or 1000) if ln["rolls"] else left
            raise ValueError(f"{it.get('name_zh') or ''}：这次到货比还没到的多（还差 {left_show:g} {unit}）。"
                             f"供应商多发了的话，多出来的另开一张采购入库单")
        q = min(q, left) if qtys is None else q
        uc = (ln["unit_cost"] or 0) * (1 + fee_rate)
        dl = {"item_id": ln["item_id"], "qty": q, "unit_cost": round(uc, 6), "note": ln["note"] or "", "po_line": ln["id"]}
        if ln["rolls"]:
            dl.update(rolls=int(round(q / (ln["net_g"] or 1000))), net_g=ln["net_g"], brand=ln["brand"])
        doc_lines.append(dl)
        got[ln["id"]] = q
    if not doc_lines:
        raise ValueError("没有要入库的数量")
    d = docs.create("purchase", doc_lines, (note or f"采购单 {po['no']} 到货"), user, ref=f"po:{po['no']}")
    for lid, q in got.items():
        c.execute("UPDATE inv_po_lines SET received=COALESCE(received,0)+? WHERE id=?", (q, lid))
    left = c.execute("SELECT SUM(MAX(qty-COALESCE(received,0),0)) FROM inv_po_lines WHERE po_id=?", (po["id"],)).fetchone()[0] or 0
    now = ledger._now()
    c.execute("UPDATE inv_po SET status=?, received_at=CASE WHEN ?='received' THEN ? ELSE received_at END WHERE id=?",
              ("received" if left <= 1e-6 else "partial", "received" if left <= 1e-6 else "partial", now, po["id"]))
    c.commit()
    finance.event("purchase_received", round(abs(d.get("amount") or 0), 2), ref_type="po", ref_no=po["no"],
                  note=f"采购到货入库 {d['no']}", user=user, category=_po_category(c, po["id"]))
    return get_po(po["id"])


def on_receipt_void(d, amount, user=""):
    """v2.39：采购到货入库单被作废：已到数量减回去、状态退回「已下单 / 部分到货」、财务记一笔负的到货。"""
    c = db.conn()
    po = c.execute("SELECT * FROM inv_po WHERE no=?", (d["ref"][3:],)).fetchone()
    if not po:
        return
    lines = c.execute("SELECT id, qty, COALESCE(received,0) r FROM inv_po_lines WHERE po_id=?", (po["id"],)).fetchall()
    closed = po["status"] == "received" and any(ln["r"] < (ln["qty"] or 0) - 1e-9 for ln in lines)   # 手动「结单」过的
    for dl in c.execute("SELECT item_id, qty, extra FROM inv_doc_lines WHERE doc_id=?", (d["id"],)).fetchall():
        left = abs(dl["qty"] or 0)
        try:
            pl = (json.loads(dl["extra"] or "{}") or {}).get("po_line")
        except ValueError:
            pl = None
        if pl:      # 入库时记了是采购单哪一行 → 精确退回这一行
            c.execute("UPDATE inv_po_lines SET received=MAX(0, COALESCE(received,0)-?) WHERE id=? AND po_id=?", (left, pl, po["id"]))
            continue
        for ln in c.execute("SELECT id, COALESCE(received,0) r FROM inv_po_lines WHERE po_id=? AND item_id=? ORDER BY id DESC",
                            (po["id"], dl["item_id"])).fetchall():
            take = min(left, ln["r"])
            if take > 0:
                c.execute("UPDATE inv_po_lines SET received=? WHERE id=?", (max(0, ln["r"] - take), ln["id"]))
                left -= take
            if left <= 1e-9:
                break
    if po["status"] in ("partial", "received") and not closed:
        got = c.execute("SELECT SUM(COALESCE(received,0)) FROM inv_po_lines WHERE po_id=?", (po["id"],)).fetchone()[0] or 0
        c.execute("UPDATE inv_po SET status=?, received_at=NULL WHERE id=?", ("partial" if got > 1e-9 else "ordered", po["id"]))
    c.commit()
    if amount:
        finance.event("purchase_received", -round(amount, 2), ref_type="po", ref_no=po["no"],
                      note=f"作废到货入库单 {d['no']}", user=user, category=_po_category(c, po["id"]))


def _po_category(c, pid):
    cats = [r[0] for r in c.execute("SELECT DISTINCT i.category FROM inv_po_lines l JOIN inv_items i ON i.id=l.item_id WHERE l.po_id=?", (pid,))]
    return cats[0] if len(cats) == 1 else "mixed"


def pay(pid, amount, method="转账", day=None, note="", user=""):
    c = db.conn()
    po = _po(c, pid)
    try:
        amt = round(float(amount), 2)
    except (TypeError, ValueError):
        raise ValueError("金额要是数字")
    if not amt:
        raise ValueError("金额不能是 0")
    day = str(day or dt.date.today().isoformat())[:10]
    c.execute("INSERT INTO inv_payments(po_id, ts, day, amount, method, note, username) VALUES(?,?,?,?,?,?,?)",
              (po["id"], ledger._now(), day, amt, str(method or "")[:20], str(note or "")[:200], user))
    c.commit()
    sup = c.execute("SELECT name FROM inv_suppliers WHERE id=?", (po["supplier_id"],)).fetchone() if po["supplier_id"] else None
    finance.event("purchase_payment", amt, ref_type="po", ref_no=po["no"], note=f"{sup['name'] if sup else ''} {note or ''}".strip(),
                  user=user, category=_po_category(c, po["id"]), day=day, method=method)
    db.audit(user, "库存·采购付款", po["no"], f"{amt}")
    return get_po(po["id"])


def get_po(pid):
    c = db.conn()
    po = _po(c, pid)
    d = dict(po)
    d["status_zh"] = STATUS.get(d["status"], d["status"])
    sup = c.execute("SELECT * FROM inv_suppliers WHERE id=?", (po["supplier_id"],)).fetchone() if po["supplier_id"] else None
    d["supplier"] = dict(sup) if sup else None
    d["lines"] = [dict(r) for r in c.execute("SELECT l.*, i.code, i.name_zh, i.name_th, i.unit, i.category FROM inv_po_lines l "
                                             "JOIN inv_items i ON i.id=l.item_id WHERE l.po_id=? ORDER BY l.id", (po["id"],))]
    d["goods_total"] = round(sum((x["qty"] or 0) * (x["unit_cost"] or 0) for x in d["lines"]), 2)
    d["total"] = round(d["goods_total"] + (po["ship_fee"] or 0) + (po["other_fee"] or 0), 2)
    d["payments"] = [dict(r) for r in c.execute("SELECT * FROM inv_payments WHERE po_id=? ORDER BY id", (po["id"],))]
    d["paid"] = round(sum(p["amount"] for p in d["payments"]), 2)
    d["pay_status"] = "paid" if d["paid"] >= d["total"] - 0.01 and d["total"] > 0 else ("partial" if d["paid"] else "unpaid")
    d["docs"] = [x for x in docs.list_docs("purchase", limit=50) if x.get("ref") == f"po:{po['no']}"]
    return d


def list_po(status="", days=None):
    sql, args = "SELECT id FROM inv_po", []
    conds = []
    if status == "open":
        conds.append("status IN ('draft','ordered','partial')")
    elif status:
        conds.append("status=?"); args.append(status)
    if days:
        conds.append("created_at>=?"); args.append(ledger._now() - float(days) * 86400)
    sql += (" WHERE " + " AND ".join(conds) if conds else "") + " ORDER BY id DESC LIMIT 300"
    out = []
    for r in db.conn().execute(sql, args).fetchall():
        d = get_po(r["id"])
        d.pop("docs", None)
        out.append(d)
    return out


def in_transit():
    """{物品id: 在途数量}（已下单、还没到的）。"""
    out = {}
    for r in db.conn().execute("SELECT l.item_id, SUM(MAX(l.qty-COALESCE(l.received,0),0)) q FROM inv_po_lines l JOIN inv_po p ON p.id=l.po_id "
                               "WHERE p.status IN ('ordered','partial') GROUP BY l.item_id"):
        out[r["item_id"]] = r["q"] or 0
    return out


def suggest():
    """补货建议：库存 + 在途 ≤ 补货线的物品；耗材再加上耗材模块按用量算的建议（该下单的）。按默认供应商分组。"""
    c = db.conn()
    tr = in_transit()
    out = {}
    for r in c.execute("SELECT * FROM inv_items WHERE active=1"):
        it = ledger.item_row(r)
        have = (it["qty"] or 0) + tr.get(it["id"], 0)
        need, why = 0.0, ""
        if it.get("reorder_point") is not None and have <= it["reorder_point"]:
            target = it.get("reorder_qty") or max(it["reorder_point"], 1)
            need = max(target, it["reorder_point"] * 2 - have) if not it.get("reorder_qty") else target
            why = f"库存 + 在途 {have:g} ≤ 补货线 {it['reorder_point']:g}"
        if need > 0:
            out[it["id"]] = {"item": it, "qty": need, "why": why, "transit": tr.get(it["id"], 0)}
    try:
        from .. import materials
        spool_g = float(load_config().get("filament_spool_kg") or 1.0) * 1000
        for row in materials.plan()["rows"]:
            if not (row.get("urgent") or row.get("short")) or not row.get("suggest_spools"):
                continue
            r = c.execute("SELECT * FROM inv_items WHERE category='filament' AND material=? AND color=? AND active=1",
                          (row["material"].upper(), row["color"])).fetchone()
            if not r:
                continue
            it = ledger.item_row(r)
            transit = tr.get(it["id"], 0)
            rolls = max(0, int(row["suggest_spools"]) - int(math.floor(transit / spool_g)))
            if rolls <= 0:
                continue
            out[it["id"]] = {"item": it, "qty": rolls * spool_g, "rolls": rolls, "net_g": spool_g, "transit": transit,
                             "why": f"按用量 {row.get('runout_date') or '很快'} 用完，建议买 {rolls} 卷"}
    except Exception:  # noqa: BLE001  耗材建议拿不到不影响
        pass
    return sorted(out.values(), key=lambda x: (x["item"].get("supplier_id") or 0, x["item"]["category"], x["item"]["code"]))


def po_from_suggest(item_ids, user=""):
    """按补货建议生成采购单草稿：按物品的默认供应商分组，每个供应商一张。"""
    want = {int(i) for i in item_ids or []}
    groups = {}
    for s in suggest():
        if want and s["item"]["id"] not in want:
            continue
        ln = {"item_id": s["item"]["id"], "qty": s["qty"], "unit_cost": s["item"].get("avg_cost") or None}
        if s.get("rolls"):
            ln.update(rolls=s["rolls"], net_g=s["net_g"])
        groups.setdefault(s["item"].get("supplier_id"), []).append(ln)
    out = []
    for sup, lines in groups.items():
        out.append(save_po({"supplier_id": sup, "lines": lines, "note": "按补货建议生成"}, user))
    return out


def _dumps(x):
    return json.dumps(x, ensure_ascii=False)


def summary():
    """采购模块顶上的概况（v2.21）：进行中几张、在途金额、还没付的钱、本月到货 / 付款。"""
    import datetime as _dt
    c = db.conn()
    open_n = c.execute("SELECT COUNT(*) FROM inv_po WHERE status IN ('draft','ordered','partial')").fetchone()[0]
    transit = c.execute("SELECT COALESCE(SUM((l.qty-COALESCE(l.received,0))*l.unit_cost),0) FROM inv_po_lines l JOIN inv_po p ON p.id=l.po_id "
                        "WHERE p.status IN ('ordered','partial') AND l.qty>COALESCE(l.received,0)").fetchone()[0]
    unpaid = 0.0
    for r in c.execute("SELECT id FROM inv_po WHERE status IN ('ordered','partial','received')").fetchall():
        d = get_po(r["id"])
        unpaid += max(0.0, d["total"] - d["paid"])
    m0 = _dt.date.today().replace(day=1)
    start = _dt.datetime(m0.year, m0.month, 1).timestamp()
    rec = c.execute("SELECT COALESCE(SUM(amount),0) FROM inv_moves WHERE kind='purchase' AND ts>=?", (start,)).fetchone()[0]
    paid = c.execute("SELECT COALESCE(SUM(amount),0) FROM inv_payments WHERE day>=?", (m0.isoformat(),)).fetchone()[0]
    return {"open": open_n, "in_transit": round(transit, 2), "unpaid": round(unpaid, 2), "month_received": round(rec, 2),
            "month_paid": round(paid, 2), "month": m0.strftime("%Y-%m")}
