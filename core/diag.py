"""运行日志与诊断包（v2.14.1）：测试和日常使用时出了问题，能看到发生了什么，一键打包发给开发者。

- 程序出错（后端异常）和页面出错（浏览器里的 JavaScript 错误）都记到 data/logs/app.log（自动轮换，最多约 6MB）。
- 「系统检查与升级」页能看最近的错误，并下载诊断包（日志 + 版本 + 系统检查结果 + 去掉密钥的设置）。
"""
import io
import json
import logging
import os
import re
import time
import zipfile
from logging.handlers import RotatingFileHandler

from .config import DATA_DIR

LOG_DIR = os.path.join(DATA_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "app.log")
_LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (\w+) (.*)$")
log = logging.getLogger("3dops")
_client_seen = {}


def setup(app=None):
    """把日志写到文件。重复调用不会重复加 handler。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    if not any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        h = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
        log.propagate = False
    if app is not None:
        for hh in log.handlers:
            if hh not in app.logger.handlers:
                app.logger.addHandler(hh)
    return log


def server_error(e, method="", path="", user=""):
    import traceback
    tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))[-4000:]
    log.error("后端出错 %s %s 用户=%s：%s\n%s", method, path, user or "-", e, tb)


def client_error(d, user="", ua=""):
    """浏览器里的错误：同一条错误 10 分钟内只记一次，避免刷屏。"""
    msg = str(d.get("msg") or "")[:500]
    key = (msg, str(d.get("src") or "")[-80:], d.get("line"))
    now = time.time()
    if now - _client_seen.get(key, 0) < 600:
        return False
    _client_seen[key] = now
    if len(_client_seen) > 500:
        _client_seen.clear()
    log.warning("页面出错 用户=%s 版本=%s 页面=%s 位置=%s:%s：%s\n%s\n浏览器=%s", user or "-", str(d.get("ver") or "")[:20],
                str(d.get("url") or "")[:200], str(d.get("src") or "")[-120:], d.get("line"), msg,
                str(d.get("stack") or "")[:2000], ua[:200])
    return True


def note(msg, *args):
    log.info(msg, *args)


def recent(n=50, levels=("ERROR", "WARNING")):
    """最近的错误（新的在前）。多行的记录合成一条。"""
    files = [LOG_PATH] + [f"{LOG_PATH}.{i}" for i in range(1, 6)]
    out = []
    for fp in files:
        if not os.path.exists(fp):
            continue
        with open(fp, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
        recs, cur = [], None
        for ln in lines:
            m = _LINE.match(ln)
            if m:
                cur = {"time": m.group(1), "level": m.group(2), "text": m.group(3), "detail": ""}
                recs.append(cur)
            elif cur is not None:
                cur["detail"] += ln + "\n"
        out.extend(r for r in reversed(recs) if r["level"] in levels)
        if len(out) >= n:
            break
    for r in out:
        r["detail"] = r["detail"][-3000:]
    return out[:n]


def bundle(version, check_items, cfg, secret_keys):
    """诊断包：日志、版本、系统检查结果、设置（去掉密钥、打印机访问码）。不含订单、买家资料。"""
    safe = {}
    for k, v in (cfg or {}).items():
        if k in secret_keys or any(t in k.lower() for t in ("key", "secret", "token", "password")):
            safe[k] = "***" if v else ""
        elif k == "printers":
            safe[k] = [{kk: ("***" if kk in ("access_code", "password", "token") and vv else vv) for kk, vv in (p or {}).items()} for p in (v or [])]
        else:
            safe[k] = v
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("info.json", json.dumps({"version": version, "time": time.strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False, indent=2))
        z.writestr("system_check.json", json.dumps(check_items, ensure_ascii=False, indent=2, default=str))
        z.writestr("config_no_secrets.json", json.dumps(safe, ensure_ascii=False, indent=2, default=str))
        for fp in [LOG_PATH] + [f"{LOG_PATH}.{i}" for i in range(1, 6)]:
            if os.path.exists(fp):
                z.write(fp, "logs/" + os.path.basename(fp))
    return buf.getvalue()
