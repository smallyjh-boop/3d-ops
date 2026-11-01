# v2.51：经营概况多店铺——「各店铺对比」（一个店铺一行、合计 = 总览、按平台合起来、最好 / 最差）、
# Lazada 店铺表现 / 评价 / 退货 / 真实扣点 / 同步状态按店铺存和看、店铺筛选对 Lazada 数据也有效、
# 没数据的指标不算达标（「x/y 达标 · z 项暂无数据」）、每个指标都有中文 / 泰文名字（Basket size……）。
# 两个 Lazada 店铺 + 一个 Shopee 店铺；Lazada 接口是假的。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, time
D = T + "/m_ops251"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, integrations, orders as orders_mod, modules
from modules.ops import lazada as LZ, dash
db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "secret123", "listing", "Nok")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
CL = A.app.test_client(); CL.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
LZ.init()
now = time.time()
CR = {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}
A_ID = integrations.save_shop({"platform": "lazada", "name": "ShopA Lazada", "enabled": True, "creds": CR})
B_ID = integrations.save_shop({"platform": "lazada", "name": "ShopB Lazada", "enabled": True, "creds": CR})
C_ID = integrations.save_shop({"platform": "shopee", "name": "ShopC Shopee", "enabled": True, "creds": {"partner_id": "1"}})
ok(len({A_ID, B_ID, C_ID}) == 3, "three shops")

# ---------- 订单（今天） ----------
def o(no, plat, shop, total, status="completed", **kw):
    return {"platform": plat, "shop": shop, "order_no": no, "status": status, "order_time": now - 120, "order_total": total,
            "items": [{"sku": "3DP0015-WH", "qty": 1, "unit_price": total, "item_total": total}], **kw}
orders_mod.upsert([o("A1", "lazada", "ShopA Lazada", 900), o("A2", "lazada", "ShopA Lazada", 600),
                   o("B1", "lazada", "ShopB Lazada", 30),                                            # 小单：ShopB 销售额、利润最低
                   o("B2", "lazada", "ShopB Lazada", 250, "to_ship", ship_by=now - 3600),            # 待发货（超时）
                   o("C1", "shopee", "ShopC Shopee", 500), o("C2", "shopee", "ShopC Shopee", 400)], source="test")

# ---------- Lazada：两个店铺各自的店铺表现、评价、退货、流水、同步状态 ----------
PERF_A = {"indicators": [
    {"name": "Ship on Time", "type": "SHIP_ON_TIME", "score": "98", "formatted_score": "98%", "formatted_target": "≥ 95%", "target_respected": "true"},
    {"name": "Cancellation Rate", "type": "CANCELLATION_RATE", "score": "1", "formatted_score": "1%", "formatted_target": "≤ 2%", "target_respected": "true"},
    {"name": "Basket size", "type": "BASKET_SIZE", "score": "", "formatted_score": "", "formatted_target": "", "target_respected": "true"},   # 没数据
    {"name": "Brand New Metric", "type": "BRAND_NEW_METRIC", "score": "", "formatted_score": "-", "formatted_target": "≥ 3", "target_respected": ""}]}
PERF_B = {"indicators": [
    {"name": "Ship on Time", "type": "SHIP_ON_TIME", "score": "80", "formatted_score": "80%", "formatted_target": "≥ 95%", "target_respected": "false"},
    {"name": "Cancellation Rate", "type": "CANCELLATION_RATE", "score": "", "formatted_score": "", "formatted_target": "≤ 2%", "target_respected": "true"},  # 没数据
    {"name": "Basket size", "type": "BASKET_SIZE", "score": "350", "formatted_score": "฿350", "formatted_target": "", "target_respected": ""}]}   # 有数没要求：不算


class FakeConn:
    def __init__(self, d):
        self.d = d

    def seller_performance(self):
        return self.d


LZ.sync_performance(FakeConn(PERF_A), {"id": A_ID, "name": "ShopA Lazada"})
LZ.sync_performance(FakeConn(PERF_B), {"id": B_ID, "name": "ShopB Lazada"})
c = db.conn()
ok(sorted(r[0] for r in c.execute("SELECT shop_id FROM oa_lz_perf")) == sorted([A_ID, B_ID]), "performance stored per shop (one row each)")
cols = {t: {r[1] for r in c.execute(f"PRAGMA table_info({t})")} for t in ("oa_lz_state", "oa_lz_tx", "oa_lz_review", "oa_lz_reverse", "oa_lz_perf")}
ok(all("shop_id" in v for v in cols.values()), "every Lazada table has shop_id")
today = time.strftime("%Y-%m-%d")
c.executemany("INSERT INTO oa_lz_tx(shop_id, uid, order_no, day, fee_name, amount, is_item) VALUES(?,?,?,?,?,?,?)",
              [(A_ID, "a1", "A1", today, "Item Price Credit", 1000, 1), (A_ID, "a2", "A1", today, "Commission", -100, 0),
               (B_ID, "b1", "B1", today, "Item Price Credit", 500, 1), (B_ID, "b2", "B1", today, "Commission", -60, 0),
               (B_ID, "b3", "B1", today, "Payment Fee", -15, 0)])
c.executemany("INSERT INTO oa_lz_review(shop_id, review_id, item_id, rating, content, created, can_reply, reply) VALUES(?,?,?,?,?,?,?,?)",
              [(A_ID, "ra1", "1", 5, "ดีมาก", now - 3600, 1, "ขอบคุณ"), (A_ID, "ra2", "1", 4, "ok", now - 7200, 1, ""),
               (B_ID, "rb1", "2", 2, "แย่", now - 3600, 1, "")])
c.execute("INSERT INTO oa_lz_reverse(shop_id, line_id, reverse_id, order_no, request_type, status, refund_amount, created) VALUES(?,?,?,?,?,?,?,?)",
          (B_ID, "L1", "R1", "B1", "RETURN", "REQUEST_INITIATE", 30, now - 600))
for k in LZ.KINDS:
    c.execute("INSERT OR REPLACE INTO oa_lz_state(shop_id, kind, last_try, last_ok, error, hint, rows) VALUES(?,?,?,?,?,?,?)", (A_ID, k, now, now, "", "", 1))
    c.execute("INSERT OR REPLACE INTO oa_lz_state(shop_id, kind, last_try, last_ok, error, hint, rows) VALUES(?,?,?,?,?,?,?)",
              (B_ID, k, now, now if k != "finance" else None, "InsufficientPermission" if k == "finance" else "", "", 1))
c.commit()

# ---------- 客服：ShopB 有一个买家在等回复 ----------
cs_on = modules.enabled("cs")
if cs_on:
    from modules.cs.logic import data as csd
    cid = csd.create_conv("buyer1", "lazada", "api", B_ID)["id"]
    c.execute("INSERT INTO cs_msg(conv_id, role, text, created_at) VALUES(?,?,?,?)", (cid, "seller", "hi", now - 900))
    c.execute("INSERT INTO cs_msg(conv_id, role, text, created_at) VALUES(?,?,?,?)", (cid, "buyer", "ยังไม่ได้ของ", now - 600))
    cid2 = csd.create_conv("buyer2", "lazada", "api", A_ID)["id"]                              # 已经回了：不算
    c.execute("INSERT INTO cs_msg(conv_id, role, text, created_at) VALUES(?,?,?,?)", (cid2, "buyer", "สวัสดี", now - 900))
    c.execute("INSERT INTO cs_msg(conv_id, role, text, created_at) VALUES(?,?,?,?)", (cid2, "seller", "ค่ะ", now - 600))
    c.commit()

# ---------- 指标名字 / 没数据 ----------
pl = LZ.perf_label({"name": "Basket size", "type": "BASKET_SIZE", "value": "", "target": "", "ok": True})
ok(pl["zh"] != "Basket size" and "客单价" in pl["zh"] and pl["th"] and pl["known"], f"Basket size has zh/th names {pl['zh']} {pl['th']}")
ok(pl["nodata"] and pl["ok"] is None and pl["v"] is None, "no score → nodata, not counted as passing even if API says target_respected")
pl = LZ.perf_label({"name": "", "type": "SOME_NEW_THING", "value": "3", "target": "", "ok": None})
ok(pl["zh"] == "Some new thing" and pl["known"] is False, f"unknown indicator → readable label {pl['zh']}")
for nm in ("Positive Seller Rating", "Ship on Time", "Cancellation Rate", "Chat Response Rate", "Chat Response Time", "Return Rate", "Penalty Points",
           "Fast Delivery Rate", "Conversion Rate", "Visitors", "Product Rating", "Basket size"):
    x = LZ.perf_label({"name": nm, "type": "", "value": "1", "target": "", "ok": None})
    ok(x["known"] and x["zh"] != nm and x["th"] != nm, f"{nm} → {x['zh']} / {x['th']}")
ok(LZ.perf_label({"name": "Cancellation Rate", "type": "", "value": "0%", "target": "≤ 2%", "ok": None})["ok"] is True, "0% is real data (not nodata)")

# ---------- 总览：全部店铺 ----------
r = C.get("/api/oa/dashboard?range=7").get_json()
cp = r["compare"]
ok(cp is not None and isinstance(cp["rows"], list), "compare present in summary mode")
rows = {(x["platform"], x["shop"]): x for x in cp["rows"]}
a, b, cc = rows.get(("lazada", "ShopA Lazada")), rows.get(("lazada", "ShopB Lazada")), rows.get(("shopee", "ShopC Shopee"))
ok(a and b and cc, f"one row per shop {list(rows)}")
ok(a["n"] == 2 and abs(a["revenue"] - 1500) < 0.01 and b["n"] == 2 and abs(b["revenue"] - 280) < 0.01 and cc["n"] == 2 and abs(cc["revenue"] - 900) < 0.01,
   f"per-shop orders/revenue {a['n']} {a['revenue']} {b['n']} {b['revenue']} {cc['n']} {cc['revenue']}")
t = cp["total"]
ok(t["n"] == r["kpi"]["n"] and abs(t["revenue"] - r["kpi"]["revenue"]) < 0.01 and abs(t["profit"] - r["kpi"]["profit"]) < 0.05,
   f"totals = summary {t['n']} {t['revenue']} {t['profit']} vs {r['kpi']}")
ok(t["margin"] == r["kpi"]["margin"], f"total margin = summary margin {t['margin']} {r['kpi']['margin']}")
ok(abs(sum(x["revenue"] for x in cp["rows"]) - t["revenue"]) < 0.01 and sum(x["n"] for x in cp["rows"]) == t["n"], "rows add up to total")
bp = {x["platform"]: x for x in cp["by_platform"]}
ok(bp["lazada"]["n"] == 4 and abs(bp["lazada"]["revenue"] - 1780) < 0.01 and bp["lazada"]["shops"] >= 2 and abs(bp["shopee"]["revenue"] - 900) < 0.01,
   f"group by platform {bp.get('lazada')}")
ok(abs(sum(x["revenue"] for x in cp["by_platform"]) - t["revenue"]) < 0.01, "platform groups add up to total")
bw = cp["best_worst"]
ok(bw["revenue"]["best"]["shop"] == "ShopA Lazada" and bw["revenue"]["worst"]["shop"] == "ShopB Lazada", f"best/worst revenue {bw.get('revenue')}")
ok(bw["profit"]["best"]["shop"] == "ShopA Lazada" and bw["profit"]["worst"]["shop"] == "ShopB Lazada", f"best/worst profit {bw.get('profit')}")
ok("margin" in bw and bw["margin"]["best"]["value"] >= bw["margin"]["worst"]["value"], "best/worst margin")
ok(b["to_ship"] == 1 and b["overdue"] == 1 and a["to_ship"] == 0, "to-ship per shop")
ok(a["rating"] == 4.5 and a["reviews"] == 2 and b["rating"] == 2 and b["bad_open"] == 1 and cc.get("rating") is None, "avg rating per Lazada shop, none for Shopee")
ok(b["returns"] == 1 and a["returns"] == 0, "returns per shop")
ok(a["fee_rate"] == 10 and b["fee_rate"] == 15, f"real fee rate per shop {a['fee_rate']} {b['fee_rate']}")
ok(t["fee_rate"] == round(175 / 1500 * 100, 2), f"combined fee rate {t['fee_rate']}")
ok(a["perf"] == {"ok": 2, "n": 2, "nodata": 2} and b["perf"] == {"ok": 0, "n": 1, "nodata": 1},
   f"perf counts exclude no-data indicators {a['perf']} {b['perf']}")
ok(a["sync"]["tone"] == "ok" and b["sync"]["tone"] == "bad" and b["sync"]["errors"][0]["kind"] == "finance" and cc.get("sync") is None, "sync dot per shop")
ok(t["sync"]["tone"] == "bad" and t["sync"]["bad"] == 1, "total sync shows a shop with errors")
if cs_on:
    ok(cp["cs"] and b["unreplied"] == 1 and a["unreplied"] == 0 and t["unreplied"] >= 1, f"unreplied chats per shop {a['unreplied']} {b['unreplied']}")
lz = r["lazada"]
ok(len(lz["performance"]) == 2 and {p["shop_id"] for p in lz["performance"]} == {A_ID, B_ID}, "performance per shop on overview")
ok(lz["perf_count"] == {"ok": 2, "n": 3, "nodata": 3}, f"overview perf count: x/y + no data {lz['perf_count']}")
comb = {g["key"]: g for g in lz["perf_combined"]}
ok(comb["SHIP_ON_TIME"]["worst"]["shop"] == "ShopB Lazada" and comb["SHIP_ON_TIME"]["worst"]["v"] == 80 and comb["SHIP_ON_TIME"]["bad_n"] == 1,
   "combined: worst shop per indicator")
ok(comb["CANCELLATION_RATE"]["worst"]["shop"] == "ShopA Lazada" and comb["CANCELLATION_RATE"]["nodata_n"] == 1, "worst ignores shops without data")
ok(comb["BRAND_NEW_METRIC"]["nodata"] and comb["BRAND_NEW_METRIC"]["worst"] is None, "indicator with no data anywhere")
ok(lz["reviews"]["n"] == 3 and lz["shops"] == 2, "summary Lazada numbers = all shops")
ok(len({x["shop"] for x in lz["status"]}) == 2, "status for both shops")

# ---------- 选了一个店铺 ----------
r2 = C.get("/api/oa/dashboard?range=7&shop=ShopB%20Lazada").get_json()
ok(r2["compare"] is None and r2["kpi"]["n"] == 2, "single shop: no comparison, KPIs only this shop")
l2 = r2["lazada"]
ok(l2["reviews"]["n"] == 1 and l2["reverse"]["n"] == 1 and l2["shops"] == 1 and [p["shop_id"] for p in l2["performance"]] == [B_ID],
   "single shop: Lazada reviews / returns / performance only this shop")
ok(l2["fees"]["rate"] == 15 and {s["shop_id"] for s in l2["status"]} == {B_ID} and l2["perf_combined"] is None, "single shop: fees + status")
ok(l2["perf_count"] == {"ok": 0, "n": 1, "nodata": 1}, f"single shop perf count {l2['perf_count']}")
ok(r2["shipping"]["to_ship"] == 1 and r2["shipping"]["overdue_n"] == 1 and r["shipping"]["to_ship"] >= 1, "single shop: shipping card only this shop")
r3 = C.get("/api/oa/dashboard?range=7&shop=ShopC%20Shopee").get_json()
ok(r3["lazada"]["shops"] == 0 and r3["lazada"]["reviews"]["n"] == 0 and not r3["lazada"]["performance"], "Shopee shop: no Lazada data")
r4 = C.get("/api/oa/dashboard?range=7&platform=lazada").get_json()
ok(r4["compare"] and {x["platform"] for x in r4["compare"]["rows"]} == {"lazada"} and r4["compare"]["total"]["n"] == r4["kpi"]["n"],
   "platform filter: compare only that platform's shops, total = summary")
r5 = C.get("/api/oa/dashboard?range=7&platform=shopee").get_json()
ok(r5["lazada"]["shops"] == 0 and not r5["lazada"]["performance"], "other platform: no Lazada data")
ok(any(s["shop"] == "ShopC Shopee" for s in r["filters"]["shops"]), "filter options include shops")

# ---------- 店铺与评价：同样的筛选 ----------
l = C.get("/api/oa/lazada?days=7").get_json()
ok(l["scope"]["shop_ids"] is None and len(l["per_shop"]) == 2 and l["perf_combined"] and l["filters"]["shops"], "lazada tab: all shops + per-shop table")
ps = {x["shop_id"]: x for x in l["per_shop"]}
ok(ps[A_ID]["fees"]["rate"] == 10 and ps[B_ID]["reverse"]["n"] == 1 and ps[B_ID]["reviews"]["bad_open"] == 1 and ps[A_ID]["perf"]["nodata"] == 2,
   "per-shop reviews / returns / fee / perf")
lb = C.get("/api/oa/lazada?days=7&shop=ShopA%20Lazada").get_json()
ok(lb["scope"]["shop_ids"] == [A_ID] and {x["shop_id"] for x in lb["reviews"]} == {A_ID} and not lb["reverse"] and lb["per_shop"] is None
   and lb["fees"]["rate"] == 10 and len(lb["performance"]) == 1, "lazada tab: one shop")
lc = C.get("/api/oa/lazada?days=7&shop=ShopC%20Shopee").get_json()
ok(lc["scope"]["shop_ids"] == [] and not lc["reviews"] and not lc["performance"], "lazada tab: Shopee shop → nothing (page explains)")
ll = CL.get("/api/oa/lazada?days=7&shop=ShopB%20Lazada").get_json()
ok(ll["ok"] and "per_shop" not in ll and {x["shop_id"] for x in ll["reviews"]} == {B_ID}, "listing staff: reviews filtered, no owner data")
ok(CL.get("/api/oa/dashboard").status_code == 403, "overview still owner only")

# 关掉的店铺：店铺表现不再显示
integrations.save_shop({"id": B_ID, "platform": "lazada", "name": "ShopB Lazada", "enabled": False, "creds": CR})
ok([p["shop_id"] for p in LZ.performance()] == [A_ID], "disabled shop hidden from performance")
print("ERRORS", E_)
