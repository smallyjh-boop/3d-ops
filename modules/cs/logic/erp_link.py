"""客服模块 ↔ ERP（产品库、订单、生产）的唯一连接点。

客服模块的其他文件都不直接读写 ERP 的表或函数，只调用这里。
以后客服要拆成独立程序，或者 ERP 改了结构，只改这一个文件：
  - products()              产品资料（品名、泰文标题、材料、尺寸、颜色、售价、发货天数）
  - find_orders(text, buyer) 从消息里找订单号 / 按买家找最近订单
  - order_brief(oid)        订单摘要（状态、最晚发货、商品、定制备注、生产进度、运单号）
  - add_order_note(...)     把定制要求 / 备注写进订单（生产工单上会显示定制备注）
  - create_quote(...)       生成报价单（批发 / 定制询价）
  - capacity_hours_per_day() 估算交期用
"""
import re
import time

from core import codes, orders, pricing, production, store
from core.config import load_config


def _cfg():
    return load_config()


def products():
    """产品摘要列表（给 AI 当资料用，只含对外价格，不含成本利润）。"""
    cfg = _cfg()
    colors = codes.color_hex(cfg)
    out = []
    for row in store.list_products():
        try:
            p = store.load(row["id"])
        except Exception:  # noqa: BLE001
            continue
        try:
            prices = pricing.price_product(cfg, p)
        except Exception:  # noqa: BLE001
            prices = [{}] * len(p.get("variants") or [])
        cp = p.get("copy") or {}
        vs = []
        for v, pr in zip(p.get("variants") or [], prices):
            name = " ".join(x for x in (v.get("opt1_zh"), v.get("opt2_zh")) if x)
            th = " ".join(x for x in ((colors.get(v.get("opt1_zh") or "") or {}).get("th"),
                                       (colors.get(v.get("opt2_zh") or "") or {}).get("th")) if x)
            vs.append({"sku": v.get("sku"), "option_zh": name, "option_th": th or None,
                       "price": (pr or {}).get("final_price"), "list_price": (pr or {}).get("list_price"),
                       "floor_price": (pr or {}).get("floor_price"), "hours": v.get("hours")})
        out.append({"id": p["id"], "name_zh": p.get("name_zh", ""), "title_th": cp.get("title_th", ""),
                    "title_en": cp.get("title_en", ""), "material": p.get("material") or "PLA",
                    "size": p.get("size_text") or "", "features_zh": (p.get("features_zh") or "")[:200],
                    "keywords": p.get("keywords") or "", "lead_days": p.get("lead_days") or cfg.get("default_ship_days", 3),
                    "variants": vs})
    return out


def sku_info(sku):
    sku = (sku or "").strip().upper()
    for p in products():
        for v in p["variants"]:
            if (v.get("sku") or "").upper() == sku:
                return p, v
    return None, None


_TOKEN = re.compile(r"[A-Za-z0-9]{6,30}")


def find_orders(text="", buyer="", days=120, limit=5):
    """消息里出现的订单号（完全一致）+ 这个买家最近的订单。"""
    from core import db
    c = db.conn()
    found = []
    toks = {t.upper() for t in _TOKEN.findall(text or "")}
    if toks:
        q = ",".join("?" * len(toks))
        for r in c.execute(f"SELECT id FROM orders WHERE UPPER(order_no) IN ({q})", tuple(toks)):
            found.append(r["id"])
    if buyer and len(found) < limit:
        since = time.time() - days * 86400
        for r in c.execute("SELECT id FROM orders WHERE (buyer=? OR receiver=?) AND COALESCE(order_time,0)>=? "
                           "ORDER BY order_time DESC LIMIT ?", (buyer, buyer, since, limit)):
            if r["id"] not in found:
                found.append(r["id"])
    return [order_brief(i) for i in found[:limit] if order_brief(i)]


def order_by_no(order_no):
    from core import db
    r = db.conn().execute("SELECT id FROM orders WHERE UPPER(order_no)=?", ((order_no or "").strip().upper(),)).fetchone()
    return order_brief(r["id"]) if r else None


def order_brief(oid):
    o = orders.get_order(oid)
    if not o:
        return None
    jobs = production.list_jobs(order_id=oid)
    prog = {}
    for j in jobs:
        prog[j["status_zh"]] = prog.get(j["status_zh"], 0) + int(j["qty"] or 0)
    return {"id": o["id"], "order_no": o["order_no"], "platform": o.get("platform"), "status": o.get("status"),
            "status_zh": o.get("status_zh"), "order_time": o.get("order_time"), "ship_by": o.get("ship_by"),
            "shipped_at": o.get("shipped_at"), "tracking_no": o.get("tracking_no") or "", "carrier": o.get("carrier") or "",
            "buyer": o.get("buyer") or "", "custom_note": o.get("custom_note") or "", "seller_note": o.get("seller_note") or "",
            "buyer_note": o.get("buyer_note") or "", "total": o.get("order_total"), "kind": o.get("kind"),
            "items": [{"sku": i.get("sku"), "name": i.get("name"), "qty": i.get("qty"), "color": i.get("color")}
                      for i in o.get("items") or []],
            "production": prog, **_ship_clock(o)}


def _ship_clock(o):
    """店铺承诺付款后 24–48 小时发货：告诉 AI 这个订单下单多久了、有没有超时。"""
    import time
    t = o.get("order_time")
    try:
        t = float(t)
    except (TypeError, ValueError):
        return {}
    h = (time.time() - t) / 3600
    shipped = bool(o.get("shipped_at")) or o.get("status") in ("shipped", "delivered", "done", "completed")
    return {"下单后已过小时": round(h, 1), "已超过48小时还没发货": (not shipped) and h > 48}


def add_order_note(oid, text, field="custom_note", user=""):
    """在订单的定制备注 / 卖家备注后面追加一段（不覆盖原来的）。定制备注会显示在生产工单上。"""
    if field not in ("custom_note", "seller_note"):
        raise ValueError("只能写定制备注或卖家备注")
    o = orders.get_order(oid)
    if not o:
        raise ValueError("订单不存在")
    text = (text or "").strip()
    if not text:
        raise ValueError("备注是空的")
    old = (o.get(field) or "").strip()
    if text in old:
        return order_brief(oid)
    new = (old + "\n" if old else "") + f"[客服] {text}"
    orders.update_order(oid, user=user, **{field: new})
    return order_brief(oid)


def set_priority(oid, user=""):
    orders.update_order(oid, user=user, priority=1)
    return order_brief(oid)


def create_quote(buyer, items, note="", user="", platform="manual"):
    """生成报价单（订单页「报价」里能看到，确认后可以改成正式订单）。items: [{sku, qty, unit_price}]"""
    o = orders.create_manual({"kind": "quote", "buyer": buyer or "", "platform": platform or "manual",
                              "buyer_note": note or "客服询价",
                              "items": [{"sku": i["sku"], "qty": i["qty"], "unit_price": i.get("unit_price")} for i in items]},
                             user=user)
    return order_brief(o["id"])


def capacity_hours_per_day():
    cfg = _cfg()
    n = len(cfg.get("printers") or []) or int(cfg.get("printer_count") or 1)
    return max(1.0, n * float(cfg.get("hours_per_day_each") or 16))


def default_ship_days():
    return int(_cfg().get("default_ship_days") or 3)


def ai_cfg():
    """AI 接口设置（和 ERP 共用一个密钥）。"""
    return _cfg()


def color_names():
    return {k: v.get("th") for k, v in codes.color_hex(_cfg()).items()}


def buyer_history(platform, buyer, exclude_conv=None):
    """这个买家以前的订单和会话（给 AI 认出老顾客、给客服看）。只给摘要，不给电话地址。"""
    from core import db
    buyer = (buyer or "").strip()
    if not buyer:
        return None
    c = db.conn()
    rows = c.execute("SELECT id, order_no, platform, status, order_time, order_total FROM orders WHERE (buyer=? OR receiver=?) "
                     "AND status NOT IN ('quote') ORDER BY order_time DESC LIMIT 20", (buyer, buyer)).fetchall()
    items = {}
    for r in rows[:5]:
        items[r["id"]] = [f"{i['sku'] or ''} {i['name'] or ''} ×{i['qty']}".strip()
                          for i in c.execute("SELECT sku, name, qty FROM order_items WHERE order_id=?", (r["id"],))]
    paid = [r for r in rows if r["status"] not in ("cancelled", "unpaid")]
    convs = c.execute("SELECT id, tags, lead_stage, intent, updated_at FROM cs_conv WHERE buyer=? AND id!=? ORDER BY updated_at DESC LIMIT 10",
                      (buyer, exclude_conv or -1)).fetchall()
    tags = []
    for cv in convs:
        for t in (cv["tags"] or "").split(","):
            if t and t not in tags:
                tags.append(t)
    level = ""
    try:
        r = c.execute("SELECT buyer_key FROM orders WHERE buyer=? AND buyer_key IS NOT NULL LIMIT 1", (buyer,)).fetchone()
        if r:
            b = c.execute("SELECT level FROM buyers WHERE key=?", (r["buyer_key"],)).fetchone()
            level = (b["level"] if b else "") or ""
    except Exception:  # noqa: BLE001
        pass
    if not rows and not convs:
        return None
    return {"orders": len(paid), "spent": round(sum(float(r["order_total"] or 0) for r in paid), 2),
            "last_order": time.strftime("%Y-%m-%d", time.localtime(rows[0]["order_time"])) if rows and rows[0]["order_time"] else "",
            "recent": [{"order_no": r["order_no"], "status": orders.STATUS_ZH.get(r["status"], r["status"]),
                        "day": time.strftime("%Y-%m-%d", time.localtime(r["order_time"])) if r["order_time"] else "",
                        "total": r["order_total"], "items": items.get(r["id"], [])} for r in rows[:5]],
            "past_chats": len(convs), "tags": tags[:8], "level": orders.LEVEL_ZH.get(level, level) if level else "",
            "repeat": len(paid) >= 1}


def confirm_quote(oid, user=""):
    """报价单 → 正式订单（待发货，开始排产）。"""
    o = order_brief(oid)
    if not o:
        raise ValueError("找不到报价单")
    if o.get("status") != "quote":
        raise ValueError("这个订单已经不是报价单了")
    orders.update_order(oid, user=user, status="to_ship", kind="wholesale")      # 状态变化会自动排产
    return order_brief(oid)
