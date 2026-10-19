# v2.36：批发站密钥（scope = wholesale）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys
os.environ["LH_DATA_DIR"] = T + "/vo"; sys.path.insert(0, APP)
import app as A
from core import db, store, orders as om
try: db.create_user("boss", "secret1", "owner", "boss", "zh")
except Exception: pass
c = A.app.test_client(); c.post("/api/auth/login", json={"username": "boss", "password": "secret1"})
wk = c.post("/api/apikeys", json={"name": "批发站", "scope": "wholesale"}).get_json()["key"]
fk = c.post("/api/apikeys", json={"name": "推送", "scope": "full"}).get_json()["key"]
x = A.app.test_client(); H = lambda k: {"Authorization": "Bearer " + k}

# 1. SKU：有售价和库存，没有成本 / 底价
skus = x.get("/api/v1/skus", headers=H(wk)).get_json()["skus"]
assert skus, "没有 SKU"
s0 = skus[0]
for k in ("unit_cost", "floor_price", "suggested_price", "manual_price", "hours"):
    assert k not in s0, k
for k in ("sku", "price", "stock", "name", "title_th"):
    assert k in s0, k
print("skus", len(skus), sorted(s0)[:6])
img = next((s["image"] for s in skus if s.get("image")), None)
if img:   # 批发站要能下载商品图片
    r = x.get(img["url"], headers=H(wk)); assert r.status_code == 200 and r.mimetype.startswith("image/"), r.status_code

# 2. 推单：平台强制为 wholesale，不能借批发密钥改 Lazada 订单
lz = x.post("/api/v1/orders", json={"orders": [{"platform": "lazada", "order_no": "LZ-WS-1", "status": "to_ship",
                                                "items": [{"sku": s0["sku"], "qty": 1, "unit_price": 100}]}]}, headers=H(fk)).get_json()
assert lz["ok"], lz
r = x.post("/api/v1/orders", json={"orders": [
    {"platform": "lazada", "order_no": "LZ-WS-1", "status": "cancelled"},
    {"order_no": "WS-0001", "status": "to_ship", "buyer": "ร้านทดสอบ", "phone": "0812345678",
     "address": "Bangkok", "items": [{"sku": s0["sku"], "qty": 20, "unit_price": 80}]}]}, headers=H(wk)).get_json()
assert r["ok"], r
cdb = db.conn()
lz_row = cdb.execute("SELECT status FROM orders WHERE platform='lazada' AND order_no='LZ-WS-1'").fetchone()
assert lz_row["status"] != "cancelled", "批发密钥改到了 Lazada 订单"
ws = cdb.execute("SELECT * FROM orders WHERE order_no='WS-0001'").fetchone()
assert ws["platform"] == "wholesale" and ws["source"] == "wholesale", dict(ws)
jobs = cdb.execute("SELECT COUNT(*) FROM jobs WHERE order_id=?", (ws["id"],)).fetchone()[0]
print("wholesale order", ws["platform"], ws["status"], "jobs", jobs)

# 3. 查单：只看到批发订单，没有成本
o = x.get("/api/v1/orders?platform=lazada&limit=1000", headers=H(wk)).get_json()["orders"]
assert o and all(i["platform"] == "wholesale" for i in o), [i["platform"] for i in o]
assert "cost" not in o[0] and "platform_fee" not in o[0]
w1 = [i for i in o if i["order_no"] == "WS-0001"][0]
assert w1.get("buyer") == "ร้านทดสอบ" and w1["items"][0]["qty"] == 20   # 自己客户的收货信息要看得到（发货用）

# 4. 改状态：只能改批发订单
r = x.post("/api/v1/orders/status", json={"order_no": "WS-0001", "status": "shipped", "tracking_no": "TH123"}, headers=H(wk)).get_json()
assert r["updated"] == 1, r
x.post("/api/v1/orders/status", json={"platform": "lazada", "order_no": "LZ-WS-1", "status": "cancelled"}, headers=H(wk))
lz_row = cdb.execute("SELECT status FROM orders WHERE platform='lazada' AND order_no='LZ-WS-1'").fetchone()
assert lz_row["status"] != "cancelled", "批发密钥改到了 Lazada 订单状态"
r = x.post("/api/v1/orders/status", json={"order_no": "NOPE-9", "status": "cancelled"}, headers=H(wk)).get_json()
assert r["updated"] == 0 and r["not_found"] == ["NOPE-9"], r
ws = cdb.execute("SELECT status, tracking_no FROM orders WHERE order_no='WS-0001'").fetchone()
print("status", ws["status"], ws["tracking_no"])

# 5. 别的接口一律 403
for m, p in (("get", "/api/v1/cost-params"), ("get", "/api/v1/profit"), ("get", "/api/v1/production"),
             ("get", "/api/v1/materials"), ("get", "/api/v1/cs/ping"), ("post", "/api/v1/ops/products/X"),
             ("post", "/api/v1/catalog/products"), ("get", "/api/v1/finance/summary")):
    code = getattr(x, m)(p, headers=H(wk)).status_code
    assert code == 403, (p, code)
assert x.get("/api/v1/ping", headers=H(wk)).status_code == 200
print("keys", [(k["name"], k["scope"]) for k in c.get("/api/integrations").get_json().get("keys", [])][-2:])

# 4. v2.37 回调：只有批发站密钥能登记；批发订单状态变化时回调（带签名）
import hashlib, hmac, json as _json
from core import wholesale_hook
r = x.post("/api/v1/wholesale/hook", json={"url": "https://shop.test/erp/hook/", "secret": "s" * 20}, headers=H(fk))
assert r.status_code == 403, r.status_code
r = x.post("/api/v1/wholesale/hook", json={"url": "ftp://x", "secret": "s" * 20}, headers=H(wk))
assert r.status_code == 400, r.status_code
r = x.post("/api/v1/wholesale/hook", json={"url": "https://shop.test/erp/hook/", "secret": "s" * 20}, headers=H(wk))
assert r.get_json()["ok"], r.get_json()
sent = []
wholesale_hook._post = lambda url, secret, body: sent.append((url, secret, body))
import threading as _th
_orig = _th.Thread
class _Now:
    def __init__(self, target, args, daemon=True): self.t, self.a = target, args
    def start(self): self.t(*self.a)
wholesale_hook.threading.Thread = _Now
x.post("/api/v1/orders/status", json={"order_no": "WS-0001", "status": "completed"}, headers=H(wk))
wholesale_hook.threading.Thread = _orig
assert sent and sent[-1][0] == "https://shop.test/erp/hook/", sent
body = _json.loads(sent[-1][2]); assert body["order_no"] == "WS-0001" and body["status"] == "completed", body
print("hook ok", body["status"])
print("ALL OK")
