"""数字显示格式（v2.54.1）：模型尺寸 / 体积不显示浮点噪声（52.18000030517578 → 52.2）。只改显示，不改存的数据。"""


def num(v, digits=1):
    """四舍五入到 digits 位，去掉多余的 0：18.0 → "18"，52.18000030517578 → "52.2"；不是数字返回空串。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x != x or x in (float("inf"), float("-inf")):
        return ""
    s = f"{round(x, digits):.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def size_text(size, sep=" × ", digits=1, unit=" mm"):
    """[52.18, 64.89, 18] → "52.2 × 64.9 × 18 mm"。"""
    if not size:
        return ""
    parts = [num(x, digits) for x in size]
    return sep.join(parts) + unit if all(parts) else ""


def cm_from_mm(v, digits=1):
    """毫米 → 厘米（数字，保留 digits 位）。"""
    try:
        return round(float(v) / 10.0, digits)
    except (TypeError, ValueError):
        return 0.0
