"""采购——v2.30 从内核搬出来的模块。

采购单（下单、物流单号、到货入库、付款）、补货建议（按库存和在途算该买多少，一键生成采购单）、供应商、付款记录。
采购单的数据和到货入库在内核的库存里（库存流水只能通过单据改变），关掉采购模块库存照常用。
"""

MODULE = {
    "id": "pur",
    "name_zh": "采购",
    "name_th": "จัดซื้อ",
    "version": "1.0",
    "desc_zh": "采购单（下单、到货入库、付款）、补货建议、供应商、付款记录。",
    "desc_th": "ใบสั่งซื้อ (สั่ง รับของเข้าสต็อก จ่ายเงิน) แนะนำเติมสต็อก ผู้ขาย ประวัติการจ่ายเงิน",
    "depends": [],
    "order": 30,
    "menus": [
        {"tab": "purchase", "mod": "pur", "zh": "采购单", "th": "ใบสั่งซื้อ", "roles": "owner,production,listing"},
        {"tab": "po_suggest", "mod": "pur", "zh": "补货建议", "th": "แนะนำเติมสต็อก", "roles": "owner,production,listing", "after": "purchase", "panel": "purchase"},
        {"tab": "po_suppliers", "mod": "pur", "zh": "供应商", "th": "ผู้ขาย", "roles": "owner,production,listing", "after": "po_suggest", "panel": "purchase"},
        {"tab": "po_pay", "mod": "pur", "zh": "付款记录", "th": "ประวัติการจ่ายเงิน", "roles": "owner", "after": "po_suppliers", "panel": "purchase"},
    ],
    "production_allow": [("POST", r"^/api/inv/po/\d+/(receive|pay|order|cancel|close|tracking)$")],
    "ui": {"html": "page.html", "page_js": ["purchase.js", "page.js"], "boot_js": []},
}
