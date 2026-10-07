"""Shopee 开放平台（Open Platform v2）订单拉取。

需要：在 open.shopee.com 注册开发者、创建应用（Partner ID / Partner Key），用卖家账号授权店铺后得到
shop_id 和 access_token（4 小时有效，自动用 refresh_token 续期）。
按官方文档编写，拿到正式 Partner ID 后需要联调确认。
"""
import hashlib
import hmac
import json
import time
import urllib.parse

import requests

from . import Connector, NotReady

HOST = "https://partner.shopeemobile.com"

STATUS = {
    "UNPAID": "unpaid", "READY_TO_SHIP": "to_ship", "PROCESSED": "to_ship", "RETRY_SHIP": "to_ship",
    "SHIPPED": "shipped", "TO_CONFIRM_RECEIVE": "shipped", "COMPLETED": "completed",
    "IN_CANCEL": "cancelled", "CANCELLED": "cancelled", "TO_RETURN": "returned",
}


def _sign(key, base):
    return hmac.new(key.encode(), base.encode(), hashlib.sha256).hexdigest()


class ShopeeConnector(Connector):
    PLATFORM = "shopee"
    LABEL = "Shopee"
    READY = True
    NOTE = "需要 Shopee 开放平台的 Partner ID / Partner Key，并授权店铺（得到 Shop ID 和 token）。" \
           "按官方文档编写，拿到正式 Partner ID 后需要联调确认。"
    FIELDS = [("partner_id", "Partner ID", False), ("partner_key", "Partner Key", True), ("shop_id", "Shop ID", False),
              ("access_token", "Access Token", True), ("refresh_token", "Refresh Token", True)]

    # ---------- 授权 ----------
    def authorize_url(self, redirect_uri):
        path, ts = "/api/v2/shop/auth_partner", int(time.time())
        pid = str(self.creds.get("partner_id", ""))
        q = {"partner_id": pid, "timestamp": ts, "sign": _sign(self.creds.get("partner_key", ""), f"{pid}{path}{ts}"),
             "redirect": redirect_uri}
        return HOST + path + "?" + urllib.parse.urlencode(q)

    def _public(self, path, body):
        ts = int(time.time())
        pid = str(self.creds.get("partner_id", ""))
        q = {"partner_id": pid, "timestamp": ts, "sign": _sign(self.creds.get("partner_key", ""), f"{pid}{path}{ts}")}
        data = requests.post(HOST + path, params=q, json=body, timeout=30).json()
        if data.get("error"):
            raise NotReady(f"Shopee 授权失败：{data.get('error')} {data.get('message')}")
        self.creds["access_token"] = data["access_token"]
        self.creds["refresh_token"] = data.get("refresh_token") or self.creds.get("refresh_token")
        self.creds["token_expire"] = time.time() + float(data.get("expire_in") or 14400)
        self.creds_changed = True
        return data

    def exchange_code(self, code):
        return self._public("/api/v2/auth/token/get", {"code": code, "shop_id": int(self.creds.get("shop_id") or 0),
                                                       "partner_id": int(self.creds.get("partner_id") or 0)})

    def refresh(self):
        return self._public("/api/v2/auth/access_token/get", {"refresh_token": self.creds.get("refresh_token", ""),
                                                              "shop_id": int(self.creds.get("shop_id") or 0),
                                                              "partner_id": int(self.creds.get("partner_id") or 0)})

    def _ensure_token(self):
        exp = float(self.creds.get("token_expire") or 0)
        if (not exp or exp < time.time() + 600) and self.creds.get("refresh_token"):
            self.refresh()

    # ---------- 请求 ----------
    def _get(self, path, params):
        ts = int(time.time())
        pid, sid, tok = str(self.creds.get("partner_id", "")), str(self.creds.get("shop_id", "")), self.creds.get("access_token", "")
        q = {"partner_id": pid, "timestamp": ts, "access_token": tok, "shop_id": sid,
             "sign": _sign(self.creds.get("partner_key", ""), f"{pid}{path}{ts}{tok}{sid}")}
        q.update(params)
        data = requests.get(HOST + path, params=q, timeout=30).json()
        if data.get("error"):
            raise RuntimeError(f"Shopee {path} 出错：{data.get('error')} {data.get('message')}")
        return data.get("response") or {}

    # ---------- 订单 ----------
    def fetch_orders(self, since, until):
        self.check()
        self._ensure_token()
        sns, t0 = [], int(since)
        while t0 < until:                              # 一次最多查 15 天
            t1 = min(int(until), t0 + 15 * 86400 - 60)
            cursor = ""
            while True:
                r = self._get("/api/v2/order/get_order_list", {"time_range_field": "update_time", "time_from": t0,
                                                               "time_to": t1, "page_size": 100, "cursor": cursor})
                sns += [o["order_sn"] for o in r.get("order_list") or []]
                if not r.get("more"):
                    break
                cursor = r.get("next_cursor") or ""
            t0 = t1
        return self.details(list(dict.fromkeys(sns)))

    def details(self, sns):
        out = []
        fields = "buyer_username,item_list,total_amount,ship_by_date,note,message_to_seller,actual_shipping_fee," \
                 "estimated_shipping_fee,pay_time"
        for i in range(0, len(sns), 50):
            r = self._get("/api/v2/order/get_order_detail", {"order_sn_list": ",".join(sns[i:i + 50]),
                                                             "response_optional_fields": fields})
            out += [self.convert(o) for o in r.get("order_list") or []]
        return out

    def convert(self, o):
        items = []
        for it in o.get("item_list") or []:
            qty = int(it.get("model_quantity_purchased") or 1)
            price = float(it.get("model_discounted_price") or it.get("model_original_price") or 0)
            items.append({"sku": it.get("model_sku") or it.get("item_sku") or "", "name": it.get("item_name") or "",
                          "variation": it.get("model_name") or "", "qty": qty, "unit_price": price, "item_total": price * qty})
        return {
            "platform": "shopee", "order_no": o.get("order_sn"), "status": STATUS.get(o.get("order_status"), "other"),
            "order_time": o.get("create_time"), "ship_by": o.get("ship_by_date"),
            "buyer": o.get("buyer_username") or "", "buyer_note": o.get("message_to_seller") or "",
            "seller_note": o.get("note") or "", "order_total": o.get("total_amount"),
            "shipping_fee": o.get("actual_shipping_fee") or o.get("estimated_shipping_fee"),
            "items": items, "raw": {"order_status": o.get("order_status")},
        }

    # ---------- 推送（Shopee Push）----------
    def handle_webhook(self, headers, body, url=""):
        key = self.creds.get("partner_key", "")
        if key and url:
            expect = _sign(key, url + "|" + body.decode("utf-8", "replace"))
            if headers.get("Authorization", "") != expect:
                raise PermissionError("签名不对")
        msg = json.loads(body or b"{}")
        if int(msg.get("code") or 0) != 3:            # 3 = 订单状态变化
            return None
        sn = (msg.get("data") or {}).get("ordersn")
        if not sn:
            return None
        self._ensure_token()
        return self.details([sn])
