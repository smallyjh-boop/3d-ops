# v2.21：采购单独成模块；电商财务（损益、利润分析、平台结算对账、收支、现金流、税务、对外接口）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, json, time, datetime as dt, zipfile
D = T + "/vfin"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
import app as A
from core import orders, config, db, integrations
from modules.fin import logic as fin
from core import inventory as inv
E = 0
def ok(b, m):
    global E; print(("OK  " if b else "ERR ") + m); E += (not b)
C = A.app.test_client()
cfg = config.load_config(); cfg["platform_fee_rate"] = 0.1; cfg["shopee_fee_rate"] = 0; config.save_config(cfg)

M = dt.date.today().strftime("%Y-%m")
d1 = dt.date.today().replace(day=1)
old = (dt.datetime.now() - dt.timedelta(days=40)).strftime("%Y-%m-%d 10:00")
t1 = d1.strftime("%Y-%m-%d") + " 10:00"
r = orders.upsert([
    {"platform": "lazada", "shop": "LZ1", "order_no": "LZ-1001", "status": "completed", "order_time": t1, "order_total": 500,
     "items": [{"sku": "X-1", "qty": 1, "unit_price": 500}]},
    {"platform": "lazada", "shop": "LZ1", "order_no": "LZ-1002", "status": "completed", "order_time": t1, "order_total": 300,
     "items": [{"sku": "X-2", "qty": 2, "unit_price": 150}]},
    {"platform": "shopee", "shop": "SP1", "order_no": "SP-2001", "status": "completed", "order_time": t1, "order_total": 200,
     "items": [{"sku": "X-1", "qty": 1, "unit_price": 200}]},
    {"platform": "shopee", "shop": "SP1", "order_no": "SP-OLD", "status": "shipped", "order_time": old, "order_total": 150, "items": []},
], source="test")
ok(r["orders_new"] == 4, "test orders")

# ---- 损益表：没导结算 → 扣费按扣点估算；固定费用按设置估算 ----
pl = fin.pl(*fin.period(M)[:2])
s = pl["summary"]
ok(s["orders"] >= 3 and s["fee_estimated"] > 0 and s["fixed_estimated"] > 0, f"pl estimates {s['fee_estimated']} {s['fixed_estimated']}")
keys = [l["key"] for l in pl["lines"]]
ok(keys[0] == "revenue" and "gross" in keys and keys[-1] == "net" and "out_vat" not in keys, "pl lines (VAT off)")
net_calc = round(sum(l["amount"] for l in pl["lines"] if l["level"] == 1 or l["key"] == "revenue"), 2)
ok(abs(net_calc - s["net"]) < 0.05, f"pl adds up {net_calc} vs {s['net']}")

# ---- 平台结算：Lazada 每笔费用一行 ----
csv = ("Transaction Date,Fee Name,Order No.,Amount,VAT in Amount,WHT Amount,Statement\n"
       f"{d1.isoformat()},Item Price Credit,LZ-1001,500,0,5,ST1\n"
       f"{d1.isoformat()},Commission,LZ-1001,-40,2.62,0,ST1\n"
       f"{d1.isoformat()},Payment Fee,LZ-1001,-15,0.98,0,ST1\n"
       f"{d1.isoformat()},Item Price Credit,LZ-1002,300,0,3,ST1\n"
       f"{d1.isoformat()},Commission,LZ-1002,-90,5.89,0,ST1\n"
       f"{d1.isoformat()},Item Price Credit,LZ-9999,100,0,1,ST1\n"
       f"{d1.isoformat()},Adjustment,,-20,0,0,ST1\n")
def up(content, name):
    return C.post("/api/fin/settle/preview", data={"file": (io.BytesIO(content.encode()), name)}, content_type="multipart/form-data").get_json()
p = up(csv, "lazada_statement.csv")
mp = p["mapping"]
ok(p["platform"] == "lazada" and set(mp) >= {"order_no", "amount", "fee_name", "date", "wht", "vat"} and "net" not in mp, f"lazada columns auto-mapped {mp}")
r = C.post("/api/fin/settle/import", json={"token": p["token"], "mapping": mp, "platform": "lazada", "shop": "LZ1"}).get_json()
ok(r["new_rows"] == 7 and r["orders"] == 3 and r["matched"] == 2, f"lazada import {r}")
st = {o["order_no"]: o["settlement"] for o in db.conn().execute("SELECT order_no, settlement FROM orders WHERE platform='lazada'")}
ok(st.get("LZ-1001") == 445 and st.get("LZ-1002") == 210, f"settlement written {st}")
p2 = up(csv, "lazada_statement.csv")
r2 = C.post("/api/fin/settle/import", json={"token": p2["token"], "mapping": p2["mapping"], "platform": "lazada"}).get_json()
ok(r2["new_rows"] == 0 and r2["dup_rows"] == 7, "same file twice → no duplicates")
ok(db.conn().execute("SELECT settlement FROM orders WHERE order_no='LZ-1001'").fetchone()[0] == 445, "settlement unchanged after dup import")

# ---- Shopee：每单一行的到账金额 ----
csv2 = "Order ID,Payout Completed Date,Original product price,Commission Fee,Total Released Amount (฿)\n" + \
       f"'SP-2001,{d1.isoformat()} 08:00,200,-12,176\n"
p3 = up(csv2, "Income.released.th.csv")
ok(p3["platform"] == "shopee" and "net" in p3["mapping"] and "amount" not in p3["mapping"], f"shopee net column {p3['mapping']}")
r3 = C.post("/api/fin/settle/import", json={"token": p3["token"], "mapping": p3["mapping"], "platform": "shopee"}).get_json()
ok(r3["matched"] == 1 and db.conn().execute("SELECT settlement FROM orders WHERE order_no='SP-2001'").fetchone()[0] == 176, "shopee settlement (leading ' stripped)")

# ---- 对账 ----
rc = C.get(f"/api/fin/reconcile?start={(dt.date.today() - dt.timedelta(days=60)).isoformat()}").get_json()
ok(any(x["order_no"] == "LZ-1002" for x in rc["diff"]) and not any(x["order_no"] == "LZ-1001" for x in rc["diff"]),
   "LZ-1002 fee higher than expected (300×0.9=270 vs 210)")
ok(any(x["order_no"] == "SP-OLD" and x["days"] >= 39 for x in rc["unpaid"]), "old shipped order unpaid")
ok(any(x["order_no"] == "LZ-9999" for x in rc["unknown"]) and rc["total"]["adjustments"] == -20, "unknown order + adjustment")
ok(rc["batches"] and rc["batches"][0]["platform"] == "shopee", "batches listed")

# 结算之后才导入的订单：自动补上
orders.upsert([{"platform": "lazada", "shop": "LZ1", "order_no": "LZ-9999", "status": "completed", "order_time": t1, "order_total": 110, "items": []}], source="test")
fin.reconcile(*fin.period(M)[:2])
ok(db.conn().execute("SELECT settlement FROM orders WHERE order_no='LZ-9999'").fetchone()[0] == 100, "late order picks up settlement")

# ---- 损益表现在用真实扣费 ----
s2 = fin.pl(*fin.period(M)[:2])["summary"]
ok(s2["fee_estimated"] < s["fee_estimated"] and s2["wht"] == 9, f"pl uses real fees, wht {s2['wht']}")

# ---- 收支 ----
r = C.post("/api/fin/expenses", json={"day": d1.isoformat(), "category": "广告费", "amount": 300, "payee": "Lazada", "method": "platform"}).get_json()
eid = r["row"]["id"]
ok(r["ok"] and r["row"]["category"] == "广告费", "expense saved")
up_r = C.post(f"/api/fin/expenses/{eid}/receipt", data={"file": (io.BytesIO(b"%PDF-1.4 test"), "bill.pdf")}, content_type="multipart/form-data")
ok(up_r.status_code == 200 and C.get(f"/api/fin/expenses/{eid}/receipt").data.startswith(b"%PDF"), "receipt upload / download")
ok(C.post(f"/api/fin/expenses/{eid}/receipt", data={"file": (io.BytesIO(b"x"), "a.exe")}, content_type="multipart/form-data").status_code == 400, "bad receipt type rejected")
C.post("/api/fin/expenses", json={"day": d1.isoformat(), "category": "房租", "amount": 5000})
C.post("/api/fin/expenses", json={"day": d1.isoformat(), "category": "老板投入", "amount": 20000, "direction": "in"})
C.post("/api/fin/expenses", json={"day": d1.isoformat(), "category": "其他收入", "amount": 50, "direction": "in"})
ok(C.post("/api/fin/expenses", json={"amount": -5}).status_code == 400, "negative amount rejected")
x = C.get(f"/api/fin/expenses?month={M}").get_json()
ok(x["total_out"] == 5300 and x["total_in"] == 20050 and x["rows"][0]["has_receipt"] in (True, False), f"expense list {x['total_out']} {x['total_in']}")
pl3 = fin.pl(*fin.period(M)[:2])
s3 = pl3["summary"]
fx = next((l for l in pl3["lines"] if l["key"] == "fixed_est"), None)       # v2.40：按项估算——记了房租，房租不再估，其它照估
ok((fx is None or "房租" not in fx["note"]) and any(l["key"] == "exp:房租" for l in pl3["lines"]) and any(l["key"] == "other_in" for l in pl3["lines"])
   and s3["capital_in"] == 20000, "recorded rent replaces estimate; capital not income")
# 旧接口（利润页的其他支出）
ok(C.post("/api/expenses", json={"day": d1.isoformat(), "kind": "运费补贴", "amount": 10}).status_code == 200, "old expense API still works")
old_list = C.get("/api/expenses").get_json()
ok(any(e["kind"] == "快递运费" and e["amount"] == 10 for e in old_list["items"]), "old list shows it (old category mapped)")
C.delete(f"/api/fin/expenses/{eid}")
ok(C.get(f"/api/fin/expenses?month={M}").get_json()["total_out"] == 5010, "delete expense")

# ---- 采购付款进现金流 ----
it = inv.save_item({"name_zh": "测试纸箱", "category": "pack", "unit": "个"})
po = inv.save_po({"lines": [{"item_id": it["id"], "qty": 10, "unit_cost": 8}], "ship_fee": 20})
inv.po_action(po["id"], "order")
inv.receive_po(po["id"])
inv.pay_po(po["id"], 60, "转账", d1.isoformat())
cf = fin.cashflow(*fin.period(M)[:2])
t = cf["total"]
ok(t["purchase_out"] == 60 and t["settle_in"] == 911 and t["capital_in"] == 20000 and t["expense_out"] == 5010 and t["other_in"] == 50,
   f"cashflow {t}")
ok(abs(t["net"] - (911 + 50 + 20000 - 60 - 5010)) < 0.01 and cf["rows"][-1]["running"] == t["net"], "cashflow totals / running balance")
sm = C.get("/api/inv/po-summary").get_json()
ok(sm["unpaid"] == 40 and sm["month_paid"] == 60 and sm["month_received"] == 100, f"purchase summary {sm}")

# ---- 利润分析 ----
for by in ("platform", "shop", "product", "sku", "day", "month"):
    b = C.get(f"/api/fin/breakdown?by={by}&month={M}").get_json()
    ok(b["rows"] and abs(sum(r["revenue"] for r in b["rows"]) - b["total"]["revenue"]) < 0.1, f"breakdown {by}")
b = C.get(f"/api/fin/breakdown?by=sku&month={M}").get_json()
ok(any(r["key"] == "X-1" and r["qty"] == 2 for r in b["rows"]), "sku qty")

# ---- VAT ----
cfg = config.load_config(); cfg["fin_vat_on"] = True; config.save_config(cfg)
C.post("/api/fin/expenses", json={"day": d1.isoformat(), "category": "软件 / 订阅", "amount": 1070, "vat": 70, "tax_invoice": True})
pv = fin.pl(*fin.period(M)[:2])
sv = pv["summary"]
ok(abs(sv["out_vat"] - sv["revenue"] * 7 / 107) < 0.05 and abs(sv["revenue_net"] - (sv["revenue"] - sv["out_vat"])) < 0.05, "output VAT split from price")
ok(any(l["key"] == "out_vat" for l in pv["lines"]) and sv["in_vat"] >= 70 + 9.49 - 0.05, f"input VAT from expenses + fees {sv['in_vat']}")
tx = C.get(f"/api/fin/tax?month={M}").get_json()
ok(tx["vat_on"] and abs(tx["total"]["payable"] - (sv["out_vat"] - sv["in_vat"])) < 0.05 and tx["total"]["wht"] == 9, "tax page")
cfg["fin_vat_on"] = False; config.save_config(cfg)
tx = C.get(f"/api/fin/tax?month={M}").get_json()
ok(not tx["vat_on"] and tx["total"]["payable"] == 0 and tx["year_sales"] > 0 and tx["vat_threshold"] == 1800000, "VAT off by default path")

# ---- 总览 / 导出 / 删除结算 ----
ov = C.get(f"/api/fin/overview?month={M}").get_json()
ok(ov["summary"]["orders"] >= 4 and "change" in ov and ov["diff_count"] >= 1 and ov["unpaid_count"] == len(fin.reconcile(*fin.period(M)[:2])["unpaid"]) and ov["platforms"], "overview")
x = C.get(f"/api/fin/export?month={M}")
wb = __import__("openpyxl").load_workbook(io.BytesIO(x.data))
ok(x.status_code == 200 and {"损益表", "按产品", "收支明细", "现金流"} <= set(wb.sheetnames), "excel export")
bid = [b for b in fin.settle_batches() if b["platform"] == "shopee"][0]["id"]
C.delete(f"/api/fin/settle/batches/{bid}")
ok(db.conn().execute("SELECT settlement FROM orders WHERE order_no='SP-2001'").fetchone()[0] is None, "delete batch clears settlement")

# ---- 权限 / 对外接口 ----
FK = integrations.create_key("fin", "finance")
r = C.get(f"/api/v1/finance/pl?month={M}", headers={"Authorization": "Bearer " + FK})
ok(r.status_code == 200 and r.get_json()["ok"] and r.get_json()["lines"], "v1 finance pl")
for u in ("breakdown?by=product", "cashflow", "expenses", "tax"):
    ok(C.get(f"/api/v1/finance/{u}{'&' if '?' in u else '?'}month={M}", headers={"Authorization": "Bearer " + FK}).status_code == 200, f"v1 finance {u}")
ok(C.post("/api/v1/finance/pl", headers={"Authorization": "Bearer " + FK}).status_code in (403, 405), "finance key read-only")
ok(C.get("/api/fin/pl?month=2026-13").status_code == 400, "bad month → 400")
db.create_user("boss", "secret1", "owner", "老板"); db.create_user("nok", "pass123", "listing", "Nok")
C2 = A.app.test_client(); C2.post("/api/auth/login", json={"username": "nok", "password": "pass123"})
ok(C2.get(f"/api/fin/pl?month={M}").status_code == 403 and C2.get("/api/inv/po-summary").status_code == 200, "finance owner-only, purchase for staff")
print("ERRORS", E)
