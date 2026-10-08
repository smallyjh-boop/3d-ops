# v2.28：桌面客户端——配对、每个人加速自己的、在本机打开（一次性下载码）、安装包、客户端模块（找 NAS / 设置）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, json, threading, time, io, zipfile, http.server
D = T + "/v228"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E = 0
def ok(b, m):
    global E; print(("OK  " if b else "ERR ") + m); E += (not b)
import app as A
from core import db, accel, desktop, config, bgjobs
C = A.app.test_client()
# 两个账号（老板 + 员工），各自登录一个客户端
db.create_user("boss", "secret123", "owner", "老板")
db.create_user("nok", "secret123", "listing", "Nok")
cb, cn = A.app.test_client(), A.app.test_client()
ok(cb.post("/api/auth/login", json={"username": "boss", "password": "secret123"}).status_code == 200, "boss login")
ok(cn.post("/api/auth/login", json={"username": "nok", "password": "secret123"}).status_code == 200, "nok login")
ok(C.post("/api/desktop/pair", json={"device_id": "a" * 32}).status_code == 401, "pair needs login")
ok(cb.post("/api/desktop/pair", json={"device_id": "x"}).status_code == 400, "bad device id")
rb = cb.post("/api/desktop/pair", json={"device_id": "b" * 32, "device_name": "BOSS-PC"}).get_json()
rn = cn.post("/api/desktop/pair", json={"device_id": "n" * 32, "device_name": "NOK-PC"}).get_json()
ok(rb["key"].startswith("lh_") and rb["worker_name"] == "老板@BOSS-PC" and rn["worker_name"] == "Nok@NOK-PC", f"pair {rb.get('worker_name')} {rn.get('worker_name')}")
HB = {"Authorization": "Bearer " + rb["key"]}; HN = {"Authorization": "Bearer " + rn["key"]}
# 配对的密钥只能做电脑加速
ok(C.get("/api/v1/orders", headers=HB).status_code == 403, "desktop key is worker-only")
caps = ["mesh", "preview"]
for h, n in ((HB, rb["worker_name"]), (HN, rn["worker_name"])):
    r = C.post("/api/v1/accel/hello", json={"name": n, "caps": caps, "proto": accel.PROTO, "version": A.VERSION, "desktop": True}, headers=h).get_json()
ok(r["ok"], "hello")
ws = {w["name"]: w for w in accel.workers()}
ok(ws["老板@BOSS-PC"]["user"] == "boss" and ws["Nok@NOK-PC"]["user"] == "nok" and ws["Nok@NOK-PC"]["desktop"], f"workers know owner {[(w['name'], w['user']) for w in ws.values()]}")
devs = cb.get("/api/desktop/devices").get_json()["devices"]
ok(len(devs) == 2 and {d["user"] for d in devs} == {"boss", "nok"} and devs[0]["version"] == A.VERSION, f"devices {devs}")
ok(cn.get("/api/desktop/devices").status_code == 403, "staff can't list devices")

# 每个人加速自己的：Nok 的活只给 Nok 的电脑
config.save_config({**config.load_config(), "accel_on": True})
def poll(h, n, out):
    r = C.get(f"/api/v1/accel/next?name={urllib_q(n)}&caps=mesh,preview&wait=4", headers=h)
    out.append(r.get_json() if r.status_code == 200 else None)
from urllib.parse import quote as urllib_q
# 直接在线程里模拟后台任务（带用户）
def task_for(user):
    out = {}
    def fn():
        out["r"] = accel.run("mesh", {}, {}, lambda: "nas", remote_done=lambda r, o: r, timeout=20, claim_wait=3, heavy_local=False)
        return out["r"]
    bgjobs.start(fn, "测试", user)
    return out
got_b, got_n = [], []
tb = threading.Thread(target=poll, args=(HB, rb["worker_name"], got_b)); tn = threading.Thread(target=poll, args=(HN, rn["worker_name"], got_n))
tb.start(); tn.start(); time.sleep(0.3)
out = task_for("nok")
tb.join(); tn.join()
ok(got_n and got_n[0] and got_n[0].get("user") == "nok" and not (got_b and got_b[0]), f"nok's task went to nok's PC (boss {got_b}, nok {got_n})")
tid = got_n[0]["id"]
C.post(f"/api/v1/accel/task/{tid}/done", data={"result": json.dumps({"ok": 1})}, headers=HN)
for _ in range(100):
    if "r" in out: break
    time.sleep(0.05)
ok(out.get("r") == {"ok": 1}, f"result back {out}")
# Nok 的电脑暂停：Nok 的活不给老板的电脑（老板没开「帮别人加速」）→ NAS 做
C.post("/api/v1/accel/hello", json={"name": rn["worker_name"], "caps": caps, "proto": accel.PROTO, "paused": True}, headers=HN)
got_b = []
tb = threading.Thread(target=poll, args=(HB, rb["worker_name"], got_b)); tb.start(); time.sleep(0.3)
out = task_for("nok")
tb.join()
for _ in range(100):
    if "r" in out: break
    time.sleep(0.05)
ok(out.get("r") == "nas" and not (got_b and got_b[0]), f"paused → NAS, boss PC not used {out} {got_b}")
# 老板打开「也帮别人加速」→ Nok 的活可以给老板的电脑
C.post("/api/v1/accel/hello", json={"name": rb["worker_name"], "caps": caps, "proto": accel.PROTO, "share": True}, headers=HB)
got_b = []
tb = threading.Thread(target=poll, args=(HB, rb["worker_name"], got_b)); tb.start(); time.sleep(0.3)
out = task_for("nok")
tb.join()
ok(got_b and got_b[0] and got_b[0]["user"] == "nok", f"shared PC helps {got_b}")
if got_b and got_b[0]:
    C.post(f"/api/v1/accel/task/{got_b[0]['id']}/done", data={"result": json.dumps({"ok": 2})}, headers=HB)
# 共享加速电脑（老板手动生成的密钥，没有主人）谁的活都做
from core import integrations
shared = integrations.create_key("办公室加速", "worker")
HS = {"Authorization": "Bearer " + shared}
C.post("/api/v1/accel/hello", json={"name": "Office", "caps": caps, "proto": accel.PROTO}, headers=HS)
ok({w["name"]: w for w in accel.workers()}["Office"]["user"] == "", "shared worker has no owner")
ok(accel._eligible({"user": ""}, "nok") and not accel._eligible({"user": "boss"}, "nok") and accel._eligible({"user": "boss", "share": True}, "nok")
   and accel._eligible({"user": "boss"}, ""), "eligibility rules")
# 重新配对：旧密钥作废
rb2 = cb.post("/api/desktop/pair", json={"device_id": "b" * 32, "device_name": "BOSS-PC"}).get_json()
ok(C.post("/api/v1/accel/hello", json={"name": "x", "caps": []}, headers=HB).status_code == 401 and
   C.post("/api/v1/accel/hello", json={"name": rb2["worker_name"], "caps": []}, headers={"Authorization": "Bearer " + rb2["key"]}).status_code == 200, "re-pair revokes old key")
# 老板停用 Nok 的电脑
nid = [d for d in cb.get("/api/desktop/devices").get_json()["devices"] if d["user"] == "nok"][0]["id"]
ok(cb.post(f"/api/desktop/devices/{nid}/revoke", json={}).status_code == 200 and
   C.post("/api/v1/accel/hello", json={"name": "y", "caps": []}, headers=HN).status_code == 401, "revoke")

# 在本机打开：一次性下载码
os.makedirs(D + "/models", exist_ok=True)
pid = None
plist = cb.get("/api/products").get_json()
pid = (plist[0]["id"] if isinstance(plist, list) else plist["items"][0]["id"])
ok(cb.post("/api/desktop/dltoken", json={"path": "/api/config"}).status_code == 400, "only file downloads allowed")
t = cb.post("/api/desktop/dltoken", json={"path": f"/api/products/{pid}/model/download"}).get_json()
ok(t["url"].startswith("/api/desktop/dl/"), "token")
r1 = C.get(t["url"]); r2 = C.get(t["url"])
direct = cb.get(f"/api/products/{pid}/model/download")
ok(r1.status_code == direct.status_code and r1.data == direct.data and r2.status_code == 404, f"token download works once ({r1.status_code}/{direct.status_code}, again {r2.status_code})")

# 安装包
z = cn.get("/api/desktop/package")
ok(z.status_code == 200, "staff can download desktop package")
zf = zipfile.ZipFile(io.BytesIO(z.data)); names = zf.namelist()
need = ["3D-Ops-Desktop/Install.bat", "3D-Ops-Desktop/server.json", "3D-Ops-Desktop/app/desktop/desktop_app.py", "3D-Ops-Desktop/app/desktop/icon.ico",
        "3D-Ops-Desktop/app/worker.py", "3D-Ops-Desktop/app/app.py", "3D-Ops-Desktop/app/core/accel.py", "3D-Ops-Desktop/app/desktop/requirements-desktop.txt"]
ok(all(n in names for n in need), f"package files {[n for n in need if n not in names]}")
sj = json.loads(zf.read("3D-Ops-Desktop/server.json"))
ok(sj["servers"][0] == "http://localhost" and sj["version"] == A.VERSION, f"server.json {sj}")
bat = zf.read("3D-Ops-Desktop/Install.bat").decode()
ok("\r\n" in bat and "pythonw.exe" in bat and "desktop_app.py\" --installed" in bat and "{" not in bat, "install bat")
ok(C.get("/api/desktop/package").status_code in (401, 302), "package needs login")
upd = zipfile.ZipFile(io.BytesIO(C.get("/api/v1/accel/package", headers={"Authorization": "Bearer " + rb2["key"]}).data)).namelist()
ok("desktop/desktop_app.py" in upd, "auto-update package includes desktop")

# 「我的加速器」（偶尔用的电脑：浏览器 + 加速器）：包里带好地址和只属于这个账号的密钥
zp = cn.get("/api/accel/package?personal=1")
ok(zp.status_code == 200, "staff can download personal accelerator")
zpn = zipfile.ZipFile(io.BytesIO(zp.data)).namelist()
ok(all(n in zpn for n in ("3D-Ops-Accelerator/Install.bat", "3D-Ops-Accelerator/app/desktop/accel_tray.py", "3D-Ops-Accelerator/app/desktop/accel.ico",
                          "3D-Ops-Accelerator/app/worker.py", "3D-Ops-Accelerator/app/desktop/requirements-accel.txt")), "accelerator package layout")
abat = zipfile.ZipFile(io.BytesIO(zp.data)).read("3D-Ops-Accelerator/Install.bat").decode()
ok("accel_tray.py" in abat and "3D-Ops-Accelerator" in abat and "--accel" in abat and "{" not in abat, "accelerator install bat")
wj = json.loads(zipfile.ZipFile(io.BytesIO(zp.data)).read("3D-Ops-Accelerator/app/data/worker.json"))
ok(wj["server"] == "http://localhost" and wj["key"].startswith("lh_") and wj["name_prefix"] == "Nok", f"worker.json {wj}")
C.post("/api/v1/accel/hello", json={"name": "Nok@OLD-PC", "caps": caps, "proto": accel.PROTO}, headers={"Authorization": "Bearer " + wj["key"]})
ok({w["name"]: w for w in accel.workers()}["Nok@OLD-PC"]["user"] == "nok", "personal accelerator belongs to nok")
zo = cb.get("/api/accel/package")
ok(not any(n.endswith("data/worker.json") for n in zipfile.ZipFile(io.BytesIO(zo.data)).namelist()), "owner shared package has no key")

# 客户端模块（不开窗口）：找 NAS、设置
os.environ["HOME"] = D; os.environ["LH_DESKTOP_ROOT"] = D
sys.path.insert(0, os.path.join(APP, "desktop"))
import importlib
dk = importlib.import_module("desktop_app")
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        b = json.dumps({"version": "9.9"}).encode(); self.send_response(200); self.end_headers(); self.wfile.write(b)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
good = f"http://127.0.0.1:{srv.server_address[1]}"
dk.C["servers"] = ["http://127.0.0.1:1", good]
ok(dk.pick_server(1.0) == good, "pick_server skips dead LAN, uses next")
ok(dk.probe("http://127.0.0.1:1", 0.5) is None and dk.probe(good) == "9.9", "probe")
ok(dk.Api().open_local("/etc/passwd").get("ok") is False, "open_local only token urls")
info = dk.Api().info()
ok(info["desktop"] and info["version"] == A.VERSION and len(info["device_id"]) == 32 and info["accel"]["state"] == "未配对", f"api info {info['accel']['state']}")
s1 = dk.single_instance(); s2 = dk.single_instance()
ok(s1 is not None and s2 is None, "single instance")
srv.shutdown()
# 真的跑一下：客户端配对后自带的加速连上 NAS（用真的 HTTP 服务器）
from werkzeug.serving import make_server
ws_ = make_server("127.0.0.1", 0, A.app, threaded=True); threading.Thread(target=ws_.serve_forever, daemon=True).start()
nas = f"http://127.0.0.1:{ws_.server_port}"
rp = cn.post("/api/desktop/pair", json={"device_id": dk.C["device_id"], "device_name": "NOK-LAPTOP"}).get_json()
dk.STATE["server"] = nas
dk.C["no_install"] = True
dk.API.paired(nas, rp["key"], rp["worker_name"], "nok")
w = None
for _ in range(100):
    w = {x["name"]: x for x in accel.workers()}.get("Nok@NOK-LAPTOP")
    if w and w.get("caps"): break
    time.sleep(0.2)
ok(w and w["user"] == "nok" and w["desktop"] and "mesh" in w["caps"], f"desktop accel online {w and (w['user'], w['desktop'], w['caps'])}")
ok(dk.API.info()["accel"]["state"] == "在线" and json.load(open(os.path.join(D, "desktop.json")))["user"] == "nok", "client state online, conf saved")
# 真的派一件活（读模型）给这台电脑
stl = os.path.join(D, "cube.stl"); shutil.copy(os.path.join(T, "cat.stl"), stl)
res = {}
def job():
    res["r"] = accel.run("mesh", {}, {"model": stl}, lambda: "nas", remote_done=lambda r, o: r, timeout=60, claim_wait=10, heavy_local=False)
jid = bgjobs.start(job, "读模型", "nok")
for _ in range(200):
    if "r" in res: break
    time.sleep(0.1)
ok(isinstance(res.get("r"), dict) and dk.ACCEL.w.done == 1, f"real task done on desktop accel {str(res.get('r'))[:120]} done={dk.ACCEL.w.done}")
dk.API.set_option("paused", True)
ok(dk.ACCEL.w.paused and dk.C["paused"], "pause option")
# 托盘版加速器（替身托盘，不开窗口）：读带好的 worker.json，连上 NAS，图标带状态
sys.path.insert(0, "/tmp/claude-0/stub") if os.path.exists("/tmp/claude-0/stub/pystray.py") else None
stubd = os.path.join(D, "stub"); os.makedirs(stubd, exist_ok=True)
open(os.path.join(stubd, "pystray.py"), "w").write('''
class MenuItem:
    def __init__(self, text, action, checked=None, default=False, enabled=True): self.text = text; self.action = action; self.checked = checked
class Menu:
    SEPARATOR = None
    def __init__(self, *items): self.items = items
class Icon:
    def __init__(self, name, img, title, menu): self.icon = img; self.title = title; self.menu = menu; self.notes = []
    def notify(self, msg, title=""): self.notes.append((title, msg))
    def update_menu(self): pass
    def run(self): pass
    def stop(self): pass
''')
sys.path.insert(0, stubd)
import worker as Wm
rp2 = cn.post("/api/desktop/pair", json={"device_id": "t" * 32, "device_name": "TRAY"}).get_json()
Wm.CONF = os.path.join(D, "worker_tray.json")
json.dump({"server": nas, "key": rp2["key"], "name_prefix": "Nok", "autostart_done": 1, "no_install": 1}, open(Wm.CONF, "w"))
at = importlib.import_module("accel_tray")
at.LOGF = os.path.join(D, "worker_tray.log")
c = Wm.load_conf()
at.start_worker(c)
icon = at.tray(c)
for _ in range(100):
    if at.state() == "在线": break
    time.sleep(0.2)
time.sleep(1.5)
names = [it.text if isinstance(it.text, str) else it.text(it) for it in icon.menu.items if it]
ok(at.state() == "在线" and any("在线" in n for n in names) and "也帮别人加速（同事的活）" in names and "退出加速器" in names, f"tray accel online {at.state()} {names}")
ok(icon.notes and "后台运行" in icon.notes[0][1] and os.path.exists(at.LOGF), f"first-run tip & log file {icon.notes}")
wn = [w for w in accel.workers() if w["name"].startswith("Nok@")]
ok(any(w["user"] == "nok" and w["online"] for w in wn), "tray accel registered as nok")
pause = [it for it in icon.menu.items if it and it.text == "暂停加速"][0]
pause.action(icon, pause)
ok(at.S["w"].paused and Wm.load_conf()["paused"], "pause from tray")
import trayicon
ok(trayicon.image("accel.png", "在线").size == (64, 64) and trayicon.image("accel.png", "暂停") is not trayicon.image("accel.png", "在线"), "status icons")
ws_.shutdown()
print("ERRORS", E)
