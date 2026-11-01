"""打印机机群：机器编码、常用机型、增删打印机时保持任务对应关系。

每台打印机（设置里 printers 列表的一行）：
  code     机器编码，唯一，例如 P1S-01（贴在机器上，生产单、任务、记录都显示它）
  name     机型，例如 Bambu Lab P1S —— 同机型的打印机共用切片文件和打印方案，互为备用
  enabled  是否参与排单（维修 / 停用时关掉，任务自动转到同机型或其他机器）
  g_per_h、orca_*、conn 同以前
任务和打印记录里存的是打印机序号；改顺序、删除打印机时用编码把序号对回来。
"""
import re
import time

from . import db

# 常用机型（拓竹主流 + 创想三维 K 系列）。bed：打印范围 X×Y×Z（毫米）；g_per_h：估算用每小时克数
MODELS = [
    {"name": "Bambu Lab A1 mini", "prefix": "A1M", "brand": "bambu", "bed": [180, 180, 180], "g_per_h": 15},
    {"name": "Bambu Lab A1", "prefix": "A1", "brand": "bambu", "bed": [256, 256, 256], "g_per_h": 20},
    {"name": "Bambu Lab P1P", "prefix": "P1P", "brand": "bambu", "bed": [256, 256, 256], "g_per_h": 22},
    {"name": "Bambu Lab P1S", "prefix": "P1S", "brand": "bambu", "bed": [256, 256, 256], "g_per_h": 22},
    {"name": "Bambu Lab P2S", "prefix": "P2S", "brand": "bambu", "bed": [256, 256, 256], "g_per_h": 25},
    {"name": "Bambu Lab X1 Carbon", "prefix": "X1C", "brand": "bambu", "bed": [256, 256, 256], "g_per_h": 24},
    {"name": "Bambu Lab X1E", "prefix": "X1E", "brand": "bambu", "bed": [256, 256, 256], "g_per_h": 24},
    {"name": "Bambu Lab H2S", "prefix": "H2S", "brand": "bambu", "bed": [340, 320, 340], "g_per_h": 26},
    {"name": "Bambu Lab H2D", "prefix": "H2D", "brand": "bambu", "bed": [325, 320, 325], "g_per_h": 28},
    {"name": "Creality K1C", "prefix": "K1C", "brand": "creality", "bed": [220, 220, 250], "g_per_h": 18},
    {"name": "Creality K1", "prefix": "K1", "brand": "creality", "bed": [220, 220, 250], "g_per_h": 18},
    {"name": "Creality K1 Max", "prefix": "K1M", "brand": "creality", "bed": [300, 300, 300], "g_per_h": 20},
    {"name": "Creality K2 Plus", "prefix": "K2P", "brand": "creality", "bed": [350, 350, 350], "g_per_h": 24},
    # 光固化（树脂）：打印时间主要看高度，一盘放多少个时间差不多；切片要在电脑上用厂家软件做
    {"name": "Anycubic Photon Mono M5s", "prefix": "M5S", "brand": "anycubic", "tech": "resin", "bed": [218, 123, 200], "g_per_h": 0, "ext": [".pm5s"]},
    {"name": "Anycubic Photon Mono M5", "prefix": "M5", "brand": "anycubic", "tech": "resin", "bed": [218, 123, 200], "g_per_h": 0, "ext": [".pm5"]},
    {"name": "Anycubic Photon Mono M7 Pro", "prefix": "M7P", "brand": "anycubic", "tech": "resin", "bed": [223, 126, 230], "g_per_h": 0, "ext": [".pm7"]},
    {"name": "Elegoo Saturn 4 Ultra", "prefix": "ST4U", "brand": "elegoo", "tech": "resin", "bed": [218, 123, 220], "g_per_h": 0, "ext": [".goo"]},
    {"name": "Elegoo Mars 5 Ultra", "prefix": "MS5U", "brand": "elegoo", "tech": "resin", "bed": [153, 77, 165], "g_per_h": 0, "ext": [".goo"]},
]
RESIN_EXT = (".pm5s", ".pm5", ".pm7", ".pm7m", ".pm4n", ".pm4u", ".pm3", ".pm3m", ".pm3r", ".pwmx", ".pwma", ".pwmb",
             ".pwmo", ".pwms", ".pws", ".pw0", ".pwx", ".dlp", ".dl2p", ".pmx2", ".pwc", ".ctb", ".cbddlp", ".goo",
             ".prz", ".jxs", ".zip")
RESIN_MATERIALS = ["RESIN", "RESIN-ABS", "RESIN-WASH", "RESIN-TOUGH", "RESIN-8K"]
RESIN_ZH = {"RESIN": "标准树脂", "RESIN-ABS": "类 ABS 树脂", "RESIN-WASH": "水洗树脂", "RESIN-TOUGH": "高韧性树脂", "RESIN-8K": "8K 高精度树脂"}


def is_resin(material):
    m = str(material or "").upper()
    return m.startswith("RESIN") or "树脂" in m or "เรซิ่น" in m


def tech_of(p):
    """打印机是 FDM 还是光固化：设置里写了就用设置的，否则按机型判断。"""
    t = (p or {}).get("tech")
    if t in ("fdm", "resin"):
        return t
    m = model_info((p or {}).get("name"))
    return (m or {}).get("tech", "fdm")


def is_multicolor(p):
    """v2.52：这台打印机能不能打多色（有 AMS / 多色）。设置里勾了就按设置；没设置时拓竹 A1 / P1S / P2S / X1 / H2 系列算能
    （常配 AMS），P1P、创想三维 K1 / K1C / K1 Max 算不能。v2.54：先按机型模板 + 单台覆盖（effective）。"""
    if p and "ams" not in p and "_eff" not in p and p.get("name"):
        try:
            p = effective(p)
        except Exception:  # noqa: BLE001  读不到设置时按机型判断
            pass
    v = (p or {}).get("ams")
    if v in (True, False):
        return v
    if isinstance(v, str) and v.strip():
        return v.strip().lower() in ("1", "true", "yes", "on")
    if tech_of(p) == "resin":
        return False
    m = model_info((p or {}).get("name")) or {}
    return m.get("brand") == "bambu" and m.get("prefix") != "P1P"


def job_tech(material):
    return "resin" if is_resin(material) else "fdm"
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,15}$")
# 存打印机序号的表（v2.54 复审：查过所有建表语句，printer INTEGER 只有这些；print_files.printer 是机型名，
# inv_moves / inv_docs / spools 存的是机器编码，production_orders.printers 存编码，inv_printer_locs 按编码对）
PRINTER_TABLES = ("jobs", "print_runs", "failures", "maintenance", "job_plates", "trials")
PIN_TABLES = ("jobs", "job_plates")      # 删掉的打印机：固定（pin）在它上面的任务 / 盘取消固定，重新排单


def _short(name):
    return re.sub(r"^(bambulab|creality)", "", re.sub(r"[^a-z0-9]", "", (name or "").lower()))


def model_info(name):
    """按名字找机型（容错：大小写、空格、"Bambu Lab"/"Creality" 可省略）。名字里包含的最长机型名胜出。"""
    n = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    hits = [m for m in MODELS if _short(m["name"]) and _short(m["name"]) in n]
    return max(hits, key=lambda m: len(_short(m["name"]))) if hits else None


def prefix_for(name):
    m = model_info(name)
    if m:
        return m["prefix"]
    w = re.sub(r"(?i)\b(bambu\s*lab|creality|printer)\b", "", name or "").strip()
    w = re.sub(r"[^A-Za-z0-9]", "", w).upper()
    return (w[:4] or "PR")


def ensure_codes(printers):
    """没有编码 / 编码重复的打印机自动编上（机型前缀-两位序号）。返回是否改过。"""
    changed = False
    used = set()
    for p in printers:
        c = str(p.get("code") or "").strip().upper()
        if c and CODE_RE.match(c) and c not in used:
            if p.get("code") != c:
                p["code"] = c
                changed = True
            used.add(c)
        else:
            p["code"] = ""
    for p in printers:
        if not p["code"]:
            pre = prefix_for(p.get("name"))
            n = 1
            while f"{pre}-{n:02d}" in used:
                n += 1
            p["code"] = f"{pre}-{n:02d}"
            used.add(p["code"])
            changed = True
        if "enabled" not in p:
            p["enabled"] = True
            changed = True
        if p.get("tech") not in ("fdm", "resin"):
            p["tech"] = tech_of(p)
            changed = True
    return changed


def label(p, i=None):
    """显示用：P1S-01 · Bambu Lab P1S"""
    code = p.get("code") or (f"#{i + 1}" if i is not None else "")
    return f"{code} · {p.get('name') or ''}".strip(" ·")


def match(old, new):
    """v2.54：旧列表的序号 → 新列表的序号（按稳定 id 对；没有 id 的旧数据按编码对）。对不上 = None（删掉了）。"""
    nid = {p.get("id"): j for j, p in enumerate(new) if p.get("id")}
    ncode = {p.get("code"): j for j, p in enumerate(new) if p.get("code")}
    old_ids = {p.get("id") for p in old if p.get("id")}
    out = {}
    for i, p in enumerate(old):
        pid, code = p.get("id"), p.get("code")
        j = nid.get(pid) if pid else None
        if j is None and code in ncode:
            cand = new[ncode[code]]
            if not cand.get("id") or not pid or cand.get("id") not in old_ids:
                j = ncode[code]
        out[i] = j
    return out


def remap(old, new):
    """打印机列表改了（排序 / 删除 / 新增）：把任务、打印记录、保养记录里的序号对到新位置（v2.54 按稳定 id 对，
    改编码不再当成删掉）。被删掉的打印机：没开始的任务清空打印机（重新排单）；正在打印的不允许删（调用前检查）。"""
    m = match(old, new)
    mapping = {i: j for i, j in m.items() if j != i}
    old_codes = [p.get("code") for p in old]
    c = db.conn()
    has_spools = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='spools'").fetchone()
    gone = [old_codes[i] for i, j in m.items() if j is None and old_codes[i]]
    # v2.41 复审：同一个位置的编码换成了一个新编码 = 改名，不是删掉 → 料卷跟着换到新编码上，不卸下来
    new_codes_all = {p.get("code") for p in new}
    for i, code in enumerate(old_codes):
        if code in gone and i < len(new) and new[i].get("code") and new[i].get("code") not in old_codes \
                and i not in [j for j in m.values() if j is not None]:
            if has_spools:
                c.execute("UPDATE spools SET printer=?, updated_at=? WHERE status='loaded' AND printer=?", (new[i]["code"], time.time(), code))
            gone.remove(code)
    # v2.54：同一台（id 一样）改了编码 → 料卷等跟着改（v2.55：两台互换编码也不会串，见 fleetcodes.rename_codes）
    ren = [(old_codes[i], new[j]["code"]) for i, j in m.items()
           if j is not None and old_codes[i] and new[j].get("code") and new[j].get("code") != old_codes[i]]
    if ren and has_spools:
        from . import fleetcodes
        fleetcodes.rename_codes(ren)
    gone = [g for g in gone if g not in new_codes_all]
    if gone and has_spools:
        # v2.41：删掉的打印机上装着的料卷 → 取下来放回库里（以前一直挂在已经不存在的编码上，新加的同型号打印机会「继承」它）
        c.execute(f"UPDATE spools SET status='open', printer=NULL, slot=NULL, updated_at=? WHERE status='loaded' AND printer IN "
                  f"({','.join('?' * len(gone))})", (time.time(), *gone))
    c.commit()
    if not mapping:
        return {}
    for t in PRINTER_TABLES:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
            continue
        # 先挪到负数，避免 0→1、1→0 互相覆盖
        for i, j in mapping.items():
            c.execute(f"UPDATE {t} SET printer=? WHERE printer=?", (-1000 - i, i))
        for i, j in mapping.items():
            if j is None:
                if t in PIN_TABLES:
                    c.execute(f"UPDATE {t} SET printer=NULL, pin=0 WHERE printer=?", (-1000 - i,))
                else:
                    c.execute(f"UPDATE {t} SET printer=NULL WHERE printer=?", (-1000 - i,))
            else:
                c.execute(f"UPDATE {t} SET printer=? WHERE printer=?", (j, -1000 - i))
    c.commit()
    from . import printers as pr
    pr.remap_status(mapping)
    return mapping


def busy_codes(old, new):
    """要删掉的打印机里，还有正在打印的 → 不能删。"""
    m = match(old, new)
    out = []
    c = db.conn()
    for i, p in enumerate(old):
        if m.get(i) is None:
            n = c.execute("SELECT COUNT(*) FROM print_runs WHERE status='printing' AND printer=?", (i,)).fetchone()[0]
            if n:
                out.append(p.get("code"))
    return out


# =====================================================================================================
# v2.54 打印机机群（几百到几千台）：机型模板 + 单台覆盖、稳定 id、分组 / 位置 / 用途、厂家表单、批量导入
#
# 稳定身份的做法（v2.54 的选择）：每台打印机有一个永远不变的 id（p + 10 位随机），新接口和页面都用 id；
# 数据库里的任务 / 打印记录 / 失败 / 保养照旧存序号（几十处 SQL 在用，全改风险大），新增打印机只往后加（序号不变），
# 删除时 remap() 按 id 把序号对到新位置（以前按编码对，改编码会被当成删掉）；状态缓存按 id 跟着挪，不清空。
# =====================================================================================================
import ipaddress
import uuid

# 机型模板里的字段：同机型的打印机默认都用模板的值，单台只在「单独设置」的地方覆盖（例如这台装了 0.6 喷嘴）
TPL_FIELDS = ("nozzle", "plate", "g_per_h", "ams", "orca_machine", "orca_process", "orca_filament")
# v2.54 复审：喷嘴和热床板是每台自己的（换过 0.6 喷嘴的那台不能让同机型的新打印机「继承」）——迁移不放进模板，
# 添加打印机时要明确填喷嘴
PER_PRINTER = ("nozzle", "plate")
ROLES = ("any", "orders", "stock")          # 用途：都可以 / 只打订单 / 只打备货（排单那边读）
ROLE_ZH = {"any": ("都可以", "ทั้งหมด"), "orders": ("只打订单", "เฉพาะออเดอร์"), "stock": ("只打备货", "เฉพาะสต็อก")}
# 每台打印机 v2.54 新增的字段（排单那边只读这些）：分组、位置（货架-层-位）、用途、专门打的生产单、暂停接单（保养）
NEW_DEFAULTS = {"group": "", "location": "", "role": "any", "dedicated_po": "", "paused": False}
LOC_RE = re.compile(r"^[A-Za-z]{1,3}[\-\s]?\d{1,3}([\-\s]\d{1,3}){0,3}$")
LOC_WORDS = ("货架", "架", "层", "区", "排", "rack", "shelf", "ชั้น", "โซน")


def _num(v, lo, hi):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if lo <= x <= hi else None


def clean_value(f, v):
    """模板 / 覆盖里的一个值整理成标准格式；None = 没设置（跟随模板 / 机型默认）。"""
    if v is None:
        return None
    if f == "nozzle":
        return _num(v, 0.1, 2)
    if f == "g_per_h":
        return _num(v, 0.01, 10000)
    if f == "ams":
        if v in (True, False):
            return v
        s = str(v).strip().lower()
        if s in ("", "auto", "none", "null"):
            return None
        return s in ("1", "true", "yes", "on", "是")
    s = str(v).strip().strip('"')
    return s[:160] if s else None


def builtin_template(name):
    """常用机型表里自带的默认值（目前只有每小时克数）。"""
    m = model_info(name) or {}
    out = {}
    if m.get("g_per_h"):
        out["g_per_h"] = float(m["g_per_h"])
    return out


def template_of(name, cfg=None):
    """机型模板：常用机型表的默认值 + 设置里的 printer_models[机型]。"""
    if cfg is None:
        from .config import load_config
        cfg = load_config()
    t = builtin_template(name)
    for k, v in ((cfg.get("printer_models") or {}).get(name) or {}).items():
        if k in TPL_FIELDS:
            v = clean_value(k, v)
            if v is not None:
                t[k] = v
    return t


def overrides(p):
    """这台打印机单独设置的值。p["ovr"] 是存下来的覆盖；p 上直接写的模板字段如果和读出来时（p["_eff"]）不一样，
    说明调用的人改过 → 也算覆盖（旧代码 / 测试直接改 p["nozzle"] 也能生效）。返回 (明确的覆盖, 直接写的值)。"""
    o = {}
    for k, v in (p.get("ovr") or {}).items():
        if k in TPL_FIELDS:
            v = clean_value(k, v)
            if v is not None:
                o[k] = v
    eff = p.get("_eff")
    loose = {}
    for f in TPL_FIELDS:
        if f not in p:
            continue
        if eff is not None and f in eff and p[f] == eff[f]:
            continue
        v = clean_value(f, p[f])
        if v is None:
            if eff is not None:
                o.pop(f, None)          # 清空了 → 回到跟随模板
            continue
        loose[f] = v
    return o, loose


def effective(p, cfg=None):
    """唯一的读法：这台打印机实际生效的设置（机型模板 + 单台覆盖）。切片核对、切片配置、多色判断、估算、排单都用它。
    load_config() 读出来的打印机已经是这个结果（带 _eff 标记）；对这样的 p 再调一次直接返回。"""
    p = p or {}
    eff = p.get("_eff")
    if eff is not None and "ovr" in p and all((f in p) == (f in eff) and p.get(f) == eff.get(f) for f in TPL_FIELDS):
        return p
    o, loose = overrides(p)
    t = template_of(p.get("name"), cfg)
    for f, v in loose.items():
        if f in o or t.get(f) != v:
            o[f] = v
    out = dict(p)
    out["ovr"] = o
    e = {}
    for f in TPL_FIELDS:
        v = o[f] if f in o else t.get(f)
        if v is None:
            out.pop(f, None)
        else:
            out[f] = v
            e[f] = v
    out["_eff"] = e
    for k, d in NEW_DEFAULTS.items():
        out.setdefault(k, d)
    return out


def to_stored(p, cfg):
    """存进 config.json 的样子：不存模板算出来的值，只存 ovr（单台覆盖）。"""
    e = effective(p, cfg)
    out = {k: v for k, v in e.items() if k not in TPL_FIELDS and k != "_eff"}
    out["ovr"] = dict(e.get("ovr") or {})
    return out


def new_id():
    return "p" + uuid.uuid4().hex[:10]


def ensure_fields(printers):
    """v2.54：每台打印机要有稳定 id 和新字段的默认值。返回是否改过。"""
    changed = False
    seen = set()
    for p in printers:
        pid = str(p.get("id") or "")
        if not pid or pid in seen:
            p["id"] = new_id()
            changed = True
        seen.add(p["id"])
        for k, d in NEW_DEFAULTS.items():
            if k not in p:
                p[k] = d
                changed = True
        if p.get("role") not in ROLES:
            p["role"] = "any"
            changed = True
    return changed


def looks_like_location(note):
    s = str(note or "").strip()
    if not s or len(s) > 20:
        return False
    return bool(LOC_RE.match(s)) or any(w in s.lower() for w in LOC_WORDS)


def migrate254(cfg):
    """v2.54 一次性迁移：同机型的打印机设置完全一样的值 → 变成机型模板；不一样的留作单台覆盖。
    喷嘴、热床板（PER_PRINTER）永远留在每台自己身上，不放进模板。
    备注像位置（A-03-2、2 号货架）的抄到「位置」。原地修改 cfg。"""
    prs = cfg.get("printers") or []
    tpls = {k: dict(v) for k, v in (cfg.get("printer_models") or {}).items()}
    by_model = {}
    for p in prs:
        by_model.setdefault(p.get("name") or "", []).append(p)
    for name, group in by_model.items():
        if not name:
            continue
        t = dict(tpls.get(name) or {})
        for f in TPL_FIELDS:
            if f in t or f in PER_PRINTER:
                continue
            vals = [clean_value(f, (p.get("ovr") or {}).get(f, p.get(f))) for p in group]
            if vals and all(v is not None for v in vals) and all(v == vals[0] for v in vals):
                t[f] = vals[0]
        if t:
            tpls[name] = t
    cfg["printer_models"] = tpls
    for p in prs:
        if not p.get("location") and looks_like_location(p.get("note")):
            p["location"] = str(p.get("note")).strip()
    ensure_fields(prs)
    cfg["_fleet254"] = True
    return cfg


def index_of(printers, key):
    """按 id / 编码 / 序号找打印机，返回序号或 None（新接口都用 id，旧接口的序号照样能用）。"""
    if key is None:
        return None
    s = str(key).strip()
    for i, p in enumerate(printers):
        if p.get("id") == s:
            return i
    for i, p in enumerate(printers):
        if str(p.get("code") or "").upper() == s.upper():
            return i
    for i, p in enumerate(printers):          # v2.55：改过编码的打印机，以前印的二维码标签（旧编码）还能找到它
        if s.upper() in [str(x).upper() for x in (p.get("old_codes") or [])]:
            return i
    if s.isdigit() and int(s) < len(printers):
        return int(s)
    return None


def next_codes(name, n, printers, width=3):
    """批量添加的自动编码：P1S-001、P1S-002 …（跳过已经用掉的号）。"""
    pre = prefix_for(name)
    used = {str(p.get("code") or "").upper() for p in printers}
    out, k = [], 1
    while len(out) < n:
        c = f"{pre}-{k:0{width}d}"
        if c not in used and f"{pre}-{k:02d}" not in used:
            out.append(c)
            used.add(c)
        k += 1
    return out


# ---------------- 厂家表单（以后加别的厂家只在这里加一项） ----------------
VENDORS = {
    "bambu": {
        "zh": "拓竹 Bambu Lab（局域网）", "th": "Bambu Lab (LAN)", "brands": ["bambu"], "conn": "bambu",
        "fields": [
            {"key": "host", "zh": "IP 地址", "th": "ที่อยู่ IP", "req": True, "kind": "ip", "ph": "192.168.1.50"},
            {"key": "serial", "zh": "序列号", "th": "หมายเลขซีเรียล", "req": True, "kind": "serial", "ph": "01P00A000000000"},
            {"key": "access_code", "zh": "访问码", "th": "รหัสเข้าถึง (Access Code)", "req": True, "kind": "secret", "ph": "12345678"}],
        "hint_zh": "打印机屏幕 设置 → 网络（WLAN）看 IP 和访问码，设置 → 设备信息 看序列号。要打开「局域网模式」；新固件还要打开「开发者模式」才能由本系统发送打印。",
        "hint_th": "ดู IP และรหัสเข้าถึงที่หน้าจอเครื่อง ตั้งค่า → เครือข่าย (WLAN) ดูหมายเลขซีเรียลที่ ตั้งค่า → ข้อมูลอุปกรณ์ ต้องเปิด «โหมด LAN» และเฟิร์มแวร์ใหม่ต้องเปิด «โหมดนักพัฒนา» ด้วย จึงจะส่งงานพิมพ์จากระบบนี้ได้",
        "checks": ["lan", "auth", "status", "devmode"]},
    "creality": {
        "zh": "Creality 原厂固件", "th": "Creality เฟิร์มแวร์เดิม", "brands": ["creality"], "conn": "creality",
        "fields": [{"key": "host", "zh": "IP 地址", "th": "ที่อยู่ IP", "req": True, "kind": "ip", "ph": "192.168.1.60"}],
        "hint_zh": "Creality K1 / K1C / K1 Max / K2：屏幕 设置 → 网络 看 IP。只要填 IP。",
        "hint_th": "Creality K1 / K1C / K1 Max / K2: ดู IP ที่หน้าจอ ตั้งค่า → เครือข่าย กรอกแค่ IP",
        "checks": ["port"]},
    "moonraker": {
        "zh": "Klipper / Moonraker（Fluidd、Mainsail）", "th": "Klipper / Moonraker (Fluidd, Mainsail)", "brands": ["creality", "*"], "conn": "moonraker",
        "fields": [{"key": "host", "zh": "IP 地址", "th": "ที่อยู่ IP", "req": True, "kind": "ip", "ph": "192.168.1.70"},
                   {"key": "port", "zh": "端口（可不填）", "th": "พอร์ต (เว้นว่างได้)", "req": False, "kind": "port", "ph": "7125"}],
        "hint_zh": "root 过的 K1 或其他 Klipper 打印机：端口一般是 7125（Fluidd 4408 / Mainsail 4409），不填会自动试。",
        "hint_th": "K1 ที่ root แล้ว หรือเครื่อง Klipper อื่น: พอร์ตปกติคือ 7125 (Fluidd 4408 / Mainsail 4409) ถ้าไม่กรอกระบบจะลองให้เอง",
        "checks": ["port"]},
    "none": {"zh": "不连接（手动记录）", "th": "ไม่เชื่อมต่อ (บันทึกเอง)", "brands": ["*"], "conn": "none", "fields": [],
             "hint_zh": "不连接也能用：员工在生产看板手动点「开始」「打完」。", "hint_th": "ไม่เชื่อมต่อก็ใช้ได้: พนักงานกด «เริ่ม» «เสร็จ» ที่บอร์ดผลิตเอง",
             "checks": []},
}


def vendor_of_model(name):
    """机型默认用哪个厂家表单。"""
    b = (model_info(name) or {}).get("brand")
    if b == "bambu":
        return "bambu"
    if b == "creality":
        return "creality"
    return "none"


def vendors_for(name):
    b = (model_info(name) or {}).get("brand") or ""
    return [k for k, v in VENDORS.items() if b in v["brands"] or "*" in v["brands"]]


def vendor_of(p):
    """这台打印机现在用的厂家表单（按连接方式；自动识别 → 认出来的那种，没认出来按机型）。"""
    c = p.get("conn") or {}
    t = c.get("type") or "none"
    if t == "auto":
        t = c.get("detected") or vendor_of_model(p.get("name"))
    return t if t in VENDORS else "none"


HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*$")


def valid_host(s):
    s = str(s or "").strip()
    if not s:
        return False
    try:
        ipaddress.IPv4Address(s)
        return True
    except ValueError:
        pass
    if re.fullmatch(r"[\d.]+", s):       # 像 IP 但不对（192.168.1.300）
        return False
    return bool(HOST_RE.match(s)) and len(s) <= 253


def validate_conn(vendor, data, old=None):
    """按厂家检查连接设置。返回 (conn, errors[(zh, th)])。访问码没改（****** / 空）保持原来的。"""
    old = old or {}
    data = data or {}
    v = VENDORS.get(vendor)
    if not v:
        return None, [("不支持的厂家 / 连接方式", "ไม่รองรับยี่ห้อ / การเชื่อมต่อนี้")]
    errs = []
    c = {"type": v["conn"], "host": "", "serial": "", "access_code": "", "port": "",
         "loaded": str(data.get("loaded", old.get("loaded", "")) or "").strip(),
         "auto_complete": data.get("auto_complete", old.get("auto_complete", True)) not in (False, "false", "0", 0),
         "detected": v["conn"] if v["conn"] != "none" else ""}
    for f in v["fields"]:
        k = f["key"]
        val = str(data.get(k) if data.get(k) is not None else "").strip()
        if f["kind"] == "secret":
            if val in ("", "******"):
                val = old.get(k, "") or ""
            if f["req"] and not val:
                errs.append((f"请填写{f['zh']}", f"กรุณากรอก{f['th']}"))
            elif val and not re.fullmatch(r"[A-Za-z0-9]{4,16}", val):
                errs.append((f"{f['zh']}只能是 4–16 位英文或数字", f"{f['th']} ต้องเป็นตัวอักษรหรือตัวเลข 4–16 ตัว"))
        elif f["kind"] == "ip":
            if not val:
                errs.append((f"请填写{f['zh']}", f"กรุณากรอก{f['th']}"))
            elif not valid_host(val):
                errs.append((f"IP 地址「{val}」不对（例如 192.168.1.50）", f"ที่อยู่ IP «{val}» ไม่ถูกต้อง (เช่น 192.168.1.50)"))
        elif f["kind"] == "serial":
            val = val.upper()
            if f["req"] and not val:
                errs.append((f"请填写{f['zh']}", f"กรุณากรอก{f['th']}"))
            elif val and not re.fullmatch(r"[A-Z0-9]{8,20}", val):
                errs.append((f"序列号「{val}」不对：8–20 位英文或数字", f"หมายเลขซีเรียล «{val}» ไม่ถูกต้อง: ตัวอักษรหรือตัวเลข 8–20 ตัว"))
        elif f["kind"] == "port":
            if val and not (val.isdigit() and 1 <= int(val) <= 65535):
                errs.append((f"端口「{val}」不对（1–65535）", f"พอร์ต «{val}» ไม่ถูกต้อง (1–65535)"))
        c[k] = val
    if v["conn"] == "none":
        c = {"type": "none", "loaded": c["loaded"], "auto_complete": c["auto_complete"]}
    return c, errs


# ---------------- 批量导入（Excel / CSV） ----------------
IMPORT_COLS = {
    "code": ("code", "编码", "机器编码", "รหัส", "รหัสเครื่อง"),
    "model": ("model", "name", "机型", "型号", "รุ่น"),
    "host": ("ip", "host", "ip 地址", "ip地址", "ที่อยู่ ip"),
    "serial": ("serial", "序列号", "sn", "ซีเรียล", "หมายเลขซีเรียล"),
    "access_code": ("access code", "access_code", "访问码", "รหัสเข้าถึง"),
    "group": ("group", "分组", "กลุ่ม"),
    "location": ("location", "位置", "ตำแหน่ง"),
    "vendor": ("vendor", "连接方式", "การเชื่อมต่อ"),
    "role": ("role", "用途", "การใช้งาน"),
    "nozzle": ("nozzle", "喷嘴", "喷嘴直径", "หัวฉีด", "ขนาดหัวฉีด"),
}
DEFAULT_NOZZLE = 0.4


def _col_key(h):
    h = str(h or "").strip().lower()
    for k, names in IMPORT_COLS.items():
        if h in names:
            return k
    return None


def read_table(filename, data):
    """读 Excel / CSV，返回 [行 dict]（表头按 IMPORT_COLS 认，中 / 英 / 泰都行）。"""
    import csv
    import io
    if str(filename or "").lower().endswith((".xlsx", ".xlsm")):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        raw = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    else:
        text = data.decode("utf-8-sig", "replace") if isinstance(data, bytes) else str(data)
        sample = text[:2000]
        delim = "\t" if sample.count("\t") > sample.count(",") else ","
        raw = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not raw:
        return []
    keys = [_col_key(h) for h in raw[0]]
    if "model" not in keys:
        raise ValueError("表头要有「机型」（model）这一列")
    rows = []
    for r in raw[1:5001]:
        d = {}
        for k, v in zip(keys, r):
            if k:
                d[k] = "" if v is None else str(v).strip()
        if any(d.values()):
            rows.append(d)
    return rows


def known_model(name, cfg):
    """导入 / 添加时机型要认得：常用机型表、已有的机型模板、已有打印机的机型。"""
    s = str(name or "").strip()
    if not s:
        return None
    names = set((cfg.get("printer_models") or {}).keys()) | {p.get("name") for p in cfg.get("printers") or []}
    for n in names:
        if n and n.lower() == s.lower():
            return n
    m = model_info(s)
    return m["name"] if m else None


def validate_import(rows, cfg):
    """检查导入的行。返回 [{row, ok, errors[(zh,th)], warnings[(zh,th)], printer}]（printer = 要加进去的打印机）。"""
    prs = list(cfg.get("printers") or [])
    used_codes = {str(p.get("code") or "").upper() for p in prs}
    used_hosts = {(p.get("conn") or {}).get("host") for p in prs if (p.get("conn") or {}).get("host")}
    used_serials = {str((p.get("conn") or {}).get("serial") or "").upper() for p in prs if (p.get("conn") or {}).get("serial")}
    out = []
    taken = []
    for n, r in enumerate(rows, 1):
        errs, warns = [], []
        model = known_model(r.get("model"), cfg)
        if not model:
            errs.append((f"认不出机型「{r.get('model') or ''}」", f"ไม่รู้จักรุ่น «{r.get('model') or ''}»"))
            model = str(r.get("model") or "")
        code = str(r.get("code") or "").strip().upper()
        if code:
            if not CODE_RE.match(code):
                errs.append((f"编码「{code}」只能用英文、数字和 - _，最多 16 位", f"รหัส «{code}» ใช้ได้เฉพาะอังกฤษ ตัวเลข - _ ไม่เกิน 16 ตัว"))
            elif code in used_codes:
                errs.append((f"编码「{code}」已经有了", f"รหัส «{code}» มีอยู่แล้ว"))
        vendor = str(r.get("vendor") or "").strip().lower()
        vendor = {"klipper": "moonraker", "fluidd": "moonraker", "mainsail": "moonraker"}.get(vendor, vendor)
        if not vendor:
            vendor = vendor_of_model(model) if r.get("host") else "none"
        if vendor not in VENDORS:
            errs.append((f"连接方式「{vendor}」不认得（bambu / creality / moonraker / none）",
                         f"ไม่รู้จักการเชื่อมต่อ «{vendor}» (bambu / creality / moonraker / none)"))
            vendor = "none"
        conn, cerrs = validate_conn(vendor, r)
        errs += cerrs
        host = (conn or {}).get("host")
        if host and host in used_hosts:
            errs.append((f"IP {host} 已经有别的打印机在用", f"IP {host} มีเครื่องอื่นใช้อยู่แล้ว"))
        ser = str((conn or {}).get("serial") or "").upper()
        if ser and ser in used_serials:
            errs.append((f"序列号 {ser} 重复了", f"หมายเลขซีเรียล {ser} ซ้ำ"))
        role = str(r.get("role") or "any").strip().lower() or "any"
        if role not in ROLES:
            warns.append((f"用途「{role}」不认得，按「都可以」", f"ไม่รู้จักการใช้งาน «{role}» ใช้ «ทั้งหมด»"))
            role = "any"
        if not errs:
            if not code:
                from . import fleetcodes      # v2.55：按编码规则（分组有自己的规则就用它）
                spec = {"name": model, "group": str(r.get("group") or "")[:30], "location": str(r.get("location") or "")[:30]}
                code, prob = fleetcodes.generate(prs + taken, [spec], cfg)[0]
                if prob:
                    errs.append(fleetcodes.PROBLEM[prob])
            taken.append({"code": code, "name": model, "group": str(r.get("group") or "")[:30], "location": str(r.get("location") or "")[:30]})
            used_codes.add(code)
            if host:
                used_hosts.add(host)
            if ser:
                used_serials.add(ser)
        m = model_info(model) or {}
        ovr = {}
        if m.get("tech", "fdm") != "resin":      # v2.54 复审：喷嘴是每台自己的，不从模板继承；没填按 0.4 并提醒确认
            raw_n = str(r.get("nozzle") or "").strip()
            nz = clean_value("nozzle", raw_n) if raw_n else None
            if raw_n and nz is None:
                errs.append((f"喷嘴直径「{raw_n}」不对（例如 0.4）", f"ขนาดหัวฉีด «{raw_n}» ไม่ถูกต้อง (เช่น 0.4)"))
            elif nz is None:
                nz = DEFAULT_NOZZLE
                warns.append(("没填喷嘴直径，按 0.4 mm：不是 0.4 的请改", "ไม่ได้กรอกขนาดหัวฉีด ใช้ 0.4 มม. ถ้าไม่ใช่ 0.4 กรุณาแก้"))
            if nz is not None:
                ovr["nozzle"] = nz
        out.append({"row": n, "ok": not errs, "errors": errs, "warnings": warns,
                    "printer": {"code": code, "name": model, "enabled": True, "tech": m.get("tech", "fdm"),
                                "group": str(r.get("group") or "")[:30], "location": str(r.get("location") or "")[:30],
                                "role": role, "dedicated_po": "", "paused": False, "conn": conn or {"type": "none"}, "ovr": ovr}})
    return out
