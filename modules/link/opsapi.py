"""运营分析系统写回产品数据（对接规范 v1.1 第 6 条，B 类）。

能改：泰文标题 title_th、类目属性 attributes、售价 price（按 SKU）、上下架 active。
硬性边界（任何模式都执行）：
  - 售价不能低于该 SKU 的最低价 floor_price（最低加价率对应的价格）
  - 同一个 SKU 每天（泰国时间）最多改 1 次售价
  - 不能删除产品，只能下架（active = false）
  - 泰文标题 10–255 个字符（Lazada 限制）
模式（设置 → ops_write_mode）：
  auto     自动生效（默认，老板决定）
  confirm  只做建议：记成「待确认」，在「运营改动」页人工通过后才生效
每次写入记下改前值、改后值、原因，可以一键撤回。改完的产品在导出页显示「有修改待同步」。
"""
import datetime as dt
import json
import time

from core import db, pricing, store
from core.config import load_config

FIELDS = {"title_th": "泰文标题", "attributes": "类目属性", "price": "售价", "active": "上下架"}
STATUS_ZH = {"applied": "已生效", "pending": "待确认", "rejected": "已拒绝", "reverted": "已撤回"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, updated_at REAL, key_name TEXT,
  product_id TEXT, sku TEXT, requested TEXT, before TEXT, after TEXT,
  reason TEXT, source_action_id TEXT, status TEXT, decided_by TEXT, decided_at REAL, note TEXT, raw_before TEXT
);
CREATE INDEX IF NOT EXISTS ops_changes_upd ON ops_changes(updated_at);
CREATE INDEX IF NOT EXISTS ops_changes_sku ON ops_changes(sku, ts);
"""


class OpsError(ValueError):
    def __init__(self, msg, code="invalid", http=400):
        super().__init__(msg)
        self.code = code
        self.http = http


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    if "raw_before" not in {r[1] for r in c.execute("PRAGMA table_info(ops_changes)")}:
        c.execute("ALTER TABLE ops_changes ADD COLUMN raw_before TEXT")
    c.commit()


def mode():
    return "confirm" if (load_config().get("ops_write_mode") or "auto") == "confirm" else "auto"


# ---------------- 找产品 / SKU ----------------
def resolve(target):
    """<sku 或 product_id> → (product, variant 或 None)"""
    t = (target or "").strip()
    if not t:
        raise OpsError("没有指定产品或 SKU", "not_found", 404)
    try:
        return store.load(t), None
    except (FileNotFoundError, ValueError, OSError):
        pass
    up = t.upper()
    pid = up.split("-")[0]
    for cand in (pid, *(i["id"] for i in store.list_products())):
        try:
            p = store.load(cand)
        except (FileNotFoundError, ValueError, OSError):
            continue
        for v in p.get("variants", []):
            if (v.get("sku") or "").upper() == up:
                return p, v
    raise OpsError(f"找不到产品或 SKU：{t}", "not_found", 404)


def _floor(cfg, p, v):
    base = dict(v)
    base.pop("manual_price", None)
    return pricing.price_variant(cfg, base, p.get("markup"), p.get("material"))["floor_price"]


def _current_price(cfg, p, v):
    return pricing.price_variant(cfg, v, p.get("markup"), p.get("material"))["final_price"]


def _today_start():
    now = dt.datetime.now()
    return dt.datetime(now.year, now.month, now.day).timestamp()


# ---------------- 校验 + 计算改前 / 改后 ----------------
def _plan(p, v, changes):
    cfg = load_config()
    if not isinstance(changes, dict) or not changes:
        raise OpsError("changes 不能为空", "invalid")
    bad = [k for k in changes if k not in FIELDS]
    if bad:
        raise OpsError(f"不支持修改这些字段：{', '.join(bad)}（只能改 {', '.join(FIELDS)}）", "invalid_field")
    before, after = {}, {}
    if "title_th" in changes:
        t = str(changes["title_th"] or "").strip()
        if not 10 <= len(t) <= 255:
            raise OpsError(f"泰文标题长度要在 10–255 个字符之间（现在 {len(t)}）", "title_length")
        before["title_th"] = (p.get("copy") or {}).get("title_th", "")
        after["title_th"] = t
    if "attributes" in changes:
        a = changes["attributes"]
        if not isinstance(a, dict) or not a:
            raise OpsError("attributes 要是 {属性键: 值} 的格式", "invalid")
        cur = p.get("attributes") or {}
        before["attributes"] = {k: (cur.get(k) or {}).get("value") for k in a}
        after["attributes"] = {str(k): val for k, val in a.items()}
    if "price" in changes:
        if v is None:
            if len([x for x in p.get("variants", []) if x.get("sku")]) != 1:
                raise OpsError("这个产品有多个 SKU，改售价请用 SKU 调用（/api/v1/ops/products/<SKU>）", "sku_required")
            v = next(x for x in p["variants"] if x.get("sku"))
        try:
            price = round(float(changes["price"]), 2)
        except (TypeError, ValueError):
            raise OpsError("price 要是数字（泰铢）", "invalid")
        fl = _floor(cfg, p, v)
        if price < fl:
            raise OpsError(f"售价低于最低价 {fl}", "below_floor")
        n = db.conn().execute("SELECT COUNT(*) FROM ops_changes WHERE sku=? AND ts>=? AND status IN ('applied','pending') "
                              "AND requested LIKE '%\"price\"%'", (v["sku"], _today_start())).fetchone()[0]
        if n:
            raise OpsError(f"{v['sku']} 今天已经改过一次售价（每个 SKU 每天最多改 1 次）", "price_daily_limit")
        before["price"] = _current_price(cfg, p, v)
        before["_manual_price"] = v.get("manual_price")     # 撤回时原样恢复（没有手动价就恢复成自动定价）
        after["price"] = price
    if "active" in changes:
        before["active"] = p.get("active", True) is not False
        after["active"] = bool(changes["active"])
    return v, before, after


def _apply(p, v, after):
    if "title_th" in after:
        p.setdefault("copy", {})["title_th"] = after["title_th"]
    if "attributes" in after:
        attrs = p.setdefault("attributes", {})
        for k, val in after["attributes"].items():
            attrs[k] = {"status": "ops", "value": val}
    if "price" in after and v is not None:
        for x in p.get("variants", []):
            if x.get("sku") == v.get("sku"):
                x["manual_price"] = after["price"]
    if "active" in after:
        p["active"] = after["active"]
    _mark_unsynced(p, list(after))
    store.bump_rev(p, "运营写回")
    store.save(p)


def _restore(p, v, before):
    if "title_th" in before:
        p.setdefault("copy", {})["title_th"] = before["title_th"]
    if "attributes" in before:
        attrs = p.setdefault("attributes", {})
        for k, val in before["attributes"].items():
            if val is None:
                attrs.pop(k, None)
            else:
                attrs[k] = {"status": "manual", "value": val}
    if "price" in before and v is not None:
        for x in p.get("variants", []):
            if x.get("sku") == v.get("sku"):
                raw = before.get("_manual_price", before["price"])
                if raw in (None, "", 0):
                    x.pop("manual_price", None)
                else:
                    x["manual_price"] = raw
    if "active" in before:
        p["active"] = before["active"]
    _mark_unsynced(p, [k for k in before if not k.startswith("_")])
    store.bump_rev(p, "运营写回（撤销）")
    store.save(p)


def _mark_unsynced(p, fields):
    """已经上传到平台的产品：标成「有修改待同步」，导出页能筛出来。"""
    if not isinstance(p.get("listing"), dict):
        p["listing"] = {}
    lst = p["listing"]
    for plat in ("lazada", "shopee"):
        st = lst.get(plat) or {}
        if st.get("status") in ("uploaded", "live", "rejected", "inactive", "update"):
            if st.get("status") != "update":
                st["prev"] = st.get("status")        # 记住平台上原来的状态（在售 / 审核中 / 已下架）
            st.update(status="update", at=time.time(),
                      note="运营系统修改：" + "、".join(FIELDS.get(f, f) for f in fields))
            lst[plat] = st


def _row(r):
    d = dict(r)
    for k in ("requested", "before", "after"):
        d[k] = json.loads(d.get(k) or "{}")
    d["before"] = {k: v for k, v in d["before"].items() if not k.startswith("_")}
    d.pop("raw_before", None)
    d["status_zh"] = STATUS_ZH.get(d["status"], d["status"])
    d["applied"] = d["status"] == "applied"
    return d


def get(cid):
    r = db.conn().execute("SELECT * FROM ops_changes WHERE id=?", (cid,)).fetchone()
    return _row(r) if r else None


# ---------------- 对外动作 ----------------
def submit(target, changes, reason="", source_action_id="", key_name="api"):
    p, v = resolve(target)
    v, before, after = _plan(p, v, changes)
    m = mode()
    now = time.time()
    status = "applied" if m == "auto" else "pending"
    c = db.conn()
    cid = c.execute("""INSERT INTO ops_changes(ts, updated_at, key_name, product_id, sku, requested, before, after, reason,
                       source_action_id, status) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (now, now, key_name, p["id"], (v or {}).get("sku"), json.dumps(changes, ensure_ascii=False),
                     json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False),
                     (reason or "")[:500], str(source_action_id or "")[:80], status)).lastrowid
    c.commit()
    if status == "applied":
        _apply(p, v, after)
    db.audit(key_name, "运营写入" + ("（已生效）" if status == "applied" else "（待确认）"),
             (v or {}).get("sku") or p["id"], f"{_desc(before, after)}；原因：{reason or '-'}")
    return get(cid)


def _desc(before, after):
    out = []
    for k in after:
        b, a = before.get(k), after.get(k)
        if k == "attributes":
            out.append(f"属性 {', '.join(after[k])}")
        elif k == "title_th":
            out.append("标题")
        else:
            out.append(f"{FIELDS[k]} {b}→{a}")
    return "、".join(out)


def _load_pv(ch):
    p = store.load(ch["product_id"])
    v = next((x for x in p.get("variants", []) if ch.get("sku") and x.get("sku") == ch["sku"]), None)
    return p, v


def approve(cid, user):
    ch = get(cid)
    if not ch or ch["status"] != "pending":
        raise OpsError("这条修改不是「待确认」状态", "invalid_state", 409)
    p, v = _load_pv(ch)
    # 确认时再检查一次售价边界（期间成本可能变了）
    if "price" in ch["after"] and v is not None:
        fl = _floor(load_config(), p, v)
        if ch["after"]["price"] < fl:
            raise OpsError(f"售价低于最低价 {fl}（成本变了），不能通过", "below_floor")
    _apply(p, v, ch["after"])
    _decide(cid, "applied", user)
    db.audit(user, "通过运营修改", ch.get("sku") or ch["product_id"], _desc(ch["before"], ch["after"]))
    return get(cid)


def reject(cid, user, note=""):
    ch = get(cid)
    if not ch or ch["status"] != "pending":
        raise OpsError("这条修改不是「待确认」状态", "invalid_state", 409)
    _decide(cid, "rejected", user, note)
    db.audit(user, "拒绝运营修改", ch.get("sku") or ch["product_id"], note or "")
    return get(cid)


def revert(cid, user):
    ch = get(cid)
    if not ch:
        raise OpsError("没有这条修改记录", "not_found", 404)
    if ch["status"] == "pending":
        return reject(cid, user, "撤回")
    if ch["status"] != "applied":
        raise OpsError(f"这条修改是「{ch['status_zh']}」，不能撤回", "invalid_state", 409)
    p, v = _load_pv(ch)
    r = db.conn().execute("SELECT before FROM ops_changes WHERE id=?", (cid,)).fetchone()
    _restore(p, v, json.loads(r["before"] or "{}"))
    _decide(cid, "reverted", user)
    db.audit(user, "撤回运营修改", ch.get("sku") or ch["product_id"], _desc(ch["after"], ch["before"]))
    return get(cid)


def _decide(cid, status, user, note=""):
    c = db.conn()
    now = time.time()
    c.execute("UPDATE ops_changes SET status=?, decided_by=?, decided_at=?, updated_at=?, note=? WHERE id=?",
              (status, user, now, now, note or None, cid))
    c.commit()


def list_changes(since=0, status="", limit=200, product=""):
    conds, args = ["updated_at>=?"], [float(since or 0)]
    if status:
        conds.append("status=?"); args.append(status)
    if product:
        conds.append("(product_id LIKE ? OR sku LIKE ?)"); args += [f"%{product}%"] * 2
    sql = f"SELECT * FROM ops_changes WHERE {' AND '.join(conds)} ORDER BY id DESC LIMIT ?"
    return [_row(r) for r in db.conn().execute(sql, (*args, min(1000, int(limit or 200))))]


def counts():
    return {r["status"]: r["n"] for r in db.conn().execute("SELECT status, COUNT(*) n FROM ops_changes GROUP BY status")}
