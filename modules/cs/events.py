"""客服模块订阅的事件（v2.46）。"""


def on_order_status(oid, new, old=None, user=""):
    """订单变成已发货：排一个「主动告诉买家」的任务（有会话的订单才会真的发 / 出草稿）。"""
    if new != "shipped" or old == "shipped":
        return None
    try:
        from .logic import jobs
        return jobs.enqueue("notify", None, {"order_id": oid, "what": "shipped"}, delay=5)
    except Exception:  # noqa: BLE001  客服出问题不影响发货
        return None
