"use strict";
// 对接模块：设置 → AI 与对接 里的「店铺对接」（v2.30 从 ops.js 搬过来）。
// API 密钥在内核（app.js 的 INTG_UI），密钥列表加载好后发 intg-loaded 事件，这里接着画店铺。
(function () {
  const isOwner = () => window.OPSH && OPSH.isOwner();
  let INTG = null;
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
  // ---- 店铺设置表单（v2.49）：上面一行基本信息；一个应用一张卡片（Key / Secret / 授权 / 换 token 都在卡片里）；
  //      token 收进每张卡片的「高级」；一般不用的单独应用收在最下面。分组来自连接器的 groups / fields[].group（core/connectors describe）。
  const TT = (s) => (window.I18N ? I18N.t(s) : s);
  const tip = (s) => (s ? UX.help(TT(s)) : "");
  const fmtDay = (ts) => { const d = new Date(ts * 1000); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
  function appStatus(shop, g, fields, cr) {
    const pre = g.prefix || "";
    const filled = fields.some((f) => !f.token && cr[f.key]);
    if (!filled) return g.slot ? UX.dot("", "没填，用主应用") : UX.dot("warn", "未填");
    if (!cr[pre + "access_token"]) return UX.dot("warn", "未授权");
    const ex = (shop && shop.expires) || {}, now = Date.now() / 1000;
    const end = ex[pre + "refresh_expire"] || (!cr[pre + "refresh_token"] && ex[pre + "token_expire"]) || 0;
    if (end && end < now) return UX.dot("bad", "授权过期");
    if (end && end < now + 7 * 86400) return UX.dot("warn", `已授权 · ${fmtDay(end)} 到期`);
    return UX.dot("ok", "已授权") + (end ? ` <span class="muted small">有效至 ${fmtDay(end)}</span>` : "");
  }
  function credInput(f, cr, label) {
    return `<label>${esc(label)}<input data-cred="${f.key}" ${f.secret ? 'type="password" autocomplete="new-password"' : 'autocomplete="off"'} value="${esc(cr[f.key] || "")}" data-notr></label>`;
  }
  function appCard(shop, c, g, cr) {
    const fields = c.fields.filter((f) => f.group === g.slot);
    if (!fields.length) return "";
    const main = c.fields.filter((f) => f.group === (c.groups[0] || {}).slot);
    // 卡片里不用重复写「聊天应用 App Key（…）」：用主应用同名字段的短名字
    const short = (f) => (g === c.groups[0] ? f.label : ((main.find((m) => m.base === f.base) || f).label));
    const keys = fields.filter((f) => !f.token), toks = fields.filter((f) => f.token);
    const id = g.slot || "main";
    return `<div class="sf-app" data-slot="${esc(g.slot)}">
      <div class="sf-app-h"><h4>${esc(g.title)}${tip(g.help)}</h4>${appStatus(shop, g, fields, cr)}</div>
      ${g.for ? `<div class="sf-app-for">${esc(g.for)}</div>` : ""}
      <div class="sf-keys">${keys.map((f) => credInput(f, cr, short(f))).join("")}</div>
      ${c.ready && c.auth ? `<div class="sf-auth">
        <button data-authurl data-app="${esc(g.slot)}">① 打开授权页</button>
        <input id="sf-code-${id}" placeholder="${esc(TT("② 授权后把浏览器地址栏的整个网址贴到这里"))}" data-notr>
        <button class="primary" data-authcode data-app="${esc(g.slot)}">③ 换 token</button>${tip("先填好上面的 Key / Secret。点①会自动保存并打开平台授权页，用卖家账号登录同意；跳转后把地址栏整个网址贴到②，点③。")}
      </div>` : ""}
      ${toks.length ? `<details class="sf-adv"><summary>高级（手动填 token）</summary><div class="sf-keys">${toks.map((f) => credInput(f, cr, short(f))).join("")}</div></details>` : ""}
    </div>`;
  }
  function shopForm(shop) {
    const plat = shop ? shop.platform : (INTG.connectors[0] || {}).platform;
    const box = $("#shop-form");
    box.dataset.sid = shop ? shop.id : "";
    const render = (p) => {
      const c0 = INTG.connectors.find((x) => x.platform === p) || { fields: [], groups: [] };
      const c = { ...c0, groups: c0.groups && c0.groups.length ? c0.groups : [{ slot: "", prefix: "", title: "应用授权" }],
        fields: (c0.fields || []).map((f) => ({ group: "", base: f.key, ...f })), auth: p === "lazada" || p === "shopee" };
      const cr = (shop && shop.platform === p && shop.creds) || {};
      const common = c.fields.filter((f) => f.group === "common");
      const groups = c.groups.filter((g) => !g.more), more = c.groups.filter((g) => g.more);
      const moreFilled = more.filter((g) => c.fields.some((f) => f.group === g.slot && cr[f.key])).length;
      box.innerHTML = `<div class="sf-head"><h4>${shop ? "店铺设置" : "添加店铺"} · ${esc(c.label || p)}${c.ready && c.note ? tip(c.note) : ""}</h4>
          <button class="mini-x" data-shopcancel>✕ 取消</button></div>
        <div class="sf-basic">
          ${shop ? "" : `<label>平台<select id="sf-platform">${INTG.connectors.map((x) => `<option value="${x.platform}" ${x.platform === p ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select></label>`}
          <label>店铺名称<input id="sf-name" value="${esc(shop ? shop.name : "")}" data-notr></label>
          <label>同步间隔（分钟）<input id="sf-interval" type="number" min="5" value="${shop ? shop.interval_min : 15}"></label>
          ${common.map((f) => `<label><span>${esc(f.label)}${tip("Lazada 后台应用里填的 Callback URL，必须是 https，一字不差（例如 https://www.google.com/）。所有应用共用；不填就用本系统地址。")}</span><input data-cred="${f.key}" value="${esc(cr[f.key] || "")}" placeholder="https://www.google.com/" data-notr></label>`).join("")}
          <label class="sf-chk"><input type="checkbox" id="sf-enabled" ${shop && shop.enabled ? "checked" : ""} ${c.ready ? "" : "disabled"}> 启用自动同步</label>
        </div>
        ${c.ready ? "" : `<p class="small warn">${esc(c.note || "")}</p>`}
        ${groups.map((g) => appCard(shop, c, g, cr)).join("")}
        ${more.length ? `<details class="sf-more"><summary>其他单独应用（一般不用）${moreFilled ? ` <span class="muted small">· 已填 ${moreFilled}</span>` : ""}</summary>
          ${more.map((g) => appCard(shop, c, g, cr)).join("")}</details>` : ""}
        <div class="sf-foot"><button class="primary" data-shopsave>保存</button><button data-shopcancel>取消</button>
          ${c.fields.some((f) => f.secret) ? `<span class="muted small">保密项显示 ****** 表示已保存${tip("不改就保持原样；要换掉就清空后填新的。")}</span>` : ""}</div>`;
      if (window.I18N) I18N.translate(box);
    };
    render(plat);
    box.classList.remove("hidden");
    box.onchange = (e) => { if (e.target.id === "sf-platform") render(e.target.value); };
  }
  // 保存表单（授权前也会自动保存一次，新店铺就有了编号）；返回店铺编号
  async function saveForm() {
    const box = $("#shop-form"), creds = {};
    $$("#shop-form [data-cred]").forEach((i) => (creds[i.dataset.cred] = i.value));
    const sid = box.dataset.sid ? +box.dataset.sid : null;
    const shop = sid && INTG.shops.find((x) => x.id === sid);
    const r = await api("/api/shops", { json: { id: sid, platform: shop ? shop.platform : $("#sf-platform").value, name: $("#sf-name").value,
      interval_min: $("#sf-interval").value, enabled: $("#sf-enabled").checked, creds } });
    box.dataset.sid = r.id || sid;
    return +box.dataset.sid;
  }
  async function reopen(sid) {
    await OPS.loadIntegrations();
    const s = INTG.shops.find((x) => x.id === sid);
    if (s) shopForm(s);
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
        if (!(await busy(t, saveForm))) return;          // busy() 出错时已经提示，返回空
        $("#shop-form").classList.add("hidden");
        toast("已保存");
        return OPS.loadIntegrations();
      }
      if (d.authurl !== undefined) {
        const w = window.open("about:blank", "_blank");      // 先开窗口（不被拦截），保存好再跳到授权页
        const sid = await busy(t, async () => {
          const id = await saveForm();
          const r = await api(`/api/shops/${id}/auth-url`, { json: { redirect: location.origin + "/", app: d.app || "" } });
          if (w) w.location = r.url; else window.open(r.url, "_blank");
          return id;
        });
        if (!sid) { if (w) w.close(); return; }
        const code = $("#shop-form").querySelector(`[data-slot="${d.app || ""}"] input[id^="sf-code-"]`);
        const keep = code ? code.value : "";
        await reopen(sid);
        const c2 = $("#shop-form").querySelector(`[data-slot="${d.app || ""}"] input[id^="sf-code-"]`);
        if (c2) { c2.value = keep; c2.focus(); }
        return;
      }
      if (d.authcode !== undefined) {
        const inp = $("#shop-form").querySelector(`[data-slot="${d.app || ""}"] input[id^="sf-code-"]`);
        if (!inp || !inp.value.trim()) { toast("先把授权后地址栏的整个网址贴到框里", true); if (inp) inp.focus(); return; }
        const sid = await busy(t, async () => {
          const id = await saveForm();
          await api(`/api/shops/${id}/auth-code`, { json: { code: inp.value, app: d.app || "" } });
          return id;
        });
        if (!sid) return;
        toast("授权成功");
        return reopen(sid);
      }
    } catch (err) { toast(err.message, true); }
  });
  document.addEventListener("intg-loaded", (e) => {
    INTG = e.detail;
    if (!$("#intg-shopcard")) return;
    renderShops();
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
