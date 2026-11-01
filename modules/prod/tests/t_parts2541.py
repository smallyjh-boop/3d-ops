# v2.54.1：订单取消时多盘任务已打好的零件进零件库（不是成品库存），以后同 SKU 的任务开始时列出来。
# 沿用 v2.52 的一件成品要打几盘的打印方案（盘 1 主体件、盘 2 小零件）→ 生产每一盘都排单、各用自己的文件 / 打印机要求 / 用料，
# 凑齐一整套才进成品库存（qty_done），某一盘失败只有这一盘回到队列；一盘的产品照旧
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import json, os, sys, shutil, sqlite3
D = T + "/m_parts2541"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
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

# ---------- 打印机：P1S（有 AMS，#0）+ K1C（没有，#1） ----------
save_config({"printers": [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "tech": "fdm"},
                          {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "enabled": True, "tech": "fdm"}],
             "stock_auto_use": False})
CONFIRM = {"bed_clear": True, "material": True}

# ---------- 产品：两盘的方案（盘 1 主体件 两色 一盘 1 套；盘 2 小零件 单色黑 一盘 2 套） ----------
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
from core import modules
pp = modules.public("model")
jp = pp.job_plates(PID, "3DP0002-WH", "白色")
ok(len(jp) == 2 and jp[0]["multicolor"] and not jp[1]["multicolor"] and jp[1]["sets"] == 2, f"job_plates {[(x['plate_id'], x['sets'], x['multicolor']) for x in jp]}")
ok(abs(jp[0]["grams"] - 55) < 0.2 and jp[1]["grams"] == 8 and jp[1]["colours"][0]["colour"] == "黑色", f"plate grams incl. purge {jp[0]['grams']} {jp[1]['colours']}")
ok(production.plate_text(jp[0]) == "盘 1/2 · 主体件" and "盘" not in production.plate_text(jp[0], "th"), "plate label zh / th")
from core import modules
pp = modules.public('model')

orders_mod.upsert([{"platform": "manual", "order_no": "PT-1", "status": "to_ship", "items": [{"sku": "3DP0002-WH", "qty": 2}]}], source="test")
chain.order_changed("t"); production.generate("t")
oid = db.conn().execute("SELECT id FROM orders WHERE order_no='PT-1'").fetchone()["id"]
OJ = production.list_jobs(order_id=oid)[0]["id"]
s0 = production.stock_qty("3DP0002-WH"); sell0 = production.sellable_qty("3DP0002-WH")
rr = production.start_run(OJ, 1, send=False, user="boss", confirm=CONFIRM, plate="p2"); production.finish_run(rr["run_id"], "boss")   # 盘 2 一盘 2 套
oj = production.list_jobs(order_id=oid)[0]
ok(oj["qty_done"] == 0 and oj["status"] == "todo", "only plate 2 printed: no complete set")
orders_mod.upsert([{"platform": "manual", "order_no": "PT-1", "status": "cancelled", "items": [{"sku": "3DP0002-WH", "qty": 2}]}], source="test")
chain.order_changed("t"); production.generate("t")
ok(not production.list_jobs(order_id=oid), "job dropped after cancel")
ps = production.parts_available("3DP0002-WH")
ok(len(ps) == 1 and ps[0]["plate_id"] == "p2" and ps[0]["qty"] == 2 and ps[0]["plate_no"] == 2, f"plate-2 parts recorded {ps}")
ok(production.part_label(ps[0]) == "3DP0002-WH 盘 2 零件", "part label")
ok(production.stock_qty("3DP0002-WH") == s0 and production.sellable_qty("3DP0002-WH") == sell0, "sellable / stock unchanged")
ok(not db.conn().execute("SELECT 1 FROM inv_items WHERE category='goods' AND name_zh LIKE '%零件%'").fetchone(), "no goods item for parts")
production.generate("t")
ok(len(production.parts_available("3DP0002-WH")) == 1, "parts not recorded twice")
ok(any("零件" in x["action"] for x in orders_mod.get_log(oid)), "order log mentions parts")

# ---------- 新任务的开始对话框列出可用零件 ----------
job = production.create_job(PID, "3DP0002-WH", 2, kind="stock", user="boss")
so = PC.get(f"/api/jobs/{job['id']}/send-options?plate=p2&printer=1").get_json()
ok(len(so.get("parts") or []) == 1 and so["parts"][0]["label"] == "3DP0002-WH 盘 2 零件" and so["parts"][0]["same_plate"] and so["parts"][0]["qty"] == 2, f"start dialog lists parts {so.get('parts')}")
so1 = PC.get(f"/api/jobs/{job['id']}/send-options?plate=p1&printer=0").get_json()
ok(len(so1.get("parts") or []) == 1 and not so1["parts"][0]["same_plate"], "other plate: listed but not same plate")
ok(production.parts_available("3DP0002-BK") == [], "other SKU: none")
js = open(os.path.join(APP, "modules/prod/ui/prod.js"), encoding="utf-8").read()
ok("o.parts" in js, "start dialog UI shows parts")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
