"""定价：成本 = 材料 + 机时 + 包材 + 失败损耗；售价 = 成本 ×(1+加价率) ÷(1-平台扣点)。"""
import math


def thb_per_gram(cfg, material=None):
    """每克材料成本。树脂：按每公斤树脂价 + 酒精 / 离型膜 / 手套等耗材比例。"""
    from .fleet import is_resin
    if material and is_resin(material):
        return float(cfg.get("resin_thb_per_kg") or 800) / 1000.0 * (1 + float(cfg.get("resin_extra_rate") or 0.15))
    return cfg["filament_price_cny_per_kg"] * cfg["cny_to_thb"] / 1000.0


def fixed_monthly(cfg):
    return (cfg["monthly_rent"] + cfg["monthly_labor"]
            + cfg["monthly_depreciation"] + cfg["monthly_maintenance"])


def monthly_machine_hours(cfg):
    return max(1.0, cfg["printer_count"] * cfg["hours_per_day_each"] * 30)


def machine_hour_cost(cfg):
    """每打印小时成本 = 电费 + 固定成本按机时分摊。"""
    power = cfg["printer_avg_kw"] * cfg["electricity_thb_per_kwh"]
    return power + fixed_monthly(cfg) / monthly_machine_hours(cfg)


def nice_price(x, ending):
    n = math.ceil(x)
    if ending is None or ending < 0:
        return n
    r = n - n % 10 + ending
    return r if r >= n else r + 10


def variant_cost(cfg, grams, hours, material_type=None):
    grams = float(grams or 0)
    hours = float(hours or 0)
    material = grams * (1 + cfg["material_loss_rate"]) * thb_per_gram(cfg, material_type)
    machine = hours * machine_hour_cost(cfg)
    packaging = cfg["packaging_per_item"]
    failure = (material + machine) * cfg["failure_rate"]
    total = material + machine + packaging + failure
    return {
        "material": round(material, 2),
        "machine": round(machine, 2),
        "packaging": round(packaging, 2),
        "failure": round(failure, 2),
        "total": round(total, 2),
    }


def price_variant(cfg, variant, markup=None, material=None):
    """返回该变体的成本拆分、建议价、最终价、实际加价率和警告。"""
    fee = cfg["platform_fee_rate"]
    mk = cfg["default_markup"] if markup in (None, "") else float(markup)
    cost = variant_cost(cfg, variant.get("grams"), variant.get("hours"), material)
    suggested = nice_price(cost["total"] * (1 + mk) / (1 - fee), cfg["price_ending"])
    floor = nice_price(cost["total"] * (1 + cfg["min_markup"]) / (1 - fee), cfg["price_ending"])
    manual_price = variant.get("manual_price")
    if manual_price not in (None, "", 0):  # 填了手动售价就以手动价为准（市场定价）
        final = float(manual_price)
    else:
        final = float(suggested)
    net = final * (1 - fee)
    actual_markup = (net - cost["total"]) / cost["total"] if cost["total"] > 0 else None
    warn = ""
    if not variant.get("grams") or not variant.get("hours"):
        warn = "缺少克数或打印时长"
    elif actual_markup is not None and actual_markup < cfg["min_markup"] - 1e-9:
        warn = f"加价率低于最低要求 {cfg['min_markup']:.0%}"
    list_price = final
    rate = cfg.get("discount_display_rate") or 0
    if rate > 0:
        list_price = nice_price(final / (1 - rate), cfg["price_ending"])
    return {
        "cost": cost,
        "suggested_price": suggested,
        "floor_price": floor,
        "final_price": round(final, 2),
        "list_price": round(list_price, 2),
        "special_price": round(final, 2) if rate > 0 else None,
        "platform_fee": round(final * fee, 2),
        "profit": round(net - cost["total"], 2),
        "actual_markup": None if actual_markup is None else round(actual_markup, 4),
        "warning": warn,
    }


def price_product(cfg, product):
    return [price_variant(cfg, v, product.get("markup"), product.get("material")) for v in product.get("variants", [])]


def cost_summary(cfg):
    return {
        "thb_per_gram": round(thb_per_gram(cfg), 4),
        "machine_hour_cost": round(machine_hour_cost(cfg), 2),
        "fixed_monthly": fixed_monthly(cfg),
        "monthly_machine_hours": monthly_machine_hours(cfg),
    }
