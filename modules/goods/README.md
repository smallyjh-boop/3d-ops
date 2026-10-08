# 模块：商品（goods）

商品（基础模块，不能关）：产品库、编辑产品、图片 / 修图 / 卖点图 / 场景图、AI 文案、类目与属性、分组、规格与 SKU、
按耗材自动算库存（库存待同步到平台）。产品资料和数据在 core/store.py 等（主链路的数据层）。

## 文件

- `__init__.py`
- `api.py`
- `module.py`
- `ui/adimg.js`
- `ui/imgedit.js`
- `ui/page.html`
- `ui/scene.js`
- `ui/specmodel.js`

## 改动记录

- 1.0（系统 v2.31.0）：从内核拆成模块。
- 1.1（系统 v2.32.0）：编辑产品加「打包时怎么核对这个产品」。
