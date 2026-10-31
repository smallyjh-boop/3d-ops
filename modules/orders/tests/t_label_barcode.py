# v2.41.2：上传图片型平台面单 PDF（Lazada 卖家中心打印的，页面上没有文字）→ 读条码对订单号 / 运单号
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io
D = T + "/m_wbbar"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A  # noqa: F401
from core import db, labels, orders as orders_mod
import zxingcpp
from PIL import Image

orders_mod.upsert([{"platform": "lazada", "order_no": "1134620956753716", "status": "to_ship", "items": [{"sku": "X", "qty": 1}]},
                   {"platform": "shopee", "order_no": "SP-1", "tracking_no": "TH0123456789", "status": "to_ship", "items": [{"sku": "X", "qty": 1}]},
                   {"platform": "shopee", "order_no": "SP-2", "status": "to_ship", "items": [{"sku": "X", "qty": 1}]}], source="test")
oid = {r["order_no"]: r["id"] for r in db.conn().execute("SELECT id, order_no FROM orders")}


def page(*codes):
    """一页 A6 面单图片，上面画几个 Code128 条码（没有文字层）。"""
    pg = Image.new("L", (1240, 1748), 255)
    y = 100
    for c in codes:
        bc = Image.fromarray(zxingcpp.create_barcode(c, zxingcpp.BarcodeFormat.Code128).to_image(scale=4, add_quiet_zones=True))
        pg.paste(bc, (100, y)); y += bc.height + 120
    return pg


pages = [page("LEXDO0190000384", "1134620956753716"),      # Lazada：运单号 + 订单号
         page("TH0123456789"),                              # 只有运单号
         page("NOT-IN-SYSTEM-999")]                         # 系统里没有
buf = io.BytesIO(); pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:], resolution=300.0)
r = labels.import_pdf(io.BytesIO(buf.getvalue()), user="boss")
ok(r["pages"] == 3 and r["matched"] == 2 and r["unmatched_pages"] == [3], f"matched by barcode {r}")
ok(sorted(r["order_nos"]) == ["1134620956753716", "SP-1"], f"order nos {r['order_nos']}")
o = orders_mod.get_order(oid["1134620956753716"])
ok(o["label_file"] == f"{o['id']}.pdf" and os.path.exists(os.path.join(labels.LABEL_DIR, o["label_file"])), "label stored")
ok(not orders_mod.get_order(oid["SP-2"]).get("label_file"), "other order untouched")
# 太短的条码不乱对
buf = io.BytesIO(); page("SP").save(buf, "PDF", resolution=300.0)
r = labels.import_pdf(io.BytesIO(buf.getvalue()))
ok(r["matched"] == 0 and r["unmatched_pages"] == [1], f"short code no match {r}")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
