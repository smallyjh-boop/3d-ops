# v2.43：订单页批量处理生产任务（用库存发 / 标记已打好 / 标记已打包）；订单详情带可用成品数；生产角色也能用
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3
D = T + "/m_jobs243"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, production, orders as orders_mod, chain
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pong", "secret123", "production", "Pong")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
P = A.app.test_client(); P.post("/api/auth/login", json={"username": "pong", "password": "secret123"})
sku = store.load("3DP0015")["variants"][0]["sku"]
orders_mod.upsert([{"platform": "manual", "order_no": f"J-{i}", "status": "to_ship", "items": [{"sku": sku, "qty": 2}]} for i in range(3)], source="test")
chain.order_changed("t")
oid = lambda no: db.conn().execute("SELECT id FROM orders WHERE order_no=?", (no,)).fetchone()["id"]
ids = [oid(f"J-{i}") for i in range(3)]
jobs = lambda o: production.list_jobs(order_id=o)
ok(all(jobs(o) and jobs(o)[0]["status"] == "todo" for o in ids), "jobs generated")
# 订单详情：带可用成品数
production.stock_set(sku, 3, None, "t")
d = C.get(f"/api/orders/{ids[0]}").get_json()
ok(d["jobs"][0]["stock_free"] == 3, f"stock_free in detail {d['jobs'][0].get('stock_free')}")
# 用库存发：第一单 2 个、第二单 1 个（只剩 1 个），第三单没库存
r = C.post("/api/jobs/bulk", json={"order_ids": ids, "action": "use_stock"}).get_json()
ok(r["done"] == 2 and len(r["skipped"]) == 1 and "库存" in r["skipped"][0], f"use stock {r}")
ok(jobs(ids[0])[0]["stock_n"] == 2 and jobs(ids[1])[0]["stock_n"] == 1, "reserved per order")
# 标记已打好：还没开始打的（第二单剩 1 个、第三单）→ 待打包；第一单全用库存的已经不用打
r = P.post("/api/jobs/bulk", json={"order_ids": ids[1:], "action": "printed"}).get_json()
ok(r["done"] == 2 and all(jobs(o)[0]["status"] == "post" for o in ids[1:]), f"printed (production role) {r}")
r = C.post("/api/jobs/bulk", json={"order_ids": ids, "action": "packed"}).get_json()
ok(r["done"] >= 2 and all(jobs(o)[0]["status"] == "packed" for o in ids[1:]), f"packed {r}")
ok(C.post("/api/jobs/bulk", json={"order_ids": ids, "action": "nope"}).status_code == 400, "bad action")
# 单个任务：退回、换打印机（订单详情里的按钮用的就是这些接口）
j = jobs(ids[2])[0]
ok(C.post(f"/api/jobs/{j['id']}", json={"status": "post"}).status_code == 200 and jobs(ids[2])[0]["status"] == "post", "back to post")
log = [x["action"] for x in orders_mod.get_log(ids[1])]
ok(any("用库存" in a for a in log) and any("已打包" in a for a in log), f"order log {log[:6]}")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
