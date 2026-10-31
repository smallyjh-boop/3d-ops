"""选品交给「今日待办」（🔔）的条目：今天巡逻找到的高分新模型（可选推到手机，走运营模块的提醒）、采用的草稿许可待核验、
模型文件下载失败 / 网站风控暂停、关注巡逻好几天没跑（扩展没开）。"""
import time

from core import store
from core.config import load_config

from . import db, rules, sites, watch


def provide(add):
    cfg = load_config()
    c = db.conn()
    thr = rules.tf(cfg.get("cur_alert_score"), 70)
    t0 = db.day_start()
    day = time.strftime("%Y-%m-%d", time.gmtime(t0 + 7 * 3600))
    alert_on = cfg.get("cur_alert_on", True) is not False
    hi = c.execute("SELECT * FROM cur_candidates WHERE new_at>=? AND excluded='' AND score>=? AND status='' ORDER BY score DESC LIMIT 5",
                   (t0, thr)).fetchall()
    for r in hi:
        add(f"cur-new:{r['id']}", "选品", "info", f"高分新模型 {r['score']:.0f} 分：{r['title'][:50]}", f"{sites.name_of(r['platform'])} · {r['category'] or ''}",
            "cur_cand", "owner,listing", alert=(f"🧩 高分新模型 {r['score']:.0f} 分：{r['title'][:60]} {r['url']}" if alert_on else None),
            th=(f"โมเดลใหม่คะแนนสูง {r['score']:.0f}: {r['title'][:50]}", f"{sites.name_of(r['platform'])} · {rules.CATEGORY_TH.get(r['category'], r['category'] or '')}"))
    n_new = c.execute("SELECT COUNT(*) FROM cur_candidates WHERE new_at>=? AND excluded=''", (t0,)).fetchone()[0]
    if n_new > len(hi):
        add(f"cur-newday:{day}", "选品", "info", f"关注巡逻今天找到 {n_new} 个新模型", f"{thr:.0f} 分以上 {len(hi)} 个", "cur_cand", "owner,listing",
            th=(f"วันนี้ตระเวนเจอโมเดลใหม่ {n_new} รายการ", f"{thr:.0f} คะแนนขึ้นไป {len(hi)} รายการ"))
    pend = []
    for r in c.execute("SELECT product_id FROM cur_candidates WHERE product_id<>'' AND adopted_at>=? ORDER BY adopted_at DESC LIMIT 200",
                       (time.time() - 90 * 86400,)).fetchall():
        try:
            p = store.load(r["product_id"])
        except (FileNotFoundError, ValueError):
            continue
        if (p.get("license_check") or {}).get("status") == "pending":
            pend.append(p["id"])
    if pend:
        add(f"cur-lic:{day}:{len(pend)}", "选品", "warn", f"{len(pend)} 个选品草稿许可待核验", "打开产品编辑页，看原站许可可以商用就点「核验通过」；核验前不能导出 / 推送："
            + "、".join(pend[:5]), "cur_queue", "owner,listing",
            th=(f"สินค้าฉบับร่าง {len(pend)} รายการรอตรวจสัญญาอนุญาต", "เปิดหน้าแก้ไขสินค้า ดูสัญญาอนุญาตที่เว็บต้นทาง ใช้เชิงพาณิชย์ได้จึงกด「ตรวจผ่าน」: " + ", ".join(pend[:5])))
    bad = c.execute("SELECT COUNT(*) FROM cur_files WHERE state='failed' AND kind<>'image' AND updated_at>=?", (time.time() - 3 * 86400,)).fetchone()[0]
    if bad:
        add(f"cur-dlfail:{day}:{bad}", "选品", "warn", f"{bad} 个模型文件下载失败", "在「选品 → 采集队列」里重新下载，或到原站下载后在产品的模型库上传", "cur_queue",
            "owner,listing", th=(f"ดาวน์โหลดไฟล์โมเดลไม่สำเร็จ {bad} ไฟล์", "ดาวน์โหลดใหม่ใน「คัดเลือกสินค้า → คิวเก็บข้อมูล」 หรือดาวน์โหลดเองแล้วอัปโหลดในคลังโมเดลของสินค้า"))
    for p in watch.overview(cfg):
        if p["paused"]:
            add(f"cur-pause:{p['key']}:{int(p['until'] // 3600)}", "选品", "warn", f"{p['name']} 疑似风控，采集和下载暂停中", p["reason"], "cur_watch",
                "owner,listing", th=(f"{p['name']} อาจถูกบล็อก หยุดเก็บข้อมูลและดาวน์โหลดชั่วคราว", ""))
    w = c.execute("SELECT COUNT(*) n, MAX(last_run) last FROM cur_watches WHERE enabled=1").fetchone()
    if w["n"] and watch.cfg_watch(cfg)["enabled"] and (w["last"] or 0) < time.time() - 2 * 86400:
        add(f"cur-nopatrol:{day}", "选品", "info", f"{w['n']} 个关注两天没巡逻了", "要有一台电脑开着装了 ERP 扩展的 Chrome（扩展会自动巡逻）", "cur_watch",
            "owner,listing", th=(f"{w['n']} รายการที่เฝ้าดูไม่ได้ตระเวนมา 2 วัน", "ต้องมีคอมเปิด Chrome ที่ติดตั้งส่วนขยาย ERP"))
