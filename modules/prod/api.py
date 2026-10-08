"""生产模块的接口：排单、打印机、切片文件、打印方案、耗材料卷、成品备货、质量、保养、打印单据。
v2.31 从 web/production.py 搬过来。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403

bp = Blueprint("m_prod", __name__)
PREFIXES = ['/api/print-files', '/api/slicer', '/api/printers', '/api/printer-models', '/api/jobs', '/api/spools', '/api/materials', '/api/files', '/print/spools', '/print/jobs', '/api/sliced', '/api/runs', '/api/quality', '/api/production', '/api/maintenance', '/api/calib']
PATTERNS = [r"^/api/stock(/make)?$", '^/api/products/[^/]+/recipe(/slice)?$']


@bp.post("/api/products/<pid>/recipe")
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


@bp.post("/api/products/<pid>/recipe/slice")
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


@bp.post("/api/sliced/parse")
def sliced_parse():
    f = request.files.get("file")
    if not f:
        return err("请选择切片文件")
    cfg = load_config()
    pid = request.form.get("pid")
    material = request.form.get("material") or "PLA"
    tmp = os.path.join(DATA_DIR, "tmp")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, f"{uuid.uuid4().hex}_{os.path.basename(f.filename or 'x.gcode')}")
    f.save(path)
    try:
        r = slicer.parse_sliced_file(path, material)
    except slicer.SliceError as e:
        return err(str(e))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if pid and r.get("grams"):
        try:
            _learn(cfg, store.load(pid), r["grams"])
        except FileNotFoundError:
            pass
    return jsonify(r)


@bp.get("/api/slicer/info")
def slicer_info():
    cfg = load_config()
    orca, tried = slicer.find_orca(cfg, explain=True)
    if orca and cfg.get("orca_path") != orca:
        save_config({"orca_path": orca})  # 找到了就记住，下次不用再搜
    from core import orca_profiles as op
    presets = {}
    if orca or os.environ.get("APPDATA") or os.environ.get("ORCA_PROFILES_DIR"):
        idx = op.build_index(orca)
        presets = op.summary(idx)
    return jsonify({"orca": orca or "", "tried": tried, "profiles": slicer.find_profiles(), "presets": presets,
                    "calibration": cfg.get("est_calibration"), "calibration_n": cfg.get("est_calibration_n")})


@bp.get("/api/slicer/presets")
def slicer_presets():
    """下拉选项：全部打印机预设；指定 machine 时给出兼容的工艺和耗材。"""
    from core import orca_profiles as op
    cfg = load_config()
    idx = op.build_index(slicer.find_orca(cfg))
    machines = sorted({e["name"] for e in idx["list"]["machine"] if e["inst"]},
                      key=lambda n: (0 if n.startswith(("Bambu Lab", "Creality")) else 1, n))
    m = (request.args.get("machine") or "").strip()
    return jsonify({"machines": machines,
                    "processes": op.processes_for(idx, m) if m else [],
                    "filaments": op.filaments_for(idx, m) if m else []})


@bp.post("/api/slicer/automatch")
def slicer_automatch():
    """按打印机名称自动匹配 OrcaSlicer 打印机/工艺/耗材配置并保存。force=true 时覆盖已填的。"""
    from core import orca_profiles as op
    body = request.get_json(force=True) or {}
    cfg = load_config()
    exe = slicer.find_orca(cfg)
    idx = op.build_index(exe)
    printers = body.get("printers") or cfg.get("printers") or []
    force = bool(body.get("force"))
    out, missing = [], []
    from core import fleet
    for p in printers:
        p = dict(p)
        if fleet.tech_of(p) == "resin":     # 光固化不用 OrcaSlicer
            out.append(p)
            continue
        a = op.auto_match(idx, p.get("name", ""), "PLA")
        for k in ("orca_machine", "orca_process", "orca_filament"):
            cur = (p.get(k) or "").strip()
            if force or not cur or (os.path.sep in cur and not os.path.exists(cur.strip('"'))):
                p[k] = a[k]
        if not p.get("orca_machine"):
            missing.append(p.get("name", ""))
        out.append(p)
    # 只把匹配到的配置写回已保存的同一台打印机（按机器编码）；页面上还没保存的增删由「保存」处理
    saved = cfg.get("printers") or []
    by_code = {p.get("code"): p for p in out if p.get("code")}
    changed = False
    for sp in saved:
        m = by_code.get(sp.get("code"))
        if m:
            for k in ("orca_machine", "orca_process", "orca_filament"):
                if sp.get(k) != m.get(k):
                    sp[k] = m.get(k); changed = True
    if changed:
        save_config({"printers": saved})
    return jsonify({"printers": out, "missing": missing, "orca": exe or "", "presets": op.summary(idx)})


@bp.post("/api/slicer/pick")
def slicer_pick():
    """弹出 Windows 选择文件窗口，让用户手动选 OrcaSlicer 程序。"""
    try:
        p = slicer.pick_exe_dialog()
    except slicer.SliceError as e:
        return err(str(e))
    if not p:
        return err("没有选择文件")
    exe = slicer._from_user_path(p)
    if not exe or not exe.lower().endswith(".exe"):
        return err(f"选择的不是程序文件：{p}")
    save_config({"orca_path": exe})
    slicer._orca_cache["path"] = exe
    return jsonify({"orca": exe})


@bp.post("/api/slicer/test")
def slicer_test():
    body = request.get_json(force=True) or {}
    try:
        return jsonify(slicer.orca_test(load_config(), int(body.get("printer", 0))))
    except slicer.SliceError as e:
        return err(str(e))


@bp.get("/api/production")
def production_board():
    production.generate(_uname())
    b = production.board()
    b["status_zh"] = production.STATUS_ZH
    return jsonify(b)


@bp.post("/api/production/schedule")
def production_schedule():
    return jsonify({"scheduled": production.schedule()})


@bp.post("/api/jobs/<int:jid>")
def job_update(jid):
    b = request.get_json(force=True) or {}
    try:
        j = production.set_status(jid, b.get("status"), _uname(), b.get("printer"), b.get("note"))
    except ValueError as e:
        return err(str(e))
    return jsonify(j)


@bp.get("/api/materials")
def materials_plan():
    return jsonify(materials.plan())


@bp.post("/api/materials")
def materials_update():
    b = request.get_json(force=True) or {}
    if b.get("mode") == "set" and _need("materials.adjust"):
        return _need("materials.adjust")
    try:
        if b.get("mode") == "set":
            materials.set_stock(b.get("material"), b.get("color"), float(b.get("kg")), _uname())
        else:
            materials.add_stock(b.get("material"), b.get("color"), float(b.get("kg")), _uname(), b.get("reason") or "入库")
    except (TypeError, ValueError):
        return err("请填写正确的公斤数")
    return jsonify(materials.plan())


@bp.get("/api/spools")
def spools_list():
    a = request.args
    return jsonify({"items": materials.spools(a.get("material") or "", a.get("color") or "", a.get("status") or "active",
                                              a.get("printer") or ""), "status_zh": materials.SPOOL_ST,
                    "alerts": materials.alerts()})


@bp.post("/api/spools")
def spools_receive():
    """入库 N 卷（未开封）。"""
    b = request.get_json(force=True) or {}
    try:
        codes_ = materials.receive(b.get("material"), (b.get("color") or "").strip(), b.get("count"), b.get("net_g") or 1000,
                                   (b.get("brand") or "").strip()[:40], b.get("price"), _uname())
    except (TypeError, ValueError) as e:
        return err(str(e) or "请填写正确的数量")
    return jsonify({"codes": codes_, "plan": materials.plan()})


@bp.post("/api/spools/<sid>/<act>")
def spool_act(sid, act):
    b = request.get_json(force=True) or {}
    try:
        s = materials.spool_action(sid, act, _uname(), b.get("printer") or "", (b.get("slot") or "").strip()[:10],
                                   b.get("grams"), b.get("brand"), b.get("note"))
    except (TypeError, ValueError) as e:
        return err(str(e) or "数字不对")
    return jsonify({"spool": s})


@bp.get("/print/spools")
def spools_print():
    """料卷标签：贴在料盘上，上机 / 称重时扫码。"""
    from html import escape as h
    from core import labels
    ids = [x for x in (request.args.get("ids") or "").split(",") if x.strip()]
    rows = [materials.spool_get(x) for x in ids]
    rows = [r for r in rows if r]
    fmt = (lambda t: dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d") if t else "")
    css = ("body{font:12px 'Microsoft YaHei','Leelawadee UI',sans-serif;margin:8px}.lb{display:inline-block;width:60mm;height:30mm;"
           "border:1px dashed #999;padding:2mm;margin:1mm;box-sizing:border-box;vertical-align:top;overflow:hidden}"
           ".c{font-size:20px;font-weight:bold}@media print{.noprint{display:none}.lb{border:none;page-break-inside:avoid}}")
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>料卷标签</title><style>{css}</style></head><body>"
           "<p class='noprint'><button onclick='print()'>打印 / พิมพ์</button></p>"]
    for r in rows:
        out.append(f"<div class='lb'><div class='c'>{h(r['code'])}</div><div><b>{h(r['material'])} {h(r['color'])}</b> "
                   f"{h(r.get('brand') or '')} {r['net_g']:.0f}g</div><div>{labels.code128_svg(r['code'], 22, 1)}</div>"
                   f"<div>入库 {fmt(r['created_at'])}</div></div>")
    out.append("</body></html>")
    return app.response_class("".join(out), mimetype="text/html")


@bp.get("/api/materials/log")
def materials_log():
    return jsonify({"items": materials.log()})


@bp.get("/api/printers")
def printers_get():
    runs = {r["printer"]: r for r in production.active_runs()}
    lst = _printer_list()
    maint = {m["index"]: m for m in production.maintenance_status()}
    for p in lst:
        r = runs.get(p["index"])
        p["run"] = {k: r[k] for k in ("id", "sku", "name", "color", "count", "alert", "started_at", "sent")} if r else None
        p["maintenance"] = maint.get(p["index"])
    return jsonify({"printers": lst})


@bp.post("/api/printers/<int:idx>/conn")
def printer_conn_save(idx):
    b = request.get_json(force=True) or {}
    cfg = load_config()
    printers = cfg.get("printers") or []
    if idx >= len(printers):
        return err("打印机不存在")
    old = printers[idx].get("conn") or {}
    c = {"type": b.get("type") or "auto", "host": (b.get("host") or "").strip(), "serial": (b.get("serial") or "").strip(),
         "port": str(b.get("port") or "").strip(), "loaded": (b.get("loaded") or "").strip(),
         "auto_complete": bool(b.get("auto_complete", True)), "detected": old.get("detected", "")}
    code = b.get("access_code")
    c["access_code"] = old.get("access_code", "") if code in (None, "******") else str(code).strip()
    printers[idx]["conn"] = c
    save_config({"printers": printers})
    printers_mod.poll_once(idx, printers[idx])
    return jsonify({"printers": _printer_list()})


@bp.post("/api/printers/<int:idx>/loaded")
def printer_loaded(idx):
    """生产员工填写：这台打印机现在装的是什么颜色（没有料盘读数的打印机用）。"""
    cfg = load_config()
    printers = cfg.get("printers") or []
    if idx >= len(printers):
        return err("打印机不存在")
    c = dict(printers[idx].get("conn") or {})
    c["loaded"] = ((request.get_json(force=True) or {}).get("loaded") or "").strip()
    printers[idx]["conn"] = c
    save_config({"printers": printers})
    production.schedule()
    return jsonify({"ok": True})


def _conn_hint(pr, e):
    """把网络错误翻译成能照着做的检查步骤。"""
    import errno
    import socket
    c = pr.get("conn") or {}
    ip = (c.get("ip") or c.get("host") or "").strip()
    no = getattr(e, "errno", None)
    msg = str(e)
    if not ip:
        return "。还没填 IP：先填好点「保存」，再测试连接"
    head = f"（用的是已保存的 IP {ip}，改了没点「保存」的话先保存）"
    if no in (errno.EHOSTUNREACH, errno.ENETUNREACH) or "No route to host" in msg or "unreachable" in msg.lower():
        return head + (f"。NAS 找不到 {ip} 这台设备，通常是：① 打印机 IP 变了——在打印机屏幕 设置 → 网络 看现在的 IP"
                       "（建议在路由器里给打印机固定 IP）；② 打印机关机 / 休眠 / 没连上 WiFi；③ 打印机连的是访客 WiFi 或另一个路由器，"
                       "或者路由器开了「AP 隔离 / 无线隔离」，有线的 NAS 访问不到无线设备；④ 在电脑上打开命令提示符输入 ping " + ip + " 看通不通，"
                       "电脑也不通就是网络问题，电脑通而 NAS 不通，检查 NAS 的 Docker 网络")
    if no == errno.ECONNREFUSED or "refused" in msg.lower():
        return head + "。设备在，但端口没开：拓竹要在打印机上打开「局域网模式」（新固件还要开「开发者模式」）；Creality 确认连接方式选对"
    if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in msg.lower():
        return head + "。连接超时：打印机可能在休眠或网络很慢，确认打印机开着、和 NAS 在同一个网络，再试一次"
    if "auth" in msg.lower() or "password" in msg.lower() or "not authorized" in msg.lower() or "bad user" in msg.lower():
        return head + "。访问码不对：拓竹的访问码在打印机屏幕 设置 → 网络 / WLAN，每次重新打开局域网模式会变"
    return head


@bp.post("/api/printers/<int:idx>/test")
def printer_test(idx):
    cfg = load_config()
    printers = cfg.get("printers") or []
    if idx >= len(printers):
        return err("打印机不存在")
    try:
        t, st = printers_mod.test(printers[idx])
    except Exception as e:  # 连接错误：原样 + 看得懂的原因（v2.22.1）
        return err(f"连接失败：{e}{_conn_hint(printers[idx], e)}")
    c = dict(printers[idx].get("conn") or {})
    c["detected"] = t
    if c.get("type") in (None, "", "none"):
        c["type"] = "auto"
    printers[idx]["conn"] = c
    save_config({"printers": printers})
    printers_mod.poll_once(idx, printers[idx])
    return jsonify({"type": t, "status": st, "status_zh": printers_mod.STATE_ZH.get(st.get("state"), "")})


@bp.post("/api/printers/<int:idx>/command")
def printer_command(idx):
    cmd = (request.get_json(force=True) or {}).get("cmd")
    if cmd not in ("pause", "resume", "stop"):
        return err("不支持的指令")
    try:
        printers_mod.command(idx, cmd)
    except Exception as e:  # 打印机不在线等
        return err(str(e))
    return jsonify({"ok": True})


@bp.get("/api/printer-models")
def printer_models():
    from core import fleet
    return jsonify({"models": fleet.MODELS})


@bp.get("/api/print-files")
def print_files_list():
    pid = request.args.get("product_id")
    files = print_files.list_files(pid)
    names = {}
    for f in files:
        if f["product_id"] not in names:
            try:
                names[f["product_id"]] = store.load(f["product_id"]).get("name_zh", "")
            except FileNotFoundError:
                names[f["product_id"]] = "（产品已删除）"
        f["product_name"] = names[f["product_id"]]
    prods = [{"id": p["id"], "name": p["name_zh"]} for p in store.list_products()]
    return jsonify({"files": files, "products": prods, "status_zh": print_files.STATUS_ZH,
                    "printers": _model_names()})


@bp.get("/api/print-files/<int:fid>")
def print_file_get(fid):
    f = print_files.ensure_params(print_files.get(fid))
    if not f:
        return err("文件不存在", 404)
    from core import recipes
    pidx = _printer_index(f.get("printer"))
    try:
        f["bed_mm"] = recipes.bed_size(pidx if pidx is not None else 0)
    except Exception:  # noqa: BLE001
        f["bed_mm"] = None
    try:
        f["product_material"] = recipes.norm_material(store.load(f["product_id"]).get("material") or "PLA")
    except FileNotFoundError:
        f["product_material"] = None
    return jsonify(f)


# ---------------- 文件管理（模型 + 切片文件） ----------------
@bp.get("/api/files")
def files_overview():
    from core import filemgr
    a = request.args
    out = filemgr.overview(a.get("q", ""), a.get("kind", ""), a.get("status", ""), a.get("printer", ""))
    out["printers"] = _model_names()
    out["status_zh"] = print_files.STATUS_ZH
    return jsonify(out)


@bp.post("/api/files/models")
def files_models_bulk():
    """批量上传模型：文件名以产品编号开头（3DP0001.stl / 3DP0001_猫.3mf）自动对应。"""
    from core import filemgr
    tmp = os.path.join(DATA_DIR, "tmp")
    os.makedirs(tmp, exist_ok=True)
    target = request.form.get("product_id") or ""
    out = []
    for f in request.files.getlist("files"):
        pid = target or filemgr.match_model_file(f.filename or "")
        if not pid:
            out.append({"file": f.filename, "ok": False, "error": "文件名里没有找到产品编号"})
            continue
        ext = os.path.splitext(f.filename or "")[1].lower()
        path = os.path.join(tmp, uuid.uuid4().hex + ext)
        f.save(path)
        try:
            r = filemgr.set_model(pid, path, f.filename, _uname())
            out.append({"file": f.filename, "ok": True, "product_id": pid, "replaced": r["replaced"], "files_reset": r["files_reset"]})
        except (ValueError, OSError, FileNotFoundError) as e:
            out.append({"file": f.filename, "ok": False, "product_id": pid, "error": str(e)})
        finally:
            if os.path.exists(path):
                os.remove(path)
    return jsonify({"results": out})


@bp.post("/api/print-files/<int:fid>/replace")
def print_file_replace(fid):
    from core import filemgr
    f = request.files.get("file")
    if not f:
        return err("请选择新的切片文件")
    tmp = os.path.join(DATA_DIR, "tmp")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, uuid.uuid4().hex + "_" + os.path.basename(f.filename or "x"))
    f.save(path)
    try:
        r = filemgr.replace_slice(fid, path, f.filename, _uname())
    except (ValueError, FileNotFoundError) as e:
        return err(str(e))
    finally:
        if os.path.exists(path):
            os.remove(path)
    production.schedule()
    return jsonify(r)


@bp.get("/api/files/zip")
def files_zip():
    from core import filemgr
    pids = [x for x in (request.args.get("ids") or "").split(",") if x]
    if not pids:
        return err("请选择产品")
    buf = filemgr.zip_products(pids, request.args.get("all") == "1")
    name = f"3d_files_{time.strftime('%Y%m%d_%H%M')}.zip" if len(pids) > 1 else f"{pids[0]}_files.zip"
    return send_file(buf, as_attachment=True, download_name=name, mimetype="application/zip")


@bp.get("/api/print-files/<int:fid>/toolpath")
def print_file_toolpath(fid):
    """切片预览数据（按层、按类型的挤出路径，gzip）。"""
    from core import toolpath
    f = print_files.get(fid)
    if not f:
        return err("文件不存在", 404)
    if f.get("kind") == "resin":
        return err("光固化文件没有 3D 切片预览，请在 Photon Workshop / Chitubox 里检查")
    try:
        blob = toolpath.build(print_files.path_of(f), f.get("kind") or "3mf", os.path.join(print_files.FILE_DIR, "cache"))
    except (ValueError, OSError, zipfile.BadZipFile) as e:
        return err(f"读不了这个切片文件：{e}")
    resp = app.response_class(blob, mimetype="application/octet-stream")
    resp.headers["Content-Encoding"] = "gzip"
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp


@bp.post("/api/print-files")
def print_files_upload():
    """上传在电脑上切好的文件（可以一次多个）。打印机 / 一盘几个不填就从文件里自动认。
    表单：files（或 file）、product_id（不填就按文件名开头的产品编号对应）、printer（auto）、per_plate（auto）、sku、color、note"""
    from core import filemgr
    fm = request.form
    files = request.files.getlist("files") or ([request.files["file"]] if request.files.get("file") else [])
    if not files:
        return err("请选择切片文件")
    tmp = os.path.join(DATA_DIR, "tmp")
    os.makedirs(tmp, exist_ok=True)
    results = []
    for f in files:
        pid = fm.get("product_id") or filemgr.match_model_file(f.filename or "")
        if not pid:
            results.append({"file": f.filename, "ok": False, "error": "文件名里没有找到产品编号（文件名要以产品编号开头，例如 3DP0001_xxx.gcode.3mf）"})
            continue
        path = os.path.join(tmp, uuid.uuid4().hex + "_" + os.path.basename(f.filename or "x"))
        f.save(path)
        try:
            r = filemgr.upload_slice(path, f.filename, pid, _uname(), fm.get("printer") or "auto", fm.get("per_plate") or "auto",
                                     fm.get("sku") or "", fm.get("color") or "", fm.get("note") or "",
                                     hours=fm.get("hours"), ml=fm.get("ml"), spec=fm.get("spec"))
            results.append({"file": f.filename, "ok": True, "product_id": pid, "id": r["id"], "printer": r["printer"],
                            "per_plate": r["per_plate"], "version": r.get("version"), "detected": r.get("detected"),
                            "kind": r.get("kind"), "hours": r.get("hours"), "grams": r.get("grams"),
                            "material": ((r.get("report") or {}).get("params") or {}).get("material")})
        except (ValueError, FileNotFoundError) as e:
            results.append({"file": f.filename, "ok": False, "product_id": pid, "error": str(e)})
        finally:
            if os.path.exists(path):
                os.remove(path)
    production.schedule()
    out = {"results": results}
    if len(results) == 1 and results[0]["ok"]:       # 兼容以前的单文件上传
        out.update(print_files.get(results[0]["id"]) or {})
        out["detected"] = results[0]["detected"]
    elif len(results) == 1:
        return err(results[0]["error"])
    return jsonify(out)


@bp.post("/api/print-files/<int:fid>/ai-review")
def print_file_ai(fid):
    from core import recipes
    f = print_files.get(fid)
    if not f:
        return err("文件不存在", 404)
    p = store.load(f["product_id"])
    r = f.get("recipe") or recipes.get(p)
    geo = None
    try:
        idx = _printer_index(f["printer"])
        geo = recipes.geometry(p, r, idx if idx is not None else 0) if p.get("model") else None
    except Exception:  # 没有模型
        geo = None
    try:
        ai = recipes.ai_review(load_config(), p, r, geo, f.get("report"))
    except ai_copy.AIError as e:
        return err(str(e))
    return jsonify(print_files.set_checks(fid, ai=ai))


@bp.post("/api/print-files/<int:fid>/review")
def print_file_review(fid):
    b = request.get_json(force=True) or {}
    try:
        f = print_files.review(fid, b.get("items") or {}, _uname(), b.get("note") or "")
    except ValueError as e:
        return err(str(e))
    production.schedule()
    return jsonify(f)


@bp.post("/api/print-files/<int:fid>/verify")
def print_file_verify(fid):
    fm = request.form if request.files else (request.get_json(force=True, silent=True) or {})
    photo = None
    ph = request.files.get("photo")
    if ph:
        d = os.path.join(print_files.FILE_DIR, "photos")
        os.makedirs(d, exist_ok=True)
        photo = f"{fid}_{int(time.time())}.jpg"
        ph.save(os.path.join(d, photo))
    num = (lambda v: float(v) if v not in (None, "") else None)
    try:
        f = print_files.verify(fid, str(fm.get("ok")) in ("1", "true", "True"), _uname(), num(fm.get("actual_grams")),
                               num(fm.get("actual_hours")), fm.get("note") or "", photo)
    except ValueError as e:
        return err(str(e))
    return jsonify(f)


@bp.get("/api/print-files/photo/<name>")
def print_file_photo(name):
    return send_from_directory(os.path.join(print_files.FILE_DIR, "photos"), os.path.basename(name))


@bp.post("/api/print-files/<int:fid>")
def print_files_update(fid):
    r = print_files.update(fid, **(request.get_json(force=True) or {}))
    production.schedule()
    return jsonify(r)


@bp.delete("/api/print-files/<int:fid>")
def print_files_delete(fid):
    print_files.delete(fid)
    production.schedule()
    return jsonify({"ok": True})


@bp.get("/api/print-files/<int:fid>/download")
def print_files_download(fid):
    f = print_files.get(fid)
    if not f:
        abort(404)
    return send_file(print_files.path_of(f), as_attachment=True, download_name=f["filename"])


# ---- 打印批次 ----
@bp.get("/api/jobs/<int:jid>/send-options")
def job_send_options(jid):
    try:
        return jsonify(production.send_options(jid, request.args.get("printer")))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/jobs/<int:jid>/start")
def job_start(jid):
    b = request.get_json(force=True) or {}
    try:
        r = production.start_run(jid, b.get("printer"), b.get("count"), b.get("merge_ids") or [], b.get("file_id"),
                                 bool(b.get("send", True)), _uname(), b.get("confirm") or {}, b.get("tray"),
                                 bool(b.get("force_color")))
    except (ValueError, ConnectionError, OSError, slicer.SliceError) as e:
        return err(str(e))
    if r.get("file"):
        r["note"] = ((r["file"].get("report") or {}).get("note")) or ""
    r["file"] = {k: (r["file"] or {}).get(k) for k in ("id", "filename", "status")} if r.get("file") else None
    return jsonify(r)


@bp.post("/api/runs/<int:rid>/<action>")
def run_action(rid, action):
    b = request.get_json(force=True, silent=True) or {}
    try:
        if action == "done":
            production.finish_run(rid, _uname())
        elif action == "fail":
            production.fail_run(rid, b.get("reason") or "", b.get("note") or "", _uname())
        elif action == "cancel":
            production.cancel_run(rid, _uname())
        else:
            return err("不支持的操作")
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True})


@bp.post("/api/jobs/<int:jid>/use-stock")
def job_use_stock(jid):
    try:
        return jsonify(production.use_stock(jid, (request.get_json(force=True) or {}).get("n"), _uname()))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/stock")
def stock_post():
    b = request.get_json(force=True) or {}
    if not b.get("sku"):
        return err("请填写 SKU")
    production.stock_set(b["sku"], b.get("qty"), b.get("target"), _uname())
    return stock_get()


@bp.post("/api/stock/make")
def stock_make():
    """人工确认后生成备货任务（排在订单任务后面）。"""
    b = request.get_json(force=True) or {}
    from core import orders as om
    hit = om.match_sku(b.get("sku"), om.sku_index())
    if not hit:
        return err("产品库里找不到这个 SKU")
    try:
        j = production.create_job(hit[0], b["sku"], int(b.get("qty") or 1), "stock", None, _uname(), "备货")
    except (ValueError, FileNotFoundError) as e:
        return err(str(e))
    return jsonify(j)


@bp.get("/api/quality")
def quality_get():
    from core import extras
    q = production.quality(int(request.args.get("days") or 30))
    q["aftersales"] = extras.as_stats(int(request.args.get("days") or 30))
    return jsonify(q)


@bp.post("/api/maintenance")
def maintenance_post():
    b = request.get_json(force=True) or {}
    parts = [p for p in (b.get("parts") or []) if isinstance(p, dict) and p.get("item_id") and p.get("qty")]
    if parts and _need("inv.out"):
        return _need("inv.out")
    try:
        production.maintenance_done(int(b.get("printer") or 0), b.get("item"), _uname(), b.get("note") or "", parts)
    except ValueError as e:
        return err(str(e))
    return maintenance_get()


@bp.post("/api/materials/flag")
def materials_flag():
    b = request.get_json(force=True) or {}
    materials.flag(b.get("material"), b.get("color"), b.get("action"), _uname())
    return jsonify(materials.plan())


@bp.get("/print/jobs")
def jobs_print():
    """生产工单贴纸（60×40mm）：贴在成品袋上，打包时扫码核对。"""
    from html import escape as h
    from core import labels
    ids = [int(x) for x in (request.args.get("ids") or "").split(",") if x.strip().isdigit()]
    jobs = [j for j in production.list_jobs() if j["id"] in ids]
    cmap = codes.color_hex(load_config())
    css = ("@page{size:60mm 40mm;margin:0}*{box-sizing:border-box}body{margin:0;font:10px 'Leelawadee UI',Tahoma,'Microsoft YaHei',sans-serif}"
           ".t{width:60mm;height:40mm;padding:2mm;page-break-after:always;overflow:hidden;display:flex;flex-direction:column;gap:.6mm}"
           ".sku{font-size:15px;font-weight:800}.big{font-size:12px;font-weight:700}.n{border:1px dashed #000;padding:.6mm;font-weight:700}"
           ".row{display:flex;justify-content:space-between;align-items:center}"
           "@media screen{body{background:#ddd}.t{background:#fff;margin:6px auto}}@media print{.np{display:none}}")
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>工单</title><style>{css}</style></head><body>"
           "<p class='np' style='text-align:center'><button onclick='print()'>打印 / พิมพ์</button> 60×40mm</p>"]
    for j in jobs:
        th = (cmap.get(j["color"] or "") or {}).get("th", "")
        out.append(f"""<div class="t"><div class="row"><span class="sku">{h(j['sku'] or '')}</span><span class="big">× {j['qty']}</span></div>
<div class="big">{h(j['color'] or '')} {h(th)}</div><div>{h((j['name'] or '')[:40])}</div>
<div>{labels.code128_svg(j['sku'] or '', 26, 1)}</div>
<div class="row"><span>{h(j.get('order_no') or ('备货' if j.get('kind') == 'stock' else ''))}</span><span><b>{h(j.get('printer_code') or '')}</b> #{j['id']}</span></div>
{f'<div class="n">{h(j["custom_note"][:60])}</div>' if j.get('custom_note') else ''}</div>""")
    out.append("</body></html>")
    return app.response_class("".join(out), mimetype="text/html")


# ---- 用真实数据校准（v2.15）：估算克数 / 打印速度 / 空打阈值 ----
@bp.get("/api/calib")
def calib_report():
    from core import calib
    return jsonify(calib.report())


@bp.post("/api/calib/apply")
def calib_apply():
    from core import calib
    b = request.get_json(force=True) or {}
    try:
        return jsonify(calib.apply(b.get("kind"), b.get("data"), _uname()))
    except (ValueError, TypeError) as e:
        return err(str(e))


@bp.get("/api/products/<pid>/recipe")
def recipe_get(pid):
    """打印方案 + 各方向几何分析 + 每台打印机一盘能放几个 + 这个产品的切片文件。"""
    from core import mesh, recipes, specmodel
    try:
        p0 = store.load(pid)
    except FileNotFoundError:
        return err("产品不存在", 404)
    # v2.22：?spec= 看某个规格（规格有自己的模型时，模型、方案、切片文件都是这个规格的）
    spec = request.args.get("spec") or ""
    p = specmodel.view(p0, spec)
    r = recipes.get(p)
    out = {"recipe": r, "summary_zh": recipes.summary_zh(r), "has_model": bool(p.get("model")),
           "orient_zh": mesh.ORIENT_ZH, "support_zh": recipes.SUPPORT_ZH, "bed_types": recipes.BED_TYPES,
           "printers": _model_names(), "printer_idx": _model_first_idx(),
           "files": print_files.list_files(pid), "status_zh": print_files.STATUS_ZH,
           "review_items": print_files.REVIEW_ITEMS, "material": recipes.norm_material(p.get("material") or "PLA"),
           "materials": recipes.MATERIALS, "temp_range": recipes.TEMP_RANGE,
           "advice": {k: (p.get("print_advice") or {}).get(k) for k in ("risks", "temp_speed", "support_why", "orientation")}
           if p.get("print_advice") else None}
    out["files"] = [print_files.ensure_params(f) for f in out["files"]]
    out["spec"] = p.get("_spec") or ""
    out["spec_asked"] = spec
    out["specs"] = [{"spec": s_, "own": specmodel.own(p0, s_)} for s_ in specmodel.specs(p0)]
    if any(x["own"] for x in out["specs"]):
        out["files"] = [f for f in out["files"] if (f.get("spec") or "") == out["spec"]]
    from core import filemgr
    mp = specmodel.model_path(p) if p.get("_spec") else filemgr.model_path(p)
    out["model"] = ({k: p["model"].get(k) for k in ("file", "orig_name", "uploaded_at", "uploaded_by", "metrics", "ext", "parts_of")}
                    | {"size": os.path.getsize(mp), "history": len(filemgr.model_history(pid)), "spec_model": bool(p.get("_spec"))}) if mp else None
    out["setup"] = []
    for i in out["printer_idx"]:      # 同机型只算一次
        st = recipes.setup_info(p, r, i)
        out["setup"].append(st)
        if "OrcaSlicer" in str(st.get("error") or ""):      # 没装切片软件：不用每台都找一遍
            out["setup"] += [st] * (len(out["printers"]) - i - 1)
            break
    if p.get("model"):
        try:
            tris = mesh.load(specmodel.model_path(p))
            out["orientations"] = mesh.analyze_all(tris)
            out["per_printer"] = []
            for i in out["printer_idx"]:
                g = recipes.geometry(p, r, i)
                out["per_printer"].append({"index": i, "capacity": g.get("capacity"), "bed_mm": g.get("bed_mm")})
            g0 = recipes.geometry(p, r, 0)
            out["geometry"] = g0
            out["checks"] = recipes.check(r, g0, None, p.get("material") or "PLA")
        except Exception as e:  # 模型读不了
            out["model_error"] = str(e)
    return jsonify(out)


@bp.get("/api/stock")
def stock_get():
    return jsonify({"items": production.stock_list(), "suggest": production.stock_suggest()})


@bp.get("/api/maintenance")
def maintenance_get():
    return jsonify({"printers": production.maintenance_status()})
