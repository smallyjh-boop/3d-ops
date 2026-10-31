# v2.48：运营分析第二期——竞品（插件采集 / 粘贴 AI 识别、日销推算、单件利润用 ERP 成本和 Lazada 真实扣点、竞品动态）、
# 爆款雷达（关键词、搜索结果、机会分、侵权 = 0 分、从产品搜索词导入、巡逻清单和上限）、竞店（店铺页识别、ERP 我的店铺）、
# 计划（目标 = 对标 × 30% / 60%、实际订单、分阶段任务进今日待办、AI 更新）、营销日历（倒排任务、产能）、
# 店铺后台数据（AI 识别、对上 SKU、生命周期显示、关键词搜索量进雷达）、扩展接口的密钥权限。AI 全部是假的（ai_copy.call）。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, time, datetime as dt
D = T + "/m_ops248"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, integrations, todo, orders as orders_mod, modules, ai_copy, pricing
from core.config import save_config, load_config
db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "secret123", "listing", "Nok")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
CL = A.app.test_client(); CL.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
from modules.ops import comp, radar, shops, plans, campaigns, traffic, mkt_db, mkt_util
KEY = integrations.create_key("Nok")                       # 员工的扩展密钥（完整权限）
H = {"Authorization": "Bearer " + KEY, "X-Ext-Version": "3.0.0"}
NOW = time.time()

# ---------- 表 ----------
names = {r[0] for r in db.conn().execute("SELECT name FROM sqlite_master WHERE type='table'")}
need = {"ops_comp", "ops_comp_links", "ops_comp_snaps", "ops_comp_events", "ops_radar_keywords", "ops_radar_searches", "ops_radar_items",
        "ops_radar_item_snaps", "ops_radar_volumes", "ops_patrol_log", "ops_shops", "ops_shop_snaps", "ops_shop_items", "ops_shop_item_snaps",
        "ops_shop_comp_links", "ops_plans", "ops_plan_tasks", "ops_campaigns", "ops_backend_pages", "ops_backend_rows"}
ok(need <= names, f"ops_ tables {sorted(need - names)}")
ok("shops" in names, "ERP shops table untouched (ops_shops is separate)")

# ---------- 假 AI ----------
CALLS = []
AI = {"ip": False}
def fake_ai(cfg, system, user, image_b64=None):
    CALLS.append(system[:20])
    if "数据录入助手" in system and "商品页" in system:
        return json.dumps({"title": "ที่วางโทรศัพท์ Phone Stand", "shop": "ShopX", "price": 199, "list_price": 299, "voucher": 10,
                           "sold_text": "1.2k", "rating": 4.8, "reviews": "350", "free_ship": True, "variants": "ขาว ดำ", "size_text": "10x8 cm"})
    if "成本估算师" in system:
        return '```json\n{"grams": 40, "hours": 2, "material": "PLA", "size_guess": "10x8x6", "confidence": 0.7, "reason": "小件"}\n```'
    if "选品顾问" in system:
        return json.dumps({"printable": 0.9, "printable_reason": "简单", "grams": 30, "hours": 1.5, "material": "PLA", "ip_risk": AI["ip"],
                           "ip_reason": "Pokemon 角色" if AI["ip"] else "", "potential": 0.7, "potential_reason": "多颜色",
                           "design_idea": "加名字定制", "summary": "值得做"})
    if "卖家后台" in system:
        return json.dumps({"kind": "product_performance", "period_text": "最近7天", "period_days": 7,
                           "rows": [{"name": "Phone stand", "seller_sku": "3DP0015-WH", "visitors": 140, "views": 300, "add_to_cart": 12, "orders": 2, "units": 2},
                                    {"name": "Other", "seller_sku": "ZZZ-1", "visitors": 50, "orders": 0, "conversion": 0}],
                           "keywords": [{"keyword": "ที่วางโทรศัพท์", "search_volume": "12.5k", "bid": 3}]})
    if "资深运营" in system:
        return json.dumps({"summary": "曝光不够，先换主图", "tasks": [{"offset": 0, "phase": "起步", "text": "换第一张主图", "text_th": "เปลี่ยนรูปแรก"}],
                           "keywords_th": ["ที่วางโทรศัพท์"], "risks": ["别降到最低价以下"]})
    if "店铺页面" in system:
        return json.dumps({"name": "ShopX", "followers": "5k"})
    return "{}"
ai_copy.call = fake_ai
save_config({"ai_api_key": "test-key", "platform_fee_rate": 0.2,
             "printers": [{"name": "P1", "model": "P1S", "enabled": True}, {"name": "P2", "model": "P1S", "enabled": True}, {"name": "P3", "enabled": False}],
             "hours_per_day_each": 20})
cfg = load_config()

# ---------- ERP 数据：Lazada 真实扣点、订单 ----------
c = db.conn()
from modules.ops import lazada as LZ
LZ.init()
today_s = dt.date.today().isoformat()
c.executemany("INSERT INTO oa_lz_tx(shop_id, uid, order_no, day, fee_name, amount, is_item) VALUES(?,?,?,?,?,?,?)",
              [(1, "u1", "X1", today_s, "Item Price Credit", 2000, 1), (1, "u2", "X1", today_s, "Commission", -200, 0),
               (1, "u3", "X1", today_s, "Payment Fee", -100, 0)])
c.commit()
rate, src, _ = mkt_util.fee_rate("lazada", cfg)
ok(abs(rate - 0.15) < 1e-6 and "真实扣点" in src, f"Lazada fee = real rate from finance lines {rate} {src}")
ok(mkt_util.fee_rate("tiktok", cfg)[0] == 0.2, "other platform fee from settings")
cap = mkt_util.capacity(cfg)
ok(cap["printers"] == 2 and cap["hours_per_day"] == 40, f"capacity from prod printers {cap}")
uc = mkt_util.unit_cost(40, 2, False, cfg)
ok(uc == pricing.variant_cost(cfg, 40, 2)["total"], "unit cost = ERP pricing")

orders_mod.upsert([{"platform": "lazada", "order_no": f"P{i}", "status": "completed", "order_time": NOW - i * 86400 - 3600, "order_total": 250,
                    "items": [{"sku": "3DP0015-WH", "qty": 1, "unit_price": 250, "item_total": 250}]} for i in range(0, 6)], source="test")

# ---------- 竞品：粘贴文字 AI 识别、新建、两次记录算日销 ----------
r = C.post("/api/oa/comp/extract", json={"text": "หน้าสินค้า ... ขายแล้ว 1.2k", "url": "https://www.lazada.co.th/products/x-i111-s222.html"}).get_json()
ok(r["ok"] and r["how"] == "ai" and r["data"]["price"] == 199 and r["data"]["sold_text"] == "1.2k", f"AI extract {r}")
r = C.post("/api/oa/comp", json={"url": "https://www.lazada.co.th/products/x-i111-s222.html", "skus": "3dp0015-wh", "price": 260, "sold_text": "100", "reviews": 20}).get_json()
ok(r["ok"] and r["new"], "create competitor")
CID = r["id"]
ok(comp.links(CID) == ["3DP0015-WH"], "linked SKU uppercased")
# 第一条记录改成 3 天前，再记一次
c.execute("UPDATE ops_comp_snaps SET ts=? WHERE comp_id=?", (NOW - 3 * 86400, CID)); c.commit()
r = C.post(f"/api/oa/comp/{CID}/snap", json={"price": 230, "sold_text": "130", "reviews": 25}).get_json()
e = r["est"]
ok(abs(e["daily"] - 10) < 0.2 and e["confidence"] == "实测", f"daily from sold delta {e['daily']} {e['method']}")
ok(e["fee_rate"] == 0.15 and e["fee_unit"] == round(230 * 0.15, 2), f"fee uses Lazada real rate {e['fee_rate']}")
sk = mkt_util.sku_rows(cfg)["3DP0015-WH"]
ok(e["cost_key"] == "sku" and e["unit_cost"] == sk["unit_cost"], f"cost from linked ERP SKU {e['unit_cost']} {sk['unit_cost']}")
ok(e["profit_unit"] == round(230 - e["fee_unit"] - e["unit_cost"], 2), "unit profit = price - fee - cost")
ev = comp.events(1)
ok(any(x["kind"] == "price_drop" and x["comp_id"] == CID and x["text_th"] for x in ev), f"price drop event {ev}")
ok(C.post(f"/api/oa/comp/{CID}/snap", json={"title": "x"}).status_code == 400, "snap needs a number")

# ---------- 浏览器扩展：商品页采集（AI）、卡片、已采集、对比 ----------
ok(C.get("/api/v1/ops/ext/ping").status_code == 401, "ext needs key")
p = C.get("/api/v1/ops/ext/ping", headers=H).get_json()
ok(p["ok"] and p["ai"] and any(s["sku"] == "3DP0015-WH" for s in p["skus"]) and p["user"] == "Nok", "ext ping with staff key")
ok(integrations.EXT_SEEN.get("Nok") == "3.0.0", "extension version noted")
rk = integrations.create_key("ro", "read")
ok(C.get("/api/v1/ops/ext/ping", headers={"Authorization": "Bearer " + rk}).status_code == 403, "read-only key refused")
ok(C.get("/api/v1/ops/changes", headers=H).status_code == 403, "write-back api still needs ops scope")
ld = json.dumps({"@type": "Product", "name": "LD title", "image": "https://img.lazcdn.com/a.jpg", "offers": {"price": "199"}})
r = C.post("/api/v1/ops/ext/competitor", headers=H, json={"url": "https://www.lazada.co.th/products/stand-i999-s1.html?spm=x", "title": "t",
                                                          "text": "ราคา ฿199 ขายแล้ว 1.2k", "ld": [ld], "image": "",
                                                          "shop_url": "https://www.lazada.co.th/shop/shopx", "shop_name": "ShopX"}).get_json()
ok(r["ok"] and r["new"] and r["how"] == "ai" and r["est"]["price_eff"] == 189 and r["image"] == "https://img.lazcdn.com/a.jpg", f"ext capture {r.get('est', {}).get('price_eff')}")
C2 = r["id"]
ok(comp.get(C2)["est_grams"] == 40 and r["est"]["cost_key"] == "ai" and r["radar"], "new competitor gets AI cost estimate, goes to radar")
ok(r["est"]["unit_cost"] == mkt_util.unit_cost(40, 2, False), "AI grams/hours x ERP cost params")
sh = shops.by_key("lazada:shopx")
ok(sh and not sh["watch"] and r.get("shop_id") == sh["id"], "its shop remembered as candidate")
r = C.post("/api/v1/ops/ext/competitor", headers=H, json={"url": "https://www.lazada.co.th/products/stand-i999-s1.html", "text": "x"}).get_json()
ok(r["ok"] and not r["new"] and r["est"]["n_snaps"] == 1, "re-capture within 30 min replaces the snapshot")
r = C.post("/api/v1/ops/ext/card", headers=H, json={"url": "https://shopee.co.th/abc-i.11.22", "title": "card", "text": "฿89 ขายแล้ว 50"}).get_json()
ok(r["ok"] and r["how"] == "rules" and r["est"]["price_eff"] == 89, f"card capture by rules {r.get('how')}")
r = C.post("/api/v1/ops/ext/card", headers=H, json={"url": "https://shopee.co.th/search", "text": "฿1"}).get_json()
ok(not r["ok"], "card without item id refused")
r = C.post("/api/v1/ops/ext/known", headers=H, json={"urls": ["https://www.lazada.co.th/products/x-i111-s9.html", "https://www.lazada.co.th/products/n-i5.html"]}).get_json()
ok(list(r["known"].values()) == [CID], f"known {r}")
r = C.get(f"/api/v1/ops/ext/compare?ids={CID},{C2}", headers=H).get_json()
ok(len(r["rows"]) == 2, "compare columns")
r = C.post(f"/api/v1/ops/ext/competitor/{C2}", headers=H, json={"radar_status": "want"}).get_json()
ok(r["ok"] and comp.get(C2)["radar_status"] == "want", "mark want from extension")

# 页面数据
L = C.get("/api/oa/comp").get_json()
g = next(x for x in L["compare"] if x["sku"] == "3DP0015-WH")
ok(g["comp_count"] == 1 and abs(g["my_daily"] - 0.2) < 0.01 and g["comp_daily_top"] == 10, f"my sku vs competitor {g['my_daily']} {g['comp_daily_top']}")
ok(any(x["id"] == C2 for x in L["radar"]) and not any(x["id"] == CID for x in L["radar"]), "selection radar = unlinked")
ok(CL.get("/api/oa/comp").status_code == 403, "competitors owner only")
r = C.post(f"/api/oa/comp/{C2}/ai-cost").get_json()
ok(r["ok"] and r["grams"] == 40, "ai cost endpoint")

# ---------- 爆款雷达 ----------
r = C.post("/api/oa/radar/keywords", json={"platform": "lazada", "keywords": "ที่วางโทรศัพท์\nโมเดลโปเกมอน"}).get_json()
ok(r["added"] == 2, "add keywords")
cards = [{"url": f"https://www.lazada.co.th/products/p-i{100 + i}-s1.html", "title": f"Stand {i}", "text": f"฿{150 + i * 10} ขายแล้ว {1000 - i * 50}",
          "image": "https://img/x.jpg"} for i in range(12)]
r = C.post("/api/v1/ops/ext/search", headers=H, json={"url": "https://www.lazada.co.th/catalog/?q=%E0%B8%97%E0%B8%B5%E0%B9%88%E0%B8%A7%E0%B8%B2%E0%B8%87%E0%B9%82%E0%B8%97%E0%B8%A3%E0%B8%A8%E0%B8%B1%E0%B8%9E%E0%B8%97%E0%B9%8C",
                                                       "cards": cards, "total_text": "2,345 items found"}).get_json()
ok(r["ok"] and r["cards"] == 12 and r["total_results"] == 2345, f"search capture {r.get('cards')} {r.get('total_results')}")
o = r["opportunity"]
ok(0 < o["score"] <= 100 and o["ai"].get("summary") == "值得做" and o["unit_cost"] == mkt_util.unit_cost(30, 1.5), f"opportunity scored with AI {o['score']}")
ok(o["price_median"] and o["profit_unit"] == round(o["price_median"] * (1 - 0.15) - o["unit_cost"], 2), "radar profit uses real fee + ERP cost")
KID = r["keyword_id"]
AI["ip"] = True
r = C.post(f"/api/oa/radar/keywords/{KID}/ai").get_json()
o = radar.opportunity(cfg, radar.keyword(KID))
ok(o["score"] == 0 and o["ip_risk"] and "侵权" in o["notes"][0] and o["notes_th"], "IP risk → 0 points")
AI["ip"] = False
C.post(f"/api/oa/radar/keywords/{KID}/ai")
ok(radar.opportunity(cfg, radar.keyword(KID))["score"] > 0, "re-assess clears")
# 从产品搜索词导入
p = store.load("3DP0015"); p["keyword_plan"] = {"title_core": "ขาตั้งมือถือ", "core": ["ที่วางโทรศัพท์", "แท่นวางมือถือ"]}; store.save(p)
r = C.post("/api/oa/radar/import", json={"platform": "lazada"}).get_json()
ok(r["added"] == 2, f"import from product keyword plans {r}")
B = C.get("/api/oa/radar").get_json()
row = next(x for x in B["rows"] if x["keyword"] == "ที่วางโทรศัพท์")
ok("3DP0015" in row["products"], "products already using the keyword")
ok(any(x["source"] == "product" and x["product_id"] == "3DP0015" for x in B["rows"]), "imported keywords marked with product")
# 巡逻清单 / 上限 / 日志
save_config({"oa_patrol_daily_cap": 3})
pl = C.get("/api/v1/ops/ext/patrol", headers=H).get_json()
ok(pl["cap"] == 3 and pl["done"] == 1 and len(pl["items"]) == 2 and pl["total"] >= 3, f"patrol plan with cap {pl['cap']} {pl['done']} {len(pl['items'])}")
ok(any(i["kind"] == "product" for i in radar.patrol_plan(load_config())["items"]) or pl["total"] > len(pl["items"]), "patrol includes competitor pages")
C.post("/api/v1/ops/ext/patrol/log", headers=H, json={"kind": "search", "url": "u", "ok": False, "note": "遇到验证码，巡逻停止"})
C.post("/api/v1/ops/ext/patrol/log", headers=H, json={"kind": "product", "url": "u2", "ok": True})
pl = C.get("/api/v1/ops/ext/patrol", headers=H).get_json()
ok(pl["left"] == 0 and pl["items"] == [], "daily limit reached → nothing more today")
ok(radar.board(load_config())["log"][0]["who"] == "Nok", "patrol log keeps who")
save_config({"oa_patrol_daily_cap": 60})
r = C.post("/api/v1/ops/ext/search", headers=H, json={"url": "https://www.lazada.co.th/catalog/?q=abc", "cards": []}).get_json()
ok(not r["ok"] and "验证码" in r["error"], "empty search page (captcha) refused")

# ---------- 竞店 ----------
txt = "ShopX\n5.2พัน ผู้ติดตาม\n96% คะแนนร้านค้าเชิงบวก\nอัตราการตอบกลับแชท 88%\nสมัครสมาชิกเมื่อ 3 ปี ที่แล้ว"
sc = [{"url": f"https://www.lazada.co.th/products/s-i{500 + i}-s1.html", "title": f"Item {i}", "text": f"฿{100 + i} ขายแล้ว {200 + i}"} for i in range(5)]
r = C.post("/api/v1/ops/ext/shop", headers=H, json={"url": "https://www.lazada.co.th/shop/shopx?path=profile.htm", "text": txt, "cards": sc, "title": "ShopX | Lazada"}).get_json()
ok(r["ok"] and r["stats"] and r["items"] == 5 and r["metrics"]["followers"] == 5200 and r["metrics"]["positive_pct"] == 96 and r["metrics"]["response_rate"] == 88,
   f"shop page parsed {r.get('metrics', {}).get('followers')}")
SID = r["shop_id"]
ok(shops.get(SID)["watch"] == 1, "captured shop is watched")
c.execute("UPDATE ops_shop_item_snaps SET ts=? WHERE shop_id=?", (NOW - 2 * 86400, SID)); c.execute("UPDATE ops_shop_snaps SET ts=? WHERE shop_id=?", (NOW - 2 * 86400, SID)); c.commit()
sc2 = [{"url": x["url"], "title": x["title"], "text": f"฿{100 + i} ขายแล้ว {220 + i}"} for i, x in enumerate(sc)]
r = C.post("/api/v1/ops/ext/shop", headers=H, json={"url": "https://www.lazada.co.th/shop/shopx", "text": txt, "cards": sc2}).get_json()
ok(abs(r["metrics"]["daily"] - 50) < 0.5, f"shop daily floor {r['metrics']['daily']}")
r = C.post("/api/v1/ops/ext/shop/watch", headers=H, json={"url": "https://shopee.co.th/othershop", "name": "Other"}).get_json()
ok(r["ok"] and shops.get(r["id"])["watch"] == 1, "watch from product page")
r = C.post("/api/v1/ops/ext/shop/known", headers=H, json={"urls": ["https://www.lazada.co.th/shop/shopx", "https://x.com"]}).get_json()
ok(list(r["known"].values())[0]["id"] == SID, "shop known")
save_config({"oa_my_shop_urls": "https://www.lazada.co.th/shop/myshop"})
SB = C.get("/api/oa/shops").get_json()
ok(any(x["is_mine"] and x["shop_key"] == "lazada:myshop" for x in SB["rows"]) and SB["mine_set"], "my shop from settings")
ok(any(x["platform"] == "lazada" and x["orders"] >= 6 for x in SB["erp"]), f"my shop real numbers from ERP orders {SB['erp']}")
ok(SB["bench"]["daily"] == 50 and any(g_["key"] == "daily" for g_ in SB["gaps"]), f"median benchmark + gap with ERP daily {SB['bench']} {SB['gaps']}")
ok(any(i["kind"] == "shop" and i["ref"] for i in shops.patrol_items(load_config())), "shops in patrol list")
ok(shops.parse_shop("https://shopee.co.th/search?keyword=a")[1] is None and shops.parse_shop("https://shopee.co.th/shop/123")[1] == "shopee:shop:123", "shop url parsing")

# ---------- 店铺后台数据 ----------
r = C.post("/api/v1/ops/ext/backend", headers=H, json={"url": "https://sellercenter.lazada.co.th/apps/product/performance", "title": "Product", "tables": "Product\tVisitors\n...", "text": ""}).get_json()
ok(r["ok"] and r["rows"] == 2 and r["matched"] == 1 and r["keywords"] == 1, f"backend page parsed {r}")
t_ = traffic.get("3DP0015-WH", "lazada")
ok(t_["visitors"] == 140 and abs(t_["conversion"] - 1.43) < 0.01 and t_["visitors_per_day"] == 20, f"traffic per SKU, conversion derived {t_}")
ok(radar.opportunity(cfg, radar.keyword(KID))["volume"] == 12500, "keyword search volume goes to radar")
lc = C.get("/api/oa/lifecycle").get_json()
lr = next(x for x in lc["rows"] if x["sku"] == "3DP0015-WH" and x["platform"] == "lazada")
ok(lr["traffic"] and lr["traffic"]["visitors"] == 140, "lifecycle shows traffic")
dsh = C.get("/api/oa/dashboard").get_json()
ok(dsh["market"]["traffic"]["matched"] == 1 and dsh["market"]["comp_events"], f"dashboard market card {list(dsh['market'])}")
ok(C.get("/api/oa/traffic").get_json()["pages"][0]["n_rows"] == 2, "traffic page")
save_config({"ai_api_key": ""})
r = C.post("/api/v1/ops/ext/backend", headers=H, json={"url": "https://sellercenter.lazada.co.th/x", "tables": "a"}).get_json()
ok(not r["ok"] and "AI" in r["error"], "backend needs AI")
r = C.post("/api/oa/comp/extract", json={"text": "฿120 ขายแล้ว 3.4พัน 12 รีวิว"}).get_json()
ok(r["how"] == "rules" and r["data"]["price"] == 120 and r["data"]["sold_text"] == "3.4พัน", f"no AI → rules {r['data']}")
save_config({"ai_api_key": "test-key"})

# ---------- 计划 ----------
sg = C.get("/api/oa/plans/suggest?sku=3DP0015-WH&platform=lazada&kind=hero").get_json()
ok(sg["benchmark_daily"] == 10 and sg["target_daily"] == 3.0, f"hero target = benchmark x 30% {sg}")
sg2 = C.get("/api/oa/plans/suggest?sku=3DP0015-WH&platform=lazada&kind=scale").get_json()
ok(sg2["target_daily"] == 6.0, f"scale target = benchmark x 60% {sg2['target_daily']}")
start = (dt.date.today() - dt.timedelta(days=4)).isoformat()
r = C.post("/api/oa/plans", json={"sku": "3DP0015-WH", "platform": "lazada", "kind": "hero", "start_day": start}).get_json()
ok(r["ok"], f"create plan {r}")
PID = r["id"]
ok(C.post("/api/oa/plans", json={"sku": "3DP0015-WH", "platform": "lazada", "kind": "scale"}).status_code == 400, "one active plan per sku+platform")
ok(C.post("/api/oa/plans", json={"sku": "NOPE-1", "platform": "lazada", "kind": "hero"}).status_code == 400, "unknown sku")
d = C.get(f"/api/oa/plans/{PID}").get_json()["plan"]
pr = d["progress"]
ok(pr["elapsed"] == 5 and pr["cum_actual"] == 5, f"actual from ERP orders {pr['elapsed']} {pr['cum_actual']}")
ok(pr["actual_revenue"] == 1250 and pr["actual_profit"] != 0, "plan revenue / profit like finance")
due = [t for t in d["tasks"] if t["due"]]
ok(len(due) >= 3 and all(t["text_th"] for t in due), f"staged tasks due {len(due)}")
tl = todo.collect("listing")
items = [i for i in tl["items"] if i["key"].startswith("ptask:")]
ok(len(items) == len(due) and items[0]["group"] == "计划" and items[0]["title_th"], "plan tasks in today's to-dos (staff see them)")
C.post("/api/todo/state", json={"key": items[0]["key"], "state": "done"})
d = C.get(f"/api/oa/plans/{PID}").get_json()["plan"]
tid = int(items[0]["key"].split(":")[1])
ok(next(t for t in d["tasks"] if t["id"] == tid)["done_at"], "done in to-dos = done in plan")
t2 = [t for t in d["tasks"] if t["due"]][0]
r = CL.post(f"/api/oa/plans/{PID}/task", json={"id": t2["id"], "done": True}).get_json()
ok(r["ok"] and todo.states().get(f"ptask:{t2['id']}") == "done", "tick in plan page → to-do done")
pl_staff = CL.get("/api/oa/plans").get_json()
ok(pl_staff["ok"] and "actual_profit" not in pl_staff["rows"][0]["progress"] and not pl_staff["owner"], "staff see plans without profit")
ok(CL.post(f"/api/oa/plans/{PID}/ai").status_code == 403 and CL.post("/api/oa/plans", json={}).status_code == 403, "staff can't change plans")
r = C.post(f"/api/oa/plans/{PID}/ai").get_json()
ok(r["ok"] and "曝光不够" in r["note"] and "ที่วางโทรศัพท์" in r["note"], "AI update plan note")
ai_t = [t for t in plans.tasks(PID) if t["source"] == "ai"]
ok(len(ai_t) == 1 and ai_t[0]["text_th"] == "เปลี่ยนรูปแรก", "AI tasks added")
C.post(f"/api/oa/plans/{PID}/task", json={"text": "拍短视频", "offset": 6})
ok(any(t["text"] == "拍短视频" for t in plans.tasks(PID)), "manual task")
c.execute("UPDATE ops_plans SET target_daily=50 WHERE id=?", (PID,)); c.commit()
d = plans.detail(load_config(), PID)
ok(d["progress"]["status"] in ("behind", "far") and d["tips"] and len(d["tips"]) == len(d["tips_th"]), f"behind → tips {d['progress']['status']}")
ok(any("访客" in x or "转化" in x or "目标日销" in x or "评价" in x for x in d["tips"]), f"tips use traffic / capacity {d['tips']}")
ok(any(i["key"].startswith(f"pstat:{PID}:") for i in todo.collect()["items"]), "plan behind in to-dos")
ok(C.post(f"/api/oa/plans/{PID}", json={"status": "done"}).get_json()["ok"] and plans.get(PID)["status"] == "done", "close plan")

# ---------- 营销日历 ----------
cal = C.get("/api/oa/campaigns?days=400").get_json()
ok(any(e["kind"] == "double" for e in cal["events"]) and any(e["kind"] == "festival" for e in cal["events"]), "built-in campaigns")
ok(cal["capacity"]["capacity_hours_per_day"] == 40 and cal["capacity"]["printers"] == 2, f"capacity in calendar {cal['capacity']}")
ev = cal["events"][0]
ok([t["offset"] for t in ev["tasks"]] == [-14, -7, -3, 0, 3] and ev["tasks"][0]["text_th"], "T-14..T+3 tasks")
in7 = (dt.date.today() + dt.timedelta(days=7)).isoformat()
r = C.post("/api/oa/campaigns", json={"name": "店庆", "start": in7, "multiplier": 500}).get_json()
ok(r["ok"], "add custom campaign")
ok(C.post("/api/oa/campaigns", json={"name": "x", "start": "2026-13-01"}).status_code == 400, "bad date")
cur = next(e for e in C.get("/api/oa/campaigns").get_json()["events"] if e["name"] == "店庆")
ok(cur["over_capacity"], "500x orders → over capacity")
tds = [i for i in todo.collect()["items"] if i["key"] == f"camp:{cur['key']}:-7"]
ok(tds and tds[0]["level"] == "warn" and tds[0]["alert"] and "超过产能" in tds[0]["detail"], "campaign T-7 task in to-dos with capacity warning")
C.post("/api/oa/campaigns/remove", json={"key": cur["key"]})
ok(not any(e["name"] == "店庆" for e in C.get("/api/oa/campaigns").get_json()["events"]), "remove custom")
k0 = cal["events"][0]["key"]
C.post("/api/oa/campaigns/remove", json={"key": k0})
ok(not any(e["key"] == k0 for e in C.get("/api/oa/campaigns?days=400").get_json()["events"]), "hide built-in")
C.post("/api/oa/campaigns/remove", json={"restore": True})
ok(any(e["key"] == k0 for e in C.get("/api/oa/campaigns?days=400").get_json()["events"]), "restore hidden")
ok(CL.get("/api/oa/campaigns").status_code == 200 and CL.post("/api/oa/campaigns", json={}).status_code == 403, "staff view calendar, owner edits")

# ---------- 今日待办 / 手机提醒 / 日报 ----------
tc = todo.collect()
keys = [i["key"] for i in tc["items"]]
ok(not tc["errors"], f"no to-do errors {tc['errors']}")
ok(any(k.startswith("cev:") for k in keys) and any(k.startswith(f"radar:{C2}") for k in keys), "competitor events + want in to-dos")
grp = {g_["zh"]: g_["th"] for g_ in tc["groups"]}
ok(grp.get("竞品") == "สินค้าคู่แข่ง" and grp.get("计划") == "แผนสินค้า", "new groups translated")
cev = next(i for i in tc["items"] if i["key"].startswith("cev:") and "降价" in i["title"])
ok(cev["alert"] and cev["title_th"].startswith("📉"), "price drop pushes to phone, Thai title")
ok(not any(i["key"].startswith("radar") or i["key"].startswith("cev:") for i in todo.collect("listing")["items"]), "staff don't see owner-only market items")
from modules.ops import alerts
SENT = []
alerts.send = lambda text, cfg=None: (SENT.append(text), (True, ""))[1]
save_config({"oa_radar_alert_score": 1, "oa_radar_report_hour": 0})
txt_ = radar.daily_report(load_config())
ok(txt_ and "爆款雷达日报" in txt_ and SENT, "daily radar report sent")
ok(radar.daily_report(load_config()) is None, "only once a day")

# ---------- 页面文件 ----------
for f in ("market.js", "plan.js", "page.css"):
    ok(C.get(f"/m/ops/{f}").status_code == 200, f"ui {f}")
html = C.get("/m/ops/page.html").get_data(as_text=True)
ok(all(f'id="tab-{t_}"' in html for t_ in ("ops_plans", "ops_cal", "ops_traffic", "ops_comp", "ops_radar", "ops_shops")), "page sections")
th = json.load(open(os.path.join(APP, "modules", "ops", "i18n", "th.json"), encoding="utf-8"))
ok(all(k in th for k in ("竞品", "爆款雷达", "竞店", "营销日历", "流量数据", "爆款 / 上量计划")), "Thai menu names")
sch = next(m for m in C.get("/api/settings/schema").get_json()["modules"] if m["id"] == "ops")
ok(any(f["key"] == "oa_patrol_daily_cap" for g_ in sch["groups"] for f in g_["fields"]), "phase-2 settings")
man = json.load(open(os.path.join(APP, "extension", "manifest.json"), encoding="utf-8"))
ok(man["version"] == integrations.EXT_LATEST and "capture.js" in json.dumps(man) and "patrol.html" in os.listdir(os.path.join(APP, "extension")), "extension merged + version")
print("ERRORS", E_)
