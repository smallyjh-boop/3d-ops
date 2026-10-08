# v2.31.1：编辑页保存过、从没导出过的产品（listing 存成了 null）导出上架表格不再报错
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, json
D = T + "/m_listing"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import store, listing
C = A.app.test_client()
pid = store.list_products()[0]["id"]
p = store.load(pid)
raw = json.load(open(os.path.join(store.PRODUCTS_DIR, pid + ".json"), encoding="utf-8")); raw["listing"] = None
json.dump(raw, open(os.path.join(store.PRODUCTS_DIR, pid + ".json"), "w", encoding="utf-8"))
ok(store.load(pid)["listing"] == {}, "load normalizes null listing")
p = dict(raw); listing._set(p, "lazada", "pending", user="t")
ok(p["listing"]["lazada"]["status"] == "pending", "_set works on null listing")
# 编辑页保存不再存成 null
q = store.load(pid); q.pop("listing", None)
C.post(f"/api/products/{pid}", json=q)
ok(isinstance(json.load(open(os.path.join(store.PRODUCTS_DIR, pid + ".json"), encoding="utf-8")).get("listing"), dict), "editor save keeps listing a dict")
# 并发保存不会互相搬走临时文件
import threading
errs = []
def w():
    try:
        for _ in range(30):
            store.save(store.load(pid))
    except Exception as e:  # noqa: BLE001
        errs.append(e)
ts = [threading.Thread(target=w) for _ in range(4)]; [t.start() for t in ts]; [t.join() for t in ts]
ok(not errs, f"concurrent saves ok {errs[:1]}")
r = C.post("/api/export", json={"ids": [pid]})
ok(r.status_code != 500, f"export with null listing doesn't crash ({r.status_code} {r.get_data(as_text=True)[:120]})")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
