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


def colour_cost(cfg, colours, hours, material_type=None):
    """v2.52 多色：按每种颜色的克数（含摊到这个颜色的冲刷废料 purge_g）分别算材料钱，机时按总时长（含换色时间）。
    colours = [{colour, material, grams, purge_g?}]。返回 variant_cost 一样的字段 + per_colour（每种颜色的克数、钱）。"""
    per, mat = [], 0.0
    for c in colours or []:
        g = float(c.get("grams") or 0) + float(c.get("purge_g") or 0)
        m = g * (1 + cfg["material_loss_rate"]) * thb_per_gram(cfg, c.get("material") or material_type)
        mat += m
        per.append({"colour": c.get("colour") or "", "material": c.get("material") or material_type or "",
                    "grams": round(float(c.get("grams") or 0), 1), "purge_g": round(float(c.get("purge_g") or 0), 1), "cost": round(m, 2)})
    machine = float(hours or 0) * machine_hour_cost(cfg)
    packaging = cfg["packaging_per_item"]
    failure = (mat + machine) * cfg["failure_rate"]
    return {"material": round(mat, 2), "machine": round(machine, 2), "packaging": round(packaging, 2), "failure": round(failure, 2),
            "total": round(mat + machine + packaging + failure, 2), "per_colour": per,
            "purge_g": round(sum(x["purge_g"] for x in per), 1)}


def fee_rate_for(cfg, platform=None, shop=None, category=None):
    """v2.53：某平台 / 店铺 / 类目的费率（真实优先、没有就用默认；见 core/feerates.py）。出错一律退回设置里的默认扣点。"""
    try:
        from . import feerates
        return feerates.resolve(platform, shop, category, cfg)
    except Exception:  # noqa: BLE001
        from . import feerates
        pct = float(cfg.get("platform_fee_rate") or 0)
        return feerates._pack((platform or "lazada"), shop or "", category or "", {"default": {"pct": pct, "fixed": 0.0}}, "default", "default", 0, 0, None)


def price_variant(cfg, variant, markup=None, material=None, platform=None, shop=None, category=None, rate=None):
    """返回该变体的成本拆分、建议价、最终价、实际加价率和警告。
    v2.52：变体有 colour_usage（多色，打印方案算的每种颜色用量）时，材料按颜色分开算（cost.per_colour）。
    v2.53：平台费用来自费率引擎：platform / shop / category 都不给 = 默认平台（Lazada）的默认店铺；返回里多 fee（每个费用项的拆分，中 / 泰文名）。"""
    from . import feerates
    if rate is None:
        rate = fee_rate_for(cfg, platform, shop, category)
    fee = rate["pct"]
    fixed = rate["fixed"]
    mk = cfg["default_markup"] if markup in (None, "") else float(markup)
    cu = variant.get("colour_usage")
    if isinstance(cu, list) and len(cu) > 1:
        cost = colour_cost(cfg, cu, variant.get("hours"), material)
        # 克数以变体上填的为准（多色用量是打印方案算的比例）：总克数不一样时按比例缩放各颜色
        tot = sum(float(c.get("grams") or 0) + float(c.get("purge_g") or 0) for c in cu)
        g = float(variant.get("grams") or 0)
        if g and tot and abs(g - tot) > 0.05:
            k = g / tot
            cost = colour_cost(cfg, [dict(c, grams=float(c.get("grams") or 0) * k, purge_g=float(c.get("purge_g") or 0) * k) for c in cu],
                               variant.get("hours"), material)
    else:
        cost = variant_cost(cfg, variant.get("grams"), variant.get("hours"), material)
    suggested = nice_price(feerates.price_for(cost["total"], mk, rate), cfg["price_ending"])
    floor = nice_price(feerates.price_for(cost["total"], cfg["min_markup"], rate), cfg["price_ending"])
    manual_price = variant.get("manual_price")
    if manual_price not in (None, "", 0):  # 填了手动售价就以手动价为准（市场定价）
        final = float(manual_price)
    else:
        final = float(suggested)
    fb = feerates.breakdown(rate, final)
    net = final - fb["total"]
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
        "platform_fee": fb["total"],
        "fee": fb,
        "profit": round(net - cost["total"], 2),
        "actual_markup": None if actual_markup is None else round(actual_markup, 4),
        "warning": warn,
    }


def price_product(cfg, product, platform=None, shop=None):
    """整个产品每个变体的定价；类目取产品的类目（引擎按 店铺×类目 找费率）。"""
    from . import feerates
    cat = feerates.category_of(product)[0]
    rate = fee_rate_for(cfg, platform, shop, cat)
    return [price_variant(cfg, v, product.get("markup"), product.get("material"), rate=rate) for v in product.get("variants", [])]


def price_by_shop(cfg, product):
    """同一个产品在每个启用店铺的定价：[{platform, shop, rows}]。没有店铺记录时给一个默认 Lazada。"""
    from . import feerates, db
    out = []
    try:
        shops = [(r["platform"], r["name"]) for r in db.conn().execute(
            "SELECT platform, name FROM shops WHERE enabled=1 AND platform IN ('lazada','shopee') ORDER BY platform, id")]
    except Exception:  # noqa: BLE001
        shops = []
    for plat, name in shops or [("lazada", "")]:
        out.append({"platform": plat, "shop": name, "rows": price_product(cfg, product, plat, name)})
    return out


def cost_summary(cfg):
    return {
        "thb_per_gram": round(thb_per_gram(cfg), 4),
        "machine_hour_cost": round(machine_hour_cost(cfg), 2),
        "fixed_monthly": fixed_monthly(cfg),
        "monthly_machine_hours": monthly_machine_hours(cfg),
    }
