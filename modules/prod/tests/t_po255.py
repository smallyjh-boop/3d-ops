# v2.55：新建生产单像逛产品库一样选——「建议生产」清单（按急迫排序、理由、整盘取整、订单待打、已盖住的不出现）、「全部产品」按近 30 天销量排（可按类目 / 标签 / 自动分组筛）、
# 从选好的清单建草稿 / 直接下达（交期、加急、专用打印机用稳定 id）、预计克数 / 机时用的数据、和成品备货「一键补货」不重复建单
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import json, os, sys, shutil, sqlite3, time
D = T + "/m_po255"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, production, store, po
from core.inventory import goodsstock as G
db.create_user("boss", "secret123", "owner", "Boss"); db.create_user("pong", "secret123", "production", "Pong")
db.create_user("lee", "secret123", "listing", "Lee")
def cli(u):
    c = A.app.test_client(); c.post("/api/auth/login", json={"username": u, "password": "secret123"}); return c
C, PC, LC = cli("boss"), cli("pong"), cli("lee")
PRS = [{"code": "P1S-01", "name": "Bambu Lab P1S", "g_per_h": 22, "enabled": True}, {"code": "K1C-01", "name": "Creality K1C", "g_per_h": 18, "enabled": True}]
config.save_config({"printers": PRS, "stock_auto_use": False, "stock_cover_days": 7, "gs_sales_days": 30, "gs_safety": 1, "gs_cat_default": "",
                    "inv_qc_on": False, "review_enabled": False})
SKA, SKB, SKC = "3DP0003-WH", "3DP0003-PK", "3DP0001-PK"
sug = lambda: C.get("/api/porders/suggest").get_json()
rowof = lambda sku: next((x for x in sug()["items"] if x["sku"] == sku), None)
C.post("/api/inv/gs/add", json={"skus": [SKA, SKB, SKC]})
production.sku_per_plate = lambda sku: 4 if sku == SKA else 1          # SKA 一盘 4 个
# 销量：SKA 近期卖得最多（21 件，其中 14 件在 7 天内），SKB 卖 3 件，SKC 没销量但手动目标 5
now = time.time()
for no, sku, q, ago in (("P-A1", SKA, 14, 1), ("P-A2", SKA, 7, 20), ("P-B1", SKB, 3, 2)):
    C.post("/api/orders/manual", json={"order_no": no, "items": [{"sku": sku, "qty": q, "unit_price": 100}]})
    db.conn().execute("UPDATE orders SET order_time=? WHERE order_no=?", (now - ago * 86400, no)); db.conn().commit()
C.post("/api/inv/gs/target", json={"skus": [SKC], "target": 5})
db.conn().execute("DELETE FROM jobs WHERE kind='order'"); db.conn().commit()      # 先排除订单任务的影响，下面单独测「订单待打」

# ---------- 权限 / 形状 ----------
ok(LC.get("/api/porders/suggest").status_code == 200 and LC.get("/api/porders/picker").status_code == 200, "everybody may read the picker data")
s = sug()
ok(set(s) >= {"items", "products", "units"}, f"suggest shape {sorted(s)}")
ok(set(s["items"][0]) >= {"sku", "name", "img", "sold7", "sold30", "sellable", "making", "target", "gap", "cover_days", "qty", "per_plate", "reason_zh", "reason_th"}, "item fields")

# ---------- 建议生产：排序 / 理由 / 整盘取整 / 排除已够的 ----------
skus = [x["sku"] for x in s["items"]]
ok(SKA in skus and SKB in skus and SKC in skus, f"all three below target are suggested {skus}")
a, b, c_ = rowof(SKA), rowof(SKB), rowof(SKC)
ok(a["sold7"] == 14 and a["sold30"] == 21 and b["sold7"] == 3, f"7 / 30 day sales {a['sold7']}/{a['sold30']}")
ok(a["gap"] == G.rows()[[r["sku"] for r in G.rows()].index(SKA)]["gap"] and a["gap"] > 0, f"gap comes from goodsstock {a['gap']}")
ok(a["per_plate"] == 4 and a["qty"] % 4 == 0 and 0 <= a["qty"] - a["gap"] < 4, f"qty rounded up to full plates: gap {a['gap']} -> {a['qty']}")
ok(b["qty"] == b["gap"] and c_["qty"] == 5, f"no plate info -> plain gap ({b['qty']}, {c_['qty']})")
ok(skus.index(SKA) < skus.index(SKB) < skus.index(SKC), f"urgency order: no stock + selling first, never-sold last {skus}")
ok("近 7 天卖 14 个" in a["reason_zh"] and "已经没货" in a["reason_zh"] and "14" in a["reason_th"], f"reason: {a['reason_zh']} | {a['reason_th']}")
ok("低于目标 5" in c_["reason_zh"] and not any("一" <= ch <= "鿿" for ch in c_["reason_th"]), f"target reason {c_['reason_zh']}; Thai has no Chinese")
# 有一点库存：库存只够 N 天
db.conn().execute("UPDATE stock SET qty=1 WHERE sku=?", (SKB,)); db.conn().commit()
b = rowof(SKB)
ok(b and b["sellable"] == 1 and b["cover_days"] is not None and "库存只够" in b["reason_zh"], f"has stock -> days of cover reason: {b and b['reason_zh']}")
ok(b["gap"] == G.rows()[[r["sku"] for r in G.rows()].index(SKB)]["gap"], "gap still goodsstock's")
# 买来的、产品库里没有的不出现；够了的不出现
db.conn().execute("UPDATE stock SET qty=50 WHERE sku=?", (SKC,)); db.conn().commit()
ok(rowof(SKC) is None, "a SKU already covered (stock >= target) is not suggested")
it = C.post("/api/inv/items", json={"name_zh": "外购手机支架", "category": "goods", "unit": "个", "code": "BUY-001"}).get_json()["item"]
C.post("/api/inv/gs/target", json={"skus": ["BUY-001"], "target": 9})
ok(rowof("BUY-001") is None, "bought-in goods are not production suggestions")
# 订单待打：建议里排最前、数量加上去
C.post("/api/orders/manual", json={"order_no": "P-C1", "items": [{"sku": SKC, "qty": 3, "unit_price": 100}]})
db.conn().execute("DELETE FROM jobs WHERE kind='order' AND UPPER(sku)<>?", (SKC,))
db.conn().execute("UPDATE jobs SET status='todo', run_id=NULL, qty_done=0 WHERE kind='order'"); db.conn().commit()
nj = db.conn().execute("SELECT COALESCE(SUM(qty),0) FROM jobs WHERE kind='order' AND UPPER(sku)=?", (SKC,)).fetchone()[0]
s = sug(); c_ = rowof(SKC)
ok(nj > 0, f"manual order generated order jobs ({nj})")
if nj:
    ok(c_ and c_["order_pending"] == nj and s["items"][0]["sku"] == SKC, f"unprinted order units first: pending {c_ and c_['order_pending']}, first={s['items'][0]['sku']}")
    ok(c_["qty"] == c_["gap"] + nj and "订单还有" in c_["reason_zh"], f"qty includes order units {c_['qty']}")
else:
    ok(True, "order jobs not generated in this fixture (skipped)")
db.conn().execute("DELETE FROM jobs WHERE kind='order'"); db.conn().commit()
db.conn().execute("UPDATE stock SET qty=0 WHERE sku=?", (SKC,)); db.conn().commit()
ok(s["products"] == len({x["product_id"] for x in s["items"]}) and s["units"] == sum(x["qty"] for x in s["items"]), "card numbers = products / units of the list")

# ---------- 全部产品：按近 30 天销量，筛选 ----------
p = C.get("/api/porders/picker").get_json()
ids = [x["id"] for x in p["products"]]
ok(ids.index("3DP0003") < ids.index("3DP0001") if "3DP0001" in ids else True, "hot product first")
sold = [x["sold30"] for x in p["products"]]
ok(sold == sorted(sold, reverse=True), f"sorted by 30-day sales desc {sold[:5]}")
p3 = next(x for x in p["products"] if x["id"] == "3DP0003")
ok(p3["sold30"] == 24 and {s_["sku"] for s_ in p3["skus"]} >= {SKA, SKB}, f"product total 30d sales {p3['sold30']} with SKUs")
ok("hot" in p3["gk"] and "below" in p3["gk"] and "out" in p3["gk"], f"auto groups {p3['gk']}")
sk = next(x for x in p3["skus"] if x["sku"] == SKA)
ok(sk["sold7"] == 14 and sk["sold30"] == 21 and "sellable" in sk and "making" in sk, "SKU level numbers")
p1 = store.load("3DP0001"); p1["category"] = {"id": 1, "name": "挂件"}; p1["groups"] = []; store.save(p1)
p = C.get("/api/porders/picker").get_json()
ok("挂件" in p["categories"] and next(x for x in p["products"] if x["id"] == "3DP0001")["category"] == "挂件", "category filter data")
ok(isinstance(p["tags"], list), "tag list for the tag filter")
ok(all(not (s_["sku"] == "BUY-001") for x in p["products"] for s_ in x["skus"]), "bought-in not listed")
# 估算数据：每件克数 / 机时来自产品库
for x in p["products"]:
    for s_ in x["skus"]:
        if s_["grams_each"] is not None:
            ok(s_["grams_each"] > 0, f"grams per piece known {s_['sku']} {s_['grams_each']}")
            break
    else:
        continue
    break
v = store.load("3DP0003"); v["variants"][0]["grams"] = 20; v["variants"][0]["hours"] = 1.5; store.save(v)
s0 = next(x for x in C.get("/api/porders/picker").get_json()["products"] if x["id"] == "3DP0003")["skus"][0]
ok(s0["grams_each"] == 20 and s0["hours_each"] == 1.5, f"estimate inputs grams/hours {s0['grams_each']}/{s0['hours_each']}")

# ---------- 从选好的清单建单 ----------
items = sug()["items"]
lines = [{"sku": x["sku"], "qty": x["qty"]} for x in items[:2]]
r = PC.post("/api/porders", json={"lines": lines, "due": "2030-02-01", "priority": 1, "note": "选的", "printers": ["P1S-01"]}).get_json()
ok(r["status"] == "draft" and len(r["lines"]) == 2 and r["priority"] == 1 and r["due"] > 0, f"draft from picker {r['no']}")
ok(r["printers"] == [config.load_config()["printers"][0]["id"]] and r["printer_idx"] == [0], f"printer restriction stored as stable id {r['printers']}")
ok([x["qty"] for x in r["lines"]] == [x["qty"] for x in items[:2]], "edited/suggested quantities kept")
left = [x["sku"] for x in sug()["items"]]
ok(items[0]["sku"] not in left and items[1]["sku"] not in left, "SKUs in a draft are no longer suggested (covered)")
r2 = C.post("/api/porders", json={"lines": [{"sku": SKC, "qty": 4}], "release": True}).get_json()
ok(r2["status"] == "released", "create + release in one go")
ok(rowof(SKC) is None, "released lines count as in production")
# 改草稿（选择器同一个接口）
up = C.post(f"/api/porders/{r['id']}", json={"lines": [{"sku": items[0]["sku"], "qty": 9}], "printers": []}).get_json()
ok(up["qty"] == 9 and up["printers"] == [], "edit a draft: lines + clear printers")

# ---------- 和一键补货不重复 ----------
config.save_config({"printers": PRS})
db.conn().execute("DELETE FROM production_orders"); db.conn().execute("DELETE FROM po_lines"); db.conn().execute("DELETE FROM jobs"); db.conn().commit()
db.conn().execute("UPDATE stock SET qty=0"); db.conn().commit()
before = {x["sku"] for x in sug()["items"]}
plan = {x["sku"]: x for x in G.plan() if x["type"] == "own"}
ok(before >= set(plan) and all(rowof(k)["qty"] == v["qty"] for k, v in plan.items()), "suggestion qty == 一键补货 plan qty when no unprinted orders")
rp = C.post("/api/inv/gs/replenish", json={"skus": [SKB]}).get_json()
ok(rp["po"] and rowof(SKB) is None, "一键补货 creates a draft; the suggestion drops that SKU")
rl = C.post("/api/inv/gs/replenish", json={"lines": [{"sku": SKB, "qty": 3}]})
ok(rl.status_code == 400, "the replenish API refuses to duplicate it")
n_po = len(C.get("/api/porders").get_json()["orders"])
other = [x for x in sug()["items"] if x["sku"] != SKB][:1]
C.post("/api/porders", json={"lines": [{"sku": other[0]["sku"], "qty": other[0]["qty"]}]})
ok(other[0]["sku"] not in {x["sku"] for x in G.plan()}, "created from the picker -> 一键补货 no longer proposes it")
ok(len(C.get("/api/porders").get_json()["orders"]) == n_po + 1, "one order created")

# ---------- 界面文件 ----------
js = open(APP + "/modules/prod/ui/po.js", encoding="utf-8").read()
ok("/api/porders/suggest" in js and "/api/porders/picker" in js and 'editModal(null, "sug")' in js and "建议生产：" in js, "UI wires the picker + top card")
print("ERRORS", E_)
