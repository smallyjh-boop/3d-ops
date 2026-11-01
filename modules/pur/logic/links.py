"""物品 ↔ 供应商（v2.51）：每个物品可以有几个供应商，每个写购买链接（1688 / 淘宝 / 拼多多 / Shopee / Lazada）、最近单价、
起订量、包装数（一包几个 / 一卷几克）、到货天数。「首选供应商」就是物品档案里的默认供应商（inv_items.supplier_id）。
价格历史：每次到货记一笔（单价、汇率、到手单价 = 摊了运费 / 税的泰铢单价），比价按到手单价比。
到货后（内核发 po.received 事件）：记价格历史、更新最近单价；耗材的平均进价变了超过设置的百分比 → 改定价用的耗材价格
（设置可以关）并给老板一条待办「产品成本 / 价格要看一下」。
"""
import json
import math
import time

from core import db, inventory as inv
from core.config import load_config, save_config
from core.inventory import purchase as _kp

from .store import ensure, platform_of_url


def _f(v, name, allow_none=True):
    if v in (None, ""):
        if allow_none:
            return None
        raise ValueError(f"{name}要填")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name}要是数字")
    if not math.isfinite(x) or x < 0:
        raise ValueError(f"{name}要是不小于 0 的数字")
    return x


def _urls(v):
    if isinstance(v, str):
        v = [x for x in v.replace(",", "\n").split("\n")]
    out = []
    for u in v or []:
        u = str(u or "").strip()
        if u and u not in out:
            if not u.lower().startswith(("http://", "https://")):
                u = "https://" + u
            out.append(u[:500])
    return out[:5]


def _row(r, sups=None, preferred=None):
    d = dict(r)
    d["urls"] = json.loads(d.get("urls") or "[]")
    d["platforms"] = [platform_of_url(u) for u in d["urls"]]
    s = (sups or {}).get(d["supplier_id"])
    if s is None and d.get("supplier_id"):
        s = db.conn().execute("SELECT * FROM inv_suppliers WHERE id=?", (d["supplier_id"],)).fetchone()
        s = dict(s) if s else None
    d["supplier"] = {k: s.get(k) for k in ("id", "name", "platform", "currency", "lead_days", "active")} if s else None
    d["currency"] = d.get("currency") or (s or {}).get("currency") or "THB"
    d["lead"] = d.get("lead_days") if d.get("lead_days") is not None else (s or {}).get("lead_days")
    d["preferred"] = preferred is not None and d["supplier_id"] == preferred
    fx = _kp.default_fx() if d["currency"] == "CNY" else 1.0
    d["price_thb"] = round(d["price"] * fx, 4) if d.get("price") is not None else None
    return d


def item_links(item_id):
    """这个物品的所有供应商（首选的排在前面）+ 价格历史 + 比价。"""
    ensure()
    it = inv.get_item(item_id)
    if not it:
        raise ValueError("没有这个物品")
    c = db.conn()
    rows = [_row(r, preferred=it.get("supplier_id")) for r in c.execute("SELECT * FROM pur_item_sup WHERE item_id=?", (it["id"],))]
    rows.sort(key=lambda x: (not x["preferred"], x["price_thb"] if x["price_thb"] is not None else 1e12))
    hist = history(it["id"])
    last_landed = {}
    for h in hist:                     # 最新的在前
        last_landed.setdefault(h["supplier_id"], h["landed"])
    for r in rows:
        r["last_landed"] = last_landed.get(r["supplier_id"])
        r["compare"] = r["last_landed"] if r["last_landed"] is not None else r["price_thb"]
    vals = [r["compare"] for r in rows if r["compare"]]
    best = min(vals) if vals else None
    for r in rows:
        r["cheapest"] = best is not None and r["compare"] == best and len(vals) > 1
    return {"item": it, "links": rows, "history": hist, "cheapest": best}


def history(item_id, limit=60):
    ensure()
    out = []
    for r in db.conn().execute("SELECT p.*, s.name supplier_name FROM pur_prices p LEFT JOIN inv_suppliers s ON s.id=p.supplier_id "
                               "WHERE p.item_id=? ORDER BY p.ts DESC, p.id DESC LIMIT ?", (int(item_id), int(limit))):
        out.append(dict(r))
    return out


def all_links():
    """{物品id: [供应商链接…]}（补货建议、采购单表单用）。"""
    ensure()
    c = db.conn()
    sups = {r["id"]: dict(r) for r in c.execute("SELECT * FROM inv_suppliers")}
    pref = {r["id"]: r["supplier_id"] for r in c.execute("SELECT id, supplier_id FROM inv_items")}
    out = {}
    for r in c.execute("SELECT * FROM pur_item_sup"):
        out.setdefault(r["item_id"], []).append(_row(r, sups, pref.get(r["item_id"])))
    return out


def save_link(d, user=""):
    """新建 / 修改物品的一个供应商。preferred=True 时同时设成首选（物品档案的默认供应商）。"""
    ensure()
    c = db.conn()
    it = inv.get_item(d.get("item_id"))
    if not it:
        raise ValueError("没有这个物品")
    try:
        sid = int(d.get("supplier_id"))
    except (TypeError, ValueError):
        raise ValueError("先选供应商")
    s = c.execute("SELECT * FROM inv_suppliers WHERE id=?", (sid,)).fetchone()
    if not s:
        raise ValueError("没有这个供应商")
    cur = str(d.get("currency") or s["currency"] or "THB").upper()
    if cur not in _kp.CURRENCIES:
        raise ValueError("货币只能是 THB 或 CNY")
    price = _f(d.get("price"), "单价")
    if it["category"] == "filament" and d.get("price_roll") not in (None, ""):      # 耗材按卷填价格 → 存每克（和物品单位一样）
        price = _f(d.get("price_roll"), "每卷价格") / (_f(d.get("net_g"), "每卷克数") or 1000)
    vals = {"urls": json.dumps(_urls(d.get("urls")), ensure_ascii=False), "price": price, "currency": cur,
            "moq": _f(d.get("moq"), "起订量"), "pack_qty": _f(d.get("pack_qty"), "包装数"), "lead_days": _f(d.get("lead_days"), "到货天数"),
            "net_g": _f(d.get("net_g"), "每卷克数"), "note": str(d.get("note") or "")[:300], "updated_at": time.time()}
    lid = d.get("id")
    if lid:
        old = c.execute("SELECT * FROM pur_item_sup WHERE id=?", (int(lid),)).fetchone()
        if not old:
            raise ValueError("没有这条供应商记录")
        dup = c.execute("SELECT id FROM pur_item_sup WHERE item_id=? AND supplier_id=? AND id!=?", (it["id"], sid, old["id"])).fetchone()
        if dup:
            raise ValueError("这个物品已经有这个供应商了")
        c.execute("UPDATE pur_item_sup SET supplier_id=?, " + ", ".join(f"{k}=?" for k in vals) + " WHERE id=?", (sid, *vals.values(), old["id"]))
        lid = old["id"]
    else:
        ex = c.execute("SELECT id FROM pur_item_sup WHERE item_id=? AND supplier_id=?", (it["id"], sid)).fetchone()
        if ex:
            lid = ex["id"]
            c.execute("UPDATE pur_item_sup SET " + ", ".join(f"{k}=?" for k in vals) + " WHERE id=?", (*vals.values(), lid))
        else:
            lid = c.execute("INSERT INTO pur_item_sup(item_id, supplier_id, " + ", ".join(vals) + ") VALUES(?,?," + ",".join("?" * len(vals)) + ")",
                            (it["id"], sid, *vals.values())).lastrowid
    c.commit()
    if d.get("preferred") in (True, 1, "1", "true") or not it.get("supplier_id"):
        set_preferred(it["id"], sid, user)
    if vals["price"] is not None:
        _price_row(c, it["id"], sid, vals["price"], cur, None, None, "", "manual")
    db.audit(user, "采购·物品供应商", it["code"], s["name"])
    return item_links(it["id"])


def delete_link(lid, user=""):
    ensure()
    c = db.conn()
    r = c.execute("SELECT * FROM pur_item_sup WHERE id=?", (int(lid),)).fetchone()
    if not r:
        raise ValueError("没有这条供应商记录")
    c.execute("DELETE FROM pur_item_sup WHERE id=?", (r["id"],))
    c.commit()
    it = inv.get_item(r["item_id"])
    if it and it.get("supplier_id") == r["supplier_id"]:
        nxt = c.execute("SELECT supplier_id FROM pur_item_sup WHERE item_id=? ORDER BY id LIMIT 1", (r["item_id"],)).fetchone()
        inv.save_item({"id": it["id"], "supplier_id": nxt["supplier_id"] if nxt else None}, user)
    return item_links(r["item_id"])


def set_preferred(item_id, supplier_id, user=""):
    ensure()
    inv.save_item({"id": int(item_id), "supplier_id": int(supplier_id) if supplier_id not in (None, "") else None}, user)
    c = db.conn()
    if supplier_id not in (None, ""):
        c.execute("INSERT OR IGNORE INTO pur_item_sup(item_id, supplier_id, urls, updated_at) VALUES(?,?,?,?)",
                  (int(item_id), int(supplier_id), "[]", time.time()))
        c.commit()
    return item_links(item_id)


def delete_supplier(sid, user=""):
    """删除供应商：用过的（有采购单 / 物品用它）只停用，没用过的直接删。"""
    ensure()
    c = db.conn()
    s = c.execute("SELECT * FROM inv_suppliers WHERE id=?", (int(sid),)).fetchone()
    if not s:
        raise ValueError("没有这个供应商")
    used = c.execute("SELECT 1 FROM inv_po WHERE supplier_id=? LIMIT 1", (s["id"],)).fetchone() or \
        c.execute("SELECT 1 FROM pur_prices WHERE supplier_id=? LIMIT 1", (s["id"],)).fetchone()
    if used:
        c.execute("UPDATE inv_suppliers SET active=0 WHERE id=?", (s["id"],))
        c.commit()
        db.audit(user, "库存·供应商", s["name"], "停用")
        return {"deleted": False, "deactivated": True}
    c.execute("DELETE FROM pur_item_sup WHERE supplier_id=?", (s["id"],))
    c.execute("UPDATE inv_items SET supplier_id=NULL WHERE supplier_id=?", (s["id"],))
    c.execute("DELETE FROM inv_suppliers WHERE id=?", (s["id"],))
    c.commit()
    db.audit(user, "库存·供应商", s["name"], "删除")
    return {"deleted": True, "deactivated": False}


def _price_row(c, item_id, sid, price, cur, fx, landed, po_no, source, qty=None):
    if source == "manual":       # 手动改的价格：同一天同一个价格不重复记
        last = c.execute("SELECT unit_price FROM pur_prices WHERE item_id=? AND supplier_id=? ORDER BY id DESC LIMIT 1", (item_id, sid)).fetchone()
        if last and last["unit_price"] is not None and abs(last["unit_price"] - price) < 1e-9:
            return
    fx = fx or (_kp.default_fx() if cur == "CNY" else 1.0)
    c.execute("INSERT INTO pur_prices(item_id, supplier_id, ts, day, unit_price, currency, fx_rate, landed, qty, po_no, source) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (item_id, sid, time.time(), time.strftime("%Y-%m-%d"), price, cur, fx,
                                                landed if landed is not None else price * fx, qty, po_no, source))
    c.commit()


# ---------------- 到货以后：价格历史 + 成本更新 ----------------
def on_po_received(po_id, lines=None, user=""):
    """内核 po.received 事件：每一行记价格历史、更新这个供应商的最近单价；然后看耗材成本要不要更新。"""
    ensure()
    c = db.conn()
    po = c.execute("SELECT * FROM inv_po WHERE id=?", (int(po_id),)).fetchone()
    if not po:
        return None
    rate = _kp.fee_rate(c, po)
    fx = _kp._fx(po)
    cur = po["currency"] or "THB"
    changes = []
    for x in lines or []:
        ln = c.execute("SELECT * FROM inv_po_lines WHERE id=?", (int(x["line_id"]),)).fetchone()
        if not ln:
            continue
        landed = (ln["unit_cost"] or 0) * fx * (1 + rate)
        prev = c.execute("SELECT landed FROM pur_prices WHERE item_id=? AND source!='manual' AND landed>0 ORDER BY ts DESC, id DESC LIMIT 1",
                         (ln["item_id"],)).fetchone()
        _price_row(c, ln["item_id"], po["supplier_id"], ln["unit_cost"], cur, fx, landed, po["no"], "po", x.get("qty"))
        if po["supplier_id"]:
            c.execute("INSERT OR IGNORE INTO pur_item_sup(item_id, supplier_id, urls, currency, updated_at) VALUES(?,?,?,?,?)",
                      (ln["item_id"], po["supplier_id"], "[]", cur, time.time()))
            c.execute("UPDATE pur_item_sup SET price=?, currency=?, updated_at=? WHERE item_id=? AND supplier_id=?",
                      (ln["unit_cost"], cur, time.time(), ln["item_id"], po["supplier_id"]))
            it = inv.get_item(ln["item_id"])
            if it and not it.get("supplier_id"):
                inv.save_item({"id": it["id"], "supplier_id": po["supplier_id"]}, user)
        c.commit()
        it = inv.get_item(ln["item_id"]) or {}
        if prev and prev["landed"] and it.get("category") != "filament":
            pct = (landed - prev["landed"]) / prev["landed"] * 100
            if abs(pct) >= _pct():
                changes.append(_record(c, "item", ln["item_id"], it.get("name_zh") or "", prev["landed"], landed, pct, 0, po["no"], user))
    ids = [int(x["line_id"]) for x in lines or []]
    fil = ids and c.execute(f"SELECT 1 FROM inv_po_lines l JOIN inv_items i ON i.id=l.item_id WHERE l.id IN ({','.join('?' * len(ids))}) "
                            "AND i.category='filament'", ids).fetchone()
    if fil:                       # 这次到了耗材 → 看平均进价
        ch = update_filament_cost(po["no"], user)
        if ch:
            changes.append(ch)
    return changes


def _pct():
    try:
        return float(load_config().get("pur_cost_alert_pct") or 5)
    except (TypeError, ValueError):
        return 5.0


def filament_avg_thb_g():
    """库存里耗材的平均进价（泰铢 / 克，按数量加权）。没库存时用最近一次到货的到手单价。"""
    c = db.conn()
    r = c.execute("SELECT SUM(qty*avg_cost) v, SUM(qty) q FROM inv_items WHERE category='filament' AND active=1 AND qty>0 AND avg_cost>0").fetchone()
    if r["q"]:
        return r["v"] / r["q"]
    ensure()
    r = c.execute("SELECT p.landed FROM pur_prices p JOIN inv_items i ON i.id=p.item_id WHERE i.category='filament' AND p.landed>0 "
                  "ORDER BY p.ts DESC LIMIT 1").fetchone()
    return r["landed"] if r else None


def update_filament_cost(po_no="", user=""):
    """耗材平均进价 → 定价用的「耗材价格（人民币/公斤）」。变化超过设置的百分比才动（设置里可以关自动改：只提醒）。"""
    cfg = load_config()
    thb_g = filament_avg_thb_g()
    fx = float(cfg.get("cny_to_thb") or 0) or 4.5
    if not thb_g:
        return None
    new = round(thb_g * 1000 / fx, 2)                         # 人民币 / 公斤
    old = float(cfg.get("filament_price_cny_per_kg") or 0)
    if old <= 0:
        return None
    pct = (new - old) / old * 100
    if abs(pct) < _pct():
        return None
    auto = cfg.get("pur_auto_cost", True) not in (False, 0, "0", "false")
    if auto:
        save_config({"filament_price_cny_per_kg": new})
    c = db.conn()
    return _record(c, "filament", None, "耗材", old, new, pct, 1 if auto else 0, po_no, user)


def _record(c, kind, item_id, label, old, new, pct, applied, po_no, user):
    rid = c.execute("INSERT INTO pur_cost_changes(ts, kind, item_id, label, old, new, pct, applied, po_no, state, username) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (time.time(), kind, item_id, label[:100], round(old, 4), round(new, 4), round(pct, 1),
                                                     applied, po_no, "open", user)).lastrowid
    c.commit()
    return dict(c.execute("SELECT * FROM pur_cost_changes WHERE id=?", (rid,)).fetchone())


def cost_changes(state="open", limit=50):
    ensure()
    sql, args = "SELECT x.*, i.code, i.name_th, i.unit FROM pur_cost_changes x LEFT JOIN inv_items i ON i.id=x.item_id", []
    if state:
        sql += " WHERE x.state=?"
        args.append(state)
    return [dict(r) for r in db.conn().execute(sql + " ORDER BY x.id DESC LIMIT ?", (*args, int(limit)))]


def cost_action(cid, action, user=""):
    """apply：把提醒里的新耗材价格写进设置（没开自动更新时）；dismiss：知道了。"""
    ensure()
    c = db.conn()
    r = c.execute("SELECT * FROM pur_cost_changes WHERE id=?", (int(cid),)).fetchone()
    if not r:
        raise ValueError("没有这条提醒")
    if action == "apply":
        if r["kind"] != "filament":
            raise ValueError("只有耗材价格可以写进设置")
        save_config({"filament_price_cny_per_kg": r["new"]})
        c.execute("UPDATE pur_cost_changes SET applied=1, state='done' WHERE id=?", (r["id"],))
    elif action == "dismiss":
        c.execute("UPDATE pur_cost_changes SET state='done' WHERE id=?", (r["id"],))
    else:
        raise ValueError("操作不对")
    c.commit()
    db.audit(user, "采购·成本变化", r["label"], action)
    return dict(c.execute("SELECT * FROM pur_cost_changes WHERE id=?", (r["id"],)).fetchone())
