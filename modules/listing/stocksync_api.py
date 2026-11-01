"""库存同步的接口（v2.53）：对照总表、行内改、批量、锁定、规则、同步记录、待导出。路由挂在 listing 模块的 bp 上（api.py 末尾导入本文件）。"""
from web.common import *  # noqa: F401,F403

from . import stocksync
from .api import bp


def _shaped(data, f):
    """按筛选条件过滤：kpi = 待同步 pending / 失败 failed / 对不上 mismatch / 快卖完 low / 已超卖 oversold / 已锁定 locked；q 搜索；shop 店铺。"""
    rows = []
    q = (f.get("q") or "").strip().lower()
    k = f.get("kpi") or ""
    shop = f.get("shop")
    for r in data["rows"]:
        if q and q not in f"{r['sku']} {r['product_id']} {r['name']} {r['color']} {r['spec']}".lower():
            continue
        cells = {sid: c for sid, c in r["cells"].items() if not shop or str(sid) == str(shop)}
        if not cells:
            continue
        if (k == "low" and not r["low"]) or (k == "oversold" and not r["oversold"]):
            continue
        if k in ("pending", "failed", "locked") and not any(c["status"] == k for c in cells.values()):
            continue
        if k == "mismatch" and not any(c["mismatch"] for c in cells.values()):
            continue
        rows.append({**r, "cells": cells})
    return rows


@bp.get("/api/stocksync/matrix")
def ss_matrix():
    data = stocksync.compute()
    rows = _shaped(data, request.args)
    total, rows = len(rows), rows[:int(request.args.get("limit") or 400)]
    return jsonify({"ok": True, "shops": data["shops"], "rows": rows, "total": total, "kpi": data["kpi"], "settings": data["settings"],
                    "pull": {str(k): v for k, v in stocksync.PULL_INFO.items()}, "trend": stocksync.trend(7)})


def _cells(b):
    return [{"sku": str(c.get("sku") or ""), "shop_id": c.get("shop_id")} for c in b.get("cells") or [] if c.get("sku")]


@bp.post("/api/stocksync/edit")
def ss_edit():
    b = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify({"ok": True, **stocksync.edit_qty(b.get("sku") or "", b.get("shop_id"), b.get("qty"), _uname(), bool(b.get("lock")))})
    except (ValueError, TypeError, RuntimeError) as e:
        return err(str(e))


@bp.post("/api/stocksync/lock")
def ss_lock():
    b = request.get_json(force=True, silent=True) or {}
    qty = b.get("qty")
    try:
        return jsonify({"ok": True, **stocksync.set_lock(b.get("sku") or "", b.get("shop_id"), None if qty in (None, "") else int(qty), _uname())})
    except (ValueError, RuntimeError) as e:
        return err(str(e))


@bp.post("/api/stocksync/bulk")
def ss_bulk():
    b = request.get_json(force=True, silent=True) or {}
    cells = _cells(b)
    if not cells:
        return err("请先勾选")
    try:
        return jsonify({"ok": True, **stocksync.bulk(b.get("action") or "", cells, b.get("params") or {}, _uname())})
    except (ValueError, RuntimeError) as e:
        return err(str(e))


@bp.post("/api/stocksync/push-all")
def ss_push_all():
    user = _uname()
    return maybe_async("库存全部重推", lambda: jsonify({"ok": True, **stocksync.force_all(user)}), "ss_push")


@bp.post("/api/stocksync/check")
def ss_check():
    user = _uname()
    return maybe_async("库存同步检查", lambda: jsonify({"ok": True, **stocksync.run_check(user)}), "ss_push")


@bp.post("/api/stocksync/retry")
def ss_retry():
    b = request.get_json(force=True, silent=True) or {}
    return jsonify({"ok": True, **stocksync.retry_failed(_uname(), b.get("ids") or None)})


@bp.get("/api/stocksync/rules")
def ss_rules():
    a = request.args
    return jsonify({"ok": True, "rule": stocksync.get_rule(a.get("scope") or "shop", a.get("key") or "", a.get("shop_id") or 0),
                    "defaults": stocksync.settings()})


@bp.post("/api/stocksync/rules")
def ss_rules_save():
    b = request.get_json(force=True, silent=True) or {}
    try:
        rule = stocksync.set_rule(b.get("scope") or "", b.get("key") or "", b.get("shop_id") or 0, b.get("data") or {}, _uname())
    except ValueError as e:
        return err(str(e))
    stocksync.reset_cache()
    skus = [b["key"]] if b.get("scope") == "sku" else None
    res = stocksync.sync_pending("rule", _uname(), skus=skus, explicit=bool(skus))        # 自动推送没开时，只有改单个 SKU 的规则才马上推
    return jsonify({"ok": True, "rule": rule, "sync": {k: res[k] for k in ("pushed", "failed", "skipped")}})


@bp.get("/api/stocksync/log")
def ss_log():
    a = request.args
    return jsonify({"ok": True, "items": stocksync.log_list(a.get("sku") or "", a.get("shop") or None, a.get("reason") or "", a.get("result") or "",
                                                           int(a.get("days") or 30), int(a.get("limit") or 200))})


@bp.get("/api/stocksync/export-list")
def ss_export_list():
    return jsonify({"ok": True, "items": stocksync.export_list(request.args.get("shop") or 0)})


@bp.post("/api/stocksync/export")
def ss_export():
    b = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify({"ok": True, **stocksync.export_sheet(b.get("shop_id"), b.get("skus") or None)})
    except ValueError as e:
        return err(str(e))


@bp.post("/api/stocksync/uploaded")
def ss_uploaded():
    b = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify({"ok": True, **stocksync.mark_uploaded(b.get("shop_id"), b.get("skus") or None, _uname())})
    except ValueError as e:
        return err(str(e))
