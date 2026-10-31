# v2.44：在线商品——从 Lazada 拉店铺商品、按 SellerSku 对上 ERP（表格上传的也能对上）、状态跟平台走、
# 筛选、快速改价改库存（改到平台并写回 ERP）、上下架、产品库显示在哪些店铺在线
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json
D = T + "/m_online"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, integrations, listing, stockcalc, orders as orders_mod
from core.connectors import lazada as LZ
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
ok(C.post("/api/online/sync", json={}).status_code == 400, "no shop: clear error")
sid = integrations.save_shop({"platform": "lazada", "name": "ร้านรวมของดี", "enabled": True,
                              "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})
p = store.load("3DP0015")
skus = [v["sku"] for v in p["variants"]]
ok(not (p.get("lazada_api") or {}).get("item_id"), "uploaded by spreadsheet: ERP does not know the item id yet")


def prod(item, status, sku_list, name="x", qty=5, reject=None):
    return {"item_id": item, "status": status, "attributes": {"name": name}, "primary_category": "3800",
            "images": json.dumps(["https://img/a.jpg"]), "created_time": "1793000000000", "updated_time": "1793100000000",
            "rejectReason": [{"violationDetail": reject}] if reject else [],
            "skus": [{"SellerSku": s, "SkuId": 9000 + i, "price": 99, "special_price": 79, "quantity": qty, "Status": "active",
                      "Url": f"https://www.lazada.co.th/i{item}.html"} for i, s in enumerate(sku_list)]}


SHOP = [prod("111", "Active", skus, "ฟิกเกอร์แมว", qty=5), prod("222", "Suspended", ["3DP0002-WH"], "โคมไฟ", reject="Wrong image"),
        prod("333", "InActive", ["NOT-IN-ERP"], "ของอื่น", qty=0)] + [prod(str(1000 + i), "Active", [f"X-{i}"]) for i in range(60)]
calls = []


def fake(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    calls.append((path, dict(params)))
    if path == "/products/get":
        off, lim = int(params["offset"]), int(params["limit"])
        return {"code": "0", "data": {"total_products": str(len(SHOP)), "products": SHOP[off:off + lim]}}
    return {"code": "0", "data": {}}


LZ.LazadaConnector._call = fake
r = C.post("/api/online/sync", json={}).get_json()
ok(r["shops"][0]["items"] == 63 and r["shops"][0]["linked"] == 2 and not r["shops"][0]["error"], f"synced with paging {r}")
ok(sum(1 for c in calls if c[0] == "/products/get") == 2, "two pages of 50")
q = store.load("3DP0015")
ok(q["lazada_api"]["item_id"] == "111" and q["lazada_api"]["skus"][skus[0]] == "9000", "spreadsheet product linked to item id")
ok(listing.status_of(q, "lazada")["status"] == "live" and q.get("exported_at"), "status from platform: live, SKU locked")
q2 = store.load("3DP0002")
ok(listing.status_of(q2, "lazada")["status"] == "rejected" and "Wrong image" in listing.status_of(q2, "lazada").get("note", ""), "rejected with reason")
r = C.get("/api/online?platform=lazada").get_json()
ok(r["counts"].get("live") == 61 and r["counts"].get("rejected") == 1 and r["counts"].get("inactive") == 1
   and r["counts"].get("unlinked") == 61 and r["counts"].get("stock0") == 1, f"counts {r['counts']}")
it = next(x for x in r["items"] if x["item_id"] == "111")
ok(it["product_id"] == "3DP0015" and it["price_min"] == 79 and it["qty"] == 5 * len(skus) and it["shop"] == "ร้านรวมของดี", "row fields")
ok([x["item_id"] for x in C.get("/api/online?platform=lazada&linked=no&q=ของอื่น").get_json()["items"]] == ["333"], "filter unlinked + search")
ok([x["item_id"] for x in C.get("/api/online?platform=lazada&status=rejected").get_json()["items"]] == ["222"], "filter status")
ok([x["item_id"] for x in C.get("/api/online?platform=lazada&stock0=1").get_json()["items"]] == ["333"], "filter stock 0")
# 近 30 天销量
orders_mod.upsert([{"platform": "lazada", "order_no": "S1", "status": "shipped", "items": [{"sku": skus[0], "qty": 3}]}], source="test")
it = next(x for x in C.get("/api/online?platform=lazada&q=111").get_json()["items"])
ok(it["sold_30d"] == 3, f"sold 30d {it['sold_30d']}")
# 改价 / 库存：改到平台、写回 ERP
calls.clear()
r = C.post("/api/online/sku", json={"platform": "lazada", "shop_id": sid, "item_id": "111", "seller_sku": skus[0],
                                    "price": "109", "special_price": "89", "qty": "7"}).get_json()
pq = [json.loads(c[1]["payload"]) for c in calls if c[0] == "/product/price_quantity/update"]
sk = pq[0]["Request"]["Product"]["Skus"]["Sku"][0] if pq else {}
ok(sk.get("Price") == "109.0" and sk.get("SalePrice") == "89.0" and sk.get("Quantity") == "7" and sk.get("SkuId") == "9000", f"sent to Lazada {sk}")
v0 = store.load("3DP0015")["variants"][0]
ok(v0["manual_price"] == 89 and "售价" in r["erp"], f"ERP price follows {r['erp']}")
ok(stockcalc._synced("lazada")[skus[0].upper()]["synced"] == 7, "stock marked synced")
ok(C.post("/api/online/sku", json={"platform": "lazada", "shop_id": sid, "item_id": "111", "seller_sku": skus[0], "qty": "-1"}).status_code == 400, "negative refused")
ok(C.post("/api/online/sku", json={"platform": "shopee", "shop_id": sid, "item_id": "111", "seller_sku": skus[0], "qty": "1"}).status_code == 400, "shopee: no api yet")
# 下架 / 上架
calls.clear()
ok(C.post("/api/online/active", json={"platform": "lazada", "shop_id": sid, "item_id": "111", "active": False}).status_code == 200
   and any(c[0] == "/product/deactivate" and "<ItemId>111</ItemId>" in c[1]["apiRequestBody"] for c in calls), "deactivate")
ok(listing.status_of(store.load("3DP0015"), "lazada")["status"] == "inactive", "ERP status inactive")
C.post("/api/online/active", json={"platform": "lazada", "shop_id": sid, "item_id": "111", "active": True})
ok(any(c[0] == "/product/update" for c in calls), "activate via update")
# 产品库：在哪些店铺在线
lib = {x["id"]: x for x in C.get("/api/products").get_json()}
ok(lib["3DP0015"]["online"] and lib["3DP0015"]["online"][0]["shop"] == "ร้านรวมของดี" and not lib["3DP0005"]["online"], "library shows shops")
# 平台上删掉的商品：下次同步去掉
SHOP[:] = SHOP[:2]
C.post("/api/online/sync", json={})
ok({x["item_id"] for x in C.get("/api/online").get_json()["items"]} == {"111", "222"}, "deleted items removed")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
