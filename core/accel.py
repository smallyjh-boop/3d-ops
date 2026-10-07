"""电脑加速（v2.20）：NAS 的 CPU 慢，把吃 CPU 的活（切片、读大模型、生成 3D 预览、抠图、去水印）交给一直开着的电脑做。

  电脑上运行 worker.py（双击 4_start_worker.bat），它每隔十几秒向 NAS 报到（hello），然后一直问 NAS「有活吗」（next）。
  NAS 上要做重活时调用 run(kind, …)：
    · 有在线的电脑、而且会做这种活 → 放进队列，电脑领走后下载输入文件、算好、把结果和文件传回来；
    · 没有电脑在线、电脑 claim_wait 秒内没领（都在忙）、电脑算到一半掉线 / 超时、电脑上缺组件 → 自动改在 NAS 上算；
    · 电脑算出来是「文件本身有问题」（例如模型坏了切不了）→ 直接报错，不再让 NAS 重算一遍（NAS 也一样会失败，还更慢）。
  NAS 上自己算的重活同时最多 accel_local_slots 个（默认 1），其它的排队（任务中心显示「排队中」）。

★ 对外接口：run()  heavy()  status()  workers()  enabled()
  电脑那边的接口在 web/system.py：/api/v1/accel/hello | next | task/<id>/file/<名字> | task/<id>/done | task/<id>/fail（密钥权限 worker）
  每种活的「算法本身」在 core/kernels.py，NAS 和电脑跑的是同一份代码。
"""
import os
import shutil
import tempfile
import threading
import time
import uuid

from . import bgjobs
from .config import DATA_DIR, load_config

PROTO = 1
ONLINE_S = 45              # 多久没报到算离线
KINDS = {"slice": "切片", "mesh": "读模型", "preview": "3D 预览", "removebg": "抠图", "inpaint": "去水印 / 杂物",
         "toolpath": "切片预览"}
INPAINT_RANK = {"basic": 0, "opencv": 1, "lama": 2}

_cv = threading.Condition()
_workers = {}              # 名字 → {name, caps, cpu, gpu, version, last, busy, done, failed, ip, info}
_tasks = {}                # 任务号 → 任务
_queue = []                # 等电脑领的任务号（先进先出）
_stats = {"remote": 0, "local": 0, "fallback": 0}
_recent = []               # 最近 30 个任务（系统页显示）

_slots_lock = threading.Lock()
_slots = None
_slots_n = 0
_held = threading.local()


class RemoteError(Exception):
    """电脑算出来的「文件本身有问题」类错误。"""


def _cfg_int(cfg, k, d, lo, hi):
    try:
        return max(lo, min(hi, int(cfg.get(k) if cfg.get(k) not in (None, "") else d)))
    except (TypeError, ValueError):
        return d


def enabled(cfg=None):
    cfg = cfg or load_config()
    return bool(cfg.get("accel_on", True))


# ---------------- NAS 上的重活：同时最多几个 ----------------
def _sem():
    global _slots, _slots_n
    n = _cfg_int(load_config(), "accel_local_slots", 1, 1, 4)
    with _slots_lock:
        if _slots is None or n != _slots_n:
            _slots, _slots_n = threading.BoundedSemaphore(n), n
        return _slots


class heavy:
    """with heavy(): …  NAS 本机的重活排队（同一个线程里嵌套不会自己卡住自己）。"""

    def __enter__(self):
        depth = getattr(_held, "n", 0)
        if depth == 0:
            s = _sem()
            if not s.acquire(blocking=False):
                bgjobs.note(status="queued", stage="queued")
                s.acquire()
                bgjobs.note(status="running", stage="")
            _held.sem = s
        _held.n = depth + 1
        return self

    def __exit__(self, *a):
        _held.n -= 1
        if _held.n == 0:
            try:
                _held.sem.release()
            except ValueError:
                pass
        return False


# ---------------- 电脑（worker）登记 ----------------
def hello(name, info, ip=""):
    name = (str(name or "PC").strip() or "PC")[:40]
    caps = [c for c in (info.get("caps") or []) if c in KINDS]
    with _cv:
        w = _workers.setdefault(name, {"name": name, "done": 0, "failed": 0, "busy": 0, "first": time.time()})
        w.update(caps=caps, cpu=info.get("cpu"), gpu=str(info.get("gpu") or "")[:80], version=str(info.get("version") or "")[:20],
                 proto=info.get("proto"), slots=info.get("slots") or 1, inpaint=info.get("inpaint") or "",
                 orca=str(info.get("orca") or "")[:80], os=str(info.get("os") or "")[:60], last=time.time(), ip=ip,
                 missing={k: str(v)[:200] for k, v in (info.get("missing") or {}).items() if k in KINDS},
                 installing=str(info.get("installing") or "")[:100],
                 paused=bool(info.get("paused")))
        _cv.notify_all()
    return {"ok": True, "proto": PROTO, "server_version": _server_version(), "enabled": enabled()}


def _server_version():
    try:
        from web.common import VERSION
        return VERSION
    except Exception:  # noqa: BLE001
        return ""


def _online(w, now=None):
    return (now or time.time()) - w.get("last", 0) < ONLINE_S


def workers():
    now = time.time()
    sv = _server_version()
    out = []
    with _cv:
        for w in _workers.values():
            d = {k: v for k, v in w.items()}
            d["online"] = _online(w, now)
            d["ago"] = round(now - w.get("last", 0))
            d["version_ok"] = not sv or not w.get("version") or w.get("version") == sv
            d["kinds"] = [KINDS[c] for c in w.get("caps") or []]
            out.append(d)
    out.sort(key=lambda d: (not d["online"], d["name"]))
    return out


def _capable(kind, params=None):
    """返回 (能不能交给电脑, 不能时的原因代码, 说明)。原因：no_pc 没有电脑在线 / pc_cant 电脑做不了这个（缺组件）/
    pc_stuck 电脑程序没在领活 / pc_worse 电脑的方法不如 NAS。"""
    now = time.time()
    why, msg = "no_pc", ""
    for w in _workers.values():
        if not _online(w, now) or w.get("paused") or w.get("proto") != PROTO:
            continue
        if kind not in (w.get("caps") or []):
            why, msg = "pc_cant", ((w.get("missing") or {}).get(kind) or "")
            continue
        # 报到了但没在领活、手上也没活（程序卡住了）：不等它，NAS 直接做
        if not w.get("polling") and not w.get("busy") and now - w.get("last_poll", 0) > 5:
            why, msg = "pc_stuck", ""
            continue
        if kind == "inpaint" and params is not None:
            # 电脑上去水印的方法不比 NAS 好就不用电脑（例如 NAS 装了 LaMa、电脑没装）
            from . import imgtools
            if INPAINT_RANK.get(w.get("inpaint"), 0) < INPAINT_RANK.get(imgtools.status()["inpaint"], 0):
                why, msg = "pc_worse", ""
                continue
        return True, "", ""
    return False, why, msg


# ---------------- 派活 ----------------
def run(kind, params, files, local, remote_done=None, timeout=1800, claim_wait=None, min_bytes=0, err_cls=RuntimeError,
        heavy_local=True):
    """做一件重活。files：{名字: 本机路径}（电脑会下载）；local()：在 NAS 上做；remote_done(结果, {名字: 文件路径})：处理电脑传回的结果。
    min_bytes：输入文件加起来小于这个大小就直接在 NAS 上做（小文件传来传去反而慢）。"""
    cfg = load_config()
    size = sum(os.path.getsize(p) for p in files.values() if p and os.path.exists(p))
    why, msg = ("off", "") if not enabled(cfg) else ("small", "") if size < min_bytes else ("", "")
    if not why:
        with _cv:
            ok, why, msg = _capable(kind, params)
        if ok:
            if claim_wait is None:
                claim_wait = _cfg_int(cfg, "accel_claim_wait", 8, 2, 120)
            res = _remote(kind, params, files, remote_done, timeout, claim_wait, err_cls)
            if not isinstance(res, _Fallback):
                return res
            why, msg = res.why, res.msg
            _stats["fallback"] += 1
    _stats["local"] += 1
    _last_local[kind] = {"why": why, "msg": msg, "at": time.time()}
    bgjobs.note(where="NAS", why=why, why_msg=msg)
    if heavy_local and size >= min_bytes:          # 小文件不排队（几秒就好，不该等在大切片后面）
        with heavy():
            return local()
    return local()


class _Fallback:
    """电脑没做成，改 NAS 做（带原因）。"""

    def __init__(self, why, msg=""):
        self.why, self.msg = why, msg


_last_local = {}           # 每种活最近一次为什么在 NAS 上做（系统页显示）


def _remote(kind, params, files, remote_done, timeout, claim_wait, err_cls):
    tid = uuid.uuid4().hex[:12]
    t = {"id": tid, "kind": kind, "params": params, "files": {k: v for k, v in files.items() if v}, "status": "queued",
         "created": time.time(), "worker": "", "result": None, "error": "", "final": False, "out": {}, "dir": "",
         "job": (bgjobs.current() or {}).get("label", "")}
    with _cv:
        _tasks[tid] = t
        _queue.append(tid)
        _cv.notify_all()
    bgjobs.note(stage="wait_pc")
    try:
        with _cv:
            end = time.time() + claim_wait
            while t["status"] == "queued" and time.time() < end:
                _cv.wait(max(0.05, end - time.time()))
            if t["status"] == "queued":                 # 电脑都在忙 / 刚好掉线：NAS 自己做
                if tid in _queue:
                    _queue.remove(tid)
                t["status"] = "gave_up"
                _log(t, "电脑没接手，改在 NAS 上做")
                return _Fallback("pc_busy")
        bgjobs.note(where=t["worker"], stage="pc")
        end = time.time() + timeout
        with _cv:
            while t["status"] == "claimed":
                w = _workers.get(t["worker"]) or {}
                if time.time() > end or not _online(w):
                    t["status"] = "lost"
                    break
                _cv.wait(5)
        if t["status"] == "done":
            _stats["remote"] += 1
            _log(t, "")
            if remote_done:
                return remote_done(t["result"], t["out"])
            return t["result"]
        if t["status"] == "failed" and t["final"]:
            _log(t, t["error"])
            raise err_cls(t["error"])
        _log(t, ("电脑掉线 / 超时" if t["status"] == "lost" else f"电脑出错：{t['error']}") + "，改在 NAS 上做")
        bgjobs.note(where="NAS", stage="")
        return _Fallback("pc_lost" if t["status"] == "lost" else "pc_err", t.get("error", "")[:200])
    finally:
        with _cv:
            _tasks.pop(tid, None)
            if tid in _queue:
                _queue.remove(tid)
        if t.get("dir"):
            shutil.rmtree(t["dir"], ignore_errors=True)


def _log(t, msg):
    _recent.insert(0, {"kind": KINDS.get(t["kind"], t["kind"]), "worker": t.get("worker") or "", "status": t["status"], "msg": msg[:200],
                       "secs": round(time.time() - t["created"], 1), "at": time.time(), "job": t.get("job", "")})
    del _recent[30:]
    if msg:
        try:
            from . import diag
            diag.log.info("电脑加速 %s：%s", KINDS.get(t["kind"], t["kind"]), msg[:300])
        except Exception:  # noqa: BLE001
            pass


# ---------------- 电脑那边调用的 ----------------
def next_task(name, caps, wait=25):
    """电脑来领活（长轮询，最多等 wait 秒）。返回 {id, kind, params, files: [名字]} 或 None。"""
    end = time.time() + max(1, min(60, wait))
    with _cv:
        w = _workers.get(name)
        if w:
            w["last"] = time.time()
            w["polling"] = w.get("polling", 0) + 1
        try:
            return _wait_task(name, w, caps, end)
        finally:
            if w:
                w["polling"] = max(0, w.get("polling", 1) - 1)
                w["last_poll"] = time.time()


def _wait_task(name, w, caps, end):
    """（调用方已经拿着 _cv）"""
    while True:
        for tid in list(_queue):
            t = _tasks.get(tid)
            if t and t["status"] == "queued" and t["kind"] in caps:
                _queue.remove(tid)
                t.update(status="claimed", worker=name, claimed=time.time())
                if w:
                    w["busy"] = w.get("busy", 0) + 1
                _cv.notify_all()
                return {"id": tid, "kind": t["kind"], "params": t["params"], "files": list(t["files"]),
                        "sizes": {k: os.path.getsize(p) for k, p in t["files"].items() if os.path.exists(p)},
                        "ext": {k: os.path.splitext(p)[1].lower()[:8] for k, p in t["files"].items()}}
        left = end - time.time()
        if left <= 0:
            return None
        _cv.wait(left)


def task_file(tid, name):
    t = _tasks.get(tid)
    if not t or t["status"] != "claimed":
        return None
    return t["files"].get(name)


def task_done(tid, name, result, files):
    """files：{名字: werkzeug FileStorage}。"""
    t = _tasks.get(tid)
    if not t or t["status"] != "claimed":
        return False
    d = tempfile.mkdtemp(prefix="accel_", dir=_tmp())
    out = {}
    for k, f in (files or {}).items():
        safe = "".join(ch for ch in k if ch.isalnum() or ch in "._-")[:60] or "f"
        p = os.path.join(d, safe)
        f.save(p)
        out[k] = p
    with _cv:
        t.update(status="done", result=result, out=out, dir=d)
        _end(t, True)
        _cv.notify_all()
    return True


def task_fail(tid, name, error, final=False):
    t = _tasks.get(tid)
    if not t or t["status"] != "claimed":
        return False
    with _cv:
        t.update(status="failed", error=str(error or "出错")[:2000], final=bool(final))
        _end(t, False)
        _cv.notify_all()
    return True


def _end(t, ok):
    w = _workers.get(t["worker"])
    if w:
        w["busy"] = max(0, w.get("busy", 0) - 1)
        w["done" if ok else "failed"] = w.get("done" if ok else "failed", 0) + 1
        w["last"] = time.time()


def _tmp():
    d = os.path.join(DATA_DIR, "tmp")
    os.makedirs(d, exist_ok=True)
    return d


def status():
    with _cv:
        q = [{"kind": KINDS.get(t["kind"], t["kind"]), "status": t["status"], "worker": t.get("worker", ""),
              "secs": round(time.time() - t["created"]), "job": t.get("job", "")} for t in _tasks.values()]
    cfg = load_config()
    return {"enabled": enabled(cfg), "workers": workers(), "tasks": q, "recent": list(_recent), "stats": dict(_stats),
            "local_slots": _cfg_int(cfg, "accel_local_slots", 1, 1, 4), "kinds": KINDS, "server_version": _server_version(),
            "last_local": dict(_last_local)}
