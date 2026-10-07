"""平台结算对账（v2.21）：导入 Lazada / Shopee / TikTok 后台导出的结算 / 收入报表，和系统里的订单对上。

支持两种表格：
  · 每单一行，有「到账金额」列（Shopee 收入报表 Total Released Amount、TikTok Total settlement amount）
  · 每笔费用一行（Lazada 对账单 Account Statement：商品金额、佣金、手续费、运费……各一行，按订单号加起来就是到账）
列名自动认（中 / 英 / 泰），认不出的可以在预览里手动选。同一个文件导两次不会重复（按行内容去重）。

导入后：系统里对上的订单写入「实际到账」（orders.settlement），利润就按真实平台扣费算，不再按扣点估算。
"""
import hashlib
import json
import os
import re
import time
import uuid

from .. import db
from ..config import DATA_DIR
from .common import day_of, r2, settings, ts

DIR = os.path.join(DATA_DIR, "finance", "settle_imports")
SCHEMA = """
CREATE TABLE IF NOT EXISTS fin_settle_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT, shop TEXT, filename TEXT, rows INTEGER, new_rows INTEGER, orders INTEGER,
  total REAL, date_from TEXT, date_to TEXT, username TEXT, created_at REAL, mapping TEXT
);
CREATE TABLE IF NOT EXISTS fin_settle_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER, platform TEXT, shop TEXT, order_no TEXT, order_key TEXT, fee_name TEXT,
  amount REAL, wht REAL DEFAULT 0, vat REAL DEFAULT 0, day TEXT, ref TEXT, row_hash TEXT, is_item INTEGER DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS fin_settle_hash ON fin_settle_lines(platform, row_hash);
CREATE INDEX IF NOT EXISTS fin_settle_order ON fin_settle_lines(platform, order_key);
CREATE INDEX IF NOT EXISTS fin_settle_day ON fin_settle_lines(day);
"""

# 列名（小写，包含即可；越靠前越优先）
FIELDS = {
    "order_no": ["order/adjustment id", "order no.", "order no", "order number", "order id", "order_id", "order sn", "orderid",
                 "หมายเลขคำสั่งซื้อ", "เลขที่คำสั่งซื้อ", "订单号", "订单编号"],
    "net": ["total released amount", "total settlement amount", "settlement amount", "escrow amount", "payout amount",
            "released amount", "net amount", "ยอดเงินที่ได้รับ", "ยอดที่ได้รับ", "ยอดสุทธิ", "结算金额", "到账金额", "实收金额"],
    "amount": ["amount(include vat)", "amount (include vat)", "amount", "จำนวนเงิน", "金额"],
    "fee_name": ["fee name", "fee type", "transaction type", "ประเภทค่าธรรมเนียม", "ประเภทรายการ", "费用名称", "费用类型", "交易类型"],
    "date": ["payout completed date", "transaction date", "settlement time", "settled time", "release date", "statement date",
             "วันที่ทำรายการ", "วันที่", "结算时间", "日期", "date"],
    "wht": ["wht amount", "withholding tax", "wht", "ภาษีหัก ณ ที่จ่าย", "代扣税", "预扣税"],
    "vat": ["vat in amount", "vat amount", "ภาษีมูลค่าเพิ่ม", "增值税"],
    "ref": ["statement number", "statement", "payout id", "transaction number", "เลขที่รายการ", "结算单号"],
}
FIELD_ZH = {"order_no": "订单号", "net": "到账金额（每单一行的表格）", "amount": "金额（每笔费用一行的表格）", "fee_name": "费用名称 / 类型",
            "date": "结算日期", "wht": "代扣税（WHT）", "vat": "费用里的 VAT", "ref": "结算单号"}
NOT_AMOUNT = ("vat", "wht", "include vat?", "currency")
ITEM_WORDS = ("item price", "product price", "item price credit", "ราคาสินค้า", "商品金额", "商品价格", "orders-item", "sales")


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()


def key(order_no):
    """订单号统一写法：去掉空格、引号、前面的 #，只留字母数字（表格里常把长数字存成 '123 或 1.23E+15）。"""
    s = str(order_no or "").strip().lstrip("'#").replace(" ", "")
    if re.fullmatch(r"\d+\.0", s):
        s = s[:-2]
    return re.sub(r"[^0-9A-Za-z]", "", s).upper()


def auto_map(headers):
    cand = []
    for ci, h in enumerate(headers):
        hl = str(h or "").lower().strip()
        if not hl:
            continue
        for field, words in FIELDS.items():
            for rank, w in enumerate(words):
                if field == "amount" and any(x in hl for x in NOT_AMOUNT) and "include vat" not in hl:
                    continue
                if w == hl:
                    cand.append((0, rank, -len(w), ci, field))
                elif w in hl:
                    cand.append((1, rank, -len(w), ci, field))
    cand.sort()
    used_c, used_f, out = set(), set(), {}
    for _a, _r, _l, ci, field in cand:
        if ci in used_c or field in used_f:
            continue
        out[field] = ci
        used_c.add(ci)
        used_f.add(field)
    if "net" in out:
        out.pop("amount", None)
    return out


def _guess_platform(text):
    from ..orders import guess_platform
    t = str(text or "").lower()
    if "released amount" in t or "escrow" in t:
        return "shopee"
    if "statement" in t or "fee name" in t:
        return guess_platform(t) or "lazada"
    if "order/adjustment id" in t or "settlement amount" in t:
        return "tiktok"
    return guess_platform(t)


def preview(f):
    from ..orders import _cell, _read_rows
    os.makedirs(DIR, exist_ok=True)
    ext = os.path.splitext(f.filename or "")[1].lower() or ".xlsx"
    if ext not in (".xlsx", ".xlsm", ".csv", ".txt"):
        raise ValueError("请上传 .xlsx 或 .csv 表格（旧的 .xls 请先用 Excel 另存为 .xlsx）")
    token = uuid.uuid4().hex[:12]
    path = os.path.join(DIR, token + ext)
    f.save(path)
    rows = _read_rows(path)
    if not rows:
        raise ValueError("表格是空的")
    best, hi = -1, 0
    for i, r in enumerate(rows[:20]):
        s = len(auto_map([_cell(c) for c in r]))
        if s > best:
            best, hi = s, i
    headers = [_cell(c) for c in rows[hi]]
    data = [[_cell(c) for c in r] for r in rows[hi + 1:] if any(_cell(c) for c in r)]
    mapping = auto_map(headers)
    with open(os.path.join(DIR, token + ".json"), "w", encoding="utf-8") as fp:
        json.dump({"path": path, "header_row": hi, "filename": f.filename}, fp)
    return {"token": token, "headers": headers, "sample": data[:8], "rows": len(data), "mapping": mapping,
            "platform": _guess_platform((f.filename or "") + " " + " ".join(headers)), "fields": FIELD_ZH}


def _is_item(name):
    n = str(name or "").lower()
    return any(w in n for w in ITEM_WORDS)


def do_import(token, mapping, platform, shop="", user=""):
    from ..orders import _cell, _num, _read_rows, _time
    token = re.sub(r"[^0-9a-f]", "", str(token or ""))
    meta_p = os.path.join(DIR, token + ".json")
    if not token or not os.path.exists(meta_p):
        raise ValueError("上传的表格过期了，请重新选择文件")
    meta = json.load(open(meta_p, encoding="utf-8"))
    platform = (platform or "").strip().lower()
    if platform not in ("lazada", "shopee", "tiktok", "other"):
        raise ValueError("请选择平台")
    mp = {k: int(v) for k, v in (mapping or {}).items() if v not in (None, "", -1, "-1") and k in FIELDS}
    if "order_no" not in mp:
        raise ValueError("请选择「订单号」是哪一列")
    if "net" not in mp and "amount" not in mp:
        raise ValueError("请选择「到账金额」或「金额」是哪一列")
    rows = _read_rows(meta["path"])[meta["header_row"] + 1:]
    c = db.conn()
    cur = c.execute("INSERT INTO fin_settle_batches(platform, shop, filename, rows, username, created_at, mapping) VALUES(?,?,?,?,?,?,?)",
                    (platform, shop or "", meta.get("filename") or "", 0, user, time.time(), json.dumps(mp)))
    bid = cur.lastrowid
    n = new = 0
    touched, days = set(), []
    for r in rows:
        cells = [_cell(x) for x in r]
        if not any(cells):
            continue
        get = (lambda f: cells[mp[f]] if f in mp and mp[f] < len(cells) else "")
        amount = _num(get("net") if "net" in mp else get("amount"))
        on = get("order_no")
        if amount is None or (not on and not amount):
            continue
        n += 1
        t = _time(get("date")) if "date" in mp else None
        day = day_of(t) if t else ""
        if day:
            days.append(day)
        fee = get("fee_name") if "fee_name" in mp else ("settlement" if "net" in mp else "")
        h = hashlib.sha1(("|".join(cells)).encode("utf-8", "ignore")).hexdigest()[:24]
        try:
            c.execute("INSERT INTO fin_settle_lines(batch_id, platform, shop, order_no, order_key, fee_name, amount, wht, vat, day, ref, "
                      "row_hash, is_item) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (bid, platform, shop or "", on, key(on), str(fee)[:80], amount, abs(_num(get("wht")) or 0), abs(_num(get("vat")) or 0),
                       day, get("ref")[:60], h, 1 if ("net" not in mp and _is_item(fee)) else 0))
            new += 1
            if on:
                touched.add(key(on))
        except Exception as e:  # noqa: BLE001  同一行导过了（唯一索引）
            if "UNIQUE" not in str(e):
                raise
    total = c.execute("SELECT COALESCE(SUM(amount),0) FROM fin_settle_lines WHERE batch_id=?", (bid,)).fetchone()[0]
    c.execute("UPDATE fin_settle_batches SET rows=?, new_rows=?, orders=?, total=?, date_from=?, date_to=? WHERE id=?",
              (n, new, len(touched), r2(total), min(days) if days else "", max(days) if days else "", bid))
    c.commit()
    matched = _apply(platform, touched)
    db.audit(user, "财务·导入平台结算", f"{platform} {shop}".strip(), f"{meta.get('filename')}：{new} 行新数据，{len(touched)} 个订单，对上 {matched} 个")
    try:
        os.remove(meta["path"]); os.remove(meta_p)
    except OSError:
        pass
    return {"batch": bid, "rows": n, "new_rows": new, "dup_rows": n - new, "orders": len(touched), "matched": matched,
            "total": r2(total)}


def _order_index(c, platform):
    idx = {}
    for o in c.execute("SELECT id, order_no FROM orders WHERE platform=?", (platform,)):
        idx[key(o["order_no"])] = o["id"]
    return idx


def _apply(platform, keys):
    """把每个订单的结算合计写进 orders.settlement（只有对得上的）。返回对上的订单数。"""
    if not keys:
        return 0
    c = db.conn()
    idx = _order_index(c, platform)
    n = 0
    for k in keys:
        oid = idx.get(k)
        if not oid:
            continue
        s = c.execute("SELECT SUM(amount) a FROM fin_settle_lines WHERE platform=? AND order_key=?", (platform, k)).fetchone()["a"]
        c.execute("UPDATE orders SET settlement=? WHERE id=?", (r2(s), oid))
        n += 1
    c.commit()
    return n


def sync_pending():
    """订单是在结算表之后才导入的：补写到账金额。"""
    c = db.conn()
    for p in [r["platform"] for r in c.execute("SELECT DISTINCT platform FROM fin_settle_lines")]:
        idx = _order_index(c, p)
        missing = {k for k, oid in idx.items()
                   if c.execute("SELECT 1 FROM orders WHERE id=? AND settlement IS NULL", (oid,)).fetchone()}
        have = {r["order_key"] for r in c.execute("SELECT DISTINCT order_key FROM fin_settle_lines WHERE platform=?", (p,))}
        _apply(p, missing & have)


def batches(limit=50):
    return [dict(r) for r in db.conn().execute("SELECT * FROM fin_settle_batches ORDER BY id DESC LIMIT ?", (int(limit),))]


def delete_batch(bid, user=""):
    c = db.conn()
    b = c.execute("SELECT * FROM fin_settle_batches WHERE id=?", (int(bid),)).fetchone()
    if not b:
        raise ValueError("没有这次导入")
    keys = {r["order_key"] for r in c.execute("SELECT DISTINCT order_key FROM fin_settle_lines WHERE batch_id=?", (int(bid),))}
    c.execute("DELETE FROM fin_settle_lines WHERE batch_id=?", (int(bid),))
    c.execute("DELETE FROM fin_settle_batches WHERE id=?", (int(bid),))
    idx = _order_index(c, b["platform"])
    for k in keys:
        oid = idx.get(k)
        if not oid:
            continue
        s = c.execute("SELECT SUM(amount) a, COUNT(*) n FROM fin_settle_lines WHERE platform=? AND order_key=?", (b["platform"], k)).fetchone()
        c.execute("UPDATE orders SET settlement=? WHERE id=?", (r2(s["a"]) if s["n"] else None, oid))
    c.commit()
    db.audit(user, "财务·删除结算导入", str(bid), b["filename"] or "")


def order_lines(platform, order_no):
    return [dict(r) for r in db.conn().execute("SELECT fee_name, amount, wht, vat, day, ref FROM fin_settle_lines WHERE platform=? AND order_key=? "
                                               "ORDER BY id", (platform, key(order_no)))]


def reconcile(start, end):
    """对账（按下单日期的期间）：
       settled 已回款的订单（到账 vs 订单金额，平台实际扣了多少）
       diff    平台扣费比按扣点估算的多出 容差 以上的
       unpaid  已发货 / 已完成超过 N 天还没有回款记录的
       unknown 结算表里有、系统里找不到的订单号（订单没导入？）"""
    from ..config import load_config
    from ..finance import EXCLUDE
    cfg = load_config()
    st = settings(cfg)
    sync_pending()
    c = db.conn()
    s_ts, e_ts = ts(start), ts(end)
    orders = c.execute(f"SELECT id, platform, shop, order_no, status, order_time, order_total, settlement FROM orders WHERE order_time>=? "
                       f"AND order_time<? AND status NOT IN ({','.join('?' * len(EXCLUDE))}) AND COALESCE(platform,'') NOT IN ('manual','')",
                       (s_ts, e_ts, *EXCLUDE)).fetchall()
    settled, diff, unpaid = [], [], []
    now = time.time()
    tot = {"orders": len(orders), "settled": 0, "revenue": 0.0, "net": 0.0, "fees": 0.0, "unpaid_amount": 0.0, "diff_amount": 0.0}
    for o in orders:
        rev = float(o["order_total"] or 0)
        rate = cfg.get("shopee_fee_rate") if o["platform"] == "shopee" and cfg.get("shopee_fee_rate") else cfg.get("platform_fee_rate", 0)
        expect = rev * (1 - float(rate or 0))
        row = {"id": o["id"], "platform": o["platform"], "shop": o["shop"], "order_no": o["order_no"], "status": o["status"],
               "day": day_of(o["order_time"]) if o["order_time"] else "", "revenue": r2(rev)}
        if o["settlement"] is not None:
            net = float(o["settlement"])
            fee = rev - net
            row.update(net=r2(net), fee=r2(fee), fee_rate=round(fee / rev * 100, 1) if rev else None, expected=r2(expect),
                       diff=r2(expect - net))
            settled.append(row)
            tot["settled"] += 1; tot["revenue"] += rev; tot["net"] += net; tot["fees"] += fee
            if expect - net > st["tolerance"]:
                diff.append(row); tot["diff_amount"] += expect - net
        elif o["status"] in ("shipped", "completed") and o["order_time"] and now - o["order_time"] > st["settle_days"] * 86400:
            row["days"] = int((now - o["order_time"]) // 86400)
            unpaid.append(row); tot["unpaid_amount"] += rev
    known = {}
    for o in c.execute("SELECT platform, order_no FROM orders"):
        known.setdefault(o["platform"], set()).add(key(o["order_no"]))
    unknown = []
    for r in c.execute("SELECT platform, order_no, order_key, SUM(amount) a, MAX(day) d FROM fin_settle_lines WHERE COALESCE(order_key,'')!='' "
                       "AND day>=? AND day<? GROUP BY platform, order_key", (start.isoformat(), end.isoformat())):
        if r["order_key"] not in known.get(r["platform"], set()):
            unknown.append({"platform": r["platform"], "order_no": r["order_no"], "amount": r2(r["a"]), "day": r["d"]})
    adj = c.execute("SELECT COALESCE(SUM(amount),0) a FROM fin_settle_lines WHERE COALESCE(order_key,'')='' AND day>=? AND day<?",
                    (start.isoformat(), end.isoformat())).fetchone()["a"]
    tot = {k: (r2(v) if isinstance(v, float) else v) for k, v in tot.items()}
    tot["fee_rate"] = round(tot["fees"] / tot["revenue"] * 100, 1) if tot["revenue"] else None
    tot["adjustments"] = r2(adj)
    diff.sort(key=lambda x: -x["diff"])
    unpaid.sort(key=lambda x: -x["days"])
    return {"total": tot, "settled": settled[:500], "diff": diff[:300], "unpaid": unpaid[:300], "unknown": unknown[:300],
            "settings": {"days": st["settle_days"], "tolerance": st["tolerance"]}}
