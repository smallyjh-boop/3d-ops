"""首页、登录、账号、设置、备份、系统检查与升级、运行日志。"""
from web.common import *  # noqa: F401,F403
from core import chain

@app.get("/")
def index():
    """页面里的 js/css 加上版本号，升级后浏览器不会用旧缓存。"""
    with open(os.path.join(BASE_DIR, "static", "index.html"), encoding="utf-8") as f:
        html = f.read()
    html = re.sub(r'(/static/(?!vendor)[\w./-]+\.(?:js|css))"', rf'\1?v={VERSION}"', html)
    from core import i18n_admin
    import json as _json
    from core import modules
    mi = _json.dumps(modules.i18n_th(), ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("</head>", f'<script>window.CLIENT_VERSION="{VERSION}";window.I18N_MODULES={mi};</script>{i18n_admin.script_tag()}</head>', 1)
    # v2.31：主链路模块的页面直接放进首页（和以前一样一打开就在），js 按原来的顺序加载
    panels, js, css = modules.inline_parts()
    html = html.replace("</head>", "".join(f'<link rel="stylesheet" href="/m/{m}/{n}?v={VERSION}">' for m, n in css) + "</head>", 1)
    html = html.replace("<!--MODULE_PANELS-->", panels, 1)
    html = html.replace("<!--MODULE_SCRIPTS-->", "\n".join(
        f'<script src="/m/{mid}/{n}?v={VERSION}-{(modules.get(mid)["meta"].get("version") or "")}"></script>' for mid, n in js), 1)
    r = app.response_class(html, mimetype="text/html")
    r.headers["Cache-Control"] = "no-store"
    return r


def _nozzle(v):
    try:
        x = float(v)
        return x if 0.1 <= x <= 2 else 0.4
    except (TypeError, ValueError):
        return 0.4


# ---------------- 设置 ----------------
@app.get("/api/config")
def get_config():
    cfg = load_config()
    u = auth.current_user()
    out = {"config": auth.strip_config(cfg, u), "rembg": images.rembg_available(), "version": VERSION,
           "docker": os.environ.get("LH_DOCKER") == "1"}
    if u["role"] == "owner":
        out["summary"] = pricing.cost_summary(cfg)
    return jsonify(out)


@app.post("/api/config")
def post_config():
    incoming = request.get_json(force=True) or {}
    incoming = {k: v for k, v in incoming.items() if v != "******"}   # 没改过的密钥保持原值
    cfg = load_config()
    remap_old = None
    for k, v in incoming.items():
        if k not in cfg or k in ("template_defaults", "category_memory", "shopee_cat_map",
                                 "est_calibration", "est_calibration_n"):
            continue
        if k == "printers":
            if not isinstance(v, list) or not v:
                return err("打印机设置格式不对")
            from core import fleet
            clean = []
            old_pr = cfg.get("printers") or []
            by_code = {o.get("code"): o for o in old_pr if o.get("code")}
            for i, pr in enumerate(v[:200]):
                try:
                    gph = float(pr.get("g_per_h") or 20)
                except (TypeError, ValueError):
                    return err(f"打印机 {i + 1} 的「每小时克数」需要填数字")
                code = str(pr.get("code") or "").strip().upper()
                if code and not fleet.CODE_RE.match(code):
                    return err(f"机器编码「{code}」只能用英文、数字和 - _，最多 16 位")
                en = pr.get("enabled", True)
                clean.append({"code": code, "name": str(pr.get("name") or f"打印机{i + 1}")[:40], "g_per_h": gph,
                              "enabled": en not in (False, "false", "0", 0, ""),
                              "tech": pr.get("tech") if pr.get("tech") in ("fdm", "resin") else "",
                              "note": str(pr.get("note") or "")[:40],
                              "orca_machine": str(pr.get("orca_machine") or "").strip().strip('"'),
                              "orca_process": str(pr.get("orca_process") or "").strip().strip('"'),
                              "orca_filament": str(pr.get("orca_filament") or "").strip().strip('"'),
                              # v2.32：发送切片文件前核对喷嘴直径、热床板
                              "nozzle": _nozzle(pr.get("nozzle")),
                              "plate": str(pr.get("plate") or "").strip()[:40]})
                # 连接设置（IP/访问码）在打印机页单独保存：按机器编码保留原来的
                prev = by_code.get(code) if code else (old_pr[i] if i < len(old_pr) and not old_pr[i].get("code") else None)
                if prev and prev.get("conn"):
                    clean[-1]["conn"] = prev["conn"]
            codes_in = [p["code"] for p in clean if p["code"]]
            dup = {c for c in codes_in if codes_in.count(c) > 1}
            if dup:
                return err("机器编码重复了：" + "、".join(sorted(dup)))
            fleet.ensure_codes(clean)
            busy = fleet.busy_codes(old_pr, clean)
            if busy:
                return err("这些打印机还有正在打印的任务，不能删除：" + "、".join(busy) + "（先在生产看板里点「打完」或「失败」）")
            remap_old = old_pr
            cfg[k] = clean
            continue
        if k == "color_table":
            rows, seen = [], set()
            for line in str(v).splitlines():
                parts = [x.strip() for x in re.split(r"[,，]", line)]
                if len(parts) >= 2 and parts[0] and parts[1]:
                    code = parts[1].upper()
                    if not re.fullmatch(r"[A-Z0-9]{1,6}", code):
                        return err(f"颜色代码「{parts[1]}」只能用 1-6 位英文大写字母或数字")
                    if code in seen:
                        return err(f"颜色代码「{code}」重复了")
                    seen.add(code)
                    rows.append((parts + ["", "", ""])[:5])
            if not rows:
                return err("颜色表不能为空")
            cfg[k] = [[r[0], r[1].upper(), r[2], r[3]] + ([r[4]] if r[4] else []) for r in rows]
            continue
        if isinstance(cfg[k], bool):
            cfg[k] = v in (True, "true", "1", "是", 1)
            continue
        if k in LIST_KEYS:                                # 逗号 / 换行分隔的文字列表（v2.22.1：财务分类也走这里，之前存成字符串导致设置页空白）
            items = v if isinstance(v, list) else re.split(r"[,，、\n]", str(v or ""))
            cfg[k] = [str(x).strip()[:20] for x in items if str(x).strip()][:30]
            continue
        if k == "inv_pack_rules":                         # 发货自动扣包材规则 [{item_id, qty, per}]
            if not isinstance(v, list):
                return err("包材规则格式不对")
            clean = []
            for r in v[:20]:
                try:
                    if r.get("item_id") and float(r.get("qty") or 0) > 0:
                        clean.append({"item_id": int(r["item_id"]), "qty": float(r["qty"]), "per": "item" if r.get("per") == "item" else "order"})
                except (TypeError, ValueError, AttributeError):
                    return err("包材规则里的数量要是数字")
            cfg[k] = clean
            continue
        if isinstance(cfg[k], (int, float)) and not isinstance(cfg[k], bool):
            try:
                v = float(v)
                if isinstance(DEFAULT_INT.get(k), int) and v.is_integer():
                    v = int(v)
            except (TypeError, ValueError):
                return err(f"{k} 需要填数字")
        cfg[k] = v
    if not 0 <= cfg["platform_fee_rate"] < 0.9:
        return err("平台扣点应在 0 到 0.9 之间（例如 0.2 表示 20%）")
    cfg = save_config(cfg)
    if remap_old is not None:
        from core import fleet
        fleet.remap(remap_old, cfg["printers"])
        try:
            chain.reschedule()     # 打印机增减、停用后重新分配任务
        except Exception:  # noqa: BLE001  排单失败不影响保存
            pass
    return jsonify({"config": auth.strip_config(cfg, auth.current_user()), "summary": pricing.cost_summary(cfg)})


@app.get("/api/backups")
def backups_get():
    return jsonify({"items": extras.backups(), "keep": extras.KEEP_BACKUPS})


@app.post("/api/backups")
def backups_post():
    try:
        name = extras.backup_now("manual")
    except OSError as e:
        return err(f"备份失败：{e}")
    return jsonify({"name": name, "items": extras.backups()})


@app.get("/api/backups/<name>")
def backups_download(name):
    return send_from_directory(extras.BACKUP_DIR, os.path.basename(name), as_attachment=True)


@app.post("/api/backups/<name>/verify")
def backups_verify(name):
    from core import sysadmin
    ok, msg = sysadmin.verify_backup(os.path.join(extras.BACKUP_DIR, os.path.basename(name)))
    return jsonify({"ok": ok, "message": msg})


# ---------------- 系统检查 / 在线升级（只有老板） ----------------
@app.get("/api/system/check")
def system_check():
    from core import sysadmin
    return jsonify(sysadmin.check())


@app.post("/api/client-error")
def client_error():
    """页面（浏览器）里出的错，记到运行日志里，方便排查。"""
    u = auth.current_user() or {}
    diag.client_error(request.get_json(force=True, silent=True) or {}, u.get("username", ""), request.headers.get("User-Agent", ""))
    return jsonify({"ok": True})


@app.post("/api/client-timing")
def client_timing():
    """3D 模型打开得慢（超过 2 秒）时页面报上来，记到运行日志，方便看慢在下载、解析还是显示。"""
    u = auth.current_user() or {}
    d = request.get_json(force=True, silent=True) or {}
    def n(k):
        try:
            return round(float(d.get(k) or 0))
        except (TypeError, ValueError):
            return 0
    diag.note("3D 打开较慢 用户=%s %s：共 %sms（下载 %sms / 解析 %sms / 显示 %sms），%s KB，%s 面%s，文件=%s",
              u.get("username", "-"), str(d.get("kind") or "")[:20], n("total"), n("download"), n("parse"), n("prepare"),
              n("bytes") // 1024, n("triangles"), "（精简预览）" if d.get("preview") else "", str(d.get("url") or "")[:160])
    return jsonify({"ok": True})


@app.get("/api/system/errors")
def system_errors():
    return jsonify({"items": diag.recent(int(request.args.get("n") or 50))})


@app.get("/api/system/diagnostics")
def system_diagnostics():
    """诊断包：日志 + 版本 + 系统检查 + 去掉密钥的设置（不含订单和买家资料）。"""
    import io as _io
    from core import sysadmin
    try:
        items = sysadmin.check()
    except Exception as e:  # noqa: BLE001
        items = {"error": str(e)}
    data = diag.bundle(VERSION, items, load_config(), auth.SECRET_KEYS)
    name = f"3d-ops-diag-v{VERSION}-{time.strftime('%Y%m%d-%H%M')}.zip"
    return send_file(_io.BytesIO(data), as_attachment=True, download_name=name, mimetype="application/zip")


@app.post("/api/system/upgrade")
def system_upgrade():
    from core import sysadmin
    f = request.files.get("file")
    if not f:
        return err("请选择升级包（3d-ops-vX.X.zip 或 3d-ops-nas-app-vX.X.zip）")
    tmp = os.path.join(DATA_DIR, "tmp")
    os.makedirs(tmp, exist_ok=True)
    path = os.path.join(tmp, "upgrade.zip")
    f.save(path)
    try:
        r = sysadmin.upgrade(path, force=request.form.get("force") == "1", user=_uname())
    except ValueError as e:
        return err(str(e))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if r["restart"] == "auto":
        sysadmin.restart_later()
    return jsonify(r)


# ---- v2.26 在线更新（GitHub） ----
@app.get("/api/system/update")
def system_update_status():
    from core import updater
    return jsonify(updater.status())


@app.post("/api/system/update/check")
def system_update_check():
    from core import updater
    return jsonify(updater.check(force=True))


@app.post("/api/system/update/apply")
def system_update_apply():
    from core import sysadmin, updater
    b = request.get_json(silent=True) or {}
    try:
        r = updater.apply(b.get("tag") or None, user=_uname())
    except (RuntimeError, ValueError) as e:
        return err(str(e))
    if r["restart"] == "auto":
        sysadmin.restart_later()
    return jsonify(r)


# ---- v2.26 外网访问（Tailscale） ----
@app.get("/api/system/remote")
def system_remote():
    from core import sysadmin
    cfg = load_config()
    return jsonify({"remote_url": cfg.get("remote_url") or "", "tailscale_ips": sysadmin.tailscale_ips(),
                    "port": request.host.rsplit(":", 1)[1] if ":" in request.host else "", "host": request.host})


@app.post("/api/system/remote")
def system_remote_save():
    b = request.get_json(silent=True) or {}
    u = str(b.get("remote_url") or "").strip().rstrip("/")
    if u and not re.match(r"^https?://", u):
        u = "http://" + u
    if u and not re.fullmatch(r"https?://[\w.\-\[\]:]+(/[\w./-]*)?", u):
        return err("地址格式不对，例：http://100.81.34.58:8790")
    cfg = load_config()
    cfg["remote_url"] = u
    save_config(cfg)
    db.audit(_uname(), "外网地址", u or "（清空）")
    return jsonify({"remote_url": u})


@app.post("/api/system/install-rembg")
def system_install_rembg():
    from core import sysadmin
    db.audit(_uname(), "安装抠图组件")
    return jsonify(sysadmin.install_rembg())


@app.post("/api/system/restart")
def system_restart():
    from core import sysadmin
    if not sysadmin.IN_DOCKER:
        return err("Windows 版请关闭黑色窗口，再双击 2_start.bat 启动")
    db.audit(_uname(), "重启程序")
    sysadmin.restart_later()
    return jsonify({"ok": True})


@app.get("/api-docs")
def api_docs():
    with open(os.path.join(BASE_DIR, "static", "api-docs.html"), encoding="utf-8") as f:
        return app.response_class(f.read().replace("{{BASE}}", request.host_url.rstrip("/")), mimetype="text/html")


@app.get("/login")
def login_page():
    if db.user_count() == 0:
        return redirect("/setup")
    return _page("login.html")


@app.get("/setup")
def setup_page():
    if db.user_count() > 0:
        return redirect("/login")
    return _page("login.html")


@app.post("/api/auth/setup")
def auth_setup():
    """第一次使用：创建老板账号（只有在还没有任何账号时可以用）。"""
    if db.user_count() > 0:
        return err("已经有账号了，请直接登录", 403)
    b = request.get_json(force=True) or {}
    try:
        u = db.create_user(b.get("username"), b.get("password"), "owner", b.get("display_name") or "", b.get("lang") or "zh")
    except ValueError as e:
        return err(str(e))
    session.permanent = True
    session["uid"] = u["id"]
    db.audit(u["username"], "创建老板账号")
    return jsonify({"user": u})


# v2.41：连续输错密码先锁一会儿（同一个账号 + 同一个来源：15 分钟内错 8 次 → 锁 15 分钟）。
# 以前只是每次错了等 0.5 秒，同时发很多个请求就能很快地猜（NAS 开了外网访问时尤其要防）
_LOGIN_FAILS = {}
_LOGIN_LOCK = threading.Lock()
LOGIN_MAX_FAILS, LOGIN_WINDOW = 8, 15 * 60


def _login_key(username):
    return (str(username or "").strip().lower(), request.remote_addr or "")


def _login_prune(now):
    """防止被刷爆内存（v2.41 复审：不能整个清空——那样随便编 5000 个用户名就能把正被锁的账号解开）。
    先去掉过期的；还太多就去掉没锁住、最久没动的；锁住的账号最后才动。"""
    for k in [k for k, v in _LOGIN_FAILS.items() if not v or now - v[-1] >= LOGIN_WINDOW]:
        del _LOGIN_FAILS[k]
    if len(_LOGIN_FAILS) <= 5000:
        return
    order = sorted(_LOGIN_FAILS, key=lambda k: (len(_LOGIN_FAILS[k]) >= LOGIN_MAX_FAILS, _LOGIN_FAILS[k][-1]))
    for k in order[:len(_LOGIN_FAILS) - 4000]:
        del _LOGIN_FAILS[k]


def _login_reserve(key):
    """检查有没有锁住，同时先记一次「失败」占住名额（同一把锁里做完）：
    并发发一堆请求也最多试 LOGIN_MAX_FAILS 次；登录成功再整个清掉。返回 False = 锁住了。"""
    now = time.time()
    with _LOGIN_LOCK:
        fails = [t for t in _LOGIN_FAILS.get(key, []) if now - t < LOGIN_WINDOW]
        if len(fails) >= LOGIN_MAX_FAILS:
            _LOGIN_FAILS[key] = fails
            return False
        fails.append(now)
        _LOGIN_FAILS[key] = fails
        if len(_LOGIN_FAILS) > 5000:
            _login_prune(now)
        return True


@app.post("/api/auth/login")
def auth_login():
    b = request.get_json(force=True) or {}
    key = _login_key(b.get("username"))
    if not _login_reserve(key):
        return err("密码错太多次了，请 15 分钟后再试（忘记密码请找老板重设）", 429)
    u = db.authenticate(b.get("username"), b.get("password"))
    if not u:
        return err("用户名或密码不对", 401)
    with _LOGIN_LOCK:
        _LOGIN_FAILS.pop(key, None)
    session.permanent = b.get("remember", True) is not False   # 记住登录：关浏览器也不用重新登录（默认 30 天，用着就一直续期）
    session["uid"] = u["id"]
    db.audit(u["username"], "登录")
    return jsonify({"user": u})


@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/auth/state")
def auth_state():
    return jsonify({"login_required": auth.login_required(), "has_users": db.user_count() > 0, "version": VERSION})


@app.get("/api/me")
def me():
    u = auth.current_user()
    u = dict(u)
    u.setdefault("perms", db.user_perms(u.get("role")))
    return jsonify({"user": u, "login_required": auth.login_required(), "roles": db.ROLES, "perm_list": db.PERMS})


@app.get("/api/users")
def users_list():
    return jsonify({"users": db.list_users(), "roles": db.ROLES, "perm_list": db.PERMS})


@app.post("/api/users")
def users_create():
    b = request.get_json(force=True) or {}
    if db.user_count() == 0 and (b.get("role") or "listing") != "owner":
        return err("请先给自己建一个「老板」账号（否则建好员工账号后你自己就登录不进来了）")
    try:
        u = db.create_user(b.get("username"), b.get("password"), b.get("role") or "listing",
                           b.get("display_name") or "", b.get("lang") or "th")
    except ValueError as e:
        return err(str(e))
    return jsonify({"user": u, "users": db.list_users()})


@app.post("/api/users/<int:uid>")
def users_update(uid):
    b = request.get_json(force=True) or {}
    try:
        extra = {"tabs": b["tabs"]} if "tabs" in b else {}
        u = db.update_user(uid, display_name=b.get("display_name"), role=b.get("role"), lang=b.get("lang"),
                           active=b.get("active"), password=b.get("password") or None, perms=b.get("perms"), **extra)
    except ValueError as e:
        return err(str(e))
    return jsonify({"user": u, "users": db.list_users()})


@app.get("/api/audit")
def audit_list():
    a = request.args
    return jsonify({"items": db.audit_list(int(a.get("limit", 500)), a.get("user") or None, a.get("target") or None,
                                           a.get("q") or None, a.get("days") or None, a.get("hide_login") == "1"),
                    "users": db.audit_users()})


@app.post("/api/me/password")
def me_password():
    """员工自己改密码。"""
    u = auth.current_user()
    if not u or not u.get("id"):
        return err("本机模式不需要密码")
    b = request.get_json(force=True) or {}
    full = db.get_user(uid=u["id"])
    if not db.authenticate(full["username"], b.get("old") or ""):
        return err("原密码不对")
    try:
        db.update_user(u["id"], password=b.get("new") or "")
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True})


@app.post("/api/me/lang")
def me_lang():
    u = auth.current_user()
    lang = (request.get_json(force=True) or {}).get("lang")
    if u and u.get("id") and lang in ("zh", "th"):
        db.update_user(u["id"], lang=lang)
    return jsonify({"ok": True})


@app.get("/api/version")
def api_version():
    r = jsonify({"version": VERSION, "pid": os.getpid()})
    r.headers["Access-Control-Allow-Origin"] = "*"    # v2.26：设置页从局域网测试外网地址能不能打开
    return r


@app.post("/api/shutdown")
def api_shutdown():
    """新版本启动时用来关闭还在运行的旧版本（只接受本机请求）。"""
    if request.remote_addr not in ("127.0.0.1", "::1") or os.environ.get("LH_DOCKER") == "1":
        abort(403)
    if not request.is_json:      # v2.41：别的网页用表单偷偷 POST 过来关掉程序（浏览器跨站发不了 JSON，除非我们同意）
        abort(403)
    threading.Timer(0.3, lambda: os._exit(0)).start()
    return jsonify({"ok": True})


# ---- 泰文翻译审核（v2.15）：导出对照表 → 泰国员工改 → 导入，马上生效 ----
@app.get("/api/system/i18n")
def i18n_status():
    from core import i18n_admin
    return jsonify({"count": i18n_admin.count()})


@app.get("/api/system/i18n/export")
def i18n_export():
    import io as _io
    from core import i18n_admin
    return send_file(_io.BytesIO(i18n_admin.export_xlsx()), as_attachment=True, download_name=f"泰文翻译对照表-v{VERSION}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/api/system/i18n/import")
def i18n_import():
    from core import i18n_admin
    f = request.files.get("file")
    if not f:
        return err("请选择审过的对照表（.xlsx）")
    try:
        n = i18n_admin.import_xlsx(f.read())
    except Exception as e:  # noqa: BLE001  不是这个格式的表格
        return err(f"表格读不了：{e}")
    db.audit(_uname(), "导入泰文翻译修改", "", f"{n} 条")
    return jsonify({"imported": n, "count": i18n_admin.count()})


@app.post("/api/system/i18n/reset")
def i18n_reset():
    from core import i18n_admin
    i18n_admin.reset()
    db.audit(_uname(), "清除泰文翻译修改", "", "")
    return jsonify({"count": 0})


@app.get("/api/settings/schema")
def settings_schema_get():
    """设置页按模块分开的结构（v2.18）。"""
    from core import settings_schema
    return jsonify({"ok": True, "modules": settings_schema.schema()})


@app.get("/api/bg/<jid>")
def bg_job(jid):
    """后台任务的进度 / 结果（切片等，v2.19）。"""
    from core import bgjobs
    j = bgjobs.get(jid)
    if not j:
        return err("任务不存在或已过期（程序重启过？）", 404)
    return jsonify(j)
