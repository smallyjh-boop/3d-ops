"""店铺与系统对接模块的接口（v2.30 从 web/integrations.py 搬过来）：
店铺（平台开放接口拉订单、授权、Webhook 推送）、3D选品工具推产品（/api/v1/catalog/…）、运营分析系统写回（/api/v1/ops/…）和「运营改动」页面。
API 密钥管理、只读查询接口（/api/v1/orders、skus、cost-params…）在内核。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403
from core import connectors, integrations
from . import curator, opsapi

bp = Blueprint("m_link", __name__)
PREFIXES = ["/api/curator", "/api/v1/categories", "/api/v1/catalog/", "/api/v1/ops/", "/api/ops/", "/api/v1/webhook/", "/api/shops"]
curator.init()
opsapi.init()


def _ops_err(e):
    return jsonify({"ok": False, "error": str(e), "code": getattr(e, "code", "invalid")}), getattr(e, "http", 400)


def _v1_err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


@bp.get("/api/curator")
def curator_status():
    return jsonify(curator.status())


@bp.post("/api/curator")
def curator_save():
    b = request.get_json(force=True) or {}
    return jsonify(curator.save(b.get("base_url"), b.get("api_key")))


@bp.post("/api/curator/test")
def curator_test():
    b = request.get_json(force=True) or {}
    return jsonify(curator.test(b.get("base_url"), b.get("api_key")))


@bp.post("/api/v1/catalog/products")
def v1_catalog_create():
    b = request.get_json(force=True, silent=True)
    if b is None:
        return jsonify({"ok": False, "error": "请求体必须是 JSON", "code": "invalid_field"}), 400
    try:
        r = curator.create(b, auth.current_user()["username"])
    except curator.CatalogError as e:
        return jsonify({"ok": False, "error": str(e), "code": e.code}), e.http
    return jsonify({"ok": True, **r}), (201 if r["created"] else 200)


@bp.post("/api/v1/catalog/products/<code>/files")
def v1_catalog_add_files(code):
    """选品工具补传模型文件（已建档的产品）。"""
    b = request.get_json(force=True, silent=True)
    if b is None:
        return jsonify({"ok": False, "error": "请求体必须是 JSON", "code": "invalid_field"}), 400
    try:
        r = curator.add_files(code, b, auth.current_user()["username"])
    except curator.CatalogError as e:
        return jsonify({"ok": False, "error": str(e), "code": e.code}), e.http
    return jsonify({"ok": True, **r})


@bp.put("/api/v1/catalog/products/<code>/variants")
def v1_catalog_sync_variants(code):
    """选品工具同步规格（对接规范 4.3.5，v2.16）：传完整列表，按 spec_id 对比；已导出的产品删掉的规格只标记待确认。"""
    b = request.get_json(force=True, silent=True)
    if b is None:
        return jsonify({"ok": False, "error": "请求体必须是 JSON", "code": "invalid_field"}), 400
    try:
        r = curator.sync_variants(code, b, auth.current_user()["username"])
    except curator.CatalogError as e:
        return jsonify({"ok": False, "error": str(e), "code": e.code}), e.http
    return jsonify({"ok": True, **r})


@bp.post("/api/v1/ops/products/<target>")
def v1_ops_product(target):
    b = request.get_json(force=True, silent=True) or {}
    try:
        ch = opsapi.submit(target, b.get("changes"), b.get("reason") or "", b.get("source_action_id") or "", _uname())
    except opsapi.OpsError as e:
        return _ops_err(e)
    return jsonify({"ok": True, "change_id": ch["id"], "applied": ch["applied"], "status": ch["status"],
                    "product_id": ch["product_id"], "sku": ch["sku"], "before": ch["before"], "after": ch["after"]})


@bp.post("/api/v1/ops/changes/<int:cid>/revert")
def v1_ops_revert(cid):
    try:
        ch = opsapi.revert(cid, _uname())
    except opsapi.OpsError as e:
        return _ops_err(e)
    return jsonify({"ok": True, "change": ch})


@bp.get("/api/v1/ops/changes")
def v1_ops_changes():
    a = request.args
    return jsonify({"ok": True, "mode": opsapi.mode(),
                    "changes": opsapi.list_changes(a.get("since") or 0, a.get("status") or "", a.get("limit") or 200)})


# ERP 页面里查看 / 通过 / 拒绝 / 撤回
@bp.get("/api/ops/changes")
def ops_changes_ui():
    a = request.args
    return jsonify({"changes": opsapi.list_changes(0, a.get("status") or "", a.get("limit") or 300, a.get("q") or ""),
                    "counts": opsapi.counts(), "mode": opsapi.mode(), "status_zh": opsapi.STATUS_ZH})


@bp.post("/api/ops/changes/<int:cid>/<act>")
def ops_change_act(cid, act):
    try:
        if act == "approve":
            ch = opsapi.approve(cid, _uname())
        elif act == "reject":
            ch = opsapi.reject(cid, _uname(), (request.get_json(force=True, silent=True) or {}).get("note") or "")
        elif act == "revert":
            ch = opsapi.revert(cid, _uname())
        else:
            return err("动作不对")
    except opsapi.OpsError as e:
        return err(str(e))
    return jsonify({"change": ch})


@bp.route("/api/v1/webhook/<platform>", methods=["GET", "POST"])
def v1_webhook(platform):
    """平台主动推送。GET 用于平台校验地址是否可用。"""
    if request.method == "GET":
        return jsonify({"ok": True})
    if platform not in connectors.REGISTRY:
        return _v1_err("不支持的平台", 404)
    res = integrations.webhook(platform, request.headers, request.get_data()[:1_000_000], request.url)
    return jsonify({"ok": True, "result": res})


@bp.post("/api/shops")
def shop_save():
    try:
        sid = integrations.save_shop(request.get_json(force=True) or {})
    except ValueError as e:
        return err(str(e))
    return jsonify({"id": sid, "shops": integrations.list_shops()})


@bp.delete("/api/shops/<int:sid>")
def shop_delete(sid):
    integrations.delete_shop(sid)
    return jsonify({"shops": integrations.list_shops()})


@bp.post("/api/shops/sync-all")
def shop_sync_all():
    """v2.44.1：工作台 / 订单页的「同步订单」：开了接口的店铺都马上拉一次订单。"""
    out = []
    for r in integrations.list_shops():
        if not r.get("enabled") or not r.get("ready"):
            continue
        try:
            st = integrations.sync_shop(r["id"])
            out.append({"shop": r["name"], "new": st.get("orders_new", 0), "updated": st.get("orders_updated", 0)})
        except Exception as e:  # noqa: BLE001  一个店失败不影响别的
            out.append({"shop": r["name"], "error": str(e)[:200]})
    if not out:
        return err("还没有开了接口的店铺（设置 → AI 与对接 → 店铺对接）")
    return jsonify({"shops": out})


@bp.post("/api/shops/<int:sid>/sync")
def shop_sync(sid):
    b = request.get_json(force=True, silent=True) or {}
    try:
        st = integrations.sync_shop(sid, full=bool(b.get("full")))
    except Exception as e:  # 连接器错误原样告诉老板
        return err(f"同步失败：{e}")
    return jsonify(st)


@bp.post("/api/shops/<int:sid>/auth-url")
def shop_auth_url(sid):
    b = request.get_json(force=True) or {}
    try:
        return jsonify({"url": integrations.authorize_url(sid, b.get("redirect") or request.host_url, b.get("app") or "")})
    except Exception as e:  # 缺 App Key 等
        return err(str(e))


@bp.post("/api/shops/<int:sid>/auth-code")
def shop_auth_code(sid):
    b = request.get_json(force=True) or {}
    try:
        integrations.exchange_code(sid, b.get("code") or "", b.get("app") or "")
    except Exception as e:  # 授权失败
        return err(f"授权失败：{e}")
    return jsonify({"ok": True, "shops": integrations.list_shops()})


@bp.get("/api/v1/categories")
def v1_categories():
    """ERP 里能用的类目（已上传 Lazada 模板的类目）。name 就是推送时 category 要填的值。"""
    from core import extras as _ex
    return jsonify({"ok": True, "categories": curator.categories(),
                    "groups": [{"id": g["id"], "name": g["name"]} for g in _ex.groups()]})
