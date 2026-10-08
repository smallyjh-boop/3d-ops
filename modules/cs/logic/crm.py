"""客服 v2.24：客户档案、登记中心（备注 / 待办 / 售后 / 投诉 / 特殊需求）、客服账号与店铺、客服报表。

参考电商平台客服后台（Shopee / Lazada 卖家中心聊天、千牛等）通行的做法：
  · 客户档案按 平台 + 店铺 + 买家 建，备注挂在档案上（换了会话也看得到），写明谁、哪个店、什么时间写的；
  · 登记的内容（备注、待办跟进、售后、投诉、特殊需求）统一放「登记中心」，按店铺 / 客服 / 类型 / 状态 / 日期筛选、导出；
  · 每条回复记下是哪个客服（ERP 账号或扩展密钥）发的，绩效按客服、按店铺统计：接待量、首次响应、平均响应、超时、
    AI 采用率、自动回复、关联订单；
  · 客服只看自己负责的店铺（老板在「客服账号与店铺」里分配，空 = 全部店铺）。
"""
import time

from core import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS cs_customer (
  id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT, shop TEXT, buyer TEXT,
  tags TEXT, first_at REAL, last_at REAL, convs INTEGER DEFAULT 0, note TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS cs_customer_key ON cs_customer(platform, shop, buyer);
CREATE TABLE IF NOT EXISTS cs_record (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, customer_id INTEGER, conv_id INTEGER,
  platform TEXT, shop TEXT, buyer TEXT, text TEXT, status TEXT DEFAULT 'open', priority INTEGER DEFAULT 0,
  due_at REAL, created_by TEXT, created_at REAL, updated_at REAL, done_by TEXT, done_at REAL, result TEXT
);
CREATE INDEX IF NOT EXISTS cs_record_st ON cs_record(status, due_at);
CREATE INDEX IF NOT EXISTS cs_record_cust ON cs_record(customer_id);
"""
KINDS = {"note": "备注", "todo": "待办 / 跟进", "aftersales": "售后登记", "complaint": "投诉", "request": "特殊需求 / 定制"}
KINDS_TH = {"note": "บันทึก", "todo": "งานที่ต้องทำ / ติดตาม", "aftersales": "บริการหลังการขาย", "complaint": "ร้องเรียน", "request": "ความต้องการพิเศษ / สั่งทำ"}
OPEN_KINDS = ("todo", "aftersales", "complaint", "request")     # 这些要处理完（备注只是记一笔）


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(cs_conv)")}
    if "customer_id" not in cols:
        c.execute("ALTER TABLE cs_conv ADD COLUMN customer_id INTEGER")
    c.commit()


# ---------------- 客服是谁 ----------------
def agent_of(username):
    """消息里记的用户名 → 客服名：扩展的密钥「api:Nok」→「Nok」（建密钥时用员工的账号名，就能对上 ERP 账号）。"""
    u = (username or "").strip()
    return u[4:] if u.startswith("api:") else u


def agent_names():
    """{账号名: 显示名}（ERP 账号）。"""
    try:
        return {r["username"]: (r["display_name"] or r["username"]) for r in db.conn().execute("SELECT username, display_name FROM users")}
    except Exception:  # noqa: BLE001
        return {}


# ---------------- 账号负责哪些店铺 ----------------
def _skey(username):
    return f"shops:{username}"


def shops_of(username):
    """这个账号负责的店铺（空列表 = 全部店铺）。"""
    r = db.conn().execute("SELECT v FROM cs_settings WHERE k=?", (_skey(agent_of(username)),)).fetchone()
    return [x for x in (r["v"] if r else "").split("\n") if x.strip()]


def set_shops(username, shops):
    c = db.conn()
    v = "\n".join(dict.fromkeys(s.strip() for s in shops or [] if s and s.strip()))
    c.execute("INSERT OR REPLACE INTO cs_settings(k, v) VALUES(?, ?)", (_skey(agent_of(username)), v))
    c.commit()
    return shops_of(username)


def known_shops():
    c = db.conn()
    out = [r[0] for r in c.execute("SELECT DISTINCT shop FROM cs_conv WHERE COALESCE(shop,'')!='' ORDER BY shop")]
    try:
        from . import api
        for t in api._presence_list(3600):
            if t.get("shop") and t["shop"] not in out:
                out.append(t["shop"])
    except Exception:  # noqa: BLE001
        pass
    return out


def allowed(user):
    """当前用户能看的店铺：None = 全部（老板、或没分配店铺的员工）。"""
    if not user or user.get("role") == "owner":
        return None
    s = shops_of(user.get("username") or "")
    return s or None


def shop_ok(user, shop):
    a = allowed(user)
    return a is None or (shop or "") in a


# ---------------- 客户档案 ----------------
def customer_for(platform, shop, buyer):
    """按 平台 + 店铺 + 买家 找档案，没有就建。买家名为空不建档。"""
    buyer = (buyer or "").strip()
    if not buyer:
        return None
    c = db.conn()
    key = (platform or "", shop or "", buyer)
    r = c.execute("SELECT * FROM cs_customer WHERE platform=? AND shop=? AND buyer=?", key).fetchone()
    now = time.time()
    if r:
        c.execute("UPDATE cs_customer SET last_at=? WHERE id=?", (now, r["id"]))
        c.commit()
        return dict(r)
    cid = c.execute("INSERT INTO cs_customer(platform, shop, buyer, first_at, last_at, convs) VALUES(?,?,?,?,?,0)", (*key, now, now)).lastrowid
    c.commit()
    return dict(c.execute("SELECT * FROM cs_customer WHERE id=?", (cid,)).fetchone())


def link_conv(conv):
    """会话 → 客户档案（买家名、店铺有了以后）。返回档案 id。"""
    if not conv or not (conv.get("buyer") or "").strip():
        return None
    cu = customer_for(conv.get("platform"), conv.get("shop"), conv.get("buyer"))
    if not cu:
        return None
    c = db.conn()
    if conv.get("customer_id") != cu["id"]:
        c.execute("UPDATE cs_conv SET customer_id=? WHERE id=?", (cu["id"], conv["id"]))
        c.execute("UPDATE cs_customer SET convs=(SELECT COUNT(*) FROM cs_conv WHERE customer_id=?) WHERE id=?", (cu["id"], cu["id"]))
        c.commit()
    return cu["id"]


def customer(cid):
    """档案 + 历史会话 + 关联订单 + 备注 / 登记。"""
    c = db.conn()
    r = c.execute("SELECT * FROM cs_customer WHERE id=?", (cid,)).fetchone()
    if not r:
        raise ValueError("没有这个客户档案")
    d = dict(r)
    d["conv_list"] = [dict(x) for x in c.execute(
        "SELECT id, status, intent, summary, order_no, created_at, updated_at, lead_stage FROM cs_conv WHERE customer_id=? ORDER BY updated_at DESC LIMIT 30", (cid,))]
    d["orders"] = sorted({x["order_no"] for x in d["conv_list"] if x.get("order_no")})
    d["records"] = records(customer_id=cid, limit=100)
    d["visits"] = len(d["conv_list"])
    return d


# ---------------- 登记中心 ----------------
def _rec(r):
    d = dict(r)
    d["kind_zh"] = KINDS.get(d["kind"], d["kind"])
    d["kind_th"] = KINDS_TH.get(d["kind"], d["kind"])
    d["agent"] = agent_of(d.get("created_by"))
    d["overdue"] = bool(d["status"] == "open" and d.get("due_at") and d["due_at"] < time.time())
    return d


def add_record(kind, text, user="", conv_id=None, customer_id=None, due_at=None, priority=0, platform="", shop="", buyer=""):
    kind = kind if kind in KINDS else "note"
    text = (text or "").strip()
    if not text:
        raise ValueError("内容是空的")
    c = db.conn()
    if conv_id:
        cv = c.execute("SELECT id, platform, shop, buyer, customer_id FROM cs_conv WHERE id=?", (conv_id,)).fetchone()
        if not cv:
            raise ValueError("会话不存在")
        platform, shop, buyer = cv["platform"] or "", cv["shop"] or "", cv["buyer"] or ""
        customer_id = customer_id or cv["customer_id"] or link_conv(dict(cv))
    elif customer_id:
        cu = c.execute("SELECT platform, shop, buyer FROM cs_customer WHERE id=?", (customer_id,)).fetchone()
        if cu:
            platform, shop, buyer = cu["platform"], cu["shop"], cu["buyer"]
    try:
        due = float(due_at) if due_at not in (None, "") else None
    except (TypeError, ValueError):
        due = None
    now = time.time()
    rid = c.execute("""INSERT INTO cs_record(kind, customer_id, conv_id, platform, shop, buyer, text, status, priority, due_at,
                       created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (kind, customer_id, conv_id, platform or "", shop or "", buyer or "", text[:2000],
                     "done" if kind == "note" else "open", int(priority or 0), due, user, now, now)).lastrowid
    c.commit()
    return get_record(rid)


def get_record(rid):
    r = db.conn().execute("SELECT * FROM cs_record WHERE id=?", (rid,)).fetchone()
    if not r:
        raise ValueError("没有这条登记")
    return _rec(r)


def update_record(rid, user="", **kw):
    r = get_record(rid)
    sets = {}
    if "text" in kw and (kw["text"] or "").strip():
        sets["text"] = kw["text"].strip()[:2000]
    if "status" in kw and kw["status"] in ("open", "done"):
        sets["status"] = kw["status"]
        sets["done_by"], sets["done_at"] = (user, time.time()) if kw["status"] == "done" else (None, None)
    if "result" in kw:
        sets["result"] = (kw["result"] or "")[:1000]
    if "due_at" in kw:
        try:
            sets["due_at"] = float(kw["due_at"]) if kw["due_at"] not in (None, "") else None
        except (TypeError, ValueError):
            pass
    if "priority" in kw:
        sets["priority"] = int(kw["priority"] or 0)
    if "kind" in kw and kw["kind"] in KINDS:
        sets["kind"] = kw["kind"]
    if not sets:
        return r
    sets["updated_at"] = time.time()
    c = db.conn()
    c.execute("UPDATE cs_record SET " + ", ".join(f"{k}=?" for k in sets) + " WHERE id=?", (*sets.values(), rid))
    c.commit()
    return get_record(rid)


def delete_record(rid):
    c = db.conn()
    c.execute("DELETE FROM cs_record WHERE id=?", (rid,))
    c.commit()


def records(kind="", status="", shop="", agent="", q="", date_from=None, date_to=None, customer_id=None, conv_id=None,
            due_only=False, shops=None, limit=500):
    conds, args = [], []
    if kind:
        conds.append("kind=?"); args.append(kind)
    if status == "overdue":
        conds.append("status='open' AND due_at IS NOT NULL AND due_at<?"); args.append(time.time())
    elif status:
        conds.append("status=?"); args.append(status)
    if shop:
        conds.append("COALESCE(shop,'')=?"); args.append(shop)
    if shops is not None:
        conds.append("COALESCE(shop,'') IN (%s)" % ",".join("?" * len(shops)) if shops else "0")
        args += list(shops)
    if agent:
        conds.append("(created_by=? OR created_by=?)"); args += [agent, "api:" + agent]
    if q:
        conds.append("(text LIKE ? OR buyer LIKE ? OR result LIKE ?)"); args += [f"%{q}%"] * 3
    if date_from:
        conds.append("created_at>=?"); args.append(float(date_from))
    if date_to:
        conds.append("created_at<?"); args.append(float(date_to))
    if customer_id:
        conds.append("customer_id=?"); args.append(int(customer_id))
    if conv_id:
        conds.append("conv_id=?"); args.append(int(conv_id))
    if due_only:
        conds.append("status='open' AND due_at IS NOT NULL AND due_at<?"); args.append(time.time() + 86400)
    sql = ("SELECT * FROM cs_record" + (" WHERE " + " AND ".join(conds) if conds else "")
           + " ORDER BY CASE WHEN status='open' THEN 0 ELSE 1 END, COALESCE(due_at, 9e18), priority DESC, created_at DESC LIMIT ?")
    return [_rec(r) for r in db.conn().execute(sql, (*args, int(limit)))]


def record_counts(shops=None):
    c = db.conn()
    cond, args = "", []
    if shops is not None:
        cond = " AND COALESCE(shop,'') IN (%s)" % ",".join("?" * len(shops)) if shops else " AND 0"
        args = list(shops)
    now = time.time()
    return {"open": c.execute("SELECT COUNT(*) FROM cs_record WHERE status='open'" + cond, args).fetchone()[0],
            "overdue": c.execute("SELECT COUNT(*) FROM cs_record WHERE status='open' AND due_at IS NOT NULL AND due_at<?" + cond, (now, *args)).fetchone()[0],
            "due_today": c.execute("SELECT COUNT(*) FROM cs_record WHERE status='open' AND due_at IS NOT NULL AND due_at<?" + cond,
                                   (_day_start(now) + 86400, *args)).fetchone()[0]}


def export_xlsx(rows, path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "登记中心"
    ws.append(["编号", "类型", "状态", "平台", "店铺", "买家", "内容", "处理结果", "到期", "登记人", "登记时间", "完成人", "完成时间"])
    f = lambda t: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else ""  # noqa: E731
    for r in rows:
        ws.append([r["id"], r["kind_zh"], "已完成" if r["status"] == "done" else ("已超期" if r["overdue"] else "待处理"), r["platform"], r["shop"],
                   r["buyer"], r["text"], r.get("result") or "", f(r.get("due_at")), r["agent"], f(r["created_at"]),
                   agent_of(r.get("done_by")), f(r.get("done_at"))])
    for col, w in zip("ABCDEFGHIJKLM", (6, 12, 8, 8, 14, 16, 50, 30, 16, 10, 16, 10, 16)):
        ws.column_dimensions[col].width = w
    wb.save(path)
    return path


# ---------------- 客服报表 ----------------
def _day_start(t=None):
    lt = time.localtime(t or time.time())
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def report(t0, t1, shops=None, agent=None):
    """时间段 [t0, t1) 的客服报表：按客服、按店铺。
    响应时间 = 买家（一段连续消息的第一条）→ 我们下一条回复；首次响应 = 每个会话这一段时间里第一次回复。"""
    from . import data
    c = db.conn()
    try:
        alert = float(data.settings().get("alert_minutes") or 10)
    except ValueError:
        alert = 10.0
    cond, args = "", []
    if shops is not None:
        cond = " AND COALESCE(v.shop,'') IN (%s)" % ",".join("?" * len(shops)) if shops else " AND 0"
        args = list(shops)
    rows = c.execute("SELECT m.conv_id, m.role, m.text, m.source, m.ai_draft, m.created_at, m.username, COALESCE(v.shop,'') shop, "
                     "COALESCE(v.platform,'') platform, v.customer_id, v.order_id FROM cs_msg m JOIN cs_conv v ON v.id=m.conv_id "
                     "WHERE m.created_at>=? AND m.created_at<? AND m.role IN ('buyer','seller')" + cond + " ORDER BY m.conv_id, m.id",
                     (t0, t1, *args)).fetchall()
    names = agent_names()
    A, S = {}, {}

    def ag(u):
        k = agent_of(u) or "（未记录）"
        return A.setdefault(k, {"agent": k, "name": names.get(k, k), "convs": set(), "sent": 0, "auto": 0, "with_draft": 0, "edited": 0,
                                "waits": [], "first": [], "over": 0})

    def sh(r):
        k = r["shop"] or "（未填店铺）"
        return S.setdefault(k, {"shop": k, "platforms": set(), "convs": set(), "buyer_msgs": 0, "sent": 0, "customers": set(),
                                "orders": set(), "waits": [], "unanswered": 0})
    pending, first_done = {}, set()
    for r in rows:
        s = sh(r)
        s["platforms"].add(r["platform"])
        s["convs"].add(r["conv_id"])
        if r["customer_id"]:
            s["customers"].add(r["customer_id"])
        if r["order_id"]:
            s["orders"].add(r["order_id"])
        if r["role"] == "buyer":
            s["buyer_msgs"] += 1
            pending.setdefault(r["conv_id"], r["created_at"])
            continue
        a = ag(r["username"])
        a["convs"].add(r["conv_id"])
        a["sent"] += 1
        s["sent"] += 1
        if r["source"] == "auto":
            a["auto"] += 1
        elif r["ai_draft"]:
            a["with_draft"] += 1
            if (r["ai_draft"] or "").strip() != (r["text"] or "").strip():
                a["edited"] += 1
        p0 = pending.pop(r["conv_id"], None)
        if p0 is not None and r["created_at"] >= p0:
            w = (r["created_at"] - p0) / 60
            a["waits"].append(w)
            s["waits"].append(w)
            if w > alert:
                a["over"] += 1
            if r["conv_id"] not in first_done:
                a["first"].append(w)
        first_done.add(r["conv_id"])
    for cid in pending:                              # 这段时间结束时还没回复的
        r = next((x for x in rows if x["conv_id"] == cid), None)
        if r:
            sh(r)["unanswered"] += 1
    avg = lambda v: round(sum(v) / len(v), 1) if v else None  # noqa: E731
    agents = []
    for a in A.values():
        if agent and a["agent"] != agent:
            continue
        agents.append({"agent": a["agent"], "name": a["name"], "convs": len(a["convs"]), "sent": a["sent"], "auto": a["auto"],
                       "avg_reply_min": avg(a["waits"]), "first_reply_min": avg(a["first"]), "over_alert": a["over"],
                       "adopt_pct": round(100 * (a["with_draft"] - a["edited"]) / a["with_draft"]) if a["with_draft"] else None})
    rc = {}
    for r in c.execute("SELECT created_by, kind, status, done_by, created_at, done_at FROM cs_record WHERE (created_at>=? AND created_at<?) OR (done_at>=? AND done_at<?)",
                       (t0, t1, t0, t1)):
        k = agent_of(r["created_by"])
        if t0 <= (r["created_at"] or 0) < t1:
            rc.setdefault(k, {"added": 0, "done": 0})["added"] += 1
        if r["done_at"] and t0 <= r["done_at"] < t1 and r["kind"] != "note":
            rc.setdefault(agent_of(r["done_by"]), {"added": 0, "done": 0})["done"] += 1
    for a in agents:
        a["records_added"] = rc.get(a["agent"], {}).get("added", 0)
        a["records_done"] = rc.get(a["agent"], {}).get("done", 0)
    agents.sort(key=lambda x: -x["sent"])
    shops_out = []
    for s in S.values():
        new_c = 0
        if s["customers"]:
            ids = list(s["customers"])
            new_c = c.execute("SELECT COUNT(*) FROM cs_customer WHERE id IN (%s) AND first_at>=?" % ",".join("?" * len(ids)), (*ids, t0)).fetchone()[0]
        conv_ids = list(s["convs"])
        leads = c.execute("SELECT COUNT(*) FROM cs_conv WHERE id IN (%s) AND lead_at>=? AND lead_at<?" % ",".join("?" * len(conv_ids)),
                          (*conv_ids, t0, t1)).fetchone()[0] if conv_ids else 0
        shops_out.append({"shop": s["shop"], "platforms": sorted(x for x in s["platforms"] if x), "convs": len(s["convs"]),
                          "buyer_msgs": s["buyer_msgs"], "sent": s["sent"], "customers": len(s["customers"]), "new_customers": new_c,
                          "returning": len(s["customers"]) - new_c, "with_order": len(s["orders"]), "leads": leads,
                          "avg_reply_min": avg(s["waits"]), "unanswered": s["unanswered"]})
    shops_out.sort(key=lambda x: -x["convs"])
    tot_w = [w for a in A.values() for w in a["waits"]]
    return {"from": t0, "to": t1, "agents": agents, "shops": shops_out,
            "total": {"convs": len({r["conv_id"] for r in rows}), "sent": sum(a["sent"] for a in agents),
                      "auto": sum(a["auto"] for a in agents), "avg_reply_min": avg(tot_w),
                      "over_alert": sum(a["over_alert"] for a in agents), "buyer_msgs": sum(s["buyer_msgs"] for s in shops_out)}}


def workbench(user):
    """登录后工作台的客服报告：今天 vs 昨天；员工看自己，老板看全部（按客服、按店铺）。"""
    from . import data
    now = time.time()
    d0 = _day_start(now)
    shops = allowed(user)
    own = (user or {}).get("role") == "owner"
    me = agent_of((user or {}).get("username"))
    today = report(d0, now + 1, shops, None if own else None)
    yest = report(d0 - 86400, d0, shops)
    mine = None
    if not own:
        mine = {"today": next((a for a in today["agents"] if a["agent"] == me), None),
                "yesterday": next((a for a in yest["agents"] if a["agent"] == me), None)}
    my_recs = [r for r in records(status="open", shops=shops, limit=200) if r.get("due_at") and r["due_at"] < d0 + 86400]
    convs = [x for x in data.list_convs("open", limit=100) if shops is None or (x.get("shop") or "") in shops]
    waiting = [{"id": x["id"], "buyer": x.get("buyer"), "shop": x.get("shop") or "", "platform": x.get("platform"), "wait_min": x.get("wait_min"),
                "needs_human": bool(x.get("needs_human"))} for x in convs if (x.get("last") or {}).get("role") == "buyer"]
    waiting.sort(key=lambda x: -(x["wait_min"] or 0))
    leads_due = [x for x in data.leads(due_only=True) if shops is None or (x.get("shop") or "") in shops]
    return {"owner": own, "me": me, "shops": shops, "today": today, "yesterday": yest, "mine": mine,
            "waiting": waiting[:10], "waiting_n": len(waiting), "records_due": my_recs[:10], "records": record_counts(shops),
            "leads_due": len(leads_due), "unanswered_kb": len(data.unanswered())}


def active_agents(days=60):
    """最近回复过的客服（给筛选用）：[{agent, name}]。"""
    names = agent_names()
    out = []
    for r in db.conn().execute("SELECT DISTINCT username FROM cs_msg WHERE role='seller' AND created_at>=? AND COALESCE(username,'')!=''",
                               (time.time() - days * 86400,)):
        a = agent_of(r[0])
        if a and a not in [x["agent"] for x in out]:
            out.append({"agent": a, "name": names.get(a, a)})
    return out
