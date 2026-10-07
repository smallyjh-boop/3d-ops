3D 运营管理系统 —— 自动测试

一、回归测试（每次改代码、发版前必须全部通过）
    在程序文件夹里运行：
        python tests/run_all.py              跑全部（约 2 分钟）
        python tests/run_all.py t_modellib   只跑某一个
    测试只用临时文件夹里的测试数据（tests/fixtures/base_data.zip 解压出来的），不会碰正式数据。
    全部「通过」才能发版；有「失败」时会打印失败的输出，完整日志留在提示的临时文件夹里。

二、界面测试（可选，要先装 Playwright：pip install playwright && playwright install chromium）
        python tests/ui/run_ui.py
    会起一个测试服务器（端口 8799，AI 用假的回答），中文、泰文界面各点一遍：
    产品编辑、修图、卖点图、模型库摆盘预览。检查页面有没有 JavaScript 报错、泰文界面有没有漏翻的中文。

三、每个测试管什么
    t_modellib   模型库：多文件、组件合并、摆放方向、空打风险、AI 检查、预览摆盘、旧数据重新分析
    t_perm2131   员工权限：删模型、换模型、取消订单、盘点、删客服消息
    t_imgtools   修图：去水印（OpenCV / 基础 / LaMa 接口）、保存新图、替换原图和恢复
    t_catalog    3D选品工具建产品、多规格、补传模型文件
    t_spool      耗材按卷管理
    t_lst2111    上架状态按平台规则
    t_v211       审单、物流交接、买家、售后
    api_test     /api/v1 对接接口、密钥权限
    t_up         上传切片文件（拓竹 / Creality）
    t_cs         AI 客服
    ops_test     订单导入、利润
    t_fleet      打印机机群
    t_v27        系统检查、备份
    t_resin      光固化打印机和切片文件
    t_listing    导出上架表格（Lazada / Shopee）
    t_v1         运营分析系统对接
    t_ops        运营写回审批
    t_v2141      产品编辑防覆盖、运行日志、诊断包
    v20_test     生产全流程（下单 → 排产 → 发打印机 → 完成）；最后 3 行 ERR 是故意测的错误情况

四、加新功能时
    在 tests/cases/ 里加一个 t_xxx.py（照着现有的写：开头 3 行固定，用 T 下面的临时数据目录），
    在 run_all.py 的 ORDER 里加上名字。测试里用 ok(条件, "说明") 记结果，最后 print("ERRORS", E)。
