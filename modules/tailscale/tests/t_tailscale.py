# 外网自动加入（Tailscale）模块：设置、访问规则、客户端取密钥、加入结果、关掉模块、密钥不外泄
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, json, threading, http.server
D = T + "/m_tailscale"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, desktop
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("nok", "secret123", "listing", "Nok")
cb, cn, C = A.app.test_client(), A.app.test_client(), A.app.test_client()
cb.post("/api/auth/login", json={"username": "boss", "password": "secret123"}); cn.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
st = cb.get("/api/m/tailscale/status").get_json()
ok(not st["key_set"] and st["tag"] == "tag:3dops" and st["auto"], f"defaults {st['key_set']} {st['tag']}")
ok(cn.get("/api/m/tailscale/status").status_code == 403, "staff can't see status")
sch = {m["id"]: m for m in cb.get("/api/settings/schema").get_json()["modules"]}
ok(any(g["title"] == "外网自动加入（Tailscale）" for g in sch["general"]["groups"]), "settings under 通用")
cb.post("/api/system/remote", json={"remote_url": "http://100.81.34.58:8790"})
cb.post("/api/config", json={"ts_authkey": "tskey-auth-ABC123"})
ok(cb.get("/api/config").get_json()["config"]["ts_authkey"] == "******", "auth key masked")
st = cb.get("/api/m/tailscale/status").get_json()
ok(st["key_set"] and st["key_ok"] and st["nas"] == "100.81.34.58:8790", f"status {st['nas']}")
ok('"tag:3dops": ["autogroup:admin"]' in st["acl"] and '"dst": ["100.81.34.58:8790"]' in st["acl"] and "autogroup:member" in st["acl"], "acl policy")
# 客户端：用配对后的电脑加速密钥拿预授权密钥
rp = cn.post("/api/desktop/pair", json={"device_id": "n" * 32, "device_name": "NOK-PC"}).get_json()
H = {"Authorization": "Bearer " + rp["key"]}
ok(C.get("/api/v1/accel/tailscale").status_code == 401, "needs key")
r = C.get("/api/v1/accel/tailscale", headers=H).get_json()
ok(r["authkey"] == "tskey-auth-ABC123" and r["tag"] == "tag:3dops" and r["auto"], "client gets auth key")
ok(any("Tailscale" in (a.get("action") or "") for a in db.conn().execute("select action from audit").fetchall() and [dict(x) for x in db.conn().execute("select action from audit")]), "audited")
C.post("/api/v1/accel/tailscale/joined", headers=H, json={"ok": True, "ips": ["100.64.1.2", "fd7a::1", "bad ip!"], "msg": ""})
j = cb.get("/api/m/tailscale/status").get_json()["joins"]
ok(j and j[0]["name"] == "Nok@NOK-PC" and j[0]["ok"] and j[0]["ips"] == ["100.64.1.2", "fd7a::1"], f"join recorded {j}")
# 别的密钥（只读 / 完整）拿不到
from core import integrations
rk = integrations.create_key("只读", "read")
ok(C.get("/api/v1/accel/tailscale", headers={"Authorization": "Bearer " + rk}).status_code == 403, "read key refused")
# 关掉模块
cb.post("/api/modules/tailscale", json={"on": False})
ok(C.get("/api/v1/accel/tailscale", headers=H).status_code == 404 and cb.get("/api/m/tailscale/status").status_code == 404, "disabled → 404")
sch = {m["id"]: m for m in cb.get("/api/settings/schema").get_json()["modules"]}
ok(not any(g["title"] == "外网自动加入（Tailscale）" for g in sch["general"]["groups"]), "disabled → settings hidden")
cb.post("/api/modules/tailscale", json={"on": True})
config.save_config({"ts_authkey": ""})
ok(C.get("/api/v1/accel/tailscale", headers=H).status_code == 404, "no key → 404 with reason")
# 客户端 tsjoin（这里不是 Windows：只测不会弹窗的路径）
sys.path.insert(0, os.path.join(APP, "desktop"))
import tsjoin
ok(tsjoin.status() == {"installed": False, "running": False, "ips": []}, "status without tailscale")
from werkzeug.serving import make_server
ws = make_server("127.0.0.1", 0, A.app, threaded=True); threading.Thread(target=ws.serve_forever, daemon=True).start()
nas = f"http://127.0.0.1:{ws.server_port}"
r = tsjoin.join(nas, rp["key"], "x")
ok(not r["ok"] and "预授权密钥" in r["error"], f"join: no key on NAS {r}")
config.save_config({"ts_authkey": "tskey-auth-ABC123", "ts_auto": False})
r = tsjoin.join(nas, rp["key"], "x", require_auto=True)
ok(r.get("skip"), f"auto off → skip {r}")
ws.shutdown()
print("ERRORS", E_)
