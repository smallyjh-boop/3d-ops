"""库存模块给别的模块用的接口（modules.public("inv")，库存模块关着时拿到 None）。

  on_post(c, item_id, qty, kind, user)   ledger.post 每记一笔流水都会调（新物品第一次入库自动放货位）
  where_is(物品编码)                      → [(货位编号, 数量)]（拣货单、面单信息区按货位排）
  sort_key(货位编号)                      货位排序（A2 在 A10 前面）
  human(货位编号, lang)                   A1-02-03 → A区 1号货架 第2层 第3位
  order_out(订单id)                       这个订单的出库单（发货时扣的成品、纸箱、包材），没有返回 None
  assign(物品id, 货位编号, user)            把物品放到货位（v2.51 采购到货时顺便放）
  suggest_loc(分类)                       给这个分类的物品推荐一个空格（没有返回 None）
"""
from . import locations


def on_post(c, item_id, qty, kind, user=""):
    return locations.on_post(c, item_id, qty, kind, user)


def where_is(code):
    return locations.where_is(code)


def sort_key(code):
    return locations.sort_key(code)


def human(code, lang="zh"):
    return locations.human(code, lang)


def order_out(order_id):
    from . import shipout
    return shipout.summary(order_id)


def assign(item_id, code, user=""):
    return locations.assign(item_id, code, user)


def suggest_loc(category):
    return locations.suggest(category)
