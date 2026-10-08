"""订单（基础模块）：订单列表 / 导入 / 手工单 / 审单、打包核对、发货交接、售后、买家档案、每单利润、工作台数据、
打印订单 / 面单 / 交接单。订单变化通过 core/chain.py 发事件：生产模块生成生产任务、库存模块发货扣包材。"""

MODULE = {
    "id": "orders",
    "name_zh": "订单",
    "name_th": "ออเดอร์",
    "version": "1.3",
    "desc_zh": "订单、审单、打包核对、发货交接、售后、买家档案、每单利润。",
    "desc_th": "ออเดอร์ ตรวจออเดอร์ ตรวจแพ็ก ส่งมอบพัสดุ หลังการขาย ข้อมูลผู้ซื้อ กำไรต่อคำสั่งซื้อ",
    "core": True,
    "depends": ["goods"],
    "order": 4,
    "menus": [
        {"tab": "orders", "mod": "orders", "zh": "订单列表", "th": "รายการออเดอร์", "roles": "owner,listing,production"},
        {"tab": "pack", "mod": "orders", "zh": "打包核对", "th": "ตรวจแพ็ก", "roles": "owner,listing,production", "after": "orders"},
        {"tab": "handover", "mod": "orders", "zh": "发货交接", "th": "ส่งมอบพัสดุ", "roles": "owner,listing,production", "after": "pack"},
        {"tab": "aftersales", "mod": "orders", "zh": "售后", "th": "หลังการขาย", "roles": "owner,listing", "after": "handover"},
        {"tab": "buyers", "mod": "orders", "zh": "买家档案", "th": "ข้อมูลผู้ซื้อ", "roles": "owner,listing", "after": "aftersales"},
        {"tab": "profit", "mod": "biz", "zh": "每单利润", "th": "กำไรต่อคำสั่งซื้อ", "roles": "owner"},
    ],
    "production_allow": [("GET", r"^/print/(item-labels|waybill|waybill-preview)$"), ("GET", r"^/api/waybill/(status|awb/\d+/\d+\.png)$")],
    "owner_only": [("POST", r"^/api/waybill/template$")],
    "settings_module": "orders",
    "settings": [("打包核对与发货交接（扫什么码）", [
        ("scan_order_key", "打开订单 / 发货交接时扫：both = 订单号或快递单号；tracking = 只认快递单号；order = 只认订单号", ["both", "tracking", "order"]),
        ("pack_item_mode", "打包时怎么核对商品（产品里可以单独设）：tap = 点一下确认；scan = 扫商品码 / 内部标签；none = 只核对订单", ["tap", "scan", "none"]),
        ("item_label_size", "内部商品标签尺寸（毫米，热敏标签纸）", ["50x30", "40x30", "60x40"])]),
        ("自制面单模板", [
            ("label_carrier", "用哪家快递的版式：auto = 按订单的「物流」自动认（认不出用通用版）", ["auto", "flash", "kerry", "jt", "spx", "lex", "best", "ninja", "dhl", "thpost", "generic"]),
            ("label_size", "面单尺寸：100x150 热敏 4×6 寸 / 100x100 小标签 / a6 普通打印机 A6 纸", ["100x150", "100x100", "a6"])])],
    "settings_cards": ["orders"],
    "config_defaults": {"scan_order_key": "both", "pack_item_mode": "tap", "item_label_size": "50x30", "label_carrier": "auto", "label_size": "100x150"},
    "ui": {"inline": True, "html": "page.html", "eager_js": ["orders.js", "aftersales.js", "shipping.js", "pack.js", "labels.js"], "css": ["page.css"], "page_js": [], "boot_js": []},
}
