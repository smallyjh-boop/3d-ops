"""库存模块收听的事件（core/chain.py 发出）。"""

SHIP_FROM = ("to_ship", "quote", "unpaid")
SHIPPED = ("shipped", "completed")
# v2.40 复审：平台中间状态（ON_HOLD 等认不出的 = other）生产照常、库存照样占着 → 从这里发货也要开出库单
SHIP_OUT_FROM = SHIP_FROM + ("other",)


def on_order_status(oid, new, old=None, user=""):
    """待发货 → 已发货：开「订单出库」单（成品、纸箱、包材，v2.35，modules/inv/shipout.py）；
    已发货 → 又改回待发货：出库单作废（数量冲回）。"""
    from . import shipout
    if new in SHIPPED and old in SHIP_OUT_FROM:
        return shipout.ship_order(oid, user)
    if new in SHIP_FROM and old in SHIPPED:
        return shipout.revert(oid, user)
    if new in SHIP_FROM and old in ("returned", "delivery_failed"):
        # v2.41：退货 / 拒收后重新发：东西已经由售后验货退回库存，原来的出库单不作废，只是允许再出一次库
        return shipout.allow_again(oid, user)
    return None
