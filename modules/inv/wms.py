"""仓库作业（v2.52，参考 BigSeller WMS）：货位上的数量、上架推荐、移库、库内补货、货位图和提醒。

  一本账     物品的总数量还是只记在物品上（inv_items.qty，单据 / 流水改它）；每个货位放了多少记在 inv_loc_qty，
             总数 − 各货位加起来 = 「待上架」（到了货还没放上货架的）。物品的「货位」（inv_items.location）= 主货位（拣货位）。
  入库       ledger.post → on_post：设置「入库自动上架」开着 → 按推荐放（放不下的留在待上架）；关着 → 全部进待上架，扫货位确认。
             采购到货（采购模块）用 putaway_batch：这次到的货按收货时填的货位放，没填的按推荐。
  出库       先扣待上架，再从货位上扣：主货位 → 拣货区 → 其它（按走路顺序）。
  推荐       同一个物品已经在的货位（有空间）→ 同分类物品附近的空货位 → 其它空货位（按区 / 货架放哪些分类）；
             只放拣货区 / 备货区 / 耗材区（成品先拣货区，其它物品先耗材区），不放暂存 / 退货 / 次品区；
             遵守容量、固定货位（只放指定的物品）、不混放（已经有别的物品就不放）、尺寸等级。
  移库       move(from, to, [{item_id, qty}])：从货位（或待上架）搬到另一个货位，检查同样的规则；记日志 inv_loc_log。
  补货       拣货区的货位设了「最低数量」：低于它 → 从备货区搬（建移库任务 inv_loc_tasks，进今日待办）。
  货位图     map_data：每个货位 空 / 有货 / 满 / 超容量，区的利用率，提醒（空货位、很久没动的货位、一个物品放太多货位）。
"""
import contextlib
import threading
import time

from core import db
from core.config import load_config

ZTYPES = {   # 区的类型
    "pick": ("拣货区", "โซนหยิบสินค้า"), "reserve": ("备货区", "โซนสต็อกสำรอง"), "staging": ("暂存区", "โซนพักสินค้า"),
    "returns": ("退货区", "โซนสินค้าคืน"), "defect": ("次品区", "โซนสินค้าชำรุด"), "supply": ("耗材区", "โซนวัสดุสิ้นเปลือง"),
    # v2.53：包材区（放包材、打包台）、生产区（每台打印机、每个 AMS 槽是一个货位，按打印机设置自动建）、待检区（刚打好等质检的成品）
    "pack": ("包材区", "โซนวัสดุแพ็ก"), "production": ("生产区", "โซนผลิต"), "qc": ("待检区", "โซนรอตรวจ")}
SIZES = {"S": ("小", "เล็ก"), "M": ("中", "กลาง"), "L": ("大", "ใหญ่"), "XL": ("特大", "ใหญ่พิเศษ")}
_SRANK = {"S": 1, "M": 2, "L": 3, "XL": 4}
PUTAWAY_TYPES = ("pick", "reserve", "supply", "pack")
OUT_LAST = ("staging", "qc", "returns", "defect", "production")      # v2.53：出库最后才扣这些区（待检 / 退货 / 次品不能当好货发）
REPL_TYPES = ("pick", "supply", "pack")       # v2.53：拣货区、耗材区、包材区的货位都可以设最低数量，低了从备货区补
EPS = 1e-9
_tl = threading.local()


def _now():
    return time.time()


def _L():
    from . import locations
    return locations


# ---------------- 基础数据 ----------------
def zinfo(c=None):
    """{区字母: {warehouse, warehouse_name, ztype, name, categories}}（没设的区：默认仓库、拣货区）"""
    c = c or db.conn()
    whs = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM inv_warehouses")}
    dflt = default_warehouse(c)
    out = {}
    for r in c.execute("SELECT * FROM inv_loc_groups WHERE kind='zone'"):
        w = r["warehouse"] or dflt
        out[r["code"]] = {"warehouse": w, "warehouse_name": whs.get(w, ""), "ztype": r["ztype"] or "pick", "name": r["name"] or ""}
    return out, whs.get(dflt, ""), dflt


def zone_of(code, c=None):
    zs, wn, dflt = zinfo(c)
    p = _L().parse(code)
    z = p[0] if p else ""
    return zs.get(z) or {"warehouse": dflt, "warehouse_name": wn, "ztype": "pick", "name": ""}


def default_warehouse(c=None):
    c = c or db.conn()
    r = c.execute("SELECT id FROM inv_warehouses ORDER BY id LIMIT 1").fetchone()
    if r:
        return r["id"]
    wid = c.execute("INSERT INTO inv_warehouses(name, note, created_at) VALUES('默认仓库', '', ?)", (_now(),)).lastrowid
    return wid


def _locs(c, active=True):
    """{id: 货位（带区的类型）}"""
    zs, wn, dflt = zinfo(c)
    out = {}
    for r in c.execute("SELECT * FROM inv_locations" + (" WHERE active=1" if active else "")):
        d = dict(r)
        z = zs.get(d["zone"]) or {"warehouse": dflt, "ztype": "pick"}
        d["ztype"], d["warehouse"] = z["ztype"], z["warehouse"]
        out[d["id"]] = d
    return out


def _qty_rows(c, item_id=None, loc_id=None):
    sql, args = "SELECT item_id, loc_id, qty FROM inv_loc_qty WHERE qty>?", [EPS]
    if item_id is not None:
        sql += " AND item_id=?"
        args.append(int(item_id))
    if loc_id is not None:
        sql += " AND loc_id=?"
        args.append(int(loc_id))
    return [dict(r) for r in c.execute(sql, args)]


def loc_qty(c, item_id, loc_id):
    r = c.execute("SELECT qty FROM inv_loc_qty WHERE item_id=? AND loc_id=?", (int(item_id), int(loc_id))).fetchone()
    return float(r["qty"] or 0) if r else 0.0


def loc_total(c, loc_id):
    return float(c.execute("SELECT COALESCE(SUM(qty),0) FROM inv_loc_qty WHERE loc_id=? AND qty>0", (int(loc_id),)).fetchone()[0] or 0)


def located(c, item_id):
    return float(c.execute("SELECT COALESCE(SUM(qty),0) FROM inv_loc_qty WHERE item_id=? AND qty>0", (int(item_id),)).fetchone()[0] or 0)


def _item(c, item_id):
    r = c.execute("SELECT * FROM inv_items WHERE id=?", (int(item_id),)).fetchone()
    return dict(r) if r else None


def unplaced(c, item_id):
    it = _item(c, item_id)
    if not it:
        return 0.0
    return max(0.0, float(it["qty"] or 0) - located(c, item_id))


def item_size(c, item_id):
    r = c.execute("SELECT size FROM inv_item_wms WHERE item_id=?", (int(item_id),)).fetchone()
    return (r["size"] or "") if r else ""


def set_item_size(item_id, size, user=""):
    size = str(size or "").upper()
    if size and size not in SIZES:
        raise ValueError("尺寸等级写 S / M / L / XL（或者空）")
    c = db.conn()
    c.execute("INSERT INTO inv_item_wms(item_id, size) VALUES(?,?) ON CONFLICT(item_id) DO UPDATE SET size=excluded.size", (int(item_id), size))
    c.commit()
    return size


def _set(c, item_id, loc_id, qty):
    if qty <= EPS:
        c.execute("DELETE FROM inv_loc_qty WHERE item_id=? AND loc_id=?", (int(item_id), int(loc_id)))
    else:
        c.execute("INSERT INTO inv_loc_qty(item_id, loc_id, qty, updated_at) VALUES(?,?,?,?) ON CONFLICT(item_id, loc_id) "
                  "DO UPDATE SET qty=excluded.qty, updated_at=excluded.updated_at", (int(item_id), int(loc_id), round(qty, 6), _now()))


def _log(c, item_id, frm, to, qty, kind, user="", ref=""):
    c.execute("INSERT INTO inv_loc_log(ts, item_id, from_loc, to_loc, qty, kind, username, ref) VALUES(?,?,?,?,?,?,?,?)",
              (_now(), int(item_id), frm or "", to or "", float(qty), kind, user or "", ref or ""))
    for code in (frm, to):
        if code:
            c.execute("UPDATE inv_locations SET last_move=? WHERE code=?", (_now(), code))


def _add(c, item_id, loc, dq, kind, user="", ref=""):
    _set(c, item_id, loc["id"], loc_qty(c, item_id, loc["id"]) + dq)
    _log(c, item_id, "" if dq > 0 else loc["code"], loc["code"] if dq > 0 else "", abs(dq), kind, user, ref)


# ---------------- 规则：这个货位能不能放 ----------------
def check(c, loc, item, qty, extra=0.0):
    """能放返回 (None, 还能放多少)；不能放返回 (原因, 0)。extra = 同一次还要放进来的别的数量（批量移库）。"""
    if not loc.get("active", 1):
        return f"货位 {loc['code']} 停用了", 0
    if loc.get("fixed_item") and int(loc["fixed_item"]) != int(item["id"]):
        fx = _item(c, loc["fixed_item"])
        return f"{loc['code']} 是 {fx['code'] if fx else '别的物品'} 的固定货位", 0
    if not loc.get("mixed", 1):
        others = [r for r in _qty_rows(c, loc_id=loc["id"]) if r["item_id"] != item["id"]]
        if others:
            return f"{loc['code']} 不混放，已经放了别的物品", 0
    ls, isz = loc.get("size") or "", item_size(c, item["id"])
    if ls and isz and _SRANK.get(isz, 0) > _SRANK.get(ls, 9):
        return f"{item['code']} 是 {isz} 号，{loc['code']} 只放 {ls} 号以下", 0
    cap = loc.get("capacity")
    if cap not in (None, ""):
        room = float(cap) - loc_total(c, loc["id"]) - extra
        if room < qty - EPS:
            return f"{loc['code']} 放不下（容量 {float(cap):g}，还能放 {max(0.0, room):g}）", max(0.0, room)
        return None, room
    return None, float("inf")


# ---------------- 上架推荐 ----------------
def _dist(a, b):
    """两个货位离多远（同区同货架最近；不是标准编号的算很远）"""
    pa, pb = _L().parse(a["code"]), _L().parse(b["code"])
    if not pa or not pb:
        return (9, 0, 0, 0)
    return (0 if pa[0] == pb[0] else 1, abs(pa[1] - pb[1]), abs(pa[2] - pb[2]), abs(pa[3] - pb[3]))


def _cats_ok(loc, cat, gs):
    cats = _L()._cats_of(loc, gs)
    return (not cats) or cat in cats, bool(cats) and cat in cats


def _type_rank(ztype, cat):
    # v2.53：按分类找区：成品 → 拣货区；包材 → 包材区；耗材 / 备件 / 工具… → 耗材区
    order = {"goods": ("pick", "reserve", "supply", "pack"), "pack": ("pack", "supply", "pick", "reserve")}.get(cat, ("supply", "pick", "reserve", "pack"))
    return order.index(ztype) if ztype in order else 9


def candidates(c, item, kind=""):
    """推荐顺序：[(货位, 理由)]，理由 same 同物品已在 / near 同分类附近的空位 / empty 其它空位"""
    sk = _L().sort_key
    locs = _locs(c)
    gs = _L().groups()
    rows = _qty_rows(c)
    used = {}
    for r in rows:
        used.setdefault(r["loc_id"], set()).add(r["item_id"])
    homes = {}
    for r in c.execute("SELECT id, location, category FROM inv_items WHERE active=1 AND location IS NOT NULL AND location!=''"):
        homes.setdefault(r["location"], set()).add(r["id"])
    code2loc = {l["code"]: l for l in locs.values()}
    out, seen = [], set()
    # 1. 同一个物品已经在的货位：固定货位 → 主货位 → 拣货区 → 走路顺序
    mine = [l for l in locs.values() if item["id"] in used.get(l["id"], ()) or l["code"] == item.get("location")
            or (l.get("fixed_item") and int(l["fixed_item"]) == item["id"])]
    mine.sort(key=lambda l: (0 if l.get("fixed_item") == item["id"] else 1, 0 if l["code"] == item.get("location") else 1,
                             _type_rank(l["ztype"], item["category"]) if l["ztype"] in PUTAWAY_TYPES else 8, sk(l["code"])))
    for l in mine:
        if l["ztype"] in PUTAWAY_TYPES or l["code"] == item.get("location") or l.get("fixed_item") == item["id"]:
            out.append((l, "same"))
            seen.add(l["id"])

    def empty(l):
        return not used.get(l["id"]) and not homes.get(l["code"]) and not l.get("fixed_item")
    pool = [l for l in locs.values() if l["id"] not in seen and l["ztype"] in PUTAWAY_TYPES and empty(l) and _cats_ok(l, item["category"], gs)[0]]
    # 2. 同分类物品附近的空位
    anchors = [l for l in mine] or [code2loc[code] for code, ids in homes.items() if code in code2loc and any(
        (_item(c, i) or {}).get("category") == item["category"] for i in ids)]
    if anchors:
        near = sorted(pool, key=lambda l: (min(_dist(a, l) for a in anchors), _type_rank(l["ztype"], item["category"]), sk(l["code"])))
        near = [l for l in near if min(_dist(a, l) for a in anchors)[0] == 0]      # 只算同一个区
        for l in near:
            out.append((l, "near"))
            seen.add(l["id"])
    # 3. 其它空位：放这个分类的货架优先，再拣货区 / 备货区 / 耗材区，再走路顺序
    rest = [l for l in pool if l["id"] not in seen]
    rest.sort(key=lambda l: (0 if _cats_ok(l, item["category"], gs)[1] else 1, _type_rank(l["ztype"], item["category"]), sk(l["code"])))
    out += [(l, "empty") for l in rest]
    return out


def recommend(item_id, qty=None, kind="", c=None, limit=5):
    """上架推荐：[{code, qty, reason, human_zh, human_th}]（qty 不给 = 待上架的数量；放不下的部分没有推荐）"""
    c = c or db.conn()
    it = _item(c, item_id)
    if not it:
        raise ValueError("没有这个物品")
    left = float(qty) if qty not in (None, "") else unplaced(c, it["id"])
    plan = []
    for loc, why in candidates(c, it, kind):
        reason, room = check(c, loc, it, 0)
        if reason:
            continue
        take = 0.0
        if left > EPS:
            take = min(left, room)
            if take <= EPS:
                continue
        plan.append({"code": loc["code"], "qty": round(take, 6), "reason": why, "ztype": loc["ztype"],
                     "human_zh": _L().human(loc["code"]), "human_th": _L().human(loc["code"], "th")})
        left -= take
        if left <= EPS or len(plan) >= limit:
            break
    return plan


def suggest(category, c=None):
    """给这个分类的新物品找一个空位（没有返回 None）。"""
    c = c or db.conn()
    fake = {"id": -1, "code": "", "category": category, "location": None}
    for loc, _why in candidates(c, fake):
        if not check(c, loc, fake, 0)[0]:
            return loc["code"]
    return None


def auto_place(c, item_id, qty, kind="", user=""):
    """按推荐放 qty（放不下的留在待上架）。返回 [(货位编号, 数量)]。不 commit。"""
    it = _item(c, item_id)
    done = []
    for p in recommend(item_id, qty, kind, c, limit=50):
        if p["qty"] <= EPS:
            continue
        loc = _L().get_loc(p["code"])
        _add(c, item_id, loc, p["qty"], "putaway", user, kind)
        done.append((p["code"], p["qty"]))
    if done and not it.get("location"):
        c.execute("UPDATE inv_items SET location=? WHERE id=?", (done[0][0], item_id))
    return done


# ---------------- 库存变化 → 货位 ----------------
def _out_order(c, item):
    sk = _L().sort_key
    locs = _locs(c, active=False)
    rows = [r for r in _qty_rows(c, item_id=item["id"]) if r["loc_id"] in locs]
    pref = getattr(_tl, "prefer", None) or ()
    def prank(l):
        return pref.index(l["code"]) if l["code"] in pref else (pref.index(l["ztype"]) if l["ztype"] in pref else len(pref))
    rows.sort(key=lambda r: (prank(locs[r["loc_id"]]),
                             OUT_LAST.index(locs[r["loc_id"]]["ztype"]) + 1 if locs[r["loc_id"]]["ztype"] in OUT_LAST else 0,
                             0 if locs[r["loc_id"]]["code"] == item.get("location") else 1,
                             0 if locs[r["loc_id"]]["ztype"] == "pick" else 1, sk(locs[r["loc_id"]]["code"])))
    return [(locs[r["loc_id"]], r["qty"]) for r in rows]


def reconcile(c, item_id, user="", kind="out"):
    """货位上的加起来不能比总数多：多出来的从货位上扣（主货位 → 拣货区 → 走路顺序）。返回扣了哪些。"""
    it = _item(c, item_id)
    if not it:
        return []
    excess = located(c, item_id) - max(0.0, float(it["qty"] or 0))
    took = []
    if excess <= EPS:
        return took
    for loc, q in _out_order(c, it):
        if excess <= EPS:
            break
        d = min(q, excess)
        _set(c, item_id, loc["id"], q - d)
        _log(c, item_id, loc["code"], "", d, kind, user)
        took.append((loc["code"], d))
        excess -= d
    return took


def _quiet():
    return getattr(_tl, "quiet", None)


@contextlib.contextmanager
def quiet(item_ids):
    """这些物品的库存变化不动货位（按货位盘点确认时：货位上的数自己写）。"""
    old = getattr(_tl, "quiet", None)
    _tl.quiet = set(int(i) for i in item_ids) | (old or set())
    try:
        yield
    finally:
        _tl.quiet = old


@contextlib.contextmanager
def prefer(codes):
    """v2.53：这段时间里出库先从这些货位（或区类型，例如 "pack"）扣：打包台扣包材、次品区报废、退货区……"""
    old = getattr(_tl, "prefer", None)
    _tl.prefer = tuple(x for x in (codes or []) if x) + (old or ())
    try:
        yield
    finally:
        _tl.prefer = old


@contextlib.contextmanager
def route(loc_code):
    """v2.53：这段时间里入库的东西放到这个货位（退货登记 → 退货区）。"""
    old = getattr(_tl, "route", None)
    _tl.route = loc_code
    try:
        yield
    finally:
        _tl.route = old


@contextlib.contextmanager
def putaway_batch(targets=None, user=""):
    """采购到货等：这一批入库先进待上架，结束时按 targets {物品id: 货位} 放，没写的按推荐（设置「入库自动上架」关着就留在待上架）。
    用法：with putaway_batch({...}) as pb: 入库……；之后 pb["placed"]、pb["warnings"]。"""
    pb = {"got": {}, "placed": [], "warnings": [], "targets": {int(k): v for k, v in (targets or {}).items() if str(v or "").strip()}}
    old = getattr(_tl, "batch", None)
    _tl.batch = pb
    try:
        yield pb
    finally:
        _tl.batch = old
    c = db.conn()
    auto = load_config().get("inv_loc_auto", True)
    for iid, q in pb["got"].items():
        q = min(q, unplaced(c, iid))
        if q <= EPS:
            continue
        code = pb["targets"].get(iid)
        if code:
            try:
                move("", code, [{"item_id": iid, "qty": q}], user, kind="putaway", commit=False)
                it = _item(c, iid)
                home = _L().get_loc(it["location"]) if it.get("location") else None
                if not home or loc_qty(c, iid, home["id"]) <= EPS:     # 主货位上已经没有了 → 收货时填的货位当主货位
                    c.execute("UPDATE inv_items SET location=? WHERE id=?", (_L().get_loc(code)["code"], iid))
                pb["placed"].append({"item_id": iid, "code": _L().norm_code(code), "qty": q})
                continue
            except ValueError as e:
                pb["warnings"].append(str(e))
        if auto and c.execute("SELECT 1 FROM inv_locations LIMIT 1").fetchone():
            for code_, q_ in auto_place(c, iid, q, "purchase", user):
                pb["placed"].append({"item_id": iid, "code": code_, "qty": q_})
        elif not auto and c.execute("SELECT 1 FROM inv_locations LIMIT 1").fetchone():
            from . import flows          # v2.53：不自动上架 → 先放暂存区，扫货位确认上架（待上架列表里有推荐）
            if not flows.spool_item(c, iid):
                st = flows.zone_loc(c, "staging")
                _add(c, iid, st, q, "receive", user, "purchase")
                pb["placed"].append({"item_id": iid, "code": st["code"], "qty": q, "staging": True})
    c.commit()


def on_post(c, item_id, qty, kind, user=""):
    """ledger.post 每记一笔都会调（同一个事务里，不 commit）。"""
    if not qty:
        return
    q_ = _quiet()
    if q_ and int(item_id) in q_:
        return
    from . import flows
    if flows.spool_item(c, item_id):          # v2.53：按料卷管的耗材：货位上的数 = 每个货位上料卷剩的克数
        flows.spool_sync(c, item_id=item_id, user=user, kind=kind)
        return
    if qty < 0:
        reconcile(c, item_id, user, kind)
        check_replenish(c, item_id)
        return
    it = _item(c, item_id)
    if not it or not it["active"]:
        return
    tgt = flows.route_in(c, it, kind, getattr(_tl, "route", None))   # v2.53：打印出来的成品 → 待检区；退货 → 退货区
    if tgt:
        q = min(float(qty), unplaced(c, item_id))
        if q > EPS:
            _add(c, item_id, tgt, q, "putaway", user, kind)
        return
    pb = getattr(_tl, "batch", None)
    if pb is not None:
        pb["got"][int(item_id)] = pb["got"].get(int(item_id), 0) + float(qty)
        return
    if not load_config().get("inv_loc_auto", True):
        return
    if not c.execute("SELECT 1 FROM inv_locations LIMIT 1").fetchone():
        return
    q = unplaced(c, item_id)            # 自动上架：连以前没放上去的一起放
    if q > EPS:
        auto_place(c, item_id, q, kind, user)


# ---------------- 移库 / 上架 ----------------
def move(frm, to, lines, user="", kind="move", task_id=None, force=False, commit=True):
    """从货位 frm（空 = 待上架）搬到货位 to。lines：[{item_id, qty}]（qty 空 = 全部）。force = 超容量也放（其它规则不能跳过）。"""
    L = _L()
    c = db.conn()
    src = None
    if str(frm or "").strip():
        src = L.get_loc(frm)
        if not src:
            raise ValueError(f"没有货位 {frm}")
    dst = L.get_loc(to) if str(to or "").strip() else None
    if not dst or not dst["active"]:
        raise ValueError(f"没有货位 {to}" if str(to or "").strip() else "先扫要放到的货位")
    if src and src["id"] == dst["id"]:
        raise ValueError("原货位和目标货位是同一个")
    plan, extra = [], 0.0
    for ln in lines or []:
        it = _item(c, ln.get("item_id"))
        if not it:
            raise ValueError("没有这个物品")
        from . import flows
        if flows.spool_item(c, it["id"]):
            raise ValueError(f"{it['code']} 按料卷管理：扫料卷标签移动（料卷页 / 手机「料卷」）")
        have = loc_qty(c, it["id"], src["id"]) if src else unplaced(c, it["id"])
        try:
            q = have if ln.get("qty") in (None, "") else float(ln["qty"])
        except (TypeError, ValueError):
            raise ValueError(f"数量「{ln.get('qty')}」要填数字")
        if q != q or q <= EPS:
            raise ValueError(f"{it['code']} 的数量要大于 0")
        if q > have + 1e-6:
            raise ValueError(f"{it['code']} 在{src['code'] if src else '待上架'}只有 {have:g}")
        reason, _room = check(c, dst, it, q, extra)
        if reason and not (force and "放不下" in reason):
            raise ValueError(reason)
        extra += q
        plan.append((it, q))
    if not plan:
        raise ValueError("没有要搬的东西")
    dz = zone_of(dst["code"], c)["ztype"]
    if not dst.get("mixed", 1):
        kinds = {it["id"] for it, _q in plan} | {r["item_id"] for r in _qty_rows(c, loc_id=dst["id"])}
        if len(kinds) > 1:
            raise ValueError(f"{dst['code']} 不混放，一次只能放一种物品")
    for it, q in plan:
        if src:
            _set(c, it["id"], src["id"], loc_qty(c, it["id"], src["id"]) - q)
        _set(c, it["id"], dst["id"], loc_qty(c, it["id"], dst["id"]) + q)
        _log(c, it["id"], src["code"] if src else "", dst["code"], q, kind, user, f"task:{task_id}" if task_id else "")
        if dz in PUTAWAY_TYPES and (not it.get("location") or (src and it["location"] == src["code"] and loc_qty(c, it["id"], src["id"]) <= EPS
                                                           and not (src.get("fixed_item") and int(src["fixed_item"]) == it["id"]))):
            c.execute("UPDATE inv_items SET location=? WHERE id=?", (dst["code"], it["id"]))
    if task_id:
        c.execute("UPDATE inv_loc_tasks SET status='done', done_by=?, done_at=? WHERE id=?", (user, _now(), int(task_id)))
    if commit:
        c.commit()
        db.audit(user, {"putaway": "货位上架", "replenish": "库内补货"}.get(kind, "移库"),
                 f"{src['code'] if src else '待上架'} → {dst['code']}", "，".join(f"{it['code']}×{q:g}" for it, q in plan))
    return {"from": src["code"] if src else "", "to": dst["code"], "moved": [{"item_id": it["id"], "code": it["code"], "qty": q} for it, q in plan]}


def putaway(item_id, code, qty=None, user="", force=False, frm=""):
    """上架：待上架的物品放到货位（扫货位确认）。frm = 暂存区的货位（v2.53：采购到货先放暂存区）。"""
    return move(frm or "", code, [{"item_id": item_id, "qty": qty}], user, kind="putaway", force=force)


def pending_count(c=None):
    c = c or db.conn()
    from . import flows
    n = sum(1 for r in c.execute("SELECT id, qty FROM inv_items WHERE active=1 AND qty>0").fetchall()
            if float(r["qty"] or 0) - located(c, r["id"]) > 1e-6 and not flows.spool_item(c, r["id"]))
    stg = [l["id"] for l in _locs(c).values() if l["ztype"] == "staging"]
    if stg:
        n += c.execute(f"SELECT COUNT(*) FROM inv_loc_qty WHERE qty>0 AND loc_id IN ({','.join('?' * len(stg))})", stg).fetchone()[0]
    return n


def pending(c=None):
    """待上架：[{item, qty, suggest:[推荐]}]"""
    from core.inventory import ledger
    c = c or db.conn()
    out = []
    from . import flows
    for r in c.execute("SELECT * FROM inv_items WHERE active=1 AND qty>0 ORDER BY category, code").fetchall():
        if flows.spool_item(c, r["id"]):
            continue                   # v2.53：按料卷管的耗材在「料卷」里上架（一卷一卷扫）
        u = float(r["qty"] or 0) - located(c, r["id"])
        if u > 1e-6:
            out.append({"item": ledger.item_row(r), "qty": round(u, 6), "suggest": recommend(r["id"], u, "", c, limit=3), "from": ""})
    # v2.53：暂存区里的（采购到货先放暂存区）也算待上架，上架 = 从暂存区搬到推荐的货位
    locs = _locs(c)
    for r in _qty_rows(c):
        l = locs.get(r["loc_id"])
        if not l or l["ztype"] != "staging":
            continue
        it = _item(c, r["item_id"])
        if not it or not it["active"]:
            continue
        out.append({"item": ledger.item_row(c.execute("SELECT * FROM inv_items WHERE id=?", (it["id"],)).fetchone()), "qty": round(r["qty"], 6),
                    "suggest": recommend(it["id"], r["qty"], "", c, limit=3), "from": l["code"]})
    return out


# ---------------- 库内补货 ----------------
def replenish_suggestions(c=None):
    """拣货区货位低于最低数量 → 从备货区搬多少。[{item_id, code, name_zh, name_th, to, now, min, need, sources:[(货位, 数量)]}]"""
    c = c or db.conn()
    sk = _L().sort_key
    locs = _locs(c)
    out = []
    for l in sorted(locs.values(), key=lambda x: sk(x["code"])):
        if l["ztype"] not in REPL_TYPES or l.get("min_qty") in (None, ""):
            continue
        ids = {r["item_id"] for r in _qty_rows(c, loc_id=l["id"])}
        if l.get("fixed_item"):
            ids.add(int(l["fixed_item"]))
        ids |= {r[0] for r in c.execute("SELECT id FROM inv_items WHERE active=1 AND location=?", (l["code"],))}
        for iid in sorted(ids):
            it = _item(c, iid)
            if not it or not it["active"]:
                continue
            now = loc_qty(c, iid, l["id"])
            mn = float(l["min_qty"])
            if now >= mn - EPS:
                continue
            cap = l.get("capacity")
            target = float(cap) if cap not in (None, "") else max(mn * 2, mn + 1)
            need = max(0.0, target - now)
            if cap not in (None, ""):
                need = min(need, max(0.0, float(cap) - loc_total(c, l["id"])))
            srcs, left = [], need
            for r in sorted(_qty_rows(c, item_id=iid), key=lambda r: sk(locs[r["loc_id"]]["code"]) if r["loc_id"] in locs else (9,)):
                lo = locs.get(r["loc_id"])
                if not lo or lo["ztype"] != "reserve" or left <= EPS:
                    continue
                t = min(r["qty"], left)
                srcs.append((lo["code"], round(t, 6)))
                left -= t
            out.append({"item_id": iid, "code": it["code"], "name_zh": it["name_zh"], "name_th": it["name_th"], "unit": it["unit"],
                        "to": l["code"], "now": now, "min": mn, "need": round(need, 6), "sources": srcs, "ztype": l["ztype"],
                        "category": it["category"]})
    return out


def check_replenish(c, item_id):
    """出库之后：这个物品的拣货位低了就建补货任务（同一个事务里）。"""
    try:
        for s in replenish_suggestions(c):
            if s["item_id"] == int(item_id):
                _make_tasks(c, s)
    except Exception:  # noqa: BLE001  补货任务出错不影响记账
        pass


def _make_tasks(c, s, user="系统"):
    made = 0
    for frm, q in s["sources"]:
        if c.execute("SELECT 1 FROM inv_loc_tasks WHERE status='open' AND kind='replenish' AND item_id=? AND to_loc=? AND from_loc=?",
                     (s["item_id"], s["to"], frm)).fetchone():
            continue
        c.execute("INSERT INTO inv_loc_tasks(kind, item_id, from_loc, to_loc, qty, status, created_by, created_at) VALUES('replenish',?,?,?,?,'open',?,?)",
                  (s["item_id"], frm, s["to"], q, user, _now()))
        made += 1
    return made


def ensure_tasks(user="系统"):
    c = db.conn()
    n = sum(_make_tasks(c, s, user) for s in replenish_suggestions(c))
    c.commit()
    return n


def tasks(status="open"):
    c = db.conn()
    out = []
    for r in c.execute("SELECT t.*, i.code, i.name_zh, i.name_th, i.unit FROM inv_loc_tasks t JOIN inv_items i ON i.id=t.item_id "
                       "WHERE t.status=? ORDER BY t.id", (status,)):
        d = dict(r)
        src = _L().get_loc(d["from_loc"]) if d["from_loc"] else None
        d["available"] = loc_qty(c, d["item_id"], src["id"]) if src else 0
        out.append(d)
    return sorted(out, key=lambda d: _L().sort_key(d["from_loc"] or ""))


def task_cancel(tid, user=""):
    c = db.conn()
    c.execute("UPDATE inv_loc_tasks SET status='cancel', done_by=?, done_at=? WHERE id=? AND status='open'", (user, _now(), int(tid)))
    c.commit()


def task_do(tid, qty=None, user=""):
    c = db.conn()
    t = c.execute("SELECT * FROM inv_loc_tasks WHERE id=?", (int(tid),)).fetchone()
    if not t or t["status"] != "open":
        raise ValueError("这个任务已经做完或取消了")
    src = _L().get_loc(t["from_loc"])
    have = loc_qty(c, t["item_id"], src["id"]) if src else 0
    q = min(float(qty if qty not in (None, "") else t["qty"]), have)
    if q <= EPS:
        raise ValueError(f"{t['from_loc']} 已经没有这个物品了")
    return move(t["from_loc"], t["to_loc"], [{"item_id": t["item_id"], "qty": q}], user, kind=t["kind"], task_id=t["id"], force=True)


# ---------------- 货位图 / 提醒 / 统计 ----------------
def state_of(total, cap):
    if total <= EPS:
        return "empty"
    if cap in (None, ""):
        return "partial"
    cap = float(cap)
    if total > cap + EPS:
        return "over"
    return "full" if total >= cap - EPS else "partial"


def map_data(idle_days=None, max_spread=None):
    """货位图：每个货位的状态 + 区的统计 + 提醒。"""
    cfg = load_config()
    idle_days = float(idle_days or cfg.get("inv_loc_idle_days") or 90)
    max_spread = int(max_spread or cfg.get("inv_loc_max_spread") or 3)
    c = db.conn()
    sk = _L().sort_key
    locs = _locs(c)
    zs, _wn, _d = zinfo(c)
    rows = _qty_rows(c)
    per_loc, per_item = {}, {}
    for r in rows:
        if r["loc_id"] in locs:
            per_loc.setdefault(r["loc_id"], []).append(r)
            per_item.setdefault(r["item_id"], []).append(locs[r["loc_id"]]["code"])
    now = _now()
    zones, idle, empties = {}, [], []
    for l in locs.values():
        if l["ztype"] == "production":      # v2.53：打印机 / AMS 槽不是存货的地方，不算利用率和空货位
            continue
        tot = sum(r["qty"] for r in per_loc.get(l["id"], []))
        st = state_of(tot, l.get("capacity"))
        z = zones.setdefault(l["zone"], {"zone": l["zone"], "ztype": l["ztype"], "name": (zs.get(l["zone"]) or {}).get("name", ""),
                                         "total": 0, "used": 0, "empty": 0, "full": 0, "over": 0, "cap": 0.0, "cap_used": 0.0})
        z["total"] += 1
        z["used" if tot > EPS else "empty"] += 1
        z["full"] += st == "full"
        z["over"] += st == "over"
        if l.get("capacity") not in (None, ""):
            z["cap"] += float(l["capacity"])
            z["cap_used"] += min(tot, float(l["capacity"]))
        if st == "empty":
            empties.append(l["code"])
        last = l.get("last_move") or l.get("created_at") or 0
        if tot > EPS and last and now - last > idle_days * 86400:
            idle.append({"code": l["code"], "days": int((now - last) // 86400)})
    names = {r["id"]: dict(r) for r in c.execute("SELECT id, code, name_zh, name_th FROM inv_items")}
    spread = [{"item_id": iid, "code": names[iid]["code"], "name_zh": names[iid]["name_zh"], "name_th": names[iid]["name_th"],
               "locations": sorted(codes, key=sk)} for iid, codes in per_item.items() if len(codes) > max_spread and iid in names]
    total = sum(z["total"] for z in zones.values())
    used = sum(z["used"] for z in zones.values())
    return {"zones": sorted(zones.values(), key=lambda z: z["zone"]),
            "stats": {"total": total, "used": used, "empty": total - used, "util": round(100 * used / total, 1) if total else 0,
                      "full": sum(z["full"] for z in zones.values()), "over": sum(z["over"] for z in zones.values()),
                      "pending": pending_count(c), "tasks": c.execute("SELECT COUNT(*) FROM inv_loc_tasks WHERE status='open'").fetchone()[0]},
            "alerts": {"empty": sorted(empties, key=sk), "idle": sorted(idle, key=lambda x: -x["days"]), "spread": spread,
                       "idle_days": idle_days, "max_spread": max_spread}}


def where_is(code):
    """物品编码（成品 = SKU）→ [(货位编号, 这个货位的数量)]：拣货区在前，按走路顺序；货位上都没有时给主货位和总数。"""
    c = db.conn()
    r = c.execute("SELECT * FROM inv_items WHERE code=? AND active=1", (str(code or "").upper(),)).fetchone()
    if not r:
        return []
    it = dict(r)
    sk = _L().sort_key
    locs = _locs(c, active=False)
    rows = [x for x in _qty_rows(c, item_id=it["id"]) if x["loc_id"] in locs]
    rows.sort(key=lambda x: (0 if locs[x["loc_id"]]["ztype"] == "pick" else 1, sk(locs[x["loc_id"]]["code"])))
    out = [(locs[x["loc_id"]]["code"], round(x["qty"], 6)) for x in rows]
    if not out and it.get("location"):
        out = [(it["location"], it["qty"] or 0)]
    return out


def item_locations(item_id):
    """物品在哪些货位：[{code, qty, ztype, human_zh, human_th, primary}] + 待上架"""
    c = db.conn()
    it = _item(c, item_id)
    if not it:
        return {"locations": [], "unplaced": 0}
    locs = _locs(c, active=False)
    out = []
    for r in _qty_rows(c, item_id=item_id):
        l = locs.get(r["loc_id"])
        if l:
            out.append({"code": l["code"], "id": l["id"], "qty": r["qty"], "ztype": l["ztype"], "primary": l["code"] == it.get("location"),
                        "human_zh": _L().human(l["code"]), "human_th": _L().human(l["code"], "th")})
    out.sort(key=lambda x: _L().sort_key(x["code"]))
    return {"locations": out, "unplaced": unplaced(c, item_id), "size": item_size(c, item_id)}


def pick_route(skus):
    """拣货路线：[(sku, 货位, 数量)] 按 区 → 货架 → 层 → 位 排，每个区一组：[{zone, ztype, name, rows:[…]}]（没有货位的放最后一组）"""
    groups = {}
    sk = _L().sort_key
    for sku, qty in skus:
        w = where_is(sku)
        code = w[0][0] if w else ""
        z = (_L().parse(code) or ("",))[0]
        groups.setdefault(z, []).append({"sku": sku, "qty": qty, "code": code, "where": w})
    zs, _wn, _d = zinfo()
    out = []
    for z in sorted(groups, key=lambda x: (x == "", x)):
        rows = sorted(groups[z], key=lambda r: (sk(r["code"]) if r["code"] else (9,), r["sku"]))
        out.append({"zone": z, "ztype": (zs.get(z) or {}).get("ztype", "pick") if z else "", "name": (zs.get(z) or {}).get("name", ""), "rows": rows})
    return out
