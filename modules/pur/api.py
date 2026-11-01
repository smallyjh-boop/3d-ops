"""采购模块的接口（v2.30 从 web/inventory.py 搬过来；v2.51 加了 /api/inv/pur/…）。
采购单的数据（采购单表、在途数量、供应商、到货差异）在内核的库存里（core/inventory/purchase.py），供应商资料接口 /api/inv/suppliers 也在内核（物品要用）。
新接口都在 /api/inv/pur/ 下面：跟库存的接口一样，没有金额权限的员工看不到金额（web/common.py 的 _hide_inv_money）。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403
from web.common import _sees_inv_money
from core import inventory as inv

from .logic import analytics, links, quick, receiving, suggest
from .logic.store import ensure

bp = Blueprint("m_pur", __name__)
PREFIXES = ["/api/inv/po", "/api/inv/suggest", "/api/inv/pur/", "/print/pur-labels"]      # /api/inv/po-summary 也算


def _money():
    u = auth.current_user()
    return not u or u.get("role") == "api" or _sees_inv_money(u)


def _ok(**kw):
    return jsonify({"ok": True, **kw})


@bp.get("/api/inv/po-summary")
def inv_po_summary():
    ensure()
    return jsonify({"ok": True, **inv.po_summary()})


@bp.get("/api/inv/po")
def inv_po_list():
    ensure()
    a = request.args
    return jsonify({"ok": True, "po": inv.list_po(a.get("status") or "", a.get("days") or None, a.get("supplier") or None, (a.get("q") or "").strip()),
                    "status": inv.PO_STATUS, "methods": inv.PAY_METHODS, "issue_kinds": inv.PO_ISSUE_KINDS})


@bp.get("/api/inv/po/<pid>")
def inv_po_get(pid):
    ensure()
    try:
        return jsonify({"ok": True, "po": inv.get_po(pid)})
    except ValueError as e:
        return err(str(e), 404)


@bp.post("/api/inv/po")
def inv_po_save():
    if _need("inv.in"):
        return _need("inv.in")
    ensure()
    try:
        return jsonify({"ok": True, "po": inv.save_po(request.get_json(force=True) or {}, _uname())})
    except (TypeError, ValueError) as e:
        return err(str(e))


@bp.post("/api/inv/po/<int:pid>/<act>")
def inv_po_act(pid, act):
    b = request.get_json(force=True, silent=True) or {}
    key = "inv.pay" if act in ("pay", "refund") else "inv.in"
    if _need(key):
        return _need(key)
    ensure()
    try:
        if act == "receive":
            po = inv.receive_po(pid, b.get("qtys"), _uname(), b.get("note") or "", b.get("issues") or None)
        elif act in ("pay", "refund"):
            po = inv.pay_po(pid, b.get("amount"), b.get("method") or "转账", b.get("day"), b.get("note") or "", _uname(), refund=act == "refund")
        elif act == "return":
            po = inv.po_return(pid, b.get("qtys") or {}, b.get("note") or "", _uname())
        elif act in ("order", "cancel", "close", "tracking", "done"):
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


# ---------------- v2.51 ----------------
@bp.get("/api/inv/pur/overview")
def pur_overview():
    """页面顶上：数字卡片 + 每个页签的数量 + 供应商（下拉用）。"""
    ensure()
    s = inv.po_summary()
    sg = suggest.compute()["rows"]
    return _ok(summary=s, counts={"suggest_red": sum(1 for r in sg if r["urgency"] == "red"), "suggest": len(sg),
                                  "transit": len(inv.list_po("transit")), "issues": s.get("issues_open", 0)},
               suppliers=inv.suppliers(True), status=inv.PO_STATUS, methods=inv.PAY_METHODS, issue_kinds=inv.PO_ISSUE_KINDS,
               fx=inv.default_fx(), money=_money(), owner=(auth.current_user() or {"role": "owner"}).get("role") == "owner", perms={k: auth.has_perm(auth.current_user() or {"role": "owner"}, k)
                                                           for k in ("inv.in", "inv.pay", "inv.adjust")})


@bp.get("/api/inv/pur/suggest")
def pur_suggest():
    return _ok(**suggest.compute(request.args.get("all") == "1"))


@bp.post("/api/inv/pur/suggest/po")
def pur_suggest_po():
    if _need("inv.in"):
        return _need("inv.in")
    try:
        pos = suggest.create_pos((request.get_json(force=True) or {}).get("rows") or [], _uname())
    except (TypeError, ValueError) as e:
        return err(str(e))
    return _ok(po=pos)


@bp.get("/api/inv/pur/items")
def pur_items():
    """采购单表单用：物品 + 首选供应商 + 每个供应商的单价（按物品）。"""
    ensure()
    al = links.all_links()
    out = []
    for it in inv.items():
        if it["category"] == "goods":
            continue
        out.append({k: it.get(k) for k in ("id", "code", "name_zh", "name_th", "category", "unit", "supplier_id", "avg_cost", "qty", "transit")}
                   | {"links": [{k: x.get(k) for k in ("supplier_id", "price", "currency", "net_g", "moq", "pack_qty", "urls")} for x in al.get(it["id"], [])]})
    return _ok(items=out)


@bp.get("/api/inv/pur/items/<int:iid>/links")
def pur_item_links(iid):
    try:
        return _ok(**links.item_links(iid))
    except ValueError as e:
        return err(str(e), 404)


@bp.post("/api/inv/pur/links")
def pur_link_save():
    if _need("inv.in"):
        return _need("inv.in")
    try:
        return _ok(**links.save_link(request.get_json(force=True) or {}, _uname()))
    except (TypeError, ValueError) as e:
        return err(str(e))


@bp.post("/api/inv/pur/links/<int:lid>/delete")
def pur_link_delete(lid):
    if _need("inv.in"):
        return _need("inv.in")
    try:
        return _ok(**links.delete_link(lid, _uname()))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/inv/pur/items/<int:iid>/preferred")
def pur_item_preferred(iid):
    if _need("inv.in"):
        return _need("inv.in")
    try:
        return _ok(**links.set_preferred(iid, (request.get_json(force=True) or {}).get("supplier_id"), _uname()))
    except (TypeError, ValueError) as e:
        return err(str(e))


@bp.post("/api/inv/pur/suppliers/<int:sid>/delete")
def pur_supplier_delete(sid):
    if _need("inv.in"):
        return _need("inv.in")
    try:
        return _ok(**links.delete_supplier(sid, _uname()))
    except ValueError as e:
        return err(str(e))


@bp.get("/api/inv/pur/analytics")
def pur_analytics():
    if not _money():
        return err("采购分析只有老板和有「入库」或「付款」权限的员工能看", 403)
    return _ok(**analytics.overview(), costs=links.cost_changes(""), filament_cny_kg=load_config().get("filament_price_cny_per_kg"))


@bp.post("/api/inv/pur/costs/<int:cid>/<act>")
def pur_cost_act(cid, act):
    try:
        return _ok(change=links.cost_action(cid, act, _uname()))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/inv/pur/quick/parse")
def pur_quick_parse():
    if _need("inv.in"):
        return _need("inv.in")
    f = request.files.get("image")
    text = request.form.get("text") if request.form else None
    if text is None and request.is_json:
        text = (request.get_json(silent=True) or {}).get("text")
    try:
        return _ok(draft=quick.parse(text or "", f.read() if f else None))
    except (TypeError, ValueError) as e:
        return err(str(e))
    except Exception as e:  # noqa: BLE001  AI 出错（没填密钥、网络……）
        return err(f"AI 读取失败：{e}")


@bp.post("/api/inv/pur/quick/create")
def pur_quick_create():
    if _need("inv.in"):
        return _need("inv.in")
    try:
        return _ok(po=quick.create(request.get_json(force=True) or {}, _uname()))
    except (TypeError, ValueError) as e:
        return err(str(e))


@bp.get("/api/inv/pur/scan")
def pur_scan():
    try:
        return _ok(**receiving.scan(request.args.get("code")))
    except ValueError as e:
        return err(str(e))


@bp.get("/api/inv/pur/transit")
def pur_transit():
    return _ok(pos=receiving.open_pos())


@bp.post("/api/inv/pur/receive")
def pur_receive():
    if _need("inv.in"):
        return _need("inv.in")
    b = request.get_json(force=True) or {}
    try:
        return _ok(**receiving.receive(b.get("po_id"), b.get("qtys") or {}, b.get("issues") or [], b.get("locations") or {},
                                       b.get("note") or "", _uname()))
    except (TypeError, ValueError) as e:
        return err(str(e))


@bp.get("/api/inv/pur/issues")
def pur_issues():
    ensure()
    return _ok(issues=inv.po_issues(request.args.get("status", "open")))


@bp.post("/api/inv/pur/issues/<int:iid>/resolve")
def pur_issue_resolve(iid):
    if _need("inv.in"):
        return _need("inv.in")
    try:
        return _ok(po=inv.resolve_po_issue(iid, (request.get_json(force=True, silent=True) or {}).get("resolution") or "", _uname()))
    except ValueError as e:
        return err(str(e))


@bp.get("/print/pur-labels")
def pur_labels():
    a = request.args
    counts = {}
    for part in (a.get("lines") or "").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            try:
                counts[k.strip()] = int(float(v))
            except ValueError:
                pass
    try:
        html = receiving.labels_html(a.get("po") or "", counts or None, "th" if a.get("lang") == "th" else "zh")
    except ValueError as e:
        return err(str(e), 404)
    return app.response_class(html, mimetype="text/html")
