"""运营分析模块交给「今日待办」的条目（core/todo.py）：亏本订单、售价低于最低价、商品阶段（审核不通过 / 该再测 / 建议下架）、
货到付款拒收率偏高、Lazada 差评没回复、新的退货退款申请、店铺表现不达标、接口出错（没权限等）。"""
import hashlib
import time

from core.config import load_config


def _f(cfg, k, d):
    try:
        return float(cfg.get(k) if cfg.get(k) not in (None, "") else d)
    except (TypeError, ValueError):
        return d


def provide(add):
    cfg = load_config()
    from . import dash, lazada, lifecycle
    day = time.strftime("%Y-%m-%d")
    # 亏本订单（近 3 天）
    for o in dash.loss_orders(dash.profits(dash.day_start(2), cfg=cfg)):
        plat = (o["platform"] or "").capitalize()
        est = "（平台费是按扣点估算的）" if o["fee_estimated"] else ""
        add(f"loss:{o['id']}", "利润", "warn", f"亏本订单：{plat} {o['order_no']}", f"利润 ฿{o['profit']:,.2f}{est}", "ops_dash", "owner",
            alert=f"💸 亏本订单：{plat} {o['order_no']} 利润 {o['profit']:,.2f} 铢{est}",
            th=(f"ออเดอร์ขาดทุน: {plat} {o['order_no']}", f"กำไร ฿{o['profit']:,.2f}" + (" (ค่าธรรมเนียมเป็นการประมาณ)" if est else "")))
    # 售价低于最低价
    for p in dash.pricing_issues(cfg):
        where = "、".join(f"{x['platform'].capitalize()} ฿{x['price']:g}" for x in p["platform_prices"])
        cur = f"ERP ฿{p['price']:g}" if p["erp_low"] else where
        key = f"floor:{p['sku']}:{p['price']}:{where}"
        add(key, "耗材与价格", "bad", f"售价低于最低价：{p['sku']}", f"现价 {cur} / 最低 ฿{p['floor_price']:g}", "ops_life", "owner",
            alert=f"🏷️ 售价低于最低价：{p['sku']} 现价 {cur}，最低 ฿{p['floor_price']:g}",
            th=(f"ราคาต่ำกว่าราคาขั้นต่ำ: {p['sku']}", f"ราคาตอนนี้ {cur} / ขั้นต่ำ ฿{p['floor_price']:g}"))
    # 商品阶段
    for r in lifecycle.board(cfg)["rows"]:
        if r["stage"] not in ("rejected", "retest", "delist", "erp_off"):
            continue
        plat = r["platform"].capitalize()
        icon = {"rejected": "🚫", "delist": "🗑️", "retest": "🔁", "erp_off": "⚠️"}[r["stage"]]
        add(f"stage:{r['sku']}:{r['platform']}:{r['stage']}", "商品", "bad" if r["stage"] in ("rejected", "delist") else "warn",
            f"{r['stage_label']}：{r['sku']}（{plat}）", r["action"], "ops_life", "owner,listing",
            alert=f"{icon} {r['stage_label']}：{r['sku']}（{plat}）→ {r['action']}" if r["stage"] in ("rejected", "delist") else None,
            th=(f"{r['stage_th']}: {r['sku']} ({plat})", r["action_th"]))
    # 货到付款拒收率
    cod = dash.cod_stats(30)
    lim = _f(cfg, "oa_cod_fail_rate", 10)
    if cod["cod_fail_rate"] is not None and cod["cod_orders"] >= 10 and cod["cod_fail_rate"] >= lim:
        add(f"codfail:{day[:7]}", "发货", "warn", f"货到付款拒收率偏高：{cod['cod_fail_rate']}%",
            f"近 30 天 {cod['cod_failed']}/{cod['cod_orders']} 单拒收 / 派送失败", "ops_dash", "owner",
            alert=f"📦 货到付款拒收率偏高：近 30 天 {cod['cod_failed']}/{cod['cod_orders']} 单（{cod['cod_fail_rate']}%）",
            th=(f"อัตราปฏิเสธรับ COD สูง: {cod['cod_fail_rate']}%", f"30 วันล่าสุด {cod['cod_failed']}/{cod['cod_orders']} ออเดอร์"))
    # Lazada 差评没回复（近 30 天）
    stars = _f(cfg, "oa_bad_review_stars", 3)
    for r in lazada.reviews_list(30, unreplied=True):
        if r["rating"] is None or r["rating"] > stars:
            continue
        name = r.get("item_name") or r["item_id"]
        add(f"review:{r['shop_id']}:{r['review_id']}", "评价", "bad", f"{r['rating']} 星差评没回复：{name[:40]}", (r["content"] or "")[:120],
            "ops_lazada", "owner,listing", alert=f"⭐ {r['rating']} 星差评：{name[:40]}：{(r['content'] or '')[:80]}",
            th=(f"รีวิว {r['rating']} ดาวยังไม่ตอบ: {name[:40]}", (r["content"] or "")[:120]))
    # 新的退货退款申请（还没处理完的，近 14 天）
    for r in lazada.reverse_list(14):
        if not r["open"]:
            continue
        kind = {"RETURN": "退货退款", "ONLY_REFUND": "仅退款", "CANCEL": "取消"}.get((r["request_type"] or "").upper(), r["request_type"] or "退货退款")
        amt = f" ฿{r['refund_amount']:,.2f}" if r["refund_amount"] else ""
        add(f"reverse:{r['shop_id']}:{r['line_id']}:{r['status']}", "售后", "warn", f"Lazada {kind}申请：{r['order_no']}{amt}",
            f"{r['reason'] or ''} · {r['status']}", "ops_lazada", "owner,listing",
            alert=f"↩️ Lazada {kind}申请：{r['order_no']}{amt}（{r['reason'] or r['status']}）",
            th=(f"คำขอ{'คืนสินค้า' if kind == '退货退款' else 'คืนเงิน' if kind == '仅退款' else 'ยกเลิก'} Lazada: {r['order_no']}{amt}",
                f"{r['reason'] or ''} · {r['status']}"))
    # 店铺表现不达标
    for sh in lazada.performance():
        for m in sh["metrics"]:
            if m.get("ok") is False:
                add(f"perf:{sh['shop_id']}:{m['type'] or m['name']}:{m['value']}", "平台接口", "warn",
                    f"店铺表现没达标：{m['name']} {m['value']}", f"{sh['shop']} · 要求 {m['target']}", "ops_lazada", "owner",
                    alert=f"📉 {sh['shop']} 店铺表现没达标：{m['name']} {m['value']}（要求 {m['target']}）",
                    th=(f"ประสิทธิภาพร้านไม่ถึงเกณฑ์: {m['name']} {m['value']}", f"{sh['shop']} · เกณฑ์ {m['target']}"))
    # 接口出错（没权限、授权过期……）
    for s in lazada.status():
        if not s["error"]:
            continue
        h = hashlib.md5(s["error"].encode("utf-8", "ignore")).hexdigest()[:8]
        add(f"lzerr:{s['shop_id']}:{s['kind']}:{h}", "平台接口", "bad", f"Lazada {s['zh']}拉不下来：{s['shop']}",
            s["hint"] or s["error"][:150], "ops_lazada", "owner",
            alert=f"🔌 Lazada {s['zh']}拉不下来（{s['shop']}）：{s['hint'] or s['error'][:150]}",
            th=(f"ดึง{s['th']}จาก Lazada ไม่ได้: {s['shop']}", s["hint_th"] or s["error"][:150]))
