"""AI 接口统一管理（v2.53，内核模块，不能关）：
· 「AI 接口」页：各家 AI 的密钥（只存在 NAS 上，网页只显示打码）、测试连接、能力标签（文字 / 看图 / 出图 / 参考图改图）；
  每个任务（文字 / 看图 / 出图三组）选服务商 + 模型 + 备用顺序，每天 / 每月费用上限；价格表；场景图模板。
· 「AI 用量」页：每次调用的任务、服务商、模型、token / 张数、估算费用（泰铢）、成功 / 出错、用时；按天 / 任务 / 服务商看。
逻辑在 core/ai/（系统里所有 AI 调用都从那里走）。"""

MODULE = {
    "id": "ai",
    "name_zh": "AI 接口",
    "name_th": "การเชื่อมต่อ AI",
    "version": "1.0",
    "desc_zh": "统一管理系统里所有 AI：多家服务商（Claude、OpenAI、Gemini、DeepSeek、通义、Flux…）、按任务选 AI 和备用、用量费用和上限。",
    "desc_th": "จัดการ AI ทั้งหมดในระบบที่เดียว: หลายผู้ให้บริการ (Claude, OpenAI, Gemini, DeepSeek, Qwen, Flux…) เลือก AI และตัวสำรองตามงาน การใช้งาน ค่าใช้จ่าย และเพดาน",
    "core": True,
    "depends": [],
    "order": 5,
    "menus": [{"tab": "ai_conf", "mod": "sys", "zh": "AI 接口", "th": "การเชื่อมต่อ AI", "roles": "owner"},
              {"tab": "ai_usage", "mod": "sys", "zh": "AI 用量", "th": "การใช้ AI", "roles": "owner"}],
    "settings_module": "ai",
    "settings_cards": ["ai"],
    "owner_only": [("*", r"^/api/ai/")],
    "ui": {"html": "page.html", "page_js": ["page.js"], "boot_js": ["card.js"], "css": []},
}
