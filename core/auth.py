"""登录与权限。

什么时候需要登录：
- NAS / Docker 运行时：必须登录（第一次打开先创建老板账号）。
- 自己电脑（Windows）单机运行：没有建过账号就不用登录（和以前一样，等同老板）；建了账号以后也要登录。

角色：
- owner      老板：全部
- listing    上架客服：产品、图片、文案、类目、导出；不能改设置，看不到成本/利润/密钥
- production 生产打包：只读产品、3D 模型、切片、打印建议；看不到价格成本，不能改产品
"""
import os
import re
import time
from datetime import timedelta

from flask import g, jsonify, redirect, request, session

from . import db

PUBLIC = ("/login", "/setup", "/api/auth/", "/static/", "/api/version", "/api/shutdown", "/favicon")
PUBLIC_EXACT = set()       # 只有这个地址本身不用登录（模块说明书 public_exact，例如手机版 /m 自己显示登录框）

# 只有老板能用
OWNER_ONLY = [
    ("POST", r"^/api/config$"),
    ("*", r"^/api/(profit|expenses|fin/)"),
    ("*", r"^/api/users"),
    ("*", r"^/api/audit"),
    ("GET", r"^/api/catalog$"),
    ("POST", r"^/api/slicer/(automatch|pick)$"),
    ("DELETE", r"^/api/templates/"),
    ("*", r"^/api/(integrations|apikeys|shops)"),
    ("*", r"^/api-docs"),
    ("POST", r"^/api/printers/\d+/(conn|test)$"),
    ("*", r"^/api/backups"),
    ("*", r"^/api/system/"),
    ("POST", r"^/api/modules/"),                 # v2.29 模块开关
    ("GET", r"^/api/modules/events"),
    ("POST", r"^/api/ops/changes/"),
    ("POST", r"^/api/calib/"),
]
# 生产角色能用的（其他全部拒绝）
PRODUCTION_ALLOW = [
    ("GET", r"^/$"),
    ("GET", r"^/api/modules$"),                          # v2.29 模块菜单
    ("GET", r"^/m/[a-z0-9_]+/[A-Za-z0-9_-]+\.(html|js|css)$"),
    ("GET", r"^/api/accel/(package|status)$"),
    ("GET", r"^/api/bg/list$"),
    ("POST", r"^/api/bg/(clear|[a-f0-9]+/retry)$"),
    ("GET", r"^/api/(config|colors|me|products|categories|scenes|slicer/info|slicer/presets|shopee/tree)$"),
    ("GET", r"^/api/products/[^/]+$"),
    ("GET", r"^/api/goods/(library|views)$"),                # v2.53 产品库（自动分组）；售价字段下面会去掉
    ("POST", r"^/api/client-(error|timing)$"),
    ("GET", r"^/api/calib$"),
    ("GET", r"^/files/"),
    ("GET", r"^/scenes/"),
    ("POST", r"^/api/products/[^/]+/(model|model/metrics|slice|print-advice|print-advice/apply|check|check-shopee)$"),
    ("POST", r"^/api/sliced/parse$"),
    ("POST", r"^/api/slicer/test$"),
    ("POST", r"^/api/pricing$"),
    ("GET", r"^/api/(orders|orders/\d+|production|materials|materials/log|skus)$"),
    ("POST", r"^/api/(jobs/\d+|jobs/bulk|production/schedule|materials)$"),      # v2.43：订单页批量处理生产任务
    ("POST", r"^/api/orders/\d+$"),
    ("GET", r"^/print/(orders|labels|handover|spools)$"),
    ("GET", r"^/api/spools$"),
    ("GET", r"^/api/bg/[a-f0-9]+$"),                      # 后台任务进度（切片等）
    ("GET", r"^/api/inv/"),                              # 库存管理（v2.17）：能做什么由 inv.* 权限决定
    ("POST", r"^/api/inv/(docs|stocktake)(/\d+/(save|confirm|void))?$"),
    ("POST", r"^/api/inv/(items|suppliers|po|suggest/po|presets)$"),
    ("POST", r"^/api/spools(/[A-Za-z0-9]+/(load|unload|weigh|empty|dry|edit))?$"),
    ("GET", r"^/api/handovers(/\d+)?$"),
    ("POST", r"^/api/handovers(/\d+/(scan|remove|close))?$"),
    ("POST", r"^/api/labels/(import|check)$"),
    ("GET", r"^/api/(printers|print-files)$"),
    ("GET", r"^/api/print-files/\d+/download$"),
    ("POST", r"^/api/printers/\d+/(command|loaded)$"),
    ("POST", r"^/api/print-files(/slice|/\d+)?$"),
    ("POST", r"^/api/jobs/\d+/(send|plate-done|start|use-stock|use-part)$"),
    ("GET", r"^/api/jobs/\d+/send-options$"),
    ("POST", r"^/api/runs/\d+/(done|fail|cancel)$"),
    ("GET", r"^/api/products/[^/]+/(recipe|mesh|filaments)$"),
    ("GET", r"^/api/products/[^/]+/models(/[^/]+/(download|thumb|stl|preview))?$"),
    ("GET", r"^/api/products/[^/]+/model/(stl|preview)$"),
    ("GET", r"^/api/print-files/\d+/toolpath$"),
    ("GET", r"^/api/files(/zip)?$"),
    ("GET", r"^/api/products/[^/]+/model/(download|history)(/[^/]+)?$"),
    ("POST", r"^/api/products/[^/]+/model(/restore)?$"),
    ("POST", r"^/api/files/models$"),
    ("POST", r"^/api/print-files/\d+/replace$"),
    ("POST", r"^/api/products/[^/]+/recipe(/slice)?$"),
    ("GET", r"^/api/print-files/(\d+|photo/[^/]+)$"),
    ("POST", r"^/api/print-files/\d+/(review|verify|ai-review)$"),
    ("GET", r"^/api/(stock|quality|maintenance|dashboard|groups|aftersales)$"),
    ("POST", r"^/api/(stock/make|maintenance|materials/flag|pack/done)$"),
    ("GET", r"^/api/pack/lookup$"),
    ("POST", r"^/api/shops/sync-all$"),                   # v2.44.1：工作台 / 订单页「同步订单」
    ("GET", r"^/print/jobs$"),
    ("GET", r"^/api/colors$"),                            # v2.41：颜色表（泰文颜色名，生产员工用泰文界面）
    ("GET", r"^/fonts/"),                                 # v2.41：泰文字体
    ("GET", r"^/api/todo(/count)?$"), ("POST", r"^/api/todo/state$"),   # v2.46：今日待办（只给这个角色能看的）；v2.49 🔔 数字
    ("GET", r"^/api/search$"),                            # v2.49：全局搜索（按角色给结果，没有客服会话）
]
SECRET_KEYS = ("ai_api_key", "imgbb_api_key", "image_api_key", "curator_api_key", "update_token")
COST_KEYS = ("filament_price_cny_per_kg", "cny_to_thb", "material_loss_rate", "electricity_thb_per_kwh",
             "printer_avg_kw", "monthly_rent", "monthly_labor", "monthly_depreciation", "monthly_maintenance",
             "printer_count", "hours_per_day_each", "failure_rate", "packaging_per_item", "platform_fee_rate",
             "shopee_fee_rate", "default_markup", "min_markup")
PRICE_HIDE = ("cost", "material_cost", "machine_cost", "failure", "profit", "markup", "actual_markup",
              "suggested_price", "floor_price", "platform_fee", "fee", "by_shop", "breakdown", "margin", "summary", "warning")


def login_required():
    return os.environ.get("LH_DOCKER") == "1" or db.user_count() > 0


def current_user():
    return getattr(g, "user", None)


def is_owner():
    u = current_user()
    return bool(u) and u["role"] == "owner"


def _match(rules, method, path):
    return any((m == "*" or m == method) and re.search(p, path) for m, p in rules)


# 需要特别权限的操作（老板在「系统 → 设置 → 账号与权限」里给员工单独开）
PERM_RULES = [
    ("DELETE", r"^/api/print-files/\d+$", "files.delete"),
    ("DELETE", r"^/api/products/[^/]+/model$", "models.delete"),
    ("DELETE", r"^/api/products/[^/]+/models/[^/]+$", "models.delete"),
    ("POST", r"^/api/products/[^/]+/models(/current|/reanalyze|/ai-check|/layout-preview|/[^/]+/spec)?$", "files.upload"),
    ("POST", r"^/api/products/[^/]+/models/current$", "models.change"),
    ("POST", r"^/api/products/[^/]+/model/restore$", "models.change"),
    ("POST", r"^/api/spools/[A-Za-z0-9]+/delete$", "materials.adjust"),
    ("POST", r"^/api/products/[^/]+/model(/restore)?$", "files.upload"),
    ("POST", r"^/api/files/models$", "files.upload"),
    ("POST", r"^/api/print-files$", "files.upload"),
    ("POST", r"^/api/print-files/\d+/replace$", "files.upload"),
    ("DELETE", r"^/api/products/[^/]+$", "products.delete"),
    ("POST", r"^/api/orders/\d+/edit$", "orders.edit"),
    ("DELETE", r"^/api/orders/", "orders.delete"),
]


def missing_perm(user, method, path):
    """返回缺少的权限名（中文）；有权限返回 None。"""
    if user.get("role") == "owner":
        return None
    perms = user.get("perms") or db.user_perms(user.get("role"))
    for m, pat, key in PERM_RULES:
        if (m == "*" or m == method) and re.search(pat, path) and not perms.get(key):
            return dict(db.PERMS).get(key, key)
    return None


def has_perm(user, key):
    return user.get("role") == "owner" or bool((user.get("perms") or db.user_perms(user.get("role"))).get(key))


def allowed(user, method, path):
    if user["role"] == "owner":
        return True
    if any((m == "*" or m == method) and re.search(pat, path) for m, pat, _k in PERM_RULES):
        return missing_perm(user, method, path) is None      # 有这个权限就可以（不管角色）
    if _match(OWNER_ONLY, method, path):
        return False
    if user["role"] == "production":
        return _match(PRODUCTION_ALLOW, method, path)
    return True   # listing


def strip_config(cfg, user):
    """给员工的设置：去掉密钥和成本参数。"""
    out = dict(cfg)
    if isinstance(out.get("ai_providers"), dict):    # v2.53：各家 AI 的密钥不下发（「AI 接口」页有自己的打码接口）
        out["ai_providers"] = {k: {kk: ("******" if kk in ("api_key", "image_key") and vv else vv) for kk, vv in (v or {}).items()}
                               for k, v in out["ai_providers"].items()}
    if out.get("printers"):     # 打印机访问码不下发
        prs = []
        for p in out["printers"]:
            p = dict(p)
            if p.get("conn"):
                c = dict(p["conn"])
                if c.get("access_code"):
                    c["access_code"] = "******"
                p["conn"] = c
            prs.append(p)
        out["printers"] = prs
    for k in SECRET_KEYS:             # v2.26：密钥对老板也不再发回浏览器（只显示 ******，不改就保持原值）
        if out.get(k):
            out[k] = "******"
    if user["role"] == "owner":
        return out
    for k in COST_KEYS:
        out.pop(k, None)
    return out


def strip_prices(obj, user):
    """员工看不到成本/利润/加价率（递归去掉这些字段）。生产角色连售价也不看。"""
    if user["role"] == "owner":
        return obj
    hide = set(PRICE_HIDE)
    if user["role"] == "production":
        hide |= {"final_price", "list_price", "special_price", "price", "sku_price", "price_sig"}
    if isinstance(obj, dict):
        return {k: strip_prices(v, user) for k, v in obj.items() if k not in hide}
    if isinstance(obj, list):
        return [strip_prices(v, user) for v in obj]
    return obj


ACTION_NAMES = [
    (r"^POST /api/orders/\d+/edit$", "修改订单"),
    (r"^POST /api/files/models$", "批量上传模型"),
    (r"^POST /api/print-files/\d+/replace$", "替换切片文件"),
    (r"^POST /api/products/[^/]+/model/restore$", "恢复旧模型"),
    (r"^DELETE /api/products/[^/]+/model$", "删除模型文件"),
    (r"^POST /api/cs/convs/\d+/sent$", "客服：记录回复"),
    (r"^POST /api/cs/convs/\d+/action$", "客服：操作（写订单备注/报价等）"),
    (r"^POST /api/cs/settings$", "客服：修改店铺政策"),
    (r"^POST /api/cs/kb$", "客服：保存常见问答"),
    (r"^DELETE /api/cs/", "客服：删除"),
    (r"^POST /api/orders/import/commit$", "导入订单"),
    (r"^POST /api/orders/import", ""),
    (r"^POST /api/orders/manual$", "新建手工订单"),
    (r"^POST /api/orders/\d+$", "修改订单备注/状态"),
    (r"^DELETE /api/orders/", "删除订单"),
    (r"^POST /api/jobs/\d+/send$", "发送打印"),
    (r"^POST /api/jobs/\d+/start$", "开始打印（一盘）"),
    (r"^POST /api/runs/\d+/done$", "一盘打完"),
    (r"^POST /api/runs/\d+/fail$", "打印失败"),
    (r"^POST /api/runs/\d+/cancel$", "撤销打印"),
    (r"^POST /api/jobs/\d+/use-stock$", "用成品库存出货"),
    (r"^POST /api/jobs/\d+/use-part$", "使用零件"),
    (r"^POST /api/stock/make$", "生成备货任务"),
    (r"^POST /api/stock$", "成品库存盘点/目标"),
    (r"/recipe/slice$", "按打印方案切片"),
    (r"/recipe$", "保存打印方案"),
    (r"/ai-review$", "AI 检查切片"),
    (r"/review$", "人工复核切片"),
    (r"/verify$", "试打验证"),
    (r"^POST /api/aftersales", "售后"),
    (r"^POST /api/backups$", "手动备份"),
    (r"/api/groups", "产品分组"),
    (r"^POST /api/maintenance$", "打印机保养"),
    (r"^POST /api/materials/flag$", "耗材开封/烘干"),
    (r"^POST /api/pack/done$", "打包核对"),
    (r"^POST /api/jobs/", "更新生产任务"),
    (r"^POST /api/orders/batch$", "批量处理订单"),
    (r"^POST /api/labels/import$", "上传平台面单"),
    (r"^POST /api/labels/check$", ""),
    (r"^POST /api/printers/\d+/command$", "打印机暂停/继续/取消"),
    (r"^POST /api/printers/", "打印机设置"),
    (r"/api/print-files", "打印文件库"),
    (r"^POST /api/materials$", "耗材入库/盘点"),
    (r"/api/expenses", "记录支出"),
    (r"/api/apikeys", "API 密钥"),
    (r"/api/shops", "店铺对接设置"),
    (r"^POST /api/products/[^/]+$", "保存产品"),
    (r"^DELETE /api/products/[^/]+$", "删除产品"),
    (r"/duplicate$", "复制产品"),
    (r"/regen-skus$", "重新生成 SKU"),
    (r"/images/rendered$", "生成商品图/场景图"),
    (r"/images/(host|url)$", "上传图床"),
    (r"/images", "图片操作"),
    (r"/(ai|keywords)$", "AI 文案/关键词"),
    (r"/(ai-category|fill-attrs)$", "AI 类目/属性"),
    (r"/ai-shopee-category$", "AI Shopee 类目"),
    (r"/model$", "上传 3D 模型"),
    (r"/(slice)$|/api/sliced/parse$", "切片"),
    (r"/print-advice", "打印建议"),
    (r"/scene-ai$", "AI 场景图"),
    (r"^POST /api/export/shopee$", "导出 Shopee 表格"),
    (r"^POST /api/export$", "导出 Lazada 表格"),
    (r"^POST /api/config$", "修改设置"),
    (r"/api/slicer/", "切片设置"),
    (r"^POST /api/templates", "上传类目模板"),
    (r"^DELETE /api/templates", "删除类目模板"),
    (r"/api/scenes", "背景库"),
    (r"^POST /api/users", "修改账号"),
    (r"/api/me/", "个人设置"),
]


def action_name(method, path):
    key = f"{method} {path}"
    for pat, name in ACTION_NAMES:
        if re.search(pat, key):
            return name
    return key


def _api_guard(path):
    """对外接口 /api/v1/...：用 API 密钥，不用登录。平台推送（webhook）由连接器自己验签。"""
    if path.startswith("/api/v1/webhook/"):
        g.user = {"id": -1, "username": "webhook", "display_name": "平台推送", "role": "api", "lang": "zh"}
        return None
    from . import integrations
    raw = request.headers.get("X-API-Key", "")
    h = request.headers.get("Authorization", "")
    if not raw and h.lower().startswith("bearer "):
        raw = h[7:].strip()
    k = integrations.check_key(raw.strip())
    if not k:
        return jsonify({"ok": False, "error": "API 密钥不对或已停用（请求头 Authorization: Bearer <密钥>）"}), 401
    scope = k.get("scope") or "full"
    g.user = {"id": -1, "username": f"api:{k['name']}", "display_name": k["name"], "role": "api", "lang": "zh",
              "scope": scope}
    if path.startswith(("/api/v1/cs/", "/api/v1/labels/", "/api/v1/ops/ext/", "/api/v1/curate/ext/")):
        integrations.note_ext(k["name"], request.headers.get("X-Ext-Version", "").strip()[:12])
    if path.startswith("/api/v1/accel/") and scope not in ("worker", "full"):
        return jsonify({"ok": False, "error": "电脑加速要用「电脑加速」权限的密钥（scope = worker）"}), 403
    if scope == "worker":
        # 电脑加速密钥（v2.20）：只能领活、传结果
        if not (path.startswith("/api/v1/accel/") or path == "/api/v1/ping"):
            return jsonify({"ok": False, "error": "这个密钥只能给电脑加速用（/api/v1/accel/）"}), 403
    elif scope == "read":
        # 只读密钥：只能 GET，不能碰客服接口（里面有买家聊天内容），也不能调写回接口
        # v2.50：选品扩展接口（/api/v1/curate/）只给员工的扩展密钥（完整权限），只读密钥连 GET 也不行
        if request.method not in ("GET", "HEAD") or path.startswith(("/api/v1/cs/", "/api/v1/ops/", "/api/v1/curate/")):
            return jsonify({"ok": False, "error": "这个密钥是只读的，只能查询，不能修改或推送"}), 403
    elif scope == "ops":
        # 运营写回密钥（规范 v1.1 第 6 条）：只能调 /api/v1/ops/...（和 ping）
        if not (path.startswith("/api/v1/ops/") or path == "/api/v1/ping"):
            return jsonify({"ok": False, "error": "这个密钥只能调用 /api/v1/ops/ 写回接口"}), 403
    elif scope == "catalog":
        # v2.54：旧「3D选品工具」对接已移除，这种密钥不再有任何权限（行还留着，设置里显示「已停用」）
        return jsonify({"ok": False, "error": "「建产品」密钥已停用：旧的 3D选品工具对接在 v2.54 移除了"}), 403
    elif scope == "wholesale":
        # 批发站密钥（v2.36）：只能读 SKU、推送 / 查询 / 改状态批发站自己的订单（platform 强制为 wholesale）
        ok = ((request.method in ("GET", "HEAD") and (path in ("/api/v1/ping", "/api/v1/skus", "/api/v1/orders")
                                                       or path.startswith("/api/v1/images/")))
              or (request.method == "POST" and path in ("/api/v1/orders", "/api/v1/orders/status", "/api/v1/wholesale/hook")))
        if not ok:
            return jsonify({"ok": False, "error": "这个密钥只能给批发站用（读 SKU、推送和查询批发订单）"}), 403
    elif scope == "chat":
        # AI 接待密钥（v2.38，系统一 ai-sales-desk）：只能读 SKU 和图片、推送 / 查询 / 改状态聊天订单（platform 强制为 chat）
        ok = ((request.method in ("GET", "HEAD") and (path in ("/api/v1/ping", "/api/v1/skus", "/api/v1/orders")
                                                       or path.startswith("/api/v1/images/")))
              or (request.method == "POST" and path in ("/api/v1/orders", "/api/v1/orders/status")))
        if not ok:
            return jsonify({"ok": False, "error": "这个密钥只能给 AI 接待系统用（读 SKU、推送和查询聊天订单）"}), 403
    elif scope == "finance":
        # 财务密钥（规范第 11 条）：只能读 /api/v1/finance/…（和 ping）
        if not (request.method in ("GET", "HEAD") and (path.startswith("/api/v1/finance/") or path == "/api/v1/ping")):
            return jsonify({"ok": False, "error": "这个密钥只能读取财务接口 /api/v1/finance/"}), 403
    elif path.startswith("/api/v1/ops/") and not path.startswith("/api/v1/ops/ext/"):
        # v2.48：/api/v1/ops/ext/… 是浏览器扩展的采集接口（竞品、搜索结果、店铺、卖家后台数据），员工的扩展密钥（完整权限）就能用
        return jsonify({"ok": False, "error": "写回接口要用「运营写回」权限的密钥（scope = ops）"}), 403
    return None


def install(app):
    app.secret_key = db.secret_key()
    from .config import load_config
    try:
        days = max(1, min(365, int(load_config().get("login_days") or 30)))
    except (TypeError, ValueError):
        days = 30
    app.permanent_session_lifetime = timedelta(days=days)
    # NAS 上同一个 IP 跑着好几个系统（选品工具、分析系统……），浏览器的 cookie 只按 IP 区分、不按端口区分，
    # 大家都用默认名字「session」会互相顶掉，表现就是「老是要重新登录」。所以用自己的名字。
    app.config.update(SESSION_COOKIE_NAME="3dops_session", SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_REFRESH_EACH_REQUEST=True)

    @app.before_request
    def _guard():
        path = request.path
        if path.startswith("/api/v1/"):
            if request.method == "OPTIONS":      # 浏览器扩展跨域预检
                return "", 204
            return _api_guard(path)
        if any(path.startswith(p) for p in PUBLIC) or path in PUBLIC_EXACT:
            return None
        if not login_required():
            g.user = {"id": 0, "username": "local", "display_name": "本机", "role": "owner", "lang": "zh"}
            return None
        uid = session.get("uid")
        u = db.get_user(uid=uid) if uid else None
        if not u or not u["active"]:
            session.clear()
            if path.startswith("/api/"):
                return jsonify({"error": "请先登录", "login": True}), 401
            return redirect("/setup" if db.user_count() == 0 else "/login")
        g.user = u
        if not allowed(u, request.method, path):
            mp = missing_perm(u, request.method, path)
            if path.startswith("/api/"):
                return jsonify({"error": f"你的账号没有「{mp}」的权限，请老板在 系统 → 设置 → 账号与权限 里开通" if mp
                                else "你的账号没有这个权限"}), 403
            return "没有权限", 403
        return None

    @app.teardown_request
    def _release(_exc=None):
        db.release()

    @app.after_request
    def _audit(resp):
        u = getattr(g, "user", None)
        if u and u.get("role") != "api" and request.method in ("POST", "PUT", "DELETE") and resp.status_code < 400 \
                and not request.path.startswith(("/api/auth/", "/api/pricing", "/api/products/new")) \
                and not re.search(r"/(check|check-shopee|model/metrics)$|^/api/labels/check$|^/api/orders/manual$|^/api/me/lang$|^/api/orders/import/|^/api/cs/(convs/\d+/(draft|messages|screenshot)|convs/\d+$|convs$|quote|translate)", request.path):
            m = re.search(r"/api/products/([^/]+)", request.path)
            target = m.group(1) if m else ""
            db.audit(u["username"], action_name(request.method, request.path), target)
        return resp
