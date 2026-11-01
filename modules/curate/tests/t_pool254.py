# 候选池操作重做（v2.54.1）：表单字符串数字（"30"）不再报 '>' not supported、每条都能删除 / 恢复 / 编辑（类目、手动分数留原分、备注、标签、标题）、
# 删除（不写指纹，再采到会重新出现）和忽略（不再出现）的区别、采用了的不在池子里、页签个数、清理建议 + 按钮、回收站恢复 / 彻底删除。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import json, os, shutil, sqlite3, sys, time
D = T + "/m_pool254"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
FAILED = []


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)
    if not b:
        FAILED.append(m)


import app as A
from core import db
from modules.curate import cand, pool, sites, db as cdb

db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "secret123", "listing", "Nok")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
N = A.app.test_client(); N.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
cc = cdb.conn()
pool.ensure()
NOW = time.time()
DAY = 86400


def wipe():
    for t in ("cur_candidates", "cur_trash", "cur_gone"):
        cc.execute(f"DELETE FROM {t}")
    cc.commit()


def add(n, platform="makerworld", score=60, status="", excluded="", pid="", seen=0, ago=1, watch=0, cat="宠物", title=None, author="", metrics=None, bad=""):
    cc.execute("INSERT INTO cur_candidates(skey, platform, url, title, thumb, author, metrics, score, excluded, category, status, product_id, seen_at, first_seen, last_seen, watch_id, capture_bad) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (f"s:{n}", platform, f"https://x/{n}", title or f"Model {n} unique title", "https://t/x.jpg", author, json.dumps(metrics or {}), score, excluded, cat, status, pid, seen,
                NOW - ago * DAY, NOW - ago * DAY, watch, bad))
    cc.commit()
    return cc.execute("SELECT id FROM cur_candidates WHERE skey=?", (f"s:{n}",)).fetchone()[0]


def rows(q=""):
    return C.get("/api/cur/candidates" + q).get_json()


def gone(sk):
    return bool(cc.execute("SELECT 1 FROM cur_gone WHERE skey=?", (sk,)).fetchone())


# ================= 1. 字符串数字（「清理所选」的 bug）=================
wipe()
add(1, excluded="宗教", ago=40); add(2, score=20, ago=40); add(3, status="ignored", ago=40); add(4, status="ignored", ago=5)
S = {"excl_days": "30", "low_score": "40", "low_days": "30", "ignored_days": "30"}
r = C.post("/api/cur/pool/preview", json={"opts": S})
pv = r.get_json()
ok(r.status_code == 200 and pv["ok"] and {x["id"]: x["n"] for x in pv["classes"]}["ignored"] == 1, f"preview with string numbers works ({r.status_code})")
r = C.post("/api/cur/pool/preview", json={"opts": {"excl_days": " 30 ", "low_score": "40.5", "low_days": "", "ignored_days": 30.0}})
ok(r.status_code == 200, "spaces / decimals / empty string / floats accepted")
r = C.post("/api/cur/pool/clean", json={"opts": S, "classes": ["excl", "low", "ignored"]})
ok(r.status_code == 200 and r.get_json()["removed"] == 3, f"clean with string numbers {r.get_json()}")
for bad in ("abc", "-5", "99999", "1e9", "nan", "inf", "٣٠x", [1], {"a": 1}):
    r = C.post("/api/cur/pool/preview", json={"opts": {"excl_days": bad}})
    ok(r.status_code == 400 and "请填数字" in r.get_json()["error"], f"preview rejects {bad!r} → 请填数字")
ok(C.post("/api/cur/pool/preview", json={"opts": {"low_score": "101"}}).status_code == 400, "low_score range 0–100")
r = C.post("/api/cur/pool/clean", json={"opts": {"ignored_days": "abc"}, "classes": ["ignored"]})
ok(r.status_code == 400 and cc.execute("SELECT COUNT(*) FROM cur_candidates").fetchone()[0] == 1, "bad number: nothing cleaned")
r = C.post("/api/cur/pool/settings", json={"cap": "3000", "low_score": "35", "excl_days": "45", "ignored_days": "20", "low_days": "25"})
st = pool.settings()
ok(r.status_code == 200 and st["cap"] == 3000 and st["low_score"] == 35 and st["excl_days"] == 45 and st["ignored_days"] == 20 and st["low_days"] == 25
   and all(isinstance(st[k], int) for k in ("cap", "low_score", "excl_days")), f"settings coerce strings to int {st}")
r = C.post("/api/cur/pool/settings", json={"cap": "5000", "low_score": "xyz"})
ok(r.status_code == 400 and pool.settings()["cap"] == 3000, "bad settings: nothing half-saved")
C.post("/api/cur/pool/settings", json={"cap": 5000, "low_score": 40, "excl_days": 30, "ignored_days": 30, "low_days": 30})
ok(C.post("/api/cur/candidates/status", json={"ids": ["x"], "status": "later"}).status_code == 400, "status ids: non-number → 400 not 500")
ok(C.post("/api/cur/collect/action", json={"id": "abc", "action": "hold"}).status_code == 400, "other endpoint with string id → 400")
ok(C.get("/api/cur/candidates?min=abc&watch=x").status_code == 200, "listing tolerates junk numbers")

# ================= 2. 每条删除 / 恢复 / 编辑 =================
wipe()
a = add(10, score=70)                                 # 新发现
b = add(11, status="ignored")
x = add(12, excluded="宗教", score=55)
p = add(13, status="adopted", pid="P1")
ok(N.post("/api/cur/candidates/delete", json={"ids": [a]}).get_json()["deleted"] == 1, "any user can delete (recoverable)")
row = cc.execute("SELECT * FROM cur_trash WHERE skey='s:10'").fetchone()
ok(row and row["reason"] == "deleted" and not gone("s:10") and not cc.execute("SELECT 1 FROM cur_candidates WHERE skey='s:10'").fetchone(), "删除 → recycle bin, NO fingerprint")
ok(C.post("/api/cur/candidates/delete", json={"ids": [p]}).get_json()["deleted"] == 0 and cc.execute("SELECT 1 FROM cur_candidates WHERE skey='s:13'").fetchone(), "adopted cannot be deleted")
ok(C.post("/api/cur/candidates/delete", json={"ids": ["zz"]}).status_code == 400, "delete with junk ids → 400")
# 删除后在原站再采到 → 重新出现（新发现）；忽略的 → 不再出现
url10 = "https://makerworld.com/en/models/101010-delete-me"
k10 = sites.source_key(url10)
cand.upsert([{"url": url10, "title": "Delete me widget", "author": "bob", "thumb": "https://t/a.jpg", "metrics": {"likes": "50"}}])
i10 = cc.execute("SELECT id FROM cur_candidates WHERE skey=?", (k10,)).fetchone()[0]
C.post("/api/cur/candidates/delete", json={"ids": [i10]})
ok(not gone(k10) and cc.execute("SELECT 1 FROM cur_trash WHERE skey=?", (k10,)).fetchone(), "deleted real candidate: bin only")
out = cand.upsert([{"url": url10, "title": "Delete me widget", "author": "bob", "thumb": "https://t/a.jpg", "metrics": {"likes": "50"}}])
nr = cc.execute("SELECT * FROM cur_candidates WHERE skey=?", (k10,)).fetchone()
ok(nr and nr["status"] == "" and not nr["seen_at"] and out[url10]["status"] == "" and not cc.execute("SELECT 1 FROM cur_trash WHERE skey=?", (k10,)).fetchone(),
   "deleted ≠ ignored: collected again → shows up as a new discovery")
C.post("/api/cur/candidates/status", json={"ids": [nr["id"]], "status": "ignored"})
C.post("/api/cur/candidates/delete", json={"ids": [nr["id"]]})
ok(gone(k10) and cc.execute("SELECT 1 FROM cur_trash WHERE skey=?", (k10,)).fetchone(), "deleting an IGNORED row keeps its fingerprint")
out = cand.upsert([{"url": url10, "title": "Delete me widget", "author": "bob", "thumb": "https://t/a.jpg"}])
ok(not cc.execute("SELECT 1 FROM cur_candidates WHERE skey=?", (k10,)).fetchone() and out[url10]["status"] == "ignored", "ignored (even if deleted) never comes back")
# 恢复：已忽略 → 待处理；规则排除 → 「我说可以」，重新打分也不再排除
ok(C.post("/api/cur/candidates/restore", json={"ids": [b, x, p]}).get_json()["restored"] == 2, "restore ignored + excluded (adopted untouched)")
rb = cc.execute("SELECT status FROM cur_candidates WHERE id=?", (b,)).fetchone()
rx = cc.execute("SELECT excluded, ex_ok FROM cur_candidates WHERE id=?", (x,)).fetchone()
ok(rb[0] == "" and rx[0] == "" and rx[1] == 1, "ignored → open; excluded → cleared with ex_ok")
cc.execute("UPDATE cur_candidates SET title='Buddha statue 佛像 religious', author='a' WHERE id=?", (x,)); cc.commit()
cand.rescore_all()
ok(cc.execute("SELECT excluded FROM cur_candidates WHERE id=?", (x,)).fetchone()[0] == "", "rescore keeps the restored one un-excluded")
# 编辑
cc.execute("UPDATE cur_candidates SET score=64, score_auto=-1 WHERE id=?", (b,)); cc.commit()
r = C.post("/api/cur/candidates/edit", json={"id": b, "category": "收纳整理", "score": "88", "note": "老板说先做这个", "tags": "猫, 收纳，猫", "title": "我的标题"})
ok(r.status_code == 200, f"edit ok {r.status_code}")
e = next(y for y in rows("?min=0")["rows"] if y["id"] == b)
ok(e["category"] == "收纳整理" and e["cat_manual"] and e["score"] == 88 and e["score_manual"] and e["score_auto"] == 64, f"category + manual score, original kept ({e['score']}/{e['score_auto']})")
ok(e["note"] == "老板说先做这个" and e["tags"] == ["猫", "收纳"] and e["title"] == "我的标题" and e["title_manual"] and e["title_raw"].startswith("Model 11"), "note / tags (deduped) / title override, raw title kept")
cand.rescore_all()
e = next(y for y in rows("?min=0")["rows"] if y["id"] == b)
ok(e["score"] == 88 and e["category"] == "收纳整理" and e["score_manual"], "rescore_all does not overwrite manual score / category")
ok(len(rows("?min=0&q=%E8%80%81%E6%9D%BF")["rows"]) == 1 and len(rows("?min=0&q=%E6%94%B6%E7%BA%B3")["rows"]) == 1, "search finds note / tags")
ok(C.post("/api/cur/candidates/edit", json={"id": b, "score": "abc"}).status_code == 400 and C.post("/api/cur/candidates/edit", json={"id": b, "score": "101"}).status_code == 400
   and C.post("/api/cur/candidates/edit", json={"id": b, "score": -1}).status_code == 400 and C.post("/api/cur/candidates/edit", json={"id": 99999, "note": "x"}).status_code == 400, "edit validates score / id")
ok(C.post("/api/cur/candidates/edit", json={"id": b, "tags": 5}).status_code == 400, "edit validates tags")
C.post("/api/cur/candidates/edit", json={"id": b, "score": "", "category": "", "title": ""})
e = next(y for y in rows("?min=0")["rows"] if y["id"] == b)
ok(not e["score_manual"] and not e["cat_manual"] and not e["title_manual"] and e["score"] != 88, f"clear overrides → back to system score ({e['score']})")
ok(N.post("/api/cur/candidates/edit", json={"id": b, "note": "staff note"}).status_code == 200, "staff can edit notes")

# ================= 3. 页签 / 采用了的不在池子里 =================
wipe()
add(20); add(21, seen=NOW); add(22, status="later"); add(23, status="ignored"); add(24, excluded="宗教"); add(25, status="adopted", pid="P5"); add(26, pid="P6")
d = rows()
ok(len(d["rows"]) == 3 and d["tab"] == "pending", f"default view = 待处理 (new + seen + later), adopted hidden ({len(d['rows'])})")
ok(d["tabs"] == {"pending": 3, "done": 2, "adopted": 2, "trash": 0}, f"tab counts {d['tabs']}")
ok(d["kpi"]["total"] == 5 and d["pool"]["total"] == 5 and d["groups"]["total"] == 5, "totals do not count adopted")
ok(len(rows("?tab=adopted")["rows"]) == 2 and len(rows("?tab=done")["rows"]) == 2, "已采用 / 已处理 tabs")
ok(all(y["status"] in ("", "later") for y in rows("?tab=pending")["rows"]), "pending contains no ignored")
ok(len(rows("?tab=pending&gk=site:makerworld")["rows"]) == 3 and len(rows("?gk=pg:ignored")["rows"]) == 1, "auto groups combine with the tab; pg: groups pick state themselves")
ok(len(rows("?status=all&ex=1")["rows"]) == 7, "old status / ex params still work")
C.post("/api/cur/candidates/delete", json={"ids": [cc.execute("SELECT id FROM cur_candidates WHERE skey='s:20'").fetchone()[0]]})
d = rows("?tab=trash")
ok(d["tabs"]["trash"] == 1 and len(d["trash"]) == 1 and d["trash"][0]["reason"] == "deleted" and d["trash"][0]["days_left"] in (6, 7) and d["rows"] == [], "回收站 tab lists binned rows")
ok(rows()["tabs"]["pending"] == 2, "deleted row leaves the pending count")
ok(C.get("/api/cur/overview").get_json()["cand"] == 2, "overview 候选 badge = pending only")

# ================= 4. 清理建议 + 按钮 =================
wipe()
for i in range(30, 33):
    add(i, status="ignored", ago=40)
add(33, status="ignored", ago=3)
for i in range(34, 36):
    add(i, excluded="宗教", ago=40)
add(36, score=10, ago=40); add(37, status="adopted", pid="P7", ago=90)
add(38, title="Same Title Model", author="Bob", score=70); add(39, title="same title model!", author="bob", score=50); add(40, title="Same-Title Model", author="BOB", score=40)
add(41, bad="标题是作者 / 店铺名")
sg = C.get("/api/cur/pool/suggestions").get_json()
by = {x["id"]: x for x in sg["items"]}
ok(set(by) == {"ignored", "excl", "low", "dup", "bad"} and "adopted" not in by, f"suggestion kinds {list(by)}")
ok(by["ignored"]["n"] == 3 and by["excl"]["n"] == 2 and by["low"]["n"] == 1 and by["dup"]["n"] == 2 and by["dup"]["groups"] == 1 and by["bad"]["n"] == 1, "suggestion counts (dup: 2 extra rows in 1 group)")
ok(len(by["ignored"]["items"]) == 3 and by["ignored"]["items"][0]["title"] and by["ignored"]["items"][0]["days"] >= 39, "each suggestion lists the affected candidates")
ok(by["dup"]["items"][0]["keep"].lower().startswith("same title") and by["ignored"]["mb"] < 1, "dup shows what is kept; sizes are tiny (UI hides < 1 MB)")
ok(sg["thresholds"] == {"excl_days": 30, "low_score": 40, "low_days": 30, "ignored_days": 30}, f"thresholds come from settings {sg['thresholds']}")
C.post("/api/cur/pool/settings", json={"ignored_days": "2"})
ok({x["id"]: x["n"] for x in C.get("/api/cur/pool/suggestions").get_json()["items"]}["ignored"] == 4, "changing the setting changes the suggestion")
C.post("/api/cur/pool/settings", json={"ignored_days": 30})
ok(N.post("/api/cur/pool/clean", json={"classes": ["ignored"]}).status_code == 403, "staff cannot run a suggestion")
r = C.post("/api/cur/pool/clean", json={"classes": ["ignored"]}).get_json()
ok(r["removed"] == 3 and gone("s:30") and cc.execute("SELECT COUNT(*) FROM cur_trash WHERE reason='ignored'").fetchone()[0] == 3, "ignored suggestion → bin + fingerprints kept")
r = C.post("/api/cur/pool/clean", json={"classes": ["dup"]}).get_json()
ok(r["removed"] == 2 and cc.execute("SELECT 1 FROM cur_candidates WHERE skey='s:38'").fetchone() and gone("s:39"), "dup suggestion → merged (best kept; cleaned ones keep the fingerprint as before)")
ok(C.post("/api/cur/candidates/delete-bad", json={}).get_json()["deleted"] == 1 and cc.execute("SELECT reason FROM cur_trash WHERE skey='s:41'").fetchone()[0] == "deleted" and not gone("s:41"),
   "bad-capture suggestion → recycle bin (restorable), no fingerprint")
sg = C.get("/api/cur/pool/suggestions").get_json()
ok({x["id"] for x in sg["items"]} == {"excl", "low"}, "ran suggestions disappear")

# ================= 5. 回收站 恢复 / 彻底删除 =================
n = C.post("/api/cur/pool/restore", json={"skeys": ["s:41", "s:30"]}).get_json()["restored"]
ok(n == 2 and cc.execute("SELECT status FROM cur_candidates WHERE skey='s:30'").fetchone()[0] == "ignored" and not gone("s:30"), "bin restore (single + batch)")
ok(N.post("/api/cur/pool/purge", json={"skeys": ["s:31"]}).status_code == 403, "staff cannot purge")
left = cc.execute("SELECT COUNT(*) FROM cur_trash").fetchone()[0]
r = C.post("/api/cur/pool/purge", json={"skeys": ["s:31"]}).get_json()
ok(r["purged"] == 1 and cc.execute("SELECT COUNT(*) FROM cur_trash").fetchone()[0] == left - 1 and gone("s:31"), "purge one: row gone, fingerprint stays")
r = C.post("/api/cur/pool/purge", json={"skeys": []}).get_json()
ok(r["purged"] == 0, "purge with empty selection deletes nothing")
r = C.post("/api/cur/pool/purge", json={}).get_json()
ok(r["purged"] == left - 1 and cc.execute("SELECT COUNT(*) FROM cur_trash").fetchone()[0] == 0, "empty the whole bin")

# ================= 6. 池子上限不动 + 前端 =================
wipe()
for i in range(50, 60):
    add(i, score=60 + i - 50)
add(60, status="adopted", pid="P1")
ok(pool.enforce_cap(10) == 0, "adopted rows do not count towards the cap; never-seen good ones are safe")
js = open(os.path.join(APP, "modules/curate/ui/curate.js"), encoding="utf-8").read()
for k in ("data-c-menu", "data-c-del", "data-c-edit", "data-c-tab", "data-cl-sg", "data-c-settings"):
    ok(k in js, f"UI has {k}")
ok("cleanDialog" not in js, "old clean dialog removed")
print("FAILED: " + " | ".join(FAILED) if FAILED else "all passed")
print("DONE errors=%d" % E_)
sys.exit(1 if E_ else 0)
