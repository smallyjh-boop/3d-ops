"""快速开采购单（v2.51）：把 1688 / 淘宝 / 拼多多 / Shopee / Lazada 的订单文字贴进来（或者上传订单截图），AI 读出
供应商、商品、数量、单价、运费、订单号 / 运单号 → 可以改的采购单草稿；商品按名字对到库存物品（对不上可以新建）。"""
import base64
import difflib
import io
import re

from core import ai_copy, db, inventory as inv
from core.config import load_config

from .store import ensure

SYSTEM = "你是采购助理，从电商订单里准确读出采购信息。不要编造看不到的内容，看不到就留空。只输出 JSON。"
PROMPT = """下面是一张采购订单（1688 / 淘宝 / 拼多多 / Shopee / Lazada 等平台的订单详情、订单截图或聊天里的报价）。
读出这些信息，输出 JSON：
{"platform": "1688 / 淘宝 / 拼多多 / Shopee / Lazada / 其他", "supplier": "店铺 / 卖家名称", "order_no": "平台订单号",
 "tracking": "物流单号", "carrier": "物流公司", "currency": "CNY 或 THB（人民币 ¥ / 元 = CNY，泰铢 ฿ / บาท = THB）",
 "ship_fee": 运费数字, "total": 实付总额数字,
 "items": [{"name": "商品名（原文）", "spec": "规格 / 颜色 / 型号", "qty": 数量, "unit_price": 单价数字, "net_g": 每卷克数（耗材，例如 1kg = 1000，不是耗材留空）}]}
数字只写数字（不要货币符号）。"""


def _jpeg_b64(raw):
    from PIL import Image
    im = Image.open(io.BytesIO(raw))
    im = im.convert("RGB")
    if max(im.size) > 1800:
        im.thumbnail((1800, 1800))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def _num(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))
    return float(m.group()) if m else None


def _norm(s):
    return re.sub(r"[\s\-_/·,，。()（）\[\]【】]+", "", str(s or "").lower())


def match_item(name, spec="", items=None):
    """商品名 → 最像的库存物品：[(分数, 物品)]（分数 0~1，越大越像）。耗材按 材料 + 颜色 认。"""
    items = items if items is not None else inv.items()
    text = _norm(f"{name} {spec}")
    out = []
    for it in items:
        if it["category"] == "goods":
            continue
        cand = [_norm(it.get("name_zh")), _norm(it.get("name_th")), _norm(f"{it.get('name_zh')}{it.get('spec') or ''}")]
        score = max(difflib.SequenceMatcher(None, text, c).ratio() for c in cand if c) if any(cand) else 0
        for c in cand:
            if c and len(c) >= 2 and c in text:
                score = max(score, 0.6 + min(0.35, len(c) / max(len(text), 1)))
        if it["category"] == "filament" and it.get("material") and it.get("color"):
            if _norm(it["material"]) in text and _norm(it["color"]).rstrip("色") in text:
                score = max(score, 0.9)
            elif _norm(it["material"]) in text:
                score = max(score, min(score + 0.1, 0.55))
        out.append((round(score, 3), it))
    out.sort(key=lambda x: -x[0])
    return out[:5]


def _guess_cat(name):
    n = str(name or "").lower()
    if any(w in n for w in ("pla", "petg", "tpu", "abs", "asa", "耗材", "线材", "filament")):
        return "filament"
    if any(w in n for w in ("箱", "袋", "胶带", "气泡", "面单", "包装", "纸")):
        return "pack"
    if any(w in n for w in ("喷嘴", "热床", "皮带", "风扇", "ptfe", "配件", "nozzle", "加热")):
        return "part"
    return "other"


def parse(text="", image=None):
    """AI 读订单 → 草稿（还没存）。image：图片的原始字节。"""
    ensure()
    text = str(text or "").strip()
    if not text and not image:
        raise ValueError("贴订单文字或者上传订单截图")
    cfg = load_config()
    user = PROMPT + ("\n\n订单内容：\n" + text[:6000] if text else "\n\n订单在图片里。")
    raw = ai_copy.call(ai_copy.tcfg(cfg, "pur_quick"), SYSTEM, user, _jpeg_b64(image) if image else None)
    d = ai_copy.extract_json(raw)
    return draft_from(d)


def draft_from(d):
    """AI 读出来的 JSON → 草稿：对上供应商、物品。"""
    c = db.conn()
    plat = str(d.get("platform") or "").strip()
    sname = str(d.get("supplier") or "").strip()
    cur = str(d.get("currency") or "").upper()
    if cur not in ("CNY", "THB"):
        cur = inv.default_currency(plat, sname)
    sup = None
    if sname:
        sup = c.execute("SELECT * FROM inv_suppliers WHERE active=1 AND (name=? OR name LIKE ?)", (sname, f"%{sname}%")).fetchone()
    if not sup and plat:
        sup = c.execute("SELECT * FROM inv_suppliers WHERE active=1 AND (LOWER(platform)=LOWER(?) OR LOWER(name)=LOWER(?)) ORDER BY id LIMIT 1",
                        (plat, plat)).fetchone()
    items = inv.items()
    lines = []
    for x in d.get("items") or []:
        name = str(x.get("name") or "").strip()
        if not name:
            continue
        spec = str(x.get("spec") or "").strip()
        m = match_item(name, spec, items)
        best = m[0] if m and m[0][0] >= 0.55 else None
        it = best[1] if best else None
        qty = _num(x.get("qty")) or 1
        price = _num(x.get("unit_price"))
        net_g = _num(x.get("net_g"))
        if not net_g:
            mm = re.search(r"(\d+(?:\.\d+)?)\s*(kg|公斤|千克|g|克)\b", f"{name} {spec}", re.I)
            if mm:
                net_g = float(mm.group(1)) * (1000 if mm.group(2).lower() in ("kg", "公斤", "千克") else 1)
        lines.append({"name": name, "spec": spec, "qty": qty, "unit_price": price, "net_g": net_g,
                      "item_id": it["id"] if it else None, "score": best[0] if best else (m[0][0] if m else 0),
                      "candidates": [{"id": i["id"], "code": i["code"], "name_zh": i["name_zh"], "name_th": i.get("name_th") or "",
                                      "category": i["category"], "score": s} for s, i in m[:4] if s > 0.2],
                      "new_item": None if it else {"name_zh": (name + (f" {spec}" if spec else ""))[:80], "category": _guess_cat(name + spec),
                                                   "unit": "g" if _guess_cat(name + spec) == "filament" else "个"}})
    return {"platform": plat, "supplier_name": sname, "supplier_id": sup["id"] if sup else None,
            "currency": cur, "fx_rate": inv.default_fx() if cur == "CNY" else 1.0,
            "order_ref": str(d.get("order_no") or "")[:60], "tracking": str(d.get("tracking") or "")[:60],
            "carrier": str(d.get("carrier") or "")[:40], "ship_fee": _num(d.get("ship_fee")) or 0, "total": _num(d.get("total")),
            "lines": lines}


def create(d, user=""):
    """把（改过的）草稿存成采购单：没有的供应商新建；没对上物品、要新建的建档（耗材要材料 + 颜色）；耗材按卷。"""
    ensure()
    c = db.conn()
    sid = d.get("supplier_id")
    if not sid and str(d.get("supplier_name") or "").strip():
        s = inv.save_supplier({"name": d["supplier_name"], "platform": d.get("platform") or "", "currency": d.get("currency") or ""}, user)
        sid = s["id"]
    lines = []
    for i, x in enumerate(d.get("lines") or []):
        if x.get("skip"):
            continue
        iid = x.get("item_id")
        if not iid:
            ni = x.get("new_item") or {}
            if not ni.get("name_zh"):
                raise ValueError(f"第 {i + 1} 行：选一个库存物品，或者填新物品的名字")
            it = inv.save_item({"name_zh": ni["name_zh"], "category": ni.get("category") or "other", "unit": ni.get("unit") or "个",
                                "material": ni.get("material") or "", "color": ni.get("color") or "", "supplier_id": sid}, user)
            iid = it["id"]
        it = inv.get_item(iid)
        if not it:
            raise ValueError(f"第 {i + 1} 行：没有这个物品")
        qty = _num(x.get("qty")) or 0
        price = _num(x.get("unit_price"))
        if it["category"] == "filament":
            net = _num(x.get("net_g")) or 1000
            lines.append({"item_id": iid, "rolls": int(round(qty)), "net_g": net, "unit_cost": (price / net) if price is not None else None,
                          "note": x.get("name", "")[:80]})
        else:
            lines.append({"item_id": iid, "qty": qty, "unit_cost": price, "note": x.get("name", "")[:80]})
    po = inv.save_po({"supplier_id": sid, "currency": d.get("currency") or "THB", "fx_rate": d.get("fx_rate"), "ship_fee": d.get("ship_fee") or 0,
                      "order_ref": d.get("order_ref") or "", "tracking": d.get("tracking") or "", "carrier": d.get("carrier") or "",
                      "expected_date": d.get("expected_date") or "", "lines": lines, "note": d.get("note") or "", "source": "ai"}, user)
    if sid:                       # 记下这个供应商的单价，下次补货建议直接用
        for ln in po["lines"]:
            c.execute("INSERT OR IGNORE INTO pur_item_sup(item_id, supplier_id, urls, currency, updated_at) VALUES(?,?,?,?,strftime('%s','now'))",
                      (ln["item_id"], sid, "[]", po["currency"]))
            c.execute("UPDATE pur_item_sup SET price=?, currency=? WHERE item_id=? AND supplier_id=?", (ln["unit_cost"], po["currency"], ln["item_id"], sid))
        c.commit()
    return po
