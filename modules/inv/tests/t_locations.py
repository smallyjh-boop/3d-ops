# v2.33：货位管理——批量建货位、入库自动上架（按分类默认区）、出库先扣未上架再扣货位、移库、一键上架、货位核对、标签、拣货单
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
# 建货位之前：照常记账，不出错
box = C.post("/api/inv/items", json={"name_zh": "纸箱 S", "category": "pack", "unit": "个"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": box["id"], "qty": 5}], "", "t")
ok(L.item_locations(box["id"])["unplaced"] == 5, "no locations yet -> all unplaced")
r = C.post("/api/inv/locations/bulk", json={"zone": "B", "shelves": 2, "cells": 3}).get_json()
ok(r["ok"] and len(r["made"]) == 6 and r["made"][0] == "B-01-01", f"bulk {r.get('made')}")
ok(len(C.post("/api/inv/locations/bulk", json={"zone": "B", "shelves": 2, "cells": 3}).get_json()["made"]) == 0, "bulk skips existing")
C.post("/api/inv/locations/bulk", json={"zone": "A", "shelves": 1, "cells": 2})
ok(C.post("/api/inv/locations/bulk", json={"zone": "坏", "shelves": 1, "cells": 1}).status_code == 400, "bad zone rejected")
config.save_config({"inv_loc_zones": "包材=B, 耗材=A", "inv_loc_auto": True})
ok(L.zones_setting() == {"pack": "B", "filament": "A"}, f"zones {L.zones_setting()}")
# 未上架的一键上架
r = C.get("/api/inv/locations/unplaced").get_json()
ok(any(x["item"]["id"] == box["id"] and x["suggest"]["code"].startswith("B-") for x in r["items"]), "unplaced with suggestion in B zone")
C.post("/api/inv/locations/putaway", json={})
li = L.item_locations(box["id"])
ok(li["unplaced"] == 0 and li["locations"][0]["code"] == "B-01-01" and li["locations"][0]["qty"] == 5, f"putaway {li}")
# 入库：自动放进已经在的货位
inv.create_doc("purchase", [{"item_id": box["id"], "qty": 10}], "", "t")
li = L.item_locations(box["id"]); ok(li["locations"][0]["qty"] == 15 and li["unplaced"] == 0, "receive goes to existing location")
# 新物品入库：分类默认区的空格
tape = C.post("/api/inv/items", json={"name_zh": "胶带", "category": "pack", "unit": "卷"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": tape["id"], "qty": 4}], "", "t")
li = L.item_locations(tape["id"]); ok(li["locations"] and li["locations"][0]["code"] == "B-01-02", f"new item -> next empty in zone {li}")
# 移库：B-01-01 → B-02-01 移 6 个
b0101, b0201 = L.get_loc("B-01-01")["id"], L.get_loc("B-02-01")["id"]
r = C.post("/api/inv/locations/move", json={"item_id": box["id"], "from_loc": b0101, "to_loc": b0201, "qty": 6}).get_json()
ok(r["ok"] and {x["code"]: x["qty"] for x in r["locations"]} == {"B-01-01": 9, "B-02-01": 6}, f"move {r.get('locations')}")
ok(C.post("/api/inv/locations/move", json={"item_id": box["id"], "from_loc": b0101, "to_loc": b0201, "qty": 100}).status_code == 400, "can't move more than there")
# 出库：先扣未上架，再从少的货位扣
C.post("/api/inv/locations/move", json={"item_id": box["id"], "from_loc": b0201, "to_loc": 0, "qty": 2})   # 取下 2 个（未上架 2）
inv.create_doc("issue", [{"item_id": box["id"], "qty": 5}], "", "t")
li = L.item_locations(box["id"]); q = {x["code"]: x["qty"] for x in li["locations"]}
ok(li["unplaced"] == 0 and q == {"B-01-01": 9, "B-02-01": 1}, f"issue: unplaced first, then smallest location {q} {li['unplaced']}")
ok(sum(q.values()) + li["unplaced"] == inv.get_item(box["id"])["qty"], "location sum == item qty")
# 货位核对：B-01-01 数到 7（少 2 → 未上架）；再数到 9（从未上架补回）
r = C.post(f"/api/inv/locations/{b0101}/check", json={"counts": {str(box["id"]): 7}}).get_json()
li = L.item_locations(box["id"]); ok(li["unplaced"] == 2 and r["notes"], "check less -> unplaced")
r = C.post(f"/api/inv/locations/{b0101}/check", json={"counts": {str(box["id"]): 12}}).get_json()
li = L.item_locations(box["id"]); ok(li["unplaced"] == 0 and {x["code"]: x["qty"] for x in li["locations"]}["B-01-01"] == 9 and r["notes"], "check more -> take unplaced, rest needs stocktake")
# 盘点调账：账上多出 3 个 → 自动放进推荐货位
st = C.post("/api/inv/stocktake", json={"category": "pack"}).get_json()["doc"]
ln = next(x for x in st["lines"] if x["item_id"] == box["id"])
C.post(f"/api/inv/stocktake/{st['id']}/save", json={"counts": {str(ln["id"]): inv.get_item(box["id"])["qty"] + 3}}); C.post(f"/api/inv/stocktake/{st['id']}/confirm")
li = L.item_locations(box["id"]); ok(sum(x["qty"] for x in li["locations"]) + li["unplaced"] == inv.get_item(box["id"])["qty"] and li["unplaced"] == 0, "stocktake gain goes to location")
# 货位详情 / 扫码打开 / 删除
d = C.get("/api/inv/locations/find?code=b-01-01").get_json()
ok(d["ok"] and d["location"]["code"] == "B-01-01" and d["items"][0]["loc_qty"] > 0 and d["log"], "find by scan (case-insensitive)")
ok(C.delete(f"/api/inv/locations/{b0101}").status_code == 400, "can't delete non-empty")
a02 = L.get_loc("A-01-02")["id"]; ok(C.delete(f"/api/inv/locations/{a02}").get_json()["ok"], "delete empty")
it = C.get(f"/api/inv/items/{box['id']}").get_json(); ok(it["loc"]["locations"] and "suggest" in it["loc"], "item detail has locations")
html = C.get("/print/inv-locations").get_data(as_text=True); ok(html.count('class="lb"') == 7 and "B-02-03" in html, "location labels")
# 成品：备货入库进 C 区，拣货单按货位
config.save_config({"inv_loc_zones": "包材=B, 耗材=A, 成品=C"})
C.post("/api/inv/locations/bulk", json={"zone": "C", "shelves": 1, "cells": 2})
sku = store.load(store.list_products()[0]["id"])["variants"][0]["sku"]
production.stock_add(sku, 3, "备货打印 批次#1", "t", sku.split("-")[0], "测试", "白色")
ok(L.where_is(sku) and L.where_is(sku)[0][0] == "C-01-01", f"goods stock placed {L.where_is(sku)}")
config.save_config({"review_enabled": False})
o = C.post("/api/orders/manual", json={"order_no": "LOC-1", "order_total": 99, "items": [{"sku": sku, "qty": 1}]}).get_json()
ph = C.get(f"/print/orders?type=pick&ids={o['id']}").get_data(as_text=True)
ok("C-01-01" in ph and "货位" in ph, "pick list shows location")
# 设置
sch = {m["id"]: m for m in C.get("/api/settings/schema").get_json()["modules"]}
ok(any(g["title"] == "货位" for g in sch["inventory"]["groups"]), "settings group")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
