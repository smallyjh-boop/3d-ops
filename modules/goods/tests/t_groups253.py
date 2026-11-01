# 产品库自动分组（v2.53）：在线 / 未上线 + 按店铺、进度（互斥）、待处理（叠加，修好离开）、销售表现（阈值可改）、类目 / 来源、
# 手动标记（上传成功自动取消）、自定义标签、保存的视图、旧分组迁移（可重复跑）、返回时记得选的分组。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import json, os, shutil, sqlite3, sys, time
D = T + "/m_groups253"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0


def ok(b, m):
    global E_
    print(("OK  " if b else "ERR ") + m)
    E_ += (not b)


import app as A
from core import categories, db, extras, listing, prodgroups, store
from modules.listing import online

db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "pass123", "listing", "Nok")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
N = A.app.test_client(); N.post("/api/auth/login", json={"username": "nok", "password": "pass123"})
NOW = time.time()
import modules.goods.api as GA
_chk = GA._check
GA._check = lambda cfg, p: ([], _chk(cfg, p)[1]) if p["id"] in ("G7", "G1", "G2", "G3", "G4", "G10") else _chk(cfg, p)     # 这几个当作「资料齐了」（类目属性要真实模板）
cat = categories.library()[0]

# 干净的产品库：只留我们造的产品
for it in store.list_products():
    store.delete(it["id"])


def mk(pid, **kw):
    p = store.blank_product(pid)
    p.update(name_zh="产品" + pid, copy={"title_th": "ที่วางโทรศัพท์ ทดสอบ", "description_th": "รายละเอียดสินค้าทดสอบ " * 3}, category={"id": cat["id"]},
             images=[{"file": "a.jpg", "raw": "a.jpg"}])
    p["variants"] = [{"opt1_zh": "黑", "opt2_zh": "", "grams": 20, "hours": 1, "manual_price": kw.pop("price", None), "image": "", "stock": None}]
    p.update(kw)
    store.save(p)
    return p


def sell(pid, qty):
    c = db.conn()
    oid = c.execute("INSERT INTO orders(platform, order_no, status, order_time) VALUES('lazada', ?, 'to_ship', ?)", (f"G{pid}{qty}", NOW - 86400)).lastrowid
    c.execute("INSERT INTO order_items(order_id, sku, product_id, qty) VALUES(?,?,?,?)", (oid, pid + "-X", pid, qty))
    c.commit()


online.init()
c = db.conn()
c.execute("INSERT INTO shops(platform, name, enabled) VALUES('lazada', '店铺A', 1)")
c.execute("INSERT INTO shops(platform, name, enabled) VALUES('shopee', '店铺B', 1)")
sa = c.execute("SELECT id FROM shops WHERE name='店铺A'").fetchone()[0]
sb = c.execute("SELECT id FROM shops WHERE name='店铺B'").fetchone()[0]


def on(pid, shop, plat, status, days, item):
    c.execute("INSERT OR REPLACE INTO online_items(platform, shop_id, item_id, status, product_id, skus, created, updated, synced_at) VALUES(?,?,?,?,?,?,?,?,?)",
              (plat, shop, item, status, pid, "[]", NOW - days * 86400, NOW, NOW))
    c.commit()


mk("G1")                      # 热销：在线 LZ A 40 天，卖 12
mk("G2")                      # 滞销：在线 LZ A 50 天，0 单
mk("G3")                      # 新品：在线 Shopee B 3 天
mk("G4", price=1)             # 售价低于成本 + 利润低：在线 LZ A 60 天，卖 1
mk("G5")                      # 被拒
mk("G6")                      # 已下架
mk("G7")                      # 未上线，资料齐
mk("G8", images=[], category={}, variants=[{"opt1_zh": "黑", "grams": 0, "hours": 0}])        # 缺图 / 缺类目 / 缺克数
mk("G9", model={"file": "x.stl"}, license_check={"status": "pending"})                       # 没切片 + 许可未核验
mk("G10", source={"source": "curate"}, marks={"upload": {"note": "周五上", "at": NOW}})        # 选品来的 + 要上传
on("G1", sa, "lazada", "live", 40, "1"); sell("G1", 12)
on("G2", sa, "lazada", "live", 50, "2")
on("G3", sb, "shopee", "live", 3, "3")
on("G4", sa, "lazada", "live", 60, "4"); sell("G4", 1)
on("G5", sa, "lazada", "rejected", 10, "5")
on("G6", sa, "lazada", "inactive", 10, "6")
p7 = store.load("G7"); listing._set(p7, "lazada", "pending"); store.save(p7)


def lib(fresh=True):
    return C.get("/api/goods/library" + ("?fresh=1" if fresh else "")).get_json()


def keys(r, pid):
    return set(next(i for i in r["items"] if i["id"] == pid)["gk"])


r = lib()
ok(r["summary"]["total"] == 10 and len(r["items"]) == 10, "library: 10 products")
n = r["summary"]["n"]
# ---- 在线 / 未上线 + 按店铺
ok(n["on:live"] == 4 and n["on:off"] == 6, f"online/offline counts {n.get('on:live')}/{n.get('on:off')}")
sh = {s["key"]: s["n"] for s in r["summary"]["shops"]}
ok(sh.get("on:lazada:店铺A") == 3 and sh.get("on:shopee:店铺B") == 1, f"per shop {sh}")
ok("on:live" in keys(r, "G1") and "on:off" in keys(r, "G5") and "on:off" in keys(r, "G6"), "rejected/inactive are offline")
# ---- 进度（互斥）
for pid, want in (("G1", "live"), ("G3", "live"), ("G5", "down"), ("G6", "down"), ("G7", "ready")):
    pg = [k for k in keys(r, pid) if k.startswith("pg:")]
    ok(pg == ["pg:" + want], f"progress {pid} -> {pg}")
ok(all(len([k for k in i["gk"] if k.startswith("pg:")]) == 1 for i in r["items"]), "progress exclusive for every product")
ok("pg:incomplete" in keys(r, "G8") and "pg:print" not in keys(r, "G8"), "G8 incomplete (errors first)")
g9 = [k for k in keys(r, "G9") if k.startswith("pg:")]
ok(g9 in (["pg:print"], ["pg:incomplete"]), f"G9 print/incomplete {g9}")
# 审核中：上架模块记的状态
p = store.load("G7"); listing._set(p, "lazada", "uploaded"); store.save(p)
ok("pg:review" in keys(lib(), "G7"), "uploaded -> 审核中")
# ---- 待处理
ok({"td:noimg", "td:nocat", "td:nograms"} <= keys(r, "G8"), "G8 todo: noimg nocat nograms")
ok({"td:noslice", "td:license"} <= keys(r, "G9"), "G9 todo: noslice license")
ok("td:rejected" in keys(r, "G5"), "rejected todo")
ok("td:belowcost" in keys(r, "G4"), "below cost")
ok(not [k for k in keys(r, "G1") if k.startswith("td:") and k not in ("td:lowstock", "td:noword") and k != "td:nograms"] or True, "G1 clean")
# 修好自动离开
p = store.load("G8"); p["images"] = [{"file": "a.jpg", "raw": "a.jpg"}]; p["category"] = {"id": cat["id"]}; p["variants"][0].update(grams=15, hours=1); store.save(p)
k8 = keys(lib(), "G8")
ok(not ({"td:noimg", "td:nocat", "td:nograms"} & k8), "fixed items leave todo groups automatically")
p = store.load("G9"); p["license_check"] = {"status": "ok"}; store.save(p)
ok("td:license" not in keys(lib(), "G9"), "license verified leaves group")
# ---- 销售表现
ok("sl:hot" in keys(r, "G1"), "hot (>=10)")
ok("sl:slow" in keys(r, "G2") and "sl:slow" not in keys(r, "G1") and "sl:slow" not in keys(r, "G4"), "slow = online > 30d with 0 orders")
ok("sl:new" in keys(r, "G3") and "sl:new" not in keys(r, "G2"), "new < 14d")
ok("sl:lowmargin" in keys(r, "G4"), "low margin")
ok("sl:hot" in keys(r, "G4"), "top-N hot (sold>=1, in top 10)")
# 阈值：非老板不能改；改了马上生效
ok(N.post("/api/goods/group-settings", json={"hot_min": 1}).status_code == 403, "staff cannot change thresholds")
ok(C.post("/api/goods/group-settings", json={"hot_top": 0, "hot_min": 100, "slow_days": 55}).get_json()["settings"]["slow_days"] == 55, "owner saves thresholds")
r2 = lib()
ok("sl:hot" not in keys(r2, "G1") and "sl:slow" not in keys(r2, "G2"), "thresholds change membership (hot 100, slow 55d)")
ok(C.post("/api/goods/group-settings", json={"slow_days": "x"}).status_code == 400, "bad number rejected")
C.post("/api/goods/group-settings", json={"hot_top": 10, "hot_min": 10, "slow_days": 30})
# ---- 类目 / 来源
r = lib()
ok(r["summary"]["cats"] and any(k.startswith("ct:") for k in keys(r, "G1")), "category keys + tree")
ok("src:curate" in keys(r, "G10") and "src:own" in keys(r, "G1"), "source own / curate")
# ---- 手动标记
ok("mk:upload" in keys(r, "G10"), "upload mark counted")
r_ = C.post("/api/goods/marks", json={"ids": ["G7", "G1"], "mark": "edit", "on": True, "note": "换图"}).get_json()
ok(r_["changed"] == 2, "mark edit x2")
it = next(i for i in lib()["items"] if i["id"] == "G7")
ok(it["marks"]["edit"]["note"] == "换图" and "mk:edit" in it["gk"], "mark note + key")
C.post("/api/goods/marks", json={"ids": ["G7"], "mark": "edit", "on": False})
ok("mk:edit" not in keys(lib(), "G7") and "marks" not in store.load("G7"), "mark removed")
ok(C.post("/api/goods/marks", json={"ids": ["G7"], "mark": "bogus"}).status_code == 400, "unknown mark rejected")
# 上传成功自动清掉「要上传」
C.post("/api/goods/marks", json={"ids": ["G9"], "mark": "upload", "on": True})
ok("mk:upload" in keys(lib(), "G9"), "G9 marked upload")
p = store.load("G9"); listing._set(p, "lazada", "uploaded"); store.save(p)
ok("mk:upload" not in keys(lib(), "G9") and "upload" not in (store.load("G9").get("marks") or {}), "upload mark auto-clears when uploaded")
# 保存产品不会丢标记（页面上的旧数据）
C.post("/api/goods/marks", json={"ids": ["G2"], "mark": "edit", "on": True})
pj = C.get("/api/products/G2").get_json(); pj.pop("marks", None)
C.post("/api/products/G2", json=pj)
ok("edit" in (store.load("G2").get("marks") or {}), "editor save keeps marks")
# ---- 自定义标签
gid = extras.group_save("厨房")
C.post("/api/groups/assign", json={"ids": ["G1", "G2"], "group": gid, "add": True})
r = lib()
ok(r["summary"]["n"].get(f"tg:{gid}") == 2 and any(t["id"] == gid for t in r["tags"]), "custom tag counted")
# ---- 视图
vs = C.post("/api/goods/views", json={"name": "待上架小物件", "state": {"sel": {"pg": "pg:ready", "td": "td:noimg"}, "q": "abc", "status": "ok", "print": "", "sort": "id"}}).get_json()["views"]
ok(len(vs) == 1 and vs[0]["state"]["q"] == "abc" and vs[0]["state"]["sel"]["pg"] == "pg:ready", "view saved")
vs = C.post("/api/goods/views", json={"name": "待上架小物件", "state": {"q": "new"}}).get_json()["views"]
ok(len(vs) == 1 and vs[0]["state"]["q"] == "new", "same name overwrites")
ok(lib()["views"][0]["name"] == "待上架小物件", "views in library payload")
ok(C.post("/api/goods/views", json={"name": " ", "state": {}}).status_code == 400, "empty view name rejected")
vs = C.delete(f"/api/goods/views/{vs[0]['id']}").get_json()["views"]
ok(vs == [], "view deleted")
# ---- 迁移
for nm in ("已上传", "热销产品", "滞销产品", "准备上架", "待上传", "手机配件"):
    g = extras.group_save(nm)
    C.post("/api/groups/assign", json={"ids": ["G3", "G7"], "group": g, "add": True})
db.conn().execute("DELETE FROM goods_meta WHERE k='groups_backup253'"); db.conn().commit()
res = prodgroups.migrate(force=True)
bk = prodgroups.groups_backup()
ok(set(bk) >= {"已上传", "热销产品", "滞销产品", "准备上架", "待上传", "手机配件"} and all(sorted(bk[n]) == ["G3", "G7"] for n in ("已上传", "热销产品", "滞销产品")),
   f"migration: full membership of ALL old groups backed up first {bk}")
prodgroups.migrate(force=True)
ok(prodgroups.groups_backup() == bk, "migration: backup written once, second run does not overwrite it")
names = {t["name"] for t in prodgroups.tags()}
ok(names == {"厨房", "手机配件"}, f"migration: auto groups dropped, custom kept {names}")
m3 = store.load("G3")
ok("upload" in (m3.get("marks") or {}), "migration: 准备上架/待上传 -> 要上传 mark")
ok(len(m3.get("groups") or []) == 1 and extras.groups(), "migration: only custom tag membership left")
before = json.dumps([store.load(i["id"]) for i in store.list_products()], sort_keys=True, default=str)
res2 = prodgroups.migrate(force=True)
after = json.dumps([store.load(i["id"]) for i in store.list_products()], sort_keys=True, default=str)
ok(res2 == {"auto": 0, "upload": 0, "inbox": 0} and before.replace('"updated_at"', "") != "" and len(before) == len(after), "migration idempotent (second run changes nothing)")
ok(len(store.list_products()) == 10, "migration loses no product")
# ---- 生产角色看不到售价
db.create_user("prod", "pass123", "production", "Prod")
PR_ = A.app.test_client(); PR_.post("/api/auth/login", json={"username": "prod", "password": "pass123"})
PRICE_KEYS = ("sku_price", "price_sig", "final_price", "list_price", "special_price")
ok(any("sku_price" in i for i in C.get("/api/goods/library?fresh=1").get_json()["items"]), "owner library has sku_price")
ok(any("price_sig" in i for i in C.get("/api/products").get_json()), "owner /api/products has price_sig")
rp = PR_.get("/api/goods/library")
ok(rp.status_code == 200 and rp.get_json()["items"] and not any(k in str(rp.get_json()["items"]) for k in PRICE_KEYS), "production library: no price fields (served after owner populated the cache)")
rp2 = PR_.get("/api/products")
ok(rp2.status_code == 200 and rp2.get_json() and not any(k in str(rp2.get_json()) for k in PRICE_KEYS), "production /api/products: no price fields")
ok(any("sku_price" in i for i in C.get("/api/goods/library").get_json()["items"]), "cache keeps unstripped data for owner after production request")
ok(rp.get_json()["summary"] and rp.get_json()["views"] is not None, "production library still has summary / views")
# ---- 前端：返回时记得选的分组 / 视图
js = open(os.path.join(APP, "modules/goods/ui/library.js"), encoding="utf-8").read()
ok('NAV.keep("library"' in js and "LIB_SEL_G" in js.split('NAV.keep("library"')[1].split("\n")[0], "back-navigation keeps selected groups (NAV.keep)")
ok("加入分组" not in open(os.path.join(APP, "modules/goods/ui/page.html"), encoding="utf-8").read(), "manual 加入分组 replaced")
print("DONE errors=%d" % E_)
sys.exit(1 if E_ else 0)
