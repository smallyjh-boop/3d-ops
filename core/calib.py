"""用真实数据校准（v2.15）：估算克数 / 时长、每台打印机每小时打几克、空打风险阈值。

数据来源（都是系统里已经有的，不用额外录入）：
  - 切片文件（拓竹 / Orca / Creality 导出的，里面有真实克数和时长）＋ 产品 3D 模型的体积 → 克数估算偏多少
  - 试打验证时填的实际克数 / 时长、打印批次的开始 / 结束时间 → 切片时长和实际差多少
  - 打印失败记录（原因是「翘边 / 首层不粘」「打飞 / 脱离热床」）＋ 打印方案的摆放方向 → 空打阈值是不是太松
只给建议，老板点「应用」才改设置；每次应用都记在操作日志里。
"""
import json
import statistics
import time

from . import db, mesh, slicer, store
from .config import load_config, save_config

RISK_DEFAULT = {"contact_bad": 0.3, "contact_warn": 1.5, "overhang_bad": 8.0, "overhang_warn": 1.5, "tall_warn": 4.0, "tall_bad": 6.0}
ADHESION = ("翘边", "首层", "打飞", "脱离", "空打")
MIN_N = 3          # 至少几条数据才给建议


def risk_thresholds(cfg=None):
    cfg = cfg if cfg is not None else load_config()
    out = dict(RISK_DEFAULT)
    for k, v in (cfg.get("risk_thresholds") or {}).items():
        if k in out:
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                pass
    return out


def risk_key(cfg=None):
    """阈值改了，模型库里存的风险等级要重新算：用这个短字符串判断。"""
    th = risk_thresholds(cfg)
    return ",".join(f"{th[k]:g}" for k in sorted(th))


def mat_key(material):
    m = str(material or "PLA").upper()
    for k in ("PETG", "PLA", "ABS", "ASA", "TPU", "PC", "PA", "RESIN"):
        if m.startswith(k):
            return k
    return m.split("-")[0]


def _median(xs):
    return round(statistics.median(xs), 3) if xs else None


def _rows(sql, args=()):
    try:
        return [dict(r) for r in db.conn().execute(sql, args)]
    except Exception:  # noqa: BLE001  表还没建（新装的系统）
        return []


# ---------------- 1. 克数：估算 vs 切片文件 ----------------
def grams_pairs(cfg):
    """每个有 3D 模型、又有 FDM 切片文件的产品：(材料, 估算单件克数（不含校准）, 切片单件克数)。"""
    out = []
    base = dict(cfg, est_calibration=1.0, est_calibration_by_mat={})
    files = _rows("SELECT product_id, grams, per_plate, status, kind FROM print_files WHERE active=1 AND grams>0 AND COALESCE(per_plate,1)>0")
    seen = {}
    for f in files:
        if str(f.get("kind") or "").startswith("resin"):
            continue
        pid = f["product_id"]
        per = f["grams"] / max(1, int(f["per_plate"] or 1))
        if pid in seen and f.get("status") not in ("reviewed", "verified"):
            continue
        seen[pid] = per
    for pid, real in seen.items():
        try:
            p = store.load(pid)
        except (FileNotFoundError, ValueError):
            continue
        met = (p.get("model") or {}).get("metrics") or {}
        if not met.get("volume_mm3") or (p.get("model") or {}).get("parts_of"):
            continue          # 没有体积数据，或是合并的整套（切片按「套」算，不好对比），跳过
        mat = p.get("material") or "PLA"
        if mat_key(mat) == "RESIN":
            continue
        est = slicer.estimate(base, met, mat).get("grams")
        if est:
            out.append({"product_id": pid, "material": mat_key(mat), "est": round(est, 1), "real": round(real, 1), "ratio": round(real / est, 3)})
    return out


# ---------------- 2. 速度：每台打印机每小时打几克（从切片文件算） ----------------
def speed_rows(cfg):
    prs = cfg.get("printers") or []
    out = []
    files = _rows("SELECT printer, grams, hours FROM print_files WHERE active=1 AND grams>0 AND hours>0.2")
    over = float(cfg.get("est_overhead_h", 0.15))
    by = {}
    for f in files:
        by.setdefault(f["printer"] or "", []).append(f["grams"] / max(0.05, f["hours"] - over))
    for i, p in enumerate(prs):
        name = p.get("name") or ""
        xs = [x for k, v in by.items() for x in v if k and (k == name or k == p.get("code") or k in name)]
        out.append({"idx": i, "code": p.get("code") or f"#{i + 1}", "name": name, "now": p.get("g_per_h") or 20,
                    "n": len(xs), "suggest": round(_median(xs), 1) if len(xs) >= MIN_N else None})
    return out


# ---------------- 3. 时长：切片时长 vs 实际 ----------------
def time_rows(cfg):
    prs = cfg.get("printers") or []
    runs = _rows("SELECT printer, hours, started_at, ended_at FROM print_runs WHERE status IN ('done','packed','post') "
                 "AND started_at>0 AND ended_at>started_at AND hours>0.2")
    ver = _rows("SELECT printer, hours, actual_hours FROM print_files WHERE actual_hours>0 AND hours>0")
    by = {}
    for r in runs:
        real = (r["ended_at"] - r["started_at"]) / 3600
        if 0.3 < real / r["hours"] < 3:
            by.setdefault(r["printer"], []).append(real / r["hours"])
    ratios_ver = [v["actual_hours"] / v["hours"] for v in ver if 0.3 < v["actual_hours"] / v["hours"] < 3]
    out = []
    for i, p in enumerate(prs):
        xs = by.get(i, [])
        out.append({"idx": i, "code": p.get("code") or f"#{i + 1}", "name": p.get("name") or "", "n": len(xs), "ratio": _median(xs)})
    return out, {"n": len(ratios_ver), "ratio": _median(ratios_ver)}


# ---------------- 4. 打印失败 vs 摆放方向的风险等级 ----------------
def failure_rows(days=180):
    since = time.time() - days * 86400
    runs = _rows("SELECT id, product_id, status FROM print_runs WHERE COALESCE(ended_at, started_at, 0)>=? AND status IN ('done','packed','post','failed')", (since,))
    fails = _rows("SELECT run_id, product_id, reason FROM failures WHERE ts>=?", (since,))
    fail_by_run = {f["run_id"]: f for f in fails}
    stat = {lv: {"runs": 0, "adhesion": 0, "other": 0} for lv in ("ok", "warn", "bad", "unknown")}
    contact_ok_fail = []   # 风险「没问题」但还是打飞 / 翘边的：贴平台面积
    cache = {}
    for r in runs:
        pid = r["product_id"]
        if pid not in cache:
            cache[pid] = _orient_state(pid)
        lv, contact = cache[pid]
        s = stat[lv]
        s["runs"] += 1
        f = fail_by_run.get(r["id"])
        if f:
            if any(k in (f["reason"] or "") for k in ADHESION):
                s["adhesion"] += 1
                if lv == "ok" and contact is not None:
                    contact_ok_fail.append(contact)
            else:
                s["other"] += 1
    for s in stat.values():
        s["rate"] = round(s["adhesion"] / s["runs"] * 100, 1) if s["runs"] else None
    return stat, contact_ok_fail


def _orient_state(pid):
    """这个产品现在的打印方向下的风险等级和贴平台面积（来自模型库分析）。"""
    try:
        p = store.load(pid)
    except (FileNotFoundError, ValueError):
        return "unknown", None
    lib_id = (p.get("model") or {}).get("lib_id")
    e = next((x for x in p.get("model_lib") or [] if x.get("id") == lib_id), None)
    orient = (p.get("recipe") or {}).get("orientation") or "bottom"
    o = next((x for x in ((e or {}).get("info") or {}).get("orients") or [] if x.get("key") == orient), None)
    if not o:
        return "unknown", None
    return o.get("level") or "unknown", o.get("contact_cm2")


# ---------------- 汇总 + 建议 ----------------
def report(cfg=None):
    cfg = cfg or load_config()
    gp = grams_pairs(cfg)
    by_mat = {}
    for x in gp:
        by_mat.setdefault(x["material"], []).append(x["ratio"])
    cur = cfg.get("est_calibration_by_mat") or {}
    grams = [{"material": m, "n": len(v), "now": cur.get(m, cfg.get("est_calibration", 1.0)),
              "suggest": _median([min(3, max(0.33, r)) for r in v]) if len(v) >= MIN_N else None} for m, v in sorted(by_mat.items())]
    speeds = speed_rows(cfg)
    times, ver = time_rows(cfg)
    fstat, ok_fail = failure_rows()
    th = risk_thresholds(cfg)
    risk_suggest = None
    # 风险显示「没问题」的产品里，因为打飞 / 翘边失败的比例明显偏高 → 把「贴平台面积小」的提醒线往上调
    ok = fstat["ok"]
    if ok["runs"] >= 10 and ok["adhesion"] >= MIN_N and (ok["rate"] or 0) >= 5 and ok_fail:
        q75 = sorted(ok_fail)[int(len(ok_fail) * 0.75) if len(ok_fail) > 1 else 0]
        new_warn = round(min(6.0, max(th["contact_warn"] * 1.2, q75)), 1)
        if new_warn > th["contact_warn"]:
            risk_suggest = {"contact_warn": new_warn, "why": f"风险显示「没问题」的批次里，有 {ok['adhesion']} 次因为翘边 / 打飞失败（{ok['rate']}%）"}
    return {"grams": grams, "grams_pairs": gp[:200], "speeds": speeds, "times": times, "verify_time": ver,
            "failures": fstat, "risk": th, "risk_default": RISK_DEFAULT, "risk_suggest": risk_suggest, "min_n": MIN_N}


def apply(kind, data, user=""):
    """应用建议。kind: grams（按材料的克数系数）/ speed（打印机每小时克数）/ risk（空打阈值）。"""
    cfg = load_config()
    if kind == "grams":
        m = dict(cfg.get("est_calibration_by_mat") or {})
        for k, v in (data or {}).items():
            v = float(v)
            if not 0.33 <= v <= 3:
                raise ValueError(f"{k} 的系数 {v} 不合理")
            m[str(k)] = round(v, 3)
        save_config({"est_calibration_by_mat": m})
    elif kind == "speed":
        prs = list(cfg.get("printers") or [])
        for k, v in (data or {}).items():
            i, v = int(k), float(v)
            if not 3 <= v <= 120:
                raise ValueError(f"每小时 {v} 克不合理")
            if 0 <= i < len(prs):
                prs[i] = dict(prs[i], g_per_h=round(v, 1))
        save_config({"printers": prs})
    elif kind == "risk":
        th = {} if data == "reset" else dict(cfg.get("risk_thresholds") or {})
        for k, v in (data if isinstance(data, dict) else {}).items():
            if k in RISK_DEFAULT:
                v = float(v)
                if not 0 < v < 100:
                    raise ValueError(f"{k} = {v} 不合理")
                th[k] = v
        save_config({"risk_thresholds": th})
    else:
        raise ValueError("不支持的校准项目")
    db.audit(user, "应用校准", kind, json.dumps(data, ensure_ascii=False)[:300])
    return report()
