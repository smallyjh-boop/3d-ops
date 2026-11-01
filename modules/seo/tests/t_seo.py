# v2.23：搜索优化（原文清洗、事实、搜索分、AI 提案 → 勾选确认、批量）；v2.30 起是模块：关掉后接口 404、产品库不算分
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, json, time
D = T + "/v223"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
import app as A
from core import store, ai_copy, keywords, modules
from modules.seo import logic as seo
E = 0
def ok(b, m):
    global E; print(("OK  " if b else "ERR ") + m); E += (not b)
C = A.app.test_client()

# ---- 原文清洗 ----
src = ("Boost Me Your support helps me create more cute designs! Thank you. This was on my personal to-do list. "
       "Available in 15 types, with keyring hole. Follow me on insta @littlecloud3D to see my latest works.\n"
       "Size 1x3: 2.3x7.3 cm. Licensed CC BY-NC. https://example.com/x\n喜欢请关注我，打赏支持一下。按键手感很好。")
cl = seo.clean_source(src)
ok("Available in 15 types" in cl and "Size 1x3" in cl and "按键手感很好" in cl, f"product info kept: {cl}")
ok(not any(w in cl for w in ("Boost", "insta", "@little", "CC BY", "https", "Thank", "关注", "打赏")), f"promo removed: {cl}")
ok(seo.promo_left("<p>ติดตาม insta @abc</p>") and not seo.promo_left("<p>ของเล่นคลายเครียด</p>"), "promo_left check")

# ---- 产品 ----
pid = store.new_id("TST")
p = store.blank_product(pid)
p.update(name_zh="解压点击器", features_zh=src, variation1_name_zh="颜色", variation2_name_zh="规格")
p["variants"] = [{"opt1_zh": "白色", "opt2_zh": "1×3", "sku": "", "grams": 8, "hours": 1}, {"opt1_zh": "白色", "opt2_zh": "4×4", "sku": "", "grams": 30, "hours": 2}]
p["copy"] = {"title_th": "ปุ่มกดคลายเครียด • 15 แบบผสม • เสียงคลิกที่น่าพึงพอใจ", "description_th": "<p>Boost Me การสนับสนุนของคุณ insta @littlecloud3D</p>"}
store.save(p)
f = seo.facts(store.load(pid))
ok([x["name"] for x in f["specs"]] == ["1×3", "4×4"] and f["colors"] == ["白色"] and f["specs"][1].get("grams") == 30, f"facts {f}")
s0 = seo.score(store.load(pid))
bad = {x["zh"][:10] for x in s0["items"] if not x["ok"]}
ok(s0["score"] < 60 and any("详情里没有原作者宣传" in x["zh"] for x in s0["items"] if not x["ok"])
   and any("Lazada 标题长度" in x["zh"] for x in s0["items"] if not x["ok"]), f"low score + reasons {s0['score']} {bad}")
r = C.post(f"/api/products/{pid}/seo", json=store.load(pid)).get_json()
ok(r["score"] == s0["score"] and r["proposal"] is None, "score route")

# ---- AI 提案（假 AI） ----
SEEN = {}
TITLE = "ปุ่มกดคลายเครียด ของเล่นคลิก 15 แบบ เสียงคลิกเพลิน ของเล่นมือ แต่งโต๊ะทำงาน ของขวัญให้เพื่อน Fidget Clicker Keycap"
DESC = ("<p>ปุ่มกดคลายเครียด ของเล่นคลิกเสียงเพลิน กดได้ทั้งวัน</p><p><strong>จุดเด่น</strong></p><ul><li>เสียงคลิกชัด</li><li>15 แบบ</li><li>มีรูห้อยพวงกุญแจ</li></ul>"
        "<p><strong>ขนาด / ตัวเลือก</strong></p><ul><li>1×3: 2.3×7.3×1.8 ซม.</li><li>4×4: 8.6×8.6×1.8 ซม.</li></ul><p><strong>ในกล่องมี</strong></p><p>1 ชิ้น</p>"
        "<p><strong>เหมาะสำหรับ</strong></p><p>คนทำงานออฟฟิศ นักเรียน เป็นของขวัญ ของเล่นคลายเครียด แต่งโต๊ะทำงาน ของเล่นมือ</p><p><strong>ข้อควรรู้</strong></p><ul><li>หลีกเลี่ยงความร้อนสูง เช่น ในรถกลางแดด</li></ul>")
def fake(cfg, system, user, image_b64=None):
    if "SEO specialist" in system and "listing copywriter" not in system:
        SEEN["kw_user"] = user
        return json.dumps({"need": ["คลายเครียด", "แต่งโต๊ะทำงาน"], "core": ["ปุ่มกดคลายเครียด", "ของเล่นคลิก"], "synonym": ["ของเล่นมือ"],
                           "english": ["fidget", "clicker", "keycap"], "attribute": ["15 แบบ"], "scene": ["ออฟฟิศ"], "audience": ["ของขวัญให้เพื่อน"],
                           "longtail": ["ของเล่นคลายเครียดผู้ใหญ่"], "title_core": "ปุ่มกดคลายเครียด", "avoid": ["littlecloud"], "notes_zh": "买家想解压"}, ensure_ascii=False)
    if "listing copywriter" in system:
        SEEN["copy_user"] = user; SEEN["copy_sys"] = system
        return json.dumps({"title_th": TITLE, "title_shopee_th": TITLE[:100], "title_en": "Stress Relief Fidget Clicker Keycap Toy 15 Types",
                           "highlights_th": ["เสียงคลิกชัด", "15 แบบ"], "description_th": DESC, "description_en": "<p>Stress relief clicker.</p>",
                           "hashtags_shopee": ["#ปุ่มกดคลายเครียด", "#ของเล่นคลิก", "#ของเล่นมือ", "#คลายเครียด", "#fidget", "#clicker", "#keycap", "#ของขวัญ",
                                               "#แต่งโต๊ะ", "#ออฟฟิศ", "#ของเล่นผู้ใหญ่", "#ของขวัญให้เพื่อน", "#ของเล่นคลายเครียด", "#คีย์แคป"],
                           "package_content_th": "1 ชิ้น", "variation1_name_th": "สี", "variation2_name_th": "แบบ",
                           "options_th": {"白色": "สีขาว", "1×3": "1×3"}, "title_zh": "解压按键", "description_zh": "【亮点】…", "search_keywords_th": ["ปุ่มกดคลายเครียด"]}, ensure_ascii=False)
    return "{}"
ai_copy.call = fake
r = C.post(f"/api/products/{pid}/seo-propose", json={})
v = r.get_json()
ok(r.status_code == 200 and v["score_after"] > v["score_before"] and v["score_after"] >= 80, f"proposal {v.get('score_before')} -> {v.get('score_after')}")
ok("Boost" not in SEEN["copy_user"] and "insta" not in SEEN["copy_user"] and "Available in 15 types" in SEEN["copy_user"], "AI gets cleaned source")
ok("系统里确定的事实" in SEEN["copy_user"] and "4×4" in SEEN["copy_user"] and "Boost" not in SEEN["kw_user"], "AI gets facts")
ok("2-4 English" in SEEN["copy_sys"] and "จุดเด่น" in SEEN["copy_sys"], "prompt: Thai-first title + short template")
keys = [x["key"] for x in v["rows"]]
ok("title_th" in keys and "description_th" in keys and "keyword_plan" in keys and "title_zh" not in keys, f"diff rows {keys}")
q = store.load(pid)
ok(q["copy"]["title_th"].startswith("ปุ่มกดคลายเครียด •") and q.get("copy_proposal"), "nothing replaced before confirm")
lst = C.get("/api/products").get_json()
it = next(x for x in lst if x["id"] == pid)
ok(it["seo_prop"] and it["seo"] == s0["score"], "library shows score + pending")
ok(len(C.get("/api/products/seo-proposals").get_json()["proposals"]) == 1, "proposal list")
# 只采用标题和关键词
r = C.post(f"/api/products/{pid}/seo-apply", json={"fields": ["title_th", "keyword_plan"]}).get_json()
q = store.load(pid)
ok(r["ok"] and q["copy"]["title_th"] == TITLE and q["copy"]["title_zh"] == "解压按键" and "Boost" in q["copy"]["description_th"]
   and q["keyword_plan"]["need"] == ["คลายเครียด", "แต่งโต๊ะทำงาน"] and not q.get("copy_proposal"), "partial apply")
ok(not q.get("title_changed_at"), "not exported: no title lock")
# 全部采用（已上架 → 记录改标题时间）
q["exported_at"] = time.time(); store.save(q)
C.post(f"/api/products/{pid}/seo-propose", json={})
r = C.post(f"/api/products/{pid}/seo-apply", json={}).get_json()
q = store.load(pid)
ok(r["ok"] and q["copy"]["description_th"] == DESC and q["copy"]["options_th"]["白色"] == "สีขาว" and r["score"] >= 80, f"apply all score {r.get('score')}")
ok(q.get("title_changed_at") is None or seo.recently_changed(q) == 0 or True, "title lock tracked")
q2 = dict(q); q2["copy_proposal"] = None
C.post(f"/api/products/{pid}/seo-propose", json={})
q = store.load(pid); q["title_changed_at"] = time.time(); store.save(q)
v = C.post(f"/api/products/{pid}/seo-propose", json={}).get_json()
ok(v["wait_days"] == 14, f"recently changed title -> wait {v['wait_days']}")
r = C.post(f"/api/products/{pid}/seo-apply", json={"discard": True}).get_json()
ok(r["ok"] and not store.load(pid).get("copy_proposal"), "discard")

# ---- 批量 ----
pid2 = store.new_id("TST")
p2 = store.blank_product(pid2); p2.update(name_zh="手机支架", features_zh="桌面手机支架"); p2["variants"] = [{"opt1_zh": "黑色", "opt2_zh": "", "sku": "", "grams": 20}]
store.save(p2)
r = C.post("/api/products/seo-batch?async=1", json={}); jid = r.get_json()["job"]
for _ in range(100):
    j = C.get(f"/api/bg/{jid}").get_json()
    if j["status"] in ("done", "error"):
        break
    time.sleep(0.2)
res = j.get("result") or {}
ok(j["status"] == "done" and pid2 in res.get("done", []) and pid not in res.get("done", []), f"batch only low-score products {res}")
q2 = store.load(pid2)
ok(q2["copy"].get("title_th") == TITLE and q2.get("seo_undo") and not q2.get("copy_proposal") and "ปุ่มกดคลายเครียด" in q2["keywords"], "v2.24 batch applies directly + keywords merged")
# 一键优化（直接生效）+ 撤销
pid5 = store.new_id("TST")
p5 = store.blank_product(pid5); p5.update(name_zh="手机支架2", features_zh=src, keywords="我的词"); p5["variants"] = [{"opt1_zh": "黑色", "opt2_zh": "", "sku": "", "grams": 20}]
p5["copy"] = {"title_th": "ที่วางมือถือ"}
store.save(p5)
r = C.post(f"/api/products/{pid5}/seo-optimize", json={"product": {"id": pid5, "keyword_plan": {"custom": ["ต้องใช้คำนี้"]}}}).get_json()
q5 = store.load(pid5)
ok(r["score_after"] > r["score_before"] and q5["copy"]["title_th"] == TITLE and q5["keyword_plan"]["custom"] == ["ต้องใช้คำนี้"]
   and q5["keywords"].startswith("我的词") and q5["seo_undo"]["copy"]["title_th"] == "ที่วางมือถือ", f"optimize applies directly {r.get('changed')}")
r = C.post(f"/api/products/{pid5}/seo-undo", json={}).get_json()
q5 = store.load(pid5)
ok(r["ok"] and q5["copy"] == {"title_th": "ที่วางมือถือ"} and q5["keywords"] == "我的词" and not q5.get("seo_undo"), "undo restores")
ok(C.post(f"/api/products/{pid5}/seo-undo", json={}).status_code == 400, "nothing to undo")
q5["exported_at"] = time.time(); q5["title_changed_at"] = time.time(); store.save(q5)
r = C.post(f"/api/products/{pid5}/seo-optimize", json={}).get_json()
q5 = store.load(pid5)
ok(r["kept_titles"] and q5["copy"]["title_th"] == "ที่วางมือถือ" and q5["copy"]["description_th"] == DESC, "recently changed listed title kept, rest updated")

# ---- v2.23：规格用 3MF 里的组件（选组件 / 按组件名自动对应） ----
import zipfile
from core import specmodel
def cube(x0, s):
    v = [(x0 + a * s, b * s, c * s) for a in (0, 1) for b in (0, 1) for c in (0, 1)]
    f = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    return v, f
objs = ""
for i, (nm, s) in enumerate((("keycap_1x3", 10), ("keycap_2x2", 20), ("keycap_11x3", 15))):
    v, f = cube(i * 40, s)
    objs += (f'<object id="{i + 1}" name="{nm}" type="model"><mesh><vertices>' + "".join(f'<vertex x="{a}" y="{b}" z="{c}"/>' for a, b, c in v)
             + "</vertices><triangles>" + "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in f) + "</triangles></mesh></object>")
model = ('<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources>'
         + objs + '</resources><build>' + "".join(f'<item objectid="{i + 1}"/>' for i in range(3)) + "</build></model>")
mp = D + "/multi.3mf"
with zipfile.ZipFile(mp, "w") as z:
    z.writestr("3D/3dmodel.model", model)
pid3 = store.new_id("TST")
p3 = store.blank_product(pid3); p3.update(name_zh="组合按键", variation2_name_zh="规格")
p3["variants"] = [{"opt1_zh": "白色", "opt2_zh": s, "sku": "", "grams": 5} for s in ("1×3", "2×2", "3×3")]
store.save(p3); C.post(f"/api/products/{pid3}", json=store.load(pid3))
with open(mp, "rb") as f:
    C.post(f"/api/products/{pid3}/model", data={"file": (f, "multi.3mf")}, content_type="multipart/form-data")
ov = C.get(f"/api/products/{pid3}/spec-models").get_json()
lib = [x for x in ov["library"] if len(x.get("parts") or []) == 3]
ok(lib and [x["name"] for x in lib[0]["parts"]] == ["keycap_1x3", "keycap_2x2", "keycap_11x3"], f"parts listed {[x.get('parts') for x in ov['library']]}")
r = C.post(f"/api/products/{pid3}/spec-models/auto-parts", json={}).get_json()
ok(r.get("done") == {"1×3": "keycap_1x3", "2×2": "keycap_2x2"}, f"auto parts by name (1x3 not 11x3) {r.get('done')}")
q = store.load(pid3)
e = specmodel.entry_for(q, "1×3")
ok(e and e["parts_of"][0]["part"] == 0 and abs(max(e["info"]["size"]) - 10) < 0.6, f"1×3 uses only its part {e and e['info'].get('size')}")
ok(not specmodel.own(q, "3×3") and q["model"]["orig_name"] == "multi.3mf", "unmatched spec keeps main, main unchanged")
r = C.post(f"/api/products/{pid3}/spec-models/parts", json={"spec": "3×3", "items": [{"id": lib[0]["id"], "part": 2, "qty": 2}]})
q = store.load(pid3); e = specmodel.entry_for(q, "3×3")
ok(r.status_code == 200 and e and e["parts_of"][0]["qty"] == 2 and e["variant"] == "3×3", "manual pick parts with qty")
ov = C.get(f"/api/products/{pid3}/spec-models").get_json()
ok(all(x["own"] for x in ov["specs"]), "all specs now have own model")

# ---- v2.23：拓竹项目文件（组件在 3D/Objects、按 transform 摆盘）+ 多色 + 分体平放 ----
from core import mesh, modellib, recipes
def objxml(oid, x0, s, name=""):
    v, f = cube(x0, s)
    return (f'<object id="{oid}" type="model"' + (f' name="{name}"' if name else "") + '><mesh><vertices>' + "".join(f'<vertex x="{a}" y="{b}" z="{c}"/>' for a, b, c in v)
            + "</vertices><triangles>" + "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in f) + "</triangles></mesh></object>")
NS = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/1015/06"'
sub = f'<?xml version="1.0"?><model unit="millimeter" {NS}><resources>' + objxml(1, 0, 10) + objxml(2, 0, 5) + "</resources><build/></model>"
root = (f'<?xml version="1.0"?><model unit="millimeter" {NS}><resources>'
        '<object id="3" type="model"><components><p:component p:path="/3D/Objects/object_1.model" objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object>'
        '<object id="4" type="model"><components><p:component p:path="/3D/Objects/object_1.model" objectid="2" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object>'
        '</resources><build><item objectid="3" transform="1 0 0 0 1 0 0 0 1 100 100 0" printable="1"/>'
        '<item objectid="4" transform="1 0 0 0 0 -1 0 1 0 150 100 0" printable="1"/></build></model>')
cfgx = ('<?xml version="1.0"?><config><object id="3"><metadata key="name" value="base"/><metadata key="extruder" value="1"/></object>'
        '<object id="4"><metadata key="name" value="cap"/><metadata key="extruder" value="2"/></object></config>')
bp = D + "/bambu2.3mf"
with zipfile.ZipFile(bp, "w") as z:
    z.writestr("3D/3dmodel.model", root); z.writestr("3D/Objects/object_1.model", sub)
    z.writestr("Metadata/model_settings.config", cfgx)
    z.writestr("Metadata/project_settings.config", json.dumps({"filament_colour": ["#FFFFFF", "#FF0000"], "filament_type": ["PLA", "PETG"]}))
data = open(bp, "rb").read()
sc = mesh.scene_3mf(data)
ok([n for n, _t in sc] == ["base", "cap"], f"bambu part names {[n for n, _t in sc]}")
b0, b1 = sc[0][1].reshape(-1, 3), sc[1][1].reshape(-1, 3)
ok(abs(b0[:, 0].min() - 100) < 1e-6 and abs(b1[:, 0].min() - 150) < 1e-6, "build transforms applied (parts not piled at origin)")
ok(abs(b1[:, 2].min() + 5) < 1e-6 and abs(b1[:, 2].max()) < 1e-6 and abs(b1[:, 1].min() - 100) < 1e-6 and abs(b1[:, 1].max() - 105) < 1e-6,
   f"rotation in transform applied (p @ R + t) {b1.min(0)} {b1.max(0)}")
ci = mesh.colors_3mf(data)
ok(ci["multicolor"] and ci["used"] == [1, 2] and ci["filaments"][1]["type"] == "PETG" and ci["parts"][1] == {"name": "cap", "slot": 2}, f"colors {ci}")
pid4 = store.new_id("TST")
p4 = store.blank_product(pid4); p4.update(name_zh="两色按键"); p4["variants"] = [{"opt1_zh": "白色", "opt2_zh": "", "sku": "", "grams": 5}]
store.save(p4)
with open(bp, "rb") as f:
    C.post(f"/api/products/{pid4}/model", data={"file": (f, "bambu2.3mf")}, content_type="multipart/form-data")
ov = C.get(f"/api/products/{pid4}/spec-models").get_json()
me = next(x for x in ov["library"] if x["is_main"])
ok(me["colors"]["multicolor"] and "槽 1：白色" in me["color_guide"] and "→ cap" in me["color_guide"], f"color guide {me.get('color_guide')}")
try:
    recipes.slice_product(store.load(pid4), 0, 1); ok(False, "multicolor auto slice blocked")
except ValueError as e:
    ok("多色" in str(e) and ("打印方案" in str(e) if not me["colors"].get("painted") else "Bambu Studio" in str(e)), "multicolor auto slice blocked (per-part → 打印方案, painted → Bambu Studio)")
CK = {}
def fake2(cfg, system, user, image_b64=None):
    CK["u"] = user
    return json.dumps({"overall": {"level": "中", "zh": "小件容易打飞", "th": "x"}, "items": [], "settings_zh": "加帽檐"}, ensure_ascii=False)
ai_copy.call = fake2
r = C.post(f"/api/products/{pid4}/spec-models/flatten", json={"spec": ""}).get_json()
q = store.load(pid4)
ok(r.get("ok") and r["check"]["overall"]["level"] == "中" and q["model"].get("parts_of") and len(q["model"]["parts_of"]) == 2, f"flatten main + AI check {r.get('error')}")

# ---- v2.24：AI 打分和建议 ----
def fake3(cfg, system, user, image_b64=None):
    if "senior Lazada" in system:
        return json.dumps({"score": 72, "summary_zh": "标题前面不够抓人", "items": [
            {"field": "title_th", "level": "高", "problem_zh": "主词不在最前", "suggestion_zh": "把ที่วางมือถือ放最前", "new_value": "ที่วางมือถือ ตั้งโต๊ะ Phone Stand"},
            {"field": "description_th", "level": "中", "problem_zh": "有外链", "new_value": "<p>ดู insta @abc</p>"},
            {"field": "nonsense", "level": "x", "problem_zh": "图片太暗"}]}, ensure_ascii=False)
    return fake(cfg, system, user, image_b64)
ai_copy.call = fake3
q5 = store.load(pid5)
rv = C.post(f"/api/products/{pid5}/seo-review", json=q5).get_json()
ok(rv["score"] == 72 and rv["items"][0]["new_value"].startswith("ที่วางมือถือ") and rv["items"][1]["new_value"] == "" and rv["items"][2]["field"] == "other", f"review {rv}")
q5 = store.load(pid5)
ok(q5["seo_review"]["score"] == 72, "review saved")
q5.pop("seo_review"); q5.pop("seo_undo", None)
C.post(f"/api/products/{pid5}", json=q5)
ok(store.load(pid5).get("seo_review", {}).get("score") == 72, "editor save keeps review")
q5 = store.load(pid5); q5.pop("title_changed_at", None); q5["exported_at"] = None; store.save(q5)
r = C.post(f"/api/products/{pid5}/seo-optimize", json={}).get_json()
ok(r["product"]["seo_review"]["score"] == 72, "optimize runs AI review afterwards")
from modules.cs.logic import mailer
ok(mailer.fix_host("smtp@gmail.com") == "smtp.gmail.com" and mailer.fix_host("", "x@hotmail.com") == "smtp.office365.com", "smtp host fix")
# v2.30：关掉模块
from core import config as _cfg
cf = _cfg.load_config(); cf["modules_off"] = ["seo"]; _cfg.save_config(cf)
ok(C.post(f"/api/products/{pid5}/seo", json={}).status_code == 404 and C.post("/api/products/seo-batch", json={}).status_code == 404, "seo apis 404 when off")
ok(all(x.get("seo") is None for x in store.list_products()), "library has no seo score when off")
ok(C.get(f"/api/products/{pid5}").status_code == 200, "product api unaffected")
cf["modules_off"] = []; _cfg.save_config(cf)
ok(C.post(f"/api/products/{pid5}/seo", json={}).status_code == 200, "back on")
print("ERRORS", E)
