"""运营分析（v2.46，把原来单独的「运营分析系统」并进来）：运营看板、商品生命周期、今日待办与手机提醒、Lazada 运营数据
（财务流水 → 真实扣点 / 财务对账、评价、退货退款、店铺表现）。数据直接读 ERP，不再通过 /api/v1 同步一份。"""
from . import public


def _start():
    from . import alerts, lazada
    lazada.start()
    alerts.start()


def _todo(add):
    from . import todos
    todos.provide(add)


MODULE = {
    "id": "ops",
    "name_zh": "运营分析",
    "name_th": "วิเคราะห์การขาย",
    "version": "1.0",
    "desc_zh": "运营看板、商品生命周期、今日待办与 LINE / Telegram 提醒、Lazada 财务流水 / 评价 / 退货退款 / 店铺表现。",
    "desc_th": "แดชบอร์ดการขาย วงจรชีวิตสินค้า งานวันนี้และแจ้งเตือน LINE / Telegram ข้อมูลการเงิน รีวิว คืนสินค้า และประสิทธิภาพร้านจาก Lazada",
    "depends": [],
    "order": 45,
    "public": public,
    "menus": [
        {"tab": "ops_todo", "mod": "home", "zh": "今日待办", "th": "งานวันนี้", "roles": "owner,listing,production", "after": "dashboard"},
        {"tab": "ops_dash", "mod": "home", "zh": "运营看板", "th": "แดชบอร์ดการขาย", "roles": "owner", "after": "ops_todo"},
        {"tab": "ops_life", "mod": "home", "zh": "商品生命周期", "th": "วงจรชีวิตสินค้า", "roles": "owner", "after": "ops_dash"},
        {"tab": "ops_lazada", "mod": "home", "zh": "Lazada 数据", "th": "ข้อมูล Lazada", "roles": "owner,listing", "after": "ops_life"},
    ],
    "owner_only": [("GET", r"^/api/oa/(dashboard|lifecycle|alerts)$"), ("POST", r"^/api/oa/(lazada/sync|alerts/)")],
    "settings_module": "ops",
    "settings": [
        ("手机提醒（今日待办里重要的事推到手机，同一件事只推一次）", [
            ("oa_alert_on", "开启手机提醒", "bool"),
            ("oa_alert_every_min", "每隔几分钟检查一次"),
            ("oa_line_token", "LINE 官方账号 Channel access token（LINE Developers → Messaging API）", "password"),
            ("oa_line_to", "LINE 接收人 User ID（U 开头）或群组 ID（C 开头）"),
            ("oa_alert_telegram", "也发到客服模块设好的 Telegram 机器人", "bool")]),
        ("看板与提醒的标准", [
            ("oa_ship_warn_hours", "离最晚发货不到几小时就提醒"),
            ("oa_cod_fail_rate", "货到付款拒收率超过百分之几提醒（近 30 天至少 10 单货到付款才算）"),
            ("oa_bad_review_stars", "几星及以下算差评")]),
        ("商品生命周期（测款规则，天 / 件）", [
            ("oa_test_days", "测款期天数（从第一次在售算）"), ("oa_retest_days", "再测截止天数（到这天还没出单就建议下架）"),
            ("oa_hero_qty_30d", "近 30 天卖到几件算主推"), ("oa_decline_days", "出过单后连续几天零销量算衰退"),
            ("oa_delist_days", "连续几天零销量建议下架")]),
        ("Lazada 运营数据", [
            ("oa_lz_sync_min", "每隔几分钟自动拉一次财务流水、评价、退货退款、店铺表现（0 = 只手动点「立即同步」）",
             ["0", "30", "60", "120", "360"])]),
    ],
    "config_defaults": {"oa_alert_on": False, "oa_alert_every_min": 10, "oa_line_token": "", "oa_line_to": "", "oa_alert_telegram": False,
                        "oa_alert_muted": [], "oa_ship_warn_hours": 12, "oa_cod_fail_rate": 10, "oa_bad_review_stars": 3,
                        "oa_test_days": 14, "oa_retest_days": 30, "oa_hero_qty_30d": 10, "oa_decline_days": 30, "oa_delist_days": 60,
                        "oa_lz_sync_min": "60"},
    "secrets": ["oa_line_token"],
    "todo": _todo,
    "startup": _start,
    "ui": {"html": "page.html", "page_js": ["ops.js", "page.js"], "css": ["page.css"], "boot_js": []},
}
