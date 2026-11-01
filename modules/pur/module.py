"""采购——v2.30 从内核搬出来的模块；v2.51 按 BigSeller 的思路重做。

一个页面三个页签：补货建议（按生产任务、近 30 天用量、订单量算还能用几天、该买多少，红黄绿，一键按供应商生成采购单）·
采购单（草稿 → 已下单·在途 → 部分到货 → 已入库 → 完成；取消、退货；分几次付款，自动记到财务；人民币下单 + 汇率；
运费 / 税分摊进到手成本；贴订单文字 / 截图让 AI 开单）· 到货入库（扫码、记差异、放货位、打印标签；手机 /m 也能扫）。
供应商不单独一页：采购单 / 物品里下拉选，「＋新供应商」「管理」。物品 ↔ 供应商：购买链接、最近单价、起订量、包装数、到货天数、比价。
采购单的数据和到货入库在内核的库存里（库存流水只能通过单据改变），关掉采购模块库存照常用。
"""


from . import public


def _todo(add):
    from .logic import todo
    todo.provide(add)


def _on_received(po_id=None, lines=None, user="", **_kw):
    from .logic import links
    return links.on_po_received(po_id, lines, user)


MODULE = {
    "id": "pur",
    "name_zh": "采购",
    "name_th": "จัดซื้อ",
    "version": "2.0",
    "desc_zh": "补货建议（按真实用量）、采购单（在途、分批到货、差异、退货、分次付款、人民币汇率、到手成本）、到货入库（手机扫码）、供应商比价、AI 识别订单开单、采购分析。",
    "desc_th": "แนะนำเติมสต็อก (จากการใช้จริง) ใบสั่งซื้อ (ระหว่างขนส่ง รับหลายรอบ ของไม่ตรง คืนของ จ่ายหลายงวด อัตราแลกเปลี่ยนหยวน ต้นทุนถึงมือ) "
               "รับของเข้าคลัง (สแกนด้วยมือถือ) เทียบราคาผู้ขาย AI อ่านออเดอร์เปิดใบสั่งซื้อ วิเคราะห์การจัดซื้อ",
    "depends": ["inv"],
    "order": 30,
    # v2.51：四个菜单并成一个页面（三个页签）；旧的菜单 id 留成看不见的菜单，跳到对应的页签（书签、待办里的链接还能用）
    "menus": [
        {"tab": "purchase", "mod": "pur", "zh": "采购", "th": "จัดซื้อ", "roles": "owner,production,listing"},
        {"tab": "po_suggest", "mod": "pur", "zh": "补货建议", "th": "แนะนำเติมสต็อก", "roles": "owner,production,listing", "ghost": True,
         "panel": "purchase", "parent": "purchase"},
        {"tab": "po_recv", "mod": "pur", "zh": "到货入库", "th": "รับของเข้าคลัง", "roles": "owner,production,listing", "ghost": True,
         "panel": "purchase", "parent": "purchase"},
        {"tab": "po_suppliers", "mod": "pur", "zh": "供应商", "th": "ผู้ขาย", "roles": "owner,production,listing", "ghost": True,
         "panel": "purchase", "parent": "purchase"},
        {"tab": "po_pay", "mod": "pur", "zh": "付款记录", "th": "ประวัติการจ่ายเงิน", "roles": "owner", "ghost": True,
         "panel": "purchase", "parent": "purchase"},
    ],
    "production_allow": [("POST", r"^/api/inv/po/\d+/(receive|pay|refund|order|cancel|close|done|return|tracking)$"),
                         ("POST", r"^/api/inv/pur/(receive|links|links/\d+/delete|items/\d+/preferred|suggest/po|quick/(parse|create)|"
                                  r"issues/\d+/resolve|suppliers/\d+/delete)$"),
                         ("GET", r"^/print/pur-labels$")],
    "owner_only": [("POST", r"^/api/inv/pur/costs/\d+/(apply|dismiss)$")],
    "events": {"po.received": _on_received},
    "public": public,             # v2.54：draft_po / in_transit（成品备货的外购补货）
    "todo": _todo,
    "settings_module": "inventory",
    "settings": [("采购", [
        ("pur_default_lead_days", "一般从下单到收货几天（物品 / 供应商没写的时候用；耗材用「耗材从下单到收货大约几天」）"),
        ("pur_safety_days", "补货建议：安全天数（多备几天，防止晚到）"),
        ("pur_cover_days", "补货建议：一次买够几天的用量"),
        ("pur_auto_cost", "到货后耗材平均进价变了，自动更新定价用的「耗材价格（人民币/公斤）」（关掉 = 只提醒）", "bool"),
        ("pur_cost_alert_pct", "进价变化超过百分之几才提醒（例如 5）")])],
    "config_defaults": {"pur_default_lead_days": 7, "pur_safety_days": 5, "pur_cover_days": 30, "pur_auto_cost": True, "pur_cost_alert_pct": 5},
    "ui": {"html": "page.html", "page_js": ["purchase.js", "po.js", "page.js"], "css": ["page.css"], "boot_js": []},
}
