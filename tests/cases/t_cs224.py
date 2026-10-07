# v2.24：扩展多店铺实时跟踪（presence）、ERP 提醒（alerts）、「按我的意思写」AI 先问
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, json, time
D = T + "/v224"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3; c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
import app as A
from core import ai_copy, integrations
E = 0
def ok(b, m):
    global E; print(("OK  " if b else "ERR ") + m); E += (not b)
C = A.app.test_client()
SEEN = {}
def fake(cfg, system, user, image_b64=None):
    SEEN["sys"], SEEN["user"] = system, user
    if "客服" in system:
        instr = "老板/客服的要求（这次回复必须照做）" in user
        return json.dumps({"lang": "th", "intent": "shipping" if instr else "product", "summary_zh": "问价格", "reply": "ส่งวันนี้ค่ะ" if instr else "ราคา 99 บาทค่ะ",
                           "reply_zh": "今天发货" if instr else "99 铢", "needs_human": False, "confidence": 0.9, "tags": [],
                           "ask_seller_zh": "今天几点前下单能发？" if instr else "应该被忽略"}, ensure_ascii=False)
    return "{}"
ai_copy.call = fake
K = integrations.create_key("Nok", "cs")
H = {"Authorization": "Bearer " + K, "X-Ext-Version": "2.6.0"}
r = C.post("/api/v1/cs/capture", json={"url": "https://sellercenter.lazada.co.th/im", "shop": "店A", "platform": "lazada", "buyer": "Somchai",
                                        "messages": [{"from": "buyer", "text": "ราคาเท่าไหร่คะ"}]}, headers=H).get_json()
cid = r["id"]
ok(r["drafted"] and r["draft"] == "ราคา 99 บาทค่ะ" and not (r.get("analysis") or {}).get("ask_seller_zh"), f"auto draft, no ask without instruction {r.get('drafted')} {r.get('draft')} {(r.get('analysis') or {}).get('ask_seller_zh')}")
r = C.post("/api/v1/cs/draft", json={"conv_id": cid, "instruction": "告诉她今天发货"}, headers=H).get_json()
ok(r["draft"] == "ส่งวันนี้ค่ะ" and r["analysis"]["ask_seller_zh"] == "今天几点前下单能发？" and "告诉她今天发货" in SEEN["user"], "instruction draft + AI asks back")
ok("ask_seller_zh" in SEEN["user"], "prompt asks for ask_seller_zh")
# presence：两个标签页（两个店铺）
r = C.post("/api/v1/cs/presence", json={"tab": "11", "shop": "店A", "platform": "lazada", "host": "sellercenter.lazada.co.th", "unread": 2, "buyers": ["Nok"], "auto": True}, headers=H).get_json()
r = C.post("/api/v1/cs/presence", json={"tab": "12", "shop": "店B", "platform": "shopee", "host": "seller.shopee.co.th", "unread": 0, "buyers": [], "auto": False}, headers=H).get_json()
ok(len(r["tabs"]) == 2 and r["tabs"][0]["shop"] == "店A" and r["tabs"][0]["unread"] == 2 and r["stats"]["open"] >= 1, f"presence list {r}")
ok(C.post("/api/v1/cs/presence", json={"shop": "x"}, headers=H).status_code == 400, "presence needs tab")
a = C.get("/api/cs/alerts").get_json()
ok(a["unread_in_browser"] == 2 and len(a["tabs"]) == 2 and a["latest"] and a["latest"][0]["id"] == cid and a["latest"][0]["shop"] == "店A", f"alerts {a}")
from core.cs import api as csapi
for k in list(csapi.PRESENCE):
    csapi.PRESENCE[k]["at"] -= 120
ok(C.get("/api/cs/alerts").get_json()["tabs"] == [], "stale tabs dropped")
ok(C.post("/api/v1/cs/presence", json={"tab": "1"}).status_code == 401, "presence needs key")

# ---- v2.24：客户档案、登记中心、账号与店铺、报表、工作台 ----
from core import db
from core.cs import crm, data as csd
c1 = C.get(f"/api/cs/convs/{cid}").get_json()
ok(c1["customer"] and c1["customer"]["visits"] == 1 and c1["shop"] == "店A", f"conv linked to customer {c1.get('customer')}")
cust = c1["customer"]["id"]
# 同一个买家在同一个店铺：同一个档案；在另一个店铺：另一个档案
r2 = C.post("/api/v1/cs/capture", json={"url": "https://seller.shopee.co.th/chat", "shop": "店B", "platform": "shopee", "buyer": "Somchai",
                                         "messages": [{"from": "buyer", "text": "มีของไหม"}]}, headers=H).get_json()
ok(r2["customer"]["id"] != cust, "other shop = other customer")
r = C.post("/api/cs/records", json={"conv_id": cid, "kind": "note", "text": "老客户，喜欢粉色"}).get_json()
ok(r["status"] == "done" and r["shop"] == "店A" and r["buyer"] == "Somchai" and r["customer_id"] == cust, f"note {r}")
due = time.time() - 60
r = C.post("/api/v1/cs/records", json={"conv_id": cid, "kind": "todo", "text": "明天问她要不要批发价", "due_at": due}, headers=H).get_json()
todo = r["id"]
ok(r["status"] == "open" and r["agent"] == "Nok" and r["overdue"], f"extension todo {r}")
c1 = C.get(f"/api/cs/convs/{cid}").get_json()
ok(len(c1["customer"]["records"]) == 2, "records on customer")
lst = C.get("/api/cs/records?status=overdue").get_json()
ok([x["id"] for x in lst["records"]] == [todo] and lst["counts"]["overdue"] == 1 and "店A" in lst["shops"], f"records center filter {lst['counts']}")
ok(len(C.get("/api/cs/records?agent=Nok").get_json()["records"]) == 1, "filter by agent")
r = C.post(f"/api/cs/records/{todo}", json={"status": "done", "result": "她说下周再定"}).get_json()
ok(r["status"] == "done" and r["done_at"] and r["result"], "mark done")
x = C.get("/api/cs/records/export")
ok(x.status_code == 200 and x.data[:2] == b"PK", "export xlsx")
# 回复记录到客服（扩展密钥 Nok）
C.post("/api/v1/cs/sent", json={"conv_id": cid, "text": "ส่งวันนี้ค่ะ"}, headers=H)
rep = C.get("/api/cs/report?period=today").get_json()
a = next(x for x in rep["agents"] if x["agent"] == "Nok")
ok(a["sent"] == 1 and a["convs"] == 1 and a["avg_reply_min"] is not None and a["records_added"] == 1 and a["records_done"] == 0, f"agent report {a}")
sa = next(x for x in rep["shops"] if x["shop"] == "店A")
sb = next(x for x in rep["shops"] if x["shop"] == "店B")
ok(sa["convs"] == 1 and sa["new_customers"] == 1 and sb["unanswered"] == 1, f"shop report {sa} {sb}")
ok(C.get("/api/cs/report/export?period=7d").data[:2] == b"PK", "report export")
wb = C.get("/api/cs/workbench").get_json()
ok(wb["owner"] and wb["today"]["total"]["sent"] == 1 and wb["waiting_n"] >= 1 and "yesterday" in wb, f"workbench {wb['waiting_n']}")
# 员工只看自己负责的店铺
db.create_user("boss", "secret1", "owner", "老板", "zh"); db.create_user("nok", "pass123", "listing", "Nok", "th")
C.post("/api/auth/login", json={"username": "boss", "password": "secret1"})
r = C.post("/api/cs/agents/shops", json={"agent": "nok", "shops": ["店B"]}).get_json()
ok(r["shops"] == ["店B"], "assign shops")
ag = C.get("/api/cs/agents").get_json()
ok(any(x["agent"] == "nok" and x["shops"] == ["店B"] for x in ag["agents"]) and any(x["agent"] == "Nok" and x["kind"] == "key" for x in ag["agents"]), f"agents {ag}")
S2 = A.app.test_client()
ok(S2.post("/api/auth/login", json={"username": "nok", "password": "pass123"}).status_code == 200, "staff login")
cv = S2.get("/api/cs/convs?status=active").get_json()
ok({x["shop"] for x in cv["convs"]} == {"店B"} and cv["shops"] == ["店B"], f"staff sees only own shop {[x['shop'] for x in cv['convs']]}")
ok(all(x["shop"] == "店B" for x in S2.get("/api/cs/records").get_json()["records"]), "staff records filtered")
ok(S2.post(f"/api/cs/records/{todo}", json={"status": "open"}).status_code == 403, "staff can't edit other shop record")
ok(S2.post("/api/cs/records", json={"conv_id": cid, "kind": "note", "text": "x"}).get_json().get("error"), "staff can't add to other shop")
ok(S2.post("/api/cs/agents/shops", json={"agent": "nok", "shops": []}).status_code in (403,), "staff can't assign shops")
rp = S2.get("/api/cs/report?period=today").get_json()
ok(all(x["agent"] == "nok" for x in rp["agents"]) and {x["shop"] for x in rp["shops"]} <= {"店B"}, "staff report: own only")
ok(S2.get("/api/cs/workbench").get_json()["owner"] is False, "staff workbench")
print("ERRORS", E)
