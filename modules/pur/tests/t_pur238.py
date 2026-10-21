# v2.38：全功能测试的高优先级问题——库存、采购、对账
# 10 采购到货不能超量   11 作废采购入库单 → 采购单、财务一起退回   12 同一物品写几行出库，合起来看库存
# 13 Shopee 订单没有订单金额时，对账按商品合计算（以前收入当 0、扣费算成负数）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, time, datetime as dt
D = T + "/m_pur238"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, inventory as inv, orders, store
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
it = C.post("/api/inv/items", json={"name_zh": "胶带", "category": "pack", "unit": "卷"}).get_json()["item"]
qty = lambda: inv.get_item(it["code"])["qty"]
sup = C.post("/api/inv/suppliers", json={"name": "S"}).get_json()
sid = (sup.get("supplier") or sup).get("id")
po = C.post("/api/inv/po", json={"supplier_id": sid, "lines": [{"item_id": it["id"], "qty": 10, "unit_cost": 5}]}).get_json()["po"]
C.post(f"/api/inv/po/{po['id']}/order")
lid = po["lines"][0]["id"]

# ---- 10 超量到货
r = C.post(f"/api/inv/po/{po['id']}/receive", json={"qtys": {str(lid): 4}}).get_json()
ok(r["po"]["status"] == "partial" and qty() == 4, f"receive 4/10 ({r['po']['status']}, stock {qty()})")
r = C.post(f"/api/inv/po/{po['id']}/receive", json={"qtys": {str(lid): 10}})
ok(r.status_code == 400 and "还差 6" in r.get_json()["error"], f"over-receive refused ({r.status_code} {r.get_json().get('error')})")
ok(qty() == 4, "stock unchanged after refused over-receive")
r = C.post(f"/api/inv/po/{po['id']}/receive", json={"qtys": {str(lid): 6}}).get_json()
ok(r["po"]["status"] == "received" and qty() == 10, "receive the remaining 6 -> received")

# ---- 11 作废入库单
fin_sum = lambda: db.conn().execute("SELECT COALESCE(SUM(amount),0) FROM fin_events WHERE kind='purchase_received' AND ref_no=?", (po["no"],)).fetchone()[0]
f0 = fin_sum()
doc = db.conn().execute("SELECT no FROM inv_docs WHERE ref=? AND status='done' ORDER BY id DESC", ("po:" + po["no"],)).fetchone()["no"]
r = C.post(f"/api/inv/docs/{doc}/void")
p2 = C.get(f"/api/inv/po/{po['id']}").get_json()["po"]
ok(r.status_code == 200 and qty() == 4, f"void receipt -> stock back to 4 ({qty()})")
ok(p2["status"] == "partial" and p2["lines"][0]["received"] == 4, f"PO back to partial 4/10 ({p2['status']}, {p2['lines'][0]['received']})")
ok(abs(fin_sum() - (f0 - 30)) < 0.01, f"finance received reduced by 30 ({f0} -> {fin_sum()})")
r = C.post(f"/api/inv/po/{po['id']}/receive", json={"qtys": {str(lid): 6}}).get_json()
ok(r.get("po", {}).get("status") == "received" and qty() == 10, "can receive again after void")

# ---- 12 同一物品写两行
r = C.post("/api/inv/docs", json={"kind": "issue", "lines": [{"item_id": it["id"], "qty": 6}, {"item_id": it["id"], "qty": 6}], "note": "t"})
ok(r.status_code == 400 and qty() == 10, f"two lines 6+6 > 10 refused ({r.status_code}, stock {qty()})")
r = C.post("/api/inv/docs", json={"kind": "issue", "lines": [{"item_id": it["id"], "qty": 4}, {"item_id": it["id"], "qty": 5}], "note": "t"})
ok(r.status_code == 200 and qty() == 1, f"two lines 4+5 <= 10 ok (stock {qty()})")
for bad in ("nan", "inf", "-inf"):
    r = C.post("/api/inv/docs", json={"kind": "purchase", "lines": [{"item_id": it["id"], "qty": bad}], "note": "t"})
    ok(r.status_code == 400, f"qty {bad} refused")
ok(C.get("/api/inv/items").status_code == 200 and qty() == 1, "items page still loads")

# ---- 13 对账：没有订单金额
from modules.fin import logic as fin
sku = next(v["sku"] for x in store.list_products() for v in (store.load(x["id"]).get("variants") or []) if v.get("sku"))
orders.upsert([{"platform": "shopee", "order_no": "SPNOAMT", "status": "已完成", "order_time": time.time() - 3600,
                "items": [{"sku": sku, "qty": 2, "unit_price": 129}]}], source="t")
oid = db.conn().execute("SELECT id, order_total FROM orders WHERE order_no='SPNOAMT'").fetchone()
db.conn().execute("UPDATE orders SET order_total=NULL, settlement=210 WHERE id=?", (oid["id"],)); db.conn().commit()
M = dt.date.today().strftime("%Y-%m")
rc = fin.reconcile(*fin.period(M)[:2])
row = next(x for x in rc["settled"] if x["order_no"] == "SPNOAMT")
ok(row["revenue"] == 258 and row["fee"] == 48, f"reconcile uses item total when order_total empty (rev {row['revenue']}, fee {row['fee']})")
print("ERRORS", E_)
