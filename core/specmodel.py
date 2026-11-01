"""规格 ↔ 3D 模型（v2.22）。

一个产品有一个「主模型」（product["model"]：3D 预览、商品图、估算都用它）。
产品有好几个规格（变体的第二个选项 opt2_zh：大号 / 小号 / 套装…）而且各规格是不同的模型时，可以给每个规格指定模型库里的一个文件：
  变体 v["model_lib_id"] = 模型库条目 id（同一规格的所有颜色一起改）。没指定的规格用主模型。
指定了自己模型的规格，有自己的打印方案（product["spec_recipes"][规格]）和自己的切片文件（print_files.spec = 规格）。
生产时按订单 SKU → 规格 → 模型 / 方案 / 切片文件。

★ 对外接口：specs(p)  spec_of_sku(p, sku)  entry_for(p, spec)  view(p, spec)  model_path(view)
            overview(pid)  map_spec(pid, spec, eid, user)  save_recipe(pid, spec, recipe)  fill_grams(pid, spec, user)
"""
import copy
import os

from . import store

MODEL_EXT = (".stl", ".3mf", ".obj")


def specs(p):
    out = []
    for v in p.get("variants") or []:
        s = (v.get("opt2_zh") or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def spec_of_sku(p, sku):
    sku = (sku or "").strip().upper()
    if not sku:
        return ""
    for v in p.get("variants") or []:
        if (v.get("sku") or "").strip().upper() == sku:
            return (v.get("opt2_zh") or "").strip()
    return ""


def _lib(p):
    return {e["id"]: e for e in (p.get("model_lib") or []) if isinstance(e, dict) and e.get("id")}


def entry_for(p, spec):
    """这个规格指定的模型库条目（没指定 / 文件不在了 → None = 用主模型）。"""
    if not spec:
        return None
    lib = _lib(p)
    for v in p.get("variants") or []:
        if (v.get("opt2_zh") or "").strip() == spec and v.get("model_lib_id") in lib:
            e = lib[v["model_lib_id"]]
            if (p.get("model") or {}).get("lib_id") == e["id"]:
                return None             # 指定的就是主模型：等于没指定
            from . import modellib
            if modellib.path_of(p["id"], e) and os.path.splitext(e["file"])[1].lower() in MODEL_EXT:
                return e
    return None


def own(p, spec):
    return entry_for(p, spec) is not None


def _plans(p):
    return p.get("print_plans") if isinstance(p.get("print_plans"), dict) else {}


def file_spec(p, spec):
    """v2.53.1：这个规格的任务只能用 print_files.spec 等于几的切片文件（"" = 主模型的文件）。
    规格有自己的模型，或者有自己的打印方案（保存过的盘 / 「按主模型缩放 N%」）→ 规格自己；其他 → 主模型。
    打印方案的 plan_key、切片文件的筛选、试打结果写回都按这个，保证不会把主模型 100% 的文件发给缩放过的规格。"""
    spec = (spec or "").strip()
    if not spec:
        return ""
    if own(p, spec):
        return spec
    pl = _plans(p).get(spec) or {}
    return spec if (pl.get("plates") or pl.get("follow")) else ""


def follow_scale(p, spec):
    """「按主模型缩放 N%」的规格 → N（百分比）；其他 → None。"""
    spec = (spec or "").strip()
    pl = (_plans(p).get(spec) or {}) if spec else {}
    if pl.get("follow") and pl.get("scale"):
        try:
            return round(float(pl["scale"]), 1)
        except (TypeError, ValueError):
            return None
    return None


def plan_sliced(p, spec):
    """这个规格的切片文件要按打印方案（modules/model printplan.slice_plate）切，不能用 recipes.slice_product 切模型：
    「按主模型缩放」的规格，或者没有自己的模型、却有自己保存过的方案（例如从别的规格复制的）。"""
    key = file_spec(p, spec)
    return bool(key) and (follow_scale(p, key) is not None or not own(p, key))


def spec_name(s):
    return f"规格「{s}」" if s else "主模型"


def file_error(f, p, sku):
    """切片文件和任务（产品 p 的 SKU）的规格 / 尺寸对不对得上；对不上返回原因（中文），对得上返回 ""。
    第二道保险：开始打印 / 试打 / 检查文件都会再核对一次（slicecheck 只核对机型 / 喷嘴 / 热床板）。"""
    if not f:
        return ""
    head = f"文件尺寸 / 规格和任务不一致（文件 #{f.get('id')}）："
    if (f.get("product_id") or "") != (p.get("id") or ""):
        return head + "不是这个产品的切片文件"
    want = file_spec(p, spec_of_sku(p, sku))
    have = (f.get("spec") or "").strip()
    if have != want:
        return head + f"任务要{spec_name(want)}的文件，这个文件是{spec_name(have)}的。请用{spec_name(want)}的打印方案重新切片"
    sc = follow_scale(p, want)
    fs = f.get("scale")
    if sc is not None:
        if fs in (None, ""):
            return head + f"{spec_name(want)}按主模型缩放 {sc:g}%，这个文件没有记录缩放比例，请重新切片"
        if abs(float(fs) - sc) > 0.05:
            return head + f"{spec_name(want)}现在按主模型缩放 {sc:g}%，这个文件是按 {float(fs):g}% 切的，请重新切片"
    elif fs not in (None, "") and abs(float(fs) - 100.0) > 0.05:
        return head + f"这个文件是按 {float(fs):g}% 缩放切的，{spec_name(want)}现在不缩放，请重新切片"
    return ""


def view(p, spec):
    """按规格看的产品：模型、打印方案换成这个规格的。没有自己模型的规格就是产品本身（_spec = ""）。"""
    e = entry_for(p, spec)
    if not e:
        v = dict(p)
        v["_spec"] = ""
        return v
    from . import modellib
    v = dict(p)
    info = e.get("info") or {}
    v["model"] = {"file": e["file"], "ext": e.get("ext") or os.path.splitext(e["file"])[1].lstrip("."),
                  "orig_name": e.get("orig_name") or e["file"], "lib_id": e["id"],
                  "metrics": {"size": info.get("size")} if info.get("size") else {}, "triangles": info.get("triangles")}
    v["_model_path"] = modellib.path_of(p["id"], e)
    sr = (p.get("spec_recipes") or {}).get(spec)
    if sr is None:
        sr = copy.deepcopy(p.get("recipe") or {})
        sr.pop("capacity_learned", None)
        sr.pop("updated_at", None)
    v["recipe"] = sr
    v["_spec"] = spec
    return v


def model_path(prod):
    """（产品或 view）现在要用的模型文件路径。"""
    if prod.get("_model_path"):
        return prod["_model_path"]
    m = prod.get("model")
    if not m:
        return None
    return os.path.join(store.image_dir(prod["id"], "model"), m["file"])


def overview(pid):
    from . import modellib, print_files
    modellib.library(pid)            # 登记 + 分析还没分析过的文件（尺寸、组件），v2.23
    p = store.load(pid)
    lib = _lib(p)
    files = print_files.list_files(pid)
    main = p.get("model") or None
    rows = []
    for s in specs(p):
        e = entry_for(p, s)
        vs = [v for v in p.get("variants") or [] if (v.get("opt2_zh") or "").strip() == s]
        est = ((e or {}).get("info") or {}).get("est") or {}
        rows.append({"spec": s, "entry_id": e["id"] if e else "", "name": (e or {}).get("orig_name") or "",
                     "own": bool(e), "variants": len(vs), "grams": vs[0].get("grams") if vs else None,
                     "hours": vs[0].get("hours") if vs else None, "est": est,
                     "own_recipe": s in (p.get("spec_recipes") or {}),
                     "files": sum(1 for f in files if (f.get("spec") or "") == file_spec(p, s))})
    entries = []
    for e in lib.values():
        info = e.get("info") or {}
        ext = os.path.splitext(e.get("file") or "")[1].lower()
        entries.append({"id": e["id"], "name": e.get("orig_name") or e["file"], "ok": bool(info.get("ok")) and ext in MODEL_EXT,
                        "parts": [{"index": x.get("index"), "name": x.get("name"), "size": x.get("size"), "best": x.get("best")} for x in info.get("parts") or []],
                        "colors": info.get("colors"), "color_guide": color_guide(info.get("colors")) if (info.get("colors") or {}).get("multicolor") else "",
                        "parts_of": e.get("parts_of") or None,
                        "size": info.get("size"), "est": info.get("est"), "is_main": (main or {}).get("lib_id") == e["id"],
                        "specs": [s for s in specs(p) if entry_for(p, s) and entry_for(p, s)["id"] == e["id"]]})
    return {"main": {"name": (main or {}).get("orig_name") or "", "lib_id": (main or {}).get("lib_id") or "",
                     "size": ((main or {}).get("metrics") or {}).get("size"), "estimate": (main or {}).get("estimate")} if main else None,
            "specs": rows, "library": entries, "has_specs": bool(rows)}


def map_spec(pid, spec, eid, user=""):
    """规格 spec 用模型库里的 eid（空 = 用主模型）。同一规格的所有颜色一起改。"""
    from . import db, modellib
    p = store.load(pid)
    modellib._sync(p)
    spec = (spec or "").strip()
    if spec not in specs(p):
        raise ValueError(f"这个产品没有规格「{spec}」")
    lib = _lib(p)
    if eid:
        e = lib.get(eid)
        if not e:
            raise ValueError("模型库里没有这个文件（刷新一下）")
        if os.path.splitext(e["file"])[1].lower() not in MODEL_EXT:
            raise ValueError("只能选 STL / 3MF / OBJ 模型文件")
    before = entry_for(p, spec)
    for v in p.get("variants") or []:
        if (v.get("opt2_zh") or "").strip() == spec:
            if eid:
                v["model_lib_id"] = eid
                v["model_file"] = lib[eid]["file"]
            else:
                v.pop("model_lib_id", None)
                v.pop("model_file", None)
    if eid and not lib[eid].get("variant"):
        lib[eid]["variant"] = spec
    store.save(p)
    after = entry_for(store.load(pid), spec)
    if (before or {}).get("id") != (after or {}).get("id"):
        # 换了模型：这个规格原来的切片文件不能再用（退回草稿）
        from . import print_files  # noqa: F401
        c = db.conn()
        c.execute("UPDATE print_files SET status='draft', note=? WHERE product_id=? AND active=1 AND COALESCE(spec,'')=? AND status!='draft'",
                  (f"规格「{spec}」换了模型，请重新切片或复核", pid, spec if before else ""))
        c.commit()
    db.audit(user, "规格指定模型", pid, f"{spec} → {(lib.get(eid) or {}).get('orig_name') or '主模型'}")
    return overview(pid)


def save_recipe(pid, spec, recipe):
    """保存打印方案：有自己模型的规格存到 spec_recipes，其他存到产品的方案。返回存的位置（规格名或空）。"""
    p = store.load(pid)
    if spec and own(p, spec):
        old = (p.get("spec_recipes") or {}).get(spec) or {}
        recipe["capacity_learned"] = old.get("capacity_learned") or {}
        p.setdefault("spec_recipes", {})[spec] = recipe
        store.save(p)
        return spec
    recipe["capacity_learned"] = (p.get("recipe") or {}).get("capacity_learned") or {}
    p["recipe"] = recipe
    store.save(p)
    return ""


def learn_capacity(prod, key, n):
    """recipes 用：记住一盘排得下几个（规格自己的方案存到规格里）。"""
    try:
        p = store.load(prod["id"])
    except FileNotFoundError:
        return
    spec = prod.get("_spec") or ""
    if spec and own(p, spec):
        r = (p.get("spec_recipes") or {}).get(spec)
        if r is None:
            return
    else:
        r = p.get("recipe")
        if not r:
            return
    r.setdefault("capacity_learned", {})[key] = int(n)
    store.save(p)
    prod["recipe"] = r


def fill_grams(pid, spec, user=""):
    """按这个规格的模型估算（没有自己模型就用主模型）填这个规格所有颜色的克数和时长。"""
    p = store.load(pid)
    e = entry_for(p, spec)
    if e:
        est = (e.get("info") or {}).get("est") or {}
    else:
        est0 = (p.get("model") or {}).get("estimate") or {}
        pp = est0.get("per_printer") or [{}]
        est = {"grams": est0.get("grams"), "hours": pp[0].get("hours") if pp else None}
    if not est.get("grams"):
        raise ValueError("这个模型还没有估算（先在模型库里分析一下）")
    n = 0
    for v in p.get("variants") or []:
        if (v.get("opt2_zh") or "").strip() == spec:
            v["grams"] = round(float(est["grams"]), 1)
            if est.get("hours"):
                v["hours"] = round(float(est["hours"]), 2)
            v["grams_src"] = "est"
            n += 1
    store.save(p)
    return n


def size_label(size):
    """模型外框 [x, y, z] mm → 规格名，例如 12cm / 8.5cm（最长边）。"""
    try:
        L = max(float(x) for x in size)
    except (TypeError, ValueError):
        return ""
    if L <= 0:
        return ""
    cm = L / 10
    return (f"{round(cm)}cm" if cm >= 10 else f"{cm:.1f}".rstrip("0").rstrip(".") + "cm")


def auto_specs(pid, user=""):
    """v2.22.1 自动加规格：模型库里还没分配给规格的模型文件，每个文件加成一个规格（按尺寸起名，例如 12cm），
    每个颜色一行，克数 / 时长用模型估算，并且指定这个规格用这个模型。产品原来没有规格时，现有的变体按主模型尺寸起名。"""
    from . import codes, db, modellib
    from . import specs as specs_mod
    from .config import load_config
    p = store.load(pid)
    modellib._sync(p)
    ov = overview(pid)
    main_id = (p.get("model") or {}).get("lib_id")
    used = {e for e in (v.get("model_lib_id") for v in p.get("variants") or []) if e}
    todo = [e for e in ov["library"] if e["ok"] and not e["is_main"] and e["id"] not in used and e["id"] != main_id]
    if not todo:
        raise ValueError("模型库里没有还没分配给规格的模型文件。先在「📚 模型库」上传其他尺寸 / 型号的模型，再点自动加规格")
    lib = _lib(p)
    vs = p.setdefault("variants", [])
    names = specs(p)
    added = []
    if not names:
        main_size = ((p.get("model") or {}).get("metrics") or {}).get("size")
        first = size_label(main_size) or "标准款"
        for v in vs:
            v["opt2_zh"] = first
        names = [first]
        added.append(first)
    s0 = names[0]
    tmpl = [v for v in vs if (v.get("opt2_zh") or "").strip() == s0] or vs[:1]
    for e in todo:
        n = size_label(e.get("size")) or os.path.splitext(e["name"])[0][:20]
        if n in names:
            n = (os.path.splitext(e["name"])[0][:14] + " " + n)[:20] if n else os.path.splitext(e["name"])[0][:20]
        k = 2
        base_n = n
        while n in names:
            n = f"{base_n[:17]}-{k}"
            k += 1
        est = e.get("est") or {}
        for t in tmpl:
            row = {kk: vv for kk, vv in t.items() if kk not in ("sku", "spec_id", "image", "stock", "manual_price", "model_lib_id",
                                                               "model_file", "platform_dirty", "model_note")}
            row.update(opt2_zh=n, model_lib_id=e["id"], model_file=lib[e["id"]]["file"], manual_price=None, image="", stock=None, sku="")
            if est.get("grams"):
                row["grams"] = round(float(est["grams"]), 1)
                row["grams_src"] = "est"
            if est.get("hours"):
                row["hours"] = round(float(est["hours"]), 2)
            vs.append(row)
        lib[e["id"]]["variant"] = n
        names.append(n)
        added.append(n)
    if not (p.get("variation2_name_zh") or "").strip():
        p["variation2_name_zh"] = "规格"
    p.setdefault("copy", {}).setdefault("variation2_name_th", "ขนาด")
    ot = p["copy"].setdefault("options_th", {})
    for n in added:
        ot.setdefault(n, n)
    bad = specs_mod.check_variants(p, None)
    if bad:
        raise ValueError(bad)
    codes.ensure_skus(load_config(), p)
    store.save(p)
    db.audit(user, "按模型自动加规格", pid, "、".join(added))
    return added


def map_parts(pid, spec, items, user=""):
    """v2.23：规格用模型库文件里的某几个组件（例如一个 3MF 里装了 15 种组合，每个规格只打其中一个）。
    items: [{"id": 库文件 id, "part": 组件序号, "qty": 数量}] → 组合成一个模型存进模型库，并指定给这个规格。"""
    from . import modellib
    spec = (spec or "").strip()
    if spec not in specs(store.load(pid)):
        raise ValueError(f"这个产品没有规格「{spec}」")
    e = modellib.make_entry(pid, items, user, name=f"{spec}", variant=spec)
    return map_spec(pid, spec, e["id"], user)


def _norm_name(s):
    import re
    s = str(s or "").lower().replace("×", "x").replace("*", "x")
    s = re.sub(r"\.(stl|3mf|obj|step)$", "", s)
    return re.sub(r"[\s_\-]+", "", s)


def auto_parts(pid, user=""):
    """v2.23：按组件名自动对应：组件名里包含规格名（例如组件「keycap_1x3」↔ 规格「1×3」）就指定给这个规格。
    已经有自己模型的规格不动。返回 {对上的规格: 组件名}。"""
    import re
    p = store.load(pid)
    ov = overview(pid)
    done = {}
    cands = []
    for e in ov["library"]:
        if not e["ok"] or e.get("parts_of"):
            continue
        for x in e.get("parts") or []:
            cands.append((e["id"], x["index"], x["name"] or "", _norm_name(x["name"])))
    if not cands:
        raise ValueError("模型库的文件里没有读到组件（3MF 里只有一个整体）。可以给每个规格「⬆ 上传 / 换模型」")
    for row in ov["specs"]:
        if row["own"]:
            continue
        key = _norm_name(row["spec"])
        if not key:
            continue
        # 规格名出现在组件名里，前后不能紧挨数字（1x3 不能匹配到 11x3 / 1x30）
        pat = re.compile(r"(?<![0-9.])" + re.escape(key) + r"(?![0-9])")
        hits = [c for c in cands if pat.search(c[3])]
        if len(hits) == 1:
            map_parts(pid, row["spec"], [{"id": hits[0][0], "part": hits[0][1], "qty": 1}], user)
            done[row["spec"]] = hits[0][2]
    return done


# ---------------- v2.23：多色 / 分体 ----------------
def colors_of(prod):
    """这个产品（或按规格的 view）现在用的模型的多色信息（没有返回 None）。"""
    lid = (prod.get("model") or {}).get("lib_id")
    e = _lib(prod).get(lid) if lid else None
    return ((e or {}).get("info") or {}).get("colors")


def color_guide(ci):
    """告诉员工每一槽装什么颜色、哪个零件用哪一槽（中文）。"""
    if not ci:
        return ""
    used = set(ci.get("used") or [])
    lines = []
    for f in ci.get("filaments") or []:
        if used and f["slot"] not in used:
            continue
        ps = [x["name"] for x in ci.get("parts") or [] if x.get("slot") == f["slot"] or (isinstance(x.get("slot"), list) and f["slot"] in x["slot"])]
        lines.append(f"槽 {f['slot']}：{f.get('name') or '颜色'}（{f.get('hex')}）{f.get('type') or ''}" + (f" → {'、'.join(ps[:6])}" if ps else ""))
    if ci.get("painted"):
        lines.append("模型上有涂色（同一个零件多种颜色）")
    return "；".join(lines)


def check_auto_slice(prod):
    """程序自动切片前检查：多色模型做不了，返回说明（空 = 可以）。"""
    ci = colors_of(prod)
    if ci and ci.get("multicolor"):
        if ci.get("painted"):
            return ("这是涂色的多色模型，程序切会丢掉涂色。请在电脑上用 Bambu Studio 打开这个模型文件切片，再上传切片文件。"
                    "需要的耗材：" + color_guide(ci))
        return ("这是多色模型（不同零件不同颜色），这里的自动切片只能切单色。请到「打印方案」里摆盘、给每个零件选 AMS 槽，"
                "再点「按这一盘切片」。需要的耗材：" + color_guide(ci))
    return ""


def flatten(pid, spec="", user=""):
    """v2.23：分体模型的每个组件按程序推荐的方向平放，排在一盘里（不重叠），存成新模型。
    spec 有值：指定给这个规格；没有：设为主模型。返回 {overview, selection, entry}。"""
    from . import modellib
    p = store.load(pid)
    e = entry_for(p, spec) if spec else None
    if not e:
        lid = (p.get("model") or {}).get("lib_id")
        e = _lib(p).get(lid)
    if not e:
        raise ValueError("还没有模型")
    parts = (e.get("info") or {}).get("parts") or []
    if len(parts) < 2:
        raise ValueError("这个模型只有一个整体，不用分开摆")
    sel = [{"id": e["id"], "part": x["index"], "qty": 1, "orient": x.get("best") or "bottom"} for x in parts]
    if spec:
        ne = modellib.make_entry(pid, sel, user, name=f"{spec}_分体平放", variant=spec)
        map_spec(pid, spec, ne["id"], user)
    else:
        r = modellib.make_current(pid, sel, user, name=f"{os.path.splitext(e.get('orig_name') or 'model')[0][:30]}_分体平放")
        ne = r.get("merged")
    return {"selection": sel, "entry": {"id": (ne or {}).get("id"), "name": (ne or {}).get("orig_name")}}
