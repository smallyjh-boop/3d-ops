"""货位（v2.33 建；v2.34 编号改成「区+货架号-层-位」；v2.35 简化成「一个物品一个货位，数量只记一本账」）。

  货位编号   区字母 + 货架号 - 层 - 位，例如 A1-02-03 = A 区 1 号货架 第 2 层 第 3 位
             区 1–2 个英文字母；货架号 1–99；层、位写两位数字。输入 a1-2-3 也认（自动写成 A1-02-03）
  一物一位   每个物品只放一个货位：物品资料的「货位」（inv_items.location）。数量只记在物品上（库存就一本账），
             货架上显示「这个格子放了什么、现在还有多少」，所以入库、出库、打印扣料、发货、盘点之后自动对得上。
             物品资料里选货位，和在货架上点格子「放物品」是同一件事；换货位 = 改这个字段。一个格子可以放几样东西。
  新物品     第一次入库还没货位时（ledger.post → on_post），自动放到「放这个分类的货架」（货架没设看区）的第一个空格；
             没有合适的空格就先不放，在「没货位的物品」里人工放（不会塞进指定给别的分类的货架）
  建货架     选区、起始货架号（默认接着排）、建几个、几层、每层几位 → 一次生成；之后可以加一层 / 某层加一位 / 删空的
  层号方向   设置里选「最下面一层是第 1 层」（默认）还是「最上面是第 1 层」，只影响页面上货架的画法
  盘点       按货架 / 货位盘点：docs.stocktake_start(area=…)，只列这些格子里的物品
对外（public.py）：on_post  where_is  sort_key  area_codes
"""
import re
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
CREATE TABLE IF NOT EXISTS inv_loc_groups (
  code TEXT PRIMARY KEY, kind TEXT, name TEXT, categories TEXT, updated_at REAL
);
"""
# inv_loc_stock 是 v2.33/v2.34「按货位记数量」留下的表：v2.35 起不用了，只在迁移时读一次
CODE_RE = re.compile(r"^([A-Z]{1,2})(\d{1,2})-(\d{2})-(\d{2})$")                 # A1-02-03
LOOSE_RE = re.compile(r"^([A-Z]{1,2})\s*(\d{1,2})\s*[-_ /.]\s*(\d{1,2})\s*[-_ /.]\s*(\d{1,2})$")
OLD_RE = re.compile(r"^([A-Z]{1,2})-(\d{2})-(\d{2})$")                            # v2.33：区-货架-格
SHELF_RE = re.compile(r"^([A-Z]{1,2})(\d{1,2})$")                                 # A1
ZONE_RE = re.compile(r"^[A-Z]{1,2}$")                                             # A
MAX_LAYERS, MAX_POS, MAX_SHELVES = 20, 50, 20


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


def _now():
    return time.time()


def layer_bottom(cfg=None):
    return bool((cfg or load_config()).get("inv_loc_layer_bottom", True))


# ---------------- 建表 / 迁移 ----------------
def init():
    c = db.conn()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(inv_locations)")}
    for col in ("shelf", "layer", "pos"):
        if col not in cols:
            c.execute(f"ALTER TABLE inv_locations ADD COLUMN {col} INTEGER")
    c.commit()
    _migrate_codes(c)
    _migrate_one_place(c)


def _migrate_codes(c):
    """v2.33 → v2.34：「区-货架-格」A-01-03 → A1-01-03（原来没有层，记成第 1 层）；已经是新写法的补上 区/货架/层/位；
    设置里「分类=区」的写法搬到区的「放哪些分类」。"""
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


def _migrate_one_place(c):
    """v2.34 → v2.35：每个物品只留一个货位。物品资料里选过、而且存在的货位优先；填的是货架 / 区的，
    取这个货架里放它最多的格子（没有就第一个空格）；没填的，取原来放它最多的那个格子。只做一次。"""
    if load_config().get("inv_loc_v235"):
        return
    codes = {r["code"]: dict(r) for r in c.execute("SELECT id, code, zone, shelf FROM inv_locations WHERE active=1")}
    best = {}
    try:
        for r in c.execute("SELECT s.item_id, l.code, s.qty FROM inv_loc_stock s JOIN inv_locations l ON l.id=s.loc_id "
                           "WHERE s.qty>0 ORDER BY s.qty DESC"):
            best.setdefault(r["item_id"], []).append(r["code"])
    except Exception:  # noqa: BLE001  没有旧表
        pass
    taken = {r[0] for r in c.execute("SELECT location FROM inv_items WHERE active=1 AND location IS NOT NULL AND location!=''")}
    changed = 0
    for it in c.execute("SELECT id, location, note FROM inv_items").fetchall():
        cur = norm_code(it["location"]) if it["location"] else ""
        new = cur if cur in codes else None
        if new is None and cur and (SHELF_RE.match(cur) or ZONE_RE.match(cur)):
            inside = [x for x in best.get(it["id"], []) if _in_area(codes[x], cur)]
            empty = sorted((x for x, l in codes.items() if _in_area(l, cur) and x not in taken), key=sort_key)
            new = (inside or empty or [None])[0]
        if new is None and not cur:
            new = (best.get(it["id"]) or [None])[0]
        if new is None and cur:
            new = (best.get(it["id"]) or [None])[0]
        if (new or "") != (it["location"] or ""):
            note = it["note"] or ""
            old = (it["location"] or "").strip()
            if old and old not in codes and not (SHELF_RE.match(cur) or ZONE_RE.match(cur)) and old not in note:
                note = (note + "；" if note else "") + f"原位置：{old}"       # 以前随手写的位置，留在备注里
            c.execute("UPDATE inv_items SET location=?, note=? WHERE id=?", (new, note, it["id"]))
            changed += 1
        if new:
            taken.add(new)
    c.commit()
    save_config({"inv_loc_v235": True})
    if changed:
        db.audit("系统", "货位改成一物一位", f"{changed} 个物品", "")


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


# ---------------- 货位和里面的物品 ----------------
def _stocked_ids(c):
    return {r[0] for r in c.execute("SELECT DISTINCT item_id FROM inv_moves")}


def _item_brief(it, stocked):
    low = it["reorder_point"] is not None and (it["qty"] or 0) <= it["reorder_point"] and it["id"] in stocked
    return {"id": it["id"], "code": it["code"], "name_zh": it["name_zh"], "name_th": it["name_th"], "qty": it["qty"] or 0,
            "unit": it["unit"], "category": it["category"], "low": bool(low), "reorder_point": it["reorder_point"]}


def _assigned(c):
    """{货位编号: [物品…]}（只算启用的物品）"""
    stocked = _stocked_ids(c)
    out = {}
    for it in c.execute("SELECT * FROM inv_items WHERE active=1 AND location IS NOT NULL AND location!='' ORDER BY code"):
        out.setdefault(it["location"], []).append(_item_brief(it, stocked))
    return out


def locations(active_only=True):
    """所有货位 + 每个格子里的物品（按区 → 货架 → 层 → 位排好）。"""
    c = db.conn()
    rows = c.execute("SELECT * FROM inv_locations" + (" WHERE active=1" if active_only else "")).fetchall()
    at = _assigned(c)
    out = []
    for r in rows:
        its = at.get(r["code"], [])
        out.append(dict(r, items=len(its), top=its[:4], qty=sum(x["qty"] for x in its),
                        low=any(x["low"] for x in its)))
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


def items_at(code):
    c = db.conn()
    stocked = _stocked_ids(c)
    return [_item_brief(it, stocked) for it in c.execute(
        "SELECT * FROM inv_items WHERE active=1 AND location=? ORDER BY code", (code,))]


def loc_detail(lid):
    loc = get_loc(lid)
    if not loc:
        raise ValueError("没有这个货位")
    loc["human_zh"], loc["human_th"] = human(loc["code"]), human(loc["code"], "th")
    return {"location": loc, "items": items_at(loc["code"])}


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


def bulk_create(zone, shelf=None, layers=1, positions=1, name="", categories=None, user="", count=1):
    """建货架：zone 区字母，shelf 起始货架号（空 = 接着排），count 建几个，每个 layers 层 × positions 位
    → A1-01-01 … 。已有的格子跳过（同一个货架号再建一次 = 补上缺的层和位）。返回 {shelves, made}。"""
    zone = str(zone or "").strip().upper()
    if not ZONE_RE.match(zone):
        raise ValueError("区用 1–2 个英文字母，例如 A")
    try:
        shelf = int(shelf) if str(shelf or "").strip() else next_shelf(zone)
        layers, positions = int(layers), int(positions)
        count = int(count or 1)
    except (TypeError, ValueError):
        raise ValueError("货架号、个数、层数、每层位数要填数字")
    if not (1 <= count <= MAX_SHELVES):
        raise ValueError(f"一次最多建 {MAX_SHELVES} 个货架")
    if not (1 <= shelf and shelf + count - 1 <= 99):
        raise ValueError("货架号在 1–99 之间")
    if not (1 <= layers <= MAX_LAYERS and 1 <= positions <= MAX_POS):
        raise ValueError(f"层数 1–{MAX_LAYERS}，每层位数 1–{MAX_POS}")
    c = db.conn()
    have = {r[0] for r in c.execute("SELECT code FROM inv_locations")}
    made, shelves = [], []
    cats = _valid_cats(categories) if categories is not None else None
    for s in range(shelf, shelf + count):
        for layer in range(1, layers + 1):
            for pos in range(1, positions + 1):
                code = make_code(zone, s, layer, pos)
                if code in have:
                    continue
                _insert(c, zone, s, layer, pos)
                made.append(code)
        sc = shelf_code(zone, s)
        shelves.append(sc)
        if name or cats:
            g = _group(c, sc) or {"name": "", "categories": []}
            nm = (f"{name} {s - shelf + 1}" if count > 1 and name else name) or g["name"]
            _save_group(c, sc, nm, cats if cats is not None else g["categories"])
    c.commit()
    db.audit(user, "建货架", "、".join(shelves), f"{layers} 层 × {positions} 位，新建 {len(made)} 个货位")
    return {"shelves": shelves, "shelf": shelves[0], "made": made}


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


def _ensure_empty(c, codes):
    if not codes:
        return
    q = ",".join("?" * len(codes))
    full = sorted({r[0] for r in c.execute(f"SELECT location FROM inv_items WHERE active=1 AND location IN ({q})", list(codes))}, key=sort_key)
    if full:
        raise ValueError(f"{'、'.join(full[:5])} 里还放着东西，先把东西换到别的货位再删")


def _delete(c, rows):
    ids = [r["id"] for r in rows]
    q = ",".join("?" * len(ids))
    c.execute(f"DELETE FROM inv_locations WHERE id IN ({q})", ids)
    c.execute(f"DELETE FROM inv_loc_stock WHERE loc_id IN ({q})", ids)


def delete_loc(lid, user=""):
    c = db.conn()
    r = get_loc(lid)
    if not r:
        raise ValueError("没有这个货位")
    _ensure_empty(c, [r["code"]])
    _delete(c, [r])
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
    _ensure_empty(c, [r["code"] for r in rows])
    _delete(c, rows)
    code = shelf_code(zone, shelf)
    if layer in (None, ""):
        c.execute("DELETE FROM inv_loc_groups WHERE code=?", (code,))
    c.commit()
    db.audit(user, "删除货架" if layer in (None, "") else "删除货架的一层", code, "" if layer in (None, "") else f"第 {layer} 层")
    return len(rows)


# ---------------- 放物品 ----------------
def _in_area(r, area):
    """area 是区（A）、货架（A1）或货位（A1-02-03）"""
    if ZONE_RE.match(area):
        return r["zone"] == area
    if SHELF_RE.match(area):
        return r.get("shelf") is not None and shelf_code(r["zone"], r["shelf"]) == area
    return r.get("code") == area


def area_codes(area):
    """区 / 货架 / 货位 → 里面所有货位编号（盘点用）。"""
    a = norm_code(area)
    if not (ZONE_RE.match(a) or SHELF_RE.match(a) or CODE_RE.match(a)):
        raise ValueError("写区（A）、货架（A1）或货位（A1-02-03）")
    rows = [dict(r) for r in db.conn().execute("SELECT code, zone, shelf FROM inv_locations WHERE active=1")]
    out = sorted((r["code"] for r in rows if _in_area(r, a)), key=sort_key)
    if not out:
        raise ValueError(f"没有 {a} 这个区 / 货架 / 货位")
    return out


def assign(item_id, code, user=""):
    """把物品放到货位（code 空 = 拿下来，没有货位）。返回物品。"""
    from core.inventory import ledger
    c = db.conn()
    it = c.execute("SELECT * FROM inv_items WHERE id=?", (int(item_id),)).fetchone()
    if not it:
        raise ValueError("没有这个物品")
    code = norm_code(code) if str(code or "").strip() else ""
    if code:
        loc = get_loc(code)
        if not loc or not loc["active"]:
            raise ValueError(f"没有货位 {code}（先在「货位」里建好货架）")
        code = loc["code"]
    c.execute("UPDATE inv_items SET location=?, updated_at=? WHERE id=?", (code or None, _now(), it["id"]))
    c.commit()
    db.audit(user, "放货位" if code else "拿下货位", it["code"], code)
    return ledger.get_item(it["id"])


def _cats_of(r, gs):
    """这个格子放哪些分类：货架设了就按货架，没设按区；都没设 = 不限。"""
    sc = shelf_code(r["zone"], r["shelf"]) if r.get("shelf") is not None else None
    if sc and (gs.get(sc) or {}).get("categories"):
        return gs[sc]["categories"]
    return (gs.get(r.get("zone") or "") or {}).get("categories") or []


def suggest(category, c=None):
    """给这个分类的物品找一个空格：放这个分类的货架（货架没设看区）的第一个空格 → 没指定分类的货架的第一个空格 → None。"""
    c = c or db.conn()
    used = {r[0] for r in c.execute("SELECT location FROM inv_items WHERE active=1 AND location IS NOT NULL AND location!=''")}
    empties = sorted((dict(r) for r in c.execute("SELECT code, zone, shelf FROM inv_locations WHERE active=1") if r["code"] not in used),
                     key=lambda r: sort_key(r["code"]))
    gs = groups()
    for r in empties:
        if category in _cats_of(r, gs):
            return r["code"]
    return next((r["code"] for r in empties if not _cats_of(r, gs)), None)


def on_post(c, item_id, qty, kind, user=""):
    """每一笔库存变化之后（ledger.post，同一个事务里）：新物品第一次入库、还没货位 → 自动放一个空格（设置里可以关）。"""
    if not qty or qty <= 0:
        return
    it = c.execute("SELECT id, category, location, active FROM inv_items WHERE id=?", (item_id,)).fetchone()
    if not it or not it["active"] or it["location"]:
        return
    if not load_config().get("inv_loc_auto", True):
        return
    if not c.execute("SELECT 1 FROM inv_locations LIMIT 1").fetchone():
        return                                   # 还没建货位：不用管
    code = suggest(it["category"], c)
    if code:
        c.execute("UPDATE inv_items SET location=? WHERE id=?", (code, item_id))


def unassigned():
    """有库存、但还没有货位（或货位已经删了）的物品 + 推荐的空格。"""
    from core.inventory import ledger
    c = db.conn()
    codes = {r[0] for r in c.execute("SELECT code FROM inv_locations WHERE active=1")}
    out, taken = [], set()
    for r in c.execute("SELECT * FROM inv_items WHERE active=1 AND qty>0 ORDER BY category, code").fetchall():
        if r["location"] and r["location"] in codes:
            continue
        it = ledger.item_row(r)
        out.append({"item": it, "suggest": None})
    # 推荐：一个一个往下排，不重复推荐同一个空格
    used = {r[0] for r in c.execute("SELECT location FROM inv_items WHERE active=1 AND location IS NOT NULL AND location!=''")}
    gs = groups()
    empties = sorted((dict(r) for r in c.execute("SELECT code, zone, shelf FROM inv_locations WHERE active=1") if r["code"] not in used),
                     key=lambda r: sort_key(r["code"]))
    for x in out:
        cat = x["item"]["category"]
        pick = next((r for r in empties if r["code"] not in taken and cat in _cats_of(r, gs)), None) or \
            next((r for r in empties if r["code"] not in taken and not _cats_of(r, gs)), None)
        if pick:
            x["suggest"] = pick["code"]
            taken.add(pick["code"])
    return out


def assign_all(user=""):
    """「没货位的物品」全部按推荐放。返回 [{item_id, code}]。"""
    done = []
    for x in unassigned():
        if x["suggest"]:
            assign(x["item"]["id"], x["suggest"], user)
            done.append({"item_id": x["item"]["id"], "code": x["suggest"]})
    return done


def find(code):
    """扫码 / 输入：货位编号 → 货位；货架编号（A1）/ 区 → 货架；物品编码 / SKU → 物品和它的货位。"""
    s = str(code or "").strip().upper()
    if not s:
        raise ValueError("先扫码或输入编号")
    loc = get_loc(s) if not s.isdigit() else None
    if loc:
        return {"type": "location", **loc_detail(loc["id"])}
    c = db.conn()
    if SHELF_RE.match(s) or ZONE_RE.match(s):
        if any(_in_area(dict(r), s) for r in c.execute("SELECT code, zone, shelf FROM inv_locations")):
            return {"type": "shelf" if SHELF_RE.match(s) else "zone", "code": s}
    r = c.execute("SELECT * FROM inv_items WHERE UPPER(code)=?", (s,)).fetchone()
    if r:
        from core.inventory import ledger
        it = ledger.item_row(r)
        loc = get_loc(it["location"]) if it.get("location") else None
        return {"type": "item", "item": it, "location": loc}
    raise ValueError(f"没找到 {s}：不是货位、货架，也不是物品编码")


def where_is(code):
    """物品编码（成品就是 SKU）→ [(货位编号, 现在的数量)]（一物一位，最多一个）。拣货单、面单信息区用。"""
    r = db.conn().execute("SELECT location, qty FROM inv_items WHERE code=? AND active=1", (str(code or "").upper(),)).fetchone()
    return [(r["location"], r["qty"] or 0)] if r and r["location"] else []


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
