"""模块框架的接口（v2.29）：模块列表、开关、模块页面文件、事件记录。"""
from web.common import *  # noqa: F401,F403
from core import modules


@app.get("/api/modules")
def modules_list():
    u = auth.current_user() or {}
    show_all = request.args.get("all") == "1" and auth.is_owner()
    return jsonify({"modules": modules.listing(None if auth.is_owner() else u, all_=show_all)})


@app.post("/api/modules/<mid>")
def modules_toggle(mid):
    b = request.get_json(silent=True) or {}
    try:
        r = modules.set_enabled(mid, bool(b.get("on")))
    except ValueError as e:
        return err(str(e))
    db.audit(_uname(), "模块开关", f"{modules.name_of(mid)} → {'开' if b.get('on') else '关'}")
    return jsonify(r)


@app.get("/api/modules/events")
def modules_events():
    return jsonify({"events": modules.recent_events(int(request.args.get("n") or 50), request.args.get("errors") == "1")})


@app.get("/m/<mid>/<name>")
def modules_ui(mid, name):
    p = modules.ui_path(mid, name)
    if not p:
        abort(404)
    r = send_file(p, max_age=0)
    r.headers["Cache-Control"] = "no-cache"
    return r


# ---------------- 今日待办（v2.46，core/todo.py）：各模块交上来的待办，工作台卡片和「运营分析 → 今日待办」页面共用 ----------------
from core import todo as _todo  # noqa: E402
_todo.init()


@app.get("/api/todo")
def todo_list():
    u = auth.current_user() or {"role": "owner"}
    return jsonify({"ok": True, **_todo.collect(u.get("role"), include_done=request.args.get("all") == "1")})


@app.post("/api/todo/state")
def todo_state():
    b = request.get_json(silent=True) or {}
    try:
        _todo.set_state(b.get("key"), b.get("state") or "", _uname())
    except ValueError as e:
        return err(str(e))
    return jsonify({"ok": True})
