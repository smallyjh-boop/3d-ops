"""采购的今日待办（v2.51，MODULE["todo"]）：
  · 采购单过了预计到货还没到（过 3 天以上算红）；
  · 到货差异（少发 / 破损 / 发错 / 多发）还没处理；
  · 补货建议里有「来不及到货」的（红）；
  · 进价变了：耗材平均进价变化超过设置的百分比（已经自动改了定价用的耗材价格 / 或者等老板确认），别的物品到手单价变化大。
"""
import datetime as dt

from core import db, inventory as inv

from . import links, suggest
from .store import ensure

ROLES = "owner,production,listing"


def provide(add):
    ensure()
    c = db.conn()
    today = dt.date.today()
    for r in c.execute("SELECT p.id, p.no, p.expected_date, p.tracking, s.name sname FROM inv_po p LEFT JOIN inv_suppliers s ON s.id=p.supplier_id "
                       "WHERE p.status IN ('ordered','partial') AND p.expected_date IS NOT NULL AND p.expected_date!='' "
                       "AND p.expected_date<?", (today.isoformat(),)):
        try:
            late = (today - dt.date.fromisoformat(r["expected_date"])).days
        except ValueError:
            continue
        who = r["sname"] or ""
        add(f"pur:late:{r['id']}:{r['expected_date']}", "采购", "bad" if late >= 3 else "warn",
            f"采购单过了预计到货还没到：{r['no']} {who}".strip(), f"晚了 {late} 天" + (f"，运单 {r['tracking']}" if r["tracking"] else ""),
            "po_recv", ROLES, alert=late >= 3 or None,
            th=(f"ใบสั่งซื้อเลยวันที่คาดว่าถึงแล้วยังไม่มา: {r['no']} {who}".strip(),
                f"ช้า {late} วัน" + (f" เลขพัสดุ {r['tracking']}" if r["tracking"] else "")))
    for x in inv.po_issues("open"):
        q = x["qty"] or 0
        q_show = f"{q / 1000:g} kg" if x.get("unit") == "g" else f"{q:g} {x.get('unit') or ''}"
        kind_th = {"short": "ส่งขาด", "damaged": "เสียหาย", "wrong": "ส่งผิด", "extra": "ส่งเกิน"}.get(x["kind"], x["kind"])
        add(f"pur:issue:{x['id']}", "采购", "warn", f"到货差异没处理：{x['no']} {x.get('name_zh') or ''} {x['kind_zh']} {q_show}".strip(),
            x.get("note") or "找供应商补发 / 退款", "purchase", ROLES,
            th=(f"ของถึงไม่ตรงยังไม่จัดการ: {x['no']} {x.get('name_th') or x.get('name_zh') or ''} {kind_th} {q_show}".strip(),
                x.get("note") or "ติดต่อผู้ขายให้ส่งเพิ่ม / คืนเงิน"))
    try:
        rows = [r for r in suggest.compute()["rows"] if r["urgency"] == "red" and r["item"]["category"] != "filament"]
    except Exception:  # noqa: BLE001
        rows = []
    if rows:
        names = "、".join(r["item"]["name_zh"] for r in rows[:4]) + ("…" if len(rows) > 4 else "")
        names_th = ", ".join((r["item"].get("name_th") or r["item"]["name_zh"]) for r in rows[:4]) + ("…" if len(rows) > 4 else "")
        add(f"pur:red:{today.isoformat()}:{len(rows)}", "采购", "bad", f"{len(rows)} 种物品现在下单也来不及到货", names, "po_suggest", ROLES,
            th=(f"{len(rows)} รายการ สั่งตอนนี้ก็มาไม่ทัน", names_th))
    for ch in links.cost_changes("open"):
        sign = "+" if ch["pct"] > 0 else ""
        if ch["kind"] == "filament":
            done = "已自动更新定价用的耗材价格" if ch["applied"] else "到「采购 → 分析」确认要不要更新"
            add(f"pur:cost:{ch['id']}", "耗材与价格", "warn",
                f"耗材进价变了 {sign}{ch['pct']:g}%：¥{ch['old']:g} → ¥{ch['new']:g} / kg", f"{done}；产品成本和建议售价跟着变了，看一下价格",
                "library", "owner",
                th=(f"ราคาซื้อฟิลาเมนต์เปลี่ยน {sign}{ch['pct']:g}%: ¥{ch['old']:g} → ¥{ch['new']:g} / kg",
                    ("อัปเดตราคาฟิลาเมนต์สำหรับคิดราคาแล้ว" if ch["applied"] else "ไปยืนยันที่「จัดซื้อ → วิเคราะห์」")
                    + " ต้นทุนและราคาแนะนำของสินค้าเปลี่ยนตาม ตรวจราคาด้วย"))
        else:
            add(f"pur:cost:{ch['id']}", "采购", "info", f"进价变了 {sign}{ch['pct']:g}%：{ch['label']}",
                f"到手单价 ฿{ch['old']:.2f} → ฿{ch['new']:.2f}（{ch['po_no'] or ''}）", "purchase", "owner",
                th=(f"ราคาซื้อเปลี่ยน {sign}{ch['pct']:g}%: {ch.get('name_th') or ch['label']}",
                    f"ต้นทุนถึงมือ ฿{ch['old']:.2f} → ฿{ch['new']:.2f} ({ch['po_no'] or ''})"))
