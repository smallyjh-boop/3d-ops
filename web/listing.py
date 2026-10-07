"""导出上架表格、上架状态、类目模板、Shopee 类目。"""
from web.common import *  # noqa: F401,F403

# ---------------- 类目与属性 ----------------
@app.get("/api/categories")
def category_list():
    return jsonify(categories.library())


@app.get("/api/category-fields")
def category_fields():
    cat = categories.get(request.args.get("id"))
    if not cat:
        return err("找不到类目", 404)
    fields = lazada_template.attribute_fields(cat)
    return jsonify({"id": cat["id"], "name": cat["name"], "cat_id": cat["cat_id"],
                    "fields": [{k: f[k] for k in ("key", "label", "required", "options", "tip", "kind")}
                               for f in fields]})


# ---------------- Shopee ----------------
@app.get("/api/shopee/categories")
def shopee_categories():
    q = (request.args.get("q") or "").strip()
    cid = request.args.get("id")
    if cid:
        return jsonify([{"id": cid, "path": shopee.path_of(cid), "name": shopee.display_name(cid)}])
    if not q:
        return jsonify([])
    words = re.split(r"[\s>,，、]+", q)
    if re.search(r"[^\x00-\x7f]", q):
        # 中文/泰文：先让 AI 翻译成 Shopee 类目树用的英文关键词
        if q not in _SP_KW_CACHE:
            try:
                d = ai_copy.extract_json(ai_copy.call(load_config(), "Translate e-commerce search words. Output only JSON.",
                    f'Give 3-6 short English keywords (single words or 2-word phrases, as used in Shopee category names, '
                    f'singular and plural forms) for finding the Shopee category of: "{q}". Return {{"keywords": [...]}}'))
                _SP_KW_CACHE[q] = [str(x) for x in d.get("keywords") or []]
            except ai_copy.AIError as e:
                return err(f"中文/泰文搜索需要 AI（{e}）。也可以用英文关键词，或用下面的逐级选择。")
        words = _SP_KW_CACHE[q]
    res = shopee.search(words, limit=30)
    if q.isdigit() and q in shopee.tree():
        res = [(q, shopee.path_of(q))] + res
    return jsonify([{"id": c, "path": p, "name": shopee.display_name(c),
                     "restricted": shopee.tree()[c][1]} for c, p in res])


@app.get("/api/shopee/attrs")
def shopee_attrs():
    """v2.25：Shopee 类目的属性（必填的在前，带可选值）。"""
    return jsonify({"attrs": shopee.attrs_for(request.args.get("id") or "", 80)})


@app.post("/api/products/<pid>/shopee-attrs")
def shopee_attrs_fill(pid):
    """AI 给 Shopee 必填属性挑值。body 可以带编辑页里没保存的产品。返回 {属性ID: {...}}，页面合进 P.shopee_attrs。"""
    p = request.get_json(silent=True) or store.load(pid)
    try:
        return jsonify({"values": shopee.fill_attrs(load_config(), p)})
    except ai_copy.AIError as e:
        return err(str(e))


@app.get("/api/shopee/tree")
def shopee_tree():
    return jsonify([[cid, path, r] for cid, (path, r) in shopee.tree().items()])


@app.post("/api/export/shopee")
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


# ---------------- 模板、导出 ----------------
@app.get("/api/templates/sync")
def templates_sync_status():
    """v2.25：Lazada 全部类目模板的自动下载进度。"""
    from core import lazada_sync
    return jsonify(lazada_sync.status())


@app.post("/api/templates/sync")
def templates_sync_run():
    """手动开始 / 重新下载全部 Lazada 类目模板（后台做）。{force: true} 全部重新下载。"""
    from core import lazada_sync
    b = request.get_json(silent=True) or {}

    def go():
        from core import bgjobs
        try:
            r = lazada_sync.download_all(lambda i, n: bgjobs.note(stage=f"{i}/{n}"), force=bool(b.get("force")))
        except RuntimeError as e:
            return err(str(e))
        return jsonify(r)
    return maybe_async("下载 Lazada 全部类目模板", go, "templates")


@app.get("/api/templates")
def templates():
    return jsonify(categories.template_files())


@app.post("/api/templates")
def template_upload():
    f = request.files.get("file")
    if not f or not (f.filename or "").lower().endswith(".xlsx"):
        return err("请上传从 Lazada 卖家中心下载的 .xlsx 模板")
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    base = re.sub(r"[^\w.-]", "_", os.path.basename(f.filename))
    path = os.path.join(TEMPLATE_DIR, base)
    f.save(path)
    try:
        sheets = lazada_template.parse(path)
    except Exception as e:
        os.remove(path)
        return err(f"无法读取这个模板：{e}")
    if not sheets:
        os.remove(path)
        return err("这个文件里没有找到 Lazada 类目工作表（需要带 _hide 隐藏表的官方模板）")
    return jsonify({"name": base, "categories": [s["sheet"] for s in sheets]})


@app.delete("/api/templates/<name>")
def template_delete(name):
    """不直接删除，移到 _deleted 文件夹，误删可以找回。"""
    name = os.path.basename(name)
    path = os.path.join(TEMPLATE_DIR, name)
    if not os.path.exists(path):
        return err("找不到模板", 404)
    trash = os.path.join(TEMPLATE_DIR, "_deleted")
    os.makedirs(trash, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.replace(path, os.path.join(trash, f"{stamp}_{name}"))
    return jsonify({"ok": True})


@app.post("/api/export")
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
@app.get("/api/listing/batches")
def listing_batches():
    from core import listing
    return jsonify({"batches": listing.list_batches(int(request.args.get("limit") or 50), request.args.get("platform") or None),
                    "status_zh": listing.STATUS_ZH})


@app.post("/api/listing/status")
def listing_status():
    from core import listing
    b = request.get_json(force=True) or {}
    try:
        n = listing.set_status(b.get("ids") or [], b.get("platform"), b.get("status"), b.get("note"), _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"changed": n})


@app.post("/api/listing/batches/<int:bid>")
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


@app.delete("/api/listing/batches/<int:bid>")
def listing_batch_delete(bid):
    from core import listing
    listing.delete_batch(bid)
    return jsonify({"ok": True})


@app.get("/api/export/<name>")
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
