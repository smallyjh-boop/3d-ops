# Lazada 授权（v2.41.2）：自己填 https 回调地址；粘贴授权后的整个网址也能换 token；回调地址可以不填
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, urllib.parse
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
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
