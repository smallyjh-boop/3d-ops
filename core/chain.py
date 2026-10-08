"""主链路的联动（v2.31）：商品 → 订单 → 生产 → 库存。

订单这边不直接调用生产 / 库存，只发事件；开着的模块自己接：
  order_changed(user)          订单新增 / 改了商品明细 / 审核通过 → 生产模块生成生产任务（返回生成了几个）
  reschedule()                 打印机、订单优先级变了 → 生产模块重新排单
  order_status(oid, new, old)  订单状态变了 → 库存模块（已发货扣包材）等
库存是「同一个事务里一起记」的（打印扣耗材、成品增减、耗材料卷变化），用 inv() 拿库存模块，关着返回 None 就不记。
"""
from . import modules


def _on(mid):
    return not modules.is_loaded() or modules.enabled(mid)


def order_changed(user=""):
    if not modules.is_loaded():             # 没装载模块（单独的脚本）：照旧直接生成
        from . import production
        return production.generate(user)
    r = modules.emit("order.changed", user=user)
    return sum(v for v in r.values() if isinstance(v, int))


def reschedule():
    if not modules.is_loaded():
        from . import production
        return production.schedule()
    r = modules.emit("chain.reschedule")
    return next((v for v in r.values() if not (isinstance(v, dict) and "error" in v)), None)


def order_status(oid, new, old=None, user=""):
    if not modules.is_loaded():             # 没装载模块（单独的脚本）：按「全开」，直接交给库存模块的发货出库（v2.35）
        try:
            from modules.inv import events as _inv_events
            _inv_events.on_order_status(oid, new, old, user)
        except Exception:  # noqa: BLE001  出库失败不能影响发货
            pass
        return {}
    return modules.emit("order.status", oid=oid, new=new, old=old, user=user)


def inv():
    """库存模块开着 → core.inventory；关着 → None（不记库存流水、不扣包材 / 耗材）。"""
    if not _on("inv"):
        return None
    from . import inventory
    return inventory


def prod_on():
    return _on("prod")


def resin_on():
    return _on("resin")
