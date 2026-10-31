"use strict";
// v2.49 外壳：右上角 🔔 待办抽屉（每个页面都有，原来的「今日待办」页面）、🔍 全局搜索（Ctrl+K）。
// 文字用 Z(中文, 泰文) 直接写两种语言；样式在 static/shell.css。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const tr = (s) => (window.I18N && I18N.t ? I18N.t(s) : s);
  const E = (s) => (window.UX ? UX.esc(s) : String(s == null ? "" : s));
  const own = () => typeof ME === "undefined" || !ME || ME.role === "owner";
  const q1 = (s, r = document) => r.querySelector(s);

  // 顶部「运营」大菜单按界面语言写（其它大菜单靠翻译表）
  document.querySelectorAll("#modnav .mod[data-th]").forEach((b) => { b.textContent = TH() ? b.dataset.th : b.dataset.zh; });
  const bellBtn = q1("#bell-btn"), gsBtn = q1("#gs-btn");
  if (bellBtn) bellBtn.title = Z("待办（完成 / 忽略 / 去处理）", "งานที่ต้องทำ (เสร็จ / ข้าม / ไปจัดการ)");
  if (gsBtn) gsBtn.title = Z("搜索 订单 / 快递单号 / SKU / 产品 / 买家 / 客服会话（Ctrl+K）", "ค้นหา ออเดอร์ / เลขพัสดุ / SKU / สินค้า / ผู้ซื้อ / แชท (Ctrl+K)");
  [bellBtn, gsBtn].forEach((b) => b && b.setAttribute("data-notr", ""));

  // =================== 🔔 待办 ===================
  const LV = [["bad", "紧急", "ด่วน"], ["warn", "注意", "ควรดู"], ["info", "提醒", "แจ้งให้ทราบ"]];
  let COUNT = null, DATA = null, SRC = "", SHOW_DONE = false, drawer = null, timer = null;

  async function poll() {
    if (document.hidden) return;
    try { COUNT = await api("/api/todo/count"); } catch { return; }
    const n = q1("#bell-n");
    if (!n) return;
    n.textContent = COUNT.bad || COUNT.n;
    n.classList.toggle("hidden", !COUNT.n);
    n.classList.toggle("bell-bad", !!COUNT.bad);
    bellBtn.title = Z(`待办 ${COUNT.n} 条${COUNT.bad ? `，紧急 ${COUNT.bad}` : ""}`, `งาน ${COUNT.n} รายการ${COUNT.bad ? ` ด่วน ${COUNT.bad}` : ""}`);
  }
  function startPoll() {
    poll();
    clearInterval(timer);
    timer = setInterval(poll, 60000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
  }

  function ensureDrawer() {
    if (drawer) return drawer;
    drawer = document.createElement("div");
    drawer.className = "sh-drawer hidden";
    drawer.innerHTML = `<div class="sh-mask" data-sh-close></div><aside class="sh-panel" role="dialog">
      <div class="sh-head"><h3></h3><button class="mini" data-sh-close>✕</button></div>
      <div class="sh-filter"></div><div class="sh-body"></div><div class="sh-foot"></div></aside>`;
    document.body.appendChild(drawer);
    drawer.addEventListener("click", drawerClick);
    drawer.addEventListener("change", (e) => {
      if (e.target.matches("[data-sh-done]")) { SHOW_DONE = e.target.checked; loadTodo(); }
      const c = e.target.closest("[data-al-src]");
      if (c) api("/api/oa/alerts/muted", { json: { source: c.dataset.alSrc, muted: !c.checked } }).catch((err) => toast(err.message, true));
    });
    return drawer;
  }
  async function openTodo(src) {
    ensureDrawer();
    if (src != null) SRC = src;
    drawer.classList.remove("hidden");
    document.body.classList.add("sh-open");
    q1(".sh-body", drawer).innerHTML = `<p class="muted">${Z("加载中…", "กำลังโหลด…")}</p>`;
    await loadTodo();
  }
  function closeTodo() { if (drawer) drawer.classList.add("hidden"); document.body.classList.remove("sh-open"); }

  function srcName(id) {
    const s = ((DATA && DATA.sources) || []).find((x) => x.id === id);
    return s ? Z(s.zh, s.th) : id;
  }
  function itemHtml(i) {
    const title = TH() ? (i.title_th || tr(i.title)) : i.title;
    const det = i.detail ? (TH() ? (i.detail_th || tr(i.detail)) : i.detail) : "";
    return `<div class="sh-it lv-${E(i.level)}${i.state ? " is-done" : ""}">
      <div class="sh-it-t"><b data-notr>${E(title)}</b>${det ? `<div class="small muted" data-notr>${E(det)}</div>` : ""}
        <div class="sh-it-m"><span class="sh-chip">${E(Z(i.group, ((DATA.groups || []).find((g) => g.zh === i.group) || {}).th || i.group))}</span></div></div>
      <div class="sh-it-b">${i.state ? `<span class="small muted">${i.state === "done" ? Z("已完成", "เสร็จแล้ว") : Z("已忽略", "ข้ามแล้ว")}</span>
          <button class="mini" data-todo-k="${E(i.key)}" data-todo-s="">${Z("恢复", "คืนค่า")}</button>`
        : `${i.tab ? `<button class="mini primary" data-todo-go="${E(i.tab)}">${Z("去处理", "ไปจัดการ")}</button>` : ""}
          <button class="mini" data-todo-k="${E(i.key)}" data-todo-s="done">${Z("完成", "เสร็จ")}</button>
          <button class="mini" data-todo-k="${E(i.key)}" data-todo-s="ignored">${Z("忽略", "ข้าม")}</button>`}</div></div>`;
  }
  async function loadTodo() {
    let d;
    try { d = DATA = await api("/api/todo" + (SHOW_DONE ? "?all=1" : "")); } catch (e) { q1(".sh-body", drawer).innerHTML = `<p class="bad">${E(e.message)}</p>`; return; }
    const open = d.items.filter((i) => !i.state);
    const bySrc = {};
    open.forEach((i) => { bySrc[i.source] = (bySrc[i.source] || 0) + 1; });
    if (SRC && !bySrc[SRC] && !SHOW_DONE) SRC = "";
    const bad = open.filter((i) => i.level === "bad").length;
    q1(".sh-head h3", drawer).innerHTML = `🔔 ${Z("待办", "งานที่ต้องทำ")} <span class="muted small">${open.length}${bad ? ` · <span class="bad">${Z("紧急", "ด่วน")} ${bad}</span>` : ""}</span>`;
    q1(".sh-filter", drawer).innerHTML = `<div class="chips">${[["", Z("全部", "ทั้งหมด"), open.length], ...Object.entries(bySrc).map(([k, n]) => [k, srcName(k), n])]
      .map(([k, l, n]) => `<button class="chip ${k === SRC ? "on" : ""}" data-sh-src="${E(k)}"><span data-notr>${E(l)}</span> <b>${n}</b></button>`).join("")}</div>`;
    const items = d.items.filter((i) => !SRC || i.source === SRC);
    let html = (d.errors || []).length ? `<div class="warn-box small">${d.errors.map((x) => `${E(srcName(x.source))}：${E(x.error)}`).join("<br>")}</div>` : "";
    for (const [lv, zh, th] of LV) {
      const its = items.filter((i) => !i.state && i.level === lv);
      if (its.length) html += `<div class="sh-grp sh-${lv}"><h4>${Z(zh, th)} <span class="muted">· ${its.length}</span></h4>${its.map(itemHtml).join("")}</div>`;
    }
    const done = items.filter((i) => i.state);
    if (done.length) html += `<div class="sh-grp"><h4>${Z("已完成 / 忽略", "เสร็จ / ข้ามแล้ว")} <span class="muted">· ${done.length}</span></h4>${done.map(itemHtml).join("")}</div>`;
    q1(".sh-body", drawer).innerHTML = html || (window.UX ? UX.empty(Z("没有待办 🎉", "ไม่มีงานค้าง 🎉")) : "");
    q1(".sh-foot", drawer).innerHTML = `<div class="row gap"><label class="small sh-cb"><input type="checkbox" data-sh-done ${SHOW_DONE ? "checked" : ""}> ${Z(`显示已完成 / 忽略的（${d.hidden}）`, `แสดงที่เสร็จ / ข้ามแล้ว (${d.hidden})`)}</label>
      ${window.UX ? UX.help(Z("完成 = 已经处理了；忽略 = 这件事不用管。同一件事以后有变化会重新出现。", "เสร็จ = จัดการแล้ว; ข้าม = ไม่ต้องสนใจ ถ้ามีการเปลี่ยนแปลงจะขึ้นมาใหม่")) : ""}</div>
      ${own() && window.MODKIT && MODKIT.enabled("ops") ? `<details class="sh-alerts"><summary>📱 ${Z("手机提醒（LINE / Telegram）", "แจ้งเตือนมือถือ (LINE / Telegram)")}</summary><div class="sh-al-box small muted">…</div></details>` : ""}`;
    const det = q1(".sh-alerts", drawer);
    if (det) det.addEventListener("toggle", () => { if (det.open) alertsBox(q1(".sh-al-box", drawer)); }, { once: true });
    if (COUNT) { COUNT.n = open.length; COUNT.bad = bad; }
    const n = q1("#bell-n");
    if (n) { n.textContent = bad || open.length; n.classList.toggle("hidden", !open.length); n.classList.toggle("bell-bad", !!bad); }
  }

  // 手机提醒（原来在「今日待办」页面下面；开关和 LINE 设置在「设置 → 运营分析」）
  async function alertsBox(box) {
    let a;
    try { a = await api("/api/oa/alerts"); } catch (e) { box.innerHTML = `<p class="bad">${E(e.message)}</p>`; return; }
    const ch = a.channels.length ? a.channels.map((c) => (c === "line" ? "LINE" : "Telegram")).join(" + ") : Z("没有", "ยังไม่มี");
    box.classList.remove("muted");
    box.innerHTML = `<p>${window.UX ? UX.dot(a.on ? "ok" : "warn", a.on ? Z("开着", "เปิดอยู่") : Z("关着", "ปิดอยู่")) : ""} · ${Z("推送到", "ส่งไปที่")}：<b>${E(ch)}</b>
        ${window.UX ? UX.help(Z("待办里重要的事（超时未发货、差评、亏本订单、耗材不够、接口出错……）推到手机，同一件事只推一次。开关、LINE 设置在「设置 → 运营分析」。",
          "เรื่องสำคัญในงานที่ต้องทำ (ส่งเกินเวลา รีวิวแย่ ออเดอร์ขาดทุน วัสดุไม่พอ API ผิดพลาด…) ส่งเข้ามือถือ เรื่องเดียวกันส่งครั้งเดียว เปิด/ปิดและตั้งค่า LINE ที่「ตั้งค่า → วิเคราะห์การขาย」")) : ""}</p>
      <div class="row gap wrap"><button class="mini" data-al-test>${Z("发一条测试消息", "ส่งข้อความทดสอบ")}</button>
        <button class="mini" data-al-run>${Z("现在检查并推送", "ตรวจและส่งตอนนี้")}</button>
        <button class="mini" data-al-cfg>${Z("设置", "ตั้งค่า")}</button></div>
      <div class="sh-sub">${Z("哪些来源推送", "แหล่งที่ส่งแจ้งเตือน")}</div>
      <div class="row gap wrap">${a.sources.map((s) => `<label class="sh-cb"><input type="checkbox" data-al-src="${E(s.id)}" ${a.muted.includes(s.id) ? "" : "checked"}> <span data-notr>${E(Z(s.zh, s.th))}</span></label>`).join("")}</div>
      <div class="sh-sub">${Z("最近推送", "แจ้งเตือนล่าสุด")}</div>
      ${a.recent.slice(0, 8).map((r) => `<div class="sh-rec"><span class="muted nowrap">${fmtTime(r.ts).slice(5)}</span> <span data-notr>${E(r.text)}</span>
        ${r.sent ? "" : `<span class="bad" title="${E(r.send_error || "")}">${Z("没推出去", "ยังส่งไม่ได้")}</span>`}</div>`).join("") || (window.UX ? UX.empty(Z("还没有", "ยังไม่มี")) : "")}`;
  }

  async function drawerClick(e) {
    if (e.target.closest("[data-sh-close]")) return closeTodo();
    const s = e.target.closest("[data-sh-src]");
    if (s) { SRC = s.dataset.shSrc; return loadTodo(); }
    const b = e.target.closest("[data-todo-k]");
    if (b) { await busy(b, () => api("/api/todo/state", { json: { key: b.dataset.todoK, state: b.dataset.todoS } })); loadTodo(); document.dispatchEvent(new CustomEvent("todo-changed")); return; }
    const g = e.target.closest("[data-todo-go]");
    if (g) { closeTodo(); return goTab(g.dataset.todoGo); }
    const t = e.target.closest("[data-al-test]");
    if (t) return busy(t, async () => { await api("/api/oa/alerts/test", { json: {} }); toast(Z("测试消息发出去了", "ส่งข้อความทดสอบแล้ว")); });
    const r = e.target.closest("[data-al-run]");
    if (r) return busy(r, async () => { const x = await api("/api/oa/alerts/run", { json: {} }); toast(Z(`新记 ${x.collected} 条，推送 ${x.sent} 条`, `บันทึกใหม่ ${x.collected} ส่ง ${x.sent}`)); alertsBox(r.closest(".sh-al-box")); });
    if (e.target.closest("[data-al-cfg]")) { closeTodo(); window.CFG_MOD = "ops"; try { CFG_MOD = "ops"; } catch { /* 忽略 */ } goTab("settings"); }
  }
  if (bellBtn) bellBtn.addEventListener("click", () => (drawer && !drawer.classList.contains("hidden") ? closeTodo() : openTodo()));

  // =================== 🔍 全局搜索 ===================
  let gs = null, gsT = null, GS = [], SEL = 0, gsSeq = 0;
  const PLAT = (p) => ({ lazada: "Lazada", shopee: "Shopee", tiktok: "TikTok", manual: Z("私下成交", "ขายตรง") }[p] || p || "");
  function ensureSearch() {
    if (gs) return gs;
    gs = document.createElement("div");
    gs.className = "gs hidden";
    gs.innerHTML = `<div class="gs-mask" data-gs-close></div><div class="gs-box" role="dialog">
      <div class="gs-in"><span>🔍</span><input id="gs-q" autocomplete="off" spellcheck="false"><kbd>Esc</kbd></div>
      <div class="gs-res"></div></div>`;
    document.body.appendChild(gs);
    const inp = q1("#gs-q", gs);
    inp.placeholder = Z("订单号 / 快递单号 / SKU / 产品名 / 买家 / 客服会话", "เลขออเดอร์ / เลขพัสดุ / SKU / ชื่อสินค้า / ผู้ซื้อ / แชท");
    inp.addEventListener("input", () => { clearTimeout(gsT); gsT = setTimeout(runSearch, 220); });
    inp.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); SEL = Math.max(0, Math.min(GS.length - 1, SEL + (e.key === "ArrowDown" ? 1 : -1))); mark(); }
      if (e.key === "Enter") { e.preventDefault(); const el = q1(`[data-gs-i="${SEL}"]`, gs); if (el && GS[SEL]) el.click(); else runSearch(); }
    });
    gs.addEventListener("click", (e) => {
      if (e.target.closest("[data-gs-close]")) return closeSearch();
      const it = e.target.closest("[data-gs-i]");
      if (it) { e.preventDefault(); pick(GS[+it.dataset.gsI]); }
    });
    return gs;
  }
  function openSearch() {
    ensureSearch().classList.remove("hidden");
    const inp = q1("#gs-q", gs);
    inp.focus(); inp.select();
    if (!inp.value) q1(".gs-res", gs).innerHTML = `<p class="gs-hint">${Z("输入至少 2 个字。↑ ↓ 选择，回车打开。扫码枪扫面单 / SKU 标签也可以。", "พิมพ์อย่างน้อย 2 ตัวอักษร ↑ ↓ เลือก Enter เปิด ใช้เครื่องสแกนสแกนใบปะหน้า / ป้าย SKU ได้")}</p>`;
  }
  function closeSearch() { if (gs) gs.classList.add("hidden"); }
  function mark() {
    gs.querySelectorAll("[data-gs-i]").forEach((x) => x.classList.toggle("on", +x.dataset.gsI === SEL));
    const on = q1("[data-gs-i].on", gs);
    if (on) on.scrollIntoView({ block: "nearest" });
  }
  async function runSearch() {
    const q = q1("#gs-q", gs).value.trim();
    const box = q1(".gs-res", gs);
    if (q.length < 2) { GS = []; box.innerHTML = `<p class="gs-hint">${Z("输入至少 2 个字", "พิมพ์อย่างน้อย 2 ตัวอักษร")}</p>`; return; }
    const seq = ++gsSeq;
    let r;
    try { r = await api("/api/search?q=" + encodeURIComponent(q)); } catch (e) { box.innerHTML = `<p class="bad">${E(e.message)}</p>`; return; }
    if (seq !== gsSeq) return;
    GS = []; SEL = 0;
    if (!r.groups.length) { box.innerHTML = `<p class="gs-hint">${Z("没找到", "ไม่พบ")} “<span data-notr>${E(q)}</span>”</p>`; return; }
    box.innerHTML = r.groups.map((g) => `<div class="gs-grp"><h4>${E(Z(g.zh, g.th))} <span class="muted">${g.items.length}</span></h4>${g.items.map((it) => {
      const i = GS.push({ type: g.type, it }) - 1;
      if (g.type === "order") {
        return `<a href="#" class="gs-it" data-gs-i="${i}"><span class="gs-ic">📦</span><span class="gs-main"><b class="mono" data-notr>${E(it.order_no)}</b>
          <span class="small muted" data-notr>${E(PLAT(it.platform))}${it.shop ? " · " + E(it.shop) : ""}${it.buyer ? " · " + E(it.buyer) : ""}${it.tracking_no ? " · " + E(it.tracking_no) : ""}</span></span>
          <span class="gs-side small">${E(Z(it.status_zh, it.status_th))}<br><span class="muted">${it.order_time ? fmtTime(it.order_time).slice(0, 10) : ""}</span></span></a>`;
      }
      if (g.type === "product") {
        return `<a href="#" class="gs-it" data-gs-i="${i}" data-p360="${E(it.sku || it.id)}">${it.thumb ? `<img class="gs-th" src="${E(it.thumb)}" loading="lazy" alt="">` : '<span class="gs-ic">🧩</span>'}
          <span class="gs-main"><b data-notr>${E(it.name || it.title_th || it.id)}</b><span class="small muted mono" data-notr>${E(it.id)}${it.sku ? " · " + E(it.sku) : ""}${it.n_skus > 1 ? ` · ${it.n_skus} SKU` : ""}</span></span>
          <span class="gs-side small">${it.draft ? Z("草稿", "ฉบับร่าง") : it.active ? "" : `<span class="muted">${Z("已下架", "ปิดการขายแล้ว")}</span>`}</span></a>`;
      }
      return `<a href="#" class="gs-it" data-gs-i="${i}"><span class="gs-ic">💬</span><span class="gs-main"><b data-notr>${E(it.buyer || "#" + it.id)}</b>
        <span class="small muted" data-notr>${E(PLAT(it.platform))}${it.order_no ? " · " + E(it.order_no) : ""}${it.summary || it.summary_th ? " · " + E((TH() && it.summary_th) || it.summary) : ""}</span></span>
        <span class="gs-side small">${it.needs_human ? `<span class="warn">${Z("需人工", "ต้องตอบเอง")}</span><br>` : ""}<span class="muted">${it.updated_at ? fmtTime(it.updated_at).slice(5) : ""}</span></span></a>`;
    }).join("")}</div>`).join("");
    mark();
  }
  // 等某个模块的页面脚本加载好（第一次打开那个页面时才加载）
  async function waitFor(fn, ms = 6000) {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) { if (fn()) return true; await new Promise((r) => setTimeout(r, 120)); }
    return false;
  }
  async function pick(x) {
    if (!x) return;
    closeSearch();
    const it = x.it;
    try {
      if (x.type === "order") {
        await goTab("orders");
        if (await waitFor(() => window.OPS && OPS.openOrder)) OPS.openOrder(it.id);
      } else if (x.type === "product") {
        // 有「商品 360」抽屉就直接打开它（结果行是链接，抽屉不会自己接管链接的点击）
        if (window.P360 && P360.open) { P360.open(it.sku || it.id); return; }
        await goTab("library");
        if (await waitFor(() => typeof openProduct === "function")) await openProduct(it.id);
      } else if (x.type === "conv") {
        await goTab("cs");
        if (await waitFor(() => window.CS && CS.openConv)) await CS.openConv(+it.id);
      }
    } catch (e) { toast(e.message, true); }
  }
  if (gsBtn) gsBtn.addEventListener("click", openSearch);
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "k" || e.key === "K")) { e.preventDefault(); openSearch(); return; }
    if (e.key === "Escape") { if (gs && !gs.classList.contains("hidden")) closeSearch(); else if (drawer && !drawer.classList.contains("hidden")) closeTodo(); }
  });

  // 启动：等登录信息（ME）好了再开始问 🔔
  (async () => {
    await waitFor(() => typeof ME !== "undefined" && ME, 20000);
    startPoll();
  })();
  window.SHELL = { openTodo, closeTodo, openSearch, poll, show() { /* 换页面不用做什么 */ } };
})();
