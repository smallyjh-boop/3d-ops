"""浏览器扩展的三件后台活：采集队列（读详情页）、模型文件下载（用浏览器里的登录状态下载，再上传到 ERP）、关注巡逻（读列表页）。
节奏和防风控（从「3D选品工具」pace.py 搬过来，v2.51.x / 扩展 3.1.2 改成两条线并行）：
  · 详情页、文件各一条线，每个网站各自：同时最多 conc 个（默认 2）、相邻两次开始之间随机隔几秒（标准档：详情页 4–12 秒、文件 8–20 秒）、
    每小时有上限（设置里能改）；每天巡逻页数有上限；
  · 一出现风控迹象（HTTP 429 / 403、人机验证、太频繁）就把这个平台减速一半并暂停 30 分钟（6 小时内再出现暂停 2 小时），
    采集、下载、巡逻一起停；之后一直顺利就慢慢提回原来的速度；也可以手动暂停 / 继续一个网站；
  · 领了活没交回（Chrome 关了、扩展后台被停）：详情页 4 分钟、文件 3 分钟没进度就放回队列，超时 3 次算失败；
  · 候选 / 产品草稿已删除的任务自动取消（不算失败）。
扩展 3.1.2 有活时一直领（没活或在等节奏时按服务器给的 wait 秒数睡，闹钟每分钟叫醒一次）；老扩展 3.1.1 每分钟问一次也照样能用（文件一次给一个）。
"""
import random
import re
import threading
import time
from urllib.parse import urlparse

from core.config import load_config

from . import db, sites

SPEEDS = {
    # v2.51.x（扩展 3.1.2）：详情页和文件分两条线、每个网站各自并行 2 个、节奏按「秒」算（以前一次只做一件、文件按产品成批 + 产品之间停 45–90 秒、每小时 30 个文件）。
    #          名称（中, 泰）                          文件间隔(秒)  详情页间隔(秒)  每网站每小时文件数  每网站每小时详情页数
    "slow": (("慢（最稳）", "ช้า (ปลอดภัยสุด)"), (15, 35), (10, 25), 60, 150),
    "normal": (("标准（推荐）", "มาตรฐาน (แนะนำ)"), (8, 20), (4, 12), 150, 400),
    "fast": (("快（容易被风控）", "เร็ว (เสี่ยงถูกบล็อก)"), (4, 10), (2, 6), 300, 800),
}
COLLECT_STALL = 240          # 详情页「正在读」超过 4 分钟没交回 = 扩展卡住 / 关掉了：放回队列重试
FILE_STALL = 180             # 文件下载 3 分钟没进度（扩展 3.1.2 每几秒报一次进度）= 卡住：放回队列重试
FILE_STALL_OLD = 600         # 不报进度的老扩展（3.1.1）：10 分钟
MAX_TRIES = 3                # 超时 / 中断 3 次就算失败（写清楚原因）
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


def pacing(cfg=None):
    """节奏（每个网站）：两条线（detail 详情页 / file 文件）各自的间隔（秒，随机）、同时几个、每小时上限。设置里可以改（0 / 空 = 按速度档位）。"""
    cfg = cfg or load_config()
    prof = SPEEDS[speed(cfg)]
    return {"detail": {"gap": prof[2], "conc": min(4, max(1, _i(cfg.get("cur_detail_conc"), 2))),
                       "cap": _i(cfg.get("cur_detail_hour_cap"), 0) or prof[4]},
            "file": {"gap": prof[1], "conc": min(4, max(1, _i(cfg.get("cur_dl_conc"), 2))),
                     "cap": _i(cfg.get("cur_dl_hour_cap"), 0) or prof[3]}}


# ---------------- 每个平台的节奏 / 暂停 ----------------
def _state():
    st = db.get("pace") or {}
    return st if isinstance(st, dict) else {}


def _plat(st, p):
    d = st.setdefault(p, {})
    for k, v in (("factor", 1.0), ("cooldown_until", 0), ("next_at", 0), ("hour_start", 0), ("hour_count", 0), ("risk_count", 0),
                 ("last_risk", 0), ("reason", ""), ("collect_next", 0), ("held", False), ("detail_hour", 0)):
        d.setdefault(k, v)
    if time.time() - d["hour_start"] >= 3600:
        d["hour_start"], d["hour_count"], d["detail_hour"] = time.time(), 0, 0
    return d


def paused(p):
    d = _plat(_state(), p)
    return d["cooldown_until"] if d["cooldown_until"] > time.time() else 0


def _blocked(d, p):
    """这个网站现在能不能派活：(原因, 暂停到) 或 ("", 0)。"""
    if d.get("held"):
        return f"{sites.name_of(p)} 已手动暂停", 0
    if d["cooldown_until"] > time.time():
        return (f"{sites.name_of(p)} 疑似风控暂停中（{d['reason'] or '原站要求验证 / 太频繁'}），到 "
                f"{time.strftime('%H:%M', time.localtime(d['cooldown_until']))} 自动继续"), d["cooldown_until"]
    return "", 0


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
    """「继续 / 恢复」：清掉暂停（风控暂停和手动暂停）和减速。"""
    with _lock:
        st = _state()
        for k in ([p] if p else list(st)):
            st.pop(k, None)
        db.put("pace", st)


def hold_site(p, on=True):
    """手动暂停 / 继续一个网站（采集、下载、巡逻一起）。继续 = 同时清掉风控暂停和减速。"""
    if p not in sites.load():
        raise ValueError("没有这个网站")
    if not on:
        return reset(p)
    with _lock:
        st = _state()
        _plat(st, p)["held"] = True
        db.put("pace", st)


def overview(cfg=None):
    st = _state()
    pc = pacing(cfg)
    out = []
    t0 = db.day_start()
    c = db.conn()
    cw = cfg_watch(cfg)
    now = time.time()
    for sid, s in sites.load().items():
        d = _plat(st, sid)
        f = max(1.0, d["factor"])
        cool = d["cooldown_until"] > now
        out.append({"key": sid, "name": s["name"], "paused": cool or bool(d.get("held")), "held": bool(d.get("held")),
                    "until": d["cooldown_until"] if cool else 0, "factor": d["factor"], "reason": d["reason"] if cool else "",
                    "hour_count": d["hour_count"], "cap": max(3, int(pc["file"]["cap"] / f)),
                    "detail_hour": d["detail_hour"], "detail_cap": max(3, int(pc["detail"]["cap"] / f)),
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
        q = c.execute("SELECT id, state, product_id FROM cur_collect WHERE skey=? AND hidden=0 ORDER BY id DESC LIMIT 1", (k,)).fetchone()
        if q and q["state"] in ("waiting", "running", "failed"):
            out[u] = {"state": q["state"], "item": q["id"], "product_id": q["product_id"]}
            continue
        m = c.execute("SELECT product_id FROM cur_candidates WHERE skey=? AND product_id<>''", (k,)).fetchone()
        if m:
            out[u] = {"state": "imported", "product_id": m["product_id"]}
    return out


def collect_queue():
    c = db.conn()
    act = [dict(r) for r in c.execute("SELECT * FROM cur_collect WHERE state IN ('waiting','running') AND hidden=0 "
                                      "ORDER BY state='running' DESC, prio DESC, pos, id LIMIT 50")]
    recent = [dict(r) for r in c.execute("SELECT * FROM cur_collect WHERE state NOT IN ('waiting','running') AND hidden=0 ORDER BY updated_at DESC LIMIT 10")]
    return {"active": act, "recent": recent, "paused": bool(db.get("collect_paused")), "waiting": sum(1 for r in act if r["state"] == "waiting")}


def collect_action(iid, action):
    """一个详情页任务的操作（扩展的采集队列面板、老页面用）。批量的在 job_action。"""
    if action in ("pause", "resume"):
        db.put("collect_paused", action == "pause")
        return collect_queue()
    if action not in ("cancel", "retry", "up"):
        raise ValueError("未知操作")
    job_action([f"c{iid}"], {"cancel": "delete"}.get(action, action))
    return collect_queue()


# ---------------- 任务是不是还有用（候选 / 产品删掉了就自动取消，不算失败） ----------------
def _product_alive(pid, cache):
    if pid not in cache:
        from core import store
        try:
            store.load(pid)
            cache[pid] = True
        except (FileNotFoundError, ValueError):
            cache[pid] = False
    return cache[pid]


def _dead_reason(c, r, cache):
    """详情页任务：候选 / 产品草稿已经删掉了 → 原因；还有用 → ""。"""
    if r["kind"] == "refresh":
        return "" if c.execute("SELECT 1 FROM cur_candidates WHERE skey=?", (r["skey"],)).fetchone() else "候选已删除，任务自动取消"
    if r["product_id"] and not _product_alive(r["product_id"], cache):
        return "产品草稿已删除，任务自动取消"
    return ""


def _drop_collect(c, r, why):
    """自动取消：只读候选的任务直接删掉；产品的任务标「已取消」并从队列里藏起来（产品的文案 / 整理标记还在这一行上）。"""
    if r["kind"] == "refresh" or not r["product_id"]:
        c.execute("DELETE FROM cur_collect WHERE id=?", (r["id"],))
    else:
        c.execute("UPDATE cur_collect SET state='canceled', hidden=1, held=0, message=?, updated_at=? WHERE id=?", (why, time.time(), r["id"]))


def cancel_orphans():
    """候选 / 产品草稿已删除的任务（详情页、文件下载）自动取消。「删除采集错误的」、清理、扩展来领活时都会做。返回取消了几个。"""
    c = db.conn()
    cache, n = {}, 0
    for r in c.execute("SELECT * FROM cur_collect WHERE state IN ('waiting','running','failed') OR (state='canceled' AND hidden=0)").fetchall():
        why = _dead_reason(c, r, cache)
        if why:
            _drop_collect(c, r, why)
            n += 1
    for (pid,) in c.execute("SELECT DISTINCT product_id FROM cur_files WHERE kind<>'image' AND state IN ('queued','downloading','failed')").fetchall():
        if not _product_alive(pid, cache):
            n += c.execute("DELETE FROM cur_files WHERE product_id=?", (pid,)).rowcount
    c.commit()
    return n


def cleanup():
    """「清理失败 / 无效任务」：已删除的候选 / 产品的任务取消；失败 / 已取消的详情页任务从队列里拿掉（候选的直接删）；
    失败的文件下载变回「没下载」（产品上还能点「⬇ 下载模型文件」重新排队）。返回 {orphans, collect, files}。"""
    n0 = cancel_orphans()
    c = db.conn()
    now = time.time()
    n1 = c.execute("DELETE FROM cur_collect WHERE state IN ('failed','canceled') AND (kind='refresh' OR product_id='')").rowcount
    n1 += c.execute("UPDATE cur_collect SET hidden=1, updated_at=? WHERE state IN ('failed','canceled') AND hidden=0", (now,)).rowcount
    n2 = c.execute("UPDATE cur_files SET state='', held=0, got=0, total=0, updated_at=? WHERE kind<>'image' AND state='failed'", (now,)).rowcount
    c.commit()
    return {"orphans": n0, "collect": n1, "files": n2}


# ---------------- 失败原因（说人话） ----------------
PLAIN = {"risk": "原站要人机验证 / 说请求太频繁：这个网站自动暂停，到时间自动继续（不用管）",
         "login": "原站要求登录：在装了扩展的 Chrome 里登录原站，再点「重试」",
         "missing": "原站上找不到了（可能被作者删掉或改成私密）",
         "timeout": "扩展读了 {n} 次都没读完（Chrome 关了、电脑睡了，或页面太慢）：可以点「重试」",
         "detail": "页面上没读到模型资料（可能没加载完或网站改版了）：可以点「重试」",
         "file": "下载失败：可以点「重试」"}


CODES = (("原站要人机验证", "risk"), ("原站要求登录", "login"), ("原站上找不到", "missing"), ("次都没读完", "timeout"), ("次都中断", "stall"),
         ("页面上没读到模型资料", "detail"), ("下载失败", "file"), ("上次读取超时", "retry"), ("上次下载中断", "retry"), ("等一下自动再试", "retry"),
         ("候选已删除", "gone"), ("产品草稿已删除", "gone"), ("已从队列删除", "removed"))


def reason_code(msg):
    """失败 / 等待原因 → 代码（页面按代码显示中文 / 泰文的白话；原文放在后面给懂的人看）。"""
    for k, v in CODES:
        if k in (msg or ""):
            return v
    return "other" if msg else ""


def reason_detail(msg):
    """原因后面括号里的原文（原站返回的错误等），给懂的人看；白话模板自己的括号不算。"""
    m = re.search(r"（([^（）]*)）$", msg or "")
    if not m or any(m.group(0) in v for v in PLAIN.values()):
        return ""
    return m.group(1)


def _plain(kind, raw, base="detail"):
    s = PLAIN.get(kind) or PLAIN[base]
    raw = str(raw or "").strip()
    return (s + (f"（{raw[:120]}）" if raw and kind == "other" else ""))[:300]


# ---------------- 领活（两条线：详情页 / 文件；每个网站各自的间隔、同时几个、每小时上限） ----------------
LANE = {}          # 扩展最近一次来领活时的情况（采集队列页上「扩展在做什么 / 为什么在等」）


def _note_lane(lane, reason, wait):
    LANE[lane] = {"at": time.time(), "reason": reason, "wait": wait}


def _release_stuck(c):
    """扩展领了活没交回（关了 Chrome、Service Worker 被停、卡住）：超时放回队列；超时 3 次算失败。"""
    now = time.time()
    for r in c.execute("SELECT id, tries FROM cur_collect WHERE state='running' AND started_at<?", (now - COLLECT_STALL,)).fetchall():
        if r["tries"] >= MAX_TRIES:
            c.execute("UPDATE cur_collect SET state='failed', message=?, updated_at=? WHERE id=?", (PLAIN["timeout"].format(n=r["tries"]), now, r["id"]))
        else:
            c.execute("UPDATE cur_collect SET state='waiting', message='上次读取超时，已放回队列重试', updated_at=? WHERE id=?", (now, r["id"]))
    for r in c.execute("SELECT id, tries FROM cur_files WHERE state='downloading' AND ((beat>0 AND beat<?) OR (beat=0 AND started_at<?))",
                       (now - FILE_STALL, now - FILE_STALL_OLD)).fetchall():
        if r["tries"] >= MAX_TRIES:
            c.execute("UPDATE cur_files SET state='failed', error=?, updated_at=? WHERE id=?",
                      (f"下载了 {r['tries']} 次都中断了（Chrome 关了、电脑睡了或网络断了）：可以点「重试」", now, r["id"]))
        else:
            c.execute("UPDATE cur_files SET state='queued', error='上次下载中断，已放回队列重试', got=0, total=0, updated_at=? WHERE id=?", (now, r["id"]))
    c.commit()


def _running_by_site(c, sql):
    out = {}
    for (u,) in c.execute(sql).fetchall():
        p = sites.platform(u) if "://" in str(u) else (u or "other")
        out[p] = out.get(p, 0) + 1
    return out


def collect_next(cfg=None):
    """扩展来领下一个要读的详情页。返回 {item, wait（秒，多久后再来领）, reason（为什么没给）}。
    顺序：优先级（高 / 普通 / 低）→ 队列位置 → 先来后到；每个网站最多同时读 conc 个、相邻两次开始之间随机隔 gap 秒（风控减速时乘系数）。"""
    cfg = cfg or load_config()
    if db.get("collect_paused"):
        _note_lane("detail", "采集队列已暂停", 0)
        return {"item": None, "wait": 0, "reason": "采集队列已暂停"}
    c = db.conn()
    _release_stuck(c)
    pc = pacing(cfg)["detail"]
    running = _running_by_site(c, "SELECT url FROM cur_collect WHERE state='running'")
    rows = c.execute("SELECT * FROM cur_collect WHERE state='waiting' AND held=0 AND hidden=0 ORDER BY prio DESC, pos, id LIMIT 80").fetchall()
    cache, pick, why, wait, skip = {}, None, "", 0, set()
    now = time.time()
    with _lock:
        st = _state()
        for r in rows:
            dead = _dead_reason(c, r, cache)
            if dead:
                _drop_collect(c, r, dead)
                continue
            p = sites.platform(r["url"])
            if p in skip:
                continue
            d = _plat(st, p)
            f = max(1.0, d["factor"])
            b, _until = _blocked(d, p)
            if b:
                why = b
                skip.add(p)
                continue
            if running.get(p, 0) >= pc["conc"]:
                why, wait = f"{sites.name_of(p)} 正在同时读 {running[p]} 个详情页", min(wait or 5, 5)
                skip.add(p)
                continue
            cap = max(3, int(pc["cap"] / f))
            if d["detail_hour"] >= cap:
                w = int(d["hour_start"] + 3600 - now) + 1
                why, wait = f"{sites.name_of(p)} 这个小时已读 {d['detail_hour']} 个详情页（上限 {cap}，设置里能改）", min(wait or w, w)
                skip.add(p)
                continue
            if d["collect_next"] > now:
                w = int(d["collect_next"] - now) + 1
                why, wait = f"{sites.name_of(p)} 按节奏等 {w} 秒", min(wait or w, w)
                skip.add(p)
                continue
            pick = r
            d["collect_next"] = now + random.uniform(*pc["gap"]) * f
            d["detail_hour"] += 1
            break
        db.put("pace", st)
    if not pick:
        c.commit()
        _note_lane("detail", why, wait)
        return {"item": None, "wait": wait, "reason": why}
    c.execute("UPDATE cur_collect SET state='running', started_at=?, tries=tries+1, updated_at=? WHERE id=?", (now, now, pick["id"]))
    c.commit()
    _note_lane("detail", "", 0)
    return {"item": {"id": pick["id"], "url": pick["url"], "title": pick["title"]}, "wait": 0, "reason": "", "conc": pc["conc"]}


def collect_result(body, who=""):
    """扩展交回一个详情页读到的东西 {id, data} 或 {id, error, snippet, status}：补进产品草稿。
    任务已经被删掉 / 取消了：不报错，忽略；候选 / 产品草稿已删除：自动取消（不算失败）。"""
    from . import adopt
    iid = _i(body.get("id"), 0)
    c = db.conn()
    q = c.execute("SELECT * FROM cur_collect WHERE id=?", (iid,)).fetchone()
    if not q or q["state"] == "canceled":
        return {"ok": True, "state": "ignored"}
    p = sites.platform(q["url"])
    now = time.time()
    dead = _dead_reason(c, q, {})
    if dead:
        _drop_collect(c, q, dead)
        c.commit()
        return {"ok": True, "state": "canceled"}
    data = body.get("data") if isinstance(body.get("data"), dict) else None
    if not data:
        kind, why = classify_failure(body)
        if kind == "risk":
            until = on_risk(p, why or str(body.get("error") or ""))
            msg = f"原站要人机验证 / 说请求太频繁：{sites.name_of(p)} 暂停到 {time.strftime('%H:%M', time.localtime(until))}，之后自动继续"
            c.execute("UPDATE cur_collect SET state='waiting', tries=MAX(0, tries-1), message=?, updated_at=? WHERE id=?", (msg, now, iid))
        else:
            msg = _plain(kind, str(body.get("error") or "") + (f"；{why}" if why else ""))
            c.execute("UPDATE cur_collect SET state='failed', message=?, updated_at=? WHERE id=?", (msg, now, iid))
        c.commit()
        return {"ok": True, "state": "failed", "kind": kind}
    if q["kind"] == "refresh" or not q["product_id"]:
        from . import cand
        ok = cand.refresh_from_detail(q["skey"], data)
        if ok:
            c.execute("UPDATE cur_collect SET state='done', message='', updated_at=? WHERE id=?", (now, iid))
        else:
            _drop_collect(c, q, "候选已删除，任务自动取消")
        c.commit()
        on_success(p)
        return {"ok": True, "state": "done" if ok else "canceled", "product_id": ""}
    ok = adopt.enrich(q["product_id"], data, who or q["who"])
    if ok:
        c.execute("UPDATE cur_collect SET state='done', message='', updated_at=? WHERE id=?", (now, iid))
    else:
        _drop_collect(c, q, "产品草稿已删除，任务自动取消")
    c.commit()
    on_success(p)
    from . import pipeline
    pipeline.kick()
    return {"ok": True, "state": "done" if ok else "canceled", "product_id": q["product_id"]}


# ---------------- 模型文件下载（扩展用浏览器登录状态下载，上传进产品的模型库） ----------------
FILE_ORDER = "prio DESC, CASE WHEN pos=0 THEN id ELSE pos END, id"


def files_next(cfg=None):
    """扩展来领下一个要下载的模型文件（一次一个；扩展 3.1.2 同时开几条下载）。
    返回 {product, files:[{id,url,name}], pacing, wait, reason}；没有能下载的：product = None、wait = 多久后再来（秒）。"""
    cfg = cfg or load_config()
    c = db.conn()
    _release_stuck(c)
    pc = pacing(cfg)["file"]
    running = _running_by_site(c, "SELECT platform FROM cur_files WHERE state='downloading'")
    rows = c.execute(f"SELECT * FROM cur_files WHERE state='queued' AND kind<>'image' AND held=0 ORDER BY {FILE_ORDER} LIMIT 80").fetchall()
    cache, pick, why, wait, skip = {}, None, "", 0, set()
    now = time.time()
    with _lock:
        st = _state()
        for r in rows:
            if r["product_id"] in skip:
                continue
            if not _product_alive(r["product_id"], cache):
                c.execute("DELETE FROM cur_files WHERE product_id=?", (r["product_id"],))
                skip.add(r["product_id"])
                continue
            p = r["platform"] or "other"
            if p in skip:
                continue
            d = _plat(st, p)
            f = max(1.0, d["factor"])
            b, _until = _blocked(d, p)
            if b:
                why = b
                skip.add(p)
                continue
            if running.get(p, 0) >= pc["conc"]:
                why, wait = f"{sites.name_of(p)} 正在同时下载 {running[p]} 个文件", min(wait or 5, 5)
                skip.add(p)
                continue
            cap = max(3, int(pc["cap"] / f))
            if d["hour_count"] >= cap:
                w = int(d["hour_start"] + 3600 - now) + 1
                why, wait = f"{sites.name_of(p)} 这个小时已下载 {d['hour_count']} 个文件（上限 {cap}，设置里能改）", min(wait or w, w)
                skip.add(p)
                continue
            if d["next_at"] > now:
                w = int(d["next_at"] - now) + 1
                why, wait = f"{sites.name_of(p)} 按节奏等 {w} 秒", min(wait or w, w)
                skip.add(p)
                continue
            pick = r
            d["hour_count"] += 1
            d["next_at"] = now + random.uniform(*pc["gap"]) * f
            break
        db.put("pace", st)
    if not pick:
        c.commit()
        _note_lane("file", why, wait)
        return {"product": None, "files": [], "wait": wait, "reason": why}
    c.execute("UPDATE cur_files SET state='downloading', started_at=?, beat=0, got=0, total=0, updated_at=?, tries=tries+1 WHERE id=?", (now, now, pick["id"]))
    c.commit()
    _note_lane("file", "", 0)
    return {"product": pick["product_id"], "files": [{"id": pick["id"], "url": pick["url"], "name": pick["name"]}],
            "pacing": {"file_gap": [0, 0], "platform": pick["platform"]}, "wait": 0, "reason": "", "conc": pc["conc"]}


def file_progress(fid, got, total=0):
    """扩展 3.1.2 下载时每几秒报一次进度（也是心跳：3 分钟没进度就算卡住）。返回 {cancel: 任务被删掉 / 取消了就停}。"""
    c = db.conn()
    now = time.time()
    n = c.execute("UPDATE cur_files SET got=?, total=?, beat=?, updated_at=? WHERE id=? AND state='downloading'",
                  (max(0, _i(got, 0)), max(0, _i(total, 0)), now, now, fid)).rowcount
    c.commit()
    return {"cancel": not n}


def file_fail(fid, body):
    c = db.conn()
    f = c.execute("SELECT * FROM cur_files WHERE id=?", (fid,)).fetchone()
    if not f or f["state"] != "downloading":
        return {"kind": "other", "stop": False, "message": "", "ignored": True}
    kind, why = classify_failure(body)
    now = time.time()
    raw = str(body.get("error") or "")
    if kind == "risk":
        until = on_risk(f["platform"], why or raw)
        msg = f"原站要人机验证 / 说请求太频繁：{sites.name_of(f['platform'])} 的下载、采集、巡逻暂停到 {time.strftime('%H:%M', time.localtime(until))}，之后自动继续"
        c.execute("UPDATE cur_files SET state='queued', tries=MAX(0, tries-1), error=?, got=0, total=0, updated_at=? WHERE id=?", (msg, now, fid))
    elif kind == "other" and f["tries"] < MAX_TRIES:
        msg = _plain(kind, raw + (f"；{why}" if why else ""), "file") + f"（第 {f['tries']} 次，等一下自动再试）"
        c.execute("UPDATE cur_files SET state='queued', error=?, got=0, total=0, updated_at=? WHERE id=?", (msg[:300], now, fid))
    else:
        msg = _plain(kind, raw + (f"；{why}" if why else ""), "file")
        c.execute("UPDATE cur_files SET state='failed', error=?, updated_at=? WHERE id=?", (msg[:300], now, fid))
    c.commit()
    return {"kind": kind, "stop": kind in ("risk", "login"), "message": msg}


def file_uploaded(fid, name, stream):
    """扩展下载好的文件：直接存进产品的模型库文件夹（source_files），登记到产品资料。"""
    from core import store
    from . import files, pipeline
    c = db.conn()
    f = c.execute("SELECT * FROM cur_files WHERE id=?", (fid,)).fetchone()
    if not f:
        raise ValueError("没有这个文件（任务已删除）")
    try:
        store.load(f["product_id"])
    except (FileNotFoundError, ValueError):
        c.execute("DELETE FROM cur_files WHERE product_id=?", (f["product_id"],))
        c.commit()
        raise ValueError("产品草稿已经删掉了")
    stored, n = files.save_to_product(f["product_id"], name or f["name"], stream)
    p = store.load(f["product_id"])
    p.setdefault("source_files", []).append({"name": stored, "bytes": n, "kind": files.kind_of(stored), "url": f["url"], "orig_name": f["name"],
                                             "added_at": time.time(), "added_by": "选品"})
    store.save(p)
    c.execute("UPDATE cur_files SET state='ok', stored=?, bytes=?, got=?, total=?, error='', updated_at=? WHERE id=?", (stored, n, n, n, time.time(), fid))
    c.execute("UPDATE cur_collect SET post=1 WHERE product_id=?", (f["product_id"],))
    c.commit()
    on_success(f["platform"])
    pipeline.kick()
    return {"ok": True, "bytes": n, "name": stored}


# ---------------- 采集队列管理（勾选、删除、优先级、排序、暂停 / 继续、重试） ----------------
JOB_STATES = {"detail": ("waiting", "running", "failed", "canceled"), "file": ("queued", "downloading", "failed")}


def jobs(args=None, limit=300):
    """采集队列里的任务（详情页 + 文件下载），id = c<编号> / f<编号>。args: lane=detail|file、site=平台、state=waiting|running|failed|held。
    排序 = 扩展领活的顺序（正在做的在最前，然后优先级 → 位置）。"""
    args = args or {}
    c = db.conn()
    out = []
    lane, site, state = args.get("lane") or "", args.get("site") or "", args.get("state") or ""
    now = time.time()
    if lane in ("", "detail"):
        for r in c.execute("SELECT * FROM cur_collect WHERE hidden=0 AND (state IN ('waiting','running','failed') OR (state='canceled' AND updated_at>?)) "
                           "ORDER BY state='running' DESC, state='failed', prio DESC, pos, id LIMIT ?", (now - 86400, limit)).fetchall():
            out.append({"id": f"c{r['id']}", "lane": "detail", "site": sites.platform(r["url"]), "title": r["title"] or r["url"], "url": r["url"],
                        "product_id": r["product_id"], "refresh": r["kind"] == "refresh", "state": r["state"], "held": bool(r["held"]), "prio": r["prio"],
                        "message": r["message"], "code": reason_code(r["message"]), "detail": reason_detail(r["message"]), "tries": r["tries"], "created_at": r["created_at"],
                        "secs": int(now - r["started_at"]) if r["state"] == "running" else 0})
    if lane in ("", "file"):
        for r in c.execute("SELECT f.*, COALESCE(k.title, '') ctitle FROM cur_files f LEFT JOIN cur_collect k ON k.id=(SELECT MAX(id) FROM cur_collect WHERE product_id=f.product_id) "
                           "WHERE f.kind<>'image' AND f.state IN ('queued','downloading','failed') ORDER BY f.state='downloading' DESC, f.state='failed', "
                           "f.prio DESC, CASE WHEN f.pos=0 THEN f.id ELSE f.pos END, f.id LIMIT ?", (limit,)).fetchall():
            out.append({"id": f"f{r['id']}", "lane": "file", "site": r["platform"] or "other", "title": r["name"], "url": r["url"], "product_id": r["product_id"],
                        "product_title": r["ctitle"], "state": r["state"], "held": bool(r["held"]), "prio": r["prio"], "message": r["error"], "code": reason_code(r["error"]), "detail": reason_detail(r["error"]), "tries": r["tries"],
                        "created_at": r["created_at"], "got": r["got"], "total": r["total"], "size": r["size_text"],
                        "secs": int(now - r["started_at"]) if r["state"] == "downloading" else 0})
    if site:
        out = [j for j in out if j["site"] == site]
    if state == "held":
        out = [j for j in out if j["held"]]
    elif state == "waiting":
        out = [j for j in out if j["state"] in ("waiting", "queued") and not j["held"]]
    elif state == "running":
        out = [j for j in out if j["state"] in ("running", "downloading")]
    elif state:
        out = [j for j in out if j["state"] == state]
    for j in out:
        j["site_name"] = sites.name_of(j["site"])
    return out


def _split(ids):
    cs, fs = [], []
    for x in ids or []:
        s = str(x)
        if s[:1] in ("c", "f") and s[1:].isdigit():
            (cs if s[0] == "c" else fs).append(int(s[1:]))
    return cs, fs


def _reorder(c, lane, sel, op, before=None):
    """调整扩展领活的顺序（等着的任务）：top 置顶 / bottom 置底 / up 提前 / down 推后 / move 拖到 before 前面。
    跨优先级移动时跟着改优先级（不然顺序不会变）。最后把位置重新编号。"""
    if lane == "detail":
        rows = [list(r) for r in c.execute("SELECT id, prio FROM cur_collect WHERE state='waiting' AND hidden=0 ORDER BY prio DESC, pos, id")]
    else:
        rows = [list(r) for r in c.execute(f"SELECT id, prio FROM cur_files WHERE state='queued' AND kind<>'image' ORDER BY {FILE_ORDER}")]
    sel = [r for r in rows if r[0] in set(sel)]
    if not sel:
        return 0
    ids = {r[0] for r in sel}
    rest = [r for r in rows if r[0] not in ids]
    if op == "top":
        top = max(r[1] for r in rows)
        for r in sel:
            r[1] = top
        rows = sel + rest
    elif op == "bottom":
        low = min(r[1] for r in rows)
        for r in sel:
            r[1] = low
        rows = rest + sel
    elif op in ("up", "down"):
        seq = rows if op == "up" else rows[::-1]
        for i in range(1, len(seq)):
            if seq[i][0] in ids and seq[i - 1][0] not in ids:
                seq[i][1] = seq[i - 1][1]
                seq[i - 1], seq[i] = seq[i], seq[i - 1]
        rows = seq if op == "up" else seq[::-1]
    elif op == "move":
        tgt = next((k for k, r in enumerate(rest) if r[0] == before), None)
        if tgt is None:
            prio = rest[-1][1] if rest else sel[0][1]
            rows = rest + sel
        else:
            prio = rest[tgt][1]
            rows = rest[:tgt] + sel + rest[tgt:]
        for r in sel:
            r[1] = prio
    tbl = "cur_collect" if lane == "detail" else "cur_files"
    c.executemany(f"UPDATE {tbl} SET pos=?, prio=? WHERE id=?", [(k + 1, r[1], r[0]) for k, r in enumerate(rows)])
    return len(sel)


def job_action(ids, action, prio=None, before=None):
    """采集队列的批量操作。ids = ["c12", "f34"…]。
    delete 删除（产品的下载任务只是取消这次下载，产品不动；产品的详情页任务标「已取消」藏起来；候选的重新读取任务直接删）
    retry 重试失败的 · hold 暂停这个任务 · resume 继续 · prio 设优先级（1 高 / 0 普通 / -1 低）· top / bottom / up / down / move（before = 拖到哪个任务前面）。
    返回 {n: 改了几个}。"""
    cs, fs = _split(ids)
    if not cs and not fs:
        raise ValueError("先勾选任务")
    c = db.conn()
    now = time.time()
    mk = lambda xs: ",".join("?" for _ in xs)  # noqa: E731
    n = 0
    if action == "delete":
        if cs:
            n += c.execute(f"DELETE FROM cur_collect WHERE id IN ({mk(cs)}) AND (kind='refresh' OR product_id='')", cs).rowcount
            n += c.execute(f"UPDATE cur_collect SET state=CASE WHEN state='done' THEN 'done' ELSE 'canceled' END, hidden=1, held=0, message='已从队列删除', updated_at=? "
                           f"WHERE id IN ({mk(cs)})", [now, *cs]).rowcount
        if fs:
            n += c.execute(f"UPDATE cur_files SET state='', held=0, got=0, total=0, error='', updated_at=? WHERE id IN ({mk(fs)}) AND state<>'ok'", [now, *fs]).rowcount
    elif action == "retry":
        if cs:
            n += c.execute(f"UPDATE cur_collect SET state='waiting', message='', tries=0, hidden=0, held=0, updated_at=? WHERE id IN ({mk(cs)}) "
                           f"AND state IN ('failed','canceled')", [now, *cs]).rowcount
        if fs:
            n += c.execute(f"UPDATE cur_files SET state='queued', error='', tries=0, held=0, got=0, total=0, updated_at=? WHERE id IN ({mk(fs)}) AND state IN ('failed','')",
                           [now, *fs]).rowcount
    elif action in ("hold", "resume"):
        v = 1 if action == "hold" else 0
        if cs:
            n += c.execute(f"UPDATE cur_collect SET held=? WHERE id IN ({mk(cs)})", [v, *cs]).rowcount
        if fs:
            n += c.execute(f"UPDATE cur_files SET held=? WHERE id IN ({mk(fs)})", [v, *fs]).rowcount
    elif action == "prio":
        v = max(-1, min(1, _i(prio, 0)))
        if cs:
            n += c.execute(f"UPDATE cur_collect SET prio=? WHERE id IN ({mk(cs)})", [v, *cs]).rowcount
        if fs:
            n += c.execute(f"UPDATE cur_files SET prio=? WHERE id IN ({mk(fs)})", [v, *fs]).rowcount
    elif action in ("top", "bottom", "up", "down", "move"):
        bc, bf = _split([before] if before else [])
        if cs:
            n += _reorder(c, "detail", cs, action, bc[0] if bc else None)
        if fs:
            n += _reorder(c, "file", fs, action, bf[0] if bf else None)
    else:
        raise ValueError("未知操作")
    c.commit()
    return {"n": n}


def queue_status(cfg=None):
    """采集队列页上面一行：现在的速度（个 / 分钟，最近 10 分钟）、还要多久（预计）、扩展在做什么、每条线为什么在等、每个网站的暂停。"""
    cfg = cfg or load_config()
    c = db.conn()
    now = time.time()
    win = 600

    def rate(sql):
        n, first = c.execute(sql, (now - win,)).fetchone()
        if not n:
            return 0.0, 0
        span = min(win, max(60.0, now - (first or now)))
        return round(n / (span / 60), 2), n

    det_rate, det_n = rate("SELECT COUNT(*), MIN(updated_at) FROM cur_collect WHERE state='done' AND updated_at>=?")
    file_rate, file_n = rate("SELECT COUNT(*), MIN(updated_at) FROM cur_files WHERE kind<>'image' AND state='ok' AND url<>'' AND updated_at>=?")
    det_left = {}
    for (u,) in c.execute("SELECT url FROM cur_collect WHERE state IN ('waiting','running') AND held=0 AND hidden=0"):
        p = sites.platform(u)
        det_left[p] = det_left.get(p, 0) + 1
    file_left = {r[0] or "other": r[1] for r in c.execute("SELECT platform, COUNT(*) FROM cur_files WHERE kind<>'image' AND state IN ('queued','downloading') "
                                                          "AND held=0 GROUP BY platform")}
    pc = pacing(cfg)
    st = _state()
    eta, blocked = 0.0, []
    for p in set(det_left) | set(file_left):
        d = _plat(st, p)
        f = max(1.0, d["factor"])
        b, until = _blocked(d, p)
        if b:
            blocked.append(p)
            if d.get("held"):
                continue
        # 预计：按节奏每分钟能做几个（每小时上限也算上）；扩展最近 10 分钟有实测速度就用实测的
        exp_d = min(60 / (sum(pc["detail"]["gap"]) / 2 * f), pc["detail"]["cap"] / f / 60)
        exp_f = min(60 / (sum(pc["file"]["gap"]) / 2 * f), pc["file"]["cap"] / f / 60)
        t = max(det_left.get(p, 0) / exp_d, file_left.get(p, 0) / exp_f) * 60 + max(0, until - now)
        eta = max(eta, t)
    nd, nf = sum(det_left.values()), sum(file_left.values())
    if det_rate or file_rate:
        meas = max(nd / det_rate * 60 if det_rate else 0, nf / file_rate * 60 if file_rate else 0)
        if meas:
            eta = meas if not eta else (eta + meas) / 2
    doing = [{"lane": "detail", "title": r["title"] or r["url"], "site_name": sites.name_of(sites.platform(r["url"])), "secs": int(now - r["started_at"])}
             for r in c.execute("SELECT * FROM cur_collect WHERE state='running' ORDER BY started_at LIMIT 8")]
    doing += [{"lane": "file", "title": r["name"], "site_name": sites.name_of(r["platform"]), "secs": int(now - r["started_at"]), "got": r["got"], "total": r["total"]}
              for r in c.execute("SELECT * FROM cur_files WHERE state='downloading' ORDER BY started_at LIMIT 8")]
    lanes = {k: {**v, "ago": int(now - v["at"])} for k, v in LANE.items() if now - v["at"] < 300}
    run_d = _running_by_site(c, "SELECT url FROM cur_collect WHERE state='running'")
    run_f = _running_by_site(c, "SELECT platform FROM cur_files WHERE state='downloading'")
    site_rows = []
    for p, s in sites.load().items():
        d = _plat(st, p)
        f = max(1.0, d["factor"])
        cool = d["cooldown_until"] > now
        site_rows.append({"key": p, "name": s["name"], "held": bool(d.get("held")), "until": d["cooldown_until"] if cool else 0, "reason": d["reason"] if cool else "",
                          "factor": d["factor"],
                          "detail": {"running": run_d.get(p, 0), "left": det_left.get(p, 0), "next_in": max(0, int(d["collect_next"] - now)),
                                     "hour": d["detail_hour"], "cap": max(3, int(pc["detail"]["cap"] / f)), "conc": pc["detail"]["conc"]},
                          "file": {"running": run_f.get(p, 0), "left": file_left.get(p, 0), "next_in": max(0, int(d["next_at"] - now)),
                                   "hour": d["hour_count"], "cap": max(3, int(pc["file"]["cap"] / f)), "conc": pc["file"]["conc"]}})
    return {"rate": {"detail": det_rate, "file": file_rate, "total": round(det_rate + file_rate, 2), "done_10m": det_n + file_n},
            "left": {"detail": nd, "file": nf}, "eta": int(eta) if (nd or nf) else 0, "doing": doing, "lanes": lanes,
            "pacing": pc, "speed": speed(cfg), "blocked": blocked, "paused": bool(db.get("collect_paused")), "sites": site_rows}


def queue_download(pid, ids=None, who=""):
    """「⬇ 下载模型文件」（采集队列、产品编辑页、产品 360、扩展的详情页按钮都用这个）：
    · 还没下载的 / 失败的模型文件 → 重新排队，等扩展下载；
    · 一个文件链接都还没有（详情页还没读到，或读的时候原站没给文件）→ 详情页重新进采集队列（扩展读到文件链接后自动排队下载）；
    · 文件都下载好了 → 也重新读一次详情页（原站可能加了新文件；已经下载过的不会重复下载）。
    返回 {queued: 排队的文件数, busy: 已经在排队 / 下载的, recollect: 是否重新读详情页, done: 已下载的文件数, state: queued|recollect|done}。"""
    from core import store
    try:
        p = store.load(pid)
    except (FileNotFoundError, ValueError):
        raise ValueError("没有这个产品")
    src = p.get("source") or {}
    if src.get("source") != "curate" or not src.get("source_url"):
        raise ValueError("这个产品不是从模型网站采用的，没有原站可以下载；请直接上传模型文件")
    c = db.conn()
    q = "UPDATE cur_files SET state='queued', error='', tries=0, held=0, updated_at=? WHERE product_id=? AND kind<>'image' AND state IN ('', 'failed')"
    args = [time.time(), pid]
    if ids:
        q += f" AND id IN ({','.join('?' for _ in ids)})"
        args += [int(x) for x in ids]
    n = c.execute(q, args).rowcount
    busy = c.execute("SELECT COUNT(*) FROM cur_files WHERE product_id=? AND kind<>'image' AND state IN ('queued','downloading')", (pid,)).fetchone()[0]
    ok = c.execute("SELECT COUNT(*) FROM cur_files WHERE product_id=? AND kind<>'image' AND state='ok'", (pid,)).fetchone()[0]
    re_read = False
    if not n and not busy and not ids:
        re_read = recollect_product(pid, src["source_url"], p.get("name_zh") or "", c=c)
    c.commit()
    from . import pipeline
    pipeline.kick()
    return {"queued": n, "busy": busy, "recollect": re_read, "done": ok, "state": "queued" if n or busy else "recollect" if re_read else "done"}


def recollect_product(pid, url, title="", c=None):
    """产品的详情页重新进采集队列（已经在排队的不重复加）。返回有没有加。"""
    c = c or db.conn()
    if c.execute("SELECT 1 FROM cur_collect WHERE product_id=? AND state IN ('waiting','running')", (pid,)).fetchone():
        return True
    pos = (c.execute("SELECT MIN(pos) FROM cur_collect").fetchone()[0] or 1) - 1          # 人点的：排到最前
    c.execute("INSERT INTO cur_collect(url, skey, title, who, product_id, pos, state, created_at, updated_at, copy) VALUES(?,?,?,?,?,?, 'waiting', ?, ?, 1)",
              (url, sites.source_key(url), title[:200], "", pid, pos, time.time(), time.time()))
    return True


def recollect_candidates(ids):
    """候选池「重新读取」：候选的详情页进采集队列（kind=refresh，不建产品），扩展读到后改正标题、作者、缩略图。返回排了几个。"""
    c = db.conn()
    n = 0
    for i in ids or []:
        r = c.execute("SELECT * FROM cur_candidates WHERE id=?", (int(i),)).fetchone()
        if not r or not r["url"]:
            continue
        if c.execute("SELECT 1 FROM cur_collect WHERE skey=? AND state IN ('waiting','running')", (r["skey"],)).fetchone():
            continue
        pos = (c.execute("SELECT MAX(pos) FROM cur_collect").fetchone()[0] or 0) + 1
        c.execute("INSERT INTO cur_collect(url, skey, title, thumb, who, product_id, pos, state, created_at, updated_at, copy, kind) "
                  "VALUES(?,?,?,?, '', '', ?, 'waiting', ?, ?, 1, 'refresh')", (r["url"], r["skey"], r["title"], r["thumb"], pos, time.time(), time.time()))
        c.execute("UPDATE cur_candidates SET refresh_at=? WHERE id=?", (time.time(), r["id"]))
        n += 1
    c.commit()
    return n


def manual_upload(pid, name, stream, who=""):
    """「手动上传」模型文件（STL / 3MF / ZIP…）：存进产品的 source_files，和扩展上传的一样做 ERP 分析（模型库、3D 模型、规格、克数 / 时长）。"""
    from core import store
    from . import files, pipeline
    try:
        store.load(pid)
    except (FileNotFoundError, ValueError):
        raise ValueError("没有这个产品")
    kind = files.kind_of(name)
    if kind not in files.MODEL_KINDS:
        raise ValueError("只能上传模型文件（STL / 3MF / OBJ / STEP / ZIP）")
    stored, n = files.save_to_product(pid, name, stream)
    p = store.load(pid)
    p.setdefault("source_files", []).append({"name": stored, "bytes": n, "kind": files.kind_of(stored), "url": "", "orig_name": name,
                                             "added_at": time.time(), "added_by": who or "手动上传"})
    src = p.setdefault("source", {})
    src["specs_done"] = False                          # 新文件：重新识别规格 / 克数（已经有人改过的变体不会被改）
    store.save(p)
    c = db.conn()
    c.execute("INSERT INTO cur_files(product_id, platform, name, url, kind, state, stored, bytes, created_at, updated_at) VALUES(?,?,?,?,?, 'ok', ?, ?, ?, ?)",
              (pid, sites.platform(src.get("source_url") or ""), stored, "", kind, stored, n, time.time(), time.time()))
    # post=3：马上整理（不等还在排队的原站下载——没开扩展时它们可能一直在等）
    if c.execute("UPDATE cur_collect SET post=3 WHERE id=(SELECT MAX(id) FROM cur_collect WHERE product_id=?)", (pid,)).rowcount == 0:
        c.execute("INSERT INTO cur_collect(url, skey, title, who, product_id, pos, state, post, created_at, updated_at, copy) VALUES(?,?,?,?,?,0,'done',3,?,?,1)",
                  (src.get("source_url") or "", src.get("source_id") or "", p.get("name_zh") or "", who[:60], pid, time.time(), time.time()))
    c.commit()
    pipeline.kick()
    return {"name": stored, "bytes": n}


def file_status(pid):
    """一个产品的模型文件状态（采集队列、编辑页、产品 360、采集箱用）：
    {ok, queued, downloading, failed, none(有链接没排队), links, collect(详情页状态), errors[], state, ext}"""
    c = db.conn()
    out = {"ok": 0, "queued": 0, "downloading": 0, "failed": 0, "none": 0}
    for r in c.execute("SELECT state, COUNT(*) n FROM cur_files WHERE product_id=? AND kind<>'image' GROUP BY state", (pid,)):
        out["none" if not r["state"] else r["state"]] = out.get(r["state"] or "none", 0) + r["n"]
    out["links"] = sum(out[k] for k in ("ok", "queued", "downloading", "failed", "none"))
    q = c.execute("SELECT state, message FROM cur_collect WHERE product_id=? AND hidden=0 ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    out["collect"] = q["state"] if q else ""
    out["collect_msg"] = q["message"] if q else ""
    out["errors"] = [r[0] for r in c.execute("SELECT DISTINCT error FROM cur_files WHERE product_id=? AND kind<>'image' AND state='failed' AND error<>'' LIMIT 3", (pid,))]
    out["state"] = ("downloading" if out["downloading"] else "queued" if out["queued"] else "failed" if out["failed"] and not out["ok"]
                    else "ok" if out["ok"] else "collect" if out["collect"] in ("waiting", "running") else "none")
    out["ext"] = ext_status()
    return out


# ---------------- 扩展在不在线 ----------------
_seen_mem = {}


def note_ext(who):
    """扩展来领活（/ext/next、/files/next、/watch/next）就记一下：装了扩展的 Chrome 开着、后台自动采集开着。30 秒最多写一次库。"""
    now = time.time()
    who = (who or "?")[:60]
    if now - _seen_mem.get(who, 0) < 30:
        return
    _seen_mem[who] = now
    d = db.get("ext_seen") or {}
    d = {k: v for k, v in d.items() if now - v < 7 * 86400}
    d[who] = now
    db.put("ext_seen", d)


EXT_ONLINE_SEC = 180


def ext_status():
    """{online, last, who:[在线的密钥名]}：3 分钟内有扩展来领过活就算在线（扩展每分钟问一次）。"""
    d = db.get("ext_seen") or {}
    now = time.time()
    on = sorted(k for k, v in d.items() if now - v < EXT_ONLINE_SEC)
    return {"online": bool(on), "last": max(d.values()) if d else 0, "who": on}


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
        b, _until = _blocked(d, w["platform"])
        if b:
            why = b
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
