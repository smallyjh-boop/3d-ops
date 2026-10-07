# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, json, time
os.environ["LH_DATA_DIR"]=T+"/v20"; sys.path.insert(0,APP)
import app as A
from core import db
c=A.app.test_client()
def J(r):
    d=r.get_json()
    if r.status_code>=400: print("  ERR",r.status_code,d)
    return d
pv=J(c.post("/api/orders/import/preview",data={"file":(open(T+"/ordtest/bigseller_orders.xlsx","rb"),"b.xlsx")},content_type="multipart/form-data"))
J(c.post("/api/orders/import/commit",json={"token":pv["token"],"mapping":pv["mapping"]}))
J(c.post("/api/orders/manual",json={"kind":"wholesale","buyer":"W","items":[{"sku":"3DP0001-PK","qty":5,"unit_price":99}]}))
o=J(c.get("/api/orders?tab=all"))["orders"]; print("ship_by auto", [(x["order_no"], bool(x["ship_by"])) for x in o])
r=J(c.get("/api/products/3DP0001/recipe")); print("recipe", r["summary_zh"], [p["capacity"] for p in r["per_printer"]], [x["level"] for x in r["checks"]])
r=J(c.post("/api/products/3DP0001/recipe",json=dict(r["recipe"],orientation="front",supports="tree",brim=True,per_plate=2))); print("saved", r["summary_zh"])
f=J(c.post("/api/products/3DP0001/recipe/slice",json={"printer":1,"count":2})); print("sliced", f["status"], f["per_plate"], f["grams"], [x["level"] for x in f["checks"]], {k:v for k,v in f["report"].items() if k!="preview"})
print("review missing", J(c.post(f"/api/print-files/{f['id']}/review",json={"items":{"supports":1}})))
items={k:1 for k,_ in r["review_items"]}
f=J(c.post(f"/api/print-files/{f['id']}/review",json={"items":items})); print("reviewed", f["status"])
b=J(c.get("/api/production"))
for l in b["lanes"]: print("lane", l["name"], [(j["id"],j["sku"],j["remaining"],(j.get("plan") or {}).get("per_plate"),(j.get("plan") or {}).get("file_status")) for j in l["queue"]])
pk=[j for l in b["lanes"] for j in l["queue"] if j["sku"]=="3DP0001-PK"]
jid=pk[0]["id"]
so=J(c.get(f"/api/jobs/{jid}/send-options?printer=1")); print("options", so["remaining"], [m["id"] for m in so["merge"]], so["capacity"], so["suggestion"], [ (x["per_plate"],x["status"]) for x in so["files"]])
print("no confirm", J(c.post(f"/api/jobs/{jid}/start",json={"printer":1,"count":4,"send":False})))
st=J(c.post(f"/api/jobs/{jid}/start",json={"printer":1,"count":4,"merge_ids":[m["id"] for m in so["merge"]],"send":False,"file_id":None,"confirm":{"bed_clear":True,"material":True}}))
print("start manual", st)
runs=J(c.get("/api/production"))["lanes"][1]["runs"]; print("runs", [(r["id"],r["count"],r["alloc"],r["extra"]) for r in runs])
J(c.post(f"/api/runs/{st['run_id']}/done"))
print("jobs after", [(j["id"],j["sku"],j["qty"],j["qty_done"],j["status"]) for j in J(c.get("/api/production"))["lanes"][1]["queue"]+J(c.get("/api/production"))["post"]])
# full plate with on-the-fly slice count 6 on printer 1 -> needs slicing (recipe reviewed -> inherits)
so=J(c.get(f"/api/jobs/{jid}/send-options?printer=1")) if J(c.get("/api/production")) else None
todo=[j for l in J(c.get("/api/production"))["lanes"] for j in l["queue"] if j["sku"]=="3DP0001-PK"]
if todo:
    t=time.time(); st2=J(c.post(f"/api/jobs/{todo[0]['id']}/start",json={"printer":1,"count":6,"send":True,"confirm":{"bed_clear":True,"material":True,"review":items}})); print("send x6", round(time.time()-t,1), st2)
    if st2 and st2.get("run_id"):
        J(c.post(f"/api/runs/{st2['run_id']}/fail",json={"reason":"翘边 / 首层不粘","note":"test"}))
print("stock", J(c.get("/api/stock")))
q=J(c.get("/api/quality")); print("quality", q["runs_done"], q["runs_failed"], q["fail_rate"], q["by_reason"])
print("maint", [ (m["name"], m["hours"]) for m in J(c.get("/api/maintenance"))["printers"]])
J(c.post("/api/maintenance",json={"printer":1,"item":"clean"}))
oid=o[0]["id"]; od=J(c.get(f"/api/orders/{oid}"))
print("aftersales", J(c.post("/api/aftersales",json={"order_id":oid,"kind":"reship","reason":"运输损坏","items":[{"item_id":od["items"][0]["id"],"qty":1}]})), len(J(c.get("/api/aftersales"))["items"]))
print("backup", J(c.post("/api/backups"))["name"])
J(c.post("/api/groups",json={"name":"厨房用品"})); g=J(c.get("/api/groups"))["groups"]; J(c.post("/api/groups/assign",json={"ids":["3DP0001","3DP0002"],"group":g[0]["id"]}))
pl=J(c.get("/api/products")); print("products", [(p["id"],p["groups"],p["file_status"],p["sold30"],p["has_model"]) for p in pl[:3]])
d=J(c.get("/api/dashboard")); print("dash", {k:v for k,v in d.items() if k not in ("printers",)})
lk=J(c.get("/api/pack/lookup?code=26100512345")); print("pack", lk.get("order_no"), [(j["id"],j["status"]) for j in lk.get("jobs",[])])
x=c.get("/print/jobs?ids=1,2"); print("ticket", x.status_code, len(x.data))
print("mat", [(m["color"], m["pending_kg"], m.get("humid")) for m in J(c.get("/api/materials"))["rows"]])
J(c.post("/api/materials/flag",json={"material":"PETG","color":"黑色","action":"opened"}))
