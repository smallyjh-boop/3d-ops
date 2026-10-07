# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D=T+"/vsp"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
for x in ("products","config.json","sequence.json"):
    src=T+"/v13/"+x; (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, D+"/"+x)
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
# 先用旧方式录库存，再看迁移
from core import db, materials
materials.init.__globals__  # noqa
c=db.conn(); c.executescript(materials.SCHEMA)
c.execute("INSERT INTO inventory(material,color,kg,updated_at) VALUES('PLA','白色',2.35,0)"); c.commit()
import app as A
cl=A.app.test_client(); E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+=(not b)
def kg(m,c_): return db.conn().execute("SELECT kg FROM inventory WHERE material=? AND color=?",(m,c_)).fetchone()["kg"]
sp=materials.spools("PLA","白色")
ok(len(sp)==3 and sum(s["status"]=="sealed" for s in sp)==2 and abs(kg("PLA","白色")-2.35)<1e-6, f"migrated {[ (s['code'],s['status'],s['remaining_g']) for s in sp]}")
r=cl.post("/api/spools",json={"material":"PLA","color":"黑色","count":2,"net_g":1000,"brand":"Bambu"}).get_json()
ok(len(r["codes"])==2 and abs(kg("PLA","黑色")-2.0)<1e-6, f"receive {r['codes']}")
prs=A.load_config()["printers"]; code0=prs[0]["code"] or "#1"
s1=r["codes"][0]
x=cl.post(f"/api/spools/{s1}/load",json={"printer":code0,"slot":"A1"}).get_json(); ok(x["spool"]["status"]=="loaded", "load")
materials.consume("PLA","黑色",300,"打印完成 test","t",printer=0)
x=materials.spool_get(s1); ok(abs(x["remaining_g"]-700)<1e-6 and abs(kg("PLA","黑色")-1.7)<1e-6, f"consume from loaded {x['remaining_g']}")
materials.consume("PLA","黑色",900,"big","t",printer=0)
a=materials.spool_get(s1); b=materials.spool_get(r["codes"][1])
ok(a["status"]=="empty" and b["status"]=="loaded" and abs(b["remaining_g"]-800)<1e-6 and abs(kg("PLA","黑色")-0.8)<1e-6, f"rollover {a['status']} {b['status']} {b['remaining_g']}")
materials.consume("PLA","黑色",1000,"over","t",printer=0)
ok(abs(kg("PLA","黑色")+0.2)<1e-6, f"negative tracked {kg('PLA','黑色')}")
materials.receive("PLA","黑色",1,1000)
ok(abs(kg("PLA","黑色")-0.8)<1e-6, f"negative settled {kg('PLA','黑色')}")
x=cl.post(f"/api/spools/{b['code']}/weigh",json={"grams":0}).get_json()
x=cl.post(f"/api/spools/{b['code']}/empty",json={}).get_json(); ok(x["spool"]["status"]=="empty","empty")
materials.set_stock("PLA","黑色",1.5,"t")
ok(abs(kg("PLA","黑色")-1.5)<1e-6, f"set_stock {kg('PLA','黑色')}")
materials.add_stock("PLA","红色",1.5,"t")
ok(len(materials.spools("PLA","红色"))==2 and abs(kg("PLA","红色")-1.5)<1e-6, "add_stock split")
# alerts: loaded low
w=materials.spools("PLA","白色",status="sealed")[0]
cl.post(f"/api/spools/{w['code']}/load",json={"printer":code0,"slot":"A2"})
cl.post(f"/api/spools/{w['code']}/weigh",json={"grams":50})
al=materials.alerts(); print("   alerts:", [a["text"] for a in al][:6])
ok(any("只剩 50 g" in a["text"] for a in al), "low loaded alert")
ok(cl.get("/print/spools?ids="+w["code"]).status_code==200, "label print")
ok(cl.post(f"/api/spools/{w['code']}/delete",json={}).status_code==400, "cannot delete opened")
d=cl.get("/api/dashboard").get_json(); ok("material_alerts" in d, "dashboard alerts")
pl=cl.get("/api/materials").get_json(); ok(all("spools" in r for r in pl["rows"]), "plan spools")
print("ERRORS",E)
