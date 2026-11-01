"""数量怎么显示（v2.55）：整个仓库页面（库存表、货位列表、按商品、货位图、抽屉、手机）里「某个物品的数量」都走这一个函数，
只在这里改显示格式（例如耗材显示成「2 卷 · 1.97 kg」）。接口把它的结果放在 qty_text（中文单位）/ qty_text_th（泰文单位）。

qty_text(qty, unit, item=None, lang="zh") → 纯文本（不带 HTML）。item 是 inv_items 的一行（dict），可能是 None。
默认格式 = 以前库存表的写法：克 → 「1,970 g ≈ 1.97 kg」，其它 → 「12 个」。"""

from core.inventory import units

U_TH = {"个": "ชิ้น", "卷": "ม้วน", "张": "แผ่น", "件": "ชิ้น", "米": "เมตร", "瓶": "ขวด", "盒": "กล่อง", "套": "ชุด"}


def _num(v, d=2):
    s = f"{float(v or 0):,.{d}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def unit_label(unit, lang="zh"):
    return (U_TH.get(unit) or unit or "") if lang == "th" else (unit or "")


class Ctx:
    """一次请求里共用的耗材卷数据（懒加载：没有耗材就一条都不查）。"""

    def __init__(self, c=None):
        self.c = c
        self._st = None
        self._loc = None

    @property
    def stats(self):
        if self._st is None:
            self._st = units.spool_stats(self.c)
        return self._st

    @property
    def loc(self):
        if self._loc is None:
            self._loc = units.loc_stats(self.c)
        return self._loc


def _is_fil(item):
    return bool(item) and (item.get("category") == "filament")


def _fil_text(qty, item, lang, ctx, loc_id):
    """耗材：整个物品 → 「2 卷（1 整卷 + 1 开封卷）· 1.97 kg」；某个货位 → 「1 卷 · 1.0 kg」（树脂 = 瓶 + 毫升）。没有料卷记录时只说重量。"""
    mat = item.get("material")
    k = (mat, item.get("color"))
    ctx = ctx or Ctx()
    i = 0 if lang == "zh" else 1
    if loc_id is not None:
        st = (ctx.loc.get(k) or {}).get(loc_id)
        if st:
            return units.loc_text(mat, st["rolls"], st["grams"])[i]
        return units.fmt_g(qty)
    u = item.get("units")
    if u and abs((u.get("grams") or 0) - float(qty or 0)) < 0.5:
        return u["text_zh" if lang == "zh" else "text_th"]
    st = ctx.stats.get(k)
    if st and abs(st["grams"] - float(qty or 0)) < 0.5:
        return units.stock_text(mat, st)[i]
    return units.fmt_g(qty)


def qty_text(qty, unit, item=None, lang="zh", ctx=None, loc_id=None):
    """item = inv_items 的一行（要有 category / material / color 才能认出耗材）；loc_id = 这个数量是某个货位上的（耗材显示该货位几卷）。
    耗材走 core/inventory/units.py 的文字，其他物品照旧。"""
    if _is_fil(item) and (unit == "g" or not unit or item.get("material") is not None):
        return _fil_text(qty, item, lang, ctx, loc_id)
    if unit == "g":
        return f"{_num(qty, 0)} g ≈ {_num((qty or 0) / 1000.0, 2)} kg"
    return f"{_num(qty, 2)} {unit_label(unit, lang)}".strip()


def both(qty, unit, item=None, ctx=None, loc_id=None):
    """接口用：{qty_text, qty_text_th}"""
    return {"qty_text": qty_text(qty, unit, item, "zh", ctx, loc_id), "qty_text_th": qty_text(qty, unit, item, "th", ctx, loc_id)}
