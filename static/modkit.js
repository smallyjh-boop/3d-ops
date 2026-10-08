"use strict";
// v2.29 模块框架（前台内核）：按 /api/modules 加菜单；页面第一次打开时才加载模块的 page.html / page.js / page.css；
// 设置 → 模块管理（开关）；模块的设置卡片放到设置对应的大分类里。
// 模块的 page.js 这样注册：window.MODS["<id>"] = { show(tab, panel) {...}, settings(box) {...} }
(function () {
  window.MODS = window.MODS || {};
  let LIST = [];
  const loaded = {};          // 模块 id → Promise（页面文件已加载）
  const th = () => window.I18N && I18N.lang === "th";
  const nm = (m) => (th() ? m.name_th : m.name_zh);

  function addMenus() {
    LIST.forEach((m) => (m.menus || []).forEach((mn) => {
      if ($(`#subnav .tab[data-tab="${mn.tab}"]`)) return;
      const b = document.createElement("button");
      b.className = "tab"; b.dataset.mod = mn.mod; b.dataset.tab = mn.tab; b.dataset.roles = mn.roles; b.dataset.module = m.id;
      b.textContent = th() ? mn.th : mn.zh;
      b.setAttribute("data-notr", "");
      const after = mn.after && $(`#subnav .tab[data-tab="${mn.after}"]`);
      const sameMod = $$(`#subnav .tab[data-mod="${mn.mod}"]`);
      const anchor = after || sameMod[sameMod.length - 1];
      if (anchor) anchor.after(b); else $("#subnav").appendChild(b);
      if (typeof ME !== "undefined" && ME) {
        if (!mn.roles.split(",").includes(ME.role) && ME.role !== "owner") b.classList.add("role-hidden");
        if (ME.role !== "owner" && ME.tabs && ME.tabs.length && !ME.tabs.includes(mn.tab)) b.classList.add("role-hidden");
      }
      b.addEventListener("click", () => goTab(mn.tab));
      if (!$(`#tab-${mn.tab}`)) {
        const sec = document.createElement("section");
        sec.id = "tab-" + mn.tab; sec.className = "panel hidden"; sec.dataset.module = m.id;
        $("main").appendChild(sec);
      }
    }));
    $$("#modnav .mod").forEach((x) => x.classList.toggle("hidden", !visibleTabs(x.dataset.mod).length));
  }

  async function init() {
    try { LIST = (await api("/api/modules")).modules || []; } catch { LIST = []; }
    addMenus();
  }

  // 模块的页面文件：只加载一次；出错只影响这个模块
  function loadModule(mid) {
    if (loaded[mid]) return loaded[mid];
    const m = LIST.find((x) => x.id === mid) || { ui: { html: true, js: true, css: true } };
    loaded[mid] = (async () => {
      const v = "?v=" + (window.CLIENT_VERSION || "") + "-" + (m.version || "");
      if (m.ui.css) {
        const l = document.createElement("link"); l.rel = "stylesheet"; l.href = `/m/${mid}/page.css${v}`; document.head.appendChild(l);
      }
      let html = "";
      if (m.ui.html) {
        const r = await fetch(`/m/${mid}/page.html${v}`, { cache: "no-cache" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        html = await r.text();
      }
      if (m.ui.js) {
        await new Promise((ok, bad) => {
          const s = document.createElement("script"); s.src = `/m/${mid}/page.js${v}`;
          s.onload = ok; s.onerror = () => bad(new Error("page.js 加载失败"));
          document.body.appendChild(s);
        });
      }
      return html;
    })();
    loaded[mid].catch(() => { delete loaded[mid]; });
    return loaded[mid];
  }

  async function show(name) {
    const panel = $(`#tab-${name}`);
    if (!panel || !panel.dataset.module) return;
    const mid = panel.dataset.module;
    try {
      const html = await loadModule(mid);
      if (!panel.dataset.ready) { panel.innerHTML = html; panel.dataset.ready = "1"; }
      const M = window.MODS[mid];
      if (M && M.show) await M.show(name, panel);
    } catch (e) {
      panel.innerHTML = `<div class="card"><p class="bad">「${esc(LIST.find((x) => x.id === mid) ? nm(LIST.find((x) => x.id === mid)) : mid)}」这个模块加载失败：<span data-notr>${esc(e.message || e)}</span></p>
        <p class="small muted">其它功能不受影响。可以在 设置 → 模块管理 里先关掉它，再把这个情况发给开发者。</p></div>`;
      console.error("module", mid, e);
    }
  }

  // 设置页：模块管理 + 各模块的设置卡片
  async function settings(cat) {
    if (cat === "modules") return manager();
    for (const m of LIST.filter((x) => x.settings_card && x.settings_module === cat)) {
      let ext = $(`[data-cfgext="${cat}"]`);
      if (!ext) { ext = document.createElement("div"); ext.className = "cfg-ext"; ext.dataset.cfgext = cat; $("#tab-settings").appendChild(ext); }
      ext.classList.remove("hidden");
      let box = ext.querySelector(`[data-modcard="${m.id}"]`);
      if (!box) { box = document.createElement("div"); box.className = "card"; box.dataset.modcard = m.id; ext.appendChild(box); }
      try {
        await loadModule(m.id);
        const M = window.MODS[m.id];
        if (M && M.settings) await M.settings(box);
      } catch (e) { box.innerHTML = `<p class="bad small">「${esc(nm(m))}」的设置加载失败：<span data-notr>${esc(e.message || e)}</span></p>`; }
    }
  }

  const BUILTIN = ["商品", "上架导出", "搜索优化", "3D 模型", "订单", "生产", "库存", "采购", "财务", "客服", "树脂打印", "对接", "电脑加速 / 桌面端"];
  async function manager() {
    let box = $('[data-cfgext="modules"]');
    if (!box) { box = document.createElement("div"); box.className = "cfg-ext"; box.dataset.cfgext = "modules"; $("#tab-settings").appendChild(box); }
    box.classList.remove("hidden");
    let all = [];
    try { all = (await api("/api/modules?all=1")).modules; } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
    const byId = Object.fromEntries(all.map((m) => [m.id, m]));
    box.innerHTML = `<div class="card"><h3>模块管理</h3>
      <p class="small muted">每个功能是一个模块（一个文件夹）：关掉以后它的菜单、设置、后台任务都不出现，数据保留，再打开就回来。基础模块不能关；关掉一个模块时，依赖它的模块会一起停用。</p>
      <table class="grid"><thead><tr><th>模块名称</th><th>说明</th><th>版本</th><th>依赖</th><th>状态</th></tr></thead><tbody>
      ${all.map((m) => `<tr${m.error ? ' class="st-err"' : ""}><td><b data-notr>${esc(nm(m))}</b></td>
        <td class="small" data-notr>${esc(th() ? m.desc_th || m.desc_zh : m.desc_zh)}${m.error ? `<div class="bad">${esc(m.error)}</div>` : ""}</td>
        <td class="small">${esc(m.version || "")}</td>
        <td class="small" data-notr>${m.depends.map((d) => esc(byId[d] ? nm(byId[d]) : d)).join("、") || "—"}</td>
        <td class="nowrap">${m.core ? '<span class="pill">基础，不能关</span>' : m.error ? '<span class="bad">出错</span>'
          : `<label class="switch-l" style="white-space:nowrap"><input type="checkbox" data-modsw="${esc(m.id)}" ${m.enabled ? "checked" : ""}> ${m.enabled ? "开着" : "关着"}</label>`}</td></tr>`).join("")
        || '<tr><td colspan="5" class="muted">还没有模块</td></tr>'}</tbody></table>
      <p class="small muted" style="margin-top:10px">还没拆成模块的内置功能（接下来几个版本陆续变成模块，到时也可以在这里开关）：${BUILTIN.join("、")}</p></div>`;
    box.querySelectorAll("[data-modsw]").forEach((cb) => cb.addEventListener("change", async () => {
      const id = cb.dataset.modsw, on = cb.checked, m = byId[id];
      if (!on && m.dependents.length && !confirm(`关掉「${nm(m)}」，依赖它的模块也会停用：${m.dependents.map((d) => byId[d] ? nm(byId[d]) : d).join("、")}。继续？`)) { cb.checked = true; return; }
      try {
        await api(`/api/modules/${encodeURIComponent(id)}`, { json: { on } });
        toast(on ? "已打开，刷新页面后菜单出现" : "已关闭，刷新页面后菜单消失");
        manager();
      } catch (e) { toast(e.message, true); cb.checked = !on; }
    }));
  }

  window.MODKIT = { init, show, settings, list: () => LIST, load: loadModule };
})();
