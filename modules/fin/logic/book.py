"""收支记录（v2.21）：支出（广告费、快递、房租、工资……）和其他收入，可以上传票据（照片 / PDF）。
沿用旧的 expenses 表（v1 的「其他支出」），加了几列。"""
import os
import time

from core import db
from core.config import DATA_DIR, load_config

RECEIPT_DIR = os.path.join(DATA_DIR, "finance", "receipts")
OUT_CATS = ["广告费", "快递运费", "包材（不入库的）", "平台罚款 / 扣款", "软件 / 订阅", "水电网", "房租", "人工工资", "设备折旧",
            "设备维修", "办公杂费", "其他支出"]
IN_CATS = ["其他收入", "退回的钱 / 赔偿", "老板投入"]
METHODS = {"transfer": "转账", "cash": "现金", "card": "刷卡", "platform": "平台扣款", "other": "其他"}
# 旧版「其他支出」的类型 → 新分类
OLD_MAP = {"运费补贴": "快递运费", "包材": "包材（不入库的）", "耗材以外采购": "办公杂费", "其他": "其他支出"}


def init():
    c = db.conn()
    c.execute("CREATE TABLE IF NOT EXISTS expenses (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, kind TEXT, amount REAL, note TEXT, "
              "username TEXT, created_at REAL)")
    cols = {r[1] for r in c.execute("PRAGMA table_info(expenses)")}
    for col, typ in (("direction", "TEXT DEFAULT 'out'"), ("vat", "REAL DEFAULT 0"), ("tax_invoice", "INTEGER DEFAULT 0"),
                     ("payee", "TEXT"), ("method", "TEXT"), ("receipt", "TEXT"), ("platform", "TEXT"), ("shop", "TEXT"),
                     ("updated_at", "REAL"), ("deleted", "INTEGER DEFAULT 0")):
        if col not in cols:
            c.execute(f"ALTER TABLE expenses ADD COLUMN {col} {typ}")
    for old, new in OLD_MAP.items():
        c.execute("UPDATE expenses SET kind=? WHERE kind=?", (new, old))
    c.execute("CREATE INDEX IF NOT EXISTS expenses_day ON expenses(day)")
    c.commit()


def categories(cfg=None):
    cfg = cfg or load_config()
    extra = [str(x).strip() for x in (cfg.get("fin_expense_cats") or []) if str(x).strip()]
    return {"out": OUT_CATS + [x for x in extra if x not in OUT_CATS], "in": IN_CATS, "methods": METHODS,
            "fixed": list(cfg.get("fin_fixed_cats") or ["房租", "人工工资", "设备折旧"])}


def _row(r):
    d = dict(r)
    d["category"] = d.pop("kind")
    d["direction"] = d.get("direction") or "out"
    d["has_receipt"] = bool(d.get("receipt"))
    d.pop("receipt", None)
    return d


def list_expenses(start=None, end=None, category="", direction=""):
    sql, args = "SELECT * FROM expenses WHERE COALESCE(deleted,0)=0", []
    if start:
        sql += " AND day>=?"; args.append(str(start))
    if end:
        sql += " AND day<?"; args.append(str(end))
    if category:
        sql += " AND kind=?"; args.append(category)
    if direction:
        sql += " AND COALESCE(direction,'out')=?"; args.append(direction)
    return [_row(r) for r in db.conn().execute(sql + " ORDER BY day DESC, id DESC", args)]


def save_expense(d, user=""):
    try:
        amount = float(d.get("amount"))
    except (TypeError, ValueError):
        raise ValueError("请填写金额")
    if amount <= 0:
        raise ValueError("金额要大于 0（收入和支出用「方向」区分）")
    direction = "in" if d.get("direction") == "in" else "out"
    cat = str(d.get("category") or ("其他收入" if direction == "in" else "其他支出")).strip()[:40]
    cat = OLD_MAP.get(cat, cat)          # 旧版利润页的分类
    day = str(d.get("day") or time.strftime("%Y-%m-%d"))[:10]
    vat = float(d.get("vat") or 0)
    if vat < 0 or vat >= amount:
        raise ValueError("VAT 金额不对（应该小于总金额）")
    vals = {"day": day, "kind": cat, "amount": round(amount, 2), "note": str(d.get("note") or "")[:300], "direction": direction,
            "vat": round(vat, 2), "tax_invoice": 1 if d.get("tax_invoice") else 0, "payee": str(d.get("payee") or "")[:80],
            "method": d.get("method") if d.get("method") in METHODS else "transfer", "platform": str(d.get("platform") or "")[:20],
            "shop": str(d.get("shop") or "")[:60], "updated_at": time.time()}
    c = db.conn()
    if d.get("id"):
        c.execute("UPDATE expenses SET " + ", ".join(f"{k}=?" for k in vals) + " WHERE id=?", (*vals.values(), int(d["id"])))
        eid = int(d["id"])
        act = "财务·修改收支"
    else:
        cur = c.execute("INSERT INTO expenses(" + ", ".join(vals) + ", username, created_at) VALUES(" + ",".join("?" * (len(vals) + 2)) + ")",
                        (*vals.values(), user, time.time()))
        eid = cur.lastrowid
        act = "财务·记收支"
    c.commit()
    db.audit(user, act, str(eid), f"{'收入' if direction == 'in' else '支出'} {cat} ฿{amount:,.2f}")
    return _row(c.execute("SELECT * FROM expenses WHERE id=?", (eid,)).fetchone())


def delete_expense(eid, user=""):
    c = db.conn()
    r = c.execute("SELECT * FROM expenses WHERE id=?", (int(eid),)).fetchone()
    if not r:
        raise ValueError("没有这条记录")
    c.execute("UPDATE expenses SET deleted=1, updated_at=? WHERE id=?", (time.time(), int(eid)))
    c.commit()
    db.audit(user, "财务·删除收支", str(eid), f"{r['kind']} ฿{r['amount']}")


RECEIPT_EXT = (".jpg", ".jpeg", ".png", ".webp", ".pdf", ".heic")


def set_receipt(eid, f):
    ext = os.path.splitext(f.filename or "")[1].lower()
    if ext not in RECEIPT_EXT:
        raise ValueError("票据请上传照片（jpg / png）或 PDF")
    c = db.conn()
    if not c.execute("SELECT 1 FROM expenses WHERE id=?", (int(eid),)).fetchone():
        raise ValueError("没有这条记录")
    os.makedirs(RECEIPT_DIR, exist_ok=True)
    name = f"{int(eid)}_{int(time.time())}{ext}"
    f.save(os.path.join(RECEIPT_DIR, name))
    c.execute("UPDATE expenses SET receipt=? WHERE id=?", (name, int(eid)))
    c.commit()
    return name


def receipt_path(eid):
    r = db.conn().execute("SELECT receipt FROM expenses WHERE id=?", (int(eid),)).fetchone()
    if not r or not r["receipt"]:
        return None
    p = os.path.join(RECEIPT_DIR, os.path.basename(r["receipt"]))
    return p if os.path.exists(p) else None
