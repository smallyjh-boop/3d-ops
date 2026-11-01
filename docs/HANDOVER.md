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
  3b. ✅ 自动分组（老板批准）：产品库 / 采集箱 / 候选池（含清理 + 回收站）/ 上架工作台（按店铺）左边的手动分组换成自动、动态分组，共用 static/groups.js + core/prodgroups.py
     （手动只剩标记 + 标签 + 保存的视图；旧分组升级时自动迁移）。测试 t_groups253 / t_inbox_groups253 / t_pool_clean253 / t_workbench_groups253。
     注意：铺货到第二个店铺的推送记录存在 p["lazada_api_shops"]（还没在线上真店铺验证）
  4. 模型区改进（展示 / 打印分开、组装、按规格）——进行中
  5. 仓库全部物品进货位（料卷、生产区 / 待检区、全流程走货位）——进行中

## 已知问题 / 坑
- 测试临时目录 /tmp/3dops-test-* 很大（每个约 0.8–1 GB），磁盘满时要清理
- OrcaSlicer 不认我们写的 3MF 加拓竹标记（会崩溃 -11）；普通 3MF + Metadata/model_settings.config 才能按槽分色
- 涂色 3MF（MakerWorld / 拓竹）不能按盘程序切（会丢涂色），要在 Bambu Studio 切好上传
- 拍照识别准确率目前来自模拟照片，需要真实照片验证（系统 → 识别测试）

## 重要决定（以及原因）
- Lazada 聊天用单独的 IM 应用授权（im_* 字段），数据 / 广告接口按路径分到不同应用
- 切片软件给的每色克数已含冲刷；系统存净克数，成本和扣库存另加冲刷，避免重复计算

## 本次改动的文件
- 见 git log（v2.52.0 相关提交）
