"""AI 打印建议 + 产品描述。

输入：产品信息、3D 模型几何分析（尺寸、6 个摆放方向的悬空/接触面积）、可选的渲染图和你的提示词。
输出：用途卖点描述（填进①）、建议材质、摆放方向、层高、壁数、填充率/图案、支撑、帽檐、风险与注意事项。
建议里的参数可以一键应用到估算和 OrcaSlicer 自动切片。
"""
import json

from . import ai_copy

MATERIALS = ["PLA", "PETG", "TPU", "ABS", "ASA", "PLA-CF", "PETG-CF", "PA", "PC"]
PATTERNS = ["gyroid", "grid", "cubic", "crosshatch", "rectilinear", "honeycomb", "lightning"]
SUPPORTS = ["none", "tree", "normal"]

SYSTEM = """你是资深 FDM 3D 打印工程师兼电商产品经理。店铺在泰国销售 3D 打印产品，打印机：Bambu Lab P1S、Creality K1 Max、Creality K1C（0.4 喷嘴，可打 PLA/PETG/TPU/ABS/ASA）。
你要根据产品信息、模型几何分析数据（以及可能附带的产品渲染图）给出：
1) 产品描述：用中文写「用途/卖点」，给客户看的角度（用途、使用场景、优点、适合人群、尺寸感受），4-6 条短句，用「；」分隔。
   严禁提到 3D 打印、打印、FDM、层纹、耗材、生产方式等制造相关的词（避免同行模仿）。材质只在特殊材质（TPU 软胶、PETG 耐热等）对用户有意义时写「材质特点」，不写制造方式。
2) 打印建议：材质、摆放方向（必须从给出的 6 个方向 key 里选）、层高、壁数、顶/底层数、填充率与图案、支撑、帽檐(brim)、速度/温度注意点、强度/耐用性说明、风险和后处理。
考虑泰国气候：高温高湿，车内/户外/阳光直射的产品不要推荐 PLA（会软化变形），优先 PETG/ASA；需要弹性/防滑用 TPU；要尽量少支撑、底面接触面积足够、外观面朝上或朝外。
摆放方向选择要结合几何数据：overhang_cm2 越小越少支撑，contact_cm2 太小容易倒，height_mm 越高越慢。外观要求高的面不要朝下贴平台（会有支撑痕迹）。
只输出 JSON，不要其他文字。所有给人看的说明都同时给中文(zh)和泰文(th)，泰文要自然、简短，给泰国员工看。"""

USER_TMPL = """产品信息：
- 名称：{name}
- 现有用途/卖点：{features}
- 当前材质：{material}
- 尺寸（宽×深×高 mm）：{size}
- 体积：{volume} cm³，表面积：{surface} cm²，估算重量：{grams} g
- 细高（高度/最小底边 > 3）：{tall_thin}
6 个摆放方向的几何分析（overhang_cm2=超过45°悬空面积，steep_cm2=30-45°陡峭面，contact_cm2=底面贴平台面积，height_mm=打印高度，score 越低越好，仅供参考）：
{orients}
程序初选方向：{best}
用户补充要求：{prompt}

输出 JSON 格式：
{{
  "product_guess": {{"zh": "你认为这是什么产品（一句话）", "th": "..."}},
  "features_zh": "用途；场景；优点；适合人群；尺寸感受",
  "name_zh_suggest": "如果现有名称为空或不清楚，给一个简短中文产品名，否则空字符串",
  "material": {{"pick": "PLA/PETG/TPU/ABS/ASA 等", "why": {{"zh": "...", "th": "..."}}, "alternatives": ["PETG"]}},
  "orientation": {{"pick": "bottom/top/front/back/left/right 之一", "why": {{"zh": "...", "th": "..."}}}},
  "layer_height_mm": 0.2,
  "walls": 2,
  "top_bottom_layers": 4,
  "infill_pct": 15,
  "infill_pattern": "gyroid/grid/cubic/crosshatch/rectilinear/honeycomb/lightning 之一",
  "supports": "none/tree/normal 之一",
  "support_why": {{"zh": "...", "th": "..."}},
  "brim": false,
  "settings_why": {{"zh": "层高/壁数/填充为什么这样设（一两句）", "th": "..."}},
  "temp_speed": {{"zh": "温度、速度、风扇、热床等注意点", "th": "..."}},
  "strength": {{"zh": "强度、耐热、耐用性说明（对客户和对生产）", "th": "..."}},
  "risks": [{{"zh": "可能出现的问题和预防方法", "th": "..."}}],
  "post_process": [{{"zh": "后处理（去支撑、打磨、检查等）", "th": "..."}}],
  "quality_tips": [{{"zh": "提升外观/质量的小技巧", "th": "..."}}]
}}"""


def _num(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _bi(x):
    if isinstance(x, dict):
        return {"zh": str(x.get("zh") or ""), "th": str(x.get("th") or "")}
    return {"zh": str(x or ""), "th": ""}


def normalize(d, analysis):
    keys = [o["key"] for o in (analysis or {}).get("orientations", [])] or ["bottom"]
    m = d.get("material") or {}
    o = d.get("orientation") or {}
    mat = str(m.get("pick") or "PLA").upper().strip()
    out = {
        "product_guess": _bi(d.get("product_guess")),
        "features_zh": str(d.get("features_zh") or "").strip(),
        "name_zh_suggest": str(d.get("name_zh_suggest") or "").strip(),
        "material": {"pick": mat if mat in MATERIALS else "PLA", "why": _bi(m.get("why")),
                     "alternatives": [str(x).upper() for x in (m.get("alternatives") or []) if str(x).upper() in MATERIALS][:3]},
        "orientation": {"pick": o.get("pick") if o.get("pick") in keys else (analysis or {}).get("best", "bottom"),
                        "why": _bi(o.get("why"))},
        "layer_height_mm": round(_num(d.get("layer_height_mm"), 0.08, 0.32, 0.2), 2),
        "walls": int(_num(d.get("walls"), 1, 8, 2)),
        "top_bottom_layers": int(_num(d.get("top_bottom_layers"), 2, 10, 4)),
        "infill_pct": int(_num(d.get("infill_pct"), 0, 100, 15)),
        "infill_pattern": d.get("infill_pattern") if d.get("infill_pattern") in PATTERNS else "gyroid",
        "supports": d.get("supports") if d.get("supports") in SUPPORTS else "none",
        "support_why": _bi(d.get("support_why")),
        "brim": bool(d.get("brim")),
        "settings_why": _bi(d.get("settings_why")),
        "temp_speed": _bi(d.get("temp_speed")),
        "strength": _bi(d.get("strength")),
        "risks": [_bi(x) for x in (d.get("risks") or [])][:6],
        "post_process": [_bi(x) for x in (d.get("post_process") or [])][:6],
        "quality_tips": [_bi(x) for x in (d.get("quality_tips") or [])][:6],
    }
    if ai_copy.mentions_process(out["features_zh"]):
        out["features_warning"] = True
    return out


def advise(cfg, product, analysis, prompt="", image_b64=None):
    a = analysis or {}
    orients = "\n".join(
        f"- {o['key']}（{o['label']}）：overhang_cm2={o['overhang_cm2']}，steep_cm2={o['steep_cm2']}，"
        f"contact_cm2={o['contact_cm2']}，height_mm={o['height_mm']}，score={o['score']}"
        for o in a.get("orientations", [])) or "（没有 3D 模型，无几何数据，请根据产品信息判断，方向填 bottom）"
    est = ((product.get("model") or {}).get("estimate") or {})
    grams = est.get("grams") or (product.get("variants") or [{}])[0].get("grams") or "-"
    user = USER_TMPL.format(
        name=product.get("name_zh") or "（未填写）",
        features=product.get("features_zh") or "（未填写）",
        material=product.get("material") or "PLA",
        size=" × ".join(str(x) for x in (a.get("size_mm") or [])) or product.get("size_text") or "-",
        volume=est.get("volume_cm3", "-"), surface=a.get("surface_cm2", "-"), grams=grams,
        tall_thin="是" if a.get("tall_thin") else "否",
        orients=orients, best=a.get("best", "bottom"), prompt=prompt or "（无）",
    )
    data = ai_copy.extract_json(ai_copy.call(cfg, SYSTEM, user, image_b64))
    return normalize(data, a)


def slice_overrides(advice):
    """把建议转成 OrcaSlicer 工艺参数。"""
    if not advice:
        return {}
    sup = advice.get("supports", "none")
    o = {
        "layer_height": str(advice.get("layer_height_mm", 0.2)),
        "wall_loops": str(advice.get("walls", 2)),
        "top_shell_layers": str(advice.get("top_bottom_layers", 4)),
        "bottom_shell_layers": str(advice.get("top_bottom_layers", 4)),
        "sparse_infill_density": f"{advice.get('infill_pct', 15)}%",
        "sparse_infill_pattern": advice.get("infill_pattern", "gyroid"),
        "enable_support": "0" if sup == "none" else "1",
        "brim_type": "auto_brim" if advice.get("brim") else "no_brim",
    }
    if sup != "none":
        o["support_type"] = "tree(auto)" if sup == "tree" else "normal(auto)"
    return o


def to_json(advice):
    return json.dumps(advice, ensure_ascii=False)
