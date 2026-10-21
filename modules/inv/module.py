"""库存：库存管理（物品、采购入库 / 领用 / 报废 / 调整单据、盘点、流水、库存报表）、发货自动扣包材、
打印扣耗材和成品增减同步记流水、给财务的事件接口。数据在 core/inventory/。
接订单模块的事件 order.status（已发货 → 扣包材）。关掉后：不再记库存流水、不扣包材 / 备件，耗材料卷照常（生产模块）。"""
from . import events, public

MODULE = {
    "id": "inv",
    "name_zh": "库存",
    "name_th": "สต็อก",
    "version": "1.5",
    "desc_zh": "库存管理（物品、单据、盘点、流水）、发货自动扣包材、打印扣耗材和成品同步记流水。",
    "desc_th": "จัดการสต็อก (สิ่งของ เอกสาร ตรวจนับ ความเคลื่อนไหว) ตัดวัสดุแพ็กอัตโนมัติเมื่อส่งของ บันทึกการใช้ฟิลาเมนต์และสินค้าสำเร็จรูป",
    "depends": [],
    "order": 6,
    "menus": [
        {"tab": "inventory", "mod": "inv", "zh": "库存管理", "th": "จัดการสต็อก", "roles": "owner,production,listing", "before": "materials"},
    ],
    "events": {"order.status": events.on_order_status},
    "public": public,             # 别的模块用：where_is / sort_key / order_out；ledger.post → on_post（新物品自动放货位）
    "production_allow": [("POST", r"^/api/inv/locations(/(assign|assign-all|bulk|add|group))?$"), ("GET", r"^/print/inv-locations$")],
    "settings_module": "inventory",
    "settings": [("货位", [
        ("inv_loc_auto", "新物品第一次入库、还没货位时，自动放到这个分类的货架的空格（关掉 = 人工放）", "bool"),
        ("inv_loc_layer_bottom", "最下面一层是第 1 层（关掉 = 最上面一层是第 1 层）", "bool")]),
        ("订单发货出库", [
            ("inv_ship_out", "订单变成「已发货」时自动出库：扣「用库存发」的成品、这单用的纸箱、下面规则里的包材（每单一张出库单）", "bool")])],
    "config_defaults": {"inv_loc_auto": True, "inv_loc_layer_bottom": True, "inv_ship_out": True},
    "ui": {"inline": True, "html": "page.html", "eager_js": ["inventory.js", "locations.js"], "css": ["page.css"], "page_js": [], "boot_js": []},
}
