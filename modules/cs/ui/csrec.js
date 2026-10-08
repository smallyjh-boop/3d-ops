"use strict";
// 客服 v2.24：登记中心、客服报表、客服账号与店铺、工作台上的客服报告（登录就能看到）
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const KT = { note: "บันทึก", todo: "ติดตาม", aftersales: "หลังการขาย", complaint: "ร้องเรียน", request: "ความต้องการพิเศษ" };
  const mins = (v) => (v == null ? "—" : v < 1 ? Z("<1 分钟", "<1 นาที") : v < 60 ? `${Math.round(v)} ${Z("分钟", "นาที")}` : `${(v / 60).toFixed(1)} ${Z("小时", "ชม.")}`);
  const pct = (v) => (v == null ? "—" : v + "%");
  const t = (x) => (x ? fmtTime(x).slice(5, 16) : "");
  const dayStart = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.getTime() / 1000; };

  function show(name) {
    if (name === "csrec") loadRec().catch((e) => toast(e.message, true));
    if (name === "csrep") loadRep().catch((e) => toast(e.message, true));
    if (name === "csext") loadAgents().catch(() => {});
  }

  // ---------------- 登记中心 ----------------
  let REC = null;
  function recQuery() {
    const p = $("#rec-period").value, now = Date.now() / 1000;
    const from = { today: dayStart(), "7d": dayStart() - 6 * 86400, "30d": dayStart() - 29 * 86400 }[p] || "";
    const qs = new URLSearchParams({ kind: $("#rec-kind").value, status: $("#rec-status").value, shop: $("#rec-shop").value,
      agent: $("#rec-agent").value, q: $("#rec-q").value.trim(), from: from ? String(from) : "", to: from ? String(now + 1) : "" });
    return qs.toString();
  }
  async function loadRec() {
    const qs = recQuery();
    REC = await api("/api/cs/records?" + qs);
    $("#rec-export").href = "/api/cs/records/export?" + qs;
    const keep = (el, items, first) => { const cur = el.value; el.innerHTML = `<option value="">${first}</option>` + items.map(([v, l]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""} data-notr>${esc(l)}</option>`).join(""); };
    keep($("#rec-kind"), Object.entries(REC.kinds).map(([k, v]) => [k, TH() ? KT[k] || v : v]), Z("全部类型", "ทุกประเภท"));
    keep($("#rec-shop"), (REC.shops || []).map((x) => [x, x]), Z("全部店铺", "ทุกร้าน"));
    keep($("#rec-agent"), (REC.agents || []).map((x) => [x.agent, x.name]), Z("全部登记人", "ทุกคน"));
    const c = REC.counts;
    $("#rec-counts").innerHTML = Z(`待处理 <b>${c.open}</b> · 今天到期 <b>${c.due_today}</b> · <span class="${c.overdue ? "bad" : ""}">已超期 <b>${c.overdue}</b></span>`,
      `รอจัดการ <b>${c.open}</b> · ครบกำหนดวันนี้ <b>${c.due_today}</b> · เลยกำหนด <b>${c.overdue}</b>`);
    $("#rec-table tbody").innerHTML = REC.records.map((r) => `<tr class="${r.overdue ? "rec-od" : ""}" data-id="${r.id}">
        <td><span class="pill">${esc(TH() ? KT[r.kind] || r.kind_zh : r.kind_zh)}</span></td>
        <td>${r.status === "done" ? `<span class="ok">${Z("已完成", "เสร็จ")}</span>` : r.overdue ? `<span class="bad">${Z("已超期", "เลยกำหนด")}</span>` : r.kind === "note" ? "" : Z("待处理", "รอจัดการ")}</td>
        <td data-notr>${esc(r.shop || "")}${r.platform ? ` · ${esc(r.platform)}` : ""}<div><b>${esc(r.buyer || "")}</b></div></td>
        <td data-notr style="max-width:360px">${esc(r.text)}</td>
        <td data-notr class="muted">${esc(r.result || "")}</td>
        <td>${t(r.due_at)}</td>
        <td data-notr>${esc(r.agent || "")}${r.done_by ? `<div class="muted small">✓ ${esc(String(r.done_by).replace(/^api:/, ""))}</div>` : ""}</td>
        <td>${t(r.created_at)}</td>
        <td class="nowrap">${r.status === "open" && r.kind !== "note" ? `<button class="mini primary" data-rec="done">✓ ${Z("完成", "เสร็จ")}</button>` : ""}
          ${r.status === "done" && r.kind !== "note" ? `<button class="mini" data-rec="reopen">${Z("重开", "เปิดใหม่")}</button>` : ""}
          ${r.conv_id ? `<button class="mini" data-rec="conv" data-cid="${r.conv_id}">${Z("会话", "แชท")}</button>` : ""}
          <button class="mini" data-rec="edit">✎</button> <button class="mini danger" data-rec="del">✕</button></td></tr>`).join("")
      || `<tr><td colspan="9" class="muted">${Z("没有符合条件的登记", "ไม่มีรายการ")}</td></tr>`;
  }
  ["#rec-kind", "#rec-status", "#rec-shop", "#rec-agent", "#rec-period"].forEach((k) => $(k).addEventListener("change", () => loadRec().catch((e) => toast(e.message, true))));
  let RQ = null;
  $("#rec-q").addEventListener("input", () => { clearTimeout(RQ); RQ = setTimeout(() => loadRec().catch(() => {}), 400); });
  $("#rec-table").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-rec]"); if (!b) return;
    const id = +b.closest("tr").dataset.id, r = REC.records.find((x) => x.id === id);
    try {
      if (b.dataset.rec === "done") {
        const res = prompt(Z("处理结果（可空）", "ผลการจัดการ (ไม่ใส่ก็ได้)"), r.result || ""); if (res === null) return;
        await api(`/api/cs/records/${id}`, { json: { status: "done", result: res } });
      }
      if (b.dataset.rec === "reopen") await api(`/api/cs/records/${id}`, { json: { status: "open" } });
      if (b.dataset.rec === "edit") {
        const tx = prompt(Z("登记内容", "รายละเอียด"), r.text); if (tx === null) return;
        await api(`/api/cs/records/${id}`, { json: { text: tx } });
      }
      if (b.dataset.rec === "del") { if (!confirm(Z("删除这条登记？", "ลบรายการนี้?"))) return; await api(`/api/cs/records/${id}`, { method: "DELETE" }); }
      if (b.dataset.rec === "conv") { goTab("cs"); setTimeout(() => window.CS && CS.openConv(+b.dataset.cid), 400); return; }
      loadRec();
    } catch (err) { toast(err.message, true); }
  });
  $("#rec-new").addEventListener("click", () => {
    const kinds = REC ? REC.kinds : { note: "备注" };
    MODAL.open(`<div class="row between"><h3>${Z("新登记", "บันทึกใหม่")}</h3><button class="mini" data-recm="close">${Z("关闭", "ปิด")}</button></div>
      <div class="form3"><label>${Z("类型", "ประเภท")}<select id="rn-kind">${Object.entries(kinds).map(([k, v]) => `<option value="${k}">${esc(TH() ? KT[k] || v : v)}</option>`).join("")}</select></label>
        <label>${Z("店铺", "ร้าน")}<input id="rn-shop" list="rn-shops" data-notr><datalist id="rn-shops">${((REC && REC.shops) || []).map((x) => `<option value="${esc(x)}">`).join("")}</datalist></label>
        <label>${Z("买家", "ลูกค้า")}<input id="rn-buyer" data-notr></label>
        <label>${Z("平台", "แพลตฟอร์ม")}<select id="rn-plat"><option value="lazada">Lazada</option><option value="shopee">Shopee</option><option value="tiktok">TikTok</option><option value="line">LINE</option><option value="">${Z("其他", "อื่นๆ")}</option></select></label>
        <label>${Z("到期时间", "กำหนดเวลา")}<input id="rn-due" type="datetime-local"></label></div>
      <label>${Z("内容", "รายละเอียด")}<textarea id="rn-text" rows="3" data-notr></textarea></label>
      <div class="row gap" style="margin-top:8px"><button class="primary" data-recm="save">${Z("登记", "บันทึก")}</button></div>`);
  });
  document.addEventListener("click", async (e) => {
    const b = e.target.closest && e.target.closest("[data-recm]"); if (!b) return;
    if (b.dataset.recm === "close") return MODAL.close();
    const dv = $("#rn-due").value;
    try {
      await api("/api/cs/records", { json: { kind: $("#rn-kind").value, text: $("#rn-text").value, shop: $("#rn-shop").value.trim(), buyer: $("#rn-buyer").value.trim(),
        platform: $("#rn-plat").value, due_at: dv ? new Date(dv).getTime() / 1000 : "" } });
      MODAL.close(); toast(Z("已登记", "บันทึกแล้ว")); loadRec();
    } catch (err) { toast(err.message, true); }
  });

  // ---------------- 客服报表 ----------------
  function agentTable(rows, own) {
    if (!rows.length) return `<p class="muted small">${Z("这段时间没有回复记录", "ไม่มีการตอบในช่วงนี้")}</p>`;
    return `<table class="grid small"><thead><tr><th>${Z("客服", "แอดมิน")}</th><th>${Z("接待会话", "แชทที่ดูแล")}</th><th>${Z("回复", "ตอบ")}</th><th>${Z("自动回复", "ตอบอัตโนมัติ")}</th>
      <th>${Z("首次响应", "ตอบครั้งแรก")}</th><th>${Z("平均响应", "เวลาตอบเฉลี่ย")}</th><th>${Z("超时", "ตอบช้า")}</th><th>${Z("AI 采用率", "ใช้ร่าง AI")}</th><th>${Z("登记 / 完成", "บันทึก / เสร็จ")}</th></tr></thead><tbody>
      ${rows.map((a) => `<tr><td data-notr><b>${esc(a.name)}</b></td><td>${a.convs}</td><td>${a.sent}</td><td>${a.auto}</td><td>${mins(a.first_reply_min)}</td>
        <td>${mins(a.avg_reply_min)}</td><td class="${a.over_alert ? "bad" : ""}">${a.over_alert}</td><td>${pct(a.adopt_pct)}</td><td>${a.records_added} / ${a.records_done}</td></tr>`).join("")}</tbody></table>`;
  }
  function shopTable(rows) {
    if (!rows.length) return `<p class="muted small">${Z("这段时间没有咨询", "ไม่มีการสอบถาม")}</p>`;
    return `<table class="grid small"><thead><tr><th>${Z("店铺", "ร้าน")}</th><th>${Z("咨询会话", "แชท")}</th><th>${Z("买家消息", "ข้อความลูกค้า")}</th><th>${Z("回复", "ตอบ")}</th>
      <th>${Z("新客户 / 老客户", "ลูกค้าใหม่ / เก่า")}</th><th>${Z("关联订单", "มีออเดอร์")}</th><th>${Z("新线索", "โอกาสขายใหม่")}</th><th>${Z("平均响应", "เวลาตอบเฉลี่ย")}</th><th>${Z("还没回复", "ยังไม่ตอบ")}</th></tr></thead><tbody>
      ${rows.map((s) => `<tr><td data-notr><b>${esc(s.shop)}</b> <span class="muted">${esc(s.platforms.join("、"))}</span></td><td>${s.convs}</td><td>${s.buyer_msgs}</td><td>${s.sent}</td>
        <td>${s.new_customers} / ${s.returning}</td><td>${s.with_order}</td><td>${s.leads}</td><td>${mins(s.avg_reply_min)}</td><td class="${s.unanswered ? "bad" : ""}">${s.unanswered}</td></tr>`).join("")}</tbody></table>`;
  }
  async function loadRep() {
    const p = $("#rep-period").value;
    const r = await api("/api/cs/report?period=" + p);
    $("#rep-export").href = "/api/cs/report/export?period=" + p;
    const tt = r.total;
    $("#rep-body").innerHTML = `<div class="tiles">
        <div class="tile"><span>${Z("咨询会话", "แชท")}</span><b>${tt.convs}</b></div>
        <div class="tile"><span>${Z("买家消息", "ข้อความลูกค้า")}</span><b>${tt.buyer_msgs}</b></div>
        <div class="tile"><span>${Z("回复（其中自动）", "ตอบ (อัตโนมัติ)")}</span><b>${tt.sent}<small> / ${tt.auto}</small></b></div>
        <div class="tile"><span>${Z("平均响应", "เวลาตอบเฉลี่ย")}</span><b>${mins(tt.avg_reply_min)}</b></div>
        <div class="tile ${tt.over_alert ? "bad" : ""}"><span>${Z("超时回复", "ตอบช้า")}</span><b>${tt.over_alert}</b></div></div>
      <div class="card"><h3>${Z("按客服", "ตามแอดมิน")}</h3>${agentTable(r.agents)}</div>
      <div class="card"><h3>${Z("按店铺", "ตามร้าน")}</h3>${shopTable(r.shops)}</div>`;
  }
  $("#rep-period").addEventListener("change", () => loadRep().catch((e) => toast(e.message, true)));

  // ---------------- 客服账号与店铺（老板） ----------------
  async function loadAgents() {
    const box = $("#cs-agents");
    if (!box) return;
    if (typeof ME === "undefined" || !ME || ME.role !== "owner") { box.innerHTML = ""; return; }
    const d = await api("/api/cs/agents");
    box.innerHTML = `<h3>${Z("客服账号与负责的店铺", "แอดมินและร้านที่ดูแล")}</h3>
      <p class="small muted">${Z("给每个客服勾选他负责的店铺：员工只看得到这些店铺的会话、登记和报表；一个都不勾 = 全部店铺。扩展密钥的名字用员工的登录账号名，回复记录和绩效就能对上同一个人。",
        "เลือกร้านที่แต่ละคนดูแล: พนักงานจะเห็นเฉพาะร้านนั้น ไม่เลือกเลย = ทุกร้าน")}</p>
      ${d.shops.length ? "" : `<p class="small warn">${Z("还没有店铺名：在扩展面板的「店铺」里填上店铺名（每个店铺的浏览器各填一次），或者在会话里填。", "ยังไม่มีชื่อร้าน")}</p>`}
      <table class="grid small"><thead><tr><th>${Z("客服", "แอดมิน")}</th><th>${Z("类型", "ประเภท")}</th><th>${Z("负责的店铺", "ร้านที่ดูแล")}</th></tr></thead><tbody>
      ${d.agents.map((a) => `<tr data-agent="${esc(a.agent)}"><td data-notr><b>${esc(a.name)}</b> <span class="muted">${esc(a.agent)}</span></td>
        <td>${a.kind === "key" ? Z("扩展密钥", "คีย์ส่วนขยาย") : a.role === "owner" ? Z("老板", "เจ้าของ") : Z("员工账号", "บัญชีพนักงาน")}</td>
        <td>${a.role === "owner" ? `<span class="muted">${Z("全部店铺", "ทุกร้าน")}</span>` : d.shops.map((s) => `<label class="chk-inline"><input type="checkbox" data-agshop="${esc(s)}" ${a.shops.includes(s) ? "checked" : ""}> <span data-notr>${esc(s)}</span></label>`).join(" ") || "—"}
          ${a.role !== "owner" && !a.shops.length ? `<span class="muted small">（${Z("全部", "ทั้งหมด")}）</span>` : ""}</td></tr>`).join("")}</tbody></table>`;
  }
  document.addEventListener("change", async (e) => {
    const cb = e.target.closest && e.target.closest("[data-agshop]"); if (!cb) return;
    const tr = cb.closest("tr");
    const shops = [...tr.querySelectorAll("[data-agshop]")].filter((x) => x.checked).map((x) => x.dataset.agshop);
    try { await api("/api/cs/agents/shops", { json: { agent: tr.dataset.agent, shops } }); toast(Z("已保存", "บันทึกแล้ว")); loadAgents(); } catch (err) { toast(err.message, true); }
  });

  // ---------------- 工作台：客服报告（登录后第一屏） ----------------
  function diff(a, b, lowerBetter) {
    if (a == null || b == null || a === b) return "";
    const up = a > b, good = lowerBetter ? !up : up;
    return ` <span class="small ${good ? "ok" : "bad"}">${up ? "↑" : "↓"}${typeof a === "number" && !Number.isInteger(a) ? Math.abs(a - b).toFixed(1) : Math.abs(a - b)}</span>`;
  }
  async function dash(el) {
    if (!el) return;
    let w;
    try { w = await api("/api/cs/workbench"); } catch { el.innerHTML = ""; return; }
    const T0 = w.today.total, Y0 = w.yesterday.total;
    const mine = w.mine && w.mine.today, my0 = w.mine && w.mine.yesterday;
    const head = w.owner
      ? `<div class="tiles">
          <div class="tile" data-go="cs"><span>${Z("待回复", "รอตอบ")}</span><b class="${w.waiting_n ? "bad" : ""}">${w.waiting_n}</b></div>
          <div class="tile"><span>${Z("今天咨询会话", "แชทวันนี้")}</span><b>${T0.convs}${diff(T0.convs, Y0.convs)}</b></div>
          <div class="tile"><span>${Z("今天回复（自动）", "ตอบวันนี้ (อัตโนมัติ)")}</span><b>${T0.sent}<small> / ${T0.auto}</small>${diff(T0.sent, Y0.sent)}</b></div>
          <div class="tile"><span>${Z("平均响应", "เวลาตอบเฉลี่ย")}</span><b>${mins(T0.avg_reply_min)}${diff(T0.avg_reply_min, Y0.avg_reply_min, true)}</b></div>
          <div class="tile ${T0.over_alert ? "bad" : ""}"><span>${Z("超时回复", "ตอบช้า")}</span><b>${T0.over_alert}</b></div>
          <div class="tile ${w.records.overdue ? "bad" : w.records.due_today ? "warn" : ""}" data-go="csrec"><span>${Z("待办 今天到期 / 超期", "งานครบกำหนด / เลย")}</span><b>${w.records.due_today}<small> / ${w.records.overdue}</small></b></div>
          <div class="tile ${w.leads_due ? "warn" : ""}" data-go="cs"><span>${Z("线索要跟进", "โอกาสขายต้องติดตาม")}</span><b>${w.leads_due}</b></div>
          <div class="tile" data-go="cskb"><span>${Z("AI 答不上来的问题", "คำถามที่ AI ตอบไม่ได้")}</span><b>${w.unanswered_kb}</b></div></div>`
      : `<div class="tiles">
          <div class="tile" data-go="cs"><span>${Z("待回复", "รอตอบ")}</span><b class="${w.waiting_n ? "bad" : ""}">${w.waiting_n}</b></div>
          <div class="tile"><span>${Z("我今天接待", "วันนี้ฉันดูแล")}</span><b>${mine ? mine.convs : 0}${diff(mine ? mine.convs : 0, my0 ? my0.convs : 0)}</b></div>
          <div class="tile"><span>${Z("我今天回复", "วันนี้ฉันตอบ")}</span><b>${mine ? mine.sent : 0}</b></div>
          <div class="tile"><span>${Z("我的平均响应", "เวลาตอบเฉลี่ยของฉัน")}</span><b>${mins(mine && mine.avg_reply_min)}${diff(mine && mine.avg_reply_min, my0 && my0.avg_reply_min, true)}</b></div>
          <div class="tile ${mine && mine.over_alert ? "bad" : ""}"><span>${Z("我超时回复", "ฉันตอบช้า")}</span><b>${mine ? mine.over_alert : 0}</b></div>
          <div class="tile ${w.records.overdue ? "bad" : w.records.due_today ? "warn" : ""}" data-go="csrec"><span>${Z("待办 今天到期 / 超期", "งานครบกำหนด / เลย")}</span><b>${w.records.due_today}<small> / ${w.records.overdue}</small></b></div></div>`;
    const waits = w.waiting.length ? `<div><b class="small">${Z("等你回复的买家", "ลูกค้ารอตอบ")}</b>${w.waiting.map((x) => `<div class="small"><a href="#" data-wconv="${x.id}" data-notr>${esc(x.buyer || "?")}</a>
        <span class="muted" data-notr>${esc(x.shop)} · ${esc(x.platform || "")}</span> · <span class="${(x.wait_min || 0) >= 10 ? "bad" : ""}">${Z(`等了 ${x.wait_min || 0} 分钟`, `รอ ${x.wait_min || 0} นาที`)}</span>${x.needs_human ? ` <span class="warn">${Z("需人工", "ต้องให้คนตอบ")}</span>` : ""}</div>`).join("")}</div>` : "";
    const due = w.records_due.length ? `<div><b class="small">${Z("今天到期的待办", "งานที่ครบกำหนดวันนี้")}</b>${w.records_due.map((r) => `<div class="small ${r.overdue ? "bad" : ""}"><span class="pill">${esc(TH() ? KT[r.kind] || r.kind_zh : r.kind_zh)}</span>
        <span data-notr>${esc(r.buyer || "")}</span> · <span data-notr>${esc(r.text.slice(0, 60))}</span> · ${t(r.due_at)}</div>`).join("")}</div>` : "";
    el.innerHTML = `<div class="card dash-cs"><div class="row between"><h3>💬 ${Z("客服今日报告", "รายงานแชทวันนี้")}</h3>
        <span class="small muted">${Z("和昨天比", "เทียบกับเมื่อวาน")} · <a href="#" data-go="csrep">${Z("看详细报表", "ดูรายงานละเอียด")}</a></span></div>
      ${head}
      <div class="lanes two">${waits}${due}</div>
      ${w.owner && w.today.agents.length ? `<details ${w.today.agents.length > 1 ? "open" : ""}><summary class="small">${Z("今天每个客服", "แอดมินแต่ละคนวันนี้")}</summary>${agentTable(w.today.agents)}</details>` : ""}
      ${w.owner && w.today.shops.length > 1 ? `<details><summary class="small">${Z("今天每个店铺", "แต่ละร้านวันนี้")}</summary>${shopTable(w.today.shops)}</details>` : ""}</div>`;
  }
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("[data-wconv]"); if (!a) return;
    e.preventDefault(); goTab("cs"); setTimeout(() => window.CS && CS.openConv(+a.dataset.wconv), 400);
  });

  window.CSREC = { show, dash };
})();
