# 模块：订单（orders）

订单（基础模块）：订单列表 / 导入 / 手工单 / 审单、打包核对、发货交接、售后、买家档案、每单利润、工作台数据、
打印订单 / 面单 / 交接单、订单用哪个邮政纸箱、浏览器插件转交的平台面单。订单变化通过 core/chain.py 发事件：
生产模块生成生产任务、库存模块发货出库。对外（modules.public("orders")）：box_for(order)、set_box(oid, code)。

## 文件

- `__init__.py`
- `api.py`
- `carriers.py`      自制快递面单模板
- `module.py`
- `labeltext.py`    面单上印的字只用泰文 / 英文（商品名、规格换成产品的泰文）
- `packbox.py`       订单用哪个纸箱（产品设的邮政纸箱里最大的，打包时可改）
- `scanning.py`      打包核对 / 交接扫什么码
- `waybill/`         平台面单框架（来源、模板、排版）
- `tests/t_label_barcode.py`  上传图片型面单 PDF 读条码
- `i18n/th.json`
- `ui/aftersales.js`
- `ui/labels.js`
- `ui/orders.js`
- `ui/pack.js`
- `ui/packbox.js`
- `ui/page.css`
- `ui/page.html`
- `ui/shipping.js`

## 改动记录

- 1.0（系统 v2.31.0）：从内核拆成模块。
- 1.1（系统 v2.32.0）：打包核对 / 发货交接扫什么码可以设置（scanning.py）；每个产品单独设核对方式（扫码 / 点一下确认 / 不用核对）；内部商品标签；打包核对页面从 home.js 搬进模块（ui/pack.js）。
- 1.2（系统 v2.33.0）：自制快递面单模板（carriers.py、ui/labels.js）：9 家快递 + 通用，3 种尺寸，设置里预览，按订单快递公司自动套用；拣货单加货位列。
- 1.3（系统 v2.34.0）：平台面单框架（waybill/）：面单来源（上传的 PDF 现在能用；Shopee / Lazada / TikTok 接口取面单留好位置，接通后实现 connectors 的 fetch_label 即可）、自定义模板（面单下面加信息区或另起一张：订单号、条码、SKU×数量、规格、货位、留言、定制要求、补打提示……）、PDF 转图片自动裁白边 / 横转竖、设置页实时预览、打印记录（补打第 N 次）。订单列表页的代码从 static/ops.js 搬进模块（ui/orders.js）。泰文翻译从内核 static/i18n.js 搬到模块自己的 i18n/th.json（只在这个模块里用到的那些），界面不变。
- 1.4（系统 v2.35.0）：订单纸箱（packbox.py、ui/packbox.js）：默认用订单里各产品的邮政纸箱中最大的一个，订单详情和打包核对页可以改（orders.pack_box，/api/pack-boxes、/api/orders/<id>/pack-box）；订单详情加「发货出库」（纸箱 + 出库单，出库单在库存模块）。浏览器插件转交平台面单：POST /api/v1/labels/import（员工的扩展密钥），按页上的订单号 / 运单号对应订单，日志写「插件 · Shopee」。
- 1.5（系统 v2.39.0）：重新导入 / 平台推送的状态只往前走（已发货、已完成、已取消不会被旧表格改回待发货）；「修改订单」不填金额 = 金额不变，改了商品按差额调整；数量负数 / 0 当 1；正在打印的订单不能删；员工看订单操作记录时金额隐藏；借「登记售后」改成拒收也要「取消/拒收」权限。测试 tests/cases/t_v239.py、modules/inv/tests/t_money239.py。
- 1.6（系统 v2.40.0）：订单离开「待发货」（发货、完成、改回未付款）→ 还没开始的生产任务停下；报价单打完不再自动变成已发货；交接扫码拒收未付款 / 报价单；表格没有平台列时按订单号找已有订单，不重复建；重新导入商品没变就不重建任务（保留指定打印机、任务备注）；Lazada 新版（驼峰列名）、Shopee 英文导出的自动对列修正（整词匹配 + 排除词）；打包核对拒绝已取消 / 退货的订单、显示订单状态；导入结果的新生产任务数修正；售后补发数量不超过原订单、金额不能是负数。测试 tests/cases/t_v240.py。
- 1.7（系统 v2.41.0）：代收货款金额统一写法；改发货时限时校验格式、只记真正改了的字段；坏表格、乱填的商品明细、批量 id 报清楚的错；批量操作有失败时提示哪几单没成；改成「退货」也要取消订单权限；扫码框可以翻译；生产角色看不到用不了的按钮；字段名泰文翻译。测试 tests/cases/t_v241.py。
- 1.8（系统 v2.41.2）：Lazada 面单接通：打印面单时自动从 Lazada 接口取（waybill/sources.fetch 把订单的平台原始编号 raw 带给连接器）。测试 modules/orders/tests/t_waybill.py、modules/link/tests/t_lazada2412.py。
- 1.8 补充：上传平台面单 PDF 时，页面文字里找不到订单号就读条码（core/labels._page_barcodes，pypdfium2 + zxing-cpp），图片型 PDF（Lazada 卖家中心打印的）也能对上订单。测试 modules/orders/tests/t_label_barcode.py。
- 1.9（系统 v2.42.0）：面单只印泰文 / 英文（labeltext.py；平台面单信息区、自制快递面单、旧版自制面单）；「面单下面加信息」面单宽度占满纸、剩下的给信息区（render.split_mm，info_mm 改成最少高度，旧的 34 迁移成 12）。测试 tests/t_label_th.py。
- 1.9 补充：打面单（/api/labels/check、/print/labels）、打包核对、发货交接前先 integrations.refresh_platforms 拉一次平台最新状态，orders.BLOCK_SHIP（已取消 / 退货 / 拒收）拦下。测试 tests/t_v242ship.py（含 10 / 20 / 50 单批量打印）。
- 1.9 补充：信息区按必须印的内容定高度（render.need_mm / split_mm(need)），放不下按优先级减、商品多紧凑排；.wb 高度比纸短 0.4 毫米、break-inside: avoid，不会挤到下一张。
- 2.0（系统 v2.43.0）：订单详情的生产任务加操作（用库存、已打好、已打包、退回重打、换打印机；接口在生产模块），订单详情带每个任务现在可用的成品数（stock_free）；订单列表批量「用库存发 / 标记已打好 / 标记已打包」（/api/jobs/bulk）。
- 2.1（系统 v2.45.0）：面单规格缩写（labeltext.short / platform_spec：ERP 规格优先、颜色在前、去前缀 / 括号 / 默认规格、每段 16 字），规格排在商品名前面。
- 2.2（系统 v2.46.0）：面单商品清单可编辑：表格 / 列表两种样式，列（图片、商品、规格、SKU、产品编号、数量、货位）开关和顺序，数量画圈、商品名行数；每个平台可以单独一套内容（纸张和布局共用）；打印时信息区放不下的订单提示「这次单独打一张商品清单」（layout=page）。
