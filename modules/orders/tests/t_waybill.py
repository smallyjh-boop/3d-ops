# v2.34：平台面单框架——上传的平台面单 PDF 按模板排（裁白边、横转竖、信息区：订单号 / SKU / 货位 / 留言 / 打印次数）、
# 原样 PDF、另起一张信息、预览、面单来源一览、平台接口取面单（模拟接通）、打印记录
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, json
D = T + "/m_wb"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, store, production, connectors, integrations, orders as orders_mod
from modules.orders import waybill
from modules.orders.waybill import sources, render, template as WT
from PIL import Image
C = A.app.test_client()


def mk_pdf(pages):
    """手写一个最简单的 PDF：pages = [(宽pt, 高pt, 内容流)]，字体 Helvetica。"""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for w, h, content in pages:
        objs.append(f"<< /Length {len(content.encode())} >>\nstream\n{content}\nendstream")
        cid = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Contents {cid} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out)); out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    return out


def label_ops(x, y, w, h, order_no, track):
    bars = " ".join(f"{x + 20 + i * 5} {y + h - 140} {2 if i % 3 else 1} 70 re f" for i in range(40))
    return (f"0 0 0 RG 1.5 w {x} {y} {w} {h} re S BT /F1 14 Tf {x + 20} {y + h - 30} Td (ORDER {order_no}) Tj ET "
            f"BT /F1 12 Tf {x + 20} {y + h - 50} Td (TRK {track}) Tj ET 0 0 0 rg {bars}")


config.save_config({"review_enabled": False})
sku = store.load(store.list_products()[0]["id"])["variants"][0]["sku"]
o1 = C.post("/api/orders/manual", json={"order_no": "WB-1001", "order_total": 199, "items": [{"sku": sku, "qty": 2}]}).get_json()
o2 = C.post("/api/orders/manual", json={"order_no": "WB-1002", "order_total": 99, "items": [{"sku": sku, "qty": 1}]}).get_json()
o3 = C.post("/api/orders/manual", json={"order_no": "WB-1003", "order_total": 99, "items": [{"sku": sku, "qty": 1}]}).get_json()
db.conn().execute("UPDATE orders SET buyer_note='ขอกล่องสวยๆ', custom_note='刻字 MALI' WHERE id=?", (o1["id"],)); db.conn().commit()
# A4 纸左上角一张 100×150 的面单（WB-1001）；第二页横版面单（WB-1002，150×100）
pdf = mk_pdf([(595, 842, label_ops(20, 397, 283, 425, "WB-1001", "TH000111")),
              (595, 842, label_ops(20, 500, 425, 283, "WB-1002", "TH000222"))])
r = C.post("/api/labels/import", data={"file": (io.BytesIO(pdf), "awb.pdf")}, content_type="multipart/form-data").get_json()
ok(r["pages"] == 2 and r["matched"] == 2, f"import split {r}")
# 来源一览、模板默认值
st = C.get("/api/waybill/status").get_json()
src = {s["id"]: s for s in st["sources"]}
ok(src["upload"]["ready"] and not src["shopee"]["ready"] and not src["lazada"]["ready"] and src["self"]["ready"], "sources status")
ok(st["template"]["enabled"] is False and st["renderer"] is True and len(st["fields"]) >= 10, "default template off, renderer ok")
# 模板没开：原样 PDF
r = C.get(f"/print/labels?type=platform&ids={o1['id']}")
ok(r.mimetype == "application/pdf", "template off -> raw pdf")
# 开模板（信息区高度超范围会被限制）
t = C.post("/api/waybill/template", json={"enabled": True, "info_mm": 999, "fields": ["order_no", "items", "loc", "total", "buyer_note", "custom_note", "count", "bad"],
                                          "text": "易碎品 ของเปราะบาง"}).get_json()["template"]
ok(t["enabled"] and t["info_mm"] == 70 and "bad" not in t["fields"] and t["layout"] == "below", f"save template {t}")
ok(WT.clean({"paper": "100x150", "info_mm": 120})["info_mm"] == 70, "info area capped")
# 货位：成品放在 C1 货架
C.post("/api/inv/locations/bulk", json={"zone": "C", "shelf": 1, "layers": 2, "positions": 2, "categories": ["goods"]})
production.stock_add(sku, 3, "备货打印", "t", sku.split("-")[0], "测试", "白色")
h = C.get(f"/print/labels?type=platform&ids={o1['id']},{o2['id']},{o3['id']}").get_data(as_text=True)
ok(f"/api/waybill/awb/{o1['id']}/0.png" in h and f"/api/waybill/awb/{o2['id']}/0.png" in h, "composed page uses awb images")
ok("WB-1001" in h and sku in h and "×2" in h and "C1-01-01" in h and "ขอกล่องสวยๆ" in h and "刻字 MALI" in h and "易碎品" in h, "info area content")
ok("补打 第2次" in h and "#1" in h and "WB-1003" in h and "没有平台面单" in h, "raw print counted, second print warns; missing listed")
ok(h.count('class="wb"') == 2 and "100mm 150mm" in h, "one label per order (below layout)")
h = C.get(f"/print/labels?type=platform&ids={o1['id']}").get_data(as_text=True)
ok("补打 第3次" in h, "reprint warning")
ok(waybill.counts([o1["id"]])[o1["id"]] == 3, "print records")
ok(C.get(f"/print/labels?type=platform&ids={o1['id']}&raw=1").mimetype == "application/pdf", "raw=1 -> original pdf")
ok(C.get(f"/print/waybill?ids={o3['id']}").status_code == 404, "only missing -> 404")
# 面单图片：A4 上的小面单裁白边；横版转竖
r = C.get(f"/api/waybill/awb/{o1['id']}/0.png")
im = Image.open(io.BytesIO(r.data)); ok(r.mimetype == "image/png" and im.width < 1400 and im.height > im.width, f"cropped {im.size}")
im2 = Image.open(io.BytesIO(C.get(f"/api/waybill/awb/{o2['id']}/0.png").data)); ok(im2.height > im2.width and im2.height < 1900, f"rotated {im2.size}")
ok(C.get(f"/api/waybill/awb/{o3['id']}/0.png").status_code == 404, "no awb -> 404")
# 另起一张信息
C.post("/api/waybill/template", json={"layout": "page", "paper": "100x180"})
h = C.get(f"/print/waybill?ids={o1['id']}").get_data(as_text=True)
ok(h.count('class="wb"') == 2 and 'class="info full"' in h and "100mm 180mm" in h, "page layout: awb + info page")
# 预览（不记打印）
n0 = waybill.counts([o1["id"]])[o1["id"]]
h = C.get("/print/waybill-preview?tpl=" + json.dumps({"layout": "below", "fields": ["order_no", "items", "count"]})).get_data(as_text=True)
ok("2610090001ABCD" in h and "补打 第2次" in h and "setTimeout" not in h and waybill.counts([o1["id"]])[o1["id"]] == n0, "preview")
# 平台接口取面单（模拟 Lazada 接通）
png = io.BytesIO(); Image.new("L", (600, 900), 255).save(png, "PNG")
integrations.save_shop({"platform": "lazada", "name": "Lazada TH", "enabled": True, "creds": {"app_key": "k"}})
orders_mod.upsert([{"platform": "lazada", "shop": "Lazada TH", "order_no": "LZ-777", "status": "to_ship", "items": [{"sku": sku, "qty": 1}]}], source="test")
lz = db.conn().execute("SELECT id FROM orders WHERE order_no='LZ-777'").fetchone()["id"]
r = C.post("/api/labels/check", json={"ids": [lz]}).get_json(); ok(r["missing"] == [lz], "api not connected -> missing")
p, why = sources.ensure(orders_mod.get_order(lz)); ok(p is None and "上传" in why, f"ensure explains {why}")
Lz = connectors.REGISTRY["lazada"]
Lz.LABEL_READY = True
Lz.fetch_label = lambda self, o: {"kind": "png", "data": png.getvalue(), "tracking_no": "LEX0001"}
ok(any(s["id"] == "lazada" and s["ready"] for s in sources.status()), "lazada source ready when connected + shop enabled")
r = C.post("/api/labels/check", json={"ids": [lz]}).get_json()
oz = orders_mod.get_order(lz)
ok(r["have"] == [lz] and oz["label_file"] == f"{lz}.pdf" and oz["tracking_no"] == "LEX0001", f"fetched from api {r} {oz['tracking_no']}")
ok(any(x["action"] == "取平台面单" for x in orders_mod.get_log(lz)), "order log")
Lz.LABEL_READY = False
# 连接器默认：取面单没接通
try:
    connectors.make("shopee", {}).fetch_label({}); ok(False, "base fetch_label")
except connectors.NotReady:
    ok(True, "base fetch_label raises NotReady")
# 设置页卡片的接口：员工不能改模板
db.create_user("staff", "pass123", "listing", "Staff", "zh")
C2 = A.app.test_client(); ok(C2.post("/api/auth/login", json={"username": "staff", "password": "pass123"}).status_code == 200, "staff login")
ok(C2.post("/api/waybill/template", json={"enabled": False}).status_code == 403, "staff can't change template")
print("ERRORS", E_); sys.exit(1 if E_ else 0)
