# v2.56（T36）桌面客户端：找 Bambu Studio / OrcaSlicer、保存后自动回传的判断、编辑任务、切片软件自检（服务器端 + 结果清单）
# Windows 上才能真跑软件：这里用模拟的文件系统 / 注册表 / HTTP / 进程测纯函数；自检的服务器端用真的 3MF 走一遍
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, json, zipfile, re, tempfile
D = T + "/m_slicerdesk256"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP); sys.path.insert(0, os.path.join(APP, "desktop"))
E_ = 0


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)


import numpy as np
import app as A
import slicer_edit as se
from core import db
from modules.model import slicerproj as sp
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("nok", "secret123", "production", "Nok")
cb, cn, C = A.app.test_client(), A.app.test_client(), A.app.test_client()
cb.post("/api/auth/login", json={"username": "boss", "password": "secret123"}); cn.post("/api/auth/login", json={"username": "nok", "password": "secret123"})

# ---------- 检测 ----------
ok(se.app_of_name("Bambu Studio") == "bambu" and se.app_of_name("OrcaSlicer 2.3.1") == "orca" and se.app_of_name("Orca Slicer") == "orca"
   and se.app_of_name("Bambu Handy") is None and se.app_of_name("Chrome") is None, "registry DisplayName -> app")
files = {r"D:\Apps\Bambu\bambu-studio.exe", r"C:\Program Files\OrcaSlicer\orca-slicer.exe"}
reg = [{"DisplayName": "Bambu Studio", "InstallLocation": r"D:\Apps\Bambu", "DisplayVersion": "02.02.01.60"},
       {"DisplayName": "OrcaSlicer", "DisplayVersion": "2.3.1"}, {"DisplayName": "Google Chrome"}]
d = se.detect(exists=lambda p: p in files, registry=reg)
ok(d["bambu"]["path"] == r"D:\Apps\Bambu\bambu-studio.exe" and d["bambu"]["version"] == "02.02.01.60" and d["bambu"]["source"] == "registry",
   f"Bambu found via registry InstallLocation {d['bambu']}")
ok(d["orca"]["path"] == r"C:\Program Files\OrcaSlicer\orca-slicer.exe" and d["orca"]["version"] == "2.3.1" and d["orca"]["source"] == "default",
   f"Orca found in default dir + version from registry {d['orca']}")
d = se.detect(exists=lambda p: False, registry=[])
ok(d == {"bambu": None, "orca": None}, "nothing installed")
d = se.detect(exists=lambda p: p == r"C:\X\OrcaSlicer.exe", registry=[{"DisplayName": "OrcaSlicer", "DisplayIcon": r'"C:\X\OrcaSlicer.exe",0'}])
ok(d["orca"] and d["orca"]["path"] == r"C:\X\OrcaSlicer.exe", "DisplayIcon used when no InstallLocation")
ok(se.read_registry() == [] or os.name == "nt", "registry read is empty off Windows")

# ---------- 保存后自动回传的判断 ----------
w = se.SaveWatcher((100.0, 10))
ok(not w.step(0, (100.0, 10)), "unchanged -> no upload")
ok(not w.step(1, (105.0, 50)), "changed: wait for stable")
ok(not w.step(2, (106.0, 80)), "still writing (changed again)")
ok(not w.step(3.5, (106.0, 80)), "stable 1.5 s: not yet")
ok(not w.step(4.1, (106.0, 80), valid=lambda: False), "stable 2 s but broken zip: wait")
ok(w.step(4.2, (106.0, 80)), "stable 2 s + valid -> upload")
ok(not w.step(9, (106.0, 80)), "same file not uploaded twice")
ok(not w.step(10, None), "file gone -> nothing")
good = io.BytesIO()
with zipfile.ZipFile(good, "w") as z:
    z.writestr("3D/3dmodel.model", "<model/>")
ok(se.is_valid_project(good.getvalue()) and not se.is_valid_project(good.getvalue()[:-30]) and not se.is_valid_project(b"xx"), "valid zip check (half-written file rejected)")
ok(se.halves((0, 0, 1920, 1040)) == ((0, 0, 960, 1040), (960, 0, 960, 1040)), "split halves")
ok(se.split_screen(1)[0] is False, "split screen off Windows: fails safely")
ok(se.safe_name('a/b:c*?.3mf') == "a_b_c_.3mf", "safe file name")

# ---------- 编辑任务（模拟下载 / 打开 / 保存 / 上传） ----------
HOME = tempfile.mkdtemp(dir=T)


class R:
    def __init__(self, code, content=b"", j=None):
        self.status_code, self.content, self._j = code, content, j

    def json(self):
        return self._j


ups, launched, clock = [], [], [1000.0]
job = se.EditJob({"sid": "se1", "app": "bambu", "download": "/api/slicer-edit/se1/file?t=x", "upload": "/api/slicer-edit/se1/upload?t=y",
                  "filename": "3DP0002_p1_BambuStudio.3mf"}, "http://nas:8790", {"bambu": {"path": r"C:\BS\bambu-studio.exe"}},
                 home=HOME, get=lambda url, timeout=0: R(200, good.getvalue()),
                 post=lambda url, data=None, headers=None, timeout=0: (ups.append((url, len(data))), R(200, j={"ok": True, "confirm": [], "changes": []}))[1],
                 popen=lambda args, **kw: launched.append(args) or type("P", (), {"pid": 4242})(), clock=lambda: clock[0])
st = job.start(watch=False)
ok(st["status"] == "editing" and job.path.startswith(os.path.join(HOME, "Documents", "3D-Ops", "编辑中")) and os.path.exists(job.path), f"downloaded into 文档\\3D-Ops\\编辑中 {job.path}")
ok(launched and launched[0][0] == r"C:\BS\bambu-studio.exe" and launched[0][1] == job.path, "opened with Bambu Studio exe")
ok(not job.poll_once(), "nothing saved yet")
with open(job.path, "wb") as f:
    f.write(good.getvalue() + b"")
os.utime(job.path, (2000, 2000))
clock[0] = 1001; job.poll_once()
clock[0] = 1003.5
ok(job.poll_once() and ups and ups[0][0] == "http://nas:8790/api/slicer-edit/se1/upload?t=y" and job.state["syncs"] == 1, "saved + stable -> auto upload")
job.stop("done")
ok(job.state["status"] == "done" and not job.poll_once(), "stopped: no more uploads")
job2 = se.EditJob({"sid": "se2", "app": "orca", "download": "/x", "upload": "/y"}, "http://nas", {"bambu": {"path": "x"}}, home=HOME)
ok(job2.start(watch=False)["status"] == "no_app" and "OrcaSlicer" in job2.state["error"], "software not installed -> no_app")
job3 = se.EditJob({"sid": "se3", "app": "bambu", "download": "/d", "upload": "/u"}, "http://nas", {"bambu": {"path": "x"}}, home=HOME,
                  get=lambda url, timeout=0: R(200, good.getvalue()),
                  post=lambda url, data=None, headers=None, timeout=0: R(403, j={"error": "这次编辑已经结束（完成 / 放弃）"}),
                  popen=lambda args, **kw: type("P", (), {"pid": 1})(), clock=lambda: clock[0])
job3.start(watch=False)
os.utime(job3.path, (3000, 3000)); clock[0] = 2000; job3.poll_once(); clock[0] = 2003; job3.poll_once()
ok(job3.state["status"] == "ended" and "结束" in job3.state["error"], "server says session ended -> stop watching")

# ---------- 自检（服务器端） ----------
r = cn.post("/api/desktop/selftest/start", json={"apps": ["bambu", "orca"]})
runs = r.get_json()["runs"]
ok(r.status_code == 200 and set(runs) == {"bambu", "orca"}, "selftest start: one test plate per app")
from core import store
ok(not any("selftest" in (p.get("id") or "") for p in store.list_products()), "no test product created")
data = C.get(runs["orca"]["download"]).data
ok(data[:2] == b"PK" and C.get(runs["orca"]["download"]).status_code == 403, "test file one-time download without login")
rp = sp.read_project(data)
ok(len(rp["objects"]) == 2 and sorted(o["extruder"] for o in rp["objects"]) == [1, 2], "test plate: 2 objects, 2 slots")
r = C.post(runs["orca"]["upload"], data=data)
ck = r.get_json()["check"]
ok(r.status_code == 200 and ck["objects_ok"] and ck["slots_ok"] and ck["colours_ok"] and not ck["moved"], f"unchanged upload: all ok but not moved {ck}")
# 模拟在软件里挪了一下
model = zipfile.ZipFile(io.BytesIO(data)).read("3D/3dmodel.model").decode()
first = re.search(r'<item objectid="(\d+)"[^>]*transform="([^"]*)"', model)
model2 = model.replace(first.group(2), sp.tf_str(sp.rz(0), [95, 110, 0]))
bo = io.BytesIO()
with zipfile.ZipFile(bo, "w") as zo:
    zi = zipfile.ZipFile(io.BytesIO(data))
    for n in zi.namelist():
        zo.writestr(n, model2.encode() if n == "3D/3dmodel.model" else zi.read(n))
ck = C.post(runs["orca"]["upload"], data=bo.getvalue()).get_json()["check"]
ok(ck["moved"] and "95.0" in ck["moved_detail"], f"moved detected {ck['moved_detail']}")
ok(C.post(runs["orca"]["upload"].replace("t=", "t=bad"), data=data).status_code == 403, "selftest upload needs token")
det = {"bambu": None, "orca": {"path": "C:\\o.exe", "version": "2.3.1"}}
checks = se.selftest_checks(det, {"orca": {"opened": True, "uploaded": True, "server": ck}}, (False, "没找到切片软件的窗口"))
keys = {c["key"]: c["ok"] for c in checks}
ok(keys["bambu.installed"] is False and keys["orca.installed"] and keys["orca.moved"] and keys["split"] is False and "bambu.opened" not in keys,
   f"checklist {keys}")
ok(all(c["zh"] and c["th"] and not re.search(r"[\u4e00-\u9fff]", c["th"]) for c in checks), "checklist zh + th (no Chinese in Thai)")
r = cn.post("/api/desktop/selftest/report", json={"pc": "NOK-PC", "client": "2.56.0", "slicers": det, "checks": checks,
                                                 "sids": [runs["orca"]["sid"], runs["bambu"]["sid"]], "errors": []})
rec = r.get_json()["record"]
ok(r.status_code == 200 and rec["passed"] is False and rec["slicers"]["orca"]["version"] == "2.3.1", "report stored")
lg = cn.get("/api/desktop/selftest/log").get_json()["log"]
ok(lg and lg[0]["pc"] == "NOK-PC" and len(lg[0]["checks"]) == len(checks), "web can read latest selftest")
ok(C.get(runs["bambu"]["download"]).status_code == 403, "selftest files cleaned after report")

# ---------- 客户端 Api（不开窗口） ----------
os.environ["HOME"] = D; os.environ["LH_DESKTOP_ROOT"] = D
import importlib
dk = importlib.import_module("desktop_app")
info = dk.Api().info()
ok(info["edit"] and set(info["slicers"]) == {"bambu", "orca"}, "info() reports slicers")
ok(dk.Api().edit_in_slicer({"download": "/etc/passwd"})["status"] == "error", "edit_in_slicer only server edit urls")
ok(dk.Api().edit_status("nope")["status"] == "none" and dk.Api().edit_stop("nope")["status"] == "none", "status / stop unknown")
ok(dk.Api().selftest_checks(det, {}, None)[0]["key"] == "bambu.installed", "selftest_checks exposed to the page")
sys.exit(1 if E_ else 0)
