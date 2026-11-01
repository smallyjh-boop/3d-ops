# v2.54.1 复审修复：手动编辑过的候选不被自动清理 / 上限 / 去重动；去重留编辑过的并合并备注标签；
# 清除回收站 skeys 不是列表 → 400；删除过的再采到，备注 / 标签 / 手动分数带回。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import json, os, shutil, sqlite3, sys, time
D = T + "/m_pool2541b"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)


import app as A
from core import db
from modules.curate import cand, pool, sites, db as cdb

db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
cc = cdb.conn()
pool.ensure()
NOW = time.time(); DAY = 86400


def wipe():
    for t in ("cur_candidates", "cur_trash", "cur_gone"):
        cc.execute(f"DELETE FROM {t}")
    cc.commit()


def add(n, score=60, status="", excluded="", ago=1, title=None, author="", **kw):
    cc.execute("INSERT INTO cur_candidates(skey, platform, url, title, thumb, author, metrics, score, excluded, category, status, product_id, seen_at, first_seen, last_seen, watch_id, capture_bad) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (f"s:{n}", "makerworld", f"https://x/{n}", title or f"Model {n} unique title", "https://t/x.jpg", author, "{}", score, excluded, "宠物", status, "", 1,
                NOW - ago * DAY, NOW - ago * DAY, 0, ""))
    for k, v in kw.items():
        cc.execute(f"UPDATE cur_candidates SET {k}=? WHERE skey=?", (v, f"s:{n}"))
    cc.commit()
    return cc.execute("SELECT id FROM cur_candidates WHERE skey=?", (f"s:{n}",)).fetchone()[0]


def has(i):
    return bool(cc.execute("SELECT 1 FROM cur_candidates WHERE id=?", (i,)).fetchone())


def row(i):
    return cc.execute("SELECT * FROM cur_candidates WHERE id=?", (i,)).fetchone()


# ---- 1. 清理 / 上限不动编辑过的 ----
wipe()
S = {"excl_days": 30, "low_score": 40, "low_days": 30, "ignored_days": 30}
plain = add(1, score=10, ago=60)
e = {k: add(10 + i, score=10, ago=60, **{k: v}) for i, (k, v) in enumerate([("note", "keep me"), ("tags", '["a"]'), ("title_ovr", "My title"), ("score_ovr", 5), ("cat_ovr", 1)])}
ex_ed = add(20, excluded="宗教", ago=60, note="n")
ig_ed = add(21, status="ignored", ago=60, tags='["x"]')
ok(all(pool.edited(row(i)) for i in e.values()), "all five edit kinds count as edited")
ok(not pool.edited(row(plain)), "untouched row is not edited (score_ovr default -1)")
sel, _m = pool._select(S)
ok(set(sel["low"]) == {plain} and not sel["excl"] and not sel["ignored"], f"selection skips edited rows {sel['low']}")
ok(sel["_skipped"]["low"] == 5 and sel["_skipped"]["excl"] == 1 and sel["_skipped"]["ignored"] == 1, f"skipped counts {sel['_skipped']}")
pool.run(S, ["excl", "low", "ignored"])
ok(not has(plain) and all(has(i) for i in e.values()) and has(ex_ed) and has(ig_ed), "run() cleans only the untouched row")
wipe()
for i in range(6):
    add(30 + i, score=10, ago=5)
ed = add(40, score=10, ago=5, note="mine")
n = pool.enforce_cap(3)
ok(has(ed) and n >= 1, f"cap skips edited row (removed {n})")
wipe()
add(50, score=10, ago=60, note="x"); add(51, score=10, ago=60)
sg = C.get("/api/cur/pool/suggestions").get_json()
low = next(x for x in sg["items"] if x["id"] == "low")
ok(low["n"] == 1 and low["edited_skipped"] == 1, f"manual suggestion reports edited_skipped {low.get('edited_skipped')}")
js = open(os.path.join(APP, "modules/curate/ui/curate.js"), encoding="utf-8").read()
ok("edited_skipped" in js and "手动编辑过" in js and "แก้ไขเอง" in js, "UI shows bilingual edited-skipped note")

# ---- 2. 去重 ----
wipe()
a = add(60, score=90, ago=1, title="Same Dragon Model Title", author="bob")
b = add(61, score=20, ago=5, title="Same Dragon Model Title", author="bob", note="my note", tags='["t1","t2"]')
sel, mg = pool._select(S)
ok(mg.get(a) == b and b not in mg, f"edited row preferred over the higher-score one: merge={mg}")
pool.run(S, ["dup"])
ok(has(b) and not has(a), "dedupe keeps the edited row")
ok(row(b)["note"] == "my note" and json.loads(row(b)["tags"]) == ["t1", "t2"], "kept row keeps note / tags")
wipe()
a = add(62, score=90, title="Another Dragon Model", author="bob", note="n1")
b = add(63, score=20, title="Another Dragon Model", author="bob", note="n2")
pool.run(S, ["dup"])
ok(has(a) and has(b), "two edited duplicates are both kept")
wipe()
w = add(64, title="Merge Dragon Model", author="bob", note="keep", tags='["a","b"]')
lo = add(65, title="Merge Dragon Model", author="bob", note="other", tags='["b","c"]')
pool._merge_metrics(cc, w, [lo]); cc.commit()
r = row(w)
ok("keep" in r["note"] and "other" in r["note"] and json.loads(r["tags"]) == ["a", "b", "c"], f"merge unions note/tags {r['note']!r} {r['tags']}")

# ---- 3. purge skeys ----
wipe()
i = add(70); pool.delete_rows([i])
r = C.post("/api/cur/pool/purge", json={"skeys": "s:70"})
ok(r.status_code == 400 and cc.execute("SELECT COUNT(*) FROM cur_trash").fetchone()[0] == 1, f"skeys string -> 400, nothing purged ({r.status_code})")
r = C.post("/api/cur/pool/purge", json={"skeys": None})
ok(r.status_code == 400 and cc.execute("SELECT COUNT(*) FROM cur_trash").fetchone()[0] == 1, "skeys null -> 400")
r = C.post("/api/cur/pool/purge", json={"skeys": ["s:70"]})
ok(r.status_code == 200 and cc.execute("SELECT COUNT(*) FROM cur_trash").fetchone()[0] == 0, "skeys list purges those")
i = add(71); pool.delete_rows([i])
r = C.post("/api/cur/pool/purge", json={})
ok(r.status_code == 200 and cc.execute("SELECT COUNT(*) FROM cur_trash").fetchone()[0] == 0, "no skeys = purge all")

# ---- 4. 删除后再采到：带回备注 / 标签 / 分数 ----
wipe()
url = "https://makerworld.com/en/models/99999-carry-over"
cand.upsert([{"url": url, "title": "Carry over widget model", "author": "bob", "thumb": "https://t/a.jpg", "metrics": {"likes": "50"}}])
k = sites.source_key(sites.canonical(url))
cc.execute("UPDATE cur_candidates SET note='remember', tags='[\"gift\"]', title_ovr='Mine', score_ovr=77, cat_ovr=1, category='玩具' WHERE skey=?", (k,)); cc.commit()
i = cc.execute("SELECT id FROM cur_candidates WHERE skey=?", (k,)).fetchone()[0]
pool.delete_rows([i])
ok(not has(i), "deleted")
cand.upsert([{"url": url, "title": "Carry over widget model", "author": "bob", "thumb": "https://t/a.jpg", "metrics": {"likes": "60"}}])
r = cc.execute("SELECT * FROM cur_candidates WHERE skey=?", (k,)).fetchone()
ok(r and r["note"] == "remember" and json.loads(r["tags"]) == ["gift"] and r["title_ovr"] == "Mine" and r["score_ovr"] == 77 and r["cat_ovr"] == 1,
   "re-collected row keeps note / tags / title_ovr / score_ovr / cat_ovr")
ok(r and r["score"] == 77 and r["category"] == "玩具", "manual score / category applied to the new row")
ok(not cc.execute("SELECT 1 FROM cur_trash WHERE skey=?", (k,)).fetchone(), "trash row dropped")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
