# 手机 / 平板 App 模块（mobile 1.0）：扫码识别、查订单、交接选物流、打包照片、安卓安装包、手机页不用登录也能打开、平板 App 标记
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import io, os, sys, shutil, zipfile
D = T + "/m_mobile"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, store
db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("packer", "secret123", "production", "Packer", "th")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
config.save_config({"review_enabled": False})
prods = [store.load(x["id"]) for x in store.list_products()[:2]]
s1, s2 = prods[0]["variants"][0]["sku"], prods[1]["variants"][0]["sku"]
o = C.post("/api/orders/manual", json={"order_no": "MOB-001", "order_total": 100, "buyer": "Somchai Test", "carrier": "Flash Express",
                                        "items": [{"sku": s1, "qty": 2}, {"sku": s2, "qty": 1}]}).get_json()
db.conn().execute("UPDATE orders SET tracking_no='TH5566778899', carrier='Flash Express' WHERE id=?", (o["id"],)); db.conn().commit()

# ---- 手机页：没登录也能打开（页面自己显示登录框），js / css 也不用登录
anon = A.app.test_client()
r = anon.get("/m")
ok(r.status_code == 200 and b"/m/mobile/m.js" in r.data and b"I18N_MODULES" in r.data, f"/m opens without login {r.status_code}")
ok(anon.get("/m/mobile/m.js").status_code == 200 and anon.get("/m/mobile/scan.js").status_code == 200, "phone js public")
ok(anon.get("/api/mobile/boot").status_code == 401, "phone api needs login")
ok(anon.get("/m/inv/inventory.js").status_code in (302, 401), "other module files still need login")

# ---- 扫码识别：订单号 / 运单号
r = C.get("/api/mobile/resolve?code=MOB-001").get_json()
ok(r["type"] == "order" and r["order"]["id"] == o["id"] and r["alert"] is None, f"order no {r.get('type')}")
ok(len(r["order"]["items"]) == 2 and all("img" in i for i in r["order"]["items"]) and r["order"]["items"][0]["img"].startswith("/files/"),
   "order items carry images")
ok("jobs" in r["order"] and "job_counts" in r["order"], "order carries production progress")
r = C.get("/api/mobile/resolve?code=%20TH-5566778899%0A").get_json()
ok(r["type"] == "order" and r["order"]["order_no"] == "MOB-001", "tracking with dashes / whitespace")
# 设置里「只认快递单号」时查询照样两个都认
config.save_config({"scan_order_key": "tracking"})
ok(C.get("/api/mobile/resolve?code=MOB-001").get_json()["type"] == "order", "resolver ignores pack key setting")
config.save_config({"scan_order_key": "both"})

# ---- SKU：还没建库存档 → sku；建了 → item（带货位）
r = C.get(f"/api/mobile/resolve?code={s1.lower()}").get_json()
ok(r["type"] in ("sku", "item"), f"sku resolves {r['type']}")
if r["type"] == "sku":
    ok(r["sku"]["product_id"] == prods[0]["id"] and r["sku"]["img"], "sku summary")
ok(C.get("/api/mobile/resolve?code=NOPE-XYZ-123").get_json()["type"] == "unknown", "unknown code")
ok(C.get("/api/mobile/resolve?code=").status_code == 400, "empty code rejected")

# 货架 + 物品 + 货位
r = C.post("/api/inv/locations/bulk", json={"zone": "Z", "layers": 2, "positions": 2}).get_json()
ok(r.get("ok"), f"shelf created {r}")
it = C.post("/api/inv/items", json={"name_zh": "气泡袋", "category": "pack", "unit": "个", "code": "BAG-01"}).get_json()["item"]
ok(C.post("/api/inv/docs", json={"kind": "purchase", "lines": [{"item_id": it["id"], "qty": 50}], "note": "test"}).status_code == 200, "stock in")
r = C.post("/api/inv/locations/assign", json={"item_id": it["id"], "code": "z1-1-2"}).get_json()
ok(r.get("ok") and r["item"]["location"] == "Z1-01-02", f"assigned {r}")
r = C.get("/api/mobile/resolve?code=bag-01").get_json()
ok(r["type"] == "item" and r["item"]["qty"] == 50 and r["item"]["loc"]["code"] == "Z1-01-02" and r["item"]["loc"]["human_zh"], f"item {r}")
ok("avg_cost" in r["item"], "owner sees cost")
r = C.get("/api/mobile/resolve?code=z1-1-2").get_json()
ok(r["type"] == "location" and [x["code"] for x in r["items"]] == ["BAG-01"], f"location {r.get('type')}")
r = C.get("/api/mobile/resolve?code=Z1").get_json()
ok(r["type"] == "shelf" and len(r["locations"]) == 4 and r["items"][0]["code"] == "BAG-01", f"shelf {r.get('type')}")

# ---- 查订单（买家名）、交接选物流
r = C.get("/api/mobile/orders?q=somchai%20test").get_json()
ok([x["order_no"] for x in r["orders"]] == ["MOB-001"] and r["orders"][0]["n_items"] == 3, f"search buyer {r}")
ok(C.get("/api/mobile/orders?q=a").status_code == 400, "search needs 2 chars")
r = C.get("/api/mobile/carriers").get_json()
ok(any(x["carrier"] == "Flash Express" for x in r["carriers"]) and r["open"] == [], f"carriers {r}")
h = C.post("/api/handovers", json={"carrier": "Flash Express"}).get_json()
r = C.get("/api/mobile/carriers").get_json()
ok(r["open"] and r["open"][0]["id"] == h["id"], "open handover listed")

# ---- 打包照片
from PIL import Image
buf = io.BytesIO(); Image.new("RGB", (3000, 2000), (200, 30, 30)).save(buf, "PNG"); png = buf.getvalue()
r = C.post(f"/api/mobile/orders/{o['id']}/photos", data={"files": (io.BytesIO(png), "p.png"), "kind": "pack"}, content_type="multipart/form-data")
ph = r.get_json().get("photos") or []
ok(r.status_code == 200 and len(ph) == 1 and ph[0]["user"] == "boss", f"photo uploaded {r.get_json()}")
g = C.get(ph[0]["url"])
im = Image.open(io.BytesIO(g.data))
ok(g.status_code == 200 and max(im.size) == 1600 and im.format == "JPEG", f"photo shrunk to jpg {im.size}")
r = C.post(f"/api/mobile/orders/{o['id']}/photos", data={"files": (io.BytesIO(b"not an image"), "x.png")}, content_type="multipart/form-data")
ok(r.status_code == 400, "non-image rejected")
ok(C.get(f"/api/mobile/orders/{o['id']}/photos/..%2Fapp.db").status_code == 404, "no path traversal")
ok(C.get(f"/api/mobile/resolve?code=MOB-001").get_json()["order"]["photos"] == 1, "order shows photo count")
ok(any("打包照片" in (x.get("action") or "") for x in C.get(f"/api/orders/{o['id']}").get_json()["log"]), "photo logged on order")

# ---- 生产打包角色：能用手机接口，金额看不到，不能管安装包
P = A.app.test_client(); P.post("/api/auth/login", json={"username": "packer", "password": "secret123"})
ok(P.get("/api/mobile/boot").get_json()["user"]["role"] == "production", "packer boot")
r = P.get("/api/mobile/resolve?code=MOB-001").get_json()
ok(r.get("type") == "order" and "order_total" not in r["order"], "packer resolves order")
r = P.get("/api/mobile/resolve?code=BAG-01").get_json()
ok(r.get("type") == "item" and "avg_cost" not in r["item"] and "value" not in r["item"], "packer: no cost on items")
ok(P.post(f"/api/mobile/orders/{o['id']}/photos", data={"files": (io.BytesIO(png), "p.png")}, content_type="multipart/form-data").status_code == 200,
   "packer uploads photo")
ok(P.post("/api/mobile/apk/fetch", json={}).status_code == 403, "packer cannot fetch apk")
ok(P.get("/api/pack/lookup?code=MOB-001").status_code == 200 and P.get("/api/handovers").status_code == 200, "packer: pack + handover apis")

# ---- 取消的订单：扫到要大声提醒
db.conn().execute("UPDATE orders SET status='cancelled' WHERE id=?", (o["id"],)); db.conn().commit()
r = C.get("/api/mobile/resolve?code=TH5566778899").get_json()
ok(r["order"]["blocked"] and r["alert"]["level"] == "error" and "不要" in r["alert"]["zh"] and "ยกเลิก" in r["alert"]["th"], f"cancelled alert {r['alert']}")
r = C.post(f"/api/handovers/{h['id']}/scan", json={"code": "TH5566778899"})
ok(r.status_code == 400 and "不能发货" in r.get_json()["error"], "handover blocks cancelled")

# ---- 安卓安装包
ok(anon.get("/apk").status_code == 404 and "GitHub".encode() in anon.get("/apk").data, "no apk yet: friendly page")
z = io.BytesIO()
with zipfile.ZipFile(z, "w") as zf:
    zf.writestr("AndroidManifest.xml", b"x"); zf.writestr("classes.dex", b"y")
r = C.post("/api/mobile/apk/upload", data={"file": (io.BytesIO(z.getvalue()), "a.apk"), "version": "1.0.0"}, content_type="multipart/form-data")
ok(r.status_code == 200 and r.get_json()["version"] == "1.0.0" and r.get_json()["source"] == "upload", f"apk upload {r.get_json()}")
r = anon.get("/apk")
ok(r.status_code == 200 and r.headers["Content-Type"] == "application/vnd.android.package-archive" and "3D-Ops-1.0.0.apk" in r.headers.get("Content-Disposition", ""),
   "anyone on LAN downloads apk")
ok(C.post("/api/mobile/apk/upload", data={"file": (io.BytesIO(b"junk"), "a.apk")}, content_type="multipart/form-data").status_code == 400, "bad apk rejected")
from modules.mobile import apk
rel = [{"tag_name": "v2.45.1", "assets": [{"id": 1, "name": "x.zip"}]},
       {"tag_name": "android-v1.2.0", "assets": [{"id": 5, "name": "3dops-1.2.0-debug.apk"}, {"id": 6, "name": "3dops-1.2.0-release.apk"}]},
       {"tag_name": "android-v1.10.0", "assets": [{"id": 9, "name": "3dops-1.10.0-debug.apk"}]},
       {"tag_name": "android-v9.0.0", "draft": True, "assets": [{"id": 10, "name": "a.apk"}]}]
p = apk._pick(rel)
ok(p["version"] == "1.10.0" and p["asset_id"] == 9, f"pick newest android release {p}")
ok(apk._pick(rel[1:2])["asset_id"] == 6, "prefer release apk")
ok(apk._pick([]) is None, "no release")

# ---- 平板 App：网页版标记 in-app（隐藏加速器、桌面版下载）
r = C.get("/", headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/124 3DOpsApp/1.0.0"})
ok(b'class="in-app"' in r.data and b"IN_APP=true" in r.data, "app user agent marks in-app")
ok(b'class="in-app"' not in C.get("/").data, "normal browser unchanged")
ok(C.get("/api/modules").status_code == 200 and any(m["id"] == "mobile" for m in C.get("/api/modules").get_json()["modules"]), "module listed")

# ---- 模块关掉：手机页和接口都没有
C.post("/api/modules/mobile", json={"on": False})
ok(anon.get("/m").status_code == 404 and C.get("/api/mobile/boot").status_code == 404, "module off → 404")
C.post("/api/modules/mobile", json={"on": True})
ok(anon.get("/m").status_code == 200, "module back on")
print("ERRORS", E_)
