"""财务报表（v2.21）：损益表、利润分析、现金流、税、总览。

口径：
  · 损益表按「下单日期」（权责发生制）：这期间下的单（不含取消 / 退款 / 未付款 / 报价）的收入和成本，加上这期间记的支出。
  · 现金流按「钱实际进出的日期」：平台回款（导入的结算表）、其他收入、采购付款、支出。
  · 平台扣费：导入过结算表的订单用真实到账算；没有的按设置里的扣点估算（标「估」）。
  · 生产成本只算 材料 + 电费 + 包材 + 失败损耗；房租、人工、折旧算「固定费用」：这期间记了账就用记的，没记就按设置估算
    （利润页的「每单利润」把固定成本按机时分摊进去了，看单品赚不赚钱用那个；看整个店赚不赚钱用这里）。
  · VAT：设置里开了才算（默认关：还没注册 VAT）。开了以后收入按含税价拆出销项税，记了税票的支出 / 平台费用里的 VAT 算进项。
"""
import datetime as dt

from core import db, pricing
from core.config import load_config
from .common import day_of, period, r2, settings, ts


def _orders(start, end):
    from core.finance import EXCLUDE
    c = db.conn()
    orders = c.execute(f"SELECT * FROM orders WHERE order_time>=? AND order_time<? AND status NOT IN ({','.join('?' * len(EXCLUDE))})",
                       (ts(start), ts(end), *EXCLUDE)).fetchall()
    items = {}
    if orders:
        ids = [o["id"] for o in orders]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for it in c.execute(f"SELECT * FROM order_items WHERE order_id IN ({','.join('?' * len(chunk))})", chunk):
                items.setdefault(it["order_id"], []).append(it)
    return orders, items


def _profits(start, end, cfg):
    from core.finance import order_profit
    orders, items = _orders(start, end)
    out = []
    for o in orders:
        its = items.get(o["id"], [])
        out.append((o, its, order_profit(cfg, o, its)))
    return out


def _expenses(start, end):
    return [dict(r) for r in db.conn().execute(
        "SELECT * FROM expenses WHERE COALESCE(deleted,0)=0 AND day>=? AND day<?", (start.isoformat(), end.isoformat()))]


def _line(key, zh, th, amount, level=1, note="", est=False):
    """note：(中文, 泰文) 或空。"""
    nz, nt = note if isinstance(note, tuple) else (note, note)
    return {"key": key, "zh": zh, "th": th, "amount": r2(amount), "level": level, "note": nz, "note_th": nt, "est": est}


def pl(start=None, end=None, month=None):
    """损益表。返回 {period, lines: [...], summary: {...}}"""
    if start is None:
        start, end, label = period(month)
    else:
        label = f"{start.isoformat()} ~ {(end - dt.timedelta(days=1)).isoformat()}"
    cfg = load_config()
    st = settings(cfg)
    rows = _profits(start, end, cfg)
    rev = sum(p["revenue"] for _o, _i, p in rows)
    fee = sum(p["fee"] for _o, _i, p in rows)
    fee_est = sum(p["fee"] for _o, _i, p in rows if p["fee_estimated"])
    material = sum(p["material"] for _o, _i, p in rows)
    packaging = sum(p["packaging"] for _o, _i, p in rows)
    failure = sum(p["failure"] for _o, _i, p in rows)
    hours = sum(p["hours"] for _o, _i, p in rows)
    elec = hours * float(cfg.get("printer_avg_kw") or 0) * float(cfg.get("electricity_thb_per_kwh") or 0)
    missing = sum(1 for _o, _i, p in rows if p["missing_data"])
    vr = st["vat_rate"]
    out_vat = rev * vr / (1 + vr) if st["vat_on"] and st["incl_vat"] else (rev * vr if st["vat_on"] else 0)
    if st["vat_on"] and not st["incl_vat"]:
        rev_net = rev                    # 价格不含税：收入就是不含税的，销项税另外收（这里只记账，不改价格）
    else:
        rev_net = rev - out_vat
    # 平台费用里的 VAT（结算表里有就用）
    fee_vat = 0.0
    if st["vat_on"]:
        from .settle import key
        keys = {(o["platform"], key(o["order_no"])) for o, _i, p in rows if p["fee_source"] == "settlement"}
        if keys:
            for r in db.conn().execute("SELECT platform, order_key, SUM(vat) v FROM fin_settle_lines GROUP BY platform, order_key"):
                if (r["platform"], r["order_key"]) in keys:
                    fee_vat += r["v"] or 0
    fee_net = fee - fee_vat
    cogs = material + elec + packaging + failure
    gross = rev_net - fee_net - cogs
    # 售后损失
    from core import extras
    loss = sum(a["loss"] for a in extras.as_losses(ts(start)) if a["created_at"] < ts(end))
    # 支出 / 其他收入
    exps = _expenses(start, end)
    by_cat, other_in, capital = {}, 0.0, 0.0
    in_vat = 0.0
    for e in exps:
        amt = float(e["amount"] or 0)
        if (e.get("direction") or "out") == "in":
            if e["kind"] == "老板投入":
                capital += amt
            else:
                other_in += amt
            continue
        v = float(e.get("vat") or 0) if (st["vat_on"] and e.get("tax_invoice")) else 0
        in_vat += v
        by_cat[e["kind"]] = by_cat.get(e["kind"], 0) + amt - v
    days = max(0, (min(end, dt.date.today() + dt.timedelta(days=1)) - start).days)     # 还没到的日子不算
    # v2.40：按项估算——记了账的那项用记的，没记的那几项按设置估算（以前只要记了一项，其余全部不算）
    FIX_KEYS = (("房租", "monthly_rent", "ค่าเช่า"), ("人工工资", "monthly_labor", "ค่าแรง"),
                ("设备折旧", "monthly_depreciation", "ค่าเสื่อม"), ("设备维修", "monthly_maintenance", "ค่าซ่อมบำรุง"))
    est_items = [(zh, th, float(cfg.get(k) or 0)) for zh, k, th in FIX_KEYS if not by_cat.get(zh) and float(cfg.get(k) or 0)]
    # 设置里自己加了固定费用分类（例如「工资」）并且记了账：分不清对应哪一项 → 照以前，记了就都不估，免得重复算
    custom = [k for k in st["fixed_cats"] if k not in {z for z, _k, _t in FIX_KEYS}]
    if any(by_cat.get(k) for k in custom):
        est_items = []
    fixed_est = sum(v for _z, _t, v in est_items) * days / 30.0
    opex = sum(by_cat.values())
    op_profit = gross - loss - opex - fixed_est
    net = op_profit + other_in
    wht = _wht(start, end)
    try:
        from core import inventory
        inv_used = inventory.expense(ts(start), ts(end), "category")["total"]
    except Exception:  # noqa: BLE001
        inv_used = None

    L = [_line("revenue", "销售收入（订单金额）", "รายได้จากการขาย (ยอดคำสั่งซื้อ)", rev, 0, (f"{len(rows)} 单", f"{len(rows)} คำสั่งซื้อ"))]
    if st["vat_on"] and st["incl_vat"]:
        L.append(_line("out_vat", "减：销项税 VAT", "หัก: ภาษีขาย VAT", -out_vat, 1, f"{vr * 100:g}%"))
        L.append(_line("rev_net", "不含税收入", "รายได้ไม่รวม VAT", rev_net, 2))
    elif st["vat_on"]:
        # v2.41：价格不含税——销项税是另外向买家收、要交给税务局的钱，不从收入里减（以前写「减：销项税」但收入不变，看起来算不平）
        L.append(_line("out_vat", "销项税 VAT（价格不含税：另外向买家收，交给税务局，不算收入也不减收入）",
                       "ภาษีขาย VAT (ราคาไม่รวม VAT: เก็บเพิ่มจากผู้ซื้อแล้วนำส่งสรรพากร ไม่นับเป็นรายได้)", out_vat, 4, f"{vr * 100:g}%"))
    L += [_line("fee", "减：平台扣费（佣金、服务费、手续费、卖家优惠）", "หัก: ค่าธรรมเนียมแพลตฟอร์ม", -fee_net, 1,
                (f"其中按扣点估算 ฿{fee_est:,.0f}", f"ในนี้ประมาณจากอัตราค่าธรรมเนียม ฿{fee_est:,.0f}") if fee_est else "", est=bool(fee_est)),
          _line("material", "减：材料", "หัก: วัสดุ", -material, 1),
          _line("elec", "减：电费", "หัก: ค่าไฟ", -elec, 1, (f"{hours:,.1f} 打印小时", f"{hours:,.1f} ชั่วโมงพิมพ์")),
          _line("packaging", "减：包材", "หัก: วัสดุแพ็ค", -packaging, 1),
          _line("failure", "减：失败损耗", "หัก: ความเสียหายจากงานเสีย", -failure, 1),
          _line("gross", "毛利", "กำไรขั้นต้น", gross, 2),
          _line("aftersales", "减：售后损失（退款、补发、罚款……）", "หัก: ความเสียหายหลังการขาย", -loss, 1)]
    for k, v in sorted(by_cat.items(), key=lambda x: -x[1]):
        L.append(_line("exp:" + k, "减：" + k, "หัก: " + k, -v, 1, ("固定费用", "ค่าใช้จ่ายคงที่") if k in st["fixed_cats"] else ""))
    if fixed_est:
        mon = sum(v for _z, _t, v in est_items)
        L.append(_line("fixed_est", "减：固定费用（本期没记账的几项，按设置估算）",
                       "หัก: ค่าใช้จ่ายคงที่ (รายการที่ยังไม่บันทึก ประมาณจากการตั้งค่า)", -fixed_est, 1,
                       (f"{'、'.join(z for z, _t, _v in est_items)}：฿{mon:,.0f}/月 × {days} 天",
                        f"{', '.join(t for _z, t, _v in est_items)}: ฿{mon:,.0f}/เดือน × {days} วัน"), est=True))
    L.append(_line("op_profit", "经营利润", "กำไรจากการดำเนินงาน", op_profit, 2))
    if other_in:
        L.append(_line("other_in", "加：其他收入", "บวก: รายได้อื่น", other_in, 1))
    L.append(_line("net", "净利润（税前）", "กำไรสุทธิ (ก่อนภาษี)", net, 3))
    summary = {"orders": len(rows), "revenue": r2(rev), "revenue_net": r2(rev_net), "fees": r2(fee_net), "cogs": r2(cogs),
               "gross": r2(gross), "gross_margin": round(gross / rev_net * 100, 1) if rev_net else None,
               "opex": r2(opex + fixed_est + loss), "net": r2(net), "net_margin": round(net / rev_net * 100, 1) if rev_net else None,
               "fee_rate": round(fee / rev * 100, 1) if rev else None, "fee_estimated": r2(fee_est), "missing_data_orders": missing,
               "aov": r2(rev / len(rows)) if rows else 0, "capital_in": r2(capital), "wht": r2(wht["total"]),
               "out_vat": r2(out_vat), "in_vat": r2(in_vat + fee_vat), "inventory_used": r2(inv_used) if inv_used is not None else None,
               "material_est": r2(material), "fixed_estimated": r2(fixed_est)}
    return {"period": label, "start": start.isoformat(), "end": (end - dt.timedelta(days=1)).isoformat(), "lines": L,
            "summary": summary, "vat_on": st["vat_on"]}


def _wht(start, end):
    rows = db.conn().execute("SELECT platform, SUM(wht) w FROM fin_settle_lines WHERE day>=? AND day<? GROUP BY platform",
                             (start.isoformat(), end.isoformat())).fetchall()
    return {"total": sum(r["w"] or 0 for r in rows), "by_platform": {r["platform"]: r2(r["w"]) for r in rows}}


DIMS = ("platform", "shop", "product", "sku", "day", "month")


def breakdown(start, end, by="platform"):
    """利润分析：按平台 / 店铺 / 产品 / SKU / 日 / 月。利润 = 收入 − 平台扣费 − 生产成本（含分摊的机时）。不含支出。"""
    if by not in DIMS:
        by = "platform"
    cfg = load_config()
    groups = {}
    tot = {"orders": 0, "qty": 0, "revenue": 0.0, "fee": 0.0, "cost": 0.0, "profit": 0.0}
    for o, its, p in _profits(start, end, cfg):
        tot["orders"] += 1
        tot["revenue"] += p["revenue"]; tot["fee"] += p["fee"]; tot["cost"] += p["cost"]; tot["profit"] += p["profit"]
        if by in ("platform", "shop", "day", "month"):
            k = {"platform": o["platform"] or "其他", "shop": f"{o['platform'] or ''} · {o['shop'] or '（没写店铺）'}",
                 "day": day_of(o["order_time"]), "month": day_of(o["order_time"])[:7]}[by]
            shares = [(k, 1.0, sum((i["qty"] or 1) for i in its), "")]
        else:
            tot_items = sum((i["item_total"] or 0) for i in its)
            shares = [] if its else [("（没有商品明细）", 1.0, 0, "")]
            for i in its:
                share = (i["item_total"] or 0) / tot_items if tot_items else 1 / max(1, len(its))
                k = (i["product_id"] or "（没对上产品）") if by == "product" else (i["sku"] or "?")
                shares.append((k, share, i["qty"] or 1, i["name"] or ""))
        tot["qty"] += sum(s[2] for s in shares)
        counted = set()      # v2.41：一张订单里同一个产品有好几个 SKU，订单数只算一次
        for k, share, qty, name in shares:
            g = groups.setdefault(k, {"key": k, "name": name, "orders": 0, "qty": 0, "revenue": 0.0, "fee": 0.0, "cost": 0.0, "profit": 0.0,
                                      "est_fee": 0})
            if k not in counted:
                g["orders"] += 1
                g["est_fee"] += 1 if p["fee_estimated"] else 0
                counted.add(k)
            g["qty"] += qty
            for f in ("revenue", "fee", "cost", "profit"):
                g[f] += p[f] * share
            if name and not g["name"]:
                g["name"] = name
    if by == "product":
        from core import store
        for g in groups.values():
            try:
                g["name"] = store.load(g["key"]).get("name_zh") or g["name"]
            except Exception:  # noqa: BLE001
                pass
    out = []
    for g in groups.values():
        g = {k: (r2(v) if isinstance(v, float) else v) for k, v in g.items()}
        g["margin"] = round(g["profit"] / g["revenue"] * 100, 1) if g["revenue"] else None
        g["share"] = round(g["revenue"] / tot["revenue"] * 100, 1) if tot["revenue"] else None
        out.append(g)
    out.sort(key=(lambda x: x["key"]) if by in ("day", "month") else (lambda x: -x["revenue"]))
    tot = {k: (r2(v) if isinstance(v, float) else v) for k, v in tot.items()}
    tot["margin"] = round(tot["profit"] / tot["revenue"] * 100, 1) if tot["revenue"] else None
    return {"by": by, "rows": out, "total": tot}


def cashflow(start, end):
    """现金流：按天（期间超过 62 天按月）。"""
    monthly = (end - start).days > 62
    bucket = (lambda d: d[:7]) if monthly else (lambda d: d)
    c = db.conn()
    rows = {}

    def add(day, k, v):
        if not day:
            return
        r = rows.setdefault(bucket(day), {"key": bucket(day), "settle_in": 0.0, "other_in": 0.0, "capital_in": 0.0,
                                         "purchase_out": 0.0, "expense_out": 0.0})
        r[k] += float(v or 0)
    s, e = start.isoformat(), end.isoformat()
    for r in c.execute("SELECT day, SUM(amount) a FROM fin_settle_lines WHERE day>=? AND day<? GROUP BY day", (s, e)):
        add(r["day"], "settle_in", r["a"])
    for r in c.execute("SELECT day, kind, COALESCE(direction,'out') dir, amount FROM expenses WHERE COALESCE(deleted,0)=0 AND day>=? AND day<?", (s, e)):
        if r["dir"] == "in":
            add(r["day"], "capital_in" if r["kind"] == "老板投入" else "other_in", r["amount"])
        else:
            add(r["day"], "expense_out", r["amount"])
    try:
        for r in c.execute("SELECT day, SUM(amount) a FROM fin_events WHERE kind='purchase_payment' AND day>=? AND day<? GROUP BY day", (s, e)):
            add(r["day"], "purchase_out", r["a"])
    except Exception:  # noqa: BLE001  库存模块还没建表
        pass
    out = []
    tot = {"settle_in": 0.0, "other_in": 0.0, "capital_in": 0.0, "purchase_out": 0.0, "expense_out": 0.0}
    bal = 0.0
    for k in sorted(rows):
        r = rows[k]
        r["in"] = r["settle_in"] + r["other_in"] + r["capital_in"]
        r["out"] = r["purchase_out"] + r["expense_out"]
        r["net"] = r["in"] - r["out"]
        bal += r["net"]
        r["running"] = bal
        for f in tot:
            tot[f] += r[f]
        out.append({kk: (r2(v) if isinstance(v, float) else v) for kk, v in r.items()})
    tot["in"] = tot["settle_in"] + tot["other_in"] + tot["capital_in"]
    tot["out"] = tot["purchase_out"] + tot["expense_out"]
    tot["net"] = tot["in"] - tot["out"]
    has_settle = c.execute("SELECT 1 FROM fin_settle_lines LIMIT 1").fetchone() is not None
    return {"monthly": monthly, "rows": out, "total": {k: r2(v) for k, v in tot.items()}, "has_settlements": has_settle}


def tax(start, end):
    """VAT（开了才算）按月 + 平台代扣税（WHT）。"""
    cfg = load_config()
    st = settings(cfg)
    months = []
    d = dt.date(start.year, start.month, 1)
    while d < end:
        nxt = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        s2, e2 = max(d, start), min(nxt, end)
        p = pl(s2, e2)["summary"]
        w = _wht(s2, e2)
        exp_vat = sum(float(e.get("vat") or 0) for e in _expenses(s2, e2)
                      if (e.get("direction") or "out") == "out" and e.get("tax_invoice"))
        months.append({"month": d.strftime("%Y-%m"), "sales": p["revenue"], "out_vat": p["out_vat"] if st["vat_on"] else 0,
                       "in_vat_expenses": r2(exp_vat) if st["vat_on"] else 0,
                       "in_vat_fees": r2(p["in_vat"] - exp_vat) if st["vat_on"] else 0,
                       "payable": r2(p["out_vat"] - p["in_vat"]) if st["vat_on"] else 0, "wht": r2(w["total"]), "wht_by_platform": w["by_platform"]})
        d = nxt
    # 不开 VAT 时也提醒：一年营业额超过 180 万铢要注册 VAT
    year = start.year
    ys, ye = dt.date(year, 1, 1), dt.date(year + 1, 1, 1)
    year_sales = sum(p["revenue"] for _o, _i, p in _profits(ys, ye, cfg))
    missing_invoice = [dict(id=e["id"], day=e["day"], category=e["kind"], amount=e["amount"]) for e in _expenses(start, end)
                       if (e.get("direction") or "out") == "out" and not e.get("tax_invoice") and float(e["amount"] or 0) >= 1000]
    return {"vat_on": st["vat_on"], "vat_rate": st["vat_rate"], "incl_vat": st["incl_vat"], "months": months,
            "total": {k: r2(sum(m[k] for m in months)) for k in ("sales", "out_vat", "in_vat_expenses", "in_vat_fees", "payable", "wht")},
            "year": year, "year_sales": r2(year_sales), "vat_threshold": 1_800_000,
            "missing_invoice": missing_invoice[:50] if st["vat_on"] else []}


def overview(month=None, start=None, end=None):
    """v2.41：可以按任意期间（今年 / 自定义），和下面的损益表一致；对比的是紧挨着的前一段同样长的期间。"""
    if start is not None:
        s, e = start, end
        label = f"{s.isoformat()} ~ {(e - dt.timedelta(days=1)).isoformat()}"
        ps = s - (e - s)
    else:
        s, e, label = period(month)
        ps = dt.date(s.year - (s.month == 1), (s.month - 2) % 12 + 1, 1)
    cur = pl(s, e)
    prev = pl(ps, s)
    cf = cashflow(s, e)
    from .settle import reconcile
    rc = reconcile(s, e)
    days = breakdown(s, e, "day")
    top = breakdown(s, e, "product")["rows"][:8]
    plat = breakdown(s, e, "platform")["rows"]

    def chg(a, b):
        return round((a - b) / abs(b) * 100, 1) if b else None
    keys = ("revenue", "gross", "net", "orders", "aov", "fees")
    return {"month": label, "custom": start is not None, "summary": cur["summary"], "prev": prev["summary"],
            "change": {k: chg(cur["summary"][k] or 0, prev["summary"][k] or 0) for k in keys},
            "cash": cf["total"], "has_settlements": cf["has_settlements"], "reconcile": rc["total"],
            "unpaid_count": len(rc["unpaid"]), "diff_count": len(rc["diff"]), "unknown_count": len(rc["unknown"]),
            "unsettled_count": len(rc["unsettled"]), "issues": rc["total"]["issues"],
            "days": [{"day": d["key"], "revenue": d["revenue"], "profit": d["profit"], "orders": d["orders"]} for d in days["rows"]],
            "top_products": top, "platforms": plat, "vat_on": cur["vat_on"]}
