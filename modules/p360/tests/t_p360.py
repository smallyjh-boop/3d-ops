# 商品 360 抽屉（p360 1.0）：GET /api/p360/<SKU 或产品编号>——按角色去掉成本利润 / 价格、模块关着那一块不出现、找不到 404、
# 库存货位、在线商品、销量曲线、竞品中位价和排名、评价、计划、待确认改动、生产任务、最近订单。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, time
D = T + "/m_p360"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, production, config
db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "secret123", "listing", "Nok")
db.create_user("pack", "secret123", "production", "Pack", "th")
def login(u):
    c = A.app.test_client(); c.post("/api/auth/login", json={"username": u, "password": "secret123"}); return c
C, CL, CP = login("boss"), login("nok"), login("pack")
config.save_config({"review_enabled": False})

PID = "3DP0015"
p = store.load(PID)
SKU = p["variants"][0]["sku"].upper()
SKUS = [v["sku"].upper() for v in p["variants"] if v.get("sku")]

# ---- 数据：订单、库存、货位、在线商品、评价、竞品、计划、运营改动、生产任务
o = C.post("/api/orders/manual", json={"order_no": "P360-001", "order_total": 300, "buyer": "Test", "items": [{"sku": SKU, "qty": 3, "unit_price": 100}]}).get_json()
ok(o.get("id"), f"order created {o}")
production.stock_add(SKU, 7, "test", "boss", PID)
r = C.post("/api/inv/locations/bulk", json={"zone": "P", "layers": 1, "positions": 2}).get_json()
it = db.conn().execute("SELECT id FROM inv_items WHERE code=?", (SKU,)).fetchone()
if it:
    C.post("/api/inv/locations/assign", json={"item_id": it["id"], "code": "P1-01-02"})
from modules.listing import online
online.init()
db.conn().execute("INSERT INTO shops(platform, name, enabled) VALUES('lazada', 'LZ Shop A', 1)")
sid = db.conn().execute("SELECT id FROM shops WHERE name='LZ Shop A'").fetchone()[0]
db.conn().execute("""INSERT INTO online_items(platform, shop_id, item_id, status, raw_status, reason, name, product_id, skus, price_min, price_max, qty, created, updated, synced_at)
                     VALUES('lazada', ?, '9001', 'rejected', 'suspended', 'Image has watermark', 'Phone stand', ?, ?, 129, 129, 5, ?, ?, ?)""",
                  (sid, PID, json.dumps([{"seller_sku": SKU, "price": 159, "special_price": 129, "qty": 5, "status": "active"}]), time.time() - 86400 * 20, time.time(), time.time()))
from modules.ops import lazada as oalz
oalz._ensure()
for i, (rt, txt) in enumerate([(5, "ดีมาก"), (2, "แตกง่าย"), (4, "ok")]):
    db.conn().execute("INSERT INTO oa_lz_review(shop_id, review_id, item_id, rating, content, created) VALUES(?,?,?,?,?,?)",
                      (sid, f"r{i}", "9001", rt, txt, time.time() - i * 3600))
db.conn().commit()
for u, price in (("https://www.lazada.co.th/products/a-i111-s1.html", 99), ("https://www.lazada.co.th/products/b-i112-s1.html", 149),
                 ("https://www.lazada.co.th/products/c-i113-s1.html", 400)):
    r = C.post("/api/oa/comp", json={"url": u, "skus": SKU.lower(), "price": price, "sold_text": "100", "reviews": 10})
    ok(r.status_code == 200, f"comp {price} {r.status_code}")
r = C.post("/api/oa/plans", json={"sku": SKU, "platform": "lazada", "kind": "hero"})
ok(r.status_code == 200, f"plan {r.get_json()}")
from modules.link import opsapi
config.save_config({"ops_write_mode": "confirm"})
ch = opsapi.submit(SKU, {"title_th": "ที่วางโทรศัพท์ ทดสอบ แบบใหม่ สำหรับโต๊ะทำงาน"}, reason="seo test")
ok(ch["status"] == "pending", "pending ops change")
job = production.create_job(PID, SKU, 2, kind="stock", user="boss")["id"]

# ---- 老板：全部
r = C.get(f"/api/p360/{SKU.lower()}")
d = r.get_json()
ok(r.status_code == 200 and d["product"]["id"] == PID and d["focus"] == 0, f"owner view {r.status_code} {d.get('focus')}")
v0 = d["variants"][0]
ok(all(k in v0 for k in ("price", "floor_price", "cost", "profit", "fee")), f"owner sees cost/profit {sorted(v0)}")
ok(v0["stock"] == 7 and v0["free"] == 7, f"stock {v0.get('stock')} {v0.get('free')}")
if it:
    ok((v0.get("location") or {}).get("code") == "P1-01-02" and v0["location"]["th"], f"location {v0.get('location')}")
ok(d["sales"]["qty_30d"] == 3 and len(d["sales"]["days"]) == 30 and d["sales"]["days"][-1]["qty"] == 3, f"sales {d['sales']['qty_30d']}")
ok(d["kpi"]["sold_30d"] == 3 and d["kpi"]["profit_unit"] is not None and len(d["kpi"]["spark"]) == 30, f"kpi {d['kpi']}")
ok(len(d["online"]) == 1 and d["online"][0]["item_id"] == "9001" and d["online"][0]["reason"] and d["online"][0]["shop"] == "LZ Shop A", "online item")
ok(d["reviews"]["n"] == 3 and d["reviews"]["avg"] == 3.67 and d["reviews"]["bad"] == 1, f"reviews {d['reviews']}")
ok(d["kpi"]["rating"] == 3.67, "kpi rating")
cp = d["comp"]
ok(len(cp["rows"]) == 3 and cp["median"] == 149 and cp["rank"]["of"] == 4 and cp["my_price"], f"comp {cp.get('median')} {cp.get('rank')}")
ok(d["plans"] and d["plans"][0]["sku"] == SKU and d["plans"][0]["kind_label"], f"plans {d.get('plans')}")
ok("actual_profit" in d["plans"][0], "owner sees plan profit")
ok(d["lifecycle"] and any(x["stage"] == "rejected" for x in d["lifecycle"]), f"lifecycle {[x['stage'] for x in d['lifecycle']]}")
ok(d["kpi"]["stage"]["stage"] == "rejected" and d["kpi"]["stage"]["label_th"], f"stage chip {d['kpi'].get('stage')}")
ok(len(d["pending"]) == 1 and any(s.get("go") == "opschg" for s in d["suggestions"]), "pending change + suggestion")
ok(any(j["id"] == job for j in d["jobs"]), f"production job {d['jobs']}")
ok(d["orders"] and d["orders"][0]["order_no"] == "P360-001" and "unit_price" in d["orders"][0], "recent orders")
ok(isinstance(d["changes"], list), "changes list")

# 产品编号也行，没有选中的规格
d2 = C.get(f"/api/p360/{PID}").get_json()
ok(d2["focus"] is None and d2["product"]["id"] == PID, "product id resolves")

# ---- 上架客服：没有成本 / 最低价 / 利润
dl = CL.get(f"/api/p360/{SKU}").get_json()
txt = json.dumps(dl)
vl = dl["variants"][0]
ok("price" in vl and not any(k in vl for k in ("floor_price", "cost", "profit", "fee", "markup")), f"listing no cost {sorted(vl)}")
ok("profit_unit" not in dl["kpi"] and "actual_profit" not in dl["plans"][0] and "actual_revenue" not in dl["plans"][0], "listing: no profit in kpi / plans")
ok('"profit' not in txt and '"cost' not in txt and "floor_price" not in txt and '"fee"' not in txt, "listing: nothing with cost/profit anywhere")
ok("comp" in dl and "reviews" in dl and "changes" in dl, "listing sees ops sections")
ok(not any(x["source"] == "audit" for x in dl["changes"]), "listing: no audit log")

# ---- 生产：连售价都没有，没有运营数据
r = CP.get(f"/api/p360/{SKU}")
dp = r.get_json()
ok(r.status_code == 200, f"production allowed {r.status_code}")
ok("price" not in dp["variants"][0] and "unit_price" not in dp["orders"][0] and "revenue_30d" not in dp["sales"], "production: no prices")
ok(not any(k in dp for k in ("comp", "reviews", "plans", "lifecycle", "traffic", "changes")), f"production: no ops sections {sorted(dp)}")
ok(all("price_min" not in x for x in dp.get("online") or []), "production: no online prices")

# ---- 模块关着：那一块不出现
cf = config.load_config(); cf["modules_off"] = ["ops", "inv"]; config.save_config(cf)
d3 = C.get(f"/api/p360/{SKU}").get_json()
ok(not any(k in d3 for k in ("comp", "reviews", "plans", "lifecycle", "traffic")), f"ops off → sections omitted {sorted(d3)}")
ok("location" not in d3["variants"][0] and "online" in d3, "inv off → no location; listing still on")
cf["modules_off"] = ["listing"]; config.save_config(cf)
d4 = C.get(f"/api/p360/{SKU}").get_json()
ok("online" not in d4 and "reviews" not in d4 and "comp" in d4, f"listing off → online/reviews omitted {sorted(d4)}")
cf["modules_off"] = []; config.save_config(cf)

# ---- 找不到
r = C.get("/api/p360/NOPE-XX")
ok(r.status_code == 404 and "找不到" in r.get_json()["error"] and r.get_json()["error_th"], f"unknown sku 404 {r.get_json()}")
ok(C.get("/api/p360/..%2Fapp").status_code == 404, "bad id 404")

# ---- 前台文件
ok(C.get("/static/p360.js").status_code == 200 and C.get("/static/p360.css").status_code == 200, "static files")
html = C.get("/").get_data(as_text=True)
ok("/static/p360.js" in html and "/static/p360.css" in html, "index loads p360")
print("ERRORS", E_)
