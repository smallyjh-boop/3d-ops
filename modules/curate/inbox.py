"""采集箱（v2.50.1，像 BigSeller 的采集箱）：「采用 / 采集」马上建 ERP 产品草稿（流水线、编辑页、许可门槛、模型文件都照常），
但产品带 inbox=True，先放在「选品 → 采集箱」里，不进产品库（产品库、分组数、全局搜索默认都不算它）。
整理好了点「转入产品库」（去掉 inbox）。许可没核验 / 没模型文件时提醒但允许转；导出 / 推送的许可门槛照旧在上架检查里。

  listing(args)        采集箱列表 + 左边的文件夹（全部 · 按类目 · 未分类 · 自己建的文件夹 = 产品分组）+ 每个产品的状态（文件 / 文案 / 许可 / 图片）
  to_library(ids)      转入产品库，返回提醒
  delete(ids)          删掉产品草稿（候选标成「不采用」）
  queue_copy(ids)      「AI 写文案」：排进后台（只填空着的字段）
  migrate()            升级时：已经在产品库里的选品草稿（没导出 / 上架过的）搬进采集箱，只做一次
"""
import time

from core import store

from . import db, sites, watch


def exported(p):
    return bool(p.get("exported_at") or p.get("shopee_exported_at") or (p.get("lazada_api") or {}).get("item_id")
                or any((v or {}).get("status") not in (None, "", "none") for v in (p.get("listing") or {}).values()))


def migrate(force=False):
    """选品采用、还是草稿、从没导出 / 上架过的产品 → 采集箱。只做一次（cur_settings.inbox_migrated）。返回搬了几个。"""
    if db.get("inbox_migrated") and not force:
        return 0
    n = 0
    for item in store.list_products():
        try:
            p = store.load(item["id"])
        except Exception:  # noqa: BLE001
            continue
        if (p.get("source") or {}).get("source") == "curate" and p.get("draft") and "inbox" not in p and not exported(p):
            p["inbox"] = True
            store.save(p)
            n += 1
    db.put("inbox_migrated", time.time())
    return n


def _products():
    out = []
    for item in store.list_products():
        try:
            p = store.load(item["id"])
        except Exception:  # noqa: BLE001
            continue
        if p.get("inbox"):
            out.append(p)
    return out


def count():
    return len(_products())


def _cat(p, cands, names):
    cid = (p.get("category") or {}).get("id")
    if cid and names.get(cid):
        return names[cid]
    return cands.get(p["id"], {}).get("category") or (p.get("source") or {}).get("category_guess") or ""


def image_state(p):
    """图片：none 没图 / source 还在用原站图（可能有水印）/ own 都换成自己的（或修过图）。"""
    imgs = [i for i in p.get("images") or [] if i.get("file")]
    if not imgs:
        return "none"
    return "source" if any(i.get("from") == "source" and not i.get("edited") for i in imgs) else "own"


def row(p, cands=None, names=None, ext=None, ai=True):
    cands = cands if cands is not None else {}
    names = names if names is not None else {}
    c = db.conn()
    fs = watch.file_status(p["id"])
    if ext is not None:
        fs["ext"] = ext
    cp = p.get("copy") or {}
    s = p.get("source") or {}
    pend = c.execute("SELECT 1 FROM cur_collect WHERE product_id=? AND copy=0", (p["id"],)).fetchone()
    copy = "done" if cp.get("title_th") and cp.get("description_th") else "writing" if pend and ai else "todo"
    lc = p.get("license_check") or {}
    cd = cands.get(p["id"], {})
    img = next((f"/files/{p['id']}/{'out' if i.get('processed') else 'raw'}/{i['file']}" for i in p.get("images") or [] if i.get("file")), "")
    return {"product_id": p["id"], "name": p.get("name_zh") or "", "title_th": cp.get("title_th") or "", "title_original": s.get("title_original") or "",
            "url": s.get("source_url") or "", "platform": s.get("platform") or "", "author": s.get("author") or "",
            "thumb": img or cd.get("thumb") or "", "score": cd.get("score"), "category": _cat(p, cands, names),
            "adopted_at": s.get("imported_at") or 0, "groups": p.get("groups") or [],
            "files": fs, "copy": copy, "license": lc.get("status") or "", "license_auto": lc.get("auto") or "", "license_name": lc.get("name") or "",
            "images": image_state(p), "n_images": len(p.get("images") or []), "model": bool(p.get("model")),
            "specs": len(p.get("specs") or []), "ip": (p.get("ip_risk") or {}).get("status") == "pending"}


def listing(args):
    """args：folder（all / cat:类目 / nocat / g:分组编号）、q（搜索）。"""
    from core import categories, extras
    from . import cand
    migrate()
    names = {x["id"]: x["name"] for x in categories.library()}
    c = db.conn()
    cands = {r["product_id"]: dict(r) for r in c.execute("SELECT product_id, category, score, thumb FROM cur_candidates WHERE product_id<>''")}
    ext = watch.ext_status()
    ai = cand.ai_on()
    rows = [row(p, cands, names, ext, ai) for p in _products()]
    rows.sort(key=lambda r: -(r["adopted_at"] or 0))
    cats, groups = {}, {}
    for r in rows:
        cats[r["category"] or ""] = cats.get(r["category"] or "", 0) + 1
        for g in r["groups"]:
            groups[g] = groups.get(g, 0) + 1
    from .rules import CATEGORY_TH
    folders = {"all": len(rows), "nocat": cats.get("", 0),
               "cats": [{"name": k, "th": CATEGORY_TH.get(k, ""), "n": v} for k, v in sorted(cats.items(), key=lambda x: -x[1]) if k],
               "groups": [{"id": g["id"], "name": g["name"], "n": groups.get(g["id"], 0)} for g in extras.groups()]}
    f = str(args.get("folder") or "all")
    if f == "nocat":
        rows = [r for r in rows if not r["category"]]
    elif f.startswith("cat:"):
        rows = [r for r in rows if r["category"] == f[4:]]
    elif f.startswith("g:"):
        rows = [r for r in rows if str(f[2:]) in [str(x) for x in r["groups"]]]
    q = str(args.get("q") or "").strip().lower()
    if q:
        rows = [r for r in rows if q in " ".join([r["product_id"], r["name"], r["title_th"], r["title_original"], r["author"]]).lower()]
    k = {"total": folders["all"], "lic_pending": sum(1 for r in rows if r["license"] == "pending"),
         "no_files": sum(1 for r in rows if not r["files"]["ok"]), "no_copy": sum(1 for r in rows if r["copy"] != "done"),
         "source_img": sum(1 for r in rows if r["images"] == "source")}
    return {"rows": rows, "folders": folders, "kpi": k, "ext": ext, "ai": ai}


def to_library(ids, who=""):
    """转入产品库：去掉 inbox。许可没核验 / 没模型文件只提醒（导出 / 推送的许可门槛照旧）。返回 {moved, warnings:{编号: [提醒]}}。"""
    from core import db as cdb
    moved, warns = [], {}
    for pid in ids or []:
        try:
            p = store.load(pid)
        except (FileNotFoundError, ValueError):
            continue
        if not p.get("inbox"):
            continue
        w = []
        if (p.get("license_check") or {}).get("status") == "pending":
            w.append("许可还没核验（核验前不能导出 / 推送）")
        if not p.get("source_files") and not p.get("model"):
            w.append("还没有模型文件")
        if image_state(p) == "source":
            w.append("还在用原站图片（可能有水印）")
        p.pop("inbox", None)
        p["inbox_out_at"] = time.time()
        store.save(p)
        cdb.audit(who or "选品", "选品·转入产品库", pid, "；".join(w))
        moved.append(pid)
        if w:
            warns[pid] = w
    return {"moved": moved, "warnings": warns}


def delete(ids, who=""):
    """删掉采集箱里的产品草稿（图片、模型文件一起删）；候选标「不采用」，以后还能在候选池里恢复、重新采用。"""
    from core import db as cdb
    c = db.conn()
    n = 0
    for pid in ids or []:
        try:
            p = store.load(pid)
        except (FileNotFoundError, ValueError):
            continue
        if not p.get("inbox"):
            raise ValueError(f"{pid} 已经转入产品库了，请在产品库里删除")
        store.delete(pid)
        c.execute("UPDATE cur_candidates SET product_id='', status='ignored' WHERE product_id=?", (pid,))
        c.execute("DELETE FROM cur_files WHERE product_id=?", (pid,))
        c.execute("UPDATE cur_collect SET state='canceled', post=2, copy=1 WHERE product_id=? AND state IN ('waiting','running')", (pid,))
        c.execute("UPDATE cur_collect SET post=2, copy=1 WHERE product_id=?", (pid,))
        cdb.audit(who or "选品", "选品·从采集箱删除", pid, p.get("name_zh") or "")
        n += 1
    c.commit()
    return n


def queue_copy(ids):
    """「AI 写文案」：每个产品排一次后台写文案（只填空着的，人写过的不动）。返回排了几个。"""
    c = db.conn()
    n = 0
    for pid in ids or []:
        r = c.execute("SELECT MAX(id) FROM cur_collect WHERE product_id=?", (pid,)).fetchone()[0]
        if r:
            c.execute("UPDATE cur_collect SET copy=0, created_at=MIN(created_at, ?) WHERE id=?", (time.time() - 3600, r))
        else:
            try:
                p = store.load(pid)
            except (FileNotFoundError, ValueError):
                continue
            s = p.get("source") or {}
            c.execute("INSERT INTO cur_collect(url, skey, title, product_id, pos, state, created_at, updated_at, copy, post) VALUES(?,?,?,?,0,'done',?,?,0,2)",
                      (s.get("source_url") or "", s.get("source_id") or sites.source_key(s.get("source_url") or ""), p.get("name_zh") or "", pid,
                       time.time(), time.time()))
        n += 1
    c.commit()
    from . import pipeline
    pipeline.kick()
    return n
