"""爆款计划 / 上量计划（第二期，从运营分析系统 modules/plans 搬过来）：目标从竞品推出来，每天用 ERP 实际订单对目标。

- 爆款计划（hero）：测款期 / 刚出单的款，把日销做到对标竞品最高日销的 30% 左右
- 上量计划（scale）：已经稳定出单的款，扩变体、多店铺、多平台，日销做到对标竞品最高日销的 60% 左右
- 不投广告：动作都是自然流量的做法（主图标题、券、活动、套餐、变体、评价跟进），利润优先；不刷单、不刷评价、不好评返现
目标曲线：起点 = 计划开始前 14 天日均，前 2/3 的天数线性爬到目标，之后保持。
分阶段任务到日子了进「今日待办」（key = ptask:<任务编号>）；在待办里点「完成」和在计划页勾掉是同一件事。
"""
import datetime as dt
import json
import time

from core import todo
from core.config import load_config

from . import mkt_db
from .mkt_util import ai_json, capacity_hours, day_start_ts, sku_avg_daily, sku_daily, sku_money, sku_rows, today

KINDS = {"hero": ("爆款计划", "แผนสร้างสินค้าขายดี"), "scale": ("上量计划", "แผนเพิ่มยอดขาย")}
RATIO = {"hero": 0.3, "scale": 0.6}
TEMPLATES = {
    "hero": [
        (0, "起步", "对标竞品：第一张主图突出卖点和尺寸，标题放进竞品标题里最常见的 3 个泰文关键词",
         "เทียบคู่แข่ง: รูปแรกเน้นจุดขายและขนาด ใส่คีย์เวิร์ดไทย 3 คำที่คู่แข่งใช้บ่อยที่สุดในชื่อ"),
        (0, "起步", "核对价格：参考竞品到手价中位数定价，到手价不能低于 ERP 最低价",
         "ตรวจราคา: ตั้งตามราคาสุทธิกลางของคู่แข่ง แต่ต้องไม่ต่ำกว่าราคาขั้นต่ำใน ERP"),
        (1, "起步", "设店铺券（满减或新客券），报名平台新品 / 包邮活动（先核对活动后的利润）",
         "ตั้งคูปองร้าน (ลดเมื่อซื้อครบ / ลูกค้าใหม่) สมัครแคมเปญสินค้าใหม่ / ส่งฟรี (ตรวจกำไรหลังเข้าแคมเปญก่อน)"),
        (3, "起步", "每单放感谢卡；发货后在聊天里提醒确认收货和评价（不送好评返现、不刷单）",
         "ใส่การ์ดขอบคุณทุกออเดอร์ หลังส่งของทักแชทเตือนกดรับสินค้าและรีวิว (ไม่แลกรีวิว ไม่ปั๊มออเดอร์)"),
        (7, "起步", "第 1 周复盘：看实际对目标；一直没出单 → 换第一张主图和标题再测",
         "สรุปสัปดาห์แรก: เทียบยอดจริงกับเป้า ถ้ายังไม่มีออเดอร์ → เปลี่ยนรูปแรกและชื่อแล้วทดสอบใหม่"),
        (10, "放量", "加颜色 / 尺寸变体或 2 件装套餐，提高客单价", "เพิ่มสี / ขนาด หรือแพ็ก 2 ชิ้น เพิ่มยอดต่อออเดอร์"),
        (14, "放量", "报名最近的大促，设活动价，核对活动价下的利润", "สมัครแคมเปญใหญ่ที่ใกล้ที่สุด ตั้งราคาแคมเปญ ตรวจกำไร"),
        (14, "放量", "同款按类目上到另一个店铺或 Shopee（标题和主图做差异）", "ลงสินค้าเดียวกันในร้านอื่นหรือ Shopee (ชื่อและรูปหลักต้องต่างกัน)"),
        (21, "冲刺", "按目标日销备耗材；卖得好的颜色提前打几件现货，缩短发货时间",
         "เตรียมวัสดุตามเป้ายอดขาย สีที่ขายดีพิมพ์เก็บไว้ก่อน ส่งของเร็วขึ้น"),
        (30, "复盘", "计划到期：达标 → 转「上量计划」；不达标 → 停止投入，模型记入失败名单",
         "ครบแผน: ถึงเป้า → เปลี่ยนเป็น「แผนเพิ่มยอดขาย」 ไม่ถึง → หยุดลงแรง บันทึกโมเดลไว้ว่าไม่สำเร็จ"),
    ],
    "scale": [
        (0, "扩款", "加变体：新颜色 / 尺寸 / 套装（看竞品卖得最好的规格）", "เพิ่มตัวเลือก: สี / ขนาด / ชุด (ดูตัวเลือกที่คู่แข่งขายดีที่สุด)"),
        (3, "铺货", "同款铺到其他类目店铺和 Shopee，标题、主图各做差异，不要完全复制",
         "ลงสินค้าเดียวกันในร้านอื่นและ Shopee ชื่อและรูปหลักต้องต่างกัน อย่าคัดลอกทั้งหมด"),
        (5, "铺货", "店铺内做搭配购买（Bundle / Combo），把流量带给同店其他款", "ทำ Bundle / Combo ในร้าน ส่งต่อทราฟฟิกให้สินค้าอื่น"),
        (7, "活动", "接下来每个双数日大促都报名；活动前 3 天设好店铺券", "สมัครทุกแคมเปญวันเลขเบิ้ล ตั้งคูปองร้านก่อน 3 วัน"),
        (10, "利润", "涨价 5% 测试一周，销量掉得不多就保留新价（利润优先）", "ขึ้นราคา 5% ทดสอบ 1 สัปดาห์ ยอดไม่ลดมากก็ใช้ราคาใหม่ (กำไรมาก่อน)"),
        (14, "产能", "按目标日销算每天要几小时打印，排产和耗材提前备好", "คำนวณชั่วโมงพิมพ์ต่อวันตามเป้า เตรียมคิวพิมพ์และวัสดุล่วงหน้า"),
        (21, "复盘", "第 3 周复盘：看各店铺、各平台谁卖得好，资源集中到卖得好的", "สรุปสัปดาห์ที่ 3: ดูร้าน / แพลตฟอร์มที่ขายดี ทุ่มให้ที่ขายดี"),
        (30, "复盘", "计划到期：总结销量、利润，决定是否继续加目标", "ครบแผน: สรุปยอดขายและกำไร ตัดสินใจว่าจะเพิ่มเป้าต่อไหม"),
    ],
}
PHASE_TH = {"起步": "เริ่มต้น", "放量": "เพิ่มยอด", "冲刺": "เร่ง", "复盘": "สรุปผล", "扩款": "เพิ่มตัวเลือก", "铺货": "กระจายสินค้า",
            "活动": "แคมเปญ", "利润": "กำไร", "产能": "กำลังผลิต", "自定义": "เพิ่มเอง", "AI": "AI"}
STATUS = {"pending": ("未开始", "ยังไม่เริ่ม"), "ok": ("正常", "ปกติ"), "start": ("刚开始", "เพิ่งเริ่ม"), "ahead": ("领先", "นำหน้าเป้า"),
          "behind": ("落后", "ตามหลังเป้า"), "far": ("严重落后", "ตามหลังเป้ามาก")}


def _c():
    return mkt_db.conn()


def _sku(sku, skus=None):
    skus = skus if skus is not None else sku_rows()
    return skus.get((sku or "").upper())


def suggest(cfg, sku, platform, kind):
    """按竞品和我们自己的销量给一个默认目标：对标竞品最高日销 × 30%（爆款）/ 60%（上量）；产能限制一款最多占一半打印时间。"""
    from . import comp
    base = sku_avg_daily(sku, platform, 14)
    b = comp.benchmark(cfg, sku, platform)
    top = (b or {}).get("comp_daily_top")
    if kind == "scale":
        target = max(base * 1.5, round(top * 0.6, 1)) if top else max(base * 2, base + 1)
    else:
        target = max(base + 0.5, round(top * 0.3, 1)) if top else max(1.0, base * 2)
    target = round(max(0.5, target), 1)
    pct = "60%" if kind == "scale" else "30%"
    if top:
        note, note_th = f"对标竞品最高日销 {top:g} 件 × {pct}", f"ยอดขายต่อวันสูงสุดของคู่แข่ง {top:g} ชิ้น × {pct}"
    else:
        note, note_th = "还没有关联竞品，按自己的销量翻倍定", "ยังไม่ได้ผูกคู่แข่ง ตั้งเป้าเป็น 2 เท่าของยอดตัวเอง"
    s = _sku(sku) or {}
    cap = capacity_hours(cfg)
    if s.get("hours") and cap and target * float(s["hours"]) > cap * 0.5:
        target = round(cap * 0.5 / float(s["hours"]), 1)
        note += f"；受产能限制（一款最多占一半打印时间 = {target:g} 件/天）"
        note_th += f" จำกัดด้วยกำลังผลิต (สินค้าเดียวใช้เวลาพิมพ์ได้ไม่เกินครึ่ง = {target:g} ชิ้น/วัน)"
    return {"baseline_daily": base, "benchmark_daily": top, "target_daily": target, "note": note, "note_th": note_th}


def create(cfg, sku, platform, kind, target_daily=None, days=30, start_day=None):
    from . import campaigns
    sku = (sku or "").strip().upper()
    platform = (platform or "").lower()
    if kind not in KINDS:
        raise ValueError("计划类型不对")
    s = _sku(sku)
    if not s:
        raise ValueError(f"ERP 里没有 SKU {sku}")
    if s.get("draft"):
        raise ValueError(f"{sku} 还是 ERP 里的草稿，补完资料、上架后再建计划")
    c = _c()
    if c.execute("SELECT 1 FROM ops_plans WHERE sku=? AND platform=? AND status='active'", (sku, platform)).fetchone():
        raise ValueError("这个 SKU 在这个平台已经有进行中的计划")
    sg = suggest(cfg, sku, platform, kind)
    target = float(target_daily) if target_daily not in (None, "") else sg["target_daily"]
    if target <= 0:
        raise ValueError("目标日销要大于 0")
    days = max(7, min(90, int(days or 30)))
    start = dt.date.fromisoformat(start_day) if start_day else today()
    cur = c.execute("""INSERT INTO ops_plans(sku, platform, kind, status, start_day, days, baseline_daily, benchmark_daily, target_daily,
                       unit_price, ai_note, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sku, platform, kind, "active", start.isoformat(), days, sg["baseline_daily"], sg["benchmark_daily"],
                     target, s.get("price"), sg["note"], time.time()))
    pid = cur.lastrowid
    scale = days / 30
    for off, phase, text, text_th in TEMPLATES[kind]:
        c.execute("INSERT INTO ops_plan_tasks(plan_id, offset, phase, text, text_th, source) VALUES(?,?,?,?,?,?)",
                  (pid, min(days - 1, round(off * scale)), phase, text, text_th, "rule"))
    end = start + dt.timedelta(days=days)
    for e in campaigns.big_events(cfg, max(1, (end - today()).days + 1)):
        sd = dt.date.fromisoformat(e["start"])
        if start <= sd <= end and (not platform or platform in (e.get("platforms") or campaigns.ALL)):
            off = max(0, (sd - start).days - 7)
            c.execute("INSERT INTO ops_plan_tasks(plan_id, offset, phase, text, text_th, source) VALUES(?,?,?,?,?,?)",
                      (pid, off, "活动", f"报名「{e['name']}」（{e['start']}），设活动价和店铺券，按目标备耗材",
                       f"สมัคร「{e['name_th']}」({e['start']}) ตั้งราคาแคมเปญและคูปองร้าน เตรียมวัสดุตามเป้า", "campaign"))
    c.commit()
    return pid


def _target_at(p, d):
    """第 d 天（从 1 开始）的目标日销。"""
    ramp = max(1, round(p["days"] * 0.67))
    b, t = p["baseline_daily"] or 0, p["target_daily"] or 0
    return round(b + (t - b) * min(1.0, d / ramp), 2)


def progress(cfg, p):
    start = dt.date.fromisoformat(p["start_day"])
    td = today()
    end_day = dt.date.fromtimestamp(p["closed_at"]) if p.get("closed_at") else td
    elapsed = max(0, min(p["days"], (min(td, end_day) - start).days + 1))
    since = day_start_ts(start)
    daily = sku_daily(p["sku"], p["platform"], since)
    series, cum_t, cum_a = [], 0.0, 0
    for i in range(p["days"]):
        d = start + dt.timedelta(days=i)
        tg = _target_at(p, i + 1)
        a = daily.get(d.isoformat(), 0) if i < elapsed else None
        if i < elapsed:
            cum_t += tg
            cum_a += a
        series.append({"day": d.isoformat(), "target": tg, "actual": a})
    last7 = [x["actual"] for x in series[max(0, elapsed - 7):elapsed] if x["actual"] is not None]
    avg7 = round(sum(last7) / len(last7), 2) if last7 else 0
    ratio = round(cum_a / cum_t, 2) if cum_t >= 0.5 else None
    if elapsed == 0:
        status = "pending"
    elif ratio is None:
        status = "start"
    elif ratio >= 1:
        status = "ahead"
    elif ratio >= 0.7:
        status = "ok"
    elif ratio >= 0.4:
        status = "behind"
    else:
        status = "far"
    rev, prof = sku_money(p["sku"], p["platform"], since, cfg)
    price = p.get("unit_price") or 0
    target_total = round(sum(x["target"] for x in series), 1)
    return {"elapsed": elapsed, "series": series, "cum_target": round(cum_t, 1), "cum_actual": cum_a, "ratio": ratio,
            "status": status, "status_label": STATUS[status][0], "status_th": STATUS[status][1], "avg7": avg7,
            "target_now": _target_at(p, max(1, elapsed)), "target_total": target_total, "target_revenue": round(target_total * price, 0),
            "actual_revenue": rev, "actual_profit": prof, "expired": elapsed >= p["days"] and td > start + dt.timedelta(days=p["days"] - 1)}


def diagnose(cfg, p, pr, bench=None, skus=None):
    """落后 / 领先时给原因和下一步（规则；AI 版在 ai_refresh 里）。返回 [(中文, 泰文)]。"""
    from . import campaigns, comp, traffic
    tips = []
    tr = traffic.get(p["sku"], p["platform"] or None)
    pv = (bench or {}).get("price_vs_median_pct")
    if pr["status"] in ("behind", "far") and tr and tr.get("visitors") is not None:
        days = tr.get("period_days") or 7
        vpd = tr["visitors"] / max(1, days)
        conv = tr.get("conversion")
        if vpd < 10:
            tips.append((f"后台数据：每天只有约 {vpd:.0f} 个访客（{tr.get('period_text') or ''}）→ 曝光问题：标题关键词、类目、主图点击率、报名活动",
                         f"ข้อมูลหลังร้าน: ผู้เข้าชมแค่ราว {vpd:.0f} คน/วัน → ปัญหาการมองเห็น: คีย์เวิร์ดในชื่อ หมวดหมู่ รูปหลัก สมัครแคมเปญ"))
        elif conv is not None and conv < 1.5:
            tips.append((f"后台数据：每天约 {vpd:.0f} 个访客但转化率只有 {conv:.1f}% → 转化问题：价格、评价数、详情图、规格选择",
                         f"ข้อมูลหลังร้าน: ผู้เข้าชมราว {vpd:.0f} คน/วัน แต่อัตราซื้อแค่ {conv:.1f}% → ปัญหาการปิดการขาย: ราคา รีวิว รูปรายละเอียด ตัวเลือก"))
    if pr["status"] in ("behind", "far"):
        if pr["avg7"] == 0 and not tr:
            tips.append(("近 7 天没出单：多半是曝光或点击问题 → 换第一张主图、标题加竞品关键词；检查商品是否还在售",
                         "7 วันไม่มีออเดอร์: น่าจะเป็นปัญหาการมองเห็นหรือคลิก → เปลี่ยนรูปแรก ใส่คีย์เวิร์ดของคู่แข่งในชื่อ ตรวจว่าสินค้ายังขายอยู่"))
        if pv is not None and pv > 15:
            tips.append((f"售价比竞品中位价高 {pv:g}%：先加店铺券或 2 件装，不要直接降到最低价以下",
                         f"ราคาสูงกว่าราคากลางของคู่แข่ง {pv:g}%: เพิ่มคูปองร้านหรือแพ็ก 2 ชิ้นก่อน อย่าลดต่ำกว่าราคาขั้นต่ำ"))
        elif pv is not None and pv < -10:
            tips.append((f"售价已经比竞品中位价低 {-pv:g}%，不是价格问题 → 看主图、标题、评价数",
                         f"ราคาต่ำกว่าราคากลางของคู่แข่งแล้ว {-pv:g}% ไม่ใช่ปัญหาราคา → ดูรูปหลัก ชื่อ จำนวนรีวิว"))
        tips.append(("跟进已买家评价（聊天提醒），评价数是转化率的关键", "ติดตามรีวิวจากผู้ซื้อ (ทักแชทเตือน) จำนวนรีวิวสำคัญต่ออัตราซื้อ"))
    elif pv is not None and pv > 15:
        tips.append((f"售价比竞品中位价高 {pv:g}%：卖点（尺寸、材质、颜色）要在主图上讲清楚，否则先加店铺券或 2 件装",
                     f"ราคาสูงกว่าราคากลางของคู่แข่ง {pv:g}%: ต้องบอกจุดขาย (ขนาด วัสดุ สี) ในรูปหลักให้ชัด ไม่งั้นเพิ่มคูปองหรือแพ็ก 2 ชิ้น"))
    if pr["status"] == "ahead" and pr["elapsed"] >= 7:
        tips.append(("超过目标：可以调高目标，或涨价 5% 测试；爆款计划可以提前转上量计划",
                     "เกินเป้า: เพิ่มเป้าได้ หรือขึ้นราคา 5% ทดสอบ แผนสินค้าขายดีเปลี่ยนเป็นแผนเพิ่มยอดได้เลย"))
    s = _sku(p["sku"], skus) or {}
    cap = capacity_hours(cfg)
    if s.get("hours") and cap and pr["target_now"] * float(s["hours"]) > cap * 0.5:
        h = pr["target_now"] * float(s["hours"])
        tips.append((f"目标日销要每天 {h:.1f} 小时打印，超过产能一半，注意排产", f"เป้ายอดขายต้องพิมพ์ {h:.1f} ชม./วัน เกินครึ่งของกำลังผลิต ระวังคิวพิมพ์"))
    for e in [e for e in campaigns.big_events(cfg, 14) if e["days_left"] > 0][:2]:
        tips.append((f"{e['days_left']} 天后有「{e['name']}」，记得报名", f"อีก {e['days_left']} วันมี「{e['name_th']}」 อย่าลืมสมัคร"))
    if bench:
        for ev in comp.events(7):
            if ev["comp_id"] in bench.get("comp_ids", []) and ev["kind"] in ("price_drop", "surge", "voucher"):
                tips.append((ev["text"], ev.get("text_th") or ev["text"]))
    return tips[:6]


def tasks(pid):
    st = todo.states()
    out = []
    for r in _c().execute("SELECT * FROM ops_plan_tasks WHERE plan_id=? ORDER BY offset, id", (pid,)):
        t = dict(r)
        if not t["done_at"] and st.get(f"ptask:{t['id']}") == "done":
            t["done_at"] = -1          # 在今日待办里点了完成
        t["phase_th"] = PHASE_TH.get(t["phase"] or "", t["phase"])
        out.append(t)
    return out


def get(pid):
    r = _c().execute("SELECT * FROM ops_plans WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None


def detail(cfg, pid, skus=None, cmp=None):
    from . import comp
    p = get(pid)
    if not p:
        return None
    skus = sku_rows(cfg) if skus is None else skus
    pr = progress(cfg, p)
    cmp = comp.compare(cfg, skus=skus) if cmp is None else cmp
    bench = next((g for g in cmp if g["sku"] == p["sku"] and (not p["platform"] or g["platform"] == p["platform"])), None)
    s = skus.get(p["sku"]) or {}
    start = dt.date.fromisoformat(p["start_day"])
    ts = tasks(pid)
    tdi = today().isoformat()
    for t in ts:
        t["day"] = (start + dt.timedelta(days=t["offset"])).isoformat()
        t["due"] = not t["done_at"] and t["day"] <= tdi
    tips = diagnose(cfg, p, pr, bench, skus)
    return {**p, "kind_label": KINDS[p["kind"]][0], "kind_th": KINDS[p["kind"]][1], "product_id": s.get("product_id"), "name": s.get("name"),
            "color": s.get("variant"), "progress": pr, "tips": [t[0] for t in tips], "tips_th": [t[1] for t in tips], "bench": bench, "tasks": ts}


def listing(cfg=None, include_closed=True):
    from . import comp
    cfg = cfg or load_config()
    q = "SELECT id FROM ops_plans" + ("" if include_closed else " WHERE status='active'") + " ORDER BY status='active' DESC, id DESC"
    ids = [r["id"] for r in _c().execute(q).fetchall()]
    if not ids:
        return []
    skus = sku_rows(cfg)
    cmp = comp.compare(cfg, skus=skus)
    return [detail(cfg, i, skus, cmp) for i in ids]


def set_task(pid, tid, done, user=""):
    c = _c()
    c.execute("UPDATE ops_plan_tasks SET done_at=? WHERE id=? AND plan_id=?", (time.time() if done else None, tid, pid))
    c.commit()
    try:
        todo.set_state(f"ptask:{int(tid)}", "done" if done else "", user)
    except ValueError:
        pass


def update(pid, data):
    sets = {}
    if data.get("target_daily") not in (None, ""):
        sets["target_daily"] = max(0.1, float(data["target_daily"]))
    if data.get("status") in ("active", "done", "stopped"):
        sets["status"] = data["status"]
        sets["closed_at"] = None if data["status"] == "active" else time.time()
    if "result" in data:
        sets["result"] = (data["result"] or "")[:500]
    if sets:
        _c().execute(f"UPDATE ops_plans SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), pid))
        _c().commit()


def delete(pid):
    c = _c()
    c.execute("DELETE FROM ops_plan_tasks WHERE plan_id=?", (pid,))
    c.execute("DELETE FROM ops_plans WHERE id=?", (pid,))
    c.commit()


def add_task(pid, offset, text, phase="自定义"):
    if not get(pid):
        raise ValueError("没有这个计划")
    _c().execute("INSERT INTO ops_plan_tasks(plan_id, offset, phase, text, source) VALUES(?,?,?,?,?)",
                 (pid, max(0, int(float(offset or 0))), phase, str(text)[:300], "manual"))
    _c().commit()


AI_SYS = """你是泰国电商（Lazada / Shopee）的资深运营，帮一家 3D 打印小卖家做单品计划。原则：
- 不投广告，靠自然流量：主图和标题关键词、店铺券、平台活动、套餐和变体、多店铺铺货、跟进真实买家评价
- 利润优先、只求小爆；不刷单、不刷评价、不好评返现、不做违反平台规则的事
- 价格不能低于 ERP 最低价（floor_price）
根据数据给出具体、可执行的任务（每条一句话，写清楚做什么），和泰文标题关键词建议。只回复 JSON：
{"summary": "两三句中文判断：现在卡在哪、接下来重点做什么",
 "tasks": [{"offset": 从计划第一天算第几天做（整数，不小于今天的天数）, "phase": "起步|放量|冲刺|活动|利润|复盘", "text": "任务（中文）", "text_th": "同一个任务的泰文"}],
 "keywords_th": ["泰文关键词", ...], "risks": ["风险或注意事项", ...]}
tasks 最多 8 条。"""


def _int(v, default):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def ai_refresh(cfg, pid):
    """AI 更新计划：把计划、产品、实际销量、竞品、后台流量、大促发给 AI，换掉还没做的 AI 任务，写一段判断。"""
    from . import campaigns, comp, traffic
    d = detail(cfg, pid)
    if not d:
        raise ValueError("没有这个计划")
    pr = d["progress"]
    comps = []
    if d["bench"]:
        rows = {r["id"]: r for r in comp.listing(cfg)}
        for cid in d["bench"]["comp_ids"][:6]:
            r = rows.get(cid)
            if r:
                e = r["est"]
                comps.append({"title": r["title"], "shop": r["shop"], "price": e["price_eff"], "daily": e["daily"],
                              "reviews": e["reviews"], "rating": e["rating"], "free_ship": e["free_ship"]})
    s = _sku(d["sku"]) or {}
    tr = traffic.get(d["sku"], d["platform"] or None) or {}
    ctx = {
        "plan": {"type": d["kind_label"], "platform": d["platform"] or "全部", "day": pr["elapsed"], "days": d["days"],
                 "target_daily": d["target_daily"], "baseline_daily": d["baseline_daily"]},
        "product": {"sku": d["sku"], "name": s.get("name"), "title_th": s.get("title_th"), "price": s.get("price"),
                    "floor_price": s.get("floor_price"), "unit_cost": s.get("unit_cost"), "print_hours": s.get("hours")},
        "actual": {"cum_actual": pr["cum_actual"], "cum_target": pr["cum_target"], "avg7": pr["avg7"], "status": pr["status_label"],
                   "revenue": pr["actual_revenue"], "profit": pr["actual_profit"]},
        "competitors": comps,
        "shop_backend_traffic": {k: v for k, v in tr.items() if k in ("period_text", "impressions", "visitors", "views", "add_to_cart", "orders", "conversion")} or None,
        "tasks_done": [t["text"] for t in d["tasks"] if t["done_at"]][:12],
        "upcoming_campaigns": [{"name": e["name"], "start": e["start"]} for e in campaigns.big_events(cfg, 30) if e["days_left"] >= 0][:4],
    }
    r = ai_json(cfg, AI_SYS, json.dumps(ctx, ensure_ascii=False))
    c = _c()
    c.execute("DELETE FROM ops_plan_tasks WHERE plan_id=? AND source='ai' AND done_at IS NULL", (pid,))
    for t in (r.get("tasks") or [])[:8]:
        if not isinstance(t, dict) or not t.get("text"):
            continue
        off = max(pr["elapsed"] - 1, _int(t.get("offset"), pr["elapsed"]))
        c.execute("INSERT INTO ops_plan_tasks(plan_id, offset, phase, text, text_th, source) VALUES(?,?,?,?,?,?)",
                  (pid, max(0, min(d["days"] - 1, off)), str(t.get("phase") or "AI")[:10], str(t["text"])[:300],
                   str(t.get("text_th") or "")[:300] or None, "ai"))
    note = str(r.get("summary") or "").strip()
    if r.get("keywords_th"):
        note += "\n关键词：" + "、".join(map(str, r["keywords_th"][:12]))
    if r.get("risks"):
        note += "\n注意：" + "；".join(map(str, r["risks"][:5]))
    c.execute("UPDATE ops_plans SET ai_note=?, ai_at=? WHERE id=?", (note[:2000], time.time(), pid))
    c.commit()
    return note


def due_tasks(cfg=None):
    """进今日待办的计划任务（进行中的计划里到日子、还没做的）和进度提醒。"""
    return listing(cfg, include_closed=False)
