"use strict";
// 库存同步（v2.53）：商品 → 上架 →「库存同步」页签。数字卡片 → 图表 → 库存对照总表（SKU × 店铺）；同步记录；待导出；规则。
// 数据来自 /api/stocksync/*（modules/listing/stocksync.py）。文字用 Z(中文, 泰文)。
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const E = (s) => (window.UX ? UX.esc(s) : String(s == null ? "" : s));
  const SS = { view: "matrix", kpi: "", shop: "", q: "", data: null, sel: new Set() };
  const STATUS = { synced: ["已同步", "ซิงก์แล้ว", "ok"], pending: ["待同步", "รอซิงก์", "warn"], failed: ["同步失败", "ซิงก์ไม่สำเร็จ", "bad"],
    locked: ["已锁定", "ล็อกอยู่", "info"], delisted: ["平台已下架", "ลงขายถูกปิดบนแพลตฟอร์ม", "bad"] };
  const REASON = { ship: ["出货", "ส่งของ"], in: ["入库", "รับเข้า"], produce: ["生产完成", "ผลิตเสร็จ"], manual: ["手动", "ด้วยมือ"], timer: ["定时", "ตามเวลา"],
    rule: ["规则变更", "เปลี่ยนกฎ"], event: ["库存变化", "สต็อกเปลี่ยน"] };
  const rz = (k) => Z(...(REASON[k] || [k, k]));
  const dt = (t) => (t ? new Date(t * 1000).toLocaleString("sv").slice(5, 16) : "—");
  const root = () => $("#ss-root");

  function frame() {
    const r = root();
    if (!r) return null;
    if (!r.dataset.built) {
      r.dataset.built = "1";
      r.innerHTML = `<div class="row between wrap" style="margin-bottom:8px"><div class="ux-tabs" id="ss-tabs"></div>
        <div class="row gap wrap"><select id="ss-shop" class="small" style="width:auto"></select>
        <input id="ss-q" class="small" style="width:180px" placeholder="${E(Z("搜索 SKU / 产品", "ค้นหา SKU / สินค้า"))}">
        <button class="mini primary-lite" id="ss-check" title="${E(Z("立即拉平台库存、对照、推待同步的", "ดึงสต็อกจากแพลตฟอร์ม เทียบ และส่งที่รอซิงก์ทันที"))}">🔄 ${E(Z("立即检查", "ตรวจสอบทันที"))}</button>
        <button class="mini" id="ss-pushall">⚡ ${E(Z("一键全部重推", "ส่งใหม่ทั้งหมด"))}</button>
        <button class="mini" id="ss-rules">⚙ ${E(Z("默认规则", "กฎเริ่มต้น"))}</button></div></div>
        <div id="ss-body"></div>`;
    }
    $("#ss-tabs").innerHTML = ["matrix", "log", "export"].map((k) => `<button class="ux-tab ${SS.view === k ? "on" : ""}" data-ss-view="${k}">${E(
      { matrix: Z("库存对照总表", "ตารางเทียบสต็อก"), log: Z("同步记录", "ประวัติซิงก์"), export: Z("待导出", "รอส่งออก") }[k])}</button>`).join("");
    return r;
  }

  async function load() {
    if (!frame()) return;
    if (SS.view === "log") return loadLog();
    if (SS.view === "export") return loadExport();
    const body = $("#ss-body");
    let d;
    try { d = await api(`/api/stocksync/matrix?kpi=${SS.kpi}&shop=${SS.shop}&q=${encodeURIComponent(SS.q)}`); }
    catch (e) { body.innerHTML = `<span class="bad">${E(e.message)}</span>`; return; }
    SS.data = d;
    const sel = $("#ss-shop");
    sel.innerHTML = `<option value="">${E(Z("全部店铺", "ทุกร้าน"))}</option>` + d.shops.map((s) => `<option value="${s.id}" data-notr ${String(s.id) === String(SS.shop) ? "selected" : ""}>${E(s.name)} ${s.api ? "" : "(" + Z("导出", "ส่งออก") + ")"}</option>`).join("");
    body.innerHTML = kpiHtml(d) + chartsHtml(d) + tableHtml(d) + `<div id="ss-bar" class="ss-bar hidden"></div>`;
    syncBar();
  }

  function kpiHtml(d) {
    const k = d.kpi, on = (x) => (SS.kpi === x ? "ss-kpi-on" : "");
    return UX.kpis([
      { label: Z("待同步", "รอซิงก์"), value: k.pending, tone: k.pending ? "warn" : "ok", go: "ss:pending", sub: Z("系统可售和平台不一样", "ต่างจากแพลตฟอร์ม") },
      { label: Z("同步失败", "ซิงก์ไม่สำเร็จ"), value: k.failed, tone: k.failed ? "bad" : "ok", go: "ss:failed", sub: Z("看原因，可重试", "ดูสาเหตุ ลองใหม่ได้") },
      { label: Z("对不上", "ไม่ตรงกัน"), value: k.mismatch, tone: k.mismatch ? "warn" : "ok", go: "ss:mismatch", sub: Z("平台显示和系统不符", "แพลตฟอร์มแสดงไม่ตรงระบบ") },
      { label: Z("快卖完", "ใกล้หมด"), value: k.low, tone: k.low ? "warn" : "ok", go: "ss:low", sub: Z("可售很少或撑不了几天", "เหลือน้อยหรือขายได้ไม่กี่วัน") },
      { label: Z("已超卖", "ขายเกินสต็อก"), value: k.oversold, tone: k.oversold ? "bad" : "ok", go: "ss:oversold", sub: Z("待发货比库存+能做的多", "ออเดอร์รอส่งมากกว่าสต็อก+ที่ผลิตได้") },
    ]).replace(/class="ux-kpi /g, (m) => m) + (SS.kpi ? `<p class="small"><b>${E(Z("已筛选", "กรองอยู่"))}</b>：${E(({ pending: Z("待同步", "รอซิงก์"), failed: Z("同步失败", "ซิงก์ไม่สำเร็จ"), mismatch: Z("对不上", "ไม่ตรงกัน"), low: Z("快卖完", "ใกล้หมด"), oversold: Z("已超卖", "ขายเกินสต็อก") })[SS.kpi] || SS.kpi)}
      <a href="#" id="ss-clear">${E(Z("清除筛选", "ล้างตัวกรอง"))}</a></p>` : "");
  }

  function chartsHtml(d) {
    const cnt = {};
    d.rows.forEach((r) => Object.values(r.cells).forEach((c) => { cnt[c.status] = (cnt[c.status] || 0) + 1; }));
    const bars = Object.keys(STATUS).filter((k) => cnt[k]).map((k) => ({ label: Z(STATUS[k][0], STATUS[k][1]), value: cnt[k], tone: STATUS[k][2] === "info" ? "" : STATUS[k][2] }));
    const tr = d.trend || [];
    const cols = tr.length && tr.some((x) => x.n) ? UX.columns(tr.map((x) => ({ label: x.day, value: x.n, tone: x.fail ? "warn" : "", text: Z(`${x.n} 次`, `${x.n} ครั้ง`) })), { h: 70, from: tr[0].day.slice(5), to: tr[tr.length - 1].day.slice(5) }) : UX.empty(Z("近 7 天没有推送", "7 วันที่ผ่านมาไม่มีการส่ง"));
    return `<div class="ss-charts"><div class="card"><b class="small">${E(Z("各状态的 SKU×店铺", "สถานะ SKU×ร้าน"))}</b>${UX.bars(bars, { empty: Z("还没有数据", "ยังไม่มีข้อมูล") })}</div>
      <div class="card"><b class="small">${E(Z("近 7 天推送次数", "จำนวนการส่ง 7 วัน"))}</b>${cols}</div></div>`;
  }

  function tableHtml(d) {
    if (!d.rows.length) return `<div class="card">${UX.empty(Z("没有 SKU：产品导出 / 推送过、或在线商品对上了 ERP 之后才会出现在这里", "ยังไม่มี SKU: จะแสดงหลังส่งออก/ส่งสินค้าหรือผูกกับสินค้าออนไลน์แล้ว"))}</div>`;
    const shops = d.shops.filter((s) => !SS.shop || String(s.id) === String(SS.shop) ).filter((s) => d.rows.some((r) => r.cells[s.id]));
    const head1 = `<tr><th rowspan="2"><input type="checkbox" id="ss-all"></th><th rowspan="2">SKU</th><th rowspan="2">${E(Z("产品", "สินค้า"))}</th><th rowspan="2" class="r">${E(Z("库存/占用", "สต็อก/จอง"))}</th>` +
      shops.map((s) => `<th colspan="5" class="ss-shop" data-notr>${E(s.name)} <span class="muted small">${s.api ? "API" : Z("导出", "ส่งออก")}</span></th>`).join("") + `</tr>`;
    const sub = shops.map(() => ["系统可售|ระบบขายได้", "平台显示|แพลตฟอร์ม", "差异|ต่าง", "上次同步|ซิงก์ล่าสุด", "状态|สถานะ"].map((x) => { const [a, b] = x.split("|"); return `<th class="r small">${E(Z(a, b))}</th>`; }).join("")).join("");
    const rows = d.rows.map((r) => {
      const cs = shops.map((s) => {
        const c = r.cells[s.id];
        if (!c) return `<td colspan="5" class="muted small">—</td>`;
        const st = STATUS[c.status] || [c.status, c.status, ""];
        const diff = c.diff == null ? "—" : (c.diff > 0 ? "+" : "") + c.diff;
        const hint = r.virtual || c.virt ? ` title="${E(Z(`实物 ${c.phys} + 虚拟(按需打印) ${c.virt}`, `ของจริง ${c.phys} + เสมือน(ผลิตตามสั่ง) ${c.virt}`))}"` : "";
        return `<td class="r"${hint}><input type="number" min="0" class="ss-in ${c.locked ? "ss-locked" : ""}" value="${c.target}" data-sku="${E(r.sku)}" data-shop="${s.id}" data-old="${c.target}"></td>
          <td class="r">${c.platform == null ? '<span class="muted">—</span>' : `<b class="${c.mismatch ? "bad" : ""}">${c.platform}</b>`}</td>
          <td class="r ${c.diff ? (c.mismatch ? "bad" : "warn") : "muted"}">${diff}</td>
          <td class="small muted">${c.last == null ? "—" : c.last}<br>${dt(c.last_at)}</td>
          <td><span class="ss-st ss-${st[2]}" ${c.error ? `title="${E(c.error)}"` : ""}>${E(Z(st[0], st[1]))}</span>${c.paused ? ` <span class="small bad">${E(Z("停售", "หยุดขาย"))}</span>` : ""}
            ${c.error ? `<div class="small bad ss-err" data-notr>${E(c.error)}</div>` : ""}
            <button class="mini ss-lock" data-sku="${E(r.sku)}" data-shop="${s.id}" data-lock="${c.locked ? "" : c.target}" title="${E(c.locked ? Z("解锁", "ปลดล็อก") : Z("锁定这个数，自动同步不会改", "ล็อกจำนวนนี้ ซิงก์อัตโนมัติจะไม่แก้"))}">${c.locked ? "🔒" : "🔓"}</button>
            <button class="mini ss-rule" data-sku="${E(r.sku)}" data-shop="${s.id}" data-pid="${E(r.product_id)}" title="${E(Z("这个 SKU / 产品的规则", "กฎของ SKU / สินค้านี้"))}">⚙</button></td>`;
      }).join("");
      const flag = (r.oversold ? `<span class="ss-st ss-bad">${E(Z("超卖", "ขายเกิน"))}</span> ` : "") + (r.low ? `<span class="ss-st ss-warn">${E(Z("快卖完", "ใกล้หมด"))}</span>` : "");
      return `<tr><td><input type="checkbox" class="ss-pick" data-sku="${E(r.sku)}" ${SS.sel.has(r.sku) ? "checked" : ""}></td><td class="mono" data-notr data-p360="${E(r.sku)}">${E(r.sku)}</td>
        <td data-notr class="ss-name">${E(r.name)} <span class="muted small">${E(r.color)} ${E(r.spec)}</span><div>${flag}</div></td>
        <td class="r">${r.on_hand}<span class="muted small"> / ${r.reserved}</span>${r.units != null ? `<div class="muted small">${E(Z(`耗材可做 ${r.units}`, `วัสดุผลิตได้ ${r.units}`))}</div>` : ""}</td>${cs}</tr>`;
    }).join("");
    return `<div class="ss-wrap"><table class="grid small ss-table"><thead>${head1}<tr>${sub}</tr></thead><tbody>${rows}</tbody></table></div>
      ${d.total > d.rows.length ? `<p class="small bad">${E(Z(`只显示前 ${d.rows.length} 个（共 ${d.total}），请用搜索 / 筛选缩小范围`, `แสดง ${d.rows.length} แรก (ทั้งหมด ${d.total}) กรุณาค้นหา / กรอง`))}</p>` : ""}
      <p class="small muted">${E(Z("系统可售 = 成品库存 − 订单占住 − 安全库存（+ 按需打印虚拟库存）；改数字后按 Enter 马上推到平台（没接口的店铺记进「待导出」）。🔒 锁定后自动同步不会改这个数。", "ขายได้ของระบบ = สต็อกสำเร็จรูป − จอง − สต็อกกันชน (+ สต็อกเสมือนผลิตตามสั่ง) แก้ตัวเลขแล้วกด Enter เพื่อส่งทันที (ร้านไม่มี API จะเข้า “รอส่งออก”) 🔒 ล็อกแล้วซิงก์อัตโนมัติจะไม่แก้"))}</p>`;
  }

  function syncBar() {
    const bar = $("#ss-bar");
    if (!bar) return;
    bar.classList.toggle("hidden", !SS.sel.size);
    if (!SS.sel.size) return;
    bar.innerHTML = `<b>${E(Z(`已选 ${SS.sel.size} 个 SKU`, `เลือก ${SS.sel.size} SKU`))}</b>` +
      [["push", "推送", "ส่ง"], ["recalc", "按规则重算", "คำนวณตามกฎ"], ["safety", "设安全库存", "ตั้งสต็อกกันชน"], ["alloc", "改分配", "แก้การแบ่ง"], ["zero", "设 0（临时停售）", "ตั้งเป็น 0 (หยุดขายชั่วคราว)"],
        ["resume", "恢复", "กลับมาขาย"], ["lock", "锁定", "ล็อก"], ["unlock", "解锁", "ปลดล็อก"]].map(([k, a, b]) => `<button class="mini" data-ss-bulk="${k}">${E(Z(a, b))}</button>`).join("") +
      `<button class="mini" id="ss-sel-clear">${E(Z("清除", "ล้าง"))}</button>`;
  }

  async function bulk(action) {
    const cells = [...SS.sel].map((s) => ({ sku: s, shop_id: SS.shop || null }));
    const params = {};
    if (action === "safety") { const v = prompt(Z("安全库存（件）", "สต็อกกันชน (ชิ้น)"), "2"); if (v == null) return; params.safety = +v; }
    if (action === "alloc") {
      const a = prompt(Z("分配方式：share 全部显示 / percent 按比例 / fixed 固定件数", "รูปแบบ: share / percent / fixed"), "percent"); if (!a) return;
      params.alloc = a; if (a !== "share") { const v = prompt(a === "percent" ? Z("百分比（%）", "เปอร์เซ็นต์ (%)") : Z("固定件数", "จำนวนคงที่"), "50"); if (v == null) return; params.alloc_val = +v; }
      params.per_shop = !!SS.shop;
    }
    if (action === "lock") { const v = prompt(Z("锁定为（件）", "ล็อกไว้ที่ (ชิ้น)"), "0"); if (v == null) return; params.qty = +v; }
    if (action === "zero" && !confirm(Z("把选中的 SKU 在平台上改成 0（临时停售）？", "ตั้งสต็อกเป็น 0 บนแพลตฟอร์ม (หยุดขายชั่วคราว)?"))) return;
    try {
      const r = await api("/api/stocksync/bulk", { json: { action, cells, params } });
      toast(r.pushed != null ? Z(`已推送 ${r.pushed}，失败 ${r.failed}，跳过 ${r.skipped}`, `ส่งแล้ว ${r.pushed} ล้มเหลว ${r.failed} ข้าม ${r.skipped}`) : Z("已完成", "เสร็จแล้ว"), !!r.failed);
      load();
    } catch (e) { toast(e.message, true); }
  }

  async function editQty(inp) {
    const qty = inp.value;
    if (qty === inp.dataset.old || qty === "") return;
    try {
      const r = await api("/api/stocksync/edit", { json: { sku: inp.dataset.sku, shop_id: +inp.dataset.shop, qty: +qty } });
      toast(r.export ? Z("已记下，等导出", "บันทึกแล้ว รอส่งออก") : Z("已推送到平台", "ส่งไปแพลตฟอร์มแล้ว"));
    } catch (e) { toast(e.message, true); }
    load();
  }

  // ---------- 规则弹窗 ----------
  async function ruleDialog(scope, key, shopId, title) {
    let cur = {}, df = {};
    try { const r = await api(`/api/stocksync/rules?scope=${scope}&key=${encodeURIComponent(key)}&shop_id=${shopId || 0}`); cur = r.rule || {}; df = r.defaults || {}; } catch (e) { return toast(e.message, true); }
    const m = document.createElement("div");
    m.className = "ss-modal";
    const opt = (v, zh, th, sel) => `<option value="${v}" ${sel === v ? "selected" : ""}>${E(Z(zh, th))}</option>`;
    m.innerHTML = `<div class="ss-dlg"><h3 data-notr>${E(title)}</h3>
      <p class="small muted">${E(Z("留空 = 用上一级 / 全局默认", "เว้นว่าง = ใช้ค่าระดับบน / ค่าเริ่มต้น"))}（${E(Z("全局默认：安全库存", "ค่าเริ่มต้น: สต็อกกันชน"))} ${df.safety}，${E(Z("虚拟上限", "เพดานเสมือน"))} ${df.cap}）</p>
      <label class="small">${E(Z("安全库存", "สต็อกกันชน"))}<input id="rl-safety" type="number" min="0" value="${cur.safety ?? ""}"></label>
      <label class="small">${E(Z("分配方式", "การแบ่งสต็อก"))}<select id="rl-alloc"><option value="">—</option>${opt("share", "全部显示", "แสดงทั้งหมด", cur.alloc)}${opt("percent", "按比例 %", "ตามเปอร์เซ็นต์ %", cur.alloc)}${opt("fixed", "固定件数", "จำนวนคงที่", cur.alloc)}</select></label>
      <label class="small">${E(Z("比例 % / 固定件数", "% / จำนวนคงที่"))}<input id="rl-val" type="number" min="0" value="${cur.alloc_val ?? ""}"></label>
      <label class="small">${E(Z("按需打印虚拟库存", "สต็อกเสมือน (ผลิตตามสั่ง)"))}<select id="rl-virtual"><option value="">${E(Z("跟随产品设置", "ตามการตั้งค่าสินค้า"))}</option>${opt("on", "开", "เปิด", cur.virtual)}${opt("off", "关", "ปิด", cur.virtual)}</select></label>
      <label class="small">${E(Z("虚拟库存上限", "เพดานสต็อกเสมือน"))}<input id="rl-cap" type="number" min="0" value="${cur.cap ?? ""}"></label>
      <div class="row gap"><button class="mini primary-lite" id="rl-ok">${E(Z("保存", "บันทึก"))}</button><button class="mini" id="rl-x">${E(Z("取消", "ยกเลิก"))}</button></div></div>`;
    document.body.appendChild(m);
    m.querySelector("#rl-x").onclick = () => m.remove();
    m.querySelector("#rl-ok").onclick = async () => {
      const g = (id) => m.querySelector(id).value;
      const num = (v) => (v === "" ? null : +v);
      try {
        const r = await api("/api/stocksync/rules", { json: { scope, key, shop_id: shopId || 0, data: { safety: num(g("#rl-safety")), alloc: g("#rl-alloc") || null, alloc_val: num(g("#rl-val")), virtual: g("#rl-virtual") || null, cap: num(g("#rl-cap")) } } });
        toast(Z(`规则已保存；推送 ${r.sync.pushed} 个`, `บันทึกกฎแล้ว ส่ง ${r.sync.pushed} รายการ`)); m.remove(); load();
      } catch (e) { toast(e.message, true); }
    };
  }

  // ---------- 同步记录 ----------
  async function loadLog() {
    const body = $("#ss-body");
    const f = SS.logf || (SS.logf = { sku: "", reason: "", result: "" });
    let d;
    try { d = await api(`/api/stocksync/log?sku=${encodeURIComponent(f.sku)}&reason=${f.reason}&result=${f.result}&shop=${SS.shop}`); } catch (e) { body.innerHTML = `<span class="bad">${E(e.message)}</span>`; return; }
    const items = d.items;
    const failed = items.filter((x) => !x.ok).length;
    const sel = (id, v, opts) => `<select id="${id}" class="small" style="width:auto">${opts.map(([k, a, b]) => `<option value="${k}" ${v === k ? "selected" : ""}>${E(Z(a, b))}</option>`).join("")}</select>`;
    body.innerHTML = UX.kpis([{ label: Z("记录数", "จำนวนบันทึก"), value: items.length }, { label: Z("失败", "ล้มเหลว"), value: failed, tone: failed ? "bad" : "ok" }]) +
      `<div class="row gap wrap" style="margin:8px 0"><input id="lg-sku" class="small" placeholder="SKU" value="${E(f.sku)}" style="width:160px">
        ${sel("lg-reason", f.reason, [["", "全部原因", "ทุกเหตุผล"], ...Object.keys(REASON).map((k) => [k, REASON[k][0], REASON[k][1]])])}
        ${sel("lg-result", f.result, [["", "全部结果", "ทุกผลลัพธ์"], ["ok", "成功", "สำเร็จ"], ["fail", "失败", "ล้มเหลว"]])}
        <button class="mini" id="lg-retry" ${failed ? "" : "disabled"}>↻ ${E(Z("重试失败的", "ลองใหม่ที่ล้มเหลว"))}</button></div>` +
      (items.length ? `<table class="grid small"><thead><tr><th>${E(Z("时间", "เวลา"))}</th><th>SKU</th><th>${E(Z("店铺", "ร้าน"))}</th><th class="r">${E(Z("变化", "เปลี่ยน"))}</th><th>${E(Z("原因", "เหตุผล"))}</th><th>${E(Z("结果", "ผลลัพธ์"))}</th></tr></thead><tbody>` +
        items.map((x) => `<tr><td class="muted">${dt(x.ts)}</td><td class="mono" data-notr data-p360="${E(x.sku)}">${E(x.sku)}</td><td data-notr>${E(x.shop)}</td>
          <td class="r">${x.old == null ? "—" : x.old} → <b>${x.new == null ? "—" : x.new}</b></td><td>${E(rz(x.reason))}</td>
          <td class="${x.ok ? "ok" : "bad"}" data-notr>${x.ok ? "✔ " + E(x.result === "ok" ? "" : x.result) : "✗ " + E(x.result)}</td></tr>`).join("") + "</tbody></table>" : UX.empty(Z("没有记录", "ไม่มีบันทึก")));
  }

  // ---------- 待导出 ----------
  async function loadExport() {
    const body = $("#ss-body");
    let shops;
    try { shops = (await api("/api/stocksync/matrix")).shops.filter((s) => !s.api); } catch (e) { body.innerHTML = `<span class="bad">${E(e.message)}</span>`; return; }
    if (!shops.length) { body.innerHTML = UX.empty(Z("所有店铺都接了接口，不需要导出", "ทุกร้านเชื่อม API แล้ว ไม่ต้องส่งออก")); return; }
    let html = "";
    for (const s of shops) {
      const d = await api(`/api/stocksync/export-list?shop=${s.id}`);
      html += `<div class="card" style="margin-bottom:10px"><div class="row between"><h3 data-notr>${E(s.name)} <span class="muted small">${E(s.platform)}</span></h3>
        <span><button class="mini primary-lite" data-ss-exp="${s.id}" ${d.items.length ? "" : "disabled"}>⬇ ${E(Z("生成导出表", "สร้างไฟล์ส่งออก"))}</button>
        <button class="mini" data-ss-up="${s.id}" ${d.items.length ? "" : "disabled"}>✔ ${E(Z("已上传", "อัปโหลดแล้ว"))}</button></span></div>
        <p class="small muted">${E(Z("这个店铺还没有接口：下载表格 → 在卖家中心批量更新库存 → 点「已上传」标记已同步。", "ร้านนี้ยังไม่มี API: ดาวน์โหลดไฟล์ → อัปเดตสต็อกในศูนย์ผู้ขาย → กด “อัปโหลดแล้ว”"))}</p>
        <div id="ss-exp-file-${s.id}"></div>
        ${d.items.length ? `<table class="grid small"><thead><tr><th>SKU</th><th>${E(Z("产品", "สินค้า"))}</th><th class="r">${E(Z("要显示的库存", "สต็อกที่ต้องแสดง"))}</th><th class="r">${E(Z("上次", "ครั้งก่อน"))}</th></tr></thead><tbody>` +
          d.items.map((x) => `<tr><td class="mono" data-notr data-p360="${E(x.sku)}">${E(x.sku)}</td><td data-notr>${E(x.name)} ${E(x.color)} ${E(x.spec)}</td><td class="r"><b>${x.qty}</b></td><td class="r muted">${x.last == null ? "—" : x.last}</td></tr>`).join("") + "</tbody></table>"
          : UX.empty(Z("没有待导出的", "ไม่มีรายการรอส่งออก"))}</div>`;
    }
    body.innerHTML = html;
  }

  // ---------- 事件 ----------
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (!t.closest || !t.closest("#ss-root, .ss-modal")) return;
    const q = (s) => t.closest(s);
    try {
      if (q("[data-ss-view]")) { SS.view = q("[data-ss-view]").dataset.ssView; return load(); }
      if (t.id === "ss-clear") { e.preventDefault(); SS.kpi = ""; return load(); }
      if (t.id === "ss-check") return busy(t, async () => { const r = await apiJob("/api/stocksync/check", { json: {} }); toast(Z(`已检查：推送 ${r.pushed}，失败 ${r.failed}`, `ตรวจแล้ว: ส่ง ${r.pushed} ล้มเหลว ${r.failed}`), !!r.failed); load(); });
      if (t.id === "ss-pushall") { if (!confirm(Z("把所有接口店铺的库存全部重新推一遍？（锁定的不动）", "ส่งสต็อกใหม่ทั้งหมดของทุกร้านที่มี API? (ที่ล็อกไว้ไม่แก้)"))) return; return busy(t, async () => { const r = await apiJob("/api/stocksync/push-all", { json: {} }); toast(Z(`已重推 ${r.pushed}，失败 ${r.failed}`, `ส่งใหม่ ${r.pushed} ล้มเหลว ${r.failed}`), !!r.failed); load(); }); }
      if (t.id === "ss-rules") return ruleDialog("shop", "", SS.shop || 0, SS.shop ? Z("店铺规则", "กฎของร้าน") : Z("店铺规则（选一个店铺再点）", "กฎของร้าน (เลือกร้านก่อน)"));
      if (q(".ss-rule")) { const b = q(".ss-rule"); return ruleDialog("sku", b.dataset.sku, 0, `${b.dataset.sku} ${Z("规则", "กฎ")}`); }
      if (q(".ss-lock")) { const b = q(".ss-lock"); const r = await api("/api/stocksync/lock", { json: { sku: b.dataset.sku, shop_id: +b.dataset.shop, qty: b.dataset.lock === "" ? null : +b.dataset.lock } }); return load(); }
      if (q("[data-ss-bulk]")) return bulk(q("[data-ss-bulk]").dataset.ssBulk);
      if (t.id === "ss-sel-clear") { SS.sel.clear(); return load(); }
      if (t.id === "lg-retry") { const r = await api("/api/stocksync/retry", { json: {} }); toast(Z(`重试：成功 ${r.pushed}，失败 ${r.failed}`, `ลองใหม่: สำเร็จ ${r.pushed} ล้มเหลว ${r.failed}`), !!r.failed); return load(); }
      if (q("[data-ss-exp]")) { const sid = q("[data-ss-exp]").dataset.ssExp; const r = await api("/api/stocksync/export", { json: { shop_id: +sid } });
        $(`#ss-exp-file-${sid}`).innerHTML = `<p><a href="/api/export/${encodeURIComponent(r.file)}" download>⬇ ${E(r.file)}</a> <span class="muted small">(${r.rows})</span></p>`; return; }
      if (q("[data-ss-up]")) { const r = await api("/api/stocksync/uploaded", { json: { shop_id: +q("[data-ss-up]").dataset.ssUp } }); toast(Z(`已标记 ${r.marked} 个已同步`, `ทำเครื่องหมายซิงก์แล้ว ${r.marked} รายการ`)); return load(); }
    } catch (err) { toast(err.message, true); }
  });
  document.addEventListener("ux-go", (e) => { if (String(e.detail).startsWith("ss:") && root()) { const k = e.detail.slice(3); SS.kpi = SS.kpi === k ? "" : k; SS.view = "matrix"; load(); } });
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (!t.closest || !t.closest("#ss-root")) return;
    if (t.id === "ss-shop") { SS.shop = t.value; load(); }
    else if (t.id === "ss-all") { document.querySelectorAll(".ss-pick").forEach((x) => { x.checked = t.checked; t.checked ? SS.sel.add(x.dataset.sku) : SS.sel.delete(x.dataset.sku); }); syncBar(); }
    else if (t.classList.contains("ss-pick")) { t.checked ? SS.sel.add(t.dataset.sku) : SS.sel.delete(t.dataset.sku); syncBar(); }
    else if (t.classList.contains("ss-in")) editQty(t);
    else if (t.id === "lg-reason" || t.id === "lg-result") { SS.logf.reason = $("#lg-reason").value; SS.logf.result = $("#lg-result").value; loadLog(); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.classList && e.target.classList.contains("ss-in")) { e.preventDefault(); e.target.blur(); } });
  { let tm = null; document.addEventListener("input", (e) => {
    if (e.target.id === "ss-q") { SS.q = e.target.value; clearTimeout(tm); tm = setTimeout(load, 300); }
    if (e.target.id === "lg-sku") { SS.logf.sku = e.target.value; clearTimeout(tm); tm = setTimeout(loadLog, 300); } }); }
  window.loadStockPending = load;      // export.js 切到「库存同步」时调用
  window.SS = SS;
})();
