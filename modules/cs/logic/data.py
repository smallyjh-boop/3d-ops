"""客服模块自己的数据：会话、消息、知识库、学到的回复、客服设置（和 ERP 的表分开）。"""
import json
import time

from core import db
from .presets import PLAYBOOK, PRESETS

SCHEMA = """
CREATE TABLE IF NOT EXISTS cs_conv (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT DEFAULT 'manual', shop_id INTEGER, platform TEXT, ext_id TEXT,
  buyer TEXT, order_id INTEGER, order_no TEXT,
  status TEXT DEFAULT 'open', needs_human INTEGER DEFAULT 0, human_reason TEXT,
  intent TEXT, summary TEXT, lang TEXT,
  draft TEXT, draft_zh TEXT, analysis TEXT, draft_at REAL,
  unread INTEGER DEFAULT 0, assigned TEXT,
  created_at REAL, updated_at REAL, last_buyer_at REAL
);
CREATE INDEX IF NOT EXISTS cs_conv_upd ON cs_conv(updated_at);
CREATE INDEX IF NOT EXISTS cs_conv_ext ON cs_conv(platform, ext_id);
CREATE TABLE IF NOT EXISTS cs_msg (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id INTEGER, role TEXT, text TEXT, text_zh TEXT,
  source TEXT, ext_id TEXT, ai_draft TEXT, created_at REAL, username TEXT
);
CREATE INDEX IF NOT EXISTS cs_msg_conv ON cs_msg(conv_id);
CREATE TABLE IF NOT EXISTS cs_kb (
  id INTEGER PRIMARY KEY AUTOINCREMENT, q TEXT, a TEXT, a_zh TEXT, tags TEXT,
  active INTEGER DEFAULT 1, uses INTEGER DEFAULT 0, created_at REAL, updated_at REAL, username TEXT
);
CREATE TABLE IF NOT EXISTS cs_examples (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id INTEGER, question TEXT, ai_reply TEXT, final_reply TEXT,
  intent TEXT, created_at REAL, username TEXT
);
CREATE TABLE IF NOT EXISTS cs_settings (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS cs_unanswered (
  id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT, question_zh TEXT, conv_id INTEGER, count INTEGER DEFAULT 1,
  created_at REAL, last_at REAL, status TEXT DEFAULT 'open', kb_id INTEGER
);
CREATE TABLE IF NOT EXISTS cs_cursor (shop_id INTEGER PRIMARY KEY, cursor REAL, last_ok REAL, last_error TEXT);
-- v2.46：快捷回复（可带变量）、后台任务队列（以后可以拆到单独的进程 / 机器）、质检抽查
CREATE TABLE IF NOT EXISTS cs_quick (
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, text TEXT, shop TEXT DEFAULT '', cat TEXT DEFAULT '',
  uses INTEGER DEFAULT 0, sort INTEGER DEFAULT 0, created_at REAL, username TEXT
);
CREATE TABLE IF NOT EXISTS cs_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, conv_id INTEGER, payload TEXT, status TEXT DEFAULT 'todo',
  tries INTEGER DEFAULT 0, run_at REAL, created_at REAL, done_at REAL, error TEXT, worker TEXT
);
CREATE INDEX IF NOT EXISTS cs_jobs_st ON cs_jobs(status, run_at);
CREATE TABLE IF NOT EXISTS cs_qa (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id INTEGER, day TEXT, score REAL, accuracy REAL, attitude REAL, speed REAL,
  comment TEXT, agent TEXT, shop TEXT, by_ai INTEGER DEFAULT 1, created_at REAL, username TEXT
);
"""

# 店铺客服政策（AI 回答的依据）。老板在「客服 → 知识库与话术」里改。
DEFAULT_SETTINGS = {
    "shop_name": "",
    "persona": "礼貌、热情、简短。用买家的语言回复（一般是泰语）。泰语称呼买家 คุณลูกค้า，女性语气结尾用 ค่ะ/นะคะ。"
               "不要长篇大论，一般 1–3 句。可以适当用 1 个表情。",
    "ship_policy": "所有商品都是接单后 3D 打印制作，付款后 24–48 小时内发货（定制新设计、大尺寸、批发大单按确认的日期）。物流：曼谷 1–2 天，外府 2–3 天，偏远地区 3–5 天。",
    "return_policy": "收到商品有破损或少件，请在收货 3 天内拍照/视频联系客服，我们补发或退款。非质量问题不退换。",
    "custom_policy": "可以定制颜色、刻字（名字/文字）、尺寸放大缩小。定制前先和客服确认细节，下单时在备注里写清楚。"
                     "复杂定制需要加价，由客服报价。",
    "wholesale_tiers": "10:5,30:10,50:15,100:20",     # 数量:折扣%（10 个以上 95 折…）
    "wholesale_note": "批发/大单可以开发票吗？可以私下下单或在平台下单，交期按数量另算。",
    "extra": "",                                      # 其他补充（营业时间、活动等）
    "playbook": PLAYBOOK,                             # 回复规则 / 预案（AI 每次回复都遵守）
    "auto_draft": "1",                                # 平台新消息自动生成回复草稿
    "auto_send": "1",                                 # 允许扩展「全自动」模式自动发送（扩展里还要选全自动才生效）
    "auto_min_conf": "0.85",                          # AI 把握不低于这个才自动发
    "auto_intents": "product,price,stock,order_status,thanks",   # 全自动时，这些类型的问题可以自动发送
    "auto_max_per_hour": "40",                        # 每小时最多自动发送几条（防止出错时乱发）
    "model": "",                                      # 客服专用 AI 模型（空 = 和设置页一样）。要快可以用更小的模型
    "alert_minutes": "10",                            # 买家消息超过几分钟没回复算「超时」（0 = 不提醒）
    "tg_token": "",                                   # Telegram 机器人 token（手机提醒，可空）
    "tg_chat": "",                                    # 接收提醒的 Telegram chat id
    # ---- v2.46 接口聊天 / 人工接管 / 夜间 / 主动提醒 / 质检 ----
    "poll_sec": "15",                                 # 接口店铺多久拉一次新消息（秒）
    "takeover_min": "30",                             # 人工接管后多少分钟没动静自动交回 AI（0 = 不交回）
    "night_from": "22:00", "night_to": "08:00",       # 夜间时段
    "night_mode": "off",                              # 夜间：off 照常 / notice 自动回一句「明早回复」/ auto 能自动答的直接答
    "night_text": "ขอบคุณที่ทักมานะคะ ตอนนี้นอกเวลาทำการ แอดมินจะรีบตอบกลับพรุ่งนี้เช้าค่ะ 🙏",
    "notify_shipped": "1",                            # 订单发货了主动告诉买家（按店铺的 AI 模式：自动发 / 出草稿）
    "notify_delayed": "1",                            # 订单超过 48 小时还没发货，主动安抚买家
    "tpl_shipped": "คุณ{买家名} คะ คำสั่งซื้อ {订单号} จัดส่งแล้วนะคะ เลขพัสดุ {运单号} ขอบคุณที่อุดหนุนค่ะ 🙏",
    "tpl_delayed": "คุณ{买家名} คะ คำสั่งซื้อ {订单号} กำลังผลิตอยู่ค่ะ คาดว่าจะจัดส่งภายใน {预计发货日} ขออภัยที่ให้รอนะคะ 🙏",
    "qa_daily": "5",                                  # 每天让 AI 抽查几个昨天的会话打分（0 = 不抽查）
    "shop_cfg": "{}",                                 # 每个店铺的 AI 模式等（JSON，见 shopcfg.py）
    # ---- v2.22 智能客服 ----
    "tiers": "",          # 每类问题怎么处理（JSON {意图: auto 自动发 / confirm AI 写好人确认 / human 转人工}），空 = 按 auto_intents 推出来
    "forbidden": "退款、赔偿、补发、免运费、额外折扣、保证某天一定送到、保证永不损坏、平台外交易（LINE/电话/转账）",
    "forbidden_words": "คืนเงินให้,โอนเงินคืน,ชดเชย,ส่งฟรี,แถมฟรี,รับประกัน 100,ไลน์,LINE,โอนเข้าบัญชี,退款给,赔偿,包邮,保证",
    "smart": "1",          # 更灵活：可以追问、推荐相关产品 / 套装、记住这个买家以前买过什么
    "learn_mode": "suggest",   # 从人工回复里学新知识：suggest 先放「待确认」/ auto 直接加进知识库 / off 不学
    "follow_hours": "24",  # 新线索多久后提醒跟进（小时）；报价后按 2 倍
    "smtp_host": "", "smtp_port": "465", "smtp_user": "", "smtp_pass": "", "smtp_from": "", "smtp_tls": "ssl",
    "owner_email": "", "cs_email": "",
    "email_urgent": "1", "email_overdue": "1", "email_follow": "1", "email_weekly": "1",
    "weekly_day": "1", "weekly_hour": "9",        # 周报：星期几（1 = 周一）几点发
    "last_weekly": "", "last_follow_digest": "",
}
SECRET = ("smtp_pass", "tg_token")
TIER_NAMES = {"auto": "自动发送", "confirm": "AI 写好，人确认后发", "human": "转人工"}


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    from . import crm
    crm.init()                    # v2.24：客户档案、登记中心
    cols = {r[1] for r in c.execute("PRAGMA table_info(cs_conv)")}
    if "alerted_at" not in cols:
        c.execute("ALTER TABLE cs_conv ADD COLUMN alerted_at REAL")
    for col, typ in (("tags", "TEXT"), ("needs", "TEXT"), ("lead_stage", "TEXT DEFAULT ''"), ("lead_value", "REAL"),
                     ("next_follow_at", "REAL"), ("follow_note", "TEXT"), ("tier", "TEXT"), ("urgent_alerted_at", "REAL"),
                     ("lead_at", "REAL"), ("shop", "TEXT"),
                     # v2.46：人工接管 / 分配、平台会话的最后消息、头像、夜间提示、主动提醒
                     ("mode", "TEXT DEFAULT ''"), ("taken_by", "TEXT"), ("taken_at", "REAL"), ("ext_last_id", "TEXT"),
                     ("avatar", "TEXT"), ("night_noticed_at", "REAL"), ("notified", "TEXT")):
        if col not in cols:
            c.execute(f"ALTER TABLE cs_conv ADD COLUMN {col} {typ}")
    mcols = {r[1] for r in c.execute("PRAGMA table_info(cs_msg)")}
    for col, typ in (("kind", "TEXT DEFAULT 'text'"), ("extra", "TEXT"), ("status", "TEXT DEFAULT ''"), ("error", "TEXT")):
        if col not in mcols:
            c.execute(f"ALTER TABLE cs_msg ADD COLUMN {col} {typ}")
    kcols = {r[1] for r in c.execute("PRAGMA table_info(cs_kb)")}
    for col, typ in (("source", "TEXT DEFAULT 'manual'"), ("status", "TEXT DEFAULT 'active'"), ("conv_id", "INTEGER"), ("note", "TEXT"),
                     ("shop", "TEXT DEFAULT ''")):
        if col not in kcols:
            c.execute(f"ALTER TABLE cs_kb ADD COLUMN {col} {typ}")
    c.commit()
    if not c.execute("SELECT COUNT(*) FROM cs_kb").fetchone()[0]:
        seed_presets()
    else:
        update_presets()          # 没改过的旧版标准话术自动换成新版
    _migrate_settings()


# 以前版本的默认店铺政策（没改过的自动换成新的）
OLD_SETTINGS = {
    "ship_policy": ["所有商品都是接单后 3D 打印制作，一般付款后 2–3 天内发货，大单/定制按实际制作时间。"],
}


def _migrate_settings():
    c = db.conn()
    for k, olds in OLD_SETTINGS.items():
        r = c.execute("SELECT v FROM cs_settings WHERE k=?", (k,)).fetchone()
        if r and (r["v"] or "").strip() in olds:
            c.execute("UPDATE cs_settings SET v=? WHERE k=?", (DEFAULT_SETTINGS[k], k))
    c.commit()


def update_presets():
    """标准话术升级：还是旧版原文（没被人改过）的条目换成新版。返回更新了几条。"""
    c = db.conn()
    n = 0
    for p in PRESETS:
        olds = p.get("old") or []
        if not olds:
            continue
        key = p["q"].split("|")[0].strip()
        for r in c.execute("SELECT id, q, a FROM cs_kb").fetchall():
            if (r["q"] or "").split("|")[0].strip() == key and (r["a"] or "").strip() in olds:
                c.execute("UPDATE cs_kb SET a=?, a_zh=?, updated_at=? WHERE id=?", (p["a"], p["a_zh"], time.time(), r["id"]))
                n += 1
    c.commit()
    return n


def seed_presets(user="system"):
    """把标准话术加进常见问答（已经有同样问题的不重复加，不覆盖改过的；没改过的旧版本换成新版）。返回加了 + 更新了几条。"""
    n = update_presets()
    c = db.conn()
    have = {(r["q"] or "").split("|")[0].strip() for r in c.execute("SELECT q FROM cs_kb")}
    now = time.time()
    for p in PRESETS:
        key = p["q"].split("|")[0].strip()
        if key in have:
            continue
        c.execute("INSERT INTO cs_kb(q, a, a_zh, tags, active, created_at, updated_at, username) VALUES(?,?,?,?,1,?,?,?)",
                  (p["q"], p["a"], p["a_zh"], p["tags"], now, now, user))
        n += 1
    c.commit()
    return n


def presets_missing():
    have = {(r["q"] or "").split("|")[0].strip() for r in db.conn().execute("SELECT q FROM cs_kb")}
    return sum(1 for p in PRESETS if p["q"].split("|")[0].strip() not in have)


def settings():
    out = dict(DEFAULT_SETTINGS)
    for r in db.conn().execute("SELECT k, v FROM cs_settings"):
        out[r["k"]] = r["v"]
    return out


def public_settings():
    """给网页看的设置：密码不回传（只告诉有没有填）。"""
    s = settings()
    for k in SECRET:
        s[k + "_set"] = bool(s.get(k))
        s[k] = ""
    return s


def save_settings(d):
    c = db.conn()
    for k in DEFAULT_SETTINGS:
        if k in SECRET and not d.get(k):
            continue                    # 密码留空 = 不改
        if k in d and d[k] is not None:
            c.execute("INSERT OR REPLACE INTO cs_settings(k, v) VALUES(?,?)", (k, str(d[k])[:4000]))
    c.commit()
    return settings()


def wholesale_tiers(s=None):
    """"10:5,30:10" → [(10, 5.0), (30, 10.0)]（按数量从小到大）"""
    s = (s if s is not None else settings().get("wholesale_tiers")) or ""
    out = []
    for part in str(s).replace("，", ",").split(","):
        if ":" in part:
            a, b = part.split(":", 1)
            try:
                out.append((int(float(a)), float(b)))
            except ValueError:
                continue
    return sorted(out)


# ---------------- 会话 / 消息 ----------------
def _conv(r):
    if not r:
        return None
    d = dict(r)
    for k in ("analysis", "needs"):
        try:
            d[k] = json.loads(d[k]) if d.get(k) else None
        except ValueError:
            d[k] = None
    d["tag_list"] = [t for t in (d.get("tags") or "").split(",") if t]
    return d


def get_conv(cid):
    return _conv(db.conn().execute("SELECT * FROM cs_conv WHERE id=?", (cid,)).fetchone())


def find_conv(platform, ext_id):
    return _conv(db.conn().execute("SELECT * FROM cs_conv WHERE platform=? AND ext_id=?", (platform, ext_id)).fetchone())


def create_conv(buyer="", platform="", channel="manual", shop_id=None, ext_id=None, order_id=None, order_no=None):
    now = time.time()
    c = db.conn()
    cid = c.execute("""INSERT INTO cs_conv(channel, shop_id, platform, ext_id, buyer, order_id, order_no, status,
                       created_at, updated_at) VALUES(?,?,?,?,?,?,?,'open',?,?)""",
                    (channel, shop_id, platform or "", ext_id, buyer or "", order_id, order_no, now, now)).lastrowid
    c.commit()
    return get_conv(cid)


def update_conv(cid, **kw):
    allowed = ("buyer", "platform", "order_id", "order_no", "status", "needs_human", "human_reason", "intent", "summary",
               "lang", "draft", "draft_zh", "analysis", "draft_at", "unread", "assigned", "last_buyer_at",
               "tags", "needs", "lead_stage", "lead_value", "next_follow_at", "follow_note", "tier", "urgent_alerted_at", "lead_at", "shop",
               "mode", "taken_by", "taken_at", "ext_last_id", "avatar", "night_noticed_at", "notified", "shop_id", "channel")
    sets = {k: v for k, v in kw.items() if k in allowed}
    for k in ("analysis", "needs"):
        if k in sets and not isinstance(sets[k], (str, type(None))):
            sets[k] = json.dumps(sets[k], ensure_ascii=False)
    if not sets:
        return get_conv(cid)
    sets["updated_at"] = time.time()
    c = db.conn()
    c.execute(f"UPDATE cs_conv SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), cid))
    c.commit()
    return get_conv(cid)


def delete_conv(cid):
    c = db.conn()
    c.execute("DELETE FROM cs_msg WHERE conv_id=?", (cid,))
    c.execute("DELETE FROM cs_conv WHERE id=?", (cid,))
    c.commit()


def list_convs(status="", q="", limit=200, shop="", agent="", shops=None, mine=""):
    conds, args = [], []
    if mine:                                   # v2.46：分给我的 / 我接管的
        conds.append("(assigned=? OR taken_by=?) AND status!='closed'"); args += [mine, mine]
    if shop:
        conds.append("COALESCE(shop,'')=?"); args.append(shop)
    if shops is not None:                      # v2.24：员工只看自己负责的店铺
        conds.append("COALESCE(shop,'') IN (%s)" % ",".join("?" * len(shops)) if shops else "0")
        args += list(shops)
    if agent:
        conds.append("id IN (SELECT conv_id FROM cs_msg WHERE role='seller' AND (username=? OR username=?))"); args += [agent, "api:" + agent]
    if status == "human":
        conds.append("needs_human=1 AND status!='closed'")
    elif status == "leads":
        conds.append("COALESCE(lead_stage,'') IN ('new','follow','quoted')")
    elif status == "follow":
        conds.append("COALESCE(lead_stage,'') IN ('new','follow','quoted') AND next_follow_at IS NOT NULL AND next_follow_at<=?")
        args.append(time.time())
    elif status == "active":
        conds.append("status!='closed'")
    elif status == "unreplied":                # v2.46：买家最后说话、还没回
        conds.append("status='open'")
    elif status == "taken":
        conds.append("mode='human' AND status!='closed'")
    elif status:
        conds.append("status=?"); args.append(status)
    if q:
        conds.append("(buyer LIKE ? OR order_no LIKE ? OR summary LIKE ? OR id IN (SELECT conv_id FROM cs_msg WHERE text LIKE ?))")
        args += [f"%{q}%"] * 4
    sql = "SELECT * FROM cs_conv" + (" WHERE " + " AND ".join(conds) if conds else "") + " ORDER BY updated_at DESC LIMIT ?"
    rows = [_conv(r) for r in db.conn().execute(sql, (*args, int(limit)))]
    c = db.conn()
    for d in rows:
        m = c.execute("SELECT role, text, created_at FROM cs_msg WHERE conv_id=? AND role IN ('buyer','seller') "
                      "ORDER BY id DESC LIMIT 1", (d["id"],)).fetchone()
        d["last"] = dict(m) if m else None
        d["wait_min"] = int((time.time() - m["created_at"]) / 60) if m and m["role"] == "buyer" and d["status"] != "closed" else None
        d.pop("analysis", None)
        d.pop("needs", None)
    return rows


def add_msg(cid, role, text, source="paste", user="", text_zh=None, ext_id=None, ai_draft=None, ts=None, kind="text", extra=None,
            status=""):
    """kind：text 文字 / image 图片 / item 商品卡片 / order 订单卡片 / sys 系统；extra 是卡片 / 图片的资料（dict）。"""
    text = (text or "").strip()
    if not text and kind == "text":
        return None
    c = db.conn()
    if ext_id and c.execute("SELECT 1 FROM cs_msg WHERE conv_id=? AND ext_id=?", (cid, ext_id)).fetchone():
        return None
    now = ts or time.time()
    mid = c.execute("INSERT INTO cs_msg(conv_id, role, text, text_zh, source, ext_id, ai_draft, created_at, username, kind, extra, status) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (cid, role, text, text_zh, source, ext_id, ai_draft, now, user, kind or "text",
                                                        json.dumps(extra, ensure_ascii=False) if extra else None, status or "")).lastrowid
    up = {"updated_at": time.time()}
    if role == "buyer":
        up.update(last_buyer_at=now, status="open")
        c.execute("UPDATE cs_conv SET unread=COALESCE(unread,0)+1 WHERE id=?", (cid,))
    elif role == "seller":
        up.update(status="waiting", unread=0, draft=None, draft_zh=None)
    c.execute(f"UPDATE cs_conv SET {', '.join(k + '=?' for k in up)} WHERE id=?", (*up.values(), cid))
    c.commit()
    return mid


def set_msg_zh(mid, zh):
    c = db.conn()
    c.execute("UPDATE cs_msg SET text_zh=? WHERE id=?", (zh, mid))
    c.commit()


def _msg(r):
    d = dict(r)
    try:
        d["extra"] = json.loads(d["extra"]) if d.get("extra") else None
    except ValueError:
        d["extra"] = None
    return d


def messages(cid, limit=200):
    return [_msg(r) for r in db.conn().execute(
        "SELECT * FROM (SELECT * FROM cs_msg WHERE conv_id=? ORDER BY id DESC LIMIT ?) ORDER BY id", (cid, int(limit)))]


def claim_sent(cid, text, ext_id):
    """平台拉回来的我方消息，是不是 ERP 刚发的那条（还没有平台编号）：是就补上编号，返回 True。"""
    c = db.conn()
    if not ext_id or c.execute("SELECT 1 FROM cs_msg WHERE conv_id=? AND ext_id=?", (cid, ext_id)).fetchone():
        return bool(ext_id)
    r = c.execute("SELECT id FROM cs_msg WHERE conv_id=? AND role='seller' AND COALESCE(ext_id,'')='' AND text=? "
                  "AND created_at>? ORDER BY id DESC LIMIT 1", (cid, (text or "").strip(), time.time() - 3 * 86400)).fetchone()
    if not r:
        return False
    c.execute("UPDATE cs_msg SET ext_id=? WHERE id=?", (ext_id, r["id"]))
    c.commit()
    return True


def set_msg(mid, **kw):
    sets = {k: v for k, v in kw.items() if k in ("ext_id", "status", "error", "text_zh")}
    if sets:
        c = db.conn()
        c.execute(f"UPDATE cs_msg SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), mid))
        c.commit()


def delete_msg(mid):
    c = db.conn()
    c.execute("DELETE FROM cs_msg WHERE id=?", (mid,))
    c.commit()


# ---------------- 知识库 / 学到的回复 ----------------
def kb_list(active_only=False):
    sql = "SELECT * FROM cs_kb" + (" WHERE active=1" if active_only else "") + " ORDER BY uses DESC, id DESC"
    return [dict(r) for r in db.conn().execute(sql)]


def kb_save(d, user=""):
    c = db.conn()
    now = time.time()
    q, a = (d.get("q") or "").strip(), (d.get("a") or "").strip()
    if not q or not a:
        raise ValueError("问题和回答都要填")
    vals = (q[:1000], a[:3000], (d.get("a_zh") or "")[:3000], (d.get("tags") or "")[:200], 1 if d.get("active", True) else 0,
            (d.get("shop") or "")[:100])            # v2.46：shop 空 = 所有店铺通用，填了 = 只给这个店铺用
    if d.get("id"):
        c.execute("UPDATE cs_kb SET q=?, a=?, a_zh=?, tags=?, active=?, shop=?, updated_at=?, username=? WHERE id=?",
                  (*vals, now, user, int(d["id"])))
        kid = int(d["id"])
    else:
        kid = c.execute("INSERT INTO cs_kb(q, a, a_zh, tags, active, shop, created_at, updated_at, username) VALUES(?,?,?,?,?,?,?,?,?)",
                        (*vals, now, now, user)).lastrowid
    c.commit()
    return dict(c.execute("SELECT * FROM cs_kb WHERE id=?", (kid,)).fetchone())


def kb_delete(kid):
    c = db.conn()
    c.execute("DELETE FROM cs_kb WHERE id=?", (kid,))
    c.commit()


def kb_used(ids):
    if not ids:
        return
    c = db.conn()
    c.executemany("UPDATE cs_kb SET uses=COALESCE(uses,0)+1 WHERE id=?", [(i,) for i in ids])
    c.commit()


def add_example(cid, question, ai_reply, final_reply, intent="", user=""):
    c = db.conn()
    c.execute("INSERT INTO cs_examples(conv_id, question, ai_reply, final_reply, intent, created_at, username) "
              "VALUES(?,?,?,?,?,?,?)", (cid, question[:2000], (ai_reply or "")[:3000], final_reply[:3000], intent, time.time(), user))
    c.execute("DELETE FROM cs_examples WHERE id < (SELECT MAX(id) - 1000 FROM cs_examples)")
    c.commit()


def examples(limit=300):
    return [dict(r) for r in db.conn().execute("SELECT * FROM cs_examples ORDER BY id DESC LIMIT ?", (int(limit),))]


def delete_example(eid):
    c = db.conn()
    c.execute("DELETE FROM cs_examples WHERE id=?", (eid,))
    c.commit()


def cursor_get(shop_id):
    r = db.conn().execute("SELECT * FROM cs_cursor WHERE shop_id=?", (shop_id,)).fetchone()
    return dict(r) if r else {"shop_id": shop_id, "cursor": None}


def cursor_set(shop_id, cursor=None, ok=True, error=""):
    c = db.conn()
    old = cursor_get(shop_id)
    c.execute("INSERT OR REPLACE INTO cs_cursor(shop_id, cursor, last_ok, last_error) VALUES(?,?,?,?)",
              (shop_id, cursor if cursor is not None else old.get("cursor"),
               time.time() if ok else old.get("last_ok"), "" if ok else (error or "")[:500]))
    c.commit()


def stats(shops=None):
    c = db.conn()
    cond, args = "", []
    if shops is not None:
        cond = " AND COALESCE(shop,'') IN (%s)" % ",".join("?" * len(shops)) if shops else " AND 0"
        args = list(shops)
    ov = overdue()
    if shops is not None:
        ids = {r[0] for r in c.execute("SELECT id FROM cs_conv WHERE 1" + cond, args)}
        ov = [x for x in ov if x["id"] in ids]
    return {"open": c.execute("SELECT COUNT(*) FROM cs_conv WHERE status='open'" + cond, args).fetchone()[0],
            "human": c.execute("SELECT COUNT(*) FROM cs_conv WHERE needs_human=1 AND status!='closed'" + cond, args).fetchone()[0],
            "waiting": c.execute("SELECT COUNT(*) FROM cs_conv WHERE status='waiting'" + cond, args).fetchone()[0],
            "overdue": len(ov)}


def _last_roles(c, cid):
    return c.execute("SELECT role, created_at FROM cs_msg WHERE conv_id=? AND role IN ('buyer','seller') "
                     "ORDER BY id DESC LIMIT 1", (cid,)).fetchone()


def overdue(minutes=None):
    """买家最后一条消息超过 N 分钟还没回复的会话。返回 [{id, buyer, platform, wait_min, text, alerted_at, last_at}]。"""
    if minutes is None:
        try:
            minutes = float(settings().get("alert_minutes") or 0)
        except ValueError:
            minutes = 10
    if minutes <= 0:
        return []
    c = db.conn()
    now = time.time()
    out = []
    for r in c.execute("SELECT id, buyer, platform, alerted_at FROM cs_conv WHERE status!='closed'"):
        m = c.execute("SELECT role, text, created_at FROM cs_msg WHERE conv_id=? AND role IN ('buyer','seller') "
                      "ORDER BY id DESC LIMIT 1", (r["id"],)).fetchone()
        if m and m["role"] == "buyer" and now - (m["created_at"] or now) >= minutes * 60:
            out.append({"id": r["id"], "buyer": r["buyer"] or "", "platform": r["platform"] or "",
                        "wait_min": int((now - m["created_at"]) / 60), "text": (m["text"] or "")[:80],
                        "alerted_at": r["alerted_at"], "last_at": m["created_at"]})
    out.sort(key=lambda x: -x["wait_min"])
    return out


def perf(days=7):
    """客服效果统计：回复了多少、自动发了多少、AI 草稿被改的比例、平均回复时间。"""
    c = db.conn()
    since = time.time() - days * 86400
    rows = c.execute("SELECT conv_id, role, text, source, ai_draft, created_at FROM cs_msg "
                     "WHERE created_at>=? AND role IN ('buyer','seller') ORDER BY conv_id, id", (since,)).fetchall()
    sent = auto = with_draft = edited = 0
    waits = []
    pending = {}
    for r in rows:
        if r["role"] == "buyer":
            pending.setdefault(r["conv_id"], r["created_at"])
            continue
        sent += 1
        if r["source"] == "auto":
            auto += 1
        elif r["ai_draft"]:
            with_draft += 1
            if (r["ai_draft"] or "").strip() != (r["text"] or "").strip():
                edited += 1
        t0 = pending.pop(r["conv_id"], None)
        if t0 and r["created_at"] >= t0:
            waits.append((r["created_at"] - t0) / 60)
    waits.sort()
    convs = c.execute("SELECT COUNT(DISTINCT conv_id) FROM cs_msg WHERE created_at>=? AND role='buyer'", (since,)).fetchone()[0]
    return {"days": days, "convs": convs, "sent": sent, "auto": auto, "with_draft": with_draft, "edited": edited,
            "adopt_pct": round(100 * (with_draft - edited) / with_draft) if with_draft else None,
            "avg_reply_min": round(sum(waits) / len(waits), 1) if waits else None,
            "median_reply_min": round(waits[len(waits) // 2], 1) if waits else None,
            "over_alert": sum(1 for w in waits if w > float(settings().get("alert_minutes") or 10))}


def auto_sent_last_hour():
    return db.conn().execute("SELECT COUNT(*) FROM cs_msg WHERE source='auto' AND created_at>?",
                             (time.time() - 3600,)).fetchone()[0]


# ---------------- v2.22：分级处理 ----------------
DEFAULT_TIERS = {"product": "auto", "price": "auto", "stock": "auto", "order_status": "auto", "thanks": "auto",
                 "custom": "confirm", "wholesale": "confirm", "other": "confirm",
                 "complaint": "human", "refund": "human", "change_order": "human"}


def tiers(s=None):
    s = s or settings()
    try:
        t = json.loads(s.get("tiers") or "{}")
    except ValueError:
        t = {}
    if not t:      # 老设置：auto_intents 里的是自动，其他按默认（不会比原来更放开）
        allowed = {x.strip() for x in str(s.get("auto_intents") or "").split(",") if x.strip()}
        t = {k: ("auto" if (k in allowed and v == "auto") else ("confirm" if v == "auto" else v)) for k, v in DEFAULT_TIERS.items()}
    out = dict(DEFAULT_TIERS)
    out.update({k: v for k, v in t.items() if v in TIER_NAMES})
    for k in ("complaint", "refund", "change_order"):
        out[k] = "human"          # 这几类永远转人工
    return out


# ---------------- v2.22：知识库待确认 / 答不上来的问题 ----------------
def kb_pending():
    return [dict(r) for r in db.conn().execute("SELECT * FROM cs_kb WHERE status='pending' ORDER BY id DESC")]


def kb_add_learned(q, a, a_zh="", tags="", conv_id=None, active=False, note=""):
    c = db.conn()
    now = time.time()
    kid = c.execute("INSERT INTO cs_kb(q, a, a_zh, tags, active, created_at, updated_at, username, source, status, conv_id, note) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (q[:1000], a[:3000], (a_zh or "")[:3000], (tags or "")[:200], 1 if active else 0, now, now, "AI 学习",
                     "learned", "active" if active else "pending", conv_id, (note or "")[:300])).lastrowid
    c.commit()
    return kid


def kb_review(kid, ok, d=None, user=""):
    c = db.conn()
    if not ok:
        c.execute("DELETE FROM cs_kb WHERE id=? AND status='pending'", (kid,))
    else:
        d = d or {}
        sets = {"status": "active", "active": 1, "updated_at": time.time(), "username": user}
        for k in ("q", "a", "a_zh", "tags"):
            if d.get(k):
                sets[k] = d[k]
        c.execute(f"UPDATE cs_kb SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), kid))
    c.commit()


def unanswered_add(question, question_zh="", conv_id=None):
    from .brain import sim
    question = (question or "").strip()
    if not question:
        return
    c = db.conn()
    for r in c.execute("SELECT id, question FROM cs_unanswered WHERE status='open'").fetchall():
        if sim(question, r["question"]) > 0.55:
            c.execute("UPDATE cs_unanswered SET count=count+1, last_at=? WHERE id=?", (time.time(), r["id"]))
            c.commit()
            return
    c.execute("INSERT INTO cs_unanswered(question, question_zh, conv_id, created_at, last_at) VALUES(?,?,?,?,?)",
              (question[:1000], (question_zh or "")[:1000], conv_id, time.time(), time.time()))
    c.commit()


def unanswered(status="open", limit=100):
    return [dict(r) for r in db.conn().execute("SELECT * FROM cs_unanswered WHERE status=? ORDER BY count DESC, last_at DESC LIMIT ?",
                                               (status, int(limit)))]


def unanswered_done(uid, kb_id=None):
    c = db.conn()
    c.execute("UPDATE cs_unanswered SET status=?, kb_id=? WHERE id=?", ("done" if kb_id else "ignored", kb_id, uid))
    c.commit()


# ---------------- v2.22：线索 / 跟进 ----------------
LEAD_STAGES = {"new": "新线索", "follow": "跟进中", "quoted": "已报价", "won": "成交", "lost": "流失"}


def leads(stage="", due_only=False):
    conds, args = ["COALESCE(lead_stage,'')!=''"], []
    if stage:
        conds.append("lead_stage=?"); args.append(stage)
    if due_only:
        conds.append("lead_stage IN ('new','follow','quoted') AND next_follow_at IS NOT NULL AND next_follow_at<=?")
        args.append(time.time())
    return [_conv(r) for r in db.conn().execute("SELECT * FROM cs_conv WHERE " + " AND ".join(conds) + " ORDER BY COALESCE(next_follow_at, 9e12), updated_at DESC LIMIT 300", args)]
