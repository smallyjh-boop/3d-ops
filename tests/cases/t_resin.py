# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, struct, json, io
os.environ["LH_DATA_DIR"]=T+"/vr"; sys.path.insert(0,APP)
import app as A
from core import db, config, production, store, pricing, resinfile, fleet
try: db.create_user("boss","secret1","owner","boss","zh")
except Exception: pass
c=A.app.test_client(); c.post("/api/auth/login",json={"username":"boss","password":"secret1"})
# synthetic pm5s
def mk(path):
    hdr=struct.pack("<10f3I2f3I", 0.017, 0.05, 2.0, 0.5, 30, 5, 6, 4, 6, 12.5, 1, 11520, 5120, 0, 0, 0, 0, 2*3600+1200)
    head=b"ANYCUBIC"+b"\0"*4+struct.pack("<7I",517,8,64,0,0,0,64+16+len(hdr))
    head=head.ljust(64,b"\0")
    sec=b"HEADER".ljust(12,b"\0")+struct.pack("<I",len(hdr))+hdr
    ld=b"LAYERDEF".ljust(12,b"\0")+struct.pack("<I",4)+struct.pack("<I",800)
    open(path,"wb").write(head+sec+ld)
mk(T+"/3DP0003_test.pm5s"); print("parse", resinfile.parse(T+"/3DP0003_test.pm5s"))
open(T+"/3DP0003_x.ctb","wb").write(b"\x00"*100)
# printers: add M5s
cfg=config.load_config(); prs=cfg["printers"]+[{"name":"Anycubic Photon Mono M5s","g_per_h":0}]
r=c.post("/api/config", json={"printers":prs, "resin_thb_per_kg": 900}); print("save", r.status_code, [(p["code"],p["tech"]) for p in r.get_json()["config"]["printers"]])
# product 3 -> resin
p=store.load("3DP0003"); p["material"]="RESIN"; store.save(p)
for f in [T+"/3DP0003_test.pm5s",T+"/3DP0003_x.ctb"]:
    r=c.post("/api/print-files", data={"files":[(open(f,"rb"), os.path.basename(f))], "per_plate":"6"} if "pm5s" in f else {"files":[(open(f,"rb"), os.path.basename(f))], "hours":"1.5","ml":"20"}, content_type="multipart/form-data")
    j=r.get_json(); print("upload", r.status_code, j.get("error"), j.get("printer"), j.get("per_plate"), j.get("hours"), j.get("grams"), j.get("kind"), j.get("detected"))
print("toolpath", c.get(f"/api/print-files/{j['id']}/toolpath").get_json())
sku=p["variants"][0]["sku"] if p.get("variants") else ""
production.create_job("3DP0003", sku, 10, "stock")
production.create_job("3DP0001", "3DP0001-WH", 2, "stock")
for x in production.list_jobs(("todo",)): print("job", x["product_id"], x["material"], x["tech"], x["printer_code"], round((x["planned_end"] or 0)-(x["planned_start"] or 0)))
v={"grams":10,"hours":1}
print("cost pla", pricing.variant_cost(config.load_config(),10,1)["material"], "resin", pricing.variant_cost(config.load_config(),10,1,"RESIN")["material"])
print("sys", [ (i["name"],i["status"],i["detail"][:40]) for i in c.get("/api/system/check").get_json()["items"] if "M5S" in i["name"] or "字体" in i["name"]])
idx=[i for i,p in enumerate(config.load_config()["printers"]) if p["tech"]=="resin"][0]
from core import slicer
try: slicer.resolve_profiles(config.load_config(), idx)
except Exception as e: print("slice resin:", e)
jid=[x for x in production.list_jobs(("todo",)) if x["product_id"]=="3DP0001"][0]["id"]
print("matcheck", production.material_check(dict(production.list_jobs(("todo",))[0]) | {"product_id":"3DP0001","material":"PLA"}, None, idx)["error"])
