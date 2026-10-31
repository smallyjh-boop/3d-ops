"""界面语言检查用的测试服务器（tests/ui/i18n_sweep.js 访问它）。
用法：python tests/ui/i18n_server.py <数据目录> <端口>
数据目录事先从测试数据（tests/fixtures/base_data.zip 解压出来的 v13）复制一份；这里建三个账号
（boss/owner、nok/listing、lek/production，密码都是 secret123）、塞几条客服会话 / 竞品 / 库存 / 采购单，
AI 换成假的回答（不连外网），然后起服务器。
"""
import json
import os
import sys
import time

D, PORT = sys.argv[1], sys.argv[2]
APP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LH_DATA_DIR"] = D
os.environ["PORT"] = str(PORT)
for k in ("LH_NO_MODULE_STARTUP", "LH_NO_TPL_SYNC", "LH_NO_UPDATE_CHECK", "LH_NO_PRESETS"):
    os.environ.setdefault(k, "1")
sys.argv[1:] = ["--no-browser"]
sys.path.insert(0, APP)
import app as A  # noqa: E402
from core import ai_copy, db  # noqa: E402


def fake(cfg, system, user, image_b64=None, **k):
    return json.dumps({"lang": "th", "buyer_msgs_zh": ["有粉色吗"], "intent": "product", "summary_zh": "买家问颜色",
                       "summary_th": "ลูกค้าถามสี", "reply": "มีสีชมพูค่ะ", "reply_zh": "有粉色", "needs_human": False,
                       "confidence": 0.9, "order_no": "", "custom_request_zh": "", "custom_request_th": "", "order_note_zh": "",
                       "kb_ids_used": [], "save_as_faq": False, "text": "（翻译）"})


ai_copy.call = fake

SEED = os.path.join(D, ".i18n_seeded")
if not os.path.exists(SEED):
    _c = db.conn()
    _c.execute("DELETE FROM users")
    _c.commit()
    for u, role, name, lang in (("boss", "owner", "Boss", "zh"), ("nok", "listing", "Nok", "th"), ("lek", "production", "Lek", "th")):
        try:
            db.create_user(u, "secret123", role, name, lang)
        except Exception as e:  # noqa: BLE001
            print("user", u, e)
    c = A.app.test_client()
    print("login", c.post("/api/auth/login", json={"username": "boss", "password": "secret123"}).status_code)
    try:   # 客服会话（买家消息是泰文 = 原始数据）
        from modules.cs.logic import data as cs
        cs.init()
        cv = cs.create_conv(buyer="Mali", platform="lazada")
        cs.add_msg(cv["id"], "buyer", "สวัสดีค่ะ มีสีชมพูไหมคะ", text_zh="你好，有粉色吗")
        cs.add_msg(cv["id"], "seller", "มีค่ะ", user="boss")
        cs.add_msg(cv["id"], "buyer", "ราคาเท่าไหร่คะ ส่งกี่วัน", text_zh="多少钱，几天到")
        cs.update_conv(cv["id"], intent="price", summary="买家问价格和发货时间", tags="询价",
                       analysis={"summary_zh": "买家问价格和发货时间", "summary_th": "ลูกค้าถามราคาและวันส่ง"})
        cv2 = cs.create_conv(buyer="Somchai", platform="shopee")
        cs.add_msg(cv2["id"], "buyer", "อยากสั่ง 30 ชิ้น ลดได้ไหม", text_zh="想订 30 个，能便宜吗")
    except Exception as e:  # noqa: BLE001
        print("cs seed", e)
    for body in ({"url": "https://www.lazada.co.th/products/x-i111-s222.html", "title": "โคมไฟแมว 3D", "skus": "3DP0001", "price": 260,
                  "sold_text": "100", "reviews": 20},):
        print("comp", c.post("/api/oa/comp", json=body).status_code)
    try:
        it = c.post("/api/inv/items", json={"name_zh": "测试胶带", "name_th": "เทปทดสอบ", "category": "pack", "unit": "卷"}).get_json()["item"]
        s = c.post("/api/inv/suppliers", json={"name": "Supplier A"}).get_json()
        sid = (s.get("supplier") or s)["id"]
        po = c.post("/api/inv/po", json={"supplier_id": sid, "lines": [{"item_id": it["id"], "qty": 10, "unit_cost": 5}]}).get_json()["po"]
        c.post(f"/api/inv/po/{po['id']}/order", json={})
    except Exception as e:  # noqa: BLE001
        print("inv seed", e)
    try:
        print("exp", c.post("/api/fin/expenses", json={"date": time.strftime("%Y-%m-%d"), "category": "房租", "amount": 5000, "note": "rent"}).status_code)
    except Exception as e:  # noqa: BLE001
        print("exp seed", e)
    open(SEED, "w").write("1")
db.release()
A.main()
