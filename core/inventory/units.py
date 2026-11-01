"""耗材的两个单位：卷 + 重量（v2.55）。树脂同一套，只是「卷」叫「瓶」、重量旁边多一个毫升。

数量的唯一来源还是克（inv_items.qty，和料卷剩余克数加起来始终一致）；这里只负责「怎么数、怎么说」：
  - 卷数：从料卷（core/materials.spools）数——未开封（整卷）/ 已开封在库 / 在机上，用完的不算，记成负数的占位卷也不算
  - 每个货位上几卷、多少克（料卷的货位在 inv_spool_loc，库存模块写）
  - 补货线可以用卷或公斤：inv_items.reorder_unit（'roll' / 'kg' / 空 = 老的按克），reorder_value 是填的数；
    reorder_point 始终同步成克（老代码、SQL 照旧能用），按卷的提醒用真实卷数比，不用克数估
  - 每卷净重 inv_items.roll_g（空 = 设置里的 filament_spool_kg）
文字（中 / 泰）也在这里一处生成，界面、测试、提醒用同一份。
"""
import math

from .. import db
from ..config import load_config

REORDER_UNITS = ("roll", "kg")


# ---------------- 词 ----------------
def is_resin(material):
    m = (material or "").upper()
    return m.startswith("RESIN") or "树脂" in m or "เรซิ่น" in m


def words(material):
    """{roll: (中, 泰), full, open, loaded}：卷 / 瓶。"""
    if is_resin(material):
        return {"roll": ("瓶", "ขวด"), "full": ("整瓶", "ขวดเต็ม"), "open": ("开封瓶", "ขวดเปิดแล้ว"), "loaded": ("在机上", "อยู่บนเครื่อง"),
                "kind": "bottle"}
    return {"roll": ("卷", "ม้วน"), "full": ("整卷", "ม้วนเต็ม"), "open": ("开封卷", "ม้วนเปิดแล้ว"), "loaded": ("在机上", "อยู่บนเครื่อง"),
            "kind": "roll"}


def n_str(v, d=0):
    v = round(float(v), d)
    return f"{v:,.{d}f}" if d else f"{int(v):,}"


def trim(v, d=2):
    """1.90 → 1.9，2.0 → 2，1.97 → 1.97"""
    s = f"{float(v):.{d}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def fmt_g(g):
    """克数怎么说：>= 1 公斤用 kg（最多两位小数，至少一位：1.0 / 1.97 / 1.5），不到 1 公斤用 g。"""
    g = float(g or 0)
    if abs(g) >= 1000:
        s = f"{g / 1000:.2f}"
        if s.endswith("0"):
            s = s[:-1]
        return f"{s} kg"
    return f"{round(g):,} g"


def density(cfg=None):
    try:
        d = float((cfg or load_config()).get("resin_density") or 1.1)
        return d if d > 0 else 1.1
    except (TypeError, ValueError):
        return 1.1


def default_roll_g(cfg=None):
    try:
        return float((cfg or load_config()).get("filament_spool_kg") or 1.0) * 1000
    except (TypeError, ValueError):
        return 1000.0


def roll_g_of(it, cfg=None):
    """这个物品每卷（瓶）净重多少克：物品自己填的 → 设置里的默认。"""
    try:
        v = float(it.get("roll_g") or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v > 0 else default_roll_g(cfg)


def tare_g(cfg=None):
    try:
        return max(0.0, float((cfg or load_config()).get("inv_spool_tare_g") or 0))
    except (TypeError, ValueError):
        return 0.0


# ---------------- 数卷 ----------------
def _live(r):
    """算不算一卷：没用完，并且（整卷 或 还有料）。"""
    return r["status"] != "empty" and (r["status"] == "sealed" or (r["remaining_g"] or 0) > 0)


def spool_stats(c=None):
    """{(材料, 颜色): {sealed, open, loaded, rolls, grams}}（一次查完，列表里每个物品用）。"""
    c = c or db.conn()
    out = {}
    try:
        rows = c.execute("SELECT material, color, status, remaining_g FROM spools WHERE status!='empty'").fetchall()
    except Exception:  # noqa: BLE001  老库没有料卷表
        return out
    for r in rows:
        if not _live(r):
            continue
        d = out.setdefault((r["material"], r["color"]), {"sealed": 0, "open": 0, "loaded": 0, "rolls": 0, "grams": 0.0})
        d[r["status"] if r["status"] in ("sealed", "open", "loaded") else "open"] += 1
        d["rolls"] += 1
        d["grams"] += max(0.0, float(r["remaining_g"] or 0))
    return out


def stock_text(material, st, cfg=None):
    """「2 卷（1 整卷 + 1 开封卷）· 1.97 kg」，返回 (中文, 泰文)。"""
    w = words(material)
    n = st["rolls"]
    parts_zh, parts_th = [], []
    for key in ("sealed", "open", "loaded"):
        if st.get(key):
            wk = {"sealed": "full", "open": "open", "loaded": "loaded"}[key]
            parts_zh.append(f"{st[key]} {w[wk][0]}" if key != "loaded" else f"{st[key]} {w['loaded'][0]}")
            parts_th.append(f"{st[key]} {w[wk][1]}" if key != "loaded" else f"{st[key]} {w['loaded'][1]}")
    ml = f" ≈ {n_str(st['grams'] / density(cfg))} ml" if w["kind"] == "bottle" and st["grams"] > 0 else ""
    zh = f"{n} {w['roll'][0]}" + (f"（{' + '.join(parts_zh)}）· " if n and parts_zh else " · ") + f"{fmt_g(st['grams'])}{ml}"
    th = f"{n} {w['roll'][1]}" + (f" ({' + '.join(parts_th)})" if n and parts_th else "") + f" · {fmt_g(st['grams'])}{ml}"
    return zh, th


def for_item(it, stats=None, cfg=None):
    """耗材物品的两个单位：{kind, rolls, sealed, open, loaded, grams, kg, ml, tracked, text_zh, text_th, roll_g}。非耗材返回 None。"""
    if it.get("category") != "filament":
        return None
    stats = spool_stats() if stats is None else stats
    st = stats.get((it.get("material"), it.get("color")))
    tracked = st is not None
    if st is None:
        st = {"sealed": 0, "open": 0, "loaded": 0, "rolls": 0, "grams": max(0.0, float(it.get("qty") or 0))}
    w = words(it.get("material"))
    zh, th = stock_text(it.get("material"), st, cfg)
    return {"kind": w["kind"], "rolls": st["rolls"], "sealed": st["sealed"], "open": st["open"], "loaded": st["loaded"],
            "grams": round(st["grams"], 1), "kg": round(st["grams"] / 1000.0, 3),
            "ml": round(st["grams"] / density(cfg)) if w["kind"] == "bottle" else None,
            "tracked": tracked, "word_zh": w["roll"][0], "word_th": w["roll"][1], "roll_g": roll_g_of(it, cfg),
            "text_zh": zh, "text_th": th}


def below(it, extra_g=0.0):
    """低于补货线没有：按卷的用真实卷数（含在途折成的卷数）比，按公斤 / 按克的比重量。it 要先 decorate 过才有卷数。"""
    ru, rv, u = it.get("reorder_unit"), it.get("reorder_value"), it.get("units")
    if ru == "roll" and rv is not None and u is not None:
        return u["rolls"] + extra_g / roll_g_of(it) <= float(rv) + 1e-9
    rp = it.get("reorder_point")
    return rp is not None and float(it.get("qty") or 0) + extra_g <= float(rp) + 1e-9


def decorate(items, c=None):
    """给 inv.items() 出来的耗材行补上 units，并按补货线的单位重算 low。"""
    stats = None
    cfg = load_config()
    for it in items:
        if it.get("category") != "filament":
            continue
        if stats is None:
            stats = spool_stats(c)
        it["units"] = for_item(it, stats, cfg)
        it["low"] = bool(below(it))
        it.update(reorder_text(it))
    return items


def reorder_text(it):
    """补货线怎么说：{reorder_zh, reorder_th}（耗材按填的单位，其他不加）。"""
    rp, ru, rv = it.get("reorder_point"), it.get("reorder_unit"), it.get("reorder_value")
    if rp is None or it.get("category") != "filament":
        return {}
    w = words(it.get("material"))
    if ru == "roll" and rv is not None:
        return {"reorder_zh": f"{trim(rv, 1)} {w['roll'][0]}", "reorder_th": f"{trim(rv, 1)} {w['roll'][1]}"}
    if ru == "kg" and rv is not None:
        return {"reorder_zh": f"{trim(rv, 2)} kg", "reorder_th": f"{trim(rv, 2)} kg"}
    return {"reorder_zh": fmt_g(rp), "reorder_th": fmt_g(rp)}


def qty_text(it, qty_g, kind_word=True):
    """一个数量（克）按这个物品的补货线单位怎么说：按卷 → 「2.5 卷」（按每卷净重折），其他 → 重量。"""
    w = words(it.get("material"))
    if it.get("reorder_unit") == "roll":
        r = float(qty_g or 0) / roll_g_of(it)
        d = 0 if abs(r - round(r)) < 0.05 else 1
        return f"{n_str(r, d)} {w['roll'][0]}", f"{n_str(r, d)} {w['roll'][1]}"
    return fmt_g(qty_g), fmt_g(qty_g)


# ---------------- 补货线 ----------------
def apply_reorder(vals, d, existing=None):
    """save_item 用：把界面填的 (单位, 数) 转成克写进 reorder_point / reorder_qty，同时记下单位和数。vals 是要写库的字段，d 是请求。"""
    ex = existing or {}
    unit = ex.get("reorder_unit")
    if "reorder_unit" in d:
        unit = str(d.get("reorder_unit") or "").strip().lower()
        if unit in ("", "g", "none"):
            unit = None
        if unit not in (None, *REORDER_UNITS):
            raise ValueError("补货线的单位只能是 卷 或 公斤")
        vals["reorder_unit"] = unit
    if unit is None:
        if "reorder_unit" in d:
            vals["reorder_value"] = None
        if "reorder_unit" in d and "reorder_value" in d:        # 单位选了「克」：填的数就是克数
            vals["reorder_point"] = None if d["reorder_value"] in (None, "") else float(d["reorder_value"])
        if "reorder_qty_value" in d:
            vals["reorder_qty"] = None if d["reorder_qty_value"] in (None, "") else float(d["reorder_qty_value"])
        return
    rg = float(vals.get("roll_g") or ex.get("roll_g") or 0) or default_roll_g()

    def to_g(v, label):
        try:
            x = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{label}要填数字")
        if not math.isfinite(x) or x < 0:
            raise ValueError(f"{label}要填 0 或正数")
        return x * (1000.0 if unit == "kg" else rg), x

    if "reorder_value" in d:
        if d.get("reorder_value") in (None, ""):
            vals["reorder_value"], vals["reorder_point"] = None, None
        else:
            g, x = to_g(d["reorder_value"], "补货线")
            vals["reorder_value"], vals["reorder_point"] = x, g
    elif "reorder_unit" in d and ex.get("reorder_value") is not None:     # 只换了单位：数不变，克数按新单位重算
        g, x = to_g(ex["reorder_value"], "补货线")
        vals["reorder_point"] = g
    if "reorder_qty_value" in d:
        if d.get("reorder_qty_value") in (None, ""):
            vals["reorder_qty"] = None
        else:
            vals["reorder_qty"] = to_g(d["reorder_qty_value"], "每次补多少")[0]


# ---------------- 货位 ----------------
def loc_stats(c=None):
    """{(材料, 颜色): {货位id: {rolls, grams}}}：每个货位上几卷、多少克（来自料卷的货位）。"""
    c = c or db.conn()
    out = {}
    try:
        rows = c.execute("SELECT s.material, s.color, s.status, s.remaining_g, l.loc_id FROM spools s JOIN inv_spool_loc l ON l.spool_id=s.id "
                         "WHERE s.status!='empty' AND l.loc_id IS NOT NULL").fetchall()
    except Exception:  # noqa: BLE001  货位表还没建
        return out
    for r in rows:
        if not _live(r):
            continue
        d = out.setdefault((r["material"], r["color"]), {}).setdefault(r["loc_id"], {"rolls": 0, "grams": 0.0})
        d["rolls"] += 1
        d["grams"] += max(0.0, float(r["remaining_g"] or 0))
    return out


def loc_text(material, rolls, grams, cfg=None):
    """「1 卷 · 1.0 kg」（树脂：1 瓶 · 1.0 kg ≈ 909 ml）。"""
    w = words(material)
    ml = f" ≈ {n_str(grams / density(cfg))} ml" if w["kind"] == "bottle" and grams > 0 else ""
    return f"{rolls} {w['roll'][0]} · {fmt_g(grams)}{ml}", f"{rolls} {w['roll'][1]} · {fmt_g(grams)}{ml}"


# ---------------- 盘点 ----------------
def rolls_to_grams(it, counted_rolls, book_g, book_rolls):
    """数了几卷 → 折成克：账面克数 + (数到的卷数 − 账面卷数) × 每卷净重。"""
    return max(0.0, float(book_g) + (float(counted_rolls) - float(book_rolls)) * roll_g_of(it))
