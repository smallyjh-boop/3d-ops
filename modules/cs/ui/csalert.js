"use strict";
// 客服提醒（v2.24）：ERP 任何页面都能看到「有客户在问」——顶部「客服」显示数字、弹出提示、响一声、标签页标题闪、桌面通知；
// 客服工作台上方显示每个店铺浏览器里还没读的消息（浏览器扩展每 15 秒报一次）。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  let SEEN = null, STOP = false, BASE_TITLE = document.title, FLASH = null, LAST = null;
  try { SEEN = new Set(JSON.parse(sessionStorage.getItem("cs_seen") || "[]")); } catch { SEEN = new Set(); }
  const keep = () => { try { sessionStorage.setItem("cs_seen", JSON.stringify([...SEEN].slice(-200))); } catch { /* 忽略 */ } };

  function beep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      [0, 0.18].forEach((t) => { const o = ctx.createOscillator(), g = ctx.createGain(); o.frequency.value = 880; g.gain.value = 0.07; o.connect(g); g.connect(ctx.destination); o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + 0.12); });
    } catch { /* 浏览器不让放声音 */ }
  }
  function flash(n) {
    clearInterval(FLASH);
    if (!n) { document.title = BASE_TITLE; return; }
    let on = false;
    FLASH = setInterval(() => { on = !on; document.title = on ? `(🔔${n}) ${Z("有客户在问", "มีลูกค้าถาม")}` : BASE_TITLE; }, 1200);
  }
  function badge(n, title) {
    const b = document.querySelector('.mod[data-mod="cs"]');
    if (!b) return;
    let s = b.querySelector(".cs-badge");
    if (!s) { s = document.createElement("span"); s.className = "cs-badge"; b.appendChild(s); }
    s.textContent = n > 99 ? "99+" : String(n);
    s.classList.toggle("hidden", !n);
    b.title = title || "";
  }
  function desktop(title, body) {
    try {
      if ("Notification" in window && Notification.permission === "granted") {
        const n = new Notification(title, { body, tag: "cs-alert" });
        n.onclick = () => { window.focus(); goTab("cs"); n.close(); };
      }
    } catch { /* 忽略 */ }
  }
  function presence(d) {
    const box = document.querySelector("#cs-presence");
    if (!box) return;
    const tabs = d.tabs || [];
    // v2.49：没有浏览器扩展开着店铺页（店铺都走接口）时不显示这一行
    box.classList.toggle("hidden", !tabs.length);
    if (!tabs.length) { box.innerHTML = ""; return; }
    box.innerHTML = tabs.length
      ? `<span class="small muted">${Z("浏览器里的店铺", "ร้านที่เปิดในเบราว์เซอร์")}：</span>` + tabs.map((t) => `<span class="pill ${t.unread ? "warn-pill" : ""}" title="${esc((t.buyers || []).join("、"))}">
          <span data-notr>${esc(t.shop || t.host || "?")}</span> · ${esc(t.platform || "")} ${t.unread ? `🔔 ${t.unread}` : "✓"}${t.auto ? "" : ` · ${Z("自动关", "ปิดอัตโนมัติ")}`}</span>`).join(" ")
      : `<span class="small muted">${Z("还没有店铺页面开着 AI 客服扩展（打开卖家中心聊天页，扩展会自动跟踪）", "ยังไม่มีหน้าร้านที่เปิดส่วนขยาย AI")}</span>`;
  }
  async function tick() {
    if (STOP || typeof ME === "undefined" || !ME || !["owner", "listing"].includes(ME.role)) return;
    let d;
    try { d = await api("/api/cs/alerts"); } catch (e) { if (e.status === 403 || e.status === 401) STOP = true; return; }
    LAST = d;
    const st = d.stats || {};
    const n = (st.open || 0) + (d.unread_in_browser || 0);
    badge(n, Z(`待回复 ${st.open || 0} · 需人工 ${st.human || 0} · 超时 ${st.overdue || 0} · 浏览器里未读 ${d.unread_in_browser || 0}`, `รอตอบ ${st.open || 0}`));
    flash(document.hidden ? n : 0);
    presence(d);
    const fresh = (d.latest || []).filter((x) => !SEEN.has(`${x.id}:${x.at}`));
    if (SEEN.size === 0 && !sessionStorage.getItem("cs_seen")) { fresh.forEach((x) => SEEN.add(`${x.id}:${x.at}`)); keep(); return; }   // 刚打开页面：不把旧消息当新的
    if (fresh.length) {
      fresh.forEach((x) => SEEN.add(`${x.id}:${x.at}`)); keep();
      const x = fresh[0];
      const who = `${x.buyer || Z("买家", "ลูกค้า")}${x.shop ? " · " + x.shop : ""}${x.platform ? " · " + x.platform : ""}`;
      beep();
      desktop(Z("有客户在问", "มีลูกค้าถาม") + " · " + who, x.text);
      const host = document.querySelector("#toast");
      if (host) {
        toast(`🔔 ${Z("新客户消息", "ข้อความใหม่จากลูกค้า")}（${who}）：${x.text}${fresh.length > 1 ? Z(` 等 ${fresh.length} 条`, ` และอีก ${fresh.length - 1}`) : ""}`, false, 9000);
      }
      if (!document.querySelector("#tab-cs").classList.contains("hidden") && window.CS && window.CS.reload) window.CS.reload();
    }
  }
  // 第一次点进客服页时问一次要不要桌面提醒
  document.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest('[data-mod="cs"]');
    if (b && "Notification" in window && Notification.permission === "default") { try { Notification.requestPermission(); } catch { /* 忽略 */ } }
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { flash(0); tick(); } });
  setTimeout(tick, 3000);
  setInterval(tick, 15000);
  window.CSALERT = { tick, last: () => LAST };
})();
