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
- `logic/notice.py`
- `logic/presets.py`
- `logic/report.py`
- `logic/service.py`
- `module.py`
- `tests/t_cs.py`
- `tests/t_cs224.py`
- `tests/t_chat246.py`
- `tests/t_cs249.py`
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
- 2.3（系统 v2.47.2）：Lazada 聊天可以用单独的聊天应用（In-house IM Chat）：店铺设置里填聊天应用的 App Key / Secret，单独授权，token 存在 im_*（连接器 im_view），聊天接口都用它签名；没授权时提示去授权。测试 t_chat246。
- 2.4（系统 v2.49.0）：
  - 平台通知（logic/notice.py）：Lazada 官方账号（名字打码成 L****l、会话标签 official / system、不是买家的账号类型、通知模板）发来的卖家通知单独认出来（会话 kind='system'）：
    不算未回复 / 超时 / 需人工 / 工作台和报表统计，不打标签、不写 AI 草稿、不自动回复、不进今日待办；聊天页单独的「平台通知」页签（灰色）、只读、一键「全部标记已读」（Lazada 上也标）。
    通知里的 HTML 服务器原样保存，界面里安全地显示（只认图片、链接（新窗口打开）、换行，别的标签只留文字）；列表预览去掉标签。启动时把以前收进来的通知重新认出来，清掉错的需人工 / 标签 / 草稿。
  - 聊天页：长网址自动折行（不横向滚动）；头部压成一行；需人工改成一行提示；工具条一排小图标（⚡🛍📦🖼🀄🤖），给 AI 的要求放进 🤖 的小弹窗；回复框输入 / 搜快捷回复；
    「▶ 连续处理」按等待时间过有 AI 草稿的未回复会话（Enter 发送、Tab 改、→ 跳过、Esc 退出）；右边自动列出买家最近的订单（一键发订单卡片 / 关联），买家提到产品时推荐 1–3 个商品卡片（窄屏点 📋 打开）；
    买家消息在后台自动翻成中文（限速、存在 cs_msg.text_zh，中文界面显示在消息下面）；未回复按等待时间排、显示还剩几分钟超时；新消息列表里闪一下；没有扩展开着店铺页时不显示「浏览器里的店铺」那一行；打开会话 = Lazada 上标已读（以前打开时先清了未读，平台上没标）。
  - 对买家不提生产 / 3D 打印 / 接单后制作：AI 规则、提示词、默认店铺政策、标准话术、快捷回复「备货中」、延迟安抚模板都改成「备货 / 打包 / 尽快发货」（没改过的旧默认自动换新）；
    回复里出现 ผลิต / พิมพ์ 3D / 3D print / กำลังพิมพ์ / 生产 / 打印 …（brain.PROD_WORDS，设置里的词清空了也照样挡）不会自动发送；订单的生产进度只给员工看；知识库里还有这些词的回答标红。
  - 泰文界面的客服页不显示中文（周报按界面语言生成、待补知识按语言显示、常见问答只显示一半问法、标签显示名字、快捷回复的变量和标题显示泰文），中文界面也一样。
  - 客服工作台改用统一页面组件：数字卡片带 7 天走势、服务指标进度条、客服负载 / 店铺会话条形图。测试 tests/t_cs249.py。
- 2.5（系统 v2.50.0）：聊天右边「🧾 从聊天建单」：买家 / 平台 / 店铺从会话带过来，商品按「买家提到的商品」预填，建手工订单（马上排产）或报价单，会话自动关联（动作 make_order，erp_link.create_order；对话框在订单模块 OPS.orderFromChat）。买家历史里带风险买家提醒（黑名单原因 / 拒收 / 退货次数）。
