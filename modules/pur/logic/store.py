"""采购模块自己的数据表（v2.51）：物品 ↔ 供应商（购买链接、最近单价、起订量、包装数、到货天数）、价格历史、成本变化提醒。
采购单本身、到货差异、付款还在内核 core/inventory/purchase.py（库存模块关掉采购也能看）。

第一次打开（每个数据库一次）自动迁移老数据：
  · 供应商没写货币的按平台 / 名字补上（1688 / 淘宝 / 拼多多 → 人民币，其他泰铢）；
  · 物品的「默认供应商」「购买链接」→ 物品 ↔ 供应商；
  · 已经到货的采购单 → 价格历史（以后比价、看耗材每公斤价格走势用）。
"""
import json
import threading
import time

from core import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS pur_item_sup (
  id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, supplier_id INTEGER, urls TEXT, price REAL, currency TEXT,
  moq REAL, pack_qty REAL, lead_days REAL, net_g REAL, note TEXT, updated_at REAL, UNIQUE(item_id, supplier_id)
);
CREATE INDEX IF NOT EXISTS pur_item_sup_item ON pur_item_sup(item_id);
CREATE TABLE IF NOT EXISTS pur_prices (
  id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, supplier_id INTEGER, ts REAL, day TEXT, unit_price REAL, currency TEXT,
  fx_rate REAL, landed REAL, qty REAL, po_no TEXT, source TEXT
);
CREATE INDEX IF NOT EXISTS pur_prices_item ON pur_prices(item_id, ts);
CREATE TABLE IF NOT EXISTS pur_cost_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, item_id INTEGER, label TEXT, old REAL, new REAL, pct REAL,
  applied INTEGER DEFAULT 0, po_no TEXT, state TEXT DEFAULT 'open', username TEXT
);
CREATE TABLE IF NOT EXISTS pur_meta (key TEXT PRIMARY KEY, value TEXT);
"""
_done = set()
_lock = threading.Lock()

PLATFORMS = [("1688", ("1688.com",)), ("淘宝", ("taobao.com", "tmall.com", "tb.cn")), ("拼多多", ("pinduoduo.com", "yangkeduo.com", "pdd")),
             ("Shopee", ("shopee.",)), ("Lazada", ("lazada.",)), ("TikTok", ("tiktok.",))]


def platform_of_url(url):
    u = str(url or "").lower()
    for name, keys in PLATFORMS:
        if any(k in u for k in keys):
            return name
    return ""


def ensure():
    if db.DB_PATH in _done:
        return
    with _lock:
        if db.DB_PATH in _done:
            return
        from core import inventory
        inventory.init()            # 内核的采购表（加了新的列）先建好
        c = db.conn()
        c.executescript(SCHEMA)
        c.commit()
        if not c.execute("SELECT 1 FROM pur_meta WHERE key='migrated251'").fetchone():
            try:
                migrate(c)
            finally:
                c.execute("INSERT OR REPLACE INTO pur_meta(key, value) VALUES('migrated251', ?)", (str(time.time()),))
                c.commit()
        _done.add(db.DB_PATH)


def migrate(c):
    from core import inventory as inv
    from core.inventory import purchase
    n = {"suppliers": 0, "links": 0, "prices": 0}
    # 1 供应商：货币、平台
    for s in c.execute("SELECT * FROM inv_suppliers").fetchall():
        plat = s["platform"] or ""
        if not plat:
            for name, _k in PLATFORMS:
                if name.lower() in (s["name"] or "").lower():
                    plat = name
                    break
            plat = plat or platform_of_url(s["link"])
        cur = s["currency"] or inv.default_currency(plat, s["name"])
        c.execute("UPDATE inv_suppliers SET platform=?, currency=? WHERE id=?", (plat, cur, s["id"]))
        n["suppliers"] += 1
    sup_by_plat = {}
    for s in c.execute("SELECT * FROM inv_suppliers WHERE active=1 ORDER BY id").fetchall():
        sup_by_plat.setdefault((s["platform"] or "").lower(), s["id"])
        sup_by_plat.setdefault((s["name"] or "").lower(), s["id"])
    # 2 物品的默认供应商 / 购买链接 → 物品 ↔ 供应商
    for it in c.execute("SELECT id, supplier_id, link, avg_cost FROM inv_items").fetchall():
        sid = it["supplier_id"]
        url = (it["link"] or "").strip()
        if not sid and url:
            sid = sup_by_plat.get(platform_of_url(url).lower())
        if not sid:
            continue
        last = c.execute("SELECT l.unit_cost, p.currency FROM inv_po_lines l JOIN inv_po p ON p.id=l.po_id WHERE l.item_id=? AND p.supplier_id=? "
                         "AND p.status!='draft' ORDER BY p.id DESC LIMIT 1", (it["id"], sid)).fetchone()
        srow = c.execute("SELECT currency FROM inv_suppliers WHERE id=?", (sid,)).fetchone()
        cur = (last["currency"] if last else None) or (srow["currency"] if srow else "") or "THB"
        price = last["unit_cost"] if last else None
        c.execute("INSERT OR IGNORE INTO pur_item_sup(item_id, supplier_id, urls, price, currency, updated_at) VALUES(?,?,?,?,?,?)",
                  (it["id"], sid, json.dumps([url] if url else []), price, cur, time.time()))
        if not it["supplier_id"]:
            c.execute("UPDATE inv_items SET supplier_id=? WHERE id=?", (sid, it["id"]))
        n["links"] += 1
    # 3 已到货的采购单 → 价格历史
    for po in c.execute("SELECT * FROM inv_po WHERE status IN ('partial','received','done')").fetchall():
        rate = purchase.fee_rate(c, po)
        fx = purchase._fx(po)
        day = time.strftime("%Y-%m-%d", time.localtime(po["received_at"] or po["ordered_at"] or po["created_at"] or time.time()))
        for ln in c.execute("SELECT * FROM inv_po_lines WHERE po_id=? AND COALESCE(received,0)>0", (po["id"],)).fetchall():
            c.execute("INSERT INTO pur_prices(item_id, supplier_id, ts, day, unit_price, currency, fx_rate, landed, qty, po_no, source) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (ln["item_id"], po["supplier_id"], po["received_at"] or po["created_at"], day,
                                                        ln["unit_cost"], po["currency"] or "THB", fx, (ln["unit_cost"] or 0) * fx * (1 + rate),
                                                        ln["received"], po["no"], "migrate"))
            n["prices"] += 1
            if po["supplier_id"]:
                c.execute("INSERT OR IGNORE INTO pur_item_sup(item_id, supplier_id, urls, currency, updated_at) VALUES(?,?,?,?,?)",
                          (ln["item_id"], po["supplier_id"], "[]", po["currency"] or "THB", time.time()))
                c.execute("UPDATE pur_item_sup SET price=?, currency=? WHERE item_id=? AND supplier_id=?",
                          (ln["unit_cost"], po["currency"] or "THB", ln["item_id"], po["supplier_id"]))
    c.commit()
    return n
