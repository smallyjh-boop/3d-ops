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


def job_tech(material):
    return "resin" if is_resin(material) else "fdm"
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,15}$")
PRINTER_TABLES = ("jobs", "print_runs", "failures", "maintenance")


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


def remap(old, new):
    """打印机列表改了（排序 / 删除 / 新增）：把任务、打印记录里的序号按编码对到新位置。
    被删掉的打印机：没开始的任务清空打印机（重新排单）；正在打印的不允许删（调用前检查）。"""
    old_codes = [p.get("code") for p in old]
    new_idx = {p.get("code"): i for i, p in enumerate(new)}
    mapping = {}
    for i, c in enumerate(old_codes):
        j = new_idx.get(c)
        if j != i:
            mapping[i] = j
    c = db.conn()
    gone = [code for code in old_codes if code and code not in new_idx]
    # v2.41 复审：同一个位置的编码换成了一个新编码 = 改名，不是删掉 → 料卷跟着换到新编码上，不卸下来
    has_spools = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='spools'").fetchone()
    for i, code in enumerate(old_codes):
        if code in gone and i < len(new) and new[i].get("code") and new[i].get("code") not in old_codes:
            if has_spools:
                c.execute("UPDATE spools SET printer=?, updated_at=? WHERE status='loaded' AND printer=?", (new[i]["code"], time.time(), code))
            gone.remove(code)
    if gone and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='spools'").fetchone():
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
                if t == "jobs":
                    c.execute("UPDATE jobs SET printer=NULL, pin=0 WHERE printer=?", (-1000 - i,))
                else:
                    c.execute(f"UPDATE {t} SET printer=NULL WHERE printer=?", (-1000 - i,))
            else:
                c.execute(f"UPDATE {t} SET printer=? WHERE printer=?", (j, -1000 - i))
    c.commit()
    from . import printers as pr
    pr.reset_status()
    return mapping


def busy_codes(old, new):
    """要删掉的打印机里，还有正在打印的 → 不能删。"""
    keep = {p.get("code") for p in new}
    out = []
    c = db.conn()
    for i, p in enumerate(old):
        if p.get("code") not in keep:
            n = c.execute("SELECT COUNT(*) FROM print_runs WHERE status='printing' AND printer=?", (i,)).fetchone()[0]
            if n:
                out.append(p.get("code"))
    return out
