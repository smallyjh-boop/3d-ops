# v2.56（T36）在切片软件（Bambu Studio / OrcaSlicer）里编辑一盘：
# 1. 机型模板「切片软件」auto / bambu / orca 和 slicer_app_of
# 2. 生成的项目 3MF：core/mesh 读回位置一致；每个零件带编号；多零件文件保留成一个对象多个 part
# 3. 真 OrcaSlicer 打开再导出不崩溃、零件数一致；真 Orca 切生成的项目（两槽多色）成功
# 4. 模拟在软件里编辑（改位置 / 转角 / 槽、复制、删除、拆成对象、删组件、给组件换槽、合并回组合）→ 上传 → 方案同步正确
# 5. 锁（同一盘只能一人编辑）、一次性下载、完成 / 放弃
# 6. 安全核对：槽改成 PETG、零件移出热床 → 需要确认，确认前不能切片
# 7. 主文件变了旧切片作废；网页保存没改摆盘保留主文件
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, re, io, zipfile, subprocess, tempfile, time
D = T + "/m_slicerapp36"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)


import numpy as np
import app as A
from core import db, store, modellib, mesh, slicer, fleet
from core.config import load_config, save_config
from modules.model import printplan as pp, slicerproj as sp, editsession as es
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pong", "secret123", "production", "Pong")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
PC = A.app.test_client(); PC.post("/api/auth/login", json={"username": "pong", "password": "secret123"})
ANON = A.app.test_client()
ORCA = slicer.find_orca(load_config())
WORK = tempfile.mkdtemp(prefix="t36_", dir=T)


def box(w, d, h, o=(0, 0, 0)):
    v = np.array([[0, 0, 0], [w, 0, 0], [w, d, 0], [0, d, 0], [0, 0, h], [w, 0, h], [w, d, h], [0, d, h]], float) + np.array(o, float)
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return v[np.array(f)]


def orca(args, cwd):
    return subprocess.run([ORCA] + args, cwd=cwd, capture_output=True, timeout=300)


# ---------- 1. 切片软件选择 ----------
save_config({"printers": [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "tech": "fdm"},
                          {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "enabled": True, "tech": "fdm"}]})
ok(fleet.slicer_app_of({"printer": "Bambu Lab P1S"}) == "bambu", "auto: Bambu plate -> Bambu Studio")
ok(fleet.slicer_app_of({"printer": "Creality K1C"}) == "orca", "auto: K1C plate -> OrcaSlicer")
ok(fleet.slicer_app_of("Creality K1 Max") == "orca" and fleet.slicer_app_of("Bambu Lab X1 Carbon") == "bambu", "by model name")
cfg = load_config()
ok(fleet.slicer_app_of(cfg["printers"][0]) == "bambu", "printer dict (effective)")
r = C.post("/api/fleet/templates", json={"templates": {"Bambu Lab P1S": {"slicer_app": "orca"}, "Creality K1C": {"slicer_app": "bambu"}}})
ok(r.status_code == 200, f"save template slicer_app {r.status_code}")
ok(fleet.slicer_app_of({"printer": "Bambu Lab P1S"}) == "orca" and fleet.slicer_app_of({"printer": "Creality K1C"}) == "bambu", "template choice wins")
r = C.post("/api/fleet/templates", json={"templates": {"Bambu Lab P1S": {"slicer_app": "photoshop"}}})
ok(r.status_code == 400, "bad slicer_app rejected")
C.post("/api/fleet/templates", json={"templates": {"Bambu Lab P1S": {"slicer_app": "auto"}, "Creality K1C": {"slicer_app": ""}}})
ok(fleet.slicer_app_of({"printer": "Bambu Lab P1S"}) == "bambu" and "slicer_app" not in (load_config()["printer_models"].get("Bambu Lab P1S") or {}),
   "auto = not stored, back to brand rule")
ok(fleet.clean_value("slicer_app", "BAMBU") == "bambu" and fleet.clean_value("slicer_app", "auto") is None, "clean_value")

# ---------- 准备产品：方块、扁盒、3 个组件的组合 3MF ----------
PID = "3DP0002"
p = store.load(PID)
p["material"] = "PLA"
p.pop("print_plans", None)
store.save(p)
cube = os.path.join(WORK, "cube.stl"); mesh.write_stl(box(20, 20, 20), cube)
flat = os.path.join(WORK, "flat.stl"); mesh.write_stl(box(40, 16, 6), flat)


def kit_3mf(path):
    """3 个组件（底座 / 手臂 / 头）的组合 3MF（拓竹那样：build 里 3 个 item，名字在 model_settings 里）。"""
    meshes = [("底座 base", box(30, 30, 6)), ("手臂 arm", box(8, 30, 8, (40, 0, 0))), ("头 head", box(14, 14, 14, (60, 0, 0)))]
    res, build, ms = "", "", ""
    for i, (nm, t) in enumerate(meshes, start=1):
        v = t.reshape(-1, 3)
        u, inv = np.unique(v, axis=0, return_inverse=True)
        vs = "".join(f'<vertex x="{a}" y="{b}" z="{c}"/>' for a, b, c in u)
        ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in inv.reshape(-1, 3))
        res += f'<object id="{i}" type="model"><mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>'
        build += f'<item objectid="{i}" transform="1 0 0 0 1 0 0 0 1 50 50 0"/>'
        ms += f'<object id="{i}"><metadata key="name" value="{nm}"/><metadata key="extruder" value="1"/></object>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("3D/3dmodel.model", '<?xml version="1.0"?><model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
                   f"<resources>{res}</resources><build>{build}</build></model>")
        z.writestr("Metadata/model_settings.config", f'<?xml version="1.0"?><config>{ms}</config>')


kit = os.path.join(WORK, "kit.3mf"); kit_3mf(kit)
lib = modellib.upload(PID, [modellib.SavedFile(cube, "cube.stl"), modellib.SavedFile(flat, "flat.stl"), modellib.SavedFile(kit, "kit.3mf")], "boss")
CUBE, FLAT, KIT = lib[0]["id"], lib[1]["id"], lib[2]["id"]
ok(len(modellib.load_parts(modellib.path_of(PID, modellib._entry(store.load(PID), KIT)))) == 3, "kit has 3 components")
p = store.load(PID)
p["model"] = dict(p.get("model") or {}, lib_id=CUBE, file=lib[0]["file"], orig_name="cube.stl")
store.save(p)

plate1 = {"id": "p1", "name": "", "printer": "Bambu Lab P1S", "layer_height": 0.2, "sets": 1, "manual": True,
          "slots": [{"slot": 1, "material": "PLA", "colour": "白色"}, {"slot": 2, "material": "PLA", "colour": "黑色"}],
          "items": [{"uid": "ia1", "id": CUBE, "part": None, "orient": "bottom", "slot": 1, "x": 60, "y": 60, "rot": 0},
                    {"uid": "ib1", "id": FLAT, "part": None, "orient": "bottom", "slot": 2, "x": 150, "y": 70, "rot": 30},
                    {"uid": "ic1", "id": FLAT, "part": None, "orient": "front", "slot": 1, "x": 90, "y": 180, "rot": 90, "mirror": "x"},
                    {"uid": "id1", "id": CUBE, "part": None, "orient": "bottom", "slot": 2, "x": 200, "y": 200, "rot": 0, "scale": 0.5}]}
r = pp.save_plan(PID, "", {"plates": [plate1]}, "boss")
plan = pp.get_plan(store.load(PID), "")
P1 = plan["plates"][0]
BY = {it["uid"]: it for it in P1["items"]}

# ---------- 2. 生成项目 3MF，core/mesh 读回位置一致 ----------
out = os.path.join(WORK, "p1_orca.3mf")
b = sp.build_project(PID, "", "p1", "", "orca", out)
z = zipfile.ZipFile(out)
names = z.namelist()
ok("Metadata/model_settings.config" in names and "3D/3dmodel.model" in names, "project has model + model_settings")
ok(b["settings"] == bool(ORCA) and (("Metadata/project_settings.config" in names) == bool(ORCA)), f"project_settings written when Orca present {b['notes']}")
if ORCA:
    ps = json.loads(z.read("Metadata/project_settings.config"))
    ok(ps.get("printer_settings_id", "").startswith("Bambu Lab P1S") and len(ps.get("filament_colour") or []) == 2, f"settings printer {ps.get('printer_settings_id')}")
    ok([c.upper() for c in ps["filament_colour"]] == ["#F4F4F2", "#202124"], f"filament colours by scheme {ps['filament_colour']}")
    ok(len(ps.get("filament_settings_id") or []) == 2 and ps.get("print_settings_id"), "filament / process profile names")
ms = z.read("Metadata/model_settings.config").decode()
ok(all(f"#{u}" in ms for u in BY), "every object named with #uid")
ok('<metadata key="extruder" value="2"/>' in ms, "slot -> extruder")
sc = mesh.scene_3mf(open(out, "rb").read())
ok(len(sc) == 4, f"scene has 4 objects {len(sc)}")
fps = pp.fps_for(PID, store.load(PID), P1)
for (nm, tris), uid in zip(sc, ["ia1", "ib1", "ic1", "id1"]):
    v = tris.reshape(-1, 3)
    it = BY[uid]
    x, y = sp.place_xy(tris, it["rot"])
    ok(abs(x - it["x"]) < 0.05 and abs(y - it["y"]) < 0.05 and abs(v[:, 2].min()) < 1e-3, f"{uid} position read back {x:.2f},{y:.2f}")
    ok(abs(v[:, 2].max() - fps[uid]["h"]) < 0.11, f"{uid} height same as web footprint {v[:, 2].max():.1f}/{fps[uid]['h']}")
rp = sp.read_project(open(out, "rb").read())
for o in rp["objects"]:
    src = BY[o["uid"]]
    d = sp.decompose(sp.orient_matrix(src) @ o["lin"])
    ok(d["orient"] == src["orient"] and abs((d["rot"] - src["rot"] + 180) % 360 - 180) < 0.05 and d["mirror"] == (src.get("mirror") or "")
       and abs(d["scale"] - (src.get("scale") or 1)) < 1e-4, f"{o['uid']} decompose {d}")

# ---------- 3. 真 OrcaSlicer：打开再导出、切片 ----------
if ORCA:
    wd = tempfile.mkdtemp(dir=WORK)
    r = orca(["--export-3mf", "re.3mf", "--outputdir", wd, out], wd)
    ok(r.returncode == 0 and os.path.exists(os.path.join(wd, "re.3mf")), f"Orca opens + exports our project rc={r.returncode}")
    ok(not os.path.exists(os.path.join(APP, "result.json")), "Orca result.json not written into repo")
    rr = sp.read_project(open(os.path.join(wd, "re.3mf"), "rb").read())
    ok(len(rr["objects"]) == 4 and sorted(o["uid"] for o in rr["objects"]) == sorted(BY), f"Orca keeps 4 objects + uids {[o['uid'] for o in rr['objects']]}")
    ok(sorted(o["extruder"] for o in rr["objects"]) == [1, 1, 2, 2], "Orca keeps extruders")
    for o in rr["objects"]:
        src = BY[o["uid"]]
        x, y = sp.place_xy(o["world"], src["rot"])
        ok(abs(x - src["x"]) < 0.1 and abs(y - src["y"]) < 0.1, f"after Orca round trip {o['uid']} at {x:.1f},{y:.1f}")
    RE_ORCA = open(os.path.join(wd, "re.3mf"), "rb").read()
    res = es.slice_master(load_config(), out, 1, "PLA")
    ok(res.get("grams") and len([f for f in res.get("filaments") or [] if f.get("grams")]) == 2, f"real Orca slices generated 2-colour project {res.get('grams')} {res.get('filaments')}")
else:
    print("（没有 OrcaSlicer：跳过真切片）")
    RE_ORCA = None

# ---------- 5. 会话：开始 / 锁 / 下载 ----------
r = C.post(f"/api/products/{PID}/print-plan/edit/start", json={"spec": "", "plate_id": "p1"})
S1 = r.get_json()
ok(r.status_code == 200 and S1["session"]["app"] == "bambu" and S1["app_name"] == "Bambu Studio", f"start edit (Bambu plate -> Bambu Studio) {r.status_code}")
r = PC.post(f"/api/products/{PID}/print-plan/edit/start", json={"spec": "", "plate_id": "p1"})
ok(r.status_code == 409 and r.get_json()["locked"]["user"] == "boss" and "Boss" in r.get_json()["error"], "second person locked out, shows who")
st = C.get(f"/api/products/{PID}/print-plan/edit/status").get_json()
ok(st["plates"][0]["session"]["user"] == "boss" and st["plates"][0]["app"] == "bambu", "status shows lock")
r = ANON.get(S1["download"])
ok(r.status_code == 200 and r.data[:2] == b"PK", "one-time download works without login")
DL = r.data
ok(ANON.get(S1["download"]).status_code == 403, "download link only once")
ok(ANON.post(S1["upload"].replace("t=", "t=x"), data=DL).status_code == 403, "upload with wrong token refused")
ok(ANON.post(S1["upload"], data=b"not a zip").status_code == 400, "half-saved / not zip refused")
SID = S1["session"]["id"]; TOK = S1["upload"].split("t=")[1]
# 锁超时
s_ = es.get(SID)
ok(es.open_for(PID, "", "p1", now=s_["touched"] + es.LOCK_TTL + 5) == [], "lock auto-expires after 2 h")
d_ = es._load(); d_[SID]["status"] = "open"; es._save(d_)


# ---------- 4. 模拟在软件里编辑 ----------
def edit(data, fn_model=None, fn_ms=None, fn_ps=None):
    zi = zipfile.ZipFile(io.BytesIO(data)); bo = io.BytesIO()
    with zipfile.ZipFile(bo, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in zi.namelist():
            x = zi.read(n)
            if n == "3D/3dmodel.model" and fn_model:
                x = fn_model(x.decode()).encode()
            if n == "Metadata/model_settings.config" and fn_ms:
                x = fn_ms(x.decode()).encode()
            if n == "Metadata/project_settings.config" and fn_ps:
                x = json.dumps(fn_ps(json.loads(x))).encode()
            zo.writestr(n, x)
    return bo.getvalue()


def obj_ids(data):
    """{uid: 根对象 id}"""
    ms_ = zipfile.ZipFile(io.BytesIO(data)).read("Metadata/model_settings.config").decode()
    out_ = {}
    for m in re.finditer(r'<object id="(\d+)">\s*<metadata key="name" value="([^"]*)"', ms_):
        out_[sp.uid_of(m.group(2))] = m.group(1)
    return out_


def set_tf(model, oid, tf):
    return re.sub(rf'(<item objectid="{oid}"[^>]*transform=")[^"]*', lambda m: m.group(1) + tf, model)


def drop_item(model, oid):
    return re.sub(rf'\s*<item objectid="{oid}"[^>]*/>', "", model)


base_data = RE_ORCA or DL
ids = obj_ids(base_data)
# ia1：挪到 (100, 120)、转 90°；ib1：换到槽 1；ic1：复制一个放到 (200, 120)；id1：删掉


def m1(model):
    model = set_tf(model, ids["ia1"], sp.tf_str(sp.rz(90), [100, 120, 0]))
    m = re.search(rf'<item objectid="{ids["ic1"]}"[^>]*/>', model)
    dup = re.sub(r'objectid="\d+"', 'objectid="999"', m.group(0))
    dup = re.sub(r'transform="[^"]*"', 'transform="' + sp.tf_str(sp.rz(90), [200, 120, 0]) + '"', dup)
    dup = re.sub(r'\s*p:UUID="[^"]*"', "", dup)
    obj = re.search(rf'<object id="{ids["ic1"]}"[^>]*>.*?</object>', model, re.S).group(0)
    obj2 = re.sub(rf'<object id="{ids["ic1"]}"', '<object id="999"', obj, count=1)
    obj2 = re.sub(r'\s*p:UUID="[^"]*"', "", obj2)
    model = model.replace("</resources>", obj2 + "</resources>").replace(m.group(0), m.group(0) + dup)
    return drop_item(model, ids["id1"])


def ms1(ms_):
    o = re.search(rf'<object id="{ids["ib1"]}">.*?</object>', ms_, re.S).group(0)
    ms_ = ms_.replace(o, re.sub(r'<metadata key="extruder" value="\d+"/>', '<metadata key="extruder" value="1"/>', o))
    c = re.search(rf'<object id="{ids["ic1"]}">.*?</object>', ms_, re.S).group(0)
    return ms_.replace("</config>", re.sub(rf'<object id="{ids["ic1"]}">', '<object id="999">', c, count=1) + "</config>")


E1 = edit(base_data, m1, ms1)
p_before = pp.get_plan(store.load(PID), "")
r = ANON.post(S1["upload"], data=E1)
R1 = r.get_json()
ok(r.status_code == 200 and R1["ok"], f"upload from desktop (token) {r.status_code} {R1.get('error')}")
plan = pp.get_plan(store.load(PID), "")
pl = plan["plates"][0]
its = {it["uid"]: it for it in pl["items"]}
ok(set(its) >= {"ia1", "ib1", "ic1"} and "id1" not in its and len(pl["items"]) == 4, f"deleted id1, kept others + one copy {sorted(its)}")
a = its.get("ia1") or {}
ok(abs(a.get("x", 0) - 100) < 0.1 and abs(a.get("y", 0) - 120) < 0.1 and abs(a.get("rot", 0) - 90) < 0.1, f"ia1 moved+rotated {a.get('x')},{a.get('y')},{a.get('rot')}")
ok((its.get("ib1") or {}).get("slot") == 1, "ib1 extruder 2 -> slot 1")
cp = [it for u, it in its.items() if u not in BY]
ok(len(cp) == 1 and cp[0]["id"] == FLAT and cp[0]["orient"] == "front" and cp[0].get("mirror") == "x" and abs(cp[0]["x"] - 200) < 0.1,
   f"copy of ic1 is a new item with same model/orientation {cp}")
ok(its["ic1"]["orient"] == "front" and its["ic1"].get("mirror") == "x" and abs(its["ic1"]["rot"] - 90) < 0.1, "ic1 orientation untouched")
m = pl.get("master") or {}
ok(m.get("sha") and m.get("file") and es.master_path(PID, "", pl), "upload stored as plate master file")
ok(pl.get("confirm") == [] or pl.get("confirm") is None or all("PETG" not in c["zh"] for c in pl["confirm"]), f"no material issue {pl.get('confirm')}")
ok(any(c["zh"] == "复制了零件" for c in R1["changes"]) and R1["deleted"] == 1, "changes report copy + delete")
web = C.get(f"/api/products/{PID}/print-plan").get_json()["plan"]["plates"][0]
ok(len(web["items"]) == 4 and abs([i for i in web["items"] if i["uid"] == "ia1"][0]["x"] - 100) < 0.1, "web plan shows the same")
SIG1 = pp.plate_sig(pl)

# 网页保存（没改摆盘）保留主文件；改了摆盘 → 主文件不再用
r = C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": web and C.get(f"/api/products/{PID}/print-plan").get_json()["plan"]})
pl = pp.get_plan(store.load(PID), "")["plates"][0]
ok(r.status_code == 200 and (pl.get("master") or {}).get("sha") == m["sha"], f"web save without layout change keeps master {r.status_code} {r.get_json().get('error') if r.status_code != 200 else ''}")

# ---------- 7. 主文件变了旧切片作废 ----------
if ORCA:
    rs = C.post(f"/api/products/{PID}/print-plan/slice", json={"spec": "", "plate_id": "p1"})
    j = rs.get_json()
    ok(rs.status_code == 200 and j.get("ok"), f"slice plate with master {rs.status_code} {j.get('error', '')[:300]}")
    pl = pp.get_plan(store.load(PID), "")["plates"][0]
    ok(bool(pl.get("sliced")), "sliced result stored")
E2 = edit(E1, lambda md: set_tf(md, ids["ia1"], sp.tf_str(sp.rz(0), [110, 120, 0])))
r = ANON.post(S1["upload"], data=E2)
pl = pp.get_plan(store.load(PID), "")["plates"][0]
ok(r.status_code == 200 and not pl.get("sliced") and pp.plate_sig(pl) != SIG1, "new master -> old slicing invalid, signature changed")
ok(len(es.history(PID, "", "p1")) == 2 and len(pl["master"].get("history") or []) == 1, "history keeps previous master")
sig_a = pp.plate_sig(pl)
pl2 = dict(pl, master=dict(pl["master"], sha="0" * 64))
ok(pp.plate_sig(pl2) != sig_a, "plate_sig includes master hash")

# ---------- 6. 安全核对 ----------
E3 = edit(E2, lambda md: set_tf(md, ids["ia1"], sp.tf_str(sp.rz(0), [300, 120, 0])),
          fn_ps=lambda ps_: dict(ps_, filament_type=["PETG"] + list(ps_.get("filament_type", [])[1:])) if ps_ else ps_)
if not zipfile.ZipFile(io.BytesIO(E3)).namelist().count("Metadata/project_settings.config"):
    E3 = edit(E3)
r = ANON.post(S1["upload"], data=E3)
R3 = r.get_json()
pl = pp.get_plan(store.load(PID), "")["plates"][0]
txt = " ".join(c["zh"] for c in pl.get("confirm") or [])
ok(r.status_code == 200 and "超出热床" in txt, f"moved off bed -> needs confirm: {txt[:200]}")
if ORCA:
    ok("PETG" in txt and pl["slots"][0]["material"] == "PETG", "slot 1 changed to PETG -> needs confirm, slot updated")
ok(all(c.get("th") for c in pl["confirm"]), "confirm reasons have Thai")
rs = C.post(f"/api/products/{PID}/print-plan/slice", json={"spec": "", "plate_id": "p1"})
ok(rs.status_code == 400 and "需要确认" in rs.get_json()["error"], "cannot slice before confirm")
r = C.post(f"/api/products/{PID}/print-plan/edit/confirm", json={"spec": "", "plate_id": "p1"})
pl = pp.get_plan(store.load(PID), "")["plates"][0]
ok(r.status_code == 200 and not pl.get("confirm") and pl["confirmed"]["by"] == "boss", "confirm clears it, records who")

# 放弃：回到开始编辑前
r = C.post(f"/api/products/{PID}/print-plan/edit/abandon", json={"sid": SID})
pl = pp.get_plan(store.load(PID), "")["plates"][0]
ok(r.status_code == 200 and sorted(it["uid"] for it in pl["items"]) == sorted(BY) and not pl.get("master"), "abandon restores the plate before editing")
ok(ANON.post(S1["upload"], data=E1).status_code == 403, "upload after abandon refused")
ok(PC.post(f"/api/products/{PID}/print-plan/edit/start", json={"spec": "", "plate_id": "p1"}).status_code == 200, "lock released: pong can edit now")
sid_p = es.open_for(PID, "", "p1")[0]["id"]
ok(C.post(f"/api/products/{PID}/print-plan/edit/finish", json={"sid": sid_p}).status_code == 200, "owner can finish someone's session")
ok(es.open_for(PID, "", "p1") == [], "finish releases lock")

# ---------- 多零件（3 个组件的组合） ----------
plate2 = {"id": "p1", "name": "", "printer": "Bambu Lab P1S", "layer_height": 0.2, "sets": 1, "manual": True,
          "slots": [{"slot": 1, "material": "PLA", "colour": "白色"}, {"slot": 2, "material": "PLA", "colour": "黑色"}],
          "items": [{"uid": "ik1", "id": KIT, "part": None, "orient": "bottom", "slot": 1, "x": 128, "y": 128, "rot": 0}]}
pp.save_plan(PID, "", {"plates": [plate2]}, "boss")
r = C.post(f"/api/products/{PID}/print-plan/edit/start", json={"spec": "", "plate_id": "p1", "app": "orca"})
S2 = r.get_json()
ok(r.status_code == 200 and S2["session"]["app"] == "orca", "start with explicit app = orca")
KD = ANON.get(S2["download"]).data
rk = sp.read_project(KD)
ok(len(rk["objects"]) == 1 and len(rk["objects"][0]["parts"]) == 3, f"whole kit = one object with 3 parts {[len(o['parts']) for o in rk['objects']]}")
pn = [x["name"] for x in rk["objects"][0]["parts"]]
ok(any("底座" in n for n in pn) and all(sp.src_of(n) and sp.src_of(n)[0] == "ik1" for n in pn), f"part names readable + #uid.component {pn}")
if ORCA:
    wd = tempfile.mkdtemp(dir=WORK)
    open(os.path.join(wd, "kit.3mf"), "wb").write(KD)
    r = orca(["--export-3mf", "re.3mf", "--outputdir", wd, "kit.3mf"], wd)
    rk2 = sp.read_project(open(os.path.join(wd, "re.3mf"), "rb").read()) if r.returncode == 0 else {"objects": []}
    ok(r.returncode == 0 and len(rk2["objects"]) == 1 and len(rk2["objects"][0]["parts"]) == 3, f"Orca keeps kit as 1 object / 3 parts rc={r.returncode}")
    ok(sorted(sp.src_of(x["name"])[1] for x in rk2["objects"][0]["parts"]) == [0, 1, 2], "Orca keeps part names (#uid.component)")
    KBASE = open(os.path.join(wd, "re.3mf"), "rb").read()
else:
    KBASE = KD
TK = S2["upload"]


def split_objects(data, drop_ci=None, slot_ci=None):
    """模拟「拆成对象」：一个对象的每个 part 变成单独的对象（保持世界位置），可以顺便删一个组件、给一个组件换槽。"""
    zi = zipfile.ZipFile(io.BytesIO(data))
    model = zi.read("3D/3dmodel.model").decode()
    msx = zi.read("Metadata/model_settings.config").decode()
    root = re.search(r'<object id="(\d+)"[^>]*>\s*<components>(.*?)</components>', model, re.S)
    item = re.search(rf'<item objectid="{root.group(1)}"[^>]*transform="([^"]*)"', model)
    it_m = mesh._mat(item.group(1))
    comps = re.findall(r'<component ([^>]*)/>', root.group(2))
    pmeta = dict(re.findall(r'<part id="(\d+)"[^>]*>.*?<metadata key="name" value="([^"]*)"', msx, re.S))
    objs_, items_, mss = "", "", ""
    nid = 500
    for c in comps:
        at = dict(re.findall(r'([\w:]+)="([^"]*)"', c))
        nm = pmeta[at["objectid"]]
        ci = sp.src_of(nm)[1]
        if ci == drop_ci:
            continue
        cm = mesh._mat(at.get("transform")) or (np.eye(3), np.zeros(3))
        R, t = mesh._compose(cm, it_m)
        objs_ += f'<object id="{nid}" type="model"><components><component p:path="{at["p:path"]}" objectid="{at["objectid"]}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object>'
        items_ += f'<item objectid="{nid}" transform="{sp.tf_str(R, t)}" printable="1"/>'
        ex = 2 if ci == slot_ci else 1
        mss += (f'<object id="{nid}"><metadata key="name" value="{nm}"/><metadata key="extruder" value="{ex}"/>'
                f'<part id="{at["objectid"]}" subtype="normal_part"><metadata key="name" value="{nm}"/><metadata key="extruder" value="{ex}"/></part></object>')
        nid += 1
    model = re.sub(r"<build[^>]*>.*?</build>", "<build>" + items_ + "</build>", model, flags=re.S).replace("</resources>", objs_ + "</resources>")
    msx = re.sub(r"<object id=.*</object>", mss, msx, flags=re.S)
    msx = re.sub(r"<plate>.*?</plate>", "", msx, flags=re.S)
    bo = io.BytesIO()
    with zipfile.ZipFile(bo, "w") as zo:
        for n in zi.namelist():
            x = zi.read(n)
            if n == "3D/3dmodel.model":
                x = model.encode()
            if n == "Metadata/model_settings.config":
                x = msx.encode()
            zo.writestr(n, x)
    return bo.getvalue()


KS = split_objects(KBASE, drop_ci=1, slot_ci=2)
r = ANON.post(TK, data=KS)
pl = pp.get_plan(store.load(PID), "")["plates"][0]
parts_ = sorted((it.get("part"), it["slot"]) for it in pl["items"])
ok(r.status_code == 200 and parts_ == [(0, 1), (2, 2)], f"split into objects, deleted arm, head -> slot 2: {parts_} {r.get_json().get('error')}")
ok(len({it.get("group") for it in pl["items"]}) == 1 or all(not it.get("group") for it in pl["items"]), "split objects: no stale group")
fpk = pp.fps_for(PID, store.load(PID), pl)
for it in pl["items"]:
    ok(abs(fpk[it["uid"]]["w"] - (30 if it["part"] == 0 else 14)) < 0.2, f"component {it['part']} footprint size right")
base_c = [it for it in pl["items"] if it["part"] == 0][0]
head_c = [it for it in pl["items"] if it["part"] == 2][0]
ok(abs((head_c["x"] - base_c["x"]) - 52) < 0.2, f"components keep relative position {head_c['x'] - base_c['x']:.1f}")
if ORCA:                                                   # 多色（不同零件不同槽）真切片
    res = es.slice_master(load_config(), es.master_path(PID, "", pl), 1, "PLA")
    ok(len([f for f in res.get("filaments") or [] if f.get("grams")]) == 2, f"split kit 2 colours sliced by real Orca {res.get('filaments')}")

# 合并回组合（软件里「组合」：几个对象合成一个对象，part 名字不变）
def merge_all(data):
    zi = zipfile.ZipFile(io.BytesIO(data))
    model = zi.read("3D/3dmodel.model").decode()
    msx = zi.read("Metadata/model_settings.config").decode()
    items = re.findall(r'<item objectid="(\d+)"[^>]*transform="([^"]*)"', model)
    comps, parts_x = "", ""
    for oid, tf in items:
        R, t = mesh._mat(tf)
        obj = re.search(rf'<object id="{oid}"[^>]*>\s*<components>(.*?)</components>', model, re.S).group(1)
        for c in re.findall(r"<component ([^>]*)/>", obj):
            at = dict(re.findall(r'([\w:]+)="([^"]*)"', c))
            comps += f'<component p:path="{at["p:path"]}" objectid="{at["objectid"]}" transform="{sp.tf_str(R, t)}"/>'
        o = re.search(rf'<object id="{oid}">(.*?)</object>', msx, re.S).group(1)
        parts_x += "".join(re.findall(r"<part .*?</part>", o, re.S))
    model = re.sub(r"<build[^>]*>.*?</build>", '<build><item objectid="900" transform="1 0 0 0 1 0 0 0 1 0 0 0" printable="1"/></build>', model, flags=re.S)
    model = model.replace("</resources>", f'<object id="900" type="model"><components>{comps}</components></object></resources>')
    msx = re.sub(r"<object id=.*</object>", f'<object id="900"><metadata key="name" value="Assembly"/><metadata key="extruder" value="1"/>{parts_x}</object>',
                 msx, flags=re.S)
    bo = io.BytesIO()
    with zipfile.ZipFile(bo, "w") as zo:
        for n in zi.namelist():
            x = zi.read(n)
            if n == "3D/3dmodel.model":
                x = model.encode()
            if n == "Metadata/model_settings.config":
                x = msx.encode()
            zo.writestr(n, x)
    return bo.getvalue()


KM = merge_all(KS)
r = ANON.post(TK, data=KM)
pl = pp.get_plan(store.load(PID), "")["plates"][0]
g = {it.get("group") for it in pl["items"]}
ok(r.status_code == 200 and len(pl["items"]) == 2 and len(g) == 1 and None not in g, f"merged back -> one group {[(it.get('part'), it.get('group')) for it in pl['items']]}")
ok(sorted((it.get("part"), it["slot"]) for it in pl["items"]) == [(0, 1), (2, 2)], "merged: per-part slots kept")
# 合并回全部 3 个组件 → 一件整个文件 + 每个组件的槽
KS2 = split_objects(KBASE, slot_ci=2)
r = ANON.post(TK, data=merge_all(KS2))
pl = pp.get_plan(store.load(PID), "")["plates"][0]
ok(len(pl["items"]) == 1 and pl["items"][0]["part"] is None and pl["items"][0].get("part_slots", {}).get("2") == 2, f"all 3 merged -> whole file item with part_slots {pl['items']}")
# 新加的模型（对应不上）
def add_unknown(data):
    zi = zipfile.ZipFile(io.BytesIO(data))
    model = zi.read("3D/3dmodel.model").decode()
    v = box(10, 10, 10).reshape(-1, 3)
    u, inv = np.unique(v, axis=0, return_inverse=True)
    vs = "".join(f'<vertex x="{a}" y="{b}" z="{c}"/>' for a, b, c in u)
    ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in inv.reshape(-1, 3))
    model = model.replace("</resources>", f'<object id="777" name="Cylinder" type="model"><mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object></resources>')
    model = model.replace("</build>", '<item objectid="777" transform="1 0 0 0 1 0 0 0 1 20 200 0" printable="1"/></build>')
    bo = io.BytesIO()
    with zipfile.ZipFile(bo, "w") as zo:
        for n in zi.namelist():
            zo.writestr(n, model.encode() if n == "3D/3dmodel.model" else zi.read(n))
    return bo.getvalue()


r = ANON.post(TK, data=add_unknown(merge_all(KS2)))
pl = pp.get_plan(store.load(PID), "")["plates"][0]
ok(r.status_code == 200 and len(pl["items"]) == 2 and any("对应不上" in c["zh"] for c in pl.get("confirm") or []), "unknown new model -> stored + needs confirm")
# 软件里多了一盘
def second_plate(data):
    zi = zipfile.ZipFile(io.BytesIO(data))
    msx = zi.read("Metadata/model_settings.config").decode()
    model = zi.read("3D/3dmodel.model").decode()
    oids = re.findall(r'<item objectid="(\d+)"', model)
    msx = re.sub(r"<plate>.*?</plate>", "", msx, flags=re.S)
    msx = msx.replace("</config>", f'<plate><metadata key="plater_id" value="1"/><model_instance><metadata key="object_id" value="{oids[0]}"/></model_instance></plate>'
                      f'<plate><metadata key="plater_id" value="2"/><model_instance><metadata key="object_id" value="{oids[1]}"/></model_instance></plate></config>')
    # 第 2 盘的零件在场景里在第 1 盘右边（盘宽 × 1.2）
    model = re.sub(rf'(<item objectid="{oids[1]}"[^>]*transform=")([^"]*)"',
                   lambda m: m.group(1) + " ".join(m.group(2).split()[:9] + [str(float(m.group(2).split()[9]) + 256 * 1.2)] + m.group(2).split()[10:]) + '"', model)
    bo = io.BytesIO()
    with zipfile.ZipFile(bo, "w") as zo:
        for n in zi.namelist():
            x = zi.read(n)
            zo.writestr(n, model.encode() if n == "3D/3dmodel.model" else msx.encode() if n == "Metadata/model_settings.config" else x)
    return bo.getvalue()


r = ANON.post(TK, data=second_plate(KS2))
plan = pp.get_plan(store.load(PID), "")
ok(r.status_code == 200 and len(plan["plates"]) == 2 and plan["plates"][1]["master"]["plate_no"] == 2 and plan["plates"][1]["items"],
   f"software plate 2 -> new plan plate {[len(x['items']) for x in plan['plates']]} {r.get_json().get('error')}")
it2 = plan["plates"][1]["items"][0]
ok(0 < it2["x"] < 256, f"plate 2 item position relative to its own plate {it2['x']}")
ok(C.post(f"/api/products/{PID}/print-plan/edit/finish", json={"sid": S2["session"]["id"]}).status_code == 200, "finish kit session")

# ================= 审查修复（v2.56 复审） =================
from core import print_files, production
plan = pp.get_plan(store.load(PID), "")
ok(len(plan["plates"]) == 2 and plan["plates"][1].get("master_of") == "p1", "precondition: p2 derived from p1's project")
P2 = plan["plates"][1]["id"]
# 必修 1：同一会话里同一个多盘文件存好几次，不会把第 2 盘加好几遍；盘 id 不变
r = C.post(f"/api/products/{PID}/print-plan/edit/start", json={"spec": "", "plate_id": "p1", "app": "orca"})
S3 = r.get_json()
ok(r.status_code == 200 and S3["session"]["from_master"], "edit p1 again: continues from its master file")
D3 = ANON.get(S3["download"]).data
for k in range(3):
    rr = ANON.post(S3["upload"], data=D3)
plan = pp.get_plan(store.load(PID), "")
ok(rr.status_code == 200 and len(plan["plates"]) == 2 and plan["plates"][1]["id"] == P2, f"3 uploads of a 2-plate file -> still 2 plates, same id {[x['id'] for x in plan['plates']]}")
ok(C.post(f"/api/products/{PID}/print-plan/edit/finish", json={"sid": S3["session"]["id"]}).status_code == 200, "finish S3")
# 必修 2：编辑分出来的盘（p2）：按方案重新生成这一盘，回传不会被第 1 盘覆盖、不会把零件当新模型
nlib = len(store.load(PID).get("model_lib") or [])
p2_uids = sorted(it["uid"] for it in plan["plates"][1]["items"])
r = C.post(f"/api/products/{PID}/print-plan/edit/start", json={"spec": "", "plate_id": P2, "app": "orca"})
S4 = r.get_json()
ok(r.status_code == 200 and not S4["session"]["from_master"] and any("分出来" in n["zh"] for n in S4["session"]["notes"]), "derived plate: regenerated from plan, with note")
D4 = ANON.get(S4["download"]).data
ok(sorted(o["uid"] for o in sp.read_project(D4)["objects"]) == p2_uids, "derived plate edit file has only its own parts")
rr = ANON.post(S4["upload"], data=D4)
plan = pp.get_plan(store.load(PID), "")
p2 = next(x for x in plan["plates"] if x["id"] == P2)
ok(rr.status_code == 200 and sorted(it["uid"] for it in p2["items"]) == p2_uids and len(plan["plates"]) == 2, f"p2 synced to itself {rr.get_json().get('error')}")
ok(len(store.load(PID).get("model_lib") or []) == nlib, "no part mistaken for a new model")
ok(not p2.get("master_of") and p2["master"]["plate_no"] == 1 and es.master_path(PID, "", p2), "p2 now has its own master")
C.post(f"/api/products/{PID}/print-plan/edit/finish", json={"sid": S4["session"]["id"]})
# 必修 3：主文件变了，旧的（已复核的）切片文件作废，生产不会再用；有需要确认时生产拒绝
if ORCA:
    rs = C.post(f"/api/products/{PID}/print-plan/slice", json={"spec": "", "plate_id": "p1"})
    fid = rs.get_json().get("file_id")
    f1 = print_files.get(fid)
    ok(rs.status_code == 200 and f1["plate_sig"] == pp.plate_sig(pp.get_plan(store.load(PID), "")["plates"][0]), "plan file records plate signature")
    db.conn().execute("UPDATE print_files SET status='reviewed' WHERE id=?", (fid,)); db.conn().commit()
    ok(pp.plate_file_check(PID, "", "p1", print_files.get(fid)) is True, "fresh reviewed file usable")
    r = C.post(f"/api/products/{PID}/print-plan/edit/start", json={"spec": "", "plate_id": "p1", "app": "orca"})
    S5 = r.get_json()
    D5 = ANON.get(S5["download"]).data
    D5b = edit(D5, fn_ms=lambda m_: m_.replace("</config>", '<!-- saved again --></config>'))     # 内容变了（新的主文件），摆盘不变
    ANON.post(S5["upload"], data=D5b)
    ok(print_files.get(fid)["active"] == 0, "new master -> old plan file set inactive")
    db.conn().execute("UPDATE print_files SET active=1 WHERE id=?", (fid,)); db.conn().commit()
    ok(pp.plate_file_check(PID, "", "p1", print_files.get(fid)) is False, "stale signature -> file not usable even if active")
    plan = pp.get_plan(store.load(PID), "")
    found = print_files.find(PID, "", "Bambu Lab P1S", "", plate_id="p1")
    ok(found is None or found["id"] != fid or not pp.plate_file_check(PID, "", "p1", found), "production lookup skips stale file")
    # 主文件按款式换颜色切：颜色记在文件上
    rs = C.post(f"/api/products/{PID}/print-plan/slice", json={"spec": "", "plate_id": "p1", "colour": "红色"})
    fj = print_files.get(rs.get_json().get("file_id") or 0) or {}
    ok(rs.status_code == 200 and fj.get("color") == "红色", f"master sliced for a colour records the colour {fj.get('color')} {rs.get_json().get('error', '')[:200]}")
    tmpc = os.path.join(WORK, "rc.3mf")
    es.recolour(es.master_path(PID, "", plan["plates"][0]), tmpc, ["#D62F2F", ""])
    pc = json.loads(zipfile.ZipFile(tmpc).read("Metadata/project_settings.config"))["filament_colour"]
    ok(pc[0] == "#D62F2F" and pc[1].upper() != "#D62F2F", f"recolour only changes filament_colour {pc}")
    C.post(f"/api/products/{PID}/print-plan/edit/finish", json={"sid": S5["session"]["id"]})
# 有需要确认 → 生产找文件时拒绝
p = store.load(PID)
p["print_plans"][""]["plates"][0]["confirm"] = [{"zh": "测试", "th": "ทดสอบ", "kind": "general"}]
store.save(p)
try:
    pp.plate_file_check(PID, "", "p1", {"plate_sig": "x"})
    ok(False, "confirm pending -> production refuses")
except ValueError as e:
    ok("需要确认" in str(e) and "ยืนยัน" in str(e), "confirm pending -> production refuses (zh + th)")
# 建议 8：机型类确认只有老板能确认，材料类有权限的人都能确认
p = store.load(PID)
p["print_plans"][""]["plates"][0]["confirm"] = [{"zh": "喷嘴不对", "th": "หัวฉีดไม่ตรง", "kind": "machine"}]
store.save(p)
r = PC.post(f"/api/products/{PID}/print-plan/edit/confirm", json={"spec": "", "plate_id": "p1"})
ok(r.status_code == 403 and "老板" in r.get_json()["error"], "machine-type confirm: production staff refused")
ok(C.post(f"/api/products/{PID}/print-plan/edit/confirm", json={"spec": "", "plate_id": "p1"}).status_code == 200, "owner can confirm machine-type")
p = store.load(PID)
p["print_plans"][""]["plates"][0]["confirm"] = [{"zh": "槽 1 换成 PETG", "th": "ช่อง 1 เป็น PETG", "kind": "material"}]
store.save(p)
ok(PC.post(f"/api/products/{PID}/print-plan/edit/confirm", json={"spec": "", "plate_id": "p1"}).status_code == 200, "material confirm: staff can confirm")
# 建议 6：网页改了摆盘丢主文件：未确认项进操作日志，材料类留在盘上，旧切片文件作废
p = store.load(PID)
pl0 = p["print_plans"][""]["plates"][0]
pl0["confirm"] = [{"zh": "槽 1 换成 PETG", "th": "x", "kind": "material"}, {"zh": "超出热床", "th": "x", "kind": "general"}]
store.save(p)
web = C.get(f"/api/products/{PID}/print-plan").get_json()["plan"]
web["plates"][0]["layer_height"] = 0.16
r = C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": web})
pl0 = pp.get_plan(store.load(PID), "")["plates"][0]
ok(r.status_code == 200 and not pl0.get("master") and [c["kind"] for c in pl0.get("confirm") or []] == ["material"], f"web layout change drops master, keeps material confirm {r.get_json().get('error')}")
au = db.conn().execute("SELECT detail FROM audit WHERE action LIKE '%主文件不再用%' ORDER BY id DESC LIMIT 1").fetchone()
ok(au and "超出热床" in au[0], "dropped confirm items written to audit log")
# 建议 4：主文件记着但文件没了：不悄悄按方案切
p = store.load(PID)
p2_ = next(x for x in p["print_plans"][""]["plates"] if x["id"] == P2)
mpth = es.master_path(PID, "", p2_)
os.rename(mpth, mpth + ".gone")
rs = C.post(f"/api/products/{PID}/print-plan/slice", json={"spec": "", "plate_id": P2})
ok(rs.status_code == 400 and "找不到" in rs.get_json()["error"], "missing master file -> error, no silent plan slicing")
os.rename(mpth + ".gone", mpth)
ok(p2_["master"]["file"] in es._referenced(PID, "", P2), "files referenced by plan are protected from history cleanup")
# 建议 7：别人在软件里编辑时网页不能改这一盘；同一个人编辑期间网页改了这一盘 → 回传拒绝不覆盖
r = PC.post(f"/api/products/{PID}/print-plan/edit/start", json={"spec": "", "plate_id": P2, "app": "orca"})
S6 = r.get_json()
web = C.get(f"/api/products/{PID}/print-plan").get_json()["plan"]
wp = next(x for x in web["plates"] if x["id"] == P2)
wp["layer_height"] = 0.16
r = C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": web})
ok(r.status_code == 400 and "Pong" in r.get_json()["error"] and "/" in r.get_json()["error"], f"boss cannot change the plate pong is editing {r.get_json().get('error', '')[:80]}")
D6 = ANON.get(S6["download"]).data
web = PC.get(f"/api/products/{PID}/print-plan").get_json()["plan"]
wp = next(x for x in web["plates"] if x["id"] == P2)
wp["layer_height"] = 0.16
ok(PC.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": web}).status_code == 200, "editor himself may change the plate in web")
r = ANON.post(S6["upload"], data=D6)
ok(r.status_code == 400 and "网页上被改过" in r.get_json()["error"], "upload after web change of the same plate refused (no overwrite)")
# 建议 9：结束以后的上传（拿锁后再查状态）
PC.post(f"/api/products/{PID}/print-plan/edit/abandon", json={"sid": S6["session"]["id"]})
ok(ANON.post(S6["upload"], data=D6).status_code == 403, "upload after end refused")
# 建议 1：上传上限比全局 60 MB 大（不是 413）
big = b"x" * (70 * 1048576)
r = C.post(f"/api/products/{PID}/print-plan/edit/start", json={"spec": "", "plate_id": P2, "app": "orca"})
S7 = r.get_json()
r = ANON.post(S7["upload"], data=big)
ok(r.status_code == 400, f"70 MB upload reaches the check (not 413) {r.status_code}")
del big
# 建议 2：zip 炸弹
bo = io.BytesIO()
with zipfile.ZipFile(bo, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("3D/3dmodel.model", "<model/>")
    z.writestr("3D/bomb.model", b"\0" * (60 * 1048576))
r = ANON.post(S7["upload"], data=bo.getvalue())
ok(r.status_code == 400 and "压缩比" in r.get_json()["error"], f"zip bomb rejected {r.status_code} {r.get_json()}")
C.post(f"/api/products/{PID}/print-plan/edit/finish", json={"sid": S7["session"]["id"]})
# 建议 10：服务器错误提示有泰文
ok(" / " in es.ENDED and "สิ้นสุด" in es.ENDED, "server errors have Thai")

# 按主模型缩放的规格不能编辑
ok(not os.path.exists(os.path.join(APP, "result.json")), "no result.json left in repo")
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if E_ else 0)
