"use strict";
// 商品模块：产品库（列表、分组、筛选、批量操作、打开产品）。v2.34 从 static/app.js 搬过来，代码没改。
// ---------------- 产品库 ----------------
let LIB = [], GROUPS = [], LIB_SUM = { n: {}, shops: [], cats: [] }, LIB_VIEWS = [], LIB_SET = {}, LIB_VIEW = 0;
let LIB_SEL_G = {};            // v2.53 自动分组：{段落: 分组键}，几个段落同时选 = 并起来
const LIB_SEL = new Set();
const FST_ZH = { draft: "草稿", reviewed: "未试打", verified: "已验证" };
window.LIB_SEL_IDS = () => LIB_SEL;
// v2.53：左边的分组全部是自动的（按资料 + 平台在线数据现算，修好就自动离开）；只有「要上传 / 要修改」和自定义标签是手动的
const PG_ITEMS = [["incomplete", "资料不全", "bad"], ["print", "待切片 / 待试打", "warn"], ["ready", "可上架", "ok"], ["review", "审核中", ""], ["live", "在售", "ok"], ["down", "已下架 / 被拒", "bad"]];
const TD_ITEMS = [["noimg", "缺图"], ["noword", "缺文案"], ["nocat", "缺类目"], ["nograms", "缺克数"], ["noslice", "没切片"], ["notest", "未试打"], ["license", "许可未核验"], ["rejected", "审核被拒"], ["belowcost", "售价低于成本"], ["lowstock", "在售但库存不够"]];
const SL_ITEMS = [["hot", "热销", "ok"], ["slow", "滞销", "warn"], ["new", "新品", ""], ["lowmargin", "利润低", "bad"]];
async function loadLibrary() {
  // v2.50.1：选品采用的模型先在「选品 → 采集箱」，不进产品库（这里只显示个数和链接）
  const r = await api("/api/goods/library");
  LIB = r.items; LIB_SUM = r.summary; LIB_VIEWS = r.views || []; LIB_SET = r.settings || {};
  GROUPS = (r.tags || []).map((t) => Object.assign(t, { count: LIB_SUM.n["tg:" + t.id] || 0 }));
  const nIn = r.inbox || 0, li = $("#lib-inbox");
  if (li) { li.classList.toggle("hidden", !nIn); $("#lib-inbox-n").textContent = nIn; }
  renderGroups();
  renderLibrary();
}
function catItems(nodes, lvl) {
  return nodes.flatMap((c) => [{ key: "ct:" + c.path, label: c.name, n: c.n, raw: true, indent: lvl }]
    .concat(lvl < 2 && LIB_SEL_G.cat && (LIB_SEL_G.cat === "ct:" + c.path || LIB_SEL_G.cat.startsWith("ct:" + c.path + " > ")) ? catItems(c.kids, lvl + 1) : []));
}
function renderGroups() {
  const n = LIB_SUM.n || {}, tot = LIB_SUM.total || 0;
  const pick = (arr, p) => arr.map(([k, label, tone]) => ({ key: p + k, label, n: n[p + k] || 0, tone: n[p + k] && tone ? tone : "" }));
  const on = n["on:live"] || 0;
  const spec = {
    sel: LIB_SEL_G, views: LIB_VIEWS, viewOn: LIB_VIEW,
    top: [{ key: "", label: "全部", n: tot }, { key: "on:live", label: "在线", n: on, tone: "ok" }, { key: "on:off", label: "未上线", n: n["on:off"] || 0 }],
    shops: (LIB_SUM.shops || []).map((s) => ({ key: s.key, label: (s.platform === "lazada" ? "LZ " : s.platform === "shopee" ? "Shopee " : s.platform + " ") + (s.shop || ""), n: s.n, raw: true })),
    sections: [
      { id: "pg", title: "1. 进度", help: "每个产品只在一个里面：资料不全 → 待切片 / 待试打 → 可上架 → 审核中 → 在售 → 已下架 / 被拒", items: pick(PG_ITEMS, "pg:") },
      { id: "td", title: "2. 待处理", help: "一个产品可以同时在几个里面；修好就自动离开", items: pick(TD_ITEMS.map((x) => [x[0], x[1], "warn"]), "td:") },
      { id: "sl", title: "3. 销售表现（近 30 天）", help: "热销 / 滞销 / 新品 / 利润低的标准在「⚙ 分组标准」里改", items: pick(SL_ITEMS, "sl:") },
      { id: "cat", title: "4. 类目 / 来源", items: catItems(LIB_SUM.cats || [], 0).concat(n["ct:none"] ? [{ key: "ct:none", label: "没选类目", n: n["ct:none"] }] : [])
        .concat([{ key: "src:own", label: "来源：自建", n: n["src:own"] || 0 }, { key: "src:curate", label: "来源：选品采集", n: n["src:curate"] || 0 }]) },
      { id: "mk", title: "5. 手动标记", help: "只有这里是手动的：「要上传」上传成功后自动取消；「要修改」保存产品时会问是否取消", items: [{ key: "mk:upload", label: "⬆ 要上传", n: n["mk:upload"] || 0 }, { key: "mk:edit", label: "✏ 要修改", n: n["mk:edit"] || 0 }]
        .concat(GROUPS.map((x) => ({ key: "tg:" + x.id, label: x.name, n: x.count, raw: true }))),
        foot: '<a class="small" data-gtag-new>＋ 新建标签</a> <a class="small" data-gtag-mgr>管理标签</a>' },
    ],
    foot: '<a class="small" data-grp-clear>清除选择</a>',
  };
  const box = $("#grp-list");
  box.innerHTML = GRP.html(spec);
  GRP.bind(box, spec, () => { LIB_VIEW = 0; renderGroups(); renderLibrary(); });
  $("#lib-grp-pick").innerHTML = GROUPS.map((x) => `<option value="${x.id}" data-notr>${esc(x.name)}</option>`).join("") || '<option value="">（先新建标签）</option>';
  $("#btn-lib-gset").classList.toggle("hidden", !(window.CAN && CAN("settings")));
}
function libFiltered() {
  const q = $("#lib-q").value.trim().toLowerCase();
  const st = $("#lib-status").value, pr = $("#lib-print").value, sort = $("#lib-sort").value;
  let rows = LIB.filter((p) => {
    if (!GRP.match(p, LIB_SEL_G)) return false;
    if (q) {
      const hay = [p.id, p.name_zh, p.title_th, (p.skus || []).join(" "), (p.colors || []).join(" "), p.keywords, p.category, p.material].join(" ").toLowerCase();
      if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    if (st === "ok" && p.errors) return false;
    if (st === "todo" && !p.errors) return false;
    if (st === "exported" && !p.exported) return false;
    if (st === "new" && p.exported) return false;
    if (st === "online" && !(p.online || []).length) return false;          // v2.44：在线商品（从店铺拉回来的）
    if (st === "online_live" && !(p.online || []).some((o) => o.status === "live")) return false;
    if (st === "offline" && (p.online || []).length) return false;
    if (st === "seo_low" && !(p.seo != null && p.seo < 80)) return false;
    if (st === "seo_prop" && !p.seo_prop) return false;
    if (pr === "nomodel" && p.has_model) return false;
    if (pr === "nofile" && ["reviewed", "verified"].includes(p.file_status)) return false;
    if (pr === "reviewed" && p.file_status !== "reviewed") return false;
    if (pr === "verified" && p.file_status !== "verified") return false;
    return true;
  });
  const key = { updated: (p) => -(p.updated_at || 0), id: (p) => p.id, sold: (p) => -(p.sold30 || 0), name: (p) => p.name_zh || "" }[sort];
  rows.sort((a, b) => { const x = key(a), y = key(b); return x < y ? -1 : x > y ? 1 : 0; });
  return rows;
}
function renderLibrary() {
  const rows = libFiltered();
  const gname = Object.fromEntries(GROUPS.map((x) => [x.id, x.name]));
  $("#lib-count").textContent = `${rows.length} / ${LIB.length} 个产品`;
  $("#lib-table tbody").innerHTML = rows.map((p) => `
    <tr class="clickable ${LIB_SEL.has(p.id) ? "sel" : ""}" data-id="${esc(p.id)}">
      <td><input type="checkbox" data-lsel="${esc(p.id)}" ${LIB_SEL.has(p.id) ? "checked" : ""}></td>
      <td>${p.thumb ? `<img class="thumb" src="${esc(p.thumb)}" alt="" loading="lazy">` : ""}</td>
      <td><b data-notr data-p360="${esc(p.id)}">${esc(p.id)}</b>${p.exported ? ' <span class="muted small" title="已导出过，SKU 已锁定">🔒</span>' : ""}
        ${p.draft ? '<div><span class="pill warn-pill" title="选品来的，填好颜色、核对售价后再导出">草稿·待完善</span></div>' : p.from_curator ? '<div class="small muted">来自选品</div>' : ""}</td>
      <td class="lib-name"><span data-notr>${esc(p.name_zh)}</span>${window.SEO ? SEO.badge(p) : ""}${p.title_th ? `<div class="small muted clamp2" data-notr title="${esc(p.title_th)}">${esc(p.title_th)}</div>` : ""}</td>
      <td>${pgPill(p)} ${marksPills(p)} ${(p.groups || []).map((g) => gname[g] ? `<span class="pill tag-pill" data-notr>${esc(gname[g])}</span>` : "").join(" ")}
        <div class="small">${p.lz && p.lz.status !== "none" ? `LZ ${lstBadge(p.lz, "lazada")}` : ""} ${p.sp && p.sp.status !== "none" ? `SP ${lstBadge(p.sp, "shopee")}` : ""}</div>${onlineBadges(p)}</td>
      <td class="small">${skuCell(p)}</td>
      <td>${p.category ? `<span data-notr>${esc(LANG === "th" ? p.category_th || p.category : p.category)}</span>` : '<span class="bad small">未选</span>'}</td>
      <td>${statusBadge(p.errors, p.warnings)}</td>
      <td class="small">${!p.has_model ? '<span class="muted">无模型</span>' : p.file_status ? `<span class="pill fpill-${p.file_status}">${FST_ZH[p.file_status]}</span>` : '<span class="warn">没切片</span>'}</td>
      <td>${p.sold30 || ""}</td>
      <td class="small">${p.updated_at ? fmtTime(p.updated_at).slice(0, 10) : ""}</td>
      <td class="nowrap"><button class="primary-lite" data-edit="${esc(p.id)}">编辑</button> <button data-dup="${esc(p.id)}">复制</button>${CAN("products.delete") ? ` <button class="danger" data-del="${esc(p.id)}">删除</button>` : ""}</td>
    </tr>`).join("");
  $("#lib-empty").classList.toggle("hidden", LIB.length > 0);
  $("#lib-table").classList.toggle("hidden", LIB.length === 0);
  $("#lib-all").checked = rows.length > 0 && rows.every((p) => LIB_SEL.has(p.id));
  $("#lib-selinfo").textContent = LIB_SEL.size ? `已勾选 ${LIB_SEL.size} 个产品` : "勾选产品后批量处理";
  $("#lib-bulk").classList.toggle("on", LIB_SEL.size > 0);
  $("#btn-lib-del").classList.toggle("hidden", !CAN("products.delete"));
}
$("#lib-inbox").addEventListener("click", (e) => { e.preventDefault(); goTab("cur_inbox"); });
["#lib-status", "#lib-print", "#lib-sort"].forEach((k) => $(k).addEventListener("change", renderLibrary));
$("#lib-q").addEventListener("input", renderLibrary);
$("#lib-all").addEventListener("change", (e) => { libFiltered().forEach((p) => (e.target.checked ? LIB_SEL.add(p.id) : LIB_SEL.delete(p.id))); renderLibrary(); });
// ---- 视图（v2.53）：把选的分组 + 搜索 + 下拉筛选存成名字，一键回来 ----
const libState = () => ({ sel: { ...LIB_SEL_G }, q: $("#lib-q").value, status: $("#lib-status").value, print: $("#lib-print").value, sort: $("#lib-sort").value });
function libApply(st) {
  LIB_SEL_G = { ...((st && st.sel) || {}) };
  $("#lib-q").value = (st && st.q) || ""; $("#lib-status").value = (st && st.status) || ""; $("#lib-print").value = (st && st.print) || ""; $("#lib-sort").value = (st && st.sort) || "updated";
}
window.LIB_STATE = { get: libState, set: libApply };
$("#grp-list").addEventListener("click", async (e) => {
  try {
    const t = e.target;
    if (t.closest("[data-grp-clear]")) { LIB_SEL_G = {}; LIB_VIEW = 0; $("#lib-q").value = ""; ["#lib-status", "#lib-print"].forEach((k) => ($(k).value = "")); renderGroups(); return renderLibrary(); }
    const vd = t.closest("[data-grp-vdel]");
    if (vd) { e.stopPropagation(); if (!confirm("删除这个视图？")) return; const r = await api(`/api/goods/views/${vd.dataset.grpVdel}`, { method: "DELETE" }); LIB_VIEWS = r.views; if (LIB_VIEW === +vd.dataset.grpVdel) LIB_VIEW = 0; return renderGroups(); }
    const v = t.closest("[data-grp-view]");
    if (v) { const x = LIB_VIEWS.find((y) => y.id === +v.dataset.grpView); if (x) { libApply(x.state); LIB_VIEW = x.id; renderGroups(); renderLibrary(); } return; }
    if (t.closest("[data-gtag-new]")) {
      const n = prompt("新标签名称（例如：厨房用品、手机配件、定制礼品）"); if (!n) return;
      await api("/api/groups", { json: { name: n } }); return loadLibrary();
    }
    if (t.closest("[data-gtag-mgr]")) return tagManager();
  } catch (err) { toast(err.message, true); }
});
function tagManager() {
  const box = MODAL.open(`<h3>管理标签</h3><p class="small muted">标签是自己起名的手动标记（和采集箱的标签是同一套）。删除标签不会删除产品。</p>
    <div>${GROUPS.map((x) => `<div class="row gap" style="margin:4px 0"><b data-notr style="flex:1">${esc(x.name)}</b><span class="muted small">${x.count}</span><button class="mini" data-gren="${x.id}">改名</button><button class="mini danger" data-gdel="${x.id}">删除</button></div>`).join("") || '<p class="muted">还没有标签</p>'}</div>
    <div class="row gap" style="margin-top:10px"><button data-mclose>关闭</button></div>`);
  box.onclick = async (e) => {
    try {
      const d = e.target.dataset;
      if (d.gdel) { if (!confirm("删除这个标签？产品不会被删除。")) return; await api(`/api/groups/${d.gdel}`, { method: "DELETE" }); delete LIB_SEL_G.mk; MODAL.close(); return loadLibrary(); }
      if (d.gren) { const g = GROUPS.find((x) => String(x.id) === d.gren); const n = prompt("标签名称", g.name); if (!n) return; await api("/api/groups", { json: { id: g.id, name: n } }); MODAL.close(); return loadLibrary(); }
    } catch (err) { toast(err.message, true); }
  };
}
$("#btn-lib-saveview").addEventListener("click", async () => {
  const cur = LIB_VIEWS.find((x) => x.id === LIB_VIEW);
  const n = prompt("视图名称（例如：待上架的小物件）", cur ? cur.name : ""); if (!n) return;
  try { const r = await api("/api/goods/views", { json: { name: n, state: libState() } }); LIB_VIEWS = r.views; LIB_VIEW = (r.views.find((x) => x.name === n.trim().slice(0, 30)) || {}).id || 0; renderGroups(); toast("已保存视图"); }
  catch (err) { toast(err.message, true); }
});
$("#btn-lib-gset").addEventListener("click", () => {
  const S = LIB_SET, f = (k, lab, unit) => `<label class="row gap" style="margin:4px 0"><span style="width:230px">${lab}</span><input type="number" min="0" step="any" data-gs="${k}" value="${S[k]}" style="width:90px"> <span class="muted small">${unit}</span></label>`;
  const box = MODAL.open(`<h3>分组标准</h3><p class="small muted">自动分组用的标准，改了马上生效。</p>
    ${f("hot_min", "热销：近 30 天卖出至少", "件")}${f("hot_top", "热销：或者排进前", "名（至少卖出 1 件）")}${f("slow_days", "滞销：在线超过", "天，近 30 天 0 单")}${f("new_days", "新品：在线不到", "天")}${f("low_margin", "利润低：利润率低于", "%")}${f("low_stock", "在售但库存不够：库存少于", "件")}
    <div class="row gap" style="margin-top:10px"><button class="primary" data-gs-go>保存</button><button data-mclose>取消</button></div>`);
  box.onclick = async (e) => {
    if (!e.target.closest("[data-gs-go]")) return;
    const d = {}; box.querySelectorAll("[data-gs]").forEach((i) => (d[i.dataset.gs] = i.value));
    try { const r = await api("/api/goods/group-settings", { json: d }); LIB_SET = r.settings; MODAL.close(); toast("已保存"); loadLibrary(); } catch (err) { toast(err.message, true); }
  };
});
async function libMark(mark, on) {
  if (!LIB_SEL.size) { toast("请先勾选产品", true); return; }
  let note = "";
  if (on) { note = prompt(`备注（可以不填）：为什么「${mark === "upload" ? "要上传" : "要修改"}」`, ""); if (note === null) return; }
  const r = await api("/api/goods/marks", { json: { ids: [...LIB_SEL], mark, on, note: on ? note : undefined } });
  toast(`${on ? "已标记" : "已取消标记"} ${r.changed} 个产品`); LIB_SEL.clear(); loadLibrary();
}
$("#btn-mk-upload").addEventListener("click", () => libMark("upload", true).catch((e) => toast(e.message, true)));
$("#btn-mk-edit").addEventListener("click", () => libMark("edit", true).catch((e) => toast(e.message, true)));
$("#btn-mk-off").addEventListener("click", async () => {
  const m = prompt("取消哪个标记？输入：上传 或 修改", "上传"); if (!m) return;
  libMark(/修/.test(m) ? "edit" : "upload", false).catch((e) => toast(e.message, true));
});
async function grpAssign(add) {
  const g = $("#lib-grp-pick").value;
  if (!LIB_SEL.size) { toast("请先勾选产品", true); return; }
  if (!g) { toast("请先新建标签", true); return; }
  const r = await api("/api/groups/assign", { json: { ids: [...LIB_SEL], group: +g, add } });
  toast(`${add ? "加上" : "去掉"} ${r.changed} 个产品`); LIB_SEL.clear(); loadLibrary();
}
$("#btn-grp-add").addEventListener("click", () => grpAssign(true).catch((e) => toast(e.message, true)));
$("#btn-lib-clear").addEventListener("click", () => { LIB_SEL.clear(); renderLibrary(); });
// v2.53：不用订单直接生产 / 试打（弹窗在生产模块的 trial.js）
$("#btn-lib-make").addEventListener("click", () => { if (!LIB_SEL.size) { toast("请先勾选产品", true); return; } if (window.TRIAL) TRIAL.stockDialog({ pids: [...LIB_SEL], source: "library" }); });
$("#btn-lib-trial").addEventListener("click", () => { if (window.TRIAL) TRIAL.bulkTrial([...LIB_SEL], "library"); });
$("#btn-lib-zip").addEventListener("click", () => {
  if (!LIB_SEL.size) return;
  location.href = `/api/files/zip?ids=${[...LIB_SEL].map(encodeURIComponent).join(",")}`;
});
$("#btn-lib-del").addEventListener("click", async (e) => {
  const ids = [...LIB_SEL];
  if (!ids.length) return;
  if (!confirmDelete(`选中的 ${ids.length} 个产品（${ids.slice(0, 20).join("、")}${ids.length > 20 ? " …" : ""}）——图片、模型、资料都会删除`)) return;
  await busy(e.target, async () => {
    let n = 0;
    for (const id of ids) {
      try { await api(`/api/products/${encodeURIComponent(id)}`, { method: "DELETE" }); n++; if (P && P.id === id) { P = null; renderEditor(); } }
      catch (err) { toast(`${id}：${err.message}`, true); }
    }
    LIB_SEL.clear(); toast(`已删除 ${n} 个产品`); await loadLibrary();
  });
});
// 「← 返回」（v2.53）：按钮带 data-nav-back="library"，static/nav.js 处理——回到打开这个产品之前的页面（采集箱、上架、订单…），
// 筛选、滚动位置都和原来一样；没有上一页（直接打开链接）才回产品库
$("#btn-grp-rm").addEventListener("click", () => grpAssign(false).catch((e) => toast(e.message, true)));
$("#lib-table").addEventListener("click", async (e) => {
  const cb = e.target.closest("[data-lsel]");
  if (cb) { cb.checked ? LIB_SEL.add(cb.dataset.lsel) : LIB_SEL.delete(cb.dataset.lsel); renderLibrary(); return; }
  if (e.target.closest("td") && e.target.closest("td").cellIndex === 0) return;
  const del = e.target.dataset.del, dup = e.target.dataset.dup;
  if (e.target.dataset.edit) { e.stopPropagation(); return openProduct(e.target.dataset.edit, true); }
  if (del) {
    e.stopPropagation();
    if (!confirmDelete(`产品 ${del}（图片、模型、资料一起删除，编号不会再用）`)) return;
    await api(`/api/products/${del}`, { method: "DELETE" });
    if (P && P.id === del) { P = null; renderEditor(); }
    return loadLibrary();
  }
  if (dup) {
    e.stopPropagation();
    const p = await api(`/api/products/${dup}/duplicate`, { method: "POST" });
    toast(`已复制为 ${p.id}（图片需重新上传）`);
    return loadLibrary();
  }
  const tr = e.target.closest("tr[data-id]");
  if (tr) openProduct(tr.dataset.id);
});
$("#btn-new").addEventListener("click", async () => {
  P = await api("/api/products/new", { method: "POST" });
  dirty = false; ED_EDIT = true; await renderEditor(); showTab("edit");
});

// opt.nav：浏览器后退恢复时 "none"（v2.53，见 static/nav.js）。返回 true = 打开了
async function openProduct(id, edit = false, opt = {}) {
  if (P && dirty && ED_EDIT) {
    if (confirm(`「${P.id}」有修改还没保存，要保存吗？（取消 = 不保存）`)) await saveProduct(true);
  }
  P = await api(`/api/products/${encodeURIComponent(id)}`);
  dirty = false;
  ED_EDIT = !!edit;
  if (window.NAV && !opt.nav) NAV.mark({ hl: id });   // 返回时这一行闪一下
  showTab("edit", opt);          // 先切过去（显示得快），再填内容
  await renderEditor();
  return true;
}
// v2.53：返回产品库时记得当时选的分组（筛选框、排序由 NAV 按 id 自动记）
if (window.NAV) NAV.keep("library", { get: () => ({ sel: { ...LIB_SEL_G }, v: LIB_VIEW }), set: (s) => { LIB_SEL_G = { ...((s && s.sel) || {}) }; LIB_VIEW = (s && s.v) || 0; } });
// v2.42：SKU 多的产品（颜色 × 规格几十个）只显示前 3 个 + 颜色 / 个数，其余点开看，不把整行撑得很高
function skuCell(p) {
  const skus = (p.skus || []).filter(Boolean);
  const cols = [...new Set((p.colors || []).filter(Boolean))];
  const one = (x) => `<div class="mono nowrap" data-notr><span data-p360="${esc(x)}">${esc(x)}</span></div>`;
  if (skus.length <= 3) return skus.map(one).join("");
  const colTxt = cols.length ? ` · ${cols.slice(0, 4).map((c) => esc(typeof colorLabel === "function" ? colorLabel(c) : c)).join(" / ")}${cols.length > 4 ? " …" : ""}` : "";
  return `<div class="nowrap"><b>${skus.length}</b> 个 SKU<span class="muted">${colTxt}</span></div>${skus.slice(0, 2).map(one).join("")}
    <details class="sku-more"><summary class="muted">全部 ${skus.length} 个</summary><div class="sku-grid">${skus.map(one).join("")}</div></details>`;
}
// v2.44：在哪些店铺在线（在线商品页从店铺拉回来的）
function onlineBadges(p) {
  const o = p.online || [];
  if (!o.length) return "";
  const z = { live: "在售", uploaded: "审核中", rejected: "不通过", inactive: "已下架" };
  return `<div class="small">${o.map((x) => `<span class="pill ${x.status === "live" ? "ok-pill" : x.status === "rejected" ? "bad-pill" : "tag-pill"}" title="${esc(x.shop)}">${x.platform === "lazada" ? "LZ" : x.platform === "shopee" ? "SP" : esc(x.platform)} <span data-notr>${esc(x.shop.slice(0, 10))}</span> ${z[x.status] || ""}</span>`).join(" ")}</div>`;
}

// v2.53：进度 / 标记小标签
function pgPill(p) {
  const k = ((p.gk || []).find((x) => x.startsWith("pg:")) || "").slice(3), it = PG_ITEMS.find((x) => x[0] === k);
  return it ? `<span class="pill ${it[2] === "ok" ? "ok-pill" : it[2] === "bad" ? "bad-pill" : it[2] === "warn" ? "warn-pill" : "tag-pill"}">${it[1]}</span>` : "";
}
function marksPills(p) {
  const m = p.marks || {};
  return ["upload", "edit"].filter((k) => m[k]).map((k) => `<span class="pill warn-pill" ${m[k].note ? `title="${esc(m[k].note)}" data-notr-title` : ""}>${k === "upload" ? "⬆ 要上传" : "✏ 要修改"}</span>`).join(" ");
}
// 保存产品时：标了「要修改」就问一句要不要取消（v2.53）
const ASKED = new Set();
window.addEventListener("load", () => {
  const orig = window.saveProduct;
  if (typeof orig !== "function") return;
  window.saveProduct = async function (...a) {
    const r = await orig.apply(this, a);
    try {
      const it = P && LIB.find((x) => x.id === P.id);
      if (P && ((it && it.marks && it.marks.edit) || (P.marks && P.marks.edit)) && !dirty && !a[0] && !ASKED.has(P.id)) {
        ASKED.add(P.id);
        if (confirm(`「${P.id}」标了「要修改」。改好了吗？要取消这个标记吗？`)) {
          await api("/api/goods/marks", { json: { ids: [P.id], mark: "edit", on: false } });
          if (it) { delete it.marks.edit; it.gk = it.gk.filter((x) => x !== "mk:edit"); }
          if (P.marks) delete P.marks.edit;
        }
      }
    } catch (e) { /* 不影响保存 */ }
    return r;
  };
});
