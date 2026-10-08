"""商品（基础模块，不能关）：产品库、编辑产品、图片 / 修图 / 卖点图 / 场景图、AI 文案、类目与属性、分组、规格与 SKU、
按耗材自动算库存（库存待同步到平台）。产品资料和数据在 core/store.py 等（主链路的数据层）。"""

MODULE = {
    "id": "goods",
    "name_zh": "商品",
    "name_th": "สินค้า",
    "version": "1.1",
    "desc_zh": "产品库、编辑产品、图片与修图、AI 文案、类目属性、分组、规格与 SKU。所有功能的基础。",
    "desc_th": "คลังสินค้า แก้ไขสินค้า รูปภาพและแต่งรูป ข้อความ AI หมวดหมู่และคุณสมบัติ กลุ่ม ตัวเลือกและ SKU — พื้นฐานของทุกฟังก์ชัน",
    "core": True,
    "depends": [],
    "order": 1,
    "menus": [
        {"tab": "library", "mod": "goods", "zh": "产品库", "th": "คลังสินค้า", "roles": "owner,listing,production"},
        {"tab": "edit", "mod": "goods", "zh": "编辑产品", "th": "แก้ไขสินค้า", "roles": "owner,listing,production", "after": "library", "ghost": True},
    ],
    "ui": {"inline": True, "html": "page.html", "eager_js": ["scene.js", "adimg.js", "imgedit.js", "specmodel.js"], "page_js": [], "boot_js": []},
}
