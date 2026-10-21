"""AI 客服——v2.30 从内核搬出来的模块（原来的 core/cs/ 现在是 modules/cs/logic/）。

客服工作台、登记中心、客服报表、知识库与话术；顶部「有客户在问」提醒；浏览器扩展的聊天接口；
超时未回复的手机提醒（Telegram）和周报邮件。只通过 logic/erp_link.py 读写产品、订单、生产。
"""
from . import logic


def _start_alerts():
    from .logic import alerts
    alerts.start()


MODULE = {
    "id": "cs",
    "name_zh": "AI 客服",
    "name_th": "แชทลูกค้า AI",
    "version": "1.3",
    "desc_zh": "客服工作台（AI 写回复、读截图、报价）、登记中心、客服报表、知识库与话术、浏览器扩展聊天、超时提醒。",
    "desc_th": "หน้าแชทลูกค้า (AI เขียนคำตอบ อ่านภาพหน้าจอ เสนอราคา) ศูนย์บันทึก รายงาน คลังความรู้ ส่วนขยายเบราว์เซอร์ และแจ้งเตือนเมื่อตอบช้า",
    "depends": [],
    "order": 10,
    "public": logic,
    "menus": [
        {"tab": "cs", "mod": "cs", "zh": "客服工作台", "th": "โต๊ะแชทลูกค้า", "roles": "owner,listing"},
        {"tab": "csrec", "mod": "cs", "zh": "登记中心", "th": "ศูนย์บันทึก", "roles": "owner,listing", "after": "cs"},
        {"tab": "csrep", "mod": "cs", "zh": "客服报表", "th": "รายงานแอดมิน", "roles": "owner,listing", "after": "csrec"},
        {"tab": "cskb", "mod": "cs", "zh": "知识库与话术", "th": "คลังความรู้และคำตอบ", "roles": "owner,listing", "after": "csrep"},
    ],
    "owner_only": [("POST", r"^/api/cs/settings$"), ("POST", r"^/api/cs/mail/test$"), ("DELETE", r"^/api/cs/(convs|examples)/")],
    "perm_rules": [("DELETE", r"^/api/cs/(messages|convs)/\d+$", "cs.delete")],
    "settings_cards": ["cs", "accounts"],
    "startup": _start_alerts,
    "ui": {"html": "page.html", "page_js": ["cs.js", "csrec.js", "page.js"], "boot_js": ["csalert.js"]},
}
