"""展示模型（v2.52，给商品页用）：多零件模型「组装好」的样子 —— 每个零件的位置和旋转（像商品照片那样拼起来）。

和打印方案（printplan.py，零件平放在热床上）分开：这里只管好看，3D 预览、颜色效果、商品图都用这个姿势。

数据（产品资料 product["display"]）：
  {"source": 模型库文件 id（零件从这个文件读，默认 = 主模型）,
   "parts": [{"index": 组件序号, "pos": [x, y, z], "rot": [rx, ry, rz]（度，XYZ 顺序）, "colour": 零件颜色（空 = 跟着款式颜色）, "hidden": bool}],
   "updated_at", "updated_by", "ai": 上次是不是 AI 摆的}
  坐标：Z 朝上，毫米；pos = 零件外框中心的位置。默认 = 零件在文件里原来的位置、不转。

「AI 按图片组装」：把商品主图 + 每个零件几个角度的渲染图（浏览器画好传上来）拼成一张对照图，连同零件外框尺寸交给 ERP 的 AI，
让它给每个零件的位置 / 旋转，当初稿；结果仅供参考，员工再用鼠标调整。DeepSeek 不能看图（会提示换能看图的 AI）。
"""
import base64
import io
import json
import math
import os
import time

import numpy as np

from core import modellib, store
from core.config import load_config


def _source(p, src=None):
    lib = {e["id"]: e for e in p.get("model_lib") or [] if isinstance(e, dict) and e.get("id")}
    sid = src or (p.get("display") or {}).get("source") or (p.get("model") or {}).get("lib_id")
    e = lib.get(sid)
    if not e:
        e = next((x for x in lib.values() if (x.get("info") or {}).get("ok")), None)
    if not e:
        raise ValueError("还没有模型文件（先上传 3D 模型）")
    fp = modellib.path_of(p["id"], e)
    if not fp or os.path.splitext(fp)[1].lower() not in modellib.MODEL_EXT:
        raise ValueError("这个文件不能组装（要 STL、3MF 或 OBJ）")
    return e, fp


def parts_info(pid, src=None):
    """零件列表：序号、名字、外框尺寸、原来的中心。"""
    p = store.load(pid)
    modellib._sync(p)
    e, fp = _source(p, src)
    out = []
    for i, (name, tris) in enumerate(modellib.load_parts(fp)):
        v = np.asarray(tris, dtype=np.float64).reshape(-1, 3)
        mn, mx = v.min(0), v.max(0)
        out.append({"index": i, "name": name, "size": [round(float(x), 1) for x in (mx - mn)],
                    "center": [round(float(x), 2) for x in (mn + mx) / 2], "triangles": int(len(tris))})
    return e, out


def part_tris(pid, index, src=None, max_tris=150_000):
    """一个零件的三角面（原来的坐标，给浏览器显示），太多时隔几个取一个。"""
    p = store.load(pid)
    _e, fp = _source(p, src)
    parts = modellib.load_parts(fp)
    i = int(index)
    if not 0 <= i < len(parts):
        raise ValueError("没有这个零件")
    t = np.asarray(parts[i][1], dtype=np.float32)
    if len(t) > max_tris:
        t = t[:: int(math.ceil(len(t) / max_tris))]
    return t


def get(pid):
    p = store.load(pid)
    e, parts = parts_info(pid)
    d = p.get("display") if isinstance(p.get("display"), dict) else {}
    if d.get("source") and d["source"] != e["id"]:
        d = {}
    pose = {x["index"]: x for x in d.get("parts") or []}
    rows = []
    for x in parts:
        q = pose.get(x["index"]) or {}
        rows.append({**x, "pos": q.get("pos") or x["center"], "rot": q.get("rot") or [0, 0, 0], "colour": q.get("colour") or "",
                     "hidden": bool(q.get("hidden")), "saved": bool(q)})
    return {"source": e["id"], "source_name": e.get("orig_name") or e["file"], "parts": rows,
            "updated_at": d.get("updated_at"), "updated_by": d.get("updated_by"), "ai": bool(d.get("ai")),
            "has_pose": bool(d.get("parts"))}


def _vec(v, n=3, lim=5000):
    out = []
    for x in (v or [])[:n]:
        try:
            f = float(x)
        except (TypeError, ValueError):
            f = 0.0
        if not math.isfinite(f):
            f = 0.0
        out.append(round(max(-lim, min(lim, f)), 3))
    return out + [0.0] * (n - len(out))


def save(pid, data, user=""):
    """保存组装姿势。data = {"source", "parts": [{index, pos, rot, slot, hidden}], "ai": bool}"""
    p = store.load(pid)
    e, parts = parts_info(pid, data.get("source"))
    n = len(parts)
    rows = []
    for x in data.get("parts") or []:
        try:
            i = int(x.get("index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= i < n:
            continue
        rows.append({"index": i, "pos": _vec(x.get("pos")), "rot": [((r + 180) % 360) - 180 for r in _vec(x.get("rot"), lim=100000)],
                     **({"colour": str(x["colour"])[:30]} if x.get("colour") else {}), **({"hidden": True} if x.get("hidden") else {})})
    p["display"] = {"source": e["id"], "parts": rows, "updated_at": time.time(), "updated_by": user, "ai": bool(data.get("ai"))}
    store.save(p)
    return get(pid)


def reset(pid, user=""):
    p = store.load(pid)
    p["display"] = None
    store.save(p)
    return get(pid)


def _rot_matrix(rx, ry, rz):
    """XYZ 顺序的欧拉角（度）→ 旋转矩阵（和 three.js 的 Euler 'XYZ' 一样）。"""
    a, b, c = (math.radians(float(x or 0)) for x in (rx, ry, rz))
    X = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    Y = np.array([[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]])
    Z = np.array([[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]])
    return X @ Y @ Z


def assembled_tris(pid):
    """按组装姿势拼好的整个模型（三角面），给 3D 预览 / 商品图用；没有保存过姿势返回 None。"""
    p = store.load(pid)
    d = p.get("display") if isinstance(p.get("display"), dict) else None
    if not d or not d.get("parts"):
        return None
    _e, fp = _source(p, d.get("source"))
    pose = {x["index"]: x for x in d["parts"]}
    out = []
    for i, (_n, tris) in enumerate(modellib.load_parts(fp)):
        q = pose.get(i)
        t = np.asarray(tris, dtype=np.float64)
        if q and q.get("hidden"):
            continue
        if q:
            v = t.reshape(-1, 3)
            c = (v.min(0) + v.max(0)) / 2
            m = _rot_matrix(*q.get("rot") or [0, 0, 0])
            t = ((v - c) @ m.T + np.array(q.get("pos") or c)).reshape(-1, 3, 3)
        out.append(t)
    if not out:
        return None
    t = np.concatenate(out)
    v = t.reshape(-1, 3)
    mn, mx = v.min(0), v.max(0)
    return t - np.array([(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]])


# ---------------- AI 按图片组装 ----------------
AI_SYSTEM = """你是 3D 打印产品的装配工程师。用户有一个分成几个零件打印的产品，要在网店里展示「组装好」的样子。
你会看到一张对照图：左边（或第一格）是商品主图（组装好的实物照片），后面每一格是一个零件从几个角度的渲染图（格子上写着零件编号）。
再给你每个零件的外框尺寸（毫米）。请判断每个零件在组装好的产品里的位置和朝向。
坐标系：Z 朝上，单位毫米，原点在组装好的整个产品底面中心；pos = 零件外框中心的位置；rot = 绕 X、Y、Z 轴依次旋转的角度（度，XYZ 顺序），
零件的「原始朝向」就是渲染图里的样子。零件之间要贴合，不要互相穿插、不要悬空。只输出 JSON。"""


def _sheet(product_img, renders):
    """拼一张对照图：商品主图 + 每个零件的几张渲染图（每行一个零件，左边写编号）。返回 JPEG base64。"""
    from PIL import Image, ImageDraw
    cell = 220
    rows = []
    for idx in sorted(renders, key=lambda k: int(k)):
        ims = []
        for u in renders[idx][:4]:
            try:
                raw = base64.b64decode(u.split(",", 1)[1] if "," in u else u)
                ims.append(Image.open(io.BytesIO(raw)).convert("RGB"))
            except Exception:  # noqa: BLE001
                continue
        if ims:
            rows.append((int(idx), ims))
    if not rows:
        raise ValueError("没有零件的渲染图")
    cols = max(len(r[1]) for r in rows)
    left = 0
    prod = None
    if product_img is not None:
        prod = product_img.convert("RGB")
        prod.thumbnail((cell * 2, cell * 2))
        left = cell * 2 + 20
    W = left + 60 + cols * cell
    H = max(len(rows) * cell, prod.size[1] if prod else 0) + 30
    sheet = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    if prod:
        sheet.paste(prod, (0, 30))
        d.text((4, 6), "PRODUCT PHOTO", fill=(200, 0, 0))
    for r, (idx, ims) in enumerate(rows):
        y = 30 + r * cell
        d.text((left + 4, y + cell // 2), f"PART {idx}", fill=(0, 0, 200))
        for c, im in enumerate(ims):
            im = im.copy()
            im.thumbnail((cell - 8, cell - 8))
            sheet.paste(im, (left + 60 + c * cell + 4, y + 4))
    if W > 1800:
        sheet.thumbnail((1800, 1800))
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _main_image(p):
    """商品主图（第 1 张；处理过的在 out/，原图在 raw/）。"""
    from PIL import Image
    for x in p.get("images") or []:
        if not isinstance(x, dict):
            continue
        for sub, key in (("out", "file"), ("raw", "raw"), ("raw", "file")):
            name = x.get(key)
            fp = os.path.join(store.product_dir(p["id"]), sub, os.path.basename(str(name))) if name else ""
            if fp and os.path.exists(fp):
                try:
                    return Image.open(fp)
                except Exception:  # noqa: BLE001
                    return None
        break
    return None


def ai_assemble(pid, renders, user="", product_image=None):
    """renders = {零件序号: [dataURL...]}（浏览器画好的几个角度）。返回 {parts: [{index, pos, rot}], note, provider_warn}（不保存）。"""
    from core import ai_copy
    cfg = load_config()
    if (cfg.get("ai_provider") or "") == "deepseek":
        raise ValueError("现在设置的 AI（DeepSeek）不能看图片，「AI 按图片组装」需要能看图的 AI（设置 → AI 与对接 换成 Claude 或其他支持图片的模型）。"
                         "也可以直接用鼠标拖动零件组装")
    p = store.load(pid)
    _e, parts = parts_info(pid)
    if len(parts) < 2:
        raise ValueError("这个模型只有一个零件，不用组装")
    img = None
    if product_image:
        try:
            from PIL import Image
            raw = base64.b64decode(product_image.split(",", 1)[1] if "," in product_image else product_image)
            img = Image.open(io.BytesIO(raw))
        except Exception:  # noqa: BLE001
            img = None
    if img is None:
        img = _main_image(p)
    sheet = _sheet(img, renders or {})
    info = [{"index": x["index"], "name": x["name"], "size_mm": x["size"]} for x in parts]
    user_msg = ("产品：" + (p.get("name_zh") or p["id"]) + ("" if img is not None else "（没有商品主图，按常识组装）") +
                "\n零件（外框尺寸 = X 宽 × Y 深 × Z 高，毫米，是渲染图里的原始朝向）：\n" + json.dumps(info, ensure_ascii=False) +
                '\n\n输出 JSON：{"parts": [{"index": 0, "pos": [x, y, z], "rot": [rx, ry, rz]}], "note_zh": "一句话说明", "note_th": "..."}')
    data = ai_copy.extract_json(ai_copy.call(cfg, AI_SYSTEM, user_msg, image_b64=sheet))
    out = []
    n = len(parts)
    for x in data.get("parts") or []:
        try:
            i = int(x.get("index"))
        except (TypeError, ValueError):
            continue
        if 0 <= i < n:
            out.append({"index": i, "pos": _vec(x.get("pos")), "rot": _vec(x.get("rot"), lim=720)})
    if not out:
        raise ValueError("AI 没有给出零件位置，请重试或手动组装")
    return {"parts": out, "note_zh": str(data.get("note_zh") or "")[:300], "note_th": str(data.get("note_th") or "")[:300],
            "has_photo": img is not None}
