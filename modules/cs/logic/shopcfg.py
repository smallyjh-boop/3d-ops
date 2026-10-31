"""每个店铺的客服设置（v2.46）：AI 模式、接口收消息开不开、夜间模式。存在 cs_settings 的 shop_cfg（JSON，按店铺名）。

AI 模式：
  off    AI 不管，只人工回
  draft  AI 写好草稿，人点发送（默认，最稳）
  auto   AI 能答的（分级里设成「自动发」、把握够、没触发转人工的）直接发；其它照样出草稿 / 转人工
会话被人工接管（cs_conv.mode='human'）时，不管店铺是什么模式，AI 都只出草稿不自动发。
"""
import json
import time

from . import data

MODES = {"off": ("只人工", "คนตอบเอง"), "draft": ("AI 出草稿", "AI ร่างให้"), "auto": ("AI 自动回复", "AI ตอบอัตโนมัติ")}
DEFAULT = {"mode": "draft", "im": True}


def _all():
    try:
        d = json.loads(data.settings().get("shop_cfg") or "{}")
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


def get(shop):
    out = dict(DEFAULT)
    out.update(_all().get(shop or "", {}))
    if out.get("mode") not in MODES:
        out["mode"] = "draft"
    return out


def save(shop, **kw):
    d = _all()
    cur = d.get(shop or "", {})
    if "mode" in kw and kw["mode"] in MODES:
        cur["mode"] = kw["mode"]
    if "im" in kw:
        cur["im"] = bool(kw["im"])
    d[shop or ""] = cur
    data.save_settings({"shop_cfg": json.dumps(d, ensure_ascii=False)})
    return get(shop)


def mode_of(conv):
    """这个会话现在 AI 怎么处理：off / draft / auto（被人接管 = draft；夜间按夜间模式）。"""
    if (conv.get("mode") or "") == "human":
        return "draft"
    m = get(conv.get("shop") or "")["mode"]
    if m == "off":
        return "off"
    if m == "draft" and is_night() and data.settings().get("night_mode") == "auto":
        return "auto"
    return m


def _hm(v, d):
    try:
        h, m = str(v or d).split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        h, m = d.split(":")
        return int(h) * 60 + int(m)


def is_night(now=None):
    s = data.settings()
    if (s.get("night_mode") or "off") == "off":
        return False
    t = time.localtime(now or time.time())
    cur = t.tm_hour * 60 + t.tm_min
    a, b = _hm(s.get("night_from"), "22:00"), _hm(s.get("night_to"), "08:00")
    return (a <= cur < b) if a < b else (cur >= a or cur < b)
