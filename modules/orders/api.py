"""订单模块（基础模块）的接口：订单、审单、售后、买家、物流交接、打包核对、利润、工作台、打印订单 / 面单 / 交接单。
v2.31 从 web/orders.py 搬过来。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403
from core import chain

bp = Blueprint("m_orders", __name__)
PREFIXES = []
PATTERNS = []


@bp.post("/api/orders/import/preview")
def orders_import_preview():
    f = request.files.get("file")
    if not f:
        return err("请选择订单表格")
    try:
        return jsonify(orders_mod.preview(f))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/orders/import/commit")
def orders_import_commit():
    b = request.get_json(force=True) or {}
    try:
        st = orders_mod.commit(b.get("token"), b.get("mapping") or {}, b.get("platform") or "",
                               b.get("profile") or "", _uname())
    except ValueError as e:
        return err(str(e))
    st["jobs"] = chain.order_changed(_uname())
    return jsonify(st)


@bp.get("/api/orders")
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


@bp.get("/api/orders/<int:oid>")
def order_get(oid):
    o = orders_mod.get_order(oid)
    if not o:
        return err("订单不存在", 404)
    o["jobs"] = production.list_jobs(order_id=oid)
    o["log"] = orders_mod.get_log(oid, hide_money=not auth.is_owner())
    from core import extras as _ex
    o["aftersales"] = _ex.as_list(oid, days=3650)
    o["buyer_profile"] = orders_mod.buyer_profile(o.get("buyer_key"), exclude_id=None) if o.get("buyer_key") else None
    o["is_cod"] = orders_mod.is_cod(o)
    o["review_flags"] = orders_mod.review_flags(o) if o["status"] == "to_ship" else []
    if auth.is_owner():
        o["profit"] = finance.order_profit(load_config(), o, [dict(i) for i in o["items"]])
    _add_pack_info(o)
    return jsonify(_strip_order(o))


def _add_pack_info(o):
    """v2.35：用哪个纸箱（自动 / 改过）、发货出库单（库存模块开着才有）。"""
    from modules.orders import packbox
    o["box"] = packbox.box_for(o)
    from core import modules as _mods
    _inv = _mods.public("inv")
    o["out"] = _inv.order_out(o["id"]) if _inv is not None and hasattr(_inv, "order_out") else None


@bp.post("/api/orders/<int:oid>/edit")
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
    chain.reschedule()
    return jsonify(o)


@bp.post("/api/orders/<int:oid>")
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
    chain.order_changed(_uname())
    chain.reschedule()
    return jsonify(_strip_order(o))


@bp.post("/api/orders/batch")
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
    chain.order_changed(_uname())
    chain.reschedule()
    return jsonify({"done": n})


@bp.get("/api/orders/export")
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


@bp.delete("/api/orders/<int:oid>")
def order_delete(oid):
    try:
        orders_mod.delete_order(oid, _uname())
    except ValueError as e:      # v2.38：正在打印的订单不能删
        return err(str(e))
    return jsonify({"ok": True})


@bp.post("/api/orders/manual")
def order_manual():
    try:
        o = orders_mod.create_manual(request.get_json(force=True) or {}, _uname())
    except ValueError as e:
        return err(str(e))
    chain.order_changed(_uname())
    return jsonify(o)


@bp.post("/api/orders/<int:oid>/review")
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
    chain.order_changed(_uname())
    chain.reschedule()
    return jsonify(_strip_order(orders_mod.get_order(oid)))


@bp.post("/api/orders/tracking-import")
def orders_tracking_import():
    """批量填运单号：每行 订单号,运单号[,物流公司]。"""
    b = request.get_json(force=True) or {}
    r = orders_mod.import_tracking(b.get("text") or "", bool(b.get("mark_shipped")), _uname())
    if b.get("mark_shipped"):
        chain.order_changed(_uname())
    return jsonify(r)


@bp.get("/api/buyers")
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


@bp.post("/api/buyers")
def buyers_post():
    b = request.get_json(force=True) or {}
    try:
        p = orders_mod.buyer_set(b.get("key") or "", b.get("level"), b.get("note"), b.get("name"), _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify(p)


# ---- 发货交接单 ----
@bp.get("/api/handovers")
def handovers_get():
    return jsonify({"items": orders_mod.handover_list(), "methods": orders_mod.SHIP_METHOD_ZH})


@bp.post("/api/handovers")
def handovers_open():
    b = request.get_json(force=True) or {}
    hid = orders_mod.handover_open(str(b.get("carrier") or "").strip()[:60], b.get("method") or "", _uname())
    return jsonify(orders_mod.handover_get(hid))


@bp.get("/api/handovers/<int:hid>")
def handover_get(hid):
    d = orders_mod.handover_get(hid)
    return jsonify(d) if d else err("交接单不存在", 404)


@bp.post("/api/handovers/<int:hid>/<act>")
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
            chain.reschedule()
            return jsonify({**r, "handover": orders_mod.handover_get(hid)})
        else:
            return err("操作不对", 404)
    except ValueError as e:
        return err(str(e))
    return jsonify(orders_mod.handover_get(hid))


@bp.delete("/api/handovers/<int:hid>")
def handover_del(hid):
    try:
        orders_mod.handover_delete(hid)
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True})


@bp.post("/api/orders/rematch")
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
    chain.order_changed(_uname())
    chain.reschedule()
    return jsonify({"matched": n})


@bp.get("/api/profit")
def profit_report():
    return jsonify(finance.report(int(request.args.get("days") or 30)))


@bp.post("/api/labels/import")
def labels_import():
    f = request.files.get("file")
    if not f:
        return err("请选择面单 PDF")
    try:
        return jsonify(labels.import_pdf(f.stream, _uname()))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/v1/labels/import")
def v1_labels_import():
    """浏览器扩展转交平台面单 PDF（v2.35）：员工在卖家中心 / BigSeller 下载面单 PDF 时，扩展弹提示，点「发送」才传上来。
    用员工的扩展密钥（Authorization: Bearer）。表单字段 file（PDF）、site（从哪个网站下载的，只记日志）。"""
    f = request.files.get("file")
    if not f:
        return err("没有收到面单 PDF")
    head = f.stream.read(1024)
    f.stream.seek(0)
    if b"%PDF-" not in head:
        return err("这个文件不是 PDF")
    site = re.sub(r"[^A-Za-z ]", "", request.form.get("site") or "")[:20]
    try:
        r = labels.import_pdf(f.stream, _uname(), via="插件" + (f" · {site}" if site else ""))
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True, **r})


@bp.post("/api/labels/check")
def labels_check():
    """勾选的订单哪些有平台面单。v2.34：没有的、平台接口接通了的，顺便去平台取（waybill/sources.ensure）。"""
    from modules.orders.waybill import sources as _wbs
    ids = [int(x) for x in (request.get_json(force=True) or {}).get("ids") or []]
    have, missing = [], []
    for oid in ids:
        o = orders_mod.get_order(oid)
        ok = bool(o and _wbs.ensure(o)[0])
        (have if ok else missing).append(oid)
    return jsonify({"have": have, "missing": missing})


@bp.get("/api/dashboard")
def dashboard_get():
    return jsonify(extras.dashboard(auth.is_owner()))


@bp.get("/api/aftersales")
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


@bp.get("/api/aftersales/<int:aid>")
def aftersales_one(aid):
    d = extras.as_get(aid)
    return jsonify(_strip_as(d)) if d else err("售后记录不存在", 404)


@bp.post("/api/aftersales")
def aftersales_post():
    b = request.get_json(force=True) or {}
    if b.get("status") and b.get("order_id"):      # v2.38：借售后把订单改成取消 / 拒收，一样要 orders.cancel 权限
        denied = _cancel_denied(int(b["order_id"]), b)
        if denied:
            return denied
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
        chain.order_changed(_uname())
    return jsonify({"id": aid})


@bp.post("/api/aftersales/<int:aid>")
def aftersales_update(aid):
    try:
        d = extras.as_update(aid, request.get_json(force=True) or {}, _uname(), auth.is_owner())
    except ValueError as e:
        return err(str(e))
    return jsonify(_strip_as(d))


@bp.post("/api/aftersales/<int:aid>/close")
def aftersales_close(aid):
    try:
        extras.as_close(aid, _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True})


@bp.post("/api/aftersales/<int:aid>/inspect")
def aftersales_inspect(aid):
    b = request.get_json(force=True) or {}
    try:
        d = extras.as_inspect(aid, b.get("items") or [], b.get("note") or "", _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify(_strip_as(d))


@bp.post("/api/aftersales/<int:aid>/evidence")
def aftersales_evidence_add(aid):
    files = request.files.getlist("files")
    if not files:
        return err("请选择照片或视频")
    try:
        ev = extras.as_evidence_add(aid, files, _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"evidence": ev})


@bp.get("/api/aftersales/<int:aid>/evidence/<path:name>")
def aftersales_evidence_get(aid, name):
    path = os.path.join(extras.evidence_dir(aid), os.path.basename(name))
    if not os.path.isfile(path):
        return err("文件不存在", 404)
    return send_file(path, conditional=True)


@bp.delete("/api/aftersales/<int:aid>/evidence/<path:name>")
def aftersales_evidence_del(aid, name):
    try:
        ev = extras.as_evidence_del(aid, name, _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"evidence": ev})


@bp.get("/api/pack/lookup")
def pack_lookup():
    """打包核对：扫订单号 / 运单号，列出这个订单要装的商品。"""
    from modules.orders import scanning
    code = (request.args.get("code") or "").strip()
    if not code:
        return err("请扫描或输入订单号 / 运单号")
    r = scanning.find_order(code)
    if not r:
        return err(scanning.not_found_msg(code), 404)
    o = orders_mod.get_order(r["id"])
    o["jobs"] = production.list_jobs(order_id=r["id"])
    cfg = load_config()
    for it, m in zip(o.get("items") or [], scanning.modes_for_items(o.get("items") or [], cfg)):
        it.update(m)                          # v2.32：这一行怎么核对：scan 扫商品码 / tap 点一下 / none 不用核对；img 产品图
    o["scan_key"] = scanning.key_setting(cfg)
    _add_pack_info(o)
    return jsonify(_strip_order(o))


@bp.get("/api/pack-boxes")
def pack_boxes():
    """泰国邮政标准纸箱（v2.35）：产品编辑页、打包页选纸箱用。"""
    from core.inventory import boxes
    return jsonify({"ok": True, "boxes": boxes.catalog(), "none": boxes.NONE})


@bp.post("/api/orders/<int:oid>/pack-box")
def order_pack_box(oid):
    """打包时改纸箱：{box: 规格 / "none" / ""（按产品自动）}。"""
    from modules.orders import packbox
    try:
        return jsonify({"ok": True, "box": packbox.set_box(oid, (request.get_json(force=True) or {}).get("box") or "", _uname())})
    except ValueError as e:
        return err(str(e))


@bp.post("/api/pack/done")
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


@bp.get("/print/orders")
def orders_print():
    """打印：pick 拣货/生产汇总单，pack 装箱单（每单一页）。"""
    ids = [int(x) for x in (request.args.get("ids") or "").split(",") if x.strip().isdigit()]
    kind = request.args.get("type") or "pack"
    orders = [o for o in (orders_mod.get_order(i) for i in ids) if o]
    from html import escape as h
    fmt = (lambda t: dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "")
    css = ("body{font:13px 'Microsoft YaHei','Leelawadee UI',sans-serif;margin:16px;color:#111}"
           "table{border-collapse:collapse;width:100%;margin:6px 0}th,td{border:1px solid #999;padding:5px 6px;text-align:left}"
           "th{background:#eee}.pg{page-break-after:always;margin-bottom:24px}h2{margin:4px 0}.note{border:2px solid #000;"
           "padding:6px;margin:6px 0;font-weight:bold}.box{display:inline-block;width:14px;height:14px;border:1px solid #000}"
           "@media print{.noprint{display:none}}")
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>{'拣货单' if kind == 'pick' else '装箱单'}</title>"
           f"<style>{css}</style></head><body><p class='noprint'><button onclick='print()'>打印 / พิมพ์</button></p>"]
    if kind == "pick":
        agg = {}
        for o in orders:
            for it in o["items"]:
                k = (it.get("sku") or "", it.get("color") or "")
                a = agg.setdefault(k, {"name": it.get("name") or "", "qty": 0, "orders": []})
                a["qty"] += it.get("qty") or 1
                a["orders"].append(f"{o['order_no']}×{it.get('qty') or 1}")
        from core import modules as _mods
        _inv = _mods.public("inv")            # v2.33：有成品库存的 SKU 显示在哪个货位，按货位顺序排（走一趟拣完）
        where = {sku: (_inv.where_is(sku) if _inv else []) for (sku, _c) in agg}
        out.append(f"<h2>拣货 / 生产汇总单 ใบรวมสินค้า</h2><p>{len(orders)} 个订单 · 打印时间 {fmt(time.time())}</p>"
                   "<table><tr><th></th><th>货位</th><th>SKU</th><th>商品</th><th>颜色</th><th>数量</th><th>订单</th></tr>")
        _key = getattr(_inv, "sort_key", None) or (lambda c_: (0, c_))
        _none = (2,)                           # 没有货位的排最后
        for (sku, color), a in sorted(agg.items(), key=lambda kv: (_key(where[kv[0][0]][0][0]) if where.get(kv[0][0]) else _none, kv[0])):
            w = "、".join(f"{c_} ×{q_:g}" for c_, q_ in where.get(sku) or []) or "—"
            out.append(f"<tr><td><span class='box'></span></td><td><b>{h(w)}</b></td><td><b>{h(sku)}</b></td><td>{h(a['name'])}</td><td>{h(color)}</td>"
                       f"<td><b>{a['qty']}</b></td><td style='font-size:11px'>{h(', '.join(a['orders']))}</td></tr>")
        out.append("</table>")
        notes = [o for o in orders if o.get("custom_note") or o.get("buyer_note")]
        if notes:
            out.append("<h3>有备注的订单</h3><table><tr><th>订单号</th><th>定制要求 / 买家留言</th></tr>")
            for o in notes:
                out.append(f"<tr><td>{h(o['order_no'])}</td><td>{h(o.get('custom_note') or '')} {h(o.get('buyer_note') or '')}</td></tr>")
            out.append("</table>")
    else:
        for o in orders:
            out.append(f"<div class='pg'><h2>装箱单 ใบแพ็คสินค้า · {h(o['order_no'])}</h2>"
                       f"<p>{h(o.get('platform') or '')} {h(o.get('shop') or '')} · 买家 ผู้ซื้อ：{h(o.get('buyer') or '')} · "
                       f"下单 {fmt(o.get('order_time'))}{' · 最晚发货 ' + fmt(o.get('ship_by')) if o.get('ship_by') else ''}"
                       f"{' · 运单 ' + h(o['tracking_no']) if o.get('tracking_no') else ''}</p>")
            if o.get("custom_note"):
                out.append(f"<div class='note'>定制要求 ความต้องการพิเศษ：{h(o['custom_note'])}</div>")
            if o.get("buyer_note"):
                out.append(f"<div class='note'>买家留言 ข้อความผู้ซื้อ：{h(o['buyer_note'])}</div>")
            out.append("<table><tr><th>✔</th><th>SKU</th><th>商品</th><th>规格/颜色</th><th>数量</th></tr>")
            for it in o["items"]:
                out.append(f"<tr><td><span class='box'></span></td><td><b>{h(it.get('sku') or '')}</b></td><td>{h(it.get('name') or '')}</td>"
                           f"<td>{h(it.get('variation') or it.get('color') or '')}</td><td><b>{it.get('qty') or 1}</b></td></tr>")
            out.append("</table><p>检查 ตรวจ：____　打包 แพ็ค：____</p></div>")
    out.append("</body></html>")
    for o in orders:
        orders_mod.log(o["id"], _uname(), "打印拣货单" if kind == "pick" else "打印装箱单")
    return app.response_class("".join(out), mimetype="text/html")


@bp.get("/print/handover")
def handover_print():
    """交接单打印：给快递员签字。"""
    from html import escape as h
    d = orders_mod.handover_get(int(request.args.get("id") or 0))
    if not d:
        return err("交接单不存在", 404)
    fmt = (lambda t: dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M") if t else "")
    cfg = load_config()
    rows = "".join(f"<tr><td>{i}</td><td><b>{h(o['tracking_no'] or '（无运单号）')}</b></td><td>{h(o['order_no'])}</td>"
                   f"<td>{h(o['platform'] or '')}</td><td>{o['n_items']}</td><td>{'COD ฿' + format(o['cod'], ',.0f') if o['cod'] else ''}</td></tr>"
                   for i, o in enumerate(d["orders"], 1))
    html = (f"<!doctype html><html><head><meta charset='utf-8'><title>交接单 #{d['id']}</title><style>"
            "body{font:13px 'Microsoft YaHei','Leelawadee UI',sans-serif;margin:16px;color:#111}table{border-collapse:collapse;width:100%}"
            "th,td{border:1px solid #999;padding:5px 6px;text-align:left}th{background:#eee}.sig{margin-top:28px;display:flex;gap:60px}"
            "@media print{.noprint{display:none}}</style></head><body><p class='noprint'><button onclick='print()'>打印 / พิมพ์</button></p>"
            f"<h2>发货交接单 ใบส่งมอบพัสดุ #{d['id']}</h2>"
            f"<p>物流 ขนส่ง：<b>{h(d['carrier'] or '-')}</b> · {h(d['method_zh'] or '')} · 寄件人 ผู้ส่ง：{h(cfg.get('sender_name') or '')} "
            f"{h(cfg.get('sender_phone') or '')}<br>共 รวม <b>{d['count']}</b> 件包裹 พัสดุ"
            f"{' · 货到付款合计 ยอด COD ฿' + format(d['cod_total'], ',.0f') if d['cod_total'] else ''} · 打印时间 {fmt(time.time())}</p>"
            "<table><tr><th>#</th><th>运单号 เลขพัสดุ</th><th>订单号</th><th>平台</th><th>件数</th><th>COD</th></tr>"
            f"{rows}</table><div class='sig'><div>交件人 ผู้ส่งมอบ：________________</div><div>快递员 พนักงานขนส่ง：________________</div>"
            "<div>时间 เวลา：________________</div></div></body></html>")
    return app.response_class(html, mimetype="text/html")


@bp.get("/print/item-labels")
def item_labels_print():
    """v2.32：内部商品标签（自产件后处理时贴在袋子上，打包时扫）。?ids=订单id,..."""
    from modules.orders import scanning
    ids = [int(x) for x in (request.args.get("ids") or "").split(",") if x.strip().isdigit()]
    if not ids:
        return err("请先选订单")
    orders = [o for o in (orders_mod.get_order(i) for i in ids) if o]
    return app.response_class(scanning.labels_html(orders), mimetype="text/html")


@bp.get("/print/labels")
def labels_print():
    ids = [int(x) for x in (request.args.get("ids") or "").split(",") if x.strip().isdigit()]
    kind = request.args.get("type") or "self"
    if not ids:
        return err("请先勾选订单")
    if kind == "platform":
        if waybill.enabled() and request.args.get("raw") != "1":     # v2.34：按自定义模板排（加信息区）
            html, have, _miss = waybill.print_html(ids, _uname())
            if not have:
                return err("选中的订单都还没有平台面单", 404)
            return app.response_class(html, mimetype="text/html")
        try:
            data, have, _missing = labels.merged_pdf(ids)
        except ValueError as e:
            return err(str(e))
        if not have:
            return err("选中的订单都还没有平台面单", 404)
        labels.mark_printed(have, _uname(), "平台面单")
        waybill.record(have, _uname(), "平台面单")
        import io as _io
        return send_file(_io.BytesIO(data), mimetype="application/pdf", as_attachment=False,
                         download_name=f"labels_{dt.datetime.now().strftime('%m%d_%H%M')}.pdf")
    orders = [o for o in (orders_mod.get_order(i) for i in ids) if o]
    labels.mark_printed([o["id"] for o in orders], _uname(), "自制面单")
    waybill.record([o["id"] for o in orders], _uname(), "自制面单")
    from modules.orders import carriers          # v2.33：按快递公司的版式（?tpl=flash&size=100x150 可以指定）
    return app.response_class(carriers.html(orders, load_config(), request.args.get("tpl"), request.args.get("size")), mimetype="text/html")


# ---------------- 平台面单框架（v2.34，modules/orders/waybill）----------------
from modules.orders import waybill  # noqa: E402
waybill.init()


@bp.get("/api/waybill/status")
def waybill_status():
    """面单来源（上传 / 各平台接口）、自定义模板、可选的信息项。"""
    return jsonify({"ok": True, **waybill.status()})


@bp.post("/api/waybill/template")
def waybill_template_save():
    return jsonify({"ok": True, "template": waybill.save_template(request.get_json(force=True) or {})})


@bp.get("/print/waybill")
def waybill_print():
    """按模板打印平台面单（不管模板开没开都按模板排；订单页「打印面单」在模板开着时也走这里）。"""
    ids = [int(x) for x in (request.args.get("ids") or "").split(",") if x.strip().isdigit()]
    if not ids:
        return err("请先勾选订单")
    if not waybill.render.available():
        return err("缺少 PDF 转图片组件（pypdfium2）。NAS 重启容器会自动安装；Windows 重新双击 1_setup.bat", 500)
    html, have, _miss = waybill.print_html(ids, _uname())
    if not have:
        return err("选中的订单都还没有平台面单", 404)
    return app.response_class(html, mimetype="text/html")


@bp.get("/print/waybill-preview")
def waybill_preview():
    """设置页预览：?tpl=模板 JSON（不传 = 已保存的模板）。示例订单 + 示例面单。"""
    import json as _json
    try:
        tpl = _json.loads(request.args.get("tpl") or "{}")
    except ValueError:
        tpl = {}
    return app.response_class(waybill.preview_html(tpl if isinstance(tpl, dict) else {}), mimetype="text/html")


@bp.get("/api/waybill/awb/<int:oid>/<int:page>.png")
def waybill_awb(oid, page):
    try:
        data = waybill.awb_image(oid, page)
    except ValueError as e:
        return err(str(e), 404)
    except ImportError:
        return err("缺少 PDF 转图片组件（pypdfium2）", 500)
    resp = app.response_class(data, mimetype="image/png")
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


@bp.get("/print/label-preview")
def label_preview():
    """v2.33：面单模板预览（示例数据）。?carrier=flash&size=100x150"""
    from modules.orders import carriers
    return app.response_class(carriers.preview_html(load_config(), request.args.get("carrier"), request.args.get("size")), mimetype="text/html")


@bp.get("/api/label-templates")
def label_templates():
    from modules.orders import carriers
    return jsonify({"carriers": [{"id": k, "name": v["name"] or "通用", "th": v["th"], "color": v["color"]} for k, v in carriers.CARRIERS.items()],
                    "sizes": [{"id": k, "zh": v} for k, v in carriers.SIZE_ZH.items()]})
