"""货位管理（v2.33）：仓库按「区-货架-格」分货位，物品按货位记数量。

  货位编号   区 + 货架 + 格，例如 A-01-03（A 区第 1 个货架第 3 格）；每个货位有条码标签，扫一下就打开
  按货位记数 inv_loc_stock（物品, 货位, 数量）；物品的总数还是以 inv_items.qty 为准，
             没放到货位上的 = 总数 − 各货位之和，叫「未上架」
  自动处理   每一笔库存变化（入库、领用、打印扣料、发货扣包材、盘点……）都经过 ledger.post → on_post：
             入库：开了「入库自动上架」就放进推荐货位，否则先记「未上架」
             出库：先扣「未上架」的，不够再按货位顺序扣（数量少的格子先扣空，腾出货位）
  推荐货位   ① 这个物品已经放着的货位（放得最多的那个）② 物品资料里填的默认货位
             ③ 这个分类默认放的区里第一个空格 ④ 任何一个空格
  货位核对   数一数某个货位里的东西：少了的记回「未上架」，多了的从「未上架」补；总数要改用「盘点」调账
对外：on_post(c, item_id, qty, kind)  suggest(item)  item_locations(item_id)
"""
import contextlib
import re
import threading
import time

from core import db
from core.config import load_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_locations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, zone TEXT, note TEXT, active INTEGER DEFAULT 1, created_at REAL
);
CREATE TABLE IF NOT EXISTS inv_loc_stock (
  item_id INTEGER, loc_id INTEGER, qty REAL DEFAULT 0, updated_at REAL, PRIMARY KEY(item_id, loc_id)
);
CREATE INDEX IF NOT EXISTS inv_loc_stock_loc ON inv_loc_stock(loc_id);
CREATE TABLE IF NOT EXISTS inv_loc_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, item_id INTEGER, from_loc INTEGER, to_loc INTEGER, qty REAL, username TEXT, reason TEXT
);
"""
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,19}$")
_ctx = threading.local()
EPS = 1e-9


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()


@contextlib.contextmanager
def manual():
    """货位自己移动 / 核对时，不要再自动分配（避免同一笔变化被处理两次）。"""
    old = getattr(_ctx, "off", False)
    _ctx.off = True
    try:
        yield
    finally:
        _ctx.off = old


def _now():
    return time.time()


def zones_setting(cfg=None):
    """设置「分类默认放哪个区」：耗材=A, 包材=B → {"filament": "A", "pack": "B"}（中文分类名 / 编号都认）。"""
    from core.inventory import ledger
    cfg = cfg or load_config()
    name2id = {v[0]: k for k, v in ledger.CATEGORIES.items()}
    out = {}
    for part in re.split(r"[,，;；\n]+", str(cfg.get("inv_loc_zones") or "")):
        if "=" not in part and ":" not in part:
            continue
        k, v = re.split(r"[=:：]", part, maxsplit=1)
        k, v = k.strip(), v.strip().upper()
        if k and v:
            out[name2id.get(k, k)] = v
    return out


def locations(active_only=True):
    c = db.conn()
    rows = c.execute("SELECT * FROM inv_locations" + (" WHERE active=1" if active_only else "") + " ORDER BY code").fetchall()
    occ = {r["loc_id"]: (r["n"], r["q"]) for r in c.execute(
        "SELECT loc_id, COUNT(*) n, SUM(qty) q FROM inv_loc_stock WHERE qty>0 GROUP BY loc_id")}
    return [dict(r, items=occ.get(r["id"], (0, 0))[0]) for r in rows]


def get_loc(loc):
    c = db.conn()
    if str(loc).isdigit():
        r = c.execute("SELECT * FROM inv_locations WHERE id=?", (int(loc),)).fetchone()
    else:
        r = c.execute("SELECT * FROM inv_locations WHERE code=?", (str(loc).strip().upper(),)).fetchone()
    return dict(r) if r else None


def save_loc(d, user=""):
    code = str(d.get("code") or "").strip().upper()
    if not CODE_RE.match(code):
        raise ValueError("货位编号只能用英文大写、数字和 -，最多 20 位，例如 A-01-03")
    c = db.conn()
    zone = str(d.get("zone") or code.split("-")[0]).strip().upper()[:10]
    if d.get("id"):
        c.execute("UPDATE inv_locations SET code=?, zone=?, note=?, active=? WHERE id=?",
                  (code, zone, str(d.get("note") or "")[:100], 0 if d.get("active") in (0, "0", False) else 1, int(d["id"])))
        lid = int(d["id"])
    else:
        if c.execute("SELECT 1 FROM inv_locations WHERE code=?", (code,)).fetchone():
            raise ValueError(f"货位 {code} 已经有了")
        lid = c.execute("INSERT INTO inv_locations(code, zone, note, active, created_at) VALUES(?,?,?,1,?)",
                        (code, zone, str(d.get("note") or "")[:100], _now())).lastrowid
    c.commit()
    db.audit(user, "货位", code)
    return get_loc(lid)


def bulk_create(zone, shelves, cells, user=""):
    """批量建货位：zone 区（字母），shelves 个货架，每个货架 cells 格 → A-01-01 … A-0n-mm。已有的跳过。"""
    zone = str(zone or "").strip().upper()
    if not re.match(r"^[A-Z0-9]{1,3}$", zone):
        raise ValueError("区用 1–3 位字母或数字，例如 A")
    try:
        shelves, cells = int(shelves), int(cells)
    except (TypeError, ValueError):
        raise ValueError("货架数和格数要填数字")
    if not (1 <= shelves <= 99 and 1 <= cells <= 99):
        raise ValueError("货架数、每个货架的格数都在 1–99 之间")
    c = db.conn()
    have = {r[0] for r in c.execute("SELECT code FROM inv_locations")}
    made = []
    for s in range(1, shelves + 1):
        for k in range(1, cells + 1):
            code = f"{zone}-{s:02d}-{k:02d}"
            if code in have:
                continue
            c.execute("INSERT INTO inv_locations(code, zone, note, active, created_at) VALUES(?,?,?,1,?)", (code, zone, "", _now()))
            made.append(code)
    c.commit()
    db.audit(user, "批量建货位", zone, f"{len(made)} 个")
    return made


def delete_loc(lid, user=""):
    c = db.conn()
    if c.execute("SELECT 1 FROM inv_loc_stock WHERE loc_id=? AND qty>0", (int(lid),)).fetchone():
        raise ValueError("货位里还有东西，先移走再删")
    r = get_loc(lid)
    c.execute("DELETE FROM inv_loc_stock WHERE loc_id=?", (int(lid),))
    c.execute("DELETE FROM inv_locations WHERE id=?", (int(lid),))
    c.commit()
    db.audit(user, "删除货位", (r or {}).get("code", ""))


# ---------------- 按货位的数量 ----------------
def _rows(c, item_id):
    return [dict(r) for r in c.execute(
        "SELECT s.loc_id, s.qty, l.code FROM inv_loc_stock s JOIN inv_locations l ON l.id=s.loc_id "
        "WHERE s.item_id=? AND s.qty>0 ORDER BY l.code", (item_id,))]


def _total(c, item_id):
    r = c.execute("SELECT qty FROM inv_items WHERE id=?", (item_id,)).fetchone()
    return float(r["qty"] or 0) if r else 0.0


def item_locations(item_id):
    c = db.conn()
    rows = _rows(c, int(item_id))
    placed = sum(r["qty"] for r in rows)
    return {"locations": rows, "unplaced": max(0.0, _total(c, int(item_id)) - placed)}


def _add(c, item_id, loc_id, q):
    c.execute("INSERT INTO inv_loc_stock(item_id, loc_id, qty, updated_at) VALUES(?,?,?,?) "
              "ON CONFLICT(item_id, loc_id) DO UPDATE SET qty=MAX(0, qty+excluded.qty), updated_at=excluded.updated_at",
              (item_id, loc_id, q, _now()))
    c.execute("DELETE FROM inv_loc_stock WHERE item_id=? AND loc_id=? AND qty<=?", (item_id, loc_id, EPS))


def _log(c, item_id, f, t, q, user, reason):
    c.execute("INSERT INTO inv_loc_log(ts, item_id, from_loc, to_loc, qty, username, reason) VALUES(?,?,?,?,?,?,?)",
              (_now(), item_id, f, t, q, user or "", reason or ""))


def suggest(it, cfg=None):
    """推荐货位（见文件开头）。返回 {id, code, why} 或 None。"""
    c = db.conn()
    rows = _rows(c, it["id"])
    if rows:
        best = max(rows, key=lambda r: r["qty"])
        return {"id": best["loc_id"], "code": best["code"], "why": "已经放在这里"}
    if it.get("location"):
        loc = get_loc(it["location"])
        if loc and loc["active"]:
            return {"id": loc["id"], "code": loc["code"], "why": "物品资料里的默认货位"}
    zone = zones_setting(cfg).get(it.get("category"))
    q = ("SELECT l.id, l.code FROM inv_locations l WHERE l.active=1 AND NOT EXISTS "
         "(SELECT 1 FROM inv_loc_stock s WHERE s.loc_id=l.id AND s.qty>0)")
    if zone:
        r = c.execute(q + " AND l.zone=? ORDER BY l.code LIMIT 1", (zone,)).fetchone()
        if r:
            return {"id": r["id"], "code": r["code"], "why": f"{zone} 区的空格"}
    r = c.execute(q + " ORDER BY l.code LIMIT 1").fetchone()
    return {"id": r["id"], "code": r["code"], "why": "空的货位"} if r else None


def on_post(c, item_id, qty, kind, user=""):
    """每一笔库存变化之后（同一个事务里）调整货位上的数量。"""
    if getattr(_ctx, "off", False) or not qty:
        return
    if not c.execute("SELECT 1 FROM inv_locations LIMIT 1").fetchone():
        return                                  # 还没建货位：不用管
    rows = _rows(c, item_id)
    placed = sum(r["qty"] for r in rows)
    total = _total(c, item_id)                  # 已经是变化后的总数
    if qty > 0:
        if not load_config().get("inv_loc_auto", True):
            return
        it = dict(c.execute("SELECT * FROM inv_items WHERE id=?", (item_id,)).fetchone())
        s = suggest(it)
        if s:
            q = min(qty, max(0.0, total - placed))
            if q > EPS:
                _add(c, item_id, s["id"], q)
                _log(c, item_id, None, s["id"], q, user, f"入库自动上架（{s['why']}）")
        return
    # 出库：先扣「未上架」的，不够再扣货位（数量少的先扣）
    over = placed - max(0.0, total)
    for r in sorted(rows, key=lambda r: (r["qty"], r["code"])):
        if over <= EPS:
            break
        q = min(over, r["qty"])
        _add(c, item_id, r["loc_id"], -q)
        _log(c, item_id, r["loc_id"], None, q, user, f"出库（{kind}）")
        over -= q


def move(item_id, from_loc, to_loc, qty, user=""):
    """移库 / 上架：from_loc 为 0 或空 = 从「未上架」拿；to_loc 为 0 或空 = 放回「未上架」。"""
    c = db.conn()
    item_id = int(item_id)
    try:
        q = float(qty)
    except (TypeError, ValueError):
        raise ValueError("数量不对")
    if q <= 0:
        raise ValueError("数量要大于 0")
    f = int(from_loc or 0)
    t = int(to_loc or 0)
    if f == t:
        raise ValueError("从哪里到哪里是同一个地方")
    info = item_locations(item_id)
    have = info["unplaced"] if not f else next((r["qty"] for r in info["locations"] if r["loc_id"] == f), 0)
    if q > have + EPS:
        raise ValueError(f"那里只有 {have:g}，不够移 {q:g}")
    if t and not (get_loc(t) or {}).get("active"):
        raise ValueError("目标货位不存在或已停用")
    with manual():
        if f:
            _add(c, item_id, f, -q)
        if t:
            _add(c, item_id, t, q)
        _log(c, item_id, f or None, t or None, q, user, "上架" if not f else ("移库" if t else "取下（未上架）"))
    c.commit()
    return item_locations(item_id)


def putaway_all(user=""):
    """一键上架：所有「未上架」的数量放进推荐货位。返回 [{item_id, code, qty}]。"""
    from core.inventory import ledger
    out = []
    for r in db.conn().execute("SELECT * FROM inv_items WHERE active=1 AND qty>0"):
        it = ledger.item_row(r)
        un = item_locations(it["id"])["unplaced"]
        if un <= EPS:
            continue
        s = suggest(it)
        if not s:
            break                               # 没有空货位了
        move(it["id"], 0, s["id"], un, user)
        out.append({"item_id": it["id"], "code": s["code"], "qty": un})
    return out


def unplaced():
    """有「未上架」数量的物品 + 推荐货位。"""
    from core.inventory import ledger
    out = []
    cfg = load_config()
    for r in db.conn().execute("SELECT * FROM inv_items WHERE active=1 AND qty>0 ORDER BY category, code"):
        it = ledger.item_row(r)
        un = item_locations(it["id"])["unplaced"]
        if un > EPS:
            out.append({"item": it, "unplaced": un, "suggest": suggest(it, cfg)})
    return out


def loc_detail(lid):
    from core.inventory import ledger
    loc = get_loc(lid)
    if not loc:
        raise ValueError("没有这个货位")
    c = db.conn()
    items = []
    for r in c.execute("SELECT s.qty AS loc_qty, i.* FROM inv_loc_stock s JOIN inv_items i ON i.id=s.item_id "
                       "WHERE s.loc_id=? AND s.qty>0 ORDER BY i.code", (loc["id"],)):
        it = ledger.item_row(r)
        it["loc_qty"] = r["loc_qty"]
        items.append(it)
    log = [dict(r) for r in c.execute(
        "SELECT g.*, i.code, i.name_zh FROM inv_loc_log g JOIN inv_items i ON i.id=g.item_id WHERE g.from_loc=? OR g.to_loc=? "
        "ORDER BY g.id DESC LIMIT 30", (loc["id"], loc["id"]))]
    return {"location": loc, "items": items, "log": log}


def check(lid, counts, user=""):
    """货位核对：counts {物品id: 数到的数量}。少了 → 记回「未上架」；多了 → 从「未上架」补（不够就提示去盘点）。"""
    loc = get_loc(lid)
    if not loc:
        raise ValueError("没有这个货位")
    c = db.conn()
    notes = []
    with manual():
        for iid, v in (counts or {}).items():
            iid = int(iid)
            try:
                n = float(v)
            except (TypeError, ValueError):
                continue
            if n < 0:
                raise ValueError("数量不能是负数")
            info = item_locations(iid)
            cur = next((r["qty"] for r in info["locations"] if r["loc_id"] == loc["id"]), 0.0)
            d = n - cur
            if abs(d) <= EPS:
                continue
            if d < 0:
                _add(c, iid, loc["id"], d)
                _log(c, iid, loc["id"], None, -d, user, f"货位核对 {loc['code']}：少了，记回未上架")
                notes.append({"item_id": iid, "diff": d, "note": "少了的记成「未上架」；确实丢了 / 坏了请到「盘点」或「报废」调账"})
            else:
                take = min(d, info["unplaced"])
                if take > EPS:
                    _add(c, iid, loc["id"], take)
                    _log(c, iid, None, loc["id"], take, user, f"货位核对 {loc['code']}：多了，从未上架补")
                if d - take > EPS:
                    notes.append({"item_id": iid, "diff": d - take, "note": "比账上多，请到「盘点」里调账（盘点会把多出来的放进这个货位）"})
    c.commit()
    db.audit(user, "货位核对", loc["code"], f"{len(counts or {})} 个物品")
    return {"detail": loc_detail(loc["id"]), "notes": notes}


def where_is(code):
    """物品编码（成品就是 SKU）→ [(货位编号, 数量)]，按货位顺序。拣货单用。"""
    c = db.conn()
    r = c.execute("SELECT id FROM inv_items WHERE code=?", (str(code or "").upper(),)).fetchone()
    return [(x["code"], x["qty"]) for x in _rows(c, r["id"])] if r else []


def labels_html(locs):
    """货位标签：每个货位一张（50×30 毫米），Code128 条码 = 货位编号。"""
    from html import escape as h
    from core import labels
    cards = "".join(f"""<div class="lb"><div class="code">{h(l['code'])}</div><div class="bc">{labels.code128_svg(l['code'], height=40, module=2)}</div>
<div class="nt">{h(l.get('note') or '')}</div></div>""" for l in locs) or "<p>没有货位</p>"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>货位标签</title><style>
@page {{ size: 50mm 30mm; margin: 0 }} body {{ margin: 0 }}
.lb {{ width: 50mm; height: 30mm; box-sizing: border-box; padding: 1.5mm 2mm; page-break-after: always; font-family: sans-serif;
      display: flex; flex-direction: column; overflow: hidden }}
.code {{ font: bold 15pt monospace; text-align: center; letter-spacing: 1px }}
.bc {{ height: 13mm }} .bc svg {{ height: 100% }}
.nt {{ font-size: 7pt; text-align: center; white-space: nowrap; overflow: hidden }}
</style></head><body>{cards}<script>setTimeout(() => print(), 300)</script></body></html>"""
