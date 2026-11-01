"""数量怎么显示（v2.55）：整个仓库页面（库存表、货位列表、按商品、货位图、抽屉、手机）里「某个物品的数量」都走这一个函数，
只在这里改显示格式（例如耗材显示成「2 卷 · 1.97 kg」）。接口把它的结果放在 qty_text（中文单位）/ qty_text_th（泰文单位）。

qty_text(qty, unit, item=None, lang="zh") → 纯文本（不带 HTML）。item 是 inv_items 的一行（dict），可能是 None。
默认格式 = 以前库存表的写法：克 → 「1,970 g ≈ 1.97 kg」，其它 → 「12 个」。"""

U_TH = {"个": "ชิ้น", "卷": "ม้วน", "张": "แผ่น", "件": "ชิ้น", "米": "เมตร", "瓶": "ขวด", "盒": "กล่อง", "套": "ชุด"}


def _num(v, d=2):
    s = f"{float(v or 0):,.{d}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def unit_label(unit, lang="zh"):
    return (U_TH.get(unit) or unit or "") if lang == "th" else (unit or "")


def qty_text(qty, unit, item=None, lang="zh"):
    if unit == "g":
        return f"{_num(qty, 0)} g ≈ {_num((qty or 0) / 1000.0, 2)} kg"
    return f"{_num(qty, 2)} {unit_label(unit, lang)}".strip()


def both(qty, unit, item=None):
    """接口用：{qty_text, qty_text_th}"""
    return {"qty_text": qty_text(qty, unit, item, "zh"), "qty_text_th": qty_text(qty, unit, item, "th")}
