"""客服业务流程：会话、读消息、生成回复、发送 / 学习、写订单备注、报价。界面接口和浏览器扩展都调用这里。"""
import threading
import time

from . import brain, data, erp_link

PLATFORMS = {"lazada": "Lazada", "shopee": "Shopee", "tiktok": "TikTok", "line": "LINE", "facebook": "Facebook",
             "manual": "其他"}


def conv_full(cid):
    c = data.get_conv(cid)
    if not c:
        raise ValueError("会话不存在")
    c["messages"] = data.messages(cid)
    c["order"] = erp_link.order_brief(c["order_id"]) if c.get("order_id") else None
    if not c["order"]:
        buyer_text = " ".join(m["text"] for m in c["messages"] if m["role"] == "buyer")
        c["order_candidates"] = erp_link.find_orders(buyer_text, c.get("buyer") or "")
    else:
        c["order_candidates"] = []
    c["suggestions"] = suggestions(c)
    try:
        c["buyer_history"] = erp_link.buyer_history(c.get("platform") or "", c.get("buyer") or "", cid)
    except Exception:  # noqa: BLE001
        c["buyer_history"] = None
    c["lead_stages"] = data.LEAD_STAGES
    # v2.24：客户档案（第几次来、历史会话、备注 / 登记）
    from . import crm
    try:
        cu_id = c.get("customer_id") or crm.link_conv(c)
        if cu_id:
            cu = crm.customer(cu_id)
            c["customer"] = {"id": cu["id"], "visits": cu["visits"], "first_at": cu["first_at"], "orders": cu["orders"],
                             "tags": cu.get("tags") or "", "records": cu["records"][:30],
                             "convs": [x for x in cu["conv_list"] if x["id"] != cid][:10]}
        else:
            c["customer"] = None
            c["records"] = crm.records(conv_id=cid, limit=30)
    except Exception:  # noqa: BLE001
        c["customer"] = None
    c["record_kinds"] = crm.KINDS
    # v2.46：能不能直接发（接口渠道）、AI 现在怎么处理这个会话
    from . import channels, shopcfg
    c["can_send"] = channels.of(c) is not None
    c["ai_mode"] = shopcfg.mode_of(c)
    c["shop_mode"] = shopcfg.get(c.get("shop") or "")["mode"]
    if c.get("kind") == "system":             # v2.49：平台通知只读
        c["can_send"] = False
        c["suggestions"] = []
    return c


def suggest_products(cid, n=3):
    """买家提到了某个产品（名字、编号、SKU、发来的商品卡片）：推荐 1–3 个可以发的商品卡片（v2.49）。"""
    msgs = [m for m in data.messages(cid, 20) if m["role"] == "buyer"][-6:]
    if not msgs:
        return []
    text = " ".join(m["text"] for m in msgs if (m.get("kind") or "text") == "text")
    item_ids = {str((m.get("extra") or {}).get("item_id")) for m in msgs if m.get("kind") == "item" and (m.get("extra") or {}).get("item_id")}
    try:
        ps = erp_link.products()
    except Exception:  # noqa: BLE001
        return []
    up = text.upper()
    scored = []
    for p in ps:
        hay = " ".join([p["id"], p["name_zh"], p["title_th"], p["title_en"], p.get("keywords") or ""])
        sc = brain.sim(text, hay) if text.strip() else 0
        if p["id"].upper() in up or any((v.get("sku") or "").upper() in up for v in p["variants"] if v.get("sku")):
            sc += 5
        scored.append((sc, p))
    scored.sort(key=lambda x: -x[0])
    out = []
    for sc, p in scored:
        if len(out) >= n or sc < 0.18:
            break
        try:
            out.append(dict(erp_link.product_card(p["id"]), score=round(sc, 2)))
        except Exception:  # noqa: BLE001
            continue
    if item_ids:          # 买家发来的商品卡片对应的产品排最前
        for p in ps:
            try:
                card = erp_link.product_card(p["id"])
            except Exception:  # noqa: BLE001
                continue
            if str(card.get("lazada_item_id")) in item_ids and all(x["id"] != card["id"] for x in out):
                out.insert(0, dict(card, score=9))
    return out[:n]


def suggestions(c):
    """根据 AI 分析给出可以一键做的事。"""
    a = c.get("analysis") or {}
    out = []
    o = c.get("order")
    if a.get("custom_request_zh"):
        txt = a["custom_request_zh"] + (f"｜{a['custom_request_th']}" if a.get("custom_request_th") else "")
        out.append({"type": "custom_note", "label": "把定制要求写进订单（生产工单会显示）", "label_th": "บันทึกรายละเอียดสั่งทำลงคำสั่งซื้อ", "text": txt, "need_order": not o})
    if a.get("order_note_zh"):
        out.append({"type": "seller_note", "label": "记到订单的卖家备注", "label_th": "บันทึกเป็นโน้ตผู้ขายในคำสั่งซื้อ", "text": a["order_note_zh"], "need_order": not o})
    q = a.get("quote")
    if q and q.get("lines"):
        out.append({"type": "quote", "label": f"生成报价单（{q['total_qty']} 个，合计 {q['total']} 铢，约 {q['ship_days']} 天发货）",
                    "label_th": f"สร้างใบเสนอราคา ({q['total_qty']} ชิ้น รวม {q['total']} บาท ส่งประมาณ {q['ship_days']} วัน)",
                    "items": [{"sku": x["sku"], "qty": x["qty"], "unit_price": x["unit_price"]} for x in q["lines"]]})
    if a.get("intent") in ("complaint", "refund") and o:
        out.append({"type": "aftersales", "label": "去订单登记售后（退款 / 补发）", "label_th": "ไปบันทึกหลังการขายที่คำสั่งซื้อ", "order_id": o["id"]})
    if a.get("intent") == "order_status" and o and o.get("status") == "to_ship" and not o.get("priority"):
        out.append({"type": "priority", "label": "买家在催：把订单设为加急", "label_th": "ลูกค้าเร่ง: ตั้งคำสั่งซื้อเป็นด่วน"})
    if o and o.get("status") == "quote":
        out.append({"type": "quote_confirm", "label": f"买家确认了：把报价单 {o['order_no']} 转成正式订单（开始排产）",
                    "label_th": f"ลูกค้ายืนยันแล้ว: เปลี่ยนใบเสนอราคา {o['order_no']} เป็นคำสั่งซื้อ", "order_id": o["id"]})
    return out


def _link_order(c, order_no="", user=""):
    if c.get("order_id"):
        return c
    o = erp_link.order_by_no(order_no) if order_no else None
    if not o:
        buyer_text = " ".join(m["text"] for m in data.messages(c["id"]) if m["role"] == "buyer")
        cands = erp_link.find_orders(buyer_text, "")   # 只按消息里的订单号自动关联（按买家名可能不准，只做候选）
        o = cands[0] if len(cands) == 1 else None
    if o:
        c = data.update_conv(c["id"], order_id=o["id"], order_no=o["order_no"])
    return c


def ensure_conv(platform="", buyer="", shop="", ext_id=None, channel="manual", order_no=""):
    """按 平台 + 外部编号（扩展用：平台:店铺:买家）找会话，没有就新建。"""
    if ext_id:
        c = data.find_conv(platform or "", ext_id)
        if c:
            if buyer and not c.get("buyer"):
                c = data.update_conv(c["id"], buyer=buyer)
            if shop and c.get("shop") != shop:
                c = data.update_conv(c["id"], shop=shop)
            if not c.get("customer_id"):
                from . import crm
                crm.link_conv(c)
                c = data.get_conv(c["id"])
            return c
    c = data.create_conv(buyer=buyer, platform=platform, channel=channel, ext_id=ext_id)
    if shop:
        c = data.update_conv(c["id"], shop=shop)
    from . import crm
    crm.link_conv(c)                         # v2.24：客户档案
    c = data.get_conv(c["id"])
    if order_no:
        c = _link_order(c, order_no)
    return c


def add_messages(cid, msgs, source="paste", user="", replace_tail=False):
    """批量加消息 [{from: buyer/seller/note, text, ext_id?, ts?}]。
    replace_tail=True（扩展每次读整段对话）：只加最后一条已知消息之后的新消息，避免重复。"""
    existing = data.messages(cid, 500)
    if replace_tail and existing:
        known = [(m["role"], m["text"].strip()) for m in existing if m["role"] in ("buyer", "seller")]
        incoming = [("seller" if m.get("from") == "seller" else "buyer", (m.get("text") or "").strip()) for m in msgs]
        # 找到已知记录的最后一条在新列表里的位置，从它后面开始加
        start = 0
        if known:
            last = known[-1]
            for i in range(len(incoming) - 1, -1, -1):
                if incoming[i] == last:
                    # 往前多对几条，确认是同一段
                    k = 1
                    while k < 3 and i - k >= 0 and len(known) - 1 - k >= 0 and incoming[i - k] == known[len(known) - 1 - k]:
                        k += 1
                    start = i + 1
                    break
            else:
                # 新列表里没有任何已知消息：只要不是全部重复，就整段加
                kset = set(known)
                start = 0 if not all(x in kset for x in incoming) else len(incoming)
        msgs = msgs[start:]
    n = 0
    for m in msgs:
        role = m.get("from") if m.get("from") in ("buyer", "seller", "note") else "buyer"
        learn = None
        if role == "seller" and source in ("extension", "screenshot", "platform"):
            # 员工在平台上把回复发出去了（扩展读回来）：和 AI 草稿对照，学习
            c = data.get_conv(cid)
            if c and c.get("draft"):
                pend = []
                for x in reversed(data.messages(cid)):
                    if x["role"] == "seller":
                        break
                    if x["role"] == "buyer":
                        pend.insert(0, x["text"])
                learn = (pend, c["draft"], c.get("intent") or "")
        if data.add_msg(cid, role, m.get("text"), source=source, user=user, ext_id=m.get("ext_id"), ts=m.get("ts"),
                        ai_draft=learn[1] if learn else None):
            n += 1
            if learn and learn[0]:
                data.add_example(cid, "\n".join(learn[0]), learn[1], m.get("text") or "", learn[2], user)
                learn_async(cid, "\n".join(learn[0]), learn[1], m.get("text") or "", user)
    return n


def make_draft(cid, instruction="", user=""):
    c = data.get_conv(cid)
    if c and c.get("kind") == "system":
        raise ValueError("这是平台通知，不用回复")
    msgs = data.messages(cid)
    if not any(m["role"] == "buyer" for m in msgs):
        raise ValueError("还没有买家消息")
    c = _link_order(c)
    found = [erp_link.order_brief(c["order_id"])] if c.get("order_id") else \
        erp_link.find_orders(" ".join(m["text"] for m in msgs if m["role"] == "buyer"), c.get("buyer") or "")
    a = brain.draft(c, msgs, [o for o in found if o], instruction)
    if a.get("order_no") and not c.get("order_id"):
        c = _link_order(c, a["order_no"])
    # 买家消息的中文翻译
    for mid, zh in zip(a.get("pending_ids") or [], a.get("buyer_msgs_zh") or []):
        if zh:
            data.set_msg_zh(mid, zh)
    data.kb_used(a.get("kb_ids_used"))
    c = data.get_conv(cid)
    tags = list(dict.fromkeys((c.get("tag_list") or []) + (a.get("tags") or [])))[:12]
    up = dict(draft=a["reply"], draft_zh=a["reply_zh"], analysis=a, draft_at=time.time(), intent=a["intent"],
              summary=a["summary_zh"], lang=a["lang"], needs_human=1 if a["needs_human"] else 0,
              human_reason=a["human_reason_zh"], tier=a.get("tier"), tags=",".join(tags))
    if a.get("needs"):
        old = c.get("needs") or []
        seen = {x.get("detail_zh") for x in old}
        up["needs"] = (old + [x for x in a["needs"] if x["detail_zh"] not in seen])[-10:]
    # 销售线索：批发 / 定制 / 大单 → 进「跟进」列表，到时间提醒
    if a.get("lead") and not (c.get("lead_stage") or ""):
        hours = _f(data.settings().get("follow_hours"), 24)
        up.update(lead_stage="new", lead_at=time.time(), next_follow_at=time.time() + hours * 3600,
                  lead_value=a.get("lead_value") or None, follow_note=a.get("follow_up_zh") or "")
    elif a.get("follow_up_zh") and (c.get("lead_stage") or "") in ("new", "follow", "quoted"):
        up["follow_note"] = a["follow_up_zh"]
    data.update_conv(cid, **up)
    # 答不上来的问题 → 「待补充的知识」
    if a.get("unknown_question_zh"):
        q = "\n".join(m["text"] for m in msgs if m["id"] in set(a.get("pending_ids") or []))[-500:]
        data.unanswered_add(q or a["unknown_question_zh"], a["unknown_question_zh"], cid)
    # 紧急（投诉、退款、要人工的）→ 马上发邮件
    if a["needs_human"]:
        try:
            from . import alerts
            alerts.urgent_async(cid)
        except Exception:  # noqa: BLE001
            pass
    return conv_full(cid)


def _f(v, d):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def learn_async(cid, question, ai_reply, final_reply, user=""):
    """员工发出的回复和 AI 原稿不一样 / AI 没写：后台让 AI 看看有没有新知识，放进「待确认」（或直接加进知识库）。"""
    s = data.settings()
    mode = s.get("learn_mode") or "suggest"
    if mode == "off" or not question or not final_reply or (ai_reply or "").strip() == final_reply.strip():
        return

    def go():
        try:
            near = brain.kb_match(question, 4)
            r = brain.learn(question, ai_reply, final_reply, near)
            if not r:
                return
            for k in data.kb_list():               # 已经有几乎一样的就不加
                if brain.sim(k["a"], r["a"]) > 0.8:
                    return
            note = f"从会话 #{cid} 学到" + (f"（补充第 {r['update_id']} 条）" if r.get("update_id") else "")
            data.kb_add_learned(r["q"], r["a"], r["a_zh"], r["tags"], cid, active=(mode == "auto"), note=note)
            for u in data.unanswered():            # 之前答不上来的问题，这次有人答了
                if brain.sim(u["question"], question) > 0.5:
                    data.unanswered_done(u["id"], -1)
        except Exception as e:  # noqa: BLE001  学习失败不影响发送
            try:
                from core import diag
                diag.log.warning("客服学习失败：%s", e)
            except Exception:  # noqa: BLE001
                pass
        finally:
            from core import db
            db.release()
    threading.Thread(target=go, daemon=True, name="cs-learn").start()


def record_sent(cid, text, user="", source="manual", kind="text", extra=None, ext_id=None, status=""):
    """回复已经发出去了（员工在平台发的，或程序发的）：记下来；和 AI 草稿不一样时，作为「好回复」学习。
    v2.46：kind / extra 是图片、商品卡片、订单卡片；ext_id 是平台消息编号（接口发的）。"""
    c = data.get_conv(cid)
    text = (text or "").strip()
    if not text:
        raise ValueError("回复是空的")
    if kind != "text":
        data.add_msg(cid, "seller", text, source=source, user=user, ext_id=ext_id, kind=kind, extra=extra, status=status)
        return conv_full(cid)
    msgs = data.messages(cid)
    pending = []
    for m in reversed(msgs):
        if m["role"] == "seller":
            break
        if m["role"] == "buyer":
            pending.insert(0, m["text"])
    ai = c.get("draft") or ""
    data.add_msg(cid, "seller", text, source=source, user=user, ai_draft=ai or None, ext_id=ext_id, status=status)
    if pending and source != "auto":      # 自动发的不当「好回复」学（只学人确认过的）
        # 改过的回复一定学；没改也记一份（说明 AI 的说法被认可）
        data.add_example(cid, "\n".join(pending), ai, text, c.get("intent") or "", user)
        learn_async(cid, "\n".join(pending), ai, text, user)
    # 跟进中的线索：我们回复了 → 下次跟进时间往后推
    if (c.get("lead_stage") or "") in ("new", "follow", "quoted"):
        hours = _f(data.settings().get("follow_hours"), 24) * (2 if c.get("lead_stage") == "quoted" else 1)
        data.update_conv(cid, next_follow_at=time.time() + hours * 3600,
                         lead_stage="follow" if c.get("lead_stage") == "new" else c.get("lead_stage"))
    return conv_full(cid)


def do_action(cid, act, user=""):
    c = conv_full(cid)
    t = act.get("type")
    if t == "link_order":
        o = erp_link.order_brief(int(act["order_id"])) if act.get("order_id") else erp_link.order_by_no(act.get("order_no"))
        if not o:
            raise ValueError("找不到这个订单")
        data.update_conv(cid, order_id=o["id"], order_no=o["order_no"])
        return conv_full(cid), "已关联订单 " + o["order_no"]
    if t == "unlink_order":
        data.update_conv(cid, order_id=None, order_no=None)
        return conv_full(cid), "已取消关联"
    if t in ("custom_note", "seller_note"):
        oid = act.get("order_id") or (c.get("order") or {}).get("id")
        if not oid:
            raise ValueError("请先关联订单")
        erp_link.add_order_note(int(oid), act.get("text") or "", t, user)
        data.add_msg(cid, "note", f"已写入订单{'定制备注' if t == 'custom_note' else '卖家备注'}：{act.get('text')}", "system", user)
        return conv_full(cid), "已写入订单"
    if t == "priority":
        oid = (c.get("order") or {}).get("id")
        if not oid:
            raise ValueError("请先关联订单")
        erp_link.set_priority(oid, user)
        return conv_full(cid), "已设为加急"
    if t == "quote":
        items = act.get("items") or []
        if not items:
            raise ValueError("报价单没有商品")
        o = erp_link.create_quote(c.get("buyer") or "", items, f"客服询价（会话 #{cid}）", user,
                                  c.get("platform") if c.get("platform") in ("lazada", "shopee", "tiktok") else "manual")
        data.add_msg(cid, "note", f"已生成报价单 {o['order_no']}，合计 {o.get('total')} 铢", "system", user)
        if not c.get("order_id"):
            data.update_conv(cid, order_id=o["id"], order_no=o["order_no"])
        hours = _f(data.settings().get("follow_hours"), 24) * 2
        data.update_conv(cid, lead_stage="quoted", lead_value=o.get("total") or c.get("lead_value"),
                         next_follow_at=time.time() + hours * 3600, lead_at=c.get("lead_at") or time.time())
        return conv_full(cid), f"已生成报价单 {o['order_no']}"
    if t == "quote_confirm":
        o = erp_link.confirm_quote(int(act.get("order_id") or (c.get("order") or {}).get("id") or 0), user)
        data.add_msg(cid, "note", f"报价单 {o['order_no']} 已转成正式订单，开始排产", "system", user)
        data.update_conv(cid, lead_stage="won", next_follow_at=None, lead_value=o.get("total") or c.get("lead_value"))
        return conv_full(cid), f"已转成正式订单 {o['order_no']}"
    if t == "lead":
        stage = act.get("stage")
        if stage not in data.LEAD_STAGES and stage != "":
            raise ValueError("跟进阶段不对")
        up = {"lead_stage": stage}
        if stage and not c.get("lead_at"):
            up["lead_at"] = time.time()
        if act.get("days") not in (None, ""):
            up["next_follow_at"] = time.time() + float(act["days"]) * 86400 if float(act["days"]) > 0 else None
        if stage in ("won", "lost", ""):
            up["next_follow_at"] = None
        if act.get("note") is not None:
            up["follow_note"] = str(act["note"])[:300]
        if act.get("value") not in (None, ""):
            up["lead_value"] = float(act["value"])
        data.update_conv(cid, **up)
        if stage:
            data.add_msg(cid, "note", f"跟进：{data.LEAD_STAGES[stage]}" + (f"，{act.get('note')}" if act.get("note") else ""), "system", user)
        return conv_full(cid), "已更新跟进"
    if t == "tags":
        tags = [x.strip() for x in str(act.get("tags") or "").replace("，", ",").split(",") if x.strip()]
        data.update_conv(cid, tags=",".join(dict.fromkeys(tags))[:300])
        return conv_full(cid), "已更新标签"
    if t == "kb":
        q = act.get("q") or "\n".join(m["text"] for m in c["messages"] if m["role"] == "buyer")[-500:]
        a = act.get("a") or next((m["text"] for m in reversed(c["messages"]) if m["role"] == "seller"), "")
        data.kb_save({"q": q, "a": a, "a_zh": act.get("a_zh") or "", "tags": c.get("intent") or ""}, user)
        return conv_full(cid), "已加入常见问答"
    if t == "close":
        data.update_conv(cid, status="closed", needs_human=0)
        return conv_full(cid), "已结束"
    if t == "reopen":
        data.update_conv(cid, status="open")
        return conv_full(cid), "已重新打开"
    if t == "human_done":
        data.update_conv(cid, needs_human=0, human_reason="")
        return conv_full(cid), "已处理"
    raise ValueError("不支持的操作")


def from_screenshot(cid, raw, user=""):
    r = brain.read_screenshot(raw)
    c = data.get_conv(cid)
    up = {}
    if r["buyer"] and not c.get("buyer"):
        up["buyer"] = r["buyer"]
    if r["platform"] in PLATFORMS and not c.get("platform"):
        up["platform"] = r["platform"]
    if up:
        data.update_conv(cid, **up)
    n = add_messages(cid, r["messages"], "screenshot", user, replace_tail=True)
    if r["order_no"]:
        _link_order(data.get_conv(cid), r["order_no"])
    return n


def auto_decision(c):
    """全自动模式下，这条回复能不能自动发出去。返回 {ok, reason}。"""
    s = data.settings()
    a = c.get("analysis") or {}
    if str(s.get("auto_send", "1")) != "1":
        return {"ok": False, "reason": "老板关闭了自动发送"}
    if (c.get("mode") or "") == "human":
        return {"ok": False, "reason": f"{c.get('taken_by') or '客服'} 接管了这个会话"}
    from . import shopcfg
    if shopcfg.get(c.get("shop") or "")["mode"] == "off":
        return {"ok": False, "reason": "这个店铺设置为只人工回复"}
    if c.get("kind") == "system":
        return {"ok": False, "reason": "平台通知，不回复"}
    if not c.get("draft"):
        return {"ok": False, "reason": "没有回复草稿"}
    if brain.production_hit(c.get("draft") or ""):          # v2.49：提到生产 / 打印的不能自动发
        return {"ok": False, "reason": f"回复里提到了生产 / 打印（{brain.production_hit(c['draft'])}），请改一下再发"}
    if c.get("needs_human"):
        return {"ok": False, "reason": "需要人工：" + (c.get("human_reason") or "")}
    tier = data.tiers(s).get(a.get("intent"), "confirm")
    if tier != "auto" or a.get("tier") == "human":
        return {"ok": False, "reason": f"「{a.get('intent_zh') or a.get('intent')}」类问题设置为{data.TIER_NAMES.get(tier, tier)}"}
    try:
        need = float(s.get("auto_min_conf") or 0.85)
    except ValueError:
        need = 0.85
    if float(a.get("confidence") or 0) < need:
        return {"ok": False, "reason": f"AI 把握不够（{round(float(a.get('confidence') or 0) * 100)}%）"}
    if a.get("custom_request_zh") or a.get("order_note_zh"):
        return {"ok": False, "reason": "有定制要求 / 备注，需要人确认后写进订单"}
    try:
        cap = int(float(s.get("auto_max_per_hour") or 40))
    except ValueError:
        cap = 40
    if data.auto_sent_last_hour() >= cap:
        return {"ok": False, "reason": f"这一小时已经自动发了 {cap} 条，先停一下（防止出错乱发）"}
    return {"ok": True, "reason": ""}
