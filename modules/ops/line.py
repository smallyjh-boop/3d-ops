"""LINE 推送（从运营分析系统 kernel/line.py 搬过来）。LINE Notify 已停止服务，用 LINE 官方账号 Messaging API 推送：
在 LINE Developers 建一个 Messaging API 频道，拿 Channel access token；接收人 = 自己的 User ID（U 开头，频道「Basic settings」最下面）
或者群组 ID（C 开头，把官方账号拉进群）。"""
import requests

PUSH_URL = "https://api.line.me/v2/bot/message/push"


def send(token, to, text):
    """返回 (成功?, 错误说明)。"""
    token, to = str(token or "").strip(), str(to or "").strip()
    if not token or not to:
        return False, "还没填 LINE 的 Channel access token 和接收人 ID"
    try:
        r = requests.post(PUSH_URL, timeout=15, json={"to": to, "messages": [{"type": "text", "text": str(text)[:4900]}]},
                          headers={"Authorization": f"Bearer {token}"})
    except requests.RequestException as e:
        return False, f"连不上 LINE：{e.__class__.__name__}"
    if r.status_code != 200:
        return False, f"LINE 返回 {r.status_code}：{r.text[:200]}"
    return True, ""
