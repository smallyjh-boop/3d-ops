"""选品模块的接口。
  /api/cur/…              网页用（登录；上架客服看不到成本、利润）
  /api/v1/curate/ext/…    浏览器扩展用（员工的扩展密钥，和 AI 客服、运营采集同一把；只读密钥不能用，见 core/auth.py）
"""
import re
import time

from flask import Blueprint, g, jsonify, request

from core import auth
from core.config import load_config

from . import cand, db, demand, inbox, pipeline, sites, watch

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
        inbox.migrate()
        c = db.conn()
        return {"cand": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE excluded='' AND status=''").fetchone()[0],
                "queue": c.execute("SELECT COUNT(*) FROM cur_collect WHERE state IN ('waiting','running')").fetchone()[0]
                + c.execute("SELECT COUNT(*) FROM cur_files WHERE state IN ('queued','downloading')").fetchone()[0],
                "watch": c.execute("SELECT COUNT(*) FROM cur_watches WHERE enabled=1").fetchone()[0], "ai": cand.ai_on(),
                "inbox": inbox.count(), "ext": watch.ext_status(),
                "sites": [{"id": i, "name": n, "url": u.replace("{q}", "")} for i, n, u in sites.search_entries()],
                "waiting": c.execute("SELECT COUNT(*) FROM cur_collect WHERE state IN ('waiting','running')").fetchone()[0]
                + c.execute("SELECT COUNT(*) FROM cur_files WHERE state IN ('queued','downloading')").fetchone()[0],
                "owner": _owner(), "alert_score": load_config().get("cur_alert_score") or 70}
    return _go(go)


@bp.get("/api/cur/candidates")
def cur_candidates():
    return _go(lambda: _strip(cand.listing(request.args.to_dict(), _owner())))


@bp.post("/api/cur/candidates/status")
def cur_cand_status():
    b = _b()
    return _go(lambda: cand.set_status(b.get("ids") or [], b.get("status") or "") or {})


@bp.post("/api/cur/candidates/recollect")
def cur_cand_recollect():
    """「重新读取」：候选的详情页进采集队列，扩展读到后改正标题、作者、缩略图（不建产品）。ids 空 = 全部「采集可能出错」的。"""
    b = _b()

    def go():
        ids = b.get("ids") or [r[0] for r in db.conn().execute("SELECT id FROM cur_candidates WHERE capture_bad<>'' AND product_id=''")]
        return {"queued": watch.recollect_candidates(ids)}
    return _go(go)


@bp.post("/api/cur/candidates/delete-bad")
def cur_cand_delete_bad():
    """批量「删除采集错误的」（没采用过的）。"""
    b = _b()
    # 它们排着的「重新读取」任务一起删掉（以前留在采集队列里，扩展读到才发现「候选已经删掉了」，白白占着队列）
    return _go(lambda: {"deleted": cand.delete_bad(b.get("ids") or None), "jobs_canceled": watch.cancel_orphans()})


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
        watch.cancel_orphans()                     # 候选 / 产品草稿已删除的任务：自动取消，不当失败显示
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
                         "ip": (p.get("ip_risk") or {}).get("status") == "pending", "fstat": watch.file_status(p["id"]),
                         "inbox": bool(p.get("inbox"))})
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
        return {"rows": rows, "jobs": watch.jobs(request.args.to_dict()), "status": watch.queue_status(), "collect": watch.collect_queue(), "kpi": k,
                "days": days, "pace": watch.overview(), "ext": watch.ext_status()}
    return _go(go)


@bp.post("/api/cur/jobs/action")
def cur_jobs_action():
    """采集队列的批量操作（勾选的任务 c<编号> = 详情页、f<编号> = 文件下载）：delete / retry / hold / resume / prio / top / bottom / up / down / move。"""
    b = _b()
    return _go(lambda: watch.job_action([str(x) for x in (b.get("ids") or [])][:500], b.get("action") or "", b.get("prio"), b.get("before")))


@bp.post("/api/cur/queue/cleanup")
def cur_queue_cleanup():
    """「清理失败 / 无效任务」。"""
    return _go(lambda: watch.cleanup())


@bp.post("/api/cur/sites/<site>/hold")
def cur_site_hold(site):
    """手动暂停 / 继续一个网站（采集、下载、巡逻一起）；继续也会清掉风控暂停。"""
    b = _b()
    return _go(lambda: watch.hold_site(site, bool(b.get("on"))) or {"pace": watch.overview()})


@bp.post("/api/cur/products/<pid>/download")
def cur_product_download(pid):
    """「⬇ 下载模型文件」：没下载的 / 失败的排队；一个文件链接都没有就重新读详情页（扩展读到后自动下载）。"""
    b = _b()
    return _go(lambda: {**watch.queue_download(pid, b.get("ids")), "status": watch.file_status(pid)})


@bp.get("/api/cur/products/<pid>/files")
def cur_product_files(pid):
    """编辑页 / 产品 360：模型文件（已下载的，可以下载到电脑 / 删除）、下载队列、状态、扩展在不在线。"""
    def go():
        from core import modellib, store
        try:
            p = store.load(pid)
        except (FileNotFoundError, ValueError):
            raise ValueError("没有这个产品")
        try:
            lib = modellib.library(pid)
        except Exception:  # noqa: BLE001
            lib = {"items": []}
        cur = (p.get("model") or {}).get("lib_id")
        fs = [{"name": e["file"], "orig_name": e.get("orig_name") or e["file"], "bytes": e.get("bytes") or 0, "ext": e.get("ext") or "",
               "lib_id": e["id"], "current": e["id"] == cur, "dir": e.get("dir")} for e in lib.get("items") or [] if e.get("dir") == "source_files"]
        return {"files": fs, "queue": [r for r in watch.product_files(pid) if r["kind"] != "image" and r["state"] != "ok"],
                "status": watch.file_status(pid), "curate": (p.get("source") or {}).get("source") == "curate",
                "model": bool(p.get("model")), "source_url": (p.get("source") or {}).get("source_url") or "",
                "updated_at": p.get("updated_at") or 0, "inbox": bool(p.get("inbox"))}
    return _go(go)


@bp.post("/api/cur/products/<pid>/upload")
def cur_product_upload(pid):
    """「手动上传」模型文件（STL / 3MF / ZIP…）：进产品的模型库，和扩展上传的一样做 ERP 分析。"""
    if not auth.has_perm(g.user, "files.upload"):
        return _e("没有上传文件的权限（设置 → 账号与权限：上传文件）", 403)
    fs = request.files.getlist("file")
    if not fs:
        return _e("请选择文件")

    def go():
        out = [watch.manual_upload(pid, f.filename or "model.stl", f.stream, _who()) for f in fs[:20]]
        return {"saved": out, "status": watch.file_status(pid)}
    return _go(go)


@bp.post("/api/cur/products/<pid>/files/delete")
def cur_product_file_delete(pid):
    """删掉一个已下载的模型文件（挪到产品的 model_history，可以找回）；以后还能再从原站下载。"""
    if not auth.has_perm(g.user, "models.delete"):
        return _e("没有删除模型文件的权限", 403)
    name = str(_b().get("name") or "")

    def go():
        from core import modellib, store
        p = store.load(pid)
        modellib.library(pid)
        p = store.load(pid)
        e = next((x for x in p.get("model_lib") or [] if x.get("dir") == "source_files" and x["file"] == name), None)
        if not e:
            raise ValueError("没有这个文件")
        modellib.remove(pid, e["id"], _who())
        p = store.load(pid)
        p["source_files"] = [x for x in p.get("source_files") or [] if x.get("name") != name]
        store.save(p)
        c = db.conn()
        c.execute("UPDATE cur_files SET state='', stored='', updated_at=? WHERE product_id=? AND stored=? AND url<>''", (time.time(), pid, name))
        c.execute("DELETE FROM cur_files WHERE product_id=? AND stored=? AND url=''", (pid, name))
        c.commit()
        return {"status": watch.file_status(pid)}
    return _go(go)


@bp.get("/api/cur/inbox")
def cur_inbox():
    return _go(lambda: _strip(inbox.listing(request.args.to_dict())))


@bp.post("/api/cur/inbox/action")
def cur_inbox_action():
    """采集箱的操作：to_library 转入产品库 / delete 删除 / copy AI 写文案 / download 下载模型文件（ids 一个或多个产品编号）。"""
    b = _b()
    ids = [str(x) for x in b.get("ids") or []][:200]
    act = b.get("action") or ""

    def go():
        if not ids:
            raise ValueError("先勾选产品")
        if act == "to_library":
            return inbox.to_library(ids, _who())
        if act == "delete":
            if not auth.has_perm(g.user, "products.delete"):
                raise PermissionError
            return {"deleted": inbox.delete(ids, _who())}
        if act == "copy":
            return {"queued": inbox.queue_copy(ids)}
        if act == "download":
            n, re_read, errs = 0, 0, []
            for pid in ids:
                try:
                    r = watch.queue_download(pid)
                    n += r["queued"]
                    re_read += 1 if r["recollect"] else 0
                except ValueError as e:
                    errs.append(f"{pid}：{e}")
            return {"queued": n, "recollect": re_read, "errors": errs}
        raise ValueError("未知操作")
    try:
        return _go(go)
    except PermissionError:
        return _e("没有删除产品的权限（设置 → 账号与权限：删除产品）", 403)


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


@bp.post("/api/v1/curate/ext/download")
def ext_download():
    """扩展：模型网站详情页上「下载模型文件到 ERP」（已经采用过的模型）。"""
    b = _b()

    def go():
        url = sites.canonical(str(b.get("url") or ""))
        k = sites.source_key(url)
        r = db.conn().execute("SELECT product_id FROM cur_candidates WHERE skey=? AND product_id<>''", (k,)).fetchone() if k else None
        if not r:
            raise ValueError("这个模型还没采用：先点「＋ 采集」")
        return {"product_id": r["product_id"], **watch.queue_download(r["product_id"])}
    return _go(go)


@bp.get("/api/v1/curate/ext/queue")
def ext_queue():
    return _go(lambda: watch.collect_queue())


@bp.post("/api/v1/curate/ext/queue/action")
def ext_queue_action():
    b = _b()
    return _go(lambda: watch.collect_action(int(b.get("id") or 0), b.get("action") or ""))


@bp.get("/api/v1/curate/ext/next")
def ext_next():
    watch.note_ext(_who())
    return _go(lambda: watch.collect_next())


@bp.post("/api/v1/curate/ext/result")
def ext_result():
    b = _b()
    return _go(lambda: watch.collect_result(b, _who()))


@bp.get("/api/v1/curate/ext/files/next")
def ext_files_next():
    watch.note_ext(_who())
    return _go(lambda: watch.files_next())


@bp.post("/api/v1/curate/ext/files/<int:fid>/upload")
def ext_file_upload(fid):
    name = request.args.get("name") or ""
    return _go(lambda: watch.file_uploaded(fid, name, request.stream))


@bp.post("/api/v1/curate/ext/files/<int:fid>/progress")
def ext_file_progress(fid):
    """扩展 3.1.2：下载进度（也是心跳）。cancel = 任务被删掉 / 取消了，扩展停下这个下载。"""
    b = _b()
    return _go(lambda: watch.file_progress(fid, b.get("got"), b.get("total")))


@bp.post("/api/v1/curate/ext/files/<int:fid>/fail")
def ext_file_fail(fid):
    b = _b()
    return _go(lambda: watch.file_fail(fid, b))


@bp.get("/api/v1/curate/ext/watch/next")
def ext_watch_next():
    watch.note_ext(_who())
    return _go(lambda: watch.watch_next())


@bp.post("/api/v1/curate/ext/watch/result")
def ext_watch_result():
    b = _b()
    return _go(lambda: watch.watch_result(int(b.get("id") or 0), b.get("items") or [], b.get("error") or "",
                                          {"snippet": b.get("snippet"), "url": b.get("url"), "status": b.get("status")}))
