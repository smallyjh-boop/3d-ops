# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, json
os.environ["LH_DATA_DIR"]=T+"/apidata"; sys.path.insert(0,APP)
import app as A
from core import db
db.create_user('boss','secret1','owner','老板','zh'); db.create_user('nok','pass123','listing','Nok','th')
c=A.app.test_client(); c.post("/api/auth/login",json={"username":"boss","password":"secret1"})
key=c.post("/api/apikeys",json={"name":"测试脚本"}).get_json()["key"]; print("key",key[:12])
x=A.app.test_client()
print("noauth", x.get("/api/v1/ping").status_code, x.get("/api/v1/ping",headers={"Authorization":"Bearer bad"}).status_code)
H={"Authorization":"Bearer "+key}
print("ping", x.get("/api/v1/ping",headers=H).get_json())
o={"platform":"tiktok","order_no":"TT001","status":"AWAITING_SHIPMENT 待发货","order_time":"2026-10-05T10:00:00+07:00","buyer":"Ann",
   "custom":"x","order_total":"258","items":[{"sku":"3DP0001-PK","qty":2,"unit_price":129},{"sku":"NOPE-1","qty":1}]}
r=x.post("/api/v1/orders",headers=H,json={"orders":[o,{"items":[]}],"source":"tt-test"}).get_json(); print("push",r)
r=x.post("/api/v1/orders",headers=H,json={"orders":[o]}).get_json(); print("push again",r["orders_new"],r["orders_updated"],r["jobs"])
print("status", x.post("/api/v1/orders/status",headers=H,json={"platform":"tiktok","order_no":"TT001","tracking_no":"TH99"}).get_json())
l=x.get("/api/v1/orders?since=0",headers=H).get_json()["orders"][0]; print("list",l["order_no"],l["status"],l["tracking_no"],l["source"],l["jobs"])
import datetime as dt; print("time", dt.datetime.fromtimestamp(l["order_time"]))
print("status2", x.post("/api/v1/orders/status",headers=H,json={"orders":[{"platform":"tiktok","order_no":"TT001","status":"cancelled"},{"order_no":"ZZZ"}]}).get_json())
print("jobs after cancel", [tuple(r) for r in db.conn().execute("select order_id,status from jobs")])
print("skus", len(x.get("/api/v1/skus",headers=H).get_json()["skus"]), x.get("/api/v1/production",headers=H).get_json())
print("webhook", x.post("/api/v1/webhook/shopee",data=b'{"code":3,"data":{"ordersn":"A1"}}').get_json(), x.post("/api/v1/webhook/foo",data=b'{}').status_code)
s=c.post("/api/shops",json={"platform":"shopee","name":"Shopee 主店","creds":{"partner_id":"1","partner_key":"secretk","shop_id":"2","access_token":"t","refresh_token":"r"},"enabled":True}).get_json()
sh=s["shops"][0]; print("shop", sh["creds"], sh["ready"])
c.post("/api/shops",json={"id":sh["id"],"platform":"shopee","name":"Shopee 主店","creds":{"partner_key":"******","shop_id":"3"},"enabled":True})
from core import integrations; print("kept secret", integrations.get_shop_raw(sh["id"])["creds"])
r=c.post(f"/api/shops/{sh['id']}/sync",json={}); print("sync", r.status_code, r.get_json())
print("auth-url", c.post(f"/api/shops/{sh['id']}/auth-url",json={"redirect":"http://x/"}).get_json()["url"][:90])
ig=c.get("/api/integrations").get_json(); print("log", [(l["source"],l["ok"],l["message"][:60]) for l in ig["log"]][:4]); print("hooks", ig["webhooks"][0]["result"])
n=A.app.test_client(); n.post("/api/auth/login",json={"username":"nok","password":"pass123"}); print("listing->integrations", n.get("/api/integrations").status_code, n.get("/api-docs").status_code)
print("docs", c.get("/api-docs").status_code)
# converters
from core.connectors.shopee import ShopeeConnector; from core.connectors.lazada import LazadaConnector, sign
print(ShopeeConnector({}).convert({"order_sn":"S1","order_status":"READY_TO_SHIP","create_time":1791200000,"item_list":[{"model_sku":"3DP0001-WH","item_name":"cat","model_name":"White","model_quantity_purchased":2,"model_discounted_price":99}]}))
print(LazadaConnector({}).convert({"order_id":1,"order_number":"L1","statuses":["ready_to_ship"],"created_at":"2026-10-04 10:00:00 +0700","price":"258.00"},[{"sku":"3DP0001-PK","item_price":"129","paid_price":"129"}]*2))
print(sign("helloworld","/orders/get",{"app_key":"123","timestamp":"1"}))
