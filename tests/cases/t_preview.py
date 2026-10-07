# v2.15.3：大模型打开加速 —— 3MF 快速解析结果和逐个解析一致、预览没算好回 202 + 后台排队、304 不重复下载、开机补算
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, time, zipfile, re, gzip, struct
D=T+"/vprev"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T+"/v13", D)
import sqlite3; c0=sqlite3.connect(D+"/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
import numpy as np
import app as A
from core import store, mesh, modellib, preview, filemgr
c=A.app.test_client(); E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+=(not b)

# ---- 造一个 3MF：两个物体，一个属性顺序正常（快速路径），一个属性顺序打乱（慢速路径）
rng=np.random.default_rng(1)
def obj(oid, nv, nt, shuffled):
    v=rng.random((nv,3))*50; t=rng.integers(0,nv,(nt,3))
    if shuffled:
        vs="".join(f'<vertex z="{a[2]:.4f}" x="{a[0]:.4f}" y="{a[1]:.4f}"/>' for a in v)
        ts="".join(f'<triangle v3="{b[2]}" v1="{b[0]}" v2="{b[1]}" p1="0"/>' for b in t)
    else:
        vs="".join(f'<vertex x="{a[0]:.4f}" y="{a[1]:.4f}" z="{a[2]:.4f}"/>' for a in v)
        ts="".join(f'<triangle v1="{b[0]}" v2="{b[1]}" v3="{b[2]}"/>' for b in t)
    ref=np.round(v,4)[t]
    return f'<object id="{oid}" name="part{oid}" type="model"><mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>', ref
o1,r1=obj(1,3000,6000,False); o2,r2=obj(2,500,900,True)
xml=f'<?xml version="1.0"?><model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources>{o1}{o2}</resources><build><item objectid="1"/><item objectid="2"/></build></model>'
f3=T+"/two.3mf"
with zipfile.ZipFile(f3,"w") as z: z.writestr("3D/3dmodel.model", xml)
parts=modellib.load_parts(f3)
ok(len(parts)==2 and [n for n,_ in parts]==["part1","part2"], f"3MF 两个组件 {[n for n,_ in parts]}")
ok(np.abs(parts[0][1]-r1).max()<1e-6, "快速路径解析结果一致")
ok(np.abs(parts[1][1]-r2).max()<1e-6, "属性顺序打乱的走慢速路径，结果一致")
allt=mesh.load(f3); ok(len(allt)==6900, f"mesh.load 合计 {len(allt)} 面")
ok(len(mesh.load(T+"/bambu_project.3mf"))>0, "拓竹项目 3MF 还能读")

# ---- 预览：没算好 + 大文件 → 202，后台算好后 200，带 ETag，再请求 304
pid=store.list_products()[0]["id"]
r=c.post(f"/api/products/{pid}/model", data={"file":(open(T+"/cat.stl","rb"),"cat.stl")}, content_type="multipart/form-data")
ok(r.status_code==200, f"上传模型 {r.status_code}")
p=store.load(pid); fp=filemgr.model_path(p)
for _ in range(50):          # 上传后会后台预先算（等它算完再清掉，模拟「老产品没有缓存」）
    if preview.ready(fp): break
    time.sleep(0.1)
ok(preview.ready(fp), "上传后后台已算好预览")
shutil.rmtree(preview.CACHE, ignore_errors=True)
old=preview.SYNC_BYTES; preview.SYNC_BYTES=1      # 当它是大文件
r=c.get(f"/api/products/{pid}/model/preview?nowait=1")
ok(r.status_code==202 and r.get_json().get("pending"), f"没算好回 202 {r.status_code}")
for _ in range(100):
    if preview.ready(fp): break
    time.sleep(0.1)
ok(preview.ready(fp), "后台排队算好了")
r=c.get(f"/api/products/{pid}/model/preview?nowait=1")
ok(r.status_code==200 and r.headers.get("ETag"), f"算好后 200 + ETag {r.status_code}")
raw=gzip.decompress(r.data); ok(raw[:4]==b"3DPV", "预览格式正确")
r2=c.get(f"/api/products/{pid}/model/preview?nowait=1", headers={"If-None-Match": r.headers["ETag"]})
ok(r2.status_code==304 and not r2.data, f"浏览器已有 → 304 {r2.status_code}")
r3=c.get(f"/api/products/{pid}/model/preview")       # 老页面（不带 nowait）照样当场算
ok(r3.status_code==200, "不带 nowait 照样 200")
preview.SYNC_BYTES=old
# 小文件不带缓存也当场算（不回 202）
shutil.rmtree(preview.CACHE, ignore_errors=True)
r=c.get(f"/api/products/{pid}/model/preview?nowait=1")
ok(r.status_code==200, f"小文件当场算 {r.status_code}")

# ---- 开机补算：清掉缓存，warm_all 把模型排队算好
shutil.rmtree(preview.CACHE, ignore_errors=True)
preview.warm_all(min_bytes=0, delay=0)
for _ in range(100):
    if preview.ready(fp): break
    time.sleep(0.1)
ok(preview.ready(fp), "开机补算：产品模型预览已算好")
# 同一个文件重复排队只算一次
preview.warm(fp); preview.warm(fp); ok(len(preview._queued)<=1, "重复排队去重")

# ---- 页面报上来的慢加载记到日志
r=c.post("/api/client-timing", json={"kind":"快速预览","total":3500,"download":3000,"parse":200,"prepare":100,"bytes":2000000,"triangles":200000,"preview":True,"url":"/x"})
ok(r.status_code==200, "client-timing")
time.sleep(0.2)
log=open(os.path.join(D,"logs","app.log"),encoding="utf-8").read()
ok("3D 打开较慢" in log, "慢加载写进运行日志")
print("ERRORS", E)
