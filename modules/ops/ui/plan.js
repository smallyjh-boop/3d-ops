"use strict";
// 运营分析第二期（v2.48）：爆款 / 上量计划、营销日历（v2.49 起在「运营 → 计划与活动」的页签里；流量数据并进了「商品表现」，见 ops.js）。公共小函数在 market.js 的 window.OPSU。
(function () {
  const U = window.OPSU;
  const { $, Z, m, n1, PLAT, day, card, tbl, link } = U;
  const own = () => typeof ME === "undefined" || !ME || ME.role === "owner";
  const BOX = { ops_plans: "ops-plans", ops_cal: "ops-cal" };
  async function show(tab) {
    const box = $("#" + BOX[tab]);
    if (!box) return;
    if (!box.innerHTML) box.innerHTML = `<p class="muted">${Z("加载中…", "กำลังโหลด…")}</p>`;
    try {
      if (tab === "ops_plans") return await plansPage(box);
      if (tab === "ops_cal") return await calPage(box);
    } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
  }

  // ======================= 计划 =======================
  let PL = null, PNEW = false;
  const ST_CLS = { ahead: "ok", ok: "ok", start: "", pending: "muted", behind: "warn", far: "bad" };
  function chart(series) {
    const W = 600, H = 110, P = 4;
    const mx = Math.max(1, ...series.map((x) => Math.max(x.target || 0, x.actual || 0)));
    const bw = (W - P * 2) / series.length;
    const y = (v) => H - P - (v / mx) * (H - P * 2);
    const bars = series.map((x, i) => x.actual == null ? "" : `<rect x="${P + i * bw + bw * 0.15}" y="${y(x.actual)}" width="${bw * 0.7}" height="${Math.max(1, y(0) - y(x.actual))}" class="${x.actual >= x.target ? "oa-rev" : "oa-low"}"><title>${x.day} ${Z("实际", "จริง")} ${x.actual} / ${Z("目标", "เป้า")} ${x.target}</title></rect>`).join("");
    const line = series.map((x, i) => `${i ? "L" : "M"}${P + i * bw + bw / 2},${y(x.target)}`).join(" ");
    return `<svg viewBox="0 0 ${W} ${H}" class="oa-chart oa-chart-s" preserveAspectRatio="none">${bars}<path d="${line}" class="oa-target"/></svg>
      <div class="small muted">${Z("柱 = 每天实际卖出件数（ERP 订单），线 = 目标", "แท่ง = ชิ้นที่ขายจริงต่อวัน (ออเดอร์ ERP) เส้น = เป้า")}</div>`;
  }
  function planCard(p) {
    const pr = p.progress;
    const tasks = p.tasks.map((t) => `<li class="${t.due ? "warn" : t.done_at ? "muted" : ""}"><label><input type="checkbox" data-p-task="${t.id}" data-pid="${p.id}" ${t.done_at ? "checked" : ""}>
      <span class="small">${t.day} · ${esc(Z(t.phase, t.phase_th || t.phase))}${t.source === "ai" ? " · AI" : ""}</span> <span data-notr>${esc(Z(t.text, t.text_th || t.text))}</span></label></li>`).join("");
    const b = p.bench;
    return card(`<span class="mono" data-notr>${esc(p.sku)}</span> <span data-notr>${esc(p.name || "")} ${esc(p.color || "")}</span> · ${esc(Z(p.kind_label, p.kind_th))} · ${esc(PLAT(p.platform))}
        <b class="${ST_CLS[pr.status] || ""}">${esc(Z(pr.status_label, pr.status_th))}</b>${p.status !== "active" ? ` <span class="muted">（${p.status === "done" ? Z("已结束", "จบแล้ว") : Z("已停止", "หยุดแล้ว")}）</span>` : ""}`,
      `<div class="tiles">
        <div class="tile"><span>${Z("进度", "ความคืบหน้า")}</span><b>${Z(`第 ${pr.elapsed} / ${p.days} 天`, `วันที่ ${pr.elapsed} / ${p.days}`)}</b><small>${Z("开始", "เริ่ม")} ${p.start_day}</small></div>
        <div class="tile"><span>${Z("累计实际 / 目标（件）", "สะสมจริง / เป้า (ชิ้น)")}</span><b>${pr.cum_actual} / ${pr.cum_target}</b><small>${pr.ratio != null ? Z(`达成 ${Math.round(pr.ratio * 100)}%`, `ทำได้ ${Math.round(pr.ratio * 100)}%`) : ""}</small></div>
        <div class="tile"><span>${Z("近 7 天日均 / 今天目标", "เฉลี่ย 7 วัน / เป้าวันนี้")}</span><b>${pr.avg7} / ${pr.target_now}</b><small>${Z("目标日销", "เป้าขาย/วัน")} ${p.target_daily} · ${Z("起点", "เริ่มที่")} ${p.baseline_daily ?? 0}${p.benchmark_daily != null ? ` · ${Z("对标竞品", "คู่แข่ง")} ${p.benchmark_daily}` : ""}</small></div>
        ${pr.actual_profit !== undefined ? `<div class="tile"><span>${Z("计划期销售额 / 利润", "ยอดขาย / กำไร ช่วงแผน")}</span><b>${m(pr.actual_revenue)}</b><small>${Z("利润", "กำไร")} ${m(pr.actual_profit)}</small></div>` : ""}</div>
      ${chart(pr.series)}
      ${p.tips.length ? `<h4>${Z("现在该做什么", "ตอนนี้ควรทำอะไร")}</h4><ul class="small">${Z(p.tips, p.tips_th).map((x) => `<li data-notr>${esc(x)}</li>`).join("")}</ul>` : ""}
      ${b ? `<p class="small muted">${Z("竞品", "คู่แข่ง")}：${b.comp_count} · ${Z("中位价", "ราคากลาง")} ${m(b.comp_price_median)} · ${Z("最高日销", "ขายสูงสุด/วัน")} ${n1(b.comp_daily_top)}</p>` : ""}
      ${p.ai_note ? `<div class="oa-note small" data-notr>${esc(p.ai_note)}</div>` : ""}
      <h4>${Z("分阶段任务（到日子的会进 🔔 待办）", "งานแต่ละช่วง (ถึงวันจะขึ้นใน 🔔 งานที่ต้องทำ)")}</h4><ul class="oa-tasks">${tasks}</ul>
      <div class="row gap wrap"><input data-p-newtask="${p.id}" placeholder="${Z("加一个任务", "เพิ่มงาน")}" style="flex:1;min-width:200px"><input data-p-newoff="${p.id}" type="number" min="0" value="${Math.max(0, pr.elapsed - 1)}" style="width:70px" title="${Z("第几天（从 0 开始）", "วันที่ (เริ่ม 0)")}">
        <button class="mini" data-p-addtask="${p.id}">${Z("加任务", "เพิ่มงาน")}</button></div>
      ${own() ? `<div class="row gap wrap" style="margin-top:8px"><button data-p-ai="${p.id}">${Z("AI 更新计划", "AI อัปเดตแผน")}</button>
        <input data-p-target="${p.id}" value="${p.target_daily}" style="width:70px"><button class="mini" data-p-settarget="${p.id}">${Z("改目标日销", "แก้เป้าขาย/วัน")}</button>
        ${p.status === "active" ? `<button class="mini" data-p-status="${p.id}" data-st="done">${Z("结束计划", "จบแผน")}</button><button class="mini" data-p-status="${p.id}" data-st="stopped">${Z("停止", "หยุด")}</button>`
          : `<button class="mini" data-p-status="${p.id}" data-st="active">${Z("重新开始", "เริ่มใหม่")}</button>`}
        <button class="mini" data-p-del="${p.id}">${Z("删除", "ลบ")}</button></div>` : ""}`);
  }
  async function plansPage(box) {
    PL = await api("/api/oa/plans");
    const pre = window.OPS_PLAN_PREFILL; window.OPS_PLAN_PREFILL = null;
    if (pre) PNEW = true;
    const active = PL.rows.filter((p) => p.status === "active"), closed = PL.rows.filter((p) => p.status !== "active");
    box.innerHTML = `<p class="small">${Z("爆款计划：测款期 / 刚出单的款，日销做到对标竞品最高日销的 30%；上量计划：已经稳定出单的款，做到 60%。每天用 ERP 实际订单对目标；不投广告、不刷单。",
        "แผนสินค้าขายดี: สินค้าที่เพิ่งเริ่มขาย ทำยอดขาย/วันให้ได้ 30% ของคู่แข่งที่ขายดีสุด แผนเพิ่มยอดขาย: สินค้าที่ขายสม่ำเสมอแล้ว ทำให้ได้ 60% เทียบกับออเดอร์จริงใน ERP ทุกวัน ไม่ยิงแอด ไม่ปั๊มออเดอร์")}</p>
      ${own() ? `<div class="row gap" style="margin-bottom:8px"><button data-p-new>${Z("＋ 新建计划", "＋ สร้างแผน")}</button></div><div id="op-new"></div>` : ""}
      ${active.map(planCard).join("") || `<p class="muted">${Z("还没有进行中的计划。", "ยังไม่มีแผนที่กำลังทำ")}</p>`}
      ${closed.length ? `<details><summary>${Z(`已结束的计划（${closed.length}）`, `แผนที่จบแล้ว (${closed.length})`)}</summary>${closed.map(planCard).join("")}</details>` : ""}`;
    if (PNEW && own()) newForm(pre);
    box.onclick = plansClick;
    box.onchange = async (e) => {
      const c = e.target.closest("[data-p-task]");
      if (c) { await api(`/api/oa/plans/${c.dataset.pid}/task`, { json: { id: +c.dataset.pTask, done: c.checked } }); toast(Z("已保存", "บันทึกแล้ว")); }
    };
  }
  function newForm(pre) {
    const b = $("#op-new");
    b.innerHTML = card(Z("新建计划", "สร้างแผน"), `<datalist id="op-skus">${PL.skus.map((s) => `<option value="${esc(s.sku)}">${esc(s.name)} ${esc(s.color || "")}</option>`).join("")}</datalist>
      <div class="oa-fgrid"><label>SKU<input name="sku" list="op-skus" value="${esc((pre && pre.sku) || "")}"></label>
        <label>${Z("平台", "แพลตฟอร์ม")}<select name="platform"><option value="lazada">Lazada</option><option value="shopee">Shopee</option><option value="tiktok">TikTok</option><option value="">${Z("全部平台", "ทุกแพลตฟอร์ม")}</option></select></label>
        <label>${Z("类型", "ประเภท")}<select name="kind"><option value="hero">${Z("爆款计划（30%）", "แผนสินค้าขายดี (30%)")}</option><option value="scale">${Z("上量计划（60%）", "แผนเพิ่มยอดขาย (60%)")}</option></select></label>
        <label>${Z("目标日销（件，空 = 自动）", "เป้าขาย/วัน (ว่าง = อัตโนมัติ)")}<input name="target_daily"></label>
        <label>${Z("天数", "จำนวนวัน")}<input name="days" value="30"></label><label>${Z("开始日期", "วันเริ่ม")}<input name="start_day" type="date"></label></div>
      <p class="small muted" data-p-sug></p>
      <div class="row gap"><button class="mini" data-p-suggest>${Z("算建议目标", "คำนวณเป้าแนะนำ")}</button><button data-p-create>${Z("建计划", "สร้างแผน")}</button><button class="mini" data-p-cancel>${Z("取消", "ยกเลิก")}</button></div>`);
    if (pre && pre.platform) b.querySelector('[name="platform"]').value = pre.platform;
  }
  async function plansClick(e) {
    const t = (s) => e.target.closest(s);
    let b;
    if (t("[data-p-new]")) { PNEW = !PNEW; if (PNEW) newForm(); else $("#op-new").innerHTML = ""; return; }
    if (t("[data-p-cancel]")) { PNEW = false; $("#op-new").innerHTML = ""; return; }
    if ((b = t("[data-p-suggest]"))) {
      const f = U.form($("#op-new"));
      return busy(b, async () => {
        const r = await api(`/api/oa/plans/suggest?sku=${encodeURIComponent(f.sku)}&platform=${f.platform}&kind=${f.kind}`);
        $("#op-new [name=target_daily]").value = r.target_daily;
        $("[data-p-sug]").textContent = `${Z("建议", "แนะนำ")} ${r.target_daily} ${Z("件/天", "ชิ้น/วัน")}：${Z(r.note, r.note_th)}（${Z("现在日均", "ตอนนี้เฉลี่ย")} ${r.baseline_daily}）`;
      });
    }
    if ((b = t("[data-p-create]"))) {
      const f = U.form($("#op-new"));
      return busy(b, async () => { await api("/api/oa/plans", { json: f }); toast(Z("计划建好了", "สร้างแผนแล้ว")); PNEW = false; show("ops_plans"); });
    }
    if ((b = t("[data-p-addtask]"))) {
      const id = b.dataset.pAddtask, tx = $(`[data-p-newtask="${id}"]`).value, off = $(`[data-p-newoff="${id}"]`).value;
      if (!tx.trim()) return;
      return busy(b, async () => { await api(`/api/oa/plans/${id}/task`, { json: { text: tx, offset: off } }); show("ops_plans"); });
    }
    if ((b = t("[data-p-ai]"))) return busy(b, async () => { await apiJob(`/api/oa/plans/${b.dataset.pAi}/ai`, { json: {} }); toast(Z("AI 已更新计划", "AI อัปเดตแผนแล้ว")); show("ops_plans"); });
    if ((b = t("[data-p-settarget]"))) return busy(b, async () => { await api(`/api/oa/plans/${b.dataset.pSettarget}`, { json: { target_daily: $(`[data-p-target="${b.dataset.pSettarget}"]`).value } }); show("ops_plans"); });
    if ((b = t("[data-p-status]"))) return busy(b, async () => { await api(`/api/oa/plans/${b.dataset.pStatus}`, { json: { status: b.dataset.st } }); show("ops_plans"); });
    if ((b = t("[data-p-del]"))) { if (!confirm(Z("删除这个计划和它的任务？", "ลบแผนนี้และงานทั้งหมด?"))) return; await api(`/api/oa/plans/${b.dataset.pDel}`, { json: { delete: true } }); return show("ops_plans"); }
  }

  // ======================= 营销日历 =======================
  const KIND = () => ({ double: Z("双数日大促", "แคมเปญวันเลขเบิ้ล"), mid: Z("月中", "กลางเดือน"), payday: Z("发薪日", "เงินเดือนออก"), festival: Z("节日", "เทศกาล"), custom: Z("自己加的", "เพิ่มเอง") });
  async function calPage(box) {
    const d = await api("/api/oa/campaigns");
    const c = d.capacity;
    const ev = d.events.map((e) => {
      const tl = e.tasks.map((t) => `<div class="oa-tl ${t.today ? "today" : t.done ? "done" : ""}"><b>${t.offset > 0 ? "T+" + t.offset : t.offset === 0 ? "T" : "T" + t.offset}</b> <span class="small">${t.day}</span>
        <div class="small" data-notr>${esc(Z(t.text, t.text_th))}</div></div>`).join("");
      return `<div class="card oa-ev ${e.big ? "" : "oa-ev-small"}"><h3><span data-notr>${esc(Z(e.name, e.name_th || e.name))}</span> <span class="small muted">${e.start}${e.end !== e.start ? " ~ " + e.end : ""} · ${esc(KIND()[e.kind] || e.kind)}</span>
          <span class="small ${e.days_left <= 3 && e.days_left >= 0 ? "warn" : "muted"}">${e.days_left > 0 ? Z(`还有 ${e.days_left} 天`, `อีก ${e.days_left} วัน`) : e.days_left === 0 ? Z("就是今天", "วันนี้") : Z("已开始 / 已过", "เริ่มแล้ว / ผ่านไปแล้ว")}</span>
          ${own() ? `<button class="mini" data-cal-hide="${esc(e.key)}">${e.kind === "custom" ? Z("删除", "ลบ") : Z("隐藏", "ซ่อน")}</button>` : ""}</h3>
        <p class="small">${Z("预计", "คาด")} <b>${n1(e.expected_orders)}</b> ${Z("单/天", "ออเดอร์/วัน")}（${Z("平时", "ปกติ")} ×${e.multiplier}）· ${Z("要打印约", "ต้องพิมพ์ราว")} ${n1(e.need_hours)} ${Z("小时", "ชม.")}
          ${e.over_capacity ? `<b class="bad">${Z("超过产能：建议限量或提前打库存", "เกินกำลังผลิต: ควรจำกัดจำนวนหรือพิมพ์เก็บไว้ก่อน")}</b>` : ""}</p>
        ${e.big ? `<div class="oa-tls">${tl}</div>` : ""}</div>`;
    }).join("");
    box.innerHTML = card(Z("产能（生产模块的打印机）", "กำลังผลิต (เครื่องพิมพ์ในโมดูลการผลิต)"), `<div class="tiles">
        <div class="tile"><span>${Z("每天能打", "พิมพ์ได้ต่อวัน")}</span><b>${n1(c.capacity_hours_per_day)} ${Z("小时", "ชม.")}</b><small>${c.printers} ${Z("台打印机", "เครื่อง")}${c.from_prod ? "" : Z("（按设置估）", " (ตามที่ตั้งไว้)")}</small></div>
        <div class="tile"><span>${Z("平均每单打印", "เฉลี่ยพิมพ์ต่อออเดอร์")}</span><b>${n1(c.avg_hours_per_order, 2)} ${Z("小时", "ชม.")}</b><small>${c.avg_from_history ? Z("近 30 天订单算的", "คิดจากออเดอร์ 30 วัน") : Z("订单太少，用设置里的默认值", "ออเดอร์น้อย ใช้ค่าที่ตั้งไว้")}</small></div>
        <div class="tile"><span>${Z("平时每天", "ปกติต่อวัน")}</span><b>${n1(c.baseline_daily_orders, 1)} ${Z("单", "ออเดอร์")}</b><small>${Z("每天最多能做", "ทำได้มากสุด/วัน")} ${c.max_orders_per_day ?? "—"} ${Z("单", "ออเดอร์")}</small></div>
        <div class="tile"><span>${Z("大促当天最多接", "วันแคมเปญรับได้มากสุด")}</span><b>${c.max_orders_campaign_day ?? "—"} ${Z("单", "ออเดอร์")}</b><small>${Z("排队中", "ในคิว")} ${n1(c.queue_hours)} ${Z("小时", "ชม.")}</small></div></div>
      <p class="small muted">${Z("内置活动按平台惯例推算（双数日、月中 15 号、发薪日 25 号、泰国节日），具体日期和报名截止以卖家中心公告为准。要专门准备的活动（大促、节日、自己加的）到日子的任务进今日待办。",
        "แคมเปญในระบบคำนวณตามธรรมเนียมแพลตฟอร์ม (วันเลขเบิ้ล กลางเดือน 15 เงินเดือนออก 25 เทศกาลไทย) วันที่จริงให้ดูประกาศในหลังร้าน งานที่ถึงวันจะขึ้นในงานวันนี้")}</p>`)
      + (own() ? card(Z("加活动", "เพิ่มแคมเปญ"), `<div class="oa-fgrid" id="oc-addcal"><label>${Z("名称", "ชื่อ")}<input name="name"></label><label>${Z("开始", "เริ่ม")}<input name="start" type="date"></label>
          <label>${Z("结束", "สิ้นสุด")}<input name="end" type="date"></label><label>${Z("订单是平时的几倍", "ออเดอร์กี่เท่าของปกติ")}<input name="multiplier" value="3"></label><label class="oa-span">${Z("备注", "หมายเหตุ")}<input name="note"></label></div>
          <div class="row gap"><button data-cal-add>${Z("加入", "เพิ่ม")}</button>${d.hidden ? `<button class="mini" data-cal-restore>${Z(`恢复隐藏的内置活动（${d.hidden}）`, `แสดงแคมเปญที่ซ่อน (${d.hidden})`)}</button>` : ""}</div>`) : "")
      + (ev || `<p class="muted">${Z("接下来没有活动", "ไม่มีแคมเปญเร็วๆ นี้")}</p>`);
    box.onclick = async (e) => {
      const t = (s) => e.target.closest(s);
      let b;
      if ((b = t("[data-cal-add]"))) return busy(b, async () => { await api("/api/oa/campaigns", { json: U.form($("#oc-addcal")) }); toast(Z("已加入", "เพิ่มแล้ว")); show("ops_cal"); });
      if ((b = t("[data-cal-hide]"))) return busy(b, async () => { await api("/api/oa/campaigns/remove", { json: { key: b.dataset.calHide } }); show("ops_cal"); });
      if ((b = t("[data-cal-restore]"))) return busy(b, async () => { await api("/api/oa/campaigns/remove", { json: { restore: true } }); show("ops_cal"); });
    };
  }

  window.OPSB = Object.assign(window.OPSB || {}, { plan: { tabs: Object.keys(BOX), show } });
})();
