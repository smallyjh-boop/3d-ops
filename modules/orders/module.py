"""订单（基础模块）：订单列表 / 导入 / 手工单 / 审单、打包核对、发货交接、售后、买家档案、每单利润、工作台数据、
打印订单 / 面单 / 交接单。订单变化通过 core/chain.py 发事件：生产模块生成生产任务、库存模块发货扣包材。"""

MODULE = {
    "id": "orders",
    "name_zh": "订单",
    "name_th": "ออเดอร์",
    "version": "1.0",
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
    "ui": {"inline": True, "html": "page.html", "eager_js": ["aftersales.js", "shipping.js"], "page_js": [], "boot_js": []},
}
