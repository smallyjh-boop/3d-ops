"""库存单据：采购入库、退回入库、领用出库、报废、调整（开单即生效，开错了可以作废＝反向冲回），盘点（草稿 → 填实盘数 → 确认）。
每张单据有单号，确认后生成流水（ledger.post）。耗材的单据通过 materials 的函数改数量（料卷跟着变），流水带单号。"""
import datetime as dt
import json
import math

from .. import db
from . import ledger, units

DOC_KINDS = {"purchase": ("采购入库", "RK", 1), "return": ("退回入库", "TH", 1), "issue": ("领用出库", "LY", -1),
             "scrap": ("报废", "BF", -1), "adjust": ("调整", "TZ", 0), "stocktake": ("盘点", "PD", 0),
             "ship": ("订单出库", "CK", -1),
             "po_return": ("采购退货", "TG", -1)}     # v2.51：退货给供应商（只能从采购单开，见 purchase.return_goods）          # v2.35：订单发货时自动开（成品 + 纸箱 + 包材），见 modules/inv/shipout.py


def _no(c, kind):
    pre = DOC_KINDS[kind][1] + dt.datetime.now().strftime("%Y%m%d")
    n = c.execute("SELECT COUNT(*) FROM inv_docs WHERE no LIKE ?", (pre + "%",)).fetchone()[0] + 1
    no = f"{pre}-{n:02d}"
    while c.execute("SELECT 1 FROM inv_docs WHERE no=?", (no,)).fetchone():
        n += 1
        no = f"{pre}-{n:02d}"
    return no


def _fil_apply(it, kind, qty, unit_cost, doc_id, user, reason, printer="", extra=None):
    """耗材：调用 materials（料卷跟着变），流水由 materials 回调记（带单号）。qty 有正负。
    v2.55 按卷：入库 / 退回 N 卷 = 新建 N 条料卷记录（每卷一个编号和标签）；领用 / 报废 N 卷 = 这 N 卷记用完。
    返回 {codes, grams}（按卷的才有）。"""
    from .. import materials
    extra = extra or {}
    ctx = {"kind": kind, "doc_id": doc_id, "printer": printer or ""}
    if unit_cost not in (None, ""):
        ctx["unit_cost"] = float(unit_cost)
    res = {}
    with materials.context(**ctx):
        if qty > 0 and extra.get("rolls") and kind in ("purchase", "return", "adjust"):
            net = float(extra.get("net_g") or 1000)
            res["codes"] = materials.receive(it["material"], it["color"], int(extra["rolls"]), net, extra.get("brand") or "",
                                             (float(unit_cost) * net) if unit_cost not in (None, "") else None, user,
                                             opened=bool(extra.get("opened")) and kind == "return", reason=reason)
            res["grams"] = int(extra["rolls"]) * net
        elif qty < 0 and extra.get("rolls") and kind in ("issue", "scrap", "adjust"):
            r = materials.take_rolls(it["material"], it["color"], int(extra["rolls"]), extra.get("spools") or None, user, reason)
            res.update(r)
            res["grams"] = -r["grams"]
        elif qty < 0:
            materials.consume(it["material"], it["color"], -qty, reason, user)
        else:
            materials.add_stock(it["material"], it["color"], qty / 1000.0, user, reason)
    return res


def _apply(c, it, kind, qty, unit_cost, doc_id, user, reason, printer="", extra=None):
    if it["category"] == "filament":
        c.commit()                       # materials 用同一个连接，自己提交
        return _fil_apply(it, kind, qty, unit_cost, doc_id, user, reason, printer, extra)
    elif it["category"] == "goods":
        c.commit()
        from . import goods
        goods.apply(it, kind, qty, unit_cost, doc_id, user, reason)
    else:
        ledger.post(c, it["id"], kind, qty, unit_cost, reason, user, doc_id, "", printer)
    return {}


def create(kind, lines, note="", user="", printer="", ref="", move_kind=None, allow_negative=False):
    """开单并生效。lines：[{item_id, qty（正数；调整单可正可负）, unit_cost, note, rolls, net_g, brand, move_kind}]。返回单据。
    move_kind：流水类型（默认和单据类型一样；发货自动扣包材用 pack；每一行也可以单独写，订单出库：成品 ship、纸箱包材 pack）。
    allow_negative：自动扣料不够时也扣（库存变负数，会提醒）。"""
    if kind not in DOC_KINDS or kind == "stocktake":
        raise ValueError("单据类型不对")
    sign = DOC_KINDS[kind][2]
    c = db.conn()
    clean = []
    so_far = {}           # v2.39：同一个物品写了好几行 → 累计起来看库存够不够
    so_rolls = {}
    for i, ln in enumerate(lines or []):
        it = ledger.get_item(ln.get("item_id"))
        if not it:
            raise ValueError(f"第 {i + 1} 行：没有这个物品")
        if not it["active"]:
            raise ValueError(f"第 {i + 1} 行：{it['name_zh']} 已停用")
        rolled = bool(ln.get("rolls")) and it["category"] == "filament" and kind in ("purchase", "return", "issue", "scrap")
        try:
            q = float(ln.get("qty") or 0)
            if rolled:                                  # v2.55：按卷填（卷数 × 每卷净重，没填净重 = 物品的默认）
                nr = float(ln["rolls"])
                if nr != int(nr) or nr < 1:
                    raise ValueError(f"第 {i + 1} 行：卷数要填整数")
                ln = dict(ln, rolls=int(nr), net_g=float(ln.get("net_g") or units.roll_g_of(it)))
                q = ln["rolls"] * ln["net_g"]
        except (TypeError, ValueError) as e:
            raise ValueError(str(e) if str(e).startswith("第") else f"第 {i + 1} 行：数量不对")
        if not math.isfinite(q):                      # v2.39："nan" / "inf" 会把库存写坏
            raise ValueError(f"第 {i + 1} 行：数量不对")
        if not q or (sign and q < 0):
            raise ValueError(f"第 {i + 1} 行：数量要大于 0")
        qty = q * sign if sign else q
        so_far[it["id"]] = so_far.get(it["id"], 0) + qty
        if qty < 0 and not allow_negative and it["category"] != "filament" and (it["qty"] or 0) + so_far[it["id"]] < -1e-6:
            raise ValueError(f"第 {i + 1} 行：{it['name_zh']} 库存只有 {it['qty']:g} {it['unit']}，不够出"
                             + ("（这张单里同一个物品有好几行，合起来算）" if so_far[it["id"]] != qty else ""))
        if rolled and qty < 0:                           # 整卷出库：够不够卷（在机上的不算，先下机）先看清楚，别开了单再报错
            so_rolls[it["id"]] = so_rolls.get(it["id"], 0) + ln["rolls"]
            st = units.spool_stats().get((it["material"], it["color"])) or {"sealed": 0, "open": 0}
            if ln.get("spools"):                         # v2.55.0：指定了哪几卷 → 开单前全部查清楚（料号颜色、用完 / 在机上、卷数对得上、没重复）
                sp = [str(x).strip() for x in (ln["spools"] if isinstance(ln["spools"], (list, tuple)) else [ln["spools"]]) if str(x).strip()]
                if len(sp) != ln["rolls"]:
                    raise ValueError(f"第 {i + 1} 行：写了 {ln['rolls']} 卷，但指定的料卷编号有 {len(sp)} 个")
                if len({x.upper() for x in sp}) != len(sp):
                    raise ValueError(f"第 {i + 1} 行：料卷编号有重复")
                from .. import materials
                try:
                    materials.check_take(it["material"], it["color"], sp)
                except ValueError as e:
                    raise ValueError(f"第 {i + 1} 行：{e}")
                ln = dict(ln, spools=sp)
            elif so_rolls[it["id"]] > st["sealed"] + st["open"]:
                raise ValueError(f"第 {i + 1} 行：{it['name_zh']} 在库的只有 {st['sealed'] + st['open']} 卷（在机上的要先下机），不够出 {so_rolls[it['id']]} 卷")
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
    line_ids = []
    for it, qty, uc, lnote, ln in clean:
        line_ids.append(c.execute("INSERT INTO inv_doc_lines(doc_id, item_id, qty, unit_cost, note, extra) VALUES(?,?,?,?,?,?)",
                                  (doc_id, it["id"], qty, uc, lnote,
                                   json.dumps({k: ln.get(k) for k in ("rolls", "net_g", "brand", "po_line", "opened") if ln.get(k)}))).lastrowid)
    c.commit()
    label = DOC_KINDS[kind][0]
    done = []                                           # v2.55.0：已经生效的行；中途哪一行失败 → 前面的全部冲回，单据标作废，不留「已完成但没生效」的单
    try:
        for (it, qty, uc, lnote, ln), lid in zip(clean, line_ids):
            res = _apply(c, it, ln.get("move_kind") or move_kind or kind, qty, uc, doc_id, user,
                         f"{label} {no}" + (f"：{lnote or note}" if (lnote or note) else ""), printer,
                         {k: ln.get(k) for k in ("rolls", "net_g", "brand", "opened", "spools")})
            done.append((it, qty, uc, ln, lid, res))
            if res.get("codes"):                       # 每卷的编号记在这一行里（标签、追溯用）；整卷出库的克数以实际那几卷为准
                ex = {k: ln.get(k) for k in ("rolls", "net_g", "brand", "po_line", "opened") if ln.get(k)}
                ex["spools"] = res["codes"]
                if res.get("prev"):
                    ex["prev"] = res["prev"]           # 每卷拿走前的状态和剩余克数，作废时原样放回
                c.execute("UPDATE inv_doc_lines SET qty=?, extra=? WHERE id=?", (res["grams"], json.dumps(ex), lid))
    except Exception as e:  # noqa: BLE001
        _rollback_applied(c, done, kind, doc_id, no, user)
        c.execute("UPDATE inv_docs SET status='void', void_by=?, void_at=?, note=? WHERE id=?",
                  (user, ledger._now(), (str(note or "") + f" [开单失败已回滚：{e}]")[:500], doc_id))
        c.commit()
        raise
    _set_amount(c, doc_id)
    c.commit()
    db.audit(user, f"库存·{label}", no, f"{len(clean)} 行")
    return get(doc_id)


def _rollback_applied(c, done, kind, doc_id, no, user):
    """开单中途失败：把已经生效的行冲回（整卷的按卷放回 / 作废，其他按数量反向）。"""
    for it, qty, uc, ln, lid, res in reversed(done):
        try:
            if res.get("codes") and it["category"] == "filament":
                from .. import materials
                with materials.context(kind=kind, doc_id=doc_id):
                    if qty > 0:
                        materials.discard_rolls(it["material"], it["color"], res["codes"], user, f"开单失败回滚 {no}")
                    elif res.get("prev"):
                        materials.restore_rolls(it["material"], it["color"], res["prev"], user, f"开单失败回滚 {no}")
            else:
                _apply(c, it, kind, -qty, uc, doc_id, user, f"开单失败回滚 {no}")
        except Exception as e2:  # noqa: BLE001  回滚本身失败：记下来，别吞掉原来的错误
            import logging
            logging.getLogger("3dops").error("单据 %s 回滚失败：%s", no, e2)


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
    # v2.55.0：按卷的行（有料卷编号）要精确冲回：入库的那几卷记用完、出库的那几卷原样放回；先全部查清楚能不能冲，不能就整张不动
    rolled_lines = []
    for ln in c.execute("SELECT l.*, i.category, i.material, i.color, i.name_zh FROM inv_doc_lines l JOIN inv_items i ON i.id=l.item_id WHERE l.doc_id=?", (d["id"],)):
        try:
            ex = json.loads(ln["extra"] or "null") or {}
        except ValueError:
            ex = {}
        if ln["category"] != "filament" or not ex.get("spools"):
            continue
        if ln["qty"] > 0:
            for cd in ex["spools"]:
                sp = c.execute("SELECT status, remaining_g, net_g FROM spools WHERE code=?", (cd,)).fetchone()
                if not sp or sp["status"] not in ("sealed", "open") or float(sp["remaining_g"] or 0) < float(sp["net_g"] or 0) - 0.5:
                    raise ValueError(f"{ln['name_zh']} 入库的 {cd} 已经用过 / 上机 / 用完了，不能作废。先处理那一卷（或开调整单）")
        else:
            if not ex.get("prev"):
                raise ValueError(f"{ln['name_zh']} 是旧版本开的整卷出库，没有记下每卷原来的状态，不能作废。请开「退回入库」单把这几卷放回来")
            for p_ in ex["prev"]:
                sp = c.execute("SELECT status FROM spools WHERE code=?", (p_["code"],)).fetchone()
                if not sp or sp["status"] != "empty":
                    raise ValueError(f"{ln['name_zh']} 出库的 {p_['code']} 已经不是「用完」状态，不能作废")
        rolled_lines.append((ln, ex))
    rolled = {}                                         # 物品 → 已经按卷冲回的克数（带正负）
    for ln, ex in rolled_lines:
        from .. import materials
        am = abs(sum(m_["a"] or 0 for m_ in mv if m_["item_id"] == ln["item_id"]))
        qsum = abs(sum(m_["q"] or 0 for m_ in mv if m_["item_id"] == ln["item_id"])) or 1
        with materials.context(kind=d["kind"], doc_id=d["id"], **({"unit_cost": am / qsum} if am else {})):
            if ln["qty"] > 0:
                r = materials.discard_rolls(ln["material"], ln["color"], ex["spools"], user, f"作废 {d['no']}")
                rolled[ln["item_id"]] = rolled.get(ln["item_id"], 0.0) + r["grams"]
            else:
                r = materials.restore_rolls(ln["material"], ln["color"], ex["prev"], user, f"作废 {d['no']}")
                rolled[ln["item_id"]] = rolled.get(ln["item_id"], 0.0) - r["grams"]
    c.execute("UPDATE inv_docs SET status='void', void_by=?, void_at=? WHERE id=?", (user, ledger._now(), d["id"]))   # 按卷冲回都成功了才标作废
    c.commit()
    for m in mv:
        it = ledger.get_item(m["item_id"])
        q = m["q"] or 0
        if not q:
            continue
        r = rolled.get(m["item_id"], 0.0)
        if r and q * r > 0:                              # 这部分已经按卷冲回了，只冲剩下的（同一单里还有按克的行）
            cut = min(abs(q), abs(r)) * (1 if q > 0 else -1)
            rolled[m["item_id"]] = r - cut
            q -= cut
            if abs(q) < 1e-6:
                continue
        uc = (m["a"] / m["q"]) if m["q"] else None
        _apply(c, it, m["kind"], -q, uc, d["id"], user, f"作废 {d['no']}")
    c.commit()
    if (d["ref"] or "").startswith("po:"):       # v2.39：采购单的到货入库单作废 → 采购单的已到数量、状态、财务记录一起退回
        from . import purchase
        purchase.on_receipt_void(d, sum(abs(m["a"] or 0) for m in mv), user)
    elif (d["ref"] or "").startswith("poret:"):  # v2.51：采购退货单作废 → 采购单的已退数量退回
        from . import purchase
        purchase.on_return_void(d, user)
    db.audit(user, "库存·作废单据", d["no"], "")
    return get(d["id"])


# ---------------- 盘点 ----------------
def stocktake_start(category="", user="", note="", area="", codes=None, item_ids=None, allow_empty=False):
    """开一张盘点单（草稿）：列出这个分类（空 = 全部）所有启用的物品和账面数。
    v2.35：按货架盘点——area 是区 / 货架 / 货位（例如 A1），codes 是里面的货位编号，只列放在这些格子里的物品。
    v2.52：按货位盘点（库存模块）——item_ids 给出要列的物品；allow_empty = 一个物品都没有也开（数空货位）。"""
    c = db.conn()
    sql, args = "SELECT * FROM inv_items WHERE active=1", []
    if item_ids is not None:
        ids = [int(x) for x in item_ids] or [-1]
        sql += f" AND id IN ({','.join('?' * len(ids))})"
        args += ids
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
    if not items and not allow_empty:
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


def resolve_count(it, v, book_g=None, book_rolls=None, tare=None):
    """盘点填的一个数 → (实盘克数或数量, extra)。普通数 = 物品单位的数量；
    v2.55 耗材可以填 {"rolls": 数到几卷} 或 {"weigh": [{code, gross, tare?}]}（每卷称毛重，减去空料盘 = 净重）或 {"grams": 克}。
    book_g / book_rolls：这次盘的范围（整个物品，或者一个货位）里账面的克数和卷数，不给 = 整个物品。"""
    if not isinstance(v, dict):
        return (None if v in (None, "") else _num(v)), None
    if it["category"] != "filament":
        raise ValueError("只有耗材能按卷数 / 称重盘点")
    stats = units.spool_stats().get((it["material"], it["color"])) or {"rolls": 0, "grams": 0.0, "sealed": 0, "open": 0}
    bg = float(it["qty"] or 0) if book_g is None else float(book_g)
    br = units.shelf_rolls(stats) if book_rolls is None else book_rolls     # v2.55.0：账面卷数不含在机上的（盘点数的是架子上的）
    if "rolls" in v:
        if v["rolls"] in (None, ""):
            return None, None
        n = _num(v["rolls"])
        if n != int(n):
            raise ValueError("卷数要填整数（半卷的称重）")
        return round(units.rolls_to_grams(it, n, bg, br), 3), {"mode": "rolls", "rolls": int(n), "sys_rolls": int(br)}
    if "weigh" in v:
        from .. import materials
        ents, before, after = [], 0.0, 0.0
        t0 = units.tare_g() if tare in (None, "") else float(tare)
        for e in v["weigh"] or []:
            if e.get("gross") in (None, ""):
                continue
            sp = materials.spool_get(e.get("code"))
            if not sp or (sp["material"], sp["color"]) != (it["material"], it["color"]):
                raise ValueError(f"{e.get('code')} 不是 {it['material']} {it['color']} 的料卷")
            g = _num(e["gross"])
            if g > 20000:
                raise ValueError("毛重要填 0–20000 克")
            t = t0 if e.get("tare") in (None, "") else _num(e["tare"])
            net = round(max(0.0, g - t), 1)
            before += max(0.0, float(sp["remaining_g"] or 0))
            after += net
            ents.append({"code": sp["code"], "gross": g, "tare": t, "net": net})
        if not ents:
            return None, None
        return round(max(0.0, bg - before + after), 3), {"mode": "weigh", "spools": ents}
    if "grams" in v:
        return (None if v["grams"] in (None, "") else _num(v["grams"])), None
    raise ValueError("盘点的数不对")


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):      # v2.41：以前把 Python 的原始报错丢给用户
        raise ValueError(f"实盘数「{v}」要填数字")
    if not math.isfinite(x) or x < 0:
        raise ValueError(f"实盘数「{v}」要填 0 或正数")
    return x


def stocktake_save(doc_id, counts, user=""):
    """填实盘数（可以分几次填）。counts：{line_id: 数量 或 None（清空）}；耗材还可以 {rolls: 几卷} / {weigh: [{code, gross}]}。"""
    c = db.conn()
    d = c.execute("SELECT * FROM inv_docs WHERE id=?", (int(doc_id),)).fetchone()
    if not d or d["kind"] != "stocktake" or d["status"] != "draft":
        raise ValueError("这张盘点单已经确认或不存在")
    for lid, v in (counts or {}).items():
        ln = c.execute("SELECT item_id FROM inv_doc_lines WHERE id=? AND doc_id=?", (int(lid), d["id"])).fetchone()
        if not ln:
            continue
        val, ex = resolve_count(ledger.get_item(ln["item_id"]), v)
        c.execute("UPDATE inv_doc_lines SET counted=?, extra=? WHERE id=? AND doc_id=?", (val, json.dumps(ex) if ex else None, int(lid), d["id"]))
    c.commit()
    return get(d["id"])


def stocktake_confirm(doc_id, user="", loc_hook=None):
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
        ex = json.loads(ln["extra"]) if ln["extra"] else {}
        q0 = float(it["qty"] or 0)
        diff = float(ln["counted"]) - q0
        if it["category"] == "filament" and ex.get("mode"):
            if _confirm_fil(c, it, ex, d, user, loc_hook):
                n += 1
            c.execute("UPDATE inv_doc_lines SET qty=?, extra=? WHERE id=?",
                      (float(ledger.get_item(it["id"])["qty"] or 0) - q0, json.dumps(ex), ln["id"]))
            continue
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


def _pick_shelf(c, it, n):
    """从架子上（整卷 + 开封，不含在机上）按「先整卷、再剩得少的」挑 n 卷的编号。"""
    rows = c.execute("SELECT code FROM spools WHERE material=? AND color=? AND status IN ('sealed','open') AND (status='sealed' OR remaining_g>0) "
                     "ORDER BY CASE status WHEN 'sealed' THEN 0 ELSE 1 END, CASE status WHEN 'open' THEN remaining_g ELSE 0 END, id",
                     (it["material"], it["color"])).fetchall()
    return [r["code"] for r in rows[:n]]


def _confirm_fil(c, it, ex, d, user, loc_hook=None):
    """耗材按卷数 / 称重盘点的确认：多出来的卷建成新料卷（带编号标签），少了的卷记用完；称重的把那几卷剩余克数改成净重。返回有没有差异。
    v2.55.0：卷数差异按「确认这一刻」架子上的卷数重算（盘点期间有出入库也对），变了的写进 ex["warn"]；在机上的不算少；
    按货位盘的（ex.by_loc）交给库存模块的 loc_hook，只动数的那个货位。"""
    from .. import materials
    c.commit()
    changed = False
    with materials.context(kind="adjust", doc_id=d["id"]):
        if ex["mode"] == "rolls":
            if ex.get("by_loc") and loc_hook:
                return bool(loc_hook(c, it, ex, d, user))
            cur = units.shelf_rolls(units.spool_stats().get((it["material"], it["color"])))
            if ex.get("by_loc"):
                delta = int(ex.get("delta_rolls", 0))
            else:
                delta = int(ex.get("rolls", 0)) - cur
                if int(ex.get("sys_rolls", cur)) != cur:
                    ex["warn"] = {"was": int(ex.get("sys_rolls")), "now": cur, "done": True}      # 盘点期间账面变了，已按现在的算
            if delta > 0:
                materials.receive(it["material"], it["color"], delta, units.roll_g_of(it), "", None, user, reason=f"盘点 {d['no']} 多 {delta} 卷")
                changed = True
            elif delta < 0:
                have = len(_pick_shelf(c, it, 10 ** 6))
                if have < -delta:
                    raise ValueError(f"{it['name_zh']} 架子上只有 {have} 卷，没法再少 {-delta} 卷（在机上的要先下机）")
                materials.take_rolls(it["material"], it["color"], -delta, None, user, f"盘点 {d['no']} 少")
                changed = True
        elif ex["mode"] == "weigh":
            for e in ex.get("spools") or []:
                sp = materials.spool_get(e["code"])
                if sp and abs(float(sp["remaining_g"] or 0) - e["net"]) >= 0.5:
                    materials.spool_action(sp["id"], "weigh", user, grams=e["net"])
                    changed = True
    return changed


def get(doc_id):
    c = db.conn()
    d = c.execute("SELECT * FROM inv_docs WHERE id=? OR no=?", (int(doc_id) if str(doc_id).isdigit() else -1, str(doc_id))).fetchone()
    if not d:
        return None
    out = dict(d)
    out["kind_zh"] = DOC_KINDS.get(d["kind"], (d["kind"],))[0]
    out["lines"] = []
    for ln in c.execute("SELECT l.*, i.code, i.name_zh, i.name_th, i.unit, i.category, i.material, i.color, i.qty AS now_qty, i.location FROM inv_doc_lines l "
                        "JOIN inv_items i ON i.id=l.item_id WHERE l.doc_id=? ORDER BY l.id", (d["id"],)):
        x = dict(ln)
        try:
            ex = json.loads(x.get("extra") or "null") or {}
        except ValueError:
            ex = {}
        x["spools"] = ex.get("spools") or []
        x["rolls"] = ex.get("rolls") if d["kind"] != "stocktake" else None
        x["net_g"] = ex.get("net_g")
        if d["kind"] == "stocktake":
            x["count_mode"] = ex.get("mode") or ""
            x["counted_rolls"] = ex.get("rolls") if ex.get("mode") == "rolls" else None
        if x.get("category") == "filament":
            x["units"] = _line_units(c, x["item_id"])
            if x["units"]:
                x["shelf_rolls"] = x["units"]["sealed"] + x["units"]["open"]       # v2.55.0：盘点的账面卷数（不含在机上的）
            x["warn"] = ex.get("warn") or None
            if d["kind"] == "stocktake" and d["status"] == "draft" and ex.get("mode") == "rolls" and x.get("shelf_rolls") is not None \
                    and ex.get("sys_rolls") is not None and int(ex["sys_rolls"]) != x["shelf_rolls"]:
                x["warn"] = {"was": int(ex["sys_rolls"]), "now": x["shelf_rolls"], "done": False}
        if d["kind"] == "stocktake" and x["counted"] is not None and d["status"] == "draft":
            x["diff"] = round(float(x["counted"]) - float(x["now_qty"] or 0), 3)
        out["lines"].append(x)
    out["spool_codes"] = [cd for x in out["lines"] for cd in x["spools"]]       # v2.55：这张单进出的料卷（打标签用）
    return out


def _line_units(c, item_id):
    r = c.execute("SELECT * FROM inv_items WHERE id=?", (item_id,)).fetchone()
    return units.for_item(dict(r)) if r else None


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
