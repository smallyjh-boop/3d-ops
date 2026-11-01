"""生产模块的接口：排单、打印机、切片文件、打印方案、耗材料卷、成品备货、质量、保养、打印单据。
v2.31 从 web/production.py 搬过来。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403
from core import trial

bp = Blueprint("m_prod", __name__)
PREFIXES = ['/api/fleet', '/print/fleet-labels', '/api/print-files', '/api/trial', '/api/slicer', '/api/printers', '/api/printer-models', '/api/jobs', '/api/spools', '/api/materials', '/api/files', '/print/spools', '/print/jobs', '/api/sliced', '/api/runs', '/api/quality', '/api/production', '/api/maintenance', '/api/calib', '/api/porders', '/print/po']
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
        p0 = store.load(pid)
        if specmodel.plan_sliced(p0, b.get("spec") or ""):
            # v2.53.1：按主模型缩放 / 只有自己打印方案的规格不能按主模型切（会切出主模型大小的文件）
            raise ValueError(f"{specmodel.spec_name(b.get('spec'))}要在产品的「打印方案」里按它自己的方案切片")
        p = specmodel.view(p0, b.get("spec") or "")     # 规格有自己的模型时切那个模型（v2.22）
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
    items = materials.spools(a.get("material") or "", a.get("color") or "", a.get("status") or "active", a.get("printer") or "")
    # v2.41.1：生产角色看不到料卷价格（strip_prices 对生产角色去掉 price）
    return jsonify({"items": auth.strip_prices(items, auth.current_user() or {"role": "production"}), "status_zh": materials.SPOOL_ST,
                    "alerts": materials.alerts()})


@bp.post("/api/spools")
def spools_receive():
    """入库 N 卷（未开封）。"""
    b = request.get_json(force=True) or {}
    try:
        codes_ = materials.receive(b.get("material"), (b.get("color") or "").strip(), b.get("count"), b.get("net_g") or 1000,
                                   (b.get("brand") or "").strip()[:40], b.get("price") if (auth.current_user() or {}).get("role") != "production" else None, _uname())
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
    return jsonify({"spool": auth.strip_prices(s, auth.current_user() or {"role": "production"})})


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
    where, qr = {}, None
    try:                          # v2.53：标签带二维码（手机扫码上架 / 上机）和放在哪个货位（仓库模块开着时）
        from core import modules
        m = modules.public("inv")
        if m is not None and hasattr(m, "spool_locs"):
            where = m.spool_locs()
            from modules.inv import qr
    except Exception:  # noqa: BLE001
        where = {}
    for r in rows:
        lc = (where.get(r["id"]) or {}).get("code") or ""
        q = f"<div style='float:right;width:18mm;height:18mm'>{qr.svg(r['code'], 18)}</div>" if qr else ""
        out.append(f"<div class='lb'>{q}<div class='c'>{h(r['code'])}</div><div><b>{h(r['material'])} {h(r['color'])}</b> "
                   f"{h(r.get('brand') or '')} {r['net_g']:.0f}g</div><div>{labels.code128_svg(r['code'], 22, 1)}</div>"
                   f"<div>入库 {fmt(r['created_at'])}{(' · 📍 ' + h(lc)) if lc else ''}</div></div>")
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


PRINTER_MOVED = "打印机列表已经变了（有打印机被添加、移除或调整了顺序），为了不发错打印机，这次没有执行。请刷新页面后再操作"


def _same_printer(idx, b=None):
    """v2.54 复审：页面按序号发指令时带上这台打印机的稳定 id（printer_id）。打开页面以后打印机列表改过
    （删了 / 加了 / 调了顺序），序号对应的已经是别的打印机 → 拒绝，不发错打印机。没带 id 的旧调用照旧按序号。"""
    pid = (b or {}).get("printer_id") or request.args.get("printer_id")
    if not pid:
        return None
    prs = load_config().get("printers") or []
    if idx is None or not (0 <= int(idx) < len(prs)) or prs[int(idx)].get("id") != str(pid):
        return err(PRINTER_MOVED, 409)
    return None


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
    deny = _same_printer(idx, request.get_json(force=True, silent=True))
    if deny:
        return deny
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


@bp.post("/api/printers/<int:idx>/netdiag")
def printer_netdiag(idx):
    """v2.53.0：网络诊断。端口结果和结论所有人可见；服务器网卡 / 路由 / ARP 只有老板能看。"""
    from core import netdiag
    deny = _same_printer(idx, request.get_json(force=True, silent=True))
    if deny:
        return deny
    cfg = load_config()
    printers = cfg.get("printers") or []
    if idx >= len(printers):
        return err("打印机不存在")
    c = printers[idx].get("conn") or {}
    ip = (c.get("host") or c.get("ip") or "").strip()
    if not ip:
        return err("还没填 IP：先填好点「保存」，再做网络诊断")
    ctype = c.get("type") or "auto"
    if ctype == "auto":
        ctype = c.get("detected") or "auto"
    owner = auth.is_owner()
    r = netdiag.diagnose(ip, ctype, with_net=owner)
    ok_ports = [p["port"] for p in r["ports"] if p["kind"] == "ok"]
    if 8883 in ok_ports and c.get("serial") and c.get("access_code"):  # 拓竹：顺便试一次登录
        mqtt = "ok"
        try:
            printers_mod.test(printers[idx])
        except Exception as e:
            m = str(e)
            mqtt = "nostatus" if "序列号" in m else ("auth" if ("访问码" in m or "授权" in m) else None)
        r["conclusions"] = netdiag.conclusions(ctype, r["ports"], r["net"], ip, mqtt)
    return jsonify(r)


@bp.post("/api/printers/<int:idx>/command")
def printer_command(idx):
    b = request.get_json(force=True) or {}
    cmd = b.get("cmd")
    if cmd not in ("pause", "resume", "stop"):
        return err("不支持的指令")
    deny = _same_printer(idx, b)
    if deny:
        return deny
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


@bp.post("/api/print-files/<int:fid>/confirm-printer")
def print_file_confirm_printer(fid):
    """v2.32：文件里读不出机型时，老板确认这个文件是给哪台机型的（只能确认一次，文件里有机型的不能改）。"""
    from modules.prod import slicecheck
    try:
        f = slicecheck.confirm(fid, (request.get_json(force=True) or {}).get("printer") or "", _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True, "file": f, "machine": slicecheck.describe(f)})


@bp.get("/api/print-files/<int:fid>/check")
def print_file_check(fid):
    """v2.32：这个切片文件能不能发到某台打印机（?printer=序号）。"""
    from modules.prod import slicecheck
    f = print_files.get(fid)
    if not f:
        return err("文件不存在", 404)
    try:
        idx = int(request.args.get("printer"))
    except (TypeError, ValueError):
        idx = None
    return jsonify(slicecheck.check(print_files.ensure_params(f), idx))


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
        return jsonify(production.send_options(jid, request.args.get("printer"), request.args.get("plate") or None))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/jobs/<int:jid>/start")
def job_start(jid):
    b = request.get_json(force=True) or {}
    try:
        r = production.start_run(jid, b.get("printer"), b.get("count"), b.get("merge_ids") or [], b.get("file_id"),
                                 bool(b.get("send", True)), _uname(), b.get("confirm") or {}, b.get("tray"),
                                 bool(b.get("force_color")), b.get("plate") or None)
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


@bp.post("/api/jobs/<int:jid>/use-part")
def job_use_part(jid):
    """v2.54.1：用零件库里的一条零件代替这个任务的一盘。"""
    b = request.get_json(force=True) or {}
    try:
        return jsonify(production.use_part(jid, int(b.get("part_id") or 0), b.get("sets"), _uname()))
    except (ValueError, TypeError) as e:
        return err(str(e))


@bp.post("/api/jobs/bulk")
def jobs_bulk():
    """v2.43：订单页批量处理这些订单的生产任务。action：
    use_stock 还没开始打的任务用成品库存发（能用多少用多少）/ printed 还没开始打的标「已打好」（扣耗材）/ packed 打好的标「已打包」。"""
    b = request.get_json(force=True) or {}
    act, oids = b.get("action"), [int(x) for x in b.get("order_ids") or []]
    if act not in ("use_stock", "printed", "packed"):
        return err("不支持的操作")
    done, skipped = 0, []
    for oid in oids:
        for j in production.list_jobs(order_id=oid):
            tag = f"{j.get('order_no') or oid} · {j['sku']}"
            try:
                if act == "use_stock":
                    if j["status"] != "todo" or j.get("run_id") or j["remaining"] <= 0:
                        continue
                    production.use_stock(j["id"], j["remaining"], _uname())
                elif act == "printed":
                    if j["status"] != "todo" or j.get("run_id"):
                        continue
                    production.set_status(j["id"], "post", _uname())
                else:
                    if j["status"] != "post":
                        continue
                    production.set_status(j["id"], "packed", _uname())
                done += 1
            except ValueError as e:
                skipped.append(f"{tag}：{e}")
    return jsonify({"done": done, "skipped": skipped})


@bp.post("/api/stock")
def stock_post():
    b = request.get_json(force=True) or {}
    if not b.get("sku"):
        return err("请填写 SKU")
    production.stock_set(b["sku"], b.get("qty"), b.get("target"), _uname())
    return stock_get()


@bp.delete("/api/jobs/<int:jid>")
def job_delete(jid):
    """v2.41：删除还没开始打的备货任务（以前生成了就删不掉，只能标完成）。"""
    try:
        production.delete_stock_job(jid, _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True})


@bp.post("/api/stock/make")
def stock_make():
    """人工确认后生成备货任务（排在订单任务后面）。v2.53：可以带 priority（1 加急）、printer（指定打印机）、source（从哪个入口来的）。"""
    b = request.get_json(force=True) or {}
    deny = _need_producer()
    if deny:
        return deny
    try:
        r = trial.create_stock([{"sku": b.get("sku"), "qty": b.get("qty") or 1}], b.get("priority") or 0, b.get("printer"), _uname(),
                               b.get("source") or "")
    except (ValueError, FileNotFoundError) as e:
        return err(str(e))
    return jsonify(r["jobs"][0])


def _need_producer():
    """v2.53：备货 / 试打 / 测试任务只有老板和生产角色能建。"""
    if not trial.can_produce(auth.current_user()):
        return err("没有权限：只有老板和生产人员可以建生产 / 试打任务", 403)
    return None


@bp.post("/api/jobs/stock")
def jobs_stock():
    """「➕ 生产」：一次给好几个 SKU 建备货任务。{items: [{sku, qty}], priority, printer, source}。"""
    deny = _need_producer()
    if deny:
        return deny
    b = request.get_json(force=True) or {}
    try:
        return jsonify(trial.create_stock(b.get("items") or [], b.get("priority") or 0, b.get("printer"), _uname(), b.get("source") or ""))
    except (ValueError, FileNotFoundError) as e:
        return err(str(e))


@bp.get("/api/trial/skus")
def trial_skus():
    """「➕ 生产」对话框：这几个产品的 SKU（规格 / 颜色 / 现有库存）。pids=A,B"""
    from core import store
    out = []
    for pid in [x for x in (request.args.get("pids") or "").split(",") if x]:
        try:
            p = store.load(pid)
        except (FileNotFoundError, ValueError):
            continue
        for v in p.get("variants") or []:
            if v.get("sku"):
                out.append({"pid": pid, "name": p.get("name_zh") or "", "sku": v["sku"], "spec": (v.get("opt2_zh") or "").strip(),
                            "colour": (v.get("opt1_zh") or "").strip(), "stock": production.stock_qty(v["sku"])})
    return jsonify({"skus": out, "printers": [{"index": i, "label": (p.get("code") or f"#{i + 1}") + " " + (p.get("name") or "")}
                                              for i, p in enumerate(load_config().get("printers") or []) if p.get("enabled", True) is not False]})


@bp.get("/api/trial/printers")
def trial_printers():
    try:
        return jsonify(trial.printer_options(request.args.get("pid") or "", request.args.get("spec") or "", request.args.get("plate") or "",
                                             request.args.get("sku") or ""))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/trial")
def trial_create():
    """「🧪 试打」：{product_id, sku, spec, plate_id, printer, file_id, source, all_plates, only_unverified}。
    没有切片文件就现在切（慢，浏览器带 ?async=1 放后台）。几盘的产品不指定盘 → 每一盘一个试打任务。"""
    deny = _need_producer()
    if deny:
        return deny
    b = request.get_json(force=True) or {}
    user = _uname()

    def go():
        from core import slicer
        try:
            if b.get("all_plates") or (not b.get("plate_id") and b.get("only_unverified")):
                return jsonify(trial.create_trials(b.get("product_id") or "", b.get("sku") or "", b.get("spec"), b.get("plate_id") or "",
                                                   b.get("printer"), user, b.get("source") or "", bool(b.get("only_unverified"))))
            return jsonify(trial.create_trial(b.get("product_id") or "", b.get("sku") or "", b.get("spec"), b.get("plate_id") or "",
                                              b.get("printer"), b.get("file_id"), user, b.get("source") or ""))
        except (ValueError, FileNotFoundError, OSError, slicer.SliceError) as e:
            return err(str(e))
    return maybe_async("试打任务 " + str(b.get("product_id") or ""), go, "slice", b.get("product_id") or "")


@bp.post("/api/trial/check-file")
def trial_check_file():
    """「🔍 检查切片文件」（不打印）。{product_id, spec, plate_id, printer, file_id, slice}"""
    deny = _need_producer()
    if deny:
        return deny
    b = request.get_json(force=True) or {}
    user = _uname()

    def go():
        from core import slicer
        try:
            return jsonify(trial.check_file(b.get("product_id") or "", b.get("spec"), b.get("plate_id") or "", b.get("printer"),
                                            b.get("file_id"), b.get("sku") or "", user, b.get("slice", True) is not False))
        except (ValueError, FileNotFoundError, OSError, slicer.SliceError) as e:
            return err(str(e))
    return maybe_async("检查切片文件 " + str(b.get("product_id") or ""), go, "slice", b.get("product_id") or "")


@bp.get("/api/trial/pending")
def trial_pending():
    return jsonify({"rows": trial.pending()})


@bp.get("/api/trial/history")
def trial_history():
    return jsonify(trial.history(request.args.get("pid") or ""))


@bp.get("/api/trial/stats")
def trial_stats():
    return jsonify(trial.stats_for([x for x in (request.args.get("pids") or "").split(",") if x]))


@bp.get("/api/trial/job/<int:jid>")
def trial_job(jid):
    try:
        return jsonify(trial.job_info(jid))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/trial/job/<int:jid>/result")
def trial_result(jid):
    """试打结果（电脑 / 手机 /m 共用）：multipart（可带 photo 照片，可多张）或 json。"""
    deny = _need_producer()
    if deny:
        return deny
    if request.files:
        fm = request.form
        issues = fm.getlist("issues") or [x for x in (fm.get("issues") or "").split(",") if x]
        photos = [trial.save_photo(jid, f) for f in request.files.getlist("photo") if f and f.filename]
    else:
        fm = request.get_json(force=True, silent=True) or {}
        issues, photos = fm.get("issues") or [], []
    try:
        return jsonify(trial.submit_result(jid, str(fm.get("ok")) in ("1", "true", "True"), issues, fm.get("note") or "", fm.get("grams"),
                                           fm.get("hours"), fm.get("dest") or "", photos, _uname()))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/trial/<int:tid>/retry")
def trial_retry(tid):
    deny = _need_producer()
    if deny:
        return deny
    b = request.get_json(force=True, silent=True) or {}

    def go():
        from core import slicer
        try:
            return jsonify(trial.retry(tid, _uname(), b.get("printer")))
        except (ValueError, FileNotFoundError, OSError, slicer.SliceError) as e:
            return err(str(e))
    return maybe_async("再试一次", go, "slice", "")


@bp.post("/api/printers/<int:idx>/print-test")
def printer_print_test(idx):
    """设置 → 生产 → 打印机连接 →「🧪 打印测试」：给这台机型切 20 mm 立方体，走正常开始打印（kind=test）。"""
    deny = _need_producer()
    if deny:
        return deny
    b = request.get_json(force=True, silent=True) or {}
    deny = _same_printer(idx, b)
    if deny:
        return deny
    user = _uname()

    def go():
        from core import slicer
        try:
            return jsonify(trial.printer_test(idx, user, b.get("confirm") or {}))
        except (ValueError, ConnectionError, OSError, slicer.SliceError) as e:
            return err(str(e))
    return maybe_async("打印测试", go, "slice", "")


@bp.get("/api/quality")
def quality_get():
    from core import extras
    q = production.quality(int(request.args.get("days") or 30))
    q["aftersales"] = extras.as_stats(int(request.args.get("days") or 30))
    return jsonify(q)


@bp.post("/api/maintenance")
def maintenance_post():
    b = request.get_json(force=True) or {}
    deny = _same_printer(int(b.get("printer") or 0), b)
    if deny:
        return deny
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
{f'<div class="n">共 {int(j["multi_plate"])} 盘，凑齐一套再装袋 · ครบ {int(j["multi_plate"])} เพลทแล้วค่อยแพ็ค</div>' if int(j.get('multi_plate') or 0) > 1 else ''}
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
    from modules.prod import slicecheck
    _cfg = load_config()
    for f in out["files"]:
        f["machine"] = slicecheck.describe(f, _cfg)        # v2.32：这个文件是哪个机型的、能发到哪几台
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
    items = production.stock_list()
    for it in items:                       # v2.35：订单「用库存发」占住的（发货出库时才扣）
        it["reserved"] = production.reserved(it["sku"])
    return jsonify({"items": items, "suggest": production.stock_suggest()})


@bp.get("/api/maintenance")
def maintenance_get():
    return jsonify({"printers": production.maintenance_status()})


# ---------------- 生产单（v2.54） ----------------
@bp.get("/api/porders")
def po_list():
    from core import po
    return jsonify({"orders": po.listing(request.args.get("status") or "", (request.args.get("q") or "").strip()), "counts": po.counts()})


@bp.get("/api/porders/suggest")
def po_suggest():
    """v2.55 建议生产清单（和成品备货的一键补货同一套计算，只含自产）。"""
    from core import po
    return jsonify(po.suggest())


@bp.get("/api/porders/picker")
def po_picker():
    """v2.55 新建生产单：全部产品（按近 30 天销量排）。"""
    from core import po
    return jsonify(po.picker())


@bp.get("/api/porders/<int:pid>")
def po_get(pid):
    from core import po
    try:
        return jsonify(po.get(pid))
    except ValueError as e:
        return err(str(e), 404)


@bp.post("/api/porders")
def po_create():
    """建生产单。{lines: [{sku, qty}], source, priority, due, note, printers: [编号或序号], release: true 马上下达}"""
    from core import po
    deny = _need_producer()
    if deny:
        return deny
    b = request.get_json(force=True) or {}
    try:
        return jsonify(po.create(b.get("lines") or [], b.get("source") or "manual", _uname(), b.get("priority") or 0, b.get("due"),
                                 b.get("note") or "", b.get("printers"), bool(b.get("release"))))
    except (ValueError, FileNotFoundError) as e:
        return err(str(e))


@bp.post("/api/porders/from-orders")
def po_from_orders():
    """订单汇总：今天所有还没开始的订单任务归到一张生产单（scope=all 是所有没开始的）。"""
    from core import po
    deny = _need_producer()
    if deny:
        return deny
    b = request.get_json(silent=True) or {}
    try:
        return jsonify(po.from_orders(_uname(), b.get("scope") or "today", b.get("priority") or 0, b.get("note") or ""))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/porders/<int:pid>")
def po_update(pid):
    from core import po
    deny = _need_producer()
    if deny:
        return deny
    try:
        return jsonify(po.update(pid, request.get_json(force=True) or {}, _uname()))
    except (ValueError, FileNotFoundError) as e:
        return err(str(e))


@bp.post("/api/porders/<int:pid>/<act>")
def po_act(pid, act):
    from core import po
    deny = _need_producer()
    if deny:
        return deny
    u = _uname()
    try:
        if act == "release":
            return jsonify(po.release_po(pid, u))
        if act == "pause":
            return jsonify(po.pause(pid, True, u))
        if act == "resume":
            return jsonify(po.pause(pid, False, u))
        if act == "cancel":
            return jsonify(po.cancel(pid, u))
    except (ValueError, FileNotFoundError) as e:
        return err(str(e))
    return err("没有这个操作", 404)


@bp.get("/print/po/<int:pid>")
def po_sheet(pid):
    """可打印的生产单（A4，带单号二维码）。?lang=th 泰文。"""
    from core import po
    try:
        html = po.sheet_html(pid, "th" if request.args.get("lang") == "th" else "zh")
    except ValueError as e:
        return err(str(e), 404)
    return app.response_class(html, mimetype="text/html")


from . import fleet_api  # noqa: E402,F401  v2.54 打印机机群（同一个 bp）
