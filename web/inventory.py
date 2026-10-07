"""库存管理（v2.17）的接口。只调用 core.inventory 的公开函数。"""
from web.common import *  # noqa: F401,F403
from core import inventory as inv

DOC_PERM = {"purchase": "inv.in", "return": "inv.in", "issue": "inv.out", "scrap": "inv.out", "adjust": "inv.adjust"}


def _perms():
    u = auth.current_user() or {}
    return {k: auth.has_perm(u, k) for k in ("inv.in", "inv.out", "inv.adjust", "inv.pay")} if u else {"inv.in": True, "inv.out": True, "inv.adjust": True, "inv.pay": True}


@app.get("/api/inv/po-summary")
def inv_po_summary():
    return jsonify({"ok": True, **inv.po_summary()})


@app.get("/api/inv/meta")
def inv_meta():
    return jsonify({"ok": True, "categories": inv.categories(), "units": inv.UNITS,
                    "kinds": {k: v[0] for k, v in inv.KINDS.items()}, "doc_kinds": {k: v[0] for k, v in inv.DOC_KINDS.items()},
                    "overview": inv.overview(), "alerts": inv.alerts(), "perms": _perms(),
                    "printers": [p.get("code") or p.get("name") for p in (load_config().get("printers") or [])]})


@app.get("/api/inv/items")
def inv_items():
    a = request.args
    return jsonify({"ok": True, "items": inv.items(a.get("category") or "", (a.get("q") or "").strip(), a.get("low") == "1", a.get("all") == "1")})


@app.get("/api/inv/items/<iid>")
def inv_item(iid):
    it = inv.get_item(iid)
    if not it:
        return err("没有这个物品", 404)
    return jsonify({"ok": True, "item": it, "moves": inv.moves(item_id=it["id"], limit=100)})


@app.post("/api/inv/items")
def inv_item_save():
    if _need("inv.in"):
        return _need("inv.in")
    try:
        it = inv.save_item(request.get_json(force=True) or {}, _uname())
    except (TypeError, ValueError) as e:
        return err(str(e))
    return jsonify({"ok": True, "item": it})


@app.post("/api/inv/presets")
def inv_presets():
    """补全常用物品（耗材常用颜色、备件、工具、包材）：已经有的不重复建。"""
    if _need("inv.in"):
        return _need("inv.in")
    return jsonify({"ok": True, "added": inv.seed_presets(_uname())})


@app.get("/api/inv/moves")
def inv_moves():
    a = request.args
    return jsonify({"ok": True, "moves": inv.moves(a.get("item_id"), a.get("kind") or None, a.get("days") or None,
                                                   min(int(a.get("limit") or 300), 2000), a.get("doc_id"))})


@app.get("/api/inv/docs")
def inv_docs():
    a = request.args
    return jsonify({"ok": True, "docs": inv.docs(a.get("kind") or "", a.get("days") or None)})


@app.get("/api/inv/docs/<did>")
def inv_doc(did):
    d = inv.doc(did)
    return jsonify({"ok": True, "doc": d}) if d else err("没有这张单", 404)


@app.post("/api/inv/docs")
def inv_doc_create():
    b = request.get_json(force=True) or {}
    key = DOC_PERM.get(b.get("kind"))
    if not key:
        return err("单据类型不对")
    if _need(key):
        return _need(key)
    try:
        d = inv.create_doc(b["kind"], b.get("lines") or [], b.get("note") or "", _uname(), b.get("printer") or "")
    except (TypeError, ValueError) as e:
        return err(str(e))
    return jsonify({"ok": True, "doc": d})


@app.post("/api/inv/docs/<did>/void")
def inv_doc_void(did):
    if _need("inv.adjust"):
        return _need("inv.adjust")
    try:
        return jsonify({"ok": True, "doc": inv.void_doc(did, _uname())})
    except ValueError as e:
        return err(str(e))


@app.post("/api/inv/stocktake")
def inv_stocktake_start():
    """开始盘点（有领用权限的员工就能开、能填数；确认要「盘点确认 / 调整」权限）。"""
    if _need("inv.out"):
        return _need("inv.out")
    b = request.get_json(force=True) or {}
    try:
        return jsonify({"ok": True, "doc": inv.stocktake_start(b.get("category") or "", _uname(), b.get("note") or "")})
    except ValueError as e:
        return err(str(e))


@app.post("/api/inv/stocktake/<int:did>/<act>")
def inv_stocktake_act(did, act):
    try:
        if act == "save":
            if _need("inv.out"):
                return _need("inv.out")
            d = inv.stocktake_save(did, (request.get_json(force=True) or {}).get("counts") or {}, _uname())
        elif act == "confirm":
            if _need("inv.adjust"):
                return _need("inv.adjust")
            d = inv.stocktake_confirm(did, _uname())
        else:
            return err("操作不对")
    except (TypeError, ValueError) as e:
        return err(str(e))
    return jsonify({"ok": True, "doc": d})


@app.get("/api/inv/expense")
def inv_expense():
    a = request.args
    return jsonify({"ok": True, **inv.expense(a.get("start") or None, a.get("end") or None, a.get("group") or "category")})


# ---------------- 采购（v2.18） ----------------
@app.get("/api/inv/suppliers")
def inv_suppliers():
    return jsonify({"ok": True, "suppliers": inv.suppliers(request.args.get("all") == "1")})


@app.post("/api/inv/suppliers")
def inv_supplier_save():
    if _need("inv.in"):
        return _need("inv.in")
    try:
        return jsonify({"ok": True, "supplier": inv.save_supplier(request.get_json(force=True) or {}, _uname())})
    except (TypeError, ValueError) as e:
        return err(str(e))


@app.get("/api/inv/po")
def inv_po_list():
    return jsonify({"ok": True, "po": inv.list_po(request.args.get("status") or "", request.args.get("days") or None),
                    "status": inv.PO_STATUS, "methods": inv.PAY_METHODS})


@app.get("/api/inv/po/<pid>")
def inv_po_get(pid):
    try:
        return jsonify({"ok": True, "po": inv.get_po(pid)})
    except ValueError as e:
        return err(str(e), 404)


@app.post("/api/inv/po")
def inv_po_save():
    if _need("inv.in"):
        return _need("inv.in")
    try:
        return jsonify({"ok": True, "po": inv.save_po(request.get_json(force=True) or {}, _uname())})
    except (TypeError, ValueError) as e:
        return err(str(e))


@app.post("/api/inv/po/<int:pid>/<act>")
def inv_po_act(pid, act):
    b = request.get_json(force=True, silent=True) or {}
    key = "inv.pay" if act == "pay" else "inv.in"
    if _need(key):
        return _need(key)
    try:
        if act == "receive":
            po = inv.receive_po(pid, b.get("qtys"), _uname(), b.get("note") or "")
        elif act == "pay":
            po = inv.pay_po(pid, b.get("amount"), b.get("method") or "转账", b.get("day"), b.get("note") or "", _uname())
        elif act in ("order", "cancel", "close", "tracking"):
            po = inv.po_action(pid, act, _uname(), b.get("tracking"))
        else:
            return err("操作不对")
    except (TypeError, ValueError) as e:
        return err(str(e))
    return jsonify({"ok": True, "po": po})


@app.get("/api/inv/suggest")
def inv_suggest():
    return jsonify({"ok": True, "items": inv.suggest()})


@app.post("/api/inv/suggest/po")
def inv_suggest_po():
    if _need("inv.in"):
        return _need("inv.in")
    pos = inv.po_from_suggest((request.get_json(force=True) or {}).get("item_ids") or [], _uname())
    return jsonify({"ok": True, "po": pos})


# ---------------- 财务模块对接（v2.18，对接规范第 11 条） ----------------
@app.get("/api/v1/finance/events")
def v1_finance_events():
    a = request.args
    return jsonify({"ok": True, "events": inv.finance_events(float(a.get("since") or 0), min(int(a.get("limit") or 1000), 5000),
                                                             a.get("kind") or "")})


@app.get("/api/v1/finance/inventory")
def v1_finance_inventory():
    try:
        return jsonify({"ok": True, **inv.finance_month(request.args.get("month") or None)})
    except ValueError:
        return err("month 要是 YYYY-MM")


@app.get("/api/inv/finance")
def inv_finance_ui():
    """库存页「财务」：最近的财务事件 + 本月汇总（和给财务模块的接口一样的数据）。"""
    if _need("inv.pay"):
        return _need("inv.pay")
    return jsonify({"ok": True, "events": list(reversed(inv.finance_events(0, 5000)))[:200], "month": inv.finance_month(request.args.get("month") or None)})
