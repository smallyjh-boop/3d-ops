"""从文件名自动识别规格（从「3D选品工具」variant_detect.py 搬过来，规则不变）。

思路：同一个产品的多个模型文件，文件名里共同的部分是「产品名」，剩下不同的部分里有尺寸（100mm、60x72、W80L80H36、Small/Large、3 个装）
或版本（V2、带孔）的，就是不同规格；只有零件词（盖子、底座、左/右）的，是每个规格都要打印的零件；像打印配置（0.2mm PLA MK4 1h15m）的忽略。
文件名看不出来时，看外形是不是同一个形状按比例缩放。最后都要人在选品库里看一眼。

对外：rule_variants(files) —— files: [{id, name, folder, bbox}]，返回 {variants, common, ignored, confidence, note}
"""
import os
import re

MAX_VARIANTS = 30          # 自动识别最多列出的规格数（多了要人挑）
SPEC_LIMIT, SPEC_SUGGEST = 12, 8   # 对接规范 4.3.3：建议 ≤ 8 个，最多 12 个
# 尺寸词 → (中文, 泰文, 排序, 英文规格码)。按规范 4.3.6 统一说法：迷你 / 小号 / 中号 / 大号 / 特大号
SIZE_WORDS = {
    "xxs": ("迷你", "ขนาดมินิ", 1, "MINI"), "xs": ("迷你", "ขนาดมินิ", 2, "MINI"), "tiny": ("迷你", "ขนาดมินิ", 2, "MINI"), "mini": ("迷你", "ขนาดมินิ", 2, "MINI"),
    "s": ("小号", "ขนาดเล็ก", 3, "S"), "small": ("小号", "ขนาดเล็ก", 3, "S"), "sm": ("小号", "ขนาดเล็ก", 3, "S"),
    "short": ("矮款", "แบบเตี้ย", 3, "SHORT"), "thin": ("薄款", "แบบบาง", 3, "THIN"), "narrow": ("窄款", "แบบแคบ", 3, "NARROW"),
    "m": ("中号", "ขนาดกลาง", 5, "M"), "medium": ("中号", "ขนาดกลาง", 5, "M"), "med": ("中号", "ขนาดกลาง", 5, "M"), "mid": ("中号", "ขนาดกลาง", 5, "M"),
    "regular": ("标准款", "แบบมาตรฐาน", 5, "STD"), "standard": ("标准款", "แบบมาตรฐาน", 5, "STD"),
    "l": ("大号", "ขนาดใหญ่", 7, "L"), "large": ("大号", "ขนาดใหญ่", 7, "L"), "big": ("大号", "ขนาดใหญ่", 7, "L"),
    "tall": ("高款", "แบบสูง", 7, "TALL"), "long": ("长款", "แบบยาว", 7, "LONG"), "wide": ("宽款", "แบบกว้าง", 7, "WIDE"), "thick": ("厚款", "แบบหนา", 7, "THICK"),
    "xl": ("特大号", "ขนาดใหญ่พิเศษ", 8, "XL"), "xxl": ("特大号", "ขนาดใหญ่พิเศษ", 9, "XXL"), "huge": ("特大号", "ขนาดใหญ่พิเศษ", 9, "XL"), "giant": ("特大号", "ขนาดใหญ่พิเศษ", 9, "XL"),
    "小": ("小号", "ขนาดเล็ก", 3, "S"), "小号": ("小号", "ขนาดเล็ก", 3, "S"), "中": ("中号", "ขนาดกลาง", 5, "M"), "中号": ("中号", "ขนาดกลาง", 5, "M"),
    "大": ("大号", "ขนาดใหญ่", 7, "L"), "大号": ("大号", "ขนาดใหญ่", 7, "L"), "特大": ("特大号", "ขนาดใหญ่พิเศษ", 9, "XL"), "迷你": ("迷你", "ขนาดมินิ", 2, "MINI"),
}
# 规格名、品名、标题里不能出现的词（规范 4.3.6）：颜色由 ERP 管，营销词平台不允许
COLOR_WORDS = ["白", "黑", "红", "粉", "蓝", "绿", "黄", "紫", "灰", "金色", "银色", "橙", "棕", "彩虹", "渐变", "夜光", "透明", "木纹", "大理石", "多色", "彩色",
               "ขาว", "ดำ", "แดง", "ชมพู", "ฟ้า", "น้ำเงิน", "เขียว", "เหลือง", "ม่วง", "เทา", "สีทอง", "สีเงิน", "ส้ม", "น้ำตาล", "สีรุ้ง", "ไล่สี", "เรืองแสง", "โปร่งใส", "หลากสี",
               "white", "black", "red", "pink", "blue", "green", "yellow", "purple", "grey", "gray", "gold", "silver", "orange", "brown", "rainbow", "gradient", "glow", "transparent", "multicolor"]
MARKETING_WORDS = ["热卖", "爆款", "推荐", "限量", "特价", "秒杀", "包邮", "正品", "最便宜", "第一", "ขายดี", "แนะนำ", "ลดราคา", "ราคาถูก", "ส่งฟรี", "ของแท้", "best seller", "hot sale", "free shipping"]


def banned_words(text, words):
    """text 里出现的禁用词（英文按整词，中泰文按包含）。"""
    t = (text or "").lower()
    out = []
    for w in words:
        if re.fullmatch(r"[a-z ]+", w):
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", t):
                out.append(w)
        elif w in t:
            out.append(w)
    return out


def name_len(text):
    """规格名的字数：泰文上下的元音、声调符号不算一个字。"""
    import unicodedata
    return sum(1 for ch in (text or "") if unicodedata.category(ch) != "Mn")


def _cm(mm):
    v = round(float(mm) / 10, 1)
    return f"{v:g}"


VERSION_WORDS = {
    "with": ("带", "มี"), "without": ("不带", "ไม่มี"), "no": ("无", "ไม่มี"), "hole": ("孔", "รู"), "holes": ("孔", "รู"), "solid": ("实心", "ตัน"), "hollow": ("空心", "กลวง"),
    "wall": ("壁厚", "ผนัง"), "walls": ("壁厚", "ผนัง"), "plain": ("素面", "เรียบ"), "text": ("带字", "มีตัวอักษร"), "logo": ("带标志", "มีโลโก้"), "magnet": ("磁吸", "แม่เหล็ก"), "magnets": ("磁吸", "แม่เหล็ก"),
    "alt": ("备选款", "แบบอื่น"), "alternative": ("备选款", "แบบอื่น"), "version": ("版", "เวอร์ชัน"), "ver": ("版", "เวอร์ชัน"), "single": ("单个", "ชิ้นเดียว"), "double": ("双层", "สองชั้น"),
    "open": ("开口", "เปิด"), "closed": ("封闭", "ปิด"), "round": ("圆形", "กลม"), "square": ("方形", "สี่เหลี่ยม"), "hex": ("六角", "หกเหลี่ยม"),
}
PART_WORDS = {
    "lid", "cover", "top", "bottom", "base", "stand", "body", "shell", "inner", "outer", "left", "right", "part", "connector", "insert", "cap",
    "handle", "ring", "leg", "foot", "feet", "hinge", "pin", "clip", "tray", "drawer", "frame", "support", "bracket", "mount", "screw", "nut",
    "bolt", "knob", "door", "side", "front", "back", "piece", "half", "upper", "lower", "floater", "indicator", "join", "joiner", "spacer",
    "adapter", "washer", "plug", "stem", "arm", "wheel", "axle", "gear", "spring", "button", "latch", "rail", "slider", "holder", "plate",
    "saucer", "drip", "reservoir", "wick", "shelf", "rack", "wall_mount", "assembly", "盖", "盖子", "底座", "底", "支架", "零件", "托盘", "把手",
}
PROFILE_WORDS = {"pla", "petg", "abs", "asa", "tpu", "mk3", "mk3s", "mk4", "mk4s", "x1c", "x1", "p1s", "p1p", "a1", "bambu", "prusa", "ender",
                 "k1", "core", "orca", "slicer", "gcode", "nozzle", "layer", "infill", "supports", "brim"}


def _split_words(text):
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return [w for w in re.split(r"[^0-9a-zA-Z一-鿿%.]+", text.lower()) if w and w != "."]


def _plural(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") and w[:-1] in PART_WORDS else w


def file_features(name, folder=""):
    """一个文件名里的尺寸、版本、零件词。"""
    base = os.path.splitext(name)[0]
    raw = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", f"{folder} {base}")          # rightV2 → right V2，slickLid → slick Lid
    raw = re.sub(r"[_\-+]+", " ", raw).lower().replace("×", "x").replace("*", "x")
    sizes = []
    for m in re.finditer(r"\bw\s*(\d+(?:\.\d+)?)\s*l\s*(\d+(?:\.\d+)?)(?:\s*h\s*(\d+(?:\.\d+)?))?", raw):
        sizes.append(("dims", tuple(float(x) for x in m.groups() if x)))
    raw2 = re.sub(r"\bw\s*\d+(?:\.\d+)?\s*l\s*\d+(?:\.\d+)?(?:\s*h\s*\d+(?:\.\d+)?)?", " ", raw)
    for m in re.finditer(r"(?<![\d.])(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)(?:\s*x\s*(\d+(?:\.\d+)?))?(?![\d.])", raw2):
        sizes.append(("dims", tuple(float(x) for x in m.groups() if x)))
    raw2 = re.sub(r"(?<![\d.])\d+(?:\.\d+)?\s*x\s*\d+(?:\.\d+)?(?:\s*x\s*\d+(?:\.\d+)?)?(?![\d.])", " ", raw2)
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*(mm|cm|in|inch)\b", raw2):
        v = float(m.group(1)) * (10 if m.group(2) == "cm" else 25.4 if m.group(2).startswith("in") else 1)
        sizes.append(("len", round(v, 1), m.group(0).replace(" ", "")))
    raw2 = re.sub(r"(\d+(?:\.\d+)?)\s*(mm|cm|in|inch)\b", " ", raw2)
    for m in re.finditer(r"(\d+)\s*%", raw2):
        sizes.append(("pct", int(m.group(1))))
    for m in re.finditer(r"(?:\bx\s*(\d+)\b|\b(\d+)\s*(?:pcs|pc|pack|packs|个装|件套|件|个)\b)", raw2):
        sizes.append(("qty", int(m.group(1) or m.group(2))))
    words = [_plural(w) for w in _split_words(re.sub(r"(\d+)\s*%|\bx\s*\d+\b", " ", raw2))]
    return {"sizes": sizes, "words": words}


def _is_profile(feat):
    words = set(feat["words"])
    hits = len(words & PROFILE_WORDS) + sum(1 for w in words if re.fullmatch(r"\d+h\d+m|\d+h|\d+m\d+s", w))
    hits += sum(1 for s in feat["sizes"] if s[0] == "len" and s[1] <= 1.0)   # 0.2mm 这类层高
    return hits >= 2


def _label(key):
    """规格名和规格属性（规范 4.3.6 命名）：返回 {name_zh, name_th, name_en, kind, pack_qty, scale_pct}。"""
    zh, th, en, ver_zh, ver_th, ver_en = [], [], [], [], [], []
    kind, pack, scale = "", 1, 0
    if any(k[0] == "ver" and k[1] in ("wall", "walls") for k in key):
        # “2mm walls”是壁厚（版本差异），不是尺寸：写成“厚壁 2mm”
        thin = [k for k in key if k[0] == "len" and k[1] < 10]
        if thin:
            t = thin[0][1]
            key = tuple(k for k in key if k != thin[0] and not (k[0] == "ver" and k[1] in ("wall", "walls")))
            ver_zh.append(f"壁厚 {t:g}mm"); ver_th.append(f"ผนัง {t:g} มม."); ver_en.append(f"W{t:g}")
            kind = "version" if not any(k[0] in ("dims", "len", "pct", "size") for k in key) else ""
    for k in key:
        if k[0] == "dims":
            vals = k[1]
            if min(vals) >= 10:      # 文件名里的长宽高一般是毫米：换成厘米
                txt = "×".join(_cm(v) for v in vals)
                zh.append(txt + "cm"); th.append(txt + " ซม."); en.append(txt.replace("×", "X"))
            else:                    # 2x1、4x2 这类是格数，不是尺寸
                txt = "×".join(f"{v:g}" for v in vals)
                zh.append(txt); th.append(txt); en.append(txt.replace("×", "X"))
            kind = kind or "size"
        elif k[0] == "len":
            c = _cm(k[1])
            zh.append(f"{c}cm"); th.append(f"{c} ซม."); en.append(f"{c}CM")
            kind = kind or "size"
        elif k[0] == "pct":
            zh.append(f"{k[1]}%"); th.append(f"{k[1]}%"); en.append(f"{k[1]}P")
            scale = k[1]; kind = kind or "size"
        elif k[0] == "qty":
            pack = int(k[1])
            zh.append(f"{pack} 件装"); th.append(f"แพ็ค {pack} ชิ้น"); en.append(f"P{pack}")
            kind = "bundle"
        elif k[0] == "size":
            w = SIZE_WORDS[k[1]]
            zh.append(w[0]); th.append(w[1]); en.append(w[3])
            kind = kind or "size"
        elif k[0] == "ver":
            w = k[1]
            if w in VERSION_WORDS:
                ver_zh.append(VERSION_WORDS[w][0]); ver_th.append(VERSION_WORDS[w][1])
            else:
                ver_zh.append(w); ver_th.append(w)
            ver_en.append(w.upper()[:6])
            kind = kind or "version"
    if ver_zh:
        vz = "".join(ver_zh).replace("不带孔", "无孔")
        zh.append(vz if vz.endswith(("款", "版", "mm")) else vz + "款")
        vt = "".join(ver_th)
        th.append(vt if vt.startswith("ผนัง") else "แบบ" + vt)
        en.append("".join(ver_en)[:10])
    return {"name_zh": "·".join(zh), "name_th": "·".join(th), "name_en": "-".join(en)[:20],
            "kind": kind or "size", "pack_qty": pack, "scale_pct": scale}


def _sort_value(key, bbox_vol):
    nums = []
    for k in key:
        if k[0] == "dims":
            p = 1.0
            for v in k[1]:
                p *= v
            nums.append(p)
        elif k[0] in ("len", "pct", "qty"):
            nums.append(float(k[1]))
        elif k[0] == "size":
            nums.append(SIZE_WORDS[k[1]][2])
    return (nums[0] if nums else bbox_vol or 0, bbox_vol or 0)


def rule_variants(files):
    """规则识别。files: [{id,name,folder,bbox,est_minutes,est_grams}]。返回建议字典。"""
    feats = {f["id"]: file_features(f["name"], f.get("folder") or "") for f in files}
    ignored = [fid for fid, ft in feats.items() if _is_profile(ft)]
    use = [f for f in files if f["id"] not in ignored]
    if len(use) < 2:
        return {"variants": [], "common": [f["id"] for f in use], "ignored": ignored, "confidence": "high", "note": "只有一个模型文件，不分规格"}
    # 同一个文件有 V1/V2 等多个版本时，只用最新的（旧版忽略）
    sig = {}
    for f in use:
        words = feats[f["id"]]["words"]
        ver = max([int(w[1:]) for w in words if re.fullmatch(r"v\d+", w)] or [1])
        base_sig = (tuple(w for w in words if not re.fullmatch(r"v\d+", w)), tuple(feats[f["id"]]["sizes"]))
        sig.setdefault(base_sig, []).append((ver, f["id"]))
    for group in sig.values():
        if len(group) > 1:
            group.sort()
            ignored += [fid for _v, fid in group[:-1]]
    use = [f for f in use if f["id"] not in ignored]
    common_words = set.intersection(*(set(feats[f["id"]]["words"]) for f in use))
    keys, parts_only, base_files = {}, [], []
    for f in use:
        ft = feats[f["id"]]
        residual = [w for w in ft["words"] if w not in common_words]
        key = [("dims", s[1]) if s[0] == "dims" else s[:3] if s[0] == "len" else s[:2] for s in ft["sizes"]]
        for w in residual:
            if w in SIZE_WORDS:
                key.append(("size", w))
            elif w in VERSION_WORDS:          # V1/V2 是文件的修订版本，不是卖的规格（上面已经只留最新版）
                key.append(("ver", w))
        # 文件夹名里的尺寸已经算进来了；同一个尺寸写两遍去重（80×80 是 80×80×36 的一部分时只留后者）
        key = list(dict.fromkeys(key))
        dims = [k for k in key if k[0] == "dims"]
        key = tuple(k for k in key if not (k[0] == "dims" and any(o != k and o[1][:len(k[1])] == k[1] for o in dims)))
        has_part = any(w in PART_WORDS for w in residual) or any(w in ("part", "parts") for w in _split_words(f.get("folder") or ""))
        other = [w for w in residual if w not in PART_WORDS and w not in SIZE_WORDS and w not in VERSION_WORDS and not re.fullmatch(r"v\d+|\d+(\.\d+)?", w)]
        if key:
            keys.setdefault(key, []).append(f["id"])
        elif not residual:
            base_files.append(f["id"])          # 文件名就是产品名本身：通常是“原始尺寸”
        else:
            parts_only.append((f["id"], has_part, other))
    # 只有零件（盖子等）、尺寸是别的规格尺寸的一部分：挂到那些规格下面，不单独成规格（例如 80×80 的盖子配 80×80×36 的盒子）
    part_keys = {}
    for k, ids in list(keys.items()):
        if all(any(w in PART_WORDS for w in feats[i]["words"]) for i in ids):
            dims = [x[1] for x in k if x[0] == "dims"]
            owners = [o for o in keys if o != k and dims and any(od[1][:len(dims[0])] == dims[0] and len(od[1]) > len(dims[0]) for od in o if od[0] == "dims")]
            if owners:
                part_keys[k] = (ids, owners)
                del keys[k]
    real_keys = {k: v for k, v in keys.items() if any(x[0] in ("dims", "len", "pct", "qty", "size") for x in k)}
    ver_keys = {k: v for k, v in keys.items() if k not in real_keys}
    variants = []
    if real_keys or len(ver_keys) >= 1:
        for k, ids in list(real_keys.items()) + list(ver_keys.items()):
            extra = [i for pk, (pids, owners) in part_keys.items() if k in owners for i in pids]
            variants.append({"key": k, "file_ids": ids + extra})
        if base_files:
            variants.append({"key": (("size", "standard"),), "file_ids": base_files})
    common = [fid for fid, _p, _o in parts_only] if variants else [fid for fid, _p, _o in parts_only] + base_files
    unclear = [fid for fid, has_part, other in parts_only if other and not has_part]
    if not variants and len(unclear) >= 2:
        confidence, note = "low", "文件名里看不出尺寸或版本，可能是不同款式，也可能是一套零件，建议用 AI 识别或人工判断"
    elif not variants:
        confidence, note = "high", "这些文件是同一个产品的零件，不分规格"
    else:
        confidence = "high" if real_keys and not ver_keys else "medium"
        note = f"按文件名识别出 {len(variants)} 个规格" + (f"，另有 {len(common)} 个共用零件（每个规格都要打印）" if common else "")
    scaled_mode = False
    if not variants and len(unclear) >= 2:   # 文件名看不出来：看外形是不是同一个形状按比例放大缩小
        scaled = _scaled_group([f for f in files if f["id"] in unclear])
        if scaled:
            variants = [{"key": (("len", mx, ""),), "file_ids": [fid]} for fid, mx in scaled]
            common = [i for i in common if i not in unclear]
            scaled_mode = True
            confidence, note = "medium", f"文件名里没写尺寸，按模型外形判断是同一个形状的 {len(variants)} 个尺寸"
    if len(variants) == 1:   # 只有一个规格就等于不分规格
        common = sorted(set(common) | set(variants[0]["file_ids"]))
        variants = []
    by_id = {f["id"]: f for f in files}
    size_kind = any(x[0] in ("dims", "len", "pct", "size") for v in variants for x in v["key"])
    base_long = 0
    for v in variants:
        v.update(_label(v["key"]))
        own = [by_id[i] for i in v["file_ids"] if i in by_id]
        longest = max((_bbox_long(f.get("bbox")) for f in own), default=0)
        names = "、".join(f["name"] for f in own)
        if v["key"] == (("size", "standard"),):
            v.update(name_zh="标准款", name_th="แบบมาตรฐาน", name_en="STD", kind="size" if size_kind else "version", scale_pct=100)
            base_long = longest
        only_words = all(x[0] == "size" for x in v["key"])
        if only_words and len(own) == 1 and longest and v["key"] != (("size", "standard"),):
            # 小号 / 大号 后面加上最长边的厘米数（规范：可以两种都写，例如“大号 15cm”）
            v["name_zh"] += f" {_cm(longest)}cm"; v["name_th"] += f" {_cm(longest)} ซม."
        v["_long"] = longest
        if scaled_mode:
            v["conf"], v["evidence"] = 0.75, f"文件名里没写尺寸，外形按比例缩放：{names}"
        elif any(x[0] == "ver" for x in v["key"]) and not any(x[0] in ("dims", "len", "pct", "qty", "size") for x in v["key"]):
            v["conf"], v["evidence"] = 0.85, f"文件名：{names}"
        else:
            v["conf"], v["evidence"] = 0.95, f"文件名：{names}"
        if len(own) + len(common) > 1:
            v["evidence"] += "（多零件，尺寸为最大零件）"
        v["evidence"] = v["evidence"][:200]
        vols = [_bbox_volume(by_id[i].get("bbox")) for i in v["file_ids"] if i in by_id]
        v["sort"] = _sort_value(v["key"], max(vols) if vols else 0)
    if base_long:
        for v in variants:
            if v["kind"] == "size" and not v["scale_pct"] and v["_long"]:
                v["scale_pct"] = round(v["_long"] / base_long * 100)
    variants.sort(key=lambda v: (v["kind"] == "bundle", v["sort"]))   # 规范：从小到大、从单件到套装
    for v in variants:
        for k in ("key", "sort", "_long"):
            v.pop(k, None)
    extra = ""
    if len(variants) > MAX_VARIANTS:
        extra = f"；识别出 {len(variants)} 个规格，只列出前 {MAX_VARIANTS} 个"
        variants = variants[:MAX_VARIANTS]
    if len(variants) > SPEC_LIMIT:
        extra += f"；ERP 每个产品最多 {SPEC_LIMIT} 个规格，请删掉不卖的，或拆成几个产品"
    elif len(variants) > SPEC_SUGGEST:
        extra += f"；建议不超过 {SPEC_SUGGEST} 个规格（每个规格还要乘以颜色数）"
    return {"variants": variants, "common": common, "ignored": ignored, "confidence": confidence, "note": note + extra}


def _bbox_long(bbox):
    try:
        return max(float(v) for v in (bbox or "").split(","))
    except ValueError:
        return 0


def _scaled_group(files):
    """这些文件是不是同一个形状的不同尺寸：长宽高按同一个比例放大缩小（误差 4% 以内），而且大小确实不同。"""
    dims = []
    for f in files:
        try:
            d = sorted(float(v) for v in (f.get("bbox") or "").split(","))
        except ValueError:
            return None
        if len(d) != 3 or d[0] <= 0:
            return None
        dims.append((f["id"], d))
    dims.sort(key=lambda x: x[1][2])
    base = dims[0][1]
    scales = []
    for _fid, d in dims:
        ratios = [d[i] / base[i] for i in range(3)]
        if max(ratios) - min(ratios) > 0.04 * max(ratios):
            return None
        scales.append(sum(ratios) / 3)
    if any(b / a < 1.08 for a, b in zip(scales, scales[1:])):
        return None
    return [(fid, d[2]) for fid, d in dims]


def _bbox_volume(bbox):
    try:
        x, y, z = (float(v) for v in (bbox or "").split(","))
        return x * y * z
    except ValueError:
        return 0


