"""v2.53 没有订单也能生产 / 试打：备货任务（任何入口）、🧪 试打任务（kind=trial）、🔍 检查切片文件（不打印）、
打印机 🧪 打印测试（kind=test，20 mm 立方体）。

和订单任务走同一条路：排单 → 开始打印对话框（机型 / 喷嘴 / 热床板核对 slicecheck 一律照旧，AMS 核对照旧）→ 打印 → 打完扣耗材。
区别只有：
  trial  最优先排；可以用还没试打验证的文件开始（试打就是为了验证它）；打完不进库存，等员工填「试打结果」
  test   打印机连接测试：打完就结束，不进库存
  stock  打完进成品库存（→ 待检区 → 质检合格才可售），可以加急、可以指定打印机
对外：create_stock / create_trial / check_file / printer_test / submit_result / pending / history / printer_options
"""
import json
import os
import re
import time

from . import db, print_files
from .config import load_config

ISSUES = ["翘边", "支撑难拆", "拉丝", "尺寸不对", "颜色不对", "掉层", "其他"]
ISSUES_TH = {"翘边": "ขอบงอ", "支撑难拆": "ซัพพอร์ตแกะยาก", "拉丝": "เป็นเส้นใย", "尺寸不对": "ขนาดไม่ถูก", "颜色不对": "สีไม่ถูก",
             "掉层": "ชั้นหลุด", "其他": "อื่น ๆ"}
DESTS = {"stock": "合格入库", "sample": "当样品", "scrap": "报废"}
KINDS = ("order", "stock", "reship", "trial", "test")
TEST_PRODUCT = "__test__"
BIG_DEV = 0.4          # 切片文件的克数 / 时长和估算差超过 40% 算「差得多」


def _now():
    return time.time()


def can_produce(user):
    """老板和生产角色可以建备货 / 试打 / 测试任务；别的角色不行。"""
    return bool(user) and user.get("role") in ("owner", "production")


def _printers(cfg=None):
    return (cfg or load_config()).get("printers") or []


def _label(p, i):
    return (p.get("code") or f"#{i + 1}") + " " + (p.get("name") or "")


def _plan_mod():
    from . import modules
    return modules.public("model")


# ---------------- 备货任务（任何入口） ----------------
def create_stock(items, priority=0, printer=None, user="", source="", po_source="manual", due=None, printers=None):
    """items: [{sku, qty}]（或 [{product_id, sku, qty}]）。v2.54：一次操作建一张生产单（同一 SKU 合并成一行）并马上下达，
    每行一个备货任务。返回 {"jobs": 建好的任务, "errors": 没对上的行, "po": 生产单}。"""
    from . import po as _po
    if not items:
        raise ValueError("请选择要生产的 SKU")
    note = "备货" + (f"（{source}）" if source else "")
    po = _po.create(items, po_source if po_source in _po.SOURCES else "manual", user, priority=1 if int(priority or 0) else 0, due=due,
                    note=note, printers=printers)
    errs = po.get("errors") or []
    try:
        po = _po.release_po(po["id"], user, pin=printer)
    except (ValueError, FileNotFoundError):
        c = db.conn()                                  # 下达不成功：这张草稿单不留
        c.execute("DELETE FROM po_lines WHERE po_id=?", (po["id"],))
        c.execute("DELETE FROM production_orders WHERE id=?", (po["id"],))
        c.commit()
        raise
    from . import production
    jobs = [j for j in production.list_jobs(("todo", "printing")) if j.get("po_id") == po["id"]]
    db.audit(user, "新建备货任务", ",".join(j["sku"] for j in jobs), f"来源 {source or '-'}；生产单 {po['no']}" + (f"；{'；'.join(errs)}" if errs else ""))
    po["errors"] = errs
    return {"jobs": jobs, "errors": errs, "po": po}


# ---------------- 试打 ----------------
def printer_options(pid, spec="", plate_id="", sku=""):
    """试打能用的打印机：和这一盘（打印方案里选的机型）同机型的。idle = 现在空闲。"""
    from . import production
    from .printers import get_status
    cfg = load_config()
    prs = _printers(cfg)
    p, spec, plan, plate = _resolve(pid, spec, plate_id, sku)
    model = (plate or {}).get("printer") or ""
    busy = {r["printer"] for r in production.active_runs()}
    out = []
    for i, pr_ in enumerate(prs):
        if pr_.get("enabled", True) is False:
            continue
        if model and (pr_.get("name") or "") != model:
            continue
        st = get_status(i).get("state") or ""
        idle = i not in busy and st not in ("printing", "paused", "offline")
        out.append({"index": i, "code": pr_.get("code") or f"#{i + 1}", "name": pr_.get("name") or "", "idle": idle,
                    "state": st, "label": _label(pr_, i)})
    out.sort(key=lambda x: (not x["idle"], x["index"]))
    return {"model": model, "printers": out,
            "plates": [{"id": x["id"], "name": x.get("name") or "", "printer": x.get("printer") or ""} for x in plan.get("plates") or []]}


def _resolve(pid, spec, plate_id, sku=""):
    """(产品, 规格, 方案, 盘)。plate_id 不填 = 方案第一盘。
    v2.53.1：方案按 plan_key（= 切片文件的规格）取：跟着主模型的规格用主模型的方案，按主模型缩放的规格用缩放后的方案。"""
    from . import specmodel, store
    pp = _plan_mod()
    if not pp:
        raise ValueError("「3D 模型」模块没有开启，不能按打印方案试打")
    try:
        p = store.load(pid)
    except FileNotFoundError:
        raise ValueError("产品不存在")
    sku_spec = specmodel.spec_of_sku(p, sku) if sku else ""
    if spec in (None, ""):
        spec = sku_spec
    spec = (spec or "").strip()
    if sku and sku_spec and sku_spec != spec:
        raise ValueError(f"SKU {sku} 是规格「{sku_spec}」的，不是「{spec or '主模型'}」的")
    plan = pp.get_plan(p, specmodel.file_spec(p, spec))
    plates = plan.get("plates") or []
    if not plates:
        raise ValueError("这个产品没有打印方案，请先在产品编辑页的「打印方案」里摆盘")
    plate = next((x for x in plates if x["id"] == plate_id), None) if plate_id else plates[0]
    if not plate:
        raise ValueError("没有这一盘（刷新一下）")
    return p, spec, plan, plate


def _sku_for(p, spec, sku):
    if sku:
        return sku.strip().upper()
    for v in p.get("variants") or []:
        if (v.get("opt2_zh") or "").strip() == (spec or "") and v.get("sku"):
            return v["sku"].strip().upper()
    return ""


def _colour_for(p, sku):
    for v in p.get("variants") or []:
        if (v.get("sku") or "").strip().upper() == (sku or "").upper():
            return (v.get("opt1_zh") or "").strip()
    return ""


def _pick_printer(pid, spec, plate_id, sku, printer):
    if printer not in (None, ""):
        i = int(printer)
        prs = _printers()
        if not (0 <= i < len(prs)):
            raise ValueError("没有这台打印机")
        return i
    po = printer_options(pid, spec, plate_id, sku)
    if not po["printers"]:
        raise ValueError(f"设置里没有「{po['model'] or '能用'}」的打印机可以试打（生产 → 打印机里添加 / 启用）")
    return po["printers"][0]["index"]


def _plate_file(p, pid, spec, plate_id, sku, idx, user, slice_now=True):
    """这一盘给这台打印机用的切片文件（不管有没有复核）；没有就现在按方案切（slice_now）。返回 (文件, 是不是刚切的)。"""
    pname = _printers()[idx].get("name") or ""
    colour = _colour_for(p, sku)
    rows = print_files.candidates(pid, sku, pname, colour, usable_only=False, plate_id=plate_id)
    f = rows[0] if rows else None
    if f:
        return f, False
    if not slice_now:
        return None, False
    pp = _plan_mod()
    from . import slicer, specmodel
    try:
        r = pp.slice_plate(pid, specmodel.file_spec(p, spec), plate_id, colour, idx, user)     # v2.53.1：按这个规格的方案（缩放后）切
    except slicer.SliceError as e:
        raise ValueError(f"这一盘还没有切片文件，现在切片没有成功：{e}")
    return r["file"], True


def create_trial(pid, sku="", spec=None, plate_id="", printer=None, file_id=None, user="", source=""):
    """建一个试打任务（pin 到那台打印机，最优先）。有文件用文件（机型 / 喷嘴对不上的当场拒绝）；没有文件现在切片。"""
    from . import production
    p, spec, plan, plate = _resolve(pid, spec, plate_id, sku)
    plate_id = plate["id"]
    sku = _sku_for(p, spec, sku)
    idx = _pick_printer(pid, spec, plate_id, sku, printer)
    prs = _printers()
    sliced_now = False
    if file_id:
        f = print_files.get(int(file_id))
        if not f or f.get("product_id") != pid:
            raise ValueError("文件不存在，或不是这个产品的")
    else:
        f, sliced_now = _plate_file(p, pid, spec, plate_id, sku, idx, user)
    f = print_files.ensure_params(f)
    from modules.prod import slicecheck
    sc = slicecheck.check(f, idx)
    if not sc["ok"]:
        raise ValueError("不能用这个切片文件试打：" + "；".join(sc["errors"]))
    ferr = _file_mismatch(f, p, sku, plate_id, len(plan.get("plates") or []) == 1)     # v2.53.1：规格 / 缩放比例 / 盘
    if ferr:
        raise ValueError(ferr)
    n = max(1, int(f.get("per_plate") or plate.get("sets") or 1))
    j = production.create_job(pid, sku, n, "trial", None, user, "试打" + (f"（{source}）" if source else ""),
                              priority=1, printer=idx, file_id=f["id"])
    total = len(plan.get("plates") or [])
    pname = plate.get("name") or ""
    c = db.conn()
    tid = c.execute("""INSERT INTO trials(job_id, product_id, sku, spec, plate_id, plate_no, plate_total, plate_name, file_id, printer,
                       status, qty, created_at, created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (j["id"], pid, sku, spec, plate_id, [x["id"] for x in plan["plates"]].index(plate_id) + 1, total, pname, f["id"],
                     idx, "queued", n, _now(), user)).lastrowid
    c.commit()
    db.audit(user, "新建试打任务", f"{pid} {sku}", f"盘 {plate_id} 文件 #{f['id']} {_label(prs[idx], idx)}")
    production.schedule()
    return {"job": dict(production._job(c, j["id"])), "trial": get_trial(tid), "file": _file_brief(f), "sliced_now": sliced_now,
            "printer": idx, "printer_label": _label(prs[idx], idx)}


def create_trials(pid, sku="", spec=None, plate_id="", printer=None, user="", source="", only_unverified=False):
    """商品库批量 / 没指定盘：每一盘一个试打任务（几盘的方案按盘）。only_unverified：已经有试打验证过文件的盘跳过。"""
    p, spec, plan, _plate = _resolve(pid, spec, plate_id, sku)
    plates = [x for x in plan["plates"] if x["id"] == plate_id] if plate_id else list(plan["plates"])
    made, skipped, errs = [], [], []
    sku2 = _sku_for(p, spec, sku)
    for pl in plates:
        if only_unverified:
            pname = pl.get("printer") or ""
            fs = print_files.candidates(pid, sku2, pname, _colour_for(p, sku2), usable_only=False, plate_id=pl["id"])
            if any(x.get("status") == "verified" for x in fs):
                skipped.append(pl["id"])
                continue
        try:
            made.append(create_trial(pid, sku, spec, pl["id"], printer, None, user, source))
        except ValueError as e:
            errs.append(f"{pl.get('name') or pl['id']}：{e}")
    if not made and errs:
        raise ValueError("；".join(errs))
    return {"trials": made, "skipped": skipped, "errors": errs}


def _file_mismatch(f, p, sku, plate_id, single=False):
    """v2.53.1：试打 / 检查用的文件必须是这个规格（缩放比例）、这一盘的。对得上 → ""。"""
    from . import specmodel
    err = specmodel.file_error(f, p, sku)
    if err:
        return err
    if (f.get("plate_id") or "") != plate_id and not (single and not f.get("plate_id")):
        return f"文件尺寸 / 规格和任务不一致（文件 #{f.get('id')}）：不是打印方案里这一盘的切片文件"
    return ""


def _file_brief(f):
    return {k: (f or {}).get(k) for k in ("id", "filename", "status", "per_plate", "grams", "hours", "plate_id")} if f else None


# ---------------- 试打结果 ----------------
def get_trial(tid=None, job_id=None):
    c = db.conn()
    r = c.execute("SELECT * FROM trials WHERE id=?", (tid,)).fetchone() if tid else \
        c.execute("SELECT * FROM trials WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    for k in ("issues", "photos"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except ValueError:
            d[k] = []
    d["dest_zh"] = DESTS.get(d.get("dest") or "", "")
    return d


def job_info(job_id):
    """试打结果表单要的东西：试打记录 + 预填的克数 / 时长（打印批次里的，读不到用文件的）+ 能选哪些去向。"""
    t = get_trial(job_id=job_id)
    if not t:
        raise ValueError("这个任务不是试打任务")
    c = db.conn()
    run = c.execute("SELECT * FROM print_runs WHERE id=?", (t.get("run_id") or 0,)).fetchone() if t.get("run_id") else None
    if not run:
        run = c.execute("SELECT * FROM print_runs WHERE alloc LIKE ? ORDER BY id DESC LIMIT 1", (f'%"{job_id}":%',)).fetchone()
    f = print_files.get(t["file_id"]) if t.get("file_id") else None
    t["prefill"] = {"grams": (run["grams"] if run and run["grams"] else (f or {}).get("grams")),
                    "hours": run["hours"] if run and run["hours"] else (f or {}).get("hours")}
    t["file"] = _file_brief(f)
    t["can_stock"] = _single_plate(t)
    t["issues_all"] = ISSUES
    t["dests"] = [{"key": k, "zh": v} for k, v in DESTS.items() if k != "stock" or t["can_stock"]]
    return t


def _single_plate(t):
    return int(t.get("plate_total") or 1) <= 1 and bool(t.get("sku"))


def pending():
    """已经打完、等着填试打结果的试打任务。"""
    out = []
    for r in db.conn().execute("SELECT * FROM trials WHERE status='await' ORDER BY id"):
        t = get_trial(r["id"])
        try:
            from . import store
            t["name"] = store.load(t["product_id"]).get("name_zh") or ""
        except Exception:  # noqa: BLE001
            t["name"] = ""
        out.append(t)
    return out


def mark_failed_run(job, reason, note, user):
    """production.fail_run：试打 / 测试这一盘中途失败了 → 试打记录失败（不用再填结果），任务结束。"""
    c = db.conn()
    now = _now()
    if job["kind"] == "trial":
        t = get_trial(job_id=job["id"])
        if t and t["status"] in ("queued", "await"):
            c.execute("UPDATE trials SET status='fail', issues=?, note=?, done_at=?, done_by=? WHERE id=?",
                      (json.dumps([reason or "其他"], ensure_ascii=False), note or "", now, user, t["id"]))
            if t.get("file_id"):
                print_files.verify(t["file_id"], False, user, note=f"{reason or '其他'} {note or ''}".strip())
    c.execute("UPDATE jobs SET status='done', done_at=?, run_id=NULL, pin=0 WHERE id=?", (now, job["id"]))
    c.commit()


def submit_result(job_id, ok, issues=None, note="", grams=None, hours=None, dest="", photos=None, user=""):
    """员工填「试打结果」。ok → 文件自动试打验证、实际克数 / 时长写回款式（成本更新）、按去向处理这批成品；失败 → 记原因、文件退回草稿。"""
    from . import production
    c = db.conn()
    j = production._job(c, job_id)
    t = get_trial(job_id=job_id)
    if (j["kind"] or "") != "trial" or not t:
        raise ValueError("这个任务不是试打任务")
    if t["status"] in ("success", "fail"):
        raise ValueError("这个试打已经填过结果了")
    if t["status"] != "await":
        raise ValueError("这盘还没打完，打完以后再填试打结果")
    issues = [str(x) for x in (issues or []) if str(x).strip()]
    num = (lambda v: float(v) if v not in (None, "") else None)
    try:
        grams, hours = num(grams), num(hours)
    except (TypeError, ValueError):
        raise ValueError("克数 / 时长要填数字")
    if ok and dest not in DESTS:
        raise ValueError("请选择这批成品的去向：合格入库 / 当样品 / 报废")
    if ok and dest == "stock" and not _single_plate(t):
        raise ValueError("这个产品要打好几盘才是一整件，单独一盘不能入库。请选「当样品」或「报废」")
    now = _now()
    f = print_files.get(t["file_id"]) if t.get("file_id") else None
    photo_names = list(photos or [])
    if ok:
        if f:
            print_files.verify(f["id"], True, user, grams, hours, note or "试打合格", photo_names[0] if photo_names else None)
        applied = _write_back(t, grams, hours) if (grams or hours) else []
        qty = int(t.get("qty") or 1)
        if dest == "stock":
            production.stock_add(t["sku"], qty, f"备货打印 试打合格入库 试打#{t['id']}", user, t["product_id"], j["name"], j["color"])
        elif dest == "sample":
            db.audit(user, "试打样品", t["sku"] or t["product_id"], f"试打#{t['id']} ×{qty}（样品，不可售）")
        else:
            db.audit(user, "试打报废", t["sku"] or t["product_id"], f"试打#{t['id']} ×{qty}")
    else:
        applied = []
        if not issues and not (note or "").strip():
            raise ValueError("失败了请选择问题（翘边 / 拉丝…）或写一句原因")
        if f:
            print_files.verify(f["id"], False, user, note=("、".join(issues) + (" " + note if note else "")).strip(),
                               photo=photo_names[0] if photo_names else None)
        qty = int(t.get("qty") or 1)
    c.execute("""UPDATE trials SET status=?, issues=?, note=?, grams=?, hours=?, photos=?, dest=?, done_at=?, done_by=?, applied=? WHERE id=?""",
              ("success" if ok else "fail", json.dumps(issues, ensure_ascii=False), note or "", grams, hours,
               json.dumps(photo_names), dest if ok else "", now, user, json.dumps(applied, ensure_ascii=False), t["id"]))
    c.execute("UPDATE jobs SET status='done', done_at=?, run_id=NULL, pin=0, updated_at=?, updated_by=? WHERE id=?",
              (now, now, user, job_id))
    c.commit()
    db.audit(user, "试打结果", f"{t['product_id']} {t['sku']}", ("合格 " + DESTS.get(dest, "")) if ok else "不合格 " + "、".join(issues))
    production.schedule()
    out = get_trial(t["id"])
    out["hint"] = "" if ok else "可以去产品的「打印方案」调整摆放 / 方向 / 支撑后重新切片，再点「再试一次」"
    return out


def retry(tid, user="", printer=None):
    """「再试一次」：同一盘（重新切片的话用新文件）再建一个试打任务。"""
    t = get_trial(tid)
    if not t:
        raise ValueError("试打记录不存在")
    return create_trial(t["product_id"], t["sku"], t["spec"], t["plate_id"], printer if printer not in (None, "") else t["printer"],
                        None, user, "再试一次")


def _write_back(t, grams, hours):
    """实际克数 / 时长写回款式（成本跟着变）。几盘的方案写进这一盘的切片结果再按方案算；没有保存过方案的直接写规格的款式。"""
    from . import store
    pp = _plan_mod()
    if pp and hasattr(pp, "apply_actual"):
        return pp.apply_actual(t["product_id"], t["spec"], t["plate_id"], grams, hours, t.get("sku") or "")
    return []


def save_photo(job_id, fileobj):
    d = os.path.join(print_files.FILE_DIR, "photos")
    os.makedirs(d, exist_ok=True)
    name = f"trial{job_id}_{int(_now() * 1000)}.jpg"
    fileobj.save(os.path.join(d, name))
    return name


def history(pid):
    """每个产品的试打记录：次数、成功率、常见问题、照片、每条的结果。"""
    rows = [get_trial(r["id"]) for r in db.conn().execute("SELECT id FROM trials WHERE product_id=? ORDER BY id DESC", (pid,))]
    done = [t for t in rows if t["status"] in ("success", "fail")]
    ok_n = sum(1 for t in done if t["status"] == "success")
    cnt = {}
    for t in done:
        for i in t["issues"]:
            cnt[i] = cnt.get(i, 0) + 1
    photos = [x for t in rows for x in t["photos"]][:12]
    return {"count": len(done), "success": ok_n, "rate": round(ok_n / len(done) * 100) if done else None,
            "issues": sorted(cnt.items(), key=lambda kv: -kv[1]), "photos": photos, "rows": rows,
            "waiting": sum(1 for t in rows if t["status"] in ("queued", "await"))}


def stats_for(pids):
    """商品库「未试打」分组等：{pid: {count, success}}"""
    out = {}
    for pid in pids:
        h = history(pid)
        out[pid] = {"count": h["count"], "success": h["success"], "rate": h["rate"], "waiting": h["waiting"]}
    return out


# ---------------- 打印测试（20 mm 立方体） ----------------
def printer_test(idx, user="", confirm=None):
    """设置 → 生产 → 打印机连接 →「🧪 打印测试」：给这台打印机的机型切一个 20 mm 立方体，走正常的开始打印路径（kind=test）。"""
    from . import printers as pr, production, slicer
    cfg = load_config()
    prs = _printers(cfg)
    if not (0 <= int(idx) < len(prs)):
        raise ValueError("打印机不存在")
    idx = int(idx)
    p = prs[idx]
    from . import fleet
    if fleet.tech_of(p) == "resin":
        raise ValueError("光固化打印机不能用 FDM 立方体测试")
    if ((p.get("conn") or {}).get("type") or "none") == "none":
        raise ValueError("这台打印机还没设置连接。先填好连接方式、保存，再点「测试连接」确认通了，然后再做打印测试")
    st = pr.get_status(idx)
    if st.get("state") == "offline":
        raise ValueError(f"「{_label(p, idx)}」现在连不上（离线）。先确认打印机开着、和系统在同一个网络，点「测试连接」通了再做打印测试")
    if st.get("state") in ("printing", "paused"):
        raise ValueError(f"「{_label(p, idx)}」正在打印，等它打完再测试")
    busy = db.conn().execute("SELECT id FROM print_runs WHERE printer=? AND status='printing' LIMIT 1", (idx,)).fetchone()
    if busy:
        raise ValueError(f"「{_label(p, idx)}」上还有一盘（批次 #{busy['id']}）在打，先在生产看板结束它")
    if not slicer.find_orca(cfg):
        raise ValueError("没有找到 OrcaSlicer，不能给这台打印机的机型切测试立方体。请先在 设置 → 生产 里安装 / 指定 OrcaSlicer")
    f = _test_file(cfg, idx, p, user)
    c = db.conn()
    now = _now()
    jid = c.execute("""INSERT INTO jobs(product_id, sku, name, color, material, qty, grams_each, hours_each, printer, pin, file_id, status,
                       kind, priority_job, note, created_at, updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    ("", "TEST-CUBE", "打印测试 20mm 立方体", "", "PLA", 1, f.get("grams"), f.get("hours"), idx, 1, f["id"],
                     "todo", "test", 1, "打印测试", now, now, user)).lastrowid
    c.commit()
    try:
        r = production.start_run(jid, idx, None, [], f["id"], True, user, confirm or {})
    except Exception:
        c.execute("DELETE FROM jobs WHERE id=?", (jid,))
        c.commit()
        raise
    db.audit(user, "打印机打印测试", _label(p, idx), f"任务 #{jid} 批次 #{r['run_id']}")
    return {"job_id": jid, "run_id": r["run_id"], "file": _file_brief(f), "printer": _label(p, idx)}


def _test_file(cfg, idx, p, user):
    """这台打印机机型的测试立方体切片文件（同机型、同喷嘴、同热床板的复用，对不上就重新切）。"""
    from . import slicer
    from modules.prod import slicecheck
    pname = p.get("name") or ""
    for r in db.conn().execute("SELECT id FROM print_files WHERE product_id=? AND active=1 ORDER BY id DESC", (TEST_PRODUCT,)):
        f = print_files.ensure_params(print_files.get(r["id"]))
        if f and f["printer"] == pname and slicecheck.check(f, idx, cfg)["ok"]:
            return f
    import shutil
    import tempfile
    d = tempfile.mkdtemp(prefix="ptest_")
    try:
        stl = os.path.join(d, "cube20.stl")
        slicer._cube_stl(stl)
        keep = os.path.join(d, "cube20.gcode.3mf")
        try:
            res = slicer.orca_slice(cfg, stl, idx, "PLA", timeout=300, keep_to=keep)
        except slicer.SliceError as e:
            raise ValueError(f"测试立方体切片没有成功：{e}")
        if not os.path.isfile(res.get("kept") or keep):
            raise ValueError("测试立方体切片没有成功：切片软件没有生成文件")
        f = print_files.add(res.get("kept") or keep, f"cube20_{re.sub(r'[^A-Za-z0-9]+', '_', pname)}.gcode.3mf", TEST_PRODUCT, pname, "", 1,
                            "", "打印机打印测试（20 mm 立方体）", user, "PLA", res.get("grams"), res.get("hours"), source="test")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    db.conn().execute("UPDATE print_files SET status='reviewed' WHERE id=?", (f["id"],))
    db.conn().commit()
    return print_files.ensure_params(print_files.get(f["id"]))


# ---------------- 检查切片文件（不打印） ----------------
def _gcode_text(f, limit=12_000_000):
    import zipfile
    path = print_files.path_of(f)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            n = next((x for x in z.namelist() if x.startswith("Metadata/plate_") and x.endswith(".gcode")), None) or \
                next((x for x in z.namelist() if x.lower().endswith(".gcode")), None)
            if not n:
                return ""
            with z.open(n) as fh:
                return fh.read(limit).decode("utf-8", "ignore")
    with open(path, "rb") as fh:
        return fh.read(limit).decode("utf-8", "ignore")


def first_layer(text):
    """G-code 第一层有挤出的路径：[[(x, y), ...], ...]（遇到第二层就停）。"""
    layer, rel, e_last = 0, True, 0.0
    x = y = 0.0
    segs, cur, n = [], [], 0
    for line in text.splitlines():
        if line.startswith(";"):
            if line.startswith((";LAYER_CHANGE", "; CHANGE_LAYER", ";LAYER:")):
                layer += 1
                if layer >= 2:
                    break
                if cur:
                    segs.append(cur)
                    cur = []
            continue
        if line.startswith("M83"):
            rel = True
        elif line.startswith("M82"):
            rel = False
        elif line.startswith("G92"):
            m = re.search(r"E([-\d.]+)", line)
            if m:
                e_last = float(m.group(1))
        elif line.startswith(("G1", "G0", "G2", "G3")):
            mx, my, me = re.search(r"X([-\d.]+)", line), re.search(r"Y([-\d.]+)", line), re.search(r"E([-\d.]+)", line)
            nx = float(mx.group(1)) if mx else x
            ny = float(my.group(1)) if my else y
            ext = False
            if me:
                e = float(me.group(1))
                ext = (e > 0) if rel else (e > e_last)
                if not rel:
                    e_last = e
            if layer == 1 and ext and (mx or my) and n < 20000:
                if not cur:
                    cur = [(x, y)]
                cur.append((nx, ny))
                n += 1
            elif cur and layer == 1:
                segs.append(cur)
                cur = []
            x, y = nx, ny
    if cur:
        segs.append(cur)
    return segs


def preview_svg(segs, bed, excl=None):
    bw, bd = float(bed[0]), float(bed[1])
    paths = []
    for seg in segs:
        if len(seg) < 2:
            continue
        step = max(1, len(seg) // 80)
        s2 = seg[::step] + ([seg[-1]] if (len(seg) - 1) % step else [])
        paths.append("M" + " L".join(f"{p[0]:.1f},{bd - p[1]:.1f}" for p in s2))
    ex = ""
    if excl:
        ex = (f'<rect x="{excl[0]}" y="{bd - excl[3]:.1f}" width="{excl[2] - excl[0]:.1f}" height="{excl[3] - excl[1]:.1f}" '
              f'fill="#fecaca" stroke="#dc2626" stroke-width="0.8"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-4 -4 {bw + 8:g} {bd + 8:g}">'
            f'<rect x="0" y="0" width="{bw:g}" height="{bd:g}" fill="#f8fafc" stroke="#94a3b8" stroke-width="1.2"/>{ex}'
            f'<path d="{" ".join(paths)}" fill="none" stroke="#ea580c" stroke-width="0.9" stroke-linejoin="round"/></svg>')


def _chk(res, key, level, zh, th):
    res["checks"].append({"key": key, "level": level, "zh": zh, "th": th})
    if level == "error":
        res["errors"].append(zh)
    elif level == "warn":
        res["warnings"].append(zh)


def check_file(pid, spec=None, plate_id="", printer=None, file_id=None, sku="", user="", slice_now=True):
    """🔍 检查切片文件（不打印）：用这一盘现有的文件（没有就现在切）核对机型 / 喷嘴 / 热床板、克数时长和估算、
    零件都在热床上并且不压拓竹废料口、颜色槽和方案一致；画第一层预览图。任何红色原因 → ok=False。"""
    from . import slicer
    from modules.prod import slicecheck
    p, spec, plan, plate = _resolve(pid, spec, plate_id, sku)
    plate_id = plate["id"]
    sku = _sku_for(p, spec, sku)
    idx = _pick_printer(pid, spec, plate_id, sku, printer)
    prs = _printers()
    pr_ = prs[idx]
    res = {"ok": True, "checks": [], "errors": [], "warnings": [], "printer": idx, "printer_label": _label(pr_, idx),
           "plate": {"id": plate_id, "name": plate.get("name") or "", "no": [x["id"] for x in plan["plates"]].index(plate_id) + 1,
                     "total": len(plan["plates"])}, "sliced_now": False, "file": None, "preview_svg": ""}
    f = None
    try:
        if file_id:
            f = print_files.get(int(file_id))
            if not f or f.get("product_id") != pid:
                raise ValueError("文件不存在，或不是这个产品的")
        else:
            f, res["sliced_now"] = _plate_file(p, pid, spec, plate_id, sku, idx, user, slice_now)
    except ValueError as e:
        _chk(res, "file", "error", str(e), "ไม่มีไฟล์สไลซ์ของถาดนี้ หรือสไลซ์ไม่สำเร็จ")
        res["ok"] = False
        return res
    if not f:
        _chk(res, "file", "error", "这一盘还没有切片文件", "ถาดนี้ยังไม่มีไฟล์สไลซ์")
        res["ok"] = False
        return res
    f = print_files.ensure_params(f)
    res["file"] = _file_brief(f)
    # 0. v2.53.1 文件的产品 / 规格 / 缩放比例 / 盘要和这一盘一致（按主模型缩放的规格不能用主模型 100% 的文件）
    ferr = _file_mismatch(f, p, sku, plate_id, len(plan.get("plates") or []) == 1)
    if ferr:
        _chk(res, "spec", "error", ferr, "ขนาด / สเปกของไฟล์ไม่ตรงกับงาน (เป็นไฟล์ของรุ่นย่อย / ถาดอื่น หรือสเกลไม่ตรง) ห้ามส่งพิมพ์ ให้สไลซ์ใหม่")
    # 1. 机型 / 喷嘴 / 热床板 / FDM（slicecheck）
    sc = slicecheck.check(f, idx)
    if sc["ok"]:
        _chk(res, "machine", "ok", f"机型 / 喷嘴 / 热床板和「{_label(pr_, idx)}」一致", f"รุ่น / หัวฉีด / แผ่นฐาน ตรงกับ「{_label(pr_, idx)}」")
    else:
        for e in sc["errors"]:
            _chk(res, "machine", "error", e, "รุ่นเครื่อง / หัวฉีด / แผ่นฐาน ไม่ตรงกับเครื่องพิมพ์นี้ ส่งไปพิมพ์ไม่ได้")
    # 2. 克数 / 时长 vs 估算
    est = _estimate(p, plan, plate, spec, _colour_for(p, sku))
    g, h = f.get("grams"), f.get("hours")
    res["grams"], res["hours"], res["est_grams"], res["est_hours"] = g, h, est.get("grams"), est.get("hours")
    for key, val, ev, zh, th, unit in (("grams", g, est.get("grams"), "克数", "น้ำหนัก", "g"), ("hours", h, est.get("hours"), "时长", "เวลา", "h")):
        if val and ev:
            dev = abs(float(val) - float(ev)) / float(ev)
            if dev > BIG_DEV:
                _chk(res, key, "warn", f"{zh}和估算差得多：切片 {val:g} {unit}，估算 {ev:g} {unit}（差 {dev * 100:.0f}%）。检查摆放、缩放、支撑、层高",
                     f"{th}ต่างจากที่ประมาณไว้มาก: สไลซ์ {val:g} {unit}, ประมาณ {ev:g} {unit} (ต่าง {dev * 100:.0f}%)")
            else:
                _chk(res, key, "ok", f"{zh}和估算接近：切片 {val:g} {unit}，估算 {ev:g} {unit}", f"{th}ใกล้เคียงที่ประมาณ: {val:g} {unit} / {ev:g} {unit}")
        elif val:
            _chk(res, key, "ok", f"{zh}：{val:g} {unit}（方案里没有可比的估算）", f"{th}: {val:g} {unit}")
    # 3. 零件都在热床上 / 不压废料口（读第一层 G-code）
    pp = _plan_mod()
    pname = pr_.get("name") or ""
    bed = pp.bed_of(pname)
    excl = pp.exclude_of(pname)
    segs = []
    try:
        segs = first_layer(_gcode_text(f))
    except Exception:  # noqa: BLE001  读不出来不影响其他检查
        segs = []
    pts = [pt for s in segs for pt in s]
    res["preview_svg"] = preview_svg(segs, bed, excl)
    if not pts:
        if f.get("kind") == "resin":
            _chk(res, "bed", "ok", "光固化文件，不检查第一层", "ไฟล์เรซิ่น ไม่ตรวจชั้นแรก")
        else:
            _chk(res, "bed", "warn", "读不出第一层路径，没法核对零件位置", "อ่านเส้นทางชั้นแรกไม่ได้ จึงตรวจตำแหน่งชิ้นงานไม่ได้")
    else:
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        bb = [round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)]
        res["first_layer"] = {"bbox": bb, "bed": [bed[0], bed[1]], "points": len(pts)}
        tol = 1.0
        if bb[0] < -tol or bb[1] < -tol or bb[2] > bed[0] + tol or bb[3] > bed[1] + tol:
            _chk(res, "bed", "error", f"有零件在热床外面：第一层范围 X {bb[0]}~{bb[2]}、Y {bb[1]}~{bb[3]} mm，热床 {bed[0]}×{bed[1]} mm",
                 f"มีชิ้นงานอยู่นอกฐานพิมพ์ (X {bb[0]}~{bb[2]}, Y {bb[1]}~{bb[3]} mm ฐาน {bed[0]}×{bed[1]} mm)")
        else:
            _chk(res, "bed", "ok", f"零件都在热床上（第一层 X {bb[0]}~{bb[2]}、Y {bb[1]}~{bb[3]} mm）",
                 f"ชิ้นงานทั้งหมดอยู่บนฐานพิมพ์ (ชั้นแรก X {bb[0]}~{bb[2]}, Y {bb[1]}~{bb[3]} mm)")
        if excl:
            hit = sum(1 for (px, py) in pts if excl[0] - 0.3 <= px <= excl[2] - 0.3 and excl[1] - 0.3 <= py <= excl[3] - 0.3)
            if hit:
                _chk(res, "exclude", "error", f"零件压到了拓竹热床左前角的废料口（{excl[2]:g}×{excl[3]:g} mm）。重新摆盘，把零件挪出这块区域",
                     f"ชิ้นงานทับช่องทิ้งเศษที่มุมซ้ายหน้าของฐาน Bambu ({excl[2]:g}×{excl[3]:g} mm) ให้จัดวางใหม่")
            else:
                _chk(res, "exclude", "ok", "没有压到废料口", "ไม่ทับช่องทิ้งเศษ")
    # 4. 颜色槽 vs 方案
    if f.get("kind") != "resin":
        used, planned = _slots_used(f), sorted({int(it.get("slot") or 1) for it in plate.get("items") or []}) or [1]
        res["slots"] = {"used": used, "planned": planned}
        if used:
            miss = [s for s in planned if s not in used] if len(planned) > 1 else []
            extra = [s for s in used if s not in planned] if len(planned) > 1 else []
            if miss or extra:
                _chk(res, "slots", "error", f"颜色槽和方案不一致：方案用槽 {planned}，切片文件实际用到槽 {used}",
                     f"ช่องสีไม่ตรงกับแผน: แผนใช้ช่อง {planned} ไฟล์ใช้จริง {used}")
            else:
                _chk(res, "slots", "ok", f"颜色槽和方案一致（槽 {used}）", f"ช่องสีตรงกับแผน (ช่อง {used})")
        elif len(planned) > 1:
            _chk(res, "slots", "warn", "读不出切片文件用了哪几个颜色槽", "อ่านไม่ได้ว่าไฟล์ใช้ช่องสีไหน")
    res["ok"] = not res["errors"]
    return res


def _slots_used(f):
    try:
        from . import slicer
        info = slicer.parse_sliced_file(print_files.path_of(f))
    except Exception:  # noqa: BLE001
        return []
    return [int(x["slot"]) for x in info.get("filaments") or [] if float(x.get("grams") or 0) > 0]


def _estimate(p, plan, plate, spec, colour):
    """这一盘按模型体积估的克数 / 时长（不看切片结果）。"""
    pp = _plan_mod()
    try:
        u = pp.plate_usage(p, plan, dict(plate, sliced=None), colour)
        return {"grams": round((u["grams"] + u["purge_g"]) or 0, 1) or None, "hours": u["hours"] or None}
    except Exception:  # noqa: BLE001
        return {}
