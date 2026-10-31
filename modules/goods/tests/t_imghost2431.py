# v2.43.1：图床上传——大图先压缩、同时传几张、每张传好就记下；一张失败不影响别的，再点只传没成功的
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, io, threading, time
D = T + "/m_imghost"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, config, imghost
from PIL import Image
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
# 压缩：4000x4000 的 PNG（带透明）→ JPEG，≤ 1MB，边长 ≤ 2000，透明铺白；太小的放大到 330
src = os.path.join(D, "big.png")
im = Image.effect_noise((4000, 4000), 80).convert("RGBA"); im.putpixel((0, 0), (0, 0, 0, 0)); im.save(src)
data, ext = imghost.prepare(src, max_bytes=1_000_000)
out = Image.open(io.BytesIO(data))
ok(ext == "jpg" and len(data) <= 1_000_000 and max(out.size) <= 2000 and out.mode == "RGB", f"compressed {len(data)} {out.size}")
Image.new("RGB", (200, 120), "white").save(os.path.join(D, "tiny.jpg"))
d2, _ = imghost.prepare(os.path.join(D, "tiny.jpg"))
ok(min(Image.open(io.BytesIO(d2)).size) >= 330, "tiny image upscaled to 330")
# 上传：6 张，第 3 张一直失败；同时最多 4 张在传
pid = "3DP0015"
p = store.load(pid)
for i in range(6):
    f = f"t{i}.jpg"
    Image.new("RGB", (800, 800), (i * 30, 100, 100)).save(os.path.join(store.image_dir(pid, "raw"), f))
p["images"] = [{"file": f"t{i}.jpg", "raw": f"t{i}.jpg"} for i in range(6)]
p["white_bg"] = None
store.save(p)
config.save_config({"imgbb_api_key": "k"})
live, peak, calls = [0], [0], []
lock = threading.Lock()
def fake(key, path, retries=1):
    with lock:
        live[0] += 1; peak[0] = max(peak[0], live[0]); calls.append(os.path.basename(path))
    time.sleep(0.2)
    with lock:
        live[0] -= 1
    if path.endswith("t2.jpg"):
        raise imghost.HostError("图床错误 500")
    return "https://i.ibb.co/" + os.path.basename(path)
imghost.upload_imgbb = fake
t0 = time.time()
r = C.post(f"/api/products/{pid}/images/host").get_json()
ok(r["uploaded"] == 5 and len(r["failed"]) == 1 and "t2.jpg" in r["failed"][0], f"partial result {r.get('uploaded')} {r.get('failed')}")
ok(1 < peak[0] <= 4 and time.time() - t0 < 1.0, f"parallel (peak {peak[0]}, {time.time() - t0:.2f}s)")
q = store.load(pid)
ok(sum(1 for i in q["images"] if i.get("url")) == 5 and not next(i for i in q["images"] if i["file"] == "t2.jpg").get("url"), "urls saved")
calls.clear()
imghost.upload_imgbb = lambda key, path, retries=1: calls.append(os.path.basename(path)) or "https://i.ibb.co/x.jpg"
r = C.post(f"/api/products/{pid}/images/host").get_json()
ok(calls == ["t2.jpg"] and r["uploaded"] == 1 and not r["failed"], f"second click only uploads the failed one {calls}")
config.save_config({"imgbb_api_key": ""})
ok(C.post(f"/api/products/{pid}/images/host").status_code == 400, "no key: clear error")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
