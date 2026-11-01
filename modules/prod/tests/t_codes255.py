# v2.55：打印机编码规则——积木预览、顺序号范围（同机型 / 同分组 / 全部）、分组各用各的规则、添加 / 导入 / 发现自动编码、
# 手填编码（不分大小写查重 + 字符检查）、批量重新编号（预览 旧→新、冲突、确认）、改完以后引用都没断
# （任务 / 打印记录按 id、料卷装在哪台、仓库生产区货位、生产单指定打印机、标签）、两台互换编码不串、改位置时提示重新编号
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3
D = T + "/m_codes255"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m, flush=True); E_ += (not b)
import app as A
from core import db, fleet, fleetcodes as fc, production, materials, po, printers as pr
from core.config import load_config, save_config
from modules.inv import flows
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pong", "secret123", "production", "Pong")
def cli(u):
    c = A.app.test_client(); c.post("/api/auth/login", json={"username": u, "password": "secret123"}); return c
C, PC = cli("boss"), cli("pong")
pr.send_file = lambda idx, path, name, kind, slot=None: name
CONF = {"bed_clear": True, "material": True}

def prs():
    return load_config()["printers"]
def codes():
    return [p["code"] for p in prs()]
def rules(**kw):
    d = {"rules": {"std": {"name": "标准", "sep": "-", "blocks": [{"t": "model"}, {"t": "seq", "width": 3, "scope": "model"}]}}, "default": "std", "groups": {}, "group_codes": {}}
    d.update(kw)
    return d
def put_rules(d):
    r = C.post("/api/fleet/codes/rules", json=d)
    assert r.status_code == 200, r.get_json()
    return r.get_json()
def blocks(*bs, sep="-", name="规则"):
    return {"name": name, "sep": sep, "blocks": list(bs)}
SEQ = lambda w=3, sc="model": {"t": "seq", "width": w, "scope": sc}
def add(name="Bambu Lab P1S", n=1, **kw):
    r = C.post("/api/fleet/printers", json=dict({"name": name, "n": n, "nozzle": "0.4"}, **kw))
    assert r.status_code == 200, r.get_json()
    return r.get_json()
def byid(i):
    return next(p for p in prs() if p["id"] == i)

base = [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "tech": "fdm", "group": "A 区", "location": "A-01-1"},
        {"code": "P1S-02", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True, "tech": "fdm", "group": "A 区", "location": "A-01-2"},
        {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "enabled": True, "tech": "fdm", "group": "B 区", "location": "B-02-1"}]
save_config({"printers": base, "stock_auto_use": False})
ids = [p["id"] for p in prs()]

# ================= 1 规则校验 + 预览 =================
rr, errs = fc.clean_rule(blocks({"t": "fixed", "v": "pr"}, {"t": "group"}, SEQ(2, "group"), name="x"))
ok(not errs and rr["blocks"][0]["v"] == "PR", "clean_rule ok, fixed upper-cased")
ok(fc.clean_rule(blocks(SEQ(5)))[1] and fc.clean_rule(blocks(SEQ(3), SEQ(3)))[1] and fc.clean_rule(blocks({"t": "bogus"}))[1]
   and fc.clean_rule(blocks({"t": "fixed", "v": ""}))[1] and fc.clean_rule({"blocks": [], "sep": "-"})[1] and fc.clean_rule(blocks(SEQ(), sep="."))[1],
   "bad rules rejected: width 5 / two seq / unknown block / empty fixed / no blocks / bad separator")
r = C.post("/api/fleet/codes/preview", json={"rule": blocks({"t": "group"}, {"t": "model"}, SEQ(3))}).get_json()
ex = [x["code"] for x in r["examples"]]
ok(r["ok"] and ex == ["A-P1S-001", "A-P1S-002", "B-K1C-001", "B-P1S-003"], f"preview group+model+seq(per model) {ex}")
r = C.post("/api/fleet/codes/preview", json={"rule": blocks({"t": "fixed", "v": "PR"}, {"t": "loc"}, SEQ(2, "global"), sep="_")}).get_json()
ok([x["code"] for x in r["examples"]] == ["PR_A_03_2_01", "PR_A_03_3_02", "PR_B_01_1_03", "PR_B_01_2_04"], f"preview fixed+loc+global sep _ {[x['code'] for x in r['examples']]}")
r = C.post("/api/fleet/codes/preview", json={"rule": blocks({"t": "group"}, {"t": "model"}, SEQ(4, "group"), sep="")}).get_json()
ok([x["code"] for x in r["examples"]] == ["AP1S0001", "AP1S0002", "BK1C0001", "BP1S0002"], f"no separator, width 4, per group {[x['code'] for x in r['examples']]}")
r = C.post("/api/fleet/codes/preview", json={"rule": blocks({"t": "fixed", "v": "ABCDEFGH"}, {"t": "loc"}, {"t": "model"}, SEQ(4))}).get_json()
ok(r["ok"] and r["length_ok"] is False, "preview flags codes longer than 16")
r = C.post("/api/fleet/codes/preview?lang=th", json={"rule": blocks(SEQ(9))}).get_json()
ok(not r["ok"] and "หลัก" in r["errors"][0]["msg"], "preview error in Thai")

# 保存规则：整套存 / 校验 / 权限
ok(C.post("/api/fleet/codes/rules", json={"rules": {"x": blocks(SEQ(7))}, "default": "x"}).status_code == 400, "invalid rule not saved")
ok(C.post("/api/fleet/codes/rules", json={"rules": {"x": {"sep": "-", "blocks": [{"t": "model"}, SEQ()]}}, "default": "x"}).status_code == 400, "rule needs a name")
ok(C.post("/api/fleet/codes/rules", json={"rules": {}}).status_code == 400, "at least one rule")
ok(PC.post("/api/fleet/codes/rules", json=rules()).status_code == 403 and PC.post("/api/fleet/codes/renumber", json={"all": True}).status_code == 403, "production cannot save rules / renumber")
ok(PC.get("/api/fleet/codes/rules").status_code == 200, "production can read rules")
g = C.get("/api/fleet/codes/rules").get_json()
ok(g["default"] == "std" and g["rules"]["std"]["blocks"][0]["t"] == "model" and g["group_list"] == ["A 区", "B 区"], "no saved rules -> built-in model-sequence rule")

# ================= 2 顺序号范围 =================
def gen(specs, cfgrules, existing=None):
    cfg = {"printer_code_rules": cfgrules}
    return [c for c, _p in fc.generate(existing or [], specs, cfg)]
S = lambda n, g="", l="": {"name": n, "group": g, "location": l}
P1, K1 = "Bambu Lab P1S", "Creality K1C"
sp = [S(P1, "A"), S(K1, "A"), S(P1, "B"), S(K1, "B")]
cr = lambda *bs, **kw: {"rules": {"x": blocks(*bs, **kw)}, "default": "x"}
ok(gen(sp, cr({"t": "model"}, SEQ(3, "model"))) == ["P1S-001", "K1C-001", "P1S-002", "K1C-002"], "scope per model")
ok(gen(sp, cr({"t": "model"}, SEQ(3, "global"))) == ["P1S-001", "K1C-002", "P1S-003", "K1C-004"], "scope global")
ok(gen(sp, cr({"t": "group"}, {"t": "model"}, SEQ(3, "group"))) == ["A-P1S-001", "A-K1C-002", "B-P1S-001", "B-K1C-002"], "scope per group")
ok(gen(sp, cr({"t": "group"}, {"t": "model"}, SEQ(3, "model"))) == ["A-P1S-001", "A-K1C-001", "B-P1S-002", "B-K1C-002"], "group+model, numbered per model")
# 跳过已用的号（含老格式 P1S-01）和大小写
ex_ = [{"code": "p1s-01", "name": P1}, {"code": "P1S-003", "name": P1}]
ok(gen([S(P1), S(P1)], cr({"t": "model"}, SEQ(3)), ex_) == ["P1S-002", "P1S-004"], "skips used numbers (legacy P1S-01 counts as 1, case-insensitive)")
# 没有顺序号的规则：重复报问题
res = fc.generate([], [S(P1, "A", "A-01-1"), S(P1, "A", "A-01-1")], {"printer_code_rules": cr({"t": "group"}, {"t": "loc"})})
ok(res[0][1] is None and res[0][0] == "A-A-01-1" and res[1][1] == "dup", f"rule without seq: second identical is a duplicate {res}")
ok(gen([S(P1, "A 区")], {"rules": {"x": blocks({"t": "group"}, SEQ())}, "default": "x", "group_codes": {}}) == ["A-001"], "group token from ascii part of name")
ok(gen([S(P1, "甲区")], {"rules": {"x": blocks({"t": "group"}, SEQ())}, "default": "x", "group_codes": {"甲区": "JIA"}}) == ["JIA-001"], "group short code for non-ascii group")
ok(gen([S(P1, "甲区")], cr({"t": "group"}, {"t": "model"}, SEQ())) == ["P1S-001"], "empty group token skipped")
ok(len(fc.generate([], [S(P1, "A", "A-01-1")], {"printer_code_rules": cr({"t": "fixed", "v": "ABCDEFGH"}, {"t": "loc"}, {"t": "model"}, SEQ(4))})[0][0]) > 16
   and fc.generate([], [S(P1, "A", "A-01-1")], {"printer_code_rules": cr({"t": "fixed", "v": "ABCDEFGH"}, {"t": "loc"}, {"t": "model"}, SEQ(4))})[0][1] == "long", "too long -> problem")

# ================= 3 添加 N 台自动编码（按规则、分组各用各的规则） =================
put_rules(rules(rules={"std": blocks({"t": "model"}, SEQ(3), name="标准"),
                       "area": blocks({"t": "group"}, {"t": "model"}, SEQ(3, "group"), name="分区")},
                default="std", groups={"B 区": "area"}))
r = add(P1, 2)
ok(r["codes"] == ["P1S-003", "P1S-004"], f"default rule, skips P1S-01/02 {r['codes']}")
r = add(K1, 2, group="B 区")
ok(r["codes"] == ["B-K1C-001", "B-K1C-002"], f"group B uses its own rule {r['codes']}")
r = add(P1, 1, group="B 区", location="B-05-1")
ok(r["codes"] == ["B-P1S-003"], f"group scope counts B-K1C-001/002 -> 003 {r['codes']}")
r = add(P1, 1, group="C 区")
ok(r["codes"] == ["P1S-005"], f"group with no rule of its own -> default {r['codes']}")
# 手填：字符 / 不分大小写查重
r = C.post("/api/fleet/printers", json={"name": P1, "nozzle": "0.4", "code": "p1s-003"})
ok(r.status_code == 400 and "已经有了" in r.get_json()["error"], "manual code duplicate (case-insensitive) rejected on add")
r = C.post("/api/fleet/printers", json={"name": P1, "nozzle": "0.4", "code": "P1S 3!"})
ok(r.status_code == 400 and "只能用英文" in r.get_json()["error"], "manual code invalid chars rejected")
r = C.post("/api/fleet/printers?lang=th", json={"name": P1, "nozzle": "0.4", "code": "p1s-003"})
ok(r.status_code == 400 and "มีอยู่แล้ว" in r.get_json()["error"], "duplicate message in Thai")
r = C.post("/api/fleet/printers", json={"name": P1, "nozzle": "0.4", "code": "my-p1s"})
ok(r.status_code == 200 and r.get_json()["codes"] == ["MY-P1S"], "manual code accepted, upper-cased")
mid = r.get_json()["added"][0]
r = C.post("/api/fleet/printers/" + mid, json={"code": "k1c-01"})
ok(r.status_code == 400, "edit to an existing code (other case) rejected")
r = C.post("/api/fleet/printers/" + mid, json={"code": "my-p1s"})
ok(r.status_code == 200 and byid(mid)["code"] == "MY-P1S", "re-saving own code (other case) is fine")
ok(C.post("/api/fleet/codes/check", json={"code": "k1c-01"}).get_json()["ok"] is False and C.post("/api/fleet/codes/check", json={"code": "k1c-01", "id": ids[2]}).get_json()["ok"] is True
   and C.post("/api/fleet/codes/check", json={"code": "bad code"}).get_json()["ok"] is False, "check endpoint")
r = C.post("/api/fleet/printers/" + mid, json={"code": "MY-P1S-9"})
ok(r.status_code == 200 and byid(mid)["code"] == "MY-P1S-9" and "MY-P1S" in byid(mid)["old_codes"], "manual rename remembers the old code")
ok(fleet.index_of(prs(), "MY-P1S") == fleet.index_of(prs(), mid), "old code still finds the printer (printed labels keep working)")
C.delete("/api/fleet/printers/" + mid)

# ================= 4 导入 / 发现（add-many）自动编码 =================
csv = "model,group,location,ip,vendor,nozzle\nBambu Lab P1S,B 区,B-07-1,,,0.4\nCreality K1C,B 区,B-07-2,,,0.4\nBambu Lab P1S,,,,,0.4\nBambu Lab P1S,,,,,0.4\n"
r = C.post("/api/fleet/import", json={"text": csv}).get_json()
ok(r["ok"] == 4 and [x["printer"]["code"] for x in r["rows"]] == ["B-P1S-004", "B-K1C-005", "P1S-006", "P1S-007"], f"import preview codes by rule {[x['printer']['code'] for x in r['rows']]}")
r = C.post("/api/fleet/import?commit=1", json={"text": csv})
ok(r.status_code == 200 and r.get_json()["codes"] == ["B-P1S-004", "B-K1C-005", "P1S-006", "P1S-007"], f"import commit {r.get_json()}")
csv2 = "code,model,group\nb-p1s-004,Bambu Lab P1S,B 区\nZZ-1,Bambu Lab P1S,\nzz-1,Bambu Lab P1S,\n"
r = C.post("/api/fleet/import", json={"text": csv2}).get_json()
ok(r["ok"] == 1 and r["bad"] == 2, f"import: manual duplicate of existing (other case) + duplicate inside the file flagged {r['ok']}/{r['bad']}")
# 同一个文件里手填的编码，后面自动编的不会撞
csv3 = "code,model,group\nP1S-008,Bambu Lab P1S,\n,Bambu Lab P1S,\n"
r = C.post("/api/fleet/import?commit=1", json={"text": csv3}).get_json()
ok(r["codes"] == ["P1S-008", "P1S-009"], f"auto code avoids manual code in the same file {r['codes']}")
r = C.post("/api/fleet/add-many", json={"devices": [{"ip": "10.9.0.1", "model": K1, "vendor": "creality", "group": "B 区", "location": "B-08-1", "code": ""},
                                                     {"ip": "10.9.0.2", "model": K1, "vendor": "creality", "group": "B 区", "location": "B-08-2", "code": ""}]})
ok(r.status_code == 200 and r.get_json()["codes"] == ["B-K1C-006", "B-K1C-007"], f"discovery add-many with blank code -> rule {r.get_json()}")
import core.printer_discovery as disc
orig = disc.discover
disc.discover = lambda cfg, secs, scan_hosts=None: {"devices": [{"ip": "10.9.0.9", "model": K1, "vendor": "creality", "serial": ""}], "scanned": 1}
d = C.post("/api/fleet/discover", json={}).get_json()
disc.discover = orig
ok(d["devices"][0]["code_suggest"] == "K1C-003", f"discovery suggestion (default rule, numbers 1-2 taken in the model scope) {d['devices'][0]['code_suggest']}")

# ================= 5 引用准备：任务 / 打印记录 / 装着的料卷 / 生产区货位 / 生产单 / 标签 =================
put_rules(rules(rules={"std": blocks({"t": "model"}, SEQ(3), name="标准")}, default="std"))
save_config({"printers": base, "stock_auto_use": False})        # 回到 3 台
# 现在打印机：P1S-01(0) P1S-02(1) K1C-01(2)；先给它们 A / B 分组（base 里已有）
ids = [p["id"] for p in prs()]
ok(len(ids) == 3, "reset to 3 printers")
SKA = "3DP0003-WH"
porder = C.post("/api/porders", json={"lines": [{"sku": SKA, "qty": 2}], "printers": ["P1S-01", "K1C-01"], "release": True}).get_json()
ok(porder.get("id"), f"PO created {porder}")
poid = porder["id"]
raw_refs = db.conn().execute("SELECT printers FROM production_orders WHERE id=?", (poid,)).fetchone()["printers"]
jobs = [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE po_id=?", (poid,))]
j0 = jobs[0]
ok(j0["printer"] in (0, 2), f"job scheduled on a listed printer {j0['printer']}")
pidx = j0["printer"]
production.start_run(j0["id"], pidx, 2, [], None, False, "t", CONF)
run_id = db.conn().execute("SELECT run_id FROM jobs WHERE id=?", (j0["id"],)).fetchone()["run_id"]
old_code = prs()[pidx]["code"]
sp_ids = materials.receive("PLA", "白色", 2, 1000, user="t")
sid = int(sp_ids[0][1:])
materials.spool_action(sid, "load", "t", old_code, "A1")
sid2 = int(sp_ids[1][1:])
materials.spool_action(sid2, "load", "t", prs()[1]["code"], "A1")
flows.sync_printers()
locs0 = {r["pid"]: dict(r) for r in db.conn().execute("SELECT * FROM inv_printer_locs")}
ok(set(locs0) >= set(ids) and all(locs0[i]["code"] == byid(i)["code"] for i in ids), "inv_printer_locs now keyed by printer id")
shelf_of = {i: locs0[i]["shelf"] for i in ids}
def spool_on(s):
    r = db.conn().execute("SELECT printer, status FROM spools WHERE id=?", (s,)).fetchone()
    return r["printer"], r["status"]
ok(spool_on(sid) == (old_code, "loaded"), "spool loaded on the printer")
# 出入库记录里的打印机（编码）
cnt_moves = db.conn().execute("SELECT COUNT(*) n FROM inv_moves WHERE printer=?", (old_code,)).fetchone()["n"]

# ================= 6 批量重新编号：预览 =================
put_rules(rules(rules={"std": blocks({"t": "model"}, SEQ(3), name="标准"),
                       "area": blocks({"t": "group"}, {"t": "model"}, SEQ(3, "group"), name="分区")},
                default="std", groups={"A 区": "area"}))
pv = C.post("/api/fleet/codes/renumber", json={"ids": ids}).get_json()
rows = {x["id"]: x for x in pv["rows"]}
ok(rows[ids[0]]["old"] == "P1S-01" and rows[ids[0]]["new"] == "A-P1S-001" and rows[ids[1]]["new"] == "A-P1S-002" and rows[ids[2]]["new"] == "K1C-001",
   f"preview old -> new, group rule for A {[ (x['old'], x['new']) for x in pv['rows']]}")
ok(pv["changed"] == 3 and pv["conflicts"] == 0 and codes() == ["P1S-01", "P1S-02", "K1C-01"], "preview changes nothing")
pv2 = C.post("/api/fleet/codes/renumber", json={"group": "A 区", "rule": "std"}).get_json()
ok([x["new"] for x in pv2["rows"]] == ["P1S-001", "P1S-002"], f"explicit rule + group selection {[x['new'] for x in pv2['rows']]}")
# 顺序：按现有编码倒着
pv3 = C.post("/api/fleet/codes/renumber", json={"ids": ids[:2], "rule": "std", "order": "code"}).get_json()
ok([x["old"] for x in pv3["rows"]] == ["P1S-01", "P1S-02"], "order by code")
# 冲突：没有顺序号的规则 → 同机型重复；和没选中的重复
put_rules(rules(rules={"std": blocks({"t": "model"}, SEQ(3), name="标准"), "nos": blocks({"t": "model"}, name="无序号")}, default="std"))
pv4 = C.post("/api/fleet/codes/renumber", json={"ids": ids, "rule": "nos"}).get_json()
st = {x["old"]: x["status"] for x in pv4["rows"]}
ok(pv4["conflicts"] == 2 and st["P1S-01"] == "conflict" and st["P1S-02"] == "conflict" and st["K1C-01"] == "change", f"duplicates highlighted as conflict {st}")
ap = C.post("/api/fleet/codes/renumber", json={"ids": ids, "rule": "nos", "apply": True})
ok(ap.status_code == 400 and codes() == ["P1S-01", "P1S-02", "K1C-01"], "apply refused while conflicts, nothing changed")
ok(C.post("/api/fleet/codes/renumber", json={}).status_code == 400, "needs a selection")
# 和没选中的重复（只选 P1S-01，规则无序号 → P1S 已被 P1S-02? 不重复；先把 P1S-02 改成 P1S 再试）
C.post("/api/fleet/printers/" + ids[1], json={"code": "P1S"})
pv5 = C.post("/api/fleet/codes/renumber", json={"ids": [ids[0]], "rule": "nos"}).get_json()
ok(pv5["conflicts"] == 1 and pv5["rows"][0]["status"] == "conflict", "collision with an unselected printer is a conflict")
C.post("/api/fleet/printers/" + ids[1], json={"code": "P1S-02"})
ok(codes() == ["P1S-01", "P1S-02", "K1C-01"], "restored")
# 已经符合规则 → 不变
put_rules(rules(rules={"std": blocks({"t": "model"}, SEQ(3), name="标准")}, default="std"))
C.post("/api/fleet/codes/renumber", json={"ids": ids, "apply": True})
same = C.post("/api/fleet/codes/renumber", json={"ids": ids}).get_json()
ok(same["changed"] == 0 and same["same"] == 3 and codes() == ["P1S-001", "P1S-002", "K1C-001"], f"renumber by std rule then preview again = unchanged {codes()}")
ok(C.post("/api/fleet/codes/renumber", json={"ids": ids, "apply": True}).get_json()["n"] == 0, "second apply is a no-op")

# ================= 7 引用没断（上一步已经把 P1S-01/02/K1C-01 改成 P1S-001/002/K1C-001） =================
new_code = prs()[pidx]["code"]
ok(new_code != old_code and old_code not in codes(), f"printer {old_code} renamed to {new_code}")
ok([p["id"] for p in prs()] == ids, "stable ids and order unchanged")
jn = db.conn().execute("SELECT printer FROM jobs WHERE id=?", (j0["id"],)).fetchone()["printer"]
ok(jn == pidx, "job still on the same printer (by id / index)")
rn = db.conn().execute("SELECT printer, status FROM print_runs WHERE id=?", (run_id,)).fetchone()
ok(rn["printer"] == pidx, "print run still on the same printer")
board = C.get("/api/production").get_json()
lane = next(l for l in board["lanes"] if l["index"] == pidx)
ok(lane["code"] == new_code, f"board lane shows the new code {lane['code']}")
ok(spool_on(sid) == (new_code, "loaded"), f"loaded spool followed the rename {spool_on(sid)}")
ok(spool_on(sid2)[0] == prs()[1]["code"], "other spool followed too")
ok(db.conn().execute("SELECT COUNT(*) n FROM inv_moves WHERE printer=?", (old_code,)).fetchone()["n"] == 0
   and db.conn().execute("SELECT COUNT(*) n FROM inv_moves WHERE printer=?", (new_code,)).fetchone()["n"] == cnt_moves, "stock-move history re-pointed to the new code")
flows.sync_printers()
locs1 = {r["pid"]: dict(r) for r in db.conn().execute("SELECT * FROM inv_printer_locs WHERE active=1")}
ok(all(locs1[i]["code"] == byid(i)["code"] and locs1[i]["shelf"] == shelf_of[i] for i in ids), "production-zone shelves kept, renamed to the new codes")
n_old = db.conn().execute("SELECT COUNT(*) n FROM inv_printer_locs WHERE code IN ('P1S-01','P1S-02','K1C-01')").fetchone()["n"]
ok(n_old == 0, "no stale inv_printer_locs rows")
z = flows.zone_letter(db.conn(), "production", create=False)
lc = flows._L().make_code(z, shelf_of[ids[0]], 1, 1)
note = db.conn().execute("SELECT note FROM inv_locations WHERE code=?", (lc,)).fetchone()["note"]
ok(note == byid(ids[0])["code"], f"production-zone location note = new code {note}")
ok(byid(ids[0])["code"] in flows.prod_human(flows._L().parse(lc)) and flows.printer_of(lc)[0] == byid(ids[0])["code"], "location display / lookup use the new code")
sl = db.conn().execute("SELECT l.code FROM inv_spool_loc s JOIN inv_locations l ON l.id=s.loc_id WHERE s.spool_id=?", (sid,)).fetchone()
ok(sl is None or flows.printer_of(sl["code"])[0] == new_code, "spool's shelf resolves to the new printer code")
# 生产单：指定打印机按 id 存，改编码以后还认
raw_after = db.conn().execute("SELECT printers FROM production_orders WHERE id=?", (poid,)).fetchone()["printers"]
ok(po.resolve_printers(__import__("json").loads(raw_after)) == sorted({0, 2}) or set(po.resolve_printers(__import__("json").loads(raw_after))) == {0, 2},
   f"PO printer restriction still resolves to the same printers (was {raw_refs} now {raw_after})")
ok(ids[0] in raw_after and ids[2] in raw_after, "legacy code refs in the PO were migrated to stable ids before renaming")
for j in db.conn().execute("SELECT printer FROM jobs WHERE po_id=? AND printer IS NOT NULL", (poid,)):
    ok(j["printer"] in (0, 2), "PO jobs still only on the listed printers")
# 标签：新编码、旧二维码仍能找到
html = C.get("/print/fleet-labels?ids=" + ",".join(ids)).get_data(as_text=True)
ok(all(c in html for c in codes()) and html.count('class="lb"') == 3, "labels print the new codes")
ok(fleet.index_of(prs(), old_code) == pidx, "old printed QR (old code) still opens the printer")
ok(C.get("/print/fleet-labels?ids=" + old_code).get_data(as_text=True).count('class="lb"') == 1, "labels by old code still found")
ok(byid(ids[pidx if pidx < 3 else 0])["old_codes"], "old codes remembered")

# ================= 8 两台互换编码：料卷 / 货架不串 =================
put_rules(rules(rules={"std": blocks({"t": "model"}, SEQ(3), name="标准")}, default="std"))
a, b2 = prs()[0], prs()[1]
s3 = int(materials.receive("PLA", "黑色", 1, 1000, user="t")[0][1:]); s4 = int(materials.receive("PLA", "黑色", 1, 1000, user="t")[0][1:])
materials.spool_action(s3, "load", "t", a["code"], "B1"); materials.spool_action(s4, "load", "t", b2["code"], "B1")
sa, sb = s3, s4
locs_b = {r["pid"]: r["shelf"] for r in db.conn().execute("SELECT pid, shelf FROM inv_printer_locs WHERE active=1")}
# 通过重新编号接口造互换：先手工把两台改成一个不会重复的，再按「按列表倒序」不好造；直接用 rename_codes + 配置保存模拟互换
pa, pb = dict(a), dict(b2)
ca, cb = a["code"], b2["code"]
cur = prs()
cur[0] = dict(cur[0], code=cb); cur[1] = dict(cur[1], code=ca)
save_config({"printers": cur})
fc.rename_codes([(ca, cb), (cb, ca)])
flows.sync_printers()
ok(spool_on(sa)[0] == cb and spool_on(sb)[0] == ca, f"swap A<->B: spools follow their printers {spool_on(sa)} {spool_on(sb)}")
locs_a = {r["pid"]: r["shelf"] for r in db.conn().execute("SELECT pid, shelf FROM inv_printer_locs WHERE active=1")}
ok(locs_a[ids[0]] == locs_b[ids[0]] and locs_a[ids[1]] == locs_b[ids[1]], "swap: shelves stay with their printers")
rows_ = {r["pid"]: r["code"] for r in db.conn().execute("SELECT pid, code FROM inv_printer_locs WHERE active=1")}
ok(rows_[ids[0]] == cb and rows_[ids[1]] == ca, "swap: inv_printer_locs codes swapped without clobbering")
# 换回去
cur = prs(); cur[0] = dict(cur[0], code=ca); cur[1] = dict(cur[1], code=cb)
save_config({"printers": cur}); fc.rename_codes([(cb, ca), (ca, cb)]); flows.sync_printers()
ok(spool_on(sa)[0] == ca and spool_on(sb)[0] == cb, "swap back")
# 设置页保存（web/system.py → fleet.remap）互换也不串
cur = prs(); old_list = [dict(x) for x in cur]
cur[0] = dict(cur[0], code=cb); cur[1] = dict(cur[1], code=ca)
new_list = save_config({"printers": cur})["printers"]
fleet.remap(old_list, new_list)
ok(spool_on(sa)[0] == cb and spool_on(sb)[0] == ca, f"fleet.remap swap safe {spool_on(sa)} {spool_on(sb)}")
cur = prs(); old_list = [dict(x) for x in cur]
cur[0] = dict(cur[0], code=ca); cur[1] = dict(cur[1], code=cb)
fleet.remap(old_list, save_config({"printers": cur})["printers"])
flows.sync_printers()

# ================= 9 改分组 / 位置：编码里带着旧的 → 提示重新编号（不自动改） =================
put_rules(rules(rules={"std": blocks({"t": "model"}, SEQ(3), name="标准"),
                       "area": blocks({"t": "group"}, {"t": "model"}, SEQ(3, "group"), name="分区"),
                       "loc": blocks({"t": "loc"}, SEQ(2, "global"), name="位置")}, default="std", groups={"A 区": "area"}))
C.post("/api/fleet/codes/renumber", json={"ids": ids, "apply": True})
ok(codes()[0].startswith("A-P1S-") and codes()[2] == "K1C-001", f"renumber after rule change {codes()}")
r = C.post("/api/fleet/printers/" + ids[0], json={"location": "A-09-9"}).get_json()
ok(r["renumber_suggest"] == [], "area rule does not embed the location -> no prompt")
r = C.post("/api/fleet/printers/" + ids[0], json={"group": "C 区"}).get_json()
ok(r["renumber_suggest"] == [ids[0]], f"group changed and code embeds the group -> prompt {r['renumber_suggest']}")
ok(byid(ids[0])["code"].startswith("A-P1S-"), "not renumbered automatically")
pv = C.post("/api/fleet/codes/renumber", json={"ids": r["renumber_suggest"]}).get_json()
ok(pv["rows"][0]["new"].startswith("P1S-") or pv["rows"][0]["new"].startswith("C-"), f"preview offers the new code {pv['rows'][0]['new']}")
r = C.post("/api/fleet/printers/" + ids[2], json={"group": "Z 区"}).get_json()
ok(r["renumber_suggest"] == [], "std rule has no group/location block -> no prompt")
put_rules(rules(rules={"std": blocks({"t": "model"}, SEQ(3), name="标准"), "loc": blocks({"t": "loc"}, SEQ(2, "global"), name="位置")}, default="loc"))
C.post("/api/fleet/codes/renumber", json={"ids": [ids[1]], "apply": True})
ok(byid(ids[1])["code"] == "A-01-2-01" or byid(ids[1])["code"].startswith("A-01-2"), f"location-based code {byid(ids[1])['code']}")
r = C.post("/api/fleet/bulk", json={"ids": [ids[1]], "action": "location", "value": "A-02-5"}).get_json()
ok(r["renumber_suggest"] == [ids[1]], f"bulk location change prompts too {r}")
r = C.post("/api/fleet/bulk", json={"ids": [ids[2]], "action": "role", "value": "any"}).get_json()
ok(r["renumber_suggest"] == [], "unrelated bulk action: no prompt")

# ================= 9b 复审（v2.55.0）：每处改编码走同一套 + 互换 / 复用不让旧标签悄悄指错 + 二维码装稳定 id =================
import json as _json
calls = {"po": 0}
_orig_mig = fc.migrate_po_refs
def _mig():
    calls["po"] += 1
    return _orig_mig()
fc.migrate_po_refs = _mig
pa_, pb_ = prs()[0], prs()[1]
xa, xb = pa_["code"], pb_["code"]
# 单台改编码：生产单引用先迁移、旧编码记下来
r = C.post("/api/fleet/printers/" + pa_["id"], json={"code": "ZZ-9"}).get_json()
ok(calls["po"] == 1 and "ZZ-9" == byid(pa_["id"])["code"] and xa in byid(pa_["id"])["old_codes"], f"single code change: PO refs migrated + old code remembered ({calls})")
# 复用：另一台改成 A 之前的编码 → A 的旧编码里这个码不能再认（否则旧标签悄悄开错机器），记进 stale_codes
r = C.post("/api/fleet/printers/" + pb_["id"], json={"code": xa})
ok(r.status_code != 200 and byid(pb_["id"])["code"] == xb, "v2.55.0 review: manual reuse of another printer's old code refused")
_o = [dict(x) for x in prs()]; _n = [dict(x) for x in prs()]
_n[1]["code"] = xa                                            # 直接走 helper 模拟重新编号 / 互换造成的复用
fc.note_code_changes(_o, _n); save_config({"printers": _n})
ok(xa not in byid(pa_["id"]).get("old_codes", []) and xa in byid(pa_["id"]).get("stale_codes", []), "old code now owned by another printer dropped from old_codes (kept as stale)")
ok(xb in byid(pb_["id"]).get("old_codes", []), "the other printer remembers its own previous code")
ok(fleet.index_of(prs(), xa) == prs().index(byid(pb_["id"])), "current code wins when scanning")
d = C.get("/api/fleet/printers/" + xa).get_json()
ok(d.get("stale_label") is True and d["printer"]["id"] == pb_["id"], "scanning the reassigned old code -> stale_label warning")
ok(C.get("/api/fleet/printers/" + pb_["id"]).get_json().get("stale_label") is False, "scanning by stable id -> no warning")
ok(C.get("/api/fleet/printers/" + xb).get_json().get("stale_label") is False, "scanning a still-valid old code -> no warning")
# 设置页保存同一行改编码也走这一套
cfgp = [dict(x) for x in prs()]
rows_ = [{"code": (("SET-1" if x["id"] == pa_["id"] else x["code"])), "name": x["name"], "g_per_h": x.get("g_per_h", 20), "enabled": True,
          "tech": x.get("tech"), "nozzle": x.get("nozzle")} for x in cfgp]
n0 = calls["po"]
r = C.post("/api/config", json={"printers": rows_})
ok(r.status_code == 200 and calls["po"] == n0 + 1 and byid(pa_["id"])["code"] == "SET-1" and "ZZ-9" in byid(pa_["id"])["old_codes"],
   f"settings page rename: same helper (PO migrate + remember_old) {r.status_code} {byid(pa_['id']).get('old_codes')}")
# 互换（直接用 helper）：两台旧标签都会指到对方 → relabel 列出来
o_ = [dict(x) for x in prs()]
n_ = [dict(x) for x in prs()]
n_[0]["code"], n_[1]["code"] = o_[1]["code"], o_[0]["code"]
info = fc.note_code_changes(o_, n_)
ok({x["id"] for x in info["relabel"]} == {n_[0]["id"], n_[1]["id"]} and all(x["old"] and x["now_of"] for x in info["relabel"]), f"swap -> both need reprint {info['relabel']}")
ok(o_[0]["code"] not in n_[0].get("old_codes", []) and o_[0]["code"] in n_[0].get("stale_codes", []), "swap: old codes colliding with the other printer are dropped from old_codes")
save_config({"printers": n_})
d = C.get("/api/fleet/printers/" + o_[0]["code"]).get_json()
ok(d["stale_label"] is True and d["printer"]["id"] == n_[1]["id"], "after swap, scanning the old label code -> warning (opens the new owner)")
# 批量重新编号接口带 relabel 字段
r = C.post("/api/fleet/codes/renumber", json={"ids": ids, "apply": True}).get_json()
ok("relabel" in r and "relabel_ids" in r, "renumber result carries relabel list")
fc.migrate_po_refs = _orig_mig
# 二维码装稳定 id（牌子上大字还是编码），扫码两种都认
from modules.inv import qr as _qr
seen = []
_osvg = _qr.svg
_qr.svg = lambda url, *a, **k: (seen.append(url), _osvg(url, *a, **k))[1]
html = C.get("/print/fleet-labels?ids=" + ",".join(ids)).get_data(as_text=True)
_qr.svg = _osvg
ok(len(seen) == 3 and all(f"?printer={byid(i)['id']}#" in u for i, u in zip(ids, seen)), f"label QR encodes the stable id {seen[:1]}")
ok(all(byid(i)["code"] in html for i in ids), "label still prints the readable code")
ok(fleet.index_of(prs(), byid(ids[0])["id"]) == fleet.index_of(prs(), byid(ids[0])["code"]), "scan accepts both id and code")


# ================= 9b 复审：别的机器的旧编码不能分给新机器 =================
_ps = [dict(x) for x in prs()]
_a = dict(_ps[0], old_codes=["OLD-ZZ-1"])
_ps[0] = _a
_old = "OLD-ZZ-1"
ok(_old.upper() in fleet.retired_codes(_ps) and _old.upper() not in fleet.retired_codes(_ps, _a["id"]), f"retired_codes lists other printers' old codes {_old}")
_nm = fleet.next_codes("Bambu Lab P1S", 3, _ps)
ok(_old.upper() not in {x.upper() for x in _nm}, f"next_codes skips old codes {_nm}")
_ps2 = [dict(code="P1S-002", old_codes=["P1S-001"], id="a"), dict(code="P1S-003", id="b")]
ok(fleet.next_codes("Bambu Lab P1S", 1, _ps2) == ["P1S-004"] and fleet.next_codes("Bambu Lab P1S", 1, [dict(code="P1S-002", id="a")]) == ["P1S-001"],
   "next_codes: free number reused only when no printer remembers it")
ok(fc.check_code(_old, _ps, exclude_id="zz") is not None and fc.check_code(_old, _ps, exclude_id=_a["id"]) is None,
   "check_code: another printer's old code refused, the owner may take it back")
ok(fleet.stale_label([dict(id="a", code="X-1", old_codes=["P-9"]), dict(id="b", code="P-9")], "P-9") is True, "stale_label also covers old_codes of other printers")
_cur = [dict(x) for x in prs()]
_real = next((x for p_ in _cur for x in p_.get("old_codes", []) if x.upper() not in {q["code"].upper() for q in _cur}), None)
ok(_real is not None, f"setup: a real free old code exists {_real}")
_rows = [{"code": x["code"], "name": x["name"], "g_per_h": 20, "enabled": True} for x in _cur] + [{"code": _real, "name": "Bambu Lab P1S", "g_per_h": 20, "enabled": True}]
_r = C.post("/api/config", json={"printers": _rows})
ok(_r.status_code >= 400 and len(prs()) == len(_cur), f"settings page: new printer with another's old code refused {_r.status_code}")

# ================= 10 审计 + 最终一致性 =================
ok(all(fleet.CODE_RE.match(c) for c in codes()) and len({c.upper() for c in codes()}) == len(codes()), f"all codes valid and unique {codes()}")
ok(db.conn().execute("SELECT COUNT(*) n FROM audit WHERE action='批量重新编号打印机'").fetchone()["n"] >= 1, "renumber audited")
print("DONE errors=%d" % E_)
sys.exit(1 if E_ else 0)
