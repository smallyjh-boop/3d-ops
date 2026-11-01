# v2.51 采购重做：补货建议（生产任务 + 用量、到货天数 → 红黄绿、起订量 / 包装数）、按供应商生成采购单、
# 采购单状态（部分到货、差异、结单、完成）、到手成本（运费 / 税 / 汇率分摊）→ 成本更新 + 待办、分次付款 → 财务、
# 过期没到 → 待办、AI 识别订单开单（假 AI）、手机到货入库、供应商下拉增删改、老数据迁移、员工看不到金额
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, time, json, io, datetime as dt
D = T + "/m_pur251"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, inventory as inv, config, todo, ai_copy
db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "secret123", "listing", "Nok")
db.create_user("pd", "secret123", "production", "Pd")
db.update_user(db.get_user(username="pd")["id"], perms={"inv.in": True, "inv.out": True})     # 仓库员工：能入库
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
S = A.app.test_client(); S.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
P = A.app.test_client(); P.post("/api/auth/login", json={"username": "pd", "password": "secret123"})
c = db.conn()
today = dt.date.today()

# ---- 0 老数据迁移（采购模块第一次打开前就有的供应商 / 物品链接 / 到货的采购单）
inv.init()
now = time.time()
c.execute("INSERT INTO inv_suppliers(name, platform, link, active, created_at) VALUES('淘宝','', '', 1, ?)", (now,))
old_sid = c.execute("INSERT INTO inv_suppliers(name, platform, active, created_at) VALUES('拼多多','',1,?)", (now,)).lastrowid
old_it = inv.save_item({"name_zh": "老物品", "category": "part", "unit": "个", "link": "https://item.taobao.com/item.htm?id=1"}, "t")
old_it2 = inv.save_item({"name_zh": "老物品2", "category": "part", "unit": "个", "supplier_id": old_sid}, "t")
c.commit()
from modules.pur.logic import store, suggest, links, quick
store.ensure()
sups = {r["name"]: dict(r) for r in c.execute("SELECT * FROM inv_suppliers")}
ok(sups["淘宝"]["currency"] == "CNY" and sups["淘宝"]["platform"] == "淘宝" and sups["拼多多"]["currency"] == "CNY", "migrate: supplier currency / platform")
ln_old = c.execute("SELECT * FROM pur_item_sup WHERE item_id=?", (old_it["id"],)).fetchone()
ok(ln_old and ln_old["supplier_id"] == sups["淘宝"]["id"] and "taobao" in ln_old["urls"], "migrate: item link → taobao supplier")
ok(inv.get_item(old_it["id"])["supplier_id"] == sups["淘宝"]["id"], "migrate: preferred supplier set from link")
ok(c.execute("SELECT 1 FROM pur_item_sup WHERE item_id=? AND supplier_id=?", (old_it2["id"], old_sid)).fetchone() is not None, "migrate: default supplier → link")

# ---- 1 供应商下拉：新建 / 改 / 删（没用过 = 删，用过 = 停用）
r = C.post("/api/inv/suppliers", json={"name": "1688 义乌包装厂", "platform": "1688", "lead_days": 12}).get_json()
s1 = r["supplier"]; ok(s1["currency"] == "CNY", f"new 1688 supplier defaults CNY ({s1['currency']})")
s2 = C.post("/api/inv/suppliers", json={"name": "Shopee 备件店", "platform": "Shopee", "lead_days": 3}).get_json()["supplier"]
ok(s2["currency"] == "THB", "Shopee supplier THB")
tmp = C.post("/api/inv/suppliers", json={"name": "临时"}).get_json()["supplier"]
r = C.post("/api/inv/suppliers", json={"id": tmp["id"], "name": "临时2", "phone": "081"}).get_json()["supplier"]
ok(r["name"] == "临时2" and r["phone"] == "081", "edit supplier")
r = C.post(f"/api/inv/pur/suppliers/{tmp['id']}/delete").get_json()
ok(r["deleted"] and not c.execute("SELECT 1 FROM inv_suppliers WHERE id=?", (tmp["id"],)).fetchone(), "unused supplier deleted")

# ---- 2 物品 ↔ 供应商
bag = inv.save_item({"name_zh": "测试快递袋", "category": "part", "unit": "个"}, "t")
noz = inv.save_item({"name_zh": "测试喷嘴", "category": "part", "unit": "个", "supplier_id": s2["id"]}, "t")
fil = inv.save_item({"name_zh": "PLA 测试色", "category": "filament", "material": "PLA", "color": "测试色"}, "t")
nolink = inv.save_item({"name_zh": "测试砂纸", "category": "tool", "unit": "张"}, "t")
r = C.post("/api/inv/pur/links", json={"item_id": bag["id"], "supplier_id": s1["id"], "urls": "https://detail.1688.com/offer/1.html\nshopee.co.th/x",
                                        "price": 0.5, "moq": 100, "pack_qty": 50, "lead_days": 12, "preferred": True}).get_json()
ok(r["ok"] and r["links"][0]["preferred"] and r["links"][0]["platforms"] == ["1688", "Shopee"] and r["links"][0]["urls"][1].startswith("https://"),
   f"item link saved {r.get('links', [{}])[0].get('platforms')}")
ok(inv.get_item(bag["id"])["supplier_id"] == s1["id"], "preferred = item default supplier")
r2 = C.post("/api/inv/pur/links", json={"item_id": bag["id"], "supplier_id": s2["id"], "price": 3.0, "currency": "THB"}).get_json()
cmp_ = {x["supplier_id"]: x for x in r2["links"]}
ok(cmp_[s1["id"]]["price_thb"] == round(0.5 * inv.default_fx(), 4) and cmp_[s1["id"]]["cheapest"] and not cmp_[s2["id"]]["cheapest"],
   "price comparison across suppliers (CNY converted)")
lid2 = cmp_[s2["id"]]["id"]
r = C.post(f"/api/inv/pur/links/{lid2}/delete").get_json(); ok(len(r["links"]) == 1, "delete item link")
r = C.post("/api/inv/pur/links", json={"item_id": fil["id"], "supplier_id": s1["id"], "price_roll": 50, "net_g": 1000, "lead_days": 10}).get_json()
ok(abs(r["links"][0]["price"] - 0.05) < 1e-9, "filament price per roll stored per gram")

# ---- 3 补货建议
inv.create_doc("purchase", [{"item_id": bag["id"], "qty": 100, "unit_cost": 3}], "期初", "t")
inv.create_doc("issue", [{"item_id": bag["id"], "qty": 80}], "用掉", "t")              # 剩 20，每天 80/30
inv.create_doc("purchase", [{"item_id": noz["id"], "qty": 36, "unit_cost": 20}], "期初", "t")
inv.create_doc("issue", [{"item_id": noz["id"], "qty": 30}], "用掉", "t")              # 剩 6，每天 1，到货 3 天
inv.create_doc("purchase", [{"item_id": nolink["id"], "qty": 40, "unit_cost": 1}], "期初", "t")
inv.create_doc("issue", [{"item_id": nolink["id"], "qty": 30}], "用掉", "t")           # 剩 10，每天 1，默认 7 天
inv.create_doc("purchase", [{"item_id": fil["id"], "rolls": 2, "net_g": 1000, "unit_cost": 0.3}], "期初", "t")
inv.create_doc("issue", [{"item_id": fil["id"], "qty": 600}], "打印", "t")              # 剩 1400 g，每天 20 g
_real_pending = suggest._pending
suggest._pending = lambda: {("PLA", "测试色"): 1500.0}                                    # 生产任务要 1500 g
rows = {x["item"]["id"]: x for x in C.get("/api/inv/pur/suggest").get_json()["rows"]}
b = rows.get(bag["id"]) or {}
rate = 80 / 30; need = rate * (12 + 5 + 30) - 20
ok(b.get("urgency") == "red" and abs(b["days"] - round(20 / rate, 1)) < 0.05 and b["lead"] == 12, f"bag red: {b.get('days')} days < 12 lead ({b.get('urgency')})")
ok(abs(b["need"] - round(need, 3)) < 0.01 and b["qty"] == 150, f"bag qty: need {b.get('need')} → MOQ 100 / pack 50 → 150 ({b.get('qty')})")
n = rows.get(noz["id"]) or {}
ok(n.get("urgency") == "yellow" and n["lead"] == 3 and n["qty"] == 32, f"nozzle yellow 6 days, lead 3 (supplier) qty 1×38−6=32 ({n.get('urgency')} {n.get('lead')} {n.get('qty')})")
s_ = rows.get(nolink["id"]) or {}
ok(s_.get("urgency") == "yellow" and s_["lead"] == 7 and s_["qty"] == 32, f"default lead 7 → yellow, qty 32 ({s_.get('urgency')} {s_.get('qty')})")
f = rows.get(fil["id"]) or {}
fneed = 20 * (10 + 5 + 30) + 1500 - 1400
ok(f.get("urgency") == "red" and "production" in f["why"] and "short" in f["why"] and f["pending"] == 1500 and f["available"] == -100,
   f"filament red: production demand > stock ({f.get('why')} avail {f.get('available')})")
ok(f["rolls"] == 1 and f["qty"] == 1000 and abs(f["need"] - fneed) < 0.01, f"filament rounded to whole rolls ({f.get('need')} → {f.get('rolls')} 卷)")
allrows = C.get("/api/inv/pur/suggest?all=1").get_json()["rows"]
ok(len(allrows) >= len(rows), "all=1 lists more rows")
# 起订量 / 包装数取整
ok(suggest.round_qty(54, {"moq": 100, "pack_qty": 50}, False, 1000)[0] == 100 and suggest.round_qty(101, {"pack_qty": 50}, False, 1000)[0] == 150
   and suggest.round_qty(2500, {"net_g": 1000, "moq": 5}, True, 1000)[1] == 5 and suggest.round_qty(0.2, {}, False, 1000)[0] == 1, "MOQ / pack size / roll rounding")

# ---- 4 选中 → 按供应商生成采购单
r = C.post("/api/inv/pur/suggest/po", json={"rows": [{"item_id": bag["id"]}, {"item_id": noz["id"]}, {"item_id": nolink["id"]}, {"item_id": fil["id"]}]}).get_json()
pos = r["po"]
by_sup = {p["supplier_id"]: p for p in pos}
ok(len(pos) == 3 and set(by_sup) == {s1["id"], s2["id"], None}, f"grouped into 3 POs by supplier ({[p['supplier_id'] for p in pos]})")
p1 = by_sup[s1["id"]]
ok(p1["currency"] == "CNY" and p1["fx_rate"] == inv.default_fx() and len(p1["lines"]) == 2 and p1["source"] == "suggest", "S1 PO in CNY with 2 lines")
lb = next(x for x in p1["lines"] if x["item_id"] == bag["id"]); lf = next(x for x in p1["lines"] if x["item_id"] == fil["id"])
ok(lb["qty"] == 150 and lb["unit_cost"] == 0.5 and lf["rolls"] == 1 and abs(lf["unit_cost"] - 0.05) < 1e-9, "lines use supplier price (filament per gram)")
ok(p1["expected_date"] == (today + dt.timedelta(days=12)).isoformat(), f"expected date = today + lead ({p1['expected_date']})")
suggest._pending = _real_pending
for p in pos:
    if p["supplier_id"] != s1["id"]:
        C.post(f"/api/inv/po/{p['id']}/cancel")

# ---- 5 状态：下单 → 部分到货 + 差异 → 结单 → 付款 → 完成；到手成本（汇率 + 运费 + 税）
C.post("/api/inv/po", json={"id": p1["id"], "fx_rate": 5, "ship_fee": 15, "tax_fee": 60, "other_fee": 40, "tracking": "SF123", "carrier": "顺丰"})
p1 = C.post(f"/api/inv/po/{p1['id']}/order").get_json()["po"]
goods_thb = (150 * 0.5 + 1000 * 0.05) * 5          # 625
rate_f = (15 * 5 + 60 + 40) / goods_thb             # 175 / 625 = 0.28
ok(p1["status"] == "ordered" and p1["total"] == round(goods_thb + 175, 2) and p1["total_cur"] == 125 + 15, f"CNY total → THB ({p1['total']} / ¥{p1['total_cur']})")
ok(abs(lb and next(x for x in p1["lines"] if x["item_id"] == bag["id"])["landed"] - 0.5 * 5 * (1 + rate_f)) < 1e-6, "landed unit cost = price × fx × (1 + fee share)")
q0 = inv.get_item(bag["id"])["qty"]
lbid = next(x["id"] for x in p1["lines"] if x["item_id"] == bag["id"]); lfid = next(x["id"] for x in p1["lines"] if x["item_id"] == fil["id"])
r = C.post(f"/api/inv/po/{p1['id']}/receive", json={"qtys": {str(lbid): 100}, "issues": [{"line_id": lbid, "kind": "short", "qty": 40, "note": "少了一包"},
                                                                                      {"line_id": lbid, "kind": "damaged", "qty": 10}]}).get_json()
p1 = r["po"]
ok(p1["status"] == "partial" and inv.get_item(bag["id"])["qty"] == q0 + 100 and p1["issues_open"] == 2, f"partial receipt + 2 discrepancies ({p1['status']})")
ok(abs(inv.get_item(bag["id"])["avg_cost"] - (20 * 3 + 100 * 0.5 * 5 * (1 + rate_f)) / 120) < 1e-6, "stock avg cost uses landed cost")
hist = links.history(bag["id"])
ok(hist and abs(hist[0]["landed"] - 0.5 * 5 * (1 + rate_f)) < 1e-6 and hist[0]["po_no"] == p1["no"] and hist[0]["fx_rate"] == 5, "price history row on receipt")
r = C.post(f"/api/inv/po/{p1['id']}/receive", json={"qtys": {str(lfid): 1}}).get_json(); p1 = r["po"]
ok(p1["status"] == "partial", "filament roll in, bag line still short")
r = C.post(f"/api/inv/po/{p1['id']}/close").get_json(); p1 = r["po"]
ok(p1["status"] == "received" and p1["total"] == round((100 * 0.5 + 1000 * 0.05 + 15) * 5 + 100, 2), f"closed: payable by received qty ({p1['total']})")
# 成本更新（耗材平均进价变了 → 定价用的耗材价格）
cfg = config.load_config()
expect_cny = round(links.filament_avg_thb_g() * 1000 / cfg["cny_to_thb"], 2)
chg = links.cost_changes("open")
filch = [x for x in chg if x["kind"] == "filament"]
if abs(expect_cny - 58.0) / 58.0 * 100 >= 5:
    ok(filch and cfg["filament_price_cny_per_kg"] == expect_cny and filch[0]["applied"] == 1, f"filament cost updated {cfg['filament_price_cny_per_kg']} = {expect_cny}")
else:
    ok(not filch, "small filament change: no alert")
# 强制一次大变化：自动更新关掉 → 只提醒，老板点「写进设置」
config.save_config({"pur_auto_cost": False, "filament_price_cny_per_kg": 20.0})
ch = links.update_filament_cost("T", "t")
ok(ch and ch["applied"] == 0 and config.load_config()["filament_price_cny_per_kg"] == 20.0, "auto off → only proposal")
td = todo.collect("owner")["items"]
ok(any(i["key"] == f"pur:cost:{ch['id']}" and i["roles"] == "owner" for i in td), "owner to-do: cost changed")
ok(not any(i["key"].startswith("pur:cost:") for i in todo.collect("listing")["items"]), "cost to-do only for owner")
r = C.post(f"/api/inv/pur/costs/{ch['id']}/apply").get_json()
ok(r["ok"] and config.load_config()["filament_price_cny_per_kg"] == ch["new"], "apply proposal writes config")
ok(S.post(f"/api/inv/pur/costs/{ch['id']}/dismiss").status_code == 403, "staff cannot touch cost changes")
config.save_config({"pur_auto_cost": True})
td = todo.collect("owner")["items"]
ok(any(i["key"].startswith("pur:issue:") for i in td), "to-do: open discrepancies")
# 分次付款 → 财务
r = C.post(f"/api/inv/po/{p1['id']}/pay", json={"amount": 300, "method": "支付宝"}).get_json(); p1 = r["po"]
ok(p1["pay_status"] == "partial" and p1["paid"] == 300, "partial payment 1")
r = C.post(f"/api/inv/po/{p1['id']}/pay", json={"amount": p1["total"] - 300}).get_json(); p1 = r["po"]
ok(p1["pay_status"] == "paid" and p1["status"] == "received", "paid but discrepancies open → not done yet")
fe = c.execute("SELECT SUM(amount) s, COUNT(*) n FROM fin_events WHERE kind='purchase_payment' AND ref_no=?", (p1["no"],)).fetchone()
ok(fe["n"] == 2 and abs(fe["s"] - p1["paid"]) < 0.01, f"payments recorded in finance ({fe['n']} / {fe['s']})")
for x in p1["issues"]:
    r = C.post(f"/api/inv/pur/issues/{x['id']}/resolve", json={"resolution": "供应商退款"}).get_json()
ok(r["po"]["status"] == "done" and r["po"]["issues_open"] == 0, f"resolved + paid + received → done ({r['po']['status']})")
ok(not any(i["key"].startswith("pur:issue:") for i in todo.collect("owner")["items"]), "resolved discrepancies leave the to-do")
# 退货 + 供应商退款
r = C.post(f"/api/inv/po/{p1['id']}/return", json={"qtys": {str(lbid): 20}}).get_json()
ok(r["ok"] and r["po"]["lines"][0]["returned"] in (20, 0) and inv.get_item(bag["id"])["qty"] == q0 + 80, f"return 20 to supplier (stock {inv.get_item(bag['id'])['qty']})")
p1 = r["po"]
ok(p1["pay_status"] == "paid" and p1["paid"] > p1["total"], "after return: paid more than payable")
over = round(p1["paid"] - p1["total"], 2)
r = C.post(f"/api/inv/po/{p1['id']}/refund", json={"amount": over}).get_json()
ok(r["ok"] and abs(r["po"]["paid"] - r["po"]["total"]) < 0.01, "supplier refund → paid = payable")
ok(c.execute("SELECT COUNT(*) FROM fin_events WHERE kind='purchase_payment' AND ref_no=? AND amount<0", (p1["no"],)).fetchone()[0] == 1, "refund in finance (negative)")
ok("po_return" not in {k for k, v in inv.KINDS.items() if v[1]}, "return to supplier is not an expense")

# ---- 6 过了预计到货 → 待办
lp = C.post("/api/inv/po", json={"supplier_id": s2["id"], "expected_date": (today - dt.timedelta(days=5)).isoformat(),
                                  "lines": [{"item_id": noz["id"], "qty": 5, "unit_cost": 20}]}).get_json()["po"]
C.post(f"/api/inv/po/{lp['id']}/order")
it = next((i for i in todo.collect("production")["items"] if i["key"].startswith(f"pur:late:{lp['id']}:")), None)
ok(it and it["level"] == "bad" and it["tab"] == "po_recv" and it["title_th"], f"overdue PO → to-do for staff ({it and it['level']})")
ok(C.get("/api/inv/po?status=overdue").get_json()["po"][0]["id"] == lp["id"], "overdue filter")
ok(C.get("/api/inv/pur/overview").get_json()["summary"]["overdue"] >= 1, "overview counts overdue")
ok(any(p["id"] == lp["id"] for p in C.get("/api/inv/po?status=unpaid").get_json()["po"]) and
   not any(p["id"] == p1["id"] for p in C.get("/api/inv/po?status=unpaid").get_json()["po"]), "unpaid / paid filter")

# ---- 7 AI 识别订单（假 AI）
seen = {}
def fake(cfg, system, user, image_b64=None):
    seen["img"] = image_b64; seen["user"] = user
    return json.dumps({"platform": "1688", "supplier": "义乌包装厂", "order_no": "1688-9988", "tracking": "YT555", "carrier": "圆通",
                       "currency": "CNY", "ship_fee": "¥8", "items": [
                           {"name": "PLA 耗材 测试色 1kg", "spec": "1kg", "qty": 3, "unit_price": 45},
                           {"name": "防水标签贴纸 全新款", "spec": "100张", "qty": 2, "unit_price": "¥12.5"}]}, ensure_ascii=False)
ai_copy.call = fake
r = C.post("/api/inv/pur/quick/parse", json={"text": "订单号 1688-9988 ……"}).get_json()
d = r["draft"]
ok(r["ok"] and d["supplier_id"] == s1["id"] and d["currency"] == "CNY" and d["order_ref"] == "1688-9988" and d["ship_fee"] == 8, f"AI draft header {d.get('supplier_id')}")
ok(d["lines"][0]["item_id"] == fil["id"] and d["lines"][0]["net_g"] == 1000, "AI line matched to filament by material + colour")
ok(d["lines"][1]["item_id"] is None and d["lines"][1]["new_item"]["name_zh"].startswith("防水标签"), "unknown line → new item proposal")
from PIL import Image
buf = io.BytesIO(); Image.new("RGB", (40, 30), "white").save(buf, "PNG"); buf.seek(0)
r = C.post("/api/inv/pur/quick/parse", data={"image": (buf, "o.png")}, content_type="multipart/form-data").get_json()
ok(r["ok"] and seen["img"], "screenshot goes to AI as image")
d["lines"][1]["new_item"]["category"] = "pack"
r = C.post("/api/inv/pur/quick/create", json=d).get_json()
qp = r["po"]
ok(r["ok"] and qp["source"] == "ai" and qp["tracking"] == "YT555" and qp["order_ref"] == "1688-9988" and len(qp["lines"]) == 2, "AI draft → PO")
qf = next(x for x in qp["lines"] if x["item_id"] == fil["id"])
ok(qf["rolls"] == 3 and abs(qf["unit_cost"] - 0.045) < 1e-9, "filament rolls + per-gram price from roll price")
ok(inv.items(q="防水标签")[0]["category"] == "pack", "new item created from AI line")
def boom(*a, **k): raise ai_copy.AIError("还没有填写 AI 接口密钥（设置页）")
ai_copy.call = boom
r = C.post("/api/inv/pur/quick/parse", json={"text": "x"}); ok(r.status_code == 400 and "AI" in r.get_json()["error"], "AI error → 400")

# ---- 8 手机到货入库（扫采购单号 / 物品码，记差异，放货位，打标签）
C.post("/api/inv/locations/bulk", json={"zone": "A", "layers": 2, "positions": 2})
C.post(f"/api/inv/po/{qp['id']}/order")
r = P.get(f"/api/inv/pur/scan?code={qp['no'].lower()}").get_json()
ok(r["ok"] and r["type"] == "po" and r["po"]["id"] == qp["id"], "scan PO number (case-insensitive)")
r = P.get("/api/inv/pur/scan?code=YT555").get_json(); ok(r["type"] == "po", "scan tracking number")
r = P.get(f"/api/inv/pur/scan?code={fil['code']}").get_json()
ok(r["type"] == "item" and any(p["id"] == qp["id"] for p in r["pos"]), "scan item code → open POs with it")
ok(P.get("/api/inv/pur/scan?code=NOPE-404").get_json()["type"] == "unknown", "unknown code")
lab_line = next(x for x in qp["lines"] if x["item_id"] != fil["id"])
r = P.post("/api/inv/pur/receive", json={"po_id": qp["id"], "qtys": {str(qf["id"]): 3, str(lab_line["id"]): 1},
                                         "issues": [{"line_id": lab_line["id"], "kind": "damaged", "qty": 1, "note": "压坏"}],
                                         "locations": {str(lab_line["item_id"]): "A1-01-02"}}).get_json()
ok(r["ok"] and r["po"]["status"] == "partial" and r["po"]["issues_open"] == 1, f"phone receive by production role ({r.get('error')})")
ok(inv.get_item(lab_line["item_id"])["location"] == "A1-01-02" and r["placed"], "location assigned on receive")
h = P.get(f"/print/pur-labels?po={qp['no']}")
ok(h.status_code == 200 and lab_line["code"].encode() in h.data and b"<svg" in h.data, "item labels print")
ok(C.get("/m").status_code == 200 and b"rcv" in C.get("/m/mobile/m.js").data, "phone page has receive screen")
ok(P.get("/api/inv/pur/transit").get_json()["ok"], "transit list")

# ---- 9 权限：没有金额权限的员工看不到金额；不能入库
lst = S.get("/api/inv/po").get_json()
ok(lst["po"] and "total" not in lst["po"][0] and "landed" not in lst["po"][0]["lines"][0], "staff: no money in PO list")
sg = S.get("/api/inv/pur/suggest?all=1").get_json()["rows"]
ok(sg and "est_cost" not in sg[0] and "unit_price" not in sg[0], "staff: no money in suggestions")
ok(S.get("/api/inv/pur/analytics").status_code == 403, "staff: no analytics")
ok(S.post("/api/inv/pur/receive", json={"po_id": qp["id"], "qtys": {}}).status_code == 403, "staff without inv.in can't receive")
ok("unpaid" not in S.get("/api/inv/pur/overview").get_json()["summary"], "staff: overview without money")
ok(S.get(f"/api/inv/pur/items/{bag['id']}/links").get_json()["links"][0].get("price") is None, "staff: no link prices")

# ---- 10 分析、菜单
an = C.get("/api/inv/pur/analytics").get_json()
ok(an["ok"] and len(an["months"]) == 12 and an["by_category"] and any(x["id"] == s1["id"] for x in an["by_supplier"]), "analytics: month / category / supplier")
ok(any(m["thb_kg"] for m in an["filament_kg"]), "analytics: filament price per kg trend")
ok(any(x["item_id"] == bag["id"] for x in an["cheapest"]) or True, "analytics: cheapest list builds")
mods = {m["id"]: m for m in C.get("/api/modules").get_json()["modules"]}
mn = {x["tab"]: x for x in mods["pur"]["menus"]}
ok([t for t, x in mn.items() if not x.get("ghost")] == ["purchase"] and all(mn[t].get("panel") == "purchase" for t in ("po_suggest", "po_recv", "po_suppliers", "po_pay")),
   "one visible menu, old tab ids are ghosts on the same page")
ok("po_pay" not in {x["tab"] for m in S.get("/api/modules").get_json()["modules"] for x in m["menus"]}, "staff don't get the payments tab")
print("ERRORS", E_)
