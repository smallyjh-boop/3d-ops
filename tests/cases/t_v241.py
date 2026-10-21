# v2.41：全功能测试的低级问题
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, time, datetime as dt, copy
D = T + "/v241"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, store, production, orders, lazada_template, labels, fleet, materials, inventory as inv
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pk", "pass123", "production", "Pk")
def cl(u, p):
    c = A.app.test_client(); c.post("/api/auth/login", json={"username": u, "password": p}); return c
C, PK = cl("boss", "secret123"), cl("pk", "pass123")
config.save_config({"review_enabled": False, "stock_auto_use": False})
sku = next(v["sku"] for it in store.list_products() for v in (store.load(it["id"]).get("variants") or []) if v.get("sku"))
pid = sku.split("-")[0]
manual = lambda no, **kw: C.post("/api/orders/manual", json={"order_no": no, "items": [{"sku": sku, "qty": 1, "unit_price": 100}], **kw}).get_json()
jobs_of = lambda oid: [dict(r) for r in db.conn().execute("SELECT * FROM jobs WHERE order_id=?", (oid,))]
CONF = {"bed_clear": True, "material": True}

# ---- 商品：没有 Shopee 标签时也查详情长度
p = store.load(pid); p.setdefault("copy", {})["description_th"] = "สั้น"; p["copy"]["hashtags_shopee"] = ""
_e, w = lazada_template.check_product(p, {})
ok(any("详情建议" in x for x in w), "detail length checked without shopee tags")

# ---- 订单：COD 金额照实印；ship_by 看不懂报错；改订单不记没改的字段；坏输入不是 500
ok(labels.cod_txt(1250.5) == "1,250.50" and labels.cod_txt(1250) == "1,250", "COD text keeps satang")
o = manual("L1", cod=1250.5)
html = C.get(f"/print/labels?type=self&ids={o['id']}").get_data(as_text=True)
ok("1,250.50" in html, "self-made label prints 1,250.50")
r = C.post(f"/api/orders/{o['id']}", json={"ship_by": "tomorrow"})
ok(r.status_code == 400, f"unreadable ship_by refused ({r.status_code})")
C.post(f"/api/orders/{o['id']}", json={"ship_by": "2026-12-01 18:00"})
n0 = len(orders.get_log(o["id"]))
C.post(f"/api/orders/{o['id']}", json={"ship_by": "2026-12-01 18:00"})
C.post(f"/api/orders/{o['id']}/edit", json={"custom_note": "x", "platform_fee": None, "order_time": orders.get_order(o["id"])["order_time"]})
lg = orders.get_log(o["id"])
ok(not any(x["action"] in ("最晚发货", "平台费", "下单时间") for x in lg[: len(lg) - n0]), f"unchanged fields not logged {[x['action'] for x in lg[:len(lg) - n0]]}")
ok(any(x["action"] == "最晚发货" and "2026-12-01 18:00" in x["detail"] for x in lg), "ship_by logged as a readable date")
for desc, req in (("manual items:[null]", lambda: C.post("/api/orders/manual", json={"items": [None, {"sku": 123}]})),
                  ("commit without token", lambda: C.post("/api/orders/import/commit", json={})),
                  ("batch bad ids", lambda: C.post("/api/orders/batch", json={"ids": ["x"], "action": "priority", "value": 1})),
                  ("preview broken xlsx", lambda: C.post("/api/orders/import/preview", data={"file": (io.BytesIO(b"not excel"), "x.xlsx")}, content_type="multipart/form-data"))):
    sc = req().status_code
    ok(sc < 500 and (sc == 400 or desc.startswith("manual")), f"{desc} -> no 500 ({sc})")
# 批量删除说明没删成的原因
o2 = manual("L2"); j = jobs_of(o2["id"])[0]
production.start_run(j["id"], 0, 1, [], None, False, "t", CONF)
r = C.post("/api/orders/batch", json={"ids": [o2["id"]], "action": "delete"})
ok(r.status_code == 400 and "正在打印" in r.get_json()["error"], "batch delete says why it failed")
production.cancel_run(db.conn().execute("SELECT run_id FROM jobs WHERE id=?", (j["id"],)).fetchone()["run_id"] or 0, "t")
ok(jobs_of(o2["id"])[0]["pin"] == 0, "undo a plate unpins the job")
# 生产员工：颜色表、泰文字体能读
ok(PK.get("/api/colors").status_code == 200 and PK.get("/fonts/thai.css").status_code == 200, "production can load colors and thai fonts")
# 退货后重新发货：再出一次库
config.save_config({"inv_ship_out": True})
pk_item = C.post("/api/inv/items", json={"name_zh": "气泡袋", "category": "pack", "unit": "个"}).get_json()["item"]
inv.create_doc("purchase", [{"item_id": pk_item["id"], "qty": 10}], "期初", "t")
config.save_config({"inv_pack_auto": True, "inv_pack_rules": [{"item_id": pk_item["id"], "qty": 1, "per": "order"}]})
o3 = manual("RS1")
for st in ("shipped", "returned", "to_ship", "shipped"):
    orders.update_order(o3["id"], "t", status=st)
ok(inv.get_item(pk_item["code"])["qty"] == 8, f"re-ship after return deducts packing again ({inv.get_item(pk_item['code'])['qty']})")

# ---- 生产：换到不对类型的打印机报错；删打印机时料卷取下；负库存提醒；删备货任务
cfg = config.load_config()
resin_i = next((i for i, p in enumerate(cfg["printers"]) if fleet.tech_of(p) == "resin"), None)
if resin_i is None:
    cfg["printers"].append({"name": "Elegoo Saturn 4", "code": "R1-01", "tech": "resin"}); config.save_config(cfg)
    resin_i = len(cfg["printers"]) - 1
o4 = manual("PR1"); j = jobs_of(o4["id"])[0]
r = C.post(f"/api/jobs/{j['id']}", json={"printer": resin_i})
ok(r.status_code == 400 and jobs_of(o4["id"])[0]["printer"] != resin_i, f"FDM job -> resin printer refused ({r.status_code})")
code0 = config.load_config()["printers"][0].get("code")
C.post("/api/spools", json={"material": "PLA", "color": "白色", "count": 1})
sp = db.conn().execute("SELECT code FROM spools ORDER BY id DESC LIMIT 1").fetchone()["code"]
db.conn().execute("UPDATE spools SET status='loaded', printer=? WHERE code=?", (code0, sp)); db.conn().commit()
old = copy.deepcopy(config.load_config()["printers"]); new = old[1:]
fleet.remap(old, new)
row = db.conn().execute("SELECT status, printer FROM spools WHERE code=?", (sp,)).fetchone()
ok(row["status"] == "open" and row["printer"] is None, f"spool on deleted printer goes back to stock ({dict(row)})")
k = ("PLA", "紫色")
materials.consume("PLA", "紫色", 300, "t", "t") if hasattr(materials, "consume") else None
al = [a["text"] for a in materials.alerts() if "紫色" in a["text"]]
ok(not al or any("负数" in t for t in al), f"negative stock alert explains itself {al[:1]}")
r = C.post("/api/stock/make", json={"sku": sku, "qty": 2}).get_json()
ok(C.delete(f"/api/jobs/{r['id']}").status_code == 200 and not db.conn().execute("SELECT 1 FROM jobs WHERE id=?", (r["id"],)).fetchone(), "stock job can be deleted")
ok(C.delete(f"/api/jobs/{jobs_of(o4['id'])[0]['id']}").status_code == 400, "order job cannot be deleted that way")

# ---- 财务：按产品订单数；概况跟着期间；不含税 VAT 说明行；导出付款方式中文；盘点非数字
from modules.fin import logic as fin
p = store.load(pid); s2 = [v["sku"] for v in p["variants"] if v.get("sku")][:2]
o5 = C.post("/api/orders/manual", json={"order_no": "BD1", "items": [{"sku": s2[0], "qty": 1, "unit_price": 100}, {"sku": s2[1], "qty": 1, "unit_price": 100}]}).get_json()
M = dt.date.today().strftime("%Y-%m")
before = {r["key"]: r["orders"] for r in fin.breakdown(*fin.period(M)[:2], by="product")["rows"]}
ok(before.get(pid, 0) == sum(1 for x in db.conn().execute("SELECT DISTINCT o.id FROM orders o JOIN order_items i ON i.order_id=o.id WHERE i.product_id=? AND o.status NOT IN ('cancelled','returned','delivery_failed','quote')", (pid,))),
   f"product order count not doubled ({before.get(pid)})")
y0 = dt.date.today().replace(month=1, day=1).isoformat()
r = C.get(f"/api/fin/overview?start={y0}&end={dt.date.today().isoformat()}").get_json()
p2 = C.get(f"/api/fin/pl?start={y0}&end={dt.date.today().isoformat()}").get_json()
ok(r["summary"]["revenue"] == p2["summary"]["revenue"], f"overview follows custom period ({r['summary']['revenue']} vs {p2['summary']['revenue']})")
config.save_config({"fin_vat_on": True, "fin_prices_incl_vat": False})
lines = fin.pl(*fin.period(M)[:2])["lines"]
ov = next(l for l in lines if l["key"] == "out_vat")
ok(ov["level"] == 4 and ov["amount"] > 0 and not any(l["key"] == "rev_net" for l in lines), "excl-VAT output tax shown as a note line")
config.save_config({"fin_vat_on": False})
C.post("/api/fin/expenses", json={"day": dt.date.today().isoformat(), "category": "广告费", "amount": 10, "method": "transfer"})
import openpyxl
x = C.get(f"/api/fin/export?month={M}")
wb = openpyxl.load_workbook(io.BytesIO(x.data))
vals = [c for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for c in row if c in ("transfer", "转账")]
ok("转账" in vals and "transfer" not in vals, f"export payment method in Chinese {set(vals)}")
st = inv.stocktake_start("pack", "t")
lid = st["lines"][0]["id"]
r = C.post(f"/api/inv/stocktake/{st['id']}/save", json={"counts": {str(lid): "abc"}})
ok(r.status_code == 400 and "数字" in r.get_json()["error"], f"stocktake non-number friendly error ({r.get_json()})")
print("ERRORS", E_)
