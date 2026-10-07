"""产品库：每个产品一个 JSON 文件，图片放在同名文件夹里。"""
import json
import os
import re
import shutil
import time

from .config import DATA_DIR

PRODUCTS_DIR = os.path.join(DATA_DIR, "products")


def _ensure():
    os.makedirs(PRODUCTS_DIR, exist_ok=True)


def safe_id(pid):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", pid or ""):
        raise ValueError("产品编码只能用英文字母、数字、- 和 _")
    return pid


def product_dir(pid):
    return os.path.join(PRODUCTS_DIR, safe_id(pid))


def image_dir(pid, kind):
    d = os.path.join(product_dir(pid), kind)
    os.makedirs(d, exist_ok=True)
    return d


SEQ_PATH = os.path.join(DATA_DIR, "sequence.json")


def new_id(prefix):
    """顺序编号，删除过的号码也不会再用。"""
    _ensure()
    seq = {}
    if os.path.exists(SEQ_PATH):
        try:
            with open(SEQ_PATH, "r", encoding="utf-8") as f:
                seq = json.load(f)
        except (OSError, json.JSONDecodeError):
            seq = {}
    nums = [int(seq.get(prefix, 0))]
    for name in os.listdir(PRODUCTS_DIR):
        m = re.fullmatch(re.escape(prefix) + r"(\d+)\.json", name)
        if m:
            nums.append(int(m.group(1)))
    n = max(nums) + 1
    seq[prefix] = n
    with open(SEQ_PATH, "w", encoding="utf-8") as f:
        json.dump(seq, f)
    return f"{prefix}{n:04d}"


def _seo_score(p):
    try:
        from . import seo
        return seo.quick_score(p)
    except Exception:  # noqa: BLE001
        return None


def list_products():
    _ensure()
    out = []
    for name in sorted(os.listdir(PRODUCTS_DIR)):
        if name.endswith(".json"):
            try:
                p = load(name[:-5])
                out.append({
                    "id": p["id"],
                    "name_zh": p.get("name_zh", ""),
                    "title_th": p.get("copy", {}).get("title_th", ""),
                    "variants": len(p.get("variants", [])),
                    "images": len(p.get("images", [])),
                    "image_urls": sum(1 for i in p.get("images", []) if i.get("url")),
                    "updated_at": p.get("updated_at", 0),
                    "seo": _seo_score(p),                       # v2.23 搜索分
                    "seo_prop": bool(p.get("copy_proposal")),   # 有待确认的搜索优化
                })
            except Exception:
                continue
    out.sort(key=lambda x: x["updated_at"], reverse=True)
    return out


def load(pid):
    with open(os.path.join(PRODUCTS_DIR, safe_id(pid) + ".json"), "r", encoding="utf-8") as f:
        p = json.load(f)
    # 兼容旧版本数据
    for k, v in (("category", {}), ("attributes", {}), ("copy", {}), ("images", []), ("exported_at", None),
                 ("shopee_category", {})):
        p.setdefault(k, v)
    return p


def save(product):
    _ensure()
    safe_id(product["id"])
    product["updated_at"] = int(time.time())
    path = os.path.join(PRODUCTS_DIR, product["id"] + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(product, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return product


def bump_rev(product, user=""):
    """产品资料（编辑页能改的字段）被改了一次：版本号 +1，记下是谁、什么时候。
    编辑页保存时带着打开时的版本号，对不上说明中间有人（或运营写回）改过，不会被悄悄覆盖。"""
    product["edit_rev"] = int(product.get("edit_rev") or 0) + 1
    product["edited_by"] = user or ""
    product["edited_at"] = int(time.time())
    return product


def delete(pid):
    path = os.path.join(PRODUCTS_DIR, safe_id(pid) + ".json")
    if os.path.exists(path):
        os.remove(path)
    d = product_dir(pid)
    if os.path.isdir(d):
        shutil.rmtree(d)


def blank_product(pid):
    return {
        "id": pid,
        "name_zh": "",
        "features_zh": "",
        "keywords": "",
        "material": "PLA",
        "size_text": "",
        "package": {"length": 10, "width": 10, "height": 10},
        "package_status": "default",
        "variation1_name_zh": "颜色",
        "variation2_name_zh": "",
        "variants": [{"opt1_zh": "", "opt2_zh": "", "grams": 0, "hours": 0,
                      "manual_price": None, "image": "", "stock": None}],
        "markup": None,
        "images": [],
        "white_bg": None,
        "copy": {},
        "category": {},
        "shopee_category": {},
        "attributes": {},
        "exported_at": None,
        "updated_at": 0,
    }
