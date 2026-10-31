"""自定义平台面单模板（v2.34）：在平台面单旁边加自己的信息（类似 BigSeller 的「自定义面单」）。

平台面单本身（条码、运单号、分拣码、收寄件人）是平台 / 快递定的，不能改；能改的是：
面单放多大、要不要裁白边 / 转方向，以及旁边加一块「信息区」写自己要的东西（拣货、打包、防重复贴）。

存在设置 waybill_tpl（一个字典）：
  enabled   打印平台面单时按模板排（关掉 = 原样打印平台的 PDF）
  layout    below 面单下面加信息区（同一张纸，面单自动缩小）/ page 面单原样，后面另起一张打信息
  paper     纸张：100x150（默认）/ 100x180 / a6
  info_mm   信息区最少留多高（毫米，below 用）。v2.42：面单宽度占满纸、高度按比例，剩下的都给信息区；
            面单太长时才把面单缩小，给信息区留够这个高度
  font      信息区字号（pt）
  fields    显示哪些信息（见 FIELDS）
  sort      商品排序：loc 按货位（拣货走一趟）/ sku 按 SKU
  text      自定义一行字（例如「易碎品 轻拿轻放 / ของเปราะบาง」）
  crop      自动裁掉面单 PDF 的白边（A4 纸上的小面单也能放大）
  rotate    面单是横的就转成竖的
"""
from core.config import load_config, save_config

FIELDS = [
    ("order_no", "订单号", "เลขออเดอร์"),
    ("order_bc", "订单号条码", "บาร์โค้ดเลขออเดอร์"),
    ("items", "SKU × 数量", "SKU × จำนวน"),
    ("name", "商品名称", "ชื่อสินค้า"),
    ("spec", "规格 / 颜色", "ตัวเลือก / สี"),
    ("loc", "货位", "ช่องเก็บ"),
    ("total", "总件数", "จำนวนรวม"),
    ("buyer_note", "买家留言", "ข้อความผู้ซื้อ"),
    ("custom_note", "定制要求", "ความต้องการพิเศษ"),
    ("seller_note", "卖家备注", "หมายเหตุผู้ขาย"),
    ("shop", "店铺", "ร้าน"),
    ("count", "打印次数（补打时黑底提示）", "จำนวนครั้งที่พิมพ์"),
    ("time", "打印时间", "เวลาพิมพ์"),
]
FIELD_IDS = [f[0] for f in FIELDS]
# v2.46：信息区的样式：table 商品清单表格（像 BigSeller 的拣货清单）/ list 紧凑（一行一个商品）
STYLES = {"table": ("商品清单表格（图片、商品名、规格、SKU、数量一列一列）", "ตารางรายการสินค้า"),
          "list": ("紧凑（一行一个商品）", "แบบกะทัดรัด (หนึ่งบรรทัดต่อสินค้า)")}
# 商品清单表格的列（顺序可以调）：(id, 中文, 泰文, 印在表头的字)
COLS = [("img", "图片", "รูป", "Img"), ("name", "商品名", "ชื่อสินค้า", "Item"), ("spec", "规格 / 颜色", "ตัวเลือก / สี", "Variant"),
        ("sku", "SKU", "SKU", "SKU"), ("psku", "产品编号", "รหัสสินค้า", "P.SKU"), ("qty", "数量", "จำนวน", "Qty"),
        ("loc", "货位", "ช่องเก็บ", "Loc")]
COL_IDS = [c[0] for c in COLS]
DEFAULT_COLS = [{"id": "img", "on": False}, {"id": "name", "on": True}, {"id": "spec", "on": True}, {"id": "sku", "on": True},
                {"id": "psku", "on": False}, {"id": "qty", "on": True}, {"id": "loc", "on": True}]
# 按平台可以单独设的（内容）；纸张、版式、裁边、转向所有平台共用（一次打印只能是一种纸）
CONTENT_KEYS = ("style", "cols", "fields", "font", "text", "qty_circle", "name_lines", "sort")
PLATFORMS = {"lazada": "Lazada", "shopee": "Shopee", "tiktok": "TikTok", "manual": "手工单 / 其它"}
LAYOUTS = {"below": ("面单下面加信息（同一张纸，面单自动缩小）", "เพิ่มข้อมูลใต้ใบปะหน้า (แผ่นเดียว ย่อใบปะหน้าอัตโนมัติ)"),
           "page": ("面单原样，后面另起一张打信息", "ใบปะหน้าขนาดเดิม แล้วพิมพ์ข้อมูลอีกแผ่น")}
PAPERS = {"100x150": (100, 150), "100x180": (100, 180), "a6": (105, 148)}
PAPER_ZH = {"100x150": "100×150 毫米（热敏 4×6 寸）", "100x180": "100×180 毫米（加长热敏纸）", "a6": "A6 105×148 毫米"}
PAPER_TH = {"100x150": "100×150 มม. (กระดาษความร้อน 4×6 นิ้ว)", "100x180": "100×180 มม. (กระดาษความร้อนแบบยาว)", "a6": "A6 105×148 มม."}
DEFAULT = {"enabled": False, "layout": "below", "paper": "100x150", "info_mm": 12, "font": 9,
           "fields": ["order_no", "items", "spec", "loc", "total", "buyer_note", "custom_note", "count"],
           "sort": "loc", "text": "", "crop": True, "rotate": True,
           "style": "table", "cols": DEFAULT_COLS, "qty_circle": True, "name_lines": 2}


def _int(v, lo, hi, d):
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError):
        return d


def clean(d):
    d = dict(d or {})
    t = dict(DEFAULT)
    t["enabled"] = d.get("enabled") in (True, 1, "1", "true", "on")
    t["layout"] = d.get("layout") if d.get("layout") in LAYOUTS else DEFAULT["layout"]
    t["paper"] = d.get("paper") if d.get("paper") in PAPERS else DEFAULT["paper"]
    mm = d.get("info_mm")
    if mm in (34, "34"):                       # v2.42：以前的默认 34 是固定高度（面单缩得太小），改成最少留 12
        mm = DEFAULT["info_mm"]
    t["info_mm"] = _int(mm, 8, 70, DEFAULT["info_mm"])
    t["info_mm"] = min(t["info_mm"], PAPERS[t["paper"]][1] - 60)       # 面单区至少留 60 毫米
    t["font"] = _int(d.get("font"), 7, 14, DEFAULT["font"])
    f = d.get("fields")
    t["fields"] = [x for x in FIELD_IDS if x in f] if isinstance(f, (list, tuple)) else list(DEFAULT["fields"])
    t["sort"] = d.get("sort") if d.get("sort") in ("loc", "sku") else "loc"
    t["text"] = str(d.get("text") or "").strip()[:80]
    for k in ("crop", "rotate", "qty_circle"):
        t[k] = DEFAULT[k] if d.get(k) is None else d.get(k) in (True, 1, "1", "true", "on")
    t["style"] = d.get("style") if d.get("style") in STYLES else DEFAULT["style"]
    t["name_lines"] = _int(d.get("name_lines"), 1, 3, DEFAULT["name_lines"])
    cols, seen = [], set()
    for c in d.get("cols") if isinstance(d.get("cols"), list) else []:
        cid = c.get("id") if isinstance(c, dict) else c
        if cid in COL_IDS and cid not in seen:
            seen.add(cid)
            cols.append({"id": cid, "on": bool(c.get("on", True)) if isinstance(c, dict) else True})
    cols += [dict(c) for c in DEFAULT_COLS if c["id"] not in seen]       # 新加的列补在后面
    if not any(c["on"] for c in cols):
        cols = [dict(c) for c in DEFAULT_COLS]
    t["cols"] = cols
    return t


def load(cfg=None, platform=None):
    """模板。platform 给了且这个平台单独设过内容（waybill_tpl_by），内容用它的，纸张 / 版式用通用的。"""
    cfg = cfg or load_config()
    base = clean({**DEFAULT, **(cfg.get("waybill_tpl") or {})})
    over = ((cfg.get("waybill_tpl_by") or {}).get(platform) or {}) if platform else {}
    if not over:
        return base
    return clean({**base, **{k: v for k, v in over.items() if k in CONTENT_KEYS}})


def plat_key(platform):
    return platform if platform in PLATFORMS else "manual"


def save(d, platform=None):
    """保存通用模板；platform 给了就只存这个平台的内容（d 为 None / {"same": True} 时去掉单独设置，跟通用一样）。"""
    cfg = load_config()
    if not platform:
        t = clean({**load(cfg), **(d or {})})
        save_config({"waybill_tpl": t})
        return t
    by = dict(cfg.get("waybill_tpl_by") or {})
    if not d or d.get("same"):
        by.pop(platform, None)
    else:
        t = clean({**load(cfg), **d})
        by[platform] = {k: t[k] for k in CONTENT_KEYS}
    save_config({"waybill_tpl_by": by})
    return load(load_config(), platform)
