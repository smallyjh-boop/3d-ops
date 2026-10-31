# v2.49：Lazada 平台通知（官方账号的 HTML 通知）单独放、不算统计、不写草稿；打开会话在 Lazada 上标已读；
# 买家消息后台翻成中文；对买家不提生产 / 3D 打印（默认话术、规则、快捷回复、禁用词、自动发送拦截、旧默认迁移）；周报按界面语言
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, sys, shutil, sqlite3, json, time, re
D = T + "/m_cs249"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
import app as A
from core import db, integrations, ai_copy
from core.connectors import lazada as LZ
from modules.cs.logic import data, chat, jobs, brain, service, notice, presets, report
from modules.cs.logic.channels import lazada_im
from modules.cs import module as csmod
db.create_user("boss", "secret123", "owner", "Boss")
C = A.app.test_client(); C.post("/api/auth/login", json={"username": "boss", "password": "secret123"})
data.init()

# ---- 旧默认迁移：没改过的旧政策 / 规则 / 禁用词 / 话术 / 快捷回复换成新版 ----
dbc = db.conn()
for k in ("ship_policy", "tpl_delayed", "forbidden_words", "playbook", "custom_policy"):
    dbc.execute("INSERT OR REPLACE INTO cs_settings(k, v) VALUES(?,?)", (k, data.OLD_SETTINGS[k][-1]))
dbc.execute("INSERT OR REPLACE INTO cs_settings(k, v) VALUES('persona', 'my own style')")
old_pre = next(p for p in presets.PRESETS if p.get("old") and "ผลิต" in p["old"][-1])
key = old_pre["q"].split("|")[0].strip()
kid = dbc.execute("SELECT id FROM cs_kb WHERE q LIKE ?", (key + "%",)).fetchone()["id"]
dbc.execute("UPDATE cs_kb SET a=? WHERE id=?", (old_pre["old"][-1], kid))
dbc.execute("DELETE FROM cs_quick")
dbc.commit()
chat.quick_list()
dbc.execute("UPDATE cs_quick SET title='制作中', text=? WHERE title='备货中'", (list(chat.OLD_QUICK)[0],)); dbc.commit()
data.init()
s = data.settings()
ok(all(s[k] == data.DEFAULT_SETTINGS[k] for k in ("ship_policy", "tpl_delayed", "forbidden_words", "playbook", "custom_policy")) and s["persona"] == "my own style",
   "unchanged old defaults migrated, edited ones kept")
ok(dbc.execute("SELECT a FROM cs_kb WHERE id=?", (kid,)).fetchone()["a"] == old_pre["a"], "unchanged old preset answer replaced")
q = chat.quick_list()
ok(not any("ผลิต" in x["text"] for x in q) and any(x["title"] == "备货中" for x in q), "old quick reply replaced")

# ---- 默认里没有对买家说生产 / 打印的词 ----
bad = []
for p in presets.PRESETS:
    if brain.production_hit(p["a"]):
        bad.append(p["a"][:40])
    if re.search(r"生产|打印|耗材|制作", p["a_zh"]):
        bad.append(p["a_zh"][:40])
for k in ("ship_policy", "custom_policy", "tpl_delayed", "tpl_shipped", "night_text"):
    if brain.production_hit(data.DEFAULT_SETTINGS[k].split("对买家")[0]):
        bad.append(k)
for t, x, _c in chat.DEFAULT_QUICK:
    if brain.production_hit(x) or "制作" in t:
        bad.append(t)
ok(not bad, f"no production words in buyer-facing defaults {bad}")
ok("3D 打印" not in brain.SYSTEM.split("必须遵守")[0] and "不要提生产" in brain.SYSTEM, "system prompt: no production talk")
for w in ("ผลิต", "พิมพ์ 3D", "3D print", "กำลังพิมพ์", "生产", "打印"):
    ok(brain.forbidden_hit(f"ตอนนี้ {w} อยู่ค่ะ") != "", f"forbidden word blocks: {w}")
ok(brain.forbidden_hit("ผลิตภัณฑ์นี้ราคา 199 บาทค่ะ", {"forbidden_words": ""}) == "", "ผลิตภัณฑ์ (product) is fine")
ok(brain.forbidden_hit("กำลังผลิตค่ะ", {"forbidden_words": ""}) == "ผลิต", "production words blocked even if settings were emptied")

# ---- AI 回复里有生产 → 转人工，不自动发 ----
def fake_ai(cfg, system, user, **k):
    if "翻译" in system:
        return json.dumps({"text": "这个多少钱"})
    if "主管" in system:
        return json.dumps({"points": ["多补知识库"], "points_th": ["เพิ่มคลังความรู้"]})
    return json.dumps({"lang": "th", "intent": "price", "reply": "สินค้ากำลังผลิตอยู่ค่ะ ราคา 199 บาท", "reply_zh": "", "needs_human": False,
                       "confidence": 0.99, "summary_zh": "问价格"})
ai_copy.call = fake_ai
cv = service.ensure_conv("lazada", "Mali", "LZ-TH", "x:1", "manual")
data.add_msg(cv["id"], "buyer", "ราคาเท่าไหร่คะ")
full = service.make_draft(cv["id"])
ok(full["needs_human"] and "生产" in full["human_reason"] and not service.auto_decision(full)["ok"], f"production reply → human, not auto ({full['human_reason']})")
data.update_conv(cv["id"], draft="ส่งของพรุ่งนี้ค่ะ กำลังพิมพ์ 3D อยู่", needs_human=0)
ok("生产" in service.auto_decision(service.conv_full(cv["id"]))["reason"], "auto_decision blocks production words in the draft")
data.delete_conv(cv["id"])

# ---- 平台通知：官方账号的 HTML 消息 ----
HTML = ('<img width="750" height="300" src="https://img.lazcdn.com/g/tps/sem_seller_engagement_push/banner.jpg"/>'
        '<br/>แคมเปญ 11.11 เปิดรับสมัครแล้ว <a href="https://sellercenter.lazada.co.th/campaign?x=1&amp;y=2">คลิก</a>'
        '<script>alert(1)</script>')
ok(notice.notice_text(HTML) and notice.looks_html(HTML), "official html sample detected")
pl = notice.plain(HTML)
ok("<" not in pl and "🖼" in pl and "คลิก" in pl, f"plain text preview: {pl}")
ok(notice.official_name("L****************l") and notice.official_name("Lazada Seller Center") and not notice.official_name("Mali") and not notice.official_name("Lazy cat"), "official names")
ok(notice.session_is_system({"title": "Shop fan", "tags": ["official"]}) and notice.session_is_system({"title": "x", "tags": "SYSTEM,foo"})
   and not notice.session_is_system({"title": "Mali", "tags": []}), "session tags official/system")

NOW = time.time() * 1000
SESS = [{"session_id": "S1", "buyer_id": "B1", "title": "Mali", "last_message_time": str(NOW - 1000)},
        {"session_id": "OFF", "buyer_id": "L1", "title": "L****************l", "tags": ["official"], "last_message_time": str(NOW - 900)},
        {"session_id": "OFF2", "buyer_id": "L2", "title": "Promo", "last_message_time": str(NOW - 800)}]
MSGS = {"S1": [{"message_id": "m1", "from_account_type": "1", "send_time": str(NOW - 5000), "template_id": "1", "content": json.dumps({"txt": "มีสีชมพูไหมคะ"})}],
        "OFF": [{"message_id": "o1", "from_account_type": "1", "send_time": str(NOW - 4000), "template_id": "1", "content": json.dumps({"txt": HTML})}],
        "OFF2": [{"message_id": "p1", "from_account_type": "1", "send_time": str(NOW - 3000), "template_id": "1", "content": json.dumps({"txt": HTML})}]}
READS = []
def fake(self, path, params, base=LZ.API, token=True, method="GET", files=None):
    if path == "/im/session/list":
        return {"code": "0", "success": "true", "data": {"session_list": SESS, "has_more": "false"}}
    if path == "/im/message/list":
        lst = sorted(MSGS.get(params["session_id"], []), key=lambda m: -float(m["send_time"]))
        return {"code": "0", "success": "true", "data": {"message_list": lst, "has_more": "false"}}
    if path == "/im/session/read":
        READS.append(dict(params))
        return {"code": "0", "success": "true", "data": {}}
    return {"code": "0", "success": "true", "data": {"message_id": "x"}}
LZ.LazadaConnector._call = fake
sid = integrations.save_shop({"platform": "lazada", "name": "LZ-TH", "enabled": True,
                              "creds": {"app_key": "k", "app_secret": "s", "access_token": "t", "refresh_token": "r"}})
sid = sid["id"] if isinstance(sid, dict) else sid
data.save_settings({"alert_minutes": "1"})
r = jobs.poll_all(force=True)
buyer = data.find_conv("lazada", f"im:{sid}:S1"); off = data.find_conv("lazada", f"im:{sid}:OFF"); off2 = data.find_conv("lazada", f"im:{sid}:OFF2")
ok(r == {"LZ-TH": 1}, f"only the buyer conversation counts as new {r}")
ok(off["kind"] == "system" and off2["kind"] == "system" and buyer["kind"] in ("", None), "official tag + HTML notice → kind=system")
ok(data.messages(off["id"])[0]["text"] == json.loads(MSGS["OFF"][0]["content"])["txt"], "server keeps the raw text")
todo = [x["kind"] for x in db.conn().execute("SELECT kind FROM cs_jobs WHERE conv_id IN (?,?) AND status='todo'", (off["id"], off2["id"]))]
ok(not todo and not off.get("tags") and not off.get("needs_human"), f"no AI job / tags for notices {todo}")
# 买家等了超过 1 分钟；通知也「等了」但不算
db.conn().execute("UPDATE cs_msg SET created_at=? WHERE conv_id IN (?,?,?)", (time.time() - 600, buyer["id"], off["id"], off2["id"])); db.conn().commit()
ib = C.get("/api/cs/inbox?status=active").get_json()
ok([c["id"] for c in ib["convs"]] == [buyer["id"]] and ib["counts"]["unreplied"] == 1 and ib["counts"]["system"] == 2, f"inbox counts {ib['counts']}")
ib = C.get("/api/cs/inbox?status=system").get_json()
ok({c["id"] for c in ib["convs"]} == {off["id"], off2["id"]} and "<" not in ib["convs"][0]["last"]["text"], "notice tab lists notices with plain preview")
ok([x["id"] for x in data.overdue()] == [buyer["id"]] and data.stats()["open"] == 1, "overdue / stats skip notices")
d = C.get("/api/cs/dashboard").get_json()
ok(d["today"]["unreplied"] == 1 and d["today"]["buyers"] == 1 and d["notices"] == 2 and len(d["series"]["buyers"]) == 7, f"dashboard skips notices {d['today']}")
todos = []
csmod._todo(lambda *a, **k: todos.append(a[0]))
ok(todos and all(f":{buyer['id']}:" in t for t in todos), f"to-dos only for the buyer {todos}")
ok(C.post(f"/api/cs/convs/{off['id']}/send", json={"text": "hi"}).status_code == 400, "cannot reply to a notice")
ok(C.post(f"/api/cs/convs/{off['id']}/draft", json={}).status_code == 400, "no AI draft for a notice")
ok(C.get(f"/api/cs/convs/{off['id']}").get_json()["can_send"] is False, "notice is read-only")
# 全部标已读（Lazada 上也标）
READS.clear()
r = C.post("/api/cs/notices/read").get_json()
ok(r["n"] >= 1 and C.get("/api/cs/inbox?status=active").get_json()["counts"]["system"] == 0, "mark all notices read")
ok(any(x["session_id"] in ("OFF", "OFF2") for x in READS), f"notices marked read on Lazada {READS}")
# 打开买家会话 = Lazada 上标已读
READS.clear()
ok(data.get_conv(buyer["id"])["unread"] >= 1, "buyer unread before open")
C.get(f"/api/cs/convs/{buyer['id']}")
for _ in range(30):
    if READS:
        break
    time.sleep(0.1)
ok(READS and READS[0]["session_id"] == "S1" and READS[0]["last_read_message_id"] == "m1" and data.get_conv(buyer["id"])["unread"] == 0, f"open → read on Lazada {READS}")

# ---- 启动时重新分类：以前收进来、被当成买家的通知 ----
old = service.ensure_conv("lazada", "L*********l", "LZ-TH", "im:old:1", "manual")
data.add_msg(old["id"], "buyer", HTML)
data.update_conv(old["id"], needs_human=1, human_reason="售后", tags="售后", draft="ขอโทษค่ะ")
dbc.execute("UPDATE cs_conv SET kind='' WHERE id=?", (old["id"],)); dbc.commit()
jobs.enqueue("draft", old["id"])
data.init()
o2 = data.get_conv(old["id"])
ok(o2["kind"] == "system" and not o2["needs_human"] and not o2["tags"] and not o2["draft"], "startup re-classifies old notices and clears wrong flags")
ok(not db.conn().execute("SELECT 1 FROM cs_jobs WHERE conv_id=? AND status='todo'", (old["id"],)).fetchone(), "queued AI job removed")

# ---- 买家消息自动翻成中文（后台任务）----
MSGS["S1"].append({"message_id": "m2", "from_account_type": "1", "send_time": str(NOW + 1000), "template_id": "1", "content": json.dumps({"txt": "ราคาเท่าไหร่คะ"})})
SESS[0]["last_message_time"] = str(NOW + 1000)
jobs.poll_all(force=True)
ok(db.conn().execute("SELECT 1 FROM cs_jobs WHERE conv_id=? AND kind='tr' AND status='todo'", (buyer["id"],)).fetchone(), "translate job queued")
db.conn().execute("UPDATE cs_jobs SET run_at=0 WHERE kind='tr'"); db.conn().commit()
jobs.run_due()
zh = [m["text_zh"] for m in data.messages(buyer["id"]) if m["role"] == "buyer"]
ok(zh[-1] == "这个多少钱", f"buyer message translated {zh}")
chat._tr_times[:] = [time.time()] * chat.TR_PER_MIN
db.conn().execute("UPDATE cs_msg SET text_zh=NULL WHERE conv_id=?", (buyer["id"],)); db.conn().commit()
ok(chat.translate_pending(buyer["id"]) == 0 and db.conn().execute("SELECT 1 FROM cs_jobs WHERE conv_id=? AND kind='tr' AND status='todo'", (buyer["id"],)).fetchone(),
   "rate limited → retried later")
chat._tr_times.clear()

# ---- 知识库：老板改过的回答里还有生产 / 打印 → 标出来 ----
data.kb_save({"q": "ส่งกี่วัน", "a": "สินค้าผลิตตามออเดอร์ค่ะ"}, "boss")
kb = C.get("/api/cs/kb").get_json()["kb"]
ok(any(k["prod_hit"] == "ผลิต" for k in kb) and all(not k["prod_hit"] for k in kb if k.get("username") == "system"), "KB entries with production words flagged")

# ---- 周报按界面语言 ----
data.unanswered_add("ส่งต่างประเทศได้ไหม", "能寄国外吗", buyer["id"])
w = C.get("/api/cs/weekly?ai=1&lang=th").get_json()
ok(not re.search(r"[一-鿿]", w["text"]) and "ส่งต่างประเทศ" in w["text"] and "เพิ่มคลังความรู้" in w["text"], f"Thai weekly report has no Chinese: {w['text'][:200]}")
w = C.get("/api/cs/weekly?last=0&lang=zh").get_json()
ok("客服周报" in w["text"] and "能寄国外吗" in w["text"], "Chinese weekly report")

# ---- 推荐商品卡片（买家提到产品编号）----
pid = db.conn().execute("SELECT id FROM products LIMIT 1").fetchone() if db.conn().execute("SELECT name FROM sqlite_master WHERE name='products'").fetchone() else None
from core import store
pl_ = store.list_products()
if pl_:
    data.add_msg(buyer["id"], "buyer", f"ขอดู {pl_[0]['id']} หน่อยค่ะ")
    sg = C.get(f"/api/cs/convs/{buyer['id']}/suggest").get_json()["items"]
    ok(sg and sg[0]["id"] == pl_[0]["id"], f"product suggestion {[x['id'] for x in sg]}")
print("ERRORS", E_)
sys.exit(1 if E_ else 0)
