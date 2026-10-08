# v2.33：快递面单模板——按订单的物流认快递、各家版式、尺寸、预览、设置
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil
D = T + "/m_carr"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, store
from modules.orders import carriers
C = A.app.test_client()
for t, k in (("Flash Express", "flash"), ("Kerry", "kerry"), ("KEX Express", "kerry"), ("J&T Express", "jt"), ("SPX Express", "spx"),
             ("Lazada Express (LEX)", "lex"), ("ไปรษณีย์ไทย EMS", "thpost"), ("Thailand Post", "thpost"), ("Ninja Van", "ninja"), ("", "generic"), ("abc", "generic")):
    ok(carriers.detect({"carrier": t}) == k, f"detect {t!r} -> {k}")
config.save_config({"review_enabled": False, "sender_name": "Lucky 3D", "sender_phone": "0812345678"})
sku = store.load(store.list_products()[0]["id"])["variants"][0]["sku"]
o = C.post("/api/orders/manual", json={"order_no": "LB-1", "order_total": 299, "items": [{"sku": sku, "qty": 2}]}).get_json()
db.conn().execute("UPDATE orders SET carrier='Flash Express', tracking_no='TH01234567', cod=299, receiver='สมชาย', postcode='10110', address='กรุงเทพ' WHERE id=?", (o["id"],)); db.conn().commit()
h = C.get(f"/print/labels?type=self&ids={o['id']}").get_data(as_text=True)
ok("Flash Express" in h and "#FFD400" in h and "100mm 150mm" in h and "TH01234567" in h and "COD ฿299" in h and "10110" in h and "Lucky 3D" in h, "flash 100x150")
h = C.get(f"/print/labels?type=self&ids={o['id']}&tpl=thpost&size=a6").get_data(as_text=True)
ok("Thailand Post" in h and "105mm 148mm" in h and 'class="pcb"' in h, "override thpost a6 with postcode boxes")
h = C.get(f"/print/labels?type=self&ids={o['id']}&size=100x100").get_data(as_text=True)
ok("100mm 100mm" in h and "สินค้า：" not in h, "100x100 compact")
config.save_config({"label_carrier": "kerry", "label_size": "a6"})
h = C.get(f"/print/labels?type=self&ids={o['id']}").get_data(as_text=True)
ok("KEX Express" in h and "105mm 148mm" in h, "settings fix carrier and size")
p = C.get("/print/label-preview?carrier=jt&size=100x150").get_data(as_text=True)
ok("J&amp;T Express" in p and "สมชาย ใจดี" in p and "打印 / พิมพ์" not in p, "preview with sample")
r = C.get("/api/label-templates").get_json(); ok(len(r["carriers"]) == len(carriers.CARRIERS) and len(r["sizes"]) == 3, "templates api")
sch = {m["id"]: m for m in C.get("/api/settings/schema").get_json()["modules"]}
ok(any(g["title"] == "自制面单模板" for g in sch["orders"]["groups"]), "settings group")
ms = {m["id"]: m for m in C.get("/api/modules?all=1").get_json()["modules"]}; ok("orders" in ms["orders"]["settings_cards"], "settings card")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
