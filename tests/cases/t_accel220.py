# v2.20：电脑加速（worker）+ 任务中心
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, threading, time, json, io, zipfile, socket
D = T + "/vaccel"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
import app as A
from core import accel, bgjobs, kernels, config, store, slicer, imgtools, modellib
E = 0
def ok(b, m):
    global E; print(("OK  " if b else "ERR ") + m); E += (not b)

C = A.app.test_client()
cfg = config.load_config(); cfg["accel_claim_wait"] = 2
ORCA = "/tmp/squashfs-root/orca-wrap"
if os.path.exists(ORCA): cfg["orca_path"] = ORCA
config.save_config(cfg)
STL = T + "/cat.stl"

# ---- 没有电脑：NAS 自己做 ----
loc = kernels.mesh_summary(STL, "PLA")
ok(loc["triangles"] > 1000 and loc["metrics"]["volume_mm3"] > 0 and loc.get("orients"), "local mesh summary")
ok(accel.status()["stats"]["local"] >= 1 and accel.status()["stats"]["remote"] == 0, "counted as local")
j0 = bgjobs.start(lambda: kernels.mesh_summary(STL, "PLA", orients=False, parts=False), "t", "", "model")
for _ in range(100):
    if bgjobs.get(j0["id"])["status"] != "running": break
    time.sleep(0.05)
g0 = bgjobs.get(j0["id"]); ok(g0["where"] == "NAS" and g0["why"] == "small", f"why small file on NAS {g0.get('why')}")
from core import mesh
a1 = mesh.load(STL); a2 = mesh.load(STL); ok(a1 is a2 and not a1.flags.writeable, "parsed model cached (read-only)")

# ---- 密钥权限 ----
r = C.post("/api/accel/key", json={}); KEY = r.get_json()["key"]; ok(r.status_code == 200 and KEY.startswith("lh_"), "worker key created")
H = {"Authorization": "Bearer " + KEY}
from core import integrations
RK = integrations.create_key("ro", "read")
ok(C.get("/api/v1/accel/next?name=x&wait=1", headers={"Authorization": "Bearer " + RK}).status_code == 403, "read key cannot take jobs")
ok(C.get("/api/v1/products", headers=H).status_code == 403, "worker key cannot read products")
ok(C.get("/api/v1/ping", headers=H).status_code == 200, "worker key ping")
z = zipfile.ZipFile(io.BytesIO(C.get("/api/v1/accel/package", headers=H).data)); names = z.namelist()
ok("worker.py" in names and "core/accel.py" in names and "core/kernels.py" in names and not any(n.endswith(".bat") for n in names)
   and not any("__pycache__" in n for n in names), "auto-update package (no .bat)")
z2 = zipfile.ZipFile(io.BytesIO(C.get("/api/accel/package").data))
ok("4_start_worker.bat" in z2.namelist() and "5_worker_autostart.bat" in z2.namelist(), "full package has start scripts")
# NAS 上没有 .bat（旧的在线升级跳过了）：下载包里也要有
import web.accel as WA
_orig = WA.BASE_DIR
_tmpd = D + "/fakeapp"; shutil.copytree(APP, _tmpd, ignore=shutil.ignore_patterns("*.bat", "tests", "data", "__pycache__"))
WA.BASE_DIR = _tmpd
z3 = zipfile.ZipFile(io.BytesIO(C.get("/api/accel/package").data)); WA.BASE_DIR = _orig
bt = z3.read("4_start_worker.bat")
ok("4_start_worker.bat" in z3.namelist() and "1_setup.bat" in z3.namelist() and b"worker.py" in bt and b"\r\n" in bt, "start scripts filled in when NAS lacks .bat")

# ---- 电脑在线但不接活：等 2 秒后 NAS 自己做 ----
r = C.post("/api/v1/accel/hello", headers=H, json={"name": "ghost", "caps": ["mesh"], "proto": accel.PROTO, "cpu": 8, "version": A.VERSION})
ok(r.status_code == 200 and r.get_json()["server_version"] == A.VERSION, "hello")
st = accel.status(); ok(st["workers"][0]["name"] == "ghost" and st["workers"][0]["online"], "worker listed online")
kernels.MESH_MIN_BYTES = 0
t0 = time.time(); res = kernels.mesh_summary(STL, "PLA", orients=False, parts=False)
ok(res["triangles"] == loc["triangles"] and time.time() - t0 < 1.5 and accel.status()["stats"]["fallback"] == 0, "stuck worker (not polling) skipped at once")
# 在领活、但领的是别的活（相当于手上满了）：等 2 秒后 NAS 自己做
th = threading.Thread(target=lambda: A.app.test_client().get("/api/v1/accel/next?name=ghost&caps=preview&wait=4", headers=H)); th.start(); time.sleep(0.3)
t0 = time.time(); res = kernels.mesh_summary(STL, "PLA", orients=False, parts=False)
ok(res["triangles"] == loc["triangles"] and 1.5 < time.time() - t0 < 20 and accel.status()["stats"]["fallback"] == 1, "fallback to NAS after claim wait")
th.join()

# ---- 模拟电脑：报「文件有问题」→ NAS 直接报错，不重算 ----
def fake_worker(final):
    c = A.app.test_client()
    r = c.get("/api/v1/accel/next?name=ghost&caps=mesh&wait=10", headers=H)
    if r.status_code != 200: return
    t = r.get_json()
    f = c.get(f"/api/v1/accel/task/{t['id']}/file/model", headers=H)
    assert len(f.data) == os.path.getsize(STL)
    c.post(f"/api/v1/accel/task/{t['id']}/fail", headers=H, json={"error": "模型坏了", "final": final})
th = threading.Thread(target=fake_worker, args=(True,)); th.start()
try:
    kernels.mesh_summary(STL, "PLA", orients=False, parts=False); ok(False, "final error should raise")
except ValueError as e:
    ok("模型坏了" in str(e), "final error from PC raised without NAS retry")
th.join()
th = threading.Thread(target=fake_worker, args=(False,)); th.start()
res = kernels.mesh_summary(STL, "PLA", orients=False, parts=False); th.join()
ok(res["triangles"] == loc["triangles"], "non-final PC error → NAS redoes it")

# ---- 真的电脑程序（worker.py）对着真的服务器 ----
from werkzeug.serving import make_server
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
srv = make_server("127.0.0.1", PORT, A.app, threaded=True)
threading.Thread(target=srv.serve_forever, daemon=True).start()
import worker as W
wk = W.Worker(f"http://127.0.0.1:{PORT}", KEY, "test-pc", slots=2); wk.auto_update = False; wk.no_install = True
threading.Thread(target=wk.loop, daemon=True).start()
for _ in range(100):
    if any(w["name"] == "test-pc" and w["online"] for w in accel.workers()): break
    time.sleep(0.1)
w = next(w for w in accel.workers() if w["name"] == "test-pc")
ok("removebg" in w["caps"] or "removebg" in (w.get("missing") or {}), f"missing component reported {w.get('missing')}")
ok(w["online"] and "mesh" in w["caps"] and "preview" in w["caps"] and w["version_ok"], f"worker.py online caps={w['caps']}")
time.sleep(0.5)
st0 = accel.status()["stats"]["remote"]
th_path = D + "/tmp/thumb_test.png"; os.makedirs(D + "/tmp", exist_ok=True)
res = kernels.mesh_summary(STL, "PLA", thumb_to=th_path)
ok(accel.status()["stats"]["remote"] == st0 + 1 and res["triangles"] == loc["triangles"] and res.get("orients") == json.loads(json.dumps(loc["orients"])),
   "mesh summary done on PC, same result")
ok(os.path.getsize(th_path) > 500, "thumbnail came back from PC")
from core import preview
data = kernels.preview_bytes(STL, 5000)
import gzip; raw = gzip.decompress(data); ok(raw[:4] == b"3DPV", "preview built on PC")

# 后台任务里记录「在哪台电脑上做」
def job():
    return {"r": kernels.mesh_summary(STL, "PLA", orients=False, parts=False)["triangles"]}
j = bgjobs.start(job, "test", "", "model", "P1")
for _ in range(100):
    if bgjobs.get(j["id"])["status"] != "running": break
    time.sleep(0.1)
g = bgjobs.get(j["id"]); ok(g["status"] == "done" and g["where"] == "test-pc", f"job where = PC ({g.get('where')})")

if "slice" in w["caps"]:
    keep = D + "/tmp/kept.gcode.3mf"
    r = slicer.orca_slice(config.load_config(), STL, 0, "PLA", keep_to=keep)
    ok(r.get("where") == "pc" and r["grams"] > 5 and os.path.getsize(keep) > 1000 and r.get("kept") == keep, f"slice on PC {r.get('grams')}g kept")
    st0 = accel.status()["stats"]["remote"]
    tp = kernels.toolpath_blob(keep, "3mf")
    ok(len(tp) > 100 and accel.status()["stats"]["remote"] == st0 + 1, "slice preview (toolpath) built on PC")
    r2 = slicer.orca_slice(config.load_config(), T + "/bambu_project.3mf", 0, "PLA")
    ok(r2.get("where") == "pc" and r2["grams"] > 0, "bambu 3mf sliced on PC (name/ext kept)")
else:
    print("OK  (no OrcaSlicer here: slice on PC skipped)")

from PIL import Image
im = Image.new("RGB", (120, 90), (200, 50, 50)); mk = Image.new("L", (120, 90), 0); mk.paste(255, (40, 30, 60, 50))
st0 = accel.status()["stats"]["remote"]
out, used = imgtools.inpaint(im, mk, "auto")
ok(out.size == (120, 90) and accel.status()["stats"]["remote"] == st0 + 1, f"inpaint on PC ({used})")
try:
    imgtools.inpaint(im, Image.new("L", (120, 90), 0)); ok(False, "empty mask")
except ValueError:
    ok(True, "empty mask rejected before sending")

# ---- 路由：后台 + 任务中心 ----
pid = store.list_products()[0]["id"]
r = C.post(f"/api/products/{pid}/models/reanalyze?async=1", json={}); ok(r.status_code == 202 and r.get_json()["job"], "reanalyze async")
jid = r.get_json()["job"]
for _ in range(200):
    g = C.get(f"/api/bg/{jid}").get_json()
    if g["status"] != "running": break
    time.sleep(0.1)
ok(g["status"] == "done" and "items" in g["result"], "reanalyze job done")
L = C.get("/api/bg/list").get_json()
ok(any(x["id"] == jid and x["kind"] == "model_re" and x["link"] == pid for x in L["jobs"]) and "test-pc" in L["accel"]["online"], "task center list")
r = C.post("/api/products/NOPE/models/current?async=1", json={"items": []}); jid2 = r.get_json()["job"]
for _ in range(100):
    g = C.get(f"/api/bg/{jid2}").get_json()
    if g["status"] != "running": break
    time.sleep(0.1)
ok(g["status"] == "error", "failing job → error")
r = C.post(f"/api/bg/{jid2}/retry", json={}); ok(r.status_code == 200 and r.get_json()["job"] != jid2, "retry creates new job")
r = C.post(f"/api/bg/{jid}/retry", json={}); ok(r.status_code == 400, "cannot retry finished ok job")
with open(STL, "rb") as f:
    r = C.post(f"/api/products/{pid}/model?async=1", data={"file": (f, "cat.stl")}, content_type="multipart/form-data")
ok(r.status_code == 202, "model upload async")
jid3 = r.get_json()["job"]
for _ in range(300):
    g = C.get(f"/api/bg/{jid3}").get_json()
    if g["status"] != "running": break
    time.sleep(0.1)
ok(g["status"] == "done" and g["result"]["model"]["triangles"] == loc["triangles"], "model uploaded in background")
ok(not [n for n in os.listdir(D + "/tmp") if n.endswith(".stl") and len(n) > 30], "temp upload removed")
r = C.post("/api/ai/back-translate?async=1", json={"title_th": "ทดสอบ", "description_th": ""}); ok(r.status_code == 202, "AI route replayed in background")
jid4 = r.get_json()["job"]
for _ in range(100):
    g = C.get(f"/api/bg/{jid4}").get_json()
    if g["status"] != "running": break
    time.sleep(0.1)
ok(g["status"] in ("done", "error") and g["kind"] == "ai", f"AI job finished ({g['status']}: {str(g.get('error'))[:60]})")
r = C.post(f"/api/products/{pid}/keywords?async=1", json=store.load(pid)); ok(r.status_code == 202 and C.get(f"/api/bg/{r.get_json()['job']}").get_json()["link"] == pid, "keywords job linked to product")
C.post("/api/bg/clear", json={}); ok(not [x for x in C.get("/api/bg/list").get_json()["jobs"] if x["status"] == "done"], "clear finished")

# ---- NAS 本机排队：同时只做 1 个 ----
accel_cfg = config.load_config(); accel_cfg["accel_on"] = False; config.save_config(accel_cfg)
order = []
def slow(n):
    with accel.heavy():
        order.append(("in", n)); time.sleep(0.4); order.append(("out", n))
    return {}
js = [bgjobs.start(lambda n=n: slow(n), f"h{n}", "") for n in range(2)]
time.sleep(0.15)
sts = sorted(bgjobs.get(x["id"])["status"] for x in js)
ok(sts == ["queued", "running"], f"second heavy job queued {sts}")
time.sleep(1.2)
ok(order[1][0] == "out", f"heavy jobs one at a time {order}")
with accel.heavy():
    with accel.heavy():
        ok(True, "nested heavy() does not deadlock")
wk.stop.set(); srv.shutdown()
print("ERRORS", E)
