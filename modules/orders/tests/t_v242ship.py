# v2.42：打面单 / 打包核对 / 发货交接前先从平台拉最新状态，买家取消的单拦下；一次打 10 / 20 / 50 单平台面单
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, io, re, time, json, base64
D = T + "/m_v242ship"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, config, integrations, labels, orders as orders_mod
from core.connectors import lazada as LZ
from modules.orders import waybill
from PIL import Image, ImageDraw
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
oid = lambda no: db.conn().execute("SELECT id FROM orders WHERE order_no=?", (no,)).fetchone()["id"]

# ---------- 取消拦截 ----------
sid = integrations.save_shop({"platform": "lazada", "name": "LZ", "enabled": True,
                              "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})
orders_mod.upsert([{"platform": "lazada", "shop": "LZ", "order_no": "LZ-C1", "tracking_no": "LEXC1", "status": "to_ship",
                    "items": [{"sku": "X-1", "qty": 1}]}], source="test")
REMOTE = {"LZ-C1": "to_ship"}
fetches = []
def fake_fetch(self, since, until):
    fetches.append(time.time())
    return [{"platform": "lazada", "order_no": no, "status": st, "items": [{"sku": "X-1", "qty": 1}]} for no, st in REMOTE.items()]
LZ.LazadaConnector.fetch_orders = fake_fetch
r = C.post("/api/labels/check", json={"ids": [oid("LZ-C1")]}).get_json()
ok(not r["blocked"] and len(fetches) == 1, f"still to_ship, synced once {r}")
C.post("/api/labels/check", json={"ids": [oid("LZ-C1")]})
ok(len(fetches) == 1, "no second sync within a minute")
REMOTE["LZ-C1"] = "cancelled"                       # 买家在 Lazada 上取消了
db.conn().execute("UPDATE shops SET last_sync=0 WHERE id=?", (sid,)); db.conn().commit()
r = C.post("/api/labels/check", json={"ids": [oid("LZ-C1")]}).get_json()
ok(r["blocked"] and r["blocked"][0]["order_no"] == "LZ-C1" and not r["have"] and not r["missing"], f"label check blocks cancelled {r}")
ok(orders_mod.get_order(oid("LZ-C1"))["status"] == "cancelled", "status synced from platform")
r = C.get(f"/print/labels?type=self&ids={oid('LZ-C1')}")
ok(r.status_code == 409 and "LZ-C1" in r.get_json()["error"], "print refuses cancelled")
# 打包核对 / 交接：本地还是待发货、平台已取消 → 扫的时候拉一次，拦下
orders_mod.upsert([{"platform": "lazada", "shop": "LZ", "order_no": "LZ-C2", "tracking_no": "LEXC2", "status": "to_ship",
                    "items": [{"sku": "X-1", "qty": 1}]}], source="test")
REMOTE.update({"LZ-C2": "cancelled"})
db.conn().execute("UPDATE shops SET last_sync=0 WHERE id=?", (sid,)); db.conn().commit()
r = C.get("/api/pack/lookup?code=LZ-C2")
ok(r.status_code == 400 and "不要打包" in r.get_json()["error"], f"pack blocks {r.get_json()}")
orders_mod.upsert([{"platform": "lazada", "shop": "LZ", "order_no": "LZ-C3", "tracking_no": "LEXC3", "status": "to_ship",
                    "items": [{"sku": "X-1", "qty": 1}]}], source="test")
REMOTE.update({"LZ-C3": "cancelled"})
db.conn().execute("UPDATE shops SET last_sync=0 WHERE id=?", (sid,)); db.conn().commit()
hid = orders_mod.handover_open("LEX", "", "boss")
try:
    orders_mod.handover_scan(hid, "LEXC3", "boss"); ok(False, "handover blocks")
except ValueError as e:
    ok("不能发货" in str(e), f"handover blocks {e}")
# 平台连不上：照本地状态，不影响打印
def boom(self, since, until):
    raise RuntimeError("network down")
LZ.LazadaConnector.fetch_orders = boom
orders_mod.upsert([{"platform": "lazada", "shop": "LZ", "order_no": "LZ-OK", "status": "to_ship", "items": [{"sku": "X-1", "qty": 1}]}], source="test")
db.conn().execute("UPDATE shops SET last_sync=0 WHERE id=?", (sid,)); db.conn().commit()
r = C.get(f"/print/labels?type=self&ids={oid('LZ-OK')}")
ok(r.status_code == 200, "platform down: still prints by local status")

# ---------- 批量打印平台面单 ----------
db.conn().execute("UPDATE shops SET enabled=0"); db.conn().commit()
config.save_config({"waybill_tpl": {"enabled": True, "layout": "below", "fields": ["order_no", "items", "spec", "total", "count"]}})
os.makedirs(labels.LABEL_DIR, exist_ok=True)


def awb_pdf(no, path):
    """一张 A4 上一个 Lazada 大小的面单图片（图片型 PDF，和卖家中心打的一样）。"""
    pg = Image.new("L", (2480, 3508), 255); d = ImageDraw.Draw(pg)
    d.rectangle([200, 200, 1180, 1540], outline=0, width=8)
    for x in range(260, 1100, 18): d.rectangle([x, 300, x + 8, 700], fill=0)
    d.text((300, 760), no, fill=0)
    pg.save(path, "PDF", resolution=300.0)


N = 50
batch = [{"platform": "shopee", "order_no": f"B-{i:03d}", "status": "to_ship", "items": [{"sku": f"S-{i}", "qty": 1 + i % 3, "variation": "Black"}]}
         for i in range(N)]
orders_mod.upsert(batch, source="test")
ids = [oid(f"B-{i:03d}") for i in range(N)]
for i, x in enumerate(ids):
    awb_pdf(f"B-{i:03d}", os.path.join(labels.LABEL_DIR, f"{x}.pdf"))
    db.conn().execute("UPDATE orders SET label_file=? WHERE id=?", (f"{x}.pdf", x))
db.conn().commit()
pages_html = {}
for n in (10, 20, 50):
    t0 = time.time()
    r = C.get(f"/print/labels?type=platform&ids={','.join(map(str, ids[:n]))}")
    dt_ = time.time() - t0
    html = r.get_data(as_text=True)
    wb = len(re.findall(r'<div class="wb">', html))
    imgs = re.findall(r'<img src="([^"]+)"', html)
    ok(r.status_code == 200 and wb == n and len(imgs) == n and all(f"B-{i:03d}" in html for i in range(n)), f"{n} orders → {wb} labels")
    ok(all(f"flex-basis:{x}" not in html for x in ("0.0mm",)) and "flex-basis:" in html, f"{n}: sizes set")
    t1 = time.time()
    bad = [u for u in imgs if C.get(u).status_code != 200]
    print(f"    {n} 单：打印页 {dt_:.1f} 秒，面单图片 {time.time() - t1:.1f} 秒")
    ok(not bad, f"{n}: all label images load")
    pages_html[n] = (html, imgs)
cnt = waybill.counts(ids[:10])
ok(all(v == 3 for v in cnt.values()), f"print counted per order (10 printed 3 times) {set(cnt.values())}")
# 原样 PDF：50 单合成一个 50 页的 PDF
r = C.get(f"/print/labels?type=platform&raw=1&ids={','.join(map(str, ids))}")
import pypdf
ok(r.status_code == 200 and len(pypdf.PdfReader(io.BytesIO(r.data)).pages) == N, "raw merged PDF has 50 pages")
# 真的用浏览器排版打印：50 单 = 50 张纸（100×150），每张一个面单
try:
    from playwright.sync_api import sync_playwright
    html, imgs = pages_html[50]
    for u in set(imgs):
        html = html.replace(u, "data:image/png;base64," + base64.b64encode(C.get(u).data).decode())
    with sync_playwright() as pw:
        b = pw.chromium.launch(); pg = b.new_page(); pg.set_content(html, wait_until="load")
        pdf = pg.pdf(prefer_css_page_size=True, print_background=True); b.close()
    rd = pypdf.PdfReader(io.BytesIO(pdf))
    box = rd.pages[0].mediabox
    ok(len(rd.pages) == N and abs(float(box.width) / 72 * 25.4 - 100) < 1 and abs(float(box.height) / 72 * 25.4 - 150) < 1,
       f"browser prints {len(rd.pages)} pages of {float(box.width) / 72 * 25.4:.0f}x{float(box.height) / 72 * 25.4:.0f}mm")
except ImportError:
    print("    （没装 Playwright，跳过浏览器排版检查）")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
