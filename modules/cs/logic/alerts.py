"""客服提醒：买家消息超过 N 分钟没人回 → 推送到手机（Telegram）和邮件；v2.22 加：
  紧急（投诉、退款、AI 转人工）马上发邮件；每天一封「今天要跟进的客户」；每周一封客服周报。邮件发到老板邮箱 + 客服邮箱。

设置（客服 → 知识库与话术 → 店铺政策 → 手机提醒）：
  alert_minutes  几分钟没回算超时（0 = 关闭）
  tg_token       Telegram 机器人 token（在 Telegram 里找 @BotFather 创建）
  tg_chat        接收提醒的 chat id（先给机器人发一句话，再点「自动获取」）
同一个会话在买家发新消息之前只提醒一次。
"""
import threading
import time

import requests

from core import db
from . import data

PLAT = {"lazada": "Lazada", "shopee": "Shopee", "tiktok": "TikTok", "manual": "其他"}


def send_telegram(text, token=None, chat=None):
    s = data.settings()
    token = (token or s.get("tg_token") or "").strip()
    chat = (chat or s.get("tg_chat") or "").strip()
    if not token or not chat:
        raise ValueError("还没有填 Telegram 机器人 token 和 chat id")
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=15)
    except requests.RequestException as e:
        raise ValueError(f"连不上 Telegram：{e}")
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not j.get("ok"):
        raise ValueError(f"Telegram 返回错误：{j.get('description') or r.status_code}")
    return True


def find_chat_id(token):
    """给机器人发过消息后，从 getUpdates 里找到 chat id。"""
    token = (token or "").strip()
    if not token:
        raise ValueError("先填机器人 token")
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15)
        j = r.json()
    except (requests.RequestException, ValueError) as e:
        raise ValueError(f"连不上 Telegram：{e}")
    if not j.get("ok"):
        raise ValueError(f"token 不对：{j.get('description')}")
    for u in reversed(j.get("result") or []):
        m = u.get("message") or u.get("channel_post") or {}
        ch = m.get("chat") or {}
        if ch.get("id"):
            return str(ch["id"]), ch.get("title") or ch.get("first_name") or ch.get("username") or ""
    raise ValueError("没找到：请先在 Telegram 里给你的机器人发一句话（例如 hi），再点一次")


def _tg_ready(s):
    return bool(s.get("tg_token") and s.get("tg_chat"))


def check_once(now=None):
    """每分钟跑一次。返回这次提醒了几个超时会话。"""
    from . import mailer
    s = data.settings()
    now = now or time.time()
    tg, mail = _tg_ready(s), mailer.configured(s)
    n = 0
    if tg or (mail and s.get("email_overdue") == "1"):
        items = [x for x in data.overdue() if not x["alerted_at"] or x["alerted_at"] < x["last_at"]]
        if items:
            lines = [f"⏰ {len(items)} 个买家超过 {s.get('alert_minutes')} 分钟没回复："]
            for x in items[:10]:
                lines.append(f"· [{PLAT.get(x['platform'], x['platform'] or '其他')}] {x['buyer'] or '买家'}（等了 {x['wait_min']} 分钟）：{x['text']}")
            if len(items) > 10:
                lines.append(f"…还有 {len(items) - 10} 个")
            sent = False
            if tg:
                try:
                    send_telegram("\n".join(lines)); sent = True
                except ValueError as e:
                    print("Telegram 提醒失败：", e)
            if mail and s.get("email_overdue") == "1":
                try:
                    mailer.send(f"⏰ 客服超时：{len(items)} 个买家没回复", "\n".join(lines) + "\n\n请打开 3D 运营管理系统 → 客服 处理。", s=s)
                    sent = True
                except ValueError as e:
                    print("邮件提醒失败：", e)
            if sent:
                c = db.conn()
                for x in items:
                    c.execute("UPDATE cs_conv SET alerted_at=? WHERE id=?", (now, x["id"]))
                c.commit()
                n = len(items)
    if mail:
        _digest(s, now)
        _weekly(s, now)
    return n


def _digest(s, now):
    """每天早上（周报的小时）一封：今天要跟进的客户。"""
    if s.get("email_follow") != "1":
        return
    lt = time.localtime(now)
    day = time.strftime("%Y-%m-%d", lt)
    if s.get("last_follow_digest") == day or lt.tm_hour < int(s.get("weekly_hour") or 9):
        return
    due = data.leads(due_only=True)
    data.save_settings({"last_follow_digest": day})
    if not due:
        return
    from . import mailer
    lines = [f"今天有 {len(due)} 个客户该跟进了："]
    for x in due[:30]:
        lines.append(f"· {x.get('buyer') or '买家'}（{data.LEAD_STAGES.get(x.get('lead_stage'), '')}"
                     f"{'，约 ฿' + format(x['lead_value'], ',.0f') if x.get('lead_value') else ''}）：{x.get('follow_note') or x.get('summary') or ''}")
    try:
        mailer.send(f"📋 今天要跟进的客户：{len(due)} 个", "\n".join(lines) + "\n\n打开 客服 → 跟进 处理。", s=s)
    except ValueError as e:
        print("跟进提醒邮件失败：", e)


def _weekly(s, now):
    if s.get("email_weekly") != "1":
        return
    lt = time.localtime(now)
    week = time.strftime("%G-W%V", lt)
    if s.get("last_weekly") == week:
        return
    if lt.tm_wday + 1 != int(s.get("weekly_day") or 1) or lt.tm_hour < int(s.get("weekly_hour") or 9):
        return
    data.save_settings({"last_weekly": week})
    from . import mailer, report
    r = report.weekly()
    report.save_last(r)
    try:
        mailer.send(f"📊 客服周报 {r['from']} ~ {r['to']}", report.as_text(r), s=s)
    except ValueError as e:
        print("周报邮件失败：", e)


def urgent_async(cid):
    """会话需要人工（投诉、退款、AI 不能答应的）：马上发邮件（同一个会话在买家发新消息前只发一次）。"""
    s = data.settings()
    from . import mailer
    if s.get("email_urgent") != "1" or not mailer.configured(s):
        return
    c = data.get_conv(cid)
    if not c or (c.get("urgent_alerted_at") and c["urgent_alerted_at"] >= (c.get("last_buyer_at") or 0)):
        return
    data.update_conv(cid, urgent_alerted_at=time.time())
    a = c.get("analysis") or {}
    last = [m["text"] for m in data.messages(cid)[-6:] if m["role"] == "buyer"]
    body = (f"买家：{c.get('buyer') or '（没有名字）'}（{PLAT.get(c.get('platform'), c.get('platform') or '其他')}）\n"
            f"原因：{c.get('human_reason') or a.get('intent_zh') or ''}\n"
            f"买家要什么：{c.get('summary') or ''}\n\n买家说：\n" + "\n".join(last) +
            (f"\n\nAI 草稿（还没发）：\n{c.get('draft')}\n中文：{c.get('draft_zh') or ''}" if c.get("draft") else "") +
            f"\n\n订单：{c.get('order_no') or '没有关联'}\n打开 3D 运营管理系统 → 客服 → 需人工 处理。")

    def go():
        try:
            mailer.send(f"🚨 客服要人工处理：{c.get('buyer') or '买家'} · {a.get('intent_zh') or ''}", body, s=s)
        except ValueError as e:
            print("紧急邮件失败：", e)
    threading.Thread(target=go, daemon=True, name="cs-urgent").start()


def _loop():
    while True:
        try:
            check_once()
        except Exception as e:  # noqa: BLE001  网络问题等，下次再试
            print("客服提醒发送失败：", e)
        finally:
            db.release()
        time.sleep(60)


_started = False


def start():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="cs-alerts").start()
