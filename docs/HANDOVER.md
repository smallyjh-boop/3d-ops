# 交接记录（每次会话结束更新，下次新会话只读这里）

## 最后更新
2026-11-01

## 当前状态
- 已发布：v2.54.0（main，2026-11-01）：打印机机群重做（生产 → 打印机、机型模板、单台喷嘴 / 热床板、发现 / 导入、分组 / 用途 / 专用 / 暂停、
  事件循环连接管理 core/printer_manager.py、可拆 PRINTER_WORKER=external）、成品备货重做（core/inventory/goodsstock.py）、生产单（core/po.py）、
  删除旧外部选品工具对接
- v2.53.0：AI 接口、场景图、返回回原处、模型区按规格、仓库全部进货位、自动分组、库存同步（自动推送总开关默认关）、平台费率、试打 / 打印测试、网络诊断
- 开发中（v2.54.1，未发版）：选品 → 候选池操作重做（页签 待处理 / 已采用 / 已处理 / 回收站；每条删除 / 恢复 / 编辑 / 手动分数；清理对话框换成「可以清理」建议行 + ⚙ 设置；修「清理所选」字符串数字报错）。详见 modules/curate/README.md「系统 v2.54.1」，测试 t_pool254.py
- 测试机已装 OrcaSlicer 2.3.1（/opt/orca，PATH 里 orca-slicer），v20_test 和真切片测试能跑
- 老板 NAS：两个网口同网段（qvs0 192.168.31.2 没插线），需要在 QNAP 把网口 1 改 DHCP 才能永久生效
- 打印机：P1S、K1 Max（192.168.31.139）、K1C（192.168.31.133）已填；K1 原厂固件发送打印待「打印测试」真机验证
- 下一步：等老板反馈（K1 真机打印测试、真机打印测试、库存同步对照表核对后开自动推送、真实照片测识别、生产单 / 机群页试用）

- 已发布 v2.55.0（main，2026-11-01，分组全量 124 个 + 多语言检查通过）：
  A 统一打印方案编辑器（modules/model，测试 t_editor255）；B 耗材卷 + 重量（core/inventory/units.py，t_units255 / t_units255b / pur t_pur255）；
  C 新建生产单选产品（core/po.py suggest / picker，建议数量 = 缺口，订单待打只排前面，t_po255）；D 打印机编码规则（core/fleetcodes.py，新标签二维码装稳定 id，t_codes255）；
  E 货位三种看法 + 服务端分页（modules/inv/views.py / locviews.py / qtytext.py，t_locviews255）

- 开发中（分支 t36-slicer-edit，v2.56.0 未发版）：T36 第一步「在 Bambu Studio / OrcaSlicer 里编辑一盘」+ 桌面客户端切片软件自检 + T37 ① ③。
  modules/model/slicerproj.py（生成 / 读回项目 3MF）、editsession.py（会话、锁、主文件、同步、安全核对、切主文件）、ui/slicedit.js；
  core/fleet.slicer_app_of + 机型模板 slicer_app；desktop/slicer_edit.py + desktop_app Api；modules/desk/selftest.py；
  assembly.py 作者装配 / 平铺图、core/mesh.assembly_3mf。详见 modules/model/README.md、modules/desk/README.md「系统 v2.56.0」。
  测试 t_slicerapp36 / t_asm37 / desk t_slicerdesk256。Bambu Studio 在这里没法测：等老板在 Windows 上跑「🔧 切片软件自检」。
  没做：T37 ②（装配视图编辑回传）、电脑上用 Bambu Studio 切片（T36 第二步）、NAS 网页版（第三步）。

## 已知问题 / 坑
- 测试临时目录 /tmp/3dops-test-* 很大（每个约 0.8–1 GB），磁盘满时要清理
- OrcaSlicer 不认我们写的 3MF 加拓竹标记（会崩溃 -11）；普通 3MF + Metadata/model_settings.config 才能按槽分色
- 涂色 3MF（MakerWorld / 拓竹）不能按盘程序切（会丢涂色），要在 Bambu Studio 切好上传
- 拍照识别准确率目前来自模拟照片，需要真实照片验证（系统 → 识别测试）

- v2.56：OrcaSlicer 2.3.1 读拓竹格式项目 3MF：project_settings 必须是完整配置（只写几个键会崩溃 -11），我们让 Orca 自己导出一次取它的；
  <plate> 的 plater_name 写中文会崩溃（留空）；自定义的对象 / part metadata（erp_uid）导出时会丢，靠名字末尾「#编号」对应；
  创想三维单喷头机型带几个耗材要 single_extruder_multi_material=1，耗材配置里不能写 filament_colour（否则 -5）
- 拓竹 X1 / P1 左前角 18×28 mm 是废料口（bed_exclude_area），零件压到那里 OrcaSlicer 报「盘上没有能切的零件」；自动排列已避开（printplan.exclude_of）

## 重要决定（以及原因）
- v2.54 打印机身份：稳定 id + 只往后加；数据库仍存序号，删除时 fleet.remap 按 id 重映射（全改成 id 要动几十处 SQL，风险大）
- v2.54 复审：load_config 按文件版本缓存并返回拷贝（pickle）；本进程保存后 config.invalidate()，别的进程写按 inode / mtime / 大小认出来
- v2.54 复审：printers._status 按稳定 id 存（外面按序号读写照旧）；后台进程 ERP 等不到结果但已认领 = UnknownResult（不当失败，start_run 记成打印中）
- v2.54 打印机设置只存单台覆盖 ovr，模板在 printer_models；所有读取用 fleet.effective（load_config 已经算好）
- v2.54 排单（另一个任务）只读 group / location / role / dedicated_po / paused，不要在这边改 production.schedule()
- v2.53：展示（product["display"] = {"v": 2, "specs": {规格: …}}）和打印方案（print_plans[规格]）各管各的；「按主模型缩放」的规格 = print_plans[规格] = {"follow": True, "scale": N}
- Lazada 聊天用单独的 IM 应用授权（im_* 字段），数据 / 广告接口按路径分到不同应用
- 切片软件给的每色克数已含冲刷；系统存净克数，成本和扣库存另加冲刷，避免重复计算

- v2.55 打印参数的唯一来源是打印方案每盘的 params；product["recipe"] / spec_recipes 只是第 1 盘的镜像（老代码读）；recipes.get 只认 v2.55 后保存过（盘里有 params）的方案
- v2.55 零件单独参数写在 3MF Metadata/model_settings.config 的 <object> metadata（layer_height / sparse_infill_density / wall_loops），切片时 keep_settings 保留该文件
- v2.55 复审：盘参数的温度带 temp_material（给哪个材料设的），换材料 / 不一致就作废；printplan._migrate 不改 p（返回拷贝 + params_auto 标记），缩放规格签名一律用 plate_sig；resolve_profiles 默认 strict（自动选到别的材料的配置就抛错），只看配置的地方传 strict=False
- v2.55 丝绸料：recipes.norm_material 把 SILK / 丝 → PLA-SILK（和 PLA 是 close，不拦）；match_filament 先找 Generic PLA Silk，没有用普通 PLA
## 本次改动的文件
- 见 git log（v2.52.0 相关提交）
