"""商品 360：一个产品（或一个 SKU）的全部情况，给右边抽屉用。只读，不缓存（一个产品，几十毫秒）。

对外：view(目标, user) → dict；目标 = SKU（3DP0015-WH）或产品编号（3DP0015）；找不到抛 NotFound。

权限（按角色，不按页面）：
  owner       全部
  listing     没有成本、最低价、平台费、利润（售价、竞品价、销量照样看）
  production  连售价 / 订单金额也没有；没有运营数据（生命周期、流量、竞品、评价、计划、改动）
各块的数据来自对应模块（modules.public / 模块自己的读函数），模块关着那一块就不出现（key 不在返回里）。
"""
import datetime as dt
import json
import statistics
import time

from core import db, listing as core_listing, modules, pricing, production, store
from core.config import load_config

DAYS = 30
PLATFORMS = ("lazada", "shopee")
PLAT_NAME = {"lazada": "Lazada", "shopee": "Shopee", "tiktok": "TikTok"}
EXCLUDE = ("cancelled", "returned", "unpaid", "quote", "delivery_failed")      # 和 core.finance.EXCLUDE 一样：不算销量
JOB_OPEN = ("todo", "printing", "post", "failed")


class NotFound(ValueError):
    pass


# ---------------- 找产品 ----------------
def resolve(target):
    """SKU 或产品编号 → (产品, 选中的规格序号或 None)。"""
    t = str(target or "").strip()
    if not t:
        raise NotFound("没有指定产品或 SKU")
    for cand in dict.fromkeys((t, t.upper())):
        try:
            return store.load(cand), None
        except (FileNotFoundError, ValueError, OSError):
            pass
    up = t.upper()
    tried = set()
    for cand in (up.split("-")[0], None):
        ids = [cand] if cand else [i["id"] for i in store.list_products()]
        for pid in ids:
            if pid in tried:
                continue
            tried.add(pid)
            try:
                p = store.load(pid)
            except (FileNotFoundError, ValueError, OSError):
                continue
            for i, v in enumerate(p.get("variants") or []):
                if str(v.get("sku") or "").strip().upper() == up:
                    return p, i
    raise NotFound(f"找不到产品或 SKU：{t}")


def _img(p, file=None):
    imgs = [i for i in p.get("images") or [] if i.get("file")]
    im = next((i for i in imgs if file and (i.get("file") == file or i.get("raw") == file)), None) or (imgs[0] if imgs else None)
    if not im:
        return ""
    return f"/files/{p['id']}/{'out' if im.get('processed') else 'raw'}/{im['file']}"


def _safe(fn, *a, **k):
    """一块出错不影响整个抽屉（记日志，这块不显示）。"""
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("3dops").warning("商品 360 %s 出错：%s", getattr(fn, "__name__", fn), e)
        return None


def _day(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


# ---------------- 各块 ----------------
def _variants(cfg, p, role):
    owner, see_price = role == "owner", role in ("owner", "listing")
    inv = modules.public("inv")
    c = db.conn()
    out = []
    for i, v in enumerate(p.get("variants") or []):
        sku = str(v.get("sku") or "").strip().upper()
        row = {"idx": i, "sku": sku, "opt1": v.get("opt1_zh") or "", "opt2": v.get("opt2_zh") or "", "image": _img(p, v.get("image"))}
        row["opt2_th"] = ((p.get("copy") or {}).get("options_th") or {}).get(row["opt2"]) or ""      # v2.50：规格的泰文名（泰文界面用）
        if see_price:
            pr = pricing.price_variant(cfg, v, p.get("markup"), p.get("material"))
            row.update(price=pr["final_price"], list_price=pr["list_price"])
            if owner:
                row.update(floor_price=pr["floor_price"], cost=pr["cost"]["total"], fee=pr["platform_fee"], profit=pr["profit"],
                           markup=pr["actual_markup"], below_floor=bool(pr["floor_price"] and pr["final_price"] < pr["floor_price"] - 0.01),
                           warning=pr["warning"])
        if sku:
            st = c.execute("SELECT qty, target FROM stock WHERE sku=?", (sku,)).fetchone()
            res = production.reserved(sku, c)
            qty = max(0, st["qty"]) if st else 0
            row.update(stock=qty, reserved=res, free=max(0, qty - res), target=st["target"] if st else None)
            if inv:
                loc = (_safe(inv.where_is, sku) or [None])[0]
                if loc:
                    row["location"] = {"code": loc[0], "zh": _safe(inv.human, loc[0]) or loc[0], "th": _safe(inv.human, loc[0], "th") or loc[0]}
        out.append(row)
    return out


def _sales(skus, pid):
    """近 30 天每天件数 + 全部订单（生命周期要用：第一次 / 最后一次卖出），按 (SKU, 平台)。"""
    c = db.conn()
    marks = ",".join("?" * len(skus)) or "''"
    rows = c.execute(f"""SELECT o.platform, o.order_time t, UPPER(i.sku) sku, i.qty q, i.item_total, i.unit_price FROM order_items i
                         JOIN orders o ON o.id=i.order_id
                         WHERE (UPPER(i.sku) IN ({marks}) OR i.product_id=?) AND o.status NOT IN ({','.join('?' * len(EXCLUDE))})""",
                     (*skus, pid, *EXCLUDE)).fetchall()
    now = time.time()
    today = dt.date.today()
    days = [(today - dt.timedelta(days=DAYS - 1 - k)).isoformat() for k in range(DAYS)]
    per_day = dict.fromkeys(days, 0)
    by = {}
    q30 = rev30 = 0
    for r in rows:
        q, t = int(r["q"] or 1), r["t"] or 0
        a = by.setdefault((r["sku"] or "", (r["platform"] or "").lower()), {"orders": [], "qty_total": 0, "qty_30d": 0, "last_sale": None})
        a["orders"].append((t, q))
        a["qty_total"] += q
        a["last_sale"] = max(a["last_sale"] or 0, t) or None
        if now - t <= DAYS * 86400:
            a["qty_30d"] += q
        d = _day(t) if t else ""
        if d in per_day:
            per_day[d] += q
            q30 += q
            rev30 += float(r["item_total"] if r["item_total"] is not None else (r["unit_price"] or 0) * q)
    return {"days": [{"day": d, "qty": per_day[d]} for d in days], "qty_30d": q30, "revenue_30d": round(rev30, 2)}, by


def _lifecycle(cfg, p, variants, online, by_sales):
    """每个 SKU × 平台的阶段和建议动作（规则和运营分析的「商品生命周期」一样）。"""
    from modules.ops import lifecycle as lc
    r = lc.rules(cfg)
    view = core_listing.v1_view(p)
    now = time.time()
    out = []
    for v in variants:
        if not v["sku"]:
            continue
        for plat in PLATFORMS:
            lst = view.get(plat) or {}
            onl = [{"status": o["status"], "item_id": o["item_id"], "created": o.get("created")} for o in online
                   if o["platform"] == plat and any(str(s.get("seller_sku") or "").upper() == v["sku"] for s in o["skus"])]
            if lst.get("status") in ("none", None) and not onl and plat != "lazada":
                continue
            sa = by_sales.get((v["sku"], plat)) or {"orders": [], "qty_total": 0, "qty_30d": 0, "last_sale": None}
            start, est = lc._start(lst, onl, p.get("exported_at"))
            stage = "draft" if p.get("draft") else lc._stage(r, lst, onl, start, sa, now)
            zh, th, level, act, act_th = lc.STAGES[stage]
            if stage == "rejected" and lst.get("note"):
                act, act_th = f"{act}（原因：{lst['note']}）", f"{act_th} (เหตุผล: {lst['note']})"
            out.append({"sku": v["sku"], "platform": plat, "stage": stage, "label": zh, "label_th": th, "level": level,
                        "action": act, "action_th": act_th, "start": start, "start_estimated": bool(est and start),
                        "qty_30d": sa["qty_30d"], "last_sale": sa["last_sale"]})
    order = lc.STAGE_ORDER
    out.sort(key=lambda x: (order.index(x["stage"]) if x["stage"] in order else 99, x["sku"], x["platform"]))
    return out


def _traffic(skus):
    from modules.ops import traffic
    out = []
    for s in skus:
        for plat in PLATFORMS:
            t = traffic.get(s, plat)
            if t:
                out.append({"sku": s, "platform": plat, **{k: t.get(k) for k in ("impressions", "visitors", "views", "add_to_cart", "orders",
                                                                                 "conversion", "period_text", "period_days", "ts")}})
    return out


def _comp(skus, my_prices):
    """关联了这个产品 SKU 的竞品：最新价格、评分、销量；中位价和我们的价格排第几（便宜的排前面）。"""
    from modules.ops import comp as cm
    c = db.conn()
    marks = ",".join("?" * len(skus)) or "''"
    ids = {}
    for r in c.execute(f"SELECT comp_id, sku FROM ops_comp_links WHERE UPPER(sku) IN ({marks})", skus):
        ids.setdefault(r["comp_id"], []).append(r["sku"])
    rows = []
    for cid, linked in ids.items():
        x = cm.get(cid)
        if not x or x.get("status") == "archived":
            continue
        ss = cm.snaps(cid)
        last = ss[-1] if ss else {}
        rows.append({"id": cid, "platform": x.get("platform"), "title": x.get("title") or last.get("title") or "", "shop": x.get("shop") or "",
                     "url": x.get("url") or "", "image": x.get("image") or "", "skus": sorted(linked),
                     "price": cm._eff(last), "list_price": last.get("list_price"), "rating": last.get("rating"), "reviews": last.get("reviews"),
                     "sold_text": last.get("sold_text") or "", "sold_30d": last.get("sold_30d"), "ts": last.get("ts")})
    rows.sort(key=lambda x: (x["price"] is None, x["price"] or 0))
    prices = sorted(x["price"] for x in rows if x["price"] is not None)
    mine = [x for x in my_prices if x]
    my = round(statistics.median(mine), 2) if mine else None
    out = {"rows": rows, "median": round(statistics.median(prices), 2) if prices else None,
           "min": prices[0] if prices else None, "max": prices[-1] if prices else None, "my_price": my}
    if my and prices:
        out["rank"] = {"rank": sum(1 for x in prices if x < my - 0.01) + 1, "of": len(prices) + 1}
        out["vs_median_pct"] = round((my / out["median"] - 1) * 100, 1) if out["median"] else None
    return out


def _reviews(online):
    item_ids = [o["item_id"] for o in online if o["platform"] == "lazada"]
    if not item_ids:
        return {"n": 0, "avg": None, "bad": 0, "items": []}
    from modules.ops import lazada
    lazada._ensure()
    marks = ",".join("?" * len(item_ids))
    rows = [dict(r) for r in db.conn().execute(
        f"SELECT rating, content, created, reply, item_id, images FROM oa_lz_review WHERE item_id IN ({marks}) ORDER BY created DESC", item_ids)]
    rated = [r["rating"] for r in rows if r["rating"]]
    return {"n": len(rows), "avg": round(sum(rated) / len(rated), 2) if rated else None, "bad": sum(1 for x in rated if x <= 3),
            "items": [{k: r[k] for k in ("rating", "content", "created", "reply", "images")} for r in rows[:8]]}


def _plans(cfg, skus, owner):
    from modules.ops import plans as pl
    marks = ",".join("?" * len(skus)) or "''"
    out = []
    for r in db.conn().execute(f"SELECT id FROM ops_plans WHERE status='active' AND UPPER(sku) IN ({marks}) ORDER BY id DESC", skus):
        p = pl.get(r["id"])
        pr = _safe(pl.progress, cfg, p) or {}
        tasks = _safe(pl.tasks, p["id"]) or []
        start = dt.date.fromisoformat(p["start_day"]) if p.get("start_day") else None
        today = dt.date.today().isoformat()
        due = [t for t in tasks if not t.get("done_at") and start and (start + dt.timedelta(days=t["offset"] or 0)).isoformat() <= today]
        row = {"id": p["id"], "sku": p["sku"], "platform": p["platform"], "kind": p["kind"],
               "kind_label": pl.KINDS.get(p["kind"], (p["kind"], p["kind"]))[0], "kind_th": pl.KINDS.get(p["kind"], (p["kind"], p["kind"]))[1],
               "start_day": p["start_day"], "days": p["days"], "target_daily": p["target_daily"], "elapsed": pr.get("elapsed"),
               "avg7": pr.get("avg7"), "ratio": pr.get("ratio"), "status": pr.get("status"), "status_label": pr.get("status_label"),
               "status_th": pr.get("status_th"), "tasks_due": [{"text": t.get("text"), "text_th": t.get("text_th")} for t in due[:3]]}
        if owner:
            row.update(actual_revenue=pr.get("actual_revenue"), actual_profit=pr.get("actual_profit"))
        out.append(row)
    return out


OPS_FIELDS = {"title_th": ("标题", "ชื่อสินค้า"), "attributes": ("属性", "คุณสมบัติ"), "price": ("售价", "ราคา"), "active": ("上下架", "เปิด/ปิดขาย")}


def _desc(before, after):
    """运营改动一句话（中文、泰文）：售价 199→179、标题、属性 颜色、上下架 True→False。"""
    zh, th = [], []
    for k, a in after.items():
        z, t = OPS_FIELDS.get(k, (k, k))
        if k == "attributes":
            tail = " " + ", ".join(a) if isinstance(a, dict) else ""
        elif k == "title_th":
            tail = ""
        else:
            tail = f" {before.get(k)}→{a}"
        zh.append(z + tail)
        th.append(t + tail)
    return "、".join(zh), ", ".join(th)


def _changes(p, skus, role):
    """运营系统写回的改动（待确认 / 已生效 / 撤回）+ 这个产品的操作记录（只给老板：和「操作记录」页一样）。"""
    out, pending = [], []
    lk = modules.public("link")
    if lk is not None:
        sk = set(skus)
        for ch in lk.opsapi.list_changes(product=p["id"], limit=30):
            if ch.get("product_id") != p["id"] and str(ch.get("sku") or "").upper() not in sk:
                continue
            desc, desc_th = _desc(ch.get("before") or {}, ch.get("after") or {})
            row = {"ts": ch["ts"], "who": ch.get("decided_by") or ch.get("key_name") or "", "what": desc, "what_th": desc_th, "sku": ch.get("sku") or "",
                   "reason": ch.get("reason") or "", "status": ch["status"], "status_zh": ch.get("status_zh"), "source": "ops", "id": ch["id"]}
            (pending if ch["status"] == "pending" else out).append(row)
    if role == "owner":
        try:                               # v2.50：操作名有泰文翻译（各模块 th.json）就带上
            th_map = modules.i18n_th()
        except Exception:  # noqa: BLE001
            th_map = {}
        for a in db.audit_list(limit=30, target=p["id"]):
            a = dict(a)
            act = a.get("action") or ""
            out.append({"ts": a["ts"], "who": a.get("username") or "", "what": act, "what_th": th_map.get(act) or None, "detail": a.get("detail") or "",
                        "source": "audit"})
    if p.get("edited_at") and not any(x["source"] == "audit" for x in out):
        out.append({"ts": p["edited_at"], "who": p.get("edited_by") or "", "what": "编辑产品资料", "what_th": "แก้ไขข้อมูลสินค้า", "source": "edit"})
    out.sort(key=lambda x: -(x["ts"] or 0))
    return out[:20], pending


def _jobs(skus, pid, role):
    c = db.conn()
    marks = ",".join("?" * len(skus)) or "''"
    rows = c.execute(f"""SELECT j.id, j.sku, j.qty, j.qty_done, j.status, j.kind, j.printer, j.planned_end, j.created_at, o.order_no, o.id order_id
                         FROM jobs j LEFT JOIN orders o ON o.id=j.order_id
                         WHERE (UPPER(j.sku) IN ({marks}) OR j.product_id=?) AND j.status IN ({','.join('?' * len(JOB_OPEN))})
                         ORDER BY j.id DESC LIMIT 30""", (*skus, pid, *JOB_OPEN)).fetchall()
    prs = load_config().get("printers") or []
    out = []
    for r in rows:
        d = dict(r)
        pi = d.pop("printer")
        d["printer_code"] = (prs[pi].get("code") or prs[pi].get("name") or "") if pi is not None and 0 <= pi < len(prs) else ""
        d["status_zh"] = production.STATUS_ZH.get(d["status"], d["status"])
        d["kind_zh"] = production.KIND_ZH.get(d.get("kind") or "order", "")
        d["remaining"] = max(0, int(d["qty"] or 1) - int(d["qty_done"] or 0))
        out.append(d)
    return out


def _orders(skus, pid, role):
    from core import orders as om
    c = db.conn()
    marks = ",".join("?" * len(skus)) or "''"
    rows = c.execute(f"""SELECT o.id, o.order_no, o.platform, o.shop, o.status, o.order_time, i.sku, i.variation, i.qty, i.unit_price, i.item_total
                         FROM order_items i JOIN orders o ON o.id=i.order_id
                         WHERE UPPER(i.sku) IN ({marks}) OR i.product_id=? ORDER BY o.order_time DESC, o.id DESC LIMIT 8""",
                     (*skus, pid)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["status_zh"] = om.STATUS_ZH.get(d["status"] or "", d["status"] or "")
        if role not in ("owner", "listing"):
            d.pop("unit_price", None)
            d.pop("item_total", None)
        out.append(d)
    return out


# ---------------- 汇总 ----------------
def view(target, user=None):
    role = (user or {}).get("role") or "owner"
    owner, staff = role == "owner", role in ("owner", "listing")
    p, focus = resolve(target)
    cfg = load_config()
    variants = _variants(cfg, p, role)
    skus = [v["sku"] for v in variants if v["sku"]]
    imgs = [f"/files/{p['id']}/{'out' if i.get('processed') else 'raw'}/{i['file']}" for i in p.get("images") or [] if i.get("file")]
    lst_view = core_listing.v1_view(p)
    out = {
        "ok": True, "role": role, "owner": owner, "prices": staff, "focus": focus, "target": str(target),
        "product": {"id": p["id"], "name_zh": p.get("name_zh") or "", "title_th": (p.get("copy") or {}).get("title_th") or "",
                    "image": imgs[0] if imgs else "", "images": imgs[:8], "material": p.get("material") or "",
                    "opt1_name": p.get("variation1_name_zh") or "", "opt2_name": p.get("variation2_name_zh") or "",
                    "active": p.get("active", True) is not False, "draft": bool(p.get("draft")),
                    "license_pending": (p.get("license_check") or {}).get("status") == "pending",    # v2.50 选品采用的草稿：许可待核验
                    "updated_at": p.get("updated_at") or None, "edited_at": p.get("edited_at") or None, "edited_by": p.get("edited_by") or "",
                    "listing": {k: {"status": v.get("status"), "status_zh": core_listing.STATUS_ZH.get(v.get("status") or "none", ""),
                                    "first_listed_at": v.get("first_listed_at"), "note": v.get("note")} for k, v in lst_view.items()}},
        "variants": variants,
    }
    # v2.50.1 选品采用的产品：模型文件数量 / 下载状态（「⬇ 下载模型文件」按钮）
    src = p.get("source") or {}
    if src.get("source") == "curate":
        cur = modules.public("curate")
        fs = _safe(cur.product_files, p["id"]) if cur is not None and hasattr(cur, "product_files") else None
        out["product"]["model_files"] = {"n": len(p.get("source_files") or []), "model": bool(p.get("model")), "status": fs or {},
                                         "inbox": bool(p.get("inbox")), "can": cur is not None}
    # 平台在售（上架模块）
    lst = modules.public("listing")
    online = []
    if lst is not None and hasattr(lst, "product_online"):
        online = _safe(lst.product_online, p["id"], skus) or []
        if not staff:
            for o in online:
                o.pop("price_min", None), o.pop("price_max", None)
                for s in o["skus"]:
                    s.pop("price", None), s.pop("special_price", None)
        out["online"] = online
    if lst is not None and staff and hasattr(lst, "stock_sync_recent"):       # v2.53 库存同步记录
        out["stocksync"] = _safe(lst.stock_sync_recent, skus, 10) or []
    sales, by_sales = _sales(skus, p["id"])
    if not staff:
        sales.pop("revenue_30d", None)
    out["sales"] = sales
    # 运营分析（生命周期、流量、竞品、评价、计划）：生产员工不看
    ops = modules.public("ops")
    if ops is not None and staff:
        lc = _safe(_lifecycle, cfg, p, variants, online, by_sales)
        if lc is not None:
            out["lifecycle"] = lc
        tr = _safe(_traffic, skus)
        if tr is not None:
            out["traffic"] = tr
        cp = _safe(_comp, skus, [v.get("price") for v in variants])
        if cp is not None:
            out["comp"] = cp
        if lst is not None:
            rv = _safe(_reviews, online)
            if rv is not None:
                out["reviews"] = rv
        pl = _safe(_plans, cfg, skus, owner)
        if pl is not None:
            out["plans"] = pl
    if staff:
        hist, pending = _changes(p, skus, role)
        out["changes"], out["pending"] = hist, pending
    out["suggestions"] = _suggest(out, owner)
    out["jobs"] = _jobs(skus, p["id"], role)
    out["orders"] = _orders(skus, p["id"], role)
    out["kpi"] = _kpi(out, owner)
    return out


def _suggest(d, owner):
    """抽屉里「计划与建议」的建议条：生命周期的建议动作（去重）、低于最低价（老板）、待确认的运营改动、库存不够。"""
    out, seen = [], set()
    for r in d.get("lifecycle") or []:
        if r["action"] and r["level"] in ("bad", "warn", "good", "info") and r["action"] not in seen:
            seen.add(r["action"])
            plat = PLAT_NAME.get(r["platform"], r["platform"])
            out.append({"tone": {"bad": "bad", "warn": "warn", "good": "ok"}.get(r["level"], ""), "zh": f"{r['sku']} · {plat}：{r['action']}",
                        "th": f"{r['sku']} · {plat}: {r['action_th']}"})
    if owner:
        for v in d["variants"]:
            if v.get("below_floor"):
                out.append({"tone": "bad", "zh": f"{v['sku']} 售价 {v['price']:g} 低于最低价 {v['floor_price']:g}",
                            "th": f"{v['sku']} ราคา {v['price']:g} ต่ำกว่าราคาขั้นต่ำ {v['floor_price']:g}"})
    n = len(d.get("pending") or [])
    if n:
        out.append({"tone": "warn", "zh": f"有 {n} 条运营改动等确认（商品 → 运营改动）", "th": f"มีการแก้ไขจากระบบวิเคราะห์ {n} รายการรอยืนยัน", "go": "opschg"})
    for v in d["variants"]:
        if v["sku"] and v.get("target") and (v.get("free") or 0) < v["target"]:
            out.append({"tone": "warn", "zh": f"{v['sku']} 可用库存 {v.get('free') or 0}，低于备货目标 {v['target']}",
                        "th": f"{v['sku']} สต็อกพร้อมใช้ {v.get('free') or 0} ต่ำกว่าเป้า {v['target']}"})
    return out[:12]


def _kpi(d, owner):
    """顶部数字：库存 / 销量是整个产品的（各规格加起来）；单件利润、阶段优先看点开的那个 SKU。"""
    vs = d["variants"]
    f = d.get("focus")
    pick = [vs[f]] if f is not None and f < len(vs) else vs
    k = {"stock": sum(v.get("stock") or 0 for v in vs), "free": sum(v.get("free") or 0 for v in vs),
         "sold_30d": d["sales"]["qty_30d"], "spark": [x["qty"] for x in d["sales"]["days"]]}
    if owner:
        prof = [v["profit"] for v in pick if v.get("profit") is not None]
        k["profit_unit"] = round(statistics.median(prof), 2) if prof else None
        k["profit_min"] = min(prof) if prof else None
        k["profit_max"] = max(prof) if prof else None
    lc = d.get("lifecycle")
    if lc:
        want = {v["sku"] for v in pick}
        top = next((r for r in lc if r["sku"] in want), lc[0])
        k["stage"] = {x: top[x] for x in ("stage", "label", "label_th", "level", "platform", "sku")}
    rv = d.get("reviews")
    if rv and rv["n"]:
        k["rating"], k["reviews"] = rv["avg"], rv["n"]
    return k
