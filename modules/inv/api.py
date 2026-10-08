"""库存模块的接口：物品、单据、盘点、流水、库存报表、给财务的事件。v2.31 从 web/inventory.py 搬过来。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403
from core import inventory as inv

bp = Blueprint("m_inv", __name__)


def _views():
    from modules.inv import views
    return views
PREFIXES = ['/api/inv/', '/api/v1/finance/events', '/api/v1/finance/inventory', '/print/inv-locations']
PATTERNS = []


from core import inventory as inv


DOC_PERM = {"purchase": "inv.in", "return": "inv.in", "issue": "inv.out", "scrap": "inv.out", "adjust": "inv.adjust"}


def _perms():
    u = auth.current_user() or {}
    return {k: auth.has_perm(u, k) for k in ("inv.in", "inv.out", "inv.adjust", "inv.pay")} if u else {"inv.in": True, "inv.out": True, "inv.adjust": True, "inv.pay": True}


@bp.get("/api/inv/meta")
def inv_meta():
    return jsonify({"ok": True, "categories": inv.categories(), "units": inv.UNITS,
                    "kinds": {k: v[0] for k, v in inv.KINDS.items()}, "doc_kinds": {k: v[0] for k, v in inv.DOC_KINDS.items()},
                    "overview": inv.overview(), "alerts": _views().alerts(), "perms": _perms(),
                    "printers": [p.get("code") or p.get("name") for p in (load_config().get("printers") or [])]})


@bp.get("/api/inv/items")
def inv_items():
    a = request.args
    if a.get("view"):            # v2.32：库存 / 物品资料 / 没库存 / 已停用
        from modules.inv import views
        return jsonify({"ok": True, "items": views.listing(a.get("view"), a.get("category") or "", (a.get("q") or "").strip()),
                        "counts": views.counts()})
    return jsonify({"ok": True, "items": inv.items(a.get("category") or "", (a.get("q") or "").strip(), a.get("low") == "1", a.get("all") == "1")})


@bp.get("/api/inv/items/<iid>")
def inv_item(iid):
    it = inv.get_item(iid)
    if not it:
        return err("没有这个物品", 404)
    from modules.inv import locations
    loc = locations.get_loc(it["location"]) if it.get("location") else None
    return jsonify({"ok": True, "item": it, "moves": inv.moves(item_id=it["id"], limit=100),
                    "loc": {"code": loc["code"] if loc else "", "id": loc["id"] if loc else None,          # v2.35：一物一位
                            "human_zh": locations.human(loc["code"]) if loc else "", "human_th": locations.human(loc["code"], "th") if loc else "",
                            "missing": bool(it.get("location") and not loc),
                            "suggest": None if loc else locations.suggest(it["category"])}})


@bp.post("/api/inv/items")
def inv_item_save():
    if _need("inv.in"):
        return _need("inv.in")
    b = request.get_json(force=True) or {}
    try:
        if "location" in b:                      # v2.35：货位要是建好的格子（a1-2-3 也认），空 = 没货位
            from modules.inv import locations
            raw = str(b.get("location") or "").strip()
            old = inv.get_item(int(b["id"])) if b.get("id") else None
            if not (old and raw == (old.get("location") or "")):     # 没改就不检查
                loc = locations.get_loc(raw) if raw else None
                if raw and not loc:
                    raise ValueError(f"没有货位 {raw}（先在「货位」里建好货架，或者留空）")
                b["location"] = loc["code"] if loc else ""
        it = inv.save_item(b, _uname())
    except (TypeError, ValueError) as e:
        return err(str(e))
    return jsonify({"ok": True, "item": it})


@bp.post("/api/inv/presets")
def inv_presets():
    """补全常用物品（耗材常用颜色、备件、工具、包材）：已经有的不重复建。"""
    if _need("inv.in"):
        return _need("inv.in")
    return jsonify({"ok": True, "added": inv.seed_presets(_uname())})


@bp.get("/api/inv/moves")
def inv_moves():
    a = request.args
    return jsonify({"ok": True, "moves": inv.moves(a.get("item_id"), a.get("kind") or None, a.get("days") or None,
                                                   min(int(a.get("limit") or 300), 2000), a.get("doc_id"))})


@bp.get("/api/inv/docs")
def inv_docs():
    a = request.args
    return jsonify({"ok": True, "docs": inv.docs(a.get("kind") or "", a.get("days") or None)})


@bp.get("/api/inv/docs/<did>")
def inv_doc(did):
    d = inv.doc(did)
    return jsonify({"ok": True, "doc": d}) if d else err("没有这张单", 404)


@bp.post("/api/inv/docs")
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


@bp.post("/api/inv/docs/<did>/void")
def inv_doc_void(did):
    if _need("inv.adjust"):
        return _need("inv.adjust")
    try:
        return jsonify({"ok": True, "doc": inv.void_doc(did, _uname())})
    except ValueError as e:
        return err(str(e))


@bp.post("/api/inv/stocktake")
def inv_stocktake_start():
    """开始盘点（有领用权限的员工就能开、能填数；确认要「盘点确认 / 调整」权限）。"""
    if _need("inv.out"):
        return _need("inv.out")
    b = request.get_json(force=True) or {}
    try:
        area = str(b.get("area") or "").strip().upper()
        if area:                                 # v2.35：按货架 / 区 / 货位盘点
            from modules.inv import locations
            codes = locations.area_codes(area)
            return jsonify({"ok": True, "doc": inv.stocktake_start(b.get("category") or "", _uname(), b.get("note") or "", area, codes)})
        return jsonify({"ok": True, "doc": inv.stocktake_start(b.get("category") or "", _uname(), b.get("note") or "")})
    except ValueError as e:
        return err(str(e))


@bp.post("/api/inv/stocktake/<int:did>/<act>")
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


@bp.get("/api/inv/expense")
def inv_expense():
    a = request.args
    return jsonify({"ok": True, **inv.expense(a.get("start") or None, a.get("end") or None, a.get("group") or "category")})


# ---------------- 采购（v2.18） ----------------
@bp.get("/api/inv/suppliers")
def inv_suppliers():
    return jsonify({"ok": True, "suppliers": inv.suppliers(request.args.get("all") == "1")})


@bp.post("/api/inv/suppliers")
def inv_supplier_save():
    if _need("inv.in"):
        return _need("inv.in")
    try:
        return jsonify({"ok": True, "supplier": inv.save_supplier(request.get_json(force=True) or {}, _uname())})
    except (TypeError, ValueError) as e:
        return err(str(e))


# ---------------- 财务模块对接（v2.18，对接规范第 11 条） ----------------
@bp.get("/api/v1/finance/events")
def v1_finance_events():
    a = request.args
    return jsonify({"ok": True, "events": inv.finance_events(float(a.get("since") or 0), min(int(a.get("limit") or 1000), 5000),
                                                             a.get("kind") or "")})


@bp.get("/api/v1/finance/inventory")
def v1_finance_inventory():
    try:
        return jsonify({"ok": True, **inv.finance_month(request.args.get("month") or None)})
    except ValueError:
        return err("month 要是 YYYY-MM")


@bp.get("/api/inv/finance")
def inv_finance_ui():
    """库存页「财务」：最近的财务事件 + 本月汇总（和给财务模块的接口一样的数据）。"""
    if _need("inv.pay"):
        return _need("inv.pay")
    return jsonify({"ok": True, "events": list(reversed(inv.finance_events(0, 5000)))[:200], "month": inv.finance_month(request.args.get("month") or None)})


# ---------------- 纸箱（v2.35：泰国邮政标准纸箱的库存和用量）----------------
@bp.get("/api/inv/boxes")
def inv_boxes():
    return jsonify({"ok": True, "boxes": _views().box_stats()})


@bp.post("/api/inv/boxes/<code>/item")
def inv_box_item(code):
    """给这个规格的纸箱建档（库存里的包材物品 BOX-规格）。"""
    if _need("inv.in"):
        return _need("inv.in")
    from core.inventory import boxes
    iid = boxes.ensure_item(code, _uname())
    if not iid:
        return err("不是邮政标准纸箱规格")
    return jsonify({"ok": True, "item": inv.get_item(iid)})


# ---------------- 货位（v2.33 建；v2.35：一个物品一个货位，数量只记在物品上）----------------
from modules.inv import locations as _loc  # noqa: E402
from modules.inv import shipout as _shipout  # noqa: E402
_loc.init()
_shipout.init()


def _ok(fn):
    try:
        return jsonify({"ok": True, **fn()})
    except ValueError as e:
        return err(str(e))


@bp.get("/api/inv/locations")
def inv_locations():
    a = request.args
    return jsonify({"ok": True, "locations": _loc.locations(a.get("all") != "1"), "unassigned": len(_loc.unassigned()),
                    "groups": _loc.groups(), "layer_bottom": _loc.layer_bottom(), "categories": inv.categories()})


@bp.post("/api/inv/locations")
def inv_location_save():
    if _need("inv.in"):
        return _need("inv.in")
    return _ok(lambda: {"location": _loc.save_loc(request.get_json(force=True) or {}, _uname())})


@bp.post("/api/inv/locations/bulk")
def inv_location_bulk():
    """建货架：{zone, shelf(起始号，空=接着排), count(建几个), layers, positions, name, categories}"""
    if _need("inv.in"):
        return _need("inv.in")
    b = request.get_json(force=True) or {}
    return _ok(lambda: _loc.bulk_create(b.get("zone"), b.get("shelf"), b.get("layers"), b.get("positions"),
                                        b.get("name") or "", b.get("categories"), _uname(), b.get("count") or 1))


@bp.post("/api/inv/locations/add")
def inv_location_add():
    """货架加一层（不带 layer）/ 某一层加一位（带 layer）。"""
    if _need("inv.in"):
        return _need("inv.in")
    b = request.get_json(force=True) or {}
    if b.get("layer") in (None, ""):
        return _ok(lambda: {"made": _loc.add_layer(b.get("shelf"), _uname())})
    return _ok(lambda: {"made": [_loc.add_pos(b.get("shelf"), b.get("layer"), _uname())]})


@bp.post("/api/inv/locations/remove")
def inv_location_remove():
    """删空的货架（不带 layer）/ 货架的某一层（带 layer）。"""
    if _need("inv.adjust"):
        return _need("inv.adjust")
    b = request.get_json(force=True) or {}
    return _ok(lambda: {"removed": _loc.remove(b.get("shelf"), b.get("layer"), _uname())})


@bp.post("/api/inv/locations/group")
def inv_location_group():
    """区 / 货架的名字、放哪些分类。"""
    if _need("inv.in"):
        return _need("inv.in")
    b = request.get_json(force=True) or {}
    return _ok(lambda: {"group": _loc.save_group(b.get("code"), b.get("name") or "", b.get("categories") or [], _uname())})


@bp.delete("/api/inv/locations/<int:lid>")
def inv_location_delete(lid):
    if _need("inv.adjust"):
        return _need("inv.adjust")
    return _ok(lambda: (_loc.delete_loc(lid, _uname()) or {}))


@bp.get("/api/inv/locations/find")
def inv_location_find():
    """扫码 / 输入：货位 → 货位详情；货架 → 货架；物品编码 / SKU → 它放在哪。"""
    try:
        return jsonify({"ok": True, **_loc.find(request.args.get("code"))})
    except ValueError as e:
        return err(str(e), 404)


@bp.get("/api/inv/locations/unassigned")
def inv_unassigned():
    """有库存、还没货位的物品 + 推荐的空格。"""
    return jsonify({"ok": True, "items": _loc.unassigned()})


@bp.post("/api/inv/locations/assign")
def inv_loc_assign():
    """放物品：{item_id, code}（code 空 = 拿下来）。"""
    if _need("inv.in"):
        return _need("inv.in")
    b = request.get_json(force=True) or {}
    return _ok(lambda: {"item": _loc.assign(b.get("item_id"), b.get("code") or "", _uname())})


@bp.post("/api/inv/locations/assign-all")
def inv_loc_assign_all():
    if _need("inv.in"):
        return _need("inv.in")
    return _ok(lambda: {"done": _loc.assign_all(_uname())})


@bp.get("/api/inv/locations/<int:lid>")
def inv_location_detail(lid):
    return _ok(lambda: _loc.loc_detail(lid))


@bp.get("/print/inv-locations")
def inv_location_labels():
    """货位标签：?ids=1,2 / ?shelf=A1 / ?zone=A / 不带 = 全部；?kind=shelf 打货架牌；?lang=th 泰文说明。"""
    a = request.args
    lang = "th" if a.get("lang") == "th" else "zh"
    locs = _loc.locations()
    if a.get("shelf"):
        sc = a["shelf"].strip().upper()
        locs = [l for l in locs if l.get("shelf") is not None and _loc.shelf_code(l["zone"], l["shelf"]) == sc]
    elif a.get("zone"):
        locs = [l for l in locs if l["zone"] == a["zone"].strip().upper()]
    ids = [x for x in (a.get("ids") or "").split(",") if x.strip()]
    if ids:
        locs = [l for l in (_loc.get_loc(i) for i in ids) if l]
    if a.get("kind") == "shelf":
        codes = list(dict.fromkeys(_loc.shelf_code(l["zone"], l["shelf"]) for l in locs if l.get("shelf") is not None))
        return app.response_class(_loc.shelf_labels_html(codes, lang), mimetype="text/html")
    return app.response_class(_loc.labels_html(locs, lang), mimetype="text/html")
