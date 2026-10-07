"""按耗材自动算可售库存（v2.16）。

每个变体（颜色 × 规格）：
    这个颜色可用克数 = 剩余耗材 − 已排队任务要用的 − 安全余量（设置里的 stock_safety_g）
    能做件数 = 可用克数 ÷（单件克数 × 损耗系数）
    库存 = min(上限, 能做件数)；低于「低库存线」时按设置显示 0 或真实件数
随机颜色：用这个材料所有颜色加起来的可用克数算（单个颜色卖完了，随机颜色通常还有货）。
同一卷耗材是所有产品共用的：每个产品都按「这个颜色还能做几件」显示，不分摊（按单生产、补货快，同时被买光的概率低）。

总开关 cfg["stock_auto"]，产品里 p["stock_auto"] = True / False 可以单独开关（None = 跟总开关）。
没开的产品：库存 = 变体里手填的数，没填用默认库存（和以前一样）。

「要同步到平台」：stock_sync 表记着每个 SKU 上次同步到平台的数（导出上架表格、手动标记已改好、
以后接 Lazada 接口自动推送）。现在算出来的数和它差得够多（≥ stock_min_change，或者一边是 0 一边不是）就列进待同步。
"""
import math
import time

from . import codes, db, store
from .config import load_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_sync (
  sku TEXT NOT NULL, platform TEXT NOT NULL DEFAULT 'lazada', product_id TEXT,
  synced INTEGER, synced_at REAL, synced_by TEXT, how TEXT,
  PRIMARY KEY(sku, platform)
);
"""
_cache = {"t": 0, "v": None}


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()


def settings(cfg=None):
    cfg = cfg or load_config()

    def num(k, d):
        try:
            return float(cfg.get(k, d))
        except (TypeError, ValueError):
            return float(d)
    return {"on": bool(cfg.get("stock_auto")), "cap": int(num("stock_cap", 50)), "low_line": int(num("stock_low_line", 3)),
            "low_mode": "real" if cfg.get("stock_low_mode") == "real" else "zero", "min_change": max(1, int(num("stock_min_change", 3))),
            "loss": max(1.0, num("stock_loss_factor", 1.1)), "safety_g": max(0.0, num("stock_safety_g", 50)),
            "default": int(num("default_stock", 50))}


def enabled(p, cfg=None):
    v = p.get("stock_auto")
    if v in (True, False):
        return v
    return bool((cfg or load_config()).get("stock_auto"))


def names_codes(cfg):
    return {code for _zh, code, _th, _en in codes.color_table(cfg)}


def _ckey(cfg, color):
    c = codes.find_color(cfg, color)
    return c[1] if c else str(color or "").strip()


def available(cfg=None, fresh=True):
    """{(材料, 颜色代码): 可用克数}。fresh=False 时 3 秒内重复调用用缓存。导出几十个产品时先算一次传给 compute。"""
    now = time.time()
    if not fresh and _cache["v"] is not None and now - _cache["t"] < 3:
        return _cache["v"]
    cfg = cfg or load_config()
    st = settings(cfg)
    from . import inventory, materials
    out = {}
    for (m, ck), g in inventory.filament_available().items():     # v2.17：耗材数量以库存管理为准
        k = (m, ck if ck in names_codes(cfg) else _ckey(cfg, ck))
        out[k] = out.get(k, 0.0) + max(0.0, g - st["safety_g"])
    try:
        demand, _by_job = materials._job_demand()
    except Exception:  # noqa: BLE001
        demand = {}
    for (m, col), kg in demand.items():
        k = ((m or "PLA").upper(), _ckey(cfg, col))
        if k in out:
            out[k] = max(0.0, out[k] - kg * 1000.0)
    _cache.update(t=now, v=out)
    return out


def compute(p, cfg=None, avail=None):
    """每个变体一条：{sku, color, spec, stock, units, auto, reason}。顺序和 p["variants"] 一样。"""
    cfg = cfg or load_config()
    st = settings(cfg)
    auto = enabled(p, cfg)
    mat = (p.get("material") or "PLA").strip().upper()
    if auto and avail is None:
        avail = available(cfg)
    specs = {s["spec_id"]: s for s in p.get("specs") or []}
    out = []
    for v in p.get("variants") or []:
        row = {"sku": v.get("sku") or "", "color": v.get("opt1_zh") or "", "spec": v.get("opt2_zh") or "", "auto": auto,
               "units": None, "reason": ""}
        manual = v.get("stock")
        if not auto:
            row["stock"] = int(manual) if manual not in (None, "") else st["default"]
            row["reason"] = "手填" if manual not in (None, "") else "默认库存"
            row["why"] = [["stock.r.manual" if manual not in (None, "") else "stock.r.default", {}]]
            out.append(row)
            continue
        sp = specs.get(v.get("spec_id"))
        if sp and sp.get("status") == "review":
            row.update(stock=0, reason="规格待确认", why=[["stock.r.review", {}]])
            out.append(row)
            continue
        g = float(v.get("grams") or 0)
        if g <= 0:
            row.update(stock=st["default"] if manual in (None, "") else int(manual), reason="克数待补，暂用默认 / 手填库存",
                       why=[["stock.r.no_grams", {}]])
            out.append(row)
            continue
        rnd = codes.is_random(cfg, v.get("opt1_zh"))
        if rnd:
            have = sum(x for (m, col), x in avail.items() if m == mat and col != codes.RANDOM_CODE)
        elif not (v.get("opt1_zh") or "").strip():
            have = None
        else:
            have = avail.get((mat, _ckey(cfg, v.get("opt1_zh"))), 0.0)
        if have is None:
            row.update(stock=st["default"] if manual in (None, "") else int(manual), reason="还没选颜色", why=[["stock.r.no_color", {}]])
            out.append(row)
            continue
        units = int(math.floor(have / (g * st["loss"])))
        stock = min(st["cap"], units)
        reason = f"{'所有颜色' if rnd else row['color']}可用 {have:.0f} g，够做 {units} 件"
        why = [["stock.r.calc", {"c": "@all" if rnd else row["color"], "g": round(have), "u": units}]]
        if units < st["low_line"]:
            if st["low_mode"] == "zero":
                stock = 0
                reason += f"（低于 {st['low_line']} 件，显示 0）"
                why.append(["stock.r.low_zero", {"n": st["low_line"]}])
            else:
                reason += f"（低于 {st['low_line']} 件）"
                why.append(["stock.r.low_real", {"n": st["low_line"]}])
        row.update(stock=stock, units=units, reason=reason, why=why)
        out.append(row)
    return out


def stocks(p, cfg=None, avail=None):
    """导出上架表格用：每个变体的库存数。"""
    return [r["stock"] for r in compute(p, cfg, avail)]


# ---------------- 待同步到平台 ----------------
def _synced(platform="lazada"):
    try:
        return {r["sku"]: dict(r) for r in db.conn().execute("SELECT * FROM stock_sync WHERE platform=?", (platform,))}
    except Exception:  # noqa: BLE001
        return {}


def pending(platform="lazada", cfg=None):
    """开了自动库存、已经导出过的产品里，现在的库存和上次同步到平台的数差得够多的 SKU。"""
    cfg = cfg or load_config()
    st = settings(cfg)
    av = available(cfg, fresh=True)
    synced = _synced(platform)
    out = []
    for item in store.list_products():
        p = store.load(item["id"])
        if not enabled(p, cfg) or not p.get("exported_at"):
            continue
        for r in compute(p, cfg, av):
            if not r["sku"]:
                continue
            old = synced.get(r["sku"])
            last = old["synced"] if old else None
            diff = None if last is None else r["stock"] - last
            need = last is None or abs(diff) >= st["min_change"] or ((r["stock"] == 0) != (last == 0))
            if need:
                out.append({"sku": r["sku"], "product_id": p["id"], "name": p.get("name_zh", ""), "color": r["color"],
                            "spec": r["spec"], "stock": r["stock"], "last": last, "diff": diff, "reason": r["reason"], "why": r.get("why"),
                            "last_at": old["synced_at"] if old else None})
    out.sort(key=lambda x: (x["stock"] != 0, x["product_id"], x["sku"]))
    return out


def mark_synced(items, user="", how="manual", platform="lazada"):
    """items：[{sku, stock, product_id}]，记为已经同步到平台。"""
    c = db.conn()
    now = time.time()
    n = 0
    for it in items:
        sku = str(it.get("sku") or "").strip().upper()
        if not sku or it.get("stock") is None:
            continue
        c.execute("INSERT INTO stock_sync(sku, platform, product_id, synced, synced_at, synced_by, how) VALUES(?,?,?,?,?,?,?) "
                  "ON CONFLICT(sku, platform) DO UPDATE SET synced=excluded.synced, synced_at=excluded.synced_at, "
                  "synced_by=excluded.synced_by, how=excluded.how, product_id=excluded.product_id",
                  (sku, platform, it.get("product_id"), int(it["stock"]), now, user, how))
        n += 1
    c.commit()
    return n


def mark_exported(products, platform="lazada", user="", cfg=None):
    """导出上架表格时，表格里的库存就是平台上的库存：记为已同步。"""
    cfg = cfg or load_config()
    av = available(cfg, fresh=True)
    items = []
    for p in products:
        for r in compute(p, cfg, av):
            if r["sku"]:
                items.append({"sku": r["sku"], "stock": r["stock"], "product_id": p["id"]})
    return mark_synced(items, user, "export", platform)


def pick_random_color(material, grams_needed, product=None, cfg=None):
    """随机颜色的订单：选一个颜色来打。优先打印机上已经装着的（不用换料），其次产品上架的颜色里剩得最多的，
    最后是这个材料任何有货的颜色。返回 (颜色中文名, 说明)。"""
    cfg = cfg or load_config()
    mat = (material or "PLA").strip().upper()
    av = available(cfg, fresh=True)
    names = {code: zh for zh, code, _th, _en in codes.color_table(cfg)}
    listed = []
    for v in (product or {}).get("variants") or []:
        c = (v.get("opt1_zh") or "").strip()
        if c and not codes.is_random(cfg, c) and c not in listed:
            listed.append(c)
    need = float(grams_needed or 0)
    cands = {}
    for (m, code), g in av.items():
        if m == mat and code != codes.RANDOM_CODE and g >= need:
            cands[code] = g
    loaded = set()
    try:
        for r in db.conn().execute("SELECT color FROM spools WHERE UPPER(material)=? AND status='loaded' AND remaining_g>=?", (mat, need)):
            loaded.add(_ckey(cfg, r["color"]))
    except Exception:  # noqa: BLE001
        pass
    listed_codes = [_ckey(cfg, c) for c in listed]

    def score(code):
        return (code in loaded, code in listed_codes, cands.get(code, 0))
    if not cands:
        # 都不够：选剩得最多的（让人知道要补货）
        allc = {code: g for (m, code), g in av.items() if m == mat and code != codes.RANDOM_CODE}
        if not allc:
            first = listed[0] if listed else ""
            return first, "没有耗材库存记录，按产品第一个颜色" if first else "没有耗材库存记录，需要人工选颜色"
        code = max(allc, key=lambda k: allc[k])
        return names.get(code, code), f"所有颜色都不够 {need:.0f} g，选了剩得最多的（{allc[code]:.0f} g），要补货"
    code = max(cands, key=score)
    why = "打印机上已经装着" if code in loaded else ("产品上架颜色里剩得最多" if code in listed_codes else "剩得最多")
    return names.get(code, code), f"随机颜色 → {names.get(code, code)}（{why}，可用 {cands[code]:.0f} g）"
