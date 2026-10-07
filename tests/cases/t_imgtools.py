# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, base64
D=T+"/vimg"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T+"/v13", D)
import sqlite3; c0=sqlite3.connect(D+"/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
import numpy as np
from PIL import Image, ImageDraw
import app as A
from core import imgtools, store
c=A.app.test_client(); E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+=(not b)
def durl(img, fmt="PNG"):
    b=io.BytesIO(); img.save(b, fmt); return "data:image/png;base64,"+base64.b64encode(b.getvalue()).decode()
# gradient background with a "watermark" text block
W,H=900,700
bg=np.zeros((H,W,3),np.uint8); bg[...,0]=np.linspace(180,240,W)[None,:]; bg[...,1]=np.linspace(200,230,H)[:,None]; bg[...,2]=200
img=Image.fromarray(bg); d=ImageDraw.Draw(img); d.rectangle([400,300,560,340],fill=(20,20,20))
mask=Image.new("L",(W,H),0); ImageDraw.Draw(mask).rectangle([395,295,565,345],fill=255)
st=c.get("/api/imgtool/status").get_json(); ok("inpaint" in st, f"status {st['inpaint']} cv2={st['cv2']} lama={st['lama']}")
r=c.post("/api/imgtool/inpaint",json={"data":durl(img),"mask":durl(mask)}).get_json()
out=np.asarray(imgtools.from_data_url(r["data"]).convert("RGB")).astype(int)
diff=np.abs(out[300:340,400:560]-bg[300:340,400:560]).mean()
same=np.abs(out[:200,:200]-bg[:200,:200]).max()
ok(r["method"]=="opencv" and diff<25 and same<=6, f"opencv inpaint diff {diff:.1f}, untouched max {same}")
o2,m2=imgtools.inpaint(img,mask,"basic"); d2=np.abs(np.asarray(o2).astype(int)[300:340,400:560]-bg[300:340,400:560]).mean(); ok(m2=="basic" and d2<40, f"basic inpaint diff {d2:.1f}")
# fake LaMa session: identity output 0-255 (plumbing only)
class _I:
    def __init__(s,n): s.name=n
class FakeSess:
    def get_inputs(s): return [_I("image"),_I("mask")]
    def run(s,_o,feeds):
        assert feeds["image"].shape==(1,3,512,512) and feeds["mask"].shape==(1,1,512,512)
        return [feeds["image"]*255.0]
os.makedirs(imgtools.LAMA_DIR,exist_ok=True); open(imgtools.LAMA_PATH,"wb").write(b"x")
imgtools._lama=FakeSess()
ok(imgtools.status()["inpaint"]=="lama", "lama detected")
o3,m3=imgtools.inpaint(img,mask); ok(m3=="lama" and o3.size==img.size, "lama plumbing")
os.remove(imgtools.LAMA_PATH); imgtools._lama=None
ok(c.post("/api/imgtool/inpaint",json={"data":durl(img),"mask":durl(Image.new("L",(W,H),0))}).status_code==400, "empty mask refused")
# save edited image
pid="3DP0001"; p=store.load(pid)
up=c.post(f"/api/products/{pid}/images",data={"files":[(io.BytesIO(open(T+'/claude-0/x.jpg','rb').read() if os.path.exists(T+'/claude-0/x.jpg') else (lambda b:(img.save(b,'JPEG'),b.getvalue())[1])(io.BytesIO())),"a.jpg")]},content_type="multipart/form-data").get_json()
raw=up["images"][-1]["raw"]; n0=len(up["images"])
p2=c.post(f"/api/products/{pid}/images/edited",json={"raw":raw,"data":durl(o2.convert('RGB')),"mode":"new"}).get_json()
ok(len(p2["images"])==n0+1 and p2["images"][n0]["edited"], "save as new")
rgba=o2.convert("RGBA"); a=np.asarray(rgba).copy(); a[:50,:50,3]=0; rgba=Image.fromarray(a)
p3=c.post(f"/api/products/{pid}/images/edited",json={"raw":raw,"data":durl(rgba),"mode":"replace"}).get_json()
it=[x for x in p3["images"] if x.get("has_orig")][0]
ok(it["raw"].endswith(".png") and os.path.exists(os.path.join(store.image_dir(pid,"raw"),"_orig",it["raw"])), f"replace -> png with backup {it['raw']}")
p4=c.post(f"/api/products/{pid}/images/restore",json={"raw":it["raw"]}).get_json()
it4=[x for x in p4["images"] if x["raw"]==it["raw"]][0]; ok(not it4["has_orig"] and not it4["edited"], "restore original")
ok(c.post(f"/api/products/{pid}/images/restore",json={"raw":it["raw"]}).status_code==400, "restore twice refused")
print("ERRORS",E)
