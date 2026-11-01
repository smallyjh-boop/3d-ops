"""生产单（v2.54）：一张单管一批要生产的成品（SKU + 数量），下达后变成普通的备货打印任务（kind "stock"，jobs.po_id 指向这张单）。

  来源 source   manual 手工 / stock 成品备货补货 / orders 订单汇总（今天所有没开始的订单任务归到一张单）/ campaign 活动
  状态 status   draft 草稿 → released 已下达 → producing 生产中 → partial 部分完成 → done 完成；cancelled 取消
  暂停 paused   整张单暂停：它的任务不再排给打印机（已经在打的那一盘打完）
  专用打印机    po["printers"] = [打印机序号或编号]：这张单的任务只能排给这几台；
               反过来打印机资料里 p["dedicated_po"] = 单号 id 的，只接这张单的任务（见 printer_ok / production.schedule）
  进度         每行 done = 这行所有任务已打好的件数；ETA = 还没打完的任务里最晚的计划结束时间；用料 = 任务已扣的克数
  打完的成品    走原来的备货打印流程：库存管理开了「待检区」就先进待检区，没开直接入库上架（core/production.finish_run）

打印机资料里的这几个字段由别处维护，这里只读，缺了就按默认：p["paused"]（暂停：不接新任务）、p["role"]（any / orders / stock）、
p["dedicated_po"]（专用于哪张单）、p["group"]、p["location"]。
"""
import json
import time

from . import db
from .config import load_config

SOURCES = ("manual", "stock", "orders", "campaign")
SOURCE_ZH = {"manual": "手工", "stock": "成品备货", "orders": "订单汇总", "campaign": "活动"}
SOURCE_TH = {"manual": "สร้างเอง", "stock": "เตรียมสต็อก", "orders": "สรุปออเดอร์", "campaign": "แคมเปญ"}
STATUS_ZH = {"draft": "草稿", "released": "已下达", "producing": "生产中", "partial": "部分完成", "done": "完成", "cancelled": "已取消"}
STATUS_TH = {"draft": "ฉบับร่าง", "released": "สั่งผลิตแล้ว", "producing": "กำลังผลิต", "partial": "เสร็จบางส่วน", "done": "เสร็จสิ้น",
             "cancelled": "ยกเลิก"}
ACTIVE = ("released", "producing", "partial")


def _now():
    return time.time()


def _row(c, po_id):
    r = c.execute("SELECT * FROM production_orders WHERE id=?", (int(po_id),)).fetchone()
    if not r:
        raise ValueError("没有这张生产单")
    return r


def _next_no(c):
    day = time.strftime("%y%m%d")
    n = c.execute("SELECT COUNT(*) FROM production_orders WHERE no LIKE ?", (f"PO{day}-%",)).fetchone()[0] + 1
    while c.execute("SELECT 1 FROM production_orders WHERE no=?", (f"PO{day}-{n:02d}",)).fetchone():
        n += 1
    return f"PO{day}-{n:02d}"


# ---------------- 打印机引用（稳定 id；兼容旧的编号 / 序号） ----------------
MODEL_PREFIX = "model:"


def resolve_printers(refs, prs=None):
    """引用 → 打印机序号列表（认不出来的丢掉）。引用可以是：打印机 id（现在存的）、编号 / 序号（旧数据）、
    "model:机型名"（明确选「这个机型的任一台」，展开成该机型所有打印机）。
    只写机型名的旧写法：这个机型只有一台才认；有几台同名的认不准，丢掉（不再悄悄挑第一台）。"""
    prs = prs if prs is not None else (load_config().get("printers") or [])
    out = []

    def add(i):
        if 0 <= i < len(prs) and i not in out:
            out.append(i)
    for x in refs or []:
        if isinstance(x, int) and not isinstance(x, bool):
            add(x)
            continue
        s = str(x).strip()
        if not s:
            continue
        if s.lower().startswith(MODEL_PREFIX):
            m = s[len(MODEL_PREFIX):].strip().lower()
            for k, p in enumerate(prs):
                if m and (p.get("name") or "").strip().lower() == m:
                    add(k)
            continue
        hit = next((k for k, p in enumerate(prs) if p.get("id") and str(p["id"]) == s), None)
        if hit is None:
            hit = next((k for k, p in enumerate(prs) if (p.get("code") or "").lower() == s.lower()), None)
        if hit is None:
            same = [k for k, p in enumerate(prs) if (p.get("name") or "").lower() == s.lower()]
            if len(same) == 1:
                hit = same[0]
        if hit is None and s.isdigit():
            hit = int(s)
        if hit is not None:
            add(hit)
    return out


def _clean_printers(refs):
    """存的时候：存稳定 id（改编号、调顺序都不会丢）；没有 id 的老配置退回存编号 / 序号；
    "model:机型" 原样存（明确选的「这个机型的任一台」）；只写了有几台同名的机型名 = 当作选了这个机型。"""
    prs = load_config().get("printers") or []
    out = []
    for x in refs or []:
        s = str(x).strip()
        if not isinstance(x, int) and s.lower().startswith(MODEL_PREFIX):
            if not resolve_printers([s], prs):
                raise ValueError("填的打印机找不到")
            v = MODEL_PREFIX + s[len(MODEL_PREFIX):].strip()
            if v not in out:
                out.append(v)
            continue
        idx = resolve_printers([x], prs)
        if not idx and s and not s.isdigit() and any((p.get("name") or "").lower() == s.lower() for p in prs):
            out.append(MODEL_PREFIX + s)
            continue
        for i in idx:
            v = prs[i].get("id") or prs[i].get("code") or i
            if v not in out:
                out.append(v)
    if refs and not out:
        raise ValueError("填的打印机找不到")
    return out


def _migrate_refs(c, prs):
    """旧数据：生产单里存的是编号 / 序号 → 换成稳定 id（认得出的才换；已经是 id / model: 的不动）。"""
    if not any(p.get("id") for p in prs):
        return
    ids = {str(p.get("id")) for p in prs if p.get("id")}
    for r in c.execute("SELECT id, printers FROM production_orders WHERE printers IS NOT NULL AND printers NOT IN ('', '[]')").fetchall():
        try:
            refs = json.loads(r["printers"] or "[]")
        except ValueError:
            continue
        if not refs or all(isinstance(x, str) and (x.lower().startswith(MODEL_PREFIX) or x in ids) for x in refs):
            continue
        new = []
        for x in refs:
            if isinstance(x, str) and (x.lower().startswith(MODEL_PREFIX) or x in ids):
                new.append(x)
                continue
            for i in resolve_printers([x], prs):
                v = prs[i].get("id")
                if v and v not in new:
                    new.append(v)
        if new and new != refs:
            c.execute("UPDATE production_orders SET printers=? WHERE id=?", (json.dumps(new), r["id"]))
    c.commit()


ACTIVE_PO = ("draft", "released", "producing", "partial")


def dedication_status(value, c=None):
    """打印机的「专用生产单」填的值（单 id 或单号）→ {"state": "none"|"active"|"ended"|"missing", "po_id", "no", "status"}。
    ended = 单子已完成 / 取消，missing = 找不到这张单；这两种都当作没有专用（打印机照常接活），界面提醒「专用的生产单已结束」。"""
    d = str(value or "").strip()
    if not d:
        return {"state": "none", "po_id": None, "no": "", "status": ""}
    c = c or db.conn()
    r = c.execute("SELECT id, no, status FROM production_orders WHERE id=?", (int(d),)).fetchone() if d.isdigit() else None
    if r is None:
        r = c.execute("SELECT id, no, status FROM production_orders WHERE no=?", (d,)).fetchone()
    if r is None:
        return {"state": "missing", "po_id": None, "no": d, "status": ""}
    return {"state": "active" if r["status"] in ACTIVE_PO else "ended", "po_id": r["id"], "no": r["no"], "status": r["status"]}


# ---------------- 排单用的规则 ----------------
def rules(printers, c=None):
    """排单（production.schedule）和手动开始用：返回 allowed(打印机序号, 任务) → bool。
    暂停的打印机不接新任务；role orders 只接订单 / 补发、stock 只接备货（试打 / 测试不管 role）；
    p["dedicated_po"] 的打印机只接这张单的任务；单子自己指定了打印机的只能排给这几台；暂停的单子不排。字段缺了 = 不限制。"""
    c = c or db.conn()
    pos = {}
    try:
        _migrate_refs(c, printers)
    except Exception:  # noqa: BLE001  迁移失败不能影响排单
        pass
    for r in c.execute("SELECT id, no, paused, printers, status FROM production_orders"):
        try:
            refs = json.loads(r["printers"] or "[]")
        except ValueError:
            refs = []
        pos[r["id"]] = {"no": r["no"], "paused": bool(r["paused"]) or r["status"] == "cancelled", "idx": set(resolve_printers(refs, printers))}

    def dedicated(p):
        st = dedication_status(p.get("dedicated_po"), c)
        return st["po_id"] if st["state"] == "active" else None   # 专用的单子没了 / 结束了 = 不再专用

    def allowed(i, j):
        p = printers[i]
        if p.get("paused") is True:
            return False
        kind = (j["kind"] if "kind" in j.keys() else "order") or "order"
        role = str(p.get("role") or "any").lower()
        if kind in ("order", "reship") and role == "stock":
            return False
        if kind == "stock" and role == "orders":
            return False
        poid = (j["po_id"] if "po_id" in j.keys() else None) or None
        d = dedicated(p)
        if d is not None and d != poid:
            return False
        if poid:
            rec = pos.get(poid)
            if rec and (rec["paused"] or (rec["idx"] and i not in rec["idx"])):
                return False
        return True
    return allowed


def check_printer(j, idx):
    """手动开始打印时再核对一次：暂停的打印机、别的单专用的打印机、这张单没指定的打印机、暂停的单子都不行。"""
    prs = load_config().get("printers") or []
    if not (0 <= idx < len(prs)) or (j.get("kind") or "order") in ("trial", "test"):
        return
    names = prs[idx].get("name") or idx
    if prs[idx].get("paused") is True:
        raise ValueError(f"「{names}」已暂停，不接新任务（打印机页恢复后再用）")
    c = db.conn()
    allowed = rules(prs, c)
    if allowed(idx, j):
        return
    poid = j.get("po_id")
    if poid:
        r = c.execute("SELECT no, paused, printers FROM production_orders WHERE id=?", (poid,)).fetchone()
        if r and r["paused"]:
            raise ValueError(f"生产单 {r['no']} 已暂停，先恢复它")
        if r and resolve_printers(json.loads(r["printers"] or "[]"), prs) and idx not in resolve_printers(json.loads(r["printers"] or "[]"), prs):
            raise ValueError(f"生产单 {r['no']} 只能用它指定的打印机")
    d = str(prs[idx].get("dedicated_po") or "").strip()
    if d:
        raise ValueError(f"「{names}」专用于生产单 {d}，只接那张单的任务")
    raise ValueError(f"「{names}」的用途（{prs[idx].get('role')}）不接这类任务")


# ---------------- 建单 / 编辑 ----------------
def _lines_in(lines):
    """[{sku, qty}] → 合并同 SKU、对上产品库的行（找不到 SKU 的报错）。"""
    from . import orders, store
    if not lines:
        raise ValueError("请选择要生产的 SKU")
    idx = orders.sku_index()
    out, errs = {}, []
    for it in lines:
        sku = str(it.get("sku") or "").strip().upper()
        if not sku:
            continue
        try:
            q = int(float(it.get("qty") or 0))
        except (TypeError, ValueError):
            q = 0
        if q <= 0:
            errs.append(f"{sku}：数量要大于 0")
            continue
        hit = orders.match_sku(sku, idx)
        if not hit:
            errs.append(f"{sku}：产品库里找不到这个 SKU")
            continue
        if sku in out:
            out[sku]["qty"] += q
            continue
        info = orders._variant_info(*hit) or {}
        try:
            name = store.load(hit[0]).get("name_zh") or info.get("name") or ""
        except Exception:  # noqa: BLE001
            name = info.get("name") or ""
        out[sku] = {"sku": sku, "product_id": hit[0], "name": name, "color": info.get("color") or "", "qty": q}
    if not out:
        raise ValueError("；".join(errs) or "没有可生产的 SKU")
    return list(out.values()), errs


def create(lines, source="manual", user="", priority=0, due=None, note="", printers=None, release=False, kind_note=""):
    """建一张草稿生产单；release=True 马上下达。返回 get(id)（带 errors：没对上的行）。"""
    ls, errs = _lines_in(lines)
    if source not in SOURCES:
        source = "manual"
    c = db.conn()
    now = _now()
    prs = _clean_printers(printers) if printers else []
    pid = c.execute("INSERT INTO production_orders(no, source, status, priority, due, note, printers, paused, created_at, created_by, updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (_next_no(c), source, "draft", 1 if int(priority or 0) else 0, _due(due), note or "", json.dumps(prs), 0, now, user, now)).lastrowid
    for ln in ls:
        c.execute("INSERT INTO po_lines(po_id, sku, product_id, name, color, qty, done) VALUES(?,?,?,?,?,?,0)",
                  (pid, ln["sku"], ln["product_id"], ln["name"], ln["color"], ln["qty"]))
    c.commit()
    db.audit(user, "新建生产单", _row(c, pid)["no"], f"来源 {SOURCE_ZH.get(source)}；{len(ls)} 个 SKU")
    if release:
        return release_po(pid, user, errors=errs)
    out = get(pid)
    out["errors"] = errs
    return out


def _due(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return time.mktime(time.strptime(str(v)[:10], "%Y-%m-%d")) + 86399
    except ValueError:
        raise ValueError("交期格式不对（要 2026-11-05）")


def update(po_id, fields, user=""):
    """改单子：草稿可以改行（lines 整体替换）；已下达的只能改备注 / 优先级 / 交期 / 专用打印机。"""
    c = db.conn()
    r = _row(c, po_id)
    if r["status"] in ("done", "cancelled"):
        raise ValueError("这张单已经结束了")
    sets, args = ["updated_at=?"], [_now()]
    if "note" in fields:
        sets.append("note=?"); args.append(fields.get("note") or "")
    if "due" in fields:
        sets.append("due=?"); args.append(_due(fields.get("due")))
    if "priority" in fields:
        sets.append("priority=?"); args.append(1 if int(fields.get("priority") or 0) else 0)
    if "printers" in fields:
        sets.append("printers=?"); args.append(json.dumps(_clean_printers(fields.get("printers") or [])))
    if fields.get("lines") is not None:
        if r["status"] != "draft":
            raise ValueError("已经下达的单不能改 SKU 和数量（取消它再新建，或者另开一张）")
        ls, _errs = _lines_in(fields["lines"])
        c.execute("DELETE FROM po_lines WHERE po_id=?", (po_id,))
        for ln in ls:
            c.execute("INSERT INTO po_lines(po_id, sku, product_id, name, color, qty, done) VALUES(?,?,?,?,?,?,0)",
                      (po_id, ln["sku"], ln["product_id"], ln["name"], ln["color"], ln["qty"]))
    c.execute(f"UPDATE production_orders SET {', '.join(sets)} WHERE id=?", (*args, po_id))
    if "priority" in fields:
        c.execute("UPDATE jobs SET priority_job=? WHERE po_id=? AND status IN ('todo','printing')", (1 if int(fields.get("priority") or 0) else 0, po_id))
    c.commit()
    if "printers" in fields or "priority" in fields:
        from . import production
        production.schedule()
    return get(po_id)


# ---------------- 下达 / 暂停 / 取消 ----------------
def release_po(po_id, user="", errors=None, pin=None):
    """下达：每一行建一个备货任务（多盘 / 多色照旧，由排单按各盘安排）。"""
    from . import production
    c = db.conn()
    r = _row(c, po_id)
    if r["status"] != "draft":
        raise ValueError("只有草稿可以下达")
    lines = c.execute("SELECT * FROM po_lines WHERE po_id=? ORDER BY id", (po_id,)).fetchall()
    if not lines:
        raise ValueError("这张单没有 SKU")
    note = f"生产单 {r['no']}" + (f" · {r['note']}" if r["note"] else "")
    made = []
    try:
        for ln in lines:
            j = production.create_job(ln["product_id"], ln["sku"], ln["qty"], "stock", None, user, note, priority=r["priority"],
                                      po_id=po_id, schedule_now=False, printer=pin)
            made.append(j["id"])
            c.execute("UPDATE po_lines SET job_id=? WHERE id=?", (j["id"], ln["id"]))
    except Exception:
        for jid in made:                         # 中途出错：已建的任务撤回，单子还是草稿
            c.execute("DELETE FROM jobs WHERE id=?", (jid,))
            c.execute("DELETE FROM job_plates WHERE job_id=?", (jid,))
        c.execute("UPDATE po_lines SET job_id=NULL WHERE po_id=?", (po_id,))
        c.commit()
        raise
    c.execute("UPDATE production_orders SET status='released', released_at=?, updated_at=? WHERE id=?", (_now(), _now(), po_id))
    c.commit()
    db.audit(user, "下达生产单", r["no"], f"{len(made)} 个任务")
    production.schedule()
    out = get(po_id)
    if errors:
        out["errors"] = errors
    return out


def pause(po_id, on=True, user=""):
    from . import production
    c = db.conn()
    r = _row(c, po_id)
    if r["status"] not in ACTIVE and r["status"] != "draft":
        raise ValueError("这张单已经结束了")
    c.execute("UPDATE production_orders SET paused=?, updated_at=? WHERE id=?", (1 if on else 0, _now(), po_id))
    c.commit()
    db.audit(user, "暂停生产单" if on else "恢复生产单", r["no"])
    production.schedule()
    return get(po_id)


def cancel(po_id, user=""):
    """取消整张单：还没开始打的任务删掉（已经打好进库存的不动）；有一盘正在打就先不让取消。"""
    from . import production
    c = db.conn()
    r = _row(c, po_id)
    if r["status"] in ("done", "cancelled"):
        raise ValueError("这张单已经结束了")
    jobs = c.execute("SELECT * FROM jobs WHERE po_id=?", (po_id,)).fetchall()
    for j in jobs:
        if j["run_id"] and (j["kind"] or "") == "stock":
            raise ValueError(f"任务 #{j['id']} 有一盘正在打，先在生产看板结束这一盘再取消")
    for j in jobs:
        if (j["kind"] or "") == "stock":
            c.execute("DELETE FROM jobs WHERE id=?", (j["id"],))
            c.execute("DELETE FROM job_plates WHERE job_id=?", (j["id"],))
        else:
            c.execute("UPDATE jobs SET po_id=NULL WHERE id=?", (j["id"],))        # 订单汇总单：订单任务放回去，照常生产
    c.execute("UPDATE production_orders SET status='cancelled', paused=0, done_at=?, updated_at=? WHERE id=?", (_now(), _now(), po_id))
    c.commit()
    db.audit(user, "取消生产单", r["no"])
    production.schedule()
    return get(po_id)


def on_job_deleted(job_id, po_id, user=""):
    """备货任务被单独删了：对应的行去掉；单子没有任务了就算取消。"""
    if not po_id:
        return
    c = db.conn()
    c.execute("DELETE FROM po_lines WHERE job_id=?", (job_id,))
    if not c.execute("SELECT 1 FROM po_lines WHERE po_id=?", (po_id,)).fetchone() and not c.execute("SELECT 1 FROM jobs WHERE po_id=?", (po_id,)).fetchone():
        c.execute("UPDATE production_orders SET status='cancelled', done_at=?, updated_at=? WHERE id=? AND status!='done'", (_now(), _now(), po_id))
    c.commit()


# ---------------- 订单汇总 ----------------
def from_orders(user="", scope="today", priority=0, note=""):
    """把「今天」所有还没开始的订单任务归到一张生产单（scope=all 是所有没开始的）。订单任务本身不变，只是挂上单号方便一起看进度。"""
    c = db.conn()
    t0 = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
    sql = ("SELECT j.* FROM jobs j JOIN orders o ON o.id=j.order_id WHERE j.kind IN ('order','reship') AND j.status='todo' AND j.po_id IS NULL "
           "AND o.status IN ('to_ship','other')")
    args = []
    if scope != "all":
        sql += " AND (j.created_at>=? OR COALESCE(o.ship_by, 9e12)<=?)"
        args = [t0, t0 + 86400 + 86399]
    jobs = c.execute(sql, args).fetchall()
    if not jobs:
        raise ValueError("今天没有还没开始的订单任务")
    now = _now()
    pid = c.execute("INSERT INTO production_orders(no, source, status, priority, note, printers, paused, created_at, created_by, updated_at, released_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (_next_no(c), "orders", "released", 1 if priority else 0, note or "订单汇总", "[]", 0, now, user, now, now)).lastrowid
    agg = {}
    for j in jobs:
        a = agg.setdefault((j["sku"] or "").upper(), {"product_id": j["product_id"], "name": j["name"], "color": j["color"], "qty": 0})
        a["qty"] += int(j["qty"] or 0)
        c.execute("UPDATE jobs SET po_id=? WHERE id=?", (pid, j["id"]))
    for sku, a in agg.items():
        c.execute("INSERT INTO po_lines(po_id, sku, product_id, name, color, qty, done) VALUES(?,?,?,?,?,?,0)",
                  (pid, sku, a["product_id"], a["name"], a["color"], a["qty"]))
    c.commit()
    db.audit(user, "订单汇总生产单", _row(c, pid)["no"], f"{len(jobs)} 个订单任务")
    return get(pid)


# ---------------- 进度 ----------------
def _unit_cost(sku, product_id):
    try:
        from .inventory import goods
        return goods._unit_cost(sku, product_id) or 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def _detail(c, r):
    """一张单的完整状态（不写库）。"""
    po = dict(r)
    try:
        po["printers"] = json.loads(po.get("printers") or "[]")
    except ValueError:
        po["printers"] = []
    po["printer_idx"] = resolve_printers(po["printers"])
    po["paused"] = bool(po["paused"])
    jobs = [dict(j) for j in c.execute("SELECT * FROM jobs WHERE po_id=?", (po["id"],))]
    lines = []
    qty = done = 0
    grams = cost = 0.0
    eta = None
    active_run = False
    started = False
    for ln in c.execute("SELECT * FROM po_lines WHERE po_id=? ORDER BY id", (po["id"],)):
        d = dict(ln)
        js = [j for j in jobs if (j["sku"] or "").upper() == d["sku"].upper()] if po["source"] == "orders" else [j for j in jobs if j["id"] == d["job_id"]]
        d["done"] = min(d["qty"], sum(int(j["qty_done"] or 0) for j in js)) if js else (d["done"] or 0)
        d["grams"] = round(sum(float(j["consumed_g"] or 0) for j in js), 1)
        d["printing"] = any(j["run_id"] for j in js)
        d["job_ids"] = [j["id"] for j in js]
        d["status"] = "done" if d["done"] >= d["qty"] else ("printing" if d["printing"] else ("todo" if js else "draft"))
        ends = [j["planned_end"] for j in js if j["planned_end"] and j["status"] in ("todo", "printing")]
        d["eta"] = max(ends) if ends else None
        d["cost"] = round(_unit_cost(d["sku"], d["product_id"]) * d["done"], 2)
        d["pct"] = round(100 * d["done"] / d["qty"]) if d["qty"] else 0
        if d["eta"]:
            eta = max(eta or 0, d["eta"])
        active_run = active_run or d["printing"]
        started = started or any(int(j["plates_done"] or 0) > 0 for j in js)
        grams += d["grams"]
        cost += d["cost"]
        qty += d["qty"]
        done += d["done"]
        lines.append(d)
    po["lines"] = lines
    po["qty"], po["done"] = qty, done
    po["pct"] = round(100 * done / qty) if qty else 0
    po["grams"], po["cost"], po["eta"] = round(grams, 1), round(cost, 2), eta
    po["late"] = bool(po.get("due") and eta and eta > po["due"] and po["status"] in ACTIVE)
    po["_active_run"], po["_started"] = active_run, started
    po["status_zh"] = STATUS_ZH.get(po["status"], po["status"])
    po["status_th"] = STATUS_TH.get(po["status"], po["status"])
    po["source_zh"] = SOURCE_ZH.get(po["source"], po["source"])
    po["source_th"] = SOURCE_TH.get(po["source"], po["source"])
    return po


def _derive(po):
    if po["status"] in ("draft", "cancelled"):
        return po["status"]
    if po["qty"] and po["done"] >= po["qty"]:
        return "done"
    if po["_active_run"]:
        return "producing"
    if po["done"] > 0:
        return "partial"
    if po["_started"]:
        return "producing"
    return "released"


def refresh(po_id, c=None):
    """按任务的进度更新单子的状态（打完一盘、开始一盘、任务被删之后都会调）。"""
    c = c or db.conn()
    r = c.execute("SELECT * FROM production_orders WHERE id=?", (po_id,)).fetchone()
    if not r or r["status"] in ("draft", "cancelled", "done"):
        return
    po = _detail(c, r)
    st = _derive(po)
    if st != r["status"]:
        c.execute("UPDATE production_orders SET status=?, done_at=CASE WHEN ?='done' THEN ? ELSE done_at END, updated_at=? WHERE id=?",
                  (st, st, _now(), _now(), po_id))
        c.commit()
        if st == "done":
            db.audit("系统", "生产单完成", r["no"], f"{po['done']}/{po['qty']}")
            try:
                from . import modules
                modules.emit("po.done", po_id=po_id, no=r["no"])
            except Exception:  # noqa: BLE001
                pass


def sync():
    """排单之后顺手把所有进行中的单子的状态对一遍。"""
    try:
        c = db.conn()
        for r in c.execute("SELECT id FROM production_orders WHERE status IN ('released','producing','partial')").fetchall():
            refresh(r["id"], c)
    except Exception:  # noqa: BLE001  状态对不上不能影响排单
        import logging
        logging.getLogger("3dops").warning("生产单状态没更新", exc_info=True)


def warnings(po):
    """这张单指定的 / 专用的打印机打不了它的东西 → 提醒（机型不对、没有多色、没有这个机型的切片文件）。"""
    from . import fleet, print_files, production
    prs = load_config().get("printers") or []
    dedicated = {i for i, p in enumerate(prs) if str(p.get("dedicated_po") or "").strip() in (str(po["id"]), po["no"])}
    idx = sorted(set(po.get("printer_idx") or []) | dedicated)
    out = []
    for i in idx:
        p = prs[i]
        label = p.get("code") or p.get("name") or f"#{i + 1}"
        if p.get("paused") is True:
            out.append({"printer": i, "code": "paused", "zh": f"打印机 {label} 已暂停，不会接这张单的任务", "th": f"เครื่อง {label} หยุดชั่วคราว จะไม่รับงานของใบสั่งนี้"})
        for ln in po["lines"]:
            if ln["status"] == "done":
                continue
            try:
                from . import orders
                info = orders._variant_info(ln["product_id"], (orders.sku_index().get(ln["sku"].upper()) or (0, 0))[1]) or {}
            except Exception:  # noqa: BLE001
                info = {}
            mat = info.get("material") or "PLA"
            if fleet.tech_of(p) != fleet.job_tech(mat):
                out.append({"printer": i, "sku": ln["sku"], "code": "tech", "zh": f"{label} 打不了 {ln['sku']}（{mat} 和这台的打印方式不同）",
                            "th": f"{label} พิมพ์ {ln['sku']} ไม่ได้ ({mat} ไม่ตรงกับชนิดเครื่อง)"})
                continue
            cols = production.job_colours(ln["product_id"], ln["sku"], ln["color"])
            if production.needs_multicolor(cols) and not fleet.is_multicolor(p):
                out.append({"printer": i, "sku": ln["sku"], "code": "ams", "zh": f"{label} 没有 AMS / 多色，打不了 {ln['sku']}（多色）",
                            "th": f"{label} ไม่มี AMS / หลายสี พิมพ์ {ln['sku']} (หลายสี) ไม่ได้"})
                continue
            if not fleet.is_resin(mat):
                pl = print_files.plan({"product_id": ln["product_id"], "sku": ln["sku"], "color": ln["color"], "qty": ln["qty"], "qty_done": 0,
                                       "material": mat}, p.get("name") or "")
                if not pl.get("file"):
                    out.append({"printer": i, "sku": ln["sku"], "code": "nofile", "zh": f"{label} 这个机型没有 {ln['sku']} 的切片文件（要先切片）",
                                "th": f"ไม่มีไฟล์สไลซ์ของ {ln['sku']} สำหรับรุ่น {label} (ต้องสไลซ์ก่อน)"})
    return out


def get(po_id):
    c = db.conn()
    r = _row(c, po_id)
    po = _detail(c, r)
    if r["status"] in ACTIVE:
        st = _derive(po)
        if st != r["status"]:
            refresh(po_id, c)
            po = _detail(c, _row(c, po_id))
    po["warnings"] = warnings(po) if (po["printer_idx"] or _has_dedicated(po)) and po["status"] != "cancelled" else []
    po.pop("_active_run", None)
    po.pop("_started", None)
    return po


def _has_dedicated(po):
    return any(str(p.get("dedicated_po") or "").strip() in (str(po["id"]), po["no"]) for p in (load_config().get("printers") or []))


def listing(status="", q=""):
    """列表：每张单的汇总（不带行）。status：active（进行中）/ 具体状态 / 空 = 全部。"""
    c = db.conn()
    rows = c.execute("SELECT * FROM production_orders ORDER BY CASE WHEN status IN ('released','producing','partial') THEN 0 WHEN status='draft' THEN 1 ELSE 2 END, id DESC").fetchall()
    out = []
    for r in rows:
        if status == "active" and r["status"] not in ACTIVE:
            continue
        if status and status != "active" and r["status"] != status:
            continue
        po = _detail(c, r)
        if r["status"] in ACTIVE and _derive(po) != r["status"]:
            refresh(r["id"], c)
            po = _detail(c, _row(c, r["id"]))
        if q and q.lower() not in (po["no"] + " " + (po["note"] or "") + " ".join(ln["sku"] for ln in po["lines"])).lower():
            continue
        po.pop("_active_run", None)
        po.pop("_started", None)
        po["n_lines"] = len(po["lines"])
        out.append(po)
    return out


def counts():
    c = db.conn()
    d = {}
    for r in c.execute("SELECT status, COUNT(*) n FROM production_orders GROUP BY status"):
        d[r["status"]] = r["n"]
    d["paused"] = c.execute("SELECT COUNT(*) FROM production_orders WHERE paused=1 AND status IN ('draft','released','producing','partial')").fetchone()[0]
    return d


def lane_info(po_ids):
    """看板用：{po_id: {no, status}}。"""
    ids = [i for i in set(po_ids) if i]
    if not ids:
        return {}
    c = db.conn()
    return {r["id"]: {"id": r["id"], "no": r["no"], "status": r["status"], "paused": bool(r["paused"])}
            for r in c.execute(f"SELECT id, no, status, paused FROM production_orders WHERE id IN ({','.join('?' * len(ids))})", ids)}


def sheet_html(po_id, lang="zh"):
    """可打印的生产单（A4）：单号二维码、每行 SKU / 颜色 / 数量 / 勾选框。"""
    from html import escape as h
    from modules.inv import qr as _qr
    po = get(po_id)
    th = lang == "th"
    T = (lambda zh, t: t if th else zh)
    rows = "".join(f"<tr><td class='m'>{h(ln['sku'])}</td><td>{h(ln['name'] or '')} {h(ln['color'] or '')}</td><td class='n'>{ln['qty']}</td>"
                   f"<td class='n'>{ln['done']}</td><td class='box'></td></tr>" for ln in po["lines"])
    due = time.strftime("%Y-%m-%d", time.localtime(po["due"])) if po.get("due") else "-"
    css = ("body{font:13px 'Leelawadee UI',Tahoma,'Microsoft YaHei',sans-serif;margin:14mm}h1{margin:0 0 4px;font-size:22px}.top{display:flex;justify-content:space-between;gap:16px}"
           "table{width:100%;border-collapse:collapse;margin-top:12px}td,th{border:1px solid #444;padding:6px 8px;text-align:left}.n{text-align:right;width:70px}"
           ".m{font-family:monospace;font-weight:700}.box{width:44px}@media print{.np{display:none}}")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{h(po['no'])}</title><style>{css}</style></head><body>"
            f"<p class='np'><button onclick='print()'>{T('打印', 'พิมพ์')}</button></p>"
            f"<div class='top'><div><h1>{T('生产单', 'ใบสั่งผลิต')} {h(po['no'])}</h1>"
            f"<div>{T('来源', 'ที่มา')}：{h((SOURCE_TH if th else SOURCE_ZH).get(po['source'], ''))} · {T('状态', 'สถานะ')}：{h((STATUS_TH if th else STATUS_ZH).get(po['status'], ''))}"
            f"{' · ' + T('加急', 'ด่วน') if po['priority'] else ''}</div>"
            f"<div>{T('交期', 'กำหนดส่ง')}：{due} · {T('共', 'รวม')} {po['qty']} {T('件', 'ชิ้น')}</div>"
            f"{'<div>' + h(po['note']) + '</div>' if po.get('note') else ''}</div>"
            f"<div>{_qr.svg(po['no'], 28)}</div></div>"
            f"<table><thead><tr><th>SKU</th><th>{T('商品', 'สินค้า')}</th><th>{T('数量', 'จำนวน')}</th><th>{T('已完成', 'เสร็จแล้ว')}</th><th>✓</th></tr></thead><tbody>{rows}</tbody></table>"
            f"</body></html>")
