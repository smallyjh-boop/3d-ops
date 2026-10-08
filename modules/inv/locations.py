"""货位管理（v2.33 建，v2.34 改成「区 + 货架号 - 层 - 位」）。

  货位编号   区字母 + 货架号 - 层 - 位，例如 A1-02-03 = A 区 1 号货架 第 2 层 第 3 位
             区 1–2 个英文字母；货架号 1–99；层、位写两位数字。输入时 a1-2-3 也认（自动写成 A1-02-03）
  建货架     选区、货架号（默认接着排）、几层、每层几位，一次生成全部货位；之后可以单独「加一层」「这一层加一位」，
             空的位 / 层 / 整个货架可以删
  放什么     货架（或整个区）可以设「放哪些分类」：入库自动上架时先找这个分类的货架里的空位
  层号方向   设置里选「最下面一层是第 1 层」（默认）还是「最上面是第 1 层」，只影响页面上货架的画法
  按货位记数 inv_loc_stock（物品, 货位, 数量）；物品的总数还是以 inv_items.qty 为准，
             没放到货位上的 = 总数 − 各货位之和，叫「未上架」
  自动处理   每一笔库存变化（入库、领用、打印扣料、发货扣包材、盘点……）都经过 ledger.post → on_post：
             入库：开了「入库自动上架」就放进推荐货位，否则先记「未上架」
             出库：先扣「未上架」的，不够再按货位顺序扣（数量少的位先扣空，腾出货位）
  推荐货位   ① 这个物品已经放着的货位（放得最多的那个）② 物品资料里填的默认货位 / 货架 / 区
             ③ 放这个分类的货架（货架没设就看区）里的空位 ④ 没指定分类的货架里的空位
             都没有 → 留在「未上架」，人工放（不会塞进指定给别的分类的货架）
  货位核对   数一数某个货位里的东西：少了的记回「未上架」，多了的从「未上架」补；总数要改用「盘点」调账
对外：on_post(c, item_id, qty, kind)  suggest(item)  item_locations(item_id)  where_is(code)  sort_key(code)
"""
import contextlib
import re
import threading
import time

from core import db
from core.config import load_config, save_config

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
CREATE TABLE IF NOT EXISTS inv_loc_groups (
  code TEXT PRIMARY KEY, kind TEXT, name TEXT, categories TEXT, updated_at REAL
);
"""
CODE_RE = re.compile(r"^([A-Z]{1,2})(\d{1,2})-(\d{2})-(\d{2})$")                 # A1-02-03
LOOSE_RE = re.compile(r"^([A-Z]{1,2})\s*(\d{1,2})\s*[-_ /.]\s*(\d{1,2})\s*[-_ /.]\s*(\d{1,2})$")
OLD_RE = re.compile(r"^([A-Z]{1,2})-(\d{2})-(\d{2})$")                            # v2.33：区-货架-格
SHELF_RE = re.compile(r"^([A-Z]{1,2})(\d{1,2})$")                                 # A1
ZONE_RE = re.compile(r"^[A-Z]{1,2}$")                                             # A
MAX_LAYERS, MAX_POS = 20, 50
_ctx = threading.local()
EPS = 1e-9


# ---------------- 编号 ----------------
def make_code(zone, shelf, layer, pos):
    return f"{zone}{int(shelf)}-{int(layer):02d}-{int(pos):02d}"


def shelf_code(zone, shelf):
    return f"{zone}{int(shelf)}"


def norm_code(code):
    """输入的货位编号 → 标准写法（a1-2-3 → A1-02-03）；不是货位编号的原样大写返回。"""
    s = str(code or "").strip().upper()
    m = LOOSE_RE.match(s)
    if m and 1 <= int(m.group(2)) <= 99 and 1 <= int(m.group(3)) <= 99 and 1 <= int(m.group(4)) <= 99:
        return make_code(m.group(1), m.group(2), m.group(3), m.group(4))
    return s


def parse(code):
    """A1-02-03 → (区, 货架号, 层, 位)；不是标准编号返回 None。"""
    m = CODE_RE.match(norm_code(code))
    return (m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))) if m else None


def sort_key(code):
    """按 区 → 货架号 → 层 → 位 排（A2 排在 A10 前面）；不是标准编号的排最后。"""
    p = parse(code)
    return (0, p[0], p[1], p[2], p[3], "") if p else (1, "", 0, 0, 0, str(code or ""))


def human(code, lang="zh"):
    """A1-02-03 → A区 1号货架 第2层 第3位"""
    p = parse(code)
    if not p:
        return str(code or "")
    z, s, l, n = p
    return f"โซน {z} แร็ค {s} ชั้น {l} ช่อง {n}" if lang == "th" else f"{z}区 {s}号货架 第{l}层 第{n}位"


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(inv_locations)")}
    for col in ("shelf", "layer", "pos"):
        if col not in cols:
            c.execute(f"ALTER TABLE inv_locations ADD COLUMN {col} INTEGER")
    c.commit()
    _migrate(c)


def _migrate(c):
    """v2.33 → v2.34：① 「区-货架-格」A-01-03 → A1-01-03（原来没有层，记成第 1 层）；已经是新写法的补上 区/货架/层/位；
    ② 设置里「分类=区」的写法搬到区的「放哪些分类」。"""
    rows = c.execute("SELECT id, code FROM inv_locations WHERE shelf IS NULL").fetchall()
    have = {r[0] for r in c.execute("SELECT code FROM inv_locations")}
    moved = []
    for r in rows:
        code = r["code"]
        p = parse(code)
        if not p:
            m = OLD_RE.match(code or "")
            if m:
                new = make_code(m.group(1), m.group(2), 1, m.group(3))
                if new not in have:
                    have.add(new)
                    moved.append(f"{code}→{new}")
                    code = new
                    p = parse(new)
        if p:
            c.execute("UPDATE inv_locations SET code=?, zone=?, shelf=?, layer=?, pos=? WHERE id=?", (code, p[0], p[1], p[2], p[3], r["id"]))
    old = str(load_config().get("inv_loc_zones") or "").strip()
    if old:
        for cat, zone in _old_zones(old).items():
            if ZONE_RE.match(zone) or SHELF_RE.match(zone):
                g = _group(c, zone) or {"categories": []}
                if cat not in g["categories"]:
                    _save_group(c, zone, g.get("name") or "", g["categories"] + [cat])
    c.commit()
    if old:
        save_config({"inv_loc_zones": ""})
    if moved:
        db.audit("系统", "货位编号改新写法", f"{len(moved)} 个", "，".join(moved)[:480])


def _old_zones(text):
    """v2.33 设置的写法：耗材=A, 包材=B → {"filament": "A", "pack": "B"}"""
    from core.inventory import ledger
    name2id = {v[0]: k for k, v in ledger.CATEGORIES.items()}
    out = {}
    for part in re.split(r"[,，;；\n]+", text):
        if "=" not in part and ":" not in part and "：" not in part:
            continue
        k, v = re.split(r"[=:：]", part, maxsplit=1)
        k, v = k.strip(), v.strip().upper()
        if k and v:
            out[name2id.get(k, k)] = v
    return out


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


def layer_bottom(cfg=None):
    return bool((cfg or load_config()).get("inv_loc_layer_bottom", True))


# ---------------- 区 / 货架的说明（名字、放哪些分类）----------------
def _group(c, code):
    r = c.execute("SELECT * FROM inv_loc_groups WHERE code=?", (code,)).fetchone()
    return _g(r) if r else None


def _g(r):
    return {"code": r["code"], "kind": r["kind"], "name": r["name"] or "",
            "categories": [x for x in (r["categories"] or "").split(",") if x]}


def groups():
    return {r["code"]: _g(r) for r in db.conn().execute("SELECT * FROM inv_loc_groups ORDER BY code")}


def _save_group(c, code, name, cats):
    kind = "zone" if ZONE_RE.match(code) else "shelf"
    c.execute("INSERT INTO inv_loc_groups(code, kind, name, categories, updated_at) VALUES(?,?,?,?,?) "
              "ON CONFLICT(code) DO UPDATE SET kind=excluded.kind, name=excluded.name, categories=excluded.categories, "
              "updated_at=excluded.updated_at", (code, kind, str(name or "")[:40], ",".join(dict.fromkeys(cats)), _now()))


def _valid_cats(categories):
    from core.inventory import ledger
    valid = {x["id"] for x in ledger.categories()}
    return [str(x) for x in (categories or []) if str(x) in valid]


def save_group(code, name="", categories=None, user=""):
    """区（A）或货架（A1）的名字、放哪些分类。"""
    code = str(code or "").strip().upper()
    if not (ZONE_RE.match(code) or SHELF_RE.match(code)):
        raise ValueError("区写字母（例如 A），货架写区字母 + 货架号（例如 A1）")
    cats = _valid_cats(categories)
    c = db.conn()
    _save_group(c, code, name, cats)
    c.commit()
    db.audit(user, "货位分区", code, f"{name} · {','.join(cats)}")
    return groups().get(code)


# ---------------- 货位列表 ----------------
def locations(active_only=True):
    c = db.conn()
    rows = c.execute("SELECT * FROM inv_locations" + (" WHERE active=1" if active_only else "")).fetchall()
    items = {}
    for r in c.execute("SELECT s.loc_id, s.qty, i.code, i.name_zh, i.name_th, i.unit FROM inv_loc_stock s "
                       "JOIN inv_items i ON i.id=s.item_id WHERE s.qty>0 ORDER BY s.qty DESC"):
        items.setdefault(r["loc_id"], []).append({"code": r["code"], "name_zh": r["name_zh"], "name_th": r["name_th"],
                                                 "qty": r["qty"], "unit": r["unit"]})
    out = [dict(r, items=len(items.get(r["id"], [])), top=items.get(r["id"], [])[:4]) for r in rows]
    return sorted(out, key=lambda l: sort_key(l["code"]))


def get_loc(loc):
    c = db.conn()
    if str(loc).isdigit():
        r = c.execute("SELECT * FROM inv_locations WHERE id=?", (int(loc),)).fetchone()
        return dict(r) if r else None
    code = norm_code(loc)
    r = c.execute("SELECT * FROM inv_locations WHERE code=?", (code,)).fetchone()
    if not r:
        m = OLD_RE.match(code)                   # v2.33 打的旧标签 A-01-03 扫进来也认
        if m:
            r = c.execute("SELECT * FROM inv_locations WHERE code=?", (make_code(m.group(1), m.group(2), 1, m.group(3)),)).fetchone()
    return dict(r) if r else None


def _insert(c, zone, shelf, layer, pos, note=""):
    code = make_code(zone, shelf, layer, pos)
    return c.execute("INSERT INTO inv_locations(code, zone, shelf, layer, pos, note, active, created_at) VALUES(?,?,?,?,?,?,1,?)",
                     (code, zone, int(shelf), int(layer), int(pos), str(note or "")[:100], _now())).lastrowid


def save_loc(d, user=""):
    """单个货位：{code: "A1-02-03"} 或 {zone, shelf, layer, pos}；有 id 就是改备注 / 停用。"""
    c = db.conn()
    if d.get("id"):
        old = get_loc(int(d["id"]))
        if not old:
            raise ValueError("没有这个货位")
        c.execute("UPDATE inv_locations SET note=?, active=? WHERE id=?",
                  (str(d.get("note") or "")[:100], 0 if d.get("active") in (0, "0", False) else 1, int(d["id"])))
        c.commit()
        db.audit(user, "货位", old["code"], "改备注 / 停用")
        return get_loc(int(d["id"]))
    if d.get("code"):
        p = parse(d["code"])
    else:
        try:
            p = (str(d.get("zone") or "").strip().upper(), int(d.get("shelf")), int(d.get("layer")), int(d.get("pos")))
        except (TypeError, ValueError):
            p = None
    if not p or not ZONE_RE.match(p[0]) or not (1 <= p[1] <= 99 and 1 <= p[2] <= MAX_LAYERS and 1 <= p[3] <= MAX_POS):
        raise ValueError(f"货位编号写法：区字母 + 货架号 - 层 - 位，例如 A1-02-03（最多 {MAX_LAYERS} 层、每层 {MAX_POS} 位）")
    code = make_code(*p)
    if c.execute("SELECT 1 FROM inv_locations WHERE code=?", (code,)).fetchone():
        raise ValueError(f"货位 {code} 已经有了")
    lid = _insert(c, *p, note=d.get("note"))
    c.commit()
    db.audit(user, "货位", code)
    return get_loc(lid)


def next_shelf(zone):
    r = db.conn().execute("SELECT MAX(shelf) FROM inv_locations WHERE zone=?", (str(zone or "").upper(),)).fetchone()
    return int(r[0] or 0) + 1


def bulk_create(zone, shelf=None, layers=1, positions=1, name="", categories=None, user=""):
    """建货架：zone 区字母，shelf 货架号（空 = 接着排），layers 层 × positions 位 → A1-01-01 … A1-0n-mm。已有的跳过。"""
    zone = str(zone or "").strip().upper()
    if not ZONE_RE.match(zone):
        raise ValueError("区用 1–2 个英文字母，例如 A")
    try:
        shelf = int(shelf) if str(shelf or "").strip() else next_shelf(zone)
        layers, positions = int(layers), int(positions)
    except (TypeError, ValueError):
        raise ValueError("货架号、层数、每层位数要填数字")
    if not (1 <= shelf <= 99):
        raise ValueError("货架号在 1–99 之间")
    if not (1 <= layers <= MAX_LAYERS and 1 <= positions <= MAX_POS):
        raise ValueError(f"层数 1–{MAX_LAYERS}，每层位数 1–{MAX_POS}")
    c = db.conn()
    have = {r[0] for r in c.execute("SELECT code FROM inv_locations")}
    made = []
    for layer in range(1, layers + 1):
        for pos in range(1, positions + 1):
            code = make_code(zone, shelf, layer, pos)
            if code in have:
                continue
            _insert(c, zone, shelf, layer, pos)
            made.append(code)
    sc = shelf_code(zone, shelf)
    if name or categories:
        g = _group(c, sc) or {"name": "", "categories": []}
        _save_group(c, sc, name or g["name"], _valid_cats(categories) if categories is not None else g["categories"])
    c.commit()
    db.audit(user, "建货架", sc, f"{layers} 层 × {positions} 位，新建 {len(made)} 个货位")
    return {"shelf": sc, "made": made}


def _shelf_rows(c, sc):
    m = SHELF_RE.match(str(sc or "").strip().upper())
    if not m:
        raise ValueError("货架写区字母 + 货架号，例如 A1")
    return m.group(1), int(m.group(2)), [dict(r) for r in c.execute(
        "SELECT * FROM inv_locations WHERE zone=? AND shelf=? ORDER BY layer, pos", (m.group(1), int(m.group(2))))]


def add_layer(sc, user=""):
    """加一层（放在最大的层号上面），位数和现在最高那层一样。"""
    c = db.conn()
    zone, shelf, rows = _shelf_rows(c, sc)
    if not rows:
        raise ValueError(f"没有货架 {sc}")
    top = max(r["layer"] for r in rows)
    if top >= MAX_LAYERS:
        raise ValueError(f"最多 {MAX_LAYERS} 层")
    n = sum(1 for r in rows if r["layer"] == top) or 1
    made = [make_code(zone, shelf, top + 1, p) for p in range(1, n + 1)]
    for p in range(1, n + 1):
        _insert(c, zone, shelf, top + 1, p)
    c.commit()
    db.audit(user, "货架加一层", shelf_code(zone, shelf), f"第 {top + 1} 层 {n} 位")
    return made


def add_pos(sc, layer, user=""):
    """某一层加一位（放在这一层最后）。"""
    c = db.conn()
    zone, shelf, rows = _shelf_rows(c, sc)
    if not rows:
        raise ValueError(f"没有货架 {sc}")
    layer = int(layer)
    if not (1 <= layer <= MAX_LAYERS):
        raise ValueError("层号不对")
    last = max([r["pos"] for r in rows if r["layer"] == layer] or [0])
    if last >= MAX_POS:
        raise ValueError(f"每层最多 {MAX_POS} 位")
    _insert(c, zone, shelf, layer, last + 1)
    c.commit()
    code = make_code(zone, shelf, layer, last + 1)
    db.audit(user, "货架加一位", code)
    return code


def _ensure_empty(c, ids):
    if not ids:
        return
    q = ",".join("?" * len(ids))
    full = [r[0] for r in c.execute(f"SELECT DISTINCT l.code FROM inv_loc_stock s JOIN inv_locations l ON l.id=s.loc_id "
                                     f"WHERE s.loc_id IN ({q}) AND s.qty>0", ids)]
    if full:
        raise ValueError(f"{'、'.join(sorted(full, key=sort_key)[:5])} 里还有东西，先移走再删")


def _delete_ids(c, ids):
    q = ",".join("?" * len(ids))
    c.execute(f"DELETE FROM inv_loc_stock WHERE loc_id IN ({q})", ids)
    c.execute(f"DELETE FROM inv_locations WHERE id IN ({q})", ids)


def delete_loc(lid, user=""):
    c = db.conn()
    r = get_loc(lid)
    if not r:
        raise ValueError("没有这个货位")
    _ensure_empty(c, [r["id"]])
    _delete_ids(c, [r["id"]])
    c.commit()
    db.audit(user, "删除货位", r["code"])


def remove(sc, layer=None, user=""):
    """删整个货架（layer 空）或货架的某一层；里面要是空的。"""
    c = db.conn()
    zone, shelf, rows = _shelf_rows(c, sc)
    if layer not in (None, ""):
        rows = [r for r in rows if r["layer"] == int(layer)]
    if not rows:
        raise ValueError("没有这些货位")
    ids = [r["id"] for r in rows]
    _ensure_empty(c, ids)
    _delete_ids(c, ids)
    code = shelf_code(zone, shelf)
    if layer in (None, ""):
        c.execute("DELETE FROM inv_loc_groups WHERE code=?", (code,))
    c.commit()
    db.audit(user, "删除货架" if layer in (None, "") else "删除货架的一层", code, "" if layer in (None, "") else f"第 {layer} 层")
    return len(ids)


# ---------------- 按货位的数量 ----------------
def _rows(c, item_id):
    rows = [dict(r) for r in c.execute(
        "SELECT s.loc_id, s.qty, l.code FROM inv_loc_stock s JOIN inv_locations l ON l.id=s.loc_id "
        "WHERE s.item_id=? AND s.qty>0", (item_id,))]
    return sorted(rows, key=lambda r: sort_key(r["code"]))


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


def _empties(c):
    rows = [dict(r) for r in c.execute(
        "SELECT l.id, l.code, l.zone, l.shelf FROM inv_locations l WHERE l.active=1 AND NOT EXISTS "
        "(SELECT 1 FROM inv_loc_stock s WHERE s.loc_id=l.id AND s.qty>0)")]
    return sorted(rows, key=lambda r: sort_key(r["code"]))


def _in_area(r, area):
    """area 是区（A）或货架（A1）"""
    return (r["zone"] == area) if ZONE_RE.match(area) else (r["shelf"] is not None and shelf_code(r["zone"], r["shelf"]) == area)


def _cats_of(r, gs):
    """这个位放哪些分类：货架设了就按货架，没设按区；都没设 = 不限。"""
    sc = shelf_code(r["zone"], r["shelf"]) if r.get("shelf") is not None else None
    if sc and (gs.get(sc) or {}).get("categories"):
        return gs[sc]["categories"]
    return (gs.get(r.get("zone") or "") or {}).get("categories") or []


def suggest(it, cfg=None):
    """推荐货位（见文件开头）。返回 {id, code, why} 或 None（没有合适的空位：留在「未上架」，人工放）。
    不会把东西自动放到「指定了别的分类」的货架上。"""
    c = db.conn()
    rows = _rows(c, it["id"])
    if rows:
        best = max(rows, key=lambda r: r["qty"])
        return {"id": best["loc_id"], "code": best["code"], "why": "已经放在这里"}
    empties = _empties(c)
    pref = str(it.get("location") or "").strip().upper()
    if pref:
        loc = get_loc(pref)
        if loc and loc["active"]:
            return {"id": loc["id"], "code": loc["code"], "why": "物品资料里的默认货位"}
        if ZONE_RE.match(pref) or SHELF_RE.match(pref):
            e = next((r for r in empties if _in_area(r, pref)), None)
            if e:
                return {"id": e["id"], "code": e["code"], "why": f"物品资料里的默认位置 {pref} 的空位"}
    cat = it.get("category")
    gs = groups()
    for r in empties:
        if cat in _cats_of(r, gs):
            area = shelf_code(r["zone"], r["shelf"]) if r.get("shelf") is not None else r["zone"]
            return {"id": r["id"], "code": r["code"], "why": f"{area} 放这个分类，空位"}
    e = next((r for r in empties if not _cats_of(r, gs)), None)
    return {"id": e["id"], "code": e["code"], "why": "空的货位"} if e else None


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
    for r in sorted(rows, key=lambda r: (r["qty"], sort_key(r["code"]))):
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
    for r in db.conn().execute("SELECT * FROM inv_items WHERE active=1 AND qty>0").fetchall():
        it = ledger.item_row(r)
        un = item_locations(it["id"])["unplaced"]
        if un <= EPS:
            continue
        s = suggest(it)
        if not s:
            continue                            # 没有合适的空位：留在「未上架」
        move(it["id"], 0, s["id"], un, user)
        out.append({"item_id": it["id"], "code": s["code"], "qty": un})
    return out


def unplaced():
    """有「未上架」数量的物品 + 推荐货位。"""
    from core.inventory import ledger
    out = []
    cfg = load_config()
    for r in db.conn().execute("SELECT * FROM inv_items WHERE active=1 AND qty>0 ORDER BY category, code").fetchall():
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
    loc["human_zh"], loc["human_th"] = human(loc["code"]), human(loc["code"], "th")
    return {"location": loc, "items": items, "log": log}


def find(code):
    """扫码 / 输入：货位编号 → 货位；货架编号（A1）→ 货架；物品编码 / SKU → 放在哪些货位。"""
    s = str(code or "").strip().upper()
    if not s:
        raise ValueError("先扫码或输入编号")
    loc = get_loc(s) if not s.isdigit() else None
    if loc:
        return {"type": "location", **loc_detail(loc["id"])}
    c = db.conn()
    if SHELF_RE.match(s) or ZONE_RE.match(s):
        if any(_in_area(dict(r), s) for r in c.execute("SELECT zone, shelf FROM inv_locations")):
            return {"type": "shelf" if SHELF_RE.match(s) else "zone", "code": s}
    r = c.execute("SELECT * FROM inv_items WHERE UPPER(code)=?", (s,)).fetchone()
    if r:
        from core.inventory import ledger
        return {"type": "item", "item": ledger.item_row(r), **item_locations(r["id"])}
    raise ValueError(f"没找到 {s}：不是货位、货架，也不是物品编码")


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


# ---------------- 标签 ----------------
_LABEL_CSS = """@page {{ size: {w}mm {h}mm; margin: 0 }} body {{ margin: 0 }}
.lb {{ width: {w}mm; height: {h}mm; box-sizing: border-box; padding: 1.5mm 2mm; page-break-after: always;
      font-family: 'Leelawadee UI', Tahoma, 'Microsoft YaHei', sans-serif; display: flex; flex-direction: column; overflow: hidden }}
.code {{ font: bold {fs}pt monospace; text-align: center; letter-spacing: 1px; line-height: 1.1 }}
.bc {{ height: {bh}mm }} .bc svg {{ height: 100% }}
.nt {{ font-size: 7.5pt; text-align: center; white-space: nowrap; overflow: hidden }}
@media screen {{ body {{ background: #ddd }} .lb {{ background: #fff; margin: 6px auto }} }}"""


def _page(title, cards, w=50, h=30, fs=15, bh=12):
    css = _LABEL_CSS.format(w=w, h=h, fs=fs, bh=bh)
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title><style>{css}</style></head>"
            f"<body>{cards}<script>setTimeout(() => print(), 300)</script></body></html>")


def labels_html(locs, lang="zh"):
    """货位标签：每个货位一张（50×30 毫米），Code128 条码 = 货位编号，下面一行写「A区 1号货架 第2层 第3位」。"""
    from html import escape as h
    from core import labels
    cards = "".join(f"""<div class="lb"><div class="code">{h(l['code'])}</div><div class="bc">{labels.code128_svg(l['code'], height=40, module=2)}</div>
<div class="nt">{h(human(l['code'], lang))}{(' · ' + h(l['note'])) if l.get('note') else ''}</div></div>""" for l in locs) or "<p>没有货位</p>"
    return _page("货位标签", cards)


def shelf_labels_html(codes, lang="zh"):
    """货架牌：每个货架一张（50×30 毫米），大字写货架编号 + 名字 + 放什么。"""
    from html import escape as h
    from core import labels
    from core.inventory import ledger
    gs = groups()
    cat = {x["id"]: (x["th"] if lang == "th" else x["zh"]) for x in ledger.categories()}
    cards = []
    for sc in codes:
        g = gs.get(sc) or {}
        m = SHELF_RE.match(sc)
        title = (f"โซน {m.group(1)} แร็ค {m.group(2)}" if lang == "th" else f"{m.group(1)}区 {m.group(2)}号货架") if m else sc
        what = "、".join(cat.get(x, x) for x in g.get("categories") or [])
        cards.append(f"""<div class="lb"><div class="code" style="font-size:26pt">{h(sc)}</div><div class="bc" style="height:8mm">{labels.code128_svg(sc, height=30, module=2)}</div>
<div class="nt">{h(title)}{(' · ' + h(g['name'])) if g.get('name') else ''}</div><div class="nt">{h(what)}</div></div>""")
    return _page("货架牌", "".join(cards) or "<p>没有货架</p>")
