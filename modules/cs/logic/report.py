"""客服周报（v2.22）：这周的客服数据 + 问得最多的、答不上来的、要跟进的客户、AI 学到的新知识、AI 的建议。"""
import json
import time

from core import db
from . import data

TAG_ORDER = ["批发", "定制", "企业团购", "送礼", "急单", "售后", "差评风险"]


def weekly(days=7, with_ai=True):
    c = db.conn()
    since = time.time() - days * 86400
    perf = data.perf(days)
    intents = {}
    tags = {}
    for r in c.execute("SELECT intent, tags FROM cs_conv WHERE updated_at>=?", (since,)):
        if r["intent"]:
            intents[r["intent"]] = intents.get(r["intent"], 0) + 1
        for t in (r["tags"] or "").split(","):
            if t:
                tags[t] = tags.get(t, 0) + 1
    from .brain import INTENTS
    leads_new = c.execute("SELECT COUNT(*), COALESCE(SUM(lead_value),0) FROM cs_conv WHERE lead_at>=?", (since,)).fetchone()
    stages = {r["lead_stage"]: r["n"] for r in c.execute(
        "SELECT lead_stage, COUNT(*) n FROM cs_conv WHERE COALESCE(lead_stage,'')!='' AND updated_at>=? GROUP BY lead_stage", (since,))}
    due = data.leads(due_only=True)
    learned = c.execute("SELECT COUNT(*) FROM cs_kb WHERE source='learned' AND created_at>=?", (since,)).fetchone()[0]
    pending = c.execute("SELECT COUNT(*) FROM cs_kb WHERE status='pending'").fetchone()[0]
    out = {
        "days": days, "from": time.strftime("%Y-%m-%d", time.localtime(since)), "to": time.strftime("%Y-%m-%d"),
        "perf": perf,
        "intents": sorted([{"intent": k, "name": INTENTS.get(k, k), "n": v} for k, v in intents.items()], key=lambda x: -x["n"]),
        "tags": sorted([{"tag": k, "n": v} for k, v in tags.items()], key=lambda x: -x["n"]),
        "leads": {"new": leads_new[0], "value": round(leads_new[1] or 0, 2), "stages": stages,
                  "due": [{"id": x["id"], "buyer": x.get("buyer"), "stage": data.LEAD_STAGES.get(x.get("lead_stage"), ""),
                           "note": x.get("follow_note") or "", "value": x.get("lead_value")} for x in due[:20]]},
        "unanswered": [{"q": u["question_zh"] or u["question"], "q_th": u["question"] or u["question_zh"], "n": u["count"]}
                       for u in data.unanswered()[:10]],
        "learned": learned, "kb_pending": pending, "overdue_now": len(data.overdue()),
    }
    out["points"], out["points_th"] = [], []
    if with_ai:
        try:
            from .brain import weekly_insight
            pts = weekly_insight({k: out[k] for k in ("perf", "intents", "tags", "leads", "unanswered", "learned")})
            out["points"], out["points_th"] = pts.get("zh") or [], pts.get("th") or []
        except Exception:  # noqa: BLE001  没有 AI 也照样出周报
            pass
    return out


# v2.49：泰文界面的周报（泰国员工看）
INTENT_TH = {"product": "ถามสินค้า", "price": "ถามราคา / ส่วนลด", "stock": "ถามของ / ส่งกี่วัน", "order_status": "ถามสถานะคำสั่งซื้อ",
             "custom": "สั่งทำพิเศษ", "wholesale": "ขายส่ง / จำนวนมาก", "complaint": "ร้องเรียน / ของเสียหาย", "refund": "คืนเงิน / คืนสินค้า",
             "change_order": "แก้ไขคำสั่งซื้อ", "thanks": "ขอบคุณ / รีวิว", "other": "อื่นๆ"}
TAG_TH = {"批发": "ขายส่ง", "定制": "สั่งทำ", "送礼": "ของขวัญ", "企业团购": "องค์กร", "回头客": "ลูกค้าเก่า", "急单": "ด่วน", "价格敏感": "เน้นราคา",
          "比价": "เทียบราคา", "要样品": "ขอตัวอย่าง", "新品询问": "ถามสินค้าใหม่", "售后": "หลังการขาย", "差评风险": "เสี่ยงรีวิวไม่ดี", "好评": "รีวิวดี",
          "海外 / 外地": "ต่างประเทศ / ต่างจังหวัด", "询价": "ถามราคา", "催单": "ตามของ", "闲聊": "คุยทั่วไป", "咨询": "สอบถาม"}
STAGE_TH = {"new": "ลูกค้าใหม่", "follow": "กำลังติดตาม", "quoted": "เสนอราคาแล้ว", "won": "ปิดการขาย", "lost": "หลุด"}


def as_text(r, lang="zh"):
    if lang == "th":
        return as_text_th(r)
    p = r["perf"]
    L = [f"客服周报 {r['from']} ~ {r['to']}", "",
         f"有买家消息的会话 {p['convs']} 个，回复 {p['sent']} 条（自动发送 {p['auto']} 条），"
         f"AI 草稿直接采用率 {p['adopt_pct'] if p['adopt_pct'] is not None else '-'}%，平均回复 {p['avg_reply_min'] if p['avg_reply_min'] is not None else '-'} 分钟，"
         f"超时才回复 {p['over_alert']} 次；现在超时未回复 {r['overdue_now']} 个。", ""]
    if r["intents"]:
        L.append("问得最多：" + "、".join(f"{x['name']} {x['n']}" for x in r["intents"][:6]))
    if r["tags"]:
        L.append("客户需求标签：" + "、".join(f"{x['tag']} {x['n']}" for x in r["tags"][:8]))
    ld = r["leads"]
    L.append(f"新销售线索 {ld['new']} 个（估计 ฿{ld['value']:,.0f}）；" + "、".join(f"{data.LEAD_STAGES.get(k, k)} {v}" for k, v in ld["stages"].items()))
    if ld["due"]:
        L.append("要跟进的客户：")
        L += [f"  · {x['buyer'] or '买家'}（{x['stage']}）{x['note']}" for x in ld["due"][:10]]
    if r["unanswered"]:
        L.append("AI 答不上来的问题（请补进知识库）：")
        L += [f"  · {x['q']}（{x['n']} 次）" for x in r["unanswered"]]
    L.append(f"AI 这周从人工回复里学到 {r['learned']} 条新知识，待确认 {r['kb_pending']} 条。")
    if r["points"]:
        L += ["", "AI 的总结和建议："] + [f"  {i + 1}. {x}" for i, x in enumerate(r["points"])]
    return "\n".join(L)


def save_last(r):
    c = db.conn()
    c.execute("INSERT OR REPLACE INTO cs_settings(k, v) VALUES('last_weekly_report', ?)", (json.dumps(r, ensure_ascii=False, default=str)[:60000],))
    c.commit()


def last():
    r = db.conn().execute("SELECT v FROM cs_settings WHERE k='last_weekly_report'").fetchone()
    try:
        return json.loads(r["v"]) if r else None
    except ValueError:
        return None


def as_text_th(r):
    p = r["perf"]
    dash = lambda v: "-" if v is None else v
    L = [f"รายงานแชทลูกค้า {r['from']} ~ {r['to']}", "",
         f"แชทที่มีข้อความลูกค้า {p['convs']} แชท ตอบ {p['sent']} ข้อความ (ส่งอัตโนมัติ {p['auto']}) "
         f"ใช้ร่าง AI ตรงๆ {dash(p['adopt_pct'])}% ตอบเฉลี่ย {dash(p['avg_reply_min'])} นาที "
         f"ตอบช้าเกินกำหนด {p['over_alert']} ครั้ง ตอนนี้ยังไม่ได้ตอบเกินเวลา {r['overdue_now']} แชท", ""]
    if r["intents"]:
        L.append("ถามบ่อยที่สุด: " + ", ".join(f"{INTENT_TH.get(x['intent'], x['intent'])} {x['n']}" for x in r["intents"][:6]))
    if r["tags"]:
        L.append("แท็กความต้องการ: " + ", ".join(f"{TAG_TH.get(x['tag'], x['tag'])} {x['n']}" for x in r["tags"][:8]))
    ld = r["leads"]
    L.append(f"โอกาสขายใหม่ {ld['new']} ราย (ประมาณ ฿{ld['value']:,.0f}) " + ", ".join(f"{STAGE_TH.get(k, k)} {v}" for k, v in ld["stages"].items()))
    if ld["due"]:
        L.append("ลูกค้าที่ต้องติดตาม:")
        L += [f"  · {x['buyer'] or 'ลูกค้า'}" for x in ld["due"][:10]]
    if r["unanswered"]:
        L.append("คำถามที่ AI ตอบไม่ได้ (เพิ่มในคลังความรู้):")
        L += [f"  · {x.get('q_th') or x['q']} ({x['n']} ครั้ง)" for x in r["unanswered"]]
    L.append(f"สัปดาห์นี้ AI เรียนรู้ความรู้ใหม่ {r['learned']} รายการ รอยืนยัน {r['kb_pending']} รายการ")
    if r.get("points_th"):
        L += ["", "สรุปและคำแนะนำจาก AI:"] + [f"  {i + 1}. {x}" for i, x in enumerate(r["points_th"])]
    return "\n".join(L)
