"""3D选品工具 → ERP 新建产品（规范 v1.5 第 4.2 条，ERP 2.12）。

选品工具调 POST /api/v1/catalog/products，ERP：
1. 同一个 source + source_id 只建一次（再推返回已有编号，created = false）；
2. 生成产品编号（3DP + 流水号），建成「草稿」：颜色、SKU、售价在 ERP 里补齐后再导出上架；
3. 把图片、模型文件从选品工具下载到 ERP 自己的 data 文件夹（用选品工具发的密钥，设置里填）。
"""
import json
import re
import os
import shutil
import time
import uuid
from urllib.parse import urljoin

from core import db, store
from core.config import DATA_DIR, load_config

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalog_imports (
  source TEXT NOT NULL, source_id TEXT NOT NULL, product_id TEXT, created_at REAL, key_name TEXT, payload TEXT,
  PRIMARY KEY(source, source_id)
);
"""
MATERIALS = {"PLA": "PLA", "PETG": "PETG", "TPU": "TPU", "ABS": "ABS", "ASA": "ASA", "树脂": "RESIN", "RESIN": "RESIN",
             "其他": "PLA", "OTHER": "PLA"}
IMG_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGES = 30
MAX_IMG_BYTES = 20 * 1024 * 1024
MAX_FILE_BYTES = 500 * 1024 * 1024


class CatalogError(Exception):
    def __init__(self, msg, code="invalid", http=400):
        super().__init__(msg)
        self.code, self.http = code, http


def init():
    c = db.conn()
    c.executescript(SCHEMA)
    c.commit()


def categories():
    """ERP 里能用的类目 = 已上传了 Lazada 模板的类目（导出上架表格要用）。"""
    from core import categories as cats
    lib = cats.library()
    return [{"name": c["name"], "id": c["id"], "lazada_cat_id": c.get("cat_id") or None, "path": c.get("path") or ""} for c in lib]


def _find_category(val):
    v = str(val or "").strip()
    if not v:
        return None
    lib = categories()
    for c in lib:
        if v in (c["name"], c["id"], str(c["lazada_cat_id"] or "")):
            return c
    low = v.lower()
    hits = [c for c in lib if low == (c["name"] or "").lower() or (c["name"] or "").lower().endswith("> " + low)]
    return hits[0] if len(hits) == 1 else None


def _session():
    import requests
    s = requests.Session()
    key = (load_config().get("curator_api_key") or "").strip()
    if key:
        s.headers["Authorization"] = "Bearer " + key
    return s


def _abs(url):
    url = str(url or "").strip()
    if url.startswith(("http://", "https://")):
        return url
    base = (load_config().get("curator_base_url") or "").strip()
    if not base:
        raise CatalogError("图片 / 文件地址是相对地址，请在 ERP「系统 → 设置 → AI 与对接 → 3D选品工具对接」填选品工具地址", "image_download_failed", 502)
    return urljoin(base.rstrip("/") + "/", url.lstrip("/"))


def _download(sess, url, dest_dir, max_bytes, kind):
    """下载到 dest_dir，返回 (文件名, content-type)。"""
    try:
        r = sess.get(_abs(url), stream=True, timeout=(10, 60))
    except Exception as e:  # noqa: BLE001
        raise CatalogError(f"下载{kind}失败：{e}", "image_download_failed", 502)
    if r.status_code in (401, 403):
        raise CatalogError(f"下载{kind}被选品工具拒绝（{r.status_code}）：请在 ERP「系统 → 设置 → AI 与对接 → 3D选品工具对接」填对选品工具的密钥",
                           "image_download_failed", 502)
    if r.status_code != 200:
        raise CatalogError(f"下载{kind}失败：HTTP {r.status_code}（{url}）", "image_download_failed", 502)
    ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    os.makedirs(dest_dir, exist_ok=True)
    tmp = os.path.join(dest_dir, ".dl_" + uuid.uuid4().hex)
    n = 0
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(256 * 1024):
            n += len(chunk)
            if n > max_bytes:
                f.close()
                os.remove(tmp)
                raise CatalogError(f"{kind}太大了（超过 {max_bytes // 1048576} MB）：{url}", "image_download_failed", 502)
            f.write(chunk)
    return tmp, ctype


def _listing(raw):
    """选品工具 2.2 的结构化商品文案 listing（只认识的字段，长度做个上限）。不是对象就当没有。"""
    if not isinstance(raw, dict):
        return None
    out = {}
    for k in ("title_zh", "title_th"):
        if raw.get(k):
            out[k] = str(raw[k]).strip()[:255]
    for k in ("intro_zh", "intro_th", "package_zh", "package_th"):
        if raw.get(k):
            out[k] = str(raw[k]).strip()[:3000]
    for k, n in (("highlights_zh", 8), ("highlights_th", 8), ("scenes_zh", 10), ("scenes_th", 10), ("notes_zh", 10), ("notes_th", 10),
                 ("keywords_zh", 20), ("keywords_th", 20)):
        if isinstance(raw.get(k), list):
            out[k] = [str(x).strip()[:300] for x in raw[k] if str(x).strip()][:n]
    risk = []
    for r in raw.get("ip_risk") or [] if isinstance(raw.get("ip_risk"), list) else []:
        if isinstance(r, dict) and r.get("term"):
            risk.append({"term": str(r["term"])[:60], "reason": str(r.get("reason") or "")[:200]})
        elif isinstance(r, str) and r.strip():
            risk.append({"term": r.strip()[:60], "reason": ""})
    out["ip_risk"] = risk[:20]
    out["method"] = str(raw.get("method") or "")[:10]
    out["version"] = raw.get("version")
    out["generated_at"] = raw.get("generated_at")
    return out


def text_to_html(t):
    """选品工具的段落文字（【标题】、• 列表）→ 平台详情用的简单 HTML。已经是 HTML 的原样返回。"""
    import html as _h
    t = (t or "").strip()
    if not t or re.search(r"<(p|ul|li|br|strong)\b", t, re.I):
        return t
    out, ul = [], []

    def flush():
        if ul:
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in ul) + "</ul>")
            ul.clear()
    for line in t.splitlines():
        line = line.strip()
        if not line:
            flush()
            continue
        m = re.match(r"^[•·\-*]\s*(.+)$", line)
        if m:
            ul.append(_h.escape(m.group(1)))
            continue
        flush()
        m = re.match(r"^(【[^】]+】)\s*(.*)$", line)
        if m:
            out.append(f"<p><strong>{_h.escape(m.group(1))}</strong>{(' ' + _h.escape(m.group(2))) if m.group(2) else ''}</p>")
        else:
            out.append(f"<p>{_h.escape(line)}</p>")
    flush()
    return "".join(out)


def _parse_variants(raw):
    """多规格（对接规范 4.3，v2.16 起按 core/specs 的规则）。返回 (specs, warnings)。"""
    from core import specs as _specs
    try:
        return _specs.parse(raw)
    except _specs.SpecError as e:
        raise CatalogError(str(e), "invalid_field")


def create(b, key_name=""):
    """新建产品（草稿）。返回 {product_code, created, skus, images, files, warnings}。"""
    if not isinstance(b, dict):
        raise CatalogError("请求体必须是 JSON 对象", "invalid_field")
    source = str(b.get("source") or "").strip()[:40]
    sid = str(b.get("source_id") if b.get("source_id") is not None else "").strip()[:60]
    if not source or not sid:
        raise CatalogError("缺少 source / source_id（用来防止重复建档）", "invalid_field")
    c = db.conn()
    old = c.execute("SELECT product_id FROM catalog_imports WHERE source=? AND source_id=?", (source, sid)).fetchone()
    if old:
        try:
            p = store.load(old["product_id"])
            return {"product_code": p["id"], "created": False, "skus": [v["sku"] for v in p.get("variants", []) if v.get("sku")],
                    "images": len(p.get("images") or []), "files": len(p.get("source_files") or []), "warnings": []}
        except (FileNotFoundError, ValueError):
            c.execute("DELETE FROM catalog_imports WHERE source=? AND source_id=?", (source, sid))   # ERP 里删掉了：重新建
            c.commit()
    # 选品工具 v1.5 起叫 name_zh / name_th（早期草案叫 title_zh / title_th，两种都认）
    title_zh = str(b.get("name_zh") or b.get("title_zh") or "").strip()
    title_th = str(b.get("name_th") or b.get("title_th") or "").strip()
    if not title_zh and not title_th:
        raise CatalogError("中文品名和泰文品名至少要有一个（name_zh / name_th）", "title_required")
    if b.get("license_verified") is not True:
        raise CatalogError("这个产品的许可还没有人工核验可商用（license_verified 不是 true），ERP 不建档", "license_not_verified")
    cat = _find_category(b.get("category"))
    if not cat:
        raise CatalogError(f"类目「{b.get('category') or ''}」在 ERP 里没有（取值要来自 GET /api/v1/categories）", "invalid_category")
    mat_in = str(b.get("material") or "PLA").strip()
    material = MATERIALS.get(mat_in.upper()) or MATERIALS.get(mat_in)
    if not material:
        raise CatalogError(f"材料「{mat_in}」不对（PLA / PETG / TPU / ABS / ASA / 树脂 / 其他）", "invalid_field")
    for k, typ in (("images", list), ("files", list), ("tags", list), ("print_profiles", list)):
        if b.get(k) is not None and not isinstance(b.get(k), typ):
            raise CatalogError(f"{k} 必须是数组", "invalid_field")
    try:
        grams = float(b.get("filament_grams") or 0)
        minutes = float(b.get("print_minutes") or 0)
    except (TypeError, ValueError):
        raise CatalogError("filament_grams / print_minutes 要是数字", "invalid_field")
    images = sorted([x for x in (b.get("images") or []) if isinstance(x, dict) and x.get("url")],
                    key=lambda x: (not x.get("is_cover"), x.get("position") if isinstance(x.get("position"), (int, float)) else 999))
    if len(images) > MAX_IMAGES:
        images = images[:MAX_IMAGES]
    specs, spec_warn = _parse_variants(b.get("variants"))

    from core import codes
    cfg = load_config()
    prefix = (cfg.get("sku_prefix") or "3DP").strip().upper() or "3DP"
    pid = store.new_id(prefix)
    p = store.blank_product(pid)
    p.update(name_zh=title_zh or title_th, material=material, features_zh=str(b.get("description_zh") or "")[:5000],
             keywords=", ".join(str(t) for t in (b.get("tags") or [])[:30]), draft=True)
    p["copy"] = {k: v for k, v in {"title_zh": title_zh, "title_th": title_th,
                                   "description_zh": str(b.get("description_zh") or "")[:20000],
                                   "description_th": text_to_html(str(b.get("description_th") or "")[:20000])}.items() if v}
    lst = _listing(b.get("listing"))
    if lst:
        # 选品工具 2.2 的商品文案（需求单 2026-10-06）：平台标题、卖点、包装内容、搜索词放进 ERP 的文案字段（编辑页能改），原样也存一份
        p["curator_listing"] = lst
        cp = p["copy"]
        for src, dst in (("title_th", "title_th"), ("title_zh", "title_zh"), ("title_th", "title_shopee_th"), ("package_th", "package_content_th")):
            if lst.get(src):
                cp[dst] = lst[src]
        if lst.get("highlights_th"):
            cp["highlights_th"] = lst["highlights_th"]
        kws = [str(x) for x in (lst.get("keywords_th") or []) + (lst.get("keywords_zh") or [])]
        if kws:
            p["keywords"] = ", ".join(dict.fromkeys(kws + [str(t) for t in (b.get("tags") or [])]))[:2000]
        if lst.get("ip_risk"):
            p["ip_risk"] = {"items": lst["ip_risk"], "status": "pending", "at": time.time()}
    p["category"] = {"id": cat["id"], "cat_id": cat["lazada_cat_id"] or "", "status": "manual"}
    if specs:
        # 多规格（尺寸 / 版本 / 套装数量）：每个规格一个变体，放在第二个选项「规格」里；颜色在 ERP 里加，加颜色时按 规格 × 颜色 展开
        from core import specs as _specs
        _specs.build_rows(p, specs)
        _specs.package_from_specs(p)
    else:
        p["variants"][0].update(grams=round(grams, 1) if grams else 0, hours=round(minutes / 60.0, 2) if minutes else 0)
    p["source"] = {"source": source, "source_id": sid, "source_version": str(b.get("source_version") or "")[:20],
                   "title_original": str(b.get("title_original") or "")[:300],
                   "description_original": str(b.get("description_original") or "")[:20000],
                   "description_source_zh": str(b.get("source_description_zh") or "")[:20000],   # 原站描述直译（选品工具 2.2，只作参考）
                   "description_source_th": str(b.get("source_description_th") or "")[:20000],
                   "source_url": str(b.get("source_url") or "")[:500], "platform": str(b.get("platform") or "")[:40],
                   "author": str(b.get("author") or "")[:100], "license_name": str(b.get("license_name") or "")[:100],
                   "license_url": str(b.get("license_url") or "")[:500], "license_verified": True,
                   "reference_price": b.get("reference_price") if isinstance(b.get("reference_price"), dict) else None,
                   "print_profiles": (b.get("print_profiles") or [])[:20], "package_url": str(b.get("package_url") or "")[:500],
                   "updated_at": b.get("updated_at"), "imported_at": time.time(), "key_name": key_name}
    if isinstance(b.get("source_colors"), list):
        p["source_colors"] = [str(x)[:20] for x in b["source_colors"][:20]]
    codes.ensure_skus(cfg, p)
    store.save(p)
    warnings = list(spec_warn)
    try:
        sess = _session()
        raw_dir = store.image_dir(pid, "raw")
        for im in images:
            tmp, ctype = _download(sess, im["url"], raw_dir, MAX_IMG_BYTES, "图片")
            ext = IMG_EXT.get(ctype) or os.path.splitext(str(im["url"]).split("?")[0])[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                os.remove(tmp)
                raise CatalogError(f"图片不是 JPG / PNG：{im['url']}", "image_download_failed", 502)
            name = f"{uuid.uuid4().hex[:10]}{'.jpg' if ext == '.jpeg' else ext}"
            os.replace(tmp, os.path.join(raw_dir, name))
            p.setdefault("images", []).append({"file": name, "raw": name, "processed": False, "url": ""})
        store.save(p)
        # 模型文件：不是必需的，下载失败只提醒
        files_dir = os.path.join(store.product_dir(pid), "source_files")
        got, model_set = [], False
        all_files, seen_url = [], set()
        for f in [x for x in (b.get("files") or []) if isinstance(x, dict) and x.get("url")] + \
                [x for v in specs for x in v["files"]]:
            if f["url"] not in seen_url:
                seen_url.add(f["url"])
                all_files.append(f)
        by_url = {}
        # 规格对应的文件优先当 3D 模型：第 1 个规格的文件排最前
        first_spec = [x["url"] for x in (specs[0]["files"] if specs else [])]
        all_files.sort(key=lambda f: 0 if f["url"] in first_spec else 1)
        for f in all_files[:40]:
            fname = os.path.basename(str(f.get("name") or "file")).replace("/", "_")[:120] or "file"
            try:
                tmp, _ct = _download(sess, f["url"], files_dir, MAX_FILE_BYTES, "模型文件")
            except CatalogError as e:
                warnings.append(str(e))
                continue
            dest = os.path.join(files_dir, fname)
            if os.path.exists(dest):
                dest = os.path.join(files_dir, f"{uuid.uuid4().hex[:6]}_{fname}")
            os.replace(tmp, dest)
            got.append({"name": os.path.basename(dest), "bytes": os.path.getsize(dest), "kind": str(f.get("kind") or "")[:20],
                        "url": f["url"], "orig_name": fname, "added_at": time.time()})
            by_url[f["url"]] = os.path.basename(dest)
            ext = os.path.splitext(fname)[1].lower()
            if not model_set and ext in (".stl", ".3mf") and not fname.lower().endswith(".gcode.3mf"):
                try:
                    from core import filemgr
                    tmp2 = os.path.join(DATA_DIR, "tmp", uuid.uuid4().hex + ext)
                    os.makedirs(os.path.dirname(tmp2), exist_ok=True)
                    shutil.copyfile(dest, tmp2)
                    try:
                        filemgr.set_model(pid, tmp2, fname, key_name or "选品工具")
                    finally:
                        if os.path.exists(tmp2):
                            os.remove(tmp2)
                    model_set = True
                    p = store.load(pid)
                except Exception as e:  # noqa: BLE001  模型读不了不影响建档
                    warnings.append(f"模型文件 {fname} 读不了，没有设为产品 3D 模型：{e}")
        p["source_files"] = got
        if specs:
            model_name = (p.get("model") or {}).get("orig_name")
            for v, sp in zip(p["variants"], specs):
                mine = [by_url[x["url"]] for x in sp["files"] if x["url"] in by_url]
                # 这个规格自己的模型文件；没有就用产品的 3D 模型
                v["model_file"] = mine[0] if mine else None
                v["model_note"] = "" if mine else ("用产品的 3D 模型" + (f"（{model_name}）" if model_name else ""))
        store.save(p)
    except CatalogError:
        _rollback(pid)
        raise
    except Exception as e:  # noqa: BLE001
        _rollback(pid)
        raise CatalogError(f"建档失败：{e}", "invalid", 500)
    c.execute("INSERT OR REPLACE INTO catalog_imports(source, source_id, product_id, created_at, key_name, payload) VALUES(?,?,?,?,?,?)",
              (source, sid, pid, time.time(), key_name, json.dumps({"name_zh": title_zh, "name_th": title_th, "category": b.get("category"),
                                                                    "source_url": b.get("source_url"), "updated_at": b.get("updated_at")},
                                                                   ensure_ascii=False)))
    c.commit()
    db.audit(key_name or "api", "选品工具建产品", pid, f"{p['name_zh']}（{source}#{sid}）")
    _autocomplete(pid, key_name)
    return {"product_code": pid, "created": True, "skus": [v["sku"] for v in p.get("variants", []) if v.get("sku")],
            "images": len(p.get("images") or []), "files": len(p.get("source_files") or []), "warnings": warnings}


def _autocomplete(pid, who=""):
    """选品工具推过来的文案只有泰文 / 中文：后台用 AI 把英文、Shopee 标签、包装内容、变体名称等空着的字段补上（v2.22）。
    没设置 AI 密钥就不做（编辑页可以手动点「补全空着的文案」）。"""
    cfg = load_config()
    if not (cfg.get("ai_api_key") or "").strip():
        return
    from core import ai_copy, bgjobs

    def go():
        p = store.load(pid)
        out = ai_copy.complete_copy(cfg, p, p.get("keyword_plan"))
        p = store.load(pid)              # 期间可能有人改过
        ai_copy.apply_completion(p, out)
        store.save(p)
        return {"ok": True, "fields": list(out)}
    bgjobs.start(go, f"补全文案 {pid}", who or "api", "ai_fill", pid)


def _rollback(pid):
    try:
        store.delete(pid)
    except Exception:  # noqa: BLE001
        pass
    d = os.path.join(store.PRODUCTS_DIR, pid)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)


# ---------------- 系统 → 设置 → 账号与权限：选品工具连接 ----------------
def status():
    cfg = load_config()
    c = db.conn()
    key = (cfg.get("curator_api_key") or "").strip()
    recent = []
    for r in c.execute("SELECT * FROM catalog_imports ORDER BY created_at DESC LIMIT 15"):
        try:
            p = store.load(r["product_id"])
            name, draft, nsku = p.get("name_zh"), bool(p.get("draft")), len([v for v in p.get("variants", []) if v.get("sku")])
        except (FileNotFoundError, ValueError):
            name, draft, nsku = "（ERP 里已删除）", False, 0
        recent.append({"product_id": r["product_id"], "source_id": r["source_id"], "name": name, "draft": draft,
                       "skus": nsku, "created_at": r["created_at"], "key_name": r["key_name"]})
    last = db.kv_get("curator_last_test")
    return {"base_url": (cfg.get("curator_base_url") or "").strip(), "key_set": bool(key),
            "key_mask": (key[:4] + "…" + key[-4:]) if len(key) > 10 else ("已填" if key else ""),
            "last_test": json.loads(last) if last else None, "recent": recent,
            "imported": c.execute("SELECT COUNT(*) FROM catalog_imports").fetchone()[0]}


def save(base_url=None, api_key=None):
    from core.config import save_config
    upd = {}
    if base_url is not None:
        u = str(base_url).strip().rstrip("/")
        if u and not u.startswith(("http://", "https://")):
            u = "http://" + u
        upd["curator_base_url"] = u
    if api_key not in (None, "", "******"):
        upd["curator_api_key"] = str(api_key).strip()
    if upd:
        save_config(upd)
    return status()


def test(base_url=None, api_key=None):
    """测试 ERP → 选品工具：① 地址通不通（ping）② 密钥对不对（读选品记录列表）。"""
    import requests
    cfg = load_config()
    base = (str(base_url).strip().rstrip("/") if base_url else (cfg.get("curator_base_url") or "").strip().rstrip("/"))
    key = api_key if api_key not in (None, "", "******") else (cfg.get("curator_api_key") or "").strip()
    out = {"ok": False, "base_url": base, "steps": [], "version": None, "ts": time.time()}
    if not base:
        out["steps"].append({"ok": False, "text": "还没填选品工具地址"})
        return out
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    h = {"Authorization": "Bearer " + key} if key else {}
    try:
        r = requests.get(base + "/api/v1/ping", headers=h, timeout=8)
        j = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
        if r.status_code == 200:
            out["version"] = j.get("version")
            out["steps"].append({"ok": True, "text": f"地址能连上（选品工具 {j.get('version') or ''}）".replace(" ）", "）")})
        else:
            out["steps"].append({"ok": False, "text": f"地址能连上，但返回 HTTP {r.status_code}，可能不是选品工具的地址"})
    except Exception as e:  # noqa: BLE001
        out["steps"].append({"ok": False, "text": f"连不上 {base}：{str(e)[:120]}。检查地址、端口，选品工具有没有在运行"})
        db.kv_set("curator_last_test", json.dumps(out, ensure_ascii=False))
        return out
    if not key:
        out["steps"].append({"ok": False, "text": "还没填选品工具的密钥（ERP 下载图片要用）"})
    else:
        try:
            r = requests.get(base + "/api/v1/catalog", params={"limit": 1}, headers=h, timeout=8)
            if r.status_code in (401, 403):
                out["steps"].append({"ok": False, "text": "密钥不对：选品工具拒绝了（请到选品工具「设置 → ERP 对接」重新复制「ERP 访问本系统的密钥」）"})
            elif r.status_code == 200:
                out["steps"].append({"ok": True, "text": "密钥正确，可以下载图片和模型文件"})
            else:
                out["steps"].append({"ok": False, "text": f"用密钥读选品记录时返回 HTTP {r.status_code}"})
        except Exception as e:  # noqa: BLE001
            out["steps"].append({"ok": False, "text": f"用密钥读选品记录失败：{str(e)[:120]}"})
    out["ok"] = all(s["ok"] for s in out["steps"])
    db.kv_set("curator_last_test", json.dumps(out, ensure_ascii=False))
    return out


# ---------------- 补传模型文件（选品工具 1.9.2 需求单，ERP 2.12.2） ----------------
MODEL_EXT = (".stl", ".3mf")


def _own(p, b, key_name, c, why):
    """检查这个产品是不是这条选品记录建的；2.12 以前手动建档的，第一次对接时把来源对上。"""
    source = str(b.get("source") or "").strip()[:40]
    sid = str(b.get("source_id") if b.get("source_id") is not None else "").strip()[:60]
    if b.get("product_code") and str(b["product_code"]).strip().upper() != p["id"].upper():
        raise CatalogError("product_code 和地址里的产品编号不一样", "invalid_field")
    if not source or not sid:
        raise CatalogError("缺少 source / source_id", "invalid_field")
    src = p.get("source") or {}
    if src:
        if str(src.get("source")) != source or str(src.get("source_id")) != sid:
            raise CatalogError(f"产品 {p['id']} 不是这条选品记录建的（ERP 记录的是 {src.get('source')} #{src.get('source_id')}）", "invalid_field")
    else:
        other = c.execute("SELECT product_id FROM catalog_imports WHERE source=? AND source_id=?", (source, sid)).fetchone()
        if other and other["product_id"] != p["id"]:
            raise CatalogError(f"选品记录 #{sid} 在 ERP 里对应的是 {other['product_id']}，不是 {p['id']}", "invalid_field")
        p["source"] = {"source": source, "source_id": sid, "linked_at": time.time(), "linked_by": key_name, "linked_manually": True}
        c.execute("INSERT OR IGNORE INTO catalog_imports(source, source_id, product_id, created_at, key_name, payload) VALUES(?,?,?,?,?,?)",
                  (source, sid, p["id"], time.time(), key_name, json.dumps({"linked": why}, ensure_ascii=False)))


def sync_variants(code, b, key_name=""):
    """选品工具同步规格（对接规范 4.3.5，PUT .../variants）：传完整列表，按 spec_id 对比。"""
    from core import specs as _specs
    if not isinstance(b, dict):
        raise CatalogError("请求体必须是 JSON 对象", "invalid_field")
    try:
        p = store.load(store.safe_id(code))
    except (FileNotFoundError, ValueError):
        raise CatalogError(f"ERP 里没有产品 {code}", "not_found", 404)
    if not isinstance(b.get("variants"), list):
        raise CatalogError("variants 必须是数组（传全部现有规格）", "invalid_field")
    c = db.conn()
    _own(p, b, key_name, c, "同步规格时对上")
    try:
        new, warnings = _specs.parse(b["variants"])
    except _specs.SpecError as e:
        raise CatalogError(str(e), "invalid_field")
    if isinstance(b.get("source_colors"), list):
        p["source_colors"] = [str(x)[:20] for x in b["source_colors"][:20]]
    res = _specs.sync(p, new)
    _specs.package_from_specs(p)
    from core import codes
    codes.ensure_skus(load_config(), p)
    if res["added"] or res["updated"] or res["removed"] or res["removed_pending"]:
        store.bump_rev(p, key_name or "选品工具")
        db.audit(key_name or "api", "选品工具同步规格", p["id"],
                 "；".join(f"{k} {'、'.join(v)}" for k, v in (("新增", res["added"]), ("修改", res["updated"]), ("删除", res["removed"]),
                                                            ("待确认删除", res["removed_pending"])) if v))
    store.save(p)
    c.commit()
    return {**res, "skus": [v["sku"] for v in p.get("variants", []) if v.get("sku")], "warnings": warnings}


def add_files(code, b, key_name=""):
    """给已建档的产品补传模型文件。返回 {added, skipped, warnings, files}。
    防重复：同一产品里 url 相同，或「原文件名 + 字节数」相同的跳过。
    有 variant 的挂到对应规格（还没有规格模型时设为这个规格的模型）；产品还没有 3D 模型时，第一个 STL / 3MF 设为产品模型。"""
    if not isinstance(b, dict):
        raise CatalogError("请求体必须是 JSON 对象", "invalid_field")
    try:
        p = store.load(store.safe_id(code))
    except (FileNotFoundError, ValueError):
        raise CatalogError(f"ERP 里没有产品 {code}", "not_found", 404)
    c = db.conn()
    _own(p, b, key_name, c, "补传模型文件时对上")
    files = b.get("files")
    if not isinstance(files, list) or not files:
        raise CatalogError("files 必须是非空数组", "invalid_field")
    have = list(p.get("source_files") or [])
    have_urls = {x.get("url") for x in have if x.get("url")}
    have_nb = {((x.get("orig_name") or x.get("name") or "").lower(), int(x.get("bytes") or 0)) for x in have}
    specs = {(v.get("opt2_zh") or "").strip(): v for v in p.get("variants", []) if (v.get("opt2_zh") or "").strip()}
    sess = _session()
    files_dir = os.path.join(store.product_dir(p["id"]), "source_files")
    added, skipped, warnings, new_rows = 0, 0, [], []
    for f in [x for x in files if isinstance(x, dict) and x.get("url")][:20]:
        fname = os.path.basename(str(f.get("name") or "file")).replace("/", "_")[:120] or "file"
        nb = (fname.lower(), int(f.get("bytes") or 0))
        if f["url"] in have_urls or (nb[1] and nb in have_nb):
            skipped += 1
            continue
        try:
            tmp, _ct = _download(sess, f["url"], files_dir, MAX_FILE_BYTES, "模型文件")
        except CatalogError as e:
            warnings.append(f"{fname}：{e}")
            continue
        size = os.path.getsize(tmp)
        if (fname.lower(), size) in have_nb:     # 选品工具没给字节数，下载下来才知道是重复的
            os.remove(tmp)
            skipped += 1
            continue
        dest = os.path.join(files_dir, fname)
        if os.path.exists(dest):
            dest = os.path.join(files_dir, f"{uuid.uuid4().hex[:6]}_{fname}")
        os.replace(tmp, dest)
        row = {"name": os.path.basename(dest), "bytes": size, "kind": str(f.get("kind") or "")[:20], "url": f["url"],
               "orig_name": fname, "variant": str(f.get("variant") or "").strip()[:40], "added_at": time.time(), "added_by": key_name}
        have.append(row)
        new_rows.append(row)
        have_urls.add(f["url"])
        have_nb.add((fname.lower(), size))
        added += 1
    p["source_files"] = have
    # 挂到规格
    for row in new_rows:
        if not row["variant"]:
            continue
        hit = [v for v in p.get("variants", []) if (v.get("opt2_zh") or "").strip() == row["variant"]]
        if not hit:
            warnings.append(f"{row['orig_name']}：ERP 里没有规格「{row['variant']}」，已作为整个产品的文件保存")
            continue
        for v in hit:
            if not v.get("model_file") and os.path.splitext(row["name"])[1].lower() in MODEL_EXT:
                v["model_file"] = row["name"]
                v["model_note"] = ""
    store.save(p)
    # 产品还没有 3D 模型：第一个 STL / 3MF 设为产品模型（不改已有的）
    if not p.get("model"):
        for row in new_rows:
            ext = os.path.splitext(row["name"])[1].lower()
            if ext not in MODEL_EXT or row["name"].lower().endswith(".gcode.3mf"):
                continue
            try:
                from core import filemgr
                tmp2 = os.path.join(DATA_DIR, "tmp", uuid.uuid4().hex + ext)
                os.makedirs(os.path.dirname(tmp2), exist_ok=True)
                shutil.copyfile(os.path.join(files_dir, row["name"]), tmp2)
                try:
                    filemgr.set_model(p["id"], tmp2, row["orig_name"], key_name or "选品工具")
                finally:
                    if os.path.exists(tmp2):
                        os.remove(tmp2)
                break
            except Exception as e:  # noqa: BLE001
                warnings.append(f"{row['orig_name']} 读不了，没有设为产品 3D 模型：{e}")
    c.commit()
    if added:
        db.audit(key_name or "api", "选品工具补传模型文件", p["id"], "、".join(r["orig_name"] for r in new_rows))
    return {"added": added, "skipped": skipped, "warnings": warnings,
            "files": [{"name": r["name"], "variant": r["variant"], "bytes": r["bytes"]} for r in new_rows]}
