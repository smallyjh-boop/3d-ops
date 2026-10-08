"""店铺与系统对接——v2.30 从内核搬出来的模块。

· 店铺对接：平台开放接口定时拉订单、授权、平台 Webhook 推送（连接器在 core/connectors，订单入库在内核）。
· 3D选品工具：推送新产品建草稿（/api/v1/catalog/…、/api/v1/categories），设置里填选品工具地址和密钥。
· 运营分析系统写回：/api/v1/ops/…（ops 密钥）改标题、属性、售价、上下架；「商品 → 运营改动」查看 / 确认 / 撤回。
API 密钥管理和只读查询接口（/api/v1/orders、skus、cost-params、profit…）在内核，关掉这个模块不受影响。
"""
from . import curator, opsapi  # noqa: F401


def _start():
    from core import integrations
    integrations.start_scheduler()       # 店铺对接：定时拉订单


class _Public:
    curator = curator
    opsapi = opsapi


MODULE = {
    "id": "link",
    "name_zh": "店铺与系统对接",
    "name_th": "เชื่อมต่อร้านค้าและระบบอื่น",
    "version": "1.1",
    "desc_zh": "店铺开放接口自动拉订单、3D选品工具推产品、运营分析系统写回（标题 / 属性 / 售价 / 上下架）和「运营改动」页。",
    "desc_th": "ดึงออเดอร์อัตโนมัติจาก API ร้านค้า รับสินค้าจากเครื่องมือคัดเลือกสินค้า 3D และการแก้ไขจากระบบวิเคราะห์ (ชื่อ คุณสมบัติ ราคา เปิด/ปิดขาย)",
    "depends": [],
    "order": 50,
    "public": _Public,
    "menus": [
        {"tab": "opschg", "mod": "goods", "zh": "运营改动", "th": "การแก้ไขจากระบบวิเคราะห์", "roles": "owner,listing", "after": "export"},
    ],
    "settings_module": "ai",
    "settings_cards": ["ai"],
    "settings": [("运营分析系统写回（标题、属性、售价、上下架）", [
        ("ops_write_mode", "写回方式：auto = 自动生效（默认）；confirm = 只做建议，到「商品 → 运营改动」人工确认后才生效", ["auto", "confirm"])])],
    "startup": _start,
    "ui": {"html": "page.html", "page_js": ["opschg.js", "settings.js"], "boot_js": []},
}
