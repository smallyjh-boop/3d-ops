"use strict";
// v2.44：在线商品——从店铺拉回来的商品（按平台分）：筛选、快速改价改库存（直接改到平台并写回 ERP）、上下架、更新资料。
(function () {
  const OL = { plat: "lazada", status: "", data: null, open: new Set() };
  const STZ = { live: "在售", uploaded: "审核中", rejected: "审核不通过", inactive: "已下架", deleted: "已删除" };
  const money = (v) => (v == null || v === "" ? "—" : "฿" + (+v).toLocaleString(undefined, { maximumFractionDigits: 2 }));
  async function load() {
    if (OL.plat !== "lazada") {
      $("#ol-flow").innerHTML = ""; $("#ol-synced").textContent = ""; $("#ol-shop").innerHTML = "";
      $("#ol-list").innerHTML = '<div class="card"><p class="muted">Shopee 还没有接口：接口申请下来后，这里和 Lazada 一样能看、能改。现在请在 Shopee 卖家中心操作。</p></div>';
      return;
    }
    const qs = new URLSearchParams({ platform: OL.plat, shop: $("#ol-shop").value || "", status: OL.status, q: $("#ol-q").value.trim(),
      linked: $("#ol-unlinked").checked ? "no" : "", stock0: $("#ol-stock0").checked ? "1" : "", pending: $("#ol-pending").checked ? "1" : "" });
    let r;
    try { r = await api("/api/online?" + qs); } catch (e) { $("#ol-list").innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
    OL.data = r;
    const cur = $("#ol-shop").value;
    $("#ol-shop").innerHTML = `<option value="">全部店铺</option>` + r.shops.map((s) => `<option value="${s.id}" data-notr>${esc(s.name)}</option>`).join("");
    $("#ol-shop").value = cur;
    $("#ol-synced").textContent = r.synced_at ? `上次同步 ${fmtTime(r.synced_at)}` : "还没同步过";
    const c = r.counts, all = Object.entries(c).filter(([k]) => STZ[k]).reduce((a, [, v]) => a + v, 0);
    const chip = (k, zh, warn) => `<button class="lw-chip ${warn ? "warn" : ""} ${OL.status === k ? "on" : ""}" data-st="${k}"><span>${zh}</span> <b>${k ? c[k] || 0 : all}</b></button>`;
    $("#ol-flow").innerHTML = chip("", "全部") + '<span class="lw-arrow">｜</span>' + chip("live", "在售") + chip("uploaded", "审核中") +
      chip("rejected", "审核不通过", true) + chip("inactive", "已下架") +
      `<span class="lw-flow-r small muted">没对上 ERP <b>${c.unlinked || 0}</b> · 库存为 0 <b>${c.stock0 || 0}</b></span>`;
    $("#ol-sum").textContent = `${r.items.length} 个商品`;
    if (!r.items.length) {
      $("#ol-list").innerHTML = `<div class="card"><p class="muted">${r.synced_at ? "没有符合条件的商品" : "还没有拉过店铺商品：点上面「🔄 立即同步」"}</p></div>`;
      return;
    }
    $("#ol-list").innerHTML = `<table class="grid lw-table"><thead><tr><th></th><th>商品 / ERP 编号</th><th>店铺</th><th>状态</th><th>价格</th><th>库存</th><th>近 30 天</th><th></th></tr></thead><tbody>` +
      r.items.map(row).join("") + "</tbody></table>";
  }
  function row(it) {
    const key = `${it.shop_id}|${it.item_id}`;
    const pr = it.price_min == null ? "—" : it.price_min === it.price_max ? money(it.price_min) : `${money(it.price_min)}–${money(it.price_max)}`;
    const acts = [
      `<button class="mini" data-skus="${esc(key)}">改价 / 库存 ▾</button>`,
      it.status === "live" ? `<button class="mini" data-off="${esc(key)}">下架</button>` : it.status === "inactive" ? `<button class="mini" data-on="${esc(key)}">上架</button>` : "",
      it.product_id ? `<button class="mini" data-edit="${esc(it.product_id)}">编辑资料</button><button class="mini primary-lite" data-push="${esc(it.product_id)}" title="把 ERP 里的标题、详情、图片、属性、价格、库存更新到店铺">⬆ 更新到店铺</button>` : "",
      it.url ? `<a class="btn mini-btn" href="${esc(it.url)}" target="_blank" rel="noopener">看商品页 ↗</a>` : "",
    ].join("");
    const skus = OL.open.has(key) ? `<tr class="lw-iss-row"><td></td><td colspan="7"><table class="grid small ol-skus" data-key="${esc(key)}"><thead><tr><th>SKU</th><th>原价</th><th>促销价</th><th>库存</th><th></th></tr></thead><tbody>` +
      it.skus.map((s) => `<tr data-sku="${esc(s.seller_sku)}"><td class="mono" data-notr>${esc(s.seller_sku)}</td>
        <td><input type="number" step="0.01" min="0" data-f="price" value="${s.price ?? ""}" style="width:90px"></td>
        <td><input type="number" step="0.01" min="0" data-f="special_price" value="${s.special_price ?? ""}" style="width:90px" placeholder="无"></td>
        <td><input type="number" step="1" min="0" data-f="qty" value="${s.qty ?? ""}" style="width:70px"></td>
        <td><button class="mini primary" data-save="1">保存到平台</button></td></tr>`).join("") + "</tbody></table></td></tr>" : "";
    return `<tr><td>${it.image ? `<img class="thumb" src="${esc(it.image)}" alt="" loading="lazy">` : ""}</td>
      <td class="lib-name"><div class="clamp2" data-notr title="${esc(it.name)}">${esc(it.name)}</div>
        <div class="small">${it.product_id ? `<span class="pill tag-pill" data-notr>${esc(it.product_id)}</span>` : '<span class="pill warn-pill">没对上 ERP</span>'}
        <span class="muted mono" data-notr>${esc(it.item_id)}</span> · ${it.skus.length} SKU</div></td>
      <td class="small" data-notr>${esc(it.shop)}</td>
      <td><span class="lst lst-${esc(it.status)}">${esc(STZ[it.status] || it.raw_status || "")}</span>${it.reason ? `<div class="small bad clamp2" data-notr title="${esc(it.reason)}">${esc(it.reason)}</div>` : ""}</td>
      <td class="nowrap">${pr}</td><td class="${it.qty === 0 ? "bad" : ""}">${it.qty}</td><td>${it.sold_30d || 0}</td>
      <td><div class="row gap wrap">${acts}</div></td></tr>` + skus;
  }
  const findItem = (key) => (OL.data.items || []).find((x) => `${x.shop_id}|${x.item_id}` === key);
  document.addEventListener("click", async (e) => {
    if (!e.target.closest || !e.target.closest("#tab-online")) return;
    const t = e.target.closest("button"); if (!t) return;
    const d = t.dataset;
    try {
      if (d.plat) { OL.plat = d.plat; $$("#ol-plat button").forEach((b) => b.classList.toggle("on", b === t)); OL.status = ""; return load(); }
      if (d.st !== undefined) { OL.status = d.st; return load(); }
      if (t.id === "ol-sync") {
        return busy(t, async () => {
          const r = await apiJob("/api/online/sync", { json: {} });
          const s = r.shops || [];
          toast(s.map((x) => x.error ? `${x.shop}：同步失败 ${x.error}` : `${x.shop}：${x.items} 个商品，对上 ERP ${x.linked} 个`).join("；"), s.some((x) => x.error));
          await load();
        });
      }
      if (d.skus) { OL.open.has(d.skus) ? OL.open.delete(d.skus) : OL.open.add(d.skus); return load(); }
      if (d.edit) return openProduct(d.edit, true);
      if (d.off || d.on) {
        const it = findItem(d.off || d.on);
        if (!confirm(`${d.off ? "下架" : "上架"}「${it.name.slice(0, 40)}」？`)) return;
        await busy(t, () => api("/api/online/active", { json: { platform: OL.plat, shop_id: it.shop_id, item_id: it.item_id, active: !!d.on } }));
        toast(d.off ? "已下架" : "已上架"); return load();
      }
      if (d.push) {
        if (!confirm(`把 ERP 里 ${d.push} 的标题、详情、图片、属性、价格、库存更新到店铺？`)) return;
        return busy(t, async () => {
          const r = await apiJob("/api/listing/lazada/push", { json: { product_ids: [d.push], force: false } });
          if (r.ok.length) toast("已更新到店铺（平台可能会重新审核）");
          else toast((r.failed[0] && r.failed[0].error) || (r.errors[0]) || "没有更新", true);
          await load();
        });
      }
      if (d.save) {
        const tr = t.closest("tr"), key = t.closest("table").dataset.key, it = findItem(key);
        const v = (f) => tr.querySelector(`[data-f="${f}"]`).value;
        const old = it.skus.find((s) => s.seller_sku === tr.dataset.sku) || {};
        const body = { platform: OL.plat, shop_id: it.shop_id, item_id: it.item_id, seller_sku: tr.dataset.sku };
        if (v("price") !== String(old.price ?? "")) body.price = v("price");
        if (v("special_price") !== String(old.special_price ?? "")) body.special_price = v("special_price");
        if (v("qty") !== String(old.qty ?? "")) body.qty = v("qty");
        if (Object.keys(body).length === 4) return toast("没有改动");
        await busy(t, async () => {
          const r = await api("/api/online/sku", { json: body });
          toast("已改到平台" + (r.erp ? `；ERP 也改了：${r.erp}` : ""));
          await load();
        });
      }
    } catch (err) { toast(err.message, true); }
  });
  ["#ol-shop", "#ol-unlinked", "#ol-stock0", "#ol-pending"].forEach((k) => document.addEventListener("change", (e) => { if (e.target.matches && e.target.matches(k)) load(); }));
  { let tm = null; document.addEventListener("input", (e) => { if (e.target.id === "ol-q") { clearTimeout(tm); tm = setTimeout(load, 300); } }); }
  // v2.49：上架工作台 / 在线商品 两个页签
  document.addEventListener("click", (e) => { const t = e.target.closest("[data-lst-tab]"); if (t && !t.classList.contains("on")) goTab(t.dataset.lstTab); });
  window.MODS = window.MODS || {};
  const prev = window.MODS.listing || {};
  window.MODS.listing = { ...prev, show(tab, p) { if (prev.show) prev.show(tab, p); if (tab === "online") load(); } };
  window.ONLINE = { load };
})();
