"""公共部分：Flask 应用、权限、通用小工具（err、_uname、_need…）。各模块的路由在 web/ 下面的其他文件里，
都用 `from web.common import *` 拿到这里的东西。"""


import datetime as dt


import os


import re


import shutil


import sys


import threading


import time


import uuid


import webbrowser


import zipfile


from PIL import Image


from flask import Flask, abort, jsonify, redirect, request, send_file, send_from_directory, session


from core import (ai_copy, scenes, attributes, catalog, categories, codes, images, imghost,
                  lazada_template, pricing, shopee, slicer, store)


from core.config import BASE_DIR, DATA_DIR, DEFAULT_CONFIG, LIST_KEYS, load_config, save_config


def _read_version():
    """版本号只写在 app.py 里（在线升级按它认版本），这里读出来给页面和接口用。"""
    try:
        with open(os.path.join(BASE_DIR, "app.py"), encoding="utf-8") as f:
            m = re.search(r'^VERSION\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1) if m else "0"
    except OSError:
        return "0"


VERSION = _read_version()


TEMPLATE_DIR = categories.TEMPLATE_DIR


EXPORT_DIR = os.path.join(DATA_DIR, "exports")


ALLOWED_IMG = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


app = Flask("app", root_path=BASE_DIR, static_folder="static", static_url_path="/static")


from core import auth, db  # noqa: E402  登录与权限


auth.install(app)


app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024


from core import diag  # noqa: E402  运行日志 / 诊断包（v2.14.1）


diag.setup(app)


def _no_perm(key):
    return f"你的账号没有「{dict(db.PERMS).get(key, key)}」的权限，请老板在 系统 → 设置 → 账号与权限 里开通"


def _need(key):
    """路由里按内容判断的权限（PERM_RULES 只能按路径）。没有权限返回错误响应。"""
    u = auth.current_user()
    if u and not auth.has_perm(u, key):
        return err(_no_perm(key), 403)
    return None


def maybe_async(label, fn, kind="", link=""):
    """?async=1 时把耗时的操作放到后台（返回 202 和任务号，浏览器轮询 /api/bg/<任务号>）；否则当场执行。
    fn 在后台线程里跑，要用 app.test_request_context 才能用 jsonify，所以这里包一层。"""
    if request.args.get("async") != "1":
        return fn()
    from core import bgjobs
    user = auth.current_user() or {}
    uname = user.get("username", "")

    def run():
        with app.app_context(), app.test_request_context():
            from flask import g
            g.user = user
            return fn()
    j = bgjobs.start(run, label, uname, kind, link)
    return jsonify({"ok": True, "job": j["id"]}), 202


# 这些接口要等 AI / 网络（十几秒到一分钟）：浏览器加 ?async=1 时整个请求放到后台重放（v2.20.2），进任务中心。
# 值 = 任务分类（任务中心显示用）
ASYNC_ROUTES = {"ai_category": "ai_cat", "ai_shopee_category": "ai_cat", "fill_attrs": "ai_cat", "print_advice_api": "ai_advice",
                "ad_suggest": "ai", "scenes_ai_bg": "ai_img", "scene_ai": "ai_img", "image_host": "img_host",
                "ai_keywords": "ai_kw", "ai_back": "ai", "print_file_ai": "ai_check", "ai_english": "ai_en", "ai_complete": "ai_fill"}


@app.before_request
def _async_replay():
    short = (request.endpoint or "").split(".")[-1]          # v2.31：模块的接口 endpoint 是「m_goods.ai_category」
    if request.args.get("async") != "1" or short not in ASYNC_ROUTES:
        return None
    from core import bgjobs
    user = auth.current_user() or {}
    body = request.get_data()
    ctype = request.headers.get("Content-Type", "")
    qs = [(k, v) for k, vs in request.args.lists() for v in vs if k != "async"]
    path, method, ep, va = request.path, request.method, request.endpoint, dict(request.view_args or {})

    def run():
        with app.app_context(), app.test_request_context(path, method=method, data=body, content_type=ctype, query_string=qs):
            from flask import g
            g.user = user
            return app.view_functions[ep](**va)
    pid = va.get("pid") or ""
    j = bgjobs.start(run, f"{short} {pid}".strip(), user.get("username", ""), ASYNC_ROUTES[short], pid)
    return jsonify({"ok": True, "job": j["id"]}), 202


def err(msg, code=400):
    return jsonify({"error": msg}), code


@app.errorhandler(Exception)
def handle_any(e):
    if isinstance(getattr(e, "code", None), int) and e.code < 500:
        return err(getattr(e, "description", None) or str(e), e.code)
    u = auth.current_user() or {}
    diag.server_error(e, request.method, request.path, u.get("username", ""))
    return err(f"程序出错：{e}（已记录到运行日志）", 500)


def _prefix(cfg):
    return re.sub(r"[^A-Za-z0-9]", "", cfg.get("sku_prefix") or "P")[:6] or "P"


def _check(cfg, p):
    cat = categories.get((p.get("category") or {}).get("id"))
    if lazada_template.ensure_brand(p, cat, cfg):       # 品牌空着：自动填 No Brand 并保存
        try:
            q = store.load(p["id"])
            q["attributes"] = p["attributes"]
            store.save(q)
        except (FileNotFoundError, KeyError):
            pass
    return lazada_template.check_product(p, pricing.price_product(cfg, p), cat, cfg)


DEFAULT_INT = {k: v for k, v in DEFAULT_CONFIG.items() if isinstance(v, int) and not isinstance(v, bool)}


def _enrich_products(out):
    """产品库：切片文件状态、近 30 天销量。"""
    c = db.conn()
    best = {}
    for r in c.execute("SELECT product_id, status FROM print_files WHERE active=1"):
        cur = best.get(r["product_id"])
        if not cur or print_files.STATUS_RANK.get(r["status"], 0) > print_files.STATUS_RANK.get(cur, 0):
            best[r["product_id"]] = r["status"]
    sold = {r["product_id"]: r["q"] for r in c.execute(
        """SELECT i.product_id, SUM(i.qty) q FROM order_items i JOIN orders o ON o.id=i.order_id
           WHERE o.order_time>=? AND o.status NOT IN ('cancelled','unpaid','quote') GROUP BY i.product_id""",
        (time.time() - 30 * 86400,))}
    for it in out:
        it["file_status"] = best.get(it["id"])
        it["sold30"] = sold.get(it["id"], 0)


def _lst(p, platform):
    from core import listing
    st = listing.status_of(p, platform)
    return {"status": st.get("status") or "none", "note": st.get("note", ""), "batch": st.get("batch"), "at": st.get("at")}


def _rename_spec_links(pid, old, p, renames):
    from core import db as _db
    sr = old.get("spec_recipes") or {}
    p["spec_recipes"] = {renames.get(k, k): v for k, v in sr.items()}
    for e in p.get("model_lib") or []:
        if e.get("variant") in renames:
            e["variant"] = renames[e["variant"]]
    c = _db.conn()
    for o, n in renames.items():
        c.execute("UPDATE print_files SET spec=? WHERE product_id=? AND COALESCE(spec,'')=?", (n, pid, o))
    c.commit()


def _save_from_client(pid, p):
    if p.get("id") != pid:
        abort(400, "产品编码不一致")
    cfg = load_config()
    try:
        old = store.load(pid)
        p["images"] = old.get("images", [])
        p["white_bg"] = old.get("white_bg")
        p["exported_at"] = old.get("exported_at")
        p["shopee_exported_at"] = old.get("shopee_exported_at")
        p["listing"] = old.get("listing")            # 上架进度由导出 / 标记接口维护
        if "specs" in old:
            p["specs"] = old.get("specs")              # 规格由选品工具同步 / 「确认规格」接口维护（v2.16）
        for k in ("seo_review", "seo_undo", "seo_log", "title_changed_at", "copy_dirty_after_export"):   # v2.24：搜索优化由后台维护
            if k in old:
                p[k] = old[k]
            else:
                p.pop(k, None)
        for k in ("ip_risk", "curator_listing"):     # 侵权确认走单独的接口；选品工具原始文案只读
            if k in old:
                p[k] = old.get(k)
        if "active" not in p and "active" in old:
            p["active"] = old["active"]
        p["model"] = old.get("model")              # 模型和打印建议由后台维护
        p["model_lib"] = old.get("model_lib") or []  # 模型库由后台维护（v2.13）；没有时存空列表，不存 null
        from core import specs as _specs
        bad = _specs.check_variants(p, old)          # v2.22：不能加出重复的变体 / 选品工具没有的规格
        if bad:
            abort(400, bad)
        # v2.22.1：规格改名（按 SKU 认出来）→ 模型对应、打印方案、切片文件、模型库标注一起跟着改名
        renames = {}
        old_by_sku = {(x.get("sku") or "").upper(): (x.get("opt2_zh") or "").strip() for x in old.get("variants") or [] if x.get("sku")}
        new_names = {(v.get("opt2_zh") or "").strip() for v in p.get("variants") or []}
        for v in p.get("variants") or []:
            o = old_by_sku.get((v.get("sku") or "").upper())
            n = (v.get("opt2_zh") or "").strip()
            if o and n and o != n and o not in new_names:
                renames.setdefault(o, n)
        if renames:
            _rename_spec_links(pid, old, p, renames)
        # 规格用哪个模型由「规格用哪个模型」维护（v2.22）：按规格从已保存的产品里取，不信页面上可能过时的值
        spec_model = {}
        for x in old.get("variants") or []:
            if x.get("model_lib_id"):
                on = (x.get("opt2_zh") or "").strip()
                spec_model.setdefault(renames.get(on, on), (x["model_lib_id"], x.get("model_file")))
        for v in p.get("variants") or []:
            mm = spec_model.get((v.get("opt2_zh") or "").strip())
            if mm:
                v["model_lib_id"], v["model_file"] = mm
            else:
                v.pop("model_lib_id", None)
        p["print_advice"] = old.get("print_advice")
        p["recipe"] = old.get("recipe")            # 打印方案、分组有单独的接口保存
        p["groups"] = old.get("groups") or []
        p["source"] = old.get("source")            # 选品工具来源信息、下载的原始文件
        p["source_files"] = old.get("source_files")
        for k in ("edit_rev", "edited_by", "edited_at"):
            p[k] = old.get(k)
        store.bump_rev(p, _uname())
        # 选品工具推过来的草稿：填了颜色就算补齐了
        p["draft"] = bool(old.get("draft")) and not any((v.get("opt1_zh") or "").strip() for v in p.get("variants", []))
        if old.get("exported_at"):
            old_sku = [v.get("sku") for v in old.get("variants", [])]
            for i, v in enumerate(p.get("variants", [])):
                if i < len(old_sku) and old_sku[i]:
                    v["sku"] = old_sku[i]
    except FileNotFoundError:
        pass
    codes.ensure_skus(cfg, p)
    cat = categories.get((p.get("category") or {}).get("id"))
    if cat and attributes.remember_manual(cfg, p, cat):
        save_config({"category_memory": cfg["category_memory"]})
    if attributes.remember_shopee(cfg, p):
        save_config({"shopee_cat_map": cfg["shopee_cat_map"]})
    return store.save(p)


def _conflict(pid, p):
    """编辑页打开后，别人（或运营写回）改过这个产品：返回 409，让页面问一下再覆盖。"""
    if request.args.get("force") or p.get("edit_rev") is None:
        return None
    try:
        old = store.load(pid)
    except FileNotFoundError:
        return None
    if int(old.get("edit_rev") or 0) == int(p.get("edit_rev") or 0):
        return None
    when = time.strftime("%m-%d %H:%M", time.localtime(old.get("edited_at") or time.time()))
    r = jsonify({"error": f"这个产品在你打开之后被「{old.get('edited_by') or '别人'}」改过（{when}）。", "conflict": True,
                 "edited_by": old.get("edited_by"), "edited_at": old.get("edited_at")})
    return r, 409


def _apply_fill(cfg, p, cat, use_ai=True):
    attrs, pkg = attributes.fill(cfg, p, cat, use_ai=use_ai)
    p["attributes"] = attrs
    if pkg and p.get("package_status") == "default":
        try:
            dims = {k: round(float(pkg[k]), 1) for k in ("length", "width", "height")}
            if all(0.01 <= d <= 200 for d in dims.values()):
                p["package"] = dims
                p["package_status"] = "ai" if pkg.get("sure") else "check"
        except (KeyError, TypeError, ValueError):
            pass
    return p


_SP_KW_CACHE = {}


def _check_shopee(cfg, p):
    e1, w1 = _check(cfg, p)
    # Lazada 专属的检查项不影响 Shopee
    skip = ("Lazada 类目", "类目对应的模板", "AI 对类目不确定", "属性「", "类目属性还没填写")
    e1 = [x for x in e1 if not any(s in x for s in skip)]
    e2, w2 = shopee.check_product(p, pricing.price_product(cfg, p), cfg)
    errs = list(dict.fromkeys(e1 + e2))
    return errs, list(dict.fromkeys(w1 + w2))


def _advised_cfg(cfg, p):
    """产品启用了「打印建议」参数时，估算按建议的填充率/壁数/支撑来算。"""
    adv = p.get("print_advice") or {}
    if not adv.get("applied"):
        return cfg
    c = dict(cfg)
    c["est_infill"] = adv.get("infill_pct", 15) / 100
    c["est_shell_mm"] = round(adv.get("walls", 2) * 0.42, 2)
    c["est_support_factor"] = 1.0 if adv.get("supports") == "none" else 1.15
    return c


def _learn(cfg, p, real_grams):
    est = ((p.get("model") or {}).get("estimate") or {}).get("grams")
    if est and real_grams:
        slicer.calibrate(cfg, est, real_grams)
        save_config({"est_calibration": cfg["est_calibration"], "est_calibration_n": cfg["est_calibration_n"]})


def _add_images(p, items, replace_renders=False, white_bg=False):
    """把 PIL 图片加入产品图片。items: [{"img", "kind", "color"}]。kind=main/angle/dims（渲染图）或 scene（场景图）。"""
    from PIL import Image
    cfg = load_config()
    pid = p["id"]
    size = int(cfg["image_size"])
    added = []
    for item in items:
        img = item["img"].convert("RGB")
        w, h = img.size
        if w != h:
            s0 = min(w, h)
            img = img.crop(((w - s0) // 2, (h - s0) // 2, (w - s0) // 2 + s0, (h - s0) // 2 + s0))
        if img.size != (size, size):
            img = img.resize((size, size), Image.LANCZOS)
        kind = item.get("kind", "")
        name = f"{'s' if kind == 'scene' else 'r'}_{uuid.uuid4().hex[:10]}.jpg"
        img.save(os.path.join(store.image_dir(pid, "raw"), name), "JPEG", quality=95, subsampling=0)
        img.save(os.path.join(store.image_dir(pid, "out"), name), "JPEG", quality=95, subsampling=0)
        entry = {"file": name, "raw": name, "processed": True, "url": "", "color": item.get("color", "")}
        if kind == "scene":
            entry["scene"] = True
            if item.get("note"):
                entry["note"] = item["note"]
        else:
            entry["render"] = kind
        if replace_renders and not added:
            p["images"] = [i for i in p.get("images", []) if not i.get("render")]
        p.setdefault("images", []).append(entry)
        added.append(entry)
        if item.get("color") and kind == "main":
            for v in p.get("variants", []):
                if (v.get("opt1_zh") or "").strip() == item["color"]:
                    v["image"] = name
    if white_bg and added:
        p["white_bg"] = {"file": added[0]["file"], "url": ""}
    # 排序：主图（各颜色）→ 场景图 → 多角度 → 尺寸图 → 实拍图
    order = {"main": 0, "angle": 2, "dims": 3}

    def rank(i):
        if i.get("render"):
            return order.get(i["render"], 4)
        return 1 if i.get("scene") else 5
    p["images"] = sorted(p.get("images", []), key=rank)
    store.save(p)
    return added


def _decode_data_url(data):
    import base64
    import io as _io
    from PIL import Image
    if "," in data:
        data = data.split(",", 1)[1]
    img = Image.open(_io.BytesIO(base64.b64decode(data)))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB")


# ---- 修图（v2.14）：去背景、去水印 / 杂物、保存修好的图 ----
from core import imgtools  # noqa: E402


# ---------------- AI 文案 ----------------
def _cat_name(p):
    c = p.get("category") or {}
    return c.get("path") or c.get("name") or ""


def _after_export(platform, pids, files, body):
    """导出成功：建一个上架批次，产品改成「待上传」；选了分组的顺便加进分组。"""
    from core import listing
    gid = body.get("group_id")
    try:
        gid = int(gid) if gid not in (None, "", "0", 0) else None
    except (TypeError, ValueError):
        gid = None
    if gid:
        extras.group_assign(pids, gid, True)
    return listing.create_batch(platform, pids, files, body.get("batch_name") or "", gid, _uname())


# ---------------- 订单 / 生产 / 耗材 / 利润 ----------------
from core import finance, materials, orders as orders_mod, production  # noqa: E402


for _m in (orders_mod, production, materials, finance):
    _m.init()


def _uname():
    u = auth.current_user()
    return (u or {}).get("username", "")


def _strip_order(o):
    if auth.is_owner():
        return o
    for k in ("order_total", "platform_fee", "shipping_fee", "profit") + orders_mod.MONEY_FIELDS:
        o.pop(k, None)
    if isinstance(o.get("buyer_profile"), dict):
        o["buyer_profile"].pop("spent", None)
    if auth.current_user()["role"] == "production":
        for it in o.get("items") or []:
            it.pop("unit_price", None); it.pop("item_total", None)
    return o


def _cancel_denied(oid, b):
    """改成「已取消 / 拒收」要 orders.cancel 权限（状态没变不算）。"""
    st = b.get("status")
    if st not in ("cancelled", "delivery_failed"):
        return None
    try:
        if orders_mod.get_order(oid)["status"] == st:
            return None
    except Exception:  # noqa: BLE001
        pass
    return _need("orders.cancel")


# ---------------- 面单 ----------------
from core import labels  # noqa: E402


# ---------------- 打印机 / 打印文件库 ----------------
from core import print_files, printers as printers_mod  # noqa: E402


print_files.init()


printers_mod.on_change(production.on_printer_change)


CONN_SECRET = ("access_code",)


def _printer_list():
    cfg = load_config()
    owner = auth.is_owner()
    out = []
    for i, p in enumerate(cfg.get("printers") or []):
        c = dict(p.get("conn") or {})
        for k in CONN_SECRET:
            if c.get(k):
                c[k] = "******" if owner else ""
        if not owner:
            c = {"type": c.get("type", "none"), "loaded": c.get("loaded", "")}
        st = printers_mod.get_status(i)
        out.append({"index": i, "name": p.get("name", f"打印机{i + 1}"), "code": p.get("code") or f"#{i + 1}",
                    "enabled": p.get("enabled", True) is not False, "conn": c, "status": st,
                    "status_zh": printers_mod.STATE_ZH.get(st.get("state") or "none", "")})
    return out


def _model_names():
    """不重复的机型名（同机型多台只出现一次，切片文件 / 打印方案按机型）。"""
    return list(dict.fromkeys(p.get("name") for p in load_config().get("printers") or []))


def _model_first_idx():
    names = [p.get("name") for p in load_config().get("printers") or []]
    return [names.index(n) for n in _model_names()]


def _printer_index(name):
    for i, p in enumerate(load_config().get("printers") or []):
        if p.get("name") == name:
            return i
    return None


# ---- 模型库（v2.13）：一个产品的全部模型文件，选哪个 / 哪几个当 3D 模型 ----
from core import modellib  # noqa: E402


_MESH_CACHE = {}


# ---------------- 售后 / 备份 / 分组 / 工作台 / 打包核对 ----------------
from core import extras  # noqa: E402


extras.init()


from core import listing  # noqa: E402  上架进度 / 批次


listing.init()


@app.after_request
def _ext_cors(resp):   # 浏览器扩展跨域访问 /api/v1/…（v2.30 从客服模块搬到内核：运营写回也用）
    o = request.headers.get("Origin", "")
    if request.path.startswith("/api/v1/") and o.startswith(("chrome-extension://", "moz-extension://")):
        resp.headers["Access-Control-Allow-Origin"] = o
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-API-Key"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


def _strip_as(d):
    if not auth.is_owner():
        for k in extras.AS_LOSS + ("loss",):
            d.pop(k, None)
    return d


@app.get("/api/groups")
def groups_get():
    return jsonify({"groups": extras.groups()})


# ---------------- 对外 API（/api/v1，用 API 密钥）与店铺对接 ----------------
from core import connectors, integrations  # noqa: E402


integrations.init()


def _v1_err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


# 只读密钥查询订单时去掉的买家个人信息（泰国 PDPA：分析用不到，就不往外给）
V1_PII_FIELDS = ("buyer", "receiver", "phone", "address", "postcode", "buyer_note", "label_file", "buyer_key")


def _v1_read_only():
    from flask import g
    return (getattr(g, "user", None) or {}).get("scope") == "read"


from core import specs, stockcalc  # noqa: E402,F401


stockcalc.init()


from core import inventory  # noqa: E402


inventory.init()


# ---------------- 登录 / 账号 ----------------
def _page(name):
    with open(os.path.join(BASE_DIR, "static", name), encoding="utf-8") as f:
        html = f.read()
    r = app.response_class(html.replace("{{VERSION}}", VERSION), mimetype="text/html")
    r.headers["Cache-Control"] = "no-store"
    return r


def _port_busy(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _free_port(port):
    """端口被占用（通常是没关掉的旧版本）时，先礼貌地请它退出，不行再结束那个进程。"""
    if not _port_busy(port):
        return True
    import subprocess
    import urllib.request
    print(f"  检测到端口 {port} 已被占用（可能是旧版本还开着），正在关闭旧版本…")
    try:
        urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown", data=b"{}",
                                                      headers={"Content-Type": "application/json"}), timeout=3)
    except Exception:
        pass
    for _ in range(10):
        time.sleep(0.3)
        if not _port_busy(port):
            return True
    if os.name == "nt":
        try:
            out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=10).stdout
            pids = {line.split()[-1] for line in out.splitlines()
                    if len(line.split()) >= 5 and line.split()[1].endswith(f":{port}")
                    and ("LISTEN" in line.upper() or line.split()[2] in ("0.0.0.0:0", "[::]:0"))
                    and line.split()[-1].isdigit()}
            for pid in pids:
                if int(pid) != os.getpid():
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=10)
        except Exception as e:
            print(f"  自动关闭失败：{e}")
        for _ in range(10):
            time.sleep(0.3)
            if not _port_busy(port):
                return True
    return False


# 给各路由模块用 `from web.common import *`（包括下划线开头的小工具）
__all__ = [_n for _n in dir() if not _n.startswith("__")]
