"""面单。

两种：
1) 平台面单：Lazada / Shopee / TikTok / BigSeller 批量打印出来的面单 PDF，上传到这里，
   系统按每页上的订单号 / 运单号自动拆分、对应到订单。之后在订单页勾选订单 → 打印面单，合并成一个 PDF 打印。
   （以后接上平台开放接口，可以直接从平台取面单，不用上传。）
2) 自制面单：手工订单 / 私下成交 / 自己找快递时用。100×150mm 热敏纸，带订单号、运单号条形码。
"""
import io
import os
import re
import time

from . import db
from .config import DATA_DIR

LABEL_DIR = os.path.join(DATA_DIR, "labels")


def _pypdf():
    try:
        import pypdf
        return pypdf
    except ImportError as e:
        raise ValueError("缺少 PDF 组件。Windows 请重新双击 1_setup.bat；NAS 重启容器会自动安装") from e


def _norm(s):
    return re.sub(r"[\s\-]", "", str(s or "")).upper()


def import_pdf(fileobj, user="", via=""):
    """拆分平台面单 PDF，按页面文字里的订单号/运单号对应订单。返回 {matched, unmatched_pages, pages, order_nos}
    via：从哪来的（例如「插件 · Shopee」，v2.35 浏览器扩展转交），写进订单日志。"""
    pypdf = _pypdf()
    data = fileobj.read()
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
    except Exception as e:  # 不是 PDF
        raise ValueError(f"读不了这个 PDF：{e}") from e
    c = db.conn()
    rows = c.execute("SELECT id, order_no, tracking_no FROM orders WHERE status NOT IN ('cancelled') "
                     "AND order_time>=?", (time.time() - 90 * 86400,)).fetchall()
    keys, nos = [], {}
    for r in rows:
        nos[r["id"]] = r["order_no"]
        for k in (r["order_no"], r["tracking_no"]):
            k = _norm(k)
            if len(k) >= 6:
                keys.append((k, r["id"]))
    keys.sort(key=lambda x: -len(x[0]))
    os.makedirs(LABEL_DIR, exist_ok=True)
    matched, unmatched, pages_by_order = [], [], {}
    for i, page in enumerate(reader.pages):
        try:
            text = _norm(page.extract_text() or "")
        except Exception:  # 图片型 PDF
            text = ""
        oid = next((o for k, o in keys if k in text), None)
        if oid is None:
            unmatched.append(i + 1)
            continue
        pages_by_order.setdefault(oid, []).append(i)
    for oid, idxs in pages_by_order.items():
        w = pypdf.PdfWriter()
        for i in idxs:
            w.add_page(reader.pages[i])
        name = f"{oid}.pdf"
        with open(os.path.join(LABEL_DIR, name), "wb") as f:
            w.write(f)
        c.execute("UPDATE orders SET label_file=? WHERE id=?", (name, oid))
        from . import orders
        orders.log(oid, user, "上传平台面单", f"{len(idxs)} 页" + (f" · {via}" if via else ""), commit=False)
        matched.append(oid)
    c.commit()
    return {"pages": len(reader.pages), "matched": len(matched), "unmatched_pages": unmatched,
            "order_nos": [nos.get(o, "") for o in matched],
            "hint": "" if not unmatched else "有的页面没找到订单号/运单号：可能是图片型 PDF，或这些订单还没导入系统"}


def merged_pdf(order_ids):
    """把选中订单的平台面单合并成一个 PDF。返回 (bytes, 有面单的订单id, 没面单的订单id)"""
    pypdf = _pypdf()
    c = db.conn()
    w = pypdf.PdfWriter()
    have, missing = [], []
    for oid in order_ids:
        r = c.execute("SELECT label_file FROM orders WHERE id=?", (oid,)).fetchone()
        path = os.path.join(LABEL_DIR, r["label_file"]) if r and r["label_file"] else None
        if not path or not os.path.exists(path):
            missing.append(oid)
            continue
        for p in pypdf.PdfReader(path).pages:
            w.add_page(p)
        have.append(oid)
    buf = io.BytesIO()
    if have:
        w.write(buf)
    return buf.getvalue(), have, missing


def mark_printed(order_ids, user="", kind="平台面单"):
    c = db.conn()
    now = time.time()
    from . import orders
    for oid in order_ids:
        c.execute("UPDATE orders SET label_printed_at=? WHERE id=?", (now, oid))
        orders.log(oid, user, f"打印{kind}", "", commit=False)
    c.commit()


# ---------------- Code 128 条形码（SVG）----------------
_C128 = ["212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213", "221312",
         "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132", "221231", "213212",
         "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211", "212123", "212321", "232121",
         "111323", "131123", "131321", "112313", "132113", "132311", "211313", "231113", "231311", "112133", "112331",
         "132131", "113123", "113321", "133121", "313121", "211331", "231131", "213113", "213311", "213131", "311123",
         "311321", "331121", "312113", "312311", "332111", "314111", "221411", "431111", "111224", "111422", "121124",
         "121421", "141122", "141221", "112214", "112412", "122114", "122411", "142112", "142211", "241211", "221114",
         "413111", "241112", "134111", "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112",
         "421211", "212141", "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311",
         "113141", "114131", "311141", "411131", "211412", "211214", "211232", "2331112"]


def code128_svg(text, height=50, module=2):
    text = "".join(ch for ch in str(text) if 32 <= ord(ch) < 127)
    if not text:
        return ""
    codes = [104] + [ord(ch) - 32 for ch in text]          # Code B
    chk = codes[0] + sum(i * v for i, v in enumerate(codes[1:], 1))
    codes += [chk % 103, 106]
    bars, x = [], 10 * module
    for code in codes:
        pat = _C128[code]
        for j, w in enumerate(pat):
            w = int(w) * module
            if j % 2 == 0:
                bars.append(f'<rect x="{x}" y="0" width="{w}" height="{height}"/>')
            x += w
    total = x + 10 * module
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {height}" width="100%" height="{height}" '
            f'preserveAspectRatio="none">{"".join(bars)}</svg>')


def self_made_html(orders, cfg):
    """自制面单：每单一张 100×150mm。"""
    from html import escape as h
    sender = " ".join(x for x in (cfg.get("sender_name"), cfg.get("sender_phone")) if x)
    s_addr = cfg.get("sender_address") or ""
    css = ("@page{size:100mm 150mm;margin:0}*{box-sizing:border-box}body{margin:0;font:12px 'Leelawadee UI','Tahoma',"
           "'Microsoft YaHei',sans-serif;color:#000}.lb{width:100mm;height:150mm;padding:4mm;page-break-after:always;"
           "display:flex;flex-direction:column;gap:2mm;overflow:hidden}.box{border:1.5px solid #000;padding:2mm}"
           ".big{font-size:17px;font-weight:700}.pc{font-size:30px;font-weight:800;letter-spacing:2px}"
           ".row{display:flex;justify-content:space-between;align-items:center}.cod{border:2px solid #000;font-size:18px;"
           "font-weight:800;padding:1mm 3mm}.small{font-size:10px}.bc{text-align:center}.bc div{font-size:11px;"
           "letter-spacing:1px}.note{border:1.5px dashed #000;padding:1.5mm;font-weight:700}"
           "@media screen{body{background:#ddd}.lb{background:#fff;margin:8px auto}.noprint{text-align:center;padding:8px}}"
           "@media print{.noprint{display:none}}")
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>面单 ใบปะหน้า</title><style>{css}</style></head><body>"
           "<div class='noprint'><button onclick='print()' style='font-size:16px;padding:6px 20px'>打印 / พิมพ์</button>"
           " <span class='small'>打印机选择 100×150mm 纸张，缩放 100%</span></div>"]
    for o in orders:
        items = "，".join(f"{i.get('sku')}×{i.get('qty') or 1}" for i in o.get("items") or [])
        track = o.get("tracking_no") or ""
        cod = o.get("cod")
        out.append(f"""<div class="lb">
  <div class="row"><span class="big">{h(o.get('carrier') or '')}</span>
    {f'<span class="cod">COD ฿{cod:,.0f}</span>' if cod else '<span class="small">ไม่เก็บเงินปลายทาง</span>'}</div>
  {f'<div class="bc">{code128_svg(track, 46)}<div>{h(track)}</div></div>' if track else ''}
  <div class="box"><div class="small">ผู้รับ / 收件人</div>
    <div class="big">{h(o.get('receiver') or o.get('buyer') or '')}　{h(o.get('phone') or '')}</div>
    <div>{h(o.get('address') or '（没有地址，请在订单详情里填写）')}</div>
    <div class="row"><span></span><span class="pc">{h(o.get('postcode') or '')}</span></div></div>
  <div class="box small"><div>ผู้ส่ง / 寄件人：{h(sender)}</div><div>{h(s_addr)}</div></div>
  <div class="bc">{code128_svg(o.get('order_no'), 34, 1)}<div>{h(o.get('platform') or '')} {h(o.get('order_no'))}</div></div>
  <div class="small">สินค้า：{h(items)}</div>
  {f'<div class="note small">{h(o.get("custom_note"))}</div>' if o.get('custom_note') else ''}
</div>""")
    out.append("</body></html>")
    return "".join(out)
