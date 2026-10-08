"""客服 AI：找资料（产品 / 订单 / 知识库 / 学到的回复）→ 让 AI 写回复 → 规则兜底。

AI 只能用这里给它的资料回答；价格、交期、订单状态都由程序算好交给它，不让它自己编。
"""
import base64
import io
import json
import math
import re

from core import ai_copy
from . import data, erp_link

INTENTS = {
    "product": "问产品（尺寸、颜色、材料、用途）",
    "price": "问价格 / 优惠",
    "stock": "问有没有货 / 多久发货",
    "order_status": "问订单 / 物流进度",
    "custom": "定制要求",
    "wholesale": "批发 / 大量询价",
    "complaint": "投诉 / 破损 / 少件",
    "refund": "退款 / 退货",
    "change_order": "改订单（地址、颜色、取消）",
    "thanks": "感谢 / 好评",
    "other": "其他",
}
HUMAN_INTENTS = ("complaint", "refund", "change_order")
# 客户需求标签（v2.22）：AI 每次从对话里认出来，存到会话上，方便找批发 / 定制客户、跟进
TAGS = ["批发", "定制", "送礼", "企业团购", "回头客", "急单", "价格敏感", "比价", "要样品", "新品询问", "售后", "差评风险", "好评", "海外 / 外地"]

# 规则识别（没有 AI 或 AI 出错时也能用；AI 结果优先）
KEYWORDS = {
    "refund": ["คืนเงิน", "คืนสินค้า", "refund", "退款", "退货", "ยกเลิกคำสั่ง"],
    "complaint": ["แตก", "หัก", "เสียหาย", "ชำรุด", "ไม่ได้รับ", "ขาด", "ผิดสี", "ส่งผิด", "broken", "damaged", "破", "坏", "少件", "发错"],
    "wholesale": ["ราคาส่ง", "ขายส่ง", "จำนวนมาก", "ล็อตใหญ่", "wholesale", "bulk", "批发", "大量", "ชิ้นขึ้นไป"],
    "custom": ["สั่งทำ", "สลัก", "ใส่ชื่อ", "ทำชื่อ", "เปลี่ยนสี", "ขยาย", "ย่อ", "custom", "定制", "刻字", "名字", "改颜色"],
    "order_status": ["เลขพัสดุ", "จัดส่งหรือยัง", "ส่งหรือยัง", "ถึงเมื่อไหร่", "พัสดุ", "ติดตาม", "tracking", "物流", "发货了吗", "到哪"],
    "change_order": ["เปลี่ยนที่อยู่", "แก้ที่อยู่", "ยกเลิก", "เปลี่ยนสี", "改地址", "取消"],
    "stock": ["มีของ", "พร้อมส่ง", "กี่วัน", "ส่งไว", "有货", "几天"],
    "price": ["ราคา", "ลด", "โค้ด", "ส่วนลด", "เท่าไหร่", "price", "discount", "多少钱", "优惠"],
    "thanks": ["ขอบคุณ", "ได้รับแล้ว", "thank", "谢谢", "收到了"],
}


def rule_intent(text):
    t = (text or "").lower()
    for k in ("refund", "complaint", "wholesale", "custom", "change_order", "order_status", "stock", "price", "thanks"):
        if any(w.lower() in t for w in KEYWORDS[k]):
            return k
    return "other"


def _qty_in(text):
    """消息里的数量（10 ชิ้น / 50 อัน / 100个 / x20）"""
    nums = [int(m) for m in re.findall(r"(\d{1,5})\s*(?:ชิ้น|อัน|ตัว|個|个|件|pcs|pieces|ea)", text or "", re.I)]
    nums += [int(m) for m in re.findall(r"[x×]\s*(\d{1,5})", text or "")]
    return max(nums) if nums else None


# ---------------- 相似度（泰文没有空格：用字符二元组） ----------------
def _grams(s):
    s = re.sub(r"\s+", " ", (s or "").lower())
    out = set()
    for w in re.findall(r"[a-z0-9]+", s):
        out.add("w:" + w)
    s2 = re.sub(r"[\sa-z0-9.,!?;:()\[\]\"'/\\-]+", "", s)
    out |= {s2[i:i + 2] for i in range(len(s2) - 1)}
    return out


def sim(a, b):
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / math.sqrt(len(ga) * len(gb))


def kb_match(text, n=5):
    rows = data.kb_list(active_only=True)
    scored = sorted(((sim(text, r["q"] + " " + (r.get("tags") or "")), r) for r in rows), key=lambda x: -x[0])
    return [dict(r, score=round(s, 3)) for s, r in scored[:n] if s > 0.08]


def example_match(text, n=4):
    rows = data.examples(400)
    scored = sorted(((sim(text, r["question"]), r) for r in rows), key=lambda x: -x[0])
    return [r for s, r in scored[:n] if s > 0.12]


def relevant_products(text, order_skus=(), n=12):
    ps = erp_link.products()
    if len(ps) <= n:
        return ps
    skus = {s.upper() for s in order_skus if s}

    def score(p):
        hay = " ".join([p["id"], p["name_zh"], p["title_th"], p["title_en"], p["keywords"]] +
                       [(v.get("sku") or "") + " " + (v.get("option_th") or "") for v in p["variants"]])
        s = sim(text, hay)
        if any((v.get("sku") or "").upper() in skus for v in p["variants"]) or p["id"].upper() in (text or "").upper():
            s += 10
        return s
    return sorted(ps, key=score, reverse=True)[:n]


# ---------------- 批发报价 / 交期 ----------------
def quote(items, tiers=None):
    """items: [{sku, qty}] → 每个 SKU 的单价（按总数量的折扣档，不低于最低售价）、合计、预计交期。"""
    tiers = tiers if tiers is not None else data.wholesale_tiers()
    total_qty = sum(int(i.get("qty") or 0) for i in items)
    disc = 0.0
    for q, d in tiers:
        if total_qty >= q:
            disc = d
    lines, hours, missing = [], 0.0, []
    for it in items:
        p, v = erp_link.sku_info(it.get("sku"))
        qty = int(it.get("qty") or 0)
        if not v or not v.get("price") or qty <= 0:
            missing.append(it.get("sku"))
            continue
        unit = v["price"] * (1 - disc / 100)
        floor = v.get("floor_price") or 0
        clamped = unit < floor
        unit = max(unit, floor)
        unit = math.floor(unit) if unit >= 20 else round(unit, 1)
        lines.append({"sku": v["sku"], "name": p["name_zh"], "name_th": p["title_th"][:60], "option": v["option_zh"],
                      "qty": qty, "price": v["price"], "unit_price": unit, "total": round(unit * qty, 2), "floor_hit": clamped})
        hours += float(v.get("hours") or 1) * qty
    days = max(erp_link.default_ship_days(), math.ceil(hours / erp_link.capacity_hours_per_day()) + 1) if lines else None
    return {"discount_pct": disc, "total_qty": total_qty, "lines": lines, "total": round(sum(x["total"] for x in lines), 2),
            "ship_days": days, "missing": missing, "tiers": tiers}


# ---------------- AI ----------------
SYSTEM = """你是泰国网店「{shop}」的客服，店里卖 3D 打印的产品（接单后打印制作）。
回复风格：{persona}

必须遵守：
1. 只能根据下面给的资料回答：产品、价格、颜色、尺寸、交期、订单状态、店铺政策。资料里没有的，不要编（不编价格、日期、运单号、优惠），
   回复里礼貌地说「马上帮您确认」，并把 needs_human 设为 true。
2. 退款、退货、赔偿、补发：不要自己答应，先安抚、请买家发照片/视频，needs_human=true。
3. 不要在平台聊天里给 LINE、电话、银行账号，不要引导买家平台外付款（平台会处罚）。
4. 定制要求：确认清楚细节（文字、颜色、尺寸、数量），把要求整理到 custom_request_zh / custom_request_th。
5. 批发/大量：用资料里算好的报价（quote），不能比它更便宜；交期用 quote.ship_days。
6. 用买家用的语言回复（泰语买家用泰语）。回复要短，像真人客服。
7. 下面这些事你不能自己答应（要答应的话 needs_human=true，回复里只说「马上帮您确认」）：{forbidden}
{smart}只输出 JSON。"""
SMART = """8. 灵活一点：信息不够就礼貌追问 1 个最关键的问题（尺寸、颜色、数量、要不要刻字、哪天要）；
   买家犹豫时可以推荐资料里相关的产品、颜色或套装；老顾客（资料里有买家历史）要认出来，语气更亲切；
   能一次说清楚的不要分好几条。不确定的事情不要假装知道。
"""

OUT_SPEC = """输出 JSON：
{"lang": "th/en/zh", "buyer_msgs_zh": ["待回复的每条买家消息的中文翻译，顺序一致"],
 "intent": "%s 之一", "summary_zh": "一句话：买家要什么", "summary_th": "同一句话的泰语（给泰国员工看）",
 "reply": "发给买家的回复（买家的语言）", "reply_zh": "回复的中文意思",
 "needs_human": true/false, "human_reason_zh": "为什么要人工处理（不需要就空）", "human_reason_th": "同上，泰语", "confidence": 0~1,
 "order_no": "消息里提到的订单号（没有就空）",
 "custom_request_zh": "定制要求（中文，给生产看；没有就空）", "custom_request_th": "定制要求（泰文，给泰国员工看）",
 "order_note_zh": "其他需要记到订单上的备注（例如：买家要求周五前到、包装要送礼；没有就空）",
 "wholesale_items": [{"sku": "...", "qty": 0}], "kb_ids_used": [用到的知识库 id], "save_as_faq": true/false,
 "tags": ["从这些里选（可以多个，没有就空）：%s"],
 "needs": [{"type": "批发/定制/送礼/企业团购/样品/其他", "detail_zh": "具体要什么（数量、规格、颜色、刻字、预算、哪天要）"}],
 "lead": true/false（这是不是值得跟进的销售机会：批发、大单、定制、企业采购、问了价还没下单的），
 "lead_value_thb": 估计这单能成交多少钱（不知道就 0）,
 "follow_up_zh": "如果买家没回，下次跟进时说什么（中文，给客服看）",
 "unknown_question_zh": "资料里查不到、你答不上来的问题（中文，一句话；能答就空）",
 "ask_seller_zh": "只在有「老板/客服的要求」时用：照他的意思写好回复；如果他的意思里缺了你必须知道才能回的信息（价格、日期、数量、能不能做到…），一句话问他（中文），否则空"}""" % ("/".join(INTENTS), "、".join(TAGS))


def _jpeg_b64(raw):
    from PIL import Image
    im = Image.open(io.BytesIO(raw))
    im = im.convert("RGB")
    if max(im.size) > 1800:
        im.thumbnail((1800, 1800))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def read_screenshot(raw):
    """聊天截图 → 消息列表。"""
    cfg = erp_link.ai_cfg()
    user = ("这是 Shopee / Lazada / TikTok 卖家后台或手机上的聊天截图。按顺序读出所有消息。"
            "右边/卖家发的是 seller，左边/买家发的是 buyer。"
            '输出 JSON：{"platform": "shopee/lazada/tiktok/unknown", "buyer": "买家名字（看得到就填）", '
            '"order_no": "截图里看到的订单号", "messages": [{"from": "buyer/seller", "text": "原文"}]}')
    d = ai_copy.extract_json(ai_copy.call(cfg, "你是 OCR 助手，准确读出聊天内容，不要翻译，不要漏字。只输出 JSON。", user, _jpeg_b64(raw)))
    msgs = [{"from": "seller" if str(m.get("from")).lower().startswith("s") else "buyer", "text": str(m.get("text") or "").strip()}
            for m in d.get("messages") or [] if str(m.get("text") or "").strip()]
    return {"platform": str(d.get("platform") or ""), "buyer": str(d.get("buyer") or ""), "order_no": str(d.get("order_no") or ""),
            "messages": msgs}


def build_context(conv, msgs, orders_found, instruction=""):
    s = data.settings()
    pending = []
    for m in reversed(msgs):
        if m["role"] == "seller":
            break
        if m["role"] == "buyer":
            pending.insert(0, m)
    last_text = " ".join(m["text"] for m in pending) or " ".join(m["text"] for m in msgs if m["role"] == "buyer")[-500:]
    order_skus = [i["sku"] for o in orders_found for i in o.get("items") or []]
    prods = relevant_products(last_text, order_skus)
    intent0 = rule_intent(last_text)
    q = None
    qty = _qty_in(last_text)
    if intent0 == "wholesale" or (qty and qty >= (data.wholesale_tiers() or [(10, 0)])[0][0]):
        # 先按最相关的产品报一个价（具体 SKU 由 AI 在 wholesale_items 里确认，确认后再精确报价）
        if prods and qty:
            q = quote([{"sku": prods[0]["variants"][0]["sku"], "qty": qty}]) if prods[0]["variants"] else None
    hist = [{"from": m["role"], "text": m["text"]} for m in msgs[-24:] if m["role"] in ("buyer", "seller", "note")]
    try:
        buyer_hist = erp_link.buyer_history(conv.get("platform") or "", conv.get("buyer") or "", conv.get("id"))
    except Exception:  # noqa: BLE001
        buyer_hist = None
    ctx = {
        "回复规则和预案（必须遵守）": s.get("playbook") or "",
        "店铺政策": {"发货": s["ship_policy"], "退换": s["return_policy"], "定制": s["custom_policy"],
                 "批发折扣档（数量:折扣%）": s["wholesale_tiers"], "批发说明": s["wholesale_note"], "其他": s["extra"],
                 "默认发货天数": erp_link.default_ship_days()},
        "产品": [{"编号": p["id"], "品名": p["name_zh"], "泰文标题": p["title_th"][:120], "材料": p["material"], "尺寸": p["size"],
                "用途": p["features_zh"], "发货天数": p["lead_days"],
                "款式": [{"sku": v["sku"], "款式": v["option_zh"], "泰文": v["option_th"], "售价THB": v["price"]} for v in p["variants"]]}
               for p in prods],
        "相关订单": orders_found,
        "知识库": [{"id": k["id"], "问": k["q"], "答": k["a"]} for k in kb_match(last_text)],
        "以前的好回复（参考语气和说法）": [{"买家": e["question"][:300], "回复": e["final_reply"][:400]} for e in example_match(last_text)],
        "批发报价（程序算好的）": q,
        "这个买家的历史（以前的订单、以前的会话标签）": buyer_hist,
        "这类问题怎么处理": {k: data.TIER_NAMES[v] for k, v in data.tiers(s).items()},
        "聊天记录（从旧到新，note 是内部备注买家看不到）": hist,
        "待回复的买家消息": [m["text"] for m in pending],
    }
    if instruction:
        ctx["老板/客服的要求（这次回复必须照做）"] = instruction
    return ctx, pending, intent0, q


def _cs_cfg():
    """客服可以单独用一个更快的模型。"""
    cfg = dict(erp_link.ai_cfg())
    m = (data.settings().get("model") or "").strip()
    if m:
        cfg["ai_model"] = m
    return cfg


def draft(conv, msgs, orders_found, instruction=""):
    """生成回复草稿。返回 analysis dict。"""
    s = data.settings()
    ctx, pending, intent0, q = build_context(conv, msgs, orders_found, instruction)
    cfg = _cs_cfg()
    system = SYSTEM.format(shop=s.get("shop_name") or "我们的店", persona=s.get("persona"),
                           forbidden=s.get("forbidden") or "退款、赔偿、补发、免运费、额外折扣",
                           smart=SMART if str(s.get("smart", "1")) == "1" else "")
    raw = ai_copy.call(cfg, system, json.dumps(ctx, ensure_ascii=False, default=str) + "\n\n" + OUT_SPEC)
    d = ai_copy.extract_json(raw)
    intent = d.get("intent") if d.get("intent") in INTENTS else intent0
    tier = data.tiers(s).get(intent, "confirm")
    needs = bool(d.get("needs_human")) or intent in HUMAN_INTENTS or tier == "human"
    reason = str(d.get("human_reason_zh") or "")
    if (intent in HUMAN_INTENTS or tier == "human") and not reason:
        reason = INTENTS[intent] + "，需要人工确认"
    # 规则兜底：回复里出现「不能随便承诺」的词 → 转人工（AI 有时会忍不住答应）
    hit = forbidden_hit(str(d.get("reply") or ""), s)
    if hit:
        needs = True
        reason = (reason + "；" if reason else "") + f"回复里有要老板确认的承诺（{hit}）"
        tier = "human"
    try:
        conf = max(0.0, min(1.0, float(d.get("confidence") or 0)))
    except (TypeError, ValueError):
        conf = 0.0
    wi = []
    for it in d.get("wholesale_items") or []:
        try:
            if it.get("sku") and int(it.get("qty") or 0) > 0:
                wi.append({"sku": str(it["sku"]).upper(), "qty": int(it["qty"])})
        except (TypeError, ValueError):
            continue
    return {
        "lang": d.get("lang") or "th", "intent": intent, "intent_zh": INTENTS.get(intent, ""),
        "summary_zh": str(d.get("summary_zh") or ""), "summary_th": str(d.get("summary_th") or ""),
        "human_reason_th": str(d.get("human_reason_th") or ""), "reply": str(d.get("reply") or "").strip(),
        "reply_zh": str(d.get("reply_zh") or "").strip(), "needs_human": needs, "human_reason_zh": reason, "confidence": conf,
        "order_no": str(d.get("order_no") or "").strip(),
        "custom_request_zh": str(d.get("custom_request_zh") or "").strip(),
        "custom_request_th": str(d.get("custom_request_th") or "").strip(),
        "order_note_zh": str(d.get("order_note_zh") or "").strip(),
        "wholesale_items": wi, "quote": quote(wi) if wi else q,
        "kb_ids_used": [int(x) for x in d.get("kb_ids_used") or [] if str(x).isdigit()],
        "save_as_faq": bool(d.get("save_as_faq")),
        "buyer_msgs_zh": [str(x) for x in d.get("buyer_msgs_zh") or []],
        "pending_ids": [m["id"] for m in pending],
        "instruction": instruction,
        "tier": "human" if needs else tier, "tier_zh": data.TIER_NAMES["human" if needs else tier],
        "tags": [t for t in (d.get("tags") or []) if t in TAGS][:6],
        "needs": [{"type": str(x.get("type") or "")[:20], "detail_zh": str(x.get("detail_zh") or "")[:300]}
                  for x in (d.get("needs") or []) if isinstance(x, dict) and x.get("detail_zh")][:5],
        "lead": bool(d.get("lead")) or intent in ("wholesale", "custom"),
        "lead_value": _num(d.get("lead_value_thb")),
        "follow_up_zh": str(d.get("follow_up_zh") or "")[:300],
        "unknown_question_zh": str(d.get("unknown_question_zh") or "")[:300],
        "ask_seller_zh": str(d.get("ask_seller_zh") or "")[:300] if instruction else "",
    }


def _num(v):
    try:
        return max(0.0, float(v or 0))
    except (TypeError, ValueError):
        return 0.0


def forbidden_hit(reply, s=None):
    s = s or data.settings()
    words = [w.strip() for w in re.split(r"[,，\n]", s.get("forbidden_words") or "") if w.strip()]
    low = (reply or "").lower()
    for w in words:
        if w.lower() in low:
            return w
    return ""


_TR_CACHE = {}


def translate(text, to="zh", conv=None, polite=True):
    """翻译。to=th 时按客服口吻（卖家发给买家的话：礼貌、自然、ค่ะ/ครับ 按店铺设定），给「中文打字 → 泰语」实时翻译用。有缓存。"""
    text = (text or "").strip()
    if not text:
        return ""
    s = data.settings()
    key = (text, to, bool(polite), (s.get("persona") or "")[:80])
    if key in _TR_CACHE:
        return _TR_CACHE[key]
    cfg = _cs_cfg()
    if to == "th" and polite:
        ctx = ""
        if conv:
            last = [m["text"] for m in (conv.get("messages") or []) if m["role"] in ("buyer", "seller")][-4:]
            if last:
                ctx = "最近的对话（参考语气和称呼）：\n" + "\n".join(last) + "\n\n"
        user = (f"{ctx}把卖家要发给买家的这段话翻译成泰语，网店客服口吻，自然、礼貌、简短（风格：{s.get('persona') or ''}）。"
                f"意思不能改，数字、价格、日期、SKU 照原样。只翻译，不要加内容。\n\n{text}\n\n输出 {{\"text\": \"...\"}}")
    else:
        lang = {"zh": "简体中文", "th": "泰语", "en": "英语"}.get(to, to)
        user = f'把下面的话翻译成{lang}，口语自然：\n{text}\n输出 {{"text": "..."}}'
    d = ai_copy.extract_json(ai_copy.call(cfg, "你是翻译。只输出 JSON。", user))
    out = str(d.get("text") or "")
    if len(_TR_CACHE) > 500:
        _TR_CACHE.clear()
    _TR_CACHE[key] = out
    return out


def learn(question, ai_reply, final_reply, kb_near):
    """员工改过 / 自己写的回复里有没有新的、以后能复用的知识（店铺做法、产品细节、政策）。
    返回 {q, a, a_zh, tags, update_id?} 或 None。"""
    cfg = _cs_cfg()
    user = ("下面是买家的问题、AI 原来写的回复（可能没有）、客服最后实际发出去的回复，和知识库里最接近的几条。\n"
            "判断：客服的回复里有没有【以后别的买家也会问、值得记进知识库】的新信息（店铺的做法、价格规则、产品细节、交期、政策、常见情况的说法）？\n"
            "只是寒暄、只针对这一个订单的（例如具体运单号）、知识库已经有的，都不要。\n"
            "要的话输出 {\"learn\": true, \"q\": \"买家常见的问法（泰语，可以 2-3 种问法用 | 分开）\", \"a\": \"标准回答（泰语，去掉这个买家的个人信息）\", "
            "\"a_zh\": \"回答的中文意思\", \"tags\": \"标签\", \"update_id\": 如果是在补充 / 更正知识库里某一条就写它的 id 否则 null}；不要就输出 {\"learn\": false}。\n\n"
            + json.dumps({"买家问": question[:1500], "AI 原稿": (ai_reply or "")[:1500], "实际回复": final_reply[:1500],
                          "知识库里接近的": [{"id": k["id"], "问": k["q"][:300], "答": k["a"][:500]} for k in kb_near]}, ensure_ascii=False))
    d = ai_copy.extract_json(ai_copy.call(cfg, "你是客服知识库整理员。只输出 JSON。", user))
    if not d.get("learn") or not d.get("q") or not d.get("a"):
        return None
    return {"q": str(d["q"])[:1000], "a": str(d["a"])[:3000], "a_zh": str(d.get("a_zh") or "")[:3000],
            "tags": str(d.get("tags") or "")[:200], "update_id": d.get("update_id") if str(d.get("update_id") or "").isdigit() else None}


def weekly_insight(stats):
    """周报里 AI 写的一段总结和建议（中文）。"""
    cfg = _cs_cfg()
    d = ai_copy.extract_json(ai_copy.call(cfg, "你是电商客服主管。只输出 JSON。",
                                          "根据这周的客服数据，写 3-5 条简短的中文总结和下周建议（哪些问题多、该补什么知识库、哪些客户要跟进、"
                                          "自动回复哪里可以放开或收紧）。输出 {\"points\": [\"...\"]}\n\n" + json.dumps(stats, ensure_ascii=False, default=str)))
    return [str(x) for x in d.get("points") or []][:6]
