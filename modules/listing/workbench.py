"""上架工作台（v2.43）：每个产品「缺什么」和怎么修、原地修（确认类目 / 属性 / 包裹尺寸）、批量 AI 补齐。

issues(pid, platform)   上架检查的红色 / 黄色项，每条带 fix：
                          ai          AI 能补（选类目、填属性、补文案）→ ai_fill
                          confirm_cat AI 选的类目要确认 → fix(pid, "confirm_cat")（同时给出类目名）
                          confirm_attr AI 填的属性要确认 → fix(pid, "confirm_attr")（同时给出属性名和值）
                          confirm_pkg 包裹尺寸是估算的 → fix(pid, "confirm_pkg")（同时给出尺寸）
                          confirm_phys v2.55.1 实物数据（尺寸 / 净重 / 包裹尺寸 / 包裹重量）没确认 → 原地看、改（set_phys）、确认；
                                      confirm_phys_batch(ids) 批量确认（有红色问题 / 缺值的跳过）
                          edit        要人工改（打开编辑页）
fix(pid, action, user)  原地修
ai_fill(ids, platform, user)  选类目、填属性、补空着的文案（后台任务，进任务中心）
"""
import time

from core import ai_copy, attributes, bgjobs, categories, db, store
from core.config import load_config

AI_HINTS = ("还没有选择 Lazada 类目", "类目属性还没填写", "必填，还没填写", "必填，请补充", "没有英文标题", "没有包装内容",
            "没有 Shopee 标签", "没有泰文详情", "Shopee 类目", "还没有泰文")


def _checks(cfg, p, platform):
    from web.common import _check, _check_shopee
    return _check_shopee(cfg, p) if platform == "shopee" else _check(cfg, p)


def _fix_of(text):
    if "AI 对类目不确定" in text:
        return "confirm_cat"
    if "AI 不确定，请确认" in text:
        return "confirm_attr"
    if "实物数据" in text:
        return "confirm_phys"
    if "包裹尺寸是 AI 估算的" in text:
        return "confirm_pkg"
    if "上传图床" in text:
        return "host"
    if any(h in text for h in AI_HINTS):
        return "ai"
    return "edit"


def issues(pid, platform="lazada"):
    cfg = load_config()
    p = store.load(pid)
    errs, warns = _checks(cfg, p, platform)
    cat = (p.get("category") or {})
    labels = {}
    tpl = categories.get(cat.get("id"))
    if tpl:
        labels = {f["key"]: f.get("label") or f["key"] for f in tpl["fields"]}
    return {
        "id": pid, "platform": platform,
        "errors": [{"text": e, "fix": _fix_of(e)} for e in errs],
        "warnings": [{"text": w, "fix": _fix_of(w)} for w in warns],
        "category": categories.display_name(tpl["cat_id"], tpl["sheet"]) if tpl else "",
        "check_attrs": [{"key": k, "label": labels.get(k, k), "value": a.get("value")}
                        for k, a in (p.get("attributes") or {}).items() if a.get("status") == "check"],
        "package": p.get("package") or {},
        "physical": _phys_rows(p),
    }


def _phys_rows(p):
    from core import physical
    out = []
    for s, r in physical.rows(p).items():
        out.append({"spec": s, "ok": r["ok"], "missing": r["missing"], "box": r["box"], "qty": r["qty"],
                    "checks": r["checks"], **{f: {k: r[f][k] for k in ("v", "src", "ok", "by", "at")} for f in physical.FIELDS}})
    return out


def fix(pid, action, user="", data=None):
    from core import physical
    data = data or {}
    p = store.load(pid)
    if action == "confirm_cat":
        if not (p.get("category") or {}).get("id"):
            raise ValueError("还没有类目")
        p["category"]["status"] = "manual"
        try:
            attributes.remember_manual(load_config(), p, categories.get(p["category"]["id"]))
        except Exception:  # noqa: BLE001  记不住也不影响确认
            pass
    elif action == "confirm_attr":
        for a in (p.get("attributes") or {}).values():
            if a.get("status") == "check":
                a["status"] = "manual"
    elif action == "confirm_pkg":
        p["package_status"] = "manual"
    elif action == "confirm_phys":          # 一个产品（或一个规格）的实物数据全部确认
        keys = physical.spec_keys(p)
        specs = [data["spec"]] if data.get("spec") is not None and data.get("spec") in keys else keys
        for s in specs:
            physical.confirm(p, s, data.get("fields"), user)
    elif action == "set_phys":              # 原地改一项（人工写入 = 已确认）
        spec = (data.get("spec") or "").strip()
        if spec not in physical.spec_keys(p):
            raise ValueError("没有这个规格（刷新一下）")
        physical.set_item(p, spec, data.get("field"), data.get("value"), "manual", user, ok=True)
    else:
        raise ValueError("不支持的操作")
    store.save(p)
    db.audit(user, "上架工作台确认", pid, action)
    return issues(pid)


def confirm_phys_batch(ids, user=""):
    """批量确认实物数据：每个规格 4 项都有值、没有红色问题的才确认；其它跳过并说明原因。"""
    from core import physical
    done, skipped = [], []
    for pid in ids:
        try:
            p = store.load(pid)
        except FileNotFoundError:
            skipped.append({"id": pid, "reason": "产品不存在"})
            continue
        bad = []
        for s, r in physical.rows(p).items():
            empty = [physical.FIELD_ZH[f] for f in physical.FIELDS if r[f]["v"] in (None, 0, [])]
            reds = [c["zh"] for c in r["checks"] if c["level"] == "red"]
            if empty or reds:
                bad.append(f"{s or '默认'}：" + "；".join((["没有" + "、".join(empty)] if empty else []) + reds))
                continue
            physical.confirm(p, s, None, user)
        store.save(p)
        if bad:
            skipped.append({"id": pid, "reason": " / ".join(bad)})
        else:
            done.append(pid)
    db.audit(user, "上架工作台批量确认实物数据", f"{len(done)} 个", ", ".join(done)[:300])
    return {"ok": True, "done": done, "skipped": skipped}


def _fill_one(cfg, p, platform):
    """一个产品：没类目就让 AI 选、属性没填就填、空着的文案补上。返回做了什么。"""
    from web.common import _apply_fill
    did = []
    cat = p.get("category") or {}
    if platform != "shopee":
        if not cat.get("id"):
            m = attributes.match_category(cfg, p)
            p["category"] = {**cat, **m}
            did.append("类目")
        tpl = categories.get((p.get("category") or {}).get("id"))
        if tpl and (did or not p.get("attributes") or any(a.get("status") == "missing" for a in p["attributes"].values())):
            p["category"]["cat_id"] = tpl["cat_id"]
            _apply_fill(cfg, p, tpl)
            did.append("属性")
    elif not (p.get("shopee_category") or {}).get("id"):
        try:
            m = attributes.match_shopee_category(cfg, p)
            if m:
                p["shopee_category"] = {**(p.get("shopee_category") or {}), **m}
                did.append("Shopee 类目")
        except Exception:  # noqa: BLE001  Shopee 类目匹配失败：不影响补文案
            pass
    miss, opts = ai_copy.missing_copy(p)
    if miss or opts:
        out = ai_copy.complete_copy(cfg, p, p.get("keyword_plan"))
        ai_copy.apply_completion(p, out)
        did.append("文案")
    return did


def ai_fill(ids, platform="lazada", user=""):
    cfg = load_config()
    done, failed = [], []
    for i, pid in enumerate(ids):
        bgjobs.note(stage=f"{i + 1}/{len(ids)}")
        try:
            p = store.load(pid)
            did = _fill_one(cfg, p, platform)
            if did:
                p["updated_at"] = time.time()
                store.save(p)
            done.append({"id": pid, "did": did})
        except ai_copy.AIError as e:
            failed.append({"id": pid, "error": str(e)[:300]})
            if "密钥" in str(e) or "key" in str(e).lower():
                break
        except Exception as e:  # noqa: BLE001  一个失败不影响别的
            failed.append({"id": pid, "error": str(e)[:300]})
    db.audit(user, "上架工作台 AI 补齐", f"{len(done)} 个", ", ".join(d["id"] for d in done)[:300])
    return {"ok": True, "done": done, "failed": failed}
