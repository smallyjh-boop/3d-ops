# v2.54.0：几百到几千台打印机——机型模板 + 单台覆盖（切片核对照样严格）、厂家表单校验、稳定 id、分组 / 位置 / 用途、
# 局域网发现（假设备）、Excel / CSV 导入、批量操作、迁移、1000 台连接管理压力测试、后台进程模式
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, json, time, socket, asyncio, subprocess, threading, sqlite3, io
D = T + "/m_fleet254"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m, flush=True); E_ += (not b)
import app as A
from core import db, config, fleet, production, printers as pr, printer_manager as pm, printer_discovery as disc
from modules.prod import slicecheck

CFGP = D + "/config.json"
def raw():
    return json.load(open(CFGP, encoding="utf-8"))
def write_raw(d):
    json.dump(d, open(CFGP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ================= 1 迁移：同机型一样的值 → 模板；不一样的 → 单台覆盖；备注像位置 → 位置；连接保留 =================
r0 = raw()
legacy = [
    {"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "nozzle": 0.4, "plate": "Textured PEI Plate", "ams": True, "enabled": True,
     "orca_machine": "Bambu Lab P1S 0.4 nozzle", "orca_process": "0.20mm Standard @BBL X1C", "orca_filament": "Bambu PLA Basic @BBL X1C",
     "note": "A-03-2", "conn": {"type": "bambu", "host": "192.168.31.166", "serial": "01P00A123456789", "access_code": "12345678"}},
    {"code": "P1S-02", "name": "Bambu Lab P1S", "g_per_h": 22, "nozzle": 0.6, "plate": "Textured PEI Plate", "ams": True, "enabled": True,
     "orca_machine": "Bambu Lab P1S 0.4 nozzle", "orca_process": "0.20mm Standard @BBL X1C", "orca_filament": "Bambu PLA Basic @BBL X1C",
     "note": "新买的", "conn": {"type": "none"}},
    {"code": "K1M-01", "name": "Creality K1 Max", "g_per_h": 20, "nozzle": 0.4, "plate": "", "enabled": True, "note": "2 号货架",
     "conn": {"type": "creality", "host": "192.168.31.170"}},
    {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "nozzle": 0.4, "plate": "", "enabled": False, "conn": {"type": "auto", "host": "192.168.31.171"}},
]
r0["printers"] = legacy; r0.pop("_fleet254", None); r0.pop("printer_models", None)
write_raw(r0)
cfg = config.load_config()
rr = raw()
tp = rr.get("printer_models") or {}
ok(rr.get("_fleet254") is True, "migration flag persisted")
ok(tp.get("Bambu Lab P1S", {}).get("plate") == "Textured PEI Plate" and tp["Bambu Lab P1S"].get("orca_machine") == "Bambu Lab P1S 0.4 nozzle"
   and tp["Bambu Lab P1S"].get("ams") is True, f"identical P1S values -> template {tp.get('Bambu Lab P1S')}")
ok("nozzle" not in tp["Bambu Lab P1S"], "P1S nozzle differs -> not in template")
sp = rr["printers"]
ok(sp[0]["ovr"] == {"nozzle": 0.4} and sp[1]["ovr"] == {"nozzle": 0.6}, f"different nozzle kept per printer {sp[0]['ovr']} {sp[1]['ovr']}")
ok(all(f not in sp[i] for i in range(4) for f in fleet.TPL_FIELDS), "stored form has no template fields (only ovr)")
ok(tp.get("Creality K1 Max", {}).get("nozzle") == 0.4 and tp["Creality K1 Max"].get("g_per_h") == 20.0, "single printer model -> all values template")
eff = cfg["printers"]
for i, lp in enumerate(legacy):
    same = all(fleet.clean_value(f, lp.get(f)) == eff[i].get(f) for f in fleet.TPL_FIELDS if fleet.clean_value(f, lp.get(f)) is not None)
    ok(same, f"effective values unchanged after migration: {lp['code']}")
ok(eff[0]["conn"]["access_code"] == "12345678" and eff[2]["conn"]["host"] == "192.168.31.170", "connections kept")
ok(eff[0]["location"] == "A-03-2" and eff[2]["location"] == "2 号货架" and eff[1]["location"] == "", "note that looks like location -> location")
ok(all(p["role"] == "any" and p["group"] == "" and p["dedicated_po"] == "" and p["paused"] is False for p in eff), "new field defaults")
ids = [p["id"] for p in eff]
ok(len(set(ids)) == 4 and all(x.startswith("p") for x in ids), "stable ids assigned")
ok([p["id"] for p in config.load_config()["printers"]] == ids, "ids stable across loads")
ok(eff[3]["enabled"] is False, "enabled kept")

# ================= 2 模板 + 单台覆盖 → 切片核对 / 切片配置 / 多色 都用同一个读法 =================
def F(noz, prof="Bambu Lab P1S 0.4 nozzle", bed="Textured PEI Plate"):
    return {"id": 1, "kind": "3mf", "printer": "", "filename": "x.gcode.3mf",
            "report": {"params": {"printer_profile": prof, "nozzle_mm": noz, "bed_type": bed}}}
ok(slicecheck.check(F(0.4), 0)["ok"], "P1S-01 (override 0.4) accepts 0.4 file")
ok(not slicecheck.check(F(0.6), 0)["ok"], "P1S-01 rejects 0.6 file")
ok(slicecheck.check(F(0.6), 1)["ok"] and not slicecheck.check(F(0.4), 1)["ok"], "P1S-02 override 0.6 used by slicecheck")
ok(not slicecheck.check(F(0.4, bed="Cool Plate"), 0)["ok"], "template plate checked (Cool Plate rejected)")
ok(not slicecheck.check(F(0.4, prof="Creality K1C 0.4 nozzle"), 0)["ok"], "wrong model still rejected")
ok(not slicecheck.check({"id": 2, "kind": "3mf", "report": {"params": {"nozzle_mm": 0.4}}}, 0)["ok"], "unknown model still needs confirm (strict)")
# 改模板：P1S 模板加 0.4 喷嘴 → P1S-01 的覆盖还在（明确设置的），改模板热床板 → 两台都跟着变
C = A.app.test_client()
r = C.post("/api/fleet/templates", json={"templates": {"Bambu Lab P1S": {"nozzle": "0.4", "plate": "Smooth PEI Plate", "ams": "false"}}})
ok(r.status_code == 200, f"save template {r.status_code} {r.get_json() if r.status_code != 200 else ''}")
ok(not slicecheck.check(F(0.4), 0)["ok"] and slicecheck.check(F(0.4, bed="Smooth PEI Plate"), 0)["ok"], "template plate change applies to P1S-01")
ok(slicecheck.check(F(0.6, bed="Smooth PEI Plate"), 1)["ok"], "P1S-02 still uses its 0.6 override after template change")
ok(fleet.is_multicolor(config.load_config()["printers"][0]) is False, "is_multicolor follows template ams=false")
ok(fleet.is_multicolor({"name": "Bambu Lab P1S"}) is False, "is_multicolor on raw dict also resolves template")
ok(fleet.is_multicolor({"name": "Bambu Lab P1S", "ams": True}) is True, "explicit ams on dict wins")
r = C.post("/api/fleet/templates", json={"templates": {"Bambu Lab P1S": {"nozzle": "abc"}}})
ok(r.status_code == 400, "bad template value rejected")
# 单台覆盖接口：P1S-01 设 0.6 → 核对跟着变；清空 → 跟模板
r = C.post("/api/fleet/printers/" + ids[0], json={"ovr": {"nozzle": "0.6"}})
ok(r.status_code == 200 and slicecheck.check(F(0.6, bed="Smooth PEI Plate"), 0)["ok"], "override via API used by slicecheck")
r = C.post("/api/fleet/printers/" + ids[0], json={"ovr": {"nozzle": ""}})
ok(slicecheck.check(F(0.4, bed="Smooth PEI Plate"), 0)["ok"] and not slicecheck.check(F(0.6, bed="Smooth PEI Plate"), 0)["ok"], "cleared override -> template 0.4")
d = r.get_json()
ok({f["key"]: f["template"] for f in d["fields"]}["plate"] == "Smooth PEI Plate", "detail shows template values")
# 旧代码直接改 p["nozzle"] 再保存 → 也算覆盖
c2 = config.load_config(); c2["printers"][2]["nozzle"] = 0.8; config.save_config({"printers": c2["printers"]})
ok(raw()["printers"][2]["ovr"].get("nozzle") == 0.8 and config.load_config()["printers"][2]["nozzle"] == 0.8, "legacy direct field write -> override")
c2 = config.load_config(); c2["printers"][2]["nozzle"] = 0.4; config.save_config({"printers": c2["printers"]})
# 切片配置（resolve_profiles）也用 effective：没装 Orca 时只核对读法
p_eff = fleet.effective(raw()["printers"][0], config.load_config())
ok(p_eff.get("orca_machine") == "Bambu Lab P1S 0.4 nozzle", "effective() gives template orca profile for slicer")
src = open(APP + "/core/slicer.py", encoding="utf-8").read()
ok("fleet.effective(printers[printer_index], cfg)" in src, "slicer.resolve_profiles uses fleet.effective")

# ================= 3 厂家表单校验 + 添加 / 修改接口 =================
cc, e = fleet.validate_conn("bambu", {"host": "192.168.1.300", "serial": "", "access_code": "x"})
ok(len(e) == 3, f"bambu: bad ip + missing serial + bad code {e}")
cc, e = fleet.validate_conn("bambu", {"host": "192.168.1.50", "serial": "01p00a000000001", "access_code": "12345678"})
ok(not e and cc["serial"] == "01P00A000000001" and cc["type"] == "bambu", "bambu ok + serial upper")
cc, e = fleet.validate_conn("creality", {"host": "192.168.1.60", "serial": "ignored"})
ok(not e and cc["serial"] == "" and cc["type"] == "creality", "creality: only IP")
ok(fleet.validate_conn("moonraker", {"host": "k1.local", "port": "99999"})[1], "moonraker bad port")
ok(not fleet.validate_conn("moonraker", {"host": "k1.local", "port": ""})[1], "moonraker port optional, hostname ok")
ok(fleet.validate_conn("nope", {})[1], "unknown vendor rejected")
cc, e = fleet.validate_conn("bambu", {"host": "192.168.1.50", "serial": "01P00A000000001", "access_code": "******"}, {"type": "bambu", "access_code": "87654321"})
ok(not e and cc["access_code"] == "87654321", "masked access code keeps old")
ok(set(fleet.vendors_for("Bambu Lab P1S")) == {"bambu", "moonraker", "none"} and "creality" in fleet.vendors_for("Creality K1C"), "vendors per brand")
ok("creality" not in fleet.vendors_for("Bambu Lab P1S"), "bambu model has no creality form")
r = C.post("/api/fleet/printers", json={"name": "Bambu Lab P1S", "vendor": "bambu", "conn": {"host": "192.168.1.80"}})
ok(r.status_code == 400 and "序列号" in r.get_json()["error"], "add bambu without serial -> 400")
r = C.post("/api/fleet/printers?lang=th", json={"name": "Bambu Lab P1S", "vendor": "bambu", "conn": {"host": "192.168.1.80"}})
ok(r.status_code == 400 and "ซีเรียล" in r.get_json()["error"], "error in Thai with lang=th")
r = C.post("/api/fleet/printers", json={"name": "Bambu Lab P1S", "vendor": "bambu", "group": "A 区", "location": "A-01-1", "role": "orders",
                                        "conn": {"host": "192.168.1.80", "serial": "01P00A000000080", "access_code": "11112222"}})
ok(r.status_code == 200 and r.get_json()["codes"] == ["P1S-003"], f"add with auto code (P1S-01/02 taken) {r.get_json()}")
new_id = r.get_json()["added"][0]
d = C.get("/api/fleet/printers/" + new_id).get_json()
ok(d["printer"]["conn"]["access_code"] == "******" and d["vendor"] == "bambu" and d["printer"]["group"] == "A 区" and d["printer"]["role"] == "orders", "detail masks code + new fields")
ok(d["row"]["index"] == 4, "new printer appended (existing indices unchanged)")
r = C.post("/api/fleet/printers", json={"name": "Creality K1C", "vendor": "creality", "conn": {"host": "192.168.1.80"}})
ok(r.status_code == 400 and "192.168.1.80" in r.get_json()["error"], "duplicate IP rejected")
r = C.post("/api/fleet/printers", json={"name": "Nonexistent 3000"})
ok(r.status_code == 400, "unknown model rejected")
r = C.post("/api/fleet/printers", json={"name": "Creality K1C", "n": 3, "group": "B 区"})
ok(r.status_code == 200 and r.get_json()["codes"] == ["K1C-002", "K1C-003", "K1C-004"], f"bulk add 3 {r.get_json().get('codes')}")
r = C.post("/api/fleet/printers/" + new_id, json={"vendor": "bambu", "conn": {"host": "192.168.1.81", "serial": "01P00A000000080", "access_code": "******"}})
ok(r.status_code == 200 and config.load_config()["printers"][4]["conn"]["access_code"] == "11112222" and r.get_json()["printer"]["conn"]["host"] == "192.168.1.81",
   "edit conn keeps masked access code")
r = C.post("/api/fleet/printers/" + new_id, json={"code": "K1C-002"})
ok(r.status_code == 400, "duplicate code on edit rejected")
r = C.post("/api/fleet/printers/" + new_id, json={"role": "bogus"})
ok(r.status_code == 400, "bad role rejected")

# ================= 4 稳定 id：删除时任务 / 记录 / 状态按 id 对到新位置；改编码不算删除 =================
cfg = config.load_config(); prs = cfg["printers"]
codes = [p["code"] for p in prs]
idx_k1c2 = codes.index("K1C-003")
dbc = db.conn()
jid = production.create_job("3DP0001", "3DP0001-WH", 1, "stock")
jid = jid["id"] if isinstance(jid, dict) else jid
dbc.execute("UPDATE jobs SET printer=?, pin=1 WHERE id=?", (idx_k1c2, jid)); dbc.commit()
dbc.execute("INSERT INTO maintenance(printer, item, ts, hours_at, username, note) VALUES(?, 'clean', ?, 0, 't', '')", (idx_k1c2, time.time())); dbc.commit()
pr._status.clear(); pr._status[idx_k1c2] = {"state": "idle", "x": "k1c2"}
r = C.delete("/api/fleet/printers/" + prs[idx_k1c2 - 1]["id"])          # 删前面一台（K1C-002）
ok(r.status_code == 200, "delete printer")
cfg = config.load_config(); prs2 = cfg["printers"]
j = dbc.execute("SELECT printer FROM jobs WHERE id=?", (jid,)).fetchone()
ok(prs2[j["printer"]]["code"] == "K1C-003", f"job follows printer id after delete ({j['printer']})")
m = dbc.execute("SELECT printer FROM maintenance WHERE note='' AND username='t'").fetchone()
ok(prs2[m["printer"]]["code"] == "K1C-003", "maintenance follows")
ok(pr.get_status(idx_k1c2 - 1).get("x") == "k1c2", "status cache moved to new index (not cleared)")
ok(fleet.index_of(prs2, prs[idx_k1c2]["id"]) == idx_k1c2 - 1 and fleet.index_of(prs2, "k1c-003") == idx_k1c2 - 1 and fleet.index_of(prs2, "0") == 0, "index_of id/code/index")
# 改编码：同一台（id 不变），装着的料卷跟着换编码
k2 = prs2[idx_k1c2 - 1]
has_sp = dbc.execute("SELECT 1 FROM sqlite_master WHERE name='spools'").fetchone()
if has_sp:
    dbc.execute("INSERT INTO spools(material, color, status, printer, updated_at) VALUES('PLA', 'WH', 'loaded', 'K1C-003', ?)", (time.time(),)); dbc.commit()
r = C.post("/api/fleet/printers/" + k2["id"], json={"code": "K1C-099"})
ok(r.status_code == 200 and config.load_config()["printers"][idx_k1c2 - 1]["id"] == k2["id"], "rename keeps id + index")
if has_sp:
    ok(dbc.execute("SELECT COUNT(*) FROM spools WHERE printer='K1C-099' AND status='loaded'").fetchone()[0] == 1, "spool follows renamed code")
j = dbc.execute("SELECT printer FROM jobs WHERE id=?", (jid,)).fetchone()
ok(j["printer"] == idx_k1c2 - 1, "job untouched by rename")
# 旧的 设置 → /api/config 保存打印机：新字段、id、单台覆盖都保留
before = config.load_config()["printers"]
C.post("/api/fleet/printers/" + before[0]["id"], json={"group": "A 区", "paused": True, "dedicated_po": "PO-7", "ovr": {"nozzle": "0.6"}})
before = config.load_config()["printers"]
legacy_rows = [{k: v for k, v in p.items() if k in ("code", "name", "g_per_h", "nozzle", "plate", "enabled", "note", "orca_machine", "orca_process", "orca_filament", "tech")} for p in before]
r = C.post("/api/config", json={"printers": legacy_rows})
after = config.load_config()["printers"]
ok(r.status_code == 200 and [p["id"] for p in after] == [p["id"] for p in before], "legacy settings save keeps ids")
ok(after[0]["group"] == "A 区" and after[0]["paused"] is True and after[0]["dedicated_po"] == "PO-7" and after[0]["nozzle"] == 0.6, "legacy save keeps new fields + override")
ok(raw()["printers"][1]["ovr"].get("nozzle") == 0.6 and "plate" not in raw()["printers"][1]["ovr"], "legacy save does not turn template values into overrides")

# ================= 5 批量操作 =================
prs = config.load_config()["printers"]
sel = [p["id"] for p in prs if p["code"].startswith("K1C")]
def bulk(**b):
    r = C.post("/api/fleet/bulk", json=b); return r.status_code, r.get_json()
ok(bulk(ids=sel, action="disable")[0] == 200 and all(not p["enabled"] for p in config.load_config()["printers"] if p["id"] in sel), "bulk disable")
ok(bulk(ids=sel, action="enable")[0] == 200 and all(p["enabled"] for p in config.load_config()["printers"] if p["id"] in sel), "bulk enable")
ok(bulk(ids=sel, action="pause")[0] == 200 and all(p["paused"] for p in config.load_config()["printers"] if p["id"] in sel), "bulk pause intake")
ok(bulk(group="B 区", action="resume")[0] == 200 and all(not p["paused"] for p in config.load_config()["printers"] if p["group"] == "B 区"), "bulk resume by group")
ok(bulk(ids=sel, action="role", value="stock")[0] == 200 and all(p["role"] == "stock" for p in config.load_config()["printers"] if p["id"] in sel), "bulk role")
ok(bulk(ids=sel, action="role", value="nope")[0] == 400, "bulk bad role")
ok(bulk(ids=sel, action="group", value="C 区")[0] == 200 and all(p["group"] == "C 区" for p in config.load_config()["printers"] if p["id"] in sel), "bulk group")
ok(bulk(ids=sel, action="location", value="C-01")[0] == 200, "bulk location")
ok(bulk(ids=sel, action="nozzle", value="0.6")[0] == 200 and all(p["nozzle"] == 0.6 and p["ovr"].get("nozzle") == 0.6 for p in config.load_config()["printers"] if p["id"] in sel), "bulk nozzle override")
ok(bulk(ids=sel, action="nozzle", value="")[0] == 200 and all("nozzle" not in p["ovr"] for p in config.load_config()["printers"] if p["id"] in sel), "bulk nozzle back to template")
ok(bulk(ids=sel, action="plate", value="Cool Plate")[0] == 200 and all(p["plate"] == "Cool Plate" for p in config.load_config()["printers"] if p["id"] in sel), "bulk plate override")
ok(bulk(ids=sel, action="dedicate", value="PO-12")[0] == 200 and all(p["dedicated_po"] == "PO-12" for p in config.load_config()["printers"] if p["id"] in sel), "bulk dedicate")
ok(bulk(ids=sel, action="dedicate", value="")[0] == 200 and all(p["dedicated_po"] == "" for p in config.load_config()["printers"] if p["id"] in sel), "bulk un-dedicate")
ok(bulk(action="enable")[0] == 400 and bulk(ids=sel, action="explode")[0] == 400, "bulk needs selection / known action")
st, j = bulk(ids=sel, action="test")
ok(st == 200 and len(j["results"]) == len(sel) and all(not x["ok"] for x in j["results"]), "bulk test (no connection set) reports per printer")
s, j = C.get("/api/fleet?group=C 区").status_code, C.get("/api/fleet?group=C%20%E5%8C%BA").get_json()
ok(j["total"] == len(sel) and all(r["role"] == "stock" for r in j["rows"]), "overview filter by group")

# ================= 6 导入（CSV / Excel） =================
csv = ("编码,机型,IP,序列号,访问码,分组,位置\n"
       ",Bambu Lab P1S,192.168.2.10,01P00A000000210,12345678,D 区,D-01-1\n"
       ",P1S,192.168.2.11,01P00A000000211,12345678,D 区,D-01-2\n"
       "X-1,Bambu Lab P1S,192.168.2.300,,,D 区,\n"
       ",Unknown Printer 9,192.168.2.13,,,,\n"
       ",Creality K1C,192.168.1.81,,,,\n"
       ",Creality K1C,192.168.2.14,,,D 区,D-02-1\n")
r = C.post("/api/fleet/import", data={"file": (io.BytesIO(csv.encode("utf-8")), "p.csv")}, content_type="multipart/form-data")
j = r.get_json()
ok(r.status_code == 200 and j["ok"] == 3 and j["bad"] == 3, f"csv preview ok/bad {j.get('ok')}/{j.get('bad')}")
ok(j["rows"][0]["printer"]["code"] == "P1S-004" and j["rows"][1]["printer"]["code"] == "P1S-005", f"auto codes continue {[x['printer']['code'] for x in j['rows']]}")
ok(any("IP" in e[0] for e in j["rows"][2]["errors"]) and any("序列号" in e[0] for e in j["rows"][2]["errors"]), "bad ip + missing serial reported")
ok(any("机型" in e[0] for e in j["rows"][3]["errors"]), "unknown model reported")
ok(any("192.168.1.81" in e[0] for e in j["rows"][4]["errors"]), "existing IP reported")
ok(j["rows"][0]["printer"]["conn"]["access_code"] == "******", "preview masks access code")
n0 = len(config.load_config()["printers"])
r = C.post("/api/fleet/import?commit=1", data={"file": (io.BytesIO(csv.encode("utf-8")), "p.csv")}, content_type="multipart/form-data")
ok(r.status_code == 400 and len(config.load_config()["printers"]) == n0, "commit with bad rows adds nothing")
good = "\n".join([l for i, l in enumerate(csv.strip().split("\n")) if i in (0, 1, 2, 6)])
r = C.post("/api/fleet/import?commit=1", data={"file": (io.BytesIO(good.encode("utf-8")), "p.csv")}, content_type="multipart/form-data")
ok(r.status_code == 200 and len(r.get_json()["added"]) == 3 and len(config.load_config()["printers"]) == n0 + 3, "commit valid rows")
last = config.load_config()["printers"][-3:]
ok(last[0]["conn"]["access_code"] == "12345678" and last[0]["group"] == "D 区" and last[0]["location"] == "D-01-1" and last[2]["conn"]["type"] == "creality", "imported fields")
import openpyxl
wb = openpyxl.Workbook(); ws = wb.active
ws.append(["code", "model", "ip", "serial", "access code", "group", "location"])
ws.append(["MR-01", "Creality K1 Max", "192.168.2.20", "", "", "E", "E-1"])
bio = io.BytesIO(); wb.save(bio)
r = C.post("/api/fleet/import", data={"file": (io.BytesIO(bio.getvalue()), "p.xlsx")}, content_type="multipart/form-data")
ok(r.status_code == 200 and r.get_json()["ok"] == 1 and r.get_json()["rows"][0]["printer"]["code"] == "MR-01", "xlsx preview")
r = C.post("/api/fleet/import", data={"file": (io.BytesIO(b"a,b\n1,2\n"), "p.csv")}, content_type="multipart/form-data")
ok(r.status_code == 400, "csv without model column rejected")
ok(C.get("/api/fleet/import-template").status_code == 200, "import template download")

# ================= 7 局域网发现（假设备） =================
NOTIFY = ("NOTIFY * HTTP/1.1\r\nHOST: 239.255.255.250:1990\r\nServer: UPnP/1.0\r\nLocation: 192.168.2.50\r\nNT: urn:bambulab-com:device:3dprinter:1\r\n"
          "USN: 01P00A000000250\r\nDevModel.bambu.com: C12\r\nDevName.bambu.com: P1S-shop\r\nDevConnect.bambu.com: lan\r\nDevBind.bambu.com: free\r\n\r\n")
d0 = disc.parse_ssdp(NOTIFY)
ok(d0 and d0["ip"] == "192.168.2.50" and d0["serial"] == "01P00A000000250" and d0["model"] == "Bambu Lab P1S" and d0["lan_mode"] is True, f"parse ssdp {d0}")
ok(disc.parse_ssdp("HTTP/1.1 200 OK\r\nServer: Linux UPnP\r\n\r\n") is None, "non-bambu ssdp ignored")
ok(disc.parse_ssdp(NOTIFY.replace("C12", "N2S").replace("lan", "cloud"))["model"] == "Bambu Lab A1" and
   disc.parse_ssdp(NOTIFY.replace("lan", "cloud"))["lan_mode"] is False, "model code map + cloud mode")
# 真的 UDP：本机端口收到一条广播
ls = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); ls.bind(("127.0.0.1", 0)); lport = ls.getsockname()[1]; ls.close()
def sender():
    time.sleep(0.4)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.sendto(NOTIFY.encode(), ("127.0.0.1", lport)); s.close()
threading.Thread(target=sender).start()
def mk(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind(("127.0.0.1", port)); return s
got = disc.listen_ssdp(1.5, ports=(lport,), sock_factory=mk)
ok("192.168.2.50" in got and got["192.168.2.50"]["serial"] == "01P00A000000250", "listen_ssdp receives real UDP packet")
OPEN = {("10.5.0.7", 9999), ("10.5.0.8", 7125), ("10.5.0.9", 8883), ("192.168.1.81", 8883), ("192.168.2.50", 8883)}
calls = {"n": 0, "max": 0, "cur": 0}
async def fconnect(host, port, timeout):
    calls["n"] += 1; calls["cur"] += 1; calls["max"] = max(calls["max"], calls["cur"])
    await asyncio.sleep(0.005)
    calls["cur"] -= 1
    return (host, port) in OPEN
hosts = [f"10.5.0.{i}" for i in range(1, 255)] + ["192.168.1.81", "192.168.2.50"]
t0 = time.time()
res = disc.scan(hosts, connect=fconnect, concurrency=32)
ok(set(res) == {"10.5.0.7", "10.5.0.8", "10.5.0.9", "192.168.1.81", "192.168.2.50"}, f"scan finds open hosts {sorted(res)}")
ok(res["10.5.0.7"]["vendor"] == "creality" and res["10.5.0.8"]["vendor"] == "moonraker" and res["10.5.0.9"]["vendor"] == "bambu", "vendor guess by port")
ok(calls["max"] <= 32 and calls["n"] == len(hosts) * 4, f"bounded concurrency {calls['max']} / {calls['n']} probes")
r = disc.discover(config.load_config(), ssdp={"192.168.2.50": d0}, scan_hosts=hosts, connect=fconnect)
byip = {x["ip"]: x for x in r["devices"]}
ok(byip["192.168.2.50"]["serial"] == "01P00A000000250" and byip["192.168.2.50"]["source"] == "ssdp", "ssdp + scan merged by ip")
ok(byip["192.168.1.81"]["exists"] == "P1S-003" and not byip["10.5.0.9"]["exists"], "already-configured device marked")
ok(len(disc.hosts_of([__import__("ipaddress").ip_network("10.0.0.0/16")])) == disc.MAX_HOSTS, "subnet scan capped")
# 接口：只有老板；用假的扫描
orig_d = disc.discover
disc.discover = lambda cfg, secs, scan_hosts=None: orig_d(cfg, ssdp={"192.168.2.50": d0}, scan_hosts=hosts, connect=fconnect)
r = C.post("/api/fleet/discover", json={"seconds": 1})
ok(r.status_code == 200 and any(x["ip"] == "192.168.2.50" and x["code_suggest"] for x in r.get_json()["devices"]), "discover API")
ok(C.post("/api/fleet/discover", json={"cidr": "10.0.0.0/8"}).status_code == 400, "discover rejects huge subnet")
r = C.post("/api/fleet/add-many", json={"devices": [{"ip": "192.168.2.50", "serial": "01P00A000000250", "model": "Bambu Lab P1S", "vendor": "bambu", "access_code": "abcd1234", "group": "F"},
                                                     {"ip": "10.5.0.7", "model": "Creality K1C", "vendor": "creality", "group": "F"}]})
ok(r.status_code == 200 and len(r.get_json()["added"]) == 2, f"add discovered devices {r.get_json()}")
r = C.post("/api/fleet/add-many", json={"devices": [{"ip": "10.5.0.8", "model": "Creality K1 Max", "vendor": "moonraker"}, {"ip": "10.5.0.7", "model": "Creality K1C", "vendor": "creality"}]})
ok(r.status_code == 400 and len(r.get_json()["rows"]) == 2, "add-many all-or-nothing on duplicate")
disc.discover = orig_d

# ================= 8 权限：生产员工能看不能改 =================
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pong", "secret123", "production", "Pong")
def login(u):
    c = A.app.test_client(); c.post("/api/auth/login", json={"username": u, "password": "secret123"}); return c
P = login("pong"); B = login("boss")
ok(P.get("/api/fleet").status_code == 200, "production can view overview")
ok(P.get("/api/fleet/printers/" + ids[0]).status_code == 200 and P.get("/api/fleet/printers/" + ids[0]).get_json()["printer"]["conn"].get("access_code", "") == "", "production sees no access code")
ok(P.post("/api/fleet/printers/" + ids[0], json={"group": "X"}).status_code == 403, "production cannot edit")
ok(P.post("/api/fleet/bulk", json={"ids": [ids[0]], "action": "disable"}).status_code == 403, "production cannot bulk")
ok(P.post("/api/fleet/discover", json={}).status_code == 403 and P.post("/api/fleet/import").status_code == 403, "production cannot discover / import")
ok(P.get("/print/fleet-labels?ids=" + ids[0]).status_code == 200, "production can print labels")
html = B.get("/print/fleet-labels").get_data(as_text=True)
ok(html.count('class="lb"') == len(config.load_config()["printers"]) and html.count("<svg") == len(config.load_config()["printers"]), "QR labels for all printers")

# ================= 9 总览接口（1000 台也快） =================
cfg = config.load_config()
big = list(cfg["printers"])
for i in range(1000 - len(big)):
    big.append({"id": f"pz{i:04d}", "code": f"Z-{i:04d}", "name": ["Bambu Lab P1S", "Creality K1C", "Bambu Lab A1"][i % 3], "enabled": True,
                "group": f"Z{i // 100}", "location": f"Z{i // 100}-{i % 100:02d}", "conn": {"type": "none"}, "ovr": {}})
config.save_config({"printers": big})
pr._status.clear()
for i in range(0, 1000, 3):
    pr._status[i] = {"state": "printing", "progress": 40}
for i in range(1, 1000, 7):
    pr._status[i] = {"state": "offline"}
t0 = time.time(); r = B.get("/api/fleet?per=50&page=2"); dt = time.time() - t0
j = r.get_json()
ok(r.status_code == 200 and j["kpis"]["total"] == 1000 and len(j["rows"]) == 50 and len(j["tiles"]) == 1000, f"overview 1000 printers paged ({dt:.2f}s)")
ok(dt < 3.0, f"overview fast enough {dt:.2f}s")
ok(j["kpis"]["printing"] > 250 and j["kpis"]["offline"] > 100, f"kpis {j['kpis']}")
j2 = B.get("/api/fleet?status=printing&q=Z-00").get_json()
ok(all(r["sg"] == "printing" and "Z-00" in r["code"] for r in j2["rows"]) and j2["total"] > 0, "filter status + search")
j3 = B.get("/api/fleet?model=Creality%20K1C&group=Z3").get_json()
ok(j3["total"] > 0 and all(r["name"] == "Creality K1C" and r["group"] == "Z3" for r in j3["rows"]), "filter model + group")
pr._status.clear()
config.save_config({"printers": cfg["printers"]})

# ================= 10 连接管理：1000 台假打印机（拓竹 MQTT / Creality WS / Moonraker HTTP） =================
pf = D + "/ports.json"
cert, key = D + "/c.pem", D + "/k.pem"
subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", cert, "-days", "2", "-subj", "/CN=fake"],
               capture_output=True)
fk = subprocess.Popen([sys.executable, APP + "/modules/prod/tests/fake_printers.py", pf] + ([cert, key] if os.path.exists(cert) else []))
try:
    for _ in range(100):
        if os.path.exists(pf): break
        time.sleep(0.1)
    ports = json.load(open(pf))
    N = 1000
    lp = []
    for i in range(N):
        k = i % 10
        if k < 6:
            lp.append({"id": f"b{i}", "code": f"B{i}", "name": "Bambu Lab P1S", "group": "",
                       "conn": {"type": "bambu", "host": f"10.0.{i // 250}.{i % 250 + 1}", "serial": f"SN{i:08d}", "access_code": "badcode" if i % 97 == 0 else "12345678"}})
        elif k < 8:
            lp.append({"id": f"c{i}", "code": f"C{i}", "name": "Creality K1C", "conn": {"type": "creality", "host": f"10.1.{i // 250}.{i % 250 + 1}"}})
        else:
            lp.append({"id": f"m{i}", "code": f"M{i}", "name": "Creality K1 Max", "conn": {"type": "moonraker", "host": f"10.2.{i // 250}.{i % 250 + 1}"}})
    LCFG = {"printers": lp}
    async def opener(host, port, tls, timeout):
        return await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), timeout)
    def rss():
        for l in open("/proc/self/status"):
            if l.startswith("VmRSS"):
                return int(l.split()[1]) // 1024
        return 0
    seen = {"n": 0}
    pr.on_change(lambda i, o, n: seen.__setitem__("n", seen["n"] + 1))
    pr._status.clear()
    r0m, t0n = rss(), threading.active_count()
    mgr = pm.Manager(opener=opener, tls=False, ports={"bambu": ports["mqtt"], "creality": ports["ws"], "moonraker": ports["http"]},
                     cfg_loader=lambda: LCFG, fast=2, slow=5, stagger=2, creality_wait=0.5)
    pr._mgr = mgr
    mgr.start()
    t0 = time.time()
    bad = {i for i in range(N) if i % 10 < 6 and i % 97 == 0}
    while time.time() - t0 < 40:
        time.sleep(1)
        st = pr.get_status()
        good = sum(1 for i, v in st.items() if v.get("state") in ("printing", "idle"))
        if good >= N - len(bad) and time.time() - t0 > 6:
            break
    st = pr.get_status()
    good = sum(1 for i, v in st.items() if v.get("state") in ("printing", "idle"))
    ok(good == N - len(bad), f"1000 printers: {good} reporting status in {time.time() - t0:.1f}s ({mgr.stats()})")
    ok(all(st[i].get("state") == "offline" and ("访问码" in st[i].get("error", "") or "授权" in st[i].get("error", "")) for i in bad), "bad access code isolated per printer")
    ok(st[0 + 2].get("state") == "printing" and st[0 + 2].get("progress") is not None and st[6].get("state") == "printing" and st[8].get("state") == "printing", "all three protocols report")
    sets0 = mgr.sets; time.sleep(3)
    ok(mgr.sets > sets0 + 100, f"status updates keep flowing ({mgr.sets - sets0} in 3 s)")
    ok(threading.active_count() - t0n <= 3, f"threads bounded: +{threading.active_count() - t0n} for 1000 printers")
    ok(rss() - r0m < 250, f"memory bounded: +{rss() - r0m} MB")
    time.sleep(1.0)
    ok(seen["n"] >= N - len(bad), f"state-change callbacks delivered via event thread ({seen['n']})")
    links = mgr.links
    ok(max(l.fails for l in links.values()) >= 1 and links["b0"].backoff() >= pm.BACKOFF0 * 0.8, "failing printer backs off")
    # 指令走一直连着的 MQTT
    LCFG2 = {"printers": [dict(p) for p in lp]}
    i2 = 2
    mgr.call(links[f"b{i2}"].publish({"print": {"sequence_id": "1", "command": "pause"}}))
    time.sleep(0.5)
    s = json.loads(__import__("urllib.request").request.urlopen(f"http://127.0.0.1:{ports['http']}/stats").read())
    ok(s["commands"].get("SN00000002") == ["pause"], "command published over persistent MQTT link")
    ok(s["mqtt_conns"] >= 590, f"fake broker sees ~600 live MQTT connections ({s['mqtt_conns']})")
    # 删掉 / 改 IP：连接跟着变，别的不受影响
    lp.pop(0)
    LCFG["printers"] = lp
    mgr.kick(); time.sleep(1.5)
    ok("b0" not in mgr.links and mgr.links["b1"].idx == 0, "removed printer closed, others re-indexed")
    mgr.stop(); pr._mgr = None
    # TLS（和真的拓竹一样）：3 台走 default_open + 自签名证书
    if "mqtts" in ports:
        pr._status.clear()
        TCFG = {"printers": [{"id": f"t{i}", "code": f"T{i}", "name": "Bambu Lab P1S",
                              "conn": {"type": "bambu", "host": "127.0.0.1", "serial": f"TLS0000{i}", "access_code": "12345678"}} for i in range(3)]}
        m2 = pm.Manager(ports={"bambu": ports["mqtts"]}, cfg_loader=lambda: TCFG, stagger=0.1).start()
        pr._mgr = m2
        t0 = time.time()
        while time.time() - t0 < 10 and sum(1 for v in pr.get_status().values() if v.get("state") in ("printing", "idle")) < 3:
            time.sleep(0.3)
        ok(sum(1 for v in pr.get_status().values() if v.get("state") in ("printing", "idle")) == 3, "TLS MQTT (self-signed) works through default_open")
        m2.stop(); pr._mgr = None
    else:
        print("SKIP TLS (no openssl)")

    # ================= 11 后台进程模式（PRINTER_WORKER=external） =================
    pr._status.clear()
    cfg = config.load_config()
    wp = [{"id": "wA", "code": "WA-1", "name": "Bambu Lab P1S", "group": "A 区", "conn": {"type": "bambu", "host": "127.0.0.1", "serial": "SNW0000001", "access_code": "12345678"}},
          {"id": "wB", "code": "WB-1", "name": "Bambu Lab P1S", "group": "B 区", "conn": {"type": "bambu", "host": "10.9.0.2", "serial": "SNW0000002", "access_code": "12345678"}},
          {"id": "wN", "code": "WN-1", "name": "Creality K1C", "group": "B 区", "conn": {"type": "none"}}]
    config.save_config({"printers": wp, "printer_workers": {"w2": ["B 区"]}})
    m_def = pm.Manager(worker_id="", cfg_loader=lambda: config.load_config())
    m_w2 = pm.Manager(worker_id="w2", cfg_loader=lambda: config.load_config())
    c3 = config.load_config()
    ok([m_def.mine(p, c3) for p in c3["printers"]] == [True, False, False] and [m_w2.mine(p, c3) for p in c3["printers"]] == [False, True, True], "printers split between workers by group")
    # w2：带假连接的后台进程（写状态到数据库、执行 ERP 发来的指令）
    wrapper = D + "/w2.py"
    open(wrapper, "w").write(f"""import sys, json, asyncio, time
sys.path.insert(0, {APP!r})
import app
from core import printers as pr, printer_manager as pm
ports = json.load(open({pf!r}))
async def opener(host, port, tls, timeout):
    return await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), timeout)
pr._mgr = pm.Manager(worker_id="w2", persist=True, opener=opener, tls=False, ports={{"bambu": ports["mqtt"]}}, stagger=0.1, reload_s=1).start()
print("w2 up", flush=True)
while True:
    time.sleep(1)
""")
    env = dict(os.environ, LH_DATA_DIR=D, PYTHONPATH=APP)
    env.pop("PRINTER_WORKER", None)
    w2 = subprocess.Popen([sys.executable, wrapper], env=env, cwd=D, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    # 默认后台进程：真的 python -m core.printer_worker（127.0.0.1:8883 没开 → 连不上）
    w0 = subprocess.Popen([sys.executable, "-m", "core.printer_worker"], env=env, cwd=APP, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        pr._mgr = None
        pr._remote["on"] = True
        t0 = time.time()
        while time.time() - t0 < 30:
            s0 = pr.get_status(0); s1 = pr.get_status(1)
            if s0.get("state") == "offline" and s1.get("state") in ("printing", "idle"):
                break
            time.sleep(0.5)
        ok(pr.get_status(0).get("state") == "offline", f"ERP reads default worker state from DB ({pr.get_status(0)})")
        ok(pr.get_status(1).get("state") == "printing", f"ERP reads w2 worker state from DB ({pr.get_status(1)})")
        rows = db.conn().execute("SELECT pid, worker FROM printer_state").fetchall()
        ok({r["pid"]: r["worker"] for r in rows}.get("wB") == "w2" and {r["pid"]: r["worker"] for r in rows}.get("wA") == "", "state rows tagged by worker id")
        pr.command(1, "pause")
        time.sleep(0.5)
        s = json.loads(__import__("urllib.request").request.urlopen(f"http://127.0.0.1:{ports['http']}/stats").read())
        ok("pause" in (s["commands"].get("SNW0000002") or []), "ERP command executed by worker over its MQTT link")
        try:
            pr.command(0, "pause"); ok(False, "command to offline printer should fail")
        except ConnectionError as e:
            ok("连上" in str(e), f"offline worker printer -> clear error ({e})")
        pr.mark_sent(1, "x.gcode.3mf")
        ok(pr.get_status(1).get("file") == "x.gcode.3mf", "mark_sent wins until worker reports newer state")
    finally:
        pr._remote["on"] = False
        for w in (w2, w0):
            w.terminate()
            try:
                out = w.communicate(timeout=5)[0]
            except Exception:
                w.kill(); out = ""
        ok("打印机连接后台进程开始运行" in (out or ""), "python -m core.printer_worker starts")
finally:
    fk.kill()

print("DONE", "FAIL" if E_ else "PASS")
sys.exit(1 if E_ else 0)
