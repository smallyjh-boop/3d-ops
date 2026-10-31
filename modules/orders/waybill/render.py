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
from ..labeltext import Texts

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


def _head_html(o, tpl, n_print, total, now, extra=True):
    f = set(tpl["fields"])
    head = []
    if "order_no" in f:
        head.append(f'<b class="ono">{h(o.get("order_no") or "")}</b>')
    if "total" in f:
        head.append(f'<span>รวม {total} ชิ้น/pcs</span>')
    if "count" in f:
        head.append(f'<span class="reprint">พิมพ์ซ้ำ/Reprint #{n_print}</span>' if n_print > 1 else f'<span class="pc">#{n_print}</span>')
    if extra and "shop" in f and (o.get("shop") or o.get("platform")):
        head.append(f'<span>{h(o.get("shop") or o.get("platform") or "")}</span>')
    if extra and "time" in f:
        head.append(f'<span>{time.strftime("%m-%d %H:%M", time.localtime(now or time.time()))}</span>')
    return f'<div class="ihd">{"".join(head)}</div>'


def _cod_html(o):
    from core.labels import cod_txt
    return f'<span class="cod-tag">COD ฿{h(cod_txt(o["cod"]))}</span>' if o.get("cod") else ""


def _row_mm(tpl):
    line_mm = tpl["font"] * 0.3528 * 1.3
    img = any(c["id"] == "img" and c["on"] for c in tpl["cols"])
    return max(line_mm * tpl["name_lines"] + 1.8, 10.2 if img else 0)       # 加上格子的内边距和线


def table_html(o, tpl, n_print, where, sort_key, full=False, now=None, tx=None, info_h=None):
    """v2.46 商品清单表格（像 BigSeller 的拣货清单）：表头 → 一个商品一行（图片 / 商品名 / 规格 / SKU / 数量画圈 / 货位，
    列可以开关、调顺序）→ 留言 / 定制要求 → 自定义文字。放不下的行合成「+N」，打印前会提示改成单独打一张。"""
    f = set(tpl["fields"])
    items = _items(o, tpl, where, sort_key)
    total = sum(int(it.get("qty") or 1) for it in items)
    cols = [c["id"] for c in tpl["cols"] if c["on"]]
    title = {c[0]: c[3] for c in T.COLS}
    line_mm = tpl["font"] * 0.3528 * 1.3
    notes = [(k, f'<div class="nt"><b>{tag}</b> {h(o.get(k))}</div>')
             for k, tag in (("buyer_note", "ข้อความ Note"), ("custom_note", "สั่งทำ Custom"), ("seller_note", "หมายเหตุ Remark"))
             if k in f and o.get(k)]
    room = (T.PAPERS[tpl["paper"]][1] - 6 if full else (info_h or tpl["info_mm"]) - 2.5)
    fixed = line_mm * (2.4 + len(notes) + (1.1 if tpl["text"] else 0)) + 1
    cap = max(1, int((room - fixed) / _row_mm(tpl) + 0.1))
    rows = []
    for i, it in enumerate(items):
        q = int(it.get("qty") or 1)
        cell = {"img": (f'<img src="{h(tx.image(it))}" alt="">' if tx.image(it) else '<span class="noimg"></span>'),
                "name": f'<div class="cl" style="-webkit-line-clamp:{tpl["name_lines"]}">{h(tx.name(it))}</div>',
                "spec": f'<b>{h(tx.spec(it))}</b>', "sku": f'<span class="mono">{h(it.get("sku") or "")}</span>',
                "psku": h(it.get("product_id") or ""),
                "qty": (f'<span class="qc">{q}</span>' if q > 1 and tpl["qty_circle"] else f'<b>{q}</b>'),
                "loc": h(" ".join(c for c, _q in it["_loc"][:2]))}
        rows.append(f'<tr><td class="n">{i + 1}</td>' + "".join(f'<td class="c-{c}">{cell[c]}</td>' for c in cols) + "</tr>")
    if len(rows) > cap:
        rest = len(rows) - (cap - 1)
        rows = rows[:cap - 1] + [f'<tr><td colspan="{len(cols) + 1}" class="more">+{rest} รายการ / items (ดูใบหยิบสินค้า / see pick list)</td></tr>']
    table = (f'<table class="itb"><thead><tr><th>#</th>{"".join(f"<th class=c-{c}>{title[c]}</th>" for c in cols)}</tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table>')
    bc = (f'<div class="obc">{code128_svg(o.get("order_no") or "", height=30, module=1)}</div>'
          if "order_bc" in f and o.get("order_no") and full else "")
    txt = f'<div class="txt">{h(tpl["text"])}</div>' if tpl["text"] else ""
    st = f' style="flex-basis:{info_h:.1f}mm;font-size:{tpl["font"]}pt"' if info_h and not full else f' style="font-size:{tpl["font"]}pt"'
    return (f'<div class="info tbl{" full" if full else ""}"{st}>{_head_html(o, tpl, n_print, total, now)}{_cod_html(o) if full else ""}{bc}'
            f'{table}{"".join(n[1] for n in notes)}{txt}</div>')


def info_html(o, tpl, n_print, where, sort_key, full=False, now=None, tx=None, info_h=None):
    if tpl.get("style") == "table":
        if tx is None:
            from core.config import load_config
            tx = Texts(load_config())
        return table_html(o, tpl, n_print, where, sort_key, full, now, tx, info_h)
    return list_html(o, tpl, n_print, where, sort_key, full, now, tx, info_h)


def list_html(o, tpl, n_print, where, sort_key, full=False, now=None, tx=None, info_h=None):
    """信息区：订单号 · 店铺 · 共 N 件 · 第 N 次打印；商品一行一个（□ SKU ×数量 名称 规格 [货位]）；留言 / 定制要求 / 备注；自定义文字。
    v2.42：印出来的只有泰文 / 英文（商品名、规格是中文时换成产品的泰文，见 labeltext）。"""
    if tx is None:
        from core.config import load_config
        tx = Texts(load_config())
    f = set(tpl["fields"])
    items = _items(o, tpl, where, sort_key)
    total = sum(int(it.get("qty") or 1) for it in items)
    use_bc = "order_bc" in f and bool(o.get("order_no"))
    use_txt = bool(tpl["text"])
    use_name, extra_head = "name" in f, True

    def build_lines():
        out = []
        for it in items:
            bits = ['<span class="bx"></span>']
            if "items" in f:
                bits.append(f'<b>{h(it.get("sku") or "")}</b><span class="q">×{int(it.get("qty") or 1)}</span>')
            sp = tx.spec(it) if "spec" in f else ""        # v2.44.2：规格（颜色）放在商品名前面，放不下时截的是商品名
            if sp:
                bits.append(f'<span class="sp">{h(sp)}</span>')
            nm = tx.name(it) if use_name else ""
            if nm:
                bits.append(f'<span class="nm">{h(nm)}</span>')
            if "loc" in f and it["_loc"]:
                bits.append(f'<span class="lc">{h(" ".join(c for c, _q in it["_loc"][:2]))}</span>')
            if len(bits) > 1:
                out.append(f'<div class="it">{"".join(bits)}</div>')
        return out

    notes = [(k, f'<div class="nt"><b>{tag}</b> {h(o.get(k))}</div>')
             for k, tag in (("buyer_note", "ข้อความ Note"), ("custom_note", "สั่งทำ Custom"), ("seller_note", "หมายเหตุ Remark"))
             if k in f and o.get(k)]
    # v2.42：信息区放不下时按优先级减：商品 SKU × 数量 / 规格和客户要求（留言、定制）最重要；
    # 依次去掉 自定义文字 → 订单号条码 → 卖家备注 → 商品名 → 表头的店铺 / 时间；还放不下就把商品排成紧凑的一段（一行好几个）
    line_mm = tpl["font"] * 0.3528 * 1.3
    room = (T.PAPERS[tpl["paper"]][1] - 6 if full else (info_h or tpl["info_mm"]) - 2.5)

    def fixed_mm():
        return line_mm * (1 + len(notes) + (1.1 if use_txt else 0)) + (6.5 if use_bc else 0)

    lines = build_lines()
    for step in ("txt", "bc", "seller", "name", "head"):
        if fixed_mm() + line_mm * len(lines) <= room:
            break
        if step == "txt":
            use_txt = False
        elif step == "bc":
            use_bc = False
        elif step == "seller":
            notes = [n for n in notes if n[0] != "seller_note"]
        elif step == "name" and use_name:
            use_name = False
            lines = build_lines()
        elif step == "head":
            extra_head = False
    cap = max(1, int((room - fixed_mm()) / line_mm + 0.15))
    if len(lines) > cap:
        # 紧凑：「SKU×数量 规格」一个接一个排，自动换行；估一行能放多少字，放不下的最后写「+N」
        per_line = _per_line(tpl)
        toks = _tokens(items, f, tx)
        shown, used, line_n = [], 0, 1
        for i, t in enumerate(toks):
            ln = len(t) + 3
            if used and used + ln > per_line:
                line_n, used = line_n + 1, 0
            left = len(toks) - i - 1
            if line_n > cap or (line_n == cap and left and used + ln + 8 > per_line):
                break
            shown.append(t)
            used += ln
        rest = len(toks) - len(shown)
        more = f' <span class="more1">+{rest} รายการ/items</span>' if rest else ""
        chips = "".join('<span><i class="bx"></i>' + h(t) + "</span>" for t in shown)
        lines = [f'<div class="itc">{chips}{more}</div>']
    head = []
    if "order_no" in f:
        head.append(f'<b class="ono">{h(o.get("order_no") or "")}</b>')
    if "total" in f:                        # 表头一行放不下时右边的先被挤掉：重要的放前面
        head.append(f'<span>รวม {total} ชิ้น/pcs</span>')
    if "count" in f:
        head.append(f'<span class="reprint">พิมพ์ซ้ำ/Reprint #{n_print}</span>' if n_print > 1 else f'<span class="pc">#{n_print}</span>')
    if extra_head and "shop" in f and (o.get("shop") or o.get("platform")):
        head.append(f'<span>{h(o.get("shop") or o.get("platform") or "")}</span>')
    if extra_head and "time" in f:
        head.append(f'<span>{time.strftime("%m-%d %H:%M", time.localtime(now or time.time()))}</span>')
    bc = (f'<div class="obc">{code128_svg(o.get("order_no") or "", height=30, module=1)}</div>' if use_bc else "")
    txt = f'<div class="txt">{h(tpl["text"])}</div>' if use_txt else ""
    st = f' style="flex-basis:{info_h:.1f}mm"' if info_h and not full else ""
    return (f'<div class="info{" full" if full else ""}"{st}><div class="ihd">{"".join(head)}</div>{bc}'
            f'{"".join(lines)}{"".join(n[1] for n in notes)}{txt}</div>')


def _css(tpl):
    w, hh = T.PAPERS[tpl["paper"]]
    return f"""@page {{ size: {w}mm {hh}mm; margin: 0 }}
* {{ box-sizing: border-box }}
body {{ margin: 0; font-family: 'Leelawadee UI', Tahoma, 'Microsoft YaHei', 'PingFang SC', sans-serif; color: #000 }}
.wb {{ width: {w}mm; height: {hh - 0.4}mm; page-break-after: always; break-inside: avoid; display: flex; flex-direction: column; overflow: hidden; position: relative }}
.awb {{ flex: 1 1 auto; min-height: 0; flex-shrink: 0; display: flex; align-items: center; justify-content: center; padding: 1mm }}
.awb img {{ width: 100%; height: 100%; object-fit: contain; image-rendering: crisp-edges }}
.info {{ flex: 0 1 {tpl['info_mm']}mm; border-top: .5mm dashed #000; padding: 1mm 2mm; font-size: {tpl['font']}pt; line-height: 1.3; overflow: hidden }}
.info.full {{ flex: 1 1 auto; border-top: 0; padding: 3mm }}
.ihd {{ display: flex; flex-wrap: nowrap; gap: 0 2.5mm; align-items: center; font-weight: 700; white-space: nowrap; overflow: hidden }}
.itc {{ display: flex; flex-wrap: wrap; gap: 0 2.5mm; font-weight: 700; font-size: .92em }} .itc span {{ white-space: nowrap }} .itc .bx {{ display: inline-block; width: .8em; height: .8em; border: .3mm solid #000; margin-right: .8mm; vertical-align: -.05em }}
.ihd .ono {{ font-size: 1.1em }}
.reprint {{ background: #000; color: #fff; padding: 0 1.5mm; border-radius: 1mm }}
.pc {{ font-weight: 400 }}
.obc {{ height: 6mm; margin: .3mm 0 }} .obc svg {{ height: 100%; width: 60% }}
.it {{ display: flex; gap: 1.5mm; align-items: center; white-space: nowrap; overflow: hidden }}
.it .bx {{ flex: 0 0 auto; width: .9em; height: .9em; border: .3mm solid #000 }}
.it .q {{ font-weight: 800 }} .it .nm {{ overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 1 1 auto }} .it .sp {{ flex: 0 0 auto; font-weight: 700 }}
.it .lc {{ margin-left: auto; flex: 0 0 auto; border: .3mm solid #000; padding: 0 1mm; font-weight: 700; font-family: monospace }}
.it.more {{ font-style: italic }} .more1 {{ order: 9; margin-left: 1mm; background: #000; color: #fff; padding: 0 1mm; border-radius: 1mm; flex: 0 0 auto }}
.nt {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis }} .nt b {{ border: .3mm solid #000; padding: 0 .8mm; font-size: .85em }}
.txt {{ text-align: center; font-weight: 700; border-top: .3mm solid #000; margin-top: .5mm }}
.pg2 {{ position: absolute; right: 2mm; bottom: 1mm; font-size: 8pt }}
.itb {{ width: 100%; border-collapse: collapse; margin: .5mm 0; table-layout: fixed }}
.itb th, .itb td {{ border: .25mm solid #000; padding: .3mm .8mm; vertical-align: middle; text-align: left; overflow: hidden }}
.itb th {{ font-size: .85em; background: #eee }} .itb td.n, .itb th:first-child {{ width: 4mm; text-align: center }}
.itb .c-img {{ width: 10mm }} .itb .c-img img {{ width: 9mm; height: 9mm; object-fit: cover; display: block }}
.itb .noimg {{ display: block; width: 9mm; height: 9mm; border: .2mm dashed #999 }}
.itb .c-qty {{ width: 8mm; text-align: center }} .itb .c-loc {{ width: 11mm; font-size: .85em }} .itb .c-sku {{ width: 19mm; word-break: break-all; font-size: .85em }}
.itb .c-psku {{ width: 12mm; font-size: .85em }} .itb .c-spec {{ width: 16mm }}
.itb .cl {{ display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden }}
.itb .qc {{ display: inline-block; min-width: 1.5em; height: 1.5em; line-height: 1.4em; border: .35mm solid #000; border-radius: 50%; font-weight: 800; text-align: center }}
.itb td.more {{ font-style: italic; text-align: center }}
.cod-tag {{ border: .4mm solid #000; padding: 0 1.5mm; font-weight: 800; margin-left: 2mm }}
.info.tbl {{ padding: 1mm 1.5mm }}
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


def split_mm(tpl, aspect, need=0):
    """v2.42：面单下面加信息时，(面单区高度, 信息区高度) 毫米。面单宽度占满纸（左右各留 1 毫米），高度按面单比例（高 / 宽）；
    剩下的都给信息区；信息区不够「info_mm」和这单必须印的内容（need：商品 × 数量、买家留言、定制要求）时才把面单缩小，
    面单区至少留 60 毫米。不知道比例时按信息区 = 这两个里大的。"""
    w, hh = T.PAPERS[tpl["paper"]]
    info_min = min(max(tpl["info_mm"], need or 0), hh - 60)
    if not aspect:
        return hh - info_min, info_min
    awb = min((w - 2) * aspect + 2, hh - info_min)
    return awb, hh - awb


def _per_line(tpl):
    """紧凑排商品时一行大约放几个字（按字号估）。"""
    return max(10, int((T.PAPERS[tpl["paper"]][0] - 5) / (tpl["font"] * 0.3528 * 0.92 * 0.58)))


def _tokens(items, f, tx):
    return [f'{it.get("sku") or ""}×{int(it.get("qty") or 1)}' + (f" {tx.spec(it)}" if "spec" in f and tx.spec(it) else "")
            for it in items]


def _compact_lines(toks, per_line):
    n, used = 1, 0
    for t in toks:
        ln = len(t) + 3
        if used and used + ln > per_line:
            n, used = n + 1, 0
        used += ln
    return n


def need_mm(o, tpl, tx):
    """这单信息区必须印的高度（毫米）：表头一行 + 全部商品（3 个以内一个一行，多了紧凑排；表格样式一行一个）+ 买家留言 + 定制要求。"""
    f = set(tpl["fields"])
    items = o.get("items") or []
    line_mm = tpl["font"] * 0.3528 * 1.3
    if tpl.get("style") == "table":
        n_notes = sum(1 for k in ("buyer_note", "custom_note") if k in f and o.get(k))
        return 3.5 + line_mm * (2.4 + n_notes) + _row_mm(tpl) * len(items) + 0.5
    n_items = len(items) if len(items) <= 3 else min(len(items), _compact_lines(_tokens(items, f, tx), _per_line(tpl)))
    n_notes = sum(1 for k in ("buyer_note", "custom_note") if k in f and o.get(k))
    return 2.5 + line_mm * (1 + n_items + n_notes) + 0.5


LABEL_MIN_MM = 100        # 面单区缩到比这还小就看不清了：打印前提示这次改成单独打一张商品清单


def overflow(o, tpl, tx):
    """面单下面加商品清单时放不下（面单会被缩到 LABEL_MIN_MM 以下）→ True。"""
    return tpl["layout"] == "below" and need_mm(o, tpl, tx) > T.PAPERS[tpl["paper"]][1] - LABEL_MIN_MM


def compose(entries, tpl, where, sort_key, missing=(), title="Waybill", autoprint=True, aspects=None, tpl_of=None):
    """entries: [(订单, [面单图片地址...], 第几次打印)]。missing: [(订单号, 原因)] 显示在页面上方（不打印）。
    aspects: {订单 id: 面单第一页的 高 / 宽}（v2.42，用来让面单宽度占满纸）。"""
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>{h(title)} ใบปะหน้า</title><style>{_css(tpl)}</style></head><body>",
           "<div class='noprint'><button onclick='print()' style='font-size:16px;padding:6px 20px'>打印 / พิมพ์</button> "
           f"打印机选 {h(T.PAPER_ZH[tpl['paper']])}，缩放 100% / ขนาดจริง 100%"]
    if missing:
        out.append("<div class='miss'><b>这些订单没有平台面单，没打 / ออเดอร์เหล่านี้ไม่มีใบปะหน้า：</b><br>" +
                   "<br>".join(f"{h(no)}：{h(why)}" for no, why in missing) + "</div>")
    out.append("</div>")
    now = time.time()
    from core.config import load_config
    tx = Texts(load_config())
    for o, imgs, n in entries:
        imgs = imgs or [SAMPLE_AWB]
        ot = tpl_of(o) if tpl_of else tpl         # v2.46：每单按平台用自己的模板内容（纸张 / 版式共用）
        for i, src in enumerate(imgs):
            more = f'<div class="pg2">{i + 1}/{len(imgs)}</div>' if len(imgs) > 1 else ""
            if tpl["layout"] == "below" and i == 0:
                awb_h, inf_h = split_mm(tpl, (aspects or {}).get(o.get("id")), need_mm(o, ot, tx))
                inf = info_html(o, ot, n, where, sort_key, now=now, tx=tx, info_h=inf_h)
                out.append(f'<div class="wb"><div class="awb" style="flex-basis:{awb_h:.1f}mm"><img src="{h(src)}" alt=""></div>{inf}{more}</div>')
            else:
                out.append(f'<div class="wb"><div class="awb"><img src="{h(src)}" alt=""></div>{more}</div>')
        if tpl["layout"] == "page":
            out.append(f'<div class="wb">{info_html(o, ot, n, where, sort_key, full=True, now=now, tx=tx)}</div>')
    if autoprint:                                     # 面单图片都加载好再弹打印
        out.append("<script>(function(){var im=[].slice.call(document.images),left=im.length;"
                   "function go(){if(--left<=0)setTimeout(function(){print()},200)}"
                   "if(!left)setTimeout(function(){print()},300);im.forEach(function(x){if(x.complete)go();else{x.onload=go;x.onerror=go}})})()</script>")
    out.append("</body></html>")
    return "".join(out)


SAMPLE_ORDER = {"id": 0, "order_no": "2610090001ABCD", "platform": "shopee", "shop": "3D Shop TH", "tracking_no": "TH0123456789A",
                "buyer_note": "ขอสีชมพูนะคะ", "custom_note": "สลักชื่อ: MALI", "seller_note": "",
                "items": [{"sku": "3DP0001-PK", "name": "โคมไฟแมว Cat night light", "variation": "ชมพู Pink", "qty": 2},
                          {"sku": "3DP0007-WH", "name": "ที่วางมือถือ Phone stand", "variation": "ขาว White", "qty": 1},
                          {"sku": "3DP0012-BK-L", "name": "กล่องเก็บของ Storage box", "variation": "ดำ Black L", "qty": 1}]}
SAMPLE_WHERE = {"3DP0001-PK": [("A1-02-03", 5)], "3DP0007-WH": [("A1-01-01", 2)], "3DP0012-BK-L": [("B2-03-04", 1)]}


def preview_html(tpl, sort_key):
    """设置页预览：示例订单 + 示例面单（第 2 次打印，看补打提示）。"""
    return compose([(SAMPLE_ORDER, [SAMPLE_AWB], 2)], tpl, SAMPLE_WHERE, sort_key, title="Preview", autoprint=False,
                   aspects={SAMPLE_ORDER["id"]: 1.5})
