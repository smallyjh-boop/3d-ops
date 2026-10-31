"""客服后台任务队列 + 工作线程（v2.46）。

所有慢的事（拉平台消息、AI 写草稿 / 自动回复、质检、主动提醒）都放进 cs_jobs 表，由工作线程按顺序做：
  · 默认在 ERP 程序里开一个线程做（start()）；
  · 以后消息多了要拆开：设置环境变量 CS_WORKER=external，ERP 里就不开线程，
    在另一个进程 / 另一台机器（共用数据库）运行  python -m modules.cs.worker  就行。
任务失败会重试 3 次（间隔越来越长），错误记在任务上。
"""
import json
import os
import socket
import threading
import time

from . import data

KINDS = ("draft", "auto", "poll", "notify", "qa", "tr")
_wake = threading.Event()
_state = {"started": False, "last_poll": {}, "last_sweep": 0, "last_hour": 0, "errors": {}}


def _db():
    from core import db
    return db.conn()


def enqueue(kind, conv_id=None, payload=None, delay=0):
    """排一个任务。同一个会话还没做的同类任务不重复排。返回任务 id。"""
    c = _db()
    if conv_id:
        r = c.execute("SELECT id FROM cs_jobs WHERE kind=? AND conv_id=? AND status='todo'", (kind, conv_id)).fetchone()
        if r:
            return r["id"]
    now = time.time()
    jid = c.execute("INSERT INTO cs_jobs(kind, conv_id, payload, status, run_at, created_at) VALUES(?,?,?,'todo',?,?)",
                    (kind, conv_id, json.dumps(payload or {}, ensure_ascii=False), now + delay, now)).lastrowid
    c.commit()
    _wake.set()
    return jid


def _take(worker):
    """取一个到时间的任务（原子地标成 doing，多个工作进程也不会抢到同一个）。"""
    c = _db()
    r = c.execute("SELECT id FROM cs_jobs WHERE status='todo' AND run_at<=? ORDER BY run_at, id LIMIT 1", (time.time(),)).fetchone()
    if not r:
        return None
    n = c.execute("UPDATE cs_jobs SET status='doing', worker=?, tries=tries+1 WHERE id=? AND status='todo'", (worker, r["id"])).rowcount
    c.commit()
    if not n:
        return None
    return dict(c.execute("SELECT * FROM cs_jobs WHERE id=?", (r["id"],)).fetchone())


def _finish(j, err=None):
    c = _db()
    if err is None:
        c.execute("UPDATE cs_jobs SET status='done', done_at=?, error=NULL WHERE id=?", (time.time(), j["id"]))
    elif j["tries"] >= 3:
        c.execute("UPDATE cs_jobs SET status='failed', done_at=?, error=? WHERE id=?", (time.time(), str(err)[:500], j["id"]))
    else:
        c.execute("UPDATE cs_jobs SET status='todo', run_at=?, error=? WHERE id=?", (time.time() + 30 * j["tries"] ** 2, str(err)[:500], j["id"]))
    c.execute("DELETE FROM cs_jobs WHERE status IN ('done','failed') AND done_at<?", (time.time() - 3 * 86400,))
    c.commit()


def run_job(j):
    from . import chat
    p = json.loads(j.get("payload") or "{}")
    k = j["kind"]
    if k in ("draft", "auto"):
        return chat.run_ai(j["conv_id"], auto=(k == "auto"))
    if k == "notify":
        return chat.notify(int(p["order_id"]), p.get("what") or "shipped")
    if k == "qa":
        return chat.qa_one(j["conv_id"])
    if k == "tr":                 # v2.49：买家消息翻成中文
        return chat.translate_pending(j["conv_id"])
    if k == "poll":
        return poll_all(force=True)
    raise ValueError("不认识的任务 " + k)


def run_due(worker="main", limit=20):
    """做到时间的任务，最多 limit 个。返回做了几个。"""
    n = 0
    while n < limit:
        j = _take(worker)
        if not j:
            break
        try:
            run_job(j)
            _finish(j)
        except Exception as e:  # noqa: BLE001
            _finish(j, e)
        n += 1
    return n


# ---------------- 拉平台消息 ----------------
def _poll_sec():
    try:
        return max(5.0, float(data.settings().get("poll_sec") or 15))
    except ValueError:
        return 15.0


def poll_all(force=False):
    """拉所有开了聊天接口的店铺。出错的店铺 5 分钟后再试（比如还没开通 IM 权限）。返回 {店铺名: 新消息会话数 / 错误}。"""
    from . import chat, erp_link, shopcfg
    from .channels import lazada_im
    out = {}
    now = time.time()
    for shop in erp_link.api_shops("lazada"):
        if not shopcfg.get(shop["name"]).get("im", True):
            continue
        last = _state["last_poll"].get(shop["id"], 0)
        gap = 300 if _state["errors"].get(shop["id"]) else _poll_sec()
        if not force and now - last < gap:
            continue
        _state["last_poll"][shop["id"]] = now
        try:
            changed = lazada_im.poll(shop)
            _state["errors"].pop(shop["id"], None)
            for cid in changed:
                chat.on_buyer(cid)
            out[shop["name"]] = len(changed)
        except Exception as e:  # noqa: BLE001
            _state["errors"][shop["id"]] = str(e)
            data.cursor_set(shop["id"], ok=False, error=str(e))
            out[shop["name"]] = "错误：" + str(e)
    return out


def tick(worker="main"):
    """工作线程每一轮做的事。"""
    from core.connectors import lazada as LZ
    from . import chat
    force = LZ.IM_PUSH.is_set()
    LZ.IM_PUSH.clear()
    poll_all(force=force)
    run_due(worker)
    now = time.time()
    if now - _state["last_sweep"] > 60:
        _state["last_sweep"] = now
        chat.sweep_takeover(now)
    if now - _state["last_hour"] > 3600:
        _state["last_hour"] = now
        chat.check_delayed()
        chat.qa_daily(now)


def loop(worker=None):
    worker = worker or f"{socket.gethostname()}:{os.getpid()}"
    from core import db
    while True:
        try:
            tick(worker)
        except Exception as e:  # noqa: BLE001  网络问题等，下一轮再试
            print("客服后台任务出错：", e)
        finally:
            db.release()
        _wake.wait(min(5.0, _poll_sec()))
        _wake.clear()


def start():
    if os.environ.get("CS_WORKER") == "external" or _state["started"]:
        return False
    _state["started"] = True
    threading.Thread(target=loop, daemon=True, name="cs-worker").start()
    return True


def status():
    c = _db()
    cnt = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM cs_jobs GROUP BY status")}
    failed = [dict(r) for r in c.execute("SELECT id, kind, conv_id, error, done_at FROM cs_jobs WHERE status='failed' ORDER BY id DESC LIMIT 5")]
    return {"counts": cnt, "failed": failed, "external": os.environ.get("CS_WORKER") == "external", "errors": dict(_state["errors"])}
