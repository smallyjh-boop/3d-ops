# v2.32：库存页分成「库存」和「物品资料」——没入过库的物品不出现在库存里，也不发补货提醒
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D = T + "/m_invviews"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, inventory as inv
C = A.app.test_client()
a = C.post("/api/inv/items", json={"name_zh": "测试胶带", "category": "pack", "unit": "卷", "reorder_point": 5}).get_json()["item"]
b = C.post("/api/inv/items", json={"name_zh": "测试纸箱", "category": "pack", "unit": "个", "reorder_point": 10}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": b["id"], "qty": 3}], "", "t")
st = C.get("/api/inv/items?view=stock&category=pack").get_json()
ids = [x["id"] for x in st["items"]]
ok(b["id"] in ids and a["id"] not in ids, "stock view hides never-stocked items")
ok(next(x for x in st["items"] if x["id"] == b["id"])["low"], "stocked item below reorder point is low")
al = [x["item_id"] for x in C.get("/api/inv/meta").get_json()["alerts"]]
ok(b["id"] in al and a["id"] not in al, "alerts only for stocked items")
allv = [x["id"] for x in C.get("/api/inv/items?view=all&category=pack").get_json()["items"]]
ok(a["id"] in allv and b["id"] in allv, "catalog shows all")
z = [x["id"] for x in C.get("/api/inv/items?view=zero&category=pack").get_json()["items"]]
ok(a["id"] in z and b["id"] not in z, "zero view")
cnt = st["counts"]["pack"]
ok(cnt["all"] >= 2 and cnt["zero"] >= 1 and cnt["low"] >= 1, f"counts {cnt}")
inv.create_doc("issue", [{"item_id": b["id"], "qty": 3}], "", "t")
st = C.get("/api/inv/items?view=stock&category=pack").get_json()
ok(b["id"] in [x["id"] for x in st["items"]], "used-up item that was stocked stays visible while below reorder point")
C.post("/api/inv/items", json={"id": a["id"], "active": 0, "name_zh": "测试胶带", "unit": "卷"})
ina = [x["id"] for x in C.get("/api/inv/items?view=inactive&category=pack").get_json()["items"]]
ok(a["id"] in ina, "inactive view")
ok(len(C.get("/api/inv/items?category=pack").get_json()["items"]) >= 1, "old api still works")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
