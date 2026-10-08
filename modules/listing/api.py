"""上架导出模块的接口：导出 Lazada / Shopee 表格、上架批次和状态。v2.31 从 web/listing.py 搬过来。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403

bp = Blueprint("m_listing", __name__)
PREFIXES = ['/api/export', '/api/listing']
PATTERNS = []


@bp.post("/api/export/shopee")
def export_shopee():
    body = request.get_json(force=True) or {}
    ids = body.get("product_ids") or []
    if not ids:
        return err("请至少选择一个产品")
    if not shopee.template_path():
        return err("没有 Shopee 模板（templates_shopee 文件夹）")
    cfg = load_config()
    prods = [store.load(i) for i in ids]
    errors, warnings = [], []
    for p in prods:
        e, w = _check_shopee(cfg, p)
        name = f"{p['id']} {p.get('name_zh', '')}"
        errors += [f"{name}：{x}" for x in e]
        warnings += [f"{name}：{x}" for x in w]
    if errors and not body.get("force"):
        return jsonify({"ok": False, "errors": errors, "warnings": warnings})
    cfg_sp = dict(cfg)
    if float(cfg.get("shopee_fee_rate") or 0) > 0:
        cfg_sp["platform_fee_rate"] = float(cfg["shopee_fee_rate"])
    pr = {p["id"]: pricing.price_product(cfg_sp, p) for p in prods}
    rows = shopee.build_rows(prods, pr, cfg)
    name = shopee.export_name()
    n = shopee.fill(rows, os.path.join(EXPORT_DIR, name))
    for p in prods:
        if not p.get("exported_at"):
            p["exported_at"] = int(time.time())
        p["shopee_exported_at"] = int(time.time())
        store.save(p)
    _mark_stock(prods, "shopee")
    files = [{"file": name, "rows": n, "categories": ["Shopee"]}]
    batch = _after_export("shopee", [p["id"] for p in prods], files, body)
    return jsonify({"ok": True, "files": files, "rows": n, "errors": errors, "warnings": warnings, "batch": batch})


@bp.post("/api/export")
def export():
    body = request.get_json(force=True) or {}
    ids = body.get("product_ids") or []
    if not ids:
        return err("请至少选择一个产品")
    cfg = load_config()
    prods = [store.load(i) for i in ids]
    errors, warnings, groups = [], [], {}
    for p in prods:
        e, w = _check(cfg, p)
        name = f"{p['id']} {p.get('name_zh', '')}"
        errors += [f"{name}：{x}" for x in e]
        warnings += [f"{name}：{x}" for x in w]
        cat = categories.get((p.get("category") or {}).get("id"))
        if cat:
            groups.setdefault(cat["template"], {}).setdefault(cat["sheet"], []).append(p)
    if errors and not body.get("force"):
        return jsonify({"ok": False, "errors": errors, "warnings": warnings})
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    files_out, total = [], 0
    for tpl, sheets in groups.items():
        rows_by_sheet = {}
        for sheet, plist in sheets.items():
            pr = {p["id"]: pricing.price_product(cfg, p) for p in plist}
            cat = categories.get(f"{tpl}|{sheet}")
            rows_by_sheet[sheet] = lazada_template.build_rows(plist, pr, cfg, cat)
        label = "_".join(sheets)[:60]
        out_name = f"lazada_upload_{label}_{stamp}.xlsx"
        n = lazada_template.fill_multi(os.path.join(TEMPLATE_DIR, tpl), rows_by_sheet,
                                       os.path.join(EXPORT_DIR, out_name))
        total += n
        files_out.append({"file": out_name, "rows": n, "categories": list(sheets)})
        for plist in sheets.values():
            for p in plist:
                if not p.get("exported_at"):
                    p["exported_at"] = int(time.time())
                store.save(p)
    if not files_out:
        return jsonify({"ok": False, "errors": errors or ["所选产品都没有可用的类目"], "warnings": warnings})
    done = [p["id"] for sheets in groups.values() for plist in sheets.values() for p in plist]
    _mark_stock([p for sheets in groups.values() for plist in sheets.values() for p in plist], "lazada")
    batch = _after_export("lazada", done, files_out, body)
    return jsonify({"ok": True, "files": files_out, "rows": total, "errors": errors, "warnings": warnings, "batch": batch})


# ---------------- 上架进度 ----------------
@bp.get("/api/listing/batches")
def listing_batches():
    from core import listing
    return jsonify({"batches": listing.list_batches(int(request.args.get("limit") or 50), request.args.get("platform") or None),
                    "status_zh": listing.STATUS_ZH})


@bp.post("/api/listing/status")
def listing_status():
    from core import listing
    b = request.get_json(force=True) or {}
    try:
        n = listing.set_status(b.get("ids") or [], b.get("platform"), b.get("status"), b.get("note"), _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"changed": n})


@bp.post("/api/listing/batches/<int:bid>")
def listing_batch_update(bid):
    from core import listing
    b = request.get_json(force=True) or {}
    try:
        if b.get("name") is not None:
            return jsonify(listing.rename_batch(bid, b["name"]))
        n = listing.batch_set(bid, b.get("status") or "uploaded", b.get("note"), _uname(), b.get("only_pending", True))
    except ValueError as e:
        return err(str(e))
    return jsonify({"changed": n, "batch": listing.get_batch(bid)})


@bp.delete("/api/listing/batches/<int:bid>")
def listing_batch_delete(bid):
    from core import listing
    listing.delete_batch(bid)
    return jsonify({"ok": True})


@bp.get("/api/export/<name>")
def export_download(name):
    path = os.path.join(EXPORT_DIR, os.path.basename(name))
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=os.path.basename(name))


def _mark_stock(prods, platform):
    """导出的表格里的库存就是平台上的库存：记为已同步（v2.16 待同步库存用）。出错不影响导出。"""
    try:
        from core import stockcalc
        stockcalc.mark_exported(prods, platform, _uname())
    except Exception as e:  # noqa: BLE001
        from core import diag
        diag.log.warning("导出后记录库存失败：%s", e)
