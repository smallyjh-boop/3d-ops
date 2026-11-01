"""打印方案（每个产品一份）+ 按方案切片 + 切片报告 + 自动检查。

打印方案：摆放方向、支撑、层高、壁数、顶底层、填充、帽檐、热床板、一盘几个、材料、注意事项。
切片时：程序先把模型转到选定的方向（不让切片软件自己乱转），按数量复制、自动排版，再用方案参数切片。
切片报告：每盘克数、时长、层数、支撑用料占比、有没有超出热床、排版预览（第一层俯视图）。
自动检查：按规则先检查一遍（支撑太多、底面太小容易倒、超出热床、单盘太久等），
          有 AI 接口时再让 AI 复核；最后必须由人确认（复核）才能用于生产。
"""
import glob
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from . import mesh, slicer
from .config import load_config

BED_TYPES = {"auto": "自动（按打印机默认）", "textured": "纹理 PEI 板", "smooth": "光面 PEI 板 / 高温板",
             "cool": "低温板（Cool Plate）", "engineering": "工程板"}
BED_ORCA = {"textured": "Textured PEI Plate", "smooth": "High Temp Plate", "cool": "Cool Plate",
            "engineering": "Engineering Plate"}
SUPPORT_ZH = {"none": "不要支撑", "tree": "树状支撑", "normal": "普通支撑"}
DEFAULT = {"orientation": "bottom", "supports": "none", "support_build_plate_only": True, "support_angle": 30,
           "layer_height": 0.2, "walls": 2, "top_bottom": 4, "infill_pct": 15, "infill_pattern": "gyroid", "brim": False,
           "bed_type": "auto", "per_plate": 1, "gap_mm": 6, "notes": "", "nozzle_temp": 0, "bed_temp": 0, "filament": {}}
MATERIALS = ["PLA", "PETG", "TPU", "ABS", "ASA", "PLA-CF", "PETG-CF", "PA", "PC",
             "RESIN", "RESIN-ABS", "RESIN-WASH", "RESIN-TOUGH", "RESIN-8K"]   # RESIN* = 光固化树脂
# 各材料合理的喷嘴温度范围（超出提醒）
TEMP_RANGE = {"PLA": (190, 235), "PETG": (220, 265), "TPU": (200, 250), "ABS": (230, 280), "ASA": (230, 280),
              "PLA-CF": (200, 240), "PETG-CF": (230, 270), "PA": (250, 300), "PC": (250, 310)}
BED_TEMP_KEYS = {"cool": "cool_plate_temp", "engineering": "eng_plate_temp", "smooth": "hot_plate_temp",
                 "textured": "textured_plate_temp"}


def get(product):
    """产品的打印方案；还没有时用 AI 打印建议或默认值生成一份草稿。"""
    r = dict(DEFAULT)
    adv = product.get("print_advice") or {}
    if adv and not product.get("recipe"):
        r.update(orientation=(adv.get("orientation") or {}).get("pick") or "bottom", supports=adv.get("supports") or "none",
                 layer_height=adv.get("layer_height_mm") or 0.2, walls=adv.get("walls") or 2,
                 top_bottom=adv.get("top_bottom_layers") or 4, infill_pct=adv.get("infill_pct") or 15,
                 infill_pattern=adv.get("infill_pattern") or "gyroid", brim=bool(adv.get("brim")), from_ai=True)
    r.update(product.get("recipe") or {})
    _from_plan(product, r)
    return r


PLAN_KEYS = ("supports", "support_build_plate_only", "support_angle", "walls", "top_bottom", "infill_pct", "infill_pattern",
             "brim", "bed_type", "gap_mm", "nozzle_temp", "bed_temp", "filament", "notes")


def _from_plan(product, r):
    """v2.55：打印参数在打印方案（print_plans[规格] 每一盘的 params）里编辑，这里按第 1 盘取（老的调用照旧能用）。
    只认 v2.55 以后保存过的方案（盘里有 params）；摆放方向只在第 1 盘只放这个模型文件（整个文件）时才跟方案走。"""
    plans = product.get("print_plans")
    if not isinstance(plans, dict):
        return r
    plan = plans.get(product.get("_spec") or "") or {}
    if plan.get("follow") or plan.get("default"):
        return r
    pl = (plan.get("plates") or [None])[0]
    if not isinstance(pl, dict) or not isinstance(pl.get("params"), dict):
        return r
    for k in PLAN_KEYS:
        if k in pl["params"]:
            r[k] = pl["params"][k]
    try:
        r["layer_height"] = round(min(0.32, max(0.08, float(pl.get("layer_height") or r["layer_height"]))), 2)
    except (TypeError, ValueError):
        pass
    lid = (product.get("model") or {}).get("lib_id")
    its = pl.get("items") or []
    if lid and its and all(it.get("id") == lid and it.get("part") in (None, "") for it in its) and not it_face(its[0]) \
            and its[0].get("orient") in mesh.ORIENT_ZH:
        r["orientation"] = its[0]["orient"]
    return r


def it_face(it):
    f = (it or {}).get("face")
    return isinstance(f, (list, tuple)) and len(f) == 3


def clean(data):
    r = dict(DEFAULT)

    def num(k, lo, hi, cast=float):
        try:
            return cast(max(lo, min(hi, float(data.get(k)))))
        except (TypeError, ValueError):
            return DEFAULT[k]
    r.update(orientation=data.get("orientation") if data.get("orientation") in mesh.ORIENT_ZH else "bottom",
             supports=data.get("supports") if data.get("supports") in SUPPORT_ZH else "none",
             support_build_plate_only=bool(data.get("support_build_plate_only", True)),
             layer_height=round(num("layer_height", 0.08, 0.32), 2), walls=num("walls", 1, 8, int),
             top_bottom=num("top_bottom", 2, 10, int), infill_pct=num("infill_pct", 0, 100, int),
             infill_pattern=str(data.get("infill_pattern") or "gyroid"), brim=bool(data.get("brim")),
             bed_type=data.get("bed_type") if data.get("bed_type") in BED_TYPES else "auto",
             per_plate=num("per_plate", 1, 200, int), gap_mm=num("gap_mm", 2, 30), notes=str(data.get("notes") or "")[:500],
             support_angle=num("support_angle", 10, 80, int), nozzle_temp=num("nozzle_temp", 0, 320, int),
             bed_temp=num("bed_temp", 0, 120, int))
    if r["nozzle_temp"] and r["nozzle_temp"] < 150:
        r["nozzle_temp"] = 0
    fil = data.get("filament") if isinstance(data.get("filament"), dict) else {}
    r["filament"] = {str(k)[:80]: str(v)[:200] for k, v in fil.items() if v}
    return r


def norm_material(m):
    m = str(m or "PLA").upper().replace(" ", "").replace("_", "-")
    if "树脂" in m or m in ("SLA", "LCD", "MSLA"):
        return "RESIN"
    return {"PLA+": "PLA", "PLAPLUS": "PLA", "PETG+": "PETG", "PA6": "PA", "NYLON": "PA"}.get(m, m)


def same_material(a, b):
    """材料是否一致：完全一样 → "same"；只是同一大类（PLA / PLA-CF）→ "close"；不一样 → "diff"。"""
    a, b = norm_material(a), norm_material(b)
    if a == b:
        return "same"
    if a.split("-")[0] == b.split("-")[0]:
        return "close"
    return "diff"


def filament_overrides(r):
    """方案里改了温度时，写进耗材配置。"""
    o = {}
    if r.get("nozzle_temp"):
        o["nozzle_temperature"] = [str(r["nozzle_temp"])]
        o["nozzle_temperature_initial_layer"] = [str(r["nozzle_temp"])]
    if r.get("bed_temp"):
        for k in ("cool_plate_temp", "eng_plate_temp", "hot_plate_temp", "textured_plate_temp", "supertack_plate_temp"):
            o[k] = [str(r["bed_temp"])]
            o[k + "_initial_layer"] = [str(r["bed_temp"])]
    return o or None


def filament_for(recipe, printer_name):
    return ((recipe or {}).get("filament") or {}).get(printer_name or "") or ""


def _first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def setup_info(product, recipe, printer_idx):
    """切片前：这台打印机会用哪套配置、什么温度（不切片，只读配置）。没有 OrcaSlicer 时返回 None。"""
    from . import orca_profiles as op
    cfg = load_config()
    names = [x.get("name") for x in cfg.get("printers") or []]
    material = product.get("material") or "PLA"
    chosen = filament_for(recipe, names[printer_idx])
    notes = []
    try:
        _exe, idx, machine, process, filament = slicer.resolve_profiles(cfg, printer_idx, material, chosen, notes, strict=False)
        fc = op.flatten(idx, filament, "filament")
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    # v2.55：「和材料是否一致」按用户选的配置算（选错了的会在切片时被换掉，换上去的那个当然一致，不能拿它来显示）
    chosen_type = op.filament_type(idx, chosen) if chosen else ""
    if chosen and chosen_type and same_material(chosen_type, material) == "diff":
        notes.insert(0, {"zh": "选的耗材配置和材料不一致，切片时会自动换", "th": "โปรไฟล์ฟิลาเมนต์ที่เลือกไม่ตรงกับวัสดุ ตอนสไลซ์จะเปลี่ยนให้อัตโนมัติ",
                         "level": "warn"})
    bt = recipe.get("bed_type") if recipe.get("bed_type") in BED_TEMP_KEYS else None
    bed_key = BED_TEMP_KEYS.get(bt or "textured")
    ftype = _first(fc.get("filament_type")) or ""
    final_match = same_material(ftype, material) if ftype else None
    return {"machine": machine, "process": process, "filament": filament, "filament_type": ftype,
            "chosen": chosen, "chosen_type": chosen_type, "warnings": notes,
            "nozzle_temp": recipe.get("nozzle_temp") or _num(_first(fc.get("nozzle_temperature"))),
            "bed_temp": recipe.get("bed_temp") or _num(_first(fc.get(bed_key)) or _first(fc.get("hot_plate_temp"))),
            "temp_custom": bool(recipe.get("nozzle_temp") or recipe.get("bed_temp")),
            "material_match": (same_material(chosen_type, material) if chosen_type else final_match) if chosen else final_match,
            "final_match": final_match,
            "auto": not filament_for(recipe, names[printer_idx])}


def filament_choices(printer_idx, material):
    """这台打印机可选的耗材配置（按材料筛选，用户自己的配置排前面）。"""
    from . import orca_profiles as op
    cfg = load_config()
    try:
        exe, idx, machine, _process, auto = slicer.resolve_profiles(cfg, printer_idx, material, strict=False)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "items": []}
    mat = norm_material(material)
    items = []
    for n in op.filaments_for(idx, machine):
        e = op._lookup(idx, n)
        ft = (e or {}).get("ftype")
        if not ft:
            try:
                ft = _first(op.flatten(idx, n, "filament").get("filament_type"))
            except Exception:  # noqa: BLE001
                ft = None
        if ft and same_material(ft, mat) == "same":
            items.append({"name": n, "type": ft, "user": (e or {}).get("src") == "user"})
        if len(items) >= 80:
            break
    items.sort(key=lambda x: (0 if x["user"] else 1, 0 if x["name"] == auto else 1, x["name"]))
    return {"auto": auto, "items": items, "machine": machine}


def _num(v):
    try:
        return round(float(str(v).strip().rstrip("%")), 2)
    except (TypeError, ValueError):
        return None


# ---------------- 切片文件里的实际参数 ----------------
PARAM_KEYS = ["filament_type", "filament_settings_id", "filament_colour", "filament_vendor", "print_settings_id",
              "printer_settings_id", "printer_model", "nozzle_diameter", "nozzle_temperature",
              "nozzle_temperature_initial_layer", "curr_bed_type", "hot_plate_temp", "textured_plate_temp", "cool_plate_temp",
              "eng_plate_temp", "layer_height", "initial_layer_print_height", "wall_loops", "top_shell_layers",
              "bottom_shell_layers", "sparse_infill_density", "sparse_infill_pattern", "enable_support", "support_type",
              "support_threshold_angle", "support_on_build_plate_only", "brim_type", "brim_width", "outer_wall_speed",
              "inner_wall_speed", "sparse_infill_speed", "enable_prime_tower", "seam_position", "skirt_loops",
              # Bambu Studio / PrusaSlicer 的旧名字
              "wall_count", "perimeters", "fill_density", "fill_pattern", "support_material", "temperature", "bed_temperature",
              "filament_settings_id", "first_layer_temperature", "curr_bed_type"]
BED_NAME_KEY = {"cool plate": "cool_plate_temp", "engineering plate": "eng_plate_temp", "high temp plate": "hot_plate_temp",
                "textured pei plate": "textured_plate_temp", "smooth pei plate": "hot_plate_temp"}
BED_NAME_ZH = {"cool plate": "低温板", "engineering plate": "工程板", "high temp plate": "高温板 / 光面 PEI",
               "textured pei plate": "纹理 PEI 板", "smooth pei plate": "光面 PEI 板", "supertack plate": "超粘板"}


def _gcode_config(text):
    """G-code 末尾的配置块（; key = value）。"""
    out = {}
    tail = text[-300000:] + "\n" + text[:60000]
    for m in re.finditer(r"^;\s*([a-z_][a-z0-9_]*)\s*=\s*(.*)$", tail, re.M):
        k, v = m.group(1), m.group(2).strip()
        if k in PARAM_KEYS and k not in out:
            out[k] = v.split(";") if k.startswith(("filament_", "nozzle_", "temperature", "first_layer_temp")) or \
                k.endswith("plate_temp") or k == "bed_temperature" else v
    return out


def params_from(path_or_text, kind="3mf"):
    """读切片文件里实际用的参数（材料、温度、层高、支撑…），给人工核对。"""
    raw = {}
    try:
        if kind == "3mf":
            with zipfile.ZipFile(path_or_text) as z:
                names = z.namelist()
                if "Metadata/project_settings.config" in names:
                    d = json.loads(z.read("Metadata/project_settings.config"))
                    raw = {k: d[k] for k in PARAM_KEYS if k in d}
                if not raw.get("filament_type"):
                    g = next((n for n in names if n.startswith("Metadata/plate_") and n.endswith(".gcode")), None)
                    if g:
                        raw = {**_gcode_config(z.read(g).decode("utf-8", "ignore")), **raw}
        else:
            text = path_or_text if isinstance(path_or_text, str) and "\n" in path_or_text else \
                open(path_or_text, "rb").read().decode("utf-8", "ignore")
            raw = _gcode_config(text)
    except Exception:  # noqa: BLE001
        return {}
    if not raw:
        return {}
    f = _first
    bed_name = str(raw.get("curr_bed_type") or "")
    bed_key = BED_NAME_KEY.get(bed_name.lower())
    nozzle_t = _num(f(raw.get("nozzle_temperature")) or f(raw.get("temperature")))
    bed_t = _num(f(raw.get(bed_key)) if bed_key else None) or _num(f(raw.get("bed_temperature")))
    sup = raw.get("enable_support", raw.get("support_material"))
    walls = raw.get("wall_loops", raw.get("wall_count", raw.get("perimeters")))
    return {
        "material": str(f(raw.get("filament_type")) or "").upper() or None,
        "filament": f(raw.get("filament_settings_id")),
        "color_hex": f(raw.get("filament_colour")),
        "printer_profile": raw.get("printer_settings_id") or raw.get("printer_model"),
        "process_profile": raw.get("print_settings_id"),
        "nozzle_mm": _num(f(raw.get("nozzle_diameter"))),
        "nozzle_temp": nozzle_t,
        "nozzle_temp_first": _num(f(raw.get("nozzle_temperature_initial_layer")) or f(raw.get("first_layer_temperature"))),
        "bed_type": bed_name or None,
        "bed_type_zh": BED_NAME_ZH.get(bed_name.lower(), bed_name) if bed_name else None,
        "bed_temp": bed_t,
        "layer_height": _num(raw.get("layer_height")),
        "first_layer": _num(raw.get("initial_layer_print_height")),
        "walls": int(_num(walls)) if _num(walls) is not None else None,
        "top_layers": int(_num(raw.get("top_shell_layers"))) if _num(raw.get("top_shell_layers")) is not None else None,
        "bottom_layers": int(_num(raw.get("bottom_shell_layers"))) if _num(raw.get("bottom_shell_layers")) is not None else None,
        "infill_pct": _num(raw.get("sparse_infill_density", raw.get("fill_density"))),
        "infill_pattern": raw.get("sparse_infill_pattern", raw.get("fill_pattern")),
        "supports": None if sup is None else str(sup).strip() in ("1", "true"),
        "support_type": raw.get("support_type"),
        "support_angle": _num(raw.get("support_threshold_angle")),
        "support_plate_only": None if raw.get("support_on_build_plate_only") is None
        else str(raw.get("support_on_build_plate_only")).strip() in ("1", "true"),
        "brim": None if raw.get("brim_type") is None else raw.get("brim_type") not in ("no_brim", "none", ""),
        "brim_width": _num(raw.get("brim_width")),
        "outer_wall_speed": _num(raw.get("outer_wall_speed")),
        "infill_speed": _num(raw.get("sparse_infill_speed")),
        "prime_tower": None if raw.get("enable_prime_tower") is None else str(raw.get("enable_prime_tower")) in ("1", "true"),
    }


def compare_params(params, recipe, material):
    """切片文件里的实际参数 和 打印方案 / 产品材料 对比。返回 [{level, zh}]。"""
    out = []

    def add(level, zh):
        out.append({"level": level, "zh": zh})
    if not params:
        add("warn", "读不到这个文件的切片参数（材料、温度等），请在切片软件里核对后再复核")
        return out
    fm = params.get("material")
    if fm:
        sm = same_material(fm, material)
        if sm == "diff":
            add("error", f"材料不对：切片文件用的是 {fm}，产品材料是 {norm_material(material)}。请用正确的材料重新切片")
        elif sm == "close":
            add("warn", f"材料不完全一致：切片文件 {fm}，产品材料 {norm_material(material)}，请确认")
    else:
        add("warn", "切片文件里没有写材料类型，请人工确认")
    rng = TEMP_RANGE.get(norm_material(fm or material))
    t = params.get("nozzle_temp")
    if rng and t and not (rng[0] <= t <= rng[1]):
        add("error" if abs(t - sum(rng) / 2) > 40 else "warn",
            f"喷嘴温度 {t:g}°C 不在 {norm_material(fm or material)} 的常用范围（{rng[0]}–{rng[1]}°C），可能用错了耗材配置")
    if recipe and params.get("layer_height") and abs(params["layer_height"] - float(recipe.get("layer_height") or 0)) > 0.005:
        add("warn", f"层高和方案不一致：文件 {params['layer_height']}，方案 {recipe.get('layer_height')}")
    if recipe and params.get("supports") is not None:
        want = recipe.get("supports") != "none"
        if params["supports"] != want:
            add("warn", f"支撑和方案不一致：文件{'有' if params['supports'] else '没有'}支撑，方案是「{SUPPORT_ZH.get(recipe.get('supports'))}」")
    if recipe and params.get("walls") is not None and int(recipe.get("walls") or 0) != params["walls"]:
        add("info", f"壁数和方案不一致：文件 {params['walls']}，方案 {recipe.get('walls')}")
    if recipe and params.get("infill_pct") is not None and abs(params["infill_pct"] - float(recipe.get("infill_pct") or 0)) > 0.5:
        add("info", f"填充率和方案不一致：文件 {params['infill_pct']:g}%，方案 {recipe.get('infill_pct')}%")
    if recipe and recipe.get("bed_type") in BED_ORCA and params.get("bed_type") and \
            params["bed_type"].lower() != BED_ORCA[recipe["bed_type"]].lower():
        add("warn", f"热床板和方案不一致：文件是 {params.get('bed_type_zh')}，方案是 {BED_TYPES[recipe['bed_type']]}")
    if recipe and recipe.get("nozzle_temp") and t and abs(t - recipe["nozzle_temp"]) > 1:
        add("warn", f"喷嘴温度和方案不一致：文件 {t:g}°C，方案 {recipe['nozzle_temp']}°C")
    return out


def overrides(r):
    o = {"layer_height": str(r["layer_height"]), "wall_loops": str(r["walls"]),
         "top_shell_layers": str(r["top_bottom"]), "bottom_shell_layers": str(r["top_bottom"]),
         "sparse_infill_density": f"{r['infill_pct']}%", "sparse_infill_pattern": r["infill_pattern"],
         "enable_support": "0" if r["supports"] == "none" else "1",
         "brim_type": "outer_only" if r["brim"] else "no_brim"}
    if r["supports"] != "none":
        o["support_type"] = "tree(auto)" if r["supports"] == "tree" else "normal(auto)"
        o["support_on_build_plate_only"] = "1" if r.get("support_build_plate_only", True) else "0"
        o["support_threshold_angle"] = str(int(r.get("support_angle") or 30))
    if r.get("bed_type") in BED_ORCA:
        o["curr_bed_type"] = BED_ORCA[r["bed_type"]]
    return o


def summary_zh(r):
    return (f"{mesh.ORIENT_ZH.get(r['orientation'], r['orientation'])} · {SUPPORT_ZH.get(r['supports'])}"
            f"{'（只从热床长）' if r['supports'] != 'none' and r.get('support_build_plate_only', True) else ''} · "
            f"层高 {r['layer_height']} · {r['walls']} 层壁 · 填充 {r['infill_pct']}% {r['infill_pattern']}"
            f"{' · 帽檐' if r['brim'] else ''}{' · ' + BED_TYPES[r['bed_type']] if r.get('bed_type') not in (None, 'auto') else ''}"
            f"{' · 喷嘴 ' + str(r['nozzle_temp']) + '°C' if r.get('nozzle_temp') else ''}"
            f"{' · 热床 ' + str(r['bed_temp']) + '°C' if r.get('bed_temp') else ''}")


# ---------------- 几何 / 一盘能放几个 ----------------
def bed_size(printer_idx):
    """打印机热床尺寸（从 OrcaSlicer 打印机配置读）。"""
    cfg = load_config()
    p = (cfg.get("printers") or [])[printer_idx]
    try:
        from . import orca_profiles as op
        idx = op.build_index(slicer.find_orca(cfg))
        auto = op.auto_match(idx, p.get("name", ""), "PLA")
        machine = (p.get("orca_machine") or "").strip() or auto["orca_machine"]
        conf = op.flatten(idx, machine, "machine") if hasattr(op, "flatten") else {}
        area = conf.get("printable_area") or []
        pts = [tuple(float(v) for v in s.split("x")) for s in area]
        if pts:
            xs, ys = [a for a, _ in pts], [b for _, b in pts]
            return (max(xs) - min(xs), max(ys) - min(ys), float(conf.get("printable_height") or 250))
    except Exception:  # 没有 OrcaSlicer 时按名字猜
        pass
    from . import fleet
    m = fleet.model_info(p.get("name"))
    if m:
        return tuple(float(x) for x in m["bed"])
    return (256.0, 256.0, 250.0)


def _learned(product, printer_idx):
    lc = (product.get("recipe") or {}).get("capacity_learned") or {}
    r = product.get("recipe") or {}
    # v2.7 起按机型记（同机型多台共用）；老数据按序号记的也认
    return lc.get(f"{_pmodel(printer_idx)}:{r.get('orientation')}:{r.get('gap_mm')}") or \
        lc.get(f"{printer_idx}:{r.get('orientation')}:{r.get('gap_mm')}")


def _pmodel(printer_idx):
    prs = load_config().get("printers") or []
    try:
        return prs[int(printer_idx)].get("name") or str(printer_idx)
    except (TypeError, ValueError, IndexError):
        return str(printer_idx)


def _learn_capacity(product, printer_idx, n):
    """记住切片软件实际排得下的数量（按打印机 + 方向 + 间距），下次直接用。规格自己的方案记在规格里（v2.22）。"""
    from . import specmodel
    r = product.get("recipe") or {}
    key = f"{_pmodel(printer_idx)}:{r.get('orientation')}:{r.get('gap_mm')}"
    specmodel.learn_capacity(product, key, n)


def geometry(product, recipe, printer_idx=None):
    from . import specmodel
    mp = specmodel.model_path(product)          # 规格有自己的模型时用规格的（v2.22）
    if not mp:
        return None
    tris = mesh.rotate(mesh.load(mp), recipe["orientation"])
    g = mesh.stats(tris)
    if printer_idx is not None:
        bed = bed_size(printer_idx)
        g["bed_mm"] = bed
        extra = 8 if recipe.get("brim") else 0          # 帽檐占地方
        g["capacity"] = mesh.capacity(g["footprint_mm"], bed, recipe.get("gap_mm", 6) + extra) if g["height_mm"] <= bed[2] else 0
        lc = (product.get("recipe") or {}).get("capacity_learned") or {}
        key = f"{printer_idx}:{recipe.get('orientation')}:{recipe.get('gap_mm')}"
        if g["capacity"] and lc.get(key):
            g["capacity"] = min(g["capacity"], lc[key])
    return g


# ---------------- 检查 ----------------
def check(recipe, geo=None, report=None, material="PLA"):
    """规则检查。返回 [{level: error/warn/info, zh}]"""
    out = []

    def add(level, zh):
        out.append({"level": level, "zh": zh})
    if geo:
        if geo["contact_cm2"] < 1 and not recipe["brim"]:
            add("warn", f"底面贴平台面积只有 {geo['contact_cm2']} cm²，容易翘边或打到一半倒掉，建议开「帽檐」或换个摆放方向")
        if geo["tall_ratio"] > 3 and not recipe["brim"]:
            add("warn", f"细高的零件（高度是底边的 {geo['tall_ratio']} 倍），容易晃动，建议开「帽檐」")
        if geo["overhang_cm2"] > 2 and recipe["supports"] == "none":
            add("warn", f"这个方向有 {geo['overhang_cm2']} cm² 悬空面（超过 45°），不加支撑可能塌，"
                        f"请确认是否需要支撑，或换个方向")
        if geo["overhang_cm2"] < 0.3 and recipe["supports"] != "none":
            add("info", "这个方向几乎没有悬空面，可以试试不要支撑（省料、表面更好）")
        if geo.get("capacity") == 0:
            add("error", "模型比打印机的热床/高度还大，放不下")
        elif geo.get("capacity") and recipe["per_plate"] > geo["capacity"]:
            add("error", f"一盘 {recipe['per_plate']} 个放不下，这台打印机最多约 {geo['capacity']} 个")
    if material.upper() in ("PETG", "TPU", "ABS", "ASA") and recipe.get("bed_type") == "cool":
        add("warn", f"{material} 不适合低温板，建议用纹理 PEI 板")
    if recipe["layer_height"] > 0.28:
        add("info", "层高比较大，打印快但表面层纹明显")
    if report:
        if report.get("outside"):
            add("error", "切片结果有零件超出热床，请减少数量或调整间距")
        sp = report.get("support_pct")
        if sp is not None and sp > 25:
            add("warn", f"支撑用料占 {sp}%，偏多（浪费料、难拆、留痕），建议换方向")
        if report.get("hours_per_plate") and report["hours_per_plate"] > 12:
            add("info", f"一盘要 {report['hours_per_plate']} 小时，时间长失败损失大，可以考虑少放几个分两盘")
        if report.get("support_used") and recipe["supports"] == "none":
            add("warn", "方案是不要支撑，但切片结果用了支撑，请检查")
        if "params" in report:
            out.extend(compare_params(report.get("params"),
                                      recipe if (report.get("from_recipe") or recipe.get("updated_at")) else None, material))
    if not any(x["level"] in ("error", "warn") for x in out):
        add("ok", "规则检查没有发现问题")
    return out


AI_SYS = ("你是资深 FDM 3D 打印工程师。根据打印方案、模型几何数据、切片报告，判断这样打印会不会出问题。"
          "打印机：Bambu Lab P1S、Creality K1 Max、K1C。泰国高温高湿。只输出 JSON。")


def ai_review(cfg, product, recipe, geo, report):
    from . import ai_copy
    user = json.dumps({"产品": product.get("name_zh"), "用途": product.get("features_zh"), "材料": product.get("material"),
                       "打印方案": recipe, "当前方向几何": geo, "切片报告": {k: v for k, v in (report or {}).items()
                                                                          if k not in ("preview", "objects")}},
                      ensure_ascii=False)
    user += ('\n输出：{"ok": true/false, "summary": {"zh": "一句话结论", "th": "..."}, '
             '"issues": [{"zh": "问题和怎么改", "th": "..."}], "check_points": [{"zh": "人工复核时要看的点", "th": "..."}]}')
    d = ai_copy.extract_json(ai_copy.call(ai_copy.tcfg(cfg, "print_advice"), AI_SYS, user))
    bi = (lambda x: {"zh": str((x or {}).get("zh") or ""), "th": str((x or {}).get("th") or "")} if isinstance(x, dict)
          else {"zh": str(x or ""), "th": ""})
    return {"ok": bool(d.get("ok")), "summary": bi(d.get("summary")), "issues": [bi(x) for x in d.get("issues") or []][:6],
            "check_points": [bi(x) for x in d.get("check_points") or []][:6]}


# ---------------- 切片报告 ----------------
def _gcode_report(text):
    rep = {}
    m = re.search(r"; total layer number: (\d+)", text) or re.search(r";\s*(?:total layers count|layer_count)\s*[:=]\s*(\d+)", text)
    if m:
        rep["layers"] = int(m.group(1))
    # 按 FEATURE 统计挤出量，算支撑占比；顺便取第一层的路径做排版预览
    rel = True
    e_last = 0.0
    feat = ""
    by_feat = {}
    layer = 0
    pts, cur = [], []
    x = y = 0.0
    for line in text.splitlines():
        if line.startswith(";"):
            if line.startswith("; FEATURE:") or line.startswith(";TYPE:"):
                feat = line.split(":", 1)[1].strip().lower()
            elif line.startswith(";LAYER_CHANGE") or line.startswith("; CHANGE_LAYER"):
                layer += 1
                if cur:
                    pts.append(cur); cur = []
            continue
        if line.startswith("M83"):
            rel = True
        elif line.startswith("M82"):
            rel = False
        elif line.startswith("G92"):
            m = re.search(r"E([-\d.]+)", line)
            if m:
                e_last = float(m.group(1))
        elif line.startswith(("G1", "G0", "G2", "G3")):
            mx, my, me = re.search(r"X([-\d.]+)", line), re.search(r"Y([-\d.]+)", line), re.search(r"E([-\d.]+)", line)
            nx = float(mx.group(1)) if mx else x
            ny = float(my.group(1)) if my else y
            if me:
                e = float(me.group(1))
                de = e if rel else e - e_last
                if not rel:
                    e_last = e
                if de > 0:
                    by_feat[feat] = by_feat.get(feat, 0) + de
                    if layer == 1 and (mx or my) and len(pts) < 4000:
                        if not cur:
                            cur = [(x, y)]
                        cur.append((nx, ny))
                elif cur and layer == 1:
                    pts.append(cur); cur = []
            elif cur and layer == 1 and (mx or my):
                pts.append(cur); cur = []
            x, y = nx, ny
    if cur:
        pts.append(cur)
    tot = sum(by_feat.values())
    if tot:
        sup = sum(v for k, v in by_feat.items() if "support" in k)
        rep["support_pct"] = round(sup / tot * 100, 1)
    rep["first_layer"] = pts[:1500]
    return rep


def _svg(first_layer, bed, objects):
    """第一层俯视图（排版预览）。"""
    bw, bd = bed[0], bed[1]
    paths = []
    for seg in first_layer:
        if len(seg) < 2:
            continue
        step = max(1, len(seg) // 60)
        s2 = seg[::step] + ([seg[-1]] if (len(seg) - 1) % step else [])
        paths.append("M" + " L".join(f"{p[0]:.1f},{bd - p[1]:.1f}" for p in s2))
    boxes = "".join(f'<rect x="{o[0]:.1f}" y="{bd - o[3]:.1f}" width="{o[2] - o[0]:.1f}" height="{o[3] - o[1]:.1f}" '
                    f'fill="none" stroke="#2563eb" stroke-dasharray="3 2" stroke-width="0.8"/>' for o in objects)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-4 -4 {bw + 8} {bd + 8}">'
            f'<rect x="0" y="0" width="{bw}" height="{bd}" fill="#f8fafc" stroke="#94a3b8" stroke-width="1.2"/>'
            f'<path d="{" ".join(paths)}" fill="none" stroke="#ea580c" stroke-width="0.9" stroke-linejoin="round"/>'
            f'{boxes}</svg>')


def report_from(path_3mf, gcode_text, bed):
    rep = {}
    with zipfile.ZipFile(path_3mf) as z:
        names = z.namelist()
        if "Metadata/slice_info.config" in names:
            si = z.read("Metadata/slice_info.config").decode("utf-8", "ignore")
            g = lambda k: (re.search(rf'key="{k}"\s+value="([^"]*)"', si) or [None, None])[1]  # noqa: E731
            rep["grams_per_plate"] = float(g("weight") or 0) or None
            pred = g("prediction")
            rep["hours_per_plate"] = round(float(pred) / 3600, 2) if pred else None
            rep["support_used"] = g("support_used") == "true"
            rep["outside"] = g("outside") == "true"
            rep["count"] = len(re.findall(r"<object ", si)) or None
        objs = []
        if "Metadata/plate_1.json" in names:
            pj = json.loads(z.read("Metadata/plate_1.json"))
            objs = [o.get("bbox") for o in pj.get("bbox_objects") or [] if o.get("bbox")]
            rep["count"] = rep.get("count") or len(objs)
            rep["bed_type"] = pj.get("bed_type")
    g = _gcode_report(gcode_text)
    if not rep.get("grams_per_plate") or not rep.get("hours_per_plate"):
        st = slicer.parse_gcode_text(gcode_text[:400000] + gcode_text[-400000:]) or {}
        rep["grams_per_plate"] = rep.get("grams_per_plate") or st.get("grams")
        rep["hours_per_plate"] = rep.get("hours_per_plate") or st.get("hours")
    rep["layers"] = g.get("layers")
    rep["support_pct"] = g.get("support_pct")
    rep["preview"] = _svg(g.get("first_layer") or [], bed, objs)
    rep["params"] = params_from(path_3mf, "3mf")
    return rep


# ---------------- 按方案切片 ----------------
TOP_ONLY_INFILL = {"monotonic", "monotonicline"}     # 顶面图案，不能当填充（按 rectilinear 切）


def slice_product(product, printer_idx, count=None, recipe=None, user=""):
    """按打印方案切片：转方向 → 复制 count 个 → 自动排版 → 切片。返回 (切片文件临时路径, 报告, 方案)
    v2.55：报告里带 warnings（[{zh, th}]：耗材配置和材料不一致已自动换、顶面图案当了填充…），同时记进操作日志。"""
    from . import specmodel
    recipe = recipe or get(product)
    pre = []
    ov = overrides(recipe)
    if recipe.get("infill_pattern") in TOP_ONLY_INFILL:
        pat = recipe["infill_pattern"]
        ov["sparse_infill_pattern"] = "rectilinear"
        pre.append({"zh": f"填充图案「{pat}」是顶面图案，不能做填充：按 rectilinear 切。请在打印方案里重新选填充图案",
                    "th": f"รูปแบบเติม「{pat}」เป็นรูปแบบผิวด้านบน ใช้เป็นไส้ในไม่ได้: สไลซ์เป็น rectilinear แทน กรุณาเลือกรูปแบบเติมใหม่"})
    count = int(count or recipe.get("per_plate") or 1)
    mp = specmodel.model_path(product)
    if not mp:
        raise ValueError("这个产品还没有上传 3D 模型，只能上传切片好的文件")
    mc = specmodel.check_auto_slice(product)      # v2.23：多色模型不能自动切
    if mc:
        raise ValueError(mc)
    cfg = load_config()
    geo = geometry(product, recipe, printer_idx)
    if geo.get("capacity") is not None and count > max(1, geo["capacity"]):
        raise ValueError(f"一盘放不下 {count} 个（这台打印机最多约 {geo['capacity']} 个）")
    work = tempfile.mkdtemp(prefix="recipe_")
    try:
        tris = mesh.rotate(mesh.load(mp), recipe["orientation"])
        stl = mesh.write_stl(tris, os.path.join(work, f"{product['id']}.stl"))
        note = ""
        for _try in range(3):
            pname = ((cfg.get("printers") or [])[printer_idx] or {}).get("name", "")
            res = slicer.orca_slice(cfg, stl, printer_idx, product.get("material") or "PLA", overrides=ov,
                                    keep_to=os.path.join(work, "keep.gcode.3mf"), copies=count, orient=False,
                                    filament_name=filament_for(recipe, pname), filament_overrides=filament_overrides(recipe))
            kept = res["kept"]
            with zipfile.ZipFile(kept) as z:
                plates = sorted(n for n in z.namelist() if n.startswith("Metadata/plate_") and n.endswith(".gcode"))
                n1 = None
                if len(plates) > 1 and "Metadata/plate_1.json" in z.namelist():
                    n1 = len(json.loads(z.read("Metadata/plate_1.json")).get("bbox_objects") or [])
            if len(plates) <= 1:
                break
            # 一盘放不下：切片软件自动分成了几盘 → 按第一盘实际放下的数量重新切
            n1 = n1 or max(1, count // len(plates))
            note = f"一盘放不下 {count} 个，这台打印机一盘最多 {n1} 个，已按 {n1} 个切片"
            _learn_capacity(product, printer_idx, n1)
            count = n1
        else:
            raise ValueError("切片软件一直把零件分成几盘，请减少数量")
        with zipfile.ZipFile(kept) as z:
            gname = next((n for n in z.namelist() if n.startswith("Metadata/plate_") and n.endswith(".gcode")), None)
            text = z.read(gname).decode("utf-8", "ignore") if gname else ""
        rep = report_from(kept, text, geo.get("bed_mm") or bed_size(printer_idx))
        rep["count"] = count
        rep["capacity"] = _learned(product, printer_idx) or geo.get("capacity")
        if note:
            rep["note"] = note
        rep["geometry"] = {k: geo[k] for k in ("size_mm", "contact_cm2", "overhang_cm2", "tall_ratio") if k in geo}
        rep["profiles"] = res.get("profiles")
        rep["from_recipe"] = True
        warns = pre + (res.get("warnings") or [])
        rep["warnings"] = warns
        if warns:
            from . import db
            db.audit(user, "按方案切片：耗材配置和材料不一致等，已自动调整", product.get("id") or "", "；".join(w["zh"] for w in warns))
        out = tempfile.NamedTemporaryFile(suffix=".gcode.3mf", delete=False).name
        shutil.copyfile(kept, out)
        return out, rep, recipe
    finally:
        shutil.rmtree(work, ignore_errors=True)
