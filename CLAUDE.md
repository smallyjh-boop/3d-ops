# 项目说明（Claude 每次会话自动读取，保持简短）

## 项目
- 名称：3d-ops（3D 打印电商 ERP）
- 一句话：泰国 3D 打印网店的内部 ERP：商品 / 上架（Lazada、Shopee、TikTok）/ 订单 / 生产（打印机、切片）/ 仓库 / 采购 / 财务 / 客服 / 运营 / 选品
- 当前阶段：上线中。NAS（http://192.168.31.200:8790）自动跟随 `main` 更新
- 沟通：全部用中文；老板习惯先出方案、确认后一次性做完；新想法先记备忘，说「一起改」时一起做

## 技术栈
- 后端：Python 3 + Flask（waitress），SQLite（core/db.py），数据在 `data/`（LH_DATA_DIR 可改）
- 前端：原生 JS（static/app.js、static/ux.js 统一组件、各模块 ui/*.js），无构建步骤
- 切片：OrcaSlicer 命令行（core/slicer.py、core/orca_profiles.py）
- 浏览器扩展：extension/（选品采集、运营、客服）
- 安卓：android/（Kotlin、CameraX + ML Kit），CI .github/workflows/android.yml
- 部署：NAS Docker（docker-compose.yml、NAS_SETUP.txt）

## 常用命令
- 启动：`python app.py --no-browser`（测试时加环境变量 LH_NO_MODULE_STARTUP=1 LH_NO_TPL_SYNC=1）
- 测试：`python3 tests/run_all.py [名字 | 模块名 | 模块/测试名]`（全量很慢，分组跑；ops_test 和 t_v1 要放在同一组）
- 多语言检查：`python tests/ui/i18n_check.py --quick`（泰语界面不能出现中文）
- 测试后删除 `templates_lazada/lazada_auto_*.xlsx`
- 已知：没装 OrcaSlicer 的机器上 v20_test 会失败

## 目录结构
- `app.py`：入口，VERSION 在这里
- `core/`：通用逻辑（db、config、slicer、production、inventory、connectors/lazada.py …）
- `web/`：通用接口
- `modules/<id>/`：功能模块（module.py 里的 MODULE 定义菜单 / 权限 / 待办；api.py；ui/；i18n/th.json；tests/；README.md）
- `static/`：外壳（app.js、shell.js、ux.js、p360.js、style.css）
- `tests/`：测试运行器、通用测试、基础数据 fixtures
- `docs/`：PLAN.md、HANDOVER.md

## 规范
- 界面文字用 `Z(中文, 泰文)` 或模块 i18n/th.json；原始数据加 `data-notr`，故意双语加 `data-i18n-ok`
- 页面布局：数字卡片 → 图表 → 明细表（用 static/ux.js 的 UX.kpis / bars / meter …）
- 新功能附带测试（modules/<id>/tests/t_*.py，参考现有写法）
- 发版：改 app.py VERSION + static/app.js APP_JS_VERSION + static/api-docs.html 示例，README.txt 写更新说明，模块 README 写「系统 vX」条目
- 提交信息说明改了什么；代码、注释、提交正文里不写 AI 模型名（提交末尾固定的 Co-Authored-By 署名行除外，照常保留）

## 禁止
- 不要让老板在聊天里贴 App Secret / 密码（只在系统里填）
- 不要提交 data/ 下的数据、.env、密钥
- 不经确认不直接推 main（「发版」= 开发分支快进到 main）
- 不用会匹配到自己 shell 的 pkill 模式

## 工作方式（省 token）
- 开始新任务前先读 `docs/HANDOVER.md` 和 `docs/PLAN.md`
- 大范围查找交给 `code-searcher`，跑测试交给 `test-runner`，泰文补齐交给 `translator`
- 只读完成任务所需的文件；不读 data/、__pycache__、大 JSON、日志
- 回复简洁：说改了什么、为什么
- 任务做完后更新 `docs/HANDOVER.md`
