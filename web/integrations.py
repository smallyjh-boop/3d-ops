"""对接接口 /api/v1、密钥、店铺、3D选品工具、运营写回。"""
from web.common import *  # noqa: F401,F403

@app.get("/api/catalog")
def catalog_export():
    cfg = load_config()
    prods = [store.load(i["id"]) for i in store.list_products()]
    prods.sort(key=lambda p: p["id"])
    names = {c["id"]: c["name"] for c in categories.library()}
    checks = {p["id"]: _check(cfg, p) for p in prods}
    os.makedirs(EXPORT_DIR, exist_ok=True)
    name = f"产品资料总表_{dt.datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    path = os.path.join(EXPORT_DIR, name)
    catalog.build(cfg, prods, names, checks, path)
    return send_file(path, as_attachment=True, download_name=name)


@app.get("/api/v1/ping")
def v1_ping():
    return jsonify({"ok": True, "version": VERSION, "time": time.time()})


@app.post("/api/v1/orders")
def v1_orders_push():
    """推送订单（新增或更新）。body: {"orders":[...], "source":"可选，来源名称", "platform":"可选，默认平台"}"""
    b = request.get_json(force=True, silent=True)
    if b is None:
        return _v1_err("请求体必须是 JSON")
    orders = b.get("orders") if isinstance(b, dict) else b
    if isinstance(orders, dict):
        orders = [orders]
    if not isinstance(orders, list) or not orders:
        return _v1_err("orders 不能为空")
    if len(orders) > 1000:
        return _v1_err("一次最多 1000 个订单")
    src = (b.get("source") if isinstance(b, dict) else None) or auth.current_user()["username"]
    try:
        st = integrations.ingest(orders, str(src)[:60], (b.get("platform") if isinstance(b, dict) else "") or "")
    except ValueError as e:
        return _v1_err(str(e))
    return jsonify({"ok": not st["errors"], **st})


@app.post("/api/v1/orders/status")
def v1_orders_status():
    """只更新状态/运单号：{"platform":"shopee","order_no":"...","status":"shipped","tracking_no":"..."} 或 {"orders":[...]}"""
    b = request.get_json(force=True, silent=True) or {}
    rows = b.get("orders") if isinstance(b, dict) and "orders" in b else ([b] if isinstance(b, dict) else b)
    clean = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        r = {k: v for k, v in r.items() if k != "items"}   # 不带 items = 不改商品明细
        clean.append(r)
    if not clean:
        return _v1_err("没有要更新的订单")
    c = db.conn()
    known, missing = [], []
    for r in clean:
        plat = str(r.get("platform") or "").lower()
        row = c.execute("SELECT platform FROM orders WHERE order_no=? AND (platform=? OR ?='') ORDER BY id DESC",
                        (str(r.get("order_no") or ""), plat, plat)).fetchone()
        if row:
            r["platform"] = row["platform"]
            known.append(r)
        else:
            missing.append(r.get("order_no"))
    st = integrations.ingest(known, auth.current_user()["username"]) if known else {"orders_updated": 0}
    return jsonify({"ok": True, "updated": st.get("orders_updated", 0), "not_found": missing})


@app.get("/api/v1/orders")
def v1_orders_list():
    """查询订单：?since=Unix秒（按更新时间）&status=to_ship&limit=200"""
    a = request.args
    c = db.conn()
    conds, args = ["updated_at>=?"], [float(a.get("since") or 0)]
    if a.get("status"):
        conds.append("status=?"); args.append(a["status"])
    if a.get("platform"):
        conds.append("platform=?"); args.append(a["platform"])
    rows = c.execute(f"SELECT id FROM orders WHERE {' AND '.join(conds)} ORDER BY updated_at LIMIT ?",
                     (*args, min(1000, int(a.get("limit") or 200)))).fetchall()
    out = []
    cfg = load_config()
    read_only = _v1_read_only()
    for r in rows:
        o = orders_mod.get_order(r["id"])
        o["jobs"] = [{"id": j["id"], "sku": j["sku"], "qty": j["qty"], "status": j["status"], "printer": j["printer"],
                      "planned_end": j["planned_end"]} for j in production.list_jobs(order_id=r["id"])]
        # v2.9.1：附上本系统算的成本（材料、机时、包材、失败损耗），外部系统不用自己再算一遍
        orow = c.execute("SELECT * FROM orders WHERE id=?", (r["id"],)).fetchone()
        irows = c.execute("SELECT * FROM order_items WHERE order_id=?", (r["id"],)).fetchall()
        o["cost"] = finance.order_profit(cfg, orow, irows)
        if read_only:
            for k in V1_PII_FIELDS:
                o.pop(k, None)
        out.append(o)
    return jsonify({"ok": True, "orders": out, "count": len(out)})


@app.get("/api/v1/skus")
def v1_skus():
    """所有产品变体。v2.9.1 起多返回：材质、售价、单件成本拆分、预估包裹重量和尺寸、类目、导出时间。
    ?since=Unix秒：只返回之后改过的产品。"""
    cfg = load_config()
    since = float(request.args.get("since") or 0)
    pack_g = float(cfg.get("packaging_weight_g") or 0)
    from core import listing as _lst
    bnames = _lst.batch_names()
    from core import codes, stockcalc
    av = stockcalc.available(cfg)
    from core import modules as _mods
    _gimg = _mods.public("goods")          # 商品模块的 openapi（图片）
    out = []
    for item in store.list_products():
        if since and (item.get("updated_at") or 0) < since:
            continue
        p = store.load(item["id"])
        pk = p.get("package") or {}
        cp = p.get("copy") or {}
        prices = pricing.price_product(cfg, p)
        lst_view = _lst.v1_view(p, bnames)
        stk = stockcalc.compute(p, cfg, av)
        auto = stockcalc.enabled(p, cfg)
        spec_by = {s_["spec_id"]: s_ for s_ in p.get("specs") or []}
        for v, pr, sk in zip(p.get("variants", []), prices, stk):
            if not v.get("sku"):
                continue
            grams = float(v.get("grams") or 0)
            out.append({
                "sku": v["sku"], "product_id": p["id"], "product_code": p["id"], "name": p.get("name_zh", ""),
                "draft": bool(p.get("draft")),                 # v2.12：选品工具推过来、还没补齐的草稿
                "source": {k: (p.get("source") or {}).get(k) for k in ("source", "source_id")} if p.get("source") else None,
                "title_th": cp.get("title_th", ""), "color": v.get("opt1_zh", ""), "spec": v.get("opt2_zh", ""),
                "variant": v.get("opt2_zh", ""),                # v2.12.1：规格中文名（尺寸 / 版本 / 套装），给选品工具显示
                "material": p.get("material") or "PLA", "grams": v.get("grams"), "hours": v.get("hours"),
                "unit_cost": pr["cost"],                       # 材料/机时/包材/失败损耗/合计（泰铢，不含平台费）
                "price": pr["final_price"], "suggested_price": pr["suggested_price"], "floor_price": pr["floor_price"],
                "manual_price": v.get("manual_price"),
                "est_package_weight_g": round(grams + pack_g, 1) if grams else None,   # 产品克数 + 包材重量
                "package_cm": {"length": pk.get("length"), "width": pk.get("width"), "height": pk.get("height")},
                "lazada_category_id": (p.get("category") or {}).get("id"),
                "shopee_category_id": (p.get("shopee_category") or {}).get("id"),
                "lead_days": p.get("lead_days"), "exported_at": p.get("exported_at"), "updated_at": p.get("updated_at"),
                "listing": lst_view,                           # v2.11.1：各平台上架状态、首次上架时间、批次
                # v2.16（对接规范 4.3.7）：规格编号、颜色码、是不是随机颜色、ERP 算的库存、是否按耗材自动算、规格状态
                "spec_id": v.get("spec_id") or "",
                "color_code": (codes.find_color(cfg, v.get("opt1_zh")) or ("", ""))[1],
                "random_color": codes.is_random(cfg, v.get("opt1_zh")),
                "stock": sk["stock"], "stock_sync": auto,
                "spec_status": (spec_by.get(v.get("spec_id")) or {}).get("status") or "ok",
                # v2.32.1（接口需求单：商品主图）：{id, url, updated_at, for: sku / product}，没图为 null
                "image": _gimg.sku_image(p, v) if _gimg else None,
            })
    return jsonify({"ok": True, "skus": out, "count": len(out)})


@app.get("/api/v1/cost-params")
def v1_cost_params():
    """成本参数（只读，不含任何密钥）：两个系统算成本、利润用同一套数。"""
    from core import fleet
    cfg = load_config()
    keys = ("filament_price_cny_per_kg", "cny_to_thb", "material_loss_rate", "electricity_thb_per_kwh", "printer_avg_kw",
            "monthly_rent", "monthly_labor", "monthly_depreciation", "monthly_maintenance", "printer_count",
            "hours_per_day_each", "failure_rate", "packaging_per_item", "packaging_weight_g", "platform_fee_rate",
            "shopee_fee_rate", "default_markup", "min_markup", "resin_thb_per_kg", "resin_extra_rate",
            "default_ship_days", "sku_prefix")
    printers = [{"code": p.get("code"), "name": p.get("name"), "enabled": p.get("enabled", True) is not False,
                 "tech": fleet.tech_of(p)}
                for p in (cfg.get("printers") or [])]
    on = [p for p in printers if p["enabled"]]
    return jsonify({"ok": True, "params": {k: cfg.get(k) for k in keys}, "derived": pricing.cost_summary(cfg),
                    "printers": printers,
                    "capacity_hours_per_day": round(len(on) * float(cfg.get("hours_per_day_each") or 0), 1),
                    "colors": [{"zh": r[0], "code": r[1], "th": r[2] if len(r) > 2 else "", "en": r[3] if len(r) > 3 else ""}
                               for r in (cfg.get("color_table") or [])]})


@app.get("/api/v1/profit")
def v1_profit():
    """本系统算的利润报表（和「利润」页一样）：?days=30"""
    days = max(1, min(366, int(request.args.get("days") or 30)))
    return jsonify({"ok": True, **finance.report(days)})


@app.get("/api/v1/production")
def v1_production():
    b = production.board()
    return jsonify({"ok": True, "lanes": [{"name": l["name"], "hours": l["hours"], "jobs": len(l["queue"]),
                                           "printing": [{"sku": r["sku"], "count": r["count"]} for r in l["runs"]],
                                           "state": (l.get("status") or {}).get("state")} for l in b["lanes"]],
                    "post": len(b["post"]), "packed": len(b["packed"])})


@app.get("/api/v1/materials")
def v1_materials():
    pl = materials.plan()
    return jsonify({"ok": True, **pl, "alerts": materials.alerts(pl["rows"])})


# ---- 老板在界面上管理：API 密钥、店铺对接、同步记录 ----
@app.get("/api/integrations")
def integrations_get():
    return jsonify({"keys": integrations.list_keys(), "shops": integrations.list_shops(),
                    "connectors": connectors.describe(), "log": integrations.sync_log(50),
                    "webhooks": integrations.webhook_log(30), "base": request.host_url.rstrip("/"),
                    "ext_latest": integrations.EXT_LATEST})


@app.post("/api/apikeys")
def apikey_create():
    b = request.get_json(force=True) or {}
    raw = integrations.create_key(b.get("name") or "API", b.get("scope") or "full")
    return jsonify({"key": raw, "keys": integrations.list_keys()})


@app.post("/api/apikeys/<int:kid>")
def apikey_update(kid):
    integrations.set_key_active(kid, (request.get_json(force=True) or {}).get("active"))
    return jsonify({"keys": integrations.list_keys()})


@app.delete("/api/apikeys/<int:kid>")
def apikey_delete(kid):
    integrations.delete_key(kid)
    return jsonify({"keys": integrations.list_keys()})
