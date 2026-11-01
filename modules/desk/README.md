# 模块：桌面客户端（desk）

桌面客户端（Windows）——v2.30 从内核搬出来的模块。

· 下载桌面客户端安装包（带好 NAS 地址）；登录后自动配对（每台电脑一把只做自己活的电脑加速密钥）。
· 设置 → 组件与插件：每台电脑的状态，老板可以停用。
· 网页里的桌面端功能：在本机用切片软件打开模型 / 切片文件、Windows 通知、新窗口、顶部「本机加速」状态。
电脑加速通道本身（任务分派、加速器下载、电脑密钥登记 core/desktop.py）在内核里，关掉这个模块不影响「浏览器 + 加速器」。

## 文件

- `__init__.py`
- `api.py`
- `module.py`
- `tests/t_desk.py`
- `ui/boot.js`

## 改动记录

- 1.0（系统 v2.30.0）：从内核搬成模块。
- 1.1（系统 v2.34.0）：泰文翻译从内核 static/i18n.js 搬到模块自己的 i18n/th.json（只在这个模块里用到的那些），界面不变。
- （系统 v2.56.0，T36）在切片软件里编辑：desktop/slicer_edit.py（纯函数，Linux 上测试模拟）—— 找 Bambu Studio / OrcaSlicer（默认安装目录 +
  注册表 HKLM / HKCU Uninstall 的 DisplayName / InstallLocation / DisplayVersion / DisplayIcon），info() 带 slicers；
  edit_in_slicer(会话)：下载到 文档\3D-Ops\编辑中\<产品>\，用对应软件打开（STARTUPINFO 最大化），后台线程监视文件：修改时间 / 大小变了、
  2 秒不再变、是完整的 zip → 自动上传；服务器说会话结束就停；edit_status / edit_stop / split_screen（ctypes：软件左半屏、客户端右半屏，失败不影响）。
  🔧 切片软件自检（本机加速面板）：检测两个软件和版本 → 服务器生成测试盘（modules/desk/selftest.py：两个方块两槽多色，Bambu 版 / Orca 版各一份，
  不建产品，报告后 / 一天后清理）→ 依次用软件打开、提示「随便挪一下零件按 Ctrl+S」→ 自动回传核对（零件编号、位置、槽、颜色、配置）→ 试左右分屏 →
  通过 / 不通过清单（中泰文）上报（POST /api/desktop/selftest/report，存最近 20 次）；设置 → 组件与插件 的桌面客户端卡片显示「最近一次自检」。
  接口：POST /api/desktop/selftest/start|report、GET /api/desktop/selftest/log；不用登录（带密钥）/api/desktop/st/<id>/file|upload。
  测试 modules/desk/tests/t_slicerdesk256.py。
