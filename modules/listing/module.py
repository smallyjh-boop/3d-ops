"""上架导出：导出 Lazada / Shopee 上架表格、上架批次和平台状态、库存待同步到平台。
关掉后「导出上架表格」页面不出现，产品资料不受影响（导出过的 SKU 照样锁定）。"""


from . import public


def _start():
    from . import lazada_push
    lazada_push.start()


MODULE = {
    "id": "listing",
    "name_zh": "上架导出",
    "name_th": "ส่งออกลงขาย",
    "version": "2.1",
    "desc_zh": "导出 Lazada / Shopee 上架表格、上架批次和状态、库存待同步到平台。",
    "desc_th": "ส่งออกไฟล์ลงสินค้า Lazada / Shopee สถานะการลงขาย และสต็อกที่ต้องอัปเดตบนแพลตฟอร์ม",
    "depends": ["goods"],
    "public": public,             # 别的模块用：online_shops() 产品在哪些店铺在线（产品库显示）
    "order": 2,
    "menus": [
        {"tab": "export", "mod": "goods", "zh": "上架工作台", "th": "พื้นที่ลงสินค้า", "roles": "owner,listing", "after": "edit"},
        {"tab": "online", "mod": "goods", "zh": "在线商品", "th": "สินค้าออนไลน์", "roles": "owner,listing", "after": "export"},
    ],
    "settings_module": "goods",
    "settings": [("Lazada 接口推送", [
        ("lazada_stock_sync_min", "库存自动推到 Lazada：每隔几分钟把「库存待同步」里用接口推送过的 SKU 改掉（0 = 关，只手动点）",
         ["0", "15", "30", "60", "120"])])],
    "config_defaults": {"lazada_stock_sync_min": "30"},
    "startup": _start,
    "ui": {"inline": True, "html": "page.html", "eager_js": ["export.js", "stock.js", "online.js"], "css": ["page.css"], "page_js": [], "boot_js": []},
}
