# v2.18：采购（供应商、采购单、分批到货、运费分摊、付款）、财务通道、成品并入库存、发货扣包材、保养领用备件、设置按模块、切片 3MF 清理
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, time, zipfile, tempfile
D=T+"/v218"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T+"/v13", D)
import sqlite3; c0=sqlite3.connect(D+"/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
import app as A
from core import inventory as inv, materials, db, config, production, integrations, slicer
c=A.app.test_client(); E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+=(not b)
q=lambda code: inv.get_item(code)["qty"]

# ---- 供应商 + 物品
sup=c.post("/api/inv/suppliers",json={"name":"Bambu 泰国代理","platform":"Shopee","lead_days":3}).get_json()["supplier"]
ok(sup["id"] and sup["lead_days"]==3, "supplier")
box=c.post("/api/inv/items",json={"name_zh":"纸箱 S","category":"pack","unit":"个","reorder_point":10,"reorder_qty":50,"supplier_id":sup["id"]}).get_json()["item"]
tape=c.post("/api/inv/items",json={"name_zh":"胶带","category":"pack","unit":"卷"}).get_json()["item"]
noz=c.post("/api/inv/items",json={"name_zh":"喷嘴","category":"part","unit":"个"}).get_json()["item"]
fil=c.post("/api/inv/items",json={"name_zh":"PLA 白","category":"filament","material":"PLA","color":"白色"}).get_json()
fil=fil.get("item") or inv.items("filament")[0]
ok(box["supplier_id"]==sup["id"] and box["reorder_qty"]==50, "item supplier + reorder_qty")

# ---- 采购单：草稿 → 下单 → 分批到货（运费分摊）→ 付款
po=c.post("/api/inv/po",json={"supplier_id":sup["id"],"ship_fee":60,"lines":[
    {"item_id":box["id"],"qty":100,"unit_cost":4},{"item_id":fil["id"],"rolls":2,"net_g":1000,"unit_cost":0.5,"brand":"Bambu"}]}).get_json()["po"]
ok(po["status"]=="draft" and po["no"].startswith("CG") and po["total"]==4*100+1000+60, f"po draft total {po['total']}")
ok("要先" in c.post(f"/api/inv/po/{po['id']}/receive",json={}).get_json().get("error",""), "can't receive draft")
po=c.post(f"/api/inv/po/{po['id']}/order").get_json()["po"]; ok(po["status"]=="ordered", "ordered")
tr=inv.in_transit(); ok(tr.get(box["id"])==100 and tr.get(fil["id"])==2000, f"in transit {tr}")
items={x["id"]:x for x in c.get("/api/inv/items").get_json()["items"]}; ok(items[box["id"]]["transit"]==100, "items show transit")
l_box=next(l for l in po["lines"] if l["item_id"]==box["id"]); l_fil=next(l for l in po["lines"] if l["item_id"]==fil["id"])
fq=q(fil["code"])
po=c.post(f"/api/inv/po/{po['id']}/receive",json={"qtys":{str(l_box["id"]):60,str(l_fil["id"]):1}}).get_json()["po"]
ok(po["status"]=="partial" and q(box["code"])==60 and q(fil["code"])==fq+1000, f"partial receive {po['status']} {q(box['code'])} {q(fil['code'])}")
rate=60/1400
ok(abs(inv.get_item(box["id"])["avg_cost"]-4*(1+rate))<1e-6, f"fee allocated to unit cost {inv.get_item(box['id'])['avg_cost']}")
ok(len(materials.spools("PLA","白色","active"))>=1, "filament spool created by PO")
po=c.post(f"/api/inv/po/{po['id']}/receive",json={}).get_json()["po"]
ok(po["status"]=="received" and q(box["code"])==100 and inv.in_transit().get(box["id"]) is None, "receive rest → received")
po=c.post(f"/api/inv/po/{po['id']}/pay",json={"amount":500,"method":"转账"}).get_json()["po"]
ok(po["pay_status"]=="partial" and po["paid"]==500, "partial pay")
po=c.post(f"/api/inv/po/{po['id']}/pay",json={"amount":960}).get_json()["po"]; ok(po["pay_status"]=="paid", "paid")
ok(len(po["docs"])==2, "po links 2 purchase docs")

# ---- 财务通道
ev=inv.finance_events(0); kinds=[e["kind"] for e in ev]
ok(kinds.count("purchase_payment")==2 and kinds.count("purchase_received")==2, f"fin events {kinds}")
fk=integrations.create_key("财务","finance"); H={"Authorization":"Bearer "+fk}
r=c.get("/api/v1/finance/events?since=0",headers=H).get_json(); ok(r["ok"] and len(r["events"])==4, "finance api events")
m=c.get("/api/v1/finance/inventory",headers=H).get_json(); ok(m["ok"] and m["payments"]==1460 and m["purchases_received"]>1400, f"finance month {m.get('payments')} {m.get('purchases_received')}")
ok(c.get("/api/v1/orders",headers=H).status_code==403 and c.get("/api/v1/skus",headers=H).status_code==403, "finance key limited")

# ---- 补货建议 → 采购单
c.post("/api/inv/docs",json={"kind":"issue","lines":[{"item_id":box["id"],"qty":95}]})
sg=c.get("/api/inv/suggest").get_json()["items"]; s1=[x for x in sg if x["item"]["id"]==box["id"]]
ok(s1 and s1[0]["qty"]==50, f"suggest uses reorder_qty {s1[0]['qty'] if s1 else None}")
r=c.post("/api/inv/suggest/po",json={"item_ids":[box["id"]]}).get_json(); ok(len(r["po"])==1 and r["po"][0]["supplier_id"]==sup["id"] and r["po"][0]["status"]=="draft", "po from suggest")
c.post(f"/api/inv/po/{r['po'][0]['id']}/cancel"); ok(inv.get_po(r["po"][0]["id"])["status"]=="cancelled", "cancel po")

# ---- 成品并入库存
production.stock_add("3DP0001-WH", 3, "备货打印 批次#9", "t", "3DP0001", "测试品", "白色")
g=inv.get_item("3DP0001-WH"); ok(g and g["category"]=="goods" and g["qty"]==3, f"goods item {g and g['qty']}")
production.stock_add("3DP0001-WH", -1, "订单出货 任务#1", "t")
ok(q("3DP0001-WH")==2 and inv.moves(item_id=g["id"],limit=1)[0]["kind"]=="ship", "ship move")
st=c.post("/api/inv/stocktake",json={"category":"goods"}).get_json()["doc"]
ln=next(x for x in st["lines"] if x["code"]=="3DP0001-WH")
c.post(f"/api/inv/stocktake/{st['id']}/save",json={"counts":{str(ln["id"]):5}}); c.post(f"/api/inv/stocktake/{st['id']}/confirm")
ok(q("3DP0001-WH")==5 and production.stock_qty("3DP0001-WH")==5, "goods stocktake syncs production stock")
ex={r["key"] for r in inv.expense(0,None,"kind")["rows"]}; ok("ship" not in ex and "produce" not in ex, "goods in/out not expense")

# ---- 发货自动扣包材
config.save_config({"inv_pack_auto":True,"inv_pack_rules":[{"item_id":box["id"],"qty":1,"per":"order"},{"item_id":tape["id"],"qty":0.1,"per":"item"}]})
A.orders_mod.upsert([{"platform":"lazada","order_no":"PK1","status":"待发货","buyer":"x","order_total":100,"items":[{"sku":"3DP0001-WH","qty":3}]}], source="test")
oid=db.conn().execute("SELECT id FROM orders WHERE order_no='PK1'").fetchone()[0]
b0,t0=q(box["code"]),q(tape["code"])
A.orders_mod.update_order(oid,"t",status="shipped")
ok(q(box["code"])==b0-1 and abs(q(tape["code"])-(t0-0.3))<1e-9, f"pack deducted {q(box['code'])} {q(tape['code'])}")
A.orders_mod.update_order(oid,"t",status="completed"); ok(q(box["code"])==b0-1, "pack only once")
A.orders_mod.upsert([{"platform":"lazada","order_no":"PK2","status":"已发货","buyer":"y","order_total":100,"items":[{"sku":"3DP0001-WH","qty":1}]}], source="test")
ok(q(box["code"])==b0-1, "imported shipped order not deducted")
ok("pack" in {r["key"] for r in inv.expense(0,None,"kind")["rows"]}, "pack expense")

# ---- 保养领用备件
c.post("/api/inv/docs",json={"kind":"purchase","lines":[{"item_id":noz["id"],"qty":3,"unit_cost":100}]})
cfg=config.load_config(); code=(cfg["printers"][0].get("code") or "#1")
r=c.post("/api/maintenance",json={"printer":0,"item":"喷嘴","parts":[{"item_id":noz["id"],"qty":1}]})
ok(r.status_code==200 and q(noz["code"])==2, f"maintenance issues part {q(noz['code'])}")
ok(inv.moves(item_id=noz["id"],limit=1)[0]["printer"]==code, "part expense on printer")

# ---- 设置按模块
sc=c.get("/api/settings/schema").get_json()["modules"]
ids=[m["id"] for m in sc]; ok(ids[:3]==["general","cost","goods"] and "inventory" in ids, f"settings modules {ids}")
allkeys=[f["key"] for m in sc for g in m["groups"] for f in g["fields"]]
ok(len(allkeys)==len(set(allkeys)) and all(k in config.load_config() for k in allkeys), "settings keys unique & exist")
r=c.post("/api/config",json={"inv_categories":"模具, 胶水","inv_pack_rules":[{"item_id":box["id"],"qty":"2","per":"item"}]}).get_json()
ok(r["config"]["inv_categories"]==["模具","胶水"] and r["config"]["inv_pack_rules"][0]["qty"]==2.0, "list settings saved")
ok(any(x["id"]=="模具" for x in inv.categories()), "custom category")

# ---- 切片：去掉 3MF 里的切片软件参数
d=tempfile.mkdtemp(); src=os.path.join(d,"p.3mf")
with zipfile.ZipFile(src,"w") as z:
    z.writestr("3D/3dmodel.model","<model/>"); z.writestr("Metadata/project_settings.config","{}"); z.writestr("Metadata/model_settings.config","<x/>")
    z.writestr("Metadata/plate_1.png","x"); z.writestr("[Content_Types].xml","<x/>")
o=slicer._clean_model(src,d); names=zipfile.ZipFile(o).namelist()
ok(o!=src and "3D/3dmodel.model" in names and not any(n.startswith("Metadata/") for n in names), f"3mf cleaned {names}")
print("ERRORS", E)
