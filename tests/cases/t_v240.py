# v2.40：全功能测试的中级问题——订单与发货
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, csv
D = T + "/v240"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, store, production, orders
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
config.save_config({"review_enabled": False, "stock_auto_use": False})
sku = next(v["sku"] for it in store.list_products() for v in (store.load(it["id"]).get("variants") or []) if v.get("sku"))
q = lambda s: db.conn().execute("SELECT * FROM orders WHERE order_no=?", (s,)).fetchone()
jobs_of = lambda oid: [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE order_id=?", (oid,))]
CONF = {"bed_clear": True, "material": True}
manual = lambda no, **kw: C.post("/api/orders/manual", json={"order_no": no, "items": [{"sku": sku, "qty": 1, "unit_price": 100}], **kw}).get_json()

# ---- 1 离开待发货 → 还没开始的任务停下
for st in ("shipped", "unpaid", "completed"):
    o = manual("L" + st)
    ok(len(jobs_of(o["id"])) == 1, f"{st}: job created")
    r = C.post("/api/orders/batch", json={"ids": [o["id"]], "action": "status", "value": st})
    ok(not jobs_of(o["id"]), f"order -> {st}: untouched job removed ({jobs_of(o['id'])})")
o = manual("Lback")
C.post("/api/orders/batch", json={"ids": [o["id"]], "action": "status", "value": "unpaid"})
C.post("/api/orders/batch", json={"ids": [o["id"]], "action": "status", "value": "to_ship"})
ok(len(jobs_of(o["id"])) == 1, "unpaid -> to_ship again: job recreated")

# ---- 2 报价单打完不自动算发货；3 交接不收未付款 / 报价单
o = manual("Q1", kind="quote")
j = jobs_of(o["id"])[0]
C.post(f"/api/jobs/{j['id']}", json={"status": "post"}); C.post(f"/api/jobs/{j['id']}", json={"status": "done"})
ok(q("Q1")["status"] == "quote", f"quote stays quote after all jobs done ({q('Q1')['status']})")
h = C.post("/api/handovers", json={"carrier": "Flash"}).get_json()
hid = (h.get("handover") or h).get("id")
r = C.post(f"/api/handovers/{hid}/scan", json={"code": "Q1"})
ok(r.status_code == 400 and "报价单" in r.get_json()["error"], f"handover refuses quote ({r.status_code})")
o = manual("U1"); orders.update_order(o["id"], "t", status="unpaid")
r = C.post(f"/api/handovers/{hid}/scan", json={"code": "U1"})
ok(r.status_code == 400 and "未付款" in r.get_json()["error"], f"handover refuses unpaid ({r.status_code})")

# ---- 4 没有平台列的表格重复导入不重复建单；5 商品没变不重建任务
orders.upsert([{"platform": "tiktok", "order_no": "TT9", "status": "待发货", "items": [{"sku": sku, "qty": 2}]}], source="t")
production.generate("t")
o = q("TT9"); jid = jobs_of(o["id"])[0]["id"]
db.conn().execute("UPDATE jobs SET note='客户要亮面', pin=1 WHERE id=?", (jid,)); db.conn().commit()
st = orders.upsert([{"platform": "", "order_no": "TT9", "status": "待发货", "items": [{"sku": sku, "qty": 2, "unit_price": 50}]}], source="t")
production.generate("t")
n = db.conn().execute("SELECT COUNT(*) FROM orders WHERE order_no='TT9'").fetchone()[0]
ok(n == 1 and st["orders_updated"] == 1, f"unknown platform re-import updates the same order (count {n})")
j = jobs_of(o["id"])
ok(len(j) == 1 and j[0]["id"] == jid and j[0]["note"] == "客户要亮面" and j[0]["pin"] == 1, "unchanged items keep job, note, pinned printer")
ok(db.conn().execute("SELECT unit_price FROM order_items WHERE order_id=?", (o["id"],)).fetchone()[0] == 50, "price filled in place")
orders.upsert([{"platform": "tiktok", "order_no": "TT9", "status": "待发货", "items": [{"sku": sku, "qty": 3}]}], source="t")
production.generate("t")
ok(jobs_of(o["id"])[0]["qty"] == 3, "changed qty still rebuilds job")

# ---- 6 自动对列
H_SP = ["Order ID", "Order Status", "Return / Refund Status", "Tracking Number*", "Shipping Option", "Order Creation Date",
        "Parent SKU Reference No.", "Product Name", "SKU Reference No.", "Variation Name", "Deal Price", "Quantity",
        "Returned quantity", "Shopee Rebate(THB)", "Buyer Paid Shipping Fee", "Reverse Shipping Fee", "Grand Total", "Username (Buyer)",
        "Remark from buyer", "Note"]
m = {f: H_SP[int(c)] for c, f in orders.auto_map(H_SP).items()}
ok(m.get("sku") == "SKU Reference No." and m.get("qty") == "Quantity" and m.get("status") == "Order Status" and "shop" not in m
   and m.get("shipping_fee") != "Reverse Shipping Fee" and m.get("buyer_note") == "Remark from buyer", f"shopee EN map {m}")
H_LZ = ["orderItemId", "sellerSku", "lazadaSku", "createTime", "updateTime", "orderNumber", "customerName", "shippingName",
        "shippingPostCode", "paidPrice", "unitPrice", "cdTrackingCode", "trackingCode", "status", "buyerFailedDeliveryUserName", "sellerNote"]
m = {f: H_LZ[int(c)] for c, f in orders.auto_map(H_LZ).items()}
ok(m.get("order_no") == "orderNumber" and m.get("sku") == "sellerSku" and m.get("order_time") == "createTime"
   and m.get("tracking_no") == "trackingCode" and m.get("buyer") == "customerName" and m.get("seller_note") == "sellerNote"
   and "buyer_note" not in m and m.get("postcode") == "shippingPostCode" and m.get("unit_price") == "paidPrice", f"lazada camelCase map {m}")
H_CN = ["平台订单号", "订单状态", "下单时间", "商品SKU", "数量", "单价", "买家留言", "店铺"]
m = {f: H_CN[int(c)] for c, f in orders.auto_map(H_CN).items()}
ok(m.get("order_no") == "平台订单号" and m.get("sku") == "商品SKU" and m.get("shop") == "店铺", f"chinese headers still fine {m}")

# ---- 7 打包核对：取消的订单不让打包
o = manual("PK1"); orders.update_order(o["id"], "t", status="cancelled")
r = C.get("/api/pack/lookup?code=PK1")
ok(r.status_code == 400 and "不要打包" in r.get_json()["error"], f"pack lookup refuses cancelled ({r.status_code})")
ok(C.post("/api/pack/done", json={"order_id": o["id"]}).status_code == 400, "pack done refuses cancelled")
o = manual("PK2"); orders.update_order(o["id"], "t", status="shipped")
r = C.get("/api/pack/lookup?code=PK2").get_json()
ok(r.get("status") == "shipped" and r.get("status_zh") == "已发货", "pack lookup shows status for shipped order")

# ---- 8 导入结果的新生产任务数
buf = io.StringIO(); w = csv.writer(buf); w.writerow(["订单号", "SKU", "数量", "订单状态"]); w.writerow(["IMPJ1", sku, 1, "待发货"])
pv = C.post("/api/orders/import/preview", data={"file": (io.BytesIO(buf.getvalue().encode("utf-8-sig")), "x.csv")},
            content_type="multipart/form-data").get_json()
r = C.post("/api/orders/import/commit", json={"token": pv["token"], "mapping": pv["mapping"]}).get_json()
ok((r.get("jobs") or {}).get("created") == 1, f"import reports created jobs ({r.get('jobs')})")

# ---- 9 售后：补发数量、金额
o = manual("AS1")
item_id = o["items"][0]["id"]
r = C.post("/api/aftersales", json={"order_id": o["id"], "kind": "reship", "reason": "坏了", "items": [{"item_id": item_id, "qty": 99}]})
ok(r.status_code == 400 and not [x for x in jobs_of(o["id"]) if x["kind"] == "reship"], f"reship 99 of 1 refused ({r.status_code})")
r = C.post("/api/aftersales", json={"order_id": o["id"], "kind": "refund", "reason": "x", "amount": -50})
ok(r.status_code == 400, f"negative refund refused ({r.status_code})")
r = C.post("/api/aftersales", json={"order_id": o["id"], "kind": "reship", "reason": "坏了", "items": [{"item_id": item_id, "qty": 1}]})
ok(r.status_code == 200, "reship 1 of 1 ok")
# ==== 发布前审查发现的问题 ====
# H1 已发货的订单：打了一部分的件不进成品库存（已经跟着包裹走了）
o = manual("H1", items=[{"sku": sku, "qty": 3, "unit_price": 100}]) if False else C.post("/api/orders/manual", json={"order_no": "H1", "items": [{"sku": sku, "qty": 3, "unit_price": 100}]}).get_json()
j = jobs_of(o["id"])[0]
production.start_run(j["id"], 0, 1, [], None, False, "t", CONF)
production.finish_run(db.conn().execute("SELECT run_id FROM jobs WHERE id=?", (j["id"],)).fetchone()["run_id"] or db.conn().execute("SELECT MAX(id) FROM print_runs").fetchone()[0], "t")
s0 = production.stock_qty(sku)
C.post("/api/orders/batch", json={"ids": [o["id"]], "action": "status", "value": "shipped"})
ok(not jobs_of(o["id"]) and production.stock_qty(sku) == s0, f"shipped with partial print: job dropped, no phantom stock (+{production.stock_qty(sku) - s0})")
# H2 认不出 / 平台中间状态（待揽收、已打包、ON_HOLD）不删生产任务
orders.upsert([{"platform": "shopee", "order_no": "H2", "status": "待发货", "items": [{"sku": sku, "qty": 1}]}], source="t")
production.generate("t"); oh = q("H2")["id"]
for st_ in ("待揽收", "已打包", "ON_HOLD"):
    orders.upsert([{"platform": "shopee", "order_no": "H2", "status": st_}], source="t"); production.generate("t")
    ok(len(jobs_of(oh)) == 1, f"status {st_} -> {q('H2')['status']}: job kept")
# M3 批量改状态不再每单重排（60 单要很快）
import time as _t
ids = [manual(f"B{i}")["id"] for i in range(60)]
t0 = _t.time(); C.post("/api/orders/batch", json={"ids": ids, "action": "status", "value": "cancelled"}); dt_ = _t.time() - t0
ok(dt_ < 2.5 and not any(jobs_of(i) for i in ids), f"batch cancel 60 orders in {dt_:.2f}s, jobs removed")
# M4 改订单商品不会删补发任务
config.save_config({"stock_auto_use": True}); production.stock_add(sku, 5, "t", "t")
o = C.post("/api/orders/manual", json={"order_no": "M4", "items": [{"sku": sku, "qty": 2, "unit_price": 100}]}).get_json()
C.post("/api/aftersales", json={"order_id": o["id"], "kind": "reship", "reason": "坏了", "items": [{"item_id": o["items"][0]["id"], "qty": 1}]})
C.post(f"/api/orders/{o['id']}/edit", json={"items": [{"sku": sku, "qty": 3, "unit_price": 100}]})
ok(any(x["kind"] == "reship" for x in jobs_of(o["id"])), "reship job survives editing items")
config.save_config({"stock_auto_use": False})
# L10 平台罚款 / 赔付可以负数；补发累计不超过原数量
r = C.post("/api/aftersales", json={"order_id": o["id"], "kind": "other", "reason": "平台赔付", "penalty": -30})
ok(r.status_code == 200, f"negative penalty (platform compensation) allowed ({r.status_code})")
r = C.post("/api/aftersales", json={"order_id": o["id"], "kind": "reship", "reason": "又坏了", "items": [{"item_id": orders.get_order(o["id"])["items"][0]["id"], "qty": 3}]})
ok(r.status_code == 400 and "之前已经补发过" in r.get_json()["error"], f"cumulative reship capped ({r.status_code})")
# L11 没有平台列的表格不会撞到批发单
orders.upsert([{"platform": "wholesale", "order_no": "W-100", "status": "待发货", "items": [{"sku": sku, "qty": 1}]}], source="t")
orders.upsert([{"platform": "", "order_no": "W-100", "status": "已发货", "items": [{"sku": sku, "qty": 1}]}], source="t")
ok(db.conn().execute("SELECT status FROM orders WHERE platform='wholesale' AND order_no='W-100'").fetchone()[0] == "to_ship", "wholesale order not overwritten by an unknown-platform sheet")
print("ERRORS", E_)
