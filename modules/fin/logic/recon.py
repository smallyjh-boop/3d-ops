"""平台对账（v2.49 自动化）：每个订单自动标出回款状态，不用再手工看表格。

数据从哪来（每单标「来源」）：
  接口      Lazada 财务流水（运营分析模块每小时拉 /finance/transaction/details/get，交给 settle.import_lines）
            + 这里自己拉的 Lazada 结算单（GetPayoutStatus /finance/payout/status/get → 表 fin_payouts）：知道哪一期结算单已经打款、哪天打的。
  导入表格  Shopee / TikTok（还没有接口）以及手工导入的 Lazada 对账单。
  估算      平台还没有任何结算记录：按设置里的扣点估算到账。

每单的状态（state）：
  paid      已到账    有结算记录，且钱已经打到卡上（Lazada：对应的结算单 paid=1；Shopee / TikTok 导入的是「已拨款」报表，导入即到账）
  settled   已结算    平台已经算好这单的钱（有结算记录），但这一期还没打款
  pending   待回款    已发货，还没到该回款的时间
  overdue   超时未回款 已发货超过 N 天还没有结算记录（平台数据还没覆盖到这单：可能还没导入 / 没同步），或者结算了但超过 N 天还没打款
  unsettled 平台没结算 已发货超过 N 天，平台的结算数据已经覆盖到更晚的日子了，偏偏没有这一单（可能被平台取消 / 退货，要去问平台）
另有 issue = "diff"（扣费比预计多：到账比「订单金额 ×（1 − 扣点）」少了 容差 以上），和状态同时存在。
平台有但系统没有（unknown）：结算记录里有订单号，系统里找不到。
每单可以标「已核对」（fin_checked），标了就不算进异常数。
"""
import datetime as dt
import json
import re
import threading
import time

from core import db
from .common import day_of, r2, settings, ts

SCHEMA = """
CREATE TABLE IF NOT EXISTS fin_payouts (
  platform TEXT, shop TEXT, statement TEXT, created_at TEXT, updated_at TEXT, paid INTEGER, amount REAL, currency TEXT,
  opening REAL, closing REAL, item_revenue REAL, fees_total REAL, refunds REAL, raw TEXT, synced_at REAL,
  PRIMARY KEY(platform, shop, statement)
);
CREATE TABLE IF NOT EXISTS fin_checked (
  platform TEXT, order_key TEXT, username TEXT, at REAL, note TEXT, PRIMARY KEY(platform, order_key)
);
CREATE TABLE IF NOT EXISTS fin_sync_state (
  platform TEXT, shop TEXT, kind TEXT, last_try REAL, last_ok REAL, error TEXT, rows INTEGER, PRIMARY KEY(platform, shop, kind)
);
"""
PLATFORMS = ("lazada", "shopee", "tiktok")
STATE_ZH = {"paid": "已到账", "settled": "已结算", "pending": "待回款", "overdue": "超时未回款", "unsettled": "平台没结算"}
STATE_TH = {"paid": "เงินเข้าแล้ว", "settled": "สรุปยอดแล้ว", "pending": "รอรับเงิน", "overdue": "เกินกำหนดยังไม่ได้รับเงิน",
            "unsettled": "แพลตฟอร์มไม่ได้สรุปยอด"}
SOURCE_ZH = {"api": "接口", "import": "导入表格", "order": "订单表", "estimate": "估算"}
# 费用分类（按费用名里的词，中 / 英 / 泰；越靠前越优先）
FEE_CATS = [
    ("item", "商品金额", "ยอดสินค้า", ()),
    ("refund", "退款 / 退货", "คืนเงิน/คืนสินค้า", ("refund", "return", "reversal", "คืนเงิน", "คืนสินค้า", "退款", "退货")),
    ("penalty", "罚款", "ค่าปรับ", ("penalty", "fine", "ค่าปรับ", "罚")),
    ("voucher", "优惠券 / 促销", "คูปอง/โปรโมชั่น", ("voucher", "promotion", "discount", "coupon", "bundle", "flexi", "บัตรกำนัล", "ส่วนลด", "优惠", "折扣")),
    ("shipping", "运费", "ค่าส่ง", ("shipping", "delivery", "logistic", "ค่าจัดส่ง", "ค่าส่ง", "运费", "物流")),
    ("payment", "支付手续费", "ค่าธรรมเนียมชำระเงิน", ("payment fee", "transaction fee", "payment", "การชำระเงิน", "手续费", "支付")),
    ("commission", "佣金", "ค่าคอมมิชชั่น", ("commission", "คอมมิชชั่น", "佣金")),
    ("service", "服务费 / 活动费", "ค่าบริการ/แคมเปญ", ("service", "campaign", "program", "fee", "ค่าบริการ", "ค่าธรรมเนียม", "服务费", "费")),
    ("net", "到账（只有合计）", "ยอดสุทธิ (มีแต่ยอดรวม)", ("settlement",)),
    ("other", "其他", "อื่นๆ", ()),
]
_inited = set()
_lock = threading.Lock()


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()
    _inited.add(db.DB_PATH)


def _ensure():
    if db.DB_PATH not in _inited:
        init()


def _num(v):
    m = re.search(r"-?\d[\d,]*\.?\d*", str(v or ""))
    try:
        return float(m.group(0).replace(",", "")) if m else None
    except ValueError:
        return None


def _date(s):
    """各种写法的日期 → date（'2018-01-04 00:23:04' / '17 May 2016' / '20141228'）。认不出返回 None。"""
    s = str(s or "").strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%d %b %Y", None), ("%d %B %Y", None), ("%Y%m%d", 8), ("%d/%m/%Y", 10)):
        try:
            return dt.datetime.strptime(s[:n] if n else s, fmt).date()
        except ValueError:
            continue
    return None


def _period_of(ref):
    """Lazada 流水里的 statement：'11 May 2016 - 17 May 2016' → (起, 止)。"""
    m = re.match(r"\s*(.+?)\s+-\s+(.+?)\s*$", str(ref or ""))
    if not m:
        return None
    a, b = _date(m.group(1)), _date(m.group(2))
    return (a, b) if a and b else None


def fee_cat(name, is_item=0):
    if is_item:
        return "item"
    n = str(name or "").lower()
    for k, _zh, _th, words in FEE_CATS:
        if words and any(w in n for w in words):
            return k
    return "other"


# ---------------- Lazada 结算单（GetPayoutStatus）----------------
def _set_state(platform, shop, kind, ok, rows=0, error=""):
    c = db.conn()
    old = c.execute("SELECT last_ok FROM fin_sync_state WHERE platform=? AND shop=? AND kind=?", (platform, shop, kind)).fetchone()
    now = time.time()
    c.execute("INSERT OR REPLACE INTO fin_sync_state(platform, shop, kind, last_try, last_ok, error, rows) VALUES(?,?,?,?,?,?,?)",
              (platform, shop, kind, now, now if ok else (old["last_ok"] if old else None), "" if ok else str(error)[:400], rows))
    c.commit()


def lazada_shops():
    return [{"id": r["id"], "name": r["name"]} for r in db.conn().execute(
        "SELECT id, name FROM shops WHERE enabled=1 AND platform='lazada' ORDER BY id")]


def save_payouts(platform, shop, rows):
    """把接口拿到的结算单记下来（同一个结算单号覆盖：paid 会从 0 变 1）。返回条数。"""
    _ensure()
    c = db.conn()
    now = time.time()
    n = 0
    for x in rows or []:
        if not isinstance(x, dict) or not x.get("statement_number"):
            continue
        cur = str(x.get("payout") or "").split()
        c.execute("INSERT OR REPLACE INTO fin_payouts(platform, shop, statement, created_at, updated_at, paid, amount, currency, opening, closing, "
                  "item_revenue, fees_total, refunds, raw, synced_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (platform, shop, str(x["statement_number"]), str(x.get("created_at") or "")[:19], str(x.get("updated_at") or "")[:19],
                   1 if str(x.get("paid")).strip().lower() in ("1", "true", "yes", "paid") else 0, _num(x.get("payout")),
                   cur[1] if len(cur) > 1 else "", _num(x.get("opening_balance")), _num(x.get("closing_balance")),
                   _num(x.get("item_revenue")), _num(x.get("fees_total")), _num(x.get("refunds")),
                   json.dumps(x, ensure_ascii=False)[:2000], now))
        n += 1
    c.commit()
    return n


def sync_payouts(user="系统", days=120):
    """每个开着的 Lazada 店铺拉一次结算单（最近 days 天建的）。一个店铺出错不影响别的，错误记在 fin_sync_state。"""
    _ensure()
    from core import connectors, integrations
    out = []
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with _lock:
        for sh in lazada_shops():
            try:
                s = integrations.get_shop_raw(sh["id"])
                conn = connectors.make("lazada", s["creds"])
                conn.check()
                rows = conn.payout_status(since)
                n = save_payouts("lazada", sh["name"], rows)
                integrations._store_creds(sh["id"], conn)
                _set_state("lazada", sh["name"], "payout", True, rows=n)
                out.append({"shop": sh["name"], "payouts": n})
            except Exception as e:  # noqa: BLE001
                db.release()
                _set_state("lazada", sh["name"], "payout", False, error=str(e))
                out.append({"shop": sh["name"], "error": str(e)[:300], "hint": _hint(e)})
    return out


def _hint(e):
    try:
        from modules.ops.lazada import hint_of
        h = hint_of("finance", e)
        return h.replace("Finance API", "Finance API（GetPayoutStatus）") if h else ""
    except Exception:  # noqa: BLE001
        return ""


def sync_now(user="系统"):
    """「立即同步」：运营分析模块拉 Lazada 财务流水（只拉财务）+ 这里拉结算单。返回 {finance, payouts, ops_on}。"""
    from core import modules
    res = {"ops_on": False, "finance": None, "payouts": []}
    if modules.enabled("ops"):
        res["ops_on"] = True
        try:
            from modules.ops import lazada as olz
            res["finance"] = olz.sync(kinds=["finance"], user=user)
        except Exception as e:  # noqa: BLE001
            res["finance"] = {"error": str(e)[:300]}
    res["payouts"] = sync_payouts(user)
    return res


def _payout_index():
    """{(platform, shop): [结算单…按建立时间排]}，每个带 d（结算单号里的日期）、cd（建立日期）。"""
    idx = {}
    for r in db.conn().execute("SELECT * FROM fin_payouts ORDER BY created_at"):
        d = dict(r)
        m = re.search(r"(\d{8})", d["statement"] or "")
        d["d"] = _date(m.group(1)) if m else None
        d["cd"] = _date(d["created_at"])
        idx.setdefault((d["platform"], d["shop"] or ""), []).append(d)
    return idx


def _match_payout(pays, ref, day):
    """一行流水属于哪一期结算单：结算单号里的日期落在流水的结算期里 → 就是它；否则取流水日期之后最早建立的结算单（20 天内）。"""
    if not pays:
        return None
    per = _period_of(ref)
    if per:
        for p in pays:
            if p["d"] and per[0] - dt.timedelta(days=1) <= p["d"] <= per[1] + dt.timedelta(days=1):
                return p
        anchor = per[1]
    else:
        anchor = _date(day)
    if not anchor:
        return None
    for p in pays:
        if p["cd"] and anchor <= p["cd"] <= anchor + dt.timedelta(days=20):
            return p
    return None


# ---------------- 已核对 ----------------
def set_checked(platform, order_no, on=True, user="", note=""):
    _ensure()
    from .settle import key
    k = key(order_no)
    if not k or platform not in PLATFORMS + ("other",):
        raise ValueError("订单号或平台不对")
    c = db.conn()
    if on:
        c.execute("INSERT OR REPLACE INTO fin_checked(platform, order_key, username, at, note) VALUES(?,?,?,?,?)",
                  (platform, k, user, time.time(), str(note or "")[:200]))
    else:
        c.execute("DELETE FROM fin_checked WHERE platform=? AND order_key=?", (platform, k))
    c.commit()
    db.audit(user, "财务·对账已核对" if on else "财务·取消已核对", f"{platform} {order_no}", note or "")
    return {"ok": True, "checked": bool(on)}


def _checked():
    return {(r["platform"], r["order_key"]): {"by": r["username"], "at": r["at"], "note": r["note"]}
            for r in db.conn().execute("SELECT * FROM fin_checked")}


# ---------------- 每单状态 ----------------
def _cfg_rate(cfg, platform):
    if platform == "shopee" and cfg.get("shopee_fee_rate"):
        return float(cfg.get("shopee_fee_rate") or 0)
    if platform == "tiktok" and cfg.get("tiktok_fee_rate"):
        return float(cfg.get("tiktok_fee_rate") or 0)
    return float(cfg.get("platform_fee_rate", 0) or 0)


def _lines_by_key(c, keys_by_plat):
    out = {}
    for p, keys in keys_by_plat.items():
        keys = list(keys)
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            for r in c.execute(f"SELECT platform, shop, order_key, fee_name, amount, wht, vat, day, ref, row_hash, is_item FROM fin_settle_lines "
                               f"WHERE platform=? AND order_key IN ({','.join('?' * len(chunk))}) ORDER BY id", (p, *chunk)):
                out.setdefault((p, r["order_key"]), []).append(dict(r))
    return out


def _coverage(c):
    """每个平台的结算数据覆盖到哪些日子：{platform: (最早, 最晚)}。"""
    return {r["platform"]: (_date(r["a"]), _date(r["b"])) for r in c.execute(
        "SELECT platform, MIN(day) a, MAX(day) b FROM fin_settle_lines WHERE COALESCE(order_key,'')!='' AND COALESCE(day,'')!='' GROUP BY platform")}


def classify(orders, cfg=None, now=None):
    """orders = orders 表的行（要有 id, platform, shop, order_no, status, order_time, order_total, settlement）。
    返回 {order_id: {state, issue, source, net, fee, expected, diff, paid_at, days, statement, key}}；手工单 / 没有平台的不算。"""
    _ensure()
    from core.config import load_config
    from .settle import key
    cfg = cfg or load_config()
    st = settings(cfg)
    now = now or time.time()
    today = dt.date.today()
    c = db.conn()
    orders = [o for o in orders if (o["platform"] or "") not in ("", "manual")]
    keys = {}
    for o in orders:
        keys.setdefault(o["platform"], set()).add(key(o["order_no"]))
    lines = _lines_by_key(c, keys)
    cover = _coverage(c)
    pays = _payout_index()
    item_sum = {}
    ids = [o["id"] for o in orders if o["order_total"] is None]
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in c.execute(f"SELECT order_id, SUM(COALESCE(item_total,0)) s FROM order_items WHERE order_id IN ({','.join('?' * len(chunk))}) "
                           f"GROUP BY order_id", chunk):
            item_sum[r[0]] = r[1]
    out = {}
    N = st["settle_days"]
    for o in orders:
        k = key(o["order_no"])
        ls = lines.get((o["platform"], k), [])
        rev = float(o["order_total"] if o["order_total"] is not None else (item_sum.get(o["id"]) or 0))
        rate = _cfg_rate(cfg, o["platform"])
        expect = rev * (1 - rate)
        oday = dt.date.fromtimestamp(o["order_time"]) if o["order_time"] else today
        shipped = o["status"] in ("shipped", "completed")
        r = {"key": k, "revenue": r2(rev), "expected": r2(expect), "rate": round(rate * 100, 1), "issue": "", "paid_at": None,
             "statement": "", "days": int((now - (o["order_time"] or now)) // 86400)}
        if ls or o["settlement"] is not None:
            net = float(o["settlement"]) if o["settlement"] is not None else sum(x["amount"] for x in ls)
            r.update(net=r2(net), fee=r2(rev - net), fee_rate=round((rev - net) / rev * 100, 1) if rev else None, diff=r2(expect - net))
            r["source"] = "api" if any(str(x["row_hash"] or "").startswith("api:") for x in ls) else ("import" if ls else "order")
            if expect - net > st["tolerance"]:
                r["issue"] = "diff"
            last = max((x["day"] for x in ls if x["day"]), default="")
            r["settle_day"] = last
            if o["platform"] == "lazada" and ls:
                plist = pays.get(("lazada", ls[0]["shop"] or ""), []) or [p for (pl, _s), v in pays.items() if pl == "lazada" for p in v]
                got = [_match_payout(plist, x["ref"], x["day"]) for x in ls if x["amount"]]
                if plist and got and all(got) and all(p["paid"] for p in got):
                    r["state"] = "paid"
                    r["paid_at"] = max((p["updated_at"] or p["created_at"] or "")[:10] for p in got)
                    r["statement"] = got[-1]["statement"]
                else:
                    r["state"] = "settled"
                    if got and any(got):
                        r["statement"] = next(p for p in got if p)["statement"]
                    ld = _date(last)
                    if plist and ld and (today - ld).days > N:          # 结算了，超过 N 天还没打款
                        r["state"] = "overdue"
                        r["days"] = (today - ld).days
            elif ls:
                r["state"] = "paid"                                       # Shopee / TikTok 导入的是已拨款报表
                r["paid_at"] = last or None
            else:
                r["state"] = "settled"
        else:
            r.update(net=None, fee=None, fee_rate=None, diff=None, source="estimate")
            if not shipped:
                r["state"] = "open"
            elif o["order_time"] and now - o["order_time"] > N * 86400:
                cv = cover.get(o["platform"])
                if cv and cv[0] and cv[1] and cv[0] <= oday + dt.timedelta(days=N) <= cv[1]:
                    r["state"] = "unsettled"
                else:
                    r["state"] = "overdue"
            else:
                r["state"] = "pending"
        out[o["id"]] = r
    return out


def breakdown_of(platform, order_no):
    """一个订单的结算明细，按费用分类加起来：{cats:[{cat, zh, th, amount}], lines:[…], net, source}。"""
    _ensure()
    from .settle import key, order_lines
    c = db.conn()
    o = c.execute("SELECT * FROM orders WHERE platform=? AND order_no=?", (platform, order_no)).fetchone()
    ls = [dict(x) for x in c.execute("SELECT fee_name, amount, wht, vat, day, ref, row_hash, is_item FROM fin_settle_lines "
                                      "WHERE platform=? AND order_key=? ORDER BY id", (platform, key(order_no)))] if order_no else []
    if not ls:
        ls = [dict(x, row_hash="", is_item=0) for x in order_lines(platform, order_no)]
    cats = {}
    for x in ls:
        k = fee_cat(x["fee_name"], x.get("is_item"))
        cats[k] = cats.get(k, 0) + (x["amount"] or 0)
        x["cat"] = k
        x["src"] = "api" if str(x.get("row_hash") or "").startswith("api:") else "import"
        x.pop("row_hash", None)
    names = {k: (zh, th) for k, zh, th, _w in FEE_CATS}
    rev = None
    est = {}
    if o:
        from core.config import load_config
        from core.finance import order_profit
        items = c.execute("SELECT * FROM order_items WHERE order_id=?", (o["id"],)).fetchall()
        p = order_profit(load_config(), o, items)
        rev = p["revenue"]
        est = {k: r2(o[k]) for k in ("order_total", "buyer_shipping", "platform_discount", "seller_discount", "commission", "service_fee",
                                      "payment_fee", "platform_fee") if k in o.keys() and o[k] is not None}
    chk = db.conn().execute("SELECT * FROM fin_checked WHERE platform=? AND order_key=?", (platform, key(order_no))).fetchone()
    return {"ok": True, "platform": platform, "order_no": order_no, "order_id": o["id"] if o else None, "revenue": rev,
            "cats": [{"cat": k, "zh": names[k][0], "th": names[k][1], "amount": r2(v)} for k, v in
                     sorted(cats.items(), key=lambda kv: [x[0] for x in FEE_CATS].index(kv[0]))],
            "net": r2(sum(x["amount"] or 0 for x in ls)) if ls else None, "wht": r2(sum(x["wht"] or 0 for x in ls)),
            "lines": ls[:200], "order_fees": est, "checked": dict(chk) if chk else None}


# ---------------- 平台状态卡片 ----------------
def _ops_lazada_status():
    """运营分析模块的 Lazada 财务流水同步状态 [{shop, last_ok, last_try, error, hint}]；模块关着返回 None。"""
    from core import modules
    if not modules.enabled("ops"):
        return None
    try:
        from modules.ops import lazada as olz
        return [s for s in olz.status() if s["kind"] == "finance"]
    except Exception:  # noqa: BLE001
        return None


def platform_status(cfg=None):
    """顶部每个平台一张卡片：Lazada 有对接店铺 = 接口自动；Shopee / TikTok = 要导入表格（多久没导入）。"""
    _ensure()
    from core.config import load_config
    cfg = cfg or load_config()
    remind = int(float(cfg.get("fin_import_remind_days") or 14))
    c = db.conn()
    now = time.time()
    out = []
    for p in PLATFORMS:
        last_imp = c.execute("SELECT MAX(created_at) FROM fin_settle_batches WHERE platform=? AND COALESCE(mapping,'') NOT LIKE '%\"api\"%'",
                             (p,)).fetchone()[0]
        recent = c.execute("SELECT COUNT(*) FROM orders WHERE platform=? AND order_time>=?", (p, now - 60 * 86400)).fetchone()[0]
        d = {"platform": p, "mode": "import", "last_import": last_imp,
             "import_days": int((now - last_imp) // 86400) if last_imp else None, "orders_60d": recent, "remind_days": remind}
        if p == "lazada" and lazada_shops():
            ops = _ops_lazada_status()
            pay = [dict(r) for r in c.execute("SELECT * FROM fin_sync_state WHERE platform='lazada' AND kind='payout'")]
            every = 0.0
            try:
                every = float(cfg.get("oa_lz_sync_min") or 0)
            except (TypeError, ValueError):
                pass
            if ops is not None:
                last_ok = max((s["last_ok"] or 0 for s in ops), default=0) or None
                last_try = max((s["last_try"] or 0 for s in ops), default=0) or None
                d.update(mode="api", shops=[s["shop"] for s in ops], last_ok=last_ok,
                         next_at=(max(last_try or 0, now - 1) + every * 60) if every > 0 and last_try else (now + 120 if every > 0 else None),
                         every_min=every, errors=[{"shop": s["shop"], "error": s["error"], "hint": s["hint"], "hint_th": s.get("hint_th") or ""}
                                                  for s in ops if s["error"]])
            else:
                d.update(mode="import", ops_off=True)
            d["payout"] = {"last_ok": max((x["last_ok"] or 0 for x in pay), default=0) or None,
                           "errors": [{"shop": x["shop"], "error": x["error"], "hint": _hint(x["error"])} for x in pay if x["error"]],
                           "count": c.execute("SELECT COUNT(*) FROM fin_payouts WHERE platform='lazada'").fetchone()[0]}
        d["stale"] = d["mode"] == "import" and recent > 0 and (last_imp is None or d["import_days"] > remind)
        out.append(d)
    return out


def todo(add):
    """今日待办：Shopee / TikTok（或没对接的 Lazada）超过 N 天没导入结算报表。"""
    names = {"lazada": "Lazada", "shopee": "Shopee", "tiktok": "TikTok"}
    for s in platform_status():
        if not s["stale"]:
            continue
        nm = names[s["platform"]]
        last = dt.date.fromtimestamp(s["last_import"]).isoformat() if s["last_import"] else "never"
        if s["last_import"]:
            title, th = f"{nm} 结算报表 {s['import_days']} 天没导入了", f"ไม่ได้นำเข้ารายงานการชำระเงิน {nm} มา {s['import_days']} วัน"
        else:
            title, th = f"{nm} 还没导入过结算报表", f"ยังไม่เคยนำเข้ารายงานการชำระเงิน {nm}"
        add(f"fin_import:{s['platform']}:{last}", "财务", "warn", title,
            "到「财务 → 平台对账」导入平台后台导出的收入 / 结算报表，才知道哪些订单钱到了、扣费对不对。", tab="fin_settle", roles="owner",
            th=(th, "ไปที่「การเงิน → กระทบยอดแพลตฟอร์ม」นำเข้ารายงานรายได้/การชำระเงินจากหลังร้าน เพื่อดูว่าเงินเข้าครบและค่าธรรมเนียมถูกต้อง"))


# ---------------- 对账页 ----------------
def reconcile(start, end, platform=""):
    """对账（按下单日期的期间；platform 空 = 全部）。返回：
       total     数字卡片：receivable 应收（已发货订单金额）、arrived 已到账、fees 平台实际扣费（fee_rate 实际 % / cfg_rate 设置的 %）、
                 pending 待回款（预计）、issues 异常单数（不算已核对的）；以及旧字段 orders / settled / net / unpaid_amount / diff_amount / adjustments
       rows      每单（已发货 / 有结算的）：state、issue、source、到账、扣费、checked …
       diff      扣费比预计多      unpaid  超时未回款      unsettled  系统有但平台没结算      unknown  平台有但系统没有
       settled   有结算记录的（旧字段）"""
    from core.config import load_config
    from core.finance import EXCLUDE
    from .settle import key, sync_pending
    _ensure()
    cfg = load_config()
    st = settings(cfg)
    sync_pending()
    c = db.conn()
    s_ts, e_ts = ts(start), ts(end)
    sql = (f"SELECT id, platform, shop, order_no, status, order_time, order_total, settlement FROM orders WHERE order_time>=? AND order_time<? "
           f"AND status NOT IN ({','.join('?' * len(EXCLUDE))}) AND COALESCE(platform,'') NOT IN ('manual','')")
    args = [s_ts, e_ts, *EXCLUDE]
    if platform:
        sql += " AND platform=?"
        args.append(platform)
    orders = c.execute(sql + " ORDER BY order_time DESC", args).fetchall()
    cls = classify(orders, cfg)
    chk = _checked()
    rows = []
    tot = {"orders": 0, "settled": 0, "revenue": 0.0, "net": 0.0, "fees": 0.0, "unpaid_amount": 0.0, "diff_amount": 0.0,
           "receivable": 0.0, "arrived": 0.0, "pending": 0.0, "settled_amount": 0.0}
    counts = {k: 0 for k in STATE_ZH}
    for o in orders:
        r = cls.get(o["id"])
        if not r or r["state"] == "open":
            continue
        row = {"id": o["id"], "platform": o["platform"], "shop": o["shop"] or "", "order_no": o["order_no"], "status": o["status"],
               "day": day_of(o["order_time"]) if o["order_time"] else "", **r}
        ck = chk.get((o["platform"], r["key"]))
        row["checked"] = ck
        rows.append(row)
        counts[r["state"]] += 1
        tot["orders"] += 1
        tot["receivable"] += r["revenue"]
        if r["net"] is not None:
            tot["settled"] += 1
            tot["revenue"] += r["revenue"]
            tot["net"] += r["net"]
            tot["fees"] += r["fee"]
        if r["state"] == "paid":
            tot["arrived"] += r["net"]
        else:
            tot["pending"] += r["net"] if r["net"] is not None else r["expected"]
            if r["state"] == "settled":
                tot["settled_amount"] += r["net"] or 0
        if r["state"] in ("overdue", "unsettled") and not ck:
            tot["unpaid_amount"] += r["net"] if r["net"] is not None else r["revenue"]
        if r["issue"] == "diff" and not ck:
            tot["diff_amount"] += r["diff"]
    diff = sorted([x for x in rows if x["issue"] == "diff"], key=lambda x: (bool(x["checked"]), -x["diff"]))
    unpaid = sorted([x for x in rows if x["state"] == "overdue"], key=lambda x: (bool(x["checked"]), -x["days"]))
    unsettled = sorted([x for x in rows if x["state"] == "unsettled"], key=lambda x: (bool(x["checked"]), -x["days"]))
    known = {}
    for o in c.execute("SELECT platform, order_no FROM orders"):
        known.setdefault(o["platform"], set()).add(key(o["order_no"]))
    unknown = []
    q2, a2 = "", []
    if platform:
        q2, a2 = " AND platform=?", [platform]
    for r in c.execute("SELECT platform, shop, order_no, order_key, SUM(amount) a, MAX(day) d, MAX(row_hash) h FROM fin_settle_lines "
                       f"WHERE COALESCE(order_key,'')!='' AND day>=? AND day<?{q2} GROUP BY platform, order_key",
                       (start.isoformat(), end.isoformat(), *a2)):
        if r["order_key"] not in known.get(r["platform"], set()):
            unknown.append({"platform": r["platform"], "shop": r["shop"] or "", "order_no": r["order_no"], "key": r["order_key"],
                            "amount": r2(r["a"]), "day": r["d"], "source": "api" if str(r["h"] or "").startswith("api:") else "import",
                            "checked": chk.get((r["platform"], r["order_key"]))})
    unknown.sort(key=lambda x: (bool(x["checked"]), x["day"] or ""))
    adj = c.execute(f"SELECT COALESCE(SUM(amount),0) a FROM fin_settle_lines WHERE COALESCE(order_key,'')='' AND day>=? AND day<?{q2}",
                    (start.isoformat(), end.isoformat(), *a2)).fetchone()["a"]
    tot = {k: (r2(v) if isinstance(v, float) else v) for k, v in tot.items()}
    tot["fee_rate"] = round(tot["fees"] / tot["revenue"] * 100, 1) if tot["revenue"] else None
    tot["cfg_rate"] = round(_cfg_rate(cfg, platform or "lazada") * 100, 1)
    tot["adjustments"] = r2(adj)
    tot["issues"] = len({x["id"] for x in diff + unpaid + unsettled if not x["checked"]}) + sum(1 for x in unknown if not x["checked"])
    tot["issue_counts"] = {"diff": sum(1 for x in diff if not x["checked"]), "unpaid": sum(1 for x in unpaid if not x["checked"]),
                           "unsettled": sum(1 for x in unsettled if not x["checked"]), "unknown": sum(1 for x in unknown if not x["checked"])}
    settled = [x for x in rows if x["net"] is not None]
    return {"total": tot, "counts": counts, "rows": rows[:800], "settled": settled[:500], "diff": diff[:300], "unpaid": unpaid[:300],
            "unsettled": unsettled[:300], "unknown": unknown[:300], "platform": platform or "",
            "settings": {"days": st["settle_days"], "tolerance": st["tolerance"]}, "state_zh": STATE_ZH, "state_th": STATE_TH,
            "source_zh": SOURCE_ZH}


# ---------------- 后台：每小时拉一次结算单 ----------------
_started = False


def _loop():
    time.sleep(150)
    while True:
        try:
            from core import modules
            from core.config import load_config
            every = float(load_config().get("oa_lz_sync_min") or 60) or 60
            if modules.enabled("fin") and lazada_shops():
                sync_payouts()
        except Exception as e:  # noqa: BLE001
            print("Lazada 结算单同步失败：", e)
            every = 60
        finally:
            db.release()
        time.sleep(max(30, every) * 60)


def start():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="fin-payouts").start()
