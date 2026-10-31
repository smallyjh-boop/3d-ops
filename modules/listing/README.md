# 模块：上架导出（listing）

上架导出：导出 Lazada / Shopee 上架表格、上架批次和平台状态、库存待同步到平台。
关掉后「导出上架表格」页面不出现，产品资料不受影响（导出过的 SKU 照样锁定）。

## 文件

- `__init__.py`
- `api.py`
- `lazada_push.py`  ERP 产品直接推到 Lazada（接口）、库存推送
- `module.py`
- `workbench.py`  上架工作台：缺什么和怎么修、原地确认、AI 补齐
- `ui/page.css`
- `tests/t_lw243.py`
- `tests/t_lzpush2412.py`
- `ui/export.js`
- `ui/page.html`
- `ui/stock.js`

## 改动记录

- 1.0（系统 v2.31.0）：从内核拆成模块。
- 1.1（系统 v2.34.0）：泰文翻译从内核 static/i18n.js 搬到模块自己的 i18n/th.json（只在这个模块里用到的那些），界面不变。
- 1.2（系统 v2.40.0）：导出 Shopee 时记 exported_first=shopee，Lazada 导出后去掉；core/listing.exported_to() 判断导出过哪个平台；库存待同步按平台判断。
- 1.3（系统 v2.41.0）：批量移动到别的批次时计数正确。
- 1.4（系统 v2.42.0）：直接推送到 Lazada（lazada_push.py：图片搬到 Lazada、表格字段代码 → 接口属性按 id 对、/product/create 或 /product/update、推完状态「平台审核中」并锁 SKU）；库存待同步「推到 Lazada」和定时自动推（lazada_stock_sync_min）。测试 tests/t_lzpush2412.py。
- 1.5（系统 v2.43.0）：「导出上架表格」页改成上架工作台（平台切换、流程条、分组栏、分页、底部操作条、批次 / 库存同步分页）；缺什么原地展开修（workbench.py：/api/listing/issues、/api/listing/fix、/api/listing/ai-fill）；推送走后台任务（?async=1）；Lazada 审核结果自动同步（lazada_push.sync_status，每 30 分钟，/api/listing/lazada/status-sync）。测试 tests/t_lw243.py。
