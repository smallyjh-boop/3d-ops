# v2.33 货位管理；v2.34 改成「区+货架号-层-位」（A1-02-03）：建货架、加层 / 加位、删空的、货架放哪些分类、
# 入库自动上架、出库先扣未上架再扣货位、移库、一键上架、货位核对、扫码找货位 / 货架 / 物品、标签、拣货单按货位排、v2.33 旧编号迁移
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
# 编号
ok(L.norm_code("a1-2-3") == "A1-02-03" and L.parse("A1-02-03") == ("A", 1, 2, 3) and L.parse("A-01-03") is None, "code normalize / parse")
ok(sorted(["A10-01-01", "B1-01-01", "A2-02-01", "A2-01-05"], key=L.sort_key) == ["A2-01-05", "A2-02-01", "A10-01-01", "B1-01-01"], "natural sort")
ok(L.human("A1-02-03") == "A区 1号货架 第2层 第3位" and "แร็ค 1" in L.human("A1-02-03", "th"), "human text")
# 建货位之前：照常记账，不出错
box = C.post("/api/inv/items", json={"name_zh": "纸箱 S", "category": "pack", "unit": "个"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": box["id"], "qty": 5}], "", "t")
ok(L.item_locations(box["id"])["unplaced"] == 5, "no locations yet -> all unplaced")
# 建货架：B 区，货架号不填 = 1 号，2 层 × 3 位
r = C.post("/api/inv/locations/bulk", json={"zone": "b", "layers": 2, "positions": 3, "name": "包材架", "categories": ["pack", "坏的"]}).get_json()
ok(r["ok"] and r["shelf"] == "B1" and len(r["made"]) == 6 and r["made"][0] == "B1-01-01" and r["made"][-1] == "B1-02-03", f"bulk shelf {r}")
ok(L.groups()["B1"]["categories"] == ["pack"] and L.groups()["B1"]["name"] == "包材架", f"shelf group {L.groups()}")
ok(len(C.post("/api/inv/locations/bulk", json={"zone": "B", "shelf": 1, "layers": 2, "positions": 3}).get_json()["made"]) == 0, "bulk skips existing")
r = C.post("/api/inv/locations/bulk", json={"zone": "B", "layers": 1, "positions": 2}).get_json()
ok(r["shelf"] == "B2" and r["made"] == ["B2-01-01", "B2-01-02"], f"next shelf number {r}")
C.post("/api/inv/locations/bulk", json={"zone": "A", "shelf": 1, "layers": 1, "positions": 2})
ok(C.post("/api/inv/locations/bulk", json={"zone": "坏", "layers": 1, "positions": 1}).status_code == 400, "bad zone rejected")
ok(C.post("/api/inv/locations/bulk", json={"zone": "A", "layers": 21, "positions": 1}).status_code == 400, "too many layers rejected")
ok(C.post("/api/inv/locations", json={"code": "A1-01-01"}).status_code == 400, "duplicate single")
ok(C.post("/api/inv/locations", json={"code": "XX"}).status_code == 400, "bad single code")
ok(C.post("/api/inv/locations/group", json={"code": "A", "name": "工具区", "categories": ["tool"]}).get_json()["ok"], "zone group")
ok(C.post("/api/inv/locations/group", json={"code": "A1-01"}).status_code == 400, "bad group code")
lst = C.get("/api/inv/locations").get_json()
ok(lst["groups"]["A"]["categories"] == ["tool"] and lst["layer_bottom"] is True and lst["categories"], "list has groups / layer direction / categories")
ok([l["code"] for l in lst["locations"]][:3] == ["A1-01-01", "A1-01-02", "B1-01-01"] and lst["locations"][0]["layer"] == 1, "list sorted, has layer/pos")
# 未上架的一键上架：包材 → B1（放包材的货架）
r = C.get("/api/inv/locations/unplaced").get_json()
ok(any(x["item"]["id"] == box["id"] and x["suggest"]["code"] == "B1-01-01" for x in r["items"]), "unplaced with suggestion on pack shelf")
C.post("/api/inv/locations/putaway", json={})
li = L.item_locations(box["id"])
ok(li["unplaced"] == 0 and li["locations"][0]["code"] == "B1-01-01" and li["locations"][0]["qty"] == 5, f"putaway {li}")
# 入库：自动放进已经在的货位
inv.create_doc("purchase", [{"item_id": box["id"], "qty": 10}], "", "t")
li = L.item_locations(box["id"]); ok(li["locations"][0]["qty"] == 15 and li["unplaced"] == 0, "receive goes to existing location")
# 新物品入库：放这个分类的货架的下一个空位
tape = C.post("/api/inv/items", json={"name_zh": "胶带", "category": "pack", "unit": "卷"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": tape["id"], "qty": 4}], "", "t")
li = L.item_locations(tape["id"]); ok(li["locations"] and li["locations"][0]["code"] == "B1-01-02", f"new item -> next empty on shelf {li}")
# 区级分类：工具 → A 区
tool = C.post("/api/inv/items", json={"name_zh": "铲刀", "category": "tool", "unit": "把"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": tool["id"], "qty": 2}], "", "t")
ok(L.item_locations(tool["id"])["locations"][0]["code"] == "A1-01-01", "zone category -> zone empty")
# 物品资料的默认位置写货架：放到这个货架的空位
part = C.post("/api/inv/items", json={"name_zh": "喷嘴", "category": "part", "unit": "个", "location": "B2"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": part["id"], "qty": 3}], "", "t")
ok(L.item_locations(part["id"])["locations"][0]["code"] == "B2-01-01", "item default location = shelf")
# 移库：B1-01-01 → B1-02-01 移 6 个
b0101, b0201 = L.get_loc("B1-01-01")["id"], L.get_loc("b1-2-1")["id"]
r = C.post("/api/inv/locations/move", json={"item_id": box["id"], "from_loc": b0101, "to_loc": b0201, "qty": 6}).get_json()
ok(r["ok"] and {x["code"]: x["qty"] for x in r["locations"]} == {"B1-01-01": 9, "B1-02-01": 6}, f"move {r.get('locations')}")
ok(C.post("/api/inv/locations/move", json={"item_id": box["id"], "from_loc": b0101, "to_loc": b0201, "qty": 100}).status_code == 400, "can't move more than there")
# 出库：先扣未上架，再从少的货位扣
C.post("/api/inv/locations/move", json={"item_id": box["id"], "from_loc": b0201, "to_loc": 0, "qty": 2})   # 取下 2 个（未上架 2）
inv.create_doc("issue", [{"item_id": box["id"], "qty": 5}], "", "t")
li = L.item_locations(box["id"]); q = {x["code"]: x["qty"] for x in li["locations"]}
ok(li["unplaced"] == 0 and q == {"B1-01-01": 9, "B1-02-01": 1}, f"issue: unplaced first, then smallest location {q} {li['unplaced']}")
ok(sum(q.values()) + li["unplaced"] == inv.get_item(box["id"])["qty"], "location sum == item qty")
# 货位核对：B1-01-01 数到 7（少 2 → 未上架）；再数到 12（从未上架补回 2，再多提示盘点）
r = C.post(f"/api/inv/locations/{b0101}/check", json={"counts": {str(box["id"]): 7}}).get_json()
li = L.item_locations(box["id"]); ok(li["unplaced"] == 2 and r["notes"], "check less -> unplaced")
r = C.post(f"/api/inv/locations/{b0101}/check", json={"counts": {str(box["id"]): 12}}).get_json()
li = L.item_locations(box["id"]); ok(li["unplaced"] == 0 and {x["code"]: x["qty"] for x in li["locations"]}["B1-01-01"] == 9 and r["notes"], "check more -> take unplaced, rest needs stocktake")
# 盘点调账：账上多出 3 个 → 自动放进推荐货位
st = C.post("/api/inv/stocktake", json={"category": "pack"}).get_json()["doc"]
ln = next(x for x in st["lines"] if x["item_id"] == box["id"])
C.post(f"/api/inv/stocktake/{st['id']}/save", json={"counts": {str(ln["id"]): inv.get_item(box["id"])["qty"] + 3}}); C.post(f"/api/inv/stocktake/{st['id']}/confirm")
li = L.item_locations(box["id"]); ok(sum(x["qty"] for x in li["locations"]) + li["unplaced"] == inv.get_item(box["id"])["qty"] and li["unplaced"] == 0, "stocktake gain goes to location")
# 扫码：货位（小写、简写都认）/ 货架 / 物品编码
d = C.get("/api/inv/locations/find?code=b1-1-1").get_json()
ok(d["ok"] and d["type"] == "location" and d["location"]["code"] == "B1-01-01" and d["items"][0]["loc_qty"] > 0 and d["log"], "find location by scan")
ok(d["location"]["human_zh"] == "B区 1号货架 第1层 第1位", "detail has human text")
ok(C.get("/api/inv/locations/find?code=B1").get_json()["type"] == "shelf", "find shelf")
d = C.get(f"/api/inv/locations/find?code={box['code'].lower()}").get_json()
ok(d["type"] == "item" and d["locations"] and d["item"]["id"] == box["id"], "find item -> where it is")
ok(C.get("/api/inv/locations/find?code=NOPE").status_code == 404, "find unknown")
# 加一层 / 加一位 / 删空的层 / 删货架
r = C.post("/api/inv/locations/add", json={"shelf": "B1"}).get_json()
ok(r["made"] == ["B1-03-01", "B1-03-02", "B1-03-03"], f"add layer {r}")
r = C.post("/api/inv/locations/add", json={"shelf": "B1", "layer": 1}).get_json()
ok(r["made"] == ["B1-01-04"], f"add position {r}")
ok(C.post("/api/inv/locations/remove", json={"shelf": "B1", "layer": 3}).get_json()["removed"] == 3, "remove empty layer")
ok(C.post("/api/inv/locations/remove", json={"shelf": "B1"}).status_code == 400, "can't remove non-empty shelf")
C.post("/api/inv/locations/bulk", json={"zone": "D", "layers": 1, "positions": 1, "name": "临时"})
ok(C.post("/api/inv/locations/remove", json={"shelf": "D1"}).get_json()["removed"] == 1 and "D1" not in L.groups(), "remove empty shelf + its group")
ok(C.delete(f"/api/inv/locations/{b0101}").status_code == 400, "can't delete non-empty")
a02 = L.get_loc("A1-01-02")["id"]; ok(C.delete(f"/api/inv/locations/{a02}").get_json()["ok"], "delete empty")
it = C.get(f"/api/inv/items/{box['id']}").get_json(); ok(it["loc"]["locations"] and "suggest" in it["loc"], "item detail has locations")
# 标签
html = C.get("/print/inv-locations").get_data(as_text=True)
n_all = len(L.locations()); ok(html.count('class="lb"') == n_all and "B1-02-03" in html and "B区 1号货架 第2层 第3位" in html, "location labels")
html = C.get("/print/inv-locations?shelf=B2&lang=th").get_data(as_text=True)
ok(html.count('class="lb"') == 2 and "แร็ค 2" in html, "shelf labels (th)")
html = C.get("/print/inv-locations?kind=shelf").get_data(as_text=True)
ok(html.count('class="lb"') == 3 and "包材架" in html and "B区 1号货架" in html, "shelf signs")
# 成品：备货入库进放成品的货架，拣货单按货位
C.post("/api/inv/locations/bulk", json={"zone": "C", "shelf": 10, "layers": 1, "positions": 2, "categories": ["goods"]})
sku = store.load(store.list_products()[0]["id"])["variants"][0]["sku"]
production.stock_add(sku, 3, "备货打印 批次#1", "t", sku.split("-")[0], "测试", "白色")
ok(L.where_is(sku) and L.where_is(sku)[0][0] == "C10-01-01", f"goods stock placed {L.where_is(sku)}")
config.save_config({"review_enabled": False})
o = C.post("/api/orders/manual", json={"order_no": "LOC-1", "order_total": 99, "items": [{"sku": sku, "qty": 1}]}).get_json()
ph = C.get(f"/print/orders?type=pick&ids={o['id']}").get_data(as_text=True)
ok("C10-01-01" in ph and "货位" in ph, "pick list shows location")
# 没指定分类的物品：只放进「没指定分类」的货架；没有了就留在未上架（不会塞进别的分类的货架）
o1 = C.post("/api/inv/items", json={"name_zh": "杂物 1", "category": "other", "unit": "个"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": o1["id"], "qty": 1}], "", "t")
ok(L.item_locations(o1["id"])["locations"][0]["code"] == "B2-01-02", "other category -> unassigned shelf")
o2 = C.post("/api/inv/items", json={"name_zh": "杂物 2", "category": "other", "unit": "个"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": o2["id"], "qty": 2}], "", "t")
li = L.item_locations(o2["id"]); ok(not li["locations"] and li["unplaced"] == 2, f"no suitable empty -> stays unplaced {li}")
ok(C.post("/api/inv/locations/putaway", json={}).get_json()["ok"] and L.item_locations(o2["id"])["unplaced"] == 2, "putaway skips items without a spot")
# v2.33 的旧编号（区-货架-格）和设置「分类=区」自动迁移
c = db.conn()
c.execute("INSERT INTO inv_locations(code, zone, note, active, created_at) VALUES('E-02-05','E','',1,0)")
c.execute("INSERT INTO inv_locations(code, zone, note, active, created_at) VALUES('OLD9','OLD9','',1,0)")
c.commit()
config.save_config({"inv_loc_zones": "备件=E"})
L.init()
ok(L.get_loc("E2-01-05") and L.get_loc("E2-01-05")["layer"] == 1, "old code migrated E-02-05 -> E2-01-05")
ok(L.get_loc("E-02-05")["code"] == "E2-01-05", "old label still scans")
ok(L.groups()["E"]["categories"] == ["part"] and not config.load_config().get("inv_loc_zones"), "old zone setting migrated")
ok(L.get_loc("OLD9")["shelf"] is None, "non-standard code left as is")
# 设置
sch = {m["id"]: m for m in C.get("/api/settings/schema").get_json()["modules"]}
g = next((g for g in sch["inventory"]["groups"] if g["title"] == "货位"), None)
ok(g is not None and "inv_loc_layer_bottom" in str(g), f"settings group {g}")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
