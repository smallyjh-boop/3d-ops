# 模块：店铺与系统对接（link）

店铺与系统对接——v2.30 从内核搬出来的模块。

· 店铺对接：平台开放接口定时拉订单、授权、平台 Webhook 推送（连接器在 core/connectors，订单入库在内核）。
· 3D选品工具：推送新产品建草稿（/api/v1/catalog/…、/api/v1/categories），设置里填选品工具地址和密钥。
· 运营分析系统写回：/api/v1/ops/…（ops 密钥）改标题、属性、售价、上下架；「商品 → 运营改动」查看 / 确认 / 撤回。
API 密钥管理和只读查询接口（/api/v1/orders、skus、cost-params、profit…）在内核，关掉这个模块不受影响。

## 文件

- `__init__.py`
- `api.py`
- `curator.py`
- `module.py`
- `opsapi.py`
- `tests/t_lazada2412.py`
- `ui/opschg.js`
- `ui/page.html`
- `ui/settings.html`
- `ui/settings.js`

## 改动记录

- 1.0（系统 v2.30.0）：从内核搬成模块。
- 1.1（系统 v2.34.0）：泰文翻译从内核 static/i18n.js 搬到模块自己的 i18n/th.json（只在这个模块里用到的那些），界面不变。
- 1.2（系统 v2.41.2）：Lazada 店铺授权：店铺设置加「Callback URL（回调地址）」（可不填），授权页按它跳转（Lazada 只认 https）；换 token 时可以粘贴授权后地址栏的整个网址；Lazada 取面单（core/connectors/lazada.fetch_label：现取包裹号 → /order/package/document/get 取 PDF）；订单带付款方式、代收货款、快递。测试 tests/t_lazada2412.py。
