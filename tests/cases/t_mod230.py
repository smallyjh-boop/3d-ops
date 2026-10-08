# v2.30：6 个功能搬成模块（客服、财务、采购、搜索优化、对接、桌面客户端）——都能装载；逐个关掉：接口 404、菜单 / 设置消失，内核照常
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D = T + "/v230"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, modules, integrations
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("nok", "secret123", "listing", "Nok")
cb, cn = A.app.test_client(), A.app.test_client()
cb.post("/api/auth/login", json={"username": "boss", "password": "secret123"}); cn.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
ms = {m["id"]: m for m in cb.get("/api/modules?all=1").get_json()["modules"]}
SIX = ["cs", "fin", "pur", "seo", "link", "desk"]
ok(all(x in ms and ms[x]["enabled"] and not ms[x]["error"] for x in SIX), f"six modules loaded {[(x, ms.get(x, {}).get('error')) for x in SIX]}")
for mid in SIX:
    for f in (ms[mid]["ui"]["html"] and [ms[mid]["ui"]["html"]] or []) + ms[mid]["ui"]["page_js"] + ms[mid]["ui"]["boot_js"]:
        ok(cb.get(f"/m/{mid}/{f}").status_code == 200, f"ui file {mid}/{f}")
ok(cb.get("/api/cs/extension.zip").status_code == 200, "cs extension download (path after move)")
html = cb.get("/").get_data(as_text=True)
ok(not any(f'data-tab="{t}"' in html for t in ("cs", "csrec", "fin_overview", "purchase", "opschg")) and 'id="tab-cs"' not in html, "index has no module panels")
ok('data-needmod="seo"' in html and 'data-needmod="fin"' in html, "needmod markers")
# 员工看到的菜单
tabs = {mn["tab"] for m in cn.get("/api/modules").get_json()["modules"] for mn in m["menus"]}
ok({"cs", "csrec", "purchase", "opschg"} <= tabs and "fin_overview" not in tabs and "po_pay" not in tabs, f"staff menus {sorted(tabs)}")
# 每个模块：一个代表接口
PROBE = {"cs": ("GET", "/api/cs/convs"), "fin": ("GET", "/api/fin/meta"), "pur": ("GET", "/api/inv/po"),
         "seo": ("GET", "/api/products/seo-proposals"), "link": ("GET", "/api/ops/changes"), "desk": ("GET", "/api/desktop/devices")}
for mid, (m, path) in PROBE.items():
    ok(cb.open(path, method=m).status_code == 200, f"{mid} api on")
    r = cb.post(f"/api/modules/{mid}", json={"on": False}).get_json()
    ok(r.get("ok"), f"{mid} off")
    ok(cb.open(path, method=m).status_code == 404, f"{mid} api 404 when off")
    ok(mid not in [x["id"] for x in cb.get("/api/modules").get_json()["modules"]], f"{mid} not listed")
    ok(cb.get("/api/inv/items").status_code == 200 and cb.get("/api/orders").status_code == 200 and cb.get("/api/products").status_code == 200, f"kernel fine without {mid}")
sch = [m["id"] for m in cb.get("/api/settings/schema").get_json()["modules"]]
ok("cs" not in sch and "finance" not in sch, f"settings categories hidden {sch}")
k = integrations.create_key("t", "read")
H = {"Authorization": "Bearer " + k}
ok(cb.get("/api/v1/skus", headers=H).status_code == 200 and cb.get("/api/v1/ops/changes", headers={"Authorization": "Bearer " + integrations.create_key("o", "ops")}).status_code == 404, "v1 read api kernel, ops api module")
ok(cb.get("/api/inv/suppliers").status_code == 200, "suppliers stay in kernel")
ok(cb.get("/api/system/check").status_code == 200, "system check works with modules off")
ok(cb.get("/api/accel/package?personal=1").status_code == 200, "accelerator download without desk")
for mid in SIX:
    cb.post(f"/api/modules/{mid}", json={"on": True})
ok(all(cb.open(p, method=m).status_code == 200 for m, p in PROBE.values()), "all back on")
# 在线升级：removed_files.txt 里的旧文件会删掉（只在程序文件夹里，data 不碰）
import tempfile, zipfile, io
from core import sysadmin
tmp = tempfile.mkdtemp(); os.makedirs(tmp + "/core/cs"); open(tmp + "/core/cs/x.py", "w").write("1"); open(tmp + "/core/seo.py", "w").write("1")
os.makedirs(tmp + "/data"); open(tmp + "/data/keep.db", "w").write("1")
buf = io.BytesIO(); zf = zipfile.ZipFile(buf, "w"); zf.writestr("p/removed_files.txt", "core/cs\ncore/seo.py\ndata\n../etc\n"); zf.close()
old = sysadmin.APP_DIR; sysadmin.APP_DIR = tmp
n = sysadmin._remove_stale(zipfile.ZipFile(io.BytesIO(buf.getvalue())), "p/", os.path.abspath(tmp))
sysadmin.APP_DIR = old
ok(n == 2 and not os.path.exists(tmp + "/core/cs") and not os.path.exists(tmp + "/core/seo.py") and os.path.exists(tmp + "/data/keep.db"), f"stale files removed on upgrade ({n})")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
