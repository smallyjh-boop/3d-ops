# 模块：上架导出（listing）

上架导出：导出 Lazada / Shopee 上架表格、上架批次和平台状态、库存待同步到平台。
关掉后「导出上架表格」页面不出现，产品资料不受影响（导出过的 SKU 照样锁定）。

## 文件

- `__init__.py`
- `api.py`
- `module.py`
- `ui/export.js`
- `ui/page.html`
- `ui/stock.js`

## 改动记录

- 1.0（系统 v2.31.0）：从内核拆成模块。
- 1.1（系统 v2.34.0）：泰文翻译从内核 static/i18n.js 搬到模块自己的 i18n/th.json（只在这个模块里用到的那些），界面不变。
- 1.2（系统 v2.40.0）：导出 Shopee 时记 exported_first=shopee，Lazada 导出后去掉；core/listing.exported_to() 判断导出过哪个平台；库存待同步按平台判断。
