# 开发计划（由 /plan 生成，/go 逐条执行）

## 目标
发布 v2.52.0，然后做 v2.53.0

## 任务清单
- [x] T1：仓库 / 货位管理（WMS）｜modules/inv｜已合并
- [x] T2：展示模型 / 打印方案 / 多色 / 摆盘｜modules/model、core/slicer.py｜已合并，真实 OrcaSlicer 验证通过
- [x] T3：采集队列提速 + 队列管理｜modules/curate、extension｜已合并
- [x] T4：拍照识别产品 + 读文字｜modules/recog、android｜已合并
- [x] T5：多盘成品按盘排生产｜core/production.py、modules/prod｜验收：两盘都打完才加库存，失败只重打那一盘
- [x] T6：识别补完（本机实测、学习照片管理、各扫码框拍照、难认产品提示）｜modules/recog、modules/inv、modules/mobile
- [x] T7：发 v2.52.0｜app.py、static/app.js、static/api-docs.html、README.txt｜验收：分组全量测试通过 + 多语言检查通过
- [ ] T8：AI 接口统一管理（v2.53.0）
- [ ] T9：场景图改进（v2.53.0）
- [x] T10：「返回」回到原来的地方（v2.53.0）｜static/nav.js + 各入口｜测试 tests/cases/t_nav253.py

## 不做的事
- 不迁移旧选品工具的数据
- Shopee 接口还没绑定，财务先用导入
