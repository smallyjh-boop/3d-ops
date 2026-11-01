# 拍照识别模块（recog 1.0）：特征比对（程序生成的产品 + 模拟手机照片）、AI 第二步（假 AI）、确认的照片变参考图、
# 文字容错（ML Kit 常见错）、拍照读文字（条码 + 假 AI OCR）、手机 App 的正则接口、手机扫码的容错、权限。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import io, json, os, re, shutil, sqlite3, sys, time
D = T + "/m_recog"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; os.environ["LH_RECOG_NO_MODEL"] = "1"; sys.path.insert(0, APP)
E_ = 0


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)


import numpy as np
from PIL import Image
import app as A
from core import ai_copy, config, db, store
from modules.recog import descriptor, match, ocr, refs, textmatch
from modules.recog.tests import synth

db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("packer", "secret123", "production", "Packer", "th")
db.create_user("lister", "secret123", "listing", "Lister")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
P = A.app.test_client(); P.post("/api/auth/login", json={"username": "packer", "password": "secret123"})
L = A.app.test_client(); L.post("/api/auth/login", json={"username": "lister", "password": "secret123"})
anon = A.app.test_client()
config.save_config({"review_enabled": False, "recog_ai": "off"})

# ---- 测试产品：形状、颜色都不一样的 4 个 + 同形状不同颜色（立方体 红 / 白）
S = synth.shapes()
for pid, shape, cols, imgs in (("RCG0001", "cube", ["红色", "白色"], ["红色"]), ("RCG0002", "cylinder", ["蓝色"], []),
                               ("RCG0003", "star", ["黄色"], []), ("RCG0004", "ring", ["绿色"], ["绿色"])):
    synth.make_product(pid, f"测试{shape}", S[shape], cols, imgs)
t0 = time.time()
job = refs.build_all()
ok(not job["error"] and job["done"] >= 4, f"refs built {job['done']} products in {time.time() - t0:.1f}s err={job['error']}")
st = refs.status()
ok(st["kinds"].get("render", 0) >= 4 * len(__import__('modules.recog.render', fromlist=['x']).VIEWS) and st["kinds"].get("img", 0) >= 2,
   f"renders + product images {st['kinds']}")
ix = refs.index()
ok({"RCG0001-RD", "RCG0001-WH", "RCG0002-BL", "RCG0003-YL", "RCG0004-GN"} <= set(ix["skus"]), "all test skus indexed")
ok(refs.build_product("RCG0001")[0] is False, "unchanged product not rebuilt")

# ---- 第一步：模拟照片 → 自己的 SKU 排第一
rng = np.random.default_rng(11)
hits = 0
cases = [("RCG0001-RD", "cube", "红色"), ("RCG0001-WH", "cube", "白色"), ("RCG0002-BL", "cylinder", "蓝色"), ("RCG0003-YL", "star", "黄色"), ("RCG0004-GN", "ring", "绿色")]
for sku, shape, col in cases:
    for k in range(2):
        q = descriptor.describe(synth.photo(S[shape], synth.PALETTE[col], rng, ()))
        r = match.rank(q)
        hits += r[0][0] == sku
        if r[0][0] != sku:
            print("   miss", sku, [x[0] for x in r[:3]])
ok(hits >= 9, f"photo variant matches its product top-1 ({hits}/10)")
# 同形状不同颜色：红色立方体不会认成白色立方体
q = descriptor.describe(synth.photo(S["cube"], synth.PALETTE["红色"], rng, ("rotate",)))
r = match.rank(q)
ok(r[0][0] == "RCG0001-RD" and [x[0] for x in r].index("RCG0001-WH") > 0 if "RCG0001-WH" in [x[0] for x in r] else r[0][0] == "RCG0001-RD", f"same shape other colour ranked lower {[x[0] for x in r[:4]]}")
cf = match.confidence(r)
ok(0 <= cf[1] <= cf[0] <= 1, f"confidence ordered {cf[:3]}")

# ---- 接口：拍照识别（AI 关着 → 只用本地）
photo = synth.photo(S["star"], synth.PALETTE["黄色"], rng, ())
r = C.post("/api/recog/identify", data={"photo": (io.BytesIO(photo), "p.jpg"), "src": "m"}, content_type="multipart/form-data")
d = r.get_json()
ok(r.status_code == 200 and d["candidates"][0]["sku"] == "RCG0003-YL" and not d["ai"]["used"], f"identify api {d.get('candidates', [{}])[0].get('sku')} {d.get('ai')}")
ok(d["candidates"][0]["img"].startswith("/api/recog/disp/") and C.get(d["candidates"][0]["img"]).status_code == 200, "candidate image served")
ok(C.get(d["photo"]).status_code == 200, "query photo served")
ok(C.get("/api/recog/query/..%2F..%2Fapp.db").status_code == 404 and C.get("/api/recog/disp/RCG0001/..%2F..%2Fapp.db").status_code == 404, "no traversal")
ok(C.post("/api/recog/identify", data={"photo": (io.BytesIO(b"junk"), "p.jpg")}, content_type="multipart/form-data").status_code == 400, "bad photo rejected")
ok(C.post("/api/recog/identify", data={}, content_type="multipart/form-data").status_code == 400, "no photo rejected")

# ---- 第二步：假 AI（看图挑第 3 个）
calls = []


def fake_ai(cfg, system, user, image_b64=None):
    calls.append((user, len(image_b64 or "")))
    m = re.findall(r"^(\d)\. SKU (\S+):", user, re.M)
    pick = next((int(n) for n, s in m if s == "RCG0004-GN"), 0)
    return json.dumps({"pick": pick, "confidence": 0.91, "second": 0, "reason": "形状一样"})


config.save_config({"recog_ai": "on", "ai_api_key": "x", "ai_provider": "anthropic"})
orig = ai_copy._request
ai_copy._request = fake_ai
try:
    d = C.post("/api/recog/identify", data={"photo": (io.BytesIO(photo), "p.jpg")}, content_type="multipart/form-data").get_json()
    ok(d["ai"]["used"] and d["ai"]["ok"] and d["candidates"][0]["sku"] == "RCG0004-GN" and d["candidates"][0]["ai"], f"AI pick moves to top {d['ai']}")
    ok(abs(d["candidates"][0]["conf"] - 0.91) < 1e-6 and not d["need_pick"], "AI confidence used")
    ok(calls and calls[-1][1] > 5000 and "RCG0003-YL" in calls[-1][0], "AI got contact sheet + candidate list")
    sheet = match.contact_sheet(Image.new("RGB", (300, 200), "red"), [("A", Image.new("RGB", (50, 50), "blue"))] * 8)
    ok(sheet.size[0] > 1000, "contact sheet built")
    # AI 说都不是 → 把握压低，要员工选
    ai_copy._request = lambda *a, **k: json.dumps({"pick": 0, "confidence": 0.8, "reason": "都不像"})
    d = C.post("/api/recog/identify", data={"photo": (io.BytesIO(photo), "p.jpg")}, content_type="multipart/form-data").get_json()
    ok(d["need_pick"] and d["candidates"][0]["conf"] <= 0.3, "AI says none → ask staff")
    # AI 出错 → 只用第一步
    def boom(*a, **k):
        raise ai_copy.AIError("AI 接口错误 500: overloaded")
    ai_copy._request = boom
    d = C.post("/api/recog/identify", data={"photo": (io.BytesIO(photo), "p.jpg")}, content_type="multipart/form-data").get_json()
    ok(d["ai"]["used"] and not d["ai"]["ok"] and d["candidates"][0]["sku"] == "RCG0003-YL", "AI error → local result")
    # 不能看图的模型（400 image）→ 1 小时内不再问
    def novision(*a, **k):
        raise ai_copy.AIError("AI 接口错误 400: image input is not supported by this model")
    ai_copy._request = novision
    C.post("/api/recog/identify", data={"photo": (io.BytesIO(photo), "p.jpg")}, content_type="multipart/form-data")
    ok(not match.ai_available()[0], "no-vision model remembered")
    match._no_vision["until"] = 0
    # DeepSeek 不能看图：auto 时不调用
    ai_copy._request = fake_ai
    n0 = len(calls)
    config.save_config({"recog_ai": "auto", "ai_provider": "deepseek"})
    d = C.post("/api/recog/identify", data={"photo": (io.BytesIO(photo), "p.jpg")}, content_type="multipart/form-data").get_json()
    ok(not d["ai"]["used"] and len(calls) == n0 and "DeepSeek" in d["ai"]["why"], "deepseek → local only")
    # 每天上限
    config.save_config({"recog_ai": "on", "ai_provider": "anthropic", "recog_ai_daily": 1})
    ok(not match.ai_available()[0], "daily cap reached")
    config.save_config({"recog_ai_daily": 0})
    ok(match.ai_available()[0], "no cap → available")
finally:
    ai_copy._request = orig
config.save_config({"recog_ai": "off"})
u = match.usage()
ok(u["today"] >= 6 and u["today_ai"] >= 4, f"usage counted {u}")

# ---- 确认 → 照片变参考图（系统学会了）
odd = synth.photo(S["cylinder"], (90, 60, 30), rng, ("bg",))          # 颜色很怪的一张（棕色的圆柱）
d = C.post("/api/recog/identify", data={"photo": (io.BytesIO(odd), "p.jpg")}, content_type="multipart/form-data").get_json()
n_before = refs.status()["kinds"].get("photo", 0)
r = C.post("/api/recog/confirm", json={"rid": d["rid"], "sku": "RCG0002-BL"}).get_json()
ok(r["ok"] and r["learned"], f"confirm learned {r}")
ok(refs.status()["kinds"].get("photo", 0) == n_before + 1, "confirmed photo is a reference now")
learned = os.listdir(os.path.join(D, "recog", "learned", "RCG0002"))
ok(len(learned) == 1 and learned[0].startswith("RCG0002-BL__"), f"saved under product {learned}")
d2 = C.post("/api/recog/identify", data={"photo": (io.BytesIO(odd), "p.jpg")}, content_type="multipart/form-data").get_json()
ok(d2["candidates"][0]["sku"] == "RCG0002-BL" and d2["candidates"][0]["via"] == "photo", f"same photo now matched via learned ref {d2['candidates'][0]}")
row = db.conn().execute("SELECT chosen FROM recog_log WHERE rid=?", (d["rid"],)).fetchone()
ok(row["chosen"] == "RCG0002-BL", "choice logged")
ok(C.post("/api/recog/confirm", json={"rid": "nope", "sku": "X"}).status_code == 400, "unknown rid")
config.save_config({"recog_learn": False})
d3 = C.post("/api/recog/identify", data={"photo": (io.BytesIO(odd), "p.jpg")}, content_type="multipart/form-data").get_json()
ok(not C.post("/api/recog/confirm", json={"rid": d3["rid"], "sku": "RCG0002-BL"}).get_json()["learned"], "learning can be turned off")
config.save_config({"recog_learn": True})

# ---- 「都不是」→ 手动搜
r = C.get("/api/recog/search?q=测试star").get_json()
ok([x["sku"] for x in r["items"]] == ["RCG0003-YL"], f"manual search {r}")
ok(any(x["sku"] == "RCG0001-WH" for x in C.get("/api/recog/search?q=rcg0001%20白").get_json()["items"]), "search sku + colour")

# ---- 文字容错（ML Kit 常见的错）
from modules.inv import locations
locations.init()
C.post("/api/inv/locations/bulk", json={"zone": "A", "layers": 3, "positions": 3})
o = C.post("/api/orders/manual", json={"order_no": "2410153ABCDEFG", "order_total": 100, "buyer": "Ocr Test", "items": [{"sku": "RCG0001-RD", "qty": 1}]}).get_json()
db.conn().execute("UPDATE orders SET tracking_no='TH0112345678B' WHERE id=?", (o["id"],)); db.conn().commit()
textmatch.invalidate()
CASES = [("A1-02-03", "A1-02-03", "location"), ("A1-O2-O3", "A1-02-03", "location"), ("Al-02-O3", "A1-02-03", "location"),
         ("A1 02 03", "A1-02-03", "location"), ("A10203", "A1-02-03", "location"), ("LOC: A1-02-03", "A1-02-03", "location"),
         ("A1-2-3", "A1-02-03", "location"), ("RCG0001-RD", "RCG0001-RD", "sku"), ("RCGOOO1 RD", "RCG0001-RD", "sku"),
         ("RCG0OO3-YL", "RCG0003-YL", "sku"), ("rcg0004gn", "RCG0004-GN", "sku"),
         ("TH0112345678B", "TH0112345678B", "tracking"), ("TH O112345678B", "TH0112345678B", "tracking"), ("THO1I2345678B", "TH0112345678B", "tracking"),
         ("TH011234S678B", "TH0112345678B", "tracking"), ("TH01123456788", "TH0112345678B", "tracking"), ("Tracking No. TH0112345678B", "TH0112345678B", "tracking"),
         ("TH011234567B", "TH0112345678B", "tracking"),
         ("2410153ABCDEFG", "2410153ABCDEFG", "order"), ("24101S3A8CDEFG", "2410153ABCDEFG", "order"), ("Order: 2410153ABCDEFG", "2410153ABCDEFG", "order")]
bad = []
for text, want, typ in CASES:
    r = textmatch.match(text)
    if not r or r[0]["code"] != want or r[0]["type"] != typ or r[0]["conf"] < 0.6:
        bad.append((text, r[:2]))
ok(not bad, f"fuzzy text → codes ({len(CASES) - len(bad)}/{len(CASES)}) {bad}")
ok(textmatch.match("hello world") == [] and textmatch.match("12") == [], "garbage gives nothing")
ok(textmatch.match("Z9-09-09")[0]["type"] == "location?", "unknown location still normalised (low conf)")
r = C.get("/api/recog/text?q=A1-O2-O3").get_json()
ok(r["best"]["code"] == "A1-02-03", f"text api best {r}")
r = C.get("/api/recog/text?q=Z9-09-09").get_json()
ok(r["best"] is None and r["candidates"], "text api: not in system → no auto pick")

# ---- 手机扫码：容错（fuzzy=1）
r = C.get("/api/mobile/resolve?code=A1-O2-O3&fuzzy=1").get_json()
ok(r["type"] == "location" and r["fuzzy"]["from"] == "A1-O2-O3", f"mobile resolve fuzzy location {r.get('type')} {r.get('fuzzy')}")
r = C.get("/api/mobile/resolve?code=THO1I2345678B&fuzzy=1").get_json()
ok(r["type"] == "order" and r["order"]["order_no"] == "2410153ABCDEFG", f"mobile resolve fuzzy tracking {r.get('type')}")
ok(C.get("/api/mobile/resolve?code=THO1I2345678B").get_json()["type"] == "unknown", "without fuzzy unchanged")
r = C.get("/api/mobile/resolve?code=ZZZZ-NOPE&fuzzy=1").get_json()
ok(r["type"] == "unknown" and r["suggest"] == [], "fuzzy unknown → empty suggest")

# ---- 手机 App 的正则（/api/mobile/code-patterns）
r = P.get("/api/mobile/code-patterns")
d = r.get_json()
ok(r.status_code == 200 and d["enabled"] and len(d["patterns"]) >= 4, f"code patterns {len(d.get('patterns', []))}")
rx = [re.compile(p["re"]) for p in d["patterns"]]
for s_ in ("A1-02-03", "A1-O2-O3", "RCG0001-RD", "TH0112345678B", "THO1I2345678B", "2410153ABCDEFG", "3DP0001-WH", "3DPOO01-WH"):
    ok(any(x.match(s_) for x in rx), f"pattern matches {s_}")
ok(not any(x.match(w) for x in rx for w in ("HELLO", "ราคา", "FLASH", "OLD-LOG", "SOLD")), "patterns skip normal words")
ok(all("(?P" not in p["re"] and "(?<" not in p["re"] for p in d["patterns"]), "java-compatible regex")

# ---- 拍照读文字：条码 + 假 AI OCR
import zxingcpp
try:
    bim = zxingcpp.write_barcode_to_image(zxingcpp.create_barcode("TH0112345678B", zxingcpp.BarcodeFormat.Code128))
except AttributeError:          # 旧版 zxing-cpp
    bim = zxingcpp.write_barcode(zxingcpp.BarcodeFormat.Code128, "TH0112345678B")
bim = Image.fromarray(np.asarray(bim)).convert("RGB").resize((600, 160))
canvas = Image.new("RGB", (800, 400), (240, 240, 240)); canvas.paste(bim, (100, 100))
buf = io.BytesIO(); canvas.save(buf, "JPEG", quality=90)
r = C.post("/api/recog/ocr", data={"photo": (io.BytesIO(buf.getvalue()), "l.jpg")}, content_type="multipart/form-data").get_json()
ok(r["barcodes"] == ["TH0112345678B"] and r["candidates"][0]["code"] == "TH0112345678B" and r["best"], f"barcode read {r['barcodes']} {r['candidates'][:1]}")
sign = synth.text_image("A1-O2-O3", rng, angle=8, blur=1.0)
config.save_config({"recog_ai": "on"})
ai_copy._request = lambda cfg, system, user, img=None: json.dumps({"lines": ["货位 LOC", "Al-O2-O3"]})
try:
    r = ocr.read(sign, engine=None) if not ocr.engines() else ocr.read(sign)
    ok(r["candidates"] and r["candidates"][0]["code"] == "A1-02-03", f"ocr (AI) sign → location {r['engine']} {r['lines']} {r['candidates'][:1]}")
    # 条码坏了，下面的字还能用
    lab = synth.text_image("TH0112345678B", rng, angle=-5, barcode=True)
    ai_copy._request = lambda cfg, system, user, img=None: json.dumps({"lines": ["Flash Express", "TH O112345678B"]})
    r = C.post("/api/recog/ocr", data={"photo": (io.BytesIO(lab), "l.jpg")}, content_type="multipart/form-data").get_json()
    ok(r["candidates"] and r["candidates"][0]["code"] == "TH0112345678B", f"damaged barcode → printed text {r['candidates'][:1]}")
finally:
    ai_copy._request = orig
config.save_config({"recog_ai": "off", "recog_ocr_ai": False})
r = ocr.read(sign)
ok(r["error"] or r["engine"] in ("rapidocr", "tesseract"), f"no OCR engine → clear message {r['error']}")
config.save_config({"recog_ocr_ai": True})

# ---- 权限
ok(anon.post("/api/recog/identify").status_code == 401 and anon.get("/api/recog/status").status_code == 401, "needs login")
ok(anon.get("/m/recog/m_recog.js").status_code == 200 and anon.get("/m/recog/recog_ui.js").status_code == 200, "phone scripts public (no data)")
ok(anon.get("/m/recog/page.js").status_code in (302, 401), "other module files need login")
r = P.post("/api/recog/identify", data={"photo": (io.BytesIO(photo), "p.jpg")}, content_type="multipart/form-data")
ok(r.status_code == 200, f"packer can identify {r.status_code}")
ok(P.post("/api/recog/confirm", json={"rid": r.get_json()["rid"], "sku": "RCG0003-YL"}).status_code == 200, "packer can confirm")
ok(P.get("/api/recog/text?q=A1-02-03").status_code == 200 and P.get("/api/recog/search?q=RCG").status_code == 200, "packer text + search")
ok(P.post("/api/recog/ocr", data={"photo": (io.BytesIO(buf.getvalue()), "l.jpg")}, content_type="multipart/form-data").status_code == 200, "packer ocr")
ok(P.get("/api/recog/status").status_code == 200 and "refs" not in P.get("/api/recog/status").get_json(), "packer status without library details")
ok(P.post("/api/recog/build", json={}).status_code == 403 and P.post("/api/recog/test").status_code == 403, "packer cannot rebuild / test")
ok(P.post("/api/recog/model/download", json={}).status_code == 403 and L.post("/api/recog/model/download", json={}).status_code == 403, "only owner downloads model")
r = L.post("/api/recog/test", data={"photo": (io.BytesIO(photo), "RCG0003-YL_1.jpg")}, content_type="multipart/form-data").get_json()
ok(r["truth"] == "RCG0003-YL" and r["rank"] == 1, f"test page: truth from filename, rank {r.get('rank')}")
r = L.post("/api/recog/test", data={"photo": (io.BytesIO(photo), "x.jpg"), "truth": "RCG0002-BL"}, content_type="multipart/form-data").get_json()
ok(r["truth"] == "RCG0002-BL" and r["rank"] != 1, "test page: wrong truth → not rank 1")
ok(L.post("/api/recog/build", json={"pids": ["RCG0002"]}).get_json()["started"] in (True, False), "listing can rebuild")

# ---- 1.1 撤销刚才的确认、参考照片管理（看 / 删 / 改 SKU）
r = P.post("/api/recog/identify", data={"photo": (io.BytesIO(odd), "p.jpg")}, content_type="multipart/form-data").get_json()
ok(P.post("/api/recog/confirm", json={"rid": r["rid"], "sku": "RCG0004-GN"}).get_json()["learned"], "packer confirm (wrong) learned")
n_wrong = len(refs.list_learned("RCG0004"))
ok(n_wrong == 1, f"wrong photo stored under RCG0004 {n_wrong}")
ok(P.post("/api/recog/unconfirm", json={"rid": r["rid"]}).status_code == 200 and len(refs.list_learned("RCG0004")) == 0, "undo removes learned photo")
row = db.conn().execute("SELECT chosen, learned FROM recog_log WHERE rid=?", (r["rid"],)).fetchone()
ok(row["chosen"] is None and row["learned"] is None, "undo clears choice")
ok(P.post("/api/recog/confirm", json={"rid": r["rid"], "sku": "RCG0002-BL"}).get_json()["learned"], "re-pick after undo")
n2 = len(refs.list_learned("RCG0002"))
ok(P.post("/api/recog/confirm", json={"rid": r["rid"], "sku": "RCG0002-BL"}).status_code == 200 and len(refs.list_learned("RCG0002")) == n2, "confirm twice keeps one photo")
r2 = C.post("/api/recog/identify", data={"photo": (io.BytesIO(odd), "p.jpg")}, content_type="multipart/form-data").get_json()
C.post("/api/recog/confirm", json={"rid": r2["rid"], "sku": "RCG0002-BL"})
ok(P.post("/api/recog/unconfirm", json={"rid": r2["rid"]}).status_code == 400, "packer cannot undo someone else's")
db.conn().execute("UPDATE recog_log SET chosen_at=chosen_at-3600 WHERE rid=?", (r["rid"],)); db.conn().commit()
ok(P.post("/api/recog/unconfirm", json={"rid": r["rid"]}).status_code == 400, "packer cannot undo after 10 minutes")
d = C.get("/api/recog/learned?q=RCG0002").get_json()
ok(d["total"] >= 2 and all(x["pid"] == "RCG0002" and x["info"]["sku"] == "RCG0002-BL" for x in d["rows"]), f"learned list by product {d['total']}")
ok(C.get("/api/recog/learned?q=RCG0002-BL").get_json()["total"] == d["total"], "learned list by sku")
ok(C.get(d["rows"][0]["url"]).status_code == 200, "learned photo served")
x = d["rows"][0]
r = C.post("/api/recog/learned/move", json={"pid": x["pid"], "file": x["file"], "sku": "RCG0003-YL"}).get_json()
ok(r["ok"] and r["pid"] == "RCG0003" and any(y["file"] == r["file"] for y in refs.list_learned("RCG0003", "RCG0003-YL")), f"moved to other product {r}")
ok(any(m_["kind"] == "photo" and m_["src"] == r["file"] and "RCG0003-YL" in m_["skus"] for m_ in refs.index()["meta"]), "refs rebuilt after move")
ok(C.post("/api/recog/learned/move", json={"pid": "RCG0003", "file": r["file"], "sku": "NOPE-1"}).status_code == 400, "move to unknown sku refused")
ok(C.post("/api/recog/learned/delete", json={"pid": "RCG0003", "file": r["file"]}).get_json()["ok"] and all(y["file"] != r["file"] for y in refs.list_learned("RCG0003")), "delete learned")
ok(not any(m_["kind"] == "photo" and m_["src"] == r["file"] for m_ in refs.index()["meta"]), "refs rebuilt after delete")
ok(C.post("/api/recog/learned/delete", json={"pid": "RCG0003", "file": "x/../../app.db"}).status_code == 400, "no traversal on delete")
ok(P.get("/api/recog/learned").status_code == 403 and P.post("/api/recog/learned/delete", json={}).status_code == 403, "packer cannot manage learned photos")
ok(L.get("/api/recog/learned").status_code == 200, "listing can manage learned photos")

# ---- 随机色 / 透明的规格：提醒员工自己看，不自动用
synth.make_product("RCG0005", "测试heart", S["heart"], ["透明", "随机颜色"])
refs.build_product("RCG0005")
config.save_config({"recog_ai": "off"})
hp = synth.photo(S["heart"], synth.PALETTE["红色"], rng, ())
d = C.post("/api/recog/identify", data={"photo": (io.BytesIO(hp), "p.jpg")}, content_type="multipart/form-data").get_json()
top3 = [c_["sku"] for c_ in d["candidates"][:3]]
ok(any(s_.startswith("RCG0005") for s_ in top3), f"weak product in top 3 {top3}")
ok(d["need_pick"] and d["hint"] and set(d["hint"]["kinds"]) & {"clear", "random"} and "ใส" in d["hint"]["th"], f"weak hint + no auto-accept {d.get('hint')}")
ok(match.weak_kind("透明") == "clear" and match.weak_kind("随机颜色") == "random" and match.weak_kind("红色") == "", "weak colours")

# ---- 设置：关掉
config.save_config({"recog_on": False})
ok(C.post("/api/recog/identify", data={"photo": (io.BytesIO(photo), "p.jpg")}, content_type="multipart/form-data").status_code == 400, "off → refused")
ok(C.get("/api/mobile/code-patterns").get_json()["patterns"] == [], "off → app gets no text patterns")
config.save_config({"recog_on": True})
ok(C.get("/api/modules").status_code == 200 and any(m["id"] == "recog" for m in C.get("/api/modules").get_json()["modules"]), "module listed")
C.post("/api/modules/recog", json={"on": False})
ok(C.get("/api/recog/status").status_code == 404 and C.get("/api/mobile/code-patterns").get_json()["enabled"] is False, "module off → 404 / no patterns")
ok(C.get("/api/mobile/resolve?code=A1-O2-O3&fuzzy=1").get_json()["type"] == "unknown", "module off → resolver exact only")
C.post("/api/modules/recog", json={"on": True})

# 手机页带上识别按钮的脚本
ok(b"/m/recog/m_recog.js" in anon.get("/m").data, "phone page loads recog script")
print(f"ERRORS {E_}")
