"""上架工作台的自动分类（v2.53）：选平台 + 店铺，所有分类按这个店铺现算，不存；修好就自动离开。

  pg:*  进度（互斥）  none 未上架（什么都还没准备）· todo 资料不全 · ready 可推送 · pushing 推送中（表格待上传 / 上传失败要重推）·
                      review 审核中 · rejected 被拒 · live 在售 · down 已下架。平台状态来自在线商品同步（按店铺）；这个店铺没有记录时，
                      才退回看上架模块记的状态（没选店铺 = 这个平台全部店铺）。
  td:*  待处理（可叠加）  rejected 被拒（带原因）· noattr 类目属性没填 · badimg 图片不合规（没有白底图 / 没有图）· longtitle 标题太长 ·
                      belowcost 售价低于成本 · mismatch 平台价格或库存和系统对不上 · nostock 在售但没库存
  sl:*  表现（这个店铺近 30 天）  hot 热销 · slow 滞销 · new 新上架 · lowmargin 利润低（阈值和产品库同一套：core/prodgroups.settings）
  opp   铺货机会  别的店铺卖得出去、这个店铺还没上
  mk:*  手动标记  list 要上架 · price 要改价 · img 要改图（带备注；做完自动取消）
"""
import json
import time

from core import db, prodgroups

TITLE_MAX = 120          # 标题建议长度（平台上超过会被截断 / 影响展示）
PROGRESS = ("none", "todo", "ready", "pushing", "review", "rejected", "live", "down")
TODO = ("rejected", "noattr", "badimg", "longtitle", "belowcost", "mismatch", "nostock")


def shops(platform):
    return [dict(r) for r in db.conn().execute("SELECT id, name FROM shops WHERE platform=? ORDER BY id", (platform,))]


def _online(platform, shop_id):
    from modules.listing import online
    online.init()
    q, a = "SELECT * FROM online_items WHERE platform=? AND product_id IS NOT NULL", [platform]
    if shop_id:
        q += " AND shop_id=?"
        a.append(shop_id)
    out = {}
    for r in db.conn().execute(q, a):
        out.setdefault(r["product_id"], []).append(dict(r))
    return out


def _sold(platform, shop_id, shop_name, since):
    """近 30 天卖出：{产品: 件数} 这个店铺的 + {产品: {(平台, 店铺名): 件数}} 全部店铺的（铺货机会用）。"""
    here, anyshop = {}, {}
    for r in db.conn().execute(
            """SELECT i.product_id pid, o.platform pf, COALESCE(o.shop,'') sh, SUM(i.qty) q FROM order_items i JOIN orders o ON o.id=i.order_id
               WHERE o.order_time>=? AND o.status NOT IN ('cancelled','unpaid','quote') AND i.product_id<>'' GROUP BY i.product_id, o.platform, o.shop""", (since,)):
        anyshop.setdefault(r["pid"], {})[(r["pf"], r["sh"])] = r["q"]
        if r["pf"] == platform and (not shop_id or r["sh"] == shop_name):
            here[r["pid"]] = here.get(r["pid"], 0) + r["q"]
    return here, anyshop


def _belowcost_ctx(platform, shop_name):
    """v2.53：「售价低于成本」按这个店铺的费率引擎算（店铺有真实费率才切过来；没有就沿用产品库的算法）。"""
    try:
        from core import feerates
        from core.config import load_config
        L = feerates._load()
        if not any(k[0] == platform and (not shop_name or k[1] == shop_name) for k in L["snaps"]):
            return None
        return {"cfg": load_config(), "platform": platform, "shop": shop_name, "memo": {}}
    except Exception:  # noqa: BLE001
        return None


def _below(ctx, pid, recs):
    from core import feerates, store
    try:
        if pid not in ctx["memo"]:
            ctx["memo"][pid] = store.load(pid)
        live = {}
        for r in recs:
            if r["status"] != "live":
                continue
            try:
                for x in json.loads(r["skus"] or "[]"):
                    pr = x.get("special_price") or x.get("price")
                    if x.get("seller_sku") and pr:
                        live[str(x["seller_sku"]).upper()] = float(pr)
            except (ValueError, TypeError):
                continue
        return bool(feerates.below_cost(ctx["cfg"], ctx["memo"][pid], ctx["platform"], ctx["shop"], live))
    except Exception:  # noqa: BLE001
        return False


def compute(platform="lazada", shop_id=0, rows=None):
    """返回 {gk: {产品: [键]}, summary: {n, total, shops}, ...}。rows：产品库的行（goods 的 cached_rows）。"""
    from modules.goods import api as gapi
    S = prodgroups.settings()
    now = time.time()
    rows = rows if rows is not None else gapi.cached_rows()
    shop_list = shops(platform)
    shop_name = next((s["name"] for s in shop_list if s["id"] == shop_id), "")
    onl = _online(platform, shop_id or None)
    all_recs = _online(platform, None)
    has_online_data = bool(all_recs)
    sold_here, sold_any = _sold(platform, shop_id, shop_name, now - 30 * 86400)
    lk = "sp" if platform == "shopee" else "lz"
    bc = _belowcost_ctx(platform, shop_name)
    gk, n, mk_all = {}, {}, {}
    ranked = sorted(((pid, q) for pid, q in sold_here.items() if q > 0), key=lambda x: -x[1])
    top = {pid for pid, _q in ranked[:int(S["hot_top"])]}
    for it in rows:
        pid = it["id"]
        k = set()
        recs = onl.get(pid, [])
        st = {x["status"] for x in recs}
        lst = (it.get(lk) or {}).get("status") or "none"
        errs = it.get("sp_err_txt" if platform == "shopee" else "err_txt") or []
        if recs:
            live, review, rej, inact = "live" in st, "uploaded" in st, "rejected" in st, "inactive" in st
        elif not has_online_data or not shop_id:
            live, review, rej, inact = lst in ("live", "update"), lst == "uploaded", lst in ("rejected",), lst == "inactive"
        else:
            live = review = rej = inact = False
        pend = lst in ("pending", "failed") and not (live or review or rej or inact) and not all_recs.get(pid)       # 表格待上传 / 上传失败：平台上哪个店铺都还没有
        if live:
            pg = "live"
        elif review:
            pg = "review"
        elif rej:
            pg = "rejected"
        elif inact:
            pg = "down"
        elif pend:
            pg = "pushing"
        elif errs:
            started = (it.get("title_len") or 0) > 0 or it.get("category_id")
            pg = "todo" if started else "none"
        else:
            pg = "ready"
        k.add("pg:" + pg)
        todo = set()
        if rej:
            todo.add("rejected")
        if any("类目属性" in e or "必填" in e for e in errs):
            todo.add("noattr")
        if not it.get("n_img") or not it.get("white_bg"):
            todo.add("badimg")
        if (it.get("title_len") or 0) > TITLE_MAX:
            todo.add("longtitle")
        if bc is None:
            if "td:belowcost" in (it.get("gk") or []):
                todo.add("belowcost")
        elif _below(bc, pid, recs):
            todo.add("belowcost")
        sp, sk = it.get("sku_price") or {}, it.get("sku_stock") or {}
        for r in recs:
            if r["status"] not in ("live", "uploaded"):
                continue
            try:
                skus = json.loads(r["skus"] or "[]")
            except ValueError:
                skus = []
            for x in skus:
                sku = str(x.get("seller_sku") or "").upper()
                pr = x.get("special_price") or x.get("price")
                try:
                    if sku in sp and pr and abs(float(pr) - float(sp[sku])) > 1.0:
                        todo.add("mismatch")
                    if sku in sk and x.get("qty") is not None and int(x["qty"]) != int(sk[sku]):
                        todo.add("mismatch")
                    if r["status"] == "live" and (int(x.get("qty") or 0) == 0 or sk.get(sku) == 0):
                        todo.add("nostock")
                except (TypeError, ValueError):
                    pass
        k.update("td:" + x for x in todo)
        # ---- 表现（这个店铺）----
        q = sold_here.get(pid, 0)
        created = min((r["created"] for r in recs if r["status"] == "live" and r["created"]), default=None)
        if live and created:
            age = (now - created) / 86400
            if age < S["new_days"]:
                k.add("sl:new")
            if age > S["slow_days"] and not q:
                k.add("sl:slow")
        if q and (q >= S["hot_min"] or pid in top):
            k.add("sl:hot")
        if live and "sl:lowmargin" in (it.get("gk") or []):
            k.add("sl:lowmargin")
        # ---- 铺货机会 ----
        if not (live or review or pend):
            other = {kk: v for kk, v in sold_any.get(pid, {}).items() if not (kk[0] == platform and (not shop_id or kk[1] == shop_name))}
            if shop_id and other:
                k.add("opp:1")
        # ---- 手动标记（做完自动取消）----
        wm = it.get("wmarks") or {}
        marks = {}
        for m, v in wm.items():
            done = (m == "list" and (live or review)) or (m == "price" and v.get("sig") is not None and v["sig"] != it.get("price_sig")) \
                or (m == "img" and v.get("sig") is not None and v["sig"] != it.get("img_sig"))
            if not done:
                marks[m] = {"note": v.get("note", ""), "at": v.get("at")}
                k.add("mk:" + m)
        gk[pid] = sorted(k)
        if marks:
            mk_all[pid] = marks
        for x in k:
            n[x] = n.get(x, 0) + 1
    n["all"] = len(rows)
    return {"gk": gk, "marks": mk_all, "n": n, "total": len(rows), "shops": shop_list, "platform": platform, "shop_id": shop_id}
