"""竞品（第二期，从运营分析系统 modules/competitors 搬过来）：插件采集 / 粘贴页面文字（AI 识别），
按每次记录推算日销、销售额、平台费、生产成本和单件利润；我方 SKU vs 竞品；选品雷达；竞品动态（降价、开券、放量）。

只读别人公开展示的数字，不登录别人的店、不绕验证码、不批量爬。
销量推算的优先顺序（越靠前越准）：
  1. 两次记录的「累计已售」差值 ÷ 间隔天数                 → 实测
  2. 页面上的「近 30 天已售」                              → 实测
  3. 两次记录的评价数差值 ÷ 留评比例                         → 估（比例优先用它自己的 评价数 / 累计已售 校准）
  4. 累计已售 ÷ 上架天数（填了上架日期才有）                  → 估
平台扣点：Lazada 用第一期财务流水算出的真实扣点（mkt_util.fee_rate）；生产成本用 ERP 的成本参数（core/pricing.py）。
"""
import datetime as dt
import json
import re
import statistics
import time

from core.config import load_config

from . import mkt_db
from .mkt_util import (AiError, ai_json, ai_on, card_numbers, clean_img, fee_rate, num, parse_count, parse_url, sku_avg_daily,
                       sku_rows, tf, unit_cost as erp_unit_cost, capacity_hours)

SNAP_FIELDS = ("price", "list_price", "voucher", "sold_total", "sold_text", "sold_30d", "rating", "reviews", "free_ship", "title")

EXTRACT_SYS = """你是泰国电商数据录入助手。用户会粘贴从 Lazada / Shopee / TikTok Shop 商品页复制下来的文字（泰文、英文或中文都有）。
只提取页面上真实出现的数字，不要猜。没有的字段填 null。只回复 JSON，字段：
{"title": 商品标题, "shop": 店铺名, "price": 现在的售价（数字，泰铢；有区间取最低价）, "list_price": 划线原价,
 "voucher": 店铺优惠券能减多少泰铢（只取最常用的一张，百分比券按售价换算）, "sold_text": 累计已售的原文数字，如 "1.2k" "350",
 "sold_30d": 近30天已售（页面写明是 30 天时才填）, "rating": 评分 0-5, "reviews": 评价数（数字，可以是 "1.2k"）,
 "free_ship": 是否包邮 true/false, "variants": 规格/颜色/尺寸文字（简短）, "size_text": 页面上写的尺寸重量（简短）}"""

COST_SYS = """你是 3D 打印成本估算师。根据商品标题、规格、尺寸文字和售价，估算一件商品用 FDM（拓竹 P1S / K1 类机器、0.4 喷嘴、0.2 层高）
打印需要的耗材克重和打印小时。参考用户自己产品的真实克重和时长来校准。不确定时宁可偏保守（偏重、偏慢）。
只回复 JSON：{"grams": 数字, "hours": 数字, "material": "PLA"|"PETG"|"TPU"|"RESIN", "size_guess": "长×宽×高 cm 的猜测",
 "confidence": 0到1, "reason": "一句中文说明依据"}"""


def _c():
    return mkt_db.conn()


# ---------------- 读写 ----------------
def get(cid):
    r = _c().execute("SELECT * FROM ops_comp WHERE id=?", (cid,)).fetchone()
    return dict(r) if r else None


def snaps(cid):
    return [dict(r) for r in _c().execute("SELECT * FROM ops_comp_snaps WHERE comp_id=? ORDER BY ts", (cid,))]


def links(cid):
    return [r[0] for r in _c().execute("SELECT sku FROM ops_comp_links WHERE comp_id=? ORDER BY sku", (cid,))]


def create(data):
    url = (data.get("url") or "").strip()
    plat, key = parse_url(url)
    plat = (data.get("platform") or plat or "lazada").lower()
    c = _c()
    if key:
        old = c.execute("SELECT id FROM ops_comp WHERE item_key=?", (key,)).fetchone()
        if old:
            c.execute("UPDATE ops_comp SET status='active' WHERE id=?", (old["id"],))
            c.commit()
            set_image(old["id"], data.get("image"))
            set_links(old["id"], data.get("skus"), add_only=True)
            return old["id"], False
    if not url and not (data.get("title") or "").strip():
        raise ValueError("至少填商品链接或标题")
    now = time.time()
    cur = c.execute("""INSERT INTO ops_comp(platform, url, item_key, title, shop, note, listed_on, created_at, updated_at, image)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (plat, url[:600], key or None, (data.get("title") or "")[:300], (data.get("shop") or "")[:120],
                     (data.get("note") or "")[:500], data.get("listed_on") or None, now, now, clean_img(data.get("image"))))
    cid = cur.lastrowid
    c.commit()
    set_links(cid, data.get("skus"))
    if any(data.get(k) not in (None, "") for k in ("price", "sold_total", "sold_text", "reviews")):
        add_snap(cid, data, source=data.get("source") or "manual")
    return cid, True


def update(cid, data):
    allowed = ("title", "shop", "note", "listed_on", "platform", "url", "status", "radar_status", "est_grams", "est_hours",
               "est_material", "est_unit_cost", "cost_source", "cost_note", "fee_rate_override", "image")
    if "image" in data:
        data = {**data, "image": clean_img(data["image"])}
    sets = {k: data[k] for k in allowed if k in data}
    for k in ("est_grams", "est_hours", "est_unit_cost", "fee_rate_override"):
        if k in sets:
            sets[k] = num(sets[k])
    if sets.get("fee_rate_override") and sets["fee_rate_override"] > 1:      # 填 15 当作 15%
        sets["fee_rate_override"] /= 100
    if sets.get("status") not in (None, "active", "archived"):
        sets.pop("status")
    if sets.get("radar_status") not in (None, "new", "want", "skip", "done"):
        sets.pop("radar_status")
    if "url" in sets:
        sets["platform"], sets["item_key"] = parse_url(sets["url"])
    if sets:
        sets["updated_at"] = time.time()
        _c().execute(f"UPDATE ops_comp SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), cid))
        _c().commit()
    if "skus" in data:
        set_links(cid, data["skus"])


def set_image(cid, url):
    u = clean_img(url)
    if u:
        _c().execute("UPDATE ops_comp SET image=? WHERE id=?", (u, cid))
        _c().commit()


def set_links(cid, skus, add_only=False):
    if skus is None:
        return
    if isinstance(skus, str):
        skus = [s for s in re.split(r"[,\s，、]+", skus) if s]
    c = _c()
    if not add_only:
        c.execute("DELETE FROM ops_comp_links WHERE comp_id=?", (cid,))
    for s in skus:
        if str(s).strip():
            c.execute("INSERT OR IGNORE INTO ops_comp_links(comp_id, sku) VALUES(?,?)", (cid, str(s).strip().upper()[:60]))
    c.commit()


def delete_snap(sid):
    _c().execute("DELETE FROM ops_comp_snaps WHERE id=?", (sid,))
    _c().commit()


def add_snap(cid, data, source="manual", ts=None):
    """记一次竞品数据，和上一次比较，变化写进 ops_comp_events（今日待办和手机提醒用）。"""
    comp = get(cid)
    if not comp:
        raise ValueError("没有这个竞品")
    before = snaps(cid)
    sold, _g = parse_count(data.get("sold_text") if data.get("sold_text") not in (None, "") else data.get("sold_total"))
    s30, _ = parse_count(data.get("sold_30d"))
    rev, _ = parse_count(data.get("reviews"))
    fs = data.get("free_ship")
    row = {"price": num(data.get("price")), "list_price": num(data.get("list_price")), "voucher": num(data.get("voucher")),
           "sold_total": sold, "sold_text": str(data.get("sold_text") or data.get("sold_total") or "")[:30] or None,
           "sold_30d": s30, "rating": num(data.get("rating")), "reviews": rev,
           "free_ship": None if fs in (None, "") else (1 if str(fs).lower() in ("1", "true", "yes", "on") else 0),
           "title": (data.get("title") or "")[:300] or None}
    if row["rating"] is not None and not 0 <= row["rating"] <= 5:
        row["rating"] = None
    if row["price"] is None and row["sold_total"] is None and row["reviews"] is None:
        raise ValueError("至少要有售价、累计已售或评价数中的一个")
    c = _c()
    ts = ts or time.time()
    c.execute(f"INSERT INTO ops_comp_snaps(comp_id, ts, {', '.join(SNAP_FIELDS)}, source) VALUES(?,?,{','.join('?' * len(SNAP_FIELDS))},?)",
              (cid, ts, *[row[k] for k in SNAP_FIELDS], source))
    if row["title"] and not comp.get("title"):
        c.execute("UPDATE ops_comp SET title=? WHERE id=?", (row["title"], cid))
    if data.get("shop") and not comp.get("shop"):
        c.execute("UPDATE ops_comp SET shop=? WHERE id=?", (str(data["shop"])[:120], cid))
    c.execute("UPDATE ops_comp SET updated_at=? WHERE id=?", (ts, cid))
    c.commit()
    if before:
        _events(get(cid), before, snaps(cid))
    return row


def _events(comp, before, after):
    cfg = load_config()
    prev, cur = before[-1], after[-1]
    name = (comp.get("title") or comp.get("item_key") or f"#{comp['id']}")[:40]
    ev = []
    pct = tf(cfg.get("oa_comp_price_drop_pct"), 5)
    pe0, pe1 = _eff(prev), _eff(cur)
    if pe0 and pe1 and pe1 < pe0 * (1 - pct / 100):
        d = (1 - pe1 / pe0) * 100
        ev.append(("price_drop", f"📉 竞品降价：{name} ฿{pe0:g} → ฿{pe1:g}（-{d:.0f}%）", f"📉 คู่แข่งลดราคา: {name} ฿{pe0:g} → ฿{pe1:g} (-{d:.0f}%)"))
    elif pe0 and pe1 and pe1 > pe0 * (1 + pct / 100):
        ev.append(("price_up", f"📈 竞品涨价：{name} ฿{pe0:g} → ฿{pe1:g}", f"📈 คู่แข่งขึ้นราคา: {name} ฿{pe0:g} → ฿{pe1:g}"))
    if (cur.get("voucher") or 0) > 0 and not (prev.get("voucher") or 0):
        ev.append(("voucher", f"🎟️ 竞品开了优惠券：{name} 减 ฿{cur['voucher']:g}", f"🎟️ คู่แข่งเปิดคูปอง: {name} ลด ฿{cur['voucher']:g}"))
    if cur.get("title") and prev.get("title") and cur["title"] != prev["title"]:
        ev.append(("title", f"✏️ 竞品改了标题：{name} → {cur['title'][:60]}", f"✏️ คู่แข่งเปลี่ยนชื่อสินค้า: {name} → {cur['title'][:60]}"))
    e0, e1 = _sales(cfg, comp, before), _sales(cfg, comp, after)
    if e1["daily"] and e0["daily"] and e1["daily"] >= max(1, e0["daily"] * 2):
        ev.append(("surge", f"🔥 竞品放量：{name} 日销 {e0['daily']:g} → {e1['daily']:g} 件",
                   f"🔥 คู่แข่งยอดพุ่ง: {name} ขายต่อวัน {e0['daily']:g} → {e1['daily']:g} ชิ้น"))
    c = _c()
    for kind, text, text_th in ev:
        c.execute("INSERT INTO ops_comp_events(comp_id, ts, kind, text, text_th) VALUES(?,?,?,?,?)", (comp["id"], time.time(), kind, text, text_th))
    c.commit()


def events(days=14, limit=100):
    return [dict(r) for r in _c().execute("""SELECT e.*, c.title, c.platform, c.image FROM ops_comp_events e LEFT JOIN ops_comp c ON c.id=e.comp_id
                                             WHERE e.ts>=? ORDER BY e.ts DESC LIMIT ?""", (time.time() - days * 86400, limit))]


# ---------------- 推算 ----------------
def _eff(s):
    """到手价 = 售价 − 优惠券。"""
    if not s or s.get("price") is None:
        return None
    return round(max(0.0, s["price"] - (s.get("voucher") or 0)), 2)


def _gran(s):
    _, g = parse_count(s.get("sold_text")) if s.get("sold_text") else (None, 1)
    return g or 1


def _sales(cfg, comp, ss):
    out = {"daily": None, "method": None, "method_th": None, "confidence": None, "note": "", "note_th": "", "window_days": None}
    if not ss:
        out.update(note="还没有数据：填一次售价和累计已售", note_th="ยังไม่มีข้อมูล: กรอกราคาและยอดขายสะสมหนึ่งครั้ง")
        return out
    last = ss[-1]
    sold = [s for s in ss if s.get("sold_total") is not None]
    if len(sold) >= 2:
        L = sold[-1]
        older = [s for s in sold if L["ts"] - s["ts"] >= 0.8 * 86400]
        if older:
            base = next((s for s in reversed(older) if L["ts"] - s["ts"] >= 6.5 * 86400), older[0])
            days = (L["ts"] - base["ts"]) / 86400
            delta = L["sold_total"] - base["sold_total"]
            g = max(_gran(L), _gran(base))
            if delta < 0:
                out.update(note="累计已售比上次少（平台可能重新计数），这次不用它算",
                           note_th="ยอดขายสะสมน้อยกว่าครั้งก่อน (แพลตฟอร์มอาจนับใหม่) ครั้งนี้ไม่ใช้")
            elif g > 1 and delta < g:
                out.update(note=f"累计已售是约数（精度 {g:g} 件），{days:.0f} 天内还看不出变化，下面用其他方法估",
                           note_th=f"ยอดขายสะสมเป็นตัวเลขปัด (ละเอียด {g:g} ชิ้น) {days:.0f} วันยังไม่เห็นความเปลี่ยนแปลง ใช้วิธีอื่นประมาณ")
            else:
                out.update(daily=round(delta / days, 2), method=f"累计已售差值（{days:.1f} 天）", method_th=f"ผลต่างยอดขายสะสม ({days:.1f} วัน)",
                           window_days=round(days, 1), confidence="实测" if g <= 1 or delta >= 3 * g else "估")
                return out
    if last.get("sold_30d"):
        out.update(daily=round(last["sold_30d"] / 30, 2), method="页面上的近 30 天已售", method_th="ยอดขาย 30 วันบนหน้าเว็บ", confidence="实测")
        return out
    rv = [s for s in ss if s.get("reviews") is not None]
    if len(rv) >= 2 and rv[-1]["ts"] - rv[0]["ts"] >= 0.8 * 86400:
        L = rv[-1]
        base = next((s for s in reversed(rv) if L["ts"] - s["ts"] >= 6.5 * 86400), rv[0])
        days = (L["ts"] - base["ts"]) / 86400
        rate, own = _review_rate(cfg, comp, last)
        dr = L["reviews"] - base["reviews"]
        if dr >= 0:
            out.update(daily=round(dr / rate / days, 2), window_days=round(days, 1), confidence="估",
                       method=f"评价数差值 ÷ 留评比例 {rate:.0%}（{'按它自己的 评价/已售 校准' if own else '设置里的默认比例'}）",
                       method_th=f"ผลต่างจำนวนรีวิว ÷ อัตรารีวิว {rate:.0%} ({'ปรับจาก รีวิว/ยอดขาย ของมันเอง' if own else 'อัตราที่ตั้งไว้'})")
            return out
    if comp.get("listed_on") and last.get("sold_total"):
        try:
            age = (time.time() - dt.datetime.fromisoformat(comp["listed_on"]).timestamp()) / 86400
            if age >= 1:
                out.update(daily=round(last["sold_total"] / age, 2), confidence="估",
                           method=f"累计已售 ÷ 上架 {age:.0f} 天（平均数）", method_th=f"ยอดขายสะสม ÷ ลงขาย {age:.0f} วัน (ค่าเฉลี่ย)")
                return out
        except ValueError:
            pass
    if not out["note"]:
        out.update(note="过 1 天以上再记一次累计已售，就能算出日销（或者填上架日期先粗估）",
                   note_th="บันทึกยอดขายสะสมอีกครั้งหลัง 1 วันขึ้นไปจะคำนวณยอดขายต่อวันได้ (หรือกรอกวันลงขายเพื่อประมาณคร่าวๆ)")
    return out


def _review_rate(cfg, comp, last):
    if last.get("sold_total") and last.get("reviews") and last["sold_total"] >= 20:
        return min(0.9, max(0.02, last["reviews"] / last["sold_total"])), True
    d = {"lazada": 0.15, "shopee": 0.35, "tiktok": 0.10}.get(comp.get("platform") or "lazada", 0.15)
    r = tf(cfg.get(f"oa_review_rate_{comp.get('platform') or 'lazada'}"), d)
    return (r / 100 if r > 1 else r) or d, False


def _unit_cost(cfg, comp, linked):
    """返回 (单件生产成本, 来源中文, 来源泰文, 来源键)。优先：手动 > 选定的来源 > 关联的我方 SKU（ERP 成本）> AI 估克重时长 × ERP 成本参数。"""
    ai_cost = erp_unit_cost(comp.get("est_grams"), comp.get("est_hours"), (comp.get("est_material") or "").upper() == "RESIN", cfg)
    sku_vals = [r["unit_cost"] for r in linked if r.get("unit_cost")]
    options = {
        "manual": (comp.get("est_unit_cost"), "手动填的", "กรอกเอง"),
        "sku": (round(statistics.mean(sku_vals), 2) if sku_vals else None, "关联的我方 SKU（ERP 成本）", "SKU ของเราที่ผูกไว้ (ต้นทุนใน ERP)"),
        "ai": (ai_cost, f"AI 估 {comp.get('est_grams') or '?'}g / {comp.get('est_hours') or '?'}h × ERP 成本参数",
               f"AI ประมาณ {comp.get('est_grams') or '?'}g / {comp.get('est_hours') or '?'}h × ค่าต้นทุนใน ERP"),
    }
    order = [comp.get("cost_source")] if comp.get("cost_source") in options else []
    for k in order + ["manual", "sku", "ai"]:
        v, zh, th = options[k]
        if v is not None:
            return v, zh, th, k
    return None, "未知：点「AI 估成本」或手动填", "ยังไม่รู้: กด「AI ประมาณต้นทุน」หรือกรอกเอง", None


def estimate(cfg, comp, ss=None, linked=None, skus=None):
    ss = snaps(comp["id"]) if ss is None else ss
    if linked is None:
        skus = sku_rows(cfg) if skus is None else skus
        linked = [skus[s] for s in links(comp["id"]) if s in skus]
    last = ss[-1] if ss else {}
    s = _sales(cfg, comp, ss)
    price = _eff(last)
    if comp.get("fee_rate_override") is not None:
        rate, fee_src, fee_th = comp["fee_rate_override"], "这个竞品手动填的", "กรอกเองสำหรับคู่แข่งนี้"
    else:
        rate, fee_src, fee_th = fee_rate(comp.get("platform"), cfg)
    cost, cost_src, cost_th, cost_key = _unit_cost(cfg, comp, linked)
    fee_unit = round(price * rate, 2) if price is not None else None
    profit_unit = round(price - fee_unit - cost, 2) if price is not None and cost is not None else None
    d = s["daily"]

    def mul(x, n):
        return round(x * n, 2) if x is not None and d is not None else None
    stale_days = tf(cfg.get("oa_comp_stale_days"), 7)
    return {
        **s, "d7": round(d * 7, 1) if d is not None else None, "d30": round(d * 30, 1) if d is not None else None,
        "price_eff": price, "price": last.get("price"), "voucher": last.get("voucher"), "list_price": last.get("list_price"),
        "sold_total": last.get("sold_total"), "sold_text": last.get("sold_text"), "reviews": last.get("reviews"), "rating": last.get("rating"),
        "free_ship": last.get("free_ship"),
        "fee_rate": rate, "fee_src": fee_src, "fee_src_th": fee_th, "fee_unit": fee_unit,
        "unit_cost": cost, "cost_src": cost_src, "cost_src_th": cost_th, "cost_key": cost_key,
        "profit_unit": profit_unit, "margin": round(profit_unit / price * 100, 1) if profit_unit is not None and price else None,
        "rev_daily": mul(price, 1), "rev_7d": mul(price, 7), "rev_30d": mul(price, 30),
        "fee_7d": mul(fee_unit, 7), "fee_30d": mul(fee_unit, 30),
        "profit_daily": mul(profit_unit, 1), "profit_7d": mul(profit_unit, 7), "profit_30d": mul(profit_unit, 30),
        "print_hours_daily": round(d * comp["est_hours"], 1) if d is not None and comp.get("est_hours") else None,
        "last_ts": last.get("ts"), "n_snaps": len(ss),
        "stale": bool(last.get("ts")) and time.time() - last["ts"] > stale_days * 86400,
    }


def listing(cfg=None, include_archived=False, skus=None):
    cfg = cfg or load_config()
    c = _c()
    q = "SELECT * FROM ops_comp" + ("" if include_archived else " WHERE status='active'") + " ORDER BY id DESC"
    comps = [dict(r) for r in c.execute(q)]
    all_links = {}
    for r in c.execute("SELECT comp_id, sku FROM ops_comp_links"):
        all_links.setdefault(r["comp_id"], []).append(r["sku"])
    all_snaps = {}
    for r in c.execute("SELECT * FROM ops_comp_snaps ORDER BY ts"):
        all_snaps.setdefault(r["comp_id"], []).append(dict(r))
    skus = sku_rows(cfg) if skus is None else skus
    out = []
    for comp in comps:
        ls = sorted(all_links.get(comp["id"], []))
        e = estimate(cfg, comp, ss=all_snaps.get(comp["id"], []), linked=[skus[s] for s in ls if s in skus])
        out.append({**comp, "skus": ls, "est": e})
    return out


def compare(cfg=None, rows=None, skus=None):
    """我方 SKU vs 关联竞品：价格位置、日销对比、单件利润对比、对标日销（给计划定目标用）。"""
    cfg = cfg or load_config()
    skus = sku_rows(cfg) if skus is None else skus
    rows = listing(cfg, skus=skus) if rows is None else rows
    groups = {}
    for r in rows:
        for s in r["skus"]:
            groups.setdefault((s, r["platform"]), []).append(r)
    out = []
    for (sku, plat), comps in groups.items():
        me = skus.get(sku) or {"sku": sku, "name": None}
        prices = sorted(c["est"]["price_eff"] for c in comps if c["est"]["price_eff"] is not None)
        dailies = [c["est"]["daily"] for c in comps if c["est"]["daily"] is not None]
        rate, _s, _t = fee_rate(plat, cfg)
        my_price = me.get("price")
        my_profit = round(my_price * (1 - rate) - me["unit_cost"], 2) if my_price and me.get("unit_cost") else None
        pos = None
        if my_price and prices:
            cheaper = sum(1 for p in prices if p < my_price - 0.01)
            pos = {"rank": cheaper + 1, "of": len(prices) + 1}
        med = statistics.median(prices) if prices else None
        out.append({
            "sku": sku, "product_id": me.get("product_id"), "platform": plat, "name": me.get("name"), "color": me.get("variant"),
            "in_erp": sku in skus, "my_price": my_price, "floor_price": me.get("floor_price"), "my_unit_cost": me.get("unit_cost"),
            "my_profit_unit": my_profit, "my_daily": sku_avg_daily(sku, plat, 30), "comp_count": len(comps),
            "comp_price_min": prices[0] if prices else None, "comp_price_median": med, "comp_price_max": prices[-1] if prices else None,
            "price_pos": pos, "price_vs_median_pct": round((my_price / med - 1) * 100, 1) if my_price and med else None,
            "comp_daily_top": max(dailies) if dailies else None, "comp_daily_median": statistics.median(dailies) if dailies else None,
            "comp_daily_total": round(sum(dailies), 2) if dailies else None, "comp_ids": [c["id"] for c in comps],
        })
    out.sort(key=lambda x: -(x["comp_daily_total"] or 0))
    return out


def benchmark(cfg, sku, platform):
    for g in compare(cfg):
        if g["sku"] == (sku or "").upper() and (not platform or g["platform"] == platform):
            return g
    return None


def radar(cfg=None, rows=None):
    """选品雷达：还没关联我方 SKU 的竞品，按推算的月利润排（不做的排最后）。"""
    cfg = cfg or load_config()
    rows = listing(cfg) if rows is None else rows
    cap = capacity_hours(cfg)
    out = []
    for r in rows:
        if r["skus"] or r.get("radar_status") == "done":
            continue
        e = r["est"]
        out.append({"id": r["id"], "platform": r["platform"], "title": r["title"], "url": r["url"], "shop": r["shop"], "image": r.get("image"),
                    "radar_status": r.get("radar_status") or "new", "daily": e["daily"], "confidence": e["confidence"],
                    "price_eff": e["price_eff"], "profit_unit": e["profit_unit"], "profit_30d": e["profit_30d"],
                    "margin": e["margin"], "print_hours_daily": e["print_hours_daily"],
                    "capacity_share": round(e["print_hours_daily"] / cap * 100, 1) if e["print_hours_daily"] and cap else None})
    out.sort(key=lambda x: (x["radar_status"] == "skip", -(x["profit_30d"] if x["profit_30d"] is not None else -1e9)))
    return out


# ---------------- AI ----------------
def extract(cfg, text, url=""):
    """粘贴的页面文字 → 售价、已售、评价……。配了 AI 用 AI，没配用规则（只认最常见的写法）。返回 (数据, 'ai'|'rules')。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("先粘贴商品页的文字")
    if not ai_on(cfg):
        return card_numbers(text), "rules"
    r = ai_json(cfg, EXTRACT_SYS, f"链接：{url}\n\n页面文字：\n{text[:12000]}")
    keep = ("title", "shop", "price", "list_price", "voucher", "sold_text", "sold_30d", "rating", "reviews", "free_ship", "variants", "size_text")
    return {k: r.get(k) for k in keep}, "ai"


def ai_cost(cfg, cid):
    comp = get(cid)
    if not comp:
        raise ValueError("没有这个竞品")
    ss = snaps(cid)
    last = ss[-1] if ss else {}
    refs = [s for s in sku_rows(cfg).values() if s.get("grams") and s.get("hours")][:20]
    ref_txt = "\n".join(f"- {r['name']} {r['variant'] or ''}：{float(r['grams']):g}g，{float(r['hours']):g}h，{r['material'] or 'PLA'}" for r in refs) or "（暂无）"
    user = (f"平台：{comp['platform']}\n标题：{comp.get('title') or last.get('title') or ''}\n售价：{last.get('price')}\n"
            f"备注 / 规格：{comp.get('note') or ''}\n\n我们自己产品的真实数据：\n{ref_txt}")
    r = ai_json(cfg, COST_SYS, user)
    g, h = num(r.get("grams")), num(r.get("hours"))
    if not g or not h:
        raise AiError("AI 没给出克重和时长，请补充标题或尺寸后再试")
    reason = f"{r.get('reason') or ''}（尺寸猜测 {r.get('size_guess') or '?'}，把握 {r.get('confidence') or '?'}）"
    update(cid, {"est_grams": g, "est_hours": h, "est_material": str(r.get("material") or "PLA").upper()[:10], "cost_note": reason[:300]})
    return {"grams": g, "hours": h, "material": r.get("material"), "reason": reason}


# ---------------- 插件采集 ----------------
def _from_ld(ld):
    """商品页里的 JSON-LD（Lazada 有）：补标题、价格、评分、评价数、主图。"""
    out = {}
    items = ld if isinstance(ld, list) else [ld]
    flat = []
    for it in items:
        if isinstance(it, dict) and "@graph" in it:
            flat += it["@graph"]
        else:
            flat.append(it)
    for it in flat:
        if not isinstance(it, dict) or "Product" not in str(it.get("@type")):
            continue
        out["title"] = it.get("name")
        offers = it.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = offers.get("lowPrice") or offers.get("price") if isinstance(offers, dict) else None
        if price:
            out["price"] = price
        ar = it.get("aggregateRating") or {}
        if isinstance(ar, dict):
            if ar.get("ratingValue"):
                out["rating"] = ar["ratingValue"]
            if ar.get("reviewCount") or ar.get("ratingCount"):
                out["reviews"] = ar.get("reviewCount") or ar.get("ratingCount")
        img = it.get("image")
        if isinstance(img, list):
            img = img[0] if img else None
        if isinstance(img, dict):
            img = img.get("url")
        if img:
            out["image"] = img
        break
    return out


def capture_competitor(cfg, body):
    """插件在商品页点「采集竞品」：页面文字 → AI 识别（没配 AI 用规则）+ JSON-LD 补。"""
    url = (body.get("url") or "").strip()
    text = (body.get("text") or "")[:20000]
    if not url or not text:
        raise ValueError("没收到页面内容")
    plat, key = parse_url(url)
    if not plat:
        raise ValueError("这个页面不是 Lazada / Shopee / TikTok 的商品页")
    ld = {}
    for blob in (body.get("ld") or [])[:5]:
        try:
            ld = _from_ld(json.loads(blob) if isinstance(blob, str) else blob)
        except (ValueError, TypeError):
            continue
        if ld:
            break
    try:
        data, how = extract(cfg, text, url)
    except AiError:                              # AI 出错（密钥不对、网络）：先用规则 + JSON-LD 记下来，不让采集白点
        data, how = card_numbers(text), "rules"
    for k, v in ld.items():
        if data.get(k) in (None, "") and k in ("title", "price", "rating", "reviews"):
            data[k] = v
    if not data.get("title"):
        data["title"] = body.get("title") or ""
    data["image"] = body.get("image") or ld.get("image")
    res = _upsert(cfg, url, plat, key, data, how, body.get("skus"))
    if body.get("shop_url"):                     # 顺手记下它的店铺（进「竞店」的候选）
        from . import shops
        res["shop_id"] = shops.seen(body["shop_url"], res["id"], body.get("shop_name") or data.get("shop") or "")
    return res


def capture_card(cfg, body):
    """列表页上的商品卡片：先用规则识别（快、不花 AI 费用），没认出价格才交给 AI。"""
    url = (body.get("url") or "").strip()
    text = (body.get("text") or "")[:3000]
    plat, key = parse_url(url)
    if not plat or not key or key == url.split("?")[0]:
        raise ValueError("这张卡片的链接认不出商品编号")
    data = card_numbers(text)
    how = "rules"
    if data.get("price") is None and ai_on(cfg):
        data, how = extract(cfg, text, url)
    data["title"] = data.get("title") or (body.get("title") or "")[:300]
    data["image"] = body.get("image")
    if data.get("price") is None and data.get("sold_text") in (None, ""):
        raise ValueError("卡片上没认出价格和已售，打开商品页再点「采集竞品」")
    return _upsert(cfg, url, plat, key, data, how, body.get("skus"), source="插件·列表")


def known(urls):
    """页面上这些商品链接里，哪些已经在竞品库里（给卡片打「已采集」标记）。"""
    keys = {}
    for u in (urls or [])[:300]:
        _p, k = parse_url(u)
        if k:
            keys.setdefault(k, []).append(u)
    if not keys:
        return {}
    rows = _c().execute(f"SELECT id, item_key FROM ops_comp WHERE status='active' AND item_key IN ({','.join('?' * len(keys))})",
                        list(keys)).fetchall()
    out = {}
    for r in rows:
        for u in keys.get(r["item_key"], []):
            out[u] = r["id"]
    return out


def compare_rows(cfg, ids):
    """横向对比：每个竞品一列（最多 10 个）。"""
    out = []
    for cid in ids[:10]:
        comp = get(cid)
        if not comp:
            continue
        out.append({"id": cid, "title": comp.get("title"), "shop": comp.get("shop"), "platform": comp.get("platform"),
                    "image": comp.get("image"), "url": comp.get("url"), "skus": links(cid), "est": estimate(cfg, comp)})
    return out


def _upsert(cfg, url, plat, key, data, how, skus=None, source="插件"):
    c = _c()
    old = c.execute("SELECT id FROM ops_comp WHERE item_key=?", (key,)).fetchone() if key else None
    if old:
        cid, new = old["id"], False
        c.execute("UPDATE ops_comp SET status='active' WHERE id=?", (cid,))
        c.commit()
        set_image(cid, data.get("image"))
        last = c.execute("SELECT id, ts FROM ops_comp_snaps WHERE comp_id=? ORDER BY ts DESC LIMIT 1", (cid,)).fetchone()
        if last and time.time() - last["ts"] < 1800:      # 半小时内重复点：覆盖上一条，不算新的一天
            c.execute("DELETE FROM ops_comp_snaps WHERE id=?", (last["id"],))
            c.commit()
        try:
            add_snap(cid, data, source=source)
        except ValueError:
            pass
        if skus:
            set_links(cid, skus, add_only=True)
    else:
        payload = {**data, "url": url.split("?")[0] if plat != "lazada" else url, "platform": plat, "source": source,
                   "note": " ".join(str(x) for x in (data.get("size_text"), data.get("variants")) if x)[:300]}
        if skus:
            payload["skus"] = skus
        cid, new = create(payload)
        if new and not skus and ai_on(cfg):     # 新竞品还没关联我方 SKU：顺手让 AI 估克重和时长，利润马上能算
            try:
                ai_cost(cfg, cid)
            except (ValueError, AiError):
                pass
    return result(cfg, cid, new, data, how)


def result(cfg, cid, new=False, data=None, how=""):
    comp = get(cid)
    sk = links(cid)
    est = estimate(cfg, comp)
    cmp = [g for g in compare(cfg) if cid in g["comp_ids"]]
    return {"id": cid, "new": new, "how": how, "data": {k: v for k, v in (data or {}).items() if k != "image"},
            "title": comp.get("title"), "platform": comp.get("platform"), "image": comp.get("image"),
            "skus": sk, "est": est, "compare": cmp, "radar": not sk}
