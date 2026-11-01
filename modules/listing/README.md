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
- 2.1+：`public.product_online(产品编号, SKU 列表)`：一个产品在各店铺的在线商品（商品 360 抽屉用）；工作台 / 在线商品 / 库存待同步的产品编号、SKU 带 `data-p360`（点开商品 360）。
- 2.2（系统 v2.49.0）：「商品」菜单只留「上架」一个：上架工作台 / 在线商品 变成页面顶上的两个页签（在线商品是 ghost 菜单，旧链接 #online 照样能打开）。
- （系统 v2.53.0）：上架工作台 / 在线商品 → 编辑产品 →「← 返回」回到原来的平台、阶段、分组、第几页、搜索和滚动位置，那一行闪一下（NAV.keep，static/nav.js）。
- 2.3（系统 v2.53.0）：「库存同步」页签重做成库存对照总表（stocksync.py、stockadapters.py、stocksync_api.py、ui/stocksync.js，接口 /api/stocksync/*）：可售 = 成品库存 − 订单占住 − 安全库存（+ 按需打印虚拟库存：耗材够做几件，沿用 stockcalc 按耗材自动算库存，上限 / 打印机产能，不够掉 0）；规则全局（设置 ss_*）/ 产品 / SKU / 店铺逐级覆盖；多店铺 share / percent / fixed；成品库存变化（core/production 广播 stock.changed）和订单状态变化即时同步 + 定时检查（拉平台库存、对照、推待同步、失败退避重试）；SKU×店铺状态（已同步 / 待同步 / 同步失败 / 已锁定 / 平台已下架）、数字卡片（待同步 / 失败 / 对不上 / 快卖完 / 已超卖，点击筛选）、行内改数字 Enter 推送、批量（推送 / 重算 / 安全库存 / 分配 / 设 0 / 恢复 / 锁定）、一键全部重推；同步记录（ss_log，筛选、重试失败）；没接口的店铺（Shopee 等）出待导出表 +「已上传」；适配器 stockadapters.register("shopee", …) 接口通了自动改直接推送；待办（失败重试用完 / 对不上 / 快卖完 / 超卖 / 超过 1 天没同步）；商品 360 加「库存同步记录」块（public.stock_sync_recent）。测试 tests/t_stocksync253.py。
- （系统 v2.53.0）：上架工作台自动分类（wbgroups.py，共用 static/groups.js）：先选平台 + 店铺，所有分类按这个店铺现算；进度（未上架 → 资料不全 → 可推送 → 推送中 → 审核中 → 被拒 → 在售 → 已下架，平台状态来自在线商品同步）；待处理（被拒带原因 / 类目属性没填 / 图片不合规 / 标题太长 / 售价低于成本 / 平台价格或库存和系统对不上 / 在售但没库存）；表现（这个店铺近 30 天 热销 / 滞销 / 新上架 / 利润低，阈值和产品库同一套）；铺货机会（别的店铺卖得好、这个店铺还没上，勾选 →「上到这个店铺」，POST /api/listing/lazada/push 带 shop_id，第二个店铺的记录单独存在 lazada_api_shops，不动主店铺）；手动标记 要上架 / 要改价 / 要改图（做完自动取消）；保存为视图；返回时记得平台 / 店铺 / 分类 / 页码。库存同步页签没动。测试 modules/listing/tests/t_workbench_groups253.py。
- （系统 v2.53.0）：Shopee 导出表按 Shopee 的费率定价（platform="shopee"，不再临时改设置）；上架工作台「售价低于成本」：店铺有真实费率时按费率引擎算（线上正在卖的价 / ERP 售价扣掉这个店铺的费用后低于成本），没有真实费率沿用产品库的算法。
- （系统 v2.53.0）：库存同步上线前审查修复：① 新增「自动推送总开关」ss_auto_push（默认关，升级安全）——关着只拉平台库存、对照表显示差异（顶部提示「自动推送未开启」），事件 / 定时 / 整店规则变更都不自动推，手动推送不受影响；第一次拉到的平台数记为「上次推的数」（基线），数字没变化之前不推；没开自动库存的变体沿用旧数（手填 / 默认库存，不是实物库存），也不算超卖；默认上限沿用旧的 stock_cap（50）。② 开了自动推送后 lazada_push 旧的库存自动推送循环不再推（单一来源），关着时保持旧行为。③ 接口店铺只给 SKU 真在的店铺建单元格（在线商品表有，或 lazada_api / lazada_api_shops[店铺] 里记着），编号按店铺分开（stockadapters.product_ids），不再拿主店铺编号去推第二个店铺。④ 批量锁定必须填数量。⑤ 锁定的推送失败不写「已锁定」，之后照常重试。测试 tests/t_stocksync253.py。

- （系统 v2.53.0）复审修复：库存事件批次记「库存变化（event）」不再记成手动，自动推送开关在防抖后推送前再核对一次（关了就不推）；第一次拉到平台数时同时写 pushed_at，自动推送关着时不报「超过 1 天没同步」。测试 modules/listing/tests/t_stocksync253.py。
