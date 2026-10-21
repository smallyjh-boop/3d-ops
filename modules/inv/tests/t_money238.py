# v2.38：员工权限（全功能测试的高优先级问题）
#  6 库存 / 采购的金额只给老板和有「入库」或「付款」权限的员工；生产角色看不到料卷价格
#  9 订单操作记录不把金额给员工看     8 没有「取消/拒收」权限的员工不能借「登记售后」把订单改成拒收
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D = T + "/m_money238"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, store, inventory as inv
config.save_config({"review_enabled": False})
db.create_user("boss", "secret123", "owner", "Boss")
nok_id = db.create_user("nok", "pass123", "listing", "Nok")
db.create_user("pk", "pass123", "production", "Pk")
buy_id = db.create_user("buyer", "pass123", "listing", "Buyer")
def cl(u, p):
    c = A.app.test_client(); c.post("/api/auth/login", json={"username": u, "password": p}); return c
boss = cl("boss", "secret123")
nok_id = nok_id if isinstance(nok_id, int) else db.conn().execute("SELECT id FROM users WHERE username='nok'").fetchone()[0]
buy_id = buy_id if isinstance(buy_id, int) else db.conn().execute("SELECT id FROM users WHERE username='buyer'").fetchone()[0]
pn = db.user_perms("listing")
boss.post(f"/api/users/{buy_id}", json={"perms": dict(pn, **{"inv.in": True})})
nok, pk, buyer = cl("nok", "pass123"), cl("pk", "pass123"), cl("buyer", "pass123")

it = boss.post("/api/inv/items", json={"name_zh": "胶带", "category": "pack", "unit": "卷"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": it["id"], "qty": 5, "unit_cost": 10}], "期初", "t")
sup = boss.post("/api/inv/suppliers", json={"name": "S"}).get_json()
sid = (sup.get("supplier") or sup).get("id")
boss.post("/api/inv/po", json={"supplier_id": sid, "lines": [{"item_id": it["id"], "qty": 10, "unit_cost": 5}]})

def walk(o, acc):
    if isinstance(o, dict):
        for k, v in o.items(): acc.add(k); walk(v, acc)
    elif isinstance(o, list):
        for v in o: walk(v, acc)
    return acc
MONEY = {"avg_cost", "value", "unit_cost", "amount", "total", "paid", "unpaid", "month_paid", "goods_total"}
URLS = ["/api/inv/items", f"/api/inv/items/{it['id']}", "/api/inv/moves", "/api/inv/docs", "/api/inv/po", "/api/inv/po-summary"]
for name, c in (("listing", nok), ("production", pk)):
    leak = {u: sorted(walk(c.get(u).get_json(), set()) & MONEY) for u in URLS}
    ok(not any(leak.values()), f"{name}: no money fields {leak}")
    ok(c.get("/api/inv/expense").status_code == 403, f"{name}: expense report forbidden")
r = nok.get("/api/inv/items").get_json()
ok(r["items"] and "qty" in r["items"][0], "listing still sees quantities")
ok("avg_cost" in boss.get("/api/inv/items").get_json()["items"][0], "owner sees cost")
ok("avg_cost" in buyer.get("/api/inv/items").get_json()["items"][0] and "total" in buyer.get("/api/inv/po").get_json()["po"][0],
   "staff with inv.in (purchasing) sees cost and PO totals")
ok(buyer.get("/api/inv/expense").status_code == 200, "inv.in staff can open expense report")
boss.post("/api/spools", json={"material": "PLA", "color": "白色", "count": 1, "price": 450})
sp = pk.get("/api/spools").get_json()
ok("price" not in walk(sp, set()), "production: spool price hidden")
code = db.conn().execute("SELECT code FROM spools ORDER BY rowid DESC LIMIT 1").fetchone()[0]
if True:
    r = pk.post(f"/api/spools/{code}/weigh", json={"grams": 900})
    ok("price" not in walk(r.get_json(), set()), f"production: spool action response hides price ({r.status_code})")

# ---- 9 订单操作记录
sku = next(v["sku"] for x in store.list_products() for v in (store.load(x["id"]).get("variants") or []) if v.get("sku"))
o = boss.post("/api/orders/manual", json={"order_no": "LOG1", "order_total": 300, "items": [{"sku": sku, "qty": 1, "unit_price": 300}]}).get_json()
boss.post(f"/api/orders/{o['id']}/edit", json={"order_total": 280, "platform_fee": 15.5})
from core import orders
orders.log(o["id"], "boss", "售后验货", "入库 0 个，报废 1 个（损失约 ฿120.5）")
for name, c in (("listing", nok), ("production", pk)):
    lg = c.get(f"/api/orders/{o['id']}").get_json()["log"]
    txt = " ".join(f"{x['action']}:{x['detail']}" for x in lg)
    ok("280" not in txt and "15.5" not in txt and "120.5" not in txt, f"{name}: order log hides money ({txt[:120]})")
lg = boss.get(f"/api/orders/{o['id']}").get_json()["log"]
ok(any("280" in (x["detail"] or "") for x in lg), "owner sees money in order log")

# ---- 8 售后不能绕过取消权限
boss.post(f"/api/users/{nok_id}", json={"perms": dict(pn, **{"orders.cancel": False})})
nok = cl("nok", "pass123")
o2 = boss.post("/api/orders/manual", json={"order_no": "AS1", "items": [{"sku": sku, "qty": 1, "unit_price": 100}]}).get_json()
r = nok.post("/api/aftersales", json={"order_id": o2["id"], "kind": "return", "reason": "拒收", "status": "delivery_failed"})
st = db.conn().execute("SELECT status FROM orders WHERE id=?", (o2["id"],)).fetchone()["status"]
ok(r.status_code == 403 and st == "to_ship", f"aftersales cannot set delivery_failed without orders.cancel ({r.status_code}, {st})")
r = nok.post("/api/aftersales", json={"order_id": o2["id"], "kind": "return", "reason": "退货", "status": "returned"})
ok(r.status_code == 403, f"aftersales cannot set returned without orders.cancel ({r.status_code})")
r = nok.post("/api/aftersales", json={"order_id": o2["id"], "kind": "other", "reason": "问问题"})
ok(r.status_code == 200, "aftersales without status change still allowed")
print("ERRORS", E_)
