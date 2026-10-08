CALLS = []


def on_shipped(**kw):
    CALLS.append("demo2")
    raise RuntimeError("故意出错")


MODULE = {"id": "demo2", "name_zh": "演示二", "depends": ["demo"], "events": {"order.shipped": on_shipped}, "default_on": False}
