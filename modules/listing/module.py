"""上架导出：导出 Lazada / Shopee 上架表格、上架批次和平台状态、库存待同步到平台。
关掉后「导出上架表格」页面不出现，产品资料不受影响（导出过的 SKU 照样锁定）。"""

MODULE = {
    "id": "listing",
    "name_zh": "上架导出",
    "name_th": "ส่งออกลงขาย",
    "version": "1.2",
    "desc_zh": "导出 Lazada / Shopee 上架表格、上架批次和状态、库存待同步到平台。",
    "desc_th": "ส่งออกไฟล์ลงสินค้า Lazada / Shopee สถานะการลงขาย และสต็อกที่ต้องอัปเดตบนแพลตฟอร์ม",
    "depends": ["goods"],
    "order": 2,
    "menus": [
        {"tab": "export", "mod": "goods", "zh": "导出上架表格", "th": "ส่งออกไฟล์ลงสินค้า", "roles": "owner,listing", "after": "edit"},
    ],
    "ui": {"inline": True, "html": "page.html", "eager_js": ["export.js", "stock.js"], "page_js": [], "boot_js": []},
}
