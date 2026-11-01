"""v2.54 打印机机群接口（生产 → 打印机 页）：总览 + 分页列表、单台详情（抽屉）、添加 / 修改 / 移除、厂家表单、
测试连接（拓竹顺便检查局域网模式 / 访问码 / 序列号）、批量操作、局域网发现、Excel / CSV 导入、机型模板、二维码标签。

打印机在接口里用稳定 id（也认机器编码和旧的序号）；新加的打印机只往后加，已有的序号不变。
改动都会：保存设置 → 通知仓库（生产区货位）→ 重新排单。写操作只有老板能做（module.py 的 owner_only）。
"""
import datetime as _dt
import threading
import time

from flask import request

from web.common import *  # noqa: F401,F403
from core import fleet, fleetcodes

from .api import bp

_EDIT = threading.Lock()
def TH():
    """错误信息用哪种语言：?lang=th，或者账号的界面语言是泰文。"""
    if request.args.get("lang"):
        return request.args.get("lang") == "th"
    return ((auth.current_user() or {}).get("lang") or "") == "th"


def _e(pairs):
    """[(中文, 泰文)] → 一条错误（按界面语言）。"""
    return "；".join(p[1] if TH() else p[0] for p in pairs)


def _cfg_printers():
    cfg = load_config()
    return cfg, cfg.get("printers") or []


def _find(key):
    cfg, prs = _cfg_printers()
    i = fleet.index_of(prs, key)
    return cfg, prs, i


def _after_change(cfg, reschedule=True):
    """保存后：仓库生产区货位跟着变、重新排单。"""
    from core import chain, modules
    try:
        modules.emit("printers.changed", printers=cfg["printers"])
    except Exception:  # noqa: BLE001
        pass
    if reschedule:
        try:
            chain.reschedule()
        except Exception:  # noqa: BLE001
            pass


def _mask_conn(c, owner):
    c = dict(c or {})
    if c.get("access_code"):
        c["access_code"] = "******" if owner else ""
    if not owner:
        c = {"type": c.get("type", "none"), "loaded": c.get("loaded", ""), "host": c.get("host", "")}
    return c


def _today0():
    d = _dt.datetime.now()
    return _dt.datetime(d.year, d.month, d.day).timestamp()


def _stats_today(n):
    """今天每台打印机：打好的件数、打印时长（小时，和今天的时间段重叠的部分）。"""
    t0, now = _today0(), time.time()
    c = db.conn()
    made = {}
    busy = {}
    for r in c.execute("SELECT printer, status, count, started_at, ended_at FROM print_runs WHERE printer IS NOT NULL AND "
                       "(status='printing' OR ended_at>=?)", (t0,)):
        i = r["printer"]
        if r["status"] == "done":
            made[i] = made.get(i, 0) + int(r["count"] or 0)
        s, e = max(r["started_at"] or t0, t0), min(r["ended_at"] or now, now)
        if e > s:
            busy[i] = busy.get(i, 0) + (e - s) / 3600
    return made, busy, (now - t0) / 3600


def _maint_due(n):
    """要保养的打印机（一次查完，几千台也快）。返回 {序号: [到期项目]}。"""
    from core import production
    c = db.conn()
    hours = {r["printer"]: r["h"] or 0 for r in c.execute(
        "SELECT printer, SUM(CASE WHEN ended_at IS NOT NULL THEN (ended_at-started_at)/3600.0 ELSE 0 END) AS h "
        "FROM print_runs WHERE status IN ('done','failed') AND printer IS NOT NULL GROUP BY printer")}
    last = {}
    for r in c.execute("SELECT printer, item, MAX(hours_at) h FROM maintenance GROUP BY printer, item"):
        last[(r["printer"], r["item"])] = r["h"] or 0
    out = {}
    for i in range(n):
        h = hours.get(i, 0)
        due = [k for k, _l, every in production.MAINT_ITEMS if h - last.get((i, k), 0) >= every]
        if due:
            out[i] = due
    return out


STATE_GROUP = {"printing": "printing", "paused": "printing", "idle": "idle", "finished": "idle", "failed": "error",
               "offline": "offline", "unknown": "offline", "none": "none"}


def _row(i, p, st, run, made, busy, hours_today, due, owner):
    c = p.get("conn") or {}
    state = st.get("state") or "none"
    if state == "none" and (c.get("type") or "none") != "none":
        state = "unknown"
    return {"id": p.get("id"), "index": i, "code": p.get("code") or f"#{i + 1}", "name": p.get("name") or "",
            "group": p.get("group") or "", "location": p.get("location") or "", "role": p.get("role") or "any",
            "paused": bool(p.get("paused")), "enabled": p.get("enabled", True) is not False,
            "dedicated_po": p.get("dedicated_po") or "", "tech": fleet.tech_of(p),
            "state": state, "sg": STATE_GROUP.get(state, "offline"), "progress": st.get("progress"),
            "file": st.get("file") or "", "remaining_min": st.get("remaining_min"), "error": st.get("error") or "",
            "host": c.get("host") or "", "vendor": fleet.vendor_of(p),
            "serial": (c.get("serial") or "") if owner else "",
            "run": {k: run[k] for k in ("id", "sku", "name", "color", "count")} if run else None,
            "made_today": made.get(i, 0), "util_today": round(min(1.0, busy.get(i, 0) / hours_today), 3) if hours_today > 0 else 0,
            "maint_due": due.get(i) or [], "ovr": sorted((p.get("ovr") or {}).keys())}


def _match(r, a):
    if a.get("status"):
        want = a["status"]
        if want == "maint":
            if not r["maint_due"]:
                return False
        elif want == "paused":
            if not r["paused"]:
                return False
        elif want == "disabled":
            if r["enabled"]:
                return False
        elif r["sg"] != want:
            return False
    if a.get("model") and r["name"] != a["model"]:
        return False
    if "group" in a and a.get("group") is not None and a.get("group") != "*" and r["group"] != a["group"]:
        return False
    if a.get("role") and r["role"] != a["role"]:
        return False
    q = (a.get("q") or "").strip().lower()
    if q:
        hay = " ".join([r["code"], r["host"], r["serial"], r["name"], r["location"], r["group"]]).lower()
        if q not in hay:
            return False
    return True


@bp.get("/api/fleet")
def fleet_overview():
    """总览：数字卡片、机群地图（每台一个色块）、分页列表。?status=printing|idle|error|offline|none|maint|paused|disabled
    &model=&group=&role=&q=&page=1&per=50&sort=code|state|group|util"""
    from core import printers as printers_mod, production
    a = {k: v for k, v in request.args.items()}
    if "group" not in request.args:
        a["group"] = None
    cfg, prs = _cfg_printers()
    owner = auth.is_owner()
    st_all = printers_mod.get_status()
    runs = {r["printer"]: r for r in production.active_runs()}
    made, busy, hours_today = _stats_today(len(prs))
    due = _maint_due(len(prs))
    rows = [_row(i, p, st_all.get(i) or {}, runs.get(i), made, busy, hours_today, due, owner) for i, p in enumerate(prs)]
    en = [r for r in rows if r["enabled"]]
    k = {"total": len(rows), "enabled": len(en),
         "online": sum(1 for r in en if r["sg"] in ("printing", "idle")),
         "printing": sum(1 for r in en if r["sg"] == "printing"), "idle": sum(1 for r in en if r["sg"] == "idle"),
         "error": sum(1 for r in en if r["sg"] == "error"), "offline": sum(1 for r in en if r["sg"] == "offline"),
         "none": sum(1 for r in en if r["sg"] == "none"),
         "maint": sum(1 for r in rows if r["maint_due"]), "paused": sum(1 for r in rows if r["paused"]),
         "made_today": sum(r["made_today"] for r in rows),
         "util_today": round(sum(busy.get(r["index"], 0) for r in en) / (hours_today * len(en)), 3) if en and hours_today > 0 else 0}
    by_model = {}
    by_group = {}
    for r in rows:
        by_model[r["name"]] = by_model.get(r["name"], 0) + 1
        by_group.setdefault(r["group"], {"n": 0, "printing": 0})
        by_group[r["group"]]["n"] += 1
        by_group[r["group"]]["printing"] += r["sg"] == "printing"
    hit = [r for r in rows if _match(r, a)]
    sort = a.get("sort") or "code"
    keyf = {"code": lambda r: (r["code"],), "state": lambda r: (r["sg"], r["code"]),
            "group": lambda r: (r["group"], r["location"], r["code"]), "util": lambda r: (-r["util_today"], r["code"])}.get(sort)
    if keyf:
        hit.sort(key=keyf)
    per = max(10, min(200, int(a.get("per") or 50)))
    page = max(1, int(a.get("page") or 1))
    tiles = [{"id": r["id"], "code": r["code"], "g": r["group"], "loc": r["location"], "sg": r["sg"], "p": r["paused"],
              "en": r["enabled"], "pr": r["progress"] if r["sg"] == "printing" else None, "m": bool(r["maint_due"])}
             for r in sorted(hit, key=lambda r: (r["group"], r["location"], r["code"]))]
    return jsonify({"kpis": k, "total": len(hit), "page": page, "per": per, "rows": hit[(page - 1) * per: page * per],
                    "tiles": tiles, "models": by_model, "groups": by_group, "owner": owner})


def _detail(cfg, prs, i):
    from core import printers as printers_mod, production
    p = prs[i]
    owner = auth.is_owner()
    st = printers_mod.get_status(i)
    c = db.conn()
    made, busy, hours_today = _stats_today(len(prs))
    due = _maint_due(len(prs))
    run = next((r for r in production.active_runs() if r["printer"] == i), None)
    row = _row(i, p, st, run, made, busy, hours_today, due, owner)
    tpl = fleet.template_of(p.get("name"), cfg)
    fields = []
    for f in fleet.TPL_FIELDS:
        fields.append({"key": f, "template": tpl.get(f), "override": (p.get("ovr") or {}).get(f), "value": p.get(f)})
    hist = [dict(r) for r in c.execute("SELECT id, sku, name, color, count, status, started_at, ended_at, fail_reason FROM print_runs "
                                       "WHERE printer=? ORDER BY id DESC LIMIT 20", (i,))]
    maint = [dict(r) for r in c.execute("SELECT item, ts, hours_at, username, note FROM maintenance WHERE printer=? ORDER BY id DESC LIMIT 10", (i,))]
    ms = None
    try:
        h = production.printer_hours(i)
        items = []
        for key, label, every in production.MAINT_ITEMS:
            last = c.execute("SELECT * FROM maintenance WHERE printer=? AND item=? ORDER BY id DESC LIMIT 1", (i, key)).fetchone()
            since = h - (last["hours_at"] if last else 0)
            items.append({"item": key, "label": label, "every_h": every, "since_h": round(since, 1), "due": since >= every})
        ms = {"hours": h, "items": items}
    except Exception:  # noqa: BLE001
        pass
    vend = fleet.vendor_of(p)
    return {"printer": dict({k: v for k, v in p.items() if k not in ("conn", "_eff")}, conn=_mask_conn(p.get("conn"), owner)),
            "row": row, "status": st, "status_zh": printers_mod.STATE_ZH.get(st.get("state") or "none", ""),
            "fields": fields, "template": tpl, "vendor": vend, "vendors": fleet.vendors_for(p.get("name")),
            "history": hist, "maint_log": maint, "maintenance": ms, "owner": owner}


@bp.get("/api/fleet/meta")
def fleet_meta():
    cfg = load_config()
    models = [dict(m, vendor=fleet.vendor_of_model(m["name"]), vendors=fleet.vendors_for(m["name"])) for m in fleet.MODELS]
    known = {m["name"] for m in fleet.MODELS}
    for n in list((cfg.get("printer_models") or {}).keys()) + [p.get("name") for p in cfg.get("printers") or []]:
        if n and n not in known:
            known.add(n)
            models.append({"name": n, "prefix": fleet.prefix_for(n), "brand": "", "vendor": "none", "vendors": fleet.vendors_for(n)})
    return jsonify({"vendors": fleet.VENDORS, "models": models, "roles": fleet.ROLE_ZH, "tpl_fields": fleet.TPL_FIELDS,
                    "templates": {n: fleet.template_of(n, cfg) for n in {p.get("name") for p in cfg.get("printers") or []} | set(cfg.get("printer_models") or {})},
                    "groups": sorted({p.get("group") or "" for p in cfg.get("printers") or []} - {""}),
                    "workers": cfg.get("printer_workers") or {}})


@bp.get("/api/fleet/printers/<key>")
def fleet_printer_get(key):
    cfg, prs, i = _find(key)
    if i is None:
        return err("打印机不存在")
    d = _detail(cfg, prs, i)
    d["stale_label"] = fleet.stale_label(prs, key)         # v2.55.0：用旧标签的编码扫到的，但这个编码已经换给别的打印机了
    return jsonify(d)


def _apply_fields(p, b, cfg, errs):
    """修改一台的普通字段（编码、机型、分组、位置、用途、专用生产单、暂停、启用、备注、单台覆盖）。"""
    if "code" in b:
        code = str(b.get("code") or "").strip().upper()
        if code and not fleet.CODE_RE.match(code):
            errs.append((f"机器编码「{code}」只能用英文、数字和 - _，最多 16 位", f"รหัสเครื่อง «{code}» ใช้ได้เฉพาะอังกฤษ ตัวเลข - _ ไม่เกิน 16 ตัว"))
        elif code:
            was = p.get("code")
            p["code"] = code
    if b.get("name"):
        name = fleet.known_model(b["name"], cfg) or str(b["name"]).strip()[:40]
        if name != p.get("name"):
            p["name"] = name
            p["ovr"] = {}                   # 换了机型：单台覆盖清空，跟新机型的模板
            p.pop("_eff", None)
            for f in fleet.TPL_FIELDS:
                p.pop(f, None)
            p["tech"] = (fleet.model_info(name) or {}).get("tech", p.get("tech") or "fdm")
    for k, n in (("group", 30), ("location", 30), ("note", 40), ("dedicated_po", 40)):
        if k in b:
            p[k] = str(b.get(k) or "").strip()[:n]
    if "role" in b:
        if b["role"] not in fleet.ROLES:
            errs.append(("用途不对", "การใช้งานไม่ถูกต้อง"))
        else:
            p["role"] = b["role"]
    for k in ("paused", "enabled"):
        if k in b:
            p[k] = b[k] not in (False, "false", "0", 0, "", None)
    if isinstance(b.get("ovr"), dict):
        o = dict(p.get("ovr") or {})
        for f, v in b["ovr"].items():
            if f not in fleet.TPL_FIELDS:
                continue
            cv = fleet.clean_value(f, v)
            if v not in (None, "", "auto") and cv is None:
                errs.append((f"「{f}」的值不对：{v}", f"ค่า «{f}» ไม่ถูกต้อง: {v}"))
            elif cv is None:
                o.pop(f, None)
            else:
                o[f] = cv
        p["ovr"] = o
        p.pop("_eff", None)
        for f in fleet.TPL_FIELDS:
            p.pop(f, None)


def _apply_conn(p, b, errs):
    if "vendor" not in b:
        return
    vendor = b.get("vendor") or "none"
    old = p.get("conn") or {}
    conn, ce = fleet.validate_conn(vendor, b.get("conn") or b, old)
    errs += ce
    if conn is not None and not ce:
        p["conn"] = conn


def _save(cfg, prs, reschedule=True, renames=None):
    out = save_config({"printers": prs})
    if renames:         # v2.55：改了编码 → 料卷 / 出入库记录里的编码先跟着改，再通知仓库同步货位
        fleetcodes.rename_codes(renames)
    _after_change(out, reschedule)
    return out


@bp.post("/api/fleet/printers/<key>")
def fleet_printer_save(key):
    b = request.get_json(force=True) or {}
    with _EDIT:
        cfg, prs, i = _find(key)
        if i is None:
            return err("打印机不存在")
        p = dict(prs[i])
        errs = []
        _apply_fields(p, b, cfg, errs)
        _apply_conn(p, b, errs)
        if p.get("code") != prs[i].get("code"):          # v2.55：不分大小写查重
            ce = fleetcodes.check_code(p.get("code"), prs, exclude_id=p.get("id"))
            if ce:
                errs.append(ce)
        if errs:
            return err(_e(errs))
        old = [dict(x) for x in prs]
        prs[i] = p
        ren = [(old[i].get("code"), p.get("code"))] if old[i].get("code") != p.get("code") else None
        if ren:
            fleetcodes.migrate_po_refs()                 # v2.55.0：和批量重新编号同一套：生产单先换成稳定 id、旧编码记下来
            fleetcodes.note_code_changes(old, prs)
        cfg = _save(cfg, prs, renames=ren)
        sug = fleetcodes.suggest_after_move([old[i]], [cfg["printers"][i]], cfg) if "code" not in b or old[i].get("code") == p.get("code") else []
    from core import printers as printers_mod
    printers_mod.poll_once(i, cfg["printers"][i])
    db.audit(_uname(), "修改打印机", p.get("code"), ",".join(sorted(b.keys())))
    d = _detail(cfg, cfg["printers"], i)
    d["renumber_suggest"] = sug                # v2.55：改了位置 / 分组，编码里带着旧的 → 页面问「要按新位置重新编号吗？」
    return jsonify(d)


def _new_printer(cfg, prs, b, errs, code=None):
    name = fleet.known_model(b.get("name") or b.get("model"), cfg)
    if not name:
        errs.append((f"请选机型（认不出「{b.get('name') or b.get('model') or ''}」）", f"กรุณาเลือกรุ่น (ไม่รู้จัก «{b.get('name') or b.get('model') or ''}»)"))
        return None
    m = fleet.model_info(name) or {}
    p = {"id": fleet.new_id(), "code": "", "name": name, "enabled": True, "tech": m.get("tech", "fdm"), "note": "",
         "conn": {"type": "none"}, "ovr": {}}
    p.update(fleet.NEW_DEFAULTS)
    bb = dict(b)
    bb.pop("name", None)
    bb.pop("code", None)
    if p["tech"] != "resin":
        # v2.54 复审：喷嘴是每台自己的值，要明确填（界面默认显示 0.4 让人确认），不从机型模板 / 同机型别的打印机继承
        raw_n = b.get("nozzle", (b.get("ovr") or {}).get("nozzle") if isinstance(b.get("ovr"), dict) else None)
        nz = fleet.clean_value("nozzle", raw_n) if raw_n not in (None, "") else None
        if nz is None:
            errs.append(("请确认这台打印机的喷嘴直径（例如 0.4）", "กรุณายืนยันขนาดหัวฉีดของเครื่องนี้ (เช่น 0.4)"))
        else:
            bb["ovr"] = dict(bb.get("ovr") if isinstance(bb.get("ovr"), dict) else {}, nozzle=nz)
    _apply_fields(p, bb, cfg, errs)
    if b.get("vendor"):
        _apply_conn(p, b, errs)
    code = (code or str(b.get("code") or "")).strip().upper()
    if code:
        ce = fleetcodes.check_code(code, prs)          # v2.55：不分大小写查重 + 字符检查
        if ce:
            errs.append(ce)
        p["code"] = code
    else:                                              # 没填 = 按编码规则（分组有自己的规则就用它）自动编
        c0, prob = fleetcodes.generate(prs, [p], cfg)[0]
        if prob:
            errs.append(fleetcodes.PROBLEM[prob])
        p["code"] = c0
    host = (p.get("conn") or {}).get("host")
    if host and any((x.get("conn") or {}).get("host") == host for x in prs):
        errs.append((f"IP {host} 已经有别的打印机在用", f"IP {host} มีเครื่องอื่นใช้อยู่แล้ว"))
    return p


@bp.post("/api/fleet/printers")
def fleet_printer_add():
    """添加：{name: 机型, n: 台数, vendor, conn:{host, serial, access_code, port}, code, group, location, role}。
    一次加多台时不带连接（IP 不能重复），之后在抽屉里逐台填，或用「局域网发现」/「导入」。"""
    b = request.get_json(force=True) or {}
    n = max(1, min(500, int(b.get("n") or 1)))
    with _EDIT:
        cfg, prs = _cfg_printers()
        if len(prs) + n > 5000:
            return err("打印机最多 5000 台")
        added = []
        for _k in range(n):
            errs = []
            bb = dict(b) if n == 1 else {k: v for k, v in b.items() if k not in ("vendor", "conn", "code")}
            p = _new_printer(cfg, prs, bb, errs)
            if errs:
                return err(_e(errs))
            prs.append(p)
            added.append(p["id"])
        cfg = _save(cfg, prs)
    db.audit(_uname(), "添加打印机", ",".join(p.get("code") for p in cfg["printers"] if p.get("id") in added)[:200], str(n))
    from core import printers as printers_mod
    for i, p in enumerate(cfg["printers"]):
        if p.get("id") in added:
            printers_mod.poll_once(i, p)
    return jsonify({"added": added, "codes": [p.get("code") for p in cfg["printers"] if p.get("id") in added]})


@bp.delete("/api/fleet/printers/<key>")
def fleet_printer_delete(key):
    """移除一台：正在打印的不能移除；排给它还没开始的任务重新排单；打印记录保留（序号对到新位置）。"""
    with _EDIT:
        cfg, prs, i = _find(key)
        if i is None:
            return err("打印机不存在")
        if len(prs) <= 1:
            return err("至少要保留一台打印机")
        old = [dict(x) for x in prs]
        new = prs[:i] + prs[i + 1:]
        busy = fleet.busy_codes(old, new)
        if busy:
            return err("这台打印机还有正在打印的任务，不能移除（先在生产看板里点「打完」或「失败」）")
        cfg = save_config({"printers": new})
        fleet.remap(old, cfg["printers"])
        _after_change(cfg)
    db.audit(_uname(), "移除打印机", old[i].get("code"), old[i].get("name"))
    return jsonify({"ok": True})


@bp.post("/api/fleet/printers/<key>/test")
def fleet_printer_test(key):
    """测试连接（按厂家）：拓竹另外列出 局域网模式（8883 / 990 端口）、访问码、序列号、开发者模式 的检查结果。"""
    from core import netdiag, printers as printers_mod
    b = request.get_json(force=True, silent=True) or {}
    cfg, prs, i = _find(key)
    if i is None:
        return err("打印机不存在")
    p = dict(prs[i])
    if b.get("vendor"):                     # 还没保存的表单也能先测
        errs = []
        _apply_conn(p, b, errs)
        if errs:
            return err(_e(errs))
    return jsonify(run_test(p, netdiag, printers_mod, i if not b.get("vendor") else None, cfg, prs))


def run_test(p, netdiag, printers_mod, save_idx=None, cfg=None, prs=None):
    c = p.get("conn") or {}
    host = (c.get("host") or "").strip()
    vend = fleet.vendor_of(p)
    out = {"ok": False, "vendor": vend, "checks": [], "status": None, "message": ""}

    def chk(k, ok, zh, th):
        out["checks"].append({"key": k, "ok": ok, "zh": zh, "th": th})
    if vend == "none" or not host:
        out["message"] = "这台打印机没有设置连接"
        return out
    if vend == "bambu":
        ports = {pp: netdiag.probe_port(host, pp, 2.0)["kind"] for pp in (8883, 990)}
        lan = ports[8883] == "ok"
        chk("lan", lan, "局域网模式：8883 端口" + ("通" if lan else "不通（打印机没开「局域网模式」，或 IP 不对 / 不在同一个网络）"),
            "โหมด LAN: พอร์ต 8883 " + ("เชื่อมต่อได้" if lan else "ไม่ได้ (เครื่องยังไม่เปิด «โหมด LAN» หรือ IP ผิด / ไม่อยู่ในเครือข่ายเดียวกัน)"))
        chk("ftps", ports[990] == "ok", "传文件：990 端口" + ("通" if ports[990] == "ok" else "不通（发送打印要用）"),
            "ส่งไฟล์: พอร์ต 990 " + ("เชื่อมต่อได้" if ports[990] == "ok" else "ไม่ได้ (ต้องใช้ตอนส่งงานพิมพ์)"))
        if not lan:
            out["message"] = netdiag.fail_message(host)
            return out
    try:
        t, st = printers_mod.test(p)
        out.update(ok=True, type=t, status=st, status_zh=printers_mod.STATE_ZH.get(st.get("state"), ""))
        if vend == "bambu":
            chk("auth", True, "访问码：对", "รหัสเข้าถึง: ถูกต้อง")
            chk("status", True, "序列号：对（收到了打印机状态）", "หมายเลขซีเรียล: ถูกต้อง (ได้รับสถานะเครื่องแล้ว)")
        else:
            chk("status", True, "读到打印机状态", "อ่านสถานะเครื่องได้แล้ว")
    except Exception as e:  # noqa: BLE001
        m = str(e)
        out["message"] = printers_mod._human_err(e)
        if vend == "bambu":
            auth_bad = "访问码" in m or "授权" in m
            chk("auth", not auth_bad, "访问码：" + ("不对（打印机屏幕 设置 → 网络 看访问码，重新打开局域网模式会变）" if auth_bad else "对"),
                "รหัสเข้าถึง: " + ("ไม่ถูกต้อง (ดูที่หน้าจอ ตั้งค่า → เครือข่าย เปิดโหมด LAN ใหม่รหัสจะเปลี่ยน)" if auth_bad else "ถูกต้อง"))
            if not auth_bad:
                chk("status", False, "序列号：没收到打印机状态，请检查序列号", "หมายเลขซีเรียล: ไม่ได้รับสถานะเครื่อง กรุณาตรวจหมายเลขซีเรียล")
        else:
            chk("status", False, "读不到打印机状态", "อ่านสถานะเครื่องไม่ได้")
    if vend == "bambu":
        chk("devmode", None, "开发者模式：这里看不出来。新固件要打开「开发者模式」才能由本系统发送打印，用「🧪 打印测试」验证",
            "โหมดนักพัฒนา: ตรวจจากตรงนี้ไม่ได้ เฟิร์มแวร์ใหม่ต้องเปิด «โหมดนักพัฒนา» จึงจะส่งงานพิมพ์ได้ ใช้ «🧪 ทดสอบพิมพ์» เพื่อตรวจ")
    if out["ok"] and save_idx is not None and cfg is not None:
        try:                                # 记住认出来的连接方式
            with _EDIT:
                cfg2 = load_config()
                prs2 = cfg2.get("printers") or []
                if save_idx < len(prs2) and prs2[save_idx].get("id") == p.get("id"):
                    cc = dict(prs2[save_idx].get("conn") or {})
                    if cc.get("detected") != out.get("type"):
                        cc["detected"] = out.get("type")
                        prs2[save_idx]["conn"] = cc
                        save_config({"printers": prs2})
        except Exception:  # noqa: BLE001
            pass
    return out


# ---------------- 批量操作 ----------------
BULK = ("enable", "disable", "pause", "resume", "role", "group", "location", "nozzle", "plate", "dedicate", "test", "remove")


@bp.post("/api/fleet/bulk")
def fleet_bulk():
    """{ids: [...] 或 group: "A 区", action, value}。action：enable / disable / pause（暂停接单，保养）/ resume / role / group /
    location / nozzle（单台喷嘴覆盖，空 = 跟随模板）/ plate / dedicate（专门打某个生产单，空 = 取消）/ test（测试连接）/ remove"""
    from core import netdiag, printers as printers_mod
    b = request.get_json(force=True) or {}
    act = b.get("action")
    if act not in BULK:
        return err("不支持的批量操作")
    val = b.get("value")
    with _EDIT:
        cfg, prs = _cfg_printers()
        if b.get("ids"):
            want = {str(x) for x in b["ids"]}
            idx = [i for i, p in enumerate(prs) if p.get("id") in want or p.get("code") in want]
        elif "group" in b and b.get("group") is not None:
            idx = [i for i, p in enumerate(prs) if (p.get("group") or "") == b["group"]]
        else:
            return err("请先选打印机（勾选，或选一个分组）")
        if not idx:
            return err("没有选中的打印机")
        if act == "test":
            pass
        elif act == "remove":
            keep = [p for i, p in enumerate(prs) if i not in set(idx)]
            if not keep:
                return err("至少要保留一台打印机")
            old = [dict(x) for x in prs]
            busy = fleet.busy_codes(old, keep)
            if busy:
                return err("这些打印机还有正在打印的任务，不能移除：" + "、".join(busy))
            cfg = save_config({"printers": keep})
            fleet.remap(old, cfg["printers"])
            _after_change(cfg)
            db.audit(_uname(), "批量移除打印机", ",".join(old[i].get("code") or "" for i in idx)[:200], str(len(idx)))
            return jsonify({"ok": True, "n": len(idx)})
        else:
            errs = []
            olds = [dict(prs[i]) for i in idx]
            for i in idx:
                p = dict(prs[i])
                if act in ("enable", "disable"):
                    _apply_fields(p, {"enabled": act == "enable"}, cfg, errs)
                elif act in ("pause", "resume"):
                    _apply_fields(p, {"paused": act == "pause"}, cfg, errs)
                elif act in ("role", "group", "location"):
                    _apply_fields(p, {act: val}, cfg, errs)
                elif act == "dedicate":
                    _apply_fields(p, {"dedicated_po": val or ""}, cfg, errs)
                elif act in ("nozzle", "plate"):
                    _apply_fields(p, {"ovr": {act: val}}, cfg, errs)
                if errs:
                    return err(_e(errs))
                prs[i] = p
            cfg = _save(cfg, prs)
            db.audit(_uname(), "批量修改打印机", act, f"{len(idx)} 台 = {val}")
            sug = []
            if act in ("group", "location"):       # v2.55：编码里带着旧分组 / 位置 → 页面问「要按新位置重新编号吗？」
                sug = fleetcodes.suggest_after_move(olds, [cfg["printers"][i] for i in idx], cfg)
            return jsonify({"ok": True, "n": len(idx), "renumber_suggest": sug})
    # 测试连接：同时最多 32 台，一次最多 200 台
    from concurrent.futures import ThreadPoolExecutor
    sel = idx[:200]

    def one(i):
        p = prs[i]
        try:
            r = run_test(p, netdiag, printers_mod)
        except Exception as e:  # noqa: BLE001
            r = {"ok": False, "message": str(e), "checks": []}
        return {"id": p.get("id"), "code": p.get("code"), "ok": r["ok"], "message": r.get("message") or r.get("status_zh") or "",
                "checks": r.get("checks")}
    with ThreadPoolExecutor(max_workers=32) as ex:
        res = list(ex.map(one, sel))
    for i in sel:
        printers_mod.poll_once(i, prs[i])
    return jsonify({"results": res, "skipped": len(idx) - len(sel)})


# ---------------- 局域网发现 / 批量添加 / 导入 ----------------
@bp.post("/api/fleet/discover")
def fleet_discover():
    from core import printer_discovery
    b = request.get_json(force=True, silent=True) or {}
    secs = max(1.0, min(10.0, float(b.get("seconds") or 3)))
    hosts = None
    if b.get("cidr"):
        import ipaddress
        try:
            net = ipaddress.ip_network(str(b["cidr"]).strip(), strict=False)
        except ValueError:
            return err("网段格式不对（例如 192.168.1.0/24）")
        if net.num_addresses > printer_discovery.MAX_HOSTS + 2:
            return err("网段太大：最多扫 1024 个地址（/22）")
        hosts = [str(h) for h in net.hosts()]
    r = printer_discovery.discover(load_config(), secs, scan_hosts=hosts)
    cfg = load_config()
    for d in r["devices"]:
        d["code_suggest"] = fleetcodes.generate(cfg.get("printers") or [], [{"name": d["model"], "group": "", "location": ""}], cfg)[0][0] if d.get("model") else ""
    return jsonify(r)


@bp.post("/api/fleet/add-many")
def fleet_add_many():
    """局域网发现 / 导入预览里勾选的设备一起加：{devices: [{model, vendor, host, serial, access_code, port, group, location, role, code}]}。
    先全部检查，有一台不对就一台都不加（返回每行的问题）。"""
    b = request.get_json(force=True) or {}
    stash = _imp_get(b.get("token")) if b.get("token") else None
    if b.get("token") and stash is None:
        return err("导入的文件已经过期，请重新选文件")
    rows = []
    for d in (b.get("devices") or [])[:5000]:
        src = {}
        if stash is not None and str(d.get("row") or "").isdigit() and 1 <= int(d["row"]) <= len(stash):
            src = stash[int(d["row"]) - 1]          # 导入：访问码等原始值留在服务器上，不经过浏览器
        ac = d.get("access_code") or ""
        if ac in ("", "******"):
            ac = src.get("access_code") or ""
        rows.append({"model": d.get("model") or d.get("name") or src.get("model"), "vendor": d.get("vendor") or src.get("vendor") or "",
                     "host": d.get("host") or d.get("ip") or src.get("host") or "", "serial": d.get("serial") or src.get("serial") or "",
                     "access_code": ac, "port": d.get("port") or src.get("port") or "",
                     "group": d.get("group") or b.get("group") or "", "location": d.get("location") or "",
                     "role": d.get("role") or src.get("role") or "", "code": d.get("code") or "",
                     "nozzle": d.get("nozzle") or src.get("nozzle") or ""})
    if not rows:
        return err("没有要添加的打印机")
    return _commit_rows(rows)


# ---------------- 导入预览暂存（v2.54 复审：访问码不回传给浏览器，提交时按 token 取服务器上的原始行） ----------------
_IMPORTS = {}
IMP_TTL = 3600


def _imp_put(rows):
    import secrets
    now = time.time()
    for k in [k for k, v in _IMPORTS.items() if now - v[0] > IMP_TTL]:
        _IMPORTS.pop(k, None)
    tok = secrets.token_urlsafe(16)
    _IMPORTS[tok] = (now, rows)
    return tok


def _imp_get(tok):
    v = _IMPORTS.get(str(tok or ""))
    if not v or time.time() - v[0] > IMP_TTL:
        return None
    return v[1]


def _mask_rows(res):
    for r in res:
        c = (r.get("printer") or {}).get("conn") or {}
        if c.get("access_code"):
            c["access_code"] = "******"
    return res


def _commit_rows(rows):
    with _EDIT:
        cfg, prs = _cfg_printers()
        res = fleet.validate_import(rows, cfg)
        bad = [r for r in res if not r["ok"]]
        if bad:
            return jsonify({"ok": False, "rows": _mask_rows(res), "error": _e([("有 %d 行不对，没有添加" % len(bad), "มี %d แถวไม่ถูกต้อง ยังไม่ได้เพิ่ม" % len(bad))])}), 400
        if len(prs) + len(res) > 5000:
            return err("打印机最多 5000 台")
        added = []
        for r in res:
            p = dict(r["printer"], id=fleet.new_id())
            prs.append(p)
            added.append(p["id"])
        cfg = _save(cfg, prs)
    db.audit(_uname(), "批量添加打印机", str(len(added)), "")
    return jsonify({"ok": True, "added": added, "codes": [p.get("code") for p in cfg["printers"] if p.get("id") in added]})


@bp.post("/api/fleet/import")
def fleet_import():
    """Excel / CSV 导入：表头 编码 / 机型 / IP / 序列号 / 访问码 / 分组 / 位置（中英泰都认）。
    ?commit=1 才真的添加；不带 = 只检查，返回每行的问题（预览）。"""
    f = request.files.get("file")
    try:
        if f:
            rows = fleet.read_table(f.filename, f.read())
        else:
            b = request.get_json(force=True, silent=True) or {}
            rows = b.get("rows") or fleet.read_table("x.csv", str(b.get("text") or ""))
    except Exception as e:  # noqa: BLE001
        return err(f"读不了这个文件：{e}")
    if not rows:
        return err("文件里没有打印机")
    if request.args.get("commit") == "1":
        return _commit_rows(rows)
    res = _mask_rows(fleet.validate_import(rows, load_config()))
    # 不回传原始行（里面有明文访问码）：存在服务器上，提交时带 token + 行号
    return jsonify({"rows": res, "ok": sum(1 for r in res if r["ok"]), "bad": sum(1 for r in res if not r["ok"]), "token": _imp_put(rows)})


@bp.get("/api/fleet/import-template")
def fleet_import_template():
    body = "code,model,ip,serial,access code,group,location,vendor,nozzle\n" \
           "P1S-001,Bambu Lab P1S,192.168.1.51,01P00A000000001,12345678,A,A-01-1,bambu,0.4\n" \
           "K1C-001,Creality K1C,192.168.1.61,,,B,B-02-1,creality,0.4\n"
    return app.response_class("﻿" + body, mimetype="text/csv",
                              headers={"Content-Disposition": "attachment; filename=printers_template.csv"})


# ---------------- 机型模板（设置 → 生产） ----------------
@bp.get("/api/fleet/templates")
def fleet_templates_get():
    cfg = load_config()
    names = list(dict.fromkeys([p.get("name") for p in cfg.get("printers") or []] + list((cfg.get("printer_models") or {}).keys())))
    out = []
    for n in names:
        if not n:
            continue
        prs = [p for p in cfg.get("printers") or [] if p.get("name") == n]
        m = fleet.model_info(n) or {}
        out.append({"name": n, "template": fleet.template_of(n, cfg), "saved": (cfg.get("printer_models") or {}).get(n) or {},
                    "count": len(prs), "overrides": sum(1 for p in prs if p.get("ovr")), "tech": m.get("tech", "fdm"),
                    "first": next((i for i, p in enumerate(cfg.get("printers") or []) if p.get("name") == n), None),
                    "ams_default": fleet.is_multicolor({"name": n, "ams": None, "tech": m.get("tech", "fdm"), "_eff": {}, "ovr": {}})})
    return jsonify({"templates": out, "est_calibration": cfg.get("est_calibration"), "est_calibration_n": cfg.get("est_calibration_n")})


@bp.post("/api/fleet/templates")
def fleet_templates_save():
    """{templates: {机型: {nozzle, plate, g_per_h, ams, orca_machine, orca_process, orca_filament}}}：空 = 机型默认。"""
    b = request.get_json(force=True) or {}
    with _EDIT:
        cfg = load_config()
        tpls = {k: dict(v) for k, v in (cfg.get("printer_models") or {}).items()}
        errs = []
        for name, t in (b.get("templates") or {}).items():
            name = str(name).strip()[:40]
            if not name or not isinstance(t, dict):
                continue
            cur = dict(tpls.get(name) or {})
            for f, v in t.items():
                if f not in fleet.TPL_FIELDS:
                    continue
                cv = fleet.clean_value(f, v)
                if v not in (None, "", "auto") and cv is None:
                    errs.append((f"{name}：「{f}」的值不对（{v}）", f"{name}: ค่า «{f}» ไม่ถูกต้อง ({v})"))
                elif cv is None:
                    cur.pop(f, None)
                else:
                    cur[f] = cv
            tpls[name] = cur
        if errs:
            return err(_e(errs))
        cfg = save_config({"printer_models": tpls, "printers": cfg.get("printers") or []})
        _after_change(cfg)
    db.audit(_uname(), "修改机型模板", ",".join((b.get("templates") or {}).keys())[:200], "")
    return fleet_templates_get()


# ---------------- v2.55 编码规则 / 批量重新编号 ----------------
def _rules_out(cfg):
    rs = fleetcodes.get_rules(cfg)
    groups = sorted({p.get("group") or "" for p in cfg.get("printers") or []} - {""})
    return {"rules": rs["rules"], "default": rs["default"], "groups": rs["groups"], "group_codes": rs["group_codes"],
            "group_list": groups, "std": fleetcodes.STD}


@bp.get("/api/fleet/codes/rules")
def fleet_codes_rules():
    return jsonify(_rules_out(load_config()))


@bp.post("/api/fleet/codes/rules")
def fleet_codes_rules_save():
    """{rules: {id: {name, blocks, sep}}, default, groups: {分组: 规则 id}, group_codes: {分组: 简称}}：整套保存。"""
    b = request.get_json(force=True) or {}
    rules, errs = {}, []
    for rid, r in (b.get("rules") or {}).items():
        rid = str(rid).strip()[:20]
        rr, es = fleetcodes.clean_rule(r)
        if not rr["name"]:
            es.append(("规则要起个名字", "กฎต้องตั้งชื่อ"))
        if not rid:
            continue
        errs += [(f"{rr['name'] or rid}：{z}", f"{rr['name'] or rid}: {t}") for z, t in es]
        rules[rid] = rr
    if not rules:
        errs.append(("至少要有一条规则", "ต้องมีอย่างน้อยหนึ่งกฎ"))
    if len(rules) > fleetcodes.MAX_RULES:
        errs.append((f"规则最多 {fleetcodes.MAX_RULES} 条", f"กฎได้ไม่เกิน {fleetcodes.MAX_RULES} ข้อ"))
    if errs:
        return err(_e(errs))
    default = b.get("default") if b.get("default") in rules else next(iter(rules))
    groups = {str(g)[:30]: rid for g, rid in (b.get("groups") or {}).items() if rid in rules and str(g).strip()}
    gcodes = {str(g)[:30]: fleetcodes._alnum(c, 6) for g, c in (b.get("group_codes") or {}).items() if fleetcodes._alnum(c, 6)}
    with _EDIT:
        save_config({"printer_code_rules": {"rules": rules, "default": default, "groups": groups, "group_codes": gcodes}})
    db.audit(_uname(), "修改打印机编码规则", ",".join(r["name"] for r in rules.values())[:200], "")
    return jsonify(_rules_out(load_config()))


@bp.post("/api/fleet/codes/preview")
def fleet_codes_preview():
    """规则编辑器的实时预览：{rule: {blocks, sep}, group_codes?} → 几个例子（用空机群拼，不受现有编码影响）。"""
    b = request.get_json(force=True) or {}
    rr, errs, ex = fleetcodes.preview(b.get("rule"), load_config(), b.get("group_codes") if isinstance(b.get("group_codes"), dict) else None)
    return jsonify({"ok": not errs, "errors": [{"zh": z, "th": t, "msg": t if TH() else z} for z, t in errs], "rule": rr,
                    "examples": ex, "length_ok": all(len(x["code"]) <= 16 for x in ex)})


@bp.post("/api/fleet/codes/check")
def fleet_codes_check():
    """手填编码的检查（不分大小写查重）：{code, id}。"""
    b = request.get_json(force=True) or {}
    e = fleetcodes.check_code(b.get("code"), load_config().get("printers") or [], exclude_id=b.get("id"))
    return jsonify({"ok": not e, "message": (e[1] if TH() else e[0]) if e else ""})


def _renumber(b, apply):
    with _EDIT:
        cfg, prs = _cfg_printers()
        if b.get("ids"):
            want = {str(x) for x in b["ids"]}
            ids = {p.get("id") for p in prs if p.get("id") in want or p.get("code") in want}
        elif b.get("group") is not None:
            ids = {p.get("id") for p in prs if (p.get("group") or "") == b["group"]}
        elif b.get("all"):
            ids = {p.get("id") for p in prs}
        else:
            return err("请先选打印机（勾选，或选一个分组）")
        if not ids:
            return err("没有选中的打印机")
        rule = b.get("rule") or None
        if rule not in (fleetcodes.get_rules(cfg)["rules"] or {}):
            rule = None                              # 空 = 每台按它分组的规则（没单独设的用默认规则）
        order = b.get("order") if b.get("order") in fleetcodes.ORDERS else "location"
        rows = fleetcodes.plan_renumber(prs, ids, cfg, rule, order)
        bad = [r for r in rows if r["status"] == "conflict"]
        out = {"rows": [dict(r, problem=(r["problem"][1] if TH() else r["problem"][0]) if r["problem"] else "") for r in rows],
               "changed": sum(1 for r in rows if r["status"] == "change"), "same": sum(1 for r in rows if r["status"] == "same"),
               "conflicts": len(bad)}
        if not apply:
            return jsonify(out)
        if bad:
            return jsonify(dict(out, ok=False, error=_e([("有 %d 台的新编码有冲突，没有改" % len(bad), "มี %d เครื่องที่รหัสใหม่ชนกัน ยังไม่ได้แก้" % len(bad))]))), 400
        ch = {r["id"]: r for r in rows if r["status"] == "change"}
        if not ch:
            return jsonify(dict(out, ok=True, n=0, ids=[]))
        fleetcodes.migrate_po_refs()                  # 生产单里还存着旧编码的先换成稳定 id
        old = [dict(x) for x in prs]
        pairs = []
        for p in prs:
            r = ch.get(p.get("id"))
            if r:
                p["code"] = r["new"]
                pairs.append((r["old"], r["new"]))
        info = fleetcodes.note_code_changes(old, prs)
        cfg = _save(cfg, prs, renames=pairs)
        db.audit(_uname(), "批量重新编号打印机", f"{len(ch)} 台", ";".join(f"{r['old']}>{r['new']}" for r in list(ch.values())[:30])[:300])
        by_id = {p.get("id"): p for p in cfg["printers"]}
        return jsonify(dict(out, ok=True, n=len(ch), ids=list(ch.keys()),
                            # v2.55.0：旧标签会指到别的机器的（编码互换 / 复用）：必须重新打印；其余改了编码的也建议重印（新标签二维码是稳定 id）
                            relabel=[dict(x, name=(by_id.get(x["id"]) or {}).get("name", "")) for x in info["relabel"]],
                            relabel_ids=sorted({x["id"] for x in info["relabel"]})))


@bp.post("/api/fleet/codes/renumber")
def fleet_codes_renumber():
    """批量重新编号：{ids | group | all, rule: 规则 id（空 = 每台按所在分组的规则）, order: location|code|list, apply: true}。
    不带 apply = 预览（旧 → 新、冲突）；带 apply 才真改（服务器重新算一遍，有冲突一台都不改）。"""
    b = request.get_json(force=True) or {}
    return _renumber(b, bool(b.get("apply")))


# ---------------- 二维码标签 ----------------
@bp.get("/print/fleet-labels")
def fleet_labels():
    """每台打印机一张 50×30 毫米标签：二维码（扫了打开这台打印机的页面）+ 大字编码 + 机型 + 位置。?ids=…&lang=th"""
    from html import escape as h
    from modules.inv import qr
    cfg = load_config()
    prs = cfg.get("printers") or []
    want = [x for x in (request.args.get("ids") or "").split(",") if x.strip()]
    hit = {fleet.index_of(prs, x) for x in want}            # v2.55：旧编码（以前印的标签）也认
    sel = [p for i, p in enumerate(prs) if not want or i in hit]
    if request.args.get("group") is not None and not want:
        sel = [p for p in sel if (p.get("group") or "") == request.args.get("group")]
    base = request.host_url.rstrip("/")
    th = request.args.get("lang") == "th"
    cards = []
    for p in sel[:2000]:
        url = f"{base}/?printer={p.get('id') or p.get('code')}#printers"      # v2.55.0：二维码装稳定 id（改编码不用重印；牌子上的大字还是编码）
        loc = " · ".join(x for x in (p.get("group"), p.get("location")) if x)
        cards.append(f"""<div class="lb"><div class="qr">{qr.svg(url, 24)}</div><div class="t"><div class="code">{h(p.get('code') or '')}</div>
<div class="nt">{h(p.get('name') or '')}</div>{f'<div class="nt"><b>{h(loc)}</b></div>' if loc else ''}</div></div>""")
    title = "ป้ายเครื่องพิมพ์" if th else "打印机标签"
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title><style>
@page{{size:50mm 30mm;margin:0}}body{{margin:0;font-family:sans-serif}}
.lb{{width:50mm;height:30mm;box-sizing:border-box;padding:2mm;display:flex;gap:1.5mm;align-items:center;page-break-after:always;overflow:hidden}}
.qr{{width:24mm;height:24mm;flex:none}}.qr svg{{width:100%;height:100%}}.t{{flex:1;min-width:0}}
.code{{font-size:14pt;font-weight:700;word-break:break-all}}.nt{{font-size:7pt;margin-top:1mm}}
@media screen{{body{{background:#eee}}.lb{{background:#fff;margin:4mm;border:1px solid #ccc}}}}
</style></head><body>{''.join(cards) or '<p>-</p>'}<script>window.onload=()=>setTimeout(()=>window.print(),300)</script></body></html>"""
    return app.response_class(html, mimetype="text/html")
