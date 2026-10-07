"""上架进度：导出表格后产品进入「待上传」，在平台上传成功后改成「已上传」（失败可以记原因）。
每次导出是一个「上架批次」，记下导出了哪些产品、哪些文件，方便按批核对。

产品里存：product["listing"] = {"lazada": {"status", "batch", "at", "note"}, "shopee": {...}}
"""
import json
import time

from . import db, store

PLATFORMS = ("lazada", "shopee")
# 按平台自己的商品状态走（v2.11.1）：
#   导出表格 → 待上传 pending → 上传到平台 → 平台审核中 uploaded（Lazada「Pending QC」/ Shopee「审核中」）
#   → 审核通过、在售 live（Lazada「Active」/ Shopee「Live / 在售」）或 审核不通过 rejected（Lazada「QC Rejected」/ Shopee「违规 / 禁止」）
#   → 平台上下架了 inactive（Lazada「Inactive」/ Shopee「已下架 Unlisted」）
#   failed：上传表格时就报错，平台上没生成商品；update：平台上已有，ERP 资料又改了（例如运营系统改价），要重新同步
STATUS_ZH = {"none": "未导出", "pending": "待上传", "failed": "上传失败", "uploaded": "平台审核中", "rejected": "审核不通过",
             "live": "已上线（在售）", "inactive": "平台已下架", "update": "有修改待同步"}
ON_PLATFORM = ("uploaded", "live", "rejected", "inactive", "update")   # 平台上已经有这个商品了
PLATFORM_ZH = {"lazada": {"uploaded": "Pending QC", "live": "Active", "rejected": "QC Rejected", "inactive": "Inactive"},
               "shopee": {"uploaded": "审核中 Reviewing", "live": "在售 Live", "rejected": "违规 / 禁止 Violation", "inactive": "已下架 Unlisted"}}
SCHEMA = """
CREATE TABLE IF NOT EXISTS listing_batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT, name TEXT, group_id INTEGER,
  created_at REAL, username TEXT, files TEXT, product_ids TEXT, note TEXT, closed INTEGER DEFAULT 0
);
"""


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()


def status_of(p, platform):
    st = ((p.get("listing") or {}).get(platform) or {})
    if st.get("status"):
        return st
    # 老数据：导出过但没有记录状态 → 当作待上传
    key = "exported_at" if platform == "lazada" else "shopee_exported_at"
    if p.get(key):
        return {"status": "pending", "at": p.get(key)}
    return {"status": "none"}


def _set(p, platform, status, batch=None, note=None, user=""):
    lst = p.setdefault("listing", {})
    cur = dict(lst.get(platform) or {})
    now = time.time()
    old = cur.get("status")
    if status in ("uploaded", "live", "rejected"):
        # 上传到平台的时间：第一次（之后不改）和最近一次。没经过「审核中」直接标「已上线」/「审核不通过」也算上传过
        if status == "uploaded" or old not in ON_PLATFORM:
            cur.setdefault("first_uploaded_at", now)
            cur["last_uploaded_at"] = now
    if status == "live":
        # 第一次审核通过、真正在售的时间 = 测款期起点（之后重新上架不改）
        cur.setdefault("first_listed_at", now)
        cur["live_at"] = now
    if status == "inactive":
        cur["delisted_at"] = now
    cur.pop("prev", None)
    cur.update(status=status, at=now, by=user)
    if batch is not None:
        cur["batch"] = batch
    if note is not None:
        cur["note"] = note
    elif status != "failed":
        cur.pop("note", None)
    lst[platform] = cur


def create_batch(platform, pids, files, name="", group_id=None, user=""):
    if platform not in PLATFORMS:
        raise ValueError("平台不对")
    c = db.conn()
    n = c.execute("SELECT COUNT(*) FROM listing_batches WHERE platform=? AND date(created_at,'unixepoch','localtime')=date('now','localtime')",
                  (platform,)).fetchone()[0] + 1
    name = (name or "").strip()[:60] or f"{'Lazada' if platform == 'lazada' else 'Shopee'} {time.strftime('%m-%d')} 第 {n} 批"
    bid = c.execute("INSERT INTO listing_batches(platform, name, group_id, created_at, username, files, product_ids) VALUES(?,?,?,?,?,?,?)",
                    (platform, name, group_id, time.time(), user, json.dumps(files, ensure_ascii=False),
                     json.dumps(list(pids)))).lastrowid
    c.commit()
    for pid in pids:
        try:
            p = store.load(pid)
        except FileNotFoundError:
            continue
        _set(p, platform, "pending", batch=bid, user=user)
        store.save(p)
    return get_batch(bid)


def set_status(pids, platform, status, note=None, user=""):
    if platform not in PLATFORMS or status not in STATUS_ZH:
        raise ValueError("状态不对")
    n = 0
    for pid in pids:
        try:
            p = store.load(pid)
        except FileNotFoundError:
            continue
        _set(p, platform, status, note=note, user=user)
        store.save(p)
        n += 1
    return n


def _batch_row(r):
    d = dict(r)
    d["files"] = json.loads(d.get("files") or "[]")
    d["product_ids"] = json.loads(d.get("product_ids") or "[]")
    items, counts = [], {k: 0 for k in STATUS_ZH}
    for pid in d["product_ids"]:
        try:
            p = store.load(pid)
        except FileNotFoundError:
            continue
        st = status_of(p, d["platform"])
        # 后来又被别的批次重新导出了：这个批次里显示那次的状态
        items.append({"id": pid, "name": p.get("name_zh", ""), "status": st.get("status"), "note": st.get("note", ""),
                      "other_batch": st.get("batch") not in (None, d["id"])})
        counts[st.get("status") or "none"] += 1
    d["items"] = items
    d["counts"] = counts
    return d


def get_batch(bid):
    r = db.conn().execute("SELECT * FROM listing_batches WHERE id=?", (bid,)).fetchone()
    return _batch_row(r) if r else None


def list_batches(limit=50, platform=None):
    sql = "SELECT * FROM listing_batches" + (" WHERE platform=?" if platform else "") + " ORDER BY id DESC LIMIT ?"
    args = ((platform,) if platform else ()) + (int(limit),)
    return [_batch_row(r) for r in db.conn().execute(sql, args)]


# 整批标记时，哪些状态可以改成目标状态（不覆盖已经单独标记过的）
BATCH_FROM = {"uploaded": ("pending",), "live": ("pending", "uploaded"), "failed": ("pending",)}


def batch_set(bid, status, note=None, user="", only_pending=True):
    """整批标记：整批上传成功 → 平台审核中；整批审核通过 → 已上线。"""
    b = get_batch(bid)
    if not b:
        raise ValueError("批次不存在")
    src = BATCH_FROM.get(status, ("pending",))
    pids = [i["id"] for i in b["items"] if not i["other_batch"] and (not only_pending or i["status"] in src)]
    return set_status(pids, b["platform"], status, note, user)


def rename_batch(bid, name):
    c = db.conn()
    c.execute("UPDATE listing_batches SET name=? WHERE id=?", ((name or "").strip()[:60], bid))
    c.commit()
    return get_batch(bid)


def delete_batch(bid):
    """删除批次记录（不改产品状态，导出的文件保留）。"""
    c = db.conn()
    c.execute("DELETE FROM listing_batches WHERE id=?", (bid,))
    c.commit()


def v1_view(p, batch_names=None):
    """给 /api/v1/skus 用：每个平台的上架状态和时间（v2.11.1，状态按平台自己的商品状态）。
    first_listed_at = 第一次审核通过、真正在售的时间（测款期从这里算）；还没上线过为 null。
    platform_status = 平台上现在的状态（status 是 update 时，看这个知道平台上是在售还是审核中）。"""
    out = {}
    erp_off = p.get("active", True) is False
    for plat in PLATFORMS:
        st = status_of(p, plat)
        status = st.get("status") or "none"
        first_up = st.get("first_uploaded_at")
        if status in ON_PLATFORM and not first_up:      # 2.11.1 以前标的「已上传」：用当时标记的时间
            first_up = st.get("at")
        plat_st = st.get("prev") if status == "update" else status
        if plat_st not in ("uploaded", "live", "rejected", "inactive"):
            plat_st = None
        bid = st.get("batch")
        ts = lambda v: int(v) if v else None
        out[plat] = {"status": status, "platform_status": plat_st,
                     "first_uploaded_at": ts(first_up), "last_uploaded_at": ts(st.get("last_uploaded_at") or first_up),
                     "first_listed_at": ts(st.get("first_listed_at")), "live_at": ts(st.get("live_at")),
                     "delisted_at": ts(st.get("delisted_at")),
                     "erp_active": not erp_off,           # ERP 里被下架（例如运营系统下架）为 false，要去平台上同步下架
                     "batch_id": bid, "batch": (batch_names or {}).get(bid) if bid else None,
                     "note": st.get("note") or None}
    return out


def batch_names():
    return {r["id"]: r["name"] for r in db.conn().execute("SELECT id, name FROM listing_batches")}
