"""仓库 → 货位页的三种看法和大数据量（v2.55：1 万+ 商品、2 万+ 货位也流畅）。全部在数据库里筛选 / 排序 / 搜索 / 分页，页面只拿当前这一页。

  list    列表：一行一个货位（里面的商品带图、名称、SKU、数量，容量和占用，状态，最后动的时间）
  items   按商品：一行一个商品（总数、分布在哪些货位、太分散 / 没上架的标记）
  map     货位图：只取选中的库区 / 货架；别的库区、货架只给一行汇总
  summary 数字卡片 + 各库区利用率（缓存：货位 / 数量没变就不重算）
  drawer  点一行：货位里的东西 + 出入库记录
  bulk    批量：把几个货位里的东西搬到另一个货位

数量显示全部走 qtytext.qty_text（接口的 qty_text / qty_text_th）。
索引：inv_loc_qty(loc_id) 和 (item_id)、inv_locations(code) 和 (zone, shelf, layer, pos)、inv_items(code / name / category / location)。"""
import os
import threading
import time

from core import db
from core.config import load_config

from . import qtytext

EPS = 1e-9
SIZES = (50, 100, 200)
STATES = ("empty", "partial", "full", "over", "low")
LOC_SORTS = {          # 列 → ORDER BY（默认 code = 区 → 货架 → 层 → 位）
    "code": "l.zone, l.shelf, l.layer, l.pos, l.code",
    "zone": "l.zone, l.shelf, l.layer, l.pos",
    "pos": "l.zone, l.shelf, l.layer, l.pos",
    "contents": "tot, n",
    "qty": "tot",
    "items": "n",
    "capacity": "l.capacity",
    "util": "(CASE WHEN l.capacity IS NULL OR l.capacity<=0 THEN -1 ELSE tot/l.capacity END)",
    "state": "(CASE WHEN tot<=1e-9 THEN 0 WHEN l.capacity IS NULL THEN 1 WHEN tot>l.capacity+1e-9 THEN 4 WHEN tot>=l.capacity-1e-9 THEN 3 ELSE 2 END)",
    "last_move": "l.last_move",
}
ITEM_SORTS = {
    "name": "COALESCE(NULLIF(i.name_zh,''), i.name_th), i.code",
    "code": "i.code",
    "category": "i.category, i.code",
    "qty": "i.qty",
    "locs": "nloc",
    "placed": "placed",
    "unplaced": "(i.qty - placed)",
}
_SCHEMA_DONE = []


# ---------------- 索引 ----------------
def ensure_indexes(c=None):
    """建索引（locations.init 里调；很多次调用只建一次）。"""
    c = c or db.conn()
    for sql in ("CREATE INDEX IF NOT EXISTS inv_loc_qty_item ON inv_loc_qty(item_id)",
                "CREATE INDEX IF NOT EXISTS inv_loc_qty_loc ON inv_loc_qty(loc_id)",
                "CREATE INDEX IF NOT EXISTS inv_locations_zone ON inv_locations(zone, shelf, layer, pos)",
                "CREATE INDEX IF NOT EXISTS inv_locations_code ON inv_locations(code)",
                "CREATE INDEX IF NOT EXISTS inv_items_code ON inv_items(code)",
                "CREATE INDEX IF NOT EXISTS inv_items_name ON inv_items(name_zh)",
                "CREATE INDEX IF NOT EXISTS inv_items_catcode ON inv_items(category, code)",
                "CREATE INDEX IF NOT EXISTS inv_items_location ON inv_items(location)",
                "CREATE INDEX IF NOT EXISTS inv_loc_log_from ON inv_loc_log(from_loc, ts)",
                "CREATE INDEX IF NOT EXISTS inv_loc_log_to ON inv_loc_log(to_loc, ts)"):
        try:
            c.execute(sql)
        except Exception:  # noqa: BLE001  物品表还没建（模块初始化顺序）：下次启动再建
            pass
    c.commit()


# ---------------- 商品图片（产品库的主图，按 SKU）----------------
_IMG = {"map": {}, "key": None, "building": False}
_IMG_LOCK = threading.Lock()


def _img_key():
    from core import store
    try:
        return (store.REV[0], os.path.getmtime(store.PRODUCTS_DIR))
    except OSError:
        return (store.REV[0], 0)


def _build_imgs(key):
    out = {}
    try:
        from core import store
        for it in store.list_products():
            try:
                p = store.load(it["id"])
            except Exception:  # noqa: BLE001
                continue
            imgs = p.get("images") or []
            for v in p.get("variants") or []:
                sku = str(v.get("sku") or "").strip().upper()
                if not sku:
                    continue
                want = v.get("image")
                img = next((i for i in imgs if want and (i.get("file") == want or i.get("raw") == want)), None) or next((i for i in imgs if i.get("file")), None)
                if img:
                    out[sku] = f"/files/{p['id']}/{'out' if img.get('processed') else 'raw'}/{img['file']}"
    except Exception:  # noqa: BLE001  产品库读不了：没图而已
        pass
    with _IMG_LOCK:
        _IMG["map"], _IMG["key"], _IMG["building"] = out, key, False


def img_index(wait=False):
    """{SKU: 图片地址}。产品库有变化时在后台线程重建（不卡住请求，建好前用旧的）；wait=True 等建好（测试用）。"""
    key = _img_key()
    if _IMG["key"] != key and not _IMG["building"]:
        with _IMG_LOCK:
            start = _IMG["key"] != key and not _IMG["building"]
            if start:
                _IMG["building"] = True
        if start:
            if wait:
                _build_imgs(key)
            else:
                threading.Thread(target=_build_imgs, args=(key,), daemon=True).start()
    return _IMG["map"]


def _img_of(code, category):
    if category != "goods":
        return ""
    return img_index().get(str(code or "").upper(), "")


# ---------------- 通用 ----------------
def _int(v, d, lo=1, hi=10 ** 9):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return d


def _like(s):
    return "%" + str(s).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _dflt_wh(c):
    from . import wms
    return wms.default_warehouse(c)


def _paging(a, total):
    size = _int(a.get("size"), 50)
    size = size if size in SIZES else (50 if size < 75 else 100 if size < 150 else 200)
    pages = max(1, -(-total // size))
    page = min(_int(a.get("page"), 1), pages)
    return size, page, pages


def _brief(r, img=True):
    """商品的一小块（货位里 / 分布里用）：编码、名称、图、数量文字"""
    d = {"id": r["item_id"] if "item_id" in r.keys() else r["id"], "code": r["code"], "name_zh": r["name_zh"] or "", "name_th": r["name_th"] or "",
         "unit": r["unit"] or "", "category": r["category"] or "", "color": (r["color"] or "") if "color" in r.keys() else ""}
    d["img"] = _img_of(r["code"], r["category"]) if img else ""
    return d


# ---------------- 列表：一行一个货位 ----------------
_AGG = "WITH agg AS (SELECT loc_id, SUM(qty) tot, COUNT(*) n FROM inv_loc_qty WHERE qty>1e-9 GROUP BY loc_id)"
_TOT, _N = "COALESCE(agg.tot,0)", "COALESCE(agg.n,0)"
_STATE_SQL = ("(CASE WHEN tot<=1e-9 THEN 'empty' WHEN l.capacity IS NULL THEN 'partial' WHEN tot>l.capacity+1e-9 THEN 'over' "
              "WHEN tot>=l.capacity-1e-9 THEN 'full' ELSE 'partial' END)")
_BASE = ("FROM inv_locations l LEFT JOIN agg ON agg.loc_id=l.id LEFT JOIN inv_loc_groups g ON g.code=l.zone AND g.kind='zone'")
_COLS = (f"l.*, {_TOT} AS tot, {_N} AS n, COALESCE(NULLIF(g.ztype,''),'pick') AS ztype, COALESCE(g.warehouse, ?) AS wh")


def _loc_where(a, c):
    """筛选条件 → (WHERE 文字, 参数)。表别名：l 货位、agg 汇总、g 库区。tot / n 在外面一层用。"""
    w, args = ["l.active=1"], []
    if a.get("ztype"):
        w.append("COALESCE(NULLIF(g.ztype,''),'pick')=?")
        args.append(a["ztype"])
    elif a.get("ztype_all") != "1":                       # 生产区（打印机 / AMS 槽）不是存货的地方，默认不列
        w.append("COALESCE(NULLIF(g.ztype,''),'pick')<>'production'")
    if a.get("wh"):
        w.append("COALESCE(g.warehouse, ?)=?")
        args += [_dflt_wh(c), int(a["wh"])]
    if a.get("zone"):
        w.append("l.zone=?")
        args.append(str(a["zone"]).strip().upper())
    sh = str(a.get("shelf") or "").strip().upper()
    if sh:
        import re
        m = re.match(r"^([A-Z]{1,2})(\d{1,2})$", sh)
        if m:
            w.append("l.zone=? AND l.shelf=?")
            args += [m.group(1), int(m.group(2))]
        else:
            w.append("l.code LIKE ?")
            args.append(sh + "%")
    if a.get("category"):
        w.append("l.id IN (SELECT q.loc_id FROM inv_loc_qty q JOIN inv_items i ON i.id=q.item_id WHERE q.qty>1e-9 AND i.category=?)")
        args.append(a["category"])
    has = a.get("has") or ""
    if has == "empty":
        w.append("COALESCE(agg.tot,0)<=1e-9")
    elif has == "nonempty":
        w.append("COALESCE(agg.tot,0)>1e-9")
    st = a.get("status") or ""
    tot = _TOT
    if st == "empty":
        w.append(f"{tot}<=1e-9")
    elif st == "partial":
        w.append(f"{tot}>1e-9 AND (l.capacity IS NULL OR {tot}<l.capacity-1e-9)")
    elif st == "full":
        w.append(f"l.capacity IS NOT NULL AND {tot}>=l.capacity-1e-9 AND {tot}<=l.capacity+1e-9 AND {tot}>1e-9")
    elif st == "over":
        w.append(f"l.capacity IS NOT NULL AND {tot}>l.capacity+1e-9")
    elif st == "low":
        w.append(f"l.min_qty IS NOT NULL AND {tot}<l.min_qty")
    if a.get("below_min") == "1":
        w.append(f"l.min_qty IS NOT NULL AND {tot}<l.min_qty")
    q = str(a.get("q") or "").strip()
    if q:
        from . import locations
        nq = locations.norm_code(q)
        qs = [_like(q)]
        parts = ["l.code LIKE ? ESCAPE '\\'"]
        args2 = [qs[0]]
        if nq != q.upper():
            parts.append("l.code LIKE ? ESCAPE '\\'")
            args2.append(_like(nq))
        # 商品名称 / SKU / 条码（条码 = 物品编码）
        parts.append("l.id IN (SELECT qq.loc_id FROM inv_loc_qty qq WHERE qq.qty>1e-9 AND qq.item_id IN "
                     "(SELECT id FROM inv_items WHERE code LIKE ? ESCAPE '\\' OR name_zh LIKE ? ESCAPE '\\' OR name_th LIKE ? ESCAPE '\\'))")
        args2 += [qs[0]] * 3
        parts.append("l.code IN (SELECT location FROM inv_items WHERE location<>'' AND (code LIKE ? ESCAPE '\\' OR name_zh LIKE ? ESCAPE '\\' OR name_th LIKE ? ESCAPE '\\'))")
        args2 += [qs[0]] * 3
        w.append("(" + " OR ".join(parts) + ")")
        args += args2
    return " AND ".join(w), args


def _loc_query(a, c):
    where, wargs = _loc_where(a, c)
    return where, wargs


def _enrich_locs(c, rows):
    """给一页货位补上里面的商品（最多 40 个，按数量大的在前）、图片、数量文字、状态。"""
    from . import wms
    ids = [r["id"] for r in rows]
    codes = [r["code"] for r in rows]
    by = {i: [] for i in ids}
    if ids:
        ph = ",".join("?" * len(ids))
        seen = set()
        for r in c.execute(f"SELECT q.loc_id, q.item_id, q.qty, i.code, i.name_zh, i.name_th, i.unit, i.category, i.color, i.material, i.qty total, "
                           f"i.reorder_point, i.location FROM inv_loc_qty q JOIN inv_items i ON i.id=q.item_id "
                           f"WHERE q.loc_id IN ({ph}) AND q.qty>1e-9 AND i.active=1 ORDER BY q.qty DESC, i.code", ids):
            seen.add((r["loc_id"], r["item_id"]))
            by[r["loc_id"]].append(r)
        cmap = {r["code"]: r["id"] for r in rows}
        zero = c.execute(f"SELECT id item_id, code, name_zh, name_th, unit, category, color, material, qty total, reorder_point, location FROM inv_items "
                         f"WHERE active=1 AND location IN ({','.join('?' * len(codes))})", codes).fetchall() if codes else []
        for r in zero:
            lid = cmap.get(r["location"])
            if lid is not None and (lid, r["item_id"]) not in seen:
                d = dict(r)
                d.update(loc_id=lid, qty=0.0)
                by[lid].append(d)
        allids = {x["item_id"] for v in by.values() for x in v}
        stocked = set()
        if allids:
            stocked = {r[0] for r in c.execute(f"SELECT DISTINCT item_id FROM inv_moves WHERE item_id IN ({','.join('?' * len(allids))})", list(allids))}
    zs, _wn, _d = wms.zinfo(c)
    out = []
    qc = qtytext.Ctx(c)
    for r in rows:
        its = []
        for x in by.get(r["id"], [])[:40]:
            xd = dict(x)
            b = _brief(xd)
            q = float(xd["qty"] or 0)
            rp = xd.get("reorder_point")
            tt = qtytext.both(float(xd.get("total") or 0), b["unit"], xd, qc)
            b.update(qty=round(q, 6), total=round(float(xd.get("total") or 0), 6), primary=xd.get("location") == r["code"],
                     low=bool(rp is not None and float(xd.get("total") or 0) <= rp and xd["item_id"] in stocked), total_text=tt["qty_text"],
                     total_text_th=tt["qty_text_th"], **qtytext.both(q, b["unit"], xd, qc, r["id"]))
            its.append(b)
        tot = float(r["tot"] or 0)
        cap = r["capacity"]
        out.append(_loc_row(r, tot, its, int(r["n"] or 0), zs))
    return out


def _loc_row(r, tot, its, n, zs=None):
    from . import wms, locations
    cap = r["capacity"]
    state = wms.state_of(tot, cap)
    shelf = locations.shelf_code(r["zone"], r["shelf"]) if r["shelf"] is not None else ""
    return {"id": r["id"], "code": r["code"], "zone": r["zone"], "shelf": r["shelf"], "shelf_code": shelf, "layer": r["layer"], "pos": r["pos"], "ztype": r["ztype"],
            "warehouse": r["wh"], "capacity": cap, "min_qty": r["min_qty"], "size": r["size"], "mixed": r["mixed"], "fixed_item": r["fixed_item"],
            "note": r["note"] or "", "total": round(tot, 6), "n_items": max(n, len([x for x in its if x["qty"] > EPS])), "items": its,
            "util": (round(100.0 * tot / float(cap), 1) if cap not in (None, "") and float(cap) > 0 else None), "state": state,
            "below_min": bool(r["min_qty"] is not None and tot < float(r["min_qty"]) - EPS),
            "low": any(x["low"] for x in its) or bool(r["min_qty"] is not None and tot < float(r["min_qty"]) - EPS),
            "last_move": r["last_move"]}


def list_locations(a):
    """列表：{rows, total, page, pages, size, sort, dir}。a：筛选 / 排序 / 分页的参数（dict）。"""
    c = db.conn()
    dflt = _dflt_wh(c)
    where, wargs = _loc_where(a, c)
    # tot / n 在 SELECT 里别名，WHERE 用表达式；这里先数总数
    total = c.execute(f"{_AGG} SELECT COUNT(*) {_BASE} WHERE {where}", wargs).fetchone()[0]
    size, page, pages = _paging(a, total)
    sort = a.get("sort") if a.get("sort") in LOC_SORTS else "code"
    desc = str(a.get("dir") or "").lower() == "desc"
    order = LOC_SORTS[sort]
    if desc:
        order = ", ".join(f"{p.strip()} DESC" for p in _split_order(order))
    rows = c.execute(f"{_AGG} SELECT {_COLS} {_BASE} WHERE {where} ORDER BY {order}, l.id LIMIT ? OFFSET ?",
                     [dflt] + wargs + [size, (page - 1) * size]).fetchall()
    return {"rows": _enrich_locs(c, rows), "total": total, "page": page, "pages": pages, "size": size, "sort": sort, "dir": "desc" if desc else "asc"}


def _split_order(order):
    """'a, b, (CASE .. , ..)' → 顶层按逗号拆开（括号里的逗号不拆）"""
    out, depth, cur = [], 0, ""
    for ch in order:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


def filtered_codes(a, limit=3000):
    """当前筛选条件下的全部货位编号（「选中全部 N 个」用），最多 limit 个。"""
    c = db.conn()
    where, wargs = _loc_where(a, c)
    total = c.execute(f"{_AGG} SELECT COUNT(*) {_BASE} WHERE {where}", wargs).fetchone()[0]
    rows = c.execute(f"{_AGG} SELECT l.id, l.code {_BASE} WHERE {where} ORDER BY l.zone, l.shelf, l.layer, l.pos, l.id LIMIT ?", wargs + [limit]).fetchall()
    return {"codes": [r["code"] for r in rows], "ids": [r["id"] for r in rows], "total": total, "capped": total > len(rows)}


def suggest(q, limit=30, empty_first=False):
    """货位编号联想（输入框里边打边出）"""
    c = db.conn()
    from . import locations
    q = str(q or "").strip()
    nq = locations.norm_code(q)
    like = _like(q.upper()) if q else "%"
    rows = c.execute(f"{_AGG} SELECT l.id, l.code, l.zone, {_TOT} tot {_BASE} WHERE l.active=1 AND (l.code LIKE ? ESCAPE '\\' OR l.code LIKE ? ESCAPE '\\') "
                     "AND COALESCE(NULLIF(g.ztype,''),'pick')<>'production' ORDER BY l.zone, l.shelf, l.layer, l.pos LIMIT ?",
                     (like, _like(nq), int(limit))).fetchall()
    return [{"id": r["id"], "code": r["code"], "empty": r["tot"] <= EPS} for r in rows]


# ---------------- 按商品：一行一个商品 ----------------
_PLACED = "WITH placed AS (SELECT item_id, SUM(qty) s, COUNT(*) n FROM inv_loc_qty WHERE qty>1e-9 GROUP BY item_id)"


def _item_where(a, c):
    w, args = ["i.active=1", "(i.qty>1e-9 OR COALESCE(p.n,0)>0 OR COALESCE(i.location,'')<>'')"], []
    if a.get("category"):
        w.append("i.category=?")
        args.append(a["category"])
    z = str(a.get("zone") or "").strip().upper()
    if z:
        w.append("i.id IN (SELECT q.item_id FROM inv_loc_qty q JOIN inv_locations l ON l.id=q.loc_id WHERE q.qty>1e-9 AND l.zone=?)")
        args.append(z)
    if a.get("ztype"):
        w.append("i.id IN (SELECT q.item_id FROM inv_loc_qty q JOIN inv_locations l ON l.id=q.loc_id LEFT JOIN inv_loc_groups g ON g.code=l.zone AND g.kind='zone' "
                 "WHERE q.qty>1e-9 AND COALESCE(NULLIF(g.ztype,''),'pick')=?)")
        args.append(a["ztype"])
    sh = str(a.get("shelf") or "").strip().upper()
    if sh:
        w.append("i.id IN (SELECT q.item_id FROM inv_loc_qty q JOIN inv_locations l ON l.id=q.loc_id WHERE q.qty>1e-9 AND l.code LIKE ?)")
        args.append(sh + "%" if not sh[-1:].isdigit() or "-" in sh else sh + "-%")
    flag = a.get("flag") or ""
    spread = int(load_config().get("inv_loc_max_spread") or 3)
    if flag == "scattered":
        w.append("COALESCE(p.n,0)>?")
        args.append(spread)
    elif flag == "unplaced":
        w.append("i.qty>1e-9 AND i.qty-COALESCE(p.s,0)>1e-6")
    elif flag == "noloc":
        w.append("COALESCE(p.n,0)=0")
    elif flag == "low":
        w.append("i.reorder_point IS NOT NULL AND i.qty<=i.reorder_point")
    has = a.get("has") or ""
    if has == "empty":
        w.append("i.qty<=1e-9")
    elif has == "nonempty":
        w.append("i.qty>1e-9")
    q = str(a.get("q") or "").strip()
    if q:
        w.append("(i.code LIKE ? ESCAPE '\\' OR i.name_zh LIKE ? ESCAPE '\\' OR i.name_th LIKE ? ESCAPE '\\' OR i.brand LIKE ? ESCAPE '\\' OR i.spec LIKE ? ESCAPE '\\' "
                 "OR i.location LIKE ? ESCAPE '\\' OR i.id IN (SELECT qq.item_id FROM inv_loc_qty qq JOIN inv_locations ll ON ll.id=qq.loc_id WHERE qq.qty>1e-9 AND ll.code LIKE ? ESCAPE '\\'))")
        args += [_like(q)] * 6 + [_like(q.upper())]
    return " AND ".join(w), args, spread


def _item_from():
    return "FROM inv_items i LEFT JOIN placed p ON p.item_id=i.id"


def list_items(a):
    """按商品：{rows, total, page, pages, size}。每行：商品、总数、分布 locs、标记 flags（scattered 太分散 / unplaced 没上架 / noloc 没货位 / low 低于补货线）。"""
    c = db.conn()
    where, wargs, spread = _item_where(a, c)
    total = c.execute(f"{_PLACED} SELECT COUNT(*) {_item_from()} WHERE {where}", wargs).fetchone()[0]
    size, page, pages = _paging(a, total)
    sort = a.get("sort") if a.get("sort") in ITEM_SORTS else "name"
    desc = str(a.get("dir") or "").lower() == "desc"
    order = ITEM_SORTS[sort]
    if desc:
        order = ", ".join(f"{p.strip()} DESC" for p in _split_order(order))
    rows = c.execute(f"{_PLACED} SELECT i.*, COALESCE(p.s,0) placed, COALESCE(p.n,0) nloc {_item_from()} WHERE {where} ORDER BY {order}, i.id LIMIT ? OFFSET ?",
                     wargs + [size, (page - 1) * size]).fetchall()
    return {"rows": _enrich_items(c, rows, spread), "total": total, "page": page, "pages": pages, "size": size, "sort": sort,
            "dir": "desc" if desc else "asc", "max_spread": spread}


def _enrich_items(c, rows, spread):
    from . import locations, wms
    ids = [r["id"] for r in rows]
    dist = {i: [] for i in ids}
    if ids:
        for r in c.execute(f"SELECT q.item_id, q.qty, l.id lid, l.code, l.zone, COALESCE(NULLIF(g.ztype,''),'pick') ztype FROM inv_loc_qty q "
                           f"JOIN inv_locations l ON l.id=q.loc_id LEFT JOIN inv_loc_groups g ON g.code=l.zone AND g.kind='zone' "
                           f"WHERE q.item_id IN ({','.join('?' * len(ids))}) AND q.qty>1e-9", ids):
            dist[r["item_id"]].append(r)
        stocked = {r[0] for r in c.execute(f"SELECT DISTINCT item_id FROM inv_moves WHERE item_id IN ({','.join('?' * len(ids))})", ids)}
    out = []
    qc = qtytext.Ctx(c)
    for r in rows:
        ds = sorted(dist.get(r["id"], []), key=lambda x: (0 if x["ztype"] == "pick" else 1, locations.sort_key(x["code"])))
        unit = r["unit"] or ""
        rd = dict(r)
        qty = float(r["qty"] or 0)
        placed = float(r["placed"] or 0)
        unplaced = max(0.0, qty - placed)
        flags = []
        if int(r["nloc"]) > spread:
            flags.append("scattered")
        if qty > EPS and unplaced > 1e-6:
            flags.append("unplaced")
        if int(r["nloc"]) == 0:
            flags.append("noloc")
        low = bool(r["reorder_point"] is not None and qty <= float(r["reorder_point"]) and r["id"] in stocked)
        if low:
            flags.append("low")
        d = _brief(r)
        d.update(qty=round(qty, 6), placed=round(placed, 6), unplaced=round(unplaced, 6), nloc=int(r["nloc"]), flags=flags, low=low, location=r["location"] or "",
                 reorder_point=r["reorder_point"], brand=r["brand"] or "", spec=r["spec"] or "", material=r["material"] or "",
                 locs=[{"id": x["lid"], "code": x["code"], "qty": round(x["qty"], 6), "ztype": x["ztype"], "primary": x["code"] == r["location"],
                        **qtytext.both(x["qty"], unit, rd, qc, x["lid"])} for x in ds[:30]],
                 unplaced_text=qtytext.qty_text(unplaced, unit), unplaced_text_th=qtytext.qty_text(unplaced, unit, None, "th"), **qtytext.both(qty, unit, rd, qc))
        out.append(d)
    return out


# ---------------- 汇总（数字卡片、各库区利用率）：缓存 ----------------
_SUM = {"sig": None, "data": None, "ts": 0}
_SUM_LOCK = threading.Lock()


def _sig(c):
    a = c.execute("SELECT COUNT(*), COALESCE(MAX(updated_at),0), COALESCE(SUM(qty),0) FROM inv_loc_qty").fetchone()
    b = c.execute("SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(SUM(active),0), COALESCE(MAX(last_move),0), COALESCE(SUM(capacity),0), COALESCE(SUM(min_qty),0), "
                  "COUNT(capacity), COUNT(min_qty) FROM inv_locations").fetchone()
    g = c.execute("SELECT COUNT(*), COALESCE(MAX(updated_at),0) FROM inv_loc_groups").fetchone()
    return (tuple(a), tuple(b), tuple(g), c.execute("SELECT COALESCE(MAX(updated_at),0), COUNT(*) FROM inv_items WHERE active=1 AND qty>0").fetchone()[0:2])


def invalidate():
    _SUM["sig"] = None


def zone_aggregates(c):
    """每个库区：货位数、有货、空、满、超容量、容量合计 / 已用、货架数、最大货架号。一条 SQL。"""
    rows = c.execute(f"""{_AGG}
        SELECT l.zone, COALESCE(NULLIF(g.ztype,''),'pick') ztype, COALESCE(g.name,'') name, COALESCE(g.warehouse,?) wh,
               COUNT(*) total, SUM(CASE WHEN {_TOT}>1e-9 THEN 1 ELSE 0 END) used,
               SUM(CASE WHEN l.capacity IS NOT NULL AND {_TOT}>1e-9 AND {_TOT}>=l.capacity-1e-9 AND {_TOT}<=l.capacity+1e-9 THEN 1 ELSE 0 END) "full",
               SUM(CASE WHEN l.capacity IS NOT NULL AND {_TOT}>l.capacity+1e-9 THEN 1 ELSE 0 END) "over",
               SUM(CASE WHEN l.min_qty IS NOT NULL AND {_TOT}<l.min_qty THEN 1 ELSE 0 END) below_min,
               COALESCE(SUM(l.capacity),0) cap,
               COALESCE(SUM(CASE WHEN l.capacity IS NOT NULL THEN MIN({_TOT}, l.capacity) ELSE 0 END),0) cap_used,
               COUNT(DISTINCT l.shelf) shelves, COALESCE(MAX(l.shelf),0) max_shelf
        {_BASE} WHERE l.active=1 GROUP BY l.zone ORDER BY l.zone""", (_dflt_wh(c),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["empty"] = d["total"] - d["used"]
        out.append(d)
    return out


def summary(force=False):
    """页面顶部：数字卡片 + 各库区利用率 + 提醒的数量。货位 / 数量 / 设置没变就直接用缓存。"""
    c = db.conn()
    sig = _sig(c)
    now = time.time()
    with _SUM_LOCK:
        if not force and _SUM["sig"] == sig and now - _SUM["ts"] < 60:
            return _SUM["data"]
    from . import wms
    cfg = load_config()
    idle_days = float(cfg.get("inv_loc_idle_days") or 90)
    max_spread = int(cfg.get("inv_loc_max_spread") or 3)
    zs = zone_aggregates(c)
    store_zs = [z for z in zs if z["ztype"] != "production"]
    total = sum(z["total"] for z in store_zs)
    used = sum(z["used"] for z in store_zs)
    idle = c.execute(f"{_AGG} SELECT COUNT(*) {_BASE} WHERE l.active=1 AND COALESCE(NULLIF(g.ztype,''),'pick')<>'production' AND {_TOT}>1e-9 "
                     "AND COALESCE(l.last_move, l.created_at, 0)>0 AND COALESCE(l.last_move, l.created_at)<?", (now - idle_days * 86400,)).fetchone()[0]
    spread = c.execute("SELECT COUNT(*) FROM (SELECT item_id FROM inv_loc_qty WHERE qty>1e-9 GROUP BY item_id HAVING COUNT(*)>?)", (max_spread,)).fetchone()[0]
    wh = c.execute("SELECT COUNT(*) FROM inv_warehouses").fetchone()[0]
    cats = [dict(r) for r in c.execute("SELECT category, COUNT(*) n FROM inv_items WHERE active=1 GROUP BY category")]
    data = {"stats": {"total": total, "used": used, "empty": total - used, "util": round(100.0 * used / total, 1) if total else 0,
                      "full": sum(z["full"] for z in store_zs), "over": sum(z["over"] for z in store_zs), "below_min": sum(z["below_min"] for z in store_zs),
                      "pending": wms.pending_count(c), "tasks": c.execute("SELECT COUNT(*) FROM inv_loc_tasks WHERE status='open'").fetchone()[0],
                      "idle": idle, "spread": spread, "zones": len(store_zs), "warehouses": wh,
                      "items": c.execute("SELECT COUNT(*) FROM inv_items WHERE active=1").fetchone()[0]},
            "zones": [{**z, "name": z["name"]} for z in store_zs], "all_zones": zs, "alerts": {"idle_days": idle_days, "max_spread": max_spread,
                                                                                                      "idle": idle, "spread": spread}, "categories": cats}
    with _SUM_LOCK:
        _SUM.update(sig=sig, data=data, ts=now)
    return data


# ---------------- 货位图：只取选中的库区 / 货架 ----------------
def shelf_summaries(c, zone):
    """一个库区里每个货架一行汇总：货架号、名称、层数、位数、有货、空。"""
    rows = c.execute(f"""{_AGG}
        SELECT l.shelf, COUNT(*) total, SUM(CASE WHEN {_TOT}>1e-9 THEN 1 ELSE 0 END) used, COUNT(DISTINCT l.layer) layers,
               SUM(CASE WHEN l.capacity IS NOT NULL AND {_TOT}>l.capacity+1e-9 THEN 1 ELSE 0 END) "over",
               SUM(CASE WHEN l.min_qty IS NOT NULL AND {_TOT}<l.min_qty THEN 1 ELSE 0 END) below_min
        FROM inv_locations l LEFT JOIN agg ON agg.loc_id=l.id WHERE l.active=1 AND l.zone=? GROUP BY l.shelf ORDER BY l.shelf""", (zone,)).fetchall()
    groups = {r["code"]: r for r in c.execute("SELECT * FROM inv_loc_groups WHERE kind='shelf' AND code LIKE ?", (zone + "%",))}
    out = []
    for r in rows:
        code = f"{zone}{r['shelf']}" if r["shelf"] is not None else ""
        g = groups.get(code)
        out.append({"shelf": code, "name": (g["name"] if g else "") or "", "categories": [x for x in ((g["categories"] if g else "") or "").split(",") if x],
                    "total": r["total"], "used": r["used"], "empty": r["total"] - r["used"], "layers": r["layers"], "over": r["over"], "below_min": r["below_min"]})
    return out


def map_view(zone="", shelf="", expand="", every=False):
    """货位图的数据。zone 空 = 只给各库区汇总；zone 有 = 这个库区的货架汇总 + 要展开的货架的货位（shelf 指定一个，expand=all 全部展开）。
    其它库区 / 货架不给格子，只有汇总行。"""
    c = db.conn()
    out = {"zones": [z for z in zone_aggregates(c) if z["ztype"] != "production"]}       # 生产区（打印机 / AMS 槽）不是存货的地方，货位图不画
    zone = str(zone or "").strip().upper()
    if every:                                   # 货位不多（页面判断）：一次给全部格子
        dflt = _dflt_wh(c)
        rows = c.execute(f"{_AGG} SELECT {_COLS} {_BASE} WHERE l.active=1 AND COALESCE(NULLIF(g.ztype,''),'pick')<>'production' "
                         "ORDER BY l.zone, l.shelf, l.layer, l.pos LIMIT 3000", [dflt]).fetchall()
        out["locations"] = _enrich_locs(c, rows)
        out["shelves_all"] = {z["zone"]: shelf_summaries(c, z["zone"]) for z in out["zones"]}
        return out
    if not zone:
        return out
    out["shelves"] = shelf_summaries(c, zone)
    where = ["l.active=1", "l.zone=?"]
    args = [zone]
    sh = str(shelf or "").strip().upper()
    if expand != "all":
        if not sh:
            return out
        import re
        m = re.match(r"^([A-Z]{1,2})(\d{1,2})$", sh)
        if not m or m.group(1) != zone:
            return out
        where.append("l.shelf=?")
        args.append(int(m.group(2)))
    dflt = _dflt_wh(c)
    rows = c.execute(f"{_AGG} SELECT {_COLS} {_BASE} WHERE {' AND '.join(where)} ORDER BY l.zone, l.shelf, l.layer, l.pos LIMIT 3000", [dflt] + args).fetchall()
    out["locations"] = _enrich_locs(c, rows)
    return out


# ---------------- 点一行：抽屉 ----------------
def drawer(lid):
    """货位详情 + 出入库记录（最近 60 条）。items 带图片和 qty_text。"""
    from . import locations
    c = db.conn()
    d = locations.loc_detail(lid)
    loc = d["location"]
    row = c.execute(f"{_AGG} SELECT {_COLS} {_BASE} WHERE l.id=?", (_dflt_wh(c), loc["id"])).fetchone()
    cell = _enrich_locs(c, [row])[0] if row else None
    log = []
    for r in c.execute("SELECT g.ts, g.item_id, g.from_loc, g.to_loc, g.qty, g.kind, g.username, i.code, i.name_zh, i.name_th, i.unit "
                       "FROM inv_loc_log g LEFT JOIN inv_items i ON i.id=g.item_id WHERE g.from_loc=? OR g.to_loc=? ORDER BY g.ts DESC, g.id DESC LIMIT 60",
                       (loc["code"], loc["code"])):
        log.append({"ts": r["ts"], "item_id": r["item_id"], "code": r["code"] or "", "name_zh": r["name_zh"] or "", "name_th": r["name_th"] or "",
                    "from": r["from_loc"] or "", "to": r["to_loc"] or "", "qty": r["qty"], "kind": r["kind"], "user": r["username"] or "",
                    "dir": "in" if r["to_loc"] == loc["code"] else "out", **qtytext.both(r["qty"], r["unit"] or "")})
    d["items"] = cell["items"] if cell else d["items"]
    return {"location": loc, "items": d["items"], "cell": cell, "log": log}


# ---------------- 批量 ----------------
def bulk_move(codes, to, user="", force=False):
    """几个货位里的东西全部搬到另一个货位 to。一个一个搬，哪个搬不了记下原因，别的照搬。"""
    from . import locations, wms
    c = db.conn()
    to = locations.norm_code(to)
    if not locations.get_loc(to):
        raise ValueError(f"没有货位 {to}")
    codes = list(dict.fromkeys(locations.norm_code(x) for x in (codes or []) if str(x).strip()))
    if not codes:
        raise ValueError("先选货位")
    if len(codes) > 500:
        raise ValueError("一次最多搬 500 个货位")
    done, moved, errors = 0, 0, []
    for code in codes:
        if code == to:
            continue
        loc = locations.get_loc(code)
        if not loc:
            errors.append({"code": code, "error": "没有这个货位"})
            continue
        lines = [{"item_id": r["item_id"], "qty": None} for r in c.execute("SELECT item_id FROM inv_loc_qty WHERE loc_id=? AND qty>1e-9", (loc["id"],))]
        if not lines:
            continue
        try:
            r = wms.move(code, to, lines, user, force=force)
            done += 1
            moved += len(r["moved"])
        except ValueError as e:
            c.rollback()
            errors.append({"code": code, "error": str(e)})
    invalidate()
    return {"done": done, "moved": moved, "errors": errors, "to": to}
