"""客服模块的网页接口（Flask Blueprint）。

/api/cs/...     软件界面用（登录后）
/api/v1/cs/...  浏览器扩展用（API 密钥，在 系统 → 设置 → AI 与对接 → API 密钥 里新建）
"""
import base64
import re
import time

from flask import Blueprint, g, jsonify, request

from . import brain, crm, data, service

bp = Blueprint("cs", __name__)


def _u():
    return (getattr(g, "user", None) or {}).get("username", "")


def _err(msg, code=400):
    return jsonify({"error": str(msg)}), code


def _wrap(fn):
    def inner(*a, **kw):
        try:
            return fn(*a, **kw)
        except ValueError as e:
            return _err(e)
        except Exception as e:  # noqa: BLE001  AI 接口出错等
            from core.ai_copy import AIError
            if isinstance(e, AIError):
                return _err(f"AI 出错：{e}")
            raise
    inner.__name__ = fn.__name__
    return inner


# ---------------- 软件界面 ----------------
@bp.get("/api/cs/convs")
@_wrap
def convs():
    sh = crm.allowed(g.get("user"))
    a = request.args
    return jsonify({"convs": data.list_convs(a.get("status", "active"), a.get("q", ""), shop=a.get("shop", ""), agent=a.get("agent", ""), shops=sh),
                    "stats": data.stats(sh), "platforms": service.PLATFORMS, "shops": sh if sh is not None else crm.known_shops(), "agents": crm.active_agents(),
                    "alert_minutes": float(data.settings().get("alert_minutes") or 0)})


@bp.post("/api/cs/convs")
@_wrap
def conv_new():
    b = request.get_json(force=True) or {}
    c = data.create_conv(buyer=b.get("buyer", ""), platform=b.get("platform", ""))
    if b.get("text"):
        role = b.get("role") or "buyer"
        service.add_messages(c["id"], [{"from": role, "text": b["text"]}], "paste", _u())
    if b.get("order_no"):
        service.do_action(c["id"], {"type": "link_order", "order_no": b["order_no"]}, _u())
    return jsonify(service.conv_full(c["id"]))


@bp.get("/api/cs/convs/<int:cid>")
@_wrap
def conv_get(cid):
    data.update_conv(cid, unread=0)
    return jsonify(service.conv_full(cid))


@bp.post("/api/cs/convs/<int:cid>")
@_wrap
def conv_update(cid):
    b = request.get_json(force=True) or {}
    data.update_conv(cid, **{k: b[k] for k in ("buyer", "platform", "status", "assigned", "shop") if k in b})
    if any(k in b for k in ("buyer", "platform", "shop")):      # 换了买家 / 店铺：重新对应客户档案
        c = data.get_conv(cid)
        c["customer_id"] = None
        crm.link_conv(c)
    return jsonify(service.conv_full(cid))


@bp.delete("/api/cs/convs/<int:cid>")
@_wrap
def conv_delete(cid):
    data.delete_conv(cid)
    return jsonify({"ok": True})


@bp.post("/api/cs/convs/<int:cid>/messages")
@_wrap
def conv_msg(cid):
    b = request.get_json(force=True) or {}
    msgs = b.get("messages") or [{"from": b.get("role") or "buyer", "text": b.get("text")}]
    n = service.add_messages(cid, msgs, b.get("source") or "paste", _u())
    out = service.conv_full(cid)
    out["added"] = n
    return jsonify(out)


@bp.delete("/api/cs/messages/<int:mid>")
@_wrap
def msg_delete(mid):
    data.delete_msg(mid)
    return jsonify({"ok": True})


@bp.post("/api/cs/convs/<int:cid>/screenshot")
@_wrap
def conv_shot(cid):
    f = request.files.get("image")
    if not f:
        return _err("请选择截图")
    n = service.from_screenshot(cid, f.read(), _u())
    out = service.conv_full(cid)
    out["added"] = n
    return jsonify(out)


@bp.post("/api/cs/convs/<int:cid>/draft")
@_wrap
def conv_draft(cid):
    b = request.get_json(force=True) or {}
    return jsonify(service.make_draft(cid, b.get("instruction") or "", _u()))


@bp.post("/api/cs/convs/<int:cid>/sent")
@_wrap
def conv_sent(cid):
    b = request.get_json(force=True) or {}
    return jsonify(service.record_sent(cid, b.get("text"), _u(), b.get("source") or "manual"))


@bp.post("/api/cs/convs/<int:cid>/action")
@_wrap
def conv_action(cid):
    c, msg = service.do_action(cid, request.get_json(force=True) or {}, _u())
    c["message"] = msg
    return jsonify(c)


@bp.post("/api/cs/quote")
@_wrap
def quote():
    b = request.get_json(force=True) or {}
    return jsonify(brain.quote(b.get("items") or []))


@bp.post("/api/cs/translate")
@_wrap
def translate():
    """翻译。to=th + conv_id：中文打字 → 客服口吻的泰语（实时翻译，v2.22）。"""
    b = request.get_json(force=True) or {}
    conv = service.conv_full(int(b["conv_id"])) if b.get("conv_id") else None
    return jsonify({"text": brain.translate(b.get("text") or "", b.get("to") or "zh", conv, b.get("polite", True))})


@bp.get("/api/cs/kb/pending")
@_wrap
def kb_pending():
    return jsonify({"pending": data.kb_pending(), "unanswered": data.unanswered()})


@bp.post("/api/cs/kb/<int:kid>/review")
@_wrap
def kb_review(kid):
    b = request.get_json(force=True) or {}
    data.kb_review(kid, bool(b.get("ok")), b, _u())
    return jsonify({"ok": True})


@bp.post("/api/cs/unanswered/<int:uid>")
@_wrap
def unanswered_answer(uid):
    """给 AI 答不上来的问题写答案 → 加进知识库；ignore=true 忽略。"""
    b = request.get_json(force=True) or {}
    if b.get("ignore"):
        data.unanswered_done(uid, None)
        return jsonify({"ok": True})
    k = data.kb_save({"q": b.get("q"), "a": b.get("a"), "a_zh": b.get("a_zh") or "", "tags": b.get("tags") or ""}, _u())
    data.unanswered_done(uid, k["id"])
    return jsonify({"ok": True, "kb": k})


@bp.get("/api/cs/leads")
@_wrap
def leads():
    rows = data.leads(request.args.get("stage") or "", request.args.get("due") == "1")
    for r in rows:
        r.pop("analysis", None)
    return jsonify({"leads": rows, "stages": data.LEAD_STAGES})


@bp.get("/api/cs/weekly")
@_wrap
def weekly():
    from . import report
    if request.args.get("last") == "1":
        r = report.last()
        if r:
            return jsonify(dict(r, text=report.as_text(r)))
    r = report.weekly(with_ai=request.args.get("ai") == "1")
    return jsonify(dict(r, text=report.as_text(r)))


@bp.post("/api/cs/weekly/send")
@_wrap
def weekly_send():
    from . import mailer, report
    r = report.weekly()
    report.save_last(r)
    to = mailer.send(f"📊 客服周报 {r['from']} ~ {r['to']}", report.as_text(r))
    return jsonify({"ok": True, "to": to})


@bp.post("/api/cs/mail/test")
@_wrap
def mail_test():
    """用填的（还没保存也行）发信设置发一封测试邮件。密码留空 = 用保存过的。"""
    from . import mailer
    b = request.get_json(force=True) or {}
    s = data.settings()
    for k, v in b.items():
        if k in data.DEFAULT_SETTINGS and (v or k not in data.SECRET):
            s[k] = v
    to = mailer.send("✅ 3D 运营管理系统：邮件通知测试", "收到这封邮件说明设置正确。客服紧急事件、超时、跟进提醒和周报会发到这些邮箱。", s=s)
    return jsonify({"ok": True, "to": to})


@bp.get("/api/cs/kb")
@_wrap
def kb():
    return jsonify({"kb": [k for k in data.kb_list() if (k.get("status") or "active") != "pending"], "examples": data.examples(200),
                    "settings": data.public_settings(), "intents": brain.INTENTS, "presets_missing": data.presets_missing(),
                    "tiers": data.tiers(), "tier_names": data.TIER_NAMES, "pending": data.kb_pending(), "unanswered": data.unanswered()})


@bp.post("/api/cs/kb")
@_wrap
def kb_save():
    return jsonify(data.kb_save(request.get_json(force=True) or {}, _u()))


@bp.post("/api/cs/kb/presets")
@_wrap
def kb_presets():
    n = data.seed_presets(_u())
    return jsonify({"added": n})


@bp.delete("/api/cs/kb/<int:kid>")
@_wrap
def kb_del(kid):
    data.kb_delete(kid)
    return jsonify({"ok": True})


@bp.delete("/api/cs/examples/<int:eid>")
@_wrap
def ex_del(eid):
    data.delete_example(eid)
    return jsonify({"ok": True})


@bp.post("/api/cs/settings")
@_wrap
def settings_save():
    b = request.get_json(force=True) or {}
    if "smtp_host" in b:                       # v2.24：smtp@gmail.com 这类写法自动纠正成 smtp.gmail.com
        from . import mailer
        b["smtp_host"] = mailer.fix_host(b["smtp_host"], b.get("smtp_user") or b.get("smtp_from") or data.settings().get("smtp_user") or "")
        if str(b.get("smtp_port") or "").strip() == "465":
            b["smtp_tls"] = "ssl"
        elif str(b.get("smtp_port") or "").strip() in ("587", "25", "2525") and b.get("smtp_tls") == "ssl":
            b["smtp_tls"] = "starttls"
    data.save_settings(b)
    return jsonify(data.public_settings())


@bp.get("/api/cs/stats")
@_wrap
def stats():
    return jsonify(data.stats())


@bp.get("/api/cs/perf")
@_wrap
def perf():
    return jsonify({"perf": data.perf(int(request.args.get("days") or 7)), "overdue": data.overdue()[:50]})


@bp.post("/api/cs/alert/test")
@_wrap
def alert_test():
    from . import alerts
    b = request.get_json(force=True) or {}
    alerts.send_telegram("✅ 3D 运营管理系统：客服提醒测试成功", b.get("tg_token"), b.get("tg_chat"))
    return jsonify({"ok": True})


@bp.post("/api/cs/alert/chat-id")
@_wrap
def alert_chat_id():
    from . import alerts
    b = request.get_json(force=True) or {}
    cid, name = alerts.find_chat_id(b.get("tg_token") or data.settings().get("tg_token"))
    return jsonify({"chat_id": cid, "name": name})


@bp.get("/api/cs/extension/info")
@_wrap
def ext_info():
    """v2.27：设置 → 组件与插件：扩展最新版本、哪些员工在用哪个版本。"""
    from core import integrations
    return jsonify({"latest": integrations.EXT_LATEST,
                    "in_use": [{"name": n, "version": v} for n, v in sorted(integrations.EXT_SEEN.items())]})


@bp.get("/api/cs/extension.zip")
@_wrap
def ext_zip():
    """下载浏览器扩展（Chrome：扩展程序 → 开发者模式 → 加载已解压的扩展程序）。"""
    import io
    import os
    import zipfile
    from flask import send_file
    from core.config import BASE_DIR
    d = os.path.join(BASE_DIR, "extension")
    if not os.path.isdir(d):
        return _err("没有找到 extension 文件夹", 404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in sorted(os.listdir(d)):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                z.write(p, "listing-helper-cs-extension/" + n)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="listing-helper-cs-extension.zip", mimetype="application/zip")


# ---------------- 浏览器扩展 ----------------
def _platform_of(url):
    u = (url or "").lower()
    for k in ("lazada", "shopee", "tiktok"):
        if k in u:
            return k
    return "manual"


@bp.get("/api/v1/cs/ping")
@_wrap
def x_ping():
    s = data.settings()
    return jsonify({"ok": True, "user": _u(), "stats": data.stats(),
                    "auto_allowed": str(s.get("auto_send", "1")) == "1"})


# ---------------- v2.24：多店铺实时跟踪 + 提醒 ----------------
PRESENCE = {}          # (密钥名, 标签页 id) → {shop, platform, host, unread, buyers, title, at, user}


def _presence_list(max_age=90):
    now = time.time()
    for k in [k for k, v in PRESENCE.items() if now - v["at"] > 600]:
        PRESENCE.pop(k, None)
    return sorted([dict(v, key=f"{k[0]}|{k[1]}") for k, v in PRESENCE.items() if now - v["at"] <= max_age],
                  key=lambda x: (-int(x.get("unread") or 0), x.get("shop") or ""))


@bp.post("/api/v1/cs/presence")
@_wrap
def x_presence():
    """扩展每个标签页每 15 秒报一次：哪个店铺、会话列表里有几个未读、哪几个买家。ERP 和其他标签页用来提醒。"""
    b = request.get_json(force=True) or {}
    tab = str(b.get("tab") or "")[:40]
    if not tab:
        return _err("没有 tab")
    PRESENCE[(_u(), tab)] = {"shop": str(b.get("shop") or "")[:60], "platform": str(b.get("platform") or "")[:20],
                             "host": str(b.get("host") or "")[:80], "unread": max(0, min(999, int(b.get("unread") or 0))),
                             "buyers": [str(x)[:40] for x in (b.get("buyers") or [])][:5], "auto": bool(b.get("auto")),
                             "at": time.time(), "user": _u()}
    return jsonify({"ok": True, "tabs": _presence_list(), "stats": data.stats()})


@bp.get("/api/cs/alerts")
@_wrap
def alerts_view():
    """ERP 顶部提醒：待回复的会话（最新几条）、需要人工、超时，以及各店铺浏览器里还没读的消息。"""
    sh = crm.allowed(g.get("user"))
    rows = data.list_convs("open", limit=30, shops=sh)
    latest = []
    for r in rows:
        last = r.get("last") or {}
        if last.get("role") != "buyer":
            continue
        latest.append({"id": r["id"], "buyer": r.get("buyer") or "", "shop": r.get("shop") or "", "platform": r.get("platform") or "",
                       "text": (last.get("text") or "")[:80], "at": last.get("created_at"), "wait_min": r.get("wait_min"),
                       "needs_human": bool(r.get("needs_human"))})
    tabs = [t for t in _presence_list() if sh is None or (t.get("shop") or "") in sh]
    return jsonify({"stats": data.stats(sh), "latest": latest[:8], "tabs": tabs, "records": crm.record_counts(sh),
                    "unread_in_browser": sum(int(t.get("unread") or 0) for t in tabs)})


NOT_BUYER = re.compile(r"^\s*(messages?|chats?|inbox|im|แชท|ข้อความ|消息|聊天|会话|客服|customer service|ลูกค้า|buyer|chat with buyers?|"
                       r"(my )?last orders?|my orders?|orders?|recent orders?|products?|recommend(ed|ations)?|vouchers?|coupons?|"
                       r"quick ?replies|คำสั่งซื้อ(ล่าสุด|ของฉัน)?|สินค้า(แนะนำ)?|โค้ดส่วนลด|订单|最近订单|商品|推荐|优惠券)\s*$", re.I)


@bp.post("/api/v1/cs/capture")
@_wrap
def x_capture():
    """扩展读到的对话：{url, platform?, shop?, buyer?, order_no?, messages?: [{from, text}], screenshot?: dataURL, draft?: bool}
    同一个 平台+店铺+买家 是同一个会话；只加新消息；有新的买家消息就生成回复草稿。"""
    b = request.get_json(force=True) or {}
    platform = b.get("platform") or _platform_of(b.get("url"))
    buyer = (b.get("buyer") or "").strip()
    if NOT_BUYER.match(buyer):        # v2.47.1：旧版扩展把聊天页的标签（My Last Order、Messages…）当成买家名字
        buyer = ""
    shop = (b.get("shop") or "").strip()
    shot = b.get("screenshot")
    raw = None
    if shot:
        m = re.match(r"data:image/\w+;base64,(.*)", shot, re.S)
        raw = base64.b64decode(m.group(1) if m else shot)
    if not buyer and raw:
        # 先看截图认出买家是谁（同一个买家对应同一个会话）
        r = brain.read_screenshot(raw)
        buyer = r["buyer"] or ""
        ext = f"{platform}:{shop}:{buyer}" if buyer else None
        c = service.ensure_conv(platform, buyer, shop, ext, "extension", r.get("order_no") or b.get("order_no") or "")
        n = service.add_messages(c["id"], r["messages"], "screenshot", _u(), replace_tail=True)
    else:
        ext = f"{platform}:{shop}:{buyer}" if buyer else None
        c = service.ensure_conv(platform, buyer, shop, ext, "extension", b.get("order_no") or "")
        if raw:
            n = service.from_screenshot(c["id"], raw, _u())
        else:
            n = service.add_messages(c["id"], b.get("messages") or [], "extension", _u(), replace_tail=True)
    c = data.get_conv(c["id"])
    msgs = data.messages(c["id"])
    last = next((m for m in reversed(msgs) if m["role"] in ("buyer", "seller")), None)
    if n and last and last["role"] == "buyer":
        from . import chat
        chat.auto_tags(c["id"], last["text"])         # v2.46：询价 / 催单 / 售后 / 定制 / 闲聊
    need_draft = last and last["role"] == "buyer" and (n > 0 or not c.get("draft")) and b.get("draft", True)
    if need_draft:
        out = service.make_draft(c["id"], "", _u())
    else:
        out = service.conv_full(c["id"])
    out["added"] = n
    out["drafted"] = bool(need_draft)
    out["auto"] = service.auto_decision(out) if need_draft else {"ok": False, "reason": "没有新的买家消息"}
    return jsonify(out)


@bp.post("/api/v1/cs/translate")
@_wrap
def x_translate():
    """扩展：中文打字 → 泰语（实时翻译）。"""
    b = request.get_json(force=True) or {}
    conv = service.conv_full(int(b["conv_id"])) if b.get("conv_id") else None
    return jsonify({"text": brain.translate(b.get("text") or "", b.get("to") or "th", conv, b.get("polite", True))})


@bp.post("/api/v1/cs/draft")
@_wrap
def x_draft():
    b = request.get_json(force=True) or {}
    return jsonify(service.make_draft(int(b["conv_id"]), b.get("instruction") or "", _u()))


@bp.post("/api/v1/cs/sent")
@_wrap
def x_sent():
    b = request.get_json(force=True) or {}
    return jsonify(service.record_sent(int(b["conv_id"]), b.get("text"), _u(), "auto" if b.get("auto") else "extension"))


@bp.post("/api/v1/cs/action")
@_wrap
def x_action():
    b = request.get_json(force=True) or {}
    c, msg = service.do_action(int(b.pop("conv_id")), b, _u())
    c["message"] = msg
    return jsonify(c)


@bp.get("/api/v1/cs/conv/<int:cid>")
@_wrap
def x_conv(cid):
    return jsonify(service.conv_full(cid))


# ---------------- v2.24：登记中心、客户档案、客服报表、账号与店铺 ----------------
def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _rec_args():
    a = request.args
    return dict(kind=a.get("kind", ""), status=a.get("status", ""), shop=a.get("shop", ""), agent=a.get("agent", ""), q=a.get("q", ""),
                date_from=_f(a.get("from")), date_to=_f(a.get("to")), shops=crm.allowed(g.get("user")))


@bp.get("/api/cs/records")
@_wrap
def records_list():
    sh = crm.allowed(g.get("user"))
    return jsonify({"records": crm.records(**_rec_args()), "counts": crm.record_counts(sh), "kinds": crm.KINDS, "kinds_th": crm.KINDS_TH,
                    "shops": sh if sh is not None else crm.known_shops(), "agents": _agents_brief()})


@bp.get("/api/cs/records/export")
@_wrap
def records_export():
    import os
    import tempfile
    from flask import send_file
    path = os.path.join(tempfile.mkdtemp(), "登记中心.xlsx")
    crm.export_xlsx(crm.records(limit=5000, **_rec_args()), path)
    return send_file(path, as_attachment=True, download_name=f"cs_records_{time.strftime('%Y%m%d')}.xlsx")


def _rec_create(b):
    cid = b.get("conv_id")
    if cid:
        c = data.get_conv(int(cid))
        if not c:
            raise ValueError("会话不存在")
        if not crm.shop_ok(g.get("user"), c.get("shop")):
            raise ValueError("这个店铺不归你管")
    return crm.add_record(b.get("kind") or "note", b.get("text") or "", _u(), conv_id=int(cid) if cid else None,
                          customer_id=b.get("customer_id"), due_at=b.get("due_at"), priority=b.get("priority") or 0,
                          platform=b.get("platform") or "", shop=b.get("shop") or "", buyer=b.get("buyer") or "")


@bp.post("/api/cs/records")
@_wrap
def records_add():
    return jsonify(_rec_create(request.get_json(force=True) or {}))


@bp.post("/api/cs/records/<int:rid>")
@_wrap
def records_update(rid):
    r = crm.get_record(rid)
    if not crm.shop_ok(g.get("user"), r.get("shop")):
        return _err("这个店铺不归你管", 403)
    b = request.get_json(force=True) or {}
    return jsonify(crm.update_record(rid, _u(), **{k: b[k] for k in ("text", "status", "result", "due_at", "priority", "kind") if k in b}))


@bp.delete("/api/cs/records/<int:rid>")
@_wrap
def records_delete(rid):
    r = crm.get_record(rid)
    u = g.get("user") or {}
    if u.get("role") != "owner" and r.get("created_by") != _u():
        return _err("只能删除自己登记的（老板可以删所有的）", 403)
    crm.delete_record(rid)
    return jsonify({"ok": True})


@bp.get("/api/cs/customers/<int:cid>")
@_wrap
def customer_get(cid):
    cu = crm.customer(cid)
    if not crm.shop_ok(g.get("user"), cu.get("shop")):
        return _err("这个店铺不归你管", 403)
    return jsonify(cu)


@bp.post("/api/cs/customers/<int:cid>")
@_wrap
def customer_update(cid):
    b = request.get_json(force=True) or {}
    c = db_conn()
    if "tags" in b:
        c.execute("UPDATE cs_customer SET tags=? WHERE id=?", (str(b["tags"] or "")[:300], cid))
    c.commit()
    return jsonify(crm.customer(cid))


def db_conn():
    from core import db
    return db.conn()


def _period():
    a = request.args
    now = time.time()
    d0 = crm._day_start(now)
    p = a.get("period", "today")
    t0, t1 = {"today": (d0, now + 1), "yesterday": (d0 - 86400, d0), "7d": (d0 - 6 * 86400, now + 1),
              "30d": (d0 - 29 * 86400, now + 1)}.get(p, (d0, now + 1))
    return _f(a.get("from")) or t0, _f(a.get("to")) or t1


@bp.get("/api/cs/report")
@_wrap
def report_get():
    t0, t1 = _period()
    u = g.get("user") or {}
    r = crm.report(t0, t1, crm.allowed(u), None if u.get("role") == "owner" else None)
    if u.get("role") != "owner":                  # 员工只看到自己的绩效（店铺数据照常）
        me = crm.agent_of(u.get("username"))
        r["agents"] = [x for x in r["agents"] if x["agent"] == me]
    return jsonify(r)


@bp.get("/api/cs/report/export")
@_wrap
def report_export():
    import os
    import tempfile
    from flask import send_file
    from openpyxl import Workbook
    t0, t1 = _period()
    u = g.get("user") or {}
    r = crm.report(t0, t1, crm.allowed(u))
    if u.get("role") != "owner":
        r["agents"] = [x for x in r["agents"] if x["agent"] == crm.agent_of(u.get("username"))]
    wb = Workbook()
    ws = wb.active
    ws.title = "客服绩效"
    ws.append(["客服", "接待会话", "回复条数", "自动回复", "首次响应(分钟)", "平均响应(分钟)", "超时次数", "AI 草稿直接采用率%", "新登记", "完成登记"])
    for a in r["agents"]:
        ws.append([a["name"], a["convs"], a["sent"], a["auto"], a["first_reply_min"], a["avg_reply_min"], a["over_alert"], a["adopt_pct"],
                   a["records_added"], a["records_done"]])
    ws2 = wb.create_sheet("店铺")
    ws2.append(["店铺", "平台", "咨询会话", "买家消息", "回复条数", "客户数", "新客户", "老客户", "关联订单", "新线索", "平均响应(分钟)", "结束时未回复"])
    for s in r["shops"]:
        ws2.append([s["shop"], "、".join(s["platforms"]), s["convs"], s["buyer_msgs"], s["sent"], s["customers"], s["new_customers"],
                    s["returning"], s["with_order"], s["leads"], s["avg_reply_min"], s["unanswered"]])
    path = os.path.join(tempfile.mkdtemp(), "cs_report.xlsx")
    wb.save(path)
    return send_file(path, as_attachment=True, download_name=f"cs_report_{time.strftime('%Y%m%d', time.localtime(t0))}.xlsx")


@bp.get("/api/cs/workbench")
@_wrap
def workbench_get():
    return jsonify(crm.workbench(g.get("user") or {}))


def _agents_brief():
    names = crm.agent_names()
    return [{"agent": k, "name": v} for k, v in names.items()]


@bp.get("/api/cs/agents")
@_wrap
def agents_get():
    """客服账号与店铺：ERP 里能用客服的账号 + 扩展密钥，各自负责哪些店铺（老板看）。"""
    from core import db
    from core import integrations
    rows = []
    for r in db.conn().execute("SELECT username, display_name, role FROM users WHERE role IN ('owner','listing') ORDER BY role DESC, username"):
        rows.append({"agent": r["username"], "name": r["display_name"] or r["username"], "role": r["role"], "kind": "user",
                     "shops": crm.shops_of(r["username"])})
    users = {x["agent"] for x in rows}
    for k in integrations.list_keys():
        if k.get("scope") in ("cs", "full") and k["name"] not in users:
            rows.append({"agent": k["name"], "name": k["name"], "role": "", "kind": "key", "shops": crm.shops_of(k["name"]),
                         "ext_version": k.get("ext_version") or ""})
    return jsonify({"agents": rows, "shops": crm.known_shops()})


@bp.post("/api/cs/agents/shops")
@_wrap
def agents_set_shops():
    if (g.get("user") or {}).get("role") != "owner":
        return _err("只有老板能分配店铺", 403)
    b = request.get_json(force=True) or {}
    return jsonify({"agent": b.get("agent"), "shops": crm.set_shops(b.get("agent") or "", b.get("shops") or [])})


@bp.post("/api/v1/cs/records")
@_wrap
def x_records_add():
    """扩展：给这个会话 / 买家登记备注、待办、售后、投诉、特殊需求。"""
    return jsonify(_rec_create(request.get_json(force=True) or {}))


from . import chat_api  # noqa: E402,F401  v2.46 聊天页 / 工作台的接口（同一个 Blueprint）
