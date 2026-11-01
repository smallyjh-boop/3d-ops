"""3D 模型模块（基础模块）的接口：上传 / 预览 / 模型库 / 规格模型 / 几何分析 / 打印建议 / 估算切片。
v2.31 从 web/products.py 搬过来。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403

bp = Blueprint("m_model", __name__)
PREFIXES = []
PATTERNS = []


@bp.post("/api/products/<pid>/model")
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


@bp.post("/api/products/<pid>/model/metrics")
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


@bp.post("/api/products/<pid>/print-advice")
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


@bp.post("/api/products/<pid>/print-advice/apply")
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


@bp.post("/api/products/<pid>/slice")
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


@bp.get("/api/products/<pid>/model/preview")
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


@bp.get("/api/products/<pid>/model/stl")
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


@bp.get("/api/products/<pid>/model/download")
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


@bp.get("/api/products/<pid>/model/history")
def model_history(pid):
    from core import filemgr
    return jsonify({"history": filemgr.model_history(pid)})


@bp.get("/api/products/<pid>/model/history/<name>")
def model_history_download(pid, name):
    from core import filemgr
    fp = filemgr.history_path(pid, name)
    if not fp:
        return err("文件不存在", 404)
    return send_file(fp, as_attachment=True, download_name=f"{pid}_old_{name.partition('__')[2] or name}")


@bp.post("/api/products/<pid>/model/restore")
def model_restore(pid):
    from core import filemgr
    try:
        r = filemgr.restore_model(pid, (request.get_json(force=True) or {}).get("name", ""), _uname())
    except (ValueError, OSError) as e:
        return err(str(e))
    return jsonify({"ok": True, "files_reset": r["files_reset"]})


@bp.delete("/api/products/<pid>/model")
def model_delete(pid):
    from core import filemgr
    filemgr.delete_model(pid)
    return jsonify({"ok": True})


@bp.get("/api/products/<pid>/models")
def models_lib(pid):
    try:
        return jsonify(modellib.library(pid))
    except FileNotFoundError:
        return err("找不到这个产品", 404)


@bp.post("/api/products/<pid>/models")
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


@bp.post("/api/products/<pid>/models/reanalyze")
def models_reanalyze(pid):
    return maybe_async(f"重新分析模型 {pid}", lambda: jsonify(modellib.library(pid, reanalyze=True)), "model_re", pid)


@bp.post("/api/products/<pid>/models/current")
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


@bp.post("/api/products/<pid>/models/layout-preview")
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


@bp.post("/api/products/<pid>/models/ai-check")
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


@bp.post("/api/products/<pid>/models/<eid>/spec")
def models_spec(pid, eid):
    try:
        return jsonify(modellib.set_spec(pid, eid, (request.get_json(force=True) or {}).get("spec") or "", _uname()))
    except ValueError as e:
        return err(str(e))


@bp.delete("/api/products/<pid>/models/<eid>")
def models_delete(pid, eid):
    try:
        return jsonify(modellib.remove(pid, eid, _uname()))
    except ValueError as e:
        return err(str(e))


@bp.get("/api/products/<pid>/models/<eid>/<what>")
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


@bp.get("/api/products/<pid>/mesh")
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


@bp.get("/api/products/<pid>/filaments")
def product_filaments(pid):
    """某台打印机可选的耗材配置（按产品材料筛选）。"""
    from core import recipes
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("产品不存在", 404)
    mat = request.args.get("material") or p.get("material") or "PLA"
    return jsonify(recipes.filament_choices(int(request.args.get("printer") or 0), mat))


# ---------------- 规格 ↔ 3D 模型（v2.22） ----------------
@bp.get("/api/products/<pid>/spec-models")
def spec_models_get(pid):
    from core import specmodel
    try:
        return jsonify(specmodel.overview(pid))
    except FileNotFoundError:
        return err("产品不存在", 404)


@bp.post("/api/products/<pid>/spec-models")
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


@bp.post("/api/products/<pid>/spec-models/parts")
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


@bp.post("/api/products/<pid>/spec-models/auto-parts")
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


@bp.post("/api/products/<pid>/spec-models/flatten")
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


@bp.post("/api/products/<pid>/spec-models/auto")
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


@bp.post("/api/products/<pid>/spec-models/fill")
def spec_models_fill(pid):
    """按规格的模型估算填这个规格（所有颜色）的克数和时长。"""
    from core import specmodel
    b = request.get_json(force=True) or {}
    try:
        n = specmodel.fill_grams(pid, b.get("spec") or "", _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True, "filled": n, "product": store.load(pid), **specmodel.overview(pid)})


# ---------------- v2.52 打印方案（每个规格：几盘、手动摆盘、AMS 槽、配色）+ 展示模型（组装姿势） ----------------
from . import assembly as _asm, printplan as _pp  # noqa: E402


def _plan_payload(pid, spec, plan=None, checks=None):
    from core import mesh, specmodel
    p = store.load(pid)
    plan = plan or _pp.get_plan(p, spec)
    fps, chk, warn, pchk = {}, {}, [], {}
    for pl in plan.get("plates") or []:
        try:
            f = _pp.fps_for(pid, p, pl)
        except (ValueError, OSError) as e:
            warn.append(str(e))
            continue
        fps.update(f)
        if any(it.get("x") is None for it in pl.get("items") or []):
            if pl.get("manual") and any(it.get("x") is not None for it in pl.get("items") or []):
                _pp.place_new(pl, _pp.bed_of(pl["printer"]), f)
            else:
                _pp.auto_arrange(pl, _pp.bed_of(pl["printer"]), f)
        chk[pl["id"]] = (checks or {}).get(pl["id"]) or _pp.check_plate(pl, _pp.bed_of(pl["printer"]), f)
        try:
            pchk[pl["id"]] = _pp.plate_checks(p, pl, f)
        except (ValueError, OSError) as e:
            warn.append(str(e))
    colours = list(dict.fromkeys((v.get("opt1_zh") or "").strip() for v in p.get("variants") or []
                                 if (v.get("opt2_zh") or "").strip() == spec and (v.get("opt1_zh") or "").strip()))
    p2 = dict(p, print_plans=dict(p.get("print_plans") or {}, **{spec: plan}))
    use = {}
    for c in colours or [""]:
        try:
            use[c] = _pp.usage(p2, spec, c)
        except (ValueError, OSError) as e:
            warn.append(str(e))
    cfg = load_config()
    if auth.is_owner():
        from core import pricing
        for c, u in use.items():
            if u["multicolor"]:
                u["cost"] = pricing.colour_cost(cfg, u["colours"], u["hours"], p.get("material"))
            else:
                u["cost"] = pricing.variant_cost(cfg, u["grams"], u["hours"], p.get("material"))
    lib = []
    for e in p.get("model_lib") or []:
        info = e.get("info") or {}
        if not info.get("ok"):
            continue
        ci = info.get("colors") or {}
        lib.append({"id": e["id"], "name": e.get("orig_name") or e["file"], "best": info.get("best"), "size": info.get("size"),
                    "parts": [{"index": x.get("index"), "name": x.get("name"), "best": x.get("best"), "size": x.get("size")} for x in info.get("parts") or []],
                    "multicolor": bool(ci.get("multicolor")), "painted": bool(ci.get("painted")),
                    "colors": {"filaments": ci.get("filaments"), "used": ci.get("used"), "usage": ci.get("usage")} if ci.get("multicolor") else None,
                    "main": (p.get("model") or {}).get("lib_id") == e["id"], "origin": e.get("origin") or "",
                    "parts_of": [{"id": d.get("id"), "part": d.get("part"), "qty": d.get("qty"), "label": d.get("label")} for d in e.get("parts_of") or []] or None,
                    "cut_of": e.get("cut_of"), "orients": [{k: o.get(k) for k in ("key", "contact_cm2", "overhang_cm2", "size_mm", "score")} for o in info.get("orients") or []]})
    specs = [{"spec": s, "own": specmodel.own(p, s), "has_plan": s in (p.get("print_plans") or {})} for s in specmodel.specs(p)]
    summ = _pp.plan_summary(p2 if plan.get("from_display") else p, spec, cfg)
    return {"spec": spec, "plan": plan, "footprints": fps, "checks": chk, "usage": use, "colours": colours, "library": lib,
            "printers": _pp.printer_models(cfg), "specs": specs, "orient_zh": mesh.ORIENT_ZH, "material": p.get("material") or "PLA",
            "warnings": warn, "slot_max": _pp.SLOT_MAX, "state": summ["state"], "follow": bool(plan.get("follow")), "scale": plan.get("scale"),
            "purge": {"g": cfg.get("mc_purge_g", 1.5), "s": cfg.get("mc_change_s", 50)},
            # v2.55：每盘参数（原来「打印方案」面板的）、每盘规则检查
            "plate_checks": pchk, "params_meta": _params_meta(cfg), "model_entry": (_pp._spec_entry(p, spec) or {}).get("id")}


def _params_meta(cfg):
    from core import recipes
    names = [x.get("name") for x in cfg.get("printers") or []]
    return {"support_zh": recipes.SUPPORT_ZH, "bed_types": recipes.BED_TYPES, "patterns": _pp.PATTERNS, "materials": recipes.MATERIALS,
            "temp_range": recipes.TEMP_RANGE, "printer_idx": {n: names.index(n) for n in names if n}, "ov_range": {k: v[:2] for k, v in _pp.OV_RANGE.items()}}


@bp.get("/api/products/<pid>/print-plan")
def print_plan_get(pid):
    try:
        return jsonify(_plan_payload(pid, (request.args.get("spec") or "").strip()))
    except FileNotFoundError:
        return err("产品不存在", 404)
    except ValueError as e:
        return err(str(e))


@bp.post("/api/products/<pid>/print-plan")
def print_plan_save(pid):
    b = request.get_json(force=True) or {}
    spec = (b.get("spec") or "").strip()
    try:
        r = _pp.save_plan(pid, spec, b.get("plan") or {}, _uname())
        db.audit(_uname(), "保存打印方案（盘 / 多色）", pid, spec or "主模型")
        return jsonify(_plan_payload(pid, spec, r["plan"], r["checks"]))
    except FileNotFoundError:
        return err("产品不存在", 404)
    except ValueError as e:
        return err(str(e))


@bp.post("/api/products/<pid>/print-plan/footprint")
def print_plan_footprint(pid):
    """零件按方向放平后的俯视轮廓（编辑盘时加零件 / 换方向用，不保存）。"""
    b = request.get_json(force=True) or {}
    try:
        p = store.load(pid)
        return jsonify({"items": [_pp.footprint(pid, x.get("id"), x.get("part"), x.get("orient") or "bottom", p, x.get("scale") or 1,
                                                x.get("face"), x.get("mirror") or "") for x in (b.get("items") or [])[:200]]})
    except (ValueError, OSError) as e:
        return err(str(e))


@bp.post("/api/products/<pid>/print-plan/check")
def print_plan_check(pid):
    """检查 / 自动排列一盘（不保存）：{plate, arrange: bool} → {plate, check}"""
    b = request.get_json(force=True) or {}
    try:
        p = store.load(pid)
        plan = _pp.clean_plan(p, {"plates": [b.get("plate") or {}]})
        pl = plan["plates"][0]
        f = _pp.fps_for(pid, p, pl)
        bed = _pp.bed_of(pl["printer"])
        miss = 0
        if b.get("arrange") or any(it.get("x") is None for it in pl["items"]):
            miss = _pp.auto_arrange(pl, bed, f)
        if not pl.get("params"):
            pl = _pp._migrate(p, (b.get("spec") or "").strip(), plan)["plates"][0]     # 不改传进去的，返回补好的拷贝
        return jsonify({"plate": pl, "check": _pp.check_plate(pl, bed, f), "footprints": f, "missed": miss, "bed": bed,
                        "plate_checks": _pp.plate_checks(p, pl, f)})
    except (ValueError, OSError) as e:
        return err(str(e))


@bp.post("/api/products/<pid>/print-plan/op")
def print_plan_op(pid):
    """v2.55 编辑器的多选操作（复制 / 删除 / 镜像 / 旋转 / 缩放 / 换槽 / 方向 / 对齐 / 分布 / 成组 / 拆分 / 移到别的盘 / 单独参数 / 切割…），
    不保存，返回改好的方案。{spec, plan, op: {op, plate, uids, …}}（见 printplan.apply_op）"""
    b = request.get_json(force=True) or {}
    if (b.get("op") or {}).get("op") == "cut":       # 切割会往模型库里写两个新文件：和别的改模型库的接口一样要权限
        no = _need("models.change")
        if no:
            return no

    def go():
        try:
            r = _pp.apply_op(pid, (b.get("spec") or "").strip(), b.get("plan") or {}, b.get("op") or {}, _uname())
            if (b.get("op") or {}).get("op") == "cut":
                db.audit(_uname(), "打印方案：切割零件", pid, ", ".join(x["name"] for x in r.get("cut") or []))
            return jsonify(r)
        except FileNotFoundError:
            return err("产品不存在", 404)
        except (ValueError, OSError) as e:
            return err(str(e))
    if (b.get("op") or {}).get("op") in ("cut", "auto_orient", "split"):
        return maybe_async(f"打印方案编辑 {pid}", go, "model_lib", pid)
    return go()


@bp.post("/api/products/<pid>/print-plan/orients")
def print_plan_orients(pid):
    """v2.55 一个零件的方向卡片（六个方向 + 推荐的面），{id, part, scale}"""
    b = request.get_json(force=True) or {}
    try:
        part = b.get("part")
        return jsonify(_pp.orient_options(pid, b.get("id"), None if part in (None, "") else int(part), b.get("scale") or 1))
    except FileNotFoundError:
        return err("产品不存在", 404)
    except (ValueError, OSError) as e:
        return err(str(e))


@bp.post("/api/products/<pid>/print-plan/kit")
def print_plan_kit(pid):
    """组合摆盘（按说明 / AI）：一套零件按组装关系摆在一起（不保存，前台当初稿再手动调）。{plate, ai: bool}"""
    b = request.get_json(force=True) or {}

    def go():
        try:
            p = store.load(pid)
            pl = _pp.clean_plan(p, {"plates": [b.get("plate") or {}]})["plates"][0]
            r = _pp.kit_layout(pid, pl, use_ai=b.get("ai", True) is not False)
            bed = _pp.bed_of(pl["printer"])
            return jsonify({"plate": pl, "check": _pp.check_plate(pl, bed, r["footprints"]), "footprints": r["footprints"], "bed": bed,
                            "source": r["source"], "groups": r["groups"], "note_zh": r["note_zh"], "note_th": r["note_th"], "missed": r["missed"]})
        except (ValueError, OSError) as e:
            return err(str(e))
    return maybe_async(f"组合摆盘 {pid}", go, "ai_check", pid)


@bp.post("/api/products/<pid>/print-plan/merge")
def print_plan_merge(pid):
    """把一盘按摆好的位置合并成一个模型：规格有自己的模型 → 指定给规格；主模型 → 设为 3D 模型。
    v2.53：只影响打印 —— 展示没有自己选零件时会把合并出来的模型拆回原来的零件（assembly.resolve）。"""
    b = request.get_json(force=True) or {}

    def go():
        from core import specmodel
        spec = (b.get("spec") or "").strip()
        p = store.load(pid)
        plan = _pp.get_plan(p, spec)
        pl = next((x for x in plan["plates"] if x["id"] == b.get("plate_id")), None)
        if not pl:
            return err("没有这一盘")
        f = _pp.fps_for(pid, p, pl)
        if not pl.get("manual") or any(it.get("x") is None for it in pl["items"]):
            _pp.auto_arrange(pl, _pp.bed_of(pl["printer"]), f)
        sel = _pp.plate_selection(pl)
        try:
            if spec:
                e = modellib.make_entry(pid, sel, _uname(), name=f"{spec}_{pl['id']}", variant=spec, sets=pl.get("sets") or 1)
                specmodel.map_spec(pid, spec, e["id"], _uname())
                return jsonify({"ok": True, "entry": e["id"], "spec": spec})
            r = modellib.make_current(pid, sel, _uname(), name=f"plate_{pl['id']}", sets=pl.get("sets") or 1)
            return jsonify({"ok": True, "entry": (r.get("merged") or {}).get("id"), "files_reset": r["files_reset"]})
        except ValueError as e:
            return err(str(e))
    return maybe_async(f"按摆好的盘合并 {pid}", go, "model_lib", pid)


@bp.get("/api/products/<pid>/print-plan/export")
def print_plan_export(pid):
    """下载一盘的 3MF（按摆好的位置，每个零件带耗材槽；拓竹 Studio / OrcaSlicer 打开就是摆好、分好色的）。"""
    try:
        path, name = _pp.export_plate(pid, (request.args.get("spec") or "").strip(), request.args.get("plate") or "p1",
                                      (request.args.get("colour") or "").strip())
    except (ValueError, OSError) as e:
        return err(str(e))
    with open(path, "rb") as f:
        data = f.read()
    try:
        os.remove(path)
    except OSError:
        pass
    r = app.response_class(data, mimetype="model/3mf")
    from urllib.parse import quote
    r.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
    return r


@bp.post("/api/products/<pid>/print-plan/slice")
def print_plan_slice(pid):
    """按摆好的盘切片（多色时每个槽一份耗材配置、开擦料塔）。要 OrcaSlicer；没有时返回说明，界面上继续用估算。"""
    b = request.get_json(force=True) or {}

    def go():
        from core import slicer
        try:
            r = _pp.slice_plate(pid, (b.get("spec") or "").strip(), b.get("plate_id") or "p1", (b.get("colour") or "").strip(),
                                None if b.get("printer") in (None, "") else int(b["printer"]), _uname())
            return jsonify({"ok": True, "sliced": r["sliced"], "file_id": (r.get("file") or {}).get("id"), "warnings": r.get("warnings") or []})
        except slicer.SliceError as e:
            return err(f"切片没有成功：{e}（没有 OrcaSlicer 时克数、冲刷废料按估算，标「估」）")
        except (ValueError, OSError) as e:
            return err(str(e))
    return maybe_async(f"按打印方案切片（盘） {pid}", go, "slice", pid)


@bp.post("/api/products/<pid>/print-plan/fill")
def print_plan_fill(pid):
    b = request.get_json(force=True) or {}
    try:
        n = _pp.fill_variants(pid, (b.get("spec") or "").strip(), _uname())
    except (ValueError, OSError) as e:
        return err(str(e))
    db.audit(_uname(), "按打印方案填克数时长", pid, f"{n} 个变体")
    return jsonify({"ok": True, "n": n, "product": store.load(pid)})


@bp.get("/api/products/<pid>/display")
def display_get(pid):
    try:
        return jsonify(_asm.get(pid, (request.args.get("spec") or "").strip()))
    except FileNotFoundError:
        return err("产品不存在", 404)
    except (ValueError, OSError) as e:
        return err(str(e))


@bp.post("/api/products/<pid>/display")
def display_save(pid):
    b = request.get_json(force=True) or {}
    try:
        r = _asm.save(pid, b, _uname())
        db.audit(_uname(), "保存展示模型（零件 / 组装姿势）", pid, b.get("spec") or "主模型")
        return jsonify(r)
    except (ValueError, OSError) as e:
        return err(str(e))


@bp.delete("/api/products/<pid>/display")
def display_reset(pid):
    try:
        return jsonify(_asm.reset(pid, _uname(), (request.args.get("spec") or "").strip()))
    except (ValueError, OSError) as e:
        return err(str(e))


def _gz_tris(t):
    import gzip as _gz
    resp = app.response_class(_gz.compress(t.astype("<f4").tobytes(), 4), mimetype="application/octet-stream")
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Cache-Control"] = "private, max-age=600"
    return resp


@bp.get("/api/products/<pid>/display/part/<int:index>")
def display_part(pid, index):
    """第 index 个零件（展示里的顺序）的三角面。"""
    try:
        p = store.load(pid)
        r = _asm.resolve(p, (request.args.get("spec") or "").strip())
        inst = _asm.instances(r["items"])
        if not 0 <= index < len(inst):
            return err("没有这个零件", 404)
        it = inst[index][1]
        return _gz_tris(_asm.part_tris(pid, it["id"], it.get("part")))
    except (ValueError, OSError) as e:
        return err(str(e))


@bp.get("/api/products/<pid>/display/mesh/<eid>/<part>")
def display_mesh(pid, eid, part):
    """模型库文件里一个组件（part = 序号；all = 整个文件）的三角面，组装视图按需读，同一个零件几个只读一次。"""
    try:
        return _gz_tris(_asm.part_tris(pid, eid, None if part == "all" else int(part)))
    except (ValueError, OSError) as e:
        return err(str(e))


_DISP_STL = {}


@bp.get("/api/products/<pid>/display/stl")
def display_stl(pid):
    """按展示（零件 + 组装姿势 + 缩放）拼好的模型（STL），3D 预览和商品图用；展示就是主模型本身时 404（前台用主模型）。"""
    import tempfile as _tf
    from core import mesh
    spec = (request.args.get("spec") or "").strip()
    try:
        p = store.load(pid)
        r = _asm.resolve(p, spec)
        key = (pid, spec, _asm.token(p, r))
        data = _DISP_STL.get(key)
        if data is None:
            t = _asm.assembled_tris(pid, spec)
            if t is None:
                return err("展示就是主模型本身", 404)
            with _tf.NamedTemporaryFile(suffix=".stl", delete=False) as f:
                tmp = f.name
            try:
                mesh.write_stl(t, tmp)
                with open(tmp, "rb") as f:
                    data = f.read()
            finally:
                os.remove(tmp)
            if len(_DISP_STL) > 6:
                _DISP_STL.clear()
            _DISP_STL[key] = data
    except FileNotFoundError:
        return err("产品不存在", 404)
    except (ValueError, OSError) as e:
        return err(str(e))
    return app.response_class(data, mimetype="model/stl")


@bp.get("/api/products/<pid>/display/thumb")
def display_thumb(pid):
    """展示的缩略图（服务器画，按版本缓存），收起时的一行摘要用。"""
    try:
        fp = _asm.thumb_path(pid, (request.args.get("spec") or "").strip())
    except (ValueError, OSError) as e:
        return err(str(e), 404)
    if not fp:
        return err("没有零件", 404)
    r = send_file(fp, mimetype="image/png")
    r.headers["Cache-Control"] = "private, max-age=86400"
    return r


@bp.post("/api/products/<pid>/display/auto-select")
def display_auto_select(pid):
    """「自动选零件」（不保存）。{spec} → {items, note_zh, note_th}"""
    b = request.get_json(force=True) or {}
    try:
        return jsonify(_asm.auto_select(pid, (b.get("spec") or "").strip()))
    except (ValueError, OSError) as e:
        return err(str(e))


@bp.post("/api/products/<pid>/display/auto-assemble")
def display_auto_assemble(pid):
    """「自动组合」按几何形状（不保存）。{spec, items?, parts?} → {parts, confidence, low, note_zh, note_th}"""
    b = request.get_json(force=True) or {}

    def go():
        try:
            return jsonify(_asm.auto_assemble(pid, (b.get("spec") or "").strip(), b.get("items"), b.get("parts")))
        except (ValueError, OSError) as e:
            return err(str(e))
    return maybe_async(f"自动组合 {pid}", go, "model", pid)


@bp.post("/api/products/<pid>/display/settle")
def display_settle(pid):
    """每个零件往下落到贴合（AI 初稿 / 手动摆的再对齐）。{spec, items, parts} → {parts}"""
    b = request.get_json(force=True) or {}
    try:
        return jsonify({"parts": _asm.settle(pid, (b.get("spec") or "").strip(), b.get("items"), b.get("parts") or [])})
    except (ValueError, OSError) as e:
        return err(str(e))


@bp.post("/api/products/<pid>/display/explode")
def display_explode(pid):
    """爆炸图：每个零件沿组装方向拉开多少。{spec, items?, parts?, factor} → {offsets: {key: [dx, dy, dz]}}"""
    b = request.get_json(force=True) or {}
    try:
        f = max(0.0, min(5.0, float(b.get("factor") or 1)))
        return jsonify({"offsets": _asm.explode(pid, (b.get("spec") or "").strip(), b.get("items"), b.get("parts"), f)})
    except (ValueError, OSError, TypeError) as e:
        return err(str(e))


@bp.post("/api/products/<pid>/display/copy")
def display_copy(pid):
    """从某个规格复制展示（零件、数量、姿势）。{spec, from}"""
    b = request.get_json(force=True) or {}
    try:
        r = _asm.copy_from(pid, b.get("spec") or "", b.get("from") or "", _uname())
        db.audit(_uname(), "从规格复制展示", pid, f"{b.get('from') or '主模型'} → {b.get('spec') or '主模型'}")
        return jsonify(r)
    except (ValueError, OSError) as e:
        return err(str(e))


@bp.post("/api/products/<pid>/spec-scale")
def spec_scale(pid):
    """规格「按主模型缩放 N%」：展示和打印方案一起按主模型缩放（不用另外的文件）。{spec, pct}（pct 空 = 取消）"""
    b = request.get_json(force=True) or {}
    spec = (b.get("spec") or "").strip()
    try:
        pct = b.get("pct")
        pct = float(pct) if pct not in (None, "", 0, "0") else None
        r = _asm.set_scale(pid, spec, pct, _uname())
        _pp.set_scale(pid, spec, pct, _uname())
        db.audit(_uname(), "规格按主模型缩放", pid, f"{spec} {pct or '取消'}%")
        return jsonify(r)
    except (ValueError, OSError, TypeError) as e:
        return err(str(e))


@bp.post("/api/products/<pid>/display/ai")
def display_ai(pid):
    """AI 按图片组装（初稿，不保存；结果再按几何往下落到贴合）。"""
    b = request.get_json(force=True) or {}

    def go():
        try:
            return jsonify(_asm.ai_assemble(pid, b.get("renders") or {}, _uname(), b.get("product_image"),
                                            (b.get("spec") or "").strip(), b.get("items"), b.get("snap", True) is not False))
        except ValueError as e:
            return err(str(e))
        except Exception as e:  # noqa: BLE001  AI 没设置 / 网络错误 / 回答不是 JSON
            return err(f"AI 组装失败：{e}")
    return maybe_async(f"AI 按图片组装 {pid}", go, "ai_check", pid)


# ---------------- v2.53 ③ 概览：每个规格的展示 / 打印方案状态，一键全部切片，复制方案，从组装生成方案 ----------------
@bp.get("/api/products/<pid>/model-status")
def model_status(pid):
    """③ 顶部的规格 × 状态表（不读模型文件，快）：每个规格 展示设没设、方案 未保存 / 估 / 已切片、克数、时长、成本。"""
    from core import specmodel
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("产品不存在", 404)
    cfg = load_config()
    owner = auth.is_owner()
    rows = []
    for s in [""] + specmodel.specs(p):
        disp = _asm.summary(p, s)
        plan = _pp.plan_summary(p, s, cfg)
        if owner and plan.get("grams"):
            from core import pricing
            try:
                plan["cost"] = round(float(pricing.variant_cost(cfg, plan["grams"], plan["hours"] or 0, p.get("material")).get("total") or 0), 1)
            except Exception:  # noqa: BLE001  成本算不了不影响概览
                plan["cost"] = None
        rows.append({"spec": s, "own": bool(s and specmodel.own(p, s)),
                     "variants": sum(1 for v in p.get("variants") or [] if (v.get("opt2_zh") or "").strip() == s) if s else None,
                     "display": disp, "plan": plan})
    return jsonify({"specs": rows, "has_model": bool(p.get("model") or p.get("model_lib")), "slice_all": _pp.SLICE_ALL.get(pid),
                    "main_merged": bool((_asm._main_entry(p) or {}).get("origin") == "merged")})


@bp.post("/api/products/<pid>/print-plan/slice-all")
def print_plan_slice_all(pid):
    """「一键全部切片」：每个规格的每一盘按顺序切（后台任务，进度看 /model-status 的 slice_all）。"""
    b = request.get_json(force=True) or {}

    def go():
        try:
            return jsonify(_pp.slice_all(pid, _uname(), b.get("specs")))
        except (ValueError, OSError) as e:
            return err(str(e))
    return maybe_async(f"一键全部切片 {pid}", go, "slice", pid)


@bp.post("/api/products/<pid>/print-plan/copy")
def print_plan_copy(pid):
    """从某个规格复制打印方案。{spec, from}"""
    b = request.get_json(force=True) or {}
    try:
        _pp.copy_plan(pid, b.get("spec") or "", b.get("from") or "", _uname())
        db.audit(_uname(), "从规格复制打印方案", pid, f"{b.get('from') or '主模型'} → {b.get('spec') or '主模型'}")
        return jsonify(_plan_payload(pid, (b.get("spec") or "").strip()))
    except (ValueError, OSError) as e:
        return err(str(e))


@bp.post("/api/products/<pid>/print-plan/from-display")
def print_plan_from_display(pid):
    """「从组装生成打印方案」：展示里的零件按推荐方向平放、自动排盘（不保存，前台当草稿）。{spec}"""
    b = request.get_json(force=True) or {}
    spec = (b.get("spec") or "").strip()

    def go():
        try:
            plan = _pp.plan_from_display(pid, spec, _uname())
            return jsonify(_plan_payload(pid, spec, plan))
        except (ValueError, OSError) as e:
            return err(str(e))
    return maybe_async(f"从组装生成打印方案 {pid}", go, "model", pid)


@bp.get("/api/products/<pid>/print-plan/thumb")
def print_plan_thumb(pid):
    """一盘的俯视小图（SVG），收起时的一行摘要用。"""
    spec = (request.args.get("spec") or "").strip()
    try:
        p = store.load(pid)
        plan = _pp.get_plan(p, _pp.plan_key(p, spec))
        pl = next((x for x in plan["plates"] if x["id"] == request.args.get("plate")), None) or plan["plates"][0]
        f = _pp.fps_for(pid, p, pl)
        bed = _pp.bed_of(pl["printer"])
        if not pl.get("manual") or any(it.get("x") is None for it in pl["items"]):
            _pp.auto_arrange(pl, bed, f)
    except (ValueError, OSError, IndexError, KeyError) as e:
        return err(str(e), 404)
    W, D = float(bed[0]), float(bed[1])
    polys = []
    for it in pl["items"]:
        if it["uid"] not in f or it.get("x") is None:
            continue
        pts = " ".join(f"{x:.1f},{D - y:.1f}" for x, y in _pp._poly(f[it["uid"]], it["x"], it["y"], it.get("rot") or 0))
        polys.append(f'<polygon points="{pts}" fill="#90caf9" stroke="#1e3a5f" stroke-width="1.2"/>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-4 -4 {W + 8:.0f} {D + 8:.0f}" width="96" height="{96 * D / W:.0f}">'
           f'<rect x="0" y="0" width="{W:.0f}" height="{D:.0f}" rx="6" fill="#eef1f5" stroke="#8a97a8" stroke-width="2"/>' + "".join(polys) + "</svg>")
    r = app.response_class(svg, mimetype="image/svg+xml")
    r.headers["Cache-Control"] = "no-cache"
    return r


# ---------------- v2.56（T36）在切片软件（Bambu Studio / OrcaSlicer）里编辑一盘 ----------------
def _es():
    from modules.model import editsession
    return editsession


def _udisp():
    u = auth.current_user() or {}
    return u.get("username") or "", u.get("display_name") or u.get("username") or ""


@bp.get("/api/products/<pid>/print-plan/edit/status")
def print_plan_edit_status(pid):
    """这个规格每一盘：用哪个软件编辑、谁在编辑（锁）、主文件、需要确认。"""
    from core import fleet
    spec = (request.args.get("spec") or "").strip()
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return err("产品不存在", 404)
    plan = _pp.get_plan(p, spec)
    me, _d = _udisp()
    sessions = _es().open_for(pid, spec)
    plates = []
    for pl in plan.get("plates") or []:
        m = pl.get("master") or {}
        plates.append({"id": pl["id"], "app": fleet.slicer_app_of(pl), "session": next((s for s in sessions if s["plate"] == pl["id"]), None),
                       "master": {k: m.get(k) for k in ("app", "application", "app_ver", "saved_at", "by", "plate_no", "painted")} if m else None,
                       "history": len(m.get("history") or []) + (1 if m else 0), "confirm": pl.get("confirm") or [], "confirmed": pl.get("confirmed")})
    return jsonify({"plates": plates, "me": me, "apps": _es().sp.APPS, "follow": bool(plan.get("follow"))})


@bp.post("/api/products/<pid>/print-plan/edit/start")
def print_plan_edit_start(pid):
    b = request.get_json(force=True) or {}
    me, disp = _udisp()
    es = _es()
    try:
        r = es.start(pid, (b.get("spec") or "").strip(), str(b.get("plate_id") or "p1"), (b.get("colour") or "").strip(),
                     str(b.get("app") or ""), me, disp)
    except FileNotFoundError:
        return err("产品不存在", 404)
    except es.LockedError as e:
        return jsonify({"error": str(e), "locked": {k: e.session.get(k) for k in ("user", "display", "app", "started")}}), 409
    except ValueError as e:
        return err(str(e))
    db.audit(me, f"开始在 {r['app_name']} 里编辑打印方案", pid, f"{b.get('spec') or '主模型'} {b.get('plate_id')}")
    return jsonify(r)


def _own_session(sid):
    s = _es().get(sid)
    if not s:
        return None, err("没有这个编辑会话", 404)
    me, _d = _udisp()
    if s.get("user") != me and not auth.is_owner():
        return None, err("这是别人的编辑会话", 403)
    return s, None


@bp.post("/api/products/<pid>/print-plan/edit/finish")
def print_plan_edit_finish(pid):
    b = request.get_json(force=True) or {}
    me, _d = _udisp()
    try:
        return jsonify({"ok": True, "session": _es().finish(str(b.get("sid") or ""), me, auth.is_owner())})
    except PermissionError as e:
        return err(str(e), 403)
    except ValueError as e:
        return err(str(e))


@bp.post("/api/products/<pid>/print-plan/edit/abandon")
def print_plan_edit_abandon(pid):
    b = request.get_json(force=True) or {}
    me, _d = _udisp()
    try:
        s = _es().abandon(str(b.get("sid") or ""), me, auth.is_owner())
    except PermissionError as e:
        return err(str(e), 403)
    except ValueError as e:
        return err(str(e))
    db.audit(me, "放弃在切片软件里的编辑（恢复到编辑前）", pid, f"{s.get('spec') or '主模型'} {s.get('plate')}")
    return jsonify({"ok": True, "session": s})


@bp.post("/api/products/<pid>/print-plan/edit/upload")
def print_plan_edit_upload(pid):
    """网页上传框：软件里改好保存的 3MF 拖回来（登录的人自己的会话）。"""
    request.max_content_length = _es().MAX_UPLOAD          # 项目文件可能比全局上限（60 MB）大
    sid = request.args.get("sid") or ""
    s, bad = _own_session(sid)
    if bad:
        return bad
    f = request.files.get("file")
    data = f.read() if f else request.get_data()
    try:
        return jsonify(_es().upload(sid, s["token"], data))
    except PermissionError as e:
        return err(str(e), 403)
    except ValueError as e:
        return err(str(e))


@bp.post("/api/products/<pid>/print-plan/edit/confirm")
def print_plan_edit_confirm(pid):
    b = request.get_json(force=True) or {}
    me, _d = _udisp()
    try:
        pl = _es().confirm_plate(pid, (b.get("spec") or "").strip(), str(b.get("plate_id") or ""), me, auth.is_owner())
    except PermissionError as e:
        return err(str(e), 403)
    except (ValueError, FileNotFoundError) as e:
        return err(str(e))
    return jsonify({"ok": True, "confirmed": pl.get("confirmed")})


@bp.get("/api/products/<pid>/print-plan/edit/master")
def print_plan_edit_master(pid):
    """下载这一盘现在的主文件（切片软件保存的项目 3MF）。"""
    spec = (request.args.get("spec") or "").strip()
    try:
        plan = _pp.get_plan(store.load(pid), spec)
    except FileNotFoundError:
        return err("产品不存在", 404)
    pl = next((x for x in plan.get("plates") or [] if x["id"] == request.args.get("plate")), None)
    path = _es().master_path(pid, spec, pl) if pl else None
    if not path:
        return err("这一盘还没有主文件", 404)
    return send_file(path, mimetype="model/3mf", as_attachment=True, download_name=f"{pid}_{pl['id']}_master.3mf")


# 不用登录（带会话密钥）：桌面客户端下载编辑文件、保存后自动回传
@bp.get("/api/slicer-edit/<sid>/file")
def slicer_edit_file(sid):
    try:
        path, name = _es().take_download(sid, request.args.get("t"))
    except PermissionError as e:
        return err(str(e), 403)
    return send_file(path, mimetype="model/3mf", as_attachment=True, download_name=name)


@bp.post("/api/slicer-edit/<sid>/upload")
def slicer_edit_upload(sid):
    request.max_content_length = _es().MAX_UPLOAD
    f = request.files.get("file")
    data = f.read() if f else request.get_data()
    try:
        r = _es().upload(sid, request.args.get("t") or request.headers.get("X-Edit-Token"), data)
    except PermissionError as e:
        return err(str(e), 403)
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True, "confirm": r["confirm"], "changes": r["changes"], "session": r["session"],
                    "new_plates": r["new_plates"], "deleted": r["deleted"]})
