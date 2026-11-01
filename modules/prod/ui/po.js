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
  let ST = "active", Q = "", D = null, TIMER = null;
  const canEdit = () => !window.ME || ME.role === "owner" || ME.role === "production";
  const prs = () => (typeof CFG !== "undefined" && CFG && CFG.printers) || [];
  const prCode = (i) => { const p = prs()[i]; return p ? (p.code || p.name) : "#" + (i + 1); };

  async function load() {
    const root = document.getElementById("po-root");
    if (!root) return;
    D = await api(`/api/porders?status=${ST === "all" ? "" : ST}&q=${encodeURIComponent(Q)}`);
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

  // ---------------- 新建 / 改草稿 ----------------
  async function editModal(o) {
    let skus = [];
    try { skus = (await api("/api/inv/gs/products")).products.flatMap((p) => p.skus.map((s) => [s, p.name])); } catch { /* 仓库模块关了：手输 */ }
    const row = (sku = "", qty = 1) => `<tr><td><input class="po-sku mono" list="po-skus" value="${E(sku)}" placeholder="SKU" data-notr style="width:170px"></td>
      <td><input type="number" min="1" class="po-qty" value="${qty}" style="width:80px"></td><td><button class="mini" data-rm>✕</button></td></tr>`;
    const m = MODAL.open(`<div class="row between"><h3>${E(o ? Z("改生产单 ", "แก้ใบสั่งผลิต ") + o.no : Z("新建生产单", "สร้างใบสั่งผลิต"))}</h3><button class="mini" data-mclose>${E(Z("关闭", "ปิด"))}</button></div>
      <datalist id="po-skus">${skus.map(([s, n]) => `<option value="${E(s)}">${E(n)}</option>`).join("")}</datalist>
      <table class="grid small"><thead><tr><th>SKU</th><th>${E(Z("数量", "จำนวน"))}</th><th></th></tr></thead><tbody id="po-lines">${o ? o.lines.map((l) => row(l.sku, l.qty)).join("") : row()}</tbody></table>
      <button class="mini" id="po-addrow">＋ ${E(Z("加一行", "เพิ่มแถว"))}</button>
      <div class="form2" style="margin-top:8px"><label>${E(Z("交期", "กำหนดส่ง"))}<input type="date" id="po-due" value="${o && o.due ? new Date(o.due * 1000).toISOString().slice(0, 10) : ""}"></label>
        <label>${E(Z("备注", "หมายเหตุ"))}<input id="po-note" value="${E(o ? o.note || "" : "")}" data-notr></label>
        <label class="row"><input type="checkbox" id="po-pri" ${o && o.priority ? "checked" : ""}> ${E(Z("加急", "ด่วน"))}</label></div>
      <div class="row gap"><button class="primary" id="po-save">${E(o ? Z("保存", "บันทึก") : Z("保存为草稿", "บันทึกเป็นฉบับร่าง"))}</button>
        ${o ? "" : `<button id="po-save-rel">${E(Z("保存并下达", "บันทึกและสั่งผลิต"))}</button>`}<button data-mclose>${E(Z("取消", "ยกเลิก"))}</button></div>`);
    const lines = () => [...m.querySelectorAll("#po-lines tr")].map((tr) => ({ sku: tr.querySelector(".po-sku").value.trim(), qty: +tr.querySelector(".po-qty").value || 0 })).filter((l) => l.sku);
    m.querySelector("#po-addrow").onclick = () => m.querySelector("#po-lines").insertAdjacentHTML("beforeend", row());
    m.querySelector("#po-lines").onclick = (e) => { if (e.target.dataset.rm !== undefined) { e.target.closest("tr").remove(); } };
    const save = (release) => async () => {
      const body = { lines: lines(), due: m.querySelector("#po-due").value || null, note: m.querySelector("#po-note").value, priority: m.querySelector("#po-pri").checked ? 1 : 0, release };
      const r = o ? await api("/api/porders/" + o.id, { json: body }) : await api("/api/porders", { json: body });
      MODAL.close(); toast(Z("已保存 ", "บันทึกแล้ว ") + r.no); await load(); openModal(r.id);
    };
    m.querySelector("#po-save").onclick = (e) => busy(e.target, save(false));
    const sr = m.querySelector("#po-save-rel"); if (sr) sr.onclick = (e) => busy(e.target, save(true));
  }

  window.PO = { load, open: openModal };
})();
