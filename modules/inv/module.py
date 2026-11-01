"""仓库（原「库存」）：库存管理（物品、采购入库 / 领用 / 报废 / 调整单据、流水、库存报表）、货位（仓库 → 库区 → 货架 → 层 → 位，
上架推荐、拣货路线、库内补货、移库、货位图）、按货位盘点、发货自动扣包材、打印扣耗材和成品增减同步记流水、给财务的事件接口。
数据在 core/inventory/。接订单模块的事件 order.status（已发货 → 扣包材）。关掉后：不再记库存流水、不扣包材 / 备件，耗材料卷照常（生产模块）。"""
from . import events, public


def _todo(add):
    from . import todo
    todo.provide(add)


MODULE = {
    "id": "inv",
    "name_zh": "仓库",
    "name_th": "คลังสินค้า",
    "version": "2.1",
    "desc_zh": "库存管理（物品、单据、流水）、货位（仓库 → 库区 → 货架，上架推荐、拣货路线、补货、移库、货位图）、按货位盘点、发货自动扣包材、打印扣耗材和成品同步记流水。",
    "desc_th": "จัดการสต็อก (สิ่งของ เอกสาร ความเคลื่อนไหว) ตำแหน่งจัดเก็บ (คลัง → โซน → ชั้นวาง แนะนำการจัดเก็บ เส้นทางหยิบ เติมสินค้า ย้ายตำแหน่ง แผนผัง) "
               "ตรวจนับตามตำแหน่ง ตัดวัสดุแพ็กอัตโนมัติเมื่อส่งของ บันทึกการใช้ฟิลาเมนต์และสินค้าสำเร็จรูป",
    "depends": [],
    "order": 6,
    # v2.52：顶部菜单「库存」改名「仓库」，三个页面：库存 · 货位 · 盘点（盘点从库存页里搬出来）。
    # 旧的页面 id（locations / stocktake，以前是库存页里的页签）留成看不见的菜单，跳到新页面。
    "menus": [
        {"tab": "inventory", "mod": "inv", "zh": "库存", "th": "สต็อก", "roles": "owner,production,listing", "before": "materials"},
        {"tab": "inv_locations", "mod": "inv", "zh": "货位", "th": "ตำแหน่งจัดเก็บ", "roles": "owner,production,listing", "after": "inventory"},
        {"tab": "inv_stocktake", "mod": "inv", "zh": "盘点", "th": "ตรวจนับ", "roles": "owner,production,listing", "after": "inv_locations"},
        {"tab": "locations", "mod": "inv", "zh": "货位", "th": "ตำแหน่งจัดเก็บ", "roles": "owner,production,listing", "ghost": True,
         "panel": "inv_locations", "parent": "inv_locations"},
        {"tab": "stocktake", "mod": "inv", "zh": "盘点", "th": "ตรวจนับ", "roles": "owner,production,listing", "ghost": True,
         "panel": "inv_stocktake", "parent": "inv_stocktake"},
        # v2.53：「耗材料卷」「成品备货」变成「库存」页里的页签（页面还在生产模块：materials / stock，旧链接照样打开）
    ],
    "events": {"order.status": events.on_order_status, "printers.changed": events.on_printers_changed},
    "public": public,             # 别的模块用：where_is / sort_key / order_out / putaway_batch / pick_route；ledger.post → on_post
    "todo": _todo,                # v2.52：补货任务、待上架
    "production_allow": [("POST", r"^/api/inv/locations(/(assign|assign-all|bulk|add|group|props))?$"), ("GET", r"^/print/inv-locations$"),
                         ("POST", r"^/api/inv/wms/(putaway|move|tasks/\d+/(do|cancel))$"), ("POST", r"^/api/inv/warehouses$"),
                         # v2.53：料卷上架 / 上机 / 下机 / 称重、质检、退货、次品
                         ("POST", r"^/api/inv/spools/[^/]+/(put|load|unload|weigh)$"), ("POST", r"^/api/inv/spools/count$"),
                         ("POST", r"^/api/inv/(qc|returns|defect)/(pass|fail|act|receive)$"),
                         # v2.54：成品备货（加 SKU、改目标、一键补货——接口里再核对一次角色）
                         ("POST", r"^/api/inv/gs/(add|target|src|remove|plan|replenish)$"), ("GET", r"^/print/gs-labels$")],
    "settings_module": "inventory",
    "settings": [("货位", [
        ("inv_loc_auto", "入库时自动上架到推荐的货位（同一物品已在的货位 → 附近空位 → 其它空位；关掉 = 先进「待上架」，扫货位确认）", "bool"),
        ("inv_loc_layer_bottom", "最下面一层是第 1 层（关掉 = 最上面一层是第 1 层）", "bool"),
        ("inv_loc_idle_days", "货位图提醒：有货的货位多少天没动过算「呆滞」"),
        ("inv_loc_max_spread", "货位图提醒：一个物品放在超过几个货位就提醒（太分散不好拣）")]),
        ("区和流程（v2.53）", [
            ("inv_qc_on", "打印出来的成品先进「待检区」，质检合格再上架（关掉 = 直接按推荐上架）", "bool"),
            ("inv_returns_zone", "售后放回库存 / 登记的退货先进「退货区」，检查后再上架或放次品区", "bool"),
            ("inv_pack_station", "打包台的货位（发货扣包材先从这里扣；空 = 包材区）"),
            ("inv_slow_days", "多少天没进出算「很久没动」（库存金额页）"),
            ("inv_spool_tare_g", "空料盘重量（克）：称重盘点时 毛重 − 这个 = 剩余"),
            ("inv_spool_low_g", "料卷剩多少克以下提醒「快用完」（0 = 不提醒）"),
            ("inv_spool_expire_days", "料卷入库超过多少天提醒（0 = 不提醒）"),
            ("inv_spool_dry_days", "开封 / 烘干后多少天提醒烘干（0 = 按材料：PLA 30、PETG 7、TPU 3 …）")]),
        ("成品备货（v2.54）", [
            ("gs_sales_days", "目标数量：看最近几天的销量来算"),
            ("gs_safety", "目标数量：再多备几件（安全库存）"),
            ("gs_cat_default", "分类默认目标（还没有销量的新品用），写法：挂件=5, 摆件=3"),
            ("gs_over_x", "库存超过目标的几倍算「积压」")]),
        ("订单发货出库", [
            ("inv_ship_out", "订单变成「已发货」时自动出库：扣「用库存发」的成品、这单用的纸箱、下面规则里的包材（每单一张出库单）", "bool")])],
    "config_defaults": {"inv_loc_auto": True, "inv_loc_layer_bottom": True, "inv_ship_out": True, "inv_loc_idle_days": 90, "inv_loc_max_spread": 3,
                        "inv_qc_on": True, "inv_qc_hint253": False, "inv_returns_zone": True, "inv_pack_station": "", "inv_slow_days": 60, "inv_spool_tare_g": 250,
                        "inv_spool_low_g": 150, "inv_spool_expire_days": 365, "inv_spool_dry_days": 0,
                        "gs_sales_days": 30, "gs_safety": 1, "gs_cat_default": "", "gs_over_x": 3},
    "ui": {"inline": True, "html": "page.html", "eager_js": ["inventory.js", "locations.js", "wms.js", "stocktake.js", "zones.js", "goodsstock.js"], "css": ["page.css"],
           "page_js": [], "boot_js": []},
}
