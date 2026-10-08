"""库存模块收听的事件（core/chain.py 发出）。"""

SHIP_FROM = ("to_ship", "quote", "unpaid")
SHIPPED = ("shipped", "completed")


def on_order_status(oid, new, old=None, user=""):
    """待发货 → 已发货：开「订单出库」单（成品、纸箱、包材，v2.35，modules/inv/shipout.py）；
    已发货 → 又改回待发货：出库单作废（数量冲回）。"""
    from . import shipout
    if new in SHIPPED and old in SHIP_FROM:
        return shipout.ship_order(oid, user)
    if new in SHIP_FROM and old in SHIPPED:
        return shipout.revert(oid, user)
    return None
