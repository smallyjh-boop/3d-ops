"""类目匹配 + 属性自动填写。

属性状态（界面颜色）：
  auto    规则或你以前在这个类目选过的值（绿色）
  ai      AI 根据产品信息确定的值（正常）
  check   AI 填了但不确定，需要人工确认（红色）
  missing 必填但没有值（红色）
  empty   选填、没把握就留空（灰色，不影响上传）
  manual  你手动改过的值（蓝色，会被记住作为这个类目的默认值）
"""
import json
import re

from . import ai_copy, categories, lazada_template

# 固定规则按选项 ID 设定（中/英/泰文模板通用）
RULES = {
    "radioDangerousGoods": "103256",   # None / ไม่ใช่สินค้าอันตราย
    "deliveryStandard": "104189",      # Yes
    "warrantyType": "141503",          # No Warranty
    "catProperty.p-40387": "74369",    # Place of Origin = Thailand
}
RED = ("check", "missing")
ZH_LABELS = {
    "catProperty.p-20000": "品牌", "warrantyType": "保修类型", "warrantyPeriod": "保修期",
    "warrantyPolicy": "保修条款", "radioDangerousGoods": "危险品", "deliveryStandard": "标准配送",
    "catProperty.p-40387": "原产地", "productQualifications.TH_TISI&licenseCode": "TISI 许可证号",
    "productQualifications.TH_TISI_LICENCE_URL&licenseCode": "TISI 许可证号(链接类)",
}
ZH_RULE_VALUES = {"radioDangerousGoods": "非危险品", "deliveryStandard": "是",
                  "warrantyType": "无保修", "catProperty.p-40387": "泰国"}


def _product_brief(product):
    c = product.get("copy", {})
    opts = sorted({(v.get("opt1_zh") or "").strip() for v in product.get("variants", [])} - {""})
    return (f"名称: {product.get('name_zh', '')}\n用途/卖点: {product.get('features_zh', '')}\n"
            f"关键词: {product.get('keywords', '')}\n材料: {product.get('material', '')}\n"
            f"尺寸: {product.get('size_text', '')}\n颜色/选项: {'、'.join(opts) or '无'}\n"
            f"泰文标题: {c.get('title_th', '')}\n英文标题: {c.get('title_en', '')}")


# ---------------- 类目匹配 ----------------
CAT_SYSTEM = ("You are a Lazada Thailand category expert. Choose the most specific correct leaf category "
              "for a product. Wrong categories get listings penalised, so be strict. Classify by what the product "
              "physically IS (e.g. a plastic pipe fitting / connector is plumbing hardware or an appliance spare part), "
              "never by a related consumable (cleaning agents, chemicals) or by the production method. Output only JSON.")


BIG_LIBRARY = 150     # 有模板的类目超过这么多（v2.25 下载了全部类目模板）：先按关键词找候选，再让 AI 从候选里选


def _by_top_level(cfg, product, kws):
    """关键词在类目树里一个都没搜到时（v2.45.1）：AI 先从一级类目里选方向，再给出那个方向下面的最末级类目当候选。"""
    t = categories.tree()
    tops = sorted({path.split(" > ")[0] for path, dis in t.values() if path and not dis})
    if not tops:
        return []
    user = f"""Product:
{_product_brief(product)}

Lazada Thailand top-level categories:
{chr(10).join("- " + x for x in tops)}

Return JSON {{"top": ["1 to 3 top-level names exactly as listed where this product can be listed"]}}"""
    try:
        picked = [x for x in ai_copy.extract_json(ai_copy.call(cfg, CAT_SYSTEM, user)).get("top") or [] if x in tops]
    except ai_copy.AIError:
        return []
    leaves = [(cid, path) for cid, (path, dis) in t.items() if not dis and path.split(" > ")[0] in picked]
    words = [k.lower() for k in kws if k]
    leaves.sort(key=lambda x: -sum(1 for w in words if w in x[1].lower()))
    return leaves[:200]


def _options(cands, first="", n=5):
    """给页面的推荐类目（都能上架、不要许可证）：[{id, cat_id, path}]，AI 选的排第一。"""
    out, seen = [], set()
    for cid, path in ([(first, categories.path_of(first))] if first else []) + list(cands):
        if not cid or cid in seen or categories.needs_license(cid):
            continue
        hit = categories.by_cat_id(cid)
        if not hit:
            continue
        seen.add(cid)
        out.append({"id": hit["id"], "cat_id": cid, "path": path or hit.get("path") or hit.get("name", "")})
        if len(out) >= n:
            break
    return out


def _match_big(cfg, product, lib):
    """全部类目都能选时：Lazada 自己的类目推荐 + AI 关键词在类目树里找候选 → AI 从候选里选；
    关键词搜不到就按一级类目缩小范围。无论如何都给出几个能放的推荐类目（options）。"""
    from . import lazada_cats
    sugg = lazada_cats.suggest(product)                     # v2.45.1：Lazada 按商品名 + 图片推荐的类目
    user = f"""Product:
{_product_brief(product)}

Return JSON {{"search_keywords_th": ["8-12 short Thai words to find this product's leaf category in the Lazada Thailand
category tree: product-type words AND category-level words as Lazada names them (e.g. ของตกแต่งบ้าน, ของเล่น, ที่วาง,
อุปกรณ์จัดเก็บ, ข้อต่อ, ท่อ, อะไหล่, เครื่องมือ, อุปกรณ์วัด)"], "ideal_path_th": "<the Thai category path you would expect>"}}"""
    d1 = ai_copy.extract_json(ai_copy.call(cfg, CAT_SYSTEM, user))
    kws = list(d1.get("search_keywords_th") or [])
    kws += [x.strip() for x in str(d1.get("ideal_path_th") or "").split(">") if x.strip()]
    cands = list(dict.fromkeys(sugg + categories.search_tree(kws, limit=80)))
    if not cands:
        cands = _by_top_level(cfg, product, kws)
    res = {"id": "", "confidence": 0, "reason": "", "reason_th": "", "suggest_id": "", "suggest_path": "", "suggest_path_zh": "",
           "status": "check", "options": []}
    if not cands:
        res["reason"] = "没找到合适的类目，请在上面搜索类目手动选择"
        return res
    # v2.45：要 TISI 等许可证的类目不给 AI 选（我们没有许可证）；全是这种才留着，选了也要人工确认
    lic = {cid for cid, _p in cands if categories.needs_license(cid)}
    if len(lic) < len(cands):
        cands = [(cid, path) for cid, path in cands if cid not in lic]
        lic = set()
    have = {c["cat_id"] for c in lib}
    from_lz = {cid for cid, _p in sugg}
    lst = "\n".join(f"- {cid} | {path}" + (" (Lazada suggests)" if cid in from_lz else "") +
                    ("" if cid in have else " (no template yet)") for cid, path in cands)
    user2 = f"""Product:
{_product_brief(product)}

Candidate Lazada Thailand leaf categories (id | Thai path):
{lst}

Pick the most specific leaf category that describes what the product physically is. Lazada's own suggestions are
marked; prefer one of them when it fits.
Categories that need a Thai TISI / industrial-standard licence were removed from this list (the seller has none):
if the product's natural category needs a licence, pick the closest category from this list where the product
can legitimately be listed (e.g. a decorative / ornament / accessory category instead of a regulated electrical or toy one).
Return JSON {{"cat_id": "<id exactly as listed>", "alternatives": ["up to 4 other ids from the list that would also be acceptable"],
 "confidence": <0..1>, "reason_zh": "<one sentence Chinese>", "reason_th": "<same in Thai>", "path_zh": "<the chosen path translated to Chinese>"}}"""
    d2 = ai_copy.extract_json(ai_copy.call(cfg, CAT_SYSTEM, user2))
    ids = dict(cands)
    cid = str(d2.get("cat_id") or "").strip()
    if cid not in ids:
        cid = ""
    alts = [(str(x), ids[str(x)]) for x in (d2.get("alternatives") or []) if str(x) in ids]
    res["options"] = _options(alts + sugg + cands, cid)
    try:
        conf = float(d2.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    res.update(reason=d2.get("reason_zh", ""), reason_th=d2.get("reason_th", ""))
    if not cid:
        return res
    hit = categories.by_cat_id(cid)
    if hit:
        res.update(id=hit["id"], confidence=round(conf, 2), status="ai" if conf >= 0.75 and cid not in lic else "check")
        if cid in lic:
            res["reason"] = (res["reason"] + "（注意：这个类目要 TISI 许可证，没有合适的替代类目，请人工确认）").strip()
    else:
        res.update(suggest_id=cid, suggest_path=categories.path_of(cid), suggest_path_zh=d2.get("path_zh", ""))
    return res


def match_category(cfg, product):
    lib = categories.library()
    if len(lib) > BIG_LIBRARY:
        return _match_big(cfg, product, lib)
    ok_lib = [c for c in lib if not (c.get("needs_license") or categories.needs_license(c.get("cat_id")))]   # v2.45：避开要许可证的类目
    lines = "\n".join(f"- id: {c['id']} | {c['path'] or c['name']}" for c in (ok_lib or lib)) or "(none yet)"
    user = f"""Product:
{_product_brief(product)}

Categories the seller has templates for (Lazada Thailand, Thai names):
{lines}

Return JSON:
{{
 "best_id": "<id from the list that truly fits this product, or empty string if none fits well>",
 "confidence": <0..1, how sure that best_id is the correct Lazada leaf category>,
 "reason_zh": "<one sentence in Chinese>",
 "reason_th": "<same sentence in Thai>",
 "search_keywords_th": ["5-10 short Thai words to find the ideal leaf category in the full Lazada TH category tree: product-type words AND category-level words (e.g. ข้อต่อ, ท่อ, ประปา, อะไหล่, ที่วาง, ตกแต่ง, ของเล่น)"]
}}
Categories that require a Thai TISI licence are not offered (the seller has none): if the natural category needs one,
choose the closest listed category where the product can legitimately be sold."""
    data = ai_copy.extract_json(ai_copy.call(cfg, CAT_SYSTEM, user))
    ids = {c["id"] for c in lib}
    best = data.get("best_id") or ""
    if best not in ids:
        best = ""
    try:
        conf = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    result = {
        "id": best,
        "confidence": round(conf, 2) if best else 0,
        "reason": data.get("reason_zh", ""),
        "reason_th": data.get("reason_th", ""),
        "suggest_id": "", "suggest_path": "", "suggest_path_zh": "",
        "status": "ai" if best and conf >= 0.75 else "check",
    }
    # 第二步：没有合适的已下载类目时，从完整类目树里挑理想类目
    if not best or conf < 0.75:
        cands = categories.search_tree(data.get("search_keywords_th") or [])
        cands = [x for x in cands if not categories.needs_license(x[0])] or cands      # v2.45：避开要许可证的
        if cands:
            lst = "\n".join(f"- {cid} | {path}" for cid, path in cands)
            have = "\n".join(f"- {c['cat_id']} | {c['path'] or c['name']} (template already downloaded)" for c in lib)
            user2 = f"""Product:
{_product_brief(product)}

Candidate Lazada Thailand leaf categories:
{lst}
{have}

Pick the category that best describes what the product physically is. If a candidate marked
"template already downloaded" fits about as well as the others, prefer it.
Return JSON {{"cat_id": "<best id from the list>", "path_zh": "<that path translated to Chinese>"}}"""
            try:
                d2 = ai_copy.extract_json(ai_copy.call(cfg, CAT_SYSTEM, user2))
                cid = str(d2.get("cat_id") or "")
                if cid in dict(cands) or any(c["cat_id"] == cid for c in lib):
                    result["suggest_id"] = cid
                    result["suggest_path"] = categories.path_of(cid)
                    result["suggest_path_zh"] = d2.get("path_zh", "")
                    # 理想类目其实已经有模板 → 直接用
                    hit = next((c for c in lib if c["cat_id"] == cid), None)
                    if hit:
                        result.update(id=hit["id"], status="ai", confidence=max(result["confidence"], 0.8))
            except ai_copy.AIError:
                pass
    return result


# ---------------- 属性填写 ----------------
ATTR_SYSTEM = ("You fill Lazada Thailand product attributes from seller data. Only state what the data "
               "supports. If an attribute has an option list you must pick an exact option string. "
               "Output only JSON.")


def _match_option(val, options):
    if not options:
        return val
    if val in options:
        return val
    low = {o.lower(): o for o in options}
    return low.get(str(val).strip().lower())


def fill(cfg, product, cat, use_ai=True):
    """返回 {字段代码: {value, status, note}}。保留你手动改过（manual）的值。"""
    fields = lazada_template.attribute_fields(cat)
    old = product.get("attributes") or {}
    mem = (cfg.get("category_memory") or {}).get(categories.memory_key(cat), {})
    legacy = (cfg.get("template_defaults") or {}).get(f"{cat['template']}|{cat['sheet']}", {})
    out, ask = {}, []
    for f in fields:
        k = f["key"]
        if old.get(k, {}).get("status") == "manual" and (f["kind"] != "brandProp" or str(old[k].get("value") or "").strip()):
            out[k] = old[k]
            continue
        val, status, note = "", "", ""
        if f["kind"] == "brandProp":       # 所有店铺都是无品牌
            val, status = (str(cfg.get("brand") or "").strip() or "No Brand"), "auto"
        elif k in mem and mem[k] not in (None, ""):
            val, status, note = mem[k], "auto", "你以前在这个类目选过"
        elif k in RULES and lazada_template.label_for_id(f, RULES[k]):
            val, status = lazada_template.label_for_id(f, RULES[k]), "auto"
            note = ZH_RULE_VALUES.get(k, "")
        elif k.startswith("productQualifications."):
            status = "missing" if f["required"] else "empty"
            note = "需要泰国 TISI 认证/许可证号，AI 不能代填。没有许可证请换其他类目" if f["required"] else ""
        elif k in legacy and legacy[k] not in (None, ""):
            val, status, note = legacy[k], "auto", "导出页记住的默认值"
        elif f["kind"] == "colorFamily":
            status = "auto" if f["required"] else "empty"
            note = "按每个 SKU 的颜色自动填写" if f["required"] else ""
        elif k in ("warrantyPeriod", "warrantyPolicy"):
            status = "empty"
        else:
            ask.append(f)
        out[k] = {"value": val, "status": status, "note": note}
    for f in fields:
        if f["kind"] == "colorFamily":
            out[f["key"]]["label_zh"] = "颜色系"
        elif f["key"] in ZH_LABELS:
            out[f["key"]]["label_zh"] = ZH_LABELS[f["key"]]

    pkg = None
    if use_ai and ask:
        spec = []
        for f in ask:
            item = {"key": f["key"], "label": f["label"], "required": f["required"]}
            if f["options"]:
                item["options"] = f["options"][:150]
            spec.append(item)
        user = f"""Seller data (3D printed product, produced in Thailand):
{_product_brief(product)}

Attributes to fill:
{json.dumps(spec, ensure_ascii=False)}

Return JSON:
{{
 "attributes": {{"<key>": {{"value": "<exact option or short text, empty if unknown>", "sure": true/false, "label_zh": "<attribute name in Chinese>", "value_zh": "<chosen value in Chinese>", "note_zh": "<short reason when not sure>", "note_th": "<same reason in Thai>"}}}},
 "package_cm": {{"length": n, "width": n, "height": n, "sure": true/false}}
}}
Guidance: Place of Origin = Thailand (made locally). For brand/character/licence/IP-type attributes
(anime, franchise, team names...) choose the "other / none / generic" option (e.g. อื่นๆ, คนอื่น, Others)
— never a real franchise — unless the seller data says they hold a licence. Battery needed = no
(unless the product has electronics). PLA/PETG/resin are plastics: pick the closest material
option (e.g. Plastic, PLA if listed). Leave free-text manufacturer fields empty unless provided.
package_cm = product size plus about 2-3 cm padding per side, from the size field."""
        try:
            data = ai_copy.extract_json(ai_copy.call(cfg, ATTR_SYSTEM, user))
        except ai_copy.AIError as e:
            data = {"attributes": {}, "_error": str(e)}
        got = data.get("attributes") or {}
        for f in ask:
            k = f["key"]
            g = got.get(k) or {}
            raw = str(g.get("value") or "").strip()
            val = _match_option(raw, f["options"]) if raw else ""
            if raw and val is None:
                out[k] = {"value": "", "status": "check", "note": f"AI 给的「{raw}」不在可选项里，请手动选"}
            elif val:
                sure = bool(g.get("sure"))
                note = g.get("note_zh", "") if not sure else ""
                vz = g.get("value_zh", "")
                out[k] = {"value": val, "status": "ai" if sure else "check",
                          "note": (f"＝{vz}" if vz else "") + (f"；{note}" if note else ""),
                          "note_th": "" if sure else g.get("note_th", "")}
            else:
                out[k] = {"value": "", "status": "missing" if f["required"] else "empty",
                          "note": g.get("note_zh", "") or ("必填，请补充" if f["required"] else "")}
            if g.get("label_zh"):
                out[k]["label_zh"] = g["label_zh"]
        if data.get("_error"):
            for f in ask:
                out[f["key"]]["note"] = data["_error"]
        pkg = data.get("package_cm")
    for f in fields:
        if f["required"] and not out[f["key"]]["value"] and f["kind"] != "colorFamily":
            out[f["key"]]["status"] = "missing"
    return out, pkg


def remember_manual(cfg, product, cat):
    """把手动改过的属性记成这个类目的默认值。返回是否有变化。"""
    mem = cfg.setdefault("category_memory", {})
    key = categories.memory_key(cat)
    slot = mem.setdefault(key, {})
    changed = False
    for k, a in (product.get("attributes") or {}).items():
        if a.get("status") == "manual" and a.get("value") and slot.get(k) != a["value"]:
            slot[k] = a["value"]
            changed = True
    return changed


# ---------------- Shopee 类目 ----------------
def match_shopee_category(cfg, product):
    """先看同一个 Lazada 类目以前对应的 Shopee 类目（记忆），没有再让 AI 从 Shopee 类目树里选。"""
    from . import shopee
    laz = str((product.get("category") or {}).get("cat_id") or "")
    remembered = (cfg.get("shopee_cat_map") or {}).get(laz)
    if remembered and remembered in shopee.tree():
        return {"id": remembered, "path": shopee.path_of(remembered), "name": shopee.display_name(remembered), "status": "auto",
                "reason": "按 Lazada 类目自动对应（以前确认过）", "reason_th": ""}
    user = f"""Product:
{_product_brief(product)}
Lazada category: {categories.path_of(laz) if laz else "unknown"}

Give 6-10 short ENGLISH keywords to find this product's leaf category in the Shopee Thailand category tree:
product-type words AND category-level words as Shopee names them (e.g. "figurine", "statue", "desk organizer",
"phone stand", "vase", "planter", "sink", "water tap", "tools", "home improvement", "washing machine", "others").
Return JSON {{"keywords": ["..."]}}"""
    kw = ai_copy.extract_json(ai_copy.call(cfg, CAT_SYSTEM, user)).get("keywords") or []
    cands = shopee.search(kw, limit=60)
    if not cands:
        return {"id": "", "path": "", "status": "check", "reason": "Shopee 类目树里没找到匹配，请手动搜索或逐级选择", "reason_th": ""}
    lst = "\n".join(f"- {cid} | {path}" for cid, path in cands)
    user2 = f"""Product:
{_product_brief(product)}

Candidate Shopee Thailand leaf categories (id | path):
{lst}

Pick the leaf category that best describes what the product physically is.
Return JSON {{"cat_id": "<the numeric id exactly as listed>", "path": "<its path>", "confidence": <0..1>,
 "reason_zh": "<one sentence Chinese>", "reason_th": "<same in Thai>"}}"""
    d = ai_copy.extract_json(ai_copy.call(cfg, CAT_SYSTEM, user2))
    tree = shopee.tree()
    m = re.search(r"\d{5,}", str(d.get("cat_id") or ""))
    cid = m.group(0) if m else ""
    if cid not in tree:
        # AI 没给出有效 ID：按它给的路径/名称去找
        want = str(d.get("path") or d.get("cat_id") or "").strip().lower()
        cid = next((c for c, (pth, _r) in tree.items() if want and pth.lower() == want), "")
        if not cid and want:
            leaf = want.split(">")[-1].strip()
            cid = next((c for c, _p in cands if _p.lower().split(" > ")[-1] == leaf), "")
    try:
        conf = float(d.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    if cid not in tree:
        # 还是不行：先选最匹配的候选，标红让你确认，不留空
        cid, conf = cands[0][0], 0.3
        reason = "AI 没给出有效类目，先选了关键词最匹配的，请确认或重新选择"
        return {"id": cid, "path": shopee.path_of(cid), "name": shopee.display_name(cid), "status": "check",
                "confidence": conf, "reason": reason, "reason_th": ""}
    return {"id": cid, "path": shopee.path_of(cid), "name": shopee.display_name(cid),
            "status": "ai" if conf >= 0.75 else "check",
            "confidence": round(conf, 2), "reason": d.get("reason_zh", ""), "reason_th": d.get("reason_th", "")}


def remember_shopee(cfg, product):
    """手动选过/确认过的 Shopee 类目，记成「Lazada 类目 → Shopee 类目」的对应关系。"""
    sc = product.get("shopee_category") or {}
    laz = str((product.get("category") or {}).get("cat_id") or "")
    if sc.get("status") == "manual" and sc.get("id") and laz:
        m = cfg.setdefault("shopee_cat_map", {})
        if m.get(laz) != sc["id"]:
            m[laz] = sc["id"]
            return True
    return False
