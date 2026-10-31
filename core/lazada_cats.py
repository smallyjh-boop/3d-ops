"""Lazada 类目和类目属性直接从开放接口拉（v2.45）。

以前类目属性只能从卖家中心的批量上新模板（Excel）里读：模板没下载的类目没法填属性、没法上架，
而且模板里的属性代码和接口的要对来对去。店铺接上接口以后：
  · 类目树：/category/tree/get（泰文），每周刷新一次，存 data/lazada_api/categories.tsv（格式和内置的类目表一样）；
  · 类目属性：/category/attributes/get，用到哪个类目拉哪个，缓存 7 天（data/lazada_api/attrs/<类目ID>.json）；
  · 拉回来的属性按模板的样子生成「字段表」（as_sheet）：字段代码 catProperty.p-<属性ID> / saleProp.p-<属性ID>、
    选项、必填、品牌 / 颜色 / 保修……和模板解析出来的一样，AI 填属性、上架检查、编辑页、推送都不用改。
类目编号：接口类目在系统里的 id 写成 "api|<类目ID>"（模板类目是 "模板文件|工作表"）。
没有接口店铺、或者接口拉不到时，照旧用模板。
对外：enabled() tree_path() refresh_tree() attrs(cat_id) as_sheet(cat_id) get(id) id_of(cat_id)
"""
import json
import os
import threading
import time

from .config import DATA_DIR

DIR = os.path.join(DATA_DIR, "lazada_api")
TREE_FILE = os.path.join(DIR, "categories.tsv")
ATTR_TTL = 7 * 86400
TREE_TTL = 7 * 86400
_lock = threading.Lock()
_mem = {}

# 接口属性名 → 模板里固定的字段代码（文案、价格、包裹这些由产品资料填，不在属性里）
SKIP = {"name", "description", "short_description", "name_en", "description_en", "short_description_en", "video",
        "package_content", "package_weight", "package_length", "package_width", "package_height", "price",
        "special_price", "special_from_date", "special_to_date", "quantity", "SellerSku", "seller_sku", "color_thumbnail",
        "__images__", "promotion_whitebkg_image", "delivery_option_sof", "tax_class", "product_warranty_en"}
FIXED = {"warranty_type": ("warrantyType", "warrantyType"), "warranty": ("warrantyPeriod", "warrantyPeriod"),
         "product_warranty": ("warrantyPolicy", ""), "Hazmat": ("radioDangerousGoods", "radioDangerousGoods")}


def _conn():
    """第一个启用的 Lazada 店铺的连接器；没有返回 (None, None)。"""
    from . import connectors, db, integrations
    try:
        r = db.conn().execute("SELECT id FROM shops WHERE platform='lazada' AND enabled=1 ORDER BY id").fetchone()
    except Exception:  # noqa: BLE001  还没建店铺表
        return None, None
    if not r:
        return None, None
    s = integrations.get_shop_raw(r["id"])
    conn = connectors.make("lazada", s["creds"])
    try:
        conn.check()
    except connectors.NotReady:
        return None, None
    return r["id"], conn


_en = {"t": 0, "v": False}
_fail = {}          # 类目ID → 上次拉失败的时间（10 分钟内不再拉，免得每次检查都等网络）


def enabled():
    """有没有接了接口的 Lazada 店铺（30 秒内记住结果）。"""
    if time.time() - _en["t"] > 30:
        _en.update(t=time.time(), v=_conn()[1] is not None)
    return _en["v"]


def _done(sid, conn):
    from . import integrations
    if sid:
        integrations._store_creds(sid, conn)


# ---------------- 类目树 ----------------
def tree_path():
    """接口拉过的类目表（有就用它），没有返回 None。"""
    return TREE_FILE if os.path.exists(TREE_FILE) else None


def refresh_tree(force=False):
    """从接口拉类目树写成 TSV（id \\t 标记 \\t 泰文路径，只写最末级）。返回类目数；没接口返回 0。"""
    if not force and tree_path() and time.time() - os.path.getmtime(TREE_FILE) < TREE_TTL:
        return 0
    sid, conn = _conn()
    if not conn:
        return 0
    try:
        data = conn.category_tree()
    finally:
        _done(sid, conn)
    rows = []

    def walk(nodes, path):
        for n in nodes or []:
            p = path + [str(n.get("name") or "").strip()]
            if n.get("leaf") or not n.get("children"):
                rows.append(f"{n.get('category_id')}\t{'' if n.get('var', True) else 'D'}\t{' > '.join(x for x in p if x)}")
            else:
                walk(n.get("children"), p)
    walk(data, [])
    if len(rows) < 100:                     # 拉回来的不像完整类目树：不覆盖
        return 0
    os.makedirs(DIR, exist_ok=True)
    with open(TREE_FILE + ".tmp", "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    os.replace(TREE_FILE + ".tmp", TREE_FILE)
    from . import categories
    categories.reset_tree()
    return len(rows)


# ---------------- 类目属性 ----------------
def _attr_file(cat_id):
    return os.path.join(DIR, "attrs", f"{int(cat_id)}.json")


def attrs(cat_id, refresh=False):
    """类目属性（接口原样）。缓存 7 天；过期了拉不到就继续用旧的；从没拉过又拉不到返回 None。"""
    try:
        cid = int(str(cat_id).strip())
    except (TypeError, ValueError):
        return None
    path = _attr_file(cid)
    old = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError):
            old = None
        if old is not None and not refresh and time.time() - os.path.getmtime(path) < ATTR_TTL:
            return old
    if time.time() - _fail.get(cid, 0) < 600:
        return old
    with _lock:
        sid, conn = _conn()
        if not conn:
            return old
        try:
            data = conn.category_attributes(cid)
        except Exception:  # noqa: BLE001  接口出错：有旧的用旧的
            _fail[cid] = time.time()
            return old
        finally:
            _done(sid, conn)
    if not isinstance(data, list) or not data:
        _fail[cid] = time.time()
        return old
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(path + ".tmp", path)
    _mem.pop("k:" + str(cid), None)
    return data


def _mandatory(a):
    return str(a.get("is_mandatory")) in ("1", "true", "True")


def as_sheet(cat_id, data=None):
    """接口属性 → 和模板解析结果（lazada_template.parse 的一个工作表）一样结构的字段表（按文件修改时间记住）。"""
    if data is None:
        data = attrs(cat_id)
        if not data:
            return None
        try:
            key = (str(cat_id), os.path.getmtime(_attr_file(cat_id)))
        except (OSError, ValueError, TypeError):
            key = None
        if key and _mem.get("k:" + key[0], (None,))[0] == key[1]:
            return _mem["k:" + key[0]][1]
        out = as_sheet(cat_id, data)
        if key:
            _mem["k:" + key[0]] = (key[1], out)
        return out
    fields = []
    for a in data:
        name = str(a.get("name") or "")
        if not name or name in SKIP:
            continue
        aid = str(a.get("id") or "")
        opts = [o for o in (a.get("options") or []) if str(o.get("name") or "").strip()]
        sale = str(a.get("is_sale_prop")) == "1"
        if name in FIXED:
            key, kind = FIXED[name]
        elif name == "brand" or name == "brand_id":
            key, kind = f"catProperty.p-{aid or '20000'}", "brandProp"
        elif sale:
            key, kind = f"saleProp.p-{aid}", "colorFamily" if name == "color_family" else ""
        elif str(a.get("attribute_type") or "") == "sku":
            continue                        # 其它 SKU 级的（价格、库存、包裹……）由产品资料填
        else:
            key, kind = f"catProperty.p-{aid}", ""
        if not aid and key.endswith("p-"):
            continue
        fields.append({
            "col": len(fields) + 1, "letter": "", "key": key, "label": a.get("label") or name, "required": _mandatory(a),
            "kind": kind, "hidden": False, "readonly": False,
            "multi": str(a.get("input_type") or "") in ("multiSelect", "multiEnumInput"),
            "options": [str(o.get("name")).strip() for o in opts],
            "option_ids": [str(o.get("id")) for o in opts] if all(str(o.get("id") or "") not in ("", "0") for o in opts) else [],
            "tip": "", "api_name": name, "input_type": a.get("input_type") or "",
        })
    return {"sheet": f"api_{cat_id}", "cat_id": str(cat_id), "fields": fields, "existing_rows": 0}


def id_of(cat_id):
    return f"api|{int(cat_id)}"


def get(cat_id_str):
    """"api|<类目ID>" → 和 categories.get 一样的类目信息；拉不到返回 None。"""
    if not str(cat_id_str or "").startswith("api|"):
        return None
    cid = str(cat_id_str).split("|", 1)[1]
    s = as_sheet(cid)
    if not s:
        return None
    from . import categories
    return {**s, "template": "", "path": "", "id": id_of(cid), "name": categories.display_name(cid), "source": "api"}


def warm(cat_ids):
    """后台把这些类目的属性先拉好（批量 AI 补齐 / 推送前）。"""
    for c in cat_ids:
        try:
            attrs(c)
        except Exception:  # noqa: BLE001
            pass


LICENSE_WORDS = ("tisi", "licen", "มอก", "certificate", "qualification")


def needs_license(cat_id):
    """接口属性里有必填的许可证 / TISI 一类的项 → 要认证（只看已经拉过的缓存，不为这个去联网）。"""
    try:
        path = _attr_file(cat_id)
    except (TypeError, ValueError):
        return False
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    for a in data or []:
        txt = f"{a.get('name') or ''} {a.get('label') or ''}".lower()
        if _mandatory(a) and any(w in txt for w in LICENSE_WORDS):
            return True
    return False


def suggest(product):
    """Lazada 自己按商品名 + 主图推荐的类目（v2.45.1）：[(类目ID, 路径)]。没接口 / 拉不到返回 []。
    主图要 Lazada 图片空间的网址：推送 / 在线商品记过的直接用，没有就把主图传一次。"""
    name = ((product.get("copy") or {}).get("title_th") or (product.get("copy") or {}).get("title_en") or product.get("name_zh") or "").strip()
    imgs = product.get("images") or []
    if not name or not imgs:
        return []
    sid, conn = _conn()
    if not conn:
        return []
    try:
        url = next((u for u in ((product.get("lazada_api") or {}).get("images") or {}).values() if u), "")
        if not url:
            from . import imghost, store
            im = imgs[0]
            folder = "out" if im.get("processed") or str(im.get("file", "")).startswith("white_") else "raw"
            path = os.path.join(store.image_dir(product["id"], folder), im["file"])
            if not os.path.exists(path):
                return []
            data, ext = imghost.prepare(path, max_bytes=1_000_000, max_side=2000, min_side=330)
            url = conn.upload_image(data, f"main.{ext}")
        out = []
        for x in conn.category_suggestion(name, url):
            cid = str(x.get("categoryId") or x.get("category_id") or "").strip()
            if cid.isdigit():
                from . import categories
                out.append((cid, categories.path_of(cid) or str(x.get("categoryPath") or x.get("categoryName") or "")))
        return out
    except Exception:  # noqa: BLE001  推荐拉不到：AI 照旧按类目树选
        return []
    finally:
        _done(sid, conn)
