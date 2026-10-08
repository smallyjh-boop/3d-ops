"""快递面单模板（v2.33）：按各家快递的版式生成面单（自己发快递、手工单、私下成交用；平台单也可以当备用）。

说明：平台订单走平台物流时，快递员认的是平台出的面单（条码由平台分配），平台单请优先打印平台面单。
这里的模板按各家快递常见的热敏面单版式排：品牌色条、运单号 Code128 条码、目的地邮编大字、COD 金额框、
收件人 / 寄件人、订单号条码、商品清单。分拣码（各家内部的线路码）系统拿不到，用邮编代替。

  CARRIERS   各家快递：名字、品牌色、识别关键字、版式（courier 快递公司 / post 邮政）
  SIZES      100x150（默认，热敏 4×6 寸）/ 100x100 / a6（105×148）
  detect(o)  按订单的「物流」文字认出是哪家
  html(orders, cfg, tpl=None, size=None)   生成整页（每单一张）
"""
from html import escape as h

from core.labels import code128_svg

CARRIERS = {
    "flash": {"name": "Flash Express", "th": "แฟลช เอ็กซ์เพรส", "color": "#FFD400", "ink": "#000", "keys": ["flash"], "layout": "courier"},
    "kerry": {"name": "KEX Express (Kerry)", "th": "เคอรี่", "color": "#F26722", "ink": "#fff", "keys": ["kerry", "kex"], "layout": "courier"},
    "jt": {"name": "J&T Express", "th": "เจแอนด์ที", "color": "#E3051B", "ink": "#fff", "keys": ["j&t", "j & t", "jnt", "jt express", "j&t express"], "layout": "courier"},
    "spx": {"name": "SPX Express", "th": "เอสพีเอ็กซ์", "color": "#EE4D2D", "ink": "#fff", "keys": ["spx", "shopee xpress", "shopee express"], "layout": "courier"},
    "lex": {"name": "Lazada Logistics (LEX)", "th": "ลาซาด้า โลจิสติกส์", "color": "#0F146D", "ink": "#fff", "keys": ["lex", "lazada"], "layout": "courier"},
    "best": {"name": "BEST Express", "th": "เบสท์ เอ็กซ์เพรส", "color": "#111111", "ink": "#FFD100", "keys": ["best"], "layout": "courier"},
    "ninja": {"name": "Ninja Van", "th": "นินจาแวน", "color": "#C3002F", "ink": "#fff", "keys": ["ninja"], "layout": "courier"},
    "dhl": {"name": "DHL eCommerce", "th": "ดีเอชแอล", "color": "#FFCC00", "ink": "#D40511", "keys": ["dhl"], "layout": "courier"},
    "thpost": {"name": "Thailand Post", "th": "ไปรษณีย์ไทย", "color": "#E3051B", "ink": "#fff",
               "keys": ["ไปรษณีย์", "thailand post", "thai post", "thaipost", "ems", "ลงทะเบียน", "ไปรษณีย์ไทย"], "layout": "post"},
    "generic": {"name": "", "th": "", "color": "#000000", "ink": "#fff", "keys": [], "layout": "courier"},
}
SIZES = {"100x150": (100, 150), "100x100": (100, 100), "a6": (105, 148)}
SIZE_ZH = {"100x150": "100×150 毫米（热敏 4×6 寸，最常用）", "100x100": "100×100 毫米（小标签）", "a6": "A6 105×148 毫米（普通打印机用 A6 纸）"}


def detect(o):
    t = str((o or {}).get("carrier") or "").lower()
    for k, c in CARRIERS.items():
        if any(x in t for x in c["keys"]):
            return k
    return "generic"


def _sender(cfg):
    return (" ".join(x for x in (cfg.get("sender_name"), cfg.get("sender_phone")) if x), cfg.get("sender_address") or "")


def _postcode_boxes(pc):
    pc = "".join(ch for ch in str(pc or "") if ch.isdigit())[:5]
    return "".join(f'<span class="pcb">{h(ch)}</span>' for ch in pc.ljust(5)) if pc else ""


def _label(o, cfg, key, size):
    c = CARRIERS.get(key) or CARRIERS["generic"]
    w, hh = SIZES[size]
    small = hh <= 100
    sender, s_addr = _sender(cfg)
    track = o.get("tracking_no") or ""
    cod = o.get("cod")
    items = "，".join(f"{i.get('sku')}×{i.get('qty') or 1}" for i in o.get("items") or [])
    name = c["name"] or (o.get("carrier") or "")
    cod_html = (f'<span class="cod">COD ฿{cod:,.0f}</span>' if cod else '<span class="nocod">ไม่เก็บเงินปลายทาง<br>非货到付款</span>')
    head = (f'<div class="hd" style="background:{c["color"]};color:{c["ink"]}"><span class="brand">{h(name) or "&nbsp;"}</span>'
            f'<span class="sv">{h(o.get("ship_method_zh") or "")}</span></div>')
    tb = (f'<div class="bc">{code128_svg(track, 18 if small else 22, 2)}<div class="tn">{h(track)}</div></div>' if track
          else '<div class="bc notrk">（还没有运单号 ยังไม่มีเลขพัสดุ）</div>')
    recv = (f'<div class="box rc"><div class="lab">ผู้รับ / 收件人</div>'
            f'<div class="big">{h(o.get("receiver") or o.get("buyer") or "")}　{h(o.get("phone") or "")}</div>'
            f'<div class="addr">{h(o.get("address") or "（没有地址，请在订单详情里填写）")}</div></div>')
    send = f'<div class="box sd"><span class="lab">ผู้ส่ง / 寄件人：</span>{h(sender)}<div>{h(s_addr)}</div></div>'
    if c["layout"] == "post":
        body = (f'{head}<div class="row">{send}{cod_html}</div>{tb}'
                f'<div class="box rc post"><div class="lab">กรุณาส่ง / 收件人</div>'
                f'<div class="big">{h(o.get("receiver") or o.get("buyer") or "")}</div><div>โทร {h(o.get("phone") or "")}</div>'
                f'<div class="addr">{h(o.get("address") or "")}</div><div class="pcs">{_postcode_boxes(o.get("postcode"))}</div></div>')
    else:
        body = (f'{head}<div class="row"><div class="sort"><div class="lab">ปลายทาง / 目的地</div><div class="pc">{h(o.get("postcode") or "—")}</div></div>'
                f'{cod_html}</div>{tb}{recv}{send}')
    if not small:
        body += (f'<div class="bc ob">{code128_svg(o.get("order_no") or "", 14, 1)}<div>{h(o.get("platform") or "")} {h(o.get("order_no") or "")}</div></div>'
                 f'<div class="items">สินค้า：{h(items)}</div>')
        if o.get("custom_note"):
            body += f'<div class="note">{h(o.get("custom_note"))}</div>'
    else:
        body += f'<div class="items">#{h(o.get("order_no") or "")} · {h(items)[:80]}</div>'
    return f'<div class="lb">{body}</div>'


def _css(size):
    w, hh = SIZES[size]
    small = hh <= 100
    return (f"@page{{size:{w}mm {hh}mm;margin:0}}*{{box-sizing:border-box}}body{{margin:0;font:{11 if small else 12}px 'Leelawadee UI','Tahoma','Microsoft YaHei',sans-serif;color:#000}}"
            f".lb{{width:{w}mm;height:{hh}mm;padding:3mm;page-break-after:always;display:flex;flex-direction:column;gap:1.6mm;overflow:hidden}}"
            ".hd{display:flex;justify-content:space-between;align-items:center;padding:1.5mm 3mm;border-radius:1mm}"
            f".brand{{font-size:{15 if small else 18}px;font-weight:800;letter-spacing:.5px}}.sv{{font-size:10px;font-weight:700}}"
            ".row{display:flex;justify-content:space-between;align-items:stretch;gap:2mm}"
            ".sort{border:2px solid #000;padding:1mm 3mm;flex:1}.lab{font-size:9px;color:#333}"
            f".pc{{font-size:{24 if small else 32}px;font-weight:900;letter-spacing:3px;line-height:1.1}}"
            ".cod{border:2.5px solid #000;font-size:17px;font-weight:900;padding:1mm 3mm;display:flex;align-items:center}"
            ".nocod{font-size:9px;border:1px solid #000;padding:1mm 2mm;display:flex;align-items:center;text-align:center}"
            ".bc{text-align:center}.bc svg{width:100%}.tn{font:700 13px monospace;letter-spacing:2px}.notrk{font-size:11px;padding:3mm;border:1px dashed #000}"
            ".box{border:1.5px solid #000;padding:1.5mm 2mm}.big{font-size:15px;font-weight:800}.addr{font-size:12px}"
            ".sd{font-size:10px;flex:1}.post .big{font-size:17px}.pcs{text-align:right;margin-top:1mm}"
            ".pcb{display:inline-block;width:6.5mm;height:7.5mm;border:1.5px solid #000;margin-left:1mm;text-align:center;font:800 16px/7.5mm sans-serif}"
            ".ob div{font-size:10px}.items{font-size:10px}.note{border:1.5px dashed #000;padding:1mm;font-weight:700;font-size:10px}"
            "@media screen{body{background:#ddd}.lb{background:#fff;margin:8px auto;box-shadow:0 1px 4px #0003}.noprint{text-align:center;padding:8px}}"
            "@media print{.noprint{display:none}}")


def html(orders, cfg, tpl=None, size=None, preview=False):
    size = size if size in SIZES else (cfg.get("label_size") if cfg.get("label_size") in SIZES else "100x150")
    fixed = tpl if tpl in CARRIERS else (cfg.get("label_carrier") if cfg.get("label_carrier") in CARRIERS else None)
    w, hh = SIZES[size]
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>面单 ใบปะหน้า</title><style>{_css(size)}</style></head><body>"]
    if not preview:
        out.append(f"<div class='noprint'><button onclick='print()' style='font-size:16px;padding:6px 20px'>打印 / พิมพ์</button>"
                   f" <span style='font-size:12px'>打印机选 {w}×{hh} 毫米纸张，缩放 100%</span></div>")
    for o in orders:
        out.append(_label(o, cfg, fixed or detect(o), size))
    out.append("</body></html>")
    return "".join(out)


SAMPLE = {"order_no": "260109ABCDEF", "platform": "manual", "tracking_no": "TH0123456789AB", "cod": 299, "carrier": "",
          "receiver": "สมชาย ใจดี", "phone": "081-234-5678", "postcode": "10110",
          "address": "99/9 ซอยสุขุมวิท 21 แขวงคลองเตยเหนือ เขตวัฒนา กรุงเทพฯ 10110",
          "items": [{"sku": "3DP0012-WH", "qty": 2}, {"sku": "3DP0007-BK-L", "qty": 1}], "custom_note": "刻字：Nok"}


def preview_html(cfg, tpl, size):
    return html([dict(SAMPLE)], cfg, tpl=tpl or "generic", size=size, preview=True)
