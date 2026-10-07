# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, json, io
os.environ["LH_DATA_DIR"]=T+"/opsdata"
sys.path.insert(0,APP)
import app as A
c=A.app.test_client()
def imp(path):
    r=c.post("/api/orders/import/preview",data={"file":(open(path,"rb"),os.path.basename(path))},content_type="multipart/form-data").get_json()
    print("preview", r.get("error"), r["rows"], r["platform"], {k:v for k,v in r["mapping"].items() if v})
    s=c.post("/api/orders/import/commit",json={"token":r["token"],"mapping":r["mapping"],"platform":r["platform"],"profile":"测试"}).get_json()
    print("commit", s)
imp(T+"/ordtest/bigseller_orders.xlsx")
imp(T+"/ordtest/shopee_th.csv")
for o in c.get("/api/orders?days=3650").get_json()["orders"]:
    print(o["order_no"],o["platform"],o["status"],o["order_total"],[(i["sku"],i["product_id"],i["qty"],i["color"],i["grams"]) for i in o["items"]])
b=c.get("/api/production").get_json()
for l in b["lanes"]: print(l["name"],[(j["id"],j["sku"],j["status"]) for j in l.get("queue",[])])
print("missing",len(b["missing_data"]))
m=c.post("/api/orders/manual",json={"buyer":"批发客户","kind":"wholesale","custom_note":"刻字ABC","items":[{"sku":"3DP0001-PK","qty":10,"unit_price":99}]}).get_json()
print("manual",m["order_no"],m["order_total"],m["kind"])
jid=b["lanes"][0].get("queue",[])[0]["id"] if b["lanes"][0].get("queue",[]) else None
print("jid",jid)
if jid:
  for st in ("printing","post","packed","done"): print(st, c.post(f"/api/jobs/{jid}",json={"status":st}).get_json().get("status"))
print(json.dumps(c.get("/api/materials").get_json()["rows"][:3],ensure_ascii=False))
p=c.get("/api/profit?days=30").get_json(); print(p["total"],p["margin"],p["platforms"])
