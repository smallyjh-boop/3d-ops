"""店铺对接模块收听的事件（core/chain.py 发出）。"""
import json


def on_order_status(oid, new, old=None, user=""):
    """v2.44.1：在 ERP 里把 Lazada 订单标成「已发货」（发货交接完成 / 标记已发货）→ 在 Lazada 上「安排发货」（Ready to Ship），
    和卖家中心的「安排发货」一样，快递才会来揽收。平台同步回来的状态变化（user 为空 / 系统）不再调。失败只记日志，不影响发货。"""
    if new != "shipped" or old not in ("to_ship", "other") or not user or user in ("系统",) or str(user).startswith("api:"):
        return None
    from core import config, db
    if not config.load_config().get("lazada_auto_rts", True):
        return None
    if not db.conn().execute("SELECT 1 FROM users WHERE username=?", (user,)).fetchone():
        return None                             # 不是员工在 ERP 里操作的（表格导入、平台同步传进来的是来源名）
    return rts_now(oid, user)


def rts_now(oid, user=""):
    """v2.50：订单列表「发货 ▾ → 安排发货」/「安排发货失败」队列里重试：直接在 Lazada 上安排发货（不改 ERP 的状态）。
    返回 None = 不是开了接口的 Lazada 订单；{rts: True/False, error?}。"""
    from core import connectors, db, integrations, orders
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
        _tag(oid, False)
        _resync(sh["id"])
        return {"rts": True, "packages": pkgs}
    except Exception as e:  # noqa: BLE001  平台报错不影响 ERP 发货
        orders.log(oid, user, "Lazada 安排发货失败", str(e)[:300])
        _tag(oid, True)
        return {"rts": False, "error": str(e)}
    finally:
        integrations._store_creds(sh["id"], conn)


FAIL_TAG = "⚠ Lazada 未安排发货"


def _tag(oid, on):
    """v2.44.2：安排发货失败 → 订单打个醒目的标签（订单列表一眼看到，原因在操作记录里）；成功了去掉。"""
    from core import db
    r = db.conn().execute("SELECT tags FROM orders WHERE id=?", (oid,)).fetchone()
    tags = [t for t in str((r and r["tags"]) or "").split(",") if t and t != FAIL_TAG]
    if on:
        tags.append(FAIL_TAG)
    c = db.conn()
    c.execute("UPDATE orders SET tags=? WHERE id=?", (",".join(tags), oid))
    c.commit()


def _resync(shop_id):
    """安排发货成功后，在后台从 Lazada 拉一次订单，ERP 里的状态马上跟平台一致。"""
    import threading

    def go():
        from core import db, integrations
        try:
            integrations.sync_shop(shop_id)
        except Exception:  # noqa: BLE001  拉不下来下次定时同步再拉
            pass
        finally:
            db.release()
    threading.Thread(target=go, daemon=True, name="lz-rts-resync").start()
