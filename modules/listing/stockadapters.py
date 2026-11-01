"""库存同步的平台适配器（v2.53）：每个平台一个适配器，库存同步引擎（stocksync.py）只认这个接口。

  api_ready(shop)            这个店铺现在能不能用接口推库存（False = 走「待导出」）
  push(shop, items)          items = [{sku, qty}]；返回 {SKU 大写: {"ok": bool, "error": 原因}}
  pull(shop)                 把平台上现在显示的库存拉回来：{SKU 大写: {"qty", "status", "item_id"}}；不支持返回 None

Shopee / TikTok 还没有接口：用 ManualAdapter（api_ready 永远 False，引擎出「待导出」表格）。
以后接口通了：写一个子类、实现 api_ready / push / pull，然后 register("shopee", 新类) —— 引擎自动改成直接推送，别的代码不用动。
"""
import json

from core import connectors, db, integrations, store


class StockAdapter:
    platform = ""
    label = ""

    def api_ready(self, shop):
        return False

    def push(self, shop, items):
        raise NotImplementedError

    def pull(self, shop):
        return None


class ManualAdapter(StockAdapter):
    """没有接口的平台：出导出表格，人工上传后点「已上传」。"""

    def __init__(self, platform=""):
        self.platform = platform
        self.label = platform


def classify_error(msg):
    """把平台报错归类成一句人话（待办里显示原因）。返回 (类别, 说明)。"""
    m = str(msg or "")
    low = m.lower()
    if any(k in low for k in ("token", "illegalaccess", "unauthor", "expired", "授权")):
        return "token", "授权（token）已过期，请到店铺对接重新授权"
    if "找不到" in m or "not found" in low or "sku" in low and "exist" in low or "invalid sku" in low:
        return "sku", "平台上找不到这个 SKU"
    if "timeout" in low or "timed out" in low or "connection" in low:
        return "net", "网络超时"
    return "other", m[:200]


class LazadaAdapter(StockAdapter):
    platform = "lazada"
    label = "Lazada"
    BATCH = 20

    def _conn(self, shop):
        s = integrations.get_shop_raw(int(shop["id"]))
        conn = connectors.make("lazada", s["creds"])
        conn.check()
        return conn

    def api_ready(self, shop):
        if int(shop.get("id") or 0) <= 0 or not shop.get("enabled"):
            return False
        try:
            self._conn(shop)
            return True
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _ids(shop_id):
        """{SKU 大写: (item_id, sku_id, 平台状态)}：从在线商品表（定时拉的）里查，没有再用产品里记的推送编号。"""
        out = {}
        for r in db.conn().execute("SELECT item_id, status, skus FROM online_items WHERE platform='lazada' AND shop_id=?", (int(shop_id),)):
            for s in json.loads(r["skus"] or "[]"):
                k = str(s.get("seller_sku") or "").strip().upper()
                if k and s.get("sku_id"):
                    out[k] = (str(r["item_id"]), str(s["sku_id"]), r["status"])
        return out

    def push(self, shop, items):
        res = {}
        ids = self._ids(shop["id"])
        todo = []
        for it in items:
            k = it["sku"].upper()
            hit = ids.get(k)
            if not hit:
                try:                                              # 用接口推送过的产品，产品里记着编号
                    from . import stocksync
                    p = store.load(stocksync.product_of(k))
                    st = p.get("lazada_api") or {}
                    if st.get("item_id") and (st.get("skus") or {}).get(k):
                        hit = (str(st["item_id"]), str(st["skus"][k]), "")
                except Exception:  # noqa: BLE001
                    hit = None
            if not hit:
                res[k] = {"ok": False, "error": "SKU 在平台上找不到（还没拉回在线商品，或还没上架）"}
                continue
            todo.append((k, {"ItemId": hit[0], "SkuId": hit[1], "SellerSku": k, "Quantity": int(it["qty"])}))
        if not todo:
            return res
        try:
            conn = self._conn(shop)
        except Exception as e:  # noqa: BLE001
            for k, _ in todo:
                res[k] = {"ok": False, "error": f"店铺没授权好：{e}"}
            return res
        try:
            for i in range(0, len(todo), self.BATCH):
                part = todo[i:i + self.BATCH]
                try:
                    conn.update_price_quantity([x[1] for x in part])
                    for k, _ in part:
                        res[k] = {"ok": True, "error": ""}
                except Exception as e:  # noqa: BLE001           一批失败：逐个再试，才知道是哪个 SKU 的问题
                    if len(part) == 1:
                        res[part[0][0]] = {"ok": False, "error": str(e)[:300]}
                        continue
                    for k, body in part:
                        try:
                            conn.update_price_quantity([body])
                            res[k] = {"ok": True, "error": ""}
                        except Exception as e2:  # noqa: BLE001
                            res[k] = {"ok": False, "error": str(e2)[:300]}
        finally:
            integrations._store_creds(shop["id"], conn)
        return res

    def pull(self, shop):
        from . import online
        online.init()
        r = online.sync(shop["id"], "库存同步")["shops"][0]
        if r.get("error"):
            raise RuntimeError(r["error"])
        out = {}
        for row in db.conn().execute("SELECT item_id, status, skus FROM online_items WHERE platform='lazada' AND shop_id=?", (int(shop["id"]),)):
            for s in json.loads(row["skus"] or "[]"):
                k = str(s.get("seller_sku") or "").strip().upper()
                if k:
                    out[k] = {"qty": int(s.get("qty") or 0), "status": row["status"], "item_id": row["item_id"]}
        return out


_REG = {"lazada": LazadaAdapter()}


def register(platform, adapter):
    """接口通了以后：register("shopee", ShopeeAdapter())，引擎自动从「待导出」改成直接推送。"""
    _REG[platform] = adapter


def get(platform):
    return _REG.get(platform) or ManualAdapter(platform)
