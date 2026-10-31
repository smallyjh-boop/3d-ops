// 在卖家中心页面里：① 每个框架都能「读聊天记录 / 往输入框填回复」；② 顶层页面显示 AI 客服面板。
// 不依赖平台的具体网页结构：按「可滚动的区域里左右两边的气泡」找聊天记录，左边 = 买家，右边 = 我们。
(() => {
  if (window.__lhCsLoaded) return;
  window.__lhCsLoaded = true;

  // ---------------- 读聊天（每个框架） ----------------
  const SKIP = /^(\d{1,2}:\d{2}(:\d{2})?( ?[AP]M)?|\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}( \d{1,2}:\d{2})?|read|unread|已读|未读|อ่านแล้ว|ยังไม่อ่าน|today|yesterday|วันนี้|เมื่อวาน|今天|昨天|sent|delivered|ส่งแล้ว)$/i;

  // 平台的系统提示（不是买家说的话）
  const SYS = /^(unknown message type|please check it on (the )?app|\[?(system notice|order confirmation|ระบบ|系统通知)\]?|ข้อความประเภทนี้|ไม่รองรับข้อความ|此消息类型|该消息类型)/i;
  // 聊天区标题里常见的通用词（不是买家名字）
  // 聊天页上的按钮 / 标签（不是买家名字）。v2.47.1 加了「My Last Order」这一类（Lazada 聊天右侧的订单面板）
  const GENERIC = /^\s*(messages?|chats?|inbox|im|แชท|ข้อความ|消息|聊天|会话|客服|customer service|ลูกค้า|buyer|chat with buyers?|(my )?last orders?|my orders?|orders?|recent orders?|products?|recommend(ed|ations)?|vouchers?|coupons?|quick ?replies|คำสั่งซื้อ(ล่าสุด|ของฉัน)?|สินค้า(แนะนำ)?|โค้ดส่วนลด|订单|最近订单|商品|推荐|优惠券)\s*$/i;
  function visible(r) { return r.width > 2 && r.height > 2; }
  function ownText(el) {
    let t = "";
    for (const n of el.childNodes) if (n.nodeType === 3) t += n.nodeValue;
    return t.replace(/\s+/g, " ").trim();
  }
  function holders(root) {
    const out = [];
    const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    let el = w.currentNode;
    while (el) {
      if (!/^(SCRIPT|STYLE|SVG|BUTTON|INPUT|TEXTAREA|SELECT)$/i.test(el.tagName) && ownText(el)) {
        const r = el.getBoundingClientRect();
        if (visible(r)) out.push({ el, r, t: (el.innerText || ownText(el)).replace(/[ \t]+/g, " ").trim() });
      }
      el = w.nextNode();
    }
    // 去掉被包含的（父元素已经算了的子元素文字）
    return out.filter((h) => !out.some((o) => o !== h && o.el.contains(h.el) && o.t.includes(h.t)));
  }
  function findChat() {
    let best = null;
    for (const el of document.querySelectorAll("div,ul,ol,section,main,article")) {
      const cs = getComputedStyle(el);
      if (!/(auto|scroll)/.test(cs.overflowY)) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 240 || r.height < 140 || !visible(r)) continue;
      const hs = holders(el).filter((h) => h.r.bottom > r.top && h.r.top < r.bottom);
      if (hs.length < 2) continue;
      let L = 0, R = 0;
      for (const h of hs) { const lg = h.r.left - r.left, rg = r.right - h.r.right; if (rg < lg) R++; else L++; }
      const score = hs.length + Math.min(L, R) * 4 + (R > 0 ? 5 : 0) + r.height / 150;
      if (Math.min(L, R) === 0 && hs.length < 4) continue;
      if (!best || score > best.score) best = { el, r, hs, score };
    }
    return best;
  }
  function readChat() {
    const c = findChat();
    if (!c) return null;
    const { r } = c;
    const items = [];
    for (const h of c.hs) {
      const t = h.t;
      if (!t || SKIP.test(t) || SYS.test(t) || t.length > 2000) continue;
      const lg = h.r.left - r.left, rg = r.right - h.r.right;
      const center = Math.abs((h.r.left + h.r.right) / 2 - (r.left + r.right) / 2) < r.width * 0.08 && h.r.width < r.width * 0.5;
      if (center && t.length < 40) continue;        // 中间的日期 / 系统提示
      const side = rg < lg ? "seller" : "buyer";
      const prev = items[items.length - 1];
      if (prev && prev.from === side && h.r.top - prev.bottom < 5 && h.r.top >= prev.top) {
        prev.text += "\n" + t; prev.bottom = Math.max(prev.bottom, h.r.bottom);
      } else items.push({ from: side, text: t, top: h.r.top, bottom: h.r.bottom });
    }
    return { score: c.score, messages: items.map(({ from, text }) => ({ from, text })), buyer: guessBuyer(c), hasInput: !!findInput(c) };
  }
  function guessBuyer(c) {
    // ① 聊天区上方的标题（字号最大、文字短）
    let best = null;
    for (const el of document.querySelectorAll("div,span,h1,h2,h3,h4,p,a")) {
      const t = ownText(el);
      if (!t || t.length > 40 || SKIP.test(t) || GENERIC.test(t)) continue;
      const rr = el.getBoundingClientRect();
      if (!visible(rr) || rr.bottom > c.r.top + 4 || rr.top < c.r.top - 120 || rr.left < c.r.left - 10 || rr.right > c.r.right + 40) continue;
      const fs = parseFloat(getComputedStyle(el).fontSize) || 12;
      const fw = parseInt(getComputedStyle(el).fontWeight, 10) || 400;
      const s = fs + (fw >= 600 ? 3 : 0) - (c.r.top - rr.bottom) / 40;
      if (!best || s > best.s) best = { t, s };
    }
    if (best) return best.t;
    // ② 左边会话列表里选中的那一项
    const act = [...document.querySelectorAll("[class*=active],[class*=selected],[class*=current],[aria-selected=true]")]
      .find((el) => { const rr = el.getBoundingClientRect(); return visible(rr) && rr.right <= c.r.left + 5 && (el.innerText || "").trim(); });
    const nm = act ? act.innerText.trim().split("\n")[0].slice(0, 40) : "";
    return GENERIC.test(nm) ? "" : nm;
  }
  function findInput(c) {
    const cands = [...document.querySelectorAll("textarea,[contenteditable=true],[contenteditable=''],input[type=text]")]
      .filter((el) => { const rr = el.getBoundingClientRect(); return visible(rr) && rr.width > 150 && (!c || rr.top >= c.r.top); });
    cands.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
    return cands[0] || null;
  }
  function insertReply(text) {
    const el = (document.activeElement && (document.activeElement.isContentEditable || /TEXTAREA|INPUT/.test(document.activeElement.tagName)) &&
      document.activeElement.getBoundingClientRect().width > 150) ? document.activeElement : findInput(findChat());
    if (!el) return false;
    el.focus();
    try { document.execCommand("selectAll", false, null); document.execCommand("insertText", false, text); } catch { /* 下面兜底 */ }
    const val = el.isContentEditable ? el.innerText : el.value;
    if (!val || !val.includes(text.slice(0, 10))) {
      if (el.isContentEditable) el.innerText = text;
      else {
        const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        Object.getOwnPropertyDescriptor(proto, "value").set.call(el, text);
      }
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
    return true;
  }
  // 聊天内容变了（买家发新消息）→ 告诉面板
  let watchEl = null, obs = null, lastSig = "";
  function watch() {
    const c = findChat();
    if (!c || c.el === watchEl) return;
    if (obs) obs.disconnect();
    watchEl = c.el;
    let t = null;
    obs = new MutationObserver(() => {
      clearTimeout(t);
      t = setTimeout(() => {
        const d = readChat();
        if (!d || !d.messages.length) return;
        const last = d.messages[d.messages.length - 1];
        const sig = last.from + ":" + last.text;
        if (sig !== lastSig) { lastSig = sig; try { chrome.runtime.sendMessage({ type: "chat-changed", last }, () => void chrome.runtime.lastError); } catch { /* 插件重新加载过，旧页面 */ } }
      }, 1200);
    });
    obs.observe(watchEl, { childList: true, subtree: true, characterData: true });
  }
  setInterval(watch, 4000);

  // ---------------- 自动发送 / 巡查未读（每个框架） ----------------
  function clsOf(el) { const c = el.className; return (c && typeof c === "object" ? c.baseVal : c) || ""; }
  function findSendButton(input) {
    const ir = input.getBoundingClientRect();
    const near = [...document.querySelectorAll("button,[role=button],a,div,span,i,svg,img")].filter((el) => {
      const r = el.getBoundingClientRect();
      if (!visible(r) || r.width > 180 || r.height > 80 || el.contains(input)) return false;
      return r.left >= ir.left - 20 && r.top >= ir.top - 80 && r.top <= ir.bottom + 90 && r.left <= ir.right + 280;
    });
    const label = (el) => ((el.innerText || "") + " " + (el.getAttribute("aria-label") || "") + " " + (el.title || "")).trim();
    let b = near.find((el) => /^(send|ส่ง|发送|發送|ส่งข้อความ|kirim|gửi)$/i.test((el.innerText || "").trim()));
    if (!b) b = near.find((el) => /(^|\b)(send|ส่ง|发送)/i.test(label(el) + " " + clsOf(el) + " " + (el.getAttribute("data-testid") || "")));
    return b ? (b.closest("button,[role=button]") || b) : null;
  }
  function pressSend(input) {
    const b = findSendButton(input);
    if (b) { b.click(); return "button"; }
    input.focus();
    for (const t of ["keydown", "keypress", "keyup"]) {
      input.dispatchEvent(new KeyboardEvent(t, { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true }));
    }
    return "enter";
  }
  async function sendNow(text) {
    if (!insertReply(text)) return { ok: false, why: "no-input" };
    await new Promise((r) => setTimeout(r, 500));
    const input = findInput(findChat());
    if (!input) return { ok: false, why: "no-input" };
    const how = pressSend(input);
    await new Promise((r) => setTimeout(r, 1800));
    // 确认：输入框清空了，或者聊天里出现了这条（我们这边）
    const val = (input.isContentEditable ? input.innerText : input.value || "").trim();
    const d = readChat();
    const head = text.trim().slice(0, 12);
    const shown = d && d.messages.slice(-3).some((m) => m.from === "seller" && m.text.includes(head));
    return { ok: shown || (!val && !!d), how };
  }
  function findUnread() {
    const chat = findChat();
    const lists = [...document.querySelectorAll("div,ul")].filter((el) => {
      const cs = getComputedStyle(el);
      if (!/(auto|scroll)/.test(cs.overflowY)) return false;
      const r = el.getBoundingClientRect();
      return visible(r) && r.height > 200 && r.width > 120 && (!chat || r.right <= chat.r.left + 30);
    });
    for (const list of lists) {
      for (const el of list.querySelectorAll("span,div,i,em,b,sup")) {
        const t = ownText(el);
        const r = el.getBoundingClientRect();
        if (!visible(r) || r.width > 34 || r.height > 30) continue;
        const isNum = /^(\d{1,2}|99\+)$/.test(t);
        const bg = getComputedStyle(el).backgroundColor;
        const colored = bg && !/rgba?\(\s*(0,\s*0,\s*0,\s*0|255,\s*255,\s*255)/.test(bg) && bg !== "transparent";
        const named = /unread|badge|count|dot|red/i.test(clsOf(el));
        if ((isNum && (colored || named)) || (named && colored && !t && r.width <= 14)) {
          // 往上找到会话那一行
          let item = el;
          while (item.parentElement && item.parentElement !== list && item.getBoundingClientRect().width < list.getBoundingClientRect().width * 0.8) item = item.parentElement;
          return item;
        }
      }
    }
    return null;
  }

  // 会话列表里一共有几个未读（不点进去），以及是哪几个买家
  function countUnread() {
    const chat = findChat();
    const lists = [...document.querySelectorAll("div,ul")].filter((el) => {
      const cs = getComputedStyle(el);
      if (!/(auto|scroll)/.test(cs.overflowY)) return false;
      const r = el.getBoundingClientRect();
      return visible(r) && r.height > 200 && r.width > 120 && (!chat || r.right <= chat.r.left + 30);
    });
    let n = 0;
    const buyers = [], seen = new Set();
    for (const list of lists) {
      for (const el of list.querySelectorAll("span,div,i,em,b,sup")) {
        if (seen.has(el)) continue;
        const t = ownText(el);
        const r = el.getBoundingClientRect();
        if (!visible(r) || r.width > 34 || r.height > 30) continue;
        const bg = getComputedStyle(el).backgroundColor;
        const colored = bg && !/rgba?\(\s*(0,\s*0,\s*0,\s*0|255,\s*255,\s*255)/.test(bg) && bg !== "transparent";
        const named = /unread|badge|count|dot|red/i.test(clsOf(el));
        const m = /^(\d{1,2}|99\+)$/.exec(t);
        if ((m && (colored || named)) || (named && colored && !t && r.width <= 14)) {
          seen.add(el);
          n += m ? (t === "99+" ? 99 : +t) : 1;
          let item = el;
          while (item.parentElement && item.parentElement !== list && item.getBoundingClientRect().width < list.getBoundingClientRect().width * 0.8) item = item.parentElement;
          const nm = (item.innerText || "").trim().split("\n").find((x) => x.trim() && !/^\d{1,2}$/.test(x.trim()) && !SKIP.test(x.trim()));
          if (nm && buyers.length < 5) buyers.push(nm.trim().slice(0, 40));
        }
      }
    }
    return { n, buyers, chat: !!chat };
  }

  chrome.runtime.onMessage.addListener((msg, sender, reply) => {
    if (msg.type === "unread-q") { let d = { n: 0, buyers: [], chat: false }; try { d = countUnread(); } catch { /* 忽略 */ } chrome.runtime.sendMessage({ type: "unread-ans", req: msg.req, data: d }, () => void chrome.runtime.lastError); return; }
    if (msg.type === "collect") { let d = null; try { d = readChat(); } catch { d = null; } chrome.runtime.sendMessage({ type: "collected", req: msg.req, data: d }, () => void chrome.runtime.lastError); return; }
    if (msg.type === "insert") { reply({ ok: insertReply(msg.text) }); return; }
    if (msg.type === "sendmsg") { sendNow(msg.text).then(reply); return true; }
    if (msg.type === "patrol") {
      const it = findUnread();
      if (it) { it.scrollIntoView({ block: "center" }); it.click(); }
      reply({ clicked: !!it });
      return;
    }
    if (msg.type === "chat-changed-top" && window.top === window && PANEL) PANEL.onChange(msg.last);
  });


  if (window.top !== window) return;

  // ---------------- 面板（只在顶层页面，v2.6：默认自动运行、多店铺跟踪、提醒） ----------------
  const ZH = {
    title: "AI 客服", refresh: "🔄 刷新", shot: "📷 截屏读取", shop: "店铺", buyer: "买家", gen: "重新生成",
    fill: "填入回复框", sendnow: "直接发送", sent: "已发送", open: "在软件里打开", noconf: "请先点 ⚙ 设置软件地址和 API 密钥",
    reading: "正在读取…", thinking: "AI 正在写回复…", nochat: "没找到聊天记录：打开和买家的聊天窗口就会自动读取（也可以点「截屏读取」）。",
    filled: "已填入，请检查后按发送", nofill: "没找到回复输入框，已复制，请手动粘贴", human: "需要人工", order: "订单", msgs: "条消息",
    zh: "中文意思", done: "已完成", nodraft: "买家还没有新消息，不用回复",
    auto_on: "自动运行中", auto_off: "自动已关", auto_tip: "开着：打开聊天、切换买家、买家发新消息都会自动读取和处理；会话列表有未读也会提醒。",
    m_off: "只写草稿", m_semi: "半自动", m_auto: "全自动",
    m_help_off: "只写草稿：自动读对话、AI 写好回复放在下面，不动平台输入框。", m_help_semi: "半自动：自动写好回复并填进平台输入框，你检查后按发送。",
    m_help_auto: "全自动：简单问题（产品、价格、有货、物流、感谢）AI 有把握时自动发送；其他的填好回复并提醒你。",
    autoconfirm: "开启全自动？\n\n简单问题会由 AI 直接回复买家（只用产品资料和店铺政策，不编价格）。退款、投诉、定制、没把握的问题不会自动发，会提醒你。\n\n平台对自动回复有限制，建议先用半自动观察几天。",
    patrol: "这个店铺有未读消息、我没在操作时，自动切到那个买家处理",
    autosent: "已自动回复", needhuman: "需要你处理", ready: "回复已写好，请检查后发送", sendfail: "没能自动按发送，已填好，请手动按发送",
    took: "用时", fab_auto: "托管中", newmsg: "有客户在问",
    zin_tr: "直译", zin_ai: "按我的意思写", zhph_tr: "用中文打，自动翻成泰语（停一下就翻）", zhph_ai: "用中文告诉 AI 怎么回，例如：告诉他今天下单明天发货，可以送个小钥匙扣。按回车",
    write: "✨ 写回复", trans: "翻译中…", replyph: "发给买家的回复（泰语）", sync: "同步到平台输入框",
    ask: "AI 想先确认", answer: "回答", others: "其他店铺", unread: "未读", go: "去看",
    tier_auto: "可自动发", tier_confirm: "AI 写好·人确认", tier_human: "转人工", lead: "销售线索", old: "老顾客",
    recs: "客户档案与登记", visit: "第 {n} 次来", recph: "登记内容（备注 / 待办 / 售后…）", recadd: "登记", todo_open: "待处理",
  };
  const TH = {
    title: "AI แชท", refresh: "🔄 รีเฟรช", shot: "📷 แคปหน้าจอ", shop: "ร้าน", buyer: "ลูกค้า", gen: "สร้างใหม่",
    fill: "ใส่ในช่องตอบ", sendnow: "ส่งเลย", sent: "ส่งแล้ว", open: "เปิดในโปรแกรม", noconf: "กด ⚙ ตั้งค่าที่อยู่โปรแกรมและ API Key ก่อน",
    reading: "กำลังอ่าน…", thinking: "AI กำลังเขียนคำตอบ…", nochat: "ไม่พบแชท: เปิดหน้าแชทกับลูกค้าแล้วระบบจะอ่านเอง (หรือกด「แคปหน้าจอ」)",
    filled: "ใส่แล้ว ตรวจแล้วกดส่ง", nofill: "ไม่พบช่องพิมพ์ คัดลอกให้แล้ว วางเองได้เลย", human: "ต้องให้คนตอบ", order: "ออเดอร์", msgs: "ข้อความ",
    zh: "ความหมาย (จีน)", done: "เรียบร้อย", nodraft: "ลูกค้ายังไม่มีข้อความใหม่",
    auto_on: "ทำงานอัตโนมัติ", auto_off: "ปิดอัตโนมัติ", auto_tip: "เปิดอยู่: เปิดแชท เปลี่ยนลูกค้า หรือมีข้อความใหม่ ระบบจะอ่านและจัดการเอง มีข้อความยังไม่อ่านก็จะแจ้งเตือน",
    m_off: "เขียนร่างอย่างเดียว", m_semi: "กึ่งอัตโนมัติ", m_auto: "อัตโนมัติ",
    m_help_off: "เขียนร่าง: อ่านแชทเอง AI เขียนคำตอบไว้ด้านล่าง ไม่แตะช่องพิมพ์ของแพลตฟอร์ม", m_help_semi: "กึ่งอัตโนมัติ: เขียนคำตอบแล้วใส่ช่องพิมพ์ให้ ตรวจแล้วกดส่ง",
    m_help_auto: "อัตโนมัติ: คำถามง่ายที่ AI มั่นใจจะส่งเอง ที่เหลือใส่คำตอบไว้และแจ้งเตือน",
    autoconfirm: "เปิดโหมดอัตโนมัติ?\n\nคำถามง่ายๆ AI จะตอบลูกค้าเอง คืนเงิน ร้องเรียน สั่งทำ หรือที่ไม่มั่นใจจะไม่ส่งเองและจะแจ้งเตือน\n\nแนะนำใช้กึ่งอัตโนมัติก่อนสักสองสามวัน",
    patrol: "ร้านนี้มีข้อความยังไม่อ่าน และฉันไม่ได้ใช้งานอยู่ ให้สลับไปหาลูกค้าคนนั้นเอง",
    autosent: "ตอบอัตโนมัติแล้ว", needhuman: "ต้องให้คุณจัดการ", ready: "เขียนคำตอบแล้ว ตรวจแล้วกดส่ง", sendfail: "กดส่งอัตโนมัติไม่ได้ ใส่คำตอบไว้แล้ว กดส่งเองได้เลย",
    took: "ใช้เวลา", fab_auto: "อัตโนมัติ", newmsg: "มีลูกค้าถาม",
    zin_tr: "แปลตรง", zin_ai: "เขียนตามที่ฉันบอก", zhph_tr: "พิมพ์ภาษาจีน แปลเป็นไทยให้อัตโนมัติ", zhph_ai: "บอก AI ว่าจะตอบอย่างไร แล้วกด Enter",
    write: "✨ เขียนคำตอบ", trans: "กำลังแปล…", replyph: "ข้อความตอบลูกค้า (ภาษาไทย)", sync: "ใส่ในช่องพิมพ์ของแพลตฟอร์มด้วย",
    ask: "AI ขอถามก่อน", answer: "ตอบ", others: "ร้านอื่น", unread: "ยังไม่อ่าน", go: "ไปดู",
    tier_auto: "ส่งอัตโนมัติได้", tier_confirm: "AI เขียน·คนตรวจ", tier_human: "ส่งให้คนจัดการ", lead: "โอกาสขาย", old: "ลูกค้าเก่า",
    recs: "ประวัติลูกค้าและบันทึก", visit: "มาครั้งที่ {n}", recph: "บันทึก (โน้ต / ติดตาม / หลังการขาย…)", recadd: "บันทึก", todo_open: "รอจัดการ",
  };
  let T = ZH;
  const send = (m) => new Promise((res) => chrome.runtime.sendMessage(m, (r) => res(r || { ok: false, error: chrome.runtime.lastError && chrome.runtime.lastError.message })));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const PLATFORM = /lazada/i.test(location.hostname) ? "lazada" : /shopee/i.test(location.hostname) ? "shopee" : /tiktok/i.test(location.hostname) ? "tiktok" : "";
  const CHAT_URL = /(\/im\b|chat|message|webchat|inbox|customer-service)/i;

  const host = document.createElement("div");
  host.style.cssText = "all:initial;position:fixed;z-index:2147483646;right:16px;top:72px";
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `<style>
    *{box-sizing:border-box;font-family:system-ui,-apple-system,"Segoe UI","Noto Sans Thai","Leelawadee UI","Microsoft YaHei",sans-serif}
    .fab{position:relative;background:#0f6fde;color:#fff;border:0;border-radius:24px;padding:10px 16px;font-size:14px;font-weight:600;box-shadow:0 4px 16px #0004;cursor:pointer}
    .fab.semi{background:#d97706}.fab.auto{background:#16a34a}.fab.off{background:#64748b}.fab.alert{animation:bl 1s infinite}
    .fab .n{position:absolute;top:-6px;right:-6px;background:#dc2626;color:#fff;border-radius:10px;font-size:11px;min-width:18px;line-height:18px;padding:0 4px;text-align:center}
    @keyframes bl{50%{background:#dc2626}}
    .p{width:400px;max-height:86vh;overflow:auto;background:#fff;border:1px solid #d8dee6;border-radius:12px;box-shadow:0 10px 40px #0003;padding:12px;font-size:13px;color:#1d2330}
    .h{display:flex;align-items:center;gap:8px;margin-bottom:8px;cursor:move;user-select:none}.h b{font-size:15px;flex:1}.dot{width:8px;height:8px;border-radius:50%;background:#aaa}.dot.ok{background:#22c55e}.dot.bad{background:#ef4444}
    .ib{background:none;border:0;cursor:pointer;font-size:15px;padding:2px 4px;color:#555}
    .pw{border:0;border-radius:14px;padding:4px 10px;font-size:12px;font-weight:700;cursor:pointer;background:#dcfce7;color:#166534}.pw.off{background:#e2e8f0;color:#475569}
    .row{display:flex;gap:6px;align-items:center;margin:5px 0;flex-wrap:wrap}
    input,textarea{border:1px solid #cfd5dd;border-radius:6px;padding:6px 7px;font-size:13px;width:100%}
    .row input{flex:1;min-width:80px;width:auto}
    textarea{resize:vertical;font-size:14px;line-height:1.45}
    button.b{border:1px solid #0f6fde;background:#fff;color:#0f6fde;border-radius:6px;padding:6px 10px;font-size:13px;cursor:pointer}
    button.b.pr{background:#0f6fde;color:#fff}button.b:disabled{opacity:.5;cursor:default}button.b.sm{padding:3px 8px;font-size:12px}
    .seg{display:flex;border:1px solid #cfd5dd;border-radius:8px;overflow:hidden;width:100%}
    .seg button{flex:1;border:0;background:#fff;padding:7px 4px;font-size:13px;cursor:pointer;color:#334155}
    .seg button+button{border-left:1px solid #cfd5dd}
    .seg button.on[data-m=off]{background:#e2e8f0;font-weight:700}.seg button.on[data-m=semi]{background:#fef3c7;color:#92400e;font-weight:700}
    .seg button.on[data-m=auto]{background:#dcfce7;color:#166534;font-weight:700}
    .zseg{display:inline-flex;border:1px solid #cfd5dd;border-radius:6px;overflow:hidden}.zseg button{border:0;background:#fff;padding:3px 8px;font-size:12px;cursor:pointer}
    .zseg button.on{background:#0f6fde;color:#fff}
    .help{font-size:12px;color:#64748b;margin:3px 0}
    .st{color:#64748b;font-size:12px;margin:4px 0;min-height:16px}.err{color:#c62828}.okc{color:#15803d}
    .zh{color:#64748b;font-size:12px;margin:3px 0 6px}.sum{background:#f1f5f9;border-radius:6px;padding:5px 7px;margin:5px 0}
    .warn{background:#fef2f2;color:#b91c1c;border-radius:6px;padding:5px 7px;margin:5px 0}
    .askb{background:#fffbeb;border:1px solid #fcd34d;border-radius:6px;padding:6px 7px;margin:5px 0}
    .chip{display:inline-block;background:#eef2ff;color:#1e3a8a;border-radius:10px;padding:0 7px;font-size:12px;margin-right:4px}
    .oth{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0}.oth button{border:1px solid #fcd34d;background:#fffbeb;border-radius:10px;padding:2px 8px;font-size:12px;cursor:pointer}
    .sg button{display:block;width:100%;text-align:left;margin:3px 0}
    .tg{display:flex;align-items:center;gap:4px;font-size:12px;color:#555}.tg input{flex:none;width:auto;min-width:0}
    .log{font-size:12px;color:#475569;max-height:110px;overflow:auto;border-top:1px dashed #e2e8f0;margin-top:6px;padding-top:4px}
    .recs{border-top:1px dashed #e2e8f0;margin-top:6px;padding-top:4px}.recs summary{cursor:pointer}
    .hidden{display:none}
  </style>
  <button class="fab"><span class="t">💬 AI</span><span class="n hidden"></span></button>
  <div class="p hidden">
    <div class="h"><span class="dot"></span><b data-t="title"></b><button class="pw" data-a="power"></button><button class="ib" data-a="cfg" title="设置">⚙</button><button class="ib" data-a="min">—</button></div>
    <div class="help" data-t="auto_tip"></div>
    <div class="seg"><button data-m="off" data-t="m_off"></button><button data-m="semi" data-t="m_semi"></button><button data-m="auto" data-t="m_auto"></button></div>
    <div class="help" id="mhelp"></div>
    <label class="tg"><input type="checkbox" id="patrol"> <span data-t="patrol"></span></label>
    <div id="others"></div>
    <div class="row"><span data-t="shop"></span><input id="shop"><span data-t="buyer"></span><input id="buyer"></div>
    <div class="row"><button class="b pr sm" data-a="read" data-t="refresh"></button><button class="b sm" data-a="shot" data-t="shot"></button><span class="st" id="st" style="flex:1"></span></div>
    <div id="body"></div>
    <div class="log" id="log"></div>
  </div>`;
  document.documentElement.appendChild(host);
  const $ = (s) => root.querySelector(s);
  const keyHost = location.hostname;
  let ZH_DRAFT = "", LAST_CONV_ID = null, ZMODE = "tr", SYNC = true, ASK = "", LAST_INSTR = "";
  let CONV = null, BUSY = false, MODE = "off", AUTO_ALLOWED = true, NAUTO = 0, PENDING = false;
  let AUTO = true, TAB = "", UNREAD = 0, LAST_ACT = Date.now(), LAST_SHOT = 0, NEWN = 0;
  ["mousemove", "keydown", "mousedown", "wheel"].forEach((ev) => window.addEventListener(ev, () => { LAST_ACT = Date.now(); }, { passive: true, capture: true }));
  const idle = () => document.hidden || Date.now() - LAST_ACT > 45000;

  function applyLang() { root.querySelectorAll("[data-t]").forEach((e) => { e.textContent = T[e.dataset.t] || e.textContent; }); setMode(MODE, true); setPower(AUTO, true); }
  function status(t, cls) { $("#st").textContent = t || ""; $("#st").className = "st" + (cls === true ? " err" : cls ? " " + cls : ""); }
  function log(t) {
    const d = new Date();
    $("#log").insertAdjacentHTML("afterbegin", `<div>${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")} ${esc(t)}</div>`);
  }
  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = 880; g.gain.value = 0.08; o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.25);
    } catch { /* 浏览器不让放声音就算了 */ }
  }
  // 页面里的提醒：按钮上的数字 + 闪 + 标签页标题闪 + 响一声 + 桌面通知（点通知回到这个标签页）
  const BASE_TITLE = document.title;
  let FLASH = null;
  function titleFlash(on) {
    clearInterval(FLASH);
    if (!on) { if (document.title.startsWith("(🔔")) document.title = BASE_TITLE; return; }
    let x = false;
    FLASH = setInterval(() => { x = !x; document.title = x ? `(🔔${NEWN || UNREAD}) ${T.newmsg}` : BASE_TITLE; }, 1200);
  }
  function fabCount() {
    const n = Math.max(NEWN, UNREAD);
    const el = $(".fab .n");
    el.textContent = n > 99 ? "99+" : String(n);
    el.classList.toggle("hidden", !n);
  }
  function notifyNew(who, text, human) {
    NEWN++; fabCount();
    $(".fab").classList.add("alert");
    beep();
    if (document.hidden) titleFlash(true);
    send({ type: "notify", title: (human ? T.needhuman : T.newmsg) + (who ? " · " + who : "") + ($("#shop").value ? " · " + $("#shop").value : ""), message: text || "" });
  }
  function clearNew() { NEWN = 0; fabCount(); $(".fab").classList.remove("alert"); titleFlash(false); }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) titleFlash(false); });

  function setMode(m, quiet) {
    MODE = m;
    root.querySelectorAll(".seg button").forEach((b) => b.classList.toggle("on", b.dataset.m === m));
    $("#mhelp").textContent = T["m_help_" + m] || "";
    fabLabel();
    if (!quiet) chrome.storage.local.get({ modes: {} }, (d) => { d.modes[keyHost] = m; chrome.storage.local.set({ modes: d.modes }); });
  }
  function fabLabel() {
    const f = $(".fab");
    f.classList.toggle("semi", AUTO && MODE === "semi"); f.classList.toggle("auto", AUTO && MODE === "auto"); f.classList.toggle("off", !AUTO);
    $(".fab .t").textContent = !AUTO ? "💬 AI ⏸" : MODE === "auto" ? `🤖 AI · ${T.fab_auto}${NAUTO ? " " + NAUTO : ""}` : "💬 AI ▶";
  }
  function setPower(on, quiet) {
    AUTO = !!on;
    const b = $(".pw");
    b.textContent = "⏻ " + (AUTO ? T.auto_on : T.auto_off);
    b.classList.toggle("off", !AUTO);
    fabLabel();
    if (!quiet) {
      try { sessionStorage.setItem("lh_auto", AUTO ? "1" : "0"); } catch { /* 忽略 */ }
      chrome.storage.local.set({ autorun: AUTO });
      if (AUTO) handleNew();
      report();
    }
  }
  chrome.storage.local.get({ shops: {}, modes: {}, patrol: true, open: false, autorun: true, zmode: "tr", sync: true }, (d) => {
    let ss = null, sa = null;
    try { ss = sessionStorage.getItem("lh_shop"); sa = sessionStorage.getItem("lh_auto"); } catch { /* 忽略 */ }
    $("#shop").value = ss != null ? ss : d.shops[keyHost] || "";
    $("#patrol").checked = !!d.patrol;
    ZMODE = d.zmode === "ai" ? "ai" : "tr"; SYNC = d.sync !== false;
    setMode(d.modes[keyHost] || "off", true);
    setPower(sa != null ? sa === "1" : d.autorun !== false, true);
    if (d.open) toggle(true);
  });
  send({ type: "whoami" }).then((r) => { TAB = r && r.ok ? String(r.data.tab) : String(Math.random()).slice(2); });
  send({ type: "cfg" }).then((r) => {
    if (r.ok) { T = r.data.lang === "th" ? TH : ZH; applyLang(); }
    send({ type: "api", path: "/api/v1/cs/ping" }).then((p) => {
      $(".dot").className = "dot " + (p.ok ? "ok" : "bad");
      if (!p.ok) status(p.error === "NO_CONFIG" ? T.noconf : p.error, true);
      else AUTO_ALLOWED = p.data.auto_allowed !== false;
    });
  });
  function toggle(open) {
    $(".p").classList.toggle("hidden", !open); $(".fab").classList.toggle("hidden", open);
    if (open) clearNew();
    chrome.storage.local.set({ open });
  }
  $("#shop").addEventListener("change", () => {
    const v = $("#shop").value.trim();
    try { sessionStorage.setItem("lh_shop", v); } catch { /* 忽略 */ }
    chrome.storage.local.get({ shops: {} }, (d) => { d.shops[keyHost] = v; chrome.storage.local.set({ shops: d.shops }); });
    report();
  });
  $("#patrol").addEventListener("change", () => chrome.storage.local.set({ patrol: $("#patrol").checked }));

  function render() {
    const c = CONV;
    const zf = $("#zhin"); if (zf) ZH_DRAFT = zf.value;
    const hadFocus = zf && root.activeElement === zf;
    if (c && LAST_CONV_ID !== c.id) { ZH_DRAFT = ""; ASK = ""; LAST_CONV_ID = c.id; }   // 换了买家就清空
    if (!c) { $("#body").innerHTML = ""; return; }
    const a = c.analysis || {};
    const nmsg = (c.messages || []).length;
    ASK = a.ask_seller_zh || "";
    $("#body").innerHTML = `
      <div class="st">${nmsg} ${T.msgs}${c.order ? ` · ${T.order} <b>${esc(c.order.order_no)}</b> ${esc(c.order.status_zh || "")}` : ""}${a.intent_zh ? ` · <span class="chip">${esc(a.intent_zh)}</span>` : ""}${a.confidence != null && c.draft ? ` · ${Math.round(a.confidence * 100)}%` : ""}</div>
      ${c.needs_human ? `<div class="warn">⚠ ${T.human}：${esc((T === TH && a.human_reason_th) || c.human_reason || "")}</div>` : ""}
      ${c.summary ? `<div class="sum">📝 ${esc((T === TH && a.summary_th) || c.summary)}</div>` : ""}
      ${a.tier || c.lead_stage || (c.buyer_history && c.buyer_history.repeat) || (c.tag_list || []).length ? `<div class="st">${a.tier ? `<span class="chip">${T["tier_" + a.tier] || ""}</span>` : ""}${c.lead_stage ? `<span class="chip">💼 ${T.lead}</span>` : ""}${c.buyer_history && c.buyer_history.repeat ? `<span class="chip">👤 ${T.old}</span>` : ""}${(c.tag_list || []).slice(0, 4).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>` : ""}
      <div class="row"><span class="zseg"><button data-z="tr" class="${ZMODE === "tr" ? "on" : ""}">${T.zin_tr}</button><button data-z="ai" class="${ZMODE === "ai" ? "on" : ""}">${T.zin_ai}</button></span>
        <span id="trst" class="zh"></span></div>
      <textarea id="zhin" rows="2" placeholder="${esc(ZMODE === "ai" ? T.zhph_ai : T.zhph_tr)}">${esc(ZH_DRAFT)}</textarea>
      ${ZMODE === "ai" ? `<div class="row"><button class="b pr sm" data-a="write">${T.write}</button></div>` : ""}
      ${ASK ? `<div class="askb">❓ ${T.ask}：${esc(ASK)}<div class="row"><input id="askin"><button class="b sm" data-a="answer">${T.answer}</button></div></div>` : ""}
      <textarea id="reply" rows="5" placeholder="${esc(T.replyph)}">${esc(c.draft || "")}</textarea>
      ${c.draft_zh && T !== TH ? `<div class="zh" id="replyzh">${T.zh}：${esc(c.draft_zh)}</div>` : '<div class="zh" id="replyzh"></div>'}
      <label class="tg"><input type="checkbox" id="sync" ${SYNC ? "checked" : ""}> <span>${T.sync}</span></label>
      <div class="row"><button class="b pr" data-a="sendnow">${T.sendnow}</button><button class="b" data-a="fill">${T.fill}</button><button class="b" data-a="sent">${T.sent}</button><button class="b" data-a="gen">${T.gen}</button></div>
      <div class="sg">${(c.suggestions || []).filter((s) => s.type !== "aftersales").map((s, i) => `<button class="b" data-a="sg" data-i="${i}" ${s.need_order ? "disabled" : ""}>⚡ ${esc(s.label)}</button>`).join("")}</div>
      ${recBox(c)}
      <div class="row"><button class="b sm" data-a="open">${T.open}</button></div>`;
    if (hadFocus) { const z = $("#zhin"); if (z) { z.focus(); z.selectionStart = z.selectionEnd = z.value.length; } }
  }
  // v2.7：客户档案和登记（备注 / 待办 / 售后 / 投诉 / 特殊需求），和 ERP「登记中心」是同一份
  function recBox(c) {
    const cu = c.customer, recs = (cu && cu.records) || c.records || [];
    const K = T === TH ? { note: "บันทึก", todo: "ติดตาม", aftersales: "หลังการขาย", complaint: "ร้องเรียน", request: "ความต้องการพิเศษ" } : (c.record_kinds || {});
    const open = recs.filter((r) => r.status === "open");
    return `<details class="recs" ${open.length ? "open" : ""}><summary class="help">📒 ${T.recs}${cu ? ` · ${T.visit.replace("{n}", cu.visits)}` : ""}${recs.length ? ` · ${recs.length}` : ""}${open.some((r) => r.overdue) ? " ⏰" : ""}</summary>
      ${recs.slice(0, 5).map((r) => `<div class="help">• <b>${esc(K[r.kind] || r.kind_zh)}</b> ${esc(r.text)} <span style="color:#94a3b8">${esc(r.agent || "")}${r.status === "open" && r.kind !== "note" ? " · " + T.todo_open : ""}</span></div>`).join("")}
      <div class="row"><select id="rkind" style="border:1px solid #cfd5dd;border-radius:6px;padding:5px">${Object.entries(K).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select>
        <input id="rtext" placeholder="${esc(T.recph)}"><button class="b sm" data-a="rec">${T.recadd}</button></div></details>`;
  }
  async function syncOut(text) {
    if (!SYNC || !text) return;
    await send({ type: "insert-all", text });
  }

  async function capture(mode) {
    if (BUSY) { PENDING = true; return null; }
    BUSY = true;
    const t0 = Date.now();
    status(T.reading);
    try {
      const body = { url: location.href, shop: $("#shop").value.trim(), buyer: "", platform: PLATFORM };
      let useShot = mode === "shot";
      if (!useShot) {
        const r = await send({ type: "collect-all" });
        if (r.ok && r.data && r.data.messages.length) {
          body.messages = r.data.messages;
          body.buyer = r.data.buyer || $("#buyer").value.trim();
          $("#buyer").value = body.buyer;
        } else if (mode === "auto" && !document.hidden && CHAT_URL.test(location.href) && Date.now() - LAST_SHOT > 60000) {
          useShot = true;                                   // 读不到网页里的聊天：自动截屏让 AI 看（一分钟最多一次）
        } else throw new Error(T.nochat);
      }
      if (useShot) {
        LAST_SHOT = Date.now();
        $(".p").style.visibility = "hidden"; host.style.visibility = "hidden";
        await sleep(120);
        const s = await send({ type: "shot" });
        $(".p").style.visibility = ""; host.style.visibility = "";
        if (!s.ok) throw new Error(s.error);
        body.screenshot = s.data;
        body.buyer = $("#buyer").value.trim();
      }
      status(T.thinking);
      const res = await send({ type: "api", path: "/api/v1/cs/capture", body });
      if (!res.ok) throw new Error(res.error === "NO_CONFIG" ? T.noconf : res.error);
      CONV = res.data;
      if (CONV.buyer && !$("#buyer").value) $("#buyer").value = CONV.buyer;
      status(res.data.drafted ? `${T.took} ${((Date.now() - t0) / 1000).toFixed(1)}s` : "", "okc");
      render();
      return res.data;
    } catch (e) {
      $(".p").style.visibility = ""; host.style.visibility = "";
      status(String(e.message || e), mode !== "auto");
      return null;
    } finally {
      BUSY = false;
      if (PENDING) { PENDING = false; setTimeout(() => handleNew(), 300); }
    }
  }

  // 自动：打开聊天 / 切换买家 / 买家发新消息 → 读取，按模式处理
  async function handleNew() {
    const c = await capture("auto");
    if (!c || !c.drafted || !c.draft) return;
    const who = c.buyer || $("#buyer").value || "";
    const lastBuyer = [...(c.messages || [])].reverse().find((m) => m.role === "buyer");
    notifyNew(who, lastBuyer ? lastBuyer.text : "", c.needs_human);
    if (MODE === "off") { log(`📝 ${who}：${T.ready}`); return; }
    if (MODE === "semi") {
      await send({ type: "insert-all", text: c.draft });
      status(T.ready, "okc"); log(`✍ ${who}：${T.ready}`);
      return;
    }
    if (MODE === "auto") {
      const ok = c.auto && c.auto.ok && AUTO_ALLOWED;
      if (!ok) {
        await send({ type: "insert-all", text: c.draft });
        const why = (c.auto && c.auto.reason) || "";
        status(`${T.needhuman}：${why}`, true); log(`⚠ ${who}：${why}`);
        return;
      }
      await sleep(2500 + Math.random() * 3500);       // 像真人一样稍等一下再发
      const r = await send({ type: "sendmsg-all", text: c.draft });
      if (r.ok && r.data && r.data.ok) {
        const s = await send({ type: "api", path: "/api/v1/cs/sent", body: { conv_id: c.id, text: c.draft, auto: true } });
        if (s.ok) { CONV = s.data; render(); }
        NAUTO++; fabLabel(); NEWN = Math.max(0, NEWN - 1); fabCount();
        status(T.autosent, "okc"); log(`🤖 ${who}：${c.draft.slice(0, 40)}`);
      } else {
        status(T.sendfail, true); log(`⚠ ${who}：${T.sendfail}`);
      }
    }
  }

  async function writeByIntent(instr) {
    if (!CONV || !instr) return;
    LAST_INSTR = instr;
    status(T.thinking);
    const r = await send({ type: "api", path: "/api/v1/cs/draft", body: { conv_id: CONV.id, instruction: instr } });
    if (r.ok) { CONV = r.data; render(); status(""); await syncOut(CONV.draft); } else status(r.error, true);
  }

  async function act(a, el) {
    if (a === "min") return toggle(false);
    if (a === "cfg") return send({ type: "options" });
    if (a === "power") return setPower(!AUTO);
    if (a === "read") { clearNew(); return capture("dom"); }
    if (a === "shot") return capture("shot");
    if (a === "focus") return send({ type: "focus-tab", tab: el.dataset.tab });
    if (!CONV) return;
    if (a === "fill") {
      const t = $("#reply").value;
      const r = await send({ type: "insert-all", text: t });
      if (r.ok && r.data) status(T.filled);
      else { try { await navigator.clipboard.writeText(t); } catch { /* */ } status(T.nofill, true); }
    }
    if (a === "sendnow") {
      const t = $("#reply").value;
      const r = await send({ type: "sendmsg-all", text: t });
      if (r.ok && r.data && r.data.ok) {
        const s = await send({ type: "api", path: "/api/v1/cs/sent", body: { conv_id: CONV.id, text: t } });
        if (s.ok) { CONV = s.data; ZH_DRAFT = ""; render(); }
        clearNew();
        status(T.done, "okc");
      } else status(T.sendfail, true);
    }
    if (a === "sent") {
      const r = await send({ type: "api", path: "/api/v1/cs/sent", body: { conv_id: CONV.id, text: $("#reply").value } });
      if (r.ok) { CONV = r.data; ZH_DRAFT = ""; render(); status(T.done); clearNew(); } else status(r.error, true);
    }
    if (a === "gen") {
      const instr = ZMODE === "ai" ? ($("#zhin").value || "").trim() : "";
      status(T.thinking);
      const r = await send({ type: "api", path: "/api/v1/cs/draft", body: { conv_id: CONV.id, instruction: instr } });
      if (r.ok) { CONV = r.data; render(); status(""); await syncOut(CONV.draft); } else status(r.error, true);
    }
    if (a === "rec") {
      const tx = ($("#rtext").value || "").trim(); if (!tx) return;
      const r = await send({ type: "api", path: "/api/v1/cs/records", body: { conv_id: CONV.id, kind: $("#rkind").value, text: tx } });
      if (!r.ok) return status(r.error, true);
      const c2 = await send({ type: "api", path: `/api/v1/cs/conv/${CONV.id}` });
      if (c2.ok) { CONV = c2.data; render(); const d = $(".recs"); if (d) d.open = true; }
      status(T.done, "okc");
      return;
    }
    if (a === "write") return writeByIntent(($("#zhin").value || "").trim());
    if (a === "answer") {
      const ans = ($("#askin").value || "").trim();
      if (ans) return writeByIntent(`${LAST_INSTR || ($("#zhin").value || "").trim()}\n补充（回答你的问题「${ASK}」）：${ans}`);
    }
    if (a === "sg") {
      const s = CONV.suggestions[+el.dataset.i];
      const r = await send({ type: "api", path: "/api/v1/cs/action", body: Object.assign({ conv_id: CONV.id }, s) });
      if (r.ok) { CONV = r.data; render(); status(r.data.message || T.done); } else status(r.error, true);
    }
    if (a === "open") send({ type: "open", path: "/#cs" });
  }
  root.querySelector(".seg").addEventListener("click", (e) => {
    const b = e.target.closest("[data-m]");
    if (!b) return;
    if (b.dataset.m === "auto" && MODE !== "auto" && !window.confirm(T.autoconfirm)) return;
    setMode(b.dataset.m);
    if (AUTO) handleNew();
  });
  root.addEventListener("click", (e) => {
    const z = e.target.closest("[data-z]");
    if (z) { ZMODE = z.dataset.z; chrome.storage.local.set({ zmode: ZMODE }); render(); return; }
    const b = e.target.closest("[data-a]"); if (b && !b.disabled) act(b.dataset.a, b);
  });
  root.addEventListener("change", (e) => {
    const el = e.composedPath ? e.composedPath()[0] : e.target;
    if (el && el.id === "sync") { SYNC = el.checked; chrome.storage.local.set({ sync: SYNC }); }
  });

  // 拖动面板（不要挡住平台的发送按钮）；位置会记住
  let drag = null, moved = false;
  function startDrag(e) {
    if (e.target.closest("button.ib") || e.target.closest("button.pw")) return;
    const r = host.getBoundingClientRect();
    drag = { dx: e.clientX - r.left, dy: e.clientY - r.top }; moved = false;
    e.preventDefault();
  }
  root.querySelector(".h").addEventListener("mousedown", startDrag);
  $(".fab").addEventListener("mousedown", startDrag);
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    moved = true;
    const x = Math.max(0, Math.min(window.innerWidth - 60, e.clientX - drag.dx));
    const y = Math.max(0, Math.min(window.innerHeight - 40, e.clientY - drag.dy));
    host.style.left = x + "px"; host.style.top = y + "px"; host.style.right = "auto";
  });
  window.addEventListener("mouseup", () => {
    if (drag && moved) chrome.storage.local.set({ pos: { left: host.style.left, top: host.style.top } });
    drag = null;
  });
  chrome.storage.local.get({ pos: null }, (d) => {
    if (d.pos) { host.style.left = d.pos.left; host.style.top = d.pos.top; host.style.right = "auto"; }
  });
  $(".fab").addEventListener("click", () => { if (!moved) toggle(true); });

  // 中文输入：直译 = 停 0.8 秒就翻成泰语；按我的意思写 = 回车让 AI 按意思写（AI 有不清楚的会先问）
  // v2.5.1：面板在 shadow DOM 里，事件结束后 e.target 会变成外层元素，所以先把输入框存下来
  let TRT = null, TRSEQ = 0;
  function liveTranslate(el) {
    clearTimeout(TRT);
    ZH_DRAFT = el.value || "";
    if (ZMODE !== "tr") return;
    TRT = setTimeout(async () => {
      const zh = (el.value || "").trim();
      if (!zh) return;
      const seq = ++TRSEQ;
      const st = $("#trst");
      if (st) st.textContent = T.trans;
      try {
        const r = await send({ type: "api", path: "/api/v1/cs/translate", body: CONV ? { text: zh, to: "th", conv_id: CONV.id } : { text: zh, to: "th" } });
        if (seq !== TRSEQ) return;
        const st2 = $("#trst"), rp = $("#reply"), rz = $("#replyzh");
        if (r && r.ok) {
          const th = (r.data && r.data.text) || "";
          if (rp) rp.value = th;
          if (rz) rz.textContent = `${T.zh}：${zh}`;
          if (st2) st2.textContent = "✓";
          await syncOut(th);
        } else if (st2) st2.textContent = (r && r.error) || "×";
      } catch (err) {
        const st2 = $("#trst"); if (st2) st2.textContent = String(err.message || err);
      }
    }, 800);
  }
  root.addEventListener("input", (e) => {
    const el = e.composedPath ? e.composedPath()[0] : e.target;
    if (el && el.id === "zhin") liveTranslate(el);
  });
  root.addEventListener("compositionend", (e) => {
    const el = e.composedPath ? e.composedPath()[0] : e.target;
    if (el && el.id === "zhin") liveTranslate(el);
  });
  root.addEventListener("keydown", (e) => {
    e.stopPropagation();                        // 输入框里打字时不要被平台的快捷键抢走
    const el = e.composedPath ? e.composedPath()[0] : e.target;
    if (el && el.id === "zhin" && ZMODE === "ai" && e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault(); writeByIntent((el.value || "").trim());
    }
    if (el && el.id === "askin" && e.key === "Enter" && !e.isComposing) { e.preventDefault(); act("answer"); }
    if (el && el.id === "rtext" && e.key === "Enter" && !e.isComposing) { e.preventDefault(); act("rec"); }
  }, true);

  // 每 15 秒：数会话列表里的未读 → 报给系统（ERP 和其他标签页能看到）；没在操作时自动切到有未读的买家
  async function report() {
    let u = { n: 0, buyers: [] };
    try { const r = await send({ type: "unread-all" }); if (r.ok && r.data) u = r.data; } catch { /* 忽略 */ }
    const before = UNREAD;
    UNREAD = u.n || 0;
    fabCount();
    if (UNREAD > before && AUTO) {
      beep();
      if (document.hidden) titleFlash(true);
      send({ type: "notify", title: `${T.newmsg} · ${$("#shop").value || PLATFORM}`, message: (u.buyers || []).join("、") });
    }
    if (!TAB) return;
    const r = await send({ type: "api", path: "/api/v1/cs/presence", body: { tab: TAB, shop: $("#shop").value.trim(), platform: PLATFORM, host: keyHost, unread: UNREAD, buyers: u.buyers || [], auto: AUTO } });
    if (r.ok && r.data) {
      const others = (r.data.tabs || []).filter((t) => !t.key.endsWith("|" + TAB) && t.unread);
      $("#others").innerHTML = others.length ? `<div class="oth"><span class="help">${T.others}：</span>${others.map((t) => `<button data-a="focus" data-tab="${esc(t.key.split("|").pop())}">${esc(t.shop || t.host)} · ${esc(t.platform)} 🔔${t.unread}</button>`).join("")}</div>` : "";
    }
    if (AUTO && UNREAD > 0 && $("#patrol").checked && !BUSY && idle()) {
      const p = await send({ type: "patrol-all" });
      if (p.ok && p.data && p.data.clicked) { await sleep(2500); handleNew(); }
    }
  }
  setTimeout(report, 4000);
  setInterval(report, 15000);
  // 打开页面后自动读一次
  setTimeout(() => { if (AUTO) handleNew(); }, 3500);

  var PANEL = {
    onChange(last) {
      if (!AUTO || !last) return;
      if (last.from === "buyer") handleNew();
      else if (last.from === "seller" && CONV && !BUSY) capture("auto");   // 我们发出去了：记下来（人改过的会学习）
      else if (!CONV) handleNew();
    },
  };
  window.__lhPanel = PANEL;
  applyLang();
})();
