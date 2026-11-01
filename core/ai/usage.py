"""AI 用量和费用：每次调用记一行（任务、服务商、模型、token / 张数、估算费用（泰铢）、成功 / 出错、用时）；
按任务 / 全部的每日、每月上限（到了提醒，开了「硬上限」就不再调用）。"""
import threading
import time

from .. import db
from . import catalog as C

_lock = threading.Lock()
_ready = {"ok": False, "path": ""}

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, day TEXT NOT NULL, task TEXT, provider TEXT, model TEXT, kind TEXT,
  tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0, images INTEGER DEFAULT 0,
  cost_thb REAL DEFAULT 0, ok INTEGER DEFAULT 1, error TEXT, ms INTEGER DEFAULT 0, fallback INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ai_usage_day ON ai_usage(day);
"""


def _c():
    c = db.conn()
    if not _ready["ok"] or _ready["path"] != db.DB_PATH:
        with _lock:
            c.executescript(SCHEMA)
            c.commit()
            _ready.update(ok=True, path=db.DB_PATH)
    return c


def price(cfg, pid, model):
    own = cfg.get("ai_prices") or {}
    p = dict(C.DEFAULT_PRICES.get(pid) or {})
    p.update(own.get(pid) or {})
    p.update(own.get(f"{pid}:{model}") or {})
    return p


def cost(cfg, pid, model, tin=0, tout=0, images=0, edit=False):
    p = price(cfg, pid, model)
    img = float(p.get("edit") or p.get("img") or 0) if edit else float(p.get("img") or 0)
    return round(tin * float(p.get("in") or 0) / 1e6 + tout * float(p.get("out") or 0) / 1e6 + images * img, 4)


def log(cfg, task, pid, model, kind, tin=0, tout=0, images=0, ok=True, error="", ms=0, fallback=0, edit=False):
    c = _c()
    now = time.time()
    v = cost(cfg, pid, model, tin, tout, images, edit) if ok else 0.0
    c.execute("INSERT INTO ai_usage(ts, day, task, provider, model, kind, tokens_in, tokens_out, images, cost_thb, ok, error, ms, fallback)"
              " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (now, time.strftime("%Y-%m-%d", time.localtime(now)), task, pid, model, kind, int(tin), int(tout), int(images), v,
               1 if ok else 0, str(error or "")[:300], int(ms), int(fallback)))
    c.commit()
    return v


def spent(task=None, period="day"):
    """(费用, 次数)：今天 / 本月（task=None 全部）。"""
    day = time.strftime("%Y-%m-%d")
    where, args = ("day=?", [day]) if period == "day" else ("day LIKE ?", [day[:7] + "%"])
    if task:
        where += " AND task=?"
        args.append(task)
    r = _c().execute(f"SELECT COALESCE(SUM(cost_thb),0) s, COUNT(*) n FROM ai_usage WHERE ok=1 AND {where}", args).fetchone()
    return float(r["s"] or 0), int(r["n"] or 0)


def check(cfg, task):
    """调用前检查上限。返回 (能不能调用, 提醒文字)。"""
    tc = ((cfg.get("ai_tasks") or {}).get(task)) or {}
    lim = cfg.get("ai_limits") or {}
    name = C.TASKS.get(task, ("", task))[1]
    rules = []
    for scope, conf, label in ((task, tc, f"「{name}」"), (None, lim, "全部 AI")):
        for period, k, word in (("day", "daily_thb", "今天"), ("month", "monthly_thb", "本月")):
            try:
                cap = float(conf.get(k) or 0)
            except (TypeError, ValueError):
                cap = 0
            if cap > 0:
                rules.append((scope, period, cap, "thb", f"{label}{word}的费用已到上限 {cap:g} 铢", bool(conf.get("hard"))))
        try:
            n = int(float(conf.get("daily_calls") or 0))
        except (TypeError, ValueError):
            n = 0
        if n > 0:
            rules.append((scope, "day", n, "calls", f"{label}今天的调用次数已到上限 {n} 次", bool(conf.get("hard"))))
    warn = ""
    for scope, period, cap, unit, msg, hard in rules:
        s, n = spent(scope, period)
        if (s if unit == "thb" else n) >= cap:
            if hard:
                return False, msg + "（设置了硬上限，暂停调用；在「AI 接口」页可以改）"
            warn = warn or msg
    return True, warn


def stats(days=30, task="", provider=""):
    """用量页：数字卡片、按天、按任务、按服务商、明细。"""
    c = _c()
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - (max(1, int(days)) - 1) * 86400))
    where, args = ["day>=?"], [since]
    if task:
        where.append("task=?")
        args.append(task)
    if provider:
        where.append("provider=?")
        args.append(provider)
    w = " AND ".join(where)
    tot = c.execute(f"SELECT COUNT(*) n, COALESCE(SUM(ok),0) ok, COALESCE(SUM(cost_thb),0) cost, COALESCE(SUM(tokens_in),0) tin, "
                    f"COALESCE(SUM(tokens_out),0) tout, COALESCE(SUM(images),0) img, COALESCE(AVG(ms),0) ms, COALESCE(SUM(fallback),0) fb "
                    f"FROM ai_usage WHERE {w}", args).fetchone()
    by_day = [dict(r) for r in c.execute(f"SELECT day, COUNT(*) n, COALESCE(SUM(cost_thb),0) cost FROM ai_usage WHERE {w} GROUP BY day ORDER BY day", args)]
    by_task = [dict(r) for r in c.execute(f"SELECT task, COUNT(*) n, SUM(1-ok) err, COALESCE(SUM(cost_thb),0) cost FROM ai_usage WHERE {w} GROUP BY task ORDER BY cost DESC, n DESC", args)]
    by_prov = [dict(r) for r in c.execute(f"SELECT provider, model, COUNT(*) n, SUM(1-ok) err, COALESCE(SUM(cost_thb),0) cost, COALESCE(SUM(tokens_in),0) tin, "
                                          f"COALESCE(SUM(tokens_out),0) tout, COALESCE(SUM(images),0) img, COALESCE(AVG(ms),0) ms "
                                          f"FROM ai_usage WHERE {w} GROUP BY provider, model ORDER BY cost DESC, n DESC", args)]
    recent = [dict(r) for r in c.execute(f"SELECT * FROM ai_usage WHERE {w} ORDER BY id DESC LIMIT 200", args)]
    today, today_n = spent(None, "day")
    month, month_n = spent(None, "month")
    # 补齐没有调用的日子（图表连续）
    have = {r["day"]: r for r in by_day}
    full = []
    for i in range(int(days) - 1, -1, -1):
        d = time.strftime("%Y-%m-%d", time.localtime(time.time() - i * 86400))
        full.append(have.get(d) or {"day": d, "n": 0, "cost": 0})
    return {"total": dict(tot), "today": {"cost": today, "n": today_n}, "month": {"cost": month, "n": month_n},
            "by_day": full, "by_task": by_task, "by_provider": by_prov, "recent": recent}


def max_id():
    r = _c().execute("SELECT COALESCE(MAX(id),0) m FROM ai_usage").fetchone()
    return int(r["m"] or 0)


def cost_since(mark, tasks=()):
    """某个时间点之后这些任务实际花了多少（泰铢）——批量 / 一次生成结束后显示「实际费用」。"""
    q = "SELECT COALESCE(SUM(cost_thb),0) s FROM ai_usage WHERE id>? AND ok=1"
    args = [int(mark)]
    if tasks:
        q += f" AND task IN ({','.join('?' * len(tasks))})"
        args += list(tasks)
    return float(_c().execute(q, args).fetchone()["s"] or 0)
