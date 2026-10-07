"""成品（v2.18）：生产模块的成品备货（production.stock，按 SKU）并进库存管理，分类「成品」。

和耗材一样：成品数量变化都走 production.stock_add，那里调用这里的 on_change 记一笔库存流水；
库存管理对成品开单（盘点、调整、报废）时，反过来调用 production.stock_add，带上单号。
成品的单价 = 产品定价里算的单件成本（材料 + 机时 + 包材 + 损耗），只用来算库存金额，不算进「支出」。
"""
import contextlib
import threading

from .. import db
from ..config import load_config
from . import ledger

CTX = threading.local()


@contextlib.contextmanager
def context(**kw):
    prev = getattr(CTX, "v", None)
    CTX.v = {**(prev or {}), **kw}
    try:
        yield
    finally:
        CTX.v = prev


def _unit_cost(sku, product_id=None):
    try:
        from .. import pricing, store
        pid = product_id or sku.rsplit("-", 2)[0]
        p = store.load(pid)
        for v, pr in zip(p.get("variants") or [], pricing.price_product(load_config(), p)):
            if (v.get("sku") or "").upper() == sku.upper():
                return float((pr.get("cost") or {}).get("total") or 0)
    except Exception:  # noqa: BLE001
        pass
    return None


def ensure_item(c, sku, product_id=None, name="", color=""):
    sku = (sku or "").upper()
    r = c.execute("SELECT id FROM inv_items WHERE category='goods' AND code=?", (sku,)).fetchone()
    if r:
        return r["id"]
    now = ledger._now()
    nm = " ".join(x for x in (name, color) if x).strip() or sku
    uc = _unit_cost(sku, product_id) or 0
    return c.execute("INSERT INTO inv_items(code, name_zh, name_th, category, unit, spec, qty, avg_cost, active, created_at, updated_at) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (sku, nm, nm, "goods", "件", product_id or "", 0, uc, 1, now, now)).lastrowid


def _guess(reason, delta):
    r = reason or ""
    if "备货打印" in r or "多打" in r:
        return "produce"
    if "出货" in r or "发货" in r:
        return "ship"
    if "盘点" in r:
        return "adjust"
    if "退" in r or "验货" in r:
        return "return"
    return "produce" if delta > 0 else "ship"


def on_change(c, sku, delta, reason, user, product_id=None, name="", color=""):
    """production.stock_add 每次改成品数量都会调用（同一个连接，由它提交）。"""
    if not delta:
        return
    ctx = getattr(CTX, "v", None) or {}
    item_id = ensure_item(c, sku, product_id, name, color)
    kind = ctx.get("kind") or _guess(reason, delta)
    uc = ctx.get("unit_cost")
    if uc is None and kind in ("produce", "return") and delta > 0:
        uc = _unit_cost(sku, product_id)
    ledger.post(c, item_id, kind, float(delta), uc, reason, user,
                ctx.get("doc_id"), ctx.get("ref") or "")


def migrate():
    c = db.conn()
    try:
        rows = c.execute("SELECT sku, product_id, name, color, qty FROM stock").fetchall()
    except Exception:  # noqa: BLE001
        return 0
    n = 0
    for r in rows:
        item_id = ensure_item(c, r["sku"], r["product_id"], r["name"], r["color"])
        it = c.execute("SELECT qty FROM inv_items WHERE id=?", (item_id,)).fetchone()
        diff = float(r["qty"] or 0) - float(it["qty"] or 0)
        if abs(diff) > 1e-9:
            has = c.execute("SELECT 1 FROM inv_moves WHERE item_id=? LIMIT 1", (item_id,)).fetchone()
            ledger.post(c, item_id, "adjust" if has else "opening", diff, None, "和成品备货对齐" if has else "期初（从成品备货转过来）", "系统")
            n += 1
    c.commit()
    return n


def apply(it, kind, qty, unit_cost, doc_id, user, reason):
    """库存管理对成品开单：调用 production.stock_add（成品备货跟着变），流水由回调记。"""
    from .. import production
    if abs(qty - round(qty)) > 1e-9:
        raise ValueError(f"{it['code']} 是成品，数量要是整数")
    with context(kind=kind, doc_id=doc_id, unit_cost=unit_cost):
        production.stock_add(it["code"], int(round(qty)), reason, user, it.get("spec") or None, it.get("name_zh") or "")


def set_count(it, counted, doc_id, user):
    from .. import production
    with context(kind="adjust", doc_id=doc_id):
        production.stock_set(it["code"], int(round(counted)), user=user)
