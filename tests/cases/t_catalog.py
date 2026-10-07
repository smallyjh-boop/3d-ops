# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, threading, json, io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
D=T+"/vcat"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
for x in ("products","config.json","sequence.json","templates_lazada"):
    src=T+"/v13/"+x
    if os.path.exists(src): (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, D+"/"+x)
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
from PIL import Image
buf=io.BytesIO(); Image.new("RGB",(800,800),(200,100,50)).save(buf,"JPEG"); JPG=buf.getvalue()
STL=open(T+"/cat.stl","rb").read()
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_GET(self):
        if self.path.startswith("/api/v1/ping"):
            b=b'{"ok": true, "version": "1.8.0"}'; self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(b); return
        if self.headers.get("Authorization")!="Bearer CURKEY":
            self.send_response(401); self.end_headers(); return
        if self.path.startswith("/api/v1/catalog/7/images/"): body,ct=JPG,"image/jpeg"
        elif self.path.startswith("/api/v1/catalog/30/files/") or self.path.startswith("/api/v1/catalog/7/files/") or self.path.startswith("/api/v1/catalog/20/files/"): body,ct=STL,"application/octet-stream"
        elif self.path.startswith("/api/v1/catalog/20/images/"): body,ct=JPG,"image/jpeg"
        elif self.path.startswith("/api/v1/catalog?") or self.path=="/api/v1/catalog": body,ct=b'{"ok":true,"items":[]}',"application/json"
        else: self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type",ct); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
srv=ThreadingHTTPServer(("127.0.0.1",18799),H); threading.Thread(target=srv.serve_forever,daemon=True).start()
import app as A
from core import integrations, config
config.save_config({"curator_base_url":"http://127.0.0.1:18799","curator_api_key":"CURKEY"})
cat_key=integrations.create_key("选品工具-建产品","catalog"); read_key=integrations.create_key("选品工具-NAS","read")
c=A.app.test_client(); E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+=(not b)
HC={"Authorization":"Bearer "+cat_key}; HR={"Authorization":"Bearer "+read_key}
r=c.get("/api/v1/categories",headers=HC).get_json(); cats=r["categories"]; ok(r["ok"] and len(cats)>0, f"categories {len(cats)} e.g. {cats[0]['name']}")
ok(c.get("/api/v1/categories",headers=HR).status_code==200, "read key categories")
ok(c.get("/api/v1/orders",headers=HC).status_code==403, "catalog key cannot read orders")
ok(c.post("/api/v1/catalog/products",headers=HR,json={}).status_code==403, "read key cannot create")
body={"source":"3d-curator","source_id":7,"source_version":"1.4.0","name_zh":"猫咪耳机架","name_th":"ที่แขวนหูฟังแมว",
 "description_zh":"可爱","category":cats[0]["name"],"tags":["猫","耳机"],"material":"PETG","print_minutes":95,"filament_grams":42.5,
 "images":[{"position":2,"is_cover":False,"url":"/api/v1/catalog/7/images/2"},{"position":1,"is_cover":True,"url":"http://127.0.0.1:18799/api/v1/catalog/7/images/1"}],
 "files":[{"name":"cat.stl","bytes":len(STL),"kind":"model","url":"/api/v1/catalog/7/files/1"},{"name":"bad.zip","url":"/api/v1/catalog/9/files/x"}],
 "source_url":"https://makerworld.com/x","platform":"MakerWorld","author":"bob","license_name":"Standard Digital File License","license_verified":True,
 "reference_price":{"suggested":199,"target":179},"updated_at":1791200000}
r=c.post("/api/v1/catalog/products",headers=HC,json=body); j=r.get_json()
ok(r.status_code==201 and j["created"] and j["product_code"].startswith("3DP") and j["images"]==2 and j["files"]==1 and len(j["warnings"])==1, f"create {r.status_code} {j}")
pid=j["product_code"]
from core import store
p=store.load(pid)
ok(p["material"]=="PETG" and p["variants"][0]["grams"]==42.5 and abs(p["variants"][0]["hours"]-1.58)<0.01 and p.get("model") and p["draft"], "product fields + model")
ok(p["copy"]["title_th"]=="ที่แขวนหูฟังแมว" and p["category"]["id"]==cats[0]["id"], "copy & category")
r2=c.post("/api/v1/catalog/products",headers=HC,json=body).get_json(); ok(r2["created"] is False and r2["product_code"]==pid, "idempotent")
bad=dict(body,source_id=8,category="不存在的类目"); r=c.post("/api/v1/catalog/products",headers=HC,json=bad); ok(r.get_json().get("code")=="invalid_category", "invalid_category")
bad=dict(body,source_id=9,name_zh="",name_th=""); ok(c.post("/api/v1/catalog/products",headers=HC,json=bad).get_json().get("code")=="title_required","title_required")
bad=dict(body,source_id=10,license_verified=False); ok(c.post("/api/v1/catalog/products",headers=HC,json=bad).get_json().get("code")=="license_not_verified","license check")
config.save_config({"curator_api_key":"WRONG"})
before=len(store.list_products())
bad=dict(body,source_id=11); r=c.post("/api/v1/catalog/products",headers=HC,json=bad); ok(r.get_json().get("code")=="image_download_failed" and len(store.list_products())==before, f"download fail rollback {r.get_json().get('error')}")
s=c.get("/api/v1/skus",headers=HR).get_json()["skus"]; x=[k for k in s if k["product_id"]==pid]
ok(x and x[0]["product_code"]==pid and x[0]["draft"] and x[0]["source"]["source_id"]=="7", f"skus has product_code/draft {x[0] if x else None}")
# UI save with color clears draft
bc=A.app.test_client(); p=store.load(pid); p["variants"][0]["opt1_zh"]="白色"
bc.post(f"/api/products/{pid}",json=p); p=store.load(pid); ok(not p["draft"] and p["source"] and p["variants"][0]["sku"].endswith("-WH"), f"draft cleared {p['variants'][0]['sku']}")
ok(bc.get(f"/files/{pid}/source_files/cat.stl").status_code==200, "source file download")
old=dict(body,source_id=12); old.pop("name_zh"); old.pop("name_th"); old["title_zh"]="旧字段"; config.save_config({"curator_api_key":"CURKEY"})
r=c.post("/api/v1/catalog/products",headers=HC,json=old).get_json(); ok(r.get("created") and store.load(r["product_code"])["name_zh"]=="旧字段", "old title_zh still accepted")
config.save_config({"curator_api_key":"CURKEY"})
mv={"source":"3d-curator","source_id":20,"name_zh":"多规格花盆","name_th":"กระถาง","category":cats[0]["name"],"material":"PLA",
 "print_minutes":95,"filament_grams":30,"license_name":"x","license_verified":True,
 "images":[{"position":1,"is_cover":True,"url":"/api/v1/catalog/20/images/1"}],
 "files":[{"name":"small.stl","url":"/api/v1/catalog/20/files/4"},{"name":"large.stl","url":"/api/v1/catalog/20/files/5"}],
 "variants":[{"position":2,"name_zh":"大号","name_th":"ใหญ่","print_minutes":260,"filament_grams":88,"files":[{"name":"large.stl","url":"/api/v1/catalog/20/files/5"}]},
             {"position":1,"name_zh":"小号","name_th":"เล็ก","print_minutes":0,"filament_grams":0,"files":[{"name":"small.stl","url":"/api/v1/catalog/20/files/4"}]}]}
r=c.post("/api/v1/catalog/products",headers=HC,json=mv).get_json()
p=store.load(r["product_code"]); vs=p["variants"]
ok(r["created"] and len(r["skus"])==2 and r["files"]==2 and [v["opt2_zh"] for v in vs]==["小号","大号"] and vs[0]["grams"]==0 and vs[1]["grams"]==88 and vs[1]["model_file"]=="large.stl", f"multi-spec {r['skus']} {[(v['opt2_zh'],v['grams'],v['hours'],v.get('model_file')) for v in vs]}")
ok(p["copy"]["options_th"]=={"小号":"เล็ก","大号":"ใหญ่"} and p.get("model"), "spec thai + model")
s2=[k for k in c.get("/api/v1/skus",headers=HR).get_json()["skus"] if k["product_id"]==p["id"]]; ok({k["variant"] for k in s2}=={"小号","大号"}, "skus variant field")
bad=dict(mv,source_id=21,variants=[{"name_zh":"a"},{"name_zh":"a"}]); ok(c.post("/api/v1/catalog/products",headers=HC,json=bad).get_json().get("code")=="invalid_field","dup spec name")
zero=dict(body,source_id=22,print_minutes=0,filament_grams=0); ok(c.post("/api/v1/catalog/products",headers=HC,json=zero).status_code==201, "zero time/grams ok")
bc=A.app.test_client()
t=bc.post("/api/curator/test",json={}).get_json(); ok(t["ok"] and t["version"]=="1.8.0", f"curator test {t['steps']}")
config.save_config({"curator_api_key":"WRONG"}); t=bc.post("/api/curator/test",json={}).get_json(); ok(not t["ok"] and "密钥不对" in t["steps"][-1]["text"], "wrong key detected")
t=bc.post("/api/curator/test",json={"base_url":"http://127.0.0.1:1"}).get_json(); ok(not t["ok"] and "连不上" in t["steps"][0]["text"], "bad url detected")
st=bc.post("/api/curator",json={"base_url":"127.0.0.1:18799/","api_key":"******"}).get_json(); ok(st["base_url"]=="http://127.0.0.1:18799" and st["key_set"] and len(st["recent"])>=3, f"save/status {st['base_url']}")
# ---- 补传模型文件 ----
config.save_config({"curator_api_key":"CURKEY"})
nofile=dict(body,source_id=30,files=[]); r=c.post("/api/v1/catalog/products",headers=HC,json=nofile).get_json(); code30=r["product_code"]
ok(not store.load(code30).get("model"), "created without model")
up={"source":"3d-curator","source_id":30,"product_code":code30,"files":[{"name":"part.stl","bytes":len(STL),"kind":"stl","variant":"","url":"/api/v1/catalog/30/files/45"},{"name":"bad.stl","url":"/api/v1/catalog/99/files/1"}]}
r=c.post(f"/api/v1/catalog/products/{code30}/files",headers=HC,json=up); j=r.get_json()
ok(r.status_code==200 and j["added"]==1 and len(j["warnings"])==1 and store.load(code30).get("model"), f"add files {j}")
r=c.post(f"/api/v1/catalog/products/{code30}/files",headers=HC,json=up).get_json(); ok(r["added"]==0 and r["skipped"]==1, f"dedupe {r}")
same=dict(up,files=[{"name":"part.stl","bytes":len(STL),"url":"/api/v1/catalog/30/files/46"}]); r=c.post(f"/api/v1/catalog/products/{code30}/files",headers=HC,json=same).get_json(); ok(r["skipped"]==1,"dedupe name+bytes")
ok(c.post("/api/v1/catalog/products/3DP9999/files",headers=HC,json=up).status_code==404, "not_found 404")
wrong=dict(up,source_id=31); ok(c.post(f"/api/v1/catalog/products/{code30}/files",headers=HC,json=wrong).get_json().get("code")=="invalid_field", "source mismatch")
ok(c.post(f"/api/v1/catalog/products/{code30}/files",headers=HR,json=up).status_code==403, "read key cannot upload")
# variant attach on multi-spec product (code from source 20)
pm=[x for x in store.list_products() if (store.load(x["id"]).get("source") or {}).get("source_id")=="20"][0]["id"]
pp=store.load(pm); pp["variants"][1]["model_file"]=None; store.save(pp)
v={"source":"3d-curator","source_id":20,"files":[{"name":"big2.stl","url":"/api/v1/catalog/20/files/9","variant":"大号"},{"name":"x.stl","url":"/api/v1/catalog/20/files/10","variant":"不存在"}]}
r=c.post(f"/api/v1/catalog/products/{pm}/files",headers=HC,json=v).get_json(); pp=store.load(pm)
ok(r["added"]==2 and [x.get("model_file") for x in pp["variants"] if x["opt2_zh"]=="大号"][0]=="big2.stl" and any("不存在" in w for w in r["warnings"]), f"variant attach {r}")
# manual product without source gets linked
man="3DP0002"; mp=store.load(man); mp.pop("source",None); store.save(mp)
r=c.post(f"/api/v1/catalog/products/{man}/files",headers=HC,json={"source":"3d-curator","source_id":"77","files":[{"name":"m.stl","url":"/api/v1/catalog/7/files/1"}]}).get_json()
ok(r.get("added")==1 and store.load(man)["source"]["source_id"]=="77", f"manual product linked {r}")
print("ERRORS",E); srv.shutdown()
