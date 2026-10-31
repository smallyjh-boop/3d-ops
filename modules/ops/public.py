"""运营分析模块给别的模块用的（modules.public("ops")，模块关着时拿到 None）。"""


def dashboard():
    """运营看板的全部数字（和 /api/oa/dashboard 一样）。"""
    from . import dash
    return dash.dashboard()


def lifecycle():
    """商品生命周期：{rows:[{sku, platform, stage, stage_label, action, qty_30d, …}], counts, rules}。"""
    from . import lifecycle as lc
    return lc.board()


def lazada_fee_rates(days=30):
    """Lazada 真实扣点（财务流水算出来的）：{item_amount, deducted, rate(%), fees:[…]}。"""
    from . import lazada
    return lazada.fee_rates(days)


def notify(text):
    """发一条手机提醒（LINE / Telegram，按运营分析的设置）。返回 (成功?, 错误)。"""
    from . import alerts
    return alerts.send(text)
