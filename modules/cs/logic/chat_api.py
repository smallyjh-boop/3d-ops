"""v2.46 客服工作台 / 聊天页的接口（挂在 logic/api.py 的同一个 Blueprint 上）。"""
import os
import time
import uuid

from flask import g, jsonify, request, send_from_directory

from . import chat, crm, data, erp_link, jobs, service, shopcfg
from .api import _err, _u, _wrap, bp


def _files_dir():
    from core.config import DATA_DIR
    d = os.path.join(DATA_DIR, "cs_files")
    os.makedirs(d, exist_ok=True)
    return d


def _conv_ok(cid):
    c = data.get_conv(cid)
    if not c:
        raise ValueError("会话不存在")
    if not crm.shop_ok(g.get("user"), c.get("shop")):
        raise ValueError("你没有这个店铺的权限")
    return c


def _out(fn):
    """发送类操作：别人接管 / 发送失败 → 409 / 502，界面给出提示（可以选择强行发 / 重发）。"""
    try:
        return jsonify(fn())
    except PermissionError as e:
        return jsonify({"error": str(e), "taken": True}), 409
    except RuntimeError as e:
        return jsonify({"error": str(e), "failed": True}), 502


@bp.get("/api/cs/dashboard")
@_wrap
def cs_dashboard():
    d = chat.dashboard(g.get("user"))
    d["jobs"] = jobs.status()
    return jsonify(d)


@bp.get("/api/cs/inbox")
@_wrap
def cs_inbox():
    """聊天页左边的会话列表：status=active/unreplied/human/taken/mine/closed/leads/…"""
    sh = crm.allowed(g.get("user"))
    a = request.args
    st = a.get("status", "active")
    mine = _u() if st == "mine" else ""
    rows = data.list_convs("active" if st == "mine" else st, a.get("q", ""), limit=int(a.get("limit") or 300),
                           shop=a.get("shop", ""), shops=sh, mine=mine)
    if st == "unreplied":
        rows = [c for c in rows if (c.get("last") or {}).get("role") == "buyer"]
        rows.sort(key=lambda c: -(c.get("wait_min") or 0))           # v2.49：未回复 = 等得最久的在最上面
    elif st == "system":
        rows.sort(key=lambda c: (0 if c.get("unread") else 1, -(c.get("updated_at") or 0)))
    else:
        # 排序：需人工 → 等得最久的未回复 → 其它按时间
        rows.sort(key=lambda c: (0 if c.get("needs_human") and c["status"] != "closed" else 1,
                                 0 if (c.get("last") or {}).get("role") == "buyer" and c["status"] == "open" else 1,
                                 -(c.get("wait_min") or 0) if (c.get("last") or {}).get("role") == "buyer" else 0, -(c.get("updated_at") or 0)))
    for c in rows:
        c["ai_mode"] = shopcfg.mode_of(c)
        c.pop("draft_zh", None)
        c["has_draft"] = bool(c.pop("draft", None))
    st_all = data.list_convs("active", limit=1000, shops=sh)
    counts = {"active": len(st_all), "unreplied": sum(1 for c in st_all if (c.get("last") or {}).get("role") == "buyer" and c["status"] == "open"),
              "human": sum(1 for c in st_all if c.get("needs_human")), "taken": sum(1 for c in st_all if c.get("mode") == "human"),
              "mine": sum(1 for c in st_all if _u() in (c.get("assigned"), c.get("taken_by"))),
              "system": sum(1 for c in data.list_convs("system", limit=1000, shops=sh) if c.get("unread"))}   # v2.49：没读的平台通知
    unread = sum(int(c.get("unread") or 0) for c in st_all)
    return jsonify({"convs": rows, "counts": counts, "unread": unread, "newest_buyer": max([c.get("last_buyer_at") or 0 for c in st_all] or [0]),
                    "shops": sh if sh is not None else crm.known_shops(), "agents": _agents(), "me": _u(),
                    "alert_minutes": float(data.settings().get("alert_minutes") or 0)})


def _agents():
    names = crm.agent_names()
    return [{"agent": u, "name": n} for u, n in names.items()]


@bp.post("/api/cs/convs/<int:cid>/send")
@_wrap
def cs_send(cid):
    _conv_ok(cid)
    b = request.get_json(force=True) or {}
    kind, extra = b.get("kind") or "text", b.get("extra")
    if kind == "item" and b.get("product_id"):
        p = erp_link.product_card(b["product_id"])
        extra = {"item_id": p["lazada_item_id"], "name": p["name"], "image": p["image"], "price": p["price"], "product_id": p["id"]}
    if kind == "order" and b.get("order_id"):
        o = erp_link.order_brief(int(b["order_id"]))
        if not o:
            raise ValueError("找不到订单")
        extra = {"order_no": o["order_no"], "status": o.get("status_zh") or "", "order_id": o["id"]}
    return _out(lambda: chat.send(cid, b.get("text") or "", _u(), kind=kind, extra=extra, force=bool(b.get("force"))))


@bp.post("/api/cs/convs/<int:cid>/image")
@_wrap
def cs_image(cid):
    """发图片：存到 data/cs_files；接口渠道先传到平台图片空间再发。"""
    c = _conv_ok(cid)
    f = request.files.get("image")
    if not f:
        raise ValueError("没有图片")
    raw = f.read()
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("图片太大（最多 8MB）")
    ext = (os.path.splitext(f.filename or "")[1] or ".jpg").lower()[:5]
    name = uuid.uuid4().hex + (ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".jpg")
    with open(os.path.join(_files_dir(), name), "wb") as fh:
        fh.write(raw)
    extra = {"url": f"/api/cs/files/{name}", "local": name}
    if c.get("channel") == "lazada_im":
        from core import imghost
        path = os.path.join(_files_dir(), name)
        data_, ext2 = imghost.prepare(path, max_bytes=1_000_000, max_side=1600, min_side=1)
        with erp_link.ShopConn(c["shop_id"]) as cn:
            extra["url"] = cn.upload_image(data_, f"chat.{ext2}")
        extra["local_url"] = f"/api/cs/files/{name}"
    return _out(lambda: chat.send(cid, "", _u(), kind="image", extra=extra, force=bool(request.form.get("force"))))


@bp.get("/api/cs/files/<name>")
def cs_file(name):
    return send_from_directory(_files_dir(), os.path.basename(name))


@bp.post("/api/cs/messages/<int:mid>/resend")
@_wrap
def cs_resend(mid):
    return _out(lambda: chat.resend(mid, _u()))


@bp.post("/api/cs/convs/<int:cid>/takeover")
@_wrap
def cs_takeover(cid):
    _conv_ok(cid)
    return jsonify(chat.takeover(cid, _u()))


@bp.post("/api/cs/convs/<int:cid>/release")
@_wrap
def cs_release(cid):
    _conv_ok(cid)
    return jsonify(chat.release(cid, _u()))


@bp.post("/api/cs/convs/<int:cid>/assign")
@_wrap
def cs_assign(cid):
    _conv_ok(cid)
    return jsonify(chat.assign(cid, (request.get_json(force=True) or {}).get("agent") or "", _u()))


@bp.post("/api/cs/convs/<int:cid>/read")
@_wrap
def cs_read(cid):
    _conv_ok(cid)
    return jsonify({"ok": True, "platform": chat.mark_read(cid, background=False)})


@bp.post("/api/cs/notices/read")
@_wrap
def cs_notices_read():
    """v2.49：平台通知全部标已读（Lazada 上也标）。"""
    return jsonify({"ok": True, "n": chat.read_all_notices(crm.allowed(g.get("user")))})


@bp.get("/api/cs/convs/<int:cid>/suggest")
@_wrap
def cs_suggest(cid):
    """v2.49：买家提到的产品 → 1–3 个可以发的商品卡片。"""
    _conv_ok(cid)
    return jsonify({"items": service.suggest_products(cid)})


@bp.post("/api/cs/convs/<int:cid>/discard")
@_wrap
def cs_discard(cid):
    _conv_ok(cid)
    data.update_conv(cid, draft=None, draft_zh=None)
    return jsonify(service.conv_full(cid))


@bp.post("/api/cs/convs/<int:cid>/ai")
@_wrap
def cs_ai_now(cid):
    """让 AI 现在写草稿（后台排队，界面过几秒刷新）。"""
    _conv_ok(cid)
    return jsonify({"job": jobs.enqueue("draft", cid)})


# ---------------- 快捷回复 ----------------
@bp.get("/api/cs/quick")
@_wrap
def cs_quick():
    return jsonify({"items": chat.quick_list(request.args.get("shop", "")), "vars": ["买家名", "订单号", "运单号", "预计发货日", "店铺名"]})


@bp.post("/api/cs/quick")
@_wrap
def cs_quick_save():
    return jsonify({"items": chat.quick_save(request.get_json(force=True) or {}, _u())})


@bp.delete("/api/cs/quick/<int:qid>")
@_wrap
def cs_quick_del(qid):
    chat.quick_delete(qid)
    return jsonify({"ok": True})


@bp.get("/api/cs/convs/<int:cid>/quick/<int:qid>")
@_wrap
def cs_quick_fill(cid, qid):
    _conv_ok(cid)
    return jsonify({"text": chat.quick_use(qid, cid)})


@bp.post("/api/cs/convs/<int:cid>/fill")
@_wrap
def cs_fill(cid):
    _conv_ok(cid)
    return jsonify({"text": chat.fill((request.get_json(force=True) or {}).get("text") or "", service.conv_full(cid))})


@bp.get("/api/cs/products")
@_wrap
def cs_products():
    out = []
    for p in erp_link.search_products(request.args.get("q", ""), 12):
        try:
            out.append(erp_link.product_card(p["id"]))
        except Exception:  # noqa: BLE001
            continue
    return jsonify({"items": out})


@bp.get("/api/cs/convs/<int:cid>/orders")
@_wrap
def cs_conv_orders(cid):
    c = _conv_ok(cid)
    rows = erp_link.orders_of_buyer(c.get("platform") or "", c.get("buyer") or "", 8)
    if c.get("order_id") and not any(o and o["id"] == c["order_id"] for o in rows):
        rows.insert(0, erp_link.order_brief(c["order_id"]))
    return jsonify({"items": [o for o in rows if o]})


# ---------------- 店铺 AI 模式 / 拉消息 / 质检 ----------------
@bp.post("/api/cs/shops/mode")
@_wrap
def cs_shop_mode():
    b = request.get_json(force=True) or {}
    if (getattr(g, "user", None) or {}).get("role") != "owner":
        return _err("只有老板可以改店铺的 AI 模式", 403)
    kw = {k: b[k] for k in ("mode", "im") if k in b}
    return jsonify(shopcfg.save(b.get("shop") or "", **kw))


@bp.post("/api/cs/poll")
@_wrap
def cs_poll():
    r = jobs.poll_all(force=True)
    jobs.run_due("web", 5)
    return jsonify({"shops": r})


@bp.get("/api/cs/qa")
@_wrap
def cs_qa():
    return jsonify({"items": chat.qa_list(int(request.args.get("days") or 14), 100)})


@bp.post("/api/cs/convs/<int:cid>/qa")
@_wrap
def cs_qa_one(cid):
    _conv_ok(cid)
    r = chat.qa_one(cid, _u())
    if not r:
        raise ValueError("这个会话还没有客服回复，没法打分")
    return jsonify(r)


@bp.get("/api/cs/jobs")
@_wrap
def cs_jobs():
    return jsonify(dict(jobs.status(), now=time.time()))
