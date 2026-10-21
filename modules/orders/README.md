# 模块：订单（orders）

订单（基础模块）：订单列表 / 导入 / 手工单 / 审单、打包核对、发货交接、售后、买家档案、每单利润、工作台数据、
打印订单 / 面单 / 交接单、订单用哪个邮政纸箱、浏览器插件转交的平台面单。订单变化通过 core/chain.py 发事件：
生产模块生成生产任务、库存模块发货出库。对外（modules.public("orders")）：box_for(order)、set_box(oid, code)。

## 文件

- `__init__.py`
- `api.py`
- `carriers.py`      自制快递面单模板
- `module.py`
- `packbox.py`       订单用哪个纸箱（产品设的邮政纸箱里最大的，打包时可改）
- `scanning.py`      打包核对 / 交接扫什么码
- `waybill/`         平台面单框架（来源、模板、排版）
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
