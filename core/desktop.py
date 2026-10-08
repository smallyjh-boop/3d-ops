"""桌面客户端（v2.28）：每台电脑登录后自动「配对」，拿到一把只属于这台电脑、这个账号的电脑加速密钥。

· 配对：桌面端里登录网页后自动调用 POST /api/desktop/pair（带电脑编号、电脑名），
  返回电脑加速密钥（scope = worker），桌面端自己存起来，加速程序用它连 NAS。
  同一台电脑重新配对（换了账号 / 重装）会停用旧密钥。
· 每个人加速自己的：密钥记着是谁的电脑，accel 派活时先给任务发起人自己的电脑。
· 老板可以在 设置 → 组件与插件 看到所有桌面端、停用某台。

★ 对外：pair(user, device_id, device_name)  user_of_key(key_name)  devices()  revoke(device_id)  touch(key_name, info)
"""
import json
import os
import re
import threading
import time

from .config import DATA_DIR

PATH = os.path.join(DATA_DIR, "desktop_devices.json")
_lock = threading.Lock()


def _load():
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PATH + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(PATH + ".tmp", PATH)


def _clean_id(s):
    s = re.sub(r"[^A-Za-z0-9_-]", "", str(s or ""))[:40]
    if len(s) < 8:
        raise ValueError("电脑编号不对")
    return s


def key_name(username, device_id):
    return f"桌面·{str(username)[:18]}·{device_id[:8]}"


def pair(user, device_id, device_name=""):
    """登录的账号 + 这台电脑 → 新的电脑加速密钥（旧的停用）。返回 {key, worker_name}。"""
    from . import db, integrations
    device_id = _clean_id(device_id)
    username = user.get("username") or "user"
    pc = (str(device_name or "").strip() or "PC")[:24]
    with _lock:
        d = _load()
        old = d.get(device_id)
        if old and old.get("key_id"):
            c = db.conn()
            c.execute("UPDATE api_keys SET active=0 WHERE id=?", (old["key_id"],))
            c.commit()
        name = key_name(username, device_id)
        raw = integrations.create_key(name, "worker")
        r = db.conn().execute("SELECT id FROM api_keys WHERE key_hash=?", (integrations._h(raw),)).fetchone()
        d[device_id] = {"user": username, "display": user.get("display_name") or username, "pc": pc, "key_name": name,
                        "key_id": r["id"] if r else None, "paired_at": time.time(), "last": time.time(), "version": ""}
        _save(d)
    return {"key": raw, "worker_name": worker_name(user.get("display_name") or username, pc)}


def worker_name(display, pc):
    return f"{str(display)[:14]}@{pc}"[:40]


def user_of_key(name):
    """电脑加速密钥名 → 账号用户名（不是桌面端配对的密钥返回 ""：老板手动生成的「共享加速电脑」）。"""
    if not str(name or "").startswith("桌面·"):
        return ""
    for v in _load().values():
        if v.get("key_name") == name:
            return v.get("user") or ""
    return ""


def touch(name, version=""):
    with _lock:
        d = _load()
        for v in d.values():
            if v.get("key_name") == name:
                if time.time() - v.get("last", 0) > 300 or (version and v.get("version") != version):
                    v["last"] = time.time()
                    if version:
                        v["version"] = version
                    _save(d)
                return


def devices():
    out = []
    for did, v in _load().items():
        out.append({"id": did, **{k: v.get(k) for k in ("user", "display", "pc", "paired_at", "last", "version")}})
    out.sort(key=lambda x: -(x.get("last") or 0))
    return out


def revoke(device_id):
    from . import db
    with _lock:
        d = _load()
        v = d.pop(str(device_id), None)
        if not v:
            return False
        if v.get("key_id"):
            c = db.conn()
            c.execute("UPDATE api_keys SET active=0 WHERE id=?", (v["key_id"],))
            c.commit()
        _save(d)
    return True
