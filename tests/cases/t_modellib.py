# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, zipfile
import numpy as np
D=T+"/vml"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
for x in ("products","config.json","sequence.json"):
    src=T+"/v13/"+x; (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, D+"/"+x)
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
def cube(sx,sy,sz,ox=0):
    v=[(ox,0,0),(ox+sx,0,0),(ox+sx,sy,0),(ox,sy,0),(ox,0,sz),(ox+sx,0,sz),(ox+sx,sy,sz),(ox,sy,sz)]
    t=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
    return "<mesh><vertices>"+"".join(f'<vertex x="{a}" y="{b}" z="{c}"/>' for a,b,c in v)+"</vertices><triangles>"+"".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a,b,c in t)+"</triangles></mesh>"
xml='<?xml version="1.0"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources>'+f'<object id="1" name="桌面" type="model">{cube(120,80,5)}</object><object id="2" name="桌腿" type="model">{cube(10,10,60,200)}</object>'+'</resources><build><item objectid="1"/><item objectid="2"/></build></model>'
buf=io.BytesIO(); z=zipfile.ZipFile(buf,"w"); z.writestr("3D/3dmodel.model",xml); z.writestr("Metadata/plate_1.png",b"\x89PNG\r\n\x1a\nfake"); z.close(); KIT=buf.getvalue()
import app as A
from core import store, modellib
c=A.app.test_client(); E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+=(not b)
pid="3DP0001"
lib=c.get(f"/api/products/{pid}/models").get_json(); ok("items" in lib, f"library {len(lib['items'])} items, current linked={any(i['current'] for i in lib['items'])}")
r=c.post(f"/api/products/{pid}/models",data={"files":[(io.BytesIO(KIT),"桌子套件.3mf"),(open(T+"/cat.stl","rb"),"cat.stl"),(io.BytesIO(b"step"),"part.step")]},content_type="multipart/form-data").get_json()
items={i["orig_name"]:i for i in r["items"]}
kit=items["桌子套件.3mf"]; info=kit["info"]
ok(info["ok"] and len(info["parts"])==2 and info["parts"][0]["name"]=="桌面" and info["parts"][1]["size"]==[10.0,10.0,60.0], f"kit parts {[ (p['name'],p['size']) for p in info.get('parts',[])]}")
ok(info.get("thumb") and c.get(f"/api/products/{pid}/models/{kit['id']}/thumb").status_code==200, "thumb")
ok(not items["part.step"]["info"]["ok"] and "STEP" in items["part.step"]["info"]["reason"], "step not analyzable")
ok("fit" in info and isinstance(info["fit"]["ok"], list), f"fit {info['fit']}")
cat=items["cat.stl"]
r=c.post(f"/api/products/{pid}/models/current",json={"items":[{"id":cat["id"],"qty":1}]}).get_json()
ok(any(i["current"] and i["id"]==cat["id"] for i in r["items"]) and r["merged"] is False, "set single current")
# kit: 1 top + 4 legs
r=c.post(f"/api/products/{pid}/models/current",json={"items":[{"id":kit["id"],"part":0,"qty":1},{"id":kit["id"],"part":1,"qty":4}],"name":"桌子一套"}).get_json()
cur=[i for i in r["items"] if i["current"]][0]
ok(r["merged"] and cur["origin"]=="merged" and len(cur["parts_of"])==2 and cur["info"]["ok"], f"merged {cur['orig_name']} size {cur['info'].get('size')}")
s=cur["info"]["size"]; ok(s[2]==60.0 and s[0]<=modellib.LAYOUT_WIDTH+1, f"layout size {s}")
p=store.load(pid); ok(p["model"]["lib_id"]==cur["id"] and p["model"]["metrics"]["size"]==s, "product model = merged")
ok(c.delete(f"/api/products/{pid}/models/{cur['id']}").status_code==400, "cannot delete current")
r=c.delete(f"/api/products/{pid}/models/{items['part.step']['id']}").get_json(); ok(all(i["orig_name"]!="part.step" for i in r["items"]), "delete")
# spec mapping on a multi-spec product
p=store.load(pid); p["variation2_name_zh"]="规格"; base=dict(p["variants"][0]); p["variants"]=[dict(base,opt2_zh="小号"),dict(base,opt2_zh="大号")]; store.save(p)
r=c.post(f"/api/products/{pid}/models/{cat['id']}/spec",json={"spec":"大号"}).get_json()
ok([i for i in r["items"] if i["id"]==cat["id"]][0]["spec_models"]==["大号"], "spec mapping")
ok(c.post(f"/api/products/{pid}/models/{cat['id']}/spec",json={"spec":"不存在"}).status_code==400, "bad spec")
z=c.get(f"/api/files/zip?ids={pid}"); names=zipfile.ZipFile(io.BytesIO(z.data)).namelist(); ok(any("模型库/" in n for n in names), f"zip has library {len([n for n in names if '模型库' in n])}")
ov=c.get("/api/files").get_json(); row=[x for x in ov["rows"] if x["id"]==pid][0]; ok(row["lib_count"]>=3, f"overview lib_count {row['lib_count']}")
ok(c.get(f"/api/products/{pid}/models/{kit['id']}/download?inline=1").status_code==200, "download")
# v2.13.1 摆放方向 / 空打风险 / AI 检查
import json as _j
from core import ai_copy
lib=c.get(f"/api/products/{pid}/models").get_json(); kit=[i for i in lib["items"] if i["orig_name"]=="桌子套件.3mf"][0]
leg=kit["info"]["parts"][1]
ok(len(leg["orients"])==6 and leg["best"] in [o["key"] for o in leg["orients"]], f"leg orients best={leg['best']}")
bo={o["key"]:o for o in leg["orients"]}
ok(bo["bottom"]["level"] in ("warn","bad") and any("细高" in r["text"] for r in bo["bottom"]["risks"]), f"leg upright risky {bo['bottom']['risks']}")
ok(bo[leg["best"]]["level"]=="ok" and leg["best"]!="bottom", f"best lying {leg['best']}")
cat=[i for i in lib["items"] if i["orig_name"]=="cat.stl"][0]
ok(cat["info"].get("thumb") and c.get(f"/api/products/{pid}/models/{cat['id']}/thumb").status_code==200, "stl rendered thumb")
r=c.post(f"/api/products/{pid}/models/current",json={"items":[{"id":kit["id"],"part":0,"qty":1},{"id":kit["id"],"part":1,"qty":4,"orient":"front"}],"name":"桌子躺"}).get_json()
cur=[i for i in r["items"] if i["current"]][0]
ok(cur["info"]["size"][2]<=10.01 and any(d.get("orient")=="front" for d in cur["parts_of"]), f"merged with orient size {cur['info']['size']}")
r=c.post(f"/api/products/{pid}/models/current",json={"items":[{"id":cat["id"],"qty":1,"orient":"top"}]}).get_json()
cur=[i for i in r["items"] if i["current"]][0]; ok(r["merged"] and cur["parts_of"][0]["orient"]=="top", "single file rotated")
def fake(cfg, system, user, image_b64=None):
    assert "空打" in system and "桌腿" in user
    return _j.dumps({"overall":{"level":"中","zh":"桌腿细高","th":"x"},"items":[{"name":"桌腿","level":"中","risk_zh":"细高","fix_zh":"加帽檐","suggest_orient":"front"}],"settings_zh":"帽檐"})
ai_copy.call=fake
r=c.post(f"/api/products/{pid}/models/ai-check",json={"items":[{"id":kit["id"],"part":1,"qty":4,"orient":"bottom"}]})
d=r.get_json(); ok(r.status_code==200 and d["overall"]["level"]=="中" and d["checked"][0]["rule_risks"], f"ai check {d.get('overall')}")
ok(c.post(f"/api/products/{pid}/models/ai-check",json={"items":[]}).status_code==400, "ai check empty")
def boom(*a,**k): raise RuntimeError("没有设置 AI 密钥")
ai_copy.call=boom
r=c.post(f"/api/products/{pid}/models/ai-check",json={"items":[{"id":cat["id"],"qty":1}]}); ok(r.status_code==400 and "AI" in r.get_json()["error"], "ai error msg")
# 2.13.0 留下的旧分析结果（没有方向 / STL 缩略图）要自动重新分析
p=store.load(pid)
for e in p["model_lib"]:
    if e.get("info",{}).get("ok"):
        for k in ("orients","best","thumb","v"): e["info"].pop(k,None)
        for pp in e["info"].get("parts") or []: pp.pop("orients",None); pp.pop("best",None)
store.save(p)
lib=c.get(f"/api/products/{pid}/models").get_json()
okk=[i for i in lib["items"] if i["info"].get("ok")]
ok(all(i["info"].get("orients") and i["info"].get("thumb") and i["info"].get("v")==modellib.INFO_VER for i in okk), f"old info reanalyzed {len(okk)}")
# v2.14 预览摆盘
import gzip as _gz
r=c.post(f"/api/products/{pid}/models/layout-preview",json={"items":[{"id":kit["id"],"part":1,"qty":4,"orient":"front"}],"bed_w":220})
arr=np.frombuffer(r.data if r.headers.get("Content-Encoding")!="gzip" else _gz.decompress(r.data),dtype="<f4").reshape(-1,3)
ok(r.status_code==200 and abs(arr[:,2].max()-10)<0.01 and arr[:,0].max()<=204, f"layout preview size {arr.max(0).round(1).tolist()}")
r=c.post(f"/api/products/{pid}/models/layout-preview",json={"items":[{"id":kit["id"],"part":1,"qty":30}],"bed_w":100})
arr=np.frombuffer(_gz.decompress(r.data),dtype="<f4").reshape(-1,3); ok(arr[:,0].max()<=84.01, f"narrow bed wraps rows x<={arr[:,0].max():.1f}")
ok(c.post(f"/api/products/{pid}/models/layout-preview",json={"items":[]}).status_code==400, "preview empty refused")
print("ERRORS",E)
