# v2.53 一本库存按区管：料卷有货位（入库上架 / 上机 → 打印机·槽 / 下机 / 用完拿掉 / 称重盘点）、打印扣在机上那卷、
# 生产区货位跟着打印机设置、采购到货 → 暂存区 → 上架、打印 → 待检区 → 合格上架 / 不合格次品区、发货扣拣货区 + 打包台包材、
# 退货区、补货 + 提醒、按区的库存金额、迁移只做一次、「耗材料卷」「成品备货」变成库存页的页签（旧 id 照样能开）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, time
D = T + "/m_wms253"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, inventory as inv, materials, production, store, orders as orders_mod, todo
from modules.inv import locations as L, wms, flows, shipout
C = A.app.test_client()
config.save_config({"review_enabled": False, "inv_loss_rate": 0,
                    "printers": [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "ams": True},
                                 {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "enabled": True, "ams": False}]})
c = db.conn()
item = lambda iid: inv.get_item(iid)
def lq(iid, code):
    l = L.get_loc(code); return wms.loc_qty(db.conn(), iid, l["id"]) if l else 0
def new(name, cat="part", unit="个", **kw):
    return C.post("/api/inv/items", json={"name_zh": name, "category": cat, "unit": unit, **kw}).get_json()["item"]
def buy(iid, q):
    return inv.create_doc("purchase", [{"item_id": iid, "qty": q}], "", "t")
def sp_loc(code):
    s = materials.spool_get(code); w = flows.spool_where(db.conn(), s["id"]); return w["code"] if w else None
def fil_item(m, col):
    return item(flows._item_of(db.conn(), m, col))
def spool_sum(m, col):
    return sum((s["remaining_g"] or 0) for s in materials.spools(m, col, status="active"))

# ---------- 菜单：耗材料卷 / 成品备货 变成库存页里的页签，旧 id 照样能打开 ----------
mods = {m["id"]: m for m in C.get("/api/modules").get_json()["modules"]}
pm = {m["tab"]: m for m in mods["prod"]["menus"]}
ok(pm["materials"]["ghost"] and pm["stock"]["ghost"] and pm["materials"]["parent"] == "inventory" and pm["stock"]["parent"] == "inventory"
   and pm["materials"]["panel"] == "materials" and pm["stock"]["panel"] == "stock", f"old tab ids -> tabs of 库存 {pm['materials']}")
html = C.get("/").get_data(as_text=True)
ok('id="tab-materials"' in html and 'id="tab-stock"' in html, "old panels still there (links / tests keep working)")
ok([m["tab"] for m in mods["inv"]["menus"] if not m["ghost"]] == ["inventory", "inv_locations", "inv_stocktake"], "warehouse menu unchanged")

# ---------- 生产区：每台打印机一个货架，跟着打印机设置 ----------
pl = C.get("/api/inv/printer-locs").get_json()
z = pl["zone"]
shelf = {p["code"]: p["shelf"] for p in pl["printers"] if p["active"]}
ok(z and L.groups()[z]["ztype"] == "production" and set(shelf) == {"P1S-01", "K1C-01"} and len(set(shelf.values())) == 2, f"printer shelves {z} {shelf}")
p1, k1 = f"{z}{shelf['P1S-01']}", f"{z}{shelf['K1C-01']}"
ok(L.get_loc(f"{p1}-01-01") and L.get_loc(f"{p1}-02-04") and L.get_loc(f"{k1}-01-01") and not L.get_loc(f"{k1}-02-01"), "AMS printer: body + 4 slots; K1C: body only")
ok(L.human(f"{p1}-02-01") == "打印机 P1S-01 · 槽 A1" and L.human(f"{k1}-01-01", "th") == "เครื่องพิมพ์ K1C-01 · ตัวเครื่อง", f"human {L.human(f'{k1}-01-01', 'th')}")
m0 = C.get("/api/inv/wms/map").get_json()
ok(not any(x["ztype"] == "production" for x in m0["zones"]), "printer slots not counted as storage")

# ---------- 货架：拣货区 A（成品）、耗材区 F、包材区 B、备货区 R、暂存区 S ----------
C.post("/api/inv/locations/bulk", json={"zone": "A", "layers": 1, "positions": 3, "categories": ["goods"]})
C.post("/api/inv/locations/bulk", json={"zone": "F", "layers": 1, "positions": 4, "ztype": "supply", "categories": ["filament", "part"]})
C.post("/api/inv/locations/bulk", json={"zone": "B", "layers": 1, "positions": 2, "ztype": "pack"})
C.post("/api/inv/locations/bulk", json={"zone": "R", "layers": 1, "positions": 3, "ztype": "reserve"})
C.post("/api/inv/locations/bulk", json={"zone": "S", "layers": 1, "positions": 1, "ztype": "staging"})

# ---------- 料卷：入库 → 推荐货位；上机 → 打印机·槽；打印扣在机上那卷 ----------
r = C.post("/api/spools", json={"material": "PLA", "color": "白色", "count": 2, "net_g": 1000}).get_json()
s1, s2 = r["codes"]
fw = fil_item("PLA", "白色")
ok(sp_loc(s1) and sp_loc(s1).startswith("F1-") and sp_loc(s1) == sp_loc(s2), f"received spools put away in supply zone {sp_loc(s1)}")
ok(abs(lq(fw["id"], sp_loc(s1)) - 2000) < 1e-6 and abs(fw["qty"] - 2000) < 1e-6, "filament grams at location = spools there")
ok(wms.unplaced(db.conn(), fw["id"]) == 0 and not any(x["item"]["id"] == fw["id"] for x in wms.pending()), "spool filament not in item pending list")
x = C.post(f"/api/inv/spools/{s1}/load", json={"printer": "P1S-01", "slot": "A1"}).get_json()
ok(x["ok"] and x["spool"]["loc"]["code"] == f"{p1}-02-01" and x["spool"]["status"] == "loaded", f"load -> printer slot {x}")
ok(abs(lq(fw["id"], f"{p1}-02-01") - 1000) < 1e-6 and abs(lq(fw["id"], sp_loc(s2)) - 1000) < 1e-6, "grams follow the spool")
inv.consume_production("PLA", "白色", 120, "打印完成 批次#1", "t", 0, "run:1")
a = materials.spool_get(s1)
ok(abs(a["remaining_g"] - 880) < 1e-6 and abs(materials.spool_get(s2)["remaining_g"] - 1000) < 1e-6, f"print deducts the loaded spool {a['remaining_g']}")
fw = item(fw["id"])
ok(abs(fw["qty"] - spool_sum("PLA", "白色")) < 1e-6 and abs(lq(fw["id"], f"{p1}-02-01") - 880) < 1e-6, f"item grams = spools {fw['qty']}")
# 另一个颜色没装在机上：照旧（开一卷）—— 记到这台机身上
r = C.post("/api/spools", json={"material": "PLA", "color": "黑色", "count": 1, "net_g": 1000}).get_json()
b1 = r["codes"][0]
inv.consume_production("PLA", "黑色", 50, "打印完成 批次#2", "t", 1, "run:2")
fb = fil_item("PLA", "黑色")
ok(materials.spool_get(b1)["status"] == "loaded" and sp_loc(b1) == f"{k1}-01-01" and abs(fb["qty"] - 950) < 1e-6
   and abs(lq(fb["id"], f"{k1}-01-01") - 950) < 1e-6, f"fallback: opened spool auto-loaded, location follows {sp_loc(b1)}")
# 多色一盘：每个颜色分别扣（v2.52），各自扣自己那卷
production._consume({"id": 9, "colors": '[{"material":"PLA","colour":"白色","grams":30},{"material":"PLA","colour":"黑色","grams":20}]',
                     "material": "PLA", "color": "白色", "grams": 50, "printer": 0}, 1.0, "打印完成 批次#9", "t")
ok(abs(materials.spool_get(s1)["remaining_g"] - 850) < 1e-6 and abs(item(fb["id"])["qty"] - 930) < 1e-6
   and abs(item(fw["id"])["qty"] - spool_sum("PLA", "白色")) < 1e-6, "per-colour consumption keeps grams consistent")

# ---------- 下机 / 上架 / 用完 ----------
x = C.post(f"/api/inv/spools/{s1}/unload", json={}).get_json()
ok(x["ok"] and x["spool"]["loc"] is None and x["spool"]["status"] == "open", "unload without scan -> 待上架")
sl = C.get("/api/inv/spools?loc=unplaced").get_json()
ok(any(s["code"] == s1 for s in sl["items"]) and sl["stats"]["unplaced"] >= 1, "spool list: unplaced filter")
x = C.post(f"/api/inv/spools/{s1}/put", json={"code": "F1-01-03"}).get_json()
ok(x["ok"] and x["spool"]["loc"]["code"] == "F1-01-03" and abs(lq(fw["id"], "F1-01-03") - 850) < 1e-6, "scan spool -> scan shelf = putaway")
x = C.post(f"/api/inv/spools/{s1}/put", json={"code": f"{p1}-02-02"}).get_json()
ok(x["ok"] and materials.spool_get(s1)["printer"] == "P1S-01" and materials.spool_get(s1)["slot"] == "A2", "scan printer slot = load")
x = C.post(f"/api/inv/spools/{s1}/unload", json={"to": "F1-01-03", "grams": 800}).get_json()
ok(x["ok"] and x["spool"]["loc"]["code"] == "F1-01-03" and abs(materials.spool_get(s1)["remaining_g"] - 800) < 1e-6, "unload with weight + shelf")
ok(C.post("/api/inv/wms/move", json={"from": "F1-01-03", "to": "F1-01-04", "lines": [{"item_id": fw["id"], "qty": 100}]}).status_code == 400,
   "generic move refused for spool filament (move spools)")
# 称重盘点：毛重 − 空料盘
config.save_config({"inv_spool_tare_g": 250})
w = C.post(f"/api/inv/spools/{s2}/weigh", json={"gross": 1150}).get_json()
ok(w["ok"] and w["result"]["after"] == 900 and w["result"]["diff"] == -100 and w["result"]["amount"] < 0, f"weigh stocktake {w.get('result')}")
ok(abs(item(fw["id"])["qty"] - spool_sum("PLA", "白色")) < 1e-6 and abs(lq(fw["id"], sp_loc(s2)) - 900) < 1e-6, "weigh keeps item + location")
cnt = C.post("/api/inv/spools/count", json={"code": "F1-01-03", "entries": [{"code": s2, "gross": 1140}]}).get_json()
ok(cnt["ok"] and sp_loc(s2) == "F1-01-03" and cnt["diff_g"] == -10 and s1 in cnt["missing"], f"count at a location: moved + missing {cnt}")
C.post(f"/api/spools/{b1}/empty", json={})
ok(sp_loc(b1) is None and lq(fb["id"], f"{k1}-01-01") == 0 and abs(item(fb["id"])["qty"] - spool_sum("PLA", "黑色")) < 1e-6, "emptied spool removed from location")
lbl = C.get(f"/print/spools?ids={s1}").get_data(as_text=True)
ok("<svg" in lbl and "F1-01-03" in lbl, "spool label: QR + location")

# ---------- 打印机改了：加一台、删一台、改编码 ----------
config.save_config({"printers": [{"code": "P1S-09", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "ams": True},
                                 {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "enabled": True, "ams": False},
                                 {"code": "X1C-01", "name": "Bambu Lab X1C", "g_per_h": 25, "enabled": True, "ams": True}]})
flows.sync_printers()
rows = {r["code"]: dict(r) for r in db.conn().execute("SELECT * FROM inv_printer_locs WHERE active=1")}
x1 = f"{z}{rows['X1C-01']['shelf']}"
ok(f"{z}{rows['P1S-09']['shelf']}" == p1 and "P1S-01" not in rows and x1 not in (p1, k1), f"rename keeps shelf, new printer gets a shelf {rows}")
ok(L.get_loc(f"{x1}-02-01") and L.get_loc(f"{x1}-02-01")["active"] and L.human(f"{p1}-01-01") == "打印机 P1S-09 · 机身", "slots follow printer settings")
config.save_config({"printers": [{"code": "P1S-09", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "ams": True},
                                 {"code": "X1C-01", "name": "Bambu Lab X1C", "g_per_h": 25, "enabled": True, "ams": True}]})
flows.sync_printers()
ok(not L.get_loc(f"{k1}-01-01")["active"] and L.get_loc(f"{x1}-01-01")["active"], "removed printer -> its empty slots deactivated")

# ---------- 采购到货 → 暂存区 → 按分类推荐上架（扫货位确认） ----------
config.save_config({"inv_loc_auto": False})
tape = new("胶带", "pack")
sup = C.post("/api/inv/suppliers", json={"name": "供应商253"}).get_json()["supplier"]
po = C.post("/api/inv/po", json={"supplier_id": sup["id"], "lines": [{"item_id": tape["id"], "qty": 10, "unit_cost": 2}]}).get_json()
po = po.get("po") or po
C.post(f"/api/inv/po/{po['id']}/order", json={})
g = C.get(f"/api/inv/po/{po['id']}").get_json()["po"]
r = C.post("/api/inv/pur/receive", json={"po_id": po["id"], "qtys": {str(g["lines"][0]["id"]): 10}}).get_json()
ok(r["ok"] and lq(tape["id"], "S1-01-01") == 10, f"receiving -> staging {r.get('placed')}")
pend = [x for x in C.get("/api/inv/wms/pending").get_json()["items"] if x["item"]["id"] == tape["id"]]
ok(pend and pend[0]["from"] == "S1-01-01" and pend[0]["suggest"][0]["code"].startswith("B1-"), f"pending lists staging with pack-zone suggestion {pend}")
x = C.post("/api/inv/wms/putaway", json={"item_id": tape["id"], "code": pend[0]["suggest"][0]["code"], "from": "S1-01-01"}).get_json()
ok(x["ok"] and lq(tape["id"], "S1-01-01") == 0 and lq(tape["id"], pend[0]["suggest"][0]["code"]) == 10 and item(tape["id"])["location"].startswith("B1-"),
   "scan to confirm putaway from staging")
config.save_config({"inv_loc_auto": True})

# ---------- 打印 → 待检区 → 合格上架 / 不合格次品区 ----------
pids = [p["id"] for p in store.list_products()][:2]
p0 = store.load(pids[0]); sku = p0["variants"][0]["sku"].upper()
production.stock_add(sku, 5, "备货打印 批次#10", "t", pids[0], "测试", "")
gi = item(sku)
qc = C.get("/api/inv/held/qc").get_json()["items"]
qloc = qc[0]["from"] if qc else ""
ok(qc and qc[0]["item"]["id"] == gi["id"] and qc[0]["qty"] == 5 and L.groups()[L.parse(qloc)[0]]["ztype"] == "qc", f"print -> 待检区 {qloc}")
ok(not gi.get("location"), "QC zone is not the primary location")
x = C.post("/api/inv/qc/pass", json={"item_id": gi["id"], "qty": 4}).get_json()
ok(x["ok"] and x["to"].startswith("A1-") and lq(gi["id"], x["to"]) == 4 and item(sku)["location"] == x["to"], f"QC pass -> pick {x}")
x = C.post("/api/inv/qc/fail", json={"item_id": gi["id"], "qty": 1, "action": "scrap", "note": "拉丝"}).get_json()
dz = x.get("to")
ok(x["ok"] and x["doc"]["kind"] == "scrap" and lq(gi["id"], dz) == 0 and production.stock_qty(sku) == 4 and item(sku)["qty"] == 4, f"QC fail -> 次品区 -> scrap {dz}")
production.stock_add(sku, 2, "备货打印 批次#11", "t", pids[0], "测试", "")
C.post("/api/inv/qc/fail", json={"item_id": gi["id"], "qty": 1, "action": "defect"})
ok(lq(gi["id"], dz) == 1, "QC fail (rework) waits in 次品区")
x = C.post("/api/inv/defect/act", json={"item_id": gi["id"], "act": "rework"}).get_json()
ok(x["ok"] and lq(gi["id"], dz) == 0 and lq(gi["id"], qloc) == 2, "rework -> back to 待检区")
C.post("/api/inv/qc/pass", json={"item_id": gi["id"]})
ok(lq(gi["id"], qloc) == 0 and sum(x["qty"] for x in wms.item_locations(gi["id"])["locations"]) == 6, "all passed and shelved")

# ---------- 没过质检的不算可卖：待检 / 退货 / 次品区的成品不能「用库存发」、不进库存同步的可售 ----------
from core import modules as _mods
EV = []
_emit0 = _mods.emit
_mods.emit = lambda ev, **kw: (EV.append((ev, kw)), _emit0(ev, **kw))[1]
base = production.stock_qty(sku)
production.stock_add(sku, 3, "备货打印 批次#12", "t", pids[0], "测试", "")
ok(flows.unavailable_qty(sku) == 3 and production.unavailable_qty(sku) == 3 and production.sellable_qty(sku) == base, f"QC goods unavailable {flows.unavailable_qty(sku)}")
ok(production.free_stock(sku) == base - production.reserved(sku), "free_stock excludes QC goods")
from modules.listing import stocksync as _ss
ok(_ss.on_hand(sku) == base, "stock sync on-hand excludes QC goods")
pub_ = _mods.public("inv")
ok(pub_ is not None and pub_.unavailable_qty(sku) == 3 and pub_.unavailable_qty("NOPE-X") == 0, "public unavailable_qty")
EV.clear()
C.post("/api/inv/qc/pass", json={"item_id": gi["id"], "qty": 2})
ok(flows.unavailable_qty(sku) == 1 and production.sellable_qty(sku) == base + 2, "QC pass -> available at once")
ok(any(e == "stock.changed" and k.get("sku") == sku for e, k in EV), "QC pass broadcasts stock.changed")
EV.clear()
C.post("/api/inv/qc/fail", json={"item_id": gi["id"], "qty": 1, "action": "defect"})
ok(flows.unavailable_qty(sku) == 1 and production.sellable_qty(sku) == base + 2 and any(e == "stock.changed" for e, k in EV), "defect stays unavailable (QC -> DF)")
C.post("/api/inv/defect/act", json={"item_id": gi["id"], "act": "scrap"})
ok(flows.unavailable_qty(sku) == 0 and production.stock_qty(sku) == base + 2, "scrapped -> gone, never available")
_mods.emit = _emit0

# ---------- 发货：成品从拣货区扣，包材从打包台扣 ----------
card = new("感谢卡", "pack", "张")
buy(card["id"], 20)
home = item(card["id"])["location"]
C.post("/api/inv/wms/move", json={"from": home, "to": "B1-01-02" if home != "B1-01-02" else "B1-01-01", "lines": [{"item_id": card["id"], "qty": 5}]})
station = "B1-01-02" if home != "B1-01-02" else "B1-01-01"
config.save_config({"inv_pack_rules": [{"item_id": card["id"], "qty": 1, "per": "order"}], "inv_pack_station": station})
o1 = C.post("/api/orders/manual", json={"order_no": "W253-1", "order_total": 199, "items": [{"sku": sku, "qty": 2}]}).get_json()
pick_before = sum(x["qty"] for x in wms.item_locations(gi["id"])["locations"] if x["ztype"] == "pick")
orders_mod.update_order(o1["id"], "t", status="shipped")
s = shipout.summary(o1["id"])
ok(s and lq(card["id"], station) == 4 and lq(card["id"], home) == 15, f"pack materials from the pack station {lq(card['id'], station)} {lq(card['id'], home)}")
ok(sum(x["qty"] for x in wms.item_locations(gi["id"])["locations"] if x["ztype"] == "pick") == pick_before - 2, "goods deducted from pick zone")

# ---------- 退货 → 退货区 → 重新上架 / 次品区 ----------
x = C.post("/api/inv/returns/receive", json={"code": sku, "qty": 2, "note": "买家退回"}).get_json()
rl = x.get("to")
ok(x["ok"] and L.groups()[L.parse(rl)[0]]["ztype"] == "returns" and lq(gi["id"], rl) == 2 and production.stock_qty(sku) == base + 2, f"return -> 退货区 {rl}")
x = C.post("/api/inv/returns/act", json={"item_id": gi["id"], "act": "restock", "qty": 1}).get_json()
ok(x["ok"] and x["to"].startswith("A1-") and lq(gi["id"], rl) == 1, "inspect: restock")
x = C.post("/api/inv/returns/act", json={"item_id": gi["id"], "act": "defect"}).get_json()
ok(x["ok"] and lq(gi["id"], rl) == 0 and lq(gi["id"], dz) == 1, "inspect: to 次品区")
production.stock_add(sku, 1, "售后退回验货入库（订单 X）", "t")
ok(lq(gi["id"], rl) == 1, "after-sales restock lands in 退货区")
# 出库不会先扣待检 / 退货 / 次品区
inv.create_doc("adjust", [{"item_id": gi["id"], "qty": -1}], "测", "t")
ok(lq(gi["id"], rl) == 1 and lq(gi["id"], dz) == 1, "outbound takes good stock first")

# ---------- 补货（耗材区 / 包材区也补）+ 提醒 ----------
glue = new("胶水", "part")
buy(glue["id"], 3)
gh = item(glue["id"])["location"]
ok(gh and gh.startswith("F1-"), f"part -> supply zone {gh}")
C.post("/api/inv/wms/move", json={"from": gh, "to": "R1-01-01", "lines": [{"item_id": glue["id"], "qty": 2}]})
C.post("/api/inv/locations/props", json={"codes": [gh], "props": {"min_qty": 2}})
tk = C.get("/api/inv/wms/tasks").get_json()
ok(any(t["item_id"] == glue["id"] and t["from_loc"] == "R1-01-01" and t["to_loc"] == gh for t in tk["tasks"]), "supply zone below min -> task from reserve")
C.post("/api/inv/locations/props", json={"codes": [station], "props": {"min_qty": 10}})
td = todo.collect()["items"]
emp = [i for i in td if i["key"].startswith(f"inv:empty:{card['id']}:")]
ok(emp and emp[0]["tab"] in ("po_suggest", "inventory") and "包材区" in emp[0]["title"], f"reserve empty -> purchase reminder {emp[:1]}")
c = db.conn()
c.execute("UPDATE spools SET created_at=?, opened_at=? WHERE code=?", (time.time() - 400 * 86400, time.time() - 40 * 86400, s1))
c.commit()
config.save_config({"inv_spool_low_g": 900})
td = todo.collect()["items"]
sid1 = materials.spool_get(s1)["id"]
keys = {i["key"] for i in td}
ok({f"inv:spool:low:{sid1}", f"inv:spool:expired:{sid1}", f"inv:spool:dry:{sid1}"} <= keys, f"spool reminders {sorted(k for k in keys if 'spool' in k)}")
ok(any(i["key"].startswith("inv:returns:") for i in td), "returns waiting -> to-do")

# ---------- 库存金额：按区 / 分类、还够几天、很久没动 ----------
v = C.get("/api/inv/value?slow_days=0").get_json()
zt = {x["ztype"]: x for x in v["ztypes"]}
ok({"pick", "supply", "pack", "returns", "defect"} <= set(zt) and abs(sum(x["value"] for x in v["categories"]) - v["total"]["value"]) < 0.05, f"value by zone {list(zt)}")
gv = item(sku)
ok(zt["pick"]["value"] > 0 and abs(zt["returns"]["value"] - gv["avg_cost"]) < 0.01, "goods valued at production cost per zone")
ok(v["slow"] and v["total"]["slow_n"] == len(v["slow"]) or v["total"]["slow_n"] >= 50, "slow movers (no movement N days)")
ok(any(x["id"] == card["id"] and x["days"] > 0 for x in v["cover"]), "days of cover")
lst = C.get("/api/inv/items?view=stock&zone=t:returns").get_json()
ok([x["id"] for x in lst["items"]] == [gi["id"]] and any(o["value"] == "t:qc" for o in lst["zones"]), "库存 filter by zone")
lst = C.get("/api/inv/items?view=stock&loc=F1").get_json()
ok(fw["id"] in [x["id"] for x in lst["items"]] and all(any(l["code"].startswith("F1") for l in x["locs"]) for x in lst["items"]), "库存 filter by location + split list")
# 盘点差异折成钱
d = C.post("/api/inv/stocktake", json={"area": "R1"}).get_json()["doc"]
from modules.inv import stocktake
sm = stocktake.count(d["id"], "R1-01-01", {glue["id"]: 1}, "t")
ok(sm["progress"]["amount"]["minus"] < 0 or item(glue["id"])["avg_cost"] == 0, f"stocktake differences in money {sm['progress']}")

# ---------- 迁移：只做一次，再跑不重复；其它物品的货位数量不动 ----------
c = db.conn()
before_other = {(r[0], r[1]): r[2] for r in c.execute("SELECT item_id, loc_id, qty FROM inv_loc_qty WHERE item_id NOT IN (SELECT id FROM inv_items WHERE category='filament')")}
r = C.post("/api/spools", json={"material": "PETG", "color": "红色", "count": 2, "net_g": 1000}).get_json()
k1, k2 = r["codes"]
materials.spool_action(k1, "load", "t", "P1S-09", "B1")
c.execute("DELETE FROM inv_spool_loc WHERE spool_id IN (SELECT id FROM spools WHERE material='PETG')")
pe = flows._item_of(c, "PETG", "红色")
c.execute("DELETE FROM inv_loc_qty WHERE item_id=?", (pe,)); c.execute("UPDATE inv_items SET location=NULL WHERE id=?", (pe,))   # v2.52 时没放货位
_oloc = L.get_loc("R1-01-01")
c.execute("INSERT INTO inv_loc_qty(item_id, loc_id, qty, updated_at) VALUES(?,?,?,?)", (pe, _oloc["id"], 777.0, 1.0))    # v2.52 放在别处的一笔
nlog0 = c.execute("SELECT COUNT(*) FROM inv_loc_log WHERE kind='migrate'").fetchone()[0]
c.commit()
config.save_config({"inv_loc_v253": False})
n1 = flows.migrate()
n2 = flows.migrate()
config.save_config({"inv_loc_v253": False})
n3 = flows.migrate()
ok(n1 == 2 and n2 == 0 and n3 == 0, f"migration idempotent {n1} {n2} {n3}")
bak = c.execute("SELECT qty FROM inv_loc_qty_bak253 WHERE item_id=? AND loc_id=?", (pe, _oloc["id"])).fetchone()
ok(bak and bak[0] == 777.0, "migration: overwritten inv_loc_qty row backed up first")
lg = c.execute("SELECT * FROM inv_loc_log WHERE kind='migrate' AND item_id=?", (pe,)).fetchall()
ok(len(lg) >= 1 and any(x["from_loc"] == "R1-01-01" and abs(x["qty"] - 777.0) < 1e-6 for x in lg), f"migration: inv_loc_log row (kind migrate) per change {len(lg)}")
nl = c.execute("SELECT COUNT(*) FROM inv_loc_log WHERE kind='migrate'").fetchone()[0]
config.save_config({"inv_loc_v253": False}); flows.migrate()
ok(c.execute("SELECT COUNT(*) FROM inv_loc_log WHERE kind='migrate'").fetchone()[0] == nl and c.execute("SELECT qty FROM inv_loc_qty_bak253 WHERE item_id=? AND loc_id=?", (pe, _oloc["id"])).fetchone()[0] == 777.0, "migration: log/backup idempotent")
# ---- 老安装升级：没明确选过 inv_qc_on → 质检区默认关 + 一次性提示；明确选过的不动
import json as _json
_raw = _json.load(open(config.CONFIG_PATH, encoding="utf-8")); _had = _raw.get("inv_qc_on"); _raw["inv_qc_on"] = True; _raw["inv_loc_v253"] = False   # save_config 早就把默认值 inv_qc_on=True 写进了文件（复审）
_json.dump(_raw, open(config.CONFIG_PATH, "w", encoding="utf-8"), ensure_ascii=False)
flows.migrate()
cf = config.load_config()
ok(cf["inv_qc_on"] is False and cf.get("inv_qc_hint253") is True, "upgrade: existing install -> inv_qc_on defaults OFF + one-time hint")
mj = C.get("/api/inv/meta").get_json()
ok(mj.get("qc_hint") is True, "meta carries qc_hint for owner")
C.post("/api/inv/qc/hint", json={"enable": True})
cf = config.load_config()
ok(cf["inv_qc_on"] is True and not cf.get("inv_qc_hint253") and C.get("/api/inv/meta").get_json().get("qc_hint") is False, "hint: enable QC / dismissed for good")
config.save_config({"inv_qc_on": False, "inv_loc_v253": False}); flows.migrate()
ok(config.load_config()["inv_qc_on"] is False, "migration marker set -> a later migrate() never touches inv_qc_on again")
config.save_config({"inv_qc_on": True}); flows.migrate()
ok(config.load_config()["inv_qc_on"] is True, "after the marker is set, QC on stays on")
config.save_config({"inv_qc_on": _had if _had is not None else True})
ok(sp_loc(k1) == f"{p1}-02-05" and sp_loc(k2) is None, f"loaded -> printer slot (B1), others -> 待上架 {sp_loc(k1)} {sp_loc(k2)}")
after_other = {(r[0], r[1]): r[2] for r in c.execute("SELECT item_id, loc_id, qty FROM inv_loc_qty WHERE item_id NOT IN (SELECT id FROM inv_items WHERE category='filament')")}
ok(before_other == after_other, "other items' location quantities untouched")
ok(production.stock_list() is not None and all("target" in r for r in production.stock_list()), "finished-goods targets kept")

# ---------- 打印机设置一改，生产区货位马上跟着变（不用等打开货位页）----------
def prs_now():
    return [dict(p) for p in config.load_config()["printers"]]
def shelves():
    return {r["code"]: r["active"] for r in db.conn().execute("SELECT code, active FROM inv_printer_locs")}
prs = prs_now()
r = C.post("/api/config", json={"printers": prs + [{"code": "X1C-07", "name": "Bambu X1C", "g_per_h": 25, "enabled": True, "ams": True}]})
ok(r.status_code == 200 and shelves().get("X1C-07") == 1, f"add printer -> shelf at once {shelves()}")
ok(any(L.get_loc(l) for l in [f"{z}{r0['shelf']}-02-04" for r0 in db.conn().execute("SELECT shelf FROM inv_printer_locs WHERE code='X1C-07'")]), "new printer AMS slots exist")
prs = prs_now()
for p_ in prs:
    if p_["code"] == "X1C-07":
        p_["name"] = "X1C 改名"
C.post("/api/config", json={"printers": prs})
ok(db.conn().execute("SELECT name FROM inv_printer_locs WHERE code='X1C-07'").fetchone()[0] == "X1C 改名", "rename printer -> synced")
C.post("/api/config", json={"printers": [p_ for p_ in prs_now() if p_["code"] != "X1C-07"]})
ok(shelves().get("X1C-07") == 0, "remove printer -> shelf deactivated at once")

# ---------- 手机页 ----------
mj = C.get("/m/mobile/m.js").get_data(as_text=True)
ok(all(k in mj for k in ("SCREENS.spool", "SCREENS.qc", "SCREENS.ret")), "phone pages: spool / qc / returns")
print("ERRORS", E_)
