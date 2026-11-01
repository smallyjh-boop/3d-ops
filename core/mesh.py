"""模型文件处理（不依赖 3D 库）：读 STL / 3MF，按摆放方向旋转，算尺寸和悬空面积，写出 STL 给切片用。

摆放方向和界面 3D 预览里的一致：
bottom 原始方向（底面朝下）、top 倒放、front 前面朝下、back 背面朝下、left 左侧朝下、right 右侧朝下。
（模型文件里 Z 轴朝上；3D 预览里的「前面」= 文件里的 -Y 方向）
"""
import os
import io
import re
import struct
import zipfile

import numpy as np

ORIENT_ZH = {"bottom": "原始方向（底面朝下）", "top": "倒放（顶面朝下）", "front": "前面朝下平放",
             "back": "背面朝下平放", "left": "左侧朝下平放", "right": "右侧朝下平放"}


def _load_stl(data):
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + n * 50 == len(data):
            arr = np.frombuffer(data, dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]),
                                count=n, offset=84)
            return arr["v"].astype(np.float64)
    text = data.decode("utf-8", "ignore")
    vs = re.findall(r"vertex\s+([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)", text)
    if not vs:
        raise ValueError("读不了这个 STL 文件")
    v = np.array(vs, dtype=np.float64)
    return v[: len(v) // 3 * 3].reshape(-1, 3, 3)


_V_ORDER = re.compile(rb'<(?:\w+:)?vertex\s+x="[^"]*"\s+y="[^"]*"\s+z="[^"]*"')
_T_ORDER = re.compile(rb'<(?:\w+:)?triangle\s+v1="\d+"\s+v2="\d+"\s+v3="\d+"')


def _between(buf, tag, start=0, end=None):
    """在 buf[start:end] 里找 <tag ...> … </tag>（允许命名空间前缀），返回内容的 (起, 止)，找不到返回 None。
    用 bytes.find，不用正则的 .*?，几十 MB 的 3MF 也很快。"""
    end = len(buf) if end is None else end
    m = re.compile(rb"<(?:\w+:)?" + tag + rb"[\s>]").search(buf, start, end)
    if not m:
        return None
    a = buf.find(b">", m.end() - 1, end) + 1
    close = re.compile(rb"</(?:\w+:)?" + tag + rb">").search(buf, a, end)
    if not close:
        return None
    return a, close.start()


def _mesh_arrays(buf, a, b):
    """一个 <mesh> 里的顶点、三角面 → 三角面数组。快速路径：属性顺序是 x y z / v1 v2 v3（几乎所有软件都是）。"""
    vr = _between(buf, rb"vertices", a, b)
    tr = _between(buf, rb"triangles", a, b)
    if not vr or not tr:
        return None
    vb, tb = buf[vr[0]:vr[1]], buf[tr[0]:tr[1]]
    nv, nt = vb.count(b"<"), tb.count(b"<")
    if not nv or not nt:
        return None
    head_v, head_t = vb[:4000], tb[:4000]
    # 抽查开头几十个元素的属性顺序都是 x y z / v1 v2 v3，才走快速路径
    if len(_V_ORDER.findall(head_v)) >= head_v.count(b"<vertex") + head_v.count(b":vertex") - 1 and \
            len(_T_ORDER.findall(head_t)) >= head_t.count(b"<triangle") + head_t.count(b":triangle") - 1:
        vv = re.findall(rb'\b[xyz]="([^"]*)"', vb)
        ii = re.findall(rb'\bv[123]="(\d+)"', tb)
        if len(vv) == nv * 3 and len(ii) == nt * 3:
            v = np.array(vv, dtype=np.float64).reshape(-1, 3)
            t = np.array(ii, dtype=np.int64).reshape(-1, 3)
            return v[t]
    # 慢速路径：属性顺序不一样的文件（逐个元素读属性，顺序随意）
    def attrs(block, tag, names):
        out = []
        for el in re.findall(rb"<(?:\w+:)?" + tag + rb"\b([^>]*)>", block):
            d = dict(re.findall(rb'\b(\w+)="([^"]*)"', el))
            try:
                out.append([d[n] for n in names])
            except KeyError:
                return None
        return out
    vs = attrs(vb, rb"vertex", (b"x", b"y", b"z"))
    ts = attrs(tb, rb"triangle", (b"v1", b"v2", b"v3"))
    if not vs or not ts:
        return None
    return np.array(vs, dtype=np.float64)[np.array(ts, dtype=np.int64)]


def _parse_3mf_model(xml):
    """一个 .model 文件（或其中一段）里的全部网格。xml 可以是 str 或 bytes。"""
    buf = xml.encode("utf-8") if isinstance(xml, str) else xml
    tris, pos = [], 0
    while True:
        r = _between(buf, rb"mesh", pos)
        if not r:
            break
        t = _mesh_arrays(buf, r[0], r[1])
        if t is not None and len(t):
            tris.append(t)
        pos = r[1] + 1
    return tris


# ---------------- 3MF 场景（v2.23）：按 build / component 的 transform 摆放 ----------------
# 拓竹 / Makerworld 的项目文件：每个零件在 3D/Objects/*.model 里，3dmodel.model 用 <component transform> 组装、
# <build><item transform> 摆到盘上（作者已经按打印方向摆好）。以前没算 transform，零件全叠在原点「混在一起」。
_OBJ_RE = re.compile(rb"<(?:\w+:)?object\b([^>]*)>")
_COMP_RE = re.compile(rb"<(?:\w+:)?component\b([^>]*?)/?>")
_ITEM_RE = re.compile(rb"<(?:\w+:)?item\b([^>]*?)/?>")
_ATTR_RE = re.compile(rb'([\w:]+)="([^"]*)"')


def _attrs(s):
    return {k.split(b":")[-1].decode(): v.decode("utf-8", "ignore") for k, v in _ATTR_RE.findall(s)}


def _mat(t):
    """3MF transform「m00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31 m32」→ (R 3x3, t)，点 p' = p @ R + t。"""
    if not t:
        return None
    try:
        v = [float(x) for x in t.split()]
    except ValueError:
        return None
    if len(v) != 12:
        return None
    return np.array(v[:9]).reshape(3, 3), np.array(v[9:12])


def _apply(tris, m):
    if m is None:
        return tris
    R, t = m
    return tris @ R + t


def _compose(inner, outer):
    """先 inner 再 outer。"""
    if inner is None:
        return outer
    if outer is None:
        return inner
    return inner[0] @ outer[0], inner[1] @ outer[0] + outer[1]


def _index_models(z):
    """{(路径, objectid): {"mesh": (buf, a, b) 或 None, "comps": [(路径, id, m)], "name": ...}}"""
    objs = {}
    for n in z.namelist():
        if not n.lower().endswith(".model"):
            continue
        buf = z.read(n)
        path = "/" + n.lstrip("/")
        pos = 0
        while True:
            m = _OBJ_RE.search(buf, pos)
            if not m:
                break
            at = _attrs(m.group(1))
            close = re.compile(rb"</(?:\w+:)?object>").search(buf, m.end())
            if not close:
                break
            a, b = m.end(), close.start()
            ent = {"name": at.get("name", ""), "mesh": None, "comps": []}
            r = _between(buf, rb"mesh", a, b)
            if r:
                ent["mesh"] = (buf, a, b)
            for cm in _COMP_RE.finditer(buf, a, b):
                ca = _attrs(cm.group(1))
                if ca.get("objectid"):
                    ent["comps"].append((ca.get("path") or path, ca["objectid"], _mat(ca.get("transform"))))
            objs[(path, at.get("id", ""))] = ent
            pos = close.end()
    return objs


def _resolve(objs, key, m, depth=0):
    ent = objs.get(key)
    if not ent or depth > 8:
        return []
    out = []
    if ent["mesh"]:
        buf, a, b = ent["mesh"]
        for t in _parse_3mf_model(buf[a:b]):
            out.append(_apply(t, m))
    for path, oid, cm in ent["comps"]:
        out += _resolve(objs, (path, oid), _compose(cm, m), depth + 1)
    return out


def _bambu_names(z):
    """拓竹 Metadata/model_settings.config 里的零件名：{objectid: 名字}。"""
    try:
        txt = z.read("Metadata/model_settings.config")
    except KeyError:
        return {}
    out = {}
    for m in re.finditer(rb'<object id="(\d+)">(.*?)</object>', txt, re.S):
        nm = re.search(rb'<metadata key="name" value="([^"]*)"', m.group(2))
        if nm:
            out[m.group(1).decode()] = nm.group(1).decode("utf-8", "ignore")
    return out


def scene_3mf(data):
    """按盘上的摆放读出每个零件：[(名字, 三角面)]。没有 <build> 时返回 None（按老方法读）。"""
    z = zipfile.ZipFile(io.BytesIO(data))
    root = next((n for n in z.namelist() if n.lower() in ("3d/3dmodel.model",)), None)
    if not root:
        return None
    rbuf = z.read(root)
    b = _between(rbuf, rb"build")
    if not b:
        return None
    items = [_attrs(m.group(1)) for m in _ITEM_RE.finditer(rbuf, b[0], b[1])]
    if not items:
        return None
    objs = _index_models(z)
    names = _bambu_names(z)
    rpath = "/" + root
    out = []
    for it in items:
        if it.get("printable") == "0":
            continue
        oid = it.get("objectid", "")
        parts = _resolve(objs, (it.get("path") or rpath, oid), _mat(it.get("transform")))
        if not parts:
            continue
        nm = names.get(oid) or (objs.get((rpath, oid)) or {}).get("name") or ""
        out.append((nm or f"组件 {len(out) + 1}", np.concatenate(parts)))
    return out or None


def colors_3mf(data):
    """v2.23：拓竹 / Orca 项目文件里的耗材颜色和每个零件用哪一槽。
    返回 {"filaments": [{"slot", "hex", "type"}], "parts": [{"name", "slot"}], "used": [槽], "painted": bool, "multicolor": bool}；
    读不到返回 None。"""
    import json
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    fil = []
    if "Metadata/project_settings.config" in names:
        try:
            ps = json.loads(z.read("Metadata/project_settings.config"))
            cols = ps.get("filament_colour") or []
            types = ps.get("filament_type") or []
            for i, c in enumerate(cols):
                fil.append({"slot": i + 1, "hex": str(c)[:7], "type": str(types[i]) if i < len(types) else ""})
        except (ValueError, KeyError):
            pass
    parts, used = [], set()
    if "Metadata/model_settings.config" in names:
        txt = z.read("Metadata/model_settings.config").decode("utf-8", "ignore")
        for m in re.finditer(r'<object id="(\d+)">(.*?)</object>', txt, re.S):
            body = m.group(2)
            nm = re.search(r'<metadata key="name" value="([^"]*)"', body)
            ex = re.search(r'<metadata key="extruder" value="(\d+)"', body)
            obj_slot = int(ex.group(1)) if ex else 1
            subs = re.findall(r'<part id="\d+"[^>]*>(.*?)</part>', body, re.S)
            slots = set()
            for sb in subs:
                e2 = re.search(r'<metadata key="extruder" value="(\d+)"', sb)
                slots.add(int(e2.group(1)) if e2 else obj_slot)
            slots = slots or {obj_slot}
            used |= slots
            parts.append({"name": nm.group(1) if nm else f"组件 {len(parts) + 1}", "slot": sorted(slots)[0] if len(slots) == 1 else sorted(slots)})
    painted = False
    for n in names:
        if n.lower().endswith(".model"):
            with z.open(n) as f:
                head = f.read(4_000_000)
            if b"paint_color=" in head or b"mmu_segmentation=" in head:
                painted = True
                break
    if not fil and not parts:
        return None
    used = sorted(used) or ([1] if fil else [])
    return {"filaments": fil, "parts": parts, "used": used, "painted": painted,
            "multicolor": painted or len(used) > 1}


def _load_3mf(data):
    try:
        sc = scene_3mf(data)
    except (zipfile.BadZipFile, KeyError, ValueError):
        sc = None
    if sc:
        return np.concatenate([t for _n, t in sc])
    z = zipfile.ZipFile(io.BytesIO(data))
    tris = []
    for n in z.namelist():
        if n.lower().endswith(".model"):
            tris += _parse_3mf_model(z.read(n))
    if not tris:
        raise ValueError("3MF 里没有找到模型")
    return np.concatenate(tris)


_CACHE = {}          # 最近读过的模型（同一个大模型常常一会儿算方向、一会儿算一盘放几个，不用每次重新读文件）
_CACHE_KEEP = 3


def cached(path, loader):
    """按 (路径, 修改时间, 大小) 缓存读模型的结果（只读数组，最多留 3 个）。"""
    try:
        st = os.stat(path)
    except OSError:
        return loader(path)
    key = (os.path.abspath(path), st.st_mtime, st.st_size, loader.__name__)
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE[key] = _CACHE.pop(key)          # 放到最后（最近用过）
        return hit
    val = loader(path)
    for arr in (val if isinstance(val, list) else [val]):
        a = arr[1] if isinstance(arr, tuple) else arr
        try:
            a.flags.writeable = False
        except (AttributeError, ValueError):
            pass
    _CACHE[key] = val
    while len(_CACHE) > _CACHE_KEEP:
        _CACHE.pop(next(iter(_CACHE)))
    return val


def _load_file(path):
    with open(path, "rb") as f:
        data = f.read()
    if path.lower().endswith(".3mf") or data[:2] == b"PK":
        return _load_3mf(data)
    return _load_stl(data)


def load(path):
    return cached(path, _load_file)


def rotate(tris, orient):
    """把选定的面转到朝下（-Z）。"""
    x, y, z = tris[..., 0], tris[..., 1], tris[..., 2]
    if orient == "top":
        out = np.stack([x, -y, -z], -1)
    elif orient == "front":       # -Y 朝下
        out = np.stack([x, -z, y], -1)
    elif orient == "back":        # +Y 朝下
        out = np.stack([x, z, -y], -1)
    elif orient == "left":        # -X 朝下
        out = np.stack([-z, y, x], -1)
    elif orient == "right":       # +X 朝下
        out = np.stack([z, y, -x], -1)
    else:
        out = tris.copy()
    mn = out.reshape(-1, 3).min(0)
    return out - np.array([mn[0], mn[1], mn[2]])


def size(tris):
    p = tris.reshape(-1, 3)
    return (p.max(0) - p.min(0)).round(2).tolist()


def stats(tris):
    """当前方向（Z 朝上）的几何信息：尺寸、底面贴平台面积、悬空面积。"""
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    nrm = np.cross(b - a, c - a)
    area2 = np.linalg.norm(nrm, axis=1)
    ok = area2 > 1e-9
    nrm, area, cz = nrm[ok] / area2[ok, None], area2[ok] / 2, tris[ok, :, 2].mean(1)
    zmin = tris[..., 2].min()
    dz = nrm[:, 2]
    contact = area[(dz < -0.98) & (cz - zmin < 0.3)].sum()
    over = area[(dz < -0.707) & ~((dz < -0.98) & (cz - zmin < 0.3))].sum()
    steep = area[(dz >= -0.707) & (dz < -0.5)].sum()
    s = size(tris)
    return {"size_mm": s, "height_mm": s[2], "contact_cm2": round(float(contact) / 100, 1),
            "overhang_cm2": round(float(over) / 100, 1), "steep_cm2": round(float(steep) / 100, 1), "footprint_mm": s[:2],
            "tall_ratio": round(float(s[2]) / max(1.0, min(s[0], s[1])), 2)}


def analyze_all(tris):
    out = []
    for k in ORIENT_ZH:
        st = stats(rotate(tris, k))
        st.update(key=k, label=ORIENT_ZH[k])
        st["score"] = round(st["overhang_cm2"] * 3 + st["steep_cm2"]
                            + (8 if st["contact_cm2"] < 1 else 3 if st["contact_cm2"] < 3 else 0)
                            + st["height_mm"] / max(1.0, max(st["size_mm"])) * 2, 2)
        out.append(st)
    return out


def write_stl(tris, path):
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n, axis=1)
    ln[ln == 0] = 1
    n = n / ln[:, None]
    arr = np.zeros(len(tris), dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    arr["n"] = n
    arr["v"] = tris
    with open(path, "wb") as f:
        f.write(b"listing-helper oriented model".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        f.write(arr.tobytes())
    return path


def capacity(footprint, bed, gap=6.0, margin=5.0):
    """一盘最多能放几个（按外框估算，留间距）。"""
    w, d = float(footprint[0]) + gap, float(footprint[1]) + gap
    bw, bd = float(bed[0]) - 2 * margin + gap, float(bed[1]) - 2 * margin + gap
    n1 = int(bw // w) * int(bd // d)
    n2 = int(bw // d) * int(bd // w)        # 转 90° 放
    return max(0, n1, n2)


# ---------------- v2.55 打印方案编辑器：任意面贴平台、镜像、推荐的面、按高度切开 ----------------
FACE_AXES = {"bottom": (0, 0, -1), "top": (0, 0, 1), "front": (0, -1, 0), "back": (0, 1, 0), "left": (-1, 0, 0), "right": (1, 0, 0)}


def _unit(n):
    n = np.asarray(n, dtype=np.float64).reshape(3)
    ln = float(np.linalg.norm(n))
    if ln < 1e-9:
        raise ValueError("面的方向不对")
    return n / ln


def face_matrix(n):
    """把（模型文件里的）朝外法线 n 转到朝下（-Z）的旋转矩阵（罗德里格斯公式）。"""
    a = _unit(n)
    b = np.array([0.0, 0.0, -1.0])
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])      # 已经朝下 / 正好朝上（绕 X 转 180°）
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1 / (1 + c))


def rotate_face(tris, n):
    """选定的面（法线 n）贴平台：转到朝下，再把最低点放到 0。"""
    t = np.asarray(tris, dtype=np.float64)
    out = (t.reshape(-1, 3) @ face_matrix(n).T).reshape(t.shape)
    return out - out.reshape(-1, 3).min(0)


def orient_tris(tris, orient="bottom", face=None):
    """摆放方向：六个主要方向之一，或者 face = 任意面的法线（v2.55「按面贴平台」）。"""
    if face is not None:
        return rotate_face(tris, face)
    return rotate(np.asarray(tris, dtype=np.float64), orient if orient in ORIENT_ZH else "bottom")


def mirror(tris, mx=False, my=False):
    """镜像（沿 X / Y），三角面的顶点顺序跟着反过来（法线还是朝外）。"""
    t = np.array(tris, dtype=np.float64)
    if not (mx or my):
        return t
    if mx:
        t[..., 0] = -t[..., 0]
    if my:
        t[..., 1] = -t[..., 1]
    if bool(mx) != bool(my):
        t = t[:, [0, 2, 1], :]
    return t


def face_candidates(tris, n=3, min_cm2=1.0):
    """推荐的「贴平台面」：模型外侧的大平面（不是六个主要方向的），按面积从大到小，最多 n 个。
    返回 [{"face": [nx, ny, nz], "area_cm2"}]。"""
    t = np.asarray(tris, dtype=np.float64)
    if len(t) > 400_000:
        t = t[:: max(1, len(t) // 400_000)]
    a, b, c = t[:, 0], t[:, 1], t[:, 2]
    nrm = np.cross(b - a, c - a)
    ln = np.linalg.norm(nrm, axis=1)
    ok = ln > 1e-9
    nrm, area, cen = nrm[ok] / ln[ok, None], ln[ok] / 2, t[ok].mean(1)
    if not len(area):
        return []
    q = np.round(nrm * 40).astype(np.int64)            # 约 1.5° 一格
    _keys, inv = np.unique(q, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    tot = np.bincount(inv, weights=area)
    verts = t.reshape(-1, 3)
    out = []
    for k in np.argsort(-tot)[:60]:
        if tot[k] / 100 < min_cm2 or len(out) >= n:
            break
        m = inv == k
        nn = (nrm[m] * area[m, None]).sum(0)
        nn = nn / (np.linalg.norm(nn) or 1)
        if any(abs(float(np.dot(nn, ax))) > 0.999 for ax in FACE_AXES.values()):
            continue                                   # 六个主要方向已经有了
        d = cen[m] @ nn
        ext = float((verts @ nn).max())
        on = area[m][np.abs(d - ext) < 0.3].sum()       # 只算贴在最外面的那一层（凹进去的平面放不平）
        if on / 100 < min_cm2:
            continue
        if any(float(np.dot(nn, np.array(o["face"]))) > 0.995 for o in out):
            continue
        out.append({"face": [round(float(x), 5) for x in nn], "area_cm2": round(float(on) / 100, 1)})
    return out


def best_face_analysis(tris):
    """六个主要方向 + 推荐的面，每个算贴平台面积 / 悬空 / 尺寸 / 分数（越小越好）。"""
    rows = analyze_all(tris)
    for c in face_candidates(tris):
        st = stats(rotate_face(tris, c["face"]))
        st.update(key="face", face=c["face"], label="按面贴平台")
        st["score"] = round(st["overhang_cm2"] * 3 + st["steep_cm2"]
                            + (8 if st["contact_cm2"] < 1 else 3 if st["contact_cm2"] < 3 else 0)
                            + st["height_mm"] / max(1.0, max(st["size_mm"])) * 2, 2)
        rows.append(st)
    return rows


def is_closed(tris):
    """每条边正好被两个方向相反的三角面共用（封闭、朝向一致）。"""
    t = np.asarray(tris, dtype=np.float64)
    if not len(t):
        return False
    _v, inv = np.unique(np.round(t.reshape(-1, 3), 4), axis=0, return_inverse=True)
    f = inv.reshape(-1, 3)
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    e = e[e[:, 0] != e[:, 1]]
    fw = {}
    for a_, b_ in map(tuple, e.tolist()):
        fw[(a_, b_)] = fw.get((a_, b_), 0) + 1
    return all(fw.get((b_, a_), 0) == c for (a_, b_), c in fw.items())


def _area2(poly):
    s = 0.0
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        s += x1 * y2 - x2 * y1
    return s / 2


def _in_poly(pt, poly):
    x, y = pt
    inside = False
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[i - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _seg_cross(p1, p2, p3, p4):
    """线段 p1p2 和 p3p4 是否真正相交（端点重合不算）。"""
    def o(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2, d3, d4 = o(p3, p4, p1), o(p3, p4, p2), o(p1, p2, p3), o(p1, p2, p4)
    return ((d1 > 1e-12 > d2) or (d1 < -1e-12 < d2)) and ((d3 > 1e-12 > d4) or (d3 < -1e-12 < d4))


def _bridge(outer, hole, others):
    """把一个洞（顺时针）用一条来回的「桥」接进外圈（逆时针），变成一个简单多边形。others：还没接进来的洞（桥不能穿过）。"""
    pts_o, pts_h = outer["pts"], hole["pts"]
    hi = max(range(len(pts_h)), key=lambda i: pts_h[i][0])
    m = pts_h[hi]
    edges = [(pts_o[i], pts_o[(i + 1) % len(pts_o)]) for i in range(len(pts_o))]
    for h in [hole] + others:
        edges += [(h["pts"][i], h["pts"][(i + 1) % len(h["pts"])]) for i in range(len(h["pts"]))]
    order = sorted(range(len(pts_o)), key=lambda i: (pts_o[i][0] - m[0]) ** 2 + (pts_o[i][1] - m[1]) ** 2)
    pick = order[0]
    for i in order[:400]:
        v = pts_o[i]
        if not any(_seg_cross(m, v, a, b) for a, b in edges):
            pick = i
            break
    n = len(pts_h)
    hp = [pts_h[(hi + k) % n] for k in range(n)] + [m]
    ids_h = [hole["ids"][(hi + k) % n] for k in range(n)] + [hole["ids"][hi]]
    return {"pts": pts_o[:pick + 1] + hp + pts_o[pick:], "ids": outer["ids"][:pick + 1] + ids_h + outer["ids"][pick:]}


def _earclip(pts, ids):
    """逆时针简单多边形（可以有桥接重复的点）→ 三角形（ids）。"""
    idx = list(range(len(pts)))
    out = []
    P = np.asarray(pts, dtype=np.float64)

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    start = 0
    while len(idx) > 3:
        n = len(idx)
        found = False
        rem = np.asarray(idx)
        for kk in range(n):
            k = (start + kk) % n
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % n]
            a, b, c = P[i0], P[i1], P[i2]
            if cross(a, b, c) <= 1e-12:
                continue
            Q = P[rem]
            same = (np.all(Q == a, 1) | np.all(Q == b, 1) | np.all(Q == c, 1))
            c1 = (b[0] - a[0]) * (Q[:, 1] - a[1]) - (b[1] - a[1]) * (Q[:, 0] - a[0])
            c2 = (c[0] - b[0]) * (Q[:, 1] - b[1]) - (c[1] - b[1]) * (Q[:, 0] - b[0])
            c3 = (a[0] - c[0]) * (Q[:, 1] - c[1]) - (a[1] - c[1]) * (Q[:, 0] - c[0])
            if np.any(~same & (c1 >= -1e-12) & (c2 >= -1e-12) & (c3 >= -1e-12)):
                continue
            out.append((ids[i0], ids[i1], ids[i2]))
            idx.pop(k)
            start = max(0, k - 1)
            found = True
            break
        if not found:                         # 退化（共线 / 自相交）：剩下的按扇形补上
            for k in range(1, len(idx) - 1):
                out.append((ids[idx[0]], ids[idx[k]], ids[idx[k + 1]]))
            return out
    if len(idx) == 3:
        out.append((ids[idx[0]], ids[idx[1]], ids[idx[2]]))
    return out


def cut_z(tris, z):
    """按水平面 Z = z 切成两半，切口补面（封闭）。tris 的 Z 朝上（已经按摆放方向转好）。
    返回 (下半, 上半)。原来的网格不封闭时切口可能补不全（用 is_closed 检查）。"""
    t = np.asarray(tris, dtype=np.float64)
    zs = t[..., 2]
    if z <= zs.min() + 0.05 or z >= zs.max() - 0.05:
        raise ValueError("切的高度要在零件的最低点和最高点之间")
    vv = t.reshape(-1, 3)
    if np.any(np.abs(vv[:, 2] - z) < 1e-5):           # 正好穿过顶点：稍微挪一点，避免退化
        z += 3e-4
    uv, inv = np.unique(np.round(vv, 6), axis=0, return_inverse=True)
    f = inv.reshape(-1, 3)
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    below = uv[:, 2] < z
    pts, key_of = [], {}

    def ip(i, j):
        k = (i, j) if i < j else (j, i)
        if k not in key_of:
            a, b = uv[i], uv[j]
            s = (z - a[2]) / (b[2] - a[2])
            key_of[k] = len(pts)
            pts.append((a + (b - a) * s).tolist())
        return ("p", key_of[k])
    fb = below[f]
    nb = fb.sum(1)
    lo = [[("v", int(x)) for x in tri] for tri in f[nb == 3].tolist()]
    hi = [[("v", int(x)) for x in tri] for tri in f[nb == 0].tolist()]
    seg = []                     # 下半部分切口上的边，方向 = 补面（朝上）绕的方向
    mixed = (nb == 1) | (nb == 2)
    for tri, bl in zip(f[mixed].tolist(), fb[mixed].tolist()):
        if sum(bl) == 1:                  # 一个点在下面
            k = bl.index(True)
            a, b, c = tri[k], tri[(k + 1) % 3], tri[(k + 2) % 3]
            pab, pac = ip(a, b), ip(a, c)
            lo.append([("v", a), pab, pac])
            hi.append([pab, ("v", b), ("v", c)])
            hi.append([pab, ("v", c), pac])
            seg.append((pac[1], pab[1]))
        else:                             # 两个点在下面
            k = bl.index(False)
            a, b, c = tri[k], tri[(k + 1) % 3], tri[(k + 2) % 3]
            pab, pac = ip(a, b), ip(a, c)
            hi.append([("v", a), pab, pac])
            lo.append([pab, ("v", b), ("v", c)])
            lo.append([pab, ("v", c), pac])
            seg.append((pab[1], pac[1]))
    nxt = {}
    for s0, s1 in seg:
        nxt.setdefault(s0, []).append(s1)
    loops, used = [], set()
    for start in list(nxt):
        for first in list(nxt[start]):
            if (start, first) in used:
                continue
            loop, cur = [start], first
            used.add((start, first))
            closed = False
            for _ in range(len(seg) + 2):
                if cur == start:
                    closed = True
                    break
                loop.append(cur)
                cands = [x for x in nxt.get(cur, []) if (cur, x) not in used]
                if not cands:
                    break
                used.add((cur, cands[0]))
                cur = cands[0]
            if closed and len(loop) >= 3:
                loops.append(loop)
    polys = [{"ids": lp, "pts": [tuple(pts[i][:2]) for i in lp]} for lp in loops]
    for pg in polys:
        pg["a"] = _area2(pg["pts"])
    outers = [pg for pg in polys if pg["a"] > 1e-9]
    holes = [pg for pg in polys if pg["a"] < -1e-9]
    for o in outers:
        o["holes"] = []
    for h in holes:
        box = [o for o in outers if _in_poly(h["pts"][0], o["pts"])]
        if box:
            min(box, key=lambda o: o["a"])["holes"].append(h)
    caps = []
    for o in outers:
        cur = {"pts": list(o["pts"]), "ids": list(o["ids"])}
        hs = sorted(o["holes"], key=lambda h: -max(p[0] for p in h["pts"]))
        for i, h in enumerate(hs):
            cur = _bridge(cur, h, hs[i + 1:])
        caps += _earclip(cur["pts"], cur["ids"])

    def build(fs, flip):
        out = [[uv[i] if kind == "v" else pts[i] for kind, i in tri] for tri in fs]
        for a, b, c in caps:
            out.append([pts[a], pts[c], pts[b]] if flip else [pts[a], pts[b], pts[c]])
        return np.asarray(out, dtype=np.float64) if out else None
    return build(lo, False), build(hi, True)
