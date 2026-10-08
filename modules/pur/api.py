"""采购模块的接口（v2.30 从 web/inventory.py 搬过来）：采购单（下单、到货入库、付款）、补货建议、采购概况。
采购的数据（采购单表、在途数量、供应商）在内核的库存里（core/inventory/purchase.py），供应商资料接口 /api/inv/suppliers 也在内核（物品要用）。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403
from core import inventory as inv

bp = Blueprint("m_pur", __name__)
PREFIXES = ["/api/inv/po", "/api/inv/suggest"]      # /api/inv/po-summary 也算


@bp.get("/api/inv/po-summary")
def inv_po_summary():
    return jsonify({"ok": True, **inv.po_summary()})


@bp.get("/api/inv/po")
def inv_po_list():
    return jsonify({"ok": True, "po": inv.list_po(request.args.get("status") or "", request.args.get("days") or None),
                    "status": inv.PO_STATUS, "methods": inv.PAY_METHODS})


@bp.get("/api/inv/po/<pid>")
def inv_po_get(pid):
    try:
        return jsonify({"ok": True, "po": inv.get_po(pid)})
    except ValueError as e:
        return err(str(e), 404)


@bp.post("/api/inv/po")
def inv_po_save():
    if _need("inv.in"):
        return _need("inv.in")
    try:
        return jsonify({"ok": True, "po": inv.save_po(request.get_json(force=True) or {}, _uname())})
    except (TypeError, ValueError) as e:
        return err(str(e))


@bp.post("/api/inv/po/<int:pid>/<act>")
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


@bp.get("/api/inv/suggest")
def inv_suggest():
    return jsonify({"ok": True, "items": inv.suggest()})


@bp.post("/api/inv/suggest/po")
def inv_suggest_po():
    if _need("inv.in"):
        return _need("inv.in")
    pos = inv.po_from_suggest((request.get_json(force=True) or {}).get("item_ids") or [], _uname())
    return jsonify({"ok": True, "po": pos})
