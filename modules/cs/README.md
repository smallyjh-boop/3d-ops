# 模块：AI 客服（cs）

AI 客服——v2.30 从内核搬出来的模块（原来的 core/cs/ 现在是 modules/cs/logic/）。

客服工作台、登记中心、客服报表、知识库与话术；顶部「有客户在问」提醒；浏览器扩展的聊天接口；
超时未回复的手机提醒（Telegram）和周报邮件。只通过 logic/erp_link.py 读写产品、订单、生产。

## 文件

- `__init__.py`
- `api.py`
- `logic/__init__.py`
- `events.py`
- `worker.py`
- `logic/alerts.py`
- `logic/channels/__init__.py`
- `logic/channels/lazada_im.py`
- `logic/chat.py`
- `logic/chat_api.py`
- `logic/jobs.py`
- `logic/shopcfg.py`
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
- `tests/t_chat246.py`
- `ui/cs.js`
- `ui/csdash.js`
- `ui/page.css`
- `ui/csalert.js`
- `ui/csrec.js`
- `ui/page.html`
- `ui/page.js`

## 改动记录

- 1.0（系统 v2.30.0）：从内核搬成模块。
- 1.1（系统 v2.34.0）：泰文翻译从内核 static/i18n.js 搬到模块自己的 i18n/th.json（只在这个模块里用到的那些），界面不变。
- 1.2（系统 v2.37.1）：浏览器插件 2.9.1：后台给没有插件脚本的标签 / 框架发消息时（网页刚刷新、插件刚重新加载）不再在 chrome://extensions 里报「Could not establish connection. Receiving end does not exist.」。功能本身没变。测试 tests/ui/ui2371ext.py。
- 1.3（系统 v2.41.0）：客服 AI：顾客的话被规则判成要人工（投诉、退款、要求真人……）时，AI 草稿一律交给人工，不会被模型改判成自动回复；对话筛选「进行中」改名「对话中」。测试 tests/cases/t_v241.py。
- 2.0（系统 v2.46.0）：像客服软件一样用：
  - 「客服工作台」改成汇总页（csdash.js）：未回复 / 等了 5、15 分钟 / 需人工 / 我的、首次响应、AI 和人工回复数；要马上处理的会话；
    各店铺的消息渠道状态和 AI 模式（只人工 / 出草稿 / 自动回复，shopcfg.py）；各客服的负载；线索、售后、AI 表现、待补知识、质检、后台任务。
  - 「客服聊天」三栏（会话列表 / 聊天 / 订单与买家）：气泡、图片、商品卡片、订单卡片；AI 草稿用 / 直接发 / 重写 / 丢弃；快捷回复（变量）；
    发商品 / 订单 / 图片；中文输入自动翻泰语；接管 / 交回 AI / 分配；新消息提示音和桌面通知；Enter 发送、Alt+↑↓ 换会话。
  - Lazada 聊天接口渠道（logic/channels/lazada_im.py，连接器 im_*）：每 15 秒拉新消息（收到推送马上拉），直接在 ERP 里回复；发不出去的标红可重发。
  - 后台任务队列 cs_jobs + 工作线程（jobs.py）：拉消息、AI 草稿 / 自动回复、主动提醒、质检；CS_WORKER=external 时可以用 `python -m modules.cs.worker` 单独跑。
  - 第二期一起做了：快捷回复（cs_quick，{买家名}{订单号}{运单号}{预计发货日}{店铺名}）、发货 / 超 48 小时主动提醒（events.py 订阅 order.status）、
    自动标签（询价 / 催单 / 售后 / 定制 / 闲聊 / 咨询）、接管超时交回 AI、别人接管时发送要确认、夜间模式（提示语 / 自动答）、
    每天 AI 抽查打分（cs_qa）、分店知识库（cs_kb.shop）。
  - 扩展的全自动：店铺设成「只人工」或会话被接管时不会自动发。
- 2.1（系统 v2.47.0）：给「今日待办」（core/todo.py）交待办：超时没回复的买家、要人工处理的会话（只进待办，不重复推送——超时提醒还是客服自己的 Telegram / 邮件）。测试 modules/ops/tests/t_ops246.py。
- 2.2（系统 v2.47.1）：工作台的 Lazada 权限报错提示写清楚三步（确认 Instant Messaging 已开通 → 店铺对接里重新授权 → 立即拉取）；浏览器扩展 2.9.2 不再把聊天页的「My Last Order」「Messages」这类标签当成买家名字（服务器也挡一层 NOT_BUYER），以前存错的买家名字启动时清空。
