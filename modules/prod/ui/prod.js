"use strict";
// 生产模块：生产看板（打印批次 / 开始打印对话框）、打印机、打印方案列表、成品库存 / 备货、质量统计
(function () {
  const H = () => window.OPSH;
  const Z = (zh, th) => (window.I18N && I18N.lang === "th" ? th : zh);
  const CONN_ZH = { auto: "自动识别", bambu: "拓竹局域网", moonraker: "Klipper / Moonraker（root 过的 K1）", creality: "Creality 原厂固件", none: "不连接" };
  const FST = { draft: "草稿（未复核）", reviewed: "已复核（未试打）", verified: "已试打验证" };
  let BOARD = null, PR_TIMER = null, BOARD_TIMER = null;

  function show(name) {
    clearInterval(PR_TIMER); clearInterval(BOARD_TIMER);
    if (name === "production") { loadBoard(); BOARD_TIMER = setInterval(() => { if (!document.hidden && !$("#modal:not(.hidden)")) loadBoard().catch(() => {}); }, 20000); }
    if (name === "printers") { loadPrinters(); PR_TIMER = setInterval(() => loadPrinters().catch(() => {}), 10000); }
    if (name === "recipes") loadRecipes();
    if (name === "stock") loadStock();
    if (name === "quality") { loadQuality(); loadCalib().catch(() => {}); }
  }

  // ---------------- 弹窗（v2.31：通用弹窗搬到 static/modal.js，这里只接「关掉打印方案弹窗后刷新列表」） ----------------
  const modal = (html) => MODAL.open(html);
  const closeModal = () => MODAL.close();
  MODAL.onClose((ctx) => {
    if (ctx.wasRecipe && $("#tab-recipes") && !$("#tab-recipes").classList.contains("hidden")) loadRecipes();
    if (ctx.wasRecipe && $("#tab-files") && !$("#tab-files").classList.contains("hidden") && window.FILES) window.FILES.load();
  });

  // ---------------- 生产看板 ----------------
  function prodHead(j) {
    const pr = j.product || {};
    return `<div class="wk-head">${pr.img ? `<img src="${esc(pr.img)}" alt="" loading="lazy">` : '<div class="noimg"></div>'}
      <div><div class="wk-sku mono" data-notr>${esc(j.sku || "?")}</div>
        <div class="wk-name" data-notr>${esc(pr.name_zh || j.name || "")}</div>
        ${pr.title_th ? `<div class="wk-th small" data-notr>${esc(pr.title_th)}</div>` : ""}</div></div>`;
  }
  function jobCard(j) {
    const h = H();
    const late = j.ship_by && j.planned_end && j.planned_end > j.ship_by;
    const pl = j.plan || {};
    const kind = (j.kind && j.kind !== "order" ? `<span class="pill kind-${j.kind}">${esc(j.kind_zh)}</span>` : "") +
      (j.tech === "resin" ? `<span class="pill resin-pill" title="光固化：打完先用酒精清洗，晾干后二次固化，再去支撑">🧪 树脂${j.status === "post" ? " · 清洗→固化→去支撑" : ""}</span>` : "") +
      (j.stock_n ? `<span class="pill tag-pill" title="先占住，发货出库时扣库存">📦 ${Z("用库存", "ใช้สต็อก")} ×${j.stock_n}</span>` : "");
    const btns = {
      todo: `<button class="big primary" data-start="${j.id}">▶ 开始打印…</button>` +
        (j.stock > 0 && j.kind !== "stock" ? `<button class="big" data-usestock="${j.id}" title="先占住，发货出库时才扣库存">📦 ${Z(`用库存（可用 ${j.stock} 个）`, `ใช้สต็อก (มี ${j.stock} ชิ้น)`)}</button>` : ""),
      post: `<button class="big primary" data-js="packed">📦 已打包</button><button class="mini" data-js="todo">退回重打</button>`,
      packed: `<button class="big primary" data-js="done">🚚 已发货</button><button class="mini" data-js="post">退回</button>`,
    }[j.status] || "";
    const mv = j.status === "todo" && (CFG && CFG.printers || []).length > 1
      ? `<select class="mv" data-mv="${j.id}"><option value="">换打印机…</option>${CFG.printers.map((p, i) => i === j.printer || p.enabled === false ? "" : `<option value="${i}" data-notr>${esc((p.code ? p.code + " · " : "") + p.name)}</option>`).join("")}</select>` : "";
    const fileLine = j.status === "todo" ? (pl.file
      ? `<div class="small">📄 一盘 ${pl.per_plate} 个 · 还要 ${pl.plates} 盘 · <span class="pill fpill-${pl.file_status}">${esc(FST[pl.file_status] || "")}</span></div>`
      : '<div class="small warn">还没有可用的切片文件（打印方案里切片并复核），只能手动开始</div>') : "";
    return `<div class="job job-${j.status}${j.priority ? " urgent" : ""}" data-jid="${j.id}">
      ${prodHead(j)}
      <div class="jbig">${j.material ? `<span class="mat-badge" data-notr>${esc(j.material)}</span>` : ""} ${h.colorTxt(j.color)}
        <b class="qty">× ${j.remaining ?? j.qty}</b>${j.qty_done ? `<span class="small muted"> / 共 ${j.qty}，已打 ${j.qty_done}</span>` : ""} ${kind}</div>
      ${j.custom_note ? `<div class="note-flag" data-notr>✎ ${esc(j.custom_note)}</div>` : ""}
      ${j.buyer_note ? `<div class="small" data-notr>💬 ${esc(j.buyer_note)}</div>` : ""}
      ${j.note && j.kind !== "order" ? `<div class="small muted" data-notr>${esc(j.note)}</div>` : ""}
      ${fileLine}
      ${j.product && j.product.recipe_zh && j.status === "todo" ? `<div class="small recipe-line">🧩 ${esc(j.product.recipe_zh)}</div>` : ""}
      ${j.product && j.product.recipe_notes && j.status === "todo" ? `<div class="small warn" data-notr>⚠ ${esc(j.product.recipe_notes)}</div>` : ""}
      <div class="small muted">${pl.grams ? h.num(pl.grams, 0) + "g · " : ""}${pl.hours_left ? "约 " + h.num(pl.hours_left, 1) + "h" : ""}
        ${j.status === "todo" && j.planned_start ? ` · 预计 ${h.short(j.planned_start)} → ${h.short(j.planned_end)}` : ""}</div>
      <div class="small">${j.order_no ? `订单 <span class="mono" data-notr>${esc(j.order_no)}</span> ${esc(h.PLAT[j.platform] || j.platform || "")}` : ""}
        ${j.ship_by ? ` · <span class="${late ? "bad" : ""}">最晚发货 ${h.short(j.ship_by)}${late ? "（来不及！）" : ""}</span>` : ""}
        ${j.priority ? ' <span class="pill bad-pill">加急</span>' : ""}${j.fails ? ` <span class="bad">失败 ${j.fails} 次</span>` : ""}</div>
      <div class="row gap wrap jbtns">${btns}${mv}<button class="mini" data-ticket="${j.id}" title="打印工单贴纸">🏷</button></div></div>`;
  }
  function runCard(r, lane) {
    const h = H();
    const st = lane.status || {};
    const mine = r.sent && st.state === "printing";
    return `<div class="run" data-rid="${r.id}">
      <div class="row between"><b>正在打的这一盘 · ${r.count} 个</b>${mine ? h.stChip(st, lane.status_zh) : `<span class="pill pst-printing">${r.sent ? "已发送" : "手动开始"}</span>`}</div>
      ${mine ? `<div class="bar"><div style="width:${Number(st.progress) || 0}%"></div></div>` : ""}
      ${prodHead({ sku: r.sku, name: r.name, product: r.product })}
      <div class="jbig">${r.material ? `<span class="mat-badge" data-notr>${esc(r.material)}</span>` : ""} ${h.colorTxt(r.color)} <b class="qty">× ${r.count}</b> <span class="small muted">开始 ${h.short(r.started_at)} · 约 ${h.num(r.hours, 1)}h · ${h.num(r.grams, 0)}g</span></div>
      <div class="small">${r.jobs.map((j) => `<div>· ${j.order_no ? `订单 <span class="mono" data-notr>${esc(j.order_no)}</span>` : esc(j.kind_zh || "")} × ${j.run_qty}
        ${j.custom_note ? `<span class="note-inline" data-notr>✎ ${esc(j.custom_note)}</span>` : ""}</div>`).join("")}
        ${r.extra ? `<div>· 多打 ${r.extra} 个进成品库存</div>` : ""}</div>
      ${r.alert ? `<div class="alert-box">⚠ ${esc(r.alert)}</div>` : ""}
      <div class="row gap wrap jbtns"><button class="big primary" data-rdone="${r.id}">✓ 这一盘打完</button>
        <button class="big danger" data-rfail="${r.id}">✗ 失败</button><button class="mini" data-rcancel="${r.id}">撤销</button></div></div>`;
  }
  async function loadBoard() {
    const b = await api("/api/production");
    BOARD = b;
    const warn = [];
    if (!b.lanes.length) warn.push("还没有设置打印机（系统 → 设置 → 生产），任务没法分配。");
    if (b.missing_data.length) warn.push(`${b.missing_data.length} 个任务的产品缺少克数/时长，也没有切片文件，排单时间不准。请到产品的「打印方案」里切片。`);
    $("#prod-warn").innerHTML = warn.map((w) => `<p class="card warn small">${esc(w)}</p>`).join("");
    const lanes = b.lanes.map((l) => `<div class="lane card ${l.enabled ? "" : "lane-off"}" data-lane="${l.index}"><div class="row between"><h3><span class="pcode" data-notr>${esc(l.code)}</span> <span class="small muted" data-notr>${esc(l.name)}${l.note ? " · " + esc(l.note) : ""}</span>${l.tech === "resin" ? ' <span class="pill resin-pill">光固化</span>' : ""}</h3>${l.enabled ? H().stChip(l.status, l.status_zh) : '<span class="pill">停用</span>'}</div>
        <div class="small muted">排队 ${l.queue.length} 个任务 · 约 ${l.hours} 小时${l.free_at ? " · 空闲 " + H().short(l.free_at) : ""}</div>
        ${l.runs.map((r) => runCard(r, l)).join("")}
        ${l.queue.map(jobCard).join("") || (l.runs.length ? "" : '<p class="muted small">空闲</p>')}</div>`);
    if (b.unassigned.length) lanes.push(`<div class="lane card"><h3>未分配</h3>${b.unassigned.map(jobCard).join("")}</div>`);
    $("#prod-lanes").innerHTML = lanes.join("");
    $("#prod-post").innerHTML = b.post.map(jobCard).join("") || '<p class="muted small">没有</p>';
    $("#prod-packed").innerHTML = b.packed.map(jobCard).join("") || '<p class="muted small">没有</p>';
    $("#prod-post-n").textContent = b.post.length ? `(${b.post.length})` : "";
    $("#prod-packed-n").textContent = b.packed.length ? `(${b.packed.length})` : "";
  }

  // ---- 开始打印对话框 ----
  async function startDialog(jid, printer) {
    let o;
    try { o = await api(`/api/jobs/${jid}/send-options` + (printer != null ? `?printer=${printer}` : "")); } catch (e) { toast(e.message, true); return; }
    const lane = (BOARD.lanes || []).find((l) => l.index === o.printer) || {};
    const connected = lane.conn && lane.conn !== "none" && !["offline", "none"].includes((lane.status || {}).state);
    const busyPr = ["printing", "paused"].includes((lane.status || {}).state);
    const sg = o.suggestion;
    const j = o.job;
    const el = modal(`<div class="row between"><h3>开始打印 · <span class="mono" data-notr>${esc(j.sku)}</span> ${H().colorTxt(j.color)}</h3><button class="mini" data-mclose>关闭</button></div>
      <div class="form2">
        <label>打印机<select id="sd-printer">${(CFG.printers || []).map((p, i) => `<option value="${i}" ${i === o.printer ? "selected" : ""} data-notr>${esc((p.code ? p.code + " · " : "") + p.name)}${p.enabled === false ? "（停用）" : ""}</option>`).join("")}</select></label>
        <div class="small">${H().stChip(lane.status, lane.status_zh)}<br>这台打印机一盘最多约 <b>${o.capacity}</b> 个</div>
      </div>
      <div class="sd-box"><b>这一盘打几个</b>
        <label class="row"><input type="radio" name="sd-mode" value="order" checked> 按订单：<b>${sg.order_qty}</b> 个</label>
        <label class="row"><input type="radio" name="sd-mode" value="full"> 满盘：<b>${o.capacity}</b> 个（多出来的进成品库存）</label>
        ${sg.extra_stock ? `<label class="row"><input type="radio" name="sd-mode" value="ai"> 建议：<b>${sg.count}</b> 个（订单 ${sg.order_qty} + 备货 ${sg.extra_stock}）</label>` : ""}
        <label class="row"><input type="radio" name="sd-mode" value="custom"> 指定：<input id="sd-n" type="number" min="1" max="${o.capacity}" value="${sg.order_qty}" style="width:80px"> 个</label>
        <div class="small muted">${esc(sg.why)}</div>
      </div>
      ${o.merge.length ? `<div class="sd-box"><b>一起拼这一盘的其他任务</b>（同产品同颜色，按发货先后排）
        <div class="small">· 这个任务 #${j.id}：${o.remaining} 个 ${j.custom_note ? `<span class="note-inline" data-notr>✎ ${esc(j.custom_note)}</span>` : ""}</div>
        ${o.merge.map((m) => `<label class="row small"><input type="checkbox" data-merge="${m.id}" checked> 任务 #${m.id} ${m.order_no ? `订单 <span class="mono" data-notr>${esc(m.order_no)}</span>` : esc(m.kind === "stock" ? "备货" : "")} × ${m.remaining}
          ${m.custom_note ? `<span class="note-inline" data-notr>✎ ${esc(m.custom_note)}</span>` : ""}</label>`).join("")}</div>` : ""}
      ${o.recipe_zh ? `<div class="small recipe-line">🧩 打印方案：${esc(o.recipe_zh)}${o.recipe && o.recipe.notes ? `<div class="warn" data-notr>⚠ ${esc(o.recipe.notes)}</div>` : ""}</div>` : ""}
      <div id="sd-mat" class="sd-box sd-mat"></div>
      <div id="sd-file" class="sd-box"></div>
      <div id="sd-review" class="sd-box hidden"><b>这一盘的文件还没试打验证，请人工确认：</b>
        ${o.review_items.map(([k, lab]) => `<label class="row small"><input type="checkbox" data-ri="${k}"> ${esc(lab)}</label>`).join("")}</div>
      <label class="row bedclear"><input type="checkbox" id="sd-mat-ok"> <b>打印机里装的是 <span data-notr>${esc(o.material_check.need)}</span> ${H().colorTxt(j.color)}（已经看过料盘 / 料架）</b></label>
      ${o.material_check.tray_warn ? `<label class="row small warn"><input type="checkbox" id="sd-tray-ok"> 料盘读数不准，我已确认装的是 <span data-notr>${esc(o.material_check.need)}</span></label>` : ""}
      <label class="row bedclear"><input type="checkbox" id="sd-clear"> <b>热床已经清空，上一盘的零件和废料都拿走了</b></label>
      <div class="row gap wrap">
        ${connected && !busyPr ? '<button class="big primary" id="sd-send">📤 发送到打印机并开始</button>' : ""}
        <button class="big ${connected && !busyPr ? "" : "primary"}" id="sd-manual">▶ 手动开始（我在打印机上开始）</button>
      </div>
      ${!connected ? '<p class="small muted">这台打印机没有连接（或离线），只能手动开始：在切片软件或打印机屏幕上开始打印，打完回来点「这一盘打完」。</p>' : ""}
      ${busyPr ? '<p class="small warn">打印机正在打别的东西，等打完再发送；或者选择别的打印机。</p>' : ""}`);
    const files = o.files;
    const count = () => {
      const m = ($('input[name="sd-mode"]:checked', el) || {}).value;
      if (m === "full") return o.capacity;
      if (m === "ai") return sg.count;
      if (m === "custom") return Math.max(1, Math.min(o.capacity, +$("#sd-n", el).value || 1));
      return sg.order_qty;
    };
    const updFile = () => {
      const n = count();
      // v2.40：机型 / 喷嘴 / 热床板对不上这台打印机的文件不选它，说明原因
      const fit = (x) => x.machine_ok !== false;
      const f = files.filter((x) => x.per_plate === n && x.status !== "draft" && x.active && fit(x)).sort((a, b) => (b.status === "verified") - (a.status === "verified"))[0];
      const draft = files.find((x) => x.per_plate === n && x.status === "draft" && x.active && fit(x));
      const misfit = !f && !draft ? files.find((x) => x.per_plate === n && x.active && !fit(x)) : null;
      let html;
      if (misfit) html = `<span class="warn">一盘 ${n} 个的文件 <span data-notr>${esc(misfit.filename)}</span> 不能用在这台打印机：${esc((misfit.machine_errors || []).join("；"))}</span><br>`;
      else html = "";
      let html0;
      if (f) html0 = `📄 用文件：<span data-notr>${esc(f.filename)}</span> v${f.version} · <span class="pill fpill-${f.status}">${esc(FST[f.status])}</span> · 每盘 ${H().num(f.grams, 0)}g · ${H().num(f.hours, 1)}h`;
      else if (draft) html0 = `📄 有一盘 ${n} 个的文件，但还没复核（草稿）。可以在这里确认后直接用。`;
      else if (o.has_model) html0 = `📄 还没有一盘 ${n} 个的文件，开始时会<b>按打印方案自动切片</b>（大约 10 秒到 1 分钟）。`;
      else html0 = `<span class="warn">没有一盘 ${n} 个的切片文件，这个产品也没有 3D 模型。现有文件：${files.map((x) => x.per_plate + " 个").join("、") || "无"}。可以手动开始。</span>`;
      html += html0;
      const ff = f || draft;
      const p = ff && ff.report && ff.report.params || {};
      const mc = o.material_check;
      const bad = p.material && window.GVIEW && GVIEW.sameMat(p.material, mc.need) === "diff";
      if (ff) html += ` <button class="mini" data-gvf="${ff.id}">🔍 3D 切片预览</button>`;
      $("#sd-file", el).innerHTML = html;
      $("#sd-mat", el).innerHTML = `<div class="row gap wrap"><span>这一盘要用：</span><span class="mat-badge big" data-notr>${esc(mc.need)}</span> ${H().colorTxt(j.color)}
        ${ff ? `<span class="small">切片文件：${p.material ? `<span class="mat-badge ${bad ? "bad" : ""}" data-notr>${esc(p.material)}</span>` : '<span class="warn">没写材料</span>'}
          ${p.filament ? `<span class="muted" data-notr>${esc(p.filament)}</span>` : ""} ${p.nozzle_temp != null ? `🔥 ${p.nozzle_temp}°C` : ""} ${p.bed_temp != null ? `▭ ${p.bed_temp}°C` : ""} ${p.bed_type_zh ? esc(p.bed_type_zh) : ""}</span>` : ""}</div>
        ${bad ? `<div class="bad"><b>材料不对！</b>切片文件是 ${esc(p.material)}，产品要用 ${esc(mc.need)}。请到打印方案里重新切片，不能开始。</div>` : ""}
        ${mc.trays && mc.trays.length ? `<div class="small">打印机料盘：${mc.trays.map((t) => `<span class="tray-chip">${t.hex ? `<i style="background:${esc(t.hex)}"></i>` : ""}<span data-notr>${esc(t.type || "?")}</span></span>`).join(" ")}</div>` : ""}
        ${mc.tray_warn ? `<div class="warn small">${esc(mc.tray_warn)}</div>` : ""}`;
      const needReview = !(f && f.status === "verified");
      $("#sd-review", el).classList.toggle("hidden", !needReview);
      el.dataset.fileId = f ? f.id : (draft ? draft.id : "");
    };
    el.onchange = (e) => {   // 用 onchange（不是 addEventListener），关掉弹窗后不会残留
      if (e.target.id === "sd-printer") { closeModal(); startDialog(jid, e.target.value); return; }
      if (e.target.id === "sd-n") $('input[name="sd-mode"][value="custom"]', el).checked = true;
      updFile();
    };
    $("#sd-n", el).addEventListener("input", () => { $('input[name="sd-mode"][value="custom"]', el).checked = true; updFile(); });
    el.onclick = (e) => { const b = e.target.closest("[data-gvf]"); if (b && window.GVIEW) GVIEW.openFile(+b.dataset.gvf, { material: o.material_check.need }); };
    updFile();
    const go = async (send, btn) => {
      const review = {};
      $$("[data-ri]", el).forEach((x) => (review[x.dataset.ri] = x.checked));
      const body = { printer: +$("#sd-printer", el).value, count: count(), merge_ids: $$("[data-merge]:checked", el).map((x) => +x.dataset.merge),
        send, file_id: el.dataset.fileId || null,
        confirm: { bed_clear: $("#sd-clear", el).checked, review, material: $("#sd-mat-ok", el).checked, tray_override: !!($("#sd-tray-ok", el) || {}).checked } };
      if (!body.confirm.material) { toast("请先确认打印机里装的材料和颜色是对的", true); return; }
      if (!body.confirm.bed_clear) { toast("请先确认热床已经清空", true); return; }
      await busy(btn, async () => {
        let r;
        try { r = await api(`/api/jobs/${jid}/start`, { json: body }); }
        catch (err) {
          if (/料盘里没有接近/.test(err.message) && confirm(err.message + "\n\n已经确认料没问题，仍然发送？")) {
            r = await api(`/api/jobs/${jid}/start`, { json: { ...body, force_color: true } });
          } else throw err;
        }
        closeModal();
        toast((send ? "已发送，打印机开始打印" : "已开始（手动）") + `：这一盘 ${r.count} 个` + (r.extra ? `，多 ${r.extra} 个进库存` : "") + (r.note ? "。" + r.note : "") + (r.warning ? "。提醒：" + r.warning : ""), !!r.note, 8000);
        loadBoard();
      });
    };
    const sb = $("#sd-send", el);
    if (sb) sb.onclick = () => go(true, sb);
    $("#sd-manual", el).onclick = () => go(false, $("#sd-manual", el));
  }
  function failDialog(rid) {
    const reasons = (BOARD && BOARD.fail_reasons) || ["其他"];
    const el = modal(`<div class="row between"><h3>这一盘打印失败</h3><button class="mini" data-mclose>关闭</button></div>
      <p class="small muted">选一个原因（会统计到「质量统计」，用来改进打印方案）。用掉的料会扣库存，任务回到队列重新打。</p>
      <div class="reasons">${reasons.map((r, i) => `<label class="row"><input type="radio" name="fr" value="${esc(r)}" ${i === 0 ? "checked" : ""}> ${esc(r)}</label>`).join("")}</div>
      <label>说明（可空）<input id="fr-note" data-notr></label>
      <button class="big danger" id="fr-ok">确认失败</button>`);
    $("#fr-ok", el).onclick = () => busy($("#fr-ok", el), async () => {
      await api(`/api/runs/${rid}/fail`, { json: { reason: $('input[name="fr"]:checked', el).value, note: $("#fr-note", el).value } });
      closeModal(); toast("已记录失败，任务回到队列"); loadBoard();
    });
  }
  $("#tab-production").addEventListener("click", async (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    const d = t.dataset;
    try {
      if (d.start) return startDialog(+d.start);
      if (d.rfail) return failDialog(+d.rfail);
      if (d.ticket) { window.open(`/print/jobs?ids=${d.ticket}`, "_blank"); return; }
      if (d.rdone) {
        if (!confirm("这一盘已经打完、零件检查合格了？")) return;
        await busy(t, () => api(`/api/runs/${d.rdone}/done`, { json: {} })); toast("已记录：打完，耗材已扣"); return loadBoard();
      }
      if (d.rcancel) {
        if (!confirm("撤销这一盘？（还没真正开始打印时用，不扣料）")) return;
        await api(`/api/runs/${d.rcancel}/cancel`, { json: {} }); return loadBoard();
      }
      if (d.usestock) {
        const n = prompt("用成品库存出几个？", "1"); if (!n) return;
        await api(`/api/jobs/${d.usestock}/use-stock`, { json: { n: +n } }); toast("已用库存（先占住，发货出库时扣库存）"); return loadBoard();
      }
      if (d.js) {
        const jid = t.closest("[data-jid]").dataset.jid;
        await busy(t, () => api(`/api/jobs/${jid}`, { json: { status: d.js } })); return loadBoard();
      }
    } catch (err) { toast(err.message, true); }
  });
  $("#tab-production").addEventListener("change", async (e) => {
    const s = e.target.closest("select[data-mv]");
    if (!s || s.value === "") return;
    try { await api(`/api/jobs/${s.dataset.mv}`, { json: { printer: s.value } }); await loadBoard(); } catch (err) { toast(err.message, true); }
  });
  $("#btn-prod-sched").addEventListener("click", (e) => busy(e.target, async () => { await api("/api/production/schedule", { json: {} }); await loadBoard(); toast("已重新排单"); }));
  $("#btn-prod-reload").addEventListener("click", (e) => busy(e.target, loadBoard));
  $("#btn-prod-ticket").addEventListener("click", () => {
    const ids = [...(BOARD ? BOARD.lanes.flatMap((l) => l.queue.concat(l.runs.flatMap((r) => r.jobs))).concat(BOARD.post) : [])].map((j) => j.id);
    if (!ids.length) { toast("没有任务", true); return; }
    window.open(`/print/jobs?ids=${[...new Set(ids)].join(",")}`, "_blank");
  });

  // ---------------- 打印机 ----------------
  function prCard(p) {
    const h = H();
    const st = p.status || {};
    const c = p.conn || {};
    const own = h.isOwner();
    const prog = st.state === "printing" || st.state === "paused";
    const m = p.maintenance;
    return `<div class="card lane pr-card" data-pi="${p.index}">
      <div class="row between"><h3><span class="pcode" data-notr>${esc(p.code || "")}</span> <span data-notr>${esc(p.name)}</span>${p.enabled === false ? ' <span class="pill">停用</span>' : ""}</h3>${h.stChip(st, p.status_zh)}</div>
      ${prog ? `<div class="bar"><div style="width:${Number(st.progress) || 0}%"></div></div>` : ""}
      <div class="small">${st.file ? `文件：<span data-notr>${esc(st.file)}</span><br>` : ""}
        ${st.layer != null && st.total_layers ? `层 ${st.layer}/${st.total_layers} · ` : ""}
        ${st.nozzle != null ? `喷头 ${h.num(st.nozzle, 0)}°C · 热床 ${h.num(st.bed, 0)}°C` : ""}
        ${st.error ? `<div class="bad">${esc(st.error)}</div>` : ""}</div>
      ${p.run ? `<div class="small">这一盘：<b class="mono" data-notr>${esc(p.run.sku)}</b> ${h.colorTxt(p.run.color)} × ${p.run.count}
        ${p.run.alert ? `<div class="alert-box">⚠ ${esc(p.run.alert)}</div>` : ""}</div>` : ""}
      ${h.trayHtml(st)}
      <label class="small">现在装的料（没有料盘读数时填，例如：白色,黑色）
        <span class="row gap"><input data-loaded value="${esc(c.loaded || "")}" list="color-list" data-notr><button class="mini" data-saveloaded>保存</button></span></label>
      ${c.type && c.type !== "none" ? `<div class="row gap wrap">
        ${st.state === "printing" ? '<button data-pcmd="pause">⏸ 暂停</button>' : ""}
        ${st.state === "paused" ? '<button data-pcmd="resume">▶ 继续</button>' : ""}
        ${prog ? '<button class="danger" data-pcmd="stop">⏹ 取消打印</button>' : ""}</div>` : ""}
      ${m ? `<details class="maint" ${m.items.some((x) => x.due) ? "open" : ""}><summary>保养（累计打印 ${m.hours} 小时）${m.items.some((x) => x.due) ? ' <span class="pill bad-pill">该保养了</span>' : ""}</summary>
        ${m.items.map((it) => `<div class="row between small ${it.due ? "bad" : ""}"><span>${esc(it.label)}：每 ${it.every_h} 小时，已 ${it.since_h} 小时</span>
          <button class="mini" data-maint="${it.item}">已保养</button></div>`).join("")}</details>` : ""}
      ${own ? `<div class="small muted">连接方式：${esc(CONN_ZH[c.type || "none"] || c.type)}${c.detected && c.type === "auto" ? "：" + esc(CONN_ZH[c.detected] || c.detected) : ""} · <a href="#" data-goto-cfg="production">连接设置 →</a></div>` : ""}
    </div>`;
  }
  async function loadPrinters() {
    if (document.activeElement && document.activeElement.closest && document.activeElement.closest("#pr-cards")) return;
    if (Object.entries(LOCKS).some(([k, v]) => k.startsWith("printer-conn-") && v.editing)) return;   // 正在改连接设置时不刷新
    const r = await api("/api/printers");
    const open = new Set($$("#pr-cards details.conn[open]").map((d) => d.closest("[data-pi]").dataset.pi));
    $("#pr-cards").innerHTML = r.printers.map(prCard).join("") || '<p class="muted">还没有打印机（系统 → 设置 → 生产 添加）</p>';
    open.forEach((i) => { const d = $(`#pr-cards [data-pi="${i}"] details.conn`); if (d) d.open = true; });
  }
  $("#btn-pr-reload").addEventListener("click", (e) => busy(e.target, loadPrinters));
  $("#pr-cards").addEventListener("click", async (e) => {
    const card = e.target.closest("[data-pi]");
    if (!card) return;
    const i = card.dataset.pi, t = e.target;
    const conn = () => { const o = {}; card.querySelectorAll("[data-c]").forEach((x) => (o[x.dataset.c] = x.type === "checkbox" ? x.checked : x.value)); return o; };
    try {
      if (t.dataset.pcmd !== undefined) {
        if (t.dataset.pcmd === "stop" && !confirm("确定取消这台打印机正在打的任务？")) return;
        await busy(t, () => api(`/api/printers/${i}/command`, { json: { cmd: t.dataset.pcmd } }));
        toast("指令已发送"); setTimeout(loadPrinters, 2500);
      }
      if (t.dataset.saveloaded !== undefined) {
        await api(`/api/printers/${i}/loaded`, { json: { loaded: card.querySelector("[data-loaded]").value } });
        toast("已保存，排单会优先用这台打印机打这些颜色");
      }
      if (t.dataset.maint) {
        // v2.18：保养时可以选用掉的备件（从库存领用，记到这台打印机）
        let parts = [];
        try { parts = (await api("/api/inv/items?category=part")).items; } catch { parts = []; }
        if (!parts.length) {
          await api("/api/maintenance", { json: { printer: +i, item: t.dataset.maint } }); toast("已记录保养"); document.activeElement.blur(); loadPrinters();
        } else {
          const item = t.dataset.maint;
          const m = modal(`<h3>记录保养：<span data-notr>${esc(item)}</span></h3>
            <p class="muted small">这次用了备件就选上（从库存领用出库，记到这台打印机的支出）；没用备件直接确认。</p>
            <div class="row gap wrap"><select id="mt-part" data-notr><option value="">没用备件</option>${parts.map((p) => `<option value="${p.id}">${esc(p.code)} · ${esc(p.name_zh)}（${p.qty} ${esc(p.unit)}）</option>`).join("")}</select>
              <input id="mt-qty" type="number" value="1" min="0" step="any" style="width:70px"><input id="mt-note" placeholder="备注" style="width:160px"></div>
            <div class="row gap" style="margin-top:8px"><button class="primary" id="mt-ok">确认</button><button data-mclose>取消</button></div>`);
          m.querySelector("#mt-ok").onclick = (e) => busy(e.target, async () => {
            const pid = m.querySelector("#mt-part").value;
            await api("/api/maintenance", { json: { printer: +i, item, note: m.querySelector("#mt-note").value,
              parts: pid ? [{ item_id: +pid, qty: +m.querySelector("#mt-qty").value || 1 }] : [] } });
            toast("已记录保养"); closeModal(); loadPrinters();
          });
        }
      }
      if (t.dataset.csave !== undefined) {
        await busy(t, () => api(`/api/printers/${i}/conn`, { json: conn() })); toast("已保存"); document.activeElement.blur(); loadPrinters();
      }
      if (t.dataset.ctest !== undefined) {
        await busy(t, () => api(`/api/printers/${i}/conn`, { json: conn() }));
        const r = await api(`/api/printers/${i}/test`, { json: {} }).catch((err) => { toast(err.message, true); return null; });
        if (r) toast(`连接成功：${CONN_ZH[r.type] || r.type}，状态：${r.status_zh}`);
        document.activeElement.blur(); loadPrinters();
      }
    } catch (err) { toast(err.message, true); }
  });

  // ---------------- 打印方案列表 ----------------
  let RC_ALL = [];
  async function loadRecipes() {
    const [prods, files] = await Promise.all([api("/api/products"), api("/api/print-files")]);
    const by = {};
    files.files.forEach((f) => (by[f.product_id] = by[f.product_id] || []).push(f));
    RC_ALL = prods.map((p) => ({ ...p, files: by[p.id] || [] }));
    renderRecipes();
  }
  function renderRecipes() {
    const q = $("#rc-q").value.trim().toLowerCase(), flt = $("#rc-filter").value;
    const rows = RC_ALL.filter((p) => {
      if (q && !(`${p.id} ${p.name_zh} ${(p.skus || []).join(" ")}`.toLowerCase().includes(q))) return false;
      const act = p.files.filter((f) => f.active);
      if (flt === "none") return !act.some((f) => f.status !== "draft");
      if (flt === "draft") return act.some((f) => f.status === "draft");
      if (flt === "reviewed") return act.some((f) => f.status === "reviewed");
      if (flt === "verified") return act.some((f) => f.status === "verified");
      return true;
    });
    $("#rc-table tbody").innerHTML = rows.map((p) => {
      const act = p.files.filter((f) => f.active);
      const cnt = (s) => act.filter((f) => f.status === s).length;
      return `<tr data-rcp="${esc(p.id)}" class="clickable"><td>${p.thumb ? `<img class="thumb" src="${esc(p.thumb)}" alt="">` : ""}<b class="mono" data-notr>${esc(p.id)}</b> <span data-notr>${esc(p.name_zh)}</span></td>
        <td class="small">${p.has_recipe ? "✔ 已设置" : '<span class="muted">未设置</span>'}${p.has_model ? "" : ' <span class="muted">· 无模型</span>'}</td>
        <td class="small">${act.length} 个${cnt("verified") ? ` · <span class="pill fpill-verified">已验证 ${cnt("verified")}</span>` : ""}${cnt("reviewed") ? ` · <span class="pill fpill-reviewed">未试打 ${cnt("reviewed")}</span>` : ""}${cnt("draft") ? ` · <span class="pill fpill-draft">待复核 ${cnt("draft")}</span>` : ""}</td>
        <td>${p.file_status ? `<span class="pill fpill-${p.file_status}">${esc(FST[p.file_status])}</span>` : '<span class="pill bad-pill">没有可用文件</span>'}</td>
        <td><button class="mini">打开</button></td></tr>`;
    }).join("") || '<tr><td colspan="5" class="muted">没有</td></tr>';
  }
  $("#rc-q").addEventListener("input", renderRecipes);
  $("#rc-filter").addEventListener("change", renderRecipes);
  function openRecipe(pid) {
    const el = modal(`<div class="row between"><h3>打印方案 · <span class="mono" data-notr>${esc(pid)}</span></h3><button class="mini" data-mclose>关闭</button></div><div id="rc-modal-box"></div>`);
    el.classList.add("wide");
    window.RECIPE.mount($("#rc-modal-box", el), pid);
  }
  window.PROD_OPEN_RECIPE = openRecipe;
  $("#rc-table").addEventListener("click", (e) => {
    const tr = e.target.closest("[data-rcp]");
    if (tr) openRecipe(tr.dataset.rcp);
  });

  // ---------------- 成品库存 / 备货 ----------------
  async function loadStock() {
    const r = await api("/api/stock");
    const h = H();
    $("#sg-table tbody").innerHTML = r.suggest.map((s) => `<tr><td class="mono" data-notr>${esc(s.sku)}</td><td data-notr>${esc(s.name || "")} ${h.colorTxt(s.color)}</td>
      <td>${s.sold30}</td><td>${s.daily}</td><td>${s.target}${s.auto_target ? ' <span class="muted small">(自动)</span>' : ""}</td><td>${s.stock}${s.reserved ? ` <span class="small muted">${Z(`（订单占 ${s.reserved}）`, `(จองให้ออเดอร์ ${s.reserved})`)}</span>` : ""}</td><td>${s.order_need}</td><td>${s.making}</td>
      <td>${s.suggest ? `<b>${s.suggest}</b>` : '<span class="muted">够了</span>'}</td>
      <td class="small">${s.suggest ? (s.suggest_after - Date.now() / 1000 < 3600 ? "现在（打印机有空）" : h.short(s.suggest_after) + " 以后（订单排完）") : ""}</td>
      <td>${s.suggest ? `<input type="number" min="1" value="${s.suggest}" style="width:64px" data-mkq="${esc(s.sku)}"> <button class="mini" data-mk="${esc(s.sku)}">生成备货任务</button>` : ""}</td></tr>`).join("")
      || '<tr><td colspan="11" class="muted">暂时没有建议（近 30 天销量不够多，或者库存已经够）</td></tr>';
    $("#st-table tbody").innerHTML = r.items.map((s) => `<tr><td class="mono" data-notr>${esc(s.sku)}</td><td data-notr>${esc(s.name || "")}</td><td>${h.colorTxt(s.color)}</td>
      <td><b>${s.qty}</b>${s.reserved ? ` <span class="small muted">${Z(`（订单占 ${s.reserved}，发货时扣）`, `(จองให้ออเดอร์ ${s.reserved} ตัดตอนส่ง)`)}</span>` : ""}</td><td>${s.target ?? '<span class="muted">自动</span>'}</td><td class="small">${fmtTime(s.updated_at)}</td></tr>`).join("")
      || '<tr><td colspan="6" class="muted">还没有成品库存</td></tr>';
    if (window.OPS && OPS.loadSkus) OPS.loadSkus();
  }
  $("#btn-stock-reload").addEventListener("click", (e) => busy(e.target, loadStock));
  $("#sg-table").addEventListener("click", async (e) => {
    const sku = e.target.dataset.mk;
    if (!sku) return;
    const q = +$(`[data-mkq="${CSS.escape(sku)}"]`).value;
    if (!q || !confirm(`生成备货任务：${sku} × ${q}？会排在订单任务后面。`)) return;
    try { await api("/api/stock/make", { json: { sku, qty: q } }); toast("已生成备货任务，在生产看板里"); loadStock(); } catch (err) { toast(err.message, true); }
  });
  $("#btn-st-save").addEventListener("click", (e) => busy(e.target, async () => {
    const sku = $("#st-sku").value.trim();
    if (!sku) throw new Error("请填写 SKU");
    await api("/api/stock", { json: { sku, qty: $("#st-qty").value === "" ? null : +$("#st-qty").value, target: $("#st-target").value } });
    toast("已保存"); loadStock();
  }));

  // ---------------- 质量统计 ----------------
  async function loadQuality() {
    const q = await api(`/api/quality?days=${$("#q-days").value}`);
    const h = H();
    $("#q-summary").innerHTML = `<div>打完<b>${q.runs_done}</b></div><div>失败<b class="${q.runs_failed ? "bad" : ""}">${q.runs_failed}</b></div>
      <div>失败率<b>${q.fail_rate == null ? "-" : q.fail_rate + "%"}</b></div><div>售后<b>${q.aftersales.total}</b></div>
      ${h.isOwner() ? `<div>售后退款<b>${h.money(q.aftersales.amount)}</b></div><div>售后总损失<b>${h.money(q.aftersales.loss || 0)}</b></div>` : ""}`;
    const t = (rows, f) => rows.map((r) => `<tr><td data-notr>${f ? f(r.k) : esc(r.k ?? "")}</td><td><b>${r.n}</b></td><td>${r.g != null ? h.num(r.g, 0) + " g" : (r.amt != null && h.isOwner() ? h.money(r.amt) : "")}</td></tr>`).join("") || '<tr><td class="muted">没有</td></tr>';
    $("#q-reason tbody").innerHTML = t(q.by_reason);
    $("#q-sku tbody").innerHTML = t(q.by_sku);
    $("#q-printer tbody").innerHTML = t(q.by_printer, (k) => esc(h.printerName(k)));
    $("#q-as tbody").innerHTML = t(q.aftersales.by_reason) + ((q.aftersales.by_resp || []).length ?
      '<tr><th colspan="3">按责任方</th></tr>' + q.aftersales.by_resp.map((r) => `<tr><td>${esc(r.label || "未判定")}</td><td><b>${r.n}</b></td>
        <td>${r.loss != null && h.isOwner() ? "损失 " + h.money(r.loss) : ""}</td></tr>`).join("") : "") +
      ((q.aftersales.by_printer || []).length ? '<tr><th colspan="3">生产责任的打印机</th></tr>' + q.aftersales.by_printer.map((r) =>
        `<tr><td class="mono" data-notr>${esc(r.k)}</td><td><b>${r.n}</b></td><td></td></tr>`).join("") : "");
    $("#q-recent tbody").innerHTML = q.recent.map((r) => `<tr><td class="nowrap">${fmtTime(r.ts)}</td><td data-notr>${esc(h.printerName(r.printer))}</td>
      <td class="mono" data-notr>${esc(r.sku || "")}</td><td>${esc(r.reason || "")}</td><td data-notr>${esc(r.note || "")}</td><td>${h.num(r.grams, 0)}</td><td data-notr>${esc(r.username || "")}</td></tr>`).join("")
      || '<tr><td colspan="7" class="muted">没有失败记录</td></tr>';
  }
  $("#q-days").addEventListener("change", loadQuality);

  // ---- 估算校准（v2.15）：用真实切片 / 打印数据校准克数、速度、空打阈值 ----
  async function loadCalib() {
    const box = $("#q-calib"); if (!box) return;
    let r;
    try { r = await api("/api/calib"); } catch (err) { box.innerHTML = `<p class="bad small">${esc(err.message)}</p>`; return; }
    const owner = H().isOwner();
    const num = (v, d = 2) => (v == null ? "—" : H().num(v, d));
    const sug = (v, key, d = 2) => (v == null ? `<span class="muted">${esc(TR("cal.not_enough"))}</span>` :
      `<label><input type="checkbox" data-cal="${key}" value="${v}" ${owner ? "" : "disabled"}> <b>${num(v, d)}</b></label>`);
    const fr = r.failures || {};
    const lvRow = (k) => { const x = fr[k] || {}; return `<tr><td>${esc(TR("cal.level." + k))}</td><td>${x.runs || 0}</td><td>${x.adhesion || 0}</td><td>${x.rate == null ? "—" : x.rate + "%"}</td></tr>`; };
    const th = r.risk || {};
    const tr = (r.times || []).filter((x) => x.n);
    box.innerHTML = `<h3>${esc(TR("cal.title"))}</h3><p class="small muted">${esc(TR("cal.intro", { n: r.min_n }))}</p>
      <div class="lanes two">
        <div><h4>${esc(TR("cal.grams"))}</h4><p class="small muted">${esc(TR("cal.grams_hint"))}</p>
          <table class="grid small"><thead><tr><th>${esc(TR("cal.col.material"))}</th><th>${esc(TR("cal.col.n"))}</th><th>${esc(TR("cal.col.now"))}</th><th>${esc(TR("cal.col.suggest"))}</th></tr></thead>
          <tbody>${(r.grams || []).map((g) => `<tr><td data-notr>${esc(g.material)}</td><td>${g.n}</td><td>${num(g.now, 3)}</td><td>${sug(g.suggest, "grams:" + g.material, 3)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">${esc(TR("cal.none"))}</td></tr>`}</tbody></table></div>
        <div><h4>${esc(TR("cal.speed"))}</h4>
          <table class="grid small"><thead><tr><th>${esc(TR("cal.col.printer"))}</th><th>${esc(TR("cal.col.n"))}</th><th>${esc(TR("cal.col.now"))}</th><th>${esc(TR("cal.col.suggest"))}</th></tr></thead>
          <tbody>${(r.speeds || []).map((x) => `<tr><td data-notr>${esc(x.code)} · ${esc(x.name)}</td><td>${x.n}</td><td>${num(x.now, 1)}</td><td>${sug(x.suggest, "speed:" + x.idx, 1)}</td></tr>`).join("")}</tbody></table></div>
      </div>
      ${owner ? `<button class="primary" data-cal-act="apply">${esc(TR("cal.apply"))}</button>` : `<p class="small muted">${esc(TR("cal.owner_only"))}</p>`}
      <h4>${esc(TR("cal.time"))}</h4>
      ${tr.length ? `<table class="grid small"><thead><tr><th>${esc(TR("cal.col.printer"))}</th><th>${esc(TR("cal.col.runs"))}</th><th>${esc(TR("cal.col.ratio"))}</th><th></th></tr></thead><tbody>${tr.map((x) =>
        `<tr><td data-notr>${esc(x.code)}</td><td>${x.n}</td><td>${num(x.ratio, 2)}</td><td class="small muted">${x.ratio ? esc(TR("cal.time_hint", { r: num(x.ratio, 2), dir: TR(x.ratio >= 1 ? "cal.slower" : "cal.faster"), p: Math.round(Math.abs(x.ratio - 1) * 100), n: x.n })) : ""}</td></tr>`).join("")}</tbody></table>`
        : `<p class="small muted">${esc(TR("cal.none"))}</p>`}
      <h4>${esc(TR("cal.risk"))}</h4><p class="small muted">${esc(TR("cal.risk_hint"))}</p>
      <table class="grid small"><thead><tr><th></th><th>${esc(TR("cal.col.runs"))}</th><th>${esc(TR("cal.col.fail"))}</th><th>${esc(TR("cal.col.rate"))}</th></tr></thead>
        <tbody>${["ok", "warn", "bad", "unknown"].map(lvRow).join("")}</tbody></table>
      ${r.risk_suggest ? `<p class="warn small">${esc(TR("cal.suggest", { why: r.risk_suggest.why, old: th.contact_warn, new: r.risk_suggest.contact_warn }))}</p>` : ""}
      <div class="form3 small">${["contact_bad", "contact_warn", "overhang_bad", "overhang_warn", "tall_warn", "tall_bad"].filter((k) => k in (r.risk_default || {})).map((k) => `<label>${esc(TR("cal.th." + k))}<input type="number" step="0.1" min="0" data-calth="${k}" value="${(r.risk_suggest && r.risk_suggest[k]) || th[k]}" ${owner ? "" : "disabled"}>
        <span class="muted">（${esc(TR("cal.col.now"))} ${th[k]}）</span></label>`).join("")}</div>
      ${owner ? `<div class="row gap"><button data-cal-act="risk">${esc(TR("cal.save_th"))}</button><button data-cal-act="risk-reset">${esc(TR("cal.reset_th"))}</button></div>` : ""}`;
  }
  $("#q-calib") && $("#q-calib").addEventListener("click", async (e) => {
    const a = e.target.dataset.calAct; if (!a) return;
    try {
      if (a === "apply") {
        const g = {}, sp = {};
        $$("#q-calib [data-cal]:checked").forEach((c) => { const [k, id] = c.dataset.cal.split(":"); (k === "grams" ? g : sp)[id] = +c.value; });
        if (!Object.keys(g).length && !Object.keys(sp).length) { toast(TR("cal.not_enough"), true); return; }
        if (Object.keys(g).length) await api("/api/calib/apply", { json: { kind: "grams", data: g } });
        if (Object.keys(sp).length) await api("/api/calib/apply", { json: { kind: "speed", data: sp } });
        toast(TR("cal.applied"));
      }
      if (a === "risk" || a === "risk-reset") {
        const d = {};
        $$("#q-calib [data-calth]").forEach((x) => (d[x.dataset.calth] = +x.value));
        await api("/api/calib/apply", { json: { kind: "risk", data: a === "risk" ? d : "reset" } });
        toast(TR("cal.applied_risk"));
      }
      loadCalib();
    } catch (err) { toast(err.message, true); }
  });


  // v2.27：打印机连接设置搬到 设置 → 生产（每台单独「✏ 修改」）
  async function connSettings(box) {
    if (!box) return;
    if (Object.entries(LOCKS).some(([k, v]) => k.startsWith("cfg-prconn-") && v.editing)) return;
    const h = H();
    const r = await api("/api/printers");
    box.innerHTML = `<h3>打印机连接</h3><p class="muted small">连上以后生产看板能看到实时状态、一键开始打印、打完自动记录。每台打印机单独修改。</p>` +
      (r.printers.map((p) => { const c = p.conn || {}, st = p.status || {};
        return `<div class="sub-card pr-conn" data-pi="${p.index}"><div class="row between"><b><span class="pcode" data-notr>${esc(p.code || "")}</span> <span data-notr>${esc(p.name)}</span></b>
          <span class="row gap">${h.stChip(st, p.status_zh)}<span class="lockbar pr-lockbar"></span></span></div>
        <div class="form2 pr-connform">
            <label>连接方式<select data-c="type">${Object.entries(CONN_ZH).map(([k, v]) => `<option value="${k}" ${k === (c.type || "none") ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
            <label>IP 地址<input data-c="host" value="${esc(c.host || "")}" placeholder="例如 192.168.31.50" data-notr></label>
            <label>序列号（拓竹）<input data-c="serial" value="${esc(c.serial || "")}" data-notr></label>
            <label>访问码（拓竹）<input data-c="access_code" type="password" autocomplete="new-password" value="${esc(c.access_code || "")}" data-notr></label>
            <label>端口（一般不用填）<input data-c="port" value="${esc(c.port || "")}" data-notr></label>
            <label class="row" style="align-self:end"><input type="checkbox" data-c="auto_complete" ${c.auto_complete === false ? "" : "checked"}> 打印机报告完成时自动记录</label>
          </div>
          <p class="muted small">拓竹：打印机屏幕 → 设置 → 网络（WLAN）里看 IP 和访问码，序列号在 设置 → 设备信息。新固件需要打开「局域网模式」和「开发者模式」才能由第三方软件发送打印。<br>
            Creality K1：屏幕 设置 → 网络 看 IP。原厂固件和 root 过的（Fluidd/Mainsail）都可以，选「自动识别」即可。</p>
            <div class="row gap"><button class="mini" data-ctest>测试连接</button></div></div>`; }).join("") || '<p class="muted">还没有打印机（在上面「打印机与 OrcaSlicer 配置文件」里添加）</p>');
    $$(".pr-conn", box).forEach((card) => {
      const i = card.dataset.pi, f = card.querySelector(".pr-connform");
      const id = "cfg-prconn-" + i;
      if (LOCKS[id]) LOCKS[id].editing = false;
      lockBox(f, { id, bar: card.querySelector(".pr-lockbar"), label: "✏ 修改",
        onCancel: () => { LOCKS[id].editing = false; connSettings(box); },
        onSave: async () => {
          const o = {}; f.querySelectorAll("[data-c]").forEach((x) => (o[x.dataset.c] = x.type === "checkbox" ? x.checked : x.value));
          await api(`/api/printers/${i}/conn`, { json: o }); toast("已保存");
          LOCKS[id].editing = false; setTimeout(() => connSettings(box), 100);
        } });
    });
    if (!box.dataset.bound) {
      box.dataset.bound = "1";
      box.addEventListener("click", async (e) => {
        const t = e.target; if (t.dataset.ctest === undefined) return;
        const card = t.closest("[data-pi]"), i = card.dataset.pi;
        const o = {}; card.querySelectorAll("[data-c]").forEach((x) => (o[x.dataset.c] = x.type === "checkbox" ? x.checked : x.value));
        try {
          if (LOCKS["cfg-prconn-" + i] && LOCKS["cfg-prconn-" + i].editing) await api(`/api/printers/${i}/conn`, { json: o });
          const r2 = await busy(t, () => api(`/api/printers/${i}/test`, { json: {} }));
          if (r2) toast(`连接成功：${CONN_ZH[r2.type] || r2.type}，状态：${r2.status_zh}`);
        } catch (err) { toast(err.message, true); }
      });
    }
  }
  window.PROD = { show, loadBoard, startDialog, connSettings };
})();
