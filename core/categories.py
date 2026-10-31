"""类目库。

两部分：
1. 已下载模板的类目（templates_lazada 文件夹）—— 可以直接导出。
2. Lazada 泰国站完整类目树（core/data/lazada_th_categories.tsv，2890 个叶子类目）——
   AI 在已下载类目都不合适时，从完整树里给出建议类目，再去下载那个类目的模板。
"""
import os
import re
import threading

from . import lazada_template
from .config import BASE_DIR

TEMPLATE_DIR = os.environ.get("LH_TEMPLATE_DIR") or os.path.join(BASE_DIR, "templates_lazada")
TREE_PATH = os.path.join(BASE_DIR, "core", "data", "lazada_th_categories.tsv")
_cache = {}
_lock = threading.Lock()
_tree = None

# 常用类目的中文名（界面显示用）
ZH_NAMES = {
    "11924": "家居装饰 > 花瓶",
    "10100093": "家居装饰 > 摆件与雕像",
    "3800": "玩具 > 手办与收藏品",
    "12148": "园艺 > 花盆",
    "12298": "灯具 > 夜灯",
    "14362": "手机配件 > 手机支架",
    "10100396": "音频配件 > 耳机/音箱支架",
    "62473005": "游戏配件 > 其他游戏配件",
    "10100372": "电脑配件 > 理线器",
    "12198": "文具办公 > 桌面收纳",
    "11909": "收纳 > 收纳盒",
    "11911": "收纳 > 其他厨房收纳",
    "11882": "浴室 > 置物架与挂钩",
    "14221": "玩具 > 解压/指尖玩具",
    "3330": "玩具 > 益智游戏",
    "6707": "桌游 > 骰子与桌游配件",
    "62545802": "玩具 > Cosplay 道具",
    "10100632": "宠物用品 > 宠物玩具",
    "11926": "家居装饰 > 墙面装饰/相框/艺术品",
    "12689": "汽车用品 > 车载手机支架与充电",
    "6075": "家电配件 > 洗衣机/熨斗/烘干机配件",
    "13890": "家居清洁 > 洗手池和排水管（清洁类）",
    "12049": "水暖五金 > 存水弯/排水配件",
    "10100196": "水暖五金 > 水管与软管配件（接头/三通）",
    "12051": "水暖五金 > 洁具零件与阀门",
    "10100195": "水暖五金 > 水管/气管/软管",
    "12115": "工具 > 手动工具配件",
}


# 已知要泰国 TISI 等许可证才能上的类目（夜灯、解压玩具……；模板 / 接口里看得出来的会自动加进来）
LICENSE_KNOWN = {"12298", "14221"}


def needs_license(cat_id):
    """这个类目上架要不要 TISI 等许可证（v2.45：AI 匹配类目时避开）。"""
    cid = str(cat_id or "")
    if cid in LICENSE_KNOWN:
        return True
    with _lib_lock:
        hit = next((c for c in _library() if c.get("cat_id") == cid), None)
    if hit and hit.get("needs_license"):
        return True
    from . import lazada_cats
    return lazada_cats.needs_license(cid)


def reset_tree():
    global _tree
    _tree = None
    _lib_memo["key"] = None


def tree():
    """完整类目树：{id: (路径, 是否禁用)}。v2.45：接口拉过最新的类目树就用它（core/lazada_cats），不然用内置的。"""
    global _tree
    if _tree is None:
        t = {}
        from . import lazada_cats
        path = lazada_cats.tree_path() or TREE_PATH
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) == 3:
                        t[parts[0]] = (parts[2], parts[1] == "D")
        _tree = t
    return _tree


def path_of(cat_id):
    return (tree().get(str(cat_id)) or ("", False))[0]


def display_name(cat_id, sheet=""):
    if str(cat_id) in ZH_NAMES:
        return ZH_NAMES[str(cat_id)]
    p = path_of(cat_id)
    if p:
        return " > ".join(p.split(" > ")[-2:])
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", sheet).replace("_", " ").strip()


def search_tree(keywords, limit=60):
    """按关键词在完整类目树里找候选叶子类目（用于 AI 第二步选择）。"""
    kws = [k.strip().lower() for k in keywords if k and k.strip()]
    scored = []
    for cid, (path, disabled) in tree().items():
        if disabled:
            continue
        low = path.lower()
        leaf = low.split(" > ")[-1]
        score = sum(3 if k in leaf else 1 for k in kws if k in low)
        if score:
            scored.append((score, cid, path))
    scored.sort(key=lambda x: (-x[0], len(x[2])))
    return [(cid, path) for _, cid, path in scored[:limit]]


def _disk_cache_path(path):
    from .config import DATA_DIR
    d = os.path.join(DATA_DIR, "tpl_cache")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, os.path.basename(path) + ".json")


_CACHE_MAX = 12      # 内存里最多留几个模板的完整解析结果（全部类目约 160 个文件，全放内存太占 NAS 内存）


def parse_cached(path, keep=True):
    """解析模板（内存缓存 + 硬盘缓存）。v2.25：模板多了（全部类目 158 个文件），NAS 重启后不用全部重新解析。"""
    import json
    mtime = os.path.getmtime(path)
    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
    cp = _disk_cache_path(path)
    data = None
    try:
        if os.path.exists(cp):
            with open(cp, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("mtime") == mtime and d.get("v") == 1:
                data = d["sheets"]
    except (OSError, ValueError):
        data = None
    if data is None:
        data = lazada_template.parse(path)
        try:
            with open(cp + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"mtime": mtime, "v": 1, "sheets": data}, f, ensure_ascii=False)
            os.replace(cp + ".tmp", cp)
        except OSError:
            pass
    if keep:
        with _lock:
            _cache.pop(path, None)
            _cache[path] = (mtime, data)
            while len(_cache) > _CACHE_MAX:
                _cache.pop(next(iter(_cache)))
    return data


def _summary(path):
    """一个模板文件里每个类目的简要信息（类目列表用），单独缓存到硬盘，不把整个模板留在内存。"""
    import json
    mtime = os.path.getmtime(path)
    cp = _disk_cache_path(path)[:-5] + ".sum.json"
    try:
        with open(cp, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("mtime") == mtime and d.get("v") == 1:
            return d["cats"]
    except (OSError, ValueError):
        pass
    out = []
    for s in parse_cached(path, keep=False):
        attrs = lazada_template.attribute_fields(s)
        out.append({"sheet": s["sheet"], "cat_id": s["cat_id"],
                    "needs_license": any(x["key"].startswith("productQualifications.") and x["required"] for x in attrs),
                    "attr_labels": [a["label"] for a in attrs if a["key"].startswith("catProperty.")]})
    try:
        with open(cp + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"mtime": mtime, "v": 1, "cats": out}, f, ensure_ascii=False)
        os.replace(cp + ".tmp", cp)
    except OSError:
        pass
    return out


def template_files():
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    return sorted(f for f in os.listdir(TEMPLATE_DIR)
                  if f.lower().endswith(".xlsx") and not f.startswith("~$"))


_lib_memo = {"key": None, "val": None}
_lib_lock = threading.Lock()


def library():
    """可以选的类目。v2.45：店铺接了 Lazada 接口时，类目树里的所有类目都能选（没有模板的 id 是 "api|类目ID"，属性从接口拉）。"""
    with _lib_lock:
        lib = _library()
    from . import lazada_cats
    if not lazada_cats.enabled():
        return lib
    have = {c["cat_id"] for c in lib}
    extra = [{"id": lazada_cats.id_of(cid), "template": "", "sheet": "", "cat_id": cid, "name": display_name(cid),
              "path": path, "needs_license": False, "attr_labels": [], "source": "api"}
             for cid, (path, disabled) in tree().items() if cid not in have and not disabled and cid.isdigit()]
    return sorted(lib + extra, key=lambda c: c["name"])


def _library():
    """已下载模板里的类目：id = 模板文件|工作表。同一类目ID出现在多个模板时只保留最新的模板。
    v2.25：按（文件, 修改时间）记住结果，模板没变就不重新算。"""
    files = template_files()
    files.sort(key=lambda f: os.path.getmtime(os.path.join(TEMPLATE_DIR, f)))
    key = tuple((f, os.path.getmtime(os.path.join(TEMPLATE_DIR, f))) for f in files)
    if _lib_memo["key"] == key and _lib_memo["val"] is not None:
        return _lib_memo["val"]
    cats = {}
    for f in files:
        try:
            sheets = _summary(os.path.join(TEMPLATE_DIR, f))
        except Exception:
            continue
        for s in sheets:
            key2 = s["cat_id"] or f"{f}|{s['sheet']}"
            cats[key2] = {
                "id": f"{f}|{s['sheet']}",
                "template": f,
                "sheet": s["sheet"],
                "cat_id": s["cat_id"],
                "name": display_name(s["cat_id"], s["sheet"]),
                "path": path_of(s["cat_id"]),
                "needs_license": s["needs_license"],
                "attr_labels": s["attr_labels"],
            }
    val = sorted(cats.values(), key=lambda c: c["name"])
    _lib_memo.update(key=key, val=val)
    return val


def by_cat_id(cat_id):
    """Lazada 类目 ID → 类目（library 里的一项）：有模板用模板；没模板、接了接口时是 "api|类目ID"；都没有返回 None。"""
    cid = str(cat_id or "")
    with _lib_lock:
        hit = next((c for c in _library() if c.get("cat_id") == cid), None)
    if hit:
        return hit
    from . import lazada_cats
    if cid.isdigit() and lazada_cats.enabled():
        return {"id": lazada_cats.id_of(cid), "template": "", "sheet": "", "cat_id": cid, "name": display_name(cid),
                "path": path_of(cid), "needs_license": False, "attr_labels": [], "source": "api"}
    return None


def get(cat_id_str, for_export=False):
    """按 '模板文件|工作表'（或 v2.45 的 'api|类目ID'）取类目完整信息（含字段）。
    v2.45：店铺接了 Lazada 接口时，字段（属性、选项、必填）优先用接口拉的（core/lazada_cats），模板文件和工作表名照旧带着；
    导出 Excel（for_export=True）一定用模板本身的字段（要按模板的列写）。"""
    if not cat_id_str or "|" not in cat_id_str:
        return None
    from . import lazada_cats
    if cat_id_str.startswith("api|"):
        return None if for_export else lazada_cats.get(cat_id_str)
    f, sheet = cat_id_str.split("|", 1)
    path = os.path.join(TEMPLATE_DIR, os.path.basename(f))
    if not os.path.exists(path):
        return None
    for s in parse_cached(path):
        if s["sheet"] == sheet:
            out = {**s, "template": os.path.basename(f), "path": path, "id": cat_id_str,
                   "name": display_name(s["cat_id"], sheet)}
            if not for_export and s.get("cat_id") and lazada_cats.enabled():
                api = lazada_cats.as_sheet(s["cat_id"])
                if api and api["fields"]:
                    out.update(fields=api["fields"], source="api")
            return out
    return None


def memory_key(cat):
    return cat.get("cat_id") or cat["id"]
