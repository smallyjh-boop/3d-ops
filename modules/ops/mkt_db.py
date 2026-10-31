"""运营分析第二期（系统 v2.48.0）的数据表：竞品、爆款雷达、竞店、计划、营销日历、店铺后台数据。

表名都以 ops_ 开头（ERP 里已经有一张 shops 表是「店铺对接」的，不能重名）。
列名和原来单独的「运营分析系统」（analytics.db）一样，第三期可以直接按下面的对应关系导入旧数据：
  competitors → ops_comp            comp_links → ops_comp_links       comp_snaps → ops_comp_snaps    comp_events → ops_comp_events
  radar_keywords → ops_radar_keywords（多了 source、product_id 两列：从产品搜索词导入的关键词）
  radar_searches → ops_radar_searches  radar_items → ops_radar_items   radar_item_snaps → ops_radar_item_snaps
  radar_volumes → ops_radar_volumes    radar_patrol_log → ops_patrol_log
  shops → ops_shops（多了 erp_shop 列：对上 ERP 订单里的店铺名）  shop_snaps → ops_shop_snaps  shop_items → ops_shop_items
  shop_item_snaps → ops_shop_item_snaps  shop_comp_links → ops_shop_comp_links
  plans → ops_plans    plan_tasks → ops_plan_tasks（多了 text_th 列）    campaigns → ops_campaigns
  backend_pages → ops_backend_pages    backend_rows → ops_backend_rows
"""
from core import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS ops_comp (
  id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT, url TEXT, item_key TEXT, title TEXT, shop TEXT, note TEXT,
  status TEXT DEFAULT 'active', radar_status TEXT DEFAULT 'new', listed_on TEXT,
  est_grams REAL, est_hours REAL, est_material TEXT, est_unit_cost REAL, cost_source TEXT, cost_note TEXT,
  fee_rate_override REAL, created_at REAL, updated_at REAL, image TEXT
);
CREATE INDEX IF NOT EXISTS ops_comp_key ON ops_comp(item_key);
CREATE TABLE IF NOT EXISTS ops_comp_links (comp_id INTEGER, sku TEXT, PRIMARY KEY (comp_id, sku));
CREATE TABLE IF NOT EXISTS ops_comp_snaps (
  id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, ts REAL, price REAL, list_price REAL, voucher REAL,
  sold_total REAL, sold_text TEXT, sold_30d REAL, rating REAL, reviews REAL, free_ship INTEGER, title TEXT, source TEXT
);
CREATE INDEX IF NOT EXISTS ops_comp_snaps_c ON ops_comp_snaps(comp_id, ts);
CREATE TABLE IF NOT EXISTS ops_comp_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, comp_id INTEGER, ts REAL, kind TEXT, text TEXT, text_th TEXT
);
CREATE INDEX IF NOT EXISTS ops_comp_events_ts ON ops_comp_events(ts);

CREATE TABLE IF NOT EXISTS ops_radar_keywords (
  id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT, keyword TEXT, note TEXT, active INTEGER DEFAULT 1,
  status TEXT DEFAULT 'new', created_at REAL, last_patrol REAL, ai TEXT, ai_ts REAL, source TEXT, product_id TEXT,
  UNIQUE (platform, keyword)
);
CREATE TABLE IF NOT EXISTS ops_radar_searches (
  id INTEGER PRIMARY KEY AUTOINCREMENT, keyword_id INTEGER, ts REAL, url TEXT, total_results REAL, total_text TEXT,
  n_cards INTEGER, price_median REAL, sold_top10 REAL, top3_share REAL
);
CREATE INDEX IF NOT EXISTS ops_radar_searches_k ON ops_radar_searches(keyword_id, ts);
CREATE TABLE IF NOT EXISTS ops_radar_items (
  item_key TEXT PRIMARY KEY, platform TEXT, url TEXT, title TEXT, keyword_id INTEGER, best_rank INTEGER,
  first_seen REAL, last_seen REAL, image TEXT
);
CREATE TABLE IF NOT EXISTS ops_radar_item_snaps (
  item_key TEXT, ts REAL, keyword_id INTEGER, rank INTEGER, price REAL, sold_total REAL, sold_text TEXT
);
CREATE INDEX IF NOT EXISTS ops_radar_item_snaps_k ON ops_radar_item_snaps(item_key, ts);
CREATE TABLE IF NOT EXISTS ops_radar_volumes (
  platform TEXT, keyword TEXT, ts REAL, volume REAL, bid REAL, period_text TEXT
);
CREATE TABLE IF NOT EXISTS ops_patrol_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, day TEXT, kind TEXT, url TEXT, ok INTEGER, note TEXT, who TEXT
);
CREATE INDEX IF NOT EXISTS ops_patrol_log_day ON ops_patrol_log(day);

CREATE TABLE IF NOT EXISTS ops_shops (
  id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT, shop_key TEXT UNIQUE, name TEXT, url TEXT, logo TEXT,
  is_mine INTEGER DEFAULT 0, watch INTEGER DEFAULT 0, note TEXT, created_at REAL, last_capture REAL, erp_shop TEXT
);
CREATE TABLE IF NOT EXISTS ops_shop_snaps (
  id INTEGER PRIMARY KEY AUTOINCREMENT, shop_id INTEGER, ts REAL, followers REAL, positive_pct REAL, rating REAL, reviews REAL,
  products REAL, response_rate REAL, response_time TEXT, ship_on_time REAL, joined_text TEXT, main_category TEXT, how TEXT
);
CREATE INDEX IF NOT EXISTS ops_shop_snaps_s ON ops_shop_snaps(shop_id, ts);
CREATE TABLE IF NOT EXISTS ops_shop_items (
  shop_id INTEGER, item_key TEXT, url TEXT, title TEXT, image TEXT, first_seen REAL, last_seen REAL,
  PRIMARY KEY (shop_id, item_key)
);
CREATE TABLE IF NOT EXISTS ops_shop_item_snaps (
  shop_id INTEGER, item_key TEXT, ts REAL, price REAL, sold_total REAL, sold_text TEXT
);
CREATE INDEX IF NOT EXISTS ops_shop_item_snaps_k ON ops_shop_item_snaps(shop_id, item_key, ts);
CREATE TABLE IF NOT EXISTS ops_shop_comp_links (shop_id INTEGER, comp_id INTEGER, PRIMARY KEY (shop_id, comp_id));

CREATE TABLE IF NOT EXISTS ops_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT, platform TEXT, kind TEXT, status TEXT DEFAULT 'active',
  start_day TEXT, days INTEGER, baseline_daily REAL, benchmark_daily REAL, target_daily REAL, unit_price REAL,
  ai_note TEXT, ai_at REAL, result TEXT, created_at REAL, closed_at REAL
);
CREATE TABLE IF NOT EXISTS ops_plan_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER, offset INTEGER, phase TEXT, text TEXT, source TEXT, done_at REAL, text_th TEXT
);
CREATE INDEX IF NOT EXISTS ops_plan_tasks_p ON ops_plan_tasks(plan_id);

CREATE TABLE IF NOT EXISTS ops_campaigns (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, platforms TEXT, start_day TEXT, end_day TEXT,
  multiplier REAL, note TEXT, hidden_key TEXT, created_at REAL
);

CREATE TABLE IF NOT EXISTS ops_backend_pages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, platform TEXT, url TEXT, title TEXT, kind TEXT, period_text TEXT, n_rows INTEGER, how TEXT
);
CREATE TABLE IF NOT EXISTS ops_backend_rows (
  id INTEGER PRIMARY KEY AUTOINCREMENT, page_id INTEGER, ts REAL, platform TEXT, period_text TEXT, period_days REAL,
  sku TEXT, seller_sku TEXT, item_id TEXT, name TEXT, impressions REAL, visitors REAL, views REAL, add_to_cart REAL,
  orders REAL, units REAL, revenue REAL, conversion REAL
);
CREATE INDEX IF NOT EXISTS ops_backend_rows_sku ON ops_backend_rows(sku, platform, ts);
"""
_inited = set()


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()
    _inited.add(db.DB_PATH)


def ensure():
    if db.DB_PATH not in _inited:
        init()


def conn():
    ensure()
    return db.conn()
