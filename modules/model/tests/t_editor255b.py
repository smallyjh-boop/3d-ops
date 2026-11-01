# v2.55 发版前检查修的打印方案问题（打印机安全）：
# 1. 槽 1 换了材料（PETG / TPU）的盘，不再用按产品材料选的旧耗材配置（PLA 的温度）切片
# 2. 两种材料一盘（PLA + PETG）：盘上设的温度只给和槽 1 同材料的槽，别的槽用自己配置里的温度
# 3. 按主模型缩放的规格：主模型改了每盘参数，以前的切片作废（旧数据不受影响）
# 4. 不认识的填充图案（3dhoneycomb、zig-zag…）原样保留，不偷偷改成 gyroid
# 5. 切割要「更换 3D 模型」权限；切开了但没保存的两半过一阵清掉
# 6. 切割高度没填 / 不是数字 / 超出零件 → 400 + 说明
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json
D = T + "/m_editor255b"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)


import numpy as np
import app as A
from core import db, store, modellib, mesh, recipes, slicer
from core import orca_profiles as op
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
p["material"] = "PLA"
p["variants"] = [{"opt1_zh": "白色", "opt2_zh": "", "sku": "3DP0002-WH", "grams": 30, "hours": 1.5},
                 {"opt1_zh": "白色", "opt2_zh": "大号", "sku": "3DP0002-WH-L", "grams": 60, "hours": 3}]
p.pop("print_plans", None)
p.pop("recipe", None)
store.save(p)
cube = os.path.join(D, "cube.stl"); mesh.write_stl(box(20, 20, 20), cube)
lib = modellib.upload(PID, [modellib.SavedFile(cube, "cube.stl")], "boss")
CUBE = lib[0]["id"]
p = store.load(PID)
p["model"] = dict(p.get("model") or {}, lib_id=CUBE, file=lib[0]["file"], orig_name="cube.stl")
store.save(p)


def item(uid, x, y, slot=1):
    return {"uid": uid, "id": CUBE, "part": None, "orient": "bottom", "slot": slot, "x": x, "y": y, "rot": 0}


def plate(pid_, mats, items, **kw):
    return dict({"id": pid_, "name": "", "printer": "Bambu Lab P1S", "layer_height": 0.2, "sets": 1, "manual": True,
                 "slots": [{"slot": i + 1, "material": m, "colour": ""} for i, m in enumerate(mats)], "items": items}, **kw)


# ---------- 4. 填充图案原样保留（迁移 + 保存 + 写回 recipe） ----------
p = store.load(PID)
p["recipe"] = dict(recipes.clean({"infill_pattern": "3dhoneycomb", "walls": 3}), updated_at=1)
store.save(p)
pl0 = pp.get_plan(store.load(PID), "")["plates"][0]
ok(pl0["params"]["infill_pattern"] == "3dhoneycomb", f"migration keeps 3dhoneycomb {pl0['params']['infill_pattern']}")
pp.save_plan(PID, "", {"plates": [pl0]}, "boss")
p = store.load(PID)
ok(p["print_plans"][""]["plates"][0]["params"]["infill_pattern"] == "3dhoneycomb" and p["recipe"]["infill_pattern"] == "3dhoneycomb",
   "save + mirror back to product recipe keeps 3dhoneycomb")
ok(pp.clean_params({"infill_pattern": "zig-zag"})["infill_pattern"] == "zig-zag", "zig-zag kept")
ok(pp.clean_params({"infill_pattern": "Weird Pattern!<x>"})["infill_pattern"] == "weirdpatternx", "unknown pattern: only invalid characters stripped")
ok(pp.clean_params({"infill_pattern": ""})["infill_pattern"] == "gyroid", "empty pattern -> gyroid")
ok("3dhoneycomb" in pp.PATTERNS and "zig-zag" in pp.PATTERNS and "crosszag" in pp.PATTERNS, "editor dropdown has the OrcaSlicer patterns")

# ---------- 1a. 槽 1 换材料 → 这一盘的耗材配置清掉（任何盘 / 规格） ----------
PLA_PROF = "Bambu PLA Basic @BBL X1C"
plan = {"plates": [plate("p1", ["PLA"], [item("a1", 60, 60)]), plate("p2", ["PLA"], [item("b1", 60, 60)])]}
for x in plan["plates"]:
    x["params"] = pp.clean_params(dict(pp.base_params(store.load(PID)), filament={"Bambu Lab P1S": PLA_PROF}))
pp.save_plan(PID, "", plan, "boss")
plan = pp.get_plan(store.load(PID), "")
ok(all(x["params"]["filament"] for x in plan["plates"]), "both plates keep the chosen PLA profile")
plan["plates"][1]["slots"][0]["material"] = "PETG"
pp.save_plan(PID, "", plan, "boss")
plan = pp.get_plan(store.load(PID), "")
ok(plan["plates"][1]["params"]["filament"] == {} and plan["plates"][0]["params"]["filament"], "plate 2 slot 1 -> PETG clears plate 2's profile only")
ok(store.load(PID)["material"] == "PLA", "product material unchanged (plate 1 still PLA)")
# 规格的方案也一样
sp = {"plates": [plate("p1", ["PLA"], [item("s1", 60, 60)], params=dict(plan["plates"][0]["params"]))]}
pp.save_plan(PID, "大号", sp, "boss")
sp = pp.get_plan(store.load(PID), "大号")
ok(sp["plates"][0]["params"]["filament"], "spec plan keeps profile while PLA")
sp["plates"][0]["slots"][0]["material"] = "TPU"
pp.save_plan(PID, "大号", sp, "boss")
ok(pp.get_plan(store.load(PID), "大号")["plates"][0]["params"]["filament"] == {}, "spec plan slot 1 -> TPU clears the profile")
# 迁移：旧方案（没有每盘参数）槽 1 不是产品材料的盘，不带按产品材料选的配置
p = store.load(PID)
p["recipe"]["filament"] = {"Bambu Lab P1S": PLA_PROF}
p["print_plans"]["大号"] = {"plates": [{k: v for k, v in plate("p1", ["PETG"], [item("s1", 60, 60)]).items()}], "schemes": {}}
store.save(p)
ok(pp.get_plan(store.load(PID), "大号")["plates"][0]["params"]["filament"] == {}, "migration: PETG plate does not inherit the PLA profile")
p = store.load(PID); p["print_plans"].pop("大号", None); store.save(p)

# ---------- 2 / 1b. 真的 OrcaSlicer：材料和配置一致、每槽自己的温度 ----------
CAP = []
_run = slicer.run_cli


def spy(exe, m_path, p_path, f_path, *a, **k):
    CAP.append([json.load(open(x, encoding="utf-8")) for x in f_path.split(";")])
    return _run(exe, m_path, p_path, f_path, *a, **k)


slicer.run_cli = spy


def t0(cfg_, key="nozzle_temperature"):
    v = cfg_.get(key)
    return int(float(v[0] if isinstance(v, list) else v))


cfg = load_config()
if slicer.find_orca(cfg):
    idx = op.build_index(slicer.find_orca(cfg))
    ok(op.filament_type(idx, PLA_PROF) == "PLA", f"profile material read from the OrcaSlicer index {op.filament_type(idx, PLA_PROF)}")
    ok(slicer.filament_mismatch(idx, PLA_PROF, "PETG") == "PLA" and not slicer.filament_mismatch(idx, PLA_PROF, "PLA+"),
       "mismatch check: PLA profile vs PETG plate")
    # 1b. 盘的槽 1 是 PETG，参数里还留着 PLA 的配置（例如老数据 / 复制过来的盘）→ 用 PETG 的配置切
    p = store.load(PID)
    pl2 = p["print_plans"][""]["plates"][1]
    pl2["params"]["filament"] = {"Bambu Lab P1S": PLA_PROF}
    pl2["params"]["nozzle_temp"] = 0
    store.save(p)
    CAP.clear()
    r = pp.slice_plate(PID, "", "p2", "白色", None, "boss")
    f1 = CAP[-1][0]
    ok(f1.get("filament_type") == ["PETG"] or f1.get("filament_type") == "PETG", f"stale PLA profile ignored, sliced with a PETG profile: {f1.get('name')} {f1.get('filament_type')}")
    ok(t0(f1) >= 230, f"PETG nozzle temperature used {t0(f1)}°C")
    ok(r.get("warnings") and "PETG" in r["warnings"][0]["zh"] and r["warnings"][0]["th"], f"slice result warns about the profile {r.get('warnings')}")
    ok(any("耗材配置和材料不一致" in (a.get("action") or "") for a in db.audit_list(20)), "audit log records the fallback")
    # 同材料（PLA 盘 + PLA 配置）照常用指定的配置
    CAP.clear()
    r1 = pp.slice_plate(PID, "", "p1", "白色", None, "boss")
    ok(CAP[-1][0].get("name") == PLA_PROF and not r1.get("warnings"), f"matching profile still used {CAP[-1][0].get('name')}")
    # 2. PLA + PETG 一盘，盘上设喷嘴 215°C：槽 1（PLA）215，槽 2（PETG）用 PETG 配置自己的温度
    plan = pp.get_plan(store.load(PID), "")
    two = plate("p3", ["PLA", "PETG"], [item("c1", 60, 60, 1), item("c2", 160, 60, 2)], params=dict(plan["plates"][0]["params"], nozzle_temp=215, bed_temp=60, filament={}))
    plan["plates"].append(two)
    plan["schemes"] = {"白色": {"1": "白色", "2": "黑色"}}
    pp.save_plan(PID, "", plan, "boss")
    CAP.clear()
    r2 = pp.slice_plate(PID, "", "p3", "白色", None, "boss")
    fl = CAP[-1]
    ok(len(fl) == 2, f"two per-slot filament configs written {len(fl)}")
    ok(t0(fl[0]) == 215 and t0(fl[1]) != 215 and t0(fl[1]) >= 230, f"per-slot nozzle temps differ: PLA {t0(fl[0])}°C, PETG {t0(fl[1])}°C")
    ok(t0(fl[0], "hot_plate_temp") == 60 and t0(fl[1], "hot_plate_temp") == t0(op.flatten(idx, fl[1]["name"], "filament"), "hot_plate_temp") != 60,
       f"bed temp override only on the PLA slot: {t0(fl[0], 'hot_plate_temp')} / {t0(fl[1], 'hot_plate_temp')}")
    ok(r2["sliced"]["filaments"][1]["grams"] > 0, f"2-material plate sliced {r2['sliced']['filaments']}")
    # 同材料两槽（PLA + PLA，两种颜色）：两槽都用盘上的温度
    plan = pp.get_plan(store.load(PID), "")
    plan["plates"][2]["slots"][1]["material"] = "PLA"
    pp.save_plan(PID, "", plan, "boss")
    CAP.clear()
    pp.slice_plate(PID, "", "p3", "白色", None, "boss")
    ok([t0(x) for x in CAP[-1]] == [215, 215], f"same-material slots both get the plate temperature {[t0(x) for x in CAP[-1]]}")
else:
    print("SKIP 没有 OrcaSlicer（材料 / 温度的真切片）")
slicer.run_cli = _run

# ---------- 3. 按主模型缩放的规格：主模型改了参数 → 以前的切片作废 ----------
p = store.load(PID)
p["print_plans"] = {"": {"plates": [plate("p1", ["PLA"], [item("a1", 60, 60)])], "schemes": {}}}   # 旧数据：没有每盘参数
p.pop("spec_recipes", None)
store.save(p)
pp.set_scale(PID, "大号", 150, "boss")
sc = pp.get_plan(store.load(PID), "大号")
old_sig = pp._sig0(sc["plates"][0])                       # 以前（v2.55 之前）存的签名就是这样
p = store.load(PID)
p["print_plans"]["大号"]["sliced_by"] = {"p1": {"grams": 9, "hours": 1, "sig": old_sig}}
store.save(p)
ok(pp.get_plan(store.load(PID), "大号")["plates"][0].get("sliced"), "old data: main plan without stored params keeps the scaled spec's slice result")
main = pp.get_plan(store.load(PID), "")
pp.save_plan(PID, "", main, "boss")                       # 保存后有每盘参数了
sc = pp.get_plan(store.load(PID), "大号")
p = store.load(PID)
p["print_plans"]["大号"]["sliced_by"] = {"p1": {"grams": 9, "hours": 1, "sig": pp._sig(sc["plates"][0])}}
store.save(p)
ok(pp.get_plan(store.load(PID), "大号")["plates"][0].get("sliced"), "scaled spec slice valid with the current params")
main = pp.get_plan(store.load(PID), "")
main["plates"][0]["params"]["walls"] = 6
main["plates"][0]["params"]["supports"] = "tree"
pp.save_plan(PID, "", main, "boss")
ok(not pp.get_plan(store.load(PID), "大号")["plates"][0].get("sliced"), "main plan params changed -> scaled spec's slice invalidated")
a_ = dict(main["plates"][0], params=dict(main["plates"][0]["params"]))
ok(pp._sig(a_) != pp._sig(dict(a_, params=dict(a_["params"], nozzle_temp=230))), "params digest in the plate signature")
ok(pp._sig({k: v for k, v in a_.items() if k != "params"}) == pp._sig0(a_), "no params -> signature unchanged from before")

# ---------- 5. 切割：权限 + 没保存的两半清掉 ----------
plan = C.get(f"/api/products/{PID}/print-plan").get_json()["plan"]
u0 = plan["plates"][0]["items"][0]["uid"]


def cut(client, z, code):
    rr = client.post(f"/api/products/{PID}/print-plan/op", json={"spec": "", "plan": plan, "op": {"op": "cut", "plate": "p1", "uids": [u0], "z": z}})
    if rr.status_code != code:
        print("   cut", z, rr.status_code, rr.get_json())
    return rr


n0 = len(store.load(PID)["model_lib"])
r = cut(PC, 8, 403)
ok(r.status_code == 403 and len(store.load(PID)["model_lib"]) == n0, "production staff (no models.change) cannot cut into the model library")
r = cut(PC, None, 403)
ok(r.status_code == 403, "permission checked before anything else")
# 6. 高度检查
for z, why in ((None, "空"), ("abc", "不是数字"), (-1, "负数"), (0, "零"), (20, "等于零件高度"), (35, "超过零件")):
    r = cut(C, z, 400)
    ok(r.status_code == 400 and "切割高度" in (r.get_json() or {}).get("error", ""), f"cut z {why} -> 400 with a clear message {r.get_json()}")
ok(len(store.load(PID)["model_lib"]) == n0, "refused cuts write nothing")
r = cut(C, 8, 200)
j = r.get_json()
ids = [c["id"] for c in j["cut"]]
lib_ = {e["id"]: e for e in store.load(PID)["model_lib"]}
ok(r.status_code == 200 and all(lib_[i].get("cut_pending") and lib_[i]["origin"] == "cut" for i in ids), "cut halves marked as pending (plan not saved)")
p = store.load(PID)
ok(pp.cleanup_cuts(PID, p) == [] and len(p["model_lib"]) == n0 + 2, "fresh unsaved halves are kept for a while (another window may still be editing)")
gone = pp.cleanup_cuts(PID, p, now=__import__("time").time() + pp.CUT_TTL + 1)
store.save(p)
ok(sorted(gone) == sorted(ids) and len(store.load(PID)["model_lib"]) == n0, "unsaved halves cleaned up after the TTL")
ok(not any(modellib.path_of(PID, lib_[i]) for i in ids), "their files moved out of the model folder")
modellib.library(PID)
ok(len(store.load(PID)["model_lib"]) == n0, "library sync does not bring them back")
r = cut(C, 8, 200)
j = r.get_json()
ids = [c["id"] for c in j["cut"]]
rs = C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": j["plan"]})
ok(rs.status_code == 200, "save the plan with the cut halves")
lib_ = {e["id"]: e for e in store.load(PID)["model_lib"]}
ok(all(i in lib_ and not lib_[i].get("cut_pending") for i in ids), "saved plan uses the halves -> no longer pending, kept")
p = store.load(PID)
ok(pp.cleanup_cuts(PID, p, now=__import__("time").time() + pp.CUT_TTL * 10) == [], "used halves never cleaned up")
pj = open(os.path.join(APP, "modules/model/ui/plan.js"), encoding="utf-8").read()
ok("r.warnings" in pj, "editor shows the slice warnings")
sys.exit(1 if E_ else 0)
