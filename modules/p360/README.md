# 模块：商品 360（p360）

任何页面上点 SKU / 产品编号，右边滑出这个商品的全部情况（电脑约 540px 宽，手机全屏）。Esc / × / 点灰色背景关闭，‹ › 在看过的商品之间前后切换。

## 页面上怎么接

- 在显示 SKU 或产品编号的元素上加 `data-p360="3DP0015-WH"`（或 `data-p360="3DP0015"`），别的不用做。
  - 普通文字 / 单元格（`span`、`td`、`b`、`div`）：点一下直接打开（点击不再传给外面的整行，比如产品库整行点开编辑）；在选文字复制时不打开。
  - 本身是链接 / 按钮 / 整行（`a`、`button`、`tr`、`[onclick]`、`[role=button]`）：不抢它原来的点击，`static/p360.js` 自动在旁边加一个小「ⓘ」。
  - 代码里：`P360.open("3DP0015-WH")`、`P360.icon(sku)`（返回「ⓘ」按钮的 HTML）、`P360.close()`、`P360.refresh()`。
- 前台文件在内核：`static/p360.js`（全局点击、抽屉、渲染）、`static/p360.css`（`static/index.html` 里跟在 ux.js / style.css 后面加载）。
  界面文字用 `Z(中文, 泰文)`，抽屉整体 `data-notr`（不走自动翻译）。

现在带 `data-p360` 的地方：产品库（编号、SKU）、订单列表 / 订单详情（商品、生产任务）、每单利润的 SKU 表、售后详情、库存管理（成品）、货位里的物品（成品）、
生产看板（任务卡、打印机这一盘）、成品库存 / 备货建议、上架工作台（编号）、在线商品（ERP 编号、SKU）、库存待同步。

## 接口

`GET /api/p360/<SKU 或产品编号>`（大小写都认）。找不到：404 `{error, error_th, not_found: true}`。生产角色也能用。

```
{ ok, role, owner, prices, focus（选中的规格序号，按产品编号打开时为 null）, target,
  product: {id, name_zh, title_th, image, images[], material, opt1_name, opt2_name, active, draft, updated_at, edited_at, edited_by,
            listing: {lazada|shopee: {status, status_zh, first_listed_at, note}}},
  variants: [{idx, sku, opt1, opt2, image, stock, reserved, free, target, location?: {code, zh, th},
              price?, list_price?（老板 + 上架客服）, floor_price?, cost?, fee?, profit?, markup?, below_floor?, warning?（只有老板）}],
  online?: [{platform, shop, item_id, status, status_zh, raw_status, reason, url, price_min?, price_max?, qty, skus[]}]   ← 上架模块开着
  sales: {days: [{day, qty}]×30, qty_30d, revenue_30d?},
  lifecycle?: [{sku, platform, stage, label, label_th, level, action, action_th, start, qty_30d, last_sale}]   ← 运营分析开着，老板 + 上架客服
  traffic?: [{sku, platform, visitors, views, add_to_cart, orders, conversion, period_text, ts}]
  comp?: {rows: [{id, platform, title, shop, url, image, price（到手价）, rating, reviews, sold_text}], median, min, max, my_price, rank?: {rank, of}, vs_median_pct}
  reviews?: {n, avg, bad, items: [{rating, content, created, reply}]}      ← 运营分析 + 上架模块开着（Lazada 评价按在线商品编号）
  plans?: [{id, sku, platform, kind_label, kind_th, days, elapsed, target_daily, avg7, status_label, status_th, tasks_due[], actual_profit?（老板）}]
  changes?, pending?: [{ts, who, what, what_th, sku, reason, status, source: ops|audit|edit}]   ← 老板 + 上架客服；操作记录（audit）只给老板
  suggestions: [{tone, zh, th, go?}],
  jobs: [{id, sku, qty, remaining, status, status_zh, kind, order_no, printer_code}],
  orders: [{id, order_no, platform, status, status_zh, order_time, sku, variation, qty, unit_price?, item_total?}]（最近 8 条）,
  kpi: {stock, free, sold_30d, spark[30], profit_unit?, profit_min?, profit_max?, stage?, rating?, reviews?} }
```

权限：老板全部；上架客服没有成本 / 最低价 / 平台费 / 利润；生产员工连售价、订单金额都没有，也没有运营数据（生命周期、流量、竞品、评价、计划、改动）。
模块关着：对应的 key 不出现（库存模块关 → 没有货位；上架模块关 → 没有 online / reviews；运营分析关 → 没有 lifecycle / traffic / comp / reviews / plans；对接模块关 → 没有运营改动）。

数据来源：产品 / 定价（core.store、core.pricing）、成品库存（core.production）、货位（`modules.public("inv")`）、在线商品（`modules.public("listing").product_online`）、
生命周期规则（modules/ops/lifecycle 的 rules / _start / _stage，和「商品生命周期」页一样）、流量（ops.traffic.get）、竞品（ops.comp + 关联表）、
评价（oa_lz_review）、计划（ops.plans.progress / tasks）、运营改动（`modules.public("link").opsapi.list_changes`）、操作记录（core.db.audit_list）、生产任务和订单（内核表）。
只读，不缓存；一块出错只记日志、那块不显示。

## 文件

- `module.py`（core：和产品库一样不能关）、`api.py`、`logic.py`（汇总）、`tests/t_p360.py`
- 前台：`static/p360.js`、`static/p360.css`

## 改动记录

- 1.0：第一版（抽屉 + 接口 + 各页面的 data-p360）。测试 tests/t_p360.py（老板 / 上架客服 / 生产员工、模块关掉那块不出现、找不到 404）。
- （系统 v2.50.0）：选品采用的草稿许可待核验时，抽屉里显示「许可待核验」标签和「核验许可」按钮（POST /api/products/<编号>/license）。
- （系统 v2.50.1）：选品采用的产品：抽屉里显示模型文件个数 / 下载状态、「⬇ 下载模型文件」按钮（POST /api/cur/products/<编号>/download）、没有在线扩展时的提醒、「在采集箱」标签（数据来自 modules.public("curate").product_files）。
- （系统 v2.53.0，static/p360.js）：「生产中」卡片加「➕ 生产」，新增「试打记录」卡片（次数、成功率、常见问题、照片、再试一次）。
