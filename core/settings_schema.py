"""设置页的结构（v2.18）：按模块分开，每个模块下面分组，每组若干字段。设置页按这里渲染。

以后加新模块 / 新设置：在 MODULES 里加，或者在自己的模块里调用 register(...)，设置页自动出现，不用改前端。
字段写法：(配置键, 中文说明[, 类型])  类型：省略 = 文本 / 数字；"bool"；"password"；"list"（逗号分隔）；["选项1", "选项2"]
special：设置页里有专门界面的卡片（打印机表、颜色表、发货包材规则），按名字放到对应模块里。
"""

MODULES = [
    {"id": "general", "zh": "通用", "th": "ทั่วไป", "special": ["remote"], "groups": [
        ("店铺与编码", [
            ("sku_prefix", "产品编码前缀（英文，例 3DP → 3DP0001）"), ("brand", "品牌"), ("shop_name_th", "店铺名称（可空）")]),
        ("登录", [("login_days", "记住登录几天（登录时勾了「记住登录」才有效；每天用会自动续期；改了要重启程序后生效）")]),
        ("在线更新（GitHub）", [
            ("update_repo", "GitHub 仓库（拥有者/仓库名）"), ("update_token", "GitHub 只读令牌（私有仓库要填；只存在 NAS 上）", "password"),
            ("update_check", "每天自动检查新版本（只提醒，升级要你点）", "bool")]),
        ("备份", [("backup_copy_dir", "备份另存一份到（文件夹路径，例如 U 盘 E:\\备份 或 网盘同步文件夹；NAS 版用 HBS 3）")]),
    ]},
    {"id": "modules", "zh": "模块管理", "th": "จัดการโมดูล", "ext": True, "groups": []},
    {"id": "accounts", "zh": "账号与权限", "th": "บัญชีและสิทธิ์", "ext": True, "groups": []},
    {"id": "cost", "zh": "成本与定价", "th": "ต้นทุนและราคา", "summary": True, "groups": [
        ("成本", [
            ("filament_price_cny_per_kg", "耗材价格（人民币/公斤）"), ("cny_to_thb", "人民币兑泰铢汇率"),
            ("material_loss_rate", "材料损耗率（0.1=10%）"), ("electricity_thb_per_kwh", "电价（铢/度）"),
            ("printer_avg_kw", "单台平均功率（千瓦）"), ("monthly_rent", "房租（铢/月）"), ("monthly_labor", "人工（铢/月）"),
            ("monthly_depreciation", "设备折旧（铢/月）"), ("monthly_maintenance", "维护配件（铢/月）"),
            ("printer_count", "打印机台数"), ("hours_per_day_each", "每台每天平均打印小时"),
            ("failure_rate", "失败率（0.05=5%）"), ("packaging_per_item", "每件包材（铢）"), ("packaging_weight_g", "包材重量（克）")]),
        ("定价", [
            ("platform_fee_rate", "平台扣点（0.2=20%，请按后台核实）"), ("shopee_fee_rate", "Shopee 扣点（0=和 Lazada 一样）"),
            ("default_markup", "默认加价率（1=100%）"), ("min_markup", "最低加价率（低于报警）"), ("price_ending", "价格尾数（-1=不处理）"),
            ("discount_display_rate", "划线折扣（0=不用，0.3=显示七折）")]),
    ]},
    {"id": "goods", "zh": "商品与上架", "th": "สินค้าและการลงขาย", "special": ["colors"], "ext": True, "groups": [
        ("文案", [
            ("copy_mention_lead_time", "文案写发货天数", "bool"), ("lead_time_days", "发货天数（开启上一项才写进文案）"),
            ("copy_mention_custom", "文案写「可定制」", "bool"), ("copy_mention_wholesale", "文案写「可批发」", "bool")]),
        ("变体与库存", [
            ("default_stock", "默认库存"), ("random_color_auto", "加颜色时每个规格自动加「随机颜色」", "bool")]),
        ("按耗材自动算库存（变体库存 = 这个颜色剩下的耗材能做几件；产品里可以单独开关）", [
            ("stock_auto", "总开关", "bool"), ("stock_cap", "库存上限（够做再多也只显示这么多）"),
            ("stock_low_line", "低库存线：能做的件数低于这个数时……"), ("stock_low_mode", "……zero = 显示 0（防止缺料卖出）；real = 显示真实件数", ["zero", "real"]),
            ("stock_min_change", "变化够几件才列进「库存待同步到平台」"), ("stock_loss_factor", "单件克数 × 损耗系数（支撑、失败）"),
            ("stock_safety_g", "每个颜色留多少克不算（卷尾）")]),
        ("图片", [
            ("image_size", "输出尺寸（像素）"), ("image_fill_ratio", "产品占画面比例"), ("imgbb_api_key", "imgbb 图床密钥", "password")]),
        ("场景图 AI（可选，按张收费）", [
            ("image_provider", "接口类型", ["openai", "gemini"]), ("image_api_key", "接口密钥", "password"),
            ("image_model", "模型（留空=最便宜的：gpt-image-1-mini / gemini-3.1-flash-lite-image；效果更好：gpt-image-1 / gemini-3.1-flash-image）"),
            ("image_quality", "清晰度（openai）", ["low", "medium", "high"]), ("image_api_base", "接口地址（留空=官方，第三方中转时填写）")]),
    ]},
    {"id": "orders", "zh": "订单与售后", "th": "ออเดอร์และหลังการขาย", "groups": [
        ("订单与备货", [
            ("default_ship_days", "默认发货天数（订单没有最晚发货时间、商品也没填时）"), ("stock_cover_days", "成品备货：常备几天的销量"),
            ("stock_min_sold30", "近 30 天卖了几个以上才建议备货")]),
        ("审单（新订单命中规则就挂起，人工审核通过后才排产）", [
            ("review_enabled", "自动审单", "bool"), ("review_amount_over", "金额 ≥ 多少要人工看（0=不查）"),
            ("review_cod_new_over", "货到付款新客 金额 ≥ 多少要人工看（0=不查）"), ("review_duplicate_hours", "同一买家几小时内买一样的算重复（0=不查）"),
            ("review_keywords", "买家留言里有这些词要人工看（逗号分隔）")]),
        ("物流与售后", [
            ("ship_method_default", "平台物流默认发货方式：pickup 上门揽收 / dropoff 送到网点", ["pickup", "dropoff"]),
            ("carrier_lazada", "Lazada 默认物流"), ("carrier_shopee", "Shopee 默认物流"), ("carrier_tiktok", "TikTok 默认物流"),
            ("as_due_hours", "售后默认处理期限（小时）"), ("as_return_days", "等买家寄回 / 拒收退回 默认几天")]),
        ("发货（自制面单的寄件人）", [("sender_name", "寄件人 / 店名"), ("sender_phone", "寄件人电话"), ("sender_address", "寄件地址")]),
    ]},
    {"id": "cs", "zh": "客服", "th": "แชทลูกค้า", "ext": True, "module": "cs", "groups": []},
    {"id": "production", "zh": "生产", "th": "การผลิต", "special": ["printers"], "ext": True, "module": "prod", "groups": [
        ("切片与估算", [
            ("orca_path", "OrcaSlicer 程序路径（留空自动查找）"), ("est_infill", "估算：填充率（0.15=15%）"),
            ("est_shell_mm", "估算：外壁+顶底厚度（毫米）"), ("est_support_factor", "估算：支撑损耗系数"),
            ("est_overhead_h", "估算：每次打印额外时间（小时）")]),
        ("光固化（树脂）", [
            ("resin_thb_per_kg", "树脂每公斤价格（铢）"), ("resin_extra_rate", "额外耗材比例（酒精、离型膜、手套，0.15=15%）"),
            ("resin_density", "树脂密度（克/毫升）"), ("resin_plate_hours", "没有切片文件时，每盘按几小时估算")], "resin"),
    ]},
    {"id": "inventory", "zh": "库存与采购", "th": "สต็อกและจัดซื้อ", "special": ["pack_rules"], "groups": [
        ("库存", [
            ("inv_loss_rate", "打印扣耗材的损耗率（0.05 = 产品克数的 5%，每个耗材也能单独设）"),
            ("inv_categories", "自己加的物品分类（逗号分隔；内置：耗材、备件、包材、成品、工具、其他）", "list")], "inv"),
        ("耗材补货", [
            ("filament_lead_days", "耗材到货天数（从下单到收货）"), ("filament_safety_days", "安全库存天数"),
            ("filament_cover_days", "每次补货够用天数"), ("filament_spool_kg", "每卷公斤数")], "prod"),
    ]},
    {"id": "finance", "zh": "财务", "th": "การเงิน", "module": "fin", "groups": [
        ("税（VAT）", [
            ("fin_vat_on", "已注册 VAT（开了以后报表按含税价拆出销项税、记进项税；还没注册就关着）", "bool"),
            ("fin_vat_rate", "VAT 税率（0.07 = 7%）"), ("fin_prices_incl_vat", "商品售价含 VAT", "bool")]),
        ("对账与报表", [
            ("fin_settle_days", "发货 / 完成多少天还没回款算「超时未回款」"),
            ("fin_settle_tolerance", "平台实际扣费比按扣点估算多出多少铢才提醒"),
            ("fin_ship_tolerance", "运费核对：平台扣的运费和订单运费差多少铢以上才列出来"),
            ("fin_import_remind_days", "Shopee / TikTok（没有接口的平台）多少天没导入结算报表就进今日待办"),
            ("fin_fixed_cats", "算「固定费用」的支出分类（逗号分隔；这期间没记账就按「成本与定价」里的房租、人工、折旧估算）", "list"),
            ("fin_expense_cats", "自己加的支出分类（逗号分隔）", "list")]),
    ]},
    {"id": "ops", "zh": "运营分析", "th": "วิเคราะห์การขาย", "module": "ops", "groups": []},     # v2.46 运营分析模块（设置在模块说明书里）
    {"id": "ai", "zh": "AI 与对接", "th": "AI และการเชื่อมต่อ", "ext": True, "groups": [
        ("AI", [
            ("ai_provider", "接口类型", ["anthropic", "openai_compatible"]), ("ai_model", "模型名称"),
            ("ai_api_key", "接口密钥", "password"), ("ai_base_url", "接口地址（openai_compatible 用）")]),
    ]},
    {"id": "addons", "zh": "组件与插件", "th": "ส่วนประกอบและปลั๊กอิน", "special": ["components", "accel"], "ext": True, "groups": [
        ("电脑加速（切片、读大模型、3D 预览、抠图交给一直开着的电脑做；电脑不在线时 NAS 自己做）", [
            ("accel_on", "开启电脑加速", "bool"), ("accel_local_slots", "NAS 自己做重活时同时最多几个（1 = 一个一个来，其余排队；内存大可以 2）"),
            ("accel_claim_wait", "电脑几秒内没接手（都在忙）就 NAS 自己做")]),
    ]},
]


def register(module_id, group_title, fields, module_zh=None, module_th=None, module_of=None):
    """别的模块加自己的设置：register("finance", "财务", [("fin_xxx", "说明")], "财务", "การเงิน")。
    module_of：这组设置属于哪个功能模块（v2.29 模块框架）——模块关掉时这组设置不显示。"""
    mod = next((m for m in MODULES if m["id"] == module_id), None)
    if not mod:
        mod = {"id": module_id, "zh": module_zh or module_id, "th": module_th or module_zh or module_id, "groups": []}
        MODULES.append(mod)
    if any(g[0] == group_title for g in mod["groups"]):
        return
    mod["groups"].append((group_title, list(fields), module_of) if module_of else (group_title, list(fields)))


SPECIAL_MODULE = {"pack_rules": "inv", "printers": "prod"}     # 设置页的特殊卡片属于哪个模块（v2.31）


def schema():
    from . import modules
    out = []
    for m in MODULES:
        if m.get("module") and not modules.enabled(m["module"]):
            continue                     # 这个大分类属于一个关掉的模块
        groups = [g for g in m["groups"] if len(g) < 3 or modules.enabled(g[2])]
        special = [x for x in m.get("special", []) if modules.enabled(SPECIAL_MODULE.get(x, "goods"))]
        out.append({"id": m["id"], "zh": m["zh"], "th": m["th"], "special": special, "summary": bool(m.get("summary")),
                    "ext": bool(m.get("ext")),
                    "groups": [{"title": g[0], "fields": [{"key": f[0], "label": f[1], "type": (f[2] if len(f) > 2 else "")} for f in g[1]]}
                               for g in groups]})
    return out
