"use strict";
// AI 客服模块：客服聊天（v2.46 三栏：会话列表 / 聊天 / 买家与订单）+ 知识库与话术。只调用 /api/cs/...
(function () {
  const PLAT = { lazada: "Lazada", shopee: "Shopee", tiktok: "TikTok", line: "LINE", facebook: "Facebook", manual: "其他" };
  const ROLE = { buyer: "买家", seller: "我们", note: "内部备注" };
  let CUR = null, CONV = null, TIMER = null, KB = null, SHOPS = [], ST = "active", AGENTS = [], ME = "", NEWEST = 0, FIRST = true;
  const isOwner = () => window.OPSH && OPSH.isOwner();
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const TIER_CLS = { auto: "ok-pill", confirm: "warn-pill", human: "bad-pill" };
  const TIER_TXT = { auto: ["可自动发", "ส่งอัตโนมัติได้"], confirm: ["AI 写好·人确认", "AI เขียน·คนตรวจ"], human: ["转人工", "ส่งให้คนจัดการ"] };
  const STAGE = { new: ["新线索", "ลูกค้าใหม่"], follow: ["跟进中", "กำลังติดตาม"], quoted: ["已报价", "เสนอราคาแล้ว"], won: ["成交", "ปิดการขาย"], lost: ["流失", "หลุด"] };
  const MODE = { off: ["只人工", "คนตอบเอง", "👤"], draft: ["AI 出草稿", "AI ร่างให้", "✍"], auto: ["AI 自动回复", "AI ตอบอัตโนมัติ", "🤖"] };
  const CH = { lazada_im: ["Lazada 接口", "Lazada API"], extension: ["浏览器扩展", "ส่วนขยาย"], manual: ["手工", "บันทึกเอง"] };
  const TABS = [["active", "全部", "ทั้งหมด"], ["unreplied", "未回复", "ยังไม่ตอบ"], ["human", "需人工", "ต้องใช้คน"], ["mine", "我的", "ของฉัน"],
    ["taken", "已接管", "คนรับช่วง"], ["leads", "线索", "โอกาสขาย"], ["closed", "已结束", "ปิดแล้ว"]];
  const stageTxt = (k) => (STAGE[k] ? Z(STAGE[k][0], STAGE[k][1]) : "");
  const sumOf = (c) => (TH() && c.analysis && c.analysis.summary_th) || c.summary || "";
  const reasonOf = (c) => (TH() && c.analysis && c.analysis.human_reason_th) || c.human_reason || "";
  const ago = (m) => (m == null ? "" : m < 60 ? `${m}${Z("分", "น.")}` : `${Math.floor(m / 60)}${Z("小时", "ชม.")}`);
  const waitCls = (m) => (m == null ? "" : m >= 15 ? "w-bad" : m >= 5 ? "w-warn" : "w-ok");
  const initial = (s) => esc((String(s || "?").trim()[0] || "?").toUpperCase());
  const ls = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { return null; } return v; };

  function show(name) {
    clearInterval(TIMER);
    if (name === "cs") {
      FIRST = true;
      loadList();
      TIMER = setInterval(() => { if (!document.hidden && $("#tab-cs") && !$("#tab-cs").classList.contains("hidden")) loadList(true); }, 8000);
    }
    if (name === "cskb") loadKb();
  }

  // ---------------- 提醒：声音 + 桌面通知 ----------------
  function beep() {
    if (ls("cs_sound") === "0") return;
    try {
      const a = new (window.AudioContext || window.webkitAudioContext)(), o = a.createOscillator(), g = a.createGain();
      o.connect(g); g.connect(a.destination); o.frequency.value = 880; g.gain.value = 0.08;
      o.start(); o.frequency.setValueAtTime(660, a.currentTime + 0.12); o.stop(a.currentTime + 0.25);
    } catch { /* 浏览器不让放声音 */ }
  }
  function notifyNew(c) {
    beep();
    if (ls("cs_notify") === "1" && window.Notification && Notification.permission === "granted" && document.hidden) {
      try { new Notification(Z("新的买家消息", "ข้อความใหม่จากลูกค้า"), { body: `${c.buyer || ""}: ${((c.last || {}).text || "").slice(0, 60)}` }); } catch { /* */ }
    }
  }

  // ---------------- 会话列表 ----------------
  async function loadList(quiet) {
    const q = ($("#cs-q") || {}).value || "", sf = $("#cs-shopf");
    const d = await api(`/api/cs/inbox?status=${encodeURIComponent(ST)}&q=${encodeURIComponent(q.trim())}&shop=${encodeURIComponent(sf ? sf.value : "")}`);
    SHOPS = d.shops || []; AGENTS = d.agents || []; ME = d.me || "";
    if (sf) { const cur = sf.value; sf.innerHTML = `<option value="">${Z("全部店铺", "ทุกร้าน")}</option>` + SHOPS.map((x) => `<option value="${esc(x)}" ${x === cur ? "selected" : ""} data-notr>${esc(x)}</option>`).join(""); }
    $("#cs-tabs").innerHTML = TABS.map(([k, zh, th]) => `<button class="cs-tab ${k === ST ? "on" : ""}" data-st="${k}">${Z(zh, th)}${d.counts[k] ? ` <b class="${k === "unreplied" || k === "human" ? "bad" : ""}">${d.counts[k]}</b>` : ""}</button>`).join("");
    $("#cs-sound").textContent = ls("cs_sound") === "0" ? "🔕" : "🔔";
    if (!FIRST && d.newest_buyer > NEWEST) {
      const c = d.convs.find((x) => (x.last_buyer_at || 0) >= d.newest_buyer - 0.5) || {};
      notifyNew(c);
    }
    NEWEST = Math.max(NEWEST, d.newest_buyer || 0); FIRST = false;
    const AM = d.alert_minutes || 5;
    $("#cs-items").innerHTML = d.convs.map((c) => {
      const waiting = c.last && c.last.role === "buyer" && c.status === "open";
      const m = MODE[c.mode === "human" ? "off" : c.ai_mode] || MODE.draft;
      return `<div class="cs-item ${c.id === CUR ? "on" : ""} st-${c.status} ${c.needs_human ? "need" : ""}" data-cid="${c.id}">
        <div class="cs-av" style="${c.avatar ? `background-image:url('${esc(c.avatar)}')` : ""}">${c.avatar ? "" : initial(c.buyer)}${c.unread ? `<i>${c.unread > 99 ? "99+" : c.unread}</i>` : ""}</div>
        <div class="cs-it">
          <div class="row between"><b data-notr>${esc(c.buyer || Z("（未填买家）", "(ไม่มีชื่อ)"))}</b><span class="small muted">${fmtTime(c.updated_at).slice(5, 16)}</span></div>
          <div class="small muted cs-last" data-notr>${c.last ? (c.last.role === "seller" ? "↩ " : "") + esc(c.last.text.slice(0, 50)) : ""}</div>
          <div class="cs-badges"><span class="pill plat-${esc(c.platform || "manual")}">${esc(PLAT[c.platform] || c.platform || "其他")}</span>${c.shop ? `<span class="pill" data-notr>${esc(c.shop)}</span>` : ""}
            ${waiting ? `<span class="pill ${waitCls(c.wait_min)}">⏱ ${ago(c.wait_min || 0)}</span>` : ""}
            ${c.needs_human ? `<span class="pill bad-pill">${Z("需人工", "ต้องใช้คน")}</span>` : ""}
            ${c.mode === "human" ? `<span class="pill tag-pill">👤 <span data-notr>${esc(c.taken_by || "")}</span></span>` : `<span class="pill" title="${esc(Z(m[0], m[1]))}">${m[2]}</span>`}
            ${c.has_draft && waiting ? `<span class="pill ok-pill">${Z("草稿", "ร่าง")}</span>` : ""}
            ${c.lead_stage ? `<span class="pill tag-pill">💼 ${esc(stageTxt(c.lead_stage))}</span>` : ""}
            ${(c.tag_list || []).slice(0, 2).map((t) => `<span class="pill" data-notr>${esc(t)}</span>`).join("")}</div></div></div>`;
    }).join("") || `<p class="muted small" style="padding:12px">${Z("没有会话。Lazada 接了接口的店铺会自动收进来；其它平台用浏览器扩展，或者点「＋」粘贴。", "ยังไม่มีแชท")}</p>`;
    if (quiet && CUR) {
      const cur = d.convs.find((c) => c.id === CUR);
      if (cur && CONV && cur.updated_at > CONV.updated_at + 0.5) openConv(CUR, true);
    }
  }
  function emptyMain() {
    return `<div class="cs-empty"><h3>${Z("客服聊天", "แชทลูกค้า")}</h3><p class="muted">${Z("左边选一个会话。", "เลือกแชททางซ้าย")}</p>
      <ul class="small muted"><li>${Z("Lazada 接了接口的店铺：买家消息自动收进来，在这里直接回复，不用开卖家中心", "ร้าน Lazada ที่เชื่อม API: ข้อความเข้ามาเองและตอบได้จากที่นี่")}</li>
      <li>${Z("AI 按店铺设置：只出草稿（点发送）/ 自动回复能答的；需要人工的会标红置顶", "AI ตามการตั้งค่าร้าน: ร่างให้ / ตอบอัตโนมัติ")}</li>
      <li>${Z("「接管」后 AI 不会自动回复，别的客服也不会同时回", "「รับช่วง」แล้ว AI จะไม่ตอบเอง")}</li>
      <li>${Z("Shopee 等没接口的店铺：用浏览器扩展，消息也会进这个列表", "ร้านที่ไม่มี API ใช้ส่วนขยายเบราว์เซอร์")}</li>
      <li>${Z("快捷键：Enter 发送，Shift+Enter 换行，Alt+↑/↓ 切换会话", "Enter ส่ง, Shift+Enter ขึ้นบรรทัด")}</li></ul></div>`;
  }

  // ---------------- 一个会话 ----------------
  async function openConv(cid, keep) {
    const same = CUR === cid;
    CUR = cid;
    $$("#cs-items .cs-item").forEach((x) => x.classList.toggle("on", +x.dataset.cid === cid));
    const draftText = same && $("#cs-reply") ? $("#cs-reply").value : null;
    CONV = await api(`/api/cs/convs/${cid}`);
    render(keep && same ? draftText : null);
    if (CONV.unread) api(`/api/cs/convs/${cid}/read`, { json: {} }).catch(() => {});
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
  function cardHtml(m) {
    const x = m.extra || {};
    if (m.kind === "image") return `<a href="${esc(x.local_url || x.url)}" target="_blank"><img class="cs-img" src="${esc(x.local_url || x.url)}" loading="lazy"></a>`;
    if (m.kind === "item") return `<div class="cs-card">${x.image ? `<img src="${esc(x.image)}">` : ""}<div><b data-notr>${esc(x.name || "")}</b>${x.price ? `<div class="small">฿${esc(x.price)}</div>` : ""}<div class="small muted">🛍 ${Z("商品", "สินค้า")}</div></div></div>`;
    if (m.kind === "order") return `<div class="cs-card"><div>📦 <b class="mono" data-notr>${esc(x.order_no || "")}</b>${x.status ? `<div class="small">${esc(x.status)}</div>` : ""}</div></div>`;
    return `<div data-notr>${esc(m.text).replace(/\n/g, "<br>")}</div>`;
  }
  function msgHtml(m) {
    if (m.role === "note") return `<div class="cs-sys" data-mid="${m.id}"><span data-notr>${esc(m.text)}</span> · ${fmtTime(m.created_at).slice(5, 16)}</div>`;
    const who = m.role === "seller" ? (m.source === "auto" ? "🤖 AI" : String(m.username || "").replace(/^api:/, "")) : "";
    return `<div class="cs-msg r-${m.role} ${m.status === "failed" ? "failed" : ""}" data-mid="${m.id}">
      <div class="cs-bubble">${cardHtml(m)}${m.text_zh ? `<div class="cs-zh" data-notr>${esc(m.text_zh)}</div>` : ""}</div>
      <div class="cs-meta small muted">${fmtTime(m.created_at).slice(5, 16)}${who ? ` · <span data-notr>${esc(who)}</span>` : ""}${m.role === "seller" && m.ai_draft && m.source !== "auto" ? (m.ai_draft.trim() === (m.text || "").trim() ? ` · ${Z("用了 AI 稿", "ใช้ร่าง AI")}` : ` · ${Z("改过 AI 稿", "แก้ร่าง AI")}`) : ""}
        ${m.source === "screenshot" ? " · 截图" : m.source === "extension" ? " · 扩展" : ""}
        ${m.status === "failed" ? ` · <span class="bad">${Z("没发出去", "ส่งไม่สำเร็จ")}</span> <button class="linkbtn" data-cs="resend" data-id="${m.id}">${Z("重发", "ส่งใหม่")}</button>` : ""}
        ${CAN("cs.delete") ? '<button class="linkbtn" data-cs="del-msg" title="删除">✕</button>' : ""}</div></div>`;
  }
  function headHtml(c) {
    const ch = CH[c.channel] || CH.manual, m = MODE[c.ai_mode] || MODE.draft;
    const taken = c.mode === "human";
    const editable = c.channel !== "lazada_im";
    return `<div class="cs-head">
      <div class="cs-av big" style="${c.avatar ? `background-image:url('${esc(c.avatar)}')` : ""}">${c.avatar ? "" : initial(c.buyer)}</div>
      <div class="cs-hmain">
        <div class="row gap wrap">${editable ? `<input id="cs-buyer" value="${esc(c.buyer || "")}" placeholder="${Z("买家名字", "ชื่อลูกค้า")}" data-notr style="width:150px">
            <select id="cs-plat">${Object.entries(PLAT).map(([k, v]) => `<option value="${k}" ${k === (c.platform || "manual") ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
            <input id="cs-shop" value="${esc(c.shop || "")}" placeholder="${Z("店铺", "ร้าน")}" data-notr style="width:110px" list="cs-shop-list"><datalist id="cs-shop-list">${(SHOPS || []).map((x) => `<option value="${esc(x)}">`).join("")}</datalist>`
          : `<b class="cs-name" data-notr>${esc(c.buyer || "")}</b><span class="pill plat-${esc(c.platform)}">${esc(PLAT[c.platform] || c.platform)}</span><span class="pill" data-notr>${esc(c.shop || "")}</span>`}</div>
        <div class="small muted">${esc(Z(ch[0], ch[1]))} · ${taken ? `👤 ${Z("接管中", "รับช่วงโดย")} <b data-notr>${esc(c.taken_by || "")}</b>` : `${m[2]} ${esc(Z(m[0], m[1]))}`}
          ${c.intent ? ` · <span class="pill tag-pill">${esc((c.analysis || {}).intent_zh || c.intent)}</span>` : ""}</div></div>
      <div class="row gap wrap cs-hbtn">
        ${taken ? `<button class="mini" data-cs="release">🤖 ${Z("交回 AI", "คืนให้ AI")}</button>` : `<button class="mini primary" data-cs="takeover">👤 ${Z("接管", "รับช่วง")}</button>`}
        <select id="cs-assign" title="${Z("分配给", "มอบหมายให้")}"><option value="">${Z("分配给…", "มอบหมาย…")}</option>${AGENTS.map((a) => `<option value="${esc(a.agent)}" ${c.assigned === a.agent ? "selected" : ""} data-notr>${esc(a.name)}</option>`).join("")}</select>
        ${c.status === "closed" ? `<button class="mini" data-cs="reopen">${Z("重新打开", "เปิดใหม่")}</button>` : `<button class="mini" data-cs="close">✓ ${Z("结束", "ปิด")}</button>`}
        ${CAN("cs.delete") ? `<button class="mini danger" data-cs="del-conv">${Z("删除", "ลบ")}</button>` : ""}</div></div>`;
  }
  function draftHtml(c) {
    const a = c.analysis || {};
    const waiting = (c.messages || []).filter((m) => m.role === "buyer" || m.role === "seller").slice(-1)[0];
    if (!c.draft) {
      return waiting && waiting.role === "buyer" ? `<div class="cs-draftbar muted small">🤖 ${c.ai_mode === "off" ? Z("这个店铺设置为只人工回复", "ร้านนี้ตั้งให้คนตอบเอง") : Z("AI 草稿还没好", "AI ยังร่างไม่เสร็จ")}
        <button class="mini" data-cs="ai-now">${Z("让 AI 写", "ให้ AI ร่าง")}</button></div>` : "";
    }
    return `<div class="cs-draftbar">
      <div class="row between"><b class="small">🤖 ${Z("AI 草稿", "ร่างจาก AI")}${a.tier ? ` <span class="pill ${TIER_CLS[a.tier] || ""}">${esc(Z(...(TIER_TXT[a.tier] || ["", ""])))}</span>` : ""}${a.confidence != null ? ` <span class="muted">${Z("把握", "มั่นใจ")} ${Math.round(a.confidence * 100)}%</span>` : ""}</b>
        <span class="row gap"><button class="mini primary" data-cs="use-draft">${Z("用这个", "ใช้อันนี้")}</button>${c.can_send ? `<button class="mini" data-cs="send-draft">${Z("直接发送", "ส่งเลย")}</button>` : ""}
          <button class="mini" data-cs="ai-now">${Z("重新写", "ร่างใหม่")}</button><button class="mini" data-cs="discard">${Z("丢弃", "ทิ้ง")}</button></span></div>
      <div class="cs-dtext" data-notr>${esc(c.draft)}</div>${c.draft_zh ? `<div class="small cs-zh" data-notr>${esc(c.draft_zh)}</div>` : ""}
      ${(c.suggestions || []).length ? `<div class="cs-sugg">${c.suggestions.map((s, i) => `<button class="mini" data-cs="sugg" data-i="${i}" ${s.need_order ? "disabled" : ""} title="${esc(s.text || "")}">${esc(s.label)}${s.need_order ? Z("（先关联订单）", "") : ""}</button>`).join(" ")}</div>` : ""}</div>`;
  }
  function composerHtml(c) {
    return `<div class="cs-comp">
      <div class="cs-tools row gap wrap">
        <button class="mini" data-cs="quick">⚡ ${Z("快捷回复", "ข้อความด่วน")}</button>
        <button class="mini" data-cs="pick-item">🛍 ${Z("商品", "สินค้า")}</button>
        <button class="mini" data-cs="pick-order">📦 ${Z("订单", "คำสั่งซื้อ")}</button>
        <label class="mini filebtn">🖼 ${Z("图片", "รูป")}<input type="file" id="cs-img" accept="image/*" hidden></label>
        <button class="mini ${ls("cs_zh") === "1" ? "on" : ""}" data-cs="zh-toggle">🀄 ${Z("中文输入", "พิมพ์จีน")}</button>
        <input id="cs-instr" placeholder="${Z("给 AI 的要求（可空），例如：告诉他明天发货", "คำสั่งให้ AI (ไม่ใส่ก็ได้)")}" style="flex:1;min-width:160px">
        <button class="mini" data-cs="draft">🤖 ${Z("AI 写回复", "AI เขียน")}</button></div>
      ${ls("cs_zh") === "1" ? `<div class="cs-zhin"><textarea id="cs-zhin" rows="1" data-notr placeholder="${Z("用中文写，自动翻成泰语填到下面", "พิมพ์จีน แปลไทยให้อัตโนมัติ")}"></textarea><span class="small muted" id="cs-tr-st"></span></div>` : ""}
      <div class="cs-send"><textarea id="cs-reply" rows="3" data-notr placeholder="${c.can_send ? Z("输入回复，Enter 发送，Shift+Enter 换行", "พิมพ์ข้อความ Enter ส่ง") : Z("回复（复制后到平台 / 扩展里发送）", "ข้อความตอบ (คัดลอกไปส่งในแพลตฟอร์ม)")}"></textarea>
        <div class="cs-sendbtns">${c.can_send ? `<button class="primary" data-cs="send">${Z("发送", "ส่ง")}</button>`
          : `<button class="primary" data-cs="copy-sent">📋 ${Z("复制并记录", "คัดลอก+บันทึก")}</button><button class="mini" data-cs="sent">✓ ${Z("只记录", "บันทึกอย่างเดียว")}</button>`}
          <button class="mini" data-cs="tr">${Z("译成中文", "แปลจีน")}</button></div></div>
      <div class="small cs-zh" id="cs-reply-zh" data-notr></div></div>`;
  }
  function pasteHtml(c) {
    if (c.channel === "lazada_im") return "";
    return `<details class="cs-add"><summary class="small">＋ ${Z("粘贴买家消息 / 聊天截图（没有接口的平台）", "วางข้อความลูกค้า / ภาพหน้าจอ")}</summary>
      <textarea id="cs-text" rows="2" placeholder="${Z("粘贴买家的消息，也可以 Ctrl+V 粘贴截图", "วางข้อความ")}" data-notr></textarea>
      <div class="row gap wrap"><select id="cs-role"><option value="buyer">${Z("买家说的", "ลูกค้า")}</option><option value="seller">${Z("我们回复的", "เรา")}</option><option value="note">${Z("内部备注", "โน้ตภายใน")}</option></select>
        <button class="mini" data-cs="add">${Z("添加", "เพิ่ม")}</button><label class="filebtn mini">📷 ${Z("上传截图", "อัปโหลดภาพ")}<input type="file" id="cs-shot" accept="image/*" hidden></label></div></details>`;
  }
  function sideHtml(c) {
    const a = c.analysis || {};
    return `${orderBox(c)}${infoBox(c)}${custBox(c)}
      ${a.quote && a.quote.lines && a.quote.lines.length ? quoteHtml(a.quote) : ""}
      <div class="cs-sideact small">${c.messages.some((m) => m.role === "seller") ? `<button class="linkbtn" data-cs="kb">${Z("把这次的问答存为常见问答", "บันทึกเป็นคำถามที่พบบ่อย")}</button> · ` : ""}
        <button class="linkbtn" data-cs="qa">${Z("让 AI 给这次服务打分", "ให้ AI ให้คะแนน")}</button></div>`;
  }
  function render(keepText) {
    const c = CONV;
    $("#cs-main").innerHTML = `${headHtml(c)}
      ${c.needs_human ? `<div class="alert-box">⚠ ${Z("需要人工处理", "ต้องให้คนจัดการ")}：<span data-notr>${esc(reasonOf(c))}</span> <button class="mini" data-cs="human-done">${Z("已处理", "จัดการแล้ว")}</button></div>` : ""}
      ${sumOf(c) ? `<div class="small cs-summary" data-notr>📝 ${esc(sumOf(c))}</div>` : ""}
      <div class="cs-msgs">${c.messages.map(msgHtml).join("") || `<p class="muted small">${Z("还没有消息", "ยังไม่มีข้อความ")}</p>`}</div>
      ${pasteHtml(c)}${draftHtml(c)}${composerHtml(c)}`;
    $("#cs-side").innerHTML = sideHtml(c);
    if (keepText) $("#cs-reply").value = keepText;
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

  // ---------------- 发送 ----------------
  async function doSend(body, btn) {
    const go = async (force) => {
      try { CONV = await api(`/api/cs/convs/${CUR}/send`, { json: Object.assign({}, body, force ? { force: true } : {}) }); return true; }
      catch (e) {
        if (/正在处理/.test(e.message) && !force && confirm(`${e.message}。${Z("还是要发送吗？", "ยังจะส่งไหม?")}`)) return go(true);
        throw e;
      }
    };
    const okSent = btn ? await busy(btn, () => go(false)) : await go(false);
    if (okSent) { render(); loadList(true); }
    return okSent;
  }
  // ---------------- 弹出：快捷回复 / 商品 / 订单 ----------------
  async function quickPop() {
    const d = await api(`/api/cs/quick?shop=${encodeURIComponent(CONV.shop || "")}`);
    const el = MODAL.open(`<div class="row between"><h3>⚡ ${Z("快捷回复", "ข้อความด่วน")}</h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      <input id="qk-q" placeholder="${Z("搜索", "ค้นหา")}" style="width:100%">
      <div class="cs-quick">${d.items.map((x) => `<div class="cs-qi" data-q="${x.id}" data-s="${esc((x.title + " " + x.text).toLowerCase())}"><b>${esc(x.title)}</b>${x.cat ? ` <span class="pill">${esc(x.cat)}</span>` : ""}${x.shop ? ` <span class="pill" data-notr>${esc(x.shop)}</span>` : ""}<div class="small" data-notr>${esc(x.text)}</div></div>`).join("")}</div>
      <p class="small muted">${Z("变量", "ตัวแปร")}：${d.vars.map((v) => `{${esc(v)}}`).join(" ")} · ${Z("在「知识库与话术」页管理快捷回复", "จัดการได้ที่หน้าคลังความรู้")}</p>`);
    $("#qk-q", el).focus();
    $("#qk-q", el).oninput = () => { const q = $("#qk-q", el).value.toLowerCase(); $$(".cs-qi", el).forEach((x) => (x.style.display = x.dataset.s.includes(q) ? "" : "none")); };
    el.onclick = async (e) => {
      const it = e.target.closest(".cs-qi"); if (!it) return;
      const r = await api(`/api/cs/convs/${CUR}/quick/${it.dataset.q}`);
      MODAL.close();
      const ta = $("#cs-reply"); ta.value = (ta.value ? ta.value + " " : "") + r.text; ta.focus();
    };
  }
  async function itemPop() {
    const el = MODAL.open(`<div class="row between"><h3>🛍 ${Z("发商品给买家", "ส่งสินค้า")}</h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      <input id="ip-q" placeholder="${Z("搜索产品编号 / 名字", "ค้นหาสินค้า")}" style="width:100%"><div id="ip-list" class="cs-picks"></div>`);
    const load = async () => {
      const d = await api(`/api/cs/products?q=${encodeURIComponent($("#ip-q", el).value.trim())}`);
      $("#ip-list", el).innerHTML = d.items.map((p) => `<div class="cs-pick" data-pid="${esc(p.id)}">${p.image ? `<img src="${esc(p.image)}">` : "<span class='noimg'></span>"}
        <div><b data-notr>${esc(p.name)}</b><div class="small muted">${esc(p.id)} ${p.price ? "· ฿" + p.price : ""} ${p.lazada_item_id ? "" : `· <span class="warn">${Z("没推到 Lazada（只能发文字）", "ยังไม่ได้ลง Lazada")}</span>`}</div></div></div>`).join("") || `<p class="muted small">${Z("没找到", "ไม่พบ")}</p>`;
    };
    let t = null; $("#ip-q", el).oninput = () => { clearTimeout(t); t = setTimeout(load, 300); };
    load();
    el.onclick = async (e) => {
      const it = e.target.closest(".cs-pick"); if (!it) return;
      MODAL.close();
      if (CONV.can_send) await doSend({ kind: "item", product_id: it.dataset.pid });
      else { const p = (await api(`/api/cs/products?q=${encodeURIComponent(it.dataset.pid)}`)).items[0]; $("#cs-reply").value += (p ? p.name : it.dataset.pid); }
    };
  }
  async function orderPop() {
    const d = await api(`/api/cs/convs/${CUR}/orders`);
    const el = MODAL.open(`<div class="row between"><h3>📦 ${Z("发订单给买家", "ส่งคำสั่งซื้อ")}</h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      <div class="cs-picks">${d.items.map((o) => `<div class="cs-pick" data-oid="${o.id}"><div><b class="mono" data-notr>${esc(o.order_no)}</b> <span class="small">${esc(o.status_zh || "")}</span>
        <div class="small muted" data-notr>${(o.items || []).map((i) => `${esc(i.sku || "")} ×${i.qty}`).join("，")}${o.tracking_no ? ` · ${esc(o.tracking_no)}` : ""}</div></div></div>`).join("") || `<p class="muted small">${Z("这个买家没有订单", "ลูกค้าคนนี้ไม่มีคำสั่งซื้อ")}</p>`}</div>`);
    el.onclick = async (e) => {
      const it = e.target.closest(".cs-pick"); if (!it) return;
      MODAL.close();
      if (CONV.can_send) await doSend({ kind: "order", order_id: +it.dataset.oid });
      else $("#cs-reply").value += it.querySelector("b").textContent;
    };
  }
  async function sendImage(f) {
    if (!f || !CUR) return;
    const fd = new FormData(); fd.append("image", f);
    toast(Z("发送图片…", "กำลังส่งรูป…"), false, 20000);
    try { CONV = await api(`/api/cs/convs/${CUR}/image`, { method: "POST", body: fd }); render(); loadList(true); toast(Z("已发送", "ส่งแล้ว")); }
    catch (e) { toast(e.message, true); }
  }

  // ---------------- 事件 ----------------
  document.addEventListener("click", async (e) => {
    const tab = e.target.closest("#cs-tabs [data-st]");
    if (tab) { ST = tab.dataset.st; loadList().catch((err) => toast(err.message, true)); return; }
    const it = e.target.closest("#cs-items .cs-item");
    if (it) { openConv(+it.dataset.cid).catch((err) => toast(err.message, true)); return; }
    if (e.target.id === "cs-new") { newDialog(); return; }
    if (e.target.id === "cs-sync") {
      const r = await busy(e.target, () => api("/api/cs/poll", { json: {} }));
      if (r) { const errs = Object.entries(r.shops || {}).filter(([, v]) => typeof v === "string"); toast(errs.length ? errs.map(([k, v]) => `${k}: ${v}`).join("\n") : Z("已拉取最新消息", "ดึงข้อความล่าสุดแล้ว"), !!errs.length, errs.length ? 10000 : 2500); loadList(true); }
      return;
    }
    if (e.target.id === "cs-sound") {
      const on = ls("cs_sound") === "0";
      ls("cs_sound", on ? "1" : "0"); e.target.textContent = on ? "🔔" : "🔕";
      if (on && window.Notification && Notification.permission === "default") Notification.requestPermission().then((p) => ls("cs_notify", p === "granted" ? "1" : "0"));
      else if (on) ls("cs_notify", "1");
      if (on) beep();
      return;
    }
    const b = e.target.closest("#cs-main [data-cs], #cs-side [data-cs], #tab-cskb [data-kb], #tab-settings [data-kb]");
    if (!b) return;
    const act = b.dataset.cs;
    try {
      if (b.dataset.kb) return kbClick(b);
      if (act === "send") {
        const t = $("#cs-reply").value.trim(); if (!t) return;
        await doSend({ text: t }, b); return;
      }
      if (act === "send-draft") { await doSend({ text: CONV.draft }, b); return; }
      if (act === "use-draft") { $("#cs-reply").value = CONV.draft; $("#cs-reply-zh").textContent = CONV.draft_zh ? Z("中文意思：", "ความหมาย: ") + CONV.draft_zh : ""; $("#cs-reply").focus(); return; }
      if (act === "discard") { CONV = await api(`/api/cs/convs/${CUR}/discard`, { json: {} }); render($("#cs-reply").value); return; }
      if (act === "ai-now") { await busy(b, () => api(`/api/cs/convs/${CUR}/draft`, { json: { instruction: ($("#cs-instr") || {}).value || "" } }).then((c) => { CONV = c; render($("#cs-reply").value); })); return; }
      if (act === "takeover" || act === "release") { CONV = await api(`/api/cs/convs/${CUR}/${act}`, { json: {} }); render($("#cs-reply").value); loadList(true); return; }
      if (act === "resend") { await busy(b, async () => { CONV = await api(`/api/cs/messages/${b.dataset.id}/resend`, { json: {} }); render(); }); return; }
      if (act === "quick") return quickPop();
      if (act === "pick-item") return itemPop();
      if (act === "pick-order") return orderPop();
      if (act === "zh-toggle") { ls("cs_zh", ls("cs_zh") === "1" ? "0" : "1"); render($("#cs-reply").value); return; }
      if (act === "copy-sent") {
        const t = $("#cs-reply").value.trim(); if (!t) return;
        try { await navigator.clipboard.writeText(t); } catch { $("#cs-reply").select(); document.execCommand("copy"); }
        CONV = await api(`/api/cs/convs/${CUR}/sent`, { json: { text: t } }); render(); loadList(true);
        toast(Z("已复制并记录，到平台聊天里粘贴发送", "คัดลอกแล้ว ไปวางส่งในแพลตฟอร์ม"));
        return;
      }
      if (act === "qa") {
        const r = await busy(b, () => api(`/api/cs/convs/${CUR}/qa`, { json: {} }));
        if (r) toast(`${Z("评分", "คะแนน")} ${r.score}/5 · ${Z("准确", "แม่นยำ")} ${r.accuracy} · ${Z("态度", "ท่าที")} ${r.attitude} · ${Z("速度", "ความเร็ว")} ${r.speed}\n${r.comment}`, false, 12000);
        return;
      }
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
      if (e.target.id === "cs-shopf") loadList();
      if (e.target.id === "cs-assign" && CUR) { CONV = await api(`/api/cs/convs/${CUR}/assign`, { json: { agent: e.target.value } }); render($("#cs-reply").value); loadList(true); }
      if (e.target.id === "cs-img") { const f = e.target.files[0]; e.target.value = ""; if (CONV && CONV.can_send) await sendImage(f); else toast(Z("这个会话不是接口渠道，图片请在平台里发", "แชทนี้ส่งรูปจากแพลตฟอร์มเอง"), true); }
      if (e.target.dataset && e.target.dataset.csLead && CUR) {
        const body = { type: "lead" };
        if (e.target.dataset.csLead === "stage") body.stage = e.target.value;
        else if (e.target.value !== "") body.stage = CONV.lead_stage, body.days = e.target.value;
        else return;
        CONV = await api(`/api/cs/convs/${CUR}/action`, { json: body }); render($("#cs-reply").value); loadList(true);
      }
      if (e.target.id === "cs-shot") { const f = e.target.files[0]; e.target.value = ""; await upShot(f); }
      if (e.target.id === "cs-buyer" || e.target.id === "cs-plat" || e.target.id === "cs-shop") {
        CONV = await api(`/api/cs/convs/${CUR}`, { json: { buyer: $("#cs-buyer").value.trim(), platform: $("#cs-plat").value, shop: $("#cs-shop").value.trim() } });
        render($("#cs-reply").value); loadList(true);
      }
      if (e.target.id === "cs-ctags" && CONV && CONV.customer) {
        await api(`/api/cs/customers/${CONV.customer.id}`, { json: { tags: e.target.value.trim() } });
        toast(Z("标签已保存", "บันทึกแท็กแล้ว"));
      }
    } catch (err) { toast(err.message, true); }
  });
  document.addEventListener("paste", (e) => {
    if (!e.target.closest || !e.target.closest("#cs-main")) return;
    const f = [...(e.clipboardData || {}).files || []].find((x) => x.type.startsWith("image/"));
    if (!f) return;
    e.preventDefault();
    // 接口会话：粘贴图片 = 发给买家；其它会话：当聊天截图让 AI 读
    if (CONV && CONV.can_send && e.target.id === "cs-reply") { if (confirm(Z("把这张图片发给买家？", "ส่งรูปนี้ให้ลูกค้า?"))) sendImage(f); }
    else upShot(f).catch((err) => toast(err.message, true));
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.id === "cs-reply" && e.key === "Enter" && !e.shiftKey && !e.isComposing && CONV) {
      e.preventDefault();
      const btn = $(CONV.can_send ? '#cs-main [data-cs="send"]' : '#cs-main [data-cs="copy-sent"]');
      if (btn) btn.click();
    }
    if (e.altKey && (e.key === "ArrowDown" || e.key === "ArrowUp") && $("#tab-cs") && !$("#tab-cs").classList.contains("hidden")) {
      const items = $$("#cs-items .cs-item"); if (!items.length) return;
      const i = items.findIndex((x) => +x.dataset.cid === CUR);
      const n = items[Math.max(0, Math.min(items.length - 1, i + (e.key === "ArrowDown" ? 1 : -1)))];
      if (n) { e.preventDefault(); openConv(+n.dataset.cid); n.scrollIntoView({ block: "nearest" }); }
    }
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
  async function loadKb() {
    KB = await api("/api/cs/kb");
    const s = KB.settings, own = isOwner();
    const setBox = $("#cskb-settings");    // 设置 → 客服 里的卡片（v2.30：不在设置页时只画知识库）
    if (setBox) {
    setBox.innerHTML = `${SET_FIELDS.map(([k, l, rows]) => `<label>${esc(l)}${rows > 1 ? `<textarea data-set="${k}" rows="${rows}" ${own ? "" : "readonly"} data-notr>${esc(s[k] || "")}</textarea>` : `<input data-set="${k}" value="${esc(s[k] || "")}" ${own ? "" : "readonly"} data-notr>`}</label>`).join("")}
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
      <h4>${Z("接口聊天、人工接管、夜间、主动提醒、质检", "แชทผ่าน API รับช่วง กลางคืน แจ้งลูกค้าเชิงรุก ตรวจคุณภาพ")}</h4>
      <div class="small muted">${Z("每个店铺的 AI 模式（只人工 / 出草稿 / 自动回复）在「客服工作台」的店铺表里切换。", "โหมด AI ของแต่ละร้านตั้งในหน้าภาพรวมแชท")}</div>
      <div class="form3"><label>${Z("多久拉一次新消息（秒）", "ดึงข้อความทุกกี่วินาที")}<input data-set="poll_sec" value="${esc(s.poll_sec || "15")}" ${own ? "" : "readonly"}></label>
        <label>${Z("接管后多少分钟没回复自动交回 AI（0 = 不交回）", "รับช่วงแล้วไม่ตอบกี่นาทีคืนให้ AI")}<input data-set="takeover_min" value="${esc(s.takeover_min || "30")}" ${own ? "" : "readonly"}></label>
        <label>${Z("每天 AI 抽查几个会话打分（0 = 不抽）", "สุ่มตรวจวันละกี่แชท")}<input data-set="qa_daily" value="${esc(s.qa_daily || "5")}" ${own ? "" : "readonly"}></label>
        <label>${Z("夜间模式", "โหมดกลางคืน")}<select data-set="night_mode" ${own ? "" : "disabled"}>${[["off", Z("关（照常）", "ปิด")], ["notice", Z("自动回一句「明早回复」", "ตอบว่าจะตอบพรุ่งนี้")], ["auto", Z("AI 能答的直接答（出草稿的店铺也自动）", "AI ตอบเองที่ตอบได้")]].map(([v, l]) => `<option value="${v}" ${s.night_mode === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label>${Z("夜间开始", "เริ่ม")}<input data-set="night_from" value="${esc(s.night_from || "22:00")}" ${own ? "" : "readonly"}></label>
        <label>${Z("夜间结束", "สิ้นสุด")}<input data-set="night_to" value="${esc(s.night_to || "08:00")}" ${own ? "" : "readonly"}></label></div>
      <label>${Z("夜间自动回复的话", "ข้อความตอบกลางคืน")}<input data-set="night_text" value="${esc(s.night_text || "")}" ${own ? "" : "readonly"} data-notr></label>
      <div class="row gap wrap small"><label class="row"><input type="checkbox" data-set="notify_shipped" data-bool ${s.notify_shipped === "1" ? "checked" : ""} ${own ? "" : "disabled"}> ${Z("订单发货后主动告诉买家运单号", "แจ้งเลขพัสดุเมื่อจัดส่ง")}</label>
        <label class="row"><input type="checkbox" data-set="notify_delayed" data-bool ${s.notify_delayed === "1" ? "checked" : ""} ${own ? "" : "disabled"}> ${Z("超过 48 小时没发货主动安抚买家", "แจ้งลูกค้าเมื่อเกิน 48 ชม.ยังไม่ส่ง")}</label></div>
      <div class="small muted">${Z("主动消息按店铺的 AI 模式：自动回复的店铺直接发；其它写成草稿等客服点发送。只发给有聊天记录的买家，每个订单只发一次。变量：{买家名} {订单号} {运单号} {预计发货日}", "ข้อความเชิงรุกส่งตามโหมด AI ของร้าน")}</div>
      <label>${Z("发货通知", "ข้อความแจ้งจัดส่ง")}<input data-set="tpl_shipped" value="${esc(s.tpl_shipped || "")}" ${own ? "" : "readonly"} data-notr></label>
      <label>${Z("延迟安抚", "ข้อความขออภัยล่าช้า")}<input data-set="tpl_delayed" value="${esc(s.tpl_delayed || "")}" ${own ? "" : "readonly"} data-notr></label>
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
    }
    loadPerf();
    renderLearn();
    loadWeekly(false);
    $("#cskb-presets").innerHTML = KB.presets_missing ? `<button data-kb="presets">＋ 补充标准话术（${KB.presets_missing} 条）</button>` : '<span class="small muted">标准话术已全部加入</span>';
    $("#cskb-list").innerHTML = KB.kb.map((k) => `<tr><td data-notr>${esc(k.q)}</td><td data-notr>${esc(k.a)}${k.a_zh ? `<div class="small muted">${esc(k.a_zh)}</div>` : ""}</td>
      <td class="small">${esc(k.tags || "")}</td><td class="small" data-notr>${esc(k.shop || Z("通用", "ทุกร้าน"))}</td><td>${k.uses || 0}</td><td>${k.active ? "✅" : "停用"}</td>
      <td class="nowrap"><button class="mini" data-kb="edit" data-id="${k.id}">编辑</button> <button class="mini danger" data-kb="del" data-id="${k.id}">删除</button></td></tr>`).join("")
      || '<tr><td colspan="7" class="muted small">还没有。在会话里点「存为常见问答」，或者点上面的「添加」。</td></tr>';
    $("#cskb-ex").innerHTML = KB.examples.slice(0, 100).map((x) => `<tr><td class="small" data-notr>${esc(x.question.slice(0, 200))}</td>
      <td class="small" data-notr>${x.ai_reply && x.ai_reply !== x.final_reply ? `<div class="muted"><s>${esc(x.ai_reply.slice(0, 200))}</s></div>` : ""}${esc(x.final_reply.slice(0, 300))}</td>
      <td class="small">${fmtTime(x.created_at).slice(0, 10)} ${esc(x.username || "")}</td>
      <td>${own ? `<button class="mini danger" data-kb="del-ex" data-id="${x.id}">删除</button>` : ""}</td></tr>`).join("")
      || '<tr><td colspan="4" class="muted small">每次点「已发送」都会记下来，AI 下次遇到类似问题会参考。</td></tr>';
    loadQuick();
  }
  // v2.46 快捷回复
  let QUICK = [];
  async function loadQuick() {
    const box = $("#cskb-quick"); if (!box) return;
    QUICK = (await api("/api/cs/quick")).items;
    box.innerHTML = QUICK.map((x) => `<tr><td>${esc(x.title)}</td><td class="small" data-notr>${esc(x.text)}</td><td class="small">${esc(x.cat || "")}</td>
      <td class="small" data-notr>${esc(x.shop || Z("通用", "ทุกร้าน"))}</td><td>${x.uses || 0}</td>
      <td class="nowrap"><button class="mini" data-kb="q-edit" data-id="${x.id}">${Z("编辑", "แก้")}</button> <button class="mini danger" data-kb="q-del" data-id="${x.id}">${Z("删除", "ลบ")}</button></td></tr>`).join("")
      || `<tr><td colspan="6" class="muted small">${Z("还没有", "ยังไม่มี")}</td></tr>`;
  }
  function quickEdit(x) {
    x = x || { title: "", text: "", cat: "", shop: "" };
    const el = MODAL.open(`<div class="row between"><h3>${x.id ? Z("编辑", "แก้ไข") : Z("添加", "เพิ่ม")}${Z("快捷回复", "ข้อความด่วน")}</h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      <div class="form2"><label>${Z("标题（自己看）", "หัวข้อ")}<input id="qe-t" value="${esc(x.title)}"></label><label>${Z("分类", "หมวด")}<input id="qe-c" value="${esc(x.cat || "")}" placeholder="${Z("常用 / 物流 / 售后", "")}"></label></div>
      <label>${Z("内容（发给买家的，一般用泰语）", "ข้อความ (ภาษาไทย)")}<textarea id="qe-x" rows="4" data-notr>${esc(x.text)}</textarea></label>
      <div class="small muted">${Z("点一下插入变量：", "แทรกตัวแปร: ")}${["买家名", "订单号", "运单号", "预计发货日", "店铺名"].map((v) => `<button class="linkbtn" data-var="${v}">{${v}}</button>`).join(" ")}</div>
      <label>${Z("只给这个店铺用（空 = 所有店铺）", "เฉพาะร้าน (ว่าง = ทุกร้าน)")}<input id="qe-s" value="${esc(x.shop || "")}" data-notr list="qe-shops"><datalist id="qe-shops">${(SHOPS || []).map((s) => `<option value="${esc(s)}">`).join("")}</datalist></label>
      <button class="primary" id="qe-ok">${Z("保存", "บันทึก")}</button>`);
    el.addEventListener("click", (e) => { const v = e.target.dataset && e.target.dataset.var; if (v) { const ta = $("#qe-x", el); ta.setRangeText(`{${v}}`, ta.selectionStart, ta.selectionEnd, "end"); ta.focus(); } });
    $("#qe-ok", el).onclick = () => busy($("#qe-ok", el), async () => {
      await api("/api/cs/quick", { json: { id: x.id, title: $("#qe-t", el).value, text: $("#qe-x", el).value, cat: $("#qe-c", el).value, shop: $("#qe-s", el).value.trim(), sort: x.sort || 0 } });
      MODAL.close(); loadQuick(); toast(Z("已保存", "บันทึกแล้ว"));
    });
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
      <label>${Z("只给这个店铺用（空 = 所有店铺通用）", "เฉพาะร้าน (ว่าง = ทุกร้าน)")}<input id="kb-shop" value="${esc(k.shop || "")}" data-notr></label>
      <label class="row"><input type="checkbox" id="kb-active" ${k.active ? "checked" : ""}> 启用</label>
      <div class="row gap"><button class="primary" id="kb-ok">保存</button><button id="kb-tr">把中文意思翻成泰语回答</button></div>`);
    $("#kb-tr", el).onclick = () => busy($("#kb-tr", el), async () => { const r = await api("/api/cs/translate", { json: { text: $("#kb-azh", el).value, to: "th" } }); $("#kb-a", el).value = r.text; });
    $("#kb-ok", el).onclick = () => busy($("#kb-ok", el), async () => {
      if (pending) await api(`/api/cs/kb/${k.id}/review`, { json: { ok: true, q: $("#kb-q", el).value, a: $("#kb-a", el).value, a_zh: $("#kb-azh", el).value, tags: $("#kb-tags", el).value } });
      else await api("/api/cs/kb", { json: { id: k.id, q: $("#kb-q", el).value, a: $("#kb-a", el).value, a_zh: $("#kb-azh", el).value, tags: $("#kb-tags", el).value, shop: $("#kb-shop", el).value.trim(), active: $("#kb-active", el).checked } });
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
    if (a === "presets") { const r = await busy(b, () => api("/api/cs/kb/presets", { json: {} })); toast(`已加入 ${r ? r.added : 0} 条标准话术`); loadKb(); }
    if (a === "q-add") return quickEdit();
    if (a === "q-edit") return quickEdit(QUICK.find((x) => x.id === id));
    if (a === "q-del") { if (!confirm(Z("删除这条快捷回复？", "ลบข้อความด่วนนี้?"))) return; await api(`/api/cs/quick/${id}`, { method: "DELETE" }); loadQuick(); return; }
    if (a === "add") kbEdit();
    if (a === "edit") kbEdit(KB.kb.find((k) => k.id === id));
    if (a === "del") { if (!confirm("删除这条问答？")) return; await api(`/api/cs/kb/${id}`, { method: "DELETE" }); loadKb(); }
    if (a === "del-ex") { if (!confirm("删除这条示例回复？")) return; await api(`/api/cs/examples/${id}`, { method: "DELETE" }); loadKb(); }
  }

  window.CS = { show, openConv, reload: () => loadList(true).catch(() => {}) };
})();
