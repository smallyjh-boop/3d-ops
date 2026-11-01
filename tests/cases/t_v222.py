# v2.22：规格 ↔ 模型、英文文案、智能客服（学习、标签、跟进、邮件、实时翻译）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, json, time
D = T + "/v222"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
import app as A
from core import store, modellib, specmodel, print_files, recipes, config, db
E = 0
def ok(b, m):
    global E; print(("OK  " if b else "ERR ") + m); E += (not b)
C = A.app.test_client()
STL = T + "/cat.stl"

# ---- 规格 ↔ 模型 ----
pid = store.new_id("TST")
p = store.blank_product(pid); p.update(name_zh="规格测试", variation2_name_zh="规格")
p["variants"] = [{"opt1_zh": "白色", "opt2_zh": "大号", "sku": f"{pid}-WH-L", "grams": 10, "hours": 1},
                 {"opt1_zh": "黑色", "opt2_zh": "大号", "sku": f"{pid}-BK-L", "grams": 10, "hours": 1},
                 {"opt1_zh": "白色", "opt2_zh": "小号", "sku": f"{pid}-WH-S", "grams": 5, "hours": 1}]
store.save(p)
with open(STL, "rb") as f:
    C.post(f"/api/products/{pid}/model", data={"file": (f, "big.stl")}, content_type="multipart/form-data")
import numpy as np
from core import mesh
tris = mesh.load(STL) * 0.5
small = D + "/tmp_small.stl"; os.makedirs(os.path.dirname(small), exist_ok=True); mesh.write_stl(tris.astype(np.float32), small)
with open(small, "rb") as f:
    C.post(f"/api/products/{pid}/models", data={"files": (f, "small.stl")}, content_type="multipart/form-data")
ov = C.get(f"/api/products/{pid}/spec-models").get_json()
ok(ov["has_specs"] and [s["spec"] for s in ov["specs"]] == ["大号", "小号"] and ov["main"]["name"] == "big.stl", f"overview {ov['main']}")
small_e = next(x for x in ov["library"] if x["name"] == "small.stl")
ok(small_e["ok"] and not small_e["is_main"], "small model in library")
ov = C.post(f"/api/products/{pid}/spec-models", json={"spec": "小号", "entry_id": small_e["id"]}).get_json()
s2 = {s["spec"]: s for s in ov["specs"]}
ok(s2["小号"]["own"] and not s2["大号"]["own"] and s2["小号"]["name"] == "small.stl", "map 小号 → small.stl")
p = store.load(pid)
ok(specmodel.spec_of_sku(p, f"{pid}-WH-S") == "小号" and specmodel.own(p, "小号") and not specmodel.own(p, "大号"), "sku → spec")
v = specmodel.view(p, "小号")
ok(v["_model_path"].endswith("small.stl") and v["_spec"] == "小号", "view uses spec model")
g_big = recipes.geometry(specmodel.view(p, ""), recipes.get(p), 0)
g_small = recipes.geometry(v, recipes.get(v), 0)
ok(abs(g_small["size_mm"][0] - g_big["size_mm"][0] * 0.5) < 1, f"geometry from spec model {g_small['size_mm']} vs {g_big['size_mm']}")
r = C.post(f"/api/products/{pid}/spec-models/fill", json={"spec": "小号"}).get_json()
v2 = store.load(pid)["variants"][2]
ok(r["filled"] == 1 and v2["grams"] != 5 and v2["hours"] != 1 and v2.get("grams_src") == "est", f"fill grams from spec model {r['filled']} {v2}")
# 打印方案：规格自己的
rg = C.get(f"/api/products/{pid}/recipe?spec=小号").get_json()
ok(rg["spec"] == "小号" and any(x["own"] for x in rg["specs"]) and rg["model"]["spec_model"], "recipe view for spec")
C.post(f"/api/products/{pid}/recipe?spec=小号", json=dict(rg["recipe"], per_plate=6, spec="小号"))
p = store.load(pid)
ok(p["spec_recipes"]["小号"]["per_plate"] == 6 and (p.get("recipe") or {}).get("per_plate") != 6, "spec recipe saved separately")
ok(C.get(f"/api/products/{pid}/recipe?spec=大号").get_json()["spec"] == "", "spec without own model → main recipe")
mb = C.get(f"/api/products/{pid}/mesh?orient=bottom&spec=小号"); ml = C.get(f"/api/products/{pid}/mesh?orient=bottom")
ok(mb.status_code == 200 and ml.status_code == 200, "mesh endpoint per spec")
# 切片文件按规格分开
cfg = config.load_config()
if os.path.exists("/tmp/squashfs-root/orca-wrap"):
    cfg["orca_path"] = "/tmp/squashfs-root/orca-wrap"; config.save_config(cfg)
    r = C.post(f"/api/products/{pid}/recipe/slice", json={"printer": 0, "count": 1, "spec": "小号"}).get_json()
    ok(r.get("spec") == "小号", f"slice spec model → file spec {r.get('spec')}")
    fid = r["id"]
else:
    fid = print_files.add(small, "x.gcode", pid, "*", spec="小号", grams=3, hours=1)["id"] if False else None
    print("OK  (no Orca: slice skipped)")
db.conn().execute("UPDATE print_files SET status='reviewed' WHERE product_id=?", (pid,)); db.conn().commit()
names = [x.get("name") for x in config.load_config().get("printers")]
if fid:
    c_s = print_files.candidates(pid, f"{pid}-WH-S", names[0])
    c_l = print_files.candidates(pid, f"{pid}-WH-L", names[0])
    ok([x["id"] for x in c_s] == [fid] and fid not in [x["id"] for x in c_l], "production picks spec file only for that spec")
# 换模型 → 这个规格的切片退回草稿
big_e = next(x for x in C.get(f"/api/products/{pid}/spec-models").get_json()["library"] if x["name"] == "big.stl")
C.post(f"/api/products/{pid}/spec-models", json={"spec": "小号", "entry_id": ""})
ok(not specmodel.own(store.load(pid), "小号"), "unmap → main model")
if fid:
    ok(print_files.get(fid)["status"] == "draft", "spec files reset to draft on change")
ok(C.post(f"/api/products/{pid}/spec-models", json={"spec": "不存在", "entry_id": ""}).status_code == 400, "unknown spec rejected")


# ---- 变体检查：不能加重复的；规格模型以服务器为准 ----
q = store.load(pid)
C.post(f"/api/products/{pid}/spec-models", json={"spec": "小号", "entry_id": small_e["id"]})
q = store.load(pid)
stale = json.loads(json.dumps(q)); [v.pop("model_lib_id", None) for v in stale["variants"]]
r = C.post(f"/api/products/{pid}", json=stale)
ok(r.status_code == 200 and specmodel.own(store.load(pid), "小号"), "stale page cannot drop spec model")
q = store.load(pid); C.post(f"/api/products/{pid}/spec-models", json={"spec": "小号", "entry_id": ""})
r = C.post(f"/api/products/{pid}", json=q)                      # 页面还以为小号有自己的模型
ok(r.status_code == 200 and not specmodel.own(store.load(pid), "小号"), "stale page cannot re-add spec model")
q = store.load(pid); q["variants"].append(dict(q["variants"][0], sku=""))
r = C.post(f"/api/products/{pid}", json=q)
ok(r.status_code == 400 and "只能有一行" in r.get_json()["error"], "duplicate color+spec rejected")
q = store.load(pid); q["variants"].append(dict(q["variants"][0], opt2_zh="中号", sku=""))
ok(C.post(f"/api/products/{pid}", json=q).status_code == 200, "free spec allowed")
q = store.load(pid); q["specs"] = [{"spec_id": "s1", "name_zh": "大号"}, {"spec_id": "s2", "name_zh": "小号"}, {"spec_id": "s3", "name_zh": "中号"}]; store.save(q)
q = store.load(pid); q["variants"].append(dict(q["variants"][0], opt2_zh="特大号", sku=""))
r = C.post(f"/api/products/{pid}", json=q)
sp = {x["name_zh"]: x for x in store.load(pid)["specs"]}
ok(r.status_code == 200 and sp["特大号"].get("source") == "erp" and sp["特大号"].get("kept_local"), f"ERP spec added as local {r.get_json()}")
q = store.load(pid); [v.update(opt2_zh="超大号") for v in q["variants"] if v["opt2_zh"] == "大号"]           # v2.54：改名 → 规格记录跟着改名（不新增、不丢数据）
ok(C.post(f"/api/products/{pid}", json=q).status_code == 200 and "超大号" in {x["name_zh"] for x in store.load(pid)["specs"]} and "大号" not in {x["name_zh"] for x in store.load(pid)["specs"]}, "spec renamed in place")
q = store.load(pid); [v.update(opt2_zh="大号") for v in q["variants"] if v["opt2_zh"] == "超大号"]; C.post(f"/api/products/{pid}", json=q)
q = store.load(pid); q["variants"] = [v for v in q["variants"] if v["opt2_zh"] != "特大号"]
ok(C.post(f"/api/products/{pid}", json=q).status_code == 200 and not any(x["name_zh"] == "特大号" for x in store.load(pid)["specs"]), "removed local spec dropped")
q = store.load(pid); q["variants"].append(dict(q["variants"][0], opt2_zh="这个规格名字实在是太长了超过了二十个字的限制呀", sku=""))
r = C.post(f"/api/products/{pid}", json=q)
ok(r.status_code == 400 and "20" in r.get_json()["error"], "name length limit")
q = store.load(pid); base = q["variants"][0]
q["variants"] = [dict(base, opt1_zh=f"色{i}", opt2_zh=f"码{j}", sku="") for i in range(8) for j in range(7)]
r = C.post(f"/api/products/{pid}", json=q)
ok(r.status_code == 400 and "50" in r.get_json()["error"], "sku count limit")
q = store.load(pid); q["variants"][0]["opt2_zh"] = " 大号 "
ok(C.post(f"/api/products/{pid}", json=q).status_code == 200 and store.load(pid)["variants"][0]["spec_id"] == "s1", "spaces trimmed, spec_id set")
q = store.load(pid); q.pop("specs"); store.save(q)

# ---- v2.22.1：规格改名 → 模型、切片文件跟着走；切片文件按文件名认规格 ----
C.post(f"/api/products/{pid}/spec-models", json={"spec": "小号", "entry_id": small_e["id"]})
from core import db as _db, filemgr as _fm
_db.conn().execute("INSERT INTO print_files(product_id, sku, printer, filename, kind, per_plate, created_at, status, version, spec) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (pid, "", "*", "x.gcode.3mf", "3mf", 1, time.time(), "draft", 1, "小号")); _db.conn().commit()
q = store.load(pid)
for v in q["variants"]:
    if v["opt2_zh"] == "小号":
        v["opt2_zh"] = "迷你"
r = C.post(f"/api/products/{pid}", json=q)
q = store.load(pid)
ok(r.status_code == 200 and specmodel.own(q, "迷你") and specmodel.entry_for(q, "迷你")["id"] == small_e["id"], "rename keeps spec model")
ok(_db.conn().execute("SELECT COUNT(*) FROM print_files WHERE product_id=? AND spec='迷你'", (pid,)).fetchone()[0] >= 1
   and not _db.conn().execute("SELECT COUNT(*) FROM print_files WHERE product_id=? AND spec='小号'", (pid,)).fetchone()[0], f"rename moves slice files {[dict(x) for x in _db.conn().execute('SELECT id, spec, product_id FROM print_files WHERE product_id=?', (pid,))]}")
ok(_fm.slice_spec(q, f"{pid}_迷你_P1S.gcode.3mf") == "迷你" and _fm.slice_spec(q, f"{pid}_大号.gcode.3mf") == "", "slice file spec from filename")
ok(_fm.slice_spec(q, "a.gcode.3mf", next(v["sku"] for v in q["variants"] if v["opt2_zh"] == "迷你")) == "迷你", "slice file spec from sku")

# ---- v2.22.1：按模型自动加规格；给规格上传 / 换模型 ----
pid2 = store.new_id("TST")
p2 = store.blank_product(pid2); p2.update(name_zh="自动规格")
p2["variants"] = [{"opt1_zh": "白色", "opt2_zh": "", "sku": "", "grams": 10, "hours": 1}, {"opt1_zh": "黑色", "opt2_zh": "", "sku": "", "grams": 10, "hours": 1}]
store.save(p2)
with open(STL, "rb") as f:
    C.post(f"/api/products/{pid2}/model", data={"file": (f, "big.stl")}, content_type="multipart/form-data")
r = C.post(f"/api/products/{pid2}/spec-models/auto", json={})
ok(r.status_code == 400, "auto: nothing to add yet")
with open(small, "rb") as f:
    C.post(f"/api/products/{pid2}/models", data={"files": (f, "small.stl")}, content_type="multipart/form-data")
r = C.post(f"/api/products/{pid2}/spec-models/auto", json={}).get_json()
q = store.load(pid2)
names = specmodel.specs(q)
ok(len(r.get("added") or []) == 2 and len(names) == 2 and all(n.endswith("cm") for n in names) and len(q["variants"]) == 4, f"auto specs {r.get('added')} {names}")
ok(specmodel.own(q, names[1]) and not specmodel.own(q, names[0]) and all(v.get("sku") for v in q["variants"]), "auto spec mapped to its model, skus set")
with open(STL, "rb") as f:
    r = C.post(f"/api/products/{pid2}/models", data={"files": (f, "new_big.stl"), "spec": names[0]}, content_type="multipart/form-data")
q = store.load(pid2)
e = specmodel.entry_for(q, names[0])
ok(r.status_code == 200 and e and e["orig_name"] == "new_big.stl", "upload model for a spec maps it")

# ---- 英文 / 补全文案 ----
from core import ai_copy
CALLS = []
def fake(cfg, system, user, image_b64=None):
    CALLS.append(system[:30])
    if "listing expert" in system:
        return json.dumps({"title_en": "Cute Cat Figure Desk Decor", "description_en": "Cute cat.\nGreat gift.", "title_shopee_th": "ตุ๊กตาแมว",
                           "hashtags_shopee": ["แมว", "#ของขวัญ", "แมว", "decor"], "package_content_th": "1 x ตุ๊กตาแมว",
                           "variation1_name_th": "สี", "variation2_name_th": "ขนาด", "highlights_th": "น่ารัก\nของขวัญ",
                           "options_th": {"白色": "สีขาว", "大号": "ใหญ่", "小号": "<Thai>"}}, ensure_ascii=False)
    if "precise Thai e-commerce translator" in system:
        return json.dumps({"title_zh": "猫", "description_zh": "猫", "title_en": "Cat  Figure", "description_en": "<p>Cat</p>"})
    if "知识库整理员" in system:
        return json.dumps({"learn": True, "q": "ส่งต่างประเทศได้ไหม|ส่งไปลาวได้ไหม", "a": "ขออภัยค่ะ ตอนนี้ส่งเฉพาะในประเทศไทยค่ะ", "a_zh": "只发泰国国内", "tags": "物流"}, ensure_ascii=False)
    if system.startswith("你是翻译"):
        return json.dumps({"text": "สวัสดีค่ะ มีสินค้าพร้อมส่งค่ะ"}, ensure_ascii=False)
    if "客服主管" in system:
        return json.dumps({"points": ["批发询价多，建议补批发知识"]}, ensure_ascii=False)
    if "客服" in system:
        ctx = user
        if "ลาว" in ctx:
            return json.dumps({"lang": "th", "intent": "other", "summary_zh": "问能不能寄老挝", "reply": "ขอตรวจสอบก่อนนะคะ", "reply_zh": "我确认一下",
                               "needs_human": False, "confidence": 0.5, "unknown_question_zh": "能不能寄到老挝", "tags": ["海外 / 外地"]}, ensure_ascii=False)
        if "100 ชิ้น" in ctx:
            return json.dumps({"lang": "th", "intent": "wholesale", "summary_zh": "要 100 个做活动礼品", "reply": "ได้ค่ะ ส่งฟรีให้เลยค่ะ", "reply_zh": "可以，包邮",
                               "needs_human": False, "confidence": 0.95, "tags": ["批发", "企业团购", "乱写"], "lead": True, "lead_value_thb": 5000,
                               "needs": [{"type": "批发", "detail_zh": "100 个，月底前要"}], "follow_up_zh": "问一下数量和颜色定了没有"}, ensure_ascii=False)
        return json.dumps({"lang": "th", "intent": "product", "summary_zh": "问尺寸", "reply": "ขนาด 10 ซม. ค่ะ", "reply_zh": "10 厘米", "needs_human": False,
                           "confidence": 0.95, "tags": []}, ensure_ascii=False)
    return "{}"
ai_copy.call = fake
q = store.load(pid)
q["copy"] = {"title_th": "ตุ๊กตาแมวน่ารัก", "description_th": "<p>น่ารัก</p>"}
q["variants"][0]["opt1_zh"] = "白色"
miss, opts = ai_copy.missing_copy(q)
ok("title_en" in miss and "hashtags_shopee" in miss and "variation2_name_th" in miss and "白色" in opts and "title_th" not in miss, f"missing copy {miss} {opts}")
out = ai_copy.complete_copy(config.load_config(), q)
ok(out["title_en"] == "Cute Cat Figure Desk Decor" and out["description_en"].startswith("<p>") and out["hashtags_shopee"] == "#แมว #ของขวัญ #decor"
   and out["options_th"] == {"白色": "สีขาว", "大号": "ใหญ่"} and "title_th" not in out and isinstance(out["highlights_th"], list), f"complete copy {out}")
store.save(q)
r = C.post(f"/api/products/{pid}/ai-complete", json=q).get_json()
ok(r["ok"] and "package_content_th" in r["fields"], "ai-complete route")
r = C.post("/api/products/fill-copy?async=1", json={"ids": [pid]}); jid = r.get_json()["job"]
for _ in range(100):
    g = C.get(f"/api/bg/{jid}").get_json()
    if g["status"] != "running": break
    time.sleep(0.1)
q2 = store.load(pid)["copy"]
ok(g["status"] == "done" and q2["title_en"] and q2["package_content_th"] and q2["variation2_name_th"] == "ขนาด" and q2["title_th"] == "ตุ๊กตาแมวน่ารัก", "bulk fill keeps existing, fills empty")
bt = C.post("/api/ai/back-translate", json={"title_th": "x", "description_th": "y"}).get_json()
ok(bt["title_en"] == "Cat Figure" and bt["description_en"] == "<p>Cat</p>", "back-translate also gives English")
from core import lazada_template
qq = store.load(pid); qq["copy"]["title_en"] = ""; qq["copy"]["package_content_th"] = ""
from core import pricing
_e, w = lazada_template.check_product(qq, pricing.price_product(config.load_config(), qq), None, config.load_config()) if False else ([], [])

# ---- 智能客服 ----
from modules.cs.logic import data as csd, service as css, brain as csb, alerts as csa, report as csr, mailer
c = C.post("/api/cs/convs", json={"buyer": "Somchai", "platform": "lazada", "text": "อยากได้ 100 ชิ้น ใช้เป็นของขวัญงานบริษัท"}).get_json()
cid = c["id"]
c = C.post(f"/api/cs/convs/{cid}/draft", json={}).get_json()
a = c["analysis"]
ok(c["needs_human"] and "ส่งฟรี" in c["human_reason"] and a["tier"] == "human", f"forbidden promise → human ({c['human_reason']})")
ok(set(c["tag_list"]) == {"批发", "企业团购"} and c["needs"][0]["detail_zh"].startswith("100") , f"tags & needs {c['tag_list']}")
ok(c["lead_stage"] == "new" and c["lead_value"] == 5000 and c["next_follow_at"] > time.time() and "数量" in c["follow_note"], "wholesale → lead with follow-up")
ok(not css.auto_decision(c)["ok"], "human tier not auto-sent")
# 分级：product 默认自动，可以改成人确认
c2 = C.post("/api/cs/convs", json={"buyer": "Ann", "platform": "shopee", "text": "ขนาดเท่าไหร่คะ"}).get_json()
c2 = C.post(f"/api/cs/convs/{c2['id']}/draft", json={}).get_json()
ok(c2["analysis"]["tier"] == "auto" and css.auto_decision(c2)["ok"], "product question auto tier")
C.post("/api/cs/settings", json={"tiers": json.dumps(dict(csd.tiers(), product="confirm"))})
ok(not css.auto_decision(css.conv_full(c2["id"]))["ok"], "tier changed to confirm → not auto")
ok(csd.tiers()["refund"] == "human", "refund always human")
# 答不上来 → 待补充
c3 = C.post("/api/cs/convs", json={"buyer": "Lek", "platform": "tiktok", "text": "ส่งไปลาวได้ไหมคะ"}).get_json()
C.post(f"/api/cs/convs/{c3['id']}/draft", json={})
kp = C.get("/api/cs/kb/pending").get_json()
ok(any("老挝" in (u["question_zh"] or "") for u in kp["unanswered"]), "unanswered question recorded")
# 人工回复 → 学到新知识（待确认）
C.post(f"/api/cs/convs/{c3['id']}/sent", json={"text": "ขออภัยค่ะ ตอนนี้ส่งเฉพาะในไทยค่ะ"})
for _ in range(50):
    kp = C.get("/api/cs/kb/pending").get_json()
    if kp["pending"] and not any("老挝" in (u["question_zh"] or "") for u in kp["unanswered"]): break
    time.sleep(0.1)
ok(kp["pending"] and kp["pending"][0]["source"] == "learned" and kp["pending"][0]["status"] == "pending", "learned KB pending")
ok(not any("老挝" in (u["question_zh"] or "") for u in kp["unanswered"]), "answered question leaves the list")
kid = kp["pending"][0]["id"]
C.post(f"/api/cs/kb/{kid}/review", json={"ok": True})
ok(any(k["id"] == kid and k["active"] for k in C.get("/api/cs/kb").get_json()["kb"]), "approve → active KB")
ok(any(k["id"] == kid for k in csb.kb_match("ส่งไปลาวได้ไหม")), "AI now finds it")
csd.unanswered_add("ทำสีทองได้ไหม", "能做金色吗", c3["id"])
u = [x for x in csd.unanswered() if x["question_zh"] == "能做金色吗"][0]
r = C.post(f"/api/cs/unanswered/{u['id']}", json={"q": u["question"], "a": "ได้ค่ะ", "a_zh": "可以"}).get_json()
ok(r["ok"] and r["kb"]["a"] == "ได้ค่ะ" and not [x for x in csd.unanswered() if x["id"] == u["id"]], "answer unanswered → KB")
# 线索 / 跟进
L = C.get("/api/cs/leads").get_json()["leads"]
ok(any(x["id"] == cid for x in L), "leads list")
C.post(f"/api/cs/convs/{cid}/action", json={"type": "lead", "stage": "follow", "days": -1})
csd.update_conv(cid, next_follow_at=time.time() - 10)
ok(any(x["id"] == cid for x in C.get("/api/cs/convs?status=follow").get_json()["convs"]), "due follow-up in list")
skus = [v["sku"] for v in store.load(pid)["variants"]]
r = C.post(f"/api/cs/convs/{cid}/action", json={"type": "quote", "items": [{"sku": skus[0], "qty": 100, "unit_price": 50}]}).get_json()
ok(r["lead_stage"] == "quoted" and r["order"]["status"] == "quote", "quote → quoted")
sg = [x for x in r["suggestions"] if x["type"] == "quote_confirm"]
ok(sg, "quote confirm suggestion")
r = C.post(f"/api/cs/convs/{cid}/action", json=sg[0]).get_json()
ok(r["lead_stage"] == "won" and r["order"]["status"] == "to_ship", "quote → order, lead won")
# 买家历史
h = css.conv_full(cid)["buyer_history"]
ok(h and h["past_chats"] == 0 and h["orders"] >= 1, f"buyer history {h}")
# 实时翻译
r = C.post("/api/cs/translate", json={"text": "您好，有现货", "to": "th", "conv_id": cid}).get_json()
ok(r["text"].startswith("สวัสดี"), "live translate zh→th")
from core import integrations
XK = integrations.create_key("ext", "full")
r = C.post("/api/v1/cs/translate", json={"text": "您好，有现货", "conv_id": cid}, headers={"Authorization": "Bearer " + XK}).get_json()
ok(r["text"].startswith("สวัสดี"), "extension translate")
# 周报
w = C.get("/api/cs/weekly?ai=1").get_json()
ok(w["leads"]["new"] >= 1 and w["points"] and "客服周报" in w["text"] and any(t["tag"] == "批发" for t in w["tags"]), "weekly report")
# 邮件：假 SMTP 服务器
import socketserver, threading
MAILS = []
class H(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(b"220 test\r\n"); data_mode = False; buf = []
        while True:
            line = self.rfile.readline()
            if not line: break
            if data_mode:
                if line.strip() == b".":
                    MAILS.append(b"".join(buf).decode("utf-8", "ignore")); data_mode = False; buf = []; self.wfile.write(b"250 ok\r\n")
                else: buf.append(line)
                continue
            cmd = line.strip().upper()
            if cmd.startswith(b"EHLO") or cmd.startswith(b"HELO"): self.wfile.write(b"250 test\r\n")
            elif cmd.startswith(b"DATA"): data_mode = True; self.wfile.write(b"354 go\r\n")
            elif cmd.startswith(b"QUIT"): self.wfile.write(b"221 bye\r\n"); break
            else: self.wfile.write(b"250 ok\r\n")
srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
import email as _em
def txt(m):
    msg = _em.message_from_string(m)
    parts = [p for p in msg.walk() if p.get_content_type() == "text/plain"]
    subj = str(_em.header.make_header(_em.header.decode_header(msg["Subject"] or "")))
    return subj + "\n" + (parts[0].get_payload(decode=True).decode("utf-8", "ignore") if parts else "")
threading.Thread(target=srv.serve_forever, daemon=True).start()
C.post("/api/cs/settings", json={"smtp_host": "127.0.0.1", "smtp_port": str(port), "smtp_tls": "none", "smtp_from": "shop@example.com",
                                 "smtp_pass": "secret-pw", "owner_email": "boss@example.com", "cs_email": "cs@example.com, cs2@example.com"})
s_pub = C.get("/api/cs/kb").get_json()["settings"]
ok(s_pub["smtp_pass"] == "" and s_pub["smtp_pass_set"], "smtp password not sent back")
C.post("/api/cs/settings", json={"smtp_pass": ""})
ok(csd.settings()["smtp_pass"] == "secret-pw", "empty password keeps saved one")
r = C.post("/api/cs/mail/test", json={}).get_json()
ok(r["ok"] and r["to"] == ["boss@example.com", "cs@example.com", "cs2@example.com"] and MAILS, "test email")
n0 = len(MAILS)
csd.update_conv(cid, urgent_alerted_at=None, last_buyer_at=time.time())
csa.urgent_async(cid); time.sleep(0.5)
ok(len(MAILS) == n0 + 1 and "Somchai" in txt(MAILS[-1]), "urgent email")
csa.urgent_async(cid); time.sleep(0.3)
ok(len(MAILS) == n0 + 1, "urgent email only once")
csd.save_settings({"alert_minutes": "1"})
db.conn().execute("UPDATE cs_msg SET created_at=? WHERE conv_id=?", (time.time() - 600, c2["id"])); db.conn().commit()
n1 = len(MAILS)
csa.check_once()
ok(len(MAILS) > n1 and any("超时" in txt(m) for m in MAILS[n1:]), "overdue email")
csd.save_settings({"last_weekly": "", "weekly_day": str(time.localtime().tm_wday + 1), "weekly_hour": "0", "last_follow_digest": ""})
csd.update_conv(c3["id"], lead_stage="follow", next_follow_at=time.time() - 60, follow_note="问颜色")
n2 = len(MAILS)
csa.check_once()
ok(any("周报" in txt(m) for m in MAILS[n2:]) and any("跟进" in txt(m) for m in MAILS[n2:]) and csd.settings()["last_weekly"], "weekly + follow digest emails")
csa.check_once()
ok(csd.settings()["last_weekly"] == time.strftime("%G-W%V"), "weekly not resent")
# v2.22.1：财务的列表设置保存后还是列表（之前存成字符串，设置页整页空白）
r = C.post("/api/config", json={"fin_fixed_cats": "房租, 人工工资，水电", "fin_expense_cats": "广告、样品"})
ok(r.status_code == 200, "save list settings")
g = C.get("/api/config").get_json()["config"]
ok(g["fin_fixed_cats"] == ["房租", "人工工资", "水电"] and g["fin_expense_cats"] == ["广告", "样品"], "list settings stay lists")
from core import config as _cf
raw = json.load(open(_cf.CONFIG_PATH, encoding="utf-8")); raw["fin_fixed_cats"] = "a, b"; json.dump(raw, open(_cf.CONFIG_PATH, "w", encoding="utf-8"))
ok(_cf.load_config()["fin_fixed_cats"] == ["a", "b"], "old string config repaired on load")
srv.shutdown()
print("ERRORS", E)
