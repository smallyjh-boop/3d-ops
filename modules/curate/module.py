"""选品（v2.50，把单独的「3D选品工具」并进 ERP）：只做 ERP 没有的那部分——在模型网站（MakerWorld / Printables / Thingiverse……）上找能卖的模型。
候选池打分（泰国市场的排除规则 + AI 批量判断）→「采用」马上在产品库建 ERP 产品草稿（许可待核验）→ 之后全用 ERP 的产品编辑、模型库、
AI 文案、类目属性、定价、上架检查（许可没核验不能导出 / 推送）。另外：关注巡逻、站点包、防风控节奏、用浏览器登录状态下载模型文件、
估算 vs 实测校准（ERP 生产记录）、和爆款雷达的需求 ↔ 供给联动。
页面在顶部「商品」菜单的第一个：选品 · 产品库 · 上架；选品里三个页签：候选池 · 采集队列 · 关注巡逻。"""


def _start():
    from . import inbox, pipeline
    try:
        inbox.migrate()          # v2.50.1：已经在产品库里的选品草稿（没导出 / 上架过）搬进采集箱，只做一次
    except Exception:  # noqa: BLE001
        pass
    pipeline.start()


def _todo(add):
    from . import todos
    todos.provide(add)


class _Public:
    """给别的模块用的（modules.public("curate")）。"""
    @staticmethod
    def from_radar(keyword_id=None, keyword="", who=""):
        from core.config import load_config
        from . import demand
        return demand.from_radar(load_config(), keyword_id, keyword, who)

    @staticmethod
    def product_files(pid):
        """产品 360 / 编辑页：选品采用的产品的模型文件状态 {ok, queued, downloading, failed, links, collect, state, ext:{online}}。"""
        from . import watch
        return watch.file_status(pid)

    @staticmethod
    def inbox_count():
        """采集箱里有几个产品（产品库上的「采集箱 N」）。"""
        from . import inbox
        return inbox.count()


MODULE = {
    "id": "curate",
    "name_zh": "选品",
    "name_th": "คัดเลือกสินค้า",
    "version": "1.2",
    "desc_zh": "在模型网站找能卖的模型：候选池打分（泰国市场排除规则 + AI）、「采用」直接建产品草稿（许可待核验）、采集队列、关注巡逻；"
               "浏览器扩展显示推荐分、采集详情页、用浏览器登录状态下载模型文件。",
    "desc_th": "หาโมเดลที่ขายได้จากเว็บโมเดล 3D: ให้คะแนนผู้สมัคร (กฎตลาดไทย + AI) 「ใช้」สร้างสินค้าฉบับร่างทันที (รอตรวจสัญญาอนุญาต) คิวเก็บข้อมูล ตระเวนติดตาม "
               "ส่วนขยายเบราว์เซอร์แสดงคะแนน เก็บหน้ารายละเอียด และดาวน์โหลดไฟล์โมเดลด้วยการล็อกอินในเบราว์เซอร์",
    "depends": ["goods"],
    "order": 2,              # 在「商品」模块（order 1）后面：菜单要排在「产品库」前面
    "public": _Public,
    "menus": [
        {"tab": "curate", "mod": "goods", "zh": "选品", "th": "คัดเลือกสินค้า", "roles": "owner,listing", "before": "library"},
        {"tab": "cur_cand", "mod": "goods", "zh": "候选池", "th": "คลังผู้สมัคร", "roles": "owner,listing", "ghost": True, "panel": "curate"},
        {"tab": "cur_inbox", "mod": "goods", "zh": "采集箱", "th": "กล่องเก็บสินค้า", "roles": "owner,listing", "ghost": True, "panel": "curate"},
        {"tab": "cur_queue", "mod": "goods", "zh": "采集队列", "th": "คิวเก็บข้อมูล", "roles": "owner,listing", "ghost": True, "panel": "curate"},
        {"tab": "cur_watch", "mod": "goods", "zh": "关注巡逻", "th": "ตระเวนติดตาม", "roles": "owner,listing", "ghost": True, "panel": "curate"},
    ],
    # 改打分权重、上限这些设置在设置页（老板）；页面上的操作上架客服都能做（看不到成本、利润）
    "owner_only": [("POST", r"^/api/cur/(rescore|calibrate)$")],
    "settings_module": "goods",
    "settings": [
        ("选品 · 打分（推荐分 0–100，权重会自动换算）", [
            ("cur_w_demand", "权重：泰国需求"), ("cur_w_production", "权重：生产效率"), ("cur_w_profit", "权重：利润"),
            ("cur_w_competition", "权重：竞争少"), ("cur_w_popularity", "权重：原站热度"), ("cur_w_listing", "权重：上架难度"),
            ("cur_priority", "优先类目（逗号分隔）")]),
        ("选品 · 排除规则", [
            ("cur_max_minutes", "单件打印时长上限（分钟，超过就排除）"), ("cur_max_grams", "单件克数上限"),
            ("cur_exclude_kids", "排除儿童玩具（泰国要 TISI 认证）", "bool"),
            ("cur_calibrate", "按实测（ERP 生产记录、切片）校准 AI 估算的时长 / 克数（至少 5 个样本）", "bool")]),
        ("选品 · 提醒、巡逻和下载（浏览器扩展）", [
            ("cur_alert_score", "多少分以上算高分（进今日待办）"), ("cur_alert_on", "高分新模型也推到手机（运营分析的手机提醒）", "bool"),
            ("cur_watch_on", "开启关注巡逻", "bool"), ("cur_watch_daily_cap", "每个网站每天最多巡逻几页"),
            ("cur_watch_gap_min", "巡逻页面之间最少隔几分钟"), ("cur_watch_gap_max", "巡逻页面之间最多隔几分钟"),
            ("cur_dl_speed", "下载和采集的速度：slow 慢（最稳）/ normal 标准 / fast 快（容易被风控）", ["slow", "normal", "fast"]),
            ("cur_detail_conc", "每个网站同时读几个详情页（1–4，默认 2）"), ("cur_dl_conc", "每个网站同时下载几个文件（1–4，默认 2）"),
            ("cur_detail_hour_cap", "每个网站每小时最多读几个详情页（0 = 按速度档位：慢 150 / 标准 400 / 快 800）"),
            ("cur_dl_hour_cap", "每个网站每小时最多下载几个文件（0 = 按速度档位：慢 60 / 标准 150 / 快 300）"),
            ("cur_auto_download", "采用后自动下载模型文件（STL / 3MF / ZIP，放进产品的模型库）", "bool")]),
    ],
    "config_defaults": {"cur_w_demand": 30, "cur_w_production": 25, "cur_w_profit": 15, "cur_w_competition": 10, "cur_w_popularity": 15,
                        "cur_w_listing": 5, "cur_priority": "车和摩托配件,收纳整理,宠物,植物园艺,桌面办公,手机电脑配件,替换件适配件",
                        "cur_max_minutes": 240, "cur_max_grams": 80, "cur_exclude_kids": True, "cur_calibrate": True,
                        "cur_alert_score": 70, "cur_alert_on": True, "cur_watch_on": True, "cur_watch_daily_cap": 30, "cur_watch_gap_min": 3,
                        "cur_watch_gap_max": 8, "cur_dl_speed": "normal", "cur_auto_download": True,
                        "cur_detail_conc": 2, "cur_dl_conc": 2, "cur_detail_hour_cap": 0, "cur_dl_hour_cap": 0},
    "todo": _todo,
    "startup": _start,
    "ui": {"html": "page.html", "page_js": ["curate.js"], "css": ["page.css"], "boot_js": []},
}
