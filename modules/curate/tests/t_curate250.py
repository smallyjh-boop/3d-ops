# v2.50：选品模块（把「3D选品工具」并进 ERP）——许可证初判、泰国市场排除规则、六项打分、文件名识别规格、STL / 3MF 解析（含拓竹切片数据）、
# 流水线（翻译 / 缩略图 / 文件分析 / 规格 / 文案检查 / 质量）、转产品的许可硬门槛 + 建产品（文件只移动不复制）、关注巡逻产生新候选 + 今日待办、
# 爆款雷达「去模型站找」、扩展接口的密钥权限（只读密钥拒绝）、上架客服看不到成本利润、菜单在「商品」第一个、估算按 ERP 生产记录校准。AI 都是假的。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, time, struct, zipfile, io
D = T + "/m_cur250"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, integrations, todo, ai_copy, modules
from core.config import save_config, load_config
db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "secret123", "listing", "Nok")
db.create_user("pim", "secret123", "production", "Pim")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
CL = A.app.test_client(); CL.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
CP = A.app.test_client(); CP.post("/api/auth/login", json={"username": "pim", "password": "secret123"})
from modules.curate import rules, variants, files, cand, pipeline, watch, db as cdb, sites
KEY = integrations.create_key("Nok")
H = {"Authorization": "Bearer " + KEY, "X-Ext-Version": "3.1.0"}
RKEY = integrations.create_key("readonly", "read")
HR = {"Authorization": "Bearer " + RKEY}
OKEY = integrations.create_key("ops", "ops")

# ---------- 表 ----------
names = {r[0] for r in db.conn().execute("SELECT name FROM sqlite_master WHERE type='table'")}
ok(set(cdb.TABLES) <= names, f"cur_ tables {sorted(set(cdb.TABLES) - names)}")

# ---------- 许可证初判 ----------
L = rules.classify_license
ok(L("CC BY 4.0")[0] == rules.LIC_OK and "署名" in L("CC BY 4.0")[1], "CC BY = commercial ok (needs attribution)")
ok(L("Creative Commons - Attribution - Non-Commercial")[0] == rules.LIC_NO, "NC = no commercial")
ok(L("CC BY-NC-SA 4.0")[0] == rules.LIC_NO, "BY-NC-SA = no")
ok(L("Standard Digital File License")[0] == rules.LIC_NO, "MakerWorld standard digital file = no")
ok(L("CC0")[0] == rules.LIC_OK and L("", "https://creativecommons.org/publicdomain/zero/1.0/")[0] == rules.LIC_OK, "CC0 / public domain ok")
ok(L("All Rights Reserved")[0] == rules.LIC_NO and L("")[0] == "" and L("Some custom thing")[0] == "", "ARR no / unknown blank")
ok("ND" in L("CC BY-ND")[1], "ND noted")

# ---------- 排除规则 ----------
cfg = load_config()
ex = lambda t, ai=None: rules.parts({"title": t, "metrics": {}}, ai or {}, load_config())[1]
ok(ex("Rattle toy for kids") == rules.EX_KIDS, "kids toy excluded (มอก.)")
ok("宗教" in ex("Buddha statue"), "religious excluded")
ok("武器" in ex("Pistol replica") and ex("Gun holder for wall") == "", "weapons excluded, gun holder ok")
ok("食物" in ex("Coffee mug") and ex("Spoon rest") == "", "food contact excluded, spoon rest ok")
ok("成人" in ex("NSFW figure"), "adult excluded")
ok(ex("Pikachu planter") == rules.EX_IP and ex("ที่วาง Stitch") == rules.EX_IP, "brand / anime excluded")
ok(ex("Cable clip", {"single_color": False}) == rules.EX_MULTI, "multi-colour excluded")
ok("打印时间太长" in ex("Cable clip", {"est_minutes": 600}), "over-long print excluded")
save_config({"cur_exclude_kids": False})
ok(ex("Rattle toy for kids") == "", "kids rule can be switched off")
save_config({"cur_exclude_kids": True})

# ---------- 打分 ----------
cfg = load_config()
pp, exr, cat = rules.parts({"title": "Honda Click cup holder", "metrics": {"downloads": "2.1k", "likes": "300"}}, {}, cfg)
ok(cat == "车和摩托配件" and pp["demand"] >= 85 and pp["popularity"] > 50 and not exr, f"category prior + popularity {pp} {cat}")
s1 = rules.score(pp, cfg)
ok(0 < s1 <= 100, f"score {s1}")
save_config({"cur_w_demand": 0, "cur_w_production": 0, "cur_w_profit": 0, "cur_w_competition": 0, "cur_w_popularity": 100, "cur_w_listing": 0})
ok(rules.score(pp, load_config()) == pp["popularity"], "weights normalised")
save_config({"cur_w_demand": 30, "cur_w_production": 25, "cur_w_profit": 15, "cur_w_competition": 10, "cur_w_popularity": 15, "cur_w_listing": 5})
cfg = load_config()
from core import pricing
pp2, _e2, _c2 = rules.parts({"title": "Hook", "metrics": {}}, {"est_minutes": 60, "est_grams": 20, "price_low": 150, "price_high": 250},
                            cfg, cost_fn=cand.cost_fn(cfg), fee=0.2)
ok(pp2["profit"] > 50, f"profit from ERP pricing {pp2['profit']} cost {pricing.variant_cost(cfg, 20, 1)['total']}")
ok(rules.calib_from_pairs([(60, 90, 20, 30)] * 4)["m"] == 1.0 and rules.calib_from_pairs([(60, 90, 20, 30)] * 5) == {"m": 1.5, "g": 1.5, "n": 5},
   "calibration needs >= 5 samples")

# ---------- 文件名识别规格 ----------
fs = [{"id": 1, "name": "Planter_Small.stl", "bbox": "60,60,50"}, {"id": 2, "name": "Planter_Large.stl", "bbox": "100,100,80"},
      {"id": 3, "name": "Planter_drip_tray.stl", "bbox": "80,80,10"}]
sug = variants.rule_variants(fs)
ok(len(sug["variants"]) == 2 and [v["name_zh"].split(" ")[0] for v in sug["variants"]] == ["小号", "大号"] and 3 in sug["common"],
   f"size words → 2 specs + common part {[(v['name_zh'], v['file_ids']) for v in sug['variants']]} {sug['common']}")
sug = variants.rule_variants([{"id": 1, "name": "box_80x80x36.stl", "bbox": ""}, {"id": 2, "name": "box_120x80x36.stl", "bbox": ""},
                              {"id": 3, "name": "box_3pcs.stl", "bbox": ""}])
ok(len(sug["variants"]) == 3 and sug["variants"][-1]["kind"] == "bundle" and "cm" in sug["variants"][0]["name_zh"], f"dims + bundle {[v['name_zh'] for v in sug['variants']]}")
ok(variants.rule_variants([{"id": 1, "name": "hook.stl", "bbox": ""}])["variants"] == [], "single file = no specs")
ok(len(variants.rule_variants([{"id": 1, "name": "clip_v1.stl", "bbox": ""}, {"id": 2, "name": "clip_v2.stl", "bbox": ""}])["ignored"]) == 1, "old revision ignored")

# ---------- 测试用的模型文件（STL / 3MF 交给 ERP 的模型库分析） ----------
def cube_stl(path, s=20.0):
    v = [(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0), (0, 0, s), (s, 0, s), (s, s, s), (0, s, s)]
    tris = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    with open(path, "wb") as f:
        f.write(b"\0" * 80 + struct.pack("<I", len(tris)))
        for a, b, c in tris:
            f.write(struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *v[i]) for i in (a, b, c)) + b"\0\0")
TMP = D + "/curtmp"; os.makedirs(TMP, exist_ok=True)
MODEL_XML = ('<?xml version="1.0"?><model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="1" type="model"><mesh><vertices>'
             + "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in [(0, 0, 0), (30, 0, 0), (30, 30, 0), (0, 30, 0), (0, 0, 30), (30, 0, 30), (30, 30, 30), (0, 30, 30)])
             + '</vertices><triangles>' + "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in
                [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)])
             + '</triangles></mesh></object></resources><build><item objectid="1"/></build></model>')

# ---------- 假 AI ----------
CALLS = []
def fake_ai(cfg, system, user, image_b64=None):
    CALLS.append(system[:16])
    if "选品顾问" in system:
        items = json.loads(user)["items"]
        return json.dumps({"items": [{"i": it["i"], "category": "收纳整理", "demand": 80, "est_minutes": 60, "est_grams": 20, "single_color": True,
                                      "parts": 1, "price_low": 150, "price_high": 250, "competition": "low", "listing": 70, "exclude": "",
                                      "reason": "租房党用得上", "thai_keywords": ["ที่แขวนสายไฟ"]} for it in items]})
    if "翻译助手" in system:
        return json.dumps({"title_zh": "理线夹", "title_th": "คลิปเก็บสายไฟ", "desc_zh": "简单的理线夹", "desc_th": "คลิปเก็บสาย"})
    if "listing copywriter" in system:
        return json.dumps({"title_th": "คลิปเก็บสายไฟ ติดโต๊ะ ขายดี Cable Clip", "title_shopee_th": "คลิปเก็บสายไฟ", "title_en": "Cable Clip Organizer",
                           "highlights_th": ["ติดง่าย", "แข็งแรง"], "description_th": "<p>คลิปเก็บสายไฟ</p>", "description_en": "<p>Cable clip</p>",
                           "hashtags_shopee": ["#คลิป"], "package_content_th": "1 x คลิป", "title_zh": "理线夹 桌面", "description_zh": "理线夹",
                           "search_keywords_th": ["คลิปเก็บสาย"], "options_th": {}})
    if "precise Thai e-commerce translator" in system:
        return json.dumps({"title_zh": "理线夹 桌面", "description_zh": "理线夹"})
    if "translate a Thai" in system:
        return json.dumps({"en": "phone stand"})
    return "{}"
ai_copy.call = fake_ai
PNG = io.BytesIO()
from PIL import Image
Image.new("RGB", (800, 600), (200, 100, 50)).save(PNG, "PNG")
from modules.curate import adopt
adopt.fetch_image = lambda url, referer="": PNG.getvalue()
save_config({"ai_api_key": "test-key"})

# ---------- 扩展接口：权限 ----------
ok(C.get("/api/v1/curate/ext/ping").status_code == 401, "no key = 401")
ok(C.get("/api/v1/curate/ext/ping", headers=HR).status_code == 403, "read-only key refused (GET)")
ok(C.post("/api/v1/curate/ext/score", json={"items": []}, headers=HR).status_code == 403, "read-only key refused (POST)")
ok(C.get("/api/v1/curate/ext/ping", headers={"Authorization": "Bearer " + OKEY}).status_code == 403, "ops write-back key refused")
r = C.get("/api/v1/curate/ext/ping", headers=H)
ok(r.status_code == 200 and r.get_json()["ext_latest"] == "3.1.1" and r.get_json()["user"] == "Nok", f"ext ping with staff key {r.get_json()}")
ok(any(k["name"] == "Nok" and k.get("ext_version") == "3.1.0" for k in integrations.ext_versions()) if hasattr(integrations, "ext_versions") else True, "ext version noted")
sp = C.get("/api/v1/curate/ext/sites", headers=H).get_json()
ok(sp["version"] and {"makerworld", "printables", "thingiverse"} <= {s["id"] for s in sp["sites"]} and "_rx" not in json.dumps(sp), "site packs served as data")

# ---------- 列表页打分 ----------
cards = [{"url": "https://makerworld.com/en/models/1001-cable-clip?from=search", "title": "Cable clip organizer", "thumb": "https://x.bblmw.com/a.jpg",
          "metrics": {"downloads": "1.2k", "likes": "200"}},
         {"url": "https://www.printables.com/model/2002-pikachu-planter", "title": "Pikachu planter", "metrics": {"likes": "50"}},
         {"url": "https://www.thingiverse.com/thing:3003", "title": "Desk hook", "metrics": {"n1": "30"}},
         {"url": "https://example.com/not-a-model", "title": "x"}]
r = C.post("/api/v1/curate/ext/score", json={"items": cards}, headers=H).get_json()
sc = r["scores"]
ok(len(sc) == 3 and cards[0]["url"] in sc and "profit" not in sc[cards[0]["url"]]["parts"], f"score endpoint (3 model links, no profit for key) {list(sc)}")
ok(sc[cards[1]["url"]]["excluded"] == rules.EX_IP, "IP card excluded in badge")
ok(cdb.conn().execute("SELECT skey FROM cur_candidates WHERE url LIKE '%makerworld%'").fetchone()[0] == "mw:1001", "canonical url + source key")
n = pipeline.run_all()
row = cdb.conn().execute("SELECT * FROM cur_candidates WHERE skey='mw:1001'").fetchone()
ok(row["ai_at"] > 0 and json.loads(row["ai"])["category"] == "收纳整理" and row["category"] == "收纳整理", f"AI batch scoring ran ({n})")
lst = C.get("/api/cur/candidates").get_json()
ok(lst["ok"] and lst["kpi"]["total"] == 3 and any(x["title"] == "Cable clip organizer" for x in lst["rows"]) and "hist" in lst, "candidate pool list (owner)")
lstl = CL.get("/api/cur/candidates").get_json()
ok(all("profit" not in x["parts"] and "price" not in x for x in lstl["rows"]), "listing role: no profit / price in candidates")

# ---------- 采用 → 马上建 ERP 产品草稿 → 扩展读详情页补进来 ----------
r = C.post("/api/v1/curate/ext/collect", json={"items": [{"url": cards[0]["url"], "title": "Cable clip organizer"}]}, headers=H).get_json()
ok(r["added"] == 1 and r["waiting"] == 1 and r["products"][0]["product_code"].startswith("3DP"), f"＋采集 = adopt → product draft right away {r}")
PID = r["products"][0]["product_code"]
p = store.load(PID)
ok(p["draft"] and p["license_check"]["status"] == "pending" and p["source"]["source"] == "curate" and not p["source"]["license_verified"]
   and p["source"]["source_url"] == "https://makerworld.com/en/models/1001-cable-clip", "draft with licence pending + source link")
_pl = C.get("/api/products").get_json()
_pi = C.get("/api/products?inbox=1").get_json()
ok(not any(x.get("id") == PID for x in _pl) and any(x.get("id") == PID and x["inbox"] for x in _pi) and p.get("inbox"),
   "v2.50.1: draft goes to 采集箱, not into 产品库 (until 转入产品库)")
r2 = C.post("/api/v1/curate/ext/collect", json={"items": [{"url": cards[0]["url"]}]}, headers=H).get_json()
ok(r2["added"] == 0 and list(r2["skipped"].values()) == ["imported"], "no double adopt")
ok(C.post("/api/v1/curate/ext/status", json={"urls": [cards[0]["url"]]}, headers=H).get_json()["states"][cards[0]["url"]]["product_id"] == PID, "status → product id")
nx = C.get("/api/v1/curate/ext/next", headers=H).get_json()
ok(nx["item"] and nx["item"]["url"] == "https://makerworld.com/en/models/1001-cable-clip", f"next detail page {nx}")
detail = {"platform": "MakerWorld", "source_url": nx["item"]["url"], "title": "Cable clip organizer", "author": "Designer A",
          "description_original": "A simple cable clip for desks. Print in PLA. Support me on Patreon! " * 2, "tags": "cable, clip",
          "image_urls": ["https://makerworld.bblmw.com/1.jpg", "https://makerworld.bblmw.com/2.jpg", "https://makerworld.bblmw.com/3.jpg"],
          "model_files": [{"name": "clip_small.stl", "url": "https://makerworld.com/f/1"}, {"name": "clip_large.stl", "url": "https://makerworld.com/f/2"},
                          {"name": "clip_tray.3mf", "url": "https://makerworld.com/f/4"}, {"name": "readme.pdf", "url": "https://makerworld.com/f/3"}],
          "license_name": "CC BY 4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/"}
r = C.post("/api/v1/curate/ext/result", json={"id": nx["item"]["id"], "data": detail}, headers=H).get_json()
ok(r["ok"] and r["state"] == "done" and r["product_id"] == PID, f"detail result enriches draft {r}")
p = store.load(PID)
ok(p["license_check"]["auto"] == rules.LIC_OK and p["license_check"]["status"] == "pending" and p["license_check"]["name"] == "CC BY 4.0", "licence pre-classified, still pending")
ok("Patreon" not in (p.get("features_zh") or "") and p["source"]["author"] == "Designer A" and p["keywords"] == "cable, clip", "description cleaned (ERP copyfacts) + tags")
fq = cdb.conn().execute("SELECT name, state, kind FROM cur_files WHERE product_id=? ORDER BY id", (PID,)).fetchall()
ok([x["state"] for x in fq if x["kind"] != "image"] == ["queued", "queued", "queued", ""] and sum(1 for x in fq if x["kind"] == "image") == 3,
   f"model files queued (pdf listed only), images queued {[tuple(x) for x in fq]}")
pipeline.run_all()
p = store.load(PID)
ok(len(p["images"]) == 3 and all(os.path.isfile(os.path.join(store.image_dir(PID, "raw"), i["file"])) for i in p["images"]), "source images pulled into ERP product images")
# 扩展下载文件 → 直接进产品的模型库
fn = C.get("/api/v1/curate/ext/files/next", headers=H).get_json()
ok(fn["product"] == PID and len(fn["files"]) == 3 and fn["pacing"]["file_gap"][0] > 0, f"files next with pacing {fn}")
cube_stl(TMP + "/s.stl", 20); cube_stl(TMP + "/l.stl", 40)
with zipfile.ZipFile(TMP + "/tray.3mf", "w") as z:
    z.writestr("3D/3dmodel.model", MODEL_XML)
    z.writestr("Metadata/slice_info.config", '<config><plate><metadata key="prediction" value="5400"/><metadata key="weight" value="42.5"/></plate></config>')
for f, src in zip(fn["files"], ["s.stl", "l.stl", "tray.3mf"]):
    with open(TMP + "/" + src, "rb") as fh:
        u = C.post(f"/api/v1/curate/ext/files/{f['id']}/upload?name={f['name']}", data=fh.read(), headers={**H, "Content-Type": "application/octet-stream"})
    ok(u.status_code == 200 and u.get_json()["bytes"] > 0, f"file upload {f['name']}")
ok(C.get("/api/v1/curate/ext/files/next", headers=H).get_json()["product"] is None, "pacing: next product waits / nothing left")
ok(os.path.isfile(os.path.join(store.product_dir(PID), "source_files", "clip_small.stl")) and not os.path.isdir(os.path.join(D, "curate", "files")),
   "file stored once, in the product's model library folder")
pipeline.run_all()
p = store.load(PID)
lib = [e for e in p.get("model_lib") or [] if e.get("dir") == "source_files"]
ok(len(lib) == 3 and all((e.get("info") or {}).get("ok") for e in lib if e["ext"] == "stl"), f"ERP model library analysed the files {[(e['file'], (e.get('info') or {}).get('ok')) for e in lib]}")
names = [v["opt2_zh"] for v in p["variants"]]
ok(len(p.get("specs") or []) == 2 and names[0].startswith("小号") and names[1].startswith("大号"), f"filename variant detection → ERP specs {names}")
ok(p["variants"][0]["grams"] > 0 and p["variants"][1]["grams"] > p["variants"][0]["grams"] and p["variants"][0]["sku"] and p["variants"][0].get("model_file") == "clip_small.stl",
   f"spec grams from ERP analysis + SKU + model file {[(v['opt2_zh'], v['grams'], v['hours'], v.get('model_file')) for v in p['variants']]}")
tray = next(e for e in lib if e["file"] == "clip_tray.3mf")
ok((tray.get("info") or {}).get("sliced_result", {}).get("grams") == 42.5, f"Bambu/Orca slice data read by ERP {(tray.get('info') or {}).get('sliced_result')}")
ok(p["variants"][0]["grams"] >= 42.5, "common sliced part counted in each spec")
ok(p.get("model") and p["model"].get("lib_id"), "first STL set as the product 3D model")
ok(p["copy"].get("title_th") and p["copy"].get("description_th") and p["source"].get("ai_copy_tried"), "ERP AI copy filled the empty copy fields")
ok(p["name_zh"] == "理线夹 桌面", f"Chinese name from AI copy {p['name_zh']}")
c_real = json.loads(cdb.conn().execute("SELECT real FROM cur_candidates WHERE skey='mw:1001'").fetchone()[0] or "{}")
pipeline.calibrate()
c_real = json.loads(cdb.conn().execute("SELECT real FROM cur_candidates WHERE skey='mw:1001'").fetchone()[0] or "{}")
ok(c_real.get("grams") == p["variants"][0]["grams"], f"measured grams written back to candidate {c_real}")

# ---------- 许可门槛在 ERP 这边：上架检查挡导出 / 推送 ----------
from core import lazada_template, copyrules
from web.common import _check, _check_shopee
errs, warns = _check(load_config(), p)
ok(any("许可待核验" in e for e in errs), "listing check: licence pending = error (blocks export / push)")
ok(any("许可待核验" in e for e in _check_shopee(load_config(), p)[0]), "Shopee export blocked too")
from modules.listing import lazada_push
ok(any("许可待核验" in e for e in lazada_push._check(load_config(), p, None)[0]), "Lazada API push uses the same check")
pv = C.get(f"/api/p360/{PID}").get_json()
ok(pv["product"]["license_pending"], "product 360 shows licence pending")
r = CL.post(f"/api/products/{PID}/license", json={"verified": True})
ok(r.status_code == 200 and r.get_json()["product"]["license_check"]["status"] == "ok" and r.get_json()["product"]["license_check"]["by"] == "nok", "listing staff verifies licence")
p = store.load(PID)
ok(not any("许可待核验" in e for e in _check(load_config(), p)[0]) and p["source"]["license_verified"], "verified → licence error gone")
ok(any(a.get("action") == "许可核验" for a in db.audit_list(20)), "licence verification in audit log")
ok(not C.get(f"/api/p360/{PID}").get_json()["product"]["license_pending"], "p360 badge gone")
_hist = json.dumps(C.get(f"/api/p360/{PID}").get_json(), ensure_ascii=False)
ok("คัดเลือกสินค้า·ใช้" in _hist, "p360 history: Thai name for the adopt audit action")
# 禁止商用的初判：要 force
r = C.post("/api/cur/candidates/adopt", json={"urls": "https://www.printables.com/model/4004-hook"}).get_json()
P2 = r["products"][0]["product_code"]
watch.reset(); cdb.put("pace", {})
nx = C.get("/api/v1/curate/ext/next", headers=H).get_json()
C.post("/api/v1/curate/ext/result", json={"id": nx["item"]["id"], "data": {"source_url": nx["item"]["url"], "title": "Hook", "license_name": "CC BY-NC 4.0"}}, headers=H)
ok(store.load(P2)["license_check"]["auto"] == rules.LIC_NO, "NC pre-classified as no commercial")
ok(C.post(f"/api/products/{P2}/license", json={"verified": True}).status_code == 400, "NC licence: verify refused without force")
ok(C.post(f"/api/products/{P2}/license", json={"verified": True, "force": True}).status_code == 200, "force (bought a licence) ok")
# 选品工具的额外检查规则进了 ERP 的上架检查（所有产品）
q = store.load(P2)
q["copy"] = {"title_th": "ที่แขวน Pikachu สีแดง ขายดี", "title_en": "Buddha hook red"}
q["variants"][0]["opt2_zh"] = "红色款"
e3, w3 = copyrules.problems(q)
ok(any("品牌" in w for w in w3) and any("颜色词" in w and "标题" in w for w in w3) and any("规格名" in w for w in w3) and any("营销词" in w for w in w3)
   and any("宗教" in w for w in w3) and not e3, f"extra rules as warnings {w3}")
ok(any("品牌" in w for w in lazada_template.check_product(q, [])[1]), "warnings show up in the ERP listing check")
# 候选池里的采用
r = C.post("/api/cur/candidates/adopt", json={"ids": [cdb.conn().execute("SELECT id FROM cur_candidates WHERE skey='tv:3003'").fetchone()[0]]}).get_json()
ok(r["added"] == 1, "adopt from candidate pool")
qd = C.get("/api/cur/queue").get_json()
ok(qd["ok"] and qd["kpi"]["waiting"] >= 1 and any(x["product_id"] == PID and x["license"] == "ok" and x["specs"] == 2 and x["model"] for x in qd["rows"]), "queue page data")
ok(CL.get("/api/cur/queue").status_code == 200, "listing role sees the queue")

# ---------- 风控 ----------
cdb.conn().execute("UPDATE cur_files SET state='queued' WHERE product_id=? AND name='readme.pdf'", (PID,)); cdb.conn().commit()
watch.reset()
fn = C.get("/api/v1/curate/ext/files/next", headers=H).get_json()
f3 = fn["files"][0]["id"]
rr = C.post(f"/api/v1/curate/ext/files/{f3}/fail", json={"status": 429, "error": "Too Many Requests"}, headers=H).get_json()
ok(rr["kind"] == "risk" and rr["stop"] and watch.paused("makerworld") > time.time(), "429 → platform paused")
ok(C.get("/api/v1/curate/ext/files/next", headers=H).get_json()["product"] is None, "paused platform gets no downloads")
ok(watch.classify_failure({"status": 403, "snippet": "Please log in to download"})[0] == "login" and watch.classify_failure({"status": 404})[0] == "missing",
   "login / missing classified")
watch.reset()
ok(C.post(f"/api/cur/products/{PID}/download", json={}).get_json()["queued"] == 0, "re-download: nothing failed / everything queued")

# ---------- 关注巡逻 ----------
r = C.post("/api/cur/watches", json={"kind": "keyword", "site": "pr", "value": "cable organizer"}).get_json()
ok(r["ok"] and r["url"] == "https://www.printables.com/search/models?q=cable%20organizer", f"keyword watch {r}")
ok(C.post("/api/cur/watches", json={"kind": "url", "value": "https://www.printables.com/model/1-x"}).status_code == 400, "detail page not allowed as watch")
ok(C.post("/api/cur/watches", json={"kind": "url", "value": "https://evil.com/x"}).status_code == 400, "only model sites")
WID = r["id"]
wn = C.get("/api/v1/curate/ext/watch/next", headers=H).get_json()
ok(wn["watch"] and wn["watch"]["id"] == WID, f"watch next {wn}")
r = C.post("/api/v1/curate/ext/watch/result", json={"id": WID, "items": [{"url": "https://www.printables.com/model/5005-a", "title": "Cable organizer A"}]}, headers=H).get_json()
ok(r["baseline"] and r["new"] == 0, "first patrol = baseline only")
ok(C.get("/api/v1/curate/ext/watch/next", headers=H).get_json()["watch"] is None, "not due again yet")
cdb.conn().execute("UPDATE cur_watches SET next_run=0 WHERE id=?", (WID,)); cdb.conn().commit(); cdb.put("watch_next_at", 0)
wn = C.get("/api/v1/curate/ext/watch/next", headers=H).get_json()
r = C.post("/api/v1/curate/ext/watch/result", json={"id": WID, "items": [{"url": "https://www.printables.com/model/5005-a", "title": "Cable organizer A"},
                                                                          {"url": "https://www.printables.com/model/6006-b", "title": "Cable organizer B"}]}, headers=H).get_json()
ok(r["new"] == 1 and r["found"] == 2, f"second patrol finds 1 new {r}")
pipeline.run_all()
nb = cdb.conn().execute("SELECT * FROM cur_candidates WHERE skey='pr:6006'").fetchone()
ok(nb["new_at"] > 0 and nb["watch_id"] == WID and nb["score"] > 0, "new candidate from patrol scored")
save_config({"cur_alert_score": 10})
td = todo.collect("listing")
keys = [i["key"] for i in td["items"]]
ok(f"cur-new:{nb['id']}" in keys and any(i["source"] == "curate" and i["tab"] == "cur_cand" for i in td["items"]), f"today's to-dos (listing role) {keys[:8]}")
newi = next(i for i in td["items"] if i["key"] == f"cur-new:{nb['id']}")
ok(newi["alert"] and "高分新模型" in newi["alert"] and newi["title_th"], "high-score alert text for ops phone alerts + Thai")
save_config({"cur_alert_on": False})
ok(not next(i for i in todo.collect()["items"] if i["key"] == f"cur-new:{nb['id']}")["alert"], "alert can be switched off")
# 每天上限
save_config({"cur_watch_daily_cap": 2})
cdb.conn().execute("UPDATE cur_watches SET next_run=0"); cdb.conn().commit(); cdb.put("watch_next_at", 0)
wn = C.get("/api/v1/curate/ext/watch/next", headers=H).get_json()
ok(wn["watch"] is None and "上限" in wn["reason"], f"daily cap {wn}")
r = C.post("/api/v1/curate/ext/watch/result", json={"id": WID, "items": [], "error": "", "snippet": "Please verify you are human (captcha)"}, headers=H).get_json()
ok(r["kind"] == "risk" and watch.paused("printables"), "captcha on list page pauses platform")
watch.reset()

# ---------- 爆款雷达 → 去模型站找 ----------
from modules.ops import radar, mkt_db
mkt_db.ensure()
radar.add_keywords("lazada", "ที่วางโทรศัพท์")
kid = mkt_db.conn().execute("SELECT id FROM ops_radar_keywords WHERE keyword='ที่วางโทรศัพท์'").fetchone()[0]
r = CL.post("/api/cur/from-radar", json={"kid": kid}).get_json()
ok(r["ok"] and r["term"] == "phone stand" and len(r["added"]) == 3, f"radar keyword → one keyword watch per model site {r.get('term')} {len(r.get('added') or [])}")
ok(CL.post("/api/cur/from-radar", json={"kid": kid}).get_json()["existing"] == 3, "no duplicate watches")
cdb.conn().execute("UPDATE cur_candidates SET ai=? WHERE skey='pr:6006'", (json.dumps({"thai_keywords": ["ที่วางโทรศัพท์"]}),)); cdb.conn().commit()
lst = C.get("/api/cur/candidates?status=all").get_json()
mk = next(x for x in lst["rows"] if x["url"].endswith("6006-b"))
ok(mk["market"] and mk["market"]["keyword"] == "ที่วางโทรศัพท์" and "score" in mk["market"], f"candidate shows Thai market data {mk['market']}")

# ---------- 校准：ERP 生产记录（≥ 5 个样本） ----------
from core import production
production.init() if hasattr(production, "init") else None
cc = db.conn()
for i in range(5):
    cdb.conn().execute("INSERT INTO cur_candidates(skey, url, title, ai, real, product_id, status) VALUES(?,?,?,?,?,?, 'adopted')",
                       (f"tv:9{i}", f"https://www.thingiverse.com/thing:9{i}", "x", json.dumps({"est_minutes": 60, "est_grams": 20}), "", f"PX{i}"))
    cc.execute("INSERT INTO print_runs(printer, product_id, count, grams, hours, status, started_at, ended_at) VALUES(0,?,2,80,3,'done',?,?)",
               (f"PX{i}", 1000.0, 1000.0 + 3 * 3600))
cc.commit(); cdb.conn().commit()
k = pipeline.calibrate()
ok(k["m"] == 1.5 and k["g"] == 2.0 and k["production"] >= 5, f"calibration from ERP print runs {k}")
ok(C.post("/api/cur/calibrate").status_code == 200 and CL.post("/api/cur/calibrate").status_code == 403, "calibrate owner only")

# ---------- 菜单 ----------
def tabs(cl):
    return [(mn["tab"], mn["mod"], mn.get("before"), mn["ghost"]) for m in cl.get("/api/modules").get_json()["modules"] for mn in m["menus"]]
tb = tabs(CL)
ok(("curate", "goods", "library", False) in tb and {t[0] for t in tb if t[0].startswith("cur")} == {"curate", "cur_cand", "cur_inbox", "cur_queue", "cur_watch"},
   f"选品 in 商品 menu before 产品库, tabs 候选池 · 采集箱 · 采集队列 · 关注巡逻 {[t for t in tb if t[0].startswith('cur')]}")
ok(not any(t[0].startswith("cur") for t in tabs(CP)), "production role: no 选品 menu")
ok(C.get("/m/curate/curate.js").status_code == 200 and C.get("/m/curate/page.html").status_code == 200 and C.get("/m/curate/page.css").status_code == 200, "ui files")
src = open(os.path.join(APP, "modules", "curate", "ui", "curate.js"), encoding="utf-8").read()
ok("选品库" not in src and "待转产品" not in src and "/api/cur/models" not in src, "no parallel model library / conversion editor in the UI")
html = C.get("/").get_data(as_text=True)
ok('"候选池"' in html or "候选池" in json.dumps(modules.i18n_th(), ensure_ascii=False), "module Thai dictionary merged")
th = json.load(open(os.path.join(APP, "modules", "curate", "i18n", "th.json"), encoding="utf-8"))
ok(th.get("采集队列") and th.get("候选池"), "th.json has the page words")
# 设置
sch = C.get("/api/settings/schema").get_json()["modules"]
ok(any(f["key"] == "cur_w_demand" for m in sch if m["id"] == "goods" for g in m["groups"] for f in g["fields"]), "settings under 商品")
# 旧的对接卡片收起来了（接口照样在）
ok(C.get("/api/curator").status_code == 200 and "legacy" in C.get("/m/link/settings.html").get_data(as_text=True), "old curator link card kept as legacy")
ok(C.get("/api/v1/categories", headers={"Authorization": "Bearer " + integrations.create_key("cat", "catalog")}).status_code == 200, "/api/v1/catalog APIs still work")
# 模块关掉
ok(C.post("/api/modules/curate", json={"on": False}).status_code == 200 and C.get("/api/cur/overview").status_code == 404
   and C.get("/api/v1/curate/ext/ping", headers=H).status_code == 404, "module off → 404")
C.post("/api/modules/curate", json={"on": True})
ok(C.get("/api/cur/overview").get_json()["ok"], "module back on")
# ---------- AI：DeepSeek 可以直接选（OpenAI 兼容接口） ----------
import requests as _rq
class _R:
    status_code = 200
    def json(self): return {"choices": [{"message": {"content": "{}"}}]}
SEEN = []
_old_post = ai_copy.requests.post
ai_copy.requests.post = lambda url, **k: SEEN.append((url, k["json"]["model"])) or _R()
try:
    ai_copy._request({"ai_provider": "deepseek", "ai_api_key": "k", "ai_model": "claude-x"}, "s", "u", None); ok(False, "deepseek needs its own model name")
except ai_copy.AIError:
    ok(True, "deepseek with a non-deepseek model name → clear error")
ai_copy._request({"ai_provider": "deepseek", "ai_api_key": "k", "ai_model": "my-ds-model", "ai_base_url": ""}, "s", "u", None)
ok(SEEN and SEEN[-1][0] == "https://api.deepseek.com/chat/completions" and SEEN[-1][1] == "my-ds-model", f"deepseek provider → OpenAI-compatible endpoint {SEEN}")
ai_copy.requests.post = _old_post
sch = C.get("/api/settings/schema").get_json()["modules"]
ok(any("deepseek" in (f.get("type") or []) for m in sch for g in m["groups"] for f in g["fields"] if f["key"] == "ai_provider"), "deepseek selectable in settings")
print("ERRORS", E_)
