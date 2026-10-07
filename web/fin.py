"""电商财务（v2.21）的接口。只调用 core.fin 的公开函数。网页接口只有老板能用（auth.OWNER_ONLY）；
对外接口 /api/v1/finance/…（密钥权限 finance，只读）给以后的财务软件 / 会计用。"""
import io

from web.common import *  # noqa: F401,F403
from core import fin


def _period():
    a = request.args
    try:
        if a.get("start"):
            return fin.period(start=a.get("start"), end=a.get("end"))
        return fin.period(a.get("month") or None)
    except ValueError:
        raise ValueError("日期格式不对（月份 YYYY-MM，日期 YYYY-MM-DD）")


def _wrap(fn):
    try:
        return jsonify(fn())
    except ValueError as e:
        return err(str(e))


@app.get("/api/fin/meta")
def fin_meta():
    from core.fin.common import settings
    c = db.conn()
    shops = [dict(r) for r in c.execute("SELECT DISTINCT platform, shop FROM orders WHERE COALESCE(platform,'')!='' ORDER BY platform, shop")]
    return jsonify({"ok": True, "categories": fin.expense_categories(), "settings": settings(), "shops": shops})


@app.get("/api/fin/overview")
def fin_overview():
    return _wrap(lambda: fin.overview(request.args.get("month") or None))


@app.get("/api/fin/pl")
def fin_pl():
    def go():
        s, e, _l = _period()
        return fin.pl(s, e)
    return _wrap(go)


@app.get("/api/fin/breakdown")
def fin_breakdown():
    def go():
        s, e, label = _period()
        return dict(fin.breakdown(s, e, request.args.get("by") or "platform"), period=label)
    return _wrap(go)


@app.get("/api/fin/cashflow")
def fin_cashflow():
    def go():
        s, e, label = _period()
        return dict(fin.cashflow(s, e), period=label)
    return _wrap(go)


@app.get("/api/fin/tax")
def fin_tax():
    def go():
        s, e, label = _period()
        return dict(fin.tax(s, e), period=label)
    return _wrap(go)


@app.get("/api/fin/reconcile")
def fin_reconcile():
    def go():
        s, e, label = _period()
        return dict(fin.reconcile(s, e), period=label, batches=fin.settle_batches(20))
    return _wrap(go)


# ---------------- 收支 ----------------
@app.get("/api/fin/expenses")
def fin_expenses():
    def go():
        s, e, label = _period()
        a = request.args
        rows = fin.expenses(s.isoformat(), e.isoformat(), a.get("category") or "", a.get("direction") or "")
        tot_out = sum(r["amount"] for r in rows if r["direction"] == "out")
        tot_in = sum(r["amount"] for r in rows if r["direction"] == "in")
        by = {}
        for r in rows:
            k = (r["direction"], r["category"])
            by[k] = by.get(k, 0) + r["amount"]
        return {"period": label, "rows": rows, "total_out": round(tot_out, 2), "total_in": round(tot_in, 2),
                "by_category": [{"direction": k[0], "category": k[1], "amount": round(v, 2)} for k, v in sorted(by.items(), key=lambda x: -x[1])]}
    return _wrap(go)


@app.post("/api/fin/expenses")
def fin_expense_save():
    return _wrap(lambda: {"ok": True, "row": fin.save_expense(request.get_json(force=True) or {}, _uname())})


@app.delete("/api/fin/expenses/<int:eid>")
def fin_expense_delete(eid):
    def go():
        fin.delete_expense(eid, _uname())
        return {"ok": True}
    return _wrap(go)


@app.post("/api/fin/expenses/<int:eid>/receipt")
def fin_receipt_upload(eid):
    f = request.files.get("file")
    if not f:
        return err("请选择票据照片或 PDF")
    return _wrap(lambda: {"ok": True, "file": fin.set_receipt(eid, f)})


@app.get("/api/fin/expenses/<int:eid>/receipt")
def fin_receipt(eid):
    p = fin.receipt_path(eid)
    if not p:
        return err("没有票据", 404)
    return send_file(p)


# ---------------- 平台结算导入 ----------------
@app.post("/api/fin/settle/preview")
def fin_settle_preview():
    f = request.files.get("file")
    if not f:
        return err("请选择平台导出的结算 / 收入报表")
    return _wrap(lambda: fin.settle_preview(f))


@app.post("/api/fin/settle/import")
def fin_settle_import():
    b = request.get_json(force=True) or {}
    return _wrap(lambda: fin.settle_import(b.get("token"), b.get("mapping") or {}, b.get("platform") or "", b.get("shop") or "", _uname()))


@app.delete("/api/fin/settle/batches/<int:bid>")
def fin_settle_delete(bid):
    def go():
        fin.delete_batch(bid, _uname())
        return {"ok": True}
    return _wrap(go)


# ---------------- 导出 Excel（给会计） ----------------
@app.get("/api/fin/export")
def fin_export():
    import openpyxl
    from openpyxl.styles import Font
    try:
        s, e, label = _period()
    except ValueError as ex:
        return err(str(ex))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "损益表"
    p = fin.pl(s, e)
    ws.append([f"损益表 {p['period']}", "", "说明"])
    for ln in p["lines"]:
        ws.append([("    " if ln["level"] == 1 else "") + ln["zh"], ln["amount"], ("（估）" if ln["est"] else "") + (ln["note"] or "")])
        if ln["level"] >= 2:
            ws.cell(ws.max_row, 1).font = Font(bold=True)
            ws.cell(ws.max_row, 2).font = Font(bold=True)
    for by, title in (("platform", "按平台"), ("shop", "按店铺"), ("product", "按产品"), ("sku", "按SKU"), ("day", "按日")):
        w = wb.create_sheet(title)
        b = fin.breakdown(s, e, by)
        w.append([title, "名称", "订单", "件数", "收入", "平台扣费", "生产成本", "利润", "利润率%"])
        for r in b["rows"]:
            w.append([r["key"], r.get("name") or "", r["orders"], r["qty"], r["revenue"], r["fee"], r["cost"], r["profit"], r["margin"]])
    w = wb.create_sheet("收支明细")
    w.append(["日期", "方向", "分类", "金额", "VAT", "有税票", "收款方", "付款方式", "备注", "记账人"])
    for r in fin.expenses(s.isoformat(), e.isoformat()):
        w.append([r["day"], "收入" if r["direction"] == "in" else "支出", r["category"], r["amount"], r.get("vat") or 0,
                  "是" if r.get("tax_invoice") else "", r.get("payee") or "", r.get("method") or "", r.get("note") or "", r.get("username") or ""])
    w = wb.create_sheet("现金流")
    cf = fin.cashflow(s, e)
    w.append(["日期", "平台回款", "其他收入", "老板投入", "采购付款", "支出", "净流入", "累计"])
    for r in cf["rows"]:
        w.append([r["key"], r["settle_in"], r["other_in"], r["capital_in"], r["purchase_out"], r["expense_out"], r["net"], r["running"]])
    for sh in wb.worksheets:
        sh.column_dimensions["A"].width = 46 if sh.title == "损益表" else 18
        sh.column_dimensions["B"].width = 16
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"财务_{label}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------- 对外只读接口（密钥权限 finance，规范第 11 条） ----------------
@app.get("/api/v1/finance/pl")
def v1_fin_pl():
    def go():
        s, e, _l = _period()
        return dict(fin.pl(s, e), ok=True, currency="THB")
    return _wrap(go)


@app.get("/api/v1/finance/breakdown")
def v1_fin_breakdown():
    def go():
        s, e, label = _period()
        return dict(fin.breakdown(s, e, request.args.get("by") or "platform"), ok=True, period=label, currency="THB")
    return _wrap(go)


@app.get("/api/v1/finance/cashflow")
def v1_fin_cashflow():
    def go():
        s, e, label = _period()
        return dict(fin.cashflow(s, e), ok=True, period=label, currency="THB")
    return _wrap(go)


@app.get("/api/v1/finance/expenses")
def v1_fin_expenses():
    def go():
        s, e, label = _period()
        return {"ok": True, "period": label, "currency": "THB", "rows": fin.expenses(s.isoformat(), e.isoformat())}
    return _wrap(go)


@app.get("/api/v1/finance/tax")
def v1_fin_tax():
    def go():
        s, e, label = _period()
        return dict(fin.tax(s, e), ok=True, period=label, currency="THB")
    return _wrap(go)
