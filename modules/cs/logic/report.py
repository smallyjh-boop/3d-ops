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
        "unanswered": [{"q": u["question_zh"] or u["question"], "n": u["count"]} for u in data.unanswered()[:10]],
        "learned": learned, "kb_pending": pending, "overdue_now": len(data.overdue()),
    }
    out["points"] = []
    if with_ai:
        try:
            from .brain import weekly_insight
            out["points"] = weekly_insight({k: out[k] for k in ("perf", "intents", "tags", "leads", "unanswered", "learned")})
        except Exception:  # noqa: BLE001  没有 AI 也照样出周报
            out["points"] = []
    return out


def as_text(r):
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
