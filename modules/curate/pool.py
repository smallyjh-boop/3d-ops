"""候选池的自动分组、清理和回收站（v2.53）。

自动分组（按候选现算，不存；点哪个就筛哪个）：
  进度（互斥）  new 新发现 · seen 已看未处理 · later 稍后看 · adopted 已采用（进了采集箱 / 产品库）· ignored 已忽略 · excluded 规则排除
  顶部          top:todo 待看（新发现 + 已看未处理）· top:hi 高分待看 · top:done 已处理（已采用 + 已忽略）
  分数段 sc:high/mid/low · 来源网站 site:* · 关注巡逻 wt:<编号> / wt:none · 类目 ct:*
忽略过的永远不会回来：候选行一直留着，再看到也不改状态；就算被清理掉，指纹（skey）留在 cur_gone，不会再存。

清理（预览 → 勾选 → 执行）：每一类先给个数 + 能腾出多少 MB；清掉的进回收站 7 天（能恢复），到期删除，只留指纹。
  excl 规则排除超过 N 天 · low 低分（< N）且 N 天没再看到 · ignored 已忽略超过 N 天 · adopted 已采用（已经在采集箱 / 产品库）·
  dup 重复（同作者同标题 → 合并成一个，留数据最好的）· watchdel 来自已删除的关注巡逻
每天自动清理一次（同样的规则，天数 / 分数可改）；池子上限（默认 5000）超了先清低分、旧的。
"""
import json
import os
import re
import time

from core import config
from core import db as _core

from . import db

CLASSES = ("excl", "low", "ignored", "adopted", "dup", "watchdel")
DEFAULTS = {"auto": True, "excl_days": 30, "low_score": 40, "low_days": 30, "ignored_days": 30, "cap": 5000, "trash_days": 7, "junk_score": 15,
            "auto_classes": ["excl", "low", "ignored", "dup", "watchdel"]}
SCHEMA = """
CREATE TABLE IF NOT EXISTS cur_trash (skey TEXT PRIMARY KEY, data TEXT, reason TEXT, trashed_at REAL, bytes INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS cur_gone (skey TEXT PRIMARY KEY, reason TEXT, at REAL, platform TEXT DEFAULT '', watch_id INTEGER DEFAULT 0);
"""
_ready = set()
THUMB_DIR = lambda: os.path.join(config.DATA_DIR, "cur_thumbs")  # noqa: E731


def ensure():
    c = db.conn()
    if _core.DB_PATH in _ready:
        return c
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(cur_candidates)")}
    if "seen_at" not in cols:
        c.execute("ALTER TABLE cur_candidates ADD COLUMN seen_at REAL DEFAULT 0")
    c.commit()
    _ready.add(_core.DB_PATH)
    return c


def settings():
    cur = dict(DEFAULTS)
    cur.update(db.get("pool") or {})
    return cur


def save_settings(d):
    cur = settings()
    for k, v in (d or {}).items():
        if k == "auto":
            cur[k] = bool(v)
        elif k == "auto_classes":
            cur[k] = [x for x in v if x in CLASSES]
        elif k in DEFAULTS:
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise ValueError("请填数字")
            if f < 0 or f > 1000000:
                raise ValueError("数字范围不对")
            cur[k] = int(f)
    db.put("pool", cur)
    return cur


def is_gone(skey):
    return bool(ensure().execute("SELECT 1 FROM cur_gone WHERE skey=?", (skey,)).fetchone())


# ---------------- 自动分组 ----------------
def _key(r, now, alert):
    """一个候选的分组键（r：id status seen_at excluded product_id score platform watch_id category）。"""
    gk = set()
    if r["product_id"] or r["status"] == "adopted":
        pg = "adopted"
    elif r["status"] == "ignored":
        pg = "ignored"
    elif r["status"] == "later":
        pg = "later"
    elif r["excluded"]:
        pg = "excluded"
    elif r["seen_at"]:
        pg = "seen"
    else:
        pg = "new"
    gk.add("pg:" + pg)
    if pg in ("new", "seen"):
        gk.add("top:todo")
        if (r["score"] or 0) >= alert:
            gk.add("top:hi")
    if pg in ("adopted", "ignored"):
        gk.add("top:done")
    s = r["score"] or 0
    gk.add("sc:high" if s >= 70 else "sc:mid" if s >= 50 else "sc:low")
    if r["platform"]:
        gk.add("site:" + r["platform"])
    gk.add(f"wt:{r['watch_id']}" if r["watch_id"] else "wt:none")
    gk.add("ct:" + r["category"] if r["category"] else "ct:none")
    return gk


def _light(c):
    return c.execute("SELECT id, status, seen_at, excluded, product_id, score, platform, watch_id, category FROM cur_candidates").fetchall()


def group_index(alert=70):
    """一遍扫完：{id: 分组键集合} + 各分组个数。"""
    c = ensure()
    now = time.time()
    idx, n = {}, {}
    for r in _light(c):
        gk = _key(r, now, alert)
        idx[r["id"]] = gk
        for k in gk:
            n[k] = n.get(k, 0) + 1
    n["all"] = len(idx)
    return idx, n


def summary(n, rate_rows=None):
    from . import sites
    c = ensure()
    watches = {r["id"]: (r["label"] or r["value"] or r["url"] or "") for r in c.execute("SELECT id, label, value, url FROM cur_watches")}
    return {"n": n, "total": n.get("all", 0),
            "sites": sorted(({"key": k, "name": sites.name_of(k[5:]), "n": v} for k, v in n.items() if k.startswith("site:")), key=lambda x: -x["n"]),
            "watches": sorted(({"key": k, "name": watches.get(int(k[3:]), "#" + k[3:]), "n": v} for k, v in n.items() if re.match(r"wt:\d+$", k)), key=lambda x: -x["n"]),
            "cats": sorted(({"key": k, "name": k[3:], "n": v} for k, v in n.items() if k.startswith("ct:") and k != "ct:none"), key=lambda x: -x["n"])}


def set_seen(ids, seen=True):
    c = ensure()
    c.executemany("UPDATE cur_candidates SET seen_at=? WHERE id=? AND status<>'adopted'", [(time.time() if seen else 0, int(i)) for i in ids])
    c.commit()


# ---------------- KPI ----------------
def kpis():
    c = ensure()
    now = time.time()
    rows = c.execute("SELECT platform, watch_id, product_id, status, excluded, first_seen, seen_at FROM cur_candidates").fetchall()
    gone = c.execute("SELECT platform, watch_id, reason FROM cur_gone").fetchall()
    total = len(rows)
    review = sum(1 for r in rows if not r["product_id"] and r["status"] in ("", None) and not r["excluded"])
    newweek = sum(1 for r in rows if (r["first_seen"] or 0) >= now - 7 * 86400)
    watches = {r["id"]: (r["label"] or r["value"] or "") for r in c.execute("SELECT id, label, value FROM cur_watches")}
    by_site, by_watch = {}, {}
    adopted = seen = 0
    for p, w, adp, ign in [(r["platform"], r["watch_id"], bool(r["product_id"]) or r["status"] == "adopted", r["excluded"]) for r in rows] + \
            [(g["platform"], g["watch_id"], g["reason"] == "adopted", "") for g in gone]:
        if ign:
            continue                     # 规则排除的不算「看过的」
        seen += 1
        adopted += 1 if adp else 0
        for d, k in ((by_site, p or "?"), (by_watch, w or 0)):
            e = d.setdefault(k, [0, 0])
            e[0] += 1 if adp else 0
            e[1] += 1
    rate = lambda a, b: round(100.0 * a / b, 1) if b else 0.0  # noqa: E731
    from . import sites
    return {"total": total, "new_week": newweek, "review": review, "adopted": adopted, "rate": rate(adopted, seen),
            "by_site": sorted(({"site": k, "name": sites.name_of(k), "adopted": v[0], "seen": v[1], "rate": rate(*v)} for k, v in by_site.items()), key=lambda x: -x["seen"]),
            "by_watch": sorted(({"watch_id": k, "name": watches.get(k, "—") if k else "", "adopted": v[0], "seen": v[1], "rate": rate(*v)} for k, v in by_watch.items() if k), key=lambda x: -x["seen"])}


# ---------------- 清理 ----------------
def _bytes(r):
    return sum(len(str(r[k] or "")) for k in r.keys() if isinstance(r[k], (str, bytes))) + 64


def _norm(t):
    return re.sub(r"[^0-9a-z฀-๿一-鿿]+", "", (t or "").lower())


def _select(opts):
    """每一类选中的候选：{类: {id: 字节}}（dup 的另给合并信息）。"""
    c = ensure()
    s = settings()
    s.update({k: opts[k] for k in opts if k in DEFAULTS and k not in ("auto", "auto_classes")})
    now = time.time()
    rows = c.execute("SELECT * FROM cur_candidates").fetchall()
    wids = {r[0] for r in c.execute("SELECT id FROM cur_watches")}
    out = {k: {} for k in CLASSES}
    merge = {}          # dup：{要删的 id: 留下的 id}
    for r in rows:
        free = not r["product_id"] and r["status"] != "adopted"
        seen_ago = (now - (r["last_seen"] or 0)) / 86400
        if free and r["excluded"] and r["status"] != "ignored" and seen_ago > s["excl_days"]:
            out["excl"][r["id"]] = _bytes(r)
        if free and not r["excluded"] and r["status"] == "" and (r["score"] or 0) < s["low_score"] and seen_ago > s["low_days"]:
            out["low"][r["id"]] = _bytes(r)
        if r["status"] == "ignored" and not r["product_id"] and seen_ago > s["ignored_days"]:
            out["ignored"][r["id"]] = _bytes(r)
        if r["product_id"] or r["status"] == "adopted":
            out["adopted"][r["id"]] = _bytes(r)
        if free and r["watch_id"] and r["watch_id"] not in wids:
            out["watchdel"][r["id"]] = _bytes(r)
    groups = {}
    for r in rows:
        k = (_norm(r["author"]), _norm(r["title"]))
        if k[1] and len(k[1]) >= 6:
            groups.setdefault(k, []).append(r)
    for g in groups.values():
        if len(g) < 2:
            continue
        g.sort(key=lambda r: (bool(r["product_id"]), r["status"] == "adopted", r["status"] == "ignored", r["score"] or 0, r["last_seen"] or 0), reverse=True)
        for r in g[1:]:
            if r["product_id"] or r["status"] == "adopted":
                continue
            out["dup"][r["id"]] = _bytes(r)
            merge[r["id"]] = g[0]["id"]
    return out, merge


def preview(opts=None):
    opts = opts or {}
    sel, _m = _select(opts)
    allids = set()
    cls = []
    for k in CLASSES:
        allids |= set(sel[k])
        cls.append({"id": k, "n": len(sel[k]), "mb": round(sum(sel[k].values()) / 1048576, 4)})
    uniq = {i: max(sel[k].get(i, 0) for k in CLASSES) for i in allids}
    return {"classes": cls, "total": len(allids), "mb": round(sum(uniq.values()) / 1048576, 4), "settings": settings(), "storage": storage()}


def _trash(c, rows, reason):
    now = time.time()
    for r in rows:
        d = dict(r)
        c.execute("INSERT OR REPLACE INTO cur_trash(skey, data, reason, trashed_at, bytes) VALUES(?,?,?,?,?)",
                  (r["skey"], json.dumps(d, ensure_ascii=False), reason, now, _bytes(r)))
        c.execute("INSERT OR REPLACE INTO cur_gone(skey, reason, at, platform, watch_id) VALUES(?,?,?,?,?)",
                  (r["skey"], "adopted" if (r["product_id"] or r["status"] == "adopted") else reason, now, r["platform"] or "", r["watch_id"] or 0))
        c.execute("DELETE FROM cur_candidates WHERE id=?", (r["id"],))


def _merge_metrics(c, winner, loser_ids):
    w = c.execute("SELECT metrics, status FROM cur_candidates WHERE id=?", (winner,)).fetchone()
    m = db.jl(w["metrics"])
    status = w["status"]
    for i in loser_ids:
        r = c.execute("SELECT metrics, status FROM cur_candidates WHERE id=?", (i,)).fetchone()
        if not r:
            continue
        for k, v in db.jl(r["metrics"]).items():
            try:
                if float(str(v).replace(",", "").rstrip("kK")) > float(str(m.get(k, "0")).replace(",", "").rstrip("kK")):
                    m[k] = v
            except ValueError:
                m.setdefault(k, v)
        if r["status"] == "ignored":
            status = "ignored"                  # 其中一个忽略过 → 合并后也是忽略（忽略的不会回来）
    c.execute("UPDATE cur_candidates SET metrics=?, status=? WHERE id=?", (json.dumps(m, ensure_ascii=False), status, winner))


def run(opts=None, classes=None):
    """执行清理：classes = 勾选的类。返回 {removed, mb, by_class}。"""
    opts = opts or {}
    c = ensure()
    sel, merge = _select(opts)
    classes = [k for k in (classes or []) if k in CLASSES]
    ids, reason = {}, {}
    for k in classes:
        for i in sel[k]:
            if i not in ids:
                ids[i] = sel[k][i]
                reason[i] = k
    by = {k: 0 for k in classes}
    if "dup" in classes:
        winners = {}
        for loser, win in merge.items():
            if loser in ids:
                winners.setdefault(win, []).append(loser)
        for win, losers in winners.items():
            if win not in ids:
                _merge_metrics(c, win, losers)
    n = 0
    for i, b in ids.items():
        r = c.execute("SELECT * FROM cur_candidates WHERE id=?", (i,)).fetchone()
        if r:
            _trash(c, [r], reason[i])
            by[reason[i]] += 1
            n += 1
    c.commit()
    return {"removed": n, "mb": round(sum(ids.values()) / 1048576, 4), "by_class": by}


def enforce_cap(cap=None):
    """池子上限：超了先清低分、旧的（没处理的；稍后看 / 已采用的不动）。"""
    c = ensure()
    cap = int(cap or settings()["cap"])
    total = c.execute("SELECT COUNT(*) FROM cur_candidates").fetchone()[0]
    if cap <= 0 or total <= cap:
        return 0
    rows = c.execute("SELECT * FROM cur_candidates WHERE product_id='' AND status IN ('', 'ignored') ORDER BY (status='ignored') DESC, score ASC, last_seen ASC LIMIT ?",
                     (total - cap,)).fetchall()
    _trash(c, rows, "cap")
    c.commit()
    return len(rows)


# ---------------- 回收站 ----------------
def trash_list():
    c = ensure()
    purge_expired()
    return [{"skey": r["skey"], "reason": r["reason"], "at": r["trashed_at"], "bytes": r["bytes"], "title": db.jl(r["data"]).get("title", ""),
             "platform": db.jl(r["data"]).get("platform", ""), "score": db.jl(r["data"]).get("score"), "id": db.jl(r["data"]).get("id")}
            for r in c.execute("SELECT * FROM cur_trash ORDER BY trashed_at DESC LIMIT 500")]


def restore(skeys):
    c = ensure()
    n = 0
    cols = {r[1] for r in c.execute("PRAGMA table_info(cur_candidates)")}
    for k in skeys or []:
        r = c.execute("SELECT data FROM cur_trash WHERE skey=?", (k,)).fetchone()
        if not r or c.execute("SELECT 1 FROM cur_candidates WHERE skey=?", (k,)).fetchone():
            continue
        d = {a: b for a, b in db.jl(r["data"]).items() if a in cols and a != "id"}
        c.execute(f"INSERT INTO cur_candidates({','.join(d)}) VALUES({','.join('?' for _ in d)})", list(d.values()))
        c.execute("DELETE FROM cur_trash WHERE skey=?", (k,))
        c.execute("DELETE FROM cur_gone WHERE skey=?", (k,))
        n += 1
    c.commit()
    return n


def purge_expired(force=False):
    """回收站到期（默认 7 天）的彻底删除，只留指纹。返回删了几个。"""
    c = ensure()
    days = settings()["trash_days"]
    cut = time.time() + 1 if force else time.time() - days * 86400
    n = c.execute("DELETE FROM cur_trash WHERE trashed_at<?", (cut,)).rowcount
    c.commit()
    return n


# ---------------- 存储 / 自动清理 ----------------
def storage():
    c = ensure()
    cand = sum(len(str(v or "")) for r in c.execute("SELECT title, thumb, author, metrics, parts, ai, real, url FROM cur_candidates") for v in tuple(r))
    tr = c.execute("SELECT COALESCE(SUM(bytes),0) FROM cur_trash").fetchone()[0]
    th = 0
    d = THUMB_DIR()
    if os.path.isdir(d):
        for f in os.listdir(d):
            try:
                th += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return {"candidates": c.execute("SELECT COUNT(*) FROM cur_candidates").fetchone()[0], "cand_mb": round(cand / 1048576, 4),
            "trash": c.execute("SELECT COUNT(*) FROM cur_trash").fetchone()[0], "trash_mb": round(tr / 1048576, 4),
            "thumbs_mb": round(th / 1048576, 4), "gone": c.execute("SELECT COUNT(*) FROM cur_gone").fetchone()[0]}


def clean_thumbs():
    """缓存的缩略图：对应的候选已经不在池子里的删掉。返回删了几个。"""
    d = THUMB_DIR()
    if not os.path.isdir(d):
        return 0
    keep = {re.sub(r"[^0-9A-Za-z_-]", "_", r[0]) for r in ensure().execute("SELECT skey FROM cur_candidates")}
    n = 0
    for f in os.listdir(d):
        if os.path.splitext(f)[0] not in keep:
            try:
                os.remove(os.path.join(d, f))
                n += 1
            except OSError:
                pass
    return n


def trim_logs():
    """巡逻记录只留最近几次（每个关注 5 次）+ 60 天内的。"""
    c = ensure()
    n = c.execute("""DELETE FROM cur_watch_log WHERE ts<? AND id NOT IN (
        SELECT id FROM cur_watch_log l WHERE (SELECT COUNT(*) FROM cur_watch_log x WHERE x.watch_id=l.watch_id AND x.id>l.id)<5)""", (time.time() - 60 * 86400,)).rowcount
    c.commit()
    return n


def auto_clean(force=False):
    """每天一次（后台循环里调用）；force 不看开关和时间。返回结果，没跑返回 None。"""
    s = settings()
    now = time.time()
    if not force and (not s["auto"] or now - (db.get("pool_last") or 0) < 86400):
        return None
    db.put("pool_last", now)
    purge_expired()
    res = run({}, s["auto_classes"])
    capped = enforce_cap(s["cap"])
    res.update(capped=capped, thumbs=clean_thumbs(), logs=trim_logs())
    return res
