"""光固化切片文件：尽量从文件里读出打印时间、树脂用量、层高、层数（读不出来时由人手填）。

支持读取：Anycubic Photon Workshop 的文件（.pm5s / .pm5 / .pm7 / .pwmx / .pwmb / .pwma / .pm3 / .pm4n …，
文件头都是 "ANYCUBIC"），格式参考开源软件 UVtools 的说明。其他格式（.ctb / .goo …）先手填。
读出来的数会做合理性检查，不合理的一律当作没读到，避免用错误的时间 / 用量排产和算成本。
"""
import os
import struct

ANYCUBIC_MARK = b"ANYCUBIC"


def _read_section(f, addr, mark):
    f.seek(addr)
    head = f.read(16)
    if len(head) < 16 or not head[:12].rstrip(b"\0").startswith(mark):
        return None
    length = struct.unpack("<I", head[12:16])[0]
    if length <= 0 or length > 1 << 20:
        return None
    return f.read(length)


def parse_anycubic(path):
    with open(path, "rb") as f:
        head = f.read(64)
        if not head.startswith(ANYCUBIC_MARK):
            return {}
        version, _areas, header_addr, _p1, _preview, _p2, layerdef_addr = struct.unpack("<7I", head[12:40])
        h = _read_section(f, header_addr, b"HEADER")
        if not h or len(h) < 72:
            return {}
        (pixel, layer_h, exp, wait, bexp, blayers, lift_h, lift_s, ret_s, volume, aa, rx, ry,
         weight, price, cur, per_layer, print_time) = struct.unpack("<10f3I2f3I", h[:72])
        layers = None
        ld = _read_section(f, layerdef_addr, b"LAYERDEF")
        if ld and len(ld) >= 4:
            layers = struct.unpack("<I", ld[:4])[0]
    out = {"format": "anycubic", "version": version}
    if 0.005 <= layer_h <= 0.3:
        out["layer_height_mm"] = round(layer_h, 3)
    if 0.3 <= exp <= 60:
        out["exposure_s"] = round(exp, 2)
    if 0 < print_time < 7 * 86400:
        out["hours"] = round(print_time / 3600, 2)
    if 0 < volume < 5000:
        out["volume_ml"] = round(volume, 1)
    if 0 < weight < 6000:
        out["weight_g"] = round(weight, 1)
    if layers and 0 < layers < 100000:
        out["layers"] = layers
        if out.get("layer_height_mm"):
            out["height_mm"] = round(layers * out["layer_height_mm"], 1)
    if rx and ry and rx < 30000 and ry < 30000:
        out["resolution"] = f"{rx}×{ry}"
    return out


def parse(path, density=1.1):
    """返回 {hours, grams, volume_ml, layers, height_mm, layer_height_mm, ...}；读不到的项不返回。"""
    try:
        info = parse_anycubic(path)
    except (OSError, struct.error, ValueError):
        info = {}
    if info.get("volume_ml") and not info.get("weight_g"):
        info["weight_g"] = round(info["volume_ml"] * float(density or 1.1), 1)
    if info.get("weight_g"):
        info["grams"] = info["weight_g"]
    return info


def model_from_ext(filename):
    """按扩展名猜机型（只认确定的几种）。"""
    from .fleet import MODELS
    ext = os.path.splitext(filename.lower())[1]
    for m in MODELS:
        if ext in (m.get("ext") or []) and ext != ".goo":
            return m["name"]
    return None
