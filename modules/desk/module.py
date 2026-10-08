"""桌面客户端（Windows）——v2.30 从内核搬出来的模块。

· 下载桌面客户端安装包（带好 NAS 地址）；登录后自动配对（每台电脑一把只做自己活的电脑加速密钥）。
· 设置 → 组件与插件：每台电脑的状态，老板可以停用。
· 网页里的桌面端功能：在本机用切片软件打开模型 / 切片文件、Windows 通知、新窗口、顶部「本机加速」状态。
电脑加速通道本身（任务分派、加速器下载、电脑密钥登记 core/desktop.py）在内核里，关掉这个模块不影响「浏览器 + 加速器」。
"""

MODULE = {
    "id": "desk",
    "name_zh": "桌面客户端",
    "name_th": "โปรแกรมเดสก์ท็อป",
    "version": "1.1",
    "desc_zh": "Windows 桌面客户端：下载安装、登录自动配对加速、在本机打开模型文件、系统通知；老板可以看到 / 停用每台电脑。",
    "desc_th": "โปรแกรมเดสก์ท็อป Windows: ดาวน์โหลดติดตั้ง จับคู่ตัวเร่งอัตโนมัติหลังล็อกอิน เปิดไฟล์โมเดลในเครื่อง แจ้งเตือนระบบ เจ้าของดู/ปิดใช้แต่ละเครื่องได้",
    "depends": [],
    "order": 80,
    "settings_cards": ["addons"],
    "public_paths": ["/api/desktop/dl/"],
    "owner_only": [("*", r"^/api/desktop/devices")],
    "production_allow": [("POST", r"^/api/desktop/(pair|dltoken)$"), ("GET", r"^/api/desktop/package$")],
    "ui": {"boot_js": ["boot.js"], "page_js": []},
}
