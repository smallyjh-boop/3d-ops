"use strict";
// AI 客服（独立模块）：客服工作台 + 知识库与话术。只调用 /api/cs/...
(function () {
  const PLAT = { lazada: "Lazada", shopee: "Shopee", tiktok: "TikTok", line: "LINE", facebook: "Facebook", manual: "其他" };
  const ROLE = { buyer: "买家", seller: "我们", note: "内部备注" };
  let CUR = null, CONV = null, TIMER = null, KB = null, SHOPS = [];
  const isOwner = () => window.OPSH && OPSH.isOwner();
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const TIER_CLS = { auto: "ok-pill", confirm: "warn-pill", human: "bad-pill" };
  const TIER_TXT = { auto: ["可自动发", "ส่งอัตโนมัติได้"], confirm: ["AI 写好·人确认", "AI เขียน·คนตรวจ"], human: ["转人工", "ส่งให้คนจัดการ"] };
  const STAGE = { new: ["新线索", "ลูกค้าใหม่"], follow: ["跟进中", "กำลังติดตาม"], quoted: ["已报价", "เสนอราคาแล้ว"], won: ["成交", "ปิดการขาย"], lost: ["流失", "หลุด"] };
  const stageTxt = (k) => (STAGE[k] ? Z(STAGE[k][0], STAGE[k][1]) : "");
  const sumOf = (c) => (TH() && c.analysis && c.analysis.summary_th) || c.summary || "";
  const reasonOf = (c) => (TH() && c.analysis && c.analysis.human_reason_th) || c.human_reason || "";

  function show(name) {
    clearInterval(TIMER);
    if (name === "cs") {
      loadList();
      TIMER = setInterval(() => { if (!document.hidden && $("#tab-cs") && !$("#tab-cs").classList.contains("hidden")) loadList(true); }, 15000);
    }
    if (name === "cskb") loadKb();
    if (name === "csext") loadKeys().catch((e) => toast(e.message, true));
  }

  // ---------------- 会话列表 ----------------
  async function loadList(quiet) {
    const st = $("#cs-filter").value, q = $("#cs-q").value.trim();
    const sf = $("#cs-shopf"), af = $("#cs-agentf");
    const d = await api(`/api/cs/convs?status=${encodeURIComponent(st)}&q=${encodeURIComponent(q)}&shop=${encodeURIComponent(sf ? sf.value : "")}&agent=${encodeURIComponent(af ? af.value : "")}`);
    // v2.24：店铺 / 客服筛选
    const fill = (el, items, first) => { if (!el) return; const cur = el.value; el.innerHTML = `<option value="">${first}</option>` + items.map(([v, t]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""} data-notr>${esc(t)}</option>`).join(""); };
    SHOPS = d.shops || [];
    fill(sf, SHOPS.map((x) => [x, x]), Z("全部店铺", "ทุกร้าน"));
    fill(af, (d.agents || []).map((x) => [x.agent, x.name]), Z("全部客服", "แอดมินทั้งหมด"));
    $("#cs-stats").innerHTML = `待回复 <b>${d.stats.open}</b> · 需人工 <b class="${d.stats.human ? "bad" : ""}">${d.stats.human}</b> · 等买家 ${d.stats.waiting}` +
      (d.stats.overdue ? ` · <span class="cs-overdue">⏰ 超时 ${d.stats.overdue}</span>` : "");
    const AM = d.alert_minutes || 0;
    $("#cs-items").innerHTML = d.convs.map((c) => `<div class="cs-item ${c.id === CUR ? "on" : ""} st-${c.status}" data-cid="${c.id}">
        <div class="row between"><b data-notr>${esc(c.buyer || "（未填买家）")}</b><span class="small muted">${fmtTime(c.updated_at).slice(5, 16)}</span></div>
        <div class="small"><span class="pill plat-${esc(c.platform || "manual")}">${esc(PLAT[c.platform] || c.platform || "其他")}</span>
          ${c.needs_human ? '<span class="pill bad-pill">需人工</span>' : ""}${c.status === "open" ? '<span class="pill warn-pill">待回复</span>' : c.status === "closed" ? '<span class="pill">已结束</span>' : ""}
          ${c.order_no ? `<span class="mono small" data-notr>${esc(c.order_no)}</span>` : ""}
          ${AM && c.wait_min != null && c.wait_min >= AM ? `<span class="pill bad-pill">⏰ 等了 ${c.wait_min} 分钟</span>` : ""}
          ${c.lead_stage ? `<span class="pill tag-pill">💼 ${esc(stageTxt(c.lead_stage))}${c.next_follow_at && c.next_follow_at * 1000 <= Date.now() && ["new", "follow", "quoted"].includes(c.lead_stage) ? " ⏰" : ""}</span>` : ""}
          ${(c.tag_list || []).slice(0, 3).map((t) => `<span class="pill" data-notr>${esc(t)}</span>`).join("")}</div>
        <div class="small muted cs-last" data-notr>${c.last ? (c.last.role === "seller" ? "↩ " : "") + esc(c.last.text.slice(0, 60)) : ""}</div>
        ${c.summary && !TH() ? `<div class="small cs-sum" data-notr>${esc(c.summary)}</div>` : ""}</div>`).join("") || '<p class="muted small">没有会话。点「＋ 新消息」粘贴买家消息，或者用浏览器扩展在卖家中心读取。</p>';
    if (!quiet && CUR && !d.convs.some((c) => c.id === CUR)) { CUR = null; $("#cs-main").innerHTML = emptyMain(); }
    if (quiet && CUR) { // 扩展那边有新消息时刷新当前会话（不打断正在编辑的草稿）
      const cur = d.convs.find((c) => c.id === CUR);
      if (cur && CONV && cur.updated_at > CONV.updated_at + 0.5 && !document.activeElement.closest("#cs-main")) openConv(CUR);
    }
  }
  function emptyMain() {
    return `<div class="cs-empty"><h3>AI 客服</h3><p class="muted">左边选一个会话，或者点「＋ 新消息」。</p>
      <ol class="small muted"><li>把买家的消息粘贴进来（或者上传聊天截图，AI 会自己读出文字）</li>
      <li>点「🤖 AI 生成回复」：AI 按产品资料、订单、店铺政策写泰语回复，附中文意思</li>
      <li>看一下、改一改，点「📋 复制」，到平台聊天里粘贴发送，再点「✓ 已发送」（AI 会从你改过的回复里学习）</li>
      <li>定制要求、备注一键写进订单；批发询价一键生成报价单</li></ol>
      <p class="small muted">装了浏览器扩展的话，在 Lazada / Shopee / TikTok 卖家中心的聊天页面就能直接读取和填入，不用复制粘贴。</p></div>`;
  }

  // ---------------- 一个会话 ----------------
  async function openConv(cid) {
    CUR = cid;
    $$("#cs-items .cs-item").forEach((x) => x.classList.toggle("on", +x.dataset.cid === cid));
    CONV = await api(`/api/cs/convs/${cid}`);
    render();
  }
  function orderBox(c) {
    const o = c.order;
    if (o) {
      const prog = Object.entries(o.production || {}).map(([k, v]) => `${esc(k)} ${v}`).join(" · ");
      return `<div class="cs-order"><div class="row between"><b>订单 <span class="mono" data-notr>${esc(o.order_no)}</span></b>
          <span><button class="mini" data-cs="open-order" data-oid="${o.id}">在订单里打开</button> <button class="mini" data-cs="unlink">取消关联</button></span></div>
        <div class="small">${esc(o.status_zh || "")} · ${o.ship_by ? "最晚发货 " + fmtTime(o.ship_by).slice(5, 16) : ""} ${o.tracking_no ? ` · 运单 <span class="mono" data-notr>${esc(o.tracking_no)}</span>` : ""}
          ${prog ? ` · 生产：${prog}` : ""}</div>
        <div class="small" data-notr>${(o.items || []).map((i) => `${esc(i.sku || "")} ${esc(i.color || "")} ×${i.qty}`).join("，")}</div>
        ${o.custom_note ? `<div class="small note-flag" data-notr>✎ ${esc(o.custom_note)}</div>` : ""}</div>`;
    }
    return `<div class="cs-order none"><div class="row gap wrap small"><span class="muted">没有关联订单</span>
        <input id="cs-ono" placeholder="订单号" style="width:180px" data-notr><button class="mini" data-cs="link">关联</button></div>
      ${(c.order_candidates || []).length ? `<div class="small">可能是：${c.order_candidates.map((o) => `<button class="mini" data-cs="link-id" data-oid="${o.id}"><span data-notr>${esc(o.order_no)}</span> ${esc(o.status_zh || "")}</button>`).join(" ")}</div>` : ""}</div>`;
  }
  function msgHtml(m) {
    return `<div class="cs-msg r-${m.role}" data-mid="${m.id}">
      <div class="cs-bubble"><div data-notr>${esc(m.text).replace(/\n/g, "<br>")}</div>
        ${m.text_zh ? `<div class="cs-zh" data-notr>${esc(m.text_zh)}</div>` : ""}</div>
      <div class="cs-meta small muted">${esc(ROLE[m.role] || m.role)} · ${fmtTime(m.created_at).slice(5, 16)}${m.username ? ` · <span data-notr>${esc(String(m.username).replace(/^api:/, ""))}</span>` : ""}${m.role === "seller" && m.source === "auto" ? " · 🤖" : ""}${m.role === "seller" && m.ai_draft && m.source !== "auto" ? (m.ai_draft.trim() === (m.text || "").trim() ? ` · ${Z("用了 AI 原稿", "ใช้ร่าง AI")}` : ` · ${Z("改过 AI 稿", "แก้ร่าง AI")}`) : ""}
        ${m.source === "screenshot" ? " · 截图" : m.source === "extension" ? " · 扩展" : ""}${CAN("cs.delete") ? '<button class="linkbtn" data-cs="del-msg" title="删除">✕</button>' : ""}</div></div>`;
  }
  function render() {
    const c = CONV;
    const a = c.analysis || {};
    const hasBuyer = c.messages.some((m) => m.role === "buyer");
    $("#cs-main").innerHTML = `
      <div class="cs-head row between wrap gap">
        <div class="row gap wrap"><input id="cs-buyer" value="${esc(c.buyer || "")}" placeholder="买家名字" data-notr style="width:160px">
          <select id="cs-plat">${Object.entries(PLAT).map(([k, v]) => `<option value="${k}" ${k === (c.platform || "manual") ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
          <input id="cs-shop" value="${esc(c.shop || "")}" placeholder="${Z("店铺", "ร้าน")}" data-notr style="width:120px" list="cs-shop-list"><datalist id="cs-shop-list">${(SHOPS || []).map((x) => `<option value="${esc(x)}">`).join("")}</datalist>
          ${c.intent ? `<span class="pill tag-pill">${esc(a.intent_zh || c.intent)}</span>` : ""}
          ${a.tier ? `<span class="pill ${TIER_CLS[a.tier] || ""}">${esc(Z(...(TIER_TXT[a.tier] || ["", ""])))}</span>` : ""}</div>
        <div class="row gap">${c.status === "closed" ? '<button class="mini" data-cs="reopen">重新打开</button>' : '<button class="mini" data-cs="close">结束会话</button>'}
          ${CAN("cs.delete") ? '<button class="mini danger" data-cs="del-conv">删除</button>' : ""}</div>
      </div>
      ${c.needs_human ? `<div class="alert-box">⚠ 需要人工处理：<span data-notr>${esc(reasonOf(c))}</span> <button class="mini" data-cs="human-done">已处理</button></div>` : ""}
      ${sumOf(c) ? `<div class="small" data-notr>📝 ${esc(sumOf(c))}</div>` : ""}
      ${orderBox(c)}
      ${infoBox(c)}
      ${custBox(c)}
      <div class="cs-msgs">${c.messages.map(msgHtml).join("") || '<p class="muted small">还没有消息</p>'}</div>
      <div class="cs-add">
        <textarea id="cs-text" rows="2" placeholder="粘贴买家的消息（可以一次粘贴好几条）。也可以直接 Ctrl+V 粘贴聊天截图" data-notr></textarea>
        <div class="row gap wrap"><select id="cs-role"><option value="buyer">买家说的</option><option value="seller">我们回复的</option><option value="note">内部备注</option></select>
          <button data-cs="add">添加</button>
          <label class="filebtn">📷 上传聊天截图<input type="file" id="cs-shot" accept="image/*" hidden></label>
          <span class="small muted">截图会让 AI 读出里面的对话</span></div>
      </div>
      <div class="cs-draft card">
        <div class="row gap wrap"><button class="primary" data-cs="draft" ${hasBuyer ? "" : "disabled"}>🤖 AI 生成回复</button>
          <input id="cs-instr" placeholder="可选：给 AI 的要求，例如「语气更正式」「告诉他明天发货」「可以送一个小礼物」" style="flex:1;min-width:220px">
          ${c.draft_at ? `<span class="small muted">生成于 ${fmtTime(c.draft_at).slice(5, 16)}${a.confidence != null ? ` · 把握 ${Math.round(a.confidence * 100)}%` : ""}</span>` : ""}</div>
        ${hasBuyer || c.draft ? `
          <label class="small cs-zhin-l">${Z("✍ 用中文写（自动翻成泰语填到下面）", "✍ พิมพ์ภาษาจีน (แปลเป็นไทยให้อัตโนมัติ)")} <span class="muted" id="cs-tr-st"></span>
            <textarea id="cs-zhin" rows="2" data-notr placeholder="${Z("例如：您好，这个颜色有现货，今天下单明天发货", "เช่น 您好，这个颜色有现货")}"></textarea></label>
          <textarea id="cs-reply" rows="4" data-notr placeholder="${Z("发给买家的回复（泰语）", "ข้อความตอบลูกค้า (ภาษาไทย)")}">${esc(c.draft || "")}</textarea>
          ${c.draft_zh ? `<div class="small cs-zh" data-notr id="cs-reply-zh">中文意思：${esc(c.draft_zh)}</div>` : '<div class="small cs-zh" data-notr id="cs-reply-zh"></div>'}
          <div class="row gap wrap"><button class="primary" data-cs="copy">📋 复制回复</button>
            <button data-cs="sent">✓ 已发送（记录下来）</button>
            <button class="mini" data-cs="tr">翻译成中文看看</button></div>
          ${(c.suggestions || []).length ? `<div class="cs-sugg"><b class="small">可以一键做：</b>${c.suggestions.map((s, i) => `<div class="row gap small">
            <button class="mini primary" data-cs="sugg" data-i="${i}" ${s.need_order ? "disabled" : ""}>${esc(s.label)}</button>
            ${s.text ? `<span data-notr>${esc(s.text)}</span>` : ""}${s.need_order ? '<span class="warn">（先关联订单）</span>' : ""}</div>`).join("")}</div>` : ""}
          ${a.quote && a.quote.lines && a.quote.lines.length ? quoteHtml(a.quote) : ""}` : `<p class="small muted">先添加买家的消息。</p>`}
        ${c.messages.some((m) => m.role === "seller") ? '<div class="small"><button class="linkbtn" data-cs="kb">把这次的问答存为常见问答</button></div>' : ""}
      </div>`;
    const box = $(".cs-msgs", $("#cs-main"));
    box.scrollTop = box.scrollHeight;
  }
  // v2.24：客户档案 + 登记（备注 / 待办 / 售后 / 投诉 / 特殊需求）
  function custBox(c) {
    const cu = c.customer;
    const recs = (cu && cu.records) || c.records || [];
    const K = c.record_kinds || {};
    const KT = { note: "บันทึก", todo: "ติดตาม", aftersales: "หลังการขาย", complaint: "ร้องเรียน", request: "ความต้องการพิเศษ" };
    return `<details class="cs-cust" ${recs.some((r) => r.status === "open") ? "open" : ""}><summary class="small"><b>📒 ${Z("客户档案与登记", "ประวัติลูกค้าและบันทึก")}</b>
        ${cu ? ` · ${Z(`第 ${cu.visits} 次来`, `มาครั้งที่ ${cu.visits}`)}${cu.orders.length ? ` · ${Z("订单", "ออเดอร์")} <span data-notr>${esc(cu.orders.join("、"))}</span>` : ""}` : ` · ${Z("填了买家名字和店铺后自动建档", "ใส่ชื่อลูกค้าและร้านแล้วจะสร้างประวัติให้")}`}
        ${recs.length ? ` · ${Z(`${recs.length} 条登记`, `${recs.length} รายการ`)}${recs.some((r) => r.overdue) ? ` <span class="bad">⏰ ${Z("有到期的", "ถึงกำหนด")}</span>` : ""}` : ""}</summary>
      ${cu ? `<div class="row gap small">${Z("标签", "แท็ก")} <input id="cs-ctags" value="${esc(cu.tags || "")}" data-notr placeholder="${Z("例如 VIP、批发、爱砍价", "เช่น VIP ขายส่ง")}" style="flex:1">
        ${(cu.convs || []).length ? `<span class="muted">${Z("以前的会话", "แชทก่อนหน้า")}：${cu.convs.slice(0, 5).map((x) => `<a href="#" data-cs="goconv" data-id="${x.id}">${fmtTime(x.updated_at).slice(5, 10)}</a>`).join(" ")}</span>` : ""}</div>` : ""}
      <div class="cs-recs">${recs.map((r) => `<div class="cs-rec ${r.status} ${r.overdue ? "od" : ""}"><span class="pill">${esc(TH() ? KT[r.kind] || r.kind_zh : r.kind_zh)}</span>
          <span data-notr>${esc(r.text)}</span>${r.result ? ` <span class="muted" data-notr>→ ${esc(r.result)}</span>` : ""}
          <span class="muted"> · <span data-notr>${esc(r.agent || "")}</span>${r.shop ? ` · <span data-notr>${esc(r.shop)}</span>` : ""} · ${fmtTime(r.created_at).slice(5, 16)}${r.due_at ? ` · ${Z("到期", "กำหนด")} ${fmtTime(r.due_at).slice(5, 16)}` : ""}</span>
          ${r.kind !== "note" ? (r.status === "open" ? `<button class="mini" data-cs="rec-done" data-id="${r.id}">✓ ${Z("完成", "เสร็จ")}</button>` : `<span class="ok small">✓</span>`) : ""}</div>`).join("")}</div>
      <div class="row gap wrap"><select id="cs-rkind">${Object.entries(K).map(([k, v]) => `<option value="${k}">${esc(TH() ? KT[k] || v : v)}</option>`).join("")}</select>
        <input id="cs-rtext" placeholder="${Z("登记内容，例如：她要 50 个粉色，下周三前要", "รายละเอียด")}" data-notr style="flex:1;min-width:200px">
        <input id="cs-rdue" type="datetime-local" title="${Z("到期时间（待办 / 售后可选）", "กำหนดเวลา")}">
        <button class="mini primary" data-cs="rec-add">${Z("登记", "บันทึก")}</button></div></details>`;
  }
  // v2.22：买家历史、需求标签、销售跟进
  function infoBox(c) {
    const h = c.buyer_history, a = c.analysis || {};
    const needs = c.needs || [];
    const due = c.next_follow_at && c.next_follow_at * 1000 <= Date.now();
    return `<div class="cs-info small">
      ${h ? `<div>👤 ${h.repeat ? `<b class="ok">${Z("老顾客", "ลูกค้าเก่า")}</b> · ` : ""}${Z(`买过 ${h.orders} 单，共 ฿${Math.round(h.spent)}`, `ซื้อ ${h.orders} ครั้ง รวม ฿${Math.round(h.spent)}`)}${h.last_order ? ` · ${Z("上次", "ล่าสุด")} ${h.last_order}` : ""}${h.level ? ` · ${esc(h.level)}` : ""}${h.past_chats ? ` · ${Z(`以前聊过 ${h.past_chats} 次`, `เคยคุย ${h.past_chats} ครั้ง`)}` : ""}
        ${(h.recent || []).length ? `<details><summary>${Z("最近的订单", "คำสั่งซื้อล่าสุด")}</summary>${h.recent.map((o) => `<div data-notr>${esc(o.day)} <span class="mono">${esc(o.order_no)}</span> ${esc(o.status)} ฿${o.total ?? ""} — ${esc((o.items || []).join("，"))}</div>`).join("")}</details>` : ""}</div>` : ""}
      <div class="row gap wrap">🏷 ${(c.tag_list || []).map((t) => `<span class="pill" data-notr>${esc(t)}</span>`).join("") || `<span class="muted">${Z("没有标签", "ไม่มีแท็ก")}</span>`}
        <button class="linkbtn" data-cs="tags">${Z("改标签", "แก้แท็ก")}</button></div>
      ${needs.length ? `<div>📌 ${Z("客户需求", "ความต้องการ")}：${needs.map((n) => `<span data-notr>${n.type ? `<b>${esc(n.type)}</b> ` : ""}${esc(n.detail_zh)}</span>`).join("；")}</div>` : ""}
      <div class="row gap wrap cs-lead">💼 <select data-cs-lead="stage"><option value="">${Z("不是销售线索", "ไม่ใช่โอกาสขาย")}</option>
          ${Object.keys(STAGE).map((k) => `<option value="${k}" ${c.lead_stage === k ? "selected" : ""}>${esc(stageTxt(k))}</option>`).join("")}</select>
        ${c.lead_stage ? `<span class="${due ? "bad" : "muted"}">${c.next_follow_at ? `${Z("下次跟进", "ติดตามครั้งต่อไป")} ${fmtTime(c.next_follow_at).slice(5, 16)}${due ? " ⏰" : ""}` : ""}</span>
          <select data-cs-lead="days"><option value="">${Z("改跟进时间…", "เลื่อนเวลาติดตาม…")}</option><option value="1">${Z("明天", "พรุ่งนี้")}</option><option value="3">${Z("3 天后", "อีก 3 วัน")}</option><option value="7">${Z("一周后", "อีก 1 สัปดาห์")}</option><option value="0">${Z("不用提醒", "ไม่ต้องเตือน")}</option></select>
          ${c.lead_value ? `<span>≈ ฿${Math.round(c.lead_value)}</span>` : ""}` : ""}
        ${c.follow_note ? `<span class="muted" data-notr>→ ${esc(c.follow_note)}</span>` : ""}</div>
      ${a.unknown_question_zh ? `<div class="warn">❓ ${Z("AI 答不上来", "AI ตอบไม่ได้")}：<span data-notr>${esc(a.unknown_question_zh)}</span>（${Z("已记到「待补充的知识」", "บันทึกไว้ใน「ความรู้ที่ต้องเพิ่ม」")}）</div>` : ""}
    </div>`;
  }
  // 实时翻译：中文打字 → 泰语（停顿 0.8 秒就翻）
  let TR_T = null, TR_SEQ = 0;
  async function liveTranslate() {
    const zh = ($("#cs-zhin") || {}).value || "";
    if (!zh.trim()) return;
    const seq = ++TR_SEQ;
    $("#cs-tr-st").textContent = Z("翻译中…", "กำลังแปล…");
    try {
      const r = await api("/api/cs/translate", { json: { text: zh, to: "th", conv_id: CUR } });
      if (seq !== TR_SEQ) return;
      $("#cs-reply").value = r.text;
      $("#cs-reply-zh").textContent = Z("中文意思：", "ความหมาย: ") + zh;
      $("#cs-tr-st").textContent = "✓";
    } catch (e) { if (seq === TR_SEQ) $("#cs-tr-st").textContent = e.message; }
  }
  function quoteHtml(q) {
    return `<details class="small"><summary>报价明细（批发折扣 ${q.discount_pct}% · 约 ${q.ship_days} 天发货）</summary>
      <table class="tbl"><tr><th>SKU</th><th>款式</th><th>数量</th><th>原价</th><th>报价单价</th><th>小计</th></tr>
      ${q.lines.map((l) => `<tr><td class="mono" data-notr>${esc(l.sku)}</td><td data-notr>${esc(l.name)} ${esc(l.option)}</td><td>${l.qty}</td><td>${l.price}</td>
        <td>${l.unit_price}${l.floor_hit ? ' <span class="warn">（已是最低价）</span>' : ""}</td><td>${l.total}</td></tr>`).join("")}
      <tr><td colspan="5"><b>合计</b></td><td><b>${q.total}</b></td></tr></table></details>`;
  }

  async function upShot(file) {
    if (!file || !CUR) return;
    const fd = new FormData(); fd.append("image", file);
    toast("AI 正在读截图…", false, 30000);
    const r = await api(`/api/cs/convs/${CUR}/screenshot`, { method: "POST", body: fd });
    CONV = r; render(); toast(`读出 ${r.added} 条新消息`);
    loadList(true);
  }

  async function newDialog() {
    const el = MODAL.open(`<div class="row between"><h3>新消息</h3><button class="mini" data-mclose>关闭</button></div>
      <div class="form2"><label>买家<input id="nc-buyer" data-notr placeholder="买家名字（可空）"></label>
        <label>平台<select id="nc-plat">${Object.entries(PLAT).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label></div>
      <label>买家的消息<textarea id="nc-text" rows="5" data-notr placeholder="粘贴买家发来的话"></textarea></label>
      <label>或者上传聊天截图<input type="file" id="nc-shot" accept="image/*"></label>
      <label>订单号（可空）<input id="nc-ono" data-notr></label>
      <label class="row"><input type="checkbox" id="nc-draft" checked> 马上让 AI 生成回复</label>
      <button class="big primary" id="nc-ok">开始</button>`);
    $("#nc-ok", el).onclick = () => busy($("#nc-ok", el), async () => {
      const shot = $("#nc-shot", el).files[0];
      const text = $("#nc-text", el).value.trim();
      if (!text && !shot) { toast("请粘贴消息或上传截图", true); return; }
      let c = await api("/api/cs/convs", { json: { buyer: $("#nc-buyer", el).value.trim(), platform: $("#nc-plat", el).value, text, order_no: $("#nc-ono", el).value.trim() } });
      CUR = c.id;
      if (shot) { const fd = new FormData(); fd.append("image", shot); c = await api(`/api/cs/convs/${c.id}/screenshot`, { method: "POST", body: fd }); }
      if ($("#nc-draft", el).checked && c.messages.some((m) => m.role === "buyer")) c = await api(`/api/cs/convs/${c.id}/draft`, { json: {} });
      MODAL.close();
      CONV = c; render(); loadList(true);
    });
  }

  // ---------------- 事件 ----------------
  document.addEventListener("click", async (e) => {
    const it = e.target.closest("#cs-items .cs-item");
    if (it) { openConv(+it.dataset.cid).catch((err) => toast(err.message, true)); return; }
    if (e.target.id === "cs-new") { newDialog(); return; }
    const b = e.target.closest("#cs-main [data-cs], #tab-cskb [data-kb], #tab-settings [data-kb]");
    if (!b) return;
    const act = b.dataset.cs;
    try {
      if (b.dataset.kb) return kbClick(b);
      const post = async (url, body) => { CONV = await api(url, { json: body || {} }); render(); loadList(true); return CONV; };
      if (act === "rec-add") {
        const t = $("#cs-rtext").value.trim(); if (!t) return toast(Z("先写登记内容", "กรอกรายละเอียดก่อน"), true);
        const dv = $("#cs-rdue").value;
        await api("/api/cs/records", { json: { conv_id: CUR, kind: $("#cs-rkind").value, text: t, due_at: dv ? new Date(dv).getTime() / 1000 : "" } });
        CONV = await api(`/api/cs/convs/${CUR}`); render();
        const det = $(".cs-cust"); if (det) det.open = true;
        toast(Z("已登记", "บันทึกแล้ว"));
        return;
      }
      if (act === "rec-done") {
        const res = prompt(Z("处理结果（可空）", "ผลการจัดการ (ไม่ใส่ก็ได้)"), "");
        if (res === null) return;
        await api(`/api/cs/records/${b.dataset.id}`, { json: { status: "done", result: res } });
        CONV = await api(`/api/cs/convs/${CUR}`); render();
        const det = $(".cs-cust"); if (det) det.open = true;
        return;
      }
      if (act === "goconv") { e.preventDefault(); return openConv(+b.dataset.id); }
      if (act === "add") {
        const t = $("#cs-text").value.trim(); if (!t) return;
        await post(`/api/cs/convs/${CUR}/messages`, { role: $("#cs-role").value, text: t });
      }
      if (act === "draft") {
        await busy(b, () => post(`/api/cs/convs/${CUR}/draft`, { instruction: $("#cs-instr").value.trim() }));
      }
      if (act === "copy") {
        const t = $("#cs-reply").value;
        try { await navigator.clipboard.writeText(t); } catch { $("#cs-reply").select(); document.execCommand("copy"); }
        toast("已复制，到平台聊天里粘贴发送；发完回来点「已发送」");
      }
      if (act === "sent") { await post(`/api/cs/convs/${CUR}/sent`, { text: $("#cs-reply").value }); toast("已记录"); }
      if (act === "tr") {
        const r = await busy(b, () => api("/api/cs/translate", { json: { text: $("#cs-reply").value, to: "zh" } }));
        toast(r.text, false, 12000);
      }
      if (act === "sugg") {
        const s = CONV.suggestions[+b.dataset.i];
        if (s.type === "aftersales") { if (window.OPS) { showTab("orders"); OPS.openOrder(s.order_id); } return; }
        if (s.type === "quote" && !confirm(`生成报价单？${s.label}`)) return;
        const r = await busy(b, () => post(`/api/cs/convs/${CUR}/action`, s)); toast(r.message);
      }
      if (act === "link") { const r = await post(`/api/cs/convs/${CUR}/action`, { type: "link_order", order_no: $("#cs-ono").value.trim() }); toast(r.message); }
      if (act === "link-id") { const r = await post(`/api/cs/convs/${CUR}/action`, { type: "link_order", order_id: +b.dataset.oid }); toast(r.message); }
      if (act === "unlink") await post(`/api/cs/convs/${CUR}/action`, { type: "unlink_order" });
      if (act === "open-order") { showTab("orders"); OPS.openOrder(+b.dataset.oid); }
      if (act === "close" || act === "reopen" || act === "human-done") await post(`/api/cs/convs/${CUR}/action`, { type: act === "human-done" ? "human_done" : act });
      if (act === "kb") { const r = await post(`/api/cs/convs/${CUR}/action`, { type: "kb" }); toast(r.message); }
      if (act === "tags") {
        const t = prompt(Z("标签（逗号分隔），例如 批发,送礼,急单", "แท็ก (คั่นด้วยจุลภาค)"), (CONV.tag_list || []).join(","));
        if (t !== null) await post(`/api/cs/convs/${CUR}/action`, { type: "tags", tags: t });
      }
      if (act === "del-msg") {
        if (!confirmDelete("这条消息")) return;
        await api(`/api/cs/messages/${b.closest("[data-mid]").dataset.mid}`, { method: "DELETE" });
        await openConv(CUR);
      }
      if (act === "del-conv") {
        if (!confirmDelete("这个会话（里面的全部消息）")) return;
        await api(`/api/cs/convs/${CUR}`, { method: "DELETE" });
        CUR = null; $("#cs-main").innerHTML = emptyMain(); loadList();
      }
    } catch (err) { toast(err.message, true); }
  });
  document.addEventListener("change", async (e) => {
    try {
      if (e.target.id === "cs-filter") loadList();
      if (e.target.dataset && e.target.dataset.csLead && CUR) {
        const body = { type: "lead" };
        if (e.target.dataset.csLead === "stage") body.stage = e.target.value;
        else if (e.target.value !== "") body.stage = CONV.lead_stage, body.days = e.target.value;
        else return;
        CONV = await api(`/api/cs/convs/${CUR}/action`, { json: body }); render(); loadList(true);
      }
      if (e.target.id === "cs-shot") { const f = e.target.files[0]; e.target.value = ""; await upShot(f); }
      if (e.target.id === "cs-buyer" || e.target.id === "cs-plat" || e.target.id === "cs-shop") {
        CONV = await api(`/api/cs/convs/${CUR}`, { json: { buyer: $("#cs-buyer").value.trim(), platform: $("#cs-plat").value, shop: $("#cs-shop").value.trim() } });
        render(); loadList(true);
      }
      if (e.target.id === "cs-shopf" || e.target.id === "cs-agentf") loadList();
      if (e.target.id === "cs-ctags" && CONV && CONV.customer) {
        await api(`/api/cs/customers/${CONV.customer.id}`, { json: { tags: e.target.value.trim() } });
        toast(Z("标签已保存", "บันทึกแท็กแล้ว"));
      }
    } catch (err) { toast(err.message, true); }
  });
  document.addEventListener("paste", (e) => {
    if (!e.target.closest || !e.target.closest("#cs-main")) return;
    const f = [...(e.clipboardData || {}).files || []].find((x) => x.type.startsWith("image/"));
    if (f) { e.preventDefault(); upShot(f).catch((err) => toast(err.message, true)); }
  });
  let QT = null;
  document.addEventListener("input", (e) => {
    if (e.target.id === "cs-q") { clearTimeout(QT); QT = setTimeout(() => loadList(), 300); }
    if (e.target.id === "cs-zhin") { clearTimeout(TR_T); TR_T = setTimeout(liveTranslate, 800); }
  });

  // ---------------- 知识库与话术 ----------------
  const SET_FIELDS = [
    ["shop_name", "店铺名字", 1], ["persona", "回复风格（语气、称呼、长度）", 3], ["ship_policy", "发货 / 制作时间", 2],
    ["return_policy", "退换货 / 破损处理", 3], ["custom_policy", "定制（颜色、刻字、尺寸）", 3],
    ["wholesale_tiers", "批发折扣档（数量:折扣%，逗号分隔，例如 10:5,30:10,50:15）", 1], ["wholesale_note", "批发说明", 2],
    ["extra", "其他补充（营业时间、活动、常见注意事项）", 3],
    ["playbook", "回复规则 / 预案（AI 每次回复都会遵守）", 10],
  ];
  async function loadKeys() {
    const box = $("#cskb-keys");
    if (!isOwner()) { box.innerHTML = '<p class="small muted">密钥由老板生成，请向老板要你自己的密钥。</p>'; return; }
    const d = await api("/api/integrations");
    box.innerHTML = `<h3>员工的扩展密钥（API 密钥）</h3>
      <p class="small muted">${Z("每个用扩展的员工建一个，名字用员工的登录账号名，填到扩展设置里。员工离职时删掉他的密钥即可。当前扩展版本", "สร้างให้พนักงานแต่ละคน ตั้งชื่อเป็นชื่อบัญชีเข้าระบบของพนักงาน ถ้าพนักงานลาออกให้ลบคีย์ เวอร์ชันส่วนขยายล่าสุด")} <b data-notr>${esc(d.ext_latest || "")}</b>：${Z("「扩展版本」显示旧版的，请重新下载扩展，解压覆盖原来的文件夹，再到 chrome://extensions 点扩展上的 ⟳ 重新加载。", "ถ้าเป็นเวอร์ชันเก่า ให้ดาวน์โหลดใหม่ แตกไฟล์ทับโฟลเดอร์เดิม แล้วกด ⟳ ที่ chrome://extensions")}</p>
      <div class="row gap wrap"><input id="ck-name" placeholder="员工名字，例如 Nok" style="width:200px" data-notr><button class="primary" data-kb="key-new">生成密钥</button></div>
      <div id="ck-out"></div>
      <table class="grid small"><thead><tr><th>名称</th><th>密钥开头</th><th>扩展版本</th><th>最后使用</th><th>次数</th><th></th></tr></thead><tbody>
      ${d.keys.map((k) => `<tr><td data-notr>${esc(k.name)}</td><td class="mono" data-notr>${esc(k.prefix)}…</td>
        <td>${!k.ext_version ? "-" : k.ext_version === d.ext_latest ? `<span class="ok" data-notr>${esc(k.ext_version)}</span>` : `<span class="warn">${esc(k.ext_version === "旧版" ? Z("旧版", "เวอร์ชันเก่า") : k.ext_version)} → ${Z("请更新扩展", "กรุณาอัปเดตส่วนขยาย")}</span>`}</td>
        <td>${k.last_used ? fmtTime(k.last_used) : "-"}</td><td>${k.uses || 0}</td>
        <td><button class="mini danger" data-kb="key-del" data-id="${k.id}">删除</button></td></tr>`).join("") || '<tr><td colspan="6" class="muted">还没有密钥</td></tr>'}</tbody></table>`;
  }
  async function loadKb() {
    KB = await api("/api/cs/kb");
    const s = KB.settings, own = isOwner();
    $("#cskb-settings").innerHTML = `${SET_FIELDS.map(([k, l, rows]) => `<label>${esc(l)}${rows > 1 ? `<textarea data-set="${k}" rows="${rows}" ${own ? "" : "readonly"} data-notr>${esc(s[k] || "")}</textarea>` : `<input data-set="${k}" value="${esc(s[k] || "")}" ${own ? "" : "readonly"} data-notr>`}</label>`).join("")}
      <h4>${Z("每类问题怎么处理（分级）", "แต่ละประเภทคำถามจัดการอย่างไร")}</h4>
      <label class="row"><input type="checkbox" data-set="auto_send" data-bool ${s.auto_send === "1" ? "checked" : ""} ${own ? "" : "disabled"}> 允许全自动发送（关掉后扩展最多只能半自动：写好回复由员工按发送）</label>
      <div class="cs-tiers">${Object.entries(KB.intents).map(([k, v]) => `<label class="small">${esc(v)}
        <select data-tier="${k}" ${own && !["complaint", "refund", "change_order"].includes(k) ? "" : "disabled"}>${Object.keys(KB.tier_names).map((t) => `<option value="${t}" ${KB.tiers[k] === t ? "selected" : ""}>${esc(Z(...({ auto: ["自动发送", "ส่งอัตโนมัติ"], confirm: ["AI 写好，人确认后发", "AI เขียน คนตรวจแล้วส่ง"], human: ["转人工", "ส่งให้คนจัดการ"] }[t])))}</option>`).join("")}</select></label>`).join("")}</div>
      <div class="small muted">${Z("退款、投诉、改订单永远转人工。「自动发送」只在扩展的全自动模式、AI 把握够高、回复里没有要承诺的内容时才会发；否则写好草稿等人确认。",
        "คืนเงิน ร้องเรียน แก้ออเดอร์ ส่งให้คนจัดการเสมอ 「ส่งอัตโนมัติ」จะส่งเฉพาะในโหมดอัตโนมัติของส่วนขยาย เมื่อ AI มั่นใจพอ และคำตอบไม่มีการสัญญาอะไร ไม่อย่างนั้นจะเขียนร่างไว้รอคนตรวจ")}</div>
      <label>${Z("AI 不能自己答应的事（写给 AI 看）", "สิ่งที่ AI สัญญาเองไม่ได้")}<textarea data-set="forbidden" rows="2" ${own ? "" : "readonly"} data-notr>${esc(s.forbidden || "")}</textarea></label>
      <label>${Z("回复里出现这些词就转人工（逗号分隔，泰文 / 中文都可以）", "ถ้าคำตอบมีคำเหล่านี้ให้ส่งให้คนตรวจ (คั่นด้วยจุลภาค)")}<input data-set="forbidden_words" value="${esc(s.forbidden_words || "")}" ${own ? "" : "readonly"} data-notr></label>
      <label class="row"><input type="checkbox" data-set="smart" data-bool ${s.smart === "1" ? "checked" : ""} ${own ? "" : "disabled"}> ${Z("更灵活：信息不够时追问、推荐相关产品 / 套装、认出老顾客", "ยืดหยุ่นขึ้น: ถามเพิ่มเมื่อข้อมูลไม่พอ แนะนำสินค้าที่เกี่ยวข้อง จำลูกค้าเก่าได้")}</label>
      <div class="form3"><label>${Z("从人工回复里学习", "เรียนรู้จากคำตอบของคน")}<select data-set="learn_mode" ${own ? "" : "disabled"}>
          ${[["suggest", Z("学到的先放「待确认」", "เก็บไว้รอยืนยันก่อน")], ["auto", Z("直接加进知识库", "เพิ่มเข้าคลังความรู้เลย")], ["off", Z("不学", "ไม่เรียนรู้")]].map(([v, l]) => `<option value="${v}" ${s.learn_mode === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label>${Z("新的销售线索几小时后提醒跟进", "เตือนติดตามลูกค้าใหม่หลังกี่ชั่วโมง")}<input data-set="follow_hours" value="${esc(s.follow_hours || "24")}" ${own ? "" : "readonly"}></label></div>
      <div class="form3"><label>AI 把握至少（0–1）<input data-set="auto_min_conf" value="${esc(s.auto_min_conf)}" ${own ? "" : "readonly"}></label>
        <label>每小时最多自动发送<input data-set="auto_max_per_hour" value="${esc(s.auto_max_per_hour)}" ${own ? "" : "readonly"}></label>
        <label>客服用的 AI 模型（空 = 和设置页一样）<input data-set="model" value="${esc(s.model || "")}" placeholder="例如 claude-haiku-4-5-20251001（更快更便宜）" ${own ? "" : "readonly"} data-notr></label></div>
      <h4>超时提醒（手机）</h4>
      <div class="small muted">买家消息超过设定的分钟数没回复：客服工作台和工作台首页标红；填了 Telegram 还会推送到手机（同一个买家只提醒一次，直到他再发新消息）。
        设置方法：① 手机装 Telegram，搜索 @BotFather，发 /newbot 按提示建一个机器人，复制它给的 token；② 给你的新机器人发一句 hi；③ 把 token 填在下面，点「自动获取 chat id」；④ 保存后点「发送测试」。</div>
      <div class="form3"><label>超过几分钟没回算超时（0 = 不提醒）<input data-set="alert_minutes" value="${esc(s.alert_minutes || "10")}" ${own ? "" : "readonly"}></label>
        <label>Telegram 机器人 token<input data-set="tg_token" value="${esc(s.tg_token || "")}" ${own ? "" : "readonly"} data-notr placeholder="123456:ABC…"></label>
        <label>Telegram chat id<input data-set="tg_chat" value="${esc(s.tg_chat || "")}" ${own ? "" : "readonly"} data-notr></label></div>
      ${own ? `<div class="row gap" data-lock-skip><button class="mini" data-kb="tg-find">自动获取 chat id</button><button class="mini" data-kb="tg-test">发送测试</button></div>` : ""}
      <h4>${Z("邮件通知（紧急、超时、跟进、周报）", "แจ้งเตือนทางอีเมล (ด่วน เกินเวลา ติดตาม รายงานรายสัปดาห์)")}</h4>
      <div class="small muted">${Z("紧急（投诉、退款、要人工的）马上发；买家超时没回、每天要跟进的客户、每周客服周报也发。发到老板邮箱和客服邮箱（几个邮箱用逗号隔开）。Gmail：服务器 smtp.gmail.com，端口 465，加密 SSL，用户名填邮箱，密码要用「应用专用密码」（Google 账号 → 安全性 → 两步验证 → 应用专用密码），不是登录密码。",
        "ด่วน (ร้องเรียน คืนเงิน ต้องให้คนจัดการ) ส่งทันที; เกินเวลา ลูกค้าที่ต้องติดตาม รายงานรายสัปดาห์ก็ส่ง ไปที่อีเมลเจ้าของและอีเมลแอดมิน Gmail: smtp.gmail.com พอร์ต 465 SSL รหัสผ่านใช้ App Password")}</div>
      <div class="form3"><label>${Z("老板邮箱", "อีเมลเจ้าของ")}<input data-set="owner_email" value="${esc(s.owner_email || "")}" ${own ? "" : "readonly"} data-notr></label>
        <label>${Z("客服邮箱", "อีเมลแอดมิน")}<input data-set="cs_email" value="${esc(s.cs_email || "")}" ${own ? "" : "readonly"} data-notr></label>
        <label>${Z("发件邮箱", "อีเมลผู้ส่ง")}<input data-set="smtp_from" value="${esc(s.smtp_from || "")}" ${own ? "" : "readonly"} data-notr placeholder="${Z("一般和用户名一样", "ปกติเหมือนชื่อผู้ใช้")}"></label>
        <label>${Z("发信服务器（SMTP）", "เซิร์ฟเวอร์ (SMTP)")}<input data-set="smtp_host" value="${esc(s.smtp_host || "")}" ${own ? "" : "readonly"} data-notr placeholder="smtp.gmail.com"></label>
        <label>${Z("端口", "พอร์ต")}<input data-set="smtp_port" onchange="const t=this.closest('form,div.card,body').querySelector('[data-set=smtp_tls]');if(t){if(this.value.trim()==='465')t.value='ssl';else if(['587','25','2525'].includes(this.value.trim()))t.value='starttls';}" value="${esc(s.smtp_port || "465")}" ${own ? "" : "readonly"}></label>
        <label>${Z("加密", "การเข้ารหัส")}<select data-set="smtp_tls" ${own ? "" : "disabled"}>${["ssl", "starttls", "none"].map((v) => `<option value="${v}" ${s.smtp_tls === v ? "selected" : ""}>${v === "ssl" ? "ssl（465）" : v === "starttls" ? "starttls（587）" : v}</option>`).join("")}</select></label>
        <label>${Z("用户名", "ชื่อผู้ใช้")}<input data-set="smtp_user" value="${esc(s.smtp_user || "")}" ${own ? "" : "readonly"} data-notr></label>
        <label>${Z("密码（应用专用密码）", "รหัสผ่าน (App Password)")}<input type="password" data-set="smtp_pass" value="" placeholder="${s.smtp_pass_set ? Z("已保存（留空不改）", "บันทึกแล้ว (เว้นว่าง = ไม่เปลี่ยน)") : ""}" ${own ? "" : "readonly"} autocomplete="new-password"></label></div>
      <div class="row gap wrap small">${[["email_urgent", Z("紧急马上发", "ด่วนส่งทันที")], ["email_overdue", Z("超时没回", "เกินเวลา")], ["email_follow", Z("每天要跟进的客户", "ลูกค้าที่ต้องติดตามรายวัน")], ["email_weekly", Z("每周周报", "รายงานรายสัปดาห์")]].map(([k, l]) =>
        `<label class="row"><input type="checkbox" data-set="${k}" data-bool ${s[k] === "1" ? "checked" : ""} ${own ? "" : "disabled"}> ${l}</label>`).join("")}
        <label>${Z("周报：星期", "รายงาน: วัน")}<select data-set="weekly_day" ${own ? "" : "disabled"}>${[1, 2, 3, 4, 5, 6, 7].map((d) => `<option ${String(d) === String(s.weekly_day) ? "selected" : ""}>${d}</option>`).join("")}</select></label>
        <label>${Z("几点", "เวลา")}<input data-set="weekly_hour" value="${esc(s.weekly_hour || "9")}" style="width:50px" ${own ? "" : "readonly"}></label></div>
      ${own ? `<div class="row gap" data-lock-skip><button class="mini" data-kb="mail-test">${Z("发一封测试邮件", "ส่งอีเมลทดสอบ")}</button></div>` : ""}
      ${own ? "" : '<p class="small muted">只有老板能修改店铺政策。</p>'}`;
    if (own) lockBox($("#cskb-settings"), { id: "cs-policy", bar: $("#cskb-setbar"), label: "✏ 修改店铺政策", onCancel: loadKb,
      onSave: async () => { await api("/api/cs/settings", { json: collectSettings() }); toast("已保存"); } });
    loadPerf();
    renderLearn();
    loadWeekly(false);
    $("#cskb-presets").innerHTML = KB.presets_missing ? `<button data-kb="presets">＋ 补充标准话术（${KB.presets_missing} 条）</button>` : '<span class="small muted">标准话术已全部加入</span>';
    $("#cskb-list").innerHTML = KB.kb.map((k) => `<tr><td data-notr>${esc(k.q)}</td><td data-notr>${esc(k.a)}${k.a_zh ? `<div class="small muted">${esc(k.a_zh)}</div>` : ""}</td>
      <td class="small">${esc(k.tags || "")}</td><td>${k.uses || 0}</td><td>${k.active ? "✅" : "停用"}</td>
      <td class="nowrap"><button class="mini" data-kb="edit" data-id="${k.id}">编辑</button> <button class="mini danger" data-kb="del" data-id="${k.id}">删除</button></td></tr>`).join("")
      || '<tr><td colspan="6" class="muted small">还没有。在会话里点「存为常见问答」，或者点上面的「添加」。</td></tr>';
    $("#cskb-ex").innerHTML = KB.examples.slice(0, 100).map((x) => `<tr><td class="small" data-notr>${esc(x.question.slice(0, 200))}</td>
      <td class="small" data-notr>${x.ai_reply && x.ai_reply !== x.final_reply ? `<div class="muted"><s>${esc(x.ai_reply.slice(0, 200))}</s></div>` : ""}${esc(x.final_reply.slice(0, 300))}</td>
      <td class="small">${fmtTime(x.created_at).slice(0, 10)} ${esc(x.username || "")}</td>
      <td>${own ? `<button class="mini danger" data-kb="del-ex" data-id="${x.id}">删除</button>` : ""}</td></tr>`).join("")
      || '<tr><td colspan="4" class="muted small">每次点「已发送」都会记下来，AI 下次遇到类似问题会参考。</td></tr>';
  }
  async function loadPerf() {
    const box = $("#cskb-perf"); if (!box) return;
    const days = +($("#cskb-perf-days") || {}).value || 7;
    const r = await api(`/api/cs/perf?days=${days}`), p = r.perf;
    const n = (v, u = "") => (v == null ? "-" : v + u);
    box.innerHTML = `<div class="row between"><h3>客服效果统计</h3><select id="cskb-perf-days">
        ${[1, 7, 30].map((x) => `<option value="${x}" ${x === days ? "selected" : ""}>最近 ${x} 天</option>`).join("")}</select></div>
      <div class="tiles">
        <div class="tile"><span>有买家消息的会话</span><b>${p.convs}</b></div>
        <div class="tile"><span>发出的回复</span><b>${p.sent}</b></div>
        <div class="tile"><span>其中自动发送</span><b>${p.auto}</b></div>
        <div class="tile"><span>AI 草稿直接采用率</span><b>${n(p.adopt_pct, "%")}</b><small>${p.with_draft} 条里改了 ${p.edited} 条</small></div>
        <div class="tile"><span>平均回复用时</span><b>${n(p.avg_reply_min)}<small> 分钟</small></b><small>中位数 ${n(p.median_reply_min)} 分钟</small></div>
        <div class="tile ${p.over_alert ? "warn" : ""}"><span>超时才回复</span><b>${p.over_alert}</b></div>
        <div class="tile ${r.overdue.length ? "bad" : ""}"><span>现在超时未回复</span><b>${r.overdue.length}</b></div>
      </div>
      <p class="small muted">采用率高、改得少的问题类型，可以放心在「自动回复」里打开全自动；被改得多的，看「学到的回复」找原因，补充到常见问答。</p>`;
    $("#cskb-perf-days").onchange = loadPerf;
  }
  function kbEdit(k, pending) {
    k = k || { q: "", a: "", a_zh: "", tags: "", active: 1 };
    const el = MODAL.open(`<div class="row between"><h3>${k.id ? "编辑" : "添加"}常见问答</h3><button class="mini" data-mclose>关闭</button></div>
      <label>买家常问的问题（可以写几种问法）<textarea id="kb-q" rows="3" data-notr>${esc(k.q)}</textarea></label>
      <label>标准回答（泰语，发给买家的）<textarea id="kb-a" rows="4" data-notr>${esc(k.a)}</textarea></label>
      <label>中文意思（给自己看）<textarea id="kb-azh" rows="2" data-notr>${esc(k.a_zh || "")}</textarea></label>
      <label>标签（可空）<input id="kb-tags" value="${esc(k.tags || "")}" data-notr></label>
      <label class="row"><input type="checkbox" id="kb-active" ${k.active ? "checked" : ""}> 启用</label>
      <div class="row gap"><button class="primary" id="kb-ok">保存</button><button id="kb-tr">把中文意思翻成泰语回答</button></div>`);
    $("#kb-tr", el).onclick = () => busy($("#kb-tr", el), async () => { const r = await api("/api/cs/translate", { json: { text: $("#kb-azh", el).value, to: "th" } }); $("#kb-a", el).value = r.text; });
    $("#kb-ok", el).onclick = () => busy($("#kb-ok", el), async () => {
      if (pending) await api(`/api/cs/kb/${k.id}/review`, { json: { ok: true, q: $("#kb-q", el).value, a: $("#kb-a", el).value, a_zh: $("#kb-azh", el).value, tags: $("#kb-tags", el).value } });
      else await api("/api/cs/kb", { json: { id: k.id, q: $("#kb-q", el).value, a: $("#kb-a", el).value, a_zh: $("#kb-azh", el).value, tags: $("#kb-tags", el).value, active: $("#kb-active", el).checked } });
      MODAL.close(); loadKb(); toast("已保存");
    });
  }
  function uaEdit(u) {
    const el = MODAL.open(`<div class="row between"><h3>${Z("给这个问题写答案（加进知识库）", "เขียนคำตอบ (เพิ่มเข้าคลังความรู้)")}</h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      <label>${Z("买家的问题", "คำถามลูกค้า")}<textarea id="ua-q" rows="3" data-notr>${esc(u.question)}</textarea></label>
      ${u.question_zh ? `<p class="small muted" data-notr>${esc(u.question_zh)}</p>` : ""}
      <label>${Z("答案（用中文写，自动翻成泰语）", "คำตอบ (เขียนจีน แปลไทยอัตโนมัติ)")}<textarea id="ua-zh" rows="2" data-notr></textarea></label>
      <label>${Z("泰语答案（发给买家的）", "คำตอบภาษาไทย")}<textarea id="ua-a" rows="3" data-notr></textarea></label>
      <div class="row gap"><button id="ua-tr">${Z("翻成泰语", "แปลเป็นไทย")}</button><button class="primary" id="ua-ok">${Z("保存到知识库", "บันทึก")}</button></div>`);
    $("#ua-tr", el).onclick = () => busy($("#ua-tr", el), async () => { const r = await api("/api/cs/translate", { json: { text: $("#ua-zh", el).value, to: "th" } }); $("#ua-a", el).value = r.text; });
    $("#ua-ok", el).onclick = () => busy($("#ua-ok", el), async () => {
      if (!$("#ua-a", el).value.trim()) { if ($("#ua-zh", el).value.trim()) { const r = await api("/api/cs/translate", { json: { text: $("#ua-zh", el).value, to: "th" } }); $("#ua-a", el).value = r.text; } else throw new Error(Z("先写答案", "เขียนคำตอบก่อน")); }
      await api(`/api/cs/unanswered/${u.id}`, { json: { q: $("#ua-q", el).value, a: $("#ua-a", el).value, a_zh: $("#ua-zh", el).value } });
      MODAL.close(); loadKb(); toast(Z("已加进知识库", "เพิ่มแล้ว"));
    });
  }
  async function loadWeekly(ai) {
    const box = $("#cskb-weekly"); if (!box) return;
    box.innerHTML = `<p class="muted small">${Z("生成中…", "กำลังสร้าง…")}</p>`;
    try {
      const r = await api(`/api/cs/weekly?${ai ? "ai=1" : "last=1"}`);
      box.innerHTML = `<div class="row between"><h3>${Z("客服周报", "รายงานรายสัปดาห์")} <span class="muted small">${esc(r.from)} ~ ${esc(r.to)}</span></h3>
        <div class="row gap"><button class="mini" data-kb="weekly">${Z("重新生成（含 AI 建议）", "สร้างใหม่ (มีคำแนะนำ AI)")}</button>${isOwner() ? `<button class="mini" data-kb="weekly-send">${Z("发到邮箱", "ส่งทางอีเมล")}</button>` : ""}</div></div>
        <pre class="cs-weekly" data-notr>${esc(r.text)}</pre>`;
    } catch (e) { box.innerHTML = `<p class="bad small">${esc(e.message)}</p>`; }
  }
  function renderLearn() {
    const box = $("#cskb-learn"); if (!box) return;
    const own = isOwner();
    box.innerHTML = `<h3>${Z("AI 学到的新知识（待确认）", "ความรู้ใหม่ที่ AI เรียนรู้ (รอยืนยัน)")} <span class="muted small">${KB.pending.length}</span></h3>
      <p class="small muted">${Z("员工改过 AI 的回复、或者自己写回复时，AI 会看有没有以后能复用的新知识（店铺做法、产品细节、政策），整理成问答放在这里。确认后加进知识库，以后 AI 就会了。",
        "เมื่อพนักงานแก้คำตอบของ AI หรือเขียนเอง AI จะดูว่ามีความรู้ใหม่ที่ใช้ซ้ำได้ไหม แล้วสรุปเป็นถามตอบไว้ที่นี่ ยืนยันแล้วจะเข้าคลังความรู้")}</p>
      <table class="grid small"><tbody>${KB.pending.map((k) => `<tr><td data-notr>${esc(k.q)}</td><td data-notr>${esc(k.a)}${k.a_zh ? `<div class="muted">${esc(k.a_zh)}</div>` : ""}<div class="muted">${esc(k.note || "")}</div></td>
        <td class="nowrap">${own ? `<button class="mini primary" data-kb="learn-ok" data-id="${k.id}">✓ ${Z("加入", "เพิ่ม")}</button> <button class="mini" data-kb="learn-edit" data-id="${k.id}">${Z("改一改", "แก้")}</button> <button class="mini danger" data-kb="learn-no" data-id="${k.id}">${Z("不要", "ไม่เอา")}</button>` : ""}</td></tr>`).join("")
        || `<tr><td class="muted">${Z("没有待确认的", "ไม่มีรายการรอยืนยัน")}</td></tr>`}</tbody></table>
      <h3>${Z("AI 答不上来的问题（待补充）", "คำถามที่ AI ตอบไม่ได้ (ต้องเพิ่ม)")} <span class="muted small">${KB.unanswered.length}</span></h3>
      <table class="grid small"><tbody>${KB.unanswered.map((u) => `<tr><td data-notr>${esc(u.question)}${u.question_zh ? `<div class="muted">${esc(u.question_zh)}</div>` : ""}</td><td>${u.count} ${Z("次", "ครั้ง")}</td>
        <td class="nowrap"><button class="mini primary" data-kb="ua-answer" data-id="${u.id}">${Z("写答案", "เขียนคำตอบ")}</button> <button class="mini" data-kb="ua-ignore" data-id="${u.id}">${Z("忽略", "ข้าม")}</button></td></tr>`).join("")
        || `<tr><td class="muted">${Z("没有", "ไม่มี")}</td></tr>`}</tbody></table>`;
  }
  function collectSettings() {
    const o = {}; $$("#cskb-settings [data-set]").forEach((x) => (o[x.dataset.set] = x.dataset.bool != null ? (x.checked ? "1" : "0") : x.value));
    const t = {}; $$("#cskb-settings [data-tier]").forEach((x) => (t[x.dataset.tier] = x.value));
    o.tiers = JSON.stringify(t);
    o.auto_intents = Object.keys(t).filter((k) => t[k] === "auto").join(",");
    if (!o.smtp_pass) delete o.smtp_pass;
    return o;
  }
  async function kbClick(b) {
    const a = b.dataset.kb, id = +b.dataset.id;

    if (a === "tg-find") {
      const r = await api("/api/cs/alert/chat-id", { json: { tg_token: $('#cskb-settings [data-set="tg_token"]').value } });
      $('#cskb-settings [data-set="tg_chat"]').value = r.chat_id;
      $('#cskb-settings [data-set="tg_chat"]').dispatchEvent(new Event("input", { bubbles: true }));
      toast(`找到了：${r.name || r.chat_id}。记得点「保存」`); return;
    }
    if (a === "mail-test") {
      const o = collectSettings();
      const r = await busy(b, () => api("/api/cs/mail/test", { json: o }));
      if (r) toast(Z(`已发送到 ${r.to.join("、")}，去邮箱看看（也看看垃圾邮件）`, `ส่งไปที่ ${r.to.join(", ")} แล้ว`), false, 8000);
      return;
    }
    if (a === "learn-ok" || a === "learn-no") {
      await api(`/api/cs/kb/${id}/review`, { json: { ok: a === "learn-ok" } }); loadKb(); return;
    }
    if (a === "learn-edit") { const k = KB.pending.find((x) => x.id === id); kbEdit(k, true); return; }
    if (a === "ua-answer") { const u = KB.unanswered.find((x) => x.id === id); uaEdit(u); return; }
    if (a === "ua-ignore") { await api(`/api/cs/unanswered/${id}`, { json: { ignore: true } }); loadKb(); return; }
    if (a === "weekly") { await loadWeekly(true); return; }
    if (a === "weekly-send") { const r = await busy(b, () => api("/api/cs/weekly/send", { json: {} })); if (r) toast(Z(`周报已发送到 ${r.to.join("、")}`, `ส่งรายงานไปที่ ${r.to.join(", ")} แล้ว`)); return; }
    if (a === "tg-test") {
      await api("/api/cs/alert/test", { json: { tg_token: $('#cskb-settings [data-set="tg_token"]').value, tg_chat: $('#cskb-settings [data-set="tg_chat"]').value } });
      toast("已发送，看看手机 Telegram 有没有收到"); return;
    }
    if (a === "key-new") {
      const name = $("#ck-name").value.trim() || "AI 客服扩展";
      const r = await api("/api/apikeys", { json: { name } });
      await loadKeys();
      $("#ck-out").innerHTML = `<p class="note-flag">新密钥（只显示这一次，请复制给员工）：<b class="mono" data-notr>${esc(r.key)}</b>
        <button class="mini" data-kb="key-copy" data-k="${esc(r.key)}">复制</button></p>`;
    }
    if (a === "key-copy") { try { await navigator.clipboard.writeText(b.dataset.k); toast("已复制"); } catch { toast(b.dataset.k, false, 20000); } }
    if (a === "key-del") { if (!confirm("删除这个密钥？用它的扩展会马上不能用。")) return; await api(`/api/apikeys/${id}`, { method: "DELETE" }); loadKeys(); }
    if (a === "presets") { const r = await busy(b, () => api("/api/cs/kb/presets", { json: {} })); toast(`已加入 ${r ? r.added : 0} 条标准话术`); loadKb(); }
    if (a === "add") kbEdit();
    if (a === "edit") kbEdit(KB.kb.find((k) => k.id === id));
    if (a === "del") { if (!confirm("删除这条问答？")) return; await api(`/api/cs/kb/${id}`, { method: "DELETE" }); loadKb(); }
    if (a === "del-ex") { if (!confirm("删除这条示例回复？")) return; await api(`/api/cs/examples/${id}`, { method: "DELETE" }); loadKb(); }
  }

  window.CS = { show, openConv, reload: () => loadList(true).catch(() => {}) };
})();
