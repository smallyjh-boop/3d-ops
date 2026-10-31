"use strict";
// v2.46 客服工作台：今天的数字、紧急会话、各店铺（AI 模式、接口状态）、各客服、线索 / 售后、AI 表现、待补知识、质检、后台任务
// v2.49：用统一页面组件（static/ux.js）：数字卡片 + 7 天走势小图、服务指标进度条、负载条形图；平台通知不算在里面
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
  const sum = (a) => (a || []).reduce((x, y) => x + (+y || 0), 0);

  async function load() {
    let d;
    try { d = await api("/api/cs/dashboard"); } catch (e) { $("#csd-body").innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
    const t = d.today, p = d.perf || {}, se = d.series || {}, AM = d.alert_minutes || 10;
    $("#csd-time").textContent = Z("更新于 ", "อัปเดต ") + fmtTime(d.now).slice(11, 16) + (d.night ? Z(" · 夜间模式", " · โหมดกลางคืน") : "");
    const conv = (c) => `<div class="csd-row" data-conv="${c.id}"><span class="pill ${c.needs_human ? "bad-pill" : c.wait_min >= 15 ? "bad-pill" : "warn-pill"}">${c.needs_human ? Z("需人工", "ต้องใช้คน") : "⏱ " + n(c.wait_min) + Z("分", "น.")}</span>
      <b data-notr>${esc(c.buyer)}</b><span class="small muted" data-notr>${esc(c.shop)}</span><span class="small csd-ell" data-notr>${esc(TH() ? c.text : c.reason || c.text)}</span>
      ${c.taken_by ? `<span class="pill tag-pill">👤 <span data-notr>${esc(c.taken_by)}</span></span>` : c.assigned ? `<span class="small muted">→ <span data-notr>${esc(c.assigned)}</span></span>` : ""}</div>`;
    const shopRow = (s) => `<tr><td data-notr><b>${esc(s.shop || Z("（未填店铺）", "(ไม่ระบุร้าน)"))}</b></td>
      <td>${s.api ? (s.last_error ? `${UX.dot("bad", Z("接口出错", "API ผิดพลาด"))}<div class="small muted" data-notr style="max-width:260px">${esc(s.last_error.slice(0, 120))}</div>`
        : s.last_ok ? `${UX.dot("ok", Z("接口正常", "API ปกติ"))} <span class="small muted">${fmtTime(s.last_ok).slice(11, 16)}</span>` : UX.dot("warn", Z("等第一次拉取", "รอดึงครั้งแรก"))) : `<span class="muted">${Z("扩展 / 手工", "ส่วนขยาย / เอง")}</span>`}</td>
      <td>${s.unreplied ? `<b class="bad">${s.unreplied}</b>` : 0} / ${s.open}</td>
      <td><div class="csd-mode" data-shop="${esc(s.shop)}">${MODES.map(([k, zh, th]) => `<button class="${s.mode === k ? "on" : ""}" data-mode="${k}" ${isOwner() ? "" : "disabled"}>${Z(zh, th)}</button>`).join("")}</div></td>
      <td>${s.api ? `<label class="small row"><input type="checkbox" data-im="${esc(s.shop)}" ${s.im ? "checked" : ""} ${isOwner() ? "" : "disabled"}> ${Z("接口收发", "รับส่งผ่าน API")}</label>` : ""}</td></tr>`;
    const jobs = d.jobs || {}, jc = jobs.counts || {};
    const wk = Z("近 7 天", "7 วัน");
    // ---- 数字卡片：现在要处理的 ----
    const now = UX.kpis([
      { icon: "💬", label: Z("现在未回复", "ยังไม่ตอบ"), value: t.unreplied, tone: t.unreplied ? "warn" : "ok", go: "cs:unreplied" },
      { icon: "⏳", label: Z("等了超过 5 分钟", "รอเกิน 5 นาที"), value: t.wait5, tone: t.wait5 ? "warn" : "", go: "cs:unreplied" },
      { icon: "⏱", label: Z("等了超过 15 分钟", "รอเกิน 15 นาที"), value: t.wait15, tone: t.wait15 ? "bad" : "", go: "cs:unreplied" },
      { icon: "🙋", label: Z("需要人工", "ต้องใช้คน"), value: t.human_needed, tone: t.human_needed ? "bad" : "", go: "cs:human" },
      { icon: "👤", label: Z("分给我的", "ของฉัน"), value: t.mine, go: "cs:mine" },
    ]);
    // ---- 数字卡片：今天（带 7 天走势）----
    const today = UX.kpis([
      { label: Z("今天来问的买家", "ลูกค้าที่ทักวันนี้"), value: t.buyers, sub: `${wk} ${sum(se.buyers)}`, spark: se.buyers },
      { label: Z("今天回复", "ตอบวันนี้"), value: (t.ai_sent || 0) + (t.human_sent || 0), sub: Z(`AI ${t.ai_sent} · 人工 ${t.human_sent}`, `AI ${t.ai_sent} · คน ${t.human_sent}`), spark: se.sent },
      { label: Z("AI 自动回复", "AI ตอบเอง"), value: t.ai_sent, sub: `${wk} ${sum(se.ai)}`, spark: se.ai, tone: "info" },
      { label: Z("平均首次响应", "ตอบครั้งแรกเฉลี่ย"), value: n(t.first_avg, Z(" 分钟", " นาที")), sub: Z(`要求 ≤ ${AM} 分钟`, `เป้า ≤ ${AM} นาที`), spark: se.reply_min,
        tone: t.first_avg == null ? "" : t.first_avg <= AM ? "ok" : "bad" },
      { label: Z("今天新会话", "แชทใหม่วันนี้"), value: t.new },
    ]);
    // ---- 服务指标（有要求线）----
    const meters = [
      UX.meter({ label: Z("平均首次响应", "ตอบครั้งแรกเฉลี่ย"), value: t.first_avg, target: AM, better: "low", text: n(t.first_avg, Z("分", "น.")), targetText: Z(`≤ ${AM} 分`, `≤ ${AM} น.`) }),
      UX.meter({ label: Z("近 7 天平均回复", "ตอบเฉลี่ย 7 วัน"), value: p.avg_reply_min, target: AM, better: "low", text: n(p.avg_reply_min, Z("分", "น.")), targetText: Z(`≤ ${AM} 分`, `≤ ${AM} น.`) }),
      UX.meter({ label: Z("AI 草稿直接采用", "ใช้ร่าง AI ตรงๆ"), value: p.adopt_pct, target: 70, better: "high", text: n(p.adopt_pct, "%"), targetText: "≥ 70%" }),
      UX.meter({ label: Z("超时才回复的比例", "ตอบช้าเกินเวลา"), value: p.sent ? Math.round(100 * (p.over_alert || 0) / p.sent) : null, target: 10, better: "low", text: p.sent ? Math.round(100 * (p.over_alert || 0) / p.sent) + "%" : "-", targetText: "≤ 10%" }),
      UX.meter({ label: Z("质检平均分", "คะแนนตรวจคุณภาพ"), value: d.qa_avg, target: 4, better: "high", text: n(d.qa_avg, "/5"), targetText: "≥ 4" }),
    ].join("");
    const load = UX.bars(d.agents.map((a) => ({ label: a.name === "?" ? Z("（没登记的账号）", "(ไม่ระบุ)") : a.name, value: a.open + a.sent, text: Z(`${a.open} 个会话 · ${a.sent} 条回复${a.avg_min != null ? ` · ${a.avg_min} 分` : ""}`, `${a.open} แชท · ${a.sent} ข้อความ`),
      tone: a.avg_min != null && a.avg_min > AM ? "warn" : "" })), { empty: Z("今天还没有人回复", "วันนี้ยังไม่มีใครตอบ") });
    const shopBars = UX.bars(d.shops.filter((s) => s.open).map((s) => ({ label: s.shop || Z("（未填店铺）", "(ไม่ระบุร้าน)"), value: s.open, text: Z(`未回复 ${s.unreplied} / ${s.open}`, `ค้าง ${s.unreplied} / ${s.open}`), tone: s.unreplied ? "warn" : "ok" })),
      { empty: Z("现在没有进行中的会话", "ไม่มีแชทที่เปิดอยู่") });
    $("#csd-body").innerHTML = `
      ${now}${today}
      ${d.notices ? `<p class="small muted csd-notice" data-go="system">📢 ${Z(`${d.notices} 个平台通知没读（Lazada 官方发给卖家的，不算在上面的数字里）`, `แจ้งเตือนระบบ ${d.notices} รายการยังไม่อ่าน (ไม่นับรวมด้านบน)`)} →</p>` : ""}
      <div class="csd-grid">
        ${UX.card({ title: `🚨 ${Z("要马上处理", "ต้องจัดการด่วน")}`, help: Z("需人工 + 等了 15 分钟以上的会话，点一下打开", "ต้องใช้คน + รอเกิน 15 นาที"), tone: d.urgent.length ? "bad" : "",
          body: d.urgent.map(conv).join("") || UX.empty(Z("没有，很好 👍", "ไม่มี 👍")) })}
        ${UX.card({ title: `📏 ${Z("服务指标", "ตัวชี้วัดบริการ")}`, help: Z("黑线是要求；绿色达标，红色没达标", "เส้นดำคือเป้า เขียว = ผ่าน แดง = ไม่ผ่าน"), body: meters })}
      </div>
      <div class="csd-grid">
        ${UX.card({ title: `👥 ${Z("客服今天", "แอดมินวันนี้")}`, help: Z("手上的会话（接管 / 分配）+ 今天的回复条数；平均响应超过要求的标黄", "แชทที่ดูแล + ข้อความวันนี้"), body: load })}
        ${UX.card({ title: `🏪 ${Z("各店铺进行中的会话", "แชทที่เปิดอยู่ตามร้าน")}`, body: shopBars })}
      </div>
      ${UX.card({ title: `🏪 ${Z("店铺消息渠道与 AI 模式", "ช่องทางและโหมด AI ของร้าน")}`, help: Z("AI 模式：只人工 = AI 不管；AI 出草稿 = AI 写好人点发送（默认）；AI 自动回复 = 能答的直接发，退款 / 投诉 / 改单等照样转人工。只有老板能改。",
          "โหมด AI: คนตอบเอง / AI ร่างให้คนกดส่ง (ค่าเริ่มต้น) / AI ตอบเองเมื่อมั่นใจ"),
        body: `<div class="csd-scroll"><table class="grid small"><thead><tr><th>${Z("店铺", "ร้าน")}</th><th>${Z("消息渠道", "ช่องทาง")}</th><th>${Z("未回复 / 进行中", "ยังไม่ตอบ / เปิดอยู่")}</th><th>${Z("AI 模式", "โหมด AI")}</th><th></th></tr></thead>
        <tbody>${d.shops.map(shopRow).join("") || `<tr><td colspan="5" class="muted">${Z("还没有店铺。在 设置 → 店铺与接口 接上 Lazada，或者用浏览器扩展。", "ยังไม่มีร้าน")}</td></tr>`}</tbody></table></div>
        ${d.shops.some((s) => s.api && /permission|权限|Permission|AppWithout/i.test(s.last_error)) ? `<p class="small warn">${Z("Lazada 说这个应用没有聊天接口的权限。① 到 open.lazada.com → App Console → 你的应用 → API Permission，确认「Instant Messaging」那一组是已开通（Approved / 已勾选），不是「申请中」；② 如果聊天用的是单独的「In-house IM Chat」应用：到 系统 → 设置 → 店铺对接 → 店铺「设置」里填聊天应用的 App Key / Secret，再点「聊天应用授权」；用同一个应用的话，把店铺重新「授权」一次（旧的授权不带新权限）；③ 回来点「⟳ 立即拉取新消息」。", "Lazada แจ้งว่าแอปยังไม่มีสิทธิ์ใช้ API แชท ① ตรวจใน App Console → API Permission ว่า Instant Messaging อนุมัติแล้ว ② ไปที่ ตั้งค่า → เชื่อมร้านค้า แล้วกด「อนุญาต」ร้าน Lazada ใหม่อีกครั้ง ③ กลับมากด「⟳ ดึงข้อความใหม่ตอนนี้」")}</p>` : ""}` })}
      <div class="csd-grid">
        ${UX.card({ title: `💼 ${Z("今天要跟进的线索", "ลูกค้าที่ต้องติดตามวันนี้")}`, body: d.leads_due.map((l) => `<div class="csd-row" data-conv="${l.id}"><b data-notr>${esc(l.buyer)}</b><span class="small muted" data-notr>${esc(l.shop)}</span><span class="small csd-ell" data-notr>${TH() ? "" : esc(l.note)}</span>${l.value ? `<span>฿${Math.round(l.value)}</span>` : ""}</div>`).join("") || UX.empty(Z("没有", "ไม่มี")) })}
        ${UX.card({ title: `🧾 ${Z("售后 / 投诉（待处理）", "หลังการขาย / ร้องเรียน")}`, right: `<span class="muted small">${Z(`登记待办 ${d.records.open} · 超期 ${d.records.overdue}`, `ค้าง ${d.records.open} · เกินกำหนด ${d.records.overdue}`)}</span>`,
          body: d.aftersales.map((r) => `<div class="csd-row" ${r.conv_id ? `data-conv="${r.conv_id}"` : 'data-go-tab="csrec"'}><span class="pill ${r.overdue ? "bad-pill" : ""}">${esc(r.kind)}</span><b data-notr>${esc(r.buyer)}</b><span class="small csd-ell" data-notr>${esc(r.text)}</span></div>`).join("") || UX.empty(Z("没有", "ไม่มี")) })}
        ${UX.card({ title: `🤖 ${Z("AI 答不上来的问题", "คำถามที่ AI ตอบไม่ได้")}`, right: `<button class="mini" data-go-tab="cskb">${Z("去补知识库", "ไปเพิ่มความรู้")}</button>`,
          body: UX.bars(d.unanswered.map((u) => ({ label: TH() ? u.q_th || u.q : u.q, value: u.count, text: `${u.count}×`, go: "tab:cskb" })), { empty: Z("没有", "ไม่มี") }) })}
        ${UX.card({ title: `✅ ${Z("质检抽查（AI 打分）", "สุ่มตรวจคุณภาพ (AI ให้คะแนน)")}`, right: `<span class="muted small">${Z("平均", "เฉลี่ย")} ${n(d.qa_avg)}/5</span>`,
          body: d.qa.map((q) => `<div class="csd-row" data-conv="${q.conv_id}"><span class="pill ${q.score < 3 ? "bad-pill" : q.score >= 4 ? "ok-pill" : "warn-pill"}">${q.score}</span><b data-notr>${esc(q.buyer || "")}</b><span class="small muted" data-notr>${esc(q.agent || "")}</span><span class="small csd-ell" data-notr>${TH() ? "" : esc(q.comment || "")}</span></div>`).join("")
            || UX.empty(Z("每天自动抽几个昨天的会话打分（在 设置 → 客服 里设数量）；也可以在聊天页右边点「让 AI 给这次服务打分」。", "สุ่มตรวจทุกวันอัตโนมัติ")) })}
      </div>
      <p class="small muted">${Z("后台任务", "งานเบื้องหลัง")}：${Z("排队", "รอ")} ${jc.todo || 0} · ${Z("进行中", "กำลังทำ")} ${jc.doing || 0} · ${Z("失败", "ล้มเหลว")} ${jc.failed || 0}${jobs.external ? Z(" · 在单独的进程里运行", " · รันแยกโปรเซส") : ""}
        ${(jobs.failed || []).slice(0, 2).map((f) => ` · <span class="bad" data-notr>${esc(f.kind)}: ${esc((f.error || "").slice(0, 80))}</span>`).join("")}</p>`;
  }

  function goInbox(st) { goTab("cs"); setTimeout(() => { const b = document.querySelector(`#cs-tabs [data-st="${st}"]`); if (b) b.click(); }, 400); }
  document.addEventListener("ux-go", (e) => { if (String(e.detail).startsWith("cs:") && $("#tab-csdash") && !$("#tab-csdash").classList.contains("hidden")) goInbox(String(e.detail).slice(3)); });
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
      if (tl) goInbox(tl.dataset.go);
    } catch (err) { toast(err.message, true); }
  });
  document.addEventListener("change", async (e) => {
    if (!e.target.dataset || e.target.dataset.im === undefined) return;
    try { await api("/api/cs/shops/mode", { json: { shop: e.target.dataset.im, im: e.target.checked } }); toast(Z("已保存", "บันทึกแล้ว")); } catch (err) { toast(err.message, true); }
  });

  window.CSDASH = { show, reload: load };
})();
