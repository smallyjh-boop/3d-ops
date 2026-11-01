"""AI 接口设置：每个服务商的密钥 / 地址 / 模型，每个任务用哪个（含备用顺序）、费用上限、价格表；旧设置自动搬过来。

存在 config.json：
  ai_providers  {pid: {api_key, base_url, text_model, image_model, edit_model, image_key, image_base, image_quality, caps, enabled}}
  ai_tasks      {task: {chain: [{"p": pid, "m": 模型}], daily_thb, monthly_thb, daily_calls, hard}}
  ai_limits     {daily_thb, monthly_thb, hard}       全部任务合计的上限
  ai_prices     {"pid" 或 "pid:模型": {in, out, img, edit}}   泰铢（每百万 token / 每张图）
旧的键继续有效（老代码、老测试都还读）：ai_provider / ai_model / ai_api_key / ai_base_url = 默认文字 AI；
image_provider / image_model / image_api_key / image_api_base / image_quality = 默认出图 AI。
某个服务商在新结构里还没填过密钥时，用旧键里的密钥（所以升级后什么都不用改就能用）。
"""
import copy

from . import catalog as C

MASK = "******"


def legacy_text_pid(cfg):
    p = str(cfg.get("ai_provider") or "anthropic")
    return p if p in C.PROVIDERS and C.TEXT in C.PROVIDERS[p]["caps"] else "anthropic"


def legacy_image_pid(cfg):
    p = str(cfg.get("image_provider") or "openai")
    return p if p in C.IMAGE_PROVIDERS else "openai"


def _entry(cfg, pid):
    return dict(((cfg.get("ai_providers") or {}).get(pid)) or {})


def provider(cfg, pid):
    """解析后的服务商设置（含旧键兜底）。"""
    e = _entry(cfg, pid)
    cat = C.PROVIDERS.get(pid) or C.PROVIDERS["openai_compatible"]
    lt, li = legacy_text_pid(cfg), legacy_image_pid(cfg)
    key = (e.get("api_key") or "").strip() if "api_key" in e else ""
    if "api_key" not in e:
        if pid == lt:
            key = (cfg.get("ai_api_key") or "").strip()
        elif pid == li:
            key = (cfg.get("image_api_key") or "").strip()
    base = (e.get("base_url") or "").strip()
    if not base and pid == lt and pid in ("openai_compatible", "deepseek", "qwen"):
        base = (cfg.get("ai_base_url") or "").strip()
        if pid == "qwen" and "dashscope" not in base:
            base = ""
    if pid == "deepseek" and (not base or "deepseek" not in base):
        base = cat["base"]
    base = (base or cat["base"]).rstrip("/")
    text_model = (e.get("text_model") or "").strip() or (str(cfg.get("ai_model") or "").strip() if pid == lt else "") or cat.get("text", "")
    image_model = (e.get("image_model") or "").strip() or (str(cfg.get("image_model") or "").strip() if pid == li else "") or cat.get("image", "")
    legacy_img = (cfg.get("image_api_key") or "").strip() if pid == li else ""
    image_key = (e.get("image_key") or "").strip() or (key if "api_key" in e else (legacy_img or key))
    image_base = (e.get("image_base") or "").strip() or ((cfg.get("image_api_base") or "").strip() if pid == li else "") or base
    if pid == "gemini" and "openai.com" in image_base:
        image_base = cat["base"]
    return {"id": pid, "style": cat["style"], "api_key": key, "base_url": base, "text_model": text_model,
            "image_model": image_model, "edit_model": (e.get("edit_model") or "").strip() or cat.get("edit", ""),
            "image_key": image_key, "image_base": image_base.rstrip("/"),
            "image_quality": e.get("image_quality") or (cfg.get("image_quality") if pid == li else "") or "",
            "caps_override": [c for c in (e.get("caps") or []) if c in C.ALL_CAPS],
            "enabled": e.get("enabled", True) not in (False, 0, "0", "false"),
            "zh": cat["zh"], "th": cat["th"]}


def has_key(cfg, pid, kind="text"):
    p = provider(cfg, pid)
    return p["enabled"] and bool(p["image_key"] if kind == "image" else p["api_key"])


def caps(cfg, pid, model=None, kind="text"):
    p = provider(cfg, pid)
    m = model or (p["image_model"] if kind == "image" else p["text_model"])
    return C.model_caps(pid, m, p["caps_override"])


def task_conf(cfg, task):
    return dict(((cfg.get("ai_tasks") or {}).get(task)) or {})


def chain(cfg, task):
    """这个任务按顺序试哪些 (服务商, 模型)。模型空 = 服务商默认。"""
    grp, need = C.TASKS.get(task, C.TASKS["general"])[0], C.TASKS.get(task, C.TASKS["general"])[3]
    out = []
    for x in task_conf(cfg, task).get("chain") or []:
        p = (x or {}).get("p")
        if p in C.PROVIDERS and (p, x.get("m") or "") not in out:
            out.append((p, (x.get("m") or "").strip()))
    if out:
        return out
    if need == "image":
        return [(legacy_image_pid(cfg), "")]
    lt = legacy_text_pid(cfg)
    if grp == "vision" and lt != "anthropic" and has_key(cfg, "anthropic"):
        out.append(("anthropic", ""))          # 看图任务默认用 Claude（填了 Claude 的密钥时）
    out.append((lt, str(cfg.get("ai_model") or "").strip()))
    return out


def mask(key):
    key = str(key or "")
    if not key:
        return ""
    return (key[:3] + "…" + key[-4:]) if len(key) >= 12 else "••••"


def public_view(cfg):
    """给网页看：密钥只给打码后的样子。"""
    provs = []
    for pid, cat in C.PROVIDERS.items():
        p = provider(cfg, pid)
        e = _entry(cfg, pid)
        provs.append({"id": pid, "zh": cat["zh"], "th": cat["th"], "style": cat["style"], "kinds": [k for k in ("text", "image") if cat.get(k) or (k == "text" and C.TEXT in cat["caps"])],
                      "has_key": bool(p["api_key"]), "key_mask": mask(p["api_key"]), "has_image_key": bool(e.get("image_key")),
                      "image_key_mask": mask(e.get("image_key")), "base_url": e.get("base_url") or "", "base_default": cat["base"],
                      "text_model": e.get("text_model") or "", "image_model": e.get("image_model") or "", "edit_model": e.get("edit_model") or "",
                      "image_base": e.get("image_base") or "", "image_quality": e.get("image_quality") or "",
                      "def_text": p["text_model"], "def_image": p["image_model"], "def_edit": p["edit_model"],
                      "caps": caps(cfg, pid), "caps_override": p["caps_override"], "image_caps": caps(cfg, pid, kind="image"),
                      "enabled": p["enabled"], "legacy": pid in (legacy_text_pid(cfg), legacy_image_pid(cfg)) and "api_key" not in e and bool(p["api_key"])})
    tasks = []
    for tid, (grp, zh, th, need) in C.TASKS.items():
        tc = task_conf(cfg, tid)
        tasks.append({"id": tid, "group": grp, "zh": zh, "th": th, "need": need, "explicit": bool(tc.get("chain")),
                      "chain": [{"p": p, "m": m} for p, m in chain(cfg, tid)],
                      "daily_thb": tc.get("daily_thb") or 0, "monthly_thb": tc.get("monthly_thb") or 0,
                      "daily_calls": tc.get("daily_calls") or 0, "hard": bool(tc.get("hard"))})
    prices = copy.deepcopy(C.DEFAULT_PRICES)
    for k, v in (cfg.get("ai_prices") or {}).items():
        prices[k] = {**prices.get(k, {}), **(v or {})}
    return {"providers": provs, "tasks": tasks, "groups": C.GROUPS, "group_order": list(C.GROUPS), "cap_names": C.CAP_NAMES,
            "default_text": {"p": legacy_text_pid(cfg), "m": cfg.get("ai_model") or ""},
            "default_image": {"p": legacy_image_pid(cfg), "m": cfg.get("image_model") or ""},
            "limits": dict(cfg.get("ai_limits") or {}), "prices": prices}


def _num(v, lo=0.0):
    try:
        return max(lo, float(v or 0))
    except (TypeError, ValueError):
        return lo


def apply_update(cfg, body):
    """网页保存：返回要写进 config 的字段（只含改动的部分）。密钥：空 / 打码 = 不改；"-" = 清空。"""
    out = {}
    if isinstance(body.get("providers"), dict):
        provs = copy.deepcopy(cfg.get("ai_providers") or {})
        for pid, d in body["providers"].items():
            if pid not in C.PROVIDERS or not isinstance(d, dict):
                continue
            e = provs.setdefault(pid, {})
            for k in ("api_key", "image_key"):
                v = str(d.get(k) or "").strip()
                if v in ("", MASK) or "…" in v or "•" in v:
                    continue
                e[k] = "" if v == "-" else v
            for k in ("base_url", "text_model", "image_model", "edit_model", "image_base", "image_quality"):
                if k in d:
                    e[k] = str(d.get(k) or "").strip()[:300]
            if "caps" in d:
                e["caps"] = [c for c in (d.get("caps") or []) if c in C.ALL_CAPS]
            if "enabled" in d:
                e["enabled"] = bool(d["enabled"])
        out["ai_providers"] = provs
    if isinstance(body.get("tasks"), dict):
        tasks = copy.deepcopy(cfg.get("ai_tasks") or {})
        for tid, d in body["tasks"].items():
            if tid not in C.TASKS or not isinstance(d, dict):
                continue
            t = tasks.setdefault(tid, {})
            if "chain" in d:
                t["chain"] = [{"p": x["p"], "m": str(x.get("m") or "").strip()[:120]} for x in (d.get("chain") or [])[:5]
                              if isinstance(x, dict) and x.get("p") in C.PROVIDERS]
            for k in ("daily_thb", "monthly_thb", "daily_calls"):
                if k in d:
                    t[k] = _num(d[k])
            if "hard" in d:
                t["hard"] = bool(d["hard"])
        out["ai_tasks"] = tasks
    if isinstance(body.get("limits"), dict):
        lim = body["limits"]
        out["ai_limits"] = {"daily_thb": _num(lim.get("daily_thb")), "monthly_thb": _num(lim.get("monthly_thb")), "hard": bool(lim.get("hard"))}
    if isinstance(body.get("prices"), dict):
        pr = {}
        for k, v in body["prices"].items():
            if isinstance(v, dict) and str(k).split(":")[0] in C.PROVIDERS:
                pr[str(k)[:150]] = {kk: _num(v.get(kk)) for kk in ("in", "out", "img", "edit") if v.get(kk) not in (None, "")}
        out["ai_prices"] = pr
    dt = body.get("default_text")
    if isinstance(dt, dict) and dt.get("p") in C.TEXT_PROVIDERS:
        out["ai_provider"] = dt["p"]
        out["ai_model"] = str(dt.get("m") or "").strip()[:120] or C.PROVIDERS[dt["p"]]["text"]
    di = body.get("default_image")
    if isinstance(di, dict) and di.get("p") in C.IMAGE_PROVIDERS:
        out["image_provider"] = di["p"]
        out["image_model"] = str(di.get("m") or "").strip()[:120]
    # 旧键跟着新设置走（老代码 / 系统检查还读 ai_api_key）
    merged = {**cfg, **out}
    if "ai_providers" in out or "ai_provider" in out:
        out["ai_api_key"] = provider(merged, legacy_text_pid(merged))["api_key"]
    return out


def sync_legacy(old, upd):
    """有地方用旧键改了密钥（旧的设置页、老代码、老测试）：同步到新结构里，免得新旧不一致。返回新的 upd。"""
    if "ai_providers" in upd or not ({"ai_api_key", "image_api_key"} & set(upd)):
        return upd
    merged = {**old, **upd}
    provs = copy.deepcopy(old.get("ai_providers") or {})
    changed = False
    if "ai_api_key" in upd:
        e = provs.get(legacy_text_pid(merged))
        if e is not None and "api_key" in e:
            e["api_key"] = str(upd.get("ai_api_key") or "").strip()
            changed = True
    if "image_api_key" in upd:
        pid = legacy_image_pid(merged)
        e = provs.get(pid)
        v = str(upd.get("image_api_key") or "").strip()
        if e is not None and "image_key" in e:
            e["image_key"], changed = v, True
        elif e is not None and "api_key" in e and pid != legacy_text_pid(merged):
            e["api_key"], changed = v, True
        elif e is not None and "api_key" in e and v != e.get("api_key"):
            e["image_key"], changed = v, True
    if changed:
        upd = dict(upd, ai_providers=provs)
    return upd


def migrate(cfg, cs_model=""):
    """第一次启动 v2.53：把旧设置接进新结构（只做一次；旧键保留并继续生效）。返回要写进 config 的字段，已经做过返回 {}。
    · 默认文字 AI = 旧的 ai_provider / ai_model / ai_api_key / ai_base_url（不复制密钥：这个服务商在「AI 接口」页保存过之后才用新结构里的）
    · 默认出图 AI = 旧的 image_provider / image_model / image_api_key / image_api_base / image_quality
    · 客服单独设的模型 → 「客服回复草稿」「客服翻译」两个任务
    · 拍照识别每天几次 → 「拍照识别产品」任务的每天次数上限（提醒）"""
    if cfg.get("ai_v2"):
        return {}
    lt, li = legacy_text_pid(cfg), legacy_image_pid(cfg)
    tasks = copy.deepcopy(cfg.get("ai_tasks") or {})
    if cs_model:
        for t in ("cs_draft", "cs_translate"):
            tasks.setdefault(t, {}).setdefault("chain", [{"p": lt, "m": cs_model}])
    try:
        rd = int(cfg.get("recog_ai_daily") or 0)
    except (TypeError, ValueError):
        rd = 0
    if rd:
        tasks.setdefault("recog", {}).setdefault("daily_calls", rd)
    found = {"text": {"p": lt, "m": cfg.get("ai_model") or "", "key": bool((cfg.get("ai_api_key") or "").strip())},
             "image": {"p": li, "m": cfg.get("image_model") or "", "key": bool((cfg.get("image_api_key") or "").strip())},
             "cs_model": cs_model, "recog_daily": rd}
    return {"ai_tasks": tasks, "ai_v2": 1, "ai_migrated": found}
