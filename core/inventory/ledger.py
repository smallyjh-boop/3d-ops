"""库存：物品档案 + 流水（每一笔数量变化）+ 加权平均成本。只在 core/inventory 里面用，别的模块走 __init__ 里的接口。"""
import json
import time

from .. import db
from ..config import load_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, name_zh TEXT, name_th TEXT, category TEXT, unit TEXT,
  spec TEXT, brand TEXT, material TEXT, color TEXT, color_code TEXT, loss_rate REAL,
  qty REAL DEFAULT 0, avg_cost REAL DEFAULT 0, reorder_point REAL, location TEXT, link TEXT, note TEXT,
  active INTEGER DEFAULT 1, created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS inv_items_cat ON inv_items(category);
CREATE INDEX IF NOT EXISTS inv_items_fil ON inv_items(material, color);
CREATE TABLE IF NOT EXISTS inv_moves (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, item_id INTEGER, kind TEXT, qty REAL, unit_cost REAL, amount REAL,
  balance REAL, doc_id INTEGER, reason TEXT, username TEXT, ref TEXT, printer TEXT
);
CREATE INDEX IF NOT EXISTS inv_moves_item ON inv_moves(item_id, ts);
CREATE INDEX IF NOT EXISTS inv_moves_ts ON inv_moves(ts);
CREATE TABLE IF NOT EXISTS inv_docs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, no TEXT UNIQUE, kind TEXT, status TEXT, category TEXT, note TEXT, printer TEXT, ref TEXT,
  created_by TEXT, created_at REAL, done_by TEXT, done_at REAL, void_by TEXT, void_at REAL, amount REAL
);
CREATE TABLE IF NOT EXISTS inv_doc_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER, item_id INTEGER, qty REAL, unit_cost REAL, expected REAL, counted REAL,
  extra TEXT, note TEXT
);
CREATE INDEX IF NOT EXISTS inv_lines_doc ON inv_doc_lines(doc_id);
"""

# 分类：内置的 5 个（编号固定，界面按语言翻译）；设置里可以加自己的（inv_categories，中文名）
CATEGORIES = {"filament": ("耗材", "วัสดุพิมพ์", "HC"), "part": ("备件", "อะไหล่", "BJ"), "pack": ("包材", "วัสดุแพ็ค", "BC"),
              "goods": ("成品", "สินค้าสำเร็จรูป", "CP"), "tool": ("工具", "เครื่องมือ", "GJ"), "other": ("其他", "อื่นๆ", "QT")}
UNITS = ["g", "个", "卷", "张", "件", "米", "瓶", "盒", "套", "包", "根", "支", "把", "kg"]

# 流水类型：数量方向 + 是否算支出（出库 / 损耗类计入「支出统计」）
KINDS = {
    "opening": ("期初", 0), "purchase": ("采购入库", 0), "return": ("退回入库", 0),
    "production": ("生产消耗", 1), "loss": ("生产损耗", 1), "fail": ("打印失败损耗", 1),
    "issue": ("领用出库", 1), "scrap": ("报废", 1), "adjust": ("盘点 / 调整", 1),
    "produce": ("成品入库（备货打印）", 0), "ship": ("成品出货", 0), "pack": ("发货包材", 1),
    # v2.21 预留给以后的「进销存」：卖出去的外购商品（不是自己打印的）从库存出库，成本记到销售成本
    "sale": ("销售出库", 0),
}
# 成品的进出（生产入库、出货）是库存转移，不算「支出」；成品的盘亏 / 报废照算


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()


def categories(cfg=None):
    cfg = cfg or load_config()
    out = [{"id": k, "zh": v[0], "th": v[1], "builtin": True} for k, v in CATEGORIES.items()]
    for name in cfg.get("inv_categories") or []:
        n = str(name).strip()
        if n and n not in [x["zh"] for x in out]:
            out.append({"id": n, "zh": n, "th": n, "builtin": False})
    return out


def _now():
    return time.time()


def item_row(r):
    if not r:
        return None
    d = dict(r)
    cat = CATEGORIES.get(d.get("category") or "")
    d["category_zh"] = cat[0] if cat else (d.get("category") or "")
    d["category_th"] = cat[1] if cat else (d.get("category") or "")
    d["value"] = round((d.get("qty") or 0) * (d.get("avg_cost") or 0), 2)
    d["low"] = d.get("reorder_point") is not None and (d.get("qty") or 0) <= (d.get("reorder_point") or 0)
    return d


def get_item(item_id):
    return item_row(db.conn().execute("SELECT * FROM inv_items WHERE id=? OR code=?",
                                      (int(item_id) if str(item_id).isdigit() else -1, str(item_id))).fetchone())


def _next_code(c, category, material="", color_code=""):
    if category == "filament" and material:
        base = f"F-{material.upper()}-{(color_code or 'X').upper()}"
        code, n = base, 2
        while c.execute("SELECT 1 FROM inv_items WHERE code=?", (code,)).fetchone():
            code, n = f"{base}-{n}", n + 1
        return code
    pre = (CATEGORIES.get(category) or ("", "", "ZD"))[2]
    n = c.execute("SELECT COUNT(*) FROM inv_items WHERE code LIKE ?", (pre + "%",)).fetchone()[0] + 1
    code = f"{pre}{n:04d}"
    while c.execute("SELECT 1 FROM inv_items WHERE code=?", (code,)).fetchone():
        n += 1
        code = f"{pre}{n:04d}"
    return code


FIELDS = ("name_zh", "name_th", "category", "unit", "spec", "brand", "material", "color", "color_code", "loss_rate",
          "reorder_point", "reorder_qty", "supplier_id", "location", "link", "note", "active")


def save_item(d, user=""):
    """新建 / 修改物品档案（不改数量和成本：数量只能靠单据变）。返回物品。"""
    c = db.conn()
    now = _now()
    vals = {k: d.get(k) for k in FIELDS if k in d}
    for k in ("loss_rate", "reorder_point", "reorder_qty"):
        if k in vals:
            vals[k] = None if vals[k] in (None, "") else float(vals[k])
    if "supplier_id" in vals:
        vals["supplier_id"] = int(vals["supplier_id"]) if vals["supplier_id"] not in (None, "") else None
    if vals.get("material"):
        vals["material"] = str(vals["material"]).strip().upper()
    if "color" in vals and vals.get("color"):
        from .. import codes
        col = codes.find_color(load_config(), vals["color"])
        vals["color_code"] = col[1] if col else (vals.get("color_code") or "")
    if d.get("id"):
        it = get_item(d["id"])
        if not it:
            raise ValueError("没有这个物品")
        if it["category"] == "filament" and ("material" in vals or "color" in vals) and \
                (vals.get("material", it["material"]) != it["material"] or vals.get("color", it["color"]) != it["color"]):
            raise ValueError("耗材的材料和颜色建好后不能改（和料卷、产品颜色对应）；不对的话新建一个，旧的停用")
        if vals:
            c.execute("UPDATE inv_items SET " + ", ".join(f"{k}=?" for k in vals) + ", updated_at=? WHERE id=?",
                      (*vals.values(), now, it["id"]))
        c.commit()
        db.audit(user, "库存·修改物品", it["code"], json.dumps(vals, ensure_ascii=False)[:300])
        return get_item(it["id"])
    if not str(vals.get("name_zh") or "").strip():
        raise ValueError("请填写物品名称")
    cat = vals.get("category") or "other"
    vals["category"] = cat
    vals.setdefault("unit", "g" if cat == "filament" else "个")
    if cat == "filament":
        if not vals.get("material") or not vals.get("color"):
            raise ValueError("耗材要填材料（PLA / PETG…）和颜色")
        if c.execute("SELECT 1 FROM inv_items WHERE category='filament' AND material=? AND color=? AND active=1",
                     (vals["material"], vals["color"])).fetchone():
            raise ValueError(f"{vals['material']} {vals['color']} 已经有了")
    code = (str(d.get("code") or "").strip().upper()[:30]) or _next_code(c, cat, vals.get("material", ""), vals.get("color_code", ""))
    if c.execute("SELECT 1 FROM inv_items WHERE code=?", (code,)).fetchone():
        raise ValueError(f"编码 {code} 已经有了")
    vals.setdefault("active", 1)
    cols = ["code", *vals.keys(), "qty", "avg_cost", "created_at", "updated_at"]
    c.execute(f"INSERT INTO inv_items({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
              (code, *vals.values(), 0, float(d.get("avg_cost") or 0), now, now))
    c.commit()
    db.audit(user, "库存·新建物品", code, vals.get("name_zh", ""))
    return get_item(code)


def default_cost(cfg=None):
    """耗材没有进价记录时的单价（铢 / 克）：设置里的耗材价格。"""
    cfg = cfg or load_config()
    try:
        return float(cfg.get("filament_price_cny_per_kg") or 0) * float(cfg.get("cny_to_thb") or 0) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def post(c, item_id, kind, qty, unit_cost=None, reason="", user="", doc_id=None, ref="", printer=""):
    """记一笔流水，更新数量和加权平均成本。qty 有正负（入为正、出为负）。调用方负责 commit。"""
    r = c.execute("SELECT qty, avg_cost, category FROM inv_items WHERE id=?", (item_id,)).fetchone()
    if not r:
        raise ValueError("没有这个物品")
    q0, avg = float(r["qty"] or 0), float(r["avg_cost"] or 0)
    if not avg and r["category"] == "filament":
        avg = default_cost()
    q = float(qty)
    if q > 0 and kind in ("purchase", "opening", "produce") and unit_cost not in (None, ""):
        uc = float(unit_cost)
        avg = (max(q0, 0) * avg + q * uc) / (max(q0, 0) + q) if max(q0, 0) + q > 0 else uc
    else:
        uc = avg if unit_cost in (None, "") else float(unit_cost)
    bal = q0 + q
    c.execute("UPDATE inv_items SET qty=?, avg_cost=?, updated_at=? WHERE id=?", (bal, avg, _now(), item_id))
    c.execute("INSERT INTO inv_moves(ts, item_id, kind, qty, unit_cost, amount, balance, doc_id, reason, username, ref, printer) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
              (_now(), item_id, kind, q, uc, round(q * uc, 4), bal, doc_id, reason or KINDS.get(kind, (kind,))[0], user or "", ref or "",
               printer or ""))
    try:                       # v2.35：货位（库存模块）——新物品第一次入库还没货位时自动放一个空格；出错不影响记账
        from .. import modules
        m = modules.public("inv")
        if m is not None:
            m.on_post(c, item_id, q, kind, user)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("3dops").warning("货位没自动放（物品 %s %+g）：%s", item_id, q, e)
    return bal


def moves(item_id=None, kind=None, days=None, limit=300, doc_id=None):
    sql = "SELECT m.*, i.code, i.name_zh, i.name_th, i.unit, i.category FROM inv_moves m JOIN inv_items i ON i.id=m.item_id"
    conds, args = [], []
    if item_id:
        conds.append("m.item_id=?"); args.append(int(item_id))
    if kind:
        conds.append("m.kind=?"); args.append(kind)
    if days:
        conds.append("m.ts>=?"); args.append(_now() - float(days) * 86400)
    if doc_id:
        conds.append("m.doc_id=?"); args.append(int(doc_id))
    sql += (" WHERE " + " AND ".join(conds) if conds else "") + " ORDER BY m.id DESC LIMIT ?"
    args.append(int(limit))
    out = []
    for r in db.conn().execute(sql, args):
        d = dict(r)
        d["kind_zh"] = KINDS.get(d["kind"], (d["kind"],))[0]
        out.append(d)
    return out
