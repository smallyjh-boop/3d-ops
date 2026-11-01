"""仓库的今日待办（v2.52，MODULE["todo"]）：
  · 库内补货：拣货区货位低于最低数量 → 建移库任务（从备货区搬），每个任务一条；备货区也没货的提醒去补货；
  · 待上架：到了货还没放到货位上的物品。
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
    for s in wms.replenish_suggestions():
        if not s["sources"]:
            add(f"inv:empty:{s['item_id']}:{s['to']}", "仓库", "bad" if s["now"] <= 0 else "warn",
                f"拣货位 {s['to']} 的 {s['code']} 只剩 {s['now']:g}，备货区也没有了", "去补货 / 安排生产", "inv_locations", ROLES,
                th=(f"ช่องหยิบ {s['to']} ของ {s['code']} เหลือ {s['now']:g} โซนสำรองก็ไม่มีแล้ว", "สั่งซื้อ / วางแผนผลิต"))
    n = wms.pending_count(c)
    if n:
        add(f"inv:pending:{n}", "仓库", "info", f"{n} 个物品待上架", "到了货还没放到货位上：扫货位确认上架", "inv_locations", ROLES,
            th=(f"{n} รายการรอจัดเก็บ", "ของมาถึงแล้วแต่ยังไม่ได้วางในตำแหน่ง: สแกนตำแหน่งเพื่อยืนยัน"))
