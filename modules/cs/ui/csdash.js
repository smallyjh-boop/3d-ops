"use strict";
// v2.46 客服工作台：今天的数字、紧急会话、各店铺（AI 模式、接口状态）、各客服、线索 / 售后、AI 表现、待补知识、质检、后台任务
(function () {
  let TIMER = null;
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const isOwner = () => window.OPSH && OPSH.isOwner();
  const n = (v, u = "") => (v == null ? "-" : v + u);
  const MODES = [["off", "只人工", "คนตอบเอง"], ["draft", "AI 出草稿", "AI ร่างให้"], ["auto", "AI 自动回复", "AI ตอบเอง"]];

  function show(tab) {
    clearInterval(TIMER);
    if (tab !== "csdash") return;
    load();
    TIMER = setInterval(() => { if (!document.hidden && $("#tab-csdash") && !$("#tab-csdash").classList.contains("hidden")) load(); }, 30000);
  }
  function openConv(id) { goTab("cs"); setTimeout(() => window.CS && CS.openConv(+id), 300); }

  async function load() {
    let d;
    try { d = await api("/api/cs/dashboard"); } catch (e) { $("#csd-body").innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
    const t = d.today, p = d.perf || {};
    $("#csd-time").textContent = Z("更新于 ", "อัปเดต ") + fmtTime(d.now).slice(11, 16) + (d.night ? Z(" · 夜间模式", " · โหมดกลางคืน") : "");
    const tile = (label, v, cls = "", go = "") => `<div class="csd-tile ${cls} ${go ? "go" : ""}" ${go ? `data-go="${go}"` : ""}><span>${label}</span><b>${v}</b></div>`;
    const conv = (c) => `<div class="csd-row" data-conv="${c.id}"><span class="pill ${c.needs_human ? "bad-pill" : c.wait_min >= 15 ? "bad-pill" : "warn-pill"}">${c.needs_human ? Z("需人工", "ต้องใช้คน") : "⏱ " + n(c.wait_min) + Z("分", "น.")}</span>
      <b data-notr>${esc(c.buyer)}</b><span class="small muted" data-notr>${esc(c.shop)}</span><span class="small" data-notr style="flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis">${esc(c.reason || c.text)}</span>
      ${c.taken_by ? `<span class="pill tag-pill">👤 <span data-notr>${esc(c.taken_by)}</span></span>` : c.assigned ? `<span class="small muted">→ <span data-notr>${esc(c.assigned)}</span></span>` : ""}</div>`;
    const shopRow = (s) => `<tr><td data-notr><b>${esc(s.shop || Z("（未填店铺）", "(ไม่ระบุร้าน)"))}</b></td>
      <td>${s.api ? (s.last_error ? `<span class="bad" title="${esc(s.last_error)}">⚠ ${Z("接口出错", "API ผิดพลาด")}</span><div class="small muted" data-notr style="max-width:260px">${esc(s.last_error.slice(0, 120))}</div>`
        : s.last_ok ? `<span class="ok">● ${Z("接口正常", "API ปกติ")}</span><div class="small muted">${fmtTime(s.last_ok).slice(11, 16)}</div>` : `<span class="muted">${Z("等第一次拉取", "รอดึงครั้งแรก")}</span>`) : `<span class="muted">${Z("扩展 / 手工", "ส่วนขยาย / เอง")}</span>`}</td>
      <td>${s.unreplied ? `<b class="bad">${s.unreplied}</b>` : 0} / ${s.open}</td>
      <td><div class="csd-mode" data-shop="${esc(s.shop)}">${MODES.map(([k, zh, th]) => `<button class="${s.mode === k ? "on" : ""}" data-mode="${k}" ${isOwner() ? "" : "disabled"}>${Z(zh, th)}</button>`).join("")}</div></td>
      <td>${s.api ? `<label class="small"><input type="checkbox" data-im="${esc(s.shop)}" ${s.im ? "checked" : ""} ${isOwner() ? "" : "disabled"}> ${Z("接口收发", "รับส่งผ่าน API")}</label>` : ""}</td></tr>`;
    const jobs = d.jobs || {}, jc = jobs.counts || {};
    $("#csd-body").innerHTML = `
      <div class="csd-tiles">
        ${tile(Z("现在未回复", "ยังไม่ตอบ"), t.unreplied, t.unreplied ? "warn" : "", "unreplied")}
        ${tile(Z("等了超过 5 分钟", "รอเกิน 5 นาที"), t.wait5, t.wait5 ? "warn" : "", "unreplied")}
        ${tile(Z("等了超过 15 分钟", "รอเกิน 15 นาที"), t.wait15, t.wait15 ? "bad" : "", "unreplied")}
        ${tile(Z("需要人工", "ต้องใช้คน"), t.human_needed, t.human_needed ? "bad" : "", "human")}
        ${tile(Z("分给我的", "ของฉัน"), t.mine, "", "mine")}
        ${tile(Z("今天新会话", "แชทใหม่วันนี้"), t.new)}
        ${tile(Z("今天来问的买家", "ลูกค้าที่ทักวันนี้"), t.buyers)}
        ${tile(Z("平均首次响应", "ตอบครั้งแรกเฉลี่ย"), n(t.first_avg, Z(" 分钟", " นาที")))}
        ${tile(Z("今天 AI 自动回复", "AI ตอบเองวันนี้"), t.ai_sent)}
        ${tile(Z("今天人工回复", "คนตอบวันนี้"), t.human_sent)}
      </div>
      <div class="csd-grid">
        <div class="card"><h3>🚨 ${Z("要马上处理", "ต้องจัดการด่วน")} <span class="muted small">${Z("需人工 + 等了 15 分钟以上", "ต้องใช้คน + รอเกิน 15 นาที")}</span></h3>
          ${d.urgent.map(conv).join("") || `<p class="muted small">${Z("没有，很好 👍", "ไม่มี 👍")}</p>`}</div>
        <div class="card"><h3>👥 ${Z("客服今天", "แอดมินวันนี้")}</h3>
          <table class="grid small"><thead><tr><th>${Z("客服", "แอดมิน")}</th><th>${Z("手上的会话", "แชทที่ดูแล")}</th><th>${Z("回复条数", "ข้อความ")}</th><th>${Z("平均响应", "ตอบเฉลี่ย")}</th></tr></thead>
          <tbody>${d.agents.map((a) => `<tr><td data-notr>${esc(a.name)}</td><td>${a.open}</td><td>${a.sent}</td><td>${n(a.avg_min, Z(" 分", " น."))}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">${Z("今天还没有人回复", "วันนี้ยังไม่มีใครตอบ")}</td></tr>`}</tbody></table></div>
      </div>
      <div class="card"><div class="row between wrap"><h3>🏪 ${Z("店铺", "ร้าน")}</h3><span class="small muted">${Z("AI 模式：只人工 = AI 不管；AI 出草稿 = AI 写好人点发送（默认）；AI 自动回复 = 能答的直接发，退款 / 投诉 / 改单等照样转人工。只有老板能改。",
          "โหมด AI: คนตอบเอง / AI ร่างให้คนกดส่ง (ค่าเริ่มต้น) / AI ตอบเองเมื่อมั่นใจ")}</span></div>
        <table class="grid small"><thead><tr><th>${Z("店铺", "ร้าน")}</th><th>${Z("消息渠道", "ช่องทาง")}</th><th>${Z("未回复 / 进行中", "ยังไม่ตอบ / เปิดอยู่")}</th><th>${Z("AI 模式", "โหมด AI")}</th><th></th></tr></thead>
        <tbody>${d.shops.map(shopRow).join("") || `<tr><td colspan="5" class="muted">${Z("还没有店铺。在 设置 → 店铺与接口 接上 Lazada，或者用浏览器扩展。", "ยังไม่มีร้าน")}</td></tr>`}</tbody></table>
        ${d.shops.some((s) => s.api && /permission|权限|Permission|AppWithout/i.test(s.last_error)) ? `<p class="small warn">${Z("Lazada 说这个应用没有聊天接口的权限。① 到 open.lazada.com → App Console → 你的应用 → API Permission，确认「Instant Messaging」那一组是已开通（Approved / 已勾选），不是「申请中」；② 开通后到 系统 → 设置 → 店铺对接，把这个 Lazada 店铺重新「授权」一次（旧的授权不带新权限）；③ 回来点「⟳ 立即拉取新消息」。", "Lazada แจ้งว่าแอปยังไม่มีสิทธิ์ใช้ API แชท ① ตรวจใน App Console → API Permission ว่า Instant Messaging อนุมัติแล้ว ② ไปที่ ตั้งค่า → เชื่อมร้านค้า แล้วกด「อนุญาต」ร้าน Lazada ใหม่อีกครั้ง ③ กลับมากด「⟳ ดึงข้อความใหม่ตอนนี้」")}</p>` : ""}</div>
      <div class="csd-grid">
        <div class="card"><h3>💼 ${Z("今天要跟进的线索", "ลูกค้าที่ต้องติดตามวันนี้")}</h3>
          ${d.leads_due.map((l) => `<div class="csd-row" data-conv="${l.id}"><b data-notr>${esc(l.buyer)}</b><span class="small muted" data-notr>${esc(l.shop)}</span><span class="small" data-notr style="flex:1">${esc(l.note)}</span>${l.value ? `<span>฿${Math.round(l.value)}</span>` : ""}</div>`).join("") || `<p class="muted small">${Z("没有", "ไม่มี")}</p>`}</div>
        <div class="card"><h3>🧾 ${Z("售后 / 投诉（待处理）", "หลังการขาย / ร้องเรียน")} <span class="muted small">${Z(`登记待办 ${d.records.open} · 超期 ${d.records.overdue}`, `ค้าง ${d.records.open} · เกินกำหนด ${d.records.overdue}`)}</span></h3>
          ${d.aftersales.map((r) => `<div class="csd-row" ${r.conv_id ? `data-conv="${r.conv_id}"` : 'data-go-tab="csrec"'}><span class="pill ${r.overdue ? "bad-pill" : ""}">${esc(r.kind)}</span><b data-notr>${esc(r.buyer)}</b><span class="small" data-notr style="flex:1">${esc(r.text)}</span></div>`).join("") || `<p class="muted small">${Z("没有", "ไม่มี")}</p>`}</div>
        <div class="card"><h3>🤖 ${Z("AI 表现（近 7 天）", "ผลงาน AI (7 วัน)")}</h3>
          <div class="csd-tiles">${tile(Z("回复", "ตอบ"), n(p.sent))}${tile(Z("其中自动", "อัตโนมัติ"), n(p.auto))}${tile(Z("草稿直接采用", "ใช้ร่างตรงๆ"), n(p.adopt_pct, "%"))}${tile(Z("平均回复", "ตอบเฉลี่ย"), n(p.avg_reply_min, Z("分", "น.")))}</div>
          <h4>${Z("AI 答不上来的问题", "คำถามที่ AI ตอบไม่ได้")}</h4>
          ${d.unanswered.map((u) => `<div class="csd-row" data-go-tab="cskb"><span class="pill">${u.count}×</span><span class="small" data-notr>${esc(u.q)}</span></div>`).join("") || `<p class="muted small">${Z("没有", "ไม่มี")}</p>`}</div>
        <div class="card"><h3>✅ ${Z("质检抽查（AI 打分）", "สุ่มตรวจคุณภาพ (AI ให้คะแนน)")} <span class="muted small">${Z("平均", "เฉลี่ย")} ${n(d.qa_avg)}/5</span></h3>
          ${d.qa.map((q) => `<div class="csd-row" data-conv="${q.conv_id}"><span class="pill ${q.score < 3 ? "bad-pill" : q.score >= 4 ? "ok-pill" : "warn-pill"}">${q.score}</span><b data-notr>${esc(q.buyer || "")}</b><span class="small muted" data-notr>${esc(q.agent || "")}</span><span class="small" data-notr style="flex:1">${esc(q.comment || "")}</span></div>`).join("")
            || `<p class="muted small">${Z("每天自动抽几个昨天的会话打分（在 设置 → 客服 里设数量）；也可以在聊天页右边点「让 AI 给这次服务打分」。", "สุ่มตรวจทุกวันอัตโนมัติ")}</p>`}</div>
      </div>
      <p class="small muted">${Z("后台任务", "งานเบื้องหลัง")}：${Z("排队", "รอ")} ${jc.todo || 0} · ${Z("进行中", "กำลังทำ")} ${jc.doing || 0} · ${Z("失败", "ล้มเหลว")} ${jc.failed || 0}${jobs.external ? Z(" · 在单独的进程里运行", " · รันแยกโปรเซส") : ""}
        ${(jobs.failed || []).slice(0, 2).map((f) => ` · <span class="bad" data-notr>${esc(f.kind)}: ${esc((f.error || "").slice(0, 80))}</span>`).join("")}</p>`;
  }

  document.addEventListener("click", async (e) => {
    if (!e.target.closest("#tab-csdash")) return;
    try {
      if (e.target.id === "csd-chat") return goTab("cs");
      if (e.target.id === "csd-sync") { const r = await busy(e.target, () => api("/api/cs/poll", { json: {} })); if (r) { toast(Z("已拉取", "ดึงแล้ว")); load(); } return; }
      const mb = e.target.closest(".csd-mode [data-mode]");
      if (mb) { await api("/api/cs/shops/mode", { json: { shop: mb.closest(".csd-mode").dataset.shop, mode: mb.dataset.mode } }); toast(Z("已保存", "บันทึกแล้ว")); load(); return; }
      const row = e.target.closest("[data-conv]");
      if (row && +row.dataset.conv) return openConv(row.dataset.conv);
      const gt = e.target.closest("[data-go-tab]");
      if (gt) return goTab(gt.dataset.goTab);
      const tl = e.target.closest("[data-go]");
      if (tl) { goTab("cs"); setTimeout(() => { const b = document.querySelector(`#cs-tabs [data-st="${tl.dataset.go}"]`); if (b) b.click(); }, 400); }
    } catch (err) { toast(err.message, true); }
  });
  document.addEventListener("change", async (e) => {
    if (!e.target.dataset || e.target.dataset.im === undefined) return;
    try { await api("/api/cs/shops/mode", { json: { shop: e.target.dataset.im, im: e.target.checked } }); toast(Z("已保存", "บันทึกแล้ว")); } catch (err) { toast(err.message, true); }
  });

  window.CSDASH = { show, reload: load };
})();
