# v2.49：平台对账自动化——Lazada 财务流水（运营分析模块拉）+ 结算单 GetPayoutStatus（财务模块拉）→ 每单 已到账 / 已结算 /
# 待回款 / 超时未回款 / 平台没结算 + 扣费异常；平台有但系统没有；已核对；费用拆分；平台状态卡片；今日待办；菜单 8 → 5（旧菜单跳转）。
# Lazada 接口全是假的（LazadaConnector._call）。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, time, io, datetime as dt
D = T + "/m_recon249"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, integrations, orders as orders_mod, config
from core.connectors import lazada as LZ
from modules.fin import logic as fin
db.conn().execute("DELETE FROM order_items"); db.conn().execute("DELETE FROM orders"); db.conn().commit()      # 只用这里建的订单
db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "secret123", "listing", "Nok")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
CL = A.app.test_client(); CL.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
cfg = config.load_config(); cfg.update({"platform_fee_rate": 0.1, "shopee_fee_rate": 0.1, "fin_settle_days": 14, "fin_settle_tolerance": 5,
                                        "review_enabled": False}); config.save_config(cfg)
now = time.time()
today = dt.date.today()
dd = lambda n: today - dt.timedelta(days=n)
lzd = lambda d: d.strftime("%d %b %Y")
ago = lambda n: now - n * 86400

orders_mod.upsert([
    {"platform": "lazada", "shop": "LZShop", "order_no": "LZ-A", "status": "completed", "order_time": ago(20), "order_total": 500, "items": []},
    {"platform": "lazada", "shop": "LZShop", "order_no": "LZ-B", "status": "shipped", "order_time": ago(5), "order_total": 300, "items": []},
    {"platform": "lazada", "shop": "LZShop", "order_no": "LZ-C", "status": "completed", "order_time": ago(30), "order_total": 200, "items": []},
    {"platform": "lazada", "shop": "LZShop", "order_no": "LZ-F", "status": "shipped", "order_time": ago(2), "order_total": 150, "items": []},
    {"platform": "lazada", "shop": "LZShop", "order_no": "LZ-G", "status": "completed", "order_time": ago(32), "order_total": 100, "items": []},
    {"platform": "lazada", "shop": "LZShop", "order_no": "LZ-H", "status": "to_ship", "order_time": ago(1), "order_total": 99, "items": []},
    {"platform": "shopee", "shop": "SPShop", "order_no": "SP-D", "status": "shipped", "order_time": ago(40), "order_total": 250, "items": []},
    {"platform": "shopee", "shop": "SPShop", "order_no": "SP-E", "status": "completed", "order_time": ago(10), "order_total": 400, "items": []},
], source="test")

# ---------- 假的 Lazada ----------
sid = integrations.save_shop({"platform": "lazada", "name": "LZShop", "enabled": True,
                              "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})
pA, pB, pG = (dd(20), dd(14)), (dd(6), dd(0)), (dd(30), dd(24))
per = lambda p: f"{lzd(p[0])} - {lzd(p[1])}"
def tx(no, n, amt, kind, d, p):
    return {"order_no": no, "transaction_date": lzd(d), "amount": str(amt), "transaction_type": kind, "fee_name": kind,
            "transaction_number": f"T{no}{n}", "orderItem_no": "1", "statement": per(p), "WHT_amount": "0", "VAT_in_amount": "0", "paid_status": "Not paid"}
TX = [tx("LZ-A", 1, 500, "Item Price Credit", dd(18), pA), tx("LZ-A", 2, -40, "Commission", dd(18), pA), tx("LZ-A", 3, -10, "Payment Fee", dd(18), pA),
      tx("LZ-A", 4, -5, "Shipping Fee Paid by Seller", dd(18), pA),
      tx("LZ-B", 1, 300, "Item Price Credit", dd(3), pB), tx("LZ-B", 2, -90, "Commission", dd(3), pB),
      tx("LZ-G", 1, 100, "Item Price Credit", dd(28), pG), tx("LZ-G", 2, -10, "Commission", dd(28), pG),
      tx("LZ-ZZZ", 1, 80, "Item Price Credit", dd(4), pB),
      tx("LZ-A", 5, -15, "Voucher Discount", dd(18), pA)]
PAY = [{"statement_number": f"TH1ABC-{pA[0]:%Y%m%d}", "created_at": f"{pA[1] + dt.timedelta(days=1)} 00:10:00", "updated_at": f"{dd(10)} 09:00:00",
        "paid": "1", "payout": "12345.60 THB", "opening_balance": "0", "closing_balance": "12345.60", "item_revenue": "500", "fees_total": "-70"},
       {"statement_number": f"TH1ABC-{pB[0]:%Y%m%d}", "created_at": f"{pB[1]} 23:00:00", "updated_at": f"{pB[1]} 23:00:00", "paid": "0",
        "payout": "300.00 THB"},
       {"statement_number": f"TH1ABC-{pG[0]:%Y%m%d}", "created_at": f"{pG[1] + dt.timedelta(days=1)} 00:10:00", "updated_at": f"{pG[1]} 00:10:00",
        "paid": "0", "payout": "90.00 THB"}]
calls, DENY = [], set()


def fake(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    calls.append((path, dict(params)))
    if path in DENY:
        raise RuntimeError(f"Lazada {path} 出错：InsufficientPermission The app does not have permission to call this api")
    if path == "/finance/transaction/details/get":
        off = int(params["offset"])
        return {"code": "0", "data": TX[off:off + int(params["limit"])]}
    if path == "/finance/payout/status/get":
        return {"code": "0", "data": PAY}
    return {"code": "0", "data": {}}


LZ.LazadaConnector._call = fake
ok(CL.post("/api/fin/settle/sync", json={}).status_code == 403, "sync owner only")
r = C.post("/api/fin/settle/sync", json={}).get_json()
ok(r["ok"] and r["ops_on"] and r["payouts"] == [{"shop": "LZShop", "payouts": 3}], f"sync now: finance + payouts {r['payouts']}")
ok(r["finance"]["shops"][0]["kinds"]["finance"]["fin"]["matched"] == 3, f"finance tx via ops → fin {r['finance']['shops'][0]['kinds']['finance']}")
pc = next(c for c in calls if c[0] == "/finance/payout/status/get")[1]
ok(pc["created_after"] == (today - dt.timedelta(days=120)).isoformat() and set(pc) == {"created_after"}, f"GetPayoutStatus params {pc}")
ok(not any(c[0] == "/finance/payout/status/get" and "access_token" in c[1] for c in calls), "params only (signing in _call)")
pw = db.conn().execute("SELECT * FROM fin_payouts ORDER BY created_at").fetchall()
ok(len(pw) == 3 and pw[1]["paid"] == 1 and abs(pw[1]["amount"] - 12345.6) < 0.01 and pw[1]["currency"] == "THB", "payouts stored (amount + currency parsed)")
ok(C.post("/api/fin/settle/sync", json={}).get_json()["finance"]["shops"][0]["kinds"]["finance"]["fin"]["new_rows"] == 0, "second sync no duplicates")

# ---------- Shopee：导入已拨款报表 ----------
csv = "Order ID,Payout Completed Date,Total Released Amount (฿)\n" + f"SP-E,{dd(3).isoformat()} 08:00,360\n"
p = C.post("/api/fin/settle/preview", data={"file": (io.BytesIO(csv.encode()), "Income.released.csv")}, content_type="multipart/form-data").get_json()
ri = C.post("/api/fin/settle/import", json={"token": p["token"], "mapping": p["mapping"], "platform": "shopee", "shop": "SPShop"}).get_json()
ok(ri["matched"] == 1, f"shopee import {ri}")

# ---------- 对账 ----------
rc = C.get(f"/api/fin/reconcile?start={dd(60).isoformat()}").get_json()
st = {x["order_no"]: x for x in rc["rows"]}
ok("LZ-H" not in st, "not shipped yet → not in reconciliation")
ok(st["LZ-A"]["state"] == "paid" and st["LZ-A"]["paid_at"] == dd(10).isoformat() and st["LZ-A"]["net"] == 430 and st["LZ-A"]["source"] == "api"
   and st["LZ-A"]["statement"].endswith(f"{pA[0]:%Y%m%d}"), f"LZ-A paid via payout {st['LZ-A']}")
ok(st["LZ-B"]["state"] == "settled" and st["LZ-B"]["issue"] == "diff" and st["LZ-B"]["diff"] == 60, f"LZ-B settled, fee higher {st['LZ-B']['state']} {st['LZ-B']['diff']}")
ok(st["LZ-C"]["state"] == "unsettled" and st["LZ-C"]["source"] == "estimate", f"LZ-C platform covered later days → unsettled {st['LZ-C']['state']}")
ok(st["LZ-F"]["state"] == "pending", "LZ-F pending")
ok(st["LZ-G"]["state"] == "overdue" and st["LZ-G"]["net"] == 90 and st["LZ-G"]["days"] >= 15, f"LZ-G settled but statement unpaid > N days → overdue {st['LZ-G']}")
ok(st["SP-D"]["state"] == "overdue", f"SP-D no data, before shopee coverage → overdue {st['SP-D']['state']}")
ok(st["SP-E"]["state"] == "paid" and st["SP-E"]["paid_at"] == dd(3).isoformat() and st["SP-E"]["source"] == "import", f"SP-E imported released → paid {st['SP-E']}")
ok([x["order_no"] for x in rc["unknown"]] == ["LZ-ZZZ"] and rc["unknown"][0]["source"] == "api", "platform has, system not")
ok({x["order_no"] for x in rc["unpaid"]} == {"LZ-G", "SP-D"} and [x["order_no"] for x in rc["unsettled"]] == ["LZ-C"] and
   [x["order_no"] for x in rc["diff"]] == ["LZ-B", "LZ-A"], f"problem tabs {[x['order_no'] for x in rc['diff']]}")
t = rc["total"]
ok(t["receivable"] == 500 + 300 + 200 + 150 + 100 + 250 + 400 and t["arrived"] == 430 + 360, f"receivable / arrived {t['receivable']} {t['arrived']}")
ok(t["fees"] == 70 + 90 + 10 + 40 and t["fee_rate"] == round(210 / 1300 * 100, 1) and t["cfg_rate"] == 10.0, f"real fee vs configured {t['fees']} {t['fee_rate']}")
ok(abs(t["pending"] - (210 + 200 * 0.9 + 150 * 0.9 + 90 + 250 * 0.9)) < 0.01, f"pending {t['pending']}")
ok(t["issues"] == 6 and t["issue_counts"] == {"diff": 2, "unpaid": 2, "unsettled": 1, "unknown": 1}, f"issues {t['issues']} {t['issue_counts']}")
ok(rc["counts"]["paid"] == 2 and rc["counts"]["settled"] == 1, f"state counts {rc['counts']}")
sp = C.get(f"/api/fin/reconcile?start={dd(60).isoformat()}&platform=shopee").get_json()
ok({x["platform"] for x in sp["rows"]} == {"shopee"} and sp["total"]["issues"] == 1 and sp["rows"][0]["order_no"] == "SP-E" and not sp["unknown"], "platform switch")
ok(C.get("/api/fin/reconcile?platform=xx").status_code == 400, "bad platform")
# 费用拆分
b = C.get("/api/fin/reconcile/order?platform=lazada&order_no=LZ-A").get_json()
cats = {x["cat"]: x["amount"] for x in b["cats"]}
ok(cats == {"item": 500, "commission": -40, "payment": -10, "shipping": -5, "voucher": -15} and b["net"] == 430 and b["revenue"] == 500
   and all(l["src"] == "api" for l in b["lines"]), f"fee breakdown {cats}")
from modules.fin.logic import recon as RC
ok(RC.fee_cat("Penalty for late shipment") == "penalty" and RC.fee_cat("ค่าคอมมิชชั่น") == "commission", "fee categories")
# 已核对
ok(C.post("/api/fin/reconcile/check", json={"platform": "lazada", "order_no": "LZ-B", "checked": True}).get_json()["checked"], "mark checked")
C.post("/api/fin/reconcile/check", json={"platform": "lazada", "order_no": "LZ-ZZZ", "checked": True})
rc2 = C.get(f"/api/fin/reconcile?start={dd(60).isoformat()}").get_json()
bx = next(x for x in rc2["diff"] if x["order_no"] == "LZ-B")
ok(rc2["total"]["issues"] == 4 and bx["checked"]["by"] == "boss" and rc2["unknown"][0]["checked"], "checked persists, not counted")
C.post("/api/fin/reconcile/check", json={"platform": "lazada", "order_no": "LZ-B", "checked": False})
ok(C.get(f"/api/fin/reconcile?start={dd(60).isoformat()}").get_json()["total"]["issues"] == 5, "uncheck")
ok(C.post("/api/fin/reconcile/check", json={"platform": "xx", "order_no": "1"}).status_code == 400, "bad check refused")

# ---------- 订单利润（订单明细）同一套状态 ----------
od = {x["order_no"]: x for x in C.get(f"/api/fin/orders?start={dd(60).isoformat()}").get_json()["rows"]}
ok(od["LZ-A"]["settle"] == "paid" and od["LZ-B"]["settle"] == "settled" and od["LZ-C"]["settle"] == "overdue" and od["LZ-F"]["settle"] == "pending"
   and od["LZ-A"]["source"] == "api", f"order detail states {[(k, v['settle']) for k, v in od.items()]}")
ov = C.get(f"/api/fin/overview?start={dd(60).isoformat()}").get_json()
ok(ov["issues"] == 5 and ov["unsettled_count"] == 1, f"overview issues {ov['issues']}")

# ---------- 平台卡片 / 今日待办 ----------
ps = {p["platform"]: p for p in rc["platforms"]}
ok(ps["lazada"]["mode"] == "api" and ps["lazada"]["last_ok"] and ps["lazada"]["payout"]["count"] == 3 and ps["lazada"]["next_at"] > now, f"lazada card {ps['lazada']}")
ok(ps["shopee"]["mode"] == "import" and ps["shopee"]["import_days"] == 0 and not ps["shopee"]["stale"], "shopee card fresh")
ok(ps["tiktok"]["mode"] == "import" and ps["tiktok"]["last_import"] is None and not ps["tiktok"]["stale"], "tiktok: no orders → no nag")
keys = {i["key"] for i in C.get("/api/todo").get_json()["items"]}
ok(not any(k.startswith("fin_import:") for k in keys), "no import to-do while fresh")
db.conn().execute("UPDATE fin_settle_batches SET created_at=? WHERE platform='shopee'", (ago(20),)); db.conn().commit()
orders_mod.upsert([{"platform": "tiktok", "order_no": "TT-1", "status": "shipped", "order_time": ago(3), "order_total": 120, "items": []}], source="test")
it = {i["key"]: i for i in C.get("/api/todo").get_json()["items"]}
k_sp = f"fin_import:shopee:{dd(20).isoformat()}"
ok(k_sp in it and it[k_sp]["group"] == "财务" and it[k_sp]["tab"] == "fin_settle" and "20" in it[k_sp]["title"] and it[k_sp]["title_th"], f"shopee stale to-do {list(it)[:8]}")
ok("fin_import:tiktok:never" in it, "tiktok never imported to-do")
ok(not any(k.startswith("fin_import:") for k in {i["key"] for i in CL.get("/api/todo").get_json()["items"]}), "staff don't see finance to-do")
cfg = config.load_config(); cfg["fin_import_remind_days"] = 30; config.save_config(cfg)
ok(k_sp not in {i["key"] for i in C.get("/api/todo").get_json()["items"]}, "remind days setting")
sch = next(m for m in C.get("/api/settings/schema").get_json()["modules"] if m["id"] == "finance")
ok(any(f["key"] == "fin_import_remind_days" for g in sch["groups"] for f in g["fields"]), "setting in 设置 → 财务")

# ---------- 结算单接口没权限 ----------
DENY.add("/finance/payout/status/get")
r = C.post("/api/fin/settle/sync", json={}).get_json()
ok("error" in r["payouts"][0] and "App Console" in r["payouts"][0]["hint"], f"payout permission hint {r['payouts'][0]}")
ps = {p["platform"]: p for p in C.get(f"/api/fin/reconcile?start={dd(60).isoformat()}").get_json()["platforms"]}
ok(ps["lazada"]["payout"]["errors"] and ps["lazada"]["payout"]["last_ok"], "card keeps last ok + error")
DENY.clear()
# 结算单打款了 → 下次同步变成已到账
PAY[1]["paid"] = "1"; PAY[1]["updated_at"] = f"{today} 10:00:00"
fin.sync_payouts()
st = {x["order_no"]: x for x in C.get(f"/api/fin/reconcile?start={dd(60).isoformat()}").get_json()["rows"]}
ok(st["LZ-B"]["state"] == "paid" and st["LZ-B"]["paid_at"] == today.isoformat(), "statement paid later → 已到账")

# ---------- 菜单：8 → 5，旧的变成看不见的跳转 ----------
ms = {m["id"]: m for m in C.get("/api/modules").get_json()["modules"]}
vis = [mn["tab"] for mn in ms["fin"]["menus"] if not mn["ghost"]]
ok(vis == ["fin_overview", "fin_orders", "fin_settle", "fin_book", "fin_tax"], f"5 menus {vis}")
gh = {mn["tab"]: mn["panel"] for mn in ms["fin"]["menus"] if mn["ghost"]}
ok(gh == {"fin_profit": "fin_overview", "fin_cash": "fin_book", "profit": "fin_orders"}, f"old tabs redirect {gh}")
ok("boot.js" in ms["fin"]["ui"]["boot_js"] and "settle.js" in ms["fin"]["ui"]["page_js"], "ui files")
html = C.get("/m/fin/page.html").get_data(as_text=True)
ok(all(f'id="tab-{t}"' in html for t in vis) and "tab-fin_cash" not in html, "5 panels")
for f in ("finance.js", "orders.js", "settle.js", "boot.js", "page.css"):
    ok(C.get(f"/m/fin/{f}").status_code == 200, f"serves {f}")
ok(C.get("/api/profit?days=30").status_code == 200, "old 每单利润 api still works")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
