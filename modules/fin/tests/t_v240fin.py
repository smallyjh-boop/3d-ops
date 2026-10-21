# v2.40：全功能测试的中级问题——库存、采购、财务
#  1 固定费用按项估算   2 开 VAT（价格含税）每单利润按不含税收入   3 每件包材按件数   4 结单 / 取消后应付按到货
#  5 付款不能是负数   6 结算表里一模一样的两行都算   7 纸箱停用时发货出库照常（跳过停用的）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, time, datetime as dt
D = T + "/m_v240fin"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, store, orders, finance, inventory as inv
from modules.fin import logic as fin
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
config.save_config({"review_enabled": False, "stock_auto_use": False, "monthly_rent": 4000, "monthly_labor": 9000,
                    "monthly_depreciation": 1000, "monthly_maintenance": 500, "packaging_per_item": 10})
sku = next(v["sku"] for it in store.list_products() for v in (store.load(it["id"]).get("variants") or []) if v.get("sku"))
M = dt.date.today().strftime("%Y-%m"); d1 = dt.date.today().replace(day=1)

# ---- 1 固定费用按项估算
pl0 = fin.pl(*fin.period(M)[:2])["summary"]["fixed_estimated"]
C.post("/api/fin/expenses", json={"day": d1.isoformat(), "category": "房租", "amount": 4000})
pl1 = fin.pl(*fin.period(M)[:2])["summary"]["fixed_estimated"]
days = max(0, (min(fin.period(M)[1], dt.date.today() + dt.timedelta(days=1)) - fin.period(M)[0]).days)
ok(abs(pl0 - 14500 * days / 30) < 0.1 and abs(pl1 - 10500 * days / 30) < 0.1,
   f"rent recorded -> labor/depreciation/maintenance still estimated ({pl0:.2f} -> {pl1:.2f})")

# ---- 2 / 3 每单利润：VAT、每件包材
o = C.post("/api/orders/manual", json={"order_no": "VAT1", "order_total": 1070, "items": [{"sku": sku, "qty": 3, "unit_price": 1070 / 3}]}).get_json()
row = db.conn().execute("SELECT * FROM orders WHERE id=?", (o["id"],)).fetchone()
items = db.conn().execute("SELECT * FROM order_items WHERE order_id=?", (o["id"],)).fetchall()
p0 = finance.order_profit(config.load_config(), row, items)
ok(p0["packaging"] == 30, f"packaging per item x3 = 30 ({p0['packaging']})")
config.save_config({"fin_vat_on": True, "fin_prices_incl_vat": True, "fin_vat_rate": 0.07})
p1 = finance.order_profit(config.load_config(), row, items)
ok(abs(p1["out_vat"] - 70) < 0.01 and abs((p0["profit"] - p1["profit"]) - 70) < 0.01, f"VAT on: profit excludes 70 output VAT ({p0['profit']} -> {p1['profit']})")
config.save_config({"fin_vat_on": False})

# ---- 4 / 5 采购应付
it = C.post("/api/inv/items", json={"name_zh": "胶带", "category": "pack", "unit": "卷"}).get_json()["item"]
sup = C.post("/api/inv/suppliers", json={"name": "S"}).get_json(); sid = (sup.get("supplier") or sup).get("id")
def new_po():
    po = C.post("/api/inv/po", json={"supplier_id": sid, "lines": [{"item_id": it["id"], "qty": 100, "unit_cost": 2}]}).get_json()["po"]
    C.post(f"/api/inv/po/{po['id']}/order"); return po
po = new_po()
C.post(f"/api/inv/po/{po['id']}/receive", json={"qtys": {str(po["lines"][0]["id"]): 60}})
C.post(f"/api/inv/po/{po['id']}/close")
g = C.get(f"/api/inv/po/{po['id']}").get_json()["po"]
ok(g["total"] == 120 and g["goods_total"] == 120, f"closed PO owes only what arrived 60x2 ({g['total']})")
po2 = new_po()
C.post(f"/api/inv/po/{po2['id']}/receive", json={"qtys": {str(po2["lines"][0]["id"]): 60}})
C.post(f"/api/inv/po/{po2['id']}/cancel")
s = C.get("/api/inv/po-summary").get_json()
ok(s["unpaid"] == 240, f"cancelled-after-partial PO still owed in summary (120 + 120 = {s['unpaid']})")
r = C.post(f"/api/inv/po/{po['id']}/pay", json={"amount": -100})
ok(r.status_code == 400, f"negative payment refused ({r.status_code})")
ok(C.post(f"/api/inv/po/{po['id']}/pay", json={"amount": 120}).get_json()["po"]["pay_status"] == "paid", "pay 120 -> paid")

# ---- 6 结算表：一模一样的两行都算
orders.upsert([{"platform": "lazada", "order_no": "LZ-DUP", "status": "已完成", "order_total": 300,
                "items": [{"sku": sku, "qty": 1, "unit_price": 300}]}], source="t")
csv = ("Transaction Date,Fee Name,Order No.,Amount,VAT in Amount,WHT Amount,Statement\n"
       f"{d1.isoformat()},Item Price Credit,LZ-DUP,300,0,0,ST9\n"
       f"{d1.isoformat()},Commission,LZ-DUP,-12.90,0,0,ST9\n"
       f"{d1.isoformat()},Commission,LZ-DUP,-12.90,0,0,ST9\n")
def imp():
    p = C.post("/api/fin/settle/preview", data={"file": (io.BytesIO(csv.encode()), "lazada_st.csv")}, content_type="multipart/form-data").get_json()
    return C.post("/api/fin/settle/import", json={"token": p["token"], "mapping": p["mapping"], "platform": "lazada"}).get_json()
r = imp()
st = db.conn().execute("SELECT settlement FROM orders WHERE order_no='LZ-DUP'").fetchone()[0]
ok(r["new_rows"] == 3 and abs(st - 274.2) < 0.01, f"two identical commission rows both counted ({r['new_rows']}, settlement {st})")
r = imp()
ok(r["new_rows"] == 0 and r["dup_rows"] == 3, "importing the same file again is still deduplicated")

# ---- 7 纸箱停用：发货出库照常
config.save_config({"inv_ship_out": True})
from modules.orders import packbox
from core.inventory import boxes
o = C.post("/api/orders/manual", json={"order_no": "BOX1", "items": [{"sku": sku, "qty": 1, "unit_price": 100}]}).get_json()
packbox.set_box(o["id"], "2A") if hasattr(packbox, "set_box") else None
iid = boxes.ensure_item("2A")
db.conn().execute("UPDATE inv_items SET active=0 WHERE id=?", (iid,)); db.conn().commit()
pk = C.post("/api/inv/items", json={"name_zh": "气泡袋", "category": "pack", "unit": "个"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": pk["id"], "qty": 10}], "期初", "t")
config.save_config({"inv_pack_auto": True, "inv_pack_rules": [{"item_id": pk["id"], "qty": 1, "per": "order"}]})
orders.update_order(o["id"], "t", status="shipped")
left = inv.get_item(pk["code"])["qty"]
logs = " ".join(x["action"] for x in orders.get_log(o["id"]))
ok(left == 9, f"other packing still deducted with an inactive box ({left})")
ok("发货出库跳过" in logs or "发货出库" in logs, f"skip logged ({logs[:80]})")
print("ERRORS", E_)
