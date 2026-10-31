"""采用：候选池（或模型网站上扩展的「＋采集」）点「采用」→ 马上在产品库建一个 ERP 产品草稿，之后都用 ERP 自己的功能：
产品编辑页（图片、规格 / 变体、文案、类目、定价）、模型库（文件分析、切片）、上架检查（许可待核验挡导出 / 推送）。

  adopt(items)            建草稿：品名 = 原站标题，来源（原站链接、作者、网站），license_check = 待核验，品牌 / 动漫词 → 侵权待确认；
                          详情页进采集队列（扩展在后台读）
  enrich(pid, data)       扩展读到详情页：原站描述、标签、许可证（系统初判，仍要人核验）、图片地址（后台下载进产品图片）、模型文件（排队让扩展下载）
  post_process(pid)       文件都下载完：模型库分析、第一个 STL / 3MF 设成 3D 模型、从文件名识别规格（尺寸 / 版本 / 套装）建变体、
                          每个规格的克数 / 时长（切好的 3MF 用切片数据，否则用 ERP 的估算）；有 AI 时补全文案（core/ai_copy）
  verify_license(pid)     人工核验许可（编辑页 / 产品 360 上的按钮）：禁止商用的初判要 force
"""
import time

from core import db as cdb
from core import store
from core.config import load_config

from . import cand, db, files, rules, sites, variants

PIPE_KINDS = ("stl", "3mf", "zip", "obj")
MAX_AUTO_FILES = 30
MAX_IMAGES = 20


def _product(pid):
    try:
        return store.load(pid)
    except (FileNotFoundError, ValueError, OSError):
        return None


def adopt(items, who=""):
    """items: [{url, title, thumb}]。返回 {added:[{product_code, url}], skipped:{url: 原因}}。"""
    cfg = load_config()
    c = db.conn()
    added, skipped = [], {}
    for it in items or []:
        raw = str((it or {}).get("url") or "")
        url = sites.canonical(raw)
        k = sites.source_key(url)
        if not k:
            skipped[raw] = "not_model"
            continue
        row = c.execute("SELECT * FROM cur_candidates WHERE skey=?", (k,)).fetchone()
        if row and row["product_id"] and _product(row["product_id"]):
            skipped[raw] = "imported"
            continue
        if not row:
            cand.upsert([{"url": url, "title": it.get("title") or "", "thumb": it.get("thumb") or "", "metrics": it.get("metrics") or {}}], who)
            row = c.execute("SELECT * FROM cur_candidates WHERE skey=?", (k,)).fetchone()
        title = (row["title"] or it.get("title") or url).strip()[:200]
        prefix = (cfg.get("sku_prefix") or "3DP").strip().upper() or "3DP"
        pid = store.new_id(prefix)
        p = store.blank_product(pid)
        p.update(name_zh=title, draft=True)
        ai = db.jl(row["ai"])
        p["source"] = {"source": "curate", "source_id": k, "source_url": url, "platform": sites.name_of(sites.platform(url)),
                       "title_original": title, "author": row["author"], "license_verified": False, "imported_at": time.time(), "key_name": who,
                       "score": row["score"], "category_guess": row["category"],
                       "estimate": {"minutes": rules.tf(ai.get("est_minutes")), "grams": rules.tf(ai.get("est_grams"))} if ai.get("est_minutes") else None}
        p["license_check"] = {"status": "pending", "name": "", "url": "", "auto": "", "note": "", "at": time.time()}
        ip = rules.ip_hits(title, row["author"])
        if ip:
            p["ip_risk"] = {"items": [{"term": t, "reason": "选品检查：标题里有品牌 / 动漫角色词"} for t in ip], "status": "pending", "at": time.time()}
        from core import codes
        codes.ensure_skus(cfg, p)
        store.save(p)
        c.execute("UPDATE cur_candidates SET status='adopted', product_id=?, adopted_by=?, adopted_at=? WHERE id=?", (pid, who[:60], time.time(), row["id"]))
        pos = (c.execute("SELECT MAX(pos) FROM cur_collect").fetchone()[0] or 0) + 1
        c.execute("INSERT INTO cur_collect(url, skey, title, thumb, who, product_id, pos, state, created_at, updated_at) VALUES(?,?,?,?,?,?,?, 'waiting', ?, ?)",
                  (url, k, title, row["thumb"] or str(it.get("thumb") or "")[:500], who[:60], pid, pos, time.time(), time.time()))
        c.commit()
        cdb.audit(who or "选品", "选品·采用（建产品草稿）", pid, f"{title}（{sites.name_of(sites.platform(url))} {k}）")
        added.append({"product_code": pid, "url": raw})
    from . import pipeline
    pipeline.kick()
    return {"added": added, "skipped": skipped}


def enrich(pid, data, who=""):
    """详情页读到的东西补进产品草稿（已经有人改过的字段不覆盖）。"""
    p = _product(pid)
    if not p:
        return False
    s = p.setdefault("source", {})
    desc = str(data.get("description_original") or data.get("description") or "")[:20000]
    s.update(description_original=desc or s.get("description_original", ""), author=str(data.get("author") or s.get("author") or "")[:120],
             tags=str(data.get("tags") or "")[:1000], source_category=str(data.get("source_category") or "")[:200],
             print_profiles=(data.get("print_profiles") or [])[:20] if isinstance(data.get("print_profiles"), list) else [])
    if data.get("title") and p.get("name_zh") == s.get("title_original"):
        s["title_original"] = str(data["title"])[:300]
        p["name_zh"] = s["title_original"][:200]
    if not p.get("features_zh") and desc:
        from core import copyfacts
        p["features_zh"] = copyfacts.clean_source(desc)[:5000]
    if not p.get("keywords") and data.get("tags"):
        p["keywords"] = str(data["tags"])[:2000]
    lc = p.setdefault("license_check", {"status": "pending"})
    name, url = str(data.get("license_name") or "")[:200], str(data.get("license_url") or "")[:500]
    auto, note = rules.classify_license(name, url)
    lc.update(name=name, url=url, auto=auto or rules.LIC_UNKNOWN, note=note)
    s.update(license_name=name, license_url=url)
    ip = rules.ip_hits(p.get("name_zh"), s.get("tags"))
    if ip and not (p.get("ip_risk") or {}).get("items"):
        p["ip_risk"] = {"items": [{"term": t, "reason": "选品检查：标题 / 标签里有品牌 / 动漫角色词"} for t in ip], "status": "pending", "at": time.time()}
    store.save(p)
    c = db.conn()
    now = time.time()
    have = {r["url"] for r in c.execute("SELECT url FROM cur_files WHERE product_id=?", (pid,))}
    plat = sites.platform(s.get("source_url") or "")
    n_img = 0
    for u in data.get("image_urls") or []:
        if isinstance(u, str) and u.startswith("https://") and u not in have and n_img < MAX_IMAGES:
            have.add(u)
            n_img += 1
            c.execute("INSERT INTO cur_files(product_id, platform, name, url, kind, state, created_at, updated_at) VALUES(?,?,?,?, 'image', 'img', ?, ?)",
                      (pid, plat, f"image{n_img}", u[:1000], now, now))
    n = 0
    for f in data.get("model_files") or []:
        if not isinstance(f, dict) or not str(f.get("url") or "").startswith("http") or f["url"] in have:
            continue
        have.add(f["url"])
        name = files.safe_name(f.get("name") or f["url"].split("?")[0].split("/")[-1])
        kind = files.kind_of(name) or str(f.get("kind") or "")[:10]
        auto_dl = load_config().get("cur_auto_download", True) is not False and kind in PIPE_KINDS and n < MAX_AUTO_FILES and _mb(f.get("size")) <= 300
        n += 1 if auto_dl else 0
        c.execute("INSERT INTO cur_files(product_id, platform, name, url, size_text, kind, folder, state, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (pid, plat, name, f["url"][:1000], str(f.get("size") or "")[:20], kind, str(f.get("folder") or "")[:100], "queued" if auto_dl else "", now, now))
    c.execute("UPDATE cur_collect SET post=1 WHERE product_id=?", (pid,))
    c.commit()
    return True


def _mb(t):
    t = str(t or "").upper().replace(",", "")
    try:
        v = float("".join(ch for ch in t if ch.isdigit() or ch == ".") or 0)
    except ValueError:
        return 0
    return v * 1024 if "GB" in t else v / 1024 if "KB" in t else v


def files_pending(pid):
    return db.conn().execute("SELECT COUNT(*) FROM cur_files WHERE product_id=? AND state IN ('queued','downloading','img')", (pid,)).fetchone()[0]


def post_process(pid, cfg=None):
    """文件和图片都到了以后：模型库分析、3D 模型、规格、克数 / 时长、文案。返回做了什么。"""
    from core import modellib
    cfg = cfg or load_config()
    p = _product(pid)
    if not p:
        return []
    done = []
    s = p.setdefault("source", {})
    lib = None
    try:
        lib = modellib.library(pid)            # 登记 source_files、分析（尺寸、估算克数 / 时长、切好的 3MF 读切片数据）
    except Exception as e:  # noqa: BLE001
        s["post_error"] = str(e)[:200]
    p = _product(pid)
    s = p.setdefault("source", {})
    items = [e for e in (lib or {}).get("items") or [] if e.get("dir") == "source_files"]
    if items and not s.get("specs_done"):
        rows = []
        for i, e in enumerate(items):
            inf = e.get("info") or {}
            sz = inf.get("size") or []
            sl = inf.get("sliced_result") or {}
            est = inf.get("est") or {}
            rows.append({"id": i, "name": e.get("orig_name") or e["file"], "file": e["file"], "folder": "",
                         "bbox": ",".join(f"{float(x):.1f}" for x in sz) if len(sz) == 3 else "",
                         "grams": sl.get("grams") or est.get("grams") or 0, "hours": sl.get("hours") or est.get("hours") or 0,
                         "src": "sliced" if sl.get("grams") else "estimate", "ext": e.get("ext")})
        models = [r for r in rows if r["ext"] in ("stl", "3mf", "obj")]
        sug = variants.rule_variants([{"id": r["id"], "name": r["name"], "folder": "", "bbox": r["bbox"]} for r in models]) if models else {"variants": [], "common": []}
        by = {r["id"]: r for r in rows}
        common = [by[i] for i in sug["common"] if i in by]
        untouched = not p.get("exported_at") and len(p.get("variants") or []) <= 1 and not any((v.get("opt1_zh") or "").strip() for v in p.get("variants") or [])
        tot = lambda rs: (round(sum(r["grams"] or 0 for r in rs), 1), round(sum(r["hours"] or 0 for r in rs), 2))  # noqa: E731
        if sug["variants"] and untouched:
            from core import specs as _specs
            raw = []
            for i, v in enumerate(sug["variants"][:12]):
                own = [by[x] for x in v["file_ids"] if x in by]
                g, h = tot(common + own)
                raw.append({"spec_id": f"cur-{i + 1}", "position": i + 1, "kind": v.get("kind") or "size", "name_zh": v["name_zh"], "name_th": v["name_th"],
                            "name_en": v.get("name_en") or "", "is_default": i == 0, "scale_pct": v.get("scale_pct") or None, "pack_qty": v.get("pack_qty") or 1,
                            "parts": len(own) + len(common), "filament_grams": g, "print_minutes": h * 60,
                            "recognize": {"method": "rule", "confidence": v.get("conf") or 0.9, "evidence": v.get("evidence") or ""},
                            "files": [{"url": "file:" + r["file"], "name": r["file"]} for r in own]})
            try:
                sp, _w = _specs.parse(raw)
                _specs.build_rows(p, sp)
                _specs.package_from_specs(p)
                for vv, ss in zip(p["variants"], sp):
                    fs = [x["name"] for x in ss.get("files") or []]
                    vv["model_file"] = fs[0] if fs else None
                    vv["model_note"] = "" if fs else "用产品的 3D 模型"
                    vv["grams_src"] = "curator"
                from core import codes
                codes.ensure_skus(cfg, p)
                done.append("specs")
            except Exception as e:  # noqa: BLE001
                s["spec_suggestion"] = {"error": str(e)[:200], "variants": [v["name_zh"] for v in sug["variants"]]}
        elif untouched and models:
            g, h = tot(common or models[:1])
            if g or h:
                p["variants"][0].update(grams=g, hours=h, grams_src="curator")
                done.append("grams")
        elif sug["variants"]:
            s["spec_suggestion"] = {"variants": [v["name_zh"] for v in sug["variants"]], "note": "产品已经有变体了，没有自动改；在编辑页按建议加规格"}
        s["specs_done"] = True
        s["spec_note"] = sug.get("note", "")[:300] if models else ""
        s["time_source"] = "sliced" if any(r["src"] == "sliced" for r in models) else "estimate"
        store.save(p)
        # 3D 模型：第一个 STL / 3MF（默认规格的文件优先）
        if not p.get("model"):
            first = next((e for e in items if e.get("ext") in ("stl", "3mf") and not str(e.get("file", "")).lower().endswith(".gcode.3mf")), None)
            want = (p.get("variants") or [{}])[0].get("model_file")
            first = next((e for e in items if e["file"] == want), first)
            if first:
                try:
                    modellib.make_current(pid, [{"id": first["id"]}], "选品")
                    done.append("model")
                except Exception as e:  # noqa: BLE001
                    p = _product(pid)
                    p.setdefault("source", {})["post_error"] = f"3D 模型读不了：{str(e)[:120]}"
                    store.save(p)
    # 文案：ERP 的 AI 文案（补全空着的字段），只做一次
    p = _product(pid)
    s = p.setdefault("source", {})
    if cand.ai_on(cfg) and not s.get("ai_copy_tried"):
        s["ai_copy_tried"] = time.time()
        store.save(p)
        try:
            from core import ai_copy
            out = ai_copy.complete_copy(cfg, p, p.get("keyword_plan"))
            p = _product(pid)
            ai_copy.apply_completion(p, out)
            cp = p.get("copy") or {}
            if p.get("name_zh") == p["source"].get("title_original") and cp.get("title_th"):
                zh = cp.get("title_zh") or ai_copy.back_translate(cfg, cp["title_th"], cp.get("description_th") or "", with_en=False).get("title_zh")
                if zh:                     # 中文品名：泰文标题回译（ERP 的 AI 回译）
                    p["name_zh"] = str(zh)[:200]
            store.save(p)
            done.append("copy")
        except Exception as e:  # noqa: BLE001
            p = _product(pid)
            p.setdefault("source", {})["post_error"] = f"AI 文案：{str(e)[:150]}"
            store.save(p)
    return done


def fetch_image(url, referer=""):
    """下载一张原站图片（只 https、最大 20 MB）。测试里可以换掉。"""
    import requests
    r = requests.get(url, timeout=(10, 40), headers={"User-Agent": "Mozilla/5.0", **({"Referer": referer} if referer else {})}, stream=True)
    if r.status_code != 200:
        raise ValueError(f"HTTP {r.status_code}")
    data = r.raw.read(20 * 1024 * 1024 + 1, decode_content=True)
    if len(data) > 20 * 1024 * 1024:
        raise ValueError("图片太大")
    return data


def pull_images(pid, limit=6):
    """后台：把原站图片下载进产品图片（原图，ERP 的修图 / 白底 / 卖点图都能用）。返回处理了几张。"""
    import io
    import os
    import uuid
    from PIL import Image
    c = db.conn()
    rows = c.execute("SELECT * FROM cur_files WHERE product_id=? AND kind='image' AND state='img' ORDER BY id LIMIT ?", (pid, limit)).fetchall()
    if not rows:
        return 0
    p = _product(pid)
    if not p:
        c.execute("UPDATE cur_files SET state='failed', error='产品已删除' WHERE product_id=? AND state='img'", (pid,))
        c.commit()
        return len(rows)
    ref = (sites.site_for_url(p.get("source", {}).get("source_url") or "") or {}).get("referer") or ""
    raw = store.image_dir(pid, "raw")
    for r in rows:
        try:
            data = fetch_image(r["url"], ref)
            im = Image.open(io.BytesIO(data))
            im.load()
            name = f"{uuid.uuid4().hex[:10]}.jpg"
            im.convert("RGB").save(os.path.join(raw, name), "JPEG", quality=92)
            p = _product(pid)
            p.setdefault("images", []).append({"file": name, "raw": name, "processed": False, "url": "", "from": "source"})
            store.save(p)
            c.execute("UPDATE cur_files SET state='ok', stored=?, error='', updated_at=? WHERE id=?", (name, time.time(), r["id"]))
        except Exception as e:  # noqa: BLE001
            c.execute("UPDATE cur_files SET state='failed', error=?, updated_at=? WHERE id=?", (str(e)[:200], time.time(), r["id"]))
        c.commit()
    return len(rows)


def verify_license(pid, verified=True, force=False, who="", note=""):
    from core import copyrules
    return copyrules.verify_license(pid, verified, force, who, note)
