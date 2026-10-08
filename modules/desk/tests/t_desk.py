# 桌面客户端模块（v2.30）：开着能配对 / 下载；关掉后接口 404、菜单卡片不出现，但「浏览器 + 加速器」照常能用
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, zipfile
D = T + "/m_desk"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, desktop, modules
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("nok", "secret123", "production", "Nok")
cb, cn, C = A.app.test_client(), A.app.test_client(), A.app.test_client()
cb.post("/api/auth/login", json={"username": "boss", "password": "secret123"}); cn.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
ms = {m["id"]: m for m in cb.get("/api/modules?all=1").get_json()["modules"]}
ok(ms["desk"]["enabled"] and ms["desk"]["ui"]["boot_js"] == ["boot.js"] and ms["desk"]["settings_cards"] == ["addons"], "desk module listed")
ok(C.get("/m/desk/boot.js").status_code in (200, 401, 302) and cb.get("/m/desk/boot.js").status_code == 200, "boot.js served")
r = cn.post("/api/desktop/pair", json={"device_id": "d" * 32, "device_name": "NOK-PC"})
ok(r.status_code == 200 and r.get_json()["key"], "production staff can pair")
ok(desktop.user_of_key(desktop.key_name("nok", "d" * 32)) == "nok", "device registered in kernel")
ok(cn.get("/api/desktop/devices").status_code == 403 and cb.get("/api/desktop/devices").get_json()["devices"][0]["pc"] == "NOK-PC", "devices owner only")
z = cn.get("/api/desktop/package")
ok(z.status_code == 200 and any(n.endswith("Install.bat") for n in zipfile.ZipFile(io.BytesIO(z.data)).namelist()), "package download")
ok(C.get("/api/desktop/dl/nope").status_code == 404, "dl token public but checked")
# 关掉
ok(cb.post("/api/modules/desk", json={"on": False}).get_json()["ok"], "turn off")
ok(cn.post("/api/desktop/pair", json={"device_id": "e" * 32}).status_code == 404 and cb.get("/api/desktop/package").status_code == 404, "apis 404 when off")
ok("desk" not in [m["id"] for m in cn.get("/api/modules").get_json()["modules"]], "not in listing when off")
z = cn.get("/api/accel/package?personal=1")
ok(z.status_code == 200 and any(n.endswith("worker.json") for n in zipfile.ZipFile(io.BytesIO(z.data)).namelist()), "personal accelerator still works")
cb.post("/api/modules/desk", json={"on": True})
ok(cb.get("/api/desktop/devices").status_code == 200, "back on")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
