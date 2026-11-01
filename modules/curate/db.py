"""选品模块的数据表（cur_ 开头，在 ERP 的 app.db 里）。选品只管「找模型」：采用以后就是 ERP 的产品草稿（产品库、编辑页、模型库、上架检查都是 ERP 的）。

  cur_candidates  候选池：模型网站列表页上看到的卡片（扩展读出来的标题、图、热度数字）+ 打分（规则 + AI）；采用后 product_id = 产品编号
  cur_collect     采集队列：采用的模型等扩展读详情页（图片、描述、许可证、文件链接），读到后补进产品草稿
  cur_files       模型文件下载队列：扩展用浏览器里原站的登录状态下载，上传后直接放进产品的模型库（source_files）
  cur_watches     关注巡逻（设计师 / 关键词 / 搜索链接）；cur_watch_log 每次巡逻的记录
  cur_settings    运行状态（每个平台的节奏 / 暂停、估算校准系数……）；用户能改的设置在 ERP 设置里（config）
"""
import json
import time

from core import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS cur_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT, skey TEXT UNIQUE, platform TEXT DEFAULT '', url TEXT, title TEXT DEFAULT '', thumb TEXT DEFAULT '',
  author TEXT DEFAULT '', metrics TEXT DEFAULT '{}', ai TEXT DEFAULT '', ai_at REAL DEFAULT 0, ai_error TEXT DEFAULT '',
  score REAL DEFAULT 0, parts TEXT DEFAULT '{}', excluded TEXT DEFAULT '', category TEXT DEFAULT '', real TEXT DEFAULT '',
  watch_id INTEGER DEFAULT 0, new_at REAL DEFAULT 0, status TEXT DEFAULT '', product_id TEXT DEFAULT '', adopted_by TEXT DEFAULT '',
  adopted_at REAL DEFAULT 0, seen_by TEXT DEFAULT '', first_seen REAL DEFAULT 0, last_seen REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS cur_cand_score ON cur_candidates(score DESC, last_seen DESC);
CREATE INDEX IF NOT EXISTS cur_cand_new ON cur_candidates(new_at);
CREATE TABLE IF NOT EXISTS cur_collect (
  id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT, skey TEXT DEFAULT '', title TEXT DEFAULT '', thumb TEXT DEFAULT '', who TEXT DEFAULT '',
  product_id TEXT DEFAULT '', pos REAL DEFAULT 0, state TEXT DEFAULT 'waiting', message TEXT DEFAULT '', tries INTEGER DEFAULT 0, post INTEGER DEFAULT 0,
  created_at REAL DEFAULT 0, updated_at REAL DEFAULT 0, started_at REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS cur_collect_s ON cur_collect(state, pos);
CREATE TABLE IF NOT EXISTS cur_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT DEFAULT '', platform TEXT DEFAULT '', name TEXT DEFAULT '', url TEXT DEFAULT '',
  size_text TEXT DEFAULT '', kind TEXT DEFAULT '', folder TEXT DEFAULT '', state TEXT DEFAULT '', stored TEXT DEFAULT '', bytes INTEGER DEFAULT 0,
  error TEXT DEFAULT '', tries INTEGER DEFAULT 0, created_at REAL DEFAULT 0, updated_at REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS cur_files_p ON cur_files(product_id);
CREATE INDEX IF NOT EXISTS cur_files_s ON cur_files(state);
CREATE TABLE IF NOT EXISTS cur_watches (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT DEFAULT 'url', platform TEXT DEFAULT '', value TEXT DEFAULT '', url TEXT UNIQUE,
  label TEXT DEFAULT '', freq_hours INTEGER DEFAULT 24, scrolls INTEGER DEFAULT 1, enabled INTEGER DEFAULT 1, source TEXT DEFAULT 'manual',
  runs INTEGER DEFAULT 0, last_run REAL DEFAULT 0, next_run REAL DEFAULT 0, running_at REAL DEFAULT 0, last_found INTEGER DEFAULT 0,
  last_new INTEGER DEFAULT 0, total_new INTEGER DEFAULT 0, last_error TEXT DEFAULT '', created_by TEXT DEFAULT '', created_at REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS cur_watch_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, watch_id INTEGER, platform TEXT DEFAULT '', found INTEGER DEFAULT 0, new INTEGER DEFAULT 0,
  error TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS cur_watch_log_p ON cur_watch_log(platform, ts);
CREATE TABLE IF NOT EXISTS cur_settings (k TEXT PRIMARY KEY, v TEXT);
"""
TABLES = ("cur_candidates", "cur_collect", "cur_files", "cur_watches", "cur_watch_log", "cur_settings")
_inited = set()


# 后加的字段（v2.50.1）：(表, 字段, 定义)
COLUMNS = [("cur_candidates", "capture_bad", "TEXT DEFAULT ''"),      # 「采集可能出错」的原因（标题 = 作者名、缩略图是头像……）：不交给 AI
           ("cur_candidates", "refresh_at", "REAL DEFAULT 0"),         # 排队重新从详情页读的时间
           ("cur_collect", "copy", "INTEGER DEFAULT 0"),               # 0 = 采用后要写 AI 文案；1 = 写过了 / 不用写
           ("cur_collect", "kind", "TEXT DEFAULT ''"),                 # '' = 采用的产品草稿；refresh = 只重新读候选的标题 / 图（不建产品）
           # v2.51.x（扩展 3.1.2）：采集队列管理 + 两条线并行
           ("cur_collect", "prio", "INTEGER DEFAULT 0"),               # 优先级 1 高 / 0 普通 / -1 低（扩展领活：优先级 → pos → id）
           ("cur_collect", "held", "INTEGER DEFAULT 0"),               # 1 = 这个任务手动暂停
           ("cur_collect", "hidden", "INTEGER DEFAULT 0"),             # 1 = 从队列里拿掉了（删除 / 清理 / 产品已删除；这一行还留着文案 / 整理标记）
           ("cur_files", "prio", "INTEGER DEFAULT 0"),
           ("cur_files", "held", "INTEGER DEFAULT 0"),
           ("cur_files", "pos", "REAL DEFAULT 0"),                     # 0 = 按 id（先来后到）
           ("cur_files", "got", "INTEGER DEFAULT 0"),                  # 下载进度（字节）
           ("cur_files", "total", "INTEGER DEFAULT 0"),
           ("cur_files", "started_at", "REAL DEFAULT 0"),
           ("cur_files", "beat", "REAL DEFAULT 0")]                    # 扩展最后一次报进度的时间（3 分钟没进度 = 卡住，放回队列）


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    for t, col, ddl in COLUMNS:
        have = {r[1] for r in c.execute(f"PRAGMA table_info({t})")}
        if col not in have:
            c.execute(f"ALTER TABLE {t} ADD COLUMN {col} {ddl}")
    c.commit()
    _inited.add(db.DB_PATH)


def conn():
    if db.DB_PATH not in _inited:
        init()
    return db.conn()


def get(k, default=None):
    r = conn().execute("SELECT v FROM cur_settings WHERE k=?", (k,)).fetchone()
    if not r:
        return default
    try:
        return json.loads(r["v"])
    except ValueError:
        return default


def put(k, v):
    c = conn()
    c.execute("INSERT OR REPLACE INTO cur_settings(k, v) VALUES(?,?)", (k, json.dumps(v, ensure_ascii=False)))
    c.commit()


def jl(s, d=None):
    """读 JSON 字段（坏了 / 空的给默认值）。"""
    if not s:
        return {} if d is None else d
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return {} if d is None else d


def now():
    return time.time()


def day_start(ts=None):
    """泰国时间今天 0 点（「今日新品」和每天上限都按泰国时间算）。"""
    t = ts or time.time()
    return t - ((t + 7 * 3600) % 86400)
