# v2.40：全功能测试的中级问题——生产
#  1 退回重打清零   2 已结束的批次不能撤销   3 一台打印机同时只能一盘   4 核对不过的切片文件不算可用
#  5 只用库存发的订单还能改商品
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, json
D = T + "/m_v240prod"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, store, production, orders, print_files
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
config.save_config({"review_enabled": False, "stock_auto_use": False})
sku = next(v["sku"] for it in store.list_products() for v in (store.load(it["id"]).get("variants") or []) if v.get("sku"))
pid = sku.split("-")[0]
jobs_of = lambda oid: [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE order_id=?", (oid,))]
CONF = {"bed_clear": True, "material": True}
manual = lambda no, qty=1: C.post("/api/orders/manual", json={"order_no": no, "items": [{"sku": sku, "qty": qty, "unit_price": 100}]}).get_json()
run_of = lambda jid: db.conn().execute("SELECT run_id FROM jobs WHERE id=?", (jid,)).fetchone()["run_id"]

# ---- 1 退回重打
o = manual("RP1", 2); jid = jobs_of(o["id"])[0]["id"]
production.start_run(jid, 0, 2, [], None, False, "t", CONF); production.finish_run(run_of(jid), "t")
ok(jobs_of(o["id"])[0]["status"] == "post", "printed -> post")
C.post(f"/api/jobs/{jid}", json={"status": "todo"})
j = jobs_of(o["id"])[0]
ok(j["status"] == "todo" and j["qty_done"] == 0, f"send back to reprint resets printed count ({j['qty_done']})")
s0 = production.stock_qty(sku)
production.start_run(jid, 0, 2, [], None, False, "t", CONF); production.finish_run(run_of(jid), "t")
j = jobs_of(o["id"])[0]
ok(j["status"] == "post" and production.stock_qty(sku) == s0, f"reprint goes to the order, not stock ({j['status']}, stock +{production.stock_qty(sku) - s0})")

# ---- 2 已结束的批次不能撤销
rid = db.conn().execute("SELECT MAX(id) FROM print_runs").fetchone()[0]
r = C.post(f"/api/runs/{rid}/cancel")
ok(r.status_code == 400 and jobs_of(o["id"])[0]["status"] == "post", f"finished run cannot be cancelled ({r.status_code})")

# ---- 3 一台打印机同时只能一盘
a, b = manual("PR1"), manual("PR2")
ja, jb = jobs_of(a["id"])[0]["id"], jobs_of(b["id"])[0]["id"]
production.start_run(ja, 1, 1, [], None, False, "t", CONF)
try:
    production.start_run(jb, 1, 1, [], None, False, "t", CONF); second = True
except ValueError as e:
    second = False; msg = str(e)
ok(not second and "还有一盘" in msg, "second plate on same printer refused")
production.start_run(jb, 2, 1, [], None, False, "t", CONF)
ok(run_of(jb) is not None, "other printer still fine")
production.cancel_run(run_of(ja), "t")
ok(run_of(ja) is None, "cancel a printing run still works")

# ---- 4 喷嘴不对的切片文件不算可用
cfg = config.load_config(); cfg["printers"][1]["nozzle"] = 0.4; config.save_config(cfg)
src = os.path.join(T, "v12", "k1.gcode")
def add_file(nozzle):
    tmp = os.path.join(D, f"k1_{nozzle}.gcode"); shutil.copy(src, tmp)
    f = print_files.add(tmp, f"k1_{nozzle}.gcode", pid, "Creality K1 Max", "", 1, "", "", "t")
    from modules.prod import slicecheck
    slicecheck.confirm(f["id"], "Creality K1 Max", "t")          # 测试文件里没有机型信息：老板「确认机型」
    f = print_files.get(f["id"])
    rep = f.get("report") or {}; rep.setdefault("params", {})["nozzle_mm"] = nozzle
    db.conn().execute("UPDATE print_files SET status='reviewed', report=? WHERE id=?", (json.dumps(rep), f["id"])); db.conn().commit()
    return f["id"]
good, bad = add_file(0.4), add_file(0.6)
ids = [x["id"] for x in print_files.candidates(pid, sku, "Creality K1 Max")]
ok(good in ids and bad not in ids, f"0.6 mm file not a candidate for a 0.4 mm printer, 0.4 mm one is ({good}, {bad}, {ids})")

# ---- 5 只用库存发的订单还能改商品
production.stock_add(sku, 5, "t", "t")
config.save_config({"stock_auto_use": True})
o = manual("SK1", 2)
j = jobs_of(o["id"])[0]
ok((j["stock_n"] or 0) == 2, f"order fully reserved from stock ({j['stock_n']}, {j['status']})")
r = C.post(f"/api/orders/{o['id']}/edit", json={"items": [{"sku": sku, "qty": 3, "unit_price": 100}]})
ok(r.status_code == 200 and r.get_json()["items"][0]["qty"] == 3, f"stock-only order can change items ({r.status_code} {r.get_json().get('error', '')})")
print("ERRORS", E_)
