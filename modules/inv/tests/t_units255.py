# v2.55 耗材两个单位：卷 + 重量（树脂：瓶 + 毫升）
# 库存表「2 卷（1 整卷 + 1 开封卷）· 1.97 kg」（整卷 / 开封 / 在机上都算）、货位分布文字（A1-01-01：1 卷 · 1.0 kg、PR…（打印机上）：1 卷 · 973 g）、
# 补货线按卷或公斤（提醒、补货建议都跟着）、按卷入库 / 退回 / 领用 / 报废（每卷一条料卷记录和编号）、打印照旧按克扣在机上那卷、
# 盘点数卷 / 称重（毛重 − 空料盘）、采购建议按卷带公斤和金额、树脂按瓶、其他分类不变、老数据不用转（迁移只加列、可重复）、泰文里没有中文
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, re
D = T + "/m_units255"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, inventory as inv, materials
from core.inventory import units
from modules.inv import locations as L, wms, flows
from modules.pur.logic import suggest as pur_suggest
C = A.app.test_client()
config.save_config({"review_enabled": False, "inv_loss_rate": 0, "inv_spool_tare_g": 200, "inv_loc_auto": True,
                    "printers": [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "ams": True},
                                 {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "enabled": True, "ams": False}]})
CJK = re.compile(r"[一-鿿]")
item = lambda iid: inv.get_item(iid)
def new_fil(mat, col, **kw):
    return C.post("/api/inv/items", json={"name_zh": f"{mat} {col}", "category": "filament", "material": mat, "color": col, **kw}).get_json()
def row_of(iid, **q):
    items = C.get("/api/inv/items?view=stock").get_json()["items"] + C.get("/api/inv/items?view=all").get_json()["items"]
    return next(x for x in items if x["id"] == iid)
def spools_of(m, col, st="active"):
    return materials.spools(m, col, status=st)

pl = C.get("/api/inv/printer-locs").get_json(); z = pl["zone"]
shelf = {p["code"]: p["shelf"] for p in pl["printers"] if p["active"]}
p1 = f"{z}{shelf['P1S-01']}"
C.post("/api/inv/locations/bulk", json={"zone": "F", "layers": 1, "positions": 4, "ztype": "supply", "categories": ["filament", "part"]})

# ---------- 迁移：加列、可重复、老物品不用转 ----------
old_it = inv.save_item({"name_zh": "PLA 老颜色", "category": "filament", "material": "PLA", "color": "旧色", "reorder_point": 500}, "t")
inv.init(); inv.init()
cols = {r[1] for r in db.conn().execute("PRAGMA table_info(inv_items)")}
ok({"reorder_unit", "reorder_value", "roll_g"} <= cols, "migration: new columns")
old_it = item(old_it["id"])
ok(old_it["reorder_unit"] is None and old_it["reorder_point"] == 500 and old_it["qty"] == 0, "legacy item keeps grams reorder line")

# ---------- 按卷入库：N 卷 = N 条料卷记录 + 编号；每卷净重用物品默认或填的 ----------
fw = new_fil("PLA", "白色", roll_g=1000)["item"]
d = inv.create_doc("purchase", [{"item_id": fw["id"], "rolls": 2, "net_g": 1000, "unit_cost": 0.2}], "", "t")
codes = d["spool_codes"]
ok(len(codes) == 2 and all(re.fullmatch(r"F\d{4}", x) for x in codes) and len(set(codes)) == 2, f"receive 2 rolls -> 2 spool codes {codes}")
ok([materials.spool_get(x)["status"] for x in codes] == ["sealed", "sealed"] and materials.spool_get(codes[0])["net_g"] == 1000, "spools sealed 1000 g")
ok(abs(item(fw["id"])["qty"] - 2000) < 1e-6 and d["lines"][0]["rolls"] == 2 and d["lines"][0]["spools"] == codes, "item qty 2000 g, doc line remembers rolls + spools")
ok(C.get(f"/print/spools?ids={','.join(codes)}").status_code == 200, "label print for the new rolls")
# 净重不填 = 物品自己的默认
d85 = new_fil("PETG", "黑色", roll_g=850)["item"]
dd = inv.create_doc("purchase", [{"item_id": d85["id"], "rolls": 3}], "", "t")
ok(all(materials.spool_get(x)["net_g"] == 850 and materials.spool_get(x)["remaining_g"] == 850 for x in dd["spool_codes"]) and abs(item(d85["id"])["qty"] - 2550) < 1e-6,
   "net g per roll from the item default (850)")
ok(units.roll_g_of(item(d85["id"])) == 850 and units.roll_g_of(item(fw["id"]) | {"roll_g": None}) == 1000, "roll_g_of: item default, then settings")
for bad in ({"rolls": 0, "qty": 0}, {"rolls": 1.5}):
    try:
        inv.create_doc("purchase", [{"item_id": fw["id"], **bad}], "", "t"); ok(False, f"bad rolls {bad} refused")
    except ValueError:
        ok(True, f"bad rolls {bad} refused")

# ---------- 库存表：卷数（整卷 / 开封 / 在机上）+ 重量 ----------
inv.consume_production("PLA", "白色", 27, "打印完成 t", "t", None, "run:t0")          # 没登记机上那卷 -> 开一卷整卷来扣（开封卷 973 g）
r = row_of(fw["id"])
u = r["units"]
ok(u["rolls"] == 2 and u["sealed"] == 1 and u["open"] == 1 and u["loaded"] == 0 and abs(u["grams"] - 1973) < 1e-6, f"rolls: {u}")
ok(u["text_zh"] == "2 卷（1 整卷 + 1 开封卷）· 1.97 kg", u["text_zh"])
ok(u["text_th"] == "2 ม้วน (1 ม้วนเต็ม + 1 ม้วนเปิดแล้ว) · 1.97 kg" and not CJK.search(u["text_th"]), u["text_th"])
ok(units.fmt_g(1000) == "1.0 kg" and units.fmt_g(973) == "973 g" and units.fmt_g(1500) == "1.5 kg" and units.fmt_g(12345) == "12.35 kg", "weight format")
# 上机：开封那卷装到 P1S-01 · A1 -> 在机上
op = next(s for s in spools_of("PLA", "白色") if s["status"] == "open")
x = C.post(f"/api/inv/spools/{op['code']}/load", json={"printer": "P1S-01", "slot": "A1"}).get_json()
ok(x["ok"], f"load {x.get('error', '')}")
u = row_of(fw["id"])["units"]
ok(u["rolls"] == 2 and u["sealed"] == 1 and u["loaded"] == 1 and u["open"] == 0 and u["text_zh"] == "2 卷（1 整卷 + 1 在机上）· 1.97 kg", u["text_zh"])
# 用完的、记成负数的占位卷不算
ok(units.spool_stats()[("PLA", "白色")]["rolls"] == 2, "empty / negative placeholder spools not counted")

# ---------- 货位分布 ----------
r = row_of(fw["id"])
by = {x["code"]: x for x in r["locs"]}
sealed_loc = next(x for x in r["locs"] if x["ztype"] != "production")
prod_loc = next(x for x in r["locs"] if x["ztype"] == "production")
ok(sealed_loc["rolls"] == 1 and sealed_loc["text_zh"] == f"{sealed_loc['code']}：1 卷 · 1.0 kg", f"distribution (shelf) {sealed_loc['text_zh']}")
ok(prod_loc["code"] == f"{p1}-02-01" and prod_loc["text_zh"] == f"{p1}-02-01（打印机上）：1 卷 · 973 g", f"distribution (printer) {prod_loc['text_zh']}")
ok(prod_loc["text_th"] == f"{p1}-02-01 (บนเครื่องพิมพ์): 1 ม้วน · 973 g" and not CJK.search(prod_loc["text_th"] + sealed_loc["text_th"]), prod_loc["text_th"])
ok(r.get("unplaced_rolls") == 0, "no unplaced rolls")

# ---------- 打印照旧按克，扣在机上那卷 ----------
inv.consume_production("PLA", "白色", 100, "打印完成 t1", "t", 0, "run:t1")
ok(abs(materials.spool_get(op["code"])["remaining_g"] - 873) < 1e-6 and abs(item(fw["id"])["qty"] - 1873) < 1e-6, "print consumes grams from the loaded roll")
ok(row_of(fw["id"])["units"]["rolls"] == 2 and row_of(fw["id"])["units"]["text_zh"].endswith("· 1.87 kg"), "roll count unchanged by grams consumption")

# ---------- 补货线：按卷 / 按公斤，提醒和补货建议跟着 ----------
def reorder(unit, val, qty=None):
    b = {"id": fw["id"], "reorder_unit": unit, "reorder_value": val}
    if qty is not None:
        b["reorder_qty_value"] = qty
    return C.post("/api/inv/items", json=b).get_json()
x = reorder("roll", 2)
it = item(fw["id"])
ok(x["ok"] and it["reorder_unit"] == "roll" and it["reorder_value"] == 2 and it["reorder_point"] == 2000, f"reorder 2 rolls stored (grams synced {it['reorder_point']})")
al = {a["item_id"]: a for a in C.get("/api/inv/meta").get_json()["alerts"]}
ok(fw["id"] in al and al[fw["id"]]["qty_zh"] == "2 卷" and al[fw["id"]]["point_zh"] == "2 卷" and al[fw["id"]]["point_th"] == "2 ม้วน", f"alert by rolls {al.get(fw['id'])}")
reorder("kg", 1.5)
it = item(fw["id"])
al = {a["item_id"] for a in C.get("/api/inv/meta").get_json()["alerts"]}
ok(it["reorder_unit"] == "kg" and it["reorder_point"] == 1500 and fw["id"] not in al, "reorder 1.5 kg: 1.87 kg is fine")
reorder("kg", 1.9)
al = {a["item_id"]: a for a in C.get("/api/inv/meta").get_json()["alerts"]}
ok(fw["id"] in al and al[fw["id"]]["point_zh"] == "1.9 kg" and al[fw["id"]]["qty_zh"] == "1.87 kg", f"reorder 1.9 kg: alert {al.get(fw['id'])}")
reorder("roll", 1)
al = {a["item_id"] for a in C.get("/api/inv/meta").get_json()["alerts"]}
ok(fw["id"] not in al and row_of(fw["id"])["low"] is False, "reorder 1 roll: 2 rolls is fine even though grams < 2 kg")
ok(row_of(fw["id"])["reorder_zh"] == "1 卷" and row_of(fw["id"])["reorder_th"] == "1 ม้วน", "reorder text")
# 数据库里是不是低于补货线，各处看法一致（库存页数字卡片、物品列表、概况）
reorder("roll", 2, 3)
ok(item(fw["id"])["reorder_qty"] == 3000, "reorder qty in rolls -> grams")
ok(fw["id"] in {a["item_id"] for a in inv.alerts()} and inv.overview()["filament"]["low"] >= 1 and row_of(fw["id"])["low"] is True, "alerts / overview / list agree")
ok(fw["id"] in {x["id"] for x in inv.items("filament", "", True)}, "low_only filter by rolls")
# 老接口直接给克数 = 回到按克
C.post("/api/inv/items", json={"id": fw["id"], "reorder_point": 900})
it = item(fw["id"])
ok(it["reorder_unit"] is None and it["reorder_value"] is None and it["reorder_point"] == 900, "legacy grams save clears the unit")
bad = C.post("/api/inv/items", json={"id": fw["id"], "reorder_unit": "box", "reorder_value": 1}).get_json()
ok(not bad.get("ok"), "bad reorder unit refused")
reorder("roll", 3, 3)

# ---------- 采购建议：按卷，带公斤和金额；转成采购单也是卷 ----------
sg = [s for s in inv.suggest() if s["item"]["id"] == fw["id"]]
ok(sg and sg[0]["rolls"] and sg[0]["qty"] == sg[0]["rolls"] * sg[0]["net_g"] and sg[0]["rolls"] == 3, f"core suggest in rolls (reorder qty 3 rolls) {sg and (sg[0]['rolls'], sg[0]['qty'])}")
pr = pur_suggest.compute(include_all=True)
row = next(x for x in pr["rows"] if x["item"]["id"] == fw["id"])
ok(row["rolls"] and abs(row["qty_kg"] - row["rolls"] * row["net_g"] / 1000) < 1e-6 and row["urgency"] in ("yellow", "red") and "reorder" in row["why"], f"pur suggest rows: {row['rolls']} rolls {row['qty_kg']} kg")
ok(row["stock"]["rolls"] == 2 and row["stock"]["text_zh"].startswith("2 卷") and row["reorder_zh"] == "3 卷" and row["reorder_th"] == "3 ม้วน", "pur suggest shows stock rolls + reorder line")
ok(row["est_cost"] is not None and row["est_cost"] > 0 and row["unit_price"] is not None, f"amount shown {row['est_cost']} (per kg cost: {row['unit_price'] * 1000:.0f}/kg)")
api = C.get("/api/inv/pur/suggest?all=1").get_json()
ok(api["ok"] and any(x["item"]["id"] == fw["id"] and x["rolls"] == row["rolls"] for x in api["rows"]), "suggest api")
pos = pur_suggest.create_pos([{"item_id": fw["id"]}], "t")
ln = pos[0]["lines"][0]
ok(ln["rolls"] == row["rolls"] and ln["net_g"] == row["net_g"] and ln["qty"] == ln["rolls"] * ln["net_g"], f"PO line in rolls {ln['rolls']} x {ln['net_g']}")
ok(ln["unit_cost"] and abs(pos[0]["goods_total_cur"] - ln["qty"] * ln["unit_cost"]) < 0.01, "PO amount = grams x cost per gram (cost still per kg)")
# 提醒线按卷时，在途的卷也算（买了就别再建议）
inv.po_action(pos[0]["id"], "order", "t")
pr2 = pur_suggest.compute(include_all=True)
row2 = next(x for x in pr2["rows"] if x["item"]["id"] == fw["id"])
ok(row2["transit_rolls"] == row["rolls"] and row2["qty"] < row["qty"], f"in transit rolls counted ({row2['transit_rolls']}), no double buying")

# ---------- 采购到货：N 卷 = N 条料卷 + 标签；开了单的卷数不能超 ----------
before = len(spools_of("PLA", "白色"))
res = C.post("/api/inv/pur/receive", json={"po_id": pos[0]["id"], "qtys": {str(ln["id"]): ln["rolls"]}, "locations": {}}).get_json()
ok(res["ok"] and len(res["spools"]) == ln["rolls"], f"receiving {ln['rolls']} rolls -> {len(res['spools'])} spool codes")
ok(len(spools_of("PLA", "白色")) == before + ln["rolls"] and all(materials.spool_get(cd)["status"] == "sealed" for cd in res["spools"]), "spool records created, all sealed")
ok(C.get(f"/print/spools?ids={','.join(res['spools'])}").status_code == 200, "labels for received rolls")
ok(abs(item(fw["id"])["qty"] - (1873 + ln["qty"])) < 1e-6 and row_of(fw["id"])["units"]["rolls"] == 2 + ln["rolls"], "item grams + rolls after receiving")
bad = C.post("/api/inv/pur/receive", json={"po_id": pos[0]["id"], "qtys": {str(ln["id"]): 1}}).get_json()
ok(not bad.get("ok"), "nothing left to receive")

# ---------- 领用 / 报废 / 退回 按卷 ----------
q0 = item(fw["id"])["qty"]; n0 = row_of(fw["id"])["units"]["rolls"]
d = inv.create_doc("issue", [{"item_id": fw["id"], "rolls": 2}], "试打", "t")
gone = d["lines"][0]["spools"]
ok(len(gone) == 2 and all(materials.spool_get(cd)["status"] == "empty" for cd in gone) and abs(item(fw["id"])["qty"] - (q0 - 2000)) < 1e-6
   and row_of(fw["id"])["units"]["rolls"] == n0 - 2, f"issue 2 whole rolls (sealed first) {gone}")
ok(abs(d["lines"][0]["qty"] + 2000) < 1e-6 and d["spool_codes"] == gone, "doc line grams = those rolls")
op_after = materials.spool_get(op["code"])
ok(op_after["status"] == "loaded", "loaded roll untouched by roll issue")
try:
    inv.create_doc("issue", [{"item_id": fw["id"], "rolls": 99}], "", "t"); ok(False, "issue more rolls than in stock refused")
except ValueError as e:
    ok("不够出" in str(e), f"issue more rolls than in stock refused: {e}")
ok(len(spools_of("PLA", "白色", "empty")) >= 2, "refused issue left stock alone")
q1 = item(fw["id"])["qty"]
d = inv.create_doc("return", [{"item_id": fw["id"], "rolls": 1, "net_g": 420, "opened": 1}], "领用退回", "t")
rc = d["spool_codes"][0]
ok(materials.spool_get(rc)["status"] == "open" and materials.spool_get(rc)["remaining_g"] == 420 and abs(item(fw["id"])["qty"] - (q1 + 420)) < 1e-6, "return 1 opened roll (420 g)")
d2 = inv.create_doc("return", [{"item_id": fw["id"], "rolls": 2, "net_g": 1000}], "", "t")
ok(len(d2["spool_codes"]) == 2 and all(materials.spool_get(cd)["status"] == "sealed" for cd in d2["spool_codes"]), "return 2 sealed rolls: 2 new spools")
d3 = inv.create_doc("scrap", [{"item_id": fw["id"], "rolls": 1}], "受潮", "t")
ok(len(d3["spool_codes"]) == 1 and materials.spool_get(d3["spool_codes"][0])["status"] == "empty", "scrap by roll")
# 作废冲回
before_q = item(fw["id"])["qty"]
inv.void_doc(d3["id"], "t")
ok(abs(item(fw["id"])["qty"] - (before_q + d3["lines"][0]["qty"] * -1)) < 1e-6, "voiding a roll issue puts the grams back")
# 按克领用照旧
q2 = item(fw["id"])["qty"]
inv.create_doc("issue", [{"item_id": fw["id"], "qty": 150}], "", "t")
ok(abs(item(fw["id"])["qty"] - (q2 - 150)) < 1e-6, "issue in grams still works")

# ---------- 盘点：数卷 ----------
st = inv.stocktake_start("filament", "t")
ln = next(l for l in st["lines"] if l["item_id"] == fw["id"])
sysr = ln["shelf_rolls"]          # v2.55.0：盘点账面 = 整卷 + 开封卷（在机上的不算）
ok(ln["units"]["text_zh"].startswith(f"{ln['units']['rolls']} 卷"), "stocktake line shows roll count")
inv.stocktake_save(st["id"], {str(ln["id"]): {"rolls": sysr + 1}}, "t")
s2 = inv.doc(st["id"])
l2 = next(l for l in s2["lines"] if l["item_id"] == fw["id"])
ok(l2["count_mode"] == "rolls" and l2["counted_rolls"] == sysr + 1 and abs(l2["counted"] - (item(fw["id"])["qty"] + 1000)) < 1e-6, "count rolls: +1 roll -> counted grams = book + roll_g")
q3 = item(fw["id"])["qty"]; rolls3 = len(spools_of("PLA", "白色"))
inv.stocktake_confirm(st["id"], "t")
ok(abs(item(fw["id"])["qty"] - (q3 + 1000)) < 1e-6 and len(spools_of("PLA", "白色")) == rolls3 + 1, "confirm: one new sealed spool created")
st = inv.stocktake_start("filament", "t")
ln = next(l for l in st["lines"] if l["item_id"] == fw["id"])
sysr = ln["shelf_rolls"]
inv.stocktake_save(st["id"], {str(ln["id"]): {"rolls": sysr - 1}}, "t")
q4 = item(fw["id"])["qty"]
inv.stocktake_confirm(st["id"], "t")
ok(units.shelf_rolls(units.spool_stats()[("PLA", "白色")]) == sysr - 1 and abs(item(fw["id"])["qty"] - (q4 - 1000)) < 1e-6, "count rolls: one roll missing -> one roll gone (sealed first)")
st = inv.stocktake_start("filament", "t")
lid = next(l for l in st["lines"] if l["item_id"] == fw["id"])["id"]
try:
    inv.stocktake_save(st["id"], {str(lid): {"rolls": 1.5}}, "t"); ok(False, "half roll refused")
except ValueError:
    ok(True, "half roll refused (weigh it instead)")

# ---------- 盘点：称重 = 毛重 − 空料盘 ----------
st = inv.stocktake_start("filament", "t")
ln = next(l for l in st["lines"] if l["item_id"] == fw["id"])
ls = spools_of("PLA", "白色")
a, b = ls[0], ls[1]
before_a, before_b = a["remaining_g"], b["remaining_g"]
inv.stocktake_save(st["id"], {str(ln["id"]): {"weigh": [{"code": a["code"], "gross": 1100}, {"code": b["code"], "gross": 700, "tare": 150}]}}, "t")
l3 = next(l for l in inv.doc(st["id"])["lines"] if l["item_id"] == fw["id"])
want = item(fw["id"])["qty"] - before_a - before_b + (1100 - 200) + (700 - 150)
ok(l3["count_mode"] == "weigh" and abs(l3["counted"] - want) < 1e-6, f"weigh: counted {l3['counted']} vs {want}")
inv.stocktake_confirm(st["id"], "t")
ok(materials.spool_get(a["code"])["remaining_g"] == 900 and materials.spool_get(b["code"])["remaining_g"] == 550, "confirm: those spools set to gross - tare")
ok(abs(item(fw["id"])["qty"] - sum(s["remaining_g"] for s in spools_of("PLA", "白色"))) < 1e-6, "item grams = spools after weighing")
st = inv.stocktake_start("filament", "t")
lid = next(l for l in st["lines"] if l["item_id"] == fw["id"])["id"]
try:
    inv.stocktake_save(st["id"], {str(lid): {"weigh": [{"code": "F9999", "gross": 5}]}}, "t"); ok(False, "unknown spool refused")
except ValueError:
    ok(True, "weighing a spool of another colour / unknown refused")
# 按货位盘点也能数卷
C.post("/api/inv/locations/bulk", json={"zone": "R", "layers": 1, "positions": 2, "ztype": "reserve"})
sdoc = C.post("/api/inv/stocktake", json={"area": "F1"}).get_json()
ok(sdoc["ok"], f"loc stocktake start {sdoc.get('error', '')}")
if sdoc["ok"]:
    d = sdoc["doc"]
    print("   locs:", [(l["code"], [x["code"] for x in l["rows"]]) for l in d["locs"]], "item loc:", item(fw["id"])["location"])
    cand = next((l for l in d["locs"] for x in l["rows"] if x.get("fil") and x["item_id"] == fw["id"]), None)
    ok(cand is not None, "loc stocktake lists the filament with a roll text")
    if cand:
        rowx = next(x for x in cand["rows"] if x["item_id"] == fw["id"])
        ok(rowx["book_rolls"] >= 1 and rowx["book_text_zh"].startswith(f"{rowx['book_rolls']} 卷") and not CJK.search(rowx["book_text_th"]), f"loc row text {rowx['book_text_zh']}")
        bad = C.post(f"/api/inv/stocktake/{d['id']}/loc", json={"code": cand["code"], "counts": {str(fw["id"]): 500}}).get_json()
        ok(not bad.get("ok"), "loc count: grams refused for roll-managed filament")
        qa, na = item(fw["id"])["qty"], len(spools_of("PLA", "白色"))
        rr = C.post(f"/api/inv/stocktake/{d['id']}/loc", json={"code": cand["code"], "counts": {str(fw["id"]): {"rolls": rowx["book_rolls"] + 1}}}).get_json()
        ok(rr["ok"], f"loc count by rolls {rr.get('error', '')}")
        cf = C.post(f"/api/inv/stocktake/{d['id']}/confirm", json={}).get_json()
        ok(cf["ok"] and abs(item(fw["id"])["qty"] - (qa + 1000)) < 1e-6 and len(spools_of("PLA", "白色")) == na + 1, f"loc stocktake confirm: +1 roll {cf.get('error', '')}")
        ok(abs(item(fw["id"])["qty"] - sum(s["remaining_g"] for s in spools_of("PLA", "白色"))) < 1e-6, "item grams = spools after loc stocktake")

# ---------- 树脂：瓶 + 重量（毫升） ----------
rz = new_fil("RESIN", "灰色", roll_g=1000)["item"]
dr = inv.create_doc("purchase", [{"item_id": rz["id"], "rolls": 2, "net_g": 1000, "unit_cost": 0.8}], "", "t")
ur = row_of(rz["id"])["units"]
ok(ur["kind"] == "bottle" and ur["rolls"] == 2 and ur["text_zh"].startswith("2 瓶（2 整瓶）· 2.0 kg ≈ ") and ur["text_zh"].endswith(" ml"), ur["text_zh"])
ok(ur["ml"] == round(2000 / 1.1) and ur["text_th"].startswith("2 ขวด (2 ขวดเต็ม) · 2.0 kg") and not CJK.search(ur["text_th"]), ur["text_th"])
reorder_r = C.post("/api/inv/items", json={"id": rz["id"], "reorder_unit": "roll", "reorder_value": 3}).get_json()
ra = {a["item_id"]: a for a in C.get("/api/inv/meta").get_json()["alerts"]}
ok(rz["id"] in ra and ra[rz["id"]]["qty_zh"] == "2 瓶" and ra[rz["id"]]["point_zh"] == "3 瓶" and ra[rz["id"]]["point_th"] == "3 ขวด", f"resin alert by bottles {ra.get(rz['id'])}")
rrow = next(x for x in pur_suggest.compute(include_all=True)["rows"] if x["item"]["id"] == rz["id"])
ok(rrow["rolls"] and rrow["stock"]["kind"] == "bottle", f"resin suggestion in bottles ({rrow['rolls']})")
inv.consume_production("RESIN", "灰色", 120, "打印完成 t", "t", None, "run:r")
ur = row_of(rz["id"])["units"]
ok(ur["rolls"] == 2 and ur["text_zh"].startswith("2 瓶（1 整瓶 + 1 开封瓶）· 1.88 kg"), f"resin consumed in grams: {ur['text_zh']}")
d = inv.create_doc("issue", [{"item_id": rz["id"], "rolls": 1}], "", "t")
ok(len(d["spool_codes"]) == 1 and row_of(rz["id"])["units"]["rolls"] == 1, "resin issue by bottle")

# ---------- 其他分类不变 ----------
pt = C.post("/api/inv/items", json={"name_zh": "喷嘴 0.4", "category": "part", "unit": "个", "reorder_point": 5, "reorder_qty": 10}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": pt["id"], "qty": 3, "unit_cost": 50}], "", "t")
rp = row_of(pt["id"])
ok("units" not in rp and rp["unit"] == "个" and rp["low"] is True and rp["reorder_point"] == 5 and rp["qty"] == 3, "part: no units, low by quantity")
ok(pt["id"] in {a["item_id"] for a in inv.alerts()} and not any("units" in a for a in inv.alerts() if a["item_id"] == pt["id"]), "part alert unchanged")
sp = next(s for s in inv.suggest() if s["item"]["id"] == pt["id"])
ok("rolls" not in sp and sp["qty"] >= 7, "part suggestion in pieces")
r = C.post("/api/inv/docs", json={"kind": "issue", "lines": [{"item_id": pt["id"], "qty": 1, "rolls": 5}]}).get_json()
ok(r.get("ok") and item(pt["id"])["qty"] == 2, "rolls on a non-filament line ignored: 1 piece issued")

# ---------- 页面文字（界面里中文 / 泰文都带 Z，库存页文件语法） ----------
for f in ("inventory.js", "zones.js", "stocktake.js"):
    src = open(os.path.join(APP, "modules/inv/ui", f), encoding="utf-8").read()
    ok("units" in src or f != "inventory.js", f"{f} uses units")

print("ERRORS", E_)
