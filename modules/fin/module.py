"""电商财务——v2.30 从内核搬出来的模块（原来的 core/fin/ 现在是 modules/fin/logic/，接口是 api.py）。

总览与损益、利润分析、平台结算对账、收支记账（带票据）、现金流、税务（VAT）；
对外只读接口 /api/v1/finance/{pl,breakdown,cashflow,expenses,tax}（密钥权限 finance）。
「每单利润」和库存 / 采购记的财务事件（/api/v1/finance/events、/inventory）在内核里，关掉财务模块不影响。
"""
from . import logic

MODULE = {
    "id": "fin",
    "name_zh": "财务",
    "name_th": "การเงิน",
    "version": "1.4",
    "desc_zh": "总览与损益、利润分析、平台对账、收支记账、现金流、税务；给会计软件的只读接口。",
    "desc_th": "ภาพรวมกำไรขาดทุน วิเคราะห์กำไร กระทบยอดแพลตฟอร์ม บันทึกรายรับรายจ่าย กระแสเงินสด ภาษี และ API อ่านอย่างเดียวสำหรับโปรแกรมบัญชี",
    "depends": [],
    "order": 40,
    "public": logic,
    "menus": [
        {"tab": "fin_overview", "mod": "biz", "zh": "总览与损益", "th": "ภาพรวมและกำไรขาดทุน", "roles": "owner", "before": "profit"},
        {"tab": "fin_orders", "mod": "biz", "zh": "订单明细", "th": "รายละเอียดคำสั่งซื้อ", "roles": "owner", "after": "fin_overview"},
        {"tab": "fin_profit", "mod": "biz", "zh": "利润分析", "th": "วิเคราะห์กำไร", "roles": "owner", "after": "fin_orders"},
        {"tab": "fin_settle", "mod": "biz", "zh": "平台对账", "th": "กระทบยอดแพลตฟอร์ม", "roles": "owner", "after": "fin_profit"},
        {"tab": "fin_book", "mod": "biz", "zh": "收支记账", "th": "บันทึกรายรับรายจ่าย", "roles": "owner", "after": "fin_settle"},
        {"tab": "fin_cash", "mod": "biz", "zh": "现金流", "th": "กระแสเงินสด", "roles": "owner", "after": "fin_book"},
        {"tab": "fin_tax", "mod": "biz", "zh": "税务", "th": "ภาษี", "roles": "owner", "after": "fin_cash"},
    ],
    "ui": {"html": "page.html", "page_js": ["finance.js", "orders.js", "page.js"], "boot_js": []},
}
