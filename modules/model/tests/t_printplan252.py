# v2.52：打印方案（每个规格几盘、手动摆盘、重叠 / 超出热床检查、合并按摆好的位置）、组合摆盘（规则 / AI）、
# 展示模型（组装姿势、AI 按图片组装）、多色（AMS 槽、配色方案、slice_info 每个耗材用量、冲刷估算、按颜色算成本、
# 生产任务的颜色要求 + 只排给有 AMS 的打印机 + 按颜色扣耗材）、模型库空打风险编号的中文 / 泰文
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import base64, io, json, os, sys, shutil, sqlite3, zipfile
D = T + "/m_plan252"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import numpy as np
import app as A
from core import db, store, modellib, pricing, production, slicer, codes, fleet
from core.config import load_config, save_config
from modules.model import printplan as pp, assembly as asm
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pong", "secret123", "production", "Pong")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
PC = A.app.test_client(); PC.post("/api/auth/login", json={"username": "pong", "password": "secret123"})

def box(w, d, h):
    v = np.array([[0, 0, 0], [w, 0, 0], [w, d, 0], [0, d, 0], [0, 0, h], [w, 0, h], [w, d, h], [0, d, h]], float)
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return v[np.array(f)]

# ---------- 打印机：P1S（有 AMS）+ K1C（没有） ----------
cfg = load_config()
save_config({"printers": [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "tech": "fdm"},
                          {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "enabled": True, "tech": "fdm"}]})
prs = load_config()["printers"]
ok(fleet.is_multicolor(prs[0]) and not fleet.is_multicolor(prs[1]), "P1S multicolour by default, K1C not")
ok(fleet.is_multicolor({"name": "Creality K1C", "ams": True}) and not fleet.is_multicolor({"name": "Bambu Lab P1S", "ams": False}), "ams setting overrides")
ok([m["name"] for m in pp.printer_models()] == ["Bambu Lab P1S", "Creality K1C"] and pp.bed_of("Creality K1C")[0] == 220, "printer models + beds")

# ---------- 产品：3 个零件的 3MF（我们自己的 3MF 写法：每个零件带耗材槽）+ 一个小方块 STL ----------
PID = "3DP0002"
p = store.load(PID)
p["variants"] = [{"opt1_zh": "白色", "opt2_zh": "", "sku": "3DP0002-WH", "grams": 30, "hours": 1.5},
                 {"opt1_zh": "黑色", "opt2_zh": "", "sku": "3DP0002-BK", "grams": 30, "hours": 1.5}]
store.save(p)
tmp3 = os.path.join(D, "kit.3mf")
pp.write_plate_3mf(tmp3, [("Base", box(60, 60, 5), (40, 40, 0), 1), ("Body", box(40, 40, 30), (120, 40, 0), 1), ("Head", box(30, 30, 20), (200, 40, 0), 2)],
                   [{"hex": "#FFFFFF", "material": "PLA"}, {"hex": "#000000", "material": "PLA"}])
ci = __import__("core.mesh", fromlist=["x"]).colors_3mf(open(tmp3, "rb").read())
ok(ci and ci["multicolor"] and [x["slot"] for x in ci["parts"]] == [1, 1, 2], f"own 3MF writer: per-part extruder read back {ci and ci['parts']}")
tmps = os.path.join(D, "cube.stl"); __import__("core.mesh", fromlist=["x"]).write_stl(box(20, 20, 20), tmps)
lib = modellib.upload(PID, [modellib.SavedFile(tmp3, "kit.3mf"), modellib.SavedFile(tmps, "cube.stl")], "boss")
K3, CUBE = lib[0]["id"], lib[1]["id"]
info = modellib._entry(store.load(PID), K3)["info"]
ok(len(info.get("parts") or []) == 3, f"3 parts analysed {len(info.get('parts') or [])}")

# ---------- C. 空打风险编号 → 中文 / 泰文 ----------
for code in modellib.RISK_CODES:
    zh, th = modellib.risk_label(code, {"c": 1, "o": 2, "h": 3, "r": 4}), modellib.risk_label(code, {"c": 1, "o": 2, "h": 3, "r": 4}, "th")
    ok(zh != code and th != code and zh != th and "{" not in zh, f"risk label {code}")
js = open(os.path.join(APP, "modules/prod/ui/files.js"), encoding="utf-8").read()
ok("L(r.code" not in js and "TR(r.code" in js, "模型库表格按编号翻译风险（不再显示 risk.contact_warn）")

# ---------- 打印方案：默认 / 保存 / 重叠 / 超出热床 ----------
r = C.get(f"/api/products/{PID}/print-plan").get_json()
ok(r["plan"]["plates"] and r["plan"].get("default") and r["printers"], "default plan from current model")
fp = pp.footprint(PID, CUBE, None, "bottom")
ok(abs(fp["w"] - 20) < 0.2 and abs(fp["d"] - 20) < 0.2 and abs(fp["h"] - 20) < 0.2 and len(fp["hull"]) >= 4, f"footprint {fp['w']}x{fp['d']}x{fp['h']}")
fpb = pp.footprint(PID, K3, 1, "front")
ok(abs(fpb["h"] - 40) < 0.3 and abs(fpb["d"] - 30) < 0.3, f"footprint of part with orientation {fpb['w']}x{fpb['d']}x{fpb['h']}")
plate = {"id": "p1", "printer": "Bambu Lab P1S", "layer_height": 0.2, "sets": 1, "manual": True,
         "slots": [{"slot": 1, "material": "PLA", "colour": ""}, {"slot": 2, "material": "PLA", "colour": "黑色"}],
         "items": [{"uid": "a1", "id": K3, "part": 0, "orient": "bottom", "slot": 1, "x": 50, "y": 50, "rot": 0},
                   {"uid": "a2", "id": K3, "part": 1, "orient": "bottom", "slot": 1, "x": 60, "y": 60, "rot": 0},
                   {"uid": "a3", "id": K3, "part": 2, "orient": "bottom", "slot": 2, "x": 200, "y": 200, "rot": 45}]}
r = C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": {"plates": [plate]}})
ok(r.status_code == 400 and "重叠" in r.get_json()["error"], f"overlap refused {r.get_json()}")
plate["items"][1].update(x=150, y=60)
plate["items"][2].update(x=250, y=250)
r = C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": {"plates": [plate]}})
ok(r.status_code == 400 and "超出热床" in r.get_json()["error"], f"out of bed refused {r.get_json()}")
ck = pp.check_plate({"items": plate["items"]}, [256, 256, 256], {it["uid"]: pp.footprint(PID, K3, it["part"], "bottom") for it in plate["items"]})
ok(ck["items"]["a3"]["out"] and not ck["items"]["a1"]["out"] and not ck["items"]["a1"]["overlap"], f"check_plate per item {ck['items']}")
plate["items"][2].update(x=200, y=180, rot=30)
r = C.post(f"/api/products/{PID}/print-plan", json={"spec": "", "plan": {"plates": [plate], "schemes": {"黑色": {"1": "黑色", "2": "白色"}}}})
ok(r.status_code == 200 and r.get_json()["checks"]["p1"]["ok"], f"manual plate saved {r.get_json().get('error')}")
saved = store.load(PID)["print_plans"][""]
ok([(i["x"], i["y"], i["rot"]) for i in saved["plates"][0]["items"]] == [(50, 50, 0), (150, 60, 0), (200, 180, 30)], "positions saved as placed")
# 生产员工也能看 / 存方案；check 接口自动排列
ok(PC.get(f"/api/products/{PID}/print-plan").status_code == 200, "production role can open the print plan")
r = PC.post(f"/api/products/{PID}/print-plan/check", json={"plate": dict(plate, items=[dict(i, x=None, y=None) for i in plate["items"]]), "arrange": True}).get_json()
ok(r["check"]["ok"] and all(i["x"] is not None for i in r["plate"]["items"]), f"auto arrange gives a valid plate {r['check']}")

# ---------- 合并 / 预览 / 导出用摆好的位置 ----------
sel = pp.plate_selection(saved["plates"][0])
ok(all("x" in s for s in sel), "plate selection carries positions")
tris = modellib.layout_preview(PID, sel)
v = tris.reshape(-1, 3)
ok(abs(v[:, 0].min() - 20) < 0.6 and abs(v[:, 1].min() - 20) < 0.6, f"layout uses saved positions (base at 50,50 → min 20,20) {v[:, :2].min(0)}")
e = modellib.make_entry(PID, sel, "boss", name="plate_test")
t2 = modellib.load_parts(modellib.path_of(PID, e))[0][1].reshape(-1, 3)
ok(abs(t2[:, 0].min() - 20) < 0.6 and abs(t2[:, 0].max() - pp._poly(pp.footprint(PID, K3, 2, "bottom"), 200, 180, 30)[0][0]) < 60, "merged model keeps manual layout")
r = C.get(f"/api/products/{PID}/print-plan/export?plate=p1&colour=黑色")
z = zipfile.ZipFile(io.BytesIO(r.data))
ms = z.read("Metadata/model_settings.config").decode()
ok(r.status_code == 200 and ms.count('key="extruder" value="2"') == 2 and "transform" in z.read("3D/3dmodel.model").decode(), "export 3MF: positions + per-part filament slot")
ok(json.loads(z.read("Metadata/project_settings.config"))["filament_colour"][0].lower() == codes.color_hex(load_config())["黑色"]["hex"].lower(),
   "export uses the colour scheme (黑款: slot 1 black)")

# ---------- 每个规格自己的方案 ----------
p = store.load(PID)
p["variants"].append({"opt1_zh": "白色", "opt2_zh": "大号", "sku": "3DP0002-WH-L", "grams": 50, "hours": 2})
store.save(p)
from core import specmodel
specmodel.map_spec(PID, "大号", CUBE, "boss")
r = C.post(f"/api/products/{PID}/print-plan", json={"spec": "大号", "plan": {"plates": [{"id": "p1", "printer": "Creality K1C", "layer_height": 0.28, "sets": 4,
          "slots": [{"slot": 1, "material": "PETG"}], "items": [{"id": CUBE, "orient": "bottom"} for _ in range(4)]}]}})
ok(r.status_code == 200, f"spec plan saved {r.get_json().get('error')}")
pl = store.load(PID)["print_plans"]
ok(set(pl) == {"", "大号"} and pl["大号"]["plates"][0]["printer"] == "Creality K1C" and len(pl["大号"]["plates"][0]["items"]) == 4
   and all(i["x"] is not None for i in pl["大号"]["plates"][0]["items"]), "plan per spec, auto-arranged")
u = pp.usage(store.load(PID), "大号", "白色")
ok(not u["multicolor"] and u["colours"][0]["material"] == "PETG" and abs(u["grams"] - u["plates"][0]["grams"] / 4) < 0.2, f"sets per plate divides usage {u['grams']}")
# 编辑页保存整个产品时不会把方案盖掉
pr = C.get(f"/api/products/{PID}").get_json(); pr.pop("print_plans", None)
C.post(f"/api/products/{PID}", json=pr)
ok(set(store.load(PID).get("print_plans") or {}) == {"", "大号"}, "product save keeps print plans")

# ---------- 多色：配色、用量、冲刷估算 ----------
plan = pp.get_plan(store.load(PID), "")
ok(pp.colours_for(plan, plan["plates"][0], "白色") == {1: "白色", 2: "黑色"} and pp.colours_for(plan, plan["plates"][0], "黑色") == {1: "黑色", 2: "白色"},
   "slot → colour per colour variant (scheme)")
pe = pp.purge_estimate([30, 10], 0.2, {"mc_purge_g": 1.5, "mc_change_s": 60})
ok(pe["changes"] == 50 and pe["purge_g"] == 75 and abs(pe["extra_h"] - 50 * 60 / 3600) < 0.01 and pe["est"], f"purge estimate {pe}")
pe3 = pp.purge_estimate([30, 20, 10], 0.2, {"mc_purge_g": 1, "mc_change_s": 0})
ok(pe3["changes"] == 150, f"3 colours: k-1 changes per layer {pe3}")
ok(pp.purge_estimate([30], 0.2)["changes"] == 0, "single colour no purge")
u = pp.usage(store.load(PID), "", "白色")
cols = {c["colour"]: c for c in u["colours"]}
ok(u["multicolor"] and set(cols) == {"白色", "黑色"} and u["est"] and u["purge_g"] > 0 and u["grams"] > sum(c["grams"] for c in u["colours"]), f"multicolour usage {u['colours']} purge {u['purge_g']}")
h2 = pp.footprint(PID, K3, 2, "bottom")["h"]
ok(u["plates"][0]["changes"] == round(h2 / 0.2), f"changes only on layers where both colours exist {u['plates'][0]['changes']}")
v = next(x for x in store.load(PID)["variants"] if x["sku"] == "3DP0002-WH")
ok(isinstance(v.get("colour_usage"), list) and len(v["colour_usage"]) == 2, "saving the plan records per-colour usage on variants")

# ---------- 定价：按颜色拆分 ----------
cfg = load_config()
vv = {"grams": 40, "hours": 2, "colour_usage": [{"colour": "白色", "material": "PLA", "grams": 25, "purge_g": 5}, {"colour": "黑色", "material": "PLA", "grams": 8, "purge_g": 2}]}
pv = pricing.price_variant(cfg, vv, None, "PLA")
single = pricing.variant_cost(cfg, 40, 2, "PLA")
ok(len(pv["cost"]["per_colour"]) == 2 and abs(pv["cost"]["material"] - single["material"]) < 0.05 and abs(pv["cost"]["total"] - single["total"]) < 0.1,
   f"multi-colour cost split, same total for same grams {pv['cost']['material']} vs {single['material']}")
ok(pv["cost"]["per_colour"][0]["grams"] == 25 and pv["cost"]["purge_g"] == 7, "per colour grams + purge in breakdown")
vv2 = dict(vv, grams=80)
ok(abs(pricing.price_variant(cfg, vv2, None, "PLA")["cost"]["material"] - pricing.variant_cost(cfg, 80, 2, "PLA")["material"]) < 0.05, "breakdown scaled to the variant grams")
ok("per_colour" not in pricing.price_variant(cfg, {"grams": 40, "hours": 2}, None, "PLA")["cost"], "single colour unchanged")
r = C.post(f"/api/products/{PID}/print-plan/fill", json={"spec": ""}).get_json()
v = next(x for x in store.load(PID)["variants"] if x["sku"] == "3DP0002-BK")
ok(r["n"] == 2 and v["grams_src"] == "plan_est" and abs(v["grams"] - pp.usage(store.load(PID), "", "黑色")["grams"]) < 0.11, "fill variants from plan")

# ---------- slice_info / G-code：每个耗材的用量 ----------
sl = os.path.join(D, "sliced.gcode.3mf")
with zipfile.ZipFile(sl, "w") as z:
    z.writestr("Metadata/slice_info.config", '<?xml version="1.0"?><config><plate><metadata key="index" value="1"/>'
               '<metadata key="prediction" value="5400"/><metadata key="weight" value="14.90"/>'
               '<filament id="1" tray_info_idx="GFA00" type="PLA" color="#FFFFFF" used_m="3.10" used_g="9.30" />'
               '<filament id="2" tray_info_idx="GFA00" type="PLA" color="#000000" used_m="1.80" used_g="5.60" /></plate></config>')
    z.writestr("Metadata/plate_1.gcode", "; HEADER\n; filament used [g] = 9.30, 5.60\n; total filament used for wipe tower [g] = 1.42\n; total filament change = 37\nG1 X0\n")
r = slicer.parse_sliced_file(sl)
ok(r["grams"] == 14.9 and abs(r["hours"] - 1.5) < 0.01 and [f["grams"] for f in r["filaments"]] == [9.3, 5.6] and r["filaments"][1]["hex"] == "#000000",
   f"slice_info per-filament {r.get('filaments')}")
ok(r.get("purge_g") == 1.42 and r.get("changes") == 37, f"purge + colour changes from G-code {r.get('purge_g')} {r.get('changes')}")
g = slicer.parse_gcode_text("; filament used [g] = 3.45, 1.20\n; estimated printing time (normal mode) = 1h 2m 3s\n")
ok(abs(g["grams"] - 4.65) < 0.06 and [f["grams"] for f in g["filaments"]] == [3.45, 1.2], f"gcode per-extruder grams {g}")
ok("filaments" not in slicer.parse_gcode_text("; filament used [g] = 3.45\n; estimated printing time = 1h\n"), "single extruder: no breakdown")
# 涂色 / 多色 3MF 带切片数据：分析时记下每种耗材的用量（MakerWorld 下载的项目文件常带）
pt = os.path.join(D, "painted.3mf")
pp.write_plate_3mf(pt, [("Base", box(60, 60, 5), (40, 40, 0), 1), ("Body", box(40, 40, 30), (120, 40, 0), 1), ("Head", box(30, 30, 20), (200, 40, 0), 2)],
                   [{"hex": "#FFFFFF", "material": "PLA"}, {"hex": "#000000", "material": "PLA"}])
with zipfile.ZipFile(pt, "a") as z:
    z.writestr("Metadata/slice_info.config", '<config><plate><filament id="1" type="PLA" color="#FFFFFF" used_g="7.5" used_m="2"/><filament id="2" type="PLA" color="#000000" used_g="2.5" used_m="1"/></plate></config>')
    z.writestr("Metadata/plate_1.gcode", "; filament used [g] = 7.5, 2.5\n")
PT = modellib.upload(PID, [modellib.SavedFile(pt, "painted.3mf")], "boss")[0]
ok((PT["info"].get("colors") or {}).get("usage") == [{"slot": 1, "grams": 7.5}, {"slot": 2, "grams": 2.5}], f"painted 3MF usage read {(PT['info'].get('colors') or {}).get('usage')}")
pl3 = {"id": "pz", "printer": "Bambu Lab P1S", "layer_height": 0.2, "sets": 1, "items": [{"uid": "z1", "id": PT["id"], "part": None, "slot": 1}],
       "slots": pp._slots_from_file(PT["info"]["colors"], "PLA")}
uz = pp.plate_usage(store.load(PID), {"plates": [pl3], "schemes": {}}, pl3, "白色")
gs = {x["slot"]: x["grams"] for x in uz["slots"]}
ok(len(pl3["slots"]) == 2 and abs(gs[1] / (gs[1] + gs[2]) - 0.75) < 0.01 and uz["multicolor"], f"painted 3MF kept as-is, split by its slice_info {gs}")
# 切片（OrcaSlicer 不在这台机器：用假的切片结果）→ 方案记下每槽克数，用量不再标「估」
_orig = slicer.orca_slice
def fake_slice(cfg, model, idx, mat, **kw):
    ok(kw.get("arrange") is False and kw.get("orient") is False and len(kw.get("filaments") or []) == 2 and kw["overrides"].get("enable_prime_tower") == "1",
       f"multi-material slice call {sorted(kw)}")
    ok(zipfile.ZipFile(model).read("Metadata/model_settings.config").count(b'value="2"') == 2, "slicer gets the 3MF with per-part slots")
    shutil.copyfile(sl, kw["keep_to"])
    res = slicer.parse_sliced_file(sl); res["kept"] = kw["keep_to"]
    return res
slicer.orca_slice = fake_slice
try:
    r = pp.slice_plate(PID, "", "p1", "白色", None, "boss")
finally:
    slicer.orca_slice = _orig
# 切片软件给的克数含冲刷：记净克数（9.3 / 5.6 按比例扣掉 1.42 g 冲刷）
ok(abs(r["sliced"]["filaments"][0]["grams"] - 8.41) < 0.02 and abs(r["sliced"]["filaments"][1]["grams"] - 5.07) < 0.02 and r["sliced"]["purge_g"] == 1.42 and r["file"]["id"], f"slice plate stored (net of purge) {r['sliced']}")
u2 = pp.usage(store.load(PID), "", "白色")
ok(not u2["est"] and abs(u2["purge_g"] - 1.42) < 0.05 and {c["colour"]: c["grams"] for c in u2["colours"]} == {"白色": 8.4, "黑色": 5.1}, f"sliced usage replaces estimate {u2['colours']}")

# ---------- 生产：颜色要求、只排给有 AMS 的打印机、按颜色扣耗材 ----------
cols = production.job_colours(PID, "3DP0002-WH", "白色")
ok(len(cols) == 2 and production.needs_multicolor(cols) and production.ams_text(cols).startswith("AMS 槽 1 白色 PLA · 槽 2 黑色 PLA"), f"job colours {production.ams_text(cols)}")
job = production.create_job(PID, "3DP0002-WH", 2, kind="stock", user="boss")
production.schedule()
jl = next(x for x in production.list_jobs() if x["id"] == job["id"])
ok(jl["printer"] == 0 and "AMS 槽 1" in jl.get("ams_line", "") and "ช่อง" in jl.get("ams_line_th", ""), f"multi-colour job → P1S, card shows AMS line {jl.get('printer')}")
save_config({"printers": [dict(prs[0], enabled=False), prs[1]]})
production.schedule()
ok(next(x for x in production.list_jobs() if x["id"] == job["id"])["printer"] is None, "no AMS printer available → not assigned to K1C")
save_config({"printers": [prs[0], dict(prs[1], ams=True)]})
production.schedule()
ok(next(x for x in production.list_jobs() if x["id"] == job["id"])["printer"] in (0, 1), "K1C flagged as multicolour → assignable")
save_config({"printers": prs})
try:
    production.start_run(job["id"], 1, 2, send=False, user="boss", confirm={"bed_clear": True, "material": True})
    ok(False, "K1C must refuse multi-colour job")
except ValueError as e:
    ok("AMS" in str(e), f"start on K1C refused: {e}")
so = production.send_options(job["id"], 0)
ok(len(so["colours"]) == 2, "send options list AMS colours")
cf = db.conn()
def g_of(col):
    r = cf.execute("SELECT kg FROM inventory WHERE material='PLA' AND color=?", (col,)).fetchone()
    return float(r["kg"]) * 1000 if r else 0.0
w0, b0 = g_of("白色"), g_of("黑色")
rr = production.start_run(job["id"], 0, 2, send=False, user="boss", confirm={"bed_clear": True, "material": True})
ok(rr["colours"] and len(rr["colours"]) == 2, f"run records colours {rr['colours']}")
production.finish_run(rr["run_id"], "boss")
w1, b1 = g_of("白色"), g_of("黑色")
exp = {c["colour"]: c["grams"] for c in rr["colours"]}
ok(abs((w0 - w1) - exp["白色"] * (1 + 0.05)) < 1.5 and abs((b0 - b1) - exp["黑色"] * (1 + 0.05)) < 1.5 and (b0 - b1) > 0, f"stock deducted per colour white {w0 - w1:.1f} black {b0 - b1:.1f} exp {exp}")
# 单色产品照旧
job2 = production.create_job(PID, "3DP0002-WH-L", 1, kind="stock", user="boss")
ok("ams_line" not in next(x for x in production.list_jobs() if x["id"] == job2["id"]), "single-colour job has no AMS line")

# ---------- 组合摆盘：规则（AI 关着）+ AI（假的 ai_copy.call） ----------
kp = {"id": "k1", "printer": "Bambu Lab P1S", "layer_height": 0.2, "sets": 1, "slots": [{"slot": 1, "material": "PLA"}],
      "items": [{"uid": "u1", "id": K3, "part": 2, "orient": "bottom"}, {"uid": "u2", "id": CUBE, "orient": "bottom"},
                {"uid": "u3", "id": K3, "part": 0, "orient": "bottom"}, {"uid": "u4", "id": CUBE, "orient": "bottom"},
                {"uid": "u5", "id": K3, "part": 1, "orient": "bottom"}]}
save_config({"ai_api_key": ""})
r = C.post(f"/api/products/{PID}/print-plan/kit", json={"plate": kp}).get_json()
ok(r["source"] == "rules" and r["check"]["ok"], f"kit layout rules-only when AI off {r.get('error') or r['note_zh']}")
order = [g["name"] for g in r["groups"]]
ok(order.index("base") < order.index("body") < order.index("head") and any(g["uids"] == ["u2", "u4"] for g in r["groups"]), f"rules group + assembly order {r['groups']}")
pos = {i["uid"]: (i["x"], i["y"]) for i in r["plate"]["items"]}
ok(pos["u2"][1] == pos["u4"][1] and pos["u3"][1] < pos["u5"][1] < pos["u1"][1], f"groups in rows, base first {pos}")
ok(pp._base_name("arm_left.stl") == pp._base_name("Arm R") == "arm", "left / right pairs share a group")
from core import ai_copy
_call = ai_copy.call
seen = {}
def fake_ai(cfg, system, user, image_b64=None):
    seen["user"] = user; seen["sys"] = system; seen["img"] = image_b64
    if "组装" in system and "pos" in user:
        return json.dumps({"parts": [{"index": 0, "pos": [0, 0, 2.5], "rot": [0, 0, 0]}, {"index": 1, "pos": [0, 0, 20], "rot": [0, 0, 90]},
                                     {"index": 2, "pos": [0, 0, 45], "rot": [10, 0, 0]}, {"index": 9, "pos": [1, 1, 1]}], "note_zh": "头在最上面", "note_th": "หัวอยู่บนสุด"})
    return json.dumps({"groups": [{"name_zh": "主体", "uids": ["u3", "u5", "u1"], "rot": {"u5": 90}}, {"name_zh": "配件", "uids": ["u2", "u4", "zzz"]}],
                       "note_zh": "底座、身体、头一列", "note_th": "..."})
ai_copy.call = fake_ai
save_config({"ai_api_key": "k", "ai_provider": "anthropic"})
p = store.load(PID); p.setdefault("source", {}); p["source"] = dict(p.get("source") or {}, description_original="Assemble: put the body on the base, then the head.", tags="figure,kit"); store.save(p)
r = C.post(f"/api/products/{PID}/print-plan/kit", json={"plate": kp, "ai": True}).get_json()
ok(r["source"] == "ai" and [g["uids"] for g in r["groups"]] == [["u3", "u5", "u1"], ["u2", "u4"]] and r["check"]["ok"], f"kit layout from AI {r.get('groups')}")
ok("put the body on the base" in seen["user"] and "u5" in seen["user"], "AI gets description + part list")
ok(next(i for i in r["plate"]["items"] if i["uid"] == "u5")["rot"] == 90, "AI rotation applied")
def bad_ai(cfg, system, user, image_b64=None):
    return "not json"
ai_copy.call = bad_ai
r = C.post(f"/api/products/{PID}/print-plan/kit", json={"plate": kp}).get_json()
ok(r["source"] == "rules" and "AI 没成功" in r["note_zh"] and r["check"]["ok"], "AI failure falls back to rules")

# ---------- 展示模型：组装姿势保存 / 读取，AI 按图片组装 ----------
specmodel.map_spec(PID, "大号", "", "boss")
p = store.load(PID); p["model"] = dict(p.get("model") or {}, lib_id=K3); store.save(p)
d = C.get(f"/api/products/{PID}/display").get_json()
ok(len(d["parts"]) == 3 and not d["has_pose"] and d["parts"][2]["pos"] == d["parts"][2]["center"], f"display parts default pose {d.get('error')}")
ok(asm.assembled_tris(PID) is None, "no pose → original model used")
pose = [{"index": 0, "pos": [0, 0, 2.5], "rot": [0, 0, 0]}, {"index": 1, "pos": [0, 0, 20], "rot": [0, 0, 0]}, {"index": 2, "pos": [0, 0, 45], "rot": [0, 0, 45], "colour": "黑色"}]
d = C.post(f"/api/products/{PID}/display", json={"parts": pose}).get_json()
ok(d["has_pose"] and d["parts"][2]["rot"] == [0, 0, 45] and d["parts"][2]["colour"] == "黑色", "assembly pose saved")
d = C.get(f"/api/products/{PID}/display").get_json()
ok(d["parts"][1]["pos"] == [0, 0, 20], "assembly pose loaded")
t = asm.assembled_tris(PID).reshape(-1, 3)
ok(abs(t[:, 2].max() - 55) < 0.3 and abs(t[:, 0].max() - 30) < 0.3, f"assembled model stacked (height 55, base 60 wide) {t.max(0)}")
ok(C.get(f"/api/products/{PID}/display/stl").status_code == 200 and C.get(f"/api/products/{PID}/display/part/1").status_code == 200, "assembled STL + part mesh endpoints")
ok(store.load(PID).get("display") and "display" in C.get(f"/api/products/{PID}").get_json(), "pose stored in product")
from PIL import Image
buf = io.BytesIO(); Image.new("RGB", (64, 64), (200, 50, 50)).save(buf, "JPEG"); jpg = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
ai_copy.call = fake_ai
r = C.post(f"/api/products/{PID}/display/ai", json={"renders": {"0": [jpg, jpg], "1": [jpg], "2": [jpg]}}).get_json()
ok([x["index"] for x in r["parts"]] == [0, 1, 2] and r["parts"][1]["rot"] == [0, 0, 90] and r["note_zh"] == "头在最上面", f"AI assembly draft {r}")
ok(seen["img"] and "size_mm" in seen["user"], "AI gets a contact sheet image + part boxes")
ok(C.get(f"/api/products/{PID}/display").get_json()["parts"][1]["rot"] == [0, 0, 0], "AI result is not saved automatically")
save_config({"ai_provider": "deepseek"})
r = C.post(f"/api/products/{PID}/display/ai", json={"renders": {"0": [jpg]}})
ok(r.status_code == 400 and "DeepSeek" in r.get_json()["error"], "DeepSeek (no vision) explained")
ai_copy.call = _call
save_config({"ai_provider": "anthropic", "ai_api_key": ""})
ok(C.delete(f"/api/products/{PID}/display").get_json()["has_pose"] is False, "pose reset")

print("ERRORS", E_)
sys.exit(1 if E_ else 0)
