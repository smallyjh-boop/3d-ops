"""Lazada 运营数据（v2.46）：财务流水、评价、退货退款、店铺表现。用店铺对接里已经授权的 Lazada 店铺（同一个应用、同一个令牌）。

  财务流水  /finance/transaction/details/get  → 表 oa_lz_tx；一个订单拉到了「商品金额」那一行后，这个订单的所有行交给财务模块
            （fin.settle_import_lines，按行去重），利润就按真实平台扣费算，「平台对账」里也能看到。真实扣点 = 平台扣费 ÷ 商品金额。
  评价      /review/seller/history/list（按商品、每次最多 7 天）+ /review/seller/list/v2（每次 10 条）→ 表 oa_lz_review；
            差评（≤ 3 星）没回复的进今日待办；可以在页面上直接回复（/review/seller/reply/add）。
  退货退款  /reverse/getreverseordersforseller → 表 oa_lz_reverse（一行一个退货商品），看板上算售后（退款）金额。
  店铺表现  /seller/performance/get → 表 oa_lz_perf（每个店铺一行，原样存最新一次）。

v2.51 多店铺：所有表都带 shop_id；看板 / 店铺与评价的「店铺」筛选把店铺名换成 shop_id 传进来（shop_ids），
没筛选时 per_shop() 给每个店铺一份评价、退货、真实扣点、店铺表现、同步状态（「各店铺对比」用）。

每个店铺每类数据的同步状态在 oa_lz_state：上次成功时间、出错原因；没开接口权限会写清楚去哪里申请。
后台每隔 oa_lz_sync_min 分钟自动同步一次（0 = 只手动），页面上有「立即同步」。
"""
import datetime as dt
import json
import re
import threading
import time

from core import db, integrations

SCHEMA = """
CREATE TABLE IF NOT EXISTS oa_lz_state (
  shop_id INTEGER, kind TEXT, last_try REAL, last_ok REAL, error TEXT, hint TEXT, rows INTEGER, info TEXT,
  PRIMARY KEY(shop_id, kind)
);
CREATE TABLE IF NOT EXISTS oa_lz_tx (
  shop_id INTEGER, uid TEXT, order_no TEXT, order_item_no TEXT, day TEXT, tx_type TEXT, fee_name TEXT, amount REAL,
  vat REAL, wht REAL, statement TEXT, paid_status TEXT, seller_sku TEXT, is_item INTEGER DEFAULT 0, to_fin INTEGER DEFAULT 0,
  synced_at REAL, raw TEXT, PRIMARY KEY(shop_id, uid)
);
CREATE INDEX IF NOT EXISTS oa_lz_tx_day ON oa_lz_tx(day);
CREATE INDEX IF NOT EXISTS oa_lz_tx_order ON oa_lz_tx(order_no);
CREATE TABLE IF NOT EXISTS oa_lz_review (
  shop_id INTEGER, review_id TEXT, item_id TEXT, product_id TEXT, order_id TEXT, rating INTEGER, product_rating INTEGER,
  seller_rating INTEGER, logistics_rating INTEGER, content TEXT, review_type TEXT, images INTEGER, created REAL,
  can_reply INTEGER, reply TEXT, replied_at REAL, reply_by TEXT, synced_at REAL, raw TEXT,
  PRIMARY KEY(shop_id, review_id)
);
CREATE INDEX IF NOT EXISTS oa_lz_review_created ON oa_lz_review(created);
CREATE TABLE IF NOT EXISTS oa_lz_reverse (
  shop_id INTEGER, line_id TEXT, reverse_id TEXT, order_no TEXT, request_type TEXT, status TEXT, reason TEXT,
  refund_amount REAL, seller_sku TEXT, created REAL, updated REAL, synced_at REAL, raw TEXT,
  PRIMARY KEY(shop_id, line_id)
);
CREATE INDEX IF NOT EXISTS oa_lz_reverse_created ON oa_lz_reverse(created);
CREATE TABLE IF NOT EXISTS oa_lz_perf (
  shop_id INTEGER PRIMARY KEY, at REAL, data TEXT
);
"""
KINDS = {"finance": ("财务流水", "รายการการเงิน", "Finance API"),
         "reviews": ("评价", "รีวิว", "Product Review API"),
         "reverse": ("退货退款", "คืนสินค้า/คืนเงิน", "Return and Refund API"),
         "performance": ("店铺表现", "ประสิทธิภาพร้าน", "Seller API")}
FIRST_DAYS = 30            # 第一次往回拉几天
REVIEW_ITEMS_PER_RUN = 200
TZ = dt.timezone(dt.timedelta(hours=7))
_lock = threading.Lock()
_inited = set()


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()
    _inited.add(db.DB_PATH)


def _ensure():
    if db.DB_PATH not in _inited:
        init()


def _in(shop_ids, col="shop_id"):
    """shop_ids=None → 不筛；[] → 一个都不要；[1, 2] → 只要这几个店铺。返回 (SQL 片段, 参数)。"""
    if shop_ids is None:
        return "", ()
    ids = [int(x) for x in shop_ids]
    return (f" AND {col} IN ({','.join('?' * len(ids))})", tuple(ids)) if ids else (" AND 0", ())


def shop_ids_of(name):
    """店铺筛选（订单里的店铺名）→ Lazada 店铺 id 列表（名字对不上 = []）。"""
    n = str(name or "").strip().lower()
    return [s["id"] for s in shops() if (s["name"] or "").strip().lower() == n]


def shops():
    """开着的 Lazada 店铺 [{id, name}]。"""
    return [{"id": r["id"], "name": r["name"]} for r in db.conn().execute(
        "SELECT id, name FROM shops WHERE enabled=1 AND platform='lazada' ORDER BY id")]


# ---------------- 出错说明 ----------------
PERM_WORDS = ("permission", "not authorized", "unauthorized", "no access", "access denied", "accessdenied", "insufficient",
              "apinotfound", "api not found", "invalid api", "not allowed", "forbidden", "apppermission", "mp3seller")


def hint_of(kind, err, th=False):
    """出错了怎么办（th=True 给泰文）。"""
    e = str(err or "").lower()
    api_name = KINDS.get(kind, ("", "", ""))[2]
    if "在线商品" in e:
        return ("ยังไม่มีสินค้าออนไลน์ที่กำลังขาย: ไปที่「สินค้า → สินค้าออนไลน์」กด「ซิงค์ตอนนี้」ก่อน" if th else
                "先到「商品 → 在线商品」点「立即同步」，把店里的商品拉进来。")
    if "缺少" in e:
        return ("ร้านยังกรอกข้อมูลการอนุญาตไม่ครบ: ไปที่「ตั้งค่า → AI และการเชื่อมต่อ → เชื่อมต่อร้าน」" if th else
                "店铺还没填完授权信息：到「设置 → AI 与对接 → 店铺对接」。")
    if any(w in e for w in PERM_WORDS):
        return (f"แอปนี้ยังไม่มีสิทธิ์ใช้「{api_name}」: ขอสิทธิ์ที่ open.lazada.com → App Console → แอปของคุณ → API แล้วอนุญาตร้านใหม่ที่"
                "「ตั้งค่า → AI และการเชื่อมต่อ → เชื่อมต่อร้าน」 ถ้าเป็นแอปแยก ให้กรอก「แอปข้อมูล」ในตั้งค่าร้านแล้วกดอนุญาต" if th else
                f"这个应用还没有「{api_name}」的接口权限：到 open.lazada.com → App Console → 你的应用 → API 权限里申请，"
                "批下来后到「设置 → AI 与对接 → 店铺对接」重新授权一次店铺。"
                "如果这类接口在 Lazada 是另外建的应用（例如数据分析类的应用），在店铺设置里填「数据应用 App Key / Secret」，再点「数据应用授权」。")
    if "token" in e or "illegalaccess" in e or "session" in e:
        return ("การอนุญาตร้านหมดอายุ: อนุญาตใหม่ที่「ตั้งค่า → AI และการเชื่อมต่อ → เชื่อมต่อร้าน」" if th else
                "店铺授权过期了：到「设置 → AI 与对接 → 店铺对接」重新授权。")
    if "traffic" in e or "frequency" in e or "limit" in e:
        return "Lazada จำกัดความถี่การเรียก API เดี๋ยวระบบจะลองใหม่เอง" if th else "Lazada 限制调用频率，过一会儿会自动再试。"
    return ""


def _state(shop_id, kind):
    r = db.conn().execute("SELECT * FROM oa_lz_state WHERE shop_id=? AND kind=?", (shop_id, kind)).fetchone()
    return dict(r) if r else {}


def _set_state(shop_id, kind, ok, rows=0, error="", info=None):
    c = db.conn()
    now = time.time()
    old = _state(shop_id, kind)
    c.execute("INSERT OR REPLACE INTO oa_lz_state(shop_id, kind, last_try, last_ok, error, hint, rows, info) VALUES(?,?,?,?,?,?,?,?)",
              (shop_id, kind, now, now if ok else old.get("last_ok"), "" if ok else str(error)[:500], "" if ok else hint_of(kind, error),
               rows, json.dumps(info, ensure_ascii=False) if info is not None else old.get("info")))
    c.commit()


# ---------------- 小工具 ----------------
def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _int(v):
    n = _num(v)
    return int(n) if n is not None else None


def _ms(v):
    """毫秒 / 秒 / 文字时间 → Unix 秒。"""
    n = _num(v)
    if n is not None:
        return n / 1000 if n > 1e11 else n
    from core.connectors.lazada import _ts
    return _ts(v)


def _day(s):
    """'17 May 2016' / '2016-05-17' / 毫秒 → 'YYYY-MM-DD'。"""
    s = str(s or "").strip()
    for fmt in ("%d %b %Y", "%Y-%m-%d", "%d %B %Y", "%d/%m/%Y"):
        for cand in (s, s[:10], s[:11]):
            try:
                return dt.datetime.strptime(cand, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    t = _ms(s)
    return dt.datetime.fromtimestamp(t, TZ).strftime("%Y-%m-%d") if t else ""


def _is_item(tx_type, fee_name):
    t = f"{tx_type} {fee_name}".lower()
    return "item price" in t or "ราคาสินค้า" in t


# ---------------- 财务流水 ----------------
def _tx_rows(shop_id, lines):
    out = []
    for x in lines:
        if not isinstance(x, dict):
            continue
        amount = _num(x.get("amount"))
        if amount is None:
            continue
        uid = "|".join(str(x.get(k) or "") for k in ("transaction_number", "orderItem_no", "order_no", "transaction_type", "fee_name",
                                                      "amount", "transaction_date", "reference"))
        tx_type, fee = str(x.get("transaction_type") or ""), str(x.get("fee_name") or "")
        out.append({"uid": uid, "order_no": str(x.get("order_no") or ""), "order_item_no": str(x.get("orderItem_no") or ""),
                    "day": _day(x.get("transaction_date")), "tx_type": tx_type, "fee_name": fee or tx_type, "amount": amount,
                    "vat": abs(_num(x.get("VAT_in_amount")) or 0), "wht": abs(_num(x.get("WHT_amount")) or 0),
                    "statement": str(x.get("statement") or ""), "paid_status": str(x.get("paid_status") or ""),
                    "seller_sku": str(x.get("seller_sku") or "").upper(), "is_item": 1 if _is_item(tx_type, fee) else 0, "raw": x})
    return out


def sync_finance(conn, shop, user="系统"):
    st = _state(shop["id"], "finance")
    today = dt.datetime.now(TZ).date()
    start = today - dt.timedelta(days=FIRST_DAYS)
    if st.get("last_ok"):
        start = max(start, dt.datetime.fromtimestamp(st["last_ok"], TZ).date() - dt.timedelta(days=7))   # 往回多拉一周（流水会补记）
    c = db.conn()
    n, offset = 0, 0
    now = time.time()
    while offset < 20000:
        lines = conn.finance_transactions(start.isoformat(), today.isoformat(), offset, 500)
        for r in _tx_rows(shop["id"], lines):
            cur = c.execute("INSERT OR IGNORE INTO oa_lz_tx(shop_id, uid, order_no, order_item_no, day, tx_type, fee_name, amount, vat, wht, "
                            "statement, paid_status, seller_sku, is_item, synced_at, raw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (shop["id"], r["uid"], r["order_no"], r["order_item_no"], r["day"], r["tx_type"], r["fee_name"], r["amount"],
                             r["vat"], r["wht"], r["statement"], r["paid_status"], r["seller_sku"], r["is_item"], now,
                             json.dumps(r["raw"], ensure_ascii=False)[:2000]))
            n += cur.rowcount
        c.commit()
        offset += len(lines)
        if len(lines) < 500:
            break
    fin = push_to_fin(shop, user)
    return {"new": n, "fin": fin}


def push_to_fin(shop, user="系统"):
    """把「拉到了商品金额那一行」的订单的流水交给财务模块（一个订单只拉到一半的费用时不交：不然到账算少了，扣费算多了）。
    没有订单号的（店铺级调整、广告费等）也交。返回财务模块的结果，财务模块关着返回 None。"""
    from core import modules
    fin = modules.public("fin")
    if not fin or not hasattr(fin, "settle_import_lines"):
        return None
    c = db.conn()
    ready = {r[0] for r in c.execute("SELECT DISTINCT order_no FROM oa_lz_tx WHERE shop_id=? AND is_item=1 AND COALESCE(order_no,'')!=''",
                                     (shop["id"],))}
    rows = [dict(r) for r in c.execute("SELECT * FROM oa_lz_tx WHERE shop_id=? AND to_fin=0", (shop["id"],))]
    send = [r for r in rows if not r["order_no"] or r["order_no"] in ready]
    if not send:
        return {"new_rows": 0, "orders": 0, "matched": 0}
    res = fin.settle_import_lines("lazada", shop["name"], [
        {"order_no": r["order_no"], "fee_name": r["fee_name"], "amount": r["amount"], "wht": r["wht"], "vat": r["vat"], "day": r["day"],
         "ref": r["statement"], "uid": f"lazada-api|{shop['id']}|{r['uid']}", "is_item": r["is_item"]} for r in send],
        f"Lazada 接口 · {shop['name']}", user)
    for i in range(0, len(send), 500):
        chunk = [r["uid"] for r in send[i:i + 500]]
        c.execute(f"UPDATE oa_lz_tx SET to_fin=1 WHERE shop_id=? AND uid IN ({','.join('?' * len(chunk))})", (shop["id"], *chunk))
    c.commit()
    return res


def fee_rates(days=30, shop_ids=None):
    """真实扣点：近 N 天流水里 平台扣的钱 ÷ 商品金额，按费用名分开（shop_ids 只算这几个店铺）。"""
    _ensure()
    since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
    w, a = _in(shop_ids)
    rows = db.conn().execute(f"SELECT fee_name, is_item, SUM(amount) a, COUNT(*) n FROM oa_lz_tx WHERE day>=?{w} GROUP BY fee_name, is_item",
                             (since, *a)).fetchall()
    item = sum(r["a"] or 0 for r in rows if r["is_item"])
    fees = [{"fee_name": r["fee_name"], "amount": round(r["a"] or 0, 2), "lines": r["n"],
             "rate": round(-(r["a"] or 0) / item * 100, 2) if item else None} for r in rows if not r["is_item"]]
    fees.sort(key=lambda x: x["amount"])
    deducted = -sum(f["amount"] for f in fees if f["amount"] < 0)
    return {"item_amount": round(item, 2), "deducted": round(deducted, 2), "credits": round(sum(f["amount"] for f in fees if f["amount"] > 0), 2),
            "rate": round(deducted / item * 100, 2) if item else None, "fees": fees[:30], "days": days}


# ---------------- 评价 ----------------
def _rev_row(x):
    rt = x.get("ratings") or {}
    overall = _int(rt.get("overall_rating")) or _int(rt.get("product_rating")) or _int(x.get("rating"))
    return {"review_id": str(x.get("id") or x.get("review_id") or ""), "product_id": str(x.get("product_id") or ""),
            "order_id": str(x.get("order_id") or ""), "rating": overall, "product_rating": _int(rt.get("product_rating")),
            "seller_rating": _int(rt.get("seller_rating")), "logistics_rating": _int(rt.get("logistics_rating")),
            "content": str(x.get("review_content") or x.get("content") or "")[:2000], "review_type": str(x.get("review_type") or ""),
            "images": len(x.get("review_images") or []) + len(x.get("review_videos") or []),
            "created": _ms(x.get("create_time") or x.get("submit_time")),
            "can_reply": 0 if str(x.get("can_reply", "true")).lower() == "false" else 1,
            "reply": str(x.get("seller_reply") or "")}


def sync_reviews(conn, shop, item_ids, user="系统"):
    st = _state(shop["id"], "reviews")
    now = time.time()
    since = now - FIRST_DAYS * 86400
    if st.get("last_ok"):
        since = max(since, st["last_ok"] - 2 * 86400)
    since = max(since, now - 89 * 86400)
    windows, t = [], since
    while t < now:
        windows.append((t, min(now, t + 7 * 86400 - 60)))
        t += 7 * 86400 - 60
    c = db.conn()
    new = 0
    for item in item_ids[:REVIEW_ITEMS_PER_RUN]:
        ids = []
        for a, b in windows:
            page = 1
            while page <= 50:
                d = conn.review_ids(item, a * 1000, b * 1000, page)
                got = [str(x) for x in (d.get("id_list") or [])]
                ids += got
                total = _int(d.get("total")) or 0
                if not got or len(ids) >= total or len(got) < (_int(d.get("page_size")) or 10):
                    break
                page += 1
        have = {r[0] for r in c.execute("SELECT review_id FROM oa_lz_review WHERE shop_id=? AND item_id=?", (shop["id"], str(item)))}
        todo = [x for x in dict.fromkeys(ids) if x not in have]
        # 没回复的老评价也要刷新（可能在卖家中心回复了）
        todo += [r[0] for r in c.execute("SELECT review_id FROM oa_lz_review WHERE shop_id=? AND item_id=? AND COALESCE(reply,'')='' "
                                         "AND created>=?", (shop["id"], str(item), now - 30 * 86400))]
        for i in range(0, len(todo), 10):
            for x in conn.reviews(todo[i:i + 10]):
                r = _rev_row(x)
                if not r["review_id"]:
                    continue
                old = c.execute("SELECT reply, replied_at, reply_by FROM oa_lz_review WHERE shop_id=? AND review_id=?",
                                (shop["id"], r["review_id"])).fetchone()
                new += 0 if old else 1
                c.execute("INSERT OR REPLACE INTO oa_lz_review(shop_id, review_id, item_id, product_id, order_id, rating, product_rating, "
                          "seller_rating, logistics_rating, content, review_type, images, created, can_reply, reply, replied_at, reply_by, "
                          "synced_at, raw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (shop["id"], r["review_id"], str(item), r["product_id"], r["order_id"], r["rating"], r["product_rating"],
                           r["seller_rating"], r["logistics_rating"], r["content"], r["review_type"], r["images"], r["created"],
                           r["can_reply"], r["reply"] or (old["reply"] if old else ""), old["replied_at"] if old else None,
                           old["reply_by"] if old else None, now, json.dumps(x, ensure_ascii=False)[:3000]))
        c.commit()
    return {"items": min(len(item_ids), REVIEW_ITEMS_PER_RUN), "new": new}


def reply_review(shop_id, review_id, content, user=""):
    content = str(content or "").strip()
    if not content:
        raise ValueError("回复不能是空的")
    if len(content) > 500:
        raise ValueError("回复最多 500 个字")
    r = db.conn().execute("SELECT * FROM oa_lz_review WHERE shop_id=? AND review_id=?", (int(shop_id), str(review_id))).fetchone()
    if not r:
        raise ValueError("没有这条评价")
    if r["reply"]:
        raise ValueError("这条评价已经回复过了")
    conn = _conn(int(shop_id))
    try:
        conn.review_reply(review_id, content)
    finally:
        integrations._store_creds(int(shop_id), conn)
    c = db.conn()
    c.execute("UPDATE oa_lz_review SET reply=?, replied_at=?, reply_by=? WHERE shop_id=? AND review_id=?",
              (content, time.time(), user or "", int(shop_id), str(review_id)))
    c.commit()
    db.audit(user, "回复 Lazada 评价", str(review_id), content[:200])
    return {"ok": True}


def reviews_list(days=30, bad_only=False, unreplied=False, limit=300, shop_ids=None):
    _ensure()
    w, wa = _in(shop_ids)
    q = "SELECT * FROM oa_lz_review WHERE created>=?" + w
    a = [time.time() - int(days) * 86400, *wa]
    if bad_only:
        q += " AND rating IS NOT NULL AND rating<=3"
    if unreplied:
        q += " AND COALESCE(reply,'')='' AND can_reply=1"
    rows = [dict(r) for r in db.conn().execute(q + " ORDER BY created DESC LIMIT ?", (*a, int(limit)))]
    names = {s["id"]: s["name"] for s in (dict(r) for r in db.conn().execute("SELECT id, name FROM shops"))}
    items = _item_names()
    for r in rows:
        r.pop("raw", None)
        r["shop"] = names.get(r["shop_id"], "")
        r["item_name"], r["product_code"] = items.get(r["item_id"], ("", ""))
    return rows


def _item_names():
    """item_id → (商品名, ERP 产品编号)：从上架模块的在线商品里取（关着就空）。"""
    from core import modules
    lst = modules.public("listing")
    if not lst or not hasattr(lst, "online_item_names"):
        return {}
    try:
        return lst.online_item_names("lazada")
    except Exception:  # noqa: BLE001
        return {}


# ---------------- 退货退款 ----------------
def _money(v):
    if v is None or v == "":
        return None
    if isinstance(v, dict):
        v = v.get("amount") if "amount" in v else v.get("value")
    return _num(v)


def _erp_price(order_no, sku):
    """ERP 里这个订单这个 SKU 的单价（用来认出 Lazada 给的金额是不是「分」）。"""
    r = db.conn().execute("SELECT i.unit_price, i.item_total, i.qty, o.order_total FROM orders o JOIN order_items i ON i.order_id=o.id "
                          "WHERE o.platform='lazada' AND o.order_no=? ORDER BY (UPPER(COALESCE(i.sku,''))=?) DESC LIMIT 1",
                          (str(order_no), str(sku or "").upper())).fetchone()
    if not r:
        return None
    return r["unit_price"] or ((r["item_total"] or 0) / (r["qty"] or 1)) or r["order_total"]


def _refund(ln, order_no):
    """退款金额（铢）。文档里是字符串，没写单位；Lazada 退货接口有的版本给「分」。
    对照 ERP 里这个订单的单价：比单价大 20 倍以上就当成「分」÷ 100。"""
    refund = _money(ln.get("refund_amount"))
    if refund is None:
        refund = _money(ln.get("refund_payment_amount"))
    if not refund:
        return refund
    ref = _erp_price(order_no, ln.get("seller_sku_id") or ln.get("seller_sku")) or _money(ln.get("item_unit_price"))
    if ref and refund > 20 * ref:
        refund = refund / 100
    return round(refund, 2)


def _rev_lines(x):
    """一个退货单 → [行]（每个退货商品一行）。"""
    lines = x.get("reverse_order_lines") or x.get("reverse_order_line_list") or x.get("lines") or [x]
    out = []
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        refund = _refund(ln, x.get("trade_order_id") or ln.get("trade_order_id"))
        if str(ln.get("is_need_refund", "true")).lower() == "false":
            refund = 0.0
        out.append({"line_id": str(ln.get("reverse_order_line_id") or ln.get("trade_order_line_id") or x.get("reverse_order_id") or ""),
                    "reverse_id": str(x.get("reverse_order_id") or ""), "order_no": str(x.get("trade_order_id") or ln.get("trade_order_id") or ""),
                    "request_type": str(x.get("request_type") or ln.get("request_type") or ""),
                    "status": str(ln.get("reverse_status") or x.get("reverse_status") or ln.get("ofc_status") or x.get("status") or ""),
                    "reason": str(ln.get("reason_text") or ln.get("return_reason") or ln.get("reason") or x.get("reason_text") or "")[:300],
                    "refund_amount": refund, "seller_sku": str(ln.get("seller_sku_id") or ln.get("seller_sku") or "").upper(),
                    "created": _ms(ln.get("return_order_line_gmt_create") or ln.get("gmt_create") or x.get("gmt_create")
                                   or x.get("created_at") or x.get("create_time")),
                    "updated": _ms(ln.get("return_order_line_gmt_modified") or ln.get("gmt_modified") or x.get("gmt_modified")
                                   or x.get("updated_at")), "raw": ln})
    return out


def sync_reverse(conn, shop, user="系统"):
    st = _state(shop["id"], "reverse")
    now = time.time()
    since = now - FIRST_DAYS * 86400
    if st.get("last_ok"):
        since = max(since, st["last_ok"] - 3 * 86400)
    c = db.conn()
    page, n = 1, 0
    while page <= 100:
        d = conn.reverse_orders(page, 50, since * 1000, now * 1000)
        items = d.get("items") or d.get("reverse_orders") or d.get("list") or []
        for x in items:
            for r in _rev_lines(x):
                if not r["line_id"]:
                    continue
                c.execute("INSERT OR REPLACE INTO oa_lz_reverse(shop_id, line_id, reverse_id, order_no, request_type, status, reason, "
                          "refund_amount, seller_sku, created, updated, synced_at, raw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (shop["id"], r["line_id"], r["reverse_id"], r["order_no"], r["request_type"], r["status"], r["reason"],
                           r["refund_amount"], r["seller_sku"], r["created"] or now, r["updated"], now,
                           json.dumps(r["raw"], ensure_ascii=False)[:3000]))
                n += 1
        c.commit()
        total = _int(d.get("total")) or 0
        if len(items) < 50 or page * 50 >= total:
            break
        page += 1
    return {"lines": n}


CLOSED_WORDS = ("close", "cancel", "refund_success", "refunded", "complete", "finish", "reject", "success")


def reverse_list(days=30, limit=300, shop_ids=None):
    _ensure()
    w, wa = _in(shop_ids)
    rows = [dict(r) for r in db.conn().execute(f"SELECT * FROM oa_lz_reverse WHERE created>=?{w} ORDER BY created DESC LIMIT ?",
                                               (time.time() - int(days) * 86400, *wa, int(limit)))]
    names = {r["id"]: r["name"] for r in db.conn().execute("SELECT id, name FROM shops")}
    for r in rows:
        r.pop("raw", None)
        r["shop"] = names.get(r["shop_id"], "")
        r["open"] = not any(w in (r["status"] or "").lower() for w in CLOSED_WORDS)
    return rows


# ---------------- 店铺表现 ----------------
def _flat(d, pre="", out=None, depth=0):
    """店铺表现的 data 结构没有固定格式：摊平成 [(名字, 值)]，页面上照原样列出来。"""
    out = out if out is not None else []
    if depth > 4 or len(out) > 80:
        return out
    if isinstance(d, dict):
        name = d.get("name") or d.get("title") or d.get("indicator_name") or d.get("metric_name")
        val = next((d.get(k) for k in ("value", "score", "current_value", "rate", "display_value") if d.get(k) not in (None, "")), None)
        if name and val is not None and not isinstance(val, (dict, list)):
            out.append({"name": str(name), "value": str(val), "target": str(d.get("target") or d.get("threshold") or d.get("standard") or ""),
                        "status": str(d.get("status") or d.get("level") or "")})
            return out
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                _flat(v, f"{pre}{k}.", out, depth + 1)
            elif v not in (None, "") and not str(k).endswith("_id"):
                out.append({"name": f"{pre}{k}", "value": str(v), "target": "", "status": ""})
    elif isinstance(d, list):
        for v in d:
            _flat(v, pre, out, depth + 1)
    return out


def _metrics(d):
    """{indicators:[…]}（文档里的格式）→ [{name, value, target, ok, type}]；格式不一样就摊平原样显示。"""
    inds = d.get("indicators") if isinstance(d, dict) else None
    if isinstance(inds, list) and inds:
        out = []
        for i in inds:
            if not isinstance(i, dict):
                continue
            ok = str(i.get("target_respected", "")).lower()
            out.append({"name": str(i.get("name") or i.get("type") or ""), "type": str(i.get("type") or ""),
                        "value": str(i.get("formatted_score") or i.get("score") or ""), "target": str(i.get("formatted_target") or i.get("target") or ""),
                        "ok": True if ok == "true" else (False if ok == "false" else None)})
        return out
    return [{"name": m["name"], "type": "", "value": m["value"], "target": m["target"], "ok": None} for m in _flat(d)]


# v2.49：店铺表现的指标名（接口给的是英文 / 代码）→ 中文、泰文；better = 越高越好 high / 越低越好 low
# v2.51：补全 Lazada 卖家表现里见过的指标（Basket size、转化率、访客……）；对不上的按代码转成能读的英文（BASKET_SIZE → Basket size）
PERF_NAMES = [
    (r"basket|\baov\b|average.?order.?value|avg.?order|ขนาดตะกร้า|มูลค่าตะกร้า", "客单价（每单金额）", "มูลค่าเฉลี่ยต่อออเดอร์", "high"),
    (r"cancel|ยกเลิก", "取消率", "อัตราการยกเลิก", "low"),
    (r"fast.?(ship|deliver|handover)|\bffd\b|ส่งด่วน|ส่งเร็ว", "快速发货率", "อัตราส่งสินค้าเร็ว", "high"),
    (r"late|lsr|ล่าช้า", "迟发率", "อัตราส่งล่าช้า", "low"),
    (r"ship.?on.?time|on.?time|\bsot\b|ส่งตรงเวลา|ตรงเวลา", "准时发货率", "อัตราส่งตรงเวลา", "high"),
    (r"response.?time|reply.?time|เวลาตอบ", "聊天回复时间", "เวลาตอบแชท", "low"),
    (r"response|chat|reply|ตอบแชท|อัตราการตอบ", "聊天回复率", "อัตราการตอบแชท", "high"),
    (r"positive|seller.?rating|\bpsr\b|shop.?rating|store.?rating|คะแนนร้าน", "店铺好评率", "คะแนนร้านเชิงบวก", "high"),
    (r"product.?rating|review|rating|คะแนนสินค้า|รีวิว", "商品评分", "คะแนนสินค้า", "high"),
    (r"return|refund|คืนสินค้า|คืนเงิน", "退货退款率", "อัตราคืนสินค้า/คืนเงิน", "low"),
    (r"fake|counterfeit|ipr|violat|penalt|point|ละเมิด|คะแนนโทษ", "违规扣分", "คะแนนโทษ", "low"),
    (r"fail|ndr|non.?deliver|ส่งไม่สำเร็จ", "派送失败率", "อัตราส่งไม่สำเร็จ", "low"),
    (r"fulfil|ffr|จัดส่งสำเร็จ", "履约率", "อัตราการจัดส่งสำเร็จ", "high"),
    (r"conversion|\bcvr\b|\bcr\b|อัตราการซื้อ|คอนเวอร์ชัน", "转化率", "อัตราการซื้อ", "high"),
    (r"visitor|traffic|\buv\b|page.?view|\bpv\b|ผู้เข้าชม", "访客数", "จำนวนผู้เข้าชม", "high"),
    (r"\bgmv\b|revenue|sales|ยอดขาย", "销售额", "ยอดขาย", "high"),
    (r"buyer|customer|ผู้ซื้อ|ลูกค้า", "买家数", "จำนวนผู้ซื้อ", "high"),
    (r"content|quality|image|คุณภาพ", "商品信息质量", "คุณภาพข้อมูลสินค้า", "high"),
    (r"campaign|promotion|voucher|แคมเปญ|โปรโมชั่น", "活动参与", "การเข้าร่วมแคมเปญ", "high"),
    (r"listing|sku|สินค้าที่ลง", "在售商品数", "จำนวนสินค้าที่ขาย", "high"),
    (r"order|ออเดอร์|คำสั่งซื้อ", "订单数", "จำนวนออเดอร์", "high"),
]
NO_DATA = {"", "-", "--", "—", "n/a", "na", "null", "none", "nan", "no data", "ไม่มีข้อมูล", "暂无数据"}


def _numv(v):
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(v or "").replace(",", ""))
    return float(m.group(0)) if m else None


def readable(name):
    """指标代码 → 能读的英文：BASKET_SIZE / basketSize → Basket size。"""
    t = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name or "")).replace("_", " ").replace(".", " ").strip()
    t = re.sub(r"\s+", " ", t)
    return t[:1].upper() + t[1:].lower() if t else ""


def perf_label(m):
    """一个指标：加上 zh / th 名字、数值 v、要求 t、better（high / low）、ok、nodata（接口没给数 → 不算达标也不算不达标）。"""
    raw = f"{m.get('type') or ''} {m.get('name') or ''}".lower()
    zh = th = readable(m.get("name") or m.get("type") or "")
    better, known = None, False
    for pat, z, t, b in PERF_NAMES:
        if re.search(pat, raw):
            zh, th, better, known = z, t, b, True
            break
    tg = str(m.get("target") or "")
    if re.search(r"[<≤]|max|below|ไม่เกิน|น้อยกว่า", tg, re.I):
        better = "low"
    elif re.search(r"[>≥]|min|above|อย่างน้อย|มากกว่า", tg, re.I):
        better = "high"
    val = str(m.get("value") if m.get("value") is not None else "").strip()
    v, t = _numv(val), _numv(tg)
    nodata = val.lower() in NO_DATA or (v is None and not re.search(r"[a-zA-Z฀-๿一-鿿]", val))
    ok = None if nodata else m.get("ok")
    if ok is None and not nodata and v is not None and t is not None and better:
        ok = v <= t if better == "low" else v >= t
    return {**m, "key": str(m.get("type") or m.get("name") or zh), "zh": zh, "th": th, "known": known, "better": better or "high",
            "v": None if nodata else v, "t": t, "ok": ok, "nodata": nodata}


def perf_count(metrics):
    """达标几项 / 有数据又能判断的几项 / 暂无数据几项（没数据的不算达标）。"""
    metrics = list(metrics or [])
    judged = [x for x in metrics if not x.get("nodata") and x.get("ok") is not None]
    return {"ok": sum(1 for x in judged if x["ok"]), "n": len(judged), "nodata": sum(1 for x in metrics if x.get("nodata"))}


def _worse(a, b):
    """两个店铺的同一个指标，哪个更差（不达标比达标差；同样就按 better 比数值）。"""
    ka = (0 if a.get("ok") is False else 1, a["v"] if a["better"] == "high" else -a["v"])
    kb = (0 if b.get("ok") is False else 1, b["v"] if b["better"] == "high" else -b["v"])
    return a if ka <= kb else b


def perf_combined(perf):
    """多个店铺合起来看：每个指标一行，worst = 最差的那个店铺的数，shops = 各店铺的数。"""
    out, idx = [], {}
    for p in perf or []:
        for m in p["metrics"]:
            k = m.get("key") or m["zh"]
            if k not in idx:
                idx[k] = {"key": k, "zh": m["zh"], "th": m["th"], "known": m.get("known", True), "better": m["better"], "shops": []}
                out.append(idx[k])
            idx[k]["shops"].append({**m, "shop_id": p["shop_id"], "shop": p["shop"]})
    for g in out:
        w = None
        for x in g["shops"]:
            if not x.get("nodata") and x.get("v") is not None:
                w = x if w is None else _worse(w, x)
        if w is None:
            w = next((x for x in g["shops"] if not x.get("nodata")), None)
        g["worst"] = w
        g["nodata"] = w is None
        g["ok_n"] = sum(1 for x in g["shops"] if x.get("ok") is True)
        g["bad_n"] = sum(1 for x in g["shops"] if x.get("ok") is False)
        g["nodata_n"] = sum(1 for x in g["shops"] if x.get("nodata"))
    return out


def sync_performance(conn, shop, user="系统"):
    d = conn.seller_performance()
    c = db.conn()
    c.execute("INSERT OR REPLACE INTO oa_lz_perf(shop_id, at, data) VALUES(?,?,?)", (shop["id"], time.time(), json.dumps(d, ensure_ascii=False)))
    c.commit()
    return {"metrics": len(_metrics(d))}


def performance(shop_ids=None):
    """每个店铺一份（oa_lz_perf 一个店铺一行）：[{shop_id, shop, at, metrics, count}]。关掉的店铺不显示。"""
    _ensure()
    names = {s["id"]: s["name"] for s in shops()}
    w, a = _in(shop_ids)
    out = []
    for r in db.conn().execute(f"SELECT * FROM oa_lz_perf WHERE 1=1{w} ORDER BY shop_id", a):
        if r["shop_id"] not in names:
            continue
        try:
            d = json.loads(r["data"] or "{}")
        except ValueError:
            d = {}
        ms = [perf_label(m) for m in _metrics(d)]
        out.append({"shop_id": r["shop_id"], "shop": names.get(r["shop_id"], ""), "at": r["at"], "metrics": ms, "count": perf_count(ms),
                    "category": d.get("main_category_name") if isinstance(d, dict) else ""})
    return out


# ---------------- 同步 ----------------
def _conn(shop_id):
    from core import connectors
    s = integrations.get_shop_raw(int(shop_id))
    conn = connectors.make("lazada", s["creds"])
    conn.check()
    return conn


def _item_ids(shop_id):
    from core import modules
    lst = modules.public("listing")
    if not lst or not hasattr(lst, "online_item_ids"):
        return None
    return lst.online_item_ids("lazada", shop_id, "live")


def sync(shop_id=None, kinds=None, user="系统"):
    """同步开着的 Lazada 店铺。一类出错不影响别的（错误记在 oa_lz_state，页面上显示）。返回 {shops:[{shop, kinds:{kind: 结果 / error}}]}。"""
    _ensure()
    kinds = [k for k in (kinds or KINDS) if k in KINDS]
    out = []
    with _lock:
        for sh in shops():
            if shop_id and sh["id"] != int(shop_id):
                continue
            res = {"shop_id": sh["id"], "shop": sh["name"], "kinds": {}}
            conn = None
            try:
                conn = _conn(sh["id"])
            except Exception as e:  # noqa: BLE001
                for k in kinds:
                    _set_state(sh["id"], k, False, error=str(e))
                    res["kinds"][k] = {"error": str(e)[:300], "hint": hint_of(k, e)}
                out.append(res)
                continue
            for k in kinds:
                try:
                    if k == "finance":
                        r = sync_finance(conn, sh, user)
                    elif k == "reviews":
                        ids = _item_ids(sh["id"])
                        if ids is None:
                            raise RuntimeError("要先打开「上架导出」模块（按在线商品一个个拉评价）")
                        if not ids:
                            raise RuntimeError("这个店铺还没有在售的在线商品：先到「商品 → 在线商品」点「立即同步」，再拉评价")
                        r = sync_reviews(conn, sh, ids, user)
                    elif k == "reverse":
                        r = sync_reverse(conn, sh, user)
                    else:
                        r = sync_performance(conn, sh, user)
                    _set_state(sh["id"], k, True, rows=int(r.get("new") or r.get("lines") or r.get("metrics") or 0), info=r)
                    res["kinds"][k] = r
                except Exception as e:  # noqa: BLE001
                    db.release()
                    _set_state(sh["id"], k, False, error=str(e))
                    res["kinds"][k] = {"error": str(e)[:300], "hint": hint_of(k, e)}
            integrations._store_creds(sh["id"], conn)
            out.append(res)
    return {"shops": out}


def status(shop_ids=None):
    """每个店铺每类数据：上次成功、出错原因和怎么办。"""
    _ensure()
    st = {(r["shop_id"], r["kind"]): dict(r) for r in db.conn().execute("SELECT * FROM oa_lz_state")}
    want = None if shop_ids is None else {int(x) for x in shop_ids}
    out = []
    for sh in shops():
        if want is not None and sh["id"] not in want:
            continue
        for k, (zh, th, api_name) in KINDS.items():
            s = st.get((sh["id"], k)) or {}
            out.append({"shop_id": sh["id"], "shop": sh["name"], "kind": k, "zh": zh, "th": th, "api": api_name,
                        "last_try": s.get("last_try"), "last_ok": s.get("last_ok"), "error": s.get("error") or "", "hint": s.get("hint") or "", "hint_th": hint_of(k, s.get("error"), th=True) if s.get("error") else "",
                        "rows": s.get("rows")})
    return out


def summary(days=30, shop_ids=None):
    """看板用：评价、退货退款、真实扣点、同步出错（shop_ids = 只算这几个店铺；None = 全部）。"""
    _ensure()
    c = db.conn()
    since = time.time() - days * 86400
    w, a = _in(shop_ids)
    rv = c.execute("SELECT COUNT(*) n, AVG(rating) avg, SUM(CASE WHEN rating<=3 THEN 1 ELSE 0 END) bad, "
                   "SUM(CASE WHEN rating<=3 AND COALESCE(reply,'')='' AND can_reply=1 THEN 1 ELSE 0 END) bad_open "
                   f"FROM oa_lz_review WHERE created>=?{w}", (since, *a)).fetchone()
    rs = c.execute(f"SELECT COUNT(DISTINCT reverse_id) n, COUNT(*) lines, SUM(COALESCE(refund_amount,0)) refund FROM oa_lz_reverse WHERE created>=?{w}",
                   (since, *a)).fetchone()
    by_type = {r[0] or "?": r[1] for r in c.execute(f"SELECT request_type, COUNT(DISTINCT reverse_id) FROM oa_lz_reverse WHERE created>=?{w} "
                                                    "GROUP BY request_type", (since, *a))}
    st = status(shop_ids)
    want = None if shop_ids is None else {int(x) for x in shop_ids}
    return {"shops": len([s_ for s_ in shops() if want is None or s_["id"] in want]),
            "reviews": {"n": rv["n"] or 0, "avg": round(rv["avg"], 2) if rv["avg"] else None, "bad": rv["bad"] or 0, "bad_open": rv["bad_open"] or 0},
            "reverse": {"n": rs["n"] or 0, "lines": rs["lines"] or 0, "refund": round(rs["refund"] or 0, 2), "by_type": by_type},
            "fees": fee_rates(days, shop_ids), "errors": [x for x in st if x["error"]],
            "last_ok": c.execute(f"SELECT MAX(last_ok) FROM oa_lz_state WHERE 1=1{w}", a).fetchone()[0]}


def sync_tone(st):
    """一个店铺的同步状态 → {tone: ok / warn / bad, ok, bad, last_ok, errors}（页面上一个小圆点）。"""
    bad = [x for x in st if x["error"]]
    good = [x for x in st if not x["error"] and x["last_ok"]]
    return {"tone": "bad" if bad else ("ok" if good else "warn"), "ok": len(good), "bad": len(bad),
            "last_ok": max([x["last_ok"] or 0 for x in st] or [0]) or None,
            "errors": [{"kind": x["kind"], "zh": x["zh"], "th": x["th"], "error": x["error"][:200], "hint": x["hint"], "hint_th": x["hint_th"]}
                       for x in bad]}


def per_shop(days=30):
    """「各店铺对比」用：每个开着的 Lazada 店铺一份 {shop_id: {shop, reviews, reverse, fees, perf, sync}}。"""
    _ensure()
    c = db.conn()
    since = time.time() - days * 86400
    rv = {r["shop_id"]: r for r in c.execute(
        "SELECT shop_id, COUNT(*) n, AVG(rating) avg, SUM(CASE WHEN rating<=3 THEN 1 ELSE 0 END) bad, "
        "SUM(CASE WHEN rating<=3 AND COALESCE(reply,'')='' AND can_reply=1 THEN 1 ELSE 0 END) bad_open "
        "FROM oa_lz_review WHERE created>=? GROUP BY shop_id", (since,))}
    rs = {r["shop_id"]: r for r in c.execute(
        "SELECT shop_id, COUNT(DISTINCT reverse_id) n, SUM(COALESCE(refund_amount,0)) refund FROM oa_lz_reverse WHERE created>=? GROUP BY shop_id",
        (since,))}
    perf = {p["shop_id"]: p for p in performance()}
    st = status()
    out = {}
    for sh in shops():
        i = sh["id"]
        r, x, p = rv.get(i), rs.get(i), perf.get(i)
        f = fee_rates(days, [i])                   # 和合起来的真实扣点同一个算法（按费用名合计）
        out[i] = {"shop_id": i, "shop": sh["name"],
                  "reviews": {"n": (r["n"] or 0) if r else 0, "avg": round(r["avg"], 2) if r and r["avg"] else None,
                              "bad": (r["bad"] or 0) if r else 0, "bad_open": (r["bad_open"] or 0) if r else 0},
                  "reverse": {"n": (x["n"] or 0) if x else 0, "refund": round((x["refund"] or 0) if x else 0, 2)},
                  "fees": {k: f[k] for k in ("item_amount", "deducted", "credits", "rate")},
                  "perf": p["count"] if p else None, "perf_at": p["at"] if p else None,
                  "sync": sync_tone([x_ for x_ in st if x_["shop_id"] == i])}
    return out


# ---------------- 后台定时 ----------------
_started = False


def _loop():
    from core.config import load_config
    time.sleep(90)                       # 开机先让别的东西跑起来
    while True:
        wait = 3600
        try:
            try:
                every = float(load_config().get("oa_lz_sync_min") or 0)
            except (TypeError, ValueError):
                every = 60
            if every > 0:
                wait = max(10, every) * 60
                from core import modules
                if modules.enabled("ops") and shops():
                    sync()
        except Exception as e:  # noqa: BLE001  下次再试
            print("Lazada 运营数据同步失败：", e)
        finally:
            db.release()
        time.sleep(wait)


def start():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="ops-lazada").start()
