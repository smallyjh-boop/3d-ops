"use strict";
// v2.29 模块框架（前台内核）：按 /api/modules 加菜单；页面第一次打开时才加载模块的 page.html / page.js / page.css；
// 设置 → 模块管理（开关）；模块的设置卡片放到设置对应的大分类里。
// v2.30：一个模块可以有好几个页面（page.html 里每页一个 <section id="tab-…">）、好几个 js（说明书 ui.page_js）、
//        一打开就要的 js（ui.boot_js：例如右上角提醒、产品编辑里的小部件）、几个菜单共用一个页面（menus[].panel）。
// 模块的 js 这样注册：window.MODS["<id>"] = { show(tab, panel) {...}, settings(box, cat) {...} }
(function () {
  window.MODS = window.MODS || {};
  let LIST = [];
  const loaded = {};          // 模块 id → Promise（页面文件已加载）
  const th = () => window.I18N && I18N.lang === "th";
  const nm = (m) => (th() ? m.name_th : m.name_zh);
  const ver = (m) => "?v=" + (window.CLIENT_VERSION || "") + "-" + (m.version || "");
  const byId = (id) => LIST.find((x) => x.id === id);

  function script(src) {
    return new Promise((ok, bad) => {
      const s = document.createElement("script"); s.src = src;
      s.onload = ok; s.onerror = () => bad(new Error(src.split("?")[0].split("/").pop() + " 加载失败"));
      document.body.appendChild(s);
    });
  }

  function addMenus() {
    LIST.forEach((m) => (m.menus || []).forEach((mn) => {
      if (!$(`#subnav .tab[data-tab="${mn.tab}"]`)) {
        const b = document.createElement("button");
        b.className = "tab" + (mn.ghost ? " ghost" : ""); b.dataset.mod = mn.mod; b.dataset.tab = mn.tab; b.dataset.roles = mn.roles; b.dataset.module = m.id;
        b.textContent = th() ? mn.th : mn.zh;
        b.setAttribute("data-notr", "");
        const after = mn.after && $(`#subnav .tab[data-tab="${mn.after}"]`);
        const before = mn.before && $(`#subnav .tab[data-tab="${mn.before}"]`);
        const sameMod = $$(`#subnav .tab[data-mod="${mn.mod}"]`);
        const anchor = after || sameMod[sameMod.length - 1];
        if (before && !after) before.before(b); else if (anchor) anchor.after(b); else $("#subnav").appendChild(b);
        if (typeof ME !== "undefined" && ME) {
          if (!mn.roles.split(",").includes(ME.role) && ME.role !== "owner") b.classList.add("role-hidden");
          if (ME.role !== "owner" && ME.tabs && ME.tabs.length && !ME.tabs.includes(mn.tab)) b.classList.add("role-hidden");
        }
        b.addEventListener("click", () => goTab(mn.tab));
      }
      if (mn.panel !== mn.tab && typeof PANEL_OF !== "undefined") PANEL_OF[mn.tab] = mn.panel;
      if (!$(`#tab-${mn.panel}`)) {
        const sec = document.createElement("section");
        sec.id = "tab-" + mn.panel; sec.className = "panel hidden"; sec.dataset.module = m.id;
        $("main").appendChild(sec);
      } else $(`#tab-${mn.panel}`).dataset.module = m.id;
    }));
    $$("#modnav .mod").forEach((x) => x.classList.toggle("hidden", !visibleTabs(x.dataset.mod).length));
  }

  // 内核页面里属于某个模块的按钮 / 区块（data-needmod="seo"）：模块开着才显示
  function markNeeded(root) {
    (root || document).querySelectorAll("[data-needmod]").forEach((el) => el.classList.toggle("mod-on", !!byId(el.dataset.needmod)));
  }

  async function init() {
    try { LIST = (await api("/api/modules")).modules || []; } catch { LIST = []; }
    addMenus();
    markNeeded();
    // 一打开就要的 js（出错只影响这个模块）
    for (const m of LIST) {
      for (const f of m.ui.boot_js || []) {
        try { await script(`/m/${m.id}/${f}${ver(m)}`); } catch (e) { console.error("module boot", m.id, e); }
      }
    }
  }

  // 模块的页面：先把 html 放进去（每个 <section id="tab-…"> 换掉占位的空页面），再加载 js —— 只做一次
  function loadModule(mid) {
    if (loaded[mid]) return loaded[mid];
    const m = byId(mid) || { ui: { html: "page.html", page_js: ["page.js"], css: [] }, version: "" };
    loaded[mid] = (async () => {
      for (const f of m.ui.css || []) {
        const l = document.createElement("link"); l.rel = "stylesheet"; l.href = `/m/${mid}/${f}${ver(m)}`; document.head.appendChild(l);
      }
      if (m.ui.html) {
        const r = await fetch(`/m/${mid}/${m.ui.html}${ver(m)}`, { cache: "no-cache" });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const tpl = document.createElement("template");
        tpl.innerHTML = await r.text();
        [...tpl.content.children].forEach((el) => {
          const old = el.id && document.getElementById(el.id);
          if (old && el.tagName === "SECTION") {
            el.classList.toggle("hidden", old.classList.contains("hidden"));
            el.dataset.module = mid; el.dataset.ready = "1";
            old.replaceWith(el);
          } else if (el.tagName === "SECTION" && el.id) {
            el.dataset.module = mid; el.dataset.ready = "1"; if (!el.classList.contains("panel")) el.classList.add("panel", "hidden");
            $("main").appendChild(el);
          } else if (!old) document.body.appendChild(el);
        });
      }
      for (const f of m.ui.page_js || []) await script(`/m/${mid}/${f}${ver(m)}`);
    })();
    loaded[mid].catch(() => { delete loaded[mid]; });
    return loaded[mid];
  }

  async function show(name) {
    const pid = (typeof PANEL_OF !== "undefined" && PANEL_OF[name]) || name;
    const panel = $(`#tab-${pid}`);
    if (!panel || !panel.dataset.module) return;
    const mid = panel.dataset.module;
    try {
      await loadModule(mid);
      const p2 = $(`#tab-${pid}`);
      if (typeof CUR_TAB !== "undefined" && CUR_TAB === name) p2.classList.remove("hidden");
      const M = window.MODS[mid];
      if (M && M.show) await M.show(name, p2);
    } catch (e) {
      const m = byId(mid);
      $(`#tab-${pid}`).innerHTML = `<div class="card"><p class="bad">「<span data-notr>${esc(m ? nm(m) : mid)}</span>」这个模块加载失败：<span data-notr>${esc(e.message || e)}</span></p>
        <p class="small muted">其它功能不受影响。可以在 设置 → 模块管理 里先关掉它，再把这个情况发给开发者。</p></div>`;
      console.error("module", mid, e);
    }
  }

  // 设置页：模块管理 + 各模块的设置卡片（说明书 settings_cards: ["大分类", …]）
  async function settings(cat) {
    if (cat === "modules") return manager();
    for (const m of LIST.filter((x) => (x.settings_cards || []).includes(cat))) {
      let ext = $(`[data-cfgext="${cat}"]`);
      if (!ext) { ext = document.createElement("div"); ext.className = "cfg-ext"; ext.dataset.cfgext = cat; $("#tab-settings").appendChild(ext); }
      ext.classList.remove("hidden");
      let box = ext.querySelector(`[data-modcard="${m.id}"]`);
      if (!box) { box = document.createElement("div"); box.dataset.modcard = m.id; ext.appendChild(box); }
      try {
        await loadModule(m.id);
        const M = window.MODS[m.id];
        if (M && M.settings) await M.settings(box, cat);
      } catch (e) { box.innerHTML = `<p class="bad small">「<span data-notr>${esc(nm(m))}</span>」的设置加载失败：<span data-notr>${esc(e.message || e)}</span></p>`; }
    }
  }

  const BUILTIN = ["商品", "上架导出", "3D 模型", "订单", "生产", "库存", "树脂打印"];
  async function manager() {
    let box = $('[data-cfgext="modules"]');
    if (!box) { box = document.createElement("div"); box.className = "cfg-ext"; box.dataset.cfgext = "modules"; $("#tab-settings").appendChild(box); }
    box.classList.remove("hidden");
    let all = [];
    try { all = (await api("/api/modules?all=1")).modules; } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
    const ids = Object.fromEntries(all.map((m) => [m.id, m]));
    box.innerHTML = `<div class="card"><h3>模块管理</h3>
      <p class="small muted">每个功能是一个模块（一个文件夹）：关掉以后它的菜单、设置、后台任务都不出现，数据保留，再打开就回来。基础模块不能关；关掉一个模块时，依赖它的模块会一起停用。</p>
      <table class="grid"><thead><tr><th>模块名称</th><th>说明</th><th>版本</th><th>依赖</th><th>状态</th></tr></thead><tbody>
      ${all.map((m) => `<tr${m.error ? ' class="st-err"' : ""}><td><b data-notr>${esc(nm(m))}</b></td>
        <td class="small" data-notr>${esc(th() ? m.desc_th || m.desc_zh : m.desc_zh)}${m.error ? `<div class="bad">${esc(m.error)}</div>` : ""}</td>
        <td class="small">${esc(m.version || "")}</td>
        <td class="small" data-notr>${m.depends.map((d) => esc(ids[d] ? nm(ids[d]) : d)).join("、") || "—"}</td>
        <td class="nowrap">${m.core ? '<span class="pill">基础，不能关</span>' : m.error ? '<span class="bad">出错</span>'
          : `<label class="switch-l" style="white-space:nowrap"><input type="checkbox" data-modsw="${esc(m.id)}" ${m.enabled ? "checked" : ""}> ${m.enabled ? "开着" : "关着"}</label>`}</td></tr>`).join("")
        || '<tr><td colspan="5" class="muted">还没有模块</td></tr>'}</tbody></table>
      <p class="small muted" style="margin-top:10px">还没拆成模块的内置功能（接下来几个版本陆续变成模块，到时也可以在这里开关）：${BUILTIN.map((x) => `<span>${x}</span>`).join("、")}</p></div>`;
    box.querySelectorAll("[data-modsw]").forEach((cb) => cb.addEventListener("change", async () => {
      const id = cb.dataset.modsw, on = cb.checked, m = ids[id];
      if (!on && m.dependents.length && !confirm(`关掉「${nm(m)}」，依赖它的模块也会停用：${m.dependents.map((d) => ids[d] ? nm(ids[d]) : d).join("、")}。继续？`)) { cb.checked = true; return; }
      try {
        await api(`/api/modules/${encodeURIComponent(id)}`, { json: { on } });
        toast(on ? "已打开，刷新页面后菜单出现" : "已关闭，刷新页面后菜单消失");
        manager();
      } catch (e) { toast(e.message, true); cb.checked = !on; }
    }));
  }

  window.MODKIT = { init, show, settings, list: () => LIST, load: loadModule, enabled: (id) => !!byId(id), markNeeded };
})();
