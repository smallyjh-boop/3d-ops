"""和财务模块对接的通道（v2.18）。

库存 / 采购里跟钱有关的事都记一条「财务事件」fin_events（只增不改），财务模块（ERP 里以后的财务页，或 NAS 上单独的财务程序）
按 since 增量读取：GET /api/v1/finance/events?since=…（密钥权限 finance）。
另外按月汇总：GET /api/v1/finance/inventory?month=YYYY-MM —— 这个月各分类的消耗 / 损耗金额、采购入库金额、付款、月末库存金额。

事件类型 kind：
  purchase_payment   采购付款（现金流出，有付款方式、日期）
  purchase_received  采购到货入库（库存增加，按到手成本）
  （以后可以加：inventory_writeoff 大额报废、opening 期初……财务模块忽略不认识的类型即可）
"""
import datetime as dt
import json

from .. import db
from . import ledger

SCHEMA = """
CREATE TABLE IF NOT EXISTS fin_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, day TEXT, source TEXT, kind TEXT, amount REAL, currency TEXT DEFAULT 'THB',
  category TEXT, ref_type TEXT, ref_no TEXT, method TEXT, note TEXT, username TEXT, extra TEXT
);
CREATE INDEX IF NOT EXISTS fin_events_ts ON fin_events(ts);
"""
KIND_ZH = {"purchase_payment": "采购付款", "purchase_received": "采购到货入库"}


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()


def event(kind, amount, ref_type="", ref_no="", note="", user="", category="", day=None, method="", extra=None, source="inventory"):
    c = db.conn()
    now = ledger._now()
    c.execute("INSERT INTO fin_events(ts, day, source, kind, amount, category, ref_type, ref_no, method, note, username, extra) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
              (now, day or dt.date.today().isoformat(), source, kind, round(float(amount or 0), 2), category or "", ref_type, ref_no,
               method or "", (note or "")[:300], user or "", json.dumps(extra, ensure_ascii=False) if extra else None))
    c.commit()


def events(since=0, limit=1000, kind=""):
    sql, args = "SELECT * FROM fin_events WHERE ts>=?", [float(since or 0)]
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    out = []
    for r in db.conn().execute(sql + " ORDER BY id LIMIT ?", (*args, int(limit))):
        d = dict(r)
        d["kind_zh"] = KIND_ZH.get(d["kind"], d["kind"])
        d["extra"] = json.loads(d["extra"]) if d.get("extra") else None
        out.append(d)
    return out


def month_summary(month=None):
    """某个月（YYYY-MM，默认本月）的库存相关金额。"""
    from . import report
    if not month:
        month = dt.date.today().strftime("%Y-%m")
    y, m = (int(x) for x in month.split("-"))
    start = dt.datetime(y, m, 1).timestamp()
    end = dt.datetime(y + (m == 12), m % 12 + 1, 1).timestamp()
    by_cat = report.expense(start, end, "category")
    by_kind = report.expense(start, end, "kind")
    c = db.conn()
    rec = c.execute("SELECT COALESCE(SUM(amount),0) FROM inv_moves WHERE kind='purchase' AND ts>=? AND ts<?", (start, end)).fetchone()[0]
    pay = c.execute("SELECT COALESCE(SUM(amount),0) FROM fin_events WHERE kind='purchase_payment' AND ts>=? AND ts<?", (start, end)).fetchone()[0]
    value = c.execute("SELECT category, SUM(qty*avg_cost) v FROM inv_items WHERE active=1 GROUP BY category").fetchall()
    return {"month": month, "currency": "THB",
            "consumption_total": by_cat["total"],
            "consumption_by_category": [{"category": r["key"], "label": r["label"], "amount": r["amount"]} for r in by_cat["rows"]],
            "consumption_by_kind": [{"kind": r["key"], "label": r["label"], "amount": r["amount"]} for r in by_kind["rows"]],
            "purchases_received": round(rec, 2), "payments": round(pay, 2),
            "stock_value_now": {r["category"]: round(r["v"] or 0, 2) for r in value}}
