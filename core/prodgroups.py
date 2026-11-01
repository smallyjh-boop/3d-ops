"""产品库 / 采集箱的自动分组（v2.53）共用的东西：手动标记、自定义标签、保存的视图、阈值设置、旧分组迁移。

自动分组本身（进度、待处理、销售表现、类目 / 来源）由 modules/goods/groups.py 和 modules/curate/inbox.py 按产品资料现算，不存。
这里只存人手动做的：
  产品里 p["marks"] = {"upload": {"note", "at", "by"}, "edit": {...}, "into": {...}, "later": {...}}
      upload 要上传 · edit 要修改（产品库）；into 要转入 · later 再看看（采集箱）
  产品里 p["groups"] = [标签编号]    旧的「分组」就是现在的自定义标签（product_groups 表，和采集箱的文件夹是同一套）
  表 goods_views：保存的视图（scope = goods / inbox / cand），state = 当时选的分组 / 搜索 / 下拉筛选
"""
import json
import time

from . import db, store

MARKS = {"goods": ("upload", "edit"), "inbox": ("into", "later"), "wb": ("list", "price", "img")}
MARK_ZH = {"upload": "要上传", "edit": "要修改", "into": "要转入", "later": "再看看", "list": "要上架", "price": "要改价", "img": "要改图"}
# 旧分组迁移：这些名字的分组现在是自动的（丢掉手动成员）/ 变成「要上传」标记 / 采集箱的文件夹变成标记
AUTO_NAMES = {"已上传", "热销产品", "热销", "滞销产品", "滞销"}
UPLOAD_NAMES = {"准备上架", "待上传"}
INBOX_MARK_NAMES = {"要转入": "into", "再看看": "later"}
DEFAULTS = {"hot_min": 10, "hot_top": 10, "slow_days": 30, "new_days": 14, "low_margin": 15, "low_stock": 3}

SCHEMA = """
CREATE TABLE IF NOT EXISTS goods_views (
  id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT DEFAULT 'goods', name TEXT, state TEXT, username TEXT DEFAULT '', created_at REAL
);
CREATE TABLE IF NOT EXISTS goods_meta (k TEXT PRIMARY KEY, v TEXT);
"""
_inited = set()


def init():
    if db.DB_PATH in _inited:
        return
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()
    _inited.add(db.DB_PATH)


# ---------------- 阈值设置（销售表现、利润低、库存不够） ----------------
def settings():
    from .config import load_config
    cur = load_config().get("goods_groups") or {}
    out = {}
    for k, d in DEFAULTS.items():
        try:
            v = float(cur.get(k, d))
        except (TypeError, ValueError):
            v = float(d)
        out[k] = int(v) if v.is_integer() else v
    return out


def save_settings(d):
    from .config import load_config, save_config
    cur = dict(load_config().get("goods_groups") or {})
    for k in DEFAULTS:
        if k in (d or {}):
            try:
                v = float(d[k])
            except (TypeError, ValueError):
                raise ValueError("请填数字")
            if v < 0 or v > 100000:
                raise ValueError("数字范围不对")
            cur[k] = int(v) if v.is_integer() else v
    save_config({"goods_groups": cur})
    return settings()


# ---------------- 手动标记 ----------------
def sig_price(prices):
    """定价的指纹（「要改价」标记：价格变了就算做完）。"""
    return ",".join(str(x.get("final_price")) for x in prices or [])


def sig_img(p):
    """图片的指纹（「要改图」标记：图片变了就算做完）。"""
    return ",".join(str(i.get("file")) for i in p.get("images") or [])



def set_mark(pids, mark, on=True, note=None, user="", scope="goods"):
    """给一批产品打 / 取消标记，返回改了几个。note=None 时保留原来的备注。"""
    if mark not in MARKS.get(scope, ()):
        raise ValueError("标记不对")
    n = 0
    for pid in pids or []:
        try:
            p = store.load(pid)
        except (FileNotFoundError, ValueError):
            continue
        m = p.get("marks") if isinstance(p.get("marks"), dict) else {}
        if on:
            old = m.get(mark) or {}
            m[mark] = {"note": (old.get("note", "") if note is None else str(note))[:200],
                       "at": old.get("at") or time.time(), "by": old.get("by") or user}
            if mark == "price":
                from . import pricing
                from .config import load_config
                m[mark]["sig"] = sig_price(pricing.price_product(load_config(), p))
            elif mark == "img":
                m[mark]["sig"] = sig_img(p)
        elif mark in m:
            m.pop(mark)
        else:
            continue
        if m:
            p["marks"] = m
        else:
            p.pop("marks", None)
        store.save(p)
        n += 1
    return n


# ---------------- 保存的视图 ----------------
def views(scope="goods"):
    init()
    return [{"id": r["id"], "name": r["name"], "state": json.loads(r["state"] or "{}"), "by": r["username"]}
            for r in db.conn().execute("SELECT * FROM goods_views WHERE scope=? ORDER BY id", (scope,))]


def view_save(name, state, scope="goods", user=""):
    init()
    name = (name or "").strip()[:30]
    if not name:
        raise ValueError("请填写视图名称")
    c = db.conn()
    st = json.dumps(state or {}, ensure_ascii=False)
    r = c.execute("SELECT id FROM goods_views WHERE scope=? AND name=?", (scope, name)).fetchone()
    if r:
        c.execute("UPDATE goods_views SET state=? WHERE id=?", (st, r["id"]))      # 同名 = 覆盖
    else:
        c.execute("INSERT INTO goods_views(scope, name, state, username, created_at) VALUES(?,?,?,?,?)",
                  (scope, name, st, user, time.time()))
    c.commit()
    return views(scope)


def view_delete(vid, scope="goods"):
    init()
    c = db.conn()
    c.execute("DELETE FROM goods_views WHERE id=? AND scope=?", (vid, scope))
    c.commit()
    return views(scope)


# ---------------- 自定义标签（= 旧的分组） ----------------
def tags():
    from . import extras
    extras.init()
    return [{"id": r["id"], "name": r["name"]} for r in db.conn().execute("SELECT id, name FROM product_groups ORDER BY sort, name")]


# ---------------- 迁移（可以重复跑：没有要搬的就什么也不做） ----------------
def migrate(force=False):
    """旧的手动分组 → 新的：已上传 / 热销 / 滞销 现在是自动的（丢掉手动成员，分组删除）；准备上架 / 待上传 → 「要上传」标记；
    采集箱里叫「要转入」「再看看」的文件夹 → 对应标记；其他分组原样保留成自定义标签。产品都还在，没有丢东西。"""
    from . import extras
    init()
    extras.init()
    c = db.conn()
    if not force and c.execute("SELECT 1 FROM goods_meta WHERE k='migrated253'").fetchone():
        return {}
    plan = {}
    for g in [dict(r) for r in c.execute("SELECT id, name FROM product_groups")]:
        nm = (g["name"] or "").strip()
        if nm in AUTO_NAMES:
            plan[g["id"]] = ("auto", None)
        elif nm in UPLOAD_NAMES:
            plan[g["id"]] = ("mark", "upload")
        elif nm in INBOX_MARK_NAMES:
            plan[g["id"]] = ("mark", INBOX_MARK_NAMES[nm])
    out = {"auto": 0, "upload": 0, "inbox": 0}
    if plan:
        for item in store.list_products():
            try:
                p = store.load(item["id"])
            except Exception:  # noqa: BLE001
                continue
            gs = list(p.get("groups") or [])
            hit = [x for x in gs if x in plan]
            if not hit:
                continue
            m = p.get("marks") if isinstance(p.get("marks"), dict) else {}
            for gid in hit:
                kind, mk = plan[gid]
                if kind == "auto":
                    out["auto"] += 1
                else:
                    m.setdefault(mk, {"note": "", "at": time.time(), "by": "迁移"})
                    out["inbox" if mk in MARKS["inbox"] else "upload"] += 1
            p["groups"] = [x for x in gs if x not in plan]
            if m:
                p["marks"] = m
            store.save(p)
        for gid in plan:
            c.execute("DELETE FROM product_groups WHERE id=?", (gid,))
    c.execute("INSERT OR REPLACE INTO goods_meta(k, v) VALUES('migrated253', ?)", (str(time.time()),))
    c.commit()
    return out
