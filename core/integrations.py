"""对外接口与店铺对接。

1) API 密钥：给外部程序（以后的店铺对接服务、BigSeller 自动化、自己写的脚本）用，
   请求头带 `Authorization: Bearer <密钥>` 或 `X-API-Key: <密钥>` 调用 /api/v1/...。
   密钥只在创建时显示一次，数据库里只存哈希。
2) 店铺：每个平台店铺一条记录（授权信息 + 同步间隔），后台线程定时拉订单（连接器接通的平台）。
3) 推送日志：平台主动推送到 /api/v1/webhook/<平台> 的内容都会记下来，方便联调。
"""
import hashlib
import json
import secrets
import threading
import time
import traceback

from . import connectors, db

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, prefix TEXT, key_hash TEXT UNIQUE,
  active INTEGER DEFAULT 1, created_at REAL, last_used REAL, uses INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS shops (
  id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT, name TEXT, enabled INTEGER DEFAULT 0,
  creds TEXT, interval_min INTEGER DEFAULT 15, cursor REAL, last_sync REAL, last_ok REAL, last_error TEXT,
  created_at REAL
);
CREATE TABLE IF NOT EXISTS sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, shop_id INTEGER, source TEXT, ok INTEGER,
  orders_new INTEGER, orders_updated INTEGER, message TEXT
);
CREATE INDEX IF NOT EXISTS sync_log_ts ON sync_log(ts);
CREATE TABLE IF NOT EXISTS webhook_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, platform TEXT, shop_id INTEGER, headers TEXT, body TEXT,
  result TEXT
);
"""
FIRST_SYNC_DAYS = 7          # 第一次同步往回拉几天
OVERLAP_S = 600              # 每次多往回拉 10 分钟，防止漏单


SCOPES = {"full": "完整（可推送订单）", "read": "只读（只能查询，看不到买家个人信息）",
          "ops": "运营写回（只能改标题、属性、售价、上下架）",
          "catalog": "建产品（3D选品工具用：只能新建产品草稿、查类目）",
          "finance": "财务（财务模块用：只能读采购付款、库存消耗等财务数据）",
          "worker": "电脑加速（装在电脑上的加速程序用：只能领切片 / 读模型 / 抠图的活）",
          "wholesale": "批发站（只能读商品售价和库存、推送和查询批发站自己的订单，看不到成本）",
          "chat": "AI 接待（系统一 ai-sales-desk 用：只能读售价和库存、推送和查询聊天成交的订单，看不到成本）"}


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(api_keys)")}
    if "scope" not in cols:   # v2.9.1：只读密钥（给运营分析系统等外部程序用）
        c.execute("ALTER TABLE api_keys ADD COLUMN scope TEXT DEFAULT 'full'")
    c.commit()


# ---------------- API 密钥 ----------------
def _h(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def create_key(name, scope="full"):
    raw = "lh_" + secrets.token_urlsafe(30)
    scope = scope if scope in SCOPES else "full"
    c = db.conn()
    c.execute("INSERT INTO api_keys(name, prefix, key_hash, created_at, scope) VALUES(?,?,?,?,?)",
              ((name or "API").strip()[:40], raw[:9], _h(raw), time.time(), scope))
    c.commit()
    return raw


def check_key(raw):
    if not raw or not raw.startswith("lh_"):
        return None
    c = db.conn()
    r = c.execute("SELECT * FROM api_keys WHERE key_hash=? AND active=1", (_h(raw),)).fetchone()
    if r:
        c.execute("UPDATE api_keys SET last_used=?, uses=uses+1 WHERE id=?", (time.time(), r["id"]))
        c.commit()
    return dict(r) if r else None


EXT_LATEST = "2.9.1"     # 当前随系统发的浏览器扩展版本（extension/manifest.json）
EXT_SEEN = {}            # 密钥名 → 最近一次用扩展时的扩展版本（旧扩展不带版本号，记 "旧版"）


def note_ext(name, version):
    EXT_SEEN[name] = version or "旧版"


def list_keys():
    out = [dict(r) for r in db.conn().execute("SELECT id, name, prefix, active, created_at, last_used, uses, COALESCE(scope, 'full') AS scope FROM api_keys ORDER BY id")]
    for k in out:
        k["ext_version"] = EXT_SEEN.get(k["name"], "")
    return out


def set_key_active(kid, active):
    c = db.conn()
    c.execute("UPDATE api_keys SET active=? WHERE id=?", (1 if active else 0, kid))
    c.commit()


def delete_key(kid):
    c = db.conn()
    c.execute("DELETE FROM api_keys WHERE id=?", (kid,))
    c.commit()


# ---------------- 店铺 ----------------
def _secret_keys(platform):
    cls = connectors.REGISTRY.get(platform)
    return {k for k, _l, sec in (cls.FIELDS if cls else []) if sec} | {"access_token", "refresh_token"}


def _shop_out(r):
    d = dict(r)
    creds = json.loads(d.pop("creds") or "{}")
    sk = _secret_keys(d["platform"])
    d["creds"] = {k: ("******" if k in sk and v else v) for k, v in creds.items()
                  if k not in ("token_expire", "refresh_expire")}
    d["token_expire"] = creds.get("token_expire")
    cls = connectors.REGISTRY.get(d["platform"])
    d["ready"] = bool(cls and cls.READY)
    return d


def list_shops():
    return [_shop_out(r) for r in db.conn().execute("SELECT * FROM shops ORDER BY id")]


def get_shop_raw(sid):
    r = db.conn().execute("SELECT * FROM shops WHERE id=?", (sid,)).fetchone()
    if not r:
        raise ValueError("店铺不存在")
    d = dict(r)
    d["creds"] = json.loads(d["creds"] or "{}")
    return d


def save_shop(data):
    """新建或修改店铺。授权信息里填 ****** 表示不改。"""
    platform = data.get("platform")
    if platform not in connectors.REGISTRY:
        raise ValueError("请选择平台")
    c = db.conn()
    sid = data.get("id")
    old = get_shop_raw(sid)["creds"] if sid else {}
    creds = dict(old)
    for k, v in (data.get("creds") or {}).items():
        if v == "******":
            continue
        creds[k] = str(v).strip()
    vals = (platform, (data.get("name") or connectors.REGISTRY[platform].LABEL).strip()[:40],
            1 if data.get("enabled") else 0, json.dumps(creds), max(5, int(data.get("interval_min") or 15)))
    if sid:
        c.execute("UPDATE shops SET platform=?, name=?, enabled=?, creds=?, interval_min=? WHERE id=?", (*vals, sid))
    else:
        sid = c.execute("INSERT INTO shops(platform, name, enabled, creds, interval_min, created_at) VALUES(?,?,?,?,?,?)",
                        (*vals, time.time())).lastrowid
    c.commit()
    return sid


def delete_shop(sid):
    c = db.conn()
    c.execute("DELETE FROM shops WHERE id=?", (sid,))
    c.commit()


def _store_creds(sid, conn):
    if conn.creds_changed:
        c = db.conn()
        c.execute("UPDATE shops SET creds=? WHERE id=?", (json.dumps(conn.creds), sid))
        c.commit()
        conn.creds_changed = False


def authorize_url(sid, redirect_uri):
    s = get_shop_raw(sid)
    conn = connectors.make(s["platform"], s["creds"])
    if not hasattr(conn, "authorize_url"):
        raise ValueError("这个平台还不支持在线授权")
    return conn.authorize_url(redirect_uri)


def exchange_code(sid, code):
    s = get_shop_raw(sid)
    conn = connectors.make(s["platform"], s["creds"])
    if not hasattr(conn, "exchange_code"):
        raise ValueError("这个平台还不支持在线授权")
    conn.exchange_code(code.strip())
    _store_creds(sid, conn)


# ---------------- 同步 ----------------
_sync_lock = threading.Lock()


def log_sync(source, ok, stats=None, message="", shop_id=None):
    c = db.conn()
    c.execute("INSERT INTO sync_log(ts, shop_id, source, ok, orders_new, orders_updated, message) VALUES(?,?,?,?,?,?,?)",
              (time.time(), shop_id, source, 1 if ok else 0, (stats or {}).get("orders_new", 0),
               (stats or {}).get("orders_updated", 0), (message or "")[:1000]))
    c.execute("DELETE FROM sync_log WHERE id < (SELECT MAX(id) - 2000 FROM sync_log)")
    c.commit()


def sync_log(limit=100):
    return [dict(r) for r in db.conn().execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (int(limit),))]


def ingest(orders, source, default_platform="", user="", shop_id=None):
    """所有自动导入的入口：写订单 → 生成生产任务 → 记日志。"""
    from . import orders as orders_mod, production
    stats = orders_mod.upsert(orders, source=source, default_platform=default_platform, user=user)
    from . import chain
    stats["jobs"] = chain.order_changed(user or source)
    msg = "；".join(stats.get("errors") or [])
    if stats["unmatched"]:
        msg = (msg + "；" if msg else "") + "没对上的 SKU：" + ", ".join(u["sku"] for u in stats["unmatched"][:20])
    log_sync(source, not stats.get("errors"), stats, msg, shop_id)
    return stats


def sync_shop(sid, full=False):
    with _sync_lock:
        s = get_shop_raw(sid)
        c = db.conn()
        now = time.time()
        since = (s["cursor"] or 0) - OVERLAP_S if s["cursor"] and not full else now - FIRST_SYNC_DAYS * 86400
        conn = connectors.make(s["platform"], s["creds"])
        try:
            orders = conn.fetch_orders(since, now)
            for o in orders:
                o.setdefault("shop", s["name"])
            stats = ingest(orders, f"{s['platform']}:{s['name']}", s["platform"], shop_id=sid)
            c.execute("UPDATE shops SET cursor=?, last_sync=?, last_ok=?, last_error='' WHERE id=?", (now, now, now, sid))
            c.commit()
            return stats
        except Exception as e:  # 记录错误，下次再试
            import requests
            if isinstance(e, connectors.NotReady):
                msg = str(e)
            elif isinstance(e, requests.exceptions.RequestException):
                msg = f"连不上 {s['platform']} 的服务器（网络问题或被防火墙挡住），稍后会自动重试"
            else:
                msg = f"{type(e).__name__}: {e}"
            c.execute("UPDATE shops SET last_sync=?, last_error=? WHERE id=?", (now, msg[:500], sid))
            c.commit()
            log_sync(f"{s['platform']}:{s['name']}", False, None, msg, sid)
            raise RuntimeError(msg) from e
        finally:
            _store_creds(sid, conn)


def _loop():
    while True:
        time.sleep(60)
        try:
            now = time.time()
            for r in db.conn().execute("SELECT id, platform, interval_min, last_sync FROM shops WHERE enabled=1").fetchall():
                cls = connectors.REGISTRY.get(r["platform"])
                if not cls or not cls.READY:
                    continue
                if (r["last_sync"] or 0) + (r["interval_min"] or 15) * 60 <= now:
                    try:
                        sync_shop(r["id"])
                    except Exception:   # 已记录到店铺的 last_error
                        pass
        except Exception:
            traceback.print_exc()
        finally:
            db.release()


_started = False


def start_scheduler():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True, name="shop-sync").start()


# ---------------- 推送 ----------------
def webhook(platform, headers, body, url):
    """平台推送：先记日志；找到这个平台已启用的店铺，交给连接器解析。"""
    c = db.conn()
    hid = c.execute("INSERT INTO webhook_log(ts, platform, headers, body, result) VALUES(?,?,?,?,?)",
                    (time.time(), platform, json.dumps(dict(headers))[:4000], body[:20000].decode("utf-8", "replace"),
                     "")).lastrowid
    c.execute("DELETE FROM webhook_log WHERE id < ?", (hid - 1000,))
    c.commit()
    result = "已记录（没有启用的店铺）"
    for r in c.execute("SELECT id FROM shops WHERE platform=? AND enabled=1", (platform,)).fetchall():
        s = get_shop_raw(r["id"])
        conn = connectors.make(platform, s["creds"])
        try:
            orders = conn.handle_webhook(headers, body, url)
            _store_creds(s["id"], conn)
            if orders:
                for o in orders:
                    o.setdefault("shop", s["name"])
                st = ingest(orders, f"{platform}:{s['name']}（推送）", platform, shop_id=s["id"])
                result = f"新 {st['orders_new']}，更新 {st['orders_updated']}"
            else:
                result = "已记录（不需要处理）"
            break
        except PermissionError as e:
            result = f"签名不对：{e}"
        except Exception as e:  # 记下来，平台会重试
            result = f"{type(e).__name__}: {e}"
    c.execute("UPDATE webhook_log SET result=? WHERE id=?", (result[:500], hid))
    c.commit()
    return result


def webhook_log(limit=50):
    return [dict(r) for r in db.conn().execute("SELECT id, ts, platform, result, substr(body,1,300) AS body FROM webhook_log "
                                               "ORDER BY id DESC LIMIT ?", (int(limit),))]
