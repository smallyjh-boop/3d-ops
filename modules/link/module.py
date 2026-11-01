"""店铺与系统对接——v2.30 从内核搬出来的模块。

· 店铺对接：平台开放接口定时拉订单、授权、平台 Webhook 推送（连接器在 core/connectors，订单入库在内核）。
· 类目查询 /api/v1/categories（其他系统用）。v2.54 起旧的「3D选品工具」对接（/api/v1/catalog/…）已移除，选品在「商品 → 选品」里做。
· 运营分析系统写回：/api/v1/ops/…（ops 密钥）改标题、属性、售价、上下架；「运营 → 商品表现 → 待确认的建议」查看 / 确认 / 撤回（v2.49 起）。
API 密钥管理和只读查询接口（/api/v1/orders、skus、cost-params、profit…）在内核，关掉这个模块不受影响。
"""
from . import events, opsapi  # noqa: F401


def _migrate_v254():
    """v2.54：旧选品工具「删了也保留」的待确认规格（removed_pending）改成正常规格，不再卡上架检查。只改状态，别的数据不动。"""
    import os
    from core import specs, store
    try:
        for name in os.listdir(store.PRODUCTS_DIR):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(store.PRODUCTS_DIR, name), encoding="utf-8") as f:
                if "removed_pending" not in f.read():
                    continue
            p = store.load(name[:-5])
            if specs.clear_removed_pending(p):
                store.save(p)
    except Exception:  # noqa: BLE001
        pass


def _start():
    from core import integrations
    integrations.start_scheduler()       # 店铺对接：定时拉订单
    _migrate_v254()
    try:                                 # v2.54：旧选品工具的密钥不再用，清掉
        from core import config as _cf
        if _cf.load_config().get("curator_api_key"):
            _cf.save_config({"curator_api_key": ""})
    except Exception:  # noqa: BLE001
        pass


class _Public:
    opsapi = opsapi
    events = events          # v2.50：订单页「安排发货」调 events.rts_now


MODULE = {
    "id": "link",
    "name_zh": "店铺与系统对接",
    "name_th": "เชื่อมต่อร้านค้าและระบบอื่น",
    "version": "1.7",
    "desc_zh": "店铺开放接口自动拉订单、运营分析系统写回（标题 / 属性 / 售价 / 上下架）（在「运营 → 商品表现 → 待确认的建议」确认 / 撤回）。",
    "desc_th": "ดึงออเดอร์อัตโนมัติจาก API ร้านค้า และการแก้ไขจากระบบวิเคราะห์ (ชื่อ คุณสมบัติ ราคา เปิด/ปิดขาย)",
    "depends": [],
    "order": 50,
    "public": _Public,
    "menus": [],      # v2.49：「运营改动」页面搬到「运营 → 商品表现 → 待确认的建议」（运营分析模块，接口还是这里的 /api/ops/changes）
    "settings_module": "ai",
    "settings_cards": ["ai"],
    "settings": [("运营分析系统写回（标题、属性、售价、上下架）", [
        ("ops_write_mode", "写回方式：auto = 自动生效（默认）；confirm = 只做建议，到「运营 → 商品表现 → 待确认的建议」人工确认后才生效", ["auto", "confirm"])]),
        ("Lazada 订单", [("lazada_auto_rts", "订单在 ERP 里标成「已发货」（发货交接完成）时，自动在 Lazada 上「安排发货」（Ready to Ship）", "bool")])],
    "config_defaults": {"lazada_auto_rts": True},
    "startup": _start,
    "events": {"order.status": events.on_order_status},       # v2.44.1：ERP 里发货 → Lazada「安排发货」
    "ui": {"html": "page.html", "page_js": ["settings.js"], "boot_js": []},
}
