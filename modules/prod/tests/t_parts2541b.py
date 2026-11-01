# v2.54.1 复审修复：用库存占位的任务取消时已打好的零件也记进零件库；零件备注 / 订单日志用真实状态；
# 「使用零件」：零件记为已用、对应盘的 made 增加（不超过还需要的）、凑齐的套数入库 / 转订单。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import json, os, sys, shutil, sqlite3
D = T + "/m_parts2541b"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, production, print_files, orders as orders_mod, chain, inventory
from core.config import load_config, save_config
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pong", "secret123", "production", "Pong")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
PC = A.app.test_client(); PC.post("/api/auth/login", json={"username": "pong", "password": "secret123"})

save_config({"printers": [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "tech": "fdm"},
                          {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "enabled": True, "tech": "fdm"}],
             "stock_auto_use": True})
CONFIRM = {"bed_clear": True, "material": True}

PID = "3DP0002"
p = store.load(PID)
p["variants"] = [{"opt1_zh": "白色", "opt2_zh": "", "sku": "3DP0002-WH", "grams": 60, "hours": 4},
                 {"opt1_zh": "黑色", "opt2_zh": "", "sku": "3DP0002-BK", "grams": 60, "hours": 4}]
p["print_plans"] = {"": {"plates": [
    {"id": "p1", "name": "主体件", "printer": "Bambu Lab P1S", "layer_height": 0.2, "sets": 1, "items": [],
     "slots": [{"slot": 1, "material": "PLA", "colour": ""}, {"slot": 2, "material": "PLA", "colour": "黑色"}],
     "sliced": {"filaments": [{"slot": 1, "grams": 40}, {"slot": 2, "grams": 10}], "hours": 3, "purge_g": 5, "changes": 20}},
    {"id": "p2", "name": "小零件", "printer": "Creality K1C", "layer_height": 0.2, "sets": 2, "items": [],
     "slots": [{"slot": 1, "material": "PLA", "colour": "黑色"}],
     "sliced": {"filaments": [{"slot": 1, "grams": 8}], "hours": 1, "purge_g": 0, "changes": 0}}], "schemes": {}}}
store.save(p)
SKU = "3DP0002-WH"


def mkorder(no, status="to_ship", qty=2):
    orders_mod.upsert([{"platform": "manual", "order_no": no, "status": status, "items": [{"sku": SKU, "qty": qty}]}], source="test")
    chain.order_changed("t"); production.generate("t")
    return db.conn().execute("SELECT id FROM orders WHERE order_no=?", (no,)).fetchone()["id"]


def cancel(no, qty=2):
    orders_mod.upsert([{"platform": "manual", "order_no": no, "status": "cancelled", "items": [{"sku": SKU, "qty": qty}]}], source="test")
    chain.order_changed("t"); production.generate("t")


def job_of(jid):
    return [x for x in production.list_jobs() if x["id"] == jid][0]


# ---------- 2. 订单取消、任务用了库存占位：已打好的零件不丢 ----------
production.stock_add(SKU, 1, "seed", "boss")
oid = mkorder("PT-S", qty=2)
j = production.list_jobs(order_id=oid)[0]
ok(j["stock_n"] == 1 and j["qty_done"] == 1, f"job reserved 1 from stock {j['stock_n']} {j['qty_done']}")
rr = production.start_run(j["id"], 1, send=False, user="boss", confirm=CONFIRM, plate="p2"); production.finish_run(rr["run_id"], "boss")
j = production.list_jobs(order_id=oid)[0]
ok(j["qty_done"] == 1 and j["stock_n"] == 1, "plate 2 printed, only the reserved piece counted")
cancel("PT-S")
ok(not production.list_jobs(order_id=oid), "reserved job deleted after cancel")
ps = production.parts_available(SKU)
ok(len(ps) == 1 and ps[0]["plate_id"] == "p2" and ps[0]["qty"] == 2, f"plate-2 parts parked from the stock-reserved job {ps}")
ok(any("订单取消" in x["action"] and "零件" in x["action"] for x in orders_mod.get_log(oid)), "order log says 订单取消")
ok(production.stock_qty(SKU) == 1, "reservation released, stock untouched")
production.generate("t")
ok(len(production.parts_available(SKU)) == 1, "not parked twice")

# ---------- 4. 备注 / 日志用真实状态 ----------
oh = mkorder("PT-H", qty=1)
jh = production.list_jobs(order_id=oh)[0]
c_ = db.conn()
c_.execute("UPDATE orders SET hold=1 WHERE id=?", (oh,)); c_.commit()
ok(production._why(c_, oh) == "订单挂起", f"hold -> {production._why(c_, oh)}")
c_.execute("UPDATE orders SET hold=0, status='shipped' WHERE id=?", (oh,)); c_.commit()
ok(production._why(c_, oh) == "订单已发货", "shipped -> 订单已发货")
c_.execute("UPDATE orders SET status='completed' WHERE id=?", (oh,)); c_.commit()
ok(production._why(c_, oh) == "订单已完成", "completed")
c_.execute("UPDATE orders SET status='cancelled' WHERE id=?", (oh,)); c_.commit()
ok(production._why(c_, oh) == "订单取消", "cancelled")
c_.execute("UPDATE orders SET status='to_ship' WHERE id=?", (oh,)); c_.commit()
# 真实流程：打好一盘零件后订单被挂起 → 任务删掉，零件备注 / 日志写「订单挂起」
production.stock_add(SKU, -1, "clear", "boss")
oh2 = mkorder("PT-H2", qty=1)
jh2 = production.list_jobs(order_id=oh2)[0]
rr = production.start_run(jh2["id"], 1, send=False, user="boss", confirm=CONFIRM, plate="p2"); production.finish_run(rr["run_id"], "boss")
c_.execute("UPDATE orders SET hold=1 WHERE id=?", (oh2,)); c_.commit()
production.generate("t")
ok(not production.list_jobs(order_id=oh2), "job dropped on hold")
parts = production.parts_available(SKU)
ok(len(parts) == 2 and "订单挂起" in parts[-1]["note"] and "订单取消" not in parts[-1]["note"], f"part note uses real status {parts[-1]['note']}")
ok(any("订单挂起" in x["action"] and "零件" in x["action"] for x in orders_mod.get_log(oh2)), "order log uses real status")
c_.execute("DELETE FROM job_parts WHERE id=?", (parts[-1]["id"],)); c_.commit()

# ---------- 3. 使用零件 ----------
pid_ = production.parts_available(SKU)[0]["id"]
job = production.create_job(PID, SKU, 2, kind="stock", user="boss")
so = PC.get(f"/api/jobs/{job['id']}/send-options?plate=p2&printer=1").get_json()
ok(so["parts"][0]["can_use"] and so["parts"][0]["id"] == pid_, f"option can_use {so['parts'][0]}")
js = open(os.path.join(APP, "modules/prod/ui/prod.js"), encoding="utf-8").read()
ok("data-usepart" in js and "可以用这些零件代替这一盘" in js and "ใช้ชิ้นส่วน" in js, "UI has the use-part button and bilingual text")
ok("对应的盘不用重新打（✓" not in js, "old 'no need to reprint' wording replaced")
ok(PC.post(f"/api/jobs/{job['id']}/use-part", json={"part_id": 99999}).status_code == 400, "unknown part -> 400")
r = PC.post(f"/api/jobs/{job['id']}/use-part", json={"part_id": pid_})
ok(r.status_code == 200 and r.get_json()["used"] == 2, f"use-part api {r.get_json()}")
p_ = db.conn().execute("SELECT * FROM job_parts WHERE id=?", (pid_,)).fetchone()
ok(p_["status"] == "used" and p_["used_job"] == job["id"] and p_["used_at"], "part marked used with job and time")
ok(production.parts_available(SKU) == [], "used part no longer listed")
pl = {x["plate_id"]: x for x in db.conn().execute("SELECT * FROM job_plates WHERE job_id=?", (job["id"],))}
ok(pl["p2"]["made"] == 2 and pl["p1"]["made"] == 0, f"plate 2 made +2 ({pl['p2']['made']})")
ok(PC.post(f"/api/jobs/{job['id']}/use-part", json={"part_id": pid_}).status_code == 400, "can't use twice")
s_before = production.stock_qty(SKU)
ok(job_of(job["id"])["qty_done"] == 0, "no complete set yet")
for _ in range(2):
    rr = production.start_run(job["id"], 0, send=False, user="boss", confirm=CONFIRM, plate="p1"); production.finish_run(rr["run_id"], "boss")
jj = job_of(job["id"])
ok(jj["qty_done"] == 2 and jj["status"] == "done" and production.stock_qty(SKU) == s_before + 2, f"plate 1 x2 + parts -> 2 sets into stock ({jj['qty_done']} {jj['status']})")

# 盘 1 先打齐，再用零件 → 马上凑齐入库；零件有 3、任务只要 1 → 只用 1
c_ = db.conn()
c_.execute("""INSERT INTO job_parts(sku, product_id, plate_id, plate_no, plate_total, name, color, qty, status, created_at, created_by)
   VALUES(?,?,?,?,?,?,?,?,'avail',?,?)""", (SKU, PID, "p2", 2, 2, "小零件", "白色", 3, 1.0, "t")); c_.commit()
job2 = production.create_job(PID, SKU, 1, kind="stock", user="boss")
rr = production.start_run(job2["id"], 0, send=False, user="boss", confirm=CONFIRM, plate="p1"); production.finish_run(rr["run_id"], "boss")
s_before = production.stock_qty(SKU)
part = production.parts_available(SKU)[0]
r = production.use_part(job2["id"], part["id"], user="pong")
ok(r["used"] == 1 and r["left"] == 2, f"only needed units used {r}")
jj = job_of(job2["id"])
ok(jj["qty_done"] == 1 and jj["status"] == "done" and production.stock_qty(SKU) == s_before + 1, "set completed by the part -> stock +1")
left = production.parts_available(SKU)
ok(len(left) == 1 and left[0]["qty"] == 2, f"remaining parts stay available {left}")
used = db.conn().execute("SELECT * FROM job_parts WHERE status='used' AND used_job=?", (job2["id"],)).fetchone()
ok(used and used["qty"] == 1, "used portion recorded as its own row")
try:
    production.use_part(job2["id"], left[0]["id"], user="pong"); ok(False, "finished job can't take parts")
except ValueError:
    ok(True, "finished job can't take parts")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
