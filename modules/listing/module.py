"""上架导出：导出 Lazada / Shopee 上架表格、上架批次和平台状态、库存待同步到平台。
关掉后「导出上架表格」页面不出现，产品资料不受影响（导出过的 SKU 照样锁定）。"""


from . import public


def _start():
    from . import lazada_push, stocksync
    lazada_push.start()
    stocksync.start()


def _todo(add):
    from . import stocksync
    stocksync.todo_provide(add)


def _on_stock(**k):
    from . import stocksync
    return stocksync.on_stock_changed(**k)


def _on_order(**k):
    from . import stocksync
    return stocksync.on_order_status(**k)


MODULE = {
    "id": "listing",
    "name_zh": "上架导出",
    "name_th": "ส่งออกลงขาย",
    "version": "2.3",
    "desc_zh": "导出 Lazada / Shopee 上架表格、上架批次和状态、库存待同步到平台。",
    "desc_th": "ส่งออกไฟล์ลงสินค้า Lazada / Shopee สถานะการลงขาย และสต็อกที่ต้องอัปเดตบนแพลตฟอร์ม",
    "depends": ["goods"],
    "public": public,             # 别的模块用：online_shops() 产品在哪些店铺在线（产品库显示）
    "order": 2,
    "menus": [
        # v2.49：菜单只留「上架」一个，在线商品是页面顶上的页签（ghost：不在菜单里，菜单高亮「上架」）
        {"tab": "export", "mod": "goods", "zh": "上架", "th": "ลงขาย", "roles": "owner,listing", "after": "edit"},
        {"tab": "online", "mod": "goods", "zh": "在线商品", "th": "สินค้าออนไลน์", "roles": "owner,listing", "after": "export", "ghost": True, "parent": "export"},
    ],
    "settings_module": "goods",
    "settings": [("Lazada 接口推送", [
        ("lazada_stock_sync_min", "库存自动推到 Lazada：每隔几分钟把「库存待同步」里用接口推送过的 SKU 改掉（0 = 关，只手动点）",
         ["0", "15", "30", "60", "120"])]),
        ("库存同步规则（默认值，可按产品 / SKU / 店铺单独改）", [
            ("ss_auto_push", "自动推送总开关：先在「库存同步」对照总表核对平台数和系统数，没问题再打开。关着时只拉平台库存、显示差异，不自动推（手动推送不受影响）；打开后上面 Lazada 的旧自动推送不再运行", "bool"),
            ("ss_safety", "安全库存：每个 SKU 平台显示的数 = 成品库存 − 订单占住的 − 这个数"),
            ("ss_alloc", "多个店铺怎么分：share 每个店铺都显示全部 / percent 按比例 / fixed 固定件数（在对照总表里改具体数）", ["share", "percent", "fixed"]),
            ("ss_cap", "按需打印的虚拟库存上限（耗材够做几件、最多显示这么多；耗材不够显示 0；留空 = 跟「库存上限」stock_cap，默认 50）"),
            ("ss_printer_units", "每台打印机能撑多少件的虚拟库存（0 = 不按打印机限制）"),
            ("ss_interval_min", "定时检查：每隔几分钟拉平台库存、对照、推待同步的（0 = 只靠库存变化触发）", ["0", "5", "10", "15", "30", "60"]),
            ("ss_event_sync", "成品库存 / 订单变化时马上同步", "bool"),
            ("ss_source", "库存来源：total 全部成品库存 / pick 只算拣货区货位上的", ["total", "pick"]),
            ("ss_retry_max", "同步失败自动重试几次，用完发待办"),
            ("ss_low_qty", "快卖完：可售不超过多少件"),
            ("ss_cover_days", "快卖完：按近 30 天销量，够卖不到几天"),
            ("ss_mismatch_min", "对不上：平台显示和系统差几件以上才算"),
            ("ss_unsynced_hours", "超过多少小时没同步发待办")])],
    "config_defaults": {"lazada_stock_sync_min": "30", "ss_interval_min": "15", "ss_safety": "0", "ss_cap": "", "ss_auto_push": False, "ss_low_qty": "2",
                        "ss_cover_days": "3", "ss_mismatch_min": "1", "ss_unsynced_hours": "24", "ss_retry_max": "3", "ss_event_sync": True,
                        "ss_source": "total", "ss_alloc": "share", "ss_printer_units": "0", "ss_virtual_min": "1"},
    "events": {"stock.changed": _on_stock, "order.status": _on_order},       # v2.53 库存同步：成品库存 / 订单变化时马上同步
    "todo": _todo,
    "startup": _start,
    "ui": {"inline": True, "html": "page.html", "eager_js": ["export.js", "stocksync.js", "online.js"], "css": ["page.css"], "page_js": [], "boot_js": []},
}
