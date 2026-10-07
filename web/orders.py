"""订单、审单、售后、买家、物流交接、打包核对、费用、利润、工作台。"""
from web.common import *  # noqa: F401,F403

@app.post("/api/orders/import/preview")
def orders_import_preview():
    f = request.files.get("file")
    if not f:
        return err("请选择订单表格")
    try:
        return jsonify(orders_mod.preview(f))
    except ValueError as e:
        return err(str(e))


@app.post("/api/orders/import/commit")
def orders_import_commit():
    b = request.get_json(force=True) or {}
    try:
        st = orders_mod.commit(b.get("token"), b.get("mapping") or {}, b.get("platform") or "",
                               b.get("profile") or "", _uname())
    except ValueError as e:
        return err(str(e))
    st["jobs"] = production.generate(_uname())
    return jsonify(st)


@app.get("/api/orders")
def orders_list():
    f = {k: request.args.get(k) for k in ("tab", "q", "platform", "shop", "kind", "tag", "label", "date_from", "date_to", "sort",
                                          "page", "page_size", "pay", "carrier", "buyer_key")}
    r = orders_mod.search(f)
    r["orders"] = [_strip_order(o) for o in r["orders"]]
    r["status_zh"] = orders_mod.STATUS_ZH
    r["kind_zh"] = orders_mod.KIND_ZH
    r["ship_method_zh"] = orders_mod.SHIP_METHOD_ZH
    r["level_zh"] = orders_mod.LEVEL_ZH
    return jsonify(r)


@app.get("/api/orders/<int:oid>")
def order_get(oid):
    o = orders_mod.get_order(oid)
    if not o:
        return err("订单不存在", 404)
    o["jobs"] = production.list_jobs(order_id=oid)
    o["log"] = orders_mod.get_log(oid)
    from core import extras as _ex
    o["aftersales"] = _ex.as_list(oid, days=3650)
    o["buyer_profile"] = orders_mod.buyer_profile(o.get("buyer_key"), exclude_id=None) if o.get("buyer_key") else None
    o["is_cod"] = orders_mod.is_cod(o)
    o["review_flags"] = orders_mod.review_flags(o) if o["status"] == "to_ship" else []
    if auth.is_owner():
        o["profit"] = finance.order_profit(load_config(), o, [dict(i) for i in o["items"]])
    return jsonify(_strip_order(o))


@app.post("/api/orders/<int:oid>/edit")
def order_edit(oid):
    """修改订单：基本信息 + 商品明细（还没开始打印才能改商品）。"""
    b = request.get_json(force=True) or {}
    if _cancel_denied(oid, b):
        return _cancel_denied(oid, b)
    if not auth.is_owner():
        for k in ("order_total", "shipping_fee", "platform_fee") + orders_mod.MONEY_FIELDS:
            b.pop(k, None)
    try:
        o = orders_mod.edit_order(oid, b, _uname())
    except ValueError as e:
        return err(str(e))
    production.schedule()
    return jsonify(o)


@app.post("/api/orders/<int:oid>")
def order_update(oid):
    b = request.get_json(force=True) or {}
    keys = ("custom_note", "seller_note", "priority", "status", "kind", "tracking_no", "tags", "ship_by", "buyer",
            "receiver", "phone", "address", "postcode", "carrier", "cod", "ship_method", "payment")
    if auth.is_owner():
        keys += orders_mod.MONEY_FIELDS
    if auth.current_user()["role"] == "production":
        keys = ("custom_note",)
    if "status" in keys and _cancel_denied(oid, b):
        return _cancel_denied(oid, b)
    try:
        o = orders_mod.update_order(oid, _uname(), **{k: b.get(k) for k in keys if k in b})
    except ValueError as e:
        return err(str(e))
    production.generate(_uname())
    production.schedule()
    return jsonify(_strip_order(o))


@app.post("/api/orders/batch")
def orders_batch():
    b = request.get_json(force=True) or {}
    ids = [int(x) for x in b.get("ids") or []]
    act = b.get("action")
    if not ids:
        return err("请先勾选订单")
    if act == "delete" and not auth.has_perm(auth.current_user(), "orders.delete"):
        return err(_no_perm("orders.delete"), 403)
    if act == "status" and b.get("value") in ("cancelled", "delivery_failed") and _need("orders.cancel"):
        return _need("orders.cancel")
    try:
        n = orders_mod.batch(ids, act, b.get("value"), _uname())
    except ValueError as e:
        return err(str(e))
    production.generate(_uname())
    production.schedule()
    return jsonify({"done": n})


@app.get("/api/orders/export")
def orders_export():
    """导出订单（每个商品一行）。ids=1,2,3 或按当前筛选条件。"""
    import io as _io
    import openpyxl
    f = {k: request.args.get(k) for k in ("tab", "q", "platform", "shop", "kind", "tag", "label", "date_from", "date_to", "sort")}
    f["page_size"] = 500
    ids = [int(x) for x in (request.args.get("ids") or "").split(",") if x.strip().isdigit()]
    rows = []
    if ids:
        rows = [orders_mod.get_order(i) for i in ids]
        rows = [r for r in rows if r]
    else:
        page = 1
        while True:
            f["page"] = page
            r = orders_mod.search(f)
            rows += r["orders"]
            if page * r["page_size"] >= r["total"]:
                break
            page += 1
    owner = auth.is_owner()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "订单"
    head = ["平台", "店铺", "订单号", "状态", "下单时间", "最晚发货", "买家", "SKU", "商品", "规格", "颜色", "数量"]
    if owner:
        head += ["单价", "商品金额", "订单金额", "运费", "平台费"]
    head += ["运单号", "买家留言", "定制备注", "标签", "类型", "物流", "发货方式", "付款方式", "审核"]
    if owner:
        head += [orders_mod.FIELD_LABELS[k] for k in orders_mod.MONEY_FIELDS]
    ws.append(head)
    fmt = (lambda t: dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "")
    for o in rows:
        for it in o.get("items") or [{}]:
            row = [o.get("platform"), o.get("shop"), o.get("order_no"), orders_mod.STATUS_ZH.get(o.get("status"), o.get("status")),
                   fmt(o.get("order_time")), fmt(o.get("ship_by")), o.get("buyer"), it.get("sku"), it.get("name"),
                   it.get("variation"), it.get("color"), it.get("qty")]
            if owner:
                row += [it.get("unit_price"), it.get("item_total"), o.get("order_total"), o.get("shipping_fee"), o.get("platform_fee")]
            row += [o.get("tracking_no"), o.get("buyer_note"), o.get("custom_note"), o.get("tags"),
                    orders_mod.KIND_ZH.get(o.get("kind"), o.get("kind")), o.get("carrier"),
                    orders_mod.SHIP_METHOD_ZH.get(o.get("ship_method") or "", ""),
                    "货到付款" if orders_mod.is_cod(o) else (o.get("payment") or ""),
                    ("待审核：" + (o.get("hold_reason") or "")) if o.get("hold") else ""]
            if owner:
                row += [o.get(k) for k in orders_mod.MONEY_FIELDS]
            ws.append(row)
    for col, w in zip("ABCDEFGHIJKLMNOPQRSTUV", (9, 12, 20, 10, 17, 17, 14, 16, 26, 14, 8, 6, 8, 10, 10, 8, 8, 18, 24, 24, 12, 10)):
        ws.column_dimensions[col].width = w
    buf = _io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    name = f"orders_{dt.datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(buf, as_attachment=True, download_name=name,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.delete("/api/orders/<int:oid>")
def order_delete(oid):
    orders_mod.delete_order(oid)
    return jsonify({"ok": True})


@app.post("/api/orders/manual")
def order_manual():
    try:
        o = orders_mod.create_manual(request.get_json(force=True) or {}, _uname())
    except ValueError as e:
        return err(str(e))
    production.generate(_uname())
    return jsonify(o)


@app.post("/api/orders/<int:oid>/review")
def order_review(oid):
    """审单：approve 审核通过（开始排产）/ hold 挂起（不排产，还没开始的任务撤掉）。"""
    b = request.get_json(force=True) or {}
    act = b.get("action")
    if act not in ("approve", "hold"):
        return err("操作不对")
    try:
        orders_mod.set_hold(oid, act == "hold", b.get("reason") or "", _uname())
    except ValueError as e:
        return err(str(e))
    production.generate(_uname())
    production.schedule()
    return jsonify(_strip_order(orders_mod.get_order(oid)))


@app.post("/api/orders/tracking-import")
def orders_tracking_import():
    """批量填运单号：每行 订单号,运单号[,物流公司]。"""
    b = request.get_json(force=True) or {}
    r = orders_mod.import_tracking(b.get("text") or "", bool(b.get("mark_shipped")), _uname())
    if b.get("mark_shipped"):
        production.generate(_uname())
    return jsonify(r)


@app.get("/api/buyers")
def buyers_get():
    a = request.args
    if a.get("key"):
        p = orders_mod.buyer_profile(a["key"])
        if not p:
            return err("没有这个买家", 404)
        if not auth.is_owner():
            p.pop("spent", None)
        return jsonify(p)
    items = orders_mod.buyers_list(a.get("q") or "", a.get("level") or "", a.get("risky") == "1")
    if not auth.is_owner():
        for d in items:
            d.pop("spent", None)
    return jsonify({"items": items, "levels": orders_mod.LEVEL_ZH})


@app.post("/api/buyers")
def buyers_post():
    b = request.get_json(force=True) or {}
    try:
        p = orders_mod.buyer_set(b.get("key") or "", b.get("level"), b.get("note"), b.get("name"), _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify(p)


# ---- 发货交接单 ----
@app.get("/api/handovers")
def handovers_get():
    return jsonify({"items": orders_mod.handover_list(), "methods": orders_mod.SHIP_METHOD_ZH})


@app.post("/api/handovers")
def handovers_open():
    b = request.get_json(force=True) or {}
    hid = orders_mod.handover_open(str(b.get("carrier") or "").strip()[:60], b.get("method") or "", _uname())
    return jsonify(orders_mod.handover_get(hid))


@app.get("/api/handovers/<int:hid>")
def handover_get(hid):
    d = orders_mod.handover_get(hid)
    return jsonify(d) if d else err("交接单不存在", 404)


@app.post("/api/handovers/<int:hid>/<act>")
def handover_act(hid, act):
    b = request.get_json(force=True) or {}
    try:
        if act == "scan":
            r = orders_mod.handover_scan(hid, b.get("code"), _uname())
            r["handover"] = orders_mod.handover_get(hid)
            return jsonify(r)
        if act == "remove":
            orders_mod.handover_remove(hid, int(b.get("order_id") or 0), _uname())
        elif act == "close":
            r = orders_mod.handover_close(hid, _uname())
            production.schedule()
            return jsonify({**r, "handover": orders_mod.handover_get(hid)})
        else:
            return err("操作不对", 404)
    except ValueError as e:
        return err(str(e))
    return jsonify(orders_mod.handover_get(hid))


@app.delete("/api/handovers/<int:hid>")
def handover_del(hid):
    try:
        orders_mod.handover_delete(hid)
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True})


@app.post("/api/orders/rematch")
def orders_rematch():
    n = orders_mod.rematch()
    # 已有任务也补上克数/时长
    c = db.conn()
    c.execute("""UPDATE jobs SET product_id=(SELECT product_id FROM order_items WHERE id=jobs.order_item_id),
                 grams_each=(SELECT grams FROM order_items WHERE id=jobs.order_item_id),
                 hours_each=(SELECT hours FROM order_items WHERE id=jobs.order_item_id),
                 color=(SELECT color FROM order_items WHERE id=jobs.order_item_id),
                 material=COALESCE((SELECT material FROM order_items WHERE id=jobs.order_item_id), material)
                 WHERE status='todo' AND order_item_id IS NOT NULL""")
    c.commit()
    production.generate(_uname())
    production.schedule()
    return jsonify({"matched": n})


@app.get("/api/profit")
def profit_report():
    return jsonify(finance.report(int(request.args.get("days") or 30)))


@app.get("/api/expenses")
def expenses_list():
    return jsonify({"items": finance.list_expenses()})


@app.post("/api/expenses")
def expenses_add():
    b = request.get_json(force=True) or {}
    try:
        finance.add_expense(b.get("day"), b.get("kind"), float(b.get("amount")), b.get("note"), _uname())
    except (TypeError, ValueError):
        return err("请填写金额")
    return jsonify({"items": finance.list_expenses()})


@app.delete("/api/expenses/<int:eid>")
def expenses_delete(eid):
    finance.delete_expense(eid)
    return jsonify({"items": finance.list_expenses()})


@app.post("/api/labels/import")
def labels_import():
    f = request.files.get("file")
    if not f:
        return err("请选择面单 PDF")
    try:
        return jsonify(labels.import_pdf(f.stream, _uname()))
    except ValueError as e:
        return err(str(e))


@app.post("/api/labels/check")
def labels_check():
    ids = [int(x) for x in (request.get_json(force=True) or {}).get("ids") or []]
    c = db.conn()
    have, missing = [], []
    for oid in ids:
        r = c.execute("SELECT label_file FROM orders WHERE id=?", (oid,)).fetchone()
        ok = bool(r and r["label_file"] and os.path.exists(os.path.join(labels.LABEL_DIR, r["label_file"])))
        (have if ok else missing).append(oid)
    return jsonify({"have": have, "missing": missing})


@app.get("/api/dashboard")
def dashboard_get():
    return jsonify(extras.dashboard(auth.is_owner()))


@app.get("/api/aftersales")
def aftersales_get():
    a = request.args
    st = a.get("status") or None
    stage = a.get("stage") or None
    if st == "open" and not stage:     # 「处理中」= 所有没处理完的阶段
        items = [d for d in extras.as_list(int(a["order_id"]) if a.get("order_id") else None, None, int(a.get("days") or 365),
                                           None, a.get("kind") or None, a.get("resp"), a.get("q") or "", a.get("due") or None)
                 if not d["done"]]
    else:
        items = extras.as_list(int(a["order_id"]) if a.get("order_id") else None, st, int(a.get("days") or 365), stage,
                               a.get("kind") or None, a.get("resp"), a.get("q") or "", a.get("due") or None)
    return jsonify({"items": [_strip_as(d) for d in items], "kinds": extras.AS_KIND, "reasons": extras.AS_REASONS,
                    "stages": extras.AS_STAGE, "done": extras.AS_DONE, "resp": extras.AS_RESP, "counts": extras.as_counts(),
                    "loss_total": round(sum(d.get("loss", 0) for d in items), 2) if auth.is_owner() else None})


@app.get("/api/aftersales/<int:aid>")
def aftersales_one(aid):
    d = extras.as_get(aid)
    return jsonify(_strip_as(d)) if d else err("售后记录不存在", 404)


@app.post("/api/aftersales")
def aftersales_post():
    b = request.get_json(force=True) or {}
    try:
        aid = extras.as_add(int(b.get("order_id") or 0), b.get("kind") or "other", b.get("reason") or "其他",
                            b.get("amount") if auth.is_owner() or b.get("amount") not in (None, "") else None,
                            b.get("note") or "", _uname(), b.get("items") or [], b.get("stage") or None, b.get("due_at") or None,
                            b.get("responsibility") or "", b.get("staff") or "", b.get("return_tracking") or "",
                            b.get("return_shipping") if auth.is_owner() else None, b.get("penalty") if auth.is_owner() else None)
    except (ValueError, FileNotFoundError) as e:
        return err(str(e))
    if b.get("status") and auth.current_user()["role"] != "production":
        orders_mod.update_order(int(b["order_id"]), _uname(), status=b["status"])
        production.generate(_uname())
    return jsonify({"id": aid})


@app.post("/api/aftersales/<int:aid>")
def aftersales_update(aid):
    try:
        d = extras.as_update(aid, request.get_json(force=True) or {}, _uname(), auth.is_owner())
    except ValueError as e:
        return err(str(e))
    return jsonify(_strip_as(d))


@app.post("/api/aftersales/<int:aid>/close")
def aftersales_close(aid):
    try:
        extras.as_close(aid, _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True})


@app.post("/api/aftersales/<int:aid>/inspect")
def aftersales_inspect(aid):
    b = request.get_json(force=True) or {}
    try:
        d = extras.as_inspect(aid, b.get("items") or [], b.get("note") or "", _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify(_strip_as(d))


@app.post("/api/aftersales/<int:aid>/evidence")
def aftersales_evidence_add(aid):
    files = request.files.getlist("files")
    if not files:
        return err("请选择照片或视频")
    try:
        ev = extras.as_evidence_add(aid, files, _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"evidence": ev})


@app.get("/api/aftersales/<int:aid>/evidence/<path:name>")
def aftersales_evidence_get(aid, name):
    path = os.path.join(extras.evidence_dir(aid), os.path.basename(name))
    if not os.path.isfile(path):
        return err("文件不存在", 404)
    return send_file(path, conditional=True)


@app.delete("/api/aftersales/<int:aid>/evidence/<path:name>")
def aftersales_evidence_del(aid, name):
    try:
        ev = extras.as_evidence_del(aid, name, _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"evidence": ev})


@app.get("/api/pack/lookup")
def pack_lookup():
    """打包核对：扫订单号 / 运单号，列出这个订单要装的商品。"""
    code = (request.args.get("code") or "").strip()
    if not code:
        return err("请扫描或输入订单号 / 运单号")
    c = db.conn()
    r = c.execute("SELECT id FROM orders WHERE order_no=? OR tracking_no=? ORDER BY id DESC LIMIT 1", (code, code)).fetchone()
    if not r:
        r = c.execute("SELECT id FROM orders WHERE REPLACE(order_no,'-','')=? OR REPLACE(tracking_no,'-','')=? ORDER BY id DESC LIMIT 1",
                      (code.replace("-", ""), code.replace("-", ""))).fetchone()
    if not r:
        return err(f"找不到订单「{code}」", 404)
    o = orders_mod.get_order(r["id"])
    o["jobs"] = production.list_jobs(order_id=r["id"])
    return jsonify(_strip_order(o))


@app.post("/api/pack/done")
def pack_done():
    """核对完成：这个订单已打印好的任务标记为已打包。"""
    b = request.get_json(force=True) or {}
    oid = int(b.get("order_id") or 0)
    n = 0
    for j in production.list_jobs(order_id=oid):
        if j["status"] == "post":
            production.set_status(j["id"], "packed", _uname())
            n += 1
    orders_mod.log(oid, _uname(), "扫码核对打包完成", f"{n} 个任务")
    return jsonify({"packed": n})
