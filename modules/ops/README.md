# 模块：运营分析（ops）

把原来单独部署的「运营分析系统」（/home/user/ops-analytics，通过 /api/v1 读 ERP）并进 ERP：数据直接读 ERP 的表，
不再同步一份镜像。第一期：运营看板、商品生命周期、今日待办与手机提醒、Lazada 运营数据。

## 页面（系统 v2.49.0 起：顶部大菜单「运营」，4 个页面，页面里用页签）

每个页面：页面头（「?」说明）→ 一条筛选条（时间段 今天 / 7 天 / 30 天 / 本月 / 自定义、平台、店铺、搜索，几个页面共用，记在这台电脑上）
→ 页签 → 数字卡片 → 图表 → 明细。页面框架在 `ui/hub.js`；页签就是原来的页面 id（ghost 菜单，`panel` = 所在页面），
旧链接（待办、提醒里的 ops_comp、ops_lazada、ops_traffic、opschg……）照样能打开到对的页签。

- **经营概况**（ops_overview，老板）：页签「总览」（ops_dash）：销售额 / 利润 / 订单 / 利润率（走势小图、和上一段比）、30 天净利润；
  Lazada 同步一个点（「4 项正常 · 23:47」，出错变红，「?」里写原因和怎么办）、真实扣点 vs 设置、评价（平均星、差评、没回复）、退货退款、
  店铺表现「7/9 达标」；每日销售额柱状图；店铺表现进度条（指标名中文 / 泰文，`lazada.perf_label`）；平台扣了哪些钱（按费用名）；
  最新评价、退货退款（没有就一行灰字）；按平台、发货时效、利润最高 SKU、亏本订单、售价低于最低价、生产与耗材、市场与计划、数据健康（收起）。
  页签「店铺与评价」（ops_lazada）：同步状态、店铺表现、真实扣点、评价（回复）、退货退款。上架客服从待办链接进来只看到评价。
  接口 `/api/oa/dashboard?range=&from=&to=&platform=&shop=`（`dash.period()`）。
- **商品表现**（ops_goods，老板 + 上架客服）：页签「商品表现」（ops_life）= 原来的商品生命周期 + 流量数据：每个 SKU × 平台一行：阶段、访客、转化、
  7 / 30 天销量、30 天利润（只给老板，接口里去掉）、建议动作；采集的后台页面收在最下面。页签「待确认的建议」（ops_sugg）= 原来「商品 → 运营改动」
  （对接模块 `/api/ops/changes`：改前 → 改后、原因、通过 / 拒绝 / 撤回）。
- **市场与竞争**（ops_market，老板 + 上架客服）：页签 竞品 / 竞店 / 找新品（爆款雷达），内容在 `ui/market.js`（下面「第二期」）。
- **计划与活动**（ops_plan，老板 + 上架客服）：页签 爆款 / 上量计划、营销日历，内容在 `ui/plan.js`。
- 「今日待办」页面没有了：每个页面右上角 🔔（`static/shell.js`，`/api/todo/count` 每分钟问一次），手机提醒的设置在 🔔 抽屉下面（老板）。

## 第一期页面（v2.46，v2.49 起并进上面的页面）

- **今日待办**（ops_todo，老板 / 上架客服 / 生产都能看，按角色只显示自己的）：内核 `core/todo.py` 汇总各模块交上来的待办，
  每条「完成」或「忽略」；老板下面还有「手机提醒」：推送渠道、按来源开关、最近推送。工作台首页上也有一张「今日待办」卡片（`static/home.js` 的 `TODO_UI`）。
- **运营看板**（ops_dash，老板）：今天 / 昨天 / 近 7 天（比前 7 天）/ 近 30 天的订单、销售额、利润、利润率；财务口径的 30 天净利润；
  每日销售额图；发货时效（超时、快到期、近 30 天准时率、平均发货小时）；售后与拒收（售后损失、货到付款拒收率、Lazada 退货退款）；
  按平台；利润最高的 SKU；亏本订单；售价低于最低价（ERP 售价或平台上实际卖的价）；Lazada（评价、差评、真实扣点）；生产与耗材；数据健康。
- **商品生命周期**（ops_life，老板）：每个 SKU × 平台：未上架 / 审核中 / 审核不通过 / 测款期 / 未出单·再测 / 建议下架 / 成长 / 主推 / 衰退 / ERP 已下架 / 已下架，
  在售天数、7 / 30 天 / 累计销量、30 天利润、售价和建议动作。规则在「设置 → 运营分析」。
- **Lazada 数据**（ops_lazada，老板；上架客服只看同步状态和评价）：同步状态（出错原因 + 怎么办，例如去 App Console 申请接口权限）、立即同步、
  真实扣点（按费用名）、评价（差评 / 没回复 / 全部，直接回复）、退货退款、店铺表现。

## 第二期页面（系统 v2.48.0）

菜单：「商品」下面 竞品 / 爆款雷达 / 竞店（只给老板，里面有成本和利润）；「工作台」下面 爆款 / 上量计划、营销日历（老板和上架客服；
员工看不到计划里的销售额和利润，也不能建 / 改计划），流量数据（老板）。

- **竞品**（ops_comp）：我的商品 vs 竞品（我的售价、竞品中位价、价格排第几、我的日销（ERP 订单）vs 竞品最高日销、市场份额）、全部竞品、
  选品雷达（还没关联我方 SKU 的竞品按推算月利润排，标「要做」进今日待办）、竞品动态（降价、涨价、开券、放量、改标题）。
  添加：浏览器扩展采集，或粘贴商品页文字 →「识别」（配了 AI 用 AI，没配只认常见写法）。
  日销：两次「累计已售」相减 ÷ 天数（实测）> 页面上的近 30 天已售 > 评价数差值 ÷ 留评比例（估）> 累计已售 ÷ 上架天数（估）。
  单件利润 = 到手价 − 平台费 − 生产成本。平台费：Lazada 用第一期财务流水算出的真实扣点（近 30 天商品金额 ≥ ฿1,000 才用），
  其他平台用设置里的扣点；生产成本：手动 > 关联的我方 SKU（ERP 成本）> AI 估克重和时长 × ERP 成本参数（`core/pricing.py`）。
- **爆款雷达**（ops_radar）：关键词库、巡逻状态和记录、机会分 0–100 = 需求 + 竞争少 + 能打印（AI）+ 利润 + 小爆潜力（AI），
  AI 判断有侵权风险（品牌 / 角色 / 外观设计）直接 0 分；关键词详情（前 30 名商品、AI 结论）。
  和「搜索优化」（`core/keywords.py`）不重复存：产品的买家搜索词还是存在产品里；「从产品搜索词导入」把每个产品的标题主词和前 2 个核心词加进来巡逻；
  每个关键词显示「我们的产品」（搜索词或泰文标题里已经有这个词的产品）。每天到点（设置）推一次机会日报（和手机提醒同一个渠道）。
- **竞店**（ops_shops）：我的店铺的 ERP 实际数（按订单里的店铺名：订单、每天几单 / 几件、销售额；Lazada 店铺加上第一期店铺表现的回复率、评分）；
  盯着的竞店的中位数（粉丝、好评率、回复率、在售商品、店铺日销下限、近 7 天上新）和我的店铺落后的地方；店铺列表和详情（卖得最好的、新品起量、历史）。
- **爆款 / 上量计划**（ops_plans）：爆款计划目标日销 = 对标竞品最高日销 × 30%，上量计划 × 60%（没有竞品按自己销量翻倍；一款最多占一半产能）；
  前 2/3 天数从起点线性爬到目标；每天用 ERP 实际订单对目标（领先 / 正常 / 落后 / 严重落后）、计划期销售额和利润（和财务一样的算法）；
  「现在该做什么」（规则：后台流量判断曝光还是转化问题、价格比竞品中位高低、产能、快到的大促、竞品动态）；分阶段任务（模板 + 计划期内大促的报名任务），
  到日子进今日待办（在待办里点完成 = 计划里勾掉）；「AI 更新计划」（ERP 的 AI 设置）换掉还没做的 AI 任务、写一段判断和泰文关键词。
- **营销日历**（ops_cal）：内置每月双数日大促、月中 15 号、发薪日 25 号、泰国节日（按平台惯例推算，以卖家中心公告为准），可以隐藏、加自己的活动；
  每个大促 T-14 / T-7 / T-3 / T / T+3 倒排任务（到日子进今日待办，往回 3 天内都还在）；产能 = 生产模块里开着的打印机 × 每台每天小时，
  平均每单打印小时按近 30 天订单算，预计订单 = 平时每天订单 × 倍数，超过「大促当天最多能接」就提醒限量或提前打库存。
- **流量数据**（ops_traffic）：扩展在卖家中心采集的每个商品的曝光、访客、浏览、加购、订单、转化率（AI 识别，按卖家 SKU / 在线商品编号对上 ERP SKU）；
  商品生命周期多一列「访客 / 转化」，运营看板多一张「市场与计划」卡片（下一个大促、计划进度、竞品动态、访客最多 / 转化最低）。

## 浏览器扩展（和 AI 客服、面单转交是同一个扩展，v3.0.0）

- 下载：系统 → 设置 → 组件与插件（`/api/cs/extension.zip`）；用员工的扩展密钥（和 AI 客服同一把，完整权限）。
- `extension/capture.js`：Lazada / Shopee / TikTok 前台商品页「📊 采集竞品」、搜索结果页「🔭 采集搜索结果」、店铺页「🏪 采集店铺」、
  列表里每个商品卡片的「📊 采集」标记和横向对比栏；卖家中心的数据页「📥 采集本页数据」，带流量表格的页面打开 8 秒后自动采一次（同一页 12 小时一次，
  插件设置里可以关）；聊天页不放按钮（AI 客服的地盘）。
- `extension/patrol.html / patrol.js`：今日巡逻（插件设置弹窗里「🔭 开始今日巡逻」）：按系统给的清单（关键词搜索页、盯着的店铺、20 小时没更新的竞品页）
  逐页打开、随机停留并慢慢滚动再读页面；每天有上限（设置）、遇到验证码马上停、连续 3 页失败停、关掉标签页停。
- 接口 `/api/v1/ops/ext/…`：ping、competitor、competitor/<id>、card、known、compare、patrol、patrol/log、search、shop、shop/watch、shop/known、backend。
  `core/auth.py`：`/api/v1/ops/ext/` 用完整权限的密钥就行（`/api/v1/ops/` 其余的写回接口还是要「运营写回」密钥），只读密钥不行；也记下扩展版本。

## 第二期的表（ops_ 开头，`mkt_db.py`）和第三期导入旧数据的对应

列名和原来的 analytics.db 一样，直接按表对应复制：competitors → ops_comp，comp_links → ops_comp_links，comp_snaps → ops_comp_snaps，
comp_events → ops_comp_events（多了 text_th），radar_keywords → ops_radar_keywords（多了 source、product_id），radar_searches → ops_radar_searches，
radar_items → ops_radar_items，radar_item_snaps → ops_radar_item_snaps，radar_volumes → ops_radar_volumes，radar_patrol_log → ops_patrol_log（多了 who），
shops → ops_shops（多了 erp_shop），shop_snaps / shop_items / shop_item_snaps / shop_comp_links → ops_shop_*，plans → ops_plans，
plan_tasks → ops_plan_tasks（多了 text_th），campaigns → ops_campaigns，backend_pages / backend_rows → ops_backend_pages / ops_backend_rows。
要注意：旧库里的 SKU 是分析系统同步的 erp_skus，和 ERP 一样是大写 SKU，可以直接用；图片列旧库可能存的是本地缓存路径，导入时只留 http(s) 地址；
旧的设置键（comp_stale_days、patrol_daily_cap、radar_w_*、my_shop_urls……）在 ERP 里前面加了 oa_。

## 口径（和财务模块一致）

- 计入销售 = 不是取消 / 退货 / 未付款 / 报价 / 拒收（`core.finance.EXCLUDE`）。
- 每单利润用 `core.finance.order_profit`；按平台、按 SKU 直接用财务模块的 `breakdown()`；30 天净利润用财务模块的 `pl()`。
- 售后损失用 `core.extras.as_losses`（和损益表一样）。

## Lazada 接口（`core/connectors/lazada.py` 新加的方法，用「店铺对接」里同一个应用和令牌）

| 数据 | 接口 | 说明 |
|---|---|---|
| 财务流水 | `/finance/transaction/details/get`（start_time / end_time = YYYY-MM-DD，offset，limit ≤ 500） | 第一次拉 30 天，以后从上次成功往回 7 天；订单拉到「Item Price Credit」那一行后整单交给财务模块 `settle_import_lines` |
| 评价编号 | `/review/seller/history/list`（item_id 必填，start_time / end_time 毫秒、≤ 7 天、90 天内，current 页码 ≤ 50） | 按在线商品（上架模块的 online_items，在售的）一个个拉，每次最多 200 个商品 |
| 评价内容 | `/review/seller/list/v2`（id_list 最多 10 个） | ratings.overall_rating / product_rating；seller_reply |
| 回复评价 | `/review/seller/reply/add`（id，content ≤ 500 字，GET） | |
| 退货退款 | `/reverse/getreverseordersforseller`（page_no，page_size，ReverseOrderLineModifiedTimeRangeStart / End 毫秒） | refund_amount 没写单位：比 ERP 单价大 20 倍以上按「分」÷ 100 |
| 店铺表现 | `/seller/performance/get`（language = en-US） | indicators：name、formatted_score、formatted_target、target_respected |

这些参数都按 open.lazada.com 的文档页核对过（2026-10-31）。没开权限时错误写进 `oa_lz_state`，页面和今日待办都会提示去 App Console 申请。

## 今日待办 / 手机提醒

- 登记处在内核：`core/todo.py`。模块说明书写 `"todo": fn`，`fn(add)` 里 `add(key, 分组, 级别, 标题, 说明, tab, roles, alert, th)`。
  现在交待办的：内核（超时未发货、快到期、待审核订单、售后快到期 / 超期、耗材不够 / 该补货）、客服模块（超时没回复、要人工）、
  本模块（亏本订单、售价低于最低价、审核不通过 / 再测 / 建议下架 / ERP 已下架、货到付款拒收率偏高、Lazada 差评没回复、退货退款申请、
  店铺表现没达标、接口出错）。
- 完成 / 忽略按 key 记（`todo_state`，120 天后清掉）。
- 带 `alert` 的条目按 key 去重记进 `oa_alerts`，合成一条推到 LINE（Messaging API push）和 / 或客服模块的 Telegram；推不出去下一轮再试；
  按来源关推送（`oa_alert_muted`）。

## 设置（设置 → 运营分析）

第二期加了：竞品推算（oa_comp_stale_days、oa_comp_price_drop_pct、oa_review_rate_*）、巡逻（oa_patrol_daily_cap、oa_patrol_wait_min / max、
oa_patrol_competitors）、机会分权重（oa_radar_w_*、oa_radar_alert_score、oa_radar_report_hour）、竞店（oa_my_shop_urls、oa_shop_patrol_days）、
营销日历（oa_avg_hours_per_order、oa_ship_window_hours、oa_campaign_lookahead_days）。第一期的：

`oa_alert_on`、`oa_alert_every_min`、`oa_line_token`（密钥）、`oa_line_to`、`oa_alert_telegram`、`oa_ship_warn_hours`、`oa_cod_fail_rate`、
`oa_bad_review_stars`、`oa_test_days`、`oa_retest_days`、`oa_hero_qty_30d`、`oa_decline_days`、`oa_delist_days`、`oa_lz_sync_min`。

## 文件

- `__init__.py`
- `module.py`  说明书（菜单、设置、待办、后台任务）
- `api.py`  接口 /api/oa/…
- `dash.py`  运营看板
- `lifecycle.py`  商品生命周期
- `lazada.py`  Lazada 财务流水、评价、退货退款、店铺表现（表 oa_lz_*，后台定时同步）
- `todos.py`  交给今日待办的条目
- `alerts.py`  手机提醒（表 oa_alerts，去重、推送、后台定时）
- `line.py`  LINE 推送
- `public.py`  给别的模块用：dashboard()、lifecycle()、lazada_fee_rates()、notify(text)
- 第二期：`mkt_db.py`（表）、`mkt_util.py`（数字 / 网址识别、AI 调用 `core.ai_copy.call`、ERP 取数：SKU 成本、扣点、销量、产能）、
  `comp.py` 竞品、`radar.py` 爆款雷达、`shops.py` 竞店、`plans.py` 计划、`campaigns.py` 营销日历、`traffic.py` 店铺后台数据、
  `mkt_todos.py` 交给今日待办的条目、`mkt_api.py` 接口（/api/oa/comp… 和扩展的 /api/v1/ops/ext/…）、`ui/market.js`、`ui/plan.js`、`tests/t_ops248.py`
- `i18n/th.json`
- `tests/t_ops246.py`
- `ui/page.html`、`ui/ops.js`、`ui/page.js`、`ui/page.css`

## 改动记录

- 1.0（系统 v2.47.0）：新模块。从运营分析系统搬过来看板、商品生命周期、今日待办、LINE 告警，改成直接读 ERP；新加 Lazada 财务流水
  （进财务对账、真实扣点）、评价（差评待办、回复）、退货退款、店铺表现。测试 tests/t_ops246.py。
- 2.0（系统 v2.48.0）：第二期。从运营分析系统搬过来竞品、爆款雷达、竞店、爆款 / 上量计划、营销日历、店铺后台数据，表都在 ERP 里（ops_ 开头）；
  AI 用 ERP 的 AI 设置；成本用 ERP 定价、Lazada 用第一期的真实扣点、产能用生产模块的打印机；计划任务和活动任务进今日待办；
  原来单独的采集插件并进 ERP 的浏览器扩展（v3.0.0，扩展接口 /api/v1/ops/ext/…）。测试 tests/t_ops248.py。
- 2.1（系统 v2.48.0）：竞品、爆款雷达、竞店也给上架客服看：接口里去掉成本 / 利润 / 平台费 / 销售额（mkt_api._strip，扩展密钥也一样），页面隐藏这些列和格子、成本设置项和「AI 估成本」；估成本、流量数据还是只给老板。
- 3.0（系统 v2.49.0）：顶部新大菜单「运营」：经营概况 / 商品表现 / 市场与竞争 / 计划与活动 4 个页面，共用筛选条和页签（ui/hub.js），
  页面用统一组件（static/ux.js）重画成图形；旧页面 id 变成页签（ghost 菜单）；今日待办改成右上角 🔔；运营改动搬进「商品表现 → 待确认的建议」；
  商品表现、流量给上架客服看（没有成本利润）；看板接口支持时间段 / 平台 / 店铺；店铺表现指标名中文 / 泰文、进度条。测试 tests/t_ops246.py、t_ops248.py、tests/cases/t_shell249.py。
- （系统 v2.50.0）：public.market_keywords / market_keyword 给选品模块（候选卡片显示泰国市场数据）；爆款雷达每个关键词加「去模型站找」（POST /api/cur/from-radar：每个模型网站建一个关键词关注，然后打开「商品 → 选品 → 关注巡逻」）。
- （系统 v2.53.0）：运营分析的 AI 走「系统 → AI 接口」的「运营分析」任务；有没有 AI 按这个任务判断。
- （系统 v2.53.0）：看板的扣点（mkt_util.fee_rate）、「售价低于最低价」用费率引擎；看板数据多一个 fee_rates（各平台默认店铺现在用的费率 + 来源）。
