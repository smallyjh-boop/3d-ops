"""今日待办（v2.46，从「运营分析系统」搬进来）：各模块交上来的待办汇在一起，每条可以「完成」或「忽略」。

谁能交待办：
  · 模块说明书里写 "todo": 函数（core/modules.py 装载时登记），模块关着就不收它的待办；
  · 内核自己：订单（超时未发货、快到期、待审核、售后快到期）和耗材（不够打、该补货）。
函数的写法：fn(add)，add(key, 分组, 级别, 标题, 说明="", tab="", roles="owner", alert=None, th=None)
  key     同一件事同一个 key（完成 / 忽略按 key 记；想让它过几天再出来，就把日期或数值写进 key）
  分组     GROUPS 里的中文名（新分组排在后面）
  级别     bad 红 / warn 黄 / info 灰
  tab     点标题跳到哪个页面
  roles   谁能看到（逗号分隔：owner,listing,production；老板什么都看得到）
  alert   要推送到手机的文字（True = 用标题 + 说明）；运营分析模块按 key 去重后推送 LINE / Telegram
  th      (泰文标题, 泰文说明)，不给就用中文（前台再按翻译表翻）

对外：register(source, fn)  collect(role=None, include_done=False)  set_state(key, state, user)  sources()
      counts(role)：右上角 🔔 的数字（v2.49，每页每分钟问一次：按角色缓存 45 秒，点了完成 / 忽略马上清掉）
"""
import threading
import time
import traceback

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS todo_state (
  key TEXT PRIMARY KEY, state TEXT, ts REAL, username TEXT
);
"""
GROUPS = ["发货", "售后", "客服", "评价", "商品", "耗材与价格", "采购", "利润", "财务", "计划", "营销", "竞品", "竞店", "爆款雷达", "选品", "平台接口"]
GROUP_TH = {"发货": "การจัดส่ง", "售后": "หลังการขาย", "客服": "แชทลูกค้า", "评价": "รีวิว", "商品": "สินค้า",
            "耗材与价格": "วัสดุและราคา", "采购": "จัดซื้อ", "利润": "กำไร", "财务": "การเงิน", "平台接口": "API แพลตฟอร์ม", "其他": "อื่นๆ",
            "计划": "แผนสินค้า", "营销": "ปฏิทินการตลาด", "仓库": "คลังสินค้า", "竞品": "สินค้าคู่แข่ง", "竞店": "ร้านคู่แข่ง", "爆款雷达": "เรดาร์สินค้าขายดี", "选品": "คัดเลือกสินค้า"}
SOURCE_ZH = {"orders": ("订单", "ออเดอร์"), "prod": ("耗材", "วัสดุ")}
LEVELS = {"bad": 0, "warn": 1, "info": 2}
_providers = []          # [(来源, 函数)]
_lock = threading.Lock()
_inited = set()


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()
    _inited.add(db.DB_PATH)


def _ensure():
    if db.DB_PATH not in _inited:
        init()


def register(source, fn):
    with _lock:
        if not any(s == source and f is fn for s, f in _providers):
            _providers.append((source, fn))


def _enabled(source):
    from . import modules
    if source == "core" or not modules.is_loaded():
        return True
    return modules.get(source) is None or modules.enabled(source)


def sources():
    """[{id, zh, th}]：有哪些来源（开着的模块），设置里按来源关推送用。"""
    from . import modules
    out, seen = [], set()
    for src, _fn in list(_providers):
        if src in seen or not _enabled(src):
            continue
        seen.add(src)
        zh, th = SOURCE_ZH.get(src) or (modules.name_of(src), modules.name_of(src, th=True))
        out.append({"id": src, "zh": zh, "th": th})
    return out


def collect(role=None, include_done=False):
    """所有待办。role 给了就只要这个角色能看的（老板 = 全部）。
    返回 {items, groups, hidden, errors}；items 里每条 {key, source, group, level, title, detail, tab, roles, alert, title_th, detail_th, state}。"""
    _ensure()
    items, errors, seen = [], [], set()
    for src, fn in list(_providers):
        if not _enabled(src):
            continue

        def add(key, group, level, title, detail="", tab="", roles="owner", alert=None, th=None, _src=src):
            key = str(key)
            if key in seen:
                return
            seen.add(key)
            th = th or (None, None)
            items.append({"key": key, "source": _src, "group": group or "其他", "level": level if level in LEVELS else "info",
                          "title": str(title), "detail": str(detail or ""), "tab": tab or "", "roles": roles or "owner",
                          "alert": (f"{title}" + (f"（{detail}）" if detail else "")) if alert is True else (alert or None),
                          "title_th": th[0] or None, "detail_th": th[1] if len(th) > 1 else None})
        try:
            fn(add)
        except Exception as e:  # noqa: BLE001  一个来源出错不影响别的
            errors.append({"source": src, "error": str(e)[:300]})
            try:
                from . import diag
                diag.log.error("待办来源 %s 出错：%s\n%s", src, e, traceback.format_exc()[-1500:])
            except Exception:  # noqa: BLE001
                pass
    if role and role != "owner":
        items = [i for i in items if role in i["roles"].split(",")]
    st = states()
    for i in items:
        i["state"] = st.get(i["key"], "")
    hidden = sum(1 for i in items if i["state"])
    if not include_done:
        items = [i for i in items if not i["state"]]
    groups = GROUPS + sorted({i["group"] for i in items} - set(GROUPS))
    items.sort(key=lambda i: (groups.index(i["group"]), LEVELS.get(i["level"], 3)))
    return {"items": items, "groups": [{"zh": g, "th": GROUP_TH.get(g, g)} for g in groups], "hidden": hidden, "errors": errors}


_cache = {}            # 角色 → (时间, 结果)
CACHE_SEC = 45


def counts(role=None):
    """🔔 用：{n 未处理条数, bad 紧急条数, warn, by_source}。同一个角色 45 秒内只真正算一次。"""
    key = (db.DB_PATH, role or "owner")
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SEC:
        return hit[1]
    d = collect(role)
    items = d["items"]
    by = {}
    for i in items:
        by[i["source"]] = by.get(i["source"], 0) + 1
    out = {"n": len(items), "bad": sum(1 for i in items if i["level"] == "bad"), "warn": sum(1 for i in items if i["level"] == "warn"),
           "by_source": by}
    _cache[key] = (time.time(), out)
    return out


def states():
    _ensure()
    return {r["key"]: r["state"] for r in db.conn().execute("SELECT key, state FROM todo_state")}


def set_state(key, state, user=""):
    """state：done 完成 / ignored 忽略 / 空 = 恢复。"""
    _ensure()
    key = str(key or "").strip()
    if not key:
        raise ValueError("缺少待办编号")
    c = db.conn()
    if state in ("done", "ignored"):
        c.execute("INSERT OR REPLACE INTO todo_state(key, state, ts, username) VALUES(?,?,?,?)", (key, state, time.time(), user or ""))
    elif state in ("", None, "open"):
        c.execute("DELETE FROM todo_state WHERE key=?", (key,))
    else:
        raise ValueError("状态不对")
    c.execute("DELETE FROM todo_state WHERE ts < ?", (time.time() - 120 * 86400,))
    c.commit()
    _cache.clear()


# ---------------- 内核自己的待办：订单、售后、耗材 ----------------
def _orders(add):
    from . import config
    cfg = config.load_config()
    try:
        warn_h = float(cfg.get("oa_ship_warn_hours") or 12)
    except (TypeError, ValueError):
        warn_h = 12
    now = time.time()
    c = db.conn()
    rows = c.execute("SELECT id, platform, order_no, ship_by, COALESCE(hold,0) hold, hold_reason FROM orders "
                     "WHERE status='to_ship' ORDER BY ship_by").fetchall()
    done_jobs = set()
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone():
        # 生产任务都打包好了 / 发了的订单不算（和工作台「已超时」一样）
        for r in c.execute("SELECT order_id, SUM(CASE WHEN status IN ('packed','done') THEN 0 ELSE 1 END) n FROM jobs "
                           "WHERE order_id IS NOT NULL GROUP BY order_id"):
            if not r["n"]:
                done_jobs.add(r["order_id"])
    for o in rows:
        plat = (o["platform"] or "").capitalize()
        if o["hold"]:
            add(f"hold:{o['id']}", "发货", "warn", f"订单待审核：{plat} {o['order_no']}", o["hold_reason"] or "",
                "orders", "owner,listing", th=(f"ออเดอร์รอตรวจ: {plat} {o['order_no']}", o["hold_reason"] or ""))
        if not o["ship_by"] or o["id"] in done_jobs:
            continue
        h = round((o["ship_by"] - now) / 3600, 1)
        if h < 0:
            add(f"ship:{o['id']}", "发货", "bad", f"超时未发货：{plat} {o['order_no']}", f"已超 {abs(h):g} 小时", "orders",
                "owner,listing,production", alert=f"⚠️ 超时未发货：{plat} {o['order_no']}（已超 {abs(h):g} 小时）",
                th=(f"เลยเวลาส่ง: {plat} {o['order_no']}", f"เกินมา {abs(h):g} ชั่วโมง"))
        elif h < warn_h:
            add(f"ship:{o['id']}", "发货", "warn", f"{h:g} 小时内要发货：{plat} {o['order_no']}", "", "orders",
                "owner,listing,production", th=(f"ต้องส่งภายใน {h:g} ชั่วโมง: {plat} {o['order_no']}", ""))
    # 售后快到期 / 超期
    for a in c.execute("SELECT a.id, a.due_at, a.kind, o.order_no FROM aftersales a LEFT JOIN orders o ON o.id=a.order_id "
                       "WHERE a.status='open' AND a.due_at IS NOT NULL AND a.due_at < ? AND COALESCE(a.stage,'new') NOT IN "
                       "('refunded','reshipped','rejected','closed')", (now + 12 * 3600,)):
        late = a["due_at"] < now
        add(f"as:{a['id']}:{int(a['due_at'])}", "售后", "bad" if late else "warn",
            f"售后{'已超期' if late else '快到期'}：{a['order_no'] or '#' + str(a['id'])}", "", "aftersales", "owner,listing",
            alert=f"🧾 售后已超期：{a['order_no'] or '#' + str(a['id'])}" if late else None,
            th=(f"หลังการขาย{'เกินกำหนด' if late else 'ใกล้ครบกำหนด'}: {a['order_no'] or '#' + str(a['id'])}", ""))


def _materials(add):
    from . import materials
    day = time.strftime("%Y-%m-%d")
    for m in materials.plan()["rows"]:
        if not (m.get("urgent") or m.get("short")):
            continue
        name = f"{m['material']} {m['color']}"
        if m.get("short"):
            add(f"mat:{name}:{day}", "耗材与价格", "bad", f"耗材不够打待打印的单：{name}", f"剩 {m.get('kg', '?')} kg", "materials",
                "owner,production", alert=f"🧵 耗材已经不够：{name}，剩 {m.get('kg', '?')} kg，请马上补货",
                th=(f"วัสดุไม่พอพิมพ์งานที่รอ: {name}", f"เหลือ {m.get('kg', '?')} kg"))
        else:
            dl = m.get("days_left")
            add(f"mat:{name}:{day}", "耗材与价格", "warn", f"耗材该补货了：{name}", f"约 {dl if dl is not None else '?'} 天用完", "materials",
                "owner,production", alert=f"🧵 耗材要补货：{name}，约 {dl if dl is not None else '?'} 天用完",
                th=(f"ควรสั่งวัสดุเพิ่ม: {name}", f"ใช้หมดในราว {dl if dl is not None else '?'} วัน"))


register("orders", _orders)
register("prod", _materials)
