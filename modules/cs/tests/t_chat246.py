# v2.46：客服聊天——Lazada 聊天接口收发（模拟）、店铺 AI 模式（只人工 / 出草稿 / 自动）、人工接管与超时交回、分配、
# 快捷回复变量、商品 / 订单卡片、主动提醒（发货）、自动标签、夜间提示、质检抽查、分店知识库、工作台汇总、后台任务队列
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, time
D = T + "/m_chat246"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, integrations, ai_copy, orders as orders_mod, store
from core.connectors import lazada as LZ
REAL_CALL = LZ.LazadaConnector._call
from modules.cs.logic import data, chat, jobs, shopcfg, brain, service
from modules.cs.logic.channels import lazada_im
db.create_user("boss", "secret123", "owner", "Boss")
db.create_user("nok", "secret123", "listing", "Nok")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
C2 = A.app.test_client(); C2.post("/api/auth/login", json={"username": "nok", "password": "secret123"})
data.init()

NOW = time.time() * 1000
SESS = [{"session_id": "S1", "buyer_id": "B1", "title": "Mali", "head_url": "https://x/a.jpg", "last_message_time": str(NOW - 1000)}]
MSGS = {"S1": [
    {"message_id": "m1", "from_account_type": "1", "send_time": str(NOW - 5000), "template_id": "1", "content": json.dumps({"txt": "สวัสดีค่ะ ราคาเท่าไหร่คะ"})},
    {"message_id": "m2", "from_account_type": "1", "send_time": str(NOW - 4000), "template_id": "3", "content": json.dumps({"imgUrl": "https://x/p.jpg"})},
    {"message_id": "m3", "from_account_type": "2", "send_time": str(NOW - 3000), "template_id": "1", "content": json.dumps({"txt": "สวัสดีค่ะ"}), "auto_reply": "true"},
]}
SENT = []


def fake(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    if path == "/im/session/list":
        return {"code": "0", "success": "true", "err_code": "0", "data": {"session_list": SESS, "has_more": "false"}}
    if path == "/im/message/list":
        lst = sorted(MSGS.get(params["session_id"], []), key=lambda m: -float(m["send_time"]))
        return {"code": "0", "success": "true", "data": {"message_list": lst, "has_more": "false"}}
    if path == "/im/message/send":
        SENT.append(dict(params))
        if params.get("txt") == "BOOM":
            return {"code": "0", "success": "false", "err_code": "IM_ERR", "err_message": "blocked"}
        return {"code": "0", "success": "true", "data": {"message_id": f"out{len(SENT)}"}}
    if path == "/im/session/read":
        return {"code": "0", "success": "true", "data": {}}
    return {"code": "0", "data": {}}


LZ.LazadaConnector._call = fake
sid = integrations.save_shop({"platform": "lazada", "name": "LZ-TH", "enabled": True,
                              "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})
sid = sid["id"] if isinstance(sid, dict) else sid
DRAFTS = []


def fake_ai(cfg, system, user, **k):
    DRAFTS.append(user)
    if "主管" in system:
        return json.dumps({"accuracy": 4, "attitude": 5, "speed": 3, "comment": "回复准确"})
    return json.dumps({"lang": "th", "buyer_msgs_zh": ["多少钱"], "intent": "price", "summary_zh": "问价格", "reply": "ราคา 199 บาทค่ะ",
                       "reply_zh": "199 铢", "needs_human": False, "confidence": 0.95, "order_no": "", "custom_request_zh": "",
                       "order_note_zh": "", "kb_ids_used": [], "save_as_faq": False})


ai_copy.call = fake_ai

# ---- 拉消息 ----
r = jobs.poll_all(force=True)
cv = data.find_conv("lazada", f"im:{sid}:S1")
ok(r == {"LZ-TH": 1} and cv and cv["channel"] == "lazada_im" and cv["shop"] == "LZ-TH" and cv["buyer"] == "Mali" and cv["avatar"], f"session pulled {r}")
ms = data.messages(cv["id"])
ok([m["role"] for m in ms] == ["buyer", "buyer", "seller"] and ms[1]["kind"] == "image" and ms[1]["extra"]["url"] == "https://x/p.jpg", "messages in order, image parsed, auto reply = seller")
ok("询价" in data.get_conv(cv["id"])["tag_list"], "auto tag 询价")
jobs.poll_all(force=True)
ok(len(data.messages(cv["id"])) == 3, "no duplicates on second poll")
# 卖家最后说话 → 没有待回复；买家再发一条 → 草稿任务（默认 AI 出草稿）
MSGS["S1"].append({"message_id": "m4", "from_account_type": "1", "send_time": str(NOW + 1000), "template_id": "1", "content": json.dumps({"txt": "มีสีชมพูไหมคะ ราคาเท่าไหร่"})})
SESS[0]["last_message_time"] = str(NOW + 1000)
jobs.poll_all(force=True)
todo = db.conn().execute("SELECT kind FROM cs_jobs WHERE conv_id=? AND status='todo'", (cv["id"],)).fetchall()
ok([x["kind"] for x in todo if x["kind"] != "tr"] == ["draft"], f"draft job queued (default mode draft) {[dict(x) for x in todo]}")
jobs.run_due()
c1 = data.get_conv(cv["id"])
ok(c1["draft"] == "ราคา 199 บาทค่ะ" and not SENT, "draft written, nothing sent")
# ---- 店铺自动模式：能自动发的直接发 ----
shopcfg.save("LZ-TH", mode="auto")
jobs.enqueue("auto", cv["id"]); jobs.run_due()
ok(SENT and SENT[-1]["txt"] == "ราคา 199 บาทค่ะ" and SENT[-1]["session_id"] == "S1" and SENT[-1]["template_id"] == "1", f"auto sent {SENT[-1:]}")
last = data.messages(cv["id"])[-1]
ok(last["role"] == "seller" and last["source"] == "auto" and last["ext_id"] == "out1", "sent message recorded with platform id")
# 平台拉回同一条消息（id 一样）不重复
MSGS["S1"].append({"message_id": "out1", "from_account_type": "2", "send_time": str(NOW + 2000), "template_id": "1", "content": json.dumps({"txt": "ราคา 199 บาทค่ะ"})})
SESS[0]["last_message_time"] = str(NOW + 2000)
jobs.poll_all(force=True)
ok(sum(1 for m in data.messages(cv["id"]) if m["text"] == "ราคา 199 บาทค่ะ") == 1, "own message not duplicated")
# ---- 人工接管：AI 不自动发；别人发要确认 ----
r = C2.post(f"/api/cs/convs/{cv['id']}/takeover").get_json()
ok(r["mode"] == "human" and r["taken_by"] == "nok" and r["ai_mode"] == "draft", "nok took over, AI only drafts")
n0 = len(SENT)
MSGS["S1"].append({"message_id": "m5", "from_account_type": "1", "send_time": str(NOW + 3000), "template_id": "1", "content": json.dumps({"txt": "ขอบคุณค่ะ"})})
SESS[0]["last_message_time"] = str(NOW + 3000)
jobs.poll_all(force=True); jobs.run_due()
ok(len(SENT) == n0, "taken over: no auto send")
r = C.post(f"/api/cs/convs/{cv['id']}/send", json={"text": "hello"})
ok(r.status_code == 409 and r.get_json()["taken"], "other agent blocked while taken")
r = C.post(f"/api/cs/convs/{cv['id']}/send", json={"text": "hello", "force": True})
ok(r.status_code == 200 and SENT[-1]["txt"] == "hello", "force send works")
r = C2.post(f"/api/cs/convs/{cv['id']}/send", json={"text": "BOOM"})
ok(r.status_code == 502 and data.messages(cv["id"])[-1]["status"] == "failed", "send failure recorded")
fm = data.messages(cv["id"])[-1]["id"]
r = C2.post(f"/api/cs/messages/{fm}/resend")
ok(r.status_code == 502 and sum(1 for m in data.messages(cv["id"]) if m["text"] == "BOOM") == 1, "resend replaces the failed one")
# 超时交回
db.conn().execute("UPDATE cs_conv SET taken_at=? WHERE id=?", (time.time() - 3600, cv["id"])); db.conn().commit()
ok(chat.sweep_takeover() == 1 and data.get_conv(cv["id"])["mode"] == "", "takeover timeout → back to AI")
r = C.post(f"/api/cs/convs/{cv['id']}/assign", json={"agent": "nok"}).get_json()
ok(r["assigned"] == "nok", "assigned")
inbox = C2.get("/api/cs/inbox?status=mine").get_json()
ok([x["id"] for x in inbox["convs"]] == [cv["id"]] and inbox["counts"]["mine"] == 1, "my conversations")
# ---- 商品 / 订单卡片 ----
p = store.load("3DP0015"); p["lazada_api"] = {"item_id": 777}; store.save(p)
r = C.post(f"/api/cs/convs/{cv['id']}/send", json={"kind": "item", "product_id": "3DP0015"})
ok(r.status_code == 200 and SENT[-1]["template_id"] == "10006" and SENT[-1]["item_id"] == "777", f"item card {SENT[-1]}")
ok(data.messages(cv["id"])[-1]["kind"] == "item" and data.messages(cv["id"])[-1]["extra"]["name"], "item card recorded")
r = C.post(f"/api/cs/convs/{cv['id']}/send", json={"kind": "item", "product_id": "3DP0002"})
ok(r.status_code == 400 or "没有商品编号" in (r.get_json() or {}).get("error", ""), "unpushed product cannot be sent as card")
orders_mod.upsert([{"platform": "lazada", "order_no": "LZ-9001", "status": "to_ship", "buyer": "Mali", "receiver": "", "address": "",
                    "items": [{"sku": p["variants"][0]["sku"], "name": "x", "qty": 1}]}], source="test")
oid = db.conn().execute("SELECT id FROM orders WHERE order_no='LZ-9001'").fetchone()["id"]
r = C.post(f"/api/cs/convs/{cv['id']}/send", json={"kind": "order", "order_id": oid})
ok(r.status_code == 200 and SENT[-1]["template_id"] == "10007" and SENT[-1]["order_id"] == "LZ-9001", "order card")
ol = C.get(f"/api/cs/convs/{cv['id']}/orders").get_json()["items"]
ok(any(o["order_no"] == "LZ-9001" for o in ol), "buyer orders for the card picker")
# ---- 快捷回复变量 ----
q = C.get("/api/cs/quick").get_json()
ok(len(q["items"]) >= 5 and "买家名" in q["vars"], "default quick replies")
qid = next(x["id"] for x in q["items"] if "{运单号}" in x["text"])
db.conn().execute("UPDATE cs_conv SET order_id=?, order_no='LZ-9001' WHERE id=?", (oid, cv["id"]))
db.conn().execute("UPDATE orders SET tracking_no='TH123' WHERE id=?", (oid,)); db.conn().commit()
t = C.get(f"/api/cs/convs/{cv['id']}/quick/{qid}").get_json()["text"]
ok("LZ-9001" in t and "TH123" in t and "{" not in t, f"variables filled {t}")
ok(chat.fill("คุณ{买家名} {不认识}", data.get_conv(cv["id"])) == "คุณMali {不认识}", "unknown var kept")
# ---- 主动提醒：发货 ----
shopcfg.save("LZ-TH", mode="draft")
n0 = len(SENT)
orders_mod.set_status(oid, "shipped", "boss") if hasattr(orders_mod, "set_status") else None
from modules.cs import events as cse
cse.on_order_status(oid, "shipped", "to_ship", "boss")
db.conn().execute("UPDATE cs_jobs SET run_at=0 WHERE kind='notify'"); db.conn().commit()
jobs.run_due()
c2 = data.get_conv(cv["id"])
ok(len(SENT) == n0 and c2["draft"] and "TH123" in c2["draft"] and "shipped:LZ-9001" in c2["notified"], f"shipped notice as draft {c2['draft']}")
ok(chat.notify(oid, "shipped") is None, "notified only once")
# ---- 夜间提示 ----
data.save_settings({"night_mode": "notice", "night_from": "00:00", "night_to": "23:59"})
ok(shopcfg.is_night(), "night now")
n0 = len(SENT)
chat.on_buyer(cv["id"])
ok(len(SENT) == n0 + 1 and "นอกเวลา" in SENT[-1]["txt"], "night notice sent")
chat.on_buyer(cv["id"])
ok(len(SENT) == n0 + 1, "night notice once per night")
data.save_settings({"night_mode": "off"})
# ---- 只人工：不排任务 ----
shopcfg.save("LZ-TH", mode="off")
ok(chat.on_buyer(cv["id"]) is None, "mode off: no AI job")
shopcfg.save("LZ-TH", mode="draft")
# ---- 分店知识库 ----
data.kb_save({"q": "ส่งฟรีไหม", "a": "LZ ส่งฟรี", "shop": "LZ-TH"})
data.kb_save({"q": "ส่งฟรีไหม ร้านอื่น", "a": "อื่น", "shop": "OTHER"})
hits = [k["a"] for k in brain.kb_match("ส่งฟรีไหม", 10, shop="LZ-TH")]
ok("LZ ส่งฟรี" in hits and "อื่น" not in hits, "shop knowledge base")
# ---- 质检 ----
qa = C.post(f"/api/cs/convs/{cv['id']}/qa").get_json()
ok(qa.get("score") and abs(qa["score"] - 4.0) < 0.01, f"QA scored {qa}")
# ---- 工作台 ----
d = C.get("/api/cs/dashboard").get_json()
ok(d["today"]["ai_sent"] >= 1 and d["today"]["human_sent"] >= 1 and any(s["shop"] == "LZ-TH" and s["api"] and s["mode"] == "draft" for s in d["shops"]),
   f"dashboard {d['today']}")
ok(d["qa"] and "jobs" in d and isinstance(d["agents"], list), "dashboard sections")
r = C2.post("/api/cs/shops/mode", json={"shop": "LZ-TH", "mode": "auto"})
ok(r.status_code == 403, "staff cannot change shop mode")
# ---- 接口没开通：记错误，下一轮等 5 分钟 ----
def bad(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    raise RuntimeError("Lazada /im/session/list 出错：AppWithoutApiPermission")
LZ.LazadaConnector._call = bad
r = jobs.poll_all(force=True)
ok("Permission" in r["LZ-TH"] and "Permission" in data.cursor_get(sid)["last_error"], "permission error shown")
ok(jobs.poll_all() == {}, "backs off after error")
# ---- v2.47.2：单独的聊天应用（In-house IM Chat）：聊天接口用它的 key / token；单独授权，token 存在 im_* ----
LZ.LazadaConnector._call = fake
integrations.save_shop({"id": sid, "platform": "lazada", "name": "LZ-TH", "enabled": True,
                        "creds": {"im_app_key": "imk", "im_app_secret": "ims"}})
WHO = []
def fake2(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    WHO.append((path, self.creds.get("app_key"), self.creds.get("access_token")))
    if path == "/auth/token/create":
        return {"code": "0", "access_token": "imtok", "refresh_token": "imref", "expires_in": 86400}
    return fake(self, path, params, base, token, method, files)
LZ.LazadaConnector._call = fake2
jobs._state["errors"].clear()
r = jobs.poll_all(force=True)
ok("没授权" in str(r.get("LZ-TH")), f"IM app not authorized yet → clear message {r}")
ok("client_id=imk" in integrations.authorize_url(sid, "https://x/", "im"), "authorize url uses the chat app key")
integrations.exchange_code(sid, "https://www.google.com/?code=abc", "im")
cr = integrations.get_shop_raw(sid)["creds"]
ok(cr["im_access_token"] == "imtok" and cr["access_token"] == "t" and cr["im_refresh_token"] == "imref", "chat token stored separately")
WHO.clear(); jobs._state["errors"].clear()
jobs.poll_all(force=True)
ok(WHO and all(w[1] == "imk" and w[2] == "imtok" for w in WHO if w[0].startswith("/im/")), f"IM calls signed with the chat app {WHO[:2]}")
ok(integrations.list_shops()[0]["creds"].get("im_access_token") == "******", "chat token hidden in the shop list")
# ---- v2.47.3：数据应用（财务 / 评价 / 退货 / 店铺指标）走单独的应用；没授权给清楚的提示；主应用的接口不受影响 ----
LZ.LazadaConnector._call = REAL_CALL
SEEN = []
class _Resp:
    def __init__(self, d): self.d = d
    def json(self): return self.d
def fake_get(url, params=None, timeout=None, **k):
    SEEN.append((url.split("/rest", 1)[1], params.get("app_key"), params.get("access_token")))
    return _Resp({"code": "0", "data": {}})
LZ.requests.get = fake_get
cn = LZ.LazadaConnector({"app_key": "k", "app_secret": "s", "access_token": "t", "data_app_key": "dk", "data_app_secret": "ds"})
try:
    cn._call("/finance/transaction/details/get", {})
    ok(False, "data app not authorized should raise")
except RuntimeError as e:
    ok("数据应用还没授权" in str(e), f"data app hint {e}")
cn.creds.update(data_access_token="dt", data_token_expire=time.time() + 99999)
cn._call("/finance/transaction/details/get", {}); cn._call("/orders/get", {})
ok(SEEN == [("/finance/transaction/details/get", "dk", "dt"), ("/orders/get", "k", "t")], f"routing {SEEN}")
# ---- 解析 ----
ok(lazada_im.parse({"message_id": "x", "from_account_type": "1", "content": json.dumps({"itemId": 5, "title": "Cat"}), "template_id": "10006"})["kind"] == "item", "item parsed")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
