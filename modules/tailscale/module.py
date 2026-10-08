"""外网自动加入（Tailscale）——v2.29 第一个按新方式写的模块。

员工的电脑装好桌面客户端（或托盘加速器）、登录后，自动安装 Tailscale 并用老板设置的「预授权密钥」加入你的网络，
不用注册、不用登录 Tailscale。配合 Tailscale 后台的访问规则，这些电脑只能访问 NAS 上的这个系统。
"""


MODULE = {
    "id": "tailscale",
    "name_zh": "外网自动加入（Tailscale）",
    "name_th": "เชื่อมต่อภายนอกอัตโนมัติ (Tailscale)",
    "version": "1.0",
    "desc_zh": "桌面客户端 / 加速器装好后自动安装 Tailscale 并加入你的网络，员工不用注册登录；配合访问规则只能访问这个系统。",
    "desc_th": "หลังติดตั้งโปรแกรมเดสก์ท็อป / ตัวเร่งความเร็ว จะติดตั้ง Tailscale และเข้าร่วมเครือข่ายของคุณเอง พนักงานไม่ต้องสมัคร/ล็อกอิน ใช้ร่วมกับกฎการเข้าถึงให้เข้าได้เฉพาะระบบนี้",
    "depends": [],
    "order": 90,
    "settings_module": "general",
    "settings_card": True,
    "settings": [("外网自动加入（Tailscale）", [
        ("ts_authkey", "预授权密钥（Tailscale 后台生成，tskey-auth- 开头；只存在 NAS 上）", "password"),
        ("ts_tag", "设备标签（和密钥、访问规则里的一样）"),
        ("ts_auto", "客户端 / 加速器装好后自动加入（第一次会弹一次管理员确认）", "bool")])],
    "config_defaults": {"ts_authkey": "", "ts_tag": "tag:3dops", "ts_auto": True},
    "secrets": ["ts_authkey"],
    "owner_only": [("*", r"^/api/m/tailscale/")],
}
