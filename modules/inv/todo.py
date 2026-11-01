"""仓库的今日待办（v2.52，MODULE["todo"]）：
  · 库内补货：拣货区货位低于最低数量 → 建移库任务（从备货区搬），每个任务一条；备货区也没货的提醒去补货；
  · 待上架：到了货还没放到货位上的物品。
  v2.53：耗材区 / 包材区也补货；备货区空了 → 成品去成品备货、买的东西去采购补货建议；料卷快用完 / 过期 / 该烘干；待检区、退货区有东西。
"""
from core import db

from . import wms

ROLES = "owner,production,listing"


def provide(add):
    c = db.conn()
    if not c.execute("SELECT 1 FROM inv_locations LIMIT 1").fetchone():
        return
    wms.ensure_tasks()
    for t in wms.tasks():
        q = f"{t['qty']:g} {t['unit'] or ''}".strip()
        add(f"inv:task:{t['id']}", "仓库", "warn", f"库内补货：{t['code']} 从 {t['from_loc']} 搬 {q} 到 {t['to_loc']}",
            f"{t['name_zh'] or ''}（拣货位低于最低数量）", "inv_locations", ROLES,
            th=(f"เติมสินค้าในคลัง: {t['code']} ย้ายจาก {t['from_loc']} {q} ไป {t['to_loc']}",
                f"{t['name_th'] or t['name_zh'] or ''} (ช่องหยิบต่ำกว่าขั้นต่ำ)"))
    from core import modules
    pur = modules.enabled("pur") if hasattr(modules, "enabled") else False
    for s in wms.replenish_suggestions():
        if not s["sources"]:
            zt = wms.ZTYPES.get(s.get("ztype") or "pick", wms.ZTYPES["pick"])
            goods = s.get("category") == "goods"
            # v2.53：备货区也空了 → 成品去「成品备货」安排打印，买的东西去采购的「补货建议」
            tab = "stock" if goods else ("po_suggest" if pur else "inventory")
            add(f"inv:empty:{s['item_id']}:{s['to']}", "仓库", "bad" if s["now"] <= 0 else "warn",
                f"{zt[0]} {s['to']} 的 {s['code']} 只剩 {s['now']:g}，备货区也没有了", "安排打印（成品备货）" if goods else "去采购（补货建议）",
                tab, ROLES, th=(f"{zt[1]} {s['to']} ของ {s['code']} เหลือ {s['now']:g} โซนสำรองก็ไม่มีแล้ว",
                                "วางแผนพิมพ์ (เตรียมสต็อก)" if goods else "สั่งซื้อ (แนะนำเติมสต็อก)"))
    from . import flows
    try:
        flows.sync_printers(c)
    except Exception:  # noqa: BLE001  打印机货位同步失败不影响待办
        pass
    for a in flows.spool_alerts():      # v2.53：料卷快用完、放太久、该烘干
        add(f"inv:spool:{a['kind']}:{a['id']}", "仓库", a["level"], a["zh"], "", "materials", "owner,production", th=(a["th"], ""))
    for zt, zh, th in (("qc", "待检区有 {n} 样成品等质检", "โซนรอตรวจมีสินค้า {n} รายการรอตรวจ"),
                       ("returns", "退货区有 {n} 样等检查", "โซนสินค้าคืนมี {n} รายการรอตรวจ")):
        n = len(flows._held(c, zt))
        if n:
            add(f"inv:{zt}:{n}", "仓库", "info", zh.format(n=n), "合格 → 上架；不合格 → 次品区", "inv_locations", ROLES,
                th=(th.format(n=n), "ผ่าน → จัดเก็บ ไม่ผ่าน → โซนชำรุด"))
    n = wms.pending_count(c)
    if n:
        add(f"inv:pending:{n}", "仓库", "info", f"{n} 个物品待上架", "到了货还没放到货位上：扫货位确认上架", "inv_locations", ROLES,
            th=(f"{n} รายการรอจัดเก็บ", "ของมาถึงแล้วแต่ยังไม่ได้วางในตำแหน่ง: สแกนตำแหน่งเพื่อยืนยัน"))
