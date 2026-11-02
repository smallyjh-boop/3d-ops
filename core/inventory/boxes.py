"""泰国邮政标准纸箱（v2.35）：发货用的纸箱统一按邮政规格，方便统计用量、整箱采购。

尺寸（宽 × 长 × 高，厘米）按泰国常见的邮政纸箱规格。每个产品在编辑页选一种（product["pack_box"]），
订单发货时默认用订单里最大的那个，打包页可以改；发货出库时扣这个纸箱的库存。
纸箱在库存里是「包材」物品，编码 BOX-<规格>（例如 BOX-2A），第一次用到时自动建档。
每个纸箱带空箱重量 weight_g（v2.55.1，算包裹重量）。
对外：catalog()  get(code)  item_code(code)  ensure_item(code)  fit(长, 宽, 高)  biggest(codes)
"""
from .. import db

# (规格, 宽, 长, 高 cm)
BOXES = [
    ("00", 9.75, 14, 6), ("0", 11, 17, 6), ("0+4", 11, 17, 10), ("AA", 13, 17, 7), ("A", 14, 20, 6), ("2A", 14, 20, 12),
    ("CD", 15, 15, 15), ("B", 17, 25, 9), ("2B", 17, 25, 18), ("C", 20, 30, 11), ("C+9", 20, 30, 20), ("D", 22, 35, 14),
    ("D+11", 22, 35, 25), ("E", 24, 40, 17), ("F", 30, 45, 20), ("G", 31, 36, 26), ("H", 40, 45, 34), ("I", 45, 55, 40),
]
# v2.55.1：空纸箱重量（克，单层瓦楞纸的大概值，算包裹重量用；以后实称了可以改这里）
BOX_WEIGHT = {"00": 20, "0": 25, "0+4": 35, "AA": 30, "A": 35, "2A": 55, "CD": 60, "B": 65, "2B": 100, "C": 110, "C+9": 150,
              "D": 160, "D+11": 230, "E": 230, "F": 320, "G": 330, "H": 550, "I": 800}
NONE = "none"          # 产品 / 订单：不用纸箱（例如用快递袋，快递袋按「每单 / 每件」规则扣）


def _fmt(x):
    return f"{x:g}"


def _row(code, w, l, h):
    size = f"{_fmt(w)}×{_fmt(l)}×{_fmt(h)}"
    return {"code": code, "w": w, "l": l, "h": h, "vol": w * l * h, "size": size, "weight_g": BOX_WEIGHT.get(code, 0),
            "zh": f"{code}（{size} cm）", "th": f"เบอร์ {code} ({size} ซม.)", "item_code": item_code(code)}


def catalog():
    return [_row(*b) for b in BOXES]


def get(code):
    code = str(code or "").strip().upper()
    return next((_row(*b) for b in BOXES if b[0].upper() == code), None)


def item_code(code):
    return f"BOX-{str(code).upper()}"


def ensure_item(code, user="系统"):
    """库存里这个规格的纸箱（包材），没有就建档（数量 0）。返回物品 id；不是标准规格返回 None。"""
    b = get(code)
    if not b:
        return None
    c = db.conn()
    r = c.execute("SELECT id FROM inv_items WHERE code=?", (b["item_code"],)).fetchone()
    if r:
        return r["id"]
    from . import ledger
    it = ledger.save_item({"code": b["item_code"], "name_zh": f"邮政纸箱 {b['code']}", "name_th": f"กล่องไปรษณีย์ เบอร์ {b['code']}",
                           "category": "pack", "unit": "个", "spec": f"{b['size']} cm"}, user)
    return it["id"]


def fit(length, width, height, margin=0.0):
    """放得下这个尺寸（厘米）的最小标准纸箱（三边排序后比较）；放不下返回 None。"""
    try:
        need = sorted(float(x) + margin for x in (length, width, height))
    except (TypeError, ValueError):
        return None
    if min(need) <= 0:
        return None
    for b in sorted(catalog(), key=lambda x: x["vol"]):
        if all(a >= n for a, n in zip(sorted((b["w"], b["l"], b["h"])), need)):
            return b["code"]
    return None


def biggest(codes):
    """几个规格里体积最大的一个（订单里有几样东西时，默认用最大的纸箱）。"""
    bs = [b for b in (get(c) for c in codes or []) if b]
    return max(bs, key=lambda b: b["vol"])["code"] if bs else ""
