"""扫码识别：扫到一个码（或手输），说出它是什么，带上手机页面要用的摘要。

认得的码（系统自己打印的标签 + 平台面单）：
  订单号 / 快递单号  面单上的条码（core/labels、orders/carriers、waybill）→ order
  SKU              产品标签、内部商品标签、生产工单贴纸（条码内容都是 SKU）→ item（库存物品）或 sku（还没建库存档的产品）
  物品编码          库存物品的编码（包材、备件……成品的编码就是 SKU）→ item
  货位 / 货架 / 区   货位标签（A1-02-03）、货架牌（A1）→ location / shelf / zone
  料卷编号          料卷标签 → spool
生产单号（PO260101-01，生产单上的二维码）→ po
认不出来 → unknown（手机页面提示「不认识这个码」）。

对外：resolve(code, user, prefer="")  order_summary(row_or_id, user)  norm(code)
prefer：页面优先认哪种（"order" / "item" / "location"），同一个码两种都像时按页面来（例如验货时扫的是商品）。
"""
import re

from core import db, modules, orders as orders_mod, production, store

_WS = re.compile(r"\s+")
STATUS_TH = {"unpaid": "ยังไม่ชำระเงิน", "to_ship": "รอจัดส่ง", "shipped": "จัดส่งแล้ว", "completed": "สำเร็จ", "cancelled": "ยกเลิกแล้ว",
             "returned": "คืนสินค้า/คืนเงิน", "delivery_failed": "ปฏิเสธรับ/ส่งไม่สำเร็จ", "quote": "ใบเสนอราคา/สั่งจอง", "other": "อื่นๆ"}


def norm(code):
    """扫码枪 / 摄像头读到的码：去掉前后空白、中间的换行和制表符；不改大小写（订单号区分大小写的平台也能对上）。"""
    return _WS.sub("", str(code or "")).strip()[:120]


def _owner(user):
    return (user or {}).get("role") == "owner"


def _img_of(p, vi=None):
    if not p:
        return ""
    imgs = p.get("images") or []
    want = ((p.get("variants") or [{}])[vi] or {}).get("image") if vi is not None and vi < len(p.get("variants") or []) else None
    img = next((i for i in imgs if want and (i.get("file") == want or i.get("raw") == want)), None) or (imgs[0] if imgs else None)
    if not img:
        return ""
    return f"/files/{p['id']}/{'out' if img.get('processed') else 'raw'}/{img['file']}"


def _product_of_sku(sku):
    """SKU → (产品, 第几个规格)；对不上返回 (None, None)。"""
    s = str(sku or "").strip().upper()
    if not s:
        return None, None
    pid = s.split("-")[0]
    try:
        p = store.load(pid)
    except Exception:  # noqa: BLE001  不是产品编号 / 产品删了
        return None, None
    for i, v in enumerate(p.get("variants") or []):
        if str(v.get("sku") or "").strip().upper() == s:
            return p, i
    return None, None


# ---------------- 订单 ----------------
def _find_order(code):
    """订单号或快递单号（不管设置里规定扫哪个，查询时两个都认）。"""
    from modules.orders import scanning
    return scanning.find_order(code, "both")


def order_summary(r, user=None, fresh=False):
    """订单的摘要：状态（取消 / 退货要大声提醒）、商品（带图）、定制备注、生产进度、运单、交接单。"""
    oid = r if isinstance(r, int) else r["id"]
    if fresh:
        row = db.conn().execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        if row is not None and orders_mod._refresh_one(row):     # 先从平台拉一次最新状态（买家刚取消的单也拦住）
            pass
    o = orders_mod.get_order(oid)
    if not o:
        return None
    from modules.orders import scanning
    for it, m in zip(o.get("items") or [], scanning.modes_for_items(o.get("items") or [])):
        it.update(m)
        if not it.get("img"):
            p, vi = _product_of_sku(it.get("sku"))
            it["img"] = _img_of(p, vi)
    jobs = production.list_jobs(order_id=oid)
    counts = {}
    for j in jobs:
        counts[j["status"]] = counts.get(j["status"], 0) + 1
    out = {k: o.get(k) for k in ("id", "order_no", "platform", "shop", "status", "status_zh", "tracking_no", "carrier", "buyer",
                                 "receiver", "custom_note", "buyer_note", "seller_note", "ship_by", "order_time", "hold", "hold_reason", "kind",
                                 "handover_id", "label_printed_at", "priority", "cod", "payment", "updated_at")}
    out["items"] = [{k: it.get(k) for k in ("sku", "name", "variation", "color", "qty", "img", "check", "product_id")} for it in o["items"]]
    from core import codes
    from core.config import load_config
    cfg = load_config()
    for it in out["items"]:                              # 颜色的泰文名（泰国员工看）
        row = codes.find_color(cfg, it.get("color")) if it.get("color") else None
        it["color_th"] = row[2] if row else ""
    out["jobs"] = [{k: j.get(k) for k in ("id", "sku", "qty", "qty_done", "status", "status_zh", "printer_code", "remaining", "kind")}
                   for j in jobs]
    out["job_counts"] = counts
    out["jobs_left"] = sum(1 for j in jobs if j["status"] not in ("packed", "done"))
    out["status_th"] = STATUS_TH.get(o["status"], out["status_zh"])
    out["blocked"] = o["status"] in orders_mod.BLOCK_SHIP
    out["is_cod"] = orders_mod.is_cod(o)
    if out["is_cod"] and not _owner(user) and (user or {}).get("role") == "production":
        out["cod"] = None
    out["photos"] = photo_count(oid)
    if o.get("handover_id"):
        h = db.conn().execute("SELECT id, carrier, closed_at FROM handovers WHERE id=?", (o["handover_id"],)).fetchone()
        out["handover"] = dict(h) if h else None
    return out


def photo_count(oid):
    from . import photos
    return len(photos.list_photos(oid))


# ---------------- 库存 / 货位 ----------------
def _inv_on():
    return modules.enabled("inv")


def _item_out(it, user):
    it = dict(it)
    if not _owner(user):
        for k in ("avg_cost", "value"):
            it.pop(k, None)
    loc = None
    if it.get("location") and _inv_on():
        from modules.inv import locations
        lr = locations.get_loc(it["location"])
        if lr:
            loc = {"code": lr["code"], "id": lr["id"], "human_zh": locations.human(lr["code"]), "human_th": locations.human(lr["code"], "th")}
    it["loc"] = loc
    if _inv_on() and it.get("id"):               # v2.52：一个物品可以在几个货位（拣货位 + 备货区）+ 待上架
        from modules.inv import wms
        it["locs"] = wms.item_locations(it["id"])
    p, vi = _product_of_sku(it.get("code"))
    it["img"] = _img_of(p, vi)
    if p:
        it["product"] = {"id": p["id"], "name_zh": p.get("name_zh") or "", "title_th": (p.get("copy") or {}).get("title_th") or "",
                         "variant": {k: v for k, v in ((p.get("variants") or [{}])[vi] or {}).items() if k in ("sku", "opt1_zh", "opt2_zh")}}
        it["free_stock"] = production.free_stock(it["code"])
    return it


def _find_item(code):
    from core.inventory import ledger
    s = code.strip().upper()
    r = db.conn().execute("SELECT * FROM inv_items WHERE UPPER(code)=?", (s,)).fetchone()
    return ledger.item_row(r) if r else None


def _location(code):
    if not _inv_on():
        return None
    from modules.inv import locations
    s = code.strip().upper()
    loc = locations.get_loc(s) if not s.isdigit() else None
    if loc:
        d = locations.loc_detail(loc["id"])
        return {"type": "location", "location": d["location"], "items": d["items"]}
    if locations.SHELF_RE.match(s) or locations.ZONE_RE.match(s):
        codes = locations.area_codes(s)
        if codes:
            items = [dict(x, location=c_) for c_ in codes for x in locations.items_at(c_)]
            return {"type": "shelf" if locations.SHELF_RE.match(s) else "zone", "code": s, "locations": codes, "items": items}
    return None


def _spool(code):
    from core import materials
    s = code.strip().upper()
    if s.isdigit():
        return None
    try:
        sp = materials.spool_get(s)
    except Exception:  # noqa: BLE001
        return None
    if not sp or str(sp.get("code") or "").upper() != s:
        return None
    sp = dict(sp)
    sp.pop("price", None)
    return {"type": "spool", "spool": sp}


# ---------------- 识别 ----------------
def resolve(code, user=None, prefer="", fresh=False, fuzzy=False):
    """返回 {type, code, ...}。type：order / item / sku / location / shelf / zone / spool / unknown。
    fuzzy=True（拍照 / 摄像头读出来的文字）：认不出时按文字容错（O/0、I/1、少横杠……，拍照识别模块）找最像的码：
    把握够（≥0.85）就当成那个码（结果里带 fuzzy: {from, conf}），不够就在 unknown 里给 suggest 候选。"""
    r = _resolve(code, user, prefer, fresh)
    if r["type"] != "unknown" or not fuzzy:
        return r
    from core import modules as _m
    rc = _m.public("recog")
    if not rc:
        return r
    cands = [c for c in rc.match_text(r["code"], 5) if c["type"] != "location?"]
    if cands and cands[0]["conf"] >= 0.85 and cands[0]["code"] != r["code"]:
        r2 = _resolve(cands[0]["code"], user, prefer, fresh)
        if r2["type"] != "unknown":
            r2["fuzzy"] = {"from": r["code"], "conf": cands[0]["conf"]}
            return r2
    r["suggest"] = cands
    return r


def _resolve(code, user=None, prefer="", fresh=False):
    code = norm(code)
    if not code:
        raise ValueError("先扫码或输入")
    if re.fullmatch(r"PO\d{6}-\d+", code, re.I):         # v2.54：生产单二维码（core/po.py）
        row = db.conn().execute("SELECT id, no, status FROM production_orders WHERE UPPER(no)=?", (code.upper(),)).fetchone()
        if row:
            return {"type": "po", "code": row["no"], "po": {"id": row["id"], "no": row["no"], "status": row["status"]}}
    order = lambda: _find_order(code)                     # noqa: E731
    item = lambda: _find_item(code) if _inv_on() else None    # noqa: E731
    tries = ["location", "item", "order"] if prefer in ("item", "location") else ["order", "location", "item"]
    for kind in tries:
        if kind == "order":
            r = order()
            if r:
                s = order_summary(r, user, fresh)
                return {"type": "order", "code": code, "order": s, "alert": _order_alert(s)}
        elif kind == "location":
            loc = _location(code)
            if loc:
                if not _owner(user):
                    for x in loc.get("items") or []:
                        x.pop("avg_cost", None); x.pop("value", None)
                return {"code": code, **loc}
        elif kind == "item":
            it = item()
            if it:
                return {"type": "item", "code": code, "item": _item_out(it, user)}
    p, vi = _product_of_sku(code)
    if p:                                              # 产品的 SKU，还没建库存档（没入过库）
        v = (p.get("variants") or [{}])[vi]
        return {"type": "sku", "code": code, "sku": {"sku": v.get("sku"), "product_id": p["id"], "name_zh": p.get("name_zh") or "",
                                                     "title_th": (p.get("copy") or {}).get("title_th") or "", "opt1_zh": v.get("opt1_zh") or "",
                                                     "img": _img_of(p, vi), "free_stock": production.free_stock(v.get("sku"))}}
    sp = _spool(code)
    if sp:
        return {"code": code, **sp}
    return {"type": "unknown", "code": code}


def _order_alert(s):
    """扫到订单时要大声提醒的情况（取消 / 退货 / 拒收、挂起待审核、未付款）。"""
    if s["blocked"]:
        return {"level": "error", "zh": f"订单 {s['order_no']} 是「{s['status_zh']}」，不要打包、不要发货！",
                "th": f"ออเดอร์ {s['order_no']} สถานะ「{s['status_th']}」 ห้ามแพ็ก ห้ามส่ง!"}
    if s.get("hold"):
        return {"level": "warn", "zh": "这个订单还在「待审核」挂起中", "th": "ออเดอร์นี้ยังพักไว้รอตรวจสอบ"}
    if s["status"] == "unpaid":
        return {"level": "warn", "zh": "这个订单还没付款", "th": "ออเดอร์นี้ยังไม่ชำระเงิน"}
    return None


def search_orders(q, limit=30):
    """查订单：订单号 / 运单号 / 买家 / 收件人 / 电话 / SKU 模糊查（最新的在前）。"""
    q = str(q or "").strip()
    if len(q) < 2:
        raise ValueError("至少输入 2 个字")
    r = orders_mod.search({"q": q, "sort": "time_desc", "page": 1, "page_size": max(10, limit)})
    out = []
    for o in r.get("orders") or []:
        out.append({k: o.get(k) for k in ("id", "order_no", "platform", "status", "status_zh", "tracking_no", "buyer", "receiver",
                                          "order_time", "ship_by", "carrier")} | {"n_items": sum(int(i.get("qty") or 1) for i in o.get("items") or [])})
    return out[:limit]


def carriers():
    """发货交接选物流：待发货订单里出现的物流（带单数）+ 还没完成的交接单。"""
    c = db.conn()
    rows = c.execute("SELECT COALESCE(carrier,'') carrier, COUNT(*) n FROM orders WHERE status='to_ship' GROUP BY COALESCE(carrier,'') "
                     "ORDER BY n DESC").fetchall()
    open_ = [dict(h) | {"count": c.execute("SELECT COUNT(*) FROM orders WHERE handover_id=?", (h["id"],)).fetchone()[0]}
             for h in c.execute("SELECT id, carrier, method, created_at, username FROM handovers WHERE closed_at IS NULL ORDER BY id DESC")]
    return {"carriers": [{"carrier": r["carrier"], "to_ship": r["n"]} for r in rows if r["carrier"]], "open": open_}
