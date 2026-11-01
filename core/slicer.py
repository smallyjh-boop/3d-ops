"""克数和打印时长。

三种来源（可信度从低到高）：
1. 估算：根据模型体积、表面积（浏览器里算好传过来）估算。用过真实切片后会自动校准。
2. 导入切片结果：上传 Bambu Studio / OrcaSlicer / Creality Print 导出的 .gcode 或 .gcode.3mf，读取克数和时长。
3. 自动切片：调用 OrcaSlicer 命令行切片（需要在设置页配置打印机的配置文件）。
"""
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

FILAMENT_DENSITY = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.21, "PA": 1.14, "PC": 1.20}

DEFAULT_PRINTERS = [
    {"name": "Bambu Lab P1S", "g_per_h": 22, "orca_machine": "", "orca_process": "", "orca_filament": ""},
    {"name": "Creality K1 Max", "g_per_h": 20, "orca_machine": "", "orca_process": "", "orca_filament": ""},
    {"name": "Creality K1C", "g_per_h": 18, "orca_machine": "", "orca_process": "", "orca_filament": ""},
]


class SliceError(Exception):
    pass


# ---------------- 1. 估算 ----------------
def density_of(material):
    m = (material or "PLA").upper()
    for k, v in FILAMENT_DENSITY.items():
        if k in m:
            return v
    return 1.24


def estimate(cfg, metrics, material="PLA"):
    """metrics: volume_mm3, area_mm2, size[x,y,z]。返回每台打印机的估算克数和小时。"""
    vol = max(0.0, float(metrics.get("volume_mm3") or 0))
    area = max(0.0, float(metrics.get("area_mm2") or 0))
    shell_mm = float(cfg.get("est_shell_mm", 1.0))      # 外壁+顶底等效厚度
    infill = float(cfg.get("est_infill", 0.15))
    support = float(cfg.get("est_support_factor", 1.08))
    calib = float(cfg.get("est_calibration", 1.0))      # 用真实切片结果自动校准
    by_mat = cfg.get("est_calibration_by_mat") or {}    # v2.15：按材料分别校准（质量统计 → 估算校准）
    if by_mat:
        from .calib import mat_key
        calib = float(by_mat.get(mat_key(material), calib))
    shell_vol = min(vol, area * shell_mm)
    inner = max(0.0, vol - shell_vol)
    grams = (shell_vol + inner * infill) / 1000 * density_of(material) * support * calib
    from . import fleet
    resin = fleet.is_resin(material)
    if resin:   # 树脂件一般是实心（不抽空），加一点支撑损耗
        grams = vol / 1000 * float(cfg.get("resin_density") or 1.1) * 1.15
    grams = round(max(grams, 0.5), 1)
    size = metrics.get("size") or [0, 0, 0]
    out = []
    for i, p in enumerate(cfg.get("printers") or DEFAULT_PRINTERS):
        if fleet.tech_of(p) == "resin":
            # 光固化：按高度算（层高 0.05mm，每层约 4 秒），一盘的时间
            z = float(size[2] if len(size) > 2 else 30) + 5
            hours = round(z / 0.05 * 4 / 3600 + 0.25, 2)
        else:
            gph = float(p.get("g_per_h") or 20)
            hours = round(grams / gph + float(cfg.get("est_overhead_h", 0.15)), 2)
        out.append({"printer": i, "name": p.get("name", f"#{i + 1}"), "grams": grams, "hours": hours})
    return {"grams": grams, "per_printer": out,
            "volume_cm3": round(vol / 1000, 2), "size_mm": metrics.get("size")}


def calibrate(cfg, estimated_grams, real_grams):
    """有了真实切片克数后，更新估算校准系数（滑动平均，防止一次异常数据带偏）。"""
    if not estimated_grams or not real_grams:
        return cfg.get("est_calibration", 1.0)
    old = float(cfg.get("est_calibration", 1.0))
    base = estimated_grams / old if old else estimated_grams
    ratio = real_grams / base if base else 1.0
    ratio = min(3.0, max(0.33, ratio))
    n = int(cfg.get("est_calibration_n", 0))
    new = (old * n + ratio) / (n + 1) if n else ratio
    cfg["est_calibration"] = round(new, 4)
    cfg["est_calibration_n"] = min(n + 1, 20)
    return cfg["est_calibration"]


# ---------------- 2. 读取切片结果 ----------------
def _hms_to_hours(text):
    text = text.strip()
    d = re.search(r"(\d+)\s*d", text)
    h = re.search(r"(\d+)\s*h", text)
    m = re.search(r"(\d+)\s*m(?!m)", text)
    s = re.search(r"(\d+)\s*s", text)
    if not any((d, h, m, s)):
        return None
    secs = (int(d.group(1)) * 86400 if d else 0) + (int(h.group(1)) * 3600 if h else 0) \
        + (int(m.group(1)) * 60 if m else 0) + (int(s.group(1)) if s else 0)
    return secs / 3600


def parse_gcode_text(text, material="PLA"):
    """支持 Bambu Studio / OrcaSlicer / PrusaSlicer / Creality Print / Cura 风格的 G-code 注释。"""
    grams = hours = None
    # 克数
    for pat in (r";\s*total filament weight \[g\]\s*[:=]\s*([\d.]+)",
                r";\s*filament used \[g\]\s*[:=]\s*([\d.,\s]+)",
                r";\s*total filament used \[g\]\s*[:=]\s*([\d.]+)",
                r";\s*filament_weight\s*[:=]\s*([\d.]+)"):
        m = re.search(pat, text, re.I)
        if m:
            nums = [float(x) for x in re.findall(r"[\d.]+", m.group(1)) if x not in (".",)]
            if nums:
                grams = sum(nums)
                break
    if grams is None:
        # 只有长度：filament used [mm] 或 Cura 的 ;Filament used: 1.23m
        m = re.search(r";\s*filament used \[mm\]\s*[:=]\s*([\d.,\s]+)", text, re.I)
        mm = sum(float(x) for x in re.findall(r"[\d.]+", m.group(1))) if m else None
        if mm is None:
            m = re.search(r";\s*Filament used:\s*([\d.]+)\s*m", text, re.I)
            mm = float(m.group(1)) * 1000 if m else None
        if mm:
            area = 3.14159265 * (1.75 / 2) ** 2
            grams = mm * area / 1000 * density_of(material)
    # 时长
    for pat in (r"total estimated time\s*[:=]\s*([^;\n]+)",
                r";\s*estimated printing time(?: \(normal mode\))?\s*[:=]\s*([^\n]+)",
                r";\s*model printing time\s*[:=]\s*([^;\n]+)",
                r";\s*print_time\s*[:=]\s*([^\n]+)"):
        m = re.search(pat, text, re.I)
        if m:
            hours = _hms_to_hours(m.group(1))
            if hours:
                break
    if hours is None:
        m = re.search(r";\s*TIME\s*:\s*(\d+)", text)
        if m:
            hours = int(m.group(1)) / 3600
    if grams is None and hours is None:
        return None
    out = {"grams": round(grams, 1) if grams else None, "hours": round(hours, 2) if hours else None}
    mc = gcode_filaments(text, material)          # v2.52：多色 —— 每个耗材的克数、冲刷废料、换色次数
    if len(mc.get("filaments") or []) > 1:
        out.update(mc)
    return out


def slice_info_filaments(xml):
    """拓竹 / Orca 切片文件 Metadata/slice_info.config 里每个耗材的用量：
    <filament id="1" type="PLA" color="#FFFFFF" used_m="1.23" used_g="3.45" />。返回 [{slot, type, hex, grams, meters}]（按槽号）。"""
    out = {}
    for m in re.finditer(r"<filament\b([^>]*)/?>", xml or ""):
        a = dict(re.findall(r'([\w:]+)="([^"]*)"', m.group(1)))
        try:
            slot = int(a.get("id") or 0)
        except ValueError:
            continue
        if slot <= 0:
            continue
        try:
            g, mm = float(a.get("used_g") or 0), float(a.get("used_m") or 0)
        except ValueError:
            continue
        cur = out.setdefault(slot, {"slot": slot, "type": a.get("type") or "", "hex": (a.get("color") or "")[:7], "grams": 0.0, "meters": 0.0})
        cur["grams"] = round(cur["grams"] + g, 2)       # 几个盘的同一个耗材加在一起
        cur["meters"] = round(cur["meters"] + mm, 3)
    return [out[k] for k in sorted(out)]


def gcode_filaments(text, material="PLA"):
    """G-code 头 / 尾注释里的多耗材信息（OrcaSlicer / Bambu Studio / PrusaSlicer）：
    ; filament used [g] = 3.45, 1.20      每个耗材的克数
    ; total filament used for wipe tower [g] = 1.1    擦料塔（冲刷）用料
    ; flush ... / ; total filament change = 12        换色次数（有的版本写在 ; filament change times / total toolchanges）
    返回 {filaments: [{slot, grams}], purge_g, changes}（没有的项不返回）。"""
    out = {}
    m = re.search(r";\s*filament used \[g\]\s*[:=]\s*([\d.,\s]+)", text or "", re.I)
    if m:
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", m.group(1))]
        if nums:
            out["filaments"] = [{"slot": i + 1, "grams": round(g, 2)} for i, g in enumerate(nums)]
    for pat in (r";\s*total filament used for wipe tower \[g\]\s*[:=]\s*([\d.]+)",
                r";\s*(?:total )?flush(?:ed)? (?:volume|filament)[^=:\n]*\[g\]\s*[:=]\s*([\d.]+)"):
        m = re.search(pat, text or "", re.I)
        if m:
            out["purge_g"] = round(float(m.group(1)), 2)
            break
    for pat in (r";\s*total filament change\s*[:=]\s*(\d+)", r";\s*filament change times\s*[:=]\s*(\d+)",
                r";\s*total toolchanges\s*[:=]\s*(\d+)"):
        m = re.search(pat, text or "", re.I)
        if m:
            out["changes"] = int(m.group(1))
            break
    return out


def gcode_purge_scan(data):
    """v2.52：G-code 头里没写换色次数 / 冲刷量时（OrcaSlicer 2.3 就不写），扫一遍整个 G-code 自己算：
    换色次数 = 「; toolchange #N」的最大 N（没有时数 T0/T1… 切换）；
    冲刷废料 = 换色段（; CP TOOLCHANGE START … END）和擦料塔（; FEATURE: Prime tower）里挤出的料，按耗材直径 / 密度换成克。
    data 可以是 bytes 或 str。返回 {changes, purge_g, purge_by_slot: {槽: 克}}（算不出来返回 {}）。"""
    if isinstance(data, bytes):
        data = data.decode("utf-8", "ignore")
    if not data:
        return {}
    diam, dens = 1.75, 1.24
    m = re.search(r";\s*filament_diameter\s*[:=]\s*([\d.]+)", data)
    if m:
        diam = float(m.group(1)) or diam
    m = re.search(r";\s*filament_density\s*[:=]\s*([\d.]+)", data)
    if m:
        dens = float(m.group(1)) or dens
    changes = 0
    last_t, t_changes = None, 0
    rel, in_change, feature = True, False, ""
    e_mm, by_t = 0.0, {}
    e_re = re.compile(r"\bE(-?[\d.]+)")
    for line in data.splitlines():
        if not line:
            continue
        c = line[0]
        if c == ";":
            if line.startswith("; FEATURE:"):
                feature = line[10:].strip().lower()
            elif line.startswith("; CP TOOLCHANGE START"):
                in_change = True
            elif line.startswith("; CP TOOLCHANGE END"):
                in_change = False
            elif line.startswith("; toolchange #"):
                try:
                    changes = max(changes, int(line[14:].split()[0]))
                except ValueError:
                    pass
            continue
        if c == "T" and line[1:2].isdigit():
            try:
                t = int(line[1:].split()[0])
            except ValueError:
                continue
            if t < 64:
                if last_t is not None and t != last_t:
                    t_changes += 1
                last_t = t
            continue
        if line.startswith("M83"):
            rel = True
        elif line.startswith("M82"):
            rel = False
        elif rel and (in_change or feature == "prime tower") and line.startswith(("G1 ", "G0 ", "G2 ", "G3 ")):
            m = e_re.search(line.split(";", 1)[0])
            if m:
                v = float(m.group(1))
                if v > 0:
                    e_mm += v
                    by_t[last_t or 0] = by_t.get(last_t or 0, 0.0) + v
    changes = changes or t_changes
    if not changes:
        return {}
    k = 3.141592653589793 * (diam / 2) ** 2 / 1000.0 * dens
    return {"changes": changes, "purge_g": round(e_mm * k, 2),
            "purge_by_slot": {t + 1: round(v * k, 2) for t, v in sorted(by_t.items())}}


def _scan_text(data):
    """G-code 的统计信息一般在开头或结尾，只读头尾即可（文件可能很大）。"""
    head = data[:400_000]
    tail = data[-400_000:] if len(data) > 400_000 else b""
    return (head + b"\n" + tail).decode("utf-8", "ignore")


def parse_sliced_file(path, material="PLA"):
    """读取 .gcode / .gcode.3mf / 已切片的 .3mf，返回 {grams, hours, source}。"""
    name = os.path.basename(path).lower()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            # Bambu Studio / OrcaSlicer：Metadata/slice_info.config 里有每个盘的 prediction（秒）和 weight（克）
            if "Metadata/slice_info.config" in names:
                xml = z.read("Metadata/slice_info.config").decode("utf-8", "ignore")
                weights = [float(x) for x in re.findall(r'key="weight"\s+value="([\d.]+)"', xml)]
                preds = [float(x) for x in re.findall(r'key="prediction"\s+value="([\d.]+)"', xml)]
                if weights or preds:
                    out = {"grams": round(sum(weights), 1) if weights else None,
                           "hours": round(sum(preds) / 3600, 2) if preds else None,
                           "source": "slice_info", "plates": max(len(weights), len(preds))}
                    fil = slice_info_filaments(xml)          # v2.52：多色 —— 每种耗材用了多少
                    if fil:
                        out["filaments"] = fil
                        if not weights:
                            out["grams"] = round(sum(f["grams"] for f in fil), 1)
                    gc = [n for n in names if n.lower().endswith(".gcode")]
                    if gc:
                        raw = z.read(gc[0])
                        mc = gcode_filaments(_scan_text(raw))
                        if len(fil or []) > 1 and (mc.get("purge_g") is None or mc.get("changes") is None):
                            for k, v in gcode_purge_scan(raw).items():
                                mc.setdefault(k, v)
                        for k in ("purge_g", "changes", "purge_by_slot"):
                            if mc.get(k) is not None:
                                out[k] = mc[k]
                    return out
            gcodes = [n for n in names if n.lower().endswith(".gcode")]
            total_g = total_h = 0.0
            found = False
            for n in gcodes:
                r = parse_gcode_text(_scan_text(z.read(n)), material)
                if r:
                    found = True
                    total_g += r["grams"] or 0
                    total_h += r["hours"] or 0
            if found:
                return {"grams": round(total_g, 1), "hours": round(total_h, 2), "source": "gcode_in_3mf",
                        "plates": len(gcodes)}
        raise SliceError("这个 3MF 文件还没有切片数据。请在切片软件里切片后用「导出切片文件 (.gcode.3mf)」再上传")
    if name.endswith((".gcode", ".gco", ".g")):
        with open(path, "rb") as f:
            data = f.read()
        r = parse_gcode_text(_scan_text(data), material)
        if r:
            r["source"] = "gcode"
            return r
        raise SliceError("G-code 里没有找到克数/时长信息")
    raise SliceError("请上传 .gcode 或 .gcode.3mf 文件")


# ---------------- 3. OrcaSlicer 自动切片 ----------------
ORCA_EXE_NAMES = ("orca-slicer.exe", "OrcaSlicer.exe", "orca_slicer.exe")
_orca_cache = {"path": None}


def _is_orca_exe(path):
    names = {n.lower() for n in ORCA_EXE_NAMES} | {"orca-slicer", "orcaslicer"}   # Linux/NAS 上没有 .exe
    return bool(path) and os.path.isfile(path) and os.path.basename(path).lower() in names


def _exe_in_dir(d, depth=2):
    """在文件夹里（最多往下 depth 层）找 OrcaSlicer 主程序。"""
    if not d or not os.path.isdir(d):
        return None
    for n in ORCA_EXE_NAMES:
        c = os.path.join(d, n)
        if os.path.isfile(c):
            return c
    if depth <= 0:
        return None
    try:
        subs = [os.path.join(d, x) for x in os.listdir(d)]
    except OSError:
        return None
    for sd in subs:
        if os.path.isdir(sd):
            r = _exe_in_dir(sd, depth - 1)
            if r:
                return r
    return None


def _resolve_lnk(lnk):
    """读取 Windows 快捷方式 (.lnk) 指向的程序。"""
    try:
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               f"(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk.replace(chr(39), chr(39) * 2)}').TargetPath"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (r.stdout or "").strip() or None
    except Exception:
        return None


def _from_user_path(p):
    """设置页填写的路径：可以是 exe、安装文件夹，或桌面快捷方式。"""
    p = (p or "").strip().strip('"').strip("'")
    if not p:
        return None
    p = os.path.expandvars(os.path.expanduser(p))
    if p.lower().endswith(".lnk") and os.path.isfile(p):
        t = _resolve_lnk(p)
        return t if t and os.path.isfile(t) else None
    if os.path.isfile(p):
        return p
    return _exe_in_dir(p, 2)


def _from_registry():
    try:
        import winreg
    except ImportError:
        return []
    out = []
    # App Paths
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for n in ORCA_EXE_NAMES:
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + n) as k:
                    out.append(winreg.QueryValueEx(k, "")[0])
            except OSError:
                pass
    # 卸载信息（安装程序都会写这里）
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, root in roots:
        try:
            with winreg.OpenKey(hive, root) as rk:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(rk, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        with winreg.OpenKey(rk, sub) as k:
                            def val(name):
                                try:
                                    return str(winreg.QueryValueEx(k, name)[0])
                                except OSError:
                                    return ""
                            if "orca" not in (val("DisplayName") + sub).lower():
                                continue
                            icon = val("DisplayIcon").split(",")[0].strip().strip('"')
                            if icon:
                                out.append(icon)
                                out.append(os.path.dirname(icon))
                            for name in ("InstallLocation", "UninstallString"):
                                v = val(name).strip()
                                if v.startswith('"'):
                                    v = v[1:].split('"')[0]
                                if v:
                                    out.append(v if os.path.isdir(v) else os.path.dirname(v))
                    except OSError:
                        continue
        except OSError:
            continue
    return out


def _shortcut_dirs():
    env = os.environ.get
    home = os.path.expanduser("~")
    dirs = []
    for base in (env("APPDATA"), env("PROGRAMDATA")):
        if base:
            dirs.append(os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs"))
    for d in (os.path.join(home, "Desktop"), os.path.join(home, "OneDrive", "Desktop"),
              os.path.join(env("PUBLIC") or r"C:\Users\Public", "Desktop")):
        dirs.append(d)
    od = env("OneDrive")
    if od:
        dirs.append(os.path.join(od, "Desktop"))
    return dirs


def _from_shortcuts():
    out = []
    for d in _shortcut_dirs():
        for lnk in glob.glob(os.path.join(d, "**", "*rca*.lnk"), recursive=True):
            t = _resolve_lnk(lnk)
            if t:
                out.append(t)
    return out


def _from_common_dirs():
    out = []
    env = os.environ.get
    bases = [env("ProgramFiles"), env("ProgramFiles(x86)"), env("ProgramW6432"),
             os.path.join(env("LOCALAPPDATA") or "", "Programs"), env("LOCALAPPDATA"),
             os.path.join(os.path.expanduser("~"), "Downloads"), os.path.join(os.path.expanduser("~"), "Desktop"),
             os.path.join(os.path.expanduser("~"), "Documents"), os.path.expanduser("~")]
    if os.name == "nt":
        import string
        for L in string.ascii_uppercase:
            root = f"{L}:\\"
            if os.path.exists(root):
                bases += [root, os.path.join(root, "Program Files"), os.path.join(root, "Program Files (x86)"),
                          os.path.join(root, "Programs"), os.path.join(root, "Software"), os.path.join(root, "软件")]
    for b in bases:
        if not b or not os.path.isdir(b):
            continue
        for d in glob.glob(os.path.join(b, "*rca*")) + glob.glob(os.path.join(b, "*RCA*")):
            out.append(d)
        for d in glob.glob(os.path.join(b, "SoftFever*")):
            out.append(d)
    out += ["/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer", "/usr/bin/orca-slicer"]
    return out


def find_orca(cfg, explain=False):
    """依次查找：设置页填写的路径 → 注册表（安装信息）→ 开始菜单/桌面快捷方式 → 各硬盘常见目录 → PATH。
    找到后会记住，下次直接用。explain=True 时同时返回查找过程（找不到时给用户看）。"""
    tried = []

    def ok(c):
        if not c:
            return None
        if os.path.isdir(c):
            c = _exe_in_dir(c, 2)
        if c and (_is_orca_exe(c) or (os.path.isfile(c) and "orca" in os.path.basename(c).lower()
                                      and c.lower().endswith(".exe") and "unins" not in c.lower())):
            return c
        return None

    found = None
    user = (cfg.get("orca_path") or "").strip()
    if user:
        found = _from_user_path(user)
        tried.append(f"设置页路径：{user} → {'OK' if found else '无效'}")
    if not found and _orca_cache["path"] and os.path.isfile(_orca_cache["path"]):
        found = _orca_cache["path"]
    steps = [("注册表", _from_registry), ("快捷方式", _from_shortcuts), ("常见目录", _from_common_dirs),
             ("PATH", lambda: [shutil.which(n) for n in ("orca-slicer", "OrcaSlicer", "orca-slicer.exe")])]
    for label, fn in steps:
        if found:
            break
        try:
            cands = [c for c in fn() if c]
        except Exception as e:
            tried.append(f"{label}：出错 {e}")
            continue
        for c in cands:
            r = ok(c)
            if r:
                found = r
                break
        tried.append(f"{label}：检查了 {len(cands)} 处 → {'找到' if found else '没有'}")
    if found:
        _orca_cache["path"] = found
    return (found, tried) if explain else found


def pick_exe_dialog():
    """在电脑上弹出 Windows 选择文件窗口，让用户手动选 orca-slicer.exe。"""
    import sys
    code = ("import tkinter as tk;from tkinter import filedialog as f;r=tk.Tk();r.withdraw();"
            "r.attributes('-topmost',True);"
            "p=f.askopenfilename(title='OrcaSlicer: orca-slicer.exe',filetypes=[('OrcaSlicer','*.exe *.lnk'),('All','*.*')]);"
            "print(p or '')")
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    except Exception as e:
        raise SliceError(f"无法打开选择窗口：{e}")
    p = (r.stdout or "").strip()
    if not p:
        return ""
    p = os.path.normpath(p)
    if p.lower().endswith(".lnk"):
        p = _resolve_lnk(p) or p
    return p


def find_profiles():
    """在 OrcaSlicer / Bambu Studio 的用户目录里找你自己保存过的打印机/工艺/耗材配置。"""
    roots = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots += [os.path.join(appdata, "OrcaSlicer", "user"), os.path.join(appdata, "BambuStudio", "user")]
    home = os.path.expanduser("~")
    roots += [os.path.join(home, "Library", "Application Support", "OrcaSlicer", "user"),
              os.path.join(home, ".config", "OrcaSlicer", "user")]
    out = {"machine": [], "process": [], "filament": []}
    for r in roots:
        for kind in out:
            out[kind] += sorted(glob.glob(os.path.join(r, "*", kind, "*.json")))
    return out


def _cube_stl(path, size=20.0):
    s = size
    v = [(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0), (0, 0, s), (s, 0, s), (s, s, s), (0, s, s)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    with open(path, "w", encoding="ascii") as f:
        f.write("solid cube\n")
        for a, b, c in faces:
            f.write(" facet normal 0 0 0\n  outer loop\n")
            for i in (a, b, c):
                f.write(f"   vertex {v[i][0]} {v[i][1]} {v[i][2]}\n")
            f.write("  endloop\n endfacet\n")
        f.write("endsolid cube\n")


def gcode_to_3mf(gcode_path, out_path):
    """把 G-code 包成最简单的 .gcode.3mf（Metadata/plate_1.gcode + md5），拓竹打印机可以直接打印。"""
    import hashlib
    with open(gcode_path, "rb") as f:
        data = f.read()
    md5 = hashlib.md5(data).hexdigest().upper()
    ct = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
          '<Default Extension="gcode" ContentType="text/x.gcode"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/Metadata/plate_1.gcode" Id="rel-1" '
            'Type="http://schemas.bambulab.com/package/2021/gcode"/></Relationships>')
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("Metadata/plate_1.gcode", data)
        z.writestr("Metadata/plate_1.gcode.md5", md5)
    return out_path


def _usable(idx, val):
    """设置里存的配置在这台机器上能不能用：
    - 是文件路径且存在 → 用它
    - 路径不存在（例如从 Windows 搬到 NAS，路径是 C:\\Users\\...）→ 按文件名找同名配置
    - 是配置名 → 能找到就用
    都不行返回空，调用方改用自动匹配。"""
    from . import orca_profiles as op
    v = (val or "").strip().strip('"')
    if not v:
        return ""
    if os.path.isfile(v):
        return v
    if op._lookup(idx, v):
        return v
    base = re.split(r"[\\/]", v)[-1]
    if base.lower().endswith(".json"):
        base = base[:-5]
    if base and op._lookup(idx, base):
        return base
    return ""


def filament_mismatch(idx, filament_name, material):
    """v2.55：指定的耗材配置和要打的材料不一样（例如 PLA 的配置拿去打 PETG / TPU）→ 返回配置里的材料，一样 / 读不到返回空。
    同一大类（PLA / PLA-CF）算一样。"""
    from . import orca_profiles as op
    from .recipes import same_material
    if not filament_name or not material:
        return ""
    ft = op.filament_type(idx, filament_name)
    if ft and same_material(ft, material) == "diff":
        return ft
    return ""


def no_profile_msg(material, got="", got_type=""):
    """找不到这个材料的耗材配置（自动选到的是别的材料，例如 PC / 丝绸料选到了打印机默认的 PLA）。中文 + 泰文。"""
    extra = f"（自动选到的「{got}」是 {got_type}，不能用）" if got else ""
    extra_th = f" (โปรไฟล์ที่เลือกอัตโนมัติ「{got}」เป็น {got_type} ใช้ไม่ได้)" if got else ""
    return (f"找不到 {material} 的耗材配置，请在打印机设置里选{extra}"
            f" / ไม่พบโปรไฟล์ฟิลาเมนต์สำหรับ {material} กรุณาเลือกในการตั้งค่าเครื่องพิมพ์{extra_th}")


def resolve_profiles(cfg, printer_index=0, material="PLA", filament_name=None, notes=None, strict=True):
    """这台打印机切片用哪套配置：返回 (orca 程序, 配置索引, 打印机配置, 工艺配置, 耗材配置)。
    filament_name：打印方案里指定的耗材配置（留空 = 按材料自动选）。
    v2.55：指定的配置材料和 material 不一样时不用它（按材料自动选），原因写进 notes（[{zh, th}]）。
    v2.55：自动选出来的配置还是别的材料（PC / 丝绸料 / 不认识的材料 → 打印机默认的 PLA）→ 抛 SliceError，不切；
    strict=False（只看配置、列可选配置时）不抛，原因写进 notes。"""
    exe = find_orca(cfg)
    if not exe:
        raise SliceError("没有找到 OrcaSlicer。请在设置页点「手动选择程序」选 orca-slicer.exe（或它的桌面快捷方式）")
    printers = cfg.get("printers") or DEFAULT_PRINTERS
    if printer_index >= len(printers):
        raise SliceError("打印机序号不对")
    from . import fleet
    p = fleet.effective(printers[printer_index], cfg)    # v2.54：Orca 配置按机型模板 + 这台的单独设置
    if fleet.tech_of(p) == "resin":
        raise SliceError(f"「{p.get('name')}」是光固化打印机：请在电脑上用 Photon Workshop / Chitubox / Lychee 切好后，"
                         "在打印方案里「上传电脑上切好的文件」")
    from . import orca_profiles as op
    idx = op.build_index(exe)
    auto = op.auto_match(idx, p.get("name", ""), material)
    machine = _usable(idx, p.get("orca_machine")) or auto["orca_machine"]
    process = _usable(idx, p.get("orca_process")) or auto["orca_process"]
    filament = (filament_name or "").strip()
    if filament and not op._lookup(idx, filament):
        raise SliceError(f"打印方案里指定的耗材配置「{filament}」在 OrcaSlicer 里找不到，请重新选择")
    bad = filament_mismatch(idx, filament, material)
    if bad:                 # 安全：PLA 的配置（温度）不能拿去打 PETG / TPU
        import logging
        logging.getLogger("slicer").warning("filament profile %s is %s, plate material %s: ignored", filament, bad, material)
        if notes is not None:
            notes.append({"zh": f"指定的耗材配置「{filament}」是 {bad}，这一盘打 {material}：没有用它，改用 {material} 的通用配置。请在这一盘的参数里重新选耗材配置",
                          "th": f"โปรไฟล์ฟิลาเมนต์「{filament}」เป็น {bad} แต่ถาดนี้พิมพ์ {material}: ไม่ได้ใช้ ใช้โปรไฟล์ทั่วไปของ {material} แทน กรุณาเลือกโปรไฟล์ใหม่"})
        filament = ""
    if not filament:
        filament = _usable(idx, p.get("orca_filament"))
        # 产品材质不是 PLA 时，自动换成对应材质的通用耗材配置
        if material and material.upper() != "PLA" and machine:
            filament = op.match_filament(idx, machine, material) or filament
        filament = filament or (op.match_filament(idx, machine, material) if machine else "")
        if machine and not filament and material and material.upper() != "PLA":
            raise SliceError(no_profile_msg(material))
    for label, f in (("打印机", machine), ("工艺", process), ("耗材", filament)):
        if not f:
            raise SliceError(f"「{p.get('name')}」的{label}配置没有设置，也没能自动匹配。"
                             f"请到设置页点「自动匹配配置」，或从下拉里选择（OrcaSlicer 找到 {op.summary(idx)['machine']} 个打印机配置）")
    bad = filament_mismatch(idx, filament, material)     # 最后用的配置（自动选的）再核对一次材料
    if bad:
        msg = no_profile_msg(material, filament, bad)
        if strict:
            raise SliceError(msg)
        if notes is not None:
            zh, th = msg.split(" / ", 1)
            notes.append({"zh": zh, "th": th, "level": "error"})
    return exe, idx, machine, process, filament


def _clean_model(model_path, out_dir, keep_slots=False):
    """3MF：去掉 Metadata 里的切片软件参数（project_settings / model_settings / 切片信息），只留模型。STL 原样用。
    v2.52：keep_slots=True（按打印方案切多色盘）时保留 model_settings.config —— 里面是每个零件用哪个耗材槽，
    去掉的话 OrcaSlicer 会全部用 1 号槽（实测 OrcaSlicer 2.3.1：普通 3MF + 这个文件 → 按槽分色切）。"""
    if not model_path.lower().endswith(".3mf"):
        return model_path
    import zipfile
    try:
        src = zipfile.ZipFile(model_path)
        names = src.namelist()
        if not any(n.lower().startswith("metadata/") for n in names):
            return model_path
        out = os.path.join(out_dir, "model_clean.3mf")
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for n in names:
                low = n.lower()
                if keep_slots and low == "metadata/model_settings.config":
                    pass
                elif low.startswith("metadata/") and (low.endswith((".config", ".json", ".gcode", ".md5", ".xml")) or "plate" in low):
                    continue
                z.writestr(src.getinfo(n), src.read(n))
        return out
    except Exception:  # noqa: BLE001  清理不了就用原文件
        return model_path


def _reduce_large(model_path, out_dir, max_tris=800_000, min_mb=15):
    """模型文件大、面数多于 max_tris 时：按 0.02 → 0.1 mm 的格子合并顶点（逐步放大直到面数够少），写成 STL。
    多个零件的 3MF 不处理（零件位置可能对不上）。返回 (新文件, 说明) 或 (None, "")。"""
    try:
        if os.path.getsize(model_path) < min_mb * 1048576:
            return None, ""
        from . import modellib, preview, mesh
        import numpy as np
        parts = modellib.load_parts(model_path)
        if model_path.lower().endswith(".3mf") and len(parts) > 1:
            return None, ""
        tris = np.concatenate([t for _n, t in parts]).astype(np.float32)
        n0 = len(tris)
        if n0 <= max_tris:
            return None, ""
        cell, verts, idx = 0.02, None, None
        while cell <= 0.1001:
            verts, idx = preview._index(tris, cell)
            if len(idx) <= max_tris:
                break
            cell *= 1.5
        if len(idx) > n0 * 0.9:             # 本来就不密，简化不了多少：用原文件
            return None, ""
        out = os.path.join(out_dir, "model_reduced.stl")
        mesh.write_stl(verts[idx.astype(np.int64)], out)
        return out, f"模型 {n0:,} 个面，合并 {min(cell, 0.1):.2f} mm 以内的顶点后 {len(idx):,} 个面再切（打印效果没有区别）"
    except Exception:  # noqa: BLE001  简化不了就用原文件
        return None, ""


# OrcaSlicer 命令行的返回码（src/libslic3r/Utils.hpp 的 CLI_*）→ 说人话。Windows 上负数会显示成 4294967xxx。
ORCA_RC = {
    -1: "运行环境出错", -2: "命令行参数不对", -3: "找不到模型文件", -5: "打印机 / 工艺 / 耗材配置文件有问题",
    -6: "模型文件读不了（可能损坏）", -14: "内存不够", -17: "工艺配置和这台打印机不匹配",
    -18: "3MF 里带的参数有不认识的值", -20: "模型超出打印范围、被缩小了", -21: "自动摆盘失败", -22: "自动摆放方向失败",
    -50: "盘上没有能切的零件（零件不在打印范围里，或者分散在几个盘上）", -51: "切片前检查没通过",
    -52: "有零件一部分在打印范围外", -58: "切片时间太长", -59: "模型面数太多",
    -60: "跳过不能打的零件后没有零件可切", -61: "耗材和热床板不匹配", -100: "切片过程出错", -102: "走线超出可打印区域",
}


def rc_signed(rc):
    """4294967246 → -50（Windows 把负的返回码当无符号数显示）。"""
    try:
        rc = int(rc)
    except (TypeError, ValueError):
        return rc
    if rc >= (1 << 31):
        return rc - (1 << 32)
    if 156 <= rc <= 255:                        # Linux（NAS）上只有低 8 位：-50 → 206，-100 → 156
        return rc - 256
    return rc


def _as_parts_stl(model_path, out_dir):
    """3MF 里每个零件单独存一个 STL（各自挪到原点），一起交给 OrcaSlicer 自动摆盘。
    v2.43.3：零件在文件里摆在盘外 / 分散在几个盘上时（返回码 -50），合成一个 STL 只会更大，拆开摆才放得下。"""
    try:
        from . import mesh, modellib
        import numpy as np
        parts = modellib.load_parts(model_path)
        if len(parts) < 2:
            return []
        out = []
        for i, (_n, t) in enumerate(parts):
            t = np.asarray(t, dtype=np.float64)
            if not len(t):
                continue
            mn, mx = t.reshape(-1, 3).min(0), t.reshape(-1, 3).max(0)
            t = t - np.array([(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]])
            path = os.path.join(out_dir, f"part_{i + 1:02d}.stl")
            mesh.write_stl(t, path)
            out.append(path)
        return out
    except Exception:  # noqa: BLE001
        return []


def _as_stl(model_path, out_dir):
    """把 3MF 转成 STL（所有零件合在一起），给切片失败时重试。"""
    try:
        from . import mesh, modellib
        import numpy as np
        parts = modellib.load_parts(model_path)
        tris = np.concatenate([t for _n, t in parts]).astype(np.float64)
        mn, mx = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)          # v2.43.3：挪到原点（文件里可能摆在盘外）
        tris = tris - np.array([(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mn[2]])
        out = os.path.join(out_dir, "model_fallback.stl")
        mesh.write_stl(tris, out)
        return out
    except Exception:  # noqa: BLE001
        return None


# v2.52 多色切片：开擦料塔（冲刷换色的料）、换色时冲刷（OrcaSlicer 工艺参数）
MULTI_OVERRIDES = {"enable_prime_tower": "1", "flush_into_infill": "1", "flush_into_support": "1"}


def orca_slice(cfg, model_path, printer_index=0, material="PLA", timeout=600, overrides=None, keep_to=None,
               copies=1, orient=True, filament_name=None, filament_overrides=None, arrange=True, filaments=None, keep_settings=False):
    """调用 OrcaSlicer 命令行切片，返回 {grams, hours, source, log}。
    v2.20：配置（打印机 / 工艺 / 耗材）在 NAS 上算好写成文件；切片本身有电脑在线时交给电脑（core/accel），不然在 NAS 上做。
    v2.52：arrange=False 按文件里摆好的位置切（手动摆盘）；filaments=[{material, hex}]（多色，每个 AMS 槽一个）——
    每槽写一份耗材配置（颜色按槽），结果里带每个耗材的克数（filaments）、冲刷废料（purge_g）。多色只在本机切（不交给电脑）。
    v2.55：keep_settings=True（零件有单独的层高 / 填充 / 壁数，写在 3MF 的 model_settings.config 里）→ 保留这个文件、只在本机切。"""
    from . import accel
    from . import orca_profiles as op
    notes = []
    exe, idx, machine, process, filament = resolve_profiles(cfg, printer_index, material, filament_name, notes)
    from . import fleet
    p = fleet.effective((cfg.get("printers") or DEFAULT_PRINTERS)[printer_index], cfg)
    out_dir = tempfile.mkdtemp(prefix="slice_")
    try:
        try:
            m_path, mcfg = op.write_flat(idx, machine, "machine", out_dir)
            mname = mcfg.get("name") or machine
            p_path, _ = op.write_flat(idx, process, "process", out_dir, mname, overrides)
            f_path, _ = op.write_flat(idx, filament, "filament", out_dir, mname, filament_overrides)
            slot_used = []
            if filaments and len(filaments) > 1:          # v2.52 多色：每个槽一份耗材配置（按材料选，颜色按槽）
                fps_ = []
                for k, fl in enumerate(filaments):
                    _e, _i, _m, _p, fname_k = resolve_profiles(cfg, printer_index, fl.get("material") or material, None)
                    # v2.55：每槽自己的温度调整（fl["overrides"]，没有这个键时用 filament_overrides）——
                    # 不同材料（PLA + PETG / TPU）不能共用一个喷嘴温度
                    fo = dict((fl.get("overrides") if "overrides" in fl else filament_overrides) or {})
                    if fl.get("hex"):
                        fo["filament_colour"] = [fl["hex"]]
                    sub = os.path.join(out_dir, f"fil{k + 1}")
                    os.makedirs(sub, exist_ok=True)
                    fk, _ = op.write_flat(idx, fname_k, "filament", sub, mname, fo)
                    fps_.append(fk)
                    slot_used.append(f"槽 {k + 1}：{fname_k}" + (f"（{fo.get('nozzle_temperature', [''])[0]}°C）" if fo.get("nozzle_temperature") else ""))
                f_path = ";".join(fps_)
        except op.ProfileError as e:
            raise SliceError(f"「{p.get('name')}」的配置有问题：{e}") from e
        used = f"打印机配置：{machine}\n工艺配置：{process}\n耗材配置：{filament}\n"
        if slot_used:
            used += "每槽耗材：" + "；".join(slot_used) + "\n"
        if filament_overrides:
            used += "耗材调整：" + ", ".join(f"{k}={v}" for k, v in filament_overrides.items()) + "\n"
        if overrides:
            used += "按打印建议调整：" + ", ".join(f"{k}={v}" for k, v in overrides.items()) + "\n"
        size_mb = os.path.getsize(model_path) / 1048576
        timeout = max(timeout, min(3600, int(600 + size_mb * 30)))
        params = {"orient": bool(orient), "copies": int(copies or 1), "timeout": timeout, "material": material, "used": used,
                  "keep": bool(keep_to), "model_name": os.path.basename(model_path), "arrange": bool(arrange),
                  "keep_slots": bool(filaments and len(filaments) > 1) or bool(keep_settings)}
        name = params["model_name"]
        if ";" in f_path or keep_settings:          # 多色：几份耗材配置 / 零件单独参数：只在本机切
            result = run_cli(exe, m_path, p_path, f_path, model_path, os.path.join(out_dir, "work"), params, keep_to, model_name=name)
            result["printer"] = printer_index
            result["profiles"] = {"machine": machine, "process": process, "filament": filament, "filaments": len(filaments or [1])}
            result["warnings"] = notes
            return result

        def remote_done(res, files):
            if keep_to:
                if not files.get("kept"):
                    raise SliceError("电脑切好了，但切片文件没有传回来")
                shutil.copyfile(files["kept"], keep_to)
                res["kept"] = keep_to
            res["where"] = "pc"
            return res
        result = accel.run("slice", params, {"model": model_path, "machine": m_path, "process": p_path, "filament": f_path},
                           lambda: run_cli(exe, m_path, p_path, f_path, model_path, os.path.join(out_dir, "work"), params, keep_to,
                                           model_name=name),
                           remote_done, timeout=timeout + 120, err_cls=SliceError)
        result["printer"] = printer_index
        result["profiles"] = {"machine": machine, "process": process, "filament": filament}
        result["warnings"] = notes
        return result
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def run_cli(exe, m_path, p_path, f_path, model_path, out_dir, params, keep_to=None, model_name=""):
    """真正调 OrcaSlicer 命令行（NAS 或电脑上）。params：orient / copies / timeout / material / used（日志开头）。"""
    os.makedirs(out_dir, exist_ok=True)
    material = params.get("material") or "PLA"
    timeout = int(params.get("timeout") or 600)
    used = params.get("used") or ""
    # 文件名要带正确的扩展名（电脑上下载下来的临时文件可能没有）
    ext = os.path.splitext(model_name or model_path)[1].lower() or ".stl"
    if not model_path.lower().endswith(ext):
        fixed = os.path.join(out_dir, "model_in" + ext)
        shutil.copyfile(model_path, fixed)
        model_path = fixed
    out_3mf = os.path.join(out_dir, "result.gcode.3mf")
    # 注意：--export-3mf 只能写文件名（会放进 --outputdir），写完整路径会变成「目录/目录/文件」导致找不到
    cmd = [exe, "--arrange", "1" if params.get("arrange", True) else "0", "--orient", "1" if params.get("orient", True) else "0", "--slice", "0",
           "--load-settings", f"{m_path};{p_path}",
           "--load-filaments", f_path,
           "--allow-newer-file",
           "--outputdir", out_dir,
           "--export-3mf", "result.gcode.3mf"]
    copies = int(params.get("copies") or 1)
    if copies > 1:
        cmd += ["--clone-objects", str(copies)]

    def run(model_file, extra=()):
        files = model_file if isinstance(model_file, list) else [model_file]
        try:
            r = subprocess.run(cmd + list(extra) + files, capture_output=True, timeout=timeout,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as e:
            raise SliceError(f"切片超时（{timeout} 秒）") from e
        except OSError as e:
            raise SliceError(f"无法启动 OrcaSlicer：{e}") from e
        return r, (r.stdout or b"").decode("utf-8", "ignore")[-3000:] + "\n" + (r.stderr or b"").decode("utf-8", "ignore")[-3000:]

    # 拓竹 / Orca 的项目 3MF 里带着它自己的参数（有些值 Orca 命令行不认，例如 wall_filament=0），
    # 先去掉这些参数只留模型；还不行再转成 STL 切（v2.18）
    model_in = _clean_model(model_path, out_dir, keep_slots=bool(params.get("keep_slots")))
    # 大文件（v2.19）：面数特别多的模型先合并极近的顶点（< 0.1 mm，喷嘴 0.4 mm 打不出来的细节），再切
    small, note = _reduce_large(model_in, out_dir)
    if small:
        model_in = small
        used += note + "\n"
    r, out = run(model_in)
    log = used + out
    if r.returncode != 0 and model_path.lower().endswith(".3mf") and not glob.glob(os.path.join(out_dir, "*.gcode*")):
        first = rc_signed(r.returncode)
        parts = _as_parts_stl(model_path, out_dir)
        if parts:                               # v2.43.3：先把零件拆开，让 OrcaSlicer 自动摆盘
            r, out = run(parts, ["--ensure-on-bed"])        # 老版本 OrcaSlicer 不认这个参数：只在重试时加
            log = used + f"（3MF 切片失败：{ORCA_RC.get(first, first)}；把 {len(parts)} 个零件拆开、自动摆盘重试）\n" + out
        if r.returncode != 0 and not glob.glob(os.path.join(out_dir, "*.gcode*")):
            stl = _as_stl(model_path, out_dir)
            if stl:
                r, out = run(stl, ["--ensure-on-bed"])
                log = used + f"（3MF 切片失败：{ORCA_RC.get(first, first)}；合成一个 STL、挪到盘中间重试）\n" + out
    result = None
    used_file = None
    # 优先读导出的 3mf / 任何 3mf / 任何 gcode（不同版本的 OrcaSlicer 输出文件名不一样）
    candidates = []
    for c in [out_3mf] + glob.glob(os.path.join(out_dir, "**", "*.3mf"), recursive=True) + \
            glob.glob(os.path.join(out_dir, "**", "*.gcode"), recursive=True):
        if os.path.isfile(c) and c not in candidates and not c.endswith(("_flat.json",)) and \
                os.path.basename(c) not in ("model_clean.3mf", "model_in.3mf"):
            candidates.append(c)
    for c in candidates:
        try:
            result = parse_sliced_file(c, material)
            used_file = c
            break
        except SliceError:
            continue
    rj = os.path.join(out_dir, "result.json")
    if result is None and os.path.exists(rj):
        try:
            data = json.load(open(rj, encoding="utf-8"))
            log += "\nresult.json: " + json.dumps(data, ensure_ascii=False)[:1500]
        except (OSError, json.JSONDecodeError):
            pass
    if result is None:
        hint = ""
        rc = rc_signed(r.returncode)
        if rc in (-9, 137, -6, 134, -14) or "bad_alloc" in log or "out of memory" in log.lower():
            hint = "看起来是内存不够（NAS 内存小、模型太大）：可以把模型在电脑上简化 / 拆开，或者在电脑上切好后上传切片文件。\n"
        elif rc in (-50, -52, -60, -20):
            hint = ("零件放不进打印范围：看看模型尺寸是不是单位错了（英寸 / 米），或者模型比热床大；"
                    "多个零件的 3MF 可以在 OrcaSlicer 里摆好一盘、切好后上传切片文件。\n")
        why = ORCA_RC.get(rc)
        raise SliceError(f"切片没有成功（返回码 {rc}{'：' + why if why else ''}）。{hint}日志：\n{log.strip()[-1500:]}")
    if keep_to:   # 打印文件库：保留切片好的文件
        if used_file.endswith(".3mf"):
            shutil.copyfile(used_file, keep_to)
        else:
            # 只有 G-code：打包成拓竹能用的 .gcode.3mf（Creality 发送时会再取出 G-code）
            gcode_to_3mf(used_file, keep_to)
        result["kept_kind"] = "3mf"
        result["kept"] = keep_to
    result["source"] = "orca_cli"
    result["log"] = log.strip()[-800:]
    return result


def orca_test(cfg, printer_index=0):
    d = tempfile.mkdtemp(prefix="slicetest_")
    try:
        cube = os.path.join(d, "cube20.stl")
        _cube_stl(cube)
        return orca_slice(cfg, cube, printer_index, timeout=300)
    finally:
        shutil.rmtree(d, ignore_errors=True)
