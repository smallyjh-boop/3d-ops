# v2.43：上架工作台——缺什么（带修复方式）、原地确认类目 / 属性 / 尺寸、AI 补齐（假 AI）、Lazada 审核结果自动同步、推送走后台任务
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, time
D = T + "/m_lw243"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, integrations, listing, attributes, ai_copy
from core.connectors import lazada as LZ
from modules.listing import workbench, lazada_push
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("nok", "secret123", "listing", "Nok")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
N = A.app.test_client(); N.post("/api/auth/login", json={"username": "nok", "password": "secret123"})

# ---------- 缺什么 + 修复方式 ----------
P = "3DP0015"
p = store.load(P)
p["category"]["status"] = "check"
k0 = next(iter(p["attributes"]))
p["attributes"][k0]["status"] = "check"
p["package_status"] = "check"
store.save(p)
r = C.get(f"/api/listing/issues/{P}?platform=lazada").get_json()
fixes = {x["fix"] for x in r["errors"]}
ok({"confirm_cat", "confirm_attr", "confirm_pkg"} <= fixes, f"fix kinds {fixes}")
ok(r["category"] and any(a["key"] == k0 for a in r["check_attrs"]) and r["package"].get("length"), "category name / attrs / package given")
for act in ("confirm_cat", "confirm_attr", "confirm_pkg"):
    r = N.post(f"/api/listing/fix/{P}", json={"action": act}).get_json()      # 上架客服也能确认
ok(not r["errors"] or not ({x["fix"] for x in r["errors"]} & {"confirm_cat", "confirm_attr", "confirm_pkg"}), f"all confirmed {r['errors']}")
q = store.load(P)
ok(q["category"]["status"] == "manual" and q["attributes"][k0]["status"] == "manual" and q["package_status"] == "manual", "saved as manual")
ok(C.post(f"/api/listing/fix/{P}", json={"action": "nope"}).status_code == 400, "bad action refused")
ok(C.get("/api/listing/issues/NOPE").status_code == 404, "unknown product 404")
pid2 = "3DP0002"
r = C.get(f"/api/listing/issues/{pid2}?platform=shopee").get_json()
ok(isinstance(r["errors"], list) and all(x["fix"] in ("ai", "edit", "confirm_cat", "confirm_attr", "confirm_pkg") for x in r["errors"]), "shopee issues")

# ---------- AI 补齐（假 AI） ----------
p = store.load(pid2); cat_before = p["category"]; p["category"] = {}; p["attributes"] = {}; store.save(p)
calls = []
attributes.match_category = lambda cfg, prod: calls.append("cat") or {"id": cat_before["id"], "status": "auto"}
attributes.fill = lambda cfg, prod, cat, use_ai=True: (calls.append("attrs") or {"catProperty.p-20000": {"value": "No Brand", "status": "auto"}}, None)
ai_copy.missing_copy = lambda prod: (["title_en"], [])
ai_copy.complete_copy = lambda cfg, prod, plan=None: calls.append("copy") or {"title_en": "Moon lamp"}
ai_copy.apply_completion = lambda prod, out: prod.setdefault("copy", {}).update(out)
r = C.post("/api/listing/ai-fill", json={"product_ids": [pid2], "platform": "lazada"}).get_json()
q = store.load(pid2)
ok(r["done"] and set(r["done"][0]["did"]) == {"类目", "属性", "文案"} and q["category"]["id"] == cat_before["id"]
   and q["attributes"] and q["copy"]["title_en"] == "Moon lamp", f"ai fill {r}")
def boom(cfg, prod, plan=None):
    raise ai_copy.AIError("没有 AI 密钥")
ai_copy.complete_copy = boom
r = C.post("/api/listing/ai-fill", json={"product_ids": [pid2, "3DP0003", "3DP0004"]}).get_json()
ok(len(r["failed"]) == 1 and "密钥" in r["failed"][0]["error"], f"stops on missing key {r['failed']}")
r = C.post("/api/listing/ai-fill?async=1", json={"product_ids": [pid2]})
ok(r.status_code == 202 and r.get_json()["job"], "ai fill runs as background job")

# ---------- Lazada 审核结果同步 ----------
integrations.save_shop({"platform": "lazada", "name": "LZ", "enabled": True,
                        "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})
items = {"3DP0005": (501, "Active", {}), "3DP0007": (502, "Suspended", {"suspendedSkus": [{"rejectReason": "Image has watermark"}]}),
         "3DP0009": (503, "Pending QC", {}), "3DP0011": (504, "InActive", {})}
for pid, (iid, _s, _x) in items.items():
    q = store.load(pid); q["lazada_api"] = {"item_id": iid, "skus": {}}; listing._set(q, "lazada", "uploaded"); store.save(q)
q = store.load("3DP0013"); listing._set(q, "lazada", "uploaded"); store.save(q)          # 用表格上传的：不查
by_id = {iid: (s, x) for _p, (iid, s, x) in items.items()}
seen = []
def fake_call(self, path, params, base=LZ.API, token=True, method="GET"):
    seen.append(path)
    s, x = by_id[int(params["item_id"])]
    return {"code": "0", "data": {"item_id": params["item_id"], "status": s, **x}}
LZ.LazadaConnector._call = fake_call
r = C.post("/api/listing/lazada/status-sync", json={}).get_json()
st = {pid: listing.status_of(store.load(pid), "lazada") for pid in list(items) + ["3DP0013"]}
ok(r["checked"] == 4 and len(r["changed"]) == 3, f"checked / changed {r}")
ok(st["3DP0005"]["status"] == "live" and st["3DP0007"]["status"] == "rejected" and "watermark" in st["3DP0007"].get("note", "")
   and st["3DP0009"]["status"] == "uploaded" and st["3DP0011"]["status"] == "inactive" and st["3DP0013"]["status"] == "uploaded", f"statuses {st}")
ok(store.load("3DP0005")["lazada_api"]["platform_status"] == "Active", "raw platform status kept")
ok(listing.status_of(store.load("3DP0005"), "lazada").get("first_listed_at"), "first listed time recorded (测款期起点)")
r = C.post("/api/listing/lazada/status-sync", json={}).get_json()
ok(not r["changed"], "second sync: nothing changes")
# 有修改待同步的：上线了也保持「待同步」
q = store.load("3DP0005"); listing._set(q, "lazada", "update"); store.save(q)
C.post("/api/listing/lazada/status-sync", json={"product_ids": ["3DP0005"]})
ok(listing.status_of(store.load("3DP0005"), "lazada")["status"] == "update", "update kept")
# 推送走后台任务
r = C.post("/api/listing/lazada/push?async=1", json={"product_ids": ["3DP0015"], "force": True})
ok(r.status_code == 202 and r.get_json()["job"], "push runs as background job")
for _ in range(50):
    j = C.get(f"/api/bg/{r.get_json()['job']}").get_json()
    if j["status"] in ("done", "error"):
        break
    time.sleep(0.2)
ok(j["status"] == "done" and "ok" in (j.get("result") or {}), f"job finished {j.get('status')} {str(j.get('result'))[:120]}")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
