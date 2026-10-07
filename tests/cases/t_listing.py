# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, json
os.environ["LH_DATA_DIR"]=T+"/vl"; sys.path.insert(0,APP)
import app as A
from core import db
try: db.create_user("boss","secret1","owner","boss","zh")
except Exception: pass
c=A.app.test_client(); c.post("/api/auth/login",json={"username":"boss","password":"secret1"})
lst=c.get("/api/products").get_json(); print("products", [(p["id"], p["lz"]["status"], p["sp"]["status"], p["errors"]) for p in lst][:6])
g=c.post("/api/groups", json={"name":"猫咪系列"}).get_json()["groups"]; gid=g[0]["id"]
ids=[p["id"] for p in lst if p.get("category")][:3]; print("ids", ids)
r=c.post("/api/export", json={"product_ids":ids,"force":True,"batch_name":"","group_id":gid}).get_json()
print("export", r.get("ok"), r.get("errors")[:2] if not r.get("ok") else "", (r.get("batch") or {}).get("name"), (r.get("batch") or {}).get("counts"))
r2=c.post("/api/export/shopee", json={"product_ids":ids[:2],"force":True,"batch_name":"SP 测试批"}).get_json(); print("shopee", r2.get("ok"), (r2.get("batch") or {}).get("counts"), r2.get("error"))
lst=c.get("/api/products").get_json(); print("after", [(p["id"], p["lz"]["status"], p["sp"]["status"], p["groups"]) for p in lst if p["id"] in ids])
b=c.get("/api/listing/batches").get_json()["batches"]; print("batches", [(x["id"],x["platform"],x["name"],x["counts"]) for x in b])
c.post("/api/listing/status", json={"ids":[ids[0]],"platform":"lazada","status":"failed","note":"属性缺失"})
bid=[x for x in b if x["platform"]=="lazada"][0]["id"]
print("batch ok", c.post(f"/api/listing/batches/{bid}", json={"status":"uploaded"}).get_json()["batch"]["counts"])
print("rename", c.post(f"/api/listing/batches/{bid}", json={"name":"第一批猫"}).get_json()["name"])
# save product from client keeps listing
p=c.get(f"/api/products/{ids[1]}").get_json(); p["name_zh"]=p["name_zh"]+"x"
r=c.post(f"/api/products/{ids[1]}", json=p)
print("put", r.status_code)
lst=c.get("/api/products").get_json(); print("keep", [(p["id"], p["lz"]["status"]) for p in lst if p["id"]==ids[1]])
