"""手机提醒（从运营分析系统 modules/alerts 搬过来）：今日待办里带「alert」的条目，按 key 去重（同一件事只推一次），
合成一条消息推到 LINE（官方账号 Messaging API）和 / 或 Telegram（用客服模块里已经设好的机器人）。推送失败下一轮再试。

设置（设置 → 运营分析）：oa_alert_on 总开关、oa_alert_every_min 几分钟检查一次、oa_line_token / oa_line_to、
oa_alert_telegram 也发到客服的 Telegram；哪些来源不推（oa_alert_muted，在「今日待办」页面勾选）。
"""
import threading
import time

from core import db, todo
from core.config import load_config, save_config

from . import line

SCHEMA = """
CREATE TABLE IF NOT EXISTS oa_alerts (
  key TEXT PRIMARY KEY, ts REAL, level TEXT, source TEXT, text TEXT, sent INTEGER DEFAULT 0, send_error TEXT, sent_at REAL
);
CREATE INDEX IF NOT EXISTS oa_alerts_ts ON oa_alerts(ts);
"""
_inited = set()
_lock = threading.Lock()


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()
    _inited.add(db.DB_PATH)


def _ensure():
    if db.DB_PATH not in _inited:
        init()


def muted(cfg=None):
    cfg = cfg or load_config()
    m = cfg.get("oa_alert_muted") or []
    return set(m if isinstance(m, list) else [x.strip() for x in str(m).split(",") if x.strip()])


def set_muted(source, on):
    m = muted()
    (m.add if on else m.discard)(str(source))
    save_config({"oa_alert_muted": sorted(m)})
    return sorted(m)


def collect(cfg=None):
    """把今日待办里要推送的、还没记过的记下来。返回新记的条数。完成 / 忽略了的不推。"""
    _ensure()
    cfg = cfg or load_config()
    mu = muted(cfg)
    c = db.conn()
    n = 0
    for it in todo.collect(None)["items"]:
        if not it["alert"] or it["source"] in mu:
            continue
        cur = c.execute("INSERT OR IGNORE INTO oa_alerts(key, ts, level, source, text, sent) VALUES(?,?,?,?,?,0)",
                        (it["key"], time.time(), it["level"], it["source"], it["alert"]))
        n += cur.rowcount
    c.execute("DELETE FROM oa_alerts WHERE ts < ?", (time.time() - 120 * 86400,))
    c.commit()
    return n


def _telegram(cfg):
    """客服模块的 Telegram 机器人（开着、填了 token 和 chat id 才用）。返回发送函数或 None。"""
    if not cfg.get("oa_alert_telegram"):
        return None
    from core import modules
    cs = modules.public("cs")
    if not cs:
        return None
    try:
        import importlib
        al = importlib.import_module(cs.__name__ + ".alerts")
        data = importlib.import_module(cs.__name__ + ".data")
        s = data.settings()
    except Exception:  # noqa: BLE001
        return None
    if not (s.get("tg_token") and s.get("tg_chat")):
        return None
    return al.send_telegram


def channels(cfg=None):
    cfg = cfg or load_config()
    out = []
    if cfg.get("oa_line_token") and cfg.get("oa_line_to"):
        out.append("line")
    if _telegram(cfg):
        out.append("telegram")
    return out


def send(text, cfg=None):
    """发到所有设好的渠道。返回 (有没有发出去, 错误说明)。"""
    cfg = cfg or load_config()
    errs, ok_any = [], False
    if cfg.get("oa_line_token") and cfg.get("oa_line_to"):
        ok, e = line.send(cfg["oa_line_token"], cfg["oa_line_to"], text)
        ok_any |= ok
        if e:
            errs.append(e)
    tg = _telegram(cfg)
    if tg:
        try:
            tg(text)
            ok_any = True
        except Exception as e:  # noqa: BLE001
            errs.append(f"Telegram：{e}")
    if not ok_any and not errs:
        errs.append("还没设置推送渠道（LINE 或客服的 Telegram）")
    return ok_any, "；".join(errs)


def flush(cfg=None):
    """把还没推出去的（2 天内的）合成一条推送。返回推出去的条数。"""
    _ensure()
    cfg = cfg or load_config()
    c = db.conn()
    pending = c.execute("SELECT * FROM oa_alerts WHERE sent=0 AND ts>=? ORDER BY ts", (time.time() - 2 * 86400,)).fetchall()
    if not pending:
        return 0
    text = "【3D 运营管理系统】\n" + "\n".join(r["text"] for r in pending[:30])
    if len(pending) > 30:
        text += f"\n……还有 {len(pending) - 30} 条，打开系统右上角 🔔 待办查看"
    ok, e = send(text, cfg)
    now = time.time()
    c.executemany("UPDATE oa_alerts SET sent=?, send_error=?, sent_at=? WHERE key=?",
                  [(1 if ok else 0, e, now if ok else None, r["key"]) for r in pending])
    c.commit()
    return len(pending) if ok else 0


def run_once(force=False):
    cfg = load_config()
    if not cfg.get("oa_alert_on") and not force:
        return {"collected": 0, "sent": 0, "off": True}
    with _lock:
        n = collect(cfg)
        s = flush(cfg)
        report = None
        try:                      # v2.48：爆款雷达每天到点推一次机会日报
            from . import radar
            report = radar.daily_report(cfg)
        except Exception as e:  # noqa: BLE001
            print("爆款雷达日报失败：", e)
    return {"collected": n, "sent": s, "radar_report": bool(report)}


def recent(limit=100):
    _ensure()
    return [dict(r) for r in db.conn().execute("SELECT * FROM oa_alerts ORDER BY ts DESC LIMIT ?", (int(limit),))]


_started = False


def _loop():
    time.sleep(60)
    while True:
        wait = 600
        try:
            cfg = load_config()
            try:
                wait = max(1.0, float(cfg.get("oa_alert_every_min") or 10)) * 60
            except (TypeError, ValueError):
                wait = 600
            from core import modules
            if modules.enabled("ops") and cfg.get("oa_alert_on"):
                run_once()
        except Exception as e:  # noqa: BLE001  下次再试
            print("运营提醒推送失败：", e)
        finally:
            db.release()
        time.sleep(wait)


def start():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="ops-alerts").start()
