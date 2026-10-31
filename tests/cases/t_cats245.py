# v2.45：类目和类目属性从 Lazada 接口拉——类目树、按接口生成字段表（和模板一样的结构）、没模板的类目也能选能填能推；
# 导出 Excel 照旧用模板；AI 匹配类目避开要 TISI 许可证的类目
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json
D = T + "/cats245"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, store, integrations, categories, lazada_cats, attributes, ai_copy
from core.connectors import lazada as LZ
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})

lib0 = categories.library()
tpl = next(c for c in lib0 if c["cat_id"] == "3800")
ok(not any(c["id"].startswith("api|") for c in lib0) and categories.get(tpl["id"]).get("source") is None, "no API shop: templates only")

TREE = [{"category_id": 1, "name": "ของเล่น", "leaf": False, "var": True, "children": [
            {"category_id": 3800, "name": "ฟิกเกอร์และของสะสม", "leaf": True, "var": True},
            {"category_id": 14221, "name": "ของเล่นคลายเครียด", "leaf": True, "var": True},
            {"category_id": 99999, "name": "ของเล่นตั้งโต๊ะ ฟิกเกอร์มังกร", "leaf": True, "var": True}]}] + \
       [{"category_id": 5000 + i, "name": f"หมวด {i}", "leaf": True, "var": True} for i in range(150)]


def attrs_of(cid):
    base = [{"id": 1, "name": "name", "attribute_type": "normal", "is_mandatory": "1", "input_type": "text"},
            {"id": 20000, "name": "brand", "label": "ยี่ห้อ", "attribute_type": "normal", "is_mandatory": "1", "input_type": "singleSelect"},
            {"id": 30168, "name": "material", "label": "วัสดุ", "attribute_type": "normal", "is_mandatory": "1", "input_type": "singleSelect",
             "options": [{"id": 1661, "name": "พลาสติก", "en_name": "Plastic"}, {"id": 229864, "name": "โลหะผสม", "en_name": "Alloy"}]},
            {"id": 30097, "name": "color_family", "label": "สี", "attribute_type": "sku", "is_sale_prop": "1", "input_type": "singleSelect",
             "options": [{"id": 4660, "name": "สีดำ", "en_name": "Black"}]},
            {"id": 7, "name": "warranty_type", "label": "ประเภทการรับประกัน", "attribute_type": "normal", "input_type": "singleSelect",
             "options": [{"id": 141503, "name": "ไม่มีการรับประกัน", "en_name": "No Warranty"}]},
            {"id": 8, "name": "package_weight", "attribute_type": "sku", "is_mandatory": "1"},
            {"id": 9, "name": "price", "attribute_type": "sku", "is_mandatory": "1"}]
    if int(cid) == 14221:
        base.append({"id": 77, "name": "TH_TISI", "label": "TISI License", "attribute_type": "normal", "is_mandatory": "1", "input_type": "text"})
    return base


calls = []


def fake(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    calls.append(path)
    if path == "/category/tree/get":
        return {"code": "0", "data": TREE}
    if path == "/category/attributes/get":
        return {"code": "0", "data": attrs_of(params["primary_category_id"])}
    return {"code": "0", "data": {}}


LZ.LazadaConnector._call = fake
integrations.save_shop({"platform": "lazada", "name": "LZ", "enabled": True,
                        "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})
lazada_cats._en["t"] = 0
n = lazada_cats.refresh_tree(force=True)
ok(n >= 150 and categories.path_of("99999") == "ของเล่น > ของเล่นตั้งโต๊ะ ฟิกเกอร์มังกร", f"tree from API {n} {categories.path_of('99999')}")
ok(lazada_cats.refresh_tree() == 0, "tree not refreshed again within a week")
lib = categories.library()
ok(any(c["id"] == "api|99999" for c in lib) and any(c["id"] == tpl["id"] for c in lib), "library: templates + API categories")
ok(categories.by_cat_id("99999")["id"] == "api|99999" and categories.by_cat_id("3800")["id"] == tpl["id"], "by_cat_id prefers template, else api")
# 接口生成的字段表
cat = categories.get("api|99999")
keys = {f["key"]: f for f in cat["fields"]}
ok(cat["source"] == "api" and cat["cat_id"] == "99999" and keys["catProperty.p-20000"]["kind"] == "brandProp"
   and keys["saleProp.p-30097"]["kind"] == "colorFamily" and keys["warrantyType"]["options"] == ["ไม่มีการรับประกัน"]
   and keys["catProperty.p-30168"]["option_ids"] == ["1661", "229864"] and keys["catProperty.p-30168"]["required"], f"fields {list(keys)}")
ok(not any(k.endswith(("p-1", "p-8", "p-9")) for k in keys), "name / package / price not treated as attributes")
n0 = calls.count("/category/attributes/get")
categories.get("api|99999")
ok(calls.count("/category/attributes/get") == n0, "attributes cached")
# 有模板的类目：字段用接口的，模板文件照旧（导出用模板本身）
t_api, t_x = categories.get(tpl["id"]), categories.get(tpl["id"], for_export=True)
ok(t_api["source"] == "api" and t_api["template"] == tpl["template"] and t_x.get("source") is None and t_x["fields"] != t_api["fields"], "template id: API fields, export keeps template")
r = C.get(f"/api/category-fields?id={tpl['id']}").get_json()
ok(r["source"] == "api" and not r["needs_license"], "editor fields from API")
# 没模板的类目：能检查、能推、导出说清楚
p = store.load("3DP0015")
p["category"] = {"id": "api|99999", "cat_id": "99999", "status": "manual"}
p["attributes"] = {"catProperty.p-30168": {"value": "พลาสติก", "status": "manual"}}
store.save(p)
from web.common import _check
e, w = _check(A.load_config(), store.load("3DP0015"))
ok(not any("模板" in x for x in e), f"no 'template missing' error {e}")
r = C.post("/api/export", json={"product_ids": ["3DP0015"], "force": True}).get_json()
ok(any("没有 Excel 模板" in x for x in r.get("errors", [])), f"export explains api category {r.get('errors')}")
# 要许可证的类目
lazada_cats.attrs(14221)
ok(categories.needs_license("14221") and categories.needs_license("12298") and not categories.needs_license("99999"), "licence detection")
# AI 匹配类目：候选里要许可证的不给 AI，选能放的
prompts = []


def fake_ai(cfg, system, user, **k):
    prompts.append(user)
    if len(prompts) == 1:
        return json.dumps({"search_keywords_th": ["ของเล่น", "ฟิกเกอร์", "คลายเครียด"], "ideal_path_th": "ของเล่น > ของเล่นคลายเครียด"})
    return json.dumps({"cat_id": "99999", "confidence": 0.9, "reason_zh": "桌面摆件", "reason_th": "x", "path_zh": "玩具"})


ai_copy.call = fake_ai
m = attributes.match_category(A.load_config(), store.load("3DP0015"))
ok("14221" not in prompts[1] and "99999" in prompts[1] and "licence" in prompts[1], "licensed candidates removed from the AI list")
ok(m["id"] == "api|99999" and m["status"] == "ai", f"matched usable category {m}")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
