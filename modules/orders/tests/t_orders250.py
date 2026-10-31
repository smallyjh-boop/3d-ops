# v2.50：订单页 BigSeller 式改版：工作流队列（映射 + 计数）、每种单据打印次数、包裹类型、保存筛选、批量搜索、
# 风险买家、颜色标记、批量接口（搁置 / 交接 / 安排发货）、员工看不到利润、客服从聊天建单、运费核对
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, time, json
D = T + "/m_orders250"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, production, orders as orders_mod, chain, config
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("lin", "secret123", "listing", "Lin")
db.create_user("pong", "secret123", "production", "Pong")
def login(u):
    c = A.app.test_client(); c.post("/api/auth/login", json={"username": u, "password": "secret123"}); return c
C, L, P = login("boss"), login("lin"), login("pong")
pids = [p["id"] for p in store.list_products()]
skus = []
for pid in pids:
    for v in store.load(pid).get("variants") or []:
        if v.get("sku") and v["sku"] not in skus:
            skus.append(v["sku"])
s1, s2 = skus[0], skus[1]
now = time.time()
o = lambda no, **kw: {"platform": "lazada", "shop": "LZ", "order_no": no, "status": "to_ship", "order_time": now - 3600,
                      "ship_by": now + 48 * 3600, "items": [{"sku": s1, "qty": 1, "unit_price": 100}], "order_total": 100, **kw}
orders_mod.upsert([
    o("Q-SINGLE", tracking_no="TRK001"),
    o("Q-MULTI", items=[{"sku": s1, "qty": 3, "unit_price": 100}], order_total=300, tracking_no="TRK002"),
    o("Q-MIXED", items=[{"sku": s1, "qty": 1, "unit_price": 100}, {"sku": s2, "qty": 2, "unit_price": 50}], order_total=200),
    o("Q-NOSKU", items=[{"sku": "NOPE-XYZ", "qty": 1}]),
    o("Q-SHIPPED", status="shipped"), o("Q-DONE", status="completed"), o("Q-CANCEL", status="cancelled"),
    o("Q-UNPAID", status="unpaid"), o("Q-RET", status="returned"),
    o("Q-URGENT", ship_by=now + 3 * 3600),
], source="test")
oid = lambda no: db.conn().execute("SELECT id FROM orders WHERE order_no=?", (no,)).fetchone()["id"]
c = db.conn()
c.execute("UPDATE orders SET hold=0, reviewed_at=? WHERE order_no LIKE 'Q-%'", (now,)); c.commit()
chain.order_changed("t")
J = lambda no: production.list_jobs(order_id=oid(no))
ok(J("Q-SINGLE") and J("Q-MULTI") and J("Q-MIXED"), "jobs generated")

def lst(**kw):
    kw.setdefault("shop", "LZ")             # 测试数据里本来就有别的订单，只看这个测试建的（店铺 LZ）
    r = C.get("/api/orders?" + "&".join(f"{k}={v}" for k, v in kw.items())).get_json()
    return r, [x["order_no"] for x in r["orders"]]

# ---------- 队列映射 ----------
r, nos = lst(tab="to_produce")
ok({"Q-SINGLE", "Q-MULTI", "Q-MIXED", "Q-NOSKU", "Q-URGENT"} <= set(nos), f"to_produce {nos}")
ok(r["counts"]["to_produce"] == 5 and r["counts"]["shipped"] == 1 and r["counts"]["completed"] == 1 and r["counts"]["cancelled"] == 1
   and r["counts"]["unpaid"] == 1 and r["counts"]["aftersale"] == 1, f"counts {r['counts']}")
ok(r["counts"]["waiting"] == r["counts"]["to_produce"] and "review" in r["counts"], "legacy tab counts kept")
ok(r["counts"]["exception"] >= 2 and r["counts"]["urgent"] == 1, f"exception/urgent {r['counts']['exception']} {r['counts']['urgent']}")
_, nos = lst(tab="exception"); ok("Q-NOSKU" in nos and "Q-URGENT" in nos and "Q-SINGLE" not in nos, f"exception queue {nos}")
_, nos = lst(tab="waiting"); ok("Q-SINGLE" in nos, "legacy tab=waiting still works")
r0, nos = lst(tab="urgent"); ok(nos == ["Q-URGENT"], f"legacy urgent {nos}")
_, nos = lst(tab="aftersale"); ok(nos == ["Q-RET"], f"aftersale {nos}")
# 生产中 → 待打包 → 待打单 → 待揽收
j = J("Q-SINGLE")[0]
c.execute("UPDATE jobs SET status='printing' WHERE order_id=?", (oid("Q-SINGLE"),)); c.commit()
r, nos = lst(tab="producing"); ok("Q-SINGLE" in nos, f"producing {nos}")
c.execute("UPDATE jobs SET status='post' WHERE order_id=?", (oid("Q-SINGLE"),)); c.commit()
r, nos = lst(tab="to_pack"); ok(nos == ["Q-SINGLE"], f"to_pack {nos}")
c.execute("UPDATE jobs SET status='packed' WHERE order_id=?", (oid("Q-SINGLE"),)); c.commit()
r, nos = lst(tab="to_label"); ok(nos == ["Q-SINGLE"], f"to_label {nos}")
r = C.get(f"/print/labels?type=self&ids={oid('Q-SINGLE')}"); ok(r.status_code == 200, "print self label")
r, nos = lst(tab="to_pickup"); ok(nos == ["Q-SINGLE"], f"to_pickup after label {nos}")
r, nos = lst(tab="ready"); ok(nos == ["Q-SINGLE"], "legacy ready = to_label + to_pickup")
# 审核 / 搁置
ok(C.post("/api/orders/batch", json={"ids": [oid("Q-MULTI")], "action": "shelve", "value": "等买家补款"}).get_json()["done"] == 1, "shelve")
ok(C.post("/api/orders/batch", json={"ids": [oid("Q-MIXED")], "action": "hold", "value": "看一下"}).get_json()["done"] == 1, "hold → review")
r, nos = lst(tab="shelf"); ok(nos == ["Q-MULTI"], f"shelf {nos}")
r, nos = lst(tab="review"); ok(nos == ["Q-MIXED"] and r["counts"]["review"] == 1 and r["counts"]["shelf"] == 1, f"review {nos}")
C.post("/api/orders/batch", json={"ids": [oid("Q-MULTI"), oid("Q-MIXED")], "action": "approve"})
r, nos = lst(tab="to_produce"); ok("Q-MULTI" in nos and "Q-MIXED" in nos, "approve back to to_produce")
# 安排发货失败（Lazada RTS 失败的标签）
c.execute("UPDATE orders SET tags=? WHERE order_no='Q-SHIPPED'", (orders_mod.RTS_FAIL_TAG,)); c.commit()
r, nos = lst(tab="rts_failed"); ok(nos == ["Q-SHIPPED"] and r["counts"]["rts_failed"] == 1, f"rts_failed {nos}")
# 队列数字只用一条聚合 SQL（接口）
q = C.get("/api/orders/queues?shop=LZ").get_json(); ok(q["counts"]["to_pickup"] == 1 and len(q["queues"]) == 8, "queues endpoint")
ok(P.get("/api/orders/queues").status_code == 200, "production can read queue counts")
# 默认排序：进行中的队列按最晚发货（最急的在前）
r, nos = lst(tab="to_produce"); ok(nos[0] == "Q-URGENT" and r["sort"] == "ship_by", f"default sort ship_by {nos[:3]}")
r, _ = lst(tab="completed"); ok(r["sort"] == "time_desc", "finished queues by order time")

# ---------- 包裹类型 ----------
_, nos = lst(pkg="single", tab="all"); ok("Q-SINGLE" in nos and "Q-MULTI" not in nos and "Q-MIXED" not in nos, f"single {nos}")
_, nos = lst(pkg="multi", tab="all"); ok(nos == ["Q-MULTI"], f"multi {nos}")
_, nos = lst(pkg="mixed", tab="all"); ok(nos == ["Q-MIXED"], f"mixed {nos}")
r, _ = lst(tab="all", q="Q-MIXED"); ok(r["orders"][0]["pkg"] == "mixed", "pkg on row")

# ---------- 打印状态 ----------
ids2 = [oid("Q-MULTI"), oid("Q-MIXED")]
ok(C.get(f"/print/orders?type=pick&ids={','.join(map(str, ids2))}").status_code == 200, "print pick")
ok(C.get(f"/print/orders?type=pack&ids={ids2[0]}").status_code == 200, "print pack")
C.get(f"/print/orders?type=pack&ids={ids2[0]}")
h = C.get(f"/print/orders?type=invoice&ids={ids2[0]}"); ok(h.status_code == 200 and "ใบเสร็จ" in h.get_data(as_text=True), "print invoice")
ok(P.get(f"/print/orders?type=invoice&ids={ids2[0]}").status_code == 403, "production cannot print invoice (prices)")
pr = orders_mod.doc_prints(ids2[0]); ok(pr["pick"]["n"] == 1 and pr["pack"]["n"] == 2 and pr["invoice"]["n"] == 1, f"doc counts {pr}")
_, nos = lst(tab="all", printed="pick:1"); ok(set(nos) == {"Q-MULTI", "Q-MIXED"}, f"printed pick {nos}")
_, nos = lst(tab="all", printed="pick:0"); ok("Q-MULTI" not in nos and "Q-SINGLE" in nos, "not printed pick")
_, nos = lst(tab="all", printed="label:1"); ok(nos == ["Q-SINGLE"], f"label printed {nos}")
_, nos = lst(tab="all", label="none"); ok("Q-SINGLE" not in nos, "legacy label=none")
r, _ = lst(tab="all", q="Q-MULTI"); ok(r["orders"][0]["prints"]["pack"] == 2, "prints on row")
d = C.get(f"/api/orders/{ids2[0]}").get_json(); ok(d["prints"]["invoice"]["n"] == 1, "prints in detail")

# ---------- 批量搜索 ----------
_, nos = lst(tab="all", nos="Q-SINGLE,%20TRK002%0AQ-NOPE"); ok(set(nos) == {"Q-SINGLE", "Q-MULTI"}, f"batch exact {nos}")
r, _ = lst(tab="all", nos="Q-SINGLE%20Q-NOPE"); ok(r["nos_missing"] == ["Q-NOPE"], f"missing {r['nos_missing']}")
_, nos = lst(tab="all", nos="Q-SING", match="exact"); ok(nos == [], "exact needs full number")
_, nos = lst(tab="all", nos="SING,TRK00", match="fuzzy"); ok(set(nos) == {"Q-SINGLE", "Q-MULTI"}, f"fuzzy {nos}")

# ---------- 保存筛选（每个账号自己的）----------
r = C.post("/api/orders/presets", json={"name": "LZ 单品", "filters": {"platform": "lazada", "pkg": "single", "tab": "to_label", "bad": 1}}).get_json()
ok(len(r["items"]) == 1 and r["items"][0]["filters"] == {"platform": "lazada", "pkg": "single", "tab": "to_label"}, f"preset saved {r}")
C.post("/api/orders/presets", json={"name": "LZ 单品", "filters": {"platform": "shopee"}})
r = C.get("/api/orders/presets").get_json(); ok(len(r["items"]) == 1 and r["items"][0]["filters"]["platform"] == "shopee", "same name overwrites")
ok(L.get("/api/orders/presets").get_json()["items"] == [], "presets are per user")
ok(C.post("/api/orders/presets", json={"name": " ", "filters": {}}).status_code == 400, "name required")
P.post("/api/orders/presets", json={"name": "mine", "filters": {"tab": "to_pack"}})
dl = L.post(f"/api/orders/presets/{r['items'][0]['id']}/delete", json={})
ok(dl.status_code == 200 and len(C.get("/api/orders/presets").get_json()["items"]) == 1, f"cannot delete other user's preset {dl.status_code}")
ok(C.post(f"/api/orders/presets/{r['items'][0]['id']}/delete", json={}).get_json()["items"] == [], "delete preset")

# ---------- 风险买家 ----------
config.save_config(dict(config.load_config(), buyer_risk_refused=2, buyer_risk_returned=3)) if hasattr(config, "save_config") else None
orders_mod.upsert([{"platform": "lazada", "shop": "LZ", "order_no": f"R-{i}", "status": "delivery_failed", "buyer": "badguy", "phone": "0811111111",
                    "items": [{"sku": s1, "qty": 1}]} for i in range(2)] +
                  [{"platform": "lazada", "shop": "LZ", "order_no": "R-NEW", "status": "to_ship", "buyer": "badguy", "phone": "0811111111",
                    "items": [{"sku": s1, "qty": 1}], "payment": "COD"},
                   {"platform": "lazada", "shop": "LZ", "order_no": "R-OK", "status": "to_ship", "buyer": "goodguy", "phone": "0822222222",
                    "items": [{"sku": s1, "qty": 1}]},
                   {"platform": "lazada", "shop": "LZ", "order_no": "R-ONCE-1", "status": "delivery_failed", "buyer": "once", "phone": "0833333333",
                    "items": [{"sku": s1, "qty": 1}]},
                   {"platform": "lazada", "shop": "LZ", "order_no": "R-ONCE", "status": "to_ship", "buyer": "once", "phone": "0833333333",
                    "items": [{"sku": s1, "qty": 1}]}], source="test")
r, nos = lst(tab="all", risk=1)
ok("R-NEW" in nos and "R-OK" not in nos and "R-ONCE" not in nos, f"risk filter {nos}")
row = [x for x in lst(tab="all", q="R-NEW")[0]["orders"] if x["order_no"] == "R-NEW"][0]
ok("risk" in row["buyer_tags"] and "拒收" in row["risk_reason"], f"risk tag on row {row['buyer_tags']} {row['risk_reason']}")
d = C.get(f"/api/orders/{oid('R-NEW')}").get_json(); ok(d["risk"]["risky"] and d["risk"]["refused"] == 2, f"risk in detail {d['risk']}")
key = d["buyer_key"]
k2 = C.get(f"/api/orders/{oid('R-OK')}").get_json()["buyer_key"]
C.post("/api/buyers", json={"key": k2, "level": "blacklist", "note": "骂人"})
r, nos = lst(tab="all", risk=1); ok("R-OK" in nos, "manual blacklist is risky")
d = C.get(f"/api/orders/{oid('R-OK')}").get_json(); ok("黑名单" in d["risk"]["reason"] and "骂人" in d["risk"]["reason"], f"blacklist reason {d['risk']}")
from modules.cs.logic import erp_link
h = erp_link.buyer_history("lazada", "goodguy"); ok(h and "黑名单" in h["risk"] and h["blacklist"], f"CS sees risk {h and h.get('risk')}")

# ---------- 颜色标记 ----------
ok(C.post("/api/orders/flag", json={"ids": [oid("Q-SINGLE")], "color": "red", "note": "先打"}).get_json()["done"] == 1, "flag")
ok(C.post("/api/orders/flag", json={"ids": [oid("Q-SINGLE")], "color": "pink"}).status_code == 400, "bad colour")
C.post("/api/orders/batch", json={"ids": [oid("Q-MULTI")], "action": "flag", "value": "blue|等回复"})
_, nos = lst(tab="all", flag="red"); ok(nos == ["Q-SINGLE"], f"flag filter {nos}")
_, nos = lst(tab="all", flag="any"); ok(set(nos) == {"Q-SINGLE", "Q-MULTI"}, "any flag")
ok(orders_mod.get_order(oid("Q-MULTI"))["flag_note"] == "等回复", "flag note")
C.post("/api/orders/flag", json={"ids": [oid("Q-MULTI")], "color": ""}); ok(not orders_mod.get_order(oid("Q-MULTI"))["flag"], "unflag")

# ---------- 批量：交接单、安排发货 ----------
r = C.post("/api/orders/handover-add", json={"ids": [oid("Q-SINGLE"), oid("Q-CANCEL")]}).get_json()
ok(r["added"] == 1 and len(r["errors"]) == 1 and r["handovers"], f"handover add {r}")
ok(orders_mod.get_order(oid("Q-SINGLE"))["handover_id"] == r["handovers"][0], "order in handover")
ok(P.post("/api/orders/handover-add", json={"ids": [oid("Q-SHIPPED")]}).status_code == 400, "shipped order not added (production allowed to call)")
r = C.post("/api/orders/rts", json={"ids": [oid("Q-SINGLE")]})
ok(r.status_code == 400, f"rts: no Lazada API shop → clear error {r.get_json()}")
ok(L.post("/api/orders/batch", json={"ids": [oid("Q-MIXED")], "action": "priority", "value": 1}).get_json()["done"] == 1, "listing bulk priority")
ok(P.post("/api/orders/batch", json={"ids": [oid("Q-MIXED")], "action": "priority", "value": 0}).status_code == 403, "production no batch")

# ---------- 员工看不到利润 ----------
r = C.get("/api/orders?tab=all&q=Q-MULTI").get_json()
ok("est_profit" in r["orders"][0] and r["orders"][0]["est_profit"]["revenue"] == 300, f"owner sees est profit {r['orders'][0].get('est_profit')}")
for cl, nm in ((L, "listing"), (P, "production")):
    r = cl.get("/api/orders?tab=all").get_json()
    ok(r["orders"] and all("est_profit" not in x and "order_total" not in x and "profit" not in x for x in r["orders"]), f"{nm} no profit/total")
    d = cl.get(f"/api/orders/{oid('Q-MULTI')}").get_json(); ok("profit" not in d, f"{nm} no profit in detail")
# 只看亏本单：老板才行；员工传了也不管
c.execute("UPDATE orders SET order_total=1 WHERE order_no='Q-MIXED'"); c.commit()
_, nos = lst(tab="all", loss=1); ok("Q-MIXED" in nos and "Q-MULTI" not in nos, f"loss filter {nos}")
r = L.get("/api/orders?tab=all&loss=1").get_json(); ok(r["total"] > 3, "loss ignored for staff")
# 商品缩略图字段
r = C.get("/api/orders?tab=all&q=Q-MULTI").get_json(); ok("img" in r["orders"][0]["items"][0], "item img field")
# 平台状态
r = C.get("/api/orders?tab=all&q=Q-SINGLE").get_json(); ok("status_raw" in r["orders"][0], "platform status field")

# ---------- 客服：从聊天建单 ----------
from modules.cs.logic import data as csdata
cid = csdata.create_conv(buyer="chatbuyer", platform="lazada")["id"]
r = C.post(f"/api/cs/convs/{cid}/action", json={"type": "make_order", "kind": "manual", "items": [{"sku": s1, "qty": 2, "unit_price": 80}],
                                                 "note": "刻字 Nid", "ship": {"receiver": "Nid", "phone": "0899"}})
j = r.get_json(); ok(r.status_code == 200 and j.get("order_id"), f"make order from chat {r.status_code} {str(j)[:300]}")
mo = orders_mod.get_order(j["order_id"]); ok(mo["platform"] == "lazada" and mo["buyer"] == "chatbuyer" and mo["kind"] == "manual"
                                            and mo["custom_note"] == "刻字 Nid" and mo["receiver"] == "Nid" and mo["status"] == "to_ship", "order fields")
r = C.post(f"/api/cs/convs/{cid}/action", json={"type": "make_order", "kind": "quote", "items": [{"sku": s1, "qty": 50}]}).get_json()
ok(orders_mod.get_order(r["order_id"])["status"] == "quote", "quote from chat")
ok(C.post(f"/api/cs/convs/{cid}/action", json={"type": "make_order", "items": []}).status_code == 400, "no items → error")
ok(any(x.get("pid") for x in C.get("/api/skus").get_json()), "skus carry product id")

# ---------- 运费核对（财务 → 平台对账）----------
from modules.fin.logic import recon
c.execute("UPDATE orders SET shipping_fee=40 WHERE order_no='Q-DONE'"); c.commit()
c.execute("CREATE TABLE IF NOT EXISTS fin_settle_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT, shop TEXT, order_key TEXT, order_no TEXT, "
          "fee_name TEXT, amount REAL, wht REAL, vat REAL, day TEXT, ref TEXT, row_hash TEXT, is_item INTEGER)")
cols = {r[1] for r in c.execute("PRAGMA table_info(fin_settle_lines)")}
from modules.fin.logic.settle import key as skey
def line(no, name, amt, item=0):
    vals = {"platform": "lazada", "shop": "LZ", "order_key": skey(no), "order_no": no, "fee_name": name, "amount": amt, "day": time.strftime("%Y-%m-%d"),
            "ref": "", "row_hash": f"t:{no}:{name}:{amt}", "is_item": item, "wht": 0, "vat": 0}
    vals = {k: v for k, v in vals.items() if k in cols}
    c.execute(f"INSERT INTO fin_settle_lines({','.join(vals)}) VALUES({','.join('?' * len(vals))})", list(vals.values()))
line("Q-DONE", "Item Price Credit", 100, 1); line("Q-DONE", "Shipping Fee (Paid By Customer)", 40); line("Q-DONE", "Shipping Fee Charged by Lazada", -75)
line("Q-SHIPPED", "Item Price Credit", 100, 1); line("Q-SHIPPED", "Shipping Fee (Paid By Customer)", 40); line("Q-SHIPPED", "Shipping Fee Charged by Lazada", -42)
c.commit()
rows = c.execute("SELECT id, platform, shop, order_no, status, order_time, order_total, settlement FROM orders WHERE order_no IN ('Q-DONE','Q-SHIPPED')").fetchall()
sc = recon.ship_check(rows, {}, 5)
ok(len(sc) == 1 and sc[0]["order_no"] == "Q-DONE" and sc[0]["charged"] == 75 and sc[0]["expected"] == 40 and sc[0]["diff"] == 35, f"ship check {sc}")
import datetime as _dt
r = C.get(f"/api/fin/reconcile?start={(_dt.date.today() - _dt.timedelta(days=5)).isoformat()}&end={(_dt.date.today() + _dt.timedelta(days=1)).isoformat()}")
if r.status_code == 200:
    jr = r.get_json(); ok("ship" in jr and jr["total"].get("ship_issues", 0) >= 1, f"reconcile has ship tab {jr['total'].get('ship_issues')}")
else:
    ok(False, f"reconcile {r.status_code} {r.get_data(as_text=True)[:200]}")

# ---------- 手机端搜索（mobile 模块用 orders.search）还好用 ----------
rr = orders_mod.search({"q": "Q-MULTI", "sort": "time_desc", "page": 1, "page_size": 10})
ok(rr["orders"] and rr["orders"][0]["order_no"] == "Q-MULTI" and rr["orders"][0]["items"], "search() for mobile")
print("ERRORS", E_)
