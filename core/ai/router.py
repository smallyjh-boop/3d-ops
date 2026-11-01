"""按任务选 AI：按设置的顺序试（主选 → 备用），出错 / 限流 / 超时自动换下一个；不能看图 / 不能出图的跳过并说清楚；
每次调用记用量和费用；到了费用上限提醒或暂停。"""
import base64
import io
import threading
import time

from . import catalog as C
from . import conf, providers, usage
from .errors import AIError

_last_warn = {"msg": "", "t": 0}
_mig = {"done": False}
_mig_lock = threading.Lock()


def task_of(cfg):
    t = (cfg or {}).get("_ai_task") or "general"
    return t if t in C.TASKS else "general"


def ensure_migrated():
    """第一次用到时把旧设置搬进新结构（只搬一次）。"""
    if _mig["done"]:
        return
    with _mig_lock:
        if _mig["done"]:
            return
        _mig["done"] = True
        try:
            from ..config import load_config, save_config
            cfg = load_config()
            if cfg.get("ai_v2"):
                return
            cs_model = ""
            try:
                from .. import db
                r = db.conn().execute("SELECT v FROM cs_settings WHERE k='model'").fetchone()
                cs_model = (r["v"] if r else "") or ""
            except Exception:  # noqa: BLE001  没有客服模块的表
                cs_model = ""
            upd = conf.migrate(cfg, cs_model.strip())
            if upd:
                save_config(upd)
        except Exception as e:  # noqa: BLE001
            try:
                from .. import diag
                diag.log.error("AI 设置迁移失败：%s", e)
            except Exception:  # noqa: BLE001
                pass


def _label(pid):
    return C.PROVIDERS.get(pid, {}).get("zh", pid)


def no_vision_msg(pid):
    if pid == "deepseek":
        return "现在设置的 AI（DeepSeek）不能看图片，这个功能需要能看图的 AI（系统 → AI 接口 里给这个任务换成 Claude 或其他能看图的模型）"
    return f"现在设置的 AI（{_label(pid)}）不能看图片，这个功能需要能看图的 AI（系统 → AI 接口 里给这个任务换一个能看图的模型）"


def candidates(cfg, task, need=None):
    """(可用的 [(pid, model, provider)], 跳过的原因 [文字])。need：text / vision / image / edit。"""
    kind = "image" if need in ("image", "edit") else "text"
    out, why = [], []
    for pid, model in conf.chain(cfg, task):
        p = conf.provider(cfg, pid)
        m = model or (p["image_model"] if kind == "image" else p["text_model"])
        if not p["enabled"]:
            why.append(f"{_label(pid)} 已停用")
            continue
        if not (p["image_key"] if kind == "image" else p["api_key"]):
            why.append(f"{_label(pid)} 还没有填写密钥")
            continue
        cp = C.model_caps(pid, m, p["caps_override"])
        if need == "vision" and C.VISION not in cp:
            why.append(no_vision_msg(pid))
            continue
        if kind == "image" and C.IMAGE not in cp:
            why.append(f"{_label(pid)} 不能出图")
            continue
        out.append((pid, m, p))
    return out, why


def can(cfg, task, need=None):
    """(能不能用, 原因)。need 省略 = 按任务本身的要求。"""
    need = need or {"vision_opt": "text"}.get(C.TASKS.get(task, C.TASKS["general"])[3], C.TASKS.get(task, C.TASKS["general"])[3])
    c, why = candidates(cfg, task, need)
    if c:
        return True, ""
    keyless = all("密钥" in w for w in why) if why else True
    return False, ("还没有填写 AI 接口密钥" if keyless else why[0])


def _budget(cfg, task):
    ok, msg = usage.check(cfg, task)
    if not ok:
        raise AIError(msg, kind="budget")
    if msg and (msg != _last_warn["msg"] or time.time() - _last_warn["t"] > 3600):
        _last_warn.update(msg=msg, t=time.time())
        try:
            from .. import diag
            diag.log.warning("AI 费用提醒：%s", msg)
        except Exception:  # noqa: BLE001
            pass
    return msg


def text(cfg, system, user, image_b64=None, strict_image=False):
    """文字（可带一张图）。strict_image：一定要看图（看不了就报错，不退回纯文字）。"""
    ensure_migrated()
    task = task_of(cfg)
    need_t = C.TASKS[task][3]
    want_vision = bool(image_b64)
    must_vision = want_vision and (strict_image or need_t == "vision")
    cands, why = candidates(cfg, task, "vision" if want_vision else "text")
    if want_vision and not cands:
        if must_vision:
            allc, why2 = candidates(cfg, task, "text")
            if not allc and all("密钥" in w for w in why2):
                raise AIError("还没有填写 AI 接口密钥（设置页）", kind="config")
            raise AIError(next((w for w in why if "看图" in w), why[0] if why else "没有能看图的 AI"), kind="cap")
        image_b64 = None                       # 能看图更好的任务：退回纯文字
        cands, why = candidates(cfg, task, "text")
    if not cands:
        if not why or all("密钥" in w for w in why):
            raise AIError("还没有填写 AI 接口密钥（设置页）", kind="config")
        raise AIError(why[0], kind="config")
    _budget(cfg, task)
    errs = []
    for i, (pid, model, p) in enumerate(cands):
        if pid == "deepseek" and (not model or str(model).lower().startswith("claude")):
            errs.append(AIError("接口类型选了 DeepSeek：请在「模型名称」里填 DeepSeek 的模型名（DeepSeek 开放平台的模型列表里有）", kind="config"))
            continue
        t0 = time.time()
        try:
            out, tin, tout = providers.text(p, model, system, user, image_b64)
        except AIError as e:
            e = AIError(providers.scrub(str(e), p["api_key"]), kind=e.kind, status=e.status)
            _log(cfg, task, pid, model, "vision" if image_b64 else "text", ok=False, error=str(e), ms=(time.time() - t0) * 1000, fallback=i)
            errs.append(e)
            continue
        _log(cfg, task, pid, model, "vision" if image_b64 else "text", tin=tin, tout=tout, ms=(time.time() - t0) * 1000, fallback=i)
        return out
    # 都失败：带图的「能看图更好」任务，再用第一个不带图试一次（以前的做法：模型看不了图时退回纯文字）
    if image_b64 and not must_vision and any(e.kind == "client" for e in errs):
        return text(dict(cfg, _ai_task=task), system, user, None)
    if len(errs) == 1 or len({str(e) for e in errs}) == 1:
        raise errs[0]
    raise AIError("；".join(f"{_label(c[0])}：{str(e)[:160]}" for c, e in zip(cands, errs)), kind=errs[-1].kind, status=errs[-1].status)


def _log(cfg, task, pid, model, kind, **kw):
    try:
        usage.log(cfg, task, pid, model, kind, **kw)
    except Exception:  # noqa: BLE001  记账失败不影响调用
        pass


def image(cfg, prompt, ref_png=None, aspect="1:1", n=1, task=None, want_edit=True):
    """出图。返回 {"images": [bytes], "edited": 是否按参考图改的, "provider", "model", "cost"}。
    ref_png + want_edit：优先用能「参考图改图」的服务商；都不能改图时只生成背景（edited=False，调用方自己把产品抠图贴上去）。
    prompt 可以是函数 prompt(edit) → 文字：改图和只生成背景用不同的提示词。"""
    ensure_migrated()
    task = task or (cfg.get("_ai_task") if cfg.get("_ai_task") in C.TASKS else "scene")
    cands, why = candidates(cfg, task, "image")
    if not cands:
        if not why or all("密钥" in w for w in why):
            raise AIError("还没有填写图片 AI 的接口密钥（系统 → AI 接口）", kind="config")
        raise AIError(why[0], kind="config")
    _budget(cfg, task)
    order = cands
    if ref_png and want_edit:
        def edit_model(pid, m, p):
            if pid in ("fal", "replicate"):
                mm = m if C.edit_capable_model(pid, m) else p["edit_model"]
                return mm if mm and C.edit_capable_model(pid, mm) and C.EDIT in C.model_caps(pid, mm, p["caps_override"]) else ""
            return m if C.EDIT in C.model_caps(pid, m, p["caps_override"]) else ""
        ed = [(pid, edit_model(pid, m, p), p, True) for pid, m, p in cands if edit_model(pid, m, p)]
        order = ed + [(pid, m, p, False) for pid, m, p in cands]
    else:
        order = [(pid, m, p, False) for pid, m, p in cands]
    errs = []
    for i, (pid, model, p, edit) in enumerate(order):
        t0 = time.time()
        try:
            imgs = providers.image(p, model, prompt(edit) if callable(prompt) else prompt, ref_png if edit else None, aspect, n, edit)
        except AIError as e:
            e = AIError(providers.scrub(str(e), p["image_key"]), kind=e.kind, status=e.status)
            _log(cfg, task, pid, model, "image", ok=False, error=str(e), ms=(time.time() - t0) * 1000, fallback=i)
            errs.append(e)
            continue
        cost = 0.0
        try:
            cost = usage.log(cfg, task, pid, model, "edit" if edit else "image", images=len(imgs), ms=(time.time() - t0) * 1000,
                             fallback=i, edit=edit)
        except Exception:  # noqa: BLE001
            pass
        return {"images": imgs, "edited": edit, "provider": pid, "model": model, "cost": cost}
    if len(errs) == 1:
        raise errs[0]
    raise AIError("；".join(str(e)[:160] for e in errs), kind=errs[-1].kind)


def estimate_image(cfg, task="scene", n=1, edit=True):
    """出 n 张图大约多少钱（按第一个能用的出图服务商）。"""
    cands, _ = candidates(cfg, task, "image")
    if not cands:
        return 0.0
    pid, m, p = cands[0]
    em = m if C.edit_capable_model(pid, m) else p["edit_model"]
    can_edit = edit and bool(em) and C.edit_capable_model(pid, em) and C.EDIT in C.model_caps(pid, em, p["caps_override"])
    return usage.cost(cfg, pid, m, images=n, edit=can_edit)


def estimate_text(cfg, task, tin=1500, tout=400, n=1):
    cands, _ = candidates(cfg, task, "vision" if C.TASKS.get(task, ("", "", "", ""))[3] == "vision" else "text")
    if not cands:
        return 0.0
    pid, m, _p = cands[0]
    return usage.cost(cfg, pid, m, tin * n, tout * n)


def test(cfg, pid, kind="text"):
    """「测试连接」：返回 {ok, msg, ms}（出错信息里不带密钥）。"""
    p = conf.provider(cfg, pid)
    if not (p["image_key"] if kind == "image" else p["api_key"]):
        return {"ok": False, "msg": "还没有填写密钥", "ms": 0}
    t0 = time.time()
    try:
        out, tin, tout = providers.ping(p, kind)
    except AIError as e:
        return {"ok": False, "msg": providers.scrub(str(e), p["api_key"], p["image_key"])[:300], "ms": int((time.time() - t0) * 1000)}
    if kind == "text":
        _log(cfg, "general", pid, p["text_model"], "text", tin=tin, tout=tout, ms=(time.time() - t0) * 1000)
    return {"ok": True, "msg": str(out)[:80], "ms": int((time.time() - t0) * 1000)}


def png_b64(img, fmt="JPEG"):
    buf = io.BytesIO()
    img.save(buf, fmt, quality=85) if fmt == "JPEG" else img.save(buf, fmt)
    return base64.b64encode(buf.getvalue()).decode()
