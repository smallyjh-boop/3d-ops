# v2.54：生产单——来源（手工 / 成品备货补货 / 订单汇总 / 活动）、草稿 → 已下达 → 生产中 → 部分完成 → 完成 / 取消、暂停、下达建备货任务（po_id）、
# 每行进度 + ETA + 用料 + 成本、打完进待检区或直接入库、多盘产品、➕ 生产 = 一张单；
# 专用打印机：生产单指定的打印机 / 打印机 role / paused / dedicated_po 排单都要遵守，字段没填 = 照旧；打印单据、权限
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import json, os, sys, shutil, sqlite3
D = T + "/m_po254"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, production, po, printers as pr, chain
from core.config import load_config, save_config
from modules.inv import flows
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pong", "secret123", "production", "Pong")
db.create_user("lee", "secret123", "listing", "Lee")
def cli(u):
    c = A.app.test_client(); c.post("/api/auth/login", json={"username": u, "password": "secret123"}); return c
C, PC, LC = cli("boss"), cli("pong"), cli("lee")

PRS = [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "tech": "fdm"},
       {"code": "P1S-02", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "tech": "fdm"},
       {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "enabled": True, "tech": "fdm"}]
def setp(extra=None):
    prs = [dict(p, **((extra or {}).get(i) or {})) for i, p in enumerate(PRS)]
    save_config({"printers": prs, "stock_auto_use": False})
setp()
CONF = {"bed_clear": True, "material": True}
pr.send_file = lambda idx, path, name, kind, slot=None: name
SKA, SKB = "3DP0003-WH", "3DP0003-PK"
jobs_of = lambda poid: [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE po_id=? ORDER BY id", (poid,))]
run_of = lambda jid: db.conn().execute("SELECT run_id FROM jobs WHERE id=?", (jid,)).fetchone()["run_id"]
def printer_of(poid):
    return {j["sku"]: j["printer"] for j in jobs_of(poid)}

# ---------- 权限 ----------
ok(LC.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 1}]}).status_code == 403, "listing role can't create production orders")
ok(LC.get("/api/porders").status_code == 200, "everybody may read the list")

# ---------- 草稿 → 已下达 ----------
r = PC.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 3}, {"sku": SKB, "qty": 2}, {"sku": SKA, "qty": 1}], "priority": 1, "due": "2030-01-05", "note": "试试"})
d = r.get_json()
ok(r.status_code == 200 and d["status"] == "draft" and d["source"] == "manual" and d["no"].startswith("PO"), f"draft created {d.get('no')} by production role")
ok(len(d["lines"]) == 2 and next(x for x in d["lines"] if x["sku"] == SKA)["qty"] == 4, "same SKU merged into one line")
ok(d["priority"] == 1 and d["due"] > 0 and d["qty"] == 6 and d["done"] == 0, "priority / due / totals")
PID = d["id"]
ok(not jobs_of(PID), "a draft makes no print jobs")
u = C.post(f"/api/porders/{PID}", json={"lines": [{"sku": SKA, "qty": 2}, {"sku": SKB, "qty": 2}], "note": "改过"}).get_json()
ok(u["qty"] == 4 and u["note"] == "改过", "draft lines replaceable")
ok(C.post("/api/porders", json={"lines": [{"sku": "NOPE-1", "qty": 1}]}).status_code == 400, "unknown SKU refused")
ok(C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 0}]}).status_code == 400, "qty 0 refused")
ok(C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 1}], "printers": ["ZZZ-99"]}).status_code == 400, "unknown printer refused")
rel = C.post(f"/api/porders/{PID}/release").get_json()
js = jobs_of(PID)
ok(rel["status"] == "released" and len(js) == 2, f"release -> {len(js)} jobs, status {rel.get('status')}")
ok(all(j["kind"] == "stock" and j["priority_job"] == 1 and j["po_id"] == PID and j["status"] == "todo" for j in js), "jobs are stock jobs linked by po_id, priority carried")
ok(all(j["printer"] is not None for j in js), "jobs scheduled")
ok(C.post(f"/api/porders/{PID}/release").status_code == 400, "can't release twice")
ok(C.post(f"/api/porders/{PID}", json={"lines": [{"sku": SKA, "qty": 9}]}).status_code == 400, "released order's lines are frozen")
board = C.get("/api/production").get_json()
cards = [c for l in board["lanes"] for c in l["queue"]] + board["unassigned"]
ok(all(c.get("po_no") == rel["no"] for c in cards if c["id"] in {j["id"] for j in js}), "board cards carry the PO number")
ok(any(l.get("working_po") and l["working_po"]["id"] == PID for l in board["lanes"]), "board lane shows which PO a printer works on")
ok(rel["eta"] and rel["eta"] > 0, "ETA from planned_end")

# ---------- 进度：一张行打完 → 部分完成；全部打完 → 完成 ----------
flows.zone_loc(db.conn(), "pick"); db.conn().commit()           # 用上货位 → 打印出来的成品进待检区
save_config({"inv_qc_on": True})
ja, jb = (next(j for j in js if j["sku"] == SKA), next(j for j in js if j["sku"] == SKB))
production.start_run(ja["id"], ja["printer"], 2, [], None, False, "t", CONF)
g = C.get(f"/api/porders/{PID}").get_json()
ok(g["status"] == "producing", f"printing -> producing ({g['status']})")
ok(next(x for x in g["lines"] if x["sku"] == SKA)["status"] == "printing", "line shows printing")
s0 = production.stock_qty(SKA)
production.finish_run(run_of(ja["id"]), "t")
g = C.get(f"/api/porders/{PID}").get_json()
la = next(x for x in g["lines"] if x["sku"] == SKA)
ok(la["done"] == 2 and la["pct"] == 100 and g["status"] == "partial" and g["done"] == 2, f"one line done -> partial ({g['status']} {g['done']}/{g['qty']})")
ok(production.stock_qty(SKA) == s0 + 2, "goods entered stock")
ok(production.unavailable_qty(SKA) == 2 and production.sellable_qty(SKA) == s0, f"with QC on they wait in the QC zone ({production.unavailable_qty(SKA)})")
ok(g["grams"] >= 0 and la["cost"] >= 0, f"consumption {g['grams']}g + cost {g['cost']}")
save_config({"inv_qc_on": False})
production.start_run(jb["id"], jb["printer"], 2, [], None, False, "t", CONF)
production.finish_run(run_of(jb["id"]), "t")
g = C.get(f"/api/porders/{PID}").get_json()
ok(g["status"] == "done" and g["done"] == 4 and g["pct"] == 100 and g["done_at"], f"all lines done -> done ({g['status']})")
ok(production.unavailable_qty(SKB) == 0, "with QC off the goods go straight to stock")
ok(C.post(f"/api/porders/{PID}/cancel").status_code == 400, "finished order can't be cancelled")
lst = C.get("/api/porders?status=done").get_json()
ok(any(x["id"] == PID for x in lst["orders"]) and lst["counts"].get("done", 0) >= 1, "list filter + counts")

# ---------- 暂停 / 取消 ----------
r2 = C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 2}, {"sku": SKB, "qty": 2}], "release": True}).get_json()
P2 = r2["id"]
ok(r2["status"] == "released" and all(j["printer"] is not None for j in jobs_of(P2)), "create + release in one call")
pz = C.post(f"/api/porders/{P2}/pause").get_json()
ok(pz["paused"] and all(j["printer"] is None for j in jobs_of(P2)), "paused order's jobs get no printer")
try:
    production.start_run(jobs_of(P2)[0]["id"], 0, 1, [], None, False, "t", CONF); started = True
except ValueError as e:
    started = False; msg = str(e)
ok(not started and "暂停" in msg, f"can't start a job of a paused order ({msg})")
rs = C.post(f"/api/porders/{P2}/resume").get_json()
ok(not rs["paused"] and all(j["printer"] is not None for j in jobs_of(P2)), "resume schedules again")
ja2 = jobs_of(P2)[0]
production.start_run(ja2["id"], ja2["printer"], 1, [], None, False, "t", CONF)
ok(C.post(f"/api/porders/{P2}/cancel").status_code == 400, "can't cancel while a plate is printing")
production.cancel_run(run_of(ja2["id"]), "t")
cn = C.post(f"/api/porders/{P2}/cancel").get_json()
ok(cn["status"] == "cancelled" and not jobs_of(P2), "cancel removes the unstarted jobs")
ok(C.post(f"/api/porders/{P2}/release").status_code == 400, "cancelled order can't be released")

# ---------- ➕ 生产 = 一张单（一次操作一张） ----------
n0 = len(C.get("/api/porders").get_json()["orders"])
r = C.post("/api/jobs/stock", json={"items": [{"sku": SKA, "qty": 2}, {"sku": SKB, "qty": 1}], "source": "library"}).get_json()
ok(len(r["jobs"]) == 2 and r["po"]["status"] == "released" and all(j["po_id"] == r["po"]["id"] for j in r["jobs"]), "➕ 生产 makes one released order with its jobs")
ok(len(C.get("/api/porders").get_json()["orders"]) == n0 + 1, "one order per action")
r1 = C.post("/api/stock/make", json={"sku": SKA, "qty": 1}).get_json()
ok(r1["kind"] == "stock" and r1["po_id"], "stock/make also gets a PO")
# 删掉备货任务 → 单子里对应的行去掉；没行了 = 取消
for j in r["jobs"]:
    C.delete(f"/api/jobs/{j['id']}")
ok(C.get(f"/api/porders/{r['po']['id']}").get_json()["status"] == "cancelled", "deleting every job cancels the order")
C.delete(f"/api/jobs/{r1['id']}")

# ---------- 订单汇总 ----------
o1 = C.post("/api/orders/manual", json={"order_no": "PO-O1", "items": [{"sku": SKA, "qty": 2, "unit_price": 100}]}).get_json()
o2 = C.post("/api/orders/manual", json={"order_no": "PO-O2", "items": [{"sku": SKA, "qty": 1, "unit_price": 100}, {"sku": SKB, "qty": 1, "unit_price": 100}]}).get_json()
oj = [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE order_id IN (?,?) AND kind='order'", (o1["id"], o2["id"]))]
ok(len(oj) >= 3 and all(j["po_id"] is None for j in oj), "order jobs are not forced into a PO")
so = C.post("/api/porders/from-orders", json={}).get_json()
ok(so["source"] == "orders" and so["status"] == "released", "orders summary order is released at once")
ok(next(x for x in so["lines"] if x["sku"] == SKA)["qty"] >= 3, f"lines are summed per SKU {[(x['sku'], x['qty']) for x in so['lines']]}")
oj2 = [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE order_id IN (?,?) AND kind='order'", (o1["id"], o2["id"]))]
ok(all(j["po_id"] == so["id"] for j in oj2), "today's open order jobs attached (order jobs themselves unchanged)")
ok(all(j["kind"] == "order" and j["order_id"] for j in oj2), "still ordinary order jobs")
ok(C.post("/api/porders/from-orders", json={}).status_code == 400, "nothing left to attach the second time")
ja3 = oj2[0]
production.start_run(ja3["id"], ja3["printer"], ja3["qty"], [], None, False, "t", CONF); production.finish_run(run_of(ja3["id"]), "t")
g = C.get(f"/api/porders/{so['id']}").get_json()
ok(g["done"] >= ja3["qty"] and g["status"] in ("producing", "partial"), f"progress follows the order jobs ({g['done']}/{g['qty']} {g['status']})")
cn = C.post(f"/api/porders/{so['id']}/cancel").get_json()
ok(cn["status"] == "cancelled" and all(j["po_id"] is None for j in [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE order_id IN (?,?)", (o1["id"], o2["id"]))]),
   "cancelling an orders-summary order just lets go of the order jobs")

# ---------- 专用打印机：生产单指定 ----------
def clear_todo():
    for j in production.list_jobs(("todo",)):
        if j["kind"] == "stock":
            production.delete_stock_job(j["id"], "t")
clear_todo()
setp()
p3 = C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 2}, {"sku": SKB, "qty": 2}], "printers": ["K1C-01"], "release": True}).get_json()
ok(set(printer_of(p3["id"]).values()) <= {2}, f"order restricted to its printer list -> {printer_of(p3['id'])}")
setp()
C.post(f"/api/porders/{p3['id']}", json={"printers": ["P1S-02", 0]})
ok(set(printer_of(p3["id"]).values()) <= {0, 1}, f"printer list also accepts indices -> {printer_of(p3['id'])}")
C.post(f"/api/porders/{p3['id']}/cancel")

# ---------- 打印机字段：paused / role / dedicated_po ----------
setp({0: {"paused": True}, 1: {"paused": True}})
p4 = C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 1}, {"sku": SKB, "qty": 1}], "release": True}).get_json()
ok(set(printer_of(p4["id"]).values()) <= {2}, f"paused printers get no new jobs -> {printer_of(p4['id'])}")
try:
    production.start_run(jobs_of(p4["id"])[0]["id"], 0, 1, [], None, False, "t", CONF); st = True
except ValueError as e:
    st = False; m = str(e)
ok(not st and "暂停" in m, f"manual start on a paused printer refused ({m})")
setp({0: {"paused": True}, 1: {"paused": True}, 2: {"paused": True}})
production.schedule()
ok(all(j["printer"] is None for j in jobs_of(p4["id"])), "all printers paused -> jobs wait unassigned")
C.post(f"/api/porders/{p4['id']}/cancel")

setp({0: {"role": "orders"}, 1: {"role": "orders"}})
p5 = C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 1}, {"sku": SKB, "qty": 1}], "release": True}).get_json()
ok(set(printer_of(p5["id"]).values()) <= {2}, f"role orders printers don't take stock jobs -> {printer_of(p5['id'])}")
C.post(f"/api/porders/{p5['id']}/cancel")
o3 = C.post("/api/orders/manual", json={"order_no": "PO-O3", "items": [{"sku": SKA, "qty": 1, "unit_price": 100}]}).get_json()
ojs = [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE order_id=?", (o3["id"],))]
setp({2: {"role": "stock"}})
production.schedule()
ojs = [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE order_id=?", (o3["id"],))]
ok(ojs and all(j["printer"] in (0, 1) for j in ojs), f"role stock printer doesn't take order jobs -> {[j['printer'] for j in ojs]}")
setp({2: {"role": "bogus"}})
production.schedule()

p6 = C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 1}], "release": True}).get_json()
setp({0: {"dedicated_po": str(p6["id"])}})
production.schedule()
ok(printer_of(p6["id"])[SKA] in (0, 1, 2), "a PO's jobs may still use other printers")
ojs = [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE order_id=?", (o3["id"],))]
p7 = C.post("/api/porders", json={"lines": [{"sku": SKB, "qty": 1}], "release": True}).get_json()
ok(printer_of(p7["id"])[SKB] != 0 and all(j["printer"] != 0 for j in ojs), "a dedicated printer takes only its own PO's jobs")
setp({0: {"dedicated_po": str(p7["id"])}, 1: {"dedicated_po": str(p7["id"])}, 2: {"dedicated_po": str(p7["id"])}})
production.schedule()
ok(printer_of(p7["id"])[SKB] in (0, 1, 2) and printer_of(p6["id"])[SKA] is None and all(j["printer"] is None for j in [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE order_id=?", (o3["id"],))]),
   "every printer dedicated to one PO -> other jobs wait")
try:
    production.start_run(jobs_of(p6["id"])[0]["id"], 0, 1, [], None, False, "t", CONF); st = True
except ValueError as e:
    st = False; m = str(e)
ok(not st and "专用" in m, f"manual start on another PO's dedicated printer refused ({m})")
bd = C.get("/api/production").get_json()
ok(all(l["dedicated"] and l["dedicated"]["id"] == p7["id"] for l in bd["lanes"]), "board lanes show their dedicated PO")

# 专用打印机打不了这张单的东西 → 提醒
g = C.get(f"/api/porders/{p7['id']}").get_json()
ok(isinstance(g["warnings"], list), f"warnings list present ({len(g['warnings'])})")
setp({0: {"dedicated_po": str(p7["id"]), "paused": True}})
g = C.get(f"/api/porders/{p7['id']}").get_json()
ok(any(w["code"] == "paused" for w in g["warnings"]), "warns when its dedicated printer is paused")
setp({2: {"tech": "resin", "name": "Elegoo Saturn", "dedicated_po": str(p7["id"])}})
g = C.get(f"/api/porders/{p7['id']}").get_json()
ok(any(w["code"] == "tech" and w["printer"] == 2 for w in g["warnings"]), f"warns when a dedicated printer can't print the items {[w['code'] for w in g['warnings']]}")
ok(all(("zh" in w and "th" in w) for w in g["warnings"]), "warnings are bilingual")

# ---------- 字段都没有 = 照旧 ----------
setp()
clear_todo()
for r_ in db.conn().execute("SELECT id FROM production_orders WHERE status IN ('released','producing','partial')").fetchall():
    C.post(f"/api/porders/{r_['id']}/cancel")
p8 = C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 3}, {"sku": SKB, "qty": 3}], "release": True}).get_json()
ok(all(j["printer"] is not None for j in jobs_of(p8["id"])), "printers without the new fields behave as before")
ok(production.schedule() >= 0, "schedule runs with absent fields")

# ---------- 多盘产品 ----------
from core import print_files
PIDM = "3DP0002"
pm = store.load(PIDM)
pm["variants"] = [{"opt1_zh": "白色", "opt2_zh": "", "sku": "3DP0002-WH", "grams": 60, "hours": 4}]
pm["print_plans"] = {"": {"plates": [
    {"id": "p1", "name": "主体件", "printer": "Bambu Lab P1S", "layer_height": 0.2, "sets": 1, "items": [],
     "slots": [{"slot": 1, "material": "PLA", "colour": ""}], "sliced": {"filaments": [{"slot": 1, "grams": 40}], "hours": 3, "purge_g": 0, "changes": 0}},
    {"id": "p2", "name": "小零件", "printer": "Creality K1C", "layer_height": 0.2, "sets": 2, "items": [],
     "slots": [{"slot": 1, "material": "PLA", "colour": ""}], "sliced": {"filaments": [{"slot": 1, "grams": 8}], "hours": 1, "purge_g": 0, "changes": 0}}], "schemes": {}}}
store.save(pm)
setp()
pmu = C.post("/api/porders", json={"lines": [{"sku": "3DP0002-WH", "qty": 4}], "release": True}).get_json()
mj = jobs_of(pmu["id"])[0]
pl = {v["plate_id"]: v for v in next(x for x in production.list_jobs() if x["id"] == mj["id"])["plates"]}
ok(mj["multi_plate"] == 2 and pl["p1"]["prints_left"] == 4 and pl["p2"]["prints_left"] == 2, "multi-plate product in a PO: per-plate prints")
ok(pmu["lines"][0]["done"] == 0 and pmu["status"] == "released", "no sets done yet")
production.start_run(mj["id"], pl["p1"]["printer"] if pl["p1"]["printer"] is not None else 0, 1, [], None, False, "t", CONF, None, False, "p1")
g = C.get(f"/api/porders/{pmu['id']}").get_json()
ok(g["status"] == "producing" and g["done"] == 0, f"a plate printing -> producing, sets not complete yet ({g['status']})")
production.finish_run(run_of(mj["id"]) or db.conn().execute("SELECT id FROM print_runs WHERE status='printing'").fetchone()["id"], "t")
g = C.get(f"/api/porders/{pmu['id']}").get_json()
ok(g["done"] == 0, "one plate of two is not a finished set")

# ---------- 打印单据 ----------
h = C.get(f"/print/po/{PID}").get_data(as_text=True)
ok(PID and "<svg" in h and rel["no"] in h and SKA in h, "printable sheet has number, QR and SKUs")
ok("ใบสั่งผลิต" in C.get(f"/print/po/{PID}?lang=th").get_data(as_text=True), "Thai sheet")
ok(C.get("/print/po/99999").status_code == 404, "unknown sheet 404")


# ---------- 专用的单子结束 / 找不到 = 不再专用 + 提醒 ----------
setp()
for st_ in ("done", "cancelled"):
    pe = C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 1}], "release": True}).get_json()
    db.conn().execute("UPDATE production_orders SET status=? WHERE id=?", (st_, pe["id"])); db.conn().commit()
    ok(po.dedication_status(str(pe["id"]))["state"] == "ended" and po.dedication_status(pe["no"])["state"] == "ended", f"dedication to a {st_} order = ended")
    setp({0: {"dedicated_po": str(pe["id"])}, 1: {"dedicated_po": str(pe["id"])}, 2: {"dedicated_po": str(pe["id"])}})
    pn = C.post("/api/porders", json={"lines": [{"sku": SKB, "qty": 1}], "release": True}).get_json()
    production.schedule()
    ok(printer_of(pn["id"])[SKB] in (0, 1, 2), f"printers dedicated to a {st_} order still take other jobs")
    bd = production.board()
    ok(all(l.get("dedicated_warn") for l in bd["lanes"][:3]), "board lane shows the warning")
    C.post(f"/api/porders/{pn['id']}/cancel")
setp({0: {"dedicated_po": "PO000000-99"}})
ok(po.dedication_status("PO000000-99")["state"] == "missing" and po.dedication_status("")["state"] == "none", "missing / empty dedication states")
pm = C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 1}], "release": True}).get_json()
production.schedule()
ok(printer_of(pm["id"])[SKA] is not None, "dedication to a missing order doesn't block jobs")
setp()

# ---------- 打印机限制存稳定 id ----------
prs_ = load_config()["printers"]
ok(all(p.get("id") for p in prs_), "printers carry stable ids")
pa_ = C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 1}], "printers": ["K1C-01"]}).get_json()
ok(pa_["printers"] == [prs_[2]["id"]], f"stored by id {pa_['printers']}")
cfg_ = load_config(); cfg_["printers"][2]["code"] = "K1C-RENAMED"; save_config(cfg_)
ok(po.resolve_printers(pa_["printers"]) == [2] and C.get(f"/api/porders/{pa_['id']}").get_json()["printer_idx"] == [2], "renaming the code keeps the restriction")
cfg_ = load_config(); cfg_["printers"] = [cfg_["printers"][2]] + cfg_["printers"][:2]; save_config(cfg_)
ok(po.resolve_printers(pa_["printers"]) == [0], "reordering printers keeps the restriction (id -> current index)")
setp()
prs_ = load_config()["printers"]
db.conn().execute("UPDATE production_orders SET printers=? WHERE id=?", (json.dumps(["P1S-02"]), pa_["id"])); db.conn().commit()
po.rules(prs_)
ok(json.loads(db.conn().execute("SELECT printers FROM production_orders WHERE id=?", (pa_["id"],)).fetchone()[0]) == [prs_[1]["id"]], "legacy code refs migrated to ids")
ok(po.resolve_printers(["Bambu Lab P1S"], prs_) == [], "plain model name with several printers is not guessed (no first-match)")
ok(po.resolve_printers(["Creality K1C"], prs_) == [2], "plain model name with one printer still resolves")
pb_ = C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 1}], "printers": ["model:Bambu Lab P1S"]}).get_json()
ok(po.resolve_printers(pb_["printers"], prs_) == [0, 1] and pb_["printer_idx"] == [0, 1], "explicit any-of-this-model expands to all printers of the model")
ok(C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 1}], "printers": ["model:Nope"]}).status_code == 400, "unknown model refused")

print("ERRORS", E_)
