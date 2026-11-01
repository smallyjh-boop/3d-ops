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


def footprint(pid, eid, part=None, orient="bottom", p=None, scale=1.0):
    """零件按摆放方向放平后的俯视轮廓（凸包，中心在外框中心）。返回 {hull, w, d, h, label}。scale：按主模型缩放的规格（v2.53）。"""
    p = p or store.load(pid)
    orient = orient if orient in mesh.ORIENT_ZH else "bottom"
    e = modellib._entry(p, eid)
    fp = modellib.path_of(pid, e)
    key = (fp, os.path.getmtime(fp) if fp else 0, part, orient, _sc(scale))
    if key in _FP:
        return _FP[key]
    fp, tris, label = _tris_of(pid, p, eid, part, scale)
    t = mesh.rotate(np.asarray(tris, dtype=np.float64), orient)
    v = t.reshape(-1, 3)
    if len(v) > 300_000:
        v = v[:: max(1, len(v) // 300_000)]
    mn, mx = v.min(0), v.max(0)
    c = (mn[:2] + mx[:2]) / 2
    hull = _simplify(_hull(v[:, :2] - c))
    out = {"hull": [[round(a, 1), round(b, 1)] for a, b in hull], "w": round(float(mx[0] - mn[0]), 1),
           "d": round(float(mx[1] - mn[1]), 1), "h": round(float(mx[2] - mn[2]), 1), "label": label}
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
              "size_mm": [(fps.get(it["uid"]) or {}).get(k) for k in ("w", "d", "h")]} for it in plate.get("items") or []]
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
        return default_plan(p, spec)
    return plan


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
        if got and got.get("sig") == _sig(pl):
            pl["sliced"] = {k2: v for k2, v in got.items() if k2 != "sig"}
    base.update(follow=True, scale=sp.get("scale"), base_default=bool(base.get("default")))
    base.pop("default", None)
    base.pop("updated_at", None)
    if sp.get("updated_at"):
        base["updated_at"] = sp["updated_at"]
    return base


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
                          **({"scale": round(_sc(it["scale"]), 4)} if _sc(it.get("scale")) != 1.0 else {})})
        if len({it["uid"] for it in items}) != len(items):
            for it in items:
                it["uid"] = _uid()
        printer = pl.get("printer") if pl.get("printer") in names else (sorted(names)[0] if names else "Bambu Lab P1S")
        plates.append({"id": str(pl.get("id") or f"p{i + 1}")[:12], "name": str(pl.get("name") or "")[:40], "printer": printer,
                       "layer_height": round(_num(pl.get("layer_height"), 0.04, 0.6, 0.2), 2), "sets": int(_num(pl.get("sets"), 1, 200, 1)),
                       "slots": slots, "items": items, "manual": bool(pl.get("manual")),
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
        out[it["uid"]] = footprint(pid, it["id"], it.get("part"), it.get("orient"), p, it.get("scale") or 1)
    return out


def save_plan(pid, spec, data, user=""):
    """保存方案。手动摆过的盘要求不重叠、不超出热床（返回检查结果，有问题不保存）。"""
    p = store.load(pid)
    modellib._sync(p)
    spec = (spec or "").strip()
    from core import specmodel
    if spec and spec not in specmodel.specs(p):
        raise ValueError(f"这个产品没有规格「{spec}」")
    plan = clean_plan(p, data)
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
        old = next((x for x in (get_plan(p, spec).get("plates") or []) if x.get("id") == pl["id"]), None)
        if old and old.get("sliced") and _sig(old) != _sig(pl):
            pl.pop("sliced", None)                  # 改了摆盘 / 颜色：以前的切片结果不能用了
    plan["updated_at"], plan["updated_by"] = time.time(), user
    if not isinstance(p.get("print_plans"), dict):
        p["print_plans"] = {}
    p["print_plans"][spec] = plan
    _refresh_variants(p, spec, plan)
    store.save(p)
    return {"plan": plan, "checks": checks}


def _sig(pl):
    return repr([(it["id"], it.get("part"), it.get("orient"), it.get("slot"), it.get("x"), it.get("y"), it.get("rot"), _sc(it.get("scale")))
                 for it in pl.get("items") or []]
                + [(s["slot"], s.get("material")) for s in pl.get("slots") or []] + [pl.get("printer"), pl.get("layer_height")])


def plate_selection(plate):
    """给 modellib（合并 / 预览摆盘 / 导出）用的选择：每个零件一件，带位置。"""
    return [{"id": it["id"], "part": it.get("part"), "qty": 1, "orient": it.get("orient") or "bottom",
             **({"scale": _sc(it.get("scale"))} if _sc(it.get("scale")) != 1.0 else {}),
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
        saved.setdefault("sliced_by", {})[plate_id] = dict(sl, sig=_sig(plate))
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
    """[(名字, 三角面（原点在零件外框底面中心）, (x, y, 0), 槽)]：按摆好的位置。"""
    p = p or store.load(pid)
    out = []
    for it in plate.get("items") or []:
        _fp, tris, label = _tris_of(pid, p, it["id"], it.get("part"), it.get("scale") or 1)
        t = mesh.rotate(np.asarray(tris, dtype=np.float64), it.get("orient") or "bottom")
        v = t.reshape(-1, 3)
        mn, mx = v.min(0), v.max(0)
        t = t - np.array([(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]])
        a = math.radians(float(it.get("rot") or 0))
        if a:
            rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
            t = (t.reshape(-1, 3) @ rz.T).reshape(-1, 3, 3)
        out.append((label, t, (float(it.get("x") or 0), float(it.get("y") or 0), 0.0), int(it.get("slot") or 1)))
    return out


def write_plate_3mf(path, objects, slots=None):
    """写一个最简单的 3MF：每个零件一个对象，build 里按位置摆；Metadata/model_settings.config 写每个零件用哪个耗材槽
    （拓竹 Studio / OrcaSlicer 打开就是分好色的）。"""
    import zipfile
    from xml.sax.saxutils import quoteattr
    res, build, settings = [], [], []
    for i, (name, tris, pos, slot) in enumerate(objects, start=1):
        v = np.asarray(tris, dtype=np.float64).reshape(-1, 3)
        uniq, inv = np.unique(np.round(v, 4), axis=0, return_inverse=True)
        inv = inv.reshape(-1, 3)
        vs = "".join(f'<vertex x="{a:.4f}" y="{b:.4f}" z="{c:.4f}"/>' for a, b, c in uniq)
        ts = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in inv if a != b and b != c and a != c)
        res.append(f'<object id="{i}" name={quoteattr(name)} type="model"><mesh><vertices>{vs}</vertices><triangles>{ts}</triangles></mesh></object>')
        build.append(f'<item objectid="{i}" transform="1 0 0 0 1 0 0 0 1 {pos[0]:.3f} {pos[1]:.3f} {pos[2]:.3f}" printable="1"/>')
        settings.append(f'<object id="{i}"><metadata key="name" value={quoteattr(name)}/><metadata key="extruder" value="{int(slot)}"/>'
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
        rc = dict(recipes.get(p))
        rc["layer_height"] = plate.get("layer_height") or rc.get("layer_height")
        over = recipes.overrides(rc) or {}
        if multi:
            over.update(slicer.MULTI_OVERRIDES)
        import tempfile
        keep = tempfile.NamedTemporaryFile(suffix=".gcode.3mf", delete=False).name
        res = slicer.orca_slice(cfg, path, printer_idx, fils[0]["material"], overrides=over, keep_to=keep, copies=1, orient=False,
                                arrange=False, filaments=fils if len(fils) > 1 else None)
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
        plans[spec].setdefault("sliced_by", {})[plate_id] = dict(sliced, sig=_sig(plate))
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
    return {"sliced": sliced, "file": f}


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
