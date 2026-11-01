"""平台费率引擎（v2.53）：用平台结算流水算「真实费率」，定价 / 成本 / 利润估算都从这里取，不再只用一个固定扣点。

数据来源（适配器，每个平台一个，以后 Shopee 有接口了只要注册一个新适配器）：
  lazada  运营模块拉的财务流水（oa_lz_tx；没有就看财务模块里导入的 Lazada 对账单）
  shopee  财务模块「平台对账」导入的结算报表（fin_settle_lines）
费用项（5 类）：commission 佣金 · payment 支付手续费 · shipping 运费差额 · campaign 活动 / 优惠券分担 · other 其他。
每一项分「按商品金额的百分比」和「每件固定金额」两种（运费、固定手续费按件摊）。
算出来按 店铺 × 类目 × 近 30 / 90 天 存快照（fee_rate_snap，带样本订单数）。

取费率（resolve）的顺序：店铺×类目（样本 ≥ N 单，N=设置 fee_min_orders，默认 10）→ 店铺整体 → 用户默认值
（类目默认 → 平台默认；平台默认就是旧设置 platform_fee_rate / shopee_fee_rate，迁移时原值保留）。每个结果标 source = actual（实际）/ default（默认）。
"""
import json
import math
import re
import threading
import time
import datetime as dt

from . import db

ITEMS = ("commission", "payment", "shipping", "campaign", "other")
ITEM_LABEL = {
    "commission": ("佣金", "ค่าคอมมิชชั่น"), "payment": ("支付手续费", "ค่าธรรมเนียมการชำระเงิน"),
    "shipping": ("运费差额", "ส่วนต่างค่าจัดส่ง"), "campaign": ("活动 / 优惠券分担", "แคมเปญ/คูปองที่ร้านรับผิดชอบ"),
    "other": ("其他费用", "ค่าธรรมเนียมอื่นๆ"), "default": ("默认扣点", "อัตราค่าธรรมเนียมเริ่มต้น"),
}
SOURCE_LABEL = {"actual": ("实际", "จริง"), "default": ("默认", "ค่าเริ่มต้น")}
PCT_ONLY = ("commission", "payment")
FIXED_ONLY = ("shipping",)
CHANGE_PP = 0.005                    # 费率项变化超过 0.5 个百分点 → 提醒
WINDOWS = (30, 90)
SHOPEE_REMIND_DAYS = 7
MAX_PCT = 0.8                        # 实际算出来的百分比费率上限（超过 = 数据有问题，忽略）
MAX_FIXED = 500.0                    # 每件固定费用上限（泰铢）
UNKNOWN_CAT = "-"
SHOP_LEVEL = "*"
PLATFORMS = ("lazada", "shopee")

SCHEMA = """
CREATE TABLE IF NOT EXISTS fee_rate_snap (
  platform TEXT, shop TEXT, category TEXT, win INTEGER, cat_label TEXT, items TEXT, pct REAL, fixed REAL,
  orders INTEGER, units REAL, item_amount REAL, updated_at REAL, PRIMARY KEY(platform, shop, category, win)
);
CREATE TABLE IF NOT EXISTS fee_rate_hist (
  day TEXT, platform TEXT, shop TEXT, category TEXT, win INTEGER, pct REAL, fixed REAL, orders INTEGER,
  PRIMARY KEY(day, platform, shop, category, win)
);
CREATE TABLE IF NOT EXISTS fee_defaults (
  platform TEXT, category TEXT, rate REAL, cat_label TEXT, updated_at REAL, PRIMARY KEY(platform, category)
);
CREATE TABLE IF NOT EXISTS fee_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT, shop TEXT, item TEXT, old REAL, new REAL, at REAL, status TEXT DEFAULT 'open'
);
"""
_inited = set()
_lock = threading.Lock()
_ver = [0]
_cache = {"key": None, "at": 0, "snaps": {}, "defaults": {}, "shops": {}}


def init():
    if db.DB_PATH in _inited:
        return
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()
    _inited.add(db.DB_PATH)


def invalidate():
    _ver[0] += 1
    _cache["key"] = None


def _has_table(name):
    return bool(db.conn().execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())


# ---------------- 费用名 → 费用项 ----------------
_SKIP = ("withholding", "vat", "tax", "ภาษี", "代扣", "增值税", "refund", "reversal", "penalty", "fine", "คืนเงิน", "ค่าปรับ", "退款", "罚", "冲回")
_NET = ("settlement", "payout", "released", "到账")
_CAMPAIGN = ("free shipping max", "voucher", "promotion", "promotional", "campaign", "lazcoin", "flexi", "bundle", "coupon", "discount",
             "sponsored", "program", "คูปอง", "โปรโมชั่น", "แคมเปญ", "ส่วนลด", "优惠", "活动", "促销", "广告", "包邮计划")
_SHIP = ("shipping", "delivery", "logistic", "freight", "ค่าส่ง", "ค่าจัดส่ง", "运费", "物流")


def item_of(name, is_item=0):
    """费用名 → 费用项；None = 不算平台费用（商品金额、退款、罚款、税、只有合计的到账行）。"""
    if is_item:
        return None
    n = str(name or "").lower()
    if not n or any(w in n for w in _NET) or any(w in n for w in _SKIP) or "item price" in n:
        return None
    if "commission" in n or "คอมมิชชั่น" in n or "佣金" in n:
        return "commission"
    if "payment" in n or "transaction fee" in n or "การชำระเงิน" in n or "支付" in n or "手续费" in n:
        return "payment"
    if any(w in n for w in _CAMPAIGN):
        return "campaign"
    if any(w in n for w in _SHIP):
        return "shipping"
    return "other"


def label_of(item):
    zh, th = ITEM_LABEL.get(item, (item, item))
    return {"zh": zh, "th": th}


def fee_name_label(name):
    """原始费用名的中 / 泰文名（运营模块的 fee_label）。"""
    try:
        from modules.ops.lazada import fee_label
        return fee_label(name)
    except Exception:  # noqa: BLE001
        return {"zh": str(name or ""), "th": str(name or "")}


# ---------------- 适配器：每个平台怎么拿到结算明细 ----------------
class Adapter:
    platform = ""
    mode = "import"          # api = 接口自动；import = 导入表格

    def lines(self, since_day):
        """生成器：{shop, order_no, day, fee_name, amount, is_item, sku}。amount：平台扣费为负、商品金额为正。"""
        return iter(())

    def last_update(self):
        """最近一次拿到新数据的时间（秒）；None = 从来没有。"""
        return None


class LazadaAdapter(Adapter):
    platform, mode = "lazada", "api"

    def lines(self, since_day):
        c = db.conn()
        if _has_table("oa_lz_tx"):
            names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM shops")}
            rows = c.execute("SELECT * FROM oa_lz_tx WHERE day>=? AND COALESCE(order_no,'')!=''", (since_day,)).fetchall()
            if rows:
                for r in rows:
                    yield {"shop": names.get(r["shop_id"]) or "", "order_no": r["order_no"], "day": r["day"], "fee_name": r["fee_name"],
                           "amount": r["amount"] or 0, "is_item": r["is_item"], "sku": r["seller_sku"] or ""}
                return
        if _has_table("fin_settle_lines"):
            for r in c.execute("SELECT * FROM fin_settle_lines WHERE platform='lazada' AND day>=? AND COALESCE(order_no,'')!=''", (since_day,)):
                yield {"shop": r["shop"] or "", "order_no": r["order_no"], "day": r["day"], "fee_name": r["fee_name"], "amount": r["amount"] or 0,
                       "is_item": r["is_item"], "sku": ""}

    def last_update(self):
        c = db.conn()
        t = None
        if _has_table("oa_lz_tx"):
            t = c.execute("SELECT MAX(synced_at) FROM oa_lz_tx").fetchone()[0]
        return t


class ImportAdapter(Adapter):
    """Shopee / TikTok：财务模块导入的结算报表。以后有接口了：写一个新的 Adapter 子类，register(平台, 实例) 顶替它。"""
    mode = "import"

    def __init__(self, platform):
        self.platform = platform

    def lines(self, since_day):
        if not _has_table("fin_settle_lines"):
            return
        for r in db.conn().execute("SELECT * FROM fin_settle_lines WHERE platform=? AND day>=? AND COALESCE(order_no,'')!=''",
                                   (self.platform, since_day)):
            yield {"shop": r["shop"] or "", "order_no": r["order_no"], "day": r["day"], "fee_name": r["fee_name"], "amount": r["amount"] or 0,
                   "is_item": r["is_item"], "sku": ""}

    def last_update(self):
        if not _has_table("fin_settle_batches"):
            return None
        return db.conn().execute("SELECT MAX(created_at) FROM fin_settle_batches WHERE platform=?", (self.platform,)).fetchone()[0]


ADAPTERS = {"lazada": LazadaAdapter(), "shopee": ImportAdapter("shopee")}


def register(platform, adapter):
    ADAPTERS[platform] = adapter


# ---------------- 订单 → 类目 ----------------
def category_of(product):
    """产品的类目 → (键, 名称)。没选类目 = (UNKNOWN_CAT, "")。"""
    cat = (product or {}).get("category") or {}
    cid = str(cat.get("id") or cat.get("cat_id") or "")
    if not cid:
        return UNKNOWN_CAT, ""
    try:
        from . import categories
        label = categories.display_name(cid, "")
    except Exception:  # noqa: BLE001
        label = ""
    return cid, label or str(cat.get("name") or cid)


class _Cats:
    """订单商品 → 类目（产品文件读一次就记住）。"""

    def __init__(self):
        self.by_pid, self.by_sku, self._skus = {}, None, None

    def of_pid(self, pid):
        if pid not in self.by_pid:
            try:
                from . import store
                self.by_pid[pid] = category_of(store.load(pid))
            except Exception:  # noqa: BLE001
                self.by_pid[pid] = (UNKNOWN_CAT, "")
        return self.by_pid[pid]

    def of_sku(self, sku):
        if self.by_sku is None:
            self.by_sku = {}
            try:
                from . import store
                for it in store.list_products():
                    p = store.load(it["id"])
                    ck = category_of(p)
                    for v in p.get("variants") or []:
                        if v.get("sku"):
                            self.by_sku[str(v["sku"]).strip().upper()] = ck
            except Exception:  # noqa: BLE001
                pass
        return self.by_sku.get(str(sku or "").strip().upper(), (UNKNOWN_CAT, ""))


def _order_items(platform, nos):
    out = {}
    c = db.conn()
    nos = list(nos)
    for i in range(0, len(nos), 500):
        ch = nos[i:i + 500]
        for r in c.execute(f"SELECT o.order_no, o.shop, i.product_id, i.sku, i.qty, i.item_total, i.unit_price FROM orders o JOIN order_items i ON i.order_id=o.id "
                           f"WHERE o.platform=? AND o.order_no IN ({','.join('?' * len(ch))})", (platform, *ch)):
            q = r["qty"] or 1
            out.setdefault(r["order_no"], []).append({"pid": r["product_id"] or "", "sku": r["sku"] or "", "qty": q,
                                                      "total": r["item_total"] if r["item_total"] is not None else (r["unit_price"] or 0) * q,
                                                      "shop": r["shop"] or ""})
    return out


# ---------------- 计算 ----------------
def _cv(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    if abs(m) < 1e-12:
        return 0.0
    return math.sqrt(sum((x - m) ** 2 for x in xs) / n) / abs(m)


def derive(samples):
    """samples = [(商品金额, 件数, {费用项: 金额})] → {费用项: {pct, fixed}}。
    佣金 / 支付手续费按百分比，运费差额按件固定；活动 / 其他：金额更像「每件固定」就按件，否则按百分比（样本少于 3 单一律按百分比）。"""
    tot_i = sum(s[0] for s in samples)
    tot_u = sum(s[1] for s in samples) or 1
    out = {}
    for k in ITEMS:
        tot = sum(s[2].get(k, 0) for s in samples)
        if abs(tot) < 1e-9:
            continue
        if k in PCT_ONLY:
            fixed = False
        elif k in FIXED_ONLY:
            fixed = True
        elif len(samples) >= 3:
            fixed = _cv([s[2].get(k, 0) / max(s[1], 1e-9) for s in samples]) < _cv([s[2].get(k, 0) / max(s[0], 1e-9) for s in samples])
        else:
            fixed = False
        if fixed:
            out[k] = {"pct": 0.0, "fixed": round(tot / tot_u, 4)}
        else:
            out[k] = {"pct": round(tot / tot_i, 5) if tot_i else 0.0, "fixed": 0.0}
    return out


def compute(platform, window=30, now=None):
    """近 window 天某平台的真实费率：{(店铺, 类目): {cat_label, items, pct, fixed, orders, units, item_amount, names}}（类目 SHOP_LEVEL = 店铺整体）。"""
    ad = ADAPTERS.get(platform)
    if not ad:
        return {}
    now = now or time.time()
    since = (dt.datetime.fromtimestamp(now).date() - dt.timedelta(days=window - 1)).isoformat()
    orders = {}
    for ln in ad.lines(since):
        o = orders.setdefault((ln["shop"], str(ln["order_no"])), {"item": 0.0, "fees": {}, "names": {}, "skus": [], "n_item": 0})
        if ln.get("is_item"):
            o["item"] += float(ln["amount"] or 0)
            o["n_item"] += 1
            if ln.get("sku"):
                o["skus"].append(ln["sku"])
            continue
        k = item_of(ln.get("fee_name"), ln.get("is_item"))
        if k:
            o["fees"][k] = o["fees"].get(k, 0.0) - float(ln["amount"] or 0)
            o["names"].setdefault(k, set()).add(str(ln.get("fee_name") or ""))
    info = _order_items(platform, {no for (_s, no) in orders})
    cats = _Cats()
    groups = {}          # (shop, cat) → {"label", "samples": [], "names": {}}

    def put(shop, cat, label, item, units, fees, names):
        g = groups.setdefault((shop, cat), {"label": label, "samples": [], "names": {}})
        g["samples"].append((item, units, fees))
        for k, ns in names.items():
            g["names"].setdefault(k, set()).update(ns)

    for (shop, no), o in orders.items():
        if o["item"] <= 0:
            continue                      # 还没拉到商品金额那一行：不算（扣费会偏多）
        its = info.get(no)
        shop = shop or (its[0]["shop"] if its else "")
        units_all = sum(i["qty"] for i in its) if its else max(1, o["n_item"])
        put(shop, SHOP_LEVEL, "", o["item"], units_all, o["fees"], o["names"])
        parts = {}
        if its:
            tot = sum(max(i["total"], 0) for i in its)
            for i in its:
                ck = cats.of_pid(i["pid"]) if i["pid"] else cats.of_sku(i["sku"])
                w = (max(i["total"], 0) / tot) if tot > 0 else i["qty"] / units_all
                d = parts.setdefault(ck, [0.0, 0.0])
                d[0] += w
                d[1] += i["qty"]
        else:
            for sk in o["skus"] or [""]:
                ck = cats.of_sku(sk)
                d = parts.setdefault(ck, [0.0, 0.0])
                d[0] += 1.0 / max(1, len(o["skus"]) or 1)
                d[1] += 1
        for (ck, label), (w, u) in parts.items():
            put(shop, ck, label, o["item"] * w, u, {k: v * w for k, v in o["fees"].items()}, o["names"])
    out = {}
    for (shop, cat), g in groups.items():
        items = derive(g["samples"])
        for k, v in items.items():
            v["names"] = sorted(g["names"].get(k, ()))[:8]
        item_amt = sum(s[0] for s in g["samples"])
        units = sum(s[1] for s in g["samples"])
        out[(shop, cat)] = {"cat_label": g["label"], "items": items, "orders": len(g["samples"]), "units": round(units, 2),
                            "item_amount": round(item_amt, 2),
                            "pct": round(sum(v["pct"] for v in items.values()), 5), "fixed": round(sum(v["fixed"] for v in items.values()), 4)}
    return out


# ---------------- 快照 ----------------
def _snap_row(r):
    return {"platform": r["platform"], "shop": r["shop"], "category": r["category"], "win": r["win"], "cat_label": r["cat_label"] or "",
            "items": json.loads(r["items"] or "{}"), "pct": r["pct"], "fixed": r["fixed"], "orders": r["orders"], "units": r["units"],
            "item_amount": r["item_amount"], "updated_at": r["updated_at"]}


def min_orders(cfg=None):
    from .config import load_config
    try:
        return max(1, int((cfg or load_config()).get("fee_min_orders") or 10))
    except (TypeError, ValueError):
        return 10


def refresh(platforms=None, now=None, cfg=None):
    """重算并存快照（30 / 90 天）。费率项和上一次比变了 0.5 个百分点以上 → 记一条「费率变了」事件（待办用）。返回 {平台: 店铺×类目 数}。"""
    init()
    now = now or time.time()
    n_min = min_orders(cfg)
    day = dt.datetime.fromtimestamp(now).date().isoformat()
    c = db.conn()
    res = {}
    for plat in platforms or list(ADAPTERS):
        old = {(r["shop"], r["win"]): _snap_row(r) for r in c.execute(
            "SELECT * FROM fee_rate_snap WHERE platform=? AND category=?", (plat, SHOP_LEVEL))}
        total = 0
        for win in WINDOWS:
            data = compute(plat, win, now)
            c.execute("DELETE FROM fee_rate_snap WHERE platform=? AND win=?", (plat, win))
            for (shop, cat), g in data.items():
                c.execute("INSERT OR REPLACE INTO fee_rate_snap(platform, shop, category, win, cat_label, items, pct, fixed, orders, units, item_amount, updated_at) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (plat, shop, cat, win, g["cat_label"], json.dumps(g["items"], ensure_ascii=False), g["pct"], g["fixed"], g["orders"],
                           g["units"], g["item_amount"], now))
                if win == 30:
                    c.execute("INSERT OR REPLACE INTO fee_rate_hist(day, platform, shop, category, win, pct, fixed, orders) VALUES(?,?,?,?,?,?,?,?)",
                              (day, plat, shop, cat, win, g["pct"], g["fixed"], g["orders"]))
                total += 1
            if win == 30:
                for (shop, cat), g in data.items():
                    if cat != SHOP_LEVEL:
                        continue
                    o = old.get((shop, 30))
                    if o and o["orders"] >= n_min and g["orders"] >= n_min:
                        _detect_change(c, plat, shop, o["items"], g["items"], now)
        res[plat] = total
    c.execute("DELETE FROM fee_rate_hist WHERE day<?", ((dt.datetime.fromtimestamp(now).date() - dt.timedelta(days=200)).isoformat(),))
    c.commit()
    invalidate()
    return res


def _detect_change(c, plat, shop, old_items, new_items, now):
    for k in ITEMS:
        a = (old_items.get(k) or {}).get("pct", 0.0)
        b = (new_items.get(k) or {}).get("pct", 0.0)
        if abs(b - a) > CHANGE_PP + 1e-9:
            r = c.execute("SELECT id FROM fee_events WHERE platform=? AND shop=? AND item=? AND status='open'", (plat, shop, k)).fetchone()
            if r:
                c.execute("UPDATE fee_events SET new=?, at=? WHERE id=?", (b, now, r["id"]))
            else:
                c.execute("INSERT INTO fee_events(platform, shop, item, old, new, at, status) VALUES(?,?,?,?,?,?,'open')", (plat, shop, k, a, b, now))


def after_import(platform):
    """财务模块导入结算报表之后调一下（只重算这个平台，出错不影响导入）。"""
    try:
        if platform in ADAPTERS and ADAPTERS[platform].mode == "import":
            refresh([platform])
    except Exception:  # noqa: BLE001
        pass


def events(status="open"):
    init()
    return [dict(r) for r in db.conn().execute("SELECT * FROM fee_events WHERE status=? ORDER BY at DESC", (status,))]


def ack_events(platform=None, shop=None, ids=None):
    init()
    c = db.conn()
    q, a = "UPDATE fee_events SET status='done' WHERE status='open'", []
    if ids:
        q += f" AND id IN ({','.join('?' * len(ids))})"
        a += list(ids)
    if platform:
        q += " AND platform=?"
        a.append(platform)
    if shop is not None:
        q += " AND shop=?"
        a.append(shop)
    n = c.execute(q, a).rowcount
    c.commit()
    return n


# ---------------- 默认费率（用户设置，可改）----------------
def platform_default(cfg, platform):
    """平台默认扣点 = 旧设置：Lazada platform_fee_rate；Shopee shopee_fee_rate（0 = 和 Lazada 一样）。"""
    base = float((cfg or {}).get("platform_fee_rate") or 0)
    if platform == "shopee":
        sp = float((cfg or {}).get("shopee_fee_rate") or 0)
        return sp if sp > 0 else base
    return base


def set_platform_default(platform, rate):
    from .config import load_config, save_config
    rate = float(rate)
    if not 0 <= rate < 0.9:
        raise ValueError("扣点要在 0 ~ 90% 之间")
    key = "shopee_fee_rate" if platform == "shopee" else "platform_fee_rate"
    save_config({key: rate})
    invalidate()
    return load_config().get(key)


def set_category_default(platform, category, rate, label=""):
    init()
    if not category or category in (SHOP_LEVEL,):
        raise ValueError("请选类目")
    if rate in (None, ""):
        db.conn().execute("DELETE FROM fee_defaults WHERE platform=? AND category=?", (platform, str(category)))
    else:
        rate = float(rate)
        if not 0 <= rate < 0.9:
            raise ValueError("扣点要在 0 ~ 90% 之间")
        db.conn().execute("INSERT OR REPLACE INTO fee_defaults(platform, category, rate, cat_label, updated_at) VALUES(?,?,?,?,?)",
                          (platform, str(category), rate, label or "", time.time()))
    db.conn().commit()
    invalidate()


def migrate_defaults(cfg=None):
    """旧设置迁移：platform_fee_rate / shopee_fee_rate 原值保留，成为各平台的默认（不用复制，页面直接读它们）。返回当前各平台默认。"""
    from .config import load_config
    cfg = cfg or load_config()
    return {p: platform_default(cfg, p) for p in PLATFORMS}


# ---------------- 取费率 ----------------
def _load():
    key = (db.DB_PATH, _ver[0])
    if _cache["key"] == key and time.time() - _cache["at"] < 30:
        return _cache
    init()
    c = db.conn()
    snaps = {}
    for r in c.execute("SELECT * FROM fee_rate_snap"):
        snaps[(r["platform"], r["shop"], r["category"], r["win"])] = _snap_row(r)
    defaults = {(r["platform"], r["category"]): r["rate"] for r in c.execute("SELECT * FROM fee_defaults")}
    shops = {}
    for r in c.execute("SELECT id, platform, name FROM shops WHERE enabled=1 ORDER BY id"):
        shops.setdefault(r["platform"], []).append(r["name"])
    _cache.update(key=key, at=time.time(), snaps=snaps, defaults=defaults, shops=shops)
    return _cache


def _pack(platform, shop, category, items, source, level, orders, window, updated_at, pct=None, fixed=None):
    rows = []
    for k, v in items.items():
        lb = label_of(k)
        rows.append({"key": k, "zh": lb["zh"], "th": lb["th"], "pct": v.get("pct", 0.0), "fixed": v.get("fixed", 0.0), "names": v.get("names") or []})
    rows.sort(key=lambda r: (ITEMS.index(r["key"]) if r["key"] in ITEMS else 99))
    sl = SOURCE_LABEL[source]
    return {"platform": platform, "shop": shop, "category": category, "items": rows,
            "pct": round(sum(r["pct"] for r in rows), 5) if pct is None else pct, "fixed": round(sum(r["fixed"] for r in rows), 4) if fixed is None else fixed,
            "source": source, "source_zh": sl[0], "source_th": sl[1], "level": level, "orders": orders, "window": window, "updated_at": updated_at}


def default_shop(platform):
    sh = _load()["shops"].get(platform) or []
    return sh[0] if sh else ""


def rate_ok(pct, fixed):
    """算出来的实际费率是否可信：0 ≤ 百分比 ≤ 80%，0 ≤ 每件固定费用 ≤ 500 泰铢，且不是 NaN。"""
    try:
        pct, fixed = float(pct or 0), float(fixed or 0)
    except (TypeError, ValueError):
        return False
    if pct != pct or fixed != fixed:
        return False
    return 0 <= pct <= MAX_PCT and 0 <= fixed <= MAX_FIXED


def bad_snaps():
    """样本够用、但费率异常（会被 resolve 忽略）的快照：[{platform, shop, category, win, pct, fixed}]，给待办警告用。"""
    from .config import load_config
    try:
        L = _load()
        n_min = min_orders(load_config())
    except Exception:  # noqa: BLE001
        return []
    out = []
    for (plat, shop, cat, win), s in L["snaps"].items():
        if s["orders"] >= n_min and (s["pct"] or s["fixed"]) and not rate_ok(s["pct"], s["fixed"]):
            out.append({"platform": plat, "shop": shop, "category": cat, "win": win, "pct": s["pct"], "fixed": s["fixed"]})
    return out


def resolve(platform=None, shop=None, category=None, cfg=None):
    """某平台 / 店铺 / 类目的费率。shop 不给 = 平台第一个启用的店铺；没有真实数据 → 默认值。永远返回一个可用的费率。"""
    from .config import load_config
    cfg = cfg or load_config()
    platform = (platform or "lazada").lower()
    try:
        L = _load()
    except Exception:  # noqa: BLE001  数据库没准备好（纯计算的单元测试）
        L = {"snaps": {}, "defaults": {}, "shops": {}}
    shop = shop if shop else ((L["shops"].get(platform) or [""])[0])
    cat = str(category) if category not in (None, "") else ""
    n_min = min_orders(cfg)
    for shop_try in ([shop] if shop else []):
        for level, ck in (("category", cat), ("shop", SHOP_LEVEL)):
            if level == "category" and (not cat or cat == UNKNOWN_CAT):
                continue
            for win in WINDOWS:
                s = L["snaps"].get((platform, shop_try, ck, win))
                if s and s["orders"] >= n_min and (s["pct"] or s["fixed"]):
                    if not rate_ok(s["pct"], s["fixed"]):     # 结算数据异常（负数 / 超过 80% / 固定费用离谱）→ 忽略这条，往下走，最后用默认值
                        continue
                    return _pack(platform, shop_try, cat, s["items"], "actual", level, s["orders"], win, s["updated_at"], s["pct"], s["fixed"])
    d = L["defaults"].get((platform, cat)) if cat else None
    level = "category_default"
    if d is None:
        d, level = platform_default(cfg, platform), "default"
    try:
        d = float(d)
        if not 0 <= d <= MAX_PCT:
            d = min(max(d, 0.0), MAX_PCT) if d == d else 0.0
    except (TypeError, ValueError):
        d = 0.0
    return _pack(platform, shop, cat, {"default": {"pct": float(d), "fixed": 0.0}}, "default", level, 0, 0, None)


def fee_of(rate, price):
    """某个售价上的费用：{total, items: [{key, zh, th, pct, fixed, amount}]}。"""
    items, tot = [], 0.0
    for r in rate["items"]:
        amt = price * r["pct"] + r["fixed"]
        tot += amt
        items.append({"key": r["key"], "zh": r["zh"], "th": r["th"], "pct": r["pct"], "fixed": r["fixed"], "amount": round(amt, 2)})
    return {"total": round(tot, 2), "items": items}


def breakdown(rate, price):
    """给定价结果用的费用明细（带来源、有效费率）。"""
    f = fee_of(rate, price)
    f.update(source=rate["source"], source_zh=rate["source_zh"], source_th=rate["source_th"], level=rate["level"], orders=rate["orders"],
             shop=rate["shop"], platform=rate["platform"], pct=rate["pct"], fixed=rate["fixed"],
             eff_rate=round(f["total"] / price, 4) if price else rate["pct"])
    return f


def price_for(cost, markup, rate):
    """成本加价后的含费用售价（未取整）：(成本×(1+加价)+每件固定) ÷ (1−百分比)。"""
    try:
        pct = min(max(float(rate.get("pct") or 0), 0.0), MAX_PCT)
        fixed = min(max(float(rate.get("fixed") or 0), 0.0), MAX_FIXED)
        v = (float(cost) * (1 + float(markup)) + fixed) / (1 - pct)
        return v if math.isfinite(v) else 0.0
    except Exception:  # noqa: BLE001  坏数据不能让整个定价崩掉
        return 0.0


def estimate_order_fee(cfg, platform, shop, items, revenue):
    """订单没有真实结算时估算平台费用：每件商品按它类目的费率；全是默认费率就按 订单金额 × 默认扣点（和以前一样）。"""
    r0 = resolve(platform, shop, None, cfg)
    cs = _Cats()
    parts, any_actual = [], r0["source"] == "actual"
    for i in items or []:
        try:
            pid = i["product_id"] if "product_id" in i.keys() else ""
            sku = i["sku"] if "sku" in i.keys() else ""
            ck = cs.of_pid(pid) if pid else cs.of_sku(sku)
            r = resolve(platform, shop, ck[0], cfg)
            tot = i["item_total"] if i["item_total"] is not None else (i["unit_price"] or 0) * (i["qty"] or 1)
            parts.append((r, tot or 0, i["qty"] or 1))
            any_actual = any_actual or r["source"] == "actual"
        except Exception:  # noqa: BLE001
            continue
    if not any_actual or not parts:
        return revenue * r0["pct"] + (r0["fixed"] * sum(p[2] for p in parts) if parts else 0), r0["source"]
    base = sum(p[1] for p in parts) or 1
    fee = sum(r["pct"] * t + r["fixed"] * q for r, t, q in parts)
    return fee * (revenue / base if revenue else 1) if revenue and base else fee, "actual"


# ---------------- 受影响的产品 / 低于成本 ----------------
def below_cost(cfg, product, platform, shop, live_prices=None):
    """这个店铺里售价扣掉费用后低于成本的变体：[{sku, price, cost, fee, profit, live}]。live_prices = {SKU: 平台上正在卖的价}，没有就看 ERP 售价。"""
    from . import pricing
    out = []
    rows = pricing.price_product(cfg, product, platform=platform, shop=shop)
    rate_cat = category_of(product)[0]
    rate = resolve(platform, shop, rate_cat, cfg)
    for v, pr in zip(product.get("variants") or [], rows):
        sku = str(v.get("sku") or "").upper()
        live = (live_prices or {}).get(sku)
        price = float(live) if live else pr["final_price"]
        fee = fee_of(rate, price)["total"]
        profit = price - fee - pr["cost"]["total"]
        if pr["cost"]["total"] > 0 and profit < 0:
            out.append({"sku": sku, "price": price, "cost": pr["cost"]["total"], "fee": round(fee, 2), "profit": round(profit, 2), "live": bool(live)})
    return out


def affected_products(cfg, platform, shop, limit=None):
    """按当前费率，哪些产品的利润（加价率）低于最低要求：[{id, name, variants:[…], below_cost}]。看全部产品（limit 只给调用方想截断时用）。"""
    from . import store, pricing
    out = []
    mm = float(cfg.get("min_markup") or 0)
    items = store.list_products()
    if limit:
        items = items[:limit]
    for it in items:
        try:
            p = store.load(it["id"])
            if not p.get("variants"):
                continue
            rows = pricing.price_product(cfg, p, platform=platform, shop=shop)
        except Exception:  # noqa: BLE001
            continue
        bad = []
        for i, (v, pr) in enumerate(zip(p.get("variants") or [], rows)):
            if pr["cost"]["total"] > 0 and pr.get("actual_markup") is not None and pr["actual_markup"] < mm - 1e-9 and not pr.get("warning", "").startswith("缺少"):
                bad.append({"idx": i, "sku": v.get("sku") or "", "price": pr["final_price"], "suggested": pr["suggested_price"], "markup": pr["actual_markup"],
                            "manual": v.get("manual_price") not in (None, "", 0), "profit": pr["profit"]})
        if bad:
            out.append({"id": p["id"], "name": p.get("name_zh") or p["id"], "variants": bad, "below_cost": any(b["profit"] < 0 for b in bad)})
    return out


def _listed_platforms(p, online):
    """这个产品挂在哪些平台（上架记录 / 在线商品）。"""
    from . import listing
    out = set()
    for pf in PLATFORMS:
        try:
            if (listing.status_of(p, pf).get("status") or "none") not in ("none", ""):
                out.add(pf)
        except Exception:  # noqa: BLE001
            pass
    for o in online.get(p["id"], []) or []:
        if o.get("platform") in PLATFORMS and o.get("status") not in ("deleted", "inactive"):
            out.add(o["platform"])
    return out


def _online_map():
    try:
        from . import modules as _mods
        pub = _mods.public("listing")
        return pub.online_shops() if pub else {}
    except Exception:  # noqa: BLE001
        return {}


def recalc_plan(cfg, platform, shop, ids=None):
    """「按新费率重算建议价」会改什么（确认框和真正执行用同一份）：
    只看有手动价、且在这个店铺的新费率下加价率低于最低要求的变体。手动价是所有平台共用的一个数：
    产品只挂在这个平台 → 清掉手动价（回到建议价，可撤销）；还挂在别的平台 → 不动手动价，只标「要改价」让人自己定。"""
    from . import store
    aff = affected_products(cfg, platform, shop)
    if ids:
        aff = [a for a in aff if a["id"] in set(ids)]
    online = _online_map()
    out = []
    for a in aff:
        man = [b for b in a["variants"] if b["manual"]]
        if not man:
            continue
        try:
            p = store.load(a["id"])
        except (FileNotFoundError, ValueError):
            continue
        others = sorted(_listed_platforms(p, online) - {platform})
        out.append({"id": a["id"], "name": a["name"], "action": "mark" if others else "clear", "also_on": others,
                    "variants": [{"idx": b["idx"], "sku": b["sku"], "manual_price": (p["variants"][b["idx"]] or {}).get("manual_price"),
                                  "suggested": b["suggested"], "markup": b["markup"]} for b in man]})
    return out


def _init_recalc_log():
    db.conn().execute("CREATE TABLE IF NOT EXISTS fee_recalc_log (id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT, pid TEXT, idx INTEGER, sku TEXT, "
                      "old_price REAL, platform TEXT, shop TEXT, who TEXT, at REAL, undone REAL)")


def recalc_suggested(cfg, platform, shop, ids=None, user=""):
    """「按新费率重算建议价」：见 recalc_plan。清手动价前存 manual_price_prev（+谁 / 何时）、写 fee_recalc_log 和审计，整批可撤销。
    返回 {products, variants, cleared, marked, batch, ids}。"""
    from . import store, prodgroups
    init()
    _init_recalc_log()
    plan = recalc_plan(cfg, platform, shop, ids)
    batch = f"rc{int(time.time() * 1000)}"
    now = time.time()
    nv, cleared, marked = 0, [], []
    c = db.conn()
    for a in plan:
        if a["action"] == "mark":
            marked.append(a["id"])
            continue
        p = store.load(a["id"])
        changed = False
        for b in a["variants"]:
            v = p["variants"][b["idx"]]
            if v.get("manual_price") in (None, "", 0):
                continue
            v["manual_price_prev"] = v["manual_price"]
            v["manual_price_prev_by"] = user
            v["manual_price_prev_at"] = now
            v["manual_price_prev_batch"] = batch
            c.execute("INSERT INTO fee_recalc_log(batch, pid, idx, sku, old_price, platform, shop, who, at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (batch, a["id"], b["idx"], v.get("sku") or "", float(v["manual_price"]), platform, shop or "", user, now))
            v["manual_price"] = None
            nv += 1
            changed = True
        if changed:
            store.save(p)
            cleared.append(a["id"])
    c.commit()
    done = cleared + marked
    if nv or marked:
        db.audit(user, "财务·按新费率重算建议价", f"{platform}/{shop or '全部'}", f"批次 {batch}：清手动价 {nv} 个变体（{len(cleared)} 产品），只标要改价 {len(marked)} 产品")
    try:
        prodgroups.set_mark(done, "price", True, note="平台费率调整" + ("，手动价已清（可在财务·平台费率撤销）" if cleared else "，手动价是各平台共用的，请自己确认新价"), user=user, scope="wb")
    except Exception:  # noqa: BLE001
        pass
    ack_events(platform, shop)
    return {"products": len(done), "variants": nv, "cleared": cleared, "marked": marked, "batch": batch if nv else "", "ids": done}


def recalc_undo(batch, user=""):
    """撤销一批「重算建议价」：把 manual_price_prev 放回 manual_price（这个变体现在没有手动价才放回，已经被人重新定价的不覆盖）。"""
    from . import store
    init()
    _init_recalc_log()
    c = db.conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM fee_recalc_log WHERE batch=? AND undone IS NULL", (batch,))]
    n, skipped = 0, 0
    for r in rows:
        try:
            p = store.load(r["pid"])
            v = p["variants"][r["idx"]]
        except (FileNotFoundError, ValueError, IndexError, KeyError):
            skipped += 1
            continue
        if v.get("manual_price") in (None, "", 0):
            v["manual_price"] = v.get("manual_price_prev") if v.get("manual_price_prev") not in (None, "") else r["old_price"]
            n += 1
        else:
            skipped += 1
        for k in ("manual_price_prev", "manual_price_prev_by", "manual_price_prev_at", "manual_price_prev_batch"):
            v.pop(k, None)
        store.save(p)
        c.execute("UPDATE fee_recalc_log SET undone=? WHERE id=?", (time.time(), r["id"]))
    c.commit()
    if rows:
        db.audit(user, "财务·撤销重算建议价", batch, f"恢复 {n} 个变体手动价，跳过 {skipped}")
    return {"restored": n, "skipped": skipped}


def recalc_batches(limit=5):
    """最近还没撤销的重算批次（页面上显示「撤销」）。"""
    init()
    _init_recalc_log()
    out = []
    for r in db.conn().execute("SELECT batch, platform, shop, who AS by, MAX(at) at, COUNT(*) n, COUNT(DISTINCT pid) products FROM fee_recalc_log WHERE undone IS NULL "
                               "GROUP BY batch ORDER BY at DESC LIMIT ?", (limit,)):
        out.append(dict(r))
    return out


# ---------------- 页面数据 ----------------
def table(platform=None):
    """店铺 × 类目 表：每项的费率、合计、来源（实际 / 默认）、样本订单、更新时间。"""
    from .config import load_config
    cfg = load_config()
    L = _load()
    n_min = min_orders(cfg)
    rows = []
    keys = sorted({(p, s, c) for (p, s, c, _w) in L["snaps"] if (not platform or p == platform)})
    for (p, shop, cat) in keys:
        r = resolve(p, shop, None if cat == SHOP_LEVEL else cat, cfg)
        s = L["snaps"].get((p, shop, cat, 30)) or L["snaps"].get((p, shop, cat, 90))
        r90 = L["snaps"].get((p, shop, cat, 90))
        rows.append({"platform": p, "shop": shop, "category": cat, "cat_label": (s or {}).get("cat_label") or "",
                     "level": "shop_total" if cat == SHOP_LEVEL else "category",
                     "items": r["items"], "used": r["level"], "pct": r["pct"], "fixed": r["fixed"], "source": r["source"], "source_zh": r["source_zh"], "source_th": r["source_th"],
                     "orders30": (s or {}).get("orders", 0), "orders90": (r90 or {}).get("orders", 0), "enough": (s or {}).get("orders", 0) >= n_min,
                     "updated_at": (s or {}).get("updated_at")})
    return rows


def trend(days=60):
    init()
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    out = {}
    for r in db.conn().execute("SELECT * FROM fee_rate_hist WHERE category=? AND win=30 AND day>=? ORDER BY day", (SHOP_LEVEL, since)):
        out.setdefault(f"{r['platform']}|{r['shop']}", []).append({"day": r["day"], "pct": r["pct"], "fixed": r["fixed"], "orders": r["orders"]})
    return out


def import_status(platform="shopee"):
    ad = ADAPTERS.get(platform)
    last = ad.last_update() if ad else None
    days = None if not last else max(0, int((time.time() - last) // 86400))
    return {"platform": platform, "mode": ad.mode if ad else "import", "last_import": last, "days": days,
            "stale": last is None or days >= SHOPEE_REMIND_DAYS}


# ---------------- 待办 ----------------
def _shopee_active():
    c = db.conn()
    if c.execute("SELECT 1 FROM shops WHERE platform='shopee' AND enabled=1").fetchone():
        return True
    if _has_table("fin_settle_batches") and c.execute("SELECT 1 FROM fin_settle_batches WHERE platform='shopee'").fetchone():
        return True
    return bool(c.execute("SELECT 1 FROM orders WHERE platform='shopee' AND order_time>? LIMIT 1", (time.time() - 30 * 86400,)).fetchone())


def todo(add):
    from .config import load_config
    init()
    cfg = load_config()
    # 1) Shopee 没有接口：每周提醒下载 / 导入结算报表
    ad = ADAPTERS.get("shopee")
    if ad and ad.mode == "import" and _shopee_active():
        st = import_status("shopee")
        if st["stale"]:
            wk = dt.date.today().isocalendar()
            add(f"fee_shopee_import:{wk[0]}-{wk[1]}", "财务", "warn",
                "Shopee 结算报表超过 7 天没导入，费率可能不准" if st["last_import"] else "Shopee 还没导入过结算报表，费率只能用默认值",
                "到 Shopee 卖家中心 → 我的收入 → 已拨款，下载收入报表，再到「财务 → 平台对账」导入。",
                tab="fin_fees", roles="owner",
                th=("รายงานการชำระเงิน Shopee ไม่ได้นำเข้าเกิน 7 วัน อัตราค่าธรรมเนียมอาจไม่ตรง" if st["last_import"] else
                    "ยังไม่เคยนำเข้ารายงานการชำระเงิน Shopee ตอนนี้ใช้ค่าธรรมเนียมเริ่มต้น",
                    "ไปที่ Shopee Seller Centre → รายได้ของฉัน → โอนแล้ว ดาวน์โหลดรายงานรายได้ แล้วนำเข้าที่「การเงิน → กระทบยอดแพลตฟอร์ม」"))
    # 1b) 结算算出来的费率异常（负数 / 超过 80% / 固定费用离谱）：已忽略、用默认值，提醒老板查数据
    bad = bad_snaps()
    if bad:
        by = {}
        for b in bad:
            by.setdefault((b["platform"], b["shop"]), []).append(b)
        for (plat, shop), bs in by.items():
            nm = "Shopee" if plat == "shopee" else "Lazada"
            ex = bs[0]
            add(f"fee_bad:{plat}:{shop}:{int(max(x['pct'] * 1000 for x in bs))}", "财务", "warn",
                f"{nm} 结算算出来的费率不正常（{shop or '全部店铺'}），已先用默认费率",
                f"例如 {ex['pct'] * 100:.1f}% + 每件 {ex['fixed']:.1f} 泰铢（正常应在 0~{MAX_PCT * 100:.0f}%）。可能是结算报表导错 / 退款冲回，请检查「财务 → 平台费率」和导入的报表。",
                tab="fin_fees", roles="owner",
                th=(f"อัตราค่าธรรมเนียม {nm} จากการชำระเงินผิดปกติ ({shop or 'ทุกร้าน'}) ใช้ค่าเริ่มต้นไปก่อน",
                    f"เช่น {ex['pct'] * 100:.1f}% + {ex['fixed']:.1f} บาท/ชิ้น (ปกติควรอยู่ที่ 0~{MAX_PCT * 100:.0f}%) อาจนำเข้ารายงานผิดหรือมีการคืนเงิน โปรดตรวจสอบที่「การเงิน → อัตราค่าธรรมเนียมแพลตฟอร์ม」"))
    # 2) 费率变了：列出受影响产品
    groups = {}
    for e in events("open"):
        groups.setdefault((e["platform"], e["shop"]), []).append(e)
    for (plat, shop), evs in groups.items():
        nm = "Shopee" if plat == "shopee" else "Lazada"
        chg_zh = "、".join(f"{label_of(e['item'])['zh']} {e['old'] * 100:.1f}% → {e['new'] * 100:.1f}%" for e in evs)
        chg_th = ", ".join(f"{label_of(e['item'])['th']} {e['old'] * 100:.1f}% → {e['new'] * 100:.1f}%" for e in evs)
        try:
            aff = affected_products(cfg, plat, shop)
        except Exception:  # noqa: BLE001
            aff = []
        names = "、".join(a["name"] for a in aff[:5])
        key = f"fee_change:{plat}:{shop}:{int(max(e['at'] for e in evs))}"
        if plat == "shopee":
            title, th = f"Shopee 费率可能调整了（{shop or '全部店铺'}）", f"อัตราค่าธรรมเนียม Shopee อาจถูกปรับ ({shop or 'ทุกร้าน'})"
        else:
            title, th = f"{nm} 费率变了（{shop or '全部店铺'}）", f"อัตราค่าธรรมเนียม {nm} เปลี่ยน ({shop or 'ทุกร้าน'})"
        detail = f"{chg_zh}。" + (f"按新费率有 {len(aff)} 个产品利润低于最低加价率：{names}。点进来可「按新费率重算建议价」。" if aff else "目前没有产品因此低于最低加价率。")
        detail_th = f"{chg_th} " + (f"มี {len(aff)} สินค้าที่กำไรต่ำกว่าเกณฑ์ขั้นต่ำ — กด「คำนวณราคาแนะนำใหม่ตามอัตราใหม่」ในหน้านี้" if aff else "ตอนนี้ไม่มีสินค้าที่ต่ำกว่าเกณฑ์")
        add(key, "财务", "bad" if any(a["below_cost"] for a in aff) else "warn", title, detail, tab="fin_fees", roles="owner", th=(th, detail_th))
