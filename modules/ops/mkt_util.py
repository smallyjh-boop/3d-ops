"""运营分析第二期的小工具：页面文字里的数字、商品 / 店铺网址、AI 调用，以及从 ERP 取数（SKU 售价成本、平台扣点、
实际销量、生产产能）。原来分析系统的 kernel/util.py + modules/sync/costing.py，改成直接读 ERP。"""
import datetime as dt
import re
import time
from urllib.parse import urlparse

from core import db
from core.config import load_config

DAY = 86400
PLATFORMS = ("lazada", "shopee", "tiktok")
UNITS = {"k": 1000, "พัน": 1000, "千": 1000, "หมื่น": 10000, "万": 10000, "w": 10000, "แสน": 100000, "m": 1e6, "ล้าน": 1e6}


# ---------------- 文字和数字 ----------------
def parse_count(v):
    """'1.2k' → (1200, 100)；'ขายแล้ว 3.4พัน' → (3400, 100)；'1,234' → (1234, 1)。返回 (数值, 精度)。"""
    if v is None or v == "":
        return None, None
    if isinstance(v, bool):
        return None, None
    if isinstance(v, (int, float)):
        return float(v), 1
    s = str(v).lower().replace(",", "").replace(" ", "")
    m = re.search(r"(\d+(?:\.\d+)?)(k|m|w|พัน|หมื่น|แสน|ล้าน|万|千)?", s)
    if not m:
        return None, None
    n, unit = m.group(1), m.group(2)
    mult = UNITS.get(unit, 1)
    dec = len(n.split(".")[1]) if "." in n else 0
    return float(n) * mult, (mult / 10 ** dec if unit else 1)


def num(v):
    if v in (None, "") or isinstance(v, bool):
        return None
    try:
        return float(str(v).replace(",", "").replace("฿", "").replace("%", "").strip())
    except ValueError:
        return None


def parse_url(url):
    """商品网址 → (平台, 商品唯一键)。认不出商品编号时唯一键 = 去掉 ? 后面的网址。"""
    u = (url or "").strip()
    host = urlparse(u).netloc.lower()
    plat = next((p for p in PLATFORMS if p in host), "")
    if "shp.ee" in host:
        plat = "shopee"
    if plat == "lazada":
        m = re.search(r"-i(\d+)(?:-s\d+)?\.html", u) or re.search(r"[?&]itemId=(\d+)", u)
        if m:
            return plat, f"lazada:{m.group(1)}"
    if plat == "shopee":
        m = re.search(r"-i\.(\d+)\.(\d+)", u) or re.search(r"/product/(\d+)/(\d+)", u)
        if m:
            return plat, f"shopee:{m.group(1)}.{m.group(2)}"
    if plat == "tiktok":
        m = re.search(r"/product/(\d+)", u)
        if m:
            return plat, f"tiktok:{m.group(1)}"
    return plat, (u.split("?")[0] if u else "")


def card_numbers(text):
    """商品卡片 / 页面文字里的售价、已售、评价数（只认最常见的写法；没配 AI 时用，结果要人工核对）。"""
    text = text or ""
    out = {}
    m = (re.search(r"(?:ขายแล้ว|ขายได้|ขาย|sold|已售)\s*([\d.,]+\s*(?:k|K|พัน|หมื่น|万|千)?\+?)", text)
         or re.search(r"([\d.,]+\s*(?:k|K|พัน|หมื่น)?\+?)\s*(?:sold|ชิ้น\s*ขายแล้ว)", text))
    if m:
        out["sold_text"] = m.group(1).replace(" ", "").rstrip("+")
    m = re.search(r"฿\s*([\d,]+(?:\.\d+)?)", text)
    if m:
        out["price"] = num(m.group(1))
    m = re.search(r"([\d.,]+\s*(?:k|K|พัน)?)\s*(?:ratings|rating|reviews|คะแนน|รีวิว|评价)", text)
    if m:
        out["reviews"] = m.group(1).replace(" ", "")
    return out


def clean_img(u):
    """只存 http(s) 图片地址（平台的图床）；data: 和别的东西不存。"""
    u = str(u or "").strip()
    if not u.startswith(("http://", "https://")) or len(u) > 600:
        return None
    return u


def today():
    return dt.date.today()


def day_of(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def day_start_ts(d):
    return dt.datetime.combine(d, dt.time()).timestamp()


def tf(v, d):
    """设置里的数字（文字也行）。"""
    try:
        return float(v) if v not in (None, "") else d
    except (TypeError, ValueError):
        return d


def ti(v, d):
    return int(tf(v, d))


# ---------------- AI（用 ERP 的 AI 设置：设置 → AI） ----------------
class AiError(Exception):
    pass


def ai_on(cfg=None):
    from core import ai
    return ai.ready(cfg or load_config(), "ops")


def ai_json(cfg, system, user):
    """调用 ERP 的 AI（core.ai_copy.call），要求只回 JSON。返回 dict；出错抛 AiError。"""
    from core import ai_copy
    if not ai_on(cfg):
        raise AiError("还没设置 AI：到「设置 → AI」填接口密钥")
    try:
        txt = ai_copy.call(ai_copy.tcfg(cfg, "ops"), system, user)
        r = ai_copy.extract_json(txt)
    except ai_copy.AIError as e:
        raise AiError(str(e)) from e
    except Exception as e:  # noqa: BLE001  网络等
        raise AiError(f"AI 调用失败：{e}") from e
    if not isinstance(r, dict):
        raise AiError("AI 返回的不是 JSON 对象")
    return r


# ---------------- ERP 数据 ----------------
def sku_rows(cfg=None):
    """{SKU: {sku, product_id, name, variant, price, floor_price, unit_cost, grams, hours, material, draft, active}}（和产品页同一个定价）。"""
    from .dash import price_rows
    out = {}
    for r in price_rows(cfg):
        out[r["sku"]] = {k: r[k] for k in ("sku", "product_id", "name", "variant", "price", "floor_price", "unit_cost", "grams", "hours",
                                           "draft", "active")}
        out[r["sku"]]["material"] = (r.get("product") or {}).get("material") or ""
        out[r["sku"]]["title_th"] = (r.get("product") or {}).get("title_th") or ""
    return out


def sku_options(cfg=None):
    return [{"sku": s["sku"], "name": s["name"], "color": s["variant"]} for s in sku_rows(cfg).values() if not s["draft"]]


def fee_rate(platform, cfg=None):
    """平台扣点 (比例, 来源中文, 来源泰文)。Lazada 优先用第一期拉下来的财务流水算出的真实扣点（近 30 天商品金额 ≥ ฿1,000 才用）。"""
    cfg = cfg or load_config()
    plat = (platform or "lazada").lower()
    if plat == "lazada":
        try:
            from . import lazada
            f = lazada.fee_rates(30)
            if f.get("rate") is not None and (f.get("item_amount") or 0) >= 1000:
                return round(f["rate"] / 100, 4), "Lazada 财务流水的真实扣点（近 30 天）", "ค่าธรรมเนียมจริงจากรายการการเงิน Lazada (30 วัน)"
        except Exception:  # noqa: BLE001
            pass
    if plat == "shopee" and tf(cfg.get("shopee_fee_rate"), 0):
        return tf(cfg.get("shopee_fee_rate"), 0), "设置里的 Shopee 扣点", "ค่าธรรมเนียม Shopee ที่ตั้งไว้"
    return tf(cfg.get("platform_fee_rate"), 0.2), "设置里的平台扣点", "ค่าธรรมเนียมแพลตฟอร์มที่ตั้งไว้"


def unit_cost(grams, hours, resin=False, cfg=None):
    """按 ERP 的成本参数（设置 → 成本）算一件的生产成本：材料 + 机时 + 包材 + 失败损耗。克数和时长都要有。"""
    from core import pricing
    if not grams or not hours:
        return None
    cfg = cfg or load_config()
    try:
        return pricing.variant_cost(cfg, grams, hours, "RESIN" if resin else None)["total"]
    except Exception:  # noqa: BLE001
        return None


def _excl():
    from core.finance import EXCLUDE
    return EXCLUDE


def sku_daily(sku, platform, since):
    """{日期: 件数}：ERP 订单里这个 SKU 每天卖了几件（不算取消 / 退货 / 未付款 / 报价 / 拒收）。platform 空 = 全部平台。"""
    ex = _excl()
    q = (f"SELECT o.order_time t, i.qty q FROM order_items i JOIN orders o ON o.id=i.order_id "
         f"WHERE UPPER(i.sku)=? AND o.order_time>=? AND o.status NOT IN ({','.join('?' * len(ex))})")
    args = [str(sku or "").upper(), since, *ex]
    if platform:
        q += " AND LOWER(o.platform)=?"
        args.append(platform.lower())
    out = {}
    for r in db.conn().execute(q, args):
        d = day_of(r["t"] or 0)
        out[d] = out.get(d, 0) + (r["q"] or 1)
    return out


def sku_avg_daily(sku, platform, days):
    since = day_start_ts(today() - dt.timedelta(days=days - 1))
    return round(sum(sku_daily(sku, platform, since).values()) / max(1, days), 2)


def sku_money(sku, platform, since, cfg=None):
    """这个 SKU 从 since 起的销售额和利润（利润按 core.finance.order_profit 按商品金额比例分摊，和财务一样）。"""
    from .dash import profits
    rev = prof = 0.0
    k = str(sku or "").upper()
    for o, its, p in profits(since, cfg=cfg):
        if platform and (o["platform"] or "").lower() != platform.lower():
            continue
        tot = sum((i["item_total"] or 0) for i in its)
        for i in its:
            if str(i["sku"] or "").upper() != k:
                continue
            rev += i["item_total"] or 0
            share = (i["item_total"] or 0) / tot if tot else 1 / max(1, len(its))
            prof += p["profit"] * share
    return round(rev, 2), round(prof, 2)


def capacity(cfg=None):
    """生产产能（生产模块的打印机和排队）：每天能打几小时、现在排了几小时的活。生产模块关着时只按设置估。"""
    from core import modules
    cfg = cfg or load_config()
    printers = cfg.get("printers") or []
    n_on = sum(1 for p in printers if isinstance(p, dict) and p.get("enabled", True) is not False)
    n = n_on or tf(cfg.get("printer_count"), 0)
    hours = n * tf(cfg.get("hours_per_day_each"), 0)
    queue = 0.0
    prod_on = not modules.is_loaded() or modules.enabled("prod")
    if prod_on:
        try:
            r = db.conn().execute("SELECT SUM((qty-COALESCE(qty_done,0))*COALESCE(hours_each,0)) h FROM jobs WHERE status='todo'").fetchone()
            queue = float(r["h"] or 0)
        except Exception:  # noqa: BLE001  还没有生产表
            queue = 0.0
    return {"printers": n, "hours_per_day": round(hours, 1), "queue_hours": round(queue, 1), "from_prod": bool(prod_on and n_on)}


def capacity_hours(cfg=None):
    return capacity(cfg)["hours_per_day"] or None


def orders_daily_30d():
    """近 30 天每天平均几单（计入销售的）。"""
    ex = _excl()
    since = day_start_ts(today() - dt.timedelta(days=29))
    n = db.conn().execute(f"SELECT COUNT(*) FROM orders WHERE order_time>=? AND status NOT IN ({','.join('?' * len(ex))})",
                          (since, *ex)).fetchone()[0]
    return round(n / 30.0, 2)


def avg_hours_per_order(cfg=None):
    """近 30 天平均每单要打印几小时（订单商品 × SKU 打印时长）；订单少于 5 单时用设置里的默认值。"""
    cfg = cfg or load_config()
    ex = _excl()
    since = day_start_ts(today() - dt.timedelta(days=29))
    skus = {k: (v["hours"] or 0) for k, v in sku_rows(cfg).items()}
    per = {}
    for r in db.conn().execute(f"SELECT o.id, UPPER(i.sku) sku, i.qty FROM order_items i JOIN orders o ON o.id=i.order_id "
                               f"WHERE o.order_time>=? AND o.status NOT IN ({','.join('?' * len(ex))})", (since, *ex)):
        per[r["id"]] = per.get(r["id"], 0) + skus.get(r["sku"] or "", 0) * (r["qty"] or 1)
    vals = [v for v in per.values() if v > 0]
    if len(vals) >= 5:
        return round(sum(vals) / len(vals), 2), True
    return tf(cfg.get("oa_avg_hours_per_order"), 2.0), False


def now():
    return time.time()
