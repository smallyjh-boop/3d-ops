# v2.25：Lazada / Shopee 全部类目（类目树、全部模板自动下载、大类目库 AI 两步匹配、Shopee 必填属性）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, json, threading, http.server, functools, time
D = T + "/v225"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
TPL = D + "/tpl"; os.makedirs(TPL)
SRV = D + "/srv"; os.makedirs(SRV)
FIXT = os.path.join(APP, "templates_lazada", "lazada_3dprint_20cats.xlsx")
shutil.copy(FIXT, SRV + "/a.xlsx")
open(SRV + "/bad.xlsx", "w").write("not excel")
os.environ["LH_DATA_DIR"] = D; os.environ["LH_TEMPLATE_DIR"] = TPL; sys.path.insert(0, APP)
from core import categories, lazada_sync, shopee, attributes, ai_copy
E = 0
def ok(b, m):
    global E; print(("OK  " if b else "ERR ") + m); E += (not b)

# ---- 类目树：全部类目 ----
tr = categories.tree()
ok(len(tr) >= 2890 and sum(1 for _p, d in tr.values() if not d) >= 2890, f"lazada tree {len(tr)}")
st = shopee.tree()
ok(len(st) >= 2147, f"shopee tree {len(st)}")

# ---- 本地 HTTP 服务器模拟模板下载 ----
H = functools.partial(http.server.SimpleHTTPRequestHandler, directory=SRV)
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
H = functools.partial(Q, directory=SRV)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
idx = D + "/idx.json"
json.dump({"files": [{"cats": ["1"], "url": base + "/a.xlsx"}, {"cats": ["2"], "url": base + "/bad.xlsx"},
                     {"cats": ["3"], "url": base + "/missing.xlsx"}], "generated_at": "2026-10-07", "expires_at": "2027-10-01"}, open(idx, "w"))
lazada_sync.INDEX_PATH = idx
import core.lazada_sync as LS
_sleep = time.sleep
LS.time.sleep = lambda s: None
ok(categories.library() == [], "empty library before download")
r = lazada_sync.download_all()
ok(r["downloaded"] == 1 and len(r["failed"]) == 2 and r["total"] == 3, f"download_all {r}")
ok(os.path.exists(TPL + "/lazada_auto_000.xlsx") and not os.path.exists(TPL + "/lazada_auto_001.xlsx"), "only valid excel kept")
s = lazada_sync.status()
ok(s["files"] == 3 and s["downloaded"] == 1 and s["expires_at"] == "2027-10-01" and len(s["errors"]) == 2, f"status {s}")
ok(any("HTTP 404" in e for e in s["errors"]) and any("不是 Excel" in e for e in s["errors"]), f"errors explained {s['errors']}")
lib = categories.library()
ok(len(lib) >= 10 and all(c["template"] == "lazada_auto_000.xlsx" for c in lib), f"library from auto template {len(lib)}")
ok(categories.library() is lib, "library memoized")
c0 = lib[0]
ok(categories.by_cat_id(c0["cat_id"])["id"] == c0["id"] and categories.by_cat_id("nope") is None, "by_cat_id")
ok(os.path.exists(D + "/tpl_cache/lazada_auto_000.xlsx.json"), "parse disk cache written")
ok(os.path.exists(D + "/tpl_cache/lazada_auto_000.xlsx.sum.json") and len(categories._cache) <= categories._CACHE_MAX, "summary cache, memory bounded")
categories._cache.clear()
t0 = time.time(); categories.parse_cached(TPL + "/lazada_auto_000.xlsx"); ok(time.time() - t0 < 2, "disk cache read")
r2 = lazada_sync.download_all()
ok(r2["skipped"] == 1 and r2["downloaded"] == 0, f"second run skips existing {r2}")
os.makedirs(TPL + "/_deleted"); os.replace(TPL + "/lazada_auto_000.xlsx", TPL + "/_deleted/20261007_120000_lazada_auto_000.xlsx")
r3 = lazada_sync.download_all()
ok(r3["skipped"] == 1 and not os.path.exists(TPL + "/lazada_auto_000.xlsx"), f"deleted template not re-downloaded {r3}")
r3 = lazada_sync.download_all(force=True)
ok(r3["downloaded"] == 1 and os.path.exists(TPL + "/lazada_auto_000.xlsx"), "force re-downloads")
srv.shutdown()

# ---- web 接口 ----
import app as A
C = A.app.test_client()
g = C.get("/api/templates/sync").get_json()
ok(g["files"] == 3 and g["downloaded"] == 1, f"GET sync {g.get('files')} {g.get('downloaded')}")

# ---- 大类目库：AI 两步匹配 ----
attributes.BIG_LIBRARY = 3
leaf = c0["cat_id"]; leafpath = categories.path_of(leaf)
word = leafpath.split(" > ")[-1]
calls = []
def fake(cfg, system, user, image_b64=None):
    calls.append(user)
    if "search_keywords_th" in user and "Candidate" not in user:
        return json.dumps({"search_keywords_th": [word], "ideal_path_th": leafpath}, ensure_ascii=False)
    if "Candidate" in user:
        return json.dumps({"cat_id": leaf, "confidence": 0.9, "reason_zh": "合适", "reason_th": "ok", "path_zh": "路径"}, ensure_ascii=False)
    return "{}"
ai_copy.call = fake
cfg = {}
prod = {"name_zh": "测试产品", "features_zh": "x"}
m = attributes.match_category(cfg, prod)
ok(m["id"] == c0["id"] and m["status"] == "ai" and len(calls) == 2 and leaf in calls[1], f"big match {m}")
# 没模板的类目 → suggest
other = next(cid for cid, (p, d) in tr.items() if not d and not categories.by_cat_id(cid))
def fake2(cfg, system, user, image_b64=None):
    if "Candidate" in user:
        return json.dumps({"cat_id": other, "confidence": 0.8})
    return json.dumps({"search_keywords_th": [categories.path_of(other).split(" > ")[-1]]}, ensure_ascii=False)
ai_copy.call = fake2
m = attributes.match_category(cfg, prod)
ok(m["id"] == "" and m["suggest_id"] == other and m["suggest_path"], f"suggest when no template {m}")
def fake3(cfg, system, user, image_b64=None):
    return json.dumps({"search_keywords_th": ["zzqqxx不存在"], "cat_id": "999"})
ai_copy.call = fake3
m = attributes.match_category(cfg, prod)
ok(m["id"] == "" and "手动" in m["reason"], f"no candidates {m}")

# ---- Shopee 必填属性 ----
SC = "100003"
al = shopee.attrs_for(SC)
req = shopee.required_attrs(SC)
ok(al and req and al[0]["required"] and req[0]["values"] == [], "attrs_for required first / required_attrs no values")
a0 = next(a for a in al if a["required"] and a["values"])
p = {"name_zh": "x", "shopee_category": {"id": SC, "status": "ai"}, "copy": {"title_th": "ก" * 30, "description_th": "ข" * 80},
     "images": [{"url": "http://x/1.jpg"}], "variants": []}
_e, w = shopee.check_product(p, {}, {})
ok(any("必填属性" in x and a0["en"] in x for x in w), f"warn missing required {w}")
opt = a0["values"][0]
def fake4(cfg, system, user, image_b64=None):
    vals = {str(a["id"]): "random not in list" for a in al}
    vals[str(a0["id"])] = opt[1]
    return json.dumps({"values": vals}, ensure_ascii=False)
ai_copy.call = fake4
fv = shopee.fill_attrs({}, p)
ok(fv[str(a0["id"])]["value_id"] == opt[0] and fv[str(a0["id"])]["value_th"] == opt[2], f"fill picks option {fv.get(str(a0['id']))}")
ok(all(v["value_id"] is not None or not next(a for a in al if str(a["id"]) == k)["values"] or next(a for a in al if str(a["id"]) == k)["free"] for k, v in fv.items()), "non-options dropped")
p["shopee_attrs"] = {str(a["id"]): {"value": "v"} for a in req}
_e, w = shopee.check_product(p, {}, {})
ok(not any("必填属性" in x for x in w), "no warn when filled")
g = C.get("/api/shopee/attrs?id=" + SC).get_json()
ok(g["attrs"] and g["attrs"][0]["id"] == al[0]["id"], f"api attrs {str(g)[:120]}")
print("ERRORS", E)
