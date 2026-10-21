# v2.38：AI 接待密钥（scope = chat，系统一 ai-sales-desk 用）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys
os.environ["LH_DATA_DIR"] = T + "/vo"; sys.path.insert(0, APP)
import app as A
from core import db
try: db.create_user("boss", "secret1", "owner", "boss", "zh")
except Exception: pass
c = A.app.test_client(); c.post("/api/auth/login", json={"username": "boss", "password": "secret1"})
ck = c.post("/api/apikeys", json={"name": "AI接待", "scope": "chat"}).get_json()["key"]
fk = c.post("/api/apikeys", json={"name": "推送2", "scope": "full"}).get_json()["key"]
wk = c.post("/api/apikeys", json={"name": "批发站2", "scope": "wholesale"}).get_json()["key"]
x = A.app.test_client(); H = lambda k: {"Authorization": "Bearer " + k}

# 1. SKU：有售价、库存，没有成本 / 底价
skus = x.get("/api/v1/skus", headers=H(ck)).get_json()["skus"]
assert skus, "没有 SKU"
s0 = skus[0]
for k in ("unit_cost", "floor_price", "suggested_price", "manual_price", "hours"):
    assert k not in s0, k
for k in ("sku", "price", "stock"):
    assert k in s0, k
assert x.get("/api/v1/ping", headers=H(ck)).status_code == 200

# 2. 推单：平台强制为 chat；不能借这把密钥改 Lazada / 批发订单
assert x.post("/api/v1/orders", json={"orders": [{"platform": "lazada", "order_no": "LZ-CH-1", "status": "to_ship",
                                                  "items": [{"sku": s0["sku"], "qty": 1, "unit_price": 100}]}]}, headers=H(fk)).get_json()["ok"]
r = x.post("/api/v1/orders", json={"source": "ai-sales-desk", "platform": "lazada", "orders": [
    {"platform": "lazada", "order_no": "LZ-CH-1", "status": "cancelled"},
    {"order_no": "CH-0001", "status": "to_ship", "buyer": "ลูกค้าแชท", "phone": "0812345678", "address": "Chiang Mai",
     "items": [{"sku": s0["sku"], "qty": 3, "unit_price": 120}]}]}, headers=H(ck)).get_json()
assert r["ok"], r
cdb = db.conn()
assert cdb.execute("SELECT status FROM orders WHERE platform='lazada' AND order_no='LZ-CH-1'").fetchone()["status"] != "cancelled", "AI 接待密钥改到了 Lazada 订单"
o1 = cdb.execute("SELECT * FROM orders WHERE order_no='CH-0001'").fetchone()
assert o1["platform"] == "chat" and o1["source"] == "ai-sales-desk", dict(o1)
assert cdb.execute("SELECT COUNT(*) FROM jobs WHERE order_id=?", (o1["id"],)).fetchone()[0] >= 1, "聊天订单没生成生产任务"
print("chat order", o1["platform"], o1["source"], o1["status"])

# 3. 查单：只看到 chat 订单，没有成本 / 平台费；自己客户的收货信息看得到
o = x.get("/api/v1/orders?platform=lazada&limit=1000", headers=H(ck)).get_json()["orders"]
assert o and all(i["platform"] == "chat" for i in o), [i["platform"] for i in o]
assert "cost" not in o[0] and "platform_fee" not in o[0]
assert [i for i in o if i["order_no"] == "CH-0001"][0].get("buyer") == "ลูกค้าแชท"
# 批发站密钥看不到聊天订单，反过来也一样
assert all(i["platform"] == "wholesale" for i in x.get("/api/v1/orders?limit=1000", headers=H(wk)).get_json()["orders"])

# 4. 改状态：只能改 chat 订单
assert x.post("/api/v1/orders/status", json={"order_no": "CH-0001", "status": "shipped", "tracking_no": "TH999"}, headers=H(ck)).get_json()["updated"] == 1
x.post("/api/v1/orders/status", json={"platform": "lazada", "order_no": "LZ-CH-1", "status": "cancelled"}, headers=H(ck))
assert cdb.execute("SELECT status FROM orders WHERE platform='lazada' AND order_no='LZ-CH-1'").fetchone()["status"] != "cancelled"

# 5. 别的接口一律 403（包括批发站回调、成本参数、写回、财务）
for m, p in (("get", "/api/v1/cost-params"), ("get", "/api/v1/profit"), ("get", "/api/v1/production"),
             ("get", "/api/v1/materials"), ("get", "/api/v1/cs/ping"), ("post", "/api/v1/ops/products/X"),
             ("post", "/api/v1/catalog/products"), ("get", "/api/v1/finance/summary"), ("post", "/api/v1/wholesale/hook")):
    code = getattr(x, m)(p, headers=H(ck)).status_code
    assert code == 403, (p, code)
keys = c.get("/api/integrations").get_json().get("keys", [])
assert any(k["scope"] == "chat" for k in keys), keys
print("ok chat scope")
