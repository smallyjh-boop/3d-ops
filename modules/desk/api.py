"""桌面客户端的接口：配对、电脑列表 / 停用、「在本机打开」的一次性下载码、下载安装包。"""
import json
import re
import secrets
import time

from flask import Blueprint, current_app, g, jsonify, request, send_file

from core import auth, db, desktop
from core.config import load_config

bp = Blueprint("m_desk", __name__)
PREFIXES = ["/api/desktop/"]


def _err(msg, code=400):
    return jsonify({"error": msg}), code


def _version():
    from web.common import VERSION
    return VERSION


def _login():
    u = auth.current_user()
    return u if u and u.get("id", -1) != -1 else None


@bp.post("/api/desktop/pair")
def desktop_pair():
    u = _login()
    if not u:
        return _err("请先登录", 401)
    b = request.get_json(silent=True) or {}
    try:
        r = desktop.pair(u, b.get("device_id"), b.get("device_name"))
    except ValueError as e:
        return _err(str(e))
    db.audit(u.get("username", ""), "桌面端配对", str(b.get("device_name") or "")[:40], str(b.get("device_id") or "")[:8])
    return jsonify({"ok": True, **r, "server_version": _version()})


@bp.get("/api/desktop/devices")
def desktop_devices():
    return jsonify({"devices": desktop.devices()})


@bp.post("/api/desktop/devices/<did>/revoke")
def desktop_revoke(did):
    if not desktop.revoke(did):
        return _err("找不到这台电脑", 404)
    db.audit((g.get("user") or {}).get("username", ""), "停用桌面端", did[:8])
    return jsonify({"ok": True})


# ---- 「在本机打开」：网页拿一个 2 分钟有效的一次性下载码，桌面端直接下载（不用经过网页传大文件） ----
_DL = {}
DL_OK = (r"/api/print-files/\d+/download", r"/api/products/[^/]{1,60}/model/download")


@bp.post("/api/desktop/dltoken")
def desktop_dltoken():
    u = _login()
    if not u:
        return _err("请先登录", 401)
    path = str((request.get_json(silent=True) or {}).get("path") or "").split("?")[0]
    if not any(re.fullmatch(p, path) for p in DL_OK):
        return _err("这个文件不能在本机打开")
    now = time.time()
    for k in [k for k, v in _DL.items() if v["exp"] < now]:
        _DL.pop(k, None)
    tok = secrets.token_urlsafe(24)
    _DL[tok] = {"path": path, "user": dict(u), "exp": now + 120}
    return jsonify({"url": "/api/desktop/dl/" + tok})


@bp.get("/api/desktop/dl/<tok>")
def desktop_dl(tok):
    t = _DL.pop(tok, None)
    if not t or t["exp"] < time.time():
        return _err("下载码过期了，请再点一次", 404)
    g.user = t["user"]
    endpoint, args = current_app.url_map.bind("").match(t["path"], method="GET")
    return current_app.view_functions[endpoint](**args)


@bp.get("/api/desktop/package")
def desktop_package():
    """桌面客户端安装包：解压后双击「Install.bat」。里面带好 NAS 地址（局域网 + 外网），装好登录就能用。"""
    from web.accel import app_zip, install_bat
    u = _login()
    if not u:
        return _err("请先登录", 401)
    ver = _version()
    cfg = load_config()
    here = request.host_url.rstrip("/")
    servers = [here] + [x for x in [str(cfg.get("remote_url") or "").rstrip("/")] if x and x != here]
    buf = app_zip("3D-Ops-Desktop", {"server.json": json.dumps({"servers": servers, "version": ver}, ensure_ascii=False),
                                     "Install.bat": install_bat()})
    db.audit(u.get("username", ""), "下载桌面客户端", ver)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=f"3D-Ops-Desktop-{ver}.zip")


# ---- v2.56（T36）🔧 切片软件自检：测试盘（不建产品）→ 软件里挪一下保存 → 自动回传核对 → 结果存日志 ----
@bp.post("/api/desktop/selftest/start")
def desktop_selftest_start():
    from modules.desk import selftest
    u = _login()
    if not u:
        return _err("请先登录", 401)
    apps = [a for a in ((request.get_json(silent=True) or {}).get("apps") or ["bambu", "orca"]) if a in ("bambu", "orca")]
    return jsonify({"runs": selftest.start(u.get("username", ""), apps)})


@bp.get("/api/desktop/st/<sid>/file")
def desktop_selftest_file(sid):
    from modules.desk import selftest
    try:
        path, name = selftest.take_file(sid, request.args.get("t"))
    except PermissionError as e:
        return _err(str(e), 403)
    return send_file(path, mimetype="model/3mf", as_attachment=True, download_name=name)


@bp.post("/api/desktop/st/<sid>/upload")
def desktop_selftest_upload(sid):
    from modules.desk import selftest
    from modules.model import editsession
    request.max_content_length = editsession.MAX_UPLOAD
    f = request.files.get("file")
    try:
        return jsonify({"ok": True, "check": selftest.upload(sid, request.args.get("t"), f.read() if f else request.get_data())})
    except PermissionError as e:
        return _err(str(e), 403)
    except ValueError as e:
        return _err(str(e))


@bp.post("/api/desktop/selftest/report")
def desktop_selftest_report():
    from modules.desk import selftest
    u = _login()
    if not u:
        return _err("请先登录", 401)
    return jsonify({"ok": True, "record": selftest.report(u.get("username", ""), request.get_json(silent=True) or {})})


@bp.get("/api/desktop/selftest/log")
def desktop_selftest_log():
    from modules.desk import selftest
    return jsonify({"log": selftest.log()})
