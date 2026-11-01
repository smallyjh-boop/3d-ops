# v2.54：旧「3D选品工具」对接移除：接口 404、catalog 密钥没有权限、旧推过来的产品照常读 / 改规格 / 过上架检查
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, time
D=T+"/v254"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T+"/v13", D)
import sqlite3; c0=sqlite3.connect(D+"/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
import app as A
from core import integrations, config, store, specs, codes, lazada_template, pricing
config.save_config({"review_enabled":False, "curator_api_key":"OLDKEY"})
c=A.app.test_client(); E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+=(not b)

# ---- 接口没了
for m,u in (("post","/api/v1/catalog/products"),("post","/api/v1/catalog/products/3DP0001/files"),("put","/api/v1/catalog/products/3DP0001/variants"),
            ("get","/api/curator"),("post","/api/curator"),("post","/api/curator/test")):
    r=getattr(c,m)(u,json={},headers={"Authorization":"Bearer "+integrations.create_key("full","full")} if u.startswith("/api/v1/") else {})
    ok(r.status_code in (404,405,410), f"{m.upper()} {u} gone ({r.status_code})")
# 已有的「建产品」密钥：行还在、不崩、没有任何权限；也不能再新建
_cx=integrations.create_key("选品工具-建产品","catalog"); H={"Authorization":"Bearer "+_cx}
ok(any(k.get("scope")=="catalog" for k in integrations.list_keys()), "catalog key row kept in list")
for m,u in (("post","/api/v1/catalog/products"),("get","/api/v1/categories"),("get","/api/v1/skus"),("get","/api/v1/ping")):
    r=getattr(c,m)(u,headers=H,json={}) if m=="post" else getattr(c,m)(u,headers=H)
    ok(r.status_code in (403,404,410), f"catalog key grants nothing: {m} {u} -> {r.status_code}")
# 读密钥照常用 /api/v1/categories、/api/v1/skus
rk=integrations.create_key("只读","read"); HR={"Authorization":"Bearer "+rk}
cats=c.get("/api/v1/categories",headers=HR).get_json()
ok(cats["ok"] and cats["categories"] and "groups" in cats, "GET /api/v1/categories still works")
ok(c.get("/api/v1/skus",headers=HR).status_code==200, "GET /api/v1/skus still works")
from modules.link import module as linkm

# ---- 旧选品工具推过来的产品（按旧接口建出来的样子）
V=[{"spec_id":"v7-1","position":1,"kind":"size","name_zh":"小号","name_th":"เล็ก","name_en":"S","filament_grams":28,"print_minutes":95},
   {"spec_id":"v7-2","position":2,"kind":"size","name_zh":"大号","name_th":"ใหญ่","name_en":"L","is_default":True,"filament_grams":86,"print_minutes":240}]
sp,_w=specs.parse(V)
pid=store.new_id("3DP"); p=store.blank_product(pid)
p.update(name_zh="猫咪摆件", material="PLA", draft=True)
p["copy"]={"title_zh":"可爱猫咪桌面摆件","title_th":"ตุ๊กตาแมวตั้งโต๊ะ น่ารัก"}
p["curator_listing"]={"version":1,"method":"ai","title_th":"ตุ๊กตาแมวตั้งโต๊ะ"}
p["category"]={"id":cats["categories"][0]["id"],"cat_id":cats["categories"][0].get("lazada_cat_id") or "","status":"manual"}
specs.build_rows(p, sp)
p["source"]={"source":"3d-curator","source_id":"77","platform":"MakerWorld","license_verified":True,"imported_at":time.time()}
# 旧同步留下的「选品工具删了、等人确认」
p["specs"].append(dict(p["specs"][0], spec_id="v7-9", name_zh="狗狗款", status="removed_pending", reasons=["选品工具里已经删除"], rcodes=[["spec.r.removed",""]]))
p["variants"].append(dict(p["variants"][0], spec_id="v7-9", opt2_zh="狗狗款", sku=""))
codes.ensure_skus(config.load_config(), p); store.save(p)
linkm._migrate_v254()                       # 升级时跑一次
p=store.load(pid)
ok(p["source"]["source"]=="3d-curator" and p["curator_listing"]["method"]=="ai" and p["draft"], "product data kept (source / curator_listing / draft)")
ok(next(x for x in p["specs"] if x["spec_id"]=="v7-9")["status"]=="ok", "removed_pending cleared by migration")
r=c.get(f"/api/products/{pid}"); ok(r.status_code==200 and r.get_json()["id"]==pid, "legacy product loads via API")
# 规格随便改：改名（规格记录跟着改、数据不丢）、加规格
q=r.get_json()
for v in q["variants"]:
    if v["opt2_zh"]=="小号": v["opt2_zh"]="迷你"
q["variants"].append(dict(q["variants"][0], opt2_zh="加大", sku=""))
r=c.post(f"/api/products/{pid}", json=q); ok(r.status_code==200, f"edit specs {r.status_code} {r.get_data(as_text=True)[:120]}")
p=store.load(pid); sm={x["name_zh"]:x for x in p["specs"]}
ok("迷你" in sm and sm["迷你"]["spec_id"]=="v7-1" and sm["迷你"]["grams"]==28 and "小号" not in sm and "加大" in sm, f"rename in place + add {sorted(sm)}")
ok(all(v["spec_id"]==sm[v["opt2_zh"]]["spec_id"] for v in p["variants"]), "variant spec_id follows name")
# ---- 上架检查：没有因为旧工具遗留的规格问题
cfg=config.load_config()
for v in p["variants"]: v["opt1_zh"]=v["opt1_zh"] or "白色"
p["variation1_name_zh"]="颜色"; store.save(p)
e,w=lazada_template.check_product(p, pricing.price_product(cfg,p), None, cfg)
bad=[x for x in e+w if "规格" in x and ("待确认" in x or "已经删除" in x or "选品工具" in x)]
ok(not bad, f"上架检查 no leftover spec problems {bad}")
print("ERRORS", E)
