"""场景图：背景库（内置 + 自己上传的照片）和 AI 生成场景图。

1. 背景合成（免费）：浏览器里把产品透明图放到背景照片上，可拖动、缩放、加阴影。
   内置背景在 static/scenes；自己拍的背景（书桌、书架、床头柜、客厅…）上传后存在 data/scenes。
2. AI 场景图（需要图片 AI 的 Key，按张收费）：把产品图交给图片模型，生成真实使用场景。
   支持 OpenAI（gpt-image-1，images/edits 接口，也兼容同格式的第三方接口）和 Google Gemini（图片模型）。
"""
import base64
import io
import json
import os
import re
import uuid

import requests
from PIL import Image

from .config import BASE_DIR, DATA_DIR

BUILTIN_DIR = os.path.join(BASE_DIR, "static", "scenes")
USER_DIR = os.path.join(DATA_DIR, "scenes")

# 预设场景（AI 提示词用英文更稳定）
PRESETS = {
    "desk": ("书桌/办公桌", "on a tidy modern home-office desk next to a laptop and a coffee mug, soft daylight from a window"),
    "living": ("客厅", "on a wooden coffee table in a cozy modern living room with a sofa and plants softly blurred in the background"),
    "bedroom": ("卧室床头", "on a bedside nightstand in a calm minimalist bedroom with warm lamp light"),
    "shelf": ("书架/置物架", "on a styled bookshelf with books and small decor items, warm natural light"),
    "kitchen": ("厨房", "on a clean kitchen countertop with a few cooking utensils blurred behind, bright daylight"),
    "bathroom": ("浴室", "on a bathroom vanity counter next to a sink with towels, bright clean light"),
    "car": ("车内", "inside a modern car on the dashboard / center console area, daylight through the windshield"),
    "outdoor": ("户外/花园", "outdoors on a garden table with greenery and soft sunlight, Thai tropical feeling"),
    "kids": ("儿童房", "in a bright colorful kids room on a small play table with toys softly blurred"),
    "gift": ("礼物/节日", "as a gift on a table with wrapping paper, ribbon and festive decorations, warm bokeh lights"),
    "hand": ("手持展示", "held in a person's hand to show its real size, neutral background, natural light"),
    "cafe": ("咖啡店/店铺", "on a counter in a stylish small cafe or shop, warm ambient light"),
}


# 电商常用的「空背景」（没有产品，中间留出摆放位置）。AI 只生成一次，存进背景库，所有产品都能用。
BG_PRESETS = {
    "desk_wood": ("木质书桌", "a clean light-oak wooden desk top in a bright modern home office, a laptop, notebook and small plant softly blurred in the background, soft natural window light from the left"),
    "desk_white": ("白色办公桌", "a clean white desk top in a minimalist Scandinavian workspace, monitor and pen holder softly blurred in the background, bright daylight"),
    "coffee_table": ("客厅茶几", "a wooden coffee table top in a cozy modern living room, sofa, cushions and green plant softly blurred behind, warm afternoon light"),
    "nightstand": ("卧室床头柜", "a bedside nightstand top in a calm minimalist bedroom, bed with linen sheets and a warm lamp softly blurred behind"),
    "shelf": ("书架/置物架", "an empty wooden wall shelf with a few books and a small vase pushed to the far sides, warm natural light, neutral wall"),
    "kitchen": ("厨房台面", "a clean white marble kitchen countertop, kitchen utensils and plants softly blurred in the background, bright daylight"),
    "bathroom": ("浴室台面", "a clean bathroom vanity countertop, round mirror, towels and plant softly blurred behind, bright clean light"),
    "cafe": ("咖啡店吧台", "a wooden counter in a stylish small cafe, coffee machine and warm pendant lights softly blurred behind"),
    "garden": ("户外/花园", "a wooden outdoor table in a tropical Thai garden, green leaves and soft sunlight bokeh behind"),
    "kids": ("儿童房", "a small white play table in a bright pastel kids room, soft toys and colorful decor softly blurred behind"),
    "gift": ("礼物/节日", "a table with gift boxes, ribbons and warm festive fairy-light bokeh, the gifts placed at the sides"),
    "car": ("车内中控台", "the flat dashboard area of a modern car interior in daylight, windshield view softly blurred"),
    "studio_light": ("浅色简约台", "a minimal light beige surface against a soft neutral wall with a gentle natural window shadow pattern, clean e-commerce product photography backdrop"),
}
BG_SUFFIX = (" The surface is completely EMPTY in the lower center area (nothing placed there) so a small product can be added "
             "later; the surface occupies roughly the lower 35-40% of the frame; camera at a slightly elevated eye level, "
             "photorealistic, professional e-commerce lifestyle photography, shallow depth of field, no people, no text, "
             "no logos, square 1:1.")


DEFAULT_MODEL = {"openai": "gpt-image-1-mini", "gemini": "gemini-3.1-flash-lite-image"}


class SceneError(Exception):
    pass


def _builtin_meta():
    path = os.path.join(BUILTIN_DIR, "scenes.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _user_meta_path():
    return os.path.join(USER_DIR, "scenes.json")


def _user_meta():
    try:
        with open(_user_meta_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save_user_meta(items):
    os.makedirs(USER_DIR, exist_ok=True)
    with open(_user_meta_path(), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)


def library():
    out = [{**m, "url": f"/static/scenes/{m['id']}", "builtin": True} for m in _builtin_meta()]
    for m in _user_meta():
        if os.path.exists(os.path.join(USER_DIR, m["id"])):
            out.append({**m, "url": f"/scenes/{m['id']}", "builtin": False})
    return out


def add_user(file_storage, name=""):
    """上传自己的背景照片：裁成 1:1、1200px。"""
    try:
        img = Image.open(file_storage.stream)
        img = img.convert("RGB")
    except Exception as e:
        raise SceneError(f"图片读取失败：{e}") from e
    w, h = img.size
    s = min(w, h)
    img = img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)).resize((1200, 1200), Image.LANCZOS)
    os.makedirs(USER_DIR, exist_ok=True)
    sid = f"u_{uuid.uuid4().hex[:10]}.jpg"
    img.save(os.path.join(USER_DIR, sid), "JPEG", quality=90)
    items = _user_meta()
    base = os.path.splitext(name or "")[0][:30] or f"我的背景 {len(items) + 1}"
    items.append({"id": sid, "name": base, "floor_y": 0.78, "scale": 0.42})
    _save_user_meta(items)
    return sid


def update_user(sid, **kw):
    items = _user_meta()
    for m in items:
        if m["id"] == sid:
            for k in ("floor_y", "scale", "name"):
                if k in kw and kw[k] is not None:
                    m[k] = kw[k]
    _save_user_meta(items)


def delete_user(sid):
    if not re.fullmatch(r"u_[0-9a-f]{10}\.jpg", sid or ""):
        raise SceneError("只能删除自己上传的背景")
    items = [m for m in _user_meta() if m["id"] != sid]
    _save_user_meta(items)
    try:
        os.remove(os.path.join(USER_DIR, sid))
    except OSError:
        pass


# ---------------- AI 场景图 ----------------
def build_prompt(product, scene_key, extra=""):
    size = ((product.get("model") or {}).get("metrics") or {}).get("size")
    name = (product.get("copy") or {}).get("title_en") or product.get("name_zh") or "the product"
    scene = PRESETS.get(scene_key, ("", scene_key))[1]
    size_txt = f" Its real size is about {size[0]:.0f} x {size[1]:.0f} x {size[2]:.0f} mm (W x D x H), so keep it at a realistic scale relative to the surroundings." if size else ""
    return (
        f"Professional e-commerce lifestyle photo. Place THIS EXACT product from the input image ({name}) {scene}.{size_txt} "
        "Keep the product's shape, proportions, colors and details exactly the same as the input image; do not redesign it, "
        "do not add any text, logos, watermarks or extra copies of the product. Photorealistic, natural lighting and soft "
        "realistic shadow where the product touches the surface, shallow depth of field, the product is the clear hero in "
        "the center, square 1:1 composition." + (f" Additional requirements: {extra}" if extra else "")
    )


def _png_b64_to_bytes(b64):
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    return base64.b64decode(b64)


def _openai(cfg, prompt, png_bytes):
    key = (cfg.get("image_api_key") or "").strip()
    base = (cfg.get("image_api_base") or "https://api.openai.com/v1").rstrip("/")
    model = cfg.get("image_model") or DEFAULT_MODEL["openai"]
    data = {"model": model, "prompt": prompt, "size": "1024x1024", "n": "1"}
    if cfg.get("image_quality"):
        data["quality"] = cfg["image_quality"]
    if "gpt-image" in model:
        data["input_fidelity"] = "high"
    r = requests.post(f"{base}/images/edits", headers={"Authorization": f"Bearer {key}"},
                      files={"image": ("product.png", png_bytes, "image/png")}, data=data, timeout=240)
    if r.status_code != 200 and "input_fidelity" in r.text:
        data.pop("input_fidelity", None)
        r = requests.post(f"{base}/images/edits", headers={"Authorization": f"Bearer {key}"},
                          files={"image": ("product.png", png_bytes, "image/png")}, data=data, timeout=240)
    if r.status_code != 200:
        raise SceneError(f"图片 AI 接口错误 {r.status_code}: {r.text[:300]}")
    item = (r.json().get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        return requests.get(item["url"], timeout=120).content
    raise SceneError("图片 AI 没有返回图片")


def _gemini(cfg, prompt, png_bytes):
    key = (cfg.get("image_api_key") or "").strip()
    model = cfg.get("image_model") or DEFAULT_MODEL["gemini"]
    base = (cfg.get("image_api_base") or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    if "openai.com" in base:
        base = "https://generativelanguage.googleapis.com/v1beta"
    parts = [{"text": prompt}]
    if png_bytes:
        parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(png_bytes).decode()}})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}}
    r = requests.post(f"{base}/models/{model}:generateContent", params={"key": key}, json=body, timeout=240)
    if r.status_code != 200:
        raise SceneError(f"图片 AI 接口错误 {r.status_code}: {r.text[:300]}")
    for c in r.json().get("candidates") or []:
        for part in (c.get("content") or {}).get("parts") or []:
            d = part.get("inlineData") or part.get("inline_data")
            if d and d.get("data"):
                return base64.b64decode(d["data"])
    raise SceneError("图片 AI 没有返回图片（可能被安全策略拦截，换个场景或提示词再试）")


def _openai_generate(cfg, prompt):
    key = (cfg.get("image_api_key") or "").strip()
    base = (cfg.get("image_api_base") or "https://api.openai.com/v1").rstrip("/")
    model = cfg.get("image_model") or DEFAULT_MODEL["openai"]
    data = {"model": model, "prompt": prompt, "size": "1024x1024", "n": 1}
    if cfg.get("image_quality"):
        data["quality"] = cfg["image_quality"]
    r = requests.post(f"{base}/images/generations", headers={"Authorization": f"Bearer {key}"}, json=data, timeout=240)
    if r.status_code != 200:
        raise SceneError(f"图片 AI 接口错误 {r.status_code}: {r.text[:300]}")
    item = (r.json().get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        return requests.get(item["url"], timeout=120).content
    raise SceneError("图片 AI 没有返回图片")


def ai_background(cfg, preset, extra=""):
    """AI 生成一张空背景（没有产品），存进背景库。"""
    if not (cfg.get("image_api_key") or "").strip():
        raise SceneError("还没有填写图片 AI 的接口密钥（设置 → 商品与上架 → 场景图 AI）")
    name, desc = BG_PRESETS.get(preset, (preset[:20] or "AI 背景", preset))
    prompt = f"Photorealistic empty product-display background: {desc}.{BG_SUFFIX}" + (f" Additional: {extra}" if extra else "")
    provider = cfg.get("image_provider") or "openai"
    raw = _gemini(cfg, prompt, None) if provider == "gemini" else _openai_generate(cfg, prompt)
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        raise SceneError(f"图片 AI 返回的图片无法读取：{e}") from e
    w, h = img.size
    s0 = min(w, h)
    img = img.crop(((w - s0) // 2, (h - s0) // 2, (w - s0) // 2 + s0, (h - s0) // 2 + s0)).resize((1200, 1200), Image.LANCZOS)
    os.makedirs(USER_DIR, exist_ok=True)
    sid = f"u_{uuid.uuid4().hex[:10]}.jpg"
    img.save(os.path.join(USER_DIR, sid), "JPEG", quality=90)
    items = _user_meta()
    items.append({"id": sid, "name": name + " · AI", "floor_y": 0.80, "scale": 0.40, "ai": True})
    _save_user_meta(items)
    return sid


def ai_generate(cfg, product, scene_key, product_png_b64, extra=""):
    if not (cfg.get("image_api_key") or "").strip():
        raise SceneError("还没有填写图片 AI 的接口密钥（设置 → 商品与上架 → 场景图 AI）")
    png = _png_b64_to_bytes(product_png_b64)
    prompt = build_prompt(product, scene_key, extra)
    provider = cfg.get("image_provider") or "openai"
    raw = _gemini(cfg, prompt, png) if provider == "gemini" else _openai(cfg, prompt, png)
    try:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception as e:
        raise SceneError(f"图片 AI 返回的图片无法读取：{e}") from e
    return img, prompt
