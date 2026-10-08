# v2.14.1：产品编辑防覆盖、运行日志、诊断包、前端错误上报
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, zipfile, json
D=T+"/v2141"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T+"/v13", D)
import sqlite3; c0=sqlite3.connect(D+"/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
import app as A
from core import store, diag
from modules.link import opsapi
@A.app.get("/api/_boom_test")
def _boom(): raise RuntimeError("测试用的异常")
c=A.app.test_client(); E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+=(not b)
pid="3DP0001"
p=c.get(f"/api/products/{pid}").get_json()
r1=c.post(f"/api/products/{pid}",json=p); p1=r1.get_json(); ok(r1.status_code==200 and p1["edit_rev"]>=1, f"save bumps rev {p1.get('edit_rev')}")
stale=dict(p1); stale["name_zh"]="A 改的"
fresh=dict(p1); fresh["name_zh"]="B 改的"
ok(c.post(f"/api/products/{pid}",json=fresh).status_code==200, "B saves first")
r=c.post(f"/api/products/{pid}",json=stale); ok(r.status_code==409 and r.get_json().get("conflict"), f"A stale save -> 409 {r.get_json().get('error')}")
ok(store.load(pid)["name_zh"]=="B 改的", "B's change kept")
r=c.post(f"/api/products/{pid}?force=1",json=stale); ok(r.status_code==200 and store.load(pid)["name_zh"]=="A 改的", "force overwrite")
cur=c.get(f"/api/products/{pid}").get_json()
q=store.load(pid); store.bump_rev(q,"运营写回"); store.save(q)
r=c.post(f"/api/products/{pid}",json=cur); ok(r.status_code==409 and "运营写回" in r.get_json()["error"], "ops writeback detected")
old={k:v for k,v in cur.items() if k!="edit_rev"}
ok(c.post(f"/api/products/{pid}",json=old).status_code==200, "client without rev (old page) still saves")
# images endpoint result keeps rev consistent
img=c.post(f"/api/products/{pid}/images/reorder",json={"order":[i["raw"] for i in cur.get("images",[])]}).get_json()
ok(c.post(f"/api/products/{pid}",json=img).status_code==200, "save after server-side image op ok")
# logs
r=c.post("/api/client-error",json={"msg":"TypeError: x is undefined","src":"/static/app.js","line":12,"stack":"at f"}); ok(r.status_code==200, "client error accepted")
c.post("/api/client-error",json={"msg":"TypeError: x is undefined","src":"/static/app.js","line":12})
r=c.get("/api/_boom_test"); ok(r.status_code==500 and "已记录" in r.get_json()["error"], "server error logged")
items=c.get("/api/system/errors").get_json()["items"]
ok(any("测试用的异常" in i["text"] for i in items) and sum("x is undefined" in i["text"] for i in items)==1, f"recent errors {len(items)} (client deduped)")
ok(any("Traceback" in i["detail"] for i in items if "测试用的异常" in i["text"]), "traceback kept")
from core import config
config.save_config({"ai_api_key":"sk-SECRET123","printers":[{"name":"P1S","access_code":"12345678","host":"1.2.3.4"}]})
r=c.get("/api/system/diagnostics"); z=zipfile.ZipFile(io.BytesIO(r.data)); names=z.namelist()
cfgtxt=z.read("config_no_secrets.json").decode()
ok("logs/app.log" in names and "system_check.json" in names, f"diag zip {names}")
ok("sk-SECRET123" not in cfgtxt and "12345678" not in cfgtxt and "1.2.3.4" in cfgtxt, "secrets stripped")
# 拓竹 / Orca 项目 3MF（模型在 3D/Objects/ 里）：服务器转 STL 给 3D 预览
import struct
from core import modellib
class _F:
    def __init__(s,p,n): s.p=p; s.filename=n
    def save(s,dst): open(dst,"wb").write(open(s.p,"rb").read())
modellib.upload("3DP0002",[_F(T+"/bambu_project.3mf","project.3mf")],"t")
e=[i for i in modellib.library("3DP0002")["items"] if i["orig_name"]=="project.3mf"][0]
r=c.get(f"/api/products/3DP0002/models/{e['id']}/stl"); n=struct.unpack("<I",r.data[80:84])[0] if r.status_code==200 else 0
ok(r.status_code==200 and n==12, f"library 3mf -> stl triangles {n}")
modellib.make_current("3DP0002",[{"id":e["id"],"qty":1,"orient":"bottom"}],"t")
r=c.get("/api/products/3DP0002/model/stl"); ok(r.status_code==200 and struct.unpack("<I",r.data[80:84])[0]==12, "current model -> stl")
# v2.15.2：3D 预览用精简模型
import gzip as _gz
r=c.get("/api/products/3DP0002/model/preview"); raw=_gz.decompress(r.data) if r.headers.get("Content-Encoding")=="gzip" else r.data
nv,nt,full=struct.unpack("<III",raw[4:16]); ok(raw[:4]==b"3DPV" and nt==12 and full==12, f"preview small model kept {nv},{nt},{full}")
import numpy as np
from core import preview
th=np.linspace(0,np.pi,301); ph=np.linspace(0,2*np.pi,401)
P=np.stack([np.outer(np.sin(th),np.cos(ph)),np.outer(np.sin(th),np.sin(ph)),np.outer(np.cos(th),np.ones_like(ph))],-1)*40
a_,b_,c_,d_=P[:-1,:-1],P[1:,:-1],P[1:,1:],P[:-1,1:]
big=np.concatenate([np.stack([a_,b_,c_],2).reshape(-1,3,3),np.stack([a_,c_,d_],2).reshape(-1,3,3)]).astype(np.float32)
v,i,red=preview.simplify(big,50000); ok(red and len(i)<=55000 and len(i)>20000, f"simplify {len(big)}->{len(i)}")
ok(abs(np.ptp(v,0)-np.ptp(big.reshape(-1,3),0)).max()<2, "shape size kept")
# 品牌空着自动填 No Brand
from core import lazada_template, categories
lib=categories.library(); cat=categories.get(str(lib[0]["id"])); bk=[f["key"] for f in cat["fields"] if f["kind"]=="brandProp"][0]
pp={"id":"X","attributes":{bk:{"value":"","status":"missing"}}}
ok(lazada_template.ensure_brand(pp,cat,{"brand":""}) and pp["attributes"][bk]["value"]=="No Brand", "brand auto No Brand")
print("ERRORS",E)
