"""上架导出模块给别的模块用的（modules.public("listing")，模块关着时别的模块拿到 None）。"""


def online_shops():
    """{产品编号: [{platform, shop, status}]}：这个产品在哪些店铺在线（在线商品表，v2.44）。"""
    from . import online
    online.init()
    return online.all_platforms()


def online_skus():
    """v2.46（运营分析：商品生命周期、售价低于最低价）：{SellerSku 大写: [{platform, shop_id, item_id, status, created, price}]}。
    status 是统一的叫法（live 在售 / uploaded 审核中 / rejected / inactive / deleted）；price = 平台上实际卖的价（有促销价用促销价）；
    created = 商品在平台上建的时间（Unix 秒，没有为 None）。"""
    import json
    from core import db
    from . import online
    online.init()
    out = {}
    for r in db.conn().execute("SELECT platform, shop_id, item_id, status, created, skus FROM online_items"):
        for s in json.loads(r["skus"] or "[]"):
            sku = str(s.get("seller_sku") or "").strip().upper()
            if sku:
                out.setdefault(sku, []).append({"platform": r["platform"], "shop_id": r["shop_id"], "item_id": r["item_id"],
                                                "status": r["status"], "created": r["created"] or None,
                                                "price": s.get("special_price") or s.get("price") or None})
    return out


def online_item_names(platform="lazada"):
    """v2.46：{item_id: (商品名, ERP 产品编号)}（运营分析的评价列表显示是哪个商品）。"""
    from core import db
    from . import online
    online.init()
    return {str(r["item_id"]): (r["name"] or "", r["product_id"] or "")
            for r in db.conn().execute("SELECT item_id, name, product_id FROM online_items WHERE platform=?", (platform,))}


def online_item_ids(platform="lazada", shop_id=None, status="live"):
    """v2.46（运营分析：拉评价要按商品拉）：这个店铺在线商品的平台编号 [item_id]（status 空 = 全部）。"""
    from core import db
    from . import online
    online.init()
    q, a = "SELECT item_id FROM online_items WHERE platform=?", [platform]
    if shop_id is not None:
        q += " AND shop_id=?"
        a.append(int(shop_id))
    if status:
        q += " AND status=?"
        a.append(status)
    return [r[0] for r in db.conn().execute(q + " ORDER BY updated DESC", a)]


def product_online(pid, skus=()):
    """商品 360 抽屉：这个产品在各店铺的在线商品（product_id 对上，或者任一 SellerSku 对上）。
    [{platform, shop_id, shop, item_id, status, status_zh, raw_status, reason, name, url, price_min, price_max, qty, created, updated,
      skus:[{seller_sku, price, special_price, qty, status}]}]"""
    import json
    from core import db
    from . import online
    online.init()
    want = {str(s or "").strip().upper() for s in skus if s}
    shops = {r["id"]: r["name"] for r in db.conn().execute("SELECT id, name FROM shops")}
    out = []
    for r in db.conn().execute("SELECT * FROM online_items ORDER BY platform, shop_id, updated DESC"):
        sk = json.loads(r["skus"] or "[]")
        mine = [s for s in sk if str(s.get("seller_sku") or "").strip().upper() in want]
        if r["product_id"] != pid and not mine:
            continue
        out.append({"platform": r["platform"], "shop_id": r["shop_id"], "shop": shops.get(r["shop_id"], ""), "item_id": r["item_id"],
                    "status": r["status"], "status_zh": online.STATUS_ZH.get(r["status"] or "", r["status"] or ""),
                    "raw_status": r["raw_status"], "reason": r["reason"] or "", "name": r["name"] or "", "url": r["url"] or "",
                    "price_min": r["price_min"], "price_max": r["price_max"], "qty": r["qty"], "created": r["created"] or None,
                    "updated": r["updated"] or None,
                    "skus": [{k: s.get(k) for k in ("seller_sku", "price", "special_price", "qty", "status")} for s in (mine or sk)]})
    return out
