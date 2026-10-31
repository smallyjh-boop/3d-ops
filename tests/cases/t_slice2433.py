# v2.43.3：OrcaSlicer 返回 -50（盘上没有能切的零件：零件摆在盘外 / 分散在几个盘上）→ 拆成每个零件一个 STL 自动摆盘重试；
# 返回码说人话（Windows 的 4294967246、Linux 的 206 都认成 -50）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, json, stat
D = T + "/slice2433"; shutil.rmtree(D, ignore_errors=True); os.makedirs(D)
os.environ["LH_DATA_DIR"] = T + "/v13"; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import numpy as np
from core import slicer, modellib

ok(slicer.rc_signed(4294967246) == -50 and slicer.rc_signed(206) == -50 and slicer.rc_signed(0) == 0 and slicer.rc_signed(137) == 137, "return codes")

# 假的 OrcaSlicer：一个 3MF → 返回 -50（Linux 上是 206）；几个 STL 一起传 → 切成功
fake = os.path.join(D, "orca.py")
log = os.path.join(D, "calls.json")
open(fake, "w").write(f"""#!{sys.executable}
import sys, os, json
a = sys.argv[1:]
out = a[a.index("--outputdir") + 1]
models = [x for x in a if x.lower().endswith((".3mf", ".stl")) and x != "result.gcode.3mf"]
calls = json.load(open({log!r})) if os.path.exists({log!r}) else []
calls.append({{"models": [os.path.basename(m) for m in models], "ensure": "--ensure-on-bed" in a}})
json.dump(calls, open({log!r}, "w"))
if len(models) > 1 and all(m.endswith(".stl") for m in models):
    os.makedirs(out, exist_ok=True)
    open(os.path.join(out, "plate_1.gcode"), "w").write("; total filament weight [g] : 12.5\\n; total estimated time: 1h 30m 0s\\n")
    sys.exit(0)
sys.exit(206)
""")
os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
model = os.path.join(D, "clema+perdea+inima+cu+funda.3mf")
shutil.copyfile(os.path.join(APP, "tests", "fixtures", "bambu_project.3mf"), model)
tri = np.array([[[0, 0, 0], [10, 0, 0], [0, 10, 0]], [[0, 0, 0], [0, 10, 0], [0, 0, 10]]], dtype=np.float64)
modellib.load_parts = lambda path: [("clip", tri + 500), ("heart", tri - 400), ("bow", tri + [0, 900, 0])]       # 零件摆在盘外很远
for f in ("m.json", "p.json", "f.json"):
    open(os.path.join(D, f), "w").write("{}")
params = {"orient": True, "copies": 1, "timeout": 60, "material": "PLA", "used": ""}
r = slicer.run_cli(fake, *(os.path.join(D, f) for f in ("m.json", "p.json", "f.json")), model, os.path.join(D, "work"), params,
                   model_name=os.path.basename(model))
calls = json.load(open(log))
ok(r["grams"] == 12.5 and abs(r["hours"] - 1.5) < 0.01, f"sliced after retry {r.get('grams')} {r.get('hours')}")
ok(len(calls) == 2 and calls[1]["models"] == ["part_01.stl", "part_02.stl", "part_03.stl"] and not calls[0]["ensure"] and calls[1]["ensure"], f"parts retried (ensure-on-bed only on retry) {calls}")
ok("拆开" in r.get("log", "") and "盘上没有能切的零件" in r.get("log", ""), "log explains the retry")
# 拆开的零件挪到了原点附近
from core import mesh
pt = mesh._load_stl(open(os.path.join(D, "work", "part_01.stl"), "rb").read())
ok(abs(pt.reshape(-1, 3)[:, :2].mean()) < 20 and pt.reshape(-1, 3)[:, 2].min() == 0, "parts moved to origin")
# 都不行：报错说人话
os.remove(log)
src = open(fake).read().replace("if len(models) > 1", "if False")
open(fake, "w").write(src)
try:
    slicer.run_cli(fake, *(os.path.join(D, f) for f in ("m.json", "p.json", "f.json")), model, os.path.join(D, "work2"), params,
                   model_name=os.path.basename(model))
    ok(False, "should fail")
except slicer.SliceError as e:
    ok("返回码 -50：盘上没有能切的零件" in str(e) and "单位" in str(e), f"clear error {str(e)[:120]}")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
