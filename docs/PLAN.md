# 开发计划（由 /plan 生成，/go 逐条执行）

## 目标
v2.52.0、v2.53.0 已发布；v2.54.0 已发布

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
- [x] T19：没有订单也能生产 / 试打：➕ 生产、🧪 试打 + 试打结果、🔍 检查切片文件、打印机打印测试、看板按类型区分｜core/production.py、modules/prod、modules/model
- [x] T20：动态成本核算：实际结算倒推店铺 × 类目 × 费用项费率、Shopee 定期检测、定价拆分费用、费率变化预警、平台费率页｜core/pricing.py、modules/fin、modules/ops
- [x] T13：发 v2.53.0｜测试交给 test-runner、发版前 reviewer 审查、泰文缺口交给 translator
- [x] T21：打印机管理重做（机群）：按厂商表单、列表 + 抽屉、机型模板、局域网发现 / 表格导入、分组位置角色、批量操作、机群总览、可扩展连接架构、稳定编号（v2.54.0）｜core/printers.py、core/fleet.py、modules/prod、static/app.js
- [x] T22：成品备货重做 + 生产单（专用机器、角色、暂停）（v2.54.0）｜modules/inv、core/production.py、modules/prod、modules/pur
- [x] T23：删除旧的外部 3D选品工具对接（v2.54.0）｜modules/link、web/integrations.py、modules/goods
- [x] T24：发 v2.54.0：reviewer 审查 → test-runner 全量 → 发版

## 备忘（老板说「不着急发版」：做完先放开发分支，等老板说再发）
- [ ] T25：候选池操作逻辑重做（每条可删除 / 调整、默认只看待处理、已采用自动移出、清理改一键建议、回收站页签、修清理报错）｜modules/curate｜开发中
- [ ] T26：「随机颜色」改中性浅灰 + 商品图标识 + 颜色表可设预览色；尺寸显示保留 1 位小数｜modules/model、goods、recog｜开发中
- [ ] T27：打印方案编辑器强化（展示和打印仍然分开，各管各的；不共用零件选择）：旧参数面板并进摆盘编辑器；组合模型按零件编辑；
  把切片软件（Bambu Studio / OrcaSlicer）常用编辑功能搬进来：选择（点选 / 多选 / 框选 / 同种全选）、移动 / 旋转 / 缩放（数值输入）、
  按面贴平台、自动方向、自动排列、复制 N 份 / 删除、镜像、对齐 / 均匀分布、拆成零件 / 合并成组、切割（按平面切开）、换 AMS 槽、
  移到别的盘、每个零件单独参数（层高 / 填充 / 壁数）、撤销重做 + 快捷键；
  同一个编辑器也要用在「生产 → 打印方案 / 切片文件」里打开的打印方案窗口（现在还是旧的方向 / 参数面板 + 模型文件 + 切片文件），
  两处打开的是同一份方案、同样可以编辑，切片文件列表放在编辑器下面｜modules/model、core/recipes.py｜方案已提，待老板确认后再做

- [ ] T28：耗材双单位：卷 + 重量（库存、货位分布、补货线按卷或公斤、入库 / 出库按卷、打印按克、盘点数卷或称重、采购按卷）｜modules/inv、core/materials.py、modules/pur｜方案已提，待老板说做再开始

- [x] T29：新建生产单改成选产品：默认「建议生产」清单（图片、销量、库存、在做、缺口、建议数量和理由，按急迫排序）、全部产品按销量排、规格展开、已选清单 + 合计；生产单页顶部建议生产卡片｜core/po.py、modules/prod/ui/po.js｜v2.55.0 已做（modules/prod/tests/t_po255.py）

- [ ] T30：打印机编码规则：积木式规则（前缀 / 分组 / 机架层位 / 机型简称 / 顺序号 / 分隔符）+ 预览、自动生成或自定义、批量重新编号（预览旧→新）、改位置时提示重新编号｜core/fleet.py、modules/prod｜方案已提，待老板说做再开始

## 不做的事
- 不迁移旧选品工具的数据
- Shopee 接口还没绑定，财务先用导入
