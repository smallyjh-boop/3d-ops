"""生产：生产看板（排单、打印批次）、打印机（连接、状态、保养）、文件管理、打印方案 / 切片文件、质量统计、
耗材料卷（补货计划）、成品备货。接订单模块的事件 order.changed（生成生产任务）和 chain.reschedule（重新排单）。
关掉后：新订单不生成生产任务、不轮询打印机；订单照常导入、发货。"""
from . import events

MODULE = {
    "id": "prod",
    "name_zh": "生产",
    "name_th": "การผลิต",
    "version": "1.11",
    "desc_zh": "生产看板、打印机、文件管理、打印方案和切片文件、质量统计、耗材料卷、成品备货。",
    "desc_th": "บอร์ดผลิต เครื่องพิมพ์ จัดการไฟล์ แผนการพิมพ์และไฟล์สไลซ์ สถิติคุณภาพ ม้วนฟิลาเมนต์ เตรียมสต็อกสินค้า",
    "depends": ["orders", "model"],
    "order": 5,
    "menus": [
        {"tab": "production", "mod": "prod", "zh": "生产看板", "th": "บอร์ดผลิต", "roles": "owner,production"},
        {"tab": "printers", "mod": "prod", "zh": "打印机", "th": "เครื่องพิมพ์", "roles": "owner,production", "after": "production"},
        {"tab": "files", "mod": "prod", "zh": "文件管理", "th": "จัดการไฟล์", "roles": "owner,production,listing", "after": "printers"},
        {"tab": "recipes", "mod": "prod", "zh": "打印方案 / 切片文件", "th": "แผนการพิมพ์ / ไฟล์สไลซ์", "roles": "owner,production", "after": "files"},
        {"tab": "quality", "mod": "prod", "zh": "质量统计", "th": "สถิติคุณภาพ", "roles": "owner,production", "after": "recipes"},
        # v2.53：不再是单独的菜单，是「仓库 → 库存」页里的页签「料卷」「成品备货」（旧 id 照样能打开，高亮「库存」）
        {"tab": "materials", "mod": "inv", "zh": "耗材料卷", "th": "ม้วนฟิลาเมนต์", "roles": "owner,production", "ghost": True, "parent": "inventory"},
        {"tab": "stock", "mod": "inv", "zh": "成品备货", "th": "เตรียมสต็อกสินค้า", "roles": "owner,production", "ghost": True, "parent": "inventory"},
    ],
    # v2.54：打印机机群的写操作（添加 / 修改 / 批量 / 发现 / 导入 / 模板）只有老板能做；生产员工能看总览、详情、打标签
    "owner_only": [("POST", r"^/api/print-files/\d+/confirm-printer$"), ("POST", r"^/api/fleet"), ("DELETE", r"^/api/fleet")],
    # v2.53：备货 / 试打 / 打印测试任务：生产角色也能用（接口里再核对一次角色：别的角色不行）
    "production_allow": [("POST", r"^/api/(jobs/stock|trial|trial/check-file|trial/job/\d+/result|trial/\d+/retry|printers/\d+/print-test)$"),
                         ("GET", r"^/api/trial/(skus|printers|pending|history|stats|job/\d+)$"),
                         ("GET", r"^/api/fleet(/meta|/printers/[^/]+)?$"), ("GET", r"^/print/fleet-labels$")],
    "settings_module": "orders",
    "settings": [("成品库存怎么用", [
        ("stock_auto_use", "订单的商品有成品库存时，自动「用库存发」（先占住数量，发货出库时才扣库存；不够的部分才排打印）", "bool")])],
    "config_defaults": {"stock_auto_use": True},
    "events": {"order.changed": events.on_order_changed, "chain.reschedule": events.on_reschedule},
    "ui": {"inline": True, "html": "page.html", "eager_js": ["recipe.js", "trial.js", "fleet.js", "prod.js", "files.js", "spools.js", "materials.js"], "page_js": [], "boot_js": []},
}
