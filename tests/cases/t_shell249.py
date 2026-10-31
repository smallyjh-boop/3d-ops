# v2.49：外壳——顶部大菜单（新增「运营」）、菜单页签（ghost + parent）、🔔 待办数字（缓存）、全局搜索（按角色）、工作台按角色的数
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, time
D = T + "/v249"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, todo, orders as orders_mod, search
db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "secret123", "listing", "Nok")
db.create_user("lek", "secret123", "production", "Lek")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
CL = A.app.test_client(); CL.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
CP = A.app.test_client(); CP.post("/api/auth/login", json={"username": "lek", "password": "secret123"})
now = time.time()
pid = store.list_products()[0]["id"]
p = store.load(pid)
sku = next(v["sku"] for v in p["variants"] if v.get("sku"))
orders_mod.upsert([
    {"platform": "lazada", "order_no": "LZ7788001", "status": "to_ship", "order_time": now - 3600, "ship_by": now - 600, "order_total": 300,
     "buyer": "Somchai Jaidee", "tracking_no": "TH9988776655", "items": [{"sku": sku, "qty": 1, "unit_price": 300, "item_total": 300}]},
    {"platform": "shopee", "order_no": "SP5566002", "status": "completed", "order_time": now - 86400, "order_total": 200,
     "buyer": "Nida", "items": [{"sku": sku, "qty": 1, "unit_price": 200, "item_total": 200}]},
], source="test")

# ---------- 菜单 ----------
html = C.get("/").get_data(as_text=True)
mods = [x.split('"')[0] for x in html.split('class="mod" data-mod="')[1:]]
ok(mods == ["home", "goods", "orders", "cs", "ops", "prod", "inv", "pur", "biz", "sys"], f"top menu order {mods}")
ok('id="bell-btn"' in html and 'id="gs-btn"' in html and "/static/shell.js" in html and "/static/shell.css" in html, "bell + search in the top bar")
ms = {m["id"]: m for m in C.get("/api/modules").get_json()["modules"]}
goods = [mn["tab"] for m in ms.values() for mn in m["menus"] if mn["mod"] == "goods" and not mn["ghost"]]
# v2.50：「选品」排在「产品库」前面（菜单 before = library）：商品 = 选品 · 产品库 · 上架
cur = next((mn for m in ms.values() for mn in m["menus"] if mn["tab"] == "curate"), {})
ok(sorted(goods) == ["curate", "export", "library"] and cur.get("before") == "library", f"商品 = 选品 · 产品库 · 上架 {goods} {cur.get('before')}")
on = next(mn for mn in ms["listing"]["menus"] if mn["tab"] == "online")
ok(on["ghost"] and on["parent"] == "export", "在线商品 = tab of 上架")
ok(not ms["link"]["menus"], "运营改动 menu removed from 对接")
allm = [mn for m in ms.values() for mn in m["menus"]]
ok(not any(mn["tab"] == "ops_todo" for mn in allm), "今日待办 page removed")
ok(all(mn["parent"] == mn["panel"] for mn in allm if mn["ghost"] and mn["mod"] == "ops"), "ops tabs highlight their page")
for f in ("shell.js", "shell.css", "ux.js"):
    ok(C.get(f"/static/{f}").status_code == 200, f"static {f}")

# ---------- 🔔 待办数字 ----------
c1 = C.get("/api/todo/count").get_json()
ok(c1["ok"] and c1["n"] >= 1 and c1["bad"] >= 1 and c1["by_source"].get("orders"), f"bell count {c1}")
calls = []
orig = todo.collect
todo.collect = lambda *a, **k: (calls.append(1), orig(*a, **k))[1]
C.get("/api/todo/count"); C.get("/api/todo/count")
ok(not calls, "bell count cached (no recount within 45 s)")
key = next(i["key"] for i in C.get("/api/todo").get_json()["items"] if i["key"].startswith("ship:"))
C.post("/api/todo/state", json={"key": key, "state": "done"})
c2 = C.get("/api/todo/count").get_json()
ok(calls and c2["n"] == c1["n"] - 1, "done → cache cleared, count drops")
todo.collect = orig
C.post("/api/todo/state", json={"key": key, "state": ""})
ok(CP.get("/api/todo/count").get_json()["ok"] and "sources" in C.get("/api/todo").get_json(), "production count + sources in list")

# ---------- 全局搜索 ----------
r = C.get("/api/search?q=LZ7788").get_json()
og = next((g for g in r["groups"] if g["type"] == "order"), None)
ok(og and og["items"][0]["order_no"] == "LZ7788001" and og["zh"] == "订单" and og["th"], "order number")
r = C.get("/api/search?q=TH9988776655").get_json()
ok(r["groups"][0]["type"] == "order" and r["groups"][0]["items"][0]["exact"] and r["groups"][0]["items"][0]["hit"] == "tracking", "tracking number (scan) → first")
r = C.get("/api/search?q=somchai").get_json()
ok(any(i["order_no"] == "LZ7788001" for g in r["groups"] if g["type"] == "order" for i in g["items"]), "buyer name (case-insensitive)")
r = C.get("/api/search?q=" + sku.lower()).get_json()
pg = next((g for g in r["groups"] if g["type"] == "product"), None)
ok(pg and pg["items"][0]["id"] == pid and pg["items"][0]["sku"].upper() == sku.upper(), "SKU → product")
ok(any(g["type"] == "order" for g in r["groups"]), "SKU → orders with that SKU")
name = (p.get("name_zh") or "")[:3]
if name and len(name) >= 2:
    r = C.get("/api/search?q=" + name).get_json()
    ok(any(i["id"] == pid for g in r["groups"] if g["type"] == "product" for i in g["items"]), "product name")
ok(C.get("/api/search?q=a").status_code == 400, "too short")
ok(not any(k in str(C.get("/api/search?q=LZ7788").get_json()) for k in ("order_total", "profit", "revenue")), "no money in results")
# 客服会话：老板 / 上架客服有，生产没有
c = db.conn()
c.execute("INSERT INTO cs_conv(platform, buyer, order_no, status, summary, created_at, updated_at) VALUES('lazada','Khun Malee','LZ7788001','open','问有没有粉色',?,?)", (now, now))
c.commit()
ok(any(g["type"] == "conv" for g in CL.get("/api/search?q=malee").get_json()["groups"]), "listing staff: conversations")
ok(not any(g["type"] == "conv" for g in CP.get("/api/search?q=malee").get_json()["groups"]), "production: no conversations")
ok(any(g["type"] == "order" for g in CP.get("/api/search?q=LZ7788").get_json()["groups"]), "production: orders")
ok(search._products() is search._products(), "product index cached")

# ---------- 工作台按角色 ----------
d = C.get("/api/dashboard").get_json()
ok(len(d["trend"]) == 7 and d["trend"][-1]["day"] == time.strftime("%Y-%m-%d") and d["today_cal"]["orders"] >= 1, "owner: 7-day trend")
dl = CL.get("/api/dashboard").get_json()
ok("trend" not in dl and "today" not in dl and dl["to_list"] is not None and "sugg_pending" in dl, "listing: no money, to-list + suggestions")
print("ERRORS", E_)
