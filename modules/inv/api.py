"""库存模块的接口：物品、单据、盘点、流水、库存报表、给财务的事件。v2.31 从 web/inventory.py 搬过来。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403
from core import inventory as inv

bp = Blueprint("m_inv", __name__)


def _views():
    from modules.inv import views
    return views
PREFIXES = ['/api/inv/', '/api/v1/finance/events', '/api/v1/finance/inventory', '/print/inv-locations', '/print/gs-labels']
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
                    "printers": [p.get("code") or p.get("name") for p in (load_config().get("printers") or [])],
                    "qc_hint": bool(load_config().get("inv_qc_hint253")) and not load_config().get("inv_qc_on", True) and auth.is_owner()})


@bp.post("/api/inv/qc/hint")
def inv_qc_hint():
    """升级后的一次性提示：{enable: true} = 现在就开质检（成品先进待检区）；否则只是知道了。"""
    if not auth.is_owner():
        return err("只有老板能改", 403)
    b = request.get_json(silent=True) or {}
    save_config({"inv_qc_hint253": False, **({"inv_qc_on": True} if b.get("enable") else {})})
    return jsonify({"ok": True})


@bp.get("/api/inv/items")
def inv_items():
    a = request.args
    if a.get("view") and (a.get("page") or a.get("size")):      # v2.55：服务端分页 / 排序 / 搜索
        from modules.inv import views
        sort = a.get("sort") or ""
        if sort in views.MONEY_SORTS and not (_perms().get("inv.pay") or _perms().get("inv.in")):
            sort = ""
        r = views.listing_page(a.get("view"), a.get("category") or "", (a.get("q") or "").strip(), a.get("zone") or "", (a.get("loc") or "").strip(),
                               sort, a.get("dir") == "desc", a.get("page") or 1, int(a.get("size") or 50))
        return jsonify({"ok": True, **r, "counts": views.counts_sql(), "zones": views.zone_options()})
    if a.get("view"):            # v2.32：库存 / 物品资料 / 没库存 / 已停用
        from modules.inv import views
        return jsonify({"ok": True, "items": views.listing(a.get("view"), a.get("category") or "", (a.get("q") or "").strip(),
                                                           a.get("zone") or "", (a.get("loc") or "").strip()),
                        "counts": views.counts(), "zones": views.zone_options()})
    return jsonify({"ok": True, "items": inv.items(a.get("category") or "", (a.get("q") or "").strip(), a.get("low") == "1", a.get("all") == "1")})


@bp.get("/api/inv/items/<iid>")
def inv_item(iid):
    it = inv.get_item(iid)
    if not it:
        return err("没有这个物品", 404)
    inv.units.decorate([it])                    # v2.55：耗材带「几卷」
    from modules.inv import locations, wms
    loc = locations.get_loc(it["location"]) if it.get("location") else None
    return jsonify({"ok": True, "item": it, "moves": inv.moves(item_id=it["id"], limit=100), "locs": wms.item_locations(it["id"]),
                    "loc": {"code": loc["code"] if loc else "", "id": loc["id"] if loc else None,          # v2.35：一物一位
                            "human_zh": locations.human(loc["code"]) if loc else "", "human_th": locations.human(loc["code"], "th") if loc else "",
                            "missing": bool(it.get("location") and not loc),
                            "suggest": None if loc else locations.suggest(it["category"])}})


@bp.post("/api/inv/items")
def inv_item_save():
    if _need("inv.in"):
        return _need("inv.in")
    b = request.get_json(force=True) or {}
    move_to = None
    try:
        from modules.inv import locations, wms
        if "location" in b:                      # v2.35：货位要是建好的格子（a1-2-3 也认），空 = 没货位
            raw = str(b.get("location") or "").strip()
            old = inv.get_item(int(b["id"])) if b.get("id") else None
            if not (old and raw == (old.get("location") or "")):     # 没改就不检查
                loc = locations.get_loc(raw) if raw else None
                if raw and not loc:
                    raise ValueError(f"没有货位 {raw}（先在「货位」里建好货架，或者留空）")
                b["location"] = loc["code"] if loc else ""
                if old:                          # v2.52：改主货位 = 主货位上的东西一起搬过去
                    move_to = b.pop("location")
        it = inv.save_item(b, _uname())
        if move_to is not None:
            it = locations.assign(it["id"], move_to, _uname())
        if "size" in b:
            wms.set_item_size(it["id"], b.get("size"), _uname())
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
        if area:                                 # v2.52：按货位盘点（区 / 货架 / 货位，几个用逗号分开），手机一个货位一个货位数
            from modules.inv import stocktake
            return jsonify({"ok": True, "doc": stocktake.start(area, _uname(), b.get("note") or "", b.get("category") or "")})
        return jsonify({"ok": True, "doc": inv.stocktake_start(b.get("category") or "", _uname(), b.get("note") or "")})
    except ValueError as e:
        return err(str(e))


@bp.get("/api/inv/stocktake/<int:did>")
def inv_stocktake_get(did):
    """盘点单 + 按货位的进度和差异（v2.52）。"""
    from modules.inv import stocktake
    try:
        return jsonify({"ok": True, "doc": stocktake.summary(did)})
    except ValueError as e:
        return err(str(e), 404)


@bp.post("/api/inv/stocktake/<int:did>/<act>")
def inv_stocktake_act(did, act):
    from modules.inv import stocktake
    try:
        if act == "save":
            if _need("inv.out"):
                return _need("inv.out")
            d = inv.stocktake_save(did, (request.get_json(force=True) or {}).get("counts") or {}, _uname())
        elif act == "loc":                       # v2.52：数完一个货位 {code, counts: {物品id/编码: 数量}, complete}
            if _need("inv.out"):
                return _need("inv.out")
            b = request.get_json(force=True) or {}
            d = stocktake.count(did, b.get("code"), b.get("counts") or {}, _uname(), b.get("complete", True) not in (False, 0, "0"))
        elif act == "confirm":
            if _need("inv.adjust"):
                return _need("inv.adjust")
            d = stocktake.confirm(did, _uname()) if stocktake.is_loc_doc(did) else inv.stocktake_confirm(did, _uname())
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


BIG_LOCS = 1500        # v2.55：货位多于这个数，/api/inv/locations 不再把所有货位发给页面（页面改成边打边搜）


@bp.get("/api/inv/locations")
def inv_locations():
    a = request.args
    from modules.inv import wms, locviews
    c = db.conn()
    n = c.execute("SELECT COUNT(*) FROM inv_locations WHERE active=1").fetchone()[0]
    big = n > BIG_LOCS and a.get("full") != "1"
    shelves = [r[0] for r in c.execute("SELECT DISTINCT zone || shelf FROM inv_locations WHERE active=1 AND shelf IS NOT NULL ORDER BY zone, shelf")] if big else None
    mx = {r[0]: r[1] for r in c.execute("SELECT zone, MAX(shelf) FROM inv_locations WHERE shelf IS NOT NULL GROUP BY zone")}
    return jsonify({"ok": True, "locations": [] if big else _loc.locations(a.get("all") != "1"), "big": big, "total": n,
                    "zones": [r[0] for r in c.execute("SELECT DISTINCT zone FROM inv_locations WHERE active=1 ORDER BY zone")], "max_shelf": mx,
                    **({"shelves": shelves} if big else {}), "unassigned": wms.pending_count(),
                    "groups": _loc.groups(), "layer_bottom": _loc.layer_bottom(), "categories": inv.categories(),
                    "warehouses": _loc.warehouses(), "ztypes": wms.ZTYPES, "sizes": wms.SIZES})


# ---------------- v2.55：货位页三种看法（服务端筛选 / 排序 / 搜索 / 分页，页面只拿当前一页）----------------
@bp.get("/api/inv/loc/list")
def inv_loc_list():
    """列表：一行一个货位。参数：zone shelf status(empty|partial|full|over|low) has(empty|nonempty) below_min=1 category wh ztype q
    sort(code|zone|contents|qty|items|capacity|util|state|last_move) dir(asc|desc) page size(50|100|200)"""
    from modules.inv import locviews
    return _ok(lambda: locviews.list_locations(request.args.to_dict()))


@bp.get("/api/inv/loc/items")
def inv_loc_items():
    """按商品：一行一个商品。参数：zone shelf ztype category flag(scattered|unplaced|noloc|low) has q sort(name|code|category|qty|locs|placed|unplaced) dir page size"""
    from modules.inv import locviews
    return _ok(lambda: locviews.list_items(request.args.to_dict()))


@bp.get("/api/inv/loc/codes")
def inv_loc_codes():
    """当前筛选条件下的全部货位编号（最多 3000），批量操作「选中全部」用。"""
    from modules.inv import locviews
    return _ok(lambda: locviews.filtered_codes(request.args.to_dict()))


@bp.get("/api/inv/loc/suggest")
def inv_loc_suggest():
    from modules.inv import locviews
    return _ok(lambda: {"locations": locviews.suggest(request.args.get("q") or "", min(int(request.args.get("limit") or 30), 100))})


@bp.get("/api/inv/loc/summary")
def inv_loc_summary():
    from modules.inv import locviews
    return _ok(lambda: locviews.summary(request.args.get("force") == "1"))


@bp.get("/api/inv/loc/map")
def inv_loc_map():
    """货位图：zone 空 = 各库区汇总；zone=A = 这个库区的货架汇总 + shelf=A1 展开的格子（expand=all 全部展开）。"""
    from modules.inv import locviews
    a = request.args
    return _ok(lambda: locviews.map_view(a.get("zone") or "", a.get("shelf") or "", a.get("expand") or "", a.get("every") == "1"))


@bp.get("/api/inv/loc/<int:lid>/drawer")
def inv_loc_drawer(lid):
    from modules.inv import locviews
    return _ok(lambda: locviews.drawer(lid))


@bp.post("/api/inv/loc/bulk")
def inv_loc_bulk():
    """批量：{action: "move", codes: [...], to, force} = 这些货位里的东西全部搬到 to（搬不了的会列出原因，别的照搬）。"""
    if _need("inv.in"):
        return _need("inv.in")
    from modules.inv import locviews
    b = request.get_json(force=True) or {}
    if b.get("action") != "move":
        return err("不支持的批量操作")
    return _ok(lambda: locviews.bulk_move(b.get("codes") or [], b.get("to"), _uname(), bool(b.get("force"))))


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
                                        b.get("name") or "", b.get("categories"), _uname(), b.get("count") or 1,
                                        b.get("ztype") or None, b.get("warehouse") or None, b.get("props") or None))


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
    return _ok(lambda: {"group": _loc.save_group(b.get("code"), b.get("name") or "", b.get("categories") or [], _uname(),
                                                 b.get("warehouse"), b.get("ztype"))})


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
    """货位标签：?ids=1,2 / ?shelf=A1 / ?zone=A / ?warehouse=仓库id / ?ztype=pick / 不带 = 全部；?kind=shelf 打货架牌；
    ?fmt=qr 二维码标签（v2.52，默认条码）；?lang=th 泰文说明。"""
    a = request.args
    lang = "th" if a.get("lang") == "th" else "zh"
    direct = bool((a.get("ids") or "").strip() or (a.get("codes") or "").strip() or a.get("flt") == "1")
    locs = [] if direct else _loc.locations()      # v2.55：选好了货位就不用先读全部
    if a.get("warehouse"):
        locs = [l for l in locs if str(l.get("warehouse")) == a["warehouse"]]
    if a.get("ztype"):
        locs = [l for l in locs if l.get("ztype") == a["ztype"]]
    if a.get("shelf"):
        sc = a["shelf"].strip().upper()
        locs = [l for l in locs if l.get("shelf") is not None and _loc.shelf_code(l["zone"], l["shelf"]) == sc]
    elif a.get("zone"):
        locs = [l for l in locs if l["zone"] == a["zone"].strip().upper()]
    ids = [x for x in (a.get("ids") or "").split(",") if x.strip()]
    if ids:
        locs = [l for l in (_loc.get_loc(i) for i in ids) if l]
    codes = [x for x in (a.get("codes") or "").split(",") if x.strip()]
    if codes:                                    # v2.55：列表里选中的货位
        locs = [l for l in (_loc.get_loc(i) for i in codes) if l]
    if a.get("flt") == "1":                      # v2.55：列表当前筛选条件下的全部货位
        from modules.inv import locviews
        fc = locviews.filtered_codes({k: v for k, v in a.items() if k not in ("flt", "lang", "fmt", "kind")}, 5000)
        locs = [l for l in (_loc.get_loc(i) for i in fc["ids"]) if l]
    if a.get("kind") == "shelf":
        codes = list(dict.fromkeys(_loc.shelf_code(l["zone"], l["shelf"]) for l in locs if l.get("shelf") is not None))
        return app.response_class(_loc.shelf_labels_html(codes, lang), mimetype="text/html")
    return app.response_class(_loc.labels_html(locs, lang, "qr" if a.get("fmt") == "qr" else "bar"), mimetype="text/html")


# ---------------- 仓库作业（v2.52）：仓库、货位设置、上架、移库、补货、货位图 ----------------
@bp.get("/api/inv/warehouses")
def inv_warehouses():
    return jsonify({"ok": True, "warehouses": _loc.warehouses()})


@bp.post("/api/inv/warehouses")
def inv_warehouse_save():
    if _need("inv.in"):
        return _need("inv.in")
    return _ok(lambda: {"warehouse": _loc.save_warehouse(request.get_json(force=True) or {}, _uname())})


@bp.post("/api/inv/locations/props")
def inv_location_props():
    """货位设置：{codes: [..] 或 area: "A1", props: {capacity, size, mixed, fixed_item, min_qty, note}}"""
    if _need("inv.in"):
        return _need("inv.in")
    b = request.get_json(force=True) or {}
    return _ok(lambda: {"locations": _loc.save_props(b.get("codes") or str(b.get("area") or ""), b.get("props") or {}, _uname())})


@bp.get("/api/inv/wms/map")
def inv_wms_map():
    from modules.inv import wms
    a = request.args
    return jsonify({"ok": True, **wms.map_data(a.get("idle_days") or None, a.get("max_spread") or None)})


@bp.get("/api/inv/wms/pending")
def inv_wms_pending():
    """待上架：[{item, qty, suggest:[推荐]}]"""
    from modules.inv import wms
    return jsonify({"ok": True, "items": wms.pending()})


@bp.get("/api/inv/wms/recommend")
def inv_wms_recommend():
    from modules.inv import wms
    a = request.args
    return _ok(lambda: {"plan": wms.recommend(int(a.get("item_id") or 0), a.get("qty") or None),
                        **wms.item_locations(int(a.get("item_id") or 0))})


@bp.post("/api/inv/wms/putaway")
def inv_wms_putaway():
    """上架：{item_id, code, qty（空 = 全部待上架的）, force}；{all: true} = 全部按推荐放。"""
    if _need("inv.in"):
        return _need("inv.in")
    from modules.inv import wms
    b = request.get_json(force=True) or {}
    if b.get("all"):
        return _ok(lambda: {"done": _loc.assign_all(_uname())})
    return _ok(lambda: wms.putaway(int(b.get("item_id") or 0), b.get("code"), b.get("qty"), _uname(), bool(b.get("force")), b.get("from") or ""))


@bp.post("/api/inv/wms/move")
def inv_wms_move():
    """移库：{from（空 = 待上架）, to, lines: [{item_id, qty}], task_id, force（超容量也放）}"""
    if _need("inv.in"):
        return _need("inv.in")
    from modules.inv import wms
    b = request.get_json(force=True) or {}
    return _ok(lambda: wms.move(b.get("from") or "", b.get("to"), b.get("lines") or [], _uname(),
                                "replenish" if b.get("task_id") else "move", b.get("task_id"), bool(b.get("force"))))


@bp.get("/api/inv/wms/tasks")
def inv_wms_tasks():
    """补货 / 移库任务 + 补货建议（拣货位低于最低数量）。"""
    from modules.inv import wms
    wms.ensure_tasks()
    return jsonify({"ok": True, "tasks": wms.tasks(request.args.get("status") or "open"), "suggest": wms.replenish_suggestions()})


@bp.post("/api/inv/wms/tasks/<int:tid>/<act>")
def inv_wms_task_act(tid, act):
    if _need("inv.in"):
        return _need("inv.in")
    from modules.inv import wms
    b = request.get_json(force=True) or {}
    if act == "do":
        return _ok(lambda: wms.task_do(tid, b.get("qty"), _uname()))
    if act == "cancel":
        return _ok(lambda: wms.task_cancel(tid, _uname()) or {})
    return err("操作不对")



# ---------------- v2.53：一本库存按区管：料卷货位、生产区（打印机 · 槽）、待检 / 退货 / 次品、库存金额 ----------------
def _flows():
    from modules.inv import flows
    return flows


@bp.get("/api/inv/value")
def inv_value():
    """库存金额：按区类型 / 区 / 分类、还够几天、很久没动的（金额字段只给有金额权限的人）。"""
    return jsonify({"ok": True, **_flows().value_report(request.args.get("slow_days") or None)})


@bp.get("/api/inv/printer-locs")
def inv_printer_locs():
    f = _flows()
    f.sync_printers()
    rows = [dict(r) for r in db.conn().execute("SELECT * FROM inv_printer_locs ORDER BY shelf")]
    return jsonify({"ok": True, "printers": rows, "zone": f.zone_letter(db.conn(), "production", create=False)})


@bp.get("/api/inv/spools")
def inv_spools():
    """料卷（一卷一行）+ 放在哪个货位 + 提醒。"""
    from core import materials
    f = _flows()
    try:
        f.sync_printers()
    except Exception:  # noqa: BLE001
        pass
    a = request.args
    rows = materials.spools(a.get("material") or "", a.get("color") or "", a.get("status") or "active", "")
    where = f.spool_locs()
    z = (a.get("loc") or "").strip().upper()
    out = []
    for s in rows:
        s = dict(s)
        s.pop("price", None)
        s["loc"] = where.get(s["id"])
        if z == "UNPLACED" and s["loc"]:
            continue
        if z and z != "UNPLACED" and not (s["loc"] and s["loc"]["code"].startswith(z)):
            continue
        out.append(s)
    return jsonify({"ok": True, "items": out, "alerts": f.spool_alerts(), "tare_g": f.tare_g(),
                    "stats": {"n": len(out), "grams": round(sum(max(0, x["remaining_g"] or 0) for x in out)),
                              "unplaced": sum(1 for x in out if not x["loc"]), "loaded": sum(1 for x in out if x["status"] == "loaded")}})


@bp.post("/api/inv/spools/<sid>/<act>")
def inv_spool_act(sid, act):
    """料卷：put {code} 放到货位（扫打印机 · 槽 = 上机）/ load {printer, slot} / unload {to, grams} / weigh {gross, tare}"""
    f = _flows()
    b = request.get_json(force=True) or {}
    u = _uname()
    if act == "put":
        return _ok(lambda: {"spool": f.spool_put(sid, b.get("code") or "", u)})
    if act == "load":
        return _ok(lambda: {"spool": f.spool_load(sid, b.get("printer") or "", b.get("slot") or "", u)})
    if act == "unload":
        return _ok(lambda: {"spool": f.spool_unload(sid, b.get("to") or "", b.get("grams"), u)})
    if act == "weigh":
        return _ok(lambda: {"result": f.spool_weigh(sid, b.get("gross"), u, b.get("tare")), "spool": f.spool_info(sid)})
    return err("操作不对")


@bp.post("/api/inv/spools/count")
def inv_spool_count():
    """料卷称重盘点：{code: 货位（可空）, entries: [{code: 料卷, gross: 毛重 g}]}"""
    b = request.get_json(force=True) or {}
    return _ok(lambda: _flows().spool_count(b.get("entries") or [], b.get("code") or "", _uname()))


@bp.get("/api/inv/held/<ztype>")
def inv_held(ztype):
    """待检区 / 退货区 / 次品区 / 暂存区里放着的：[{item, from, qty, suggest}]"""
    if ztype not in ("qc", "returns", "defect", "staging"):
        return err("区的类型不对")
    return jsonify({"ok": True, "items": _flows().held_list(ztype)})


def _iid(b):
    v = b.get("item_id") or b.get("code")
    it = inv.get_item(str(v).upper() if v and not str(v).isdigit() else v) if v else None
    if not it:
        raise ValueError("没有这个物品")
    return it["id"]


@bp.post("/api/inv/qc/<act>")
def inv_qc(act):
    """质检：pass {item_id, qty, to, from} → 上架；fail {item_id, qty, action: defect/scrap, from, note} → 次品区"""
    f = _flows()
    b = request.get_json(force=True) or {}
    if act == "pass":
        return _ok(lambda: f.qc_pass(_iid(b), b.get("qty"), b.get("to") or "", b.get("from") or "", _uname()))
    if act == "fail":
        if b.get("action") == "scrap" and _need("inv.out"):
            return _need("inv.out")
        return _ok(lambda: f.qc_fail(_iid(b), b.get("qty"), b.get("action") or "defect", b.get("from") or "", _uname(), b.get("note") or ""))
    return err("操作不对")


@bp.post("/api/inv/returns/<act>")
def inv_returns(act):
    """退货：receive {item_id/code, qty, note} 登记 → 退货区；act {item_id, act: restock/defect/scrap, qty, from, to}"""
    f = _flows()
    b = request.get_json(force=True) or {}
    if act == "receive":
        if _need("inv.in"):
            return _need("inv.in")
        def go():
            try:
                iid = _iid(b)
            except ValueError:
                if not b.get("code"):
                    raise
                from core.inventory import goods          # 产品的 SKU 还没建过成品档 → 建一个
                c = db.conn()
                iid = goods.ensure_item(c, str(b["code"]).strip().upper())
                c.commit()
            return f.return_receive(iid, b.get("qty") or 1, _uname(), b.get("note") or "")
        return _ok(go)
    if act == "act":
        if b.get("act") == "scrap" and _need("inv.out"):
            return _need("inv.out")
        return _ok(lambda: f.return_act(_iid(b), b.get("act") or "", b.get("qty"), b.get("from") or "", b.get("to") or "", _uname(), b.get("note") or ""))
    return err("操作不对")


@bp.post("/api/inv/defect/act")
def inv_defect():
    """次品区：{item_id, act: scrap 报废 / rework 返工好了重新质检 / restock 上架, qty, from, to, note}"""
    b = request.get_json(force=True) or {}
    if b.get("act") == "scrap" and _need("inv.out"):
        return _need("inv.out")
    return _ok(lambda: _flows().defect_act(_iid(b), b.get("act") or "", b.get("qty"), b.get("from") or "", b.get("to") or "", _uname(), b.get("note") or ""))


@bp.get("/api/inv/spools/<sid>")
def inv_spool_one(sid):
    """一卷料 + 放在哪（手机扫料卷）。"""
    s = _flows().spool_info(sid)
    return jsonify({"ok": True, "spool": s}) if s else err("没有这卷料", 404)


# ---------------- 成品备货（v2.54）：所有成品一张表、目标自动算、缺口一键补货 ----------------
def _gs_writer():
    """写操作：老板和生产角色（补货会建生产单 / 采购单草稿）。"""
    u = auth.current_user() or {"role": "owner"}
    if u.get("role") not in ("owner", "production"):
        return err("没有权限：只有老板和生产人员可以改成品备货", 403)
    return None


@bp.get("/api/inv/gs")
def gs_overview():
    from core.inventory import goodsstock
    return _ok(lambda: goodsstock.overview())


@bp.post("/api/inv/gs/<act>")
def gs_act(act):
    from core.inventory import goodsstock
    deny = _gs_writer()
    if deny:
        return deny
    b = request.get_json(force=True) or {}
    u = _uname()
    if act == "add":
        return _ok(lambda: goodsstock.add(b.get("skus"), b.get("product_ids"), b.get("group"), b.get("src"), u))
    if act == "target":
        return _ok(lambda: {"n": goodsstock.set_target(b.get("skus"), b.get("target"), u)})
    if act == "src":
        return _ok(lambda: {"n": goodsstock.set_src(b.get("skus"), b.get("src"), u)})
    if act == "remove":
        return _ok(lambda: {"n": goodsstock.remove(b.get("skus"), u)})
    if act == "plan":
        return _ok(lambda: {"plan": goodsstock.plan(b.get("skus"), b.get("group"))})
    if act == "replenish":
        return _ok(lambda: goodsstock.replenish(b.get("lines"), b.get("skus"), b.get("group"), u, bool(b.get("release")), b.get("priority") or 0,
                                                b.get("due"), b.get("printers")))
    return err("没有这个操作", 404)


@bp.get("/api/inv/gs/products")
def gs_products():
    """加进成品备货的候选：产品库的产品（带规格 SKU、已经在表里几个）。q 搜索。"""
    from core import store
    from core.inventory import goodsstock
    q = (request.args.get("q") or "").strip().lower()
    have = {r["sku"] for r in db.conn().execute("SELECT sku FROM stock")}
    out = []
    for it in store.list_products():
        try:
            p = store.load(it["id"])
        except Exception:  # noqa: BLE001
            continue
        skus = [(v.get("sku") or "").strip().upper() for v in p.get("variants") or [] if (v.get("sku") or "").strip()]
        if not skus:
            continue
        cat = goodsstock._cat_of(p)
        if q and q not in (p["id"] + " " + (p.get("name_zh") or "") + " " + cat).lower() and not any(q in s.lower() for s in skus):
            continue
        out.append({"id": p["id"], "name": p.get("name_zh") or "", "category": cat, "img": goodsstock._img(p), "skus": skus,
                    "in": sum(1 for s in skus if s in have), "tags": [str(x) for x in p.get("groups") or []]})
    cats = sorted({x["category"] for x in out if x["category"]})
    try:
        tags = [{"id": g["id"], "name": g["name"]} for g in db.conn().execute("SELECT id, name FROM product_groups ORDER BY sort, name")]
    except Exception:  # noqa: BLE001
        tags = []
    return _ok(lambda: {"products": out[:300], "total": len(out), "categories": cats, "tags": tags})


@bp.get("/api/inv/gs/locs")
def gs_locs():
    """一个 SKU 的货位（分开放的几处）+ 上架推荐，快速移库 / 上架用。"""
    from modules.inv import wms
    sku = (request.args.get("sku") or "").strip().upper()
    it = db.conn().execute("SELECT id FROM inv_items WHERE category='goods' AND UPPER(code)=?", (sku,)).fetchone()
    if not it:
        return _ok(lambda: {"item_id": None, "locations": [], "unplaced": 0, "plan": []})
    return _ok(lambda: {"item_id": it["id"], **wms.item_locations(it["id"]), "plan": wms.recommend(it["id"], None)})


@bp.get("/print/gs-labels")
def gs_labels():
    """成品标签 60×40mm：SKU 条码 + 名称 + 货位。?skus=A,B"""
    from html import escape as h
    from core import labels
    from core.inventory import goodsstock
    want = [s.strip().upper() for s in (request.args.get("skus") or "").split(",") if s.strip()]
    rs = {r["sku"]: r for r in goodsstock.rows()}
    css = ("@page{size:60mm 40mm;margin:0}*{box-sizing:border-box}body{margin:0;font:10px 'Leelawadee UI',Tahoma,'Microsoft YaHei',sans-serif}"
           ".t{width:60mm;height:40mm;padding:2mm;page-break-after:always;overflow:hidden;display:flex;flex-direction:column;gap:.6mm}"
           ".sku{font-size:15px;font-weight:800}.big{font-size:12px;font-weight:700}.row{display:flex;justify-content:space-between}"
           "@media screen{body{background:#ddd}.t{background:#fff;margin:6px auto}}@media print{.np{display:none}}")
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>SKU</title><style>{css}</style></head><body>"
           "<p class='np' style='text-align:center'><button onclick='print()'>打印 / พิมพ์</button> 60×40mm</p>"]
    for sku in want:
        r = rs.get(sku) or {"name": "", "color": "", "locs": []}
        loc = r["locs"][0]["code"] if r.get("locs") else ""
        out.append(f"<div class='t'><div class='row'><span class='sku'>{h(sku)}</span><span class='big'>{h(loc)}</span></div>"
                   f"<div class='big'>{h(r.get('color') or '')}</div><div>{h((r.get('name') or '')[:40])}</div><div>{labels.code128_svg(sku, 26, 1)}</div></div>")
    out.append("</body></html>")
    return app.response_class("".join(out), mimetype="text/html")
