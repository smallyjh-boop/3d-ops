# v2.17：库存管理模块 —— 物品档案、单据（入库 / 领用 / 报废 / 调整 / 作废）、盘点、耗材和料卷同步、打印扣料带损耗、支出统计、权限
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, time
D=T+"/vinv"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T+"/v13", D)
import sqlite3; c0=sqlite3.connect(D+"/app.db"); c0.execute("delete from users")
c0.execute("CREATE TABLE IF NOT EXISTS inventory (material TEXT NOT NULL, color TEXT NOT NULL, kg REAL DEFAULT 0, note TEXT, updated_at REAL, PRIMARY KEY(material, color))")
c0.execute("INSERT OR REPLACE INTO inventory(material,color,kg) VALUES('PLA','白色',1.2),('PETG','黑色',0.35)")    # 升级前的耗材数据
c0.commit(); c0.close()
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
import app as A
from core import inventory as inv, materials, db, config, stockcalc
c=A.app.test_client(); E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+=(not b)
def qty_of(code): return inv.get_item(code)["qty"]
def mat_g(m,col):
    r=db.conn().execute("SELECT kg FROM inventory WHERE material=? AND color=?",(m,col)).fetchone(); return (r["kg"] if r else 0)*1000

# ---- 1. 迁移：耗材模块现有的数据都有对应物品，数量一致
rows=db.conn().execute("SELECT material,color,kg FROM inventory").fetchall()
fil=inv.items("filament")
ok(len(rows)>0 and len(fil)>=len(rows), f"migrated {len(rows)} filament rows → {len(fil)} items")
bad=[(r["material"],r["color"]) for r in rows if abs(next(i["qty"] for i in fil if i["material"]==r["material"].upper() and i["color"]==r["color"])-r["kg"]*1000)>0.6]
ok(not bad, f"quantities match {bad}")
ok(all(m["kind"]=="opening" for m in inv.moves(kind="opening")) and inv.moves(kind="opening"), "opening moves")

# ---- 2. 物品档案
r=c.post("/api/inv/items",json={"name_zh":"0.4 喷嘴 硬化钢","name_th":"หัวฉีด 0.4","category":"part","unit":"个","brand":"Bambu","reorder_point":2,"location":"A架2层"}).get_json()
noz=r["item"]; ok(noz["code"]=="BJ0001" and noz["qty"]==0, f"new part {noz['code']}")
box=c.post("/api/inv/items",json={"name_zh":"纸箱 15×15×15","category":"pack","unit":"个","reorder_point":20}).get_json()["item"]
ok(box["code"]=="BC0001", "pack item")
f=c.post("/api/inv/items",json={"name_zh":"PLA 天蓝","category":"filament","material":"pla","color":"天蓝色","loss_rate":0.08}).get_json()["item"]
ok(f["code"]=="F-PLA-SB" and f["unit"]=="g" and f["color_code"]=="SB", f"filament item {f['code']}")
ok("已经有了" in c.post("/api/inv/items",json={"name_zh":"x","category":"filament","material":"PLA","color":"天蓝色"}).get_json().get("error",""), "dup filament rejected")
ok("不能改" in c.post("/api/inv/items",json={"id":f["id"],"color":"红色"}).get_json().get("error",""), "filament color locked")

# ---- 3. 单据：采购入库（加权平均）、领用、报废、调整、作废
d=c.post("/api/inv/docs",json={"kind":"purchase","lines":[{"item_id":noz["id"],"qty":5,"unit_cost":120},{"item_id":box["id"],"qty":100,"unit_cost":5}],"note":"Shopee 买"}).get_json()
ok(d.get("ok") and d["doc"]["no"].startswith("RK") and len(d["doc"]["lines"])==2, f"purchase doc {d.get('doc',{}).get('no')} {d.get('error')}")
c.post("/api/inv/docs",json={"kind":"purchase","lines":[{"item_id":noz["id"],"qty":5,"unit_cost":180}]})
it=inv.get_item(noz["id"]); ok(it["qty"]==10 and abs(it["avg_cost"]-150)<1e-6, f"weighted avg {it['avg_cost']}")
r=c.post("/api/inv/docs",json={"kind":"issue","lines":[{"item_id":noz["id"],"qty":2}],"printer":"P1S-1","note":"换喷嘴"}).get_json()
ok(r["ok"] and qty_of("BJ0001")==8, "issue")
ok("不够出" in c.post("/api/inv/docs",json={"kind":"issue","lines":[{"item_id":noz["id"],"qty":99}]}).get_json().get("error",""), "issue more than stock rejected")
ok("原因" in c.post("/api/inv/docs",json={"kind":"scrap","lines":[{"item_id":box["id"],"qty":3}]}).get_json().get("error",""), "scrap needs reason")
c.post("/api/inv/docs",json={"kind":"scrap","lines":[{"item_id":box["id"],"qty":3}],"note":"受潮"})
adj=c.post("/api/inv/docs",json={"kind":"adjust","lines":[{"item_id":box["id"],"qty":-2}],"note":"点错"}).get_json()["doc"]
ok(qty_of("BC0001")==95, f"scrap+adjust {qty_of('BC0001')}")
v=c.post(f"/api/inv/docs/{adj['id']}/void").get_json(); ok(v["doc"]["status"]=="void" and qty_of("BC0001")==97, "void reverses")
ok("只有已生效" in c.post(f"/api/inv/docs/{adj['id']}/void").get_json().get("error",""), "void twice rejected")

# ---- 4. 耗材：采购（按卷）→ 料卷也有；领用 → 料卷扣；两边一直一致
r=c.post("/api/inv/docs",json={"kind":"purchase","lines":[{"item_id":f["id"],"rolls":2,"net_g":1000,"unit_cost":0.6,"brand":"Bambu"}]}).get_json()
ok(r.get("ok") and qty_of(f["code"])==2000 and mat_g("PLA","天蓝色")==2000, f"filament purchase {qty_of(f['code'])} / {mat_g('PLA','天蓝色')} {r.get('error')}")
sp=materials.spools("PLA","天蓝色","active"); ok(len(sp)==2 and sp[0]["brand"]=="Bambu", "spools created")
ok(abs(inv.get_item(f["code"])["avg_cost"]-0.6)<1e-6, "filament avg cost from purchase")
c.post("/api/inv/docs",json={"kind":"issue","lines":[{"item_id":f["id"],"qty":150}],"note":"试打"})
ok(qty_of(f["code"])==1850 and mat_g("PLA","天蓝色")==1850, "filament issue synced")
# 老的耗材页面操作也记流水
materials.receive("PLA","天蓝色",1,1000,"eSun",500,"t")
ok(qty_of(f["code"])==2850, "old receive → inventory")
it=inv.get_item(f["code"]); ok(abs(it["avg_cost"]-(1850*0.6+1000*0.5)/2850)<1e-6, f"avg after old receive {it['avg_cost']}")
s0=materials.spools("PLA","天蓝色","active")[0]
materials.spool_action(s0["code"],"weigh","t",grams=800)
ok(abs(qty_of(f["code"])-mat_g("PLA","天蓝色"))<0.01, "weigh keeps in sync")

# ---- 5. 打印扣料：产品克数 + 损耗率（这个耗材 8%），失败整盘算损耗
before=qty_of(f["code"])
inv.consume_production("PLA","天蓝色",100,"打印完成 批次#1","t","0","run:1")
ok(abs(before-qty_of(f["code"])-108)<0.01, f"consume with loss {before-qty_of(f['code'])}")
mv=inv.moves(item_id=f["id"],limit=2); ok({m["kind"] for m in mv}=={"production","loss"}, "production + loss moves")
inv.consume_production("PLA","天蓝色",40,"打印失败 批次#2","t","0","run:2",failed=True)
ok(inv.moves(item_id=f["id"],limit=1)[0]["kind"]=="fail", "fail move")
ok(abs(qty_of(f["code"])-mat_g("PLA","天蓝色"))<0.01, "still in sync after printing")

# ---- 6. 盘点：草稿 → 填数 → 确认（按确认时的账面数算差异）
st=c.post("/api/inv/stocktake",json={"category":"part"}).get_json()["doc"]
ok(st["status"]=="draft" and st["lines"][0]["expected"]==8, "stocktake draft")
lid=st["lines"][0]["id"]
c.post(f"/api/inv/stocktake/{st['id']}/save",json={"counts":{str(lid):7}})
r=c.post(f"/api/inv/stocktake/{st['id']}/confirm").get_json()
ok(r["ok"] and qty_of("BJ0001")==7 and r["doc"]["status"]=="done", "stocktake confirm adjusts")
st2=c.post("/api/inv/stocktake",json={"category":"filament"}).get_json()["doc"]
ln=next(x for x in st2["lines"] if x["code"]==f["code"])
c.post(f"/api/inv/stocktake/{st2['id']}/save",json={"counts":{str(ln["id"]):1500}})
c.post(f"/api/inv/stocktake/{st2['id']}/confirm")
ok(abs(qty_of(f["code"])-1500)<0.6 and abs(mat_g("PLA","天蓝色")-1500)<0.6, f"filament stocktake {qty_of(f['code'])} {mat_g('PLA','天蓝色')}")

# ---- 7. 自动库存读库存管理
config.save_config({"stock_safety_g":50})
av=stockcalc.available(); ok(abs(av[("PLA","SB")]-(qty_of(f["code"])-50))<1, f"stockcalc uses inventory {av.get(('PLA','SB'))}")

# ---- 8. 支出统计 / 提醒
ex=c.get("/api/inv/expense?group=category").get_json()
cats={r["key"]:r for r in ex["rows"]}
ok("part" in cats and "filament" in cats and ex["total"]>0, f"expense by category {[(k,v['amount']) for k,v in cats.items()]}")
ok(abs(cats["part"]["amount"]-(2*150+1*150))<0.01, f"part expense = issue 2 + 盘亏 1 at avg 150 → {cats['part']['amount']}")
exk={r["key"]:r for r in c.get("/api/inv/expense?group=kind").get_json()["rows"]}
ok("loss" in exk and "fail" in exk and "production" in exk, "expense by kind")
exp=c.get("/api/inv/expense?group=printer").get_json()["rows"]; ok(any(r["key"]=="P1S-1" for r in exp), "expense by printer")
m=c.get("/api/inv/meta").get_json(); ok(any(a["code"]=="BJ0001" for a in m["alerts"])==False and m["overview"]["part"]["items"]==1, "meta overview")
c.post("/api/inv/items",json={"id":noz["id"],"reorder_point":10}); ok(any(a["code"]=="BJ0001" for a in c.get("/api/inv/meta").get_json()["alerts"]), "low stock alert")

# ---- 9. 权限：生产员工能领用，不能入库 / 调整 / 确认盘点
db.create_user("boss","secret1","owner","老板","zh"); db.create_user("pp","pass123","production","PP","th")
s=A.app.test_client(); s.post("/api/auth/login",json={"username":"pp","password":"pass123"})
ok(s.get("/api/inv/items").status_code==200, "production can view")
ok(s.post("/api/inv/docs",json={"kind":"issue","lines":[{"item_id":box["id"],"qty":1}]}).get_json().get("ok"), "production can issue")
ok(s.post("/api/inv/docs",json={"kind":"purchase","lines":[{"item_id":box["id"],"qty":1}]}).status_code==403, "production cannot purchase")
ok(s.post("/api/inv/docs",json={"kind":"adjust","lines":[{"item_id":box["id"],"qty":1}],"note":"x"}).status_code==403, "production cannot adjust")
st3=s.post("/api/inv/stocktake",json={"category":"pack"}).get_json()["doc"]
ok(s.post(f"/api/inv/stocktake/{st3['id']}/confirm").status_code==403, "production cannot confirm stocktake")
print("ERRORS", E)
