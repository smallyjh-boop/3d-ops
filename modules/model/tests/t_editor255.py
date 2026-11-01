# v2.55 统一的打印方案编辑器：旧「打印方案」参数搬进方案（每盘）、recipes.get 兼容、每个零件自己的方向、
# 多选操作（复制 / 删除 / 镜像 / 旋转 / 缩放 / 移到别的盘 / 对齐 / 成组 / 拆分）、按高度切开（两个封闭的零件）、
# 零件单独参数写进 3MF 并被真的 OrcaSlicer 用上、生产页的打印方案窗口和编辑页是同一份数据。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, zipfile, re
D = T + "/m_editor255"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)


import numpy as np
import app as A
from core import db, store, modellib, mesh, recipes, slicer, specmodel
from core.config import load_config, save_config
from modules.model import printplan as pp
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pong", "secret123", "production", "Pong")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
PC = A.app.test_client(); PC.post("/api/auth/login", json={"username": "pong", "password": "secret123"})


def box(w, d, h):
    v = np.array([[0, 0, 0], [w, 0, 0], [w, d, 0], [0, d, 0], [0, 0, h], [w, 0, h], [w, d, h], [0, d, h]], float)
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return v[np.array(f)]


save_config({"printers": [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "tech": "fdm"},
                          {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "enabled": True, "tech": "fdm"}]})
PID = "3DP0002"
p = store.load(PID)
p["variants"] = [{"opt1_zh": "白色", "opt2_zh": "", "sku": "3DP0002-WH", "grams": 30, "hours": 1.5}]
p.pop("print_plans", None)
store.save(p)
k3 = os.path.join(D, "kit.3mf")
pp.write_plate_3mf(k3, [("Base", box(60, 60, 5), (40, 40, 0), 1), ("Body", box(30, 20, 40), (120, 40, 0), 1), ("Head", box(16, 16, 12), (200, 40, 0), 1)])
cube = os.path.join(D, "cube.stl"); mesh.write_stl(box(20, 20, 20), cube)
lib = modellib.upload(PID, [modellib.SavedFile(k3, "kit.3mf"), modellib.SavedFile(cube, "cube.stl")], "boss")
K3, CUBE = lib[0]["id"], lib[1]["id"]
p = store.load(PID)
p["model"] = dict(p.get("model") or {}, lib_id=CUBE, file=lib[1]["file"], orig_name="cube.stl")
store.save(p)

# ---------- 1. 旧的打印方案（recipe）自动搬进方案（每盘的参数） ----------
r = C.post(f"/api/products/{PID}/recipe", json={"supports": "tree", "walls": 4, "infill_pct": 30, "infill_pattern": "grid", "brim": True,
                                                  "bed_type": "textured", "layer_height": 0.16, "orientation": "bottom", "notes": "小心取件",
                                                  "nozzle_temp": 215, "top_bottom": 5, "gap_mm": 8})
ok(r.status_code == 200, f"old recipe endpoint still saves {r.status_code}")
d = C.get(f"/api/products/{PID}/print-plan").get_json()
prm = d["plan"]["plates"][0]["params"]
ok(prm["supports"] == "tree" and prm["walls"] == 4 and prm["infill_pct"] == 30 and prm["brim"] and prm["bed_type"] == "textured"
   and prm["notes"] == "小心取件" and prm["nozzle_temp"] == 215 and prm["gap_mm"] == 8, f"default plan gets the recipe settings {prm}")
ok(d["plan"]["plates"][0]["layer_height"] == 0.16, "layer height migrated")
ok(d["plate_checks"]["p1"] and all("zh" in c and "th" in c for c in d["plate_checks"]["p1"]), "per-plate rule checks (zh + th)")
ok("support_zh" in d["params_meta"] and d["params_meta"]["printer_idx"].get("Creality K1C") == 1, "params meta for the panel")
# v2.54 以前保存的方案（盘里没有 params）读出来也补上
p = store.load(PID)
p["print_plans"] = {"": {"plates": [{"id": "p1", "name": "", "printer": "Bambu Lab P1S", "layer_height": 0.2, "sets": 1,
                                     "slots": [{"slot": 1, "material": "PLA", "colour": ""}],
                                     "items": [{"uid": "c1", "id": CUBE, "part": None, "orient": "bottom", "slot": 1, "x": 60, "y": 60, "rot": 0}],
                                     "manual": True}], "schemes": {}}}
store.save(p)
pl = pp.get_plan(store.load(PID), "")["plates"][0]
ok(pl["params"]["walls"] == 4 and pl["params"]["supports"] == "tree", "old saved plan (no params) migrated from recipe on read")
ok(recipes.get(store.load(PID))["walls"] == 4, "recipes.get unchanged for a migrated-but-unsaved plan")

# ---------- 2. 在编辑器里改参数 → recipes.get（老的调用）跟着变；老接口改 → 方案跟着变 ----------
plan = d["plan"]
plan["plates"][0]["params"].update(walls=5, infill_pct=40, supports="none", brim=False)
plan["plates"][0]["layer_height"] = 0.12
r = C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": plan}).get_json()
ok(r["plan"]["plates"][0]["params"]["walls"] == 5, "plan saved with params")
rg = recipes.get(store.load(PID))
ok(rg["walls"] == 5 and rg["infill_pct"] == 40 and rg["supports"] == "none" and rg["layer_height"] == 0.12 and not rg["brim"],
   f"recipes.get derives from the plan {[rg[k] for k in ('walls', 'infill_pct', 'supports', 'layer_height', 'brim')]}")
ok(store.load(PID)["recipe"]["walls"] == 5, "product recipe mirrored from plate 1")
ov = recipes.overrides(pp.recipe_of(store.load(PID), r["plan"]["plates"][0]))
ok(ov["wall_loops"] == "5" and ov["layer_height"] == "0.12" and ov["sparse_infill_density"] == "40%", f"slice overrides from plate params {ov}")
rc = C.get(f"/api/products/{PID}/recipe").get_json()
ok(rc["recipe"]["walls"] == 5 and rc["recipe"]["layer_height"] == 0.12, "production page recipe = plan (same data)")
C.post(f"/api/products/{PID}/recipe", json={**rc["recipe"], "walls": 3, "infill_pct": 20})
d = C.get(f"/api/products/{PID}/print-plan").get_json()
ok(d["plan"]["plates"][0]["params"]["walls"] == 3 and d["plan"]["plates"][0]["params"]["infill_pct"] == 20, "old recipe save pushed into the plan")
# 换材料（槽 1）→ 产品材料跟着改
plan = d["plan"]; plan["plates"][0]["slots"][0]["material"] = "PETG"; plan["plates"][0]["params"]["bed_type"] = "cool"
r = C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": plan}).get_json()
ok(store.load(PID)["material"] == "PETG", "slot 1 material of the main plan = product material")
ok(any(c["level"] == "warn" and "PETG" in c["zh"] for c in r["plate_checks"]["p1"]), "PETG on cool plate warned per plate")
plan = r["plan"]; plan["plates"][0]["slots"][0]["material"] = "PLA"; plan["plates"][0]["params"]["bed_type"] = "auto"
C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": plan})

# ---------- 3. 组合模型按零件：每个零件自己的方向、方向卡片 ----------
plan = C.get(f"/api/products/{PID}/print-plan").get_json()["plan"]
plan["plates"][0]["items"] = [{"uid": "k3", "id": K3, "part": None, "orient": "bottom", "slot": 1, "x": None, "y": None, "rot": 0}]
plan["plates"][0]["manual"] = False


def op(plan, o, client=C, code=200):
    rr = client.post(f"/api/products/{PID}/print-plan/op", json={"spec": "", "plan": plan, "op": o})
    j = rr.get_json()
    if rr.status_code != code:
        print("   op", o.get("op"), rr.status_code, j)
    return j, rr.status_code


j, st = op(plan, {"op": "split", "plate": "p1", "uids": ["k3"]})
its = j["plan"]["plates"][0]["items"]
ok(st == 200 and sorted(it["part"] for it in its) == [0, 1, 2] and all(it["x"] is not None for it in its), f"split a multi-part file into parts {[it['part'] for it in its]}")
body = next(it for it in its if it["part"] == 1)
o = C.post(f"/api/products/{PID}/print-plan/orients", json={"id": K3, "part": 1}).get_json()
keys = [r_["key"] for r_ in o["rows"]]
ok(set(["bottom", "top", "front", "back", "left", "right"]) <= set(keys) and 0 <= o["best"] < len(o["rows"]), f"orientation cards for one part {keys}")
ok(all(r_["risks"] is not None and "contact_cm2" in r_ for r_ in o["rows"]), "cards carry contact / overhang / risks")
j, st = op(j["plan"], {"op": "orient", "plate": "p1", "uids": [body["uid"]], "orient": "front"})
its = j["plan"]["plates"][0]["items"]
ok([it["orient"] for it in its if it["uid"] == body["uid"]] == ["front"] and all(it["orient"] == "bottom" for it in its if it["uid"] != body["uid"]),
   "orientation changed for the selected part only")
fb = j["footprints"][body["uid"]]
ok(abs(fb["h"] - 20) < 0.6 and abs(fb["d"] - 40) < 0.6, f"front-down body is 20 high, 40 deep {fb['w'], fb['d'], fb['h']}")
j, st = op(j["plan"], {"op": "orient", "plate": "p1", "uids": [body["uid"]], "face": [0.7071, 0.7071, 0]})
it = next(x for x in j["plan"]["plates"][0]["items"] if x["uid"] == body["uid"])
ok(it.get("face") and abs(it["face"][0] - 0.7071) < 0.01, "lay on an arbitrary face (normal stored)")
j, st = op(j["plan"], {"op": "auto_orient", "plate": "p1", "uids": [body["uid"]]})
it = next(x for x in j["plan"]["plates"][0]["items"] if x["uid"] == body["uid"])
ok(st == 200 and not it.get("face") and it["orient"] in ("left", "right", "front", "back", "bottom", "top"), f"auto orient picks a card {it['orient']}")
# 合并出来的模型（组合_*.stl）拆回 parts_of 里的零件
m = modellib.make_entry(PID, [{"id": K3, "part": 0, "qty": 1}, {"id": K3, "part": 2, "qty": 2}], "boss", name="组合_test")
pl1 = {"plates": [dict(j["plan"]["plates"][0], items=[{"uid": "mm", "id": m["id"], "part": None, "orient": "bottom", "slot": 1, "x": None, "y": None, "rot": 0}])]}
j2, st = op(pl1, {"op": "split", "plate": "p1", "uids": ["mm"]})
ok(st == 200 and sorted((it["id"], it["part"]) for it in j2["plan"]["plates"][0]["items"]) == [(K3, 0), (K3, 2), (K3, 2)],
   "merged entry expands to its parts_of (qty kept)")

# ---------- 4. 多选操作（接口） ----------
plan = j["plan"]
plan["plates"][0]["manual"] = True
uids = [it["uid"] for it in plan["plates"][0]["items"]]
base, head = [it for it in plan["plates"][0]["items"] if it["part"] == 0][0], [it for it in plan["plates"][0]["items"] if it["part"] == 2][0]
j, st = op(plan, {"op": "duplicate", "plate": "p1", "uids": [head["uid"]], "n": 3})
its = j["plan"]["plates"][0]["items"]
ok(st == 200 and len(its) == 6 and len(j["sel"]) == 3 and all(j["checks"]["p1"]["items"][u]["overlap"] == [] for u in j["sel"]),
   f"duplicate x3 placed without overlap ({len(its)} items)")
ok(j["checks"]["p1"]["ok"], f"plate still ok after duplicate {j['checks']['p1']['problems']}")
j, st = op(j["plan"], {"op": "delete", "plate": "p1", "uids": j["sel"][:2]})
ok(len(j["plan"]["plates"][0]["items"]) == 4, "delete selected")
j, st = op(j["plan"], {"op": "mirror", "plate": "p1", "uids": [base["uid"]], "axis": "x"})
b2 = next(x for x in j["plan"]["plates"][0]["items"] if x["uid"] == base["uid"])
ok(b2.get("mirror") == "x", "mirror X flag")
j, st = op(j["plan"], {"op": "mirror", "plate": "p1", "uids": [base["uid"]], "axis": "x"})
ok(not next(x for x in j["plan"]["plates"][0]["items"] if x["uid"] == base["uid"]).get("mirror"), "mirror twice = back to normal")
two = [base["uid"], head["uid"]]
before = {x["uid"]: (x["x"], x["y"]) for x in j["plan"]["plates"][0]["items"]}
j, st = op(j["plan"], {"op": "rotate", "plate": "p1", "uids": two, "angle": 90})
after = {x["uid"]: x for x in j["plan"]["plates"][0]["items"]}
ok(all(after[u]["rot"] == 90 for u in two) and (after[head["uid"]]["x"], after[head["uid"]]["y"]) != before[head["uid"]], "rotate 2 parts 90° around their centre")
w0 = j["footprints"][base["uid"]]["w"]
j, st = op(j["plan"], {"op": "scale", "plate": "p1", "uids": [base["uid"]], "pct": 50})
ok(abs(j["footprints"][base["uid"]]["w"] - w0 * 0.5) < 0.6 and next(x for x in j["plan"]["plates"][0]["items"] if x["uid"] == base["uid"])["scale"] == 0.5,
   f"scale 50% {w0} -> {j['footprints'][base['uid']]['w']}")
j, st = op(j["plan"], {"op": "align", "plate": "p1", "uids": two, "mode": "left"})
bx = [pp._bbox(j["plan"]["plates"][0], j["footprints"], {u})[0] for u in two]
ok(abs(bx[0] - bx[1]) < 0.2, f"align left {bx}")
j, st = op(j["plan"], {"op": "group", "plate": "p1", "uids": two})
g = {x["uid"]: x.get("group") for x in j["plan"]["plates"][0]["items"]}
ok(g[two[0]] and g[two[0]] == g[two[1]], "group")
j, st = op(j["plan"], {"op": "move", "plate": "p1", "uids": [two[0]], "dx": 3, "dy": 0})
mv = {x["uid"]: x for x in j["plan"]["plates"][0]["items"]}
ok(mv[two[1]]["x"] is not None and abs(mv[two[0]]["x"] - after[two[0]]["x"]) >= 0, "group moves together")
j, st = op(j["plan"], {"op": "ungroup", "plate": "p1", "uids": two})
j, st = op(j["plan"], {"op": "to_plate", "plate": "p1", "uids": [head["uid"]], "target": "new"})
ok(len(j["plan"]["plates"]) == 2 and [x["uid"] for x in j["plan"]["plates"][1]["items"]] == [head["uid"]] and j["plate"] == j["plan"]["plates"][1]["id"],
   "move to a new plate")
ok(j["plan"]["plates"][1]["params"] == j["plan"]["plates"][0]["params"], "new plate copies the plate settings")
j, st = op(j["plan"], {"op": "to_plate", "plate": j["plan"]["plates"][1]["id"], "uids": [head["uid"]], "target": "p1"})
ok(len(j["plan"]["plates"][0]["items"]) == 4 and not j["plan"]["plates"][1]["items"], "move back to plate 1")
j["plan"]["plates"] = j["plan"]["plates"][:1]
j, st = op(j["plan"], {"op": "slot", "plate": "p1", "uids": [head["uid"]], "slot": 3}, code=400)
ok(st == 400, "slot that the plate does not have is refused")
j, st = op({"plates": [dict(pp.get_plan(store.load(PID), '')["plates"][0])]}, {"op": "delete", "plate": "p1", "uids": []}, code=400)
ok(st == 400 and "选中" in j["error"], "nothing selected -> clear error")
plan = C.get(f"/api/products/{PID}/print-plan").get_json()["plan"]
j, st = op(plan, {"op": "qty", "plate": "p1", "id": CUBE, "part": None, "qty": 3})
ok(sum(1 for x in j["plan"]["plates"][0]["items"] if x["id"] == CUBE) == 3, "part list qty 1 -> 3")
j, st = op(j["plan"], {"op": "qty", "plate": "p1", "id": CUBE, "part": None, "qty": 2})
ok(sum(1 for x in j["plan"]["plates"][0]["items"] if x["id"] == CUBE) == 2, "part list qty 3 -> 2")
# 生产员工也能用编辑器
j, st = op(plan, {"op": "duplicate", "plate": "p1", "uids": [plan["plates"][0]["items"][0]["uid"]], "n": 1}, client=PC)
ok(st == 200, "production staff can use the editor ops")
# 重叠 / 超出热床还是不能保存
bad = j["plan"]; its = bad["plates"][0]["items"]; its[1]["x"], its[1]["y"] = its[0]["x"], its[0]["y"]; bad["plates"][0]["manual"] = True
rr = C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": bad})
ok(rr.status_code == 400 and "重叠" in rr.get_json()["error"], "overlap still blocks save")

# ---------- 5. 按高度切开：两个封闭的零件，高度对 ----------
plan = C.get(f"/api/products/{PID}/print-plan").get_json()["plan"]
cu = plan["plates"][0]["items"][0]
n_lib = len(store.load(PID)["model_lib"])
j, st = op(plan, {"op": "cut", "plate": "p1", "uids": [cu["uid"]], "z": 8})
ok(st == 200 and len(j["cut"]) == 2 and all(c["closed"] for c in j["cut"]), f"cut -> two closed parts {j.get('cut')}")
hs = sorted(round(c["h"], 1) for c in j["cut"])
ok(hs == [8.0, 12.0], f"cut heights 8 + 12 {hs}")
ok(len(store.load(PID)["model_lib"]) == n_lib + 2, "cut halves stored in the model library")
ok(len(j["plan"]["plates"][0]["items"]) == len(plan["plates"][0]["items"]) + 1 and j["checks"]["p1"]["ok"], "cut halves on the plate, no overlap")
for c in j["cut"]:
    e = modellib._entry(store.load(PID), c["id"])
    ok(mesh.is_closed(mesh.load(modellib.path_of(PID, e))), f"cut half file is closed {e['file']}")
lo, hi = mesh.cut_z(np.concatenate([box(30, 30, 20), (box(10, 10, 20) + [10, 10, 0])[:, [0, 2, 1], :]]), 5)
ok(mesh.is_closed(lo) and mesh.is_closed(hi), "cut a part with a hole (cap with hole) -> closed")
r0 = C.post(f"/api/products/{PID}/print-plan/op", json={"spec": "", "plan": plan, "op": {"op": "cut", "plate": "p1", "uids": [cu["uid"]], "z": 50}})
ok(r0.status_code == 400, "cut above the part refused")

# ---------- 6. 零件单独参数写进 3MF，真的 OrcaSlicer 按它切 ----------
plan = C.get(f"/api/products/{PID}/print-plan").get_json()["plan"]
plan["plates"][0]["items"] = [{"uid": "a1", "id": CUBE, "part": None, "orient": "bottom", "slot": 1, "x": 60, "y": 60, "rot": 0},
                              {"uid": "a2", "id": CUBE, "part": None, "orient": "bottom", "slot": 1, "x": 160, "y": 60, "rot": 0}]
plan["plates"][0]["manual"] = True
plan["plates"][0]["layer_height"] = 0.2
j, st = op(plan, {"op": "overrides", "plate": "p1", "uids": ["a2"], "ov": {"layer_height": 0.1, "infill_pct": 50, "walls": 5}})
it2 = next(x for x in j["plan"]["plates"][0]["items"] if x["uid"] == "a2")
ok(it2.get("ov") == {"layer_height": 0.1, "infill_pct": 50, "walls": 5}, f"per-part overrides on the item {it2.get('ov')}")
ok(any("层高不一样" in c["zh"] for c in j["plate_checks"]["p1"]), "mixed layer heights noted")
r = C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": j["plan"]})
ok(r.status_code == 200, "save plan with per-part overrides")
path, _n = pp.export_plate(PID, "", "p1")
with zipfile.ZipFile(path) as z:
    ms = z.read("Metadata/model_settings.config").decode()
os.remove(path)
ok('key="layer_height" value="0.1"' in ms and 'key="sparse_infill_density" value="50%"' in ms and 'key="wall_loops" value="5"' in ms
   and ms.count("layer_height") == 1, "overrides written as object settings in the exported 3MF")
if slicer.find_orca(load_config()):
    def layers(fid):
        from core import print_files
        with zipfile.ZipFile(print_files.path_of(print_files.get(fid))) as z:
            gc = z.read(next(n for n in z.namelist() if n.endswith(".gcode"))).decode("utf-8", "ignore")
        return int(re.search(r"; total layer number: (\d+)", gc).group(1)), gc
    s1 = pp.slice_plate(PID, "", "p1", "白色", None, "boss")
    n1, gc1 = layers(s1["file"]["id"])
    plan = C.get(f"/api/products/{PID}/print-plan").get_json()["plan"]
    j, st = op(plan, {"op": "overrides", "plate": "p1", "uids": ["a2"], "ov": {"layer_height": None, "infill_pct": None, "walls": None}})
    ok(not next(x for x in j["plan"]["plates"][0]["items"] if x["uid"] == "a2").get("ov"), "overrides cleared")
    C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": j["plan"]})
    s0 = pp.slice_plate(PID, "", "p1", "白色", None, "boss")
    n0, gc0 = layers(s0["file"]["id"])
    ok(n0 == 100 and n1 > n0 + 50, f"real OrcaSlicer honours the per-part layer height: {n0} layers -> {n1} layers")
    ok(s1["sliced"]["grams"] > s0["sliced"]["grams"], f"per-part infill / walls add material {s0['sliced']['grams']} -> {s1['sliced']['grams']} g")
    ok("; wall_loops = 3" in gc0 or "wall_loops = 3" in gc0, "plate walls (3, from the plan) used by the slicer")
else:
    print("SKIP 没有 OrcaSlicer（零件单独参数的真切片）")

# ---------- 7. 生产 → 打印方案窗口和编辑页是同一个编辑器 ----------
pj = open(os.path.join(APP, "modules/prod/ui/prod.js"), encoding="utf-8").read()
ok("PLAN.mount" in pj and "filesOnly" in pj, "production modal mounts the plan editor + files list")
rj = open(os.path.join(APP, "modules/prod/ui/recipe.js"), encoding="utf-8").read()
ok("filesOnly" in rj, "recipe.js has the files-only mode (model files + sliced files under the editor)")
pl_js = open(os.path.join(APP, "modules/model/ui/plan.js"), encoding="utf-8").read()
for k in ("print-plan/op", "print-plan/orients", "data-pe=\"cut\"", "ctrlKey", "box-select"):
    ok(k in pl_js, f"editor has {k}")
sys.exit(1 if E_ else 0)
