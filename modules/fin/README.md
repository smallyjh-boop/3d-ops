# 模块：财务（fin）

电商财务——v2.30 从内核搬出来的模块（原来的 core/fin/ 现在是 modules/fin/logic/，接口是 api.py）。

总览与损益、利润分析、平台结算对账、收支记账（带票据）、现金流、税务（VAT）；
对外只读接口 /api/v1/finance/{pl,breakdown,cashflow,expenses,tax}（密钥权限 finance）。
「每单利润」和库存 / 采购记的财务事件（/api/v1/finance/events、/inventory）在内核里，关掉财务模块不影响。

## 文件

- `__init__.py`
- `api.py`
- `logic/__init__.py`
- `logic/book.py`
- `logic/common.py`
- `logic/reports.py`
- `logic/settle.py`
- `logic/recon.py`
- `module.py`
- `tests/t_fin.py`
- `tests/t_recon249.py`
- `ui/finance.js`
- `ui/page.html`
- `ui/page.js`
- `ui/orders.js`
- `ui/settle.js`
- `ui/boot.js`
- `ui/page.css`

## 改动记录

- 1.0（系统 v2.30.0）：从内核搬成模块。
- 1.1（系统 v2.32.0）：新增「订单明细」（logic/order_detail.py、ui/orders.js）：每单收入、平台扣费拆分、到账、成本、利润、回款状态，可导出 Excel。
- 1.2（系统 v2.33.0）：订单明细导出平台 / 状态显示中文；手工单扣费来源显示「无平台费（手工单）」。
- 1.3（系统 v2.34.0）：泰文翻译从内核 static/i18n.js 搬到模块自己的 i18n/th.json（只在这个模块里用到的那些），界面不变。
- 1.4（系统 v2.39.0）：对账：订单没有订单金额（Shopee 导出常见）时按商品合计算收入，和损益表、订单明细一致。测试 modules/pur/tests/t_pur239.py。
- 1.5（系统 v2.40.0）：固定费用按项估算（记了房租，人工、折旧、维修照估）；每单利润：开 VAT 且价格含税时按不含税收入算，「每件包材」按件数算；结算表同一个文件里一模一样的两行都算（再导一次仍去重）。测试 tests/t_v240fin.py。
- 1.6（系统 v2.41.0）：利润构成每个产品每单只算一次；月份 / 自选日期的总览一致；不含税模式下的销项税单独一行说明；导出的付款方式写中文、选项顺序固定；结算表对列出错时提示清楚。测试 tests/cases/t_v241.py。
- 1.7（系统 v2.47.0）：新增 settle_import_lines()：别的模块用接口拉到的结算明细（运营分析模块的 Lazada 财务流水）直接记进平台对账，按每行的平台编号去重，对上的订单写「实际到账」，利润按真实扣费算。测试 modules/ops/tests/t_ops246.py。
- 1.8（系统 v2.49.0）：菜单 8 个并成 5 个：总览（损益 + 利润分析图）· 订单利润（订单明细和订单模块的「每单利润」并成一张表，可按订单 / 平台 / 店铺 / SKU / 天看）· 平台对账 · 收支与现金流（两个页签）· 税务；旧菜单 fin_profit / fin_cash / profit 跳到新页面。页面统一用 UX 组件（数字卡片 → 图 → 表）。平台对账自动化（logic/recon.py）：Lazada 财务流水（运营分析模块每小时拉）+ 结算单 GetPayoutStatus（/finance/payout/status/get，本模块每小时拉，表 fin_payouts）→ 每单自动标 已到账 / 已结算 / 待回款 / 超时未回款 / 平台没结算 + 扣费异常，每单显示来源（接口 / 导入表格 / 估算）、可展开看费用拆分、可标「已核对」（表 fin_checked）；顶部每个平台的数据状态卡片和「立即同步」；Shopee / TikTok 超过 fin_import_remind_days（默认 14）天没导入进今日待办（分组「财务」）。测试 tests/t_recon249.py。
- 1.9（系统 v2.50.0）：平台对账加「运费核对」页签（recon.ship_check）：平台结算明细里扣的运费（运费类、负数的行）和订单的运费（订单表运费 → 买家付的运费 → 明细里买家付的运费）比，差额超过 fin_ship_tolerance（默认 5 铢）的列出来，可以标已核对。测试 modules/orders/tests/t_orders250.py。
- 2.0（系统 v2.53.0）：平台费率引擎 core/feerates.py + 新菜单「平台费率」（fin_fees，菜单 5 → 6）。用平台结算流水（Lazada 财务流水 oa_lz_tx；Shopee 导入的报表 fin_settle_lines）算近 30 / 90 天的真实费率，按 店铺 × 类目 × 费用项（佣金 / 支付手续费 / 运费差额 / 活动·优惠券分担 / 其他），百分比和每件固定金额分开（固定费用按件摊）；快照表 fee_rate_snap（带样本订单数、更新时间）、走势 fee_rate_hist、类目默认 fee_defaults、费率变动 fee_events；每天自动重算（fees.start，LH_NO_MODULE_STARTUP 时不跑），导入报表后马上重算。回退链：店铺×类目（样本 ≥ fee_min_orders，默认 10）→ 店铺整体 → 类目默认 → 平台默认（旧设置 platform_fee_rate / shopee_fee_rate 原值保留就是平台默认，页面改它会同步回设置）；每个结果标「实际 / 默认」。适配器接口 feerates.Adapter / register(平台, 适配器)：Shopee 现在是导入适配器，以后有接口换一个适配器即可。待办：Shopee 7 天没导入 → 提醒下载导入；任一平台费用项变化超过 0.5 个百分点 → 「费率变了 / Shopee 费率可能调整了」，列出利润低于最低加价率的产品，页面上「按新费率重算建议价」把手动价过低的变体改回建议价并打「要改价」标记。接口：/api/fin/fees、/fees/refresh、/fees/defaults、/fees/min_orders、/fees/recalc、/fees/ack。测试 modules/fin/tests/t_feerates253.py。
- 2.0（系统 v2.53.0）复审修复：实际费率有范围保护（百分比 < 0 或 > 80%、每件固定费用 < 0 或 > 500 泰铢 = 数据异常，resolve 忽略它、退回下一级 / 默认值，并出「费率不正常」待办；price_for / fee_rate_for 对坏数据不抛错、不除零、不出负价）；「按新费率重算建议价」只动有手动价且受影响的变体，手动价是各平台共用的——产品还挂在别的平台就只标「要改价」；清手动价前存 manual_price_prev（+谁 / 何时）、写 fee_recalc_log 和审计，确认框列出具体改动，页面有「撤销」；受影响产品检查不再只看前 500 个。
