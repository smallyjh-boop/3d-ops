"""手机 / 平板 App（v1.0）：手机扫码干活的页面 /m（查订单、扫码发货交接、验货、库存、货位）、扫码识别接口、
打包照片、安卓 App 下载（设置 → 组件与插件）。平板用安卓 App 打开的是完整的网页版（隐藏电脑才有的功能）。"""

MODULE = {
    "id": "mobile",
    "name_zh": "手机 / 平板 App",
    "name_th": "แอปมือถือ / แท็บเล็ต",
    "version": "1.0",
    "desc_zh": "手机扫码干活（查订单、发货交接、验货、库存、货位，摄像头像扫码枪一样连续扫）；安卓 App 下载；平板打开完整网页版。",
    "desc_th": "ใช้มือถือสแกนทำงาน (ค้นออเดอร์ ส่งมอบพัสดุ ตรวจแพ็ก สต็อก ตำแหน่งจัดเก็บ กล้องสแกนต่อเนื่องเหมือนเครื่องสแกน) "
               "ดาวน์โหลดแอป Android แท็บเล็ตเปิดเวอร์ชันเว็บเต็ม",
    "depends": [],
    "order": 85,
    "settings_cards": ["addons"],
    "public_exact": ["/m", "/apk"],              # 手机页自己显示登录框；/apk = 下载安卓 App（手机浏览器里好输入）
    "public_paths": ["/m/mobile/", "/api/mobile/apk/download"],   # 手机页的 js / css（没有数据）、App 安装包
    "owner_only": [("POST", r"^/api/mobile/apk/")],
    "production_allow": [("GET", r"^/api/mobile/"), ("POST", r"^/api/mobile/orders/\d+/photos$")],
    "ui": {"page_js": ["page.js"], "boot_js": ["boot.js"], "css": []},
}
