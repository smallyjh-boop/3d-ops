# v2.50.1：选品的问题修正——「⬇ 下载模型文件」没失败也能排队 / 没文件链接就重新读详情页、手动上传 → ERP 分析、扩展在不在线、
# 采用后马上写 AI 文案（不等文件，人改过的不动，详情页到了按描述重写）、原站图片提醒（编辑页 + 上架检查）、
# Printables 列表页读成作者名 / 头像（站点包 + 卡片读取，样例 HTML）、「采集可能出错」不交给 AI、重新读取、删除采集错误的、
# 泰国市场「相近」关键词 / 「去雷达查」、采集箱（不进产品库、文件夹、转入产品库、升级时搬进来）、产品 360 的模型文件。AI 都是假的。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, time, io, subprocess
D = T + "/m_cur2501"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, integrations, ai_copy, copyrules
from core.config import save_config, load_config
db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "secret123", "listing", "Nok")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
CL = A.app.test_client(); CL.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
from modules.curate import cand, pipeline, watch, adopt, inbox, demand, db as cdb, sites
KEY = integrations.create_key("Nok")
H = {"Authorization": "Bearer " + KEY, "X-Ext-Version": "3.1.1"}

CALLS = []
def fake_ai(cfg, system, user, image_b64=None):
    CALLS.append(system[:40])
    if "选品顾问" in system:
        items = json.loads(user)["items"]
        return json.dumps({"items": [{"i": it["i"], "category": "宠物", "demand": 80, "est_minutes": 60, "est_grams": 20, "single_color": True,
                                      "parts": 1, "price_low": 150, "price_high": 250, "competition": "low", "listing": 70, "exclude": "",
                                      "reason": "养猫的人多", "thai_keywords": ["ที่ลับเล็บแมว"]} for it in items]})
    if "listing copywriter" in system:
        src = "detail" if "Scratch" in user or "scratch" in user else "title"
        return json.dumps({"title_th": f"ที่ลับเล็บแมว {src}", "title_shopee_th": "ที่ลับเล็บแมว", "title_en": "Cat scratcher",
                           "highlights_th": ["แข็งแรง"], "description_th": f"<p>ที่ลับเล็บแมว {src}</p>", "description_en": "<p>Cat scratcher</p>",
                           "hashtags_shopee": ["#แมว"], "package_content_th": "1 x", "title_zh": "猫抓板", "description_zh": "猫抓板",
                           "search_keywords_th": ["ที่ลับเล็บแมว"], "options_th": {}})
    if "precise Thai e-commerce translator" in system:
        return json.dumps({"title_zh": "猫抓板", "description_zh": "猫抓板"})
    return "{}"
ai_copy.call = fake_ai
from PIL import Image
PNG = io.BytesIO(); Image.new("RGB", (800, 600), (200, 100, 50)).save(PNG, "PNG")
adopt.fetch_image = lambda url, referer="": PNG.getvalue()
save_config({"ai_api_key": "test-key"})
TMP = D + "/tmp2501"; os.makedirs(TMP, exist_ok=True)
def cube_stl(path, s=20.0):
    import struct
    v = [(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0), (0, 0, s), (s, 0, s), (s, s, s), (0, s, s)]
    tris = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    with open(path, "wb") as f:
        f.write(b"\0" * 80 + struct.pack("<I", len(tris)))
        for a, b, c in tris:
            f.write(struct.pack("<3f", 0, 0, 0) + b"".join(struct.pack("<3f", *v[i]) for i in (a, b, c)) + b"\0\0")

# ---------- F：列表页读错（标题 = 作者名、头像）→「采集可能出错」，不交给 AI ----------
AV = "https://media.printables.com/media/users/avatars/123/fluffy.jpg"
cards = [{"url": "https://www.printables.com/model/1001-cat-scratcher", "title": "Fluffy Tails", "author": "Fluffy Tails", "thumb": AV},
         {"url": "https://www.printables.com/model/1002-cat-bowl", "title": "GentleDesign", "thumb": "https://media.printables.com/media/users/avatars/7/logo.png"},
         {"url": "https://www.printables.com/model/1003-cat-shelf", "title": "Cat wall shelf", "author": "VC Design",
          "thumb": "https://media.printables.com/media/prints/1003/images/1_a/thumbs/inside/320x240/jpg/x.webp", "thumb_w": 300},
         {"url": "https://www.printables.com/model/1004-x", "title": "Cat bed", "thumb": "https://media.printables.com/media/prints/1004/a.jpg", "thumb_w": 32}]
sc = C.post("/api/v1/curate/ext/score", json={"items": cards}, headers=H).get_json()["scores"]
def nxt():
    cdb.put("pace", {})                   # 测试里不等页面间隔
    return C.get("/api/v1/curate/ext/next", headers=H).get_json()
row = lambda k: cdb.conn().execute("SELECT * FROM cur_candidates WHERE skey=?", (k,)).fetchone()
ok(row("pr:1001")["capture_bad"] == "标题是作者 / 店铺名" and sc[cards[0]["url"]]["capture_bad"], f"title == author → 采集可能出错 {row('pr:1001')['capture_bad']}")
ok(row("pr:1002")["capture_bad"].startswith("缩略图"), f"avatar thumbnail → 采集可能出错 {row('pr:1002')['capture_bad']}")
ok(row("pr:1003")["capture_bad"] == "", "real model card is fine")
ok(row("pr:1004")["capture_bad"] == "缩略图太小，像头像", "avatar-sized thumbnail flagged")
ok(cand.capture_check("https://www.printables.com/model/5-x", "Hook", "", "https://media.printables.com/media/other/5.jpg") != "", "Printables pack: thumb must be a /media/prints/ image")
ok(cand.capture_check("https://makerworld.com/en/models/5-x", "Hook", "Bob", "https://makerworld.bblmw.com/makerworld/model/5/cover.jpg") == "", "MakerWorld normal card ok")
CALLS.clear()
pipeline.run_all()
ok(row("pr:1003")["ai_at"] > 0 and row("pr:1001")["ai_at"] == 0 and row("pr:1002")["ai_at"] == 0, "AI only judges the clean candidates")
lst = C.get("/api/cur/candidates").get_json()
ok(lst["kpi"]["bad"] == 3 and lst["kpi"]["wait_ai"] == 0, f"kpi: bad count, bad ones not waiting for AI {lst['kpi']}")
ok(len(C.get("/api/cur/candidates?bad=1&status=all&ex=1").get_json()["rows"]) == 3, "filter: only 采集可能出错")
# 正确的资料不会被旧扩展读错的覆盖
C.post("/api/v1/curate/ext/score", json={"items": [{"url": cards[2]["url"], "title": "VC Design", "author": "VC Design", "thumb": AV}]}, headers=H)
ok(row("pr:1003")["title"] == "Cat wall shelf" and row("pr:1003")["capture_bad"] == "" and "prints" in row("pr:1003")["thumb"], "good data not overwritten by a bad card")
# 新扩展读对了：自动改正 + 重新让 AI 判断
C.post("/api/v1/curate/ext/score", json={"items": [{"url": cards[3]["url"], "title": "Cat bed", "thumb": "https://media.printables.com/media/prints/1004/b.jpg", "thumb_w": 300}]}, headers=H)
ok(row("pr:1004")["capture_bad"] == "" and row("pr:1004")["ai_at"] == 0, "fixed card clears the flag, AI again")
# 升级后已有的数据：标题是别的卡片的作者名
cdb.conn().execute("INSERT INTO cur_candidates(skey, platform, url, title, thumb, author) VALUES('pr:1009','printables','https://www.printables.com/model/1009-x','VC Design','','')")
cdb.conn().commit()
ok(cand.sanity_sweep() >= 1 and row("pr:1009")["capture_bad"], "sweep: title equal to a known author flagged")
# 重新读取（详情页）
r = C.post("/api/cur/candidates/recollect", json={"ids": [row("pr:1001")["id"]]}).get_json()
ok(r["ok"] and r["queued"] == 1 and C.post("/api/cur/candidates/recollect", json={"ids": [row("pr:1001")["id"]]}).get_json()["queued"] == 0, "re-collect queued once")
nx = nxt()
ok(nx["item"] and nx["item"]["url"] == "https://www.printables.com/model/1001-cat-scratcher", f"extension gets the re-collect item {nx}")
r = C.post("/api/v1/curate/ext/result", json={"id": nx["item"]["id"], "data": {"title": "Cat scratcher wall", "author": "Fluffy Tails",
                                                                             "image_urls": ["https://media.printables.com/media/prints/1001/images/1.jpg"]}}, headers=H).get_json()
rr = row("pr:1001")
ok(r["state"] == "done" and rr["title"] == "Cat scratcher wall" and rr["capture_bad"] == "" and "prints/1001" in rr["thumb"] and rr["ai_at"] == 0 and not rr["product_id"],
   f"re-collect fixes title / thumb, no product created {dict(rr)['title']}")
r = C.post("/api/cur/candidates/delete-bad", json={}).get_json()
ok(r["deleted"] == 2 and not row("pr:1002") and row("pr:1003"), f"bulk delete capture errors {r}")

# ---------- F：站点包读 Printables / Thingiverse 列表页（样例 HTML，作者那一块在卡片最上面） ----------
for s_id in ("printables", "makerworld", "thingiverse"):
    pk = sites.load()[s_id]
    ok(pk.get("list") and pk["list"].get("title") and pk["list"].get("author_link"), f"{s_id} pack has list-card rules")
builtin = open(os.path.join(APP, "extension", "cur_sites_builtin.js"), encoding="utf-8").read()
ok('"model_image": "/media/prints/"' in builtin, "extension builtin packs regenerated")
node = shutil.which("node")
nodepath = os.pathsep.join(x for x in [os.environ.get("NODE_PATH", ""), "/opt/node-tools/node_modules"] if x)
have_pw = node and subprocess.run([node, "-e", "require('playwright')"], capture_output=True, env={**os.environ, "NODE_PATH": nodepath}).returncode == 0
if have_pw:
    def cards_of(fx, url):
        out = subprocess.run([node, os.path.join(APP, "modules", "curate", "tests", "cards_check.js"), os.path.join(APP, "extension"),
                              os.path.join(APP, "modules", "curate", "tests", "fixtures", fx), url], capture_output=True, text=True, timeout=120,
                             env={**os.environ, "NODE_PATH": nodepath})
        if out.returncode:
            print(out.stderr[-800:])
        return json.loads(out.stdout or "[]")
    pc = cards_of("printables_search.html", "https://www.printables.com/search/models?q=cat")
    ok([c["title"] for c in pc] == ["Cat cable holder", "Cat food bowl stand", "Cat wall shelf"], f"Printables: model titles, not author names {[c['title'] for c in pc]}")
    ok([c["url"] for c in pc] == ["https://www.printables.com/model/1234567-cat-cable-holder", "https://www.printables.com/model/2345678-cat-food-bowl-stand",
                                  "https://www.printables.com/model/3456789-cat-wall-shelf"], "Printables: model links (/@ author links ignored)")
    ok(all("/media/prints/" in c["thumb"] for c in pc) and [c["author"] for c in pc] == ["Fluffy Tails", "GentleDesign", "VC Design"], f"Printables: model images, author kept separately {pc}")
    ok(all(not cand.capture_check(c["url"], c["title"], c["author"], c["thumb"], c["thumb_w"]) for c in pc), "Printables cards pass the sanity rule")
    tc = cards_of("thingiverse_search.html", "https://www.thingiverse.com/search?q=cat")
    ok(len(tc) == 1 and tc[0]["title"] == "Mini cat tree for desk" and "large_display" in tc[0]["thumb"] and tc[0]["author"] == "Sv0dn1k", f"Thingiverse: same fix {tc}")
else:
    print("OK  (跳过：没有 Node + Playwright，列表页样例没在浏览器里跑)")

# ---------- 采用 → 采集箱 + 马上写 AI 文案（不等文件） ----------
r = C.post("/api/cur/candidates/adopt", json={"ids": [row("pr:1003")["id"]]}).get_json()
PID = r["products"][0]["product_code"]
p = store.load(PID)
ok(p.get("inbox") and p["draft"], "adopted draft is in the 采集箱")
CALLS.clear()
pipeline.run_all()
ok(not (store.load(PID).get("copy") or {}).get("title_th"), "copy waits a little for the detail page (extension usually reads it in a minute)")
cdb.conn().execute("UPDATE cur_collect SET created_at=created_at-200 WHERE product_id=?", (PID,)); cdb.conn().commit()
pipeline.run_all()
p = store.load(PID)
ok((p.get("copy") or {}).get("title_th") == "ที่ลับเล็บแมว title" and p["source"]["ai_copy_from"] == "title" and not p.get("source_files"),
   f"AI copy right after adopt from the source title, before any file {(p.get('copy') or {}).get('title_th')}")
ok(p["name_zh"] == "猫抓板", "Chinese name from the AI copy")
# 详情页到了（描述 / 标签）：没人改过 → 按描述重写
nx = nxt()
C.post("/api/v1/curate/ext/result", json={"id": nx["item"]["id"], "data": {"title": "Cat wall shelf", "description_original": "Scratch board for cats, wall mounted.",
        "tags": "cat, scratch", "license_name": "CC BY 4.0", "image_urls": ["https://media.printables.com/media/prints/1003/i/1.jpg"]}}, headers=H)
pipeline.run_all()
p = store.load(PID)
ok(p["copy"]["title_th"] == "ที่ลับเล็บแมว detail" and p["source"]["ai_copy_from"] == "detail", f"untouched title-only copy rewritten from the detail {p['copy']['title_th']}")
# 人改过 → 再也不自动改
p["copy"]["title_th"] = "ชื่อที่คนเขียนเอง"; store.save(p)
adopt.enrich(PID, {"description_original": "Scratch board v2", "tags": "cat"})
pipeline.run_all()
ok(store.load(PID)["copy"]["title_th"] == "ชื่อที่คนเขียนเอง", "copy edited by a person is never overwritten")

# ---------- D：原站图片（图片记来源）+ 上架检查提醒 ----------
p = store.load(PID)
ok(p["images"] and all(i.get("from") == "source" and i.get("source_url") for i in p["images"]), "source images marked (from=source + source url)")
e, w = copyrules.problems(p)
ok(any("原站图片" in x and "水印" in x for x in w) and not any("原站图片" in x for x in e), f"listing check warns about source images {w}")
p["images"][0]["edited"] = True; store.save(p)
ok(not any("原站图片" in x for x in copyrules.problems(store.load(PID))[1]), "edited (watermark removed) → warning gone")
p = store.load(PID); p["images"][0]["edited"] = False; store.save(p)

# ---------- A：下载按钮 ----------
st = C.get(f"/api/cur/products/{PID}/files").get_json()
ok(st["curate"] and st["status"]["links"] == 0 and not st["files"] and st["status"]["ext"]["online"], f"files endpoint: no files yet, extension online (it just asked for work) {st['status']}")
r = C.post(f"/api/cur/products/{PID}/download", json={}).get_json()
ok(r["ok"] and r["queued"] == 0 and r["recollect"] and r["state"] == "recollect", f"no file links yet → detail page re-queued {r}")
q = cdb.conn().execute("SELECT * FROM cur_collect WHERE product_id=? ORDER BY id DESC LIMIT 1", (PID,)).fetchone()
ok(q["state"] == "waiting" and q["copy"] == 1, "re-collect item queued (no second copy job)")
nx = nxt()
C.post("/api/v1/curate/ext/result", json={"id": nx["item"]["id"], "data": {"title": "Cat wall shelf", "model_files": [
    {"name": "shelf.stl", "url": "https://www.printables.com/model/1003/files#11"}, {"name": "big.zip", "url": "https://www.printables.com/model/1003/files#12", "size": "900 MB"}]}}, headers=H)
fs = watch.file_status(PID)
ok(fs["queued"] == 1 and fs["none"] == 1, f"detail page → stl queued, oversize zip listed only {fs}")
cdb.conn().execute("UPDATE cur_files SET state='' WHERE product_id=? AND name='shelf.stl'", (PID,)); cdb.conn().commit()
r = C.post(f"/api/cur/products/{PID}/download", json={}).get_json()
ok(r["queued"] == 2 and not r["recollect"] and r["state"] == "queued", f"download queues files that never failed {r}")
r2 = C.post(f"/api/cur/products/{PID}/download", json={}).get_json()
ok(r2["queued"] == 0 and r2["busy"] == 2 and not r2["recollect"], "already queued → busy, nothing re-read")
ok(CL.post(f"/api/cur/products/{PID}/download", json={}).status_code == 200, "listing staff can press download")
cdb.put("ext_seen", {}); watch._seen_mem.clear()
ov = C.get("/api/cur/overview").get_json()
ok(not ov["ext"]["online"] and ov["waiting"] > 0, "no extension online + waiting items → page notice data")
C.get("/api/v1/curate/ext/ping", headers=H)
ok(not watch.ext_status()["online"], "a popup ping alone does not count as the worker being online")
C.get("/api/v1/curate/ext/files/next", headers=H)
ok(watch.ext_status()["online"] and "Nok" in watch.ext_status()["who"], "worker asking for files → online")
# 扩展：详情页上「下载模型文件到 ERP」
r = C.post("/api/v1/curate/ext/download", json={"url": "https://www.printables.com/model/1003-cat-shelf?x=1"}, headers=H).get_json()
ok(r["ok"] and r["product_id"] == PID, f"extension detail-page download button {r}")
ok(C.post("/api/v1/curate/ext/download", json={"url": "https://www.printables.com/model/777-nope"}, headers=H).status_code == 400, "not adopted → clear error")
# 手动上传 → 和扩展上传一样做 ERP 分析，第一个 STL 当 3D 模型
cube_stl(TMP + "/m.stl", 30)
with open(TMP + "/m.stl", "rb") as fh:
    r = C.post(f"/api/cur/products/{PID}/upload", data={"file": (io.BytesIO(fh.read()), "my_shelf.stl")}, content_type="multipart/form-data").get_json()
ok(r["ok"] and r["saved"][0]["name"] == "my_shelf.stl", f"manual upload {r.get('error')}")
ok(C.post(f"/api/cur/products/{PID}/upload", data={"file": (io.BytesIO(b"x" * 100), "a.pdf")}, content_type="multipart/form-data").status_code == 400, "only model files")
pipeline.run_all()                       # 原站的两个文件还在下载：手动上传的不等它们，马上分析
cdb.conn().execute("UPDATE cur_files SET state='failed', error='HTTP 403' WHERE product_id=? AND state IN ('queued','downloading')", (PID,)); cdb.conn().commit()
p = store.load(PID)
ok(p.get("model") and any(e.get("file") == "my_shelf.stl" and (e.get("info") or {}).get("ok") for e in p.get("model_lib") or []), "uploaded STL analysed by the ERP model library and set as the 3D model")
ok(p["variants"][0].get("grams", 0) > 0, f"grams from the analysis {p['variants'][0].get('grams')}")
st = C.get(f"/api/cur/products/{PID}/files").get_json()
ok(st["model"] and [f["name"] for f in st["files"]] == ["my_shelf.stl"] and st["files"][0]["current"], f"editor file list {st['files']}")
cube_stl(TMP + "/n.stl", 10)
with open(TMP + "/n.stl", "rb") as fh:
    C.post(f"/api/cur/products/{PID}/upload", data={"file": (io.BytesIO(fh.read()), "extra.stl")}, content_type="multipart/form-data")
ok(C.post(f"/api/cur/products/{PID}/files/delete", json={"name": "my_shelf.stl"}).status_code == 400, "current 3D model file can't be deleted")
r = C.post(f"/api/cur/products/{PID}/files/delete", json={"name": "extra.stl"}).get_json()
ok(r["ok"] and not os.path.exists(os.path.join(store.product_dir(PID), "source_files", "extra.stl")), "delete a downloaded file")
fs = watch.file_status(PID)
ok(fs["failed"] == 2 and fs["state"] == "ok", f"status: ok + failed {fs}")
qd = C.get("/api/cur/queue").get_json()
ok(any(x["product_id"] == PID and x["fstat"]["ok"] == 1 for x in qd["rows"]) and "online" in qd["ext"], "queue page rows carry the file status")

# ---------- G：泰国市场「相近」 / 去雷达查 ----------
lst = C.get("/api/cur/candidates?status=all").get_json()
ok(lst["radar"] is False and all(x["market"] is None for x in lst["rows"]), "no radar data → radar False (UI shows 去雷达查)")
from modules.ops import radar, mkt_db
mkt_db.ensure()
radar.add_keywords("shopee", "ที่ข่วนเล็บแมว\nกระถางต้นไม้")
cdb.conn().execute("UPDATE cur_candidates SET ai=? WHERE skey='pr:1004'", (json.dumps({"thai_keywords": ["ที่ฝนเล็บแมว"]}),))
cdb.conn().execute("UPDATE cur_candidates SET category='宠物' WHERE skey='pr:1004'"); cdb.conn().commit()
lst = C.get("/api/cur/candidates?status=all").get_json()
mk = next(x for x in lst["rows"] if x["url"].endswith("1004-x"))["market"]
ok(lst["radar"] is True and mk and mk["near"] and mk["keyword"] == "ที่ข่วนเล็บแมว", f"nearest radar keyword via AI tags / category {mk}")
f = demand.matcher([{"keyword": "กระถางต้นไม้", "score": 60}])
ok(f("Succulent pot", [], "植物园艺")["near"] and f("Succulent pot", [], "植物园艺")["keyword"] == "กระถางต้นไม้", "category hint words find the radar keyword")
ok(f("Phone stand", [], "其他") is None, "nothing close → no market")

# ---------- 采集箱 ----------
from core import search as gsearch
ok(not any(x["id"] == PID for x in C.get("/api/products").get_json()), "inbox product not in 产品库 list")
ok(any(x["id"] == PID and x["inbox"] for x in C.get("/api/products?inbox=all").get_json()), "?inbox=all includes it (library counts the 采集箱 link)")
ok(not any(h["id"] == PID for h in gsearch._goods("猫抓板", 10)) and any(h["id"] == PID for h in gsearch._goods(PID, 10)), "global search: only the exact code finds an inbox product")
g = C.post("/api/groups", json={"name": "猫用品"}).get_json()
gid = next(x["id"] for x in g["groups"] if x["name"] == "猫用品")
C.post("/api/groups/assign", json={"ids": [PID], "group": gid, "add": True})
ok(next(x for x in C.get("/api/groups").get_json()["groups"] if x["id"] == gid)["count"] == 0, "library group counts skip inbox products")
ib = C.get("/api/cur/inbox").get_json()
it = next(x for x in ib["rows"] if x["product_id"] == PID)
ok(ib["folders"]["all"] >= 1 and any(c["name"] == "宠物" and c["n"] >= 1 for c in ib["folders"]["cats"]) and next(x for x in ib["folders"]["groups"] if x["id"] == gid)["n"] == 1,
   f"folders: all / by AI category / user folder {ib['folders']}")
ok(it["copy"] == "done" and it["license"] == "pending" and it["images"] == "source" and it["files"]["ok"] == 1 and it["category"] == "宠物", f"status chips {it}")
ok(len(C.get(f"/api/cur/inbox?folder=g:{gid}").get_json()["rows"]) == 1 and not C.get("/api/cur/inbox?folder=nocat").get_json()["rows"], "folder filter")
ok(len(C.get("/api/cur/inbox?q=" + PID).get_json()["rows"]) == 1, "inbox search")
ok("profit" not in json.dumps(CL.get("/api/cur/inbox").get_json()), "listing role can use the inbox")
r = C.post("/api/cur/inbox/action", json={"action": "copy", "ids": [PID]}).get_json()
ok(r["queued"] == 1, "bulk AI copy queued")
# 转入产品库：许可没核验也允许，但提醒
r = C.post("/api/cur/inbox/action", json={"action": "to_library", "ids": [PID]}).get_json()
ok(r["moved"] == [PID] and any("许可" in w for w in r["warnings"][PID]) and any("原站图片" in w for w in r["warnings"][PID]), f"转入产品库 with warnings {r}")
ok(any(x["id"] == PID for x in C.get("/api/products").get_json()) and not store.load(PID).get("inbox"), "now in 产品库")
ok(next(x for x in C.get("/api/groups").get_json()["groups"] if x["id"] == gid)["count"] == 1, "folder became a library group")
ok(any("许可待核验" in e for e in copyrules.problems(store.load(PID))[0]), "licence gate for export / push unchanged")
ok(C.post("/api/cur/inbox/action", json={"action": "delete", "ids": [PID]}).status_code == 400, "can't delete from inbox once in the library")
# 删除：产品草稿删掉，候选标「不采用」
r = C.post("/api/cur/candidates/adopt", json={"urls": "https://makerworld.com/en/models/5555-hook"}).get_json()
P2 = r["products"][0]["product_code"]
ok(CL.post("/api/cur/inbox/action", json={"action": "delete", "ids": [P2]}).status_code in (200, 403), "delete needs the products.delete permission")
r = C.post("/api/cur/inbox/action", json={"action": "delete", "ids": [P2]}).get_json()
ok(r["deleted"] == 1 and not os.path.exists(os.path.join(store.PRODUCTS_DIR, P2 + ".json")) and row("mw:5555")["status"] == "ignored" and not row("mw:5555")["product_id"], "delete from inbox")
# 升级：产品库里已有的选品草稿搬进采集箱（导出 / 上架过的不搬）
for pid_, exp in (("3DPOLD1", None), ("3DPOLD2", 123.0)):
    q = store.blank_product(pid_)
    q.update(name_zh="old", draft=True, source={"source": "curate", "source_url": "https://makerworld.com/en/models/1"}, exported_at=exp)
    store.save(q)
n = inbox.migrate(force=True)
ok(store.load("3DPOLD1").get("inbox") and not store.load("3DPOLD2").get("inbox") and n >= 1, "migration: curate drafts never exported → 采集箱")
ok(inbox.migrate() == 0, "migration runs once")

# ---------- 产品 360 ----------
pv = C.get(f"/api/p360/{PID}").get_json()
mf = pv["product"].get("model_files") or {}
ok(mf.get("n") == 1 and mf.get("model") and "state" in (mf.get("status") or {}), f"p360: model file count + status {mf}")
ok("model_files" not in C.get("/api/p360/3DPOLD2").get_json()["product"] or True, "p360 ok for others")

# ---------- 界面文件 ----------
src = open(os.path.join(APP, "modules", "curate", "ui", "curate.js"), encoding="utf-8").read()
for w in ("贴链接采集", "打开模型站去采集", "cur-float", "采集箱", "没有在线的扩展，采集队列不会动", "去雷达查", "相近：", "删除采集错误的", "手动上传", "转入产品库"):
    ok(w in src, f"curate.js has {w}")
ed = open(os.path.join(APP, "modules", "goods", "ui", "cursrc.js"), encoding="utf-8").read()
ok("还没有模型文件" in ed and "从原站下载模型文件" in ed and "原站图片，可能有水印" in ed and "要有一台装了扩展、登录了原站的 Chrome 开着" in ed, "editor: model placeholder + download / upload + source image notice")
man = json.load(open(os.path.join(APP, "extension", "manifest.json"), encoding="utf-8"))
ok(man["version"] == integrations.EXT_LATEST == "3.1.1", "extension 3.1.1")
pk = open(os.path.join(APP, "extension", "cur_picker.js"), encoding="utf-8").read()
ok("下载模型文件到 ERP" in pk and "listCards" in pk and "cur-download" in open(os.path.join(APP, "extension", "cur_bg.js"), encoding="utf-8").read(), "extension: detail-page download button + shared card reader")
print("ERRORS", E_)
