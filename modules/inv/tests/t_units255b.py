# v2.55.0 复审：按卷盘点（在机上的不算账面、按货位只动数的那个货位、确认时按现在的账面重算）、指定料卷开单先查清楚 + 失败回滚、
# 整卷出库 / 入库作废精确冲回、按卷补货线在货位列表 / 按商品视图里不再拿克数比、分页参数不是数字不再 500
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, json
D = T + "/m_units255b"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, inventory as inv, materials
from core.inventory import units
from modules.inv import locations as L, wms, flows, stocktake as ST
C = A.app.test_client()
config.save_config({"review_enabled": False, "inv_loss_rate": 0, "inv_spool_tare_g": 200, "inv_loc_auto": False,
                    "printers": [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "ams": True}]})
item = lambda iid: inv.get_item(iid)
def new_fil(mat, col, **kw):
    return C.post("/api/inv/items", json={"name_zh": f"{mat} {col}", "category": "filament", "material": mat, "color": col, **kw}).get_json()["item"]
def spools(m, col, st="active"):
    return materials.spools(m, col, status=st)
def st_of(code):
    return materials.spool_get(code)["status"]
def sid(code):
    return int(code[1:])
def loc_of(code):
    r = db.conn().execute("SELECT l.code FROM inv_spool_loc s JOIN inv_locations l ON l.id=s.loc_id WHERE s.spool_id=?", (sid(code),)).fetchone()
    return r["code"] if r else None
def n_docs():
    return db.conn().execute("SELECT COUNT(*) n FROM inv_docs").fetchone()["n"]
C.post("/api/inv/locations/bulk", json={"zone": "F", "layers": 1, "positions": 4, "ztype": "supply", "categories": ["filament", "part"]})

# ---------- 3a 盘点账面卷数不含在机上的 ----------
f1 = new_fil("PLA", "红色", roll_g=1000)
d = inv.create_doc("purchase", [{"item_id": f1["id"], "rolls": 3, "net_g": 1000, "unit_cost": 0.2}], "", "t")
c1, c2, c3 = d["spool_codes"]
materials.spool_action(sid(c3), "load", "t", "P1S-01", "A1")
q0 = item(f1["id"])["qty"]
ok(st_of(c3) == "loaded" and units.shelf_rolls(units.spool_stats()[("PLA", "红色")]) == 2, "3 rolls, 1 on the printer: shelf book = 2")
st = inv.stocktake_start("filament", "t")
ln = next(x for x in st["lines"] if x["item_id"] == f1["id"])
ok(ln["shelf_rolls"] == 2 and ln["units"]["loaded"] == 1, "stocktake line: shelf rolls 2, loaded 1 shown separately")
inv.stocktake_save(st["id"], {str(ln["id"]): {"rolls": 2}}, "t")           # 只数架子上的 2 卷
inv.stocktake_confirm(st["id"], "t")
ok(abs(item(f1["id"])["qty"] - q0) < 1e-6 and st_of(c1) == "sealed" and st_of(c2) == "sealed" and st_of(c3) == "loaded",
   "counting just the shelf rolls: no loss, nothing marked empty, loaded roll untouched")
st = inv.stocktake_start("filament", "t")
ln = next(x for x in st["lines"] if x["item_id"] == f1["id"])
inv.stocktake_save(st["id"], {str(ln["id"]): {"rolls": 1}}, "t")
inv.stocktake_confirm(st["id"], "t")
ok(st_of(c3) == "loaded" and [st_of(c1), st_of(c2)].count("empty") == 1 and abs(item(f1["id"])["qty"] - (q0 - 1000)) < 1e-6,
   "one shelf roll missing -> exactly one shelf roll gone, loaded stays")

# ---------- 3c 填数以后账面变了：确认时按现在的账面重算，并提示 ----------
f2 = new_fil("PETG", "蓝色", roll_g=1000)
inv.create_doc("purchase", [{"item_id": f2["id"], "rolls": 2, "net_g": 1000}], "", "t")
st = inv.stocktake_start("filament", "t")
ln = next(x for x in st["lines"] if x["item_id"] == f2["id"])
inv.stocktake_save(st["id"], {str(ln["id"]): {"rolls": 2}}, "t")           # 数到 2 卷 = 没差异
inv.create_doc("issue", [{"item_id": f2["id"], "rolls": 1}], "", "t")      # 盘点期间领走一卷
w = next(x for x in inv.doc(st["id"])["lines"] if x["item_id"] == f2["id"])
ok(w["warn"] and w["warn"]["was"] == 2 and w["warn"]["now"] == 1 and not w["warn"]["done"], f"draft shows the book changed {w['warn']}")
inv.stocktake_confirm(st["id"], "t")
w = next(x for x in inv.doc(st["id"])["lines"] if x["item_id"] == f2["id"])
ok(len(spools("PETG", "蓝色")) == 2 and abs(item(f2["id"])["qty"] - 2000) < 1e-6 and w["warn"] and w["warn"]["done"],
   f"confirm recomputes against the current book: counted 2 -> 2 rolls on the shelf, warning kept {w['warn']}")

# ---------- 3b 按货位盘点：只动数的那个货位 ----------
f3 = new_fil("ABS", "黑色", roll_g=1000)
d = inv.create_doc("purchase", [{"item_id": f3["id"], "rolls": 3, "net_g": 1000}], "", "t")
sa, sb, sc = d["spool_codes"]
flows.spool_put(sid(sa), "F1-01-01", "t"); flows.spool_put(sid(sb), "F1-01-01", "t"); flows.spool_put(sid(sc), "F1-01-02", "t")
ok(loc_of(sa) == "F1-01-01" and loc_of(sc) == "F1-01-02", "setup: 2 rolls in F1-01-01, 1 in F1-01-02")
doc = ST.start("F1-01-01,F1-01-02", "t")
c = ST.count(doc["id"], "F1-01-01", {str(f3["id"]): {"rolls": 1}}, "t")        # 货位 1 数到 1 卷（账面 2）
row = next(x for l in c["locs"] if l["code"] == "F1-01-01" for x in l["rows"] if x["item_id"] == f3["id"])
ok(row["book_rolls"] == 2, "loc book rolls = shelf rolls at that location")
ST.confirm(doc["id"], "t")
ok([st_of(sa), st_of(sb)].count("empty") == 1 and st_of(sc) == "sealed" and loc_of(sc) == "F1-01-02",
   "missing roll taken from the counted location, the other location untouched")
doc = ST.start("F1-01-02", "t")
ST.count(doc["id"], "F1-01-02", {str(f3["id"]): {"rolls": 3}}, "t")             # 货位 2 多出 2 卷
ST.confirm(doc["id"], "t")
here = [s for s in spools("ABS", "黑色") if loc_of(s["code"]) == "F1-01-02"]
ok(len(here) == 3 and all(loc_of(s["code"]) for s in spools("ABS", "黑色")),
   f"surplus rolls land in the counted location, not 待上架 ({[loc_of(s['code']) for s in spools('ABS', '黑色')]})")
ok(abs(item(f3["id"])["qty"] - sum(s["remaining_g"] for s in spools("ABS", "黑色"))) < 1e-6, "item grams = spools after loc stocktake")
# 数架子上的卷（在机上的不算）= 没差异
f4 = new_fil("PLA", "黄色", roll_g=1000)
d = inv.create_doc("purchase", [{"item_id": f4["id"], "rolls": 2, "net_g": 1000}], "", "t")
pa, pb = d["spool_codes"]
flows.spool_put(sid(pa), "F1-01-03", "t"); flows.spool_put(sid(pb), "F1-01-03", "t")
materials.spool_action(sid(pb), "load", "t", "P1S-01", "A2")
doc = ST.start("F1-01-03", "t")
here = [s for s in spools("PLA", "黄色") if loc_of(s["code"]) == "F1-01-03" and s["status"] != "loaded"]
ST.count(doc["id"], "F1-01-03", {str(f4["id"]): {"rolls": len(here)}}, "t")
ST.confirm(doc["id"], "t")
ok(st_of(pa) == "sealed" and st_of(pb) == "loaded", "loc count matching the shelf rolls: nothing lost")
# 货位盘点期间账面变了
doc = ST.start("F1-01-03", "t")
ST.count(doc["id"], "F1-01-03", {str(f4["id"]): {"rolls": 1}}, "t")
f4b = inv.create_doc("purchase", [{"item_id": f4["id"], "rolls": 1, "net_g": 1000}], "", "t")["spool_codes"][0]
flows.spool_put(sid(f4b), "F1-01-03", "t")                                      # 盘点期间又放进来 1 卷
s = ST.summary(doc["id"])
r_ = next(x for l in s["locs"] for x in l["rows"] if x["item_id"] == f4["id"])
ok(r_.get("sys_changed") == {"was": 1, "now": 2}, f"loc summary warns the book changed {r_.get('sys_changed')}")
ST.confirm(doc["id"], "t")
ok(len([x for x in spools("PLA", "黄色") if loc_of(x["code"]) == "F1-01-03" and x["status"] != "loaded"]) == 1,
   "confirm recomputed: counted 1 vs current 2 -> 1 roll left there")

# ---------- 指定料卷开单：先查清楚；中途失败整张回滚 ----------
f5 = new_fil("PLA", "绿色", roll_g=1000)
f6 = new_fil("PLA", "白色", roll_g=1000)
da = inv.create_doc("purchase", [{"item_id": f5["id"], "rolls": 3, "net_g": 1000}, {"item_id": f6["id"], "rolls": 1, "net_g": 1000}], "", "t")
g1, g2, g3 = da["spool_codes"][:3]; w1 = da["spool_codes"][3]
materials.spool_action(sid(g3), "load", "t", "P1S-01", "A3")
inv.create_doc("issue", [{"item_id": f5["id"], "rolls": 1, "spools": [g2]}], "", "t")     # g2 用完
q5 = item(f5["id"])["qty"]
def bad(lines, why):
    n0 = n_docs()
    try:
        inv.create_doc("issue", lines, "", "t"); ok(False, why + " (accepted)")
    except ValueError as e:
        ok(n_docs() == n0 and abs(item(f5["id"])["qty"] - q5) < 1e-6, f"{why}: refused before creating the doc ({e})")
bad([{"item_id": f5["id"], "rolls": 1, "spools": [g2]}], "empty spool")
bad([{"item_id": f5["id"], "rolls": 1, "spools": [g3]}], "loaded spool")
bad([{"item_id": f5["id"], "rolls": 1, "spools": [w1]}], "other colour spool")
bad([{"item_id": f5["id"], "rolls": 2, "spools": [g1]}], "count differs from rolls")
bad([{"item_id": f5["id"], "rolls": 2, "spools": [g1, g1]}], "duplicate code")
bad([{"item_id": f5["id"], "rolls": 1, "spools": ["F9999"]}], "unknown spool")
orig = materials.take_rolls
calls = []
def flaky(*a, **k):
    calls.append(1)
    if len(calls) == 2:
        raise ValueError("boom")
    return orig(*a, **k)
materials.take_rolls = flaky
try:
    inv.create_doc("issue", [{"item_id": f5["id"], "rolls": 1, "spools": [g1]}, {"item_id": f6["id"], "rolls": 1}], "", "t"); ok(False, "flaky apply raised")
except ValueError:
    pass
materials.take_rolls = orig
dd = db.conn().execute("SELECT * FROM inv_docs ORDER BY id DESC LIMIT 1").fetchone()
ok(dd["status"] == "void" and st_of(g1) == "sealed" and abs(item(f5["id"])["qty"] - q5) < 1e-6 and st_of(w1) == "sealed",
   "apply failure: earlier line rolled back, doc not left as done")

# ---------- 作废按卷的单：精确冲回 ----------
f7 = new_fil("TPU", "透明", roll_g=1000)
rc = inv.create_doc("purchase", [{"item_id": f7["id"], "rolls": 2, "net_g": 1000, "unit_cost": 0.3}], "", "t")
h1, h2 = rc["spool_codes"]
inv.void_doc(rc["id"], "t")
ok(st_of(h1) == "empty" and st_of(h2) == "empty" and abs(item(f7["id"])["qty"]) < 1e-6, "void a roll receipt: the created spools are gone, stock back to 0")
rc = inv.create_doc("purchase", [{"item_id": f7["id"], "rolls": 2, "net_g": 1000}], "", "t")
h1, h2 = rc["spool_codes"]
materials.consume("TPU", "透明", 300, "print", "t")                                  # 用掉一点
q7 = item(f7["id"])["qty"]
try:
    inv.void_doc(rc["id"], "t"); ok(False, "void of a partly used receipt refused")
except ValueError as e:
    ok(db.conn().execute("SELECT status FROM inv_docs WHERE id=?", (rc["id"],)).fetchone()["status"] == "done" and abs(item(f7["id"])["qty"] - q7) < 1e-6
       and st_of(h1) != "empty" and st_of(h2) != "empty", f"void of a receipt whose roll was used: refused, nothing changed ({e})")
f8 = new_fil("PLA", "灰色", roll_g=1000)
r8 = inv.create_doc("purchase", [{"item_id": f8["id"], "rolls": 2, "net_g": 1000}], "", "t")
k1, k2 = r8["spool_codes"]
materials.spool_action(sid(k1), "load", "t", "P1S-01", "A4"); materials.consume("PLA", "灰色", 400, "print", "t", "P1S-01")
materials.spool_action(sid(k1), "unload", "t")
rem = materials.spool_get(k1)["remaining_g"]
q8 = item(f8["id"])["qty"]
iss = inv.create_doc("issue", [{"item_id": f8["id"], "rolls": 2}], "", "t")
ok(st_of(k1) == "empty" and st_of(k2) == "empty" and abs(item(f8["id"])["qty"]) < 1e-6, "roll issue took both spools")
inv.void_doc(iss["id"], "t")
ok(st_of(k2) == "sealed" and st_of(k1) == "open" and abs(materials.spool_get(k1)["remaining_g"] - rem) < 1e-6 and abs(item(f8["id"])["qty"] - q8) < 1e-6,
   f"void a roll issue: spools restored exactly (sealed / open {rem:g} g), stock back {item(f8['id'])['qty']}")
ok(abs(item(f8["id"])["qty"] - sum(s["remaining_g"] for s in spools("PLA", "灰色"))) < 1e-6, "item grams = spools after void")
iss2 = inv.create_doc("issue", [{"item_id": f8["id"], "rolls": 1}], "", "t")
ln = db.conn().execute("SELECT id, extra FROM inv_doc_lines WHERE doc_id=?", (iss2["id"],)).fetchone()
ex = json.loads(ln["extra"]); ex.pop("prev", None)
db.conn().execute("UPDATE inv_doc_lines SET extra=? WHERE id=?", (json.dumps(ex), ln["id"])); db.conn().commit()
try:
    inv.void_doc(iss2["id"], "t"); ok(False, "legacy roll issue void refused")
except ValueError as e:
    ok("不能作废" in str(e), f"legacy roll issue without prev: clear refusal ({e})")

# ---------- 按卷补货线：货位列表 / 按商品视图不再拿克数比 ----------
f9 = new_fil("PLA", "橙色", roll_g=1000)
r9 = inv.create_doc("purchase", [{"item_id": f9["id"], "rolls": 3, "net_g": 1000}], "", "t")
for cd in r9["spool_codes"]:
    flows.spool_put(sid(cd), "F1-01-04", "t")
materials.consume("PLA", "橙色", 500, "print", "t")
C.post("/api/inv/items", json={"id": f9["id"], "reorder_unit": "roll", "reorder_value": 1})
rolls_now = units.spool_stats()[("PLA", "橙色")]["rolls"]
it9 = item(f9["id"])
ok(it9["reorder_point"] == 1000 and it9["qty"] > 1000 and rolls_now == 3, f"setup: grams {it9['qty']:g} > 1000 and rolls {rolls_now}")
rows = C.get("/api/inv/loc/items?flag=low&size=200").get_json()
ok(f9["id"] not in [x["id"] for x in (rows.get("rows") or [])], "by-item low filter: not low when rolls above the roll line")
r = next((x for x in (C.get("/api/inv/loc/items?size=200").get_json().get("rows") or []) if x["id"] == f9["id"]), None)
ok(r is not None and r["low"] is False and "low" not in r["flags"], "by-item row not flagged low")
C.post("/api/inv/items", json={"id": f9["id"], "reorder_unit": "roll", "reorder_value": 3})
r = next(x for x in C.get("/api/inv/loc/items?size=200").get_json()["rows"] if x["id"] == f9["id"])
ok(r["low"] is True and "low" in r["flags"], "rolls at the line -> flagged low")
ok(f9["id"] in [x["id"] for x in C.get("/api/inv/loc/items?flag=low&size=200").get_json()["rows"]], "low filter lists it")
lr = C.get("/api/inv/loc/list?size=200").get_json()
cell = next((it for l in lr["rows"] if l["code"] == "F1-01-04" for it in l["items"] if it["id"] == f9["id"]), None)
ok(cell is not None and cell["low"] is True, "location list item flag low by rolls")
C.post("/api/inv/items", json={"id": f9["id"], "reorder_unit": "roll", "reorder_value": 1})
lr = C.get("/api/inv/loc/list?size=200").get_json()
cell = next((it for l in lr["rows"] if l["code"] == "F1-01-04" for it in l["items"] if it["id"] == f9["id"]), None)
ok(cell is not None and cell["low"] is False, "location list item flag not low when rolls above the line")

# ---------- 分页参数不是数字不再 500 ----------
for u in ("/api/inv/items?view=stock&page=abc&size=xyz", "/api/inv/items?view=stock&page=1&size=-5", "/api/inv/moves?limit=abc", "/api/inv/moves?limit=999999999999",
          "/api/inv/loc/suggest?q=A&limit=zz", "/api/v1/finance/events?since=zz&limit=bad", "/api/inv/loc/list?page=x&size=y"):
    r = C.get(u)
    ok(r.status_code < 500, f"{u} -> {r.status_code}")
r = C.get("/api/inv/items?view=stock&page=1&size=99999").get_json()
ok(r.get("ok") and r["size"] <= 200, f"size bounded ({r.get('size')})")


# ---------- 复审：打印机槽位不数卷 / 作废放回原货位 / 删除的货位跳过 ----------
f10 = new_fil("PLA", "紫色", roll_g=1000)
d = inv.create_doc("purchase", [{"item_id": f10["id"], "rolls": 3, "net_g": 1000}], "", "t")
p1, p2, p3 = d["spool_codes"]
flows.spool_put(sid(p1), "F1-01-01", "t"); flows.spool_put(sid(p2), "F1-01-01", "t")
slotc = flows.slot_loc(db.conn(), "P1S-01", "A2")["code"]
flows.spool_put(sid(p3), slotc, "t")
ok(st_of(p3) == "loaded", "setup: roll loaded on printer slot")
doc = ST.start(slotc + ",F1-01-01", "t")
try:
    ST.count(doc["id"], slotc, {str(f10["id"]): {"rolls": 5}}, "t"); e = ""
except ValueError as ex_:
    e = str(ex_)
ok("打印机上的料卷不用数" in e, f"counting rolls on a printer slot refused ({e})")
ST.count(doc["id"], "F1-01-01", {str(f10["id"]): {"rolls": 4}}, "t")
ST.confirm(doc["id"], "t")
ok(st_of(p3) == "loaded" and len(spools("PLA", "紫色")) == 5, "surplus rolls created, loaded roll not displaced")
# 旧单子里已经有打印机槽位的卷数记录：确认时也不放卷、不顶下机
doc = ST.start("F1-01-01", "t")
ST.count(doc["id"], "F1-01-01", {str(f10["id"]): {"rolls": 4}}, "t")
cn = db.conn()
slot_id = L.get_loc(slotc)["id"]
ln_ = cn.execute("SELECT id, extra FROM inv_doc_lines WHERE doc_id=? AND item_id=?", (doc["id"], f10["id"])).fetchone()
ex_ = json.loads(ln_["extra"]); ex_["by_loc"][str(slot_id)] = [3, 1]; ex_["by_loc"]["999999"] = [2, 0]      # 打印机槽位 + 已删除的货位
cn.execute("UPDATE inv_doc_lines SET extra=? WHERE id=?", (json.dumps(ex_), ln_["id"])); cn.commit()
try:
    ST.confirm(doc["id"], "t"); e = ""
except Exception as ex2:
    e = repr(ex2)
ok(e == "" and st_of(p3) == "loaded", f"confirm skips printer-slot and deleted locations, loaded roll stays ({e})")

# 出库作废：放回原来的货位
f11 = new_fil("PLA", "青色", roll_g=1000)
d = inv.create_doc("purchase", [{"item_id": f11["id"], "rolls": 2, "net_g": 1000}], "", "t")
q1, q2 = d["spool_codes"]
flows.spool_put(sid(q1), "F1-01-03", "t"); flows.spool_put(sid(q2), "F1-01-04", "t")
iss = inv.create_doc("issue", [{"item_id": f11["id"], "rolls": 2}], "", "t")
ok(loc_of(q1) is None, "emptied roll lost its location")
inv.void_doc(iss["id"], "t")
ok(loc_of(q1) == "F1-01-03" and loc_of(q2) == "F1-01-04", f"void restores rolls to original locations {loc_of(q1)} {loc_of(q2)}")

# 作废：按卷冲回失败时单据不标作废
f12 = new_fil("PLA", "棕色", roll_g=1000)
d = inv.create_doc("purchase", [{"item_id": f12["id"], "rolls": 1, "net_g": 1000}], "", "t")
_orig_disc = materials.discard_rolls
def _boom(*a, **k):
    raise RuntimeError("boom")
materials.discard_rolls = _boom
try:
    inv.void_doc(d["id"], "t"); e = ""
except RuntimeError as ex3:
    e = str(ex3)
materials.discard_rolls = _orig_disc
ok(e == "boom" and inv.doc(d["id"])["status"] == "done", "void: roll reversal failed -> doc stays done")

src = open(os.path.join(APP, "modules/inv/ui/stocktake.js"), encoding="utf-8").read()
ok("shelf_rolls" in src and "book_loaded" in src, "stocktake page shows shelf rolls / loaded separately")
print("ERRORS", E_)
