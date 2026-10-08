# v2.32：打包核对 / 发货交接扫什么码可以设置；每个产品可以单独设核对方式；内部商品标签
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D = T + "/m_scan"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, store, orders as orders_mod
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
config.save_config({"review_enabled": False})
prods = [store.load(x["id"]) for x in store.list_products()[:2]]
s1, s2 = prods[0]["variants"][0]["sku"], prods[1]["variants"][0]["sku"]
o = C.post("/api/orders/manual", json={"order_no": "SCAN-001", "order_total": 100, "items": [{"sku": s1, "qty": 2}, {"sku": s2, "qty": 1}]}).get_json()
db.conn().execute("UPDATE orders SET tracking_no='TH9988776655' WHERE id=?", (o["id"],)); db.conn().commit()
sch = {m["id"]: m for m in C.get("/api/settings/schema").get_json()["modules"]}
ok(any(g["title"].startswith("打包核对与发货交接") for g in sch["orders"]["groups"]), "settings group under 订单与售后")
ok(config.load_config()["pack_item_mode"] == "tap" and config.load_config()["scan_order_key"] == "both", "defaults")
r = C.get("/api/pack/lookup?code=SCAN-001").get_json()
ok(r["id"] == o["id"] and all(i["check"] == "tap" for i in r["items"]) and r["scan_key"] == "both", f"lookup by order no, default tap {[i['check'] for i in r['items']]}")
ok(C.get("/api/pack/lookup?code=TH9988776655").status_code == 200, "lookup by tracking (both)")
# 只认快递单号
config.save_config({"scan_order_key": "tracking"})
r = C.get("/api/pack/lookup?code=SCAN-001")
ok(r.status_code == 404 and "快递单号" in r.get_json()["error"], "tracking only: order no rejected")
ok(C.get("/api/pack/lookup?code=TH-9988776655").status_code == 200, "tracking with dashes ok")
config.save_config({"scan_order_key": "order"})
ok(C.get("/api/pack/lookup?code=TH9988776655").status_code == 404 and C.get("/api/pack/lookup?code=SCAN-001").status_code == 200, "order only")
# 产品单独设置扫码
p = prods[0]; p["pack_check"] = "scan"; C.post(f"/api/products/{p['id']}", json=p)
ok(store.load(p["id"]).get("pack_check") == "scan", "editor saves pack_check")
r = C.get("/api/pack/lookup?code=SCAN-001").get_json()
modes = {i["sku"]: i["check"] for i in r["items"]}
ok(modes[s1] == "scan" and modes[s2] == "tap", f"per-product mode {modes}")
ok(all("img" in i for i in r["items"]), "items carry image")
config.save_config({"pack_item_mode": "none"})
r = C.get("/api/pack/lookup?code=SCAN-001").get_json()
ok({i["sku"]: i["check"] for i in r["items"]} == {s1: "scan", s2: "none"}, "default none, product override kept")
# 发货交接按设置认
h = C.post("/api/handovers", json={"carrier": ""}).get_json()
hid = h.get("id") or (h.get("handover") or {}).get("id")
r = C.post(f"/api/handovers/{hid}/scan", json={"code": "TH9988776655"})
ok(r.status_code == 400 and "订单号" in r.get_json()["error"], f"handover order-only rejects tracking {r.get_json()}")
r = C.post(f"/api/handovers/{hid}/scan", json={"code": "SCAN-001"})
ok(r.status_code == 200, f"handover by order no {r.get_json()}")
# 内部商品标签：每件一张，Code128 = SKU
html = C.get(f"/print/item-labels?ids={o['id']}").get_data(as_text=True)
ok(html.count('class="lb"') == 3 and s1 in html and "<svg" in html and "30mm" in html, "item labels 3 pcs")
config.save_config({"item_label_size": "60x40"})
ok("60mm 40mm" in C.get(f"/print/item-labels?ids={o['id']}").get_data(as_text=True), "label size setting")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
