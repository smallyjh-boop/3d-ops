# 采集队列的速度和管理（扩展 3.1.2）：
#  · 模拟：N 个详情页 + 3N 个文件通过服务器的领活接口（/ext/next、/files/next），假扩展按 3.1.2 的循环（两条线并行、有活一直领、
#    按服务器给的 wait 睡），用假时钟跑（节奏是真的：详情页 4–12 秒、文件 8–20 秒、每个网站同时 2 个），断言在预计时间内做完；
#  · 卡住的任务超时放回队列、3 次算失败；下载进度 = 心跳；
#  · 候选 / 产品删掉了：任务自动取消（不算失败）；「删除采集错误的」连同它们的重新读取任务一起删；「清理失败 / 无效任务」；
#  · 队列管理：优先级、置顶 / 提前 / 推后 / 置底 / 拖动、暂停 / 继续一个任务或一个网站、批量删除（下载任务 = 只取消下载）、批量重试；
#  · 扩展的循环在无头 Chromium 里真跑一遍（queue_ext_check.js：假 ERP + 假模型网站，节奏缩小）。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, time, subprocess
D = T + "/m_curq"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, integrations
from core.config import save_config
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
from modules.curate import watch, db as cdb, cand
KEY = integrations.create_key("Nok")
H = {"Authorization": "Bearer " + KEY, "X-Ext-Version": "3.1.2"}
save_config({"ai_api_key": "", "cur_dl_speed": "normal"})


class Clock:
    """假时钟：watch.py 里所有的 time.time() 都走它（节奏、超时、速度都按它算），模拟几十分钟只要几秒。"""
    def __init__(self):
        self.t = time.time()
    def time(self):
        return self.t
    def __getattr__(self, k):
        return getattr(time, k)
CLK = Clock()
watch.time = CLK
q1 = lambda sql, a=(): cdb.conn().execute(sql, a).fetchone()[0]


def adopt(urls):
    r = C.post("/api/cur/candidates/adopt", json={"urls": "\n".join(urls)}).get_json()
    return [x["product_code"] for x in r["products"]]


def detail_data(item, n_files=3):
    base = item["url"].split("?")[0]
    host = "https://makerworld.com" if "makerworld" in base else "https://www.printables.com"
    return {"source_url": base, "title": item["title"] or "Model", "image_urls": [],
            "model_files": [{"name": f"part{k}.stl", "url": f"{host}/f/{item['id']}/{k}"} for k in range(n_files)], "license_name": "CC BY 4.0"}


def run_ext(dur_detail=8, dur_file=6, limit=4 * 3600, on_detail=None):
    """假扩展 3.1.2：两条线，各自领到活就再领，领不到按 wait 睡（最多 60 秒，= 闹钟），活做完（假时间 dur 秒后）交回。返回用了多少（假）秒。"""
    t0 = CLK.t
    run, until = [], {"detail": 0, "file": 0}
    while True:
        started = True
        while started:
            started = False
            for lane in ("detail", "file"):
                if sum(1 for x in run if x[1] == lane) >= 6 or until[lane] > CLK.t:
                    continue
                r = C.get("/api/v1/curate/ext/next" if lane == "detail" else "/api/v1/curate/ext/files/next?v=2", headers=H).get_json()
                job = r.get("item") if lane == "detail" else (r.get("files") or [None])[0]
                if job:
                    run.append((CLK.t + (dur_detail if lane == "detail" else dur_file), lane, job))
                    started = True
                else:
                    until[lane] = CLK.t + min(60, r.get("wait") or 60)
        left = q1("SELECT COUNT(*) FROM cur_collect WHERE state IN ('waiting','running')") + q1("SELECT COUNT(*) FROM cur_files WHERE kind<>'image' AND state IN ('queued','downloading')")
        if not run and not left:
            return CLK.t - t0
        if CLK.t - t0 > limit:
            return None
        CLK.t = min([x[0] for x in run] + [u for u in until.values() if u > CLK.t] + [CLK.t + 60])
        for x in [x for x in run if x[0] <= CLK.t]:
            run.remove(x)
            until = {"detail": 0, "file": 0}                 # 扩展做完一件：两条线都马上再问
            _, lane, job = x
            if lane == "detail":
                body = on_detail(job) if on_detail else {"id": job["id"], "data": detail_data(job)}
                C.post("/api/v1/curate/ext/result", json=body, headers=H)
            else:
                C.post(f"/api/v1/curate/ext/files/{job['id']}/upload?name={job['name']}", data=b"solid x\n" + b"0" * 300, headers={**H, "Content-Type": "application/octet-stream"})


# ---------- 1. 模拟：20 个产品（两个网站各 10 个），每个 3 个文件 ----------
N = 10
mw = [f"https://makerworld.com/en/models/{9000 + i}-model{i}" for i in range(N)]
pr = [f"https://www.printables.com/model/{8000 + i}-model{i}" for i in range(N)]
PIDS = adopt(mw + pr)
ok(len(PIDS) == 2 * N, f"adopted {len(PIDS)} products")
# 「删除采集错误的」以前留下的重新读取任务：候选已经没了（老版本扫一遍要白读这些页面）
cand.upsert([{"url": f"https://www.printables.com/model/{7000 + i}-x", "title": "Fluffy Tails", "author": "Fluffy Tails",
              "thumb": "https://media.printables.com/media/users/avatars/1/a.jpg"} for i in range(15)], "test")
bad_ids = [r[0] for r in cdb.conn().execute("SELECT id FROM cur_candidates WHERE capture_bad<>'' AND product_id=''")]
rq = C.post("/api/cur/candidates/recollect", json={"ids": bad_ids}).get_json()
ok(len(bad_ids) == 15 and rq["queued"] == 15, f"15 re-read jobs queued for bad candidates {len(bad_ids)} {rq}")
cdb.conn().execute("DELETE FROM cur_candidates WHERE id IN (%s)" % ",".join(str(i) for i in bad_ids[:10])); cdb.conn().commit()   # 老版本删掉的（任务留着）
r = C.post("/api/cur/candidates/delete-bad", json={}).get_json()
ok(r["deleted"] == 5 and r["jobs_canceled"] == 15 and q1("SELECT COUNT(*) FROM cur_collect WHERE kind='refresh'") == 0,
   f"删除采集错误的 also removes their re-read jobs (and the orphans left by the old version) {r}")
watch.reset()
T_NEW = run_ext()
files_ok = q1("SELECT COUNT(*) FROM cur_files WHERE kind<>'image' AND state='ok'")
ok(files_ok == 3 * 2 * N and q1("SELECT COUNT(*) FROM cur_collect WHERE state='done'") == 2 * N, f"all {2 * N} detail pages + {files_ok} files done")
# 预计：每个网站 10 个详情页 × 平均 8 秒 + 30 个文件 × 平均 14 秒（两条线并行，两个网站并行）≈ 7–8 分钟；以前（每分钟一次、文件按产品成批、产品之间停 45–90 秒）要 1 小时以上
ok(T_NEW is not None and T_NEW < 12 * 60, f"simulation: {2 * N} products / {files_ok} files in {T_NEW and round(T_NEW / 60, 1)} min (expected < 12 min)")
st = C.get("/api/cur/queue").get_json()["status"]
ok(st["rate"]["total"] > 3 and st["eta"] == 0 and st["left"] == {"detail": 0, "file": 0}, f"queue status: measured speed items/min {st['rate']}")
print(f"SIM new: {2 * N} detail + {files_ok} files in {T_NEW / 60:.1f} min = {(2 * N + files_ok) / (T_NEW / 60):.1f} items/min")

# 节奏是真的：同一个网站两次领活之间隔几秒（不是几分钟），同时最多 2 个
P2 = adopt([f"https://makerworld.com/en/models/{9100 + i}-m" for i in range(4)])
watch.reset()
a = C.get("/api/v1/curate/ext/next", headers=H).get_json()
b = C.get("/api/v1/curate/ext/next", headers=H).get_json()
ok(a["item"] and not b["item"] and 1 <= b["wait"] <= 13 and "按节奏" in b["reason"], f"detail pacing: next claim in a few seconds {b}")
CLK.t += 13
b = C.get("/api/v1/curate/ext/next", headers=H).get_json()
CLK.t += 13
c = C.get("/api/v1/curate/ext/next", headers=H).get_json()
ok(b["item"] and not c["item"] and "同时" in c["reason"] and c["wait"] <= 5, f"max 2 detail pages at once per site {c}")
qs = C.get("/api/cur/queue").get_json()["status"]
ok(len([x for x in qs["doing"] if x["lane"] == "detail"]) == 2 and qs["eta"] > 0 and any(s["key"] == "makerworld" and s["detail"]["running"] == 2 for s in qs["sites"]),
   f"queue status: what the extension is doing + ETA {qs['doing']} eta={qs['eta']}")

# ---------- 2. 卡住的任务：超时放回队列，3 次算失败 ----------
CLK.t += watch.COLLECT_STALL + 1
watch.reset()
a2 = C.get("/api/v1/curate/ext/next", headers=H).get_json()
ok(a2["item"] and a2["item"]["id"] == a["item"]["id"], f"stuck detail job released after {watch.COLLECT_STALL}s and handed out again")
ok(cdb.conn().execute("SELECT message FROM cur_collect WHERE id=?", (b["item"]["id"],)).fetchone()[0].startswith("上次读取超时"), "released job says why")
CLK.t += watch.COLLECT_STALL + 1
watch.reset()
ok(C.get("/api/v1/curate/ext/next", headers=H).get_json()["item"]["id"] == a["item"]["id"], "timed out twice → handed out a third time")
CLK.t += watch.COLLECT_STALL + 1
C.get("/api/v1/curate/ext/next", headers=H)
row = cdb.conn().execute("SELECT state, message FROM cur_collect WHERE id=?", (a["item"]["id"],)).fetchone()
ok(row["state"] == "failed" and watch.reason_code(row["message"]) == "timeout", f"3 timeouts → failed with a plain reason {dict(row)}")
# 文件：报进度 = 心跳；3 分钟没进度放回队列；被删掉的下载，扩展下次报进度时停下
cdb.conn().execute("UPDATE cur_collect SET state='done' WHERE state IN ('running','waiting')"); cdb.conn().commit()
adopt_p = P2[0]
cdb.conn().execute("INSERT INTO cur_files(product_id, platform, name, url, kind, state, created_at, updated_at) VALUES(?, 'makerworld', 'big.stl', 'https://makerworld.com/f/x/1', 'stl', 'queued', 0, 0)", (adopt_p,))
cdb.conn().execute("INSERT INTO cur_files(product_id, platform, name, url, kind, state, created_at, updated_at) VALUES(?, 'makerworld', 'big2.stl', 'https://makerworld.com/f/x/2', 'stl', 'queued', 0, 0)", (adopt_p,))
cdb.conn().commit()
watch.reset()
f1 = C.get("/api/v1/curate/ext/files/next", headers=H).get_json()["files"][0]
pg = C.post(f"/api/v1/curate/ext/files/{f1['id']}/progress", json={"got": 1000, "total": 4000}, headers=H).get_json()
ok(pg["ok"] and not pg["cancel"], "progress accepted")
jl = C.get("/api/cur/queue").get_json()["jobs"]
ok(any(j["id"] == f"f{f1['id']}" and j["state"] == "downloading" and j["got"] == 1000 and j["total"] == 4000 for j in jl), "download progress per file in the queue list")
CLK.t += watch.FILE_STALL - 10
watch.reset()
C.get("/api/v1/curate/ext/files/next", headers=H)               # 领走另一个；f1 还没超时
ok(cdb.conn().execute("SELECT state FROM cur_files WHERE id=?", (f1["id"],)).fetchone()[0] == "downloading", "download with recent heartbeat not released")
CLK.t += 20
watch.reset()
cdb.conn().execute("UPDATE cur_files SET beat=? WHERE state='downloading' AND id<>?", (CLK.t, f1["id"])); cdb.conn().commit()
C.get("/api/v1/curate/ext/files/next", headers=H)
ok(cdb.conn().execute("SELECT tries FROM cur_files WHERE id=?", (f1["id"],)).fetchone()[0] == 2, "stalled download (no progress for 3 min) released and handed out again")
r = C.post("/api/cur/jobs/action", json={"ids": [f"f{f1['id']}"], "action": "delete"}).get_json()
pg = C.post(f"/api/v1/curate/ext/files/{f1['id']}/progress", json={"got": 2000, "total": 4000}, headers=H).get_json()
ok(r["n"] == 1 and pg["cancel"] and cdb.conn().execute("SELECT state FROM cur_files WHERE id=?", (f1["id"],)).fetchone()[0] == "" and store.load(adopt_p),
   "deleting a download job only cancels that download (product kept); extension told to stop")
ff = C.post(f"/api/v1/curate/ext/files/{f1['id']}/fail", json={"error": "aborted"}, headers=H).get_json()
ok(ff.get("ignored"), "late failure report for a canceled download is ignored")
cdb.conn().execute("UPDATE cur_files SET state='ok' WHERE state IN ('queued','downloading')"); cdb.conn().commit()

# ---------- 3. 候选 / 产品删掉了：自动取消，不显示「失败」 ----------
P3 = adopt(["https://www.printables.com/model/8500-gone", "https://www.printables.com/model/8501-kept"])
store.delete(P3[0])
cdb.conn().execute("INSERT INTO cur_files(product_id, platform, name, url, kind, state, created_at, updated_at) VALUES(?, 'printables', 'a.stl', 'https://www.printables.com/f/1', 'stl', 'queued', 0, 0)", (P3[0],))
cdb.conn().commit()
watch.reset()
n = C.get("/api/v1/curate/ext/next", headers=H).get_json()
ok(n["item"] and "8501" in n["item"]["url"], f"job of the deleted product skipped {n}")
gone = cdb.conn().execute("SELECT state, hidden, message FROM cur_collect WHERE product_id=?", (P3[0],)).fetchone()
ok(gone["state"] == "canceled" and gone["hidden"] == 1 and watch.reason_code(gone["message"]) == "gone", f"auto-canceled, hidden from the queue (not failed) {dict(gone)}")
ok(C.get("/api/v1/curate/ext/files/next", headers=H).get_json()["product"] is None and not q1("SELECT COUNT(*) FROM cur_files WHERE product_id=?", (P3[0],)),
   "download jobs of a deleted product removed")
jl = C.get("/api/cur/queue").get_json()["jobs"]
ok(not any(j["product_id"] == P3[0] for j in jl) and not any(j["code"] == "gone" for j in jl), "no 读取失败 entries for deleted products in the queue")
C.post("/api/v1/curate/ext/result", json={"id": n["item"]["id"], "data": detail_data(n["item"], 0)}, headers=H)

# ---------- 4. 队列管理：优先级、排序、暂停 / 继续、批量删除 / 重试 ----------
P4 = adopt([f"https://makerworld.com/en/models/{9300 + i}-q" for i in range(5)])
ids = [r[0] for r in cdb.conn().execute("SELECT id FROM cur_collect WHERE product_id IN (%s) ORDER BY id" % ",".join("?" * 5), P4)]
order = lambda: [int(j["id"][1:]) for j in C.get("/api/cur/queue?lane=detail&state=waiting").get_json()["jobs"]]
ok(order() == ids, "default order = first come first served")
C.post("/api/cur/jobs/action", json={"ids": [f"c{ids[3]}"], "action": "prio", "prio": 1})
C.post("/api/cur/jobs/action", json={"ids": [f"c{ids[0]}"], "action": "prio", "prio": -1})
ok(order() == [ids[3], ids[1], ids[2], ids[4], ids[0]], f"priority high first, low last {order()}")
watch.reset()
ok(C.get("/api/v1/curate/ext/next", headers=H).get_json()["item"]["id"] == ids[3], "claim order respects priority")
cdb.conn().execute("UPDATE cur_collect SET state='waiting' WHERE id=?", (ids[3],)); cdb.conn().commit()
C.post("/api/cur/jobs/action", json={"ids": [f"c{ids[4]}"], "action": "top"})
ok(order()[0] == ids[4], f"置顶 {order()}")
C.post("/api/cur/jobs/action", json={"ids": [f"c{ids[4]}"], "action": "bottom"})
ok(order()[-1] == ids[4], f"置底 {order()}")
o = order(); C.post("/api/cur/jobs/action", json={"ids": [f"c{o[2]}"], "action": "up"})
ok(order()[1] == o[2], f"提前 {order()}")
o = order(); C.post("/api/cur/jobs/action", json={"ids": [f"c{o[0]}"], "action": "down"})
ok(order()[1] == o[0], f"推后 {order()}")
o = order(); C.post("/api/cur/jobs/action", json={"ids": [f"c{o[-1]}"], "action": "move", "before": f"c{o[0]}"})
ok(order()[0] == o[-1], f"drag to the front {order()}")
first = order()[0]
C.post("/api/cur/jobs/action", json={"ids": [f"c{first}"], "action": "hold"})
watch.reset()
nx = C.get("/api/v1/curate/ext/next", headers=H).get_json()
ok(nx["item"]["id"] != first and any(j["held"] for j in C.get("/api/cur/queue?state=held").get_json()["jobs"]), "paused job skipped, listed under 已暂停")
cdb.conn().execute("UPDATE cur_collect SET state='waiting' WHERE id=?", (nx["item"]["id"],)); cdb.conn().commit()
C.post("/api/cur/jobs/action", json={"ids": [f"c{first}"], "action": "resume"})
watch.reset()
ok(C.get("/api/v1/curate/ext/next", headers=H).get_json()["item"]["id"] == first, "resumed job goes first again")
cdb.conn().execute("UPDATE cur_collect SET state='waiting' WHERE id=?", (first,)); cdb.conn().commit()
# 一个网站暂停 / 继续
ok(C.post("/api/cur/sites/makerworld/hold", json={"on": True}).get_json()["ok"], "pause a site")
r = C.get("/api/v1/curate/ext/next", headers=H).get_json()
ok(r["item"] is None and "手动暂停" in r["reason"], f"paused site gets nothing {r}")
ov = C.get("/api/cur/queue").get_json()
ok(any(s["key"] == "makerworld" and s["held"] for s in ov["status"]["sites"]), "site pause shown in the queue status")
C.post("/api/cur/sites/makerworld/hold", json={"on": False})
ok(C.get("/api/v1/curate/ext/next", headers=H).get_json()["item"], "继续 → site works again")
# 风控 → 暂停到时间；「继续」马上恢复
r = C.post("/api/v1/curate/ext/result", json={"id": first, "error": "blocked", "status": 429}, headers=H).get_json()
ok(r["kind"] == "risk" and C.get("/api/v1/curate/ext/next", headers=H).get_json()["item"] is None, "429 → site auto-paused (captcha / 429 kept)")
C.post("/api/cur/sites/makerworld/hold", json={"on": False})
ok(C.get("/api/v1/curate/ext/next", headers=H).get_json()["item"], "继续 clears the risk pause")
# 批量删除：产品的详情页任务 = 取消、产品还在
C.post("/api/cur/jobs/action", json={"ids": [f"c{x}" for x in ids[:2]], "action": "delete"})
ok(all(store.load(p) for p in P4[:2]) and not any(int(j["id"][1:]) in ids[:2] for j in C.get("/api/cur/queue?lane=detail").get_json()["jobs"]),
   "bulk delete: jobs gone from the queue, products kept")
# 失败的批量重试
cdb.conn().execute("UPDATE cur_collect SET state='failed', message='页面上没读到模型资料（可能没加载完或网站改版了）：可以点「重试」' WHERE id IN (?,?)", (ids[2], ids[3])); cdb.conn().commit()
fj = [j for j in C.get("/api/cur/queue?state=failed").get_json()["jobs"] if int(j["id"][1:]) in (ids[2], ids[3])]
ok(len(fj) == 2 and all(j["code"] == "detail" for j in fj), "failed jobs filter + plain reason code")
r = C.post("/api/cur/jobs/action", json={"ids": [j["id"] for j in fj], "action": "retry"}).get_json()
ok(r["n"] == 2 and q1("SELECT COUNT(*) FROM cur_collect WHERE state='failed'") == 1, "bulk retry")      # 剩下第 2 节超时失败的那一个
# 清理失败 / 无效任务
cdb.conn().execute("INSERT INTO cur_collect(url, skey, title, product_id, pos, state, message, kind, created_at, updated_at) VALUES('https://www.printables.com/model/1-x', 'pr:1', 'x', '', 0, 'failed', '候选已经删掉了', 'refresh', 0, 0)")
cdb.conn().execute("INSERT INTO cur_files(product_id, platform, name, url, kind, state, error, created_at, updated_at) VALUES(?, 'makerworld', 'z.stl', 'https://makerworld.com/f/z', 'stl', 'failed', 'x', 0, 0)", (P4[4],))
cdb.conn().commit()
r = C.post("/api/cur/queue/cleanup", json={}).get_json()
ok(r["ok"] and r["orphans"] + r["collect"] >= 2 and r["files"] == 1 and not any(j["state"] == "failed" for j in C.get("/api/cur/queue").get_json()["jobs"]), f"清理失败 / 无效任务 {r}")
ok(C.post("/api/cur/jobs/action", json={"ids": [], "action": "delete"}).status_code == 400, "nothing selected → error")
# 设置里的上限
save_config({"cur_dl_hour_cap": 500, "cur_detail_conc": 3})
pc = watch.pacing()
ok(pc["file"]["cap"] == 500 and pc["detail"]["conc"] == 3 and pc["detail"]["gap"] == (4, 12) and pc["file"]["gap"] == (8, 20), f"pacing settings {pc}")
save_config({"cur_dl_hour_cap": 0, "cur_detail_conc": 2})
# 老扩展（3.1.1）也能用：文件一次一个
ok("files" in C.get("/api/v1/curate/ext/files/next", headers={**H, "X-Ext-Version": "3.1.1"}).get_json(), "old extension still gets the same /files/next shape")

# ---------- 5. 扩展的循环在无头 Chromium 里真跑（假 ERP + 假模型网站） ----------
node = shutil.which("node")
nodepath = os.pathsep.join(x for x in [os.environ.get("NODE_PATH", ""), "/opt/node-tools/node_modules"] if x)
have_pw = node and subprocess.run([node, "-e", "require('playwright')"], capture_output=True, env={**os.environ, "NODE_PATH": nodepath}).returncode == 0
if have_pw:
    out = subprocess.run([node, os.path.join(APP, "modules", "curate", "tests", "queue_ext_check.js"), os.path.join(APP, "extension")],
                         capture_output=True, text=True, timeout=240, env={**os.environ, "NODE_PATH": nodepath})
    if out.returncode:
        print(out.stderr[-1500:])
    res = json.loads((out.stdout or "{}").strip().splitlines()[-1] if out.stdout.strip() else "{}")
    if res.get("skip"):
        print("SKIP extension loop in Chromium:", res["skip"])
    else:
        ok(res.get("details") == res.get("want_details") and res.get("files") == res.get("want_files"), f"extension: all detail pages read + files uploaded {res}")
        ok(res.get("max_detail", 0) == 2 and res.get("max_file", 0) == 2, f"extension: 2 detail tabs + 2 downloads in parallel {res}")
        ok(res.get("secs", 99) < res.get("budget", 0), f"extension: finished in {res.get('secs')}s (no 1-minute alarm waits, budget {res.get('budget')}s)")
        ok(res.get("progress", 0) > 0, "extension: download progress reported")
        ok(res.get("stuck_retried"), "extension: a job the server never answered for does not block the loop")
else:
    print("SKIP extension loop in Chromium: no node / playwright")
print("ERRORS", E_)
