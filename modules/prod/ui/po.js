"use strict";
// v2.54 生产单：数字卡片 → 图表 → 生产单表；点一张看每一行的进度 / 预计完成 / 用料和成本 / 专用打印机提醒；下达、暂停、取消、打印。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const E = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, d = 0) => (v == null || v === "" ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const tm = (t) => (t ? new Date(t * 1000).toLocaleString(TH() ? "th-TH" : "zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) : "—");
  const day = (t) => (t ? new Date(t * 1000).toLocaleDateString(TH() ? "th-TH" : "zh-CN", { month: "numeric", day: "numeric" }) : "—");
  const TONE = { draft: "", released: "info", producing: "info", partial: "warn", done: "ok", cancelled: "bad" };
  const stName = (o) => (TH() ? o.status_th : o.status_zh);
  const stChip = (o) => `<span class="po-st po-${o.status}">${E(stName(o))}</span>${o.paused ? ` <span class="po-st po-paused">⏸ ${E(Z("已暂停", "หยุดชั่วคราว"))}</span>` : ""}`;
  const srcName = (o) => (TH() ? o.source_th : o.source_zh);
  let ST = "active", Q = "", D = null, SG = null, TIMER = null;
  const canEdit = () => !window.ME || ME.role === "owner" || ME.role === "production";
  const prs = () => (typeof CFG !== "undefined" && CFG && CFG.printers) || [];
  const prCode = (i) => { const p = prs()[i]; return p ? (p.code || p.name) : "#" + (i + 1); };

  async function load() {
    const root = document.getElementById("po-root");
    if (!root) return;
    D = await api(`/api/porders?status=${ST === "all" ? "" : ST}&q=${encodeURIComponent(Q)}`);
    try { SG = await api("/api/porders/suggest"); } catch { SG = null; }       // v2.55 顶部「建议生产」卡片
    render();
    clearInterval(TIMER);
    TIMER = setInterval(() => { if (!document.hidden && root.isConnected && !root.closest(".hidden") && !document.querySelector("#modal:not(.hidden)")) load().catch(() => {}); }, 30000);
  }

  function bar(o) {
    return `<div class="po-bar" title="${o.done}/${o.qty}"><i class="${o.status === "done" ? "ok" : ""}" style="width:${o.pct}%"></i></div>`;
  }

  function render() {
    const root = document.getElementById("po-root");
    const c = D.counts, all = D.orders;
    const act = all.filter((o) => ["released", "producing", "partial"].includes(o.status));
    const late = act.filter((o) => o.late);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const doneToday = all.filter((o) => o.status === "done" && o.done_at >= today / 1000);
    const units = act.reduce((a, o) => a + (o.qty - o.done), 0);
    root.innerHTML = `
      <div class="row between wrap gap"><h2>${E(Z("生产单", "ใบสั่งผลิต"))}</h2>
        <div class="row gap wrap">${canEdit() ? `<button class="primary" id="po-new">➕ ${E(Z("新建生产单", "สร้างใบสั่งผลิต"))}</button>
          <button id="po-orders" title="${E(Z("把今天所有还没开始的订单任务归到一张单，方便一起看进度", "รวมงานออเดอร์วันนี้ที่ยังไม่เริ่มไว้ในใบเดียว"))}">📋 ${E(Z("今天订单汇总", "สรุปออเดอร์วันนี้"))}</button>` : ""}
          <button id="po-reload">${E(Z("刷新", "รีเฟรช"))}</button></div></div>
      <p class="muted small">${E(Z("生产单 = 一批要生产的成品。下达后变成打印任务，进度、预计完成、用料和成本都在这里；订单自己的打印任务不受影响。可以指定专用打印机。", "ใบสั่งผลิต = สินค้าชุดหนึ่งที่ต้องผลิต เมื่อสั่งผลิตจะกลายเป็นงานพิมพ์ ดูความคืบหน้า เวลาเสร็จ วัสดุและต้นทุนได้ที่นี่ งานพิมพ์ของออเดอร์ไม่ได้รับผลกระทบ กำหนดเครื่องพิมพ์เฉพาะได้"))}</p>
      ${canEdit() && SG ? (SG.products ? `<div class="po-sugcard"><div><b>💡 ${E(Z(`建议生产：${SG.products} 个产品`, `แนะนำให้ผลิต: ${SG.products} สินค้า`))}</b>
        <span class="small muted">${E(Z(`共 ${num(SG.units)} 件 · 按急迫程度排好，和「成品备货 → 一键补货」同一套算法`, `รวม ${num(SG.units)} ชิ้น เรียงตามความเร่งด่วน คำนวณแบบเดียวกับ「เติมสต็อกอัตโนมัติ」`))}</span></div>
        <button class="primary" id="po-sug">${E(Z("查看并新建", "ดูและสร้าง"))}</button></div>` : `<div class="small muted">✓ ${E(Z("现在没有需要补的成品。", "ตอนนี้ไม่มีสินค้าที่ต้องเติม"))}</div>`) : ""}
      ${UX.kpis([
        { label: Z("进行中", "กำลังดำเนินการ"), value: act.length, sub: Z(`还差 ${num(units)} 件`, `เหลือ ${num(units)} ชิ้น`), icon: "🏭" },
        { label: Z("草稿", "ฉบับร่าง"), value: c.draft || 0, tone: c.draft ? "warn" : "", sub: Z("还没下达", "ยังไม่สั่งผลิต") },
        { label: Z("暂停中", "หยุดชั่วคราว"), value: c.paused || 0, tone: c.paused ? "warn" : "" },
        { label: Z("可能来不及", "อาจไม่ทัน"), value: late.length, tone: late.length ? "bad" : "ok", help: Z("预计完成时间晚于交期", "เวลาคาดว่าเสร็จช้ากว่ากำหนดส่ง") },
        { label: Z("今天完成", "เสร็จวันนี้"), value: doneToday.length, tone: doneToday.length ? "ok" : "" },
      ])}
      <div class="inv-charts">
        ${UX.card({ title: Z("按状态", "ตามสถานะ"), body: UX.bars(["draft", "released", "producing", "partial", "done", "cancelled"].map((s) => ({ label: TH() ? STT[s][1] : STT[s][0], value: c[s] || 0, tone: TONE[s] === "info" ? "" : TONE[s] }))) })}
        ${UX.card({ title: Z("进行中的进度", "ความคืบหน้า"), body: UX.bars(act.slice(0, 8).map((o) => ({ label: o.no, raw: true, value: o.pct, text: `${o.done}/${o.qty}`, tone: o.late ? "bad" : "" })), { empty: Z("没有进行中的生产单", "ไม่มีใบสั่งผลิตที่กำลังทำ") }) })}
      </div>
      <div class="row gap wrap po-tools">${UX.tabs([["active", Z("进行中", "กำลังทำ"), (c.released || 0) + (c.producing || 0) + (c.partial || 0)], ["draft", Z("草稿", "ฉบับร่าง"), c.draft || 0], ["done", Z("完成", "เสร็จ"), c.done || 0], ["cancelled", Z("已取消", "ยกเลิก"), c.cancelled || 0], ["all", Z("全部", "ทั้งหมด")]], ST, "po-st")}
        <input id="po-q" type="search" placeholder="${E(Z("搜单号 / SKU / 备注", "ค้นหาเลขที่ / SKU / หมายเหตุ"))}" value="${E(Q)}" data-notr></div>
      <div class="gs-scroll"><table class="grid po-table"><thead><tr><th>${E(Z("单号", "เลขที่"))}</th><th>${E(Z("来源", "ที่มา"))}</th><th>${E(Z("状态", "สถานะ"))}</th><th>${E(Z("内容", "รายการ"))}</th>
        <th>${E(Z("进度", "ความคืบหน้า"))}</th><th>${E(Z("预计完成", "คาดว่าเสร็จ"))}</th><th>${E(Z("交期", "กำหนดส่ง"))}</th><th>${E(Z("打印机", "เครื่องพิมพ์"))}</th><th></th></tr></thead><tbody>
        ${all.map((o) => `<tr data-po="${o.id}" class="${o.paused ? "po-row-paused" : ""}">
          <td><a data-po-open="${o.id}" class="mono" data-notr><b>${E(o.no)}</b></a>${o.priority ? ` <span class="pill bad-pill">${E(Z("加急", "ด่วน"))}</span>` : ""}${o.note ? `<div class="small muted" data-notr>${E(o.note)}</div>` : ""}</td>
          <td>${E(srcName(o))}</td><td>${stChip(o)}</td>
          <td class="small"><span data-notr>${o.lines.slice(0, 3).map((l) => `${E(l.sku)} ×${l.qty}`).join("<br>")}</span>${o.lines.length > 3 ? `<br><span class="muted">${E(Z(`等 ${o.lines.length} 项`, `และอีก ${o.lines.length - 3} รายการ`))}</span>` : ""}</td>
          <td style="min-width:120px">${o.status === "draft" ? '<span class="muted">—</span>' : `${bar(o)}<span class="small">${o.done}/${o.qty}</span>`}</td>
          <td class="${o.late ? "gs-bad" : ""}">${o.status === "done" ? tm(o.done_at) : tm(o.eta)}${o.late ? " ⚠" : ""}</td>
          <td>${day(o.due)}</td>
          <td class="small" data-notr>${o.printer_idx.length ? o.printer_idx.map(prCode).join(", ") : '<span class="muted">—</span>'}</td>
          <td class="gs-act"><button class="mini" data-po-open="${o.id}">${E(Z("打开", "เปิด"))}</button> <a class="mini btn" href="/print/po/${o.id}${TH() ? "?lang=th" : ""}" target="_blank" title="${E(Z("打印生产单", "พิมพ์ใบสั่งผลิต"))}">🖨</a></td></tr>`).join("")
          || `<tr><td colspan="9" class="muted">${E(Z("还没有生产单。到「仓库 → 库存 → 成品备货」点「一键补货」，或者在这里新建。", "ยังไม่มีใบสั่งผลิต ไปที่「คลัง → สต็อก → เตรียมสต็อกสินค้า」กด「เติมสต็อกอัตโนมัติ」 หรือสร้างที่นี่"))}</td></tr>`}</tbody></table></div>`;
    document.getElementById("po-reload").onclick = (e) => busy(e.target, load);
    const n = document.getElementById("po-new"); if (n) n.onclick = () => editModal(null);
    const sg = document.getElementById("po-sug"); if (sg) sg.onclick = () => editModal(null, "sug");
    const so = document.getElementById("po-orders");
    if (so) so.onclick = (e) => busy(e.target, async () => {
      const o = await api("/api/porders/from-orders", { json: { scope: "today" } });
      toast(Z(`已生成 ${o.no}（${o.lines.length} 个 SKU）`, `สร้าง ${o.no} แล้ว (${o.lines.length} SKU)`)); await load(); openModal(o.id);
    });
    root.querySelector(".po-tools").onclick = (e) => { const b = e.target.closest("[data-ux-tab]"); if (b) { ST = b.dataset.uxTab; load().catch((x) => toast(x.message, true)); } };
    const q = document.getElementById("po-q");
    let t; q.oninput = () => { clearTimeout(t); t = setTimeout(() => { Q = q.value; load().catch(() => {}); }, 300); };
    root.querySelector(".po-table").onclick = (e) => { const b = e.target.closest("[data-po-open]"); if (b) openModal(+b.dataset.poOpen); };
  }
  const STT = { draft: ["草稿", "ฉบับร่าง"], released: ["已下达", "สั่งผลิตแล้ว"], producing: ["生产中", "กำลังผลิต"], partial: ["部分完成", "เสร็จบางส่วน"], done: ["完成", "เสร็จสิ้น"], cancelled: ["已取消", "ยกเลิก"] };

  // ---------------- 详情 ----------------
  async function openModal(id) {
    let o;
    try { o = await api("/api/porders/" + id); } catch (e) { toast(e.message, true); return; }
    const live = ["released", "producing", "partial"].includes(o.status);
    const m = MODAL.open(`<div class="row between"><h3><span class="mono" data-notr>${E(o.no)}</span> ${stChip(o)}${o.priority ? ` <span class="pill bad-pill">${E(Z("加急", "ด่วน"))}</span>` : ""}</h3><button class="mini" data-mclose>${E(Z("关闭", "ปิด"))}</button></div>
      <div class="small muted">${E(Z("来源", "ที่มา"))}：${E(srcName(o))} · ${E(Z("交期", "กำหนดส่ง"))}：${day(o.due)} · ${E(Z("预计完成", "คาดว่าเสร็จ"))}：${tm(o.eta)}${o.late ? ` <b class="gs-bad">⚠ ${E(Z("来不及", "ไม่ทัน"))}</b>` : ""}
        ${o.note ? `<br><span data-notr>${E(o.note)}</span>` : ""}</div>
      ${UX.kpis([{ label: Z("进度", "ความคืบหน้า"), value: `${o.done}/${o.qty}`, sub: o.pct + "%" }, { label: Z("用料", "วัสดุที่ใช้"), value: num(o.grams, 0) + " g" },
        { label: Z("成本", "ต้นทุน"), value: "฿" + num(o.cost, 0), help: Z("已完成件数 × 单件成本", "จำนวนที่เสร็จ × ต้นทุนต่อชิ้น") }])}
      ${(o.warnings || []).length ? `<div class="warnbox small">${o.warnings.map((w) => `⚠ ${E(TH() ? w.th : w.zh)}`).join("<br>")}</div>` : ""}
      <table class="grid small"><thead><tr><th>SKU</th><th>${E(Z("商品", "สินค้า"))}</th><th>${E(Z("数量", "จำนวน"))}</th><th>${E(Z("已完成", "เสร็จแล้ว"))}</th><th>${E(Z("预计完成", "คาดว่าเสร็จ"))}</th><th>${E(Z("用料", "วัสดุ"))}</th><th>${E(Z("成本", "ต้นทุน"))}</th></tr></thead><tbody>
      ${o.lines.map((l) => `<tr><td class="mono" data-notr>${E(l.sku)}</td><td data-notr>${E(l.name || "")} ${E(l.color || "")}</td><td>${l.qty}</td>
        <td style="min-width:110px">${o.status === "draft" ? "—" : `<div class="po-bar"><i class="${l.status === "done" ? "ok" : ""}" style="width:${l.pct}%"></i></div><span class="small">${l.done}/${l.qty}${l.printing ? " 🖨" : ""}</span>`}</td>
        <td>${l.eta ? tm(l.eta) : "—"}</td><td>${l.grams ? num(l.grams, 0) + " g" : "—"}</td><td>${l.cost ? "฿" + num(l.cost, 0) : "—"}</td></tr>`).join("")}</tbody></table>
      <p class="small muted">${E(Z("打完的成品：库存管理开了质检就先进「待检区」，合格再上架；没开直接入库上架。", "สินค้าที่พิมพ์เสร็จ: ถ้าเปิดการตรวจคุณภาพจะเข้าโซนรอตรวจก่อน ไม่เช่นนั้นเข้าสต็อกทันที"))}</p>
      ${canEdit() && o.status !== "done" && o.status !== "cancelled" ? `<div class="po-prs small"><b>${E(Z("专用打印机", "เครื่องพิมพ์เฉพาะ"))}</b>：${E(Z("不选 = 任何打印机；选了就只能用这几台。", "ไม่เลือก = เครื่องใดก็ได้ เลือกแล้วใช้เฉพาะเครื่องเหล่านี้"))}<br>
        ${prs().map((p, i) => `<label class="row" style="display:inline-flex;margin-right:10px"><input type="checkbox" data-pr="${i}" ${o.printer_idx.includes(i) ? "checked" : ""}> <span data-notr>${E(p.code || p.name)}</span></label>`).join("")}
        <button class="mini" id="po-prs-save">${E(Z("保存", "บันทึก"))}</button></div>` : ""}
      <div class="row gap wrap" style="margin-top:8px">
        ${canEdit() && o.status === "draft" ? `<button class="primary" data-act="release">▶ ${E(Z("下达（生成打印任务）", "สั่งผลิต (สร้างงานพิมพ์)"))}</button><button data-act="edit">✎ ${E(Z("改 SKU / 数量", "แก้ SKU / จำนวน"))}</button>` : ""}
        ${canEdit() && (live || o.status === "draft") ? (o.paused ? `<button data-act="resume">▶ ${E(Z("恢复", "ทำต่อ"))}</button>` : `<button data-act="pause">⏸ ${E(Z("暂停整张单", "หยุดทั้งใบ"))}</button>`) : ""}
        ${canEdit() && (live || o.status === "draft") ? `<button class="danger" data-act="cancel">${E(Z("取消整张单", "ยกเลิกทั้งใบ"))}</button>` : ""}
        <a class="btn" href="/print/po/${o.id}${TH() ? "?lang=th" : ""}" target="_blank">🖨 ${E(Z("打印生产单", "พิมพ์ใบสั่งผลิต"))}</a>
        ${live ? `<button data-act="board">${E(Z("去生产看板", "ไปบอร์ดผลิต"))}</button>` : ""}</div>`);
    const act = async (a) => {
      if (a === "board") { MODAL.close(); return goTab("production"); }
      if (a === "edit") { MODAL.close(); return editModal(o); }
      if (a === "cancel" && !confirm(Z(`取消 ${o.no}？还没开始打的任务会删掉（已经打好的成品不动）。`, `ยกเลิก ${o.no}? งานที่ยังไม่เริ่มจะถูกลบ (สินค้าที่พิมพ์เสร็จแล้วไม่เปลี่ยน)`))) return;
      await api(`/api/porders/${o.id}/${a}`, { json: {} });
      toast(Z("已完成", "เรียบร้อย")); MODAL.close(); await load(); openModal(o.id);
    };
    m.onclick = (e) => { const b = e.target.closest("[data-act]"); if (b) busy(b, () => act(b.dataset.act)); };
    const sv = m.querySelector("#po-prs-save");
    if (sv) sv.onclick = () => busy(sv, async () => {
      const pr = [...m.querySelectorAll("[data-pr]:checked")].map((x) => +x.dataset.pr);
      await api("/api/porders/" + o.id, { json: { printers: pr } });
      toast(Z("已保存", "บันทึกแล้ว")); MODAL.close(); await load(); openModal(o.id);
    });
  }

  // ---------------- 新建 / 改草稿：像逛产品库一样选产品（v2.55） ----------------
  // 左：页签「建议生产」（系统按急迫排好）/「全部产品」（按近 30 天销量排，可搜、可按类目 / 标签 / 状态筛，点开看规格）；右（手机在下）：已选清单 + 合计 + 交期等。
  async function editModal(o, tab0) {
    let SUG = [], PRD = { products: [], categories: [], tags: [] }, failed = false;
    const m0 = MODAL.open(`<p class="muted">${E(Z("加载中…", "กำลังโหลด…"))}</p>`);
    m0.classList.add("wide", "xwide");
    try { SUG = (await api("/api/porders/suggest")).items; } catch { failed = true; }
    try { PRD = await api("/api/porders/picker"); } catch { failed = true; }
    const INFO = {};                                     // SKU → 名称 / 规格 / 图 / 每件克数 / 机时
    PRD.products.forEach((p) => p.skus.forEach((s) => { INFO[s.sku] = { name: p.name, color: s.color, spec: s.spec, img: s.img || p.img, g: s.grams_each, h: s.hours_each }; }));
    SUG.forEach((s) => { INFO[s.sku] = Object.assign(INFO[s.sku] || {}, { name: s.name, color: s.color, spec: s.spec, img: s.img, g: s.grams_each, h: s.hours_each }); });
    const SEL = new Map();                               // SKU → 数量（保持加入顺序）
    if (o) o.lines.forEach((l) => { SEL.set(l.sku, l.qty); if (!INFO[l.sku]) INFO[l.sku] = { name: l.name, color: l.color }; });
    let tab = tab0 || (o ? "all" : (SUG.length ? "sug" : "all")), q = "", cat = "", tag = "", auto = "";
    const open = new Set();
    const nm = (s) => (INFO[s] && INFO[s].name) || s;
    const spec = (s) => [INFO[s] && INFO[s].color, INFO[s] && INFO[s].spec].filter(Boolean).join(" / ");
    const im = (u) => (u ? `<img class="pk-img" src="${E(u)}" loading="lazy" alt="">` : `<span class="pk-img pk-noimg"></span>`);
    const ctx = { prs: prs() };

    const m = MODAL.open(`<div class="row between"><h3>${E(o ? Z("改生产单 ", "แก้ใบสั่งผลิต ") + o.no : Z("新建生产单", "สร้างใบสั่งผลิต"))}</h3><button class="mini" data-mclose>${E(Z("关闭", "ปิด"))}</button></div>
      ${failed ? `<div class="warnbox small">${E(Z("产品数据没加载全，部分内容可能缺失。", "โหลดข้อมูลสินค้าไม่ครบ"))}</div>` : ""}
      <div class="pk-wrap"><div class="pk-left">
        ${UX.tabs([["sug", Z("建议生产", "แนะนำให้ผลิต"), SUG.length], ["all", Z("全部产品", "สินค้าทั้งหมด"), PRD.products.length]], tab, "pk-tab")}
        <div id="pk-filters" class="row gap wrap pk-filters"></div>
        <div id="pk-list" class="pk-list"></div></div>
      <div class="pk-right"><h4>${E(Z("已选", "ที่เลือก"))} <span id="pk-cnt" class="muted small"></span></h4>
        <div id="pk-sel" class="pk-sel"></div><div id="pk-tot" class="pk-tot"></div>
        <div class="form2" style="margin-top:8px"><label>${E(Z("交期", "กำหนดส่ง"))}<input type="date" id="po-due" value="${o && o.due ? new Date(o.due * 1000).toISOString().slice(0, 10) : ""}"></label>
          <label>${E(Z("备注", "หมายเหตุ"))}<input id="po-note" value="${E(o ? o.note || "" : "")}" data-notr></label>
          <label class="row"><input type="checkbox" id="po-pri" ${o && o.priority ? "checked" : ""}> ${E(Z("加急", "ด่วน"))}</label></div>
        <div class="po-prs small"><b>${E(Z("专用打印机", "เครื่องพิมพ์เฉพาะ"))}</b>：${E(Z("不选 = 任何打印机。", "ไม่เลือก = เครื่องใดก็ได้"))}<br>
          ${ctx.prs.map((p, i) => `<label class="row" style="display:inline-flex;margin-right:10px"><input type="checkbox" data-pr="${i}" ${o && o.printer_idx.includes(i) ? "checked" : ""}> <span data-notr>${E(p.code || p.name)}</span></label>`).join("") || `<span class="muted">—</span>`}</div>
        <div class="row gap wrap" style="margin-top:8px"><button class="primary" id="po-save">${E(o ? Z("保存", "บันทึก") : Z("保存为草稿", "บันทึกเป็นฉบับร่าง"))}</button>
          ${o ? "" : `<button id="po-save-rel">${E(Z("保存并下达", "บันทึกและสั่งผลิต"))}</button>`}<button data-mclose>${E(Z("取消", "ยกเลิก"))}</button></div></div></div>`);
    m.classList.add("wide", "xwide");

    const qtyIn = (sku, def) => `<input type="number" min="0" class="pk-q" data-sku="${E(sku)}" value="${SEL.has(sku) ? SEL.get(sku) : ""}" placeholder="${def == null ? "" : def}" style="width:74px">`;
    const sugRow = (s) => `<div class="pk-row ${s.level ? "lv-" + s.level : ""}" data-sku="${E(s.sku)}">
      <label class="pk-chk"><input type="checkbox" data-pk-chk="${E(s.sku)}" ${SEL.has(s.sku) ? "checked" : ""}></label>${im(s.img)}
      <div class="pk-info"><b data-notr>${E(s.name)}</b> <span class="muted small" data-notr>${E([s.color, s.spec].filter(Boolean).join(" / "))}</span> <span class="mono small muted" data-notr>${E(s.sku)}</span>
        <div class="pk-reason">${E(TH() ? s.reason_th : s.reason_zh)}</div>
        <div class="pk-nums small"><span>${E(Z("近7天", "7 วัน"))} <b>${s.sold7}</b></span><span>${E(Z("近30天", "30 วัน"))} <b>${s.sold30}</b></span><span>${E(Z("可售", "ขายได้"))} <b>${s.sellable}</b></span>
          <span>${E(Z("在做", "กำลังทำ"))} <b>${s.making}</b></span><span>${E(Z("目标", "เป้า"))} <b>${s.target}</b></span><span>${E(Z("缺口", "ขาด"))} <b>${s.gap}</b></span>
          <span>${E(Z("能卖", "พอขาย"))} <b>${s.cover_days == null ? "—" : s.cover_days + Z("天", " วัน")}</b></span>${s.per_plate > 1 ? `<span>${E(Z("每盘", "ต่อถาด"))} <b>${s.per_plate}</b></span>` : ""}</div></div>
      <div class="pk-qty"><span class="small muted">${E(Z("建议", "แนะนำ"))}</span> ${qtyIn(s.sku, s.qty)}</div></div>`;
    const prodRow = (p) => {
      const on = open.has(p.id), n = p.skus.filter((s) => SEL.has(s.sku)).length;
      return `<div class="pk-prod ${on ? "open" : ""}"><div class="pk-row pk-ph" data-pk-open="${E(p.id)}">${im(p.img)}
        <div class="pk-info"><b data-notr>${E(p.name)}</b> ${n ? `<span class="pill">${E(Z(`已选 ${n}`, `เลือก ${n}`))}</span>` : ""}
          <div class="pk-nums small"><span>${E(Z("近30天", "30 วัน"))} <b>${p.sold30}</b></span><span>${E(Z("近7天", "7 วัน"))} <b>${p.sold7}</b></span><span>${E(Z("可售", "ขายได้"))} <b>${p.sellable}</b></span>
            ${p.category ? `<span class="muted" data-notr>${E(p.category)}</span>` : ""}<span class="muted">${p.skus.length} SKU</span></div></div><span class="pk-arrow">${on ? "▾" : "▸"}</span></div>
        ${on ? `<div class="pk-skus">${p.skus.map((s) => `<div class="pk-row pk-sr" data-sku="${E(s.sku)}"><div class="pk-info"><b data-notr>${E([s.color, s.spec].filter(Boolean).join(" / ") || s.sku)}</b> <span class="mono small muted" data-notr>${E(s.sku)}</span>
          <div class="pk-nums small"><span>${E(Z("近7天", "7 วัน"))} <b>${s.sold7}</b></span><span>${E(Z("近30天", "30 วัน"))} <b>${s.sold30}</b></span><span>${E(Z("可售", "ขายได้"))} <b>${s.sellable}</b></span><span>${E(Z("在做", "กำลังทำ"))} <b>${s.making}</b></span></div></div>
          <div class="pk-qty">${qtyIn(s.sku)}</div></div>`).join("")}</div>` : ""}</div>`;
    };
    const filters = () => {
      const f = m.querySelector("#pk-filters");
      if (tab === "sug") { f.innerHTML = `<button class="mini" id="pk-addall">＋ ${E(Z("全部加入", "เพิ่มทั้งหมด"))}</button><button class="mini" id="pk-clr">${E(Z("取消全选", "ยกเลิกทั้งหมด"))}</button><span class="small muted">${E(Z("勾选后可改数量。数量 = 缺口（含订单还没打的）补到整盘。", "ติ๊กแล้วแก้จำนวนได้ จำนวน = ส่วนที่ขาด (รวมออเดอร์ที่ยังไม่พิมพ์) ปัดเป็นเต็มถาด"))}</span>`; return; }
      const A = [["", Z("全部", "ทั้งหมด")], ["hot", Z("有销量", "มียอดขาย")], ["below", Z("低于目标", "ต่ำกว่าเป้า")], ["out", Z("缺货", "ของหมด")], ["nosale", Z("没销量", "ไม่มียอดขาย")]];
      f.innerHTML = `<input id="pk-q" type="search" placeholder="${E(Z("搜产品 / SKU", "ค้นหาสินค้า / SKU"))}" value="${E(q)}" data-notr>
        <select id="pk-cat"><option value="">${E(Z("全部类目", "ทุกหมวด"))}</option>${PRD.categories.map((c) => `<option ${c === cat ? "selected" : ""} data-notr>${E(c)}</option>`).join("")}</select>
        <select id="pk-tag"><option value="">${E(Z("全部标签", "ทุกแท็ก"))}</option>${PRD.tags.map((t) => `<option value="${E(t.id)}" ${String(t.id) === tag ? "selected" : ""} data-notr>${E(t.name)}</option>`).join("")}</select>
        <span class="row gap wrap">${A.map(([k, t]) => `<button class="mini ${auto === k ? "primary" : ""}" data-pk-auto="${k}">${E(t)}</button>`).join("")}</span>`;
      const qi = f.querySelector("#pk-q"); let t; qi.oninput = () => { clearTimeout(t); t = setTimeout(() => { q = qi.value; list(); }, 200); };
      f.querySelector("#pk-cat").onchange = (e) => { cat = e.target.value; list(); };
      f.querySelector("#pk-tag").onchange = (e) => { tag = e.target.value; list(); };
    };
    const list = () => {
      const box = m.querySelector("#pk-list");
      if (tab === "sug") {
        box.innerHTML = SUG.map(sugRow).join("") || `<p class="muted">${E(Z("现在没有需要补的：库存都够目标，也没有订单等着打。可以到「全部产品」手动选。", "ตอนนี้ไม่มีรายการที่ต้องผลิต เลือกเองได้ที่「สินค้าทั้งหมด」"))}</p>`;
        return;
      }
      const kw = q.trim().toLowerCase();
      const ps = PRD.products.filter((p) => (!cat || p.category === cat) && (!tag || p.tags.includes(tag)) && (!auto || p.gk.includes(auto))
        && (!kw || (p.name + " " + p.id).toLowerCase().includes(kw) || p.skus.some((s) => s.sku.toLowerCase().includes(kw))));
      box.innerHTML = ps.map(prodRow).join("") || `<p class="muted">${E(Z("没有符合的产品。", "ไม่พบสินค้า"))}</p>`;
    };
    const num1 = (v, d = 1) => Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
    const totals = () => {
      let u = 0, g = 0, h = 0, unk = 0;
      SEL.forEach((qty, s) => { u += qty; const i = INFO[s] || {}; if (i.g) g += i.g * qty; else unk++; if (i.h) h += i.h * qty; });
      m.querySelector("#pk-cnt").textContent = SEL.size ? `(${SEL.size})` : "";
      m.querySelector("#pk-tot").innerHTML = SEL.size ? `<div class="pk-totline"><span>${E(Z("合计", "รวม"))}: <b>${SEL.size}</b> SKU · <b>${num(u)}</b> ${E(Z("件", "ชิ้น"))}</span>
        <span>${E(Z("预计用料", "วัสดุโดยประมาณ"))} <b>${num(g)}</b> g</span><span>${E(Z("预计机时", "ชั่วโมงเครื่อง"))} <b>${num1(h)}</b> h</span></div>${unk ? `<div class="small muted">${E(Z(`${unk} 个 SKU 没有克数 / 机时资料，没算进去`, `${unk} SKU ไม่มีข้อมูลกรัม / ชั่วโมง ไม่ได้รวม`))}</div>` : ""}` : "";
    };
    const selList = () => {
      m.querySelector("#pk-sel").innerHTML = [...SEL].map(([s, qty]) => { const i = INFO[s] || {}; return `<div class="pk-srow" data-sku="${E(s)}">${im(i.img)}
        <div class="pk-info"><b class="mono small" data-notr>${E(s)}</b><div class="small muted" data-notr>${E(nm(s))} ${E(spec(s))}</div>
          <div class="small muted">${i.g ? num(i.g * qty) + " g" : "—"} · ${i.h ? num1(i.h * qty) + " h" : "—"}</div></div>
        <input type="number" min="1" class="pk-sq" data-sku="${E(s)}" value="${qty}" style="width:70px"><button class="mini" data-pk-rm="${E(s)}">✕</button></div>`; }).join("")
        || `<p class="small muted">${E(Z("还没选。从左边勾选或填数量。", "ยังไม่ได้เลือก ติ๊กหรือกรอกจำนวนทางซ้าย"))}</p>`;
      totals();
    };
    const setQ = (sku, qty) => {
      if (qty > 0) SEL.set(sku, qty); else SEL.delete(sku);
    };
    const syncLeft = () => {          // 左边勾选 / 数量跟 SEL 对齐（不重画，保持焦点）
      m.querySelectorAll("#pk-list [data-pk-chk]").forEach((x) => { x.checked = SEL.has(x.dataset.pkChk); });
      m.querySelectorAll("#pk-list .pk-q").forEach((x) => { if (document.activeElement !== x) x.value = SEL.has(x.dataset.sku) ? SEL.get(x.dataset.sku) : ""; });
    };
    m.onclick = (e) => {
      const t = e.target;
      const tb = t.closest("[data-ux-tab]");
      if (tb && tb.closest("[data-ux-group='pk-tab']")) { tab = tb.dataset.uxTab; m.querySelectorAll("[data-ux-group='pk-tab'] [data-ux-tab]").forEach((x) => x.classList.toggle("on", x === tb)); filters(); list(); return; }
      const op = t.closest("[data-pk-open]");
      if (op && !t.closest("input")) { const id = op.dataset.pkOpen; open.has(id) ? open.delete(id) : open.add(id); list(); return; }
      const au = t.closest("[data-pk-auto]"); if (au) { auto = au.dataset.pkAuto; filters(); list(); return; }
      const rm = t.closest("[data-pk-rm]"); if (rm) { SEL.delete(rm.dataset.pkRm); selList(); syncLeft(); return; }
      if (t.closest("#pk-addall")) { SUG.forEach((s) => { if (!SEL.has(s.sku)) SEL.set(s.sku, s.qty); }); selList(); syncLeft(); return; }
      if (t.closest("#pk-clr")) { SUG.forEach((s) => SEL.delete(s.sku)); selList(); syncLeft(); }
    };
    m.onchange = (e) => {
      const t = e.target;
      if (t.dataset.pkChk) { const s = SUG.find((x) => x.sku === t.dataset.pkChk); if (t.checked) SEL.set(t.dataset.pkChk, SEL.get(t.dataset.pkChk) || (s ? s.qty : 1)); else SEL.delete(t.dataset.pkChk); selList(); syncLeft(); }
      else if (t.classList.contains("pk-q")) { setQ(t.dataset.sku, Math.floor(+t.value || 0)); selList(); syncLeft(); }
      else if (t.classList.contains("pk-sq")) { setQ(t.dataset.sku, Math.floor(+t.value || 0)); selList(); syncLeft(); }
    };
    m.oninput = (e) => {       // 边输入边更新合计（不重画列表，焦点不丢）
      const t = e.target;
      if (t.classList.contains("pk-sq") || t.classList.contains("pk-q")) {
        const n = Math.floor(+t.value || 0);
        if (n > 0) { SEL.set(t.dataset.sku, n); totals(); const ck = m.querySelector(`#pk-list [data-pk-chk="${CSS.escape(t.dataset.sku)}"]`); if (ck) ck.checked = true; }
      }
    };
    filters(); list(); selList();

    const save = (release) => async () => {
      const lines = [...SEL].map(([sku, qty]) => ({ sku, qty }));
      if (!lines.length) { toast(Z("还没选产品", "ยังไม่ได้เลือกสินค้า"), true); return; }
      const pr = [...m.querySelectorAll("[data-pr]:checked")].map((x) => { const p = ctx.prs[+x.dataset.pr] || {}; return p.id || p.code || +x.dataset.pr; });
      const body = { lines, due: m.querySelector("#po-due").value || null, note: m.querySelector("#po-note").value, priority: m.querySelector("#po-pri").checked ? 1 : 0, printers: pr, release };
      const r = o ? await api("/api/porders/" + o.id, { json: body }) : await api("/api/porders", { json: body });
      MODAL.close(); toast(Z("已保存 ", "บันทึกแล้ว ") + r.no); await load(); openModal(r.id);
    };
    m.querySelector("#po-save").onclick = (e) => busy(e.target, save(false));
    const sr = m.querySelector("#po-save-rel"); if (sr) sr.onclick = (e) => busy(e.target, save(true));
  }

  window.PO = { load, open: openModal, pick: editModal };
})();
