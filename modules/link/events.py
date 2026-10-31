"""店铺对接模块收听的事件（core/chain.py 发出）。"""
import json


def on_order_status(oid, new, old=None, user=""):
    """v2.44.1：在 ERP 里把 Lazada 订单标成「已发货」（发货交接完成 / 标记已发货）→ 在 Lazada 上「安排发货」（Ready to Ship），
    和卖家中心的「安排发货」一样，快递才会来揽收。平台同步回来的状态变化（user 为空 / 系统）不再调。失败只记日志，不影响发货。"""
    if new != "shipped" or old not in ("to_ship", "other") or not user or user in ("系统",) or str(user).startswith("api:"):
        return None
    from core import config, connectors, db, integrations, orders
    if not config.load_config().get("lazada_auto_rts", True):
        return None
    if not db.conn().execute("SELECT 1 FROM users WHERE username=?", (user,)).fetchone():
        return None                             # 不是员工在 ERP 里操作的（表格导入、平台同步传进来的是来源名）
    r = db.conn().execute("SELECT platform, shop, raw FROM orders WHERE id=?", (oid,)).fetchone()
    if not r or r["platform"] != "lazada":
        return None
    shops = db.conn().execute("SELECT id, name FROM shops WHERE platform='lazada' AND enabled=1").fetchall()
    sh = shops[0] if len(shops) == 1 else next((x for x in shops if (x["name"] or "").strip() == (r["shop"] or "").strip()), None)
    if not sh:
        return None
    try:
        raw = json.loads(r["raw"] or "{}")
    except ValueError:
        raw = {}
    if not raw.get("order_id"):
        return None
    s = integrations.get_shop_raw(sh["id"])
    conn = connectors.make("lazada", s["creds"])
    try:
        pkgs = conn.packages_of(raw["order_id"])
        if not pkgs:
            orders.log(oid, user, "Lazada 安排发货", "Lazada 上还没打包（先打印面单会自动打包），没有安排发货")
            return {"rts": False}
        conn.rts(pkgs)
        orders.log(oid, user, "Lazada 安排发货", "、".join(pkgs))
        return {"rts": True, "packages": pkgs}
    except Exception as e:  # noqa: BLE001  平台报错不影响 ERP 发货
        orders.log(oid, user, "Lazada 安排发货失败", str(e)[:300])
        return {"rts": False, "error": str(e)}
    finally:
        integrations._store_creds(sh["id"], conn)
