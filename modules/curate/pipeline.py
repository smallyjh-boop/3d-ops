"""后台：不占网页请求（模块启动时开一个线程；有新东西时 kick() 叫醒它）。
  · 采用的产品草稿：原站图片下载进产品图片；模型文件都下载完以后 adopt.post_process（ERP 模型库分析、3D 模型、
    从文件名识别规格建变体、克数 / 时长、ERP 的 AI 文案）
  · 候选池 AI 打分（一次 20 个）
  · 估算校准：列表页 AI 估算 vs 实测（ERP 生产记录里真实打印的时长 / 克数优先，没有就用模型库的切片数据 / 估算），至少 5 个样本
"""
import threading
import time
import traceback

from core.config import load_config

from . import adopt, cand, db, rules

_ev = threading.Event()
_started = []
_busy = threading.Lock()


def kick():
    _ev.set()


def start():
    if _started:
        return
    _started.append(1)
    threading.Thread(target=_loop, daemon=True, name="curate-pipeline").start()


def _loop():
    last_cal = 0
    while True:
        _ev.wait(60)
        _ev.clear()
        try:
            for _ in range(50):
                if not run_once():
                    break
            try:
                from . import pool
                pool.auto_clean()          # v2.53：每天一次（同样的规则，上限）
            except Exception:  # noqa: BLE001
                pass
            if time.time() - last_cal > 600:
                last_cal = time.time()
                calibrate()
        except Exception:  # noqa: BLE001
            try:
                from core import diag
                diag.log.error("选品后台出错：%s", traceback.format_exc()[-2000:])
            except Exception:  # noqa: BLE001
                pass


def run_once(cfg=None):
    """做一件事。返回有没有做事。测试里直接循环调用（run_all）。"""
    with _busy:
        cfg = cfg or load_config()
        c = db.conn()
        r = c.execute("SELECT DISTINCT product_id FROM cur_files WHERE kind='image' AND state='img' LIMIT 1").fetchone()
        if r:
            return adopt.pull_images(r["product_id"]) > 0
        # 采用后马上写 AI 文案（不等模型文件）：详情页最多等 COPY_WAIT_DETAIL 秒（有描述 / 标签写得更好），扩展没开就只按标题写
        for q in c.execute("SELECT id, product_id, state, created_at FROM cur_collect WHERE copy=0 AND product_id<>''").fetchall():
            if q["state"] in ("waiting", "running") and time.time() - (q["created_at"] or 0) < adopt.COPY_WAIT_DETAIL:
                continue
            if not cand.ai_on(cfg):
                break                                  # 没设 AI：等设好了再写
            c.execute("UPDATE cur_collect SET copy=1 WHERE id=?", (q["id"],))
            c.commit()
            adopt.write_copy(q["product_id"], cfg)
            return True
        for q in c.execute("SELECT id, product_id, post FROM cur_collect WHERE post IN (1, 3) AND product_id<>''").fetchall():
            if q["post"] == 1 and adopt.files_pending(q["product_id"]):
                continue
            try:
                adopt.post_process(q["product_id"], cfg)
            finally:
                c.execute("UPDATE cur_collect SET post=2 WHERE id=?", (q["id"],))
                c.commit()
            return True
        return cand.ai_batch(cfg) > 0


def run_all(cfg=None, limit=200):
    n = 0
    while n < limit and run_once(cfg):
        n += 1
    return n


def production_actuals(pid):
    """ERP 生产记录里这个产品一件的实际打印时长（分钟）/ 克数：打完的打印批次（开始到结束 ÷ 件数）优先，
    没有就用切片文件（克数 / 时长 ÷ 每盘件数）。没有返回 None。"""
    from core import db as cdb
    try:
        runs = cdb.conn().execute("SELECT count, grams, hours, started_at, ended_at FROM print_runs WHERE product_id=? AND status IN ('done','packed','post') "
                                  "AND count>0", (pid,)).fetchall()
    except Exception:  # noqa: BLE001
        runs = []
    mins, grams = [], []
    for r in runs:
        h = (r["ended_at"] - r["started_at"]) / 3600 if r["ended_at"] and r["started_at"] and r["ended_at"] > r["started_at"] else (r["hours"] or 0)
        if h > 0:
            mins.append(h * 60 / r["count"])
        if r["grams"]:
            grams.append(r["grams"] / r["count"])
    if not mins and not grams:
        try:
            fs = cdb.conn().execute("SELECT grams, hours, per_plate FROM print_files WHERE product_id=? AND active=1 AND grams>0", (pid,)).fetchall()
        except Exception:  # noqa: BLE001
            fs = []
        for f in fs:
            n = max(1, f["per_plate"] or 1)
            grams.append(f["grams"] / n)
            if f["hours"]:
                mins.append(f["hours"] * 60 / n)
    if not mins and not grams:
        return None
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else 0  # noqa: E731
    return {"minutes": round(med(mins), 1), "grams": round(med(grams), 1), "src": "production"}


def product_measured(pid):
    """没有生产记录时：产品第一个变体的克数 / 时长（模型库的切片数据或估算）。"""
    from core import store
    try:
        p = store.load(pid)
    except (FileNotFoundError, ValueError):
        return None
    v = (p.get("variants") or [{}])[0]
    if v.get("grams") or v.get("hours"):
        return {"minutes": round(float(v.get("hours") or 0) * 60, 1), "grams": float(v.get("grams") or 0), "src": (p.get("source") or {}).get("time_source") or "erp"}
    return None


def calibrate(cfg=None):
    """校准系数 {m, g, n, production}，存在 cur_settings.calib；系数变了候选池全部重算。实测也写回候选（real）。"""
    cfg = cfg or load_config()
    c = db.conn()
    pairs, n_prod = [], 0
    for r in c.execute("SELECT id, product_id, ai FROM cur_candidates WHERE product_id<>'' AND ai<>''").fetchall():
        ai = db.jl(r["ai"])
        em, eg = rules.tf(ai.get("est_minutes")), rules.tf(ai.get("est_grams"))
        real = production_actuals(r["product_id"])
        if real:
            n_prod += 1
        else:
            real = product_measured(r["product_id"])
        if not real:
            continue
        import json
        c.execute("UPDATE cur_candidates SET real=? WHERE id=?", (json.dumps(real), r["id"]))
        if em or eg:
            pairs.append((em, real["minutes"], eg, real["grams"]))
    c.commit()
    new = rules.calib_from_pairs(pairs)
    new["production"] = n_prod
    new["at"] = time.time()
    old = db.get("calib") or {}
    db.put("calib", new)
    if (old.get("m"), old.get("g")) != (new["m"], new["g"]):
        cand.rescore_all(cfg)
    return new
