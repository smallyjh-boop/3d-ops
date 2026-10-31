"""ERP 产品直接推到 Lazada（v2.41.2，用店铺对接里授权好的 Lazada 店铺）。

和「生成 Lazada 导入表格」用同一套数据（lazada_template.build_rows：标题、详情、属性、价格、包裹、库存……），
只是不写表格，改成调 Lazada 开放接口：
  1. 图片先搬到 Lazada 图片空间（/image/migrate，搬过的记住不重复搬）；
  2. 表格的字段代码 → 接口的属性名：catProperty.p-20000 / saleProp.p-30097 的数字就是接口属性的 id，
     选项也按 id 对（模板的选项 id 和接口的一样），对不上的按名字；类目里没有的属性不发；
  3. 平台上还没有 → /product/create；有了（记着 item_id）→ /product/update；
  4. 推完：上架状态「平台审核中」、SKU 锁定、库存记为已同步。
库存：sync_stock() 把「库存待同步」里推送过的 SKU 用 /product/price_quantity/update 改掉；设置里开了就定时自动跑。

产品里存：p["lazada_api"] = {"item_id", "skus": {SellerSku: sku_id}, "images": {原网址: Lazada 网址}, "at", "error"}
对外：shop() push(pids, user) payload(p, ...) sync_stock(user, how) start()
"""
import json
import os
import threading
import time

from core import categories, connectors, imghost, integrations, lazada_template, pricing, store
from core.config import load_config

# 表格的固定字段 → 接口属性名（类目属性表里有才发）
FIXED = {"title.th_TH": "name", "description": "description", "packageContent": "package_content",
         "warrantyType": "warranty_type", "warrantyPeriod": "warranty", "warrantyPolicy": "product_warranty",
         "radioDangerousGoods": "Hazmat", "marketImages.1:1": "promotion_whitebkg_image"}
SKU_FIXED = {"sku.package_weight": "package_weight", "sku.package_length": "package_length",
             "sku.package_width": "package_width", "sku.package_height": "package_height"}
ALWAYS = ("name", "description")          # 所有类目都有的
STOCK_BATCH = 20
STATUS_EVERY = 1800


class PushError(Exception):
    pass


def shop():
    """(店铺 id, 连接器)：店铺对接里启用的 Lazada 店铺（有好几个时用第一个）。"""
    from core import db
    r = db.conn().execute("SELECT id FROM shops WHERE platform='lazada' AND enabled=1 ORDER BY id").fetchone()
    if not r:
        raise PushError("还没有启用的 Lazada 店铺（设置 → AI 与对接 → 店铺对接，授权后勾「启用自动同步」）")
    s = integrations.get_shop_raw(r["id"])
    conn = connectors.make("lazada", s["creds"])
    try:
        conn.check()
    except connectors.NotReady as e:
        raise PushError(f"Lazada 店铺还没授权好：{e}") from e
    return r["id"], conn


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _opt_out(o):
    """选项要发的值：Lazada 校验认英文选项名（en_name），没有才用 name（v2.43.2：发泰文「ไม่」被拒）。"""
    return (str(o.get("en_name") or "").strip() or str(o.get("name") or "").strip())


def _value(field, val, attr):
    """表格里的值（选项文字）→ 接口要的值：按选项 id 对，再按名字（泰文 / 英文）对，对上了发英文选项名；都对不上原样发。"""
    if val in (None, ""):
        return None
    opts = attr.get("options") or []
    if not opts or not isinstance(val, str):
        return val
    by_id = {str(o.get("id")): o for o in opts if str(o.get("id") or "") not in ("", "0")}
    by_name = {}
    for o in opts:
        for k in (o.get("name"), o.get("en_name")):
            if str(k or "").strip():
                by_name.setdefault(str(k).strip().lower(), o)
    out = []
    for part in ([x.strip() for x in val.split(",")] if attr.get("input_type") in ("multiSelect", "multiEnumInput") else [val.strip()]):
        oid = None
        if field and field.get("option_ids") and part in field.get("options", []):
            oid = field["option_ids"][field["options"].index(part)]
        o = by_id.get(str(oid)) or by_name.get(part.lower())
        out.append(_opt_out(o) if o else part)
    return ",".join(out)


def _html(text):
    """详情：Lazada 接口按网页显示，纯文字的换行会丢 → 每行一段。已经是网页的原样发。"""
    text = str(text or "").strip()
    if not text or "<" in text:
        return text
    import html
    return "".join(f"<p>{html.escape(x)}</p>" for x in text.split("\n") if x.strip())


def _s(v):
    """Lazada 的例子里数字都写成字符串：35 → "35"，0.5 → "0.5"。"""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            raise PushError(f"数值不对：{v}")
        return str(int(f)) if f == int(f) else f"{round(f, 2):g}"
    return str(v)


def _img_path(pid, im):
    folder = "out" if im.get("processed") or str(im.get("file", "")).startswith("white_") else "raw"
    return os.path.join(store.image_dir(pid, folder), im["file"])


def _lz_img(conn, state, pid, im):
    """一张图片 → Lazada 图片空间的网址（传过的记住）。v2.43.1：本地有文件就直接传给 Lazada（不用先上传图床），
    没有本地文件才用图床网址搬（/image/migrate）。"""
    if not im:
        return None
    cache = state.setdefault("images", {})
    path = _img_path(pid, im) if im.get("file") else ""
    if path and os.path.exists(path):
        key = f"{im['file']}|{int(os.path.getmtime(path))}"
        if key not in cache:
            data, ext = imghost.prepare(path, max_bytes=1_000_000, max_side=2000, min_side=330)     # Lazada：1MB 以内、边长 ≥ 330
            cache[key] = conn.upload_image(data, f"{os.path.splitext(im['file'])[0]}.{ext}")
        return cache[key]
    url = im.get("url")
    if url:
        if url not in cache:
            cache[url] = conn.migrate_image(url)
        return cache[url]
    return None


def desc_images(p):
    """详情里放的图片（v2.44.1）：编辑页勾选的（desc_images = 图片 raw 名单）；没选过就自动取前 3 张。至少一张（主图）。"""
    imgs = p.get("images") or []
    by_raw = {im.get("raw"): im for im in imgs}
    chosen = [by_raw[r] for r in (p.get("desc_images") or []) if r in by_raw]
    return chosen or imgs[:3]


LZ_HOSTS = ("slatic.net", "lazcdn.com", "lazada.")


def desc_img_urls(html_, p, conn, state):
    """详情里的 <img src>：本系统的产品图（/files/<产品>/raw|out/<文件>）传到 Lazada；外面的网址用 /image/migrate 搬；
    已经是 Lazada 图片空间的不动；换不了的图片去掉（Lazada 不收外站图片）。"""
    import re
    import urllib.parse
    by_file = {im.get("file"): im for im in p.get("images") or [] if im.get("file")}

    def one(m):
        src = m.group(2)
        if any(h in src for h in LZ_HOSTS):
            return m.group(0)
        u = None
        loc = re.match(r"^(?:https?://[^/]+)?/files/([^/]+)/(?:raw|out)/([^?#]+)", src)
        if loc:
            im = by_file.get(urllib.parse.unquote(loc.group(2)))
            if im:
                u = _lz_img(conn, state, p["id"], im)
        elif src.startswith(("http://", "https://")):
            cache = state.setdefault("images", {})
            try:
                if src not in cache:
                    cache[src] = conn.migrate_image(src)
                u = cache[src]
            except Exception:  # noqa: BLE001  搬不了：这张图不放
                u = None
        if not u:
            return ""
        return m.group(1) + u + m.group(3)

    return re.sub(r'(<img\b[^>]*?\bsrc=["\'])([^"\']+)(["\'][^>]*>)', one, html_, flags=re.I)


def _cut(text, n, what):
    t = str(text or "").strip()
    return t if len(t) <= n else t[:n].rstrip()


def payload(p, rows, cat, attrs, conn, state):
    """build_rows 出来的这个产品的几行（一行一个 SKU）→ /product/create 的 Product（按 Lazada 文档「Create a product」
    和「变体」说明：值都是字符串；变体写在 variation.variation1 / variation2（最多 2 个，名字 ≤ 15 字、选项 ≤ 20 字），
    SKU 的 saleProp 用变体名；颜色能对上 Lazada 标准颜色（color_family）就用标准的，对不上用自定义）。"""
    by_id = {str(a.get("id")): a for a in attrs}
    by_name = {a.get("name"): a for a in attrs}
    fields = {f["key"]: f for f in (cat or {}).get("fields") or []}
    sale_names = {a.get("name") for a in attrs if str(a.get("is_sale_prop")) == "1"}

    def api_attr(key):
        if key.startswith(("catProperty.p-", "saleProp.p-")):
            return by_id.get(key.split("p-", 1)[1])
        if key in SKU_FIXED:                    # 包裹尺寸重量：每个类目都要
            return {"name": SKU_FIXED[key], "attribute_type": "sku"}
        name = FIXED.get(key)
        if name in ALWAYS:
            return by_name.get(name) or {"name": name, "attribute_type": "normal"}
        return by_name.get(name)

    first = rows[0][2]
    product_attrs, sku_attr_keys, sale_keys = {}, [], {}
    for key, val in first.items():
        if key.startswith(("sku.", "mainImage.", "customSaleProp.", "__")) and key not in SKU_FIXED:
            continue
        a = api_attr(key)
        if not a:
            continue
        if a.get("name") in sale_names:          # 标准变体属性（例如 color_family）：放进变体，不当普通属性
            sale_keys[a["name"]] = (key, a)
            continue
        if a.get("attribute_type") == "sku" or key in SKU_FIXED:
            sku_attr_keys.append((key, a))
            continue
        if key == "marketImages.1:1":
            v = _lz_img(conn, state, p["id"], p.get("white_bg"))
        elif key == "description":
            v = _html(val)
            if "<img" in v.lower():             # v2.46：编辑器里自己放了图片 → 图片换成 Lazada 的网址，不再自动接图
                v = desc_img_urls(v, p, conn, state)
            else:
                pics = [u for u in (_lz_img(conn, state, p["id"], im) for im in desc_images(p)) if u]
                if pics:                        # 详情后面接产品图（Lazada 详情只认它自己图片空间的网址）
                    v += "".join(f'<p><img src="{u}" style="max-width:100%"/></p>' for u in pics)
        elif key == "packageContent":
            v = _html(val)
        else:
            v = _value(fields.get(key), val, a)
        if v not in (None, ""):
            product_attrs[a["name"]] = _s(v)
    images = [u for u in (_lz_img(conn, state, p["id"], im) for im in (p.get("images") or [])[:8]) if u]
    if not images:
        raise PushError("没有图片（先上传图片或生成商品图）")
    out = {"PrimaryCategory": str(cat["cat_id"]), "Images": {"Image": images}, "Attributes": product_attrs}
    if state.get("item_id"):
        out["ItemId"] = str(state["item_id"])

    # SKU 的图片（每个颜色的图）
    by_raw = {im.get("raw"): im for im in p.get("images") or []}
    sku_img = {}
    for _p, idx, vals in rows:
        v = (p.get("variants") or [])[idx] if idx < len(p.get("variants") or []) else {}
        if v.get("image") and by_raw.get(v["image"]):
            sku_img[vals["sku.SellerSku"]] = _lz_img(conn, state, p["id"], by_raw[v["image"]])

    # 变体
    opt = lambda vals, n: _cut(vals.get(f"customSaleProp.Custom_Opt_Name_{n}"), 20, "选项")
    variation, sale_of = {}, {r[2]["sku.SellerSku"]: {} for r in rows}
    if len(rows) > 1:
        dims = []                              # [(变体名, customize, {SellerSku: 选项})]
        names = [first.get(f"customSaleProp.Custom_Variation_Name_{n}") for n in (1, 2)]
        if names[0]:
            col = {r[2]["sku.SellerSku"]: opt(r[2], 1) for r in rows}
            fam = None
            if "color_family" in sale_keys:     # 颜色能一一对上 Lazada 标准颜色：用标准的（搜索筛选能用）
                key, a = sale_keys["color_family"]
                fam = {r[2]["sku.SellerSku"]: _value(fields.get(key), r[2].get(key), a) for r in rows}
                pairs = {(col[s], fam[s]) for s in col}
                if not all(fam.values()) or len({c for c, _f in pairs}) != len({f for _c, f in pairs}) or len(pairs) != len({c for c, _f in pairs}):
                    fam = None
            dims.append(("color_family", False, fam) if fam else (_cut(names[0], 15, "变体名"), True, col))
        if names[1]:
            dims.append((_cut(names[1], 15, "变体名"), True, {r[2]["sku.SellerSku"]: opt(r[2], 2) for r in rows}))
        all_img = bool(sku_img) and all(sku_img.get(r[2]["sku.SellerSku"]) for r in rows)
        for n, (name, custom, by_sku) in enumerate(dims[:2], 1):
            options = list(dict.fromkeys(v for v in by_sku.values() if v))
            if len(options) > 50:
                raise PushError(f"变体「{name}」的选项超过 50 个（Lazada 上限）")
            variation[f"variation{n}"] = {"name": name, "hasImage": n == 1 and all_img, "customize": custom,
                                          "options": {"option": options}}
            for sku, v in by_sku.items():
                if v:
                    sale_of[sku][name] = v
        combos = [tuple(sorted(sale_of[r[2]["sku.SellerSku"]].items())) for r in rows]
        if len(set(combos)) != len(combos):
            raise PushError("有两个 SKU 的颜色 / 规格完全一样（选项名截到 20 个字后重复了），Lazada 分不出来，请改选项名")
        if variation:
            out["variation"] = variation
    has_img = bool(variation.get("variation1", {}).get("hasImage"))

    skus = []
    for _p, _idx, vals in rows:
        sku = vals["sku.SellerSku"]
        sk = {"SellerSku": sku, "quantity": _s(int(vals.get("__stock__") or 0)), "price": _s(vals["sku.price"])}
        sid = (state.get("skus") or {}).get(sku)
        if sid:
            sk["SkuId"] = str(sid)
        for key, a in sku_attr_keys:
            v = vals.get(key)
            v = _num(v) if key in SKU_FIXED else _value(fields.get(key), v, a)
            if v not in (None, ""):
                sk[a["name"] if key not in SKU_FIXED else SKU_FIXED[key]] = _s(v)
        if vals.get("sku.special_price.SpecialPrice"):
            sk.update(special_price=_s(vals["sku.special_price.SpecialPrice"]), special_from_date=vals["sku.special_price.Start"],
                      special_to_date=vals["sku.special_price.End"])
        if sale_of.get(sku):
            sk["saleProp"] = sale_of[sku]
        if has_img or (len(rows) == 1 and sku_img.get(sku)):
            sk["Images"] = {"Image": [sku_img[sku]]}
        skus.append(sk)
    out["Skus"] = {"Sku": skus}
    return out


def _check(cfg, p, cat):
    lazada_template.ensure_brand(p, cat, cfg)
    return lazada_template.check_product(p, pricing.price_product(cfg, p), cat, cfg)


def push(pids, user="", force=False):
    """推一批产品。返回 {ok:[{id, item_id, created}], failed:[{id, error}], errors, warnings}（errors 有就没推）。"""
    from core import listing, stockcalc
    cfg = load_config()
    sid, conn = shop()
    prods = [store.load(i) for i in pids]
    errors, warnings = [], []
    for p in prods:
        e, w = _check(cfg, p, categories.get((p.get("category") or {}).get("id")))
        name = f"{p['id']} {p.get('name_zh', '')}"
        errors += [f"{name}：{x}" for x in e]
        warnings += [f"{name}：{x}" for x in w]
    if errors and not force:
        return {"ok": [], "failed": [], "errors": errors, "warnings": warnings}
    done, failed, attr_cache = [], [], {}
    try:
        from core import bgjobs
        for i, p in enumerate(prods):
            bgjobs.note(stage=f"{i + 1}/{len(prods)}")          # 任务中心显示进度（v2.43）
            state = dict(p.get("lazada_api") or {})
            try:
                cat = categories.get((p.get("category") or {}).get("id"))
                if not cat or not cat.get("cat_id"):
                    raise PushError("还没有选择 Lazada 类目")
                if cat["cat_id"] not in attr_cache:          # v2.45：和编辑页、检查用同一份缓存（core/lazada_cats）
                    from core import lazada_cats
                    attr_cache[cat["cat_id"]] = lazada_cats.attrs(cat["cat_id"]) or conn.category_attributes(cat["cat_id"])
                rows = lazada_template.build_rows([p], {p["id"]: pricing.price_product(cfg, p)}, cfg, cat)
                body = payload(p, rows, cat, attr_cache[cat["cat_id"]], conn, state)
                state["last_payload"] = json.dumps(body, ensure_ascii=False)[:30000]      # 排查用：最后一次发出去的内容
                created = not state.get("item_id")
                r = conn.create_product(body) if created else conn.update_product(body)
                if r.get("item_id"):
                    state["item_id"] = r["item_id"]
                for x in r.get("sku_list") or []:
                    if x.get("seller_sku") and x.get("sku_id"):
                        state.setdefault("skus", {})[x["seller_sku"]] = x["sku_id"]
                state.update(at=time.time(), error="", by=user)
                p["lazada_api"] = state
                if not p.get("exported_at"):
                    p["exported_at"] = int(time.time())     # SKU 锁定（和导出表格一样）
                p.pop("exported_first", None)
                listing._set(p, "lazada", "uploaded", note="接口推送" if created else "接口更新", user=user)
                store.save(p)
                stockcalc.mark_synced([{"sku": r_[2]["sku.SellerSku"], "stock": r_[2].get("__stock__"), "product_id": p["id"]}
                                       for r_ in rows], user, "api", "lazada")
                done.append({"id": p["id"], "item_id": state.get("item_id"), "created": created})
            except Exception as e:  # noqa: BLE001  一个失败不影响别的
                state.update(error=str(e)[:500], at=time.time())
                p["lazada_api"] = state            # 搬过的图片记住，下次不重复搬
                store.save(p)
                failed.append({"id": p["id"], "error": str(e)})
    finally:
        integrations._store_creds(sid, conn)
    return {"ok": done, "failed": failed, "errors": errors, "warnings": warnings}


def sync_stock(user="", how="api"):
    """「库存待同步」里推送过（有 item_id 和 sku_id）的 SKU → Lazada。返回 {synced, skipped, failed}。"""
    from core import stockcalc
    items = stockcalc.pending("lazada")
    if not items:
        return {"synced": 0, "skipped": 0, "failed": []}
    sid, conn = shop()
    states = {}
    todo, skipped = [], 0
    for it in items:
        st = states.get(it["product_id"])
        if st is None:
            try:
                st = states[it["product_id"]] = store.load(it["product_id"]).get("lazada_api") or {}
            except FileNotFoundError:
                st = states[it["product_id"]] = {}
        sku_id = (st.get("skus") or {}).get(it["sku"])
        if not st.get("item_id") or not sku_id:
            skipped += 1                       # 用表格上传的：Lazada 上的编号不知道，还是人工改
            continue
        todo.append((it, {"ItemId": str(st["item_id"]), "SkuId": str(sku_id), "SellerSku": it["sku"], "Quantity": int(it["stock"])}))
    n, failed = 0, []
    try:
        for i in range(0, len(todo), STOCK_BATCH):
            part = todo[i:i + STOCK_BATCH]
            try:
                conn.update_price_quantity([x[1] for x in part])
                n += stockcalc.mark_synced([x[0] for x in part], user, how, "lazada")
            except Exception as e:  # noqa: BLE001
                failed.append(f"{', '.join(x[0]['sku'] for x in part)}：{e}")
    finally:
        integrations._store_creds(sid, conn)
    return {"synced": n, "skipped": skipped, "failed": failed}


# Lazada 商品状态 → 上架状态（v2.43：接口推送过的产品自动同步审核结果，不用手点）
LZ_STATUS = {"active": "live", "inactive": "inactive", "pending qc": "uploaded", "pending": "uploaded", "qc pending": "uploaded",
             "suspended": "rejected", "rejected": "rejected", "qc rejected": "rejected", "qc failed": "rejected",
             "deleted": "inactive", "deactivated": "inactive"}


def _reason(d):
    """审核不通过的原因：接口在不同地方给（suspendedSkus、reject_reason、qc_reason……），有就拼起来。"""
    out = []
    for k in ("reject_reason", "rejectReason", "qc_reason", "reason"):
        if d.get(k):
            out.append(str(d[k]))
    for s in d.get("suspendedSkus") or d.get("suspended_skus") or []:
        r = s.get("rejectReason") or s.get("reject_reason") or s.get("reason") if isinstance(s, dict) else None
        if r:
            out.append(str(r))
    return "；".join(dict.fromkeys(out))[:300]


def sync_status(user="系统", pids=None):
    """接口推送过的产品：向 Lazada 查商品状态，改上架状态（审核中 → 已上线 / 审核不通过 / 已下架）。
    返回 {checked, changed:[{id, from, to, note}], failed:[…]}。"""
    from core import listing
    sid, conn = shop()
    checked, changed, failed = 0, [], []
    try:
        for it in store.list_products():
            pid = it["id"]
            if pids and pid not in pids:
                continue
            p = store.load(pid)
            st = p.get("lazada_api") or {}
            if not st.get("item_id"):
                continue
            checked += 1
            try:
                d = conn.get_item(st["item_id"])
            except Exception as e:  # noqa: BLE001
                failed.append(f"{pid}：{e}")
                continue
            raw = str(d.get("status") or d.get("Status") or "").strip()
            new = LZ_STATUS.get(raw.lower())
            st["platform_status"], st["status_at"] = raw, time.time()
            cur = listing.status_of(p, "lazada").get("status")
            note = _reason(d) if new == "rejected" else None
            if new and (new != cur or (note and note != (listing.status_of(p, "lazada").get("note") or ""))):
                if not (cur == "update" and new == "live"):          # 有修改待同步的：上线了也保持「待同步」提醒
                    listing._set(p, "lazada", new, note=note, user=user)
                    changed.append({"id": pid, "from": cur, "to": new, "note": note or ""})
            p["lazada_api"] = st
            store.save(p)
    finally:
        integrations._store_creds(sid, conn)
    return {"checked": checked, "changed": changed, "failed": failed}


_started = False


def _loop():
    from core import diag
    last = last_status = 0
    while True:
        time.sleep(60)
        try:                                                    # v2.45：类目树每周从接口刷新一次（没到时间什么都不做）
            from core import lazada_cats
            lazada_cats.refresh_tree()
        except Exception as e:  # noqa: BLE001
            diag.log.warning("Lazada 类目树刷新失败：%s", e)
        if time.time() - last_status >= STATUS_EVERY:          # v2.43：每 30 分钟同步一次审核结果
            last_status = time.time()                           # v2.44：整店拉在线商品（顺带对上 ERP、更新上架状态）
            try:
                from . import online
                online.init()
                online.sync()
            except PushError:
                pass
            except Exception as e:  # noqa: BLE001
                diag.log.warning("Lazada 审核状态同步失败：%s", e)
        try:
            mins = int(load_config().get("lazada_stock_sync_min") or 0)
        except (TypeError, ValueError):
            mins = 0
        if mins <= 0 or time.time() - last < mins * 60:
            continue
        last = time.time()
        try:
            r = sync_stock("系统", "auto")
            if r["failed"]:
                diag.log.warning("Lazada 库存自动同步有失败：%s", r["failed"][:3])
        except PushError:
            pass                                   # 没有 Lazada 店铺：不用同步
        except Exception as e:  # noqa: BLE001
            diag.log.warning("Lazada 库存自动同步失败：%s", e)


def start():
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="lazada-stock").start()
