# 货位：v2.33 建；v2.34「区+货架号-层-位」（A1-02-03）；v2.35 一个物品一个货位、数量只记在物品上：
# 批量建货架（建几个）、加层 / 加位、删空的、货架 / 区放哪些分类、新物品第一次入库自动放空格、放物品 / 换货位 / 拿下、
# 没货位的物品、扫码找货位 / 货架 / 物品、按货架盘点、标签、拣货单按货位排、v2.33 / v2.34 旧数据迁移
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D = T + "/m_loc"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, inventory as inv, production, store
from modules.inv import locations as L
C = A.app.test_client()
loc_of = lambda iid: inv.get_item(iid)["location"]
# 编号
ok(L.norm_code("a1-2-3") == "A1-02-03" and L.parse("A1-02-03") == ("A", 1, 2, 3) and L.parse("A-01-03") is None, "code normalize / parse")
ok(sorted(["A10-01-01", "B1-01-01", "A2-02-01", "A2-01-05"], key=L.sort_key) == ["A2-01-05", "A2-02-01", "A10-01-01", "B1-01-01"], "natural sort")
ok(L.human("A1-02-03") == "A区 1号货架 第2层 第3位" and "แร็ค 1" in L.human("A1-02-03", "th"), "human text")
# 还没建货位：照常记账，物品没有货位
box = C.post("/api/inv/items", json={"name_zh": "纸箱 S", "category": "pack", "unit": "个"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": box["id"], "qty": 5}], "", "t")
ok(not loc_of(box["id"]) and inv.get_item(box["id"])["qty"] == 5, "no locations yet -> no location, qty ok")
# 批量建货架：B 区，从 1 号开始建 2 个，每个 2 层 × 3 位，放包材
r = C.post("/api/inv/locations/bulk", json={"zone": "b", "count": 2, "layers": 2, "positions": 3, "name": "包材架", "categories": ["pack", "坏的"]}).get_json()
ok(r["ok"] and r["shelves"] == ["B1", "B2"] and len(r["made"]) == 12 and r["made"][0] == "B1-01-01" and r["made"][-1] == "B2-02-03", f"bulk shelves {r.get('shelves')}")
gs = L.groups(); ok(gs["B1"]["categories"] == ["pack"] and gs["B2"]["name"] == "包材架 2", f"shelf groups {gs}")
ok(len(C.post("/api/inv/locations/bulk", json={"zone": "B", "shelf": 1, "layers": 2, "positions": 3}).get_json()["made"]) == 0, "bulk skips existing")
r = C.post("/api/inv/locations/bulk", json={"zone": "B", "layers": 1, "positions": 2}).get_json()
ok(r["shelf"] == "B3" and r["made"] == ["B3-01-01", "B3-01-02"], f"next shelf number {r}")
ok(C.post("/api/inv/locations/group", json={"code": "B", "name": "包材区", "categories": ["pack"]}).get_json()["ok"], "zone B for pack (B3 inherits)")
C.post("/api/inv/locations/bulk", json={"zone": "A", "shelf": 1, "layers": 1, "positions": 2})
ok(C.post("/api/inv/locations/bulk", json={"zone": "坏", "layers": 1, "positions": 1}).status_code == 400, "bad zone rejected")
ok(C.post("/api/inv/locations/bulk", json={"zone": "A", "layers": 21, "positions": 1}).status_code == 400, "too many layers rejected")
ok(C.post("/api/inv/locations/bulk", json={"zone": "A", "count": 21, "layers": 1, "positions": 1}).status_code == 400, "too many shelves rejected")
ok(C.post("/api/inv/locations", json={"code": "A1-01-01"}).status_code == 400, "duplicate single")
ok(C.post("/api/inv/locations/group", json={"code": "A", "name": "工具区", "categories": ["tool"]}).get_json()["ok"], "zone group")
ok(C.post("/api/inv/locations/group", json={"code": "A1-01"}).status_code == 400, "bad group code")
# 已有的物品再入库：还没货位 → 自动放到放包材的货架第一个空格
inv.create_doc("purchase", [{"item_id": box["id"], "qty": 10}], "", "t")
ok(loc_of(box["id"]) == "B1-01-01" and inv.get_item(box["id"])["qty"] == 15, f"auto place on stock-in {loc_of(box['id'])}")
tape = C.post("/api/inv/items", json={"name_zh": "胶带", "category": "pack", "unit": "卷"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": tape["id"], "qty": 4}], "", "t")
ok(loc_of(tape["id"]) == "B1-01-02", "new pack item -> next empty on pack shelf")
tool = C.post("/api/inv/items", json={"name_zh": "铲刀", "category": "tool", "unit": "把"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": tool["id"], "qty": 2}], "", "t")
ok(loc_of(tool["id"]) == "A1-01-01", "zone category -> zone empty")
# 没指定分类的物品：没有「不限分类」的空格 → 不放（不会塞进别的分类的货架）
o1 = C.post("/api/inv/items", json={"name_zh": "杂物", "category": "other", "unit": "个"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": o1["id"], "qty": 1}], "", "t")
ok(not loc_of(o1["id"]), "no suitable empty cell -> no location")
un = C.get("/api/inv/locations/unassigned").get_json()["items"]
ok([x["item"]["id"] for x in un] == [o1["id"]] and un[0]["suggest"] is None, f"unassigned list {un}")
# 物品资料里选货位（写法自动规范；不存在的不让存）
part = C.post("/api/inv/items", json={"name_zh": "喷嘴", "category": "part", "unit": "个", "location": "b2-1-2"}).get_json()["item"]
ok(part["location"] == "B2-01-02", "item location normalized")
ok(C.post("/api/inv/items", json={"id": part["id"], "location": "Z9-01-01"}).status_code == 400, "unknown location rejected")
inv.create_doc("purchase", [{"item_id": part["id"], "qty": 3}], "", "t")
ok(loc_of(part["id"]) == "B2-01-02", "chosen location kept on stock-in")
# 货架上显示：格子里的物品和现在的数量（就是库存数）
lst = C.get("/api/inv/locations").get_json()
cell = {l["code"]: l for l in lst["locations"]}
ok(cell["B1-01-01"]["items"] == 1 and cell["B1-01-01"]["qty"] == 15 and cell["B1-01-01"]["top"][0]["code"] == box["code"], "cell shows item + qty")
ok(lst["unassigned"] == 1 and lst["groups"]["A"]["categories"] == ["tool"] and lst["layer_bottom"] is True, "list meta")
inv.create_doc("issue", [{"item_id": box["id"], "qty": 6}], "", "t")
ok({l["code"]: l for l in C.get("/api/inv/locations").get_json()["locations"]}["B1-01-01"]["qty"] == 9, "issue -> cell qty follows stock")
C.post("/api/inv/items", json={"id": box["id"], "reorder_point": 10})
ok({l["code"]: l for l in C.get("/api/inv/locations").get_json()["locations"]}["B1-01-01"]["low"] is True, "low stock flag")
# 放物品 / 换货位 / 拿下
r = C.post("/api/inv/locations/assign", json={"item_id": tape["id"], "code": "b2-1-1"}).get_json()
ok(r["ok"] and loc_of(tape["id"]) == "B2-01-01", "move item to another cell")
ok(C.post("/api/inv/locations/assign", json={"item_id": tape["id"], "code": "Q1-01-01"}).status_code == 400, "assign unknown cell")
C.post("/api/inv/locations/assign", json={"item_id": tape["id"], "code": ""})
ok(not loc_of(tape["id"]), "take item down")
r = C.post("/api/inv/locations/assign-all", json={}).get_json()
ok(any(x["item_id"] == tape["id"] and x["code"].startswith("B") for x in r["done"]), f"assign-all puts pack item back {r}")
# 扫码
d = C.get("/api/inv/locations/find?code=b1-1-1").get_json()
ok(d["ok"] and d["type"] == "location" and d["location"]["code"] == "B1-01-01" and d["items"][0]["id"] == box["id"], "find location")
ok(d["location"]["human_zh"] == "B区 1号货架 第1层 第1位", "detail has human text")
ok(C.get("/api/inv/locations/find?code=B1").get_json()["type"] == "shelf", "find shelf")
d = C.get(f"/api/inv/locations/find?code={box['code'].lower()}").get_json()
ok(d["type"] == "item" and d["location"]["code"] == "B1-01-01", "find item -> its location")
ok(C.get("/api/inv/locations/find?code=NOPE").status_code == 404, "find unknown")
it = C.get(f"/api/inv/items/{box['id']}").get_json(); ok(it["loc"]["code"] == "B1-01-01" and it["loc"]["human_zh"].startswith("B区"), "item detail has location")
it = C.get(f"/api/inv/items/{o1['id']}").get_json(); ok(it["loc"]["code"] == "" and "suggest" in it["loc"], "item without location")
# 加一层 / 加一位 / 删
r = C.post("/api/inv/locations/add", json={"shelf": "B1"}).get_json(); ok(r["made"] == ["B1-03-01", "B1-03-02", "B1-03-03"], f"add layer {r}")
r = C.post("/api/inv/locations/add", json={"shelf": "B1", "layer": 1}).get_json(); ok(r["made"] == ["B1-01-04"], f"add position {r}")
ok(C.post("/api/inv/locations/remove", json={"shelf": "B1", "layer": 3}).get_json()["removed"] == 3, "remove empty layer")
ok(C.post("/api/inv/locations/remove", json={"shelf": "B1"}).status_code == 400, "can't remove shelf with items")
ok(C.post("/api/inv/locations/remove", json={"shelf": "B3"}).get_json()["removed"] == 2 and "B3" not in L.groups(), "remove empty shelf")
b11 = L.get_loc("B1-01-01")["id"]; ok(C.delete(f"/api/inv/locations/{b11}").status_code == 400, "can't delete cell with items")
a12 = L.get_loc("A1-01-02")["id"]; ok(C.delete(f"/api/inv/locations/{a12}").get_json()["ok"], "delete empty cell")
# 按货架盘点：只列 B1 上的物品
st = C.post("/api/inv/stocktake", json={"area": "B1"}).get_json()
ok(st["ok"] and {l["item_id"] for l in st["doc"]["lines"]} == {i["id"] for i in inv.items() if (i.get("location") or "").startswith("B1-")} and st["doc"]["ref"] == "area:B1", "stocktake by shelf")
ln = next(x for x in st["doc"]["lines"] if x["item_id"] == box["id"])
C.post(f"/api/inv/stocktake/{st['doc']['id']}/save", json={"counts": {str(ln["id"]): 8}}); C.post(f"/api/inv/stocktake/{st['doc']['id']}/confirm")
ok(inv.get_item(box["id"])["qty"] == 8 and loc_of(box["id"]) == "B1-01-01", "stocktake adjusts stock, location kept")
ok(C.post("/api/inv/stocktake", json={"area": "Q9"}).status_code == 400, "stocktake unknown area")
# 标签
html = C.get("/print/inv-locations").get_data(as_text=True)
ok(html.count('class="lb"') == len(L.locations()) and "B区 1号货架 第2层 第3位" in html, "location labels")
html = C.get("/print/inv-locations?shelf=B2&lang=th").get_data(as_text=True); ok(html.count('class="lb"') == 6 and "แร็ค 2" in html, "shelf labels (th)")
html = C.get("/print/inv-locations?kind=shelf").get_data(as_text=True); ok("包材架 1" in html and "B区 1号货架" in html, "shelf signs")
# 成品：备货入库自动放到放成品的货架；拣货单按货位
C.post("/api/inv/locations/bulk", json={"zone": "C", "shelf": 10, "layers": 1, "positions": 2, "categories": ["goods"]})
sku = store.load(store.list_products()[0]["id"])["variants"][0]["sku"]
production.stock_add(sku, 3, "备货打印 批次#1", "t", sku.split("-")[0], "测试", "白色")
ok(L.where_is(sku) == [("C10-01-01", 3)], f"goods stock placed {L.where_is(sku)}")
config.save_config({"review_enabled": False})
o = C.post("/api/orders/manual", json={"order_no": "LOC-1", "order_total": 99, "items": [{"sku": sku, "qty": 1}]}).get_json()
ph = C.get(f"/print/orders?type=pick&ids={o['id']}").get_data(as_text=True)
ok("C10-01-01" in ph and "货位" in ph, "pick list shows location")
# 旧数据迁移：v2.33 编号（区-货架-格）、v2.34 按货位记数量 → 一物一位
c = db.conn()
c.execute("INSERT INTO inv_locations(code, zone, note, active, created_at) VALUES('E-02-05','E','',1,0)")
for code in ("E2-01-01", "E2-01-02", "E2-01-03"):
    p_ = L.parse(code); c.execute("INSERT INTO inv_locations(code, zone, shelf, layer, pos, note, active, created_at) VALUES(?,?,?,?,?,'',1,0)", (code, *p_))
ids = {r["code"]: r["id"] for r in c.execute("SELECT id, code FROM inv_locations")}
x = C.post("/api/inv/items", json={"name_zh": "旧物品 X", "category": "part", "unit": "个"}).get_json()["item"]
y = C.post("/api/inv/items", json={"name_zh": "旧物品 Y", "category": "part", "unit": "个"}).get_json()["item"]
c.execute("UPDATE inv_items SET location='E2' WHERE id=?", (x["id"],)); c.execute("UPDATE inv_items SET location=NULL WHERE id=?", (y["id"],))
z = C.post("/api/inv/items", json={"name_zh": "旧物品 Z", "category": "part", "unit": "个", "note": "易碎"}).get_json()["item"]
c.execute("UPDATE inv_items SET location='门口铁架第2层' WHERE id=?", (z["id"],))      # 以前随手写的位置
c.execute("INSERT INTO inv_loc_stock(item_id, loc_id, qty) VALUES(?,?,5)", (x["id"], ids["E2-01-02"]))
c.execute("INSERT INTO inv_loc_stock(item_id, loc_id, qty) VALUES(?,?,1)", (x["id"], ids["E2-01-01"]))
c.execute("INSERT INTO inv_loc_stock(item_id, loc_id, qty) VALUES(?,?,2)", (y["id"], ids["E2-01-03"]))
c.commit()
config.save_config({"inv_loc_zones": "备件=E", "inv_loc_v235": False})
L.init()
ok(L.get_loc("E2-01-05") and L.get_loc("E-02-05")["code"] == "E2-01-05", "v2.33 code migrated, old label still scans")
ok(loc_of(x["id"]) == "E2-01-02" and loc_of(y["id"]) == "E2-01-03", f"v2.34 per-cell stock -> one place {loc_of(x['id'])} {loc_of(y['id'])}")
ok(loc_of(box["id"]) == "B1-01-01" and config.load_config().get("inv_loc_v235") is True, "valid locations kept, migrate once")
ok(L.groups()["E"]["categories"] == ["part"], "old zone setting migrated")
zi = inv.get_item(z["id"]); ok(not zi["location"] and zi["note"] == "易碎；原位置：门口铁架第2层", f"free-text location kept in note {zi['note']}")
# 改物品的别的字段时，原来的货位没改就不检查
c.execute("UPDATE inv_items SET location='旧写法' WHERE id=?", (z["id"],)); c.commit()
r = C.post("/api/inv/items", json={"id": z["id"], "name_zh": "旧物品 Z2", "category": "part", "location": "旧写法"})
ok(r.status_code == 200 and inv.get_item(z["id"])["name_zh"] == "旧物品 Z2", "unchanged location not re-validated")
ok(C.post("/api/inv/items", json={"id": z["id"], "name_zh": "旧物品 Z2", "category": "part", "location": "新写法"}).status_code == 400, "changed bad location rejected")
# 设置
sch = {m["id"]: m for m in C.get("/api/settings/schema").get_json()["modules"]}
g = next((g for g in sch["inventory"]["groups"] if g["title"] == "货位"), None)
ok(g is not None and "inv_loc_layer_bottom" in str(g) and "inv_loc_auto" in str(g), "settings group")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
