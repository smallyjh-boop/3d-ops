# v2.31：主链路拆成模块后的整条流程——商品 → 订单 → 生产任务 → 打完 → 自动发货 → 扣包材 / 耗材流水 → 利润；
# 再逐个关掉 生产 / 库存 / 上架导出 / 树脂打印，看关掉的部分停了、其它照常。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D = T + "/v231"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, store, production, modules, inventory as inv
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
ms = {m["id"]: m for m in C.get("/api/modules?all=1").get_json()["modules"]}
CHAIN = ["goods", "listing", "model", "orders", "prod", "inv", "resin"]
ok(all(x in ms and ms[x]["enabled"] and not ms[x]["error"] for x in CHAIN), f"chain modules loaded {[(x, ms.get(x, {}).get('error')) for x in CHAIN]}")
ok(ms["goods"]["core"] and ms["orders"]["core"] and ms["model"]["core"] and not ms["prod"]["core"], "core flags")
html = C.get("/").get_data(as_text=True)
ok(all(f'id="tab-{t}" class="panel hidden" data-module=' in html for t in ("library", "edit", "export", "orders", "production", "inventory")), "inline panels in index")
ok('/m/prod/prod.js' in html and '/m/goods/scene.js' in html and html.index('/static/ops.js') < html.index('/m/goods/scene.js') < html.index('/static/home.js'), "module scripts in order")
for mid, f in (("goods", "scene.js"), ("listing", "export.js"), ("prod", "materials.js"), ("inv", "inventory.js"), ("orders", "shipping.js")):
    ok(C.get(f"/m/{mid}/{f}").status_code == 200, f"serve {mid}/{f}")

# ---- 准备：一个产品 SKU、包材和自动扣包材规则
sku = next(v["sku"] for it in store.list_products() for v in (store.load(it["id"]).get("variants") or []) if v.get("sku"))
pid = sku.split("-")[0]
box = C.post("/api/inv/items", json={"name_zh": "测试纸箱", "category": "pack", "unit": "个"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": box["id"], "qty": 50}], "期初", "t")
config.save_config({"inv_pack_auto": True, "inv_pack_rules": [{"item_id": box["id"], "qty": 1, "per": "order"}], "review_enabled": False})
q = lambda: inv.get_item(box["code"])["qty"]
production.stock_add(sku, -production.stock_qty(sku), "清零", "t") if production.stock_qty(sku) > 0 else None

def new_order(no):
    o = C.post("/api/orders/manual", json={"order_no": no, "order_total": 199, "items": [{"sku": sku, "qty": 1, "price": 199}]}).get_json()
    return o["id"]
def jobs_of(oid):
    return [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE order_id=?", (oid,))]

# ---- 全开：整条链
oid = new_order("CHAIN1")
js = jobs_of(oid)
ok(len(js) == 1 and js[0]["status"] == "todo", f"order -> production job {[(j['id'], j['status']) for j in js]}")
mv0, b0 = len(inv.moves(limit=5000)), q()
C.post(f"/api/jobs/{js[0]['id']}", json={"status": "post"})
ok(len(inv.moves(limit=5000)) > mv0, "printing done -> filament ledger moves (inv on)")
C.post(f"/api/jobs/{js[0]['id']}", json={"status": "done"})
o = db.conn().execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()
ok(o["status"] == "shipped", f"all jobs done -> order shipped ({o['status']})")
ok(q() == b0 - 1, f"shipped -> packing deducted ({b0} -> {q()})")
pr = C.get("/api/profit?days=30").get_json()
ok(pr["total"]["orders"] >= 1, "profit report counts the order")
ev = [e["event"] for e in C.get("/api/modules/events").get_json()["events"]]
ok("order.changed" in ev and "order.status" in ev, f"events recorded {ev[:6]}")

# ---- 关掉生产：订单照常建，不生成任务
ok(C.post("/api/modules/prod", json={"on": False}).get_json()["ok"], "prod off")
oid2 = new_order("CHAIN2")
ok(oid2 and not jobs_of(oid2), "prod off -> no jobs, order still created")
ok(C.get("/api/production").status_code == 404 and C.get("/api/printers").status_code == 404, "prod apis 404")
ok(C.get("/api/orders").status_code == 200 and C.get("/api/inv/items").status_code == 200, "orders / inv fine")
html = C.get("/").get_data(as_text=True)
ok('id="tab-production"' not in html and '/m/prod/' not in html and 'id="tab-orders"' in html, "prod panels / js gone from index")
ok(C.post("/api/modules/resin", json={"on": True}).status_code == 400, "resin can't turn on without prod")
sch = {m["id"]: m for m in C.get("/api/settings/schema").get_json()["modules"]}
ok("production" not in sch and not any(g["title"] == "耗材补货" for g in sch["inventory"]["groups"]), "prod settings hidden")
C.post("/api/modules/prod", json={"on": True})
ok(len(jobs_of(oid2)) == 0 and C.get("/api/production").status_code == 200, "prod back on")
production.generate("t")
ok(len(jobs_of(oid2)) == 1, "regenerate after prod back on picks up the order")

# ---- 关掉库存：发货不扣包材、打印不记库存流水，采购跟着停
r = C.post("/api/modules/inv", json={"on": False}).get_json()
ok(r["ok"] and "pur" in r["also_off"], f"inv off, pur depends ({r.get('also_off')})")
j2 = jobs_of(oid2)[0]
mv1, b1 = len(inv.moves(limit=5000)), q()
C.post(f"/api/jobs/{j2['id']}", json={"status": "post"}); C.post(f"/api/jobs/{j2['id']}", json={"status": "done"})
ok(db.conn().execute("SELECT status FROM orders WHERE id=?", (oid2,)).fetchone()["status"] == "shipped", "order still ships with inv off")
ok(len(inv.moves(limit=5000)) == mv1 and q() == b1, "inv off -> no ledger moves, no packing")
ok(C.get("/api/inv/items").status_code == 404 and C.get("/api/inv/po").status_code == 404, "inv + pur apis 404")
ok(C.get("/api/materials").status_code == 200, "filament spools (prod) still work")
sch = {m["id"]: m for m in C.get("/api/settings/schema").get_json()["modules"]}
ok("pack_rules" not in sch["inventory"]["special"] and any(g["title"] == "耗材补货" for g in sch["inventory"]["groups"]), "inv settings hidden, prod ones stay")
from core import stockcalc
av = stockcalc.available(fresh=True)
ok(isinstance(av, dict) and len(av) > 0, f"stock calc uses spools when inv off ({len(av)} colors)")
C.post("/api/modules/inv", json={"on": True}); C.post("/api/modules/pur", json={"on": True})

# ---- 关掉上架导出
C.post("/api/modules/listing", json={"on": False})
ok(C.post("/api/export", json={"ids": []}).status_code == 404 and C.get("/api/listing/batches").status_code == 404, "listing apis 404")
ok(C.get("/api/categories").status_code == 200 and C.get("/api/templates").status_code == 200, "categories / templates (goods) fine")
html = C.get("/").get_data(as_text=True)
ok('id="tab-export"' not in html and 'id="tab-library"' in html, "export page gone")
C.post("/api/modules/listing", json={"on": True})

# ---- 关掉树脂打印：不能上传光固化文件
from core import print_files
C.post("/api/modules/resin", json={"on": False})
try:
    print_files._kind("a.pm5s"); ok(False, "resin upload blocked")
except ValueError as e:
    ok("树脂" in str(e), "resin upload blocked")
ok(print_files._kind("a.gcode.3mf") == "3mf", "fdm files fine")
C.post("/api/modules/resin", json={"on": True})
ok(print_files._kind("a.pm5s") == "resin", "resin back on")

# ---- 基础模块不能关
ok(C.post("/api/modules/goods", json={"on": False}).status_code == 400 and C.post("/api/modules/orders", json={"on": False}).status_code == 400, "core modules can't be turned off")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
