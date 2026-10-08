"""打包核对 / 发货交接扫什么码（v2.32）。

设置（设置 → 订单与售后 → 打包与交接扫码）：
  scan_order_key   打开订单 / 交接时扫什么：both 订单号或快递单号 / tracking 只认快递单号 / order 只认订单号
  pack_item_mode   打包时怎么核对商品（产品里可以单独设置，空 = 用这里的）：
                     scan 扫商品码（SKU 条码，或者后处理时贴的内部标签）
                     tap  点一下确认（看图片和数量逐行点 ✓，适合没条码的自产件）
                     none 只核对订单（扫到订单就算核对完）
  item_label_size  内部商品标签尺寸：50x30 / 40x30 / 60x40（毫米）
内部商品标签：Code128 条码，内容就是 SKU（扫码枪不管什么键盘布局都能正确输入），下面印 SKU、品名、颜色、订单号。
对外：find_order(code, key)  item_mode(product, cfg)  labels_html(orders, cfg)
"""
from html import escape as h

from core import db, store
from core.config import load_config

KEYS = {"both": "订单号或快递单号", "tracking": "只认快递单号", "order": "只认订单号"}
MODES = {"scan": "扫商品码", "tap": "点一下确认", "none": "只核对订单"}
SIZES = {"50x30": (50, 30), "40x30": (40, 30), "60x40": (60, 40)}


def key_setting(cfg=None):
    k = (cfg or load_config()).get("scan_order_key") or "both"
    return k if k in KEYS else "both"


def find_order(code, key=None):
    """按设置认订单：返回 orders 表的一行，找不到 None。先精确匹配，再去掉「-」匹配。"""
    key = key or key_setting()
    code = str(code or "").strip()
    if not code:
        return None
    cols = {"both": ("order_no", "tracking_no"), "tracking": ("tracking_no",), "order": ("order_no",)}[key]
    c = db.conn()
    where = " OR ".join(f"{x}=?" for x in cols)
    r = c.execute(f"SELECT * FROM orders WHERE {where} ORDER BY id DESC LIMIT 1", (code,) * len(cols)).fetchone()
    if not r:
        k = code.replace("-", "")
        where = " OR ".join(f"REPLACE({x},'-','')=?" for x in cols)
        r = c.execute(f"SELECT * FROM orders WHERE {where} ORDER BY id DESC LIMIT 1", (k,) * len(cols)).fetchone()
    return r


def not_found_msg(code, key=None):
    key = key or key_setting()
    hint = {"both": "订单号或快递单号", "tracking": "快递单号（设置里规定了只认快递单号）", "order": "订单号（设置里规定了只认订单号）"}[key]
    return f"找不到「{code}」对应的订单——请扫{hint}"


def item_mode(product, cfg=None):
    m = (product or {}).get("pack_check") or ""
    if m in MODES:
        return m
    m = (cfg or load_config()).get("pack_item_mode") or "tap"
    return m if m in MODES else "tap"


def modes_for_items(items, cfg=None):
    """订单明细每一行：核对方式（按产品）+ 产品图（「点一下确认」时对着图看）。返回 [{check, img}]。"""
    cfg = cfg or load_config()
    cache, out = {}, []
    for it in items:
        pid = it.get("product_id") or (str(it.get("sku") or "").split("-")[0])
        if pid not in cache:
            try:
                cache[pid] = store.load(pid)
            except Exception:  # noqa: BLE001  产品被删了 / SKU 对不上
                cache[pid] = None
        p = cache[pid]
        img = ((p or {}).get("images") or [None])[0]
        out.append({"check": item_mode(p, cfg),
                    "img": f"/files/{p['id']}/{'out' if img.get('processed') else 'raw'}/{img['file']}" if p and img else ""})
    return out


def labels_html(orders, cfg=None):
    """内部商品标签：每件一张（数量几件就几张）。"""
    from core import labels
    cfg = cfg or load_config()
    w, hh = SIZES.get(cfg.get("item_label_size") or "50x30", (50, 30))
    cards = []
    for o in orders:
        for it in o.get("items") or []:
            sku = str(it.get("sku") or "").strip().upper()
            if not sku:
                continue
            for _ in range(max(1, int(it.get("qty") or 1))):
                cards.append(f"""<div class="lb"><div class="bc">{labels.code128_svg(sku, height=40, module=2)}</div>
<div class="sku">{h(sku)}</div><div class="nm">{h(str(it.get('name') or '')[:40])}</div>
<div class="ft"><span>{h(str(it.get('color') or ''))}</span><span>#{h(str(o.get('order_no') or ''))}</span></div></div>""")
    if not cards:
        cards.append('<p style="font:14px sans-serif">这些订单里没有 SKU，打不了商品标签</p>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>商品标签</title><style>
@page {{ size: {w}mm {hh}mm; margin: 0 }}
body {{ margin: 0 }}
.lb {{ width: {w}mm; height: {hh}mm; box-sizing: border-box; padding: 1.5mm 2mm; page-break-after: always; overflow: hidden;
      font-family: sans-serif; display: flex; flex-direction: column }}
.bc {{ height: {round(hh * 0.42)}mm }} .bc svg {{ height: 100% }}
.sku {{ font: bold 11pt monospace; text-align: center; letter-spacing: .5px }}
.nm {{ font-size: 7pt; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }}
.ft {{ display: flex; justify-content: space-between; font-size: 7pt; margin-top: auto }}
</style></head><body>{''.join(cards)}<script>setTimeout(() => print(), 300)</script></body></html>"""
