# 场景图改进（v2.53）：类目模板推荐、AI 写提示词（看产品图）、多张候选 + AI 质检、参考图改图 / 不能改图时贴真实产品、
# 多尺寸、挑图加入商品图（不裁成方图）、费用（先估 / 实际）、批量（进度、取消、自动加入）、模板编辑、旧接口、权限。全部用假 AI。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import base64, io, json, os, shutil, sqlite3, sys, time
D = T + "/m_scene253"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)


import requests
from PIL import Image
import app as A
from core import ai, ai_copy, config, db, scene_ai, store

db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "pass123", "listing", "Nok")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
N = A.app.test_client(); N.post("/api/auth/login", json={"username": "nok", "password": "pass123"})


def png(img):
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()


# 产品：白底上一个红色竖长方块（宽 200 高 400）
prod = Image.new("RGB", (800, 800), "white")
prod.paste((220, 20, 20), (300, 200, 500, 600))
pid = "SCN0001"
p = store.blank_product(pid)
p.update(name_zh="手机支架", category={"id": 1, "name": "Phone Stand 手机支架"})
with open(os.path.join(store.image_dir(pid, "out"), "w.jpg"), "wb") as f:
    prod.save(f, "JPEG", quality=95)
p["images"] = [{"file": "w.jpg", "raw": "w.jpg", "processed": True, "color": ""}]
store.save(p)
pid2 = "SCN0002"
q = store.blank_product(pid2); q.update(name_zh="儿童玩具 fidget"); q["images"] = [{"file": "w.jpg", "raw": "w.jpg", "processed": True}]
shutil.copy(os.path.join(store.image_dir(pid, "out"), "w.jpg"), os.path.join(store.image_dir(pid2, "out"), "w.jpg"))
store.save(q)

# ---------------- 假出图服务商 ----------------
BG = Image.new("RGB", (1024, 1024), (40, 90, 200))
EDITED = Image.new("RGB", (1536, 1024), (40, 90, 200)); EDITED.paste((220, 20, 20), (700, 300, 836, 700))
CALLS = []


class R:
    def __init__(self, code, data=None, content=b""):
        self.status_code, self._d, self.content, self.text = code, data, content, json.dumps(data or {})

    def json(self):
        return self._d


FAIL = {"n": 0}


def fake_post(url, **kw):
    CALLS.append((url, kw))
    if FAIL["n"] > 0:
        FAIL["n"] -= 1
        return R(500, {"error": "boom"})
    if url.endswith("/images/edits"):
        return R(200, {"data": [{"b64_json": base64.b64encode(png(EDITED)).decode()}]})
    if url.endswith("/images/generations"):
        return R(200, {"data": [{"b64_json": base64.b64encode(png(BG)).decode()}]})
    if "fal.run" in url:
        return R(200, {"images": [{"url": "https://cdn.example/bg.png"}]})
    return R(404, {})


requests.post = fake_post
requests.get = lambda url, **kw: R(200, {}, content=png(BG))

TXT = []


def fake_call(cfg, system, user, image_b64=None):
    TXT.append((cfg.get("_ai_task"), system[:40], bool(image_b64)))
    if system == scene_ai.PROMPT_SYS:
        n = json.loads(user.split("\n")[0])["how_many"]
        return json.dumps({"scenes": [f"on a teak table in a Bangkok condo variant {i}" for i in range(n)]})
    if system == scene_ai.QA_SYS:
        bad = len([t for t in TXT if t[0] == "scene_qa"]) % 2 == 0      # 每隔一张说不合格
        return json.dumps({"score": 35 if bad else 88, "shape_ok": not bad, "color_ok": True, "no_text": True, "realistic": True,
                           "issues_zh": "形状变了" if bad else "", "issues_th": "รูปทรงเปลี่ยน" if bad else ""})
    return "{}"


ai_copy.call = fake_call
ai_copy._request = fake_call
config.save_config({"ai_provider": "anthropic", "ai_api_key": "sk-ant-test-123456", "image_provider": "openai",
                    "ai_providers": {"openai": {"api_key": "sk-oai-test-123456", "image_model": "gpt-image-1"},
                                     "fal": {"api_key": "fal-test-123456"}}})

# ---------------- 模板 ----------------
tp = C.get("/api/scenes/templates").get_json()
keys = [t["key"] for t in tp["templates"]]
ok({"thai_condo", "tropical_wood", "minimal_white", "kids_room", "desk_office", "outdoor"} <= set(keys) and tp["aspects"] == ["1:1", "3:4", "4:3", "16:9", "9:16"],
   "default Thai home templates + aspects")
ok(scene_ai.suggest(config.load_config(), store.load(pid))[0] == "desk_office" and scene_ai.suggest(config.load_config(), store.load(pid2))[0] == "kids_room",
   "template suggested by category / name")

# ---------------- 估费用 ----------------
est = C.post("/api/scenes/estimate", json={"products": 1, "n": 3, "qa": True, "ai_prompt": True}).get_json()
ok(est["count"] == 3 and est["images"] > 0 and est["qa"] > 0 and est["prompt"] > 0 and abs(est["total"] - (est["images"] + est["qa"] + est["prompt"])) < 0.02,
   f"estimate before running {est}")

# ---------------- 参考图改图（OpenAI 图片编辑）----------------
cand0 = C.get(f"/api/products/{pid}/scene-cands").get_json()
ok(cand0["cands"] == [] and cand0["suggest"][0] == "desk_office" and cand0["ready"]["image"] and cand0["ready"]["qa"], "candidates panel status")
CALLS.clear(); TXT.clear()
r = C.post(f"/api/products/{pid}/scene-gen", json={"template": "thai_condo", "aspect": "16:9", "n": 2}).get_json()
ok(len(r["cands"]) == 2 and all(c["mode"] == "edit" and c["aspect"] == "16:9" for c in r["cands"]), f"2 candidates via image edit {[c.get('mode') for c in r.get('cands', [])]}")
ok(all(u.endswith("/images/edits") for u, _ in CALLS) and CALLS[0][1]["data"]["size"] == "1536x1024" and "Bangkok condo variant 0" in CALLS[0][1]["data"]["prompt"],
   "edit API got product reference + AI-written scene + 16:9 size")
ok(TXT[0][0] == "scene_prompt" and TXT[0][2], "prompt AI looked at the white-background product image")
im = Image.open(os.path.join(scene_ai._dir(pid), r["cands"][0]["file"]))
ok(im.size == (1600, 900), f"16:9 output {im.size}")
qas = [c["qa"] for c in r["cands"]]
ok(qas[0]["score"] == 88 and qas[0]["ok"] and qas[1]["score"] == 35 and qas[1]["ok"] is False and not qas[1]["shape_ok"], f"QA scores + bad flagged {qas}")
ok(r["cost"] > 0, f"actual cost from usage log {r['cost']}")
rows = db.conn().execute("SELECT task, kind FROM ai_usage WHERE task LIKE 'scene%'").fetchall()
ok({x["task"] for x in rows} >= {"scene"} and any(x["kind"] == "edit" for x in rows), "scene calls in usage log")

# ---------------- 不能改图的（Flux schnell）→ 生成空场景 + 贴真实产品 ----------------
config.save_config({"ai_tasks": {"scene": {"chain": [{"p": "fal", "m": "fal-ai/flux/schnell"}]}},
                    "ai_providers": {**config.load_config()["ai_providers"], "fal": {"api_key": "fal-test-123456", "edit_model": "-"}}})
CALLS.clear()
r = C.post(f"/api/products/{pid}/scene-gen", json={"template": "minimal_white", "aspect": "3:4", "n": 1, "qa": False, "ai_prompt": False}).get_json()
c = r["cands"][0]
ok(c["mode"] == "composite" and c["qa"] is None and "fal.run/fal-ai/flux/schnell" in CALLS[0][0] and "EMPTY" in CALLS[0][1]["json"]["prompt"]
   and "image_url" not in CALLS[0][1]["json"], "flux without edit: empty background prompt, no reference")
im = Image.open(os.path.join(scene_ai._dir(pid), c["file"])).convert("RGB")
ok(im.size == (1200, 1600), f"3:4 output {im.size}")
red = [(x, y) for x in range(0, im.width, 4) for y in range(0, im.height, 4) if im.getpixel((x, y))[0] > 180 and im.getpixel((x, y))[2] < 80]
xs, ys = [a for a, _ in red], [b for _, b in red]
ratio = (max(ys) - min(ys)) / max(1, (max(xs) - min(xs)))
ok(red and 1.8 < ratio < 2.2, f"real product pasted, not distorted (h/w {ratio:.2f})")
ok(abs(sum(xs) / len(xs) - im.width / 2) < 40, "product centred")

# ---------------- 出图服务商出错 → 换备用 ----------------
config.save_config({"ai_tasks": {"scene": {"chain": [{"p": "fal", "m": "fal-ai/flux/schnell"}, {"p": "openai", "m": ""}]}}})
FAIL["n"] = 1
CALLS.clear()
r = C.post(f"/api/products/{pid}/scene-gen", json={"template": "outdoor", "n": 1, "qa": False, "ai_prompt": False}).get_json()
ok(r["cands"] and r["cands"][0]["provider"] in ("fal", "openai") and len(CALLS) == 2, f"image error → fallback {[u for u, _ in CALLS]}")

# ---------------- 挑图 → 加入商品图（不裁成方图）----------------
allc = C.get(f"/api/products/{pid}/scene-cands").get_json()["cands"]
wide = [x["id"] for x in allc if x["aspect"] == "16:9"][:1]
r = C.post(f"/api/products/{pid}/scene-cands/pick", json={"ids": wide}).get_json()
added = [i for i in r["product"]["images"] if i.get("scene")]
ok(r["added"] == 1 and added and added[0].get("aspect") == "16:9", "picked candidate added as scene image")
im = Image.open(os.path.join(store.image_dir(pid, "out"), added[0]["file"]))
ok(abs(im.width / im.height - 16 / 9) < 0.02, f"aspect kept when added {im.size}")
ok(any(x.get("picked") for x in r["cands"]), "candidate marked as used")
r = C.delete(f"/api/products/{pid}/scene-cands/{allc[0]['id']}").get_json()
ok(len(r["cands"]) == len(allc) - 1, "delete candidate")
ok(C.get(f"/scene-cand/{pid}/{r['cands'][0]['file']}").status_code == 200 and C.get(f"/scene-cand/{pid}/..%2Fx.jpg").status_code == 404, "candidate file served safely")

# ---------------- 浏览器抠好的产品图 ----------------
cut = Image.new("RGBA", (300, 300), (0, 0, 0, 0)); cut.paste((10, 200, 10, 255), (100, 50, 200, 250))
r = C.post(f"/api/products/{pid}/scene-gen", json={"image": "data:image/png;base64," + base64.b64encode(png(cut)).decode(), "n": 1,
                                                 "qa": False, "ai_prompt": False, "template": "kids_room"}).get_json()
ok(r["cands"], "transparent cutout from the browser accepted")
cs = scene_ai.cutout(prod)
ok(abs(cs.size[0] - 200) <= 4 and abs(cs.size[1] - 400) <= 4 and cs.getpixel((0, 0))[3] < 128 and cs.getpixel((cs.width // 2, cs.height // 2))[3] == 255,
   f"server white-background cutout trims to product {cs.size}")

# ---------------- 旧接口（编辑页老按钮 / API）----------------
config.save_config({"ai_tasks": {}})
r = C.post(f"/api/products/{pid}/scene-ai", json={"image": "data:image/png;base64," + base64.b64encode(png(cut)).decode(), "scene": "desk"}).get_json()
ok(r.get("added") == 1, "old /scene-ai endpoint still works through the AI layer")
r = C.post("/api/scenes/ai", json={"preset": "desk_wood"}).get_json()
ok(r.get("added"), "AI empty background still works")

# ---------------- 没设置出图 AI ----------------
config.save_config({"ai_providers": {}, "image_api_key": "", "ai_tasks": {}})
r = C.post(f"/api/products/{pid}/scene-gen", json={"n": 1})
ok(r.status_code == 400 and "密钥" in r.get_json()["error"], "no image AI → clear message")
config.save_config({"ai_providers": {"openai": {"api_key": "sk-oai-test-123456"}}})

# ---------------- 批量 ----------------
s = C.post("/api/scenes/batch", json={"ids": [pid, pid2, "NOPE999"], "n": 1, "qa": True, "auto_add": True}).get_json()
ok(s["running"] and s["total"] == 3 and s["estimate"] > 0, "batch started with estimate")
ok(C.post("/api/scenes/batch", json={"ids": [pid]}).status_code == 400, "only one batch at a time")
for _ in range(100):
    s = C.get("/api/scenes/batch").get_json()
    if not s["running"]:
        break
    time.sleep(0.1)
st = {it["pid"]: it for it in s["items"]}
ok(not s["running"] and s["done"] == 3 and s["failed"] == 1 and st[pid]["status"] == "done" and st["NOPE999"]["status"] == "error", f"batch done {s['items']}")
ok(s["cost"] > 0, f"batch actual cost {s['cost']}")
p2 = store.load(pid2)
ok(any(i.get("scene") for i in p2["images"]) == bool(st[pid2].get("added")), "auto-add best QA candidate")
ok(scene_ai.list_cands(pid2) and scene_ai.list_cands(pid2)[0]["template"] == "kids_room", "batch uses category template")
# 取消
import threading
gate = threading.Event()
orig = scene_ai.generate
scene_ai.generate = lambda *a, **k: (gate.wait(5), {"cands": [], "cost": 0, "errors": ["x"]})[1]
C.post("/api/scenes/batch", json={"ids": [pid, pid2], "n": 1})
c2 = C.post("/api/scenes/batch/cancel", json={}).get_json()
gate.set()
for _ in range(100):
    s = C.get("/api/scenes/batch").get_json()
    if not s["running"]:
        break
    time.sleep(0.05)
scene_ai.generate = orig
ok(c2["cancel"] and s["items"][1]["status"] == "cancelled", f"batch cancel {s['items']}")

# ---------------- 模板编辑（老板）----------------
r = C.post("/api/scenes/templates", json={"templates": [{"key": "Songkran!", "zh": "泼水节", "th": "สงกรานต์", "prompt": "festive", "cats": "节日, festival"}]}).get_json()
ok(r["custom"] and r["templates"][0]["key"] == "songkran" and r["templates"][0]["cats"] == ["节日", "festival"], "templates edited + cleaned")
ok(N.post("/api/scenes/templates", json={"templates": []}).status_code == 403, "staff cannot edit templates")
r = C.post("/api/scenes/templates", json={"reset": True}).get_json()
ok(not r["custom"] and len(r["templates"]) >= 6, "templates reset")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
