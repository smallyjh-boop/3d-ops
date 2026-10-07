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
           "按官方文档编写，拿到正式 App Key 后需要联调确认。"
    FIELDS = [("app_key", "App Key", False), ("app_secret", "App Secret", True),
              ("access_token", "Access Token", True), ("refresh_token", "Refresh Token", True)]

    # ---------- 授权 ----------
    def authorize_url(self, redirect_uri):
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
            raise RuntimeError(f"Lazada {path} 出错：{data.get('code')} {data.get('message')}")
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
        tracking = ""
        for it in order_items:
            key = (it.get("sku") or it.get("shop_sku") or "", it.get("variation") or "")
            m = merged.setdefault(key, {"sku": key[0], "name": it.get("name") or "", "variation": key[1], "qty": 0,
                                        "unit_price": float(it.get("item_price") or it.get("paid_price") or 0), "item_total": 0.0})
            m["qty"] += 1
            m["item_total"] += float(it.get("paid_price") or it.get("item_price") or 0)
            tracking = tracking or it.get("tracking_code") or ""
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
            "raw": {"order_id": o.get("order_id"), "statuses": o.get("statuses")},
        }

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
