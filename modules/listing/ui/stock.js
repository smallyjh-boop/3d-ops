// 库存待同步到平台（v2.16）：按耗材自动算的库存变化够多的 SKU。现在人工到平台后台改好后点「已改好」；以后接上 Lazada 接口自动推送。
(function () {
  const $ = (s) => document.querySelector(s);
  async function load() {
    const box = $("#stk-pending"); if (!box) return;
    const plat = ($("#stk-plat") || {}).value || "lazada";
    let r;
    try { r = await api(`/api/stock/pending?platform=${plat}`); } catch (e) { box.innerHTML = `<span class="bad">${esc(e.message)}</span>`; return; }
    const items = r.items || [];
    if (!items.length) {
      box.innerHTML = `<p class="muted small">${TR("stk.none")}${r.settings && r.settings.on ? "" : TR("stk.global_off")}</p>`;
      return;
    }
    box.innerHTML = `<div class="row gap" style="margin-bottom:6px"><b>${TR("stk.count", { n: items.length })}</b>
        <button class="mini primary-lite" id="stk-mark-sel">${TR("stk.mark_sel")}</button><button class="mini" id="stk-mark-all">${TR("stk.mark_all")}</button></div>
      <table class="grid small"><thead><tr><th><input type="checkbox" id="stk-all"></th><th>SKU</th><th>${TR("stk.h.product")}</th><th>${TR("stk.h.color")}</th><th>${TR("stk.h.spec")}</th>
        <th>${TR("stk.h.last")}</th><th>${TR("stk.h.now")}</th><th>${TR("stk.h.why")}</th></tr></thead><tbody>` +
      items.map((x) => `<tr><td><input type="checkbox" data-sku="${esc(x.sku)}"></td><td class="mono" data-notr>${esc(x.sku)}</td>
        <td data-notr>${esc(x.product_id)} ${esc(x.name)}</td><td data-notr>${esc(typeof colorLabel === "function" ? colorLabel(x.color) : x.color)}</td><td data-notr>${esc(x.spec)}</td>
        <td>${x.last == null ? `<span class="muted">${TR("stk.no_record")}</span>` : x.last}</td>
        <td><b class="${x.stock === 0 ? "bad" : ""}">${x.stock}</b></td><td class="muted">${esc(window.stockWhy ? window.stockWhy(x) : x.reason)}</td></tr>`).join("") +
      "</tbody></table>";
  }
  async function mark(body) {
    body.platform = ($("#stk-plat") || {}).value || "lazada";
    try { const r = await api("/api/stock/mark-synced", { json: body }); toast(TR("stk.marked", { n: r.marked })); load(); }
    catch (e) { toast(e.message, true); }
  }
  document.addEventListener("click", (e) => {
    if (e.target.id === "stk-refresh") load();
    else if (e.target.id === "stk-lz-push") {
      busy(e.target, async () => {
        try {
          const r = await api("/api/listing/lazada/stock-sync", { json: {} });
          toast(`已推到 Lazada：${r.synced} 个 SKU` + (r.skipped ? `；${r.skipped} 个是用表格上传的，请到后台人工改` : "") + (r.failed.length ? `；失败：${r.failed[0]}` : ""), !!r.failed.length);
          load();
        } catch (er) { toast(er.message, true); }
      });
    }
    else if (e.target.id === "stk-mark-all") { if (confirm(TR("stk.confirm_all"))) mark({ all: true }); }
    else if (e.target.id === "stk-mark-sel") {
      const skus = [...document.querySelectorAll("#stk-pending [data-sku]:checked")].map((x) => x.dataset.sku);
      if (!skus.length) return toast(TR("stk.pick_first"), true);
      mark({ skus });
    } else if (e.target.id === "stk-all") document.querySelectorAll("#stk-pending [data-sku]").forEach((x) => (x.checked = e.target.checked));
  });
  document.addEventListener("change", (e) => { if (e.target.id === "stk-plat") load(); });
  window.loadStockPending = load;
})();
