"""OrcaSlicer 配置（预设）索引、自动匹配和「展开继承」。

OrcaSlicer 的配置文件是一层层继承的（inherits / include），命令行直接加载系统预设或用户预设时
经常因为找不到父配置而失败。这里把选中的预设和它所有的父配置合并成一个完整的 JSON，再交给命令行。

配置来源（按优先级）：
1. 用户预设  %APPDATA%\\OrcaSlicer\\user\\<账号>\\{machine,process,filament}\\*.json
2. 系统预设  %APPDATA%\\OrcaSlicer\\system\\<厂商>\\...
3. 安装目录  <OrcaSlicer 安装目录>\\resources\\profiles\\<厂商>\\...
设置页里可以填预设名称（推荐）或 .json 文件路径。
"""
import glob
import json
import os
import re
import tempfile

KINDS = ("machine", "process", "filament")
META_DROP = {"inherits", "include", "instantiation", "setting_id", "base_id", "filament_id", "is_custom_defined",
             "user_id", "updated_time", "version"}
# 你的三台打印机的常见叫法 → OrcaSlicer 里的打印机预设名
PRINTER_HINTS = [
    (r"p1s", "Bambu Lab P1S 0.4 nozzle"),
    (r"p1p", "Bambu Lab P1P 0.4 nozzle"),
    (r"x1\s*c|x1\s*carbon", "Bambu Lab X1 Carbon 0.4 nozzle"),
    (r"a1\s*mini", "Bambu Lab A1 mini 0.4 nozzle"),
    (r"\ba1\b", "Bambu Lab A1 0.4 nozzle"),
    (r"k1\s*max", "Creality K1 Max (0.4 nozzle)"),
    (r"k1\s*c\b|k1c", "Creality K1C 0.4 nozzle"),
    (r"k1\s*se", "Creality K1 SE 0.4 nozzle"),
    (r"\bk1\b", "Creality K1 (0.4 nozzle)"),
]

_index = {"key": None, "data": None}


class ProfileError(Exception):
    pass


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def roots(orca_exe=None):
    """[(来源, 厂商目录或用户目录)]"""
    out = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        for d in sorted(glob.glob(os.path.join(appdata, "OrcaSlicer", "user", "*"))):
            out.append(("user", d))
        for d in sorted(glob.glob(os.path.join(appdata, "OrcaSlicer", "system", "*"))):
            if os.path.isdir(d):
                out.append(("system", d))
    if orca_exe:
        base = os.path.dirname(orca_exe)
        for rp in (os.path.join(base, "resources", "profiles"), os.path.join(base, "..", "resources", "profiles"),
                   os.path.join(base, "..", "Resources", "profiles")):
            for d in sorted(glob.glob(os.path.join(rp, "*"))):
                if os.path.isdir(d):
                    out.append(("install", os.path.normpath(d)))
    extra = os.environ.get("ORCA_PROFILES_DIR")  # 测试用
    if extra:
        for d in sorted(glob.glob(os.path.join(extra, "*"))):
            if os.path.isdir(d):
                out.append(("install", d))
    return out


def build_index(orca_exe=None):
    """返回 {"by_name": {name: [entry...]}, "list": {kind: [entry...]}}，entry = dict(name, kind, path, src, vendor, inst, compat, raw?)"""
    rs = roots(orca_exe)
    key = tuple(rs)
    if _index["key"] == key and _index["data"]:
        return _index["data"]
    by_name, lists = {}, {k: [] for k in KINDS}
    for src, d in rs:
        vendor = os.path.basename(d)
        for kind in KINDS:
            for path in glob.glob(os.path.join(d, kind, "**", "*.json"), recursive=True):
                data = _read(path)
                if not isinstance(data, dict):
                    continue
                name = data.get("name") or os.path.splitext(os.path.basename(path))[0]
                e = {"name": name, "kind": kind, "path": path, "src": src, "vendor": vendor,
                     "inst": str(data.get("instantiation", "true" if src == "user" else "false")).lower() == "true",
                     "compat": data.get("compatible_printers") or [],
                     "cond": data.get("compatible_printers_condition") or "",
                     "inherits": data.get("inherits") or "",
                     "ftype": data.get("filament_type")}
                by_name.setdefault(name, []).append(e)
                lists[kind].append(e)
    data = {"by_name": by_name, "list": lists, "roots": rs}
    # 用户预设一般不写兼容打印机，沿用它所继承的系统预设的兼容列表
    for kind in ("process", "filament"):
        for e in lists[kind]:
            if e["src"] != "user" or e["compat"]:
                continue
            cur, n = e, 0
            while cur and not cur["compat"] and cur["inherits"] and n < 6:
                cur = _lookup(data, cur["inherits"], None)
                n += 1
            if cur and cur["compat"]:
                e["compat"] = cur["compat"]
                e["cond"] = cur["cond"]
    _index.update(key=key, data=data)
    return data


def _lookup(idx, name, vendor=None):
    es = idx["by_name"].get(name) or []
    if not es:
        return None
    order = {"user": 0, "system": 1, "install": 2}
    es = sorted(es, key=lambda e: (0 if vendor and e["vendor"] == vendor else 1,
                                   0 if e["vendor"] == "OrcaFilamentLibrary" else 1, order.get(e["src"], 3)))
    return es[0]


def flatten(idx, entry_or_name, kind=None, _depth=0):
    """把一个预设和它所有父配置合并成完整配置（dict）。"""
    if _depth > 20:
        raise ProfileError("配置继承层数过多")
    e = entry_or_name
    if isinstance(e, str):
        if os.path.isfile(e):
            data = _read(e)
            if not isinstance(data, dict):
                raise ProfileError(f"读不了配置文件：{e}")
            e = {"name": data.get("name") or os.path.basename(e), "path": e, "vendor": None, "kind": kind}
        else:
            found = _lookup(idx, e)
            if not found:
                raise ProfileError(f"找不到配置「{e}」")
            e = found
    data = _read(e["path"]) or {}
    merged = {}
    parent = data.get("inherits")
    if parent:
        pe = _lookup(idx, parent, e.get("vendor"))
        if not pe:
            raise ProfileError(f"「{e['name']}」的父配置「{parent}」找不到")
        merged.update(flatten(idx, pe, kind, _depth + 1))
    for inc in data.get("include") or []:
        ie = _lookup(idx, inc, e.get("vendor"))
        if ie:
            merged.update({k: v for k, v in flatten(idx, ie, kind, _depth + 1).items()
                           if k not in ("name", "type", "from")})
    merged.update(data)
    return merged


def _clean(cfg, kind, machine_name=None):
    """去掉继承信息，并让命令行认为「工艺/耗材和这台打印机兼容」。
    新旧版本 OrcaSlicer 命令行都按 compatible_printers 里的打印机名做检查，所以填上打印机名。"""
    out = {k: v for k, v in cfg.items() if k not in META_DROP}
    out["from"] = "system"
    out["inherits"] = ""
    out["type"] = kind
    if kind in ("process", "filament"):
        out["compatible_printers"] = [machine_name] if machine_name else []
        out["compatible_printers_condition"] = ""
        if kind == "filament":
            out["compatible_prints"] = []
            out["compatible_prints_condition"] = ""
    return out


def write_flat(idx, name_or_path, kind, out_dir, machine_name=None, overrides=None):
    cfg = _clean(flatten(idx, name_or_path, kind), kind, machine_name)
    if overrides:
        cfg.update(overrides)
    safe = re.sub(r"[^\w.-]+", "_", str(cfg.get("name") or kind))[:60]
    path = os.path.join(out_dir, f"{kind}_{safe}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)
    return path, cfg


# ---------------- 自动匹配 ----------------
def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def match_machine(idx, printer_name):
    machines = [e for e in idx["list"]["machine"] if e["inst"]]
    names = {e["name"] for e in machines}
    low = (printer_name or "").lower()
    # 用户自己保存的同名预设优先
    for e in machines:
        if e["src"] == "user" and _norm(printer_name) and _norm(printer_name) in _norm(e["name"]):
            return e["name"]
    for pat, target in PRINTER_HINTS:
        if re.search(pat, low) and target in names:
            return target
    n = _norm(printer_name)
    cands = [e["name"] for e in machines if n and n in _norm(e["name"]) and "cfs" not in e["name"].lower()]
    cands.sort(key=lambda x: (0 if "0.4" in x else 1, len(x)))
    return cands[0] if cands else ""


def _compatible(e, machine):
    if e["compat"]:
        return machine in e["compat"]
    if e["src"] == "user":
        return not e["inherits"]  # 继承关系找不到时保守处理
    # 没有任何限制的系统耗材（如 Generic PLA @System）所有打印机通用；工艺必须明确兼容
    return e["kind"] == "filament" and not e["cond"]


def _rank(e, machine):
    explicit = machine in e["compat"]
    return 0 if (e["src"] == "user" and explicit) else (1 if explicit else 2)


def processes_for(idx, machine):
    out = [e for e in idx["list"]["process"] if e["inst"] and _compatible(e, machine)]
    best = {}
    for e in out:
        best[e["name"]] = min(best.get(e["name"], 9), _rank(e, machine))
    return sorted(best, key=lambda n: (best[n], 0 if "0.20mm standard" in n.lower() else 1, n))


def filaments_for(idx, machine):
    out = [e for e in idx["list"]["filament"] if e["inst"] and _compatible(e, machine)]
    best = {}
    for e in out:
        best[e["name"]] = min(best.get(e["name"], 9), _rank(e, machine))
    return sorted(best, key=lambda n: (best[n], 0 if "generic" in n.lower() else 1, n))


def _machine_defaults(idx, machine):
    try:
        m = flatten(idx, machine, "machine")
    except ProfileError:
        return "", []
    fil = m.get("default_filament_profile") or []
    if isinstance(fil, str):
        fil = [fil]
    return m.get("default_print_profile") or "", fil


def match_process(idx, machine):
    dp, _ = _machine_defaults(idx, machine)
    if dp and _lookup(idx, dp):
        return dp
    ps = processes_for(idx, machine)
    return ps[0] if ps else ""


def match_filament(idx, machine, material="PLA"):
    mat = (material or "PLA").upper().strip()
    fils = filaments_for(idx, machine)  # 已按「专用配置优先」排好序
    pat = re.compile(r"(^|\s)generic " + re.escape(mat.lower()) + r"(\s*@.*)?$")
    exact = [n for n in fils if pat.search(n.lower())]
    if exact:
        return exact[0]
    if mat == "PLA":
        _, df = _machine_defaults(idx, machine)
        if df and _lookup(idx, df[0]):
            return df[0]
    loose = [n for n in fils if ("generic " + mat.lower()) in n.lower()]
    return loose[0] if loose else ""


def auto_match(idx, printer_name, material="PLA"):
    m = match_machine(idx, printer_name)
    if not m:
        return {"orca_machine": "", "orca_process": "", "orca_filament": ""}
    return {"orca_machine": m, "orca_process": match_process(idx, m), "orca_filament": match_filament(idx, m, material)}


def summary(idx):
    return {k: sum(1 for e in idx["list"][k] if e["inst"]) for k in KINDS} | {
        "roots": len(idx["roots"]), "user": sum(1 for e in idx["list"]["machine"] if e["src"] == "user")}


def tmpdir():
    return tempfile.mkdtemp(prefix="orca_cfg_")
