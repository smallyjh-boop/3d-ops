"""聊天：发消息（接口渠道直接发；扩展 / 手工的记下来）、人工接管 / 交回 AI、分配客服、快捷回复、
新买家消息进来后按店铺 AI 模式处理、主动提醒、客服工作台汇总（v2.46）。"""
import json
import random
import re
import time

from . import brain, channels, data, erp_link, service, shopcfg

# 自动标签（不花 AI，消息一进来就按关键词打；AI 写草稿时还会补更细的标签）
INTENT_TAG = {"price": "询价", "wholesale": "询价", "order_status": "催单", "stock": "询价", "complaint": "售后", "refund": "售后",
              "change_order": "售后", "custom": "定制", "thanks": "闲聊", "product": "咨询"}
AUTO_TAGS = ["询价", "催单", "售后", "定制", "闲聊", "咨询"]


def _note(cid, text, user=""):
    data.add_msg(cid, "note", text, "system", user, kind="sys")


# ---------------- 发消息 ----------------
def send(cid, text="", user="", kind="text", extra=None, source="manual", force=False):
    """发一条消息给买家。接口渠道：直接发到平台；其它渠道：记下来（员工在平台 / 扩展里发）。
    别人接管着的会话，不是 force 就拒绝（防止两个人同时回）。返回会话。"""
    c = data.get_conv(cid)
    if not c:
        raise ValueError("会话不存在")
    me = (user or "").strip()
    if c.get("mode") == "human" and c.get("taken_by") and me and c["taken_by"] != me and not force and source != "auto":
        raise PermissionError(f"{c['taken_by']} 正在处理这个会话")
    text = (text or "").strip()
    if kind == "item" and extra and not text:
        text = "[สินค้า] " + (extra.get("name") or "")
    if kind == "order" and extra and not text:
        text = "[คำสั่งซื้อ] " + (extra.get("order_no") or "")
    if kind == "image" and not text:
        text = "[รูปภาพ]"
    if not text:
        raise ValueError("消息是空的")
    ch = channels.of(c)
    ext_id, status = None, ""
    if ch:
        try:
            ext_id = ch.send(c, {"kind": kind, "text": text, "extra": extra or {}}) or None
            status = "sent"
        except Exception as e:  # noqa: BLE001  发不出去：记成失败，界面可以重发
            data.add_msg(cid, "seller", text, source=source, user=me, kind=kind, extra=extra, status="failed")
            mid = data.messages(cid, 1)[-1]["id"]
            data.set_msg(mid, error=str(e)[:300])
            raise RuntimeError(f"发送失败：{e}") from e
    if c.get("mode") == "human" and c.get("taken_by") == me:
        data.update_conv(cid, taken_at=time.time())          # 接管的人在回：接管时间往后延
    return service.record_sent(cid, text, me, source=source, kind=kind, extra=extra, ext_id=ext_id, status=status)


def resend(mid, user=""):
    m = next((x for x in [dict(r) for r in _db().execute("SELECT * FROM cs_msg WHERE id=?", (mid,))]), None)
    if not m or m.get("status") != "failed":
        raise ValueError("这条消息不用重发")
    _db().execute("DELETE FROM cs_msg WHERE id=?", (mid,))
    _db().commit()
    extra = json.loads(m["extra"]) if m.get("extra") else None
    return send(m["conv_id"], m["text"], user, kind=m.get("kind") or "text", extra=extra, force=True)


def _db():
    from core import db
    return db.conn()


def can_send(c):
    return channels.of(c) is not None


# ---------------- 接管 / 分配 ----------------
def takeover(cid, user):
    data.update_conv(cid, mode="human", taken_by=user, taken_at=time.time(), assigned=user)
    _note(cid, f"{user} 接管了会话（AI 不再自动回复）", user)
    return service.conv_full(cid)


def release(cid, user=""):
    data.update_conv(cid, mode="", taken_by=None, taken_at=None)
    _note(cid, "已交回 AI" + (f"（{user}）" if user else ""), user)
    return service.conv_full(cid)


def assign(cid, agent, user=""):
    data.update_conv(cid, assigned=agent or None)
    _note(cid, f"分配给 {agent}" if agent else "取消分配", user)
    return service.conv_full(cid)


def sweep_takeover(now=None):
    """接管后太久没动静的会话自动交回 AI。返回交回了几个。"""
    try:
        mins = float(data.settings().get("takeover_min") or 0)
    except ValueError:
        mins = 30
    if mins <= 0:
        return 0
    now = now or time.time()
    n = 0
    for r in _db().execute("SELECT id, taken_at FROM cs_conv WHERE mode='human' AND taken_at IS NOT NULL AND taken_at<?",
                           (now - mins * 60,)).fetchall():
        data.update_conv(r["id"], mode="", taken_by=None, taken_at=None)
        _note(r["id"], f"接管超过 {int(mins)} 分钟没有回复，已自动交回 AI")
        n += 1
    return n


# ---------------- 新买家消息进来 ----------------
def auto_tags(cid, text):
    tag = INTENT_TAG.get(brain.rule_intent(text))
    if not tag:
        return
    c = data.get_conv(cid)
    tags = c.get("tag_list") or []
    if tag not in tags:
        data.update_conv(cid, tags=",".join([tag] + tags)[:300])


def on_buyer(cid):
    """有新的买家消息（接口拉到 / 扩展推上来）：打标签、夜间提示、按 AI 模式排后台任务。"""
    c = data.get_conv(cid)
    if not c:
        return None
    pend = []
    for m in reversed(data.messages(cid, 30)):
        if m["role"] == "seller":
            break
        if m["role"] == "buyer":
            pend.insert(0, m["text"])
    auto_tags(cid, " ".join(pend) or " ".join([m["text"] for m in data.messages(cid, 30) if m["role"] == "buyer"][-3:]))
    s = data.settings()
    if shopcfg.is_night() and s.get("night_mode") == "notice" and can_send(c) and c.get("mode") != "human":
        last = c.get("night_noticed_at") or 0
        if time.time() - last > 10 * 3600:
            try:
                send(cid, s.get("night_text") or "", "AI", source="auto")
                data.update_conv(cid, night_noticed_at=time.time())
            except Exception:  # noqa: BLE001
                pass
    mode = shopcfg.mode_of(c)
    if mode == "off":
        return None
    from . import jobs
    return jobs.enqueue("auto" if mode == "auto" and can_send(c) else "draft", cid)


def run_ai(cid, auto=False):
    """后台任务：写草稿；auto 时能自动发的直接发。返回 {sent, reason}。"""
    c = data.get_conv(cid)
    if not c or c.get("status") == "closed":
        return {"sent": False, "reason": "会话已结束"}
    msgs = data.messages(cid, 5)
    if not msgs or msgs[-1]["role"] != "buyer" and not any(m["role"] == "buyer" for m in msgs[-3:]):
        return {"sent": False, "reason": "已经回复过了"}
    full = service.make_draft(cid)
    if not auto or shopcfg.mode_of(full) != "auto":
        return {"sent": False, "reason": "只出草稿"}
    d = service.auto_decision(full)
    if not d["ok"]:
        return {"sent": False, "reason": d["reason"]}
    send(cid, full["draft"], "AI", source="auto")
    return {"sent": True, "reason": ""}


# ---------------- 快捷回复（可带变量）----------------
VARS = {"买家名": "buyer", "订单号": "order_no", "运单号": "tracking", "预计发货日": "ship_date", "店铺名": "shop",
        "buyer": "buyer", "order_no": "order_no", "tracking": "tracking", "ship_date": "ship_date", "shop": "shop"}
DEFAULT_QUICK = [
    ("问候", "สวัสดีค่ะคุณ{买家名} ยินดีให้บริการค่ะ สนใจสินค้าชิ้นไหนสอบถามได้เลยนะคะ 😊", "常用"),
    ("已发货", "คำสั่งซื้อ {订单号} จัดส่งแล้วค่ะ เลขพัสดุ {运单号} ค่ะ 🙏", "物流"),
    ("制作中", "สินค้าของคุณ{买家名}กำลังผลิตอยู่ค่ะ คาดว่าจะจัดส่งภายใน {预计发货日} นะคะ", "物流"),
    ("请稍等", "รบกวนรอสักครู่นะคะ แอดมินกำลังตรวจสอบให้ค่ะ 🙏", "常用"),
    ("感谢好评", "ขอบคุณมากนะคะ ถ้าพอใจสินค้าฝากรีวิวให้ร้านด้วยนะคะ 💕", "售后"),
    ("请拍照", "ขออภัยด้วยนะคะ รบกวนถ่ายรูป/วิดีโอสินค้าที่ได้รับส่งมาให้แอดมินดูหน่อยค่ะ จะรีบดูแลให้ค่ะ", "售后"),
]


def quick_list(shop=""):
    c = _db()
    if not c.execute("SELECT COUNT(*) FROM cs_quick").fetchone()[0]:
        now = time.time()
        for i, (t, x, cat) in enumerate(DEFAULT_QUICK):
            c.execute("INSERT INTO cs_quick(title, text, cat, sort, created_at, username) VALUES(?,?,?,?,?,?)", (t, x, cat, i, now, "system"))
        c.commit()
    rows = [dict(r) for r in c.execute("SELECT * FROM cs_quick ORDER BY sort, uses DESC, id")]
    return [r for r in rows if not shop or (r.get("shop") or "") in ("", shop)]


def quick_save(d, user=""):
    t, x = (d.get("title") or "").strip(), (d.get("text") or "").strip()
    if not x:
        raise ValueError("回复内容不能为空")
    c = _db()
    vals = (t[:60] or x[:20], x[:2000], (d.get("shop") or "")[:100], (d.get("cat") or "")[:30], int(d.get("sort") or 0))
    if d.get("id"):
        c.execute("UPDATE cs_quick SET title=?, text=?, shop=?, cat=?, sort=? WHERE id=?", (*vals, int(d["id"])))
    else:
        c.execute("INSERT INTO cs_quick(title, text, shop, cat, sort, created_at, username) VALUES(?,?,?,?,?,?,?)", (*vals, time.time(), user))
    c.commit()
    return quick_list()


def quick_delete(qid):
    c = _db()
    c.execute("DELETE FROM cs_quick WHERE id=?", (qid,))
    c.commit()


def _ship_date(o):
    import datetime as dt
    t = (o or {}).get("ship_by")
    try:
        t = float(t)
    except (TypeError, ValueError):
        t = time.time() + 86400 * float(erp_link.default_ship_days() or 2)
    return dt.datetime.fromtimestamp(t).strftime("%d/%m")


def values_of(c):
    o = c.get("order") if "order" in c else (erp_link.order_brief(c["order_id"]) if c.get("order_id") else None)
    return {"buyer": c.get("buyer") or "", "order_no": (o or {}).get("order_no") or c.get("order_no") or "",
            "tracking": (o or {}).get("tracking_no") or "", "ship_date": _ship_date(o), "shop": c.get("shop") or ""}


def fill(text, c):
    """把 {买家名} {订单号} {运单号} {预计发货日} {店铺名} 换成这个会话的值；没有值的变量换成空。"""
    v = values_of(c)
    return re.sub(r"\{([^{}]{1,12})\}", lambda m: v.get(VARS.get(m.group(1).strip(), ""), m.group(0)) if m.group(1).strip() in VARS else m.group(0), text)


def quick_use(qid, cid):
    c = _db()
    r = c.execute("SELECT * FROM cs_quick WHERE id=?", (qid,)).fetchone()
    if not r:
        raise ValueError("快捷回复不存在")
    c.execute("UPDATE cs_quick SET uses=COALESCE(uses,0)+1 WHERE id=?", (qid,))
    c.commit()
    return fill(r["text"], data.get_conv(cid))


# ---------------- 主动提醒（订单发货 / 超时没发）----------------
def conv_of_order(o):
    """订单对应的会话：关联了这个订单的；没有就同平台同买家最近的。"""
    r = _db().execute("SELECT id FROM cs_conv WHERE order_id=? ORDER BY updated_at DESC LIMIT 1", (o["id"],)).fetchone()
    if not r and o.get("buyer"):
        r = _db().execute("SELECT id FROM cs_conv WHERE platform=? AND buyer=? ORDER BY updated_at DESC LIMIT 1",
                          (o.get("platform") or "", o["buyer"])).fetchone()
    return data.get_conv(r["id"]) if r else None


def notify(order_id, what):
    """what：shipped / delayed。按店铺模式：自动模式 + 能直接发 → 发；否则放成草稿等人点发送。返回 'sent' / 'draft' / None。"""
    s = data.settings()
    if str(s.get("notify_" + what, "1")) != "1":
        return None
    o = erp_link.order_brief(order_id)
    if not o:
        return None
    c = conv_of_order(o)
    if not c or c.get("status") == "closed":
        return None
    done = set((c.get("notified") or "").split(","))
    key = f"{what}:{o['order_no']}"
    if key in done:
        return None
    if not c.get("order_id"):
        data.update_conv(c["id"], order_id=o["id"], order_no=o["order_no"])
        c = data.get_conv(c["id"])
    text = fill(s.get("tpl_" + what) or "", dict(c, order=o))
    if not text.strip():
        return None
    data.update_conv(c["id"], notified=",".join([x for x in done if x] + [key])[-500:])
    if shopcfg.mode_of(c) == "auto" and can_send(c):
        try:
            send(c["id"], text, "AI", source="auto")
            return "sent"
        except Exception:  # noqa: BLE001  发不出去就放草稿
            pass
    data.update_conv(c["id"], draft=text, draft_zh=("订单已发货，告诉买家运单号" if what == "shipped" else "订单超时未发，安抚买家"),
                     draft_at=time.time())
    _note(c["id"], "主动提醒：" + ("订单已发货" if what == "shipped" else "订单超过 48 小时还没发货") + "，草稿已写好，确认后发送")
    return "draft"


def check_delayed():
    """超过 48 小时还没发货、有会话的订单：主动安抚（每个订单只一次）。"""
    n = 0
    since = time.time() - 14 * 86400
    for r in _db().execute("SELECT DISTINCT order_id FROM cs_conv WHERE order_id IS NOT NULL AND updated_at>?", (since,)).fetchall():
        o = erp_link.order_brief(r["order_id"])
        if o and o.get("已超过48小时还没发货") and o.get("status") in ("to_ship", "pending", "processing"):
            n += notify(o["id"], "delayed") is not None
    return n


# ---------------- 质检抽查 ----------------
QA_PROMPT = """你是网店客服主管，给下面这段客服对话打分（1–5 分）：accuracy 回答准不准（有没有乱说价格日期、答非所问），
attitude 态度和语气，speed 回复速度（看时间）。再用中文写一句评语（哪里好、哪里要改）。只回 JSON：
{"accuracy":4,"attitude":5,"speed":3,"comment":"…"}"""


def qa_one(cid, user="AI"):
    msgs = data.messages(cid, 60)
    lines = [f"[{time.strftime('%H:%M', time.localtime(m['created_at']))}] {'买家' if m['role'] == 'buyer' else '客服'}"
             f"{'(AI)' if m.get('source') == 'auto' else ''}: {m['text'][:300]}" for m in msgs if m["role"] in ("buyer", "seller")]
    if not any(m["role"] == "seller" for m in msgs):
        return None
    from core import ai_copy
    raw = ai_copy.call(brain._cs_cfg(), QA_PROMPT, "\n".join(lines)[-6000:])
    try:
        j = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    except (AttributeError, ValueError):
        return None
    sc = [float(j.get(k) or 0) for k in ("accuracy", "attitude", "speed")]
    c = data.get_conv(cid)
    agent = next((m.get("username") for m in reversed(msgs) if m["role"] == "seller" and m.get("source") != "auto"), "") or "AI"
    db = _db()
    db.execute("INSERT INTO cs_qa(conv_id, day, score, accuracy, attitude, speed, comment, agent, shop, by_ai, created_at, username) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (cid, time.strftime("%Y-%m-%d"), round(sum(sc) / 3, 2), *sc, str(j.get("comment") or "")[:500],
                                                  agent, c.get("shop") or "", 1, time.time(), user))
    db.commit()
    return dict(db.execute("SELECT * FROM cs_qa ORDER BY id DESC LIMIT 1").fetchone())


def qa_daily(now=None):
    """每天抽几个昨天有回复的会话让 AI 打分（今天已经抽过就不再抽）。返回抽了几个。"""
    try:
        n = int(float(data.settings().get("qa_daily") or 0))
    except ValueError:
        n = 0
    if n <= 0:
        return 0
    now = now or time.time()
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    db = _db()
    if db.execute("SELECT 1 FROM cs_qa WHERE day=? AND by_ai=1 AND username='AI'", (today,)).fetchone():
        return 0
    t1 = time.mktime(time.strptime(today, "%Y-%m-%d"))
    ids = [r[0] for r in db.execute("SELECT DISTINCT conv_id FROM cs_msg WHERE role='seller' AND created_at>=? AND created_at<?",
                                    (t1 - 86400, t1))]
    done = 0
    for cid in random.sample(ids, min(n, len(ids))):
        try:
            done += qa_one(cid) is not None
        except Exception:  # noqa: BLE001  AI 出错：明天再抽
            break
    if not done:          # 没有可抽的也记一条，今天不再试
        db.execute("INSERT INTO cs_qa(conv_id, day, score, comment, by_ai, created_at, username) VALUES(0,?,NULL,'',1,?,'AI')", (today, now))
        db.commit()
    return done


def qa_list(days=14, limit=50):
    return [dict(r) for r in _db().execute("SELECT q.*, c.buyer FROM cs_qa q LEFT JOIN cs_conv c ON c.id=q.conv_id "
                                           "WHERE q.conv_id>0 AND q.created_at>? ORDER BY q.id DESC LIMIT ?",
                                           (time.time() - days * 86400, int(limit)))]


# ---------------- 客服工作台（汇总）----------------
def _day0(t=None):
    lt = time.localtime(t or time.time())
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def dashboard(user):
    from . import crm
    shops = crm.allowed(user)
    me = (user or {}).get("username") or ""
    now, d0 = time.time(), _day0()
    db = _db()
    inshop = (lambda s: shops is None or (s or "") in shops)
    convs = [c for c in data.list_convs("active", limit=1000) if inshop(c.get("shop"))]
    unreplied = [c for c in convs if (c.get("last") or {}).get("role") == "buyer" and c["status"] == "open"]
    w = lambda c: c.get("wait_min") or 0
    # 今天：新会话、首次响应、AI / 人工回复条数
    rows = db.execute("SELECT m.conv_id, m.role, m.source, m.username, m.created_at, c.shop FROM cs_msg m JOIN cs_conv c ON c.id=m.conv_id "
                      "WHERE m.created_at>=? AND m.role IN ('buyer','seller') ORDER BY m.conv_id, m.id", (d0,)).fetchall()
    rows = [r for r in rows if inshop(r["shop"])]
    first_wait, pend, seen = [], {}, set()
    by_agent = {}
    ai_sent = human_sent = 0
    for r in rows:
        if r["role"] == "buyer":
            pend.setdefault(r["conv_id"], r["created_at"])
            continue
        if r["source"] == "auto":
            ai_sent += 1
        else:
            human_sent += 1
            a = crm.agent_of(r["username"]) or "?"
            by_agent.setdefault(a, {"sent": 0, "waits": []})["sent"] += 1
        t0 = pend.pop(r["conv_id"], None)
        if t0:
            wmin = (r["created_at"] - t0) / 60
            if r["conv_id"] not in seen:
                first_wait.append(wmin)
                seen.add(r["conv_id"])
            if r["source"] != "auto":
                by_agent[crm.agent_of(r["username"]) or "?"]["waits"].append(wmin)
    avg = (lambda xs: round(sum(xs) / len(xs), 1) if xs else None)
    new_convs = sum(1 for c in db.execute("SELECT shop FROM cs_conv WHERE created_at>=?", (d0,)) if inshop(c["shop"]))
    buyers_today = len({r["conv_id"] for r in rows if r["role"] == "buyer"})
    urgent = sorted([c for c in convs if c.get("needs_human") or w(c) >= 15], key=lambda c: (-int(bool(c.get("needs_human"))), -w(c)))[:12]
    # 店铺
    shop_names = sorted({c.get("shop") or "" for c in convs} | {s["name"] for s in erp_link.api_shops()} | set(shopcfg._all()))
    curs = {r["shop_id"]: dict(r) for r in db.execute("SELECT * FROM cs_cursor")}
    api = {s["name"]: s for s in erp_link.api_shops()}
    shops_out = []
    for name in shop_names:
        if not inshop(name) or (not name and not any(not (c.get("shop") or "") for c in convs)):
            continue
        cfg = shopcfg.get(name)
        a = api.get(name)
        cur = curs.get(a["id"]) if a else None
        shops_out.append({"shop": name, "mode": cfg["mode"], "im": cfg.get("im", True), "api": bool(a),
                          "unreplied": sum(1 for c in unreplied if (c.get("shop") or "") == name),
                          "open": sum(1 for c in convs if (c.get("shop") or "") == name),
                          "last_ok": (cur or {}).get("last_ok"), "last_error": (cur or {}).get("last_error") or ""})
    # 客服
    names = crm.agent_names()
    load = {}
    for c in convs:
        who = c.get("taken_by") or c.get("assigned")
        if who:
            load[who] = load.get(who, 0) + 1
    agents = [{"agent": a, "name": names.get(a, a), "open": load.get(a, 0), "sent": v["sent"], "avg_min": avg(v["waits"])}
              for a, v in by_agent.items()]
    for a, n in load.items():
        if a not in by_agent:
            agents.append({"agent": a, "name": names.get(a, a), "open": n, "sent": 0, "avg_min": None})
    agents.sort(key=lambda x: -x["sent"])
    recs = crm.record_counts(shops)
    after = [r for r in crm.records(status="open", shops=shops, limit=50) if r["kind"] in ("aftersales", "complaint")][:8]
    qa = qa_list(7, 8)
    brief = lambda c: {"id": c["id"], "buyer": c.get("buyer") or "", "shop": c.get("shop") or "", "platform": c.get("platform") or "",
                       "wait_min": c.get("wait_min"), "needs_human": bool(c.get("needs_human")), "reason": c.get("human_reason") or "",
                       "text": ((c.get("last") or {}).get("text") or "")[:80], "taken_by": c.get("taken_by") or "",
                       "assigned": c.get("assigned") or ""}
    return {
        "now": now, "me": me,
        "today": {"new": new_convs, "buyers": buyers_today, "unreplied": len(unreplied),
                  "wait5": sum(1 for c in unreplied if w(c) >= 5), "wait15": sum(1 for c in unreplied if w(c) >= 15),
                  "first_avg": avg(first_wait), "ai_sent": ai_sent, "human_sent": human_sent,
                  "human_needed": sum(1 for c in convs if c.get("needs_human")),
                  "mine": sum(1 for c in convs if me and me in (c.get("taken_by"), c.get("assigned")))},
        "urgent": [brief(c) for c in urgent],
        "shops": shops_out, "modes": {k: list(v) for k, v in shopcfg.MODES.items()},
        "agents": agents,
        "leads_due": [{"id": c["id"], "buyer": c.get("buyer") or "", "shop": c.get("shop") or "", "stage": c.get("lead_stage"),
                       "value": c.get("lead_value"), "note": c.get("follow_note") or ""}
                      for c in data.leads(due_only=True) if inshop(c.get("shop"))][:8],
        "aftersales": [{"id": r["id"], "kind": r["kind_zh"], "text": r["text"][:80], "buyer": r.get("buyer") or "", "conv_id": r.get("conv_id"),
                        "overdue": r.get("overdue")} for r in after],
        "records": recs,
        "perf": data.perf(7),
        "unanswered": [{"id": u["id"], "q": (u.get("question_zh") or u["question"])[:80], "count": u["count"]} for u in data.unanswered()[:6]],
        "qa": qa, "qa_avg": avg([q["score"] for q in qa if q.get("score")]),
        "night": shopcfg.is_night(),
    }
