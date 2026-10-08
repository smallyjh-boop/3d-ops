"""库存模块收听的事件（core/chain.py 发出）。"""

SHIP_FROM = ("to_ship", "quote", "unpaid")


def on_order_status(oid, new, old=None, user=""):
    """待发货 → 已发货：按设置自动扣包材（规则在 设置 → 库存与采购）。"""
    if new in ("shipped", "completed") and old in SHIP_FROM:
        from core.inventory import packing
        return packing.pack_order(oid, user)
    return None
