"""产品资料、图片、修图、模型库、场景图、分组。"""
from web.common import *  # noqa: F401,F403

# ---------------- 产品 ----------------
@app.get("/api/products")
def products():
    cfg = load_config()
    lib = categories.library()
    names = {c["id"]: c["name"] for c in lib}
    names_th = {c["id"]: " > ".join(c["path"].split(" > ")[-2:]) for c in lib if c["path"]}
    out = []
    for item in store.list_products():
        p = store.load(item["id"])
        errs, warns = _check(cfg, p)
        sp_e, sp_w = _check_shopee(cfg, p)
        item.update({
            "sp_errors": len(sp_e), "sp_warnings": len(sp_w),
            "category": names.get((p.get("category") or {}).get("id"), ""),
            "category_id": (p.get("category") or {}).get("id", ""),
            "category_th": names_th.get((p.get("category") or {}).get("id"), ""),
            "errors": len(errs), "warnings": len(warns),
            "skus": [v.get("sku") for v in p.get("variants", [])],
            "colors": [v.get("opt1_zh") for v in p.get("variants", []) if v.get("opt1_zh")],
            "exported": bool(p.get("exported_at") or p.get("shopee_exported_at")),
            "lz": _lst(p, "lazada"), "sp": _lst(p, "shopee"), "active": p.get("active", True) is not False,
            "updated_at": p.get("updated_at") or 0,
            "groups": p.get("groups") or [], "material": p.get("material") or "",
            "has_model": bool(p.get("model")), "keywords": p.get("keywords") or "",
            "draft": bool(p.get("draft")), "from_curator": bool(p.get("source")),
            "lead_days": p.get("lead_days"), "has_recipe": bool(p.get("recipe")),
            "thumb": next((f"/files/{p['id']}/{'out' if im.get('processed') else 'raw'}/{im['file']}" for im in p.get("images", []) if im.get("file")), ""),
        })
        out.append(item)
    _enrich_products(out)
    return jsonify(out)


@app.post("/api/products/new")
def product_new():
    cfg = load_config()
    p = store.blank_product(store.new_id(_prefix(cfg)))
    codes.ensure_skus(cfg, p)
    store.save(p)
    return jsonify(p)


@app.get("/api/products/<pid>")
def product_get(pid):
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("找不到这个产品", 404)
    codes.ensure_skus(load_config(), p)
    return jsonify(p)


@app.post("/api/products/<pid>")
def product_save(pid):
    p = request.get_json(force=True)
    c = _conflict(pid, p)
    if c:
        return c
    return jsonify(_save_from_client(pid, p))


@app.post("/api/products/<pid>/regen-skus")
def regen_skus(pid):
    p = request.get_json(force=True)
    c = _conflict(pid, p)
    if c:
        return c
    if p.get("exported_at") and not request.args.get("force"):
        return err("这个产品已经导出到 Lazada，改 SKU 会导致平台对不上。确实要改请再点一次确认。", 409)
    for v in p.get("variants", []):
        v["sku"] = ""
    p["exported_at"] = None
    old = store.load(pid)
    old["exported_at"] = None
    store.save(old)
    return jsonify(_save_from_client(pid, p))


@app.delete("/api/products/<pid>")
def product_delete(pid):
    store.delete(pid)
    return jsonify({"ok": True})


@app.post("/api/products/<pid>/duplicate")
def product_duplicate(pid):
    cfg = load_config()
    src = store.load(pid)
    p = dict(src)
    p["id"] = store.new_id(_prefix(cfg))
    p["images"], p["white_bg"], p["exported_at"] = [], None, None
    for v in p.get("variants", []):
        v["image"], v["sku"] = "", ""
    p["name_zh"] = (src.get("name_zh") or "") + "（副本）"
    codes.ensure_skus(cfg, p)
    store.save(p)
    return jsonify(p)


@app.post("/api/pricing")
def pricing_preview():
    data = request.get_json(force=True) or {}
    cfg = load_config()
    codes.ensure_skus(cfg, data)
    return jsonify({"rows": auth.strip_prices(pricing.price_product(cfg, data), auth.current_user()),
                    "summary": pricing.cost_summary(cfg) if auth.is_owner() else None,
                    "skus": [v.get("sku") for v in data.get("variants", [])],
                    "colors": [(lambda c: c[1] if c else "")(codes.find_color(cfg, v.get("opt1_zh")))
                               for v in data.get("variants", [])]})


@app.post("/api/products/<pid>/check")
def product_check(pid):
    p = request.get_json(force=True) or store.load(pid)
    errs, warns = _check(load_config(), p)
    return jsonify({"errors": errs, "warnings": warns})


@app.post("/api/products/<pid>/ai-category")
def ai_category(pid):
    p = request.get_json(force=True)
    cfg = load_config()
    if not categories.library():
        return err("还没有任何 Lazada 模板。请先在「导出 Lazada 表格」页上传类目模板。")
    try:
        m = attributes.match_category(cfg, p)
    except ai_copy.AIError as e:
        return err(str(e))
    old_manual = (p.get("category") or {}).get("status") == "manual"
    if old_manual and not request.args.get("override"):
        m["id"] = p["category"]["id"]
        m["status"] = "manual"
    p["category"] = {**(p.get("category") or {}), **m}
    cat = categories.get(m["id"])
    if cat:
        p["category"]["cat_id"] = cat["cat_id"]
        _apply_fill(cfg, p, cat)
    p = _save_from_client(pid, p)
    return jsonify(p)


@app.post("/api/products/<pid>/fill-attrs")
def fill_attrs(pid):
    p = request.get_json(force=True)
    cfg = load_config()
    cat = categories.get((p.get("category") or {}).get("id"))
    if not cat:
        return err("先选择类目")
    p["category"]["cat_id"] = cat["cat_id"]
    use_ai = bool((cfg.get("ai_api_key") or "").strip())
    _apply_fill(cfg, p, cat, use_ai=use_ai)
    p = _save_from_client(pid, p)
    return jsonify({"product": p, "used_ai": use_ai})


@app.post("/api/products/<pid>/ai-shopee-category")
def ai_shopee_category(pid):
    p = request.get_json(force=True)
    cfg = load_config()
    try:
        p["shopee_category"] = attributes.match_shopee_category(cfg, p)
    except ai_copy.AIError as e:
        return err(str(e))
    return jsonify(_save_from_client(pid, p))


@app.post("/api/products/<pid>/check-shopee")
def product_check_shopee(pid):
    p = request.get_json(force=True) or store.load(pid)
    errs, warns = _check_shopee(load_config(), p)
    return jsonify({"errors": errs, "warnings": warns})


# ---------------- 3D 模型 / 克数时长 ----------------
@app.get("/api/colors")
def colors():
    return jsonify(codes.color_hex(load_config()))


@app.post("/api/products/<pid>/model")
def model_upload(pid):
    f = request.files.get("file")
    ext = os.path.splitext((f.filename if f else "") or "")[1].lower()
    if not f or ext not in (".stl", ".3mf"):
        return err("请上传 .stl 或 .3mf 模型文件")
    from core import filemgr
    tmp = os.path.join(DATA_DIR, "tmp")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, uuid.uuid4().hex + ext)
    try:
        has_model = bool((store.load(pid).get("model") or {}).get("file"))
    except FileNotFoundError:
        has_model = False
    if has_model and not auth.has_perm(auth.current_user() or {"role": "owner"}, "models.change"):
        return err(_no_perm("models.change"), 403)
    f.save(path)
    fname = f.filename

    def go():
        try:
            r = filemgr.set_model(pid, path, fname, _uname())
        except (ValueError, OSError) as e:
            return err(f"模型文件读不了：{e}")
        finally:
            if os.path.exists(path):
                os.remove(path)
        p = r["product"]
        p["_model_replaced"] = r["replaced"]
        p["_files_reset"] = r["files_reset"]
        return jsonify(p)
    return maybe_async(f"上传模型 {pid}", go, "model", pid)    # v2.20：?async=1 时后台读模型（大文件交给电脑）


@app.post("/api/products/<pid>/model/metrics")
def model_metrics(pid):
    m = request.get_json(force=True) or {}
    cfg = load_config()
    p = store.load(pid)
    if not p.get("model"):
        return err("还没有上传模型")
    est = slicer.estimate(_advised_cfg(cfg, p), m, p.get("material", "PLA"))
    p["model"]["metrics"] = {"volume_mm3": m.get("volume_mm3"), "area_mm2": m.get("area_mm2"), "size": m.get("size")}
    p["model"]["estimate"] = est
    store.save(p)
    return jsonify({"estimate": est, "product": p})


@app.post("/api/products/<pid>/print-advice")
def print_advice_api(pid):
    """AI 打印建议 + 产品描述。body: analysis（模型几何分析）, prompt, image（渲染图 dataURL，可选）"""
    from core import print_advice
    body = request.get_json(force=True) or {}
    cfg = load_config()
    p = store.load(pid)
    img = body.get("image") or ""
    if "," in img:
        img = img.split(",", 1)[1]
    try:
        adv = print_advice.advise(cfg, p, body.get("analysis") or {}, body.get("prompt") or "", img or None)
    except ai_copy.AIError as e:
        return err(str(e))
    adv["analysis"] = body.get("analysis") or {}
    adv["prompt"] = body.get("prompt") or ""
    adv["created_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    adv["applied"] = bool((p.get("print_advice") or {}).get("applied"))
    p["print_advice"] = adv
    store.save(p)
    return jsonify({"product": p})


@app.post("/api/products/<pid>/print-advice/apply")
def print_advice_apply(pid):
    """applied=true：估算和 OrcaSlicer 自动切片按建议参数来；false：恢复默认参数。"""
    body = request.get_json(force=True) or {}
    p = store.load(pid)
    if not p.get("print_advice"):
        return err("还没有打印建议")
    p["print_advice"]["applied"] = bool(body.get("applied", True))
    cfg = load_config()
    mt = (p.get("model") or {}).get("metrics")
    if mt and mt.get("volume_mm3"):
        p["model"]["estimate"] = slicer.estimate(_advised_cfg(cfg, p), mt, p.get("material", "PLA"))
    store.save(p)
    return jsonify({"product": p})


@app.post("/api/products/<pid>/slice")
def model_slice(pid):
    body = request.get_json(force=True) or {}
    return maybe_async(f"切片 {pid}", lambda: _model_slice(pid, body), "slice", pid)


def _model_slice(pid, body):
    cfg = load_config()
    p = store.load(pid)
    m = p.get("model")
    if not m:
        return err("还没有上传模型")
    path = os.path.join(store.image_dir(pid, "model"), m["file"])
    try:
        from core import print_advice
        adv = p.get("print_advice") or {}
        ov = print_advice.slice_overrides(adv) if adv.get("applied") else None
        r = slicer.orca_slice(cfg, path, int(body.get("printer", 0)), p.get("material", "PLA"), overrides=ov)
    except slicer.SliceError as e:
        return err(str(e))
    _learn(cfg, p, r.get("grams"))
    return jsonify(r)


@app.post("/api/products/<pid>/images/rendered")
def images_rendered(pid):
    """保存浏览器里渲染/合成好的图（商品图或场景图）。"""
    body = request.get_json(force=True) or {}
    p = store.load(pid)
    items = []
    for item in body.get("images") or []:
        try:
            items.append({"img": _decode_data_url(item.get("data") or ""), "kind": item.get("kind", ""),
                          "color": item.get("color", "")})
        except Exception:
            continue
    added = _add_images(p, items, replace_renders=body.get("replace_renders", True),
                        white_bg=bool(body.get("white_bg")))
    return jsonify({"product": p, "added": len(added)})


# ---------------- 卖点图（AI 推荐文字，人确认位置和内容） ----------------
@app.get("/fonts/thai.css")
def fonts_css():
    from core import adimg
    r = app.response_class(adimg.thai_css(), mimetype="text/css")
    r.headers["Cache-Control"] = "no-cache"
    return r


@app.get("/fonts/f/<name>")
def fonts_file(name):
    from core import adimg
    return send_from_directory(adimg.FONT_DIR, os.path.basename(name), max_age=31536000)


@app.post("/api/products/<pid>/ad/suggest")
def ad_suggest(pid):
    from core import adimg
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("产品不存在", 404)
    policy = ""
    try:
        from core import modules as _mods
        s = _mods.public("cs").data.settings()
        policy = f"发货：{s.get('ship_policy', '')}\n定制：{s.get('custom_policy', '')}"
    except Exception:  # noqa: BLE001
        pass
    try:
        return jsonify(adimg.suggest(load_config(), p, policy))
    except ai_copy.AIError as e:
        return err(f"AI 出错：{e}")


@app.post("/api/products/<pid>/ad/save")
def ad_save(pid):
    """保存卖点图：浏览器里合成好的图 + 设计稿（以后可以再打开修改）。同一个设计再次保存会替换原来那张图。"""
    from PIL import Image
    from core import adimg
    b = request.get_json(force=True) or {}
    try:
        p = store.load(pid)
        img = _decode_data_url(b.get("data") or "")
    except FileNotFoundError:
        return err("产品不存在", 404)
    except Exception:
        return err("图片数据不对")
    design = b.get("design") or {}
    size = int(load_config()["image_size"])
    if img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    old = (p.get("ad_designs") or {}).get(design.get("id") or "") or {}
    name = f"a_{uuid.uuid4().hex[:10]}.jpg"
    for sub in ("raw", "out"):
        img.save(os.path.join(store.image_dir(pid, sub), name), "JPEG", quality=95, subsampling=0)
    did = adimg.save_design(p, design, name)
    entry = {"file": name, "raw": name, "processed": True, "url": "", "ad": did}
    imgs = p.setdefault("images", [])
    pos = next((i for i, im in enumerate(imgs) if old.get("file") and im.get("file") == old.get("file")), None)
    if pos is not None:
        imgs[pos] = entry                       # 原位替换（保持图片顺序）
        for sub in ("raw", "out"):
            try:
                os.remove(os.path.join(store.image_dir(pid, sub), old["file"]))
            except OSError:
                pass
    else:
        at = 1 if imgs else 0                   # 新的卖点图放在主图后面
        if b.get("as_main"):
            at = 0
        imgs.insert(at, entry)
    store.save(p)
    return jsonify({"product": p, "design_id": did, "file": name})


# ---------------- 场景图 ----------------
@app.get("/api/scenes")
def scenes_list():
    return jsonify({"library": scenes.library(),
                    "presets": [{"key": k, "name": v[0]} for k, v in scenes.PRESETS.items()],
                    "bg_presets": [{"key": k, "name": v[0]} for k, v in scenes.BG_PRESETS.items()]})


@app.post("/api/scenes/ai")
def scenes_ai_bg():
    """AI 生成一张空背景存进背景库（不含产品，所有产品通用）。"""
    b = request.get_json(force=True) or {}
    try:
        sid = scenes.ai_background(load_config(), b.get("preset") or "desk_wood", b.get("extra") or "")
    except scenes.SceneError as e:
        return err(str(e))
    except Exception as e:
        return err(f"生成失败：{e}")
    return jsonify({"added": sid, "library": scenes.library()})


@app.post("/api/scenes")
def scenes_upload():
    fs = request.files.getlist("files")
    if not fs:
        return err("请选择背景照片")
    try:
        ids = [scenes.add_user(f, f.filename) for f in fs[:20]]
    except scenes.SceneError as e:
        return err(str(e))
    return jsonify({"added": ids, "library": scenes.library()})


@app.post("/api/scenes/<sid>")
def scenes_update(sid):
    b = request.get_json(force=True) or {}
    scenes.update_user(sid, floor_y=b.get("floor_y"), scale=b.get("scale"), name=b.get("name"))
    return jsonify({"library": scenes.library()})


@app.delete("/api/scenes/<sid>")
def scenes_delete(sid):
    try:
        scenes.delete_user(sid)
    except scenes.SceneError as e:
        return err(str(e))
    return jsonify({"library": scenes.library()})


@app.get("/scenes/<sid>")
def scenes_file(sid):
    return send_from_directory(scenes.USER_DIR, sid)


@app.post("/api/products/<pid>/scene-ai")
def scene_ai(pid):
    """AI 生成一张场景图。body: image（产品透明 PNG 或白底图 dataURL）, scene（预设 key 或自己写的场景描述）, extra"""
    b = request.get_json(force=True) or {}
    p = store.load(pid)
    cfg = load_config()
    if not b.get("image"):
        return err("没有产品图")
    try:
        img, prompt = scenes.ai_generate(cfg, p, b.get("scene") or "desk", b["image"], b.get("extra") or "")
    except scenes.SceneError as e:
        return err(str(e))
    except Exception as e:  # 网络等
        return err(f"生成失败：{e}")
    added = _add_images(p, [{"img": img, "kind": "scene", "color": b.get("color", ""), "note": "AI"}])
    return jsonify({"product": p, "added": len(added), "prompt": prompt})


# ---------------- 图片 ----------------
@app.get("/files/<pid>/<kind>/<name>")
def files(pid, kind, name):
    if kind not in ("raw", "out", "model", "source_files"):
        abort(404)
    return send_from_directory(store.image_dir(pid, kind), name, as_attachment=kind == "source_files")


@app.post("/api/products/<pid>/images")
def image_upload(pid):
    p = store.load(pid)
    added = []
    for f in request.files.getlist("files"):
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in ALLOWED_IMG:
            continue
        name = f"{uuid.uuid4().hex[:10]}{ext}"
        f.save(os.path.join(store.image_dir(pid, "raw"), name))
        p.setdefault("images", []).append({"file": name, "raw": name, "processed": False, "url": ""})
        added.append(name)
    if not added:
        return err("没有可用的图片（支持 jpg/png/webp）")
    store.save(p)
    return jsonify(p)


@app.post("/api/products/<pid>/images/process")
def image_process(pid):
    body = request.get_json(force=True) or {}
    return maybe_async(f"处理图片 {pid}", lambda: _image_process(pid, body), "image", pid)


def _image_process(pid, body):
    remove_bg = bool(body.get("remove_bg"))
    only = body.get("only")
    cfg = load_config()
    p = store.load(pid)
    done = 0
    for img in p.get("images", []):
        if only and img["raw"] not in only:
            continue
        if img.get("ad") or (not only and (img.get("scene") or img.get("render"))):
            continue  # 卖点图、渲染图、场景图已经是成品，批量处理时跳过
        src = os.path.join(store.image_dir(pid, "raw"), img["raw"])
        out_name = os.path.splitext(img["raw"])[0] + ".jpg"
        images.process(src, os.path.join(store.image_dir(pid, "out"), out_name),
                       size=int(cfg["image_size"]), remove_bg=remove_bg,
                       fill_ratio=float(cfg["image_fill_ratio"]))
        img.update({"file": out_name, "processed": True, "url": ""})
        done += 1
    store.save(p)
    return jsonify({"product": p, "processed": done})


@app.post("/api/products/<pid>/images/white")
def image_white(pid):
    body = request.get_json(force=True) or {}
    return maybe_async(f"白底图 {pid}", lambda: _image_white(pid, body), "image", pid)


def _image_white(pid, body):
    raw = body.get("raw")
    cfg = load_config()
    p = store.load(pid)
    img = next((i for i in p.get("images", []) if i["raw"] == raw), None)
    if not img:
        return err("找不到这张图片")
    src = os.path.join(store.image_dir(pid, "raw"), raw)
    name = "white_" + os.path.splitext(raw)[0] + ".jpg"
    images.process(src, os.path.join(store.image_dir(pid, "out"), name),
                   size=int(cfg["image_size"]), remove_bg=bool(body.get("remove_bg", True)),
                   fill_ratio=float(cfg["image_fill_ratio"]))
    p["white_bg"] = {"file": name, "url": ""}
    store.save(p)
    return jsonify(p)


@app.get("/api/imgtool/status")
def imgtool_status():
    return jsonify(imgtools.status())


@app.post("/api/imgtool/removebg")
def imgtool_removebg():
    b = request.get_json(force=True) or {}
    return maybe_async("抠图", lambda: _removebg(b), "removebg")


def _removebg(b):
    try:
        out = imgtools.remove_bg(imgtools.from_data_url(b.get("data")), b.get("model") or "isnet")
    except (ValueError, RuntimeError) as e:
        return err(str(e))
    return jsonify({"data": imgtools.to_data_url(out)})


@app.post("/api/imgtool/inpaint")
def imgtool_inpaint():
    b = request.get_json(force=True) or {}
    return maybe_async("去水印 / 杂物", lambda: _inpaint(b), "inpaint")


def _inpaint(b):
    try:
        img = imgtools.from_data_url(b.get("data"))
        out, used = imgtools.inpaint(img, imgtools.from_data_url(b.get("mask")), b.get("method") or "auto")
    except (ValueError, RuntimeError) as e:
        return err(str(e))
    except Exception as e:  # noqa: BLE001  模型 / OpenCV 出错
        return err(f"去除失败：{e}")
    return jsonify({"data": imgtools.to_data_url(out, "PNG" if out.mode == "RGBA" else "JPEG"), "method": used})


@app.post("/api/imgtool/install-lama")
def imgtool_install_lama():
    if not auth.is_owner() and auth.current_user():
        return err("只有老板可以安装组件", 403)
    return jsonify(imgtools.install_lama())


@app.post("/api/products/<pid>/images/edited")
def image_edited(pid):
    """保存修好的图：mode=new 加成一张新图（排在原图后面）；mode=replace 替换原图（第一次替换时备份原图，可以恢复）。"""
    b = request.get_json(force=True) or {}
    try:
        p = store.load(pid)
        img = imgtools.from_data_url(b.get("data"))
    except FileNotFoundError:
        return err("产品不存在", 404)
    except ValueError as e:
        return err(str(e))
    imgs = p.setdefault("images", [])
    idx = next((i for i, x in enumerate(imgs) if x["raw"] == b.get("raw")), None)
    alpha = img.mode in ("RGBA", "LA") and img.getchannel("A").getextrema()[0] < 250
    rawdir = store.image_dir(pid, "raw")

    def write(path):
        if path.lower().endswith(".png"):
            img.save(path, "PNG")
        else:
            flat = Image.new("RGB", img.size, (255, 255, 255))
            flat.paste(img.convert("RGBA"), (0, 0), img.convert("RGBA"))
            flat.save(path, "JPEG", quality=93)
    if b.get("mode") == "replace" and idx is not None:
        it = imgs[idx]
        if it.get("ad"):
            return err("卖点图请用「改卖点图」修改")
        bdir = os.path.join(rawdir, "_orig")
        os.makedirs(bdir, exist_ok=True)
        src = os.path.join(rawdir, it["raw"])
        if os.path.exists(src) and not os.path.exists(os.path.join(bdir, it["raw"])):
            shutil.copyfile(src, os.path.join(bdir, it["raw"]))
        stem, ext = os.path.splitext(it["raw"])
        new_raw = it["raw"] if (ext.lower() == ".png") == alpha else stem + (".png" if alpha else ".jpg")
        write(os.path.join(rawdir, new_raw))
        if new_raw != it["raw"]:
            if os.path.exists(os.path.join(bdir, it["raw"])):
                shutil.move(os.path.join(bdir, it["raw"]), os.path.join(bdir, new_raw))
            if os.path.exists(src):
                os.remove(src)
            for v in p.get("variants", []):
                if v.get("image") == it["raw"]:
                    v["image"] = new_raw
        it.update(raw=new_raw, file=new_raw, processed=False, url="", edited=True, has_orig=True)
    else:
        name = f"{uuid.uuid4().hex[:10]}{'.png' if alpha else '.jpg'}"
        write(os.path.join(rawdir, name))
        new = {"file": name, "raw": name, "processed": False, "url": "", "edited": True}
        imgs.insert(idx + 1 if idx is not None else len(imgs), new)
    store.save(p)
    return jsonify(p)


@app.post("/api/products/<pid>/images/restore")
def image_restore(pid):
    """恢复修图前的原图。"""
    b = request.get_json(force=True) or {}
    p = store.load(pid)
    it = next((x for x in p.get("images", []) if x["raw"] == b.get("raw")), None)
    bk = os.path.join(store.image_dir(pid, "raw"), "_orig", (it or {}).get("raw") or "")
    if not it or not os.path.isfile(bk):
        return err("没有修图前的原图")
    with Image.open(bk) as im:
        im.load()
        orig = im.copy()
    path = os.path.join(store.image_dir(pid, "raw"), it["raw"])
    if it["raw"].lower().endswith(".png"):
        orig.save(path, "PNG")
    else:
        orig.convert("RGB").save(path, "JPEG", quality=95)
    os.remove(bk)
    it.update(file=it["raw"], processed=False, url="", edited=False, has_orig=False)
    store.save(p)
    return jsonify(p)


@app.post("/api/products/<pid>/images/reorder")
def image_reorder(pid):
    body = request.get_json(force=True) or {}
    order = body.get("order") or []
    p = store.load(pid)
    by_raw = {i["raw"]: i for i in p.get("images", [])}
    p["images"] = [by_raw[r] for r in order if r in by_raw]
    for r, i in by_raw.items():
        if r in order:
            continue
        paths = [os.path.join(store.image_dir(pid, "raw"), i["raw"])]
        if i.get("processed"):
            paths.append(os.path.join(store.image_dir(pid, "out"), i["file"]))
        for path in paths:
            if os.path.exists(path):
                os.remove(path)
        for v in p.get("variants", []):
            if v.get("image") == i["raw"]:
                v["image"] = ""
    store.save(p)
    return jsonify(p)


@app.post("/api/products/<pid>/images/host")
def image_host(pid):
    cfg = load_config()
    p = store.load(pid)
    n = 0
    targets = list(p.get("images", []))
    if p.get("white_bg"):
        targets.append(p["white_bg"])
    for img in targets:
        if img.get("url"):
            continue
        folder = "out" if img.get("processed") or img["file"].startswith("white_") else "raw"
        path = os.path.join(store.image_dir(pid, folder), img["file"])
        try:
            img["url"] = imghost.upload_imgbb(cfg.get("imgbb_api_key"), path)
        except imghost.HostError as e:
            store.save(p)
            return err(str(e))
        n += 1
    store.save(p)
    return jsonify({"product": p, "uploaded": n})


@app.post("/api/products/<pid>/images/url")
def image_set_url(pid):
    body = request.get_json(force=True) or {}
    p = store.load(pid)
    target = p.get("white_bg") if body.get("raw") == "__white__" else \
        next((i for i in p.get("images", []) if i["raw"] == body.get("raw")), None)
    if target is None:
        return err("找不到这张图片")
    target["url"] = (body.get("url") or "").strip()
    store.save(p)
    return jsonify(p)


@app.post("/api/products/<pid>/keywords")
def ai_keywords(pid):
    """AI 关键词扩展：按泰国平台搜索习惯列出所有相关搜索词。"""
    from core import keywords
    p = request.get_json(force=True) or store.load(pid)
    try:
        plan = keywords.research(load_config(), p, _cat_name(p))
    except ai_copy.AIError as e:
        return err(str(e))
    return jsonify({"plan": plan, "keywords": keywords.keywords_field(plan)})


@app.post("/api/products/<pid>/ai")
def ai_generate(pid):
    """生成文案。还没有关键词扩展时先自动做一次。"""
    p = request.get_json(force=True) or store.load(pid)
    return maybe_async(f"AI 文案 {pid}", lambda: _ai_generate(p), "ai", pid)


def _ai_generate(p):
    from core import keywords
    cfg = load_config()
    try:
        plan = p.get("keyword_plan")
        new_plan = None
        if not plan:
            plan = new_plan = keywords.research(cfg, p, _cat_name(p))
        data = ai_copy.generate_copy(cfg, p, plan)
    except ai_copy.AIError as e:
        return err(str(e))
    if new_plan:
        data["keyword_plan"] = new_plan
    return jsonify(data)


@app.post("/api/products/<pid>/ai-en")
def ai_english(pid):
    """按泰文生成英文标题和英文详情（v2.22）。body 可以带编辑页里还没保存的产品。"""
    p = request.get_json(silent=True) or store.load(pid)
    try:
        return jsonify(ai_copy.to_english(load_config(), p))
    except ai_copy.AIError as e:
        return err(str(e))


@app.post("/api/products/<pid>/ai-complete")
def ai_complete(pid):
    """把空着的文案字段补完整（英文标题 / 详情、Shopee 标题和标签、包装内容、变体名称和选项泰文……），已经有的不动（v2.22）。
    body 可以带编辑页里还没保存的产品；返回补出来的字段，由页面合进去。"""
    p = request.get_json(silent=True) or store.load(pid)
    try:
        return jsonify({"ok": True, "fields": ai_copy.complete_copy(load_config(), p, p.get("keyword_plan"))})
    except ai_copy.AIError as e:
        return err(str(e))


@app.post("/api/products/fill-copy")
def fill_copy_bulk():
    """批量补全文案：有空字段的产品（或指定 ids）。后台做，进任务中心。"""
    b = request.get_json(silent=True) or {}
    ids = b.get("ids") or []
    return maybe_async("批量补全文案", lambda: jsonify(fill_copy(ids, _uname())), "ai_fill")


def fill_copy(ids=None, user=""):
    from core import bgjobs
    cfg = load_config()
    todo = []
    for it in store.list_products():
        pid = it["id"] if isinstance(it, dict) else it
        if ids and pid not in ids:
            continue
        try:
            p = store.load(pid)
        except Exception:  # noqa: BLE001
            continue
        miss, opts = ai_copy.missing_copy(p)
        if (miss or opts) and (p.get("name_zh") or (p.get("copy") or {}).get("title_th")):
            todo.append(pid)
    done, failed = [], []
    for i, pid in enumerate(todo):
        bgjobs.note(stage=f"{i + 1}/{len(todo)}")
        try:
            p = store.load(pid)
            out = ai_copy.complete_copy(cfg, p, p.get("keyword_plan"))
            ai_copy.apply_completion(p, out)
            store.save(p)
            done.append(pid)
        except ai_copy.AIError as e:
            failed.append({"id": pid, "error": str(e)[:200]})
            if "密钥" in str(e) or "key" in str(e).lower():
                break
        except Exception as e:  # noqa: BLE001
            failed.append({"id": pid, "error": str(e)[:200]})
    db.audit(user, "批量补全文案", f"{len(done)} 个", ", ".join(done)[:300])
    return {"ok": True, "done": done, "failed": failed, "total": len(todo)}


@app.post("/api/ai/back-translate")
def ai_back():
    body = request.get_json(force=True) or {}
    try:
        return jsonify(ai_copy.back_translate(load_config(), body.get("title_th", ""), body.get("description_th", "")))
    except ai_copy.AIError as e:
        return err(str(e))


@app.get("/api/skus")
def skus_list():
    """所有产品的 SKU（手工订单输入时提示用）。生产角色不返回价格。"""
    cfg = load_config()
    show_price = auth.current_user()["role"] != "production"
    out = []
    for item in store.list_products():
        p = store.load(item["id"])
        for v in p.get("variants", []):
            if v.get("sku"):
                price = None
                if show_price:
                    try:
                        price = pricing.price_variant(cfg, v, p.get("markup"), p.get("material"))["final_price"]
                    except Exception:  # 缺数据时不给价格
                        price = None
                out.append({"sku": v["sku"], "name": p.get("name_zh", ""), "color": v.get("opt1_zh", ""), "price": price})
    return jsonify(out)


_STL_CACHE = {}


def _stl_response(fp):
    """把模型（3MF / OBJ 等）转成二进制 STL 给 3D 预览用：拓竹、Orca 的项目 3MF 浏览器读不了时用这个。"""
    import tempfile as _tf
    from core import mesh, modellib
    key = (fp, os.path.getmtime(fp))
    data = _STL_CACHE.get(key)
    if data is None:
        parts = modellib.load_parts(fp)
        import numpy as _np
        tris = _np.concatenate([t for _n, t in parts])
        with _tf.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            tmp = f.name
        try:
            mesh.write_stl(tris, tmp)
            with open(tmp, "rb") as f:
                data = f.read()
        finally:
            os.remove(tmp)
        if len(_STL_CACHE) > 8:
            _STL_CACHE.clear()
        _STL_CACHE[key] = data
    return app.response_class(data, mimetype="model/stl")


def _preview_response(fp):
    """?nowait=1（新版页面）：大文件还没算好时不让浏览器干等，回 202 并在后台排队算，浏览器先读完整模型，下次打开就快了。"""
    from core import filemgr, preview
    if request.args.get("nowait") and not preview.ready(fp) and os.path.getsize(fp) >= preview.SYNC_BYTES:
        preview.warm(fp)
        return jsonify({"ok": False, "pending": True, "msg": "预览模型正在后台生成"}), 202
    etag = os.path.basename(preview.cache_path(fp))
    if request.if_none_match and etag in request.if_none_match:      # 浏览器里已经有这份：不用再下载（304）
        r = app.response_class(status=304)
    else:
        r = app.response_class(preview.build(fp, filemgr.metrics), mimetype="application/octet-stream")
        r.headers["Content-Encoding"] = "gzip"
    r.set_etag(etag)
    r.headers["Cache-Control"] = "no-cache"
    return r


@app.get("/api/products/<pid>/model/preview")
def model_preview(pid):
    """3D 预览用的精简模型（大模型先快速显示，放大 / 出图时浏览器再读完整模型）。"""
    from core import filemgr
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("产品不存在", 404)
    fp = filemgr.model_path(p)
    if not fp:
        return err("这个产品没有模型文件", 404)
    try:
        return _preview_response(fp)
    except Exception as e:  # noqa: BLE001
        return err(f"模型读不了：{e}")


@app.get("/api/products/<pid>/model/stl")
def model_stl(pid):
    from core import filemgr
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("产品不存在", 404)
    fp = filemgr.model_path(p)
    if not fp:
        return err("这个产品没有模型文件", 404)
    try:
        return _stl_response(fp)
    except Exception as e:  # noqa: BLE001  文件坏了
        return err(f"模型读不了：{e}")


@app.get("/api/products/<pid>/model/download")
def model_download(pid):
    from core import filemgr
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("产品不存在", 404)
    fp = filemgr.model_path(p)
    if not fp:
        return err("这个产品没有模型文件", 404)
    name = f"{p['id']}_{p['model'].get('orig_name') or p['model']['file']}"
    return send_file(fp, as_attachment=True, download_name=name)


@app.get("/api/products/<pid>/model/history")
def model_history(pid):
    from core import filemgr
    return jsonify({"history": filemgr.model_history(pid)})


@app.get("/api/products/<pid>/model/history/<name>")
def model_history_download(pid, name):
    from core import filemgr
    fp = filemgr.history_path(pid, name)
    if not fp:
        return err("文件不存在", 404)
    return send_file(fp, as_attachment=True, download_name=f"{pid}_old_{name.partition('__')[2] or name}")


@app.post("/api/products/<pid>/model/restore")
def model_restore(pid):
    from core import filemgr
    try:
        r = filemgr.restore_model(pid, (request.get_json(force=True) or {}).get("name", ""), _uname())
    except (ValueError, OSError) as e:
        return err(str(e))
    return jsonify({"ok": True, "files_reset": r["files_reset"]})


@app.delete("/api/products/<pid>/model")
def model_delete(pid):
    from core import filemgr
    filemgr.delete_model(pid)
    return jsonify({"ok": True})


@app.get("/api/products/<pid>/models")
def models_lib(pid):
    try:
        return jsonify(modellib.library(pid))
    except FileNotFoundError:
        return err("找不到这个产品", 404)


@app.post("/api/products/<pid>/models")
def models_upload(pid):
    files = request.files.getlist("files")
    if not files:
        return err("请选择模型文件")
    variant = request.form.get("variant") or ""
    for_spec = (request.form.get("spec") or "").strip()     # v2.22.1：给某个规格上传 / 更换模型，传完直接指定
    if for_spec:
        variant = for_spec
    # 先把文件存下来（后台线程里读不到上传的文件），读模型 / 分析放后台（v2.20）
    tmp = os.path.join(DATA_DIR, "tmp")
    os.makedirs(tmp, exist_ok=True)
    saved = []
    for f in files:
        sp = os.path.join(tmp, "up_" + uuid.uuid4().hex)
        f.save(sp)
        saved.append(modellib.SavedFile(sp, f.filename))

    def go():
        try:
            added = modellib.upload(pid, saved, _uname(), variant)
            if for_spec and added:
                from core import specmodel
                specmodel.map_spec(pid, for_spec, added[0]["id"], _uname())
        except (ValueError, OSError) as e:
            return err(str(e))
        finally:
            for x in saved:
                x.cleanup()
        return jsonify(modellib.library(pid))
    return maybe_async(f"上传模型库 {pid}", go, "model_lib", pid)


@app.post("/api/products/<pid>/models/reanalyze")
def models_reanalyze(pid):
    return maybe_async(f"重新分析模型 {pid}", lambda: jsonify(modellib.library(pid, reanalyze=True)), "model_re", pid)


@app.post("/api/products/<pid>/models/current")
def models_current(pid):
    b = request.get_json(force=True) or {}
    return maybe_async(f"设为当前模型 {pid}", lambda: _models_current(pid, b), "model_cur", pid)


def _models_current(pid, b):
    try:
        r = modellib.make_current(pid, b.get("items") or [], _uname(), b.get("name") or "", b.get("bed_w"))
    except (ValueError, OSError) as e:
        return err(str(e))
    out = modellib.library(pid)
    out.update(files_reset=r["files_reset"], merged=bool(r["merged"]))
    return jsonify(out)


@app.post("/api/products/<pid>/models/layout-preview")
def models_layout_preview(pid):
    """预览摆盘：按勾选的零件、数量、方向排好一盘，返回三角面（Float32，gzip），不保存。"""
    import gzip as _gz
    b = request.get_json(force=True) or {}
    try:
        tris = modellib.layout_preview(pid, b.get("items") or [], b.get("bed_w"))
    except FileNotFoundError:
        return err("找不到这个产品", 404)
    except (ValueError, OSError) as e:
        return err(str(e))
    resp = app.response_class(_gz.compress(tris.astype("<f4").tobytes(), 4), mimetype="application/octet-stream")
    resp.headers["Content-Encoding"] = "gzip"
    return resp


@app.post("/api/products/<pid>/models/ai-check")
def models_ai_check(pid):
    """AI 检查摆盘：按选中的模型和方向，判断空打 / 打飞的机率。"""
    b = request.get_json(force=True) or {}
    return maybe_async(f"AI 检查摆盘 {pid}", lambda: _ai_check(pid, b), "ai_check", pid)


def _ai_check(pid, b):
    try:
        return jsonify(modellib.ai_check(pid, b.get("items") or [], _uname()))
    except FileNotFoundError:
        return err("找不到这个产品", 404)
    except ValueError as e:
        return err(str(e))
    except Exception as e:  # noqa: BLE001  AI 没设置 / 网络错误 / 回答不是 JSON
        return err(f"AI 检查失败：{e}")


@app.post("/api/products/<pid>/models/<eid>/spec")
def models_spec(pid, eid):
    try:
        return jsonify(modellib.set_spec(pid, eid, (request.get_json(force=True) or {}).get("spec") or "", _uname()))
    except ValueError as e:
        return err(str(e))


@app.delete("/api/products/<pid>/models/<eid>")
def models_delete(pid, eid):
    try:
        return jsonify(modellib.remove(pid, eid, _uname()))
    except ValueError as e:
        return err(str(e))


@app.get("/api/products/<pid>/models/<eid>/<what>")
def models_file(pid, eid, what):
    p = store.load(pid)
    e = next((x for x in p.get("model_lib") or [] if x["id"] == eid), None)
    if not e:
        return err("模型库里没有这个文件", 404)
    if what == "thumb":
        th = (e.get("info") or {}).get("thumb")
        fp = os.path.join(store.product_dir(pid), "models", th) if th else None
        if not fp or not os.path.exists(fp):
            return err("没有缩略图", 404)
        return send_file(fp, mimetype="image/png")
    if what == "preview":
        fp = modellib.path_of(pid, e)
        if not fp:
            return err("文件不见了", 404)
        try:
            return _preview_response(fp)
        except Exception as ex:  # noqa: BLE001
            return err(f"模型读不了：{ex}")
    if what == "stl":
        fp = modellib.path_of(pid, e)
        if not fp:
            return err("文件不见了", 404)
        try:
            return _stl_response(fp)
        except Exception as ex:  # noqa: BLE001
            return err(f"模型读不了：{ex}")
    if what != "download":
        return err("不对", 404)
    fp = modellib.path_of(pid, e)
    if not fp:
        return err("文件不见了", 404)
    return send_file(fp, as_attachment=request.args.get("inline") != "1", download_name=e.get("orig_name") or e["file"])


@app.get("/api/products/<pid>/mesh")
def product_mesh(pid):
    """按摆放方向转好的模型三角面（Float32，gzip），给打印方案里的实时 3D 预览用。"""
    import gzip as _gz
    from core import mesh
    from core import specmodel
    try:
        p = specmodel.view(store.load(pid), request.args.get("spec") or "")      # ?spec=：规格自己的模型（v2.22）
    except FileNotFoundError:
        return err("产品不存在", 404)
    path = specmodel.model_path(p)
    if not path:
        return err("没有 3D 模型", 404)
    orient = request.args.get("orient") or "bottom"
    if orient not in mesh.ORIENT_ZH:
        orient = "bottom"
    try:
        key = (path, orient, os.path.getmtime(path))
        blob = _MESH_CACHE.get(key)
        if blob is None:
            tris = mesh.rotate(mesh.load(path), orient)
            blob = _gz.compress(tris.astype("<f4").tobytes(), 4)
            if len(_MESH_CACHE) > 12:
                _MESH_CACHE.clear()
            _MESH_CACHE[key] = blob
    except (OSError, ValueError) as e:
        return err(f"模型读取失败：{e}")
    resp = app.response_class(blob, mimetype="application/octet-stream")
    resp.headers["Content-Encoding"] = "gzip"
    return resp


@app.get("/api/products/<pid>/filaments")
def product_filaments(pid):
    """某台打印机可选的耗材配置（按产品材料筛选）。"""
    from core import recipes
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("产品不存在", 404)
    mat = request.args.get("material") or p.get("material") or "PLA"
    return jsonify(recipes.filament_choices(int(request.args.get("printer") or 0), mat))


@app.post("/api/products/<pid>/recipe")
def recipe_save(pid):
    from core import recipes, specmodel
    p = store.load(pid)
    body = request.get_json(force=True) or {}
    r = recipes.clean(body)
    if body.get("material"):
        mat = recipes.norm_material(body["material"])
        if (p.get("material") or "PLA").upper() != mat:
            r["filament"] = {}          # 换了材料：之前指定的耗材配置作废
            p["material"] = mat
            store.save(p)
    r["updated_at"] = time.time()
    r["updated_by"] = _uname()
    specmodel.save_recipe(pid, body.get("spec") or "", r)      # 规格有自己的模型时存到规格的方案里（v2.22）
    return recipe_get(pid)


@app.post("/api/products/<pid>/recipe/slice")
def recipe_slice(pid):
    """按打印方案切片：选打印机和一盘数量，生成新版本（草稿），带切片报告和自动检查。"""
    b = request.get_json(force=True) or {}
    return maybe_async(f"按方案切片 {pid}", lambda: _recipe_slice(pid, b), "slice", pid)


def _recipe_slice(pid, b):
    from core import recipes
    try:
        from core import specmodel
        p = specmodel.view(store.load(pid), b.get("spec") or "")     # 规格有自己的模型时切那个模型（v2.22）
        sp = p.get("_spec") or ""
        idx = int(b.get("printer") or 0)
        names = [x.get("name") for x in load_config().get("printers") or []]
        r = recipes.get(p)
        count = int(b.get("count") or r.get("per_plate") or 1)
        tmp, rep, r = recipes.slice_product(p, idx, count, r)
        geo = recipes.geometry(p, r, idx)
        checks = recipes.check(r, geo, rep, p.get("material") or "PLA")
        f = print_files.add(tmp, f"{pid}{'_' + sp if sp else ''}_{names[idx]}_x{count}.gcode.3mf".replace(" ", "_"), pid, names[idx],
                            b.get("sku") or "", count, b.get("color") or "", "按打印方案切片" + (f"（规格 {sp}）" if sp else ""), _uname(),
                            p.get("material") or "PLA", rep.get("grams_per_plate"), rep.get("hours_per_plate"), move=True,
                            recipe=r, report=rep, checks=checks, source="recipe", spec=sp)
    except (slicer.SliceError, ValueError, OSError, IndexError) as e:
        return err(f"切片失败：{e}")
    production.schedule()
    return jsonify(f)


@app.post("/api/groups")
def groups_post():
    b = request.get_json(force=True) or {}
    try:
        extras.group_save(b.get("name"), b.get("id"))
    except ValueError as e:
        return err(str(e))
    return groups_get()


@app.delete("/api/groups/<int:gid>")
def groups_delete(gid):
    extras.group_delete(gid)
    return groups_get()


@app.post("/api/groups/assign")
def groups_assign():
    b = request.get_json(force=True) or {}
    n = extras.group_assign(b.get("ids") or [], int(b.get("group") or 0), bool(b.get("add", True)))
    return jsonify({"changed": n, "groups": extras.groups()})


# ---------------- 规格确认、按耗材算的库存（v2.16） ----------------
@app.post("/api/products/<pid>/specs/<path:spec_id>/<action>")
def spec_confirm(pid, spec_id, action):
    """待确认的规格：ok 确认没问题 / keep 选品工具删了也保留 / delete 删掉这个规格和它的 SKU。"""
    from core import specs
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("产品不存在", 404)
    if action == "delete" and p.get("exported_at"):
        hit = [v.get("sku") for v in p.get("variants") or [] if v.get("spec_id") == spec_id and v.get("sku")]
        if hit and request.args.get("force") != "1":
            return jsonify({"ok": False, "confirm": True,
                            "error": f"这个规格的 SKU 已经导出过（{'、'.join(hit[:6])}{'…' if len(hit) > 6 else ''}），"
                                     "删掉后记得到平台后台把这些 SKU 也删掉或下架。确定删除？"}), 409
    try:
        s = specs.confirm(p, spec_id, action, _uname())
    except specs.SpecError as e:
        return err(str(e))
    store.bump_rev(p, _uname())
    store.save(p)
    db.audit(_uname(), {"ok": "确认规格", "keep": "保留规格", "delete": "删除规格"}[action], pid, s.get("name_zh", ""))
    return jsonify({"ok": True, "product": p})


@app.post("/api/products/<pid>/ip-risk")
def ip_risk_set(pid):
    """侵权待确认（选品工具 listing.ip_risk）：ok = 确认没问题（已改掉品牌 / 角色词，或确认不侵权）；pending = 改回待确认。"""
    act = (request.get_json(force=True, silent=True) or {}).get("action")
    if act not in ("ok", "pending"):
        return err("action 只能是 ok / pending")
    p = store.load(pid)
    ir = p.get("ip_risk") or {}
    if not ir.get("items"):
        return err("这个产品没有侵权提示")
    ir.update(status=act, by=_uname(), at=time.time())
    p["ip_risk"] = ir
    store.bump_rev(p, _uname())
    store.save(p)
    db.audit(_uname(), "确认侵权提示" if act == "ok" else "侵权改回待确认", pid, "、".join(x.get("term", "") for x in ir["items"]))
    return jsonify({"ok": True, "product": p})


@app.get("/api/products/<pid>/stock")
def product_stock(pid):
    from core import stockcalc
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("产品不存在", 404)
    cfg = load_config()
    return jsonify({"ok": True, "auto": stockcalc.enabled(p, cfg), "global": bool(cfg.get("stock_auto")),
                    "own": p.get("stock_auto"), "rows": stockcalc.compute(p, cfg), "settings": stockcalc.settings(cfg)})


@app.post("/api/products/<pid>/stock-auto")
def product_stock_auto(pid):
    """这个产品单独开 / 关「按耗材自动算库存」：mode = on / off / default（跟总开关）。"""
    from core import stockcalc
    mode = (request.get_json(force=True, silent=True) or {}).get("mode")
    if mode not in ("on", "off", "default"):
        return err("mode 只能是 on / off / default")
    p = store.load(pid)
    p["stock_auto"] = {"on": True, "off": False, "default": None}[mode]
    store.bump_rev(p, _uname())
    store.save(p)
    cfg = load_config()
    return jsonify({"ok": True, "product": p, "auto": stockcalc.enabled(p, cfg), "rows": stockcalc.compute(p, cfg)})


@app.get("/api/stock/pending")
def stock_pending():
    from core import stockcalc
    plat = request.args.get("platform") or "lazada"
    return jsonify({"ok": True, "items": stockcalc.pending(plat), "settings": stockcalc.settings()})


@app.post("/api/stock/mark-synced")
def stock_mark_synced():
    """在平台后台手动改好了（以后接上 Lazada 接口就自动推送）：把这些 SKU 记为已同步。"""
    from core import stockcalc
    b = request.get_json(force=True, silent=True) or {}
    plat = b.get("platform") or "lazada"
    want = {str(x).upper() for x in b.get("skus") or []}
    items = [x for x in stockcalc.pending(plat) if b.get("all") or x["sku"] in want]
    n = stockcalc.mark_synced(items, _uname(), "manual", plat)
    db.audit(_uname(), "标记库存已同步到平台", "", f"{plat} {n} 个 SKU")
    return jsonify({"ok": True, "marked": n})


# ---------------- 规格 ↔ 3D 模型（v2.22） ----------------
@app.get("/api/products/<pid>/spec-models")
def spec_models_get(pid):
    from core import specmodel
    try:
        return jsonify(specmodel.overview(pid))
    except FileNotFoundError:
        return err("产品不存在", 404)


@app.post("/api/products/<pid>/spec-models")
def spec_models_set(pid):
    """{spec, entry_id}（entry_id 空 = 这个规格用主模型）。"""
    from core import specmodel
    b = request.get_json(force=True) or {}
    no = _need("models.change")
    if no:
        return no
    try:
        return jsonify(specmodel.map_spec(pid, b.get("spec") or "", b.get("entry_id") or "", _uname()))
    except ValueError as e:
        return err(str(e))


@app.post("/api/products/<pid>/spec-models/parts")
def spec_models_parts(pid):
    """v2.23：规格只用模型库文件里的某几个组件。{spec, items: [{id, part, qty}]}。"""
    from core import specmodel
    no = _need("models.change")
    if no:
        return no
    b = request.get_json(force=True) or {}

    def go():
        try:
            return jsonify(specmodel.map_parts(pid, b.get("spec") or "", b.get("items") or [], _uname()))
        except ValueError as e:
            return err(str(e))
    return maybe_async(f"规格选组件 {pid}", go, "model_lib", pid)


@app.post("/api/products/<pid>/spec-models/auto-parts")
def spec_models_auto_parts(pid):
    """v2.23：按组件名自动对应规格（组件名里有规格名）。"""
    from core import specmodel
    no = _need("models.change")
    if no:
        return no

    def go():
        try:
            done = specmodel.auto_parts(pid, _uname())
        except ValueError as e:
            return err(str(e))
        return jsonify({"ok": True, "done": done, **specmodel.overview(pid)})
    return maybe_async(f"按组件名对应规格 {pid}", go, "model_lib", pid)


@app.post("/api/products/<pid>/spec-models/flatten")
def spec_models_flatten(pid):
    """v2.23：分体模型每个组件按推荐方向平放排一盘（spec 空 = 主模型），然后 AI 检查能不能打出来。"""
    from core import specmodel
    no = _need("models.change")
    if no:
        return no
    b = request.get_json(force=True) or {}
    spec = (b.get("spec") or "").strip()

    def go():
        try:
            r = specmodel.flatten(pid, spec, _uname())
        except ValueError as e:
            return err(str(e))
        check = None
        try:
            check = modellib.ai_check(pid, r["selection"], _uname())
        except Exception as e:  # noqa: BLE001  没有 AI 也照样摆好
            check = {"error": str(e)[:200]}
        return jsonify({"ok": True, **r, "check": check, **specmodel.overview(pid)})
    return maybe_async(f"分体平放 {pid}", go, "model_lib", pid)


@app.post("/api/products/<pid>/spec-models/auto")
def spec_models_auto(pid):
    """v2.22.1：模型库里没分配的模型文件，每个自动加成一个规格（按尺寸起名），并指定用这个模型。"""
    from core import specmodel
    no = _need("models.change")
    if no:
        return no
    try:
        added = specmodel.auto_specs(pid, _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True, "added": added, "product": store.load(pid), **specmodel.overview(pid)})


@app.post("/api/products/<pid>/spec-models/fill")
def spec_models_fill(pid):
    """按规格的模型估算填这个规格（所有颜色）的克数和时长。"""
    from core import specmodel
    b = request.get_json(force=True) or {}
    try:
        n = specmodel.fill_grams(pid, b.get("spec") or "", _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True, "filled": n, "product": store.load(pid), **specmodel.overview(pid)})
