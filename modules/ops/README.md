# 模块：运营分析（ops）

把原来单独部署的「运营分析系统」（/home/user/ops-analytics，通过 /api/v1 读 ERP）并进 ERP：数据直接读 ERP 的表，
不再同步一份镜像。第一期：运营看板、商品生命周期、今日待办与手机提醒、Lazada 运营数据。

## 页面（菜单在「工作台」下面）

- **今日待办**（ops_todo，老板 / 上架客服 / 生产都能看，按角色只显示自己的）：内核 `core/todo.py` 汇总各模块交上来的待办，
  每条「完成」或「忽略」；老板下面还有「手机提醒」：推送渠道、按来源开关、最近推送。工作台首页上也有一张「今日待办」卡片（`static/home.js` 的 `TODO_UI`）。
- **运营看板**（ops_dash，老板）：今天 / 昨天 / 近 7 天（比前 7 天）/ 近 30 天的订单、销售额、利润、利润率；财务口径的 30 天净利润；
  每日销售额图；发货时效（超时、快到期、近 30 天准时率、平均发货小时）；售后与拒收（售后损失、货到付款拒收率、Lazada 退货退款）；
  按平台；利润最高的 SKU；亏本订单；售价低于最低价（ERP 售价或平台上实际卖的价）；Lazada（评价、差评、真实扣点）；生产与耗材；数据健康。
- **商品生命周期**（ops_life，老板）：每个 SKU × 平台：未上架 / 审核中 / 审核不通过 / 测款期 / 未出单·再测 / 建议下架 / 成长 / 主推 / 衰退 / ERP 已下架 / 已下架，
  在售天数、7 / 30 天 / 累计销量、30 天利润、售价和建议动作。规则在「设置 → 运营分析」。
- **Lazada 数据**（ops_lazada，老板；上架客服只看同步状态和评价）：同步状态（出错原因 + 怎么办，例如去 App Console 申请接口权限）、立即同步、
  真实扣点（按费用名）、评价（差评 / 没回复 / 全部，直接回复）、退货退款、店铺表现。

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
- `i18n/th.json`
- `tests/t_ops246.py`
- `ui/page.html`、`ui/ops.js`、`ui/page.js`、`ui/page.css`

## 改动记录

- 1.0（系统 v2.47.0）：新模块。从运营分析系统搬过来看板、商品生命周期、今日待办、LINE 告警，改成直接读 ERP；新加 Lazada 财务流水
  （进财务对账、真实扣点）、评价（差评待办、回复）、退货退款、店铺表现。测试 tests/t_ops246.py。
