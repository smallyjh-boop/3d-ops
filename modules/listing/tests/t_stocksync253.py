# v2.53：库存同步——可售公式、安全库存、多店铺分配、按需打印虚拟库存、库存变化触发、锁定、行内改、批量、
# 失败重试再报警、对不上（拉平台库存）、超卖、同步记录和重试、没接口店铺的导出、商品 360 记录块、适配器切换。全部用假 HTTP。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, time
D = T + "/m_stocksync"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, integrations, stockcalc, production, todo, config, orders as orders_mod
from core.connectors import lazada as LZ
from modules.listing import stocksync as S, stockadapters as AD
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
S.init()
PID = "3DP0015"
sid = integrations.save_shop({"platform": "lazada", "name": "LZ1", "enabled": True,
                              "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})
p = store.load(PID)
skus = [v["sku"] for v in p["variants"]]
K, K2 = skus[0], skus[1]
p["exported_at"] = int(time.time()) - 1000
p["shopee_exported_at"] = int(time.time()) - 900
p["listing"] = {"lazada": {"status": "live"}, "shopee": {"status": "live"}}
p["stock_auto"] = True
store.save(p)
cfg0 = config.load_config(); cfg0["ss_auto_push"] = True; config.save_config(cfg0)      # 自动推送总开关（默认关，测试里开）

# ---- 假 Lazada ----
PLAT = {s: 5 for s in skus}            # 平台上现在显示的库存
calls, FAIL = [], {"on": False, "msg": "IllegalAccessToken: token expired"}


def prod(item, sku_list):
    return {"item_id": item, "status": "Active", "attributes": {"name": "x"}, "primary_category": "1", "images": "[]",
            "created_time": "1793000000000", "updated_time": "1793100000000",
            "skus": [{"SellerSku": s, "SkuId": 9000 + i, "price": 99, "quantity": PLAT[s], "Status": "active"} for i, s in enumerate(sku_list)]}


def fake(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    if path == "/products/get":
        return {"code": "0", "data": {"total_products": "1", "products": [prod("111", skus)]}}
    if path == "/product/price_quantity/update":
        if FAIL["on"]:
            raise RuntimeError(FAIL["msg"])
        for s in json.loads(params["payload"])["Request"]["Product"]["Skus"]["Sku"]:
            calls.append((s["SellerSku"], int(s["Quantity"])))
            PLAT[s["SellerSku"]] = int(s["Quantity"])
    return {"code": "0", "data": {}}


LZ.LazadaConnector._call = fake
RES = {}
production.reserved = lambda sku, c=None: RES.get(sku.upper(), 0)
S.INLINE = True


def fresh():
    S.reset_cache(); return S.compute()


def cell(sku, shop=sid, data=None):
    d = data or fresh()
    return next(r for r in d["rows"] if r["sku"] == sku)["cells"][shop]


def last_push(sku):
    return [q for s, q in calls if s == sku][-1] if any(s == sku for s, _ in calls) else None


C.post("/api/online/sync", json={})                       # 拉在线商品：记下平台编号 / sku_id
d = fresh()
ok({sid, -1} <= {s["id"] for s in d["shops"]} and any(s["id"] == sid and s["api"] for s in d["shops"]) and any(s["id"] == -1 and not s["api"] for s in d["shops"]),
   "shops: Lazada has API, Shopee (virtual) has none")
ok(any(r["sku"] == K for r in d["rows"]), "SKU rows appear")

# ---- 可售公式 + 安全库存 ----
production.stock_add(K, 10, "备货打印", "t")                # INLINE：同时触发一次同步
S.INLINE = False
c = cell(K)
ok(c["computed"] == 10 and c["target"] == 10, f"sellable = on hand {c}")
RES[K] = 3
ok(cell(K)["computed"] == 7, "minus reserved by orders: 10-3=7")
S.set_rule("sku", K, 0, {"safety": 2})
ok(cell(K)["computed"] == 5, "minus per-SKU safety stock: 10-3-2=5")
cfg = config.load_config(); cfg["ss_safety"] = 1; config.save_config(cfg)
S.set_rule("sku", K, 0, {"safety": None})
ok(cell(K)["computed"] == 6, "global default safety 1 applies when no rule: 6")
S.set_rule("product", PID, sid, {"safety": 4})
ok(cell(K)["computed"] == 3 and cell(K2)["computed"] != cell(K)["computed"] or cell(K)["computed"] == 3, "product+shop override beats global")
S.set_rule("product", PID, sid, {"safety": None}); cfg["ss_safety"] = 0; config.save_config(cfg)
RES.clear()
ok(cell(K)["computed"] == 10, "back to 10")

# ---- 分配 ----
S.set_rule("sku", K, sid, {"alloc": "fixed", "alloc_val": 4})
S.set_rule("sku", K, -1, {"alloc": "percent", "alloc_val": 50})
d = fresh()
ok(cell(K, sid, d)["computed"] == 4 and cell(K, -1, d)["computed"] == 5, f"fixed 4 / percent 50% of 10 = {cell(K, sid, d)['computed']}/{cell(K, -1, d)['computed']}")
S.set_rule("sku", K, sid, {"alloc": "fixed", "alloc_val": 99})
ok(cell(K, sid)["computed"] == 10, "fixed never exceeds sellable")
S.set_rule("sku", K, sid, {"alloc": None, "alloc_val": None}); S.set_rule("sku", K, -1, {"alloc": None, "alloc_val": None})
ok(cell(K, sid)["computed"] == 10 and cell(K, -1)["computed"] == 10, "share: every shop shows all")

# ---- 按需打印虚拟库存（耗材够做几件，上限，不够掉 0）----
production.stock_set(K2, 0, user="t") if production.stock_qty(K2) else None
v2 = next(v for v in store.load(PID)["variants"] if v["sku"] == K2)
pp = store.load(PID); pp["material"] = "PLA"
for v in pp["variants"]:
    if v["sku"] == K2:
        v["grams"] = 20
store.save(pp)
col = v2.get("opt1_zh")
key = ("PLA", stockcalc._ckey(config.load_config(), col))
AV = {key: 410.0}
stockcalc.available = lambda cfg=None, fresh=True: AV
S.reset_cache()
S.set_rule("product", PID, 0, {"virtual": "off"})          # 产品是自动库存：这里先把虚拟库存关掉，下面按 SKU 开
cc = cell(K2)
ok(cc["virt"] == 0, "virtual stock is off unless enabled")
S.set_rule("sku", K2, 0, {"virtual": "on", "cap": 20})
cc = cell(K2)
ok(cc["virt"] == 18 and cc["computed"] == cc["phys"] + 18, f"virtual = floor(410g / (20g*1.1)) = 18 (got {cc['virt']})")
S.set_rule("sku", K2, 0, {"cap": 10})
ok(cell(K2)["virt"] == 10, "virtual capped at 10")
cfg = config.load_config(); cfg["printers"] = [{"name": "A"}, {"name": "B"}]; cfg["ss_printer_units"] = 3; config.save_config(cfg)
ok(cell(K2)["virt"] == 6, "virtual limited by printer capacity (2 printers x 3)")
cfg["ss_printer_units"] = 0; config.save_config(cfg)
AV[key] = 15.0
ok(cell(K2)["virt"] == 0, "materials not enough -> virtual drops to 0")
AV[key] = 410.0
S.set_rule("sku", K2, 0, {"virtual": "off"})
ok(cell(K2)["virt"] == 0, "virtual switched off per SKU")
S.set_rule("sku", K2, 0, {"virtual": None, "cap": None})

# ---- 触发：库存变化事件 → 推到 Lazada + 同步记录 ----
S.sync_pending("timer", "t")
S.INLINE = True
calls.clear()
production.stock_add(K, 3, "备货打印 任务#9", "t")
ok(last_push(K) == 13 and cell(K)["status"] == "synced", f"stock change event pushed 13 ({calls})")
lg = S.log_list(sku=K)
ok(lg[0]["reason"] == "produce" and lg[0]["new"] == 13 and lg[0]["ok"] == 1 and lg[0]["old"] == 10, f"log: from 10 to 13 reason produce {lg[0]}")
production.stock_add(K, -2, "订单出货 任务#1", "t")
ok(last_push(K) == 11 and S.log_list(sku=K)[0]["reason"] == "ship", "ship reason, pushed 11")
production.stock_add(K, 4, "采购入库", "t")
ok(last_push(K) == 15 and S.log_list(sku=K)[0]["reason"] == "in", "purchase in -> reason in")
S.INLINE = False
production.stock_add(K, 1, "备货打印", "t")                 # INLINE 关：只标记，等 process_dirty
n0 = len(calls)
ok(len(calls) == n0 and K in S._dirty, "event only marks dirty when not inline")
S.process_dirty()
ok(last_push(K) == 16, "process_dirty pushes the change")
# 定时检查
production.stock_add(K, 1, "盘点", "t")
S._dirty.clear()
r = S.run_check("t")
ok(last_push(K) == 17 and S.log_list(sku=K)[0]["reason"] == "timer", f"periodic check pushes missed change {r}")

# ---- 复审：防抖期间关了自动推送 → 什么都不推；事件触发的批次不记成「手动」
S.INLINE = False
production.stock_add(K, -1, "盘点", "t")                     # 手动类原因 -> 事件批次
ok(K in S._dirty and S._dirty_reason.get(K) == "event", f"event batch is not 'manual' {S._dirty_reason.get(K)}")
config.save_config({"ss_auto_push": False})
before = last_push(K); n_calls = len(calls)
r = S.process_dirty()
ok(last_push(K) == before and len(calls) == n_calls and r.get("auto_off"), "switch turned off during debounce -> nothing pushed")
config.save_config({"ss_auto_push": True})
production.stock_add(K, -1, "盘点", "t")
S.process_dirty()
ok(S.log_list(sku=K)[0]["reason"] == "event", f"event push is logged as event, not manual: {S.log_list(sku=K)[0]['reason']}")
production.stock_add(K, 2, "盘点", "t"); S.process_dirty()          # 数量还原
# 基线：第一次拉到平台数写了 pushed_at；自动推送关着时不报「超过 1 天没同步」
_c_ = S._c()
_c_.execute("DELETE FROM ss_state WHERE sku=? AND shop_id=?", (K, sid)); _c_.commit()
S.pull_platform()
ok(_c_.execute("SELECT pushed_at FROM ss_state WHERE sku=? AND shop_id=?", (K, sid)).fetchone()[0], "baseline from the first pull sets pushed_at too")
_c_.execute("UPDATE ss_state SET first_seen=? WHERE sku=? AND shop_id=?", (time.time() - 3 * 86400, K, sid)); _c_.commit()
config.save_config({"ss_auto_push": False})
ok(not cell(K)["stale"], "auto push off -> never 'stale'")
config.save_config({"ss_auto_push": True})
S.sync_pending("timer", "t")

# ---- 锁定：自动同步不覆盖 ----
S.set_lock(K, sid, 3, "t")
ok(last_push(K) == 3 and cell(K)["status"] == "locked" and cell(K)["target"] == 3, "lock pushes the number and shows 已锁定")
S.INLINE = True
production.stock_add(K, 5, "备货打印", "t")
ok(last_push(K) == 3 and cell(K)["target"] == 3, "auto sync does not overwrite a locked number")
S.run_check("t")
ok(last_push(K) == 3, "periodic check does not overwrite either")
S.set_lock(K, sid, None, "t")
ok(cell(K)["status"] in ("pending", "synced") and cell(K)["target"] == 22, f"unlock goes back to computed ({cell(K)['target']})")
S.sync_pending("manual", "t")
ok(last_push(K) == 22, "unlock + sync pushes computed")
S.INLINE = False

# ---- 行内改（API）----
r = C.post("/api/stocksync/edit", json={"sku": K, "shop_id": sid, "qty": 8}).get_json()
ok(r["ok"] and last_push(K) == 8 and S.log_list(sku=K)[0]["reason"] == "manual", f"inline edit pushes 8 {r}")
r = C.post("/api/stocksync/edit", json={"sku": K, "shop_id": sid, "qty": -1})
ok(r.status_code == 400, "negative rejected")
r = C.post("/api/stocksync/edit", json={"sku": K, "shop_id": -1, "qty": 6}).get_json()
ok(r["ok"] and r.get("export") and cell(K, -1)["target"] == 6, "inline edit on a no-API shop records it for export")
S.bulk("recalc", [{"sku": K, "shop_id": None}], user="t")
ok(cell(K, -1)["target"] == 22 and last_push(K) == 22, "recalc by rule clears manual overrides")

# ---- 批量 ----
b = lambda a, **pr: C.post("/api/stocksync/bulk", json={"action": a, "cells": [{"sku": K, "shop_id": sid}, {"sku": K2, "shop_id": sid}], "params": pr}).get_json()
calls.clear()
r = b("push")
ok(r["ok"] and {s for s, _ in calls} >= {K, K2}, f"bulk push {r['pushed']}")
r = b("zero")
ok(last_push(K) == 0 and last_push(K2) == 0 and cell(K)["paused"], "bulk zero = temporary stop selling")
S.INLINE = True
production.stock_add(K, 1, "备货打印", "t")
ok(last_push(K) == 0, "paused SKU stays 0 on stock change")
S.INLINE = False
b("resume")
ok(not cell(K)["paused"] and last_push(K) == cell(K)["computed"], "bulk resume restores")
b("safety", safety=5)
ok(last_push(K) == cell(K)["computed"] and S.get_rule("sku", K)["safety"] == 5, "bulk safety stock")
b("safety", safety=0)
b("alloc", alloc="fixed", alloc_val=2, per_shop=False)
ok(last_push(K) == 2, "bulk allocation fixed 2")
b("alloc", alloc="share")
b("lock", qty=1)
ok(cell(K)["locked"] and last_push(K) == 1, "bulk lock")
b("unlock")
ok(not cell(K)["locked"], "bulk unlock")
calls.clear()
r = C.post("/api/stocksync/push-all", json={}).get_json()
ok(r["ok"] and len(calls) >= len(skus), f"push everything again ({len(calls)})")

# ---- 失败 → 自动重试 → 报警 ----
S.INLINE = True
FAIL["on"] = True
production.stock_add(K, 2, "备货打印", "t")
c = cell(K)
ok(c["status"] == "failed" and c["fails"] == 1 and "token" in c["error"] and c["error_kind"] == "token", f"failure recorded with reason {c['status']} {c['error']}")
ok(not S.log_list(sku=K)[0]["ok"] and "token" in S.log_list(sku=K)[0]["result"], "failure in log")
S.INLINE = False
items = []
todo.init()
add = lambda *a, **k: items.append((a, k))
S.todo_provide(lambda *a, **k: items.append(a))
ok(not any(a[0].startswith("ss:fail") for a in items), "no alert yet while auto retry is still allowed")
for i in range(2):
    _c = db.conn(); _c.execute("UPDATE ss_state SET next_retry=? WHERE sku=?", (time.time() - 1, K)); _c.commit()
    S.sync_pending("timer", "t")
c = cell(K)
ok(c["fails"] == 3 and c["status"] == "failed", f"auto retried up to the limit: fails={c['fails']}")
items.clear(); S.todo_provide(lambda *a, **k: items.append((a, k)))
al = [a for a, k in items if a[0].startswith("ss:fail")]
ok(al and al[0][2] == "bad" and "Lazada" not in al[0][3] or al, f"alert raised in red after retries {al[:1]}")
ok(al and al[0][3] and "token" in al[0][4] and any("th" in k for a, k in items if a[0].startswith("ss:fail")), "alert has reason and Thai text")
_c = db.conn(); _c.execute("UPDATE ss_state SET next_retry=? WHERE sku=?", (time.time() - 1, K)); _c.commit()
n = len(S.log_list(sku=K))
S.sync_pending("timer", "t")
ok(len(S.log_list(sku=K)) == n, "no more auto retries after the limit")
FAIL["on"] = False
r = C.post("/api/stocksync/retry", json={}).get_json()
ok(r["pushed"] >= 1 and cell(K)["status"] == "synced", f"manual retry of failed works {r['pushed']}")
items.clear(); S.todo_provide(lambda *a, **k: items.append(a))
ok(not any(a[0].startswith("ss:fail") for a in items), "alert gone after success")
FAIL.update(on=True, msg="SKU not found")
S.edit_qty(K2, sid, 3, "t") if False else None
try:
    S.edit_qty(K2, sid, 3, "t")
except RuntimeError as e:
    ok("找不到" in str(e), f"sku-not-found classified: {e}")
FAIL["on"] = False
S.retry_failed("t")

# ---- 对不上：拉平台库存发现手动改过 ----
S.sync_pending("manual", "t")
PLAT[K] = 99                                                # 卖家中心手动改了
r = S.run_check("t")
c = cell(K)
ok(c["platform"] == 99 and c["mismatch"] and c["diff"] == 99 - c["target"], f"mismatch detected from pulled stock {c['platform']} vs {c['target']}")
ok(fresh()["kpi"]["mismatch"] >= 1, "KPI counts mismatch")
items.clear(); S.todo_provide(lambda *a, **k: items.append(a))
ok(any(a[0].startswith("ss:mis") for a in items), "mismatch alert")
m = C.get("/api/stocksync/matrix?kpi=mismatch").get_json()
ok([r["sku"] for r in m["rows"]] == [K], "KPI click filter: mismatch")
PLAT[K] = c["target"]; S.pull_platform()
ok(not cell(K)["mismatch"], "mismatch clears when platform equals system again")
# 平台已下架
_c = db.conn(); _c.execute("UPDATE online_items SET status='inactive'"); _c.commit()
ok(cell(K)["status"] == "delisted", "platform delisted status")
_c.execute("UPDATE online_items SET status='active'"); _c.commit()
C.post("/api/online/sync", json={})

# ---- 超卖 + 快卖完 ----
orders_mod.upsert([{"platform": "lazada", "order_no": "OS1", "status": "to_ship", "items": [{"sku": K2, "qty": 500}]}], source="test")
AV[key] = 30.0
S.set_rule("sku", K2, 0, {"virtual": None})
d = fresh()
r2 = next(r for r in d["rows"] if r["sku"] == K2)
ok(r2["oversold"] and d["kpi"]["oversold"] >= 1, "oversold: open orders exceed stock + makeable")
items.clear(); S.todo_provide(lambda *a, **k: items.append((a, k)))
ov = [a for a, k in items if a[0].startswith("ss:over")]
ok(ov and ov[0][2] == "bad" and "紧急排产" in ov[0][4], "oversold alert is red with suggestions")
ok(any(r["sku"] == K2 for r in C.get("/api/stocksync/matrix?kpi=oversold").get_json()["rows"]), "KPI filter oversold")
orders_mod.upsert([{"platform": "lazada", "order_no": "OS1", "status": "cancelled", "items": [{"sku": K2, "qty": 500}]}], source="test")
orders_mod.upsert([{"platform": "lazada", "order_no": "LW1", "status": "shipped", "order_time": time.time() - 86400, "items": [{"sku": K2, "qty": 30}]}], source="test")
production.stock_set(K2, 1, user="t")
d = fresh(); r2 = next(r for r in d["rows"] if r["sku"] == K2)
ok(r2["low"] and not r2["oversold"] and r2["cover_days"] is not None, f"low stock by days of cover {r2['cover_days']}")
items.clear(); S.todo_provide(lambda *a, **k: items.append(a))
ok(any(a[0].startswith("ss:low") for a in items), "low-stock alert")

# ---- 超过 1 天没同步 ----
_c = db.conn(); _c.execute("UPDATE ss_state SET pushed=999 WHERE sku=? AND shop_id=?", (K2, sid)); _c.execute("UPDATE ss_state SET pushed_at=? WHERE sku=? AND shop_id=?", (time.time() - 3 * 86400, K2, sid)); _c.commit()
items.clear(); S.todo_provide(lambda *a, **k: items.append(a))
ok(any(a[0].startswith("ss:stale") for a in items), "not synced for over a day -> alert")
S.sync_pending("manual", "t")

# ---- 同步记录 API + 重试 ----
lg = C.get("/api/stocksync/log?reason=produce").get_json()["items"]
ok(lg and all(x["reason"] == "produce" for x in lg), "log filter by reason")
ok(all(not x["ok"] for x in C.get("/api/stocksync/log?result=fail").get_json()["items"]) and C.get("/api/stocksync/log?result=fail").get_json()["items"], "log filter failed only")
ok(all(x["sku"] == K for x in C.get(f"/api/stocksync/log?sku={K}").get_json()["items"]), "log filter by SKU")

# ---- 没接口的店铺：待导出 → 导出表 → 已上传 ----
ex = C.get("/api/stocksync/export-list?shop=-1").get_json()["items"]
ok({K, K2} <= {x["sku"] for x in ex} and all(x["qty"] >= 0 for x in ex), f"Shopee export list has {len(ex)} SKUs")
fx = C.post("/api/stocksync/export", json={"shop_id": -1}).get_json()
import openpyxl
wb = openpyxl.load_workbook(os.path.join(D, "exports", fx["file"]))
rows = list(wb.active.values)
ok(rows[0][:2] == ("SKU", "Stock") and len(rows) - 1 == fx["rows"] == len(ex), f"export sheet {fx}")
want = {r[0]: r[1] for r in rows[1:]}
production.stock_add(K, 1, "备货打印", "t")             # 导出后库存又变了：「已上传」记的是导出表里的数
r = C.post("/api/stocksync/uploaded", json={"shop_id": -1}).get_json()
ok(r["marked"] == len(ex) and cell(K, -1)["last"] == want[K], f"marked uploaded with exported numbers {r}")
ok(cell(K, -1)["status"] == "pending" and any(x["sku"] == K for x in S.export_list(-1)), "stock changed after export -> back in export list")
ok(any(x["reason"] == "manual" and x["shop"] == "Shopee" for x in S.log_list(sku=K)), "upload recorded in log")

# ---- 适配器：Shopee 接口通了以后自动改成直接推送 ----
class FakeShopee(AD.StockAdapter):
    platform = "shopee"; got = []
    def api_ready(self, shop): return True
    def push(self, shop, items): FakeShopee.got += items; return {i["sku"]: {"ok": True, "error": ""} for i in items}
    def pull(self, shop): return {}
AD.register("shopee", FakeShopee())
S.reset_cache()
ok(next(s for s in S.compute()["shops"] if s["id"] == -1)["api"], "adapter registered -> shop becomes API shop")
S.sync_pending("manual", "t")
ok(FakeShopee.got and cell(K, -1)["status"] == "synced", "pending cells now pushed through the new adapter")
AD._REG.pop("shopee")

# ================= v2.53 发版前审查的修复 =================
from modules.listing import lazada_push as LP
_saved = [dict(r) for r in db.conn().execute("SELECT * FROM ss_state")]
def _restore_state():
    _c2 = db.conn(); _c2.execute("DELETE FROM ss_state")
    for r_ in _saved:
        _c2.execute("INSERT INTO ss_state(" + ",".join(r_) + ") VALUES(" + ",".join("?" * len(r_)) + ")", list(r_.values()))
    _c2.commit()
def _set_cfg(**kw):
    c_ = config.load_config(); c_.update(kw); config.save_config(c_)

# ---- 1a 升级：ss_state 为空 + 自动推送默认关 → 什么都不推，对照表照样拉平台数 ----
_c2 = db.conn(); _c2.execute("DELETE FROM ss_state"); _c2.commit()
ok(S.settings({"x": 1})["auto"] is False and S.settings({"x": 1})["cap"] == 50, "upgrade default (no ss_* keys): auto push OFF, cap 50")
_set_cfg(ss_auto_push=False)
ok(not S.auto_enabled(), "auto push switch off")
S.INLINE = True
calls.clear()
production.stock_add(K, 1, "备货打印", "t")                 # 事件：自动推送关着，不推
ok(not calls, f"stock event pushes nothing while auto push is off ({calls[:3]})")
S.INLINE = False
PLAT.update({sk: 7 for sk in skus})
r = S.run_check("系统")
ok(not calls and r["pushed"] == 0 and r["auto"] is False, f"timer check with empty state pushes nothing ({calls[:3]})")
ok(cell(K)["platform"] == 7, "matrix still pulls the platform quantity while auto is off")
# ---- 1b 第一次基线：拉回来的平台数记为上次推的数 ----
_row = db.conn().execute("SELECT pushed, platform_qty FROM ss_state WHERE sku=? AND shop_id=?", (K, sid)).fetchone()
ok(_row["pushed"] == 7 and _row["platform_qty"] == 7 and cell(K)["last"] == 7, "baseline: pulled platform qty recorded as last pushed")
mx = C.get("/api/stocksync/matrix").get_json()
ok(mx["settings"]["auto"] is False, "matrix API tells the UI auto push is off (banner)")
n0 = len(calls)
r = C.post("/api/stocksync/rules", json={"scope": "shop", "key": "", "shop_id": sid, "data": {"safety": 1}}).get_json()
ok(len(calls) == n0 and r["sync"]["pushed"] == 0, "shop-wide rule change does not push while auto push is off")
S.set_rule("shop", "", sid, {"safety": None})
# 数字没变的 SKU：基线=目标，开了自动推送也不推
_c2 = db.conn()
for sk in skus:
    _t = cell(sk)["target"]; _c2.execute("UPDATE ss_state SET pushed=?, platform_qty=? WHERE sku=? AND shop_id=?", (_t, _t, sk, sid)); PLAT[sk] = _t
_c2.commit()
_set_cfg(ss_auto_push=True)
calls.clear()
r = S.run_check("系统")
ok(not calls and r["auto"], f"auto on + nothing changed -> still nothing pushed ({calls[:3]})")
S.INLINE = True
production.stock_add(K, 2, "备货打印", "t")
ok(calls and last_push(K) == cell(K)["target"], "auto on: an actual change is pushed")
S.INLINE = False
_restore_state()

# ---- 1c 没开自动库存的变体：沿用旧引擎的数（手填 / 默认库存），不是实物库存 ----
pp = store.load(PID); pp["stock_auto"] = False
for v in pp["variants"]:
    if v["sku"] == K: v["stock"] = 12
    if v["sku"] == K2: v.pop("stock", None)
store.save(pp); S.reset_cache()
_set_cfg(default_stock=50)
ok(cell(K)["computed"] == 12 and cell(K)["target"] == 12, f"non-auto variant keeps its hand-filled stock 12, not goods stock ({cell(K)['computed']})")
ok(cell(K2)["computed"] == 50, f"non-auto variant without a number uses default_stock 50 ({cell(K2)['computed']})")
ok(not next(r for r in fresh()["rows"] if r["sku"] == K2)["oversold"], "made-to-order product is never flagged oversold from goods stock")
pp = store.load(PID); pp["stock_auto"] = True
for v in pp["variants"]:
    v.pop("stock", None)
store.save(pp); S.reset_cache()
c_ = config.load_config(); c_.pop("ss_cap", None); c_["stock_cap"] = 50; config.save_config(c_)
ok(S.settings()["cap"] == 50, "upgrade default cap follows old stock_cap (50)")
_set_cfg(ss_cap="20"); ok(S.settings()["cap"] == 20, "explicit ss_cap wins")
c_ = config.load_config(); c_.pop("ss_cap", None); config.save_config(c_)

# ---- 2 新旧引擎：新的开了，旧循环不推；新的关，保持旧行为 ----
_old = {"n": 0}
_orig_ss = LP.sync_stock
LP.sync_stock = lambda user="", how="api": (_old.__setitem__("n", _old["n"] + 1) or {"synced": 0, "skipped": 0, "failed": []})
_set_cfg(ss_auto_push=True)
ok(LP._auto_stock_sync() is None and _old["n"] == 0, "new engine on -> old lazada loop does not push")
_set_cfg(ss_auto_push=False)
ok(LP._auto_stock_sync() is not None and _old["n"] == 1, "new engine off -> old loop behaves as before")
LP.sync_stock = _orig_ss
_set_cfg(ss_auto_push=True)

# ---- 3 只给 SKU 真在的店铺建单元格；编号按店铺分开 ----
sid2 = integrations.save_shop({"platform": "lazada", "name": "LZ2", "enabled": True,
                               "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})
pp = store.load(PID)
pp["lazada_api"] = {"item_id": "111", "skus": {K: "9000", K2: "9001"}}
store.save(pp); S.reset_cache()
d = fresh()
ok(sid2 in {s_["id"] for s_ in d["shops"]}, "second Lazada shop exists")
ok(all(sid2 not in r["cells"] for r in d["rows"]), "no cells for a Lazada shop where the SKU is not online (even if exported to Lazada)")
ok(all(sid in r["cells"] for r in d["rows"] if r["sku"] in (K, K2)), "main shop keeps its cells")
pp = store.load(PID); pp["lazada_api_shops"] = {str(sid2): {"item_id": "222", "skus": {K: "8000"}}}; store.save(pp); S.reset_cache()
d = fresh()
ok(sid2 in next(r for r in d["rows"] if r["sku"] == K)["cells"] and sid2 not in next(r for r in d["rows"] if r["sku"] == K2)["cells"],
   "second shop gets a cell only for the SKU recorded in lazada_api_shops[shop]")
pp = store.load(PID)
ok(AD.product_ids(pp, sid)[K] == ("111", "9000") and AD.product_ids(pp, sid2)[K] == ("222", "8000"), "ids are per shop_id")
ok(K2 not in AD.product_ids(pp, sid2) and AD.product_ids(pp, 9999) == {}, "no fallback to the main shop's ids for another shop")
_c2 = db.conn(); _c2.execute("DELETE FROM online_items WHERE shop_id=?", (sid,)); _c2.commit()      # 主店铺在线表没有 → 用 p["lazada_api"]
calls.clear()
_shp2 = next(s_ for s_ in d["shops"] if s_["id"] == sid2)
res = AD.get("lazada").push(_shp2, [{"sku": K2, "qty": 3}])
ok(not res[K2]["ok"] and not calls, "pushing a SKU the 2nd shop does not have fails locally with no API call (no main-shop id fallback)")
res = AD.get("lazada").push(next(s_ for s_ in d["shops"] if s_["id"] == sid), [{"sku": K2, "qty": 3}])
ok(res[K2]["ok"] and (K2, 3) in calls, "main shop still falls back to its own recorded ids")
_c2 = db.conn(); _c2.execute("DELETE FROM shops WHERE id=?", (sid2,)); _c2.execute("DELETE FROM online_items WHERE shop_id=?", (sid2,))
_c2.execute("DELETE FROM ss_state WHERE shop_id=?", (sid2,)); _c2.commit()
pp = store.load(PID); pp.pop("lazada_api_shops", None); pp.pop("lazada_api", None); store.save(pp); S.reset_cache()
C.post("/api/online/sync", json={"shop_id": sid})

# ---- 4 批量锁定必须给数量 ----
for badp, why in (({}, "missing"), ({"qty": ""}, "empty"), ({"qty": "abc"}, "non-numeric"), ({"qty": -2}, "negative")):
    n0 = len(calls)
    r = C.post("/api/stocksync/bulk", json={"action": "lock", "cells": [{"sku": K, "shop_id": sid}], "params": badp})
    ok(r.status_code == 400 and len(calls) == n0 and not cell(K)["locked"], f"bulk lock with {why} qty is rejected, nothing pushed/locked")
r = C.post("/api/stocksync/bulk", json={"action": "lock", "cells": [{"sku": K, "shop_id": sid}], "params": {"qty": 0}})
ok(r.status_code == 200 and cell(K)["locked"] and last_push(K) == 0, "an explicit 0 is a valid lock")
S.set_lock(K, sid, None, "t"); S.sync_pending("manual", "t")
_ui = open(os.path.join(APP, "modules/listing/ui/stocksync.js"), encoding="utf-8").read()
ok("params.qty = +v" in _ui and "请填写要锁定的件数" in _ui and 'ล็อกไว้ที่ (ชิ้น)"), "")' in _ui, "UI validates the bulk-lock quantity")

# ---- 5 锁定的推送失败：不写锁定，之后还会重试 ----
FAIL.update(on=True, msg="timeout while connecting")
try:
    S.edit_qty(K, sid, 4, "t", lock=True); _raised = False
except RuntimeError:
    _raised = True
c = cell(K)
ok(_raised and not c["locked"] and c["status"] == "failed", f"lock + failed push -> not locked, shows failed ({c['status']})")
FAIL["on"] = False
_c2 = db.conn(); _c2.execute("UPDATE ss_state SET next_retry=NULL WHERE sku=?", (K,)); _c2.commit()
S.sync_pending("timer", "t")
ok(cell(K)["status"] == "synced" and not cell(K)["locked"], "retried afterwards with the computed number")
S.edit_qty(K, sid, 4, "t", lock=True)
ok(cell(K)["locked"] and cell(K)["target"] == 4 and last_push(K) == 4, "lock written after the push succeeds")
S.set_lock(K, sid, None, "t"); S.sync_pending("manual", "t")

# ---- 角色：/api/stocksync/* 老板 + 上架客服可以，生产员不行 ----
db.create_user("lst", "secret123", "listing", "L"); db.create_user("prd", "secret123", "production", "P")
for u_, want_ in (("lst", 200), ("prd", 403)):
    cl = A.app.test_client(); cl.post("/api/auth/login", json={"username": u_, "password": "secret123"})
    codes_ = {cl.get("/api/stocksync/matrix").status_code, cl.get("/api/stocksync/log").status_code}
    ok(codes_ == {want_}, f"role {u_}: /api/stocksync/* -> {codes_}")
ok(C.get("/api/stocksync/matrix").status_code == 200, "owner can use /api/stocksync/*")
ok("自动推送未开启：先核对对照表，再开启" in _ui and "ยังไม่เปิดการส่งอัตโนมัติ" in _ui, "UI shows the bilingual auto-push-off banner")
ok('if (!confirm(Z("把所有接口店铺的库存全部重新推一遍' in _ui, "UI asks for confirmation before force-push-all")

# ---- 商品 360 记录块 / 页面 / 设置 ----
r = C.get(f"/api/p360/{K}").get_json()
ok(r.get("stocksync") and r["stocksync"][0]["sku"] == K and "reason_zh" in r["stocksync"][0], f"p360 block has recent sync history ({len(r.get('stocksync') or [])})")
ok(C.get("/api/stocksync/matrix").get_json()["kpi"]["total"] > 0, "matrix API")
tr = C.get("/api/stocksync/matrix").get_json()["trend"]
ok(len(tr) == 7 and tr[-1]["n"] > 0, "trend for the chart")
html = C.get("/").get_data(as_text=True)
ok("ss-root" in html, "page has the new stock sync root")
# ---- 待检 / 退货 / 次品区的成品不算可售；质检合格马上可售并触发同步（放最后：开了货位后打印出来的先进待检区）----
from modules.inv import flows as _fl
for z_, zt in (("A", "pick"), ("Q", "qc"), ("D", "defect"), ("T", "returns")):
    C.post("/api/inv/locations/bulk", json={"zone": z_, "layers": 1, "positions": 2, "ztype": zt, **({"categories": ["goods"]} if zt == "pick" else {})})
FAIL["on"] = False
S.set_rule("sku", K, 0, {"safety": 0}); S.set_rule("sku", K, sid, {"safety": 0})
b0 = cell(K)["computed"]; st0 = production.stock_qty(K)
production.stock_add(K, 3, "备货打印 批次#99", "t")
ok(production.unavailable_qty(K) == 3 and production.stock_qty(K) == st0 + 3 and cell(K)["computed"] == b0, f"3 in QC not sellable ({cell(K)['computed']} vs {b0})")
calls.clear()
_it = next(i for _l, i, _q in _fl._held(db.conn(), "qc") if i["code"].upper() == K.upper())
S.INLINE = True
_fl.qc_pass(_it["id"], 2, user="t")
S.INLINE = False
ok(production.unavailable_qty(K) == 1 and cell(K)["computed"] == b0 + 2, f"QC pass 2 -> sellable +2 ({cell(K)['computed']})")
ok(last_push(K) == b0 + 2, f"QC pass triggered a stock sync push ({last_push(K)})")
_fl.qc_fail(_it["id"], 1, action="defect", user="t")
ok(production.unavailable_qty(K) == 1 and cell(K)["computed"] == b0 + 2, "defect never sellable")

print("ERRORS:", E_)
