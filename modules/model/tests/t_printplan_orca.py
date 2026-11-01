# v2.52：打印方案「按这一盘切片」用真的 OrcaSlicer 跑一遍（多色：两个 AMS 槽、不自动摆、带擦料塔）。
# 这台机器没装 OrcaSlicer 时跳过（只打印 SKIP，不算失败）。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, zipfile, re
D = T + "/m_plan_orca"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import numpy as np
import app as A  # noqa: F401
from core import store, modellib, slicer, print_files
from core.config import load_config, save_config
from modules.model import printplan as pp

if not slicer.find_orca(load_config()):
    print("SKIP 没有 OrcaSlicer")
    sys.exit(0)

def box(w, d, h):
    v = np.array([[0, 0, 0], [w, 0, 0], [w, d, 0], [0, d, 0], [0, 0, h], [w, 0, h], [w, d, h], [0, d, h]], float)
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return v[np.array(f)]

save_config({"printers": [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "tech": "fdm"}]})
PID = "3DP0002"
p = store.load(PID)
p["variants"] = [{"opt1_zh": "白色", "opt2_zh": "", "sku": "3DP0002-WH", "grams": 30, "hours": 1.5}]
store.save(p)
k = os.path.join(D, "kit.3mf")
pp.write_plate_3mf(k, [("Base", box(40, 40, 4), (40, 40, 0), 1), ("Body", box(20, 20, 20), (120, 40, 0), 1), ("Head", box(16, 16, 12), (200, 40, 0), 2)],
                   [{"hex": "#FFFFFF", "material": "PLA"}, {"hex": "#000000", "material": "PLA"}])
K3 = modellib.upload(PID, [modellib.SavedFile(k, "kit.3mf")], "boss")[0]["id"]

plate = {"id": "p1", "printer": "Bambu Lab P1S", "layer_height": 0.2, "sets": 1, "manual": True,
         "slots": [{"slot": 1, "material": "PLA", "colour": ""}, {"slot": 2, "material": "PLA", "colour": "黑色"}],
         "items": [{"uid": "a1", "id": K3, "part": 0, "orient": "bottom", "slot": 1, "x": 60, "y": 60, "rot": 0},
                   {"uid": "a2", "id": K3, "part": 1, "orient": "bottom", "slot": 1, "x": 160, "y": 70, "rot": 30},
                   {"uid": "a3", "id": K3, "part": 2, "orient": "bottom", "slot": 2, "x": 110, "y": 180, "rot": 0}]}
pp.save_plan(PID, "", {"plates": [plate]}, "boss")

r = pp.slice_plate(PID, "", "p1", "白色", None, "boss")
s = r["sliced"]
g = {f["slot"]: f["grams"] for f in s["filaments"]}
ok(len(g) == 2 and g[1] > 0 and g[2] > 0, f"real slice: grams per AMS slot {g}")
ok(g[1] > g[2], f"white (base + body) uses more than black (head) {g}")
ok(s["changes"] >= 10 and s["purge_g"] > 1, f"colour changes {s['changes']}, purge {s['purge_g']} g (counted from the G-code)")
ok(g[2] < 5, f"slot grams are net of purge (black head 16x16x12 mm ≈ 1–3 g) {g}")
ok((s["hours"] or 0) > 0, f"time {s['hours']} h")
path = print_files.path_of(print_files.get(r["file"]["id"]))
ok(path and os.path.isfile(path) and zipfile.is_zipfile(path), f"sliced .gcode.3mf stored {path}")
# 摆好的位置保留（没有被自动重新排列）：G-code 里第一层的 X/Y 范围应该覆盖到三个零件的位置
with zipfile.ZipFile(path) as z:
    gname = next(n for n in z.namelist() if n.endswith(".gcode"))
    gc = z.read(gname).decode("utf-8", "ignore")
xs, ys = [], []
for m in re.finditer(r"^G1 [^\n]*X([\d.]+) Y([\d.]+)[^\n]*E[\d.]", gc, re.M):
    xs.append(float(m.group(1))); ys.append(float(m.group(2)))
ok(xs and min(xs) < 50 and min(ys) < 50 and max(xs) > 160 and max(ys) > 175, f"positions kept: X {min(xs):.0f}–{max(xs):.0f}, Y {min(ys):.0f}–{max(ys):.0f}")
ok("T1" in gc or "M620 S1" in gc, "G-code switches to filament 2")
u = pp.usage(store.load(PID), "", "白色")
ok(not u["est"], "usage now from slicer (not 估)")
sys.exit(1 if E_ else 0)
