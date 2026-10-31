# v2.41.2：ERP 产品直接推到 Lazada（接口，模拟 Lazada）：建商品 / 再推是更新 / 属性按 id 对 / 图片先搬 / 变体 / 库存推送 / 复制产品不带
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json
D = T + "/m_lzpush"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, categories, integrations, listing, stockcalc, config
from core.connectors import lazada as LZ
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
PID = "3DP0015"

# 没有 Lazada 店铺
r = C.post("/api/listing/lazada/push", json={"product_ids": [PID]})
ok(r.status_code == 400 and "店铺" in r.get_json()["error"], f"no shop {r.get_json()}")
integrations.save_shop({"platform": "lazada", "name": "LZ", "enabled": True,
                        "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})

p = store.load(PID)
cat = categories.get(p["category"]["id"])
# 模拟 Lazada 类目属性：模板里的 catProperty / saleProp 都有，id 一样，选项 id 一样、名字换成「TH:」开头，看是不是按 id 对
attrs = [{"id": 1, "name": "name", "attribute_type": "normal"}, {"id": 2, "name": "description", "attribute_type": "normal"},
         {"id": 3, "name": "package_content", "attribute_type": "normal"}]
for f in cat["fields"]:
    if f["key"].startswith(("catProperty.p-", "saleProp.p-")):
        aid = f["key"].split("p-", 1)[1]
        attrs.append({"id": int(aid), "name": f"attr_{aid}", "attribute_type": "sku" if f["key"].startswith("saleProp") else "normal",
                      "input_type": "multiSelect" if f.get("multi") else "singleSelect",
                      "options": [{"id": int(i), "name": "TH:" + o, "en_name": f"EN{i} "} for o, i in zip(f["options"], f["option_ids"])]})
calls = []


def fake_call(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    calls.append((path, params, method))
    if path == "/image/upload":            # v2.43.1：本地图片直接传
        name, data = files["image"]
        ok(len(data) <= 1_000_000, f"image under 1MB ({len(data)})")
        return {"code": "0", "data": {"image": {"url": "https://lzd-img/" + name}}}
    if path == "/category/attributes/get":
        return {"code": "0", "data": attrs}
    if path == "/image/migrate":
        u = params["payload"].split("<Url>")[1].split("</Url>")[0]
        return {"code": "0", "data": {"image": {"url": "https://lzd-img/" + u.rsplit("/", 1)[-1]}}}
    if path == "/product/create":
        pr = json.loads(params["payload"])["Request"]["Product"]
        return {"code": "0", "data": {"item_id": 777, "sku_list": [{"seller_sku": s["SellerSku"], "sku_id": 9000 + i}
                                                                     for i, s in enumerate(pr["Skus"]["Sku"])]}}
    return {"code": "0", "data": {}}


LZ.LazadaConnector._call = fake_call

r = C.post("/api/listing/lazada/push", json={"product_ids": [PID], "force": True}).get_json()
ok(len(r["ok"]) == 1 and r["ok"][0]["created"] and r["ok"][0]["item_id"] == 777 and not r["failed"], f"pushed {r}")
create = next(json.loads(c[1]["payload"])["Request"]["Product"] for c in calls if c[0] == "/product/create")
ok(create["PrimaryCategory"] == str(cat["cat_id"]), "category id")
ok(create["Images"]["Image"] and all(u.startswith("https://lzd-img/") for u in create["Images"]["Image"]), f"images migrated {create['Images']}")
ok(create["Attributes"]["name"] == p["copy"]["title_th"] and create["Attributes"]["description"].startswith("<p>"), "name / description")
ok('<img src="https://lzd-img/' in create["Attributes"]["description"], "description ends with product pictures (v2.44.1)")
pa = {k: a.get("value") for k, a in p["attributes"].items()}
sel = [(k, v) for k, v in pa.items() if k.startswith("catProperty.p-") and isinstance(v, str)
       and v in next((f for f in cat["fields"] if f["key"] == k), {}).get("options", [])]
# v2.43.2：按选项 id 对上后发英文选项名（Lazada 校验认 en_name，发泰文被拒）
oid_of = lambda k, v: next(f for f in cat["fields"] if f["key"] == k)["option_ids"][next(f for f in cat["fields"] if f["key"] == k)["options"].index(v)]
ok(sel and all(create["Attributes"].get("attr_" + k.split("p-")[1]) == f"EN{oid_of(k, v)}" for k, v in sel), f"option by id → en_name {sel[:2]} {create['Attributes']}")
skus = create["Skus"]["Sku"]
ok([s["SellerSku"] for s in skus] == [v["sku"] for v in p["variants"]] and all(float(s["price"]) > 0 and "quantity" in s and s["package_length"] for s in skus),
   f"skus {skus[:1]}")
# v2.43.1：按 Lazada 文档——值都是字符串；变体在 variation.variation1，SKU 的 saleProp 用变体名
ok(all(isinstance(s[k], str) for s in skus for k in ("price", "quantity", "package_length", "package_weight")), "numbers as strings")
v1 = create["variation"]["variation1"]
ok(v1["options"]["option"] and all(s["saleProp"].get(v1["name"]) in v1["options"]["option"] for s in skus)
   and len(v1["name"]) <= 15 and all(len(o) <= 20 for o in v1["options"]["option"]), f"variations {create.get('variation')}")
ok(not v1["hasImage"] or all(s.get("Images") for s in skus), "hasImage only when every SKU has a picture")
ok(any(c[0] == "/image/upload" for c in calls) and not any(c[0] == "/image/migrate" for c in calls), "local images uploaded directly (no image host needed)")
lp = C.get(f"/api/listing/lazada/last/{PID}")
ok(lp.status_code == 200 and json.loads(lp.data)["payload"]["PrimaryCategory"] == create["PrimaryCategory"], "last payload downloadable")
q = store.load(PID)
ok(q["lazada_api"]["item_id"] == 777 and q["lazada_api"]["skus"] == {s["SellerSku"]: 9000 + i for i, s in enumerate(skus)}, "state saved")
ok(listing.status_of(q, "lazada")["status"] == "uploaded" and q.get("exported_at") and listing.exported_to(q, "lazada"), "listing uploaded + sku lock")
ok(all(stockcalc._synced("lazada").get(s["SellerSku"], {}).get("how") == "api" for s in skus), "stock marked synced")
# 再推 = 更新，带 ItemId / SkuId，图片不重复搬
n_img = sum(1 for c in calls if c[0] in ("/image/migrate", "/image/upload"))
calls.clear()
r = C.post("/api/listing/lazada/push", json={"product_ids": [PID], "force": True}).get_json()
upd = next((json.loads(c[1]["payload"])["Request"]["Product"] for c in calls if c[0] == "/product/update"), None)
ok(r["ok"] and not r["ok"][0]["created"] and upd and upd["ItemId"] == "777" and all(s.get("SkuId") for s in upd["Skus"]["Sku"]), "second push updates")
ok(not any(c[0] in ("/image/migrate", "/image/upload") for c in calls) and n_img >= 1, "images not uploaded twice")


# Lazada 报错：记在产品上，返回原因
def bad_call(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    if path == "/product/update":
        raise RuntimeError("Lazada /product/update 出错：500 Invalid（attr_x is mandatory）")
    return fake_call(self, path, params, base, token, method, files)


LZ.LazadaConnector._call = bad_call
r = C.post("/api/listing/lazada/push", json={"product_ids": [PID], "force": True}).get_json()
ok(r["failed"] and "mandatory" in r["failed"][0]["error"] and "mandatory" in store.load(PID)["lazada_api"]["error"], f"error kept {r['failed']}")
LZ.LazadaConnector._call = fake_call
# 不 force：有红色项不推
r = C.post("/api/listing/lazada/push", json={"product_ids": ["3DP0002"]}).get_json()
ok(r["errors"] and not r["ok"] and not r["failed"], f"check errors block {r}")
# 库存推送：只推用接口推过的 SKU
config.save_config({"stock_auto": True, "lazada_stock_sync_min": "0"})
stockcalc.mark_synced([{"sku": s["SellerSku"], "stock": 99, "product_id": PID} for s in skus], "t", "api", "lazada")
pend = [x for x in stockcalc.pending("lazada") if x["product_id"] == PID]
calls.clear()
r = C.post("/api/listing/lazada/stock-sync", json={}).get_json()
pq = [json.loads(c[1]["payload"])["Request"]["Product"]["Skus"]["Sku"] for c in calls if c[0] == "/product/price_quantity/update"]
flat = [x for b in pq for x in b]
ok(pend and r["synced"] == len(pend) and {x["SellerSku"] for x in flat} == {x["sku"] for x in pend}
   and all(x["ItemId"] == "777" and x["SkuId"] for x in flat), f"stock pushed {r} {flat[:1]}")
ok(not [x for x in stockcalc.pending("lazada") if x["product_id"] == PID], "nothing pending after sync")
# 复制产品：不带 Lazada 编号
d = C.post(f"/api/products/{PID}/duplicate").get_json()
ok(not store.load(d["id"]).get("lazada_api"), "duplicate drops lazada_api")
# 选项 id 是 0（接口有时不给真 id）：按泰文名对上，也发英文名
from modules.listing import lazada_push as LP2
a_ = {"name": "zal", "input_type": "singleSelect", "options": [{"id": "0", "name": "ใช่", "en_name": "Yes"}, {"id": "0", "name": "ไม่", "en_name": "No "}]}
ok(LP2._value(None, "ไม่", a_) == "No" and LP2._value(None, "yes", a_) == "Yes" and LP2._value(None, "อื่น", a_) == "อื่น", "match by Thai / English name")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
