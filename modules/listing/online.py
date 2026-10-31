"""在线商品（v2.44）：从开了接口的店铺把在线商品拉回 ERP，在 ERP 里看、筛选、快速改价改库存、上下架。

为什么要拉回来：ERP 原来只认识「用接口推过的」商品；用表格上传的、在卖家中心手动建的，ERP 不知道它们在平台上的编号，
没法改价、同步库存。现在每个店铺定时把全部商品拉一次（Lazada /products/get），按 SellerSku 对上 ERP 产品：
  · 对上的产品记下平台编号（product["lazada_api"] 的 item_id / skus），以后改价、库存同步、更新资料都能用；
  · 上架状态以平台为准（在售 / 审核中 / 审核不通过 / 已下架），不用手动标；
  · 能看出「店里有、ERP 没有」的商品。
按平台分开存（platform 列）；现在接了 Lazada，Shopee 接口通了以后同一张表、同一个页面。

表 online_items：一行一个平台商品；skus 是 JSON（每个 SKU 的 SellerSku、SkuId、价格、促销价、库存、状态、商品链接）。
对外：init() sync(shop_id=None) items(filters) update_sku(...) set_active(...) start()
"""
import json
import time

from core import db, integrations, listing, store

SCHEMA = """
CREATE TABLE IF NOT EXISTS online_items (
  platform TEXT NOT NULL, shop_id INTEGER NOT NULL, item_id TEXT NOT NULL,
  status TEXT, raw_status TEXT, reason TEXT, name TEXT, image TEXT, url TEXT, category TEXT,
  product_id TEXT, skus TEXT, price_min REAL, price_max REAL, qty INTEGER,
  created REAL, updated REAL, synced_at REAL,
  PRIMARY KEY(platform, shop_id, item_id)
);
"""
# 平台状态 → 统一的状态（和上架状态一样的叫法）
LZ = {"active": "live", "inactive": "inactive", "pending qc": "uploaded", "pending": "uploaded", "suspended": "rejected",
      "rejected": "rejected", "deleted": "deleted", "sold-out": "live"}
STATUS_ZH = {"live": "在售", "uploaded": "审核中", "rejected": "审核不通过", "inactive": "已下架", "deleted": "已删除"}
SYNC_EVERY = 1800
PAGE = 50


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()


def _shops(platform=None, shop_id=None):
    rows = db.conn().execute("SELECT id, platform, name FROM shops WHERE enabled=1 ORDER BY id").fetchall()
    return [dict(r) for r in rows if (not platform or r["platform"] == platform) and (not shop_id or r["id"] == int(shop_id))]


def _sku_index():
    """SellerSku（大写）→ (产品编号, 变体序号)。"""
    out = {}
    for it in store.list_products():
        try:
            p = store.load(it["id"])
        except FileNotFoundError:
            continue
        for i, v in enumerate(p.get("variants") or []):
            if v.get("sku"):
                out[v["sku"].strip().upper()] = (p["id"], i)
    return out


def _imgs(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = [v]
    return [x for x in (v or []) if x]


def _reason(prod):
    out = []
    for r in prod.get("rejectReason") or []:
        if isinstance(r, dict):
            out += [str(r.get(k)) for k in ("violationDetail", "suggestion") if r.get(k)]
    for s in prod.get("suspendedSkus") or []:
        if isinstance(s, dict) and (s.get("rejectReason") or s.get("reason")):
            out.append(str(s.get("rejectReason") or s.get("reason")))
    return "；".join(dict.fromkeys(out))[:500]


def _row_lazada(prod):
    raw = str(prod.get("status") or "").strip()
    skus = []
    for s in prod.get("skus") or []:
        skus.append({"seller_sku": str(s.get("SellerSku") or ""), "sku_id": str(s.get("SkuId") or ""),
                     "price": float(s.get("price") or 0), "special_price": float(s.get("special_price") or 0) or None,
                     "special_to": s.get("special_to_date") or "", "qty": int(s.get("quantity") or s.get("Available") or 0),
                     "status": str(s.get("Status") or ""), "url": s.get("Url") or "", "image": next(iter(_imgs(s.get("Images"))), "")})
    prices = [(s["special_price"] or s["price"]) for s in skus if (s["special_price"] or s["price"])]
    attrs = prod.get("attributes") or {}
    return {"item_id": str(prod.get("item_id")), "raw_status": raw, "status": LZ.get(raw.lower(), "uploaded" if raw else ""),
            "reason": _reason(prod), "name": attrs.get("name") or "", "image": next(iter(_imgs(prod.get("images"))), ""),
            "url": next((s["url"] for s in skus if s["url"]), ""), "category": str(prod.get("primary_category") or ""),
            "skus": skus, "price_min": min(prices) if prices else None, "price_max": max(prices) if prices else None,
            "qty": sum(s["qty"] for s in skus), "created": float(prod.get("created_time") or 0) / 1000,
            "updated": float(prod.get("updated_time") or 0) / 1000}


def _link_erp(row, idx, user):
    """对上 ERP 产品：记下平台编号（表格上传的商品从此也能改价、同步库存），上架状态跟平台走。返回产品编号。"""
    hit = next((idx[s["seller_sku"].upper()] for s in row["skus"] if s["seller_sku"].upper() in idx), None)
    if not hit:
        return None
    pid = hit[0]
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return None
    st = dict(p.get("lazada_api") or {})
    changed = False
    if str(st.get("item_id") or "") != row["item_id"]:
        st["item_id"] = row["item_id"]
        changed = True
    skus = dict(st.get("skus") or {})
    for s in row["skus"]:
        if s["seller_sku"] and s["sku_id"] and str(skus.get(s["seller_sku"])) != s["sku_id"]:
            skus[s["seller_sku"]] = s["sku_id"]
            changed = True
    st["skus"] = skus
    if st.get("platform_status") != row["raw_status"]:
        st["platform_status"], changed = row["raw_status"], True
    cur = listing.status_of(p, "lazada")
    new = row["status"] if row["status"] in ("live", "uploaded", "rejected", "inactive") else None
    if new and new != cur.get("status") and not (cur.get("status") == "update" and new == "live"):
        listing._set(p, "lazada", new, note=row["reason"] if new == "rejected" else None, user=user)
        changed = True
    if not p.get("exported_at"):
        p["exported_at"] = int(time.time())                 # 平台上已经有了：SKU 锁定
        changed = True
    if changed:
        p["lazada_api"] = st
        store.save(p)
    return pid


def sync(shop_id=None, user="系统"):
    """把店铺的在线商品拉回来。返回 {shops:[{shop, items, linked, error}]}。"""
    from core import connectors
    from . import lazada_push
    out = []
    idx = None
    for sh in _shops("lazada", shop_id):
        s = integrations.get_shop_raw(sh["id"])
        conn = connectors.make("lazada", s["creds"])
        res = {"shop_id": sh["id"], "shop": sh["name"], "items": 0, "linked": 0, "error": ""}
        try:
            conn.check()
            seen, offset = set(), 0
            idx = idx if idx is not None else _sku_index()
            c = db.conn()
            now = time.time()
            while offset < 10000:
                d = conn.list_products(offset, PAGE)
                prods = d.get("products") or []
                for prod in prods:
                    row = _row_lazada(prod)
                    if not row["item_id"]:
                        continue
                    row["product_id"] = _link_erp(row, idx, user)
                    res["linked"] += bool(row["product_id"])
                    seen.add(row["item_id"])
                    c.execute("INSERT OR REPLACE INTO online_items(platform, shop_id, item_id, status, raw_status, reason, name, image, url, "
                              "category, product_id, skus, price_min, price_max, qty, created, updated, synced_at) "
                              "VALUES('lazada',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (sh["id"], row["item_id"], row["status"], row["raw_status"], row["reason"], row["name"], row["image"],
                               row["url"], row["category"], row["product_id"], json.dumps(row["skus"], ensure_ascii=False),
                               row["price_min"], row["price_max"], row["qty"], row["created"], row["updated"], now))
                c.commit()
                offset += len(prods)
                if len(prods) < PAGE or offset >= int(d.get("total_products") or 0):
                    break
            # 平台上已经没有的（删掉了）：从表里去掉
            for r in c.execute("SELECT item_id FROM online_items WHERE platform='lazada' AND shop_id=?", (sh["id"],)).fetchall():
                if r["item_id"] not in seen:
                    c.execute("DELETE FROM online_items WHERE platform='lazada' AND shop_id=? AND item_id=?", (sh["id"], r["item_id"]))
            c.commit()
            res["items"] = len(seen)
        except Exception as e:  # noqa: BLE001  一个店拉不下来不影响别的
            res["error"] = str(e)[:300]
        finally:
            integrations._store_creds(sh["id"], conn)
        out.append(res)
    if not out:
        raise lazada_push.PushError("还没有启用的 Lazada 店铺（设置 → AI 与对接 → 店铺对接）")
    return {"shops": out}


def _sales_30d(platform):
    rows = db.conn().execute(
        "SELECT UPPER(i.sku) AS sku, SUM(i.qty) AS n FROM order_items i JOIN orders o ON o.id=i.order_id "
        "WHERE o.platform=? AND o.order_time>=? AND o.status NOT IN ('cancelled','unpaid','quote') GROUP BY UPPER(i.sku)",
        (platform, time.time() - 30 * 86400)).fetchall()
    return {r["sku"]: int(r["n"] or 0) for r in rows}


def items(platform="", shop_id=None, status="", q="", linked="", stock0=False, update_pending=False):
    """在线商品列表 + 各状态个数。"""
    c = db.conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM online_items ORDER BY updated DESC")]
    shops = {s["id"]: s for s in (dict(r) for r in c.execute("SELECT id, platform, name FROM shops"))}
    sales = {}
    out, counts = [], {}
    pend = set()
    if update_pending:
        for it in store.list_products():
            try:
                if listing.status_of(store.load(it["id"]), "lazada").get("status") == "update":
                    pend.add(it["id"])
            except FileNotFoundError:
                pass
    for r in rows:
        if platform and r["platform"] != platform:
            continue
        if shop_id and r["shop_id"] != int(shop_id):
            continue
        r["skus"] = json.loads(r["skus"] or "[]")
        r["shop"] = (shops.get(r["shop_id"]) or {}).get("name", "")
        if r["platform"] not in sales:
            sales[r["platform"]] = _sales_30d(r["platform"])
        r["sold_30d"] = sum(sales[r["platform"]].get(s["seller_sku"].upper(), 0) for s in r["skus"])
        r["status_zh"] = STATUS_ZH.get(r["status"], r["raw_status"] or "")
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        if not r["product_id"]:
            counts["unlinked"] = counts.get("unlinked", 0) + 1
        if r["qty"] == 0:
            counts["stock0"] = counts.get("stock0", 0) + 1
        if status and r["status"] != status:
            continue
        if linked == "no" and r["product_id"]:
            continue
        if stock0 and r["qty"] != 0:
            continue
        if update_pending and r["product_id"] not in pend:
            continue
        if q:
            hay = f"{r['name']} {r['item_id']} {r['product_id'] or ''} {' '.join(s['seller_sku'] for s in r['skus'])}".lower()
            if q.lower() not in hay:
                continue
        out.append(r)
    last = c.execute("SELECT MAX(synced_at) FROM online_items").fetchone()[0]
    return {"items": out, "counts": counts, "status_zh": STATUS_ZH, "synced_at": last,
            "shops": [s for s in shops.values() if not platform or s["platform"] == platform]}


def _item(platform, shop_id, item_id):
    r = db.conn().execute("SELECT * FROM online_items WHERE platform=? AND shop_id=? AND item_id=?",
                          (platform, int(shop_id), str(item_id))).fetchone()
    if not r:
        raise ValueError("在线商品不存在（先点「立即同步」）")
    d = dict(r)
    d["skus"] = json.loads(d["skus"] or "[]")
    return d


def _conn(shop_id):
    from core import connectors
    s = integrations.get_shop_raw(int(shop_id))
    conn = connectors.make(s["platform"], s["creds"])
    conn.check()
    return conn


def update_sku(platform, shop_id, item_id, seller_sku, price=None, special_price=None, qty=None, user=""):
    """直接改平台上一个 SKU 的价格 / 促销价 / 库存，同时写回 ERP（售价 = 实际卖的价：有促销价用促销价）。"""
    if platform != "lazada":
        raise ValueError("这个平台还没有接口，只能在平台后台改")
    it = _item(platform, shop_id, item_id)
    sk = next((s for s in it["skus"] if s["seller_sku"] == seller_sku), None)
    if not sk:
        raise ValueError("这个商品里没有这个 SKU")
    body = {"ItemId": str(item_id), "SkuId": sk["sku_id"], "SellerSku": seller_sku}

    def num(v, what, integer=False):
        try:
            x = int(v) if integer else float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{what}要填数字")
        if x < 0 or x != x:
            raise ValueError(f"{what}不能是负数")
        return x
    if price not in (None, ""):
        body["Price"] = str(num(price, "价格"))
    if special_price not in (None, ""):
        sp = num(special_price, "促销价")
        if sp:
            body["SalePrice"] = str(sp)
            body["SaleStartDate"] = time.strftime("%Y-%m-%d")
            body["SaleEndDate"] = time.strftime("%Y-%m-%d", time.localtime(time.time() + 365 * 86400))
    if qty not in (None, ""):
        body["Quantity"] = str(num(qty, "库存", True))
    if len(body) == 3:
        raise ValueError("没有要改的")
    conn = _conn(shop_id)
    try:
        conn.update_price_quantity([body])
    finally:
        integrations._store_creds(int(shop_id), conn)
    # 写回在线商品表
    if "Price" in body:
        sk["price"] = float(body["Price"])
    if "SalePrice" in body:
        sk["special_price"] = float(body["SalePrice"])
    if "Quantity" in body:
        sk["qty"] = int(body["Quantity"])
    prices = [(s["special_price"] or s["price"]) for s in it["skus"] if (s["special_price"] or s["price"])]
    c = db.conn()
    c.execute("UPDATE online_items SET skus=?, price_min=?, price_max=?, qty=? WHERE platform=? AND shop_id=? AND item_id=?",
              (json.dumps(it["skus"], ensure_ascii=False), min(prices) if prices else None, max(prices) if prices else None,
               sum(s["qty"] for s in it["skus"]), platform, int(shop_id), str(item_id)))
    c.commit()
    # 写回 ERP：售价（两边一致）、库存（没开按耗材算库存时）
    erp = _write_back(it.get("product_id"), seller_sku, sk, "Quantity" in body, user)
    db.audit(user, "在线商品改价 / 库存", f"{platform}:{item_id}", json.dumps(body, ensure_ascii=False)[:300])
    return {"ok": True, "sku": sk, "erp": erp}


def _write_back(pid, seller_sku, sk, qty_changed, user):
    if not pid:
        return ""
    from core import stockcalc
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return ""
    v = next((v for v in p.get("variants") or [] if (v.get("sku") or "").upper() == seller_sku.upper()), None)
    if not v:
        return ""
    done = []
    real = sk.get("special_price") or sk.get("price")
    if real:
        v["manual_price"] = real
        done.append(f"售价 ฿{real:g}")
    if qty_changed:
        if stockcalc.enabled(p):
            done.append("库存按耗材自动算，ERP 不改")
        else:
            v["stock"] = sk["qty"]
            done.append(f"库存 {sk['qty']}")
        stockcalc.mark_synced([{"sku": seller_sku, "stock": sk["qty"], "product_id": pid}], user, "online", "lazada")
    store.save(p)
    return "、".join(done)


def set_active(platform, shop_id, item_id, active, user=""):
    """上架 / 下架整个商品。"""
    if platform != "lazada":
        raise ValueError("这个平台还没有接口，只能在平台后台操作")
    it = _item(platform, shop_id, item_id)
    conn = _conn(shop_id)
    try:
        if active:
            conn.update_product({"ItemId": str(item_id), "Skus": {"Sku": [{"SkuId": s["sku_id"], "SellerSku": s["seller_sku"],
                                                                           "Status": "active"} for s in it["skus"]]}})
        else:
            conn.deactivate(item_id)
    finally:
        integrations._store_creds(int(shop_id), conn)
    st = "live" if active else "inactive"
    c = db.conn()
    c.execute("UPDATE online_items SET status=?, raw_status=? WHERE platform=? AND shop_id=? AND item_id=?",
              (st, "active" if active else "inactive", platform, int(shop_id), str(item_id)))
    c.commit()
    if it.get("product_id"):
        try:
            p = store.load(it["product_id"])
            listing._set(p, "lazada", st, user=user)
            store.save(p)
        except FileNotFoundError:
            pass
    db.audit(user, "在线商品" + ("上架" if active else "下架"), f"{platform}:{item_id}", it.get("name", "")[:100])
    return {"ok": True, "status": st}


def platforms_of(pid):
    """产品库用：这个产品在哪些店铺在线（[{platform, shop, status}]）。"""
    shops = {r["id"]: r["name"] for r in db.conn().execute("SELECT id, name FROM shops")}
    return [{"platform": r["platform"], "shop": shops.get(r["shop_id"], ""), "status": r["status"]}
            for r in db.conn().execute("SELECT platform, shop_id, status FROM online_items WHERE product_id=?", (pid,))]


def all_platforms():
    """{产品编号: [{platform, shop, status}]}（产品库列表一次取完）。"""
    shops = {r["id"]: r["name"] for r in db.conn().execute("SELECT id, name FROM shops")}
    out = {}
    for r in db.conn().execute("SELECT product_id, platform, shop_id, status FROM online_items WHERE product_id IS NOT NULL"):
        out.setdefault(r["product_id"], []).append({"platform": r["platform"], "shop": shops.get(r["shop_id"], ""), "status": r["status"]})
    return out
