"""浏览器扩展的三件后台活：采集队列（读详情页）、模型文件下载（用浏览器里的登录状态下载，再上传到 ERP）、关注巡逻（读列表页）。
节奏和防风控（从「3D选品工具」pace.py 搬过来）：
  · 页面之间、文件之间、产品之间都随机停一会儿；每个平台每小时下载有上限、每天巡逻页数有上限；
  · 一出现风控迹象（HTTP 429 / 403、人机验证、太频繁）就把这个平台减速一半并暂停 30 分钟（6 小时内再出现暂停 2 小时），
    采集、下载、巡逻一起停；之后一直顺利就慢慢提回原来的速度。
扩展每分钟问一次「有没有活」（/api/v1/curate/ext/next、/files/next、/watch/next），服务器按上面的规矩决定给不给。
"""
import random
import re
import threading
import time
from urllib.parse import urlparse

from core.config import load_config

from . import db, sites

SPEEDS = {
    #          名称（中, 泰）                          文件间隔(秒)  产品间隔(秒)  每平台每小时文件数  采集详情页间隔(秒)
    "slow": (("慢（最稳）", "ช้า (ปลอดภัยสุด)"), (15, 35), (120, 240), 15, (20, 40)),
    "normal": (("标准（推荐）", "มาตรฐาน (แนะนำ)"), (8, 20), (45, 90), 30, (10, 25)),
    "fast": (("快（容易被风控）", "เร็ว (เสี่ยงถูกบล็อก)"), (4, 10), (20, 45), 60, (5, 12)),
}
RISK_WORDS = re.compile(r"captcha|recaptcha|hcaptcha|turnstile|cf-chl|challenge-platform|just a moment|verify (?:you are|that you are) (?:a )?human|"
                        r"are you a robot|access denied|too many requests|rate.?limit|unusual traffic|请求过于频繁|操作频繁|人机验证|安全验证|滑动验证|访问受限", re.I)
LOGIN_WORDS = re.compile(r"\b(?:log ?in|sign ?in|login required|please log in)\b|登录|登入|เข้าสู่ระบบ", re.I)
MISSING_WORDS = re.compile(r"not found|no longer available|has been removed|deleted|不存在|已删除|已下架", re.I)
KINDS = {"designer": ("设计师", "นักออกแบบ"), "keyword": ("关键词", "คีย์เวิร์ด"), "url": ("搜索链接", "ลิงก์ค้นหา")}
FREQ = (24, 48, 168)
_lock = threading.Lock()


def _i(v, d):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return d


def cfg_watch(cfg=None):
    cfg = cfg or load_config()
    lo = max(1, _i(cfg.get("cur_watch_gap_min"), 3))
    return {"enabled": cfg.get("cur_watch_on", True) is not False, "daily_cap": max(1, _i(cfg.get("cur_watch_daily_cap"), 30)),
            "gap_min": lo, "gap_max": max(lo, _i(cfg.get("cur_watch_gap_max"), 8)), "min_score": _i(cfg.get("cur_alert_score"), 70)}


def speed(cfg=None):
    v = (cfg or load_config()).get("cur_dl_speed") or "normal"
    return v if v in SPEEDS else "normal"


# ---------------- 每个平台的节奏 / 暂停 ----------------
def _state():
    st = db.get("pace") or {}
    return st if isinstance(st, dict) else {}


def _plat(st, p):
    d = st.setdefault(p, {})
    for k, v in (("factor", 1.0), ("cooldown_until", 0), ("next_at", 0), ("hour_start", 0), ("hour_count", 0), ("risk_count", 0),
                 ("last_risk", 0), ("reason", ""), ("collect_next", 0)):
        d.setdefault(k, v)
    if time.time() - d["hour_start"] >= 3600:
        d["hour_start"], d["hour_count"] = time.time(), 0
    return d


def paused(p):
    d = _plat(_state(), p)
    return d["cooldown_until"] if d["cooldown_until"] > time.time() else 0


def on_success(p):
    with _lock:
        st = _state()
        d = _plat(st, p)
        if d["factor"] > 1.0:
            d["factor"] = max(1.0, round(d["factor"] * 0.95, 3))
            db.put("pace", st)


def on_risk(p, reason):
    """风控迹象：减速一半，暂停这个平台（6 小时内第二次起暂停 2 小时）。返回暂停到的时间。"""
    with _lock:
        st = _state()
        d = _plat(st, p)
        now = time.time()
        again = now - d["last_risk"] < 6 * 3600
        d["risk_count"] = d["risk_count"] + 1 if again else 1
        d["last_risk"] = now
        d["factor"] = min(4.0, round(d["factor"] * 2, 2))
        d["cooldown_until"] = now + (120 if again else 30) * 60
        d["reason"] = str(reason)[:120]
        db.put("pace", st)
        return d["cooldown_until"]


def reset(p=None):
    with _lock:
        st = _state()
        for k in ([p] if p else list(st)):
            st.pop(k, None)
        db.put("pace", st)


def overview(cfg=None):
    st = _state()
    prof = SPEEDS[speed(cfg)]
    out = []
    t0 = db.day_start()
    c = db.conn()
    cw = cfg_watch(cfg)
    for sid, s in sites.load().items():
        d = _plat(st, sid)
        out.append({"key": sid, "name": s["name"], "paused": d["cooldown_until"] > time.time(), "until": d["cooldown_until"],
                    "factor": d["factor"], "hour_count": d["hour_count"], "cap": max(3, int(prof[3] / d["factor"])), "reason": d["reason"],
                    "pages_today": c.execute("SELECT COUNT(*) FROM cur_watch_log WHERE platform=? AND ts>=?", (sid, t0)).fetchone()[0],
                    "daily_cap": cw["daily_cap"]})
    return out


def classify_failure(info, cfg=None):
    """失败原因：risk 风控 / login 要登录 / missing 文件没了 / other。规则看不出来、又有 AI 时问 AI。返回 (类型, 说明)。"""
    status = _i(info.get("status"), 0)
    text = f"{info.get('error') or ''}\n{info.get('snippet') or ''}"
    if status == 429 or RISK_WORDS.search(text):
        return "risk", "原站要求人机验证或提示请求太频繁"
    if status == 401 or (status == 403 and LOGIN_WORDS.search(text)):
        return "login", "原站要求登录"
    if status in (404, 410) or (MISSING_WORDS.search(text) and not LOGIN_WORDS.search(text)):
        return "missing", "原站上找不到这个文件"
    if status == 403:
        return "risk", "原站拒绝访问（HTTP 403）"
    from .cand import ai_json, ai_on
    cfg = cfg or load_config()
    if info.get("snippet") and ai_on(cfg):
        try:
            out = ai_json(cfg, "你在帮 3D 模型下载程序判断失败原因。判断属于哪一类：risk = 风控（人机验证、请求太频繁、访问被限制）；"
                               "login = 需要登录或权限；missing = 文件不存在或已删除；other = 其他。只输出 JSON：{\"kind\":\"risk|login|missing|other\",\"reason\":\"一句中文\"}",
                          {"status": status, "url": str(info.get("url") or "")[:300], "page": str(info.get("snippet") or "")[:1500]})
            k = str(out.get("kind") or "other")
            return (k if k in ("risk", "login", "missing") else "other"), "AI 判断：" + str(out.get("reason") or "")[:100]
        except Exception:  # noqa: BLE001
            pass
    return "other", ""


# ---------------- 采集队列（采用的模型等扩展读详情页） ----------------
def collect_add(items, who=""):
    """列表页 / 详情页点「＋采集」或候选池点「采用」= 马上建产品草稿 + 详情页进采集队列。返回 {added, skipped:{url: 原因}, products}。"""
    from . import adopt
    r = adopt.adopt(items, who)
    return {"added": len(r["added"]), "skipped": r["skipped"], "products": r["added"]}


def collect_states(urls):
    """{原链接: {state, product_id}}：已采用 imported / 排队 waiting / running / failed。"""
    c = db.conn()
    out = {}
    for u in (urls or [])[:200]:
        k = sites.source_key(sites.canonical(str(u)))
        if not k:
            continue
        q = c.execute("SELECT id, state, product_id FROM cur_collect WHERE skey=? ORDER BY id DESC LIMIT 1", (k,)).fetchone()
        if q and q["state"] in ("waiting", "running", "failed"):
            out[u] = {"state": q["state"], "item": q["id"], "product_id": q["product_id"]}
            continue
        m = c.execute("SELECT product_id FROM cur_candidates WHERE skey=? AND product_id<>''", (k,)).fetchone()
        if m:
            out[u] = {"state": "imported", "product_id": m["product_id"]}
    return out


def collect_queue():
    c = db.conn()
    act = [dict(r) for r in c.execute("SELECT * FROM cur_collect WHERE state IN ('waiting','running') ORDER BY state='running' DESC, pos LIMIT 50")]
    recent = [dict(r) for r in c.execute("SELECT * FROM cur_collect WHERE state NOT IN ('waiting','running') ORDER BY updated_at DESC LIMIT 10")]
    return {"active": act, "recent": recent, "paused": bool(db.get("collect_paused")), "waiting": sum(1 for r in act if r["state"] == "waiting")}


def collect_action(iid, action):
    c = db.conn()
    if action in ("pause", "resume"):
        db.put("collect_paused", action == "pause")
    elif action == "cancel":
        c.execute("UPDATE cur_collect SET state='canceled', updated_at=? WHERE id=? AND state IN ('waiting','running')", (time.time(), iid))
    elif action == "retry":
        c.execute("UPDATE cur_collect SET state='waiting', message='', updated_at=? WHERE id=? AND state IN ('failed','canceled')", (time.time(), iid))
    elif action == "up":
        r = c.execute("SELECT pos FROM cur_collect WHERE id=?", (iid,)).fetchone()
        p = c.execute("SELECT id, pos FROM cur_collect WHERE state='waiting' AND pos<? ORDER BY pos DESC LIMIT 1", (r["pos"] if r else 0,)).fetchone()
        if r and p:
            c.execute("UPDATE cur_collect SET pos=? WHERE id=?", (p["pos"], iid))
            c.execute("UPDATE cur_collect SET pos=? WHERE id=?", (r["pos"], p["id"]))
    else:
        raise ValueError("未知操作")
    c.commit()
    return collect_queue()


def collect_next(cfg=None):
    """扩展来领下一个要读的详情页。返回 {item, wait, reason}。"""
    cfg = cfg or load_config()
    if db.get("collect_paused"):
        return {"item": None, "wait": 0, "reason": "已暂停"}
    c = db.conn()
    c.execute("UPDATE cur_collect SET state='waiting' WHERE state='running' AND started_at<?", (time.time() - 600,))
    rows = c.execute("SELECT * FROM cur_collect WHERE state='waiting' ORDER BY pos LIMIT 20").fetchall()
    if not rows:
        c.commit()
        return {"item": None, "wait": 0, "reason": ""}
    with _lock:
        st = _state()
        why, pick, wait = "", None, 0
        for r in rows:
            p = sites.platform(r["url"])
            d = _plat(st, p)
            if d["cooldown_until"] > time.time():
                why = f"{sites.name_of(p)} 疑似风控暂停中"
                continue
            if d["collect_next"] > time.time():
                wait = int(d["collect_next"] - time.time()) + 1
                why = "按页面间隔等待"
                continue
            pick = r
            d["collect_next"] = time.time() + random.uniform(*SPEEDS[speed(cfg)][4]) * d["factor"]
            break
        db.put("pace", st)
    if not pick:
        c.commit()
        return {"item": None, "wait": wait, "reason": why}
    c.execute("UPDATE cur_collect SET state='running', started_at=?, tries=tries+1, updated_at=? WHERE id=?", (time.time(), time.time(), pick["id"]))
    c.commit()
    return {"item": {"id": pick["id"], "url": pick["url"], "title": pick["title"]}, "wait": 0, "reason": ""}


def collect_result(body, who=""):
    """扩展交回一个详情页读到的东西 {id, data} 或 {id, error, snippet, status}：补进产品草稿。"""
    from . import adopt
    iid = _i(body.get("id"), 0)
    c = db.conn()
    q = c.execute("SELECT * FROM cur_collect WHERE id=?", (iid,)).fetchone()
    if not q:
        raise ValueError("采集队列里没有这一项")
    p = sites.platform(q["url"])
    data = body.get("data") if isinstance(body.get("data"), dict) else None
    if not data:
        kind, why = classify_failure(body)
        msg = (str(body.get("error") or "页面上没读到产品信息"))[:200] + (f"（{why}）" if why else "")
        if kind == "risk":
            on_risk(p, why or msg)
        c.execute("UPDATE cur_collect SET state=?, message=?, updated_at=? WHERE id=?", ("waiting" if kind == "risk" else "failed", msg, time.time(), iid))
        c.commit()
        return {"ok": True, "state": "failed", "kind": kind}
    ok = adopt.enrich(q["product_id"], data, who or q["who"])
    c.execute("UPDATE cur_collect SET state=?, message=?, updated_at=? WHERE id=?",
              ("done" if ok else "failed", "" if ok else "产品草稿已经删掉了", time.time(), iid))
    c.commit()
    on_success(p)
    from . import pipeline
    pipeline.kick()
    return {"ok": True, "state": "done" if ok else "failed", "product_id": q["product_id"]}


# ---------------- 模型文件下载（扩展用浏览器登录状态下载，上传进产品的模型库） ----------------
def files_next(cfg=None):
    """扩展来领下一个产品的模型文件。返回 {product, files:[{id,url,name}], pacing} 或 {product: None, reason}。"""
    cfg = cfg or load_config()
    c = db.conn()
    c.execute("UPDATE cur_files SET state='queued' WHERE state='downloading' AND updated_at<?", (time.time() - 1800,))
    c.commit()
    rows = c.execute("SELECT product_id, platform FROM cur_files WHERE state='queued' GROUP BY product_id ORDER BY MIN(updated_at) LIMIT 20").fetchall()
    prof = SPEEDS[speed(cfg)]
    why = ""
    for r in rows:
        p = r["platform"] or "other"
        with _lock:
            st = _state()
            d = _plat(st, p)
            if d["cooldown_until"] > time.time():
                why = f"{sites.name_of(p)} 疑似风控暂停中"
                continue
            if d["next_at"] > time.time():
                why = f"按节奏等待 {int(d['next_at'] - time.time())} 秒"
                continue
            fs = c.execute("SELECT id, url, name FROM cur_files WHERE product_id=? AND state='queued' ORDER BY id LIMIT 30", (r["product_id"],)).fetchall()
            cap = max(3, int(prof[3] / d["factor"]))
            if d["hour_count"] and d["hour_count"] + len(fs) > cap:
                why = f"这个小时已下载 {d['hour_count']} 个文件（上限 {cap}）"
                continue
            f = d["factor"]
            d["hour_count"] += len(fs)
            d["next_at"] = time.time() + len(fs) * sum(prof[1]) / 2 * f + random.uniform(*prof[2]) * f
            db.put("pace", st)
        c.executemany("UPDATE cur_files SET state='downloading', updated_at=?, tries=tries+1 WHERE id=?", [(time.time(), x["id"]) for x in fs])
        c.commit()
        return {"product": r["product_id"], "files": [dict(x) for x in fs],
                "pacing": {"file_gap": [round(prof[1][0] * f, 1), round(prof[1][1] * f, 1)], "platform": p}}
    return {"product": None, "reason": why}


def file_fail(fid, body):
    c = db.conn()
    f = c.execute("SELECT * FROM cur_files WHERE id=?", (fid,)).fetchone()
    if not f:
        raise ValueError("没有这个文件")
    kind, why = classify_failure(body)
    msg = (str(body.get("error") or "下载失败"))[:200] + (f"（{why}）" if why else "")
    stop = kind in ("risk", "login")
    if kind == "risk":
        until = on_risk(f["platform"], why or msg)
        msg += "，这个平台的下载、采集、巡逻暂停到 " + time.strftime("%H:%M", time.localtime(until))
        c.execute("UPDATE cur_files SET state='queued', error=? WHERE product_id=? AND state='downloading'", (msg[:300], f["product_id"]))
    else:
        c.execute("UPDATE cur_files SET state='failed', error=?, updated_at=? WHERE id=?", (msg[:300], time.time(), fid))
        if stop:
            c.execute("UPDATE cur_files SET state='failed', error=?, updated_at=? WHERE product_id=? AND state='downloading'",
                      ("原站要求登录：在这台电脑的浏览器里登录原站后点「重新下载」", time.time(), f["product_id"]))
    c.commit()
    return {"kind": kind, "stop": stop, "message": msg}


def file_uploaded(fid, name, stream):
    """扩展下载好的文件：直接存进产品的模型库文件夹（source_files），登记到产品资料。"""
    from core import store
    from . import files, pipeline
    c = db.conn()
    f = c.execute("SELECT * FROM cur_files WHERE id=?", (fid,)).fetchone()
    if not f:
        raise ValueError("没有这个文件")
    try:
        store.load(f["product_id"])
    except (FileNotFoundError, ValueError):
        c.execute("UPDATE cur_files SET state='failed', error='产品已删除' WHERE id=?", (fid,))
        c.commit()
        raise ValueError("产品草稿已经删掉了")
    stored, n = files.save_to_product(f["product_id"], name or f["name"], stream)
    p = store.load(f["product_id"])
    p.setdefault("source_files", []).append({"name": stored, "bytes": n, "kind": files.kind_of(stored), "url": f["url"], "orig_name": f["name"],
                                             "added_at": time.time(), "added_by": "选品"})
    store.save(p)
    c.execute("UPDATE cur_files SET state='ok', stored=?, bytes=?, error='', updated_at=? WHERE id=?", (stored, n, time.time(), fid))
    c.execute("UPDATE cur_collect SET post=1 WHERE product_id=?", (f["product_id"],))
    c.commit()
    on_success(f["platform"])
    pipeline.kick()
    return {"ok": True, "bytes": n, "name": stored}


def queue_download(pid, ids=None):
    """「重新下载」：失败的 / 还没下载的模型文件重新排队。"""
    c = db.conn()
    q = "UPDATE cur_files SET state='queued', error='', updated_at=? WHERE product_id=? AND kind<>'image' AND state IN ('', 'failed')"
    args = [time.time(), pid]
    if ids:
        q += f" AND id IN ({','.join('?' for _ in ids)})"
        args += [int(x) for x in ids]
    n = c.execute(q, args).rowcount
    c.commit()
    return n


def product_files(pid):
    return [dict(r) for r in db.conn().execute("SELECT id, name, url, kind, state, error, size_text, stored FROM cur_files WHERE product_id=? "
                                               "ORDER BY kind='image', id", (pid,))]


# ---------------- 关注巡逻 ----------------
def watch_url(kind, site, value):
    value = (value or "").strip()
    if not value:
        raise ValueError("请填写要关注的内容")
    if kind == "keyword":
        if len(value) > 80:
            raise ValueError("关键词太长了")
        url = sites.search_url(site, value)
    else:
        try:
            p = urlparse(value)
        except ValueError:
            raise ValueError("链接格式不对")
        if p.scheme != "https" or not sites.site_for_url(value):
            raise ValueError("只支持这些模型网站的 https 链接：" + "、".join(s["name"] for s in sites.load().values()))
        if sites.canonical(value):
            raise ValueError("这是单个模型的详情页。请填设计师主页、搜索结果页或分类页的链接")
        url = value[:1000]
    return sites.platform(url), url


def add(f, who=""):
    kind = f.get("kind") if f.get("kind") in KINDS else "url"
    plat, url = watch_url(kind, f.get("site", ""), f.get("value", ""))
    freq = _i(f.get("freq_hours"), 24)
    freq = freq if freq in FREQ else 24
    scrolls = min(3, max(1, _i(f.get("scrolls"), 1)))
    label = (f.get("label") or "").strip()[:60] or (f.get("value", "").strip()[:60] if kind == "keyword"
                                                     else (urlparse(url).path.strip("/").split("/")[-1] or urlparse(url).hostname)[:60])
    c = db.conn()
    if c.execute("SELECT 1 FROM cur_watches WHERE url=?", (url,)).fetchone():
        raise ValueError("这个已经在关注列表里了")
    cur = c.execute("INSERT INTO cur_watches(kind, platform, value, url, label, freq_hours, scrolls, enabled, source, next_run, created_by, created_at) "
                    "VALUES(?,?,?,?,?,?,?,1,?,?,?,?)", (kind, plat, f.get("value", "").strip()[:200], url, label, freq, scrolls,
                                                         f.get("source") or "manual", time.time(), who[:60], time.time()))
    c.commit()
    return {"id": cur.lastrowid, "label": label, "platform": plat, "url": url}


def update(wid, f):
    c = db.conn()
    w = c.execute("SELECT * FROM cur_watches WHERE id=?", (wid,)).fetchone()
    if not w:
        raise ValueError("没有这个关注")
    if f.get("delete"):
        c.execute("DELETE FROM cur_watches WHERE id=?", (wid,))
    elif f.get("run"):
        c.execute("UPDATE cur_watches SET next_run=?, enabled=1, running_at=0 WHERE id=?", (time.time(), wid))
    else:
        if "enabled" in f:
            c.execute("UPDATE cur_watches SET enabled=? WHERE id=?", (1 if f["enabled"] else 0, wid))
        if "freq_hours" in f and _i(f["freq_hours"], 0) in FREQ:
            c.execute("UPDATE cur_watches SET freq_hours=? WHERE id=?", (_i(f["freq_hours"], 24), wid))
        if f.get("label"):
            c.execute("UPDATE cur_watches SET label=? WHERE id=?", (str(f["label"])[:60], wid))
    c.commit()


def board(cfg=None):
    cfg = cfg or load_config()
    c = db.conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM cur_watches ORDER BY enabled DESC, total_new DESC, id")]
    adopted = {r[0]: r[1] for r in c.execute("SELECT c.watch_id, COUNT(*) FROM cur_candidates c WHERE c.watch_id>0 AND c.product_id<>'' GROUP BY c.watch_id")}
    for r in rows:
        r["adopted"] = adopted.get(r["id"], 0)
        r["platform_name"] = sites.name_of(r["platform"])
    t0 = db.day_start()
    log = [dict(r) for r in c.execute("SELECT l.*, w.label FROM cur_watch_log l LEFT JOIN cur_watches w ON w.id=l.watch_id ORDER BY l.id DESC LIMIT 30")]
    days = []
    for i in range(13, -1, -1):
        a = t0 - i * 86400
        n = c.execute("SELECT COALESCE(SUM(new),0) FROM cur_watch_log WHERE ts>=? AND ts<?", (a, a + 86400)).fetchone()[0]
        days.append({"day": time.strftime("%m-%d", time.localtime(a + 7 * 3600)), "new": n})
    return {"rows": rows, "cfg": cfg_watch(cfg), "pace": overview(cfg), "speed": speed(cfg), "speeds": {k: v[0] for k, v in SPEEDS.items()},
            "kinds": {k: v for k, v in KINDS.items()}, "search": [{"id": a, "name": b} for a, b, _u in sites.search_entries()], "log": log, "days": days,
            "new_today": c.execute("SELECT COUNT(*) FROM cur_candidates WHERE new_at>=? AND excluded=''", (t0,)).fetchone()[0],
            "collect": collect_queue(),
            "files_waiting": c.execute("SELECT COUNT(*) FROM cur_files WHERE state IN ('queued','downloading')").fetchone()[0]}


def watch_next(cfg=None):
    """扩展来领下一个要巡逻的列表页。返回 {watch, wait, reason}。"""
    cw = cfg_watch(cfg)
    if not cw["enabled"]:
        return {"watch": None, "wait": 0, "reason": "关注巡逻已关闭"}
    c = db.conn()
    c.execute("UPDATE cur_watches SET running_at=0 WHERE running_at>0 AND running_at<?", (time.time() - 600,))
    c.commit()
    rows = c.execute("SELECT * FROM cur_watches WHERE enabled=1 AND running_at=0 AND next_run<=? ORDER BY next_run, id", (time.time(),)).fetchall()
    if not rows:
        return {"watch": None, "wait": 0, "reason": ""}
    nxt = db.get("watch_next_at") or 0
    if nxt > time.time():
        return {"watch": None, "wait": int(nxt - time.time()) + 1, "reason": "按页面间隔等待"}
    st = _state()
    pick, why = None, ""
    t0 = db.day_start()
    for w in rows:
        d = _plat(st, w["platform"])
        if d["cooldown_until"] > time.time():
            why = f"{sites.name_of(w['platform'])} 疑似风控暂停中"
            continue
        n = c.execute("SELECT COUNT(*) FROM cur_watch_log WHERE platform=? AND ts>=?", (w["platform"], t0)).fetchone()[0]
        if n >= cw["daily_cap"]:
            why = f"{sites.name_of(w['platform'])} 今天已巡逻 {n} 页（上限 {cw['daily_cap']}）"
            continue
        pick = w
        break
    if not pick:
        return {"watch": None, "wait": 0, "reason": why}
    c.execute("UPDATE cur_watches SET running_at=? WHERE id=?", (time.time(), pick["id"]))
    c.commit()
    factor = max(1.0, _plat(st, pick["platform"])["factor"])
    db.put("watch_next_at", time.time() + random.uniform(cw["gap_min"], cw["gap_max"]) * 60 * factor)
    return {"watch": {"id": pick["id"], "url": pick["url"], "scrolls": pick["scrolls"], "label": pick["label"]}, "wait": 0, "reason": ""}


def watch_result(wid, items, error="", info=None):
    """扩展交回一个列表页的卡片：第一次只记下已有的（不算新品），以后新出现的标「新品」，都进候选池打分。"""
    from . import cand
    c = db.conn()
    w = c.execute("SELECT * FROM cur_watches WHERE id=?", (wid,)).fetchone()
    if not w:
        raise ValueError("没有这个关注")
    items = [it for it in (items or []) if isinstance(it, dict) and sites.canonical(str(it.get("url") or ""))][:80]
    if error or not items:
        kind, why = classify_failure({**(info or {}), "error": error or "列表页上没读到模型"})
        msg = (error or "列表页上没读到模型（可能要登录、验证，或页面结构变了）") + (f"（{why}）" if why else "")
        retry = 2 * 3600
        if kind == "risk":
            until = on_risk(w["platform"], why or msg)
            retry = max(600, until - time.time())
            msg += "，这个平台的巡逻、采集和下载暂停到 " + time.strftime("%H:%M", time.localtime(until))
        c.execute("UPDATE cur_watches SET running_at=0, last_run=?, last_error=?, next_run=? WHERE id=?", (time.time(), msg[:300], time.time() + retry, wid))
        c.execute("INSERT INTO cur_watch_log(ts, watch_id, platform, error) VALUES(?,?,?,?)", (time.time(), wid, w["platform"], msg[:300]))
        c.commit()
        return {"ok": True, "found": 0, "new": 0, "kind": kind}
    keys = {}
    for it in items:
        k = sites.source_key(sites.canonical(str(it.get("url"))))
        if k:
            keys[k] = it
    marks = ",".join("?" for _ in keys)
    known = {r[0] for r in c.execute(f"SELECT skey FROM cur_candidates WHERE skey IN ({marks})", list(keys))}
    fresh = [k for k in keys if k not in known]
    cand.upsert(list(keys.values()), f"巡逻：{w['label']}", watch_id=wid)
    baseline = w["runs"] == 0
    n_new = 0 if baseline else len(fresh)
    if fresh and not baseline:
        c.execute(f"UPDATE cur_candidates SET new_at=?, watch_id=? WHERE skey IN ({','.join('?' for _ in fresh)})", [time.time(), wid, *fresh])
    jitter = random.uniform(-0.1, 0.1) * w["freq_hours"]
    c.execute("UPDATE cur_watches SET running_at=0, runs=runs+1, last_run=?, next_run=?, last_found=?, last_new=?, total_new=total_new+?, last_error='' "
              "WHERE id=?", (time.time(), time.time() + (w["freq_hours"] + jitter) * 3600, len(keys), n_new, n_new, wid))
    c.execute("INSERT INTO cur_watch_log(ts, watch_id, platform, found, new) VALUES(?,?,?,?,?)", (time.time(), wid, w["platform"], len(keys), n_new))
    c.commit()
    on_success(w["platform"])
    return {"ok": True, "found": len(keys), "new": n_new, "baseline": baseline}
