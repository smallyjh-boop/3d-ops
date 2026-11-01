"""打印方案（v2.52，给生产用）：每个规格一份，一份方案 = 一盘或几盘。

和「展示模型」（assembly.py，给商品图用的组装姿势）分开：展示管好看，打印方案管怎么打。

数据（产品资料 product["print_plans"][规格]，规格 "" = 主模型 / 没有自己模型的规格）：
  {"plates": [盘], "schemes": {款式颜色: {"槽号": 颜色}}, "updated_at", "updated_by"}
  盘 = {"id", "name", "printer": 机型名, "layer_height", "sets": 这一盘出几套成品,
        "slots": [{"slot": 1..4, "material", "colour": 固定颜色（空 = 跟着款式颜色）}],
        "items": [{"uid", "id": 模型库文件, "part": 组件序号或 None, "orient", "slot", "x", "y", "rot"}],
        "manual": 是否手动摆过（False = 按自动排列），"sliced": 切片结果（每槽克数、冲刷废料、时长）}
  每个 item 是盘上的「一个」零件（复制 N 个 = N 个 item），x / y = 零件外框中心在热床上的位置（毫米，左下角是原点），
  rot = 绕竖直轴转的角度。

多色：每盘最多 4 个 AMS 槽；按零件分色 = 每个零件选一个槽；款式（例如 白款 / 黑款）= 配色方案（槽 → 颜色）。
拓竹 / MakerWorld 涂色的 3MF 原样保留，只读它用几种颜色、每种用多少（文件里有 slice_info 时）；改涂色请在 Bambu Studio 里改好再上传。

v2.53：「按主模型缩放 N%」的规格 = {"follow": True, "scale": N}（主模型方案里每个零件带 scale，不要另外的文件；主模型改了跟着改）；
「从某个规格复制」「从组装生成打印方案」「一键全部切片」；零件可以带 "scale"（克数按 k³、时长按 k^2.5 估）。

★ 对外（modules.public("model")）：get_plan / colours_for / usage / job_colours / run_colours / job_plates / plate_info
"""
import math
import os
import time
import uuid

import numpy as np

from core import fleet, mesh, modellib, store
from core.config import load_config

SLOT_MAX = 4
MARGIN = 5.0          # 自动排列时离热床边缘
GAP = 6.0             # 自动排列时零件间距
OVERLAP_TOL = 0.3     # 重叠超过这么多毫米才算重叠（贴着放可以）
OUT_TOL = 0.5
DEFAULT_BED = [256, 256, 256]


def _uid(prefix="i"):
    return prefix + uuid.uuid4().hex[:6]


# ---------------- 打印机 ----------------
def printer_models(cfg=None):
    """设置里启用的 FDM 打印机机型（去重）：[{name, bed, multicolor}]"""
    cfg = cfg or load_config()
    out, seen = [], set()
    for p in cfg.get("printers") or []:
        if p.get("enabled", True) is False or fleet.tech_of(p) == "resin":
            continue
        n = p.get("name") or ""
        if n in seen:
            continue
        seen.add(n)
        m = fleet.model_info(n) or {}
        out.append({"name": n, "bed": m.get("bed") or DEFAULT_BED, "multicolor": fleet.is_multicolor(p), "exclude": exclude_of(n)})
    if not out:
        out.append({"name": "Bambu Lab P1S", "bed": [256, 256, 256], "multicolor": True, "exclude": exclude_of("Bambu Lab P1S")})
    return out


def exclude_of(name):
    """热床上不能放零件的地方（v2.53）：拓竹 X1 / P1 系列左前角 18×28 mm 是废料口（切片软件的 bed_exclude_area），
    零件压到这里 OrcaSlicer 会说「盘上没有能切的零件」。返回 [x0, y0, x1, y1] 或 None。"""
    import re
    if re.search(r"bambu.*\b(x1|p1)", str(name or ""), re.I):
        return [0.0, 0.0, 18.0, 28.0]
    return None


def _x0(excl, y, d=0.0):
    """这一排从哪里开始：排的范围碰到废料口就从废料口右边开始。"""
    if excl and y < excl[3] + 1 and y + d > excl[1] - 1:
        return max(MARGIN, excl[2] + 3)
    return MARGIN


def bed_of(name, cfg=None):
    for m in printer_models(cfg):
        if m["name"] == name:
            return m["bed"]
    return (fleet.model_info(name) or {}).get("bed") or DEFAULT_BED


# ---------------- 零件外形（俯视轮廓） ----------------
_FP = {}


def _hull(pts):
    """二维凸包（单调链），逆时针。"""
    pts = np.unique(np.round(pts, 1), axis=0)
    if len(pts) < 3:
        return pts.tolist()
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(tuple(p))
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(tuple(p))
    return [list(map(float, x)) for x in lower[:-1] + upper[:-1]]


def _simplify(h, n=40):
    if len(h) <= n:
        return h
    step = len(h) / n
    return [h[int(i * step)] for i in range(n)]


def _sc(v):
    try:
        k = float(v or 1)
    except (TypeError, ValueError):
        return 1.0
    return k if 0.01 <= k <= 20 else 1.0


def _tris_of(pid, p, eid, part, scale=1.0):
    k = _sc(scale)
    if k != 1.0:
        fp, t, label = _tris_of(pid, p, eid, part)
        return fp, np.asarray(t, dtype=np.float64) * k, f"{label} ({round(k * 100)}%)"
    e = modellib._entry(p, eid)
    fp = modellib.path_of(pid, e)
    if not fp or os.path.splitext(fp)[1].lower() not in modellib.MODEL_EXT:
        raise ValueError(f"「{e.get('orig_name')}」不是能摆盘的模型文件（要 STL、3MF 或 OBJ）")
    parts = modellib.load_parts(fp)
    if part not in (None, ""):
        i = int(part)
        if not 0 <= i < len(parts):
            raise ValueError(f"「{e['orig_name']}」没有第 {i + 1} 个组件")
        return fp, parts[i][1], f"{e['orig_name']} / {parts[i][0]}"
    return fp, np.concatenate([t for _n, t in parts]), e["orig_name"]


def _face(it):
    """v2.55：按任意面贴平台（面的法线，模型文件坐标）；没有 = 用 orient 的六个方向之一。"""
    f = (it or {}).get("face")
    if isinstance(f, (list, tuple)) and len(f) == 3:
        try:
            v = [float(x) for x in f]
            if sum(x * x for x in v) > 1e-9:
                return v
        except (TypeError, ValueError):
            pass
    return None


def _mir(it):
    m = str((it or {}).get("mirror") or "")
    return "x" in m, "y" in m


def _oriented(tris, it):
    """零件按摆放方向（六个方向 / 任意面）放平，再镜像（v2.55）。Z 朝上、最低点 0。"""
    t = mesh.orient_tris(np.asarray(tris, dtype=np.float64), (it or {}).get("orient") or "bottom", _face(it))
    mx, my = _mir(it)
    if mx or my:
        t = mesh.mirror(t, mx, my)
    return t


def footprint(pid, eid, part=None, orient="bottom", p=None, scale=1.0, face=None, mirror=""):
    """零件按摆放方向放平后的俯视轮廓（凸包，中心在外框中心）。返回 {hull, w, d, h, label, contact, overhang, tall}。
    scale：按主模型缩放的规格（v2.53）；face / mirror：按面贴平台、镜像（v2.55）。"""
    p = p or store.load(pid)
    orient = orient if orient in mesh.ORIENT_ZH else "bottom"
    it = {"orient": orient, "face": face, "mirror": mirror}
    fc = _face(it)
    e = modellib._entry(p, eid)
    fp = modellib.path_of(pid, e)
    key = (fp, os.path.getmtime(fp) if fp else 0, part, orient, _sc(scale), tuple(round(x, 4) for x in fc) if fc else None, "".join(k for k, v in zip("xy", _mir(it)) if v))
    if key in _FP:
        return _FP[key]
    fp, tris, label = _tris_of(pid, p, eid, part, scale)
    t = _oriented(tris, it)
    v = t.reshape(-1, 3)
    if len(v) > 300_000:
        v = v[:: max(1, len(v) // 300_000)]
    mn, mx = v.min(0), v.max(0)
    c = (mn[:2] + mx[:2]) / 2
    hull = _simplify(_hull(v[:, :2] - c))
    try:
        st = mesh.stats(t if len(t) <= 400_000 else t[:: max(1, len(t) // 400_000)])
    except (ValueError, IndexError):
        st = {}
    out = {"hull": [[round(a, 1), round(b, 1)] for a, b in hull], "w": round(float(mx[0] - mn[0]), 1),
           "d": round(float(mx[1] - mn[1]), 1), "h": round(float(mx[2] - mn[2]), 1), "label": label,
           "contact": st.get("contact_cm2"), "overhang": st.get("overhang_cm2"), "tall": st.get("tall_ratio")}
    if len(_FP) > 200:
        _FP.clear()
    _FP[key] = out
    return out


def _poly(fp, x, y, rot):
    a = math.radians(float(rot or 0))
    ca, sa = math.cos(a), math.sin(a)
    return [(x + px * ca - py * sa, y + px * sa + py * ca) for px, py in fp["hull"]] or \
        [(x - fp["w"] / 2, y - fp["d"] / 2), (x + fp["w"] / 2, y - fp["d"] / 2), (x + fp["w"] / 2, y + fp["d"] / 2), (x - fp["w"] / 2, y + fp["d"] / 2)]


def _overlap(a, b):
    """两个凸多边形的重叠深度（分离轴），不重叠返回 0。"""
    depth = float("inf")
    for poly in (a, b):
        n = len(poly)
        for i in range(n):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % n]
            ax, ay = y1 - y2, x2 - x1
            ln = math.hypot(ax, ay)
            if ln < 1e-9:
                continue
            ax, ay = ax / ln, ay / ln
            pa = [px * ax + py * ay for px, py in a]
            pb = [px * ax + py * ay for px, py in b]
            d = min(max(pa), max(pb)) - max(min(pa), min(pb))
            if d <= 0:
                return 0.0
            depth = min(depth, d)
    return 0.0 if depth == float("inf") else depth


def check_plate(plate, bed, fps):
    """检查一盘：每个零件有没有超出热床、和谁重叠。fps: {uid: footprint}。
    返回 {"ok": bool, "items": {uid: {"out": bool, "overlap": [uid]}}, "problems": [中文说明]}"""
    W, D = float(bed[0]), float(bed[1])
    res, polys = {}, {}
    for it in plate.get("items") or []:
        f = fps.get(it["uid"])
        if not f or it.get("x") is None or it.get("y") is None:
            continue
        pg = _poly(f, float(it["x"]), float(it["y"]), it.get("rot") or 0)
        polys[it["uid"]] = pg
        out = any(px < -OUT_TOL or py < -OUT_TOL or px > W + OUT_TOL or py > D + OUT_TOL for px, py in pg)
        if len(bed) > 2 and f["h"] > float(bed[2]) + OUT_TOL:
            out = True
        ex = exclude_of(plate.get("printer"))
        if ex and not out and _overlap(pg, [(ex[0], ex[1]), (ex[2], ex[1]), (ex[2], ex[3]), (ex[0], ex[3])]) > OVERLAP_TOL:
            out = True                                          # 压到拓竹的废料口

        res[it["uid"]] = {"out": out, "overlap": []}
    ids = list(polys)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if _overlap(polys[a], polys[b]) > OVERLAP_TOL:
                res[a]["overlap"].append(b)
                res[b]["overlap"].append(a)
    probs = []
    n_out = sum(1 for r in res.values() if r["out"])
    n_ov = sum(1 for r in res.values() if r["overlap"])
    if n_out:
        probs.append(f"{n_out} 个零件超出热床")
    if n_ov:
        probs.append(f"{n_ov} 个零件互相重叠")
    return {"ok": not probs, "items": res, "problems": probs}


def auto_arrange(plate, bed, fps, gap=GAP):
    """自动排列（按外框一排排放，放不下转 90° 再试），改 plate 里每个零件的 x / y / rot。返回放不下的个数。"""
    W, D = float(bed[0]), float(bed[1])
    items = [it for it in plate.get("items") or [] if it["uid"] in fps]
    items.sort(key=lambda it: -max(fps[it["uid"]]["w"], fps[it["uid"]]["d"]))
    excl = exclude_of(plate.get("printer"))
    x, y, row_h, miss = _x0(excl, MARGIN, 1e9), MARGIN, 0.0, 0
    for it in items:
        f = fps[it["uid"]]
        w, d, rot = f["w"], f["d"], 0
        if w > W - 2 * MARGIN and d <= W - 2 * MARGIN and w <= D - 2 * MARGIN:
            w, d, rot = d, w, 90
        if x > _x0(excl, y, 1e9) and x + w > W - MARGIN:
            y, row_h = y + row_h + gap, 0.0
            x = _x0(excl, y, 1e9)
        if x + w > W - MARGIN + 0.01 and w < d and d <= W - 2 * MARGIN:   # 这一排剩下的地方转 90° 放得下
            w, d, rot = d, w, 90
        it["x"], it["y"], it["rot"] = round(x + w / 2, 1), round(y + d / 2, 1), rot
        if y + d > D - MARGIN + 0.01 or x + w > W - MARGIN + 0.01:
            miss += 1
        x += w + gap
        row_h = max(row_h, d)
    return miss


# ---------------- 组合摆盘（按说明 / AI）：一套零件按组装关系摆在一起，给员工 / 买家看得懂 ----------------
import re as _re

# 零件名里的角色词 → 排序（底座在前，主体，侧面 / 手脚，上面的，小配件最后）
ROLE_WORDS = [
    (0, r"base|bottom|stand|foot|feet|plate|底座|底|座|ฐาน"),
    (1, r"body|main|torso|frame|shell|box|case|主体|身体|身|外壳|盒|ตัว"),
    (3, r"top|lid|cap|head|cover|roof|顶|盖|头|帽|ฝา|หัว"),
    (4, r"clip|pin|peg|screw|bolt|nut|hinge|key|spacer|ring|tab|connector|卡扣|销|螺丝|螺母|铰链|垫|扣|环|คลิป|น็อต"),
    (2, r"arm|leg|wing|side|left|right|handle|手|脚|腿|翅|侧|左|右|把手|แขน|ขา"),
]
_SIDE = _re.compile(r"(?:^|(?<=[\s_\-.]))(l|r|left|right|左|右)(?=$|[\s_\-.\d])", _re.I)


def _base_name(label):
    """零件名去掉文件名、序号、左右 → 用来把同一种零件 / 左右一对放一组。"""
    n = str(label or "").split(" / ")[-1].lower()
    n = _re.sub(r"\.(stl|3mf|obj)$", "", n)
    n = _SIDE.sub(" ", n)
    n = _re.sub(r"[\d_\-.()\[\]x×#]+", " ", n)
    return _re.sub(r"\s+", " ", n).strip() or "part"


def _role(label):
    n = str(label or "").split(" / ")[-1].lower()
    for rank, pat in ROLE_WORDS:
        if _re.search(pat, n, _re.I):
            return rank
    return 2


def kit_rules(plate, fps):
    """不用 AI：按零件名分组（同一种零件、左右一对放一起），组按角色排（底座 → 主体 → 侧面 → 顶 → 小配件），
    同一组的零件朝向一致（不转）。返回 (rows=[[uid…]], rots={uid: 角度}, groups=[{name, uids}])。"""
    groups, order = {}, []
    for it in plate.get("items") or []:
        lab = (fps.get(it["uid"]) or {}).get("label") or it.get("label") or ""
        k = _base_name(lab)
        if k not in groups:
            groups[k] = {"name": k, "uids": [], "role": _role(lab), "first": len(order)}
            order.append(k)
        groups[k]["uids"].append(it["uid"])
    gl = sorted(groups.values(), key=lambda g: (g["role"], g["first"]))
    return [g["uids"] for g in gl], {}, [{"name": g["name"], "uids": g["uids"]} for g in gl]


def rows_layout(plate, fps, rows, rots, bed, gap=GAP):
    """按给定的行（每行一组零件，按顺序从左到右）摆：组和组之间换行，一行太长自动折行。不改顺序。返回放不下的个数。"""
    W, D = float(bed[0]), float(bed[1])
    by = {it["uid"]: it for it in plate.get("items") or []}
    listed = {x for r in rows for x in r}
    rows = [list(r) for r in rows] + [[u for u in by if u not in listed]]
    y, miss, placed = MARGIN, 0, set()
    for row in rows:
        row = [u for u in row if u in by and u in fps and u not in placed]
        if not row:
            continue
        excl = exclude_of(plate.get("printer"))
        x, row_h = _x0(excl, y, 1e9), 0.0
        for u in row:
            it, f = by[u], fps[u]
            rot = float(rots.get(u, 0) or 0) % 360
            pg = _poly(f, 0, 0, rot)
            w = max(px for px, _ in pg) - min(px for px, _ in pg)
            d = max(py for _, py in pg) - min(py for _, py in pg)
            if x > _x0(excl, y, 1e9) and x + w > W - MARGIN:
                y, row_h = y + row_h + gap, 0.0
                x = _x0(excl, y, 1e9)
            it["x"], it["y"], it["rot"] = round(x + w / 2, 1), round(y + d / 2, 1), round(rot, 1)
            if y + d > D - MARGIN + 0.01 or x + w > W - MARGIN + 0.01:
                miss += 1
            x += w + gap
            row_h = max(row_h, d)
            placed.add(u)
        y += row_h + gap * 1.5            # 组和组之间多空一点，看得出哪几件是一组
    return miss


KIT_SYSTEM = """你是 3D 打印工厂的摆盘师傅。一个产品由几个零件组成（同一种零件可能有好几个）。
请把这一盘的零件按「组装关系」分成几组、排成几行：同一套里互相拼在一起的零件放在相邻位置，按组装顺序（例如 底座 → 主体 → 顶盖 → 小配件），
左右对称的一对放在一起、朝向一致，让员工和买家一看就知道怎么拼。每个零件只能出现一次。只输出 JSON。"""


def kit_ai(cfg, p, plate, fps):
    """让 ERP 的 AI 按零件名、尺寸、数量、产品说明（原站描述 / 标签）给出分组和顺序；能看图的 AI 附上商品主图。
    返回 (rows, rots, groups, note_zh, note_th)。"""
    import json
    from core import ai_copy
    src = p.get("source") or {}
    desc = " ".join(str(x or "") for x in (p.get("name_zh"), p.get("features_zh"), src.get("title_original"),
                                            str(src.get("description_original") or "")[:2500], src.get("tags")))
    items = [{"uid": it["uid"], "name": (fps.get(it["uid"]) or {}).get("label", ""),
              "size_mm": [round(float((fps.get(it["uid"]) or {}).get(k) or 0), 1) for k in ("w", "d", "h")]} for it in plate.get("items") or []]
    user = ("产品说明（原站描述 / 标签 / 卖点）：\n" + desc.strip()[:3000] + "\n\n这一盘的零件（uid、名字、平放后的外框 宽×深×高 毫米）：\n" +
            json.dumps(items, ensure_ascii=False) +
            '\n\n输出 JSON：{"groups": [{"name_zh": "组名（例如 底座组件）", "uids": ["按摆放顺序的 uid"], "rot": {"uid": 绕竖直轴角度 0/90/180/270}}], '
            '"note_zh": "一句话说明怎么分组", "note_th": "..."}')
    img = None
    from core import ai
    if ai.can(cfg, "kit", "vision")[0]:                    # 能看图的 AI 才附上主图（DeepSeek 不能看图）
        try:
            import base64
            import io
            from . import assembly
            im = assembly._main_image(p)
            if im is not None:
                im = im.convert("RGB")
                im.thumbnail((768, 768))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=85)
                img = base64.b64encode(buf.getvalue()).decode()
        except Exception:  # noqa: BLE001
            img = None
    data = ai_copy.extract_json(ai_copy.call(ai_copy.tcfg(cfg, "kit"), KIT_SYSTEM, user, image_b64=img))
    valid = {it["uid"] for it in plate.get("items") or []}
    rows, rots, groups, seen = [], {}, [], set()
    for g in data.get("groups") or []:
        uids = [u for u in g.get("uids") or [] if u in valid and u not in seen]
        if not uids:
            continue
        seen.update(uids)
        rows.append(uids)
        for u, r in (g.get("rot") or {}).items():
            if u in valid:
                try:
                    rots[u] = float(r) % 360
                except (TypeError, ValueError):
                    pass
        groups.append({"name": str(g.get("name_zh") or g.get("name") or "")[:40], "uids": uids})
    if not rows:
        raise ValueError("AI 没有给出分组")
    return rows, rots, groups, str(data.get("note_zh") or "")[:300], str(data.get("note_th") or "")[:300]


def kit_layout(pid, plate, use_ai=True, cfg=None):
    """组合摆盘：AI 开着时按 AI 的分组（失败自动退回规则），没有 AI 按零件名规则。改 plate 里的位置（不保存），
    返回 {"source": "ai"|"rules", "groups", "note_zh", "note_th", "missed", "footprints"}。按组摆不下时退回省空间的自动排列。"""
    cfg = cfg or load_config()
    p = store.load(pid)
    fps = fps_for(pid, p, plate)
    bed = bed_of(plate.get("printer"))
    source, note_zh, note_th, rows = "rules", "", "", None
    from core import ai
    if use_ai and ai.ready(cfg, "kit"):
        try:
            rows, rots, groups, note_zh, note_th = kit_ai(cfg, p, plate, fps)
            source = "ai"
        except Exception as e:  # noqa: BLE001  AI 没设置好 / 回答不对：用规则
            rows = None
            note_zh, note_th = f"AI 没成功（{str(e)[:80]}），按零件名分组", "AI ไม่สำเร็จ จัดกลุ่มตามชื่อชิ้นงาน"
    if rows is None:
        rows, rots, groups = kit_rules(plate, fps)
        if not note_zh:
            note_zh = "按零件名分组：同一种零件、左右一对放在一起，底座 → 主体 → 侧面 → 顶 → 小配件"
            note_th = "จัดกลุ่มตามชื่อชิ้นงาน: ชิ้นเดียวกัน ซ้าย-ขวา วางคู่กัน ฐาน → ตัว → ด้านข้าง → ด้านบน → อุปกรณ์เล็ก"
    miss = rows_layout(plate, fps, rows, rots, bed)
    if miss:                                    # 按组摆放不下：退回省空间的排法
        miss = auto_arrange(plate, bed, fps)
        note_zh += "；按组合摆放不下，已改成省空间排列"
        note_th += " วางตามกลุ่มไม่พอ เปลี่ยนเป็นจัดเรียงแบบประหยัดพื้นที่"
    plate["manual"] = True
    return {"source": source, "groups": groups, "note_zh": note_zh, "note_th": note_th, "missed": miss, "footprints": fps}


# ---------------- 方案的读取 / 默认 / 清理 ----------------
def _spec_entry(p, spec):
    from core import specmodel
    e = specmodel.entry_for(p, spec) if spec else None
    if e:
        return e
    lid = (p.get("model") or {}).get("lib_id")
    return next((x for x in p.get("model_lib") or [] if x.get("id") == lid), None)


def _file_colours(e):
    ci = ((e or {}).get("info") or {}).get("colors") or {}
    return ci if ci.get("multicolor") else None


def default_plan(p, spec="", cfg=None):
    """还没有方案时：这个规格用的模型（组件分开时每个组件一件）放在一盘上，单色（槽 1 跟着款式颜色）。"""
    cfg = cfg or load_config()
    pm = printer_models(cfg)
    first = pm[0]["name"]
    e = _spec_entry(p, spec)
    recipe = p.get("recipe") or {}
    plate = {"id": "p1", "name": "", "printer": first, "layer_height": float(recipe.get("layer_height") or 0.2), "sets": 1,
             "slots": [{"slot": 1, "material": p.get("material") or "PLA", "colour": ""}], "items": [], "manual": False}
    if e:
        info = e.get("info") or {}
        ci = _file_colours(e)
        if ci:                                      # 涂色 / 多色 3MF：原样一件，槽按文件里的耗材
            plate["items"].append({"uid": _uid(), "id": e["id"], "part": None, "orient": "bottom", "slot": 1, "x": None, "y": None, "rot": 0})
            plate["slots"] = _slots_from_file(ci, p.get("material") or "PLA")
        else:
            plate["items"].append({"uid": _uid(), "id": e["id"], "part": None,
                                   "orient": recipe.get("orientation") or info.get("best") or "bottom", "slot": 1, "x": None, "y": None, "rot": 0})
    return {"plates": [plate], "schemes": {}, "default": True}


def _slots_from_file(ci, material):
    used = ci.get("used") or [f["slot"] for f in ci.get("filaments") or []]
    out = []
    for f in ci.get("filaments") or []:
        if used and f["slot"] not in used:
            continue
        if len(out) >= SLOT_MAX:
            break
        out.append({"slot": len(out) + 1, "file_slot": f["slot"], "material": (f.get("type") or material or "PLA").upper(),
                    "colour": f.get("name") or "", "hex": f.get("hex") or ""})
    return out or [{"slot": 1, "material": material, "colour": ""}]


def get_plan(p, spec=""):
    spec = (spec or "").strip()
    plans = p.get("print_plans") if isinstance(p.get("print_plans"), dict) else {}
    plan = plans.get(spec)
    if spec and plan and plan.get("follow") and plan.get("scale"):
        return scaled_plan(p, spec, plan)
    if not plan or not plan.get("plates"):
        return _migrate(p, spec, default_plan(p, spec))
    return _migrate(p, spec, plan)


# ---------------- v2.53 按主模型缩放的规格 / 从别的规格复制 ----------------
def scaled_plan(p, spec, sp):
    """「按主模型缩放 N%」的规格：主模型的方案，每个零件放大 / 缩小（不用另外的文件）。主模型方案改了自动跟着改。
    切片结果存在 sp["sliced_by"][盘号]（带摆盘签名，主模型改了摆盘就作废）。"""
    import copy
    base = copy.deepcopy(get_plan(p, ""))
    k = float(sp.get("scale") or 100) / 100.0
    for pl in base.get("plates") or []:
        for it in pl.get("items") or []:
            it["scale"] = round(_sc(it.get("scale")) * k, 4)
            it["x"] = it["y"] = None                     # 大小变了：重新排
        pl["manual"] = False
        pl.pop("sliced", None)
        got = (sp.get("sliced_by") or {}).get(pl["id"])
        if got and got.get("sig") == plate_sig(pl):
            pl["sliced"] = {k2: v for k2, v in got.items() if k2 != "sig"}
    base.update(follow=True, scale=sp.get("scale"), base_default=bool(base.get("default")))
    base.pop("default", None)
    base.pop("updated_at", None)
    if sp.get("updated_at"):
        base["updated_at"] = sp["updated_at"]
    return base


def _no_params(pl):
    return {k: v for k, v in pl.items() if k != "params"}


def plate_sig(pl):
    """按主模型缩放的规格存切片结果用的签名（切片、试打写回、概览、plan_summary 都用这一个）。
    读的时候按 recipe 补上的参数（_migrate 标了 AUTO_PRM，方案里其实没存）不算进签名：和 v2.55 以前存的签名一致，
    读的先后顺序也不影响结果。"""
    return _sig(_no_params(pl) if pl.get(AUTO_PRM) else pl)


def set_scale(pid, spec, pct, user=""):
    """规格的打印方案「按主模型缩放 N%」（pct 空 / 0 = 取消，回到默认）。"""
    p = store.load(pid)
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("主模型不能按自己缩放")
    plans = p.get("print_plans") if isinstance(p.get("print_plans"), dict) else {}
    if pct:
        plans[spec] = {"follow": True, "scale": round(float(pct), 1), "updated_at": time.time(), "updated_by": user}
    else:
        if (plans.get(spec) or {}).get("follow"):
            plans.pop(spec, None)
    p["print_plans"] = plans
    store.save(p)
    return get_plan(p, spec)


def copy_plan(pid, spec, src, user=""):
    """「从某个规格复制」打印方案（盘、零件、槽、配色），切片结果不带过去。"""
    import copy
    from core import specmodel
    p = store.load(pid)
    spec, src = (spec or "").strip(), (src or "").strip()
    for s in (spec, src):
        if s and s not in specmodel.specs(p):
            raise ValueError(f"这个产品没有规格「{s}」")
    if spec == src:
        raise ValueError("不能从自己复制")
    plan = copy.deepcopy(get_plan(p, plan_key(p, src) if src else ""))
    for pl in plan.get("plates") or []:
        pl.pop("sliced", None)
    for k in ("default", "follow", "sliced_by", "base_default", "scale"):
        plan.pop(k, None)
    plan.update(updated_at=time.time(), updated_by=user, copied_from=src)
    p.setdefault("print_plans", {})[spec] = clean_plan(p, plan) | {"updated_at": time.time(), "updated_by": user, "copied_from": src}
    _refresh_variants(p, spec, p["print_plans"][spec])
    store.save(p)
    return p["print_plans"][spec]


def _split_plates(pid, p, plate, bed):
    """一盘放不下：放不下的零件挪到新的一盘，直到都放下（最多 20 盘）。返回盘列表。"""
    out = [plate]
    cur = plate
    for _ in range(20):
        fps = fps_for(pid, p, cur)
        miss = auto_arrange(cur, bed, fps)
        if not miss:
            break
        W, D = float(bed[0]), float(bed[1])
        keep, move = [], []
        for it in cur["items"]:
            pg = _poly(fps[it["uid"]], it["x"], it["y"], it.get("rot") or 0)
            fits = max(px for px, _ in pg) <= W - MARGIN + 0.01 and max(py for _, py in pg) <= D - MARGIN + 0.01
            (keep if fits else move).append(it)
        if not move or not keep:
            break
        cur["items"] = keep
        auto_arrange(cur, bed, fps_for(pid, p, cur))
        nxt = {**{k: v for k, v in cur.items() if k not in ("items", "sliced")}, "id": f"p{len(out) + 1}", "items": move, "manual": False}
        out.append(nxt)
        cur = nxt
    return out


def plan_from_display(pid, spec="", user=""):
    """「从组装生成打印方案」：展示里的零件（数量照算）每个按推荐方向平放，自动排盘（一盘放不下自动分盘）。不保存，返回方案。"""
    from . import assembly
    p = store.load(pid)
    r = assembly.resolve(p, spec)
    if not r["items"]:
        raise ValueError("展示里还没有零件")
    lib = {e["id"]: e for e in p.get("model_lib") or []}
    cfg = load_config()
    old = get_plan(p, spec)
    first = (old.get("plates") or [{}])[0]
    printer = first.get("printer") or printer_models(cfg)[0]["name"]
    k = float(r.get("scale") or 1)
    items = []
    for key, it, _n in assembly.instances(r["items"]):
        if (r["poses"].get(key) or {}).get("hidden"):
            continue
        info = (lib.get(it["id"]) or {}).get("info") or {}
        src = info
        if it.get("part") is not None:
            src = next((x for x in info.get("parts") or [] if x.get("index") == it["part"]), None) or {}
        items.append({"uid": _uid(), "id": it["id"], "part": it.get("part"), "orient": src.get("best") or "bottom", "slot": 1,
                      "x": None, "y": None, "rot": 0, **({"scale": round(k, 4)} if abs(k - 1) > 1e-6 else {})})
    if not items:
        raise ValueError("展示里的零件都隐藏了")
    plate = {"id": "p1", "name": "", "printer": printer, "layer_height": float(first.get("layer_height") or 0.2), "sets": 1,
             "slots": [dict(s) for s in (first.get("slots") or [{"slot": 1, "material": p.get("material") or "PLA", "colour": ""}])][:1],
             "items": items, "manual": False}
    plates = _split_plates(pid, p, plate, bed_of(printer, cfg))
    for i, pl in enumerate(plates):
        pl["id"] = f"p{i + 1}"
        pl["manual"] = True
    return {"plates": plates, "schemes": dict(old.get("schemes") or {}), "from_display": True}


def _num(v, lo, hi, d):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return d


# ---------------- v2.55 每盘的打印参数（原来「打印方案」面板的参数，搬进来按盘设） ----------------
PARAM_KEYS = ("supports", "support_build_plate_only", "support_angle", "walls", "top_bottom", "infill_pct", "infill_pattern",
              "brim", "bed_type", "gap_mm", "nozzle_temp", "bed_temp", "filament", "notes")
PATTERNS = ["gyroid", "grid", "cubic", "crosshatch", "rectilinear", "honeycomb", "lightning", "line", "concentric", "triangles", "adaptivecubic",
            # v2.55：OrcaSlicer 其它的填充图案（AI 建议、导入的 3MF 里会有），不能被改成 gyroid
            "zig-zag", "2dlattice", "tri-hexagon", "alignedrectilinear", "3dhoneycomb", "hilbertcurve", "archimedeanchords",
            "octagramspiral", "supportcubic", "quartercubic", "crosszag", "lockedzag"]
# monotonic / monotonicline 是 OrcaSlicer 的顶面 / 底面图案，不能当填充（以前的下拉里有过）：按 rectilinear 切，提醒重新选
TOP_ONLY = {"monotonic", "monotonicline"}
SAFE_INFILL = "rectilinear"
OV_RANGE = {"layer_height": (0.04, 0.6, float), "infill_pct": (0, 100, int), "walls": (1, 20, int)}


def clean_params(d):
    """每盘参数（和 core/recipes.clean 一样的范围检查），层高在盘上（layer_height），不在这里。"""
    from core import recipes
    d = dict(d or {})
    r = recipes.clean(dict(d, layer_height=0.2))
    out = {k: r[k] for k in PARAM_KEYS}
    if out["infill_pattern"] not in PATTERNS:      # 不认识的图案保留原值（只去掉不合法的字符），不偷偷改成 gyroid
        out["infill_pattern"] = _re.sub(r"[^a-z0-9_-]+", "", str(out["infill_pattern"] or "").strip().lower())[:32] or "gyroid"
    if out["infill_pattern"] in TOP_ONLY:          # 顶面图案不能当填充
        out["infill_pattern"] = SAFE_INFILL
    if _has_temps(out) and d.get("temp_material"):  # 温度是给哪个材料设的（换了材料就作废，见 save_plan / temps_ok）
        out["temp_material"] = recipes.norm_material(d["temp_material"])[:20]
    return out


def _item_extra(it):
    """零件的 v2.55 字段：face（按面贴平台）、mirror（x / y / xy）、group（合并成组）、ov（单独参数：层高 / 填充 / 壁数）。"""
    out = {}
    fc = _face(it)
    if fc:
        n = math.sqrt(sum(x * x for x in fc))
        out["face"] = [round(x / n, 5) for x in fc]
    mx, my = _mir(it)
    if mx or my:
        out["mirror"] = ("x" if mx else "") + ("y" if my else "")
    if it.get("group"):
        out["group"] = str(it["group"])[:16]
    ov = {}
    for k, (lo, hi, cast) in OV_RANGE.items():
        v = (it.get("ov") or {}).get(k) if isinstance(it.get("ov"), dict) else None
        if v in (None, ""):
            continue
        try:
            ov[k] = cast(round(max(lo, min(hi, float(v))), 2))
        except (TypeError, ValueError):
            continue
    if ov:
        out["ov"] = ov
    return out


def base_params(p, spec=""):
    """还没有每盘参数的方案（v2.55 以前保存的 / 自动的一盘）：从原来的「打印方案」（产品 / 规格的 recipe，没有时 AI 建议 / 默认）搬过来。"""
    from core import recipes, specmodel
    try:
        v = specmodel.view(p, spec) if spec else dict(p, _spec="")
    except Exception:  # noqa: BLE001
        v = dict(p, _spec="")
    v = dict(v)
    v["print_plans"] = {}                 # 只要原来的参数，不要再从方案里读回来
    r = recipes.get(v)
    return clean_params({k: r.get(k) for k in PARAM_KEYS})


def _slot1(pl):
    try:
        return (pl.get("slots") or [{}])[0].get("material") or ""
    except (AttributeError, IndexError, TypeError):
        return ""


def _same_mat(a, b):
    from core import recipes
    return recipes.norm_material(a or "PLA") == recipes.norm_material(b or "PLA")


AUTO_PRM = "params_auto"       # 盘上的参数是读的时候按 recipe 补的（方案里没存）；保存时去掉


def _has_temps(prm):
    return bool((prm or {}).get("nozzle_temp") or (prm or {}).get("bed_temp"))


def _clear_mat_params(prm, filament=True):
    """槽 1 的材料和参数对应的材料不一样：按旧材料选的温度（和耗材配置）作废，用新材料配置里的。"""
    if filament:
        prm["filament"] = {}
    prm["nozzle_temp"] = 0
    prm["bed_temp"] = 0
    prm.pop("temp_material", None)


def _for_material(p, prm, slot1):
    """按产品材料（p["material"]）来的参数（recipe）给槽 1 是 slot1 的盘：材料一样 → 照用（记下温度是给哪个材料的）；
    不一样 → 不带耗材配置和温度（按这一盘的材料自动选）。"""
    from core import recipes
    out = dict(prm, filament=dict(prm.get("filament") or {}))
    out.pop("temp_material", None)
    if _same_mat(slot1, p.get("material")):
        if _has_temps(out):
            out["temp_material"] = recipes.norm_material(p.get("material") or "PLA")
    else:
        _clear_mat_params(out)
    return out


def temps_ok(p, pl):
    """盘上设的喷嘴 / 热床温度能不能给这一盘槽 1 的材料用：记着是给哪个材料的（temp_material）→ 要一致；
    没记（v2.55.0 及以前存的）→ 只有槽 1 是产品材料时才算数（那时的温度都是按产品材料的 recipe 来的）。"""
    prm = pl.get("params") or {}
    if not _has_temps(prm):
        return True
    tm = prm.get("temp_material")
    return _same_mat(tm, _slot1(pl)) if tm else _same_mat(_slot1(pl), p.get("material"))


def _migrate(p, spec, plan):
    """方案里每盘没有参数的，按原来的打印方案补上（不保存；保存时一起存）。
    原来的耗材配置、温度是按产品材料选的：槽 1 不是这个材料的盘不带过去（按材料自动选）。
    不改传进来的方案（p 里存的那份）：要补的时候返回一份拷贝，补上的盘标 AUTO_PRM（签名按「没存参数」算，plate_sig）。"""
    plates = (plan or {}).get("plates") or []
    if not any(not isinstance(pl.get("params"), dict) for pl in plates):
        return plan
    base = base_params(p, spec)
    plan = dict(plan)
    plan["plates"] = [pl if isinstance(pl.get("params"), dict) else dict(pl, params=_for_material(p, base, _slot1(pl)), **{AUTO_PRM: True})
                      for pl in plates]
    return plan


def recipe_of(p, plate):
    """一盘按原来「打印方案」的格式（core/recipes 的字段）：切片、检查、生产单上的说明都能照旧用。"""
    from core import recipes
    r = dict(recipes.DEFAULT)
    r.update(recipes.get(dict(p, print_plans={})))
    r.update({k: v for k, v in (plate.get("params") or {}).items() if k in PARAM_KEYS})
    r["layer_height"] = float(plate.get("layer_height") or r.get("layer_height") or 0.2)
    its = plate.get("items") or []
    if its and not _face(its[0]) and its[0].get("orient") in mesh.ORIENT_ZH:
        r["orientation"] = its[0]["orient"]
    return r


def clean_plan(p, data, cfg=None):
    """检查并整理前台交上来的方案。"""
    cfg = cfg or load_config()
    names = {m["name"] for m in printer_models(cfg)}
    lib = {e["id"]: e for e in p.get("model_lib") or [] if isinstance(e, dict) and e.get("id")}
    plates = []
    for i, pl in enumerate((data or {}).get("plates") or []):
        if i >= 20:
            break
        slots = []
        for s in (pl.get("slots") or [])[:SLOT_MAX]:
            n = len(slots) + 1
            slots.append({"slot": n, "material": str(s.get("material") or p.get("material") or "PLA").upper()[:20],
                          "colour": str(s.get("colour") or "")[:30], **({"file_slot": int(s["file_slot"])} if s.get("file_slot") else {}),
                          **({"hex": str(s["hex"])[:9]} if s.get("hex") else {})})
        if not slots:
            slots = [{"slot": 1, "material": p.get("material") or "PLA", "colour": ""}]
        items = []
        for it in (pl.get("items") or [])[:200]:
            if it.get("id") not in lib:
                raise ValueError("方案里有模型库里没有的文件（可能被删了），刷新一下")
            part = it.get("part")
            items.append({"uid": str(it.get("uid") or _uid())[:12], "id": it["id"], "part": None if part in (None, "") else int(part),
                          "orient": it.get("orient") if it.get("orient") in mesh.ORIENT_ZH else "bottom",
                          "slot": int(_num(it.get("slot"), 1, len(slots), 1)),
                          "x": None if it.get("x") in (None, "") else round(_num(it["x"], -2000, 2000, 0), 1),
                          "y": None if it.get("y") in (None, "") else round(_num(it["y"], -2000, 2000, 0), 1),
                          "rot": round(_num(it.get("rot"), -360, 360, 0), 1) % 360,
                          **({"scale": round(_sc(it["scale"]), 4)} if _sc(it.get("scale")) != 1.0 else {}),
                          **_item_extra(it)})
        if len({it["uid"] for it in items}) != len(items):
            for it in items:
                it["uid"] = _uid()
        printer = pl.get("printer") if pl.get("printer") in names else (sorted(names)[0] if names else "Bambu Lab P1S")
        plates.append({"id": str(pl.get("id") or f"p{i + 1}")[:12], "name": str(pl.get("name") or "")[:40], "printer": printer,
                       "layer_height": round(_num(pl.get("layer_height"), 0.04, 0.6, 0.2), 2), "sets": int(_num(pl.get("sets"), 1, 200, 1)),
                       "slots": slots, "items": items, "manual": bool(pl.get("manual")),
                       **({"params": clean_params(pl["params"])} if isinstance(pl.get("params"), dict) else {}),
                       **({"sliced": pl["sliced"]} if isinstance(pl.get("sliced"), dict) else {})})
    if not plates:
        raise ValueError("至少要有一盘")
    schemes = {}
    for col, m in ((data or {}).get("schemes") or {}).items():
        if isinstance(m, dict):
            schemes[str(col)[:30]] = {str(int(k)): str(v)[:30] for k, v in m.items() if str(k).isdigit() and 1 <= int(k) <= SLOT_MAX and v}
    return {"plates": plates, "schemes": schemes}


def fps_for(pid, p, plate):
    out = {}
    for it in plate.get("items") or []:
        out[it["uid"]] = footprint(pid, it["id"], it.get("part"), it.get("orient"), p, it.get("scale") or 1, it.get("face"), it.get("mirror") or "")
    return out


def save_plan(pid, spec, data, user=""):
    """保存方案。手动摆过的盘要求不重叠、不超出热床（返回检查结果，有问题不保存）。"""
    p = store.load(pid)
    modellib._sync(p)
    spec = (spec or "").strip()
    from core import specmodel
    if spec and spec not in specmodel.specs(p):
        raise ValueError(f"这个产品没有规格「{spec}」")
    plan = _migrate(p, spec, clean_plan(p, data))
    prev = get_plan(p, spec)
    checks = {}
    for pl in plan["plates"]:
        fps = fps_for(pid, p, pl)
        bed = bed_of(pl["printer"])
        if not pl["manual"] or any(it.get("x") is None for it in pl["items"]):
            auto_arrange(pl, bed, fps)
        ck = check_plate(pl, bed, fps)
        checks[pl["id"]] = ck
        if pl["manual"] and not ck["ok"]:
            raise ValueError(f"第 {plan['plates'].index(pl) + 1} 盘：" + "，".join(ck["problems"]) + "（红色的零件挪一挪，或点「自动排列」）")
        old = next((x for x in (prev.get("plates") or []) if x.get("id") == pl["id"]), None)
        _check_mat_params(p, pl, old)
        if old and old.get("sliced") and (_sig(old) != _sig(pl) or (old.get("params") or {}) != (pl.get("params") or {})):
            pl.pop("sliced", None)                  # 改了摆盘 / 颜色 / 参数：以前的切片结果不能用了
    for pl in plan["plates"]:
        pl.pop(AUTO_PRM, None)                  # 保存了：补上的参数现在是方案里存的了
    plan["updated_at"], plan["updated_by"] = time.time(), user
    if not isinstance(p.get("print_plans"), dict):
        p["print_plans"] = {}
    p["print_plans"][spec] = plan
    cleanup_cuts(pid, p)                         # 切开的两半：用上了留下，没用上的（过一阵）清掉
    _sync_material(p, spec, prev, plan)
    _mirror_recipe(p, spec, plan, user)
    _refresh_variants(p, spec, plan)
    store.save(p)
    return {"plan": plan, "checks": checks}


def _check_mat_params(p, pl, old):
    """安全（打印机温度）：槽 1 换了材料 → 原来按旧材料选的耗材配置和温度作废；温度记着是给别的材料设的 → 作废；
    没记是给哪个材料的（v2.55.0 存的）、槽 1 又不是产品材料 → 温度多半是按产品材料的 recipe 带过来的，作废。
    留下的温度记上 temp_material = 槽 1 的材料。"""
    from core import recipes
    prm = pl.get("params")
    if not isinstance(prm, dict):
        return
    s1 = _slot1(pl)
    tm = prm.get("temp_material")
    if old and not _same_mat(_slot1(old), s1):
        _clear_mat_params(prm)
    elif tm and not _same_mat(tm, s1):
        _clear_mat_params(prm)
    elif not tm and _has_temps(prm) and not _same_mat(s1, p.get("material")):
        _clear_mat_params(prm, filament=False)
    if _has_temps(prm):
        prm["temp_material"] = recipes.norm_material(s1 or p.get("material") or "PLA")
    else:
        prm.pop("temp_material", None)


def _sync_material(p, spec, prev, plan):
    """v2.55：主模型方案第 1 盘槽 1 的材料 = 产品材料（原来「打印方案」面板里的「打印材料」）。改了 → 产品材料跟着改，
    之前指定的耗材配置作废（和原来面板一样）。"""
    from core import recipes
    if spec:
        return
    try:
        new = plan["plates"][0]["slots"][0]["material"]
        old = (prev.get("plates") or [{}])[0].get("slots", [{}])[0].get("material")
    except (IndexError, KeyError, TypeError):
        return
    if new and old and recipes.norm_material(new) != recipes.norm_material(old) and \
            recipes.norm_material(new) != recipes.norm_material(p.get("material") or "PLA"):
        p["material"] = recipes.norm_material(new)
        for pl in plan["plates"]:
            (pl.get("params") or {})["filament"] = {}


def _mirror_recipe(p, spec, plan, user=""):
    """v2.55：方案是唯一的来源；原来的 product["recipe"]（有自己模型的规格：spec_recipes）照着第 1 盘写一份，
    老代码（recipes.get、按方案切片、生产单说明、一盘几个）读到的和方案一致。"""
    from core import recipes, specmodel
    pl = (plan.get("plates") or [None])[0]
    if not pl:
        return
    upd = {k: v for k, v in (pl.get("params") or {}).items() if k in PARAM_KEYS}
    upd["layer_height"] = round(min(0.32, max(0.08, float(pl.get("layer_height") or 0.2))), 2)
    e = _spec_entry(p, spec)
    its = pl.get("items") or []
    if e and its and all(it["id"] == e["id"] and it.get("part") in (None, "") for it in its) and not _face(its[0]) \
            and its[0].get("orient") in mesh.ORIENT_ZH:
        upd["orientation"] = its[0]["orient"]
    if not spec:
        cur = p.get("recipe")
        if not isinstance(cur, dict) or not cur:
            cur = {k: v for k, v in recipes.get(dict(p, print_plans={})).items() if k != "from_ai"}
        cur.update(upd)
        cur["updated_at"], cur["updated_by"] = time.time(), user or cur.get("updated_by") or ""
        p["recipe"] = cur
    elif specmodel.own(p, spec):
        srs = p.setdefault("spec_recipes", {})
        cur = srs.get(spec)
        if not isinstance(cur, dict):
            cur = {k: v for k, v in (p.get("recipe") or {}).items() if k not in ("capacity_learned", "updated_at")}
        cur.update(upd)
        cur["updated_at"], cur["updated_by"] = time.time(), user or ""
        srs[spec] = cur


def apply_recipe(pid, spec, r):
    """原来的「打印方案」接口保存后（v2.55 兼容）：参数写进对应方案的每一盘，方向写进用主模型文件的零件。没保存过方案时不用管
    （没保存过的方案每次按 recipe 生成）。"""
    from core import specmodel
    p = store.load(pid)
    key = spec if spec and specmodel.own(p, spec) else ""
    plans = p.get("print_plans") if isinstance(p.get("print_plans"), dict) else {}
    plan = plans.get(key)
    if not plan or plan.get("follow") or not plan.get("plates"):
        return False
    e = _spec_entry(p, key)
    prm = clean_params({k: r.get(k) for k in PARAM_KEYS})
    for pl in plan["plates"]:
        want = _for_material(p, prm, _slot1(pl))     # 槽 1 不是产品材料的盘：不带按产品材料选的耗材配置和温度
        if want != pl.get("params") or abs(float(pl.get("layer_height") or 0) - float(r.get("layer_height") or 0.2)) > 1e-6:
            pl.pop("sliced", None)
        pl["params"] = want
        pl["layer_height"] = float(r.get("layer_height") or 0.2)
        for it in pl.get("items") or []:
            if e and it["id"] == e["id"] and it.get("part") in (None, "") and r.get("orientation") in mesh.ORIENT_ZH \
                    and (it.get("orient") != r["orientation"] or it.get("face")):
                it["orient"] = r["orientation"]
                it.pop("face", None)
                pl["manual"] = False             # 方向变了：外形变了，重新自动排
                pl.pop("sliced", None)
        if not pl.get("manual"):
            for it in pl.get("items") or []:
                it["x"] = it["y"] = None
    store.save(p)
    return True


def _sig(pl):
    """摆盘签名（改了就要重新切片）。v2.55 的新字段（按面贴平台 / 镜像 / 单独参数 / 每盘参数）只在用到时加进去，旧的签名不变。
    每盘参数（支撑、壁数、填充、温度、耗材配置…）：按主模型缩放的规格靠这个知道主模型改了参数、以前的切片不能用了。"""
    ext = [(it.get("uid"), _item_extra(it)) for it in pl.get("items") or [] if any(k in _item_extra(it) for k in ("face", "mirror", "ov"))]
    out = _sig0(pl) + (repr(ext) if ext else "")
    if isinstance(pl.get("params"), dict) and pl["params"]:
        import hashlib
        import json
        out += "|prm:" + hashlib.md5(json.dumps(pl["params"], sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:12]
    return out


def _sig0(pl):
    return repr([(it["id"], it.get("part"), it.get("orient"), it.get("slot"), it.get("x"), it.get("y"), it.get("rot"), _sc(it.get("scale")))
                 for it in pl.get("items") or []]
                + [(s["slot"], s.get("material")) for s in pl.get("slots") or []] + [pl.get("printer"), pl.get("layer_height")])


def plate_selection(plate):
    """给 modellib（合并 / 预览摆盘 / 导出）用的选择：每个零件一件，带位置。"""
    return [{"id": it["id"], "part": it.get("part"), "qty": 1, "orient": it.get("orient") or "bottom",
             **({"scale": _sc(it.get("scale"))} if _sc(it.get("scale")) != 1.0 else {}),
             **{k: v for k, v in _item_extra(it).items() if k in ("face", "mirror")},
             **({"x": it["x"], "y": it["y"], "rot": it.get("rot") or 0} if it.get("x") is not None and it.get("y") is not None else {})}
            for it in plate.get("items") or []]


# ---------------- 颜色 ----------------
def colours_for(plan, plate, colour):
    """这一盘在「colour 款」下每个槽装什么颜色：{槽: 颜色}。配色方案 > 槽的固定颜色 > 款式颜色。"""
    sch = (plan.get("schemes") or {}).get(colour or "") or {}
    out = {}
    for s in plate.get("slots") or []:
        k = str(s["slot"])
        out[s["slot"]] = sch.get(k) or s.get("colour") or colour or ""
    return out


def is_multicolor(plan, colour=""):
    for pl in plan.get("plates") or []:
        if len({c for c in colours_for(plan, pl, colour).values() if c} | set()) > 1:
            return True
    return False


def _cfg_num(cfg, k, d):
    try:
        v = float(cfg.get(k))
        return v if v >= 0 else d
    except (TypeError, ValueError):
        return d


def _item_est(p, it, cfg):
    """一个零件的估算克数 / 时长（模型库的分析结果，按体积估）。"""
    e = next((x for x in p.get("model_lib") or [] if x.get("id") == it["id"]), None) or {}
    info = e.get("info") or {}
    src = info
    if it.get("part") not in (None, ""):
        src = next((x for x in info.get("parts") or [] if x.get("index") == int(it["part"])), None) or {}
    est = src.get("sliced_result") if src is info and info.get("sliced_result") else src.get("est") or {}
    k = _sc(it.get("scale"))            # 按主模型缩放：克数按体积（k³），时长大约按 k^2.5（估）
    return float(est.get("grams") or 0) * k ** 3, float(est.get("hours") or 0) * k ** 2.5, info, src


def purge_estimate(heights, layer_h, cfg=None):
    """估算换色次数和冲刷废料：heights = 每种颜色的零件最高多高（毫米）。
    每一层上有 k 种颜色就要换 k-1 次（拓竹 AMS 每层按颜色顺序打）。返回 {changes, purge_g, extra_h}（都是估算）。"""
    cfg = cfg or load_config()
    hs = sorted([float(h) for h in heights if h and h > 0], reverse=True)
    lh = max(0.04, float(layer_h or 0.2))
    changes = 0.0
    for k in range(2, len(hs) + 1):
        lower = hs[k] if k < len(hs) else 0.0
        changes += (k - 1) * max(0.0, hs[k - 1] - lower) / lh
    changes = int(round(changes))
    per = _cfg_num(cfg, "mc_purge_g", 1.5)
    sec = _cfg_num(cfg, "mc_change_s", 50)
    return {"changes": changes, "purge_g": round(changes * per, 1), "extra_h": round(changes * sec / 3600, 2), "est": True}


def plate_usage(p, plan, plate, colour="", cfg=None, fps=None):
    """一盘在某个款式颜色下：每个槽用多少克、冲刷废料、时长。有切片结果用切片的，没有就按体积估（est=True）。"""
    cfg = cfg or load_config()
    cols = colours_for(plan, plate, colour)
    mats = {s["slot"]: s.get("material") or p.get("material") or "PLA" for s in plate.get("slots") or []}
    per_slot = {s["slot"]: 0.0 for s in plate.get("slots") or []}
    hours = 0.0
    heights = {}
    painted = None
    for it in plate.get("items") or []:
        g, h, info, src = _item_est(p, it, cfg)
        hours += h
        ci = info.get("colors") if (info.get("colors") or {}).get("multicolor") and it.get("part") in (None, "") else None
        if ci:                                  # 涂色 / 多色 3MF：按文件里每种耗材的用量分（没有用量就平分，估）
            painted = ci
            fslots = [s for s in plate.get("slots") or [] if s.get("file_slot")] or plate.get("slots") or []
            use = {u.get("slot"): float(u.get("grams") or 0) for u in ci.get("usage") or []}
            tot = sum(use.values())
            for s in fslots:
                share = (use.get(s.get("file_slot") or s["slot"], 0) / tot) if tot else 1 / max(1, len(fslots))
                per_slot[s["slot"]] = per_slot.get(s["slot"], 0) + g * share
            hh = (info.get("size") or [0, 0, 0])[2]
            for s in fslots:
                heights[cols.get(s["slot"])] = max(heights.get(cols.get(s["slot"]), 0), hh)
        else:
            sl = int(it.get("slot") or 1)
            per_slot[sl] = per_slot.get(sl, 0) + g
            if fps and it["uid"] in fps:
                hh = fps[it["uid"]]["h"]
            else:
                o = next((x for x in (src.get("orients") or []) if x.get("key") == it.get("orient")), None)
                hh = ((o or {}).get("height_mm") or (src.get("size") or [0, 0, 0])[2]) * _sc(it.get("scale"))
            heights[cols.get(sl)] = max(heights.get(cols.get(sl), 0), float(hh or 0))
    sl_res = plate.get("sliced") or {}
    est = True
    if sl_res.get("filaments"):
        est = False
        per_slot = {int(f["slot"]): float(f.get("grams") or 0) for f in sl_res["filaments"]}
        hours = float(sl_res.get("hours") or hours)
    # 同一种颜色装在两个槽里 → 合在一起算
    by_col = {}
    for sl, g in per_slot.items():
        c = cols.get(sl) or colour or ""
        k = (c, mats.get(sl, "PLA"))
        by_col.setdefault(k, {"colour": c, "material": mats.get(sl, "PLA"), "grams": 0.0, "slots": []})
        by_col[k]["grams"] += g
        by_col[k]["slots"].append(sl)
    colours_used = [v for v in by_col.values() if v["grams"] > 0 or len(by_col) == 1]
    n_col = len({v["colour"] for v in colours_used})
    if sl_res.get("filaments"):
        pg = {"changes": int(sl_res.get("changes") or 0), "purge_g": float(sl_res.get("purge_g") or 0), "extra_h": 0.0, "est": False}
    elif n_col > 1:
        pg = purge_estimate([heights.get(v["colour"], 0) for v in colours_used], plate.get("layer_height"), cfg)
        if painted and painted.get("painted"):    # 涂色：每层都可能换色 → 按最高的高度、所有颜色算
            hmax = max(heights.values() or [0])
            pg = purge_estimate([hmax] * n_col, plate.get("layer_height"), cfg)
    else:
        pg = {"changes": 0, "purge_g": 0.0, "extra_h": 0.0, "est": est}
    return {"id": plate["id"], "printer": plate.get("printer"), "sets": int(plate.get("sets") or 1),
            "colours": [{"colour": v["colour"], "material": v["material"], "grams": round(v["grams"], 1), "slots": v["slots"]} for v in colours_used],
            "slots": [{"slot": s["slot"], "material": mats.get(s["slot"]), "colour": cols.get(s["slot"]) or "", "grams": round(per_slot.get(s["slot"], 0), 1)}
                      for s in plate.get("slots") or []],
            "grams": round(sum(per_slot.values()), 1), "purge_g": pg["purge_g"], "changes": pg["changes"],
            "hours": round(hours + pg["extra_h"], 2), "est": est or pg.get("est", True), "multicolor": n_col > 1}


def usage(p, spec="", colour="", cfg=None):
    """一件成品（一套）在某款式颜色下的用料：各颜色克数（含冲刷废料按比例摊）、时长。
    返回 {"plates": [...], "colours": [{colour, material, grams}], "grams", "purge_g", "hours", "multicolor", "est"}"""
    cfg = cfg or load_config()
    plan = get_plan(p, spec)
    plates = [plate_usage(p, plan, pl, colour, cfg) for pl in plan.get("plates") or []]
    per = {}
    purge = hours = 0.0
    for u in plates:
        n = max(1, u["sets"])
        for c in u["colours"]:
            k = (c["colour"], c["material"])
            per.setdefault(k, {"colour": c["colour"], "material": c["material"], "grams": 0.0})
            per[k]["grams"] += c["grams"] / n
        purge += u["purge_g"] / n
        hours += u["hours"] / n
    cols = [dict(v, grams=round(v["grams"], 1)) for v in per.values()]
    if purge and cols:                       # 冲刷废料按各颜色用量比例摊（扣库存时也这样扣）
        tot = sum(c["grams"] for c in cols) or 1
        for c in cols:
            c["purge_g"] = round(purge * c["grams"] / tot, 1)
    return {"plates": plates, "colours": cols, "grams": round(sum(c["grams"] for c in cols) + purge, 1),
            "purge_g": round(purge, 1), "hours": round(hours, 2), "multicolor": len({c["colour"] for c in cols}) > 1,
            "est": any(u["est"] for u in plates), "default": bool(plan.get("default"))}


# ---------------- 生产用 ----------------
def job_colours(product_id, sku, colour=""):
    """生产任务要用的颜色（每件）：[{colour, material, grams}]；单色返回一项。读不到产品返回 []。"""
    try:
        p = store.load(product_id)
    except (FileNotFoundError, OSError, ValueError):
        return []
    from core import specmodel
    spec = specmodel.spec_of_sku(p, sku)
    if not colour:
        colour = next(((v.get("opt1_zh") or "") for v in p.get("variants") or [] if (v.get("sku") or "").upper() == (sku or "").upper()), "")
    plans = p.get("print_plans") if isinstance(p.get("print_plans"), dict) else {}
    key = plan_key(p, spec)          # v2.53.1：有自己模型 / 自己方案的规格用自己的（不再借主模型的方案）
    if key not in plans:
        return []
    u = usage(p, key, colour)
    return [{"colour": c["colour"], "material": c["material"], "grams": round(c["grams"] + c.get("purge_g", 0), 1)} for c in u["colours"]]


def _plan_for_sku(p, sku):
    """(规格键, 方案)：这个 SKU 用哪份方案（规格自己的 > 主模型的）；都没保存过 → (规格, None)。"""
    from core import specmodel
    spec = specmodel.spec_of_sku(p, sku)
    plans = p.get("print_plans") if isinstance(p.get("print_plans"), dict) else {}
    key = plan_key(p, spec)          # v2.53.1：有自己模型但没保存方案的规格不借主模型的盘
    if key not in plans:
        return key, None
    plan = get_plan(p, key) if (plans.get(key) or {}).get("follow") else (plans.get(key) or {})
    return key, (plan if plan.get("plates") else None)


def job_plates(product_id, sku, colour=""):
    """v2.52 生产：一件成品要打几盘。方案有两盘以上（不是自动默认的一盘）时返回每一盘：
    [{plate_id, no, total, name, sets, printer, spec, grams, hours, colours: [{colour, material, grams}], multicolor}]
    grams / hours / colours 都是「打一次这一盘」的用量（含冲刷废料）。一盘的方案 / 没有方案 → []（生产照旧按整件打）。"""
    try:
        p = store.load(product_id)
    except (FileNotFoundError, OSError, ValueError):
        return []
    spec, plan = _plan_for_sku(p, sku)
    if not plan or plan.get("default") or len(plan.get("plates") or []) < 2:
        return []
    if not colour:
        colour = next(((v.get("opt1_zh") or "") for v in p.get("variants") or [] if (v.get("sku") or "").upper() == (sku or "").upper()), "")
    cfg = load_config()
    plates = plan["plates"]
    out = []
    for i, pl in enumerate(plates):
        u = plate_usage(p, plan, pl, colour, cfg)
        tot = sum(c["grams"] for c in u["colours"]) or 0
        cols = [{"colour": c["colour"], "material": c["material"],
                 "grams": round(c["grams"] + (u["purge_g"] * c["grams"] / tot if tot else 0), 1)} for c in u["colours"]]
        out.append({"plate_id": pl["id"], "no": i + 1, "total": len(plates), "name": pl.get("name") or "",
                    "sets": max(1, int(pl.get("sets") or 1)), "printer": pl.get("printer") or "", "spec": spec,
                    "grams": round(u["grams"] + u["purge_g"], 1), "hours": u["hours"], "colours": cols,
                    "multicolor": len({c["colour"] for c in cols if c["colour"]}) > 1})
    return out


def plate_info(p, spec, plate_id):
    """切片文件记着是哪一盘：{no, total, name}（方案里已经没有这一盘 → None）。"""
    plans = p.get("print_plans") if isinstance(p.get("print_plans"), dict) else {}
    plan = plans.get(spec or "") or {}
    if plan.get("follow"):
        plan = get_plan(p, spec or "")
    plates = plan.get("plates") or []
    for i, pl in enumerate(plates):
        if pl.get("id") == plate_id:
            return {"no": i + 1, "total": len(plates), "name": pl.get("name") or ""}
    return None


def ams_line(cols, lang="zh"):
    """「AMS 槽 1 白 PLA · 槽 2 黑 PLA」"""
    if lang == "th":
        return " · ".join(f"AMS ช่อง {i + 1} {c['colour']} {c['material']}" for i, c in enumerate(cols))
    return " · ".join(f"AMS 槽 {i + 1} {c['colour']} {c['material']}" for i, c in enumerate(cols))


def run_colours(product_id, sku, colour, count, total_grams=None):
    """一盘 count 件的各颜色用料（扣耗材库存用）。有切片文件的总克数时按比例缩放。"""
    cols = job_colours(product_id, sku, colour)
    if len({c["colour"] for c in cols}) < 2:
        return []
    out = [{"colour": c["colour"], "material": c["material"], "grams": c["grams"] * max(1, int(count or 1))} for c in cols]
    tot = sum(c["grams"] for c in out)
    if total_grams and tot:
        k = float(total_grams) / tot
        for c in out:
            c["grams"] = c["grams"] * k
    for c in out:
        c["grams"] = round(c["grams"], 1)
    return out


def fill_variants(pid, spec, user=""):
    """按打印方案算每个款式（颜色）的克数 / 时长，填进这个规格的变体（标记 grams_src = plan / plan_est）。"""
    p = store.load(pid)
    n = 0
    for v in p.get("variants") or []:
        if (v.get("opt2_zh") or "").strip() != (spec or ""):
            continue
        u = usage(p, spec, v.get("opt1_zh") or "")
        if not u["grams"]:
            continue
        v["grams"] = u["grams"]
        if u["hours"]:
            v["hours"] = u["hours"]
        v["grams_src"] = "plan_est" if u["est"] else "plan"
        v["colour_usage"] = u["colours"] if u["multicolor"] else None
        v["purge_g"] = u["purge_g"] if u["multicolor"] else None
        n += 1
    store.save(p)
    return n


def apply_actual(pid, spec, plate_id, grams, hours, sku=""):
    """v2.53 试打成功后：实际克数（含冲刷）/ 时长写回这一盘的切片结果，再按方案重算款式的克数 / 时长（成本跟着变）。
    还没保存过方案的（默认一盘）直接写这个规格的款式。返回更新了哪些 SKU。"""
    spec = (spec or "").strip()
    p = store.load(pid)
    plans = p.get("print_plans") if isinstance(p.get("print_plans"), dict) else {}
    key = plan_key(p, spec)          # v2.53.1：和切片文件同一个规格（按主模型缩放的规格写自己的，不写主模型）
    saved = plans.get(key)
    grams = float(grams) if grams not in (None, "") else None
    hours = float(hours) if hours not in (None, "") else None
    if not saved or saved.get("default") or not (saved.get("plates") or saved.get("follow")):
        out = []
        plan = get_plan(p, key)
        sets = max(1, int(next((x.get("sets") or 1 for x in plan.get("plates") or [] if x["id"] == plate_id), 1)))
        for v in p.get("variants") or []:
            if (v.get("opt2_zh") or "").strip() != spec:
                continue
            if grams:
                v["grams"] = round(grams / sets, 1)
            if hours:
                v["hours"] = round(hours / sets, 2)
            v["grams_src"] = "trial"
            out.append(v.get("sku") or "")
        store.save(p)
        return out
    plan = get_plan(p, key)
    plate = next((x for x in plan.get("plates") or [] if x["id"] == plate_id), None)
    if not plate:
        return []
    sl = dict(plate.get("sliced") or ((saved.get("sliced_by") or {}).get(plate_id)) or {})
    purge = float(sl.get("purge_g") or 0)
    net = max(0.0, (grams if grams else float(sum(f.get("grams") or 0 for f in sl.get("filaments") or []) + purge)) - purge)
    fil = sl.get("filaments") or []
    if not fil:
        slots = sorted({int(it.get("slot") or 1) for it in plate.get("items") or []}) or [1]
        fil = [{"slot": k, "grams": 1.0} for k in slots]
    tot = sum(float(f.get("grams") or 0) for f in fil) or 1.0
    sl["filaments"] = [{"slot": f["slot"], "grams": round(net * float(f.get("grams") or 0) / tot, 2)} for f in fil]
    if hours:
        sl["hours"] = hours
    sl["trial"] = True
    sl["at"] = time.time()
    if saved.get("follow"):
        saved.setdefault("sliced_by", {})[plate_id] = dict(sl, sig=plate_sig(plate))
    else:
        for x in saved["plates"]:
            if x["id"] == plate_id:
                x["sliced"] = sl
    p["print_plans"] = plans
    store.save(p)
    n = fill_variants(pid, spec, "试打")
    p = store.load(pid)
    out = []
    for v in p.get("variants") or []:
        if (v.get("opt2_zh") or "").strip() == spec:
            v["grams_src"] = "trial"
            out.append(v.get("sku") or "")
    store.save(p)
    return out


def _refresh_variants(p, spec, plan):
    """保存方案后：多色的款式记下各颜色用量（成本按颜色拆分、扣库存用），克数不动（要填克数点「填入变体」）。"""
    for v in p.get("variants") or []:
        if (v.get("opt2_zh") or "").strip() != (spec or ""):
            continue
        p2 = dict(p)
        p2["print_plans"] = dict(p.get("print_plans") or {}, **{spec: plan})
        u = usage(p2, spec, v.get("opt1_zh") or "")
        v["colour_usage"] = u["colours"] if u["multicolor"] else None
        v["purge_g"] = u["purge_g"] if u["multicolor"] else None


# ---------------- 一盘的 3MF（按摆好的位置、每个零件带耗材槽） ----------------
def plate_objects(pid, plate, p=None):
    """[(名字, 三角面（原点在零件外框底面中心）, (x, y, 0), 槽, 单独参数)]：按摆好的位置。"""
    p = p or store.load(pid)
    out = []
    for it in plate.get("items") or []:
        _fp, tris, label = _tris_of(pid, p, it["id"], it.get("part"), it.get("scale") or 1)
        t = _oriented(tris, it)
        v = t.reshape(-1, 3)
        mn, mx = v.min(0), v.max(0)
        t = t - np.array([(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]])
        a = math.radians(float(it.get("rot") or 0))
        if a:
            rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
            t = (t.reshape(-1, 3) @ rz.T).reshape(-1, 3, 3)
        out.append((label, t, (float(it.get("x") or 0), float(it.get("y") or 0), 0.0), int(it.get("slot") or 1), dict(it.get("ov") or {})))
    return out


# v2.55：零件单独参数 → OrcaSlicer 的对象参数（写在 Metadata/model_settings.config 的 <object> 里，实测 OrcaSlicer 2.3.1 会用）
OV_KEYS = {"layer_height": lambda v: f"{float(v):g}", "infill_pct": lambda v: f"{int(v)}%", "walls": lambda v: str(int(v))}
OV_ORCA = {"layer_height": "layer_height", "infill_pct": "sparse_infill_density", "walls": "wall_loops"}


def ov_metadata(ov):
    """零件单独参数 {layer_height, infill_pct, walls} → [(OrcaSlicer 参数名, 值)]"""
    out = []
    for k, fn in OV_KEYS.items():
        if (ov or {}).get(k) not in (None, ""):
            try:
                out.append((OV_ORCA[k], fn(ov[k])))
            except (TypeError, ValueError):
                pass
    return out


def write_plate_3mf(path, objects, slots=None):
    """写一个最简单的 3MF：每个零件一个对象，build 里按位置摆；Metadata/model_settings.config 写每个零件用哪个耗材槽
    （拓竹 Studio / OrcaSlicer 打开就是分好色的）。"""
    import zipfile
    from xml.sax.saxutils import quoteattr
    res, build, settings = [], [], []
    for i, ob in enumerate(objects, start=1):
        name, tris, pos, slot = ob[:4]
        ov = ob[4] if len(ob) > 4 else None
        v = np.asarray(tris, dtype=np.float64).reshape(-1, 3)
        uniq, inv = np.unique(np.round(v, 4), axis=0, return_inverse=True)
        inv = inv.reshape(-1, 3)
        vs = "".join(f'<vertex x="{a:.4f}" y="{b:.4f}" z="{c:.4f}"/>' for a, b, c in uniq)
        ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in inv if a != b and b != c and a != c)
        res.append(f'<object id="{i}" name={quoteattr(name)} type="model"><mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>')
        build.append(f'<item objectid="{i}" transform="1 0 0 0 1 0 0 0 1 {pos[0]:.3f} {pos[1]:.3f} {pos[2]:.3f}" printable="1"/>')
        extra = "".join(f'<metadata key="{k}" value={quoteattr(v)}/>' for k, v in ov_metadata(ov))
        settings.append(f'<object id="{i}"><metadata key="name" value={quoteattr(name)}/><metadata key="extruder" value="{int(slot)}"/>{extra}'
                        f'<part id="{i}" subtype="normal_part"><metadata key="name" value={quoteattr(name)}/><metadata key="extruder" value="{int(slot)}"/></part></object>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources>' + "".join(res) +
             "</resources><build>" + "".join(build) + "</build></model>")
    ct = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    ms = '<?xml version="1.0" encoding="UTF-8"?>\n<config>' + "".join(settings) + "</config>"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/model_settings.config", ms)
        if slots:
            import json
            z.writestr("Metadata/project_settings.config", json.dumps({
                "filament_colour": [s.get("hex") or "#FFFFFF" for s in slots],
                "filament_type": [s.get("material") or "PLA" for s in slots]}))
    return path


def export_plate(pid, spec, plate_id, colour="", out_path=None):
    """把一盘按摆好的位置导出成 3MF（下载 / 切片用）。返回 (路径, 文件名)。"""
    import tempfile
    from core import codes
    p = store.load(pid)
    plan = get_plan(p, spec)
    plate = next((x for x in plan["plates"] if x["id"] == plate_id), None)
    if not plate:
        raise ValueError("没有这一盘（刷新一下）")
    fps = fps_for(pid, p, plate)
    if not plate.get("manual") or any(it.get("x") is None for it in plate["items"]):
        auto_arrange(plate, bed_of(plate["printer"]), fps)
    cmap = codes.color_hex(load_config())
    cols = colours_for(plan, plate, colour)
    slots = [dict(s, hex=(cmap.get(cols.get(s["slot"]) or "") or {}).get("hex") or s.get("hex") or "#FFFFFF") for s in plate["slots"]]
    objs = plate_objects(pid, plate, p)
    out_path = out_path or tempfile.NamedTemporaryFile(suffix=".3mf", delete=False).name
    write_plate_3mf(out_path, objs, slots)
    name = f"{pid}{'_' + spec if spec else ''}_{plate_id}{'_' + colour if colour else ''}.3mf".replace(" ", "_")
    return out_path, name


# ---------------- 切片（有 OrcaSlicer 时） ----------------
def slice_plate(pid, spec, plate_id, colour="", printer_idx=None, user=""):
    """按摆好的位置、各槽的耗材切片。需要 OrcaSlicer（没有时抛 SliceError，前台提示用估算）。
    切好后记下每槽克数、冲刷废料、时长，并存成这个产品（规格）的切片文件，生产直接用。"""
    from core import print_files, recipes, slicer
    cfg = load_config()
    p = store.load(pid)
    plan = get_plan(p, spec)
    plate = next((x for x in plan["plates"] if x["id"] == plate_id), None)
    if not plate:
        raise ValueError("没有这一盘（刷新一下）")
    # 整个文件放上盘、颜色来自文件（MakerWorld / 拓竹涂色 3MF）：导出时只能写「每个零件一个槽」，涂色会丢 → 不切，说清楚
    from core import modellib
    for it in plate.get("items") or []:
        if it.get("part") in (None, ""):
            ci = ((modellib._entry(p, it["id"]) or {}).get("info") or {}).get("colors") or {}
            if ci.get("multicolor"):
                raise ValueError("这一盘里有自带颜色的 3MF（涂色 / 多色项目文件），程序切会丢掉文件里的颜色。"
                                 "请在电脑上用 Bambu Studio 打开原文件切片，再上传切片文件；或者把它拆成零件摆盘、每个零件选槽后再切。")
    names = [x.get("name") for x in cfg.get("printers") or []]
    if printer_idx is None:
        printer_idx = names.index(plate["printer"]) if plate["printer"] in names else 0
    path, fname = export_plate(pid, spec, plate_id, colour)
    try:
        cols = colours_for(plan, plate, colour)
        from core import codes
        cmap = codes.color_hex(cfg)
        fils = [{"material": s.get("material") or "PLA", "hex": (cmap.get(cols.get(s["slot"]) or "") or {}).get("hex") or "#FFFFFF"}
                for s in plate["slots"]]
        multi = len({cols.get(s["slot"]) for s in plate["slots"]}) > 1
        rc = recipe_of(p, plate)                # v2.55：这一盘自己的参数（支撑、壁数、填充、热床板、温度、耗材配置）
        pre_warns = slice_warnings(p, plate, rc)
        over = recipes.overrides(rc) or {}
        # 安全：盘上设的喷嘴 / 热床温度是给槽 1 的材料的；别的材料（PLA + PETG / TPU）的槽用它自己配置里的温度
        fo1 = recipes.filament_overrides(rc)
        for f_ in fils:
            f_["overrides"] = fo1 if _same_mat(f_["material"], fils[0]["material"]) else None
        if multi:
            over.update(slicer.MULTI_OVERRIDES)
        import tempfile
        keep = tempfile.NamedTemporaryFile(suffix=".gcode.3mf", delete=False).name
        pname0 = names[printer_idx] if 0 <= printer_idx < len(names) else plate["printer"]
        per_part = any(it.get("ov") for it in plate.get("items") or [])
        res = slicer.orca_slice(cfg, path, printer_idx, fils[0]["material"], overrides=over, keep_to=keep, copies=1, orient=False,
                                arrange=False, filaments=fils if len(fils) > 1 else None,
                                filament_name=None if len(fils) > 1 else (recipes.filament_for(rc, pname0) or None),
                                filament_overrides=fo1, keep_settings=per_part)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    fil = res.get("filaments") or []
    # 切片软件给的每个耗材克数里已经含冲刷 / 擦料塔的料；成本和扣库存会再加 purge_g，所以这里记「净」克数（v2.52 实测修正）
    purge = float(res.get("purge_g") or 0)
    pbs = {int(k): float(v) for k, v in (res.get("purge_by_slot") or {}).items()}
    tot = sum(float(f.get("grams") or 0) for f in fil)
    if purge and not pbs and tot:
        pbs = {i + 1: purge * float(f.get("grams") or 0) / tot for i, f in enumerate(fil)}
    fil = [dict(f, grams=max(0.0, float(f.get("grams") or 0) - pbs.get(i + 1, 0.0))) for i, f in enumerate(fil)]
    sliced = {"filaments": [{"slot": i + 1, "grams": round(float(f.get("grams") or 0), 2)} for i, f in enumerate(fil)] or
              [{"slot": 1, "grams": res.get("grams") or 0}],
              "purge_g": round(float(res.get("purge_g") or 0), 2), "changes": int(res.get("changes") or 0),
              "hours": res.get("hours"), "grams": res.get("grams"), "at": time.time(), "colour": colour}
    p = store.load(pid)
    plans = p.get("print_plans") if isinstance(p.get("print_plans"), dict) else {}
    if (plans.get(spec) or {}).get("follow"):          # 按主模型缩放的规格：结果记在 sliced_by（带摆盘签名）
        plans[spec].setdefault("sliced_by", {})[plate_id] = dict(sliced, sig=plate_sig(plate))
    else:
        plan = plans.get(spec) or plan
        plan.pop("default", None)
        for x in plan["plates"]:
            if x["id"] == plate_id:
                x["sliced"] = sliced
        plans[spec] = plan
    p["print_plans"] = plans
    store.save(p)
    pname = names[printer_idx] if 0 <= printer_idx < len(names) else plate["printer"]
    f = print_files.add(res["kept"], fname.replace(".3mf", ".gcode.3mf"), pid, pname, "", int(plate.get("sets") or 1), "",
                        "按打印方案（摆好的盘）切片" + (f"，{ams_line(usage(p, spec, colour)['colours'])}" if multi else ""), user,
                        fils[0]["material"], res.get("grams"), res.get("hours"), move=True, source="plan", spec=spec,
                        plate_id=plate_id,        # v2.52：记下是哪一盘（几盘的方案生产时每盘用自己的文件）
                        scale=round(float(plan["scale"]), 1) if plan.get("follow") and plan.get("scale") else None)  # v2.53.1：缩放比例
    f = print_files.ensure_params(f)          # v2.53.1：马上读切片参数（机型 / 喷嘴），排单 / 开始打印才认得出这个文件能用
    warns = pre_warns + (res.get("warnings") or [])
    if warns:
        from core import db
        db.audit(user, "打印方案切片：耗材配置和材料不一致等，已自动调整", pid, f"{spec or '主模型'} {plate_id}：" + "；".join(w["zh"] for w in warns))
    return {"sliced": sliced, "file": f, "warnings": warns}


def slice_warnings(p, plate, rc):
    """切片前的安全调整（改 rc）：盘上的温度不是给槽 1 这个材料设的 → 不用（按耗材配置的温度）；
    顶面图案（monotonic）当了填充 → 按 rectilinear 切。返回 [{zh, th}]。"""
    out = []
    if not temps_ok(p, plate):
        prm = plate.get("params") or {}
        mat = _slot1(plate) or p.get("material") or "PLA"
        src = prm.get("temp_material") or p.get("material") or "PLA"
        t = " / ".join(f"{v}°C" for v in (prm.get("nozzle_temp"), prm.get("bed_temp")) if v)
        rc["nozzle_temp"] = rc["bed_temp"] = 0
        out.append({"zh": f"这一盘设的温度（{t}）是给 {src} 的，这一盘打 {mat}：没有用，按 {mat} 耗材配置里的温度切。需要的话在这一盘的参数里重新设温度",
                    "th": f"อุณหภูมิที่ตั้งไว้ ({t}) เป็นของ {src} แต่ถาดนี้พิมพ์ {mat}: ไม่ได้ใช้ ใช้อุณหภูมิจากโปรไฟล์ {mat} แทน ตั้งใหม่ได้ในพารามิเตอร์ของถาดนี้"})
    if rc.get("infill_pattern") in TOP_ONLY:
        out.append(_top_only_warn(rc["infill_pattern"]))
        rc["infill_pattern"] = SAFE_INFILL
    return out


def _top_only_warn(pat):
    return {"zh": f"填充图案「{pat}」是顶面图案，不能做填充：按 {SAFE_INFILL} 切。请在参数里重新选填充图案",
            "th": f"รูปแบบเติม「{pat}」เป็นรูปแบบผิวด้านบน ใช้เป็นไส้ในไม่ได้: สไลซ์เป็น {SAFE_INFILL} แทน กรุณาเลือกรูปแบบเติมใหม่"}


# ---------------- v2.53 规格 × 状态 概览、一键全部切片 ----------------
def _spec_colour(p, spec):
    return next(((v.get("opt1_zh") or "").strip() for v in p.get("variants") or []
                 if (v.get("opt2_zh") or "").strip() == spec and (v.get("opt1_zh") or "").strip()), "")


def plan_key(p, spec):
    """生产时这个规格用哪份方案：规格自己的（保存过 / 按主模型缩放 / 有自己的模型）> 主模型的。
    v2.53.1：和切片文件的规格（specmodel.file_spec）是同一个，生产 / 试打 / 写回都按它。"""
    from core import specmodel
    return specmodel.file_spec(p, spec)


def plan_summary(p, spec="", cfg=None):
    """概览一行（不读模型文件）：{state, key, plates, items, sets, grams, hours, est, sliced, scale, colour}
    state：unsaved 还没保存（自动的一盘）/ saved 已保存（估）/ sliced 每盘都切过 / partial 部分切过 / follow 按主模型缩放 / inherit 跟主模型"""
    cfg = cfg or load_config()
    spec = (spec or "").strip()
    key = plan_key(p, spec)
    plan = get_plan(p, key)
    colour = _spec_colour(p, spec)
    try:
        u = usage(p, key, colour, cfg)
    except (ValueError, OSError, KeyError):
        u = {"grams": 0, "hours": 0, "est": True, "multicolor": False, "purge_g": 0}
    plates = plan.get("plates") or []
    ns = sum(1 for pl in plates if (pl.get("sliced") or {}).get("filaments") or (pl.get("sliced") or {}).get("grams"))
    if spec and key == "":
        state = "inherit"
    elif plan.get("follow"):
        state = "follow"
    elif plan.get("default"):
        state = "unsaved"
    elif plates and ns == len(plates):
        state = "sliced"
    elif ns:
        state = "partial"
    else:
        state = "saved"
    return {"state": state, "key": key, "plates": len(plates), "items": sum(len(pl.get("items") or []) for pl in plates),
            "sets": [int(pl.get("sets") or 1) for pl in plates], "grams": u.get("grams"), "hours": u.get("hours"),
            "purge_g": u.get("purge_g"), "est": bool(u.get("est")), "multicolor": bool(u.get("multicolor")),
            "sliced": ns, "scale": plan.get("scale") if plan.get("follow") else None, "colour": colour,
            "updated_at": plan.get("updated_at")}


SLICE_ALL = {}          # 产品 → 一键全部切片的进度 {total, done, current, results, errors, running}


def slice_all(pid, user="", specs=None):
    """「一键全部切片」：主模型和每个有自己方案的规格，每一盘按顺序切（真的 OrcaSlicer），切完按方案填变体克数 / 时长。
    跟着主模型的规格不用另外切（生产用主模型的），克数按主模型的方案填。进度在 SLICE_ALL[pid]。返回 {results, errors, filled, total}。"""
    from core import bgjobs, slicer, specmodel
    p = store.load(pid)
    todo = []
    keys = [""] + [s for s in specmodel.specs(p) if plan_key(p, s) == s]
    if specs is not None:
        keys = [k for k in keys if k in specs]
    for k in keys:
        plan = get_plan(p, k)
        colour = _spec_colour(p, k) or next(((v.get("opt1_zh") or "").strip() for v in p.get("variants") or []), "")
        for i, pl in enumerate(plan.get("plates") or []):
            if pl.get("items"):
                todo.append((k, pl["id"], i + 1, len(plan["plates"]), colour))
    prog = SLICE_ALL[pid] = {"total": len(todo), "done": 0, "current": "", "results": [], "errors": [], "running": True, "started": time.time()}
    filled = {}
    try:
        for n, (k, plate_id, no, tot, colour) in enumerate(todo):
            prog["current"] = {"spec": k, "no": no, "total": tot}
            bgjobs.note(stage=f"{n + 1}/{len(todo)}")
            try:
                r = slice_plate(pid, k, plate_id, colour, None, user)
                s = r["sliced"]
                prog["results"].append({"spec": k, "plate": plate_id, "no": no, "total": tot, "grams": s.get("grams"),
                                        "hours": s.get("hours"), "file_id": (r.get("file") or {}).get("id")})
            except slicer.SliceError as e:
                prog["errors"].append({"spec": k, "plate": plate_id, "no": no, "error": f"切片没有成功：{e}"})
            except (ValueError, OSError) as e:
                prog["errors"].append({"spec": k, "plate": plate_id, "no": no, "error": str(e)})
            prog["done"] = n + 1
        for k in keys:
            try:
                filled[k] = fill_variants(pid, k, user)
                if k == "":
                    p2 = store.load(pid)          # 跟着主模型的规格也按主模型的方案填
                    for s in specmodel.specs(p2):
                        if plan_key(p2, s) == "":
                            filled[s] = _fill_from(pid, s, "", user)
            except (ValueError, OSError) as e:
                prog["errors"].append({"spec": k, "plate": "", "no": 0, "error": f"填克数没成功：{e}"})
    finally:
        prog["running"] = False
        prog["current"] = ""
    return {"results": prog["results"], "errors": prog["errors"], "filled": filled, "total": prog["total"]}


def _fill_from(pid, spec, key, user=""):
    """规格（没有自己的方案）按 key 的方案填克数 / 时长。"""
    p = store.load(pid)
    n = 0
    for v in p.get("variants") or []:
        if (v.get("opt2_zh") or "").strip() != spec:
            continue
        u = usage(p, key, v.get("opt1_zh") or "")
        if not u["grams"]:
            continue
        v["grams"] = u["grams"]
        if u["hours"]:
            v["hours"] = u["hours"]
        v["grams_src"] = "plan_est" if u["est"] else "plan"
        v["colour_usage"] = u["colours"] if u["multicolor"] else None
        v["purge_g"] = u["purge_g"] if u["multicolor"] else None
        n += 1
    store.save(p)
    return n


# ---------------- v2.55 打印方案编辑器：每盘检查、零件方向卡片、多选操作（切片软件常用工具） ----------------
def plate_checks(p, plate, fps, printers=None):
    """按这一盘的参数 + 每个零件放平后的几何做规则检查（原来「打印方案」面板的检查，改成按盘、按零件）。
    返回 [{level: error/warn/info/ok, zh, th, uids}]。"""
    from core import recipes
    prm = plate.get("params") or {}
    out = []

    def add(level, zh, th, uids=None):
        out.append({"level": level, "zh": zh, "th": th, "uids": list(uids or [])})
    its = [it for it in plate.get("items") or [] if it["uid"] in fps]
    sup = prm.get("supports") or "none"
    brim = bool(prm.get("brim"))
    over = [it["uid"] for it in its if (fps[it["uid"]].get("overhang") or 0) > 2]
    if over and sup == "none":
        add("warn", f"{len(over)} 个零件这个方向有较大的悬空面（超过 45°），不加支撑可能塌：开支撑，或给它换个方向（选中零件看方向卡片）",
            f"{len(over)} ชิ้นมีส่วนยื่นลอยมาก (เกิน 45°) ถ้าไม่มีซัพพอร์ตอาจยุบ: เปิดซัพพอร์ต หรือเปลี่ยนทิศ (เลือกชิ้นเพื่อดูการ์ดทิศทาง)", over)
    if its and sup != "none" and all((fps[it["uid"]].get("overhang") or 0) < 0.3 for it in its):
        add("info", "这一盘的零件几乎没有悬空面，可以试试不要支撑（省料、表面更好）",
            "ชิ้นงานในถาดนี้แทบไม่มีส่วนยื่นลอย ลองไม่ใช้ซัพพอร์ตได้ (ประหยัดวัสดุ ผิวสวยกว่า)")
    small = [it["uid"] for it in its if fps[it["uid"]].get("contact") is not None and fps[it["uid"]]["contact"] < 1]
    if small and not brim:
        add("warn", f"{len(small)} 个零件贴热床的面积不到 1 cm²，容易翘边或打到一半倒：开「帽檐」或换方向",
            f"{len(small)} ชิ้นมีพื้นที่ติดฐานไม่ถึง 1 cm² อาจงอหรือล้มกลางทาง: เปิด「ปีกกันงอ (brim)」หรือเปลี่ยนทิศ", small)
    tall = [it["uid"] for it in its if (fps[it["uid"]].get("tall") or 0) > 3]
    if tall and not brim:
        add("warn", f"{len(tall)} 个零件细高（高度超过底边 3 倍），容易晃动：建议开「帽檐」",
            f"{len(tall)} ชิ้นสูงเรียว (สูงเกิน 3 เท่าของฐาน) อาจโยก: แนะนำเปิด「ปีกกันงอ (brim)」", tall)
    mat = recipes.norm_material(((plate.get("slots") or [{}])[0]).get("material") or p.get("material") or "PLA")
    if mat in ("PETG", "TPU", "ABS", "ASA") and prm.get("bed_type") == "cool":
        add("warn", f"{mat} 不适合低温板，建议用纹理 PEI 板", f"{mat} ไม่เหมาะกับแผ่นอุณหภูมิต่ำ แนะนำแผ่น PEI แบบผิวทราย")
    lh = float(plate.get("layer_height") or 0.2)
    if lh > 0.28:
        add("info", "层高比较大，打印快但表面层纹明显", "ความสูงชั้นค่อนข้างมาก พิมพ์เร็วแต่เห็นลายชั้นชัด")
    if prm.get("infill_pattern") in TOP_ONLY:
        w = _top_only_warn(prm["infill_pattern"])
        add("warn", w["zh"], w["th"])
    if not temps_ok(p, plate):
        add("warn", "这一盘设的温度不是给槽 1 这个材料的（换过材料）：切片时不用，按耗材配置里的温度。需要的话重新设温度",
            "อุณหภูมิที่ตั้งไว้ไม่ใช่ของวัสดุช่อง 1 (เปลี่ยนวัสดุแล้ว): ตอนสไลซ์จะไม่ใช้ ใช้อุณหภูมิจากโปรไฟล์แทน ตั้งใหม่ได้ถ้าต้องการ")
    rng = recipes.TEMP_RANGE.get(mat)
    t = prm.get("nozzle_temp") if temps_ok(p, plate) else 0
    if rng and t and not (rng[0] <= t <= rng[1]):
        add("warn", f"喷嘴温度 {t}°C 不在 {mat} 的常用范围（{rng[0]}–{rng[1]}°C）",
            f"อุณหภูมิหัวฉีด {t}°C ไม่อยู่ในช่วงปกติของ {mat} ({rng[0]}–{rng[1]}°C)")
    pm = next((m for m in printers or printer_models() if m["name"] == plate.get("printer")), {})
    if len({(s.get("colour") or "", s["slot"]) for s in plate.get("slots") or []}) > 1 and pm.get("multicolor") is False:
        add("error", "这台打印机没有 AMS，不能打多色：换有 AMS 的打印机，或只用一个槽",
            "เครื่องนี้ไม่มี AMS พิมพ์หลายสีไม่ได้: เปลี่ยนเครื่องที่มี AMS หรือใช้ช่องเดียว")
    lhs = {float((it.get("ov") or {}).get("layer_height") or lh) for it in plate.get("items") or []}
    if len(lhs) > 1:
        add("info", "这一盘的零件层高不一样（单独参数）：切片软件会按最细的层高切整盘，时间会变长",
            "ชิ้นงานในถาดนี้ความสูงชั้นไม่เท่ากัน (ตั้งค่าแยก): สไลเซอร์จะใช้ชั้นละเอียดสุดทั้งถาด ใช้เวลานานขึ้น")
    if not any(x["level"] in ("error", "warn") for x in out):
        add("ok", "规则检查没有发现问题", "ตรวจตามกฎแล้ว ไม่พบปัญหา")
    return out


_OR = {}


def orient_options(pid, eid, part=None, scale=1.0, p=None):
    """一个零件的方向卡片：六个主要方向 + 推荐的面（模型外侧的大平面），每个带贴平台面积、悬空、尺寸、风险、分数；
    best = 推荐的那个（和模型库的「程序推荐」一样按风险 + 分数）。"""
    p = p or store.load(pid)
    e = modellib._entry(p, eid)
    fp = modellib.path_of(pid, e)
    key = (fp, os.path.getmtime(fp) if fp else 0, part, _sc(scale))
    if key in _OR:
        return _OR[key]
    _f, tris, label = _tris_of(pid, p, eid, part, scale)
    rows = mesh.best_face_analysis(np.asarray(tris, dtype=np.float64))
    mat = p.get("material") or "PLA"
    for r in rows:
        r["risks"] = [{"level": x["level"], "code": x["code"], "vars": x["vars"],
                       "zh": modellib.risk_label(x["code"], x["vars"], "zh"), "th": modellib.risk_label(x["code"], x["vars"], "th")}
                      for x in modellib.orient_risks(r, mat)]
        r["level"] = "bad" if any(x["level"] == "bad" for x in r["risks"]) else "warn" if r["risks"] else "ok"
    best = min(range(len(rows)), key=lambda i: ({"ok": 0, "warn": 1, "bad": 2}[rows[i]["level"]], rows[i]["score"]))
    out = {"label": label, "rows": rows, "best": best}
    if len(_OR) > 100:
        _OR.clear()
    _OR[key] = out
    return out


def _bbox(pl, fps, uids):
    xs, ys = [], []
    for it in pl.get("items") or []:
        if it["uid"] in uids and it["uid"] in fps and it.get("x") is not None:
            pg = _poly(fps[it["uid"]], it["x"], it["y"], it.get("rot") or 0)
            xs += [a for a, _ in pg]
            ys += [b for _, b in pg]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def place_new(pl, bed, fps, gap=2.0):
    """手动摆过的盘里新加的零件（x 是空的）：从左下往右上找一个空地方（不重叠、不压废料口）；找不到放在热床外面（标红）。"""
    W, D = float(bed[0]), float(bed[1])
    ex = exclude_of(pl.get("printer"))
    placed = []
    for o in pl.get("items") or []:
        if o.get("x") is not None and o["uid"] in fps:
            pg = _poly(fps[o["uid"]], o["x"], o["y"], o.get("rot") or 0)
            placed.append((pg, min(a for a, _ in pg), min(b for _, b in pg), max(a for a, _ in pg), max(b for _, b in pg)))
    if ex:
        placed.append(([(ex[0], ex[1]), (ex[2], ex[1]), (ex[2], ex[3]), (ex[0], ex[3])], ex[0], ex[1], ex[2], ex[3]))
    for it in [x for x in pl.get("items") or [] if x.get("x") is None and x["uid"] in fps]:
        f = fps[it["uid"]]
        base = _poly(f, 0, 0, it.get("rot") or 0)
        bx0, by0 = min(a for a, _ in base), min(b for _, b in base)
        bx1, by1 = max(a for a, _ in base), max(b for _, b in base)
        done = None
        y = MARGIN - by0
        while y + by1 <= D - MARGIN + 0.01 and not done:
            x = MARGIN - bx0
            while x + bx1 <= W - MARGIN + 0.01 and not done:
                bb = (x + bx0 - gap, y + by0 - gap, x + bx1 + gap, y + by1 + gap)
                hit = False
                pg = None
                for q in placed:
                    if q[1] > bb[2] or q[3] < bb[0] or q[2] > bb[3] or q[4] < bb[1]:
                        continue
                    pg = pg or [(a + x, b + y) for a, b in base]
                    if _overlap(pg, q[0]) > OVERLAP_TOL or _gap_hit(pg, q[0], gap):
                        hit = True
                        break
                if not hit:
                    done = (x, y)
                x += 5
            y += 5
        if done:
            it["x"], it["y"] = round(done[0], 1), round(done[1], 1)
            pg = [(a + done[0], b + done[1]) for a, b in base]
            placed.append((pg, min(a for a, _ in pg), min(b for _, b in pg), max(a for a, _ in pg), max(b for _, b in pg)))
        else:
            it["x"], it["y"] = round(W + f["w"], 1), round(f["d"] / 2, 1)


def _gap_hit(a, b, gap):
    """两个多边形（凸）离得比 gap 还近：把 a 每边往外推 gap 再测重叠（近似：外框中心放大）。"""
    if gap <= 0:
        return False
    cx = sum(x for x, _ in a) / len(a)
    cy = sum(y for _, y in a) / len(a)
    big = []
    for x, y in a:
        dx, dy = x - cx, y - cy
        ln = math.hypot(dx, dy) or 1
        big.append((x + dx / ln * gap, y + dy / ln * gap))
    return _overlap(big, b) > OVERLAP_TOL


def _new_plate(src, n):
    return {**{k: v for k, v in src.items() if k not in ("items", "sliced", "id", "name")}, "id": f"p{n}", "name": "", "items": [],
            "manual": True, "params": dict(src.get("params") or {}), "slots": [dict(s) for s in src.get("slots") or []]}


def _free_plate_id(plan):
    ids = {pl["id"] for pl in plan["plates"]}
    n = len(plan["plates"]) + 1
    while f"p{n}" in ids:
        n += 1
    return n


def _expand(p, it):
    """拆成零件：合并出来的模型 → 原来的零件（parts_of，数量照算）；多个组件的文件（整个放的）→ 每个组件一件。不能拆返回 None。"""
    e = modellib._entry(p, it["id"])
    lib = {x["id"] for x in p.get("model_lib") or []}
    base = {"slot": it.get("slot") or 1, "x": None, "y": None, "rot": 0, **({"scale": it["scale"]} if it.get("scale") else {}),
            **({"ov": dict(it["ov"])} if it.get("ov") else {})}
    if e.get("parts_of") and it.get("part") in (None, ""):
        out = []
        for d in e["parts_of"]:
            if d.get("id") not in lib:
                continue
            for _ in range(max(1, int(d.get("qty") or 1))):
                out.append(dict(base, uid=_uid(), id=d["id"], part=d.get("part"), orient=d.get("orient") or "bottom"))
        return out or None
    parts = (e.get("info") or {}).get("parts") or []
    if it.get("part") in (None, "") and len(parts) > 1:
        return [dict(base, uid=_uid(), id=e["id"], part=x["index"], orient=x.get("best") or "bottom") for x in parts]
    return None


def cut_item(pid, p, it, z, user=""):
    """按高度 z（零件放平后离热床的毫米数）切成两半，切口补面。两半存进模型库（STL，来源 cut），返回两个新零件（下半在原位置）。"""
    _f, tris, label = _tris_of(pid, p, it["id"], it.get("part"), it.get("scale") or 1)
    t = _oriented(tris, it)
    lo, hi = mesh.cut_z(t, float(z))
    if lo is None or hi is None:
        raise ValueError("这个高度切不开（一边是空的）")
    stem = os.path.splitext(os.path.basename(label.split(" / ")[-1]))[0][:40] or "part"
    cleanup_cuts(pid, p)
    new = []
    for half, tag in ((lo, "A"), (hi, "B")):
        name = modellib._free_name(pid, f"{stem}_cut{round(float(z), 1)}_{tag}.stl")
        path = os.path.join(modellib._dir(pid), name)
        mesh.write_stl(half - half.reshape(-1, 3).min(0), path)
        e = {"id": "m" + uuid.uuid4().hex[:8], "file": name, "dir": "models", "orig_name": name, "bytes": os.path.getsize(path),
             "ext": "stl", "origin": "cut", "variant": "", "added_at": time.time(), "added_by": user,
             "cut_of": {"id": it["id"], "part": it.get("part"), "z": round(float(z), 2), "half": tag, "closed": bool(mesh.is_closed(half))},
             "cut_pending": True}               # 方案还没保存：保存时用上了才算数，没用上的过一阵自动清掉（cleanup_cuts）
        p.setdefault("model_lib", []).append(e)
        e["info"] = modellib.analyze(pid, e)
        new.append(e)
    store.save(p)
    a = {"uid": _uid(), "id": new[0]["id"], "part": None, "orient": "bottom", "slot": it.get("slot") or 1, "x": it.get("x"), "y": it.get("y"),
         "rot": it.get("rot") or 0, **({"ov": dict(it["ov"])} if it.get("ov") else {})}
    b = dict(a, uid=_uid(), id=new[1]["id"], x=None, y=None)
    return [a, b], new


CUT_TTL = 6 * 3600       # 切开了但方案没保存的两半，留这么久（别的窗口可能还在编辑）再清掉


def _lib_refs(p):
    """模型库里被用到的条目：所有方案的零件、展示用的零件、当前 3D 模型、规格指定的模型、合并模型的来源。"""
    refs = {(p.get("model") or {}).get("lib_id")}
    for plan in (p.get("print_plans") or {}).values() if isinstance(p.get("print_plans"), dict) else []:
        for pl in (plan or {}).get("plates") or [] if isinstance(plan, dict) else []:
            refs.update(it.get("id") for it in pl.get("items") or [])
    refs.update(v.get("model_lib_id") for v in p.get("variants") or [])
    d = p.get("display") if isinstance(p.get("display"), dict) else {}      # 展示（商品页的组装）用到的零件也算
    refs.add(d.get("source"))
    for sd in (d.get("specs") or {}).values() if isinstance(d.get("specs"), dict) else []:
        for it in (sd or {}).get("items") or [] if isinstance(sd, dict) else []:
            if isinstance(it, dict):
                refs.add(it.get("id"))
    for e in p.get("model_lib") or []:
        refs.update(d.get("id") for d in e.get("parts_of") or [])
    refs.discard(None)
    return refs


def cleanup_cuts(pid, p, ttl=CUT_TTL, now=None):
    """切割留下的文件：方案用上了 → 去掉「待保存」标记；没用上、超过 ttl 秒 → 从模型库删掉（文件挪进 model_history）。
    只改 p（调用方保存）。返回删掉的条目 id。"""
    pend = [e for e in p.get("model_lib") or [] if e.get("cut_pending")]
    if not pend:
        return []
    refs = _lib_refs(p)
    now = time.time() if now is None else now
    gone = []
    for e in pend:
        if e["id"] in refs:
            e.pop("cut_pending", None)
        elif now - float(e.get("added_at") or 0) >= ttl:
            gone.append(e["id"])
            fp = modellib.path_of(pid, e)
            if fp:
                trash = os.path.join(store.product_dir(pid), "model_history")
                os.makedirs(trash, exist_ok=True)
                try:
                    os.replace(fp, os.path.join(trash, f"{time.strftime('%Y%m%d_%H%M%S')}__{os.path.basename(fp)}"))
                except OSError:
                    pass
            th = (e.get("info") or {}).get("thumb")
            if th and os.path.exists(os.path.join(modellib._dir(pid), th)):
                try:
                    os.remove(os.path.join(modellib._dir(pid), th))
                except OSError:
                    pass
    if gone:
        p["model_lib"] = [e for e in p.get("model_lib") or [] if e["id"] not in gone]
    return gone


OPS = ("move", "rotate", "scale", "mirror", "duplicate", "delete", "slot", "orient", "auto_orient", "align", "distribute",
       "group", "ungroup", "split", "to_plate", "overrides", "qty", "cut", "arrange")


def apply_op(pid, spec, data, op, user=""):
    """多选操作（不保存，返回改好的方案给前台，前台再「保存打印方案」）。op = {op, plate, uids, …}：
    move（dx/dy 或 x/y）、rotate（angle，按选中的中心转）、scale（pct）、mirror（axis x/y）、duplicate（n）、delete、slot（slot）、
    orient（orient 或 face）、auto_orient、align（mode left/right/top/bottom/cx/cy）、distribute（axis）、group / ungroup、
    split（拆成零件）、to_plate（target 盘号 / "new"）、overrides（ov：layer_height / infill_pct / walls，空 = 跟着盘）、
    qty（id、part、qty：整个方案里这个零件有几个）、cut（z）、arrange。
    返回 {plan, footprints, checks, plate_checks, sel: [uid], plate, missed, cut?}"""
    import copy
    p = store.load(pid)
    modellib._sync(p)
    kind = (op or {}).get("op")
    if kind not in OPS:
        raise ValueError(f"不认识的操作「{kind}」")
    plan = _migrate(p, spec, clean_plan(p, data))
    plan["schemes"] = (data or {}).get("schemes") or plan.get("schemes") or {}
    for k in ("follow", "scale", "default"):
        if (data or {}).get(k) is not None:
            plan[k] = data[k]
    pl = next((x for x in plan["plates"] if x["id"] == (op or {}).get("plate")), None) or plan["plates"][0]
    uids = [u for u in (op.get("uids") or []) if any(it["uid"] == u for it in pl["items"])]
    sel = [it for it in pl["items"] if it["uid"] in uids]
    if kind not in ("qty", "arrange") and not sel:
        raise ValueError("先选中零件（点一下零件；Ctrl / Shift 多选，或拖一个框）")
    # 合并成组的零件一起动
    groups = {it.get("group") for it in sel if it.get("group")}
    if groups and kind in ("move", "rotate", "mirror", "delete", "to_plate", "duplicate", "align", "distribute"):
        sel = [it for it in pl["items"] if it["uid"] in uids or (it.get("group") and it["group"] in groups)]
        uids = [it["uid"] for it in sel]
    fps = fps_for(pid, p, pl)
    bed = bed_of(pl["printer"])
    new_sel = list(uids)
    missed = 0
    extra = {}

    def refresh():
        nonlocal fps
        fps = fps_for(pid, p, pl)
    if kind == "move":
        if op.get("x") is not None or op.get("y") is not None:
            bb = _bbox(pl, fps, set(uids))
            cx, cy = ((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2) if bb else (0, 0)
            dx = float(op["x"]) - cx if op.get("x") is not None else 0.0
            dy = float(op["y"]) - cy if op.get("y") is not None else 0.0
        else:
            dx, dy = float(op.get("dx") or 0), float(op.get("dy") or 0)
        for it in sel:
            if it.get("x") is not None:
                it["x"], it["y"] = round(it["x"] + dx, 1), round(it["y"] + dy, 1)
        pl["manual"] = True
    elif kind == "rotate":
        a = float(op.get("angle") or 0)
        bb = _bbox(pl, fps, set(uids))
        if bb and len(sel) > 1:
            cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            for it in sel:
                if it.get("x") is not None:
                    x, y = it["x"] - cx, it["y"] - cy
                    it["x"], it["y"] = round(cx + x * ca - y * sa, 1), round(cy + x * sa + y * ca, 1)
        for it in sel:
            it["rot"] = round(((it.get("rot") or 0) + a) % 360, 1)
        pl["manual"] = True
    elif kind == "scale":
        pct = float(op.get("pct") or 100)
        if not 1 <= pct <= 2000:
            raise ValueError("缩放要在 1% 到 2000% 之间")
        for it in sel:
            it["scale"] = round(pct / 100.0, 4)
            if it["scale"] == 1.0:
                it.pop("scale", None)
        refresh()
    elif kind == "mirror":
        ax = "x" if op.get("axis") != "y" else "y"
        bb = _bbox(pl, fps, set(uids))
        for it in sel:
            mx, my = _mir(it)
            if ax == "x":
                mx = not mx
            else:
                my = not my
            m = ("x" if mx else "") + ("y" if my else "")
            if m:
                it["mirror"] = m
            else:
                it.pop("mirror", None)
            it["rot"] = round((-(it.get("rot") or 0)) % 360, 1)          # 整体沿世界 X / Y 镜像 = 局部镜像 + 角度取反
            if bb and len(sel) > 1 and it.get("x") is not None:
                if ax == "x":
                    it["x"] = round(bb[0] + bb[2] - it["x"], 1)
                else:
                    it["y"] = round(bb[1] + bb[3] - it["y"], 1)
        refresh()
    elif kind == "duplicate":
        n = max(1, min(100, int(op.get("n") or 1)))
        if len(pl["items"]) + n * len(sel) > 200:
            raise ValueError("一盘最多 200 个零件")
        new_sel = []
        gmap = {}
        for _ in range(n):
            for it in sel:
                c = copy.deepcopy(it)
                c["uid"], c["x"], c["y"] = _uid(), None, None
                if it.get("group"):
                    c["group"] = gmap.setdefault((it["group"], _), "g" + uuid.uuid4().hex[:6])
                pl["items"].append(c)
                new_sel.append(c["uid"])
        refresh()
        if pl.get("manual"):
            place_new(pl, bed, fps)
        else:
            missed = auto_arrange(pl, bed, fps)
    elif kind == "delete":
        pl["items"] = [it for it in pl["items"] if it["uid"] not in set(uids)]
        new_sel = []
    elif kind == "slot":
        n = int(op.get("slot") or 1)
        if not any(s["slot"] == n for s in pl["slots"]):
            raise ValueError("这一盘没有这个槽")
        for it in sel:
            it["slot"] = n
    elif kind in ("orient", "auto_orient"):
        for it in sel:
            if kind == "auto_orient":
                o = orient_options(pid, it["id"], it.get("part"), it.get("scale") or 1, p)
                r = o["rows"][o["best"]]
                face = r.get("face")
                orient = r["key"] if r["key"] in mesh.ORIENT_ZH else "bottom"
            else:
                face = op.get("face") if isinstance(op.get("face"), (list, tuple)) else None
                orient = op.get("orient") if op.get("orient") in mesh.ORIENT_ZH else "bottom"
            it["orient"] = orient
            if face:
                it["face"] = [float(x) for x in face]
            else:
                it.pop("face", None)
        refresh()
        if pl.get("manual"):
            _resolve(pl, bed, fps, set(uids))
    elif kind == "align":
        mode = op.get("mode") or "left"
        bb = _bbox(pl, fps, set(uids))
        for it in sel:
            if it.get("x") is None or not bb:
                continue
            ib = _bbox(pl, fps, {it["uid"]})
            if mode == "left":
                it["x"] = round(it["x"] + bb[0] - ib[0], 1)
            elif mode == "right":
                it["x"] = round(it["x"] + bb[2] - ib[2], 1)
            elif mode == "bottom":
                it["y"] = round(it["y"] + bb[1] - ib[1], 1)
            elif mode == "top":
                it["y"] = round(it["y"] + bb[3] - ib[3], 1)
            elif mode == "cx":
                it["x"] = round(it["x"] + (bb[0] + bb[2]) / 2 - (ib[0] + ib[2]) / 2, 1)
            elif mode == "cy":
                it["y"] = round(it["y"] + (bb[1] + bb[3]) / 2 - (ib[1] + ib[3]) / 2, 1)
        pl["manual"] = True
    elif kind == "distribute":
        ax = 0 if op.get("axis") != "y" else 1
        its = [it for it in sel if it.get("x") is not None]
        if len(its) >= 3:
            boxes = {it["uid"]: _bbox(pl, fps, {it["uid"]}) for it in its}
            its.sort(key=lambda it: boxes[it["uid"]][ax])
            lo_, hi_ = boxes[its[0]["uid"]][ax], boxes[its[-1]["uid"]][ax + 2]
            tot = sum(boxes[it["uid"]][ax + 2] - boxes[it["uid"]][ax] for it in its)
            gap = (hi_ - lo_ - tot) / (len(its) - 1)
            cur = lo_
            for it in its:
                b = boxes[it["uid"]]
                k = "x" if ax == 0 else "y"
                it[k] = round(it[k] + cur - b[ax], 1)
                cur += (b[ax + 2] - b[ax]) + gap
        pl["manual"] = True
    elif kind == "group":
        g = "g" + uuid.uuid4().hex[:6]
        for it in sel:
            it["group"] = g
    elif kind == "ungroup":
        for it in sel:
            it.pop("group", None)
    elif kind == "split":
        new_sel, out = [], []
        n_split = 0
        for it in pl["items"]:
            if it["uid"] in set(uids):
                ex = _expand(p, it)
                if ex:
                    out += ex
                    new_sel += [x["uid"] for x in ex]
                    n_split += 1
                    continue
            out.append(it)
        if not n_split:
            raise ValueError("选中的零件不能再拆（拆成零件只对合并出来的模型、或有多个组件的文件有用）")
        if len(out) > 200:
            raise ValueError("一盘最多 200 个零件")
        pl["items"] = out
        refresh()
        if pl.get("manual"):
            place_new(pl, bed, fps)
        else:
            missed = auto_arrange(pl, bed, fps)
    elif kind == "to_plate":
        tgt = op.get("target")
        if tgt == "new" or not any(x["id"] == tgt for x in plan["plates"]):
            if len(plan["plates"]) >= 20:
                raise ValueError("最多 20 盘")
            dst = _new_plate(pl, _free_plate_id(plan))
            plan["plates"].append(dst)
        else:
            dst = next(x for x in plan["plates"] if x["id"] == tgt)
        if dst is pl:
            raise ValueError("已经在这一盘了")
        moved = [it for it in pl["items"] if it["uid"] in set(uids)]
        pl["items"] = [it for it in pl["items"] if it["uid"] not in set(uids)]
        for it in moved:
            it["x"] = it["y"] = None
            if not any(s["slot"] == it.get("slot") for s in dst["slots"]):
                it["slot"] = 1
        dst["items"] += moved
        dfps = fps_for(pid, p, dst)
        if dst.get("manual") and len(dst["items"]) > len(moved):
            place_new(dst, bed_of(dst["printer"]), dfps)
        else:
            missed = auto_arrange(dst, bed_of(dst["printer"]), dfps)
        dst["manual"] = True
        extra["plate"] = dst["id"]
    elif kind == "overrides":
        ov = op.get("ov") or {}
        for it in sel:
            cur = dict(it.get("ov") or {})
            for k in OV_RANGE:
                if k in ov:
                    if ov[k] in (None, ""):
                        cur.pop(k, None)
                    else:
                        cur[k] = ov[k]
            it["ov"] = cur
            ex = _item_extra(it)
            if ex.get("ov"):
                it["ov"] = ex["ov"]
            else:
                it.pop("ov", None)
    elif kind == "qty":
        eid, part, want = op.get("id"), op.get("part"), max(0, min(200, int(op.get("qty") or 0)))
        part = None if part in (None, "") else int(part)
        modellib._entry(p, eid)
        mine = [(x, it) for x in plan["plates"] for it in x["items"] if it["id"] == eid and it.get("part") == part]
        have = len(mine)
        if want < have:
            drop = {it["uid"] for _x, it in mine[want:]}
            for x in plan["plates"]:
                x["items"] = [it for it in x["items"] if it["uid"] not in drop]
            new_sel = []
        elif want > have:
            tgt = mine[-1][0] if mine else pl
            tmpl = copy.deepcopy(mine[-1][1]) if mine else {"id": eid, "part": part, "orient": _best_orient(p, eid, part), "slot": 1, "rot": 0}
            new_sel = []
            for _ in range(want - have):
                c = dict(copy.deepcopy(tmpl), uid=_uid(), x=None, y=None)
                c.pop("group", None)
                tgt["items"].append(c)
                new_sel.append(c["uid"])
            if len(tgt["items"]) > 200:
                raise ValueError("一盘最多 200 个零件")
            tf = fps_for(pid, p, tgt)
            if tgt.get("manual"):
                place_new(tgt, bed_of(tgt["printer"]), tf)
            else:
                missed = auto_arrange(tgt, bed_of(tgt["printer"]), tf)
            extra["plate"] = tgt["id"]
    elif kind == "cut":
        if len(sel) != 1:
            raise ValueError("切割一次选一个零件")
        it = sel[0]
        try:
            z = float(op.get("z"))
        except (TypeError, ValueError):
            raise ValueError("切割高度要填数字（离热床多少毫米）") from None
        h = float((fps.get(it["uid"]) or {}).get("h") or 0)
        if not math.isfinite(z) or z <= 0 or (h and z >= h):
            raise ValueError(f"切割高度要在 0 到 {h:.1f} 毫米之间（这个零件放平后高 {h:.1f} 毫米）")
        two, ents = cut_item(pid, p, it, z, user)
        i = pl["items"].index(it)
        pl["items"][i:i + 1] = two
        refresh()
        place_new(pl, bed, fps)
        pl["manual"] = True
        new_sel = [x["uid"] for x in two]
        extra["cut"] = [{"id": e["id"], "name": e["orig_name"], "closed": e["cut_of"]["closed"],
                         "h": ((e.get("info") or {}).get("size") or [0, 0, 0])[2]} for e in ents]
    elif kind == "arrange":
        missed = auto_arrange(pl, bed, fps)
        pl["manual"] = True
    return _op_result(pid, p, plan, new_sel, missed, extra, pl)


def _best_orient(p, eid, part):
    e = modellib._entry(p, eid)
    info = e.get("info") or {}
    if part is not None:
        info = next((x for x in info.get("parts") or [] if x.get("index") == part), None) or {}
    return info.get("best") or "bottom"


def _resolve(pl, bed, fps, uids):
    """改了方向 / 大小后和别的零件重叠了：把这几个挪到空地方。"""
    ck = check_plate(pl, bed, fps)["items"]
    bad = [it for it in pl["items"] if it["uid"] in uids and (ck.get(it["uid"]) or {}).get("overlap")]
    for it in bad:
        it["x"] = it["y"] = None
    if bad:
        place_new(pl, bed, fps)


def _op_result(pid, p, plan, sel, missed, extra, pl):
    cfg = load_config()
    pms = printer_models(cfg)
    fps, checks, pchecks = {}, {}, {}
    for x in plan["plates"]:
        f = fps_for(pid, p, x)
        fps.update(f)
        if any(it.get("x") is None for it in x["items"]):
            if x.get("manual"):
                place_new(x, bed_of(x["printer"], cfg), f)
            else:
                auto_arrange(x, bed_of(x["printer"], cfg), f)
        checks[x["id"]] = check_plate(x, bed_of(x["printer"], cfg), f)
        pchecks[x["id"]] = plate_checks(p, x, f, pms)
    return {"plan": plan, "footprints": fps, "checks": checks, "plate_checks": pchecks, "sel": sel,
            "plate": extra.get("plate") or pl["id"], "missed": missed, **{k: v for k, v in extra.items() if k != "plate"}}
