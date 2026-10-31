"""AI 客服——v2.30 从内核搬出来的模块（原来的 core/cs/ 现在是 modules/cs/logic/）。

客服工作台、登记中心、客服报表、知识库与话术；顶部「有客户在问」提醒；浏览器扩展的聊天接口；
超时未回复的手机提醒（Telegram）和周报邮件。只通过 logic/erp_link.py 读写产品、订单、生产。
"""
from . import events, logic


def _start_alerts():
    from .logic import alerts, jobs
    alerts.start()
    jobs.start()          # v2.46：拉平台消息、AI 草稿 / 自动回复、主动提醒、质检（CS_WORKER=external 时不在这里跑）


def _todo(add):
    """v2.46 今日待办：超时没回复的买家、需要人工处理的会话。超时已经由客服自己的 Telegram / 邮件提醒推送，这里不再推。"""
    from core import db
    from .logic import data
    for x in data.overdue()[:30]:
        who = x["buyer"] or "买家"
        add(f"csov:{x['id']}:{int(x['last_at'] or 0)}", "客服", "bad", f"买家等了 {x['wait_min']} 分钟没回复：{who}", x["text"], "cs",
            "owner,listing", th=(f"ลูกค้ารอ {x['wait_min']} นาทียังไม่ได้ตอบ: {who}", x["text"]))
    for r in db.conn().execute("SELECT id, buyer, human_reason, last_buyer_at FROM cs_conv WHERE needs_human=1 AND status!='closed' "
                               "ORDER BY id DESC LIMIT 30"):
        who = r["buyer"] or "买家"
        add(f"cshuman:{r['id']}:{int(r['last_buyer_at'] or 0)}", "客服", "warn", f"要人工处理：{who}", r["human_reason"] or "", "cs",
            "owner,listing", th=(f"ต้องให้คนตอบ: {who}", r["human_reason"] or ""))


MODULE = {
    "id": "cs",
    "name_zh": "AI 客服",
    "name_th": "แชทลูกค้า AI",
    "version": "2.1",
    "desc_zh": "客服工作台（汇总）、聊天页（Lazada 接口直接收发、AI 草稿 / 自动回复、人工接管）、登记中心、客服报表、知识库与话术、浏览器扩展聊天、超时提醒。",
    "desc_th": "หน้าแชทลูกค้า (AI เขียนคำตอบ อ่านภาพหน้าจอ เสนอราคา) ศูนย์บันทึก รายงาน คลังความรู้ ส่วนขยายเบราว์เซอร์ และแจ้งเตือนเมื่อตอบช้า",
    "depends": [],
    "order": 10,
    "public": logic,
    "menus": [
        {"tab": "csdash", "mod": "cs", "zh": "客服工作台", "th": "ภาพรวมแชทลูกค้า", "roles": "owner,listing"},
        {"tab": "cs", "mod": "cs", "zh": "客服聊天", "th": "แชทลูกค้า", "roles": "owner,listing", "after": "csdash"},
        {"tab": "csrec", "mod": "cs", "zh": "登记中心", "th": "ศูนย์บันทึก", "roles": "owner,listing", "after": "cs"},
        {"tab": "csrep", "mod": "cs", "zh": "客服报表", "th": "รายงานแอดมิน", "roles": "owner,listing", "after": "csrec"},
        {"tab": "cskb", "mod": "cs", "zh": "知识库与话术", "th": "คลังความรู้และคำตอบ", "roles": "owner,listing", "after": "csrep"},
    ],
    "owner_only": [("POST", r"^/api/cs/settings$"), ("POST", r"^/api/cs/mail/test$"), ("DELETE", r"^/api/cs/(convs|examples)/")],
    "perm_rules": [("DELETE", r"^/api/cs/(messages|convs)/\d+$", "cs.delete")],
    "settings_cards": ["cs", "accounts"],
    "startup": _start_alerts,
    "events": {"order.status": events.on_order_status},
    "todo": _todo,                # v2.46 今日待办（core/todo.py）
    "ui": {"html": "page.html", "page_js": ["cs.js", "csdash.js", "csrec.js", "page.js"], "css": ["page.css"], "boot_js": ["csalert.js"]},
}
