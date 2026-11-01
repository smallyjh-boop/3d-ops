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
- [x] T8：AI 接口统一管理（v2.53.0）
- [x] T9：场景图改进（v2.53.0）
- [x] T10：「返回」回到原来的地方（v2.53.0）｜static/nav.js + 各入口｜测试 tests/cases/t_nav253.py
- [x] T11：模型区改进（v2.53.0）：展示 / 打印分开、组装选零件 + 按接合位置自动组合、默认收起、按规格（不只尺寸）设置展示和打印方案、总览表、一键切片、组装生成打印方案、爆炸图、撤销｜modules/model、modules/goods、core/specmodel.py、core/modellib.py
- [x] T12：仓库全部物品进货位（v2.53.0）：料卷货位、生产区 / 待检区、采购 / 生产 / 发货 / 退货走货位、补货提醒、按库区算库存金额、手机操作、迁移｜modules/inv、core/materials.py、modules/pur、modules/mobile
- [x] T14：产品库 + 采集箱自动 / 动态分组（v2.53.0）：在线 / 未上线、进度、待处理、销售表现、类目来源、手动只做标记、保存视图｜modules/goods、modules/curate
- [x] T15：选品候选池整理 + 清理（v2.53.0）｜modules/curate
- [x] T16：上架工作台自动分类（v2.53.0）｜modules/listing
- [x] T17：库存同步重做（v2.53.0）：规则、对照总表、快速修改、预警、记录｜modules/listing、core/connectors/lazada.py
- [x] T18：打印机「网络诊断」按钮（端口逐个测、超时 / 拒绝、NAS 网口和路由、识别同网段两网口）｜core/printers.py、modules/prod
- [ ] T19：没有订单也能生产 / 试打：➕ 生产、🧪 试打 + 试打结果、🔍 检查切片文件、打印机打印测试、看板按类型区分｜core/production.py、modules/prod、modules/model
- [ ] T20：动态成本核算：实际结算倒推店铺 × 类目 × 费用项费率、Shopee 定期检测、定价拆分费用、费率变化预警、平台费率页｜core/pricing.py、modules/fin、modules/ops
- [ ] T13：发 v2.53.0｜测试交给 test-runner、发版前 reviewer 审查、泰文缺口交给 translator

## 不做的事
- 不迁移旧选品工具的数据
- Shopee 接口还没绑定，财务先用导入
