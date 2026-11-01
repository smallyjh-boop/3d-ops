# v2.56（T37 ① ③）展示组装改用可靠来源：
# ① 3MF 里作者的「装配视图」位置（model_settings.config 的 <assemble><assemble_item>）和摆盘位置不同 → 展示直接用（作者装配）
# ③ 没有作者装配也没人工保存的：零件平铺图（整齐排开），不默认显示几何 / AI 猜的组装；文件里零件本来就叠在一起的按文件位置
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, zipfile, subprocess, tempfile
D = T + "/m_asm37"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)


import numpy as np
import app as A
from core import db, store, modellib, mesh, slicer
from core.config import load_config
from modules.model import assembly as asm, mating
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
WORK = tempfile.mkdtemp(prefix="t37_", dir=T)


def box(w, d, h):
    v = np.array([[0, 0, 0], [w, 0, 0], [w, d, 0], [0, d, 0], [0, 0, h], [w, 0, h], [w, d, h], [0, d, h]], float) - [w / 2, d / 2, 0]
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return v[np.array(f)]


def bambu_3mf(path, build, assemble=None):
    """拓竹格式（Bambu Studio 那样写）：3D/Objects 里的网格 + 根对象 components + build item；model_settings 里有 <assemble>。
    build / assemble：每个零件的 (x, y, z, 绕 Z 的角度)。"""
    parts = [("底座 base", box(40, 40, 8)), ("柱子 pole", box(10, 10, 30)), ("顶盖 cap", box(24, 24, 6))]
    sub, res, items, ms, asm_x, rels = "", "", "", "", "", ""
    for i, (nm, t) in enumerate(parts):
        v = t.reshape(-1, 3)
        u, inv = np.unique(v, axis=0, return_inverse=True)
        vs = "".join(f'<vertex x="{a}" y="{b}" z="{c}"/>' for a, b, c in u)
        ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in inv.reshape(-1, 3))
        mid, oid = 2 * i + 1, 2 * i + 2
        sub += f'<object id="{mid}" type="model"><mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>'
        res += f'<object id="{oid}" type="model"><components><component p:path="/3D/Objects/parts.model" objectid="{mid}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object>'

        def tf(x, y, z, a):
            c, s = np.cos(np.radians(a)), np.sin(np.radians(a))
            return f"{c:.6f} {s:.6f} 0 {-s:.6f} {c:.6f} 0 0 0 1 {x} {y} {z}"
        items += f'<item objectid="{oid}" transform="{tf(*build[i])}" printable="1"/>'
        ms += (f'<object id="{oid}"><metadata key="name" value="{nm}"/><metadata key="extruder" value="1"/>'
               f'<part id="{mid}" subtype="normal_part"><metadata key="name" value="{nm}"/></part></object>')
        if assemble:
            asm_x += f'<assemble_item object_id="{oid}" instance_id="0" transform="{tf(*assemble[i])}" offset="0 0 0"/>'
    ns = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
          'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", f'<?xml version="1.0"?><model unit="millimeter" {ns}><resources>{res}</resources><build>{items}</build></model>')
        z.writestr("3D/Objects/parts.model", f'<?xml version="1.0"?><model unit="millimeter" {ns}><resources>{sub}</resources><build/></model>')
        z.writestr("Metadata/model_settings.config", f'<?xml version="1.0"?><config>{ms}' + (f"<assemble>{asm_x}</assemble>" if assemble is not None else "") + "</config>")


FLAT = [(40, 40, 0, 0), (100, 40, 0, 0), (160, 40, 0, 0)]                       # 摆盘：一排平放
STACK = [(0, 0, 0, 0), (0, 0, 8, 0), (0, 0, 38, 45)]                             # 作者装配：叠起来、顶盖转 45°
f_author = os.path.join(WORK, "lamp_author.3mf"); bambu_3mf(f_author, FLAT, STACK)
f_same = os.path.join(WORK, "lamp_same.3mf"); bambu_3mf(f_same, FLAT, FLAT)       # 有 <assemble> 但和摆盘一样：不算作者装配
f_plain = os.path.join(WORK, "lamp_plain.3mf"); bambu_3mf(f_plain, FLAT, None)
f_stacked = os.path.join(WORK, "lamp_stacked.3mf"); bambu_3mf(f_stacked, STACK, None)   # 文件里本来就叠好

d = mesh.assembly_3mf(open(f_author, "rb").read())
ok(d is not None and len(d) == 3 and all(x is not None for x in d), "assemble_item read for 3 parts")
R, t = d[2]
ok(np.allclose(np.array([160, 40, 0]) @ R + t, [0, 0, 38], atol=1e-6) and abs(np.degrees(np.arctan2(R[0, 1], R[0, 0])) - 45) < 1e-4,
   "delta: plate position -> assembled position, rotation 45°")
ok(mesh.assembly_3mf(open(f_plain, "rb").read()) is None, "no <assemble> -> None")

PID = "3DP0002"


def use(path, name):
    lib = modellib.upload(PID, [modellib.SavedFile(path, name)], "boss")
    p = store.load(PID)
    p["model"] = dict(p.get("model") or {}, lib_id=lib[0]["id"], file=lib[0]["file"], orig_name=name)
    p.pop("display", None)
    store.save(p)
    return lib[0]["id"]


tmp = os.path.join(WORK, "u1.3mf"); shutil.copy(f_author, tmp)
EID = use(tmp, "lamp_author.3mf")
ok(asm.author_of(PID, modellib._entry(store.load(PID), EID)) is not None, "author assembly detected (differs from plate)")
r = C.get(f"/api/products/{PID}/display?spec=").get_json()
ok(r.get("default_source") == "author" and not r.get("saved_pose"), f"display default = author assembly {r.get('default_source')}")
pos = {x["part"]: x for x in r["parts"]}
ok(np.allclose(pos[0]["pos"], [0, 0, 4], atol=0.05) and np.allclose(pos[1]["pos"], [0, 0, 23], atol=0.05) and np.allclose(pos[2]["pos"], [0, 0, 41], atol=0.05),
   f"author positions (stacked) {[pos[i]['pos'] for i in range(3)]}")
ok(abs(abs(pos[2]["rot"][2]) - 45) < 0.1 and abs(pos[0]["rot"][2]) < 0.1, f"author rotation of the cap {pos[2]['rot']}")
t_ = asm.assembled_tris(PID, "")
v = t_.reshape(-1, 3)
ok(t_ is not None and abs((v[:, 2].max() - v[:, 2].min()) - 44) < 0.1, f"3D preview assembled from author view (height 44) {v[:, 2].max() - v[:, 2].min():.1f}")

tmp = os.path.join(WORK, "u2.3mf"); shutil.copy(f_same, tmp)
EID2 = use(tmp, "lamp_same.3mf")
ok(asm.author_of(PID, modellib._entry(store.load(PID), EID2)) is None, "<assemble> same as plate -> not author assembly")
r = C.get(f"/api/products/{PID}/display?spec=").get_json()
ok(r["default_source"] == "layout", f"no author assembly, parts apart -> parts layout {r['default_source']}")
ps = sorted(r["parts"], key=lambda x: x["part"])
z_ok = all(abs(x["pos"][2] - x["size"][2] / 2) < 0.05 for x in ps)
xs = [(x["pos"][0] - x["size"][0] / 2, x["pos"][0] + x["size"][0] / 2, x["pos"][1] - x["size"][1] / 2, x["pos"][1] + x["size"][1] / 2) for x in ps]
apart = all(a[1] <= b[0] or b[1] <= a[0] or a[3] <= b[2] or b[3] <= a[2] for i, a in enumerate(xs) for b in xs[i + 1:])
ok(z_ok and apart, "layout: parts on the ground, not overlapping")
ok(all(x["name"] for x in r["parts"]), "layout parts carry names")

tmp = os.path.join(WORK, "u3.3mf"); shutil.copy(f_stacked, tmp)
use(tmp, "lamp_stacked.3mf")
r = C.get(f"/api/products/{PID}/display?spec=").get_json()
ok(r["default_source"] == "file", f"parts overlap in the file -> file positions {r['default_source']}")

# ③ 几何自动组合：只返回建议，不保存
r = C.post(f"/api/products/{PID}/display/auto-assemble", json={"spec": ""})
j = r.get_json() if r.status_code == 200 else {}
if j.get("job"):
    import time
    for _ in range(100):
        jj = C.get(f"/api/bg/{j['job']}").get_json()
        if jj.get("status") in ("done", "error"):
            j = jj.get("result") or {}
            break
        time.sleep(0.2)
ok("parts" in j, "auto-assemble still available as suggestion")
ok(not C.get(f"/api/products/{PID}/display?spec=").get_json()["saved_pose"], "suggestion is not saved by itself")
# 人工保存过的不变
tmp = os.path.join(WORK, "u4.3mf"); bambu_3mf(tmp, FLAT, STACK)
use(tmp, "lamp_author.3mf")
r = C.get(f"/api/products/{PID}/display?spec=").get_json()
parts = [{"key": x["key"], "pos": [x["pos"][0] + 100, x["pos"][1], x["pos"][2]], "rot": x["rot"]} for x in r["parts"]]
rs = C.post(f"/api/products/{PID}/display", json={"spec": "", "items": r["items"], "parts": parts})
r2 = C.get(f"/api/products/{PID}/display?spec=").get_json()
ok(rs.status_code == 200 and r2["saved_pose"] and abs(r2["parts"][0]["pos"][0] - (r["parts"][0]["pos"][0] + 100)) < 0.05, "manually saved assembly wins over author assembly")

# 真 OrcaSlicer 打开带 assemble_item 的文件不报错
ORCA = slicer.find_orca(load_config())
if ORCA:
    wd = tempfile.mkdtemp(dir=WORK)
    bambu_3mf(os.path.join(wd, "in.3mf"), FLAT, STACK)
    rr = subprocess.run([ORCA, "--export-3mf", "out.3mf", "--outputdir", wd, "in.3mf"], cwd=wd, capture_output=True, timeout=300)
    ok(rr.returncode == 0 and os.path.exists(os.path.join(wd, "out.3mf")), f"real Orca opens 3MF with assemble_item rc={rr.returncode}")
shutil.rmtree(WORK, ignore_errors=True)
sys.exit(1 if E_ else 0)
