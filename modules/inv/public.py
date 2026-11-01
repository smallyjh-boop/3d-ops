"""库存模块给别的模块用的接口（modules.public("inv")，库存模块关着时拿到 None）。

  on_post(c, item_id, qty, kind, user)   ledger.post 每记一笔流水都会调（入库上架 / 出库从货位上扣）
  where_is(物品编码)                      → [(货位编号, 这个货位的数量)]，拣货区在前、按走路顺序（拣货单、面单信息区、产品 360）
  sort_key(货位编号)                      货位排序 = 拣货走路顺序（区 → 货架 → 层 → 位，A2 在 A10 前面）
  human(货位编号, lang)                   A1-02-03 → A区 1号货架 第2层 第3位
  zone_of(货位编号)                       → {zone 区字母, ztype 区类型, name, warehouse_name}（v2.52：拣货单按区分组）
  ztype_name(类型, lang)                  pick → 拣货区
  pick_route([(sku, 数量)])               → [{zone, ztype, name, rows:[{sku, qty, code, where}]}]（v2.52，按区分组、按走路顺序）
  order_out(订单id)                       这个订单的出库单（发货时扣的成品、纸箱、包材），没有返回 None
  assign(物品id, 货位编号, user)            换主货位（主货位上的东西一起搬过去）
  suggest_loc(分类)                       给这个分类的新物品推荐一个空位（没有返回 None）
  putaway_suggest(物品id, 数量)            上架推荐 [{code, qty, reason}]（v2.52，采购到货页显示）
  putaway_batch({物品id: 货位}, user)      with 用：这一批入库按填的货位上架，没填的按推荐（v2.52，采购到货）
  on_spool(料卷id, 操作, user)             料卷上机 / 下机 / 用完之后，货位跟着变（v2.53，core/materials 调）
  spool_locs()                            {料卷 id: 货位}（v2.53，料卷列表）
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


def zone_of(code):
    from . import wms
    p = locations.parse(code)
    z = wms.zone_of(code)
    return {"zone": p[0] if p else "", "ztype": z["ztype"], "name": z.get("name", ""), "warehouse_name": z.get("warehouse_name", "")}


def ztype_name(ztype, lang="zh"):
    from . import wms
    t = wms.ZTYPES.get(ztype)
    return (t[1] if lang == "th" else t[0]) if t else ""


def pick_route(skus):
    from . import wms
    return wms.pick_route(skus)


def order_out(order_id):
    from . import shipout
    return shipout.summary(order_id)


def assign(item_id, code, user=""):
    return locations.assign(item_id, code, user)


def suggest_loc(category):
    return locations.suggest(category)


def putaway_suggest(item_id, qty=None):
    from . import wms
    try:
        return wms.recommend(item_id, qty)
    except ValueError:
        return []


def putaway_batch(targets=None, user=""):
    from . import wms
    return wms.putaway_batch(targets, user)


def on_spool(spool_id, action="", user=""):
    from . import flows
    return flows.on_spool(spool_id, action, user)


def spool_locs():
    from . import flows
    return flows.spool_locs()
