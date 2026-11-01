"""采购模块给别的模块用的接口（modules.public("pur")，采购模块关着时拿到 None）。

  draft_po(lines, user, note)   lines = [{item_id, qty, unit_cost}]：按物品的默认供应商分组，每个供应商一张采购单草稿，返回采购单列表（v2.54，成品备货的外购补货）
  in_transit(item_id)           这个物品在途（已下单、还没到）的数量
"""
from core.inventory import purchase as _kp


def draft_po(lines, user="", note=""):
    from core import db
    groups = {}
    c = db.conn()
    for ln in lines or []:
        r = c.execute("SELECT supplier_id FROM inv_items WHERE id=?", (int(ln["item_id"]),)).fetchone()
        groups.setdefault(r["supplier_id"] if r else None, []).append(
            {"item_id": int(ln["item_id"]), "qty": float(ln["qty"]), "unit_cost": ln.get("unit_cost") or None})
    return [_kp.save_po({"supplier_id": sup, "lines": ls, "note": note or "成品备货补货（外购）"}, user) for sup, ls in groups.items()]


def in_transit(item_id):
    return _kp.in_transit().get(int(item_id), 0)
