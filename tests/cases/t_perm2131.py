# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io
D=T+"/vp"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T+"/v13", D)
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
import app as A
from core import db, store, orders as om
E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+=(not b)
for u,r in (("boss","owner"),("som","production"),("nok","listing")):
    try: db.create_user(u,"secret1" if u=="boss" else "pass123",r,u,"zh")
    except Exception: pass
def cl(u,pw):
    c=A.app.test_client(); c.post("/api/auth/login",json={"username":u,"password":pw}); return c
boss=cl("boss","secret1"); som=cl("som","pass123"); nok=cl("nok","pass123")
pn=nok.get("/api/me").get_json()["user"]["perms"]; ps=som.get("/api/me").get_json()["user"]["perms"]
ok(pn.get("models.change") and pn.get("orders.cancel") and not pn.get("models.delete") and not pn.get("materials.adjust") and not pn.get("cs.delete"), f"listing defaults {pn}")
ok(not ps.get("models.change") and not ps.get("models.delete"), "production defaults")
pid="3DP0001"
lib=boss.get(f"/api/products/{pid}/models").get_json()
stl=open(T+"/cat.stl","rb").read()
r=boss.post(f"/api/products/{pid}/models",data={"files":[(io.BytesIO(stl),"x.stl")]},content_type="multipart/form-data").get_json()
x=[i for i in r["items"] if i["orig_name"]=="x.stl"][0]
r=nok.delete(f"/api/products/{pid}/models/{x['id']}"); ok(r.status_code==403 and "删除 3D 模型" in r.get_json()["error"], f"listing cannot delete lib file {r.status_code}")
r=nok.delete(f"/api/products/{pid}/model"); ok(r.status_code==403, "listing cannot delete model")
r=som.post(f"/api/products/{pid}/models/current",json={"items":[{"id":x["id"],"qty":1}]}); ok(r.status_code==403, f"production cannot change model {r.status_code}")
has=bool((store.load(pid).get("model") or {}).get("file"))
r=som.post(f"/api/products/{pid}/model",data={"file":(io.BytesIO(stl),"y.stl")},content_type="multipart/form-data"); ok(r.status_code==403 or not has, f"production cannot replace model {r.status_code} has={has}")
r=som.post(f"/api/products/{pid}/models/ai-check",json={"items":[]}); ok(r.status_code==400, f"production may run ai-check {r.status_code}")
r=nok.post(f"/api/products/{pid}/models/current",json={"items":[{"id":x["id"],"qty":1}]}); ok(r.status_code==200, "listing can change model")
uid=[u for u in boss.get("/api/users").get_json()["users"] if u["username"]=="nok"][0]["id"]
boss.post(f"/api/users/{uid}",json={"perms":dict(pn, **{"models.delete":True})}); nok=cl("nok","pass123")
lib=nok.get(f"/api/products/{pid}/models").get_json(); other=[i for i in lib["items"] if not i["current"]][0]
r=nok.delete(f"/api/products/{pid}/models/{other['id']}"); ok(r.status_code==200, f"granted delete {r.status_code}")
# materials
r=nok.post("/api/materials",json={"mode":"set","material":"PLA","color":"白","kg":3}); ok(r.status_code==403, f"stocktake denied {r.status_code}")
r=nok.post("/api/materials",json={"mode":"add","material":"PLA","color":"白","kg":1}); ok(r.status_code==200, "add stock ok")
r=boss.post("/api/materials",json={"mode":"set","material":"PLA","color":"白","kg":3}); ok(r.status_code==200, "boss stocktake")
sp=boss.post("/api/spools",json={"material":"PLA","color":"白","net_g":1000,"count":1}).get_json()["codes"][0]
r=nok.post(f"/api/spools/{sp}/delete",json={}); ok(r.status_code==403, f"spool delete denied {r.status_code}")
r=nok.post(f"/api/spools/{sp}/weigh",json={"grams":900}); ok(r.status_code==200, "spool weigh ok")
# orders
oid=om.create_manual({"order_no":"PT-1","items":[{"sku":"3DP0001-WH","name":"x","qty":1,"unit_price":100}]},"boss")["id"] if hasattr(om,"create_manual") else None
if oid is None:
    oid=boss.post("/api/orders/manual",json={"order_no":"PT-1","items":[{"sku":"3DP0001-WH","name":"x","qty":1,"unit_price":100}]}).get_json()["id"]
boss.post(f"/api/users/{uid}",json={"perms":dict(pn, **{"orders.cancel":False})}); nok=cl("nok","pass123")
r=nok.post(f"/api/orders/{oid}",json={"status":"cancelled"}); ok(r.status_code==403, f"cancel denied {r.status_code}")
r=nok.post("/api/orders/batch",json={"ids":[oid],"action":"status","value":"delivery_failed"}); ok(r.status_code==403, "batch reject denied")
r=nok.post(f"/api/orders/{oid}",json={"custom_note":"hi"}); ok(r.status_code==200, "note ok")
r=boss.post(f"/api/orders/{oid}",json={"status":"cancelled"}); ok(r.status_code==200, "boss cancel")
r=nok.post(f"/api/orders/{oid}",json={"status":"cancelled","custom_note":"already"}); ok(r.status_code==200, "unchanged cancelled status ok")
# cs
r=nok.delete("/api/cs/messages/999999"); ok(r.status_code==403, f"cs delete denied {r.status_code}")
r=boss.delete("/api/cs/messages/999999"); ok(r.status_code!=403, f"boss cs delete {r.status_code}")
print("ERRORS",E)
