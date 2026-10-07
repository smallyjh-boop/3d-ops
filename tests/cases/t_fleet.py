# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, json
os.environ["LH_DATA_DIR"]=T+"/vf"; sys.path.insert(0,APP)
import app as A
from core import db, config, production, fleet
try: db.create_user("boss","secret1","owner","boss","zh")
except Exception: pass
c=A.app.test_client(); c.post("/api/auth/login",json={"username":"boss","password":"secret1"})
cfg=config.load_config(); print("codes", [(p["code"],p["name"],p["enabled"]) for p in cfg["printers"]])
print("file persisted", [p.get("code") for p in json.load(open(T+"/vf/config.json"))["printers"]])
# conn on K1M-01
pr=cfg["printers"]; pr[1]["conn"]={"type":"none","ip":"1.2.3.4"}; config.save_config({"printers":pr})
# jobs
d=db.conn()
for i,(pid,sku) in enumerate([("3DP0001","3DP0001-WH"),("3DP0002","3DP0002-BK")]):
    production.create_job(pid, sku, 3, "stock")
production.schedule()
print("jobs", [(j["id"], j["printer"], j["printer_code"]) for j in production.list_jobs(("todo",))])
d.execute("UPDATE jobs SET printer=2, pin=1 WHERE id=1"); d.commit()
# new list: delete P1S-01 (idx0), move K1C first, add 2 P1S, disable K1M
new=[dict(pr[2]), dict(pr[1], enabled=False), {"name":"Bambu Lab P1S","g_per_h":22}, {"name":"Bambu Lab P1S","g_per_h":22}, {"name":"Bambu Lab A1 mini","g_per_h":15}]
r=c.post("/api/config", json={"printers":new}); j=r.get_json()
print("save", r.status_code, j.get("error"), [(p["code"],p["name"],p["enabled"],p.get("conn",{}).get("ip")) for p in j["config"]["printers"]])
print("jobs after", [(x["id"], x["printer"], x["printer_code"], x["pin"]) for x in production.list_jobs(("todo",))])
# dup code
r=c.post("/api/config", json={"printers":[{"code":"X-1","name":"A"},{"code":"x-1","name":"B"}]}); print("dup", r.status_code, r.get_json().get("error"))
print("models", len(c.get("/api/printer-models").get_json()["models"]))
rg=c.get("/api/products/3DP0001/recipe").get_json(); print("recipe printers", rg.get("printers"), rg.get("printer_idx"))
b=c.get("/api/production").get_json(); print("lanes", [(l["code"], l["enabled"], len(l["queue"])) for l in b["lanes"]])
