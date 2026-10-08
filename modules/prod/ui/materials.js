"use strict";
// 生产模块：耗材（库存 · 补货计划 · 记录 · 机上耗材）。v2.31 从 ops.js 搬过来。
(function () {
  const { num, colorTxt, today, isOwner, stChip, trayHtml } = window.OPSH;
  async function loadMaterials() {
    const r = await api("/api/materials");
    renderPlan(r);
    loadMatLog();
    loadMatPrinters().catch(() => {});
    if (window.SPOOLS) window.SPOOLS.load();
  }
  function renderPlan(r) {
    const p = r.params;
    $("#mat-params").textContent = `每天用量 = 实际消耗（近 7 天 / 30 天）和按订单销量预测（近 14 天权重大）中较大的；` +
      `待打印任务还要的料按打印文件算。到货要 ${p.filament_lead_days} 天，安全库存 ${p.filament_safety_days} 天，每次买够 ${p.filament_cover_days} 天用量，每卷 ${p.filament_spool_kg} kg。` +
      (isOwner() ? "（可在 设置 → 库存与采购 修改）" : "");
    $("#mat-h-forecast").textContent = `未来 ${r.horizon_days} 天需要 kg`;
    const td = today();
    $("#mat-table tbody").innerHTML = r.rows.map((x) => {
      const state = x.short ? '<span class="pill bad-pill">不够打待打印的单</span>'
        : x.urgent ? '<span class="pill warn-pill">该下单了</span>' : '<span class="pill ok-pill">充足</span>';
      const ob = x.order_by_date ? (x.order_by_date <= td ? '<b class="bad">现在</b>' : esc(x.order_by_date)) : "";
      return `<tr class="${x.short ? "row-bad" : x.urgent ? "row-warn" : ""}">
        <td data-notr>${esc(x.material)}</td><td>${colorTxt(x.color)}</td>
        <td><b>${num(x.kg, 2)}</b>${spoolSum(x.spools)}</td><td>${x.pending_kg ? num(x.pending_kg, 2) : ""}</td>
        <td>${x.daily_kg ? num(x.daily_kg, 3) : ""}<div class="small muted">实际 ${num(x.used_daily_kg, 3) || 0} · 订单 ${num(x.order_daily_kg, 3) || 0}</div></td>
        <td>${x.days_left === null ? '<span class="muted">没在用</span>' : x.days_left <= 0 ? '<b class="bad">已缺料</b>' : num(x.days_left, 0) + " 天"}</td>
        <td class="nowrap">${x.runout_date && x.days_left !== null ? esc(x.runout_date) : ""}</td>
        <td class="nowrap">${ob}</td>
        <td>${x.forecast_kg ? num(x.forecast_kg, 2) : ""}</td>
        <td>${x.buy_spools ? `<b class="bad">${x.buy_spools}</b>` : (x.suggest_spools ? `<span class="muted">${x.suggest_spools}（不急）</span>` : "")} ${state}</td>
        <td class="small mono" data-notr>${(x.top_skus || []).map((t) => `${esc(t.sku)}×${t.qty}`).join("<br>")}</td>
        <td class="nowrap"><button class="mini" data-quick="${esc(x.material)}|${esc(x.color)}">+1 卷</button>
          <button class="mini" data-flag="opened|${esc(x.material)}|${esc(x.color)}">开封</button><button class="mini" data-flag="dried|${esc(x.material)}|${esc(x.color)}">烘干</button>
          ${x.humid ? `<div class="small ${x.humid.warn ? "bad" : "muted"}">${x.humid.warn ? "⚠ 该烘干了：" : ""}开封/烘干后 ${x.humid.days} 天（${esc(x.material)} 建议 ${x.humid.limit} 天内）</div>` : ""}</td></tr>`;
    }).join("") || '<tr><td colspan="12" class="muted">还没有库存记录。在上面录入现有库存。</td></tr>';
  }
  function spoolSum(sp) {
    if (!sp || !(sp.sealed || sp.open || sp.loaded)) return "";
    return `<div class="small muted">${sp.sealed ? `未开封 ${sp.sealed} 卷` : '<span class="warn">没有备用卷</span>'}${sp.open ? ` · 已开封 ${sp.open}` : ""}${sp.loaded ? ` · 机上 ${sp.loaded}` : ""}</div>`;
  }
  async function loadMatPrinters() {
    const [r, sp] = await Promise.all([api("/api/printers"), api("/api/spools?status=loaded")]);
    const on = {};
    sp.items.forEach((s) => (on[s.printer] = on[s.printer] || []).push(s));
    $("#mat-printers").innerHTML = r.printers.map((p) => { const code = p.code || ""; const mine = on[code] || [];
      return `<div class="sub-card"><b class="mono" data-notr>${esc(code)}</b> <b data-notr>${esc(p.name)}</b> ${stChip(p.status, p.status_zh)}
      ${trayHtml(p.status) || (p.conn && p.conn.loaded ? `<div class="small">装着：<span data-notr>${esc(p.conn.loaded)}</span></div>` : (mine.length ? "" : '<div class="small muted">没有料盘信息</div>'))}
      ${mine.map((s) => `<div class="small"><span class="mono" data-notr>${esc(s.code)}</span> ${s.slot ? `<span class="mono" data-notr>${esc(s.slot)}</span> ` : ""}${esc(s.material)} ${colorTxt(s.color)}
        <b class="${s.remaining_g < 100 ? "bad" : ""}">${num(s.remaining_g, 0)} g</b></div>`).join("")}</div>`; }).join("");
  }
  async function loadMatLog() {
    const r = await api("/api/materials/log");
    $("#mat-log tbody").innerHTML = r.items.map((l) => `<tr><td class="nowrap">${fmtTime(l.ts)}</td><td data-notr>${esc(l.material)}</td>
      <td>${colorTxt(l.color)}</td><td class="${l.delta_kg < 0 ? "bad" : "ok"}">${l.delta_kg > 0 ? "+" : ""}${num(l.delta_kg, 3)}</td>
      <td>${esc(l.reason || "")}</td><td data-notr>${esc(l.username || "")}</td></tr>`).join("") || '<tr><td colspan="6" class="muted">没有记录</td></tr>';
  }
  async function matSave(mode, material, color, kg) {
    if (!color) throw new Error("请填写颜色");
    const r = await api("/api/materials", { json: { mode, material, color, kg } });
    renderPlan(r);
    loadMatLog();
    toast(mode === "set" ? "库存已更新" : "已入库");
  }
  $("#btn-mat-add").addEventListener("click", (e) => busy(e.target, () => matSave("add", $("#mat-material").value, $("#mat-color").value.trim(), $("#mat-kg").value)));
  $("#btn-mat-set").addEventListener("click", (e) => {
    if (!CAN("materials.adjust")) { toast("你的账号没有「耗材盘点改数 / 删除料卷」的权限，请老板在 系统 → 设置 → 账号与权限 里开通", true); return; }
    if (!confirm(`盘点：把 ${$("#mat-material").value} ${$("#mat-color").value.trim()} 的库存直接设为 ${$("#mat-kg").value} kg？（不是加减，原来的数会被覆盖）`)) return;
    busy(e.target, () => matSave("set", $("#mat-material").value, $("#mat-color").value.trim(), $("#mat-kg").value));
  });
  $("#mat-table").addEventListener("click", async (e) => {
    const fl = e.target.closest("[data-flag]");
    if (fl) {
      const [action, m, c] = fl.dataset.flag.split("|");
      try { renderPlan(await api("/api/materials/flag", { json: { material: m, color: c, action } })); toast(action === "opened" ? "已记录开封" : "已记录烘干"); }
      catch (err) { toast(err.message, true); }
      return;
    }
    const b = e.target.closest("[data-quick]");
    if (!b) return;
    const [m, c] = b.dataset.quick.split("|");
    const net = Math.round(((CFG && CFG.filament_spool_kg) || 1) * 1000);
    busy(b, async () => { await api("/api/spools", { json: { material: m, color: c, count: 1, net_g: net } }); toast("已入库 1 卷"); loadMaterials(); });
  });
  $("#btn-mat-reload").addEventListener("click", (e) => busy(e.target, loadMaterials));

  window.MATERIALS = { load: loadMaterials };
})();
