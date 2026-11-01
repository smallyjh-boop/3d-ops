"""AI 接口模块的接口（只有老板能用）：设置（密钥打码）、测试连接、用量统计。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403
from core import ai

bp = Blueprint("m_ai", __name__)
PREFIXES = ["/api/ai/"]
PATTERNS = []


def _view():
    cfg = load_config()
    v = ai.conf.public_view(cfg)
    today, today_n = ai.usage.spent(None, "day")
    month, month_n = ai.usage.spent(None, "month")
    v.update(usage={"today": round(today, 2), "today_n": today_n, "month": round(month, 2), "month_n": month_n},
             migrated=cfg.get("ai_migrated") or None, scene_templates=None)
    return v


@bp.get("/api/ai/settings")
def ai_settings():
    ai.ensure_migrated()
    return jsonify(_view())


@bp.post("/api/ai/settings")
def ai_settings_save():
    b = request.get_json(force=True) or {}
    upd = ai.conf.apply_update(load_config(), b)
    if upd:
        save_config(upd)
    return jsonify(_view())


@bp.post("/api/ai/test")
def ai_test():
    b = request.get_json(force=True) or {}
    pid = str(b.get("provider") or "")
    if pid not in ai.catalog.PROVIDERS:
        return err("没有这个服务商")
    kind = "image" if b.get("kind") == "image" else "text"
    if kind == "text" and ai.catalog.TEXT not in ai.catalog.PROVIDERS[pid]["caps"]:
        kind = "image"
    return jsonify(ai.test(load_config(), pid, kind))


@bp.get("/api/ai/usage")
def ai_usage():
    try:
        days = max(1, min(int(request.args.get("days") or 30), 366))
    except ValueError:
        days = 30
    d = ai.usage.stats(days, request.args.get("task") or "", request.args.get("provider") or "")
    d["tasks"] = {k: {"zh": v[1], "th": v[2], "group": v[0]} for k, v in ai.catalog.TASKS.items()}
    d["providers"] = {k: {"zh": v["zh"], "th": v["th"]} for k, v in ai.catalog.PROVIDERS.items()}
    cfg = load_config()
    d["limits"] = cfg.get("ai_limits") or {}
    return jsonify(d)
