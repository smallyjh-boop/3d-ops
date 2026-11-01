"""商品模块（基础模块，不能关）的接口：产品资料、图片、修图、场景图、文案 AI、分组、类目与类目模板、Shopee 类目。
v2.31 从 web/products.py、web/listing.py 搬过来。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403

bp = Blueprint("m_goods", __name__)
PREFIXES = []
PATTERNS = []


# ---------------- 产品 ----------------
def _rows(want):
    """产品库列表（含 v2.53 自动分组键 gk、手动标记 marks）。want：""（不要采集箱的）/ "1"（只要采集箱）/ "all"。"""
    from core import prodgroups, pricing as _pr, stockcalc
    from . import groups as _g
    cfg = load_config()
    S = prodgroups.settings()
    lib = categories.library()
    names = {c["id"]: c["name"] for c in lib}
    names_th = {c["id"]: " > ".join(c["path"].split(" > ")[-2:]) for c in lib if c["path"]}
    paths = {c["id"]: c["path"] or c["name"] for c in lib}
    out, ps = [], {}
    from core import modules as _mods
    pub = _mods.public("listing")
    online = pub.online_shops() if pub else {}         # v2.44：在哪些店铺在线（上架模块的在线商品）
    first_live = pub.online_first_live() if pub and hasattr(pub, "online_first_live") else {}
    try:
        avail = stockcalc.available(cfg, fresh=False)
    except Exception:  # noqa: BLE001
        avail = None
    now = time.time()
    for item in store.list_products():
        p = store.load(item["id"])
        if (want == "1" and not p.get("inbox")) or (want not in ("1", "all") and p.get("inbox")):
            continue
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
            "lz_item": (p.get("lazada_api") or {}).get("item_id"),       # v2.41.2：用接口推到 Lazada 的商品编号
            "online": online.get(p["id"], []),
            "updated_at": p.get("updated_at") or 0,
            "groups": p.get("groups") or [], "material": p.get("material") or "",
            "has_model": bool(p.get("model")), "keywords": p.get("keywords") or "",
            "draft": bool(p.get("draft")), "from_curator": bool(p.get("source")), "inbox": bool(p.get("inbox")),
            "lead_days": p.get("lead_days"), "has_recipe": bool(p.get("recipe")),
            "thumb": next((f"/files/{p['id']}/{'out' if im.get('processed') else 'raw'}/{im['file']}" for im in p.get("images", []) if im.get("file")), ""),
        })
        out.append(item)
        ps[p["id"]] = (p, errs)
    _enrich_products(out)
    for item in out:           # 自动分组（要销量 / 切片状态，所以放在 _enrich_products 后面）
        p, errs = ps[item["id"]]
        try:
            prices = _pr.price_product(cfg, p)
        except Exception:  # noqa: BLE001
            prices = []
        smin = None
        if any(o.get("status") == "live" for o in item["online"]) or (item["lz"]["status"] == "live") or (item["sp"]["status"] == "live"):
            try:
                comp = stockcalc.compute(p, cfg, avail)
                vals = [r["stock"] for r in comp if isinstance(r.get("stock"), (int, float))]
                smin = min(vals) if vals else None
                item["sku_stock"] = {(r.get("sku") or "").upper(): r["stock"] for r in comp if r.get("sku") and isinstance(r.get("stock"), (int, float))}
            except Exception:  # noqa: BLE001
                smin = None
        item["err_txt"] = [str(x) for x in errs][:30]
        item["sp_err_txt"] = [str(x) for x in _check_shopee(cfg, p)[0]][:30] if item["sp_errors"] else []
        item["title_len"] = len((p.get("copy") or {}).get("title_th") or "")
        item["white_bg"] = bool(p.get("white_bg"))
        item["n_img"] = len(p.get("images") or [])
        item["sku_price"] = {(v.get("sku") or "").upper(): pr.get("final_price") for v, pr in zip(p.get("variants") or [], prices) if v.get("sku")}
        item["price_sig"] = prodgroups.sig_price(prices)
        item["img_sig"] = prodgroups.sig_img(p)
        _g.classify(item, p, errs, prices, paths.get((p.get("category") or {}).get("id"), ""), smin, first_live.get(p["id"]), S, now)
    _g.finish(out, S)
    return out


_ROWS_CACHE = {}


def cached_rows():
    """产品库全部（不含采集箱）的行，3 秒内、产品没改过就用缓存（上架工作台的自动分组也用）。"""
    key = store.REV[0]
    hit = _ROWS_CACHE.get("v")
    if hit and hit[0] == key and time.time() - hit[1] < 3:
        return hit[2]
    rows = [i for i in _rows("all") if not i.get("inbox")]
    _ROWS_CACHE["v"] = (key, time.time(), rows)
    return rows


@bp.get("/api/products")
def products():
    return jsonify(_rows(request.args.get("inbox") or ""))


_LIB_CACHE = {}


@bp.get("/api/goods/library")
def goods_library():
    """产品库一次取完：产品 + 分组键 + 各分组个数 + 保存的视图 + 标签 + 阈值（服务器算，3 秒内、产品没改过就用缓存）。"""
    from core import prodgroups
    from . import groups as _g
    prodgroups.migrate()
    key = (store.REV[0], request.args.get("inbox") or "all")
    hit = _LIB_CACHE.get("v")
    if hit and hit[0] == key and time.time() - hit[1] < 3 and not request.args.get("fresh"):
        return jsonify(hit[2])
    allr = _rows("all")
    rows = [i for i in allr if not i.get("inbox")]
    res = {"items": rows, "inbox": len(allr) - len(rows), "summary": _g.summary(rows),
           "views": prodgroups.views("goods"), "tags": prodgroups.tags(), "settings": prodgroups.settings()}
    _LIB_CACHE["v"] = (key, time.time(), res)
    return jsonify(res)


@bp.post("/api/products/new")
def product_new():
    cfg = load_config()
    p = store.blank_product(store.new_id(_prefix(cfg)))
    codes.ensure_skus(cfg, p)
    store.save(p)
    return jsonify(p)


@bp.get("/api/products/<pid>")
def product_get(pid):
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("找不到这个产品", 404)
    codes.ensure_skus(load_config(), p)
    if not auth.is_owner():
        p.pop("markup", None)        # v2.40：员工看不到、也改不了加价率（保存时沿用原来的）
    return jsonify(p)


@bp.post("/api/products/<pid>")
def product_save(pid):
    p = request.get_json(force=True)
    c = _conflict(pid, p)
    if c:
        return c
    return jsonify(_save_from_client(pid, p))


@bp.post("/api/products/<pid>/regen-skus")
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


@bp.delete("/api/products/<pid>")
def product_delete(pid):
    store.delete(pid)
    return jsonify({"ok": True})


@bp.post("/api/products/<pid>/duplicate")
def product_duplicate(pid):
    cfg = load_config()
    src = store.load(pid)
    p = dict(src)
    p["id"] = store.new_id(_prefix(cfg))
    p["images"], p["white_bg"], p["exported_at"] = [], None, None
    # v2.40：上架 / 导出状态不跟着复制（以前新产品显示「已导出」、Shopee「待上传」）
    for k in ("shopee_exported_at", "exported_first", "listing", "lazada_api", "ad_designs", "seo_review", "seo_undo", "seo_log",
              "title_changed_at", "copy_dirty_after_export", "edit_rev", "edited_by", "edited_at"):
        p.pop(k, None)
    p["listing"] = {}
    # v2.40：模型文件一起复制（以前只复制了模型信息，新产品打开模型是 404）
    import shutil as _sh
    for sub in ("model", "models", "source_files"):
        sd = os.path.join(store.product_dir(pid), sub)
        if os.path.isdir(sd):
            _sh.copytree(sd, os.path.join(store.product_dir(p["id"]), sub), dirs_exist_ok=True)
    for v in p.get("variants", []):
        v["image"], v["sku"] = "", ""
    p["name_zh"] = (src.get("name_zh") or "") + "（副本）"
    codes.ensure_skus(cfg, p)
    store.save(p)
    return jsonify(p)


@bp.post("/api/pricing")
def pricing_preview():
    data = request.get_json(force=True) or {}
    cfg = load_config()
    if not auth.is_owner() and data.get("id"):      # v2.40：员工那边没有加价率 → 用保存着的算售价
        try:
            data["markup"] = store.load(data["id"]).get("markup")
        except FileNotFoundError:
            data.pop("markup", None)
    codes.ensure_skus(cfg, data)
    return jsonify({"rows": auth.strip_prices(pricing.price_product(cfg, data), auth.current_user()),
                    "summary": pricing.cost_summary(cfg) if auth.is_owner() else None,
                    "skus": [v.get("sku") for v in data.get("variants", [])],
                    "colors": [(lambda c: c[1] if c else "")(codes.find_color(cfg, v.get("opt1_zh")))
                               for v in data.get("variants", [])]})


@bp.post("/api/products/<pid>/check")
def product_check(pid):
    p = request.get_json(force=True) or store.load(pid)
    errs, warns = _check(load_config(), p)
    return jsonify({"errors": errs, "warnings": warns})


@bp.post("/api/products/<pid>/ai-category")
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


@bp.post("/api/products/<pid>/fill-attrs")
def fill_attrs(pid):
    p = request.get_json(force=True)
    cfg = load_config()
    cat = categories.get((p.get("category") or {}).get("id"))
    if not cat:
        return err("先选择类目")
    p["category"]["cat_id"] = cat["cat_id"]
    use_ai = ai.ready(cfg, "category")
    _apply_fill(cfg, p, cat, use_ai=use_ai)
    p = _save_from_client(pid, p)
    return jsonify({"product": p, "used_ai": use_ai})


@bp.post("/api/products/<pid>/ai-shopee-category")
def ai_shopee_category(pid):
    p = request.get_json(force=True)
    cfg = load_config()
    try:
        p["shopee_category"] = attributes.match_shopee_category(cfg, p)
    except ai_copy.AIError as e:
        return err(str(e))
    return jsonify(_save_from_client(pid, p))


@bp.post("/api/products/<pid>/check-shopee")
def product_check_shopee(pid):
    p = request.get_json(force=True) or store.load(pid)
    errs, warns = _check_shopee(load_config(), p)
    return jsonify({"errors": errs, "warnings": warns})


# ---------------- 3D 模型 / 克数时长 ----------------
@bp.get("/api/colors")
def colors():
    return jsonify(codes.color_hex(load_config()))


@bp.post("/api/products/<pid>/images/rendered")
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
@bp.get("/fonts/thai.css")
def fonts_css():
    from core import adimg
    r = app.response_class(adimg.thai_css(), mimetype="text/css")
    r.headers["Cache-Control"] = "no-cache"
    return r


@bp.get("/fonts/f/<name>")
def fonts_file(name):
    from core import adimg
    return send_from_directory(adimg.FONT_DIR, os.path.basename(name), max_age=31536000)


@bp.post("/api/products/<pid>/ad/suggest")
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


@bp.post("/api/products/<pid>/ad/save")
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
@bp.get("/api/scenes")
def scenes_list():
    return jsonify({"library": scenes.library(),
                    "presets": [{"key": k, "name": v[0]} for k, v in scenes.PRESETS.items()],
                    "bg_presets": [{"key": k, "name": v[0]} for k, v in scenes.BG_PRESETS.items()]})


@bp.post("/api/scenes/ai")
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


@bp.post("/api/scenes")
def scenes_upload():
    fs = request.files.getlist("files")
    if not fs:
        return err("请选择背景照片")
    try:
        ids = [scenes.add_user(f, f.filename) for f in fs[:20]]
    except scenes.SceneError as e:
        return err(str(e))
    return jsonify({"added": ids, "library": scenes.library()})


@bp.post("/api/scenes/<sid>")
def scenes_update(sid):
    b = request.get_json(force=True) or {}
    scenes.update_user(sid, floor_y=b.get("floor_y"), scale=b.get("scale"), name=b.get("name"))
    return jsonify({"library": scenes.library()})


@bp.delete("/api/scenes/<sid>")
def scenes_delete(sid):
    try:
        scenes.delete_user(sid)
    except scenes.SceneError as e:
        return err(str(e))
    return jsonify({"library": scenes.library()})


@bp.get("/scenes/<sid>")
def scenes_file(sid):
    return send_from_directory(scenes.USER_DIR, sid)


@bp.post("/api/products/<pid>/scene-ai")
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


# ---------------- 场景图改进（v2.53）：模板、多张候选 + 质检、挑图、多尺寸、批量、费用 ----------------
from core import scene_ai  # noqa: E402


def _scene_opts(b):
    return {"template": str(b.get("template") or ""), "aspect": b.get("aspect") if b.get("aspect") in scene_ai.ASPECTS else "1:1",
            "n": max(1, min(int(b.get("n") or 2), scene_ai.MAX_N)), "extra": str(b.get("extra") or "")[:300],
            "qa": b.get("qa", True) not in (False, 0, "0"), "ai_prompt": b.get("ai_prompt", True) not in (False, 0, "0"),
            "auto_add": bool(b.get("auto_add"))}


@bp.get("/api/scenes/templates")
def scene_templates():
    cfg = load_config()
    return jsonify({"templates": scene_ai.templates(cfg), "aspects": list(scene_ai.ASPECTS), "max_n": scene_ai.MAX_N,
                    "custom": isinstance(cfg.get("scene_templates"), list) and bool(cfg.get("scene_templates"))})


@bp.post("/api/scenes/templates")
def scene_templates_save():
    if not auth.is_owner():
        return err("只有老板能改场景模板", 403)
    b = request.get_json(force=True) or {}
    items = [] if b.get("reset") else scene_ai.clean_templates(b.get("templates"))
    save_config({"scene_templates": items})
    return scene_templates()


@bp.post("/api/scenes/estimate")
def scene_estimate():
    b = request.get_json(force=True) or {}
    o = _scene_opts(b)
    return jsonify(scene_ai.estimate(load_config(), int(b.get("products") or 1), o["n"], o["qa"], o["ai_prompt"]))


@bp.get("/api/products/<pid>/scene-cands")
def scene_cands(pid):
    p = store.load(pid)
    cfg = load_config()
    return jsonify({"cands": scene_ai.list_cands(pid), "suggest": scene_ai.suggest(cfg, p),
                    "ready": {"image": ai.can(cfg, "scene", "image")[0], "image_why": ai.can(cfg, "scene", "image")[1],
                              "prompt": ai.ready(cfg, "scene_prompt"), "qa": ai.can(cfg, "scene_qa", "vision")[0]}})


@bp.post("/api/products/<pid>/scene-gen")
def scene_gen(pid):
    """出几张候选（不直接加进商品图，员工挑）。body: template, aspect, n, extra, qa, ai_prompt, image（可选：浏览器抠好的透明 PNG）"""
    b = request.get_json(force=True) or {}
    p = store.load(pid)
    o = _scene_opts(b)
    cut = None
    if b.get("image"):
        try:
            cut = scene_ai.open_rgba(scenes._png_b64_to_bytes(b["image"]))
        except Exception as e:  # noqa: BLE001
            return err(f"产品图读取失败：{e}")
    cfg = load_config()
    try:
        r = scene_ai.generate(cfg, p, o["template"] or (scene_ai.suggest(cfg, p) or ["minimal_white"])[0], o["aspect"], o["n"],
                              o["extra"], cut=cut, use_ai_prompt=o["ai_prompt"], do_qa=o["qa"])
    except scene_ai.SceneAIError as e:
        return err(str(e))
    if not r["cands"]:
        return err((r["errors"] or ["没有生成出图片"])[0])
    r["all"] = scene_ai.list_cands(pid)
    return jsonify(r)


@bp.post("/api/products/<pid>/scene-cands/pick")
def scene_pick(pid):
    b = request.get_json(force=True) or {}
    p = store.load(pid)
    imgs = scene_ai.picked_images(pid, [str(x) for x in b.get("ids") or []])
    if not imgs:
        return err("请先选候选图")
    added = _add_images(p, [{"img": im, "kind": "scene", "color": b.get("color", ""), "note": "AI", "keep_aspect": True,
                             "aspect": c.get("aspect")} for im, c in imgs])
    return jsonify({"product": p, "added": len(added), "cands": scene_ai.list_cands(pid)})


@bp.delete("/api/products/<pid>/scene-cands/<cid>")
def scene_cand_del(pid, cid):
    return jsonify({"cands": scene_ai.delete_cand(pid, cid)})


@bp.get("/scene-cand/<pid>/<name>")
def scene_cand_file(pid, name):
    if not re.fullmatch(r"[0-9a-f]{10}\.jpg", name or ""):
        abort(404)
    try:
        d = scene_ai._dir(pid)
    except ValueError:
        abort(404)
    return send_from_directory(d, name)


@bp.get("/api/scenes/batch")
def scene_batch_status():
    return jsonify(scene_ai.batch_status())


@bp.post("/api/scenes/batch")
def scene_batch_start():
    b = request.get_json(force=True) or {}
    u = auth.current_user() or {}

    def add(pid, img, cand):
        q = store.load(pid)
        _add_images(q, [{"img": img, "kind": "scene", "note": "AI", "keep_aspect": True, "aspect": cand.get("aspect")}])
    try:
        return jsonify(scene_ai.batch_start(load_config(), b.get("ids") or [], _scene_opts(b), u.get("username", ""), store.load, add))
    except scene_ai.SceneAIError as e:
        return err(str(e))


@bp.post("/api/scenes/batch/cancel")
def scene_batch_cancel():
    return jsonify(scene_ai.batch_cancel())


# ---------------- 图片 ----------------
@bp.get("/files/<pid>/<kind>/<name>")
def files(pid, kind, name):
    if kind not in ("raw", "out", "model", "source_files"):
        abort(404)
    try:
        store.safe_id(pid)
    except ValueError:      # v2.41：乱写的产品编码以前是 500
        abort(404)
    return send_from_directory(store.image_dir(pid, kind), name, as_attachment=kind == "source_files")


@bp.post("/api/products/<pid>/images")
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


@bp.post("/api/products/<pid>/images/process")
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


@bp.post("/api/products/<pid>/images/white")
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


@bp.get("/api/imgtool/status")
def imgtool_status():
    return jsonify(imgtools.status())


@bp.post("/api/imgtool/removebg")
def imgtool_removebg():
    b = request.get_json(force=True) or {}
    return maybe_async("抠图", lambda: _removebg(b), "removebg")


def _removebg(b):
    try:
        out = imgtools.remove_bg(imgtools.from_data_url(b.get("data")), b.get("model") or "isnet")
    except (ValueError, RuntimeError) as e:
        return err(str(e))
    return jsonify({"data": imgtools.to_data_url(out)})


@bp.post("/api/imgtool/inpaint")
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


@bp.post("/api/imgtool/install-lama")
def imgtool_install_lama():
    if not auth.is_owner() and auth.current_user():
        return err("只有老板可以安装组件", 403)
    return jsonify(imgtools.install_lama())


@bp.post("/api/products/<pid>/images/edited")
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


@bp.post("/api/products/<pid>/images/restore")
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


@bp.post("/api/products/<pid>/images/reorder")
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
        wb = p.get("white_bg") or {}
        if wb.get("file") and wb["file"] in (i.get("file"), i.get("raw")):      # v2.40：白底图就是这张（渲染图）→ 一起清掉
            p["white_bg"] = None
    store.save(p)
    return jsonify(p)


@bp.post("/api/products/<pid>/images/host")
def image_host(pid):
    """把还没有网址的图片传到图床（导出表格用）。v2.43.1：同时传 4 张、大图先压缩，每传好一张就记下，
    一张失败不影响别的（以前一张一张传，一张卡住整个按钮转几分钟，中途传好的也没保存）。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from core import bgjobs
    cfg = load_config()
    key = cfg.get("imgbb_api_key")
    if not key:
        return err("还没有填写 imgbb 图床密钥（设置页）")
    p = store.load(pid)
    targets = [im for im in list(p.get("images", [])) + ([p["white_bg"]] if p.get("white_bg") else []) if not im.get("url")]

    def path_of(img):
        folder = "out" if img.get("processed") or img["file"].startswith("white_") else "raw"
        return os.path.join(store.image_dir(pid, folder), img["file"])

    done, failed = {}, []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(imghost.upload_imgbb, key, path_of(im)): im for im in targets}
        for i, f in enumerate(as_completed(futs)):
            im = futs[f]
            bgjobs.note(stage=f"{i + 1}/{len(targets)}")
            try:
                done[im["file"]] = f.result()
            except (imghost.HostError, OSError) as e:
                failed.append(f"{im['file']}：{e}")
            if done and (i % 4 == 3 or i == len(targets) - 1):
                _save_host_urls(pid, done)
    _save_host_urls(pid, done)
    p = store.load(pid)
    if failed and not done:
        return err("上传图床失败：" + "；".join(failed[:3]))
    return jsonify({"product": p, "uploaded": len(done), "failed": failed})


def _save_host_urls(pid, urls):
    """把传好的网址写回产品（重新读一次再写：上传期间别人改了产品也不会被盖掉）。"""
    if not urls:
        return
    q = store.load(pid)
    for im in list(q.get("images", [])) + ([q["white_bg"]] if q.get("white_bg") else []):
        if not im.get("url") and im.get("file") in urls:
            im["url"] = urls[im["file"]]
    store.save(q)


@bp.post("/api/products/<pid>/images/url")
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


@bp.post("/api/products/<pid>/keywords")
def ai_keywords(pid):
    """AI 关键词扩展：按泰国平台搜索习惯列出所有相关搜索词。"""
    from core import keywords
    p = request.get_json(force=True) or store.load(pid)
    try:
        plan = keywords.research(load_config(), p, _cat_name(p))
    except ai_copy.AIError as e:
        return err(str(e))
    return jsonify({"plan": plan, "keywords": keywords.keywords_field(plan)})


@bp.post("/api/products/<pid>/ai")
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


@bp.post("/api/products/<pid>/ai-en")
def ai_english(pid):
    """按泰文生成英文标题和英文详情（v2.22）。body 可以带编辑页里还没保存的产品。"""
    p = request.get_json(silent=True) or store.load(pid)
    try:
        return jsonify(ai_copy.to_english(load_config(), p))
    except ai_copy.AIError as e:
        return err(str(e))


@bp.post("/api/products/<pid>/ai-complete")
def ai_complete(pid):
    """把空着的文案字段补完整（英文标题 / 详情、Shopee 标题和标签、包装内容、变体名称和选项泰文……），已经有的不动（v2.22）。
    body 可以带编辑页里还没保存的产品；返回补出来的字段，由页面合进去。"""
    p = request.get_json(silent=True) or store.load(pid)
    try:
        return jsonify({"ok": True, "fields": ai_copy.complete_copy(load_config(), p, p.get("keyword_plan"))})
    except ai_copy.AIError as e:
        return err(str(e))


@bp.post("/api/products/fill-copy")
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


@bp.post("/api/ai/back-translate")
def ai_back():
    body = request.get_json(force=True) or {}
    try:
        return jsonify(ai_copy.back_translate(load_config(), body.get("title_th", ""), body.get("description_th", "")))
    except ai_copy.AIError as e:
        return err(str(e))


@bp.get("/api/skus")
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
                out.append({"sku": v["sku"], "name": p.get("name_zh", ""), "color": v.get("opt1_zh", ""), "price": price, "pid": p.get("id") or item["id"]})
    return jsonify(out)


@bp.post("/api/groups")
def groups_post():
    b = request.get_json(force=True) or {}
    try:
        extras.group_save(b.get("name"), b.get("id"))
    except ValueError as e:
        return err(str(e))
    return groups_get()


@bp.delete("/api/groups/<int:gid>")
def groups_delete(gid):
    extras.group_delete(gid)
    return groups_get()


@bp.post("/api/groups/assign")
def groups_assign():
    b = request.get_json(force=True) or {}
    n = extras.group_assign(b.get("ids") or [], int(b.get("group") or 0), bool(b.get("add", True)))
    return jsonify({"changed": n, "groups": extras.groups()})


@bp.post("/api/goods/marks")
def goods_marks():
    """手动标记：{ids, mark: upload|edit, on, note}。"""
    from core import prodgroups
    b = request.get_json(force=True) or {}
    try:
        n = prodgroups.set_mark([str(x) for x in b.get("ids") or []][:2000], b.get("mark"), bool(b.get("on", True)), b.get("note"),
                                _uname(), b.get("scope") or "goods")
    except ValueError as e:
        return err(str(e), 400)
    return jsonify({"changed": n})


@bp.get("/api/goods/views")
def goods_views():
    from core import prodgroups
    return jsonify({"views": prodgroups.views(request.args.get("scope") or "goods")})


@bp.post("/api/goods/views")
def goods_views_save():
    from core import prodgroups
    b = request.get_json(force=True) or {}
    try:
        return jsonify({"views": prodgroups.view_save(b.get("name"), b.get("state"), b.get("scope") or "goods", _uname())})
    except ValueError as e:
        return err(str(e), 400)


@bp.delete("/api/goods/views/<int:vid>")
def goods_views_del(vid):
    from core import prodgroups
    return jsonify({"views": prodgroups.view_delete(vid, request.args.get("scope") or "goods")})


@bp.post("/api/goods/group-settings")
def goods_group_settings():
    from core import prodgroups
    if not auth.is_owner():
        return err("只有老板能改阈值", 403)
    try:
        return jsonify({"settings": prodgroups.save_settings(request.get_json(force=True) or {})})
    except ValueError as e:
        return err(str(e), 400)



# ---------------- 规格确认、按耗材算的库存（v2.16） ----------------
@bp.post("/api/products/<pid>/specs/<path:spec_id>/<action>")
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


@bp.post("/api/products/<pid>/license")
def license_verify(pid):
    """v2.50 许可核验（从「商品 → 选品」采用的草稿：license_check 待核验时不能导出 / 推送）。
    {verified: true/false, force: 初判禁止商用也通过, note}"""
    from core import copyrules
    b = request.get_json(force=True, silent=True) or {}
    try:
        p = copyrules.verify_license(pid, bool(b.get("verified", True)), bool(b.get("force")), _uname(), b.get("note") or "")
    except FileNotFoundError:
        return err("没有这个产品", 404)
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True, "product": p})


@bp.post("/api/products/<pid>/ip-risk")
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


@bp.get("/api/products/<pid>/stock")
def product_stock(pid):
    from core import stockcalc
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("产品不存在", 404)
    cfg = load_config()
    return jsonify({"ok": True, "auto": stockcalc.enabled(p, cfg), "global": bool(cfg.get("stock_auto")),
                    "own": p.get("stock_auto"), "rows": stockcalc.compute(p, cfg), "settings": stockcalc.settings(cfg)})


@bp.post("/api/products/<pid>/stock-auto")
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


@bp.get("/api/stock/pending")
def stock_pending():
    from core import stockcalc
    plat = request.args.get("platform") or "lazada"
    return jsonify({"ok": True, "items": stockcalc.pending(plat), "settings": stockcalc.settings()})


@bp.post("/api/stock/mark-synced")
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


# ---------------- 类目与属性 ----------------
@bp.get("/api/categories")
def category_list():
    return jsonify(categories.library())


@bp.get("/api/category-fields")
def category_fields():
    cat = categories.get(request.args.get("id"))
    if not cat:
        return err("找不到类目", 404)
    fields = lazada_template.attribute_fields(cat)
    return jsonify({"id": cat["id"], "name": cat["name"], "cat_id": cat["cat_id"], "source": cat.get("source") or "template",
                    "needs_license": categories.needs_license(cat["cat_id"]),
                    "fields": [{k: f[k] for k in ("key", "label", "required", "options", "tip", "kind")}
                               for f in fields]})


# ---------------- Shopee ----------------
@bp.get("/api/shopee/categories")
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
                d = ai_copy.extract_json(ai_copy.call(ai_copy.tcfg(load_config(), "keywords"), "Translate e-commerce search words. Output only JSON.",
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


@bp.get("/api/shopee/attrs")
def shopee_attrs():
    """v2.25：Shopee 类目的属性（必填的在前，带可选值）。"""
    return jsonify({"attrs": shopee.attrs_for(request.args.get("id") or "", 80)})


@bp.post("/api/products/<pid>/shopee-attrs")
def shopee_attrs_fill(pid):
    """AI 给 Shopee 必填属性挑值。body 可以带编辑页里没保存的产品。返回 {属性ID: {...}}，页面合进 P.shopee_attrs。"""
    p = request.get_json(silent=True) or store.load(pid)
    try:
        return jsonify({"values": shopee.fill_attrs(load_config(), p)})
    except ai_copy.AIError as e:
        return err(str(e))


@bp.get("/api/shopee/tree")
def shopee_tree():
    return jsonify([[cid, path, r] for cid, (path, r) in shopee.tree().items()])


# ---------------- 模板、导出 ----------------
@bp.get("/api/templates/sync")
def templates_sync_status():
    """v2.25：Lazada 全部类目模板的自动下载进度。"""
    from core import lazada_sync
    return jsonify(lazada_sync.status())


@bp.post("/api/templates/sync")
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


@bp.get("/api/templates")
def templates():
    return jsonify(categories.template_files())


@bp.post("/api/templates")
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


@bp.delete("/api/templates/<name>")
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


# ---------------- 给运营分析系统的商品图片（v2.32.1，只读密钥）----------------
@bp.get("/api/v1/images/<path:image_id>")
def v1_image(image_id):
    """GET /api/v1/images/<图片编号>[?size=thumb]：只读下载商品图片。编号不对 / 拼路径一律 404。"""
    from modules.goods import openapi
    path = openapi.resolve(image_id)
    if not path:
        return jsonify({"ok": False, "code": "not_found", "error": "图片不存在"}), 404
    mt = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    etag = image_id
    if request.args.get("size") == "thumb":
        try:
            path, mt = openapi.thumb(path, image_id)
            etag += "-t"
        except Exception:  # noqa: BLE001  小图做不出来就给原图
            pass
    resp = send_file(path, mimetype=mt, conditional=True, etag=etag, max_age=86400)
    return resp

