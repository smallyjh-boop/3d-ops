# v2.35：订单发货出库——下单时有成品库存自动「用库存发」（先占住），发货时一张出库单扣成品 + 纸箱（邮政标准，按产品自动选、
# 打包时可改）+ 包材规则；改回待发货作废冲回；取消订单释放占用；订单详情 / 打包页显示纸箱和出库单
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D = T + "/m_ship"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, inventory as inv, production, store, orders as orders_mod, chain
from core.inventory import boxes
from modules.inv import shipout
C = A.app.test_client()
config.save_config({"review_enabled": False})
# 纸箱目录
cat = C.get("/api/pack-boxes").get_json()
ok(len(cat["boxes"]) == 18 and cat["boxes"][5]["code"] == "2A" and cat["boxes"][5]["size"] == "14×20×12", "standard post boxes")
ok(boxes.fit(12, 18, 10) == "2A" and boxes.fit(13, 16, 6) == "AA" and boxes.fit(60, 60, 60) is None, f"fit {boxes.fit(12, 18, 10)} {boxes.fit(13, 16, 6)}")
ok(boxes.biggest(["A", "2B", "0"]) == "2B", "biggest box")
# 产品设纸箱
pids = [p["id"] for p in store.list_products()][:2]
p1 = store.load(pids[0]); p1["pack_box"] = "2A"; store.save(p1)
p2 = store.load(pids[1]); p2["pack_box"] = "B"; store.save(p2)
sku1 = p1["variants"][0]["sku"]; sku2 = p2["variants"][0]["sku"]
# 成品库存 3 个
production.stock_add(sku1, 3, "备货打印 批次#1", "t", pids[0], "测试", "")
ok(production.free_stock(sku1) == 3, "free stock 3")
# 下单 2 个 → 自动用库存发（占住 2，不扣）
o1 = C.post("/api/orders/manual", json={"order_no": "SH-1", "order_total": 199, "items": [{"sku": sku1, "qty": 2}]}).get_json()
j1 = production.list_jobs(order_id=o1["id"])[0]
ok(j1["stock_n"] == 2 and j1["status"] == "post" and production.stock_qty(sku1) == 3 and production.reserved(sku1) == 2, f"auto use stock {dict(j1)}")
ok(production.free_stock(sku1) == 1, "free = stock - reserved")
# 第二单 2 个：只剩 1 个可用 → 用 1 个，另一个排打印
o2 = C.post("/api/orders/manual", json={"order_no": "SH-2", "order_total": 199, "items": [{"sku": sku1, "qty": 2}]}).get_json()
j2 = production.list_jobs(order_id=o2["id"])[0]
ok(j2["stock_n"] == 1 and j2["qty_done"] == 1 and j2["status"] == "todo", f"partial stock use {dict(j2)}")
ok(any(x["action"] == "用库存发" for x in orders_mod.get_log(o2["id"])), "order log says use stock")
# 包材规则：每单 1 个感谢卡
card = C.post("/api/inv/items", json={"name_zh": "感谢卡", "category": "pack", "unit": "张"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": card["id"], "qty": 50}], "", "t")
config.save_config({"inv_pack_rules": [{"item_id": card["id"], "qty": 1, "per": "order"}]})
# 订单详情：纸箱自动选
d = C.get(f"/api/orders/{o1['id']}").get_json()
ok(d["box"]["code"] == "2A" and d["box"]["auto"] is True and d["out"] is None, f"order box auto {d['box']}")
# 发货 → 出库单
orders_mod.update_order(o1["id"], "t", status="shipped")
s1 = shipout.summary(o1["id"])
kinds = {ln["code"]: ln["qty"] for ln in (s1 or {}).get("lines", [])}
ok(s1 and s1["no"].startswith("CK") and kinds.get(sku1.upper()) == 2 and kinds.get("BOX-2A") == 1 and kinds.get(card["code"]) == 1, f"ship-out doc {s1}")
ok(production.stock_qty(sku1) == 1 and production.reserved(sku1) == 1 and production.free_stock(sku1) == 0, "goods deducted at ship, reservation gone")
bx = inv.get_item("BOX-2A"); ok(bx and bx["qty"] == -1 and bx["category"] == "pack" and bx["name_zh"] == "邮政纸箱 2A", f"box item auto created {bx and bx['qty']}")
ok(inv.get_item(card["id"])["qty"] == 49, "pack rule deducted")
mv = inv.moves(item_id=inv.get_item(sku1)["id"], limit=5); ok(mv[0]["kind"] == "ship" and mv[0]["doc_id"] == s1["doc_id"], "goods move kind ship")
mv = inv.moves(item_id=bx["id"], limit=5); ok(mv[0]["kind"] == "pack", "box move kind pack (counts as expense)")
d = C.get(f"/api/orders/{o1['id']}").get_json(); ok(d["out"] and d["out"]["no"] == s1["no"], "order detail shows ship-out doc")
ok(shipout.ship_order(o1["id"], "t") is None, "ship-out only once")
# 改回待发货 → 作废冲回；再发货 → 重新出库
orders_mod.update_order(o1["id"], "t", status="to_ship")
ok(production.stock_qty(sku1) == 3 and inv.get_item("BOX-2A")["qty"] == 0 and shipout.summary(o1["id"]) is None, "revert voids doc")
ok(inv.doc(s1["doc_id"])["status"] == "void", "old doc void")
orders_mod.update_order(o1["id"], "t", status="shipped")
ok(shipout.summary(o1["id"]) and production.stock_qty(sku1) == 1, "re-ship creates new doc")
# 打包时改纸箱
r = C.post(f"/api/orders/{o2['id']}/pack-box", json={"box": "2b"}).get_json()
ok(r["ok"] and r["box"]["code"] == "2B" and r["box"]["auto"] is False, f"change box {r}")
ok(C.post(f"/api/orders/{o2['id']}/pack-box", json={"box": "XX"}).status_code == 400, "bad box rejected")
lk = C.get("/api/pack/lookup?code=SH-2").get_json(); ok(lk["box"]["code"] == "2B", "pack station shows box")
orders_mod.update_order(o2["id"], "t", status="shipped")
k2 = {ln["code"]: ln["qty"] for ln in shipout.summary(o2["id"])["lines"]}
ok(k2.get("BOX-2B") == 1 and k2.get(sku1.upper()) == 1 and "BOX-2A" not in k2, f"chosen box used, only reserved goods {k2}")
# 两个产品：默认用大的纸箱；产品设「不用纸箱」→ 不扣纸箱
o3 = C.post("/api/orders/manual", json={"order_no": "SH-3", "order_total": 99, "items": [{"sku": sku1, "qty": 1}, {"sku": sku2, "qty": 1}]}).get_json()
ok(C.get(f"/api/orders/{o3['id']}").get_json()["box"]["code"] == "B", "biggest box of the order")
p1["pack_box"] = "none"; store.save(p1); p2["pack_box"] = "none"; store.save(p2)
ok(C.get(f"/api/orders/{o3['id']}").get_json()["box"]["code"] == "none", "no box when products say none")
orders_mod.update_order(o3["id"], "t", status="shipped")
k3 = {ln["code"]: ln["qty"] for ln in (shipout.summary(o3["id"]) or {"lines": []})["lines"]}
ok(not any(c.startswith("BOX-") for c in k3) and k3.get(card["code"]) == 1, f"no box line {k3}")
# 取消还没发货的订单 → 占用放回
production.stock_add(sku1, 2, "备货打印 批次#2", "t", pids[0], "测试", "")
o4 = C.post("/api/orders/manual", json={"order_no": "SH-4", "order_total": 99, "items": [{"sku": sku1, "qty": 1}]}).get_json()
ok(production.reserved(sku1) == 1, "reserved for SH-4")
orders_mod.update_order(o4["id"], "t", status="cancelled"); chain.order_changed("t")
ok(production.reserved(sku1) == 0 and not production.list_jobs(order_id=o4["id"]), "cancel releases reservation")
# 生产页手动「用库存」也是先占住
config.save_config({"stock_auto_use": False})
o5 = C.post("/api/orders/manual", json={"order_no": "SH-5", "order_total": 99, "items": [{"sku": sku1, "qty": 1}]}).get_json()
j5 = production.list_jobs(order_id=o5["id"])[0]; ok(j5["stock_n"] == 0 and j5["status"] == "todo", "auto use off")
q0 = production.stock_qty(sku1)
r = C.post(f"/api/jobs/{j5['id']}/use-stock", json={"n": 1}).get_json()
ok(production.stock_qty(sku1) == q0 and production.reserved(sku1) == 1 and production.list_jobs(order_id=o5["id"])[0]["stock_n"] == 1, "manual use-stock reserves")
# 导入时已经是已发货的历史订单：不出库
orders_mod.upsert([{"platform": "shopee", "order_no": "OLD-1", "status": "shipped", "items": [{"sku": sku1, "qty": 1}]}], source="test")
oid_old = db.conn().execute("SELECT id FROM orders WHERE order_no='OLD-1'").fetchone()["id"]
ok(shipout.summary(oid_old) is None, "historical shipped order not deducted")
# 关掉「发货出库」
config.save_config({"inv_ship_out": False})
o6 = C.post("/api/orders/manual", json={"order_no": "SH-6", "order_total": 99, "items": [{"sku": sku2, "qty": 1}]}).get_json()
orders_mod.update_order(o6["id"], "t", status="shipped"); ok(shipout.summary(o6["id"]) is None, "switch off -> no doc")
config.save_config({"inv_ship_out": True})
# 生产模块关着：按订单商品扣成品
chain.prod_on = lambda: False
lines = shipout._goods_lines(db.conn(), orders_mod.get_order(o6["id"]))
ok(len(lines) == 1 and lines[0]["qty"] == 1, "prod off -> deduct order items")
# 设置
sch = {m["id"]: m for m in C.get("/api/settings/schema").get_json()["modules"]}
ok("inv_ship_out" in str(sch["inventory"]) and "stock_auto_use" in str(sch["orders"]), "settings")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
