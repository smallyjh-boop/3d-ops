"""平台通知（v2.49）：Lazada 官方账号（名字打码成 L****l、会话带 official 标签）发来的卖家通知 / 活动推送。

这些会话不是买家：不算未回复 / 超时 / 需人工 / 工作台统计，不打标签、不写 AI 草稿、不自动回复、不进今日待办，
在聊天页单独的「平台通知」页签里只读显示（kind='system'）。通知内容常常是 HTML（<img> <a>），
服务器原样保存，界面里安全地显示（只认图片、链接、换行）；列表预览、AI 翻译用 plain() 去掉标签后的文字。
"""
import html
import re

KIND = "system"

_TAG = re.compile(r"<\s*/?\s*(img|a|br|p|div|span|b|strong|i|em|font|u|table|tr|td|ul|li|h\d)\b[^>]*>", re.I)
_IMG = re.compile(r"<\s*img\b[^>]*>", re.I)
_ANY_TAG = re.compile(r"<[^>]{1,2000}>")
# 官方账号：L****l（中间全是 *）、Lazada / LazMall / Shopee / TikTok 官方、系统通知
_MASKED = re.compile(r"^\s*[A-Za-z]\*{3,}[A-Za-z]?\s*$")
_OFFICIAL_NAME = re.compile(r"^\s*(lazada|lazmall|laz\s*mall|lazada\s*(seller|official|thailand|th|university|notification|team|center|centre)\b.*|"
                            r"shopee(\s*(official|thailand|th|seller|notification|team|center|centre|ประเทศไทย))?|"
                            r"tiktok\s*(shop)?\s*(official|seller|notification|team|center|centre)?|"
                            r"seller\s*(center|centre|support|notification)|official|system|notification|"
                            r"ระบบ|แจ้งเตือน|ประกาศ|ลาซาด้า.*|ช้อปปี้.*|官方|系统|系统通知|平台通知)\s*$", re.I)
_SYS_TAGS = {"official", "system", "notification", "notice", "platform", "seller_notice", "marketing", "lazada", "officialaccount"}
# 卖家通知模板里常见的字
_NOTICE_HINTS = ("sem_seller_engagement_push", "seller_engagement", "sellercenter.lazada", "sellercenter", "lazada.co.th/seller",
                 "university.lazada", "เซลเลอร์เซ็นเตอร์", "Seller Center", "ผู้ขาย", "ร้านค้าของคุณ", "แคมเปญ", "สมัครเข้าร่วม")


def looks_html(text):
    return bool(_TAG.search(text or ""))


def plain(text, img="🖼"):
    """去掉 HTML：图片换成 🖼，<br>/<p> 换成空格，其它标签去掉，实体解码。不是 HTML 的原样返回。"""
    t = text or ""
    if not looks_html(t):
        return t
    t = _IMG.sub(f" {img} ", t)
    t = re.sub(r"<\s*(br|/p|/div|/li|/tr)\b[^>]*>", " ", t, flags=re.I)
    t = _ANY_TAG.sub("", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip() or img


def _tags_of(v):
    if not v:
        return set()
    if isinstance(v, (list, tuple, set)):
        items = v
    else:
        items = re.split(r"[,;|\s]+", str(v))
    out = set()
    for x in items:
        if isinstance(x, dict):
            x = x.get("name") or x.get("tag") or x.get("value") or ""
        out.add(str(x).strip().lower())
    return {x for x in out if x}


def official_name(name):
    n = (name or "").strip()
    return bool(n) and bool(_MASKED.match(n) or _OFFICIAL_NAME.match(n))


def notice_text(text):
    """这条消息像平台通知：HTML 图片 / 链接，或者通知模板里的字。"""
    t = text or ""
    if "sem_seller_engagement_push" in t or "seller_engagement" in t:
        return True
    if looks_html(t) and (_IMG.search(t) or re.search(r"<\s*a\b", t, re.I)):
        return True
    return looks_html(t) and any(h.lower() in t.lower() for h in _NOTICE_HINTS)


def session_is_system(s):
    """Lazada 会话列表的一行（/im/session/list）是不是平台 / 官方账号。"""
    s = s or {}
    tags = set()
    for k in ("tags", "tag", "session_tags", "label", "labels", "session_type", "account_type", "buyer_type"):
        tags |= _tags_of(s.get(k))
    if tags & _SYS_TAGS:
        return True
    # 买家的账号类型是 1；其它（官方 / 系统）不是买家
    for k in ("buyer_account_type", "other_account_type", "buyer_type"):
        v = str(s.get(k) or "").strip()
        if v and v not in ("1", "buyer"):
            return True
    if official_name(s.get("title") or s.get("buyer_name") or ""):
        return True
    return notice_text(s.get("summary") or "")


def msg_is_system(m):
    """接口的一条消息：发送方不是买家也不是卖家（系统消息）。"""
    fat = str((m or {}).get("from_account_type") or "").strip()
    return bool(fat) and fat not in ("1", "2")


def conv_is_system(conv, msgs):
    """存下来的会话：买家名是官方账号，或者「买家」发的每条都是通知格式。"""
    if (conv or {}).get("kind") == KIND:
        return True
    if official_name((conv or {}).get("buyer") or ""):
        return True
    bm = [m for m in msgs or [] if m.get("role") == "buyer" and (m.get("kind") or "text") == "text"]
    return bool(bm) and all(notice_text(m.get("text")) for m in bm)


def mark(cid):
    """把会话标成平台通知，清掉以前错打的需人工 / 标签 / 草稿 / 线索、排着的 AI 任务、答不上来的问题。"""
    from core import db
    c = db.conn()
    c.execute("UPDATE cs_conv SET kind=?, needs_human=0, human_reason='', tags='', draft=NULL, draft_zh=NULL, analysis=NULL, "
              "intent='', summary='', tier=NULL, lead_stage='', next_follow_at=NULL, follow_note=NULL, needs=NULL, "
              "mode='', taken_by=NULL, taken_at=NULL, assigned=NULL WHERE id=?", (KIND, cid))
    c.execute("DELETE FROM cs_jobs WHERE conv_id=? AND status='todo'", (cid,))
    c.execute("DELETE FROM cs_unanswered WHERE conv_id=? AND status='open'", (cid,))
    c.commit()


def reclassify_all():
    """启动时：把以前收进来的官方通知会话重新认出来，清掉错的标记。返回改了几个。"""
    from core import db
    from . import data
    c = db.conn()
    n = 0
    for r in c.execute("SELECT id, buyer, kind, needs_human, tags, draft FROM cs_conv").fetchall():
        conv = dict(r)
        if conv.get("kind") == KIND:
            if conv.get("needs_human") or conv.get("tags") or conv.get("draft"):
                mark(conv["id"])
                n += 1
            continue
        msgs = data.messages(conv["id"], 40)
        if conv_is_system(conv, msgs):
            mark(conv["id"])
            n += 1
    return n
