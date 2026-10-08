"""耗材库存与采购计划。

- 库存按「材质 + 颜色」记（公斤）。你录一次现有库存，之后打印完成/失败时自动扣减；进货时点「入库」。
- v2.12 按「卷」管理（树脂是「瓶」）：所有耗材都在同一个仓库，每卷有编号（F0001），状态 未开封 / 已开封在库 / 在机上 / 用完。
  装到哪台打印机上就记在哪台；那台打完一盘，就从它身上那卷扣克数。某个颜色的总库存 = 所有没用完的卷剩余克数之和
  （和上面按公斤的库存始终一致）。快没了、没有备用卷、机上那卷不够下一盘时提前提醒。
- 采购建议：按最近 7 天 / 30 天的实际用量（取较大的）和还没打印的任务需要的量，
  算出能撑几天、什么时候该下单、该买多少（按整卷取整）。
"""
import contextlib
import logging
import math
import threading
import time

from . import db
from .config import load_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory (
  material TEXT NOT NULL, color TEXT NOT NULL, kg REAL DEFAULT 0, note TEXT, updated_at REAL,
  PRIMARY KEY(material, color)
);
CREATE TABLE IF NOT EXISTS inventory_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, material TEXT, color TEXT, delta_kg REAL, reason TEXT, username TEXT
);
CREATE INDEX IF NOT EXISTS invlog_ts ON inventory_log(ts);
CREATE TABLE IF NOT EXISTS spools (
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, material TEXT NOT NULL, color TEXT NOT NULL, brand TEXT,
  net_g REAL, remaining_g REAL, status TEXT DEFAULT 'sealed', printer TEXT, slot TEXT, price REAL, note TEXT,
  created_at REAL, opened_at REAL, loaded_at REAL, emptied_at REAL, dried_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS spools_key ON spools(material, color, status);
"""
SPOOL_ST = {"sealed": "未开封", "open": "已开封（在库）", "loaded": "在机上", "empty": "用完"}
LOW_SPOOL_G = 100          # 机上那卷剩这么少就提醒
DEFAULTS = {"filament_lead_days": 10, "filament_safety_days": 5, "filament_cover_days": 30, "filament_spool_kg": 1.0}


HUMID_DAYS = {"PLA": 30, "PETG": 7, "TPU": 3, "PA": 2, "PC": 3, "ABS": 15, "ASA": 15, "PVA": 2}


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(inventory)")}
    for col in ("opened_at", "dried_at"):
        if col not in cols:
            c.execute(f"ALTER TABLE inventory ADD COLUMN {col} REAL")
    c.commit()
    _migrate_spools()


def _migrate_spools():
    """2.12 以前只按公斤记：把现有库存拆成卷（整卷算未开封，零头算一卷已开封），以后两边始终一致。只做一次。"""
    if db.kv_get("spools_migrated"):
        return
    c = db.conn()
    spool_g = float(load_config().get("filament_spool_kg") or 1.0) * 1000
    now = time.time()
    for r in c.execute("SELECT * FROM inventory WHERE kg>0").fetchall():
        if c.execute("SELECT 1 FROM spools WHERE material=? AND color=?", (r["material"], r["color"])).fetchone():
            continue
        g = r["kg"] * 1000
        full = int(g // spool_g + 1e-9)
        rest = g - full * spool_g
        for _ in range(full):
            _new_spool(c, r["material"], r["color"], spool_g, spool_g, "sealed", note="由原库存转换", now=now)
        if rest >= 1:
            _new_spool(c, r["material"], r["color"], spool_g, rest, "open", note="由原库存转换（零头）", now=now,
                       opened_at=r["opened_at"] or now)
    c.commit()
    db.kv_set("spools_migrated", "1")


def _new_spool(c, material, color, net_g, remaining_g, status="sealed", brand="", price=None, note="", now=None, opened_at=None):
    now = now or time.time()
    sid = c.execute("INSERT INTO spools(material, color, brand, net_g, remaining_g, status, price, note, created_at, opened_at, "
                    "updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (material, color, brand or "", float(net_g), float(remaining_g), status, price, note or "", now,
                     opened_at if status != "sealed" else None, now)).lastrowid
    c.execute("UPDATE spools SET code=? WHERE id=?", (f"F{sid:04d}", sid))
    return sid


def _tracked(c, k):
    return bool(c.execute("SELECT 1 FROM spools WHERE material=? AND color=? LIMIT 1", k).fetchone())


def _sync(c, k):
    """按卷算出总库存，写回 inventory（公斤）。"""
    g = c.execute("SELECT COALESCE(SUM(remaining_g),0) FROM spools WHERE material=? AND color=? AND status!='empty'", k).fetchone()[0]
    c.execute("INSERT INTO inventory(material, color, kg, updated_at) VALUES(?,?,?,?) "
              "ON CONFLICT(material, color) DO UPDATE SET kg=excluded.kg, updated_at=excluded.updated_at", (*k, g / 1000.0, time.time()))


_CTX = threading.local()


@contextlib.contextmanager
def context(**kw):
    """库存管理（core/inventory）调用这里的函数时带上：流水类型 kind、单号 doc_id、单价 unit_cost、ref、printer。"""
    prev = getattr(_CTX, "v", None)
    _CTX.v = {**(prev or {}), **kw}
    try:
        yield
    finally:
        _CTX.v = prev


def _logrow(c, k, delta_kg, reason, user):
    c.execute("INSERT INTO inventory_log(ts, material, color, delta_kg, reason, username) VALUES(?,?,?,?,?,?)",
              (time.time(), k[0], k[1], delta_kg, reason, user))
    # v2.17：耗材数量以库存管理为准，每一笔变化同步记一笔库存流水（同一个事务）
    try:
        from . import chain
        if chain.inv():                   # v2.31：库存模块开着才同步记库存流水
            from .inventory import filament as _inv
            _inv.on_change(c, k, delta_kg, reason, user, getattr(_CTX, "v", None))
    except Exception as e:  # noqa: BLE001  库存流水记不上不能影响打印 / 入库；启动时会自动对齐
        logging.getLogger("3dops").warning("库存流水没记上（%s %s %+.3f kg）：%s", k[0], k[1], delta_kg or 0, e)


def flag(material, color, action, user=""):
    """开封 / 烘干记录（泰国潮湿，PETG、TPU 等开封几天就要烘干）。"""
    m, col = _key(material, color)
    c = db.conn()
    field = "opened_at" if action == "opened" else "dried_at"
    c.execute(f"INSERT INTO inventory(material, color, kg, updated_at, {field}) VALUES(?,?,0,?,?) "
              f"ON CONFLICT(material, color) DO UPDATE SET {field}=excluded.{field}", (m, col, time.time(), time.time()))
    c.execute("INSERT INTO inventory_log(ts, material, color, delta_kg, reason, username) VALUES(?,?,?,?,?,?)",
              (time.time(), m, col, 0, "开封" if action == "opened" else "烘干", user))
    c.commit()


def humid_status(material, opened_at, dried_at, cfg=None):
    if not opened_at and not dried_at:
        return None
    days_map = dict(HUMID_DAYS)
    days_map.update((cfg or {}).get("humid_days") or {})
    lim = days_map.get(str(material).upper().split("-")[0], 30)
    since = max(opened_at or 0, dried_at or 0)
    d = (time.time() - since) / 86400
    return {"days": round(d, 1), "limit": lim, "warn": d >= lim}


def _key(material, color):
    return ((material or "PLA").strip().upper(), (color or "未知").strip())


def set_stock(material, color, kg, user="", note=None):
    """盘点（按公斤）：差额加到 / 扣在已开封的卷上。"""
    m, col = _key(material, color)
    k = (m, col)
    c = db.conn()
    old = c.execute("SELECT kg FROM inventory WHERE material=? AND color=?", k).fetchone()
    delta = float(kg) - (old["kg"] if old else 0)
    if _tracked(c, k) or float(kg) > 0:
        if delta > 0:
            _add_grams(c, k, delta * 1000, "盘点补差")
        elif delta < 0:
            _deduct(c, k, -delta * 1000, None)
        _sync(c, k)
        if note is not None:
            c.execute("UPDATE inventory SET note=? WHERE material=? AND color=?", (note, *k))
    else:
        c.execute("INSERT OR REPLACE INTO inventory(material, color, kg, note, updated_at) VALUES(?,?,?,?,?)",
                  (m, col, float(kg), note, time.time()))
    _logrow(c, k, delta, "盘点", user)
    c.commit()


def add_stock(material, color, kg, user="", reason="入库"):
    """按公斤入库（老接口）：整卷算未开封，零头算一卷已开封。负数 = 扣减。"""
    m, col = _key(material, color)
    k = (m, col)
    c = db.conn()
    g = float(kg) * 1000
    if g > 0:
        spool_g = float(load_config().get("filament_spool_kg") or 1.0) * 1000
        full = int(g // spool_g + 1e-9)
        for _ in range(full):
            _new_spool(c, m, col, spool_g, spool_g, "sealed", note=reason)
        if g - full * spool_g >= 1:
            _add_grams(c, k, g - full * spool_g, reason)
        _settle_negative(c, k)
        _sync(c, k)
    elif g < 0:
        if _tracked(c, k):
            _deduct(c, k, -g, None)
            _sync(c, k)
        else:
            c.execute("INSERT INTO inventory(material, color, kg, updated_at) VALUES(?,?,?,?) "
                      "ON CONFLICT(material, color) DO UPDATE SET kg=kg+excluded.kg, updated_at=excluded.updated_at",
                      (m, col, float(kg), time.time()))
    _logrow(c, k, float(kg), reason, user)
    c.commit()


def consume(material, color, grams, reason="", user="", printer=None):
    """打印用掉的料：从这台打印机身上那卷扣（printer = 机器编码或序号）；没登记装的哪卷，就扣已开封的，再没有就自动开一卷新的。"""
    if not grams:
        return
    m, col = _key(material, color)
    k = (m, col)
    c = db.conn()
    code = _printer_code(printer)
    if _tracked(c, k):
        _deduct(c, k, float(grams), code)
        _sync(c, k)
    else:
        c.execute("INSERT INTO inventory(material, color, kg, updated_at) VALUES(?,?,?,?) "
                  "ON CONFLICT(material, color) DO UPDATE SET kg=kg+excluded.kg, updated_at=excluded.updated_at",
                  (m, col, -float(grams) / 1000.0, time.time()))
    _logrow(c, k, -float(grams) / 1000.0, (reason or "打印消耗") + (f"（{code}）" if code else ""), user)
    c.commit()


def _printer_code(p):
    if p is None or p == "":
        return ""
    if isinstance(p, int) or (isinstance(p, str) and p.isdigit()):
        prs = load_config().get("printers") or []
        i = int(p)
        return (prs[i].get("code") or f"#{i + 1}") if 0 <= i < len(prs) else ""
    return str(p)


def _add_grams(c, k, g, note):
    """零头加到一卷已开封的卷上（没有就新建一卷已开封）。"""
    r = c.execute("SELECT id FROM spools WHERE material=? AND color=? AND status='open' ORDER BY opened_at DESC LIMIT 1", k).fetchone()
    if r:
        c.execute("UPDATE spools SET remaining_g=remaining_g+?, updated_at=? WHERE id=?", (g, time.time(), r["id"]))
    else:
        spool_g = float(load_config().get("filament_spool_kg") or 1.0) * 1000
        _new_spool(c, k[0], k[1], max(spool_g, g), g, "open", note=note, opened_at=time.time())


def _deduct(c, k, g, printer_code):
    """按顺序扣：这台机器上的那卷 → 在机上的（不知道哪台时）→ 已开封的（剩得少的先用）→ 开一卷新的。"""
    now = time.time()
    while g > 0.01:
        r = None
        if printer_code:
            r = c.execute("SELECT * FROM spools WHERE material=? AND color=? AND status='loaded' AND printer=? AND remaining_g>0 "
                          "ORDER BY loaded_at DESC LIMIT 1", (*k, printer_code)).fetchone()
        if not r and not printer_code:
            r = c.execute("SELECT * FROM spools WHERE material=? AND color=? AND status='loaded' AND remaining_g>0 "
                          "ORDER BY remaining_g LIMIT 1", k).fetchone()
        if not r:
            r = c.execute("SELECT * FROM spools WHERE material=? AND color=? AND status='open' AND remaining_g>0 "
                          "ORDER BY remaining_g LIMIT 1", k).fetchone()
            if r and printer_code:   # 显然这卷正装在这台机器上
                c.execute("UPDATE spools SET status='loaded', printer=?, loaded_at=? WHERE id=?", (printer_code, now, r["id"]))
        if not r:
            r = c.execute("SELECT * FROM spools WHERE material=? AND color=? AND status='sealed' ORDER BY id LIMIT 1", k).fetchone()
            if r:
                c.execute("UPDATE spools SET status=?, printer=?, opened_at=?, loaded_at=? WHERE id=?",
                          ("loaded" if printer_code else "open", printer_code or None, now, now if printer_code else None, r["id"]))
        if not r:
            # 没有卷了（实际料比记录多）：记在一卷负数的上，盘点 / 入库时会对平
            neg = c.execute("SELECT id FROM spools WHERE material=? AND color=? AND status='open' AND remaining_g<=0 "
                            "ORDER BY id DESC LIMIT 1", k).fetchone()
            if neg:
                c.execute("UPDATE spools SET remaining_g=remaining_g-?, updated_at=? WHERE id=?", (g, now, neg["id"]))
            else:
                _new_spool(c, k[0], k[1], 0, -g, "open", note="库存记录不够扣（请盘点）", opened_at=now)
            return
        take = min(g, max(0.0, r["remaining_g"] or 0))
        left = (r["remaining_g"] or 0) - take
        if left <= 0.5 and take < g:
            # 这卷扣完了还不够：这卷记用完，剩下的从下一卷扣
            c.execute("UPDATE spools SET remaining_g=0, status='empty', emptied_at=?, updated_at=? WHERE id=?", (now, now, r["id"]))
        else:
            c.execute("UPDATE spools SET remaining_g=?, updated_at=? WHERE id=?", (left, now, r["id"]))
        g -= take


# ---------------- 按卷操作 ----------------
def receive(material, color, count, net_g=1000, brand="", price=None, user=""):
    """入库 N 卷（未开封）。返回新卷编号。"""
    m, col = _key(material, color)
    n = int(count or 0)
    if not 1 <= n <= 200:
        raise ValueError("卷数要在 1 到 200 之间")
    net = float(net_g or 0)
    if not 10 <= net <= 10000:
        raise ValueError("每卷克数不对")
    c = db.conn()
    ids = [_new_spool(c, m, col, net, net, "sealed", brand=brand, price=float(price) if price not in (None, "") else None)
           for _ in range(n)]
    _settle_negative(c, (m, col))
    _sync(c, (m, col))
    with context(kind=(getattr(_CTX, "v", None) or {}).get("kind") or "purchase",
                 **({"unit_cost": float(price) / net} if price not in (None, "") else {})):
        _logrow(c, (m, col), n * net / 1000.0, f"入库 {n} 卷" + (f"（{brand}）" if brand else ""), user)
    c.commit()
    return [f"F{i:04d}" for i in ids]


def _settle_negative(c, k):
    """之前不够扣记成负数的：用新入库的料抵掉（相当于那部分其实早就用了）。"""
    for neg in c.execute("SELECT id, remaining_g FROM spools WHERE material=? AND color=? AND remaining_g<0", k).fetchall():
        owe = -neg["remaining_g"]
        c.execute("UPDATE spools SET remaining_g=0, status='empty', emptied_at=? WHERE id=?", (time.time(), neg["id"]))
        _deduct(c, k, owe, None)


def spool_get(sid):
    r = db.conn().execute("SELECT * FROM spools WHERE id=? OR code=?", (sid if str(sid).isdigit() else -1, str(sid).upper())).fetchone()
    return _spool_row(r) if r else None


def _spool_row(r, cfg=None):
    d = dict(r)
    d["status_zh"] = SPOOL_ST.get(d["status"], d["status"])
    d["pct"] = round(100 * (d["remaining_g"] or 0) / d["net_g"], 0) if d.get("net_g") else None
    d["humid"] = humid_status(d["material"], d.get("opened_at"), d.get("dried_at"), cfg) if d["status"] in ("open", "loaded") else None
    return d


def spools(material="", color="", status="", printer=""):
    c = db.conn()
    conds, args = [], []
    if material:
        conds.append("material=?"); args.append(material.strip().upper())
    if color:
        conds.append("color=?"); args.append(color.strip())
    if status == "active":
        conds.append("status!='empty'")
    elif status:
        conds.append("status=?"); args.append(status)
    if printer:
        conds.append("printer=?"); args.append(printer)
    cfg = load_config()
    rows = c.execute("SELECT * FROM spools" + (" WHERE " + " AND ".join(conds) if conds else "") +
                     " ORDER BY CASE status WHEN 'loaded' THEN 0 WHEN 'open' THEN 1 WHEN 'sealed' THEN 2 ELSE 3 END, material, color, id",
                     args).fetchall()
    return [_spool_row(r, cfg) for r in rows]


def spool_action(sid, action, user="", printer="", slot="", grams=None, brand=None, note=None):
    """load 上机 / unload 下机 / weigh 称重校准 / empty 用完 / dry 烘干 / edit / delete（只能删未开封的，录错时用）。"""
    c = db.conn()
    s = spool_get(sid)
    if not s:
        raise ValueError("找不到这卷耗材")
    k = (s["material"], s["color"])
    now = time.time()
    if action == "load":
        code = _printer_code(printer)
        if not code:
            raise ValueError("请选择装到哪台打印机")
        if s["status"] == "empty":
            raise ValueError("这卷已经用完了")
        # 同一台机器同一个料位上原来那卷：退回「已开封在库」
        if slot:
            for o in c.execute("SELECT id, code FROM spools WHERE status='loaded' AND printer=? AND slot=? AND id!=?", (code, slot, s["id"])):
                c.execute("UPDATE spools SET status='open', printer=NULL, slot=NULL, updated_at=? WHERE id=?", (now, o["id"]))
        else:
            # 没有料位的机器（K1 / 单料）：同一台上原来装的都退下来
            prs = {p.get("code"): p for p in (load_config().get("printers") or [])}
            from . import printers as pr_mod
            multi = False
            try:
                i = list(prs).index(code)
                multi = bool(pr_mod.get_status(i).get("trays"))
            except (ValueError, Exception):  # noqa: BLE001
                multi = False
            if not multi:
                c.execute("UPDATE spools SET status='open', printer=NULL, slot=NULL, updated_at=? WHERE status='loaded' AND printer=? AND id!=?",
                          (now, code, s["id"]))
        c.execute("UPDATE spools SET status='loaded', printer=?, slot=?, loaded_at=?, opened_at=COALESCE(opened_at, ?), updated_at=? WHERE id=?",
                  (code, slot or None, now, now, now, s["id"]))
        msg = f"{s['code']} 装到 {code}{(' ' + slot) if slot else ''}"
    elif action == "unload":
        if grams not in (None, ""):
            _set_remaining(c, s, float(grams), user, "下机称重")
        c.execute("UPDATE spools SET status=CASE WHEN status='empty' THEN 'empty' ELSE 'open' END, printer=NULL, slot=NULL, updated_at=? WHERE id=?",
                  (now, s["id"]))
        msg = f"{s['code']} 从 {s['printer'] or ''} 取下"
    elif action == "weigh":
        if grams in (None, ""):
            raise ValueError("请填写剩余克数（不含料盘）")
        _set_remaining(c, s, float(grams), user, "称重校准")
        msg = f"{s['code']} 称重 {float(grams):.0f} g"
    elif action == "empty":
        if s["remaining_g"]:
            _logrow(c, k, -(s["remaining_g"] or 0) / 1000.0, f"{s['code']} 用完（剩余清零）", user)
        c.execute("UPDATE spools SET remaining_g=0, status='empty', printer=NULL, slot=NULL, emptied_at=?, updated_at=? WHERE id=?",
                  (now, now, s["id"]))
        msg = f"{s['code']} 用完"
    elif action == "dry":
        c.execute("UPDATE spools SET dried_at=?, updated_at=? WHERE id=?", (now, now, s["id"]))
        c.execute("UPDATE inventory SET dried_at=? WHERE material=? AND color=?", (now, *k))
        msg = f"{s['code']} 烘干"
    elif action == "edit":
        c.execute("UPDATE spools SET brand=COALESCE(?, brand), note=COALESCE(?, note), updated_at=? WHERE id=?",
                  (brand, note, now, s["id"]))
        msg = f"{s['code']} 修改"
    elif action == "delete":
        if s["status"] != "sealed":
            raise ValueError("只能删除未开封的卷（录错时用）；用过的请点「用完」")
        c.execute("DELETE FROM spools WHERE id=?", (s["id"],))
        _logrow(c, k, -(s["remaining_g"] or 0) / 1000.0, f"{s['code']} 删除（录错）", user)
        msg = f"{s['code']} 删除"
    else:
        raise ValueError("操作不对")
    _sync(c, k)
    c.commit()
    db.audit(user, "耗材", s["code"], msg)
    return spool_get(s["id"]) if action != "delete" else None


def _set_remaining(c, s, g, user, why):
    g = max(0.0, g)
    delta = g - (s["remaining_g"] or 0)
    if abs(delta) >= 0.5:
        c.execute("UPDATE spools SET remaining_g=?, updated_at=? WHERE id=?", (g, time.time(), s["id"]))
        _logrow(c, (s["material"], s["color"]), delta / 1000.0, f"{s['code']} {why}", user)


def by_key():
    """每个颜色：未开封几卷、已开封几卷、在机上几卷（在哪台）、总克数。"""
    out = {}
    for r in db.conn().execute("SELECT * FROM spools WHERE status!='empty'"):
        d = out.setdefault((r["material"], r["color"]), {"sealed": 0, "open": 0, "loaded": 0, "on": []})
        d[r["status"]] = d.get(r["status"], 0) + 1
        if r["status"] == "loaded":
            d["on"].append({"code": r["code"], "printer": r["printer"], "slot": r["slot"], "remaining_g": round(r["remaining_g"] or 0)})
    return out


def _next_need():
    """每台打印机排在最前面的任务，下一盘要多少克（按颜色）。"""
    out = {}
    try:
        from . import production
        c = db.conn()
        names = production._printer_names()
        prs = load_config().get("printers") or []
        seen = set()
        for j in c.execute("SELECT * FROM jobs WHERE status='todo' AND printer IS NOT NULL ORDER BY COALESCE(planned_start, 9e12)"):
            if j["printer"] in seen:
                continue
            seen.add(j["printer"])
            pl = production.plan_for(j, j["printer"], names)
            code = (prs[j["printer"]].get("code") or f"#{j['printer'] + 1}") if 0 <= j["printer"] < len(prs) else ""
            out[code] = {"key": _key(j["material"], j["color"]), "grams": pl.get("grams_per_plate") or 0, "sku": j["sku"]}
    except Exception:  # noqa: BLE001  排单信息拿不到不影响提醒
        pass
    return out


def alerts(plan_rows=None):
    """耗材提醒：哪个颜色快没了、没有备用卷、机上那卷不够下一盘、开封太久该烘干。"""
    rows = plan_rows if plan_rows is not None else plan()["rows"]
    bk = by_key()
    out = []
    for r in rows:
        k = (r["material"], r["color"])
        d = bk.get(k) or {"sealed": 0, "open": 0, "loaded": 0}
        name = f"{r['material']} {r['color']}"
        if r["short"]:
            out.append({"level": "bad", "key": list(k), "text": f"{name} 不够打已经排队的单（还差 {max(0, r['pending_kg'] - r['kg']):.2f} kg），要马上补货"})
        elif r["urgent"]:
            import datetime as _dt
            ob = r["order_by_date"]
            when = "现在就该下单" if not ob or ob <= _dt.date.today().isoformat() else f"最晚 {ob} 下单"
            out.append({"level": "warn", "key": list(k), "text": f"{name} 预计 {r['runout_date'] or '很快'} 用完，{when}，建议买 {r['suggest_spools'] or 1} 卷"})
        if (r["daily_kg"] or r["pending_kg"]) and not d["sealed"] and r["kg"] > 0 and not r["short"]:
            out.append({"level": "warn", "key": list(k), "text": f"{name} 只剩正在用的 {r['kg'] * 1000:.0f} g，没有未开封的备用卷"})
    need = _next_need()
    for code, n in need.items():
        on = [s for s in (bk.get(n["key"]) or {}).get("on", []) if s["printer"] == code]
        if on:
            left = sum(s["remaining_g"] for s in on)
            if n["grams"] and left < n["grams"]:
                out.append({"level": "bad", "key": list(n["key"]), "printer": code,
                            "text": f"{code} 上的 {n['key'][0]} {n['key'][1]}（{'、'.join(s['code'] for s in on)}）只剩 {left:.0f} g，下一盘 {n['sku']} 要 {n['grams']:.0f} g，开打前先换料"})
    for k, d in bk.items():
        for s in d["on"]:
            if s["remaining_g"] < LOW_SPOOL_G and not any(a.get("printer") == s["printer"] and a["key"] == list(k) for a in out):
                out.append({"level": "warn", "key": list(k), "printer": s["printer"],
                            "text": f"{s['printer']} 上的 {k[0]} {k[1]}（{s['code']}）只剩 {s['remaining_g']} g，准备一卷换上"})
    cfg = load_config()
    for s in spools(status="active"):
        h = s.get("humid")
        if h and h["warn"]:
            out.append({"level": "warn", "key": [s["material"], s["color"]],
                        "text": f"{s['code']} {s['material']} {s['color']} 开封 / 烘干后 {h['days']} 天了（建议 {h['limit']} 天内），用之前先烘干"})
    order = {"bad": 0, "warn": 1}
    out.sort(key=lambda a: order.get(a["level"], 2))
    return out


def _job_demand():
    """还没打的任务还需要多少料（按打印文件 / 产品克数）+ 正在打的那一盘（还没扣）。"""
    out, by_job = {}, []
    c = db.conn()
    try:
        rows = c.execute("SELECT * FROM jobs WHERE status='todo' AND run_id IS NULL").fetchall()
        runs = c.execute("SELECT material, color, grams FROM print_runs WHERE status='printing'").fetchall()
    except Exception:  # 还没有任务表
        return out, by_job
    from . import production
    names = production._printer_names()
    for j in rows:
        pl = production.plan_for(j, j["printer"], names)
        need = pl["grams"] / 1000.0
        k = _key(j["material"], j["color"])
        out[k] = out.get(k, 0) + need
        by_job.append((k, j["id"], need))
    for r in runs:
        k = _key(r["material"], r["color"])
        out[k] = out.get(k, 0) + (r["grams"] or 0) / 1000.0
    return out, by_job


def _order_rate(now):
    """按最近 14 天 / 30 天的订单销量预测每天要用多少料（订单里每个 SKU 的克数 × 件数）。"""
    c = db.conn()
    rate, skus = {}, {}
    try:
        rows = c.execute("""SELECT i.sku, i.color, i.material, i.grams, i.qty, o.order_time FROM order_items i
                            JOIN orders o ON o.id=i.order_id
                            WHERE o.order_time>=? AND o.status NOT IN ('cancelled','unpaid','quote') AND i.grams>0""",
                         (now - 30 * 86400,)).fetchall()
    except Exception:  # 还没有订单表
        return rate, skus
    agg = {}
    for r in rows:
        k = _key(r["material"], r["color"])
        kg = (r["grams"] or 0) * (r["qty"] or 1) / 1000.0
        a = agg.setdefault(k, [0.0, 0.0])
        a[1] += kg
        if r["order_time"] >= now - 14 * 86400:
            a[0] += kg
        sk = skus.setdefault(k, {})
        sk[r["sku"]] = sk.get(r["sku"], 0) + (r["qty"] or 1)
    for k, (kg14, kg30) in agg.items():
        rate[k] = 0.6 * kg14 / 14 + 0.4 * kg30 / 30      # 近期权重大一点
    return rate, skus


def plan():
    """耗材采购计划：库存 − 待打印任务需要的量 = 可用；
    每天用量 = 实际消耗（近 7/30 天）和订单销量预测中较大的；
    算出还能用几天、哪天用完、最晚哪天要下单、该买几卷。"""
    import datetime as dt
    cfg = load_config()
    p = {k: float(cfg.get(k, v)) for k, v in DEFAULTS.items()}
    c = db.conn()
    now = time.time()
    stock = {(r["material"], r["color"]): dict(r) for r in c.execute("SELECT * FROM inventory")}
    use7, use30 = {}, {}
    for days, target in ((7, use7), (30, use30)):
        for r in c.execute("SELECT material, color, SUM(-delta_kg) AS kg FROM inventory_log WHERE delta_kg<0 AND ts>=? "
                           "AND reason NOT LIKE '盘点%' GROUP BY material, color", (now - days * 86400,)):
            target[(r["material"], r["color"])] = r["kg"] or 0
    pending, _ = _job_demand()
    orate, skus = _order_rate(now)
    keys = set(stock) | set(use30) | set(pending) | set(orate)
    rows = []
    horizon = p["filament_lead_days"] + p["filament_safety_days"] + p["filament_cover_days"]
    spool = p["filament_spool_kg"] or 1.0
    for k in sorted(keys):
        on = (stock.get(k) or {}).get("kg", 0.0)
        used_rate = max(use7.get(k, 0) / 7.0, use30.get(k, 0) / 30.0)
        rate = max(used_rate, orate.get(k, 0.0))          # 公斤/天
        need = pending.get(k, 0.0)
        free = on - need
        days_left = (free / rate) if rate > 0 else (None if free >= 0 else 0)
        runout = order_by = None
        if days_left is not None:
            runout = now + max(0, days_left) * 86400
            order_by = runout - (p["filament_lead_days"] + p["filament_safety_days"]) * 86400
        reorder_at = rate * (p["filament_lead_days"] + p["filament_safety_days"])
        target = rate * horizon + need
        buy = max(0.0, target - on)
        buy_spools = math.ceil(buy / spool - 1e-9) if buy > 0.05 else 0
        if free < 0:
            buy_spools = max(1, math.ceil((-free) / spool - 1e-9), buy_spools)
        urgent = free < 0 or (rate > 0 and free <= reorder_at)
        top = sorted((skus.get(k) or {}).items(), key=lambda x: -x[1])[:3]
        fmt = (lambda t: dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d") if t else None)
        rows.append({"material": k[0], "color": k[1], "kg": round(on, 3), "pending_kg": round(need, 3),
                     "use7_kg": round(use7.get(k, 0), 3), "use30_kg": round(use30.get(k, 0), 3),
                     "used_daily_kg": round(used_rate, 3), "order_daily_kg": round(orate.get(k, 0), 3),
                     "daily_kg": round(rate, 3), "days_left": None if days_left is None else round(days_left, 1),
                     "runout_date": fmt(runout), "order_by_date": fmt(order_by),
                     "forecast_kg": round(rate * horizon + need, 2),
                     "buy_spools": buy_spools if urgent else 0, "suggest_spools": buy_spools,
                     "urgent": urgent, "short": free < 0, "top_skus": [{"sku": a, "qty": b} for a, b in top],
                     "humid": humid_status(k[0], (stock.get(k) or {}).get("opened_at"), (stock.get(k) or {}).get("dried_at"), cfg),
                     "opened_at": (stock.get(k) or {}).get("opened_at"), "dried_at": (stock.get(k) or {}).get("dried_at")})
    bk = by_key()
    for r in rows:
        d = bk.get((r["material"], r["color"])) or {}
        r["spools"] = {"sealed": d.get("sealed", 0), "open": d.get("open", 0), "loaded": d.get("loaded", 0), "on": d.get("on", [])}
    rows.sort(key=lambda r: (not r["short"], not r["urgent"], r["days_left"] if r["days_left"] is not None else 1e9))
    return {"rows": rows, "params": p, "horizon_days": horizon}


def check_job_stock(job_grams, material, color, printer=None):
    """发送打印前检查库存够不够这一盘（有登记机上那卷时，看那卷够不够）。返回提示文字或空。"""
    k = _key(material, color)
    c = db.conn()
    code = _printer_code(printer)
    if code:
        on = c.execute("SELECT code, remaining_g FROM spools WHERE material=? AND color=? AND status='loaded' AND printer=?",
                       (*k, code)).fetchall()
        if on:
            left = sum(x["remaining_g"] or 0 for x in on)
            if left < job_grams:
                return (f"{code} 上的 {k[0]} {k[1]}（{'、'.join(x['code'] for x in on)}）记录只剩 {left:.0f} g，"
                        f"这一盘要约 {job_grams:.0f} g，可能打到一半断料，请确认或先换料")
    r = c.execute("SELECT kg FROM inventory WHERE material=? AND color=?", k).fetchone()
    if r is None:
        return ""
    if r["kg"] * 1000 < job_grams:
        return f"库存记录里 {k[0]} {k[1]} 只剩 {r['kg']:.2f} kg，不够这一盘（约 {job_grams:.0f} g），请确认实际料量"
    return ""


def log(limit=200):
    return [dict(r) for r in db.conn().execute("SELECT * FROM inventory_log ORDER BY id DESC LIMIT ?", (int(limit),))]
