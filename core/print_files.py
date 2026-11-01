"""打印文件库（切片文件）：每个产品在每台打印机上用哪个切片文件、一盘几个、每盘多少克多久。

每个文件有状态：
- draft     草稿：刚切好/刚上传，还没人确认，不能用于生产
- reviewed  已复核：AI/规则检查过，人工确认了支撑、方向、数量、参数，可以生产（显示「未试打」）
- verified  已验证：试打过，实际打出来合格（最可靠）
同一个产品 + 打印机 + 一盘数量，生成新文件时自动加版本号，旧版本保留（可以停用/恢复）。

- 拓竹 P1S 用切片好的 .gcode.3mf；Creality K1 系列用 .gcode（发送时自动从 3MF 里取出 G-code）。
"""
import json
import math
import os
import re
import shutil
import time
import zipfile

from . import db, slicer
from .config import DATA_DIR

FILE_DIR = os.path.join(DATA_DIR, "print_files")
STATUS_ZH = {"draft": "草稿（未复核）", "reviewed": "已复核（未试打）", "verified": "已试打验证"}
STATUS_RANK = {"verified": 3, "reviewed": 2, "draft": 1}
REVIEW_ITEMS = [("supports", "支撑设置正确"), ("orientation", "摆放方向正确"), ("count", "数量和排版正确"),
                ("params", "层高 / 填充 / 壁数 / 热床板正确"), ("material", "材料和颜色正确")]

SCHEMA = """
CREATE TABLE IF NOT EXISTS print_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id TEXT, sku TEXT, printer TEXT, color TEXT,
  filename TEXT, stored TEXT, kind TEXT, size INTEGER,
  per_plate INTEGER DEFAULT 1, grams REAL, hours REAL,
  note TEXT, active INTEGER DEFAULT 1, created_at REAL, username TEXT
);
CREATE INDEX IF NOT EXISTS pf_product ON print_files(product_id);
"""
NEW_COLS = (("status", "TEXT DEFAULT 'draft'"), ("version", "INTEGER DEFAULT 1"), ("source", "TEXT"),
            ("recipe", "TEXT"), ("report", "TEXT"), ("checks", "TEXT"), ("ai_review", "TEXT"),
            ("reviewed_by", "TEXT"), ("reviewed_at", "REAL"), ("review_items", "TEXT"),
            ("verified_by", "TEXT"), ("verified_at", "REAL"), ("verify_note", "TEXT"),
            ("actual_grams", "REAL"), ("actual_hours", "REAL"), ("photo", "TEXT"),
            ("spec", "TEXT DEFAULT ''"),          # v2.22：这个文件是哪个规格的（规格有自己的模型时；空 = 主模型）
            ("plate_id", "TEXT DEFAULT ''"))      # v2.52：打印方案里的哪一盘（几盘的方案每盘一个文件；空 = 整件）


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(print_files)")}
    for col, typ in NEW_COLS:
        if col not in cols:
            c.execute(f"ALTER TABLE print_files ADD COLUMN {col} {typ}")
            if col == "status":   # 以前上传的文件当作「已复核」，不影响已经在用的
                c.execute("UPDATE print_files SET status='reviewed'")
    c.commit()
    os.makedirs(FILE_DIR, exist_ok=True)


def _kind(name):
    from .fleet import RESIN_EXT
    n = name.lower()
    if n.endswith(".gcode.3mf") or n.endswith(".3mf"):
        return "3mf"
    if n.endswith(".gcode") or n.endswith(".gco"):
        return "gcode"
    if os.path.splitext(n)[1] in RESIN_EXT:
        from . import chain
        if not chain.resin_on():
            raise ValueError("「树脂打印（光固化）」模块没有打开，不能上传光固化文件（设置 → 模块管理）")
        return "resin"
    raise ValueError("只支持切片好的 .gcode.3mf / .3mf（拓竹）、.gcode（Creality），"
                     "或光固化切片文件（.pm5s / .pwmx / .ctb / .goo 等）")


def _safe(name):
    base = os.path.basename(name or "file")
    base = re.sub(r"[^\w.\-]+", "_", base, flags=re.ASCII).strip("._") or "file"
    return base[-80:]


def _has_gcode(path):
    try:
        with zipfile.ZipFile(path) as z:
            return any(n.startswith("Metadata/plate_") and n.endswith(".gcode") for n in z.namelist())
    except zipfile.BadZipFile:
        return False


def _report_for_upload(path, kind, bed):
    from . import recipes
    try:
        if kind == "3mf":
            with zipfile.ZipFile(path) as z:
                gname = next(n for n in z.namelist() if n.startswith("Metadata/plate_") and n.endswith(".gcode"))
                text = z.read(gname).decode("utf-8", "ignore")
            return recipes.report_from(path, text, bed)
        text = open(path, "rb").read().decode("utf-8", "ignore")
        g = recipes._gcode_report(text)
        st = slicer.parse_gcode_text(text[:400000] + text[-400000:]) or {}
        return {"grams_per_plate": st.get("grams"), "hours_per_plate": st.get("hours"), "layers": g.get("layers"),
                "support_pct": g.get("support_pct"), "preview": recipes._svg(g.get("first_layer") or [], bed, []),
                "params": recipes.params_from(text, "gcode")}
    except Exception:  # 报告只是参考，读不出来不影响上传
        return {"params": recipes.params_from(path, kind)}


def add(src_path, filename, product_id, printer, sku="", per_plate=1, color="", note="", user="", material="PLA",
        grams=None, hours=None, move=False, recipe=None, report=None, checks=None, source="upload", bed=None, spec="", plate_id=""):
    kind = _kind(filename)
    if kind == "resin":
        # 光固化：从文件里读时间 / 树脂用量（读不到的由人手填）
        from . import resinfile
        from .config import load_config
        info = resinfile.parse(src_path, load_config().get("resin_density") or 1.1)
        report = dict(report or {}, resin=info, layers=info.get("layers"))
        if grams is None:
            grams = info.get("grams")
        if hours is None:
            hours = info.get("hours")
        bed = None
    if kind == "3mf" and not _has_gcode(src_path):
        raise ValueError("这个 3MF 里没有切片数据。请在 Bambu Studio / OrcaSlicer 里用「导出切片文件（Export plate sliced file）」，"
                         "不是普通的「导出 3MF」")
    if kind == "3mf":
        with zipfile.ZipFile(src_path) as z:
            n = sum(1 for x in z.namelist() if x.startswith("Metadata/plate_") and x.endswith(".gcode"))
        if n > 1:
            raise ValueError(f"这个文件里有 {n} 个盘。发送打印时一次打一个盘，请在切片软件里每个盘单独导出（Export plate sliced file）")
    if report is None and bed:
        report = _report_for_upload(src_path, kind, bed)
    report = report or {}
    if grams is None:
        grams = report.get("grams_per_plate")
    if hours is None:
        hours = report.get("hours_per_plate")
    if (grams is None or hours is None) and kind != "resin":
        try:
            info = slicer.parse_sliced_file(src_path, material)
            grams = grams if grams is not None else info.get("grams")
            hours = hours if hours is not None else info.get("hours")
        except Exception:   # 读不出来就让用户手填
            pass
    c = db.conn()
    sku = (sku or "").strip().upper()
    spec = (spec or "").strip()
    ver = (c.execute("SELECT MAX(version) FROM print_files WHERE product_id=? AND printer=? AND COALESCE(sku,'')=? "
                     "AND per_plate=? AND COALESCE(spec,'')=?", (product_id, printer or "*", sku, max(1, int(per_plate or 1)), spec)).fetchone()[0] or 0) + 1
    fid = c.execute("""INSERT INTO print_files(product_id, sku, printer, color, filename, kind, per_plate, grams, hours, note,
                       created_at, username, status, version, source, recipe, report, checks)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (product_id, sku, printer or "*", color or "", _safe(filename), kind,
                     max(1, int(per_plate or 1)), grams, hours, note or "", time.time(), user, "draft", ver, source,
                     json.dumps(recipe, ensure_ascii=False) if recipe else None,
                     json.dumps(report, ensure_ascii=False) if report else None,
                     json.dumps(checks, ensure_ascii=False) if checks else None)).lastrowid
    os.makedirs(FILE_DIR, exist_ok=True)
    stored = f"{fid}_{_safe(filename)}"
    dst = os.path.join(FILE_DIR, stored)
    (shutil.move if move else shutil.copyfile)(src_path, dst)
    c.execute("UPDATE print_files SET stored=?, size=?, spec=?, plate_id=? WHERE id=?",
              (stored, os.path.getsize(dst), spec, (plate_id or "").strip(), fid))
    c.commit()
    return get(fid)


def ensure_params(f):
    """以前的文件没有记录切片参数：第一次打开时补读一次并保存。"""
    if not f or (f.get("report") or {}).get("params") is not None:
        return f
    from . import recipes
    rep = dict(f.get("report") or {})
    try:
        rep["params"] = {} if f.get("kind") == "resin" else recipes.params_from(path_of(f), f.get("kind") or "3mf")
    except Exception:  # noqa: BLE001
        rep["params"] = {}
    c = db.conn()
    c.execute("UPDATE print_files SET report=? WHERE id=?", (json.dumps(rep, ensure_ascii=False), f["id"]))
    c.commit()
    return {**f, "report": {**(f.get("report") or {}), "params": rep["params"]}}


def material_of(f):
    return ((f or {}).get("report") or {}).get("params", {}).get("material") if f else None


def gcode_from_3mf(path_3mf, out_path, plate=1):
    """从切片好的 3MF 里取出 G-code（给 Creality 用）。"""
    with zipfile.ZipFile(path_3mf) as z:
        name = f"Metadata/plate_{plate}.gcode"
        if name not in z.namelist():
            cands = [n for n in z.namelist() if n.startswith("Metadata/plate_") and n.endswith(".gcode")]
            if not cands:
                raise ValueError("3MF 里没有 G-code")
            name = cands[0]
        with z.open(name) as src, open(out_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return out_path


def _out(r, full=True):
    if not r:
        return None
    d = dict(r)
    for k in ("recipe", "report", "checks", "ai_review", "review_items"):
        try:
            d[k] = json.loads(d[k]) if d.get(k) else None
        except ValueError:
            d[k] = None
    if not full and d.get("report"):
        d["report"] = {k: v for k, v in d["report"].items() if k != "preview"}
    d["status_zh"] = STATUS_ZH.get(d.get("status") or "draft")
    return d


def get(fid):
    return _out(db.conn().execute("SELECT * FROM print_files WHERE id=?", (fid,)).fetchone())


def path_of(f):
    return os.path.join(FILE_DIR, f["stored"])


def list_files(product_id=None, full=False):
    c = db.conn()
    if product_id:
        rows = c.execute("SELECT * FROM print_files WHERE product_id=? ORDER BY printer, per_plate, version DESC, id DESC",
                         (product_id,))
    else:
        rows = c.execute("SELECT * FROM print_files ORDER BY product_id, printer, per_plate, version DESC, id DESC")
    return [_out(r, full) for r in rows]


def update(fid, **kw):
    allowed = ("sku", "printer", "per_plate", "grams", "hours", "note", "active", "color", "spec")
    sets = {k: v for k, v in kw.items() if k in allowed and v is not None}
    if "sku" in sets:
        sets["sku"] = str(sets["sku"]).strip().upper()
    if "per_plate" in sets:
        sets["per_plate"] = max(1, int(sets["per_plate"]))
    if not sets:
        return get(fid)
    c = db.conn()
    c.execute(f"UPDATE print_files SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), fid))
    c.commit()
    return get(fid)


def set_checks(fid, checks=None, ai=None):
    c = db.conn()
    if checks is not None:
        c.execute("UPDATE print_files SET checks=? WHERE id=?", (json.dumps(checks, ensure_ascii=False), fid))
    if ai is not None:
        c.execute("UPDATE print_files SET ai_review=? WHERE id=?", (json.dumps(ai, ensure_ascii=False), fid))
    c.commit()
    return get(fid)


def review(fid, items, user, note=""):
    """人工复核：每一项都要勾上。"""
    missing = [label for k, label in REVIEW_ITEMS if not items.get(k)]
    if missing:
        raise ValueError("还有没确认的项目：" + "、".join(missing))
    f = get(fid)
    if not f:
        raise ValueError("文件不存在")
    if any(x.get("level") == "error" for x in (f.get("checks") or [])):
        raise ValueError("自动检查有「错误」项，不能通过复核，请调整方案重新切片")
    c = db.conn()
    status = f["status"] if f["status"] == "verified" else "reviewed"
    c.execute("UPDATE print_files SET status=?, reviewed_by=?, reviewed_at=?, review_items=?, note=COALESCE(NULLIF(?,''),note) "
              "WHERE id=?", (status, user, time.time(), json.dumps(items), note, fid))
    c.commit()
    return get(fid)


def verify(fid, ok, user, actual_grams=None, actual_hours=None, note="", photo=None):
    """试打结果：合格 → 已验证；不合格 → 回到草稿。"""
    c = db.conn()
    if ok:
        c.execute("UPDATE print_files SET status='verified', verified_by=?, verified_at=?, verify_note=?, actual_grams=?, "
                  "actual_hours=?, photo=COALESCE(?, photo) WHERE id=?",
                  (user, time.time(), note, actual_grams, actual_hours, photo, fid))
    else:
        c.execute("UPDATE print_files SET status='draft', verify_note=?, photo=COALESCE(?, photo) WHERE id=?",
                  (f"试打不合格：{note}", photo, fid))
    c.commit()
    return get(fid)


def delete(fid):
    f = get(fid)
    if not f:
        return
    try:
        os.remove(path_of(f))
    except OSError:
        pass
    c = db.conn()
    c.execute("DELETE FROM print_files WHERE id=?", (fid,))
    c.commit()


def _printer_ok(file_printer, printer_name):
    return file_printer in ("*", "", None) or file_printer == printer_name


_CFG_MEMO = {"t": "", "cfg": None}


def _cfg_cached():
    """排单时每个任务都要查一遍：设置文件没改过就不重复读（v2.40 审查：性能）。"""
    from .config import CONFIG_PATH, load_config
    try:
        st = os.stat(CONFIG_PATH)
        mt = (st.st_mtime_ns, st.st_size)
    except OSError:
        mt = None
    if _CFG_MEMO["cfg"] is None or _CFG_MEMO["t"] != mt:
        _CFG_MEMO.update(t=mt, cfg=load_config())
    return _CFG_MEMO["cfg"]


def candidates(product_id, sku, printer_name, color="", usable_only=True, plate_id=None):
    """这台打印机能用的文件，按合适程度排序：同 SKU > 同颜色 > 已验证 > 已复核 > 新版本。
    plate_id（v2.52）：几盘的打印方案里某一盘的任务只用这一盘的文件（None = 不按盘筛，整件打的任务）。"""
    if not product_id:
        return []
    rows = [_out(r, False) for r in db.conn().execute(
        "SELECT * FROM print_files WHERE product_id=? AND active=1 ORDER BY id DESC", (product_id,))]
    rows = [r for r in rows if _printer_ok(r["printer"], printer_name)]
    if plate_id is not None:
        rows = [r for r in rows if (r.get("plate_id") or "") == plate_id]
    # v2.22：规格有自己的模型时只用这个规格的文件；没有（用主模型）时只用主模型的文件
    try:
        from . import specmodel, store
        p = store.load(product_id)
        sp = specmodel.spec_of_sku(p, sku)
        want = sp if (sp and specmodel.own(p, sp)) else ""
        rows = [r for r in rows if (r.get("spec") or "") == want or (r["sku"] and r["sku"] == (sku or "").strip().upper())]
    except FileNotFoundError:
        pass
    if usable_only:
        rows = [r for r in rows if r.get("status") in ("reviewed", "verified")]
        # 材料和产品现在的材料不一样的文件不能用（例如产品从 PLA 改成 PETG 以后，旧文件作废）
        try:
            from . import recipes, store
            need = store.load(product_id).get("material") or "PLA"
            rows = [r for r in rows if not material_of(r) or recipes.same_material(material_of(r), need) != "diff"]
        except Exception:  # noqa: BLE001
            pass
        # v2.40：机型 / 喷嘴 / 热床板对不上这台打印机的文件不算能用（以前排单和开始对话框会选中它，开始时才报错）
        try:
            from modules.prod import slicecheck
            cfg = _cfg_cached()
            idx = next((i for i, p in enumerate(cfg.get("printers") or []) if (p.get("name") or "") == printer_name), None)
            if idx is not None:
                rows = [r for r in rows if slicecheck.check(r, idx, cfg)["ok"]]
        except ImportError:
            pass
    sku = (sku or "").strip().upper()

    def score(r):
        s = 0
        if r["sku"] and r["sku"] == sku:
            s += 1000
        elif r["sku"]:
            return -1          # 别的 SKU 专用
        if r["color"] and color and r["color"] == color:
            s += 200
        elif r["color"] and color and r["color"] != color:
            s -= 50
        if r["printer"] == printer_name:
            s += 100
        s += STATUS_RANK.get(r.get("status") or "draft", 0) * 20 + (r.get("version") or 1) * 0.01
        return s
    rows = [r for r in rows if score(r) >= 0]
    rows.sort(key=score, reverse=True)
    return rows


def find(product_id, sku, printer_name, color="", per_plate=None, plate_id=None):
    rows = candidates(product_id, sku, printer_name, color, plate_id=plate_id)
    if per_plate:
        rows = [r for r in rows if int(r["per_plate"]) == int(per_plate)] or []
    return rows[0] if rows else None


def plan(job, printer_name):
    """这个任务（还剩多少个）在这台打印机上：用哪个文件、几盘、总克数、总小时。没有可用文件时用产品估算。"""
    qty = max(0, int(job.get("qty") or 1) - int(job.get("qty_done") or 0))
    rows = candidates(job.get("product_id"), job.get("sku"), printer_name, job.get("color") or "")
    if rows:
        # 优先用一盘数量最大的可用文件（盘数最少）
        best = max(rows[:6], key=lambda r: (min(qty, r["per_plate"]), STATUS_RANK.get(r["status"], 0)))
        per = max(1, int(best["per_plate"] or 1))
        plates = math.ceil(qty / per) if qty else 0
        g1 = best["grams"] or (job.get("grams_each") or 0) * per
        h1 = best["hours"] or (job.get("hours_each") or 1) * per
        # 最后一盘不满时按比例估
        full, rest = divmod(qty, per)
        g = g1 * full + (g1 / per * rest if rest else 0)
        h = h1 * full + (h1 / per * rest * 1.1 if rest else 0)
        from .fleet import is_resin
        if is_resin(job.get("material")) or best.get("kind") == "resin":
            h = h1 * plates          # 光固化：一盘的时间看高度，放几个都差不多
        return {"file": best, "per_plate": per, "plates": plates, "grams": round(g, 1), "hours": round(h, 2)}
    return {"file": None, "per_plate": qty or 1, "plates": 1 if qty else 0,
            "grams": round((job.get("grams_each") or 0) * qty, 1), "hours": round((job.get("hours_each") or 1) * qty, 2)}
