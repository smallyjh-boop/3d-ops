"""切片预览：把 G-code 里的挤出路径整理成浏览器 3D 预览用的紧凑数据（按层、按类型：外墙/内墙/填充/支撑…）。

输出格式（gzip 压缩）：
  4 字节小端整数 = 头部 JSON 长度，头部 JSON（补齐到 4 的倍数），然后是 Int16 坐标流 (x, y)，单位 0.05mm。
  每条连续路径之间用 (-32768, -32768) 隔开。
  头部：{"v":1, "scale":0.05, "types":[{key, zh, color}], "layers":[z...], "chunks":[[层, 类型序号, 整数个数], ...]}
结果缓存到 print_files/cache/，同一个文件只解析一次。
"""
import gzip
import io
import json
import math
import os
import re
import struct
import zipfile

SCALE = 0.05
BREAK = -32768
TYPES = [  # key, 中文, 颜色（和常见切片软件的配色接近）
    ("outer", "外墙", "#ff9f1c"),
    ("inner", "内墙", "#ffd166"),
    ("overhang", "悬空墙", "#3a86ff"),
    ("sparse", "稀疏填充", "#e63946"),
    ("solid", "实心填充", "#9d4edd"),
    ("top", "顶面", "#ff4d6d"),
    ("bottom", "底面", "#7b2cbf"),
    ("bridge", "桥接", "#4cc9f0"),
    ("support", "支撑", "#2ec4b6"),
    ("support_if", "支撑接触面", "#06d6a0"),
    ("brim", "帽檐 / 裙边", "#8d99ae"),
    ("other", "其他（擦嘴 / 换料塔等）", "#adb5bd"),
]
TYPE_IDX = {k: i for i, (k, _, _) in enumerate(TYPES)}


def _type_of(name):
    n = name.lower().strip()
    if "support" in n:
        return "support_if" if ("interface" in n or "transition" in n) else "support"
    if "overhang" in n:
        return "overhang"
    if "outer" in n or "external" in n:
        return "outer"
    if "inner" in n or n in ("perimeter", "wall"):
        return "inner"
    if "bridge" in n:
        return "bridge"
    if "top" in n or "ironing" in n:
        return "top"
    if "bottom" in n:
        return "bottom"
    if "sparse" in n or n in ("internal infill", "infill"):
        return "sparse"
    if "solid" in n or "gap" in n:
        return "solid"
    if "brim" in n or "skirt" in n:
        return "brim"
    return "other"


_NUM = re.compile(r"([XYZEIJF])([-+]?\d*\.?\d+)")


def parse(text, max_points=1_400_000):
    """解析 G-code → (layers_z, chunks)；chunks[(层, 类型序号)] = [路径点列表, ...]"""
    rel_e = True
    abs_xy = True
    x = y = z = 0.0
    e_last = 0.0
    ttype = "other"
    layer = -1
    layer_z = []
    marker_layers = ";LAYER_CHANGE" in text or "; CHANGE_LAYER" in text
    chunks = {}
    cur = None          # 当前路径（列表）
    cur_key = None
    min_d2 = 0.3 ** 2    # 太密的点合并（预览用不着那么细）

    def new_layer():
        nonlocal layer, cur
        layer += 1
        layer_z.append(None)
        cur = None

    def end_path():
        nonlocal cur
        cur = None

    for line in text.splitlines():
        if not line:
            continue
        c0 = line[0]
        if c0 == ";":
            if line.startswith(";TYPE:") or line.startswith("; FEATURE:"):
                ttype = _type_of(line.split(":", 1)[1])
                end_path()
            elif line.startswith(";LAYER_CHANGE") or line.startswith("; CHANGE_LAYER"):
                new_layer()
            continue
        cmd = line.split(";", 1)[0].strip()
        if not cmd:
            continue
        op = cmd.split(" ", 1)[0]
        if op in ("G1", "G0", "G2", "G3"):
            vals = dict(_NUM.findall(cmd))
            nx = float(vals["X"]) if "X" in vals else x
            ny = float(vals["Y"]) if "Y" in vals else y
            if not abs_xy:
                nx = x + float(vals.get("X", 0))
                ny = y + float(vals.get("Y", 0))
            nz = float(vals["Z"]) if "Z" in vals else z
            de = 0.0
            if "E" in vals:
                ev = float(vals["E"])
                de = ev if rel_e else ev - e_last
                if not rel_e:
                    e_last = ev
            moved = (nx != x or ny != y)
            if de > 0 and moved:
                if layer < 0 or (not marker_layers and (layer_z[layer] is None or abs(nz - layer_z[layer]) > 1e-4)
                                 and nz > (layer_z[layer] or -1)):
                    new_layer()
                if layer_z[layer] is None:
                    layer_z[layer] = nz
                key = (layer, TYPE_IDX[ttype])
                if cur is None or cur_key != key:
                    cur = [(x, y)]
                    cur_key = key
                    chunks.setdefault(key, []).append(cur)
                if op in ("G2", "G3") and ("I" in vals or "J" in vals):
                    cx, cy = x + float(vals.get("I", 0)), y + float(vals.get("J", 0))
                    a0, a1 = math.atan2(y - cy, x - cx), math.atan2(ny - cy, nx - cx)
                    r = math.hypot(x - cx, y - cy)
                    if op == "G2":   # 顺时针
                        if a1 >= a0:
                            a1 -= 2 * math.pi
                    elif a1 <= a0:
                        a1 += 2 * math.pi
                    n = max(2, min(36, int(abs(a1 - a0) * r / 0.8)))
                    for k in range(1, n):
                        a = a0 + (a1 - a0) * k / n
                        cur.append((cx + r * math.cos(a), cy + r * math.sin(a)))
                    cur.append((nx, ny))
                else:
                    # 上一个点离再前一个点很近时，直接把它挪到新位置（合并很短的小段，终点保持准确）
                    if len(cur) >= 2 and (nx - cur[-2][0]) ** 2 + (ny - cur[-2][1]) ** 2 < min_d2:
                        cur[-1] = (nx, ny)
                    else:
                        cur.append((nx, ny))
            elif moved:
                end_path()
            x, y, z = nx, ny, nz
        elif op == "M83":
            rel_e = True
        elif op == "M82":
            rel_e = False
        elif op == "G92":
            vals = dict(_NUM.findall(cmd))
            if "E" in vals:
                e_last = float(vals["E"])
        elif op == "G91":
            abs_xy = False
        elif op == "G90":
            abs_xy = True
    # 去掉没有挤出的层
    keep = [i for i, zz in enumerate(layer_z) if zz is not None]
    remap = {old: new for new, old in enumerate(keep)}
    out = {}
    for (ly, t), paths in chunks.items():
        if ly in remap:
            out[(remap[ly], t)] = [p for p in paths if len(p) >= 2]
    zs = [round(layer_z[i], 3) for i in keep]
    # 点太多时：稀疏填充、实心填充隔点取（浏览器吃不消）
    total = sum(len(p) for ps in out.values() for p in ps)
    if total > max_points:
        step = math.ceil(total / max_points) + 1
        for key, ps in out.items():
            if TYPES[key[1]][0] in ("sparse", "solid", "support", "other"):
                out[key] = [p[::step] + ([p[-1]] if (len(p) - 1) % step else []) for p in ps]
    return zs, out


def encode(zs, chunks):
    data = []
    heads = []
    for key in sorted(chunks):
        n0 = len(data)
        for p in chunks[key]:
            if len(p) < 2:
                continue
            for px, py in p:
                data.append(max(-32767, min(32767, int(round(px / SCALE)))))
                data.append(max(-32767, min(32767, int(round(py / SCALE)))))
            data.append(BREAK)
            data.append(BREAK)
        if len(data) > n0:
            heads.append([key[0], key[1], len(data) - n0])
    head = {"v": 1, "scale": SCALE, "types": [{"key": k, "zh": zh, "color": col} for k, zh, col in TYPES],
            "layers": zs, "chunks": heads}
    hb = json.dumps(head, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    hb += b" " * ((4 - len(hb) % 4) % 4)
    body = struct.pack("<I", len(hb)) + hb + struct.pack(f"<{len(data)}h", *data)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=5) as g:
        g.write(body)
    return buf.getvalue()


def read_gcode(path, kind):
    if kind == "3mf":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.startswith("Metadata/plate_") and n.endswith(".gcode")]
            if not names:
                raise ValueError("这个文件里没有 G-code")
            return z.read(sorted(names)[0]).decode("utf-8", "ignore")
    with open(path, "rb") as f:
        return f.read().decode("utf-8", "ignore")


def build(path, kind, cache_dir):
    """返回 gzip 后的预览数据（有缓存直接用）。"""
    os.makedirs(cache_dir, exist_ok=True)
    st = os.stat(path)
    cache = os.path.join(cache_dir, f"{os.path.basename(path)}.{int(st.st_mtime)}.{st.st_size}.tp.gz")
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            return f.read()
    from . import kernels
    blob = kernels.toolpath_blob(path, kind)        # 大文件交给电脑算（v2.20.2）
    # 清掉同一文件的旧缓存
    for n in os.listdir(cache_dir):
        if n.startswith(os.path.basename(path) + ".") and n.endswith(".tp.gz"):
            try:
                os.remove(os.path.join(cache_dir, n))
            except OSError:
                pass
    tmp = cache + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, cache)
    return blob
