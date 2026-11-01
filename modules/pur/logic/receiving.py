"""到货入库（v2.51）：手机扫码 / 电脑「到货入库」页签共用。

扫到的码：采购单号（CG…）/ 平台订单号 / 物流单号 → 这张采购单；物品编码 / 条码 → 有这个物品、还在途的采购单（一张就直接打开）。
入库：填这次到了多少，少发 / 破损记成差异；可以顺便给物品放货位（库存模块的货位）、打印物品标签。
"""
from html import escape as h

from core import db, inventory as inv, modules

from .store import ensure

OPEN = ("ordered", "partial")


def _putaway(lines):
    """v2.52：每一行的上架推荐（库存模块的货位）：[{code, qty}]，到货页把第一个货位当输入框的提示。"""
    loc_mod = modules.public("inv")
    if loc_mod is None or not hasattr(loc_mod, "putaway_suggest"):
        return lines
    for x in lines:
        left = max(0.0, (x.get("qty") or 0) - (x.get("received") or 0))
        x["putaway"] = [{"code": s["code"], "qty": s["qty"]} for s in loc_mod.putaway_suggest(x["item_id"], left or None)[:3]] if x.get("item_id") else []
    return lines


def _open_po_brief(p):
    return {k: p.get(k) for k in ("id", "no", "status", "status_zh", "expected_date", "tracking", "carrier", "order_ref", "overdue_days")} | {
        "supplier": (p.get("supplier") or {}).get("name") or "",
        "lines": [{k: x.get(k) for k in ("id", "item_id", "code", "name_zh", "name_th", "unit", "category", "qty", "received", "rolls",
                                         "net_g", "location")} for x in p["lines"]]}


def scan(code):
    ensure()
    s = str(code or "").strip()
    if not s:
        raise ValueError("先扫码或输入")
    c = db.conn()
    r = c.execute("SELECT id FROM inv_po WHERE UPPER(no)=UPPER(?) OR (tracking!='' AND tracking=?) OR (order_ref!='' AND order_ref=?) "
                  "ORDER BY id DESC LIMIT 1", (s, s, s)).fetchone()
    if r:
        return {"type": "po", "po": _open_po_brief(inv.get_po(r["id"]))}
    it = inv.get_item(s) or inv.get_item(s.upper())
    if it:
        pos = [_open_po_brief(inv.get_po(x["id"])) for x in c.execute(
            "SELECT DISTINCT p.id FROM inv_po p JOIN inv_po_lines l ON l.po_id=p.id WHERE l.item_id=? AND p.status IN ('ordered','partial') "
            "AND l.qty>COALESCE(l.received,0) ORDER BY p.id", (it["id"],))]
        return {"type": "item", "item": {k: it.get(k) for k in ("id", "code", "name_zh", "name_th", "unit", "category", "qty", "location")},
                "pos": pos}
    return {"type": "unknown", "code": s}


def open_pos():
    """在途的采购单（到货入库页签、手机页列表）：快到 / 过期的在前。"""
    ensure()
    out = [_open_po_brief(p) for p in inv.list_po("transit")]
    out.sort(key=lambda p: (p["expected_date"] or "9999", p["id"]))
    return out


def receive(po_id, qtys, issues=None, locations=None, note="", user=""):
    """到货：入库 + 差异 + 放货位。locations：{物品id: 货位编号}（库存模块关着就不放）。"""
    ensure()
    loc_mod = modules.public("inv")
    if loc_mod is not None and hasattr(loc_mod, "putaway_batch"):
        # v2.52：这次到的货按填的货位上架，没填的按上架推荐（同一物品已在的货位 → 附近空位 → 空位）
        with loc_mod.putaway_batch(locations or {}, user) as pb:
            po = inv.receive_po(po_id, qtys or {}, user, note or "", issues or [])
        return {"po": inv.get_po(po["id"]), "placed": pb["placed"], "warnings": pb["warnings"]}
    po = inv.receive_po(po_id, qtys or {}, user, note or "", issues or [])
    placed, warn = [], []
    for iid, code in (locations or {}).items():
        code = str(code or "").strip()
        if not code:
            continue
        if loc_mod is None or not hasattr(loc_mod, "assign"):
            warn.append("库存模块没开，货位没放")
            break
        try:
            loc_mod.assign(int(iid), code, user)
            placed.append({"item_id": int(iid), "code": code.upper()})
        except ValueError as e:
            warn.append(str(e))
    return {"po": inv.get_po(po["id"]), "placed": placed, "warnings": warn}


def labels_html(po_no, counts, lang="zh"):
    """物品标签（50×30 毫米，Code128 = 物品编码）：counts {行id: 张数}；不给 = 每行按这次能数的数量（耗材按卷，最多 50 张）。"""
    from core import labels
    p = inv.get_po(po_no)
    cards = []
    for ln in p["lines"]:
        n = counts.get(str(ln["id"])) if counts else None
        if n is None:
            got = ln.get("received") or 0
            n = int(round(got / (ln["net_g"] or 1000))) if ln.get("rolls") else (int(got) if ln["unit"] not in ("g", "kg", "米") else 1)
        n = max(0, min(int(n or 0), 50))
        name = (ln.get("name_th") if lang == "th" and ln.get("name_th") else ln.get("name_zh")) or ""
        for _ in range(n):
            cards.append(f"""<div class="lb"><div class="code">{h(ln['code'])}</div><div class="bc">{labels.code128_svg(ln['code'], height=40, module=2)}</div>
<div class="nt">{h(name)}</div><div class="nt sm">{h(p['no'])}{(' · ' + h(ln['location'])) if ln.get('location') else ''}</div></div>""")
    css = """@page { size: 50mm 30mm; margin: 0 } body { margin: 0 }
.lb { width: 50mm; height: 30mm; box-sizing: border-box; padding: 1.5mm 2mm; page-break-after: always;
      font-family: 'Leelawadee UI', Tahoma, 'Microsoft YaHei', sans-serif; display: flex; flex-direction: column; overflow: hidden }
.code { font: bold 12pt monospace; text-align: center; letter-spacing: 1px; line-height: 1.1 }
.bc { height: 11mm } .bc svg { height: 100%; width: 100% }
.nt { font-size: 7.5pt; text-align: center; white-space: nowrap; overflow: hidden } .sm { font-size: 6.5pt; color: #444 }
@media screen { body { background: #ddd } .lb { background: #fff; margin: 6px auto } }"""
    body = "".join(cards) or "<p>没有要打印的标签</p>"
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{h(p['no'])}</title><style>{css}</style></head>"
            f"<body>{body}<script>setTimeout(() => print(), 300)</script></body></html>")
