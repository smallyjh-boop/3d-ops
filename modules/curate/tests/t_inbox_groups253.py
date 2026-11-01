# 采集箱自动分组（v2.53）：进度（待下载文件 → 文件就绪 / 待写文案 → 许可待核 → 可转入 → 已转入）、待处理（下载失败 / 采集可能出错 / 原站图 / 多色 AMS / 许可风险）、
# 分数段、来源网站、类目、手动标记（要转入 / 再看看）、旧文件夹迁移成标签 / 标记、保存的视图、返回时记得选的分组。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import json, os, shutil, sqlite3, sys, time
D = T + "/m_inbgrp253"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)


import app as A
from core import db, extras, prodgroups, store
from modules.curate import db as cdb, inbox

db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
for it in store.list_products():
    store.delete(it["id"])
cc = cdb.conn()
NOW = time.time()


def mk(pid, platform="makerworld", score=60, cat="宠物", files_ok=1, files_failed=0, copy=True, lic="ok", lic_auto="", src_img=False, multi=False, bad="", inb=True, **kw):
    p = store.blank_product(pid)
    p.update(name_zh="采集" + pid, inbox=inb, draft=True, source={"source": "curate", "platform": platform, "source_url": f"https://x/{pid}", "imported_at": NOW},
             copy={"title_th": "ชื่อ", "description_th": "รายละเอียด"} if copy else {}, license_check={"status": lic, "auto": lic_auto},
             images=[{"file": "a.jpg", "from": "source" if src_img else "own"}])
    p.update(kw)
    store.save(p)
    for i in range(files_ok):
        cc.execute("INSERT INTO cur_files(product_id, name, kind, state) VALUES(?,?,?,?)", (pid, f"f{i}.stl", "model", "ok"))
    for i in range(files_failed):
        cc.execute("INSERT INTO cur_files(product_id, name, kind, state, error) VALUES(?,?,?,?,?)", (pid, f"x{i}.stl", "model", "failed", "403"))
    cc.execute("INSERT INTO cur_candidates(skey, platform, url, title, category, score, ai, capture_bad, product_id) VALUES(?,?,?,?,?,?,?,?,?)",
               (f"k:{pid}", platform, f"https://x/{pid}", pid, cat, score, json.dumps({"single_color": not multi}), bad, pid))
    cc.commit()
    return p


mk("I1", files_ok=0)                                  # 待下载文件
mk("I2", files_ok=0, files_failed=2)                  # 待下载文件 + 下载失败
mk("I3", copy=False)                                  # 文件就绪 / 待写文案
mk("I4", lic="pending", lic_auto="禁止商用")            # 许可待核 + 许可有风险
mk("I5", score=85, platform="printables")             # 可转入 + 高分
mk("I6", src_img=True, multi=True, score=40)          # 可转入 + 原站图 + 多色 + 一般
mk("I7", bad="标题是作者名", cat="")                    # 采集可能出错 + 未分类
mk("I8", inb=False, inbox_out_at=NOW)                 # 已转入
ib = C.get("/api/cur/inbox?all=1").get_json()
by = {r["product_id"]: set(r["gk"]) for r in ib["rows"]}
n = ib["summary"]["n"]
ok(ib["summary"]["total"] == 7 and n["pg:done"] == 1 and by["I8"] == {"pg:done"}, "total 7 (inbox only) + 已转入 1")
for pid, want in (("I1", "dl"), ("I2", "dl"), ("I3", "copy"), ("I4", "lic"), ("I5", "ready"), ("I6", "ready"), ("I7", "ready")):
    pg = [k for k in by[pid] if k.startswith("pg:")]
    ok(pg == ["pg:" + want], f"progress {pid} -> {pg}")
ok("td:dlfail" in by["I2"] and "td:dlfail" not in by["I1"], "download failed")
ok("td:suspect" in by["I7"], "capture suspect")
ok("td:srcimg" in by["I6"] and "td:ams" in by["I6"], "source image + AMS")
ok("td:risk" in by["I4"], "licence risk")
ok("td:any" in by["I6"] and "td:any" not in by["I5"], "待处理 any")
ok("sc:high" in by["I5"] and "sc:mid" in by["I6"], "score bands")
ok(n["site:printables"] == 1 and n["site:makerworld"] == 6, f"source sites {n.get('site:printables')}/{n.get('site:makerworld')}")
ok("ct:宠物" in by["I1"] and "ct:none" in by["I7"], "category folders automatic")
ok(n["pg:ready"] == 3 and ib["rows"] and any(c["name"] == "宠物" for c in ib["folders"]["cats"]), "can-transfer count + old folders payload kept")
# 修好自动离开：文案写好 → 进下一步
p = store.load("I3"); p["copy"] = {"title_th": "x", "description_th": "y"}; store.save(p)
ok("pg:ready" in {k for r in C.get("/api/cur/inbox?all=1").get_json()["rows"] if r["product_id"] == "I3" for k in r["gk"]}, "copy written -> moves on automatically")
# ---- 手动标记
ok(C.post("/api/goods/marks", json={"ids": ["I5", "I6"], "mark": "into", "on": True, "scope": "inbox"}).get_json()["changed"] == 2, "mark 要转入")
C.post("/api/goods/marks", json={"ids": ["I1"], "mark": "later", "on": True, "scope": "inbox"})
n = C.get("/api/cur/inbox?all=1").get_json()["summary"]["n"]
ok(n["mk:into"] == 2 and n["mk:later"] == 1, "marks counted")
ok(C.post("/api/goods/marks", json={"ids": ["I1"], "mark": "upload", "on": True, "scope": "inbox"}).status_code == 400, "产品库的标记不能用在采集箱")
# ---- 视图
vs = C.post("/api/goods/views", json={"scope": "inbox", "name": "高分可转入", "state": {"sel": {"pg": "pg:ready", "sc": "sc:high"}, "q": ""}}).get_json()["views"]
ok(len(vs) == 1 and C.get("/api/cur/inbox?all=1").get_json()["views"][0]["state"]["sel"]["sc"] == "sc:high", "saved view in inbox payload")
ok(C.get("/api/goods/views").get_json()["views"] == [], "views are per scope")
# ---- 旧文件夹迁移：要转入 / 再看看 -> 标记，其他 -> 标签
for nm, pid in (("要转入", "I2"), ("再看看", "I4"), ("猫用品", "I5")):
    g = extras.group_save(nm)
    C.post("/api/groups/assign", json={"ids": [pid], "group": g, "add": True})
prodgroups.migrate(force=True)
ok("into" in (store.load("I2").get("marks") or {}) and "later" in (store.load("I4").get("marks") or {}), "folders 要转入/再看看 -> marks")
ok({t["name"] for t in prodgroups.tags()} == {"猫用品"} and len(store.load("I5").get("groups") or []) == 1, "other folders kept as tags")
r2 = prodgroups.migrate(force=True)
ok(r2 == {"auto": 0, "upload": 0, "inbox": 0}, "migration idempotent")
ib = C.get("/api/cur/inbox?all=1").get_json()
ok(any(t["name"] == "猫用品" for t in ib["tags"]) and ib["summary"]["n"].get("mk:into") == 3, "tags + marks in payload")
# ---- 前端
js = open(os.path.join(APP, "modules/curate/ui/curate.js"), encoding="utf-8").read()
ok("IGS" in js.split("NAV.keep(")[1] and "GRP.match" in js, "back-navigation keeps inbox groups/view; panel uses GRP")
print("DONE errors=%d" % E_)
sys.exit(1 if E_ else 0)
