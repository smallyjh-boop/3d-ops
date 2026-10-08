"use strict";
// 对接模块：设置 → AI 与对接 里的「店铺对接」和「3D选品工具对接」（v2.30 从 ops.js 搬过来）。
// API 密钥在内核（app.js 的 INTG_UI），密钥列表加载好后发 intg-loaded 事件，这里接着画店铺和选品工具。
(function () {
  const isOwner = () => window.OPSH && OPSH.isOwner();
  let INTG = null;
  // ---- 3D选品工具对接 ----
  function curResult(t) {
    if (!t) return '<span class="muted">还没测试过连接</span>';
    return `<div>${t.steps.map((s) => `<div class="${s.ok ? "ok" : "bad"}">${s.ok ? "✔" : "✗"} ${esc(s.text)}</div>`).join("")}</div>
      <div class="muted">测试时间 ${fmtTime(t.ts)}</div>`;
  }
  async function loadCurator() {
    const r = await api("/api/curator");
    if (document.activeElement !== $("#cur-url")) $("#cur-url").value = r.base_url || "";
    $("#cur-key").value = "";
    $("#cur-key").placeholder = r.key_set ? `已填（${r.key_mask}），不改就空着` : "还没填";
    const lt = r.last_test;
    $("#cur-badge").innerHTML = !r.base_url ? '<span class="pill">未设置</span>' : lt ? (lt.ok ? '<span class="pill ok-pill">已连接</span>' : '<span class="pill bad-pill">连接有问题</span>') : '<span class="pill warn-pill">未测试</span>';
    $("#cur-result").innerHTML = curResult(lt);
    $("#cur-open").classList.toggle("hidden", !r.base_url);
    if (r.base_url) $("#cur-open").href = r.base_url;
    const keys = (INTG ? INTG.keys : []).filter((k) => k.scope === "catalog" || /选品/.test(k.name));
    $("#cur-keys").innerHTML = keys.length ? keys.map((k) => `<div><span class="mono" data-notr>${esc(k.name)}</span> ·
      ${k.scope === "catalog" ? '<span class="pill tag-pill">建产品</span>' : k.scope === "read" ? '<span class="pill ok-pill">只读</span>' : esc(k.scope)}
      · <span class="mono" data-notr>${esc(k.prefix)}…</span> · ${k.active ? "启用" : '<span class="bad">已停用</span>'} · 最后使用 ${k.last_used ? fmtTime(k.last_used) : "-"}（${k.uses || 0} 次）</div>`).join("")
      : '<span class="warn">还没有给选品工具的密钥</span>';
    $("#cur-count").textContent = r.imported ? `共 ${r.imported} 个` : "";
    $("#cur-recent tbody").innerHTML = r.recent.map((x) => `<tr><td class="nowrap">${fmtTime(x.created_at)}</td>
      <td><a class="link mono" data-curp="${esc(x.product_id)}" data-notr>${esc(x.product_id)}</a></td><td data-notr>${esc(x.name || "")}</td><td>${x.skus}</td>
      <td>${x.draft ? '<span class="pill warn-pill">草稿·待完善</span>' : '<span class="pill ok-pill">已补齐</span>'}</td><td class="mono" data-notr>#${esc(x.source_id)}</td></tr>`).join("")
      || '<tr><td colspan="6" class="muted">还没有推送过来的产品</td></tr>';
  }
  document.addEventListener("click", async (e) => {
    if (!e.target.closest || !e.target.closest("#cur-card")) return;
    const t = e.target;
    try {
      if (t.id === "cur-save") {
        await busy(t, async () => { await api("/api/curator", { json: { base_url: $("#cur-url").value, api_key: $("#cur-key").value } }); toast("已保存"); });
        const r = await api("/api/curator/test", { json: {} });
        toast(r.ok ? "连接正常" : "已保存，但连接有问题，看下面的提示", !r.ok);
        return loadCurator();
      }
      if (t.id === "cur-test") {
        await busy(t, async () => {
          const r = await api("/api/curator/test", { json: { base_url: $("#cur-url").value, api_key: $("#cur-key").value } });
          toast(r.ok ? "连接正常" : "连接有问题，看下面的提示", !r.ok);
        });
        return loadCurator();
      }
      if (t.id === "cur-newkey" || t.id === "cur-newread") {
        const cat = t.id === "cur-newkey";
        const r = await api("/api/apikeys", { json: { name: cat ? "选品工具-建产品" : "选品工具-NAS", scope: cat ? "catalog" : "read" } });
        $("#cur-keyout").innerHTML = `<p class="note-flag">${cat ? "建产品" : "只读"}密钥（只显示这一次，复制填到选品工具「设置 → ERP 对接 → ${cat ? "建产品密钥" : "只读密钥"}」）：<b class="mono" data-notr>${esc(r.key)}</b></p>`;
        if (window.OPS) await OPS.loadIntegrations();
        return;
      }
      if (t.dataset.curp) { showTab("library"); openProduct(t.dataset.curp); }
    } catch (err) { toast(err.message, true); }
  });
  function renderShops() {
    const cl = (p) => (INTG.connectors.find((c) => c.platform === p) || {});
    $("#intg-shops tbody").innerHTML = INTG.shops.map((x) => {
      const st = !x.ready ? '<span class="pill warn-pill">预留，未接通</span>'
        : x.last_error ? `<span class="bad small" data-notr>${esc(x.last_error)}</span>`
        : x.last_ok ? '<span class="pill ok-pill">正常</span>' : '<span class="muted">还没同步</span>';
      return `<tr><td>${esc(cl(x.platform).label || x.platform)}</td><td data-notr>${esc(x.name)}</td>
        <td>${x.enabled ? "开启" : "关闭"}</td><td>${x.interval_min} 分钟</td><td class="nowrap">${x.last_sync ? fmtTime(x.last_sync) : "-"}</td><td>${st}</td>
        <td class="nowrap"><button class="mini" data-shopedit="${x.id}">设置</button>
        ${x.ready ? `<button class="mini" data-shopsync="${x.id}">立即同步</button>` : ""}
        <button class="danger mini-x" data-shopdel="${x.id}">删除</button></td></tr>`;
    }).join("") || '<tr><td colspan="7" class="muted">还没有添加店铺</td></tr>';
    $("#intg-log tbody").innerHTML = INTG.log.map((l) => `<tr><td class="nowrap">${fmtTime(l.ts)}</td><td data-notr>${esc(l.source)}</td>
      <td>${l.ok ? '<span class="ok">成功</span>' : '<span class="bad">失败</span>'}</td><td>${l.orders_new}/${l.orders_updated}</td>
      <td class="small" data-notr>${esc(l.message || "")}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">没有同步记录</td></tr>';
    $("#intg-hooks tbody").innerHTML = INTG.webhooks.map((w) => `<tr><td class="nowrap">${fmtTime(w.ts)}</td><td>${esc(w.platform)}</td>
      <td data-notr>${esc(w.result || "")}</td><td class="mono small" data-notr>${esc(w.body || "")}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">没有平台推送记录</td></tr>';
  }
  function shopForm(shop) {
    const plat = shop ? shop.platform : (INTG.connectors[0] || {}).platform;
    const box = $("#shop-form");
    const render = (p) => {
      const c = INTG.connectors.find((x) => x.platform === p) || { fields: [] };
      const cr = (shop && shop.platform === p && shop.creds) || {};
      box.innerHTML = `<div class="row between"><h4>${shop ? "店铺设置" : "添加店铺"}</h4><button class="mini" data-shopcancel>取消</button></div>
        <div class="form4">
          <label>平台<select id="sf-platform" ${shop ? "disabled" : ""}>${INTG.connectors.map((x) => `<option value="${x.platform}" ${x.platform === p ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select></label>
          <label>店铺名称<input id="sf-name" value="${esc(shop ? shop.name : "")}" data-notr></label>
          <label>同步间隔（分钟）<input id="sf-interval" type="number" min="5" value="${shop ? shop.interval_min : 15}"></label>
          <label class="row" style="align-self:center"><input type="checkbox" id="sf-enabled" ${shop && shop.enabled ? "checked" : ""} ${c.ready ? "" : "disabled"}> 启用自动同步</label>
        </div>
        <p class="small ${c.ready ? "muted" : "warn"}">${esc(c.note || "")}</p>
        ${c.fields.length ? `<div class="form3">${c.fields.map((f) => `<label>${esc(f.label)}<input data-cred="${f.key}" ${f.secret ? 'type="password" autocomplete="new-password"' : ""} value="${esc(cr[f.key] || "")}" data-notr></label>`).join("")}</div>
          <p class="muted small">保密项显示 ****** 表示已保存，不改就保持原样。</p>` : ""}
        ${shop && c.ready ? `<div class="row gap wrap small"><button class="mini" data-authurl="${shop.id}">打开平台授权页</button>
          <input id="sf-code" placeholder="授权后地址栏里 code= 后面的内容" style="width:300px" data-notr><button class="mini" data-authcode="${shop.id}">用授权码换 token</button></div>` : ""}
        <button class="primary" data-shopsave="${shop ? shop.id : ""}">保存</button>`;
    };
    render(plat);
    box.classList.remove("hidden");
    box.onchange = (e) => { if (e.target.id === "sf-platform") render(e.target.value); };
  }
  document.addEventListener("click", async (e) => {
    if (!e.target.closest || !e.target.closest("#intg-shopcard")) return;
    const t = e.target, d = t.dataset;
    try {
      if (t.id === "btn-shop-new") return shopForm(null);
      if (d.shopcancel !== undefined) return $("#shop-form").classList.add("hidden");
      if (d.shopedit) return shopForm(INTG.shops.find((x) => x.id === +d.shopedit));
      if (d.shopdel) { if (!confirm("删除这个店铺的对接设置？已导入的订单不会删除。")) return; await api(`/api/shops/${d.shopdel}`, { method: "DELETE" }); return OPS.loadIntegrations(); }
      if (d.shopsync) {
        await busy(t, async () => {
          const r = await api(`/api/shops/${d.shopsync}/sync`, { json: {} });
          toast(`同步完成：新订单 ${r.orders_new}，更新 ${r.orders_updated}`);
        });
        return OPS.loadIntegrations();
      }
      if (d.shopsave !== undefined) {
        const creds = {};
        $$("#shop-form [data-cred]").forEach((i) => (creds[i.dataset.cred] = i.value));
        await api("/api/shops", { json: { id: d.shopsave ? +d.shopsave : null, platform: $("#sf-platform").value, name: $("#sf-name").value,
          interval_min: $("#sf-interval").value, enabled: $("#sf-enabled").checked, creds } });
        $("#shop-form").classList.add("hidden");
        toast("已保存");
        return OPS.loadIntegrations();
      }
      if (d.authurl) {
        const r = await api(`/api/shops/${d.authurl}/auth-url`, { json: { redirect: location.origin + "/" } });
        window.open(r.url, "_blank");
        return;
      }
      if (d.authcode) {
        await api(`/api/shops/${d.authcode}/auth-code`, { json: { code: $("#sf-code").value } });
        toast("授权成功");
        $("#shop-form").classList.add("hidden");
        return OPS.loadIntegrations();
      }
    } catch (err) { toast(err.message, true); }
  });
  document.addEventListener("intg-loaded", (e) => {
    INTG = e.detail;
    if (!$("#intg-shopcard")) return;
    renderShops();
    loadCurator().catch(() => {});
  });

  let HTML = null;
  async function settings(box, cat) {
    if (cat !== "ai" || !isOwner()) return;
    if (!box.querySelector("#intg-shopcard")) {
      if (!HTML) HTML = await (await fetch("/m/link/settings.html", { cache: "no-cache" })).text();
      box.innerHTML = HTML;
    }
    if (window.OPS) OPS.loadIntegrations().catch((err) => toast(err.message, true));
  }
  window.MODS = window.MODS || {};
  window.MODS.link = { settings, show(tab) { if (window.OPSCHG) return OPSCHG.show(tab); } };
})();
