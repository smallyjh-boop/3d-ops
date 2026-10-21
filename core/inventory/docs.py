"""库存单据：采购入库、退回入库、领用出库、报废、调整（开单即生效，开错了可以作废＝反向冲回），盘点（草稿 → 填实盘数 → 确认）。
每张单据有单号，确认后生成流水（ledger.post）。耗材的单据通过 materials 的函数改数量（料卷跟着变），流水带单号。"""
import datetime as dt
import json
import math

from .. import db
from . import ledger

DOC_KINDS = {"purchase": ("采购入库", "RK", 1), "return": ("退回入库", "TH", 1), "issue": ("领用出库", "LY", -1),
             "scrap": ("报废", "BF", -1), "adjust": ("调整", "TZ", 0), "stocktake": ("盘点", "PD", 0),
             "ship": ("订单出库", "CK", -1)}          # v2.35：订单发货时自动开（成品 + 纸箱 + 包材），见 modules/inv/shipout.py


def _no(c, kind):
    pre = DOC_KINDS[kind][1] + dt.datetime.now().strftime("%Y%m%d")
    n = c.execute("SELECT COUNT(*) FROM inv_docs WHERE no LIKE ?", (pre + "%",)).fetchone()[0] + 1
    no = f"{pre}-{n:02d}"
    while c.execute("SELECT 1 FROM inv_docs WHERE no=?", (no,)).fetchone():
        n += 1
        no = f"{pre}-{n:02d}"
    return no


def _fil_apply(it, kind, qty, unit_cost, doc_id, user, reason, printer="", extra=None):
    """耗材：调用 materials（料卷跟着变），流水由 materials 回调记（带单号）。qty 有正负。"""
    from .. import materials
    extra = extra or {}
    ctx = {"kind": kind, "doc_id": doc_id, "printer": printer or ""}
    if unit_cost not in (None, ""):
        ctx["unit_cost"] = float(unit_cost)
    with materials.context(**ctx):
        if kind == "purchase" and qty > 0 and extra.get("rolls"):
            materials.receive(it["material"], it["color"], int(extra["rolls"]), float(extra.get("net_g") or 1000),
                              extra.get("brand") or "", (float(unit_cost) * float(extra.get("net_g") or 1000)) if unit_cost not in (None, "") else None,
                              user)
        elif qty < 0:
            materials.consume(it["material"], it["color"], -qty, reason, user)
        else:
            materials.add_stock(it["material"], it["color"], qty / 1000.0, user, reason)


def _apply(c, it, kind, qty, unit_cost, doc_id, user, reason, printer="", extra=None):
    if it["category"] == "filament":
        c.commit()                       # materials 用同一个连接，自己提交
        _fil_apply(it, kind, qty, unit_cost, doc_id, user, reason, printer, extra)
    elif it["category"] == "goods":
        c.commit()
        from . import goods
        goods.apply(it, kind, qty, unit_cost, doc_id, user, reason)
    else:
        ledger.post(c, it["id"], kind, qty, unit_cost, reason, user, doc_id, "", printer)


def create(kind, lines, note="", user="", printer="", ref="", move_kind=None, allow_negative=False):
    """开单并生效。lines：[{item_id, qty（正数；调整单可正可负）, unit_cost, note, rolls, net_g, brand, move_kind}]。返回单据。
    move_kind：流水类型（默认和单据类型一样；发货自动扣包材用 pack；每一行也可以单独写，订单出库：成品 ship、纸箱包材 pack）。
    allow_negative：自动扣料不够时也扣（库存变负数，会提醒）。"""
    if kind not in DOC_KINDS or kind == "stocktake":
        raise ValueError("单据类型不对")
    sign = DOC_KINDS[kind][2]
    c = db.conn()
    clean = []
    so_far = {}           # v2.38：同一个物品写了好几行 → 累计起来看库存够不够
    for i, ln in enumerate(lines or []):
        it = ledger.get_item(ln.get("item_id"))
        if not it:
            raise ValueError(f"第 {i + 1} 行：没有这个物品")
        if not it["active"]:
            raise ValueError(f"第 {i + 1} 行：{it['name_zh']} 已停用")
        try:
            q = float(ln.get("qty") or 0)
            if ln.get("rolls") and it["category"] == "filament" and kind == "purchase":
                q = int(ln["rolls"]) * float(ln.get("net_g") or 1000)
        except (TypeError, ValueError):
            raise ValueError(f"第 {i + 1} 行：数量不对")
        if not math.isfinite(q):                      # v2.38："nan" / "inf" 会把库存写坏
            raise ValueError(f"第 {i + 1} 行：数量不对")
        if not q or (sign and q < 0):
            raise ValueError(f"第 {i + 1} 行：数量要大于 0")
        qty = q * sign if sign else q
        so_far[it["id"]] = so_far.get(it["id"], 0) + qty
        if qty < 0 and not allow_negative and it["category"] != "filament" and (it["qty"] or 0) + so_far[it["id"]] < -1e-6:
            raise ValueError(f"第 {i + 1} 行：{it['name_zh']} 库存只有 {it['qty']:g} {it['unit']}，不够出"
                             + ("（这张单里同一个物品有好几行，合起来算）" if so_far[it["id"]] != qty else ""))
        uc = ln.get("unit_cost")
        if uc not in (None, ""):
            uc = float(uc)
            if not math.isfinite(uc):
                raise ValueError(f"第 {i + 1} 行：单价不对")
            if uc < 0:
                raise ValueError(f"第 {i + 1} 行：单价不能是负数")
        clean.append((it, qty, uc, str(ln.get("note") or "")[:200], ln))
    if not clean:
        raise ValueError("至少要有一行")
    if kind in ("adjust", "scrap") and not str(note or "").strip():
        raise ValueError("调整 / 报废要写原因")
    no = _no(c, kind)
    now = ledger._now()
    doc_id = c.execute("INSERT INTO inv_docs(no, kind, status, note, printer, ref, created_by, created_at, done_by, done_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?)", (no, kind, "done", str(note or "")[:500], printer or "", ref or "",
                                                       user, now, user, now)).lastrowid
    for it, qty, uc, lnote, ln in clean:
        c.execute("INSERT INTO inv_doc_lines(doc_id, item_id, qty, unit_cost, note, extra) VALUES(?,?,?,?,?,?)",
                  (doc_id, it["id"], qty, uc, lnote, json.dumps({k: ln.get(k) for k in ("rolls", "net_g", "brand") if ln.get(k)})))
    c.commit()
    label = DOC_KINDS[kind][0]
    for it, qty, uc, lnote, ln in clean:
        _apply(c, it, ln.get("move_kind") or move_kind or kind, qty, uc, doc_id, user, f"{label} {no}" + (f"：{lnote or note}" if (lnote or note) else ""), printer,
               {k: ln.get(k) for k in ("rolls", "net_g", "brand")})
    _set_amount(c, doc_id)
    c.commit()
    db.audit(user, f"库存·{label}", no, f"{len(clean)} 行")
    return get(doc_id)


def _set_amount(c, doc_id):
    amt = c.execute("SELECT COALESCE(SUM(amount),0) FROM inv_moves WHERE doc_id=?", (doc_id,)).fetchone()[0]
    c.execute("UPDATE inv_docs SET amount=? WHERE id=?", (round(amt, 2), doc_id))


def void(doc_id, user=""):
    """作废：把这张单的流水全部反向冲回（数量、金额都回去），单据留着标「已作废」。"""
    c = db.conn()
    d = c.execute("SELECT * FROM inv_docs WHERE id=? OR no=?", (int(doc_id) if str(doc_id).isdigit() else -1, str(doc_id))).fetchone()
    if not d:
        raise ValueError("没有这张单")
    if d["status"] != "done":
        raise ValueError("只有已生效的单据能作废")
    if d["kind"] == "stocktake":
        raise ValueError("盘点单不能作废，数不对再开一张调整单")
    mv = c.execute("SELECT item_id, kind, SUM(qty) q, SUM(amount) a FROM inv_moves WHERE doc_id=? GROUP BY item_id, kind", (d["id"],)).fetchall()
    c.execute("UPDATE inv_docs SET status='void', void_by=?, void_at=? WHERE id=?", (user, ledger._now(), d["id"]))
    c.commit()
    for m in mv:
        it = ledger.get_item(m["item_id"])
        if not m["q"]:
            continue
        uc = (m["a"] / m["q"]) if m["q"] else None
        _apply(c, it, m["kind"], -m["q"], uc if m["q"] < 0 else uc, d["id"], user, f"作废 {d['no']}")
    c.commit()
    if (d["ref"] or "").startswith("po:"):       # v2.38：采购单的到货入库单作废 → 采购单的已到数量、状态、财务记录一起退回
        from . import purchase
        purchase.on_receipt_void(d, sum(abs(m["a"] or 0) for m in mv), user)
    db.audit(user, "库存·作废单据", d["no"], "")
    return get(d["id"])


# ---------------- 盘点 ----------------
def stocktake_start(category="", user="", note="", area="", codes=None):
    """开一张盘点单（草稿）：列出这个分类（空 = 全部）所有启用的物品和账面数。
    v2.35：按货架盘点——area 是区 / 货架 / 货位（例如 A1），codes 是里面的货位编号，只列放在这些格子里的物品。"""
    c = db.conn()
    sql, args = "SELECT * FROM inv_items WHERE active=1", []
    if category:
        sql += " AND category=?"
        args.append(category)
    if codes is not None:
        codes = list(codes)
        if not codes:
            raise ValueError("这里没有货位")
        sql += f" AND location IN ({','.join('?' * len(codes))})"
        args += codes
    items = c.execute(sql + (" ORDER BY location, code" if codes is not None else " ORDER BY category, code"), args).fetchall()
    if not items:
        raise ValueError("这里没有放东西" if codes is not None else "这个分类下没有物品")
    no = _no(c, "stocktake")
    now = ledger._now()
    doc_id = c.execute("INSERT INTO inv_docs(no, kind, status, category, note, ref, created_by, created_at) VALUES(?,?,?,?,?,?,?,?)",
                       (no, "stocktake", "draft", category or "", str(note or "")[:500], f"area:{area}" if area else "", user, now)).lastrowid
    for it in items:
        c.execute("INSERT INTO inv_doc_lines(doc_id, item_id, expected) VALUES(?,?,?)", (doc_id, it["id"], it["qty"] or 0))
    c.commit()
    db.audit(user, "库存·开始盘点", no, area or category or "全部")
    return get(doc_id)


def stocktake_save(doc_id, counts, user=""):
    """填实盘数（可以分几次填）。counts：{line_id: 数量 或 None（清空）}。"""
    c = db.conn()
    d = c.execute("SELECT * FROM inv_docs WHERE id=?", (int(doc_id),)).fetchone()
    if not d or d["kind"] != "stocktake" or d["status"] != "draft":
        raise ValueError("这张盘点单已经确认或不存在")
    for lid, v in (counts or {}).items():
        val = None if v in (None, "") else float(v)
        if val is not None and val < 0:
            raise ValueError("实盘数不能是负数")
        c.execute("UPDATE inv_doc_lines SET counted=? WHERE id=? AND doc_id=?", (val, int(lid), d["id"]))
    c.commit()
    return get(d["id"])


def stocktake_confirm(doc_id, user=""):
    """确认盘点：填了实盘数的行，按「实盘数 − 现在的账面数」调整（盘点期间有出入库也算对）；没填的跳过。"""
    c = db.conn()
    d = c.execute("SELECT * FROM inv_docs WHERE id=?", (int(doc_id),)).fetchone()
    if not d or d["kind"] != "stocktake" or d["status"] != "draft":
        raise ValueError("这张盘点单已经确认或不存在")
    lines = c.execute("SELECT * FROM inv_doc_lines WHERE doc_id=? AND counted IS NOT NULL", (d["id"],)).fetchall()
    if not lines:
        raise ValueError("还没有填任何实盘数")
    now = ledger._now()
    c.execute("UPDATE inv_docs SET status='done', done_by=?, done_at=? WHERE id=?", (user, now, d["id"]))
    c.commit()
    n = 0
    for ln in lines:
        it = ledger.get_item(ln["item_id"])
        diff = float(ln["counted"]) - float(it["qty"] or 0)
        c.execute("UPDATE inv_doc_lines SET qty=? WHERE id=?", (diff, ln["id"]))
        if abs(diff) < (0.5 if it["category"] == "filament" else 1e-6):
            continue
        n += 1
        if it["category"] == "filament":
            c.commit()
            from .. import materials
            with materials.context(kind="adjust", doc_id=d["id"]):
                materials.set_stock(it["material"], it["color"], float(ln["counted"]) / 1000.0, user)
        elif it["category"] == "goods":
            c.commit()
            from . import goods
            goods.set_count(it, float(ln["counted"]), d["id"], user)
        else:
            ledger.post(c, it["id"], "adjust", diff, None, f"盘点 {d['no']}", user, d["id"])
    _set_amount(c, d["id"])
    c.commit()
    db.audit(user, "库存·确认盘点", d["no"], f"{n} 个有差异")
    return get(d["id"])


def get(doc_id):
    c = db.conn()
    d = c.execute("SELECT * FROM inv_docs WHERE id=? OR no=?", (int(doc_id) if str(doc_id).isdigit() else -1, str(doc_id))).fetchone()
    if not d:
        return None
    out = dict(d)
    out["kind_zh"] = DOC_KINDS.get(d["kind"], (d["kind"],))[0]
    out["lines"] = []
    for ln in c.execute("SELECT l.*, i.code, i.name_zh, i.name_th, i.unit, i.category, i.qty AS now_qty, i.location FROM inv_doc_lines l "
                        "JOIN inv_items i ON i.id=l.item_id WHERE l.doc_id=? ORDER BY l.id", (d["id"],)):
        x = dict(ln)
        if d["kind"] == "stocktake" and x["counted"] is not None and d["status"] == "draft":
            x["diff"] = round(float(x["counted"]) - float(x["now_qty"] or 0), 3)
        out["lines"].append(x)
    return out


def list_docs(kind="", days=None, limit=200):
    sql, args = "SELECT * FROM inv_docs", []
    conds = []
    if kind:
        conds.append("kind=?"); args.append(kind)
    if days:
        conds.append("created_at>=?"); args.append(ledger._now() - float(days) * 86400)
    sql += (" WHERE " + " AND ".join(conds) if conds else "") + " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    out = []
    for r in db.conn().execute(sql, args):
        d = dict(r)
        d["kind_zh"] = DOC_KINDS.get(d["kind"], (d["kind"],))[0]
        d["lines_n"] = db.conn().execute("SELECT COUNT(*) FROM inv_doc_lines WHERE doc_id=?", (d["id"],)).fetchone()[0]
        out.append(d)
    return out
