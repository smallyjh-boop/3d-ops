"""库存管理（v2.17）—— 独立模块。耗材、备件、包材、工具……都是「物品」，按分类区分；数量只能通过单据 / 流水改变。

★ 别的模块只用这里列出的接口，不要直接读写 inv_* 表（以后改算法、加多仓 / 称重 / 扫码时，外面不用动）：

  物品    categories()  items(category, q, low_only, include_inactive)  get_item(id或编码)  save_item(dict, user)
  单据    create_doc(kind, lines, note, user, printer)   kind = purchase 采购入库 / return 退回入库 / issue 领用 / scrap 报废 / adjust 调整
          void_doc(id, user)  docs(kind, days)  doc(id)
  盘点    stocktake_start(category, user)  stocktake_save(id, {行id: 实盘数}, user)  stocktake_confirm(id, user)
  流水    moves(item_id, kind, days, limit, doc_id)
  统计    expense(start, end, group)  alerts()  overview()
  采购    suppliers() save_supplier()  save_po(dict) get_po(id) list_po(status) po_action(id, order/cancel/close/tracking)
          receive_po(id, {行id: 数量}) pay_po(id, 金额, 方式, 日期) in_transit() suggest() po_from_suggest(物品ids)
          po_summary()  （采购模块概况，v2.21）
  财务    finance_events(since) finance_month(YYYY-MM)       （给财务模块：采购付款 / 到货等事件、按月汇总）
  发货    pack_order(order_id)                              （订单发货时自动扣包材，按设置的规则）
  耗材    filament_available() → {(材料, 颜色代码): 克}      （自动库存、随机颜色选料用）
          consume_production(material, color, grams, reason, user, printer, ref, failed=False)
                                                           （打印完成 / 失败扣料：产品克数 + 损耗率；失败整盘记损耗）

耗材的料卷（哪卷在哪台机、开封烘干）仍在 core/materials，只是辅助记录；数量变化都会同步记到这里的流水。
"""
from . import docs as _docs
from . import filament as _fil
from . import finance as _finance
from . import goods as _goods
from . import packing as _pack
from . import presets as _presets
from . import purchase as _po
from . import ledger as _led
from . import report as _rep
from .. import db

CATEGORIES = _led.CATEGORIES
KINDS = _led.KINDS
DOC_KINDS = _docs.DOC_KINDS
UNITS = _led.UNITS


def init():
    _led.init()
    _po.init()
    _finance.init()
    _pack.init()
    for name, fn in (("耗材", _fil.migrate), ("成品", _goods.migrate), ("常用物品", _presets.seed_once)):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("3dops").warning("%s转入库存管理失败：%s", name, e)


categories = _led.categories
get_item = _led.get_item
save_item = _led.save_item
moves = _led.moves
create_doc = _docs.create
void_doc = _docs.void
doc = _docs.get
docs = _docs.list_docs
stocktake_start = _docs.stocktake_start
stocktake_save = _docs.stocktake_save
stocktake_confirm = _docs.stocktake_confirm
expense = _rep.expense
alerts = _rep.alerts
overview = _rep.overview
filament_available = _fil.available
suppliers = _po.suppliers
save_supplier = _po.save_supplier
save_po = _po.save_po
get_po = _po.get_po
list_po = _po.list_po
po_action = _po.set_status
receive_po = _po.receive
pay_po = _po.pay
in_transit = _po.in_transit
suggest = _po.suggest
po_from_suggest = _po.po_from_suggest
po_summary = _po.summary
PO_STATUS = _po.STATUS
PAY_METHODS = _po.METHODS
finance_events = _finance.events
finance_month = _finance.month_summary
pack_order = _pack.pack_order
seed_presets = _presets.seed
consume_production = _fil.consume_production


def items(category="", q="", low_only=False, include_inactive=False):
    sql, args = "SELECT * FROM inv_items", []
    conds = []
    if category:
        conds.append("category=?"); args.append(category)
    if not include_inactive:
        conds.append("active=1")
    if q:
        conds.append("(code LIKE ? OR name_zh LIKE ? OR name_th LIKE ? OR brand LIKE ? OR spec LIKE ?)")
        args += [f"%{q}%"] * 5
    if low_only:
        conds.append("reorder_point IS NOT NULL AND qty<=reorder_point")
    sql += (" WHERE " + " AND ".join(conds) if conds else "") + " ORDER BY category, code"
    tr = _po.in_transit()
    out = []
    for r in db.conn().execute(sql, args):
        it = _led.item_row(r)
        it["transit"] = tr.get(it["id"], 0)
        out.append(it)
    return out
