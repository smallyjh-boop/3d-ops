# v2.19.1：导出到平台的内容只能是泰文 / 英文；变体名称 / 选项泰文的兜底；常用物品清单
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, copy
D=T+"/vlang"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T+"/v13", D)
import sqlite3; c0=sqlite3.connect(D+"/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"]=D; sys.path.insert(0,APP)
import app as A
from core import store, codes, config, lang_guard, pricing, categories, shopee, lazada_template
from core import inventory as inv
E=0
def ok(b,m):
    global E; print(("OK  " if b else "ERR ")+m); E+=(not b)
cfg=config.load_config()
p={"copy":{},"variation1_name_zh":"颜色","variation2_name_zh":"规格","specs":[{"name_zh":"大号","name_th":"ใหญ่"}]}
ok(codes.variation_name_th(p,1)=="สี" and codes.variation_name_th(p,2)=="ตัวเลือก", "variation name defaults")
ok(codes.option_th(cfg,p,"黑色")=="สีดำ" and codes.option_th(cfg,p,"大号")=="ใหญ่" and codes.option_th(cfg,p,"荧光绿")=="荧光绿", "option_th fallbacks")
# 找一个能导出的产品，塞进中文看能不能拦住
pid=None
for it in store.list_products():
    q=store.load(it["id"]); cat=categories.get((q.get("category") or {}).get("id"))
    if cat: pid=it["id"]; break
q=store.load(pid); cat=categories.get(q["category"]["id"])
q["copy"]["title_th"]="ตุ๊กตาแมวน่ารัก ของขวัญ"; q["copy"]["description_th"]="<p>สวยงาม</p>"
q["variants"]=[dict(q["variants"][0],opt1_zh="黑色",opt2_zh="")]
pr=pricing.price_product(cfg,q)
ok(lang_guard.lazada_problems(q,pr,cfg,cat)==[], f"clean product passes {lang_guard.lazada_problems(q,pr,cfg,cat)}")
q2=copy.deepcopy(q); q2["copy"]["description_th"]="<p>可爱的猫</p>"; q2["variants"][0]["opt1_zh"]="奇怪色"
pb=lang_guard.lazada_problems(q2,pricing.price_product(cfg,q2),cfg,cat)
ok(any("泰文详情" in x for x in pb), f"chinese caught {pb}")
e,w=lazada_template.check_product(q2,pricing.price_product(cfg,q2),cat,cfg); ok(any("奇怪色" in x for x in e), f"option without thai blocked {e}")
sp=lang_guard.shopee_problems(q2,pricing.price_product(cfg,q2),cfg); ok(any("Shopee" in x for x in sp), f"shopee caught {sp}")
# 常用物品
n=inv.seed_presets(); ok(n>=35, f"presets added {n}")
ok(inv.seed_presets()==0, "presets idempotent")
fil={(i["material"],i["color"]) for i in inv.items("filament")}
ok(("PLA","白色") in fil and ("PLA","橙色") in fil and len([x for x in fil if x[0]=="PLA"])>=12, "12 PLA colors")
ok(len(inv.items("pack"))>=8 and len(inv.items("part"))>=8, "pack + part items")   # v2.35：纸箱改用邮政标准规格，不再预设 S/M/L
ok(all(i["name_th"] for i in inv.items()), "all items have thai names")
print("ERRORS", E)
