# v2.42：面单上印的字只有泰文 / 英文：平台面单的信息区、自制快递面单、旧版自制面单都不印系统的中文；
# 商品名 / 规格是中文时换成产品的泰文，换不了就不印
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, re
D = T + "/m_lblth"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A  # noqa: F401
from core import config, store, labels, orders as orders_mod
from modules.orders import carriers, labeltext
from modules.orders.waybill import render, template as WT

CJK = re.compile(r"[㐀-鿿豈-﫿]")


def printed(html):
    """去掉不打印的部分（按钮条、标题、样式里的字体名），剩下印在纸上的字。"""
    html = re.sub(r"<div class='noprint'>.*?</div>(</div>)?", "", html, flags=re.S)
    html = re.sub(r"<title>.*?</title>|<style>.*?</style>|<script>.*?</script>", "", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


p = store.load("3DP0015")
v = p["variants"][0]
orders_mod.upsert([{"platform": "manual", "order_no": "M-TH-1", "status": "to_ship", "receiver": "", "address": "",
                    "ship_method": "pickup", "buyer_note": "ขอด่วน", "custom_note": "", "cod": 0,
                    "items": [{"sku": v["sku"], "name": "猫咪手办", "variation": v.get("opt1_zh") or "白色", "qty": 2},
                              {"sku": "NOPE-1", "name": "不认识的商品", "variation": "红色大号", "qty": 1}]}], source="test")
from core import db
o = orders_mod.get_order(db.conn().execute("SELECT id FROM orders WHERE order_no='M-TH-1'").fetchone()["id"])
cfg = config.load_config()
tx = labeltext.Texts(cfg)
it0 = next(i for i in o["items"] if i["sku"] == v["sku"])
nm, sp = tx.name(it0), tx.spec(it0)
ok(nm and not CJK.search(nm) and nm == p["copy"]["title_th"], f"name -> product Thai title {nm}")
ok(sp and not CJK.search(sp), f"spec -> Thai {sp}")
it1 = next(i for i in o["items"] if i["sku"] == "NOPE-1")
ok(tx.name(it1) == "" and tx.spec(it1) == "", "unknown Chinese item: not printed")
ok(tx.name({"name": "Cat figure แมว"}) == "Cat figure แมว", "platform text kept")

tpl = WT.clean({"enabled": True, "fields": WT.FIELD_IDS})
html = render.compose([(o, [render.SAMPLE_AWB], 3)], tpl, {}, lambda c: (0,), autoprint=False)
txt = printed(html)
ok(not CJK.search(txt), f"waybill info area has no Chinese: {CJK.findall(txt)[:10]}")
ok("Reprint #3" in txt and "ชิ้น/pcs" in txt and v["sku"] in txt, "reprint / total / sku printed")
pv = printed(render.preview_html(tpl, lambda c: (0,)))
ok(not CJK.search(pv), f"settings preview has no Chinese: {CJK.findall(pv)[:10]}")
for key in carriers.CARRIERS:
    for size in carriers.SIZES:
        t = printed(carriers.html([o], cfg, key, size))
        if CJK.search(t):
            ok(False, f"carrier {key} {size}: {CJK.findall(t)[:10]}"); break
    else:
        continue
    break
else:
    ok(True, "self-made carrier labels have no Chinese")
t = printed(carriers.html([o], cfg, "generic", "100x150"))
ok("Pickup" in t and "No address" in t and "NO COD" in t, "ship method / no address / no cod in Thai+English")
t = printed(labels.self_made_html([o], cfg))
ok(not CJK.search(t), f"old self-made label has no Chinese: {CJK.findall(t)[:10]}")
# v2.42：面单宽度占满纸，剩下的给信息区
WT_ = WT.clean({"enabled": True, "paper": "100x150", "info_mm": 12})
a, b = render.split_mm(WT_, 134 / 98)
ok(abs(a - 136) < 0.01 and abs(b - 14) < 0.01, f"lazada label full width {a} {b}")
a, b = render.split_mm(WT_, 1.6)
ok(abs(b - 12) < 0.01 and abs(a - 138) < 0.01, f"long label shrinks to keep min info {a} {b}")
a, b = render.split_mm(WT_, 1.0)
ok(abs(a - 100) < 0.01 and abs(b - 50) < 0.01, f"short label gives info the rest {a} {b}")
ok(WT.clean({"info_mm": 34})["info_mm"] == 12 and WT.clean({"info_mm": 20})["info_mm"] == 20, "old default 34 migrated")
html2 = render.compose([(o, ["x.png"], 1)], WT_, {}, lambda c: (0,), autoprint=False, aspects={o["id"]: 134 / 98})
ok('flex-basis:136.0mm' in html2 and 'flex-basis:14.0mm' in html2, "sizes in page")
ok("<title>Waybill" in html2, "page title not Chinese")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
