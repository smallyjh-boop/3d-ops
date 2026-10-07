"""配置读写：所有可调参数都在 data/config.json，界面「设置」页可改。"""
import copy
import re
import json
import os

from .codes import DEFAULT_COLORS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("LH_DATA_DIR") or os.path.join(BASE_DIR, "data")   # NAS/Docker 里指向数据卷
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULT_CONFIG = {
    # ---------- 成本 ----------
    "filament_price_cny_per_kg": 58.0,   # 耗材价格（人民币/公斤）
    "cny_to_thb": 4.5,                   # 人民币兑泰铢汇率，请按实际汇率修改
    "material_loss_rate": 0.10,          # 支撑、废料、试打损耗
    "electricity_thb_per_kwh": 5.0,
    "printer_avg_kw": 0.15,              # 每台打印时平均功率（千瓦）
    "monthly_rent": 4000.0,
    "monthly_labor": 9000.0,
    "monthly_depreciation": 2500.0,      # 设备折旧（三台约6万铢/24个月）
    "monthly_maintenance": 500.0,        # 喷嘴、热床板、皮带等
    "printer_count": 3,
    "hours_per_day_each": 8.0,           # 每台每天平均打印小时（开机率），越高摊到每件的固定成本越低
    "failure_rate": 0.05,                # 失败重打的比例
    "packaging_per_item": 10.0,          # 每件包材（泰铢）
    "packaging_weight_g": 50,            # 包材重量（克），算包裹重量用
    # ---------- 定价 ----------
    "platform_fee_rate": 0.20,           # 平台扣点占位值（Lazada），请到卖家后台核实后修改
    "shopee_fee_rate": 0.0,              # Shopee 扣点，0 = 和 Lazada 一样
    "default_markup": 1.0,               # 默认加价率：1.0 = 利润等于成本（100%）
    "min_markup": 1.0,                   # 低于这个加价率会标红警告
    "price_ending": 9,                   # 价格尾数，填 -1 表示不做尾数处理
    "discount_display_rate": 0.0,        # >0 时自动生成划线价，例如 0.3 = 原价按七折显示
    # ---------- 上新默认值 ----------
    "brand": "No Brand",
    "copy_mention_lead_time": False,     # 文案里写发货天数（默认不写）
    "lead_time_days": 3,                 # 发货天数（开启上面一项时写进文案）
    "copy_mention_custom": True,         # 文案里写“可定制”
    "copy_mention_wholesale": True,      # 文案里写“可批发”
    "default_stock": 50,                 # 按单生产，库存只是可售数量
    # ---------- 按耗材自动算库存（v2.16） ----------
    "stock_auto": False,                 # 总开关：开了以后，变体库存按「这个颜色剩下的耗材能做几件」算（产品里可以单独开关）
    "stock_cap": 50,                     # 库存上限（够做再多也只显示这么多）
    "stock_low_line": 3,                 # 能做的件数低于这个数时……
    "stock_low_mode": "zero",            # ……zero = 直接显示 0（防止缺料卖出）；real = 显示真实件数
    "stock_min_change": 3,               # 变化够几件才算「要同步到平台」（防止每打一单就改一次）
    "stock_loss_factor": 1.1,            # 单件克数 × 这个系数（支撑、失败损耗）
    "stock_safety_g": 50,                # 每个颜色留这么多克不算（卷尾不好用）
    "random_color_auto": True,           # 加颜色时每个规格自动加一个「随机颜色」
    # ---------- 库存管理（v2.17） ----------
    "inv_loss_rate": 0.05,               # 打印扣料时多扣的损耗（0.05 = 产品克数的 5%），每个耗材物品可以单独设
    "inv_categories": [],                # 自己加的物品分类（中文名），内置：耗材 / 备件 / 包材 / 成品 / 工具 / 其他
    "inv_pack_auto": False,              # 订单发货时自动扣包材（v2.18）
    "inv_pack_rules": [],
    "fin_vat_on": False,                 # 财务（v2.21）：VAT 开关（还没注册 VAT 就关着；Lazada 等已经代扣的不用管）
    "fin_vat_rate": 0.07,
    "fin_prices_incl_vat": True,         # 商品售价含 VAT（泰国零售一般含税）
    "fin_settle_days": 14,               # 发货 / 完成多少天还没回款算「超时未回款」
    "fin_settle_tolerance": 5,           # 平台实际扣费比按扣点估算的多出多少铢才列出来
    "fin_fixed_cats": ["房租", "人工工资", "设备折旧"],   # 这些支出分类算固定费用（本期没记账时按成本设置估算）
    "fin_expense_cats": [],              # 自己加的支出分类
    "accel_on": True,                    # 电脑加速（v2.20）：有电脑在线时把切片、读大模型、抠图交给电脑做
    "accel_local_slots": 1,              # NAS 自己做重活时同时最多几个（其余排队）
    "accel_claim_wait": 8,               # 电脑几秒内没接手（都在忙）就 NAS 自己做
    "inv_presets_done": False,           # 常用物品清单建过了（v2.19.1，第一次启动自动建）                # 扣哪些包材：[{item_id, qty, per: order 每单 / item 每件}]
    "sku_prefix": "3DP",
    "shop_name_th": "",
    # ---------- AI 文案 ----------
    "ai_provider": "anthropic",          # anthropic 或 openai_compatible（DeepSeek/通义/OpenAI 等）
    "ai_api_key": "",
    "ai_model": "claude-sonnet-5-5",
    "ai_base_url": "https://api.deepseek.com",  # 仅 openai_compatible 使用
    # ---------- 图片 ----------
    "image_size": 1200,
    "image_fill_ratio": 0.85,            # 去背景后产品占画面比例（Lazada 要求 70% 以上）
    "filament_lead_days": 10,            # 耗材从下单到收货大约几天
    "filament_safety_days": 5,           # 安全库存（多备几天）
    "filament_cover_days": 30,           # 每次补货够用几天
    "filament_spool_kg": 1.0,            # 每卷几公斤
    "ops_write_mode": "auto",            # 运营分析系统写回：auto = 自动生效；confirm = 只做建议，人工确认后生效
    "resin_thb_per_kg": 800,             # 树脂每公斤价格（铢）
    "resin_extra_rate": 0.15,            # 树脂额外耗材：清洗酒精、离型膜、手套等，按树脂成本的比例
    "resin_density": 1.1,                # 树脂密度（克/毫升），切片软件给的是毫升时换算成克
    "resin_plate_hours": 3,              # 光固化没有切片文件时，按每盘几小时估算
    "backup_copy_dir": "",               # 每天备份后另存一份到这个文件夹（U 盘 / 网盘同步文件夹）
    "default_ship_days": 2,              # 订单没有最晚发货时间、商品也没填发货天数时，按下单后几天算
    "stock_cover_days": 7,               # 成品备货：常备几天的销量
    "stock_min_sold30": 3,               # 近 30 天卖了几个以上才建议备货
    "curator_base_url": "",              # 3D选品工具地址，例如 http://192.168.31.200:18765（推送里的图片是相对地址时用）
    "curator_api_key": "",               # 选品工具发给 ERP 的密钥（ERP 下载选品工具里的图片 / 模型文件用）
    "login_days": 30,                    # 记住登录几天（期间每次打开都会自动续期；改了要重启后生效）
    # ---------- v2.26 外网访问 / 在线更新 ----------
    "remote_url": "",                    # 外网地址（Tailscale），例如 http://100.81.34.58:8790；手机 / 电脑装 Tailscale 登录同一账号后用
    "update_repo": "smallyjh-boop/3d-ops",   # 在线更新：GitHub 仓库（拥有者/仓库名）
    "update_token": "",                  # 在线更新：GitHub 只读令牌（私有仓库要；只存在 NAS 上，不会发回浏览器）
    "update_check": True,                # 每天自动检查有没有新版本（只检查，不会自己升级）
    # ---------- v2.11 审单 / 物流 / 售后 ----------
    "review_enabled": True,              # 新订单自动审单：命中下面的规则就「挂起」，人工审核后才排产
    "review_amount_over": 1500,          # 订单金额 ≥ 这个数要人工看（0 = 不检查）
    "review_keywords": "定制,改颜色,换颜色,刻字,印字,加字,改尺寸,custom,ใส่ชื่อ,สั่งทำ,เปลี่ยนสี,สลัก,แกะชื่อ,ขอสี",
    "review_cod_new_over": 500,          # 货到付款 + 第一次买 + 金额 ≥ 这个数（0 = 不检查）
    "review_duplicate_hours": 24,        # 同一买家几小时内买了一样的东西，可能重复下单（0 = 不检查）
    "carrier_lazada": "Lazada Express (LEX)",   # 订单没写物流公司时用的默认值（平台物流）
    "carrier_shopee": "SPX Express",
    "carrier_tiktok": "J&T Express",
    "ship_method_default": "pickup",     # 平台物流：pickup 上门揽收 / dropoff 送到网点
    "as_due_hours": 48,                  # 售后默认处理期限（小时，平台一般 48 小时内要回应）
    "as_return_days": 14,                # 等买家寄回 / 拒收包裹退回，默认等几天
    "sender_name": "",                   # 自制面单：寄件人
    "sender_phone": "",
    "sender_address": "",
    "image_provider": "openai",          # 场景图 AI：openai（gpt-image-1 及兼容接口）或 gemini
    "image_api_key": "",
    "image_api_base": "",                # 留空 = 官方地址
    "image_model": "",                   # 留空 = gpt-image-1-mini / gemini-3.1-flash-lite-image（最便宜）
    "image_quality": "medium",           # openai：low / medium / high（越高越贵）
    "imgbb_api_key": "",                 # 图床，免费申请：https://api.imgbb.com/
    # ---------- 打印机与切片 ----------
    "printers": [
        {"name": "Bambu Lab P1S", "g_per_h": 22, "orca_machine": "", "orca_process": "", "orca_filament": ""},
        {"name": "Creality K1 Max", "g_per_h": 20, "orca_machine": "", "orca_process": "", "orca_filament": ""},
        {"name": "Creality K1C", "g_per_h": 18, "orca_machine": "", "orca_process": "", "orca_filament": ""},
    ],
    "default_printer": 0,
    "orca_path": "",                     # 留空自动查找 orca-slicer.exe
    "est_infill": 0.15,                  # 估算用：填充率
    "est_shell_mm": 1.0,                 # 估算用：外壁+顶底等效厚度（毫米）
    "est_support_factor": 1.08,          # 估算用：支撑/裙边损耗
    "est_overhead_h": 0.15,              # 估算用：每次打印的预热/换料时间（小时）
    "est_calibration": 1.0,              # 用真实切片结果自动校准，不用手动改
    "est_calibration_n": 0,
    "est_calibration_by_mat": {},          # v2.15：按材料的克数校准系数（质量统计 → 估算校准 里应用）
    "risk_thresholds": {},                 # v2.15：空打风险阈值（空 = 默认值，见 core/calib.py）
    # ---------- 编码 ----------
    "color_table": [list(r) for r in DEFAULT_COLORS],  # 中文, 代码, 泰文, 英文
    # ---------- Lazada 类目属性记忆（手动改过的值，按类目ID保存） ----------
    "category_memory": {},
    "shopee_cat_map": {},                # Lazada 类目ID → Shopee 类目ID（确认过的对应关系）
    "template_defaults": {},  # v0.1 导出页记住的默认值（兼容保留）
}


LIST_KEYS = ("inv_categories", "fin_fixed_cats", "fin_expense_cats")   # 设置页「逗号分隔」的文字列表


def _fix_lists(cfg):
    """v2.22.1：列表型设置如果被存成了字符串（旧版保存财务设置的 bug），读的时候拆回列表。"""
    for k in LIST_KEYS:
        v = cfg.get(k)
        if v is None:
            cfg[k] = list(DEFAULT_CONFIG.get(k) or [])
        elif not isinstance(v, list):
            cfg[k] = [x.strip() for x in re.split(r"[,，、\n]", str(v)) if x.strip()]
    return cfg


def load_config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
        if not cfg.get("_ship48"):
            # v2.7：店铺承诺 24–48 小时发货，旧的默认 3 天改成 2 天（只改一次，之后按你设置的）
            if int(cfg.get("default_ship_days") or 3) == 3:
                cfg["default_ship_days"] = 2
            cfg["_ship48"] = True
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                raw.update(default_ship_days=cfg["default_ship_days"], _ship48=True)
                with open(CONFIG_PATH + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)
                os.replace(CONFIG_PATH + ".tmp", CONFIG_PATH)
            except (OSError, json.JSONDecodeError):
                pass
    # v2.7：每台打印机要有机器编码（P1S-01 …）和启用开关
    prs = cfg.get("printers")
    if isinstance(prs, list) and prs:
        from . import fleet
        if fleet.ensure_codes(prs) and os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw.get("printers"), list) and len(raw["printers"]) == len(prs):
                    raw["printers"] = prs
                    with open(CONFIG_PATH + ".tmp", "w", encoding="utf-8") as f:
                        json.dump(raw, f, ensure_ascii=False, indent=2)
                    os.replace(CONFIG_PATH + ".tmp", CONFIG_PATH)
            except (OSError, json.JSONDecodeError):
                pass
    return _fix_lists(cfg)


def save_config(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    merged = load_config()
    merged.update(cfg)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)
    return merged
