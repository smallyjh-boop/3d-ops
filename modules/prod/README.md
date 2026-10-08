# 模块：生产（prod）

生产：生产看板（排单、打印批次）、打印机（连接、状态、保养）、文件管理、打印方案 / 切片文件、质量统计、
耗材料卷（补货计划）、成品备货。接订单模块的事件 order.changed（生成生产任务）和 chain.reschedule（重新排单）。
关掉后：新订单不生成生产任务、不轮询打印机；订单照常导入、发货。

## 文件

- `__init__.py`
- `api.py`
- `events.py`
- `module.py`
- `ui/files.js`
- `ui/materials.js`
- `ui/page.html`
- `ui/prod.js`
- `ui/recipe.js`
- `ui/spools.js`

## 改动记录

- 1.0（系统 v2.31.0）：从内核拆成模块。
