# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, json
os.environ["LH_DATA_DIR"]=T+"/vo"; sys.path.insert(0,APP)
import app as A
from core import db, store, config, listing
try: db.create_user("boss","secret1","owner","boss","zh")
except Exception: pass
c=A.app.test_client(); c.post("/api/auth/login",json={"username":"boss","password":"secret1"})
ok=c.post("/api/apikeys", json={"name":"增长引擎","scope":"ops"}).get_json()["key"]
rk=c.post("/api/apikeys", json={"name":"分析只读","scope":"read"}).get_json()["key"]
x=A.app.test_client(); H=lambda k: {"Authorization":"Bearer "+k}
sku=[v["sku"] for v in store.load("3DP0001")["variants"] if v.get("sku")][0]
skus={s["sku"]:s for s in x.get("/api/v1/skus", headers=H(rk)).get_json()["skus"]}
fl=skus[sku]["floor_price"]; print("sku", sku, "floor", fl, "price", skus[sku]["price"])
listing.set_status(["3DP0001"], "lazada", "uploaded")
P=lambda t,b,k=ok: x.post(f"/api/v1/ops/products/{t}", json=b, headers=H(k))
r=P(sku, {"changes":{"price": fl-1}, "reason":"test"}); print("below", r.status_code, r.get_json())
r=P(sku, {"changes":{"price": fl+20, "title_th":"โคมไฟแมวน่ารัก ไฟกลางคืน ตกแต่งห้องนอน"}, "reason":"换标题和价格","source_action_id":"A1"}); j=r.get_json(); print("ok", r.status_code, j)
cid=j["change_id"]
r=P(sku, {"changes":{"price": fl+30}, "reason":"again"}); print("daily", r.status_code, r.get_json().get("code"))
r=P("3DP0001", {"changes":{"price": 300}}); print("multi sku", r.status_code, r.get_json().get("code"))
r=P("3DP0001", {"changes":{"active": False, "attributes":{"catProperty.p-20000":"Generic"}}, "reason":"测款失败下架"}); print("delist", r.get_json().get("applied"), r.get_json().get("before"))
r=P("3DP0001", {"changes":{"stock": 5}}); print("bad field", r.get_json())
r=P("NOPE-1", {"changes":{"active": False}}); print("notfound", r.status_code)
p=store.load("3DP0001"); print("applied", p["copy"]["title_th"][:20], [v.get("manual_price") for v in p["variants"]][:2], p["active"], p["attributes"]["catProperty.p-20000"], p["listing"]["lazada"])
print("read key ops", P(sku, {"changes":{"active":True}}, rk).status_code, "ops key orders", x.get("/api/v1/orders", headers=H(ok)).status_code, "ping", x.get("/api/v1/ping", headers=H(ok)).status_code)
lst=x.get("/api/v1/ops/changes", headers=H(ok)).get_json(); print("list", lst["mode"], [(ch["id"], ch["status"], list(ch["before"])) for ch in lst["changes"]])
r=x.post(f"/api/v1/ops/changes/{cid}/revert", headers=H(ok)); print("revert", r.status_code, r.get_json()["change"]["status"])
p=store.load("3DP0001"); print("after revert", p["copy"]["title_th"][:20], [v.get("manual_price") for v in p["variants"]][:2])
# confirm mode
config.save_config({"ops_write_mode":"confirm"})
sku2=[v["sku"] for v in store.load("3DP0001")["variants"] if v.get("sku")][1]
r=P(sku2, {"changes":{"price": skus[sku2]["floor_price"]+10},"reason":"建议"}); j=r.get_json(); print("confirm", j["applied"], j["status"])
print("ui list", c.get("/api/ops/changes?status=pending").get_json()["counts"])
print("approve", c.post(f"/api/ops/changes/{j['change_id']}/approve", json={}).get_json()["change"]["status"], [v.get("manual_price") for v in store.load("3DP0001")["variants"]][:3])
print("export list status", [ (p["id"],p["lz"]["status"],p["active"]) for p in c.get("/api/products").get_json() if p["id"]=="3DP0001"])
print("audit", [a["action"] for a in c.get("/api/audit?limit=10").get_json()["items"]][:6])
