# 上架工作台自动分类（v2.53）：平台 + 店铺、进度（互斥）、待处理（被拒带原因 / 属性 / 图片 / 标题 / 低于成本 / 价格库存对不上 / 没库存，修好离开）、
# 这个店铺近 30 天的表现、铺货机会（别的店铺卖得好）+ 推送到指定店铺、手动标记（做完自动取消）、保存的视图、返回时记得选的分类。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import json, os, shutil, sqlite3, sys, time
D = T + "/m_wbgrp253"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)


import app as A
import modules.goods.api as GA
from core import categories, db, listing, store
from modules.listing import online

db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "pass123", "listing", "Nok")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
N = A.app.test_client(); N.post("/api/auth/login", json={"username": "nok", "password": "pass123"})
NOW = time.time()
ERRS = {"W8": ["类目属性还没填写（点「AI 匹配类目并填写属性」）"], "W9": ["泰文标题需要 5-255 个字符（现在 0）"]}
_chk = GA._check
GA._check = lambda cfg, p: (ERRS.get(p["id"], []), _chk(cfg, p)[1])
cat = categories.library()[0]
for it in store.list_products():
    store.delete(it["id"])


def mk(pid, **kw):
    p = store.blank_product(pid)
    p.update(name_zh="产品" + pid, copy={"title_th": "ที่วางโทรศัพท์ ทดสอบ", "description_th": "รายละเอียด " * 5}, category={"id": cat["id"]},
             images=[{"file": "a.jpg", "raw": "a.jpg"}], white_bg="w.jpg")
    p["variants"] = [{"opt1_zh": "黑", "grams": 20, "hours": 1, "sku": pid + "-K", "manual_price": kw.pop("price", None)}]
    p.update(kw)
    store.save(p)
    return p


online.init()
c = db.conn()
c.execute("INSERT INTO shops(platform, name, enabled) VALUES('lazada', '店铺A', 1)")
c.execute("INSERT INTO shops(platform, name, enabled) VALUES('lazada', '店铺B', 1)")
sa = c.execute("SELECT id FROM shops WHERE name='店铺A'").fetchone()[0]
sb = c.execute("SELECT id FROM shops WHERE name='店铺B'").fetchone()[0]


def on(pid, shop, status, days=40, qty=5, price=None, item=None, reason=""):
    c.execute("INSERT OR REPLACE INTO online_items(platform, shop_id, item_id, status, reason, product_id, skus, created, updated, synced_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
              ("lazada", shop, item or f"{pid}{shop}", status, reason, pid, json.dumps([{"seller_sku": pid + "-K", "price": price, "qty": qty}]), NOW - days * 86400, NOW, NOW))
    c.commit()


def sell(pid, shop, qty):
    oid = c.execute("INSERT INTO orders(platform, shop, order_no, status, order_time) VALUES('lazada', ?, ?, 'to_ship', ?)", (shop, f"O{pid}{shop}{qty}", NOW - 86400)).lastrowid
    c.execute("INSERT INTO order_items(order_id, sku, product_id, qty) VALUES(?,?,?,?)", (oid, pid + "-K", pid, qty))
    c.commit()


def sysprice(pid):
    from core import pricing
    from core.config import load_config
    return pricing.price_product(load_config(), store.load(pid))[0]["final_price"]


for i in range(1, 10):
    mk(f"W{i}")
mk("W9", copy={}, category={})
mk("W10", copy={"title_th": "ก" * 130, "description_th": "รายละเอียด " * 5}, white_bg=None)
mk("W11", price=1)                                    # 售价低于成本
on("W1", sa, "live", 40, qty=5, price=sysprice("W1")); sell("W1", "店铺A", 12)
on("W2", sa, "live", 50, qty=0, price=sysprice("W2") + 50)
on("W3", sa, "uploaded", 1)
on("W4", sa, "rejected", 10, reason="Image has watermark")
on("W5", sa, "inactive", 10)
p = store.load("W6"); listing._set(p, "lazada", "pending"); store.save(p)
on("W7", sb, "live", 3, qty=9, price=sysprice("W7")); sell("W7", "店铺B", 4)         # 店铺B 在售、新品；店铺A 还没上
on("W11", sa, "live", 5, qty=3, price=sysprice("W11"))


def fixqty(pid, shop):
    it = next(i for i in GA.cached_rows() if i["id"] == pid)
    q = (it.get("sku_stock") or {}).get(pid + "-K")
    c.execute("UPDATE online_items SET skus=? WHERE product_id=? AND shop_id=?", (json.dumps([{"seller_sku": pid + "-K", "price": it["sku_price"][pid + "-K"], "qty": q}]), pid, shop)); c.commit()
    return q


for pid_, sh_ in (("W1", sa), ("W11", sa), ("W7", sb)):
    fixqty(pid_, sh_)


def wb(shop=0, plat="lazada"):
    return C.get(f"/api/listing/wb?platform={plat}&shop={shop}").get_json()


def keys(r, pid):
    return set(r["gk"][pid])


r = wb(sa)
ok(r["total"] == 11 and {s["name"] for s in r["shops"]} == {"店铺A", "店铺B"}, "payload: total + shops")
for pid, want in (("W1", "live"), ("W2", "live"), ("W3", "review"), ("W4", "rejected"), ("W5", "down"), ("W6", "pushing"), ("W7", "ready"), ("W8", "todo"), ("W9", "none")):
    pg = [k for k in keys(r, pid) if k.startswith("pg:")]
    ok(pg == ["pg:" + want], f"shop A progress {pid} -> {pg}")
ok(all(len([k for k in g if k.startswith("pg:")]) == 1 for g in r["gk"].values()), "progress exclusive")
rb = wb(sb)
ok("pg:live" in keys(rb, "W7") and "pg:ready" in keys(rb, "W1"), "shop B: W7 live there, W1 not listed there")
ok(r["n"]["pg:live"] == 3 and rb["n"]["pg:live"] == 1, f"counts follow the shop {r['n']['pg:live']}/{rb['n']['pg:live']}")
# 待处理
ok("td:rejected" in keys(r, "W4"), "rejected todo")
ok("td:noattr" in keys(r, "W8"), "attributes missing")
ok({"td:longtitle", "td:badimg"} <= keys(r, "W10"), "long title + non-compliant image")
ok("td:belowcost" in keys(r, "W11"), "price below cost")
ok({"td:mismatch", "td:nostock"} <= keys(r, "W2") and "td:mismatch" not in keys(r, "W1"), "platform price/stock differ + no stock")
ERRS.pop("W8")
p = store.load("W10"); p["copy"]["title_th"] = "สั้น ๆ พอ"; p["white_bg"] = "w.jpg"; store.save(p)
r2 = wb(sa)
ok("td:noattr" not in keys(r2, "W8") and not ({"td:longtitle", "td:badimg"} & keys(r2, "W10")) and "pg:ready" in keys(r2, "W8"), "fixed items leave automatically")
# 表现（按店铺）
ok("sl:hot" in keys(r, "W1") and "sl:hot" not in keys(rb, "W1"), "hot is per shop")
ok("sl:slow" in keys(r, "W2") and "sl:slow" not in keys(r, "W1"), "slow: online > 30d, 0 orders here")
ok("sl:new" in keys(rb, "W7") and "sl:new" in keys(r, "W11"), "new < 14d")
ok("sl:lowmargin" in keys(r, "W11"), "low margin shares the 产品库 threshold")
C.post("/api/goods/group-settings", json={"hot_min": 100, "hot_top": 0})
ok("sl:hot" not in keys(wb(sa), "W1"), "thresholds shared with 产品库")
# 铺货机会
ok("opp:1" in keys(r, "W7") and "opp:1" not in keys(rb, "W7") and "opp:1" not in keys(r, "W1"), "opportunity: sold in shop B, not listed in A")
ok(r["n"]["opp:1"] == 1, "opportunity count")
ok(C.post("/api/listing/lazada/push", json={"product_ids": ["W7"], "shop_id": 99999}).status_code in (400, 200)
   and "error" in json.dumps(C.post("/api/listing/lazada/push", json={"product_ids": ["W7"], "shop_id": 99999}).get_json()), "push accepts shop_id (unknown / not enabled shop is refused)")
# 手动标记
C.post("/api/goods/marks", json={"ids": ["W8", "W9"], "mark": "list", "on": True, "note": "下周上", "scope": "wb"})
r = wb(sa)
ok(r["marks"]["W8"]["list"]["note"] == "下周上" and "mk:list" in keys(r, "W9"), "mark 要上架 with note")
p = store.load("W8"); listing._set(p, "lazada", "uploaded"); store.save(p)
ok("mk:list" not in keys(wb(sa), "W8") and "mk:list" in keys(wb(sa), "W9") and "list" not in (store.load("W8").get("marks") or {}), "要上架 auto-clears when listed")
C.post("/api/goods/marks", json={"ids": ["W1"], "mark": "price", "on": True, "scope": "wb"})
C.post("/api/goods/marks", json={"ids": ["W1"], "mark": "img", "on": True, "scope": "wb"})
ok({"mk:price", "mk:img"} <= keys(wb(sa), "W1"), "要改价 / 要改图 marked")
p = store.load("W1"); p["variants"][0]["manual_price"] = 777; p["images"].append({"file": "b.jpg", "raw": "b.jpg"}); store.save(p)
k1 = keys(wb(sa), "W1")
ok("mk:price" not in k1 and "mk:img" not in k1, "改价 / 改图 auto-clear when price / images change")
ok(C.post("/api/goods/marks", json={"ids": ["W1"], "mark": "bogus", "on": True, "scope": "wb"}).status_code == 400, "unknown mark refused")
# 视图
vs = C.post("/api/goods/views", json={"scope": "wb", "name": "A店可推送", "state": {"plat": "lazada", "shop": sa, "sel": {"pg": "pg:ready"}, "q": ""}}).get_json()["views"]
ok(len(vs) == 1 and wb(sa)["views"][0]["state"]["shop"] == sa, "view saved with platform + shop")
ok(N.get("/api/listing/wb?platform=shopee&shop=0").status_code == 200, "staff can open the workbench groups; shopee platform ok")
# 前端：返回时记得
js = open(os.path.join(APP, "modules/listing/ui/export.js"), encoding="utf-8").read()
keep = js.split('NAV.keep("export"')[1]
ok("sel: { ...LW.sel }" in keep and "shop: LW.shop" in keep and "page: LW.page" in keep, "back-navigation keeps class + shop + page")
ok("GRP.html" in js and "stk" not in js.split("function renderGroupsLW")[1].split("function renderExpList")[0], "workbench panel uses GRP; stock-sync tab untouched")
print("DONE errors=%d" % E_)
sys.exit(1 if E_ else 0)
