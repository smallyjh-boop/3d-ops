"""第二期的接口（v2.48）：
  /api/oa/comp…、/api/oa/radar…、/api/oa/shops…、/api/oa/plans…、/api/oa/campaigns…、/api/oa/traffic  —— 软件界面用（登录）
  /api/v1/ops/ext/…  —— 浏览器扩展采集用（员工的扩展密钥，和 AI 客服、面单转交同一把；core/auth.py 放行 full / ops 权限的密钥）
都挂在运营分析模块的 Blueprint 上（api.py 里 attach(bp)）。"""
import re

from flask import g, jsonify, request

from core.config import load_config

from . import campaigns, comp, mkt_db, plans, radar, shops, traffic
from .mkt_util import AiError, ai_on, sku_options


def _body():
    return request.get_json(force=True, silent=True) or {}


def _ids(v):
    return [int(x) for x in str(v or "").split(",") if x.strip().isdigit()]


def _e(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


def _go(fn):
    try:
        return jsonify({"ok": True, **_strip(fn() or {})})      # 员工：去掉成本利润
    except (ValueError, TypeError, AiError) as e:
        return _e(e)


def _owner():
    from core import auth
    return bool(auth.is_owner())


def _who():
    u = getattr(g, "user", None) or {}
    return u.get("display_name") or u.get("username") or ""


MONEY = {"actual_profit", "unit_cost", "my_unit_cost", "my_profit_unit", "profit_unit", "profit_7d", "profit_30d", "profit_daily",
         "margin", "floor_price", "actual_revenue", "target_revenue"}


MONEY_RE = re.compile(r"cost|profit|margin|fee_unit|fee_7d|fee_30d|floor_price|revenue", re.I)


def _strip(o):
    """员工（上架客服）看计划、竞品、雷达、竞店时去掉成本、利润（和 ERP 别的页面一样，员工看不到成本利润）。"""
    from core import auth
    if auth.is_owner():
        return o
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in MONEY and not MONEY_RE.search(str(k))}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def attach(bp):
    mkt_db.init()
    from web.common import maybe_async

    # ---------------- 竞品 ----------------
    @bp.get("/api/oa/comp")
    def oa_comp_list():
        def go():
            cfg = load_config()
            from .mkt_util import sku_rows
            skus = sku_rows(cfg)
            rows = comp.listing(cfg, include_archived=request.args.get("archived") == "1", skus=skus)
            return {"rows": rows, "compare": comp.compare(cfg, rows, skus), "radar": comp.radar(cfg, rows), "events": comp.events(14, 50),
                    "skus": [{"sku": s["sku"], "name": s["name"], "color": s["variant"]} for s in skus.values() if not s["draft"]], "ai": ai_on(cfg)}
        return _go(go)

    @bp.get("/api/oa/comp/compare")
    def oa_comp_compare():
        return _go(lambda: {"rows": comp.compare_rows(load_config(), _ids(request.args.get("ids")))})

    @bp.get("/api/oa/comp/<int:cid>")
    def oa_comp_get(cid):
        c = comp.get(cid)
        if not c:
            return _e("没有这个竞品", 404)
        return _go(lambda: {"comp": {**c, "skus": comp.links(cid)}, "snaps": comp.snaps(cid), "est": comp.estimate(load_config(), c)})

    @bp.post("/api/oa/comp")
    def oa_comp_create():
        def go():
            cid, new = comp.create(_body())
            return {"id": cid, "new": new}
        return _go(go)

    @bp.post("/api/oa/comp/<int:cid>")
    def oa_comp_update(cid):
        if not comp.get(cid):
            return _e("没有这个竞品", 404)
        return _go(lambda: comp.update(cid, _body() if _owner() else {k: v for k, v in _body().items() if not re.search(r"cost|fee|gram|hour|material", k)}))

    @bp.post("/api/oa/comp/<int:cid>/snap")
    def oa_comp_snap(cid):
        def go():
            b = _body()
            comp.add_snap(cid, b, source=b.get("source") or "manual")
            return {"est": comp.estimate(load_config(), comp.get(cid))}
        return _go(go)

    @bp.post("/api/oa/comp/snap/<int:sid>/delete")
    def oa_comp_snap_delete(sid):
        return _go(lambda: comp.delete_snap(sid))

    @bp.post("/api/oa/comp/extract")
    def oa_comp_extract():
        b = _body()

        def go():
            data, how = comp.extract(load_config(), b.get("text") or "", b.get("url") or "")
            return {"data": data, "how": how}
        return maybe_async("AI 识别竞品页面", lambda: _go(go), "ai")

    @bp.post("/api/oa/comp/<int:cid>/ai-cost")
    def oa_comp_ai_cost(cid):
        return maybe_async("AI 估竞品成本", lambda: _go(lambda: comp.ai_cost(load_config(), cid)), "ai")

    # ---------------- 爆款雷达 ----------------
    @bp.get("/api/oa/radar")
    def oa_radar_board():
        return _go(lambda: {"ai": ai_on(), **radar.board(load_config())})

    @bp.post("/api/oa/radar/keywords")
    def oa_radar_add():
        b = _body()
        return _go(lambda: {"added": radar.add_keywords(b.get("platform") or "lazada", b.get("keywords") or "", b.get("note") or "")})

    @bp.post("/api/oa/radar/import")
    def oa_radar_import():
        b = _body()
        return _go(lambda: {"added": radar.import_from_products(b.get("platform") or "lazada")})

    @bp.get("/api/oa/radar/keywords/<int:kid>")
    def oa_radar_get(kid):
        k = radar.keyword(kid)
        if not k:
            return _e("没有这个关键词", 404)

        def go():
            hist = [dict(r) for r in mkt_db.conn().execute("SELECT * FROM ops_radar_searches WHERE keyword_id=? ORDER BY ts DESC LIMIT 30", (kid,))]
            return {"keyword": k, "opp": radar.opportunity(load_config(), k), "items": radar.top_items(kid, 30), "history": hist}
        return _go(go)

    @bp.post("/api/oa/radar/keywords/<int:kid>")
    def oa_radar_update(kid):
        if not radar.keyword(kid):
            return _e("没有这个关键词", 404)
        b = _body()
        return _go(lambda: radar.delete_keyword(kid) if b.get("delete") else radar.update_keyword(kid, b))

    @bp.post("/api/oa/radar/keywords/<int:kid>/ai")
    def oa_radar_ai(kid):
        return maybe_async("AI 评估关键词", lambda: _go(lambda: {"ai": radar.assess(load_config(), kid)}), "ai")

    @bp.post("/api/oa/radar/report")
    def oa_radar_report():
        return _go(lambda: {"text": radar.daily_report(load_config(), force=True)})

    # ---------------- 竞店 ----------------
    @bp.get("/api/oa/shops")
    def oa_shops_board():
        return _go(lambda: {"ai": ai_on(), **shops.board(load_config())})

    @bp.post("/api/oa/shops")
    def oa_shops_add():
        b = _body()
        return _go(lambda: {"id": shops.ensure(b.get("url") or "", watch=True)["id"]})

    @bp.get("/api/oa/shops/<int:sid>")
    def oa_shops_get(sid):
        d = shops.detail(sid)
        return _go(lambda: d) if d else _e("没有这家店", 404)

    @bp.post("/api/oa/shops/<int:sid>")
    def oa_shops_update(sid):
        if not shops.get(sid):
            return _e("没有这家店", 404)
        b = _body()
        return _go(lambda: shops.delete(sid) if b.get("delete") else shops.update(sid, b))

    # ---------------- 计划 ----------------
    @bp.get("/api/oa/plans")
    def oa_plans_list():
        def go():
            cfg = load_config()
            return {"rows": _strip(plans.listing(cfg)), "skus": sku_options(cfg), "ai": ai_on(cfg), "owner": _owner(),
                    "kinds": {k: {"zh": v[0], "th": v[1]} for k, v in plans.KINDS.items()}}
        return _go(go)

    @bp.get("/api/oa/plans/suggest")
    def oa_plans_suggest():
        a = request.args
        return _go(lambda: plans.suggest(load_config(), (a.get("sku") or "").upper(), a.get("platform") or "", a.get("kind") or "hero"))

    @bp.post("/api/oa/plans")
    def oa_plans_create():
        b = _body()
        return _go(lambda: {"id": plans.create(load_config(), b.get("sku"), b.get("platform") or "", b.get("kind") or "hero",
                                               b.get("target_daily"), b.get("days") or 30, b.get("start_day") or None)})

    @bp.get("/api/oa/plans/<int:pid>")
    def oa_plans_get(pid):
        d = plans.detail(load_config(), pid)
        return _go(lambda: {"plan": _strip(d)}) if d else _e("没有这个计划", 404)

    @bp.post("/api/oa/plans/<int:pid>")
    def oa_plans_update(pid):
        if not plans.get(pid):
            return _e("没有这个计划", 404)
        b = _body()
        return _go(lambda: plans.delete(pid) if b.get("delete") else plans.update(pid, b))

    @bp.post("/api/oa/plans/<int:pid>/task")
    def oa_plans_task(pid):
        b = _body()

        def go():
            if b.get("text"):
                plans.add_task(pid, b.get("offset") or 0, b["text"])
            else:
                plans.set_task(pid, int(b.get("id") or 0), bool(b.get("done")), _who())
        return _go(go)

    @bp.post("/api/oa/plans/<int:pid>/ai")
    def oa_plans_ai(pid):
        return maybe_async("AI 更新计划", lambda: _go(lambda: {"note": plans.ai_refresh(load_config(), pid)}), "ai")

    # ---------------- 营销日历 ----------------
    @bp.get("/api/oa/campaigns")
    def oa_campaigns():
        return _go(lambda: campaigns.upcoming(load_config(), days=int(request.args.get("days") or 0) or None))

    @bp.post("/api/oa/campaigns")
    def oa_campaigns_add():
        b = _body()
        return _go(lambda: campaigns.add(b.get("name") or "", b.get("start") or "", b.get("end") or "", b.get("platforms") or campaigns.ALL,
                                         b.get("multiplier") or 3, b.get("note") or ""))

    @bp.post("/api/oa/campaigns/remove")
    def oa_campaigns_remove():
        b = _body()
        return _go(lambda: campaigns.restore_all() if b.get("restore") else campaigns.remove(b.get("key") or ""))

    # ---------------- 店铺后台数据 ----------------
    @bp.get("/api/oa/traffic")
    def oa_traffic():
        return _go(lambda: {"rows": traffic.latest(), "pages": traffic.pages()})

    # ---------------- 浏览器扩展（员工的扩展密钥） ----------------
    @bp.get("/api/v1/ops/ext/ping")
    def ext_ping():
        from core import integrations
        from web.common import VERSION
        cfg = load_config()
        return jsonify({"ok": True, "version": VERSION, "ai": ai_on(cfg), "user": _who(), "skus": sku_options(cfg),
                        "ext_latest": integrations.EXT_LATEST})

    @bp.post("/api/v1/ops/ext/competitor")
    def ext_competitor():
        return _go(lambda: comp.capture_competitor(load_config(), _body()))

    @bp.post("/api/v1/ops/ext/competitor/<int:cid>")
    def ext_competitor_update(cid):
        if not comp.get(cid):
            return _e("没有这个竞品", 404)
        b = _body()

        def go():
            comp.update(cid, {k: b[k] for k in ("skus", "radar_status", "note") if k in b})
            comp.set_image(cid, b.get("image"))
            return comp.result(load_config(), cid)
        return _go(go)

    @bp.post("/api/v1/ops/ext/card")
    def ext_card():
        return _go(lambda: comp.capture_card(load_config(), _body()))

    @bp.post("/api/v1/ops/ext/known")
    def ext_known():
        return _go(lambda: {"known": comp.known(_body().get("urls") or [])})

    @bp.get("/api/v1/ops/ext/compare")
    def ext_compare():
        return _go(lambda: {"rows": comp.compare_rows(load_config(), _ids(request.args.get("ids")))})

    @bp.get("/api/v1/ops/ext/patrol")
    def ext_patrol():
        return _go(lambda: radar.patrol_plan(load_config()))

    @bp.post("/api/v1/ops/ext/patrol/log")
    def ext_patrol_log():
        b = _body()

        def go():
            radar.log_patrol(b.get("kind") or "", b.get("url") or "", bool(b.get("ok")), b.get("note") or "", _who())
            return {"done": radar.patrol_done_today()}
        return _go(go)

    @bp.post("/api/v1/ops/ext/search")
    def ext_search():
        return _go(lambda: radar.record_search(load_config(), _body(), _who()))

    @bp.post("/api/v1/ops/ext/shop")
    def ext_shop():
        return _go(lambda: shops.record(load_config(), _body()))

    @bp.post("/api/v1/ops/ext/shop/watch")
    def ext_shop_watch():
        b = _body()

        def go():
            s = shops.ensure(b.get("url") or "", name=b.get("name") or "", watch=True)
            return {"id": s["id"], "name": s["name"]}
        return _go(go)

    @bp.post("/api/v1/ops/ext/shop/known")
    def ext_shop_known():
        return _go(lambda: {"known": shops.ext_known(_body().get("urls") or [])})

    @bp.post("/api/v1/ops/ext/backend")
    def ext_backend():
        return _go(lambda: traffic.capture_backend(load_config(), _body()))
