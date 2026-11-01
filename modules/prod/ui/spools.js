"use strict";
// 耗材按卷管理：入库、上机 / 下机、称重、用完、标签、提醒（v2.12）
(function () {
  const H = () => window.OPSH;
  const SEL = new Set();
  let ITEMS = [];
  const ST_CLS = { sealed: "tag-pill", open: "warn-pill", loaded: "ok-pill", empty: "" };

  async function load() {
    const q = new URLSearchParams({ status: $("#sp-status").value, material: $("#sp-q-material").value.trim(), color: $("#sp-q-color").value.trim() });
    const r = await api("/api/spools?" + q);
    ITEMS = r.items;
    $("#mat-alerts").innerHTML = r.alerts.length ? `<div class="card mat-alerts"><h3>耗材提醒</h3>${r.alerts.map((a) =>
      `<div class="small ${a.level === "bad" ? "bad" : "warn"}">${a.level === "bad" ? "⚠" : "•"} ${esc(a.text)}</div>`).join("")}</div>` : "";
    $("#sp-table tbody").innerHTML = ITEMS.map((s) => {
      const pct = s.pct == null ? 0 : Math.max(0, Math.min(100, s.pct));
      return `<tr data-sid="${esc(s.code)}" class="${SEL.has(s.code) ? "sel" : ""}"><td><input type="checkbox" data-spsel="${esc(s.code)}" ${SEL.has(s.code) ? "checked" : ""}></td>
        <td class="mono" data-notr><b>${esc(s.code)}</b></td>
        <td><span data-notr>${esc(s.material)}</span> ${H().colorTxt(s.color)}</td><td data-notr>${esc(s.brand || "")}</td>
        <td class="nowrap"><div class="sp-bar"><i style="width:${pct}%" class="${s.remaining_g < 100 && s.status !== "empty" ? "low" : ""}"></i></div>
          <span class="small">${H().num(s.remaining_g, 0)} / ${H().num(s.net_g, 0)} g</span></td>
        <td><span class="pill ${ST_CLS[s.status] || ""}">${esc(s.status_zh)}</span></td>
        <td class="mono small" data-notr>${s.status === "loaded" ? esc(s.printer || "") + (s.slot ? " · " + esc(s.slot) : "") : ""}</td>
        <td class="small">${s.opened_at ? `${Math.floor((Date.now() / 1000 - s.opened_at) / 86400)} 天` : ""}${s.humid && s.humid.warn ? '<div class="bad">该烘干了</div>' : ""}</td>
        <td class="nowrap">${s.status === "empty" ? "" : `${s.status === "loaded" ? '<button class="mini" data-sp="unload">下机</button>' : '<button class="mini primary-lite" data-sp="load">上机</button>'}
          <button class="mini" data-sp="weigh">称重</button><button class="mini" data-sp="empty">用完</button>
          ${s.status !== "sealed" ? '<button class="mini" data-sp="dry">烘干</button>' : (CAN("materials.adjust") ? '<button class="mini danger" data-sp="delete">删除</button>' : "")}`}
          <a class="btn mini-btn" target="_blank" href="/print/spools?ids=${encodeURIComponent(s.code)}">标签</a></td></tr>`;
    }).join("") || '<tr><td colspan="9" class="muted">没有料卷。在上面「入库（按卷）」录入。</td></tr>';
    $("#sp-all").checked = ITEMS.length && ITEMS.every((s) => SEL.has(s.code));
    if (window.INVZ) INVZ.spoolExtras().catch(() => {});      // v2.53：每卷放在哪个货位（仓库模块）
  }

  function printerOptions(cur = "") {
    const prs = (typeof CFG !== "undefined" && CFG && CFG.printers) || [];
    return prs.map((p, i) => { const code = p.code || `#${i + 1}`;
      return `<option value="${esc(code)}" ${code === cur ? "selected" : ""}>${esc(code)} · ${esc(p.name || "")}</option>`; }).join("");
  }

  async function act(code, action) {
    const s = ITEMS.find((x) => x.code === code) || (await api(`/api/spools?status=`)).items.find((x) => x.code === code);
    if (!s) { toast(`找不到料卷 ${code}`, true); return; }
    const done = (msg) => { toast(msg); if (window.OPS) OPS.loadMaterials(); else load(); };
    try {
      if (action === "load") {
        const el = MODAL.open(`<div class="row between"><h3>上机 · <span class="mono" data-notr>${esc(s.code)}</span> ${esc(s.material)} ${H().colorTxt(s.color)}</h3><button class="mini" data-mclose>关闭</button></div>
          <div class="form3"><label>打印机<select id="spl-pr">${printerOptions()}</select></label>
          <label>料位（拓竹 AMS 填 A1–A4、B1…；单料机器空着）<input id="spl-slot" placeholder="A1" data-notr></label></div>
          <p class="small muted">同一台机器同一个料位上原来那卷会自动退回「已开封（在库）」。</p>
          <button class="primary" id="spl-go">确定上机</button>`);
        $("#spl-go", el).onclick = () => busy($("#spl-go", el), async () => {
          await api(`/api/spools/${s.code}/load`, { json: { printer: $("#spl-pr", el).value, slot: $("#spl-slot", el).value.trim().toUpperCase() } });
          MODAL.close(); done("已上机");
        });
        return;
      }
      if (action === "unload" || action === "weigh") {
        const g = prompt(action === "unload" ? "取下来称一下，剩多少克（只算料，不含料盘；不称就直接确定）" : "称重：剩多少克（只算料，不含料盘）",
          action === "weigh" ? Math.round(s.remaining_g) : "");
        if (g === null) return;
        await api(`/api/spools/${s.code}/${action}`, { json: { grams: g === "" ? null : +g } });
        done(action === "unload" ? "已下机" : "已更新剩余克数");
        return;
      }
      if (action === "empty" && !confirm(`${s.code} 用完了？剩余的 ${Math.round(s.remaining_g)} g 会从库存里扣掉。`)) return;
      if (action === "delete" && !confirmDelete(`料卷 ${s.code}（只在录错时删除）`)) return;
      await api(`/api/spools/${s.code}/${action}`, { json: {} });
      done({ empty: "已标记用完", dry: "已记录烘干", delete: "已删除" }[action] || "已更新");
    } catch (err) { toast(err.message, true); }
  }

  $("#sp-table").addEventListener("click", (e) => {
    const cb = e.target.closest("[data-spsel]");
    if (cb) { cb.checked ? SEL.add(cb.dataset.spsel) : SEL.delete(cb.dataset.spsel); cb.closest("tr").classList.toggle("sel", cb.checked); return; }
    const b = e.target.closest("[data-sp]");
    if (b) act(b.closest("[data-sid]").dataset.sid, b.dataset.sp);
  });
  $("#sp-all").addEventListener("change", (e) => { ITEMS.forEach((s) => (e.target.checked ? SEL.add(s.code) : SEL.delete(s.code))); load(); });
  $("#sp-print").addEventListener("click", () => {
    if (!SEL.size) { toast("先勾选料卷", true); return; }
    window.open(`/print/spools?ids=${[...SEL].join(",")}`, "_blank");
  });
  ["#sp-status"].forEach((k) => $(k).addEventListener("change", load));
  ["#sp-q-material", "#sp-q-color"].forEach((k) => { let t = null; $(k).addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 300); }); });
  // 扫码：扫到料卷编号直接问做什么
  $("#sp-scan").addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    const code = e.target.value.trim().toUpperCase();
    e.target.value = "";
    if (!code) return;
    const all = (await api("/api/spools?status=")).items;
    const s = all.find((x) => x.code === code);
    if (!s) { toast(`找不到料卷 ${code}`, true); return; }
    ITEMS = all;
    const el = MODAL.open(`<div class="row between"><h3><span class="mono" data-notr>${esc(s.code)}</span> ${esc(s.material)} ${H().colorTxt(s.color)}</h3><button class="mini" data-mclose>关闭</button></div>
      <p>${esc(s.status_zh)}${s.status === "loaded" ? ` · <span class="mono" data-notr>${esc(s.printer || "")} ${esc(s.slot || "")}</span>` : ""} · 剩 ${H().num(s.remaining_g, 0)} g</p>
      <div class="row gap wrap">${s.status === "empty" ? "" : `${s.status === "loaded" ? '<button data-scan="unload">下机</button>' : '<button class="primary" data-scan="load">上机</button>'}
        <button data-scan="weigh">称重</button><button data-scan="empty">用完</button><button data-scan="dry">烘干</button>`}</div>`);
    el.onclick = (ev) => { const a = ev.target.dataset.scan; if (a) { MODAL.close(); act(s.code, a); } };
  });
  $("#btn-sp-receive").addEventListener("click", (e) => busy(e.target, async () => {
    const color = $("#sp-color").value.trim();
    if (!color) throw new Error("请填写颜色");
    const r = await api("/api/spools", { json: { material: $("#sp-material").value.trim(), color, brand: $("#sp-brand").value.trim(),
      net_g: +$("#sp-net").value, count: +$("#sp-count").value, price: $("#sp-price").value } });
    toast(`已入库 ${r.codes.length} 卷：${r.codes[0]}${r.codes.length > 1 ? " – " + r.codes[r.codes.length - 1] : ""}`);
    if ($("#sp-label").checked) window.open(`/print/spools?ids=${r.codes.join(",")}`, "_blank");
    if (window.OPS) OPS.loadMaterials(); else load();
  }));

  window.SPOOLS = { load, act };
})();
