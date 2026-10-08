"""平台面单排版（v2.34）：面单 PDF 每页 → 图片（自动裁白边、横的转竖）→ 按模板拼成打印页（HTML，每单一张或两张）。

PDF 转图片用 pypdfium2（requirements.txt；NAS 重启容器时自动安装）。没装好时 available() = False，
打印平台面单自动退回「原样打印 PDF」，不影响发货。
图片缓存在 data/cache/waybill/（同一个文件同一页只转一次）。
"""
import hashlib
import io
import os
import random
import time
from html import escape as h

from core.config import DATA_DIR
from core.labels import code128_svg

from . import template as T

CACHE = os.path.join(DATA_DIR, "cache", "waybill")
DPI = 300


def available():
    try:
        import pypdfium2  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def page_count(path):
    import pypdf
    try:
        return max(1, len(pypdf.PdfReader(path).pages))
    except Exception:  # noqa: BLE001
        return 1


def _crop(img, margin):
    """裁掉四周的白边（留 margin 像素）。"""
    bw = img.point(lambda v: 255 if v < 235 else 0)
    box = bw.getbbox()
    if not box:
        return img
    l, t, r, b = box
    return img.crop((max(0, l - margin), max(0, t - margin), min(img.width, r + margin), min(img.height, b + margin)))


def _clean_cache():
    if random.random() > 0.05:
        return
    cut = time.time() - 30 * 86400
    try:
        for f in os.listdir(CACHE):
            p = os.path.join(CACHE, f)
            if os.path.getmtime(p) < cut:
                os.remove(p)
    except OSError:
        pass


def awb_png(path, page=0, crop=True, rotate=True):
    """面单 PDF 的第 page 页 → PNG（灰度，300dpi）。"""
    st = os.stat(path)
    key = hashlib.md5(f"{os.path.abspath(path)}|{st.st_mtime}|{st.st_size}|{page}|{crop}|{rotate}|{DPI}".encode()).hexdigest()[:20]
    out = os.path.join(CACHE, key + ".png")
    if os.path.exists(out):
        with open(out, "rb") as f:
            return f.read()
    import pypdfium2 as pdfium
    from PIL import Image
    pdf = pdfium.PdfDocument(path)
    try:
        if page >= len(pdf):
            raise ValueError("面单没有这一页")
        img = pdf[page].render(scale=DPI / 72).to_pil()
    finally:
        pdf.close()
    img = img.convert("L")
    if crop:
        img = _crop(img, int(DPI / 25.4 * 1.2))
    if rotate and img.width > img.height * 1.05:
        img = img.transpose(Image.ROTATE_270)          # 横的面单顺时针转成竖的
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    data = buf.getvalue()
    os.makedirs(CACHE, exist_ok=True)
    tmp = f"{out}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, out)
    _clean_cache()
    return data


# ---------------- 信息区 ----------------
def _loc_key(codes, sort_key):
    return sort_key(codes[0][0]) if codes else (9,)


def _items(o, tpl, where, sort_key):
    items = [dict(it) for it in o.get("items") or []]
    for it in items:
        it["_loc"] = where.get(it.get("sku") or "", [])
    if tpl["sort"] == "loc":
        items.sort(key=lambda it: (_loc_key(it["_loc"], sort_key), it.get("sku") or ""))
    else:
        items.sort(key=lambda it: it.get("sku") or "")
    return items


def info_html(o, tpl, n_print, where, sort_key, full=False, now=None):
    """信息区：订单号 · 店铺 · 共 N 件 · 第 N 次打印；商品一行一个（□ SKU ×数量 名称 规格 [货位]）；留言 / 定制要求 / 备注；自定义文字。"""
    f = set(tpl["fields"])
    items = _items(o, tpl, where, sort_key)
    total = sum(int(it.get("qty") or 1) for it in items)
    head = []
    if "order_no" in f:
        head.append(f'<b class="ono">{h(o.get("order_no") or "")}</b>')
    if "shop" in f and (o.get("shop") or o.get("platform")):
        head.append(f'<span>{h(o.get("shop") or o.get("platform") or "")}</span>')
    if "total" in f:
        head.append(f'<span>共 {total} 件 / {total} ชิ้น</span>')
    if "time" in f:
        head.append(f'<span>{time.strftime("%m-%d %H:%M", time.localtime(now or time.time()))}</span>')
    if "count" in f:
        head.append(f'<span class="reprint">补打 第{n_print}次 / พิมพ์ซ้ำ</span>' if n_print > 1 else f'<span class="pc">#{n_print}</span>')
    lines = []
    for it in items:
        bits = ['<span class="bx"></span>']
        if "items" in f:
            bits.append(f'<b>{h(it.get("sku") or "")}</b><span class="q">×{int(it.get("qty") or 1)}</span>')
        if "name" in f and it.get("name"):
            bits.append(f'<span class="nm">{h(it.get("name"))}</span>')
        if "spec" in f and (it.get("variation") or it.get("color")):
            bits.append(f'<span class="sp">{h(it.get("variation") or it.get("color"))}</span>')
        if "loc" in f and it["_loc"]:
            bits.append(f'<span class="lc">{h(" ".join(c for c, _q in it["_loc"][:2]))}</span>')
        if len(bits) > 1:
            lines.append(f'<div class="it">{"".join(bits)}</div>')
    notes = []
    for k, tag in (("buyer_note", "留言 ข้อความ"), ("custom_note", "定制 สั่งทำ"), ("seller_note", "备注 หมายเหตุ")):
        if k in f and o.get(k):
            notes.append(f'<div class="nt"><b>{tag}</b> {h(o.get(k))}</div>')
    # 估计信息区放得下几行商品；放不下的合成「还有 N 项」（一行都放不下就加在第一行后面）
    line_mm = tpl["font"] * 0.3528 * 1.3
    room = (T.PAPERS[tpl["paper"]][1] - 6 if full else tpl["info_mm"] - 2)
    room -= line_mm * (1 + len(notes) + (1.1 if tpl["text"] else 0)) + (6.5 if "order_bc" in f else 0)
    cap = max(1, int(room / line_mm + 0.15))
    if len(lines) > cap:
        if cap == 1:
            rest = len(lines) - 1
            lines = [lines[0].replace('<div class="it">', '<div class="it"><span class="more1">' + f'+{rest} รายการ/项</span>', 1)]
        else:
            rest = len(lines) - (cap - 1)
            lines = lines[:cap - 1] + [f'<div class="it more">…还有 {rest} 项（见拣货单）/ อีก {rest} รายการ</div>']
    bc = (f'<div class="obc">{code128_svg(o.get("order_no") or "", height=30, module=1)}</div>'
          if "order_bc" in f and o.get("order_no") else "")
    txt = f'<div class="txt">{h(tpl["text"])}</div>' if tpl["text"] else ""
    return (f'<div class="info{" full" if full else ""}"><div class="ihd">{"".join(head)}</div>{bc}'
            f'{"".join(lines)}{"".join(notes)}{txt}</div>')


def _css(tpl):
    w, hh = T.PAPERS[tpl["paper"]]
    return f"""@page {{ size: {w}mm {hh}mm; margin: 0 }}
* {{ box-sizing: border-box }}
body {{ margin: 0; font-family: 'Leelawadee UI', Tahoma, 'Microsoft YaHei', 'PingFang SC', sans-serif; color: #000 }}
.wb {{ width: {w}mm; height: {hh}mm; page-break-after: always; display: flex; flex-direction: column; overflow: hidden; position: relative }}
.awb {{ flex: 1 1 auto; min-height: 0; display: flex; align-items: center; justify-content: center; padding: 1mm }}
.awb img {{ width: 100%; height: 100%; object-fit: contain; image-rendering: crisp-edges }}
.info {{ flex: 0 0 {tpl['info_mm']}mm; border-top: .5mm dashed #000; padding: 1mm 2mm; font-size: {tpl['font']}pt; line-height: 1.3; overflow: hidden }}
.info.full {{ flex: 1 1 auto; border-top: 0; padding: 3mm }}
.ihd {{ display: flex; flex-wrap: wrap; gap: 0 2.5mm; align-items: center; font-weight: 700 }}
.ihd .ono {{ font-size: 1.1em }}
.reprint {{ background: #000; color: #fff; padding: 0 1.5mm; border-radius: 1mm }}
.pc {{ font-weight: 400 }}
.obc {{ height: 6mm; margin: .3mm 0 }} .obc svg {{ height: 100%; width: 60% }}
.it {{ display: flex; gap: 1.5mm; align-items: center; white-space: nowrap; overflow: hidden }}
.it .bx {{ flex: 0 0 auto; width: .9em; height: .9em; border: .3mm solid #000 }}
.it .q {{ font-weight: 800 }} .it .nm {{ overflow: hidden; text-overflow: ellipsis; min-width: 0 }} .it .sp {{ flex: 0 0 auto }}
.it .lc {{ margin-left: auto; flex: 0 0 auto; border: .3mm solid #000; padding: 0 1mm; font-weight: 700; font-family: monospace }}
.it.more {{ font-style: italic }} .more1 {{ order: 9; margin-left: 1mm; background: #000; color: #fff; padding: 0 1mm; border-radius: 1mm; flex: 0 0 auto }}
.nt {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis }} .nt b {{ border: .3mm solid #000; padding: 0 .8mm; font-size: .85em }}
.txt {{ text-align: center; font-weight: 700; border-top: .3mm solid #000; margin-top: .5mm }}
.pg2 {{ position: absolute; right: 2mm; bottom: 1mm; font-size: 8pt }}
@media screen {{ body {{ background: #ddd }} .wb {{ background: #fff; margin: 8px auto; box-shadow: 0 1px 4px #0003 }}
  .noprint {{ text-align: center; padding: 8px; font-size: 14px }} .noprint .miss {{ color: #b91c1c; text-align: left; max-width: 520px; margin: 6px auto }} }}
@media print {{ .noprint {{ display: none }} }}"""


def _sample_awb():
    import base64
    bars = "".join(f"<rect x='{8 + i * 2.1:.1f}' y='22' width='{(1.2 if i % 3 else 0.6):.1f}' height='18'/>" for i in range(40))
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 150' width='100' height='150'>"
           "<rect x='1' y='1' width='98' height='148' fill='white' stroke='black' stroke-width='.8'/>"
           "<rect x='1' y='1' width='98' height='14' fill='black'/>"
           "<text x='50' y='10.5' font-size='7' fill='white' text-anchor='middle' font-family='sans-serif'>SAMPLE AWB</text>"
           f"<g fill='black'>{bars}</g>"
           "<text x='50' y='46' font-size='5' text-anchor='middle' font-family='monospace'>TH0123456789A</text>"
           "<text x='6' y='60' font-size='5' font-family='sans-serif'>Receiver 081-234-5678</text>"
           "<text x='6' y='68' font-size='4' font-family='sans-serif'>99/9 Sukhumvit Rd. Bangkok</text>"
           "<text x='94' y='86' font-size='12' font-weight='bold' text-anchor='end' font-family='sans-serif'>10110</text>"
           "<rect x='6' y='96' width='88' height='26' fill='none' stroke='black' stroke-width='.5'/>"
           "<text x='50' y='112' font-size='9' font-weight='bold' text-anchor='middle' font-family='sans-serif'>BKK-01 / A12</text>"
           "<text x='6' y='138' font-size='4' font-family='sans-serif'>Sender</text></svg>")
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


SAMPLE_AWB = _sample_awb()


def compose(entries, tpl, where, sort_key, missing=(), title="平台面单", autoprint=True):
    """entries: [(订单, [面单图片地址...], 第几次打印)]。missing: [(订单号, 原因)] 显示在页面上方（不打印）。"""
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>{h(title)} ใบปะหน้า</title><style>{_css(tpl)}</style></head><body>",
           "<div class='noprint'><button onclick='print()' style='font-size:16px;padding:6px 20px'>打印 / พิมพ์</button> "
           f"打印机选 {h(T.PAPER_ZH[tpl['paper']])}，缩放 100% / ขนาดจริง 100%"]
    if missing:
        out.append("<div class='miss'><b>这些订单没有平台面单，没打 / ออเดอร์เหล่านี้ไม่มีใบปะหน้า：</b><br>" +
                   "<br>".join(f"{h(no)}：{h(why)}" for no, why in missing) + "</div>")
    out.append("</div>")
    now = time.time()
    for o, imgs, n in entries:
        imgs = imgs or [SAMPLE_AWB]
        for i, src in enumerate(imgs):
            more = f'<div class="pg2">{i + 1}/{len(imgs)}</div>' if len(imgs) > 1 else ""
            if tpl["layout"] == "below":
                inf = info_html(o, tpl, n, where, sort_key, now=now) if i == 0 else ""
                out.append(f'<div class="wb"><div class="awb"><img src="{h(src)}" alt=""></div>{inf}{more}</div>')
            else:
                out.append(f'<div class="wb"><div class="awb"><img src="{h(src)}" alt=""></div>{more}</div>')
        if tpl["layout"] == "page":
            out.append(f'<div class="wb">{info_html(o, tpl, n, where, sort_key, full=True, now=now)}</div>')
    if autoprint:                                     # 面单图片都加载好再弹打印
        out.append("<script>(function(){var im=[].slice.call(document.images),left=im.length;"
                   "function go(){if(--left<=0)setTimeout(function(){print()},200)}"
                   "if(!left)setTimeout(function(){print()},300);im.forEach(function(x){if(x.complete)go();else{x.onload=go;x.onerror=go}})})()</script>")
    out.append("</body></html>")
    return "".join(out)


SAMPLE_ORDER = {"id": 0, "order_no": "2610090001ABCD", "platform": "shopee", "shop": "3D Shop TH", "tracking_no": "TH0123456789A",
                "buyer_note": "ขอสีชมพูนะคะ", "custom_note": "刻字：MALI", "seller_note": "",
                "items": [{"sku": "3DP0001-PK", "name": "猫咪小夜灯 โคมไฟแมว", "variation": "粉色 ชมพู", "qty": 2},
                          {"sku": "3DP0007-WH", "name": "手机支架", "variation": "白色", "qty": 1},
                          {"sku": "3DP0012-BK-L", "name": "收纳盒", "variation": "黑色 L", "qty": 1}]}
SAMPLE_WHERE = {"3DP0001-PK": [("A1-02-03", 5)], "3DP0007-WH": [("A1-01-01", 2)], "3DP0012-BK-L": [("B2-03-04", 1)]}


def preview_html(tpl, sort_key):
    """设置页预览：示例订单 + 示例面单（第 2 次打印，看补打提示）。"""
    return compose([(SAMPLE_ORDER, [SAMPLE_AWB], 2)], tpl, SAMPLE_WHERE, sort_key, title="预览", autoprint=False)
