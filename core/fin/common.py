"""财务模块共用的小工具：期间、设置。"""
import datetime as dt

from ..config import load_config


def settings(cfg=None):
    cfg = cfg or load_config()

    def f(k, d):
        try:
            return float(cfg.get(k) if cfg.get(k) not in (None, "") else d)
        except (TypeError, ValueError):
            return d
    return {"vat_on": bool(cfg.get("fin_vat_on", False)), "vat_rate": f("fin_vat_rate", 0.07),
            "incl_vat": bool(cfg.get("fin_prices_incl_vat", True)), "settle_days": int(f("fin_settle_days", 14)),
            "tolerance": f("fin_settle_tolerance", 5), "fixed_cats": list(cfg.get("fin_fixed_cats") or ["房租", "人工工资", "设备折旧"])}


def month_range(month):
    y, m = (int(x) for x in str(month).split("-")[:2])
    s = dt.date(y, m, 1)
    e = dt.date(y + (m == 12), m % 12 + 1, 1)
    return s, e


def period(month=None, start=None, end=None):
    """返回 (开始日期, 结束日期（不含）, 说明)。默认本月。日期都是 date。"""
    if start:
        s = dt.date.fromisoformat(str(start)[:10])
        e = dt.date.fromisoformat(str(end)[:10]) + dt.timedelta(days=1) if end else dt.date.today() + dt.timedelta(days=1)
        return s, e, f"{s.isoformat()} ~ {(e - dt.timedelta(days=1)).isoformat()}"
    month = month or dt.date.today().strftime("%Y-%m")
    s, e = month_range(month)
    return s, e, month


def ts(d):
    return dt.datetime(d.year, d.month, d.day).timestamp()


def day_of(t):
    return dt.datetime.fromtimestamp(t).strftime("%Y-%m-%d")


def r2(v):
    return round(float(v or 0), 2)
