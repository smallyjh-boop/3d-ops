# Lazada（v2.41.2）：自己填 https 回调地址；粘贴授权后的整个网址也能换 token；回调地址可以不填；付款方式 / 代收货款 / 快递；取面单
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, urllib.parse, json
D = T + "/m_link2412"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, integrations, connectors
from core.connectors import lazada as LZ
db.create_user("boss", "secret123", "owner", "Boss")
cb = A.app.test_client()
cb.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
cn = next(c for c in cb.get("/api/integrations").get_json()["connectors"] if c["platform"] == "lazada")
ok("callback_url" in [f["key"] for f in cn["fields"]], "callback field shown")
sid = cb.post("/api/shops", json={"platform": "lazada", "name": "LZ", "creds": {"app_key": "K1", "app_secret": "S1",
              "callback_url": " https://www.google.com/ "}}).get_json()["id"]
u = cb.post(f"/api/shops/{sid}/auth-url", json={"redirect": "http://192.168.31.200:8790/"}).get_json()["url"]
q = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)
ok(q["redirect_uri"] == ["https://www.google.com/"] and q["client_id"] == ["K1"], f"auth url uses callback {q}")
# 没填回调地址：照旧用系统自己的地址
sid2 = cb.post("/api/shops", json={"platform": "lazada", "name": "LZ2", "creds": {"app_key": "K2", "app_secret": "S2"}}).get_json()["id"]
u2 = cb.post(f"/api/shops/{sid2}/auth-url", json={"redirect": "http://192.168.31.200:8790/"}).get_json()["url"]
ok("redirect_uri=http%3A%2F%2F192.168.31.200%3A8790%2F" in u2, "default redirect")
# 粘贴整个网址 / 只填 code / code= 开头
for raw, want in [("https://www.google.com/?code=0_123_AbC&state=x#frag", "0_123_AbC"), ("  0_9_Z  ", "0_9_Z"),
                  ("code=0_5_Q&foo=1", "0_5_Q")]:
    ok(integrations._auth_code(raw) == want, f"auth code {raw!r}")
seen = {}
def fake_call(self, path, params, base=LZ.API, token=True, method="GET"):
    seen["path"], seen["code"] = path, params.get("code")
    return {"code": "0", "access_token": "AT", "refresh_token": "RT", "expires_in": 3600, "refresh_expires_in": 7200}
LZ.LazadaConnector._call = fake_call
r = cb.post(f"/api/shops/{sid}/auth-code", json={"code": "https://www.google.com/?code=0_777_X"})
ok(r.status_code == 200 and seen == {"path": "/auth/token/create", "code": "0_777_X"}, f"exchange {seen}")
cr = integrations.get_shop_raw(sid)["creds"]
ok(cr["access_token"] == "AT" and cr["refresh_token"] == "RT" and cr["callback_url"] == "https://www.google.com/", "tokens saved")
# 回调地址不填也不算缺
c = connectors.make("lazada", {"app_key": "a", "app_secret": "b", "access_token": "c", "refresh_token": "d"})
try:
    c.check(); ok(True, "callback optional")
except connectors.NotReady as e:
    ok(False, f"callback optional {e}")
try:
    connectors.make("lazada", {"app_key": "a", "app_secret": "b"}).check(); ok(False, "token still required")
except connectors.NotReady as e:
    ok("Access Token" in str(e) and "Callback" not in str(e), f"token still required {e}")
# 订单：付款方式、代收货款、快递、包裹号
o = LZ.LazadaConnector({}).convert({"order_id": 1134620956753716, "order_number": 1134620956753716, "statuses": ["packed"],
                                    "created_at": "2026-10-31 12:14:00 +0700", "price": "108.00", "payment_method": "COD"},
                                   [{"sku": "A00001", "item_price": "108", "paid_price": "108", "tracking_code": "LEXDO0190000384",
                                     "shipment_provider": "FM 3PL: LEX TH", "package_id": "FP001"}])
ok(o["status"] == "to_ship" and o["payment"] == "COD" and o["cod"] == "108.00" and o["carrier"] == "FM 3PL: LEX TH"
   and o["tracking_no"] == "LEXDO0190000384" and o["raw"]["packages"] == ["FP001"], f"convert {o}")
o = LZ.LazadaConnector({}).convert({"order_id": 2, "statuses": ["pending"], "price": "50", "payment_method": "MIXEDCARD"}, [])
ok(o["cod"] is None and o["payment"] == "MIXEDCARD", "not cod")
# 面单：现取包裹号 → 按包裹取 PDF
calls = []
def fake_call2(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    calls.append((path, params, method))
    if path == "/orders/items/get":
        pk = {} if params["order_ids"] == "[3]" else {"package_id": "FP001"}
        return {"code": "0", "data": [{"order_id": int(json.loads(params["order_ids"])[0]),
                                       "order_items": [{"order_item_id": 31, "tracking_code": "" if pk == {} else "LEX9", **pk},
                                                       {"order_item_id": 32, "tracking_code": "" if pk == {} else "LEX9", **pk}]}]}
    if path == "/order/fulfill/pack":
        req = json.loads(params["packReq"])
        return {"code": "0", "result": {"success": "true", "data": {"pack_order_list": [{"order_id": req["pack_order_list"][0]["order_id"],
                "order_item_list": [{"order_item_id": i, "item_err_code": "0", "msg": "success", "tracking_number": "TH-NEW-1",
                                     "package_id": "FP-NEW", "shipment_provider": "LEX TH"} for i in req["pack_order_list"][0]["order_item_list"]]}]}}}
    return {"code": "0", "result": {"success": True, "data": {"pdf_url": "https://lz.example/x.pdf"}}}
class R:
    content = b"%PDF-1.4 fake"
    def raise_for_status(self): pass
LZ.LazadaConnector._call = fake_call2
LZ.requests.get = lambda url, timeout=0: R()
lc = LZ.LazadaConnector({"app_key": "a", "app_secret": "b", "access_token": "c", "refresh_token": "d"})
doc = lc.fetch_label({"order_no": "999", "raw": {"order_id": 1134620956753716}})
req = json.loads(calls[-1][1]["getDocumentReq"])
ok(doc == {"kind": "pdf", "data": b"%PDF-1.4 fake", "tracking_no": "LEX9", "packed": False} and calls[0][1]["order_ids"] == "[1134620956753716]"
   and calls[-1][0] == "/order/package/document/get" and calls[-1][2] == "POST"
   and req["packages"] == [{"package_id": "FP001"}] and req["doc_type"] == "PDF", f"fetch label {calls}")
# v2.44.1：还没打包 → 和卖家中心「打包 & 打印」一样，先在 Lazada 打包再取面单
calls.clear()
doc = lc.fetch_label({"order_no": "3", "raw": {}})
pk = next((json.loads(c[1]["packReq"]) for c in calls if c[0] == "/order/fulfill/pack"), None)
req = json.loads(calls[-1][1]["getDocumentReq"])
ok(pk and pk["pack_order_list"][0]["order_id"] == "3" and pk["pack_order_list"][0]["order_item_list"] == ["31", "32"]
   and pk["shipping_allocate_type"] == "TFS" and req["packages"] == [{"package_id": "FP-NEW"}]
   and doc["tracking_no"] == "TH-NEW-1" and doc["packed"], f"pack then print {doc} {pk}")
def pack_fail(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    if path == "/order/fulfill/pack":
        return {"code": "0", "result": {"success": "true", "data": {"pack_order_list": [{"order_item_list": [{"item_err_code": "700026", "msg": "item current status not allow to pack"}]}]}}}
    return fake_call2(self, path, params, base, token, method)
LZ.LazadaConnector._call = pack_fail
try:
    lc.fetch_label({"order_no": "3", "raw": {}}); ok(False, "pack fail")
except RuntimeError as e:
    ok("打包失败" in str(e) and "not allow" in str(e), f"pack fail explained {e}")
LZ.LazadaConnector._call = fake_call2
LZ.LazadaConnector._call = lambda *a, **k: {"code": "0", "data": [{"order_id": 5, "order_items": [{"package_id": "P"}]}]} \
    if a[1] == "/orders/items/get" else {"code": "0", "result": {"success": False, "error_msg": "package not ready"}}
try:
    lc.fetch_label({"order_no": "5"}); ok(False, "lazada error")
except RuntimeError as e:
    ok("package not ready" in str(e), f"lazada error {e}")
# v2.44.1：ERP 里标「已发货」→ Lazada「安排发货」；平台同步回来的不调
from core import orders as orders_mod, chain
LZ.LazadaConnector._call = fake_call2
db.conn().execute("DELETE FROM shops"); db.conn().commit()
integrations.save_shop({"platform": "lazada", "name": "LZ", "enabled": True, "creds": {"app_key": "a", "app_secret": "b", "access_token": "c", "refresh_token": "d"}})
orders_mod.upsert([{"platform": "lazada", "shop": "LZ", "order_no": "RTS-1", "status": "to_ship", "items": [{"sku": "X", "qty": 1}],
                    "raw": {"order_id": 777}}], source="test")
oid = db.conn().execute("SELECT id FROM orders WHERE order_no='RTS-1'").fetchone()["id"]
calls.clear()
C2 = A.app.test_client(); C2.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
C2.post("/api/orders/batch", json={"ids": [oid], "action": "status", "value": "shipped"})
rts = [json.loads(c[1]["readyToShipReq"]) for c in calls if c[0] == "/order/package/rts"]
ok(rts == [{"packages": [{"package_id": "FP001"}]}], f"RTS when marked shipped in ERP {rts}")
ok(any(x["action"] == "Lazada 安排发货" for x in orders_mod.get_log(oid)), "order log")
calls.clear()
orders_mod.upsert([{"platform": "lazada", "shop": "LZ", "order_no": "RTS-2", "status": "to_ship", "items": [{"sku": "X", "qty": 1}], "raw": {"order_id": 778}}], source="test")
orders_mod.upsert([{"platform": "lazada", "shop": "LZ", "order_no": "RTS-2", "status": "shipped", "items": [{"sku": "X", "qty": 1}], "raw": {"order_id": 778}}], source="sync")
ok(not any(c[0] == "/order/package/rts" for c in calls), "platform sync does not call RTS")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
