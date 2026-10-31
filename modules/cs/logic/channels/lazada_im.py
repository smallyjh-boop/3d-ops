"""Lazada 聊天接口渠道（v2.46）。

拉消息：/im/session/list 从新到旧翻，直到会话的最后消息时间早于上次拉到的时间；有变化的会话再拉 /im/message/list。
每个店铺的进度记在 cs_cursor（cursor = 上次拉到的最后消息时间，毫秒）。第一次拉只拉最近 3 天。
消息内容 content 是 JSON 字符串：文字 {"txt":…}；图片 {"imgUrl":…}；商品 {"itemId", "title", "iconUrl", "price"…}；订单 {"orderId"…}。
"""
import json
import time

from .. import data, erp_link, notice

CHANNEL = "lazada_im"
FIRST_DAYS = 3
TPL = {"text": 1, "image": 3, "item": 10006, "order": 10007}


def _ms(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def parse(m, buyer_id=""):
    """接口的一条消息 → {from, text, kind, extra, ext_id, ts}；系统消息返回 None。"""
    try:
        c = json.loads(m.get("content") or "{}") if isinstance(m.get("content"), str) else (m.get("content") or {})
    except ValueError:
        c = {"txt": str(m.get("content"))}
    tpl = str(m.get("template_id") or m.get("type") or "1")
    fat = str(m.get("from_account_type") or "")
    if fat:
        who = "seller" if fat == "2" else "buyer"        # 1 买家；2 卖家；其它（平台 / 系统账号）放在对方那边
    else:
        who = "buyer" if buyer_id and str(m.get("from_account_id")) == str(buyer_id) else "seller"
    txt = str(c.get("txt") or c.get("text") or "").strip()
    kind, extra = "text", None
    if c.get("imgUrl") or c.get("img_url") or tpl == "3":
        kind, extra = "image", {"url": c.get("imgUrl") or c.get("img_url") or "", "w": c.get("width"), "h": c.get("height")}
        txt = txt or "[รูปภาพ]"
    elif c.get("itemId") or c.get("item_id") or tpl == "10006":
        kind = "item"
        extra = {"item_id": c.get("itemId") or c.get("item_id"), "name": c.get("title") or c.get("itemTitle") or "",
                 "image": c.get("iconUrl") or c.get("pic") or "", "price": c.get("price") or c.get("actionPrice") or ""}
        txt = txt or ("[สินค้า] " + extra["name"]).strip()
    elif c.get("orderId") or c.get("order_id") or tpl == "10007":
        kind = "order"
        extra = {"order_no": str(c.get("orderId") or c.get("order_id") or ""), "status": c.get("status") or ""}
        txt = txt or f"[คำสั่งซื้อ] {extra['order_no']}"
    if not txt and kind == "text":       # v2.49：平台通知的内容可能在 content / desc / title 里（常是 HTML）
        for k in ("content", "desc", "summary", "title", "body"):
            if isinstance(c.get(k), str) and c[k].strip():
                txt = c[k].strip()
                break
    if not txt:
        return None
    if str(m.get("auto_reply") or "").lower() in ("true", "1"):
        who = "seller"
    return {"from": who, "text": txt, "kind": kind, "extra": extra, "ext_id": str(m.get("message_id") or ""),
            "ts": _ms(m.get("send_time")) / 1000 or None}


def _conv_for(shop, s):
    sid = str(s.get("session_id") or "")
    c = data.find_conv("lazada", f"im:{shop['id']}:{sid}")
    if not c:
        from .. import service
        c = service.ensure_conv("lazada", s.get("title") or "", shop["name"], f"im:{shop['id']}:{sid}", CHANNEL)
        data.update_conv(c["id"], shop_id=shop["id"], avatar=s.get("head_url") or "")
        c = data.get_conv(c["id"])
    elif s.get("head_url") and c.get("avatar") != s.get("head_url"):
        c = data.update_conv(c["id"], avatar=s["head_url"])
    if c.get("kind") != notice.KIND and notice.session_is_system(s):     # v2.49：Lazada 官方账号 / 系统通知
        notice.mark(c["id"])
        c = data.get_conv(c["id"])
    return c


def _session_id(conv):
    return str(conv.get("ext_id") or "").split(":", 2)[-1]


def poll(shop, conn=None):
    """拉一个店铺的新消息。返回 [有新买家消息的会话 id]。"""
    cur = data.cursor_get(shop["id"])
    since = _ms(cur.get("cursor")) or (time.time() - FIRST_DAYS * 86400) * 1000
    changed, newest = [], since
    with (erp_link.ShopConn(shop["id"]) if conn is None else _Same(conn)) as cn:
        start, last_sid, pages = None, None, 0
        sessions = []
        while pages < 20:
            d = cn.im_sessions(start, 20, last_sid)
            lst = d.get("session_list") or []
            pages += 1
            stop = False
            for s in lst:
                t = _ms(s.get("last_message_time"))
                if t <= since:
                    stop = True
                    break
                sessions.append(s)
            if stop or not lst or str(d.get("has_more")).lower() != "true":
                break
            start, last_sid = d.get("next_start_time"), d.get("last_session_id")
        for s in sessions:
            c = _conv_for(shop, s)
            got = _messages(cn, c, s, since)
            newest = max(newest, _ms(s.get("last_message_time")))
            if got:
                changed.append(c["id"])
    data.cursor_set(shop["id"], newest, ok=True)
    return changed


class _Same:
    def __init__(self, c):
        self.c = c

    def __enter__(self):
        return self.c

    def __exit__(self, *a):
        return False


def _messages(cn, conv, s, since):
    """拉这个会话 since 之后的消息（从新到旧翻页），按时间顺序写进去。返回新增的买家消息条数。"""
    sid = _session_id(conv)
    out, start, last_mid = [], None, None
    for _ in range(10):
        d = cn.im_messages(sid, start, 20, last_mid)
        lst = d.get("message_list") or []
        stop = False
        for m in lst:
            if _ms(m.get("send_time")) <= since:
                stop = True
                break
            out.append(m)
        if stop or not lst or str(d.get("has_more")).lower() != "true":
            break
        start, last_mid = d.get("next_start_time"), d.get("last_message_id")
    out.sort(key=lambda m: _ms(m.get("send_time")))
    nb = 0
    if out and conv.get("kind") != notice.KIND:
        other = [m for m in out if str(m.get("from_account_type") or "") != "2"]
        if other and all(notice.msg_is_system(m) for m in other):      # 对方不是买家（系统账号）
            notice.mark(conv["id"])
            conv = data.get_conv(conv["id"])
    for m in out:
        p = parse(m, s.get("buyer_id"))
        if not p:
            continue
        if p["from"] == "seller" and data.claim_sent(conv["id"], p["text"], p["ext_id"]):
            continue                 # 我们从 ERP 发的那条（发送时接口没回编号）：对上了，不重复记
        if data.add_msg(conv["id"], p["from"], p["text"], source="platform", ext_id=p["ext_id"], ts=p["ts"],
                        kind=p["kind"], extra=p["extra"], user="lazada" if p["from"] == "seller" else ""):
            nb += p["from"] == "buyer"
    if out:
        data.update_conv(conv["id"], ext_last_id=str(out[-1].get("message_id") or ""))
    if nb and conv.get("kind") != notice.KIND and notice.conv_is_system(conv, data.messages(conv["id"], 40)):
        notice.mark(conv["id"])          # 「买家」发的全是通知格式（HTML 图片 / 链接）
        conv = data.get_conv(conv["id"])
    return 0 if conv.get("kind") == notice.KIND else nb


def send(conv, msg):
    """发消息。msg = {kind, text, extra}。返回平台消息编号。"""
    kind = msg.get("kind") or "text"
    ex = msg.get("extra") or {}
    kw = {}
    if kind == "text":
        kw["txt"] = msg.get("text") or ""
    elif kind == "image":
        kw.update(img_url=ex.get("url"), width=ex.get("w") or 600, height=ex.get("h") or 600)
    elif kind == "item":
        if not ex.get("item_id"):
            raise ValueError("这个产品还没推到 Lazada，没有商品编号，发不了商品卡片")
        kw["item_id"] = ex["item_id"]
    elif kind == "order":
        kw["order_id"] = ex.get("order_no")
    with erp_link.ShopConn(conv["shop_id"]) as cn:
        d = cn.im_send(_session_id(conv), TPL[kind], **kw)
    return str(d.get("message_id") or d.get("msg_id") or "")


def mark_read(conv):
    if not conv.get("ext_last_id"):
        return
    with erp_link.ShopConn(conv["shop_id"]) as cn:
        cn.im_read(_session_id(conv), conv["ext_last_id"])
