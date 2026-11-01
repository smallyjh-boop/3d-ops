# AI 接口（ai）

内核模块（不能关）。系统里所有 AI 调用都走 `core/ai/`，这里是设置页和用量页。

- 服务商：Claude、OpenAI、Google Gemini、DeepSeek、通义千问（百炼，OpenAI 兼容）、其他 OpenAI 兼容接口；出图：OpenAI、Gemini、Flux（fal.ai / Replicate）。
- 能力：文字 / 看图 / 出图 / 参考图改图（按服务商 + 模型名推断，可以手动改）。必须看图的任务遇到不能看图的 AI 直接说清楚（例如 DeepSeek）。
- 按任务选 AI：文字（文案、客服、翻译、打分…）/ 看图（摆盘、组装、拍照识别、截图开单、场景图质检…）/ 出图（场景图、空背景），每个任务主选 + 最多两个备用，出错 / 限流 / 超时自动换下一个。看图任务填了 Claude 的密钥时默认用 Claude。
- 用量费用：每次调用记 `ai_usage` 表（任务、服务商、模型、token / 张数、估算泰铢、成功 / 出错、用时、是否用了备用）；价格表可改；每个任务和全部的每天 / 每月上限（提醒，勾「硬上限」就暂停）。
- 密钥只存在 NAS（config.json 的 `ai_providers`），网页只显示打码；`/api/config`、诊断包都不带。
- 旧设置：`ai_provider / ai_model / ai_api_key / ai_base_url`（默认文字 AI）、`image_*`（默认出图 AI）继续有效；第一次用到时把客服单独的模型、拍照识别次数接进任务设置（`ai_v2`）。

代码：`core/ai/catalog.py`（服务商、任务、默认价格）、`conf.py`（设置、旧键兜底、迁移、打码）、`providers.py`（各家请求格式）、
`router.py`（选 AI、备用、能力检查、上限）、`usage.py`（用量费用）。调用：`ai_copy.call(ai_copy.tcfg(cfg, "任务"), system, user, image_b64)`、`ai.image(...)`、`ai.can(cfg, 任务)`。

## 改动记录
- 1.0（系统 v2.53.0）：新模块。AI 接口统一管理：多家服务商、测试连接、按任务选 AI + 自动备用、用量费用页（数字卡片 → 每天费用 → 按任务 / 服务商 → 明细）、上限、价格表、场景图模板编辑、旧设置自动接入。
