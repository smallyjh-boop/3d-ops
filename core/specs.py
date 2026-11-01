"""产品规格（v2.16，对接规范 4.3）：规格（尺寸 / 版本 / 套装 / 造型，不含颜色）。

产品里存两样：
  p["specs"]：规格列表 [{spec_id, position, kind, name_zh, name_th, name_en, is_default, size_mm, scale_pct, pack_qty, parts,
               grams, hours, files, recognize, status, reasons}]
      status：ok 正常 / review 待确认（AI 没把握、名字里有颜色词、缺泰文名）
      （旧状态 removed_pending 是旧「3D选品工具」同步产生的，v2.54 起不再使用，clear_removed_pending 把它改成 ok）
  p["variants"]：真正卖的 SKU = 规格 × 颜色（含「随机颜色」），每行 spec_id 指向规格，opt2_zh = 规格中文名。
v2.54：旧选品工具的规格同步（sync）和「规格由选品工具管理」的锁都去掉了，规格在 ERP 里可以随便改。
"""
import re
import time
import uuid

MAX_SPECS = 12
KINDS = ("size", "version", "bundle", "style")
KIND_ZH = {"size": "尺寸", "version": "版本", "bundle": "套装", "style": "造型"}
CONF_MIN = 0.8
NAME_MAX = 20

# 规格名里不该出现的颜色词（中 / 泰 / 英）
_COLOR_WORDS = ["白色", "黑色", "红色", "粉色", "粉红", "蓝色", "绿色", "黄色", "紫色", "灰色", "金色", "银色", "橙色", "棕色",
                "彩虹", "渐变", "夜光", "多色", "透明",
                "สีขาว", "สีดำ", "สีแดง", "สีชมพู", "สีฟ้า", "สีน้ำเงิน", "สีเขียว", "สีเหลือง", "สีม่วง", "สีเทา", "สีทอง",
                "สีเงิน", "สีส้ม", "สีน้ำตาล", "สีรุ้ง", "เรืองแสง"]
_COLOR_EN = re.compile(r"\b(white|black|red|pink|blue|green|yellow|purple|gr[ae]y|gold|silver|orange|brown|rainbow|gradient|glow)\b", re.I)
# 单个字的颜色（「白」「黑」…）只在作为独立词出现时算，免得「大号」之类误伤
_COLOR_ONE = re.compile(r"(^|[\s·/、（(])[白黑红粉蓝绿黄紫灰金银橙棕]($|[\s·/、）)款色])")


class SpecError(ValueError):
    pass


def color_words(text):
    t = str(text or "")
    hit = [w for w in _COLOR_WORDS if w in t]
    hit += [m.group(1) for m in _COLOR_EN.finditer(t)]
    m = _COLOR_ONE.search(t)
    if m:
        hit.append(t[m.start():m.end()].strip(" ·/、（()）"))
    return hit


def _num(v, name, label):
    if v in (None, ""):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        raise SpecError(f"规格「{name}」的 {label} 要是数字")


def parse(raw, legacy_ok=True):
    """校验并整理规格列表（选品采用时用）。返回 (specs, warnings)。不合格的抛 SpecError（中文说明）。"""
    if raw in (None, []):
        return [], []
    if not isinstance(raw, list):
        raise SpecError("variants 必须是数组")
    items = [x for x in raw if isinstance(x, dict)]
    items.sort(key=lambda x: x.get("position") if isinstance(x.get("position"), (int, float)) else 999)
    warnings = []
    if len(items) > MAX_SPECS:
        warnings.append(f"规格有 {len(items)} 个，超过 {MAX_SPECS} 个，只保留前 {MAX_SPECS} 个："
                        + "、".join(str(x.get("name_zh") or "") for x in items[MAX_SPECS:]) + " 没有加")
        items = items[:MAX_SPECS]
    out, names, ids = [], set(), set()
    for i, v in enumerate(items):
        name = str(v.get("name_zh") or "").strip()
        if not name:
            raise SpecError(f"第 {i + 1} 个规格没有中文名（name_zh）")
        if name in names:
            raise SpecError(f"规格名「{name}」重复了")
        names.add(name)
        sid = str(v.get("spec_id") or "").strip()[:40]
        if not sid:
            if not legacy_ok:
                raise SpecError(f"规格「{name}」没有 spec_id（v1.8 起必填）")
            sid = "auto-" + name                     # 老版本选品工具没有 spec_id：用名字代替
            if "auto" not in "".join(warnings):
                warnings.append("规格没有 spec_id（对接规范 v1.8 起必填），先用规格名代替；以后改名会对不上")
        if sid in ids:
            raise SpecError(f"spec_id「{sid}」重复了")
        ids.add(sid)
        kind = str(v.get("kind") or "").strip().lower()
        if kind and kind not in KINDS:
            raise SpecError(f"规格「{name}」的 kind 只能是 {' / '.join(KINDS)}")
        g = _num(v.get("filament_grams"), name, "filament_grams（克数）")
        m = _num(v.get("print_minutes"), name, "print_minutes（打印分钟）")
        scale = _num(v.get("scale_pct"), name, "scale_pct")
        try:
            pack = max(1, int(v.get("pack_qty") or 1))
            parts = max(0, int(v.get("parts") or 0))
        except (TypeError, ValueError):
            raise SpecError(f"规格「{name}」的 pack_qty / parts 要是整数")
        size = v.get("size_mm")
        if size is not None:
            if not (isinstance(size, list) and len(size) == 3):
                raise SpecError(f"规格「{name}」的 size_mm 要是 [宽, 深, 高]")
            size = [round(_num(x, name, "size_mm"), 1) for x in size]
        rec = v.get("recognize") if isinstance(v.get("recognize"), dict) else {}
        method = str(rec.get("method") or "").strip().lower()
        try:
            conf = float(rec.get("confidence")) if rec.get("confidence") is not None else None
        except (TypeError, ValueError):
            conf = None
        name_th = str(v.get("name_th") or "").strip()
        # 多零件产品：选品工具只能量到最大零件，尺寸只作参考（需求单 2026-10-06 第 3 点）
        ev = str(rec.get("evidence") or "")
        size_ref = bool(size) and (parts > 1 or "多零件" in ev or "最大零件" in ev)
        files = [x for x in (v.get("files") or []) if isinstance(x, dict) and x.get("url")] if isinstance(v.get("files"), list) else []
        reasons, rcodes = [], []
        if method and method != "manual" and conf is not None and conf < CONF_MIN:
            reasons.append(f"识别把握不大（{method} {conf:.2f}）")
            rcodes.append(["spec.r.low_conf", f" ({method} {conf:.2f})"])
        cw = color_words(name) + color_words(name_th) + color_words(v.get("name_en"))
        if cw:
            reasons.append("名字里有颜色词：" + "、".join(dict.fromkeys(cw)))
            rcodes.append(["spec.r.color_word", ": " + ", ".join(dict.fromkeys(cw))])
            warnings.append(f"规格「{name}」名字里有颜色词（{'、'.join(dict.fromkeys(cw))}），颜色由 ERP 加，已标记待确认")
        if not name_th:
            reasons.append("没有泰文名")
            rcodes.append(["spec.r.no_th", ""])
        if len(name) > NAME_MAX or len(name_th) > NAME_MAX:
            warnings.append(f"规格「{name}」名字超过 {NAME_MAX} 字，平台上可能显示不全")
        out.append({
            "spec_id": sid, "position": i + 1, "kind": kind or "", "name_zh": name[:40], "name_th": name_th[:60],
            "name_en": str(v.get("name_en") or "").strip()[:20], "is_default": bool(v.get("is_default")),
            "size_mm": size, "size_ref": size_ref, "scale_pct": scale or None, "pack_qty": pack, "parts": parts or None,
            "grams": round(g, 1) if g > 0 else 0, "hours": round(m / 60.0, 2) if m > 0 else 0, "files": files[:5],
            "recognize": {"method": method, "confidence": conf, "evidence": str(rec.get("evidence") or "")[:200]},
            "status": "review" if reasons else "ok", "reasons": reasons, "rcodes": rcodes,
        })
    if sum(1 for s in out if s["is_default"]) > 1:
        warnings.append("is_default 有多个，只用第一个")
        first = True
        for s in out:
            if s["is_default"]:
                s["is_default"], first = first, False
    return out, warnings


def _colors(p):
    seen = []
    for v in p.get("variants") or []:
        c = (v.get("opt1_zh") or "").strip()
        if c not in seen:
            seen.append(c)
    return seen or [""]


def _row(base, spec, color):
    return dict(base, opt1_zh=color, opt2_zh=spec["name_zh"], spec_id=spec["spec_id"], grams=spec["grams"], hours=spec["hours"],
                grams_src="curator" if spec["grams"] else "pending", manual_price=None, image="", stock=None, sku="")


def build_rows(p, specs):
    """新产品：每个规格一行（颜色在 ERP 里加，加颜色时 规格 × 颜色 展开）。"""
    base = dict((p.get("variants") or [{}])[0])
    for k in ("sku", "spec_id"):
        base.pop(k, None)
    p["variation2_name_zh"] = "规格"
    cp = p.setdefault("copy", {})
    cp.setdefault("variation2_name_th", "ตัวเลือก")      # 平台上的选项名（泰文「款式 / 选项」），可以在编辑页改
    p["variants"] = [_row(base, s, "") for s in specs]
    th = {s["name_zh"]: s["name_th"] for s in specs if s["name_th"]}
    if th:
        p.setdefault("copy", {}).setdefault("options_th", {}).update(th)
    p["specs"] = [{k: v for k, v in s.items()} for s in specs]


def clear_removed_pending(p):
    """v2.54：旧选品工具「删了也保留」的待确认状态不再有意义，改成正常规格。返回是否改了。"""
    n = 0
    for x in p.get("specs") or []:
        if x.get("status") == "removed_pending":
            x.update(status="ok", reasons=[], rcodes=[], kept_local=True)
            n += 1
    return bool(n)


def confirm(p, spec_id, action, user=""):
    """ERP 里的人处理待确认的规格。action：ok 确认没问题 / keep 留着 / delete 删掉（连同它的 SKU）。"""
    s = next((x for x in p.get("specs") or [] if x["spec_id"] == spec_id), None)
    if not s:
        raise SpecError("没有这个规格")
    now = time.time()
    if action == "ok":
        s.update(status="ok", reasons=[], rcodes=[], confirmed_at=now, confirmed_by=user)
    elif action == "keep":
        s.update(status="ok", reasons=[], rcodes=[], kept_local=True, confirmed_at=now, confirmed_by=user)
    elif action == "delete":
        rest = [v for v in p.get("variants") or [] if v.get("spec_id") != spec_id]
        if not rest:
            raise SpecError("至少要留一个变体，不能把最后一个规格删掉")
        p["variants"] = rest
        p["specs"] = [x for x in p["specs"] if x["spec_id"] != spec_id]
    else:
        raise SpecError("action 只能是 ok / keep / delete")
    return s


def package_from_specs(p):
    """包裹尺寸还是默认值时，按规格尺寸估一个：最大规格的长宽高（厘米）+ 1 cm 余量；
    多零件（尺寸只是参考）的 + 2 cm，并标记「请核对」。返回是否改了。"""
    if p.get("package_status") not in (None, "default"):
        return False
    sizes = [s for s in p.get("specs") or [] if isinstance(s.get("size_mm"), list) and len(s["size_mm"]) == 3 and all(s["size_mm"])]
    if not sizes:
        return False
    ref = any(s.get("size_ref") for s in sizes)
    dims = sorted((max(sorted(s["size_mm"], reverse=True)[i] for s in sizes) for i in range(3)), reverse=True)
    pad = 2 if ref else 1
    l, w, h = (round(d / 10.0 + pad, 1) for d in dims)
    if not all(0.01 <= x <= 200 for x in (l, w, h)):
        return False
    p["package"] = {"length": l, "width": w, "height": h}
    p["package_status"] = "check" if ref else "ai"
    p["package_src"] = "spec_ref" if ref else "spec"
    return True


def spec_of(p, v):
    sid = v.get("spec_id")
    if not sid:
        return None
    return next((s for s in p.get("specs") or [] if s["spec_id"] == sid), None)


def review_problems(p):
    """上架检查用：待确认的规格（阻止导出）。"""
    errs, warns = [], []
    used = {v.get("spec_id") for v in p.get("variants") or []}
    for s in p.get("specs") or []:
        if s["spec_id"] not in used:
            continue
        if s.get("status") == "review":
            errs.append(f"规格「{s['name_zh']}」待确认（{'；'.join(s.get('reasons') or [])}），在「变体」里确认后才能导出")
    return errs, warns


# 平台限制（v2.22.1，取 Lazada / Shopee 都能过的范围）：选项名最多 20 个字；每一层最多 20 个选项；规格 × 颜色最多 50 个 SKU
OPT_MAX_LEN = 20
OPT_MAX_EACH = 20
SKU_MAX = 50


def limits_problem(vs):
    colors, specs_ = [], []
    for v in vs:
        for val, bag, lab in ((v.get("opt1_zh"), colors, "颜色"), (v.get("opt2_zh"), specs_, "规格")):
            val = str(val or "").strip()
            if len(val) > OPT_MAX_LEN:
                return f"{lab}「{val}」太长：平台上的选项名最多 {OPT_MAX_LEN} 个字"
            if val and val not in bag:
                bag.append(val)
    if len(colors) > OPT_MAX_EACH:
        return f"颜色有 {len(colors)} 个：平台每一层选项最多 {OPT_MAX_EACH} 个"
    if len(specs_) > OPT_MAX_EACH:
        return f"规格有 {len(specs_)} 个：平台每一层选项最多 {OPT_MAX_EACH} 个"
    if len(vs) > SKU_MAX:
        return f"变体有 {len(vs)} 行：为了 Lazada / Shopee 都能上架，一个商品最多 {SKU_MAX} 个 SKU，可以拆成两个商品"
    return ""


def add_local_spec(p, name, grams=None, hours=None):
    """ERP 里自己加的规格：记成 source = erp。"""
    sp = p.setdefault("specs", [])
    for x in sp:
        if x.get("name_zh") == name:
            return x
    x = {"spec_id": "erp-" + uuid.uuid4().hex[:8], "name_zh": name, "name_th": "", "status": "ok", "reasons": [], "rcodes": [],
         "kept_local": True, "source": "erp", "grams": grams or 0, "hours": hours or 0, "position": 900 + len(sp), "added_at": time.time()}
    sp.append(x)
    return x


def check_variants(p, old=None):
    """保存产品前检查变体（v2.22）。返回错误说明（空 = 没问题）。会顺手去掉颜色 / 规格前后的空格。
    · 同一个 颜色 + 规格 不能有两行；
    · 选项名长度、选项个数、SKU 个数不超过平台限制；
    · 产品有规格记录（p["specs"]）时，变体的 spec_id 跟着规格名走：改名 → 规格记录跟着改名（数据不丢），新名字 → 记成 ERP 自加。
      v2.54 起规格可以随便改，不再有「由选品工具管理」的限制。"""
    vs = p.get("variants") or []
    if not vs:
        return "至少要有一个变体"
    seen = set()
    for v in vs:
        v["opt1_zh"] = str(v.get("opt1_zh") or "").strip()
        v["opt2_zh"] = str(v.get("opt2_zh") or "").strip()
        k = (v["opt1_zh"], v["opt2_zh"])
        if k in seen:
            return f"「{v['opt1_zh'] or '—'} · {v['opt2_zh'] or '—'}」有两行，同一个颜色 + 规格只能有一行"
        seen.add(k)
    bad = limits_problem(vs)
    if bad:
        return bad
    specs = (old or p).get("specs") or []
    if specs:
        p["specs"] = [dict(x) for x in specs]
        by_id = {x["spec_id"]: x for x in p["specs"]}
        names = {x["name_zh"]: x for x in p["specs"]}
        for v in vs:
            if not v["opt2_zh"]:
                v.pop("spec_id", None)
                continue
            if v["opt2_zh"] not in names:
                cur = by_id.get(v.get("spec_id"))
                if cur and cur["name_zh"] not in {w["opt2_zh"] for w in vs}:
                    names.pop(cur["name_zh"], None)       # 改名：规格记录跟着改，克数 / 尺寸等数据留着
                    cur["name_zh"] = v["opt2_zh"]
                    names[v["opt2_zh"]] = cur
                else:
                    names[v["opt2_zh"]] = add_local_spec(p, v["opt2_zh"], v.get("grams"), v.get("hours"))
            v["spec_id"] = names[v["opt2_zh"]]["spec_id"]
        used = {v["opt2_zh"] for v in vs}
        # 自己加的规格被删光：去掉；其他规格记录留着（里面有克数 / 尺寸等数据）
        p["specs"] = [x for x in p["specs"] if not (x.get("source") == "erp" and x["name_zh"] not in used)]
    return ""
