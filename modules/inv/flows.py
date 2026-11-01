"""一本库存、按区管（v2.53）：耗材、料卷、包材、备件、成品、工具都放在货位上，只是区不一样。

  生产区     每台打印机一个货架（PR1、PR2…，按打印机设置自动建、打印机增减时跟着变）：第 1 层第 1 位 = 机身 / 外挂料架，
             第 2 层 = AMS 槽（A1–A4 = 位 1–4，B1 = 位 5 …）。货位名字显示「打印机 P1S-01 · 槽 A1」。
  料卷       每卷一个货位（inv_spool_loc）：入库 → 推荐的货位（不自动上架时 → 暂存区 / 待上架），扫码上架；
             上机 → 自动搬到「打印机 · 槽」；下机 → 放回扫的货位（不扫 = 待上架）；用完 / 报废 → 自动拿掉。
             耗材物品（按克）在每个货位上的数 = 这个货位上的料卷剩的克数加起来（料卷是准的，货位跟着它）。
             按称重盘点：毛重 − 空料盘重量（设置 inv_spool_tare_g）= 剩余克数。
  待检区     打印出来的成品（流水 produce：备货打印、多打的、凑齐的套）先进待检区；质检合格 → 推荐的拣货位，
             不合格 → 次品区（报废 / 返工后重新质检）。
  退货区     售后验货放回库存的成品、手工登记的退货先进退货区；检查 → 重新上架 或 次品区。
  暂存区     采购到货（不自动上架时）先放暂存区，待上架列表按分类推荐货位（耗材区 / 包材区 / 拣货区），扫货位确认。
  打包台     设置 inv_pack_station（一个货位）：发货时包材先从这里扣（没设 = 包材区）；成品照旧从拣货区扣。
  提醒       料卷快用完、放太久（过期）、开封太久该烘干 → 今日待办；耗材区 / 包材区低于最低数量 → 从备货区补货任务。
  金额       每个区、每个分类的库存金额（成品按生产成本、买的东西按到手成本）、还够几天、很久没动的。
对外：init、spool_item、spool_sync、route_in、zone_loc、prod_human、sync_printers、on_spool（料卷操作之后）
"""
import re
import time

from core import db
from core.config import load_config, save_config

from . import wms

SCHEMA = """
CREATE TABLE IF NOT EXISTS inv_spool_loc (spool_id INTEGER PRIMARY KEY, loc_id INTEGER, updated_at REAL);
CREATE TABLE IF NOT EXISTS inv_printer_locs (code TEXT PRIMARY KEY, shelf INTEGER, name TEXT, idx INTEGER, active INTEGER DEFAULT 1,
  updated_at REAL);
CREATE TABLE IF NOT EXISTS inv_qc_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, item_id INTEGER, qty REAL, result TEXT,
  from_loc TEXT, to_loc TEXT, username TEXT, note TEXT);
"""
ZONE_DEFAULT = {"production": "PR", "qc": "QC", "returns": "RT", "defect": "DF", "staging": "ST", "pack": "PK", "pick": "A"}
SLOT_RE = re.compile(r"^([A-H])([1-4])$")
EPS = wms.EPS


def _L():
    from . import locations
    return locations


def _now():
    return time.time()


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    if "pid" not in [r[1] for r in c.execute("PRAGMA table_info(inv_printer_locs)")]:
        c.execute("ALTER TABLE inv_printer_locs ADD COLUMN pid TEXT")          # v2.55：按打印机稳定 id 对（改编码 / 互换编码货架不串）
    c.commit()
    try:
        migrate(c)
    except Exception as e:  # noqa: BLE001  迁移失败不影响启动（下次再试）
        import logging
        logging.getLogger("3dops").warning("v2.53 料卷货位迁移没做完：%s", e)


# ---------------- 区 ----------------
def _wms_on(c):
    """用上了货位（有存货的货位，不算打印机）才自动建待检区 / 退货区这些。"""
    return bool(c.execute("SELECT 1 FROM inv_locations l LEFT JOIN inv_loc_groups g ON g.code=l.zone "
                          "WHERE COALESCE(NULLIF(g.ztype,''),'pick')!='production' LIMIT 1").fetchone())


def zone_letter(c, ztype, create=True):
    r = c.execute("SELECT code FROM inv_loc_groups WHERE kind='zone' AND ztype=? ORDER BY code LIMIT 1", (ztype,)).fetchone()
    if r:
        return r["code"]
    if not create:
        return None
    taken = {x[0] for x in c.execute("SELECT code FROM inv_loc_groups WHERE kind='zone'")}
    taken |= {x[0] for x in c.execute("SELECT DISTINCT zone FROM inv_locations")}
    base = ZONE_DEFAULT.get(ztype, "Z")
    cands = [base] + [base[0] + chr(65 + i) for i in range(26)] + [chr(65 + i) + chr(65 + j) for i in range(26) for j in range(26)]
    z = next(x for x in cands if x not in taken)
    _L()._save_group(c, z, "", [])
    c.execute("UPDATE inv_loc_groups SET ztype=?, warehouse=? WHERE code=?", (ztype, wms.default_warehouse(c), z))
    return z


def zone_loc(c, ztype, create=True):
    """这个类型的区的第一个货位（没有就建一个区 + 一个货位，例如待检区 QC1-01-01）。"""
    sk = _L().sort_key
    locs = sorted((l for l in wms._locs(c).values() if l["ztype"] == ztype), key=lambda l: sk(l["code"]))
    if locs:
        return locs[0]
    if not create:
        return None
    z = zone_letter(c, ztype)
    code = _L().make_code(z, 1, 1, 1)
    old = c.execute("SELECT id FROM inv_locations WHERE code=?", (code,)).fetchone()
    if old:
        c.execute("UPDATE inv_locations SET active=1 WHERE id=?", (old["id"],))
    else:
        _L()._insert(c, z, 1, 1, 1)
    d = dict(c.execute("SELECT * FROM inv_locations WHERE code=?", (code,)).fetchone())
    d["ztype"] = ztype
    return d


def route_in(c, it, kind, override=None):
    """入库放哪（v2.53）：退货登记 → 退货区；打印出来的成品 → 待检区；售后放回库存的成品 → 退货区。None = 照原来的规则。"""
    if override:
        loc = _L().get_loc(override)
        return loc if loc and loc["active"] else None
    if it.get("category") != "goods" or not _wms_on(c):
        return None
    cfg = load_config()
    if kind == "produce" and cfg.get("inv_qc_on", True):
        return zone_loc(c, "qc")
    if kind == "return" and cfg.get("inv_returns_zone", True):
        return zone_loc(c, "returns")
    return None


def pack_prefer():
    """发货扣包材先从哪扣：设置的打包台 → 包材区。"""
    st = _L().norm_code(load_config().get("inv_pack_station") or "")
    return ([st] if st else []) + ["pack"]


# ---------------- 生产区：打印机 · 槽 ----------------
def slot_pos(slot):
    s = str(slot or "").strip().upper()
    m = SLOT_RE.match(s)
    if m:
        return 2, (ord(m.group(1)) - 65) * 4 + int(m.group(2))
    if s.isdigit() and 1 <= int(s) <= 32:
        return 2, int(s)
    return 1, 1


def slot_name(layer, pos):
    return "" if int(layer) != 2 else f"{chr(65 + (int(pos) - 1) // 4)}{(int(pos) - 1) % 4 + 1}"


def _ensure(c, z, shelf, layer, pos, note):
    code = _L().make_code(z, shelf, layer, pos)
    r = c.execute("SELECT id FROM inv_locations WHERE code=?", (code,)).fetchone()
    if r:
        c.execute("UPDATE inv_locations SET active=1, note=? WHERE id=?", (note, r["id"]))
    else:
        _L()._insert(c, z, shelf, layer, pos, note)
    return code


def sync_printers(c=None, commit=True):
    """按打印机设置建 / 停用生产区的货位（每台打印机一个货架）。打印机改了编码（同一个位置换了新编码）= 改名，货架不变。"""
    from core import fleet
    c = c or db.conn()
    prs = load_config().get("printers") or []
    cols = [r[1] for r in c.execute("PRAGMA table_info(inv_printer_locs)")]
    if "pid" not in cols:
        c.execute("ALTER TABLE inv_printer_locs ADD COLUMN pid TEXT")
    rows = {r["code"]: dict(r) for r in c.execute("SELECT * FROM inv_printer_locs")}
    if not prs and not rows:
        return {}
    z = zone_letter(c, "production")
    cur = [(i, str(p.get("code") or f"#{i + 1}").upper(), p) for i, p in enumerate(prs)]
    codes = {x[1] for x in cur}
    used = {r["shelf"] for r in rows.values()}
    consumed = set()
    out = {}
    # v2.55：先按稳定 id 认货架（改编码、两台互换编码，货架跟着打印机走）；没有 id 记录的旧行再按编码、序号认
    by_pid = {r["pid"]: r for r in rows.values() if r.get("pid")}
    live = {p.get("id") for _i, _c, p in cur if p.get("id")}
    match = {}
    for i, code, p in cur:
        r = by_pid.get(p.get("id")) if p.get("id") else None
        if r:
            match[i] = r
            consumed.add(r["code"])
    for i, code, p in cur:
        if i in match:
            continue
        r = rows.get(code)
        if r and r["code"] not in consumed and (not r.get("pid") or r.get("pid") == p.get("id") or r.get("pid") not in live):
            match[i] = r
            consumed.add(r["code"])
    for i, code, p in cur:
        if i in match:
            continue
        old = next((x for x in rows.values() if x["idx"] == i and x["code"] not in consumed and (not x.get("pid") or x.get("pid") not in live)
                    and x["code"] not in codes), None)
        if old:
            match[i] = old
            consumed.add(old["code"])
    renames = [(match[i]["code"], code) for i, code, p in cur if i in match and match[i]["code"] != code]
    targets = {n for _o, n in renames}
    for r in rows.values():                               # 已删掉的打印机留下的旧行占着新编码：先让开
        if r["code"] not in consumed and r["code"] in targets:
            newc = f"~old{r['shelf']}~"
            c.execute("UPDATE inv_printer_locs SET code=? WHERE code=?", (newc, r["code"]))
            r["code"] = newc
    for k, (o, _n) in enumerate(renames):                 # 两步改名：A↔B 互换时主键不冲突
        c.execute("UPDATE inv_printer_locs SET code=? WHERE code=?", (f"~~tmp{k}~~", o))
    for k, (_o, n) in enumerate(renames):
        c.execute("UPDATE inv_printer_locs SET code=? WHERE code=?", (n, f"~~tmp{k}~~"))
    for i, code, p in cur:
        r = match.get(i)
        if r:
            shelf = r["shelf"]
        else:
            shelf = next((s_ for s_ in range(1, 100) if s_ not in used), None)
            if shelf is None:
                continue
        used.add(shelf)
        c.execute("INSERT INTO inv_printer_locs(code, shelf, name, idx, active, updated_at, pid) VALUES(?,?,?,?,1,?,?) "
                  "ON CONFLICT(code) DO UPDATE SET shelf=excluded.shelf, name=excluded.name, idx=excluded.idx, active=1, "
                  "updated_at=excluded.updated_at, pid=excluded.pid", (code, shelf, str(p.get("name") or "")[:40], i, _now(), p.get("id")))
        _ensure(c, z, shelf, 1, 1, code)
        if fleet.tech_of(p) != "resin" and fleet.is_multicolor(p):
            for pos in range(1, 5):
                _ensure(c, z, shelf, 2, pos, code)
        c.execute("UPDATE inv_locations SET active=1, note=? WHERE zone=? AND shelf=?", (code, z, shelf))
        out[code] = shelf
    gone = [r for code, r in rows.items() if r["code"] not in consumed and r["active"]]
    if gone:
        wms._tl.syncing = True
        try:
            spool_sync(c)
        finally:
            wms._tl.syncing = False
        # 删掉的打印机上的料卷已经被取下来（fleet.remap）→ 上面先挪到待上架，再停用空的货位
        for r in gone:
            c.execute("UPDATE inv_printer_locs SET active=0 WHERE code=?", (r["code"],))
            for l in c.execute("SELECT id FROM inv_locations WHERE zone=? AND shelf=?", (z, r["shelf"])).fetchall():
                if not c.execute("SELECT 1 FROM inv_loc_qty WHERE loc_id=? AND qty>0", (l["id"],)).fetchone():
                    c.execute("UPDATE inv_locations SET active=0 WHERE id=?", (l["id"],))
    if commit:
        c.commit()
    return out


def prod_human(p, lang="zh"):
    """生产区的货位：(区, 货架, 层, 位) → 「打印机 P1S-01 · 槽 A1」；不是生产区返回 None。"""
    c = db.conn()
    g = c.execute("SELECT ztype FROM inv_loc_groups WHERE code=?", (p[0],)).fetchone()
    if not g or g["ztype"] != "production":
        return None
    r = c.execute("SELECT code FROM inv_printer_locs WHERE shelf=? ORDER BY active DESC LIMIT 1", (p[1],)).fetchone()
    pr = r["code"] if r else f"#{p[1]}"
    sl = slot_name(p[2], p[3])
    if lang == "th":
        return f"เครื่องพิมพ์ {pr} · " + (f"ช่อง {sl}" if sl else "ตัวเครื่อง")
    return f"打印机 {pr} · " + (f"槽 {sl}" if sl else "机身")


def printer_of(code):
    """生产区货位 → (打印机编码, 槽)；不是生产区返回 None。"""
    p = _L().parse(code)
    c = db.conn()
    if not p or (c.execute("SELECT ztype FROM inv_loc_groups WHERE code=?", (p[0],)).fetchone() or {"ztype": ""})["ztype"] != "production":
        return None
    r = c.execute("SELECT code FROM inv_printer_locs WHERE shelf=? AND active=1", (p[1],)).fetchone()
    return (r["code"], slot_name(p[2], p[3])) if r else None


def slot_loc(c, printer_code, slot="", create=True):
    code = str(printer_code or "").upper()
    r = c.execute("SELECT * FROM inv_printer_locs WHERE code=? AND active=1", (code,)).fetchone()
    if not r and create and not getattr(wms._tl, "syncing", False) and any(
            str(p.get("code") or f"#{i + 1}").upper() == code for i, p in enumerate(load_config().get("printers") or [])):
        sync_printers(c, commit=False)
        r = c.execute("SELECT * FROM inv_printer_locs WHERE code=? AND active=1", (code,)).fetchone()
    if not r:
        return None
    z = zone_letter(c, "production")
    layer, pos = slot_pos(slot)
    lc = _ensure(c, z, r["shelf"], layer, pos, code) if create else _L().make_code(z, r["shelf"], layer, pos)
    d = c.execute("SELECT * FROM inv_locations WHERE code=?", (lc,)).fetchone()
    if not d:
        return None
    d = dict(d)
    d["ztype"] = "production"
    return d


# ---------------- 料卷 ----------------
def _has_spools(c):
    return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='spools'").fetchone())


def spool_item(c, item_id):
    """这个物品是不是按料卷管的耗材（有料卷记录的「材料 + 颜色」）。"""
    r = c.execute("SELECT category, material, color FROM inv_items WHERE id=?", (int(item_id),)).fetchone()
    if not r or r["category"] != "filament" or not _has_spools(c):
        return False
    return bool(c.execute("SELECT 1 FROM spools WHERE material=? AND color=? LIMIT 1", (r["material"], r["color"])).fetchone())


def _item_of(c, material, color):
    r = c.execute("SELECT id FROM inv_items WHERE category='filament' AND material=? AND color=? ORDER BY active DESC, id LIMIT 1",
                  (material, color)).fetchone()
    return r["id"] if r else None


def _loc_by_id(c, lid):
    if not lid:
        return None
    r = c.execute("SELECT * FROM inv_locations WHERE id=?", (int(lid),)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["ztype"] = wms.zone_of(d["code"], c)["ztype"]
    return d


def _new_target(c, iid, s):
    """刚入库的一卷放哪：采购到货填的货位 → 自动上架开着：推荐的货位 → 关着：暂存区（有的话）→ 待上架。"""
    pb = getattr(wms._tl, "batch", None)
    if pb and iid and pb["targets"].get(iid):
        loc = _L().get_loc(pb["targets"][iid])
        if loc and loc["active"]:
            return loc
    if not _wms_on(c):
        return None
    if load_config().get("inv_loc_auto", True):
        if iid:
            for p in wms.recommend(iid, max(1.0, float(s["remaining_g"] or 0)), "", c, limit=1):
                if p["qty"] > EPS:
                    return _L().get_loc(p["code"])
        return None
    return zone_loc(c, "staging", create=bool(pb))


def _set_spool(c, s, iid, old, new, kind, user=""):
    c.execute("INSERT INTO inv_spool_loc(spool_id, loc_id, updated_at) VALUES(?,?,?) ON CONFLICT(spool_id) DO UPDATE SET "
              "loc_id=excluded.loc_id, updated_at=excluded.updated_at", (s["id"], new["id"] if new else None, _now()))
    if iid and ((old or {}).get("id") != (new or {}).get("id")):
        wms._log(c, iid, (old or {}).get("code") or "", (new or {}).get("code") or "", max(0.0, float(s["remaining_g"] or 0)), kind, user,
                 s["code"] or "")


def write_qty(c, iid, key, log_kind="", user=""):
    """耗材物品在每个货位上的数 = 这个货位上的料卷剩的克数。log_kind 给了（迁移用）就给每个改动的货位写一条 inv_loc_log。"""
    if not iid:
        return
    sums = {}
    for r in c.execute("SELECT s.remaining_g, l.loc_id FROM spools s JOIN inv_spool_loc l ON l.spool_id=s.id "
                       "WHERE s.material=? AND s.color=? AND s.status!='empty' AND l.loc_id IS NOT NULL", key):
        sums[r["loc_id"]] = sums.get(r["loc_id"], 0.0) + max(0.0, float(r["remaining_g"] or 0))
    old = {r["loc_id"]: r["qty"] for r in c.execute("SELECT loc_id, qty FROM inv_loc_qty WHERE item_id=?", (iid,))}
    for lid in set(old) | set(sums):
        if abs(old.get(lid, 0) - sums.get(lid, 0)) > 1e-6:
            wms._set(c, iid, lid, sums.get(lid, 0.0))
            if log_kind:
                dq = sums.get(lid, 0.0) - old.get(lid, 0)
                lc = (_loc_by_id(c, lid) or {}).get("code") or str(lid)
                wms._log(c, iid, "" if dq > 0 else lc, lc if dq > 0 else "", abs(dq), log_kind, user, "v2.53 料卷货位迁移")
    it = c.execute("SELECT location FROM inv_items WHERE id=?", (iid,)).fetchone()
    if it and not it["location"] and sums:
        store = [(q, _loc_by_id(c, lid)) for lid, q in sums.items()]
        store = [(q, l) for q, l in store if l and l["ztype"] in wms.PUTAWAY_TYPES]
        if store:
            c.execute("UPDATE inv_items SET location=? WHERE id=?", (max(store, key=lambda x: x[0])[1]["code"], iid))


def spool_sync(c=None, item_id=None, key=None, user="", kind=""):
    """料卷的货位跟着状态走（同一个事务，不 commit）：在机上 → 打印机 · 槽；用完 → 拿掉；取下来还在打印机上 → 待上架；
    新入库的 → 推荐的货位。然后把耗材物品在各货位上的克数重算。"""
    c = c or db.conn()
    if not _has_spools(c):
        return
    if item_id:
        r = c.execute("SELECT material, color FROM inv_items WHERE id=?", (int(item_id),)).fetchone()
        keys = [(r["material"], r["color"])] if r else []
    elif key:
        keys = [tuple(key)]
    else:
        keys = [(r[0], r[1]) for r in c.execute("SELECT DISTINCT material, color FROM spools")]
        c.execute("DELETE FROM inv_spool_loc WHERE spool_id NOT IN (SELECT id FROM spools)")
    rows = {r["spool_id"]: r["loc_id"] for r in c.execute("SELECT spool_id, loc_id FROM inv_spool_loc")}
    for k in keys:
        iid = _item_of(c, *k)
        for s in c.execute("SELECT * FROM spools WHERE material=? AND color=?", k).fetchall():
            s = dict(s)
            has = s["id"] in rows
            old = _loc_by_id(c, rows.get(s["id"]))
            if s["status"] == "empty":
                if has:
                    if old and iid:
                        wms._log(c, iid, old["code"], "", 0, "spool_empty", user, s["code"] or "")
                    c.execute("DELETE FROM inv_spool_loc WHERE spool_id=?", (s["id"],))
                continue
            if s["status"] == "loaded" and s["printer"]:
                tgt = slot_loc(c, s["printer"], s["slot"])
                if tgt and (not old or old["id"] != tgt["id"]):
                    _set_spool(c, s, iid, old, tgt, "load", user)
                elif not tgt and not has:
                    _set_spool(c, s, iid, None, None, "load", user)
                continue
            if not has:
                _set_spool(c, s, iid, None, _new_target(c, iid, s), "putaway", user)
            elif old and old["ztype"] == "production":
                _set_spool(c, s, iid, old, None, "unload", user)
        write_qty(c, iid, k)


def on_spool(spool_id, action="", user=""):
    """料卷操作之后（core/materials.spool_action 调）：货位跟着变。"""
    c = db.conn()
    r = c.execute("SELECT material, color FROM spools WHERE id=?", (int(spool_id),)).fetchone()
    if r:
        spool_sync(c, key=(r["material"], r["color"]), user=user)
    else:
        c.execute("DELETE FROM inv_spool_loc WHERE spool_id=?", (int(spool_id),))
    c.commit()


def _spool(sid):
    from core import materials
    s = materials.spool_get(sid)
    if not s:
        raise ValueError(f"没有料卷 {sid}")
    return s


def spool_where(c, sid):
    r = c.execute("SELECT loc_id FROM inv_spool_loc WHERE spool_id=?", (int(sid),)).fetchone()
    return _loc_by_id(c, r["loc_id"]) if r else None


def spool_put(sid, code, user=""):
    """料卷放到一个货位（扫料卷 → 扫货位）。扫的是打印机 · 槽 = 上机。"""
    from core import materials
    s = _spool(sid)
    loc = _L().get_loc(code)
    if not loc or not loc["active"]:
        raise ValueError(f"没有货位 {code}")
    pr = printer_of(loc["code"])
    if pr:
        return spool_load(s["id"], pr[0], pr[1], user)
    if s["status"] == "empty":
        raise ValueError(f"{s['code']} 已经用完了")
    if s["status"] == "loaded":
        materials.spool_action(s["id"], "unload", user)
        s = _spool(s["id"])
    c = db.conn()
    iid = _item_of(c, s["material"], s["color"])
    old = spool_where(c, s["id"])
    loc["ztype"] = wms.zone_of(loc["code"], c)["ztype"]
    _set_spool(c, s, iid, old, loc, "putaway" if not old else "move", user)
    write_qty(c, iid, (s["material"], s["color"]))
    c.commit()
    db.audit(user, "料卷上架", s["code"], f"{(old or {}).get('code') or '待上架'} → {loc['code']}")
    return spool_info(s["id"])


def spool_load(sid, printer, slot="", user=""):
    from core import materials
    s = _spool(sid)
    materials.spool_action(s["id"], "load", user, printer, str(slot or "").strip().upper()[:10])
    return spool_info(s["id"])


def spool_unload(sid, to="", grams=None, user=""):
    from core import materials
    s = _spool(sid)
    materials.spool_action(s["id"], "unload", user, grams=grams)
    if str(to or "").strip():
        return spool_put(s["id"], to, user)
    return spool_info(s["id"])


def tare_g(cfg=None):
    try:
        return max(0.0, float((cfg or load_config()).get("inv_spool_tare_g") or 0))
    except (TypeError, ValueError):
        return 0.0


def _avg(c, iid):
    if not iid:
        return 0.0
    r = c.execute("SELECT avg_cost FROM inv_items WHERE id=?", (iid,)).fetchone()
    return float(r["avg_cost"] or 0) if r else 0.0


def spool_weigh(sid, gross, user="", tare=None):
    """称重盘点一卷：毛重 − 空料盘重量 = 剩余克数。返回 {code, before, after, diff, amount}。"""
    from core import materials
    s = _spool(sid)
    try:
        g = float(gross)
        t = tare_g() if tare in (None, "") else float(tare)
    except (TypeError, ValueError):
        raise ValueError("毛重要填数字（克）")
    if g != g or g < 0 or g > 20000:
        raise ValueError("毛重要填 0–20000 克")
    net = round(max(0.0, g - t), 1)
    before = float(s["remaining_g"] or 0)
    materials.spool_action(s["id"], "weigh", user, grams=net)
    c = db.conn()
    iid = _item_of(c, s["material"], s["color"])
    return {"code": s["code"], "gross": g, "tare": t, "before": round(before, 1), "after": net, "diff": round(net - before, 1),
            "amount": round((net - before) * _avg(c, iid), 2)}


def spool_count(entries, code="", user=""):
    """料卷盘点（称重）：entries [{code, gross}]；code = 在哪个货位盘的（数到的卷放到这个货位，这里本来有、没数到的列出来）。"""
    c = db.conn()
    loc = _L().get_loc(code) if str(code or "").strip() else None
    if str(code or "").strip() and not loc:
        raise ValueError(f"没有货位 {code}")
    rows, seen = [], set()
    for e in entries or []:
        s = _spool(e.get("code"))
        seen.add(s["id"])
        if e.get("gross") not in (None, ""):
            rows.append(spool_weigh(s["id"], e["gross"], user, e.get("tare")))
        if loc:
            w = spool_where(c, s["id"])
            if not w or w["id"] != loc["id"]:
                spool_put(s["id"], loc["code"], user)
    missing = []
    if loc:
        for r in c.execute("SELECT s.code FROM spools s JOIN inv_spool_loc l ON l.spool_id=s.id WHERE l.loc_id=? AND s.status!='empty'",
                           (loc["id"],)):
            sid = c.execute("SELECT id FROM spools WHERE code=?", (r["code"],)).fetchone()["id"]
            if sid not in seen:
                missing.append(r["code"])
    return {"rows": rows, "diff_g": round(sum(x["diff"] for x in rows), 1), "amount": round(sum(x["amount"] for x in rows), 2),
            "missing": missing, "location": loc["code"] if loc else ""}


def spool_info(sid):
    from core import materials
    s = materials.spool_get(sid)
    if not s:
        return None
    s = dict(s)
    s.pop("price", None)
    loc = spool_where(db.conn(), s["id"])
    s["loc"] = _loc_out(loc)
    return s


def _loc_out(loc):
    if not loc:
        return None
    L = _L()
    return {"code": loc["code"], "id": loc["id"], "ztype": loc.get("ztype") or "", "human_zh": L.human(loc["code"]),
            "human_th": L.human(loc["code"], "th")}


def spool_locs():
    """{料卷 id: 货位}（料卷列表显示「放在哪」）。"""
    c = db.conn()
    out = {}
    for r in c.execute("SELECT spool_id, loc_id FROM inv_spool_loc WHERE loc_id IS NOT NULL"):
        out[r["spool_id"]] = _loc_out(_loc_by_id(c, r["loc_id"]))
    return out


def spool_alerts(cfg=None):
    """料卷提醒：快用完、放太久（过期）、开封太久该烘干。[{id, code, kind, level, zh, th}]"""
    from core import materials
    cfg = cfg or load_config()
    c = db.conn()
    if not _has_spools(c):
        return []
    low_g = float(cfg.get("inv_spool_low_g") or 0)
    exp_d = float(cfg.get("inv_spool_expire_days") or 0)
    dry_d = float(cfg.get("inv_spool_dry_days") or 0)
    now = _now()
    out = []
    for r in c.execute("SELECT * FROM spools WHERE status!='empty' AND net_g>0 ORDER BY id"):
        s = dict(r)
        rem = float(s["remaining_g"] or 0)
        where = s["printer"] + (f" · {s['slot']}" if s["slot"] else "") if s["status"] == "loaded" and s["printer"] else ""
        nm = f"{s['code']} {s['material']} {s['color']}"
        if low_g and s["status"] in ("open", "loaded") and rem < low_g:
            out.append({"id": s["id"], "code": s["code"], "kind": "low", "level": "bad" if rem <= low_g / 3 else "warn",
                        "zh": f"料卷 {nm} 快用完了：剩 {rem:.0f} g" + (f"（在 {where}）" if where else ""),
                        "th": f"ม้วน {nm} ใกล้หมด: เหลือ {rem:.0f} g" + (f" (อยู่ที่ {where})" if where else "")})
        if exp_d and s["created_at"] and now - s["created_at"] > exp_d * 86400:
            d = int((now - s["created_at"]) // 86400)
            out.append({"id": s["id"], "code": s["code"], "kind": "expired", "level": "warn",
                        "zh": f"料卷 {nm} 入库 {d} 天了（超过 {exp_d:g} 天），先用掉或检查", "th": f"ม้วน {nm} รับเข้ามา {d} วันแล้ว (เกิน {exp_d:g} วัน) ใช้ก่อนหรือตรวจสอบ"})
        if s["status"] in ("open", "loaded"):
            lim = dry_d or materials.HUMID_DAYS.get(str(s["material"]).upper().split("-")[0], 30)
            since = max(s["opened_at"] or 0, s["dried_at"] or 0)
            if since and now - since > lim * 86400:
                d = int((now - since) // 86400)
                out.append({"id": s["id"], "code": s["code"], "kind": "dry", "level": "warn",
                            "zh": f"料卷 {nm} 开封 / 烘干后 {d} 天了（{s['material']} 超过 {lim:g} 天要烘干）",
                            "th": f"ม้วน {nm} เปิด / อบแล้ว {d} วัน ({s['material']} เกิน {lim:g} วันต้องอบ)"})
    return out


# ---------------- 待检 / 次品 / 退货 ----------------
def _held(c, ztype):
    """这个类型的区里放着的：[(货位, 物品, 数量)]"""
    from core.inventory import ledger
    sk = _L().sort_key
    locs = wms._locs(c)
    out = []
    for r in wms._qty_rows(c):
        l = locs.get(r["loc_id"])
        if l and l["ztype"] == ztype:
            it = c.execute("SELECT * FROM inv_items WHERE id=?", (r["item_id"],)).fetchone()
            if it:
                out.append((l, ledger.item_row(it), r["qty"]))
    return sorted(out, key=lambda x: (sk(x[0]["code"]), x[1]["code"]))


UNAVAILABLE = ("qc", "returns", "defect")


def unavailable_qty(sku):
    """这个成品（SKU）放在待检 / 退货 / 次品区里的数量（还不能卖）；没用货位 = 0。"""
    c = db.conn()
    it = c.execute("SELECT id FROM inv_items WHERE UPPER(code)=? AND category='goods'", (str(sku or "").strip().upper(),)).fetchone()
    if not it:
        return 0
    locs = wms._locs(c)
    if not any(l["ztype"] in UNAVAILABLE for l in locs.values()):
        return 0
    return sum(r["qty"] for r in wms._qty_rows(c, item_id=it["id"])
               if locs.get(r["loc_id"]) and locs[r["loc_id"]]["ztype"] in UNAVAILABLE and r["qty"] > EPS)


def held_list(ztype):
    c = db.conn()
    out = []
    for l, it, q in _held(c, ztype):
        sug = wms.recommend(it["id"], q, "", c, limit=3) if ztype in ("qc", "returns", "staging") else []
        out.append({"item": it, "from": l["code"], "qty": round(q, 6), "suggest": sug})
    return out


def _src(c, ztype, item_id, frm=""):
    if str(frm or "").strip():
        loc = _L().get_loc(frm)
        if not loc:
            raise ValueError(f"没有货位 {frm}")
        return loc
    for l, it, _q in _held(c, ztype):
        if it["id"] == int(item_id):
            return l
    raise ValueError({"qc": "待检区里没有这个物品", "returns": "退货区里没有这个物品", "defect": "次品区里没有这个物品"}.get(ztype, "没有这个物品"))


def _qty(c, item_id, loc, qty):
    have = wms.loc_qty(c, item_id, loc["id"])
    try:
        q = have if qty in (None, "") else float(qty)
    except (TypeError, ValueError):
        raise ValueError(f"数量「{qty}」要填数字")
    if q != q or q <= EPS:
        raise ValueError("数量要大于 0")
    if q > have + 1e-6:
        raise ValueError(f"{loc['code']} 只有 {have:g}")
    return q


def _qc_log(c, item_id, q, result, frm, to, user, note=""):
    c.execute("INSERT INTO inv_qc_log(ts, item_id, qty, result, from_loc, to_loc, username, note) VALUES(?,?,?,?,?,?,?,?)",
              (_now(), int(item_id), q, result, frm or "", to or "", user or "", note or ""))
    c.commit()


def _best(c, item_id, q):
    p = wms.recommend(item_id, q, "", c, limit=1)
    if p and p[0]["qty"] > EPS:
        return p[0]["code"]
    return zone_loc(c, "pick")["code"]


def qc_pass(item_id, qty=None, to="", frm="", user=""):
    """质检合格 → 推荐的拣货位（或扫的货位）。"""
    c = db.conn()
    src = _src(c, "qc", item_id, frm)
    q = _qty(c, item_id, src, qty)
    to = str(to or "").strip() or _best(c, item_id, q)
    r = wms.move(src["code"], to, [{"item_id": int(item_id), "qty": q}], user, kind="qc_pass", force=True)
    _qc_log(c, item_id, q, "pass", src["code"], r["to"], user)
    return r


def _scrap(c, item_id, q, loc_code, user, note):
    from core import inventory as inv
    with wms.prefer([loc_code]):
        return inv.create_doc("scrap", [{"item_id": int(item_id), "qty": q}], note or "次品报废", user, allow_negative=True)


def qc_fail(item_id, qty=None, action="defect", frm="", user="", note=""):
    """质检不合格 → 次品区；action=scrap 直接报废（从次品区扣），rework = 放次品区等返工（返工好了重新质检）。"""
    c = db.conn()
    src = _src(c, "qc", item_id, frm)
    q = _qty(c, item_id, src, qty)
    dl = zone_loc(c, "defect")
    c.commit()
    r = wms.move(src["code"], dl["code"], [{"item_id": int(item_id), "qty": q}], user, kind="qc_fail", force=True)
    _qc_log(c, item_id, q, "fail" if action != "scrap" else "scrap", src["code"], dl["code"], user, note)
    if action == "scrap":
        r["doc"] = _scrap(c, item_id, q, dl["code"], user, note or "质检不合格报废")
    return r


def defect_act(item_id, act, qty=None, frm="", to="", user="", note=""):
    """次品区：scrap 报废 / rework 返工好了 → 待检区重新质检 / restock 检查没问题 → 上架。"""
    c = db.conn()
    src = _src(c, "defect", item_id, frm)
    q = _qty(c, item_id, src, qty)
    if act == "scrap":
        return {"doc": _scrap(c, item_id, q, src["code"], user, note or "次品报废")}
    if act == "rework":
        ql = zone_loc(c, "qc")
        c.commit()
        return wms.move(src["code"], ql["code"], [{"item_id": int(item_id), "qty": q}], user, kind="rework", force=True)
    if act == "restock":
        return wms.move(src["code"], str(to or "").strip() or _best(c, item_id, q), [{"item_id": int(item_id), "qty": q}], user,
                        kind="putaway", force=True)
    raise ValueError("操作不对")


def return_receive(item_id, qty, user="", note=""):
    """登记退货（买家寄回的、没走售后的）：开「退回入库」单，东西放退货区，等检查。"""
    from core import inventory as inv
    c = db.conn()
    rl = zone_loc(c, "returns")
    c.commit()
    with wms.route(rl["code"]):
        d = inv.create_doc("return", [{"item_id": int(item_id), "qty": float(qty)}], note or "退货登记", user)
    return {"doc": d, "to": rl["code"]}


def return_act(item_id, act, qty=None, frm="", to="", user="", note=""):
    """退货区：restock 检查没问题 → 重新上架；defect → 次品区；scrap → 直接报废。"""
    c = db.conn()
    src = _src(c, "returns", item_id, frm)
    q = _qty(c, item_id, src, qty)
    if act == "restock":
        r = wms.move(src["code"], str(to or "").strip() or _best(c, item_id, q), [{"item_id": int(item_id), "qty": q}], user,
                     kind="putaway", force=True)
        _qc_log(c, item_id, q, "return_restock", src["code"], r["to"], user, note)
        return r
    if act in ("defect", "scrap"):
        dl = zone_loc(c, "defect")
        c.commit()
        r = wms.move(src["code"], dl["code"], [{"item_id": int(item_id), "qty": q}], user, kind="return_defect", force=True)
        _qc_log(c, item_id, q, "return_defect", src["code"], dl["code"], user, note)
        if act == "scrap":
            r["doc"] = _scrap(c, item_id, q, dl["code"], user, note or "退货报废")
        return r
    raise ValueError("操作不对")


# ---------------- 金额：按区 / 分类、还够几天、很久没动 ----------------
def value_report(slow_days=None):
    from core.inventory import ledger
    cfg = load_config()
    slow_days = int(float(slow_days or cfg.get("inv_slow_days") or 60))
    c = db.conn()
    now = _now()
    locs = wms._locs(c, active=False)
    zs, _wn, _d = wms.zinfo(c)
    items = {r["id"]: dict(r) for r in c.execute("SELECT * FROM inv_items WHERE active=1")}
    ztypes, zones, located = {}, {}, {}
    for r in wms._qty_rows(c):
        it, l = items.get(r["item_id"]), locs.get(r["loc_id"])
        if not it or not l:
            continue
        v = r["qty"] * float(it["avg_cost"] or 0)
        located[it["id"]] = located.get(it["id"], 0) + r["qty"]
        t = ztypes.setdefault(l["ztype"], {"ztype": l["ztype"], "value": 0.0, "items": set()})
        t["value"] += v
        t["items"].add(it["id"])
        z = zones.setdefault(l["zone"], {"zone": l["zone"], "ztype": l["ztype"], "name": (zs.get(l["zone"]) or {}).get("name", ""),
                                         "value": 0.0, "items": set()})
        z["value"] += v
        z["items"].add(it["id"])
    cats = {}
    for it in items.values():
        q = float(it["qty"] or 0)
        if q <= EPS:
            continue
        v = q * float(it["avg_cost"] or 0)
        cc = cats.setdefault(it["category"], {"category": it["category"], "value": 0.0, "items": 0})
        cc["value"] += v
        cc["items"] += 1
        u = q - located.get(it["id"], 0)
        if u > 1e-6:
            t = ztypes.setdefault("unplaced", {"ztype": "unplaced", "value": 0.0, "items": set()})
            t["value"] += u * float(it["avg_cost"] or 0)
            t["items"].add(it["id"])
    used = {r[0]: float(r[1] or 0) for r in c.execute(
        "SELECT item_id, -SUM(qty) FROM inv_moves WHERE qty<0 AND ts>=? AND kind NOT IN ('adjust','po_return') GROUP BY item_id",
        (now - 30 * 86400,))}
    last = {r[0]: r[1] for r in c.execute("SELECT item_id, MAX(ts) FROM inv_moves GROUP BY item_id")}
    cover, slow = [], []
    for it in items.values():
        q = float(it["qty"] or 0)
        if q <= EPS:
            continue
        row = ledger.item_row(it)
        brief = {"id": it["id"], "code": it["code"], "name_zh": it["name_zh"], "name_th": it["name_th"], "category": it["category"],
                 "unit": it["unit"], "qty": q, "value": round(row["value"], 2)}
        daily = used.get(it["id"], 0) / 30.0
        if daily > EPS:
            cover.append(dict(brief, daily=round(daily, 3), days=round(q / daily, 1)))
        lt = last.get(it["id"]) or it["created_at"] or now
        if now - lt > slow_days * 86400:
            slow.append(dict(brief, idle_days=int((now - lt) // 86400)))
    cover.sort(key=lambda x: x["days"])
    slow.sort(key=lambda x: -x["value"])
    total = sum(x["value"] for x in cats.values())
    days = sum(x["days"] * x["value"] for x in cover) / max(EPS, sum(x["value"] for x in cover)) if cover else None
    fix = lambda d: [dict(v, value=round(v["value"], 2), items=len(v["items"]) if isinstance(v["items"], set) else v["items"]) for v in d]
    order = list(wms.ZTYPES) + ["unplaced"]
    return {"total": {"value": round(total, 2), "items": sum(x["items"] for x in cats.values()), "slow_n": len(slow),
                      "slow_value": round(sum(x["value"] for x in slow), 2), "cover_days": round(days, 1) if days is not None else None},
            "ztypes": sorted(fix(ztypes.values()), key=lambda x: order.index(x["ztype"]) if x["ztype"] in order else 99),
            "zones": sorted(fix(zones.values()), key=lambda x: x["zone"]),
            "categories": sorted(fix(cats.values()), key=lambda x: -x["value"]),
            "cover": cover[:30], "slow": slow[:50], "slow_days": slow_days}


# ---------------- 迁移 ----------------
def _backup_qty(c, iid):
    """迁移要重写这个耗材物品各货位的数量之前，先把它现有的 inv_loc_qty 行备份进 inv_loc_qty_bak253（每个 物品×货位 只存第一次的，重复跑不覆盖）。"""
    c.execute("CREATE TABLE IF NOT EXISTS inv_loc_qty_bak253 (item_id INTEGER, loc_id INTEGER, qty REAL, updated_at REAL, backed_at REAL, PRIMARY KEY(item_id, loc_id))")
    c.execute("INSERT OR IGNORE INTO inv_loc_qty_bak253(item_id, loc_id, qty, updated_at, backed_at) "
              "SELECT item_id, loc_id, qty, updated_at, ? FROM inv_loc_qty WHERE item_id=?", (_now(), int(iid)))


def _qc_default_for_existing(c):
    """升级的老安装：设置里没明确选过 inv_qc_on 的，质检区默认关（否则升级后每个打印出来的成品都进待检区、算不可售，库存推送变 0）。
    新安装（还没有任何物品）照默认开。关掉的同时记一个一次性提示（仓库页提醒可以开质检）。"""
    # config.json 里有没有 inv_qc_on 不可靠（save_config 会把模块默认值都写进去），所以以迁移标记为准：
    # 只在 v2.53 迁移还没做过时调用（migrate 保证），已有物品 = 老安装 → 明确写成关。
    try:
        if load_config().get("inv_loc_v253"):
            return
        if c.execute("SELECT 1 FROM inv_items LIMIT 1").fetchone():
            save_config({"inv_qc_on": False, "inv_qc_hint253": True})
    except Exception:  # noqa: BLE001
        pass


def migrate(c=None):
    """v2.52 → v2.53（只做一次，再跑也不会重复）：在机上的料卷 → 那台打印机 · 槽；其它的 → 耗材物品原来放的货位（v2.52 放过的），
    没放过的 → 待上架。其它物品的货位数量（inv_loc_qty）不动。成品备货的目标数量不动（还在生产模块的 stock 表）。"""
    c = c or db.conn()
    if load_config().get("inv_loc_v253"):
        return 0
    _qc_default_for_existing(c)
    n = 0
    if _has_spools(c):
        if load_config().get("printers"):
            sync_printers(c, commit=False)
        have = {r[0] for r in c.execute("SELECT spool_id FROM inv_spool_loc")}
        keys = set()
        for s in c.execute("SELECT * FROM spools WHERE status!='empty' ORDER BY id").fetchall():
            if s["id"] in have:
                continue
            k = (s["material"], s["color"])
            iid = _item_of(c, *k)
            tgt = None
            if s["status"] == "loaded" and s["printer"]:
                tgt = slot_loc(c, s["printer"], s["slot"])
            elif iid:
                it = c.execute("SELECT location FROM inv_items WHERE id=?", (iid,)).fetchone()
                home = _L().get_loc(it["location"]) if it and it["location"] else None
                if home and wms.loc_qty(c, iid, home["id"]) > EPS:
                    tgt = home
            c.execute("INSERT OR IGNORE INTO inv_spool_loc(spool_id, loc_id, updated_at) VALUES(?,?,?)", (s["id"], tgt["id"] if tgt else None, _now()))
            keys.add(k)
            n += 1
        for k in keys:
            iid = _item_of(c, *k)
            if iid:
                _backup_qty(c, iid)
                write_qty(c, iid, k, "migrate", "系统")
    c.commit()
    save_config({"inv_loc_v253": True})
    if n:
        db.audit("系统", "料卷放进货位（v2.53）", f"{n} 卷", "在机上的 → 打印机 · 槽；其它 → 原来的货位 / 待上架")
    return n
