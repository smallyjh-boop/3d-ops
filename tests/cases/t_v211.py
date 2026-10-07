# 回归测试（自动从开发时的测试脚本转换）。由 tests/run_all.py 调用，不要直接在正式数据上运行。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, json, shutil, time
D=T+"/v211data"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
for x in ("products","config.json","sequence.json"):
    src=T+"/v13/"+x
    (shutil.copytree if os.path.isdir(src) else shutil.copy)(src, D+"/"+x)
os.environ["LH_DATA_DIR"]=D
sys.path.insert(0,APP)
import app as A
c=A.app.test_client()
ERR=0
def ok(cond,msg):
    global ERR
    print(("OK  " if cond else "ERR ")+msg)
    if not cond: ERR+=1
sk=c.get("/api/skus").get_json(); sk=sk if isinstance(sk,list) else sk["skus"]
s1=sk[0]["sku"]; s2=sk[1]["sku"]
now=time.time()
orders=[
 {"platform":"lazada","order_no":"L1","status":"待发货","buyer":"somchai","phone":"0812345678","order_total":300,"items":[{"sku":s1,"qty":1}]},
 {"platform":"lazada","order_no":"L2","status":"待发货","buyer":"big","order_total":5000,"items":[{"sku":s1,"qty":5}],"commission":250,"service_fee":100,"payment_fee":50},
 {"platform":"shopee","order_no":"S1","status":"待发货","buyer":"nid","buyer_note":"ขอสีแดง ใส่ชื่อ Nid","order_total":200,"items":[{"sku":s2,"qty":1}]},
 {"platform":"lazada","order_no":"C1","status":"待发货","buyer":"codguy","phone":"0899999999","payment":"COD เก็บเงินปลายทาง","order_total":900,"items":[{"sku":s1,"qty":2}]},
]
st=A.orders_mod.upsert(orders, source="test")
ok(st["orders_new"]==4 and st["held"]==3, f"upsert held={st['held']}")
r=c.get("/api/orders?tab=review").get_json()
ok(r["counts"]["review"]==3, f"review count {r['counts']['review']}")
for o in r["orders"]: print("   ", o["order_no"], o["hold_reason"], o["is_cod"], o["buyer_tags"], o["carrier"], o["ship_method"])
A.production.generate("t")
j=A.db.conn().execute("SELECT o.order_no, COUNT(j.id) FROM orders o LEFT JOIN jobs j ON j.order_id=o.id GROUP BY o.id").fetchall()
print("   jobs", [tuple(x) for x in j])
ok(dict((x[0],x[1]) for x in j)["L2"]==0, "held order has no jobs")
L2=[o for o in r["orders"] if o["order_no"]=="L2"][0]
x=c.post(f"/api/orders/{L2['id']}/review",json={"action":"approve"}).get_json()
ok(x["hold"]==0 and x["reviewed_by"], "approve")
n=A.db.conn().execute("SELECT COUNT(*) FROM jobs WHERE order_id=?",(L2["id"],)).fetchone()[0]
ok(n>0, f"jobs after approve {n}")
x=c.post(f"/api/orders/{L2['id']}/review",json={"action":"hold","reason":"等客户确认"}).get_json()
n=A.db.conn().execute("SELECT COUNT(*) FROM jobs WHERE order_id=?",(L2["id"],)).fetchone()[0]
ok(x["hold"]==1 and n==0, f"hold removes todo jobs {n}")
d=c.get(f"/api/orders/{L2['id']}").get_json()
ok(d["profit"]["fee_source"]=="detail" and d["profit"]["fee"]==400, f"fee detail {d['profit']['fee']}")
# delivery failed -> aftersales
C1=A.db.conn().execute("SELECT id FROM orders WHERE order_no='C1'").fetchone()[0]
A.orders_mod.upsert([{"platform":"lazada","order_no":"C1","status":"Failed Delivery"}], source="test")
o=A.orders_mod.get_order(C1)
ok(o["status"]=="delivery_failed", "status delivery_failed "+o["status"])
a=c.get(f"/api/aftersales?order_id={C1}").get_json()["items"]
ok(len(a)==1 and a[0]["kind"]=="cod_reject" and a[0]["stage"]=="wait_return", "auto cod_reject")
# buyer profile now refused 1; new COD order by same buyer gets held
A.orders_mod.upsert([{"platform":"lazada","order_no":"C2","status":"待发货","buyer":"codguy","phone":"0899999999","cod":100,"order_total":100,"items":[{"sku":s1,"qty":1}]}], source="test")
o2=A.orders_mod.get_order(A.db.conn().execute("SELECT id FROM orders WHERE order_no='C2'").fetchone()[0])
ok(o2["hold"]==1 and "拒收过" in o2["hold_reason"], "refuser held: "+str(o2["hold_reason"]))
# inspect
aid=a[0]["id"]
item=A.orders_mod.get_order(C1)["items"][0]
x=c.post(f"/api/aftersales/{aid}/inspect",json={"items":[{"item_id":item["id"],"restock":1,"scrap":1}],"note":"一个坏了"}).get_json()
ok(x.get("inspect_result")=="partial" and x["stage"]=="closed" and x["scrap_cost"], f"inspect {x.get('error')} {x.get('scrap_cost')}")
stk=A.production.stock_qty(item["sku"]); ok(stk>=1, f"stock {stk}")
# aftersales update + evidence
import io
x=c.post("/api/aftersales",json={"order_id":L2["id"],"kind":"refund","reason":"颜色不对","amount":100,"responsibility":"production"}).get_json()
aid2=x["id"]
x=c.post(f"/api/aftersales/{aid2}",json={"stage":"wait_platform","penalty":20}).get_json()
ok(x["stage"]=="wait_platform" and x["penalty"]==20 and x["loss"]==120, f"as update loss {x.get('loss')}")
x=c.post(f"/api/aftersales/{aid2}/evidence",data={"files":[(io.BytesIO(b"\x89PNG...."),"p.png")]},content_type="multipart/form-data").get_json()
ok(len(x["evidence"])==1, "evidence")
f=x["evidence"][0]["file"]
ok(c.get(f"/api/aftersales/{aid2}/evidence/{f}").status_code==200, "evidence get")
x=c.delete(f"/api/aftersales/{aid2}/evidence/{f}").get_json(); ok(x["evidence"]==[], "evidence del")
x=c.post(f"/api/aftersales/{aid2}",json={"stage":"refunded"}).get_json(); ok(x["status"]=="closed", "refunded closes")
lst=c.get("/api/aftersales?status=open").get_json(); print("   counts", lst["counts"], lst["loss_total"])
p=c.get("/api/profit?days=30").get_json(); print("   profit total", p["total"])
ok(p["total"].get("aftersales",0)>0, "profit has aftersales loss")
# tracking import + handover
L1=A.db.conn().execute("SELECT id FROM orders WHERE order_no='L1'").fetchone()[0]
c.post(f"/api/orders/{L1}/review",json={"action":"approve"})
r=c.post("/api/orders/tracking-import",json={"text":"L1,LEX123\nL2\tLEX456\tLEX\nNOPE,1"}).get_json()
ok(r["updated"]==2 and r["not_found"]==["NOPE"], f"tracking import {r}")
h=c.post("/api/handovers",json={"carrier":"Lazada Express (LEX)","method":"pickup"}).get_json()
x=c.post(f"/api/handovers/{h['id']}/scan",json={"code":"LEX123"}).get_json(); ok(x.get("order") and True, f"scan {x.get('warn')}")
x=c.post(f"/api/handovers/{h['id']}/scan",json={"code":"LEX123"}).get_json(); ok("已经扫过" in (x.get("error") or ""), "dup scan")
x=c.post(f"/api/handovers/{h['id']}/scan",json={"code":"LEX456"}).get_json(); ok("待审核" in (x.get("error") or ""), "held blocked")
ok(c.get(f"/print/handover?id={h['id']}").status_code==200, "print handover")
x=c.post(f"/api/handovers/{h['id']}/close",json={}).get_json(); ok(x.get("shipped")==1, f"close {x}")
ok(A.orders_mod.get_order(L1)["status"]=="shipped", "shipped after handover")
# buyers
r=c.get("/api/buyers").get_json(); print("   buyers", [(b["name"],b["refused"],b["orders"],b["key_show"]) for b in r["items"]])
key=A.orders_mod.get_order(C1)["buyer_key"]
x=c.post("/api/buyers",json={"key":key,"level":"blacklist","note":"拒收两次"}).get_json(); ok(x["level"]=="blacklist","blacklist")
r=c.get("/api/orders?tab=urgent").get_json(); print("   urgent", r["counts"]["urgent"])
ok(c.get("/api/orders/export").status_code==200, "export")
ok(c.get("/api/dashboard").get_json().get("review") is not None, "dashboard")
print("ERRORS", ERR)
