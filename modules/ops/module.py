"""运营分析（v2.46，把原来单独的「运营分析系统」并进来）：运营看板、商品生命周期、今日待办与手机提醒、Lazada 运营数据
（财务流水 → 真实扣点 / 财务对账、评价、退货退款、店铺表现）。数据直接读 ERP，不再通过 /api/v1 同步一份。
第二期（v2.48）：竞品、爆款雷达、竞店（菜单在「商品」下面），计划、营销日历、流量数据（菜单在「工作台」下面），
浏览器扩展的采集和巡逻（/api/v1/ops/ext/…，和 AI 客服同一个扩展、同一把员工密钥）。"""
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
    "version": "2.1",
    "desc_zh": "运营看板、商品生命周期、今日待办与 LINE / Telegram 提醒、Lazada 财务流水 / 评价 / 退货退款 / 店铺表现；"
               "竞品、爆款雷达、竞店、爆款 / 上量计划、营销日历、卖家后台流量数据（浏览器扩展采集）。",
    "desc_th": "แดชบอร์ดการขาย วงจรชีวิตสินค้า งานวันนี้และแจ้งเตือน LINE / Telegram ข้อมูลการเงิน รีวิว คืนสินค้า และประสิทธิภาพร้านจาก Lazada "
               "สินค้าคู่แข่ง เรดาร์สินค้าขายดี ร้านคู่แข่ง แผนสินค้า ปฏิทินการตลาด ข้อมูลทราฟฟิกหลังร้าน (เก็บด้วยส่วนขยายเบราว์เซอร์)",
    "depends": [],
    "order": 45,
    "public": public,
    "menus": [
        {"tab": "ops_todo", "mod": "home", "zh": "今日待办", "th": "งานวันนี้", "roles": "owner,listing,production", "after": "dashboard"},
        {"tab": "ops_dash", "mod": "home", "zh": "运营看板", "th": "แดชบอร์ดการขาย", "roles": "owner", "after": "ops_todo"},
        {"tab": "ops_life", "mod": "home", "zh": "商品生命周期", "th": "วงจรชีวิตสินค้า", "roles": "owner", "after": "ops_dash"},
        {"tab": "ops_lazada", "mod": "home", "zh": "Lazada 数据", "th": "ข้อมูล Lazada", "roles": "owner,listing", "after": "ops_life"},
        {"tab": "ops_plans", "mod": "home", "zh": "爆款 / 上量计划", "th": "แผนสินค้าขายดี", "roles": "owner,listing", "after": "ops_lazada"},
        {"tab": "ops_cal", "mod": "home", "zh": "营销日历", "th": "ปฏิทินการตลาด", "roles": "owner,listing", "after": "ops_plans"},
        {"tab": "ops_traffic", "mod": "home", "zh": "流量数据", "th": "ข้อมูลทราฟฟิก", "roles": "owner", "after": "ops_cal"},
        {"tab": "ops_comp", "mod": "goods", "zh": "竞品", "th": "สินค้าคู่แข่ง", "roles": "owner,listing"},
        {"tab": "ops_radar", "mod": "goods", "zh": "爆款雷达", "th": "เรดาร์สินค้าขายดี", "roles": "owner,listing", "after": "ops_comp"},
        {"tab": "ops_shops", "mod": "goods", "zh": "竞店", "th": "ร้านคู่แข่ง", "roles": "owner,listing", "after": "ops_radar"},
    ],
    "owner_only": [("GET", r"^/api/oa/(dashboard|lifecycle|alerts)$"), ("POST", r"^/api/oa/(lazada/sync|alerts/)"),
                   ("*", r"^/api/oa/traffic(/|$)"),                            # 流量只给老板
                   # v2.48.0：竞品、雷达、竞店也给上架客服看（成本、利润在接口里去掉，见 mkt_api._strip）；估成本只给老板
                   ("POST", r"^/api/oa/comp/\d+/ai-cost$"),
                   ("POST", r"^/api/oa/plans(/\d+)?$"), ("POST", r"^/api/oa/plans/\d+/ai$"), ("POST", r"^/api/oa/campaigns")],
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
        ("竞品推算", [
            ("oa_comp_stale_days", "竞品数据超过几天没更新就提醒"), ("oa_comp_price_drop_pct", "竞品降价超过百分之几提醒"),
            ("oa_review_rate_lazada", "留评比例 Lazada（只有评价数时估销量用，0.15 = 15%）"), ("oa_review_rate_shopee", "留评比例 Shopee"),
            ("oa_review_rate_tiktok", "留评比例 TikTok")]),
        ("爆款雷达 · 巡逻（浏览器扩展）", [
            ("oa_patrol_daily_cap", "每天最多巡逻几个页面（越少越不容易被平台要求验证）"), ("oa_patrol_wait_min", "每个页面最少停留几秒"),
            ("oa_patrol_wait_max", "每个页面最多停留几秒"), ("oa_patrol_competitors", "巡逻时顺便更新竞品数据", "bool")]),
        ("爆款雷达 · 打分（机会分 0–100，有侵权风险直接 0 分）", [
            ("oa_radar_w_demand", "权重：需求"), ("oa_radar_w_competition", "权重：竞争少"), ("oa_radar_w_printable", "权重：能打印"),
            ("oa_radar_w_profit", "权重：利润"), ("oa_radar_w_potential", "权重：小爆潜力"),
            ("oa_radar_alert_score", "多少分以上进今日待办和手机提醒"), ("oa_radar_report_hour", "每天几点推送机会日报（0–23）")]),
        ("竞店", [
            ("oa_my_shop_urls", "我的店铺前台链接（Lazada / Shopee 店铺首页，多个用空格隔开）"),
            ("oa_shop_patrol_days", "竞店每隔几天巡逻一次")]),
        ("营销日历", [
            ("oa_avg_hours_per_order", "订单还不够 5 单时，按每单平均几小时打印估产能"), ("oa_ship_window_hours", "承诺发货时间（小时）"),
            ("oa_campaign_lookahead_days", "日历往后看几天")]),
    ],
    "config_defaults": {"oa_alert_on": False, "oa_alert_every_min": 10, "oa_line_token": "", "oa_line_to": "", "oa_alert_telegram": False,
                        "oa_alert_muted": [], "oa_ship_warn_hours": 12, "oa_cod_fail_rate": 10, "oa_bad_review_stars": 3,
                        "oa_test_days": 14, "oa_retest_days": 30, "oa_hero_qty_30d": 10, "oa_decline_days": 30, "oa_delist_days": 60,
                        "oa_lz_sync_min": "60",
                        "oa_comp_stale_days": 7, "oa_comp_price_drop_pct": 5, "oa_review_rate_lazada": 0.15, "oa_review_rate_shopee": 0.35,
                        "oa_review_rate_tiktok": 0.10, "oa_patrol_daily_cap": 60, "oa_patrol_wait_min": 20, "oa_patrol_wait_max": 60,
                        "oa_patrol_competitors": True, "oa_radar_w_demand": 25, "oa_radar_w_competition": 20, "oa_radar_w_printable": 20,
                        "oa_radar_w_profit": 25, "oa_radar_w_potential": 10, "oa_radar_alert_score": 70, "oa_radar_report_hour": 8,
                        "oa_my_shop_urls": "", "oa_shop_patrol_days": 1, "oa_avg_hours_per_order": 2.0, "oa_ship_window_hours": 48,
                        "oa_campaign_lookahead_days": 60},
    "secrets": ["oa_line_token"],
    "todo": _todo,
    "startup": _start,
    "ui": {"html": "page.html", "page_js": ["ops.js", "market.js", "plan.js", "page.js"], "css": ["page.css"], "boot_js": []},
}
