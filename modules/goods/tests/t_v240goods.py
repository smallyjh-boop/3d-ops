# v2.40：全功能测试的中级问题——商品与上架
#  1 只导出 Shopee 不改 Lazada 状态   2 员工看不到、改不了加价率   3 复制产品：模型文件一起复制，导出状态不带
#  4 删掉用作白底图的那张图 → 白底图清掉   5 Shopee 库存待同步只列导出过 Shopee 的
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, copy
D = T + "/m_v240goods"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, listing, config
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("nok", "pass123", "listing", "Nok")
def cl(u, p):
    c = A.app.test_client(); c.post("/api/auth/login", json={"username": u, "password": p}); return c
C, N = cl("boss", "secret123"), cl("nok", "pass123")
ids = [x["id"] for x in store.list_products()]
fresh = next(i for i in ids if not store.load(i).get("exported_at") and not store.load(i).get("shopee_exported_at"))

# ---- 1 只导出 Shopee
r = C.post("/api/export/shopee", json={"product_ids": [fresh], "force": True}).get_json()
p = store.load(fresh)
ok(r.get("ok") and listing.status_of(p, "shopee")["status"] == "pending", "shopee pending after shopee export")
ok(listing.status_of(p, "lazada")["status"] == "none", f"lazada untouched ({listing.status_of(p, 'lazada')})")
ok(p.get("exported_at"), "SKU still locked after shopee export")
C.post(f"/api/products/{fresh}", json=C.get(f"/api/products/{fresh}").get_json())
ok(listing.status_of(store.load(fresh), "lazada")["status"] == "none", "editor save keeps the shopee-only marker")
r = C.post("/api/export", json={"product_ids": [fresh], "force": True}).get_json()
if r.get("ok"):
    ok(listing.status_of(store.load(fresh), "lazada")["status"] == "pending", "lazada pending after lazada export")

# ---- 5 Shopee 库存待同步
config.save_config({"stock_auto": True})
only_lz = next(i for i in ids if i != fresh)
p = store.load(only_lz); p["exported_at"] = 1; p.pop("shopee_exported_at", None); p.pop("exported_first", None); store.save(p)
sp = {x["sku"] for x in C.get("/api/stock/pending?platform=shopee").get_json()["items"]}
lz = {x["sku"] for x in C.get("/api/stock/pending?platform=lazada").get_json()["items"]}
skus = {v["sku"] for v in p["variants"] if v.get("sku")}
ok(not (skus & sp) and (skus & lz), f"lazada-only product only in lazada pending (sp {len(skus & sp)}, lz {len(skus & lz)})")
fskus = {v["sku"] for v in store.load(fresh)["variants"] if v.get("sku")}

# ---- 2 加价率
p = store.load(only_lz); p["markup"] = 0.85; store.save(p)
g = N.get(f"/api/products/{only_lz}").get_json()
ok("markup" not in g, "listing staff does not receive markup")
g["markup"] = 5
N.post(f"/api/products/{only_lz}", json=g)
ok(store.load(only_lz).get("markup") == 0.85, f"listing staff cannot change markup ({store.load(only_lz).get('markup')})")
pr_staff = N.post("/api/pricing", json=g).get_json()["rows"]
pr_boss = C.post("/api/pricing", json=store.load(only_lz)).get_json()["rows"]
ok([x.get("final_price") for x in pr_staff] == [x.get("final_price") for x in pr_boss], "staff price preview uses saved markup")
ok(C.get(f"/api/products/{only_lz}").get_json().get("markup") == 0.85, "owner still sees markup")

# ---- 3 复制产品
src = next(i for i in ids if store.load(i).get("model"))
d = C.post(f"/api/products/{src}/duplicate").get_json()
ok(not d.get("shopee_exported_at") and not d.get("exported_at") and listing.status_of(d, "lazada")["status"] == "none"
   and listing.status_of(d, "shopee")["status"] == "none", "duplicate has no export state")
r = C.get(f"/api/products/{d['id']}/model/stl")
ok(r.status_code == 200, f"duplicate's model file opens ({r.status_code})")

# ---- 4 白底图跟着删
p = store.load(src)
from PIL import Image
raw = "wb_test.jpg"
Image.new("RGB", (200, 200), "white").save(os.path.join(store.image_dir(src, "raw"), raw))
Image.new("RGB", (200, 200), "white").save(os.path.join(store.image_dir(src, "out"), "r_wb_test.jpg"))
p.setdefault("images", []).append({"raw": raw, "file": "r_wb_test.jpg", "processed": True, "url": ""})
p["white_bg"] = {"file": "r_wb_test.jpg", "url": ""}; store.save(p)
keep = [i["raw"] for i in p["images"] if i["raw"] != raw]
C.post(f"/api/products/{src}/images/reorder", json={"order": keep})
ok(not store.load(src).get("white_bg"), "deleting the render used as white-bg clears white_bg")
# 审查 L12：保存等接口返回的产品里也没有加价率
r = N.post(f"/api/products/{only_lz}", json=N.get(f"/api/products/{only_lz}").get_json()).get_json()
ok("markup" not in r, "save response to staff has no markup")
# 审查 L14：v2.40 以前只导出过 Shopee 的老产品（没有标记）
p = store.load(only_lz); p["exported_at"] = 1000; p["shopee_exported_at"] = 1002; p["listing"] = {}; p.pop("exported_first", None); store.save(p)
ok(listing.status_of(store.load(only_lz), "lazada")["status"] == "none", "legacy shopee-only product is not lazada pending")
p["shopee_exported_at"] = 900000; store.save(p)
ok(listing.status_of(store.load(only_lz), "lazada")["status"] == "pending", "legacy lazada-then-shopee product still lazada pending")
print("ERRORS", E_)
