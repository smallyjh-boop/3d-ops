# 候选池（v2.53；v2.54.1：采用了的不算池子里的，只在 tab:adopted 里数）：自动分组（新发现 / 已看未处理 / 稍后看 / 已采用 / 已忽略 / 规则排除，分数段、来源网站、关注巡逻、类目）、采用 / 稍后看 / 忽略（忽略的不会回来）、
# 清理（预览个数 + MB、每一类、回收站恢复 / 到期删除、指纹挡住重新存）、自动清理 + 上限、重复合并、KPI、排除 / 低分只留指纹。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import json, os, shutil, sqlite3, sys, time
D = T + "/m_pool253"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
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
db.create_user("nok", "secret123", "listing", "Nok")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
N = A.app.test_client(); N.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
cc = cdb.conn()
pool.ensure()
NOW = time.time()
DAY = 86400
cc.execute("DELETE FROM cur_candidates"); cc.commit()
cc.execute("INSERT INTO cur_watches(id, kind, platform, value, url, label) VALUES(7, 'url', 'makerworld', 'x', 'https://w/7', '猫类巡逻')"); cc.commit()


def add(n, platform="makerworld", score=60, status="", excluded="", pid="", seen=0, ago=1, watch=0, cat="宠物", title=None, author="", metrics=None, thumb="https://t/x.jpg"):
    cc.execute("INSERT INTO cur_candidates(skey, platform, url, title, thumb, author, metrics, score, excluded, category, status, product_id, seen_at, first_seen, last_seen, watch_id) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (f"s:{n}", platform, f"https://x/{n}", title or f"Model {n} unique title", thumb, author, json.dumps(metrics or {}), score, excluded, cat, status, pid, seen,
                NOW - ago * DAY, NOW - ago * DAY, watch))
    cc.commit()


add(1)                                           # 新发现
add(2, seen=NOW)                                 # 已看未处理
add(3, status="later", seen=NOW)                 # 稍后看
add(4, status="adopted", pid="P1")               # 已采用
add(5, status="ignored")                         # 已忽略
add(6, excluded="儿童玩具（TISI）")                 # 规则排除
add(7, score=85, platform="printables", watch=7)  # 新发现 + 高分 + 巡逻
add(8, score=30, cat="")                         # 低分 + 未分类
d = C.get("/api/cur/candidates?gk=top:todo").get_json()
ok(len(d["rows"]) == 4, f"待看 = 新发现 + 已看未处理 (rows {len(d['rows'])})")
g = d["groups"]["n"]
ok(g["pg:new"] == 3 and g["pg:seen"] == 1 and g["pg:later"] == 1 and "pg:adopted" not in g and g["tab:adopted"] == 1 and g["pg:ignored"] == 1 and g["pg:excluded"] == 1, f"progress counts {g}")
ok(g["top:todo"] == 4 and g["top:hi"] == 1 and g["top:done"] == 1, f"top chips todo/hi/done {g['top:todo']}/{g['top:hi']}/{g['top:done']}")
ok(g["sc:high"] == 1 and g["sc:low"] == 1 and g["site:printables"] == 1 and g["wt:7"] == 1 and g["ct:none"] == 1, "score bands / site / watch / category")
ok(d["groups"]["watches"][0]["name"] == "猫类巡逻" and d["groups"]["sites"], "watch + site names in groups payload")
ok(len(C.get("/api/cur/candidates?gk=top:hi").get_json()["rows"]) == 1, "高分待看")
ok(len(C.get("/api/cur/candidates?gk=pg:ignored").get_json()["rows"]) == 1 and len(C.get("/api/cur/candidates?gk=pg:excluded").get_json()["rows"]) == 1, "ignored / excluded filters")
ok(len(C.get("/api/cur/candidates?gk=top:todo,site:printables").get_json()["rows"]) == 1, "groups combine (AND)")
# 操作：稍后看 / 忽略 / 标为已看
C.post("/api/cur/candidates/status", json={"ids": [1], "status": "later"})
C.post("/api/cur/candidates/status", json={"ids": [2], "status": "ignored"})
C.post("/api/cur/candidates/status", json={"ids": [7], "status": "seen"})
g = C.get("/api/cur/candidates").get_json()["groups"]["n"]
ok(g["pg:later"] == 2 and g["pg:ignored"] == 2 and g["pg:seen"] == 1 and g["pg:new"] == 1, f"later / ignore / seen move rows {g.get('pg:later')},{g.get('pg:ignored')},{g.get('pg:seen')},{g.get('pg:new')}")
ok(C.post("/api/cur/candidates/status", json={"ids": [1], "status": "bogus"}).status_code in (400, 500), "bad status rejected")
# 忽略的不会回来：再看到同一个模型，状态不变
url5 = "https://makerworld.com/en/models/55555-ignored-thing"
k5 = sites.source_key(url5)
cand.upsert([{"url": url5, "title": "Ignored thing", "author": "a", "thumb": "https://t/a.jpg", "metrics": {"likes": "9"}}])
cc.execute("UPDATE cur_candidates SET status='ignored' WHERE skey=?", (k5,)); cc.commit()
cand.upsert([{"url": url5, "title": "Ignored thing", "author": "a", "thumb": "https://t/a.jpg", "metrics": {"likes": "99"}}])
ok(cc.execute("SELECT status FROM cur_candidates WHERE skey=?", (k5,)).fetchone()[0] == "ignored", "seen again → still ignored")
# ---- 清理：每一类
cc.execute("DELETE FROM cur_candidates"); cc.execute("DELETE FROM cur_gone"); cc.execute("DELETE FROM cur_trash"); cc.commit()
add(11, excluded="宗教", ago=40)                  # excl 老
add(12, excluded="宗教", ago=5)                   # excl 新（不清）
add(13, score=20, ago=40)                         # low 老
add(14, score=20, ago=5)                          # low 新（不清）
add(15, status="ignored", ago=40)                 # ignored 老
add(16, status="ignored", ago=5)                  # ignored 新（不清）
add(17, status="adopted", pid="P9", watch=7)      # adopted
add(18, watch=99, ago=2)                          # 来自已删除的巡逻
add(19, title="Same Title Model", author="Bob", score=70, metrics={"likes": "100"}, platform="makerworld")
add(20, title="same title model!", author="bob", score=50, metrics={"likes": "500", "dl": "3"}, platform="printables")
add(21, title="Totally different", score=90)
pv = C.post("/api/cur/pool/preview", json={"opts": {}}).get_json()
cn = {x["id"]: x["n"] for x in pv["classes"]}
ok(cn == {"excl": 1, "low": 1, "ignored": 1, "adopted": 1, "dup": 1, "watchdel": 1}, f"preview counts per class {cn}")
ok(pv["total"] == 6 and pv["mb"] > 0 and all(x["mb"] > 0 for x in pv["classes"]) and pv["storage"]["candidates"] == 11, "preview total + MB + storage")
ok(cc.execute("SELECT COUNT(*) FROM cur_candidates").fetchone()[0] == 11, "preview changes nothing")
ok(C.post("/api/cur/pool/preview", json={"opts": {"excl_days": 3, "low_days": 3, "ignored_days": 3}}).get_json()["classes"][0]["n"] == 2, "preview honours day thresholds")
ok(N.post("/api/cur/pool/clean", json={"classes": ["excl"]}).status_code == 403, "staff cannot clean")
r = C.post("/api/cur/pool/clean", json={"classes": ["excl", "ignored"]}).get_json()
ok(r["removed"] == 2 and r["by_class"] == {"excl": 1, "ignored": 1}, f"clean only ticked classes {r}")
ok(cc.execute("SELECT COUNT(*) FROM cur_candidates").fetchone()[0] == 9 and cc.execute("SELECT COUNT(*) FROM cur_trash").fetchone()[0] == 2, "cleaned rows go to the recycle bin")
r = C.post("/api/cur/pool/clean", json={"classes": ["low", "adopted", "watchdel"]}).get_json()
ok(r["removed"] == 3, f"low + adopted + deleted-watch cleaned {r}")
# 重复合并：留数据最好的（分高的），指标取大
r = C.post("/api/cur/pool/clean", json={"classes": ["dup"]}).get_json()
w = cc.execute("SELECT * FROM cur_candidates WHERE skey='s:19'").fetchone()
ok(r["removed"] == 1 and w and json.loads(w["metrics"]) == {"likes": "500", "dl": "3"} and not cc.execute("SELECT 1 FROM cur_candidates WHERE skey='s:20'").fetchone(), "dedupe: keep best, merge metrics")
ok(cc.execute("SELECT COUNT(*) FROM cur_candidates").fetchone()[0] == 5, "remaining rows (12, 14, 16, 19, 21)")
# 回收站 / 指纹
tr = C.get("/api/cur/pool/info").get_json()
ok(len(tr["trash"]) == 6 and tr["storage"]["trash"] == 6 and tr["storage"]["gone"] == 6, "recycle bin lists cleaned rows")
cleaned = cc.execute("SELECT skey FROM cur_gone WHERE skey='s:15'").fetchone()
ok(bool(cleaned), "fingerprint kept")
url15 = "https://makerworld.com/en/models/15151-cleaned"
k15 = sites.source_key(url15)
cc.execute("INSERT INTO cur_gone(skey, reason, at, platform, watch_id) VALUES(?,?,?,?,?)", (k15, "ignored", NOW, "makerworld", 0)); cc.commit()
out = cand.upsert([{"url": url15, "title": "Cleaned", "author": "a", "thumb": "https://t/a.jpg"}])
ok(not cc.execute("SELECT 1 FROM cur_candidates WHERE skey=?", (k15,)).fetchone() and out[url15]["status"] == "ignored", "fingerprint blocks re-store")
n = C.post("/api/cur/pool/restore", json={"skeys": ["s:15", "s:11"]}).get_json()["restored"]
ok(n == 2 and cc.execute("SELECT status FROM cur_candidates WHERE skey='s:15'").fetchone()[0] == "ignored" and not cc.execute("SELECT 1 FROM cur_gone WHERE skey='s:15'").fetchone(), "restore from recycle bin (fingerprint released)")
cc.execute("UPDATE cur_trash SET trashed_at=? WHERE skey='s:13'", (NOW - 8 * DAY,)); cc.commit()
ok(pool.purge_expired() == 1 and not cc.execute("SELECT 1 FROM cur_trash WHERE skey='s:13'").fetchone() and cc.execute("SELECT 1 FROM cur_gone WHERE skey='s:13'").fetchone(), "7 days later purged, fingerprint stays")
ok(C.post("/api/cur/pool/purge").get_json()["purged"] >= 1, "empty recycle bin now")
# ---- 排除 / 低分只留指纹
url_ex = "https://makerworld.com/en/models/777-buddha-statue-religious"
cand.upsert([{"url": url_ex, "title": "Buddha statue 佛像", "author": "someone", "thumb": "https://t/b.jpg", "metrics": {"likes": "5"}}])
rw = cc.execute("SELECT * FROM cur_candidates WHERE skey=?", (sites.source_key(url_ex),)).fetchone()
ok(rw and (rw["excluded"] or rw["score"] < 15) and rw["thumb"] == "" and rw["metrics"] == "{}", f"excluded/very-low rows keep fingerprint only (excluded={rw['excluded'] if rw else None})")
# ---- 自动清理 + 上限
cc.execute("DELETE FROM cur_candidates"); cc.execute("DELETE FROM cur_trash"); cc.execute("DELETE FROM cur_gone"); cc.commit()
for i in range(100, 130):
    add(i, score=10 + i - 100, ago=1)               # 30 个新的，分数 10..39
add(200, status="later", score=1, ago=1)
add(201, excluded="宗教", ago=60)
add(202, status="ignored", ago=60)
C.post("/api/cur/pool/settings", json={"auto": True, "cap": 20, "low_score": 40})
ok(pool.settings()["cap"] == 20 and N.post("/api/cur/pool/settings", json={"cap": 1}).status_code == 403, "settings editable by owner only")
ok(C.post("/api/cur/pool/settings", json={"cap": "x"}).status_code in (400, 500), "bad number rejected")
cdb.put("pool_last", 0)
res = pool.auto_clean()
left = cc.execute("SELECT COUNT(*) FROM cur_candidates").fetchone()[0]
ok(res and res["by_class"]["excl"] == 1 and res["by_class"]["ignored"] == 1 and left == 20, f"auto-clean ran rules + cap ({left} left) {res}")
ok(cc.execute("SELECT 1 FROM cur_candidates WHERE skey='s:200'").fetchone() and not cc.execute("SELECT 1 FROM cur_candidates WHERE skey='s:100'").fetchone(), "cap drops low-score first, keeps 稍后看")
ok(not cc.execute("SELECT 1 FROM cur_gone WHERE skey='s:100'").fetchone() and cc.execute("SELECT 1 FROM cur_trash WHERE skey='s:100' AND reason='cap'").fetchone(), "cap-only cleanup: in recycle bin, NOT written to cur_gone (can come back)")
ok(cc.execute("SELECT 1 FROM cur_gone WHERE skey='s:202'").fetchone(), "ignored ones cleaned still keep their fingerprint")
# 第一天池子很大：从没看过、分数不低的新发现不会因为上限被清
cc.execute("DELETE FROM cur_candidates"); cc.execute("DELETE FROM cur_trash"); cc.execute("DELETE FROM cur_gone"); cc.commit()
for i in range(300, 330):
    add(i, score=60 + i - 300, ago=1)                  # 30 个从没看过、分数 >= 40
for i in range(330, 335):
    add(i, score=60, ago=1, seen=NOW - DAY)            # 5 个已看过没处理
add(335, status="ignored", ago=1)
add(336, score=5, ago=1)                               # 从没看过但分数很低
ok(pool.enforce_cap(20) == 7 and cc.execute("SELECT COUNT(*) FROM cur_candidates").fetchone()[0] == 30, "over-cap: only seen / ignored / low-score removed; never-seen good ones stay")
ok(not cc.execute("SELECT 1 FROM cur_candidates WHERE skey IN ('s:330','s:335','s:336')").fetchone() and cc.execute("SELECT COUNT(*) FROM cur_candidates WHERE skey BETWEEN 's:300' AND 's:329'").fetchone()[0] == 30, "the 30 new candidates all survive")
ok([r[0] for r in cc.execute("SELECT skey FROM cur_gone")] == ["s:335"], "only the ignored one got a fingerprint")
# 重新采集已有的稍后看（低于 junk 分）：作者 / 数据不清空
add(400, status="later", score=3, ago=1, author="keepme", metrics={"likes": "9"}, title="Later model unique 400")
cc.execute("UPDATE cur_candidates SET url='https://makerworld.com/en/models/400-later' WHERE skey='s:400'"); cc.commit()
cc.execute("UPDATE cur_candidates SET skey=? WHERE skey='s:400'", (sites.source_key("https://makerworld.com/en/models/400-later"),)); cc.commit()
cand.upsert([{"url": "https://makerworld.com/en/models/400-later", "title": "Later model unique 400", "author": "keepme", "metrics": {"likes": "9"}, "thumb": "https://t/a.jpg"}])
rl = cc.execute("SELECT author, metrics, status FROM cur_candidates WHERE skey=?", (sites.source_key("https://makerworld.com/en/models/400-later"),)).fetchone()
ok(rl and rl["author"] == "keepme" and json.loads(rl["metrics"]).get("likes") == "9" and rl["status"] == "later", "re-collect of existing 稍后看 below junk score keeps author / metrics")
ok(pool.auto_clean() is None, "auto-clean runs once a day")
C.post("/api/cur/pool/settings", json={"auto": False}); cdb.put("pool_last", 0)
ok(pool.auto_clean() is None, "auto-clean off")
# 缩略图缓存也清
td = pool.THUMB_DIR(); os.makedirs(td, exist_ok=True)
open(os.path.join(td, "orphan.jpg"), "wb").write(b"x" * 100)
ok(pool.clean_thumbs() == 1 and not os.path.exists(os.path.join(td, "orphan.jpg")), "orphan cached thumbnails cleaned")
# ---- KPI
cc.execute("DELETE FROM cur_candidates"); cc.execute("DELETE FROM cur_gone"); cc.commit()
add(301, platform="makerworld", status="adopted", pid="P1", watch=7)
add(302, platform="makerworld", watch=7)
add(303, platform="printables", ago=20)
add(304, platform="printables", excluded="宗教")
cc.execute("INSERT INTO cur_gone(skey, reason, at, platform, watch_id) VALUES('g1', 'adopted', ?, 'makerworld', 7)", (NOW,)); cc.commit()
kp = C.get("/api/cur/candidates").get_json()["pool"]
bs = {x["site"]: x for x in kp["by_site"]}
ok(kp["total"] == 3 and kp["new_week"] == 2 and kp["review"] == 2, f"KPI total / new this week / to review {kp['total']}/{kp['new_week']}/{kp['review']}")
ok(kp["adopted"] == 2 and kp["rate"] == round(100 * 2 / 4, 1), f"adoption rate {kp['rate']}")
ok(bs["makerworld"]["rate"] == round(100 * 2 / 3, 1) and bs["printables"]["rate"] == 0.0, "adoption rate per site")
ok(kp["by_watch"][0]["watch_id"] == 7 and kp["by_watch"][0]["name"] == "猫类巡逻" and kp["by_watch"][0]["adopted"] == 2, "adoption rate per watch")
# ---- 前端
js = open(os.path.join(APP, "modules/curate/ui/curate.js"), encoding="utf-8").read()
ok("GRP.html" in js and "CGS" in js.split("NAV.keep(")[1], "pool panel uses GRP + back-navigation keeps pool groups")
print("DONE errors=%d" % E_)
sys.exit(1 if E_ else 0)
