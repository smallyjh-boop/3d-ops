"""库存：库存管理（物品、采购入库 / 领用 / 报废 / 调整单据、盘点、流水、库存报表）、发货自动扣包材、
打印扣耗材和成品增减同步记流水、给财务的事件接口。数据在 core/inventory/。
接订单模块的事件 order.status（已发货 → 扣包材）。关掉后：不再记库存流水、不扣包材 / 备件，耗材料卷照常（生产模块）。"""
from . import events

MODULE = {
    "id": "inv",
    "name_zh": "库存",
    "name_th": "สต็อก",
    "version": "1.1",
    "desc_zh": "库存管理（物品、单据、盘点、流水）、发货自动扣包材、打印扣耗材和成品同步记流水。",
    "desc_th": "จัดการสต็อก (สิ่งของ เอกสาร ตรวจนับ ความเคลื่อนไหว) ตัดวัสดุแพ็กอัตโนมัติเมื่อส่งของ บันทึกการใช้ฟิลาเมนต์และสินค้าสำเร็จรูป",
    "depends": [],
    "order": 6,
    "menus": [
        {"tab": "inventory", "mod": "inv", "zh": "库存管理", "th": "จัดการสต็อก", "roles": "owner,production,listing", "before": "materials"},
    ],
    "events": {"order.status": events.on_order_status},
    "ui": {"inline": True, "html": "page.html", "eager_js": ["inventory.js"], "page_js": [], "boot_js": []},
}
