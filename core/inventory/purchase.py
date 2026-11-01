"""采购（v2.18）：供应商、采购单（草稿 → 已下单·在途 → 部分到货 → 已入库 → 完成；可取消、退货）、到货入库、付款、补货建议。

到货入库：生成一张「采购入库」单据（库存 + 流水），运费 / 税 / 其他费用按金额分摊进单价（到手成本）。
v2.51：采购单可以用人民币下单（currency=CNY + 下单时的汇率 fx_rate）：货款和供应商运费按汇率折成泰铢，
      进口税（tax_fee）和其他费用（国际运费、清关……other_fee）直接是泰铢；到货时一起分摊进到手单价。
      到货时可以记差异（少发 short / 破损 damaged / 发错 wrong / 多发 extra → inv_po_issues），
      少发、破损的不进库存，那一行留着没到（可以「结单」）。到货后发事件 po.received（采购模块记价格历史、更新成本）。
      已入库 + 付清 → 自动「完成」；退货给供应商（po_return 单据，出库不算支出），供应商退款记负的付款。
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
CREATE TABLE IF NOT EXISTS inv_po_issues (
  id INTEGER PRIMARY KEY AUTOINCREMENT, po_id INTEGER, line_id INTEGER, item_id INTEGER, kind TEXT, qty REAL, note TEXT,
  status TEXT DEFAULT 'open', resolution TEXT, ts REAL, username TEXT, resolved_at REAL, resolved_by TEXT
);
CREATE INDEX IF NOT EXISTS inv_po_issues_po ON inv_po_issues(po_id);
"""
STATUS = {"draft": "草稿", "ordered": "已下单·在途", "partial": "部分到货", "received": "已入库", "done": "完成",
          "cancelled": "已取消", "returned": "已退货"}
FINAL = ("received", "done", "cancelled", "returned")           # 不再等到货的状态（应付按到了的算）
ISSUE_KINDS = {"short": "少发", "damaged": "破损", "wrong": "发错", "extra": "多发"}
CURRENCIES = ("THB", "CNY")
METHODS = ["转账", "现金", "信用卡", "平台付款", "其他"]


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(inv_items)")}
    for col, typ in (("supplier_id", "INTEGER"), ("reorder_qty", "REAL")):
        if col not in cols:
            c.execute(f"ALTER TABLE inv_items ADD COLUMN {col} {typ}")
    # v2.51：人民币采购单（汇率）、进口税、物流公司、平台订单号、来源、完成时间；行的退货数量；供应商的默认货币
    for table, adds in (("inv_po", (("currency", "TEXT DEFAULT 'THB'"), ("fx_rate", "REAL DEFAULT 1"), ("tax_fee", "REAL DEFAULT 0"),
                                     ("carrier", "TEXT"), ("order_ref", "TEXT"), ("source", "TEXT"), ("done_at", "REAL"))),
                        ("inv_po_lines", (("returned", "REAL DEFAULT 0"),)),
                        ("inv_suppliers", (("currency", "TEXT"),))):
        have = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
        for col, typ in adds:
            if col not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
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
    cur = str(d.get("currency") or "").upper()
    vals["currency"] = cur if cur in CURRENCIES else default_currency(vals["platform"], name)
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


def default_currency(platform="", name=""):
    """1688 / 淘宝 / 拼多多 / 阿里巴巴 → 人民币；其他（Shopee、Lazada、线下）→ 泰铢。"""
    t = f"{platform or ''} {name or ''}".lower()
    return "CNY" if any(w in t for w in ("1688", "淘宝", "taobao", "拼多多", "pinduoduo", "pdd", "阿里", "alibaba", "天猫", "tmall", "京东")) else "THB"


def default_fx():
    """人民币 → 泰铢的默认汇率（设置里的「人民币兑泰铢汇率」，定价也用它）。"""
    try:
        return float(load_config().get("cny_to_thb") or 0) or 4.5
    except (TypeError, ValueError):
        return 4.5


# ---------------- 采购单 ----------------
def _no(c):
    pre = "CG" + dt.datetime.now().strftime("%Y%m%d")
    n = c.execute("SELECT COUNT(*) FROM inv_po WHERE no LIKE ?", (pre + "%",)).fetchone()[0] + 1
    no = f"{pre}-{n:02d}"
    while c.execute("SELECT 1 FROM inv_po WHERE no=?", (no,)).fetchone():
        n += 1
        no = f"{pre}-{n:02d}"
    return no


def _clean_lines(lines, currency="THB"):
    out = []
    for i, ln in enumerate(lines or []):
        it = ledger.get_item(ln.get("item_id"))
        if not it:
            raise ValueError(f"第 {i + 1} 行：没有这个物品")
        try:
            rolls = int(ln["rolls"]) if ln.get("rolls") not in (None, "") else None
            net = float(ln.get("net_g") or 1000) if rolls else None
            q = rolls * net if rolls and it["category"] == "filament" else float(ln.get("qty") or 0)
            uc = float(ln["unit_cost"]) if ln.get("unit_cost") not in (None, "") else \
                ((it["avg_cost"] or 0) / (default_fx() if currency == "CNY" else 1))
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
    for k in ("ship_fee", "other_fee", "tax_fee"):
        try:
            fees[k] = float(d.get(k) or 0)
            if not math.isfinite(fees[k]) or fees[k] < 0:      # v2.39
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("运费 / 税 / 其他费用要是不小于 0 的数字")
    sup = int(d["supplier_id"]) if d.get("supplier_id") not in (None, "") else None
    old = c.execute("SELECT * FROM inv_po WHERE id=?", (int(d["id"]),)).fetchone() if d.get("id") else None
    srow = c.execute("SELECT * FROM inv_suppliers WHERE id=?", (sup,)).fetchone() if sup else None
    cur = str(d.get("currency") or (old["currency"] if old else "") or (srow["currency"] if srow else "") or "THB").upper()
    if cur not in CURRENCIES:
        raise ValueError("货币只能是 THB 或 CNY")
    try:
        fx = 1.0 if cur == "THB" else float(d.get("fx_rate") or (old["fx_rate"] if old and old["currency"] == cur else 0) or default_fx())
    except (TypeError, ValueError):
        raise ValueError("汇率要是数字")
    if not math.isfinite(fx) or fx <= 0:
        raise ValueError("汇率要大于 0")
    info = (sup, str(d.get("expected_date") or "")[:10], fees["ship_fee"], fees["other_fee"], str(d.get("note") or "")[:500],
            cur, fx, fees["tax_fee"])
    extra = {k: str(d.get(k) or "").strip()[:100] for k in ("carrier", "order_ref", "tracking") if k in d}
    if d.get("id"):
        po = old
        if not po:
            raise ValueError("没有这张采购单")
        if po["status"] in FINAL:
            raise ValueError("已到货 / 已取消的采购单不能改")
        if po["status"] != "draft" and (cur != (po["currency"] or "THB") or abs(fx - (po["fx_rate"] or 1)) > 1e-9):
            if any((r["received"] or 0) > 0 for r in c.execute("SELECT received FROM inv_po_lines WHERE po_id=?", (po["id"],))):
                raise ValueError("已经有到货入库了，不能再改货币 / 汇率（到手成本已经按原来的汇率算了）")
        c.execute("UPDATE inv_po SET supplier_id=?, expected_date=?, ship_fee=?, other_fee=?, note=?, currency=?, fx_rate=?, tax_fee=? "
                  "WHERE id=?", (*info, po["id"]))
        for k, v in extra.items():
            c.execute(f"UPDATE inv_po SET {k}=? WHERE id=?", (v, po["id"]))
        if "lines" in d:
            if po["status"] != "draft":
                raise ValueError("已下单的采购单不能改明细（可以取消后重开）")
            lines = _clean_lines(d["lines"], cur)
            c.execute("DELETE FROM inv_po_lines WHERE po_id=?", (po["id"],))
            _ins_lines(c, po["id"], lines)
        pid = po["id"]
    else:
        lines = _clean_lines(d.get("lines"), cur)
        pid = c.execute("INSERT INTO inv_po(no, supplier_id, expected_date, ship_fee, other_fee, note, currency, fx_rate, tax_fee, "
                        "status, created_by, created_at, source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (_no(c), *info, "draft", user, ledger._now(), str(d.get("source") or "manual")[:20])).lastrowid
        for k, v in extra.items():
            c.execute(f"UPDATE inv_po SET {k}=? WHERE id=?", (v, pid))
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
    """order 下单（变在途）/ cancel 取消（已到货的部分不退）/ close 结单（剩下的不要了）/ done 完成 / tracking 填运单号。"""
    c = db.conn()
    po = _po(c, pid)
    now = ledger._now()
    if action == "order":
        if po["status"] != "draft":
            raise ValueError("只有草稿能下单")
        c.execute("UPDATE inv_po SET status='ordered', ordered_at=?, tracking=COALESCE(?, tracking) WHERE id=?", (now, tracking, po["id"]))
    elif action == "cancel":
        if po["status"] in FINAL:
            raise ValueError("已到货 / 已取消的不能取消")
        c.execute("UPDATE inv_po SET status='cancelled', cancelled_at=? WHERE id=?", (now, po["id"]))
    elif action == "close":
        if po["status"] != "partial":
            raise ValueError("只有部分到货的单可以结单")
        c.execute("UPDATE inv_po SET status='received', received_at=? WHERE id=?", (now, po["id"]))
        c.commit()
        _auto_done(c, po["id"])
    elif action == "done":
        if po["status"] != "received":
            raise ValueError("只有已入库的采购单可以标记完成")
        c.execute("UPDATE inv_po SET status='done', done_at=? WHERE id=?", (now, po["id"]))
    elif action == "tracking":
        c.execute("UPDATE inv_po SET tracking=? WHERE id=?", (str(tracking or "")[:100], po["id"]))
    else:
        raise ValueError("操作不对")
    c.commit()
    db.audit(user, "库存·采购单", po["no"], action)
    return get_po(po["id"])


def _auto_done(c, pid):
    """v2.51：已入库 + 已付清（也没有没处理的到货差异）→ 自动「完成」。"""
    d = get_po(pid)
    if d["status"] == "received" and d["pay_status"] == "paid" and not d["issues_open"]:
        c.execute("UPDATE inv_po SET status='done', done_at=? WHERE id=?", (ledger._now(), pid))
        c.commit()


def _fx(po):
    return float(po["fx_rate"] or 1) if (po["currency"] or "THB") != "THB" else 1.0


def fee_rate(c, po):
    """到手成本的分摊比例：(供应商运费 × 汇率 + 税 + 其他费用) ÷ 货款（泰铢）。按金额分摊。"""
    lines = c.execute("SELECT qty, unit_cost FROM inv_po_lines WHERE po_id=?", (po["id"],)).fetchall()
    fx = _fx(po)
    goods = sum((ln["qty"] or 0) * (ln["unit_cost"] or 0) for ln in lines) * fx or 1.0
    return ((po["ship_fee"] or 0) * fx + (po["other_fee"] or 0) + (po["tax_fee"] or 0)) / goods


def receive(pid, qtys=None, user="", note="", issues=None):
    """到货入库。qtys：{行id: 到货数量}（耗材按卷的行填卷数）；不给 = 剩下的全部到货。运费等按金额分摊进单价。
    v2.51 issues：[{line_id, kind: short/damaged/wrong/extra, qty, note}] 到货差异（只记录；少发 / 破损的不进库存）。
    可以只记差异不入库（qtys = {}）。"""
    c = db.conn()
    po = _po(c, pid)
    if po["status"] not in ("ordered", "partial"):
        raise ValueError("要先「下单」，到货后才能入库")
    lines = c.execute("SELECT * FROM inv_po_lines WHERE po_id=?", (po["id"],)).fetchall()
    rate = fee_rate(c, po)
    fx = _fx(po)
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
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise ValueError("到货数量要是数字")
            if not math.isfinite(fv) or fv < 0:
                raise ValueError("到货数量要是数字")
            if ln["rolls"] and abs(fv - round(fv)) > 1e-9:      # v2.39：按卷的耗材只能整卷到货
                raise ValueError("按卷采购的耗材，到货要填整数卷")
            q = fv * (ln["net_g"] or 1000) if ln["rolls"] else fv
        if q <= 0:
            continue
        if qtys is not None and q > left + 1e-6:      # v2.39：不能比还没到的多（以前能收成 14/10）
            it = ledger.get_item(ln["item_id"]) or {}
            unit = "卷" if ln["rolls"] else (it.get("unit") or "")
            left_show = left / (ln["net_g"] or 1000) if ln["rolls"] else left
            raise ValueError(f"{it.get('name_zh') or ''}：这次到货比还没到的多（还差 {left_show:g} {unit}）。"
                             f"供应商多发了的话，多出来的另开一张采购入库单")
        q = min(q, left) if qtys is None else q
        uc = (ln["unit_cost"] or 0) * fx * (1 + rate)
        dl = {"item_id": ln["item_id"], "qty": q, "unit_cost": round(uc, 6), "note": ln["note"] or "", "po_line": ln["id"]}
        if ln["rolls"]:
            dl.update(rolls=int(round(q / (ln["net_g"] or 1000))), net_g=ln["net_g"], brand=ln["brand"])
        doc_lines.append(dl)
        got[ln["id"]] = q
    clean_issues = _clean_issues(po, lines, issues)
    if not doc_lines and not clean_issues:
        raise ValueError("没有要入库的数量")
    d = None
    if doc_lines:
        d = docs.create("purchase", doc_lines, (note or f"采购单 {po['no']} 到货"), user, ref=f"po:{po['no']}")
        for lid, q in got.items():
            c.execute("UPDATE inv_po_lines SET received=COALESCE(received,0)+? WHERE id=?", (q, lid))
    now = ledger._now()
    for x in clean_issues:
        c.execute("INSERT INTO inv_po_issues(po_id, line_id, item_id, kind, qty, note, status, ts, username) VALUES(?,?,?,?,?,?,?,?,?)",
                  (po["id"], x["line_id"], x["item_id"], x["kind"], x["qty"], x["note"], "open", now, user))
    left = c.execute("SELECT SUM(MAX(qty-COALESCE(received,0),0)) FROM inv_po_lines WHERE po_id=?", (po["id"],)).fetchone()[0] or 0
    got_any = c.execute("SELECT SUM(COALESCE(received,0)) FROM inv_po_lines WHERE po_id=?", (po["id"],)).fetchone()[0] or 0
    st = "received" if left <= 1e-6 else ("partial" if got_any > 1e-9 else po["status"])
    c.execute("UPDATE inv_po SET status=?, received_at=CASE WHEN ?='received' THEN ? ELSE received_at END WHERE id=?",
              (st, st, now, po["id"]))
    c.commit()
    if d:
        finance.event("purchase_received", round(abs(d.get("amount") or 0), 2), ref_type="po", ref_no=po["no"],
                      note=f"采购到货入库 {d['no']}", user=user, category=_po_category(c, po["id"]))
        try:                    # v2.51：采购模块记价格历史、更新耗材成本（模块关着就没人收）
            from .. import modules
            modules.emit("po.received", po_id=po["id"], lines=[{"line_id": k, "qty": v} for k, v in got.items()], user=user)
        except Exception:  # noqa: BLE001
            pass
    _auto_done(c, po["id"])
    return get_po(po["id"])


def _clean_issues(po, lines, issues):
    out = []
    by_id = {ln["id"]: ln for ln in lines}
    for x in issues or []:
        kind = str(x.get("kind") or "")
        if kind not in ISSUE_KINDS:
            raise ValueError("差异类型不对（少发 / 破损 / 发错 / 多发）")
        try:
            lid = int(x.get("line_id")) if x.get("line_id") not in (None, "") else None
            q = float(x.get("qty") or 0)
        except (TypeError, ValueError):
            raise ValueError("差异数量要是数字")
        if not math.isfinite(q) or q < 0:
            raise ValueError("差异数量要是数字")
        ln = by_id.get(lid) if lid else None
        if lid and not ln:
            raise ValueError("差异：采购单里没有这一行")
        if ln and ln["rolls"]:
            q = q * (ln["net_g"] or 1000)
        out.append({"line_id": lid, "item_id": ln["item_id"] if ln else x.get("item_id"), "kind": kind, "qty": q,
                    "note": str(x.get("note") or "")[:300]})
    return out


def resolve_issue(iid, resolution="", user=""):
    """到货差异处理好了（供应商补发 / 退款 / 不追了），写一句怎么处理的。"""
    c = db.conn()
    r = c.execute("SELECT * FROM inv_po_issues WHERE id=?", (int(iid),)).fetchone()
    if not r:
        raise ValueError("没有这条差异")
    c.execute("UPDATE inv_po_issues SET status='resolved', resolution=?, resolved_at=?, resolved_by=? WHERE id=?",
              (str(resolution or "")[:300], ledger._now(), user, r["id"]))
    c.commit()
    _auto_done(c, r["po_id"])
    return get_po(r["po_id"])


def issues(status="open"):
    sql = ("SELECT x.*, p.no, i.code, i.name_zh, i.name_th, i.unit FROM inv_po_issues x JOIN inv_po p ON p.id=x.po_id "
           "LEFT JOIN inv_items i ON i.id=x.item_id")
    args = []
    if status:
        sql += " WHERE x.status=?"
        args.append(status)
    out = []
    for r in db.conn().execute(sql + " ORDER BY x.id DESC LIMIT 300", args):
        d = dict(r)
        d["kind_zh"] = ISSUE_KINDS.get(d["kind"], d["kind"])
        out.append(d)
    return out


def return_goods(pid, qtys, note="", user=""):
    """v2.51 退货给供应商：{行id: 数量}（按卷的耗材填卷数）。开一张「采购退货」出库单（按到手成本出库，不算支出），
    这一行的「已退」加上去；全部退完 → 采购单「已退货」。供应商退的钱用 pay(refund=True) 记（负的付款）。"""
    c = db.conn()
    po = _po(c, pid)
    if po["status"] not in ("partial", "received", "done"):
        raise ValueError("到了货才能退货")
    rate = fee_rate(c, po)
    doc_lines, back = [], {}
    for ln in c.execute("SELECT * FROM inv_po_lines WHERE po_id=?", (po["id"],)).fetchall():
        v = (qtys or {}).get(str(ln["id"]), (qtys or {}).get(ln["id"]))
        if v in (None, "", 0, "0"):
            continue
        try:
            q = float(v) * ((ln["net_g"] or 1000) if ln["rolls"] else 1)
        except (TypeError, ValueError):
            raise ValueError("退货数量要是数字")
        can = (ln["received"] or 0) - (ln["returned"] or 0)
        if not math.isfinite(q) or q <= 0 or q > can + 1e-6:
            raise ValueError("退货数量不能比到了的多")
        doc_lines.append({"item_id": ln["item_id"], "qty": q, "unit_cost": round((ln["unit_cost"] or 0) * _fx(po) * (1 + rate), 6),
                          "po_line": ln["id"]})
        back[ln["id"]] = q
    if not doc_lines:
        raise ValueError("填一下退多少")
    d = docs.create("po_return", doc_lines, note or f"采购单 {po['no']} 退货给供应商", user, ref=f"poret:{po['no']}")
    for lid, q in back.items():
        c.execute("UPDATE inv_po_lines SET returned=COALESCE(returned,0)+? WHERE id=?", (q, lid))
    left = c.execute("SELECT SUM(COALESCE(received,0)-COALESCE(returned,0)) FROM inv_po_lines WHERE po_id=?", (po["id"],)).fetchone()[0] or 0
    if left <= 1e-6:
        c.execute("UPDATE inv_po SET status='returned' WHERE id=?", (po["id"],))
    c.commit()
    finance.event("purchase_received", -round(abs(d.get("amount") or 0), 2), ref_type="po", ref_no=po["no"],
                  note=f"退货给供应商 {d['no']}", user=user, category=_po_category(c, po["id"]))
    db.audit(user, "库存·采购退货", po["no"], d["no"])
    return get_po(po["id"])


def on_return_void(d, user=""):
    """采购退货单被作废：已退数量减回去。"""
    c = db.conn()
    po = c.execute("SELECT * FROM inv_po WHERE no=?", (d["ref"][6:],)).fetchone()
    if not po:
        return
    for dl in c.execute("SELECT qty, extra FROM inv_doc_lines WHERE doc_id=?", (d["id"],)).fetchall():
        try:
            pl = (json.loads(dl["extra"] or "{}") or {}).get("po_line")
        except ValueError:
            pl = None
        if pl:
            c.execute("UPDATE inv_po_lines SET returned=MAX(0, COALESCE(returned,0)-?) WHERE id=?", (abs(dl["qty"] or 0), pl))
    if po["status"] == "returned":
        c.execute("UPDATE inv_po SET status='received' WHERE id=?", (po["id"],))
    c.commit()
    amt = c.execute("SELECT COALESCE(SUM(amount),0) FROM inv_moves WHERE doc_id=? AND qty<0", (d["id"],)).fetchone()[0]
    if amt:
        finance.event("purchase_received", round(abs(amt), 2), ref_type="po", ref_no=po["no"], note=f"作废退货单 {d['no']}", user=user,
                      category=_po_category(c, po["id"]))


def on_receipt_void(d, amount, user=""):
    """v2.39：采购到货入库单被作废：已到数量减回去、状态退回「已下单 / 部分到货」、财务记一笔负的到货。"""
    c = db.conn()
    po = c.execute("SELECT * FROM inv_po WHERE no=?", (d["ref"][3:],)).fetchone()
    if not po:
        return
    lines = c.execute("SELECT id, qty, COALESCE(received,0) r FROM inv_po_lines WHERE po_id=?", (po["id"],)).fetchall()
    closed = po["status"] in ("received", "done") and any(ln["r"] < (ln["qty"] or 0) - 1e-9 for ln in lines)   # 手动「结单」过的
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
    if po["status"] in ("partial", "received", "done") and not closed:
        got = c.execute("SELECT SUM(COALESCE(received,0)) FROM inv_po_lines WHERE po_id=?", (po["id"],)).fetchone()[0] or 0
        c.execute("UPDATE inv_po SET status=?, received_at=NULL, done_at=NULL WHERE id=?", ("partial" if got > 1e-9 else "ordered", po["id"]))
    c.commit()
    if amount:
        finance.event("purchase_received", -round(amount, 2), ref_type="po", ref_no=po["no"],
                      note=f"作废到货入库单 {d['no']}", user=user, category=_po_category(c, po["id"]))


def _po_category(c, pid):
    cats = [r[0] for r in c.execute("SELECT DISTINCT i.category FROM inv_po_lines l JOIN inv_items i ON i.id=l.item_id WHERE l.po_id=?", (pid,))]
    return cats[0] if len(cats) == 1 else "mixed"


def pay(pid, amount, method="转账", day=None, note="", user="", refund=False):
    """记一笔付款（可以分好几次付）。refund=True：供应商退款（记成负的付款，财务也记负的）。"""
    c = db.conn()
    po = _po(c, pid)
    try:
        amt = round(float(amount), 2)
    except (TypeError, ValueError):
        raise ValueError("金额要是数字")
    if not math.isfinite(amt) or amt <= 0:       # v2.40：负数会把「已付」冲掉
        raise ValueError("付款金额要大于 0")
    if refund:
        paid = c.execute("SELECT COALESCE(SUM(amount),0) FROM inv_payments WHERE po_id=?", (po["id"],)).fetchone()[0]
        if amt > paid + 0.01:
            raise ValueError("退款不能比已经付的多")
        amt = -amt
    day = str(day or dt.date.today().isoformat())[:10]
    c.execute("INSERT INTO inv_payments(po_id, ts, day, amount, method, note, username) VALUES(?,?,?,?,?,?,?)",
              (po["id"], ledger._now(), day, amt, str(method or "")[:20], str(note or ("供应商退款" if refund else ""))[:200], user))
    c.commit()
    sup = c.execute("SELECT name FROM inv_suppliers WHERE id=?", (po["supplier_id"],)).fetchone() if po["supplier_id"] else None
    finance.event("purchase_payment", amt, ref_type="po", ref_no=po["no"],
                  note=f"{sup['name'] if sup else ''} {('供应商退款 ' if refund else '') + (note or '')}".strip(),
                  user=user, category=_po_category(c, po["id"]), day=day, method=method)
    db.audit(user, "库存·采购退款" if refund else "库存·采购付款", po["no"], f"{amt}")
    _auto_done(c, po["id"])
    return get_po(po["id"])


def get_po(pid):
    c = db.conn()
    po = _po(c, pid)
    d = dict(po)
    d["currency"] = d.get("currency") or "THB"
    fx = _fx(po)
    d["fx_rate"] = fx
    d["status_zh"] = STATUS.get(d["status"], d["status"])
    sup = c.execute("SELECT * FROM inv_suppliers WHERE id=?", (po["supplier_id"],)).fetchone() if po["supplier_id"] else None
    d["supplier"] = dict(sup) if sup else None
    d["lines"] = [dict(r) for r in c.execute("SELECT l.*, i.code, i.name_zh, i.name_th, i.unit, i.category, i.location FROM inv_po_lines l "
                                             "JOIN inv_items i ON i.id=l.item_id WHERE l.po_id=? ORDER BY l.id", (po["id"],))]
    rate = fee_rate(c, po)
    for x in d["lines"]:
        x["returned"] = x.get("returned") or 0
        x["landed"] = round((x["unit_cost"] or 0) * fx * (1 + rate), 6)        # 每单位到手成本（泰铢）
    final = d["status"] in FINAL
    # v2.40：结单（剩下的不要了）/ 取消：只付到了的那部分（以前结单后还按下单数量算，取消后到了的部分查不到）
    # v2.51：退货的数量不算；人民币的按汇率折成泰铢
    base = lambda x: max(0.0, ((x["received"] or 0) if final else (x["qty"] or 0)) - (x["returned"] or 0))   # noqa: E731
    goods_cur = sum(base(x) * (x["unit_cost"] or 0) for x in d["lines"])
    got = any((x["received"] or 0) > 0 for x in d["lines"])
    d["fees_counted"] = got or not final
    fees_cur = (po["ship_fee"] or 0) if d["fees_counted"] else 0
    fees_thb = ((po["other_fee"] or 0) + (po["tax_fee"] or 0)) if d["fees_counted"] else 0
    d["goods_total_cur"] = round(goods_cur, 2)
    d["total_cur"] = round(goods_cur + fees_cur, 2)            # 付给供应商的（下单货币）
    d["goods_total"] = round(goods_cur * fx, 2)
    d["total"] = round((goods_cur + fees_cur) * fx + fees_thb, 2)
    d["payments"] = [dict(r) for r in c.execute("SELECT * FROM inv_payments WHERE po_id=? ORDER BY id", (po["id"],))]
    d["paid"] = round(sum(p["amount"] for p in d["payments"]), 2)
    d["unpaid"] = round(max(0.0, d["total"] - d["paid"]), 2) if d["status"] != "draft" else 0.0
    d["pay_status"] = "paid" if d["paid"] >= d["total"] - 0.01 and d["total"] > 0 else ("partial" if d["paid"] > 0 else "unpaid")
    d["issues"] = [dict(r) | {"kind_zh": ISSUE_KINDS.get(r["kind"], r["kind"])}
                   for r in c.execute("SELECT * FROM inv_po_issues WHERE po_id=? ORDER BY id", (po["id"],))]
    d["issues_open"] = sum(1 for x in d["issues"] if x["status"] == "open")
    d["overdue_days"] = None
    if d["status"] in ("ordered", "partial") and d.get("expected_date"):
        try:
            d["overdue_days"] = (dt.date.today() - dt.date.fromisoformat(d["expected_date"])).days
        except ValueError:
            pass
    d["docs"] = [x for x in docs.list_docs("purchase", limit=50) if x.get("ref") == f"po:{po['no']}"]
    return d


def list_po(status="", days=None, supplier_id=None, q=""):
    """status：open 进行中（草稿、在途、部分到货）/ transit 在途 / unpaid 未付清 / paid 已付清 / overdue 过了预计到货 / 某个状态。"""
    sql, args = "SELECT id FROM inv_po", []
    conds = []
    if status == "open":
        conds.append("status IN ('draft','ordered','partial')")
    elif status in ("transit", "overdue"):
        conds.append("status IN ('ordered','partial')")
    elif status in ("unpaid", "paid"):
        conds.append("status NOT IN ('draft')")
    elif status:
        conds.append("status=?"); args.append(status)
    if days:
        conds.append("created_at>=?"); args.append(ledger._now() - float(days) * 86400)
    if supplier_id:
        conds.append("supplier_id=?"); args.append(int(supplier_id))
    if q:
        conds.append("(no LIKE ? OR tracking LIKE ? OR order_ref LIKE ? OR note LIKE ? OR id IN (SELECT l.po_id FROM inv_po_lines l "
                     "JOIN inv_items i ON i.id=l.item_id WHERE i.name_zh LIKE ? OR i.name_th LIKE ? OR i.code LIKE ?))")
        args += [f"%{q}%"] * 7
    sql += (" WHERE " + " AND ".join(conds) if conds else "") + " ORDER BY id DESC LIMIT 300"
    out = []
    for r in db.conn().execute(sql, args).fetchall():
        d = get_po(r["id"])
        d.pop("docs", None)
        if status == "unpaid" and d["unpaid"] <= 0.01:
            continue
        if status == "paid" and (d["unpaid"] > 0.01 or d["paid"] <= 0):
            continue
        if status == "overdue" and not (d["overdue_days"] is not None and d["overdue_days"] > 0):
            continue
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
    # v2.51：在途金额按汇率折成泰铢、带上分摊的运费 / 税（= 到了以后的到手成本）
    transit, overdue = 0.0, 0
    for r in c.execute("SELECT * FROM inv_po WHERE status IN ('ordered','partial')").fetchall():
        k = _fx(r) * (1 + fee_rate(c, r))
        transit += k * (c.execute("SELECT COALESCE(SUM((qty-COALESCE(received,0))*unit_cost),0) FROM inv_po_lines WHERE po_id=? "
                                  "AND qty>COALESCE(received,0)", (r["id"],)).fetchone()[0] or 0)
        if r["expected_date"] and r["expected_date"] < _dt.date.today().isoformat():
            overdue += 1
    unpaid = 0.0
    for r in c.execute("SELECT id FROM inv_po WHERE status IN ('ordered','partial','received','done','cancelled','returned')").fetchall():
        d = get_po(r["id"])
        unpaid += max(0.0, d["total"] - d["paid"])
    m0 = _dt.date.today().replace(day=1)
    start = _dt.datetime(m0.year, m0.month, 1).timestamp()
    rec = c.execute("SELECT COALESCE(SUM(amount),0) FROM inv_moves WHERE kind='purchase' AND ts>=?", (start,)).fetchone()[0]
    paid = c.execute("SELECT COALESCE(SUM(amount),0) FROM inv_payments WHERE day>=?", (m0.isoformat(),)).fetchone()[0]
    issues_n = c.execute("SELECT COUNT(*) FROM inv_po_issues WHERE status='open'").fetchone()[0]
    return {"open": open_n, "in_transit": round(transit, 2), "unpaid": round(unpaid, 2), "month_received": round(rec, 2),
            "month_paid": round(paid, 2), "month": m0.strftime("%Y-%m"), "overdue": overdue, "issues_open": issues_n}
