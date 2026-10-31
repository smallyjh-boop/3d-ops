"""发票 / 收据（v2.50）：订单列表「打印 ▾ → 发票」。给买家的，中文 + 泰文标题，商品名用面单同一套泰文 / 英文（labeltext）。
每单一页（A5 竖版也能打）；有 VAT 设置时按设置分开显示税额。"""
import datetime as dt
from html import escape as h

from .labeltext import Texts


def _money(v):
    return f"{float(v or 0):,.2f}"


def html(orders, cfg):
    tx = Texts(cfg)
    seller = cfg.get("shop_name_th") or cfg.get("sender_name") or ""
    vat_on = bool(cfg.get("fin_vat_on"))
    vr = float(cfg.get("fin_vat_rate", 0.07) or 0)
    incl = cfg.get("fin_prices_incl_vat", True)
    css = ("body{font:13px 'Leelawadee UI','Microsoft YaHei',sans-serif;margin:16px;color:#111}"
           ".pg{page-break-after:always;max-width:720px;margin:0 auto 28px}h2{margin:0 0 4px}.hd{display:flex;justify-content:space-between;gap:16px}"
           "table{border-collapse:collapse;width:100%;margin:10px 0}th,td{border:1px solid #999;padding:5px 6px;text-align:left}"
           "th{background:#eee}td.n,th.n{text-align:right}.tot td{font-weight:bold}.muted{color:#555;font-size:12px}"
           "@media print{.noprint{display:none}}")
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>发票 ใบเสร็จรับเงิน</title><style>{css}</style></head><body>"
           "<p class='noprint'><button onclick='print()'>打印 / พิมพ์</button></p>"]
    for o in orders:
        day = dt.datetime.fromtimestamp(o.get("order_time") or 0).strftime("%Y-%m-%d") if o.get("order_time") else ""
        rows, sub = [], 0.0
        for it in o.get("items") or []:
            qty = int(it.get("qty") or 1)
            tot = it.get("item_total")
            if tot is None and it.get("unit_price") is not None:
                tot = float(it["unit_price"]) * qty
            unit = it.get("unit_price") if it.get("unit_price") is not None else ((tot or 0) / qty if qty else 0)
            sub += float(tot or 0)
            name = tx.name(it) or it.get("sku") or ""
            spec = tx.spec(it)
            rows.append(f"<tr><td>{h(it.get('sku') or '')}</td><td>{h(name)}{(' · ' + h(spec)) if spec else ''}</td>"
                        f"<td class='n'>{qty}</td><td class='n'>{_money(unit)}</td><td class='n'>{_money(tot)}</td></tr>")
        total = float(o["order_total"]) if o.get("order_total") is not None else sub
        ship = float(o.get("buyer_shipping") or 0)
        disc = float(o.get("seller_discount") or 0) + float(o.get("platform_discount") or 0)
        tail = []
        if ship:
            tail.append(f"<tr><td colspan='4' class='n'>运费 ค่าจัดส่ง</td><td class='n'>{_money(ship)}</td></tr>")
        if disc:
            tail.append(f"<tr><td colspan='4' class='n'>优惠 ส่วนลด</td><td class='n'>-{_money(abs(disc))}</td></tr>")
        if vat_on and vr:
            vat = total * vr / (1 + vr) if incl else total * vr
            base = total - vat if incl else total
            tail.append(f"<tr><td colspan='4' class='n'>不含税 มูลค่าก่อนภาษี</td><td class='n'>{_money(base)}</td></tr>"
                        f"<tr><td colspan='4' class='n'>VAT {vr * 100:g}%</td><td class='n'>{_money(vat)}</td></tr>")
            if not incl:
                total = total + vat
        tail.append(f"<tr class='tot'><td colspan='4' class='n'>合计 รวมทั้งสิ้น (THB)</td><td class='n'>{_money(total)}</td></tr>")
        buyer = o.get("receiver") or o.get("buyer") or ""
        out.append(f"<div class='pg'><div class='hd'><div><h2>收据 / 发票 ใบเสร็จรับเงิน / ใบแจ้งหนี้</h2>"
                   f"<div class='muted'>{h(seller)}<br>{h(cfg.get('sender_address') or '')} {h(cfg.get('sender_phone') or '')}</div></div>"
                   f"<div class='muted'>No. <b>{h(o.get('order_no') or '')}</b><br>日期 วันที่ {h(day)}<br>"
                   f"{h(str(o.get('platform') or '').upper())} {h(o.get('shop') or '')}</div></div>"
                   f"<p>客户 ลูกค้า：<b>{h(buyer)}</b><br><span class='muted'>{h(o.get('address') or '')} {h(o.get('postcode') or '')}</span></p>"
                   "<table><tr><th>SKU</th><th>商品 รายการ</th><th class='n'>数量 จำนวน</th><th class='n'>单价 ราคา</th><th class='n'>金额 จำนวนเงิน</th></tr>"
                   + "".join(rows) + "".join(tail) + "</table>"
                   "<p class='muted'>谢谢惠顾 ขอบคุณที่ใช้บริการ</p></div>")
    out.append("</body></html>")
    return "".join(out)
