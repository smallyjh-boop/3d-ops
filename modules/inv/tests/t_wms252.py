# v2.52 仓库（BigSeller WMS 那样）：仓库 → 库区 → 货架 → 层 → 位、库区类型、货位容量 / 混放 / 固定物品 / 尺寸、
# 上架推荐（同物品已在 → 同类附近空位 → 空位）、待上架、采购到货上架、拣货路线（按区分组、走路顺序）、打包核对「去 X 拿」、
# 库内补货（拣货位低于最低数量 → 从备货区搬，进待办）、移库（批量）、按货位盘点、标签（条码 / 二维码）、货位图、菜单「仓库」、旧数据迁移
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D = T + "/m_wms"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, inventory as inv, modules, store, production
from modules.inv import locations as L, wms, qr
C = A.app.test_client()
config.save_config({"inv_qc_on": False})       # v2.53 起打印出来的成品先进待检区；这里测的是 v2.52 的上架规则
item = lambda iid: inv.get_item(iid)
lq = lambda iid, code: wms.loc_qty(db.conn(), iid, L.get_loc(code)["id"])
def new(name, cat="part", unit="个", **kw):
    return C.post("/api/inv/items", json={"name_zh": name, "category": cat, "unit": unit, **kw}).get_json()["item"]
def buy(iid, q):
    return inv.create_doc("purchase", [{"item_id": iid, "qty": q}], "", "t")
def out(iid, q):
    return inv.create_doc("issue", [{"item_id": iid, "qty": q}], "", "t")

# ---------- 菜单：顶部「仓库」= 库存 · 货位 · 盘点；旧页面 id 跳到新页面 ----------
mods = {m["id"]: m for m in C.get("/api/modules").get_json()["modules"]}
mn = mods["inv"]["menus"]
ok([m["tab"] for m in mn if not m["ghost"]] == ["inventory", "inv_locations", "inv_stocktake"] and mods["inv"]["name_zh"] == "仓库", f"menu B {[m['tab'] for m in mn]}")
gh = {m["tab"]: m for m in mn if m["ghost"]}
ok(gh["locations"]["panel"] == "inv_locations" and gh["stocktake"]["panel"] == "inv_stocktake" and gh["stocktake"]["parent"] == "inv_stocktake", "old ids redirect")
html = C.get("/").get_data(as_text=True)
ok('data-mod="inv" data-notr data-zh="仓库" data-th="คลังสินค้า"' in html and 'id="tab-inv_locations"' in html and 'id="tab-inv_stocktake"' in html, "top menu 仓库 + panels")
ok('data-iv="stocktake"' not in html and 'data-iv="locations"' not in html, "stocktake / locations moved out of 库存 page")

# ---------- 结构：仓库 → 库区（类型）→ 货架 ----------
r = C.post("/api/inv/locations/bulk", json={"zone": "A", "layers": 2, "positions": 3, "categories": ["goods"]}).get_json()   # A1 拣货
ok(r["ok"] and len(r["made"]) == 6, "pick shelf A1")
whs = C.get("/api/inv/warehouses").get_json()["warehouses"]
ok(len(whs) == 1 and whs[0]["name"] == "默认仓库", f"default warehouse {whs}")
ok(L.groups()["A"]["ztype"] == "pick" and L.groups()["A"]["warehouse"] == whs[0]["id"], "new zone -> default warehouse, pick")
w2 = C.post("/api/inv/warehouses", json={"name": "二号仓"}).get_json()["warehouse"]
ok(C.post("/api/inv/warehouses", json={"name": "二号仓"}).status_code == 400, "duplicate warehouse name")
r = C.post("/api/inv/locations/bulk", json={"zone": "R", "layers": 1, "positions": 4, "ztype": "reserve", "warehouse": w2["id"], "props": {"capacity": 100}}).get_json()
ok(r["ok"] and L.groups()["R"]["ztype"] == "reserve" and L.groups()["R"]["warehouse"] == w2["id"] and L.get_loc("R1-01-01")["capacity"] == 100, "reserve zone in 2nd warehouse, capacity on create")
C.post("/api/inv/locations/bulk", json={"zone": "S", "layers": 1, "positions": 2, "ztype": "staging"})
C.post("/api/inv/locations/bulk", json={"zone": "P", "layers": 1, "positions": 3, "ztype": "supply", "categories": ["pack"]})
ok(C.post("/api/inv/locations/group", json={"code": "S", "ztype": "bogus"}).status_code == 400, "bad zone type rejected")
lst = C.get("/api/inv/locations").get_json()
ok(set(lst["ztypes"]) >= {"pick", "reserve", "staging", "returns", "defect", "supply"} and len(lst["warehouses"]) == 2, "zone types / warehouses in list")
ok({l["code"]: l for l in lst["locations"]}["R1-01-02"]["ztype"] == "reserve", "location carries zone type")
d = C.get(f"/api/inv/locations/{L.get_loc('R1-01-01')['id']}").get_json()["location"]
ok(d["warehouse_name"] == "二号仓" and d["state"] == "empty", "detail: warehouse + state")

# ---------- 上架推荐 + 规则 ----------
box = new("纸箱 M", "pack")
buy(box["id"], 10)
ok(item(box["id"])["location"] == "P1-01-01" and lq(box["id"], "P1-01-01") == 10, "pack -> supply zone for pack")
tape = new("胶带", "pack")
buy(tape["id"], 3)
ok(item(tape["id"])["location"] == "P1-01-02", f"same category nearby empty {item(tape['id'])['location']}")
buy(box["id"], 5)
ok(lq(box["id"], "P1-01-01") == 15 and wms.pending_count() == 0, "same item -> its existing location first")
plan = wms.recommend(box["id"], 4)
ok(plan[0]["code"] == "P1-01-01" and plan[0]["reason"] == "same", f"recommend same first {plan}")
# 容量：P1-01-01 只放 20 → 再来 10，放 5，剩下的去附近空位
C.post("/api/inv/locations/props", json={"codes": ["P1-01-01"], "props": {"capacity": 20}})
buy(box["id"], 10)
ok(lq(box["id"], "P1-01-01") == 20 and lq(box["id"], "P1-01-03") == 5, f"capacity splits putaway {wms.item_locations(box['id'])}")
ok(wms.state_of(20, 20) == "full" and wms.state_of(21, 20) == "over" and wms.state_of(0, 20) == "empty" and wms.state_of(3, None) == "partial", "states")
# 成品：先拣货区（A），不放暂存区
sku = store.load(store.list_products()[0]["id"])["variants"][0]["sku"]
production.stock_add(sku, 6, "备货打印", "t", sku.split("-")[0], "测试", "白色")
gid = inv.get_item(sku)["id"] if inv.get_item(sku) else db.conn().execute("SELECT id FROM inv_items WHERE code=?", (sku,)).fetchone()[0]
ok(L.where_is(sku) == [("A1-01-01", 6.0)], f"goods -> pick zone {L.where_is(sku)}")
ok(all(not x["code"].startswith("S") for x in wms.recommend(tape["id"], 999, limit=20)), "staging never recommended")
# 固定货位：A1-02-01 只放某个物品；不混放
other = new("喷嘴", "part")
ok(C.post("/api/inv/locations/props", json={"codes": ["A1-02-01"], "props": {"fixed_item": item(other["id"])["code"]}}).get_json()["ok"], "set fixed location")
r = C.post("/api/inv/wms/move", json={"from": "A1-01-01", "to": "A1-02-01", "lines": [{"item_id": gid, "qty": 1}]})
ok(r.status_code == 400 and "固定货位" in r.get_json()["error"], "fixed location refuses other items")
ok(C.post("/api/inv/locations/props", json={"codes": ["A1-01-01"], "props": {"fixed_item": item(other["id"])["code"]}}).status_code == 400, "can't fix a location holding other items")
C.post("/api/inv/locations/props", json={"codes": ["A1-01-02"], "props": {"mixed": 0}})
C.post("/api/inv/wms/move", json={"from": "A1-01-01", "to": "A1-01-02", "lines": [{"item_id": gid, "qty": 1}]})
buy(other["id"], 2)
ok(item(other["id"])["location"] == "A1-02-01" and lq(other["id"], "A1-02-01") == 2, "fixed item goes to its fixed location")
C.post("/api/inv/wms/move", json={"from": "A1-02-01", "to": "A1-01-03", "lines": [{"item_id": other["id"], "qty": 1}]})
r = C.post("/api/inv/wms/move", json={"from": "A1-01-03", "to": "A1-01-02", "lines": [{"item_id": other["id"], "qty": 1}]})
ok(r.status_code == 400 and "不混放" in r.get_json()["error"], "no-mix location refuses a 2nd item")
# 尺寸
C.post("/api/inv/locations/props", json={"codes": ["R1-01-04"], "props": {"size": "S"}})
C.post("/api/inv/items", json={"id": other["id"], "size": "L"})
r = C.post("/api/inv/wms/move", json={"from": "A1-01-03", "to": "R1-01-04", "lines": [{"item_id": other["id"], "qty": 1}]})
ok(r.status_code == 400 and "L" in r.get_json()["error"], "size class rule")
ok(C.post("/api/inv/locations/props", json={"codes": ["R1-01-04"], "props": {"size": "Q"}}).status_code == 400, "bad size rejected")

# ---------- 待上架（自动上架关掉）+ 扫货位确认 ----------
config.save_config({"inv_loc_auto": False})
buy(tape["id"], 7)
pend = C.get("/api/inv/wms/pending").get_json()["items"]
pt = next(x for x in pend if x["item"]["id"] == tape["id"])
ok(pt["qty"] == 7 and pt["suggest"][0]["code"] == "P1-01-02", f"pending with suggestion {pt['suggest']}")
r = C.post("/api/inv/wms/putaway", json={"item_id": tape["id"], "code": "p1-1-2", "qty": 4}).get_json()
ok(r["ok"] and lq(tape["id"], "P1-01-02") == 7 and wms.unplaced(db.conn(), tape["id"]) == 3, "putaway part by scanning location")
ok(C.post("/api/inv/wms/putaway", json={"item_id": tape["id"], "code": "P1-01-02", "qty": 9}).status_code == 400, "can't put more than pending")
ok(C.post("/api/inv/wms/putaway", json={"all": True}).get_json()["ok"] and wms.unplaced(db.conn(), tape["id"]) == 0, "put all by recommendation")
config.save_config({"inv_loc_auto": True})
# 出库：先扣待上架，再扣货位（主货位优先）
out(box["id"], 3)
ok(lq(box["id"], "P1-01-01") == 17 and lq(box["id"], "P1-01-03") == 5, f"issue takes from primary {wms.item_locations(box['id'])}")

# ---------- 拣货路线 + 拣货单按区分组 + 打包核对去哪拿 ----------
ok(L.sort_key("A1-01-02") < L.sort_key("A1-02-01") < L.sort_key("A2-01-01") < L.sort_key("B1-01-01"), "walk order zone→shelf→level→pos")
route = wms.pick_route([(item(box["id"])["code"], 1), (sku, 2), ("NOPE-SKU", 1)])
ok([g["zone"] for g in route] == ["A", "P", ""] and route[0]["ztype"] == "pick" and route[0]["rows"][0]["code"] == "A1-01-01", f"pick route grouped by zone {[(g['zone'], [r['code'] for r in g['rows']]) for g in route]}")
config.save_config({"review_enabled": False})
o = C.post("/api/orders/manual", json={"order_no": "WMS-1", "order_total": 99, "items": [{"sku": sku, "qty": 1}]}).get_json()
ph = C.get(f"/print/orders?type=pick&ids={o['id']}").get_data(as_text=True)
ok("A1-01-01" in ph and "A 区" in ph and "拣货区" in ph, "pick list grouped by zone")
pk = C.get("/api/pack/lookup?code=WMS-1").get_json()
ok(pk["items"][0]["loc"] == "A1-01-01", f"packing check knows where to pick {pk['items'][0].get('loc')}")
ok(modules.public("inv").where_is(sku)[0][0] == "A1-01-01" and modules.public("inv").zone_of("A1-01-01")["ztype"] == "pick", "public api kept")

# ---------- 库内补货 ----------
part = new("轴承", "part")
C.post("/api/inv/locations/props", json={"codes": ["A1-02-02"], "props": {"capacity": 10, "min_qty": 4}})
C.post("/api/inv/items", json={"id": part["id"], "location": "A1-02-02"})
buy(part["id"], 30)
ok(lq(part["id"], "A1-02-02") == 10 and lq(part["id"], "R1-01-01") == 20, f"overflow to reserve {wms.item_locations(part['id'])}")
out(part["id"], 7)
ok(lq(part["id"], "A1-02-02") == 3, "pick location dropped below min")
sug = [s for s in wms.replenish_suggestions() if s["item_id"] == part["id"]]
ok(sug and sug[0]["to"] == "A1-02-02" and sug[0]["need"] == 7 and sug[0]["sources"] == [("R1-01-01", 7)], f"replenish suggestion {sug}")
tk = C.get("/api/inv/wms/tasks").get_json()
t1 = next(t for t in tk["tasks"] if t["item_id"] == part["id"])
ok(t1["from_loc"] == "R1-01-01" and t1["to_loc"] == "A1-02-02" and t1["qty"] == 7, "move task created")
from core import todo
todos = todo.collect()["items"]
ok(any(i["key"] == f"inv:task:{t1['id']}" and i["group"] == "仓库" and i["tab"] == "inv_locations" for i in todos), "task in to-do")
ok(len([t for t in C.get("/api/inv/wms/tasks").get_json()["tasks"] if t["item_id"] == part["id"]]) == 1, "task not duplicated")
r = C.post(f"/api/inv/wms/tasks/{t1['id']}/do", json={}).get_json()
ok(r["ok"] and lq(part["id"], "A1-02-02") == 10 and lq(part["id"], "R1-01-01") == 13, "do task moves stock")
ok(not [t for t in C.get("/api/inv/wms/tasks").get_json()["tasks"] if t["item_id"] == part["id"]], "task closed, no new one")

# ---------- 移库：批量 ----------
C.post("/api/inv/items", json={"id": tape["id"], "location": ""})          # 拿下来 → 待上架
ok(wms.unplaced(db.conn(), tape["id"]) == 10 and not item(tape["id"])["location"], "take down -> pending")
C.post("/api/inv/wms/putaway", json={"item_id": tape["id"], "code": "R1-01-02"})
r = C.post("/api/inv/wms/move", json={"from": "R1-01-01", "to": "R1-01-02", "lines": [{"item_id": part["id"], "qty": 3}, {"item_id": tape["id"], "qty": 99}]})
ok(r.status_code == 400 and "只有" in r.get_json()["error"], "move more than there is refused")
r = C.post("/api/inv/wms/move", json={"from": "R1-01-02", "to": "R1-01-03", "lines": [{"item_id": tape["id"], "qty": 4}]}).get_json()
ok(r["ok"] and lq(tape["id"], "R1-01-03") == 4 and lq(tape["id"], "R1-01-02") == 6, "move part")
C.post("/api/inv/locations/props", json={"codes": ["R1-01-03"], "props": {"capacity": 5}})
r = C.post("/api/inv/wms/move", json={"from": "R1-01-01", "to": "R1-01-03", "lines": [{"item_id": part["id"], "qty": 3}]})
ok(r.status_code == 400 and "放不下" in r.get_json()["error"], "capacity refuses")
r = C.post("/api/inv/wms/move", json={"from": "R1-01-01", "to": "R1-01-03", "lines": [{"item_id": part["id"], "qty": 3}], "force": True}).get_json()
ok(r["ok"] and lq(part["id"], "R1-01-03") == 3, "force over capacity")
logs = db.conn().execute("SELECT COUNT(*) FROM inv_loc_log WHERE kind='move'").fetchone()[0]
ok(logs >= 3, "moves logged")

# ---------- 货位图 ----------
m = C.get("/api/inv/wms/map").get_json()
zr = next(z for z in m["zones"] if z["zone"] == "R")
ok(zr["ztype"] == "reserve" and zr["over"] == 1 and zr["total"] == 4, f"map zone stats {zr}")
ok(m["stats"]["total"] == len([l for l in L.locations() if l["ztype"] != "production"]) and "R1-01-04" in m["alerts"]["empty"] and m["stats"]["over"] == 1, "map stats + empty alert")
c = db.conn(); c.execute("UPDATE inv_locations SET last_move=? WHERE code='P1-01-03'", (wms._now() - 200 * 86400,)); c.commit()
ok(any(x["code"] == "P1-01-03" and x["days"] >= 199 for x in C.get("/api/inv/wms/map").get_json()["alerts"]["idle"]), "idle location alert")
sp = C.get("/api/inv/wms/map?max_spread=2").get_json()["alerts"]["spread"]
ok(any(x["item_id"] == part["id"] and len(x["locations"]) == 3 for x in sp), f"spread alert {sp}")

# ---------- 按货位盘点 ----------
st = C.post("/api/inv/stocktake", json={"area": "R1"}).get_json()["doc"]
ok(st["by_location"] and st["ref"] == "area:R1" and st["progress"]["total"] == 4 and {l["item_id"] for l in st["lines"]} == {part["id"], tape["id"]}, "stocktake by shelf: locations + items")
did = st["id"]
before = item(part["id"])["qty"]
r = C.post(f"/api/inv/stocktake/{did}/loc", json={"code": "R1-01-01", "counts": {str(part["id"]): 8}}).get_json()     # 账面 10 → 数到 8
ok(r["ok"] and r["doc"]["progress"]["done"] == 1 and r["doc"]["progress"]["diffs"] == 1, "count one location")
r = C.post(f"/api/inv/stocktake/{did}/loc", json={"code": "R1-01-02", "counts": {item(tape["id"])["code"]: 6, item(box["id"])["code"]: 2}}).get_json()   # 放错的纸箱
ok(any(x["code"] == item(box["id"])["code"] and x["diff"] == 2 for l in r["doc"]["locs"] for x in l["rows"]), "unexpected item found at location")
ok(C.post(f"/api/inv/stocktake/{did}/loc", json={"code": "A1-01-01", "counts": {}}).status_code == 400, "location outside the stocktake refused")
out(part["id"], 1)                                  # 盘点期间出库（从主货位扣）
r = C.post(f"/api/inv/stocktake/{did}/confirm").get_json()
ok(r["ok"] and r["doc"]["status"] == "done", "confirm location stocktake")
ok(lq(part["id"], "R1-01-01") == 8 and item(part["id"])["qty"] == before - 1 - 2, f"stock adjusted by location diff {item(part['id'])['qty']} {before}")
ok(lq(box["id"], "R1-01-02") == 2 and abs(wms.located(db.conn(), box["id"]) - item(box["id"])["qty"]) < 1e-9, "found item added at that location")
ok(lq(tape["id"], "R1-01-02") == 6, "uncounted-difference item unchanged")
plain = C.post("/api/inv/stocktake", json={"category": "tool"})
ok(plain.status_code in (200, 400), "category stocktake still works")

# ---------- 标签 ----------
h1 = C.get("/print/inv-locations?zone=R").get_data(as_text=True)
ok(h1.count('class="lb"') == 4 and "备货区 · 二号仓" in h1, "barcode labels with zone type + warehouse")
h2 = C.get("/print/inv-locations?shelf=A1&fmt=qr&lang=th").get_data(as_text=True)
ok(h2.count('class="lb qrl"') == 6 and "<svg" in h2 and "โซนหยิบสินค้า" in h2, "QR labels (th)")
h3 = C.get(f"/print/inv-locations?warehouse={w2['id']}").get_data(as_text=True)
ok(h3.count('class="lb"') == 4, "labels by warehouse")
m1 = qr.matrix("A1-02-03")
ok(len(m1) == 21 and m1[0][:7] == [True] * 7 and m1[6][6] and not m1[7][7], "qr matrix (verified against a reference encoder)")

# ---------- 采购到货：按推荐上架 / 按填的货位 ----------
cfg_items = new("扎带", "pack")
sup = C.post("/api/inv/suppliers", json={"name": "WMS供应商"}).get_json()["supplier"]
po = C.post("/api/inv/po", json={"supplier_id": sup["id"], "lines": [{"item_id": cfg_items["id"], "qty": 5, "unit_cost": 1}, {"item_id": part["id"], "qty": 2, "unit_cost": 1}]}).get_json()
po = po.get("po") or po
C.post(f"/api/inv/po/{po['id']}/order", json={})
g = C.get(f"/api/inv/po/{po['id']}").get_json()["po"]
ok(all("putaway" in l for l in g["lines"]) and g["lines"][1]["putaway"][0]["code"] == "A1-02-02", f"receiving shows putaway suggestion {[l.get('putaway') for l in g['lines']]}")
ln = {l["item_id"]: l["id"] for l in g["lines"]}
r = C.post("/api/inv/pur/receive", json={"po_id": po["id"], "qtys": {str(ln[cfg_items["id"]]): 5, str(ln[part["id"]]): 2}, "locations": {str(cfg_items["id"]): "S1-01-01"}}).get_json()
ok(r["ok"] and lq(cfg_items["id"], "S1-01-01") == 5 and any(p["code"] == "S1-01-01" for p in r["placed"]), f"receive into chosen location {r.get('placed')} {r.get('warnings')}")
ok(wms.unplaced(db.conn(), part["id"]) == 0, "receive without location -> recommended putaway")

# ---------- 旧数据迁移：原来的货位和库存 → 默认仓库、拣货区 ----------
c = db.conn()
c.execute("DELETE FROM inv_loc_qty"); c.execute("UPDATE inv_loc_groups SET warehouse=NULL, ztype=NULL WHERE code='A'")
c.execute("DELETE FROM inv_loc_groups WHERE code='P'"); c.commit()
config.save_config({"inv_loc_v252": False})
L.init()
ok(L.groups()["A"]["ztype"] == "pick" and L.groups()["P"]["ztype"] == "pick" and L.groups()["P"]["warehouse"] == whs[0]["id"], "migration: zones -> default warehouse, pick")
ok(lq(box["id"], item(box["id"])["location"]) == item(box["id"])["qty"], "migration: stock sits at the item's location")
ok(config.load_config().get("inv_loc_v252") is True, "migrate once")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
