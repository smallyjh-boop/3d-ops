"""售后、自动备份、产品分组、工作台。"""
import datetime as dt
import os
import shutil
import threading
import time
import zipfile

from . import db
from .config import DATA_DIR, load_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS aftersales (
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, kind TEXT, reason TEXT, amount REAL, note TEXT,
  status TEXT DEFAULT 'open', created_at REAL, closed_at REAL, username TEXT, job_ids TEXT
);
CREATE INDEX IF NOT EXISTS as_order ON aftersales(order_id);
CREATE TABLE IF NOT EXISTS product_groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, sort INTEGER DEFAULT 0
);
"""
AS_KIND = {"refund": "退款", "reship": "补发", "return": "退货退款", "partial": "部分退款", "cod_reject": "拒收/派送失败退回",
           "other": "其他"}
AS_REASONS = ["打印质量问题", "尺寸不对 / 装不上", "颜色不对", "发错 / 漏发", "运输损坏", "买家不想要了", "迟发 / 超时",
              "拒收 / 派送失败", "其他"]
# 售后流程（阶段）。最后四个是「处理完了」
AS_STAGE = {"new": "待处理", "wait_return": "等买家寄回", "wait_platform": "等平台判定", "received": "已收到待验货",
            "refunded": "已退款", "reshipped": "已补发", "rejected": "已拒绝", "closed": "已关闭"}
AS_DONE = ("refunded", "reshipped", "rejected", "closed")
AS_RESP = {"": "未判定", "production": "生产（打印质量）", "packing": "打包（发错/漏发/包装）", "logistics": "物流（损坏/丢件）",
           "buyer": "买家原因", "platform": "平台原因", "design": "产品设计 / 描述"}
AS_LOSS = ("amount", "reship_cost", "return_shipping", "penalty", "scrap_cost")
AS_COLS = (("stage", "TEXT"), ("due_at", "REAL"), ("evidence", "TEXT"), ("responsibility", "TEXT"), ("staff", "TEXT"),
           ("printer_codes", "TEXT"), ("print_files", "TEXT"), ("reship_cost", "REAL"), ("return_shipping", "REAL"),
           ("penalty", "REAL"), ("scrap_cost", "REAL"), ("return_tracking", "TEXT"), ("inspect_result", "TEXT"),
           ("inspect_note", "TEXT"), ("inspect_items", "TEXT"), ("inspected_at", "REAL"), ("inspected_by", "TEXT"),
           ("updated_at", "REAL"))
EVID_DIR = os.path.join(DATA_DIR, "aftersales")
EVID_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".mp4", ".mov", ".webm", ".m4v", ".pdf")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
KEEP_BACKUPS = 30


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.execute("CREATE TABLE IF NOT EXISTS as_log (id INTEGER PRIMARY KEY AUTOINCREMENT, as_id INTEGER, ts REAL, username TEXT, "
              "action TEXT, detail TEXT)")
    cols = {r[1] for r in c.execute("PRAGMA table_info(aftersales)")}
    for col, typ in AS_COLS:
        if col not in cols:
            c.execute(f"ALTER TABLE aftersales ADD COLUMN {col} {typ}")
    c.execute("UPDATE aftersales SET stage=CASE WHEN status='closed' THEN 'closed' ELSE 'new' END WHERE stage IS NULL")
    c.commit()


# ---------------- 售后 ----------------
import json  # noqa: E402


def _aslog(aid, user, action, detail="", commit=True):
    c = db.conn()
    c.execute("INSERT INTO as_log(as_id, ts, username, action, detail) VALUES(?,?,?,?,?)",
              (aid, time.time(), user or "", action, (detail or "")[:500]))
    if commit:
        c.commit()


def _iid(it):
    """补发 / 退货行里的订单商品 id；乱填 → 清楚的错误（v2.40 复审）。"""
    try:
        return int((it or {}).get("item_id") or 0)
    except (TypeError, ValueError, AttributeError):
        raise ValueError("要补发 / 退货的商品不对，请重新选择")


def _f(v, allow_neg=False):
    try:
        x = float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError(f"金额「{v}」要填数字")
    if x is not None and (x != x or x in (float("inf"), float("-inf"))):
        raise ValueError(f"金额「{v}」要填数字")
    if x is not None and x < 0 and not allow_neg:      # v2.40：退款等不能是负数（「平台罚款 / 赔付」可以负数＝平台赔给我们）
        raise ValueError(f"金额「{v}」不能是负数")
    return x


def _items_cost(rows):
    """估算这些商品的生产成本（材料 + 机时 + 包材 + 损耗），用于补发成本 / 报废损失。"""
    from . import finance
    if not rows:
        return 0.0
    pr = finance.order_profit(load_config(), {"order_total": 0, "platform": "manual", "platform_fee": 0}, rows)
    return round(pr["cost"], 2)


def _trace(order_id):
    """这个订单是哪台打印机、哪个切片文件打的（自动填到售后里，方便追责和改进）。"""
    c = db.conn()
    cfg = load_config()
    prs = cfg.get("printers") or []
    codes, files = [], []
    jids = [r[0] for r in c.execute("SELECT id FROM jobs WHERE order_id=?", (order_id,))]
    if not jids:
        return "", ""
    for r in c.execute("SELECT printer, file_id, alloc FROM print_runs WHERE COALESCE(alloc,'')!='' ORDER BY id"):
        try:
            alloc = json.loads(r["alloc"] or "{}")
        except ValueError:
            continue
        if not any(str(j) in alloc for j in jids):
            continue
        i = r["printer"]
        if i is not None and 0 <= i < len(prs):
            codes.append(prs[i].get("code") or f"#{i + 1}")
        if r["file_id"]:
            f = c.execute("SELECT filename, version FROM print_files WHERE id=?", (r["file_id"],)).fetchone()
            if f:
                files.append(f"{f['filename']} v{f['version'] or 1}")
    return ", ".join(dict.fromkeys(codes)), ", ".join(dict.fromkeys(files))


def _default_stage(kind):
    return {"return": "wait_return", "cod_reject": "wait_return"}.get(kind, "new")


def _default_due(stage):
    cfg = load_config()
    if stage == "wait_return":
        return time.time() + float(cfg.get("as_return_days") or 14) * 86400
    return time.time() + float(cfg.get("as_due_hours") or 48) * 3600


def as_add(order_id, kind, reason, amount=None, note="", user="", reship_items=None, stage=None, due_at=None,
           responsibility="", staff="", return_tracking="", return_shipping=None, penalty=None):
    """登记售后。补发：按选的商品和数量生成补发生产任务，并估算补发成本。"""
    from . import orders, production
    c = db.conn()
    o = orders.get_order(order_id)
    if not o:
        raise ValueError("订单不存在")
    if kind not in AS_KIND:
        raise ValueError("售后类型不对")
    if responsibility and responsibility not in AS_RESP:
        raise ValueError("责任方不对")
    _f(amount), _f(return_shipping), _f(penalty, True)       # v2.40：先检查，免得补发任务建了一半才报错
    jobs, cost_rows = [], []
    if kind == "reship":
        done = {r[0]: r[1] for r in c.execute("SELECT UPPER(sku), SUM(qty) FROM jobs WHERE order_id=? AND kind='reship' GROUP BY UPPER(sku)",
                                                  (order_id,))}
        # v2.40：补发（几次加起来、同一次里几行同 SKU 加起来）不能比原来这个 SKU 买的多（先全部检查，再建任务）
        bought, want = {}, {}
        for i in o["items"]:
            k = (i.get("sku") or "").upper()
            bought[k] = bought.get(k, 0) + int(i.get("qty") or 1)
        for it in reship_items or []:
            item = next((i for i in o["items"] if i["id"] == _iid(it)), None)
            if not item:
                continue
            try:
                q = int(it.get("qty") or 0)
            except (TypeError, ValueError):
                raise ValueError("补发数量要填数字")
            k = (item.get("sku") or "").upper()
            want[k] = want.get(k, 0) + max(q, 0)
        for k, q in want.items():
            before = int(done.get(k) or 0)
            if q + before > bought.get(k, 0):
                raise ValueError(f"{k} 原订单只有 {bought.get(k, 0)} 个，补发数量不能比这个多"
                                 + (f"（之前已经补发过 {before} 个）" if before else ""))
        for it in reship_items or []:
            item = next((i for i in o["items"] if i["id"] == _iid(it)), None)
            q = int(it.get("qty") or 0)
            if item and q > 0 and item.get("product_id"):
                j = production.create_job(item["product_id"], item["sku"], q, "reship", order_id, user, f"补发：{reason}")
                jobs.append(j["id"])
                cost_rows.append({**item, "qty": q})
        if not jobs:
            raise ValueError("请选择要补发的商品和数量")
    stage = stage if stage in AS_STAGE else _default_stage(kind)
    due = orders._time(due_at) if due_at else _default_due(stage)
    pcodes, pfiles = _trace(order_id)
    now = time.time()
    aid = c.execute("INSERT INTO aftersales(order_id, kind, reason, amount, note, status, created_at, username, job_ids, stage, due_at, "
                    "responsibility, staff, printer_codes, print_files, reship_cost, return_tracking, return_shipping, penalty, "
                    "evidence, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (order_id, kind, reason, _f(amount), note, "closed" if stage in AS_DONE else "open", now, user,
                     ",".join(map(str, jobs)), stage, due, responsibility or "", staff or "", pcodes, pfiles,
                     _items_cost(cost_rows) if cost_rows else None, return_tracking or "", _f(return_shipping), _f(penalty, True),
                     "[]", now)).lastrowid
    c.commit()
    _aslog(aid, user, "登记", f"{AS_KIND.get(kind, kind)} · {reason} · {AS_STAGE[stage]}")
    orders.log(order_id, user, f"售后：{AS_KIND.get(kind, kind)}", f"{reason} {note}".strip())
    return aid


def as_auto_reject(order_id, user=""):
    """订单变成「拒收/派送失败」：自动登记一条售后，等包裹退回来验货（同一订单不重复登记）。"""
    c = db.conn()
    if c.execute("SELECT 1 FROM aftersales WHERE order_id=? AND kind='cod_reject'", (order_id,)).fetchone():
        return None
    return as_add(order_id, "cod_reject", "拒收 / 派送失败", None, "自动登记：包裹退回来后请验货（能卖的入库，坏的报废）",
                  user or "系统", responsibility="buyer")


AS_EDIT = ("kind", "reason", "note", "stage", "due_at", "responsibility", "staff", "printer_codes", "print_files", "return_tracking",
           "amount", "reship_cost", "return_shipping", "penalty", "scrap_cost")
AS_EDIT_ZH = {"kind": "类型", "reason": "原因", "note": "说明", "stage": "阶段", "due_at": "处理期限", "responsibility": "责任",
              "staff": "经手人", "printer_codes": "打印机", "print_files": "切片文件", "return_tracking": "退回运单号",
              "amount": "退款金额", "reship_cost": "补发成本", "return_shipping": "退回运费", "penalty": "平台罚款/赔付",
              "scrap_cost": "报废损失"}


def as_update(aid, data, user="", owner=True):
    from . import orders
    c = db.conn()
    old = c.execute("SELECT * FROM aftersales WHERE id=?", (aid,)).fetchone()
    if not old:
        raise ValueError("售后记录不存在")
    sets = {}
    for k in AS_EDIT:
        if k not in data:
            continue
        if k in AS_LOSS and not owner:
            continue
        v = data[k]
        if k in AS_LOSS:
            try:
                v = _f(v, k == "penalty")
            except ValueError:
                # 以前存进去的负数：页面整张提交时值没变 → 照旧保存，不卡住这条记录
                try:
                    same = old[k] is not None and v not in (None, "") and abs(float(v) - float(old[k])) < 1e-9
                except (TypeError, ValueError):
                    raise ValueError(f"金额「{v}」要填数字")
                if same:
                    v = float(old[k])
                else:
                    raise
        elif k == "due_at":
            v = orders._time(v) if v else None
        elif k == "stage" and v not in AS_STAGE:
            raise ValueError("阶段不对")
        elif k == "kind" and v not in AS_KIND:
            raise ValueError("售后类型不对")
        elif k == "responsibility" and v not in AS_RESP:
            raise ValueError("责任方不对")
        else:
            v = str(v or "")[:500]
        ov = old[k]
        if (v if v not in ("",) else None) == (ov if ov not in ("",) else None):
            continue
        if isinstance(v, float) and isinstance(ov, (int, float)) and abs(v - ov) < (61 if k == "due_at" else 1e-9):
            continue
        sets[k] = v
    if not sets:
        return as_get(aid)
    now = time.time()
    if "stage" in sets:
        st = sets["stage"]
        sets["status"] = "closed" if st in AS_DONE else "open"
        sets["closed_at"] = now if st in AS_DONE else None
        if st not in AS_DONE and "due_at" not in sets and st != old["stage"]:
            sets["due_at"] = _default_due(st)
    sets["updated_at"] = now
    c.execute(f"UPDATE aftersales SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), aid))
    for k, v in sets.items():
        if k in ("status", "closed_at", "updated_at"):
            continue
        if k == "stage":
            _aslog(aid, user, "阶段", f"{AS_STAGE.get(old['stage'], old['stage'])} → {AS_STAGE[v]}", commit=False)
            orders.log(old["order_id"], user, "售后进度", AS_STAGE[v], commit=False)
        elif k == "due_at":
            _aslog(aid, user, AS_EDIT_ZH[k], dt.datetime.fromtimestamp(v).strftime("%Y-%m-%d %H:%M") if v else "（空）", commit=False)
        elif k == "responsibility":
            _aslog(aid, user, AS_EDIT_ZH[k], AS_RESP.get(v, v), commit=False)
        else:
            _aslog(aid, user, AS_EDIT_ZH.get(k, k), "（空）" if v in (None, "") else str(v)[:200], commit=False)
    c.commit()
    return as_get(aid)


def as_close(aid, user=""):
    return as_update(aid, {"stage": "closed"}, user)


def as_inspect(aid, items, result_note="", user=""):
    """退回的货验货：能卖的放回成品库存，坏的报废（报废按生产成本记损失）。items: [{item_id, restock, scrap}]"""
    from . import orders, production
    c = db.conn()
    a = c.execute("SELECT * FROM aftersales WHERE id=?", (aid,)).fetchone()
    if not a:
        raise ValueError("售后记录不存在")
    if a["inspected_at"]:
        raise ValueError("这条售后已经验过货了")
    o = orders.get_order(a["order_id"])
    by_id = {i["id"]: i for i in (o or {}).get("items", [])}
    done, scrap_rows, restock_n, scrap_n = [], [], 0, 0
    for it in items or []:
        item = by_id.get(_iid(it))
        if not item:
            continue
        rs, sc = max(0, int(it.get("restock") or 0)), max(0, int(it.get("scrap") or 0))
        if rs + sc > (item.get("qty") or 1):
            raise ValueError(f"{item['sku']} 原来只有 {item.get('qty') or 1} 个，验货数量超过了")
        if rs:
            production.stock_add(item["sku"], rs, f"售后退回验货入库（订单 {o['order_no']}）", user,
                                 product_id=item.get("product_id"), name=item.get("name") or "", color=item.get("color") or "")
            restock_n += rs
        if sc:
            scrap_rows.append({**item, "qty": sc})
            scrap_n += sc
        if rs or sc:
            done.append({"item_id": item["id"], "sku": item["sku"], "restock": rs, "scrap": sc})
    if not done:
        raise ValueError("请填写每个商品「入库」或「报废」的数量")
    result = "restock" if not scrap_n else "scrap" if not restock_n else "partial"
    scrap_cost = _items_cost(scrap_rows) if scrap_rows else None
    now = time.time()
    stage = "closed" if a["kind"] == "cod_reject" else a["stage"]
    c.execute("UPDATE aftersales SET inspect_result=?, inspect_note=?, inspect_items=?, inspected_at=?, inspected_by=?, scrap_cost=?, "
              "stage=?, status=?, closed_at=?, updated_at=? WHERE id=?",
              (result, str(result_note or "")[:500], json.dumps(done, ensure_ascii=False), now, user, scrap_cost, stage,
               "closed" if stage in AS_DONE else "open", now if stage in AS_DONE else None, now, aid))
    c.commit()
    txt = f"入库 {restock_n} 个，报废 {scrap_n} 个" + (f"（损失约 ฿{scrap_cost}）" if scrap_cost else "")
    _aslog(aid, user, "验货", txt + (f"；{result_note}" if result_note else ""))
    orders.log(a["order_id"], user, "售后验货", txt)
    return as_get(aid)


def evidence_dir(aid):
    return os.path.join(EVID_DIR, str(int(aid)))


def as_evidence_add(aid, files, user=""):
    c = db.conn()
    a = c.execute("SELECT evidence FROM aftersales WHERE id=?", (aid,)).fetchone()
    if not a:
        raise ValueError("售后记录不存在")
    ev = json.loads(a["evidence"] or "[]")
    d = evidence_dir(aid)
    os.makedirs(d, exist_ok=True)
    added = []
    for f in files:
        name = os.path.basename(f.filename or "file")
        ext = os.path.splitext(name)[1].lower()
        if ext not in EVID_EXT:
            raise ValueError(f"「{name}」不是图片、视频或 PDF")
        safe = f"{int(time.time() * 1000)}_{len(ev) + len(added)}{ext}"
        f.save(os.path.join(d, safe))
        if os.path.getsize(os.path.join(d, safe)) > 200 * 1024 * 1024:
            os.remove(os.path.join(d, safe))
            raise ValueError(f"「{name}」太大了（最大 200MB）")
        added.append({"file": safe, "name": name[:120], "ts": time.time(), "by": user})
    ev += added
    c.execute("UPDATE aftersales SET evidence=?, updated_at=? WHERE id=?", (json.dumps(ev, ensure_ascii=False), time.time(), aid))
    c.commit()
    _aslog(aid, user, "上传凭证", "、".join(x["name"] for x in added))
    return ev


def as_evidence_del(aid, fname, user=""):
    c = db.conn()
    a = c.execute("SELECT evidence FROM aftersales WHERE id=?", (aid,)).fetchone()
    if not a:
        raise ValueError("售后记录不存在")
    ev = json.loads(a["evidence"] or "[]")
    hit = [x for x in ev if x["file"] == fname]
    if not hit:
        raise ValueError("文件不存在")
    ev = [x for x in ev if x["file"] != fname]
    try:
        os.remove(os.path.join(evidence_dir(aid), os.path.basename(fname)))
    except OSError:
        pass
    c.execute("UPDATE aftersales SET evidence=? WHERE id=?", (json.dumps(ev, ensure_ascii=False), aid))
    c.commit()
    _aslog(aid, user, "删除凭证", hit[0]["name"])
    return ev


def _as_row(r, now=None):
    now = now or time.time()
    d = dict(r)
    d["kind_zh"] = AS_KIND.get(d["kind"], d["kind"])
    d["stage"] = d.get("stage") or ("closed" if d.get("status") == "closed" else "new")
    d["stage_zh"] = AS_STAGE.get(d["stage"], d["stage"])
    d["resp_zh"] = AS_RESP.get(d.get("responsibility") or "", "")
    d["evidence"] = json.loads(d.get("evidence") or "[]")
    d["inspect_items"] = json.loads(d.get("inspect_items") or "[]")
    d["loss"] = round(sum((d.get(k) or 0) for k in AS_LOSS), 2)
    d["done"] = d["stage"] in AS_DONE
    d["overdue"] = bool(not d["done"] and d.get("due_at") and d["due_at"] < now)
    d["due_soon"] = bool(not d["done"] and d.get("due_at") and now <= d["due_at"] < now + 24 * 3600)
    return d


def as_get(aid):
    c = db.conn()
    r = c.execute("""SELECT a.*, o.order_no, o.platform, o.buyer, o.status AS order_status, o.cod, o.payment FROM aftersales a
                     LEFT JOIN orders o ON o.id=a.order_id WHERE a.id=?""", (aid,)).fetchone()
    if not r:
        return None
    d = _as_row(r)
    d["log"] = [dict(x) for x in c.execute("SELECT * FROM as_log WHERE as_id=? ORDER BY id DESC", (aid,))]
    d["items"] = [dict(x) for x in c.execute("SELECT id, sku, name, color, qty, product_id FROM order_items WHERE order_id=?",
                                             (d["order_id"],))]
    return d


def as_list(order_id=None, status=None, days=90, stage=None, kind=None, resp=None, q="", due=None):
    """status: open / closed（兼容旧接口）；stage: 具体阶段；due: overdue 已超期 / soon 24 小时内到期。"""
    c = db.conn()
    conds, args = ["a.created_at>=?"], [time.time() - int(days) * 86400]
    if order_id:
        conds.append("a.order_id=?"); args.append(order_id)
    if status:
        conds.append("a.status=?"); args.append(status)
    if stage:
        conds.append("a.stage=?"); args.append(stage)
    if kind:
        conds.append("a.kind=?"); args.append(kind)
    if resp is not None and resp != "":
        conds.append("COALESCE(a.responsibility,'')=?"); args.append("" if resp == "none" else resp)
    if q:
        conds.append("(o.order_no LIKE ? OR o.buyer LIKE ? OR a.note LIKE ? OR a.return_tracking LIKE ? OR o.tracking_no LIKE ?)")
        args += [f"%{q.strip()}%"] * 5
    rows = c.execute(f"""SELECT a.*, o.order_no, o.platform, o.buyer, o.status AS order_status FROM aftersales a
                         LEFT JOIN orders o ON o.id=a.order_id WHERE {' AND '.join(conds)} ORDER BY a.id DESC""", args)
    now = time.time()
    out = [_as_row(r, now) for r in rows]
    if due == "overdue":
        out = [d for d in out if d["overdue"]]
    elif due == "soon":
        out = [d for d in out if d["overdue"] or d["due_soon"]]
    return out


def as_counts():
    now = time.time()
    c = db.conn()
    st = {r["stage"] or "new": r["n"] for r in c.execute("SELECT stage, COUNT(*) n FROM aftersales GROUP BY stage")}
    over = c.execute(f"SELECT COUNT(*) FROM aftersales WHERE stage NOT IN ({','.join('?' * len(AS_DONE))}) AND due_at<?",
                     (*AS_DONE, now)).fetchone()[0]
    soon = c.execute(f"SELECT COUNT(*) FROM aftersales WHERE stage NOT IN ({','.join('?' * len(AS_DONE))}) AND due_at>=? AND due_at<?",
                     (*AS_DONE, now, now + 86400)).fetchone()[0]
    return {"stages": st, "open": sum(v for k, v in st.items() if k not in AS_DONE), "overdue": over, "due_soon": soon}


def as_losses(since):
    """利润报表用：每条售后的损失。退款只在订单收入还算在利润里时才扣（订单已是退货/取消/拒收的，收入本来就没算）。"""
    from .finance import EXCLUDE
    c = db.conn()
    out = []
    for r in c.execute("SELECT a.*, o.status AS ost FROM aftersales a LEFT JOIN orders o ON o.id=a.order_id WHERE a.created_at>=?", (since,)):
        loss = sum((r[k] or 0) for k in ("reship_cost", "return_shipping", "penalty", "scrap_cost"))
        if r["ost"] not in EXCLUDE:
            loss += r["amount"] or 0
        if loss:
            out.append({"id": r["id"], "created_at": r["created_at"], "loss": round(loss, 2)})
    return out


def as_stats(days=90):
    c = db.conn()
    since = time.time() - days * 86400
    loss_sql = "SUM(" + "+".join(f"COALESCE({k},0)" for k in AS_LOSS) + ")"
    return {"by_reason": [dict(r) for r in c.execute(f"SELECT reason AS k, COUNT(*) AS n, SUM(COALESCE(amount,0)) AS amt, {loss_sql} AS loss "
                                                     "FROM aftersales WHERE created_at>=? GROUP BY reason ORDER BY n DESC", (since,))],
            "by_resp": [dict(r, label=AS_RESP.get(r["k"] or "", r["k"])) for r in c.execute(
                f"SELECT COALESCE(responsibility,'') AS k, COUNT(*) AS n, {loss_sql} AS loss FROM aftersales WHERE created_at>=? "
                "GROUP BY COALESCE(responsibility,'') ORDER BY n DESC", (since,))],
            "by_printer": [dict(r) for r in c.execute(
                "SELECT printer_codes AS k, COUNT(*) AS n FROM aftersales WHERE created_at>=? AND COALESCE(printer_codes,'')!='' "
                "AND responsibility='production' GROUP BY printer_codes ORDER BY n DESC", (since,))],
            "total": c.execute("SELECT COUNT(*) FROM aftersales WHERE created_at>=?", (since,)).fetchone()[0],
            "amount": c.execute("SELECT SUM(COALESCE(amount,0)) FROM aftersales WHERE created_at>=?", (since,)).fetchone()[0] or 0,
            "loss": round(c.execute(f"SELECT {loss_sql} FROM aftersales WHERE created_at>=?", (since,)).fetchone()[0] or 0, 2)}


# ---------------- 备份 ----------------
def backup_now(tag="auto"):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = f"backup_{dt.datetime.now().strftime('%Y%m%d_%H%M')}_{tag}.zip"
    path = os.path.join(BACKUP_DIR, name)
    c = db.conn()
    try:
        c.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except Exception:  # 不影响备份
        pass
    skip = {"backups", "tmp", "imports", "exports"}
    with zipfile.ZipFile(path + ".tmp", "w", zipfile.ZIP_DEFLATED) as z:
        # 数据库用 SQLite 自带的在线备份，保证一致
        tmpdb = os.path.join(BACKUP_DIR, "_app.db")
        import sqlite3
        dst = sqlite3.connect(tmpdb)
        c.backup(dst)
        dst.close()
        z.write(tmpdb, "app.db")
        os.remove(tmpdb)
        for root, dirs, files in os.walk(DATA_DIR):
            rel = os.path.relpath(root, DATA_DIR)
            if rel.split(os.sep)[0] in skip:
                dirs[:] = []
                continue
            for f in files:
                if rel == "." and f.startswith("app.db"):
                    continue
                full = os.path.join(root, f)
                z.write(full, os.path.normpath(os.path.join(rel, f)))
    os.replace(path + ".tmp", path)
    _copy_out(path)
    files = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("backup_") and f.endswith(".zip"))
    for old in files[:-KEEP_BACKUPS]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            pass
    return name


def _copy_out(path):
    """设置了「备份另存一份到」：复制过去，那边也只留最近几份。失败不影响本机备份。"""
    from .config import load_config
    d = (load_config().get("backup_copy_dir") or "").strip()
    if not d or not os.path.isdir(d):
        return
    try:
        shutil.copy2(path, os.path.join(d, os.path.basename(path)))
        olds = sorted(f for f in os.listdir(d) if f.startswith("backup_") and f.endswith(".zip"))
        for o in olds[:-KEEP_COPY]:
            os.remove(os.path.join(d, o))
    except OSError as e:
        print("备份另存失败：", e)


KEEP_COPY = 14


def backups():
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for f in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if f.startswith("backup_") and f.endswith(".zip"):
            p = os.path.join(BACKUP_DIR, f)
            out.append({"name": f, "size": os.path.getsize(p), "ts": os.path.getmtime(p)})
    return out


def _backup_loop():
    while True:
        try:
            today = dt.datetime.now().strftime("%Y%m%d")
            if not any(b["name"].startswith(f"backup_{today}") for b in backups()):
                backup_now("auto")
        except Exception:
            import traceback
            traceback.print_exc()
        finally:
            db.release()
        time.sleep(3600)


_started = False


def start_backup():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_backup_loop, daemon=True, name="backup").start()


# ---------------- 产品分组 ----------------
def groups():
    from . import store
    counts = {}
    for item in store.list_products():
        p = store.load(item["id"])
        if p.get("inbox"):              # 选品采集箱里的不算（采集箱有自己的数）
            continue
        for g in p.get("groups") or []:
            counts[g] = counts.get(g, 0) + 1
    return [dict(r, count=counts.get(r["id"], 0)) for r in
            db.conn().execute("SELECT * FROM product_groups ORDER BY sort, name")]


def group_save(name, gid=None):
    name = (name or "").strip()[:30]
    if not name:
        raise ValueError("请填写分组名称")
    c = db.conn()
    if gid:
        c.execute("UPDATE product_groups SET name=? WHERE id=?", (name, gid))
    else:
        if c.execute("SELECT 1 FROM product_groups WHERE name=?", (name,)).fetchone():
            raise ValueError("已经有这个分组了")
        gid = c.execute("INSERT INTO product_groups(name, sort) VALUES(?, (SELECT COALESCE(MAX(sort),0)+1 FROM product_groups))",
                        (name,)).lastrowid
    c.commit()
    return gid


def group_delete(gid):
    from . import store
    for item in store.list_products():
        p = store.load(item["id"])
        if gid in (p.get("groups") or []):
            p["groups"] = [g for g in p["groups"] if g != gid]
            store.save(p)
    c = db.conn()
    c.execute("DELETE FROM product_groups WHERE id=?", (gid,))
    c.commit()


def group_assign(pids, gid, add=True):
    from . import store
    n = 0
    for pid in pids:
        p = store.load(pid)
        g = list(p.get("groups") or [])
        if add and gid not in g:
            g.append(gid)
        elif not add and gid in g:
            g.remove(gid)
        else:
            continue
        p["groups"] = g
        store.save(p)
        n += 1
    return n


# ---------------- 工作台 ----------------
def dashboard(owner=False):
    from . import finance, materials, orders, printers as pr, production
    c = db.conn()
    now = time.time()
    day0 = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
    s = orders.search({"tab": "all", "page_size": 500})
    od = [o for o in orders.search({"tab": "all", "page_size": 100000})["orders"]] if s["total"] > 500 else s["orders"]
    active = [o for o in od if o["status"] == "to_ship"]
    overdue = [o for o in active if o.get("ship_by") and o["ship_by"] < now and o.get("stage") not in ("ready", "out")]
    due_today = [o for o in active if o.get("ship_by") and now <= o["ship_by"] < day0 + 86400 and o.get("stage") not in ("ready", "out")]
    ready = [o for o in active if o.get("stage") == "ready"]
    exc = [o for o in od if o.get("exceptions")]
    cfg = load_config()
    prs = []
    for i, p in enumerate(cfg.get("printers") or []):
        st = pr.get_status(i)
        prs.append({"index": i, "name": p.get("name"), "code": p.get("code") or f"#{i + 1}",
                    "enabled": p.get("enabled", True) is not False, "state": st.get("state") or "none",
                    "state_zh": pr.STATE_ZH.get(st.get("state") or "none", ""), "progress": st.get("progress"),
                    "remaining_min": st.get("remaining_min"), "file": st.get("file")})
    runs = production.active_runs()
    q = c.execute("SELECT COUNT(*) n, SUM(qty-COALESCE(qty_done,0)) pcs FROM jobs WHERE status='todo'").fetchone()
    post = c.execute("SELECT COUNT(*) FROM jobs WHERE status='post'").fetchone()[0]
    packed = c.execute("SELECT COUNT(*) FROM jobs WHERE status='packed'").fetchone()[0]
    mat = materials.plan()["rows"]
    try:
        mat_alerts = materials.alerts(mat)
    except Exception:  # noqa: BLE001  提醒算不出来不影响工作台
        mat_alerts = []
    low = [m for m in mat if m["urgent"] or m["short"]]
    humid = [m for m in mat if (m.get("humid") or {}).get("warn")]
    maint = [{"printer": x["name"], "label": it["label"]} for x in production.maintenance_status() for it in x["items"] if it["due"]]
    sug = [x for x in production.stock_suggest() if x["suggest"] > 0]
    fails_today = c.execute("SELECT COUNT(*) FROM failures WHERE ts>=?", (day0,)).fetchone()[0]
    alerts = [dict(r) for r in c.execute("SELECT id, printer, sku, alert FROM print_runs WHERE status='printing' AND COALESCE(alert,'')!=''")]
    as_open = c.execute("SELECT COUNT(*) FROM aftersales WHERE status='open'").fetchone()[0]
    asc = as_counts()
    review = sum(1 for o in active if o.get("hold"))
    urgent = sum(1 for o in active if orders.is_urgent(o, now))
    out = {"orders_active": len(active), "overdue": [{"id": o["id"], "order_no": o["order_no"], "ship_by": o["ship_by"]} for o in overdue][:20],
           "due_today": len(due_today), "ready_to_ship": len(ready), "exceptions": len(exc),
           "new_today": sum(1 for o in od if (o.get("order_time") or 0) >= day0),
           "printers": prs, "runs": len(runs), "queue_jobs": q["n"] or 0, "queue_pcs": q["pcs"] or 0,
           "post": post, "packed": packed, "low_material": [{"material": m["material"], "color": m["color"], "days_left": m["days_left"],
                                                              "short": m["short"]} for m in low][:10],
           "humid": [{"material": m["material"], "color": m["color"], "days": m["humid"]["days"]} for m in humid][:10],
           "maintenance": maint[:10], "stock_suggest": [{"sku": x["sku"], "suggest": x["suggest"]} for x in sug][:10],
           "fails_today": fails_today, "alerts": alerts, "aftersales_open": as_open,
           "aftersales_overdue": asc["overdue"] + asc["due_soon"], "review": review, "urgent": urgent,
           "material_alerts": mat_alerts[:12]}
    # v2.49 工作台按角色：上架客服看「待上架」「待确认的建议」
    try:
        from . import search
        prods = search._products()
        out["to_list"] = sum(1 for p in prods if p["active"] and not p["draft"] and not p.get("exported"))
        out["drafts"] = sum(1 for p in prods if p["draft"])
    except Exception:  # noqa: BLE001
        out["to_list"] = out["drafts"] = None
    from . import modules
    link = modules.public("link")
    try:
        out["sugg_pending"] = (link.opsapi.counts().get("pending") or 0) if link else None
    except Exception:  # noqa: BLE001
        out["sugg_pending"] = None
    if owner:
        rep = finance.report(1)
        out["today"] = {"revenue": rep["total"]["revenue"], "profit": rep["total"]["profit"], "orders": rep["total"]["orders"]}
        rep7 = finance.report(7)
        out["week"] = {"revenue": rep7["total"]["revenue"], "profit": rep7["total"]["profit"], "orders": rep7["total"]["orders"]}
        # v2.49：最近 7 天每天（工作台数字卡片下面的走势小图；今天 = 最后一个）
        byday = {r["day"]: r for r in rep7["days"]}
        out["trend"] = []
        for i in range(6, -1, -1):
            k = (dt.date.today() - dt.timedelta(days=i)).isoformat()
            r = byday.get(k) or {}
            out["trend"].append({"day": k, "orders": r.get("orders", 0), "revenue": round(r.get("revenue", 0), 2), "profit": round(r.get("profit", 0), 2)})
        out["today_cal"] = out["trend"][-1]
    return out
