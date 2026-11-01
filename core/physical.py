"""商品实物数据（v2.55.1 T31）：每个规格的成品尺寸、成品净重、包裹尺寸、包裹重量 —— 值 + 来源 + 待确认 / 已确认。

老板要求：尺寸和重量很重要不能错（平台按它算运费、超了会被罚），自动算出来的一律「待确认」，人工核对后点「确认」；
没确认的不能导出 / 推送（lazada_template.check_product 报错，Shopee 导出、Lazada 推送用同一份检查）。

数据（产品资料 product["physical"]）：
  {规格名（没有规格的产品 = ""）: {
      "size":  {"v": [宽, 深, 高] 毫米, "src", "ok", "by", "at"},     成品尺寸（组装好的）
      "net":   {"v": 克, ...},                                          成品净重（一件 / 一套，不含支撑、换色冲刷）
      "pkg":   {"v": [长, 宽, 高] 厘米, ...},                           包裹尺寸
      "pkg_g": {"v": 克, ...},                                          包裹重量（src=calc 时按公式自动算）
      "box": 纸箱规格（"" 没选 / "none" 不用纸箱）, "qty": 每个包裹几件（默认 1）, "vol_cm3": 实体体积（合理性检查用）}}
  来源 src：default 默认值 / est 估算 / calc 自动算 / model 模型外框 / assembly 组装外框 / box 纸箱 / slice 切片净重 /
            manual 手填 / weighed 实称。自动写入时可靠的来源不会被不可靠的覆盖（实称 > 手填 > 切片 > 外框 / 纸箱 > 估算）。
  包裹重量 = 净重 × 件数 + 纸箱重量（boxes 目录）+ 填充物重量（设置 filler_weight_g）；没选纸箱时 = 净重 × 件数 + 包材重量（packaging_weight_g）。

老数据兼容（不批量改数据文件，读的时候推断，保存时写新结构）：
  p["package"] / p["package_status"] / p["pack_box"] 继续是第一个规格（默认规格）的镜像，老代码照常读；
  老的编辑页 / AI 改了 p["package"] → 读的时候以它为准（package_status=manual 算已确认）；
  净重：试打写过的克数（grams_src=trial）→ 实称、待确认；其它按变体克数 → 估算、待确认。
对外：spec_keys  rows  row  issues  export_vals  set_item  set_box  set_qty  confirm  auto_pkg  box_weight  density
"""
import os
import re
import time

FIELDS = ("size", "net", "pkg", "pkg_g")
FIELD_ZH = {"size": "成品尺寸", "net": "净重", "pkg": "包裹尺寸", "pkg_g": "包裹重量"}
FIELD_TH = {"size": "ขนาดสินค้า", "net": "น้ำหนักสุทธิ", "pkg": "ขนาดพัสดุ", "pkg_g": "น้ำหนักพัสดุ"}
SRC_RANK = {"": 0, "default": 0, "est": 1, "calc": 1, "model": 2, "assembly": 2, "box": 2, "slice": 3, "manual": 4, "weighed": 5}
SRC_ZH = {"default": "默认值", "est": "估算", "calc": "自动算", "model": "模型外框", "assembly": "组装外框", "box": "纸箱",
          "slice": "切片净重", "manual": "手填", "weighed": "实称"}
SRC_TH = {"default": "ค่าเริ่มต้น", "est": "ประมาณ", "calc": "คำนวณอัตโนมัติ", "model": "กรอบโมเดล", "assembly": "กรอบแบบประกอบ",
          "box": "กล่อง", "slice": "สไลซ์ (สุทธิ)", "manual": "กรอกเอง", "weighed": "ชั่งจริง"}
# 材料密度（克 / 立方厘米），合理性检查用
DENSITY = [("PETG", 1.27), ("TPU", 1.21), ("ABS", 1.04), ("ASA", 1.07), ("PLA", 1.24)]
PKG_MARGIN_CM = 1.0       # 选纸箱：成品每个方向留的余量（总共，厘米）
PKG_PAD_CM = 3.0          # 没有合适的纸箱：成品尺寸每边 +1.5 cm
DENSITY_TOL = 0.4         # 净重和按体积估的偏差超过 40% 标黄


def density(material):
    m = (material or "PLA").upper()
    for k, v in DENSITY:
        if k in m:
            return v
    return 1.2


def _blocking(cfg):
    """没确认的实物数据挡导出 / 推送（老板确认：拦截）。LH_PHYS_BLOCK=0 只给老的回归测试用。"""
    v = (cfg or {}).get("physical_block")
    if v is None:
        v = os.environ.get("LH_PHYS_BLOCK", "1") != "0"
    return bool(v)


def _cfg(cfg):
    if cfg is not None:
        return cfg
    from .config import load_config
    return load_config()


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _dims(v):
    """[a, b, c]（都 > 0）→ 一位小数；不对返回 None。"""
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        return None
    out = [_num(x) for x in v]
    if any(x is None or x <= 0 for x in out):
        return None
    return [round(x, 1) for x in out]


def _same(a, b, tol=0.05):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))
    return abs(float(a) - float(b)) <= tol


def spec_keys(p):
    """实物数据按哪些规格分：变体里出现的规格（变体顺序；没有规格的变体 = ""）。第一个是默认规格（p["package"] 镜像它）。"""
    out = []
    for v in p.get("variants") or []:
        s = (v.get("opt2_zh") or "").strip()
        if s not in out:
            out.append(s)
    return out or [""]


def _store(p):
    d = p.get("physical")
    return d if isinstance(d, dict) else {}


def _item(d):
    if not isinstance(d, dict):
        return None
    return {"v": d.get("v"), "src": d.get("src") or "", "ok": bool(d.get("ok")), "by": d.get("by") or "", "at": d.get("at"),
            **({"note": d["note"]} if d.get("note") else {})}


def _blank():
    return {"v": None, "src": "", "ok": False, "by": "", "at": None}


# ---------------- 老数据推断 ----------------
def _legacy_pkg(p):
    pk = p.get("package") or {}
    dims = _dims([pk.get("length"), pk.get("width"), pk.get("height")])
    st = p.get("package_status") or ""
    src = "manual" if st == "manual" else "default" if st == "default" else "est"
    return {"v": dims, "src": src if dims else "", "ok": st == "manual" and bool(dims), "by": "", "at": None}


def _legacy_size(p):
    t = str(p.get("size_text") or "")
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", t)]
    if len(nums) != 3:
        return _blank()
    k = 1.0 if re.search(r"mm|มม", t, re.I) else 10.0
    d = _dims([x * k for x in nums])
    return {"v": d, "src": "est", "ok": False, "by": "", "at": None} if d else _blank()


def _legacy_net(p, spec):
    vs = [v for v in p.get("variants") or [] if (v.get("opt2_zh") or "").strip() == spec]
    tr = [float(v.get("grams") or 0) for v in vs if v.get("grams_src") == "trial" and float(v.get("grams") or 0) > 0]
    if tr:
        return {"v": round(max(tr), 1), "src": "weighed", "ok": False, "by": "", "at": None, "note": "trial"}
    gs = [float(v.get("grams") or 0) for v in vs if float(v.get("grams") or 0) > 0]
    if gs:
        return {"v": round(max(gs), 1), "src": "est", "ok": False, "by": "", "at": None}
    return _blank()


def _pack_qty(p, spec):
    for s in p.get("specs") or []:
        if isinstance(s, dict) and (s.get("name_zh") or "").strip() == spec and spec:
            try:
                return max(1, int(s.get("pack_qty") or 1))
            except (TypeError, ValueError):
                return 1
    return 1


# ---------------- 纸箱 / 包裹 ----------------
def box_weight(code):
    from .inventory import boxes
    b = boxes.get(code) if code and code != boxes.NONE else None
    return float(b["weight_g"]) if b else None


def auto_pkg(size_mm):
    """成品尺寸（毫米）→ (包裹尺寸 [长, 宽, 高] 厘米, 纸箱规格, 来源)：能装下的最小邮政纸箱；没有合适的 → 每边 +1.5 cm。"""
    from .inventory import boxes
    d = _dims(size_mm)
    if not d:
        return None, "", ""
    cm = [x / 10.0 for x in d]
    code = boxes.fit(*cm, margin=PKG_MARGIN_CM)
    if code:
        b = boxes.get(code)
        return [float(b["l"]), float(b["w"]), float(b["h"])], code, "box"
    s = sorted(cm, reverse=True)
    return [round(x + PKG_PAD_CM, 1) for x in s], "", "est"


def calc_pkg_g(net, qty, box, cfg):
    """包裹重量（克）：净重 × 件数 + 纸箱 + 填充物；没选纸箱（或用快递袋）= 净重 × 件数 + 包材重量。"""
    if net is None or net <= 0:
        return None
    bw = box_weight(box)
    if bw is not None:
        extra = bw + float(cfg.get("filler_weight_g", 20) or 0)
    else:
        extra = float(cfg.get("packaging_weight_g", 50) or 0)
    return round(net * max(1, int(qty or 1)) + extra, 1)


# ---------------- 读 ----------------
def row(p, spec, cfg=None, default=None):
    """一个规格的实物数据（老数据按上面的规则推断）。返回 {spec, size, net, pkg, pkg_g, box, box_w, qty, vol_cm3, checks, missing, ok}。"""
    cfg = _cfg(cfg)
    spec = (spec or "").strip()
    st = _store(p).get(spec) or {}
    is_def = spec == (default if default is not None else spec_keys(p)[0])
    size = _item(st.get("size")) or (_legacy_size(p) if is_def else _blank())
    net = _item(st.get("net")) or _legacy_net(p, spec)
    pkg = _item(st.get("pkg"))
    box = st.get("box") if "box" in st else (p.get("pack_box") or "")
    leg = _legacy_pkg(p)
    if not pkg:
        pkg, box = leg, (p.get("pack_box") or "")
    elif is_def:
        # 默认规格：老的编辑页 / AI 改了 p["package"]（或纸箱）→ 以它为准；确认状态跟着 package_status
        if not _same(pkg["v"], leg["v"]) or (p.get("pack_box") or "") != (box or ""):
            pkg, box = leg, (p.get("pack_box") or "")
        elif leg["ok"] != pkg["ok"]:
            pkg = dict(pkg, ok=leg["ok"])
    qty = st.get("qty") or _pack_qty(p, spec)
    try:
        qty = max(1, int(qty))
    except (TypeError, ValueError):
        qty = 1
    calc = calc_pkg_g(_num(net.get("v")), qty, box, cfg)
    s = _item(st.get("pkg_g"))
    if s and s["src"] in ("manual", "weighed") and _num(s["v"]):
        pg = s
    else:
        okc = bool(s and s["ok"] and calc is not None and _same(_num(s["v"]), calc, 0.5))
        pg = {"v": calc, "src": "calc" if calc is not None else "", "ok": okc, "by": s["by"] if okc else "", "at": s["at"] if okc else None}
    r = {"spec": spec, "size": size, "net": net, "pkg": pkg, "pkg_g": pg, "box": box or "", "box_w": box_weight(box),
         "qty": qty, "vol_cm3": _num(st.get("vol_cm3")), "infill": _num(st.get("infill")), "default": is_def}
    r["checks"] = checks(p, r)
    r["missing"] = [f for f in FIELDS if not (r[f]["ok"] and r[f]["v"] not in (None, 0, []))]
    r["ok"] = not r["missing"] and not any(c["level"] == "red" for c in r["checks"])
    return r


def rows(p, cfg=None):
    cfg = _cfg(cfg)
    keys = spec_keys(p)
    return {s: row(p, s, cfg, keys[0]) for s in keys}


def checks(p, r):
    """合理性检查：[{level: red / yellow, field, zh, th}]。"""
    out = []

    def add(level, field, zh, th):
        out.append({"level": level, "field": field, "zh": zh, "th": th})
    net, pg = _num(r["net"]["v"]), _num(r["pkg_g"]["v"])
    if r["net"]["v"] is not None and not (net and net > 0):
        add("red", "net", "净重是 0", "น้ำหนักสุทธิเป็น 0")
    if r["pkg_g"]["v"] is not None and not (pg and pg > 0):
        add("red", "pkg_g", "包裹重量是 0", "น้ำหนักพัสดุเป็น 0")
    size, pkg = _dims(r["size"]["v"]), _dims(r["pkg"]["v"])
    if size and pkg:
        s = sorted(size)
        k = sorted(x * 10 for x in pkg)
        if any(a + 0.05 < b for a, b in zip(k, s)):
            add("red", "pkg", f"包裹装不下成品：包裹 {'×'.join(f'{x:g}' for x in pkg)} cm，成品 {'×'.join(f'{x:g}' for x in size)} mm",
                f"พัสดุเล็กกว่าสินค้า: พัสดุ {'×'.join(f'{x:g}' for x in pkg)} ซม. สินค้า {'×'.join(f'{x:g}' for x in size)} มม.")
    vol = r.get("vol_cm3")
    if net and vol and vol > 0:
        exp = expected_net(vol, size, r.get("infill"), p.get("material"))
        if exp and abs(net / exp - 1) > DENSITY_TOL:
            add("yellow", "net", f"净重 {net:g} g 和按体积估的约 {exp:g} g 差得多（{net / exp * 100:.0f}%），请核对（多零件漏算 / 填充率不同？）",
                f"น้ำหนักสุทธิ {net:g} g ต่างจากที่ประมาณจากปริมาตร ~{exp:g} g มาก ({net / exp * 100:.0f}%) กรุณาตรวจสอบ")
    return out


def expected_net(vol_cm3, size_mm=None, infill_pct=None, material="PLA"):
    """按体积 × 材料密度估一件的净重（克）：外壳（壁 + 顶底，按外框表面积 × 约 1.2 mm）实心，里面按填充率。"""
    vol = _num(vol_cm3)
    if not vol or vol <= 0:
        return None
    inf = _num(infill_pct)
    inf = (inf if inf is not None else 15) / 100.0
    sh = 0.35
    d = _dims(size_mm)
    if d:
        a, b, c = (x / 10 for x in d)
        area = 2 * (a * b + a * c + b * c)
        sh = min(1.0, area * 0.12 / vol)
    return round(vol * density(material) * (sh + (1 - sh) * inf), 1)


# ---------------- 检查 / 导出 ----------------
def _spec_label(spec):
    return f"规格「{spec}」" if spec else ""


def issues(p, cfg=None):
    """上架检查（errors）：没确认 / 有红色问题的实物数据。没开拦截时返回 []。"""
    cfg = _cfg(cfg)
    if not _blocking(cfg):
        return []
    out = []
    for s, r in rows(p, cfg).items():
        if r["missing"]:
            out.append(f"实物数据未确认{('：' + _spec_label(s)) if s else ''}（{'、'.join(FIELD_ZH[f] for f in r['missing'])}）"
                       "——在 ③ 3D 模型的「实物数据」卡里核对后点「确认」")
        reds = [c["zh"] for c in r["checks"] if c["level"] == "red"]
        if reds:
            out.append(f"实物数据有错{('：' + _spec_label(s)) if s else ''}：{'；'.join(reds)}")
    return out


def export_vals(p, v, cfg=None, cache=None):
    """导出 / 推送的一行（一个变体）：按变体所属规格取 (包裹重量 kg, 长, 宽, 高 cm)。"""
    cfg = _cfg(cfg)
    spec = (v.get("opt2_zh") or "").strip()
    if cache is None:
        cache = {}
    key = (p.get("id"), spec)
    if key not in cache:
        keys = spec_keys(p)
        cache[key] = row(p, spec, cfg, keys[0])
    r = cache[key]
    g = _num(r["pkg_g"]["v"])
    if not g:          # 没有净重：按以前的算法（变体克数 + 包材重量）
        g = float(v.get("grams") or 0) + float(cfg.get("packaging_weight_g", 50))
    pk = _dims(r["pkg"]["v"]) or [(p.get("package") or {}).get(k) for k in ("length", "width", "height")]
    return round(max(0.01, g / 1000), 3), pk[0], pk[1], pk[2]


# ---------------- 写 ----------------
def _st(p, spec):
    if not isinstance(p.get("physical"), dict):
        p["physical"] = {}
    return p["physical"].setdefault((spec or "").strip(), {})


def _mirror(p, spec):
    """默认规格的包裹尺寸 / 纸箱写回老字段（老代码、老的编辑页读）。"""
    keys = spec_keys(p)
    if (spec or "").strip() != keys[0]:
        return
    st = _store(p).get(keys[0]) or {}
    pk = st.get("pkg") or {}
    d = _dims(pk.get("v"))
    if d:
        p["package"] = dict(p.get("package") or {}, length=d[0], width=d[1], height=d[2])
        p["package_status"] = "manual" if pk.get("ok") else "check"
        p["package_src"] = "physical"
    if "box" in st:
        p["pack_box"] = st["box"]


def _pin(p, spec, cfg):
    """第一次写这个规格：把现在看到的（老数据推断的）值先存下来，后面只改动的那一项。"""
    keys = spec_keys(p)
    st = _st(p, spec)
    if st.get("_v"):
        return st
    r = row(p, spec, cfg, keys[0])
    for f in ("size", "net", "pkg"):
        # 只存可靠的 / 已确认的；估算的继续按老数据推断（变体克数、p["package"] 改了跟着变）
        if f not in st and r[f]["v"] is not None and (r[f]["ok"] or SRC_RANK.get(r[f]["src"], 0) >= 2):
            st[f] = {k: r[f][k] for k in ("v", "src", "ok", "by", "at")}
    if "box" not in st:
        st["box"] = r["box"]
    st["_v"] = 1
    return st


def _norm(field, value):
    if field in ("size", "pkg"):
        d = _dims(value)
        if not d:
            raise ValueError("尺寸要填三个大于 0 的数字")
        return d
    v = _num(value)
    if v is None or v <= 0:
        raise ValueError("重量要填大于 0 的数字（克）")
    return round(v, 1)


def set_item(p, spec, field, value, src, user="", ok=None, force=False, cfg=None, note=None):
    """写一项（改 p，调用的人负责保存）。
    ok=None：自动值（待确认）—— 现在的值来源更可靠，或同样可靠且已确认、数字没变时不写（force=True 总是写，仍待确认）。
    ok=True / False：人工写入（手填 / 实称）。返回是否写了。"""
    if field not in FIELDS:
        raise ValueError("不认识的项目")
    cfg = _cfg(cfg)
    v = _norm(field, value)
    cur = row(p, spec, cfg)[field]
    if ok is None and not force and cur["v"] is not None:
        rc, rn = SRC_RANK.get(cur["src"], 0), SRC_RANK.get(src, 0)
        if rc > rn or (rc == rn and _same(cur["v"], v) and cur["ok"]):
            return False
    st = _pin(p, spec, cfg)
    if field == "pkg_g" and src == "calc":
        st.pop("pkg_g", None)
        return True
    st[field] = {"v": v, "src": src, "ok": bool(ok), "by": (user or "") if ok else "", "at": time.time()}
    if note:
        st[field]["note"] = note
    if field == "pkg" and src not in ("box",):
        from .inventory import boxes
        b = boxes.get(st.get("box"))
        if b and not _same(sorted([float(b["l"]), float(b["w"]), float(b["h"])]), sorted(v)):
            st["box"] = ""        # 手填的尺寸和选的纸箱对不上：不算这个纸箱
    _mirror(p, spec)
    return True


def set_box(p, spec, code, user="", cfg=None, auto=False):
    """选纸箱：包裹尺寸按纸箱（手选 = 已确认；auto=True 自动选 = 待确认）。code="none" 不用纸箱（快递袋），包裹尺寸不动。"""
    from .inventory import boxes
    cfg = _cfg(cfg)
    code = (code or "").strip()
    st = _pin(p, spec, cfg)
    if code in ("", boxes.NONE):
        st["box"] = code
    else:
        b = boxes.get(code)
        if not b:
            raise ValueError("没有这个纸箱规格")
        st["box"] = b["code"]
        st["pkg"] = {"v": [float(b["l"]), float(b["w"]), float(b["h"])], "src": "box", "ok": not auto,
                     "by": "" if auto else (user or ""), "at": time.time()}
    _mirror(p, spec)
    return True


def set_qty(p, spec, qty, cfg=None):
    try:
        q = int(qty)
    except (TypeError, ValueError):
        raise ValueError("件数要填整数")
    if not 1 <= q <= 100:
        raise ValueError("件数要在 1-100")
    _pin(p, spec, _cfg(cfg))["qty"] = q
    return True


def set_extra(p, spec, cfg=None, **kw):
    """自动填尺寸时顺便记下的：vol_cm3（实体体积）、infill（填充率 %）。"""
    st = _pin(p, spec, _cfg(cfg))
    for k, v in kw.items():
        if v is not None:
            st[k] = v


def confirm(p, spec, fields=None, user="", cfg=None):
    """确认（改 p）：fields 默认全部 4 项。没有值的项目跳过。返回确认了哪些。"""
    cfg = _cfg(cfg)
    r = row(p, spec, cfg)
    st = _pin(p, spec, cfg)
    done = []
    for f in fields or FIELDS:
        if f not in FIELDS:
            continue
        it = r[f]
        if it["v"] in (None, 0, []):
            continue
        st[f] = {"v": it["v"], "src": it["src"] or "manual", "ok": True, "by": user or "", "at": time.time(),
                 **({"note": it["note"]} if it.get("note") else {})}
        done.append(f)
    _mirror(p, spec)
    return done


def rename(phys, renames):
    """规格改名：实物数据跟着改名。"""
    if not isinstance(phys, dict) or not renames:
        return phys
    return {renames.get(k, k): v for k, v in phys.items()}
