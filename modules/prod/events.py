"""生产模块收听的事件（core/chain.py 发出）。"""


def on_order_changed(user=""):
    """订单新增 / 改了商品 / 审核通过：生成生产任务。返回生成了几个。"""
    from core import production
    return production.generate(user)


def on_reschedule():
    from core import production
    return production.schedule()
