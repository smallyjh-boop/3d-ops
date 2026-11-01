# 交接记录（每次会话结束更新，下次新会话只读这里）

## 最后更新
2026-11-01

## 当前状态
- 已发布：v2.52.0（main，2026-11-01）
- 测试机已装 OrcaSlicer 2.3.1（/opt/orca，PATH 里 orca-slicer），v20_test 和 model/t_printplan_orca 能真切片
- v2.53.0（开发分支，未发版）已合入：
  1. AI 接口统一管理：core/ai/ + modules/ai（系统 → AI 接口、AI 用量）；调用走 ai_copy.call(ai_copy.tcfg(cfg, "任务"), …) / ai.image；
     旧键 ai_provider/ai_api_key/image_* 仍是默认 AI；save_config 改旧键会同步（conf.sync_legacy）
  2. 场景图改进：core/scene_ai.py + goods ui/scenegen.js（候选 data/scene_cand/<产品>/），批量在产品列表勾选栏（真实出图服务商未线上验证）
  3. 「返回」回到原来的地方：static/nav.js（NAV.keep 记模块状态），测试 t_nav253
  4. 模型区：展示 / 打印分开、组装选零件 + 几何自动组合 mating.py、默认收起、按规格、一键切片、爆炸图、撤销（modules/model/README 1.3，截图脚本 tests/ui/shot253.js）
  5. 仓库一本库存按区管：modules/inv/flows.py（料卷货位、生产区、待检 / 退货 / 次品 / 暂存区、打包台扣包材）；待检 / 退货 / 次品区成品不算可售（flows.unavailable_qty）；
     打印机设置改动广播 printers.changed 立即同步生产区
  6. 自动分组：产品库 / 采集箱 / 候选池（清理 + 回收站）/ 上架工作台，共用 static/groups.js + core/prodgroups.py；
     铺货到第二个店铺记录在 p["lazada_api_shops"]（未在真店铺验证）
  7. 库存同步重做：modules/listing/stocksync.py + stockadapters.py（Lazada update_price_quantity，Shopee / TikTok 先导出表）
  8. 平台费率引擎：core/feerates.py（Lazada 财务流水 / Shopee 导入报表 → 店铺×类目×费用项的真实费率，30/90 天快照，回退链 店铺×类目 → 店铺 → 类目默认 → 平台默认）；
     pricing.price_variant / price_product 多 platform、shop 参数并返回 fee 拆分；新页面 财务 → 平台费率（fin_fees）；Shopee 7 天没导入 / 费率变动 > 0.5 个百分点进待办；
     测试 modules/fin/tests/t_feerates253.py。旧 platform_fee_rate / shopee_fee_rate 就是平台默认费率（原值保留）
- 待做：打印机「网络诊断」按钮 → reviewer 审查 → 全量测试 → 发 v2.53.0

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
