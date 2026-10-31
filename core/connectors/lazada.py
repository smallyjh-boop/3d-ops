"""Lazada 开放平台（Lazada Open Platform）订单拉取。

需要：在 open.lazada.com 注册开发者、创建应用（App Key / App Secret），用卖家账号授权后得到 access_token。
按官方文档编写（签名 HMAC-SHA256、/orders/get、/orders/items/get、/auth/token/refresh），
拿到正式 App Key 后需要联调确认。
"""
import datetime as dt
import hashlib
import hmac
import json
import threading
import time
import urllib.parse

import requests

from . import Connector, NotReady

API = "https://api.lazada.co.th/rest"
AUTH = "https://auth.lazada.com/rest"
IM_PUSH = threading.Event()      # v2.46：收到聊天推送时置位，客服轮询马上醒来
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
    def _call(self, path, params, base=API, token=True, method="GET", files=None):
        p = {"app_key": self.creds.get("app_key", ""), "timestamp": str(int(time.time() * 1000)), "sign_method": "sha256"}
        if token:
            p["access_token"] = self.creds.get("access_token", "")
        p.update({k: str(v) for k, v in params.items() if v is not None})
        p["sign"] = sign(self.creds.get("app_secret", ""), path, p)
        if files:                                   # 上传文件（v2.43.1 /image/upload）：文件不算签名
            resp = requests.post(base + path, data=p, files=files, timeout=60)
        elif method == "POST":
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
        packed = []
        if not pkgs:                            # v2.44.1：还没打包——和卖家中心「打包 & 打印」一样，先在 Lazada 打包
            ids = [it.get("order_item_id") for it in items if it.get("order_item_id")]
            if not ids:
                raise NotReady("Lazada 没有返回这个订单的商品，没法打包")
            packed = self.pack(oid, ids)
            pkgs = list(dict.fromkeys(x.get("package_id") for x in packed if x.get("package_id")))
            if not pkgs:
                raise RuntimeError("Lazada 打包了，但没有返回包裹号")
        req = {"doc_type": "PDF", "packages": [{"package_id": p} for p in pkgs], "print_item_list": False}
        for attempt in range(3):                # 刚打包完，面单可能要一两秒才生成
            r = self._call("/order/package/document/get", {"getDocumentReq": json.dumps(req)}, method="POST")
            res = r.get("result") or {}
            if (res.get("data") or {}).get("pdf_url") or not packed:
                break
            time.sleep(2)
        if res.get("success") is False or not (res.get("data") or {}).get("pdf_url"):
            raise RuntimeError(f"Lazada 没有返回面单：{res.get('error_msg') or res.get('error_code') or json.dumps(r)[:300]}")
        pdf = requests.get(res["data"]["pdf_url"], timeout=60)
        pdf.raise_for_status()
        tracking = next((it.get("tracking_code") for it in items if it.get("tracking_code")), "") or \
            next((x.get("tracking_number") for x in packed if x.get("tracking_number")), "")
        return {"kind": "pdf", "data": pdf.content, "tracking_no": tracking, "packed": bool(packed)}

    # ---------- 打包 / 安排发货（v2.44.1，Fulfillment API）----------
    def pack(self, order_id, item_ids):
        """在 Lazada 打包（快递由 Lazada 分配）：返回 [{order_item_id, package_id, tracking_number, shipment_provider}]。"""
        self._ensure_token()
        req = {"pack_order_list": [{"order_id": str(order_id), "order_item_list": [str(i) for i in item_ids]}],
               "delivery_type": "dropship", "shipping_allocate_type": "TFS"}
        res = (self._call("/order/fulfill/pack", {"packReq": json.dumps(req)}, method="POST").get("result") or {})
        items = [it for o in ((res.get("data") or {}).get("pack_order_list") or []) for it in (o.get("order_item_list") or [])]
        bad = [it for it in items if str(it.get("item_err_code") or "0") != "0"]
        if bad or (str(res.get("success")).lower() == "false") or not items:
            msg = (bad[0].get("msg") if bad else "") or res.get("error_msg") or res.get("error_code") or json.dumps(res)[:200]
            raise RuntimeError(f"Lazada 打包失败：{msg}")
        return items

    def rts(self, package_ids):
        """安排发货（Ready to Ship）。"""
        self._ensure_token()
        req = {"packages": [{"package_id": p} for p in package_ids]}
        res = (self._call("/order/package/rts", {"readyToShipReq": json.dumps(req)}, method="POST").get("result") or {})
        if str(res.get("success")).lower() == "false":
            raise RuntimeError(f"Lazada 安排发货失败：{res.get('error_msg') or res.get('error_code')}")
        return res

    def packages_of(self, order_id):
        """订单在 Lazada 的包裹号（打包后才有）。"""
        self._ensure_token()
        d = self._call("/orders/items/get", {"order_ids": json.dumps([int(order_id)])}).get("data") or []
        items = next((r.get("order_items") or [] for r in d if str(r.get("order_id")) == str(order_id)), [])
        return list(dict.fromkeys(it.get("package_id") for it in items if it.get("package_id")))

    # ---------- 推送（Lazada Push Mechanism）----------
    def handle_webhook(self, headers, body, url=""):
        secret = self.creds.get("app_secret", "")
        if secret:
            expect = hmac.new(secret.encode(), (self.creds.get("app_key", "") + body.decode("utf-8", "replace")).encode(),
                              hashlib.sha256).hexdigest()
            if headers.get("Authorization", "").lower() != expect:
                raise PermissionError("签名不对")
        msg = json.loads(body or b"{}")
        if (msg.get("data") or {}).get("session_id"):   # v2.46：聊天推送 → 客服马上拉一次新消息（不用等下一轮）
            IM_PUSH.set()
            return None
        if str(msg.get("message_type")) != "0":      # 0 = 订单状态变化
            return None
        oid = (msg.get("data") or {}).get("trade_order_id")
        if not oid:
            return None
        self._ensure_token()
        o = (self._call("/order/get", {"order_id": oid}).get("data") or {})
        return self._with_items([o]) if o else None

    # ---------- 商品（v2.41.2：ERP 产品推到 Lazada，modules/listing/lazada_push.py）----------
    def category_tree(self):
        """类目树（泰文）：[{category_id, name, leaf, var, children:[…]}]"""
        self._ensure_token()
        return self._call("/category/tree/get", {"language_code": "th_TH"}).get("data") or []

    def category_suggestion(self, product_name, image_url):
        """Lazada 按商品名 + 图片推荐类目（GetCategorySuggestion）：[{categoryId, categoryPath, categoryName}]"""
        self._ensure_token()
        d = self._call("/product/category/suggestion/get", {"product_name": product_name[:255], "image_url": image_url}).get("data") or {}
        return d.get("categorySuggestions") or []

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

    def upload_image(self, data, name="image.jpg"):
        """本地图片（不超过 1MB 的 jpg / png）→ Lazada 图片空间的网址。"""
        self._ensure_token()
        img = (self._call("/image/upload", {}, method="POST", files={"image": (name, data)}).get("data") or {}).get("image") or {}
        if not img.get("url"):
            raise RuntimeError(f"Lazada 没有返回图片网址：{name}")
        return img["url"]

    def _product(self, path, product):
        self._ensure_token()
        # Lazada 的例子里值都是字符串；allow_nan=False：价格之类算出 nan 时在这里就报清楚，不发出去。
        # 泰文 / 中文用 \u 转义（纯 ASCII 的标准 JSON），不受传输编码影响（v2.43.1：第一次推送报「not in JSON format」）
        payload = json.dumps({"Request": {"Product": product}}, ensure_ascii=True, allow_nan=False)
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

    # ---------- 在线商品（v2.44：modules/listing/online.py）----------
    def list_products(self, offset=0, limit=50, status="all"):
        """店铺商品（GetProducts）：{total_products, products:[…]}，一次最多 50 个。"""
        self._ensure_token()
        return self._call("/products/get", {"filter": status, "offset": offset, "limit": limit}).get("data") or {}

    def deactivate(self, item_id):
        """下架整个商品（DeactivateProduct）。"""
        self._ensure_token()
        body = f"<Request><Product><ItemId>{int(item_id)}</ItemId></Product></Request>"
        return self._call("/product/deactivate", {"apiRequestBody": body}, method="POST")

    # ---------- 聊天（v2.46 Instant Messaging API：modules/cs/logic/channels/lazada_im.py）----------
    # 要在开放平台给应用开通「Instant Messaging」权限；没开通时接口会报错，客服页会显示原因。
    def _im(self, path, params, method="GET"):
        self._ensure_token()
        d = self._call(path, params, method=method)
        if str(d.get("success", "true")).lower() == "false" or str(d.get("err_code") or "0") not in ("0", ""):
            raise RuntimeError(f"Lazada {path} 出错：{d.get('err_code')} {d.get('err_message') or d.get('message') or ''}")
        return d.get("data") or {k: v for k, v in d.items() if k not in ("code", "request_id")}

    def im_sessions(self, start_time=None, page_size=20, last_session_id=None):
        """会话列表（GetSessionList，按最后消息时间从新到旧）：
        {session_list:[{session_id, buyer_id, title, head_url, summary, unread_count, last_message_id, last_message_time}],
         has_more, next_start_time, last_session_id}"""
        return self._im("/im/session/list", {"start_time": str(int(start_time or time.time() * 1000)), "page_size": str(page_size),
                                              "last_session_id": last_session_id})

    def im_session(self, session_id):
        return self._im("/im/session/get", {"session_id": session_id})

    def im_messages(self, session_id, start_time=None, page_size=20, last_message_id=None):
        """会话里的消息（GetMessages，从新到旧）：{message_list:[{message_id, template_id, content(JSON 字符串),
        from_account_type(1 买家 2 卖家), from_account_id, send_time, auto_reply, process_msg}], has_more, next_start_time, last_message_id}"""
        return self._im("/im/message/list", {"session_id": session_id, "start_time": str(int(start_time or time.time() * 1000)),
                                              "page_size": str(page_size), "last_message_id": last_message_id})

    def im_send(self, session_id, template_id=1, **kw):
        """发消息（SendMessage）：template_id 1 文字(txt) / 3 图片(img_url,width,height) / 10006 商品(item_id) / 10007 订单(order_id)。
        返回 {message_id}"""
        p = {"session_id": session_id, "template_id": str(template_id)}
        p.update({k: str(v) for k, v in kw.items() if v not in (None, "")})
        return self._im("/im/message/send", p, method="POST")

    def im_read(self, session_id, last_read_message_id):
        """标记已读（ReadSession）。"""
        return self._im("/im/session/read", {"session_id": session_id, "last_read_message_id": last_read_message_id}, method="POST")

    def im_open(self, order_id):
        """按订单号打开（没有就新建）和买家的会话（OpenSession）：返回 session_id。"""
        d = self._im("/im/session/open", {"order_id": order_id}, method="POST")
        return d.get("session_id") or ""
    # ---------- 运营数据（v2.46：modules/ops/lazada.py 拉财务流水、评价、退货退款、店铺表现）----------
    # 这几个接口要在 open.lazada.com 的 App Console 里给应用开对应的权限（Finance / Product Review / Return and Refund / Seller），
    # 没开会报 permission 之类的错：运营分析页面上会显示，并提示去申请。
    def finance_transactions(self, start_date, end_date, offset=0, limit=500, trans_type=None, order_id=None):
        """QueryTransactionDetails：start_date / end_date 是 YYYY-MM-DD（相差不超过 180 天），一次最多 500 行。返回 [行]。"""
        self._ensure_token()
        p = {"start_time": start_date, "end_time": end_date, "offset": offset, "limit": limit}
        if trans_type not in (None, ""):
            p["trans_type"] = trans_type
        if order_id:
            p["trade_order_id"] = order_id
        d = self._call("/finance/transaction/details/get", p).get("data")
        return d if isinstance(d, list) else ((d or {}).get("list") or (d or {}).get("data") or [])

    @staticmethod
    def _ok(r, path):
        """评价、退货接口：外层 code 是 0，里面还有 success / error_code。"""
        if str(r.get("success", "true")).lower() == "false":
            raise RuntimeError(f"Lazada {path} 出错：{r.get('error_code') or ''} {r.get('error_msg') or ''}".strip())
        return r

    def review_ids(self, item_id, start_ms, end_ms, page=1):
        """GetHistoryReviewIdList：一个商品在一段时间（不超过 7 天、最近 90 天内）的评价编号。
        返回 {current, total, page_size, id_list:[…]}。"""
        self._ensure_token()
        path = "/review/seller/history/list"
        r = self._ok(self._call(path, {"item_id": item_id, "start_time": int(start_ms), "end_time": int(end_ms), "current": int(page)}), path)
        return r.get("data") or {}

    def reviews(self, ids):
        """GetReviewListByIdList（v2）：一次最多 10 个评价编号 → [评价]（rating 在 ratings 里，卖家回复在 seller_reply）。"""
        self._ensure_token()
        path = "/review/seller/list/v2"
        r = self._ok(self._call(path, {"id_list": json.dumps([int(x) for x in ids][:10])}), path)
        return (r.get("data") or {}).get("review_list") or []

    def review_reply(self, review_id, content):
        """回复评价（SubmitSellerReply）。"""
        self._ensure_token()
        path = "/review/seller/reply/add"
        r = self._ok(self._call(path, {"id": int(review_id), "content": str(content)[:500]}), path)     # 文档写的是 GET
        if str(r.get("data", "true")).lower() == "false":
            raise RuntimeError("Lazada 没有接受这条回复")
        return r

    def reverse_orders(self, page_no=1, page_size=50, start_ms=None, end_ms=None):
        """GetReverseOrdersForSeller：退货 / 退款 / 取消申请（按页）。start_ms / end_ms = 退货行「最后修改时间」的范围（毫秒），
        这样状态变了的也能拉到。返回 {total, items:[{reverse_order_id, trade_order_id, request_type, reverse_order_lines:[…]}]}。"""
        self._ensure_token()
        path = "/reverse/getreverseordersforseller"
        p = {"page_no": int(page_no), "page_size": int(page_size)}
        if start_ms:
            p["ReverseOrderLineModifiedTimeRangeStart"] = int(start_ms)
        if end_ms:
            p["ReverseOrderLineModifiedTimeRangeEnd"] = int(end_ms)
        r = self._ok(self._call(path, p), path)
        res = r.get("result") or r.get("data") or {}
        if isinstance(res, dict) and isinstance(res.get("data"), dict):      # 有的版本多包一层
            res = res["data"]
        return res if isinstance(res, dict) else {"items": res or []}

    def seller_performance(self, language="en-US"):
        """店铺表现（GetSellerPerformance）：{indicators:[{name, type, score, formatted_score, formatted_target, target_respected, tip}]}。"""
        self._ensure_token()
        path = "/seller/performance/get"
        r = self._ok(self._call(path, {"language": language}), path)
        return r.get("data") or r.get("result") or {}
