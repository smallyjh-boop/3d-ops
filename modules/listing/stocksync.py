"""库存同步（v2.53）：算出每个 SKU 在每个店铺该显示多少库存，和平台上实际显示的对照，差了就推（接口店铺）或出导出表（没接口的店铺）。

可售（推到平台的数）：
    实物可售 = 成品库存 − 订单占住的 − 安全库存          （成品库存读 core/production.stock_qty；设置选「拣货区」时只算拣货区货位上的）
    按需打印的虚拟库存 = min(上限, 耗材够做几件, 打印机产能)   （耗材够做几件 = stockcalc 的「按耗材自动算库存」：克数 ÷ 每件克数含冲刷损耗；不够 → 0）
    SKU 可售 = 实物可售 + 虚拟库存
多店铺分配：share 每个店铺都显示全部 / percent 按比例（% 的可售）/ fixed 固定件数（最多不超过可售）。
规则优先级（每个字段）：SKU+店铺 > SKU > 产品+店铺 > 产品 > 店铺 > 全局默认（设置里的 ss_* 键）。
单元格（SKU × 店铺）状态：synced 已同步 / pending 待同步 / failed 同步失败 / locked 已锁定 / delisted 平台已下架。
推送：事件（成品库存变化、订单状态变化）+ 定时检查；失败自动重试，次数用完变待办；没接口的店铺出「待导出」表，上传后点「已上传」。
平台适配器见 stockadapters.py（Shopee / TikTok 接口通了以后只加适配器）。
表：ss_rules 规则、ss_state 每个 SKU×店铺的同步状态、ss_log 同步记录。
"""
import json
import math
import os
import threading
import time

from core import db, store
from core.config import load_config

from . import stockadapters

SCHEMA = """
CREATE TABLE IF NOT EXISTS ss_rules (
  scope TEXT NOT NULL, key TEXT NOT NULL DEFAULT '', shop_id INTEGER NOT NULL DEFAULT 0, data TEXT,
  PRIMARY KEY(scope, key, shop_id)
);
CREATE TABLE IF NOT EXISTS ss_state (
  sku TEXT NOT NULL, shop_id INTEGER NOT NULL, pushed INTEGER, pushed_at REAL, platform_qty INTEGER, platform_at REAL, plat_status TEXT,
  locked INTEGER, paused INTEGER DEFAULT 0, want INTEGER, export_qty INTEGER,
  fails INTEGER DEFAULT 0, error TEXT, error_kind TEXT, next_retry REAL, first_seen REAL,
  PRIMARY KEY(sku, shop_id)
);
CREATE TABLE IF NOT EXISTS ss_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, sku TEXT, shop_id INTEGER, shop TEXT, old INTEGER, new INTEGER,
  reason TEXT, ok INTEGER, result TEXT, username TEXT
);
CREATE INDEX IF NOT EXISTS ss_log_sku ON ss_log(sku, ts);
"""
REASONS = ("ship", "in", "produce", "manual", "timer", "rule")          # 出货 / 入库 / 生产完成 / 手动 / 定时 / 规则变更
REASON_ZH = {"ship": "出货", "in": "入库", "produce": "生产完成", "manual": "手动", "timer": "定时", "rule": "规则变更", "event": "库存变化"}
FIELDS = ("safety", "alloc", "alloc_val", "virtual", "cap")
INLINE = False                  # 测试用：库存变化马上同步，不等后台线程
_inited = set()
_dirty = set()
_dirty_reason = {}
_lock = threading.Lock()
_timer = {"t": None}
_idx = {"t": 0, "v": None, "path": None}
PULL_INFO = {}                  # {shop_id: {"at", "error"}}


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()
    _inited.add(db.DB_PATH)


def _c():
    if db.DB_PATH not in _inited:
        init()
    return db.conn()


def reset_cache():
    _idx.update(t=0, v=None)


# ---------------- 设置（全局默认） ----------------
def settings(cfg=None):
    cfg = cfg or load_config()

    def num(k, d):
        try:
            return float(cfg.get(k, d))
        except (TypeError, ValueError):
            return float(d)
    return {"safety": int(num("ss_safety", 0)), "cap": int(num("ss_cap", 20)), "printer_units": int(num("ss_printer_units", 0)),
            "virtual_min": max(1, int(num("ss_virtual_min", 1))), "interval": int(num("ss_interval_min", 15)),
            "low_qty": int(num("ss_low_qty", 2)), "cover_days": num("ss_cover_days", 3), "mismatch_min": max(1, int(num("ss_mismatch_min", 1))),
            "unsynced_hours": num("ss_unsynced_hours", 24), "retry_max": max(1, int(num("ss_retry_max", 3))),
            "event": str(cfg.get("ss_event_sync", "1")) not in ("0", "False", "false", ""), "source": "pick" if cfg.get("ss_source") == "pick" else "total",
            "alloc": cfg.get("ss_alloc") if cfg.get("ss_alloc") in ("share", "percent", "fixed") else "share"}


# ---------------- 规则 ----------------
def rules_all():
    out = {}
    for r in _c().execute("SELECT scope, key, shop_id, data FROM ss_rules"):
        try:
            out[(r["scope"], r["key"], r["shop_id"])] = json.loads(r["data"] or "{}")
        except ValueError:
            pass
    return out


def get_rule(scope, key="", shop_id=0):
    return rules_all().get((scope, key.upper() if scope == "sku" else key, int(shop_id or 0))) or {}


def set_rule(scope, key, shop_id, data, user=""):
    """保存一条规则（只存给了的字段；字段给 None = 去掉）。返回新规则。"""
    if scope not in ("sku", "product", "shop"):
        raise ValueError("规则范围不对")
    key = (key or "").strip()
    key = key.upper() if scope == "sku" else key
    cur = get_rule(scope, key, shop_id)
    for f in FIELDS:
        if f in data:
            if data[f] in (None, ""):
                cur.pop(f, None)
            else:
                cur[f] = data[f]
    if cur.get("alloc") not in (None, "share", "percent", "fixed"):
        raise ValueError("分配方式只能是 share / percent / fixed")
    if cur.get("virtual") not in (None, "on", "off"):
        raise ValueError("virtual 只能是 on / off")
    c = _c()
    if cur:
        c.execute("INSERT OR REPLACE INTO ss_rules(scope, key, shop_id, data) VALUES(?,?,?,?)", (scope, key, int(shop_id or 0), json.dumps(cur)))
    else:
        c.execute("DELETE FROM ss_rules WHERE scope=? AND key=? AND shop_id=?", (scope, key, int(shop_id or 0)))
    c.commit()
    return cur


def _resolve(rules, st, sku, pid, shop_id):
    """每个字段按优先级取第一个有的；最后落到全局默认。"""
    chain = [rules.get(("sku", sku, shop_id)), rules.get(("sku", sku, 0)), rules.get(("product", pid, shop_id)),
             rules.get(("product", pid, 0)), rules.get(("shop", "", shop_id))]
    out = {"safety": st["safety"], "alloc": st["alloc"], "alloc_val": None, "virtual": None, "cap": st["cap"]}
    for f in FIELDS:
        for r in chain:
            if r and r.get(f) not in (None, ""):
                out[f] = r[f]
                break
    return out


# ---------------- 店铺 / SKU 范围 ----------------
def shops(only_listed=False):
    """[{id, platform, name, enabled, api}]；Shopee 没建店铺时补一个虚拟的（id = -1），出导出表用。"""
    out = []
    for r in _c().execute("SELECT id, platform, name, enabled FROM shops ORDER BY id"):
        s = dict(r)
        s["api"] = bool(stockadapters.get(s["platform"]).api_ready(s))
        out.append(s)
    if not any(s["platform"] == "shopee" for s in out):
        v = {"id": -1, "platform": "shopee", "name": "Shopee", "enabled": 1}
        v["api"] = bool(stockadapters.get("shopee").api_ready(v))
        out.append(v)
    return out


def _index():
    now = time.time()
    if _idx["v"] is not None and now - _idx["t"] < 20 and _idx["path"] == db.DB_PATH:
        return _idx["v"]
    from core import listing
    v = {}
    for it in store.list_products():
        try:
            p = store.load(it["id"])
        except FileNotFoundError:
            continue
        plats = {pl for pl in ("lazada", "shopee") if listing.exported_to(p, pl)}
        for i, var in enumerate(p.get("variants") or []):
            sku = (var.get("sku") or "").strip().upper()
            if sku:
                v[sku] = {"p": p, "i": i, "plats": plats}
    _idx.update(t=now, v=v, path=db.DB_PATH)
    return v


def product_of(sku):
    h = _index().get((sku or "").upper())
    return h["p"]["id"] if h else (sku or "").rsplit("-", 2)[0]


def _online_sets():
    """{(shop_id, SKU)} 和 {(shop_id, SKU): 平台状态}：在线商品表里有的（对上了 ERP 的 SKU）。"""
    have, stat = set(), {}
    try:
        for r in _c().execute("SELECT shop_id, status, skus FROM online_items"):
            for s in json.loads(r["skus"] or "[]"):
                k = str(s.get("seller_sku") or "").strip().upper()
                if k:
                    have.add((r["shop_id"], k))
                    stat[(r["shop_id"], k)] = r["status"]
    except Exception:  # noqa: BLE001
        pass
    return have, stat


# ---------------- 库存来源 ----------------
def on_hand(sku, source="total"):
    from core import chain, production
    if source == "pick":
        inv = chain.inv() if hasattr(chain, "inv") else None
        if inv:
            from core import modules
            pub = modules.public("inv")
            if pub is not None:
                try:
                    n = 0.0
                    for loc, q in pub.where_is(sku) or []:
                        if (pub.zone_of(loc) or {}).get("ztype") == "pick":
                            n += float(q or 0)
                    return int(n)
                except Exception:  # noqa: BLE001
                    pass
    return production.sellable_qty(sku)


def _demand():
    """{SKU: 待发货订单要的件数}、{SKU: 近 30 天卖出}。"""
    c = _c()
    open_, sold = {}, {}
    for r in c.execute("SELECT UPPER(i.sku) AS sku, SUM(i.qty) AS n FROM order_items i JOIN orders o ON o.id=i.order_id "
                       "WHERE o.status IN ('to_ship') GROUP BY UPPER(i.sku)"):
        open_[r["sku"]] = int(r["n"] or 0)
    for r in c.execute("SELECT UPPER(i.sku) AS sku, SUM(i.qty) AS n FROM order_items i JOIN orders o ON o.id=i.order_id "
                       "WHERE o.order_time>=? AND o.status NOT IN ('cancelled','unpaid','quote') GROUP BY UPPER(i.sku)", (time.time() - 30 * 86400,)):
        sold[r["sku"]] = int(r["n"] or 0)
    return open_, sold


def printer_count(cfg=None):
    prs = (cfg or load_config()).get("printers") or []
    return len([p for p in prs if isinstance(p, dict) and p.get("enabled", True) is not False]) or 0


def _units(p, cfg, avail):
    """{SKU: 耗材够做几件}：stockcalc 的「按耗材自动算库存」逻辑（克数 ÷（每件克数 × 冲刷损耗）），没开自动库存的产品也按这个算。"""
    from core import stockcalc
    rows = stockcalc.compute({**p, "stock_auto": True}, cfg, avail)
    return {r["sku"].upper(): r.get("units") for r in rows if r["sku"]}


# ---------------- 计算 ----------------
def compute(skus=None, shop_ids=None):
    """返回 {"shops", "rows", "kpi", "settings"}。skus 给了就只算这些。"""
    from core import production, stockcalc
    cfg = load_config()
    st = settings(cfg)
    rules = rules_all()
    shp = [s for s in shops() if not shop_ids or s["id"] in shop_ids]
    idx = _index()
    want = {s.upper() for s in skus} if skus else None
    have, plat_stat = _online_sets()
    c = _c()
    states = {(r["sku"], r["shop_id"]): dict(r) for r in c.execute("SELECT * FROM ss_state")}
    open_, sold = _demand()
    avail = stockcalc.available(cfg, fresh=True)
    units_cache = {}
    pc = printer_count(cfg)
    now = time.time()
    rows = []
    kpi = {"pending": 0, "failed": 0, "mismatch": 0, "low": 0, "oversold": 0, "locked": 0, "total": 0}
    for sku in sorted(idx):
        if want and sku not in want:
            continue
        h = idx[sku]
        p, v = h["p"], h["p"]["variants"][h["i"]]
        in_shops = [s for s in shp if (s["platform"] in h["plats"]) or (s["id"], sku) in have]
        if not in_shops:
            continue
        pid = p["id"]
        if pid not in units_cache:
            units_cache[pid] = _units(p, cfg, avail)
        units = units_cache[pid].get(sku)
        oh = on_hand(sku, st["source"])
        rsv = production.reserved(sku)
        row = {"sku": sku, "product_id": pid, "name": p.get("name_zh", ""), "color": v.get("opt1_zh") or "", "spec": v.get("opt2_zh") or "",
               "on_hand": oh, "reserved": rsv, "units": units, "open_orders": open_.get(sku, 0), "sold30": sold.get(sku, 0), "cells": {}}
        auto_on = stockcalc.enabled(p, cfg)
        cells = {}
        for s in in_shops:
            rule = _resolve(rules, st, sku, pid, s["id"])
            safety = max(0, int(rule["safety"] or 0))
            phys = max(0, oh - rsv - safety)
            virt_on = (rule["virtual"] == "on") or (rule["virtual"] is None and auto_on)
            virt = 0
            if virt_on and units:
                cap = int(rule["cap"] or 0) or 10 ** 9
                pcap = st["printer_units"] * pc if st["printer_units"] and pc else 10 ** 9
                virt = min(cap, units, pcap)
                if virt < st["virtual_min"]:
                    virt = 0                                       # 耗材不够 → 掉到 0
            cells[s["id"]] = {"shop": s, "rule": rule, "phys": phys, "virt": virt, "pool": phys + virt, "raw": oh - rsv - safety}
        # 分配：fixed 先定，percent 按各自的池子比例，share 全给
        for sid, cc in cells.items():
            a, pool = cc["rule"]["alloc"], cc["pool"]
            try:
                val = float(cc["rule"]["alloc_val"]) if cc["rule"]["alloc_val"] not in (None, "") else None
            except (TypeError, ValueError):
                val = None
            if a == "percent":
                alloc = int(math.floor(pool * (100.0 if val is None else val) / 100.0))
            elif a == "fixed":
                alloc = min(pool, int(val or 0))
            else:
                alloc = pool
            cc["alloc"] = max(0, alloc)
        total = max((cc["pool"] for cc in cells.values()), default=0)
        row["sellable"] = total
        row["virtual"] = max((cc["virt"] for cc in cells.values()), default=0)
        supply = oh + (units or 0 if (auto_on or any(cc["virt"] for cc in cells.values())) else 0)
        row["oversold"] = row["open_orders"] > supply or oh - rsv < 0
        daily = row["sold30"] / 30.0
        row["cover_days"] = round(total / daily, 1) if daily > 0 else None
        row["low"] = total <= st["low_qty"] or (row["cover_days"] is not None and row["cover_days"] < st["cover_days"])
        for sid, cc in cells.items():
            s = cc["shop"]
            ss = states.get((sku, sid)) or {}
            locked = ss.get("locked")
            if locked is not None:
                target = int(locked)
            elif ss.get("paused"):
                target = 0
            elif ss.get("want") is not None:
                target = int(ss["want"])
            else:
                target = cc["alloc"]
            last = ss.get("pushed")
            plat = ss.get("platform_qty")
            pstat = plat_stat.get((sid, sku)) or ss.get("plat_status") or ""
            if pstat in ("inactive", "deleted"):
                status = "delisted"
            elif locked is not None:
                status = "locked"
            elif (ss.get("fails") or 0) > 0 and ss.get("error"):
                status = "failed"
            elif last is None or target != last:
                status = "pending"
            else:
                status = "synced"
            ref = last if last is not None else target
            mismatch = s["api"] and plat is not None and abs(plat - ref) >= st["mismatch_min"] and status not in ("delisted",)
            since = ss.get("pushed_at") or ss.get("first_seen")
            row["cells"][sid] = {
                "shop_id": sid, "target": target, "computed": cc["alloc"], "phys": cc["phys"], "virt": cc["virt"], "platform": plat,
                "diff": (plat - target) if plat is not None else ((last - target) if last is not None else None), "last": last,
                "last_at": ss.get("pushed_at"), "status": status, "locked": locked is not None, "lock_qty": locked,
                "paused": bool(ss.get("paused")), "error": ss.get("error") or "", "error_kind": ss.get("error_kind") or "",
                "fails": ss.get("fails") or 0, "mismatch": bool(mismatch), "api": s["api"], "since": since,
                "stale": bool(status in ("pending", "failed") and since and now - since > st["unsynced_hours"] * 3600),
                "rule": cc["rule"], "raw": cc["raw"]}
            kpi["total"] += 1
            if status == "pending":
                kpi["pending"] += 1
            elif status == "failed":
                kpi["failed"] += 1
            elif status == "locked":
                kpi["locked"] += 1
            kpi["mismatch"] += bool(mismatch)
        kpi["low"] += bool(row["low"])
        kpi["oversold"] += bool(row["oversold"])
        rows.append(row)
    return {"shops": shp, "rows": rows, "kpi": kpi, "settings": st}


# ---------------- 记录 ----------------
def _log(sku, shop, old, new, reason, ok, result, user):
    c = _c()
    c.execute("INSERT INTO ss_log(ts, sku, shop_id, shop, old, new, reason, ok, result, username) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (time.time(), sku, shop["id"], shop["name"], old, new, reason, 1 if ok else 0, result or "", user))


def log_list(sku="", shop_id=None, reason="", result="", days=30, limit=200):
    q, a = "SELECT * FROM ss_log WHERE ts>=?", [time.time() - days * 86400]
    if sku:
        q += " AND sku LIKE ?"
        a.append(f"%{sku.upper()}%")
    if shop_id not in (None, "", 0, "0"):
        q += " AND shop_id=?"
        a.append(int(shop_id))
    if reason:
        q += " AND reason=?"
        a.append(reason)
    if result in ("ok", "fail"):
        q += " AND ok=?"
        a.append(1 if result == "ok" else 0)
    rows = [dict(r) for r in _c().execute(q + " ORDER BY id DESC LIMIT ?", a + [int(limit)])]
    for r in rows:
        r["reason_zh"] = REASON_ZH.get(r["reason"], r["reason"])
    return rows


def trend(days=7):
    """近几天每天推送次数 [{day, n, fail}]（对照总表的图表）。"""
    import datetime as dt
    out = []
    today = dt.date.today()
    for i in range(days - 1, -1, -1):
        d = today - dt.timedelta(days=i)
        t0 = time.mktime(d.timetuple())
        r = _c().execute("SELECT COUNT(*) n, SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) f FROM ss_log WHERE ts>=? AND ts<?", (t0, t0 + 86400)).fetchone()
        out.append({"day": d.isoformat(), "n": r["n"] or 0, "fail": r["f"] or 0})
    return out


def recent_for(skus, limit=10):
    """商品 360 用：这些 SKU 最近的同步记录。"""
    skus = [s.upper() for s in skus if s]
    if not skus:
        return []
    ph = ",".join("?" * len(skus))
    rows = [dict(r) for r in _c().execute(f"SELECT * FROM ss_log WHERE sku IN ({ph}) ORDER BY id DESC LIMIT ?", skus + [int(limit)])]
    for r in rows:
        r["reason_zh"] = REASON_ZH.get(r["reason"], r["reason"])
    return rows


# ---------------- 状态写入 ----------------
def _set_state(sku, sid, **kw):
    c = _c()
    c.execute("INSERT OR IGNORE INTO ss_state(sku, shop_id, first_seen) VALUES(?,?,?)", (sku, sid, time.time()))
    if kw:
        c.execute("UPDATE ss_state SET " + ", ".join(f"{k}=?" for k in kw) + " WHERE sku=? AND shop_id=?", list(kw.values()) + [sku, sid])
    c.commit()


def touch_all(data):
    """周期检查时：每个单元格记下第一次出现的时间（「超过 1 天没同步」从这里算）。"""
    c = _c()
    now = time.time()
    for r in data["rows"]:
        for sid in r["cells"]:
            c.execute("INSERT OR IGNORE INTO ss_state(sku, shop_id, first_seen) VALUES(?,?,?)", (r["sku"], sid, now))
    c.commit()


# ---------------- 推送 ----------------
def push_cells(cells, reason="manual", user="", data=None, force=False, override=None):
    """cells = [(sku, shop_id)]；只推接口店铺（没接口的留在待导出）。
    data：已经算好的 compute() 结果。override：{(sku, shop_id): 数量}（行内改数字用）。
    返回 {pushed, failed, skipped, items:[{sku, shop_id, ok, old, new, error}]}。"""
    cells = [(s.upper(), int(i)) for s, i in cells]
    data = data or compute([s for s, _ in cells])
    by = {(r["sku"], sid): (r, c) for r in data["rows"] for sid, c in r["cells"].items()}
    shp = {s["id"]: s for s in data["shops"]}
    st = data["settings"]
    out = {"pushed": 0, "failed": 0, "skipped": 0, "items": []}
    per_shop = {}
    for sku, sid in cells:
        hit = by.get((sku, sid))
        if not hit or sid not in shp:
            out["skipped"] += 1
            continue
        r, cell = hit
        shop = shp[sid]
        qty = override[(sku, sid)] if override and (sku, sid) in override else cell["target"]
        if not shop["api"]:
            out["skipped"] += 1
            continue
        if cell["locked"] and not (override and (sku, sid) in override) and reason not in ("lock",):
            out["skipped"] += 1
            continue
        if not force and cell["status"] == "synced" and not (override and (sku, sid) in override) and cell["last"] == qty:
            out["skipped"] += 1
            continue
        per_shop.setdefault(sid, []).append((sku, qty, cell))
    for sid, items in per_shop.items():
        shop = shp[sid]
        adapter = stockadapters.get(shop["platform"])
        try:
            res = adapter.push(shop, [{"sku": s, "qty": q} for s, q, _ in items])
        except Exception as e:  # noqa: BLE001
            res = {s: {"ok": False, "error": str(e)[:300]} for s, _, _ in items}
        now = time.time()
        for sku, qty, cell in items:
            rr = res.get(sku) or {"ok": False, "error": "平台没有返回结果"}
            if rr["ok"]:
                _set_state(sku, sid, pushed=qty, pushed_at=now, platform_qty=qty, platform_at=now, fails=0, error="", error_kind="", next_retry=None,
                           want=None)
                _log(sku, shop, cell["last"], qty, reason, True, "ok", user)
                out["pushed"] += 1
                out["items"].append({"sku": sku, "shop_id": sid, "ok": True, "old": cell["last"], "new": qty, "error": ""})
            else:
                kind, msg = stockadapters.classify_error(rr["error"])
                fails = (cell["fails"] or 0) + 1
                _set_state(sku, sid, fails=fails, error=msg, error_kind=kind, next_retry=now + min(3600, 300 * fails))
                _log(sku, shop, cell["last"], qty, reason, False, msg, user)
                out["failed"] += 1
                out["items"].append({"sku": sku, "shop_id": sid, "ok": False, "old": cell["last"], "new": qty, "error": msg})
    return out


def sync_pending(reason="timer", user="系统", skus=None, shop_ids=None, retry=True, data=None):
    """把待同步的单元格推出去。失败的按退避时间自动重试，次数用完不再自动试（出待办，手动重试）。"""
    data = data or compute(skus, shop_ids)
    st = data["settings"]
    now = time.time()
    todo = []
    for r in data["rows"]:
        for sid, c in r["cells"].items():
            if not c["api"] or c["locked"] or c["status"] not in ("pending", "failed"):
                continue
            if c["status"] == "failed":
                ss = _c().execute("SELECT next_retry FROM ss_state WHERE sku=? AND shop_id=?", (r["sku"], sid)).fetchone()
                if not retry or c["fails"] >= st["retry_max"] or (ss and ss["next_retry"] and ss["next_retry"] > now):
                    continue
            todo.append((r["sku"], sid))
    return push_cells(todo, reason, user, data=data)


def force_all(user="", reason="manual"):
    """一键全部重推：所有接口店铺的所有 SKU，不管有没有差异（锁定的不动）。"""
    data = compute()
    cells = [(r["sku"], sid) for r in data["rows"] for sid, c in r["cells"].items() if c["api"] and not c["locked"]]
    return push_cells(cells, reason, user, data=data, force=True)


# ---------------- 行内改 / 锁定 / 批量 ----------------
def edit_qty(sku, shop_id, qty, user="", lock=False):
    sku, sid = sku.upper(), int(shop_id)
    qty = int(qty)
    if qty < 0:
        raise ValueError("库存不能是负数")
    data = compute([sku])
    cell = next((r["cells"].get(sid) for r in data["rows"] if r["sku"] == sku), None)
    if cell is None:
        raise ValueError("这个 SKU 在这个店铺没有")
    if lock:
        _set_state(sku, sid, locked=qty)
    if cell["api"]:
        res = push_cells([(sku, sid)], "manual", user, data=data, override={(sku, sid): qty}, force=True)
        if res["failed"]:
            raise RuntimeError(res["items"][0]["error"])
        return res
    _set_state(sku, sid, want=qty)                                     # 没接口：记下要显示的数，出在待导出表里
    return {"pushed": 0, "failed": 0, "skipped": 1, "items": [], "export": True}


def set_lock(sku, shop_id, qty, user=""):
    """qty 有值 = 锁定在这个数（自动同步不会改）；None = 解锁。"""
    sku, sid = sku.upper(), int(shop_id)
    if qty is None:
        _set_state(sku, sid, locked=None)
        return {"locked": False}
    return {"locked": True, **edit_qty(sku, sid, qty, user, lock=True)}


def bulk(action, cells, params=None, user=""):
    """批量：push 推送 / recalc 按规则重算 / safety 设安全库存 / alloc 改分配 / zero 设 0（临时停售）/ resume 恢复 / lock / unlock / export 标记。
    cells = [{sku, shop_id}]（shop_id 空 = 这个 SKU 在所有店铺）。"""
    params = params or {}
    sk = sorted({c["sku"].upper() for c in cells})
    data = compute(sk)
    todo = []
    for r in data["rows"]:
        for sid in r["cells"]:
            if any(c["sku"].upper() == r["sku"] and (c.get("shop_id") in (None, "", sid) or int(c["shop_id"]) == sid) for c in cells):
                todo.append((r["sku"], sid))
    if action == "push":
        return push_cells(todo, "manual", user, data=data, force=True)
    if action == "recalc":
        for sku, sid in todo:
            _set_state(sku, sid, want=None, paused=0, locked=None)
        return sync_pending("manual", user, skus=sk, data=compute(sk))
    if action == "safety":
        for sku in {s for s, _ in todo}:
            set_rule("sku", sku, 0, {"safety": int(params.get("safety") or 0)}, user)
        return sync_pending("rule", user, skus=sk, data=compute(sk))
    if action == "alloc":
        for sku, sid in todo:
            set_rule("sku", sku, sid if params.get("per_shop") else 0,
                     {"alloc": params.get("alloc") or "share", "alloc_val": params.get("alloc_val")}, user)
        return sync_pending("rule", user, skus=sk, data=compute(sk))
    if action == "zero":
        for sku, sid in todo:
            _set_state(sku, sid, paused=1)
        return push_cells(todo, "manual", user, data=compute(sk), force=True)
    if action == "resume":
        for sku, sid in todo:
            _set_state(sku, sid, paused=0, want=None)
        return sync_pending("manual", user, skus=sk, data=compute(sk))
    if action == "lock":
        for sku, sid in todo:
            set_lock(sku, sid, int(params.get("qty") if params.get("qty") is not None else 0), user)
        return {"ok": True, "n": len(todo)}
    if action == "unlock":
        for sku, sid in todo:
            set_lock(sku, sid, None, user)
        return sync_pending("manual", user, skus=sk, data=compute(sk))
    raise ValueError("不认识的批量操作")


def retry_failed(user="", log_ids=None):
    """重试失败的：把失败的单元格按现在的目标数再推一次（手动重试会清掉失败次数）。"""
    data = compute()
    cells = []
    for r in data["rows"]:
        for sid, c in r["cells"].items():
            if c["status"] == "failed" and c["api"]:
                _set_state(r["sku"], sid, fails=0, next_retry=None)
                cells.append((r["sku"], sid))
    if log_ids:
        keep = {(x["sku"], x["shop_id"]) for x in _c().execute(f"SELECT sku, shop_id FROM ss_log WHERE id IN ({','.join('?' * len(log_ids))})", list(log_ids))}
        cells = [c for c in cells if c in keep]
    return push_cells(cells, "manual", user, data=compute([s for s, _ in cells]), force=True)


def on_rule_changed(skus, user=""):
    return sync_pending("rule", user, skus=list(skus))


# ---------------- 没接口的店铺：待导出 ----------------
def export_list(shop_id):
    data = compute()
    out = []
    for r in data["rows"]:
        c = r["cells"].get(int(shop_id))
        if c and not c["api"] and c["status"] in ("pending", "failed", "locked") and (c["last"] is None or c["target"] != c["last"]):
            out.append({"sku": r["sku"], "product_id": r["product_id"], "name": r["name"], "color": r["color"], "spec": r["spec"],
                        "qty": c["target"], "last": c["last"]})
    return out


def export_sheet(shop_id, skus=None):
    """生成导出表（xlsx：SKU、库存数）。返回 {file, rows}。"""
    import datetime as dt

    import openpyxl
    from web.common import EXPORT_DIR
    items = [x for x in export_list(shop_id) if not skus or x["sku"] in {s.upper() for s in skus}]
    shop = next((s for s in shops() if s["id"] == int(shop_id)), None)
    if not shop:
        raise ValueError("店铺不存在")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SKU", "Stock", "Product", "Variation"])
    for x in items:
        ws.append([x["sku"], x["qty"], x["name"], f"{x['color']} {x['spec']}".strip()])
    os.makedirs(EXPORT_DIR, exist_ok=True)
    name = f"stock_{shop['platform']}_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    wb.save(os.path.join(EXPORT_DIR, name))
    for x in items:
        _set_state(x["sku"], int(shop_id), export_qty=x["qty"])
    return {"file": name, "rows": len(items)}


def mark_uploaded(shop_id, skus=None, user=""):
    """导出表上传到平台后点「已上传」：把导出时的数记为已同步。"""
    sid = int(shop_id)
    shop = next((s for s in shops() if s["id"] == sid), None)
    if not shop:
        raise ValueError("店铺不存在")
    data = compute(skus)
    n = 0
    now = time.time()
    for r in data["rows"]:
        c = r["cells"].get(sid)
        if not c or (skus and r["sku"] not in {s.upper() for s in skus}):
            continue
        if c["last"] is not None and c["target"] == c["last"]:
            continue
        ss = _c().execute("SELECT export_qty FROM ss_state WHERE sku=? AND shop_id=?", (r["sku"], sid)).fetchone()
        qty = ss["export_qty"] if ss and ss["export_qty"] is not None else c["target"]
        _set_state(r["sku"], sid, pushed=qty, pushed_at=now, platform_qty=qty, platform_at=now, fails=0, error="", error_kind="",
                   want=None, export_qty=None)
        _log(r["sku"], shop, c["last"], qty, "manual", True, "已上传（导出表）", user)
        n += 1
    return {"marked": n}


# ---------------- 拉平台库存 ----------------
def pull_platform(shop_ids=None):
    """从接口店铺拉平台上实际显示的库存（发现卖家中心里手动改过的）。返回 {shop_id: {n, error}}。"""
    out = {}
    for s in shops():
        if not s["api"] or (shop_ids and s["id"] not in shop_ids):
            continue
        ad = stockadapters.get(s["platform"])
        try:
            got = ad.pull(s)
        except Exception as e:  # noqa: BLE001
            PULL_INFO[s["id"]] = {"at": time.time(), "error": str(e)[:200]}
            out[s["id"]] = {"n": 0, "error": str(e)[:200]}
            continue
        if got is None:
            continue
        now = time.time()
        for sku, d in got.items():
            _set_state(sku.upper(), s["id"], platform_qty=int(d.get("qty") or 0), platform_at=now, plat_status=d.get("status") or "")
        PULL_INFO[s["id"]] = {"at": now, "error": ""}
        out[s["id"]] = {"n": len(got), "error": ""}
    return out


def run_check(user="系统", pull=True):
    """定时检查：拉平台库存 → 对照 → 推待同步 / 重试失败。"""
    pulled = pull_platform() if pull else {}
    data = compute()
    touch_all(data)
    res = sync_pending("timer", user, data=data)
    return {"pulled": pulled, "pushed": res["pushed"], "failed": res["failed"]}


# ---------------- 事件 ----------------
def reason_kind(reason, delta=0):
    r = reason or ""
    if "出货" in r or "发货" in r or "出库" in r:
        return "ship"
    if "备货打印" in r or "多打" in r or "生产" in r or "打印完成" in r:
        return "produce"
    if "采购" in r or "入库" in r or "退" in r or delta > 0:
        return "in"
    return "manual"


def on_stock_changed(sku="", delta=0, reason="", **kw):
    """成品库存变化（core/production.stock_add 广播）→ 这个 SKU 标记待查，稍后（防抖）同步。"""
    if not sku or not settings()["event"]:
        return
    k = reason_kind(reason, delta)
    with _lock:
        _dirty.add(sku.upper())
        _dirty_reason[sku.upper()] = k
    if INLINE:
        process_dirty()
    elif _started:
        _kick()


def on_order_status(oid=None, **kw):
    """订单状态变化（占库存变了）：这个订单的 SKU 标记待查。"""
    try:
        skus = [r["sku"].upper() for r in _c().execute("SELECT sku FROM order_items WHERE order_id=?", (oid,)) if r["sku"]]
    except Exception:  # noqa: BLE001
        return
    if not skus or not settings()["event"]:
        return
    with _lock:
        for s in skus:
            _dirty.add(s)
            _dirty_reason.setdefault(s, "ship")
    if INLINE:
        process_dirty()
    elif _started:
        _kick()


def process_dirty():
    with _lock:
        skus, kinds = list(_dirty), dict(_dirty_reason)
        _dirty.clear()
        _dirty_reason.clear()
    if not skus:
        return {"pushed": 0, "failed": 0}
    reset_cache()
    out = {"pushed": 0, "failed": 0, "skipped": 0, "items": []}
    by = {}
    for s in skus:
        by.setdefault(kinds.get(s, "manual"), []).append(s)
    for kind, group in by.items():
        r = sync_pending(kind, "系统", skus=group, retry=False)
        for k in ("pushed", "failed", "skipped"):
            out[k] += r[k]
        out["items"] += r["items"]
    return out


def _kick():
    with _lock:
        if _timer["t"] and _timer["t"].is_alive():
            return

        def run():
            time.sleep(3)
            try:
                process_dirty()
            except Exception as e:  # noqa: BLE001
                from core import diag
                diag.log.warning("库存同步（事件）失败：%s", e)
        t = threading.Thread(target=run, daemon=True, name="stocksync-evt")
        _timer["t"] = t
        t.start()


# ---------------- 后台 ----------------
_started = False


def _loop():
    from core import diag
    last = 0
    while True:
        time.sleep(30)
        try:
            mins = settings()["interval"]
            if mins <= 0 or time.time() - last < mins * 60:
                continue
            last = time.time()
            run_check()
        except Exception as e:  # noqa: BLE001
            diag.log.warning("库存同步定时检查失败：%s", e)


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="stocksync").start()


# ---------------- 待办 ----------------
ROLES = "owner,listing"
ERR_TH = {"token": "โทเคนหมดอายุ ต้องอนุญาตร้านใหม่", "sku": "ไม่พบ SKU บนแพลตฟอร์ม", "net": "เครือข่ายหมดเวลา", "other": "แพลตฟอร์มปฏิเสธ"}


def todo_provide(add):
    """今日待办（MODULE["todo"]）：同步失败（重试用完）、对不上、快卖完、超卖、超过 1 天没同步。"""
    data = compute()
    st = data["settings"]
    shp = {s["id"]: s for s in data["shops"]}
    for r in data["rows"]:
        sku, nm = r["sku"], f"{r['product_id']} {r['name']}".strip()
        for sid, c in r["cells"].items():
            sh = shp[sid]["name"]
            if c["status"] == "failed" and c["fails"] >= st["retry_max"]:
                add(f"ss:fail:{sku}:{sid}:{c['fails']}", "商品", "bad", f"库存同步失败：{sku} → {sh}", f"{c['error']}（已自动重试 {c['fails']} 次）",
                    "export", ROLES, th=(f"ซิงก์สต็อกไม่สำเร็จ: {sku} → {sh}", f"{ERR_TH.get(c['error_kind'], ERR_TH['other'])} (ลองใหม่อัตโนมัติ {c['fails']} ครั้ง)"))
            if c["mismatch"] and not (c["status"] == "failed" and c["fails"] >= st["retry_max"]):
                add(f"ss:mis:{sku}:{sid}:{c['platform']}", "商品", "warn", f"库存对不上：{sku} @ {sh}",
                    f"系统 {c['last'] if c['last'] is not None else c['target']}，平台显示 {c['platform']}（可能在卖家中心手动改过）", "export", ROLES,
                    th=(f"สต็อกไม่ตรง: {sku} @ {sh}", f"ระบบ {c['last'] if c['last'] is not None else c['target']} แพลตฟอร์มแสดง {c['platform']}"))
            if c["stale"]:
                add(f"ss:stale:{sku}:{sid}", "商品", "warn", f"超过 {st['unsynced_hours']:g} 小时没同步：{sku} → {sh}", "待同步的库存一直没推出去 / 没上传", "export", ROLES,
                    th=(f"เกิน {st['unsynced_hours']:g} ชม. ยังไม่ซิงก์: {sku} → {sh}", "สต็อกที่รอซิงก์ยังไม่ถูกส่ง / อัปโหลด"))
        if r["oversold"]:
            add(f"ss:over:{sku}:{r['open_orders']}", "商品", "bad", f"已超卖：{sku}",
                f"待发货 {r['open_orders']} 件，库存 {r['on_hand']}、耗材还够做 {r['units'] or 0} 件。建议：紧急排产 / 修正库存 / 联系买家", "export", ROLES,
                th=(f"ขายเกินสต็อก: {sku}", f"รอส่ง {r['open_orders']} ชิ้น สต็อก {r['on_hand']} ผลิตได้อีก {r['units'] or 0} ชิ้น แนะนำ: เร่งผลิต / แก้สต็อก / ติดต่อผู้ซื้อ"))
        elif r["low"] and r["sold30"] > 0:
            cov = f"，按近期销量只够 {r['cover_days']} 天" if r["cover_days"] is not None else ""
            add(f"ss:low:{sku}:{r['sellable']}", "商品", "warn", f"快卖完：{sku}（可售 {r['sellable']}）", f"{nm}{cov}", "export", ROLES,
                th=(f"ใกล้หมด: {sku} (ขายได้ {r['sellable']})", nm))
