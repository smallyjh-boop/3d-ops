"""订单用哪个纸箱（v2.35）：纸箱统一用泰国邮政标准规格（core/inventory/boxes.py）。

  产品     编辑产品时选一种纸箱（product["pack_box"]：规格 / "none" 不用纸箱 / 空 没设）
  订单     默认用订单里各产品纸箱中最大的一个；打包页 / 订单详情里可以改（orders.pack_box：规格 / "none" / 空 = 自动）
  出库     订单发货时库存模块按这里的结果扣纸箱（modules/inv/shipout.py）
对外（modules.public("orders")）：box_for(order) → {code, auto, suggest, label}  set_box(oid, code, user)
"""
from core import db, store
from core.inventory import boxes


def _product_box(pid, cache):
    if not pid:
        return ""
    if pid not in cache:
        try:
            cache[pid] = str(store.load(pid).get("pack_box") or "").strip()
        except Exception:  # noqa: BLE001  产品删了
            cache[pid] = ""
    return cache[pid]


def suggest(order):
    """按订单里的产品自动选：各产品纸箱里最大的；都设了「不用纸箱」→ none；都没设 → 空。"""
    cache = {}
    picks = [_product_box(it.get("product_id"), cache) for it in order.get("items") or []]
    real = [p for p in picks if p and p != boxes.NONE]
    if real:
        return boxes.biggest(real)
    if picks and all(p == boxes.NONE for p in picks):
        return boxes.NONE
    return ""


def box_for(order):
    """这个订单用的纸箱：{code, auto（是不是自动选的）, suggest, label_zh, label_th}。"""
    chosen = str(order.get("pack_box") or "").strip()
    sug = suggest(order)
    code = chosen or sug
    b = boxes.get(code) if code and code != boxes.NONE else None
    return {"code": code, "auto": not chosen, "suggest": sug,
            "label_zh": b["zh"] if b else ("不用纸箱" if code == boxes.NONE else "没设纸箱"),
            "label_th": b["th"] if b else ("ไม่ใช้กล่อง" if code == boxes.NONE else "ยังไม่ได้ตั้งกล่อง")}


def set_box(oid, code, user=""):
    """打包时改纸箱：code = 规格 / "none" 不用纸箱 / "" 按产品自动。"""
    from core import orders
    code = str(code or "").strip()
    if code and code != boxes.NONE:
        b = boxes.get(code)
        if not b:
            raise ValueError("纸箱规格不对（要用邮政标准纸箱：00、0、A、2A、B……）")
        code = b["code"]
    c = db.conn()
    if not c.execute("SELECT 1 FROM orders WHERE id=?", (int(oid),)).fetchone():
        raise ValueError("订单不存在")
    c.execute("UPDATE orders SET pack_box=? WHERE id=?", (code or None, int(oid)))
    orders.log(int(oid), user, "改纸箱", code or "按产品自动", commit=False)
    c.commit()
    return box_for(orders.get_order(int(oid)))
