"""搜索优化模块的接口（v2.30 从 web/products.py 搬过来）。"""
from flask import Blueprint

from web.common import *  # noqa: F401,F403
from modules.seo import logic as seo

bp = Blueprint("m_seo", __name__)
PREFIXES = ["/api/products/seo-"]                       # 批量优化、待确认列表
PATTERNS = [r"^/api/products/[^/]+/seo(-[a-z]+)?$"]     # 每个产品的搜索分 / 优化 / 撤销


# ---------------- 搜索优化（v2.23） ----------------
@bp.post("/api/products/<pid>/seo")
def seo_score(pid):
    """搜索分。body 可以带编辑页里还没保存的产品。"""
    p = request.get_json(silent=True) or store.load(pid)
    out = seo.score(p)
    try:
        sp = store.load(pid)
        out["proposal"] = _prop_view(sp) if sp.get("copy_proposal") else None
        out["wait_days"] = seo.recently_changed(sp)
    except FileNotFoundError:
        out["proposal"] = None
    return jsonify(out)


def _prop_view(p):
    pr = p.get("copy_proposal") or {}
    c = p.get("copy") or {}
    rows = []
    for k, v in (pr.get("fields") or {}).items():
        if k in ("title_zh", "description_zh"):
            continue
        old = c.get(k)
        if k == "options_th":
            old = {x: (c.get("options_th") or {}).get(x, "") for x in v}
        if old == v:
            continue
        rows.append({"key": k, "label": seo.LABELS.get(k, k), "old": old or "", "new": v,
                     "zh": pr["fields"].get("title_zh") if k == "title_th" else pr["fields"].get("description_zh") if k == "description_th" else ""})
    rows.append({"key": "keyword_plan", "label": seo.LABELS["keyword_plan"], "old": "", "new": seo_plan_text(pr.get("plan") or {}), "zh": (pr.get("plan") or {}).get("notes_zh", "")})
    return {"rows": rows, "score_before": pr.get("score_before"), "score_after": pr.get("score_after"), "at": pr.get("at"),
            "by": pr.get("by"), "wait_days": pr.get("wait_days") or 0, "id": p["id"], "name_zh": p.get("name_zh", "")}


def seo_plan_text(plan):
    from core import keywords
    out = []
    for k, name in keywords.GROUPS:
        if plan.get(k):
            out.append(f"{name}：" + "、".join(plan[k]))
    return "\n".join(out)


@bp.post("/api/products/<pid>/seo-propose")
def seo_propose(pid):
    """AI 搜索优化：从买家角度重新找词 + 重写标题 / 详情 / 标签…，存成「待确认」，不直接改。"""
    body = request.get_json(silent=True) or {}

    def go():
        p = store.load(pid)
        if body.get("product") and body["product"].get("id") == pid:      # 编辑页没保存的产品资料也用上
            for k in ("name_zh", "features_zh", "keywords", "material", "size_text", "variants", "variation1_name_zh", "variation2_name_zh"):
                if k in body["product"]:
                    p[k] = body["product"][k]
        try:
            seo.propose(load_config(), p, _cat_name(p), _uname())
        except ai_copy.AIError as e:
            return err(str(e))
        sp = store.load(pid)
        sp["copy_proposal"] = p["copy_proposal"]
        store.save(sp)
        return jsonify(_prop_view(sp))
    return maybe_async(f"搜索优化 {pid}", go, "ai", pid)


@bp.post("/api/products/<pid>/seo-optimize")
def seo_optimize(pid):
    """v2.24：一键 AI 搜索优化，直接生效（关键词扩展已合并进来）。可以撤销。"""
    body = request.get_json(silent=True) or {}

    def go():
        p = store.load(pid)
        if body.get("product") and body["product"].get("id") == pid:      # 编辑页没保存的资料也用上
            for k in ("name_zh", "features_zh", "keywords", "material", "size_text", "variants", "variation1_name_zh", "variation2_name_zh"):
                if k in body["product"]:
                    p[k] = body["product"][k]
            if (body["product"].get("keyword_plan") or {}).get("custom"):
                p.setdefault("keyword_plan", {})["custom"] = body["product"]["keyword_plan"]["custom"]
        try:
            r = seo.optimize(load_config(), p, _cat_name(p), _uname())
        except ai_copy.AIError as e:
            return err(str(e))
        try:                                    # 优化完马上让 AI 再打分、给建议（失败不影响优化结果）
            p["seo_review"] = seo.review(load_config(), p)
        except Exception:  # noqa: BLE001
            p.pop("seo_review", None)
        store.bump_rev(p, _uname())
        store.save(p)
        from core import db as _db
        _db.audit(_uname(), "AI 搜索优化", pid, f"搜索分 {r['score_before']} → {r['score_after']}")
        return jsonify({**r, "product": p})
    return maybe_async(f"搜索优化 {pid}", go, "ai", pid)


@bp.post("/api/products/<pid>/seo-review")
def seo_review(pid):
    """v2.24：AI 打分和具体建议（按编辑页上现在的内容，可以带没保存的产品）。结果存在产品上。"""
    body = request.get_json(silent=True) or {}

    def go():
        p = body if body.get("id") == pid else store.load(pid)
        try:
            rv = seo.review(load_config(), p)
        except ai_copy.AIError as e:
            return err(str(e))
        sp = store.load(pid)
        sp["seo_review"] = rv
        store.save(sp)
        return jsonify(rv)
    return maybe_async(f"AI 打分 {pid}", go, "ai", pid)


@bp.post("/api/products/<pid>/seo-undo")
def seo_undo(pid):
    p = store.load(pid)
    try:
        seo.undo(p)
    except ValueError as e:
        return err(str(e))
    store.bump_rev(p, _uname())
    store.save(p)
    return jsonify({"ok": True, "product": p})


@bp.post("/api/products/<pid>/seo-apply")
def seo_apply(pid):
    """确认优化：{fields: [...]}（空 = 全部），或 {discard: true} 不要这次的优化。"""
    b = request.get_json(silent=True) or {}
    p = store.load(pid)
    if b.get("discard"):
        p.pop("copy_proposal", None)
        store.save(p)
        return jsonify({"ok": True, "product": p})
    try:
        changed = seo.apply(p, b.get("fields") or None, _uname())
    except ValueError as e:
        return err(str(e))
    store.bump_rev(p, _uname())
    store.save(p)
    from core import db as _db
    _db.audit(_uname(), "确认搜索优化", pid, "、".join(seo.LABELS.get(k, k) for k in changed))
    return jsonify({"ok": True, "changed": changed, "product": p, **seo.score(p)})


@bp.get("/api/products/seo-proposals")
def seo_proposals():
    """所有「待确认的优化」（批量优化后在这里逐个确认）。"""
    out = []
    for it in store.list_products():
        try:
            p = store.load(it["id"])
        except Exception:  # noqa: BLE001
            continue
        if p.get("copy_proposal"):
            out.append(_prop_view(p))
    return jsonify({"proposals": out})


@bp.post("/api/products/seo-batch")
def seo_batch():
    """批量搜索优化：{ids: [...]}（空 = 搜索分低于 {below}（默认 80）的全部）。直接生效（v2.24），后台做。"""
    b = request.get_json(silent=True) or {}
    ids, below = b.get("ids") or [], int(b.get("below") or 80)
    user = _uname()

    def go():
        from core import bgjobs
        cfg = load_config()
        todo, skipped = [], []
        for it in store.list_products():
            pid = it["id"]
            if ids and pid not in ids:
                continue
            try:
                p = store.load(pid)
            except Exception:  # noqa: BLE001
                continue
            if not (p.get("name_zh") or (p.get("copy") or {}).get("title_th")):
                continue
            if not ids and seo.quick_score(p) is not None and seo.quick_score(p) >= below:
                continue
            todo.append(pid)
        done, failed = [], []
        for i, pid in enumerate(todo):
            bgjobs.note(stage=f"{i + 1}/{len(todo)}", where=pid)
            try:
                p = store.load(pid)
                r = seo.optimize(cfg, p, _cat_name(p), user)       # v2.24：直接生效（可以在编辑页撤销）
                store.bump_rev(p, user)
                store.save(p)
                done.append(pid)
                if r["kept_titles"]:
                    skipped.append(pid)
            except Exception as e:  # noqa: BLE001  一个失败不影响其他
                failed.append({"id": pid, "error": str(e)[:200]})
        return jsonify({"total": len(todo), "done": done, "failed": failed, "skipped": skipped})
    return maybe_async("批量搜索优化", go, "ai_seo")
