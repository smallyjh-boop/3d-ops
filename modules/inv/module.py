"""库存：库存管理（物品、采购入库 / 领用 / 报废 / 调整单据、盘点、流水、库存报表）、发货自动扣包材、
打印扣耗材和成品增减同步记流水、给财务的事件接口。数据在 core/inventory/。
接订单模块的事件 order.status（已发货 → 扣包材）。关掉后：不再记库存流水、不扣包材 / 备件，耗材料卷照常（生产模块）。"""
from . import events, locations

MODULE = {
    "id": "inv",
    "name_zh": "库存",
    "name_th": "สต็อก",
    "version": "1.3",
    "desc_zh": "库存管理（物品、单据、盘点、流水）、发货自动扣包材、打印扣耗材和成品同步记流水。",
    "desc_th": "จัดการสต็อก (สิ่งของ เอกสาร ตรวจนับ ความเคลื่อนไหว) ตัดวัสดุแพ็กอัตโนมัติเมื่อส่งของ บันทึกการใช้ฟิลาเมนต์และสินค้าสำเร็จรูป",
    "depends": [],
    "order": 6,
    "menus": [
        {"tab": "inventory", "mod": "inv", "zh": "库存管理", "th": "จัดการสต็อก", "roles": "owner,production,listing", "before": "materials"},
    ],
    "events": {"order.status": events.on_order_status},
    "public": locations,          # ledger.post → locations.on_post（货位跟着调整）
    "production_allow": [("POST", r"^/api/inv/locations(/(move|putaway|bulk|add|group|\d+/check))?$"), ("GET", r"^/print/inv-locations$")],
    "settings_module": "inventory",
    "settings": [("货位", [
        ("inv_loc_auto", "入库时自动放进推荐货位（关掉 = 先记「未上架」，人工上架）", "bool"),
        ("inv_loc_layer_bottom", "最下面一层是第 1 层（关掉 = 最上面一层是第 1 层）", "bool")])],
    "config_defaults": {"inv_loc_auto": True, "inv_loc_layer_bottom": True},
    "ui": {"inline": True, "html": "page.html", "eager_js": ["inventory.js", "locations.js"], "css": ["page.css"], "page_js": [], "boot_js": []},
}
