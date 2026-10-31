"""电商财务——v2.30 从内核搬出来的模块（原来的 core/fin/ 现在是 modules/fin/logic/，接口是 api.py）。

总览与损益、利润分析、平台结算对账、收支记账（带票据）、现金流、税务（VAT）；
对外只读接口 /api/v1/finance/{pl,breakdown,cashflow,expenses,tax}（密钥权限 finance）。
「每单利润」和库存 / 采购记的财务事件（/api/v1/finance/events、/inventory）在内核里，关掉财务模块不影响。
"""
from . import logic


def _todo(add):
    logic.todo(add)


def _start():
    from .logic import recon
    recon.start()


MODULE = {
    "id": "fin",
    "name_zh": "财务",
    "name_th": "การเงิน",
    "version": "1.8",
    "desc_zh": "总览（损益、利润分析）、订单利润、平台对账（Lazada 接口自动对账，Shopee / TikTok 导入报表）、收支与现金流、税务；给会计软件的只读接口。",
    "desc_th": "ภาพรวม (กำไรขาดทุน วิเคราะห์กำไร) กำไรรายคำสั่งซื้อ กระทบยอดแพลตฟอร์ม (Lazada อัตโนมัติผ่าน API, Shopee / TikTok นำเข้ารายงาน) รายรับรายจ่ายและกระแสเงินสด ภาษี และ API อ่านอย่างเดียวสำหรับโปรแกรมบัญชี",
    "depends": [],
    "order": 40,
    "public": logic,
    # v2.49：8 个菜单并成 5 个；旧的菜单名（fin_profit、fin_cash、订单模块的「每单利润」profit）留成看不见的菜单，跳到新页面对应的页签
    "menus": [
        {"tab": "fin_overview", "mod": "biz", "zh": "总览", "th": "ภาพรวม", "roles": "owner", "before": "profit"},
        {"tab": "fin_orders", "mod": "biz", "zh": "订单利润", "th": "กำไรรายคำสั่งซื้อ", "roles": "owner", "after": "fin_overview"},
        {"tab": "fin_settle", "mod": "biz", "zh": "平台对账", "th": "กระทบยอดแพลตฟอร์ม", "roles": "owner", "after": "fin_orders"},
        {"tab": "fin_book", "mod": "biz", "zh": "收支与现金流", "th": "รายรับรายจ่ายและกระแสเงินสด", "roles": "owner", "after": "fin_settle"},
        {"tab": "fin_tax", "mod": "biz", "zh": "税务", "th": "ภาษี", "roles": "owner", "after": "fin_book"},
        {"tab": "fin_profit", "mod": "biz", "zh": "利润分析", "th": "วิเคราะห์กำไร", "roles": "owner", "ghost": True, "panel": "fin_overview"},
        {"tab": "fin_cash", "mod": "biz", "zh": "现金流", "th": "กระแสเงินสด", "roles": "owner", "ghost": True, "panel": "fin_book"},
        {"tab": "profit", "mod": "biz", "zh": "每单利润", "th": "กำไรต่อคำสั่งซื้อ", "roles": "owner", "ghost": True, "panel": "fin_orders"},
    ],
    "todo": _todo,
    "startup": _start,
    "ui": {"html": "page.html", "page_js": ["finance.js", "orders.js", "settle.js", "page.js"], "css": ["page.css"], "boot_js": ["boot.js"]},
}
