"""平台费率页（v2.53）的数据和每天的重算任务。费率怎么算见 core/feerates.py。"""
import threading
import time

from core import db, feerates

_started = False


def page(platform=""):
    """「财务 → 平台费率」整页的数据：数字卡片、走势、店铺×类目表、默认费率、Shopee 导入状态、未处理的费率变动。"""
    from core.config import load_config
    cfg = load_config()
    feerates.init()
    rows = feerates.table(platform or None)
    kp = {}
    for plat in feerates.PLATFORMS:
        r = feerates.resolve(plat, None, None, cfg)
        kp[plat] = {"pct": r["pct"], "fixed": r["fixed"], "source": r["source"], "source_zh": r["source_zh"], "source_th": r["source_th"],
                    "orders": r["orders"], "shop": r["shop"], "default_pct": feerates.platform_default(cfg, plat)}
    cat_defaults = [dict(r) for r in db.conn().execute("SELECT platform, category, rate, cat_label FROM fee_defaults ORDER BY platform, category")]
    events = feerates.events("open")
    aff = {}
    for e in events:
        k = f"{e['platform']}|{e['shop']}"
        if k not in aff:
            a = feerates.affected_products(cfg, e["platform"], e["shop"])
            aff[k] = {"n": len(a), "names": [x["name"] for x in a[:8]], "below_cost": sum(1 for x in a if x["below_cost"]), "ids": [x["id"] for x in a]}
    names = {n: feerates.fee_name_label(n) for r in rows for it in r["items"] for n in (it.get("names") or [])}
    return {"fee_names": names, "min_orders": feerates.min_orders(cfg), "kpis": kp, "rows": rows, "trend": feerates.trend(), "events": events, "affected": aff,
            "defaults": {"platform": {p: feerates.platform_default(cfg, p) for p in feerates.PLATFORMS}, "categories": cat_defaults},
            "shopee": feerates.import_status("shopee"), "categories": category_options(),
            "items": {k: feerates.label_of(k) for k in feerates.ITEMS},
            "updated_at": max([r["updated_at"] or 0 for r in rows] or [0]) or None}


def category_options():
    """产品用到的类目（给「类目默认费率」下拉用）。"""
    from core import store
    seen = {}
    try:
        for it in store.list_products():
            ck, label = feerates.category_of(store.load(it["id"]))
            if ck != feerates.UNKNOWN_CAT:
                seen[ck] = label
    except Exception:  # noqa: BLE001
        pass
    return [{"category": k, "label": v} for k, v in sorted(seen.items(), key=lambda x: x[1])]


def refresh(platforms=None):
    return feerates.refresh(platforms)


def _loop():
    time.sleep(240)
    while True:
        try:
            from core import modules
            if modules.enabled("fin"):
                feerates.refresh()
        except Exception as e:  # noqa: BLE001
            print("平台费率重算失败：", e)
        finally:
            db.release()
        time.sleep(24 * 3600)


def start():
    """每天重算一次费率快照（模块启动流程里调；LH_NO_MODULE_STARTUP 时不会被调用）。"""
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="fin-feerates").start()
