"""T36（v2.56）：在切片软件（Bambu Studio / OrcaSlicer）里编辑一盘 —— 编辑会话、锁、主文件、读回同步、安全核对。

流程：网页「✏ 在 Bambu Studio 中编辑」→ start() 生成这一盘的项目 3MF（已有同一软件保存的主文件 → 直接用主文件），
返回会话 id + 一次性下载地址 + 上传地址（带会话密钥，桌面客户端不用登录就能回传）。
软件里 Ctrl+S → 桌面客户端监视到文件变了、自动 upload()（或在网页上传框拖回来）→ 原样存为这一盘的主文件（保留最近 10 个版本）
→ 读回同步打印方案（零件按名字末尾的「#编号」对应：复制出来的 = 新零件，删掉的从方案里去掉，软件里新加的零件存进模型库，
软件里多出来的盘 = 方案里的新盘）→ 安全核对（材料 / 槽、机型 / 喷嘴 / 热床板、热床范围 / 废料口、多色 / AMS），
不一致标「需要确认」（中文 + 泰文），确认前不能切片。
锁：同一盘同时只能一个人编辑；2 小时没动静自动释放。完成 = 释放锁；放弃 = 恢复到开始编辑前（这次回传的都不要了）。

盘上的字段（存在打印方案里，网页保存时只要摆盘没变就保留）：
  master  = {file, sha, app, application, app_ver, saved_at, by, plate_no, painted, history: [{file, sha, at, by, app_ver}]}
  confirm = [{zh, th}]（空 / 没有 = 不用确认），confirmed = {by, at}
"""
import copy
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import threading
import time
import zipfile

import numpy as np

from core import fleet, store
from core.config import DATA_DIR, load_config

from . import slicerproj as sp

LOCK_TTL = 2 * 3600
ENDED = "这次编辑已经结束（完成 / 放弃 / 超过 2 小时），请在网页上重新点「编辑」/ การแก้ไขนี้สิ้นสุดแล้ว กรุณากด «แก้ไข» ในเว็บอีกครั้ง"
MAX_UNZIP = int(1.5 * 1024 ** 3)       # 解压后总大小上限（防 zip 炸弹）
MAX_RATIO = 400                        # 单个文件压缩比上限（大于 20 MB 的才查）
MACHINE = "machine"                    # 确认项类别：机型 / 喷嘴 / 热床板 / 没有 AMS —— 只有老板能确认
MATERIAL = "material"                  # 材料 / 耗材配置 —— 有权限的人都能确认
GENERAL = "general"
HISTORY_MAX = 10
MAX_UPLOAD = 300 * 1048576
DIR = os.path.join(DATA_DIR, "slicer_edit")
_lock = threading.RLock()


class LockedError(ValueError):
    def __init__(self, s):
        self.session = s
        who = s.get("display") or s.get("user") or "?"
        super().__init__(f"{who} 正在 {sp.APPS.get(s.get('app'), '')} 里编辑这一盘（{time.strftime('%H:%M', time.localtime(s['started']))} 开始），"
                         f"等他完成或 2 小时没动静后自动释放 / {who} กำลังแก้ไขถาดนี้อยู่")


# ---------------- 选软件 ----------------
def app_of(plate_or_printer, cfg=None):
    return fleet.slicer_app_of(plate_or_printer, cfg)


# ---------------- 会话存储 ----------------
def _path():
    return os.path.join(DIR, "sessions.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    os.makedirs(DIR, exist_ok=True)
    with open(_path() + ".tmp", "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(_path() + ".tmp", _path())


def _expire(d, now=None):
    now = now or time.time()
    gone = []
    for sid, s in list(d.items()):
        if s.get("status") == "open" and now - (s.get("touched") or s["started"]) > LOCK_TTL:
            s["status"] = "expired"
        if s.get("status") != "open" and now - (s.get("touched") or s["started"]) > 7 * 86400:
            gone.append(sid)
    for sid in gone:
        d.pop(sid, None)
        try:
            os.remove(os.path.join(DIR, sid + ".3mf"))
        except OSError:
            pass
    return d


def _public(s):
    return {k: s.get(k) for k in ("id", "pid", "spec", "plate", "colour", "app", "user", "display", "started", "touched",
                                  "status", "last_sync", "syncs", "from_master", "notes", "filename", "plate_no")}


def get(sid):
    with _lock:
        return _load().get(str(sid))


def open_for(pid, spec, plate_id=None, now=None):
    """这个产品规格（这一盘）正在编辑的会话（没过期的）。"""
    with _lock:
        d = _expire(_load(), now)
        return [_public(s) for s in d.values() if s["pid"] == pid and s["spec"] == (spec or "") and s.get("status") == "open"
                and (plate_id is None or s["plate"] == plate_id)]


def _master_dir(pid, spec, plate_id):
    safe = re.sub(r"[^\w-]+", "_", spec or "main")[:40] or "main"
    return os.path.join(store.product_dir(pid), "slicer_master", f"{safe}__{re.sub(r'[^\w-]+', '_', plate_id)}")


def master_path(pid, spec, plate):
    m = (plate or {}).get("master") or {}
    if not m.get("file"):
        return None
    p = os.path.join(_master_dir(pid, spec, plate.get("master_of") or plate["id"]), m["file"])
    return p if os.path.isfile(p) else None


def _plan_and_plate(p, spec, plate_id):
    from . import printplan as pp
    plan = pp.get_plan(p, spec)
    if plan.get("follow"):
        raise ValueError("这个规格是「按主模型缩放」的：请编辑主模型的打印方案 / แผนนี้ย่อขยายตามโมเดลหลัก กรุณาแก้ที่โมเดลหลัก")
    plate = next((x for x in plan["plates"] if x["id"] == plate_id), None)
    if not plate:
        raise ValueError("没有这一盘（刷新一下）/ ไม่มีถาดนี้ (รีเฟรชหน้า)")
    return plan, plate


# ---------------- 开始 / 完成 / 放弃 ----------------
def start(pid, spec, plate_id, colour="", app="", user="", display="", now=None):
    """开始编辑：返回 {session, download, upload, filename}（download 一次有效；upload 在会话期间一直能用）。"""
    now = now or time.time()
    spec = (spec or "").strip()
    p = store.load(pid)
    plan, plate = _plan_and_plate(p, spec, plate_id)
    app = app if app in sp.APPS else app_of(plate)
    with _lock:
        d = _expire(_load(), now)
        for s in d.values():
            if s["pid"] == pid and s["spec"] == spec and s["plate"] == plate_id and s.get("status") == "open":
                if s.get("user") != user:
                    raise LockedError(s)
                s["status"] = "replaced"              # 同一个人重新开始：旧会话作废（锁交给新的）
        sid = "se" + secrets.token_hex(6)
        os.makedirs(DIR, exist_ok=True)
        out = os.path.join(DIR, sid + ".3mf")
        mp = master_path(pid, spec, plate)
        m = plate.get("master") or {}
        notes = []
        derived = bool(plate.get("master_of"))
        if derived and mp:                            # 从别的盘的项目文件分出来的盘：按方案重新生成这一盘（不能拷整份多盘文件）
            notes.append({"zh": "这一盘是从另一盘的项目文件里分出来的：按方案重新生成编辑文件（另一盘的设置不带过来）",
                          "th": "ถาดนี้แยกมาจากไฟล์โปรเจกต์ของอีกถาด: สร้างไฟล์แก้ไขใหม่ตามแผน"})
        if mp and m.get("app") == app and not derived:  # 已经有这个软件保存的主文件：接着改它（软件里的设置全保留）
            shutil.copyfile(mp, out)
            base = copy.deepcopy(plate)
            from_master = True
            written = {it["uid"]: sp.item_cis(pid, p, it) for it in base.get("items") or []}
        else:
            if mp and not derived:
                notes.append({"zh": f"主文件是 {sp.APPS.get(m.get('app'), '')} 保存的，换成 {sp.APPS[app]} 编辑会按方案重新生成（原来软件里的特别设置不带过去）",
                              "th": f"ไฟล์หลักบันทึกด้วย {sp.APPS.get(m.get('app'), '')} เปลี่ยนเป็น {sp.APPS[app]} จะสร้างใหม่ตามแผน (การตั้งค่าพิเศษเดิมไม่ติดไปด้วย)"})
            r = sp.build_project(pid, spec, plate_id, colour, app, out, p=p)
            base = r["plate"]
            written = r["written"]
            notes += r["notes"]
            from_master = False
        hexes = sp.plate_hexes(plan, base, colour)
        before = {"plate": copy.deepcopy(plate), "plate_ids": [x["id"] for x in plan["plates"]], "stored": spec in (p.get("print_plans") or {}),
                  "derived": [copy.deepcopy(x) for x in plan["plates"] if x.get("master_of") == plate_id]}
        fname = re.sub(r'[\\/:*?"<>|\s]+', "_", f"{pid}{'_' + spec if spec else ''}_{plate_id}_{'BambuStudio' if app == 'bambu' else 'Orca'}.3mf")
        s = {"id": sid, "pid": pid, "spec": spec, "plate": plate_id, "colour": colour or "", "app": app, "user": user,
             "display": display or user, "started": now, "touched": now, "status": "open", "token": secrets.token_urlsafe(24),
             "dl": secrets.token_urlsafe(18), "base": base, "written": written, "before": before, "hexes": {str(k): v for k, v in hexes.items()},
             "from_master": from_master, "notes": notes, "filename": fname, "syncs": 0, "last_sync": None,
             "gen_sha": _sha_file(out), "plate_no": 1, "plate_sig": _psig(plate)}
        d[sid] = s
        _save(d)
    return {"session": _public(s), "download": f"/api/slicer-edit/{sid}/file?t={s['dl']}",
            "upload": f"/api/slicer-edit/{sid}/upload?t={s['token']}", "filename": fname, "app_name": sp.APPS[app]}


def _sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def take_download(sid, tok):
    """一次性下载：返回 (文件路径, 文件名)。"""
    with _lock:
        d = _load()
        s = d.get(str(sid))
        if not s or s.get("status") != "open" or not tok or not secrets.compare_digest(str(s.get("dl") or ""), str(tok)):
            raise PermissionError("下载地址过期了，请在网页上重新点「编辑」/ ลิงก์ดาวน์โหลดหมดอายุ กรุณากด «แก้ไข» ในเว็บอีกครั้ง")
        s["dl"] = ""
        s["touched"] = time.time()
        _save(d)
    return os.path.join(DIR, sid + ".3mf"), s["filename"]


def check_token(sid, tok):
    s = get(sid)
    if not s or not tok or not secrets.compare_digest(str(s.get("token") or ""), str(tok)):
        raise PermissionError("编辑会话不对或已结束 / เซสชันแก้ไขไม่ถูกต้องหรือสิ้นสุดแล้ว")
    if s.get("status") != "open":
        raise PermissionError(ENDED)
    return s


def finish(sid, user="", owner=False):
    with _lock:
        d = _load()
        s = d.get(str(sid))
        if not s:
            raise ValueError("没有这个编辑会话 / ไม่มีเซสชันแก้ไขนี้")
        if s.get("user") != user and not owner:
            raise PermissionError("只有开始编辑的人（或老板）能结束这次编辑 / เฉพาะคนที่เริ่มแก้ไข (หรือเจ้าของ) จึงจบการแก้ไขได้")
        if s.get("status") == "open":
            s["status"] = "done"
            s["touched"] = time.time()
        _save(d)
    return _public(s)


def abandon(sid, user="", owner=False):
    """放弃：这次编辑回传的都不要了，这一盘恢复到开始编辑前（主文件、零件、新加的盘）。"""
    from . import printplan as pp
    with _lock:
        d = _load()
        s = d.get(str(sid))
        if not s:
            raise ValueError("没有这个编辑会话 / ไม่มีเซสชันแก้ไขนี้")
        if s.get("user") != user and not owner:
            raise PermissionError("只有开始编辑的人（或老板）能放弃这次编辑 / เฉพาะคนที่เริ่มแก้ไข (หรือเจ้าของ) จึงยกเลิกได้")
        if s.get("status") == "open" and s.get("syncs"):
            p = store.load(s["pid"])
            plans = p.get("print_plans") if isinstance(p.get("print_plans"), dict) else {}
            b = s["before"]
            if not b.get("stored"):
                plans.pop(s["spec"], None)
            elif s["spec"] in plans:
                plan = plans[s["spec"]]
                keep = set(b["plate_ids"])
                plan["plates"] = [copy.deepcopy(b["plate"]) if x["id"] == s["plate"] else x for x in plan["plates"]
                                  if x.get("master_of") != s["plate"] and (x["id"] in keep or x.get("edit_session") != sid)]
                plan["plates"] += [copy.deepcopy(x) for x in b.get("derived") or []]
                plan["updated_at"] = time.time()
            p["print_plans"] = plans
            pp._refresh_variants(p, s["spec"], pp.get_plan(p, s["spec"]))
            store.save(p)
        if s.get("status") == "open":
            s["status"] = "abandoned"
            s["touched"] = time.time()
        _save(d)
    return _public(s)


# ---------------- 主文件 ----------------
def _psig(pl):
    from . import printplan as pp
    return pp._sig({k: v for k, v in (pl or {}).items() if k not in pp.MASTER_KEYS})


def _referenced(pid, spec, plate_id):
    """这一盘的主文件目录里还被引用的文件：方案里所有盘的主文件 + 历史、打开中的会话开始前的那份。"""
    keep = set()
    try:
        p = store.load(pid)
    except FileNotFoundError:
        return keep
    plans = p.get("print_plans") if isinstance(p.get("print_plans"), dict) else {}
    for pl in ((plans.get(spec) or {}).get("plates") or []):
        if (pl.get("master_of") or pl.get("id")) != plate_id:
            continue
        m = pl.get("master") or {}
        keep |= {m.get("file")} | {h.get("file") for h in m.get("history") or []}
    for s in _load().values():
        if s.get("status") == "open" and s["pid"] == pid and s["spec"] == spec:
            m = ((s.get("before") or {}).get("plate") or {}).get("master") or {}
            keep |= {m.get("file")} | {h.get("file") for h in m.get("history") or []}
    keep.discard(None)
    return keep


def _store_master(pid, spec, plate_id, data, info, user):
    """原样存为这一盘的主文件（保留最近 HISTORY_MAX 个版本；方案 / 打开中的会话还在用的不删）。返回主文件记录（不含 history）。"""
    d = _master_dir(pid, spec, plate_id)
    os.makedirs(d, exist_ok=True)
    sha = hashlib.sha256(data).hexdigest()
    name = time.strftime("%Y%m%d-%H%M%S") + f"_{sha[:8]}.3mf"
    with open(os.path.join(d, name + ".part"), "wb") as f:
        f.write(data)
    os.replace(os.path.join(d, name + ".part"), os.path.join(d, name))
    keep = _referenced(pid, spec, plate_id) | {name}
    files = sorted(x for x in os.listdir(d) if x.endswith(".3mf"))
    for old in [x for x in files[:-HISTORY_MAX] if x not in keep]:
        try:
            os.remove(os.path.join(d, old))
        except OSError:
            pass
    return {"file": name, "sha": sha, "app": info.get("app"), "application": info.get("application") or "",
            "app_ver": info.get("app_ver") or "", "saved_at": time.time(), "by": user, "painted": bool(info.get("painted")),
            "size": len(data)}


def history(pid, spec, plate_id):
    d = _master_dir(pid, spec, plate_id)
    try:
        return sorted((x for x in os.listdir(d) if x.endswith(".3mf")), reverse=True)
    except OSError:
        return []


def valid_project(data):
    if not data or len(data) > MAX_UPLOAD:
        raise ValueError("文件是空的或太大 / ไฟล์ว่างหรือใหญ่เกินไป")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError("不是完整的 3MF 项目文件（软件还没保存完？）/ ไม่ใช่ไฟล์โปรเจกต์ 3MF ที่สมบูรณ์") from e
    zip_guard(z)                                   # 先查大小 / 压缩比，再解压校验
    try:
        if z.testzip() is not None:
            raise zipfile.BadZipFile("crc")
        if not any(n.lower() == "3d/3dmodel.model" for n in z.namelist()):
            raise ValueError
    except (zipfile.BadZipFile, ValueError) as e:
        raise ValueError("不是完整的 3MF 项目文件（软件还没保存完？）/ ไม่ใช่ไฟล์โปรเจกต์ 3MF ที่สมบูรณ์") from e


def zip_guard(z):
    """防 zip 炸弹：解压后总大小 ≤ 1.5 GB，大文件的压缩比 ≤ 400。"""
    tot = 0
    for i in z.infolist():
        tot += i.file_size
        if i.file_size > 20 * 1048576 and i.file_size > MAX_RATIO * max(1, i.compress_size):
            raise ValueError(f"文件里「{i.filename[:60]}」压缩比异常，不收 / ไฟล์ผิดปกติ (อัตราการบีบอัดสูงเกินไป)")
    if tot > MAX_UNZIP:
        raise ValueError("文件解压后太大（超过 1.5 GB）/ ไฟล์ใหญ่เกินไปเมื่อแตกไฟล์")


def _app_from(application, fallback):
    a = str(application or "").lower()
    if "orca" in a:
        return "orca"
    if "bambu" in a:
        return fallback if fallback in sp.APPS else "bambu"
    return fallback


# ---------------- 回传 → 同步 ----------------
def upload(sid, tok, data, now=None):
    """软件保存的项目 3MF 回传：存主文件 + 同步打印方案 + 安全核对。返回 {plate, confirm, changes, session}。"""
    s = check_token(sid, tok)
    valid_project(data)
    with _lock:
        cur0 = _load().get(sid)
        if not cur0 or cur0.get("status") != "open":     # 拿到锁之前别人完成 / 放弃了
            raise PermissionError(ENDED)
        s = cur0
        rp = sp.read_project(data)
        if not rp["objects"]:
            raise ValueError("文件里没有零件 / ไม่มีชิ้นงานในไฟล์")
        res = sync(s, data, rp)
        d = _load()
        cur = d.get(sid) or s
        cur["syncs"] = int(cur.get("syncs") or 0) + 1
        cur["last_sync"] = now or time.time()
        cur["touched"] = cur["last_sync"]
        cur["plate_no"] = 1
        cur["plate_sig"] = res.pop("_sig", cur.get("plate_sig"))
        d[sid] = cur
        _save(d)
    res["session"] = _public(cur)
    return res


def _tri_stl(path, tris):
    from core import mesh
    mesh.write_stl(tris, path)


def sync(s, data, rp, cfg=None):
    from core import modellib, recipes
    from . import printplan as pp
    cfg = cfg or load_config()
    pid, spec, plate_id, user = s["pid"], s["spec"], s["plate"], s.get("user") or ""
    p = store.load(pid)
    modellib._sync(p)
    plan, plate = _plan_and_plate(p, spec, plate_id)
    plan = copy.deepcopy(plan)
    plan.pop("default", None)
    plate = next(x for x in plan["plates"] if x["id"] == plate_id)
    if s.get("plate_sig") and _psig(plate) != s["plate_sig"]:     # 编辑期间这一盘在网页上被改过：不覆盖
        raise ValueError(f"这一盘在网页上被改过了（{plan.get('updated_by') or ''}），这次回传没有同步：请在浮条上「放弃」后重新编辑"
                         " / ถาดนี้ถูกแก้ในเว็บระหว่างแก้ไข ไม่ได้ซิงก์: กด «ยกเลิก» แล้วแก้ไขใหม่")
    # 以前从这一盘的项目文件分出来的盘（软件里的第 2、3… 盘）：这次按文件重新对应，同一个盘号沿用原来的盘 id，不重复加
    old_derived = {int((x.get("master") or {}).get("plate_no") or 0): x["id"] for x in plan["plates"] if x.get("master_of") == plate_id}
    plan["plates"] = [x for x in plan["plates"] if x.get("master_of") != plate_id]
    plate.pop("master_of", None)
    plate.pop("edit_session", None)
    base = s["base"]
    by_uid = {it["uid"]: it for it in base.get("items") or []}
    lib_ids = {e.get("id") for e in p.get("model_lib") or []}
    info = dict(rp, app=_app_from(rp.get("application"), s.get("app")))
    changes, confirm = [], []

    def need(zh, th, kind=GENERAL):
        confirm.append({"zh": zh, "th": th, "kind": kind})

    seen, per_plate, added_files = set(), {}, []
    written = s.get("written") or {}

    def placed(src, lin, world, name):
        """方案里的零件 src 在软件里的样子（网格 → 世界的线性变换 lin、世界坐标 world）→ 方向 / 转角 / 缩放 / 位置。"""
        dec = sp.decompose(sp.orient_matrix(src) @ np.asarray(lin, dtype=np.float64))
        it = {k: v for k, v in src.items() if k not in ("face", "mirror", "scale", "ov", "x", "y", "rot", "orient", "slot", "part_slots", "group")}
        it.update(orient=dec["orient"], rot=dec["rot"])
        if dec["face"]:
            it["face"] = dec["face"]
        if dec["mirror"]:
            it["mirror"] = dec["mirror"]
        if abs(dec["scale"] - 1) > 1e-3:
            it["scale"] = dec["scale"]
        if dec["nonuniform"]:
            need(f"「{name}」在软件里被拉伸（不等比缩放）或斜放：网页上的样子可能和软件里不一样，以软件保存的文件为准",
                 f"「{name}」ถูกยืดไม่เท่ากันหรือวางเอียงในโปรแกรม: ภาพในเว็บอาจไม่ตรงกับโปรแกรม ยึดตามไฟล์ที่โปรแกรมบันทึก")
        x, y = sp.place_xy(world, it["rot"])
        it.update(x=round(x, 1), y=round(y, 1))
        return it

    def new_model(parts, oname):
        """对应不上的零件（软件里新加的模型）：按软件里的样子存进模型库，标「需要确认」。"""
        nonlocal p, lib_ids
        w = np.concatenate([np.asarray(x["world"], dtype=np.float64) for x in parts])
        v = w.reshape(-1, 3)
        mn, mx = v.min(0), v.max(0)
        tris = w - np.array([(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]])
        nm = re.sub(r"\s*#[\w.]+$", "", parts[0]["name"] or oname or "part").strip() or "part"
        nm = re.sub(r'[\\/:*?"<>|]+', "_", nm)[:60]
        if not nm.lower().endswith(".stl"):
            nm += ".stl"
        os.makedirs(DIR, exist_ok=True)
        tmp = os.path.join(DIR, f"new_{secrets.token_hex(4)}.stl")
        _tri_stl(tmp, tris)
        ent = modellib.upload(pid, [modellib.SavedFile(tmp, nm)], user)
        p = store.load(pid)
        lib_ids = {e.get("id") for e in p.get("model_lib") or []}
        added_files.append(ent[0]["id"])
        need(f"「{nm}」对应不上方案里的零件（软件里新加的模型）：已存进模型库、放在这一盘，确认是要打的",
             f"「{nm}」ไม่ตรงกับชิ้นงานในแผน (โมเดลใหม่จากโปรแกรม): เก็บในคลังโมเดลและวางในถาดนี้แล้ว กรุณายืนยัน")
        x, y = (mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2
        return {"uid": pp._uid(), "id": ent[0]["id"], "part": None, "orient": "bottom", "rot": 0, "x": round(float(x), 1),
                "y": round(float(y), 1), "slot": int(parts[0]["extruder"] or 1)}

    for ob in rp["objects"]:
        if not ob.get("printable", True):
            continue
        refs, unknown = {}, []
        for pt in ob["parts"]:
            src_ = pt.get("src")
            if src_ and src_[0] in by_uid and by_uid[src_[0]].get("id") in lib_ids:
                refs.setdefault(src_[0], []).append(pt)
            elif pt["subtype"] == "normal_part":
                unknown.append(pt)
        if not refs and not unknown:
            continue
        if not refs and ob["uid"] in by_uid and by_uid[ob["uid"]].get("id") in lib_ids:
            refs[ob["uid"]] = [dict(pt, src=(ob["uid"], (by_uid[ob["uid"]].get("part") or 0), None)) for pt in ob["parts"]]
            unknown = []
        made = []
        for u, pts in refs.items():
            src = by_uid[u]
            first = u not in seen
            seen.add(u)
            cis = sorted({pt["src"][1] for pt in pts})
            whole = src.get("part") in (None, "")
            allc = written.get(u) or sp.item_cis(pid, p, src)
            if whole and set(cis) >= set(allc):
                specs = [(None, pts)]
            elif whole:                                # 组合拆开了 / 删了其中的零件：每个组件一件（part = 组件序号）
                specs = [(c, [pt for pt in pts if pt["src"][1] == c]) for c in cis]
                changes.append(("组合拆成了零件 / 删了其中的零件", "แยกชิ้นส่วนของชุด / ลบบางชิ้น", f"{ob['name']}: {cis}"))
            else:
                specs = [(src.get("part"), pts)]
            for k, (part, ppts) in enumerate(specs):
                norm = [pt for pt in ppts if pt["subtype"] == "normal_part"] or ppts
                world = np.concatenate([np.asarray(pt["world"]) for pt in ppts])
                psrc = dict(src)
                it = placed(psrc, norm[0]["lin"], world, ob["name"])
                it["part"] = part
                it["uid"] = u if first and k == 0 else pp._uid()
                if not first and k == 0:
                    changes.append(("复制了零件", "คัดลอกชิ้นงาน", ob["name"]))
                if part is None:
                    pslots = {}
                    for pt in norm:
                        pslots.setdefault(str(pt["src"][1]), int(pt["extruder"] or 1))
                    it["slot"] = int(norm[0]["extruder"] or ob["extruder"] or 1)
                    if len(set(pslots.values())) > 1 or (pslots and next(iter(pslots.values())) != it["slot"]):
                        it["part_slots"] = pslots
                    ov = dict(ob.get("ov") or {})
                else:
                    it["slot"] = int(norm[0]["extruder"] or ob["extruder"] or 1)
                    ov = dict(norm[0].get("ov") or {}) or (dict(ob.get("ov") or {}) if len(ob["parts"]) == 1 else {})
                if ov:
                    it["ov"] = ov
                made.append((it, {"name": ob["name"], "world": world}))
        for pt in unknown:
            it = new_model([pt], ob["name"])
            made.append((it, {"name": pt["name"], "world": np.asarray(pt["world"])}))
        sets = [st for pt in ob["parts"] for st in [pt.get("settings")] if st] + ([ob["settings"]] if ob.get("settings") else [])
        if sets:
            changes.append(("零件在软件里有单独设置（保留在主文件里）", "ชิ้นงานมีการตั้งค่าแยกในโปรแกรม (เก็บไว้ในไฟล์หลัก)",
                            f"{ob['name']}: " + ", ".join(f"{k}={v}" for st in sets for k, v in list(st.items())[:4])[:200]))
        if len(made) > 1:                              # 软件里一个对象（组合）= 方案里成组的几件（一起移动）
            olds = {by_uid[u].get("group") for u in refs if by_uid[u].get("group")}
            grp = olds.pop() if len(olds) == 1 and all(it["uid"] in by_uid for it, _o in made[:1]) else "g" + secrets.token_hex(3)
            for it, _o in made:
                it["group"] = grp
        for it, o in made:
            per_plate.setdefault(int(ob.get("plate") or 1), []).append((it, o))
    gone = [it for u, it in by_uid.items() if u not in seen]
    for it in gone:
        changes.append(("删掉了零件", "ลบชิ้นงาน", it.get("uid")))
    # 耗材列表 → 槽
    fil = rp.get("filaments") or []
    old_slots = base.get("slots") or plate.get("slots") or []
    slots = []
    from core import codes
    rev = {(v.get("hex") or "").upper(): k for k, v in codes.color_hex(cfg).items() if v.get("hex")}
    for i, f in enumerate(fil[:pp.SLOT_MAX]):
        o = old_slots[i] if i < len(old_slots) else {"slot": i + 1, "material": f.get("type") or "PLA", "colour": ""}
        mat = recipes.norm_material(f.get("type") or o.get("material") or "PLA")
        ns = {"slot": i + 1, "material": mat if f.get("type") else (o.get("material") or "PLA"), "colour": o.get("colour") or ""}
        for k in ("file_slot",):
            if o.get(k):
                ns[k] = o[k]
        if f.get("type") and recipes.same_material(f["type"], o.get("material") or "PLA") == "diff" and i < len(old_slots):
            need(f"槽 {i + 1} 在软件里换成了 {mat}（原来是 {o.get('material')}）：确认材料、温度、AMS 里装的料",
                 f"ช่อง {i + 1} ถูกเปลี่ยนเป็น {mat} ในโปรแกรม (เดิม {o.get('material')}): ตรวจวัสดุ อุณหภูมิ และเส้นใน AMS", MATERIAL)
        want = (s.get("hexes") or {}).get(str(i + 1))
        if f.get("hex") and want and f["hex"].upper() != want.upper():
            ns["hex"] = f["hex"].upper()
            name = rev.get(f["hex"].upper())
            if name:
                ns["colour"] = name
            changes.append(("槽的颜色在软件里改了", "สีของช่องถูกเปลี่ยนในโปรแกรม", f"{i + 1}: {want} → {f['hex']}" + (f"（{name}）" if name else "")))
        slots.append(ns)
    if len(fil) > pp.SLOT_MAX:
        need(f"软件里用了 {len(fil)} 种耗材，AMS 最多 {pp.SLOT_MAX} 槽：多出来的没有对应槽",
             f"ในโปรแกรมใช้ {len(fil)} ฟิลาเมนต์ แต่ AMS มีได้สูงสุด {pp.SLOT_MAX} ช่อง")
    if not slots:
        slots = copy.deepcopy(old_slots) or [{"slot": 1, "material": p.get("material") or "PLA", "colour": ""}]
    # 耗材配置自己的材料（v2.55 规则：PLA 的配置不能打 PETG）
    try:
        from core import slicer
        from core import orca_profiles as op
        exe = slicer.find_orca(cfg)
        idx = op.build_index(exe) if exe else None
    except Exception:  # noqa: BLE001
        idx = None
    for i, f in enumerate(fil[:pp.SLOT_MAX]):
        if idx and f.get("profile"):
            ft = op.filament_type(idx, f["profile"])
            if ft and recipes.same_material(ft, f.get("type") or slots[i]["material"]) == "diff":
                need(f"槽 {i + 1} 的耗材配置「{f['profile']}」是 {ft}，材料写的是 {f.get('type')}：温度可能不对",
                     f"โปรไฟล์ช่อง {i + 1}「{f['profile']}」เป็น {ft} แต่วัสดุคือ {f.get('type')}: อุณหภูมิอาจไม่ถูก", MATERIAL)
    # 组装盘
    new_plates = []
    for no in sorted(per_plate):
        items = [it for it, _ob in per_plate[no]]
        for it in items:
            if int(it.get("slot") or 1) > len(slots):
                need(f"零件用了第 {it['slot']} 个耗材，盘上只有 {len(slots)} 个槽", f"ชิ้นงานใช้ฟิลาเมนต์ที่ {it['slot']} แต่มีแค่ {len(slots)} ช่อง")
                it["slot"] = 1
        if no == 1:
            tgt = plate
        else:
            tgt = {k: copy.deepcopy(v) for k, v in plate.items() if k not in ("items", "sliced", "master", "confirm", "confirmed")}
            tgt["id"] = old_derived.get(no) or f"p{pp._free_plate_id({'plates': plan['plates'] + new_plates})}"
            while tgt["id"] in {x["id"] for x in plan["plates"] + new_plates}:
                tgt["id"] = f"p{pp._free_plate_id({'plates': plan['plates'] + new_plates + [{'id': tgt['id']}]})}"
            tgt["name"] = ""
            tgt["edit_session"] = s["id"]
            new_plates.append(tgt)
            changes.append(("软件里多了一盘 → 方案里新的一盘", "มีถาดเพิ่มในโปรแกรม → ถาดใหม่ในแผน", f"{no} → {tgt['id']}"))
        tgt["items"] = items
        tgt["slots"] = copy.deepcopy(slots)
        tgt["manual"] = True
        tgt.pop("sliced", None)
        tgt.pop("confirmed", None)
    if 1 not in per_plate:
        plate["items"] = []
        need("软件里第 1 盘没有零件了", "ถาดที่ 1 ในโปรแกรมไม่มีชิ้นงานแล้ว")
    plan["plates"] += new_plates
    # 打印机 / 喷嘴 / 热床板
    tpl = fleet.template_of(plate.get("printer"), cfg)
    from modules.prod import slicecheck
    if rp.get("printer_profile"):
        fm = slicecheck.model_of_profile(rp["printer_profile"], cfg)
        if not fm:
            need(f"认不出软件里选的打印机「{rp['printer_profile']}」是哪个机型，这一盘是「{plate.get('printer')}」",
                 f"ไม่รู้จักเครื่องพิมพ์「{rp['printer_profile']}」ที่เลือกในโปรแกรม ถาดนี้คือ「{plate.get('printer')}」", MACHINE)
        elif slicecheck._norm(fm) != slicecheck._norm(plate.get("printer")):
            need(f"软件里选的打印机是「{fm}」，这一盘是「{plate.get('printer')}」：切出来的文件不能发到这台机型",
                 f"เครื่องพิมพ์ในโปรแกรมคือ「{fm}」แต่ถาดนี้คือ「{plate.get('printer')}」: ไฟล์ที่สไลซ์ส่งไปเครื่องรุ่นนี้ไม่ได้", MACHINE)
    else:
        need("文件里没有打印机配置（不是软件保存的完整项目？）", "ไม่มีโปรไฟล์เครื่องพิมพ์ในไฟล์ (ไม่ใช่โปรเจกต์ที่โปรแกรมบันทึก?)", MACHINE)
    want_nz = float(tpl.get("nozzle") or 0.4)
    if rp.get("nozzle") and abs(float(rp["nozzle"]) - want_nz) > 0.01:
        need(f"软件里是 {rp['nozzle']:g} mm 喷嘴，这台机型设置的是 {want_nz:g} mm", f"ในโปรแกรมใช้หัวฉีด {rp['nozzle']:g} มม. แต่รุ่นนี้ตั้งไว้ {want_nz:g} มม.", MACHINE)
    if tpl.get("plate") and rp.get("bed_type") and slicecheck._norm(tpl["plate"]) != slicecheck._norm(rp["bed_type"]):
        need(f"软件里选的热床板是「{rp['bed_type']}」，打印机现在装的是「{tpl['plate']}」",
             f"แผ่นฐานในโปรแกรมคือ「{rp['bed_type']}」แต่เครื่องใส่「{tpl['plate']}」", MACHINE)
    # 热床范围 / 废料口（按软件里零件真实的外形）
    bed = pp.bed_of(plate.get("printer"), cfg)
    excl = pp.exclude_of(plate.get("printer"))
    for no in sorted(per_plate):
        for it, ob in per_plate[no]:
            v = np.asarray(ob["world"]).reshape(-1, 3)
            mn, mx = v.min(0), v.max(0)
            if mn[0] < -sp_tol() or mn[1] < -sp_tol() or mx[0] > bed[0] + sp_tol() or mx[1] > bed[1] + sp_tol() or mx[2] > bed[2] + sp_tol():
                need(f"「{ob['name']}」超出热床范围（{bed[0]:g}×{bed[1]:g}×{bed[2]:g} mm）", f"「{ob['name']}」เกินพื้นที่ฐานพิมพ์")
            if excl and mn[0] < excl[2] and mx[0] > excl[0] and mn[1] < excl[3] and mx[1] > excl[1]:
                need(f"「{ob['name']}」压到左前角的废料口（{excl[2]:g}×{excl[3]:g} mm）", f"「{ob['name']}」ทับช่องทิ้งเศษด้านหน้าซ้าย")
    used = {int(it.get("slot") or 1) for no in per_plate for it, _ob in per_plate[no]} | set(sum((ob["part_extruders"] for ob in rp["objects"]), []))
    multi = len(used) > 1 or rp.get("painted")
    pr = next((m for m in pp.printer_models(cfg) if m["name"] == plate.get("printer")), {})
    if multi and pr.get("multicolor") is False:
        need("这一盘是多色的，这台机型没有 AMS", "ถาดนี้หลายสี แต่เครื่องรุ่นนี้ไม่มี AMS", MACHINE)
    # 主文件
    m = _store_master(pid, spec, plate_id, data, info, user)
    hist = [{k: (plate.get("master") or {}).get(k) for k in ("file", "sha", "saved_at", "by", "app_ver")}] if plate.get("master") else []
    hist += list((plate.get("master") or {}).get("history") or [])
    keep = set(history(pid, spec, plate_id))
    m["history"] = [h for h in hist if h.get("file") in keep][:HISTORY_MAX - 1]
    m["plate_no"] = 1
    plate["master"] = m
    for k, tp in enumerate(new_plates):
        tp["master"] = dict(m, plate_no=sorted(per_plate)[k + 1], history=[])
        tp["master_of"] = plate_id
    for tp in [plate] + new_plates:
        tp["confirm"] = copy.deepcopy(confirm)
    # 保存（不走 save_plan：超出热床等要标「需要确认」而不是拒收）
    old_plan = pp.get_plan(p, spec)
    cleaned = pp.clean_plan(p, plan, cfg)
    extra = {x["id"]: {k: x[k] for k in ("master", "confirm", "master_of", "edit_session") if k in x} for x in plan["plates"]}
    for x in cleaned["plates"]:
        x.update(extra.get(x["id"]) or {})
        x.pop(pp.AUTO_PRM, None)
        if x["id"] == plate_id or x["id"] in {t["id"] for t in new_plates}:
            x.pop("sliced", None)
    cleaned["updated_at"], cleaned["updated_by"] = time.time(), user
    if not isinstance(p.get("print_plans"), dict):
        p["print_plans"] = {}
    p["print_plans"][spec] = cleaned
    pp._sync_material(p, spec, old_plan, cleaned)
    pp._mirror_recipe(p, spec, cleaned, user)
    pp._refresh_variants(p, spec, cleaned)
    store.save(p)
    # 主文件变了：这一盘（和分出来的盘）以前按方案切的文件作废，生产不会拿旧文件发打印
    for pid_ in [plate_id] + [t["id"] for t in new_plates] + [v for v in old_derived.values() if v not in {t["id"] for t in new_plates}]:
        pp.retire_plate_files(pid, spec, pid_, user, "切片软件回传了新的主文件")
    from core import db
    db.audit(user, f"在 {sp.APPS.get(info['app'], '')} 里编辑打印方案（回传同步）", pid,
             f"{spec or '主模型'} {plate_id}：{len(rp['objects'])} 个零件" + (f"，需要确认 {len(confirm)} 项" if confirm else ""))
    out_plate = next(x for x in cleaned["plates"] if x["id"] == plate_id)
    return {"plate": out_plate, "new_plates": [t["id"] for t in new_plates], "confirm": confirm,
            "changes": [{"zh": a, "th": b, "detail": str(c)} for a, b, c in changes], "deleted": len(gone), "added_files": added_files,
            "master": {k: v for k, v in m.items() if k != "history"}, "_sig": _psig(out_plate)}


def sp_tol():
    return 0.5


# ---------------- 需要确认 ----------------
def confirm_plate(pid, spec, plate_id, user="", owner=True):
    p = store.load(pid)
    plans = p.get("print_plans") or {}
    plan = plans.get((spec or "").strip())
    if not plan:
        raise ValueError("没有这个打印方案 / ไม่มีแผนการพิมพ์นี้")
    pl = next((x for x in plan.get("plates") or [] if x["id"] == plate_id), None)
    if not pl:
        raise ValueError("没有这一盘 / ไม่มีถาดนี้")
    if any(c.get("kind") == MACHINE for c in pl.get("confirm") or []) and not owner:
        raise PermissionError("机型 / 喷嘴 / 热床板 / AMS 这类问题关系到打印机安全，只有老板能确认"
                              " / เรื่องรุ่นเครื่อง หัวฉีด แผ่นฐาน AMS เกี่ยวกับความปลอดภัยของเครื่อง เฉพาะเจ้าของยืนยันได้")
    if pl.get("confirm"):
        pl["confirmed"] = {"by": user, "at": time.time(), "what": [c["zh"] for c in pl["confirm"]]}
        pl["confirm"] = []
        store.save(p)
        from core import db
        db.audit(user, "确认切片软件回传的问题", pid, f"{spec or '主模型'} {plate_id}：" + "；".join(pl["confirmed"]["what"])[:300])
    return pl


# ---------------- 切主文件 ----------------
def recolour(src, dst, colours):
    """主文件按款式换颜色（同材料只换颜色）：改 project_settings 的 filament_colour，其它原样。"""
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for i in zi.infolist():
            data = zi.read(i.filename)
            if i.filename == "Metadata/project_settings.config":
                try:
                    ps = json.loads(data)
                    cols = list(ps.get("filament_colour") or [])
                    for k, c in enumerate(colours or []):
                        if c and k < len(cols):
                            cols[k] = c
                    ps["filament_colour"] = cols
                    data = json.dumps(ps, ensure_ascii=False, indent=4).encode()
                except ValueError:
                    pass
            zo.writestr(i, data)
    return dst


def slice_master(cfg, path, plate_no=1, material="PLA", timeout=900, keep_to=None, colours=None):
    """直接用 OrcaSlicer 切主文件（不加载我们的配置，用文件里软件保存的全部设置）。失败抛 SliceError。
    colours：按款式每个槽的颜色（同材料只换颜色）。"""
    import subprocess
    import tempfile
    from core import slicer
    exe = slicer.find_orca(cfg)
    if not exe:
        raise slicer.SliceError("没有找到 OrcaSlicer")
    d = tempfile.mkdtemp(prefix="master_")
    try:
        src = os.path.join(d, "master.3mf")
        if colours:
            recolour(path, src, colours)
        else:
            shutil.copyfile(path, src)
        cmd = [exe, "--slice", str(int(plate_no or 1)), "--allow-newer-file", "--outputdir", d, "--export-3mf", "result.gcode.3mf", src]
        try:
            r = subprocess.run(cmd, cwd=d, capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as e:
            raise slicer.SliceError(f"切片超时（{timeout} 秒）") from e
        out = os.path.join(d, "result.gcode.3mf")
        if r.returncode != 0 or not os.path.exists(out):
            rc = slicer.rc_signed(r.returncode)
            raise slicer.SliceError(f"主文件切片没有成功（返回码 {rc}{'：' + slicer.ORCA_RC[rc] if rc in slicer.ORCA_RC else ''}）")
        res = slicer.parse_sliced_file(out, material)
        if keep_to:
            shutil.copyfile(out, keep_to)
            res["kept"], res["kept_kind"] = keep_to, "3mf"
        res["source"] = "orca_master"
        return res
    finally:
        shutil.rmtree(d, ignore_errors=True)
