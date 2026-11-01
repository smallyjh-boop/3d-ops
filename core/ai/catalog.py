"""AI 接口统一管理（v2.53）：有哪些接口（服务商）、每个能做什么、有哪些任务、默认价格。

能力（caps）：text 写文字 / vision 看图 / image 出图 / edit 参考图改图（保持真实产品）。
模型的能力按服务商默认 + 模型名规则推断，设置页里也能手动改（ai_providers[pid].caps）。
"""
import re

TEXT, VISION, IMAGE, EDIT = "text", "vision", "image", "edit"
ALL_CAPS = (TEXT, VISION, IMAGE, EDIT)
CAP_NAMES = {TEXT: ("文字", "ข้อความ"), VISION: ("看图", "ดูรูป"), IMAGE: ("出图", "สร้างรูป"), EDIT: ("参考图改图", "แก้รูปจากรูปอ้างอิง")}

# 服务商：style = 调用方式；base = 官方地址；text / image / edit = 默认模型（留空 = 不做这一类）
PROVIDERS = {
    "anthropic": {"zh": "Claude（Anthropic）", "th": "Claude (Anthropic)", "style": "anthropic",
                  "base": "https://api.anthropic.com", "caps": [TEXT, VISION], "text": "claude-sonnet-5-5", "image": ""},
    "openai": {"zh": "OpenAI", "th": "OpenAI", "style": "openai", "base": "https://api.openai.com/v1",
               "caps": [TEXT, VISION, IMAGE, EDIT], "text": "gpt-4.1-mini", "image": "gpt-image-1-mini"},
    "gemini": {"zh": "Google Gemini", "th": "Google Gemini", "style": "gemini",
               "base": "https://generativelanguage.googleapis.com/v1beta",
               "caps": [TEXT, VISION, IMAGE, EDIT], "text": "gemini-2.5-flash", "image": "gemini-3.1-flash-lite-image"},
    "deepseek": {"zh": "DeepSeek", "th": "DeepSeek", "style": "openai", "base": "https://api.deepseek.com",
                 "caps": [TEXT], "text": "deepseek-chat", "image": ""},
    "qwen": {"zh": "通义千问（阿里云百炼）", "th": "Qwen (Alibaba Cloud)", "style": "openai",
             "base": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "caps": [TEXT], "text": "qwen-plus", "image": ""},
    "openai_compatible": {"zh": "其他 OpenAI 兼容接口", "th": "API อื่นที่เข้ากันได้กับ OpenAI", "style": "openai",
                          "base": "", "caps": [TEXT], "text": "", "image": ""},
    "fal": {"zh": "Flux（fal.ai）", "th": "Flux (fal.ai)", "style": "fal", "base": "https://fal.run",
            "caps": [IMAGE, EDIT], "text": "", "image": "fal-ai/flux/schnell", "edit": "fal-ai/flux-pro/kontext"},
    "replicate": {"zh": "Flux（Replicate）", "th": "Flux (Replicate)", "style": "replicate", "base": "https://api.replicate.com/v1",
                  "caps": [IMAGE, EDIT], "text": "", "image": "black-forest-labs/flux-schnell",
                  "edit": "black-forest-labs/flux-kontext-pro"},
}
TEXT_PROVIDERS = [k for k, v in PROVIDERS.items() if TEXT in v["caps"]]
IMAGE_PROVIDERS = [k for k, v in PROVIDERS.items() if IMAGE in v["caps"]]

# 任务：id → (分组, 中文, 泰文, 需要)。need：text 纯文字 / vision 必须看图 / vision_opt 能看图更好（看不了就只发文字）/ image 出图
GROUPS = {"text": ("文字", "ข้อความ"), "vision": ("看图", "ดูรูป"), "image": ("出图", "สร้างรูป")}
TASKS = {
    "copy": ("text", "上架文案（生成 / 补全 / 回译 / 英文）", "ข้อความลงขาย (สร้าง / เติม / แปลกลับ / อังกฤษ)", "text"),
    "category": ("text", "类目 / 属性", "หมวดหมู่ / คุณสมบัติ", "text"),
    "keywords": ("text", "关键词 / 搜索优化", "คีย์เวิร์ด / ปรับให้ค้นหาเจอ", "text"),
    "adtext": ("text", "卖点图文字", "ข้อความบนรูปจุดขาย", "text"),
    "cs_draft": ("text", "客服回复草稿", "ร่างคำตอบแชท", "text"),
    "cs_translate": ("text", "客服翻译", "แปลแชท", "text"),
    "cs_kb": ("text", "客服知识库 / 质检", "คลังความรู้แชท / ตรวจคุณภาพ", "text"),
    "curate": ("text", "选品打分", "ให้คะแนนเลือกสินค้า", "text"),
    "ops": ("text", "运营分析", "วิเคราะห์การขาย", "text"),
    "print_advice": ("text", "打印建议 / 配方检查", "คำแนะนำการพิมพ์ / ตรวจสูตร", "vision_opt"),
    "scene_prompt": ("text", "场景图提示词", "พรอมต์รูปฉาก", "vision_opt"),
    "general": ("text", "其他文字任务", "งานข้อความอื่น ๆ", "text"),
    "kit": ("vision", "摆盘组合（看渲染图）", "จัดชิ้นงานบนถาด (ดูภาพเรนเดอร์)", "vision_opt"),
    "assembly": ("vision", "按图片组装", "ประกอบตามรูป", "vision"),
    "recog": ("vision", "拍照识别产品", "ถ่ายรูปจดจำสินค้า", "vision"),
    "ocr": ("vision", "拍照读文字", "ถ่ายรูปอ่านตัวอักษร", "vision"),
    "cs_ocr": ("vision", "客服截图识字", "อ่านข้อความจากภาพแชท", "vision"),
    "pur_quick": ("vision", "截图开采购单", "เปิดใบสั่งซื้อจากภาพหน้าจอ", "vision_opt"),
    "scene_qa": ("vision", "场景图质检", "ตรวจคุณภาพรูปฉาก", "vision"),
    "scene": ("image", "场景图", "รูปฉาก", "image"),
    "scene_bg": ("image", "AI 空背景", "พื้นหลังว่าง AI", "image"),
}

# 默认价格（泰铢）：每百万 token 输入 / 输出，每张图。只是估算，按自己的账单在「AI 接口」页改。
DEFAULT_PRICES = {
    "anthropic": {"in": 110, "out": 540},
    "openai": {"in": 15, "out": 60, "img": 0.5},
    "gemini": {"in": 11, "out": 90, "img": 1.4},
    "deepseek": {"in": 10, "out": 40},
    "qwen": {"in": 15, "out": 45},
    "openai_compatible": {"in": 0, "out": 0},
    "fal": {"img": 0.15, "edit": 1.5},
    "replicate": {"img": 0.15, "edit": 1.5},
}


def model_caps(pid, model, override=None):
    """这个服务商 + 模型能做什么。override：设置页手动勾的能力（列表），优先。"""
    if override:
        return [c for c in ALL_CAPS if c in override]
    base = list(PROVIDERS.get(pid, {}).get("caps") or [TEXT])
    m = (model or "").lower()
    if pid == "qwen" and re.search(r"vl|omni|qvq|qwen3\.5|qwen-max", m):
        base.append(VISION)
    if pid == "openai_compatible" and re.search(r"vision|vl|gpt-4o|gpt-4\.1|gpt-5|claude|gemini|omni", m):
        base.append(VISION)
    return [c for c in ALL_CAPS if c in base]


def edit_capable_model(pid, model):
    """Flux 只有 kontext / edit 一类模型能按参考图改；其他服务商的图片模型都能。"""
    if pid in ("fal", "replicate"):
        return bool(re.search(r"kontext|edit|redux|fill", (model or "").lower()))
    return True
