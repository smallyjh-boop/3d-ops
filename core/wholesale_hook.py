"""v2.37：批发站回调。批发订单状态变了（发货、取消、拒收…）马上通知批发网站，网站不用等定时查询。

批发网站用「批发站」密钥调 POST /api/v1/wholesale/hook {"url": ..., "secret": ...} 登记地址和密钥，
ERP 回调时带 X-Timestamp 和 X-Signature（HMAC-SHA256(secret, 时间戳 + "." + 内容)）。
回调只是「该去查了」的信号，网站收到后自己用接口取最新状态，所以丢一两次也没关系（网站还有定时查询兜底）。
"""
import hashlib
import hmac
import json
import threading
import time

from .config import load_config, save_config

PLATFORM = "wholesale"


def register(url, secret):
    url, secret = str(url or "").strip(), str(secret or "").strip()
    if not url.startswith(("http://", "https://")) or len(secret) < 16:
        raise ValueError("url 要以 http(s):// 开头，secret 至少 16 位")
    save_config({"wholesale_hook": {"url": url[:300], "secret": secret[:200], "at": time.time()}})


def _target():
    h = load_config().get("wholesale_hook") or {}
    return (h.get("url"), h.get("secret")) if h.get("url") and h.get("secret") else (None, None)


def _post(url, secret, body):
    import requests
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    try:
        requests.post(url, data=body, timeout=8, headers={"Content-Type": "application/json", "X-Timestamp": ts,
                                                          "X-Signature": sig})
    except Exception as e:  # noqa: BLE001  网站连不上不影响 ERP
        print("批发站回调失败：", e)


def notify(order_no, status):
    url, secret = _target()
    if not url:
        return False
    body = json.dumps({"event": "order.status", "order_no": order_no, "status": status, "time": time.time()}).encode()
    threading.Thread(target=_post, args=(url, secret, body), daemon=True).start()
    return True
