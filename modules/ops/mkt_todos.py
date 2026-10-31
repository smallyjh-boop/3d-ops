"""第二期交给「今日待办」的条目（core/todo.py）：竞品动态（降价、开券、放量）和该更新的竞品、爆款机会、今天还没巡逻、
竞店新品起量和我的店铺落后、计划任务和计划进度、营销日历的活动任务。带 alert 的会推到手机（和第一期同一套去重）。"""
import time

from core.config import load_config

from .mkt_util import day_of, ti


def provide(add, cfg=None):
    cfg = cfg or load_config()
    from . import mkt_db
    mkt_db.ensure()
    errs = []
    for fn in (_comp, _radar, _shops, _plans, _campaigns):
        try:
            fn(add, cfg)
        except Exception as e:  # noqa: BLE001  一块出错不影响别的；最后一起报给今日待办
            errs.append(f"{fn.__name__[1:]}: {e}")
    if errs:
        raise RuntimeError("；".join(errs)[:300])


def _comp(add, cfg):
    from . import comp
    rows = comp.listing(cfg)
    if not rows:
        return
    for e in comp.events(3):
        hot = e["kind"] in ("price_drop", "surge", "voucher")
        add(f"cev:{e['id']}", "竞品", "warn" if e["kind"] in ("price_drop", "surge") else "info", e["text"], "", "ops_comp", "owner",
            alert=e["text"] if hot else None, th=(e.get("text_th") or e["text"], ""))
    day = day_of(time.time())
    stale = [r for r in rows if r["est"]["stale"]]
    if stale:
        n = ti(cfg.get("oa_comp_stale_days"), 7)
        names = "、".join((r["title"] or r["item_key"] or "")[:20] for r in stale[:5])
        add(f"cstale:{day}", "竞品", "info", f"{len(stale)} 个竞品超过 {n} 天没更新数据", names, "ops_comp", "owner",
            th=(f"คู่แข่ง {len(stale)} รายการไม่ได้อัปเดตเกิน {n} วัน", names))
    once = [r for r in rows if r["est"]["n_snaps"] == 1 and r["est"]["last_ts"] and time.time() - r["est"]["last_ts"] > 86400]
    if once:
        add(f"cnosale:{day}", "竞品", "info", f"{len(once)} 个竞品只记过一次：今天再记一次累计已售，就能算出日销", "", "ops_comp", "owner",
            th=(f"คู่แข่ง {len(once)} รายการบันทึกแค่ครั้งเดียว: วันนี้บันทึกยอดขายสะสมอีกครั้งจะได้ยอดขายต่อวัน", ""))
    for r in rows:
        if not r["skus"] and r.get("radar_status") == "want":
            t = (r["title"] or "")[:50]
            add(f"radar:{r['id']}", "竞品", "info", f"单品机会·要做：{t}", "在 ERP 里建品、出图后上架；建好后在竞品详情里关联 SKU", "ops_comp",
                "owner", th=(f"โอกาสสินค้า·จะทำ: {t}", "สร้างสินค้าใน ERP ทำรูปแล้วลงขาย เสร็จแล้วผูก SKU ในรายละเอียดคู่แข่ง"))


def _radar(add, cfg):
    from . import radar
    b = radar.board(cfg)
    if not b["rows"]:
        return
    thr = b["alert_score"]
    month = day_of(time.time())[:7]
    for r in b["rows"]:
        o = r["opp"]
        if r["active"] and r["status"] == "new" and o["score"] >= thr:
            summ = o["ai"].get("summary") or "；".join(o["notes"][:2])
            add(f"radar-kw:{r['id']}:{month}", "爆款雷达", "info", f"爆款机会：{r['keyword']}（{r['platform']}）{o['score']} 分", summ, "ops_radar",
                "owner", alert=f"🔭 爆款机会：{r['keyword']}（{r['platform']}）{o['score']} 分" + (f" — {o['ai'].get('summary')}" if o["ai"].get("summary") else ""),
                th=(f"โอกาสสินค้าขายดี: {r['keyword']} ({r['platform']}) {o['score']} คะแนน", " ".join(o["notes_th"][:2])))
        if r["status"] == "want":
            idea = o["ai"].get("design_idea") or "找可商用模型或自己建模，做我们自己的版本"
            add(f"radar-want:{r['id']}", "爆款雷达", "info", f"交给选品：{r['keyword']}", idea, "ops_radar", "owner",
                th=(f"ส่งต่อให้คัดเลือกสินค้า: {r['keyword']}", o["ai"].get("design_idea") or "หาโมเดลที่ใช้เชิงพาณิชย์ได้หรือออกแบบเอง ทำเวอร์ชันของเราเอง"))
    p = b["patrol"]
    if p["total"] and p["done"] == 0:
        add(f"radar-patrol:{day_of(time.time())}", "爆款雷达", "info", f"今天还没巡逻：{p['total']} 个页面待看",
            "在浏览器扩展里点「🔭 开始今日巡逻」（电脑开着、人在旁边时）", "", "owner,listing",
            th=(f"วันนี้ยังไม่ได้ตระเวน: รอดู {p['total']} หน้า", "กด「🔭 เริ่มตระเวนวันนี้」ในส่วนขยายเบราว์เซอร์ (ตอนอยู่หน้าคอม)"))


def _shops(add, cfg):
    from . import shops
    b = shops.board(cfg)
    if not b["rows"]:
        return
    week = time.strftime("%G-%V")
    if not b["mine_set"]:
        add("shop-mine-missing", "竞店", "info", "还没填我的店铺前台链接", "设置 → 运营分析 → 竞店：填 Lazada / Shopee 店铺首页，用来和竞店放在同一个标准下比较",
            "ops_shops", "owner", th=("ยังไม่ได้กรอกลิงก์หน้าร้านของเรา", "ตั้งค่า → วิเคราะห์การขาย → ร้านคู่แข่ง: กรอกหน้าแรกร้าน Lazada / Shopee"))
    for g in b["gaps"]:
        mine = "-" if g["mine"] is None else g["mine"]
        add(f"shop-gap:{g['shop_id']}:{g['key']}:{week}", "竞店", "warn", f"我的店铺{g['label']}落后竞店",
            f"{g['shop']}：{mine}{g['unit']}，竞店中位 {g['bench']}{g['unit']}", "ops_shops", "owner",
            th=(f"ร้านของเรา{g['label_th']}ตามหลังคู่แข่ง", f"{g['shop']}: {mine}{g['unit']} ค่ากลางคู่แข่ง {g['bench']}{g['unit']}"))
    for r in b["rows"]:
        if r["is_mine"] or not r["watch"]:
            continue
        for it in r["m"]["hot_new"][:3]:
            t = (it["title"] or "")[:40]
            add(f"shop-hot:{r['id']}:{it['item_key']}", "竞店", "info", f"竞店新品起量：{t}",
                f"{r['name']} · 日销 {it['daily']} · ฿{it['price'] or '-'}：看看能不能做我们自己的版本（可以加进爆款雷达的关键词）", "ops_shops", "owner",
                alert=f"🏪 竞店「{r['name']}」新品起量：{t}，日销 {it['daily']}",
                th=(f"สินค้าใหม่ของร้านคู่แข่งเริ่มขายดี: {t}", f"{r['name']} · ขายต่อวัน {it['daily']} · ฿{it['price'] or '-'}"))


def _plans(add, cfg):
    from . import plans
    week = int(time.time() // (7 * 86400))
    for p in plans.listing(cfg, include_closed=False):
        pr = p["progress"]
        plat = p["platform"].capitalize() if p["platform"] else "全部平台"
        plat_th = p["platform"].capitalize() if p["platform"] else "ทุกแพลตฟอร์ม"
        who = f"{p['sku']}（{plat}·{p['kind_label']}）"
        who_th = f"{p['sku']} ({plat_th}·{p['kind_th']})"
        for t in p["tasks"]:
            if t["due"]:
                add(f"ptask:{t['id']}", "计划", "info", f"{who}：{t['text']}", f"第 {t['offset'] + 1} 天 · {t['phase']}", "ops_plans", "owner,listing",
                    th=(f"{who_th}: {t.get('text_th') or t['text']}", f"วันที่ {t['offset'] + 1} · {t.get('phase_th') or t['phase']}"))
        if pr["status"] in ("behind", "far"):
            add(f"pstat:{p['id']}:w{week}", "计划", "bad" if pr["status"] == "far" else "warn",
                f"{who} {pr['status_label']}：累计 {pr['cum_actual']} / 目标 {pr['cum_target']} 件", "；".join(p["tips"][:3]), "ops_plans", "owner",
                alert=(f"🎯 {p['kind_label']}{pr['status_label']}：{p['sku']} 累计 {pr['cum_actual']} / 目标 {pr['cum_target']} 件"
                       + (f" → {p['tips'][0]}" if p["tips"] else "")) if pr["elapsed"] >= 3 else None,
                th=(f"{who_th} {pr['status_th']}: สะสม {pr['cum_actual']} / เป้า {pr['cum_target']} ชิ้น", " ".join(p["tips_th"][:3])))
        elif pr["status"] == "ahead" and pr["elapsed"] >= 7:
            add(f"pstat:{p['id']}:a{week}", "计划", "info", f"{who} 领先目标：累计 {pr['cum_actual']} / {pr['cum_target']} 件", "；".join(p["tips"][:2]),
                "ops_plans", "owner", th=(f"{who_th} นำหน้าเป้า: สะสม {pr['cum_actual']} / {pr['cum_target']} ชิ้น", " ".join(p["tips_th"][:2])))
        if pr["expired"]:
            rate = round((pr["ratio"] or 0) * 100)
            add(f"pexp:{p['id']}", "计划", "warn", f"{who} 计划到期，复盘并结束计划", f"达成率 {rate}%", "ops_plans", "owner",
                th=(f"{who_th} ครบกำหนดแผน สรุปผลแล้วปิดแผน", f"ทำได้ {rate}%"))


def _campaigns(add, cfg):
    from . import campaigns
    for e, t in campaigns.todays_tasks(cfg):
        over = t["offset"] == -7 and e["over_capacity"]
        extra = f"（预计 {e['expected_orders']} 单/天，超过产能，建议限量或提前打库存）" if over else ""
        extra_th = f" (คาด {e['expected_orders']} ออเดอร์/วัน เกินกำลังผลิต ควรจำกัดจำนวนหรือพิมพ์เก็บไว้ก่อน)" if over else ""
        add(f"camp:{e['key']}:{t['offset']}", "营销", "warn" if over else "info", f"{e['name']}（{e['start']}）", t["text"] + extra, "ops_cal",
            "owner,listing", alert=f"📅 {e['name']}（{e['start']}）：{t['text']}{extra}" if (t["today"] and (over or t["offset"] in (-14, 0))) else None,
            th=(f"{e['name_th']} ({e['start']})", t["text_th"] + extra_th))
