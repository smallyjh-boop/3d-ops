"""手机 / 平板 App 的接口：手机页 /m、扫码识别、查订单、交接选物流、打包照片、安卓 App 安装包。"""
import json as _json
import os

from flask import Blueprint

from web.common import *  # noqa: F401,F403
from core import modules
from modules.mobile import apk, photos, resolver

bp = Blueprint("m_mobile", __name__)
PREFIXES = ["/api/mobile/"]
PATTERNS = []
UI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")


def _ver():
    m = (modules.get("mobile") or {}).get("meta") or {}
    return f"{VERSION}-{m.get('version') or ''}"


@bp.get("/m")
def mobile_page():
    """手机页（不用登录也能打开：没登录时页面自己显示登录框）。"""
    if not modules.enabled("mobile"):
        return "模块没有打开", 404
    with open(os.path.join(UI, "m.html"), encoding="utf-8") as f:
        html = f.read()
    mi = _json.dumps(modules.i18n_th(), ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("{{V}}", _ver()).replace("{{VERSION}}", VERSION)
    html = html.replace("</head>", f'<script>window.CLIENT_VERSION="{VERSION}";window.I18N_MODULES={mi};</script></head>', 1)
    r = app.response_class(html, mimetype="text/html")
    r.headers["Cache-Control"] = "no-store"
    return r


@bp.get("/api/mobile/boot")
def mobile_boot():
    """手机页一打开：我是谁、能做什么、哪些模块开着。"""
    u = dict(auth.current_user() or {})
    perms = u.get("perms") or db.user_perms(u.get("role"))
    cfg = load_config()
    return jsonify({"user": {k: u.get(k) for k in ("username", "display_name", "role", "lang")}, "perms": perms,
                    "inv": modules.enabled("inv"), "pur": modules.enabled("pur") and modules.enabled("inv"), "version": VERSION, "scan_key": cfg.get("scan_order_key") or "both",
                    "can_cancel_view": True})


@bp.get("/api/mobile/resolve")
def mobile_resolve():
    a = request.args
    try:
        return jsonify(resolver.resolve(a.get("code"), auth.current_user(), a.get("prefer") or "", a.get("fresh") == "1",
                                        fuzzy=a.get("fuzzy") == "1"))
    except ValueError as e:
        return err(str(e))


@bp.get("/api/mobile/code-patterns")
def mobile_code_patterns():
    """安卓 App 的文字识别：哪些文字「像码」（货位、订单号、快递单号、SKU）——像了才送给网页（拍照识别模块关着时只给空表）。"""
    rc = modules.public("recog")
    if not rc:
        return jsonify({"v": 1, "patterns": [], "enabled": False})
    from core.config import load_config
    if not load_config().get("recog_on", True):
        return jsonify({"v": 1, "patterns": [], "enabled": False})
    return jsonify({**rc.code_patterns(), "enabled": True})


@bp.get("/api/mobile/orders")
def mobile_orders():
    try:
        return jsonify({"orders": resolver.search_orders(request.args.get("q"))})
    except ValueError as e:
        return err(str(e))


@bp.get("/api/mobile/orders/<int:oid>")
def mobile_order(oid):
    s = resolver.order_summary(oid, auth.current_user(), request.args.get("fresh") == "1")
    if not s:
        return err("订单不存在", 404)
    return jsonify({"order": s, "alert": resolver._order_alert(s)})


@bp.get("/api/mobile/carriers")
def mobile_carriers():
    return jsonify(resolver.carriers())


@bp.get("/api/mobile/orders/<int:oid>/photos")
def mobile_photos(oid):
    return jsonify({"photos": photos.list_photos(oid)})


@bp.post("/api/mobile/orders/<int:oid>/photos")
def mobile_photos_add(oid):
    try:
        return jsonify({"photos": photos.add(oid, request.files.getlist("files"), _uname(), request.form.get("kind") or "pack")})
    except ValueError as e:
        return err(str(e))


@bp.get("/api/mobile/orders/<int:oid>/photos/<name>")
def mobile_photo_get(oid, name):
    p = photos.path_of(oid, name)
    if not p:
        return err("照片不存在", 404)
    return send_file(p, mimetype="image/jpeg", conditional=True, max_age=86400)


# ---------------- 安卓 App 安装包 ----------------
def _apk_response():
    p, ver = apk.local_file()
    if not p:
        return app.response_class(
            "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<p style='font:16px sans-serif;padding:20px'>NAS 上还没有安卓 App 安装包：请老板在 设置 → 组件与插件 → 安卓 App 里点「从 GitHub 取最新版」或上传。<br><br>"
            "ยังไม่มีไฟล์ติดตั้งแอป Android บน NAS: ให้เจ้าของกด「ดึงเวอร์ชันล่าสุดจาก GitHub」หรืออัปโหลดใน ตั้งค่า → ส่วนประกอบและปลั๊กอิน → แอป Android</p>",
            status=404, mimetype="text/html")
    return send_file(p, mimetype="application/vnd.android.package-archive", as_attachment=True,
                     download_name=f"3D-Ops-{ver}.apk", max_age=0)


@bp.get("/apk")
def apk_short():
    if not modules.enabled("mobile"):
        return "模块没有打开", 404
    return _apk_response()


@bp.get("/api/mobile/apk/download")
def apk_download():
    return _apk_response()


@bp.get("/api/mobile/apk")
def apk_status():
    return jsonify(apk.status())


@bp.post("/api/mobile/apk/fetch")
def apk_fetch():
    try:
        return jsonify(apk.fetch_latest(_uname()))
    except ValueError as e:
        return err(str(e))


@bp.post("/api/mobile/apk/check")
def apk_check():
    try:
        apk.check_latest()
    except (RuntimeError, ValueError) as e:
        return err(str(e))
    return jsonify(apk.status())


@bp.post("/api/mobile/apk/upload")
def apk_upload():
    f = request.files.get("file")
    if not f:
        return err("请选择 APK 文件")
    try:
        return jsonify(apk.upload(f, request.form.get("version") or "", _uname()))
    except ValueError as e:
        return err(str(e))
