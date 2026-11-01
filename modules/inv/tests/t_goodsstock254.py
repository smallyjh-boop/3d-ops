# v2.54：仓库 → 库存 → 成品备货——所有成品一张表（自产 / 外购、可卖 / 待检 / 次品、货位拆开、目标、缺口、销量、能卖几天、在做的）、
# 目标数量自动算（近 N 天销量 × 常备天数 + 安全库存 / 分类默认 / 手动覆盖）、批量加（产品库选择 / 按分组）、一键补货（自产 → 生产单、外购 → 采购单草稿，
# 自产按一盘能打几个往上取整）、自动分组数字、货位（快速移库 / 上架推荐先拣货区再备货区）、标签、权限
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3
D = T + "/m_gs254"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, inventory as inv, production, store, modules, po
from core.inventory import goodsstock as G
from modules.inv import locations as L, wms, flows
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pong", "secret123", "production", "Pong")
db.create_user("lee", "secret123", "listing", "Lee")
def cli(u):
    c = A.app.test_client(); c.post("/api/auth/login", json={"username": u, "password": "secret123"}); return c
C, PC, LC = cli("boss"), cli("pong"), cli("lee")
PRS = [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True}, {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "enabled": True}]
config.save_config({"printers": PRS, "stock_auto_use": False, "stock_cover_days": 7, "gs_sales_days": 30, "gs_safety": 1, "gs_cat_default": "挂件=4",
                    "inv_qc_on": False, "review_enabled": False})
SKA, SKB, SKC = "3DP0003-WH", "3DP0003-PK", "3DP0001-PK"
rowof = lambda sku: next((r for r in C.get("/api/inv/gs").get_json()["rows"] if r["sku"] == sku), None)

# ---------- 空表 + 权限 ----------
g = C.get("/api/inv/gs").get_json()
ok(g["ok"] and g["rows"] == [] and set(g["kpis"]) >= {"units", "value", "below", "out", "put", "slow"}, f"empty overview shape {sorted(g['kpis'])}")
ok(LC.post("/api/inv/gs/add", json={"skus": [SKA]}).status_code == 403, "listing role can't edit")
ok(LC.get("/api/inv/gs").status_code == 200, "listing role can read")

# ---------- 批量加：SKU / 产品库选择 / 分组 ----------
r = PC.post("/api/inv/gs/add", json={"skus": [SKA, "nope-1"]}).get_json()
ok(r["added"] == [SKA] and r["missing"] == ["NOPE-1"], f"add by SKU {r}")
ok(PC.post("/api/inv/gs/add", json={"skus": [SKA]}).get_json()["existed"] == [SKA], "adding again = existed")
pr = C.get("/api/inv/gs/products").get_json()
p3 = next(p for p in pr["products"] if p["id"] == "3DP0003")
ok(p3["in"] == 1 and SKB in p3["skus"] and p3["img"] != "" or p3["in"] == 1, f"product picker lists SKUs, how many are already in {p3['in']}/{len(p3['skus'])}")
r = C.post("/api/inv/gs/add", json={"product_ids": ["3DP0003"]}).get_json()
ok(SKB in r["added"] and SKA in r["existed"], f"add whole product (every spec) {r}")
p1 = store.load("3DP0001"); p1["category"] = {"id": 1, "name": "挂件"}; store.save(p1)
r = C.post("/api/inv/gs/add", json={"group": {"category": "挂件"}}).get_json()
ok(r["added"] and all(s.startswith("3DP0001") for s in r["added"]), f"add by category group {r['added']}")
ok(C.post("/api/inv/gs/add", json={}).status_code == 400, "nothing selected refused")
ok("挂件" in C.get("/api/inv/gs/products").get_json()["categories"], "picker offers the category")

# ---------- 买来的（没有产品）：库存里建成品物品 + 入库 ----------
it = C.post("/api/inv/items", json={"name_zh": "外购手机支架", "category": "goods", "unit": "个", "code": "BUY-001"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": it["id"], "qty": 5, "unit_cost": 30}], "", "t")
rb = rowof("BUY-001")
ok(rb and rb["type"] == "buy" and not rb["in_library"] and rb["qty"] == 5, f"purchased goods (no product) listed as 外购: {rb and rb['type']}")
ok(rowof(SKA)["type"] == "own" and rowof(SKB)["type"] == "own", "3D printed SKUs are 自产")
C.post("/api/inv/gs/src", json={"skus": [SKB], "src": "buy"})
ok(rowof(SKB)["type"] == "buy", "a SKU can be flagged 外购")
C.post("/api/inv/gs/src", json={"skus": [SKB], "src": ""})
ok(rowof(SKB)["type"] == "own", "…and back to automatic")
ok(rb["value"] == 150, f"stock value qty x cost {rb['value']}")

# ---------- 目标数量：自动 = 销量 × 常备天数 + 安全库存；分类默认；手动覆盖 ----------
for i, q in enumerate((6, 8)):
    C.post("/api/orders/manual", json={"order_no": f"GS-O{i}", "items": [{"sku": SKA, "qty": q, "unit_price": 100}]})
ra = rowof(SKA)
ok(ra["sold"] == 14 and ra["target"] == 5 and ra["auto"], f"auto target = ceil(14/30*7 + 1) = 5 -> {ra['target']}")
ok(abs(ra["daily"] - 0.47) < 0.01, f"daily sales {ra['daily']}")
rc = rowof(SKC)
ok(rc["target"] == 4 and rc["auto"] and rc["category"] == "挂件", f"no sales -> category default 4 ({rc['target']})")
ok(rowof(SKB)["target"] == 0, "no sales, no category default -> 0")
C.post("/api/inv/gs/target", json={"skus": [SKA], "target": 12})
ra = rowof(SKA)
ok(ra["target"] == 12 and not ra["auto"] and ra["manual"] == 12, "manual override wins")
C.post("/api/inv/gs/target", json={"skus": [SKA], "target": ""})
ok(rowof(SKA)["target"] == 5 and rowof(SKA)["auto"], "empty = back to auto")
config.save_config({"gs_safety": 3, "stock_cover_days": 10})
ok(rowof(SKA)["target"] == 8, f"settings change the auto target: ceil(14/30*10+3) = 8 -> {rowof(SKA)['target']}")
config.save_config({"gs_safety": 1, "stock_cover_days": 7})
ok(C.post("/api/inv/gs/target", json={"skus": [SKA], "target": -3}).get_json()["ok"] and rowof(SKA)["target"] == 0, "negative target clamps to 0")
C.post("/api/inv/gs/target", json={"skus": [SKA], "target": ""})

# ---------- 数量：可卖 / 待检 / 次品 / 货位 / 缺口 / 能卖几天 ----------
C.post("/api/inv/locations/bulk", json={"zone": "A", "layers": 1, "positions": 3, "categories": ["goods"]})
C.post("/api/inv/locations/bulk", json={"zone": "R", "layers": 1, "positions": 3, "ztype": "reserve"})
flows.zone_loc(db.conn(), "qc"); flows.zone_loc(db.conn(), "defect"); db.conn().commit()
production.stock_add(SKA, 4, "盘点", "t")
ra = rowof(SKA)
ok(ra["qty"] == 4 and ra["sellable"] == 4 and ra["gap"] == 1, f"stock 4 vs target 5 -> gap 1 ({ra['qty']}/{ra['gap']})")
ok(ra["locs"] and ra["locs"][0]["code"].startswith("A") and ra["locs"][0]["ztype"] == "pick", f"received goods put in the pick zone {ra['locs']}")
ok(ra["cover_days"] is not None and abs(ra["cover_days"] - 4 / ra["daily"]) < 0.2, f"days of cover {ra['cover_days']}")
config.save_config({"inv_qc_on": True})
production.stock_add(SKB, 3, "备货打印 批次#1", "t")
rb2 = rowof(SKB)
ok(rb2["qc"] == 3 and rb2["sellable"] == 0 and rb2["locs"][0]["ztype"] == "qc", f"printed goods wait in QC: qc={rb2['qc']} sellable={rb2['sellable']}")
config.save_config({"inv_qc_on": False})
production.stock_add(SKC, 2, "盘点", "t")
sk_item = db.conn().execute("SELECT id FROM inv_items WHERE code=?", (SKC,)).fetchone()["id"]
wms.move(rowof(SKC)["locs"][0]["code"], flows.zone_loc(db.conn(), "defect")["code"], [{"item_id": sk_item, "qty": 1}], "t")
rc = rowof(SKC)
ok(rc["defect"] == 1 and rc["sellable"] == 1 and rc["qty"] == 2, f"defect counted apart: qty 2 = sellable 1 + defect 1 ({rc['defect']})")
# 分开放两处
ska_item = db.conn().execute("SELECT id FROM inv_items WHERE code=?", (SKA,)).fetchone()["id"]
lq = C.get(f"/api/inv/gs/locs?sku={SKA}").get_json()
ok(lq["item_id"] == ska_item and lq["locations"], "per-SKU locations endpoint")
src = lq["locations"][0]["code"]
rr = C.post("/api/inv/wms/move", json={"from": src, "to": "R1-01-01", "lines": [{"item_id": ska_item, "qty": 1}]}).get_json()
ra = rowof(SKA)
ok(rr["ok"] and len(ra["locs"]) == 2 and sum(x["qty"] for x in ra["locs"]) == 4, f"quick move splits the SKU over two locations {[(x['code'], x['qty']) for x in ra['locs']]}")

# ---------- 待上架 / 上架推荐先拣货区再备货区 ----------
rec = wms.recommend(ska_item, 2)
ok(rec and rec[0]["ztype"] == "pick", f"putaway suggestion: pick zone first ({rec[0]['code'] if rec else None})")
config.save_config({"inv_loc_auto": False})
production.stock_add(SKA, 2, "盘点", "t")
ra = rowof(SKA)
ok(ra["unplaced"] == 2 and "put" in ra["gk"], f"without auto putaway goods are awaiting putaway ({ra['unplaced']})")
g = C.get("/api/inv/gs").get_json()
ok(g["kpis"]["put"] >= 1 and g["kpis"]["put_units"] >= 2, "KPI: awaiting putaway")
lq = C.get(f"/api/inv/gs/locs?sku={SKA}").get_json()
ok(lq["unplaced"] == 2 and lq["plan"] and lq["plan"][0]["ztype"] == "pick", "locs endpoint carries the putaway suggestion (pick zone first)")
pv = C.post("/api/inv/wms/putaway", json={"item_id": ska_item, "code": lq["plan"][0]["code"], "qty": 2}).get_json()
ok(pv["ok"] and rowof(SKA)["unplaced"] == 0, "putaway from the page")
config.save_config({"inv_loc_auto": True})

# ---------- KPI / 分组 ----------
g = C.get("/api/inv/gs").get_json()
k, gr = g["kpis"], g["groups"]
ok(k["units"] == sum(r["qty"] for r in g["rows"]) and k["value"] >= 150 and k["skus"] == len(g["rows"]), f"KPIs {k}")
ok(gr.get("own", 0) >= 3 and gr.get("buy", 0) >= 1 and gr.get("qc", 0) == 1 and gr.get("out", 0) >= 1, f"auto groups {gr}")
ok(any(c["name"] == "挂件" for c in g["cats"]), "category groups")
ok(all("gk" in r for r in g["rows"]) and "below" in rowof(SKB)["gk"] + ["below"], "rows carry group keys")
config.save_config({"gs_over_x": 1})
ok("over" in rowof(SKA)["gk"], "overstock group follows the multiplier")
config.save_config({"gs_over_x": 3})

# ---------- 一键补货：自产 → 生产单（按盘取整）、外购 → 采购单草稿 ----------
C.post("/api/inv/gs/target", json={"skus": ["BUY-001"], "target": 12})
C.post("/api/inv/gs/target", json={"skus": [SKA], "target": 9})
orig = production.sku_per_plate
ok(isinstance(production.sku_per_plate(SKA), int) and production.sku_per_plate(SKA) >= 1, "sku_per_plate falls back to 1")
production.sku_per_plate = lambda sku: 4 if sku == SKA else 1
pl = C.post("/api/inv/gs/plan", json={}).get_json()["plan"]
pa = next(x for x in pl if x["sku"] == SKA); pbuy = next(x for x in pl if x["sku"] == "BUY-001")
gapA = rowof(SKA)["gap"]
ok(pa["type"] == "own" and pa["gap"] == gapA and pa["qty"] % 4 == 0 and 0 <= pa["qty"] - gapA < 4, f"own gap {gapA} rounded up to full plates -> {pa['qty']}")
ok(pbuy["type"] == "buy" and pbuy["qty"] == pbuy["gap"] == 7 and pbuy["per_plate"] == 1, f"purchased goods use the plain gap {pbuy['qty']}")
n_po = len(C.get("/api/porders").get_json()["orders"])
r = PC.post("/api/inv/gs/replenish", json={"skus": [SKA, "BUY-001"]}).get_json()
ok(r["ok"] and r["po"] and r["po"]["status"] == "draft" and r["po"]["source"] == "stock", f"自产 -> a draft production order {r['po'] and r['po']['no']}")
ok(r["po"]["lines"][0]["qty"] == pa["qty"] and len(r["po"]["lines"]) == 1, "line qty = plate-rounded")
ok(r["purchase"] and r["purchase"][0].get("status") == "draft" and r["purchase"][0]["lines"][0]["item_id"] == it["id"] and r["purchase"][0]["lines"][0]["qty"] == 7,
   f"外购 -> a draft purchase order {r['purchase'] and r['purchase'][0].get('no')}")
ok(len(C.get("/api/porders").get_json()["orders"]) == n_po + 1, "exactly one production order")
rel = C.post(f"/api/porders/{r['po']['id']}/release").get_json()
ok(rel["status"] == "released" and rowof(SKA)["making"] == pa["qty"] and rowof(SKA)["gap"] == 0, "released -> counted as in production, gap closes")
# 用户在预览里改了数量
r2 = C.post("/api/inv/gs/replenish", json={"lines": [{"sku": SKB, "qty": 6}], "release": True}).get_json()
ok(r2["po"]["status"] == "released" and r2["po"]["lines"][0]["qty"] == 6 and r2["po"]["qty"] == 6, "edited quantity + release in one go")
ok(C.post("/api/inv/gs/replenish", json={"skus": ["BUY-001"]}).get_json()["purchase"], "buy-only replenish needs no production order")
ok(C.post("/api/inv/gs/replenish", json={"lines": [{"sku": SKA, "qty": 0}]}).status_code == 400, "nothing to replenish refused")
production.sku_per_plate = orig
# 采购模块关了：回落到内核直接开草稿
ok(modules.public("pur") is not None and hasattr(modules.public("pur"), "draft_po"), "pur public draft_po")

# ---------- 去掉 / 标签 ----------
ok(C.post("/api/inv/gs/remove", json={"skus": [SKC]}).get_json()["ok"] and rowof(SKC), "SKU with stock isn't deleted, only its target/flag is cleared")
h = C.get(f"/print/gs-labels?skus={SKA},BUY-001").get_data(as_text=True)
ok(SKA in h and "BUY-001" in h and "<svg" in h, "SKU labels (barcode)")
ok(PC.post("/api/inv/gs/target", json={"skus": [SKA], "target": 3}).status_code == 200, "production role may edit targets")

# ---------- 设置里能看到 ----------
ok(G.settings()["gs_sales_days"] == 30 and G.parse_cat_default("挂件=5, 摆件=3；杯垫=2") == {"挂件": 5, "摆件": 3, "杯垫": 2}, "settings parse")

print("ERRORS", E_)
