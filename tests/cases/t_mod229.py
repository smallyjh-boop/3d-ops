# v2.29：模块框架——发现、开关、依赖、菜单、权限、设置、密钥、翻译、事件、页面文件、出错隔离
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, json
D = T + "/v229"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
os.environ["LH_EXTRA_MODULES"] = os.path.join(APP, "tests", "fixtures", "demomods")
os.environ.pop("LH_NO_MODULE_STARTUP", None)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import time
import app as A
from core import modules, config, db, settings_schema
from demomods.demo import module as demo_mod
from demomods.demo2 import module as demo2_mod
C = A.app.test_client()
ids = {m["id"]: m for m in C.get("/api/modules?all=1").get_json()["modules"]}
ok("demo" in ids and "demo2" in ids and "tailscale" in ids and "Bad_Name" not in ids, f"discover {sorted(ids)}")
ok(ids["broken"]["error"] and not ids["broken"]["enabled"], f"broken module isolated: {ids['broken']['error'][:60]}")
ok(ids["demo"]["enabled"] and not ids["demo2"]["enabled"], "default_on respected")
ok(ids["demo"]["menus"][0]["tab"] == "demo_page" and ids["demo"]["ui"] == {"html": True, "js": True, "css": False}, "menus + ui files")
time.sleep(0.5)
ok(("startup",) in demo_mod.CALLS, "startup ran")
# 接口、权限
ok(C.get("/api/m/demo/hello").get_json() == {"hi": "demo"}, "module api (no users yet = no login)")
db.create_user("nok", "secret123", "listing", "Nok"); db.create_user("boss", "secret123", "owner", "Boss")
cn, cb = A.app.test_client(), A.app.test_client()
cn.post("/api/auth/login", json={"username": "nok", "password": "secret123"}); cb.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
ok(cn.post("/api/m/demo/secret").status_code == 403 and cb.post("/api/m/demo/secret").status_code == 200, "module owner_only rule")
ok(cn.post("/api/modules/demo", json={"on": False}).status_code == 403, "staff can't toggle modules")
# 设置、默认值、密钥
sch = {m["id"]: m for m in cb.get("/api/settings/schema").get_json()["modules"]}
ok(any(g["title"] == "演示设置" for g in sch["general"]["groups"]), "module settings in schema")
ok(config.load_config()["demo_x"] == 5, "config defaults")
cb.post("/api/config", json={"demo_key": "s3cret"})
ok(cb.get("/api/config").get_json()["config"]["demo_key"] == "******" and config.load_config()["demo_key"] == "s3cret", "module secret masked")
# 翻译、页面文件
html = cb.get("/").get_data(as_text=True)
ok('"演示页面": "หน้าสาธิต"' in html, "module i18n injected")
ok(cb.get("/m/demo/page.js").status_code == 200 and cb.get("/m/demo/page.css").status_code == 404 and cb.get("/m/demo/../app.py").status_code == 404, "ui files served safely")
ok(C.get("/m/demo/page.html").status_code in (401, 302), "ui files need login")
# 事件：开着的模块收到；出错的不影响别的
r = modules.emit("order.shipped", order_id=7)
ok(r == {"demo": "ok"} and demo_mod.CALLS[-1] == ("demo", 7) and demo2_mod.CALLS == [], f"emit to enabled only {r}")
ok(cb.post("/api/modules/demo2", json={"on": True}).status_code == 200, "enable demo2")
r = modules.emit("order.shipped", order_id=8)
ok(r["demo"] == "ok" and "error" in r["demo2"] and demo2_mod.CALLS == ["demo2"], f"failing handler isolated {r}")
ok(any(e["module"] == "demo2" and e["error"] for e in cb.get("/api/modules/events?errors=1").get_json()["events"]), "event errors logged")
# 关掉：接口 404、菜单不显示、设置不显示、依赖它的一起停
rr = cb.post("/api/modules/demo", json={"on": False}).get_json()
ok(rr["also_off"] == ["demo2"], f"dependents reported {rr}")
ok(cb.get("/api/m/demo/hello").status_code == 404 and "模块没有打开" in cb.get("/api/m/demo/hello").get_json()["error"], "disabled api 404")
ok(cb.get("/m/demo/page.js").status_code == 404, "disabled ui 404")
lst = {m["id"]: m for m in cb.get("/api/modules").get_json()["modules"]}
ok("demo" not in lst and "demo2" not in lst, "disabled not in menu listing")
sch = {m["id"]: m for m in cb.get("/api/settings/schema").get_json()["modules"]}
ok(not any(g["title"] == "演示设置" for g in sch["general"]["groups"]), "disabled settings hidden")
ok(modules.emit("order.shipped", order_id=9) == {}, "disabled gets no events")
er = cb.post("/api/modules/demo2", json={"on": True})
ok(er.status_code == 400 and "依赖" in er.get_json()["error"], "can't enable without dependency")
cb.post("/api/modules/demo", json={"on": True})
ok(cb.get("/api/m/demo/hello").status_code == 200, "re-enabled works without restart")
ok(cb.post("/api/modules/nope", json={"on": True}).status_code == 400, "unknown module")
# 员工只看到自己角色能用的菜单
db.create_user("pp", "secret123", "production", "PP")
cp = A.app.test_client(); cp.post("/api/auth/login", json={"username": "pp", "password": "secret123"})
pl = {m["id"]: m for m in cp.get("/api/modules").get_json()["modules"]}
ok(cp.get("/api/modules").status_code == 200 and pl["demo"]["menus"] == [], "production role: no demo menu")
print("ERRORS", E_)
