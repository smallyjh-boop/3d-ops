"""营销日历（第二期，从运营分析系统 modules/campaigns 搬过来）：泰国电商的固定节奏（每月双数日大促、月中、发薪日、节日）
+ 自己加的活动，倒排任务（活动前 14 天到活动后 3 天），大促产能检查（用生产模块的打印机和排队）。

内置规则是按平台惯例推算的，具体日期和报名截止以卖家中心公告为准；可以在页面上隐藏内置活动、加自定义活动。
要专门准备的活动（双数日大促、节日、自己加的）当天的任务进「今日待办」。
"""
import datetime as dt
import time

from core.config import load_config

from . import mkt_db
from .mkt_util import avg_hours_per_order, capacity, orders_daily_30d, tf, ti, today

ALL = "lazada,shopee,tiktok"
BIG = ("double", "custom", "festival")     # 要专门准备的活动（月中、发薪日只在日历里显示）
# 任务倒排（相对活动开始日；正数 = 活动结束后几天）
TASKS = [(-14, "选品并报名平台活动（成长 / 主推的款优先）", "เลือกสินค้าและสมัครแคมเปญของแพลตฟอร์ม (สินค้ากำลังโต / สินค้าหลักก่อน)"),
         (-7, "设置活动价和店铺券，核对活动价下的利润；检查产能和耗材", "ตั้งราคาแคมเปญและคูปองร้าน ตรวจกำไรที่ราคาแคมเปญ ตรวจกำลังผลิตและวัสดุ"),
         (-3, "预热：店铺券上线、商品标题加活动词；提前打一些主推款", "อุ่นเครื่อง: เปิดคูปองร้าน ใส่คำแคมเปญในชื่อสินค้า พิมพ์สินค้าหลักเตรียมไว้"),
         (0, "活动当天：每 2 小时看一次订单和发货；挂起的订单尽快审核", "วันแคมเปญ: ดูออเดอร์และการส่งทุก 2 ชั่วโมง ตรวจออเดอร์ที่รอให้เร็ว"),
         (3, "复盘：看各商品活动期间的订单和利润，决定谁升为主推", "สรุปผล: ดูออเดอร์และกำไรช่วงแคมเปญ เลือกสินค้าที่จะเป็นสินค้าหลัก")]
FESTIVALS = [(2, 14, 14, "情人节", "วาเลนไทน์", 1.5), (4, 13, 15, "宋干节（泼水节）", "สงกรานต์", 1.5),
             (8, 12, 12, "泰国母亲节", "วันแม่", 1.5), (12, 5, 5, "泰国父亲节", "วันพ่อ", 1.5),
             (12, 25, 25, "圣诞节", "คริสต์มาส", 1.5), (12, 31, 31, "新年", "ปีใหม่", 1.5)]


def _c():
    return mkt_db.conn()


def _builtin(year):
    ev = []
    for m in range(1, 13):
        big = m in (11, 12)
        ev.append({"key": f"dd-{year}-{m}", "name": f"{m}.{m} 大促" + ("（全年最大）" if m == 11 else ""),
                   "name_th": f"แคมเปญ {m}.{m}" + (" (ใหญ่ที่สุดของปี)" if m == 11 else ""),
                   "start": dt.date(year, m, m), "end": dt.date(year, m, m), "multiplier": 5.0 if big else 3.0, "platforms": ALL, "kind": "double"})
        ev.append({"key": f"mid-{year}-{m}", "name": f"{m} 月月中促销", "name_th": f"โปรกลางเดือน {m}", "start": dt.date(year, m, 15),
                   "end": dt.date(year, m, 15), "multiplier": 1.8, "platforms": ALL, "kind": "mid"})
        last = (dt.date(year + (m == 12), (m % 12) + 1, 1) - dt.timedelta(days=1)).day
        ev.append({"key": f"pay-{year}-{m}", "name": f"{m} 月发薪日促销", "name_th": f"โปรเงินเดือนออก เดือน {m}", "start": dt.date(year, m, 25),
                   "end": dt.date(year, m, min(last, 28)), "multiplier": 1.5, "platforms": ALL, "kind": "payday"})
    for (mm, d1, d2, name, name_th, mult) in FESTIVALS:
        ev.append({"key": f"fest-{year}-{mm}-{d1}", "name": name, "name_th": name_th, "start": dt.date(year, mm, d1), "end": dt.date(year, mm, d2),
                   "multiplier": mult, "platforms": ALL, "kind": "festival"})
    return ev


def hidden():
    return {r[0] for r in _c().execute("SELECT hidden_key FROM ops_campaigns WHERE hidden_key IS NOT NULL")}


def custom():
    out = []
    for r in _c().execute("SELECT * FROM ops_campaigns WHERE hidden_key IS NULL ORDER BY start_day"):
        try:
            out.append({"key": f"c-{r['id']}", "id": r["id"], "name": r["name"], "name_th": r["name"], "platforms": r["platforms"] or ALL,
                        "start": dt.date.fromisoformat(r["start_day"]), "end": dt.date.fromisoformat(r["end_day"] or r["start_day"]),
                        "multiplier": r["multiplier"] or 3.0, "note": r["note"] or "", "kind": "custom"})
        except (TypeError, ValueError):
            continue
    return out


def add(name, start_day, end_day="", platforms=ALL, multiplier=3.0, note=""):
    try:
        s = dt.date.fromisoformat(str(start_day))
        e = dt.date.fromisoformat(str(end_day)) if end_day else s
    except ValueError as ex:
        raise ValueError("日期不对（要 YYYY-MM-DD）") from ex
    if e < s:
        raise ValueError("结束日期不能早于开始日期")
    c = _c()
    c.execute("INSERT INTO ops_campaigns(name, platforms, start_day, end_day, multiplier, note, created_at) VALUES(?,?,?,?,?,?,?)",
              ((name or "").strip()[:60] or "活动", platforms or ALL, s.isoformat(), e.isoformat(), tf(multiplier, 3.0) or 3.0, (note or "")[:200], time.time()))
    c.commit()


def remove(key):
    c = _c()
    key = str(key or "")
    if key.startswith("c-") and key[2:].isdigit():
        c.execute("DELETE FROM ops_campaigns WHERE id=?", (int(key[2:]),))
    elif key:
        c.execute("INSERT INTO ops_campaigns(hidden_key, created_at) VALUES(?,?)", (key, time.time()))
    c.commit()


def restore_all():
    _c().execute("DELETE FROM ops_campaigns WHERE hidden_key IS NOT NULL")
    _c().commit()


def capacity_check(cfg=None):
    """打印机每天能做多少单：产能（生产模块的打印机 × 每台每天小时）÷ 近 30 天平均每单打印小时；活动当天按承诺发货时间算可以用几天的产能，
    但要先做完现在排队的。"""
    cfg = cfg or load_config()
    cp = capacity(cfg)
    cap_h = cp["hours_per_day"]
    avg_h, from_hist = avg_hours_per_order(cfg)
    window_days = ti(cfg.get("oa_ship_window_hours"), 48) / 24.0
    return {"capacity_hours_per_day": cap_h, "printers": cp["printers"], "from_prod": cp["from_prod"],
            "avg_hours_per_order": round(avg_h, 2), "avg_from_history": from_hist,
            "max_orders_per_day": int(cap_h / avg_h) if avg_h and cap_h else None,
            "max_orders_campaign_day": int(max(0, cap_h * window_days - cp["queue_hours"]) / avg_h) if avg_h and cap_h else None,
            "baseline_daily_orders": orders_daily_30d(), "queue_hours": cp["queue_hours"]}


def upcoming(cfg=None, days=None):
    cfg = cfg or load_config()
    days = days or ti(cfg.get("oa_campaign_lookahead_days"), 60)
    td = today()
    hid = hidden()
    evs = [e for y in (td.year, td.year + 1) for e in _builtin(y) if e["key"] not in hid] + custom()
    cap = capacity_check(cfg)
    out = []
    for e in evs:
        if e["end"] < td - dt.timedelta(days=3) or (e["start"] - td).days > days:
            continue
        expect = round(cap["baseline_daily_orders"] * e["multiplier"], 1)
        tasks = []
        for off, text, text_th in TASKS:
            d = e["start"] + dt.timedelta(days=off) if off <= 0 else e["end"] + dt.timedelta(days=off)
            tasks.append({"day": d.isoformat(), "offset": off, "text": text, "text_th": text_th, "done": d < td, "today": d == td})
        out.append({**{k: v for k, v in e.items() if k not in ("start", "end")}, "start": e["start"].isoformat(), "end": e["end"].isoformat(),
                    "days_left": (e["start"] - td).days, "expected_orders": expect, "need_hours": round(expect * cap["avg_hours_per_order"], 1),
                    "over_capacity": bool(cap["max_orders_campaign_day"] is not None and expect > cap["max_orders_campaign_day"]),
                    "big": e["kind"] in BIG, "tasks": tasks})
    out.sort(key=lambda x: x["start"])
    return {"events": out, "capacity": cap, "today": td.isoformat(), "hidden": len(hid)}


def big_events(cfg=None, days=30):
    return [e for e in upcoming(cfg, days=days)["events"] if e["kind"] in BIG]


def todays_tasks(cfg=None):
    """要进今日待办的活动任务：到日子的（最多往回 3 天，周末没看到也还在；点了完成 / 忽略就不再出现）。"""
    td = today()
    res = []
    for e in upcoming(cfg, 30)["events"]:
        if e["kind"] not in BIG:
            continue
        for t in e["tasks"]:
            d = dt.date.fromisoformat(t["day"])
            if td - dt.timedelta(days=3) <= d <= td:
                res.append((e, t))
    return res
