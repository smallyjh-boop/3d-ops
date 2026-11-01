"use strict";
// 商品模块：产品库（列表、分组、筛选、批量操作、打开产品）。v2.34 从 static/app.js 搬过来，代码没改。
// ---------------- 产品库 ----------------
let LIB = [], GROUPS = [], LIB_GROUP = "";
const LIB_SEL = new Set();
const FST_ZH = { draft: "草稿", reviewed: "未试打", verified: "已验证" };
window.LIB_SEL_IDS = () => LIB_SEL;
async function loadLibrary() {
  // v2.50.1：选品采用的模型先在「选品 → 采集箱」，不进产品库（这里只显示个数和链接）
  const [list, g] = await Promise.all([api("/api/products?inbox=all"), api("/api/groups").catch(() => ({ groups: [] }))]);
  LIB = list.filter((p) => !p.inbox); GROUPS = g.groups;
  const nIn = list.length - LIB.length, li = $("#lib-inbox");
  if (li) { li.classList.toggle("hidden", !nIn); $("#lib-inbox-n").textContent = nIn; }
  renderGroups();
  renderLibrary();
}
function renderGroups() {
  const all = LIB.length, none = LIB.filter((p) => !(p.groups || []).length).length;
  $("#grp-list").innerHTML = `<div class="grp ${LIB_GROUP === "" ? "on" : ""}" data-g="">全部产品 <span class="muted">${all}</span></div>
    <div class="grp ${LIB_GROUP === "none" ? "on" : ""}" data-g="none">未分组 <span class="muted">${none}</span></div>` +
    GROUPS.map((x) => `<div class="grp ${String(LIB_GROUP) === String(x.id) ? "on" : ""}" data-g="${x.id}"><span data-notr>${esc(x.name)}</span> <span class="muted">${x.count}</span>
      <span class="grp-act"><a data-gren="${x.id}" title="改名">✎</a><a data-gdel="${x.id}" title="删除">✕</a></span></div>`).join("");
  $("#lib-grp-pick").innerHTML = GROUPS.map((x) => `<option value="${x.id}" data-notr>${esc(x.name)}</option>`).join("") || '<option value="">（先新建分组）</option>';
}
function libFiltered() {
  const q = $("#lib-q").value.trim().toLowerCase();
  const st = $("#lib-status").value, pr = $("#lib-print").value, sort = $("#lib-sort").value;
  let rows = LIB.filter((p) => {
    if (LIB_GROUP === "none" && (p.groups || []).length) return false;
    if (LIB_GROUP && LIB_GROUP !== "none" && !(p.groups || []).map(String).includes(String(LIB_GROUP))) return false;
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
        ${p.draft ? '<div><span class="pill warn-pill" title="选品工具推过来的，填好颜色、核对售价后再导出">草稿·待完善</span></div>' : p.from_curator ? '<div class="small muted">来自选品工具</div>' : ""}</td>
      <td class="lib-name"><span data-notr>${esc(p.name_zh)}</span>${window.SEO ? SEO.badge(p) : ""}${p.title_th ? `<div class="small muted clamp2" data-notr title="${esc(p.title_th)}">${esc(p.title_th)}</div>` : ""}</td>
      <td>${(p.groups || []).map((g) => gname[g] ? `<span class="pill tag-pill" data-notr>${esc(gname[g])}</span>` : "").join(" ")}
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
$("#grp-list").addEventListener("click", async (e) => {
  try {
    if (e.target.dataset.gdel) {
      if (!confirm("删除这个分组？产品不会被删除。")) return;
      await api(`/api/groups/${e.target.dataset.gdel}`, { method: "DELETE" }); LIB_GROUP = ""; return loadLibrary();
    }
    if (e.target.dataset.gren) {
      const g = GROUPS.find((x) => String(x.id) === e.target.dataset.gren);
      const n = prompt("分组名称", g.name); if (!n) return;
      await api("/api/groups", { json: { id: g.id, name: n } }); return loadLibrary();
    }
    const d = e.target.closest("[data-g]");
    if (d) { LIB_GROUP = d.dataset.g; renderGroups(); renderLibrary(); }
  } catch (err) { toast(err.message, true); }
});
$("#btn-grp-new").addEventListener("click", async () => {
  const n = prompt("新分组名称（例如：厨房用品、手机配件、定制礼品）"); if (!n) return;
  try { await api("/api/groups", { json: { name: n } }); loadLibrary(); } catch (err) { toast(err.message, true); }
});
async function grpAssign(add) {
  const g = $("#lib-grp-pick").value;
  if (!LIB_SEL.size) { toast("请先勾选产品", true); return; }
  if (!g) { toast("请先新建分组", true); return; }
  const r = await api("/api/groups/assign", { json: { ids: [...LIB_SEL], group: +g, add } });
  toast(`${add ? "加入" : "移出"} ${r.changed} 个产品`); LIB_SEL.clear(); loadLibrary();
}
$("#btn-grp-add").addEventListener("click", () => grpAssign(true).catch((e) => toast(e.message, true)));
$("#btn-lib-clear").addEventListener("click", () => { LIB_SEL.clear(); renderLibrary(); });
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
$("#btn-ed-back").addEventListener("click", () => goTab("library"));
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

async function openProduct(id, edit = false) {
  if (P && dirty && ED_EDIT) {
    if (confirm(`「${P.id}」有修改还没保存，要保存吗？（取消 = 不保存）`)) await saveProduct(true);
  }
  P = await api(`/api/products/${id}`);
  dirty = false;
  ED_EDIT = !!edit;
  showTab("edit");          // 先切过去（显示得快），再填内容
  await renderEditor();
}
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
