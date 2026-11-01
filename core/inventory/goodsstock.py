"""成品备货（v2.54，仓库 → 库存 → 成品备货）：所有成品一张表，目标数量自动算，缺口一键补货。

数据：成品数量还是 production.stock（sku, qty, target）+ 库存管理里分类「成品」的物品（两边一直同步）；货位在 inv_loc_qty（modules/inv）。
  自产 own     3D 打印的（产品库里有这个 SKU，且没标「外购」）→ 补货走生产单（core/po.py）
  外购 buy     买来的（库存里有、产品库里没有；或产品 / 这个 SKU 标了外购）→ 补货走采购（采购单草稿）
目标数量     手动填了（stock.target）就用手动的；没填 = 自动 =
             近 N 天销量 ÷ N × 常备天数 + 安全库存；没有销量时用「分类默认」（设置里写 分类=数量）；都没有 = 0
缺口 gap     = 目标 − 能用的（库存 − 订单占住 − 次品 − 退货区） − 在做的（生产中 / 采购在途）；待检区的算「很快能用」，不算缺
设置（仓库 → 设置 → 成品备货）：gs_sales_days 看几天的销量 · stock_cover_days 常备几天 · gs_safety 安全库存 · gs_cat_default 分类默认 · gs_over_x 超过目标几倍算积压
"""
import math
import time

from .. import db
from ..config import load_config

DEFAULTS = {"gs_sales_days": 30, "stock_cover_days": 7, "gs_safety": 1, "gs_cat_default": "", "gs_over_x": 3, "inv_slow_days": 60}
UNAVAIL = ("qc", "returns", "defect")


def settings(cfg=None):
    cfg = cfg or load_config()
    out = {}
    for k, d in DEFAULTS.items():
        v = cfg.get(k)
        if k == "gs_cat_default":
            out[k] = str(v if v is not None else d)
            continue
        try:
            out[k] = float(v) if v not in (None, "") else float(d)
        except (TypeError, ValueError):
            out[k] = float(d)
    out["cat_default"] = parse_cat_default(out["gs_cat_default"])
    return out


def parse_cat_default(text):
    """'挂件=5, 摆件=3'（逗号 / 分号 / 换行隔开）→ {'挂件': 5, '摆件': 3}"""
    out = {}
    for part in str(text or "").replace("；", ";").replace("，", ",").replace("\n", ",").replace(";", ",").split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        try:
            out[k.strip()] = max(0, int(float(v)))
        except ValueError:
            pass
    return out


def _cat_of(p):
    cat = (p or {}).get("category")
    if isinstance(cat, dict):
        name = cat.get("name") or cat.get("name_zh") or cat.get("path")
        if name:
            return str(name)
        return str(cat.get("id") or cat.get("cat_id") or "").split("|")[-1]       # 选好的类目 id 是「类目表文件|类目名」
    return str(cat or "")


def _img(p, v=None):
    imgs = (p or {}).get("images") or []
    want = (v or {}).get("image")
    img = next((i for i in imgs if want and (i.get("file") == want or i.get("raw") == want)), None) or next((i for i in imgs if i.get("file")), None)
    if not img:
        return ""
    return f"/files/{p['id']}/{'out' if img.get('processed') else 'raw'}/{img['file']}"


def _is_buy(p, v, src):
    if src in ("own", "buy"):
        return src == "buy"
    if not p:
        return True
    return bool(p.get("purchased") or (v or {}).get("purchased") or str(p.get("sourcing") or "").lower() in ("buy", "purchased", "外购"))


def _sold(c, days):
    out = {}
    for r in c.execute("""SELECT UPPER(i.sku) sku, SUM(i.qty) q FROM order_items i JOIN orders o ON o.id=i.order_id
                          WHERE o.order_time>=? AND o.status NOT IN ('cancelled','unpaid','quote') GROUP BY UPPER(i.sku)""",
                       (time.time() - days * 86400,)):
        out[r["sku"]] = r["q"] or 0
    return out


def _wms(c):
    """(货位 {id: 货位带区类型}, {item_id: [(货位, 数量)]})；没用货位 → ({}, {})"""
    try:
        from modules.inv import wms
        locs = wms._locs(c)
        by = {}
        for r in wms._qty_rows(c):
            l = locs.get(r["loc_id"])
            if l:
                by.setdefault(r["item_id"], []).append((l, r["qty"]))
        return locs, by
    except Exception:  # noqa: BLE001  仓库模块关着
        return {}, {}


def rows(c=None):
    """所有成品，一行一个 SKU。"""
    from .. import orders, production, store
    c = c or db.conn()
    S = settings()
    days = max(1, int(S["gs_sales_days"]))
    cover, safety, over_x = S["stock_cover_days"], S["gs_safety"], S["gs_over_x"]
    sold_n, sold30 = _sold(c, days), (_sold(c, 30) if days != 30 else None)
    if sold30 is None:
        sold30 = sold_n
    stk = {r["sku"]: dict(r) for r in c.execute("SELECT * FROM stock")}
    items = {r["code"].upper(): dict(r) for r in c.execute("SELECT * FROM inv_items WHERE category='goods' AND active=1")}
    skus = sorted(set(stk) | set(items))
    idx = orders.sku_index()
    pcache = {}

    def prod(pid):
        if pid not in pcache:
            try:
                pcache[pid] = store.load(pid)
            except Exception:  # noqa: BLE001
                pcache[pid] = None
        return pcache[pid]
    locs, loc_by = _wms(c)
    making = {}
    for r in c.execute("SELECT UPPER(sku) sku, SUM(qty - COALESCE(qty_done,0)) q FROM jobs WHERE kind='stock' AND status IN ('todo','printing') GROUP BY UPPER(sku)"):
        making[r["sku"]] = r["q"] or 0
    transit = {}
    try:
        from . import purchase
        transit = purchase.in_transit()
    except Exception:  # noqa: BLE001
        pass
    last_out = {r["item_id"]: r["t"] for r in c.execute("SELECT item_id, MAX(ts) t FROM inv_moves WHERE qty<0 GROUP BY item_id")}
    now = time.time()
    slow_days = max(1, int(S["inv_slow_days"]))
    out = []
    for sku in skus:
        st, it = stk.get(sku) or {}, items.get(sku) or {}
        hit = idx.get(sku)
        p = prod(hit[0]) if hit else (prod(st.get("product_id")) if st.get("product_id") else None)
        v = (p.get("variants") or [])[hit[1]] if (p and hit and hit[1] < len(p.get("variants") or [])) else {}
        buy = _is_buy(p if hit else None, v, st.get("src"))
        cat = _cat_of(p) if hit else ""
        qty = int(st.get("qty") if st.get("qty") is not None else (it.get("qty") or 0))
        z = {"qc": 0, "returns": 0, "defect": 0}
        place, located = [], 0.0
        for l, q in loc_by.get(it.get("id"), []):
            place.append({"code": l["code"], "qty": round(q, 3), "ztype": l["ztype"]})
            located += q
            if l["ztype"] in z:
                z[l["ztype"]] += q
        place.sort(key=lambda x: (x["ztype"] != "pick", x["code"]))
        unplaced = max(0.0, qty - located) if locs else 0.0
        rsv = production.reserved(sku, c)
        unavail = int(sum(z.values()) + 1e-9)
        sellable = max(0, qty - unavail)
        have = max(0, qty - rsv - z["defect"] - z["returns"])
        sn = sold_n.get(sku, 0)
        daily = sn / days
        manual = st.get("target")
        if manual is not None:
            target, auto = int(manual), False
        else:
            auto = True
            target = math.ceil(daily * cover + safety) if sn > 0 else int(S["cat_default"].get(cat, 0))
        mk = making.get(sku, 0) + (transit.get(it.get("id"), 0) if buy and it.get("id") else 0)
        gap = max(0, int(math.ceil(target - have - mk)))
        cost = float(it.get("avg_cost") or 0) or 0.0
        if not cost:
            try:
                from . import goods
                cost = goods._unit_cost(sku, hit[0] if hit else None) or 0.0
            except Exception:  # noqa: BLE001
                cost = 0.0
        idle = (now - (last_out.get(it.get("id")) or it.get("created_at") or st.get("updated_at") or now)) / 86400
        free = max(0, sellable - rsv)
        d = {"sku": sku, "item_id": it.get("id"), "product_id": hit[0] if hit else (st.get("product_id") or ""), "in_library": bool(hit),
             "name": (p.get("name_zh") if p and hit else None) or st.get("name") or it.get("name_zh") or sku,
             "color": v.get("opt1_zh") or st.get("color") or "", "spec": v.get("opt2_zh") or "", "img": _img(p, v) if p and hit else "",
             "type": "buy" if buy else "own", "src": st.get("src") or "", "category": cat,
             "qty": qty, "sellable": sellable, "free": free, "reserved": rsv, "qc": int(z["qc"]), "returns": int(z["returns"]), "defect": int(z["defect"]),
             "locs": place, "unplaced": round(unplaced, 3),
             "target": target, "auto": auto, "manual": manual, "gap": gap, "sold": sn, "sold30": sold30.get(sku, 0), "daily": round(daily, 2),
             "cover_days": round(free / daily, 1) if daily > 0 else None, "making": mk, "unit_cost": round(cost, 2), "value": round(qty * cost, 2),
             "idle_days": round(idle), "days": days}
        gk = ["buy" if buy else "own"]
        if free <= 0:
            gk.append("out")
        if target > 0 and have + mk < target:
            gk.append("below")
        if target > 0 and have > target * over_x:
            gk.append("over")
        if unplaced > 0.0001:
            gk.append("put")
        if d["qc"] > 0:
            gk.append("qc")
        if qty > 0 and idle >= slow_days and sn == 0:
            gk.append("slow")
        gk.append("cat:" + (cat or "none"))
        d["gk"] = gk
        out.append(d)
    out.sort(key=lambda x: (-x["gap"], x["free"] > 0, x["sku"]))
    return out


def overview(c=None):
    rs = rows(c)
    gcount, cats = {}, {}
    for r in rs:
        for k in r["gk"]:
            if k.startswith("cat:"):
                cats[k[4:]] = cats.get(k[4:], 0) + 1
            else:
                gcount[k] = gcount.get(k, 0) + 1
    S = settings()
    kp = {"units": sum(r["qty"] for r in rs), "value": round(sum(r["value"] for r in rs), 2), "skus": len(rs),
          "below": gcount.get("below", 0), "out": gcount.get("out", 0), "put": gcount.get("put", 0),
          "put_units": int(sum(r["unplaced"] for r in rs)), "slow": gcount.get("slow", 0), "gap_units": sum(r["gap"] for r in rs),
          "qc_units": sum(r["qc"] for r in rs)}
    try:
        from modules.inv import wms
        wms_on = any(True for _ in wms._locs(db.conn()))
    except Exception:  # noqa: BLE001
        wms_on = False
    return {"rows": rs, "kpis": kp, "groups": gcount, "cats": [{"name": k, "n": v} for k, v in sorted(cats.items(), key=lambda x: -x[1])],
            "settings": {k: S[k] for k in DEFAULTS}, "wms": wms_on}


# ---------------- 加进成品备货 / 改目标 ----------------
def _variants_of(pid):
    from .. import store
    p = store.load(pid)
    return [(v.get("sku") or "").strip().upper() for v in p.get("variants") or [] if (v.get("sku") or "").strip()], p


def add(skus=None, product_ids=None, group=None, src=None, user=""):
    """加进成品备货（数量 0、目标自动）。skus 直接给；product_ids 把产品的所有规格 SKU 都加；group = {"category": 名} 或 {"tag": 标签id} 按分组加。
    返回 {added, existed, missing}。"""
    from .. import orders, production, store
    c = db.conn()
    want = [str(s).strip().upper() for s in skus or [] if str(s).strip()]
    for pid in product_ids or []:
        try:
            want += _variants_of(pid)[0]
        except Exception:  # noqa: BLE001
            pass
    if group:
        for it in store.list_products():
            try:
                p = store.load(it["id"])
            except Exception:  # noqa: BLE001
                continue
            if group.get("category") and _cat_of(p) != group["category"]:
                continue
            if group.get("tag") not in (None, "") and group["tag"] not in (p.get("groups") or []) and str(group["tag"]) not in [str(x) for x in p.get("groups") or []]:
                continue
            if not group.get("category") and group.get("tag") in (None, ""):
                continue
            want += [(v.get("sku") or "").strip().upper() for v in p.get("variants") or [] if (v.get("sku") or "").strip()]
    if not want:
        raise ValueError("没有选到 SKU")
    idx = orders.sku_index()
    added, existed, missing = [], [], []
    for sku in dict.fromkeys(want):
        hit = orders.match_sku(sku, idx) if sku in idx else None
        have_item = c.execute("SELECT 1 FROM inv_items WHERE category='goods' AND UPPER(code)=?", (sku,)).fetchone()
        if not hit and not have_item:
            missing.append(sku)
            continue
        if c.execute("SELECT 1 FROM stock WHERE sku=?", (sku,)).fetchone():
            existed.append(sku)
            continue
        info = orders._variant_info(*hit) if hit else {}
        c.execute("INSERT INTO stock(sku, product_id, name, color, qty, target, src, updated_at) VALUES(?,?,?,?,0,NULL,?,?)",
                  (sku, hit[0] if hit else None, (info or {}).get("name") or "", (info or {}).get("color") or "", src if src in ("own", "buy") else None, time.time()))
        try:
            from . import goods
            goods.ensure_item(c, sku, hit[0] if hit else None, (info or {}).get("name") or "", (info or {}).get("color") or "")
        except Exception:  # noqa: BLE001
            pass
        added.append(sku)
    c.commit()
    db.audit(user, "加进成品备货", ",".join(added)[:200], f"新增 {len(added)}，已有 {len(existed)}，找不到 {len(missing)}")
    return {"added": added, "existed": existed, "missing": missing}


def set_target(skus, target, user=""):
    """改目标数量；target 为空 / None = 改回自动。"""
    c = db.conn()
    n = 0
    for sku in [str(s).strip().upper() for s in skus or [] if str(s).strip()]:
        t = None if target in (None, "") else max(0, int(float(target)))
        c.execute("INSERT INTO stock(sku, qty, target, updated_at) VALUES(?,0,?,?) ON CONFLICT(sku) DO UPDATE SET target=excluded.target, updated_at=excluded.updated_at",
                  (sku, t, time.time()))
        n += 1
    c.commit()
    db.audit(user, "改成品目标数量", ",".join(skus or [])[:200], "自动" if target in (None, "") else str(target))
    return n


def set_src(skus, src, user=""):
    """标 自产 / 外购（空 = 按产品库自动判断）。"""
    if src not in ("own", "buy", "", None):
        raise ValueError("要选 自产 或 外购")
    c = db.conn()
    for sku in [str(s).strip().upper() for s in skus or [] if str(s).strip()]:
        c.execute("INSERT INTO stock(sku, qty, src, updated_at) VALUES(?,0,?,?) ON CONFLICT(sku) DO UPDATE SET src=excluded.src", (sku, src or None, time.time()))
    c.commit()
    return len(skus or [])


def remove(skus, user=""):
    """从成品备货里去掉（只清目标和标记；有库存的不删）。"""
    c = db.conn()
    n = 0
    for sku in [str(s).strip().upper() for s in skus or []]:
        r = c.execute("SELECT qty FROM stock WHERE sku=?", (sku,)).fetchone()
        if r and (r["qty"] or 0) > 0:
            c.execute("UPDATE stock SET target=NULL, src=NULL WHERE sku=?", (sku,))
        else:
            c.execute("DELETE FROM stock WHERE sku=?", (sku,))
            n += 1
    c.commit()
    return n


# ---------------- 一键补货 ----------------
def plan(skus=None, group=None):
    """补货预览：[{sku, name, type, gap, per_plate, qty}]（自产按盘数往上取整，外购按缺口）。"""
    from .. import production
    want = {str(s).strip().upper() for s in skus or [] if str(s).strip()}
    out = []
    for r in rows():
        if r["gap"] <= 0 or (want and r["sku"] not in want):
            continue
        if group and group not in r["gk"]:
            continue
        per = production.sku_per_plate(r["sku"]) if r["type"] == "own" else 1
        qty = int(math.ceil(r["gap"] / per) * per) if per > 1 else r["gap"]
        out.append({"sku": r["sku"], "name": r["name"], "color": r["color"], "type": r["type"], "gap": r["gap"], "per_plate": per, "qty": qty,
                    "item_id": r["item_id"], "img": r["img"], "unit_cost": r["unit_cost"]})
    return out


def replenish(lines=None, skus=None, group=None, user="", release=False, priority=0, due=None, printers=None):
    """一键补货：自产 → 一张生产单（草稿；release=True 马上下达）；外购 → 采购单草稿（按供应商分）。
    lines = [{sku, qty}]（用户在预览里改过数量）；不给就按 plan(skus, group)。返回 {po, purchase, own, buy, skipped}。"""
    from .. import modules, po as _po
    pl = {x["sku"]: x for x in plan(skus, group)}
    if lines:
        sel = []
        for ln in lines:
            sku = str(ln.get("sku") or "").strip().upper()
            q = int(float(ln.get("qty") or 0))
            if sku and q > 0:
                base = pl.get(sku) or {"sku": sku, "type": next((r["type"] for r in rows() if r["sku"] == sku), "own"), "item_id": None}
                sel.append(dict(base, qty=q))
    else:
        sel = list(pl.values())
    if not sel:
        raise ValueError("现在没有需要补的（都达到目标数量了）")
    own = [x for x in sel if x["type"] == "own"]
    buy = [x for x in sel if x["type"] == "buy"]
    out = {"po": None, "purchase": [], "own": len(own), "buy": len(buy), "skipped": []}
    if own:
        out["po"] = _po.create([{"sku": x["sku"], "qty": x["qty"]} for x in own], "stock", user, priority=priority, due=due,
                               note="成品备货补货", printers=printers, release=release)
    if buy:
        c = db.conn()
        pur = modules.public("pur")
        ls = []
        for x in buy:
            iid = x.get("item_id") or (c.execute("SELECT id FROM inv_items WHERE category='goods' AND UPPER(code)=?", (x["sku"],)).fetchone() or [None])[0]
            if not iid:
                out["skipped"].append(x["sku"])
                continue
            ls.append({"item_id": iid, "qty": x["qty"], "unit_cost": x.get("unit_cost") or None})
        if ls:
            if pur is not None:
                out["purchase"] = pur.draft_po(ls, user, "成品备货补货（外购）")
            else:
                from . import purchase
                groups = {}
                for ln in ls:
                    sup = (c.execute("SELECT supplier_id FROM inv_items WHERE id=?", (ln["item_id"],)).fetchone() or [None])[0]
                    groups.setdefault(sup, []).append(ln)
                out["purchase"] = [purchase.save_po({"supplier_id": s, "lines": v, "note": "成品备货补货（外购）"}, user) for s, v in groups.items()]
    db.audit(user, "成品备货补货", f"自产 {len(own)} 外购 {len(buy)}", (out["po"] or {}).get("no", ""))
    return out
