"""上架导出模块给别的模块用的（modules.public("listing")，模块关着时别的模块拿到 None）。"""


def online_shops():
    """{产品编号: [{platform, shop, status}]}：这个产品在哪些店铺在线（在线商品表，v2.44）。"""
    from . import online
    online.init()
    return online.all_platforms()
