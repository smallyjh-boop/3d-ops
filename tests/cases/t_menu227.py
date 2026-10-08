# v2.27：菜单整理——设置按大分类、每张卡片单独保存（只发这张卡片的字段）、组件与插件
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D = T + "/v227"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import config
C = A.app.test_client()
sc = C.get("/api/settings/schema").get_json()["modules"]
ids = [m["id"] for m in sc]
ok(ids == ["general", "modules", "accounts", "cost", "goods", "orders", "cs", "production", "inventory", "finance", "ai", "addons"], f"modules {ids}")
by = {m["id"]: m for m in sc}
ok(by["addons"]["special"] == ["desktop", "components", "accel"] and any(f["key"] == "accel_on" for g in by["addons"]["groups"] for f in g["fields"]), "addons has accel + components")
ok("remote" in by["general"]["special"] and not any(f["key"] == "remote_url" for g in by["general"]["groups"] for f in g["fields"]), "remote card instead of field")
ok(all(by[x]["ext"] for x in ("accounts", "goods", "cs", "production", "ai", "addons")), "ext modules flagged")
# 一张卡片单独保存：只改这几个，其它不动
before = config.load_config()
r = C.post("/api/config", json={"sku_prefix": "ABC", "brand": "MyBrand"})
after = config.load_config()
ok(r.status_code == 200 and after["sku_prefix"] == "ABC" and after["brand"] == "MyBrand", "card save")
ok(all(after[k] == before[k] for k in before if k not in ("sku_prefix", "brand")), "other settings untouched")
info = C.get("/api/cs/extension/info").get_json()
from core import integrations
ok(info["latest"] == integrations.EXT_LATEST and isinstance(info["in_use"], list), f"extension info {info}")
html = C.get("/").get_data(as_text=True)
ok('data-tab="users"' not in html and 'data-tab="csext"' not in html, "old menu tabs removed")
ok(all(f'data-cfgext="{x}"' in html for x in ("accounts", "goods", "cs", "production", "ai", "addons")), "moved blocks in settings")
ok('id="users-table"' in html and 'id="intg-keys"' in html and 'id="cur-url"' in html and 'id="tpl-list"' in html and 'id="cskb-settings"' in html, "moved elements present")
print("ERRORS", E_)
