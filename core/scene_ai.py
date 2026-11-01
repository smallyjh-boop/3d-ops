"""场景图改进（v2.53）：AI 写提示词（看白底产品图）→ 一次出几张候选 → AI 看图质检打分 → 员工挑；
类目模板（泰国家居风格，可以改）、多尺寸（1:1 / 3:4 / 4:3 / 16:9 / 9:16）、批量（后台排队、进度、可取消）、费用（先估再算实际）。

保持真实产品：出图服务商能「参考图改图」时把产品抠图当参考图；不能改图时只生成空场景，再把真实产品抠图贴上去（产品不会走样）。
Claude 等文字 AI 不能出图：它们只写提示词和质检（「系统 → AI 接口」的「场景图提示词」「场景图质检」任务），出图用「场景图」任务的服务商。
"""
import io
import json
import os
import re
import threading
import time
import uuid

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from .config import DATA_DIR

CAND_DIR = os.path.join(DATA_DIR, "scene_cand")
ASPECTS = {"1:1": (1200, 1200), "3:4": (1200, 1600), "4:3": (1600, 1200), "16:9": (1600, 900), "9:16": (900, 1600)}
MAX_N = 6

# 类目模板（泰国常见的家居风格）。cats：类目名 / 品名里有这些词时推荐这个模板。设置里可以改（config: scene_templates）。
DEFAULT_TEMPLATES = [
    {"key": "thai_condo", "zh": "泰式现代公寓", "th": "คอนโดโมเดิร์นแบบไทย",
     "prompt": "on a sleek light-wood sideboard in a modern Bangkok condo living room, warm teak accents, large window with soft city daylight, a potted monstera softly blurred",
     "cats": ["家居", "装饰", "摆件", "收纳", "花瓶", "home", "decor", "vase", "storage"]},
    {"key": "tropical_wood", "zh": "热带木质风", "th": "ไม้สไตล์ทรอปิคอล",
     "prompt": "on a rustic teak wood table in a tropical Thai house, rattan furniture and green palm leaves softly blurred, warm natural sunlight",
     "cats": ["植物", "花盆", "木", "plant", "pot", "wood"]},
    {"key": "minimal_white", "zh": "极简白色", "th": "มินิมอลสีขาว",
     "prompt": "on a clean white surface against a soft off-white wall, minimalist style, gentle diffused daylight and a soft natural shadow",
     "cats": []},
    {"key": "kids_room", "zh": "儿童房", "th": "ห้องเด็ก",
     "prompt": "on a small white play table in a bright pastel Thai kids bedroom, soft toys and colourful decor softly blurred",
     "cats": ["玩具", "儿童", "解压", "toy", "kids", "fidget", "game"]},
    {"key": "desk_office", "zh": "书桌 / 办公", "th": "โต๊ะทำงาน / ออฟฟิศ",
     "prompt": "on a tidy modern home-office desk next to a laptop and a coffee mug, soft window daylight, a Bangkok home office",
     "cats": ["办公", "文具", "手机", "电脑", "键盘", "支架", "office", "stationery", "phone", "desk", "stand", "keycap"]},
    {"key": "outdoor", "zh": "户外 / 花园", "th": "กลางแจ้ง / สวน",
     "prompt": "on a wooden outdoor table in a lush tropical Thai garden, green leaves and soft sunlight bokeh",
     "cats": ["户外", "园艺", "露营", "garden", "outdoor", "camping"]},
    {"key": "kitchen", "zh": "厨房", "th": "ห้องครัว",
     "prompt": "on a clean light marble kitchen countertop in a bright Thai home kitchen, utensils and herbs softly blurred",
     "cats": ["厨房", "餐具", "kitchen", "cup", "tableware"]},
    {"key": "car", "zh": "车内", "th": "ในรถ",
     "prompt": "inside a modern car on the dashboard / center console area, daylight through the windshield",
     "cats": ["汽车", "车载", "car", "auto"]},
]


class SceneAIError(Exception):
    pass


# ---------------- 模板 ----------------
def templates(cfg):
    t = cfg.get("scene_templates")
    if isinstance(t, list) and t:
        return [x for x in t if isinstance(x, dict) and x.get("key")]
    return [dict(x) for x in DEFAULT_TEMPLATES]


def clean_templates(items):
    out, seen = [], set()
    for x in items or []:
        if not isinstance(x, dict):
            continue
        key = re.sub(r"[^a-z0-9_]", "", str(x.get("key") or "").lower())[:30] or "t" + uuid.uuid4().hex[:6]
        if key in seen:
            continue
        seen.add(key)
        cats = x.get("cats")
        if isinstance(cats, str):
            cats = [c.strip() for c in re.split(r"[,，、]", cats) if c.strip()]
        out.append({"key": key, "zh": str(x.get("zh") or key)[:40], "th": str(x.get("th") or x.get("zh") or key)[:60],
                    "prompt": str(x.get("prompt") or "")[:600], "cats": [str(c)[:30] for c in (cats or [])][:30]})
    return out[:40]


def suggest(cfg, product):
    """按类目 / 品名推荐模板（前 3 个）。"""
    cat = product.get("category") or {}
    text = " ".join(str(x or "") for x in (cat.get("name"), cat.get("name_zh"), cat.get("path"), product.get("name_zh"),
                                           (product.get("copy") or {}).get("title_en"))).lower()
    scored = []
    for i, t in enumerate(templates(cfg)):
        hit = sum(1 for c in t.get("cats") or [] if c and c.lower() in text)
        scored.append((-hit, i, t["key"]))
    scored.sort()
    out = [k for h, _i, k in scored if h < 0][:3]
    for k in ("minimal_white", "desk_office", "thai_condo"):
        if len(out) < 3 and k not in out and any(t["key"] == k for t in templates(cfg)):
            out.append(k)
    return out[:3]


def _template(cfg, key):
    for t in templates(cfg):
        if t["key"] == key:
            return t
    from . import scenes
    if key in scenes.PRESETS:
        return {"key": key, "zh": scenes.PRESETS[key][0], "th": scenes.PRESETS[key][0], "prompt": scenes.PRESETS[key][1], "cats": []}
    return {"key": "custom", "zh": "自定义", "th": "กำหนดเอง", "prompt": str(key or "")[:400], "cats": []}


# ---------------- 图片工具 ----------------
def open_rgba(png):
    im = Image.open(io.BytesIO(png)) if isinstance(png, (bytes, bytearray)) else png
    im = im.convert("RGBA")
    return cutout(im)


def cutout(im):
    """产品抠图：已经是透明背景就直接用；白底图从四边把接近白色的连通区域去掉（和编辑页的浏览器抠图同一个办法）。"""
    im = im.convert("RGBA")
    a = im.getchannel("A")
    if a.getextrema()[0] < 250:
        bbox = a.point(lambda v: 255 if v > 8 else 0).getbbox()
        return im.crop(bbox) if bbox else im
    rgb = im.convert("RGB")
    w, h = rgb.size
    key = (255, 0, 254)
    for pt in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)):
        px = rgb.getpixel(pt)
        if min(px) > 225 and px != key:
            ImageDraw.floodfill(rgb, pt, key, thresh=40)
    r, g, b = rgb.split()
    bgmask = ImageChops.multiply(ImageChops.multiply(r.point(lambda v: 255 if v == 255 else 0), g.point(lambda v: 255 if v == 0 else 0)),
                                 b.point(lambda v: 255 if v == 254 else 0))
    alpha = ImageChops.invert(bgmask).filter(ImageFilter.GaussianBlur(0.8))
    out = im.copy()
    out.putalpha(alpha)
    bbox = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    return out.crop(bbox) if bbox else out


def padded_png(cut, aspect="1:1"):
    """参考图：产品放在透明画布中间（留边），按要出的比例。"""
    W, H = ASPECTS.get(aspect, ASPECTS["1:1"])
    W, H = W // 2, H // 2
    c = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    s = min(W * 0.7 / cut.width, H * 0.7 / cut.height)
    p = cut.resize((max(1, int(cut.width * s)), max(1, int(cut.height * s))), Image.LANCZOS)
    c.alpha_composite(p, ((W - p.width) // 2, (H - p.height) // 2))
    buf = io.BytesIO()
    c.save(buf, "PNG")
    return buf.getvalue()


def fit_aspect(img, aspect):
    W, H = ASPECTS.get(aspect, ASPECTS["1:1"])
    img = img.convert("RGB")
    w, h = img.size
    r = W / H
    if w / h > r:
        nw = int(h * r)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    elif w / h < r:
        nh = int(w / r)
        img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    return img.resize((W, H), Image.LANCZOS)


def composite(bg, cut, x=0.5, floor=0.84, scale=0.46):
    """把产品抠图放到背景上（底部居中、柔和接地阴影）。产品按比例缩放，不变形。"""
    bg = bg.convert("RGBA")
    W, H = bg.size
    s = min(H * scale / cut.height, W * 0.8 / cut.width)
    p = cut.resize((max(1, int(cut.width * s)), max(1, int(cut.height * s))), Image.LANCZOS)
    px, py = int(W * x - p.width / 2), int(H * floor - p.height)
    sh = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(sh)
    rx, ry = p.width * 0.48, max(6, p.width * 0.07)
    cx, cy = W * x, H * floor
    d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=110)
    sh = sh.filter(ImageFilter.GaussianBlur(max(4, ry)))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(sh)
    bg.alpha_composite(shadow)
    bg.alpha_composite(p, (px, py))
    return bg.convert("RGB")


def product_image(product):
    """批量时用的产品图：白底图 → 第一张不是场景图的图片。"""
    from . import store
    pid = product["id"]
    names = []
    wb = product.get("white_bg") or {}
    if wb.get("file"):
        names.append(("out", wb["file"]))
    for im in product.get("images") or []:
        if im.get("scene"):
            continue
        for kind in ("out", "raw"):
            n = im.get("file") if kind == "out" else im.get("raw")
            if n:
                names.append((kind, n))
    for kind, n in names:
        path = os.path.join(store.image_dir(pid, kind), n)
        if os.path.exists(path):
            return Image.open(path)
    raise SceneAIError("这个产品还没有产品图（先上传或生成白底图）")


def _b64(img, size=768):
    import base64
    im = img.convert("RGB") if img.mode != "RGBA" else _on_white(img)
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _on_white(cut):
    bg = Image.new("RGB", cut.size, "white")
    bg.paste(cut, mask=cut.getchannel("A"))
    return bg


# ---------------- 提示词 ----------------
def _size_txt(product):
    size = ((product.get("model") or {}).get("metrics") or {}).get("size")
    if isinstance(size, (list, tuple)) and len(size) == 3:
        return f" Its real size is about {size[0]:.0f} x {size[1]:.0f} x {size[2]:.0f} mm (W x D x H); keep a realistic scale."
    return ""


def edit_prompt(product, scene, aspect="1:1", extra=""):
    name = (product.get("copy") or {}).get("title_en") or product.get("name_zh") or "the product"
    return (f"Professional e-commerce lifestyle photo. Place THIS EXACT product from the input image ({name}) {scene}.{_size_txt(product)} "
            "Keep the product's shape, proportions, colours and details exactly the same as the input image; do not redesign, "
            "distort or recolour it; do not add any text, logos, watermarks or extra copies of the product. Photorealistic, natural "
            f"lighting, soft realistic contact shadow, shallow depth of field, the product is the clear hero, {aspect} composition."
            + (f" Additional requirements: {extra}" if extra else ""))


def background_prompt(scene, aspect="1:1", extra=""):
    return (f"Photorealistic empty product-display scene: {scene}. The surface is completely EMPTY in the lower center area so a "
            "product can be placed there later; camera at a slightly elevated eye level, professional e-commerce lifestyle "
            f"photography, shallow depth of field, no people, no products, no text, no logos, {aspect} composition."
            + (f" Additional: {extra}" if extra else ""))


PROMPT_SYS = ("You write prompts for an image model that makes e-commerce lifestyle photos for Shopee / Lazada Thailand. "
              "Look at the product photo. Describe a believable Thai home scene where a buyer would use this product. "
              "Never describe the product's design (the image model gets the real product); never mention 3D printing, brands or text. "
              "Output only JSON.")


def ai_scenes(cfg, product, template, n=1, cut=None):
    """让文字 / 看图 AI 按产品 + 模板写 n 个不同的场景描述（英文短句，不含产品外观）。出错时用模板原文。"""
    from . import ai
    base = template.get("prompt") or ""
    if not ai.ready(cfg, "scene_prompt"):
        return [base] * n, False
    cat = (product.get("category") or {})
    user = json.dumps({"product_name": product.get("name_zh") or "", "title_en": (product.get("copy") or {}).get("title_en") or "",
                       "category": cat.get("name") or cat.get("path") or "", "features": str(product.get("features_zh") or "")[:600],
                       "style_template": base, "how_many": n}, ensure_ascii=False) + (
        '\nWrite how_many DIFFERENT scene variations in the style_template (different surface, angle, props, light). '
        'Each is ONE English phrase that continues "Place the product ..." e.g. "on a teak sideboard in a Bangkok condo ...". '
        'Reply JSON: {"scenes": ["..."]}')
    try:
        d = ai.ai_copy_json(ai.for_task(cfg, "scene_prompt"), PROMPT_SYS, user, _b64(cut) if cut is not None else None)
        sc = [str(x).strip()[:500] for x in d.get("scenes") or [] if str(x).strip()]
    except Exception:  # noqa: BLE001  AI 写不出来：用模板
        sc = []
    if not sc:
        return [base] * n, False
    while len(sc) < n:
        sc.append(sc[len(sc) % max(1, len(sc))])
    return sc[:n], True


# ---------------- 质检 ----------------
QA_SYS = ("You are a strict e-commerce photo QA checker. LEFT = the real product (reference). RIGHT = a generated lifestyle photo. "
          "Check: is the product in the right photo the SAME shape and proportions as the reference, the SAME colours, not distorted, "
          "not duplicated; is there any added text / letters / watermark / logo; does the photo look realistic (lighting, shadow, scale). "
          "Output only JSON.")
QA_USER = ('Reply JSON: {"score": 0-100, "shape_ok": true/false, "color_ok": true/false, "no_text": true/false, '
           '"realistic": true/false, "issues_zh": "short Chinese", "issues_th": "the same in Thai"}')


def qa(cfg, cut, img):
    """AI 看图打分。返回 {score, shape_ok, color_ok, no_text, realistic, ok, issues_zh, issues_th} 或 None（没有能看图的 AI）。"""
    from . import ai
    if not ai.can(cfg, "scene_qa", "vision")[0]:
        return None
    ref = _on_white(cut)
    ref.thumbnail((512, 512))
    cand = img.convert("RGB")
    cand.thumbnail((512, 512))
    sheet = Image.new("RGB", (1040, 520), "white")
    sheet.paste(ref, ((512 - ref.width) // 2 + 4, (512 - ref.height) // 2 + 4))
    sheet.paste(cand, (524 + (512 - cand.width) // 2, (512 - cand.height) // 2 + 4))
    try:
        d = ai.ai_copy_json(ai.for_task(cfg, "scene_qa"), QA_SYS, QA_USER, _b64(sheet, 1040), strict=True)
    except Exception as e:  # noqa: BLE001
        return {"score": None, "ok": None, "error": str(e)[:200]}
    try:
        score = max(0, min(100, int(float(d.get("score") or 0))))
    except (TypeError, ValueError):
        score = 0
    flags = {k: d.get(k) is not False for k in ("shape_ok", "color_ok", "no_text", "realistic")}
    return {"score": score, **flags, "ok": score >= 60 and flags["shape_ok"] and flags["color_ok"] and flags["no_text"],
            "issues_zh": str(d.get("issues_zh") or "")[:200], "issues_th": str(d.get("issues_th") or "")[:300]}


# ---------------- 候选 ----------------
def _dir(pid):
    from . import store
    store.safe_id(pid)
    return os.path.join(CAND_DIR, pid)


def _index(pid):
    try:
        with open(os.path.join(_dir(pid), "index.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


_ilock = threading.Lock()


def _save_index(pid, items):
    d = _dir(pid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "index.json.tmp"), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(os.path.join(d, "index.json.tmp"), os.path.join(d, "index.json"))


def list_cands(pid):
    return [dict(c, url=f"/scene-cand/{pid}/{c['file']}") for c in _index(pid) if os.path.exists(os.path.join(_dir(pid), c["file"]))]


def delete_cand(pid, cid):
    with _ilock:
        items = _index(pid)
        keep = [c for c in items if c["id"] != cid]
        for c in items:
            if c["id"] == cid:
                try:
                    os.remove(os.path.join(_dir(pid), c["file"]))
                except OSError:
                    pass
        _save_index(pid, keep)
    return list_cands(pid)


def picked_images(pid, ids):
    """员工挑中的候选 → [(PIL 图, 候选信息)]，并标记已用。"""
    out = []
    with _ilock:
        items = _index(pid)
        for c in items:
            if c["id"] in ids:
                path = os.path.join(_dir(pid), c["file"])
                if os.path.exists(path):
                    out.append((Image.open(path).convert("RGB"), c))
                    c["picked"] = time.time()
        _save_index(pid, items)
    return out


def generate(cfg, product, template_key="minimal_white", aspect="1:1", n=2, extra="", cut=None, use_ai_prompt=True, do_qa=True,
             should_stop=None):
    """出 n 张候选，存起来等员工挑。返回 {cands: [新候选], cost: 实际费用（泰铢，按用量记录）, edited, errors}。"""
    from . import ai
    aspect = aspect if aspect in ASPECTS else "1:1"
    n = max(1, min(int(n or 1), MAX_N))
    if cut is None:
        cut = cutout(product_image(product))
    ok, why = ai.can(cfg, "scene", "image")
    if not ok:
        raise SceneAIError(why if "密钥" not in why else "还没有填写图片 AI 的接口密钥（系统 → AI 接口）")
    mark = ai.usage.max_id()
    t = _template(cfg, template_key)
    scenes_txt, by_ai = ai_scenes(cfg, product, t, n, cut) if use_ai_prompt else ([t["prompt"]] * n, False)
    ref = padded_png(cut, aspect)
    new, errors, edited_any = [], [], False
    pid = product["id"]
    os.makedirs(_dir(pid), exist_ok=True)
    for i in range(n):
        if should_stop and should_stop():
            break
        sc = scenes_txt[i] + (f" {extra}" if extra and by_ai else "")
        try:
            r = ai.image(cfg, lambda edit, sc=sc: edit_prompt(product, sc, aspect, extra) if edit else background_prompt(sc, aspect, extra),
                         ref, aspect, 1, task="scene")
        except ai.AIError as e:
            errors.append(str(e)[:300])
            if getattr(e, "kind", "") in ("budget", "config", "auth"):
                break
            continue
        try:
            img = Image.open(io.BytesIO(r["images"][0])).convert("RGB")
        except Exception as e:  # noqa: BLE001
            errors.append(f"图片 AI 返回的图片无法读取：{e}")
            continue
        img = fit_aspect(img, aspect)
        if not r["edited"]:
            img = composite(img, cut)
        edited_any = edited_any or r["edited"]
        q = qa(cfg, cut, img) if do_qa else None
        cid = uuid.uuid4().hex[:10]
        fn = f"{cid}.jpg"
        img.save(os.path.join(_dir(pid), fn), "JPEG", quality=92)
        new.append({"id": cid, "file": fn, "template": t["key"], "template_zh": t.get("zh"), "template_th": t.get("th"),
                    "aspect": aspect, "scene": sc, "ai_prompt": by_ai, "provider": r["provider"], "model": r["model"],
                    "mode": "edit" if r["edited"] else "composite", "cost": r.get("cost") or 0, "qa": q, "created": time.time()})
    with _ilock:
        items = _index(pid) + new
        _save_index(pid, items[-60:])
    cost = ai.usage.cost_since(mark, ("scene", "scene_prompt", "scene_qa"))
    return {"cands": [dict(c, url=f"/scene-cand/{pid}/{c['file']}") for c in new], "cost": round(cost, 2), "errors": errors,
            "ai_prompt": by_ai}


def estimate(cfg, products=1, n=2, do_qa=True, use_ai_prompt=True):
    """先估费用（泰铢）：出图 + 写提示词 + 质检。"""
    from . import ai
    products = max(1, int(products or 1))
    n = max(1, min(int(n or 1), MAX_N))
    img = ai.estimate_image(cfg, "scene", n * products)
    txt = ai.estimate_text(cfg, "scene_prompt", 1200, 300, products) if use_ai_prompt and ai.ready(cfg, "scene_prompt") else 0
    q = ai.estimate_text(cfg, "scene_qa", 1500, 150, n * products) if do_qa and ai.can(cfg, "scene_qa", "vision")[0] else 0
    return {"total": round(img + txt + q, 2), "images": round(img, 2), "prompt": round(txt, 2), "qa": round(q, 2),
            "count": n * products}


# ---------------- 批量（后台排队） ----------------
BATCH = {"running": False}
_block = threading.Lock()


def batch_status():
    b = dict(BATCH)
    b.pop("thread", None)
    return b


def batch_cancel():
    if BATCH.get("running"):
        BATCH["cancel"] = True
    return batch_status()


def batch_start(cfg, ids, opts, user="", load=None, add=None):
    """ids：产品编号；opts：{template（空 = 按类目推荐的第一个）, aspect, n, extra, qa, ai_prompt, auto_add}；
    load(pid) → 产品；add(pid, img, cand)：auto_add 时把质检最高（且合格）的一张加入商品图。"""
    with _block:
        if BATCH.get("running"):
            raise SceneAIError("已经有一批场景图在生成，等它做完或先取消")
        ids = [str(x) for x in ids or []][:200]
        if not ids:
            raise SceneAIError("请先勾选产品")
        BATCH.clear()
        BATCH.update(running=True, cancel=False, total=len(ids), done=0, failed=0, cost=0.0, user=user, started=time.time(),
                     ended=None, opts=dict(opts or {}), estimate=estimate(cfg, len(ids), (opts or {}).get("n") or 2,
                                                                         bool((opts or {}).get("qa", True)),
                                                                         bool((opts or {}).get("ai_prompt", True)))["total"],
                     items=[{"pid": p, "status": "queued", "n": 0, "error": ""} for p in ids])

    def run():
        try:
            for it in BATCH["items"]:
                if BATCH.get("cancel"):
                    it["status"] = "cancelled"
                    continue
                it["status"] = "running"
                try:
                    p = load(it["pid"])
                    tpl = opts.get("template") or (suggest(cfg, p) or ["minimal_white"])[0]
                    r = generate(cfg, p, tpl, opts.get("aspect") or "1:1", opts.get("n") or 2, opts.get("extra") or "",
                                 use_ai_prompt=bool(opts.get("ai_prompt", True)), do_qa=bool(opts.get("qa", True)),
                                 should_stop=lambda: BATCH.get("cancel"))
                    it["n"] = len(r["cands"])
                    BATCH["cost"] = round(BATCH["cost"] + r["cost"], 2)
                    if r["errors"] and not r["cands"]:
                        raise SceneAIError(r["errors"][0])
                    it["error"] = (r["errors"] or [""])[0]
                    if opts.get("auto_add") and add and r["cands"]:
                        best = sorted(r["cands"], key=lambda c: -((c.get("qa") or {}).get("score") or 0))[0]
                        if (best.get("qa") or {}).get("ok") is not False:
                            imgs = picked_images(it["pid"], [best["id"]])
                            if imgs:
                                add(it["pid"], imgs[0][0], imgs[0][1])
                                it["added"] = 1
                    it["status"] = "done"
                    BATCH["done"] += 1
                except Exception as e:  # noqa: BLE001
                    it["status"], it["error"] = "error", str(e)[:300]
                    BATCH["failed"] += 1
                    BATCH["done"] += 1
        finally:
            BATCH["running"] = False
            BATCH["ended"] = time.time()
    th = threading.Thread(target=run, daemon=True, name="scene-batch")
    BATCH["thread"] = th
    th.start()
    return batch_status()
