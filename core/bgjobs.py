"""后台任务（v2.19，v2.20 加「任务中心」）：耗时的操作（切片、上传模型、抠图……）放到后台线程跑，
浏览器每隔几秒问一次结果，不会因为浏览器 / 反向代理等太久断开而「失败」。结果在内存里保留 1 小时（最多 200 个）。

任务里可以调用 note(stage=…, where=…) 更新「在哪里跑 / 进行到哪一步」（core/accel 会自动写：where = 电脑名 / NAS；
stage = queued 排队中 / wait_pc 等电脑接手 / pc 电脑处理中，网页按语言翻译）。
"""
import threading
import time
import traceback
import uuid

_JOBS = {}
_LOCK = threading.Lock()
_TL = threading.local()
KEEP_S = 3600
KEEP_N = 200
PUBLIC = ("id", "label", "user", "status", "stage", "where", "why", "why_msg", "error", "started", "ended", "link", "kind")


def _cleanup():
    now = time.time()
    for k in [k for k, v in _JOBS.items() if v["status"] not in ("running", "queued") and now - v["started"] > KEEP_S]:
        _JOBS.pop(k, None)
    if len(_JOBS) > KEEP_N:
        old = sorted((v for v in _JOBS.values() if v["status"] not in ("running", "queued")), key=lambda v: v["started"])
        for v in old[:len(_JOBS) - KEEP_N]:
            _JOBS.pop(v["id"], None)


def start(fn, label="", user="", kind="", link=""):
    """fn 在后台线程里跑。kind：分类（slice / model / image / ai…）；link：完成后点哪里看结果（前端用，例如 #p=产品编号）。"""
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "label": label, "user": user, "kind": kind, "link": link, "status": "running", "stage": "", "where": "",
           "started": time.time(), "result": None, "error": None, "http": 200, "fn": fn}
    with _LOCK:
        _cleanup()
        _JOBS[jid] = job

    def run():
        _TL.job = job
        try:
            res = fn()
            if isinstance(res, tuple):          # (数据, HTTP 状态码)：路由函数的返回值
                res, job["http"] = res[0], res[1]
            if hasattr(res, "get_json"):
                job["http"] = getattr(res, "status_code", 200)
                res = res.get_json()
            job["result"] = res
            if job["http"] >= 400 or (isinstance(res, dict) and res.get("error")):
                job["status"] = "error"
                job["error"] = (res or {}).get("error") if isinstance(res, dict) else str(res)
            else:
                job["status"] = "done"
        except Exception as e:  # noqa: BLE001
            job["status"], job["error"] = "error", str(e) or e.__class__.__name__
            try:
                from . import diag
                diag.log.error("后台任务出错 %s：%s\n%s", label, e, traceback.format_exc()[-3000:])
            except Exception:  # noqa: BLE001
                pass
        finally:
            job["ended"] = time.time()
            job["stage"] = ""
            _TL.job = None
    threading.Thread(target=run, daemon=True, name=f"bg-{label}"[:30]).start()
    return job


def current():
    return getattr(_TL, "job", None)


def note(**kw):
    """在后台任务里更新状态：stage（进行到哪一步）、where（电脑名 / NAS）、status=queued/running。不在后台任务里调用就什么也不做。"""
    j = current()
    if j is not None:
        for k, v in kw.items():
            if k in ("stage", "where", "status", "why", "why_msg") and v is not None:
                if k == "status" and j["status"] not in ("running", "queued"):
                    continue
                j[k] = v


def _pub(j, with_result=False):
    out = {k: j.get(k) for k in PUBLIC}
    out["elapsed"] = round((j.get("ended") or time.time()) - j["started"], 1)
    if with_result and j["status"] == "done":
        out["result"] = j["result"]
    return out


def get(jid):
    j = _JOBS.get(jid)
    return _pub(j, True) if j else None


def owner_of(jid):
    j = _JOBS.get(jid)
    return j.get("user") if j else None


def list_jobs(user=None, limit=40):
    """任务中心：最近的任务（新的在前）。user=None 看全部。"""
    with _LOCK:
        js = [j for j in _JOBS.values() if user is None or j.get("user") == user]
    js.sort(key=lambda j: (j["status"] not in ("running", "queued"), -j["started"]))
    return [_pub(j) for j in js[:limit]]


def retry(jid):
    j = _JOBS.get(jid)
    if not j or j["status"] != "error" or not j.get("fn"):
        return None
    return start(j["fn"], j["label"], j["user"], j.get("kind", ""), j.get("link", ""))


def clear(user=None):
    """清掉已经结束的任务（任务中心「清空已完成」）。"""
    with _LOCK:
        for k in [k for k, v in _JOBS.items() if v["status"] not in ("running", "queued") and (user is None or v.get("user") == user)]:
            _JOBS.pop(k, None)


def counts(user=None):
    with _LOCK:
        js = [j for j in _JOBS.values() if user is None or j.get("user") == user]
    return {"running": sum(j["status"] == "running" for j in js), "queued": sum(j["status"] == "queued" for j in js)}
