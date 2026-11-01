# 交接记录（每次会话结束更新，下次新会话只读这里）

## 最后更新
2026-11-01

## 当前状态
- 已发布：v2.53.0（main，2026-11-01）：AI 接口统一管理、场景图、返回回原处、模型区（按规格 / 组装）、仓库全部进货位、自动分组、
  库存同步重做（自动推送总开关默认关）、动态平台费率、生产 / 试打 / 打印测试、打印机网络诊断
- 测试机已装 OrcaSlicer 2.3.1（/opt/orca，PATH 里 orca-slicer），v20_test 和真切片测试能跑
- 老板 NAS：两个网口同网段（qvs0 192.168.31.2 没插线），临时删了路由；需要在 QNAP 把网口 1 改 DHCP 才能永久生效
- 打印机：P1S（拓竹局域网）已连上；K1 Max 原厂固件能读状态，发送打印待「打印测试」验证；K1C 待填 IP
- 下一步：等老板反馈；用户需要：核对库存同步对照表后再开自动推送、真机打印测试、真实照片测识别

- v2.54（开发中，未发版）：成品备货页重做 + 生产单（core/po.py、core/inventory/goodsstock.py）；打印机字段 paused/role/dedicated_po/group/location 由舰队页维护，排单只读

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
