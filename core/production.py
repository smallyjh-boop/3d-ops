"""生产：订单商品 → 打印任务 → 排单到打印机 → 一盘一盘打印（打印批次）→ 后处理 → 打包 → 发货。

- 任务（jobs）：一个订单商品一条（数量可以很多），还有「备货任务」（成品库存）和「补发任务」（售后）。
  qty_done = 已经打好的件数；全部打好 → 后处理 post → 已打包 packed → 已发货 done。
- 打印批次（print_runs）：打印机上的「一盘」。可以把同产品同颜色的多个任务合成一盘（拼盘），
  数量可以按订单 / 满盘 / 指定数量；多出来的件数进成品库存。
  打完（打印机报告完成或员工点「打完」）：扣这一盘的耗材，件数分给各任务；失败：记录原因，扣耗材，任务回到队列。
- 成品库存（stock）：多打的、备货打的放这里；有订单时可以「用库存」直接出货，不用再打。
"""
import json
import math
import os
import time

from . import codes, db, inventory, materials, store
from .config import load_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER, order_item_id INTEGER,
  product_id TEXT, sku TEXT, name TEXT, color TEXT, material TEXT,
  qty INTEGER DEFAULT 1, grams_each REAL, hours_each REAL,
  printer INTEGER, status TEXT DEFAULT 'todo', fails INTEGER DEFAULT 0,
  planned_start REAL, planned_end REAL, started_at REAL, printed_at REAL, packed_at REAL, done_at REAL,
  note TEXT, created_at REAL, updated_at REAL, updated_by TEXT
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS jobs_order ON jobs(order_id);
CREATE TABLE IF NOT EXISTS print_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, printer INTEGER, product_id TEXT, sku TEXT, name TEXT, color TEXT, material TEXT,
  file_id INTEGER, count INTEGER, grams REAL, hours REAL, status TEXT, alloc TEXT, extra INTEGER DEFAULT 0,
  sent INTEGER DEFAULT 0, remote_file TEXT, started_at REAL, ended_at REAL, username TEXT,
  fail_reason TEXT, fail_note TEXT, alert TEXT
);
CREATE INDEX IF NOT EXISTS runs_status ON print_runs(status);
CREATE TABLE IF NOT EXISTS failures (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, run_id INTEGER, printer INTEGER, product_id TEXT, sku TEXT,
  reason TEXT, note TEXT, grams REAL, username TEXT
);
CREATE TABLE IF NOT EXISTS stock (
  sku TEXT PRIMARY KEY, product_id TEXT, name TEXT, color TEXT, qty INTEGER DEFAULT 0, target INTEGER, updated_at REAL
);
CREATE TABLE IF NOT EXISTS stock_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, sku TEXT, delta INTEGER, reason TEXT, username TEXT
);
CREATE TABLE IF NOT EXISTS maintenance (
  id INTEGER PRIMARY KEY AUTOINCREMENT, printer INTEGER, item TEXT, ts REAL, hours_at REAL, username TEXT, note TEXT
);
"""
STATUS_ZH = {"todo": "待打印", "printing": "打印中", "post": "后处理", "packed": "已打包", "done": "已发货", "failed": "打印失败"}
KIND_ZH = {"order": "订单", "stock": "备货", "reship": "补发"}
FAIL_REASONS = ["翘边 / 首层不粘", "打飞 / 脱离热床（空打）", "拉丝 / 表面差", "断料 / 缺料", "堵头", "支撑问题（塌 / 难拆）", "层错位",
                "尺寸 / 形状不对", "颜色 / 材料用错", "人为碰到 / 取件损坏", "其他"]
MAINT_ITEMS = [("clean", "清洁热床、擦喷嘴外部", 50), ("lube", "导轨 / 丝杆清洁润滑、检查皮带", 200),
               ("nozzle", "检查 / 更换喷嘴、清理挤出机", 500)]
COLOR_CHANGE_H = 0.15      # 换料大约多花的时间（小时）


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(jobs)")}
    for col, typ in (("pin", "INTEGER DEFAULT 0"), ("plates_done", "INTEGER DEFAULT 0"), ("consumed_g", "REAL DEFAULT 0"),
                     ("file_id", "INTEGER"), ("remote_file", "TEXT"), ("sent_at", "REAL"), ("alert", "TEXT"),
                     ("qty_done", "INTEGER DEFAULT 0"), ("kind", "TEXT DEFAULT 'order'"), ("run_id", "INTEGER"),
                     ("priority_job", "INTEGER DEFAULT 0"),
                     ("stock_n", "INTEGER DEFAULT 0")):     # v2.35：订单任务里「用库存发」的个数（先占住，发货出库时才扣）
        if col not in cols:
            c.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
            if col == "qty_done":     # 老数据：已经打完的任务
                c.execute("UPDATE jobs SET qty_done=qty WHERE status IN ('post','packed','done')")
    c.commit()


def _now():
    return time.time()


def fleet_is_resin(m):
    from .fleet import is_resin
    return is_resin(m)


def _printer_names():
    return [p.get("name", f"打印机{i + 1}") for i, p in enumerate(load_config().get("printers") or [])]


def _olog(order_id, user, action, detail=""):
    if order_id:
        from . import orders
        orders.log(order_id, user, action, detail)


# ---------------- 生成任务 ----------------
def generate(user=""):
    """给需要生产、还没有任务的订单商品建任务；订单取消了，还没开始的任务删掉。"""
    from .orders import ACTIVE_STATUSES
    c = db.conn()
    rows = c.execute(f"""SELECT i.*, o.id AS oid FROM order_items i JOIN orders o ON o.id=i.order_id
        WHERE o.status IN ({','.join('?' * len(ACTIVE_STATUSES))}) AND i.product_id IS NOT NULL AND COALESCE(o.hold,0)=0
        AND i.id NOT IN (SELECT order_item_id FROM jobs WHERE order_item_id IS NOT NULL)""", ACTIVE_STATUSES).fetchall()
    now = _now()
    n = 0
    cfg = load_config()
    for r in rows:
        color, note = r["color"], None
        if codes.is_random(cfg, color):
            # 随机颜色（v2.16）：按耗材自动选一个颜色来打，记在任务备注和订单日志里
            from . import stockcalc
            try:
                prod = store.load(r["product_id"])
            except Exception:  # noqa: BLE001
                prod = None
            color, note = stockcalc.pick_random_color(r["material"] or "PLA", (r["grams"] or 0) * (r["qty"] or 1), prod, cfg)
            _olog(r["oid"], user or "系统", "随机颜色", f"{r['sku']}：{note}")
        jid = c.execute("""INSERT INTO jobs(order_id, order_item_id, product_id, sku, name, color, material, qty, grams_each,
                     hours_each, status, kind, created_at, updated_at, updated_by, note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (r["oid"], r["id"], r["product_id"], r["sku"], r["name"], color, r["material"] or "PLA",
                         r["qty"] or 1, r["grams"], r["hours"], "todo", "order", now, now, user, note)).lastrowid
        n += 1
        # v2.35：有成品库存就先用库存发（占住数量，发货出库时才扣；不够的部分才排打印）
        if cfg.get("stock_auto_use", True) and not note and r["sku"]:
            use = min(free_stock(r["sku"], c), int(r["qty"] or 1))
            if use > 0:
                _reserve(c, jid, use, int(r["qty"] or 1), 0, now, user or "系统")
                _olog(r["oid"], user or "系统", "用库存发", f"{r['sku']} ×{use}（发货出库时扣库存）")
    cancelled = c.execute("""DELETE FROM jobs WHERE status='todo' AND COALESCE(qty_done,0)=0 AND run_id IS NULL
        AND kind='order' AND order_id IN (SELECT id FROM orders WHERE status IN ('cancelled','returned','delivery_failed')
        OR COALESCE(hold,0)=1)""").rowcount
    # v2.35：还没发货就取消的订单，「用库存发」占住的数量放回去（只用库存、没打印过的任务直接删）
    cancelled += c.execute("""DELETE FROM jobs WHERE kind='order' AND run_id IS NULL AND COALESCE(stock_n,0)>0
        AND COALESCE(qty_done,0)<=COALESCE(stock_n,0) AND status IN ('todo','post')
        AND order_id IN (SELECT id FROM orders WHERE status='cancelled')""").rowcount
    cancelled += _drop_cancelled_partial(c, user)
    c.commit()
    if n or cancelled:
        schedule()
    return {"created": n, "cancelled": cancelled}


def create_job(product_id, sku, qty, kind="stock", order_id=None, user="", note=""):
    """备货任务 / 补发任务。"""
    from . import orders, store
    p = store.load(product_id)
    hit = orders.match_sku(sku, orders.sku_index()) if sku else None
    info = orders._variant_info(*hit) if hit else {"name": p.get("name_zh"), "color": "", "material": p.get("material"),
                                                      "grams": None, "hours": None}
    c = db.conn()
    now = _now()
    jid = c.execute("""INSERT INTO jobs(order_id, product_id, sku, name, color, material, qty, grams_each, hours_each, status,
                       kind, note, created_at, updated_at, updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (order_id, product_id, sku, info.get("name") or p.get("name_zh"), info.get("color", ""),
                     info.get("material") or "PLA", int(qty), info.get("grams"), info.get("hours"), "todo", kind, note,
                     now, now, user)).lastrowid
    c.commit()
    schedule()
    return dict(_job(c, jid))


# ---------------- 排单 ----------------
def plan_for(j, idx, names=None):
    from . import print_files, fleet
    names = names or _printer_names()
    name = names[idx] if idx is not None and 0 <= idx < len(names) else ""
    pl = print_files.plan(dict(j), name)
    if not pl["file"] and fleet.is_resin(j["material"]):
        # 光固化没有文件：时间主要看高度，按「一盘」估（默认每盘几小时见设置）
        cfg = load_config()
        q = max(0, int(j["qty"] or 1) - int(j["qty_done"] or 0))
        pl.update(per_plate=q or 1, plates=1 if q else 0, hours=float(cfg.get("resin_plate_hours") or 3) if q else 0)
    pl["plates_left"] = pl["plates"]
    pl["hours_left"] = pl["hours"]
    pl["grams_per_plate"] = round(pl["grams"] / pl["plates"], 1) if pl["plates"] else 0
    pl["hours_per_plate"] = round(pl["hours"] / pl["plates"], 2) if pl["plates"] else 0
    pl["remaining"] = max(0, int(j["qty"] or 1) - int(j["qty_done"] or 0))
    return pl


def _loaded(idx, p, cmap):
    """打印机现在装的颜色：料盘读到的颜色按色值对应到颜色表 + 手动填的。"""
    from . import printers as pr
    hexes, names = pr.loaded_colors(idx, p)
    out = set(names)
    for h in hexes:
        rgb = pr._rgb(h)
        best = None
        for zh, info in cmap.items():
            c2 = pr._rgb(info.get("hex"))
            if rgb and c2:
                d = sum((a - b) ** 2 for a, b in zip(rgb, c2)) ** 0.5
                if best is None or d < best[0]:
                    best = (d, zh)
        if best and best[0] < 60:
            out.add(best[1])
    return out


def schedule():
    """给待打印的任务分配打印机和预计时间：
    按（加急 → 订单 → 最晚发货 → 下单时间，备货任务最后）排序，每个任务放到「最早能完成」的打印机上；
    同颜色接着打省换料时间（也看打印机上现在装的颜色）；不同打印机按各自切片文件的时长算。
    冗余：停用的、连不上的打印机不分配（指定到它的任务也会转走）；同机型共用切片文件，
    有现成切片文件的机器优先，都排满了才用还没有文件的机型（要先切片/上传）。"""
    from . import codes, fleet, printers as pr
    cfg = load_config()
    printers = cfg.get("printers") or []
    if not printers:
        return 0
    names = [p.get("name", f"打印机{i + 1}") for i, p in enumerate(printers)]
    cmap = codes.color_hex(cfg)
    c = db.conn()
    now = _now()
    avail = []
    usable = []
    for i, p in enumerate(printers):
        st0 = pr.get_status(i)
        ok = p.get("enabled", True) is not False and not (
            (p.get("conn") or {}).get("type", "none") != "none" and st0.get("state") == "offline")
        usable.append(ok)
    if not any(usable):
        usable = [p.get("enabled", True) is not False for p in printers]
    if not any(usable):
        c.execute("UPDATE jobs SET printer=NULL, planned_start=NULL, planned_end=NULL WHERE status='todo' AND run_id IS NULL")
        c.commit()
        return 0
    for i, p in enumerate(printers):
        run = c.execute("SELECT * FROM print_runs WHERE status='printing' AND printer=? ORDER BY started_at DESC LIMIT 1",
                        (i,)).fetchone()
        st = pr.get_status(i)
        if run:
            end = (run["started_at"] or now) + max(run["hours"] or 0.5, 0.1) * 3600
            if st.get("state") == "printing" and st.get("remaining_min"):
                end = now + float(st["remaining_min"]) * 60
            avail.append([max(now, end), {run["color"]}])
        else:
            start = now
            if st.get("state") in ("printing", "paused") and st.get("remaining_min"):
                start = now + float(st["remaining_min"]) * 60     # 打印机上有别的东西在打
            avail.append([start, _loaded(i, p, cmap)])
    jobs = c.execute("""SELECT j.*, o.priority, o.ship_by, o.order_time FROM jobs j LEFT JOIN orders o ON o.id=j.order_id
                        WHERE j.status='todo' AND j.run_id IS NULL
                        ORDER BY COALESCE(o.priority,0) DESC, CASE j.kind WHEN 'stock' THEN 1 ELSE 0 END,
                        (COALESCE(j.qty_done,0)>0) DESC, COALESCE(o.ship_by, 9e12), COALESCE(o.order_time, j.created_at), j.id""").fetchall()
    overhead = float(cfg.get("est_overhead_h") or 0.15)
    no_file_penalty = float(cfg.get("no_file_penalty_h") or 6) * 3600
    for j in jobs:
        best = None
        need_tech = fleet.job_tech(j["material"])
        fits = [fleet.tech_of(printers[i]) == need_tech for i in range(len(avail))]
        pinned = j["pin"] and j["printer"] is not None and j["printer"] < len(avail) and usable[j["printer"]] and fits[j["printer"]]
        plans = {i: plan_for(j, i, names) for i in range(len(avail)) if usable[i] and fits[i] and (not pinned or i == j["printer"])}
        if not plans:      # 没有这种类型的打印机（例如树脂件但没有光固化机）：先不分配
            c.execute("UPDATE jobs SET printer=NULL, planned_start=NULL, planned_end=NULL WHERE id=?", (j["id"],))
            continue
        any_file = any(pl["file"] for pl in plans.values())
        for i, pl in plans.items():
            t, colors = avail[i]
            dur = (pl["hours_left"] + overhead * max(1, pl["plates_left"])) * 3600
            change = 0 if (not colors or j["color"] in colors) else COLOR_CHANGE_H * 3600
            fin = t + change + dur
            score = fin + (no_file_penalty if any_file and not pl["file"] else 0)
            if best is None or score < best[0]:
                best = (score, i, t + change, fin)
        _score, i, start, fin = best
        c.execute("UPDATE jobs SET printer=?, planned_start=?, planned_end=? WHERE id=?", (i, start, fin, j["id"]))
        avail[i] = [fin, {j["color"]}]
    c.commit()
    return len(jobs)


def list_jobs(statuses=None, order_id=None):
    c = db.conn()
    conds, args = [], []
    if statuses:
        conds.append(f"j.status IN ({','.join('?' * len(statuses))})"); args += list(statuses)
    if order_id:
        conds.append("j.order_id=?"); args.append(order_id)
    sql = """SELECT j.*, o.order_no, o.platform, o.custom_note, o.buyer_note, o.ship_by, o.priority, o.buyer
             FROM jobs j LEFT JOIN orders o ON o.id=j.order_id"""
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY COALESCE(j.printer, 99), COALESCE(j.planned_start, 9e12), j.id"
    out = []
    prs = load_config().get("printers") or []
    for r in c.execute(sql, args):
        d = dict(r)
        pi = d.get("printer")
        d["printer_code"] = (prs[pi].get("code") or "") if pi is not None and 0 <= pi < len(prs) else ""
        d["printer_model"] = (prs[pi].get("name") or "") if pi is not None and 0 <= pi < len(prs) else ""
        d["tech"] = "resin" if fleet_is_resin(d.get("material")) else "fdm"
        d["status_zh"] = STATUS_ZH.get(d["status"], d["status"])
        d["kind_zh"] = KIND_ZH.get(d.get("kind") or "order", "")
        d["remaining"] = max(0, int(d["qty"] or 1) - int(d["qty_done"] or 0))
        out.append(d)
    return out


def _job(c, job_id):
    j = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not j:
        raise ValueError("任务不存在")
    return j


# ---------------- 成品库存 ----------------
def stock_add(sku, delta, reason, user="", product_id=None, name="", color=""):
    if not sku or not delta:
        return
    c = db.conn()
    c.execute("""INSERT INTO stock(sku, product_id, name, color, qty, updated_at) VALUES(?,?,?,?,?,?)
                 ON CONFLICT(sku) DO UPDATE SET qty=qty+excluded.qty, updated_at=excluded.updated_at,
                 product_id=COALESCE(stock.product_id, excluded.product_id), name=COALESCE(NULLIF(stock.name,''), excluded.name),
                 color=COALESCE(NULLIF(stock.color,''), excluded.color)""",
              (sku.upper(), product_id, name or "", color or "", int(delta), _now()))
    c.execute("INSERT INTO stock_log(ts, sku, delta, reason, username) VALUES(?,?,?,?,?)",
              (_now(), sku.upper(), int(delta), reason, user))
    try:   # v2.18：成品也在库存管理里，每次变化记一笔流水（v2.31：库存模块开着才记）
        from . import chain
        if chain.inv():
            from .inventory import goods as _g
            _g.on_change(c, sku, int(delta), reason, user, product_id, name, color)
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("3dops").warning("成品库存流水没记上（%s %+d）：%s", sku, int(delta), e)
    c.commit()


def stock_qty(sku):
    r = db.conn().execute("SELECT qty FROM stock WHERE sku=?", ((sku or "").upper(),)).fetchone()
    return max(0, r["qty"]) if r else 0


def reserved(sku, c=None):
    """v2.35：还没发货的订单「用库存发」占住的成品个数（发货出库时才真正扣库存）。"""
    c = c or db.conn()
    r = c.execute("""SELECT COALESCE(SUM(j.stock_n),0) FROM jobs j JOIN orders o ON o.id=j.order_id
                     WHERE UPPER(j.sku)=? AND j.kind='order' AND COALESCE(j.stock_n,0)>0 AND o.status IN ('to_ship','quote','unpaid')""",
                  ((sku or "").upper(),)).fetchone()
    return int(r[0] or 0)


def free_stock(sku, c=None):
    """可以用的成品 = 库存 − 订单占住的。"""
    c = c or db.conn()
    r = c.execute("SELECT qty FROM stock WHERE sku=?", ((sku or "").upper(),)).fetchone()
    return max(0, (r["qty"] if r else 0) - reserved(sku, c))


def _reserve(c, job_id, n, qty, done0, now, user):
    done = done0 + n
    if done >= qty:
        c.execute("UPDATE jobs SET stock_n=COALESCE(stock_n,0)+?, qty_done=?, status='post', printed_at=?, updated_at=?, updated_by=? WHERE id=?",
                  (n, done, now, now, user, job_id))
    else:
        c.execute("UPDATE jobs SET stock_n=COALESCE(stock_n,0)+?, qty_done=?, updated_at=?, updated_by=? WHERE id=?",
                  (n, done, now, user, job_id))


def use_stock(job_id, n, user=""):
    """生产页点「用库存」。订单任务（v2.35）：先占住，发货出库时才扣库存；补发等其他任务：马上扣。"""
    c = db.conn()
    j = _job(c, job_id)
    if j["status"] != "todo" or j["run_id"]:
        raise ValueError("只有还没开始打印的任务可以用库存")
    order_job = (j["kind"] or "order") == "order" and j["order_id"]
    have = free_stock(j["sku"], c) if order_job else stock_qty(j["sku"])
    n = min(int(n or 0), have, max(0, j["qty"] - (j["qty_done"] or 0)))
    if n <= 0:
        raise ValueError("成品库存不够")
    if order_job:
        _reserve(c, job_id, n, j["qty"], j["qty_done"] or 0, _now(), user)
        c.commit()
        _olog(j["order_id"], user, f"任务 #{job_id} 用库存发 {n} 个（发货出库时扣库存）", j["sku"] or "")
    else:
        stock_add(j["sku"], -n, f"订单出货 任务#{job_id}", user)
        done = (j["qty_done"] or 0) + n
        if done >= j["qty"]:
            c.execute("UPDATE jobs SET qty_done=?, status='post', printed_at=?, updated_at=?, updated_by=? WHERE id=?",
                      (done, _now(), _now(), user, job_id))
        else:
            c.execute("UPDATE jobs SET qty_done=?, updated_at=?, updated_by=? WHERE id=?", (done, _now(), user, job_id))
        c.commit()
        _olog(j["order_id"], user, f"任务 #{job_id} 用成品库存 {n} 个", j["sku"] or "")
    schedule()
    return dict(_job(c, job_id))


def stock_list():
    return [dict(r) for r in db.conn().execute("SELECT * FROM stock ORDER BY sku")]


def stock_set(sku, qty=None, target=None, user=""):
    c = db.conn()
    sku = sku.upper()
    if qty is not None:
        cur = stock_qty(sku)
        if int(qty) != cur:
            stock_add(sku, int(qty) - cur, "盘点", user)
    if target is not None:
        c.execute("INSERT INTO stock(sku, qty, target, updated_at) VALUES(?,0,?,?) "
                  "ON CONFLICT(sku) DO UPDATE SET target=excluded.target", (sku, int(target) if target != "" else None, _now()))
        c.commit()


def stock_suggest():
    """备货建议：按近 30 天销量，给卖得好的 SKU 建议常备数量、要补多少、什么时候打（打印机空闲时）。"""
    cfg = load_config()
    cover = float(cfg.get("stock_cover_days") or 7)
    min_sold = float(cfg.get("stock_min_sold30") or 3)
    c = db.conn()
    now = _now()
    sold = {}
    for r in c.execute("""SELECT i.sku, i.product_id, i.name, i.color, SUM(i.qty) AS q FROM order_items i JOIN orders o ON o.id=i.order_id
                          WHERE o.order_time>=? AND o.status NOT IN ('cancelled','unpaid','quote') AND i.product_id IS NOT NULL
                          GROUP BY i.sku""", (now - 30 * 86400,)):
        sold[(r["sku"] or "").upper()] = dict(r)
    stk = {r["sku"]: dict(r) for r in c.execute("SELECT * FROM stock")}
    making = {}
    for r in c.execute("SELECT sku, SUM(qty - COALESCE(qty_done,0)) AS q FROM jobs WHERE kind='stock' AND status IN ('todo','printing') "
                       "GROUP BY sku"):
        making[(r["sku"] or "").upper()] = r["q"] or 0
    # 待打的订单还要多少（库存会先被订单用掉）
    need = {}
    for r in c.execute("SELECT sku, SUM(qty - COALESCE(qty_done,0)) AS q FROM jobs WHERE kind!='stock' AND status IN ('todo','printing') "
                       "GROUP BY sku"):
        need[(r["sku"] or "").upper()] = r["q"] or 0
    # 打印机什么时候空：排单里最晚完成的时间
    free = [r["t"] for r in c.execute("SELECT printer, MAX(planned_end) AS t FROM jobs WHERE status='todo' GROUP BY printer") if r["t"]]
    queue_end = min(free) if free else now
    out = []
    for sku in set(sold) | {k for k, v in stk.items() if v.get("target")}:
        s = sold.get(sku) or {}
        q30 = s.get("q") or 0
        daily = q30 / 30.0
        st = stk.get(sku) or {}
        target = st.get("target")
        auto = target is None
        if auto:
            if q30 < min_sold:
                continue
            target = math.ceil(daily * cover)
        rsv = reserved(sku, c)
        have = max(0, (st.get("qty") or 0) - rsv)          # v2.35：订单占住的不算
        gap = target + need.get(sku, 0) - have - making.get(sku, 0)
        out.append({"sku": sku, "product_id": s.get("product_id") or st.get("product_id"), "name": s.get("name") or st.get("name"),
                    "color": s.get("color") or st.get("color"), "sold30": q30, "daily": round(daily, 2), "stock": st.get("qty") or 0,
                    "reserved": rsv,
                    "target": target, "auto_target": auto, "making": making.get(sku, 0), "order_need": need.get(sku, 0),
                    "suggest": max(0, int(gap)), "suggest_after": max(now, queue_end)})
    out.sort(key=lambda x: (-x["suggest"], -x["sold30"]))
    return out


# ---------------- 打印批次（一盘）----------------
def merge_candidates(job_id):
    """可以和这个任务拼一盘的其他任务：同产品、同颜色、还没开始。"""
    c = db.conn()
    j = _job(c, job_id)
    rows = c.execute("""SELECT j.*, o.order_no, o.ship_by, o.priority FROM jobs j LEFT JOIN orders o ON o.id=j.order_id
                        WHERE j.status='todo' AND j.run_id IS NULL AND j.id!=? AND j.product_id=? AND COALESCE(j.color,'')=?
                        ORDER BY COALESCE(o.priority,0) DESC, CASE j.kind WHEN 'stock' THEN 1 ELSE 0 END,
                        COALESCE(o.ship_by, 9e12), j.id""",
                     (job_id, j["product_id"], j["color"] or "")).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["remaining"] = max(0, d["qty"] - (d["qty_done"] or 0))
        if d["remaining"]:
            out.append(d)
    return out


def send_options(job_id, printer_idx=None):
    """「开始打印」对话框需要的信息：数量选项、可拼盘的任务、可用文件、AI 建议数量、库存。"""
    from . import print_files, recipes, store
    c = db.conn()
    j = dict(_job(c, job_id))
    idx = int(printer_idx) if printer_idx not in (None, "") else j["printer"]
    names = _printer_names()
    pname = names[idx] if idx is not None and 0 <= idx < len(names) else ""
    remaining = max(0, j["qty"] - (j["qty_done"] or 0))
    merge = merge_candidates(job_id)
    files = [print_files.ensure_params(f) for f in
             print_files.candidates(j["product_id"], j["sku"], pname, j["color"] or "", usable_only=False)]
    capacity = None
    recipe = None
    try:
        from . import specmodel
        p0 = store.load(j["product_id"])
        p = specmodel.view(p0, specmodel.spec_of_sku(p0, j["sku"]))      # 规格有自己的模型（v2.22）
        recipe = recipes.get(p)
        if p.get("model"):
            g = recipes.geometry(p, recipe, idx)
            capacity = g.get("capacity")
    except Exception:  # 没有模型时只看已有文件
        p = None
    usable = [f for f in files if f["status"] in ("reviewed", "verified")]
    if not capacity:
        capacity = max([f["per_plate"] for f in files] or [remaining or 1])
    merge_total = sum(m["remaining"] for m in merge)
    # AI / 规则建议：以实际订单为主；同时有备货缺口、而且这一盘还放得下时，建议顺便多打几个
    sug = next((s for s in stock_suggest() if s["sku"] == (j["sku"] or "").upper()), None)
    order_qty = min(capacity, remaining + merge_total)
    stock_gap = max(0, (sug or {}).get("target", 0) - (sug or {}).get("stock", 0) - (sug or {}).get("making", 0))
    extra = min(max(0, capacity - order_qty), stock_gap) if j.get("kind") != "stock" else 0
    suggestion = {"count": order_qty + extra, "order_qty": order_qty, "extra_stock": extra,
                  "why": (f"订单需要 {remaining + merge_total} 个" +
                          (f"；近 30 天卖了 {sug['sold30']} 个，建议常备 {sug['target']} 个、现有 {sug['stock']} 个，"
                           f"这一盘还有空位，建议顺便多打 {extra} 个备货（可以不要）" if extra else "")
                          + (f"；一盘最多 {capacity} 个，剩下的下一盘再打" if remaining + merge_total > capacity else ""))}
    best = next((f for f in files if f["status"] in ("reviewed", "verified")), files[0] if files else None)
    mcheck = material_check(j, print_files.ensure_params(best) if best else None, idx)
    return {"material_check": mcheck,
            "job": j, "printer": idx, "printer_name": pname, "remaining": remaining, "merge": merge, "capacity": capacity,
            "files": files, "usable_files": [f["id"] for f in usable], "has_model": bool(p and p.get("model")),
            "recipe": recipe, "recipe_zh": recipes.summary_zh(recipe) if recipe else "",
            "suggestion": suggestion, "stock": free_stock(j["sku"]),
            "fail_reasons": FAIL_REASONS, "review_items": print_files.REVIEW_ITEMS}


def material_check(j, f, idx):
    """这一盘的材料核对：产品要什么材料 / 切片文件用的什么材料 / 打印机料盘里装的什么。
    返回 {need, color, file_material, nozzle_temp, bed_temp, bed_type, trays, error, tray_warn}"""
    from . import printers as pr, recipes, store
    need = j.get("material") or "PLA"
    try:
        need = store.load(j["product_id"]).get("material") or need
    except Exception:  # noqa: BLE001
        pass
    need = recipes.norm_material(need)
    prm = ((f or {}).get("report") or {}).get("params") or {}
    out = {"need": need, "color": j.get("color") or "", "file_material": prm.get("material"),
           "filament": prm.get("filament"), "nozzle_temp": prm.get("nozzle_temp"), "bed_temp": prm.get("bed_temp"),
           "bed_type": prm.get("bed_type_zh"), "error": "", "tray_warn": ""}
    from . import fleet
    from .config import load_config as _lc
    prs = _lc().get("printers") or []
    if idx is not None and 0 <= idx < len(prs) and fleet.tech_of(prs[idx]) != fleet.job_tech(need):
        out["error"] = ("这个产品是光固化树脂件，只能用光固化打印机" if fleet.is_resin(need)
                        else f"这台是光固化打印机，这个产品要用 {need}（FDM 打印机）")
        return out
    if f and prm.get("material") and recipes.same_material(prm["material"], need) == "diff":
        out["error"] = (f"材料不对：切片文件是 {prm['material']}，这个产品要用 {need}。"
                        f"请在打印方案里确认材料后重新切片")
    trays = []
    try:
        trays = [t for t in (pr.get_status(idx).get("trays") or []) if t.get("type")] if idx is not None else []
    except Exception:  # noqa: BLE001
        trays = []
    out["trays"] = [{"slot": t.get("slot"), "type": t.get("type"), "label": t.get("label"), "hex": t.get("hex")} for t in trays]
    if trays and not any(recipes.same_material(t["type"], need) != "diff" for t in trays):
        out["tray_warn"] = (f"打印机料盘里读到的是 {'、'.join(sorted({str(t['type']) for t in trays}))}，"
                            f"没有 {need}。请先换成 {need}")
    return out



def _file_for_count(j, idx, count, file_id=None, user=""):
    """找到（或马上切出）一盘 count 个的文件。"""
    from . import print_files, recipes, store
    names = _printer_names()
    pname = names[idx]
    if file_id:
        f = print_files.get(int(file_id))
        if not f:
            raise ValueError("文件不存在")
        return f
    f = print_files.find(j["product_id"], j["sku"], pname, j["color"] or "", per_plate=count)
    if f:
        return f
    from . import specmodel
    p0 = store.load(j["product_id"])
    p = specmodel.view(p0, specmodel.spec_of_sku(p0, j["sku"]))       # 规格有自己的模型时切那个模型（v2.22）
    if not p.get("model"):
        have = sorted({x["per_plate"] for x in print_files.candidates(j["product_id"], j["sku"], pname, j["color"] or "")})
        raise ValueError(f"没有一盘 {count} 个的切片文件，这个产品也没有 3D 模型可以自动切片。"
                         f"现有文件的数量：{have or '无'}")
    recipe = recipes.get(p)
    tmp, rep, recipe = recipes.slice_product(p, idx, count, recipe)
    geo = recipes.geometry(p, recipe, idx)
    checks = recipes.check(recipe, geo, rep, p.get("material") or "PLA")
    sp = p.get("_spec") or ""
    f = print_files.add(tmp, f"{p['id']}{'_' + sp if sp else ''}_{pname}_x{count}.gcode.3mf".replace(" ", "_"), p["id"], pname, "", count, "",
                        "按打印方案自动切片", user, p.get("material") or "PLA", rep.get("grams_per_plate"),
                        rep.get("hours_per_plate"), move=True, recipe=recipe, report=rep, checks=checks, source="recipe", spec=sp)
    # 同一份方案已经有复核过的文件、这次检查也没有错误 → 只是数量不同，沿用复核结果
    base = [x for x in print_files.candidates(p["id"], j["sku"] if sp else "", pname) if x.get("recipe") == recipe and x["id"] != f["id"]]
    if base and not any(x["level"] == "error" for x in checks):
        c = db.conn()
        c.execute("UPDATE print_files SET status='reviewed', reviewed_by=?, reviewed_at=?, note=? WHERE id=?",
                  (user, _now(), f"沿用同一方案的复核（文件 #{base[0]['id']}），只改了数量", f["id"]))
        c.commit()
        f = print_files.get(f["id"])
    return f


def start_run(job_id, printer_idx=None, count=None, merge_ids=None, file_id=None, send=True, user="",
              confirm=None, tray=None, force_color=False):
    """开始一盘：分配件数给各任务（拼盘）、多的进库存，发送到打印机（或手动开始）。"""
    from . import codes, print_files, printers as pr
    confirm = confirm or {}
    if not confirm.get("bed_clear"):
        raise ValueError("请先确认热床已经清空")
    if not confirm.get("material"):
        raise ValueError("请先确认打印机里装的材料和颜色是对的")
    c = db.conn()
    j = dict(_job(c, job_id))
    if j["status"] != "todo" or j["run_id"]:
        raise ValueError("这个任务已经在打印了")
    idx = int(printer_idx) if printer_idx not in (None, "") else j["printer"]
    if idx is None:
        raise ValueError("请选择打印机")
    names = _printer_names()
    jobs = [j] + [dict(_job(c, int(x))) for x in (merge_ids or []) if int(x) != job_id]
    for x in jobs[1:]:
        if x["product_id"] != j["product_id"] or (x["color"] or "") != (j["color"] or "") or x["status"] != "todo" or x["run_id"]:
            raise ValueError(f"任务 #{x['id']} 不能拼在一起（产品/颜色不同或已经在打印）")
    need = sum(max(0, x["qty"] - (x["qty_done"] or 0)) for x in jobs)
    count = int(count or need or 1)
    if send:
        pc = ((load_config().get("printers") or [])[idx].get("conn") or {})
        if (pc.get("type") or "none") == "none":
            raise ValueError("这台打印机没有设置连接（生产 → 打印机 → 连接设置）。也可以选「手动开始」，在打印机上自己开始打印")
        if pr.get_status(idx).get("state") in ("printing", "paused"):
            raise ValueError(f"「{names[idx]}」正在打印，不能发送新文件")
    f = None
    if send or file_id:
        f = _file_for_count(j, idx, count, file_id, user)
        if f["status"] == "draft":
            # 草稿：员工在开始对话框里逐项确认 = 人工复核（自动检查有错误时不允许）
            items = confirm.get("review") or {}
            if all(items.get(k) for k, _ in print_files.REVIEW_ITEMS):
                f = print_files.review(f["id"], items, user, "开始打印时人工复核")
            else:
                raise ValueError("这个切片文件还没复核。请逐项确认支撑、方向、数量、参数、材料后再开始")
        if f["status"] != "verified":
            items = confirm.get("review") or {}
            missing = [lab for k, lab in print_files.REVIEW_ITEMS if not items.get(k)]
            if missing:
                raise ValueError("这个文件还没试打验证，请先确认：" + "、".join(missing))
        count = int(f["per_plate"])
    f = print_files.ensure_params(f) if f else f
    if f:                                   # v2.32：切片文件必须是这台机型、喷嘴、热床板的，对不上一律不能发（会损坏机器）
        from modules.prod import slicecheck
        sc = slicecheck.check(f, idx)
        if not sc["ok"]:
            raise ValueError("不能用这个切片文件：" + "；".join(sc["errors"]))
    mc = material_check(j, f, idx)
    if mc["error"]:
        raise ValueError(mc["error"])
    if send and mc["tray_warn"] and not confirm.get("tray_override"):
        raise ValueError(mc["tray_warn"] + "。如果料盘读数不准、你已经确认装的是对的，请勾选「料盘读数不准，我已确认」")
    j["material"] = mc["need"]
    # 分配件数
    alloc, left = {}, count
    for x in jobs:
        if left <= 0:
            break
        n = min(left, max(0, x["qty"] - (x["qty_done"] or 0)))
        if n > 0:
            alloc[str(x["id"])] = n
            left -= n
    extra = max(0, left)
    grams = f["grams"] if f else (j["grams_each"] or 0) * count
    hours = f["hours"] if f else (j["hours_each"] or 1) * count
    remote = ""
    warning = ""
    if send:
        if not f:
            raise ValueError("没有切片文件，不能发送")
        info = codes.color_hex(load_config()).get(j["color"] or "") or {}
        slot = tray
        if slot in (None, ""):
            m = pr.match_tray(idx, info.get("hex"), j["material"] or "")
            if m:
                slot = m[0]
                if m[2] > 60 and not force_color:
                    raise ValueError(f"打印机料盘里没有接近「{j['color']}」的颜色（最接近的是 {m[1].get('label')}）。"
                                     f"请先换料，或选择料盘后再发送")
        warning = materials.check_job_stock(grams or 0, j["material"], j["color"], idx)
        rname = f"R{_now():.0f}"[-7:] + "_" + os.path.splitext(f["filename"].replace(".gcode.3mf", ".3mf"))[0][:40]
        rname += ".gcode.3mf" if f["kind"] == "3mf" else ".gcode"
        remote = pr.send_file(idx, print_files.path_of(f), rname, f["kind"], None if slot in (None, "") else int(slot))
        pr.mark_sent(idx, remote)
    now = _now()
    rid = c.execute("""INSERT INTO print_runs(printer, product_id, sku, name, color, material, file_id, count, grams, hours, status,
                       alloc, extra, sent, remote_file, started_at, username) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (idx, j["product_id"], j["sku"], j["name"], j["color"], j["material"], f["id"] if f else None, count,
                     grams, hours, "printing", json.dumps(alloc), extra, 1 if send else 0, remote, now, user)).lastrowid
    for jid in alloc:
        c.execute("UPDATE jobs SET status='printing', run_id=?, printer=?, started_at=COALESCE(started_at, ?), pin=1, alert='', "
                  "updated_at=?, updated_by=? WHERE id=?", (rid, idx, now, now, user, int(jid)))
    c.commit()
    for x in jobs:
        if str(x["id"]) in alloc:
            _olog(x["order_id"], user, f"开始打印 {names[idx]}（这一盘 {alloc[str(x['id'])]} 个）",
                  "已发送到打印机" if send else "手动开始")
    schedule()
    return {"run_id": rid, "count": count, "alloc": alloc, "extra": extra, "warning": warning, "file": f}


def _drop_cancelled_partial(c, user=""):
    """v2.38：订单取消 / 退货 / 拒收时，已经打了一部分、还没在打的任务：不再排单，已经打好的件转成品库存。"""
    rows = c.execute("""SELECT * FROM jobs WHERE kind='order' AND run_id IS NULL AND status='todo'
        AND COALESCE(qty_done,0)>COALESCE(stock_n,0)
        AND order_id IN (SELECT id FROM orders WHERE status IN ('cancelled','returned','delivery_failed'))""").fetchall()
    for j in rows:
        made = (j["qty_done"] or 0) - (j["stock_n"] or 0)
        c.execute("DELETE FROM jobs WHERE id=?", (j["id"],))
        stock_add(j["sku"], made, f"订单取消，已打好的转成品库存（任务#{j['id']}）", user or "系统", j["product_id"], j["name"], j["color"])
        _olog(j["order_id"], user or "系统", "订单取消，停止生产", f"{j['sku']} 已打好 {made} 个转成品库存")
    return len(rows)


def _run(c, rid):
    r = c.execute("SELECT * FROM print_runs WHERE id=?", (rid,)).fetchone()
    if not r:
        raise ValueError("打印批次不存在")
    return r


def finish_run(rid, user="", actual_count=None):
    """这一盘打完：扣耗材，件数分给任务，多的进成品库存。"""
    c = db.conn()
    r = dict(_run(c, rid))
    if r["status"] != "printing":
        return r
    alloc = json.loads(r["alloc"] or "{}")
    now = _now()
    inventory.consume_production(r["material"], r["color"], r["grams"] or 0, f"打印完成 批次#{rid}", user, r["printer"], f"run:{rid}")
    for jid, n in alloc.items():
        j = c.execute("SELECT * FROM jobs WHERE id=?", (int(jid),)).fetchone()
        if not j:      # v2.38：任务已经不在了（订单被删）→ 打好的件进成品库存，别中途报错（报错时耗材已经扣了）
            stock_add(r["sku"], n, f"任务已删除，打好的进库存 批次#{rid}", user, r["product_id"], r["name"], r["color"])
            continue
        done = (j["qty_done"] or 0) + n
        if j["kind"] == "stock":
            stock_add(j["sku"], n, f"备货打印 批次#{rid}", user, j["product_id"], j["name"], j["color"])
        gone = (j["kind"] or "order") == "order" and j["order_id"] and c.execute(       # v2.38：打的时候订单被取消了
            "SELECT 1 FROM orders WHERE id=? AND status IN ('cancelled','returned','delivery_failed')", (j["order_id"],)).fetchone()
        if done >= j["qty"] and not gone:
            status = "done" if j["kind"] == "stock" else "post"
            c.execute("UPDATE jobs SET qty_done=?, status=?, printed_at=?, done_at=CASE WHEN ?='done' THEN ? ELSE done_at END, "
                      "run_id=NULL, consumed_g=COALESCE(consumed_g,0)+?, updated_at=?, updated_by=? WHERE id=?",
                      (done, status, now, status, now, (r["grams"] or 0) * n / max(1, r["count"]), now, user, j["id"]))
        else:
            c.execute("UPDATE jobs SET qty_done=?, status='todo', run_id=NULL, consumed_g=COALESCE(consumed_g,0)+?, "
                      "updated_at=?, updated_by=? WHERE id=?",
                      (done, (r["grams"] or 0) * n / max(1, r["count"]), now, user, j["id"]))
        _olog(j["order_id"], user, f"打完 {n} 个（批次 #{rid}）", f"已完成 {done}/{j['qty']}")
    if r["extra"]:
        stock_add(r["sku"], r["extra"], f"多打进库存 批次#{rid}", user, r["product_id"], r["name"], r["color"])
    c.execute("UPDATE print_runs SET status='done', ended_at=?, alert='' WHERE id=?", (now, rid))
    _drop_cancelled_partial(c, user)      # v2.38：打的时候订单被取消了 → 这一盘打完后停下
    c.commit()
    schedule()
    return dict(_run(c, rid))


def fail_run(rid, reason="", note="", user=""):
    """这一盘失败：记录原因，扣掉用掉的料（按进度估，读不到按一半），任务回到队列。"""
    from . import printers as pr
    c = db.conn()
    r = dict(_run(c, rid))
    if r["status"] != "printing":
        raise ValueError("这一盘已经结束了")
    prog = pr.get_status(r["printer"]).get("progress")
    frac = (float(prog) / 100) if isinstance(prog, (int, float)) and prog > 0 else 0.5
    grams = round((r["grams"] or 0) * frac, 1)
    inventory.consume_production(r["material"], r["color"], grams, f"打印失败 批次#{rid}", user, r["printer"], f"run:{rid}", failed=True)
    now = _now()
    c.execute("INSERT INTO failures(ts, run_id, printer, product_id, sku, reason, note, grams, username) VALUES(?,?,?,?,?,?,?,?,?)",
              (now, rid, r["printer"], r["product_id"], r["sku"], reason or "其他", note, grams, user))
    alloc = json.loads(r["alloc"] or "{}")
    for jid in alloc:
        j = c.execute("SELECT * FROM jobs WHERE id=?", (int(jid),)).fetchone()
        if not j:      # v2.38：任务已经不在了
            continue
        c.execute("UPDATE jobs SET status='todo', run_id=NULL, fails=COALESCE(fails,0)+1, pin=0, alert='', "
                  "consumed_g=COALESCE(consumed_g,0)+?, updated_at=?, updated_by=? WHERE id=?",
                  (grams / max(1, len(alloc)), now, user, j["id"]))
        _olog(j["order_id"], user, f"打印失败（{reason or '其他'}）", note or "")
    c.execute("UPDATE print_runs SET status='failed', ended_at=?, fail_reason=?, fail_note=? WHERE id=?",
              (now, reason, note, rid))
    _drop_cancelled_partial(c, user)      # v2.38
    c.commit()
    schedule()
    return dict(_run(c, rid))


def cancel_run(rid, user=""):
    """还没真正开始（例如发错了）：撤销，不扣料。"""
    c = db.conn()
    r = dict(_run(c, rid))
    for jid in json.loads(r["alloc"] or "{}"):
        c.execute("UPDATE jobs SET status='todo', run_id=NULL, updated_at=?, updated_by=? WHERE id=?", (_now(), user, int(jid)))
    c.execute("UPDATE print_runs SET status='cancelled', ended_at=? WHERE id=?", (_now(), rid))
    c.commit()
    schedule()


def active_runs():
    out = []
    for r in db.conn().execute("SELECT * FROM print_runs WHERE status='printing' ORDER BY started_at"):
        d = dict(r)
        d["alloc"] = json.loads(d["alloc"] or "{}")
        out.append(d)
    return out


# ---------------- 兼容：按钮直接改状态 ----------------
def set_status(job_id, status, user="", printer=None, note=None):
    c = db.conn()
    j = _job(c, job_id)
    now = _now()
    sets = {"updated_at": now, "updated_by": user}
    if note is not None:
        sets["note"] = note
    if printer is not None and printer != "":
        sets["printer"] = int(printer)
        sets["pin"] = 1
    if not status:
        pass
    elif status == "post":
        if j["run_id"]:
            finish_run(j["run_id"], user)
            return dict(_job(c, job_id))
        if j["status"] == "todo":
            pl = plan_for(j, j["printer"])
            inventory.consume_production(j["material"], j["color"], pl["grams"], f"打印完成 任务#{job_id}", user, j["printer"], f"job:{job_id}")
            sets.update(qty_done=j["qty"], printed_at=now, consumed_g=(j["consumed_g"] or 0) + pl["grams"])
        sets["status"] = "post"
    elif status == "failed":
        if j["run_id"]:
            fail_run(j["run_id"], "其他", "", user)
            return dict(_job(c, job_id))
        sets.update(status="todo", fails=(j["fails"] or 0) + 1)
    elif status in ("packed", "done", "todo"):
        sets["status"] = status
        if status == "packed":
            sets["packed_at"] = now
        if status == "done":
            sets["done_at"] = now
    elif status == "printing":
        raise ValueError("请用「开始打印」")
    else:
        raise ValueError("状态不对")
    c.execute(f"UPDATE jobs SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), job_id))
    if status == "done" and j["order_id"]:
        left = c.execute("SELECT COUNT(*) FROM jobs WHERE order_id=? AND status!='done'", (j["order_id"],)).fetchone()[0]
        if not left:
            shipped = c.execute("UPDATE orders SET status='shipped', shipped_at=?, updated_at=? WHERE id=? AND status IN ('to_ship','quote')",
                                (now, now, j["order_id"])).rowcount
    c.commit()
    if status == "done" and j["order_id"] and locals().get("shipped"):
        from . import chain
        chain.order_status(j["order_id"], "shipped", "to_ship", user)
    if status:
        _olog(j["order_id"], user, f"生产任务 #{job_id} {STATUS_ZH.get(status, status)}", j["sku"] or "")
    schedule()
    return dict(_job(c, job_id))


def on_printer_change(idx, old, new):
    """打印机状态变化：我们发的那一盘打完了 → 自动记录；失败/取消 → 提醒员工确认。
    连不上 / 重新连上：重新排单（任务转到其他机器 / 转回来）。"""
    if (old.get("state") == "offline") != (new.get("state") == "offline") and old.get("state"):
        try:
            schedule()
        except Exception:  # noqa: BLE001
            pass
    c = db.conn()
    r = c.execute("SELECT * FROM print_runs WHERE status='printing' AND printer=? ORDER BY started_at DESC LIMIT 1", (idx,)).fetchone()
    if not r:
        return
    was, now_s = old.get("state"), new.get("state")
    fname = str(new.get("file") or "")
    remote = str(r["remote_file"] or "")
    same = bool(remote and fname and (os.path.splitext(fname)[0].split(".")[0] in remote
                                       or os.path.splitext(remote)[0].split(".")[0] in fname))
    if now_s in ("finished", "failed") and was not in ("printing", "paused") and not same:
        return
    if now_s == "finished":
        p = (load_config().get("printers") or [])[idx]
        if (p.get("conn") or {}).get("auto_complete", True):
            finish_run(r["id"], "打印机")
    elif now_s == "failed":
        c.execute("UPDATE print_runs SET alert=? WHERE id=?", ("打印机报告失败或被取消，请检查后点「失败」或「打完」", r["id"]))
        c.commit()


# ---------------- 质量 / 保养 ----------------
def quality(days=30):
    c = db.conn()
    since = _now() - days * 86400
    runs = c.execute("SELECT status, COUNT(*) n FROM print_runs WHERE started_at>=? AND status IN ('done','failed') GROUP BY status",
                     (since,)).fetchall()
    tot = {r["status"]: r["n"] for r in runs}
    q = lambda col: [dict(r) for r in c.execute(  # noqa: E731
        f"SELECT {col} AS k, COUNT(*) AS n, SUM(grams) AS g FROM failures WHERE ts>=? GROUP BY {col} ORDER BY n DESC", (since,))]
    recent = [dict(r) for r in c.execute("SELECT * FROM failures ORDER BY id DESC LIMIT 50")]
    done, failed = tot.get("done", 0), tot.get("failed", 0)
    return {"runs_done": done, "runs_failed": failed, "fail_rate": round(failed / (done + failed) * 100, 1) if done + failed else None,
            "by_reason": q("reason"), "by_sku": q("sku"), "by_printer": q("printer"), "recent": recent,
            "reasons": FAIL_REASONS}


def printer_hours(idx):
    r = db.conn().execute("""SELECT SUM(CASE WHEN ended_at IS NOT NULL THEN (ended_at-started_at)/3600.0 ELSE 0 END) AS h
                             FROM print_runs WHERE printer=? AND status IN ('done','failed')""", (idx,)).fetchone()
    return round(r["h"] or 0, 1)


def maintenance_status():
    names = _printer_names()
    c = db.conn()
    out = []
    for i, n in enumerate(names):
        h = printer_hours(i)
        items = []
        for key, label, every in MAINT_ITEMS:
            last = c.execute("SELECT * FROM maintenance WHERE printer=? AND item=? ORDER BY id DESC LIMIT 1", (i, key)).fetchone()
            since = h - (last["hours_at"] if last else 0)
            items.append({"item": key, "label": label, "every_h": every, "since_h": round(since, 1),
                          "due": since >= every, "last_ts": last["ts"] if last else None})
        out.append({"index": i, "name": n, "hours": h, "items": items})
    return out


def maintenance_done(idx, item, user="", note="", parts=None):
    """记一次保养。parts：[{item_id, qty}] 这次用掉的备件 —— 从库存领用出库，记到这台打印机上（v2.18）。"""
    from . import chain
    if parts and chain.inv():           # v2.31：库存模块关着就不领用备件
        prs = load_config().get("printers") or []
        code = (prs[idx].get("code") or f"#{idx + 1}") if 0 <= idx < len(prs) else ""
        inventory.create_doc("issue", [{"item_id": p["item_id"], "qty": p["qty"]} for p in parts], f"保养：{item}" + (f"（{note}）" if note else ""),
                             user, printer=code, ref=f"maint:{idx}")
    c = db.conn()
    c.execute("INSERT INTO maintenance(printer, item, ts, hours_at, username, note) VALUES(?,?,?,?,?,?)",
              (idx, item, _now(), printer_hours(idx), user, note))
    c.commit()


# ---------------- 看板 ----------------
def board():
    from . import printers as pr, store
    cfg = load_config()
    printers = cfg.get("printers") or []
    names = [p.get("name", f"打印机{i + 1}") for i, p in enumerate(printers)]
    jobs = list_jobs(("todo", "printing", "post", "packed"))
    runs = active_runs()
    pinfo = {}

    def prod(pid):
        if pid not in pinfo:
            try:
                p = store.load(pid)
                img = next((im for im in p.get("images", []) if im.get("file")), None)
                from . import recipes
                r = recipes.get(p)
                pinfo[pid] = {"title_th": (p.get("copy") or {}).get("title_th", "")[:60], "name_zh": p.get("name_zh", ""),
                              "img": f"/files/{pid}/{'out' if img.get('processed') else 'raw'}/{img['file']}" if img else "", "recipe_zh": recipes.summary_zh(r),
                              "recipe_notes": r.get("notes", ""), "lead_days": p.get("lead_days")}
            except Exception:  # 产品被删了
                pinfo[pid] = {}
        return pinfo[pid]
    for j in jobs:
        j["product"] = prod(j["product_id"]) if j["product_id"] else {}
        j["stock"] = free_stock(j["sku"]) if j["status"] == "todo" else 0
        if j["status"] == "todo" and j["printer"] is not None:
            pl = plan_for(j, j["printer"], names)
            f = pl["file"] or {}
            j["plan"] = {"file": f.get("filename"), "file_id": f.get("id"), "file_status": f.get("status"),
                         "per_plate": pl["per_plate"], "plates": pl["plates"], "hours_left": pl["hours"], "grams": pl["grams"]}
    by_id = {j["id"]: j for j in jobs}
    for r in runs:
        r["jobs"] = [dict(by_id[int(k)], run_qty=v) for k, v in r["alloc"].items() if int(k) in by_id]
        r["product"] = prod(r["product_id"]) if r["product_id"] else {}
    lanes = []
    for i, p in enumerate(printers):
        q = [j for j in jobs if j["printer"] == i and j["status"] == "todo"]
        st = pr.get_status(i)
        lanes.append({"index": i, "name": names[i], "code": p.get("code") or f"#{i + 1}", "enabled": p.get("enabled", True) is not False,
                      "note": p.get("note") or "", "tech": p.get("tech") or "fdm", "queue": q, "runs": [r for r in runs if r["printer"] == i],
                      "hours": round(sum((j.get("plan") or {}).get("hours_left", 0) for j in q), 1),
                      "free_at": max([j["planned_end"] or 0 for j in q] or [0]),
                      "status": st, "status_zh": pr.STATE_ZH.get(st.get("state") or "none", ""),
                      "conn": (p.get("conn") or {}).get("type", "none")})
    unassigned = [j for j in jobs if j["status"] == "todo" and j["printer"] is None]
    return {"lanes": lanes, "unassigned": unassigned,
            "post": [j for j in jobs if j["status"] == "post"],
            "packed": [j for j in jobs if j["status"] == "packed"],
            "missing_data": [j for j in jobs if j["status"] == "todo" and not (j.get("plan") or {}).get("file")
                             and (not j["grams_each"] or not j["hours_each"])],
            "fail_reasons": FAIL_REASONS}
