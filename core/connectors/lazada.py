"""Lazada 开放平台（Lazada Open Platform）订单拉取。

需要：在 open.lazada.com 注册开发者、创建应用（App Key / App Secret），用卖家账号授权后得到 access_token。
按官方文档编写（签名 HMAC-SHA256、/orders/get、/orders/items/get、/auth/token/refresh），
拿到正式 App Key 后需要联调确认。
"""
import datetime as dt
import hashlib
import hmac
import json
import time
import urllib.parse

import requests

from . import Connector, NotReady

API = "https://api.lazada.co.th/rest"
AUTH = "https://auth.lazada.com/rest"
TZ = dt.timezone(dt.timedelta(hours=7))

STATUS = {
    "unpaid": "unpaid", "pending": "to_ship", "packed": "to_ship", "ready_to_ship": "to_ship",
    "ready_to_ship_pending": "to_ship", "repacked": "to_ship", "topack": "to_ship", "toship": "to_ship",
    "shipped": "shipped", "shipped_back": "returned", "delivered": "completed", "confirmed": "completed",
    "canceled": "cancelled", "cancelled": "cancelled", "failed": "cancelled", "failed_delivery": "returned",
    "lost_by_3pl": "cancelled", "damaged_by_3pl": "cancelled",
    "returned": "returned", "return_waiting_for_approval": "returned", "return_shipped_by_customer": "returned",
}


def sign(secret, api_path, params):
    s = api_path + "".join(f"{k}{params[k]}" for k in sorted(params))
    return hmac.new(secret.encode(), s.encode(), hashlib.sha256).hexdigest().upper()


def _ts(s):
    """'2026-10-04 10:00:00 +0700' / ISO → Unix 秒"""
    s = str(s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            d = dt.datetime.strptime(s, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=TZ)
            return d.timestamp()
        except ValueError:
            continue
    try:
        return dt.datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


class LazadaConnector(Connector):
    PLATFORM = "lazada"
    LABEL = "Lazada"
    READY = True
    NOTE = "需要 Lazada 开放平台的 App Key / App Secret 和店铺授权（access_token）。" \
           "回调地址必须是 https，和 Lazada 后台应用里填的 Callback URL 一字不差（例如 https://www.google.com/）；" \
           "授权后把浏览器地址栏的整个网址粘贴到下面的框里换 token。按官方文档编写，拿到正式 App Key 后需要联调确认。"
    FIELDS = [("app_key", "App Key", False), ("app_secret", "App Secret", True),
              ("callback_url", "Callback URL（回调地址）", False),
              ("access_token", "Access Token", True), ("refresh_token", "Refresh Token", True)]
    OPTIONAL = ("callback_url",)   # v2.41.2：Lazada 只认 https 回调；不填就用系统自己的地址
    # v2.41.2 面单：订单在 Lazada 打包后有包裹号（package_id）→ /order/package/document/get 按包裹取 PDF
    LABEL_READY = True
    LABEL_NOTE = "打印时自动从 Lazada 取面单（订单要先在 Lazada 打包）"
    LABEL_NOTE_TH = "ดึงใบปะหน้าจาก Lazada อัตโนมัติตอนพิมพ์ (ต้องแพ็กใน Lazada ก่อน)"

    # ---------- 授权 ----------
    def authorize_url(self, redirect_uri):
        redirect_uri = str(self.creds.get("callback_url") or "").strip() or redirect_uri
        q = {"response_type": "code", "force_auth": "true", "redirect_uri": redirect_uri, "client_id": self.creds.get("app_key", "")}
        return "https://auth.lazada.com/oauth/authorize?" + urllib.parse.urlencode(q)

    def exchange_code(self, code):
        r = self._call("/auth/token/create", {"code": code}, base=AUTH, token=False)
        self._save_token(r)
        return r

    def _save_token(self, r):
        if not r.get("access_token"):
            raise NotReady("Lazada 授权失败：" + str(r.get("message") or r))
        self.creds["access_token"] = r["access_token"]
        if r.get("refresh_token"):
            self.creds["refresh_token"] = r["refresh_token"]
        self.creds["token_expire"] = time.time() + float(r.get("expires_in") or 0)
        self.creds["refresh_expire"] = time.time() + float(r.get("refresh_expires_in") or 0)
        self.creds_changed = True

    def refresh(self):
        r = self._call("/auth/token/refresh", {"refresh_token": self.creds.get("refresh_token", "")}, base=AUTH, token=False)
        self._save_token(r)

    # ---------- 请求 ----------
    def _call(self, path, params, base=API, token=True, method="GET"):
        p = {"app_key": self.creds.get("app_key", ""), "timestamp": str(int(time.time() * 1000)), "sign_method": "sha256"}
        if token:
            p["access_token"] = self.creds.get("access_token", "")
        p.update({k: str(v) for k, v in params.items() if v is not None})
        p["sign"] = sign(self.creds.get("app_secret", ""), path, p)
        if method == "POST":
            resp = requests.post(base + path, data=p, timeout=30)
        else:
            resp = requests.get(base + path, params=p, timeout=30)
        data = resp.json()
        if str(data.get("code", "0")) != "0":
            # v2.41.2：建产品出错时 detail 里有具体哪个字段不对
            det = "；".join(f"{d.get('field') or ''} {d.get('message') or ''}".strip() for d in (data.get("detail") or [])
                           if isinstance(d, dict))
            raise RuntimeError(f"Lazada {path} 出错：{data.get('code')} {data.get('message')}" + (f"（{det}）" if det else ""))
        return data

    def _ensure_token(self):
        exp = float(self.creds.get("token_expire") or 0)
        if exp and exp < time.time() + 3600 and self.creds.get("refresh_token"):
            self.refresh()

    # ---------- 订单 ----------
    def fetch_orders(self, since, until):
        self.check()
        self._ensure_token()
        after = dt.datetime.fromtimestamp(since, TZ).isoformat(timespec="seconds")
        raw_orders, offset = [], 0
        while True:
            d = self._call("/orders/get", {"update_after": after, "sort_by": "updated_at", "sort_direction": "ASC",
                                           "offset": offset, "limit": 100}).get("data") or {}
            batch = d.get("orders") or []
            raw_orders += batch
            offset += len(batch)
            if len(batch) < 100 or offset >= int(d.get("countTotal") or d.get("count") or 0) or offset >= 5000:
                break
        return self._with_items(raw_orders)

    def _with_items(self, raw_orders):
        items = {}
        ids = [str(o["order_id"]) for o in raw_orders]
        for i in range(0, len(ids), 50):
            d = self._call("/orders/items/get", {"order_ids": json.dumps([int(x) for x in ids[i:i + 50]])}).get("data") or []
            for row in d:
                items[str(row.get("order_id"))] = row.get("order_items") or []
        return [self.convert(o, items.get(str(o["order_id"]), [])) for o in raw_orders]

    def convert(self, o, order_items):
        sts = [str(s).lower() for s in (o.get("statuses") or [])]
        status = next((STATUS[s] for s in sts if s in STATUS), "other") if sts else "other"
        # Lazada 每件商品单独一行，同 SKU 合并
        merged = {}
        tracking = carrier = ""
        packages = []
        for it in order_items:
            key = (it.get("sku") or it.get("shop_sku") or "", it.get("variation") or "")
            m = merged.setdefault(key, {"sku": key[0], "name": it.get("name") or "", "variation": key[1], "qty": 0,
                                        "unit_price": float(it.get("item_price") or it.get("paid_price") or 0), "item_total": 0.0})
            m["qty"] += 1
            m["item_total"] += float(it.get("paid_price") or it.get("item_price") or 0)
            tracking = tracking or it.get("tracking_code") or ""
            carrier = carrier or it.get("shipment_provider") or ""
            if it.get("package_id") and it["package_id"] not in packages:
                packages.append(it["package_id"])
        buyer = " ".join(x for x in (o.get("customer_first_name"), o.get("customer_last_name")) if x)
        ship_by = None
        pst = o.get("promised_shipping_times")
        if pst:
            ship_by = _ts(pst if isinstance(pst, str) else "")
        return {
            "platform": "lazada", "order_no": str(o.get("order_number") or o.get("order_id")),
            "status": status, "order_time": _ts(o.get("created_at")), "ship_by": ship_by,
            "buyer": buyer, "buyer_note": o.get("remarks") or "",
            "order_total": o.get("price"), "shipping_fee": o.get("shipping_fee"),
            "tracking_no": tracking, "items": list(merged.values()),
            "payment": o.get("payment_method") or "", "carrier": carrier,
            "cod": o.get("price") if str(o.get("payment_method") or "").upper() == "COD" else None,
            "raw": {"order_id": o.get("order_id"), "statuses": o.get("statuses"), "packages": packages},
        }

    # ---------- 面单 ----------
    def fetch_label(self, order):
        """按包裹取 Lazada 面单 PDF。包裹号现取（订单导入时可能还没打包）。"""
        self.check()
        self._ensure_token()
        raw = order.get("raw") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                raw = {}
        oid = raw.get("order_id") or order.get("order_no")
        d = self._call("/orders/items/get", {"order_ids": json.dumps([int(oid)])}).get("data") or []
        items = next((r.get("order_items") or [] for r in d if str(r.get("order_id")) == str(oid)), [])
        pkgs = list(dict.fromkeys(it.get("package_id") for it in items if it.get("package_id")))
        if not pkgs:
            raise NotReady("这个订单在 Lazada 还没打包（没有包裹号），先在 Lazada 打包再打印")
        req = {"doc_type": "PDF", "packages": [{"package_id": p} for p in pkgs], "print_item_list": False}
        r = self._call("/order/package/document/get", {"getDocumentReq": json.dumps(req)}, method="POST")
        res = r.get("result") or {}
        if res.get("success") is False or not (res.get("data") or {}).get("pdf_url"):
            raise RuntimeError(f"Lazada 没有返回面单：{res.get('error_msg') or res.get('error_code') or json.dumps(r)[:300]}")
        pdf = requests.get(res["data"]["pdf_url"], timeout=60)
        pdf.raise_for_status()
        tracking = next((it.get("tracking_code") for it in items if it.get("tracking_code")), "")
        return {"kind": "pdf", "data": pdf.content, "tracking_no": tracking}

    # ---------- 推送（Lazada Push Mechanism）----------
    def handle_webhook(self, headers, body, url=""):
        secret = self.creds.get("app_secret", "")
        if secret:
            expect = hmac.new(secret.encode(), (self.creds.get("app_key", "") + body.decode("utf-8", "replace")).encode(),
                              hashlib.sha256).hexdigest()
            if headers.get("Authorization", "").lower() != expect:
                raise PermissionError("签名不对")
        msg = json.loads(body or b"{}")
        if str(msg.get("message_type")) != "0":      # 0 = 订单状态变化
            return None
        oid = (msg.get("data") or {}).get("trade_order_id")
        if not oid:
            return None
        self._ensure_token()
        o = (self._call("/order/get", {"order_id": oid}).get("data") or {})
        return self._with_items([o]) if o else None

    # ---------- 商品（v2.41.2：ERP 产品推到 Lazada，modules/listing/lazada_push.py）----------
    def category_attributes(self, cat_id):
        """类目属性：[{id, name, label, input_type, is_mandatory, attribute_type(normal / sku), options:[{id, name}]}]"""
        self._ensure_token()
        return self._call("/category/attributes/get", {"primary_category_id": cat_id, "language_code": "th_TH"}).get("data") or []

    def migrate_image(self, url):
        """外面的图片网址 → Lazada 图片空间的网址（建产品只认 Lazada 的图片）。"""
        self._ensure_token()
        x = ("<?xml version=\"1.0\" encoding=\"UTF-8\" ?><Request><Image><Url>"
             + url.replace("&", "&amp;").replace("<", "&lt;") + "</Url></Image></Request>")
        img = (self._call("/image/migrate", {"payload": x}, method="POST").get("data") or {}).get("image") or {}
        if not img.get("url"):
            raise RuntimeError(f"Lazada 没有返回图片网址：{url}")
        return img["url"]

    def _product(self, path, product):
        self._ensure_token()
        payload = json.dumps({"Request": {"Product": product}}, ensure_ascii=False)
        return self._call(path, {"payload": payload}, method="POST").get("data") or {}

    def create_product(self, product):
        """返回 {item_id, sku_list:[{seller_sku, sku_id, shop_sku}]}"""
        return self._product("/product/create", product)

    def update_product(self, product):
        return self._product("/product/update", product)

    def update_price_quantity(self, skus):
        """skus：[{ItemId, SkuId, SellerSku, Quantity?, Price?}]，一次最多 50 个。"""
        return self._product("/product/price_quantity/update", {"Skus": {"Sku": skus}})

    def get_item(self, item_id):
        self._ensure_token()
        return self._call("/product/item/get", {"item_id": item_id}).get("data") or {}
