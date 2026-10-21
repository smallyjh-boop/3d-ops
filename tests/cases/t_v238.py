# v2.38：全功能测试发现的高优先级问题——订单、生产部分
#  1 重新导入旧表格不能把已发货改回待发货      2 修改订单不覆盖订单金额（改商品按差额）
#  4 打印中的订单不能删；任务不在了「打完」不重复扣料   5 打了一部分的订单取消 → 停止排单，已打好的进成品库存
#  7 数量负数 / 0 当 1
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D = T + "/v238"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
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

# ---- 1 状态不倒退
orders.upsert([{"platform": "lazada", "order_no": "R1", "status": "待发货", "order_total": 100, "items": [{"sku": sku, "qty": 1}]}], source="t")
orders.update_order(q("R1")["id"], "t", status="shipped")
st = orders.upsert([{"platform": "lazada", "order_no": "R1", "status": "待发货", "order_total": 100, "items": [{"sku": sku, "qty": 1}]}], source="t")
ok(q("R1")["status"] == "shipped" and st.get("status_kept") == 1, f"re-import keeps shipped ({q('R1')['status']}, {st.get('status_kept')})")
orders.upsert([{"platform": "lazada", "order_no": "R1", "status": "已完成"}], source="t")
ok(q("R1")["status"] == "completed", "forward still applied (shipped -> completed)")
orders.upsert([{"platform": "lazada", "order_no": "R1", "status": "退货"}], source="t")
ok(q("R1")["status"] == "returned", "completed -> returned allowed")
orders.upsert([{"platform": "lazada", "order_no": "R2", "status": "待发货", "items": [{"sku": sku, "qty": 1}]}], source="t")
orders.upsert([{"platform": "lazada", "order_no": "R2", "status": "已取消"}], source="t")
orders.upsert([{"platform": "lazada", "order_no": "R2", "status": "待发货"}], source="t")
ok(q("R2")["status"] == "cancelled", "cancelled not revived by old sheet")
for old_st, new_raw, want in (("returned", "已完成", "completed"), ("delivery_failed", "已发货", "shipped"),
                              ("delivery_failed", "已完成", "completed"), ("completed", "已发货", "completed"),
                              ("to_ship", "未付款", "to_ship"), ("unpaid", "待发货", "to_ship")):
    orders.update_order(q("R1")["id"], "t", status=old_st)
    orders.upsert([{"platform": "lazada", "order_no": "R1", "status": new_raw}], source="t")
    ok(q("R1")["status"] == want, f"{old_st} + sheet {new_raw} -> {want} ({q('R1')['status']})")

# ---- 7 数量负数 / 0
orders.upsert([{"platform": "lazada", "order_no": "N1", "status": "待发货", "items": [{"sku": sku, "qty": -2}]}], source="t")
qi = db.conn().execute("SELECT qty FROM order_items WHERE order_id=?", (q("N1")["id"],)).fetchone()["qty"]
ok(qi == 1, f"import negative qty -> 1 ({qi})")
o = C.post("/api/orders/manual", json={"order_no": "N2", "items": [{"sku": sku, "qty": -3, "unit_price": 100}]}).get_json()
ok(o["items"][0]["qty"] == 1 and (o["order_total"] or 0) > 0, f"manual negative qty -> 1, total {o['order_total']}")

# ---- 2 修改订单不覆盖金额
o = C.post("/api/orders/manual", json={"order_no": "E1", "order_total": 300, "items": [{"sku": sku, "qty": 2, "unit_price": 100}]}).get_json()
oid = o["id"]
r = C.post(f"/api/orders/{oid}/edit", json={"custom_note": "刻字", "items": [{"sku": sku, "qty": 2, "unit_price": 100}]}).get_json()
ok(r["order_total"] == 300, f"edit note only keeps total 300 ({r['order_total']})")
r = C.post(f"/api/orders/{oid}/edit", json={"items": [{"sku": sku, "qty": 3, "unit_price": 100}]}).get_json()
ok(r["order_total"] == 400, f"edit qty 2->3 adjusts by item delta 300 -> 400 ({r['order_total']})")
r = C.post(f"/api/orders/{oid}/edit", json={"order_total": 350, "items": [{"sku": sku, "qty": 3, "unit_price": 100}]}).get_json()
ok(r["order_total"] == 350, "explicit total wins")
# 导入的订单：行金额有折扣 / 只有合计没单价 → 只改地址不动金额；加一行按差额
orders.upsert([{"platform": "lazada", "order_no": "E2", "status": "待发货", "order_total": 200,
                "items": [{"sku": sku, "qty": 2, "unit_price": 100, "item_total": 180}]}], source="t")
o2 = q("E2")["id"]
r = C.post(f"/api/orders/{o2}/edit", json={"address": "新地址", "items": [{"sku": sku, "qty": 2, "unit_price": 100}]}).get_json()
ok(r["order_total"] == 200 and r["items"][0]["item_total"] == 180, f"address-only edit keeps total 200 / line 180 ({r['order_total']}, {r['items'][0]['item_total']})")
orders.upsert([{"platform": "lazada", "order_no": "E3", "status": "待发货", "order_total": 500,
                "items": [{"sku": sku, "qty": 3, "item_total": 450}]}], source="t")
o3 = q("E3")["id"]
r = C.post(f"/api/orders/{o3}/edit", json={"items": [{"sku": sku, "qty": 3, "unit_price": None}, {"sku": sku, "qty": 1, "unit_price": 50}]}).get_json()
ok(r["order_total"] == 550, f"no unit price line kept, add 50 -> 550 ({r['order_total']})")
jid0 = jobs_of(o2)[0]["id"] if jobs_of(o2) else None
db.conn().execute("UPDATE jobs SET note='客户要亮面', pin=1 WHERE order_id=?", (o2,)); db.conn().commit()
C.post(f"/api/orders/{o2}/edit", json={"custom_note": "x", "items": [{"sku": sku, "qty": 2, "unit_price": 100}]})
j = jobs_of(o2)[0] if jobs_of(o2) else {}
ok(j.get("id") == jid0 and j.get("note") == "客户要亮面" and j.get("pin") == 1, "unchanged items keep production job, its note and pinned printer")

# ---- 4 打印中的订单不能删；任务没了打完不重复扣料
o = C.post("/api/orders/manual", json={"order_no": "D1", "items": [{"sku": sku, "qty": 1, "unit_price": 100}]}).get_json()
jid = jobs_of(o["id"])[0]["id"]
run = production.start_run(jid, None, 1, [], None, False, "t", CONF)
rid = run.get("run_id") or run.get("id") or db.conn().execute("SELECT run_id FROM jobs WHERE id=?", (jid,)).fetchone()["run_id"]
r = C.delete(f"/api/orders/{o['id']}")
ok(r.status_code == 400 and "正在打印" in r.get_json()["error"], f"cannot delete printing order {r.status_code}")
ok(q("D1") is not None, "order still there")
# 老数据里可能已经出现「任务不在了的批次」：模拟一下
db.conn().execute("DELETE FROM jobs WHERE id=?", (jid,)); db.conn().commit()
s0 = production.stock_qty(sku)
logs = lambda: db.conn().execute("SELECT COUNT(*) FROM print_runs WHERE id=? AND status='printing'", (rid,)).fetchone()[0]
r1 = C.post(f"/api/runs/{rid}/done"); r2 = C.post(f"/api/runs/{rid}/done")
ok(r1.status_code == 200 and logs() == 0, f"orphan run finishes ({r1.status_code}, still printing={logs()})")
ok(production.stock_qty(sku) == s0 + 1, f"orphan pieces -> stock once ({s0} -> {production.stock_qty(sku)})")

# ---- 5 打了一部分的订单取消
o = C.post("/api/orders/manual", json={"order_no": "P1", "items": [{"sku": sku, "qty": 3, "unit_price": 100}]}).get_json()
jid = jobs_of(o["id"])[0]["id"]
run = production.start_run(jid, None, 1, [], None, False, "t", CONF)
rid = db.conn().execute("SELECT run_id FROM jobs WHERE id=?", (jid,)).fetchone()["run_id"]
production.finish_run(rid, "t")
j = jobs_of(o["id"])[0]
ok(j["qty_done"] == 1 and j["status"] == "todo", f"1 of 3 printed ({j['qty_done']}, {j['status']})")
s0 = production.stock_qty(sku)
orders.update_order(o["id"], "t", status="cancelled")
production.generate("t")
ok(not jobs_of(o["id"]), f"partial job removed after cancel {[(x['id'], x['status']) for x in jobs_of(o['id'])]}")
ok(production.stock_qty(sku) == s0 + 1, f"printed piece -> stock ({s0} -> {production.stock_qty(sku)})")
# 打的时候取消：这一盘打完后停下
o = C.post("/api/orders/manual", json={"order_no": "P2", "items": [{"sku": sku, "qty": 3, "unit_price": 100}]}).get_json()
jid = jobs_of(o["id"])[0]["id"]
production.start_run(jid, None, 1, [], None, False, "t", CONF)
rid = db.conn().execute("SELECT run_id FROM jobs WHERE id=?", (jid,)).fetchone()["run_id"]
orders.update_order(o["id"], "t", status="cancelled")
ok(len(jobs_of(o["id"])) == 1, "job in a running plate stays until the plate ends")
s0 = production.stock_qty(sku)
production.finish_run(rid, "t")
ok(not jobs_of(o["id"]) and production.stock_qty(sku) == s0 + 1, f"cancel during print -> stop after plate, piece to stock ({production.stock_qty(sku) - s0})")
# 3 件打了 1 件，第二盘打剩下 2 件时订单取消 → 打完后不进打包队列，3 件都转成品库存
o = C.post("/api/orders/manual", json={"order_no": "P3", "items": [{"sku": sku, "qty": 3, "unit_price": 100}]}).get_json()
jid = jobs_of(o["id"])[0]["id"]
production.start_run(jid, None, 1, [], None, False, "t", CONF)
production.finish_run(db.conn().execute("SELECT run_id FROM jobs WHERE id=?", (jid,)).fetchone()["run_id"] or
                      db.conn().execute("SELECT MAX(id) FROM print_runs").fetchone()[0], "t")
production.start_run(jid, None, 2, [], None, False, "t", CONF)
rid = db.conn().execute("SELECT run_id FROM jobs WHERE id=?", (jid,)).fetchone()["run_id"]
orders.update_order(o["id"], "t", status="cancelled")
s0 = production.stock_qty(sku)
production.finish_run(rid, "t")
ok(not jobs_of(o["id"]) and production.stock_qty(sku) == s0 + 3, f"last plate after cancel -> all 3 to stock, not packing ({production.stock_qty(sku) - s0}, {jobs_of(o['id'])})")
# 删除订单：已经打好的件转成品库存
o = C.post("/api/orders/manual", json={"order_no": "DEL2", "items": [{"sku": sku, "qty": 2, "unit_price": 100}]}).get_json()
jid = jobs_of(o["id"])[0]["id"]
production.start_run(jid, None, 1, [], None, False, "t", CONF)
production.finish_run(db.conn().execute("SELECT run_id FROM jobs WHERE id=?", (jid,)).fetchone()["run_id"] or
                      db.conn().execute("SELECT MAX(id) FROM print_runs").fetchone()[0], "t")
s0 = production.stock_qty(sku)
ok(C.delete(f"/api/orders/{o['id']}").status_code == 200 and production.stock_qty(sku) == s0 + 1, f"delete order -> printed piece to stock ({production.stock_qty(sku) - s0})")
print("ERRORS", E_)
