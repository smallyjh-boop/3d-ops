# 3D 运营管理系统（3d-ops）

泰国 3D 打印电商的运营管理系统：商品与上架（Lazada / Shopee / TikTok）、订单、生产排单、库存采购、财务、AI 客服。

- 使用说明和更新记录：`README.txt`
- NAS 部署：`NAS_SETUP.txt`
- 测试：`python tests/run_all.py`

## 发布与在线更新

发版 = 推到 `main` 分支，版本号就是 `app.py` 里的 `VERSION`。NAS 上的系统每 12 小时检查一次 main 分支的版本，
比现在新就在「系统检查与升级」页提示，老板点「立即更新」后下载那个提交的源码包升级（先备份程序，不动数据，自动重启）。
私有仓库需要在 设置 → 通用 → 在线更新 填一个只读令牌（Fine-grained token，只给这个仓库 Contents: Read-only）。
