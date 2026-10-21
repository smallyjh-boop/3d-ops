# 模块：AI 客服（cs）

AI 客服——v2.30 从内核搬出来的模块（原来的 core/cs/ 现在是 modules/cs/logic/）。

客服工作台、登记中心、客服报表、知识库与话术；顶部「有客户在问」提醒；浏览器扩展的聊天接口；
超时未回复的手机提醒（Telegram）和周报邮件。只通过 logic/erp_link.py 读写产品、订单、生产。

## 文件

- `__init__.py`
- `api.py`
- `logic/__init__.py`
- `logic/alerts.py`
- `logic/api.py`
- `logic/brain.py`
- `logic/crm.py`
- `logic/data.py`
- `logic/erp_link.py`
- `logic/mailer.py`
- `logic/presets.py`
- `logic/report.py`
- `logic/service.py`
- `module.py`
- `tests/t_cs.py`
- `tests/t_cs224.py`
- `ui/cs.js`
- `ui/csalert.js`
- `ui/csrec.js`
- `ui/page.html`
- `ui/page.js`

## 改动记录

- 1.0（系统 v2.30.0）：从内核搬成模块。
- 1.1（系统 v2.34.0）：泰文翻译从内核 static/i18n.js 搬到模块自己的 i18n/th.json（只在这个模块里用到的那些），界面不变。
- 1.2（系统 v2.37.1）：浏览器插件 2.9.1：后台给没有插件脚本的标签 / 框架发消息时（网页刚刷新、插件刚重新加载）不再在 chrome://extensions 里报「Could not establish connection. Receiving end does not exist.」。功能本身没变。测试 tests/ui/ui2371ext.py。
- 1.3（系统 v2.41.0）：客服 AI：顾客的话被规则判成要人工（投诉、退款、要求真人……）时，AI 草稿一律交给人工，不会被模型改判成自动回复；对话筛选「进行中」改名「对话中」。测试 tests/cases/t_v241.py。
