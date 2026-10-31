"""选品模块的接口。
  /api/cur/…              网页用（登录；上架客服看不到成本、利润）
  /api/v1/curate/ext/…    浏览器扩展用（员工的扩展密钥，和 AI 客服、运营采集同一把；只读密钥不能用，见 core/auth.py）
"""
import re
import time

from flask import Blueprint, g, jsonify, request

from core import auth
from core.config import load_config

from . import cand, db, demand, pipeline, sites, watch

bp = Blueprint("m_curate", __name__)
PREFIXES = ["/api/cur/", "/api/v1/curate/"]
db.init()


def _b():
    return request.get_json(force=True, silent=True) or {}


def _who():
    u = getattr(g, "user", None) or {}
    return u.get("display_name") or u.get("username") or ""


def _e(msg, code=400, **kw):
    return jsonify({"ok": False, "error": str(msg), **kw}), code


def _go(fn):
    try:
        r = fn()
        return jsonify({"ok": True, **(r if isinstance(r, dict) else {"data": r})})
    except (ValueError, TypeError) as e:
        return _e(e)


def _owner():
    return auth.is_owner()


def _strip(d):
    """上架客服 / 扩展：去掉成本、利润（ERP 的规矩）。"""
    if _owner():
        return d
    if isinstance(d, dict):
        return {k: _strip(v) for k, v in d.items() if not re.search(r"cost|profit|margin|pricing|floor_price|suggested_price", str(k), re.I)}
    if isinstance(d, list):
        return [_strip(x) for x in d]
    return d


# ======================= 网页 =======================
@bp.get("/api/cur/overview")
def cur_overview():
    def go():
        c = db.conn()
        return {"cand": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE excluded='' AND status=''").fetchone()[0],
                "queue": c.execute("SELECT COUNT(*) FROM cur_collect WHERE state IN ('waiting','running')").fetchone()[0]
                + c.execute("SELECT COUNT(*) FROM cur_files WHERE state IN ('queued','downloading')").fetchone()[0],
                "watch": c.execute("SELECT COUNT(*) FROM cur_watches WHERE enabled=1").fetchone()[0], "ai": cand.ai_on(),
                "owner": _owner(), "alert_score": load_config().get("cur_alert_score") or 70}
    return _go(go)


@bp.get("/api/cur/candidates")
def cur_candidates():
    return _go(lambda: _strip(cand.listing(request.args.to_dict(), _owner())))


@bp.post("/api/cur/candidates/status")
def cur_cand_status():
    b = _b()
    return _go(lambda: cand.set_status(b.get("ids") or [], b.get("status") or "") or {})


@bp.post("/api/cur/candidates/adopt")
def cur_cand_adopt():
    """「采用」：马上建 ERP 产品草稿（许可待核验），详情页进采集队列（装了扩展的 Chrome 在后台读）。也可以贴一批链接（urls）。"""
    b = _b()

    def go():
        items = []
        if b.get("ids"):
            mk = ",".join("?" for _ in b["ids"])
            items = [dict(r) for r in db.conn().execute(f"SELECT url, title, thumb FROM cur_candidates WHERE id IN ({mk})", [int(i) for i in b["ids"]])]
        for u in re.split(r"[\s,]+", str(b.get("urls") or "")):
            if u.strip():
                items.append({"url": u.strip()})
        if not items:
            raise ValueError("没有要采用的")
        r = watch.collect_add(items, _who())
        bad = [u for u, why in r["skipped"].items() if why == "not_model"]
        if bad and not r["added"]:
            raise ValueError("不是支持的模型网站的模型详情页：" + "、".join(bad[:3]))
        return r
    return _go(go)


@bp.get("/api/cur/queue")
def cur_queue():
    """采集队列页：等读详情页的、文件下载进度、最近采用的产品草稿（许可状态、图片 / 文件 / 规格到了没有）。"""
    def go():
        from core import store
        c = db.conn()
        rows = []
        for r in c.execute("SELECT * FROM cur_candidates WHERE product_id<>'' ORDER BY adopted_at DESC LIMIT 60").fetchall():
            try:
                p = store.load(r["product_id"])
            except (FileNotFoundError, ValueError):
                continue
            fs = c.execute("SELECT kind='image' img, state, COUNT(*) n FROM cur_files WHERE product_id=? GROUP BY kind='image', state", (p["id"],)).fetchall()
            q = c.execute("SELECT state, message FROM cur_collect WHERE product_id=? ORDER BY id DESC LIMIT 1", (p["id"],)).fetchone()
            lc = p.get("license_check") or {}
            img = next((f"/files/{p['id']}/{'out' if i.get('processed') else 'raw'}/{i['file']}" for i in p.get("images") or [] if i.get("file")), "")
            rows.append({"product_id": p["id"], "name": p.get("name_zh") or "", "title": r["title"], "url": r["url"], "platform": sites.name_of(r["platform"]),
                         "thumb": img or r["thumb"], "score": r["score"], "adopted_at": r["adopted_at"], "adopted_by": r["adopted_by"], "draft": bool(p.get("draft")),
                         "license": lc.get("status") or "", "license_name": lc.get("name") or "", "license_auto": lc.get("auto") or "",
                         "collect": q["state"] if q else "", "collect_msg": q["message"] if q else "",
                         "files": {("img_" if f["img"] else "") + (f["state"] or "none"): f["n"] for f in fs},
                         "specs": len(p.get("specs") or []), "model": bool(p.get("model")), "copy": bool((p.get("copy") or {}).get("title_th")),
                         "ip": (p.get("ip_risk") or {}).get("status") == "pending"})
        dl = [dict(r) for r in c.execute("SELECT id, product_id, name, state, error, updated_at FROM cur_files WHERE kind<>'image' AND state IN "
                                         "('queued','downloading','failed') ORDER BY state='failed', updated_at DESC LIMIT 40")]
        k = {"waiting": c.execute("SELECT COUNT(*) FROM cur_collect WHERE state IN ('waiting','running')").fetchone()[0],
             "files": c.execute("SELECT COUNT(*) FROM cur_files WHERE kind<>'image' AND state IN ('queued','downloading')").fetchone()[0],
             "failed": c.execute("SELECT COUNT(*) FROM cur_files WHERE kind<>'image' AND state='failed'").fetchone()[0],
             "lic_pending": sum(1 for r in rows if r["license"] == "pending"),
             "adopted_30d": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE adopted_at>=?", (time.time() - 30 * 86400,)).fetchone()[0]}
        days = []
        t0 = db.day_start()
        for i in range(13, -1, -1):
            a = t0 - i * 86400
            days.append({"day": time.strftime("%m-%d", time.gmtime(a + 7 * 3600)),
                         "n": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE adopted_at>=? AND adopted_at<?", (a, a + 86400)).fetchone()[0]})
        return {"rows": rows, "downloads": dl, "collect": watch.collect_queue(), "kpi": k, "days": days, "pace": watch.overview()}
    return _go(go)


@bp.post("/api/cur/products/<pid>/download")
def cur_product_download(pid):
    b = _b()
    return _go(lambda: {"queued": watch.queue_download(pid, b.get("ids"))})


@bp.get("/api/cur/products/<pid>/files")
def cur_product_files(pid):
    return _go(lambda: {"rows": watch.product_files(pid)})


@bp.get("/api/cur/watches")
def cur_watches():
    return _go(lambda: watch.board())


@bp.post("/api/cur/watches")
def cur_watch_add():
    b = _b()
    return _go(lambda: watch.add(b, _who()))


@bp.post("/api/cur/watches/<int:wid>")
def cur_watch_update(wid):
    b = _b()
    return _go(lambda: watch.update(wid, b) or watch.board())


@bp.post("/api/cur/pace/reset")
def cur_pace_reset():
    b = _b()
    return _go(lambda: watch.reset(b.get("platform") or None) or {"pace": watch.overview()})


@bp.post("/api/cur/collect/action")
def cur_collect_action():
    b = _b()
    return _go(lambda: watch.collect_action(int(b.get("id") or 0), b.get("action") or ""))


@bp.post("/api/cur/from-radar")
def cur_from_radar():
    b = _b()
    return _go(lambda: demand.from_radar(load_config(), b.get("kid"), b.get("keyword") or "", _who()))


@bp.post("/api/cur/rescore")
def cur_rescore():
    return _go(lambda: cand.rescore_all() or {})


@bp.post("/api/cur/calibrate")
def cur_calibrate():
    return _go(lambda: {"calib": pipeline.calibrate()})


# ======================= 浏览器扩展 =======================
@bp.get("/api/v1/curate/ext/ping")
def ext_ping():
    from core import integrations
    c = db.conn()
    return jsonify({"ok": True, "user": _who(), "ext_latest": integrations.EXT_LATEST, "ai": cand.ai_on(),
                    "sites": sites.public_list()["version"], "queue": watch.collect_queue()["waiting"],
                    "files": c.execute("SELECT COUNT(*) FROM cur_files WHERE state IN ('queued','downloading')").fetchone()[0],
                    "new_today": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE new_at>=? AND excluded=''", (db.day_start(),)).fetchone()[0],
                    "watches": c.execute("SELECT COUNT(*) FROM cur_watches WHERE enabled=1").fetchone()[0],
                    "paused": [p["name"] for p in watch.overview() if p["paused"]]})


@bp.get("/api/v1/curate/ext/sites")
def ext_sites():
    return jsonify({"ok": True, **sites.public_list()})


@bp.post("/api/v1/curate/ext/score")
def ext_score():
    return _go(lambda: {"scores": _strip(cand.upsert(_b().get("items") or [], _who()))})


@bp.post("/api/v1/curate/ext/status")
def ext_status():
    return _go(lambda: {"states": watch.collect_states(_b().get("urls") or [])})


@bp.post("/api/v1/curate/ext/collect")
def ext_collect():
    b = _b()
    return _go(lambda: {**watch.collect_add(b.get("items") or [], _who()), **watch.collect_queue()})


@bp.get("/api/v1/curate/ext/queue")
def ext_queue():
    return _go(lambda: watch.collect_queue())


@bp.post("/api/v1/curate/ext/queue/action")
def ext_queue_action():
    b = _b()
    return _go(lambda: watch.collect_action(int(b.get("id") or 0), b.get("action") or ""))


@bp.get("/api/v1/curate/ext/next")
def ext_next():
    return _go(lambda: watch.collect_next())


@bp.post("/api/v1/curate/ext/result")
def ext_result():
    b = _b()
    return _go(lambda: watch.collect_result(b, _who()))


@bp.get("/api/v1/curate/ext/files/next")
def ext_files_next():
    return _go(lambda: watch.files_next())


@bp.post("/api/v1/curate/ext/files/<int:fid>/upload")
def ext_file_upload(fid):
    name = request.args.get("name") or ""
    return _go(lambda: watch.file_uploaded(fid, name, request.stream))


@bp.post("/api/v1/curate/ext/files/<int:fid>/fail")
def ext_file_fail(fid):
    b = _b()
    return _go(lambda: watch.file_fail(fid, b))


@bp.get("/api/v1/curate/ext/watch/next")
def ext_watch_next():
    return _go(lambda: watch.watch_next())


@bp.post("/api/v1/curate/ext/watch/result")
def ext_watch_result():
    b = _b()
    return _go(lambda: watch.watch_result(int(b.get("id") or 0), b.get("items") or [], b.get("error") or "",
                                          {"snippet": b.get("snippet"), "url": b.get("url"), "status": b.get("status")}))
