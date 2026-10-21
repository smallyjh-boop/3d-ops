# v2.38：已导出产品删 / 加 / 挪变体后，SKU 跟着变体走（以前按行号套回旧 SKU → 错位、重复）；上架检查拦重复 SKU
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, copy, time
D = T + "/m_sku238"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import store, lazada_template
C = A.app.test_client()
pid = next(it["id"] for it in store.list_products() if len({(v.get("opt1_zh") or "") for v in store.load(it["id"]).get("variants") or []}) >= 3)
p = store.load(pid); p["exported_at"] = time.time(); store.save(p)
K = lambda v: ((v.get("opt1_zh") or "").strip(), (v.get("opt2_zh") or "").strip())
get = lambda: C.get(f"/api/products/{pid}").get_json()
save = lambda body: C.post(f"/api/products/{pid}", json=body)
p0 = get()
orig = {K(v): v["sku"] for v in p0["variants"]}
ok(len(orig) >= 3 and all(orig.values()), f"start {list(orig.values())}")

# A：删掉第一行，后面的 SKU 不变
body = copy.deepcopy(p0); gone = body["variants"].pop(0)
r = save(body); p1 = r.get_json()
ok(r.status_code == 200 and all(v["sku"] == orig[K(v)] for v in p1["variants"]),
   f"delete first row keeps others' SKU {[(v.get('opt1_zh'), v['sku']) for v in p1['variants']]}")

# B：加一个新颜色（没有 SKU），插在中间；再把最后一行挪到最前
body = copy.deepcopy(p1)
new = dict(copy.deepcopy(body["variants"][0]), opt1_zh="红色", sku="")
body["variants"].insert(1, new)
body["variants"].insert(0, body["variants"].pop())
p2 = save(body).get_json()
skus = [v["sku"] for v in p2["variants"]]
ok(len(skus) == len(set(skus)), f"no duplicate SKU after add + reorder {skus}")
ok(all(v["sku"] == orig[K(v)] for v in p2["variants"] if v.get("opt1_zh") != "红色"),
   "existing variants keep their own SKU after reorder")
red = next(v for v in p2["variants"] if v.get("opt1_zh") == "红色")
ok(red["sku"] and red["sku"] not in orig.values(), f"new color gets a new SKU ({red['sku']})")

# C：删掉的颜色加回来 → 拿回原来的 SKU
body = copy.deepcopy(p2); body["variants"].append(dict(copy.deepcopy(gone), sku=""))
p3 = save(body).get_json()
back = next(v for v in p3["variants"] if K(v) == K(gone))
ok(back["sku"] == gone["sku"], f"re-added color gets its old SKU back ({back['sku']} vs {gone['sku']})")

# D：页面带了别的产品的 SKU / 重复 SKU → 不收
p3_by = {K(v): v["sku"] for v in p3["variants"]}
body = copy.deepcopy(p3); body["variants"][0]["sku"] = body["variants"][1]["sku"]
p4 = save(body).get_json(); skus = [v["sku"] for v in p4["variants"]]
ok(len(skus) == len(set(skus)) and all(v["sku"] == p3_by[K(v)] for v in p4["variants"]), f"client-sent wrong / duplicate SKU fixed {skus}")
# 改颜色名（SKU 已锁）→ 保留原 SKU
body = copy.deepcopy(p4); was = body["variants"][0]["sku"]; body["variants"][0]["opt1_zh"] = "浅" + body["variants"][0]["opt1_zh"]
p5 = save(body).get_json()
ok(p5["variants"][0]["sku"] == was, f"renamed color keeps its locked SKU ({p5['variants'][0]['sku']})")

# E：上架检查拦重复 SKU
q = copy.deepcopy(p5); q["variants"][1]["sku"] = q["variants"][0]["sku"]
errs, _w = lazada_template.check_product(q, {})
ok(any("SKU 重复" in e for e in errs), f"check_product flags duplicate SKU {[e for e in errs if 'SKU' in e]}")
print("ERRORS", E_)
