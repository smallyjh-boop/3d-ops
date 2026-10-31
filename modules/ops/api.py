"""运营分析模块的接口（/api/oa/…）。看板、生命周期、Lazada 数据只给老板（OWNER_ONLY）；评价列表和回复评价上架客服也能用。
今日待办的接口在内核（/api/todo，web/modules.py），这里只有推送相关的。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403
from . import alerts, dash, lazada, lifecycle, mkt_api

bp = Blueprint("m_ops", __name__)
PREFIXES = ["/api/oa/", "/api/v1/ops/ext/"]          # v2.48：浏览器扩展采集 /api/v1/ops/ext/…（最长前缀优先，/api/v1/ops/ 其余的还是对接模块的）
lazada.init()
alerts.init()
mkt_api.attach(bp)                                  # v2.48：竞品、爆款雷达、竞店、计划、营销日历、店铺后台数据


def _wrap(fn):
    try:
        return jsonify({"ok": True, **fn()})
    except ValueError as e:
        return err(str(e))


@bp.get("/api/oa/dashboard")
def oa_dashboard():
    return _wrap(dash.dashboard)


@bp.get("/api/oa/lifecycle")
def oa_lifecycle():
    return _wrap(lifecycle.board)


@bp.get("/api/oa/lazada")
def oa_lazada():
    days = max(1, min(90, int(request.args.get("days") or 30)))
    owner = auth.is_owner()

    def go():
        out = {"status": lazada.status(), "reviews": lazada.reviews_list(days), "shops": lazada.shops(),
               "sync_min": load_config().get("oa_lz_sync_min")}
        if owner:
            out.update(summary=lazada.summary(days), reverse=lazada.reverse_list(days), performance=lazada.performance(),
                       fees=lazada.fee_rates(days))
        return out
    return _wrap(go)


@bp.post("/api/oa/lazada/sync")
def oa_lazada_sync():
    b = request.get_json(silent=True) or {}
    if not lazada.shops():
        return err("还没有开着的 Lazada 店铺（设置 → AI 与对接 → 店铺对接）")
    user = _uname()
    return maybe_async("同步 Lazada 运营数据", lambda: jsonify({"ok": True, **lazada.sync(b.get("shop_id"), b.get("kinds"), user)}), "sync")


@bp.post("/api/oa/reviews/reply")
def oa_review_reply():
    b = request.get_json(silent=True) or {}
    try:
        return jsonify(lazada.reply_review(b.get("shop_id"), b.get("review_id"), b.get("content"), _uname()))
    except ValueError as e:
        return err(str(e))
    except Exception as e:  # noqa: BLE001  Lazada 报错：原样告诉用户
        return err(str(e)[:300])


@bp.get("/api/oa/alerts")
def oa_alerts():
    from core import todo
    cfg = load_config()
    return jsonify({"ok": True, "recent": alerts.recent(100), "sources": todo.sources(), "muted": sorted(alerts.muted(cfg)),
                    "on": bool(cfg.get("oa_alert_on")), "channels": alerts.channels(cfg)})


@bp.post("/api/oa/alerts/muted")
def oa_alerts_muted():
    b = request.get_json(silent=True) or {}
    return jsonify({"ok": True, "muted": alerts.set_muted(b.get("source") or "", bool(b.get("muted")))})


@bp.post("/api/oa/alerts/test")
def oa_alerts_test():
    ok, e = alerts.send("✅ 3D 运营管理系统：手机提醒测试成功")
    return jsonify({"ok": True}) if ok else err(e or "发送失败")


@bp.post("/api/oa/alerts/run")
def oa_alerts_run():
    return jsonify({"ok": True, **alerts.run_once(force=True)})
