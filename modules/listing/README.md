# 模块：上架导出（listing）

上架导出：导出 Lazada / Shopee 上架表格、上架批次和平台状态、库存待同步到平台。
关掉后「导出上架表格」页面不出现，产品资料不受影响（导出过的 SKU 照样锁定）。

## 文件

- `__init__.py`
- `api.py`
- `lazada_push.py`  ERP 产品直接推到 Lazada（接口）、库存推送
- `module.py`
- `online.py`  在线商品：从店铺拉商品、对上 ERP、改价改库存、上下架
- `public.py`  给别的模块用：online_shops()、online_skus()、online_item_ids()、online_item_names()
- `ui/online.js`
- `tests/t_online244.py`
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
- 1.6（系统 v2.43.1）：推送按 Lazada 官方文档改格式（值用字符串、variation1/2、saleProp、hasImage 规则、标准 color_family 或自定义变体、ASCII JSON）；图片直接传本地文件（/image/upload，不用图床）；记下最后一次推送内容（/api/listing/lazada/last/<产品>）；工作台「上传图床」修复按钮。测试 tests/t_lzpush2412.py。
- 1.7（系统 v2.43.2）：属性 / 变体选项发英文选项名（_opt_out：en_name），按选项 id 或泰文 / 英文名对；选项 id 是 0 时按名字对。
- 1.8（系统 v2.44.0）：在线商品（online.py、ui/online.js、/api/online…）：Lazada /products/get 拉全店商品存 online_items，按 SellerSku 对上 ERP 并记下 item_id / sku_id、上架状态跟平台走；改价改库存（/product/price_quantity/update，写回 ERP manual_price / stock）、上下架（/product/deactivate、/product/update）；定时同步改成整店拉；public.online_shops() 给产品库。测试 tests/t_online244.py。
- 1.9（系统 v2.44.1）：推送时详情后面接产品图（lazada_push.desc_images：desc_images 或前 3 张）；工作台「按状态（自动）」分组。
- 2.0（系统 v2.46.0）：详情里自己插的图片推送时换成 Lazada 图片空间的网址（desc_img_urls：本系统产品图上传、外站图 migrate、Lazada 的不动、换不了的去掉），有图片就不再自动接图。测试 tests/t_desc246.py。
- 2.1（系统 v2.47.0）：public 加 online_skus()（每个 SellerSku 在哪些店铺、平台状态、建品时间、实际售价）、online_item_ids()、online_item_names()，给运营分析模块（商品生命周期、售价低于最低价、按商品拉评价）用。测试 modules/ops/tests/t_ops246.py。
