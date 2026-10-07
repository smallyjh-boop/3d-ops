"""本地数据库（SQLite，文件在 data/app.db）。

存放：账号、操作记录；之后的订单、生产任务、库存、客服需求单也放这里。
产品资料仍然是 data/products/*.json（保持兼容）。
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time

from .config import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "app.db")
_local = threading.local()
_init_lock = threading.Lock()
_inited = False

ROLES = {
    "owner": "老板（全部权限）",
    "listing": "上架客服（上架、文案、图片、客服；看不到成本利润和设置）",
    "production": "生产打包（生产、切片、打包；看不到价格成本）",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  display_name TEXT,
  role TEXT NOT NULL,
  lang TEXT DEFAULT 'zh',
  pw_hash TEXT NOT NULL,
  active INTEGER DEFAULT 1,
  created_at REAL,
  last_login REAL
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  username TEXT,
  action TEXT,
  target TEXT,
  detail TEXT
);
CREATE INDEX IF NOT EXISTS audit_ts ON audit(ts);
CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT
);
"""


def conn():
    global _inited
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=30000")
        _local.conn = c
    if not _inited:
        with _init_lock:
            if not _inited:
                c.executescript(SCHEMA)
                cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
                if "perms" not in cols:
                    c.execute("ALTER TABLE users ADD COLUMN perms TEXT")
                if "tabs" not in cols:
                    c.execute("ALTER TABLE users ADD COLUMN tabs TEXT")   # 员工能看到哪些页面（空 = 按角色全部）
                c.commit()
                _inited = True
    return c


def release():
    """请求结束 / 后台循环每轮结束时调用：出错时没提交的写入回滚，避免一直锁住数据库。"""
    c = getattr(_local, "conn", None)
    if c is not None and c.in_transaction:
        try:
            c.rollback()
        except sqlite3.Error:
            pass


# ---------------- 密码 ----------------
def hash_pw(pw):
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt.encode(), 200_000)
    return f"pbkdf2${salt}${dk.hex()}"


def check_pw(pw, stored):
    try:
        _, salt, h = stored.split("$", 2)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", (pw or "").encode("utf-8"), salt.encode(), 200_000)
    return hmac.compare_digest(dk.hex(), h)


# ---------------- 账号 ----------------
# 员工的特别权限（老板永远全部都有）。默认值按角色给，老板可以在「账号」里给每个人单独开关。
PERMS = [
    ("files.upload", "上传 / 替换模型文件和切片文件"),
    ("files.delete", "删除切片文件"),
    ("models.change", "更换 3D 模型 / 合并摆盘 / 恢复旧版本（会让切片作废）"),
    ("models.delete", "删除 3D 模型和模型库文件"),
    ("products.delete", "删除产品"),
    ("orders.edit", "修改订单的商品和金额"),
    ("orders.cancel", "取消订单 / 标记拒收"),
    ("orders.delete", "删除订单"),
    ("materials.adjust", "耗材盘点改数 / 删除料卷"),
    ("cs.delete", "删除客服消息和会话"),
    ("inv.in", "库存：采购单、到货入库、退回入库、新建和修改物品 / 供应商"),
    ("inv.out", "库存：领用出库 / 报废 / 开盘点单填数"),
    ("inv.adjust", "库存：调整、确认盘点、作废单据"),
    ("inv.pay", "采购付款、查看财务记录"),
]
PERM_DEFAULTS = {"listing": {"files.upload": True, "orders.edit": True, "orders.cancel": True, "models.change": True, "inv.out": True},
                 "production": {"files.upload": True, "inv.out": True}}


def user_perms(role, raw=None):
    if role == "owner":
        return {k: True for k, _ in PERMS}
    out = {k: bool(PERM_DEFAULTS.get(role, {}).get(k)) for k, _ in PERMS}
    try:
        out.update({k: bool(v) for k, v in (json.loads(raw) if raw else {}).items() if k in out})
    except (ValueError, TypeError):
        pass
    return out


def _user_dict(r):
    if not r:
        return None
    keys = r.keys()
    return {"id": r["id"], "username": r["username"], "display_name": r["display_name"] or r["username"],
            "role": r["role"], "lang": r["lang"] or "zh", "active": bool(r["active"]),
            "last_login": r["last_login"], "perms": user_perms(r["role"], r["perms"] if "perms" in keys else None),
            "tabs": _tabs(r["tabs"] if "tabs" in keys else None)}


def _tabs(raw):
    try:
        v = json.loads(raw) if raw else None
    except (ValueError, TypeError):
        v = None
    return [str(x) for x in v] if isinstance(v, list) and v else None


def user_count():
    return conn().execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]


def list_users():
    return [_user_dict(r) for r in conn().execute("SELECT * FROM users ORDER BY id")]


def get_user(username=None, uid=None):
    c = conn()
    r = (c.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone() if username
         else c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    return _user_dict(r)


def create_user(username, password, role, display_name="", lang="zh"):
    username = (username or "").strip().lower()
    if not username or len(username) > 32 or not username.replace("_", "").replace(".", "").isalnum():
        raise ValueError("用户名只能用英文字母、数字、下划线，最多 32 个字符")
    if role not in ROLES:
        raise ValueError("角色不对")
    if len(password or "") < 6:
        raise ValueError("密码至少 6 位")
    c = conn()
    try:
        c.execute("INSERT INTO users(username, display_name, role, lang, pw_hash, created_at) VALUES(?,?,?,?,?,?)",
                  (username, display_name.strip() or username, role, lang if lang in ("zh", "th") else "zh",
                   hash_pw(password), time.time()))
        c.commit()
    except sqlite3.IntegrityError as e:
        raise ValueError("这个用户名已经存在") from e
    return get_user(username)


def update_user(uid, **kw):
    c = conn()
    u = get_user(uid=uid)
    if not u:
        raise ValueError("账号不存在")
    if kw.get("role") is not None and kw["role"] not in ROLES:
        raise ValueError("角色不对")
    # 至少保留一个启用的老板账号
    if u["role"] == "owner" and ((kw.get("role") or "owner") != "owner" or kw.get("active") is False):
        n = c.execute("SELECT COUNT(*) FROM users WHERE role='owner' AND active=1 AND id<>?", (uid,)).fetchone()[0]
        if n == 0:
            raise ValueError("至少要保留一个启用的老板账号")
    sets, vals = [], []
    for k in ("display_name", "role", "lang"):
        if k in kw and kw[k] is not None:
            sets.append(f"{k}=?"); vals.append(kw[k])
    if "active" in kw and kw["active"] is not None:
        sets.append("active=?"); vals.append(1 if kw["active"] else 0)
    if isinstance(kw.get("perms"), dict):
        sets.append("perms=?"); vals.append(json.dumps({k: bool(v) for k, v in kw["perms"].items() if k in dict(PERMS)}))
    if "tabs" in kw:
        t = kw["tabs"]
        sets.append("tabs=?"); vals.append(json.dumps([str(x) for x in t]) if isinstance(t, list) and t else None)
    if kw.get("password"):
        if len(kw["password"]) < 6:
            raise ValueError("密码至少 6 位")
        sets.append("pw_hash=?"); vals.append(hash_pw(kw["password"]))
    if sets:
        c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id=?", (*vals, uid))
        c.commit()
    return get_user(uid=uid)


def authenticate(username, password):
    c = conn()
    r = c.execute("SELECT * FROM users WHERE username=? AND active=1", ((username or "").strip().lower(),)).fetchone()
    if not r or not check_pw(password, r["pw_hash"]):
        time.sleep(0.5)   # 减慢暴力猜密码
        return None
    c.execute("UPDATE users SET last_login=? WHERE id=?", (time.time(), r["id"]))
    c.commit()
    return _user_dict(r)


# ---------------- 操作记录 ----------------
def audit(username, action, target="", detail=""):
    try:
        c = conn()
        c.execute("INSERT INTO audit(ts, username, action, target, detail) VALUES(?,?,?,?,?)",
                  (time.time(), username or "", action, target or "", (detail or "")[:500]))
        c.commit()
    except sqlite3.Error:
        pass


def audit_list(limit=200, username=None, target=None, q=None, days=None, hide_login=False):
    sql, args = "SELECT * FROM audit", []
    conds = []
    if username:
        conds.append("username=?"); args.append(username)
    if target:
        conds.append("target=?"); args.append(target)
    if q:
        conds.append("(action LIKE ? OR target LIKE ? OR detail LIKE ?)"); args += [f"%{q}%"] * 3
    if days:
        conds.append("ts>=?"); args.append(time.time() - float(days) * 86400)
    if hide_login:
        conds.append("action NOT IN ('登录','退出')")
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) for r in conn().execute(sql, args)]


def audit_users():
    return [r[0] for r in conn().execute("SELECT DISTINCT username FROM audit WHERE username!='' ORDER BY username")]


# ---------------- 杂项 ----------------
def secret_key():
    """Flask 会话签名密钥（第一次运行时生成，存在数据库里）。"""
    c = conn()
    r = c.execute("SELECT v FROM kv WHERE k='secret_key'").fetchone()
    if r:
        return r["v"]
    k = secrets.token_hex(32)
    c.execute("INSERT OR REPLACE INTO kv(k, v) VALUES('secret_key', ?)", (k,))
    c.commit()
    return k


def kv_get(k, default=None):
    r = conn().execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return json.loads(r["v"]) if r else default


def kv_set(k, v):
    c = conn()
    c.execute("INSERT OR REPLACE INTO kv(k, v) VALUES(?, ?)", (k, json.dumps(v, ensure_ascii=False)))
    c.commit()
