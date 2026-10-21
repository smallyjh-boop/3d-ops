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
- `module.py`
- `tests/t_fin.py`
- `ui/finance.js`
- `ui/page.html`
- `ui/page.js`

## 改动记录

- 1.0（系统 v2.30.0）：从内核搬成模块。
- 1.1（系统 v2.32.0）：新增「订单明细」（logic/order_detail.py、ui/orders.js）：每单收入、平台扣费拆分、到账、成本、利润、回款状态，可导出 Excel。
- 1.2（系统 v2.33.0）：订单明细导出平台 / 状态显示中文；手工单扣费来源显示「无平台费（手工单）」。
- 1.3（系统 v2.34.0）：泰文翻译从内核 static/i18n.js 搬到模块自己的 i18n/th.json（只在这个模块里用到的那些），界面不变。
- 1.4（系统 v2.39.0）：对账：订单没有订单金额（Shopee 导出常见）时按商品合计算收入，和损益表、订单明细一致。测试 modules/pur/tests/t_pur239.py。
