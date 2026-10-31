# 店铺设置表单（v2.49）：连接器的分组元数据（FORM_GROUPS / fields[].group）和接口、旧代码读 FIELDS 的方式保持一致
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, time
D = T + "/m_link249"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
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
desc = {c["platform"]: c for c in cb.get("/api/integrations").get_json()["connectors"]}
ok(set(desc) == set(connectors.REGISTRY), "every connector described")
for p, c in desc.items():
    cls = connectors.REGISTRY[p]
    # 旧代码按 (键, 名称, 保密) 三项读 FIELDS（check、_secret_keys）：不能变
    ok(all(len(t) == 3 for t in cls.FIELDS), f"{p}: FIELDS still 3-tuples")
    ok([f["key"] for f in c["fields"]] == [k for k, _l, _s in cls.FIELDS], f"{p}: fields order = FIELDS")
    slots = {g["slot"] for g in c["groups"]} | {"common"}
    ok(c["groups"] and all(f["group"] in slots for f in c["fields"]), f"{p}: every field in a known group")
    for f in c["fields"]:
        g = next((x for x in c["groups"] if x["slot"] == f["group"]), None)
        if g:
            ok(f["key"] == (g.get("prefix") or "") + f["base"], f"{p}.{f['key']}: base = key minus group prefix")
        ok(f["token"] == (f["base"] in ("access_token", "refresh_token")), f"{p}.{f['key']}: token flag")
        ok(f["secret"] == dict((k, s) for k, _l, s in cls.FIELDS)[f["key"]], f"{p}.{f['key']}: secret flag")
    for f in c["fields"]:
        if f["token"]:
            ok(f["key"] in integrations._secret_keys(p), f"{p}.{f['key']}: tokens are masked")
lz = desc["lazada"]
g = {x["slot"]: x for x in lz["groups"]}
ok(list(g) == ["", "im", "data", "ads"], f"lazada groups {list(g)}")
ok(set(g) - {""} == set(LZ.LazadaConnector.APP_SLOTS), "groups match APP_SLOTS")
ok(not g[""].get("more") and not g["im"].get("more") and g["data"].get("more") and g["ads"].get("more"), "data / ads collapsed")
ok("Product Review" in g[""]["help"], "main app tip mentions Product Review")
by = {f["key"]: f for f in lz["fields"]}
ok(by["callback_url"]["group"] == "common", "callback in basics row")
ok(by["app_key"]["group"] == "" and by["im_app_key"]["group"] == "im" and by["ads_refresh_token"]["group"] == "ads", "prefix grouping")
ok(by["im_app_key"]["base"] == "app_key" and by["data_access_token"]["token"], "base / token")
for slot in ("im", "data", "ads"):
    ok({f["base"] for f in lz["fields"] if f["group"] == slot} == {"app_key", "app_secret", "access_token", "refresh_token"}, f"{slot} has 4 fields")
# 没写 FORM_GROUPS 的平台：一组
ok([x["slot"] for x in desc["tiktok"]["groups"]] == [""] and all(f["group"] == "" for f in desc["tiktok"]["fields"]), "tiktok single group")
# 店铺接口：保密项打码；每个应用的到期时间
sid = cb.post("/api/shops", json={"platform": "lazada", "name": "LZ", "creds": {"app_key": "K", "app_secret": "S",
              "im_app_key": "IK", "im_app_secret": "IS"}}).get_json()["id"]
seen = []
def fake_call(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    seen.append((path, self.creds.get("app_key")))
    return {"code": "0", "access_token": "AT-" + self.creds.get("app_key"), "refresh_token": "RT", "expires_in": 3600, "refresh_expires_in": 86400}
LZ.LazadaConnector._call = fake_call
r = cb.post(f"/api/shops/{sid}/auth-code", json={"code": "https://www.google.com/?code=0_1_X", "app": "im"})
ok(r.status_code == 200 and seen == [("/auth/token/create", "IK")], f"im exchange {seen}")
shop = next(s for s in cb.get("/api/integrations").get_json()["shops"] if s["id"] == sid)
ok(shop["creds"]["im_access_token"] == "******" and shop["creds"]["im_app_secret"] == "******" and shop["creds"]["im_app_key"] == "IK", "masked")
ok(not shop["creds"].get("access_token"), "main app untouched")
ex = shop["expires"]
ok(time.time() < ex.get("im_token_expire", 0) < time.time() + 4000 and ex.get("im_refresh_expire", 0) > time.time() + 80000, f"im expiry {ex}")
ok(not any(k.endswith(("token_expire", "refresh_expire")) for k in shop["creds"]), "expiry not in creds")
# 保存时 ****** 不覆盖
cb.post("/api/shops", json={"id": sid, "platform": "lazada", "name": "LZ", "creds": {k: v for k, v in shop["creds"].items()}})
ok(integrations.get_shop_raw(sid)["creds"]["im_access_token"] == "AT-IK", "****** keeps token")
# 界面代码用的是这些字段（防止改名后表单对不上）
js = open(os.path.join(APP, "modules/link/ui/settings.js"), encoding="utf-8").read()
for frag in ("f.group", "f.token", "f.base", "g.prefix", "g.more", "shop.expires", "data-authurl", "data-authcode", "/auth-url", "/auth-code"):
    ok(frag in js, f"settings.js uses {frag}")
th = json.load(open(os.path.join(APP, "modules/link/i18n/th.json"), encoding="utf-8"))
for x in lz["groups"]:
    for k in ("title", "for", "help"):
        ok(x[k] in th, f"th: {x[k][:20]}")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
