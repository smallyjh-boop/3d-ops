# 交接记录（每次会话结束更新，下次新会话只读这里）

## 最后更新
2026-11-01

## 当前状态
- 已发布：v2.52.0（main，2026-11-01）：仓库 / 货位、打印方案 + 多色 + 摆盘 + 多盘生产、拍照识别、采集提速
- 测试机已装 OrcaSlicer 2.3.1（/opt/orca，PATH 里 orca-slicer），v20_test 和 model/t_printplan_orca 现在能真切片
- 进行中：v2.53.0
  1. ✅ AI 接口统一管理：core/ai/（catalog / conf / providers / router / usage）+ modules/ai（系统 → AI 接口、AI 用量）。
     所有调用走 ai_copy.call(ai_copy.tcfg(cfg, "任务"), …) / ai.image；旧键（ai_provider/ai_api_key/image_*）继续是默认 AI 的来源，
     某服务商在新页面保存过密钥后才用 ai_providers 里的；save_config 用旧键改密钥会同步过去（conf.sync_legacy）
  2. ✅ 场景图改进：core/scene_ai.py + goods ui/scenegen.js（候选存 data/scene_cand/<产品>/），批量在产品列表勾选栏
     （真实出图服务商的效果还没在线上验证：先用便宜的模型试几张）
  3. ✅ 「返回」回到原来的地方：static/nav.js（换页面记浏览器历史、返回恢复筛选 / 滚动 / 高亮，抽屉和弹窗按后退先关），测试 t_nav253
  4. ✅ 模型区改进（展示 / 打印分开、组装选零件 + 按接合位置自动组合 modules/model/mating.py、默认收起、按规格、一键切片、爆炸图、撤销）
  6. 产品库 / 采集箱 / 候选池 / 上架工作台 自动分组；候选池清理——进行中
  7. 库存同步重做——进行中
  5. ✅ 仓库一本库存按区管（modules/inv/flows.py，测试 modules/inv/tests/t_wms253.py）：料卷有货位（上机 → 打印机 · 槽）、
     生产区跟着打印机设置、采购 → 暂存区、打印 → 待检区 → 质检、退货区、打包台扣包材、料卷提醒、按区金额；
     「耗材料卷」「成品备货」变成「仓库 → 库存」页的页签（旧 id 照样能开）；手机 /m 加 料卷 / 质检 / 退货
  1. AI 接口统一管理（按任务选 AI、多家可换、自动备用、用量费用）
  2. 场景图改进（AI 写提示词、看图质检、多张挑图、参考图、类目模板、多尺寸、批量、费用、Flux）
  3. 「返回」回到原来的地方（全系统）
  4. 展示 / 打印分开 + 每个规格的展示和方案（已做完，见 modules/model/README 1.3）：合并成一套只影响打印、展示自动拆回零件；
     组装视图零件选择 / 自动选零件 / 几何自动组合（mating.py）/ 爆炸图 / 撤销重做；③ 默认收起 + 规格 × 状态概览；
     复制规格、按主模型缩放、从组装生成打印方案、一键全部切片。截图脚本 tests/ui/shot253.js

## 已知问题 / 坑
- 测试临时目录 /tmp/3dops-test-* 很大（每个约 0.8–1 GB），磁盘满时要清理
- OrcaSlicer 不认我们写的 3MF 加拓竹标记（会崩溃 -11）；普通 3MF + Metadata/model_settings.config 才能按槽分色
- 涂色 3MF（MakerWorld / 拓竹）不能按盘程序切（会丢涂色），要在 Bambu Studio 切好上传
- 拍照识别准确率目前来自模拟照片，需要真实照片验证（系统 → 识别测试）

- 拓竹 X1 / P1 左前角 18×28 mm 是废料口（bed_exclude_area），零件压到那里 OrcaSlicer 报「盘上没有能切的零件」；自动排列已避开（printplan.exclude_of）

## 重要决定（以及原因）
- v2.53：展示（product["display"] = {"v": 2, "specs": {规格: …}}）和打印方案（print_plans[规格]）各管各的；「按主模型缩放」的规格 = print_plans[规格] = {"follow": True, "scale": N}
- Lazada 聊天用单独的 IM 应用授权（im_* 字段），数据 / 广告接口按路径分到不同应用
- 切片软件给的每色克数已含冲刷；系统存净克数，成本和扣库存另加冲刷，避免重复计算

## 本次改动的文件
- 见 git log（v2.52.0 相关提交）
