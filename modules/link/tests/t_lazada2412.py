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
def fake_call2(self, path, params, base=LZ.API, token=True, method="GET"):
    calls.append((path, params, method))
    if path == "/orders/items/get":
        pk = {} if params["order_ids"] == "[3]" else {"package_id": "FP001"}
        return {"code": "0", "data": [{"order_id": int(json.loads(params["order_ids"])[0]),
                                       "order_items": [{"tracking_code": "LEX9", **pk}, {"tracking_code": "LEX9", **pk}]}]}
    return {"code": "0", "result": {"success": True, "data": {"pdf_url": "https://lz.example/x.pdf"}}}
class R:
    content = b"%PDF-1.4 fake"
    def raise_for_status(self): pass
LZ.LazadaConnector._call = fake_call2
LZ.requests.get = lambda url, timeout=0: R()
lc = LZ.LazadaConnector({"app_key": "a", "app_secret": "b", "access_token": "c", "refresh_token": "d"})
doc = lc.fetch_label({"order_no": "999", "raw": {"order_id": 1134620956753716}})
req = json.loads(calls[-1][1]["getDocumentReq"])
ok(doc == {"kind": "pdf", "data": b"%PDF-1.4 fake", "tracking_no": "LEX9"} and calls[0][1]["order_ids"] == "[1134620956753716]"
   and calls[-1][0] == "/order/package/document/get" and calls[-1][2] == "POST"
   and req["packages"] == [{"package_id": "FP001"}] and req["doc_type"] == "PDF", f"fetch label {calls}")
try:
    lc.fetch_label({"order_no": "3", "raw": {}}); ok(False, "not packed")
except connectors.NotReady as e:
    ok("打包" in str(e), f"not packed {e}")
LZ.LazadaConnector._call = lambda *a, **k: {"code": "0", "data": [{"order_id": 5, "order_items": [{"package_id": "P"}]}]} \
    if a[1] == "/orders/items/get" else {"code": "0", "result": {"success": False, "error_msg": "package not ready"}}
try:
    lc.fetch_label({"order_no": "5"}); ok(False, "lazada error")
except RuntimeError as e:
    ok("package not ready" in str(e), f"lazada error {e}")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
