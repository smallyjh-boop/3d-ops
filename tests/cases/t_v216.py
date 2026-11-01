# v2.16：规格（spec_id / 待确认）、随机颜色、按耗材自动算库存、库存待同步、随机颜色接单自动选色
# v2.54：旧「3D选品工具」接口移除了——这里的产品用 legacy_product() 按旧接口建出来的样子直接建（测旧数据还能用）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, time
D=T+"/v216"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T+"/v13", D)
import sqlite3; c0=sqlite3.connect(D+"/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
import app as A
from core import integrations, config, store, specs, stockcalc, materials, codes, production
config.save_config({"review_enabled":False})
read_key=integrations.create_key("只读","read")
c=A.app.test_client(); E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+=(not b)
HR={"Authorization":"Bearer "+read_key}
cats=c.get("/api/v1/categories",headers=HR).get_json()["categories"]

# ---- 1. 建档：v1.8 规格字段
def legacy_product(V, cat):
    """按旧选品工具接口（已移除）建出来的样子直接建一个产品：草稿、规格、source、curator_listing、ip_risk。"""
    sp,_w=specs.parse(V)
    pid=store.new_id("3DP"); p=store.blank_product(pid)
    p.update(name_zh="猫咪摆件", material="PLA", draft=True)
    p["copy"]={"title_zh":"可爱猫咪桌面摆件","title_th":"ตุ๊กตาแมวตั้งโต๊ะ น่ารัก ของขวัญ"}
    p["curator_listing"]={"version":1,"method":"ai","title_th":"ตุ๊กตาแมวตั้งโต๊ะ","ip_risk":[{"term":"Hello Kitty","reason":"角色"}]}
    p["ip_risk"]={"items":[{"term":"Hello Kitty","reason":"角色"}],"status":"pending","at":time.time()}
    p["category"]={"id":cat["id"],"cat_id":cat.get("lazada_cat_id") or "","status":"manual"}
    specs.build_rows(p, sp); specs.package_from_specs(p)
    p["source"]={"source":"3d-curator","source_id":"77","platform":"MakerWorld","license_verified":True,"imported_at":time.time()}
    p["source_colors"]=["粉色"]
    codes.ensure_skus(config.load_config(), p)
    store.save(p)
    return pid
V=[{"spec_id":"v7-1","position":1,"kind":"size","name_zh":"小号 8cm","name_th":"ขนาดเล็ก 8 ซม.","name_en":"S","size_mm":[62,55,80],
    "filament_grams":28,"print_minutes":95,"recognize":{"method":"rule","confidence":0.95,"evidence":"cat_small.3mf"}},
   {"spec_id":"v7-2","position":2,"kind":"size","name_zh":"大号 12cm","name_th":"ขนาดใหญ่ 12 ซม.","name_en":"L","is_default":True,
    "filament_grams":86,"print_minutes":240,"recognize":{"method":"rule","confidence":0.95}},
   {"spec_id":"v7-3","position":3,"kind":"bundle","name_zh":"小号·2 件装","name_th":"ขนาดเล็ก·แพ็ค 2 ชิ้น","name_en":"S2","pack_qty":2,
    "filament_grams":56,"print_minutes":180,"recognize":{"method":"ai","confidence":0.72,"evidence":"print two"}}]
V[2]["parts"]=3; V[2]["size_mm"]=[62,55,80]; V[2]["recognize"]["evidence"]="print two；多零件，尺寸为最大零件"
pid=legacy_product(V, cats[0])
p=store.load(pid)
ok(p["source"]["source"]=="3d-curator" and p["draft"], "legacy product loads")

ok([s["spec_id"] for s in p["specs"]]==["v7-1","v7-2","v7-3"] and [v["spec_id"] for v in p["variants"]]==["v7-1","v7-2","v7-3"], "specs + rows by spec_id")
ok(p["specs"][2]["status"]=="review" and p["specs"][0]["status"]=="ok" and p["source_colors"]==["粉色"], f"low confidence → review {p['specs'][2]['reasons']}")
ok(p["curator_listing"]["method"]=="ai" and p["source"]["platform"]=="MakerWorld", "old listing + source kept")
ok(p["ip_risk"]["status"]=="pending" and p["specs"][2]["size_ref"], "ip risk pending + size_ref")
ok(p["package_status"]=="check" and p["package_src"]=="spec_ref" and p["package"]["length"]==10.0, f"package from spec sizes {p['package']}")
ok(p["variants"][0]["sku"]==f"{pid}-S" and p["variants"][2]["sku"]==f"{pid}-S2", f"sku uses name_en {[v['sku'] for v in p['variants']]}")
# 颜色词 / 超过 12 个 / 重复 spec_id
sp,w=specs.parse([{"spec_id":"a","name_zh":"白色大号","name_th":"ใหญ่"}]); ok(sp[0]["status"]=="review" and w, "color word → review")
sp,w=specs.parse([{"spec_id":f"x{i}","name_zh":f"款{i}","name_th":"x"} for i in range(15)]); ok(len(sp)==12 and any("12" in x for x in w), "max 12")
try: specs.parse([{"spec_id":"a","name_zh":"a"},{"spec_id":"a","name_zh":"b"}]); ok(False,"dup spec_id")
except specs.SpecError: ok(True,"dup spec_id rejected")
sp,w=specs.parse([{"name_zh":"大号","name_th":"ใหญ่"}]); ok(sp[0]["spec_id"]=="auto-大号" and w, "legacy no spec_id")
ok(specs.color_words("大号")==[] and specs.color_words("白色款") and specs.color_words("Black edition"), "color word detect")

# ---- 2. 加颜色（模拟编辑页：白色 + 粉色 + 随机颜色）、SKU、待确认挡导出
cfg=config.load_config()
ok(codes.find_color(cfg,"随机颜色")[1]=="RND" and codes.is_random(cfg,"สีสุ่ม (คละสี)"), "random color in table")
p=store.load(pid)
rows=[]
for col in ("白色","粉色","随机颜色"):
    for v in [x for x in p["variants"] if not x.get("opt1_zh")] or []:
        pass
for col in ("白色","粉色","随机颜色"):
    for s in p["specs"]:
        base=next(v for v in p["variants"] if v["spec_id"]==s["spec_id"])
        rows.append(dict(base,opt1_zh=col,sku=""))
p["variants"]=rows; p["variation1_name_zh"]="颜色"
r=c.post(f"/api/products/{pid}",json=p); ok(r.status_code==200, f"save colors {r.status_code}")
p=store.load(pid)
skus=[v["sku"] for v in p["variants"]]
ok(f"{pid}-RND-L" in skus and f"{pid}-WH-S" in skus and len(skus)==9, f"skus {skus}")
ok(p["specs"][2]["status"]=="review", "client save keeps server specs")
chk=c.post(f"/api/products/{pid}/check").get_json() if c.post(f"/api/products/{pid}/check").status_code==200 else {}
from core import lazada_template, pricing
e,w=lazada_template.check_product(p, pricing.price_product(cfg,p), None, cfg)
ok(any("待确认" in x for x in e), f"review blocks export {[x for x in e if '规格' in x]}")
ok(any("侵权待确认" in x for x in e), "ip risk blocks export")
r=c.post(f"/api/products/{pid}/ip-risk",json={"action":"ok"}).get_json(); ok(r["ok"] and r["product"]["ip_risk"]["status"]=="ok", "ip risk confirmed")
r=c.post(f"/api/products/{pid}/specs/v7-3/ok").get_json(); ok(r["ok"] and r["product"]["specs"][2]["status"]=="ok", "confirm spec")
p=store.load(pid); e,w=lazada_template.check_product(p, pricing.price_product(cfg,p), None, cfg)
ok(not any("待确认" in x for x in e), f"no review/ip error after confirm {[x for x in e if '待确认' in x]}")
s=[k for k in c.get("/api/v1/skus",headers=HR).get_json()["skus"] if k["product_id"]==pid]
rnd=[k for k in s if k["random_color"]]
ok(len(rnd)==3 and rnd[0]["color_code"]=="RND" and all(k["spec_id"] for k in s) and s[0]["spec_status"]=="ok" and "stock" in s[0], f"v1 skus fields {s[0]}")

# ---- 3. v2.54：规格在 ERP 里随便改（不再由选品工具管理）：改名、改克数、删规格
p=store.load(pid)
p["variants"]=[v for v in p["variants"] if v["spec_id"]!="v7-3"]
for v in p["variants"]:
    if v["spec_id"]=="v7-1": v["opt2_zh"]="小号 10cm"; v["grams"]=30
r=c.post(f"/api/products/{pid}",json=p); ok(r.status_code==200, f"free spec edit {r.status_code} {r.get_data(as_text=True)[:100]}")
p=store.load(pid)
s1=next(x for x in p["specs"] if x["spec_id"]=="v7-1")
ok(s1["name_zh"]=="小号 10cm" and s1["size_mm"]==[62,55,80] and all(v["spec_id"]=="v7-1" for v in p["variants"] if v["opt2_zh"]=="小号 10cm"), f"spec renamed in place, data kept {s1['name_zh']}")
ok(len(p["variants"])==6, "6 rows after removing a spec")
# ---- 4. 旧的「选品工具删了」待确认状态（removed_pending）：升级时改成正常规格，不再提醒 / 不卡上架检查
p["specs"].append(dict(p["specs"][0], spec_id="v7-9", name_zh="狗狗款", status="removed_pending", reasons=["选品工具里已经删除"]))
p["exported_at"]=int(time.time()); store.save(p)
e,w=lazada_template.check_product(p, pricing.price_product(cfg,p), None, cfg); ok(not any("已经删除" in x for x in w+e), "removed_pending no longer warns")
from modules.link import module as linkm
linkm._migrate_v254(); p=store.load(pid)
ok(next(x for x in p["specs"] if x["spec_id"]=="v7-9")["status"]=="ok", "migration clears removed_pending")
r=c.post(f"/api/products/{pid}/specs/v7-9/delete?force=1").get_json(); ok(r["ok"], "delete leftover spec")
p=store.load(pid); ok(len(p["variants"])==6, "still 6 rows")
for m in ("post","put"):
    ok(getattr(c,m)(f"/api/v1/catalog/products/{pid}/variants" if m=="put" else "/api/v1/catalog/products",headers=HR,json={}).status_code in (403,404,410), f"old catalog {m} gone")

# ---- 5. 按耗材自动算库存
materials.set_stock("PLA","白色",0.5); materials.set_stock("PLA","粉色",0.05)
p=store.load(pid)
r=c.post(f"/api/products/{pid}/stock-auto",json={"mode":"on"}).get_json(); ok(r["auto"], "stock auto on (product)")
rows=c.get(f"/api/products/{pid}/stock").get_json()["rows"]
by={(x["color"],x["spec"]):x for x in rows}
avW=stockcalc.available()[("PLA","WH")]
ok(380<=avW<=450, f"white available = 500 - 50 safety - queued jobs {avW}")
wS=by[("白色","小号 10cm")]; ok(wS["stock"]==int(avW//(30*1.1)) and wS["auto"], f"white S {wS}")
ok(by[("粉色","小号 10cm")]["stock"]==0, f"pink low → 0 {by[('粉色','小号 10cm')]}")
rS=by[("随机颜色","小号 10cm")]; ok(rS["stock"]>=wS["stock"], f"random uses all colors {rS}")
wL=by[("白色","大号 12cm")]; ok(wL["stock"]==min(50,int(avW//(86*1.1))), f"white L {wL}")
config.save_config({"stock_low_mode":"real"}); stockcalc._cache["v"]=None
rows=stockcalc.compute(store.load(pid)); ok([x for x in rows if x["color"]=="粉色"][0]["stock"]==0, "pink 0g left after safety")
config.save_config({"stock_low_mode":"zero"})
st=stockcalc.stocks(store.load(pid)); ok(len(st)==6, "stocks for export")
# 关掉 → 回到手填 / 默认
c.post(f"/api/products/{pid}/stock-auto",json={"mode":"off"}); ok(stockcalc.compute(store.load(pid))[0]["stock"]==config.load_config()["default_stock"], "off → default stock")
c.post(f"/api/products/{pid}/stock-auto",json={"mode":"on"})

# ---- 6. 待同步到平台
stockcalc.mark_exported([store.load(pid)], "lazada", "t")
ok(c.get("/api/stock/pending").get_json()["items"]==[], "nothing pending after export")
materials.set_stock("PLA","白色",0.2)       # 白色少了 → 库存变化
pend=c.get("/api/stock/pending").get_json()["items"]
ok(any(x["sku"].startswith(pid+"-WH") for x in pend), f"pending after usage {[(x['sku'],x['last'],x['stock']) for x in pend]}")
r=c.post("/api/stock/mark-synced",json={"all":True}).get_json(); ok(r["marked"]==len(pend), "mark synced")
ok(c.get("/api/stock/pending").get_json()["items"]==[], "pending cleared")

# ---- 7. 随机颜色订单：接单时自动选颜色
materials.set_stock("PLA","白色",0.8)
p=store.load(pid); rsku=next(v["sku"] for v in p["variants"] if codes.is_random(cfg,v["opt1_zh"]) and v["spec_id"]=="v7-1")
A.orders_mod.upsert([{"platform":"lazada","order_no":"RND1","status":"待发货","buyer":"x","order_total":199,"items":[{"sku":rsku,"qty":2}]}], source="test")
production.generate("t")
oid=A.db.conn().execute("SELECT id FROM orders WHERE order_no='RND1'").fetchone()[0]
job=A.db.conn().execute("SELECT * FROM jobs WHERE order_id=?",(oid,)).fetchone()
ok(job and job["color"]=="白色" and "随机颜色" in (job["note"] or ""), f"random → white {dict(job) if job else None}")
col,why=stockcalc.pick_random_color("PLA",99999,p); ok(col=="白色" and "补货" in why, f"none enough → most left + warn {why}")
print("ERRORS", E)
