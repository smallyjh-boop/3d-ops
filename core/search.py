"""全局搜索（v2.49）：顶部 🔍 / Ctrl+K 一个框查 订单号、快递单号、SKU、产品名、买家名、客服会话。

按角色给结果（和菜单一致）：
  · 订单：所有角色（订单列表大家都能看）；不带金额
  · 产品：所有角色（产品库大家都能看）
  · 客服会话：老板、上架客服（客服模块开着才查）
扫码枪扫的码（SKU 标签、面单）也能直接搜：完全一样的订单号 / 快递单号 / SKU 排在最前面。

对外：search(q, user, limit=8) → {q, groups:[{type, zh, th, items:[…]}], total}
"""
import os
import re
import threading

from . import db, store

_ix_lock = threading.Lock()
_ix = {"key": None, "rows": []}
STATUS_ZH = {"unpaid": ("未付款", "ยังไม่ชำระเงิน"), "to_ship": ("待发货", "รอจัดส่ง"), "shipped": ("已发货", "จัดส่งแล้ว"),
             "completed": ("已完成", "สำเร็จ"), "cancelled": ("已取消", "ยกเลิกแล้ว"), "returned": ("退货退款", "คืนสินค้า/คืนเงิน"),
             "delivery_failed": ("拒收 / 派送失败", "ปฏิเสธรับ/ส่งไม่สำเร็จ"), "quote": ("报价 / 预订", "ใบเสนอราคา/สั่งจอง"),
             "other": ("其他", "อื่นๆ")}


def _products():
    """产品索引（编号、名字、泰文标题、SKU、颜色、缩略图）：产品文件没变就用上次的。"""
    try:
        files = tuple(sorted((e.name, e.stat().st_mtime_ns) for e in os.scandir(store.PRODUCTS_DIR) if e.name.endswith(".json")))
    except OSError:
        files = ()
    key = (store.PRODUCTS_DIR, files)
    with _ix_lock:
        if _ix["key"] == key:
            return _ix["rows"]
        rows = []
        for name, _m in files:
            try:
                p = store.load(name[:-5])
            except Exception:  # noqa: BLE001  坏文件跳过
                continue
            vs = p.get("variants") or []
            img = next((f"/files/{p['id']}/{'out' if im.get('processed') else 'raw'}/{im['file']}" for im in p.get("images") or [] if im.get("file")), "")
            skus = [str(v.get("sku") or "").strip() for v in vs if v.get("sku")]
            rows.append({"id": p["id"], "name": p.get("name_zh") or "", "title_th": (p.get("copy") or {}).get("title_th") or "",
                         "skus": skus, "thumb": img, "draft": bool(p.get("draft")), "active": p.get("active", True) is not False,
                         "exported": bool(p.get("exported_at") or p.get("shopee_exported_at") or (p.get("lazada_api") or {}).get("item_id")),
                         "hay": " ".join([p["id"], p.get("name_zh") or "", (p.get("copy") or {}).get("title_th") or "", p.get("keywords") or "",
                                          *skus]).lower()})
        _ix.update(key=key, rows=rows)
        return rows


def _orders(q, limit):
    c = db.conn()
    like = f"%{q}%"
    rows = c.execute(
        "SELECT id, platform, shop, order_no, tracking_no, buyer, receiver, status, order_time, ship_by FROM orders "
        "WHERE order_no LIKE ? OR tracking_no LIKE ? OR buyer LIKE ? OR receiver LIKE ? "
        "OR id IN (SELECT order_id FROM order_items WHERE sku LIKE ? OR name LIKE ? LIMIT 500) "
        "ORDER BY (order_no=? OR tracking_no=?) DESC, order_time DESC LIMIT ?",
        (like, like, like, like, like, like, q, q, limit)).fetchall()
    out = []
    for r in rows:
        st = STATUS_ZH.get(r["status"] or "", (r["status"] or "", r["status"] or ""))
        hit = "tracking" if q.lower() in (r["tracking_no"] or "").lower() and q.lower() not in (r["order_no"] or "").lower() else (
            "buyer" if q.lower() in f"{r['buyer'] or ''} {r['receiver'] or ''}".lower() else "")
        out.append({"id": r["id"], "order_no": r["order_no"], "platform": r["platform"] or "", "shop": r["shop"] or "",
                    "tracking_no": r["tracking_no"] or "", "buyer": r["buyer"] or r["receiver"] or "", "status": r["status"] or "",
                    "status_zh": st[0], "status_th": st[1], "order_time": r["order_time"], "hit": hit,
                    "exact": q in ((r["order_no"] or ""), (r["tracking_no"] or ""))})
    return out


def _goods(q, limit):
    ql = q.lower()
    hits = []
    for p in _products():
        if ql not in p["hay"]:
            continue
        sku = next((s for s in p["skus"] if s.lower() == ql), None) or next((s for s in p["skus"] if ql in s.lower()), "")
        score = (0 if p["id"].lower() == ql or (sku and sku.lower() == ql) else 1, 0 if ql in p["name"].lower() else 1, p["id"])
        hits.append((score, {k: p[k] for k in ("id", "name", "title_th", "thumb", "draft", "active")} | {"sku": sku, "n_skus": len(p["skus"])}))
    hits.sort(key=lambda x: x[0])
    return [h[1] for h in hits[:limit]]


def _convs(q, limit):
    from . import modules
    if modules.is_loaded() and not modules.enabled("cs"):
        return []
    c = db.conn()
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cs_conv'").fetchone():
        return []
    like = f"%{q}%"
    rows = c.execute(
        "SELECT id, buyer, platform, order_no, summary, status, needs_human, updated_at FROM cs_conv "
        "WHERE buyer LIKE ? OR order_no LIKE ? OR summary LIKE ? "
        "OR id IN (SELECT conv_id FROM cs_msg WHERE text LIKE ? OR text_zh LIKE ? ORDER BY id DESC LIMIT 200) "
        "ORDER BY updated_at DESC LIMIT ?", (like, like, like, like, like, limit)).fetchall()
    return [{"id": r["id"], "buyer": r["buyer"] or "", "platform": r["platform"] or "", "order_no": r["order_no"] or "",
             "summary": (r["summary"] or "")[:120], "status": r["status"] or "", "needs_human": bool(r["needs_human"]),
             "updated_at": r["updated_at"]} for r in rows]


def search(q, user=None, limit=8):
    q = re.sub(r"\s+", " ", str(q or "")).strip()[:80]
    if len(q) < 2:
        raise ValueError("至少输入 2 个字")
    role = (user or {}).get("role") or "owner"
    limit = max(1, min(30, int(limit or 8)))
    groups = []
    o = _orders(q, limit)
    if o:
        groups.append({"type": "order", "zh": "订单", "th": "ออเดอร์", "items": o})
    g = _goods(q, limit)
    if g:
        groups.append({"type": "product", "zh": "产品", "th": "สินค้า", "items": g})
    if role in ("owner", "listing"):
        cv = _convs(q, limit)
        if cv:
            groups.append({"type": "conv", "zh": "客服会话", "th": "แชทลูกค้า", "items": cv})
    # 完全对上的（扫码）排第一组
    groups.sort(key=lambda gr: 0 if any(i.get("exact") or (gr["type"] == "product" and (i.get("sku") or "").lower() == q.lower())
                                        for i in gr["items"]) else 1)
    return {"q": q, "groups": groups, "total": sum(len(x["items"]) for x in groups)}
