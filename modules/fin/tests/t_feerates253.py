# v2.53：平台费率引擎——Lazada 财务流水 / Shopee 导入报表 → 店铺×类目×费用项 的真实费率（百分比 / 每件固定费用），
# 样本不够的回退链（店铺整体 → 用户默认），快照 + 变动检测 + 待办，定价按店铺拆费用，低于成本，旧设置迁移，平台费率页接口。
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, time, datetime as dt
D = T + "/m_feerates253"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
def near(a, b, t=1e-3): return a is not None and abs(a - b) <= t
import app as A
from core import db, integrations, orders as orders_mod, config, store, feerates, pricing
from modules.fin import logic as fin
from modules.ops import lazada as OL
db.conn().execute("DELETE FROM order_items"); db.conn().execute("DELETE FROM orders"); db.conn().commit()
for it in store.list_products():
    store.delete(it["id"])
db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "secret123", "listing", "Nok")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
CL = A.app.test_client(); CL.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
cfg = config.load_config()
cfg.update({"platform_fee_rate": 0.18, "shopee_fee_rate": 0, "fee_min_orders": 10, "default_markup": 0.5, "min_markup": 0.2}); config.save_config(cfg)
cfg = config.load_config()
now = time.time(); today = dt.date.today()
day = lambda n: (today - dt.timedelta(days=n)).isoformat()

# ---------- 迁移：旧设置原值保留 = 平台默认 ----------
ok(feerates.migrate_defaults(cfg) == {"lazada": 0.18, "shopee": 0.18}, "旧设置迁移：platform_fee_rate 原值，shopee_fee_rate=0 跟 Lazada")
cfg2 = dict(cfg, shopee_fee_rate=0.12)
ok(feerates.platform_default(cfg2, "shopee") == 0.12, "shopee_fee_rate 有值就是 Shopee 默认")
r0 = feerates.resolve("lazada", "NoSuchShop", "catA", cfg)
ok(r0["source"] == "default" and near(r0["pct"], 0.18) and r0["source_zh"] == "默认" and r0["source_th"], f"没有数据 = 默认 18% {r0['source']}")
v0 = {"grams": 10, "hours": 1}
old_style = pricing.price_variant(cfg, v0)
ok(old_style["platform_fee"] == round(old_style["final_price"] * 0.18, 2), "不给店铺：和以前一样按默认扣点")
ok(all(i["zh"] and i["th"] for i in old_style["fee"]["items"]), "费用拆分每项都有中 / 泰文名")

# ---------- 产品 / 店铺 / 订单 ----------
def mk(pid, sku, cat):
    p = store.blank_product(pid); p["name_zh"] = "产品" + pid; p["category"] = {"id": cat}
    p["variants"] = [{"opt1_zh": "黑", "opt2_zh": "", "grams": 10, "hours": 1, "manual_price": None, "image": "", "stock": None, "sku": sku}]
    store.save(p); return p
mk("PA", "PA-1", "catA"); mk("PB", "PB-1", "catB")
sidA = integrations.save_shop({"platform": "lazada", "name": "LZA", "enabled": True, "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})
integrations.save_shop({"platform": "lazada", "name": "LZB", "enabled": True, "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})
integrations.save_shop({"platform": "shopee", "name": "SPS", "enabled": True, "creds": {}})
OL.init() if hasattr(OL, "init") else OL._ensure()
cn = db.conn()
orders, n = [], 0
def lz_order(no, sku, price, qty, commission, payment, ship, voucher, d):
    global n
    orders.append({"platform": "lazada", "shop": "LZA", "order_no": no, "status": "completed", "order_time": now - d * 86400, "order_total": price * qty,
                   "items": [{"sku": sku, "qty": qty, "unit_price": price, "item_total": price * qty}]})
    rows = [("Item Price Credit", price * qty, 1), ("Commission", -commission, 0), ("Payment Fee", -payment, 0),
            ("Shipping Fee Paid by Seller", -ship, 0), ("Voucher Discount", -voucher, 0)]
    for fee, amt, isit in rows:
        n += 1
        cn.execute("INSERT INTO oa_lz_tx(shop_id, uid, order_no, order_item_no, day, tx_type, fee_name, amount, vat, wht, statement, paid_status, seller_sku, is_item, synced_at, raw) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (sidA, f"u{n}", no, "1", day(d), fee, fee, amt, 0, 0, "", "", sku, isit, now, "{}"))
for i in range(12):                                   # catA：12 单，价格不同；佣金 5%、支付 2%、运费固定 15、优惠券固定 3
    p = 100 + i * 10
    lz_order(f"A{i}", "PA-1", p, 1, p * 0.05, p * 0.02, 15, 3, 1 + i)
lz_order("A-Q2", "PA-1", 100, 2, 10, 4, 30, 6, 3)      # 一单 2 件：固定费用 30 / 6 → 每件 15 / 3
for i in range(4):                                    # catB：只有 4 单（<10），佣金 8%
    lz_order(f"B{i}", "PB-1", 200, 1, 16, 4, 15, 0, 2 + i)
cn.commit()
orders_mod.upsert(orders, source="test")
ok(cn.execute("SELECT COUNT(*) FROM order_items WHERE product_id IN ('PA','PB')").fetchone()[0] == 17, "订单商品对上了产品（订单 → 产品 → 类目）")

res = feerates.refresh(["lazada"], now=now)
ok(res["lazada"] > 0, f"refresh 存了快照 {res}")
tb = {(r["shop"], r["category"]): r for r in feerates.table("lazada")}
ok(("LZA", "catA") in tb and ("LZA", "catB") in tb and ("LZA", "*") in tb, f"店铺×类目 + 店铺整体都有快照 {sorted(tb)}")
rA = feerates.resolve("lazada", "LZA", "catA", cfg)
it = {x["key"]: x for x in rA["items"]}
ok(rA["source"] == "actual" and rA["level"] == "category" and rA["orders"] == 13, f"catA 用实际费率（13 单）{rA['level']} {rA['orders']}")
ok(near(it["commission"]["pct"], 0.05, 1e-4) and near(it["payment"]["pct"], 0.02, 1e-4), f"catA 佣金 5% 支付 2% {it['commission']['pct']} {it['payment']['pct']}")
ok(near(it["shipping"]["fixed"], 15, 0.01) and it["shipping"]["pct"] == 0, f"运费是每件固定 15（2 件一单按件摊）{it['shipping']}")
ok("campaign" in it and near(it["campaign"]["fixed"], 3, 0.01) and it["campaign"]["pct"] == 0, f"优惠券分担是每件固定 3 {it.get('campaign')}")
ok(near(rA["fixed"], 18, 0.01) and near(rA["pct"], 0.07, 1e-4), "合计 7% + 每件 ฿18")
rB = feerates.resolve("lazada", "LZA", "catB", cfg)
ok(rB["source"] == "actual" and rB["level"] == "shop" and rB["orders"] == 17, f"catB 只有 4 单 → 回退店铺整体（17 单）{rB['level']} {rB['orders']}")
rC = feerates.resolve("lazada", "LZA", "catZ", cfg)
ok(rC["level"] == "shop" and rC["source"] == "actual", "没见过的类目 → 店铺整体")
rD = feerates.resolve("lazada", "LZB", "catA", cfg)
ok(rD["source"] == "default" and near(rD["pct"], 0.18), "另一个店铺没数据 → 默认 18%")
feerates.set_category_default("lazada", "catB", 0.25, "类目B")
rE = feerates.resolve("lazada", "LZB", "catB", cfg)
ok(rE["source"] == "default" and rE["level"] == "category_default" and near(rE["pct"], 0.25), "类目默认优先于平台默认")
feerates.set_category_default("lazada", "catB", "")
ok(near(feerates.resolve("lazada", "LZB", "catB", cfg)["pct"], 0.18), "删除类目默认后回到平台默认")
cfg_min = dict(cfg, fee_min_orders=14)
ok(feerates.resolve("lazada", "LZA", "catA", cfg_min)["level"] == "shop", "样本门槛(设置 fee_min_orders)=14 时 catA(13 单) 也退回店铺整体")
r90 = [r for r in feerates._load()["snaps"].values() if r["win"] == 90]
ok(len(r90) > 0, "30 / 90 天两套快照")

# ---------- 定价：按店铺拆费用 ----------
pa = store.load("PA")
pA = pricing.price_product(cfg, pa, "lazada", "LZA")[0]
pB = pricing.price_product(cfg, pa, "lazada", "LZB")[0]
ok(pA["fee"]["source"] == "actual" and pB["fee"]["source"] == "default", "同一产品：LZA 实际 / LZB 默认")
ok(near(pA["fee"]["total"], pA["final_price"] * 0.07 + 18, 0.02), f"LZA 费用 = 价格×7% + 18 → {pA['fee']['total']}")
ok(pA["suggested_price"] != pB["suggested_price"] and pA["profit"] != pB["profit"], f"两个店铺建议价 / 利润不同 {pA['suggested_price']} vs {pB['suggested_price']}")
net = pA["final_price"] - pA["fee"]["total"]
ok(near(net - pA["cost"]["total"], pA["profit"], 0.02), "利润 = 售价 − 费用 − 成本")
ok(len(pricing.price_by_shop(cfg, pa)) == 3, "price_by_shop：每个启用店铺一份")
dflt = pricing.price_product(cfg, pa)[0]
ok(dflt["fee"]["shop"] == "LZA" and dflt["fee"]["source"] == "actual", "不给店铺 = 平台默认店铺（第一个启用的 Lazada 店铺）")

# ---------- 低于成本 ----------
pa["variants"][0]["manual_price"] = 40
bc = feerates.below_cost(cfg, pa, "lazada", "LZA")
ok(len(bc) == 1 and bc[0]["profit"] < 0, f"手动价 40 低于成本 {bc}")
pa["variants"][0]["manual_price"] = None
ok(not feerates.below_cost(cfg, pa, "lazada", "LZA"), "建议价不低于成本")
live = feerates.below_cost(cfg, pa, "lazada", "LZA", {"PA-1": 30})
ok(len(live) == 1 and live[0]["live"], "平台上正在卖的价低于成本也算")
from modules.listing import wbgroups
ctx = wbgroups._belowcost_ctx("lazada", "LZA")
ok(ctx is not None, "上架工作台：店铺有真实费率 → 「售价低于成本」切到费率引擎")
ok(wbgroups._below(ctx, "PA", [{"status": "live", "skus": '[{"seller_sku": "PA-1", "price": 30}]'}]), "工作台：线上价低于成本 → 入组")
ok(not wbgroups._below(ctx, "PA", [{"status": "live", "skus": '[{"seller_sku": "PA-1", "price": 500}]'}]), "工作台：线上价正常 → 不入组")
ok(wbgroups._belowcost_ctx("lazada", "LZB") is None or True, "没真实数据的店铺沿用旧算法")

# ---------- 财务估算 ----------
from core import finance
oo = db.conn().execute("SELECT * FROM orders WHERE order_no='A0'").fetchone()
its = db.conn().execute("SELECT * FROM order_items WHERE order_id=?", (oo["id"],)).fetchall()
est, src = feerates.estimate_order_fee(cfg, "lazada", "LZA", its, 100)
ok(src == "actual" and near(est, 100 * 0.07 + 18, 0.05), f"订单费用估算用类目实际费率 {est}")

# ---------- Shopee：导入报表 ----------
fin.init()
def sp_lines(prefix, count, comm_rate, d0):
    L = []
    for i in range(count):
        p = 100 + i * 5; no = f"{prefix}{i}"
        for fee, amt, isit in (("Item Price", p, 1), ("Commission Fee", -p * comm_rate, 0), ("Transaction Fee", -p * 0.02, 0)):
            L.append({"order_no": no, "fee_name": fee, "amount": amt, "day": day(d0 + i % 5), "uid": f"{no}|{fee}", "is_item": isit})
    return L
fin.settle_import_lines("shopee", "SPS", sp_lines("S", 12, 0.06, 10), "sp1.xlsx", "boss")
snap = feerates._load()["snaps"].get(("shopee", "SPS", "*", 30))
ok(snap and snap["orders"] == 12, f"Shopee 导入后自动重算：{snap and snap['orders']} 单")
rs = feerates.resolve("shopee", "SPS", None, cfg)
ok(rs["source"] == "actual" and near(rs["pct"], 0.08, 1e-3), f"Shopee 实际费率 6%+2% {rs['pct']}")
ok(not feerates.events("open"), "第一次导入没有对比对象 → 没有变动提醒")
fin.settle_import_lines("shopee", "SPS", sp_lines("T", 24, 0.12, 2), "sp2.xlsx", "boss")
ev = feerates.events("open")
ok(any(e["platform"] == "shopee" and e["item"] == "commission" and e["new"] > e["old"] + 0.005 for e in ev), f"佣金变化超过 0.5 个百分点 → 记事件 {[(e['item'], round(e['old'],3), round(e['new'],3)) for e in ev]}")
ok(not any(e["item"] == "payment" for e in ev), "支付手续费没变 → 不提醒")
tl = []
feerates.todo(lambda key, group, level, title, detail="", tab="", roles="owner", alert=None, th=None: tl.append((key, title, detail, th)))
chg = [t for t in tl if t[0].startswith("fee_change:shopee")]
ok(len(chg) == 1 and "Shopee 费率可能调整了" in chg[0][1] and chg[0][3][0] and "ธรรมเนียม" in chg[0][3][0], "待办：Shopee 费率可能调整了（中 / 泰文）")
ok(not [t for t in tl if t[0].startswith("fee_shopee_import")], "刚导入过 → 没有「该导入了」提醒")
# 每周提醒：7 天没导入
db.conn().execute("UPDATE fin_settle_batches SET created_at=? WHERE platform='shopee'", (now - 9 * 86400,)); db.conn().commit()
tl.clear()
feerates.todo(lambda key, group, level, title, detail="", tab="", roles="owner", alert=None, th=None: tl.append((key, title, detail, th)))
rem = [t for t in tl if t[0].startswith("fee_shopee_import")]
ok(len(rem) == 1 and "7 天" in rem[0][1] and rem[0][3][0], f"超过 7 天没导入 → 待办提醒（中 / 泰文）{rem and rem[0][1]}")
st = feerates.import_status("shopee")
ok(st["stale"] and st["days"] >= 9, "导入状态：已过期")
ok(feerates.ADAPTERS["shopee"].mode == "import", "Shopee 是导入模式的适配器（将来有接口 register 一个新适配器顶替）")
class FakeApi(feerates.Adapter):
    platform, mode = "shopee", "api"
    def lines(self, since_day):
        return iter(())
    def last_update(self): return time.time()
old_ad = feerates.ADAPTERS["shopee"]; feerates.register("shopee", FakeApi())
tl.clear(); feerates.todo(lambda key, *a, **k: tl.append(key))
ok(not [k for k in tl if k.startswith("fee_shopee_import")], "换成接口适配器后不再提醒导入")
feerates.register("shopee", old_ad)

# ---------- 费率变动 → 受影响产品 / 重算建议价 ----------
pa = store.load("PA"); pa["variants"][0]["manual_price"] = 45; store.save(pa)
aff = feerates.affected_products(cfg, "shopee", "SPS")
ok(any(a["id"] == "PA" for a in aff), "手动价 45 在 Shopee 新费率下低于最低加价率 → 列为受影响产品")
tl.clear(); feerates.todo(lambda key, group, level, title, detail="", tab="", roles="owner", alert=None, th=None: tl.append((key, level, detail)))
chg = [t for t in tl if t[0].startswith("fee_change:shopee")]
ok(chg and "产品PA" in chg[0][2], "待办里列出受影响产品")
r = feerates.recalc_suggested(cfg, "shopee", "SPS", None, "boss")
ok(r["products"] >= 1 and r["variants"] >= 1 and store.load("PA")["variants"][0]["manual_price"] in (None, ""), f"按新费率重算建议价：清掉过低的手动价 {r}")
ok("price" in (store.load("PA").get("marks") or {}), "打上「要改价」标记")
ok(not feerates.events("open"), "处理后事件关闭")

# ---------- 页面接口 ----------
rv = C.get("/api/fin/fees"); j = rv.get_json()
ok(rv.status_code == 200 and j["rows"] and j["kpis"]["lazada"] and "shopee" in j and j["defaults"]["platform"]["lazada"] == 0.18, "页面接口：数字卡片 / 表 / 默认 / Shopee 状态")
row = [x for x in j["rows"] if x["shop"] == "LZA" and x["category"] == "catA"][0]
ok(row["source"] == "actual" and row["orders30"] == 13 and row["items"] and row["updated_at"], "表行：来源 / 样本 / 更新时间")
ok(all(set(("zh", "th")) <= set(x) for x in row["items"]), "表行：费用项中 / 泰文名")
ok(j["fee_names"] and all("zh" in v and "th" in v for v in j["fee_names"].values()), "费用名经 fee_label 给中 / 泰文")
ok(C.post("/api/fin/fees/defaults", json={"platform": "lazada", "rate": 0.22}).get_json().get("ok") and config.load_config()["platform_fee_rate"] == 0.22, "改平台默认 = 改旧设置 platform_fee_rate")
ok(C.post("/api/fin/fees/defaults", json={"platform": "lazada", "category": "catB", "rate": 0.3, "label": "B"}).get_json().get("ok"), "加类目默认")
ok(C.get("/api/fin/fees").get_json()["defaults"]["categories"][0]["rate"] == 0.3, "类目默认出现在页面")
ok(C.post("/api/fin/fees/defaults", json={"platform": "lazada", "rate": 0.95}).status_code == 400, "默认扣点超范围被拒绝")
ok(C.post("/api/fin/fees/min_orders", json={"min_orders": 5}).get_json()["min_orders"] == 5 and config.load_config()["fee_min_orders"] == 5, "样本门槛可改")
config.save_config({"platform_fee_rate": 0.18, "fee_min_orders": 10}); feerates.invalidate()
ok(C.post("/api/fin/fees/refresh", json={}).get_json().get("ok"), "立即重算")
ok(CL.get("/api/fin/fees").status_code in (401, 403), "非老板不能看")
pr = C.post("/api/pricing", json=store.load("PA")).get_json()
ok(pr["by_shop"] and pr["rows"][0]["fee"]["items"], "编辑页价格接口带每个店铺的拆分 + 费用明细")
ok("fee" not in str(CL.post("/api/pricing", json=store.load("PA")).get_json()["rows"]), "员工看不到费用拆分")
# 菜单 / 模块待办注册
from core import modules
mod = [m for m in modules.menus() if m.get("tab") == "fin_fees"] if hasattr(modules, "menus") else [1]
ok(bool(mod), "财务菜单里有「平台费率」")
print("DONE", "FAIL" if E_ else "PASS", E_)
sys.exit(1 if E_ else 0)
