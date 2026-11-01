"""T36（v2.56）：给切片软件（Bambu Studio / OrcaSlicer）编辑用的「项目 3MF」—— 生成 和 读回。

生成（build_project）：按盘、按软件各一份，格式照 OrcaSlicer 2.3.1 自己导出的项目文件（拓竹格式，两个软件都认）：
  3D/3dmodel.model           每个零件一个 <object>（components 指向 3D/Objects/object_N.model 里的网格），<build><item transform>
                             = 绕竖直轴转 rot + 放到 (x, y)；网格本身已经按网页的摆放方向 / 按面贴平台 / 镜像 / 缩放转好
  3D/Objects/object_N.model  网格；涂色 3MF 的三角面属性（paint_color 等）原样带过去
  Metadata/model_settings.config  每个零件：名字（可读，末尾「#编号」）、extruder（AMS 槽）、零件单独参数、
                             erp_uid（ERP 编号）；多零件的涂色文件每个 part 自己的 extruder；<plate> 第 1 盘
  Metadata/project_settings.config  打印机 / 工艺 / 耗材配置（OrcaSlicer 配置展开后合并；拓竹用同名系统预设），
                             耗材列表 = AMS 槽（材料、按款式的颜色、耗材配置名）
读回（read_project）：软件保存的 3MF → 每个零件（名字、erp 编号、extruder、在哪一盘、世界坐标网格、网格 → 世界的线性变换、
  零件参数）、耗材列表、有没有涂色、软件和版本、热床大小。同步规则在 editsession.py。
"""
import io
import json
import math
import re
import zipfile
from xml.sax.saxutils import quoteattr

import numpy as np

from core import mesh

APPS = {"bambu": "Bambu Studio", "orca": "OrcaSlicer"}
# 写进文件的 Application（两个软件都按「拓竹格式项目」读）。Orca 2.3.1 自己导出时就写 BambuStudio-2.3.1
APP_TAG = {"bambu": "BambuStudio-02.00.00.95", "orca": "BambuStudio-2.3.1"}
PAINT_KEYS = ("paint_color", "mmu_segmentation", "paint_supports", "paint_seam", "slic3rpe:mmu_segmentation")
OV_BACK = {"layer_height": ("layer_height", float), "sparse_infill_density": ("infill_pct", lambda v: int(float(str(v).rstrip("%")))),
           "wall_loops": ("walls", int)}
PLATE_GAP = 1.0 / 5.0          # 拓竹 / Orca 多盘时盘和盘之间的间隔（LOGICAL_PART_PLATE_GAP）


# ---------------- 变换 ----------------
def orient_matrix(it):
    """网页的摆放（方向 / 按面贴平台 / 镜像 / 缩放）→ 线性部分 M（行向量：p' = p @ M）。和 printplan._oriented 一致。"""
    from modules.model import printplan as pp
    probe = np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 0, 1], [0, 0, 0], [0, 0, 0]]], dtype=np.float64)
    r = mesh.orient_tris(probe, (it or {}).get("orient") or "bottom", pp._face(it)).reshape(-1, 3)
    o = r[0]
    m = np.array([r[1] - o, r[2] - o, r[3] - o])
    mx, my = pp._mir(it)
    m = m @ np.diag([-1.0 if mx else 1.0, -1.0 if my else 1.0, 1.0])
    return m * pp._sc((it or {}).get("scale"))


def rz(deg):
    a = math.radians(float(deg or 0))
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])


def tf_str(m, t):
    v = list(np.asarray(m, dtype=np.float64).reshape(9)) + list(np.asarray(t, dtype=np.float64).reshape(3))
    return " ".join(f"{x:.6f}".rstrip("0").rstrip(".") if abs(x) > 1e-12 else "0" for x in v)


def decompose(lin):
    """网格（模型文件坐标）→ 世界的线性变换 → {orient, face, mirror, rot, scale, nonuniform}。
    朝下（-Z）的那个方向是六个主方向之一 → orient；否则 face = 那个方向（按面贴平台）。剩下的是绕竖直轴的转角。"""
    lin = np.asarray(lin, dtype=np.float64)
    det = float(np.linalg.det(lin))
    s = abs(det) ** (1 / 3) if abs(det) > 1e-12 else 1.0
    u = lin / s
    sv = np.linalg.svd(lin, compute_uv=False)
    nonuni = bool(sv.max() - sv.min() > 0.01 * s)
    mirror = "x" if det < 0 else ""
    n = -u[:, 2]
    orient, face = "bottom", None
    for k, ax in mesh.FACE_AXES.items():
        if float(np.dot(n, ax)) > 0.9995:
            orient = k
            break
    else:
        face = [round(float(x), 5) for x in n]
    it = {"orient": orient, "face": face, "mirror": mirror}
    o = orient_matrix(it)                          # 含镜像，不含缩放
    rzm = np.linalg.inv(o) @ u
    rot = math.degrees(math.atan2(rzm[0, 1], rzm[0, 0])) % 360
    tilt = float(abs(rzm[2, 2] - 1) + abs(rzm[0, 2]) + abs(rzm[1, 2]))
    return {"orient": orient, "face": face, "mirror": mirror, "rot": round(rot, 1) % 360, "scale": round(s, 4),
            "nonuniform": nonuni or tilt > 0.02}


def place_xy(world_v, rot):
    """世界坐标的网格 + 绕竖直轴的转角 → 网页的 x / y（转之前外框的中心，转到世界坐标）。"""
    r = rz(rot)
    pre = np.asarray(world_v, dtype=np.float64).reshape(-1, 3) @ r.T
    c = (pre.min(0) + pre.max(0)) / 2
    w = np.array([c[0], c[1], 0.0]) @ r
    return float(w[0]), float(w[1])


# ---------------- 涂色 3MF 的原始网格（带三角面属性） ----------------
_TRI_RE = re.compile(rb"<(?:\w+:)?triangle\b([^>]*?)/?>")
_V_RE = re.compile(rb"<(?:\w+:)?vertex\b([^>]*?)/?>")


def _raw_mesh(buf, a, b):
    """一个 <mesh>：(顶点 N×3, 三角面 M×3, 每个三角面除 v1 v2 v3 以外的属性原文 或 None)"""
    vr = mesh._between(buf, rb"vertices", a, b)
    tr = mesh._between(buf, rb"triangles", a, b)
    if not vr or not tr:
        return None
    vs = []
    for m in _V_RE.finditer(buf, vr[0], vr[1]):
        d = dict(re.findall(rb'\b([xyz])="([^"]*)"', m.group(1)))
        vs.append([float(d.get(b"x", 0)), float(d.get(b"y", 0)), float(d.get(b"z", 0))])
    ts, attrs, any_attr = [], [], False
    for m in _TRI_RE.finditer(buf, tr[0], tr[1]):
        s = m.group(1)
        d = dict(re.findall(rb'\b(v[123])="(\d+)"', s))
        ts.append([int(d.get(b"v1", 0)), int(d.get(b"v2", 0)), int(d.get(b"v3", 0))])
        rest = re.sub(rb'\s*\bv[123]="\d+"', b"", s).strip().decode("utf-8", "ignore")
        attrs.append(rest)
        any_attr = any_attr or bool(rest)
    if not vs or not ts:
        return None
    return np.array(vs, dtype=np.float64), np.array(ts, dtype=np.int64), (attrs if any_attr else None)


def _settings_objects(z):
    """Metadata/model_settings.config → {objectid: {"meta": {k: v}, "parts": {partid: {k: v}}}}, [盘 {no, objects: [id]}]"""
    try:
        txt = z.read("Metadata/model_settings.config").decode("utf-8", "ignore")
    except KeyError:
        return {}, []
    objs = {}
    for m in re.finditer(r'<object id="(\d+)"[^>]*>(.*?)</object>', txt, re.S):
        body = m.group(2)
        parts = {}
        for pm in re.finditer(r'<part id="(\d+)"([^>]*)>(.*?)</part>', body, re.S):
            pd = dict(re.findall(r'<metadata key="([^"]+)" value="([^"]*)"', pm.group(3)))
            st = re.search(r'subtype="([^"]*)"', pm.group(2))
            pd["_subtype"] = st.group(1) if st else "normal_part"
            parts[pm.group(1)] = pd
        head = re.sub(r'<part id=.*?</part>', "", body, flags=re.S)
        meta = dict(re.findall(r'<metadata key="([^"]+)" value="([^"]*)"', head))
        objs[m.group(1)] = {"meta": {k: _unesc(v) for k, v in meta.items()}, "parts": parts}
    plates = []
    for m in re.finditer(r"<plate>(.*?)</plate>", txt, re.S):
        body = m.group(1)
        no = re.search(r'<metadata key="plater_id" value="(\d+)"', body)
        ids = re.findall(r'<metadata key="object_id" value="(\d+)"', body)
        plates.append({"no": int(no.group(1)) if no else len(plates) + 1, "objects": ids})
    return objs, plates


def _unesc(s):
    return s.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&apos;", "'").replace("&amp;", "&")


def raw_parts(data):
    """3MF 按 build 摆好的每个网格 [{name, v（文件世界坐标）, t, attrs, extruder（文件里的耗材序号）, subtype, ci, sj}]。
    ci = 组件序号（和 modellib.load_parts / 方案里 item 的 part 一样：每个 build item 一个）；sj = 这个组件里第几个网格
    （一个对象下多个 part：零件、修改器、负体积…）。"""
    z = zipfile.ZipFile(io.BytesIO(data))
    root = next((n for n in z.namelist() if n.lower() == "3d/3dmodel.model"), None)
    if not root:
        return []
    rbuf = z.read(root)
    b = mesh._between(rbuf, rb"build")
    if not b:
        return []
    objs = mesh._index_models(z)
    sobj, _pl = _settings_objects(z)
    rpath = "/" + root
    out = []

    def walk(key, m, obj_meta, acc, depth=0):
        ent = objs.get(key)
        if not ent or depth > 8:
            return
        if ent["mesh"]:
            buf, a, bb = ent["mesh"]
            r = mesh._between(buf, rb"mesh", a, bb)
            raw = _raw_mesh(buf, r[0], r[1]) if r else None
            if raw:
                v, t, at = raw
                if m is not None:
                    v = v @ m[0] + m[1]
                pm = (obj_meta.get("parts") or {}).get(key[1]) or {}
                ex = pm.get("extruder") or (obj_meta.get("meta") or {}).get("extruder") or "1"
                acc.append({"name": pm.get("name") or ent.get("name") or (obj_meta.get("meta") or {}).get("name") or f"part {len(acc) + 1}",
                            "v": v, "t": t, "attrs": at, "extruder": int(ex) if str(ex).isdigit() else 1,
                            "subtype": pm.get("_subtype") or "normal_part"})
        for path, oid, cm in ent["comps"]:
            walk((path, oid), mesh._compose(cm, m), obj_meta, acc, depth + 1)

    ci = 0
    for it in (mesh._attrs(x.group(1)) for x in mesh._ITEM_RE.finditer(rbuf, b[0], b[1])):
        if it.get("printable") == "0":
            continue
        oid = it.get("objectid", "")
        acc = []
        walk((it.get("path") or rpath, oid), mesh._mat(it.get("transform")), sobj.get(oid) or {}, acc)
        if not acc:
            continue
        for j, a in enumerate(acc):
            a.update(ci=ci, sj=j, nsub=len(acc))
            out.append(a)
        ci += 1
    return out


_RAW = {}


def _raw_cached(fp):
    import os
    key = (fp, os.path.getmtime(fp))
    if key not in _RAW:
        if len(_RAW) > 8:
            _RAW.clear()
        with open(fp, "rb") as f:
            _RAW[key] = raw_parts(f.read())
    return _RAW[key]


def item_cis(pid, p, it):
    """这个零件（方案的 item）写进项目时有哪些组件序号。"""
    from core import modellib
    if it.get("part") not in (None, ""):
        return [int(it["part"])]
    e = modellib._entry(p, it["id"])
    fp = modellib.path_of(pid, e)
    if fp and fp.lower().endswith(".3mf"):
        n = sorted({r["ci"] for r in _raw_cached(fp)})
        if n:
            return n
    try:
        return list(range(len(modellib.load_parts(fp)))) or [0]
    except Exception:  # noqa: BLE001
        return [0]


def part_name(label, uid, ci, sj=None):
    return f"{label} #{uid}.{ci}" + (f".{sj}" if sj is not None else "")


def item_parts(pid, p, it, slots):
    """盘上一个零件（方案的 item）→ 写进项目的网格（已经按网页的方向 / 镜像 / 缩放转好，外框中心在原点、最低点 z=0）。
    整个文件（part=None）按原文件结构：每个组件 / 每个网格一个 part（零件名、修改器 / 负体积、涂色原样）；
    单个组件（part=i）只要这个组件的网格。每个 part 的名字末尾是「#零件编号.组件序号[.网格序号]」（读回时靠它对应）。
    返回 (名字, [{name, v, t, attrs, extruder, subtype, ci, sj}], painted)"""
    from core import modellib
    from modules.model import printplan as pp
    e = modellib._entry(p, it["id"])
    fp = modellib.path_of(pid, e)
    slot = int(it.get("slot") or 1)
    ps = {str(k): int(v) for k, v in (it.get("part_slots") or {}).items()}
    ci_info = ((e.get("info") or {}).get("colors") or {})
    fs = {int(s.get("file_slot")): int(s["slot"]) for s in slots or [] if s.get("file_slot")}
    parts, painted = [], False
    want = None if it.get("part") in (None, "") else int(it["part"])
    if fp and fp.lower().endswith(".3mf"):
        for rp in _raw_cached(fp):
            if want is not None and rp["ci"] != want:
                continue
            if str(rp["ci"]) in ps:
                ex = ps[str(rp["ci"])]
            elif ci_info.get("multicolor") and want is None:
                ex = fs.get(rp["extruder"], rp["extruder"] if rp["extruder"] <= len(slots or [1]) else slot)
            else:
                ex = slot
            parts.append(dict(rp, v=rp["v"].copy(), t=rp["t"].copy(), extruder=ex))
            painted = painted or bool(rp["attrs"] and any(rp["attrs"]))
    label = e.get("orig_name") or "model"
    if not parts:
        _fp, tris, label = pp._tris_of(pid, p, it["id"], it.get("part"), 1)
        v = np.asarray(tris, dtype=np.float64).reshape(-1, 3)
        uniq, inv = np.unique(np.round(v, 5), axis=0, return_inverse=True)
        c0 = want if want is not None else 0
        parts = [{"name": label, "v": uniq, "t": inv.reshape(-1, 3), "attrs": None, "extruder": ps.get(str(c0), slot),
                  "subtype": "normal_part", "ci": c0, "sj": 0, "nsub": 1}]
    elif want is not None:
        label = f"{label} / {parts[0]['name']}"
    k = pp._sc(it.get("scale"))
    if k != 1.0:
        label += f" ({round(k * 100)}%)"
    m = orient_matrix(it)
    allv = np.concatenate([pt["v"] for pt in parts]) @ m
    mn, mx = allv.min(0), allv.max(0)
    c = np.array([(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]])
    flip = np.linalg.det(m) < 0
    for pt in parts:
        pt["v"] = pt["v"] @ m - c
        if flip:                                         # 镜像：三角面顶点顺序反过来（法线朝外）
            pt["t"] = pt["t"][:, [0, 2, 1]]
        base = re.sub(r"\s*#[\w.]+$", "", str(pt["name"]))
        pt["name"] = part_name(base, it["uid"], pt["ci"], pt["sj"] if pt.get("nsub", 1) > 1 else None)
    return label, parts, painted


def _mesh_xml(oid, pt):
    vs = "".join(f'<vertex x="{a:.5f}" y="{b:.5f}" z="{c:.5f}"/>' for a, b, c in pt["v"])
    at = pt.get("attrs")
    ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"{(" " + at[i]) if at and at[i] else ""}/>'
                 for i, (a, b, c) in enumerate(pt["t"]) if a != b and b != c and a != c)
    return f'  <object id="{oid}" type="model">\n   <mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh>\n  </object>\n'


NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
      'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"')


def _matrix4(m, t):
    """model_settings 里 part 的 matrix（行优先 4×4，列向量写法）。"""
    m = np.asarray(m, dtype=np.float64)
    rows = [[m[0, i], m[1, i], m[2, i], t[i]] for i in range(3)] + [[0, 0, 0, 1]]
    return " ".join(f"{x:.6f}".rstrip("0").rstrip(".") if abs(x) > 1e-12 else "0" for r in rows for x in r)


def write_project(path, objects, app="orca", settings=None, plate_name=""):
    """objects = [{name, x, y, rot, extruder, ov: [(键, 值)], parts: [{name, v, t, attrs, extruder, subtype,
    tf: (3×3, 平移) 零件在对象里的变换（可选）, ov}]}]。一个对象 = 软件里的一个对象（多个 part = 可拆开的组合）。"""
    res, build, ms, files, rels, inst = [], [], [], [], [], []
    submark = ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n' if settings else ""
    nid = 1
    for k, ob in enumerate(objects, start=1):
        sub = f"/3D/Objects/object_{k}.model"
        body, comps, pset = "", "", ""
        for pt in ob["parts"]:
            m, t = pt.get("tf") or (np.eye(3), np.zeros(3))
            body += _mesh_xml(nid, pt)
            comps += f'<component p:path="{sub}" objectid="{nid}" transform="{tf_str(m, t)}"/>'
            pextra = "".join(f'      <metadata key="{kk}" value={quoteattr(str(vv))}/>\n' for kk, vv in pt.get("ov") or [])
            pset += (f'    <part id="{nid}" subtype="{pt.get("subtype") or "normal_part"}">\n'
                     f'      <metadata key="name" value={quoteattr(str(pt["name"]))}/>\n'
                     f'      <metadata key="matrix" value="{_matrix4(m, t)}"/>\n'
                     f'      <metadata key="extruder" value="{int(pt["extruder"])}"/>\n'
                     + (f'      <metadata key="erp_src" value={quoteattr(str(pt["src"]))}/>\n' if pt.get("src") else "")
                     + f'{pextra}    </part>\n')
            nid += 1
        files.append((sub[1:], f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {NS}>\n'
                               f'{submark} <resources>\n{body} </resources>\n <build/>\n</model>\n'))
        rels.append(f' <Relationship Target="{sub}" Id="rel-{k}" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n')
        oid = nid
        nid += 1
        res.append(f'  <object id="{oid}" type="model">\n   <components>{comps}</components>\n  </object>\n')
        build.append(f'  <item objectid="{oid}" transform="{tf_str(rz(ob.get("rot")), [ob["x"], ob["y"], 0])}" printable="1"/>\n')
        extra = "".join(f'    <metadata key="{kk}" value={quoteattr(str(vv))}/>\n' for kk, vv in ob.get("ov") or [])
        ms.append(f'  <object id="{oid}">\n    <metadata key="name" value={quoteattr(ob["name"])}/>\n'
                  f'    <metadata key="extruder" value="{int(ob.get("extruder") or 1)}"/>\n{extra}{pset}  </object>\n')
        inst.append(f'    <model_instance>\n      <metadata key="object_id" value="{oid}"/>\n      <metadata key="instance_id" value="0"/>\n'
                    f'      <metadata key="identify_id" value="{100 + k}"/>\n    </model_instance>\n')
    # 没有完整配置时不写拓竹标记（拓竹格式 + 不完整的配置 OrcaSlicer 会崩溃），写成普通 3MF
    mark = (f' <metadata name="Application">{APP_TAG.get(app, APP_TAG["orca"])}</metadata>\n'
            f' <metadata name="BambuStudio:3mfVersion">1</metadata>\n') if settings else ""
    model = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {NS}>\n'
             f'{mark} <metadata name="Title">{_x(plate_name)}</metadata>\n'
             f' <resources>\n{"".join(res)} </resources>\n <build>\n{"".join(build)} </build>\n</model>\n')
    msc = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "".join(ms) +
           '  <plate>\n    <metadata key="plater_id" value="1"/>\n'
           # 盘名留空：实测 OrcaSlicer 2.3.1 命令行遇到中文盘名会崩溃（-11）
           '    <metadata key="plater_name" value=""/>\n    <metadata key="locked" value="false"/>\n'
           + "".join(inst) + "  </plate>\n</config>\n")
    ct = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
          ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
          ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
          ' <Default Extension="png" ContentType="image/png"/>\n <Default Extension="gcode" ContentType="text/x.gcode"/>\n</Types>\n')
    root_rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                 ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>\n')
    mrels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
             + "".join(rels) + "</Relationships>\n")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("3D/_rels/3dmodel.model.rels", mrels)
        for n, txt in files:
            z.writestr(n, txt)
        z.writestr("Metadata/model_settings.config", msc)
        if settings:
            z.writestr("Metadata/project_settings.config", json.dumps(settings, ensure_ascii=False, indent=4))
            z.writestr("Metadata/slice_info.config", '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <header>\n'
                       '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n    <header_item key="X-BBL-Client-Version" value=""/>\n'
                       "  </header>\n</config>\n")
    return path


def _x(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def obj_name(label, uid):
    return f"{label} #{uid}"


OBJ_UID_RE = re.compile(r"#([A-Za-z0-9]{3,12})(?![\w.])")
PART_RE = re.compile(r"#([A-Za-z0-9]{3,12})\.(\d+)(?:\.(\d+))?(?![\w.])")


def uid_of(name, meta=None):
    """对象名末尾「#编号」（软件里复制出来的名字一样）。"""
    u = (meta or {}).get("erp_uid")
    if u:
        return str(u)
    ms = OBJ_UID_RE.findall(str(name or ""))
    return ms[-1] if ms else ""


def src_of(name, meta=None):
    """part 名字「#零件编号.组件序号[.网格序号]」→ (零件编号, 组件序号, 网格序号或 None)；没有返回 None。"""
    s = (meta or {}).get("erp_src") or ""
    m = re.fullmatch(r"([A-Za-z0-9]{3,12})\.(\d+)(?:\.(\d+))?", str(s)) if s else None
    if not m:
        ms = list(PART_RE.finditer(str(name or "")))
        m = ms[-1] if ms else None
    if not m:
        return None
    return m.group(1), int(m.group(2)), (int(m.group(3)) if m.group(3) is not None else None)


_PS_CACHE = {}


def project_settings(cfg, p, plate, fils, app="orca", printer_idx=None):
    """Metadata/project_settings.config：打印机 + 工艺 + 每槽耗材配置（颜色按槽）。
    拓竹格式的项目文件必须带「完整」的配置（只写几个键 OrcaSlicer 会崩溃），所以让 OrcaSlicer 自己导出一次
    （配置展开 → orca-slicer --export-3mf 一个小方块，约 1 秒，同样的配置有缓存），取它写的 project_settings.config。
    fils = [{material, hex}]。返回 (dict 或 None, 说明 [{zh, th}])：None = 拿不到（没装 OrcaSlicer / 配置找不到），
    调用方改写普通 3MF（不带拓竹标记）。"""
    import hashlib
    import os
    import shutil
    import subprocess
    import tempfile
    from core import recipes, slicer
    from core import orca_profiles as op
    from modules.model import printplan as pp
    notes = []
    names = [x.get("name") for x in cfg.get("printers") or []]
    if printer_idx is None:
        printer_idx = names.index(plate["printer"]) if plate.get("printer") in names else 0
    rc = pp.recipe_of(p, plate)
    d = None
    try:
        exe, idx, machine, process, fil1 = slicer.resolve_profiles(cfg, printer_idx, fils[0]["material"],
                                                                   recipes.filament_for(rc, plate.get("printer")) or None, notes, strict=False)
        fnames = [fil1] + [slicer.resolve_profiles(cfg, printer_idx, f["material"], None, None, strict=False)[4] for f in fils[1:]]
        over = dict(recipes.overrides(rc) or {})
        if len(fils) > 1:
            over.update(slicer.MULTI_OVERRIDES)
        fo1 = recipes.filament_overrides(rc) or {}
        key = hashlib.md5(json.dumps([exe, machine, process, fnames, over, fo1, [f["material"] for f in fils]],
                                     sort_keys=True, default=str).encode()).hexdigest()
        if key in _PS_CACHE:
            out = json.loads(_PS_CACHE[key])
        else:
            d = tempfile.mkdtemp(prefix="proj_")
            # 单喷头、没有多色的机型（创想三维 K1 系列配置）带几个耗材时 Orca 要求「单喷头多材料」，否则配置报错（-5）
            m_path, mcfg = op.write_flat(idx, machine, "machine", d, None, {"single_extruder_multi_material": "1"} if len(fils) > 1 else None)
            mname = mcfg.get("name") or machine
            p_path, _ = op.write_flat(idx, process, "process", d, mname, over)
            fps = []
            for k, (f, fname) in enumerate(zip(fils, fnames)):
                fo = dict(fo1 if pp._same_mat(f["material"], fils[0]["material"]) else {})
                # 颜色不写进耗材配置（创想三维的配置写了会报「filament_is_support 个数不对」），导出后再填 filament_colour
                sub = os.path.join(d, f"f{k + 1}")
                os.makedirs(sub, exist_ok=True)
                fps.append(op.write_flat(idx, fname, "filament", sub, mname, fo)[0])
            cube = os.path.join(d, "cube.stl")
            slicer._cube_stl(cube, 10)
            r = subprocess.run([exe, "--load-settings", f"{m_path};{p_path}", "--load-filaments", ";".join(fps), "--arrange", "0",
                                "--orient", "0", "--outputdir", d, "--export-3mf", "ps.3mf", cube], cwd=d, capture_output=True,
                               timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            got = os.path.join(d, "ps.3mf")
            if not os.path.exists(got):
                why = [ln for ln in (r.stdout + r.stderr).decode("utf-8", "ignore").splitlines() if "error" in ln.lower() and "opengl" not in ln.lower()
                       and "glfw" not in ln.lower() and "glew" not in ln.lower() and "exclude triangles" not in ln.lower()]
                raise RuntimeError(f"OrcaSlicer 导出配置失败（返回码 {slicer.rc_signed(r.returncode)}）{(' ' + why[-1][-200:]) if why else ''}")
            with zipfile.ZipFile(got) as z:
                out = json.loads(z.read("Metadata/project_settings.config"))
            if len(_PS_CACHE) > 50:
                _PS_CACHE.clear()
            _PS_CACHE[key] = json.dumps(out)
    except Exception as e:  # noqa: BLE001  没装 OrcaSlicer / 配置找不到 → 普通 3MF
        notes.append({"zh": f"拿不到切片配置（{e}）：编辑文件里只有模型和每个零件的槽，打开后请在软件里选好打印机、工艺和耗材",
                      "th": "ไม่พบโปรไฟล์สไลซ์: ไฟล์แก้ไขมีแค่โมเดลและช่องของแต่ละชิ้น เปิดแล้วกรุณาเลือกเครื่องพิมพ์ กระบวนการ และฟิลาเมนต์ในโปรแกรม"})
        return None, notes
    finally:
        if d:
            shutil.rmtree(d, ignore_errors=True)
    out["filament_colour"] = [f.get("hex") or "#FFFFFF" for f in fils]
    if app == "bambu":
        out["version"] = "02.00.00.95"
    return out, notes


# ---------------- 读回 ----------------
def _ov_of(meta):
    ov = {}
    for k, (dst, fn) in OV_BACK.items():
        if meta.get(k) not in (None, ""):
            try:
                ov[dst] = fn(meta[k])
            except (TypeError, ValueError):
                pass
    return ov


_SKIP_META = {"name", "extruder", "erp_uid", "erp_src", "matrix", "source_file", "source_object_id", "source_volume_id",
              "source_offset_x", "source_offset_y", "source_offset_z", "_subtype", "mesh_stat"}


def read_project(data):
    """软件保存的 3MF → {application, app_ver, objects: [{name, uid, extruder, plate, world, lin, ov, settings,
    parts: [{name, src, extruder, subtype, world, lin, ov, settings}]}], filaments: [{slot, type, hex, profile}], painted, ...}"""
    z = zipfile.ZipFile(io.BytesIO(data))
    from .editsession import zip_guard
    zip_guard(z)                                     # 防 zip 炸弹：不无限解压
    root = next((n for n in z.namelist() if n.lower() == "3d/3dmodel.model"), None)
    if not root:
        raise ValueError("不是切片软件的项目文件（没有 3D/3dmodel.model）/ ไม่ใช่ไฟล์โปรเจกต์ของโปรแกรมสไลซ์")
    rbuf = z.read(root)
    app_m = re.search(rb'<metadata name="Application">([^<]*)</metadata>', rbuf)
    app_s = app_m.group(1).decode("utf-8", "ignore") if app_m else ""
    try:
        ps = json.loads(z.read("Metadata/project_settings.config"))
    except (KeyError, ValueError):
        ps = {}
    objs = mesh._index_models(z)
    sobj, plates = _settings_objects(z)
    b = mesh._between(rbuf, rb"build")
    items = [mesh._attrs(x.group(1)) for x in mesh._ITEM_RE.finditer(rbuf, b[0], b[1])] if b else []
    rpath = "/" + root
    plate_of = {}
    for pl in plates:
        for oid in pl["objects"]:
            plate_of.setdefault(oid, pl["no"])
    bed = _bed(ps)
    nplates = max([pl["no"] for pl in plates] + [1])
    out = []
    for it in items:
        oid = it.get("objectid", "")
        parts = []

        def walk(key, m, depth=0):
            ent = objs.get(key)
            if not ent or depth > 8:
                return
            if ent["mesh"]:
                buf, a, bb = ent["mesh"]
                ts = mesh._parse_3mf_model(buf[a:bb])
                if ts:
                    parts.append((key[1], np.concatenate(ts), m, ent.get("name") or ""))
            for path, cid, cm in ent["comps"]:
                walk((path, cid), mesh._compose(cm, m), depth + 1)
        walk((it.get("path") or rpath, oid), mesh._mat(it.get("transform")))
        if not parts:
            continue
        so = sobj.get(oid) or {}
        meta = so.get("meta") or {}
        pmeta = so.get("parts") or {}
        name = meta.get("name") or (objs.get((rpath, oid)) or {}).get("name") or ""
        ex = meta.get("extruder") or "1"
        oex = int(ex) if str(ex).isdigit() else 1
        pno = plate_of.get(oid)
        allw = np.concatenate([mesh._apply(t, m) for _i, t, m, _n in parts])
        if not pno:                                   # 文件里没写在哪一盘：按位置（拓竹 / Orca 多盘时盘按方阵排开）
            v = allw.reshape(-1, 3)
            pno = _plate_by_pos((v.min(0) + v.max(0)) / 2, bed)
        ox, oy = plate_origin(pno, max(nplates, pno), bed)
        shift = np.array([ox, oy, 0.0])
        plist = []
        for pid_, t, m, ename in parts:
            pm = pmeta.get(pid_) or {}
            pe = pm.get("extruder")
            pname = pm.get("name") or ename or name
            plist.append({"name": pname, "src": src_of(pname, pm), "extruder": int(pe) if pe and str(pe).isdigit() and int(pe) > 0 else oex,
                          "subtype": pm.get("_subtype") or "normal_part", "world": mesh._apply(t, m) - shift,
                          "lin": m[0] if m is not None else np.eye(3), "ov": _ov_of(pm),
                          "settings": {k: v for k, v in pm.items() if k not in _SKIP_META and k not in OV_BACK}})
        other = {k: v for k, v in meta.items() if k not in _SKIP_META and k not in OV_BACK}
        out.append({"oid": oid, "name": name, "uid": uid_of(name, meta), "extruder": oex, "plate": pno, "world": allw - shift,
                    "lin": plist[0]["lin"], "ov": _ov_of(meta), "settings": other, "parts": plist,
                    "part_extruders": sorted({p_["extruder"] for p_ in plist if p_["subtype"] == "normal_part"}),
                    "printable": it.get("printable") != "0"})
    painted = False
    for n in z.namelist():
        if n.lower().endswith(".model"):
            with z.open(n) as f:
                head = f.read(8_000_000)
            if any(k.encode() + b'="' in head for k in PAINT_KEYS):
                painted = True
                break
    fil = []
    cols = ps.get("filament_colour") or []
    types = ps.get("filament_type") or []
    profs = ps.get("filament_settings_id") or []
    for i in range(max(len(cols), len(types))):
        fil.append({"slot": i + 1, "type": str(types[i]) if i < len(types) else "", "hex": str(cols[i])[:7].upper() if i < len(cols) else "",
                    "profile": str(profs[i]) if i < len(profs) else ""})
    m = re.match(r"(BambuStudio|OrcaSlicer|Bambu Studio)[-_ ]?(.*)", app_s)
    return {"application": app_s, "app_ver": (m.group(2) if m else "") or str(ps.get("version") or ""), "objects": out,
            "filaments": fil, "painted": painted, "plates": max([o["plate"] for o in out] + [nplates]), "bed": bed,
            "printer_profile": ps.get("printer_settings_id") or "", "printer_model": ps.get("printer_model") or "",
            "nozzle": _first(ps.get("nozzle_diameter")), "bed_type": ps.get("curr_bed_type") or "",
            "process": ps.get("print_settings_id") or "", "exclude": ps.get("bed_exclude_area") or []}


def _first(v):
    if isinstance(v, list):
        v = v[0] if v else None
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _bed(ps):
    pa = ps.get("printable_area") or []
    try:
        pts = [[float(x) for x in str(s).split("x")] for s in pa]
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        return [max(xs) - min(xs), max(ys) - min(ys)] if pts else [256.0, 256.0]
    except (ValueError, IndexError):
        return [256.0, 256.0]


def _cols(n):
    v = math.sqrt(n)
    r = round(v)
    return int(r + 1 if v > r else r) or 1


def plate_origin(no, count, bed):
    """拓竹 / Orca 第 no 盘（从 1 开始）在场景里的原点（PartPlateList::compute_origin）。"""
    cols = _cols(max(1, count))
    i = max(0, int(no) - 1)
    return (i % cols) * bed[0] * (1 + PLATE_GAP), -(i // cols) * bed[1] * (1 + PLATE_GAP)


def _plate_by_pos(c, bed):
    sx, sy = bed[0] * (1 + PLATE_GAP), bed[1] * (1 + PLATE_GAP)
    col = max(0, int(math.floor(c[0] / sx)))
    row = max(0, int(math.floor(-c[1] / sy)) + 1) if c[1] < 0 else 0
    cols = max(col + 1, 1)
    return row * cols + col + 1


def plate_hexes(plan, plate, colour, cfg=None):
    """每个槽在这个款式下的颜色 #RRGGBB（和导出 / 切片一致）。"""
    from core import codes
    from core.config import load_config
    from modules.model import printplan as pp
    cmap = codes.color_hex(cfg or load_config())
    cols = pp.colours_for(plan, plate, colour)
    return {s["slot"]: ((cmap.get(cols.get(s["slot"]) or "") or {}).get("hex") or s.get("hex") or "#FFFFFF").upper()
            for s in plate.get("slots") or []}


def build_project(pid, spec, plate_id, colour="", app="orca", out_path=None, cfg=None, p=None):
    """生成这一盘给 app（bambu / orca）编辑的项目 3MF。返回 {path, plate（生成时的盘，读回时对照用）, notes, painted, hexes, settings}。"""
    import copy
    import tempfile
    from core import store
    from core.config import load_config
    from modules.model import printplan as pp
    cfg = cfg or load_config()
    p = p or store.load(pid)
    plan = pp.get_plan(p, spec)
    plate = next((x for x in plan["plates"] if x["id"] == plate_id), None)
    if not plate:
        raise ValueError("没有这一盘（刷新一下）")
    plate = copy.deepcopy(plate)
    if not plate.get("items"):
        raise ValueError("这一盘还没有零件")
    fps = pp.fps_for(pid, p, plate)
    if not plate.get("manual") or any(it.get("x") is None for it in plate["items"]):
        pp.auto_arrange(plate, pp.bed_of(plate["printer"]), fps)
    hexes = plate_hexes(plan, plate, colour, cfg)
    fils = [{"material": s.get("material") or "PLA", "hex": hexes.get(s["slot"]) or "#FFFFFF"} for s in plate["slots"]]
    objects, painted, written, groups = [], False, {}, {}
    for it in plate["items"]:
        label, parts, pt = item_parts(pid, p, it, plate["slots"])
        painted = painted or pt
        written[it["uid"]] = sorted({x["ci"] for x in parts})
        ov = pp.ov_metadata(it.get("ov"))
        if it.get("part") not in (None, "") or len(parts) == 1:
            for x in parts:
                x["ov"] = ov
        ent = {"uid": it["uid"], "label": label, "parts": parts, "x": float(it.get("x") or 0), "y": float(it.get("y") or 0),
               "rot": float(it.get("rot") or 0), "slot": int(it.get("slot") or 1), "ov": ov}
        if it.get("group"):                        # 网页里成组的零件 = 软件里一个对象（组合，可以拆开）
            groups.setdefault(it["group"], []).append(ent)
        else:
            objects.append({"name": obj_name(label, it["uid"]), "parts": parts, "x": ent["x"], "y": ent["y"], "rot": ent["rot"],
                            "extruder": ent["slot"], "ov": [("erp_uid", it["uid"])] + ov})
    for g, ents in groups.items():
        x0 = sum(e["x"] for e in ents) / len(ents)
        y0 = sum(e["y"] for e in ents) / len(ents)
        parts = []
        for e in ents:
            r = rz(e["rot"])
            for x in e["parts"]:
                x["tf"] = (r, np.array([e["x"] - x0, e["y"] - y0, 0.0]))
                parts.append(x)
        objects.append({"name": obj_name(" + ".join(e["label"] for e in ents)[:60], ents[0]["uid"]), "parts": parts, "x": x0, "y": y0,
                        "rot": 0, "extruder": ents[0]["slot"], "ov": [("erp_uid", ents[0]["uid"])]})
    settings, notes = project_settings(cfg, p, plate, fils, app)
    out_path = out_path or tempfile.NamedTemporaryFile(suffix=".3mf", delete=False).name
    pname = f"{p.get('name_zh') or pid}{' ' + spec if spec else ''} #{plate_id}"
    write_project(out_path, objects, app, settings, pname[:60])
    return {"path": out_path, "plate": plate, "notes": notes, "painted": painted, "hexes": {str(k): v for k, v in hexes.items()},
            "settings": bool(settings), "written": written}
