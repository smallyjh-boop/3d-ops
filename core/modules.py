"""模块框架（v2.29）——内核的一部分。

一个模块 = modules/<id>/ 一个文件夹，把这个功能用到的东西全装在里面：
    module.py      说明书：MODULE = {...}（名字、版本、依赖、菜单、权限、设置、事件、启动时做什么）
    api.py         网页接口：bp = flask.Blueprint(...)（可选）
    ui/page.html   页面（可选；打开这个页面时才加载）
    ui/page.js     前台代码（可选；注册 window.MODS["<id>"] = {show(tab)}）
    ui/page.css    样式（可选）
    i18n/th.json   泰文翻译 {"中文": "ไทย"}（可选）
    tests/*.py     这个模块的测试（tests/run_all.py 自动找到）
    README.md      说明和更新记录

MODULE 字段：
    id, name_zh, name_th, version, desc_zh, desc_th
    depends: ["其它模块 id"]            core: 不能关（默认 False）     default_on: 默认开（默认 True）
    menus: [{"tab": "页面 id", "mod": "放在哪个大菜单（goods / orders / cs / prod / inv / pur / biz / sys / home）",
             "zh": "菜单名", "th": "ชื่อเมนู", "roles": "owner,listing"（可选）}]
    owner_only: [("GET|POST|*", r"正则")]  只有老板能用的接口      production_allow: [...] 生产角色也能用的接口
    settings: [("分组标题", [("配置键", "说明", 类型?), ...])]   settings_module: 放在设置的哪个大分类（默认 "addons"）
    config_defaults: {"配置键": 默认值}     secrets: ["配置键"]（密钥：不发回浏览器）
    events: {"事件名": 处理函数}           startup: 函数（程序启动、模块开着时在后台线程里调用一次）

模块之间只能：调用对方说明书里写的对外函数，或者收发事件（emit / on）。不直接读写别的模块的数据表。

★ 对外：discover()  load_all(app)  enabled(mid)  set_enabled(mid, on)  listing(user)  emit(event, **data)  on(event, fn)
         i18n_th()  module_of_path(path)
"""
import importlib
import json
import os
import re
import threading
import time
import traceback

from .config import BASE_DIR, load_config, save_config

MOD_DIR = os.environ.get("LH_MODULES_DIR") or os.path.join(BASE_DIR, "modules")
_lock = threading.RLock()
_mods = {}            # id → {"meta": MODULE, "dir": 路径, "bp": Blueprint 或 None, "error": ""}
_handlers = {}        # 事件名 → [(模块 id, 函数)]
_event_log = []       # 最近的事件处理记录（系统检查里看）
_loaded = False
_prefixes = {}        # 接口前缀 → 模块 id（关掉的模块：接口返回 404）
_patterns = []        # v2.30：(正则, 模块 id)——地址中间有编号的接口，例如 /api/products/<id>/seo

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


# ---------------- 发现 ----------------
def _sources():
    """(包名, 文件夹)：modules/ + 环境变量 LH_EXTRA_MODULES 指定的文件夹（测试用，包名 = 文件夹名）。"""
    import sys
    out = [("modules", MOD_DIR)]
    extra = os.environ.get("LH_EXTRA_MODULES") or ""
    for d in [x for x in extra.split(os.pathsep) if x]:
        d = os.path.abspath(d)
        parent = os.path.dirname(d)
        if parent not in sys.path:
            sys.path.insert(0, parent)
        out.append((os.path.basename(d), d))
    return out


def discover():
    """扫描 modules/ 文件夹，读每个模块的说明书。出错的模块记下错误，不影响其它模块。"""
    found = {}
    for pkg, root in _sources():
        if os.path.isdir(root):
            found.update(_discover_in(pkg, root))
    return found


def _discover_in(pkg, root):
    found = {}
    for name in sorted(os.listdir(root)):
        d = os.path.join(root, name)
        if not ID_RE.match(name) or not os.path.isfile(os.path.join(d, "module.py")):
            continue
        rec = {"meta": {"id": name, "name_zh": name}, "dir": d, "bp": None, "error": "", "py": None, "pkg": pkg}
        if name in found:
            continue
        try:
            m = importlib.import_module(f"{pkg}.{name}.module")
            meta = dict(getattr(m, "MODULE", {}) or {})
            if meta.get("id") != name:
                raise ValueError(f"说明书里的 id「{meta.get('id')}」和文件夹名「{name}」不一样")
            meta.setdefault("version", "1.0")
            meta.setdefault("depends", [])
            meta.setdefault("core", False)
            meta.setdefault("default_on", True)
            rec["meta"], rec["py"] = meta, m
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"说明书读不出来：{e}"
        found[name] = rec
    return found


# ---------------- 开关 ----------------
_sets_cache = {"key": None, "off": set(), "on": set()}


def _sets():
    """模块开关只看设置里的 modules_off / modules_on；按设置文件的修改时间缓存（生产、库存里每次记账都要问一次，不能每次读文件）。"""
    from .config import CONFIG_PATH
    try:
        st = os.stat(CONFIG_PATH)
        key = (CONFIG_PATH, st.st_mtime_ns, st.st_size)
    except OSError:
        key = (CONFIG_PATH, None, None)
    if _sets_cache["key"] != key:
        cfg = load_config()
        _sets_cache.update(key=key, off=set(cfg.get("modules_off") or []), on=set(cfg.get("modules_on") or []))
    return _sets_cache


def _off_set(cfg=None):
    if cfg is None:
        return set(_sets()["off"])
    return set(cfg.get("modules_off") or [])


def _on_set(cfg=None):
    if cfg is None:
        return set(_sets()["on"])
    return set(cfg.get("modules_on") or [])


def is_loaded():
    """程序已经装载了模块（app 启动过）。单独用 core 的脚本 / 电脑加速程序里没有装载，主链路按「全开」处理。"""
    return _loaded


def enabled(mid, cfg=None):
    rec = _mods.get(mid)
    if not rec or rec["error"]:
        return False
    meta = rec["meta"]
    if meta.get("core"):
        return True
    if mid in _off_set(cfg):
        return False
    if not meta.get("default_on", True) and mid not in _on_set(cfg):
        return False
    return all(enabled(dep, cfg) for dep in meta.get("depends") or [])


def dependents(mid):
    return [k for k, r in _mods.items() if mid in (r["meta"].get("depends") or [])]


def set_enabled(mid, on):
    """开 / 关一个模块。返回 {ok, also_off: [跟着关掉的模块]}。"""
    rec = _mods.get(mid)
    if not rec:
        raise ValueError("没有这个模块")
    if rec["error"]:
        raise ValueError(rec["error"])
    if rec["meta"].get("core") and not on:
        raise ValueError("这是基础模块，不能关")
    cfg = load_config()
    off, onl = _off_set(cfg), _on_set(cfg)
    if on:
        missing = [d for d in rec["meta"].get("depends") or [] if not enabled(d, cfg)]
        if missing:
            raise ValueError("要先打开它依赖的模块：" + "、".join(name_of(d) for d in missing))
        off.discard(mid)
        onl.add(mid)
    else:
        off.add(mid)
        onl.discard(mid)
    save_config({"modules_off": sorted(off), "modules_on": sorted(onl)})
    also = [d for d in dependents(mid) if not on]
    if on:
        _start(mid)
    return {"ok": True, "also_off": also}


def name_of(mid, th=False):
    m = (_mods.get(mid) or {}).get("meta") or {}
    return (m.get("name_th") if th else None) or m.get("name_zh") or mid


# ---------------- 装载 ----------------
def load_all(app):
    """程序启动时调用一次：注册接口、权限、设置、事件、默认配置。关着的模块也注册（打开时不用重启），
    但它的接口会被挡住（404）、菜单不显示、后台任务不启动。"""
    global _loaded
    from . import auth, settings_schema
    from . import config as C
    with _lock:
        if _loaded:
            return
        _mods.clear()
        _mods.update(discover())
        for mid, rec in _mods.items():
            if rec["error"]:
                continue
            meta = rec["meta"]
            try:
                for k, v in (meta.get("config_defaults") or {}).items():
                    C.DEFAULT_CONFIG.setdefault(k, v)
                for k in meta.get("secrets") or []:
                    if k not in auth.SECRET_KEYS:
                        auth.SECRET_KEYS = tuple(auth.SECRET_KEYS) + (k,)
                for pth in meta.get("public_paths") or []:          # 不用登录的地址（例如一次性下载码）
                    if pth not in auth.PUBLIC:
                        auth.PUBLIC = tuple(auth.PUBLIC) + (pth,)
                        _prefixes.setdefault(pth, mid)
                for rule in meta.get("perm_rules") or []:           # 需要特别权限的接口 (方法, 正则, 权限键)
                    auth.PERM_RULES.append(tuple(rule))
                for rule in meta.get("owner_only") or []:
                    auth.OWNER_ONLY.append(tuple(rule))
                for rule in meta.get("production_allow") or []:
                    auth.PRODUCTION_ALLOW.append(tuple(rule))
                for title, fields in meta.get("settings") or []:
                    settings_schema.register(meta.get("settings_module") or "addons", title, fields, module_of=mid)
                for ev, fn in (meta.get("events") or {}).items():
                    _handlers.setdefault(ev, []).append((mid, fn))
                if os.path.isfile(os.path.join(rec["dir"], "api.py")):
                    api = importlib.import_module(f"{rec.get('pkg') or 'modules'}.{mid}.api")
                    bp = getattr(api, "bp", None)
                    if bp is not None:
                        app.register_blueprint(bp)
                        rec["bp"] = bp
                        for p in getattr(api, "PREFIXES", []) or []:
                            _prefixes[p] = mid
                        for p in getattr(api, "PATTERNS", []) or []:
                            _patterns.append((re.compile(p), mid))
                _prefixes.setdefault(f"/api/m/{mid}/", mid)
            except Exception as e:  # noqa: BLE001
                rec["error"] = f"装载出错：{e}"
                _log("load", mid, rec["error"], traceback.format_exc())
        _loaded = True

    @app.before_request
    def _mod_guard():
        from flask import jsonify, request
        mid = module_of_path(request.path)
        if mid and not enabled(mid):
            if request.path.startswith("/api/"):
                return jsonify({"error": f"「{name_of(mid)}」模块没有打开（设置 → 模块管理）"}), 404
            return "模块没有打开", 404
        return None

    for mid in list(_mods):
        _start(mid)


_started = set()


def _start(mid):
    rec = _mods.get(mid)
    if not rec or rec["error"] or mid in _started or not enabled(mid):
        return
    fn = rec["meta"].get("startup")
    _started.add(mid)
    if not fn or os.environ.get("LH_NO_MODULE_STARTUP"):
        return

    def go():
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            _log("startup", mid, str(e), traceback.format_exc())
    threading.Thread(target=go, daemon=True, name=f"mod-{mid}").start()


def module_of_path(path):
    """接口路径属于哪个模块（只认模块自己声明的前缀；/static/m/<id>/ 是模块的页面文件）。"""
    if path.startswith("/m/"):
        mid = path.split("/")[2] if len(path.split("/")) > 2 else ""
        return mid if mid in _mods else None
    best = max((p for p in _prefixes if path.startswith(p)), key=len, default=None)   # 最长的前缀优先（/api/inv/po 属于采购，不属于库存）
    if best is not None:
        return _prefixes[best]
    for rx, mid in _patterns:
        if rx.match(path):
            return mid
    return None


# ---------------- 事件 ----------------
def on(event, fn, mid="core"):
    _handlers.setdefault(event, []).append((mid, fn))


def emit(event, **data):
    """广播一个事件：开着的模块里收听它的处理函数依次调用。一个出错不影响其它的（记到系统检查里）。
    返回 {模块 id: 返回值 或 {"error": ...}}。"""
    out = {}
    for mid, fn in list(_handlers.get(event, [])):
        if mid != "core" and not enabled(mid):
            continue
        try:
            out[mid] = fn(**data)
            _log(event, mid, "", "")
        except Exception as e:  # noqa: BLE001
            out[mid] = {"error": str(e)[:300]}
            _log(event, mid, str(e)[:300], traceback.format_exc())
    return out


def _log(event, mid, err, tb):
    _event_log.insert(0, {"at": time.time(), "event": event, "module": mid, "error": err})
    del _event_log[200:]
    if err:
        try:
            from . import diag
            diag.log.error("模块 %s 处理 %s 出错：%s\n%s", mid, event, err, tb[-1500:])
        except Exception:  # noqa: BLE001
            pass


def recent_events(n=50, errors_only=False):
    return [e for e in _event_log if e["error"] or not errors_only][:n]


# ---------------- 给前台 ----------------
UI_NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}\.(html|js|css)$")


def _ui_files(rec):
    """页面文件：html（多个页面写在一个 page.html 里，每页一个 <section id="tab-…">）、page_js（打开页面时加载）、
    boot_js（程序一打开就加载：例如右上角提醒、产品编辑里的小部件）、css。说明书里可以写 "ui": {...} 改默认值。"""
    ui = os.path.join(rec["dir"], "ui")
    has = lambda n: os.path.isfile(os.path.join(ui, n))  # noqa: E731
    conf = dict(rec["meta"].get("ui") or {})
    return {"html": conf.get("html", "page.html") if has(conf.get("html", "page.html")) else "",
            "page_js": [n for n in conf.get("page_js", ["page.js"]) if has(n)],
            "boot_js": [n for n in conf.get("boot_js", ["boot.js"]) if has(n)],
            "css": [n for n in conf.get("css", ["page.css"]) if has(n)],
            # v2.31：inline = 页面直接写进首页（主链路的页面，一打开就要用）；eager_js = 跟着首页按顺序加载的 js
            "inline": bool(conf.get("inline")),
            "eager_js": [n for n in conf.get("eager_js", []) if has(n)]}


def inline_parts():
    """首页要直接放进去的模块页面和 js（开着的、inline 的模块，按 order 排）。返回 (html, [(模块, js 文件)], [(模块, css 文件)])。"""
    html, js, css = [], [], []
    cfg = load_config()
    for mid, rec in sorted(_mods.items(), key=lambda kv: (kv[1]["meta"].get("order", 50), kv[0])):
        if rec["error"] or not enabled(mid, cfg):
            continue
        ui = _ui_files(rec)
        if ui["inline"] and ui["html"]:
            try:
                with open(os.path.join(rec["dir"], "ui", ui["html"]), encoding="utf-8") as f:
                    t = f.read()
                t = re.sub(r'<section id="(tab-[\w-]+)" class="panel hidden"', rf'<section id="\1" class="panel hidden" data-module="{mid}" data-ready="1"', t)
                html.append(f"<!-- 模块 {mid} -->\n" + t)
            except OSError as e:
                _log("ui", mid, str(e), "")
        js += [(mid, n) for n in ui["eager_js"]]
        if ui["inline"]:
            css += [(mid, n) for n in ui["css"]]
    return "\n".join(html), js, css


def listing(user=None, all_=False):
    """模块列表（模块管理页 + 前台菜单）。user 不是老板时只给开着的、有权限的菜单。"""
    out = []
    cfg = load_config()
    for mid, rec in sorted(_mods.items(), key=lambda kv: (kv[1]["meta"].get("order", 50), kv[0])):
        meta = rec["meta"]
        on_ = enabled(mid, cfg)
        if not on_ and not all_:
            continue
        menus = []
        for m in meta.get("menus") or []:
            roles = [r for r in str(m.get("roles") or "owner,listing,production").split(",") if r]
            if user and user.get("role") not in roles and user.get("role") != "owner":
                continue
            menus.append({"tab": m["tab"], "mod": m.get("mod") or "sys", "zh": m.get("zh") or m["tab"], "th": m.get("th") or m.get("zh") or m["tab"],
                          "roles": ",".join(roles), "after": m.get("after") or "", "before": m.get("before") or "", "panel": m.get("panel") or m["tab"],
                          "ghost": bool(m.get("ghost"))})
        out.append({"id": mid, "name_zh": meta.get("name_zh") or mid, "name_th": meta.get("name_th") or meta.get("name_zh") or mid,
                    "desc_zh": meta.get("desc_zh") or "", "desc_th": meta.get("desc_th") or "", "version": meta.get("version"),
                    "depends": meta.get("depends") or [], "core": bool(meta.get("core")), "enabled": on_, "error": rec["error"],
                    "menus": menus, "ui": _ui_files(rec), "dependents": dependents(mid),
                    "settings_cards": list(meta.get("settings_cards") or ([meta.get("settings_module") or "addons"] if meta.get("settings_card") else []))})
    return out


def i18n_th():
    """所有开着的模块的泰文翻译合在一起（首页里注入给前台的翻译表）。"""
    out = {}
    for mid, rec in _mods.items():
        p = os.path.join(rec["dir"], "i18n", "th.json")
        if not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                out.update(json.load(f))
        except (OSError, ValueError):
            pass
    return out


def ui_path(mid, name):
    rec = _mods.get(mid)
    if not rec or not UI_NAME.match(name or ""):
        return None
    p = os.path.join(rec["dir"], "ui", name)
    return p if os.path.isfile(p) else None


def get(mid):
    return _mods.get(mid)


def public(mid):
    """别的模块 / 内核调用这个模块的对外函数：模块开着就返回说明书里的 public（一个 python 模块），关着返回 None。
    用法：d = modules.public("desk"); user = d.user_of_key(name) if d else """""
    rec = _mods.get(mid)
    if not rec or not enabled(mid):
        return None
    return rec["meta"].get("public")
