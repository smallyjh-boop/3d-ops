# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, time
D=T+"/vl2"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
for x in ("products","config.json","sequence.json"):
    src=T+"/v13/"+x; (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, D+"/"+x)
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
import app as A
c=A.app.test_client(); E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+= (not b)
pids=[p["id"] for p in c.get("/api/products").get_json()][:3] if isinstance(c.get("/api/products").get_json(),list) else [p["id"] for p in c.get("/api/products").get_json()["products"]][:3]
from core import listing, store
b=listing.create_batch("lazada", pids, [], "LZ-A")
s0=time.time()
ok(listing.batch_set(b["id"],"uploaded")==3, "batch uploaded")
v=listing.v1_view(store.load(pids[0]), listing.batch_names())["lazada"]
ok(v["status"]=="uploaded" and v["first_uploaded_at"] and v["first_listed_at"] is None and v["batch"]=="LZ-A", f"uploaded view {v}")
time.sleep(1.1)
ok(listing.batch_set(b["id"],"live")==3, "batch live")
v=listing.v1_view(store.load(pids[0]))["lazada"]
fl=v["first_listed_at"]; ok(fl and fl>v["first_uploaded_at"], "first_listed after upload")
listing.set_status([pids[1]],"lazada","rejected","图片有水印")
listing.set_status([pids[0]],"lazada","inactive")
time.sleep(1.1); listing.set_status([pids[0]],"lazada","live")
v=listing.v1_view(store.load(pids[0]))["lazada"]
ok(v["first_listed_at"]==fl and v["live_at"]>fl and v["delisted_at"], "relist keeps first_listed")
# ops change on live product -> update with platform_status live
p=store.load(pids[2]); from modules.link import opsapi
opsapi._mark_unsynced(p,["title_th"]); store.save(p)
v=listing.v1_view(store.load(pids[2]))["lazada"]
ok(v["status"]=="update" and v["platform_status"]=="live", f"update keeps platform_status {v['platform_status']}")
# direct pending->live sets uploaded times
listing.set_status([pids[1]],"shopee","pending"); listing.set_status([pids[1]],"shopee","live")
v=listing.v1_view(store.load(pids[1]))["shopee"]; ok(v["first_uploaded_at"] and v["first_listed_at"], "direct live")
since=int(time.time())-1
from core import integrations
k=integrations.create_key("t","read"); k=k["key"] if isinstance(k,dict) else k
r=c.get(f"/api/v1/skus?since={since}",headers={"Authorization":"Bearer "+k}).get_json()
ok(r["ok"] and all("listing" in x for x in r["skus"]) and len({x["product_id"] for x in r["skus"]})>=2, f"skus since {len(r['skus'])}")
print(r["skus"][0]["listing"])
print("ERRORS",E)
