"""商品生命周期（从运营分析系统 modules/products/products.py 搬过来，改成直接读 ERP）：每个 SKU × 平台一行，算阶段和建议动作。

数据：
  · 上架状态、第一次在售时间：产品里的 listing（core/listing.py v1_view，和 /api/v1/skus 一样）
  · 在线商品（上架模块从 Lazada 拉回来的）：平台状态、商品在平台上建的时间（listing 里没有第一次在售时间时用它，标「估」）
  · 销量：ERP 订单（不算取消 / 退货 / 未付款 / 报价 / 拒收，和财务一样），30 天利润用 core.finance.order_profit 按商品金额比例分摊
测款期从「第一次在售」算；没有就退回「第一次上传」，再退回「导出时间」，标「估」。Lazada、Shopee 分开算。
规则（设置 → 运营分析可改）：测款期 oa_test_days 天内 → 观察；到期没出单 → 换图换标题再测；oa_retest_days 天还没出单 → 建议下架；
出过单：近 30 天 ≥ oa_hero_qty_30d 件 → 主推；连续 oa_decline_days 天零销量 → 衰退；oa_delist_days 天零销量 → 建议下架。
"""
import time

from core import db, listing
from core.config import load_config

STAGES = {   # key: (中文, 泰文, 级别, 建议动作中文, 建议动作泰文)
    "draft": ("草稿·待完善", "ฉบับร่าง", "mute", "选品来的新品：补颜色、SKU、售价（克数 / 时长待补的先补上），再导出上架",
              "สินค้าใหม่จากการคัดเลือก: เติมสี SKU ราคา (กรัม/เวลาพิมพ์) แล้วส่งออกลงขาย"),
    "unlisted": ("未上架", "ยังไม่ลงขาย", "mute", "导出并上传到平台", "ส่งออกและอัปโหลดขึ้นแพลตฟอร์ม"),
    "review": ("审核中", "รอตรวจ", "mute", "等平台审核", "รอแพลตฟอร์มตรวจ"),
    "rejected": ("审核不通过", "ไม่ผ่านการตรวจ", "bad", "在平台后台按原因修改后重新提交（不要重新导出新建）",
                 "แก้ตามเหตุผลในหลังร้านแล้วส่งใหม่ (อย่าส่งออกสร้างใหม่)"),
    "delisted": ("已下架", "ปิดการขายแล้ว", "mute", "", ""),
    "erp_off": ("ERP 已下架", "ปิดใน ERP แล้ว", "warn", "ERP 里已下架，记得到平台上也下架", "ปิดใน ERP แล้ว อย่าลืมปิดบนแพลตฟอร์มด้วย"),
    "testing": ("测款期", "ช่วงทดสอบ", "info", "观察点击和加购；可加入店铺活动、参加新品活动", "ดูยอดคลิกและหยิบใส่ตะกร้า เข้าร่วมแคมเปญร้าน/สินค้าใหม่ได้"),
    "retest": ("未出单·再测", "ยังไม่มีออเดอร์·ทดสอบใหม่", "warn", "换主图和标题关键词，再测一轮", "เปลี่ยนรูปหลักและคีย์เวิร์ดในชื่อ แล้วทดสอบอีกรอบ"),
    "delist": ("建议下架", "ควรปิดการขาย", "bad", "下架腾出上架额度给新款", "ปิดการขายเพื่อเว้นโควตาให้สินค้าใหม่"),
    "growing": ("成长", "กำลังโต", "ok", "补评价、报名平台活动、优化标题关键词", "เพิ่มรีวิว สมัครแคมเปญ ปรับคีย์เวิร์ดในชื่อ"),
    "hero": ("主推", "สินค้าหลัก", "good", "重点资源：活动、优惠券、备足耗材和产能", "ทุ่มทรัพยากร: แคมเปญ คูปอง เตรียมวัสดุและกำลังผลิตให้พอ"),
    "declining": ("衰退", "ขายลดลง", "warn", "停止推进动作；看是否被竞品替代，必要时降价清掉或下架",
                  "หยุดโปรโมต ดูว่าถูกคู่แข่งแทนไหม ถ้าจำเป็นลดราคาเคลียร์หรือปิดการขาย"),
}
NOT_ON_SALE = ("draft", "unlisted", "review", "rejected")
STAGE_ORDER = ["rejected", "delist", "retest", "erp_off", "declining", "hero", "growing", "testing", "review", "unlisted", "draft", "delisted"]
PLATFORMS = ("lazada", "shopee")


def rules(cfg=None):
    cfg = cfg or load_config()

    def i(k, d):
        try:
            return max(1, int(float(cfg.get(k) if cfg.get(k) not in (None, "") else d)))
        except (TypeError, ValueError):
            return d
    r = {"test_days": i("oa_test_days", 14), "retest_days": i("oa_retest_days", 30), "hero_qty_30d": i("oa_hero_qty_30d", 10),
         "decline_days": i("oa_decline_days", 30), "delist_days": i("oa_delist_days", 60)}
    r["retest_days"] = max(r["retest_days"], r["test_days"] + 1)
    r["delist_days"] = max(r["delist_days"], r["decline_days"] + 1)
    return r


def _sales():
    """{(SKU 大写, 平台): {orders:[(时间, 件数)], qty_total, qty_7d, qty_30d, profit_30d, last_sale}}"""
    from core.finance import EXCLUDE
    from .dash import profits
    c = db.conn()
    now = time.time()
    out = {}
    rows = c.execute(f"SELECT o.platform, o.order_time, UPPER(i.sku) sku, i.qty FROM order_items i JOIN orders o ON o.id=i.order_id "
                     f"WHERE o.status NOT IN ({','.join('?' * len(EXCLUDE))}) AND COALESCE(i.sku,'')!=''", EXCLUDE).fetchall()
    for r in rows:
        a = out.setdefault((r["sku"], (r["platform"] or "").lower()),
                           {"orders": [], "qty_total": 0, "qty_7d": 0, "qty_30d": 0, "profit_30d": 0.0, "last_sale": None})
        q = r["qty"] or 1
        t = r["order_time"] or 0
        a["orders"].append((t, q))
        a["qty_total"] += q
        if now - t <= 7 * 86400:
            a["qty_7d"] += q
        if now - t <= 30 * 86400:
            a["qty_30d"] += q
        a["last_sale"] = max(a["last_sale"] or 0, t) or None
    cfg = load_config()
    for o, its, p in profits(now - 30 * 86400, cfg=cfg):
        tot = sum((i["item_total"] or 0) for i in its)
        for i in its:
            k = (str(i["sku"] or "").upper(), (o["platform"] or "").lower())
            if k in out:
                share = (i["item_total"] or 0) / tot if tot else 1 / max(1, len(its))
                out[k]["profit_30d"] += p["profit"] * share
    return out


def _start(lst, online, exported_at):
    """测款起点：第一次在售 > 在线商品在平台上建的时间（估）> 第一次上传（估）> 导出时间（估）。返回 (时间, 是不是估的)。"""
    if lst.get("first_listed_at"):
        return lst["first_listed_at"], False
    created = [o["created"] for o in online if o.get("created")]
    if created:
        return min(created), True
    if lst.get("first_uploaded_at"):
        return lst["first_uploaded_at"], True
    if exported_at:
        return exported_at, True
    return None, True


def _stage(r, lst, online, start, sales, now):
    st = lst.get("status")
    if st == "update":                         # 有修改待同步：按平台上现在的状态判断
        st = lst.get("platform_status") or "live"
    on = [o["status"] for o in online]
    if "live" in on and st not in ("live", "inactive"):
        st = "live"                             # 平台上已经在卖（在线商品为准）
    elif on and st in ("none", "pending", "failed", None):
        st = on[0]
    if lst.get("erp_active") is False and st == "live":
        return "erp_off"
    if st in ("none", "pending", "failed", None, "deleted"):
        return "unlisted"
    if st == "rejected":
        return "rejected"
    if st == "inactive":
        return "delisted"
    if st == "uploaded":
        return "review"
    if not start:
        return "unlisted"
    days = (now - start) / 86400
    sold_since = sum(q for t, q in (sales or {}).get("orders", []) if t and t >= start - 86400)
    if not sold_since:
        if days < r["test_days"]:
            return "testing"
        if days < r["retest_days"]:
            return "retest"
        return "delist"
    idle = (now - (sales.get("last_sale") or start)) / 86400
    if idle >= r["delist_days"]:
        return "delist"
    if idle >= r["decline_days"]:
        return "declining"
    if sales["qty_30d"] >= r["hero_qty_30d"]:
        return "hero"
    return "growing"


def _trf(t):
    if not t:
        return None
    return {k: t.get(k) for k in ("visitors", "views", "add_to_cart", "orders", "conversion", "period_text", "ts")}


def board(cfg=None):
    from core import modules
    from .dash import price_rows
    cfg = cfg or load_config()
    r = rules(cfg)
    now = time.time()
    lstm = modules.public("listing")
    online = {}
    if lstm and hasattr(lstm, "online_skus"):
        try:
            online = lstm.online_skus()
        except Exception:  # noqa: BLE001
            online = {}
    sales = _sales()
    try:                                   # v2.48：卖家后台流量（浏览器扩展采集）
        from . import traffic
        trf = traffic.by_sku()
    except Exception:  # noqa: BLE001
        trf = {}
    rows = []
    views = {}
    for pr in price_rows(cfg):
        p = pr["product"]
        if p["id"] not in views:
            views[p["id"]] = listing.v1_view(p)
        view = views[p["id"]]
        for plat in PLATFORMS:
            lst = view.get(plat) or {}
            onl = [o for o in online.get(pr["sku"], []) if o["platform"] == plat]
            if lst.get("status") in ("none", None) and not onl and plat != "lazada":
                # 没上过 Shopee 的不列（每个产品只列一行「Lazada 未上架」，不然列表一半都是空的 Shopee）
                continue
            sa = sales.get((pr["sku"], plat)) or {"orders": [], "qty_total": 0, "qty_7d": 0, "qty_30d": 0, "profit_30d": 0.0, "last_sale": None}
            start, est = _start(lst, onl, p.get("exported_at"))
            stage = "draft" if pr["draft"] else _stage(r, lst, onl, start, sa, now)
            zh, th, level, act, act_th = STAGES[stage]
            if stage == "review" and lst.get("first_uploaded_at") and now - lst["first_uploaded_at"] > 3 * 86400:
                act, act_th = "上传已超过 3 天还在审核：到平台后台看一下", "อัปโหลดเกิน 3 วันแล้วยังรอตรวจ: เข้าไปดูในหลังร้าน"
            if stage == "rejected" and lst.get("note"):
                act += f"（原因：{lst['note']}）"
                act_th += f" (เหตุผล: {lst['note']})"
            end = lst.get("delisted_at") if stage == "delisted" and lst.get("delisted_at") else now
            rows.append({"sku": pr["sku"], "product_id": pr["product_id"], "name": pr["name"], "variant": pr["variant"], "platform": plat,
                         "listing_status": lst.get("status"), "online": [{"status": o["status"], "item_id": o["item_id"]} for o in onl],
                         "stage": stage, "stage_label": zh, "stage_th": th, "level": level, "action": act, "action_th": act_th,
                         "start": start, "start_estimated": bool(est and start),
                         "days_live": round(((end or now) - start) / 86400, 1) if start and stage not in NOT_ON_SALE else None,
                         "qty_total": sa["qty_total"], "qty_7d": sa["qty_7d"], "qty_30d": sa["qty_30d"],
                         "profit_30d": round(sa["profit_30d"], 2), "last_sale": sa["last_sale"],
                         "price": pr["price"], "floor_price": pr["floor_price"], "unit_cost": pr["unit_cost"],
                         "below_floor": bool(pr["price"] is not None and pr["floor_price"] and pr["price"] < pr["floor_price"] - 0.01),
                         "traffic": _trf(trf.get((pr["sku"], plat)))})
    rows.sort(key=lambda x: (STAGE_ORDER.index(x["stage"]), -x["qty_30d"], x["sku"], x["platform"]))
    counts = {}
    for x in rows:
        counts[x["stage"]] = counts.get(x["stage"], 0) + 1
    return {"rows": rows, "counts": counts, "stage_order": STAGE_ORDER, "rules": r,
            "stages": {k: {"label": v[0], "th": v[1], "level": v[2]} for k, v in STAGES.items()}}
