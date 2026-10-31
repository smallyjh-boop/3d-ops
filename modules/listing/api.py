"""上架导出模块的接口：导出 Lazada / Shopee 表格、上架批次和状态。v2.31 从 web/listing.py 搬过来。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403

bp = Blueprint("m_listing", __name__)
PREFIXES = ['/api/export', '/api/listing']


# ---------------- v2.41.2：直接推到 Lazada（接口） ----------------
@bp.post("/api/listing/lazada/push")
def lazada_push_products():
    from . import lazada_push
    b = request.get_json(force=True) or {}
    ids = b.get("product_ids") or []
    if not ids:
        return err("请至少选择一个产品")
    user, force = _uname(), bool(b.get("force"))

    def run():
        try:
            return jsonify(lazada_push.push(ids, user, force=force))
        except lazada_push.PushError as e:
            return err(str(e))
    return maybe_async(f"推送到 Lazada（{len(ids)} 个）", run, "lz_push")      # v2.43：?async=1 时后台跑，任务中心看进度


@bp.post("/api/listing/lazada/status-sync")
def lazada_status_sync():
    """v2.43：接口推送过的产品，向 Lazada 查审核结果（平时每 30 分钟自动查一次）。"""
    from . import lazada_push
    b = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(lazada_push.sync_status(_uname(), b.get("product_ids") or None))
    except lazada_push.PushError as e:
        return err(str(e))


# ---------------- v2.43：上架工作台（缺什么、原地修、AI 补齐） ----------------
@bp.get("/api/listing/issues/<pid>")
def listing_issues(pid):
    from . import workbench
    try:
        return jsonify(workbench.issues(pid, request.args.get("platform") or "lazada"))
    except FileNotFoundError:
        return err("产品不存在", 404)


@bp.post("/api/listing/fix/<pid>")
def listing_fix(pid):
    from . import workbench
    b = request.get_json(force=True, silent=True) or {}
    try:
        workbench.fix(pid, b.get("action") or "", _uname())
        return jsonify(workbench.issues(pid, b.get("platform") or "lazada"))
    except (ValueError, FileNotFoundError) as e:
        return err(str(e))


@bp.post("/api/listing/ai-fill")
def listing_ai_fill():
    from . import workbench
    b = request.get_json(force=True, silent=True) or {}
    ids = b.get("product_ids") or []
    if not ids:
        return err("请至少选择一个产品")
    user, plat = _uname(), b.get("platform") or "lazada"
    return maybe_async(f"AI 补齐上架资料（{len(ids)} 个）", lambda: jsonify(workbench.ai_fill(ids, plat, user)), "ai_fill")


@bp.post("/api/listing/lazada/stock-sync")
def lazada_stock_sync():
    from . import lazada_push
    try:
        return jsonify(lazada_push.sync_stock(_uname(), "api"))
    except lazada_push.PushError as e:
        return err(str(e))
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
            p["exported_at"] = int(time.time())          # 锁住 SKU（Shopee 上也用这些 SKU）
            p["exported_first"] = "shopee"               # v2.40：只导出过 Shopee，Lazada 还不算「待上传」
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
                p.pop("exported_first", None)            # v2.40：Lazada 也导出过了
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
