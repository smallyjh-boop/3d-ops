# v2.55 采购按卷：补货建议带卷数 / 公斤 / 金额（补货线按卷或公斤）、改卷数生成采购单、到货入库按卷建料卷（返回编号、标签）、
# 在途的卷算进去不重复建议、树脂按瓶、其他物品照旧按个
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, re
D = T + "/m_pur255"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, inventory as inv, materials
C = A.app.test_client()
config.save_config({"review_enabled": False, "inv_loss_rate": 0})
CJK = re.compile(r"[一-鿿]")
item = lambda iid: inv.get_item(iid)

def fil(mat, col, **kw):
    return C.post("/api/inv/items", json={"name_zh": f"{mat} {col}", "category": "filament", "material": mat, "color": col, **kw}).get_json()["item"]
def sug(iid):
    return next((x for x in C.get("/api/inv/pur/suggest?all=1").get_json()["rows"] if x["item"]["id"] == iid), None)

sup = inv.save_supplier({"name": "卷料店", "currency": "THB"}, "t")
pla = fil("PLA", "红色", roll_g=1000, supplier_id=sup["id"])
inv.create_doc("purchase", [{"item_id": pla["id"], "rolls": 1, "unit_cost": 0.25}], "", "t")
inv.consume_production("PLA", "红色", 600, "打印完成 t", "t", None, "run:1")      # 剩 400 g：1 卷（开封）
C.post("/api/inv/items", json={"id": pla["id"], "reorder_unit": "roll", "reorder_value": 2, "reorder_qty_value": 4})

# ---------- 补货建议：卷数 + 公斤 + 金额 ----------
r = sug(pla["id"])
ok(r and r["rolls"] == 4 and r["net_g"] == 1000 and r["qty"] == 4000 and r["qty_kg"] == 4.0, f"suggest 4 rolls = 4 kg {r and (r['rolls'], r['qty_kg'])}")
ok(r["urgency"] in ("yellow", "red") and "reorder" in r["why"], f"below the 2-roll line ({r['urgency']}, {r['why']})")
ok(r["stock"]["rolls"] == 1 and r["stock"]["text_zh"] == "1 卷（1 开封卷）· 400 g" and r["stock"]["text_th"] == "1 ม้วน (1 ม้วนเปิดแล้ว) · 400 g", r["stock"]["text_zh"])
ok(r["reorder_zh"] == "2 卷" and r["reorder_th"] == "2 ม้วน" and not CJK.search(r["reorder_th"] + r["stock"]["text_th"]), "reorder line + Thai texts")
ok(r["est_cost"] and abs(r["est_cost"] - 4000 * r["unit_price"]) < 0.01, f"amount {r['est_cost']} (cost 250 per kg -> 4 kg = 1000)")
# 改成公斤的补货线：库存 0.4 kg，线 0.3 kg -> 不再建议
C.post("/api/inv/items", json={"id": pla["id"], "reorder_unit": "kg", "reorder_value": 0.3, "reorder_qty_value": 3})
r = sug(pla["id"])
ok(r is None or "reorder" not in r["why"], "kg line 0.3: 400 g is above it")
C.post("/api/inv/items", json={"id": pla["id"], "reorder_unit": "kg", "reorder_value": 0.5, "reorder_qty_value": 3})
r = sug(pla["id"])
ok(r and "reorder" in r["why"] and r["rolls"] == 3 and r["qty_kg"] == 3.0, f"kg line 0.5: buy 3 kg = 3 rolls {r and r['rolls']}")

# ---------- 改卷数 -> 采购单草稿（卷 + 公斤 + 金额，单价仍按公斤算） ----------
po = C.post("/api/inv/pur/suggest/po", json={"rows": [{"item_id": pla["id"], "rolls": 5, "supplier_id": sup["id"]}]}).get_json()
ok(po["ok"] and len(po["po"]) == 1, f"po from suggestion {po.get('error', '')}")
p = po["po"][0]; ln = p["lines"][0]
ok(ln["rolls"] == 5 and ln["net_g"] == 1000 and ln["qty"] == 5000 and abs(p["goods_total_cur"] - 1250) < 0.01, f"PO 5 rolls = 5 kg = {p['goods_total_cur']} (cost per kg 250)")
inv.po_action(p["id"], "order", "t")
r = sug(pla["id"])
ok(r is None or (r["transit_rolls"] == 5 and r["qty"] == 0), "5 rolls on the way -> no second suggestion")

# ---------- 到货入库：5 卷 = 5 条料卷 + 编号 ----------
n0 = len(materials.spools("PLA", "红色", status="active"))
res = C.post("/api/inv/pur/receive", json={"po_id": p["id"], "qtys": {str(ln["id"]): 3}}).get_json()
ok(res["ok"] and len(res["spools"]) == 3 and len(set(res["spools"])) == 3, f"receive 3 of 5 rolls -> {res.get('spools')}")
ok(len(materials.spools("PLA", "红色", status="active")) == n0 + 3 and abs(item(pla["id"])["qty"] - 3400) < 1e-6, "3 sealed spools created, 3.4 kg")
ok(C.get(f"/print/spools?ids={','.join(res['spools'])}").status_code == 200, "roll labels")
bad = C.post("/api/inv/pur/receive", json={"po_id": p["id"], "qtys": {str(ln["id"]): 2.5}}).get_json()
ok(not bad.get("ok"), "half roll refused")
res2 = C.post("/api/inv/pur/receive", json={"po_id": p["id"], "qtys": {str(ln["id"]): 2}}).get_json()
ok(res2["ok"] and len(res2["spools"]) == 2 and not set(res2["spools"]) & set(res["spools"]) and res2["po"]["status"] == "received", "second delivery: 2 more rolls, PO received")
u = C.get("/api/inv/items?view=stock&category=filament").get_json()["items"]
ur = next(x for x in u if x["id"] == pla["id"])["units"]
ok(ur["rolls"] == 6 and ur["sealed"] == 5 and ur["open"] == 1 and ur["text_zh"] == "6 卷（5 整卷 + 1 开封卷）· 5.4 kg", ur["text_zh"])

# ---------- 树脂：按瓶 ----------
rz = fil("RESIN", "透明", roll_g=1000, supplier_id=sup["id"])
inv.create_doc("purchase", [{"item_id": rz["id"], "rolls": 1, "unit_cost": 0.6}], "", "t")
C.post("/api/inv/items", json={"id": rz["id"], "reorder_unit": "roll", "reorder_value": 2, "reorder_qty_value": 3})
r = sug(rz["id"])
ok(r and r["rolls"] == 3 and r["stock"]["kind"] == "bottle" and r["reorder_zh"] == "2 瓶" and r["reorder_th"] == "2 ขวด", f"resin suggestion in bottles {r and (r['rolls'], r['reorder_zh'])}")
po2 = C.post("/api/inv/pur/suggest/po", json={"rows": [{"item_id": rz["id"], "supplier_id": sup["id"]}]}).get_json()
ok(po2["ok"] and po2["po"][0]["lines"][0]["rolls"] == 3, "resin PO in bottles")

# ---------- 其他物品不变 ----------
pt = C.post("/api/inv/items", json={"name_zh": "螺丝", "category": "part", "unit": "个", "reorder_point": 50, "reorder_qty": 200, "supplier_id": sup["id"]}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": pt["id"], "qty": 20, "unit_cost": 1}], "", "t")
r = sug(pt["id"])
ok(r and r["rolls"] is None and r["qty_kg"] is None and r["stock"] is None and r["qty"] >= 200, f"part: pieces {r and r['qty']}")
print("ERRORS", E_)
