# v2.46：运营分析模块——看板（和财务同一口径）、商品生命周期、今日待办（内核登记处 + 角色过滤 + 完成 / 忽略）、
# 手机提醒（按 key 去重、LINE、按来源关）、Lazada 财务流水（进财务对账、真实扣点）、评价（差评待办、回复）、退货退款、店铺表现、
# 没有接口权限时的提示。Lazada 接口全部是假的（LazadaConnector._call）。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, time, datetime as dt
D = T + "/m_ops246"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, integrations, listing, todo, orders as orders_mod, modules
from core.config import save_config, load_config
from core.connectors import lazada as LZ
db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "secret123", "listing", "Nok")
db.create_user("lek", "secret123", "production", "Lek")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
CL = A.app.test_client(); CL.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
CP = A.app.test_client(); CP.post("/api/auth/login", json={"username": "lek", "password": "secret123"})
ok(modules.enabled("ops"), "module on by default")
sch = next((m for m in C.get("/api/settings/schema").get_json()["modules"] if m["id"] == "ops"), None)
ok(sch and any(f["key"] == "oa_line_token" and f["type"] == "password" for g in sch["groups"] for f in g["fields"]), "settings category 运营分析")

now = time.time()
day0 = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
# ---------- 订单 ----------
orders_mod.upsert([
    {"platform": "lazada", "order_no": "LZ1001", "status": "completed", "order_time": now - 3600, "order_total": 500,
     "items": [{"sku": "3DP0015-WH", "qty": 2, "unit_price": 250, "item_total": 500}]},
    {"platform": "lazada", "order_no": "LZ1002", "status": "shipped", "order_time": now - 2 * 86400, "order_total": 20,
     "items": [{"sku": "3DP0001-WH", "qty": 1, "unit_price": 20, "item_total": 20}]},                     # 亏本
    {"platform": "shopee", "order_no": "SP2001", "status": "delivery_failed", "order_time": now - 5 * 86400, "order_total": 300,
     "payment": "COD", "items": [{"sku": "3DP0003-WH", "qty": 1, "unit_price": 300, "item_total": 300}]},
    {"platform": "lazada", "order_no": "LZ1003", "status": "to_ship", "order_time": now - 3 * 86400, "ship_by": now - 7200, "order_total": 250,
     "items": [{"sku": "3DP0015-PK", "qty": 1, "unit_price": 250, "item_total": 250}]},                    # 超时未发货
    {"platform": "lazada", "order_no": "LZ0999", "status": "completed", "order_time": now - 40 * 86400, "order_total": 250,
     "items": [{"sku": "3DP0017-WH", "qty": 1, "unit_price": 250, "item_total": 250}]},
], source="test")

# ---------- 看板：和财务同一个口径 ----------
r = C.get("/api/oa/dashboard").get_json()
ok(r["ok"] and r["summary"]["today"]["n"] >= 1, f"dashboard today {r['summary']['today']}")
from modules.fin import logic as fin
s30, e30 = dt.date.today() - dt.timedelta(days=29), dt.date.today() + dt.timedelta(days=1)
fb = fin.breakdown(s30, e30, "platform")["total"]
ok(abs(r["summary"]["d30"]["revenue"] - fb["revenue"]) < 0.01 and abs(r["summary"]["d30"]["profit"] - fb["profit"]) < 0.05,
   f"30-day revenue/profit same as finance {r['summary']['d30']} vs {fb}")
ok(r["breakdown_source"] == "fin" and any(p["key"] == "lazada" for p in r["platforms"]), "platform breakdown from finance module")
ok(any(s["key"] == "3DP0015-WH" for s in r["skus"]), "top skus")
ok([o["order_no"] for o in r["loss_orders"]][:1] == ["LZ1002"], f"loss orders {[o['order_no'] for o in r['loss_orders']]}")
ok("LZ1003" in [o["order_no"] for o in r["shipping"]["overdue"]] and r["shipping"]["overdue_n"] >= 1, "shipping overdue")
ok(r["cod"]["cod_failed"] == 1 and r["cod"]["cod_fail_rate"] == round(100 / r["cod"]["cod_orders"], 1), f"cod {r['cod']}")
ok(r["fin_net"] is not None and "net" in r["fin_net"], "finance net profit shown")
ok(r["health"]["orders_30d"] == r["summary"]["d30"]["n"] and "skus_missing_cost" in r["health"], "data health")
ok(len(r["daily"]) == 30 and r["daily"][-1]["day"] == dt.date.today().isoformat(), "30 days chart")
ok(CL.get("/api/oa/dashboard").status_code == 403, "dashboard owner only")
# 售价低于最低价
p = store.load("3DP0019"); p["variants"][0]["manual_price"] = 1; store.save(p)
r = C.get("/api/oa/dashboard").get_json()
ok(any(x["sku"] == "3DP0019-WH" and x["erp_low"] for x in r["pricing"]), "price below floor")

# ---------- 商品生命周期 ----------
p = store.load("3DP0015")
listing._set(p, "lazada", "live"); p["listing"]["lazada"]["first_listed_at"] = now - 20 * 86400; store.save(p)
p = store.load("3DP0013")
listing._set(p, "lazada", "live"); p["listing"]["lazada"]["first_listed_at"] = now - 70 * 86400; store.save(p)
p = store.load("3DP0005")
listing._set(p, "lazada", "rejected", note="图片有水印"); store.save(p)
p = store.load("3DP0007")
listing._set(p, "lazada", "live"); p["listing"]["lazada"]["first_listed_at"] = now - 20 * 86400; store.save(p)
lc = C.get("/api/oa/lifecycle").get_json()
row = lambda sku, plat="lazada": next((x for x in lc["rows"] if x["sku"] == sku and x["platform"] == plat), None)
ok(row("3DP0015-WH")["stage"] == "growing" and row("3DP0015-WH")["qty_30d"] == 2 and row("3DP0015-WH")["profit_30d"] != 0,
   f"sold → growing {row('3DP0015-WH')}")
ok(row("3DP0013-WH")["stage"] == "delist", f"70 days no sale → delist {row('3DP0013-WH')['stage']}")
ok(row("3DP0007-WH")["stage"] == "retest" and not row("3DP0007-WH")["start_estimated"], f"20 days no sale → retest {row('3DP0007-WH')['stage']}")
ok(row("3DP0005-WH")["stage"] == "rejected" and "图片有水印" in row("3DP0005-WH")["action"], "rejected with reason")
ok(row("3DP0002-WH")["stage"] == "unlisted", "never exported → unlisted")
ok(lc["rules"]["test_days"] == 14 and lc["counts"].get("delist"), "rules + counts")
save_config({"oa_hero_qty_30d": 2})
ok(C.get("/api/oa/lifecycle").get_json() and row("3DP0015-WH") and
   next(x for x in C.get("/api/oa/lifecycle").get_json()["rows"] if x["sku"] == "3DP0015-WH" and x["platform"] == "lazada")["stage"] == "hero",
   "hero rule from settings")
save_config({"oa_hero_qty_30d": 10})

# ---------- 今日待办 ----------
t = C.get("/api/todo").get_json()
keys = {i["key"]: i for i in t["items"]}
o3 = db.conn().execute("SELECT id FROM orders WHERE order_no='LZ1003'").fetchone()["id"]
o2 = db.conn().execute("SELECT id FROM orders WHERE order_no='LZ1002'").fetchone()["id"]
ok(f"ship:{o3}" in keys and keys[f"ship:{o3}"]["level"] == "bad" and keys[f"ship:{o3}"]["alert"], "core: overdue order to-do with alert")
ok(f"loss:{o2}" in keys and keys[f"loss:{o2}"]["source"] == "ops", "ops: loss order to-do")
ok("stage:3DP0005-WH:lazada:rejected" in keys and "stage:3DP0013-WH:lazada:delist" in keys, "ops: lifecycle to-dos")
ok(any(k.startswith("floor:3DP0019-WH") for k in keys), "ops: price below floor to-do")
ok(keys[f"ship:{o3}"]["title_th"] and t["groups"][0]["th"], "Thai text in items and groups")
ok(not t["errors"], f"no provider errors {t['errors']}")
tl = CL.get("/api/todo").get_json()
lk = {i["key"] for i in tl["items"]}
ok(f"ship:{o3}" in lk and f"loss:{o2}" not in lk and "stage:3DP0005-WH:lazada:rejected" in lk, "listing role: no profit items")
r = CP.get("/api/todo")
ok(r.status_code == 200 and f"loss:{o2}" not in {i["key"] for i in r.get_json()["items"]} and
   f"ship:{o3}" in {i["key"] for i in r.get_json()["items"]}, "production role can read its to-dos")
ok(C.post("/api/todo/state", json={"key": f"loss:{o2}", "state": "done"}).get_json()["ok"], "mark done")
t = C.get("/api/todo").get_json()
ok(f"loss:{o2}" not in {i["key"] for i in t["items"]} and t["hidden"] >= 1, "done item hidden")
ok(any(i["key"] == f"loss:{o2}" and i["state"] == "done" for i in C.get("/api/todo?all=1").get_json()["items"]), "all=1 shows done")
C.post("/api/todo/state", json={"key": f"loss:{o2}", "state": ""})
ok(f"loss:{o2}" in {i["key"] for i in C.get("/api/todo").get_json()["items"]}, "restore")
ok(C.post("/api/todo/state", json={"key": "x", "state": "bad"}).status_code == 400, "bad state refused")
# 客服模块交的待办
cc = db.conn()
cid = cc.execute("INSERT INTO cs_conv(buyer, platform, status, needs_human, human_reason, last_buyer_at, created_at, updated_at) "
                 "VALUES('Somchai','lazada','open',1,'投诉',?,?,?)", (now, now, now)).lastrowid
cc.commit()
it = next((i for i in CL.get("/api/todo").get_json()["items"] if i["key"].startswith(f"cshuman:{cid}:")), None)
ok(it and it["source"] == "cs" and it["tab"] == "cs" and it["title_th"], f"cs to-do for listing {it}")
ok(not any(i["key"].startswith("cshuman:") for i in CP.get("/api/todo").get_json()["items"]), "production does not see cs")
# 一个来源出错不影响别的
def boom(add):
    raise RuntimeError("坏了")
todo.register("ops", boom)
t = C.get("/api/todo").get_json()
ok(t["errors"] and t["errors"][0]["source"] == "ops" and f"ship:{o3}" in {i["key"] for i in t["items"]}, "provider error isolated")
todo._providers.remove(("ops", boom))
# 模块关掉：它的待办不出现
modules.set_enabled("ops", False)
ok(f"loss:{o2}" not in {i["key"] for i in C.get("/api/todo").get_json()["items"]} and C.get("/api/oa/dashboard").status_code == 404,
   "module off: no ops to-dos, api 404")
modules.set_enabled("ops", True)

# ---------- Lazada ----------
sid = integrations.save_shop({"platform": "lazada", "name": "ร้านหลัก", "enabled": True,
                              "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})
PROD = [{"item_id": "111", "status": "Active", "attributes": {"name": "ฟิกเกอร์แมว"}, "created_time": str(int((now - 50 * 86400) * 1000)),
         "updated_time": str(int(now * 1000)), "images": [], "skus": [{"SellerSku": "3DP0015-WH", "SkuId": 1, "price": 300, "special_price": 50,
                                                                      "quantity": 3, "Status": "active"}]},
        {"item_id": "222", "status": "Active", "attributes": {"name": "โคมไฟ"}, "created_time": str(int((now - 5 * 86400) * 1000)),
         "updated_time": str(int(now * 1000)), "images": [], "skus": [{"SellerSku": "3DP0009-WH", "SkuId": 2, "price": 300, "quantity": 3}]}]
TX = [{"order_no": "LZ1001", "transaction_date": dt.date.today().strftime("%d %b %Y"), "amount": "500.00", "transaction_type": "Item Price Credit",
       "fee_name": "Item Price Credit", "transaction_number": "T1", "orderItem_no": "9001", "statement": "S1", "WHT_amount": "0", "VAT_in_amount": "0"},
      {"order_no": "LZ1001", "transaction_date": dt.date.today().strftime("%d %b %Y"), "amount": "-40.00", "transaction_type": "Commission",
       "fee_name": "Commission", "transaction_number": "T2", "orderItem_no": "9001", "statement": "S1", "VAT_in_amount": "2.62", "WHT_amount": "0.4"},
      {"order_no": "LZ1001", "transaction_date": dt.date.today().strftime("%d %b %Y"), "amount": "-10.00", "transaction_type": "Payment Fee",
       "fee_name": "Payment Fee", "transaction_number": "T3", "orderItem_no": "9001", "statement": "S1"},
      {"order_no": "LZ1003", "transaction_date": dt.date.today().strftime("%d %b %Y"), "amount": "-12.00", "transaction_type": "Commission",
       "fee_name": "Commission", "transaction_number": "T4", "orderItem_no": "9003", "statement": "S1"}]       # 还没有商品金额：先不进财务
REVIEWS = {"111": [{"id": "5001", "create_time": str(int((now - 86400) * 1000)), "review_content": "สีไม่ตรงปก", "can_reply": "true",
                    "ratings": {"overall_rating": "2", "product_rating": "2", "seller_rating": "3", "logistics_rating": "4"},
                    "product_id": "111", "order_id": "LZ1001", "review_type": "PRODUCT_REVIEW", "seller_reply": ""},
                   {"id": "5002", "create_time": str(int((now - 2 * 86400) * 1000)), "review_content": "ดีมาก", "can_reply": "true",
                    "ratings": {"overall_rating": "5"}, "product_id": "111", "order_id": "LZ1001", "review_type": "PRODUCT_REVIEW"}],
           "222": []}
REVERSE = {"total": "1", "page_no": "1", "items": [{"reverse_order_id": "R1", "trade_order_id": "LZ1001", "request_type": "RETURN",
           "reverse_order_lines": [{"reverse_order_line_id": "RL1", "reverse_status": "REQUEST_INITIATE", "ofc_status": "", "reason_text": "Damaged",
                                    "refund_amount": "25000", "item_unit_price": "25000", "seller_sku_id": "3DP0015-WH", "is_need_refund": "true",
                                    "return_order_line_gmt_create": str(int((now - 3600) * 1000))}]}]}
PERF = {"main_category_name": "Toys", "indicators": [
    {"name": "Positive Seller Rating", "type": "POSITIVE_SELLER_RATING", "score": "92.0", "formatted_score": "92%", "formatted_target": "≥ 85%",
     "target_respected": "true"},
    {"name": "Ship on Time", "type": "SHIP_ON_TIME", "score": "80.0", "formatted_score": "80%", "formatted_target": "≥ 95%", "target_respected": "false"}]}
calls, DENY = [], set()


def fake(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    calls.append((path, dict(params), method))
    if path in DENY:
        raise RuntimeError(f"Lazada {path} 出错：InsufficientPermission The app does not have permission to call this api")
    if path == "/products/get":
        off = int(params["offset"])
        return {"code": "0", "data": {"total_products": str(len(PROD)), "products": PROD[off:off + 50]}}
    if path == "/finance/transaction/details/get":
        off = int(params["offset"])
        return {"code": "0", "data": TX[off:off + int(params["limit"])]}
    if path == "/review/seller/history/list":
        ids = [int(x["id"]) for x in REVIEWS.get(params["item_id"], [])
               if int(params["start_time"]) <= int(x["create_time"]) <= int(params["end_time"])]
        return {"code": "0", "success": "true", "data": {"current": params["current"], "total": str(len(ids)), "page_size": "10", "id_list": ids}}
    if path == "/review/seller/list/v2":
        want = {str(x) for x in json.loads(params["id_list"])}
        return {"code": "0", "success": "true",
                "data": {"review_list": [x for v in REVIEWS.values() for x in v if x["id"] in want]}}
    if path == "/review/seller/reply/add":
        return {"code": "0", "success": "true", "data": "true"}
    if path == "/reverse/getreverseordersforseller":
        return {"code": "0", "result": REVERSE}
    if path == "/seller/performance/get":
        return {"code": "0", "success": "true", "data": PERF}
    return {"code": "0", "data": {}}


LZ.LazadaConnector._call = fake
r = C.post("/api/oa/lazada/sync", json={"kinds": ["reviews"]}).get_json()["shops"][0]["kinds"]["reviews"]
ok("在线商品" in r["error"] and "立即同步" in r["hint"], f"no online items yet: tell to sync online products {r}")
ok(C.post("/api/online/sync", json={}).get_json()["shops"][0]["items"] == 2, "online items pulled (listing module)")
r = C.post("/api/oa/lazada/sync", json={}).get_json()
k = r["shops"][0]["kinds"]
ok(all("error" not in k[x] for x in ("finance", "reviews", "reverse", "performance")), f"sync all kinds {k}")
ok(k["finance"]["new"] == 4 and k["finance"]["fin"]["matched"] == 1, f"finance tx → fin {k['finance']}")
fc = next(c for c in calls if c[0] == "/finance/transaction/details/get")[1]
ok(str(fc["limit"]) == "500" and len(fc["start_time"]) == 10 and fc["end_time"] == dt.datetime.now(LZ.TZ).date().isoformat(), f"finance params {fc}")
hc = next(c for c in calls if c[0] == "/review/seller/history/list")[1]
ok(int(hc["end_time"]) - int(hc["start_time"]) <= 7 * 86400 * 1000 and str(hc["current"]) == "1", "review window ≤ 7 days")
ok(any(c[0] == "/review/seller/list/v2" and json.loads(c[1]["id_list"]) for c in calls), "review details by id list")
rc = next(c for c in calls if c[0] == "/reverse/getreverseordersforseller")[1]
ok("ReverseOrderLineModifiedTimeRangeStart" in rc and str(rc["page_no"]) == "1", f"reverse params {rc}")
ok(next(c for c in calls if c[0] == "/seller/performance/get")[1]["language"] == "en-US", "performance language")
o1 = db.conn().execute("SELECT settlement FROM orders WHERE order_no='LZ1001'").fetchone()
ok(abs((o1["settlement"] or 0) - 450) < 0.01, f"settlement written to order {o1['settlement']}")
o3s = db.conn().execute("SELECT settlement FROM orders WHERE order_no='LZ1003'").fetchone()["settlement"]
ok(o3s is None, "order without item price line not sent to finance yet")
ok(any(b["filename"].startswith("Lazada 接口") for b in fin.settle_batches()), "finance batch from API")
r2 = C.post("/api/oa/lazada/sync", json={"kinds": ["finance"]}).get_json()
ok(r2["shops"][0]["kinds"]["finance"]["new"] == 0 and r2["shops"][0]["kinds"]["finance"]["fin"]["new_rows"] == 0, "second sync: no duplicates")
lz = C.get("/api/oa/lazada").get_json()
ok(lz["fees"]["item_amount"] == 500 and lz["fees"]["rate"] == round((40 + 10 + 12) / 500 * 100, 2), f"real fee rate {lz['fees']}")
rv = {x["review_id"]: x for x in lz["reviews"]}
ok(rv["5001"]["rating"] == 2 and rv["5001"]["item_name"] == "ฟิกเกอร์แมว" and rv["5002"]["rating"] == 5, "reviews stored with item name")
ok(lz["reverse"][0]["refund_amount"] == 250 and lz["reverse"][0]["open"], f"refund in satang → baht {lz['reverse'][0]['refund_amount']}")
ok(lz["summary"]["reverse"]["refund"] == 250 and lz["summary"]["reviews"]["bad_open"] == 1, "summary")
pf = lz["performance"][0]["metrics"]
ok(len(pf) == 2 and pf[1]["ok"] is False and pf[1]["value"] == "80%", f"performance indicators {pf}")
ok(all(s["last_ok"] and not s["error"] for s in lz["status"]), "status ok")
ok(C.get("/api/oa/dashboard").get_json()["lazada"]["reviews"]["n"] == 2, "dashboard lazada summary")
keys = {i["key"]: i for i in C.get("/api/todo").get_json()["items"]}
ok(f"review:{sid}:5001" in keys and f"review:{sid}:5002" not in keys, "bad review to-do (only ≤ 3 stars)")
ok(f"reverse:{sid}:RL1:REQUEST_INITIATE" in keys, "reverse request to-do")
ok(any(k.startswith(f"perf:{sid}:SHIP_ON_TIME") for k in keys), "performance not met to-do")
ok(f"review:{sid}:5001" in {i["key"] for i in CL.get("/api/todo").get_json()["items"]}, "listing sees bad reviews")
# 回复评价
ok(CL.post("/api/oa/reviews/reply", json={"shop_id": sid, "review_id": "5001", "content": ""}).status_code == 400, "empty reply refused")
r = CL.post("/api/oa/reviews/reply", json={"shop_id": sid, "review_id": "5001", "content": "ขอโทษค่ะ จะส่งชิ้นใหม่ให้นะคะ"})
ok(r.status_code == 200 and calls[-1][0] == "/review/seller/reply/add" and str(calls[-1][1]["id"]) == "5001", "reply sent to Lazada")
ok(f"review:{sid}:5001" not in {i["key"] for i in C.get("/api/todo").get_json()["items"]}, "replied → to-do gone")
ok(CL.post("/api/oa/reviews/reply", json={"shop_id": sid, "review_id": "5001", "content": "x"}).status_code == 400, "no double reply")
REVIEWS["111"][0]["seller_reply"] = "ขอโทษค่ะ"
C.post("/api/oa/lazada/sync", json={"kinds": ["reviews"]})
ok(next(x for x in C.get("/api/oa/lazada").get_json()["reviews"] if x["review_id"] == "5001")["reply_by"] == "nok", "resync keeps who replied")
ok(CL.post("/api/oa/lazada/sync", json={}).status_code == 403, "sync owner only")
# 没有接口权限
DENY.add("/finance/transaction/details/get")
r = C.post("/api/oa/lazada/sync", json={}).get_json()
k = r["shops"][0]["kinds"]
ok("error" in k["finance"] and "App Console" in k["finance"]["hint"] and "error" not in k["reviews"], f"permission error isolated {k['finance']}")
st = next(s for s in C.get("/api/oa/lazada").get_json()["status"] if s["kind"] == "finance")
ok(st["error"] and "Finance API" in st["hint"] and "App Console" in st["hint_th"] and st["last_ok"], "status keeps last ok + hint (zh + th)")
keys = {i["key"]: i for i in C.get("/api/todo").get_json()["items"]}
ok(any(k_.startswith(f"lzerr:{sid}:finance:") for k_ in keys), "permission error to-do")
DENY.clear()

# ---------- 手机提醒 ----------
sent = []
from modules.ops import line as L_


class _R:
    status_code = 200
    text = "{}"


def fake_post(url, **kw):
    sent.append((url, kw))
    return _R()


L_.requests.post = fake_post
r = C.post("/api/oa/alerts/test")
ok(r.status_code == 400 and "推送渠道" in r.get_json()["error"], "test without channel: clear error")
save_config({"oa_alert_on": True, "oa_line_token": "tok", "oa_line_to": "Uabc"})
ok(C.post("/api/oa/alerts/test").status_code == 200 and sent[-1][1]["json"]["to"] == "Uabc", "test LINE")
sent.clear()
r = C.post("/api/oa/alerts/run").get_json()
ok(r["collected"] >= 3 and r["sent"] == r["collected"] and len(sent) == 1, f"alerts sent as one message {r}")
txt = sent[0][1]["json"]["messages"][0]["text"]
ok(txt.startswith("【3D 运营管理系统】") and "超时未发货" in txt and "亏本订单" in txt and "店铺表现没达标" in txt, "message has overdue order, loss order, performance")
ok(sent[0][1]["headers"]["Authorization"] == "Bearer tok", "LINE bearer token")
sent.clear()
r = C.post("/api/oa/alerts/run").get_json()
ok(r["collected"] == 0 and not sent, "same things not pushed twice")
a = C.get("/api/oa/alerts").get_json()
ok(a["recent"] and a["on"] and a["channels"] == ["line"] and any(s["id"] == "ops" for s in a["sources"]), "alerts page data")
C.post("/api/oa/alerts/muted", json={"source": "orders", "muted": True})
orders_mod.upsert([{"platform": "lazada", "order_no": "LZ1004", "status": "to_ship", "order_time": now - 86400, "ship_by": now - 600, "order_total": 500,
                    "items": [{"sku": "3DP0015-WH", "qty": 1, "unit_price": 500, "item_total": 500}]}], source="test")
r = C.post("/api/oa/alerts/run").get_json()
ok(r["collected"] == 0, f"muted source not pushed {r} {[x['key'] for x in C.get('/api/oa/alerts').get_json()['recent'][:3]]}")
ok("orders" in C.get("/api/oa/alerts").get_json()["muted"], "muted saved")
ok(load_config().get("oa_line_token") == "tok" and C.get("/api/config").get_json()["config"].get("oa_line_token") == "******",
   "LINE token is a secret")
# 失败：下一轮再试
C.post("/api/oa/alerts/muted", json={"source": "orders", "muted": False})
class _Bad:
    status_code = 401
    text = "bad token"
L_.requests.post = lambda url, **kw: _Bad()
r = C.post("/api/oa/alerts/run").get_json()
ok(r["collected"] == 1 and r["sent"] == 0, "send failed")
ok(any(x["send_error"] and "401" in x["send_error"] for x in C.get("/api/oa/alerts").get_json()["recent"]), "send error recorded")
L_.requests.post = fake_post
sent.clear()
r = C.post("/api/oa/alerts/run").get_json()
ok(r["sent"] == 1 and len(sent) == 1, "retried next round")

# ---------- 页面文件、菜单 ----------
mods = {m["id"]: m for m in C.get("/api/modules").get_json()["modules"]}
ok([m["tab"] for m in mods["ops"]["menus"]] == ["ops_todo", "ops_dash", "ops_life", "ops_lazada", "ops_plans", "ops_cal", "ops_traffic",
                                                  "ops_comp", "ops_radar", "ops_shops"], "menus")
ml = {m["id"]: m for m in CL.get("/api/modules").get_json()["modules"]}
ok([m["tab"] for m in ml["ops"]["menus"]] == ["ops_todo", "ops_lazada", "ops_plans", "ops_cal"], "listing menus")
for f in ("page.html", "ops.js", "page.js", "page.css"):
    ok(C.get(f"/m/ops/{f}").status_code == 200, f"ui {f}")
html = C.get("/m/ops/page.html").get_data(as_text=True)
ok(all(f'id="tab-{t_}"' in html for t_ in ("ops_todo", "ops_dash", "ops_life", "ops_lazada")), "page sections")
th = json.load(open(os.path.join(APP, "modules", "ops", "i18n", "th.json"), encoding="utf-8"))
ok(len(th) > 20, "Thai dictionary")
print("ERRORS", E_)
