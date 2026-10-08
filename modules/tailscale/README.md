# 模块：外网自动加入（Tailscale）（tailscale）

外网自动加入（Tailscale）——v2.29 第一个按新方式写的模块。

员工的电脑装好桌面客户端（或托盘加速器）、登录后，自动安装 Tailscale 并用老板设置的「预授权密钥」加入你的网络，
不用注册、不用登录 Tailscale。配合 Tailscale 后台的访问规则，这些电脑只能访问 NAS 上的这个系统。

## 文件

- `__init__.py`
- `api.py`
- `i18n/th.json`
- `module.py`
- `tests/t_tailscale.py`
- `ui/page.js`

## 改动记录

- 1.0（系统 v2.29.0）：第一个按模块方式写的功能。
