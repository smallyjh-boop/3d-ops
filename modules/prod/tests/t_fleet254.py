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
ok(tp.get("Bambu Lab P1S", {}).get("orca_machine") == "Bambu Lab P1S 0.4 nozzle"
   and tp["Bambu Lab P1S"].get("ams") is True, f"identical P1S values -> template {tp.get('Bambu Lab P1S')}")
ok("nozzle" not in tp["Bambu Lab P1S"], "P1S nozzle differs -> not in template")
# v2.54 复审：喷嘴 / 热床板是每台自己的，迁移永远不放进模板（就算同机型都一样 / 只有一台）
ok("plate" not in tp["Bambu Lab P1S"], "identical P1S plate stays per printer (not templated)")
sp = rr["printers"]
ok(sp[0]["ovr"] == {"nozzle": 0.4, "plate": "Textured PEI Plate"} and sp[1]["ovr"] == {"nozzle": 0.6, "plate": "Textured PEI Plate"},
   f"nozzle + plate kept per printer {sp[0]['ovr']} {sp[1]['ovr']}")
ok(all(f not in sp[i] for i in range(4) for f in fleet.TPL_FIELDS), "stored form has no template fields (only ovr)")
ok(tp.get("Creality K1 Max", {}).get("g_per_h") == 20.0 and "nozzle" not in tp["Creality K1 Max"] and sp[2]["ovr"].get("nozzle") == 0.4,
   "single printer model -> template, but nozzle stays per printer")
ok(fleet.template_of("Creality K1 Max", config.load_config()).get("nozzle") is None, "new K1 Max would not inherit a nozzle from migration")
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
ok(slicecheck.check(F(0.4), 0)["ok"] and not slicecheck.check(F(0.4, bed="Smooth PEI Plate"), 0)["ok"], "P1S-01 keeps its own plate after template change")
ok(slicecheck.check(F(0.6), 1)["ok"], "P1S-02 still uses its 0.6 override after template change")
ok(fleet.is_multicolor(config.load_config()["printers"][0]) is False, "is_multicolor follows template ams=false")
ok(fleet.is_multicolor({"name": "Bambu Lab P1S"}) is False, "is_multicolor on raw dict also resolves template")
ok(fleet.is_multicolor({"name": "Bambu Lab P1S", "ams": True}) is True, "explicit ams on dict wins")
r = C.post("/api/fleet/templates", json={"templates": {"Bambu Lab P1S": {"nozzle": "abc"}}})
ok(r.status_code == 400, "bad template value rejected")
# 单台覆盖接口：P1S-01 设 0.6 → 核对跟着变；清空 → 跟模板
r = C.post("/api/fleet/printers/" + ids[0], json={"ovr": {"nozzle": "0.6"}})
ok(r.status_code == 200 and slicecheck.check(F(0.6), 0)["ok"], "override via API used by slicecheck")
r = C.post("/api/fleet/printers/" + ids[0], json={"ovr": {"nozzle": ""}})
ok(slicecheck.check(F(0.4), 0)["ok"] and not slicecheck.check(F(0.6), 0)["ok"], "cleared override -> template 0.4")
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
r = C.post("/api/fleet/printers", json={"name": "Bambu Lab P1S", "vendor": "bambu", "group": "A 区", "location": "A-01-1", "role": "orders", "nozzle": "0.4",
                                        "conn": {"host": "192.168.1.80", "serial": "01P00A000000080", "access_code": "11112222"}})
ok(r.status_code == 200 and r.get_json()["codes"] == ["P1S-003"], f"add with auto code (P1S-01/02 taken) {r.get_json()}")
new_id = r.get_json()["added"][0]
d = C.get("/api/fleet/printers/" + new_id).get_json()
ok(d["printer"]["conn"]["access_code"] == "******" and d["vendor"] == "bambu" and d["printer"]["group"] == "A 区" and d["printer"]["role"] == "orders", "detail masks code + new fields")
ok(d["row"]["index"] == 4, "new printer appended (existing indices unchanged)")
r = C.post("/api/fleet/printers", json={"name": "Creality K1C", "vendor": "creality", "nozzle": 0.4, "conn": {"host": "192.168.1.80"}})
ok(r.status_code == 400 and "192.168.1.80" in r.get_json()["error"], "duplicate IP rejected")
r = C.post("/api/fleet/printers", json={"name": "Nonexistent 3000"})
ok(r.status_code == 400, "unknown model rejected")
r = C.post("/api/fleet/printers", json={"name": "Creality K1C", "n": 3, "group": "B 区", "nozzle": "0.4"})
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
o1 = raw()["printers"][1]["ovr"]
ok(o1.get("nozzle") == 0.6 and o1.get("plate") == "Textured PEI Plate" and not ({"g_per_h", "orca_machine", "ams"} & set(o1)),
   f"legacy save does not turn template values into overrides {o1}")

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

# =====================================================================================================
# 12 v2.54 发版前复审的修复
# =====================================================================================================
import traceback
pr._remote["on"] = False; pr._mgr = None
CONF = {"bed_clear": True, "material": True}

# ---------- 12.1（🟡10）load_config 按文件版本缓存：2000 台反复读要快；拿到的是拷贝；保存 / 别的进程写都能认出来 ----------
bigp = [{"id": f"q{i:04d}", "code": f"Q-{i:04d}", "name": ["Bambu Lab P1S", "Creality K1C"][i % 2], "enabled": True,
         "conn": {"type": "none"}, "ovr": {"nozzle": 0.4}} for i in range(2000)]
config.save_config({"printers": bigp, "printer_workers": {}})
config.invalidate()
t0 = time.time(); a2k = config.load_config(); t_first = time.time() - t0
t0 = time.time()
for _ in range(20):
    config.load_config()
t_rep = (time.time() - t0) / 20
ok(len(a2k["printers"]) == 2000 and t_rep < 0.06 and t_rep * 3 < t_first,
   f"load_config cached for 2000 printers: first {t_first * 1000:.0f} ms, repeated {t_rep * 1000:.1f} ms")
a2k["printers"][0]["code"] = "MUT"; a2k["printers"].pop(); a2k["printers"][1]["ovr"]["nozzle"] = 0.8
b2k = config.load_config()
ok(b2k["printers"][0]["code"] == "Q-0000" and len(b2k["printers"]) == 2000 and b2k["printers"][1]["nozzle"] == 0.4,
   "callers get their own copy (mutating it leaves the cache alone)")
config.save_config({"printers": bigp[:1999]})
ok(len(config.load_config()["printers"]) == 1999, "save_config invalidates the cache")
rr2 = raw(); rr2["printers"] = rr2["printers"][:5]
json.dump(rr2, open(CFGP + ".x", "w", encoding="utf-8"), ensure_ascii=False); os.replace(CFGP + ".x", CFGP)
ok(len(config.load_config()["printers"]) == 5, "config written by another process is picked up (file version)")
src_pm = open(APP + "/core/printer_manager.py", encoding="utf-8").read()
ok("run_in_executor(self._pool, self._read_cfg)" in src_pm, "manager reloads config off the event-loop thread")

# ---------- 12.2（🟡5）job_plates / trials 里的打印机序号也跟着删除 / 挪动 ----------
cfg5 = [{"id": f"r{i}", "code": f"R-{i}", "name": "Bambu Lab P1S", "enabled": True, "conn": {"type": "none"}, "ovr": {"nozzle": 0.4}} for i in range(4)]
config.save_config({"printers": cfg5})
dbc = db.conn()
dbc.execute("INSERT INTO job_plates(job_id, plate_id, printer, pin) VALUES(999001, 'p1', 2, 1)")
dbc.execute("INSERT INTO job_plates(job_id, plate_id, printer, pin) VALUES(999001, 'p2', 1, 1)")
dbc.execute("INSERT INTO trials(job_id, printer, status) VALUES(999001, 3, 'done')")
dbc.commit()
old5 = config.load_config()["printers"]           # 和删除接口一样：保存 → remap（不重新排单，免得排单把测试用的盘清掉）
new5 = config.save_config({"printers": [p_ for p_ in old5 if p_["id"] != "r1"]})["printers"]
ok(fleet.remap(old5, new5) == {1: None, 2: 1, 3: 2}, "delete R-1 -> remap")
pl = {x["plate_id"]: dict(x) for x in dbc.execute("SELECT plate_id, printer, pin FROM job_plates WHERE job_id=999001")}
prs5 = config.load_config()["printers"]
ok(pl["p1"]["printer"] is not None and prs5[pl["p1"]["printer"]]["code"] == "R-2" and pl["p1"]["pin"] == 1, f"pinned plate follows its printer after delete {pl['p1']}")
ok(pl["p2"]["printer"] is None and pl["p2"]["pin"] == 0, f"plate pinned to the deleted printer is unpinned (rescheduled) {pl['p2']}")
tr = dbc.execute("SELECT printer FROM trials WHERE job_id=999001").fetchone()
ok(prs5[tr["printer"]]["code"] == "R-3", "trial record follows its printer")
ok(set(fleet.PRINTER_TABLES) >= {"jobs", "print_runs", "failures", "maintenance", "job_plates", "trials"}, "all printer-index tables remapped")
dbc.execute("DELETE FROM job_plates WHERE job_id=999001"); dbc.execute("DELETE FROM trials WHERE job_id=999001"); dbc.commit()

# ---------- 12.3（🟡3）状态 / 通知按稳定 id：删了打印机、连接管理还没对设置时，打完的消息不会记到别的打印机上 ----------
cfg3 = [{"id": f"s{k}", "code": f"S-{k}", "name": "Bambu Lab P1S", "enabled": True, "ovr": {"nozzle": 0.4},
         "conn": {"type": "bambu", "host": f"10.8.0.{n + 1}", "serial": f"SNS000000{n}", "access_code": "12345678"}} for n, k in enumerate("WYZQ")]
config.save_config({"printers": cfg3})
pr._status.clear()
def mkrun(idx):
    j = production.create_job("3DP0001", "3DP0001-WH", 1, "stock")
    jid = j["id"] if isinstance(j, dict) else j
    return production.start_run(jid, idx, 1, [], None, False, "t", CONF)["run_id"]
runZ, runQ = mkrun(2), mkrun(3)
mgr3 = pm.Manager()                      # 没启动：只用它记状态、排队通知（和真的一样，读设置文件）
lZ = pm.Link(mgr3, "sZ", 2, cfg3[2]["conn"]); lQ = pm.Link(mgr3, "sQ", 3, cfg3[3]["conn"])
def drain():
    while not mgr3.events.empty():
        pr.fire_pid(*mgr3.events.get())
mgr3.set(lZ, {"state": "printing", "file": "z"}); mgr3.set(lQ, {"state": "printing", "file": "q"}); drain()
ok(pr.get_status(2).get("file") == "z" and pr.get_status(3).get("file") == "q", "status stored by id, read by index")
mgr3.set(lZ, {"state": "finished", "file": "z"})          # 「打完」的通知还在排队
r = B.delete("/api/fleet/printers/sW")                    # 这时删了最前面的一台：Z 2→1，Q 3→2
ok(r.status_code == 200 and lZ.idx == 2, "printer deleted while the manager has not re-synced (link keeps old index)")
drain()
st_run = lambda rid: dbc.execute("SELECT status FROM print_runs WHERE id=?", (rid,)).fetchone()["status"]
ok(st_run(runZ) == "done" and st_run(runQ) == "printing", f"only the right run finishes (Z {st_run(runZ)}, Q {st_run(runQ)})")
mgr3.set(lQ, {"state": "paused", "file": "q"}); drain()     # Q 的连接还拿着旧序号 3
ok(pr.get_status(1).get("state") == "finished" and pr.get_status(2).get("state") == "paused" and pr.get_status(3) == {},
   f"status follows printer id after delete {[pr.get_status(i).get('state') for i in range(4)]}")
ok(pr.fire_pid("sW", {"state": "printing"}, {"state": "finished"}) is False, "event for a deleted printer is dropped")
dbc.execute("UPDATE print_runs SET status='done' WHERE id=?", (runQ,)); dbc.execute("UPDATE jobs SET status='done' WHERE run_id=?", (runQ,)); dbc.commit()
pr._status.clear()

# ---------- 12.4（🟡4）抽屉的指令带稳定 id：打印机列表变了 → 服务器拒绝，不发错打印机 ----------
prs4 = config.load_config()["printers"]          # S-Y, S-Z, S-Q
drawer = {"index": 1, "id": prs4[1]["id"]}       # 打开了 S-Z 的抽屉
r = B.delete("/api/fleet/printers/" + prs4[0]["id"])   # 别人删了 S-Y：序号 1 现在是 S-Q
for path, body in ((f"/api/printers/{drawer['index']}/command", {"cmd": "pause"}), (f"/api/printers/{drawer['index']}/loaded", {"loaded": "白"}),
                   (f"/api/printers/{drawer['index']}/netdiag", {}), ("/api/maintenance", {"printer": drawer["index"], "item": "clean"})):
    r = B.post(path, json=dict(body, printer_id=drawer["id"]))
    ok(r.status_code == 409 and "刷新" in (r.get_json() or {}).get("error", ""), f"stale drawer refused: {path} {r.status_code}")
ok(config.load_config()["printers"][1]["conn"].get("loaded", "") == "", "refused 'loaded' did not touch the other printer")
ok(dbc.execute("SELECT COUNT(*) FROM maintenance WHERE printer=1 AND item='clean' AND ts>?", (time.time() - 60,)).fetchone()[0] == 0, "refused maintenance not recorded")
r = B.post("/api/printers/0/loaded", json={"loaded": "白", "printer_id": drawer["id"]})
ok(r.status_code == 200 and config.load_config()["printers"][0]["conn"].get("loaded") == "白", "matching id + index accepted")
fjs = open(APP + "/modules/prod/ui/fleet.js", encoding="utf-8").read()
ok(fjs.count("printer_id: id") >= 3 and "PROD.netDiag(idx, t, id)" in fjs and "PROD.maintDialog(idx, t.dataset.flmaint, done, id)" in fjs,
   "drawer sends the stable id with every index-based command")

# ---------- 12.5（🔴1）后台进程模式：先认领再执行；ERP 超时但后台在执行 → 结果未知（不是失败）、不重发；两个同 id 的后台进程只执行一次 ----------
config.save_config({"printers": [{"id": "kA", "code": "KA-1", "name": "Bambu Lab P1S", "enabled": True, "ovr": {"nozzle": 0.4},
                                  "conn": {"type": "bambu", "host": "10.9.9.1", "serial": "SNK0000001", "access_code": "12345678"}}],
                    "printer_workers": {}})
loop = asyncio.new_event_loop(); threading.Thread(target=loop.run_forever, daemon=True).start()
class SlowLink:
    def __init__(self, delay):
        self.n, self.delay, self.connected = 0, delay, True
    async def publish(self, payload):
        self.n += 1
        await asyncio.sleep(self.delay)
slow = SlowLink(2.5)
def fake_worker():
    m = pm.Manager(worker_id="", persist=True); m.loop = loop; m.links = {"kA": slow}; return m
wa, wb = fake_worker(), fake_worker()            # 两个后台进程，PRINTER_WORKER_ID 一样
stop = threading.Event()
def pump(m):
    while not stop.is_set():
        try:
            m.run_commands()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        finally:
            db.release()
        time.sleep(0.05)
pumps = [threading.Thread(target=pump, args=(m,), daemon=True) for m in (wa, wb)]
for t_ in pumps:
    t_.start()
pr._remote["on"] = True; pr._mgr = None
old_wait = pr.REMOTE_WAIT; pr.REMOTE_WAIT = 1.0
pA = config.load_config()["printers"][0]
def call(key):
    try:
        pr._remote_call(pA, "publish", {"print": {"command": "pause"}}, key=key); return "ok", ""
    except pr.UnknownResult as e:
        return "unknown", str(e)
    except ConnectionError as e:
        return "fail", str(e)
try:
    res, msg = call("t-1")
    ok(res == "unknown" and pr.UNKNOWN_MSG in msg, f"slow worker + ERP timeout -> result unknown, not failure ({res}: {msg})")
    time.sleep(2.0)
    rows = [dict(x) for x in dbc.execute("SELECT status, worker FROM printer_cmds WHERE ikey='t-1'")]
    ok(len(rows) == 1 and rows[0]["status"] == "done" and rows[0]["worker"] and slow.n == 1, f"worker finished it once {rows} n={slow.n}")
    res, msg = call("t-1")                              # 重试同一次发送
    time.sleep(0.3)
    ok(res == "unknown" and slow.n == 1, f"retry with the same idempotency key is refused by the worker ({res}: {msg}) n={slow.n}")
    ok(dbc.execute("SELECT status FROM printer_cmds WHERE ikey='t-1' ORDER BY id DESC").fetchone()["status"] == "dup", "duplicate marked dup")
    # 两个同 id 的后台进程：每条指令只执行一次
    slow.delay = 0.02; n0 = slow.n
    for k in range(8):
        pr._remote_call(pA, "publish", {"print": {"command": "pause"}}, wait=0)
    t0 = time.time()
    while time.time() - t0 < 10 and dbc.execute("SELECT COUNT(*) FROM printer_cmds WHERE status IN ('new','running')").fetchone()[0]:
        time.sleep(0.1)
    ok(slow.n - n0 == 8 and wa.executed + wb.executed == slow.n, f"two workers with the same id: 8 commands executed exactly once ({slow.n - n0})")
    # start_run：结果未知 → 记成打印中 + 提醒，不当失败；不能再发第二次
    slow.delay = 2.5
    def send_via_worker(idx, path, name, kind, slot=None):
        p = config.load_config()["printers"][idx]
        pr._remote_call(p, "publish", pr.bambu_start_payload(name, 1, None), key=getattr(pr._SEND, "key", ""))
        return name
    real_send = pr.send_file; pr.send_file = send_via_worker
    gp = D + "/rv.gcode"
    open(gp, "w").write("; generated by test\n; filament used [g] = 10\nM83\nG28\n;LAYER_CHANGE\nG1 X10 Y10 E1\n")
    from core import print_files
    fz = print_files.add(gp, "rv.gcode", "3DP0001", "Bambu Lab P1S", "", 1, "", "t", "boss", "PLA", 10, 1, source="plan")
    slicecheck.confirm(fz["id"], "Bambu Lab P1S", "boss"); print_files.verify(fz["id"], True, "boss")
    jz = production.create_job("3DP0001", "3DP0001-WH", 1, "stock"); jz = jz["id"] if isinstance(jz, dict) else jz
    n0 = slow.n
    try:
        out = production.start_run(jz, 0, 1, [], fz["id"], True, "boss", CONF)
        err_ = ""
    except Exception as e:  # noqa: BLE001
        out, err_ = {}, str(e)
    rrow = dbc.execute("SELECT status, sent, alert FROM print_runs WHERE id=?", (out.get("run_id"),)).fetchone() if out else None
    ok(bool(out.get("unknown")) and rrow is not None and rrow["status"] == "printing" and pr.UNKNOWN_MSG in (rrow["alert"] or "")
       and pr.UNKNOWN_MSG in out.get("warning", ""), f"start_run with unknown result: run kept as printing + warning, not a failure ({err_ or dict(rrow or {})})")
    try:
        production.start_run(jz, 0, 1, [], fz["id"], True, "boss", CONF); again = "sent again"
    except ValueError as e:
        again = str(e)
    time.sleep(2.8)
    ok(again != "sent again" and slow.n - n0 == 1, f"no second send ({again}); printer got it once ({slow.n - n0})")
    ok(pr.get_status(0).get("state") == "printing", "printer shown as printing after unknown send")
    ikeys = [x["ikey"] for x in dbc.execute("SELECT ikey FROM printer_cmds WHERE ikey LIKE 'start:%'")]
    ok(len(ikeys) == 1 and ikeys[0].startswith(f"start:kA:{jz}:"), f"start_run passes a per-send idempotency key {ikeys}")
    pr.send_file = real_send
    # 后台进程没在运行：ERP 超时 → 失败，指令作废，之后后台进程起来也不会再执行
    stop.set()
    for t_ in pumps:
        t_.join(5)
    n0 = slow.n
    res, msg = call("t-9")
    st9 = dbc.execute("SELECT status FROM printer_cmds WHERE ikey='t-9'").fetchone()["status"]
    wa.run_commands()
    ok(res == "fail" and st9 == "timeout" and slow.n == n0, f"no worker -> failure, command voided ({res}, {st9})")
finally:
    stop.set()
    pr.REMOTE_WAIT = old_wait
    pr._remote["on"] = False
    loop.call_soon_threadsafe(loop.stop)
pr._status.clear()

# ---------- 12.6（🔴2）后台进程不跑模块的启动任务（拉订单、Lazada、迁移…），生产模块的状态回调照样注册 ----------
probe = f"""import sys, threading, json, os
sys.path.insert(0, {APP!r})
started = []
_orig = threading.Thread.start
def _st(self):
    started.append(self.name); return _orig(self)
threading.Thread.start = _st
from core import printer_worker
printers = printer_worker.boot()
from core import modules, production
print("RESULT " + json.dumps({{"mods": [n for n in started if n.startswith("mod-")], "env": os.environ.get("LH_NO_MODULE_STARTUP"),
      "tpl": os.environ.get("LH_NO_TPL_SYNC"), "cb": production.on_printer_change in printers._events, "n": len(modules._started)}}))
"""
env = dict(os.environ, LH_DATA_DIR=D, PYTHONPATH=APP)
for k in ("LH_NO_MODULE_STARTUP", "LH_NO_TPL_SYNC", "PRINTER_WORKER"):
    env.pop(k, None)
pp = subprocess.run([sys.executable, "-c", probe], env=env, cwd=APP, capture_output=True, text=True, timeout=180)
line = next((l for l in pp.stdout.splitlines() if l.startswith("RESULT ")), "")
j = json.loads(line[7:]) if line else {}
ok(j.get("mods") == [] and j.get("n", 0) > 0, f"worker import starts no module background jobs {j or pp.stderr[-500:]}")
ok(j.get("env") == "1" and j.get("tpl") == "1" and j.get("cb") is True, "worker sets LH_NO_MODULE_STARTUP / LH_NO_TPL_SYNC and keeps the prod status callback")

# ---------- 12.7（🟡6）喷嘴是每台自己的：添加时要明确填；新打印机不继承同机型别的打印机的 0.6 ----------
config.save_config({"printers": [{"id": "n1", "code": "N-01", "name": "Bambu Lab P1S", "enabled": True, "conn": {"type": "none"}, "ovr": {"nozzle": 0.6}}]})
r = B.post("/api/fleet/printers", json={"name": "Bambu Lab P1S"})
ok(r.status_code == 400 and "喷嘴" in r.get_json()["error"], f"add without nozzle refused {r.get_json()}")
r = B.post("/api/fleet/printers?lang=th", json={"name": "Bambu Lab P1S"})
ok(r.status_code == 400 and "หัวฉีด" in r.get_json()["error"], "nozzle error in Thai")
r = B.post("/api/fleet/printers", json={"name": "Bambu Lab P1S", "nozzle": "0.4"})
ok(r.status_code == 200, f"add with confirmed nozzle {r.get_json()}")
pn = config.load_config()["printers"]
ok(pn[1]["nozzle"] == 0.4 and raw()["printers"][1]["ovr"].get("nozzle") == 0.4, "new printer stores its own nozzle")
SM = "Smooth PEI Plate"          # 第 2 节把 P1S 模板的热床板设成了这个
ok(slicecheck.check(F(0.4, bed=SM), 1)["ok"] and not slicecheck.check(F(0.6, bed=SM), 1)["ok"] and slicecheck.check(F(0.6, bed=SM), 0)["ok"],
   "new printer checks its own 0.4 nozzle (0.6 file rejected), the 0.6 printer still takes 0.6")
r = B.post("/api/fleet/printers", json={"name": "Anycubic Photon Mono M5s"})
ok(r.status_code == 200, f"resin printer needs no nozzle {r.get_json()}")
res6 = fleet.validate_import([{"model": "Bambu Lab P1S"}, {"model": "Bambu Lab P1S", "nozzle": "0.6"}, {"model": "Bambu Lab P1S", "nozzle": "abc"}], config.load_config())
ok(res6[0]["printer"]["ovr"] == {"nozzle": 0.4} and res6[0]["warnings"] and res6[1]["printer"]["ovr"] == {"nozzle": 0.6} and not res6[2]["ok"],
   "import: nozzle per row (missing -> 0.4 + warning, bad -> error)")

# ---------- 12.8（🟡8）导入预览 / 提交失败都不回传明文访问码；提交按 token 取服务器上的原始行 ----------
csv8 = ("model,ip,serial,access code,nozzle\n"
        "Bambu Lab P1S,192.168.7.10,01P00A000000710,SECRET71,0.4\n"
        "Bambu Lab P1S,192.168.7.11,01P00A000000711,SECRET72,0.6\n")
r = B.post("/api/fleet/import", data={"file": (io.BytesIO(csv8.encode()), "p.csv")}, content_type="multipart/form-data")
body = r.get_data(as_text=True); j = r.get_json()
ok(r.status_code == 200 and "SECRET7" not in body and "data" not in j and j.get("token"), "import preview: no plaintext access codes, server-side token")
devs = [{"row": x["row"], "model": x["printer"]["name"], "vendor": x["printer"]["conn"]["type"], "host": x["printer"]["conn"]["host"],
         "serial": x["printer"]["conn"]["serial"], "access_code": "******", "nozzle": x["printer"]["ovr"].get("nozzle")} for x in j["rows"]]
r = B.post("/api/fleet/add-many", json={"devices": [dict(devs[0], host="192.168.7.999"), devs[1]], "token": j["token"]})
ok(r.status_code == 400 and "SECRET7" not in r.get_data(as_text=True), "failed commit does not return access codes")
r = B.post("/api/fleet/add-many", json={"devices": devs, "token": j["token"]})
ok(r.status_code == 200 and len(r.get_json()["added"]) == 2, f"commit with token {r.get_json()}")
last2 = config.load_config()["printers"][-2:]
ok([x["conn"]["access_code"] for x in last2] == ["SECRET71", "SECRET72"] and [x["nozzle"] for x in last2] == [0.4, 0.6], "access codes taken from the server-side rows")
ok(B.post("/api/fleet/add-many", json={"devices": devs, "token": "nope"}).status_code == 400, "unknown / expired token refused")
csv9 = csv8.replace("192.168.7.1", "192.168.6.1").replace("00000071", "00000061") + "Bambu Lab P1S,192.168.6.300,,,\n"
r = B.post("/api/fleet/import?commit=1", data={"file": (io.BytesIO(csv9.encode()), "p.csv")}, content_type="multipart/form-data")
ok(r.status_code == 400 and "SECRET7" not in r.get_data(as_text=True), "file commit with bad rows: codes masked")

# ---------- 12.9（🟡9）/api/config 不再把 200 台以后的打印机截掉 ----------
p201 = [{"code": f"V-{i:03d}", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True} for i in range(201)]
r = B.post("/api/config", json={"printers": p201})
ok(r.status_code == 200 and len(config.load_config()["printers"]) == 201, f"/api/config keeps all 201 printers ({len(config.load_config()['printers'])})")
r = B.post("/api/config", json={"printers": p201 * 25})
ok(r.status_code == 400 and len(config.load_config()["printers"]) == 201, "/api/config over the limit -> error, nothing truncated")
ajs = open(APP + "/static/app.js", encoding="utf-8").read()
ok('data-c="printers"' not in ajs and "body.printers" not in ajs, "settings page no longer posts printers to /api/config")

print("DONE", "FAIL" if E_ else "PASS")
sys.exit(1 if E_ else 0)
