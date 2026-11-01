# v2.53：展示和打印分开（合并成一套的主模型不再影响展示，自动拆回零件）、每个规格各有展示 / 打印方案、从规格复制、按主模型缩放、
# 自动选零件、几何自动组合（盒子 + 盖子、身体 + 带插销的头）、爆炸图、从组装生成打印方案、③ 概览 / 缩略图、一键全部切片（真的 OrcaSlicer）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import io, json, os, sys, shutil, sqlite3
D = T + "/m_disp253"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import numpy as np
import app as A
from core import db, store, modellib, mesh, slicer, specmodel
from core.config import load_config, save_config
from modules.model import printplan as pp, assembly as asm, mating
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pong", "secret123", "production", "Pong")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
PC = A.app.test_client(); PC.post("/api/auth/login", json={"username": "pong", "password": "secret123"})
save_config({"printers": [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "tech": "fdm"}], "ai_api_key": ""})


# ---------- 合成零件 ----------
def box(x0, y0, z0, x1, y1, z1):
    v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return v[np.array(f)]
cat = np.concatenate
def open_box(w=60, d=40, h=30, t=3):            # 开口朝上的盒子（壁厚 3）
    return cat([box(0, 0, 0, w, d, t), box(0, 0, 0, t, d, h), box(w - t, 0, 0, w, d, h), box(t, 0, 0, w - t, t, h), box(t, d - t, 0, w - t, d, h)])
def lid(w=60, d=40, t=3, lip=5, wall=3, clr=0.2, wt=2):     # 盖子按打印的样子平放：板在下、内沿朝上（装上去要翻过来）
    i = wall + clr
    return cat([box(0, 0, 0, w, d, t), box(i, i, t, w - i, i + wt, t + lip), box(i, d - i - wt, t, w - i, d - i, t + lip),
                box(i, i, t, i + wt, d - i, t + lip), box(w - i - wt, i, t, w - i, d - i, t + lip)])
def body_with_hole(s=40, h=40, hole=10, depth=10):
    a = (s - hole) / 2
    return cat([box(0, 0, 0, s, s, h - depth), box(0, 0, h - depth, a, s, h), box(s - a, 0, h - depth, s, s, h),
                box(a, 0, h - depth, s - a, a, h), box(a, s - a, h - depth, s - a, s, h)])
def head_with_peg(s=30, h=20, peg=8, pl=8):     # 头按打印的样子：插销朝上
    a = (s - peg) / 2
    return cat([box(0, 0, 0, s, s, h), box(a, a, h, a + peg, a + peg, h + pl)])
def shift(t, x=0, y=0, z=0):
    return t + np.array([x, y, z], float)

# ---------- 1. 几何自动组合（纯算法） ----------
for R in mating.ORIENTS:
    assert np.allclose(mating.rot_matrix(*mating.euler_of(R)), R, atol=1e-6)
ok(len(mating.ORIENTS) == 24, "24 orientations, euler round trip")
r = mating.auto_assemble([{"key": "lid", "name": "lid", "tris": shift(lid(), 0, 100)}, {"key": "box", "name": "box", "tris": shift(open_box(), 100)}])
pb, pl_ = r["poses"]["box"], r["poses"]["lid"]
R = mating.rot_matrix(*pl_["rot"])
ok(r["base"] == "box" and pb["rot"] == [0.0, 0.0, 0.0], f"box is the base {r['base']}")
ok(R[2, 2] < -0.99, f"lid flipped (lip down) {pl_['rot']}")
ok(abs(pl_["pos"][0] - pb["pos"][0]) < 0.6 and abs(pl_["pos"][1] - pb["pos"][1]) < 0.6, f"lid centred on the box {pl_['pos']}")
ok(abs(pl_["pos"][2] - 29) < 0.6, f"lid plate on the rim, lip 5 mm inside (centre z 29) {pl_['pos']}")
ok(r["confidence"] >= 0.8 and r["steps"][0]["insert_mm"] > 4, f"high confidence, lip inserted {r['confidence']} {r['steps']}")
r = mating.auto_assemble([{"key": "head", "name": "head", "tris": shift(head_with_peg(), 70, 70)}, {"key": "body", "name": "body", "tris": body_with_hole()}])
ph = r["poses"]["head"]
ok(r["base"] == "body" and mating.rot_matrix(*ph["rot"])[2, 2] < -0.99, f"head flipped so the peg points down {ph['rot']}")
ok(abs(ph["pos"][0]) < 0.8 and abs(ph["pos"][1]) < 0.8 and abs(ph["pos"][2] - 46) < 0.6, f"peg in the hole: head on top of the body {ph['pos']}")
ok(r["confidence"] >= 0.9 and abs(r["steps"][0]["insert_mm"] - 8) < 0.6, f"peg inserted 8 mm {r['steps']}")
r = mating.auto_assemble([{"key": "a", "name": "", "tris": box(0, 0, 0, 20, 20, 20)}, {"key": "b", "name": "", "tris": box(0, 0, 0, 20, 20, 20)}])
ok(r["confidence"] < asm.LOW_CONF + 0.1 and r["confidence"] < 0.8, f"plain stack (no interlock) → lower confidence {r['confidence']}")
st = mating.settle([{"key": "a", "tris": box(0, 0, 0, 20, 20, 20), "center": [10, 10, 10]}, {"key": "b", "tris": box(0, 0, 0, 20, 20, 10), "center": [10, 10, 5]}],
                   {"a": {"pos": [0, 0, 30], "rot": [0, 0, 0]}, "b": {"pos": [5, 0, 80], "rot": [0, 0, 0]}})
ok(abs(st["a"]["pos"][2] - 10) < 0.3 and abs(st["b"]["pos"][2] - 25) < 0.6, f"settle drops parts onto each other / the floor {st}")

# ---------- 2. 产品：盒子、盖子、身体 + 头（3MF 两个组件）、桌子（3MF：腿 x4、桌面、支撑测试件） ----------
PID = "3DP0002"
p = store.load(PID)
p["variants"] = [{"opt1_zh": "白色", "opt2_zh": "带盖", "sku": "3DP0002-WH-A", "grams": 30, "hours": 1.5},
                 {"opt1_zh": "白色", "opt2_zh": "无盖", "sku": "3DP0002-WH-B", "grams": 30, "hours": 1.5},
                 {"opt1_zh": "白色", "opt2_zh": "2个装", "sku": "3DP0002-WH-C", "grams": 30, "hours": 1.5},
                 {"opt1_zh": "白色", "opt2_zh": "大号", "sku": "3DP0002-WH-D", "grams": 30, "hours": 1.5}]
p["model_lib"] = []; p["display"] = None; p["print_plans"] = {}
store.save(p)
def stl(name, tris):
    fp = os.path.join(D, name); mesh.write_stl(tris, fp); return modellib.SavedFile(fp, name)
k3 = os.path.join(D, "figure.3mf")
pp.write_plate_3mf(k3, [("Body", body_with_hole(), (40, 40, 0), 1), ("Head", head_with_peg(), (150, 40, 0), 1)])
t3 = os.path.join(D, "table.3mf")
pp.write_plate_3mf(t3, [("leg x4", box(0, 0, 0, 6, 6, 40), (20, 20, 0), 1), ("table top", box(0, 0, 0, 80, 50, 4), (100, 60, 0), 1),
                        ("support_test", box(0, 0, 0, 5, 5, 5), (200, 200, 0), 1)])
lib = modellib.upload(PID, [stl("box.stl", open_box()), stl("lid.stl", lid()), modellib.SavedFile(k3, "figure.3mf"), modellib.SavedFile(t3, "table.3mf")], "boss")
BOX, LID, FIG, TAB = [x["id"] for x in lib]
ok(len(modellib._entry(store.load(PID), FIG)["info"].get("parts") or []) == 2, "figure 3MF has 2 parts")

# ---------- 3. 合并成一套设为模型：只影响打印，展示自动拆回零件 ----------
r = modellib.make_current(PID, [{"id": BOX, "qty": 1}, {"id": LID, "qty": 1}], "boss")
M = r["merged"]["id"]
p = store.load(PID)
ok(p["model"]["lib_id"] == M and modellib._entry(p, M)["origin"] == "merged", "main model is now the merged print layout")
rs = asm.resolve(p, "")
ok(rs["mode"] == "merged" and sorted(x["id"] for x in rs["items"]) == sorted([BOX, LID]), f"display expands the merged main model back into its parts {rs['items']}")
d = C.get(f"/api/products/{PID}/display").get_json()
ok(len(d["parts"]) == 2 and not d["plain"] and d["mode"] == "merged" and d["main_merged"], f"GET display: 2 parts, not the flat print layout {d.get('error')}")
t = asm.assembled_tris(PID)
nb, nl = len(open_box()), len(lid())
ok(t is not None and len(t) == nb + nl, f"assembled display = box + lid (not the merged STL) {None if t is None else len(t)}")
ok(C.get(f"/api/products/{PID}/display/stl").status_code == 200, "display STL served for the viewer")
# 老格式（v2.52）：source = 合并出来的模型 → 读的时候拆回零件
p = store.load(PID); p["display"] = {"source": M, "parts": [{"index": 0, "pos": [0, 0, 0], "rot": [0, 0, 0]}], "updated_at": 1}; store.save(p)
d = asm.get(PID)
ok(len(d["parts"]) == 2 and d["mode"] == "explicit" and not d["has_pose"], f"old v2.52 display on a merged model migrated lazily {d['mode']} {len(d['parts'])}")
p = store.load(PID); p["display"] = None; store.save(p)
# 自动组合 → 保存；再「合并成一套」打印方案：展示不变
r = C.post(f"/api/products/{PID}/display/auto-assemble", json={"spec": ""}).get_json()
ok(r["confidence"] >= 0.8 and not r["low"] and len(r["parts"]) == 2, f"API auto-assemble (box + lid) {r.get('error') or r['confidence']}")
lidk = next(x["key"] for x in d["parts"] if x["id"] == LID)
lp = next(x for x in r["parts"] if x["key"] == lidk)
ok(abs(lp["pos"][2] - 29) < 0.6, f"API: lid on the box {lp}")
d = C.post(f"/api/products/{PID}/display", json={"spec": "", "parts": r["parts"], "auto": {"conf": r["confidence"]}}).get_json()
ok(d["mode"] == "explicit" and d["has_pose"] and (d.get("auto") or {}).get("conf") == r["confidence"], "assembly saved with confidence")
tok = d["token"]
pp.save_plan(PID, "", {"plates": [{"id": "p1", "printer": "Bambu Lab P1S", "items": [{"id": BOX, "orient": "bottom"}, {"id": LID, "orient": "bottom"}]}]}, "boss")
r = C.post(f"/api/products/{PID}/print-plan/merge", json={"spec": "", "plate_id": "p1"}).get_json()
p = store.load(PID)
ok(r.get("ok") and p["model"]["lib_id"] != M, f"print plan merged into a new main model {r}")
d2 = asm.get(PID)
ok(d2["token"] == tok and [x["id"] for x in d2["items"]] == [x["id"] for x in d["items"]], "display unchanged after「合并成一套（设为模型）」")
ok(C.get(f"/api/products/{PID}/display/thumb").status_code == 200 and C.get(f"/api/products/{PID}/display/thumb").mimetype == "image/png", "display thumbnail")

# ---------- 4. 每个规格自己的展示 / 方案 ----------
d = C.post(f"/api/products/{PID}/display", json={"spec": "无盖", "items": [{"id": BOX, "part": None, "qty": 1}], "parts": []}).get_json()
ok(d["spec"] == "无盖" and len(d["parts"]) == 1 and d["mode"] == "explicit", f"spec display with its own part selection {d.get('error')}")
ok(asm.resolve(store.load(PID), "带盖")["mode"] == "inherit", "spec without its own display follows the main one")
ok(len(asm.assembled_tris(PID, "无盖")) == nb and len(asm.assembled_tris(PID, "带盖")) == nb + nl, "assembled per spec")
r = C.post(f"/api/products/{PID}/print-plan", json={"spec": "无盖", "plan": {"plates": [{"id": "p1", "printer": "Bambu Lab P1S", "items": [{"id": BOX, "orient": "bottom"}]}]}})
ok(r.status_code == 200 and r.get_json()["state"] == "saved", f"spec print plan saved {r.get_json().get('error')}")
p = store.load(PID)
ok(pp.plan_key(p, "无盖") == "无盖" and pp.plan_key(p, "带盖") == "", "production: own plan vs main plan")
ga, gb = pp.usage(p, "", "白色")["grams"], pp.usage(p, "无盖", "白色")["grams"]
ok(gb < ga and gb > 0, f"grams follow the spec's plan (无盖 {gb} < 带盖 {ga})")
jc = pp.job_colours(PID, "3DP0002-WH-B", "白色")
ok(len(jc) == 1 and abs(jc[0]["grams"] - gb) < 0.2 and pp._plan_for_sku(p, "3DP0002-WH-B")[0] == "无盖", f"SKU → spec plan {jc}")
ok(pp.check_plate({"printer": "Bambu Lab P1S", "items": [{"uid": "a", "x": 15, "y": 15, "rot": 0}]}, [256, 256, 256], {"a": pp.footprint(PID, LID, None, "bottom", p)})["items"]["a"]["out"],
   "a part on the Bambu purge chute corner counts as out of the bed")
st = C.get(f"/api/products/{PID}/model-status").get_json()
rows = {x["spec"]: x for x in st["specs"]}
ok(set(rows) == {"", "带盖", "无盖", "2个装", "大号"} and rows["无盖"]["display"]["mode"] == "explicit" and rows["带盖"]["plan"]["state"] == "inherit"
   and rows[""]["plan"]["state"] == "saved" and rows[""]["plan"].get("cost"), f"③ overview per spec {[(k, v['display']['mode'], v['plan']['state']) for k, v in rows.items()]}")
ok(PC.get(f"/api/products/{PID}/model-status").status_code == 200 and "cost" not in {k for x in PC.get(f"/api/products/{PID}/model-status").get_json()["specs"] for k in x["plan"]},
   "production role sees the overview without cost")
ok(C.get(f"/api/products/{PID}/print-plan/thumb?spec=无盖").mimetype == "image/svg+xml", "plate thumbnail (SVG)")

# ---------- 5. 从规格复制 ----------
d = C.post(f"/api/products/{PID}/display/copy", json={"spec": "2个装", "from": "无盖"}).get_json()
ok(d["mode"] == "explicit" and [x["id"] for x in d["items"]] == [BOX], f"display copied from another spec {d.get('error')}")
r = C.post(f"/api/products/{PID}/print-plan/copy", json={"spec": "2个装", "from": "无盖"}).get_json()
ok(r["plan"]["plates"][0]["items"][0]["id"] == BOX and r["plan"].get("copied_from") == "无盖", "print plan copied from another spec")
d = C.post(f"/api/products/{PID}/display", json={"spec": "2个装", "items": [{"uid": d["items"][0]["uid"], "id": BOX, "qty": 2}], "parts": []}).get_json()
ok(len(d["parts"]) == 2 and asm.resolve(store.load(PID), "无盖")["items"][0]["qty"] == 1, "edit the copy (qty 2) without touching the source")

# ---------- 6. 按主模型缩放 ----------
d = C.post(f"/api/products/{PID}/spec-scale", json={"spec": "大号", "pct": 150}).get_json()
ok(d["mode"] == "scale" and d["scale"] == 150, f"spec scaled from the main model {d.get('error')}")
tm, tl = asm.assembled_tris(PID, ""), asm.assembled_tris(PID, "大号")
sm, sl = mesh.size(tm), mesh.size(tl)
ok(all(abs(b - a * 1.5) < 0.3 for a, b in zip(sm, sl)), f"display scaled 150% {sm} → {sl}")
p = store.load(PID)
plan = pp.get_plan(p, "大号")
ok(plan.get("follow") and all(abs(it["scale"] - 1.5) < 1e-6 for pl in plan["plates"] for it in pl["items"]), "plan follows the main plan, parts scaled")
ok(abs(pp.usage(p, "大号", "白色")["grams"] - pp.usage(p, "", "白色")["grams"] * 3.375) < 0.6, "grams × 1.5³")
f1, f2 = pp.footprint(PID, BOX, None, "bottom", p), pp.footprint(PID, BOX, None, "bottom", p, 1.5)
ok(abs(f2["w"] - f1["w"] * 1.5) < 0.2 and abs(f2["h"] - f1["h"] * 1.5) < 0.2, "footprint scaled")
ok(pp._plan_for_sku(p, "3DP0002-WH-D")[0] == "大号" and pp.plan_summary(p, "大号")["state"] == "follow", "production uses the scaled plan")
r = C.get(f"/api/products/{PID}/print-plan/export?spec=大号&plate=p1")
ok(r.status_code == 200, "export a scaled plate")
ok(C.post(f"/api/products/{PID}/display", json={"spec": "大号", "parts": []}).status_code == 400, "scaled spec display can't be edited separately")
d = C.post(f"/api/products/{PID}/spec-scale", json={"spec": "大号", "pct": None}).get_json()
ok(d["mode"] == "inherit" and "大号" not in (store.load(PID).get("print_plans") or {}), "scale cancelled")

# ---------- 6b. v2.53.1 按主模型缩放的规格只用自己（这个缩放比例）的切片文件 ----------
from core import print_files, production, trial
from modules.prod import slicecheck
REVIEW = {k: True for k, _ in print_files.REVIEW_ITEMS}
CONFIRM = {"bed_clear": True, "material": True, "review": REVIEW}
def gf(name, spec="", sku="", plate="p1", scale=None):
    path = os.path.join(D, name)
    open(path, "w").write("; filament used [g] = 10\nM83\nG28\n;LAYER_CHANGE\nG1 X60 Y60 E1\n")
    f = print_files.add(path, name, PID, "Bambu Lab P1S", sku, 1, "", "t", "boss", "PLA", 10, 1, source="plan", spec=spec, plate_id=plate, scale=scale)
    slicecheck.confirm(f["id"], "Bambu Lab P1S", "boss")
    print_files.review(f["id"], REVIEW, "boss")
    return print_files.get(f["id"])
C.post(f"/api/products/{PID}/spec-scale", json={"spec": "大号", "pct": 150})
p = store.load(PID)
ok(specmodel.file_spec(p, "大号") == "大号" and specmodel.follow_scale(p, "大号") == 150 and specmodel.plan_sliced(p, "大号")
   and specmodel.file_spec(p, "带盖") == "", "file_spec: scaled spec has its own files, inheriting spec uses the main ones")
fm = gf("main100.gcode")
fsku = gf("main100_skuD.gcode", sku="3DP0002-WH-D")            # 主模型 100% 的文件，却标了大号的 SKU
fl = gf("big150.gcode", spec="大号")
ok(fl["scale"] == 150 and fm["scale"] is None, f"scale recorded on the scaled spec's file automatically {fl['scale']}")
ids = lambda rows: [x["id"] for x in rows]
cd = ids(print_files.candidates(PID, "3DP0002-WH-D", "Bambu Lab P1S", usable_only=False))
ok(cd == [fl["id"]], f"scaled-spec job: only the scaled spec's files are candidates {cd} (main {fm['id']}, sku-labelled main {fsku['id']})")
ca = ids(print_files.candidates(PID, "3DP0002-WH-A", "Bambu Lab P1S", usable_only=False))
ok(fm["id"] in ca and fl["id"] not in ca and fsku["id"] not in ca, f"main-model job never gets the scaled file {ca}")
jD = production.create_job(PID, "3DP0002-WH-D", 1, "stock", user="boss")
for bad in (fm, fsku):
    try:
        production.start_run(jD["id"], 0, file_id=bad["id"], send=False, user="boss", confirm=CONFIRM); ok(False, "main file refused")
    except ValueError as e:
        ok("文件尺寸 / 规格和任务不一致" in str(e) and "大号" in str(e), f"main-model file refused for the scaled job: {e}")
r = PC.post(f"/api/jobs/{jD['id']}/start", json={"printer": 0, "send": False, "confirm": CONFIRM, "file_id": fm["id"]})
ok(r.status_code == 400 and "文件尺寸 / 规格和任务不一致" in r.get_json()["error"], "API refuses it too")
so = production.send_options(jD["id"], 0)
ok(ids(so["files"]) == [fl["id"]] and so["usable_files"] == [fl["id"]] and so["recipe"] is None, f"send options list only the scaled file {ids(so['files'])}")
ok(production._file_for_count(dict(production._job(db.conn(), jD["id"])), 0, 1)["id"] == fl["id"], "_file_for_count picks the scaled file")
# 合并：不同规格（大小）的任务不能拼一盘
jA = production.create_job(PID, "3DP0002-WH-A", 1, "stock", user="boss")
ok(jA["id"] not in ids(production.merge_candidates(jD["id"])), "a main-size job is not offered for merging with the scaled one")
try:
    production.start_run(jD["id"], 0, merge_ids=[jA["id"]], send=False, user="boss", confirm=CONFIRM); ok(False, "merge refused")
except ValueError as e:
    ok("别的规格" in str(e), f"merging different sizes refused: {e}")
# 缩放比例改了：按 150% 切的文件作废
C.post(f"/api/products/{PID}/spec-scale", json={"spec": "大号", "pct": 130})
ok(not print_files.candidates(PID, "3DP0002-WH-D", "Bambu Lab P1S", usable_only=False), "after changing the scale the 150% file is no candidate")
try:
    production.start_run(jD["id"], 0, file_id=fl["id"], send=False, user="boss", confirm=CONFIRM); ok(False, "old scale refused")
except ValueError as e:
    ok("130%" in str(e) and "150%" in str(e), f"file sliced at another scale refused: {e}")
# 规格缩放取消后，大号跟主模型：大号的旧文件不能用，主模型的可以
C.post(f"/api/products/{PID}/spec-scale", json={"spec": "大号", "pct": None})
cd = ids(print_files.candidates(PID, "3DP0002-WH-D", "Bambu Lab P1S", usable_only=False))
ok(fl["id"] not in cd and fm["id"] in cd, f"scale cancelled: back to the main files {cd}")
for j_ in (jD, jA):
    production.delete_stock_job(j_["id"], "boss")
for f_ in (fm, fsku, fl):
    print_files.update(f_["id"], active=0)

# ---------- 7. 自动选零件 ----------
ok(asm.name_qty("leg x4") == 4 and asm.name_qty("4x leg.stl") == 4 and asm.name_qty("keycap_1x3") == 1 and asm.name_qty("arm (2pcs)") == 2, "quantity from part names")
r = C.post(f"/api/products/{PID}/display/auto-select", json={"spec": "无盖"}).get_json()
ok([x["id"] for x in r["items"]] == [BOX], f"「无盖」drops the lid {r}")
p = store.load(PID); p["model"]["lib_id"] = M; store.save(p)       # 主模型换回合并的「盒子 + 盖子」
r = asm.auto_select(PID, "2个装")
ok(sorted(x["id"] for x in r["items"]) == sorted([BOX, LID]) and all(x["qty"] == 2 for x in r["items"]), f"「2个装」: merged main expanded, qty × 2 {r}")
p = store.load(PID); p["model"]["lib_id"] = TAB; store.save(p)
r = asm.auto_select(PID, "")
q = {x["part"]: x["qty"] for x in r["items"]}
ok(q == {0: 4, 1: 1}, f"table: legs × 4, top, support/test piece dropped {r}")
specmodel.map_spec(PID, "带盖", FIG, "boss")
r = asm.auto_select(PID, "带盖")
ok([(x["id"], x["part"]) for x in r["items"]] == [(FIG, 0), (FIG, 1)], f"spec mapped to its own model → its parts {r}")

# ---------- 8. 身体 + 头：规格自己的模型，自动组合；爆炸图 ----------
d = asm.get(PID, "带盖")
ok(d["mode"] == "own" and len(d["parts"]) == 2, f"spec with its own model shows its parts {d['mode']}")
r = asm.auto_assemble(PID, "带盖")
hk = next(x["key"] for x in d["parts"] if x["name"] == "Head")
h = next(x for x in r["parts"] if x["key"] == hk)
bk = next(x["key"] for x in d["parts"] if x["name"] == "Body")
b = next(x for x in r["parts"] if x["key"] == bk)
ok(r["confidence"] >= 0.9 and abs(h["pos"][2] - b["pos"][2] - 26) < 0.6 and abs(h["pos"][0] - b["pos"][0]) < 0.8, f"head plugged into the body {b} {h}")
asm.save(PID, {"parts": r["parts"]}, "boss", "带盖")
off = asm.explode(PID, "带盖")
ok(set(off) == {hk, bk} and off[hk][2] > off[bk][2] + 10 and abs(off[hk][0]) < 1, f"exploded view pulls the head up along the assembly axis {off}")
r = C.post(f"/api/products/{PID}/display/explode", json={"spec": "带盖", "factor": 2}).get_json()
ok(r["offsets"][hk][2] - r["offsets"][bk][2] > (off[hk][2] - off[bk][2]) * 1.5, "explode factor")

# ---------- 9. 从组装生成打印方案 ----------
plan = pp.plan_from_display(PID, "带盖")
pl0 = plan["plates"][0]
f = pp.fps_for(PID, store.load(PID), pl0)
ok(len(plan["plates"]) == 1 and len(pl0["items"]) == 2 and pp.check_plate(pl0, pp.bed_of(pl0["printer"]), f)["ok"], "assembly → one plate, parts laid flat, no overlap")
ok(any(abs(f[it["uid"]]["h"] - 20) < 0.5 or abs(f[it["uid"]]["h"] - 28) < 0.5 for it in pl0["items"]), "parts use the recommended orientation")
asm.save(PID, {"items": [{"id": BOX, "qty": 20}], "parts": []}, "boss", "2个装")
r = C.post(f"/api/products/{PID}/print-plan/from-display", json={"spec": "2个装"}).get_json()
n = sum(len(x["items"]) for x in r["plan"]["plates"])
ok(len(r["plan"]["plates"]) >= 2 and n == 20 and all(c["ok"] for c in r["checks"].values()), f"too many parts → split into plates {len(r['plan']['plates'])} plates, {n} parts")
r2 = C.post(f"/api/products/{PID}/print-plan", json={"spec": "2个装", "plan": r["plan"]})
ok(r2.status_code == 200, f"generated plan saves {r2.get_json().get('error')}")

# ---------- 10. 一键全部切片（真的 OrcaSlicer） ----------
if not slicer.find_orca(load_config()):
    print("SKIP 没有 OrcaSlicer：一键全部切片")
else:
    p = store.load(PID); p["model"]["lib_id"] = M; p["print_plans"].pop("2个装", None); store.save(p)
    specmodel.map_spec(PID, "带盖", "", "boss")
    pp.save_plan(PID, "无盖", {"plates": [{"id": "p1", "printer": "Bambu Lab P1S", "items": [{"id": BOX, "orient": "bottom"}]},
                                         {"id": "p2", "printer": "Bambu Lab P1S", "items": [{"id": LID, "orient": "bottom"}]}]}, "boss")
    C.post(f"/api/products/{PID}/spec-scale", json={"spec": "大号", "pct": 120})
    r = C.post(f"/api/products/{PID}/print-plan/slice-all", json={}).get_json()
    ok(r.get("total") == 4 and len(r["results"]) == 4 and not r["errors"], f"batch slicing: main 1 + 无盖 2 + 大号 1 plates {r.get('error') or r.get('errors')}")
    p = store.load(PID)
    for s in ("", "无盖", "大号"):
        sm = pp.plan_summary(p, s)
        ok(sm["sliced"] == sm["plates"] and not sm["est"], f"{s or 'main'}: every plate sliced, grams from the slicer {sm}")
    vs = {v["opt2_zh"]: v for v in p["variants"]}
    ok(vs["无盖"]["grams_src"] == "plan" and vs["大号"]["grams_src"] == "plan" and vs["带盖"]["grams_src"] == "plan", f"variants filled from the plans {[(k, v.get('grams'), v.get('grams_src')) for k, v in vs.items()]}")
    ok(vs["大号"]["grams"] > vs["带盖"]["grams"] * 1.4, f"scaled spec sliced bigger {vs['大号']['grams']} vs {vs['带盖']['grams']}")
    st = pp.SLICE_ALL.get(PID)
    ok(st and st["done"] == st["total"] == 4 and not st["running"], f"progress recorded {st and {k: st[k] for k in ('done', 'total', 'running')}}")
    rows = {x["spec"]: x for x in C.get(f"/api/products/{PID}/model-status").get_json()["specs"]}
    ok(rows["无盖"]["plan"]["state"] == "sliced", "overview shows 已切片")

    # ---------- v2.53.1 真切片：按主模型缩放 120% 的规格生产 / 试打用的是缩放后的文件 ----------
    import re
    from core import printers as pr
    def zmax(f):
        z = zm = 0.0
        for line in trial._gcode_text(f, 60_000_000).splitlines():
            if line.startswith(("G1", "G0", "G2", "G3")):
                mz = re.search(r"Z([-\d.]+)", line)
                if mz:
                    z = float(mz.group(1))
                me = re.search(r"E([-\d.]+)", line)
                if me and float(me.group(1)) > 0 and re.search(r"[XY]", line):
                    zm = max(zm, z)
        return zm
    res = {x["spec"]: x["file_id"] for x in r["results"]}
    fmain, fbig = print_files.get(res[""]), print_files.get(res["大号"])
    ok(fbig["spec"] == "大号" and fbig["scale"] == 120 and (fmain["spec"] or "") == "" and fmain["scale"] is None, f"slice-all: scaled file tagged 大号 @120% {fbig['spec']} {fbig['scale']}")
    zm, zb = zmax(fmain), zmax(fbig)
    ok(zm > 5 and abs(zb / zm - 1.2) < 0.04, f"G-code: the scaled file really is 120% tall ({zb} vs {zm} mm)")
    jD = production.create_job(PID, "3DP0002-WH-D", 1, "stock", user="boss")
    n0 = len(print_files.list_files(PID))
    fnew = production._file_for_count(dict(production._job(db.conn(), jD["id"])), 0, 1, user="boss")
    ok(len(print_files.list_files(PID)) == n0 + 1 and fnew["spec"] == "大号" and fnew["scale"] == 120 and fnew["source"] == "plan",
       f"no reviewed scaled file -> sliced the scaled plan (not the main model) {fnew['spec']} {fnew['scale']} {fnew['source']}")
    ok(abs(zmax(fnew) / zm - 1.2) < 0.04, f"newly sliced file is 120% tall ({zmax(fnew)} mm)")
    try:
        production.start_run(jD["id"], 0, file_id=fmain["id"], send=False, user="boss", confirm=CONFIRM); ok(False, "main refused")
    except ValueError as e:
        ok("文件尺寸 / 规格和任务不一致" in str(e), f"main 100% file refused for the 120% job: {e}")
    print_files.review(fnew["id"], REVIEW, "boss")
    cfg = load_config(); cfg["printers"][0]["conn"] = {"type": "bambu", "host": "10.0.0.9"}; save_config(cfg)
    SENT = []
    pr.send_file = lambda idx, path, name, kind, slot=None: (SENT.append(os.path.basename(path)) or name)
    pr.match_tray = lambda *a, **k: None
    rs = production.start_run(jD["id"], 0, send=True, user="boss", confirm=CONFIRM)
    ok(rs["file"]["id"] == fnew["id"] and SENT == [fnew["stored"]], f"start_run sends the scaled file {SENT} {fnew['stored']}")
    production.cancel_run(rs["run_id"], "boss")
    production.delete_stock_job(jD["id"], "boss")
    # 试打：用大号的文件，结果写回大号的文件 / 方案 / 款式，主模型的不动
    gA = next(v for v in store.load(PID)["variants"] if v["opt2_zh"] == "带盖")["grams"]
    try:
        trial.create_trial(PID, "3DP0002-WH-D", None, "p1", 0, fmain["id"], "boss"); ok(False, "trial with main refused")
    except ValueError as e:
        ok("文件尺寸 / 规格和任务不一致" in str(e), f"trial with the main-model file refused: {e}")
    ck = trial.check_file(PID, None, "p1", 0, fmain["id"], "3DP0002-WH-D", "boss", False)
    ok(not ck["ok"] and any(c["key"] == "spec" and c["level"] == "error" for c in ck["checks"]), f"check-file flags the main file for the scaled spec {ck['errors']}")
    tr = trial.create_trial(PID, "3DP0002-WH-D", None, "p1", 0, None, "boss")
    ok(tr["file"]["id"] == fnew["id"] and tr["trial"]["spec"] == "大号", f"trial for the scaled spec uses its file {tr['file']['id']}")
    rr = production.start_run(tr["job"]["id"], 0, send=False, user="boss", confirm=CONFIRM)
    production.finish_run(rr["run_id"], "boss")
    trial.submit_result(tr["job"]["id"], True, grams=77, hours=5, dest="sample", user="boss")
    ok(print_files.get(fnew["id"])["status"] == "verified" and print_files.get(fnew["id"])["actual_grams"] == 77, "trial verifies the scaled file")
    ok(print_files.get(fmain["id"])["status"] != "verified" and not print_files.get(fmain["id"]).get("actual_grams"), "main-model file untouched")
    p = store.load(PID)
    vs = {v["opt2_zh"]: v for v in p["variants"]}
    sb = (p["print_plans"]["大号"].get("sliced_by") or {}).get("p1") or {}
    ok(vs["大号"]["grams_src"] == "trial" and abs(vs["大号"]["grams"] - 77) < 1 and sb.get("trial"), f"grams written to the scaled spec {vs['大号']['grams']} {sb.get('trial')}")
    ok(vs["带盖"]["grams"] == gA and not (((p["print_plans"].get("") or {}).get("plates") or [{}])[0].get("sliced") or {}).get("trial"), "main plan / inheriting spec untouched")

print("ERRORS", E_)
sys.exit(1 if E_ else 0)
