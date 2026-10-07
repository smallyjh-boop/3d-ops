"""耗材和老的「耗材 / 料卷」模块（core/materials）对接。

耗材的数量以库存管理（inv_items）为准；料卷只是辅助记录（哪卷在哪台机、开封几天该烘干）。
两边怎么保持一致：materials 里每一次数量变化都会走 _logrow，那里调用这里的 on_change，记一笔库存流水。
库存管理这边对耗材开单（入库 / 领用 / 报废 / 盘点）时，反过来调用 materials 的函数，由它记流水（带上单号）。
"""
import logging

from .. import db
from ..config import load_config
from . import ledger

log = logging.getLogger("3dops")


def _key(material, color):
    return ((material or "PLA").strip().upper(), (color or "未知").strip())


def ensure_item(c, material, color):
    """找到（没有就建）这个「材料 + 颜色」的耗材物品，返回 id。"""
    m, col = _key(material, color)
    r = c.execute("SELECT id FROM inv_items WHERE category='filament' AND material=? AND color=? ORDER BY active DESC, id LIMIT 1",
                  (m, col)).fetchone()
    if r:
        return r["id"]
    from .. import codes
    hit = codes.find_color(load_config(), col)
    code = ledger._next_code(c, "filament", m, hit[1] if hit else "")
    now = ledger._now()
    cur = c.execute("INSERT INTO inv_items(code, name_zh, name_th, category, unit, material, color, color_code, qty, avg_cost, active, "
                    "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (code, f"{m} {col}", f"{m} {hit[2] if hit and hit[2] else col}", "filament", "g", m, col, hit[1] if hit else "",
                     0, ledger.default_cost(), 1, now, now))
    return cur.lastrowid


def _guess_kind(reason, delta):
    r = reason or ""
    if r.startswith("入库") or "入库" in r[:6]:
        return "purchase"
    if "打印完成" in r:
        return "production"
    if "打印失败" in r:
        return "fail"
    if any(w in r for w in ("盘点", "称重", "补差", "录错", "用完")):
        return "adjust"
    return "purchase" if delta > 0 else "issue"


def on_change(c, k, delta_kg, reason, user, ctx=None):
    """materials 每次改数量都会调用（同一个数据库连接，由 materials 提交）。"""
    if not delta_kg:
        return
    ctx = ctx or {}
    item_id = ensure_item(c, k[0], k[1])
    g = float(delta_kg) * 1000.0
    kind = ctx.get("kind") or _guess_kind(reason, g)
    ledger.post(c, item_id, kind, g, ctx.get("unit_cost"), reason, user, ctx.get("doc_id"), ctx.get("ref") or "", ctx.get("printer") or "")


def migrate():
    """第一次启动（以及以后每次启动）：把耗材模块现有的每个「材料 + 颜色」对到库存物品，数量对不上的记一笔期初 / 调整。"""
    c = db.conn()
    try:
        rows = c.execute("SELECT material, color, kg FROM inventory").fetchall()
    except Exception:  # noqa: BLE001  老库没有耗材表
        return 0
    n = 0
    for r in rows:
        item_id = ensure_item(c, r["material"], r["color"])
        it = c.execute("SELECT qty FROM inv_items WHERE id=?", (item_id,)).fetchone()
        want = float(r["kg"] or 0) * 1000.0
        diff = want - float(it["qty"] or 0)
        if abs(diff) >= 0.5:
            has = c.execute("SELECT 1 FROM inv_moves WHERE item_id=? LIMIT 1", (item_id,)).fetchone()
            ledger.post(c, item_id, "adjust" if has else "opening", diff, None,
                        "和耗材记录对齐" if has else "期初（从耗材模块转过来）", "系统")
            n += 1
    c.commit()
    return n


def available():
    """{(材料, 颜色代码或颜色名): 克数}（启用的耗材物品）。"""
    out = {}
    for r in db.conn().execute("SELECT material, color, color_code, qty FROM inv_items WHERE category='filament' AND active=1"):
        k = ((r["material"] or "PLA").upper(), r["color_code"] or (r["color"] or ""))
        out[k] = out.get(k, 0.0) + float(r["qty"] or 0)
    return out


def loss_rate(material, color, cfg=None):
    cfg = cfg or load_config()
    m, col = _key(material, color)
    r = db.conn().execute("SELECT loss_rate FROM inv_items WHERE category='filament' AND material=? AND color=? AND active=1",
                          (m, col)).fetchone()
    if r and r["loss_rate"] is not None:
        return max(0.0, float(r["loss_rate"]))
    try:
        return max(0.0, float(cfg.get("inv_loss_rate", 0.05)))
    except (TypeError, ValueError):
        return 0.05


def consume_production(material, color, grams, reason="", user="", printer=None, ref="", failed=False):
    """打印用掉的料：产品克数记「生产消耗」，再按损耗率多扣一点记「生产损耗」。失败的整盘记「打印失败损耗」。"""
    from .. import materials
    g = float(grams or 0)
    if g <= 0:
        return
    pc = materials._printer_code(printer)
    if failed:
        with materials.context(kind="fail", ref=ref, printer=pc):
            materials.consume(material, color, g, reason, user, printer=printer)
        return
    with materials.context(kind="production", ref=ref, printer=pc):
        materials.consume(material, color, g, reason, user, printer=printer)
    extra = round(g * loss_rate(material, color), 1)
    if extra >= 0.1:
        with materials.context(kind="loss", ref=ref, printer=pc):
            materials.consume(material, color, extra, (reason or "打印") + " 损耗", user, printer=printer)
