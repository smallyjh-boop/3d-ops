CALLS = []


def on_shipped(order_id=None, **kw):
    CALLS.append(("demo", order_id))
    return "ok"


def startup():
    CALLS.append(("startup",))


MODULE = {
    "id": "demo", "name_zh": "演示模块", "name_th": "โมดูลสาธิต", "version": "0.1", "desc_zh": "测试用",
    "menus": [{"tab": "demo_page", "mod": "sys", "zh": "演示页面", "th": "หน้าสาธิต", "roles": "owner,listing"}],
    "owner_only": [("POST", r"^/api/m/demo/secret$")],
    "settings": [("演示设置", [("demo_x", "演示数字")])], "settings_module": "general", "settings_card": True,
    "config_defaults": {"demo_x": 5, "demo_key": ""}, "secrets": ["demo_key"],
    "events": {"order.shipped": on_shipped}, "startup": startup,
}
