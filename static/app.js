"use strict";
const APP_JS_VERSION = "2.33.0";   // 必须和 app.py 的 VERSION 一致
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

let CFG = null;      // 设置
let CFG_REMBG = false;
let P = null;        // 正在编辑的产品
let CATS = [];       // 类目库
let FIELDS = null;   // 当前类目的属性字段
let dirty = false;
let priceTimer = null, checkTimer = null;

let LANG = "zh";
try { LANG = localStorage.getItem("ui_lang") || "zh"; } catch { /* 无存储时用中文 */ }
const catName = (c) => (LANG === "th" && c.path) ? c.path.split(" > ").slice(-2).join(" > ") : c.name;
const STATUS_TEXT = { auto: "规则/记住", ai: "AI 确定", check: "请确认", missing: "必填缺少", manual: "手动", empty: "留空" };

function toast(msg, isErr = false, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isErr ? " error" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), isErr ? 9000 : ms);
}

// ---- 页面出错时自动记到服务器的运行日志（v2.14.1），测试时方便查原因 ----
(function () {
  let n = 0;
  function report(d) {
    if (n++ > 30) return;      // 一个页面最多报 30 次
    try {
      fetch("/api/client-error", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
        body: JSON.stringify({ ...d, url: location.pathname + location.hash, ver: window.CLIENT_VERSION || "" }) }).catch(() => {});
    } catch { /* 忽略 */ }
  }
  // 被 try/catch 接住、只弹了提示的错误，也记一份带调用位置的（排查用）
  window.reportError3D = (err, where) => report({ msg: `[${where || ""}] ${(err && err.message) || err}`, stack: err && err.stack });
  window.addEventListener("error", (e) => {
    if (!e.message || /ResizeObserver loop/.test(e.message)) return;
    report({ msg: e.message, src: e.filename, line: e.lineno, col: e.colno, stack: e.error && e.error.stack });
  });
  window.addEventListener("unhandledrejection", (e) => {
    const r = e.reason || {};
    if (r && r.status) return;          // 接口返回的业务错误（没权限、参数不对）不算程序出错
    report({ msg: "未处理的异步错误：" + (r.message || String(r)), stack: r.stack });
  });
})();

async function api(url, opts = {}) {
  const o = { ...opts };
  if (o.json !== undefined) {
    o.method = o.method || "POST";
    o.headers = { "Content-Type": "application/json" };
    o.body = JSON.stringify(o.json);
    delete o.json;
  }
  const r = await fetch(url, o);
  let data = null;
  try { data = await r.json(); } catch { /* 非 JSON */ }
  if (r.status === 401 && data && data.login) { location.href = "/login"; throw new Error("请先登录"); }
  if (!r.ok || (data && data.error)) {
    const e = new Error((data && data.error) || `请求失败 ${r.status}`);
    e.status = r.status;
    throw e;
  }
  return data;
}

// 耗时的操作（切片等）放到后台：先拿到任务号，再每 2 秒问一次，直到完成（v2.19）。onTick(秒数) 可以用来显示等了多久。
// 耗时的操作（v2.19 / v2.20）：后台跑，每 1.5 秒问一次进度。任务中心（右上角「任务」）里也能看到；
// 离开这个页面也不会中断，做完任务中心会提示。onTick(秒, 任务) 用来显示读秒和「在电脑 / NAS 上做」。
window.TASK_WATCH = window.TASK_WATCH || new Set();
async function apiJob(url, opts = {}, onTick) {
  const u = url + (url.includes("?") ? "&" : "?") + "async=1";
  const first = await api(u, opts);
  if (!first || !first.job) return first;               // 老版本后台：直接返回结果
  TASK_WATCH.add(first.job);
  if (window.TASKS) TASKS.poke();
  const tick = onTick || BUSY_TICK;
  for (;;) {
    await new Promise((r) => setTimeout(r, 1500));
    let j;
    try { j = await api(`/api/bg/${first.job}`); } catch (e) { if (e.status === 404) throw e; continue; }   // 网络抖一下：继续等
    if (tick) try { tick(j.elapsed, j); } catch { /* 忽略 */ }
    if (j.status === "done") return j.result;
    if (j.status === "error") throw new Error(j.error || "失败");
  }
}
function jobWhere(j) {
  if (!j) return "";
  if (j.stage === "queued") return TR("task.st.queued");
  if (j.stage === "wait_pc") return TR("task.st.wait_pc");
  if (j.where && j.where !== "NAS") return TR("task.on_pc", { name: j.where });
  if (j.where === "NAS") return TR("task.on_nas") + (j.why ? `（${TR("task.why." + j.why)}）` : "");
  return "";
}

// 按钮等待时显示读秒（v2.20）：「处理中… 12 秒 · 电脑 xxx」
let BUSY_TICK = null;
async function busy(btn, fn, label) {
  const old = btn.textContent;
  const t0 = Date.now();
  let extra = "";
  btn.disabled = true;
  const show = () => { btn.textContent = (label ? `${label} ${TR("busy.sec_only", { s: Math.round((Date.now() - t0) / 1000) })}` : TR("busy.sec", { s: Math.round((Date.now() - t0) / 1000) })) + (extra ? " · " + extra : ""); };
  show();
  const h = setInterval(show, 1000);
  const prevTick = BUSY_TICK;
  BUSY_TICK = (_s, j) => { extra = jobWhere(j); show(); };
  try { return await fn(); }
  catch (e) { toast(e.message, true); }
  finally { clearInterval(h); BUSY_TICK = prevTick; btn.disabled = false; btn.textContent = old; }
}
// 没有按钮的等待（例如选了文件就上传）：右下角一直显示「xxx… 12 秒」，做完消失
async function busyToast(label, fn) {
  const t0 = Date.now();
  let extra = "";
  const show = () => { const t = $("#toast"); t.textContent = `${label} ${TR("busy.sec_only", { s: Math.round((Date.now() - t0) / 1000) })}${extra ? " · " + extra : ""}`; t.className = "toast"; clearTimeout(t._h); };
  show();
  const h = setInterval(show, 1000);
  const prevTick = BUSY_TICK;
  BUSY_TICK = (_s, j) => { extra = jobWhere(j); show(); };
  try { return await fn(); }
  finally { clearInterval(h); BUSY_TICK = prevTick; $("#toast").classList.add("hidden"); }
}

document.addEventListener("toggle", (e) => {
  if (e.target.id === "recipe-wrap" && e.target.open && P && window.RECIPE) RECIPE.mount($("#recipe-box"), P.id);
}, true);

// ---------------- 「先看，点修改才能改」 ----------------
// box 里的输入框默认锁住（只能看）；点「✏ 修改」才能改，改完点「保存」或「取消」。
// o: { id, bar: 放按钮的元素, onSave: async () => {}（出错就 throw，会留在修改状态）, onCancel: () => {}（不给就还原原来的值）,
//      label: 修改按钮文字, keep: 一直可以用的元素选择器, onEdit: () => {} }
const LOCKS = {};
function lockBox(box, o) {
  if (!box || !o.bar) return null;
  const st = LOCKS[o.id] || (LOCKS[o.id] = { editing: false });
  st.box = box;
  st.onCancel = o.onCancel;
  const fields = () => [...box.querySelectorAll("input,select,textarea,button")].filter((el) => !(o.keep && el.closest(o.keep)) && !el.closest("[data-lock-skip]"));
  const snap = () => fields().map((el) => (el.type === "checkbox" || el.type === "radio" ? el.checked : el.value));
  st.changed = () => st.editing && st.box.isConnected && JSON.stringify(snap()) !== JSON.stringify(st.snapshot || []);
  function apply() {
    box.classList.toggle("is-locked", !st.editing);
    box.classList.toggle("is-editing", st.editing);
    fields().forEach((el) => {
      if (!st.editing) { if (!el.disabled) { el.disabled = true; el.dataset.lk = "1"; } }
      else if (el.dataset.lk) { el.disabled = false; delete el.dataset.lk; }
    });
    o.bar.innerHTML = st.editing
      ? `<span class="lk-hint">✏ 正在修改</span><button class="primary" data-lk-act="save">💾 保存</button><button data-lk-act="cancel">取消</button>`
      : `<button class="lk-edit" data-lk-act="edit">${o.label || "✏ 修改"}</button>`;
  }
  st.apply = apply;
  o.bar.onclick = async (e) => {
    const b = e.target.closest("[data-lk-act]");
    if (!b) return;
    const act = b.dataset.lkAct;
    if (act === "edit") {
      st.editing = true; apply(); st.snapshot = snap();
      if (o.onEdit) o.onEdit();
      const first = fields().find((el) => /INPUT|TEXTAREA|SELECT/.test(el.tagName) && el.type !== "hidden");
      if (first) first.focus();
    }
    if (act === "cancel") {
      if (st.changed() && !confirm("有修改还没保存，确定放弃？")) return;
      const old = st.snapshot || [];
      st.editing = false;
      if (o.onCancel) { o.onCancel(); }
      else fields().forEach((el, i) => { if (i < old.length) { if (el.type === "checkbox" || el.type === "radio") el.checked = old[i]; else el.value = old[i]; } });
      st.apply();
    }
    if (act === "save") {
      const t = b.textContent; b.disabled = true; b.textContent = "保存中…";
      try { await o.onSave(); st.editing = false; st.apply(); }
      catch (err) { toast(err.message || String(err), true); b.disabled = false; b.textContent = t; }
    }
  };
  apply();
  return { editing: () => st.editing, set: (v) => { st.editing = !!v; apply(); if (v) st.snapshot = snap(); } };
}
// 权限：老板全部有；员工看老板在「账号」里给的
function CAN(key) { return !ME || ME.role === "owner" || !!(ME.perms && ME.perms[key]); }
// 删除要确认两次：先确认，再输入「删除」
function confirmDelete(what) {
  if (!confirm(`确定删除 ${what}？`)) return false;
  const v = prompt(`再次确认：删除后不能恢复。\n请输入「删除」两个字（泰语输入 ลบ 也可以）`, "");
  if (v == null) return false;
  if (!["删除", "ลบ", "delete"].includes(v.trim().toLowerCase())) { toast("输入不对，没有删除", true); return false; }
  return true;
}
function unsavedEdits() { return Object.values(LOCKS).some((x) => x.changed && x.changed()); }
window.addEventListener("beforeunload", (e) => { if (unsavedEdits()) { e.preventDefault(); e.returnValue = ""; } });

// ---------------- 菜单：模块 → 页面 ----------------
let CUR_TAB = null;
const PANEL_OF = {};   // 几个菜单共用一个页面：{菜单: 页面}（v2.30 起模块在说明书里写 menus[].panel）
const LAST_TAB = {};
function visibleTabs(mod) {
  return $$(`#subnav .tab[data-mod="${mod}"]`).filter((b) => !b.classList.contains("role-hidden") && !b.classList.contains("ghost"));
}
// v2.27：搬进设置的旧页面
const TAB_ALIAS = { users: "accounts", csext: "accounts" };
function showTab(name) {
  if (name === "edit" && !P) name = "library";
  if (TAB_ALIAS[name]) { CFG_MOD = TAB_ALIAS[name]; name = "settings"; }
  const btn = $(`#subnav .tab[data-tab="${name}"]`);
  const mod = btn ? btn.dataset.mod : "goods";
  LAST_TAB[mod] = name;
  CUR_TAB = name;
  $$("#modnav .mod").forEach((b) => b.classList.toggle("active", b.dataset.mod === mod));
  $$("#subnav .tab").forEach((b) => {
    b.classList.toggle("hidden", b.dataset.mod !== mod || b.classList.contains("role-hidden") || b.classList.contains("ghost"));
    b.classList.toggle("active", b.dataset.tab === name || (name === "edit" && b.dataset.tab === "library"));
  });
  $("#subnav").classList.toggle("single", visibleTabs(mod).length <= 1);
  const panel = PANEL_OF[name] || name;      // 采购的几个页面共用一个页面（v2.21）
  $$(".panel").forEach((p) => p.classList.toggle("hidden", p.id !== "tab-" + panel));
  if (name === "library") loadLibrary();
  if (name === "export" && typeof loadExport === "function") { loadExport(); if (window.loadStockPending) window.loadStockPending(); }   // v2.31：导出页在「上架导出」模块
  if (name === "settings") renderSettings();
  if (name === "logs") loadAudit();
  if (window.OPS) window.OPS.show(name);
  if (window.INV) window.INV.show(name);
  if (window.MODKIT) window.MODKIT.show(name);       // v2.29：模块的页面（第一次打开时才加载）
  try { history.replaceState(null, "", "#" + name); } catch { /* 忽略 */ }
}
async function goTab(name) {
  if (unsavedEdits() && !confirm("有修改还没保存（点「保存」才会生效），确定离开？")) return;
  Object.values(LOCKS).forEach((x) => { if (x.editing && !(x.box && x.box.isConnected && name === CUR_TAB)) x.editing = false; });
  if (dirty && P && name !== "edit") {
    if (confirm(`「${P.id}」有修改还没保存，要保存吗？（取消 = 不保存）`)) await saveProduct(true);
    else { dirty = false; try { P = await api(`/api/products/${P.id}`); } catch { /* 已删除 */ } }
    ED_EDIT = false;
  } else if (name !== "edit") ED_EDIT = false;
  showTab(name);
}
$$("#subnav .tab").forEach((b) => b.addEventListener("click", () => goTab(b.dataset.tab)));
$$("#modnav .mod").forEach((b) => b.addEventListener("click", () => {
  const tabs = visibleTabs(b.dataset.mod);
  const last = LAST_TAB[b.dataset.mod];
  goTab(tabs.some((t) => t.dataset.tab === last) ? last : (tabs[0] || {}).dataset.tab);
}));

function statusBadge(errors, warnings) {
  if (errors) return `<span class="pill bad-pill">待补 ${errors} 项</span>`;
  return `<span class="pill ok-pill">可导出</span>` + (warnings ? ` <span class="muted small">${warnings} 条提醒</span>` : "");
}

// ---------------- 产品库 ----------------
let LIB = [], GROUPS = [], LIB_GROUP = "";
const LIB_SEL = new Set();
const FST_ZH = { draft: "草稿", reviewed: "未试打", verified: "已验证" };
window.LIB_SEL_IDS = () => LIB_SEL;
async function loadLibrary() {
  const [list, g] = await Promise.all([api("/api/products"), api("/api/groups").catch(() => ({ groups: [] }))]);
  LIB = list; GROUPS = g.groups;
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
      <td><b data-notr>${esc(p.id)}</b>${p.exported ? ' <span class="muted small" title="已导出过，SKU 已锁定">🔒</span>' : ""}
        ${p.draft ? '<div><span class="pill warn-pill" title="选品工具推过来的，填好颜色、核对售价后再导出">草稿·待完善</span></div>' : p.from_curator ? '<div class="small muted">来自选品工具</div>' : ""}</td>
      <td><span data-notr>${esc(p.name_zh)}</span>${window.SEO ? SEO.badge(p) : ""}${p.title_th ? `<div class="small muted" data-notr>${esc(p.title_th.slice(0, 50))}</div>` : ""}</td>
      <td>${(p.groups || []).map((g) => gname[g] ? `<span class="pill tag-pill" data-notr>${esc(gname[g])}</span>` : "").join(" ")}
        <div class="small">${p.lz && p.lz.status !== "none" ? `LZ ${lstBadge(p.lz, "lazada")}` : ""} ${p.sp && p.sp.status !== "none" ? `SP ${lstBadge(p.sp, "shopee")}` : ""}</div></td>
      <td class="small mono" data-notr>${(p.skus || []).map(esc).join("<br>")}</td>
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

// ---------------- 编辑器 ----------------
function getPath(obj, path) { return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj); }
function setPath(obj, path, val) {
  const ks = path.split(".");
  let o = obj;
  ks.slice(0, -1).forEach((k) => { if (o[k] == null || typeof o[k] !== "object") o[k] = {}; o = o[k]; });
  o[ks[ks.length - 1]] = val;
}
function markDirty() { dirty = true; $("#ed-dirty").textContent = "（未保存）"; scheduleCheck(); if (window.SEO) SEO.schedule(); }

// 选品工具推过来的产品：原站、许可、参考价、原始文件（v2.12）
function renderSource() {
  const s = P && P.source;
  if (!s) { $("#ed-source").innerHTML = ""; return; }
  const rp = s.reference_price || {};
  const files = (P.source_files || []).map((f) => `<a class="btn mini-btn" href="/files/${encodeURIComponent(P.id)}/source_files/${encodeURIComponent(f.name)}" data-notr>⬇ ${esc(f.name)}</a>`).join(" ");
  const specs = (P.variants || []).filter((v) => v.model_file !== undefined && v.opt2_zh);
  const seen = new Set();
  const specRows = specs.filter((v) => !seen.has(v.opt2_zh) && seen.add(v.opt2_zh)).map((v) => `<div class="small">规格 <b data-notr>${esc(v.opt2_zh)}</b>：${v.model_file ? `模型 <a href="/files/${encodeURIComponent(P.id)}/source_files/${encodeURIComponent(v.model_file)}" data-notr>${esc(v.model_file)}</a>` : esc(v.model_note || "用产品的 3D 模型")}${v.grams ? ` · ${v.grams} g` : ' · <span class="warn">克数待补</span>'}${v.hours ? ` · ${v.hours} h` : ' · <span class="warn">时长待补</span>'}</div>`).join("");
  $("#ed-source").innerHTML = `<div class="card src-card">${P.draft ? `<p class="warn"><b>草稿·待完善</b>：这个产品是 3D选品工具推过来的。请在「变体」里填好颜色（会自动生成 SKU 和售价），核对类目属性后再导出上架。</p>${(P.variants || []).some((v) => !v.grams || !v.hours) ? '<p class="warn small">有规格还没有克数 / 打印时长：在「变体」里按模型估算或切片后补上，成本和售价才准。</p>' : ""}` : ""}
    <div class="small">来源：<b data-notr>${esc(s.platform || s.source || "")}</b>${s.source_id ? ` <span class="muted" data-notr>#${esc(s.source_id)}</span>` : ""}${s.linked_manually ? ' <span class="muted">（手动建档，补传文件时对上）</span>' : ""}${s.author ? ` · 作者 <span data-notr>${esc(s.author)}</span>` : ""}
      ${s.source_url ? ` · <a href="${esc(s.source_url)}" target="_blank" rel="noopener">原站页面</a>` : ""}
      ${s.license_name ? `· 许可 <span data-notr>${esc(s.license_name)}</span>` : ""}${s.license_verified ? ' <span class="ok">✔ 已核验可商用</span>' : ""}
      ${rp.suggested || rp.target ? ` · 选品阶段参考价 <span data-notr>฿${esc(rp.target || rp.suggested)}</span>（只参考，售价按 ERP 成本算）` : ""}</div>
    ${s.title_original ? `<div class="small muted" data-notr>${esc(s.title_original)}</div>` : ""}
    ${files ? `<div class="row gap wrap" style="margin-top:6px"><span class="small">原始文件：</span>${files}</div>` : ""}
    ${specRows ? `<div style="margin-top:6px">${specRows}<div class="small muted">每个规格单独切片：在「打印方案 / 切片文件」上传切片文件时选对应的 SKU。</div></div>` : ""}</div>`;
}
async function renderEditor() {
  if (!CFG) { try { await loadConfig(); } catch (e) { console.warn("设置读取失败", e); } }   // 页面刚打开、设置还没读到就进了编辑页
  $("#ed-body").classList.toggle("hidden", !P);
  if (!P) { $("#ed-title").textContent = I18N.t("未选择产品（到产品库新建或打开）"); return; }
  $("#ed-title").textContent = `${P.id}  ${P.name_zh || ""}`;
  applyEdLock();
  P.copy = P.copy || {}; P.category = P.category || {}; P.attributes = P.attributes || {};
  // 泰文界面：「变体名称」编辑的是平台上显示的泰文（v2.19.1）；没填时先放常用说法
  if (window.I18N && I18N.lang === "th") {
    const VAR_TH = { "颜色": "สี", "色": "สี", "规格": "ตัวเลือก", "尺寸": "ขนาด", "大小": "ขนาด", "款式": "แบบ", "型号": "รุ่น", "套装": "ชุด" };
    for (const n of [1, 2]) {
      const el = document.querySelector(`[data-f="variation${n}_name_zh"], [data-f="copy.variation${n}_name_th"]`);
      if (!el) continue;
      el.dataset.f = `copy.variation${n}_name_th`;
      const zh = (P[`variation${n}_name_zh`] || "").trim();
      if (!P.copy[`variation${n}_name_th`] && zh && VAR_TH[zh]) P.copy[`variation${n}_name_th`] = VAR_TH[zh];
    }
  }
  $$("#tab-edit [data-f]").forEach((el) => {
    const v = getPath(P, el.dataset.f);
    el.value = v == null ? "" : v;
  });
  $("#opt-map").value = Object.entries(P.copy.options_th || {}).map(([k, v]) => `${k}=${v}`).join("\n");
  $("#kw-th").value = (P.copy.search_keywords_th || []).join(", ");
  updateTitleCount(); updatePreview(); renderPackage(); renderKw(); if (window.SEO) SEO.schedule();
  if (window.RECIPE) { const rw = $("#recipe-wrap"); if (rw && rw.open) RECIPE.mount($("#recipe-box"), P.id); else if ($("#recipe-box")) $("#recipe-box").dataset.pid = ""; }
  renderVariants(); renderImages();
  renderModel();
  renderSource();
  renderCuratorCopy();
  await renderCategory();
  renderShopeeCat();
  refreshPricing(); runCheck();
  applyEdLock();
}
// 产品编辑页：打开时只能看，点「✏ 修改产品」才能改（打印方案有自己的「修改」按钮）
let ED_EDIT = false;
function applyEdLock() {
  const body = $("#ed-body"), rw = $("#recipe-wrap");
  const walk = (el) => { for (const c of el.children) { if (rw && c === rw) continue; if (rw && c.contains(rw)) walk(c); else c.inert = !ED_EDIT; } };
  walk(body);
  body.classList.toggle("ed-view", !ED_EDIT);
  $("#btn-save").classList.toggle("hidden", !ED_EDIT);
  $("#btn-ed-cancel").classList.toggle("hidden", !ED_EDIT);
  $("#btn-ed-edit").classList.toggle("hidden", ED_EDIT || !P);
  $("#ed-dirty").textContent = ED_EDIT ? (dirty ? "（✏ 修改中，未保存）" : "（✏ 修改中）") : "";
}
function setEdEdit(on) { ED_EDIT = !!on; applyEdLock(); }

$$("#tab-edit [data-f]").forEach((el) => el.addEventListener("input", () => {
  if (!P) return;
  let v = el.value;
  if (el.type === "number") v = v === "" ? null : Number(v);
  setPath(P, el.dataset.f, v);
  if (el.dataset.pkg !== undefined) { P.package_status = "manual"; renderPackage(); }
  markDirty();
  if (el.dataset.f === "copy.title_th" || el.dataset.f === "copy.title_shopee_th") updateTitleCount();
  if (el.dataset.f === "copy.description_th") updatePreview();
  if (/^copy\.(title|description|hashtags)/.test(el.dataset.f)) scheduleKw();
  if (el.dataset.f === "markup") schedulePricing();
  if (el.dataset.f === "name_zh") $("#ed-title").textContent = `${P.id}  ${P.name_zh || ""}`;
}));
$("#opt-map").addEventListener("input", () => {
  const m = {};
  $("#opt-map").value.split("\n").forEach((line) => {
    const i = line.indexOf("=");
    if (i > 0) m[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  });
  P.copy.options_th = m;
  markDirty();
});

function renderPackage() {
  const st = P.package_status;
  $("#pkg-box").classList.toggle("is-check", st === "check" || st === "default");
  $("#btn-pkg-ok").classList.toggle("hidden", !(st === "check" || st === "ai" || st === "default"));
  $("#pkg-note").innerHTML = st === "check" && P.package_src === "spec_ref" ? '<span class="bad">按选品工具的规格尺寸估算（多零件产品，尺寸只是最大零件的参考值），请核对后点「确认尺寸」</span>'
    : st === "check" ? '<span class="bad">AI 估算的包裹尺寸，请核对后点「确认尺寸」</span>'
    : st === "ai" && P.package_src === "spec" ? '<span>按选品工具的规格尺寸估算（最大规格 + 1 cm 余量）</span>'
    : st === "ai" ? '<span>AI 根据产品尺寸估算</span>'
    : st === "default" ? '<span class="bad">还是默认值，请填写实际包裹尺寸（或让 AI 估算）</span>'
    : "包裹重量 = 变体克数 + 包材重量，自动计算。";
}
$("#btn-pkg-ok").addEventListener("click", () => { P.package_status = "manual"; renderPackage(); markDirty(); });

function updateTitleCount() {
  const n = (P.copy.title_th || "").length;
  $("#cnt-title").innerHTML = `${n} 字符` + (n < 5 || n > 255 ? ' <span class="bad">（需 5-255）</span>' : "");
  const m = (P.copy.title_shopee_th || "").length;
  $("#cnt-title-sp").innerHTML = m ? `${m} 字符` + (m < 20 || m > 120 ? ' <span class="bad">（需 20-120）</span>' : "") : "";
}

// ---------------- 关键词扩展 ----------------
const KW_GROUPS = [["need", "买家想要什么"], ["core", "核心词"], ["synonym", "同义词/口语"], ["english", "英文词"], ["attribute", "属性词"],
  ["scene", "场景/用途"], ["audience", "人群/送礼"], ["longtail", "长尾词"], ["custom", "自己添加"]];
let kwTimer = null;
function scheduleKw() { clearTimeout(kwTimer); kwTimer = setTimeout(renderKw, 400); }
function kwNorm(s) { return String(s || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, "").toLowerCase(); }
function renderKw() {
  const plan = P && P.keyword_plan, box = $("#kw-panel");
  if (!plan) { box.classList.add("hidden"); box.innerHTML = ""; return; }
  box.classList.remove("hidden");
  const c = P.copy || {};
  const t = kwNorm((c.title_th || "") + " " + (c.title_shopee_th || ""));
  const d = kwNorm((c.description_th || "") + " " + (c.title_en || "") + " " + (c.description_en || "") + " " + (c.hashtags_shopee || ""));
  let total = 0, inTitle = 0, used = 0;
  const groups = KW_GROUPS.filter(([k]) => (plan[k] || []).length || k === "custom").map(([k, name]) => {
    const chips = (plan[k] || []).map((w, i) => {
      const n = kwNorm(w), st = n && t.includes(n) ? "title" : n && d.includes(n) ? "desc" : "none";
      total++; if (st === "title") inTitle++; if (st !== "none") used++;
      return `<span class="kw ${st}" data-notr>${esc(w)}<span class="rm" data-kwrm="${k}|${i}" title="删除">×</span></span>`;
    }).join("");
    return `<div class="kw-group"><b>${name}</b><div>${chips}${k === "custom" ? '<input id="kw-add" placeholder="＋ 添加词，回车" style="width:150px;padding:2px 6px;font-size:12px">' : ""}</div></div>`;
  }).join("");
  box.innerHTML = `<div class="row between wrap gap"><b>搜索关键词（${total} 个）</b>
      <span class="small kw-legend"><span class="kw title">在标题里</span><span class="kw desc">在详情/英文/标签里</span><span class="kw none">还没用上</span>
      覆盖率：标题 ${total ? Math.round(inTitle / total * 100) : 0}%，全部 ${total ? Math.round(used / total * 100) : 0}%</span></div>
    ${plan.title_core ? `<div class="small">标题开头主词：<b data-notr>${esc(plan.title_core)}</b></div>` : ""}
    ${plan.notes_zh ? `<div class="muted small" data-notr>${esc(L({ zh: plan.notes_zh, th: plan.notes_th }))}</div>` : ""}
    ${groups}
    ${(plan.avoid || []).length ? `<div class="small bad">不要用：<span data-notr>${esc(plan.avoid.join("、"))}</span></div>` : ""}
    <div class="muted small">灰色的词还没用上。可以删掉不合适的词、在「自己添加」里加必须用的词，再点「🔍 AI 搜索优化」重新生成（标题放最重要的，其他自然地写进详情和标签）。</div>`;
}
$("#kw-panel").addEventListener("click", (e) => {
  const rm = e.target.dataset.kwrm; if (!rm) return;
  const [k, i] = rm.split("|");
  P.keyword_plan[k].splice(Number(i), 1);
  markDirty(); renderKw();
});
$("#kw-panel").addEventListener("keydown", (e) => {
  if (e.target.id !== "kw-add" || e.key !== "Enter") return;
  const w = e.target.value.trim(); if (!w) return;
  P.keyword_plan.custom = P.keyword_plan.custom || [];
  if (!P.keyword_plan.custom.includes(w)) P.keyword_plan.custom.push(w);
  markDirty(); renderKw(); $("#kw-add").focus();
});
function mergeKeywordsField(plan) {
  // ①「关键词」：保留自己写的，再补上 AI 扩展的（去重）
  const mine = String(P.keywords || "").split(/[,，、\n]+/).map((x) => x.trim()).filter(Boolean);
  const all = [...mine];
  for (const [k] of KW_GROUPS) for (const w of plan[k] || []) if (!all.some((x) => x.toLowerCase() === w.toLowerCase())) all.push(w);
  P.keywords = all.slice(0, 60).join(", ");
  const el = document.querySelector('[data-f="keywords"]'); if (el) el.value = P.keywords;
}
$("#btn-kw").addEventListener("click", async (e) => {
  if (!P.name_zh || !P.features_zh) return toast("先填写产品名称和用途/卖点", true);
  if (P.keyword_plan && !confirm("重新扩展会替换现在的关键词列表（自己添加的会保留），继续？")) return;
  await busy(e.target, async () => {
    const r = await apiJob(`/api/products/${P.id}/keywords`, { json: P });
    const custom = (P.keyword_plan && P.keyword_plan.custom) || [];
    P.keyword_plan = { ...r.plan, custom };
    mergeKeywordsField(P.keyword_plan);
    markDirty(); await saveProduct(true); renderKw();
    toast("关键词已扩展，并补进①的关键词。下一步点「AI 生成文案」");
  });
});
function updatePreview() {
  const html = (P.copy.description_th || "").replace(/<(?!\/?(p|ul|ol|li|strong|b|br|em)\b)[^>]*>/gi, "");
  $("#desc-preview").innerHTML = html;
}

// 变体
function renderVariants() {
  const imgs = P.images || [];
  const opts = (sel) => ['<option value="">—</option>']
    .concat(imgs.map((im, i) => `<option value="${esc(im.raw)}" ${im.raw === sel ? "selected" : ""}>图 ${i + 1}</option>`)).join("");
  $("#var-table tbody").innerHTML = P.variants.map((v, i) => `
    <tr data-i="${i}">
      <td>${i + 1}</td>
      <td class="nowrap">${swatch(v.opt1_zh, "var-sw")}<input data-v="opt1_zh" list="color-list" value="${esc(uiOpt1(v.opt1_zh))}" placeholder="${isTH() ? "สีขาว" : "白色"}" style="width:100px" data-notr title="${esc(v.opt1_zh || "")}"></td>
      <td class="nowrap">${specCell(v)}${specBadge(v)}</td>
      <td class="mono small c-sku">${esc(v.sku || "")}</td>
      <td class="nowrap"><input data-v="grams" type="number" step="0.1" value="${v.grams ?? ""}" style="width:70px">${v.grams_src === "est" ? '<span class="src src-est" title="估算值">估</span>' : v.grams_src === "sliced" ? '<span class="src src-sliced" title="来自切片结果">切</span>' : ""}</td>
      <td><input data-v="hours" type="number" step="0.05" value="${v.hours ?? ""}" style="width:65px"></td>
      <td><input data-v="manual_price" type="number" step="1" value="${v.manual_price ?? ""}" style="width:80px"></td>
      <td><input data-v="stock" type="number" step="1" value="${v.stock ?? ""}" placeholder="${CFG ? CFG.default_stock : ""}" style="width:60px"></td>
      <td><select data-v="image">${opts(v.image)}</select></td>
      <td class="c-cost"></td><td class="c-sug"></td><td class="c-final"></td><td class="c-profit"></td><td class="c-mk"></td>
      <td><button class="danger" data-rm="${i}">✕</button></td>
    </tr>`).join("");
  renderColorChips();
  renderSpecReview();
  scheduleStockInfo();
  const managed = specsManaged();
  $("#btn-add-spec").classList.remove("hidden");
  $("#btn-ren-spec").classList.toggle("hidden", !renamableSpecs().length);
  $("#spec-lock-note").textContent = (managed ? (isTH() ? "แบบจากเครื่องมือคัดเลือกสินค้าจะซิงค์มาเอง แบบที่เพิ่มที่นี่จะถูกเก็บไว้ " : "选品工具的规格会自动同步；在这里加的规格标「ERP 自加」，同步时保留。") : "") +
    (isTH() ? `ข้อจำกัดแพลตฟอร์ม: ชื่อตัวเลือก ≤ 20 ตัวอักษร, แต่ละชั้น ≤ 20 ตัวเลือก, รวม ≤ 50 SKU` : `平台限制：选项名最多 20 字，颜色 / 规格各最多 20 个，合计最多 50 个 SKU`);
}
// v2.22：规格只能从已有的规格里选（或者「＋ 加规格」），不能随手打字加出「其它规格」
function specsManaged() { return !!(P.specs && P.specs.length); }
// 能在 ERP 里改名的规格：选品工具管理的商品只能改 ERP 自己加的
function renamableSpecs() {
  if (!specsManaged()) return specList();
  const cur = new Set((P.specs || []).filter((x) => x.source !== "erp").map((x) => x.name_zh));
  return specList().filter((s) => !cur.has(s));
}
const VAR_LIMIT = { len: 20, each: 20, sku: 50 };
function overLimit(addRows, addColors = 0, addSpecs = 0) {
  const nc = new Set(P.variants.map((v) => (v.opt1_zh || "").trim())).size + addColors;
  const ns = specList().length + addSpecs;
  if (nc > VAR_LIMIT.each) return isTH() ? `สีเกิน ${VAR_LIMIT.each} ตัวเลือก` : `颜色最多 ${VAR_LIMIT.each} 个（平台限制）`;
  if (ns > VAR_LIMIT.each) return isTH() ? `แบบเกิน ${VAR_LIMIT.each} ตัวเลือก` : `规格最多 ${VAR_LIMIT.each} 个（平台限制）`;
  if (P.variants.length + addRows > VAR_LIMIT.sku) return isTH() ? `รวมเกิน ${VAR_LIMIT.sku} SKU (ข้อจำกัด Lazada/Shopee) แยกเป็นสองสินค้าได้` : `合计会超过 ${VAR_LIMIT.sku} 个 SKU（Lazada / Shopee 限制），可以拆成两个商品`;
  return "";
}
function specList() {
  const out = [];
  for (const v of P.variants) { const s = (v.opt2_zh || "").trim(); if (s && !out.includes(s)) out.push(s); }
  return out;
}
function specCell(v) {
  const sp = (P.specs || []).find((x) => x.name_zh === (v.opt2_zh || "").trim());
  if (specsManaged() && sp && sp.source === "erp") return `<span data-notr>${esc(uiOpt2(v.opt2_zh))}</span> <span class="src src-est">${isTH() ? "เพิ่มใน ERP" : "ERP 自加"}</span>`;
  if (specsManaged()) return `<span data-notr title="${esc(v.opt2_zh || "")}">${esc(uiOpt2(v.opt2_zh)) || "—"}</span>`;
  const cur = (v.opt2_zh || "").trim();
  return `<select data-v2 data-notr style="width:110px"><option value="">—</option>${specList().map((s) => `<option value="${esc(s)}" ${s === cur ? "selected" : ""}>${esc(uiOpt2(s))}</option>`).join("")}
    <option value="__new">${isTH() ? "＋ แบบใหม่…" : "＋ 新规格…"}</option></select>`;
}
function colorsOf(spec) { return P.variants.filter((v) => (v.opt2_zh || "").trim() === spec).map((v) => (v.opt1_zh || "").trim()); }
function dupCombo() {
  const seen = new Set();
  for (const v of P.variants) { const k = (v.opt1_zh || "").trim() + "|" + (v.opt2_zh || "").trim(); if (seen.has(k)) return k.replace("|", " · ") || "—"; seen.add(k); }
  return "";
}
function askSpecName(msg, def = "") {
  const n = (prompt(msg, def) || "").trim();
  if (!n) return "";
  if (specList().includes(n)) { toast(isTH() ? `มีแบบ「${n}」อยู่แล้ว` : `已经有规格「${n}」了`, true); return ""; }
  if (COLORS[n]) { toast(isTH() ? "นี่คือชื่อสี ให้เพิ่มเป็นสี" : "这是颜色名：颜色请用上面的颜色点选或「＋ 其它颜色」", true); return ""; }
  return n.slice(0, 20);
}
function specBadge(v) {
  const s = (P.specs || []).find((x) => x.spec_id && x.spec_id === v.spec_id);
  if (!s) return "";
  if (s.status === "review") return `<span class="src src-est">${TR("spec.badge_review")}</span>`;
  if (s.status === "removed_pending") return `<span class="src src-est">${TR("spec.badge_removed")}</span>`;
  return "";
}
// 泰文界面：表格里的颜色、规格显示泰文（系统内部仍用中文做键，导出时用泰文）；改的时候泰文写回「选项泰文」（v2.19.1）
const isTH = () => !!(window.I18N && I18N.lang === "th");
function uiOpt1(zh) { return isTH() && zh ? colorLabel(String(zh).trim()) : (zh || ""); }
function optTh(zh) {
  if (!zh) return "";
  const m = (P.copy && P.copy.options_th) || {};
  if (m[zh]) return m[zh];
  const s = (P.specs || []).find((x) => x.name_zh === zh && x.name_th);
  return s ? s.name_th : zh;
}
function uiOpt2(zh) { return isTH() ? optTh(zh) : (zh || ""); }
function colorKeyFrom(text) {
  const t = String(text || "").trim(); if (!t) return "";
  if (COLORS[t]) return t;
  const n = (x) => String(x || "").replace(/\s+/g, "").replace(/^สี/, "").toLowerCase();
  const hit = Object.keys(COLORS).find((zh) => [COLORS[zh].th, COLORS[zh].en, COLORS[zh].code].some((x) => x && n(x) === n(t)));
  return hit || t;
}
// ---- 颜色点选 ----
function swatch(name, cls = "") {
  if (!name || !String(name).trim()) return `<span class="sw ${cls}" style="background:transparent;border-style:dashed"></span>`;
  const ci = colorInfo(String(name).trim());
  const extra = (ci.code === "RB" || ci.code === "RND") ? " rb" : ci.code === "CL" ? " cl" : "";
  return `<span class="sw ${cls}${extra}" style="background:${esc(ci.hex || "#ccc")}"></span>`;
}
function colorLabel(zh) {
  const c = COLORS[zh] || {};
  return (window.I18N && window.I18N.lang === "th" && c.th) ? c.th : zh;
}
function renderColorChips() {
  const used = new Set(colorList());
  $("#color-chips").innerHTML = Object.keys(COLORS).map((zh) =>
    `<span class="chip ${used.has(zh) ? "on" : ""}" data-color="${esc(zh)}" data-notr title="${esc((COLORS[zh].th || "") + " · " + (COLORS[zh].en || ""))}">${swatch(zh)}${esc(colorLabel(zh))}</span>`).join("");
  renderViewChips();
}
function renderViewChips() {
  const box = $("#view-chips"); if (!box) return;
  const mine = colorList();
  const rest = Object.keys(COLORS).filter((z) => !mine.includes(z));
  const cur = box.dataset.cur || mine[0] || "";
  box.innerHTML = mine.concat(rest).map((zh, i) =>
    `<span class="chip ${zh === cur ? "on" : ""}" data-vc="${esc(zh)}" data-notr ${i === mine.length && mine.length ? 'style="margin-left:10px"' : ""}>${swatch(zh)}${esc(colorLabel(zh))}</span>`).join("");
}
$("#color-chips").addEventListener("click", (e) => {
  const chip = e.target.closest("[data-color]"); if (!chip) return;
  const zh = chip.dataset.color;
  const has = P.variants.some((v) => (v.opt1_zh || "").trim() === zh);
  if (has) {
    const rest = P.variants.filter((v) => (v.opt1_zh || "").trim() !== zh);
    if (!rest.length) { P.variants[0].opt1_zh = ""; }
    else {
      const locked = P.variants.some((v) => (v.opt1_zh || "").trim() === zh && P.exported_at && v.sku);
      if (locked && !confirm(`「${zh}」的 SKU 已经导出过，确定删除这个颜色的变体？`)) return;
      P.variants = rest;
    }
    if (isRandomColor(zh)) P.random_off = true;          // 自己删掉了随机颜色：以后加颜色不再自动加回来
  } else {
    addColorRows(zh);
    const rnd = randomColorName();
    if (isRandomColor(zh)) P.random_off = false;
    else if (rnd && CFG.random_color_auto !== false && !P.random_off && !colorList().includes(rnd)) addColorRows(rnd);   // 每个规格自动加「随机颜色」
    // 随机颜色放在最后
    P.variants = P.variants.filter((v) => !isRandomColor(v.opt1_zh)).concat(P.variants.filter((v) => isRandomColor(v.opt1_zh)));
    if (!(P.variation1_name_zh || "").trim()) { P.variation1_name_zh = "颜色"; const f = document.querySelector('[data-f="variation1_name_zh"]'); if (f) f.value = "颜色"; }
  }
  markDirty(); renderVariants(); refreshPricing();
  previewColor(has ? (colorList()[0] || "") : zh);
  if (P.model) { const sc = $("#snap-color"); if (sc) sc.innerHTML = (colorList().length ? colorList() : ["默认"]).map((c) => `<option data-notr>${esc(c)}</option>`).join(""); }
});
// 加一个颜色：还没颜色的行（例如选品工具推过来的多规格：每个规格一行）全部填上，否则每个规格加一行
function addColorRows(zh) {
  const blanks = P.variants.filter((v) => !(v.opt1_zh || "").trim());
  if (blanks.length) { blanks.forEach((v) => (v.opt1_zh = zh)); return; }
  const lim = overLimit(Math.max(1, specList().length), 1, 0);
  if (lim) { toast(lim, true); return false; }
  const first = P.variants[0] || {};
  const seen = new Set(), sizes = [];
  for (const v of P.variants) { const k = (v.spec_id || "") + "|" + (v.opt2_zh || ""); if (!seen.has(k)) { seen.add(k); sizes.push(v); } }
  for (const like0 of sizes) {
    const like = like0 || first;
    P.variants.push({ opt1_zh: zh, opt2_zh: like.opt2_zh || "", spec_id: like.spec_id, grams: like.grams ?? 0, hours: like.hours ?? 0,
      grams_src: like.grams_src, manual_price: like.manual_price ?? null, image: "", stock: null, sku: "" });
  }
}
function randomColorName() { return Object.keys(COLORS).find((z) => COLORS[z].code === "RND") || ""; }
function isRandomColor(zh) { const c = COLORS[String(zh || "").trim()]; return !!(c && c.code === "RND"); }

// 选品工具整理好的商品文案（选品工具 2.2）+ 侵权提示
function renderCuratorCopy() {
  const box = $("#curator-copy"); if (!box) return;
  const L0 = P.curator_listing, ir = P.ip_risk;
  let h = "";
  if (ir && (ir.items || []).length) {
    const terms = ir.items.map((x) => `<b data-notr>${esc(x.term)}</b>${x.reason ? `<span class="muted" data-notr>（${esc(x.reason)}）</span>` : ""}`).join("、");
    h += ir.status === "pending"
      ? `<div class="warnbox small">${TR("ip.pending")}：${terms}<div class="row gap" style="margin-top:4px">
           <button class="mini primary-lite" data-ip="ok">${TR("ip.ok")}</button><span class="muted">${TR("ip.hint")}</span></div></div>`
      : `<div class="muted small">${TR("ip.done")}：${terms} <button class="mini" data-ip="pending">${TR("ip.undo")}</button></div>`;
  }
  if (L0) {
    const th = window.I18N && I18N.lang === "th";
    const g = (k) => L0[k + (th ? "_th" : "_zh")] || L0[k + (th ? "_zh" : "_th")];
    const li = (a) => (a || []).map((x) => `<li>${esc(x)}</li>`).join("");
    h += `<details class="small" style="margin:6px 0"><summary>${TR("cl.title")}${L0.method ? `（${esc(L0.method)}）` : ""}</summary><div data-notr>
      ${g("title") ? `<p><b>${esc(g("title"))}</b></p>` : ""}${g("intro") ? `<p>${esc(g("intro"))}</p>` : ""}
      ${(g("highlights") || []).length ? `<ul>${li(g("highlights"))}</ul>` : ""}
      ${(g("scenes") || []).length ? `<p>🏠 ${esc(g("scenes").join("、"))}</p>` : ""}
      ${g("package") ? `<p>📦 ${esc(g("package"))}</p>` : ""}
      ${(g("notes") || []).length ? `<ul class="muted">${li(g("notes"))}</ul>` : ""}
      ${(g("keywords") || []).length ? `<p class="muted">🔍 ${esc(g("keywords").join(", "))}</p>` : ""}</div>
      <p class="muted">${TR("cl.hint")}</p></details>`;
  }
  box.innerHTML = h;
}
$("#curator-copy").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-ip]"); if (!b) return;
  await busy(b, async () => {
    if (dirty) await saveProduct(true);
    const r = await api(`/api/products/${P.id}/ip-risk`, { json: { action: b.dataset.ip } });
    P = r.product; dirty = false; renderCuratorCopy(); runCheck();
  });
});

// 规格待确认（选品工具 AI 识别没把握、名字里有颜色词、选品工具删掉了）
function renderSpecReview() {
  const box = $("#spec-review"); if (!box) return;
  const used = new Set((P.variants || []).map((v) => v.spec_id));
  const list = (P.specs || []).filter((s) => used.has(s.spec_id) && (s.status === "review" || s.status === "removed_pending"));
  const why = (s) => (s.rcodes && s.rcodes.length ? s.rcodes.map((x) => TR(x[0]) + (x[1] || "")) : (s.reasons || [])).join("；");
  box.innerHTML = list.length ? `<div class="warnbox small"><b>${TR("spec.need_confirm", { n: list.length })}</b>${TR("spec.need_confirm_tail")}` +
    list.map((s) => `<div class="row gap wrap" style="margin-top:4px"><span data-notr><b>${esc(s.name_zh)}</b>${s.name_th ? " / " + esc(s.name_th) : ""}</span>
      <span class="muted">${esc(why(s))}${s.recognize && s.recognize.evidence ? `<span data-notr>（${esc(s.recognize.evidence)}）</span>` : ""}</span>
      ${s.status === "review"
        ? `<button class="mini primary-lite" data-spec="${esc(s.spec_id)}" data-act="ok">${TR("spec.ok")}</button><button class="mini danger" data-spec="${esc(s.spec_id)}" data-act="delete">${TR("spec.delete")}</button>`
        : `<button class="mini danger" data-spec="${esc(s.spec_id)}" data-act="delete">${TR("spec.delete_all")}</button><button class="mini" data-spec="${esc(s.spec_id)}" data-act="keep">${TR("spec.keep")}</button>`}</div>`).join("") +
    `<div class="muted" style="margin-top:4px">${TR("spec.rename_hint")}</div></div>` : "";
}
$("#spec-review").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-spec]"); if (!b) return;
  if (b.dataset.act === "delete" && !confirm(TR("spec.confirm_delete"))) return;
  await busy(b, async () => {
    if (dirty) await saveProduct(true);
    const url = `/api/products/${P.id}/specs/${encodeURIComponent(b.dataset.spec)}/${b.dataset.act}`;
    let r;
    try { r = await api(url, { method: "POST" }); }
    catch (err) { if (err.status !== 409 || !confirm(err.message)) throw err; r = await api(url + "?force=1", { method: "POST" }); }
    P = r.product; dirty = false; await renderEditor(); toast(TR("spec.done"));
  });
});

// 库存：按耗材自动算（v2.16）
let STOCK_T = null;
// 库存说明（服务器给编号 + 数字，按界面语言显示）
function stockWhy(x) {
  if (!x.why) return x.reason || "";
  return x.why.map(([k, v]) => TR(k, { ...v, c: v && v.c === "@all" ? TR("stock.r.all_colors") : (typeof colorLabel === "function" && v && v.c ? colorLabel(v.c) : (v || {}).c) })).join("");
}
window.stockWhy = stockWhy;
function scheduleStockInfo() { clearTimeout(STOCK_T); STOCK_T = setTimeout(loadStockInfo, 400); }
async function loadStockInfo() {
  if (!P || !$("#stock-auto-sel")) return;
  let r;
  try { r = await api(`/api/products/${P.id}/stock`); } catch { return; }
  $("#stock-auto-sel").value = r.own === true ? "on" : r.own === false ? "off" : "default";
  $("#stock-auto-sel option[value=default]").textContent = TR("stock.follow", { s: TR(r.global ? "stock.on" : "stock.off") });
  $("#stock-auto-note").textContent = r.auto
    ? TR("stock.note_auto", { cap: r.settings.cap, low: r.settings.low_line, mode: TR(r.settings.low_mode === "zero" ? "stock.mode_zero" : "stock.mode_real") })
    : TR("stock.note_manual");
  const rows = $$("#var-table tbody tr");
  r.rows.forEach((x, i) => {
    const inp = rows[i] && rows[i].querySelector('[data-v="stock"]'); if (!inp) return;
    inp.disabled = !!r.auto;
    if (r.auto) { inp.value = ""; inp.placeholder = String(x.stock); inp.title = stockWhy(x); inp.setAttribute("data-notr", ""); }   // 说明已按界面语言生成
    else { inp.placeholder = String(CFG ? CFG.default_stock : ""); inp.title = ""; inp.value = P.variants[i] && P.variants[i].stock != null ? P.variants[i].stock : ""; }
  });
}
$("#stock-auto-sel").addEventListener("change", async (e) => {
  const mode = e.target.value;
  try {
    if (dirty) await saveProduct(true);
    const r = await api(`/api/products/${P.id}/stock-auto`, { json: { mode } });
    P = r.product; dirty = false; $("#ed-dirty").textContent = "";
    loadStockInfo();
  } catch (err) { toast(err.message, true); }
});

// 让 3D 预览显示某个颜色（点颜色色块、输入颜色时都会调用）
function previewColor(zh) {
  $("#view-chips").dataset.cur = zh || ""; renderViewChips();
  if (!VIEWER || !VIEWER.model) return;
  const ci = colorInfo(zh || "");
  VIEWER.setColor(ci.hex, ci.code);
}
$("#view-chips").addEventListener("click", (e) => {
  const chip = e.target.closest("[data-vc]"); if (!chip) return;
  if (!VIEWER || !VIEWER.model) return toast("先上传 3D 模型", true);
  previewColor(chip.dataset.vc);
});
$("#var-table").addEventListener("input", (e) => {
  const k = e.target.dataset.v; if (!k) return;
  const i = Number(e.target.closest("tr").dataset.i);
  let v = e.target.value;
  if (e.target.type === "number") v = v === "" ? null : Number(v);
  if (k === "opt1_zh" && isTH()) v = colorKeyFrom(v);              // 泰文 / 英文颜色名 → 系统里的颜色
  if (k === "opt2_zh" && isTH() && (P.variants[i].opt2_zh || "").trim()) {
    // 泰文界面改规格名：改的是平台上显示的泰文，同一规格的所有颜色一起改
    const zh = P.variants[i].opt2_zh.trim();
    P.copy = P.copy || {}; P.copy.options_th = { ...(P.copy.options_th || {}), [zh]: String(v).trim() };
    const om = $("#opt-map"); if (om) om.value = Object.entries(P.copy.options_th).map(([a, b]) => `${a}=${b}`).join("\n");
    markDirty(); schedulePricing();
    return;
  }
  P.variants[i][k] = v;
  if (k === "grams" || k === "hours") delete P.variants[i].grams_src;
  if (k === "opt1_zh") { const sw = e.target.parentElement.querySelector(".sw"); if (sw) sw.outerHTML = swatch(v, "var-sw"); renderColorChips(); if (COLORS[String(v).trim()]) previewColor(String(v).trim()); }
  markDirty();
  schedulePricing();
});
$("#var-table").addEventListener("click", (e) => {
  if (e.target.dataset.rm === undefined) return;
  if (P.variants.length <= 1) return toast("至少保留一个变体", true);
  P.variants.splice(Number(e.target.dataset.rm), 1);
  markDirty(); renderVariants(); refreshPricing();
});
$("#btn-add-color").addEventListener("click", () => {
  let n = (prompt(isTH() ? "ชื่อสี (เช่น สีเขียวมิ้นต์)" : "颜色名字（颜色表里没有的，例如 薄荷绿）：") || "").trim();
  if (!n) return;
  n = colorKeyFrom(n);
  if (colorList().includes(n)) return toast(isTH() ? "มีสีนี้แล้ว" : "已经有这个颜色了", true);
  addColorRows(n);
  if (!(P.variation1_name_zh || "").trim()) { P.variation1_name_zh = "颜色"; const f = document.querySelector('[data-f="variation1_name_zh"]'); if (f) f.value = "颜色"; }
  markDirty(); renderVariants(); refreshPricing();
});
$("#btn-add-spec").addEventListener("click", () => {
  const specs = specList();
  if (!specs.length) {
    // 第一次加规格：现在的变体是什么规格？
    const cur = askSpecName(isTH() ? "ตัวเลือกที่มีอยู่ตอนนี้เป็นแบบอะไร (เช่น เล็ก)" : "现在这些变体是什么规格？（例如 小号）");
    if (!cur) return;
    P.variants.forEach((v) => (v.opt2_zh = cur));
  }
  const n = askSpecName(isTH() ? "ชื่อแบบใหม่ (เช่น ใหญ่ / ชุด 3 ชิ้น)" : "新规格的名字（例如 大号 / 3 个装）：");
  if (!n) { if (!specs.length) { markDirty(); renderVariants(); } return; }
  const colors = [...new Set(P.variants.map((v) => (v.opt1_zh || "").trim()))];
  const lim = overLimit(colors.length || 1, 0, 1);
  if (lim) { if (!specs.length) { markDirty(); renderVariants(); } return toast(lim, true); }
  const like = P.variants[0] || {};
  for (const c of colors.length ? colors : [""]) {
    P.variants.push({ opt1_zh: c, opt2_zh: n, grams: like.grams ?? 0, hours: like.hours ?? 0, grams_src: like.grams_src, manual_price: null, image: "", stock: null, sku: "" });
    if (specsManaged()) P.specs.push({ spec_id: "", name_zh: n, source: "erp", status: "ok" });
  }
  if (!(P.variation2_name_zh || "").trim()) { P.variation2_name_zh = "规格"; const f = document.querySelector('[data-f="variation2_name_zh"]'); if (f) f.value = "规格"; }
  markDirty(); renderVariants(); refreshPricing();
  toast(isTH() ? `เพิ่มแบบ「${n}」แล้ว ทุกสีอย่างละแถว ใส่กรัม/ราคา แล้วเลือกโมเดลที่「แต่ละแบบใช้โมเดลไหน」` : `已加规格「${n}」（每个颜色一行）。记得改克数 / 价格；这个规格是别的模型的话，到 ③「规格用哪个模型」选`, false, 8000);
});
$("#btn-ren-spec").addEventListener("click", () => {
  const specs = renamableSpecs(); if (!specs.length) return;
  const old = (prompt((isTH() ? "จะเปลี่ยนชื่อแบบไหน: " : "要改哪个规格：") + specs.join(" / "), specs[0]) || "").trim();
  if (!old || !specs.includes(old)) return;
  const n = askSpecName(isTH() ? "ชื่อใหม่" : "新名字：", old);
  if (!n) return;
  P.variants.forEach((v) => { if ((v.opt2_zh || "").trim() === old) v.opt2_zh = n; });
  (P.specs || []).forEach((x) => { if (x.source === "erp" && x.name_zh === old) x.name_zh = n; });
  if (P.copy && P.copy.options_th && P.copy.options_th[old]) { P.copy.options_th[n] = P.copy.options_th[old]; delete P.copy.options_th[old]; }
  markDirty(); renderVariants(); refreshPricing();
});
$("#var-table").addEventListener("change", (e) => {
  if (e.target.dataset.v2 === undefined) return;
  const i = Number(e.target.closest("tr").dataset.i);
  let val = e.target.value;
  if (val === "__new") {
    val = askSpecName(isTH() ? "ชื่อแบบใหม่" : "新规格的名字：");
    if (!val) { renderVariants(); return; }
  }
  const old = P.variants[i].opt2_zh;
  P.variants[i].opt2_zh = val;
  const d = dupCombo();
  if (d) { P.variants[i].opt2_zh = old; renderVariants(); return toast(isTH() ? `ซ้ำกับแถวอื่น (${d})` : `和别的行重复了（${d}），同一个颜色 + 规格只能有一行`, true); }
  markDirty(); renderVariants(); refreshPricing();
});
$("#btn-regen-sku").addEventListener("click", async (e) => {
  await busy(e.target, async () => {
    try {
      P = await api(`/api/products/${P.id}/regen-skus`, { json: P });
    } catch (err) {
      if (err.status !== 409 || !confirm(err.message)) throw err;
      P = await api(`/api/products/${P.id}/regen-skus?force=1`, { json: P });
    }
    dirty = false; await renderEditor(); toast("SKU 已重新生成");
  });
});

function schedulePricing() { clearTimeout(priceTimer); priceTimer = setTimeout(refreshPricing, 300); }
async function refreshPricing() {
  if (!P || !CFG) return;
  const res = await api("/api/pricing", { json: P });
  const rows = $$("#var-table tbody tr");
  res.rows.forEach((r, i) => {
    const tr = rows[i]; if (!tr) return;
    const c = r.cost || {};
    if (!P.exported_at) P.variants[i].sku = res.skus[i];
    const code = res.colors[i];
    const opt = (P.variants[i].opt1_zh || "").trim();
    tr.querySelector(".c-sku").innerHTML = esc(P.variants[i].sku || res.skus[i]) +
      (opt && !code ? '<br><span class="warn" title="不在颜色表里，用了自动代码。可到设置页颜色表添加">非标准颜色</span>' : "");
    tr.querySelector(".c-cost").innerHTML = `<span title="材料 ${c.material} + 机时 ${c.machine} + 包材 ${c.packaging} + 失败损耗 ${c.failure}">${c.total}</span>`;
    tr.querySelector(".c-sug").textContent = r.suggested_price;
    tr.querySelector(".c-final").innerHTML = `<b>${r.final_price}</b>` + (r.list_price !== r.final_price ? `<br><span class="muted small">划线 ${r.list_price}</span>` : "");
    tr.querySelector(".c-profit").textContent = r.profit;
    const mk = r.actual_markup == null ? "" : Math.round(r.actual_markup * 100) + "%";
    tr.querySelector(".c-mk").innerHTML = r.warning ? `<span class="bad" title="${esc(r.warning)}">${mk || "!"} ⚠</span>` : `<span class="ok">${mk}</span>`;
  });
  const s = res.summary;
  if (!s) { $("#price-note").textContent = ""; return; }
  $("#price-note").textContent = `材料 ${s.thb_per_gram} 铢/克，机时 ${s.machine_hour_cost} 铢/小时，平台扣点 ${(CFG.platform_fee_rate * 100).toFixed(0)}%。鼠标停在成本上可看拆分。`;
}

// 图片
function imgSrc(im) { return `/files/${P.id}/${im.processed ? "out" : "raw"}/${encodeURIComponent(im.file)}?t=${P.updated_at}`; }
function renderImages() {
  const imgs = P.images || [];
  $("#img-grid").innerHTML = imgs.map((im, i) => `
    <div class="img-card" data-raw="${esc(im.raw)}">
      <img src="${imgSrc(im)}" alt="">
      <div><span class="tag">${i === 0 ? "主图" : "图 " + (i + 1)}</span>${im.edited ? '<span class="tag">已修图</span>' : ""}${im.scene ? '<span class="tag">场景图</span>' : ""}${im.ad ? '<span class="tag ad-tag">卖点图</span>' : ""}${im.processed ? '<span class="ok">已处理</span>' : '<span class="warn">原图</span>'}
        ${im.url ? '<span class="ok"> · 有网址</span>' : ""}</div>
      <div class="acts">
        <button data-act="left" title="前移">◀</button><button data-act="right" title="后移">▶</button>
        ${im.ad ? '<button data-act="ad-edit">✏ 改卖点图</button>' : '<button data-act="edit" title="裁剪尺寸、调色、去背景、去水印 / 杂物、换背景加阴影、批量处理">🎨 修图</button><button data-act="ad-new" title="用这张图做卖点图">✨ 加卖点</button><button data-act="white">设为白底图</button>'}${im.has_orig ? '<button data-act="restore" title="恢复修图前的原图">↺ 原图</button>' : ""}<button data-act="url">网址</button>
        <button data-act="del" class="danger">删</button>
      </div>
    </div>`).join("") || '<span class="muted">还没有图片</span>';
  const w = P.white_bg;
  $("#white-box").innerHTML = w ? `
    <div class="img-card" data-raw="__white__"><img src="/files/${P.id}/out/${encodeURIComponent(w.file)}?t=${P.updated_at}" alt="">
      <div><span class="tag">白底图</span>${w.url ? '<span class="ok">有网址</span>' : ""}</div>
      <div class="acts"><button data-act="url">网址</button></div></div>` : "";
  if (window.sceneRefresh) window.sceneRefresh();
}
async function imageAction(e) {
  const act = e.target.dataset.act; if (!act) return;
  const raw = e.target.closest(".img-card").dataset.raw;
  if (dirty) await saveProduct(true);
  const order = (P.images || []).map((i) => i.raw);
  const idx = order.indexOf(raw);
  if (act === "edit") {
    if (!window.IMGEDIT) return;
    return IMGEDIT.open({ pid: P.id, raw, src: imgSrc(P.images[idx]), getP: () => P,
      onSaved: (np) => { P = np; renderImages(); } }).catch((err) => toast(err.message, true));
  }
  if (act === "restore") {
    if (!confirm("恢复修图前的原图？现在这张修过的图会被替换。")) return;
    try { P = await api(`/api/products/${P.id}/images/restore`, { json: { raw } }); renderImages(); toast("已恢复原图"); } catch (err) { toast(err.message, true); }
    return;
  }
  if (act === "ad-new" || act === "ad-edit") {
    if (!window.ADIMG) return;
    return act === "ad-new" ? window.ADIMG.open({ base: raw }) : window.ADIMG.edit(P.images[idx]);
  }
  try {
    if (act === "left" || act === "right") {
      const j = act === "left" ? idx - 1 : idx + 1;
      if (j < 0 || j >= order.length) return;
      [order[idx], order[j]] = [order[j], order[idx]];
      P = await api(`/api/products/${P.id}/images/reorder`, { json: { order } });
    } else if (act === "del") {
      if (!confirm("删除这张图片？")) return;
      order.splice(idx, 1);
      P = await api(`/api/products/${P.id}/images/reorder`, { json: { order } });
    } else if (act === "white") {
      await busy(e.target, async () => {
        P = await apiJob(`/api/products/${P.id}/images/white`, { json: { raw, remove_bg: CFG_REMBG } });
        if (!CFG_REMBG) toast("未安装去背景组件：白底图只补了白边。原图背景不是纯白时请先安装去背景组件。", true);
      });
    } else if (act === "url") {
      const cur = raw === "__white__" ? (P.white_bg || {}).url : (P.images[idx] || {}).url;
      const url = prompt("图片网址（可粘贴 Lazada 图片空间或其他图床网址）", cur || "");
      if (url === null) return;
      P = await api(`/api/products/${P.id}/images/url`, { json: { raw, url } });
    }
  } catch (err) { return toast(err.message, true); }
  renderImages(); renderVariants(); refreshPricing(); runCheck();
}
$("#img-grid").addEventListener("click", imageAction);
$("#btn-adimg").addEventListener("click", () => { if (!(P.images || []).length) return toast("先上传商品图片", true); window.ADIMG && window.ADIMG.open({}); });
$("#white-box").addEventListener("click", imageAction);

$("#img-input").addEventListener("change", async (e) => {
  const files = e.target.files; if (!files.length) return;
  if (dirty) await saveProduct(true);
  const fd = new FormData();
  [...files].forEach((f) => fd.append("files", f));
  try {
    P = await api(`/api/products/${P.id}/images`, { method: "POST", body: fd });
    renderImages(); renderVariants(); refreshPricing(); runCheck();
    toast(`已上传 ${files.length} 张`);
  } catch (err) { toast(err.message, true); }
  e.target.value = "";
});
async function processAll(btn, removeBg) {
  if (!(P.images || []).length) return toast("先上传图片", true);
  if (dirty) await saveProduct(true);
  await busy(btn, async () => {
    const r = await apiJob(`/api/products/${P.id}/images/process`, { json: { remove_bg: removeBg } });
    P = r.product; renderImages(); runCheck();
    toast(`已处理 ${r.processed} 张（处理后需重新上传图床）`);
  });
}
$("#btn-proc").addEventListener("click", (e) => processAll(e.target, false));
$("#btn-proc-bg").addEventListener("click", (e) => {
  if (!CFG_REMBG) return toast("去背景组件还没安装：关闭程序，双击 3_install_bg_removal.bat 安装后再启动。", true);
  processAll(e.target, true);
});
$("#btn-host").addEventListener("click", async (e) => {
  if (dirty) await saveProduct(true);
  if ((P.images || []).some((i) => !i.processed) && !confirm("有图片还没处理成方图，直接上传原图？")) return;
  await busy(e.target, async () => {
    const r = await apiJob(`/api/products/${P.id}/images/host`, { method: "POST" });
    P = r.product; renderImages(); renderVariants(); refreshPricing(); runCheck();
    toast(`已上传 ${r.uploaded} 张到图床`);
  });
});

// ---------------- 3D 模型 ----------------
let VIEWER = null, VIEWER_PID = null, LAST_SLICE = null;
// 商品图渲染尺寸：按设置页「输出尺寸」，至少 1200
function RS() { return Math.max(1200, Math.min(2000, Number(CFG && CFG.image_size) || 1200)); }
function FILL() { const f = Number(CFG && CFG.image_fill_ratio); return f > 0.3 && f <= 0.98 ? f : 0.85; }
function model3dReady() {
  return new Promise((res) => { if (window.Model3D) res(); else window.addEventListener("model3d-ready", res, { once: true }); });
}
function colorList() {
  const seen = [];
  (P.variants || []).forEach((v) => { const c = (v.opt1_zh || "").trim(); if (c && !seen.includes(c)) seen.push(c); });
  return seen;
}
function colorInfo(name) {
  if (COLORS[name]) return COLORS[name];
  const k = Object.keys(COLORS).find((z) => z.replace(/色$/, "") === String(name).replace(/色$/, "") || COLORS[z].th === name || (COLORS[z].en || "").toLowerCase() === String(name).toLowerCase());
  if (k) return COLORS[k];
  // 不在颜色表里：按名字里的关键字猜一个颜色（中/泰/英）
  const n = String(name).toLowerCase();
  const guess = [[/荧光|neon|นีออน/, null], [/粉|pink|ชมพู/, "PK"], [/紫|purple|ม่วง/, "PU"], [/红|red|แดง/, "RD"],
    [/橙|orange|ส้ม/, "OR"], [/黄|yellow|เหลือง/, "YL"], [/绿|green|เขียว/, "GN"], [/天蓝|浅蓝|sky|ฟ้า/, "SB"],
    [/蓝|blue|น้ำเงิน/, "BL"], [/黑|black|ดำ/, "BK"], [/灰|gr[ae]y|เทา/, "GY"], [/银|silver|เงิน/, "SV"],
    [/金|gold|ทอง/, "GD"], [/棕|咖|brown|น้ำตาล/, "BR"], [/米|beige|เบจ/, "BG"], [/透明|clear|ใส/, "CL"],
    [/木|wood|ไม้/, "WD"], [/彩虹|rainbow|รุ้ง/, "RB"], [/白|white|ขาว/, "WH"]];
  const neon = /荧光|neon|นีออน/.test(n);
  for (const [re, code] of guess) {
    if (!code || !re.test(n)) continue;
    const base = Object.values(COLORS).find((c) => c.code === code);
    if (!base) continue;
    if (!neon) return base;
    const neonHex = { PK: "#ff4fa3", GN: "#5cff3a", YL: "#f4ff2a", OR: "#ff7a1a", BL: "#2fb8ff", RD: "#ff2e4d", PU: "#b84dff" }[code];
    return { ...base, hex: neonHex || base.hex };
  }
  return { hex: "#cfcfcf", code: "" };
}
document.addEventListener("click", (e) => {
  if (e.target.id !== "btn-model-lib" || !P) return;
  if (window.FILES && FILES.openLib) FILES.openLib(P.id);
});
// 模型库里换了 3D 模型：编辑页正在看这个产品就重新载入
window.addEventListener("model-changed", async (e) => {
  if (!P || e.detail !== P.id) return;
  try {
    const fresh = await api(`/api/products/${encodeURIComponent(P.id)}`);
    P.model = fresh.model; P.model_lib = fresh.model_lib; P.edit_rev = fresh.edit_rev;
    await renderModel();
  } catch (err) { if (window.reportError3D) window.reportError3D(err, "编辑页刷新模型"); }
});
async function renderModel() {
  const m = P.model;
  $("#model-body").classList.toggle("hidden", !m);
  $("#model-empty").classList.toggle("hidden", !!m);
  $("#printer-select").innerHTML = (CFG.printers || []).map((p, i) => `<option value="${i}" ${i === (CFG.default_printer || 0) ? "selected" : ""}>${esc((p.code ? p.code + " · " : "") + p.name)}</option>`).join("");
  const cols = colorList();
  $("#snap-color").innerHTML = (cols.length ? cols : ["默认"]).map((c) => `<option data-notr>${esc(c)}</option>`).join("");
  $("#view-chips").dataset.cur = cols[0] || ""; renderViewChips();
  renderAdvice();
  LAST_SLICE = null;
  renderEstimate();
  // v2.22：规格用哪个模型 / 主模型换成模型库里的另一个
  if (window.SPECMODEL) SPECMODEL.mount($("#spec-model-box"), P.id, {
    onChange: async (mainChanged) => {
      if (!mainChanged) return;
      P = await api(`/api/products/${P.id}`); VIEWER_PID = null; await renderModel();
    } }).catch(() => {});
  if (!m) return;
  await model3dReady();
  if (!VIEWER) VIEWER = new window.Model3D.Viewer($("#viewer"));
  const key = `${P.id}/${m.file}/${m.uploaded_at}`;
  if (VIEWER_PID === key) { if (VIEWER.model) { const c = colorInfo(cols[0] || ""); VIEWER.setColor(c.hex, c.code); } return; }
  VIEWER_PID = key;
  $("#model-info").innerHTML = '<span class="muted">正在加载模型…</span>';
  try {
    // 先显示服务器精简过的预览模型（大模型几乎马上出来），放大看细节 / 出商品图时再换完整模型
    const metrics = await VIEWER.loadFast(`/api/products/${encodeURIComponent(P.id)}/model/preview?t=${m.uploaded_at}`,
      { url: `/files/${P.id}/model/${encodeURIComponent(m.file)}?t=${m.uploaded_at}`, ext: m.ext, fallback: `/api/products/${encodeURIComponent(P.id)}/model/stl?t=${m.uploaded_at}` });
    VIEWER.setPrint(printOpts());
    const c0 = colorInfo(cols[0] || "");
    VIEWER.setColor(c0.hex, c0.code);
    $("#viewer-safe").checked = VIEWER.safe;
    // 部分显卡会把模型画成全黑：用浅灰色检测一次，异常就自动切到兼容模式
    const cur = VIEWER._lastColor;
    VIEWER.setColor("#cccccc", "");
    if (VIEWER.checkBlack()) { $("#viewer-safe").checked = true; toast("检测到显卡显示异常，已自动切换到兼容显示模式"); }
    VIEWER.setColor(...cur);
    const r = await api(`/api/products/${P.id}/model/metrics`, { json: metrics });
    P.model = r.product.model;
    renderEstimate();
  } catch (err) {
    $("#model-info").innerHTML = `<span class="bad">模型读取失败：${esc(err.message)}</span>`;
  }
}
function renderEstimate() {
  const m = P.model || {}, e = m.estimate, s = (m.metrics || {}).size;
  $("#model-info").innerHTML = s ? `<div data-notr><b>${esc(m.orig_name || m.file)}</b></div>
    <div>尺寸（宽×深×高）：<b>${s[0]} × ${s[1]} × ${s[2]} mm</b>　体积：${e ? e.volume_cm3 : "-"} cm³</div>
    <div class="row gap"><button class="mini" id="btn-size-fill">填入产品尺寸和包裹尺寸</button></div>` : "";
  let h = "";
  if (e) {
    h += `<table class="grid est-table"><thead><tr><th>打印机</th><th>估算克数</th><th>估算时长</th></tr></thead><tbody>` +
      e.per_printer.map((x) => `<tr><td data-notr>${esc(x.name)}</td><td>${x.grams} g</td><td>${x.hours} h</td></tr>`).join("") +
      `</tbody></table><div class="muted">估算值仅供快速报价，误差约 ±30%；导入一次真实切片结果后会自动校准。</div>`;
  }
  if (LAST_SLICE) {
    const r = LAST_SLICE;
    h += `<div class="ok" style="margin-top:6px">切片结果：<b>${r.grams ?? "-"} g</b>，<b>${r.hours ?? "-"} h</b></div>
      <div class="row gap wrap"><button class="mini" data-fill="all">填入全部变体</button>` +
      (P.variants || []).map((v, i) => `<button class="mini" data-fill="${i}">只填变体 ${i + 1}${v.opt1_zh || v.opt2_zh ? ` <span data-notr>（${esc([v.opt1_zh, v.opt2_zh].filter(Boolean).join("/"))}）</span>` : ""}</button>`).join("") + "</div>";
  }
  $("#est-box").innerHTML = h;
}
function fillGrams(grams, hours, src, only = null) {
  P.variants.forEach((v, i) => {
    if (only !== null && i !== only) return;
    if (grams != null) v.grams = grams;
    if (hours != null) v.hours = hours;
    v.grams_src = src;
  });
  markDirty(); renderVariants(); refreshPricing(); saveProduct(true);
}
$("#est-box").addEventListener("click", (e) => {
  const f = e.target.closest("[data-fill]"); if (!f || !LAST_SLICE) return;
  fillGrams(LAST_SLICE.grams, LAST_SLICE.hours, "sliced", f.dataset.fill === "all" ? null : Number(f.dataset.fill));
  toast("已填入切片结果");
});
$("#model-info").addEventListener("click", (e) => {
  if (e.target.id !== "btn-size-fill") return;
  const s = P.model.metrics.size, cm = (mm) => +(mm / 10).toFixed(1);
  P.size_text = `${cm(s[0])} × ${cm(s[1])} × ${cm(s[2])} cm`;
  P.package = { length: +(cm(s[0]) + 3).toFixed(1), width: +(cm(s[1]) + 3).toFixed(1), height: +(cm(s[2]) + 3).toFixed(1) };
  P.package_status = "manual";
  $('[data-f="size_text"]').value = P.size_text;
  for (const k of ["length", "width", "height"]) $(`[data-f="package.${k}"]`).value = P.package[k];
  renderPackage(); markDirty();
  toast("已填入：包裹尺寸按产品尺寸每边加 1.5 cm，请按实际包装核对");
});
$("#model-input").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  if (P.model && P.model.file && !confirm(`用「${f.name}」替换现在的 3D 模型？已有的切片文件会退回草稿，需要重新切片或复核。`)) { e.target.value = ""; return; }
  if (dirty) await saveProduct(true);
  const fd = new FormData(); fd.append("file", f);
  try {
    P = await busyToast(TR("busy.model_upload"), () => apiJob(`/api/products/${P.id}/model`, { method: "POST", body: fd }));
    VIEWER_PID = null;
    await renderModel();
    toast("模型已上传");
  } catch (err) { toast(err.message, true); }
  e.target.value = "";
});
$("#btn-est").addEventListener("click", () => {
  const e = (P.model || {}).estimate; if (!e) return toast("模型还没计算完", true);
  const x = e.per_printer[Number($("#printer-select").value)] || e.per_printer[0];
  fillGrams(x.grams, x.hours, "est");
  toast("已填入估算值（标记为「估」），切片后可替换为准确值");
});
$("#btn-orca").addEventListener("click", async (e) => {
  if (dirty) await saveProduct(true);
  await busy(e.target, async () => {
    const r = await apiJob(`/api/products/${P.id}/slice`, { json: { printer: Number($("#printer-select").value) } });
    LAST_SLICE = r; renderEstimate();
    toast("切片完成，请选择填入哪些变体");
  }, TR("busy.slicing"));
});
$("#sliced-input").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f); fd.append("pid", P.id); fd.append("material", P.material || "PLA");
  try {
    LAST_SLICE = await api("/api/sliced/parse", { method: "POST", body: fd });
    renderEstimate();
    toast("已读取切片结果，请选择填入哪些变体");
  } catch (err) { toast(err.message, true); }
  e.target.value = "";
});
// 「随机颜色」变体的图：几种颜色的渲染图拼成一张，角上标「สีสุ่ม」
async function colorCollage(urls, size) {
  const imgs = await Promise.all(urls.map((u) => new Promise((ok, no) => { const im = new Image(); im.onload = () => ok(im); im.onerror = no; im.src = u; })));
  const n = imgs.length, cols = n <= 2 ? 2 : n <= 4 ? 2 : 3, rows = Math.ceil(n / cols);
  const cv = document.createElement("canvas"); cv.width = cv.height = size;
  const g = cv.getContext("2d");
  g.fillStyle = "#ffffff"; g.fillRect(0, 0, size, size);
  const pad = Math.round(size * 0.02), cw = (size - pad * (cols + 1)) / cols, ch = (size - pad * (rows + 1) - size * 0.08) / rows;
  imgs.forEach((im, i) => {
    const r = Math.floor(i / cols), c = i % cols, s = Math.min(cw, ch);
    const rowN = Math.min(cols, n - r * cols), off = (cols - rowN) * (cw + pad) / 2;     // 最后一行不满时居中
    g.drawImage(im, off + pad + c * (cw + pad) + (cw - s) / 2, size * 0.08 + pad + r * (ch + pad) + (ch - s) / 2, s, s);
  });
  const h = Math.round(size * 0.065);
  g.fillStyle = "#ff6b6b"; g.beginPath();
  if (g.roundRect) g.roundRect(pad, pad, size * 0.42, h, h / 2); else g.rect(pad, pad, size * 0.42, h);
  g.fill();
  g.fillStyle = "#fff"; g.font = `bold ${Math.round(h * 0.55)}px sans-serif`; g.textBaseline = "middle";
  g.fillText("สีสุ่ม · Random", pad + h * 0.45, pad + h / 2);
  return cv.toDataURL("image/jpeg", 0.92);
}
async function postRenders(images, opts = {}) {
  const r = await api(`/api/products/${P.id}/images/rendered`, { json: { images, ...opts } });
  P = r.product; dirty = false; $("#ed-dirty").textContent = "";
  renderImages(); renderVariants(); refreshPricing(); runCheck();
  return r.added;
}
$("#btn-render").addEventListener("click", async (e) => {
  if (!VIEWER || !VIEWER.model) return toast("先上传模型", true);
  if (dirty) await saveProduct(true);
  await busy(e.target, async () => {
    const cols = colorList(), list = cols.length ? cols : [""];
    const shots = [];
    const prog = (t) => ($("#render-progress").textContent = t);
    prog("正在读取完整模型…"); await VIEWER.ensureFull();      // 商品图用完整模型出
    const real = list.filter((c) => !isRandomColor(c));
    const wantColors = $("#r-colors").checked ? real : [real[0] || list[0]];
    for (const c of wantColors) {
      const ci = colorInfo(c); VIEWER.setColor(ci.hex, ci.code); VIEWER.view(35, 22);
      prog(`正在渲染：${c || "主图"}`); await new Promise((r) => setTimeout(r, 30));
      shots.push({ data: VIEWER.shot({ size: RS(), fill: FILL() }), kind: "main", color: c });
    }
    // 随机颜色：用各颜色的图拼一张「多色合集」
    const rnd = list.find((c) => isRandomColor(c));
    if (rnd && $("#r-colors").checked && shots.length >= 2) {
      prog("正在合成：随机颜色");
      shots.push({ data: await colorCollage(shots.map((x) => x.data).slice(0, 6), RS()), kind: "main", color: rnd });
    }
    const c0 = colorInfo(real[0] || list[0]); VIEWER.setColor(c0.hex, c0.code);
    if ($("#r-angles").checked) {
      for (const [az, el, label] of [[0, 8, "正面"], [90, 8, "侧面"], [180, 8, "背面"], [30, 65, "俯视"]]) {
        prog(`正在渲染：${label}`); VIEWER.view(az, el); await new Promise((r) => setTimeout(r, 30));
        shots.push({ data: VIEWER.shot({ size: RS(), fill: FILL() }), kind: "angle", color: list[0] });
      }
    }
    if ($("#r-dims").checked) {
      VIEWER.view(35, 22); prog("正在渲染：尺寸图");
      shots.push({ data: VIEWER.shot({ size: RS(), dims: true }), kind: "dims", color: list[0] });
    }
    VIEWER.view(35, 22);
    if (shots.length > 8) toast("Lazada/Shopee 主图最多 8 张，多出的不会导出。可以少选几项，或在图片区删掉不需要的", true);
    prog("正在保存…");
    const n = await postRenders(shots, { white_bg: $("#r-white").checked, replace_renders: true });
    prog(`已生成 ${n} 张商品图（替换了之前渲染的图，实拍图保留）。记得点「上传图床」。`);
  });
});
$("#btn-snap").addEventListener("click", async (e) => {
  if (!VIEWER || !VIEWER.model) return toast("先上传模型", true);
  await busy(e.target, async () => {
    const c = $("#view-chips").dataset.cur || colorList()[0] || "", ci = colorInfo(c);
    await VIEWER.ensureFull();
    VIEWER.setColor(ci.hex, ci.code);
    const n = await postRenders([{ data: VIEWER.shot({ size: RS(), fill: FILL() }), kind: "angle", color: colorList().includes(c) ? c : "" }], { replace_renders: false });
    toast(`已添加 ${n} 张`);
  });
});

// AI 文案
$("#btn-ai").addEventListener("click", async (e) => {
  if (!P.name_zh || !P.features_zh) return toast("先填写产品名称和用途/卖点", true);
  if (P.copy.title_th && !confirm("会覆盖现有文案，继续？")) return;
  await busy(e.target, async () => {
    const d = await apiJob(`/api/products/${P.id}/ai`, { json: P });
    if (d.keyword_plan) { P.keyword_plan = { ...d.keyword_plan, custom: [] }; mergeKeywordsField(P.keyword_plan); delete d.keyword_plan; }
    P.copy = { ...P.copy, ...d };
    markDirty();
    await saveProduct(true);
    await renderEditor();
    toast("文案已生成，请对照中文回译检查。下一步：⑥ AI 匹配类目");
  });
});
$("#btn-back").addEventListener("click", async (e) => {
  await busy(e.target, async () => {
    const d = await apiJob("/api/ai/back-translate", { json: { title_th: P.copy.title_th, description_th: P.copy.description_th } });
    P.copy.title_zh = d.title_zh; P.copy.description_zh = d.description_zh;
    if (d.title_en) P.copy.title_en = d.title_en;            // v2.22：英文跟着泰文更新
    if (d.description_en) P.copy.description_en = d.description_en;
    markDirty(); await renderEditor();
  });
});
// v2.22：空着的文案字段补完整（英文、Shopee 标题和标签、包装内容、变体名称、选项泰文），已经填的不动
$("#btn-complete").addEventListener("click", async (e) => {
  await busy(e.target, async () => {
    const r = await apiJob(`/api/products/${P.id}/ai-complete`, { json: P });
    const f = r.fields || {};
    const keys = Object.keys(f);
    if (!keys.length) { toast("文案都填好了，没有空着的"); return; }
    P.copy = P.copy || {};
    for (const k of keys) {
      if (k === "options_th") P.copy.options_th = { ...(P.copy.options_th || {}), ...f.options_th };
      else if (!P.copy[k] || (typeof P.copy[k] === "string" && !P.copy[k].trim())) P.copy[k] = f[k];
    }
    markDirty(); await saveProduct(true); await renderEditor();
    toast(`已补上 ${keys.length} 项：${keys.join("、")}`, false, 8000);
  });
});
$("#btn-fill-copy").addEventListener("click", async (e) => {
  if (!confirm("用 AI 把所有产品空着的文案字段补上（英文标题 / 详情、Shopee 标签、包装内容、变体名称…），已经填的不动。在后台做，可以在右上角「任务」里看进度。继续？")) return;
  await busy(e.target, async () => {
    const r = await apiJob("/api/products/fill-copy", { json: {} });
    toast(`补全了 ${r.done.length} / ${r.total} 个产品${r.failed.length ? `，${r.failed.length} 个失败：${r.failed[0].error}` : ""}`, !!r.failed.length, 10000);
    loadLibrary();
  });
});

// ---------------- 类目与属性 ----------------
async function loadCats() { CATS = await api("/api/categories"); }
function fillCatSelect(cur, known) {
  // v2.25：全部类目约 2900 个，用搜索框筛选（名称、泰文路径、类目ID）
  const q = (($("#cat-filter") || {}).value || "").trim().toLowerCase();
  const words = q.split(/\s+/).filter(Boolean);
  let list = CATS;
  if (words.length) list = CATS.filter((c) => { const t = `${catName(c)} ${c.path || ""} ${c.cat_id}`.toLowerCase(); return words.every((w) => t.includes(w)); });
  if (cur && !list.some((c) => c.id === cur)) list = CATS.filter((c) => c.id === cur).concat(list);
  $("#cat-select").innerHTML = `<option value="">${words.length ? `— 找到 ${list.length} 个 —` : "— 未选择 —"}</option>` +
    list.slice(0, 600).map((c) => `<option value="${esc(c.id)}" ${c.id === cur ? "selected" : ""} title="${esc(c.path || "")}">${esc(catName(c))}（${esc(c.cat_id)}）${c.needs_license ? " ⚠需TISI许可证" : ""}</option>`).join("") +
    (cur && !known ? `<option value="${esc(cur)}" selected>（模板已删除）${esc(cur)}</option>` : "");
}
document.addEventListener("input", (e) => {
  if (e.target.id !== "cat-filter" || !P) return;
  const cur = P.category.id || "";
  fillCatSelect(cur, CATS.some((c) => c.id === cur));
});
async function renderCategory() {
  await loadCats();
  const cur = P.category.id || "";
  const known = CATS.some((c) => c.id === cur);
  fillCatSelect(cur, known);
  $("#cat-select").classList.toggle("is-red", P.category.status === "check" || !cur);
  const c = P.category;
  let info = "";
  if (!CATS.length) info = '<span class="bad">还没有类目模板，请先到「导出 Lazada 表格」页上传模板。</span>';
  else if (c.status === "manual") info = '<span class="st st-manual">手动选择</span>';
  else if (c.id) info = `<span class="st ${c.status === "check" ? "st-check" : "st-ai"}">AI 匹配 · 把握 ${Math.round((c.confidence || 0) * 100)}%</span>`;
  if (c.id && c.status === "check") info += ` <button class="mini" id="btn-cat-ok">✓ 确认类目</button>`;
  const reason = LANG === "th" ? (c.reason_th || "") : c.reason;
  if (reason) info += `<div data-notr>${esc(reason)}</div>`;
  if (c.suggest_id && !CATS.some((x) => x.cat_id === c.suggest_id)) {
    info += `<div class="warn">AI 建议的理想类目还没有模板：<b data-notr>${esc(LANG === "th" ? c.suggest_path : (c.suggest_path_zh || ""))}</b><br><span class="muted">${esc(c.suggest_path)}（类目ID ${esc(c.suggest_id)}）</span><br>全部类目模板下载完以后（进度在「导出上架表格」页）重新点 AI 匹配类目就行。</div>`;
  }
  $("#cat-info").innerHTML = info;
  FIELDS = null;
  if (c.id && known) {
    try { FIELDS = (await api(`/api/category-fields?id=${encodeURIComponent(c.id)}`)).fields; } catch { FIELDS = null; }
  }
  renderAttrs();
}
function renderAttrs() {
  if (!FIELDS) { $("#attr-form").innerHTML = '<span class="muted">选择类目后显示属性。</span>'; return; }
  $("#attr-form").innerHTML = FIELDS.map((f) => {
    const a = P.attributes[f.key] || { value: "", status: f.required ? "missing" : "empty" };
    const zh = (LANG !== "th" && a.label_zh) ? `<b>${esc(a.label_zh)}</b> <span class="muted small" data-notr>${esc(f.label)}</span>` : `<span data-notr>${esc(f.label)}</span>`;
    const ok = (a.status === "check" && a.value) ? ` <button class="mini" data-confirm="${esc(f.key)}">✓ 确认</button>` : "";
    const lab = `<span>${zh}${f.required ? ' <span class="bad">*</span>' : ""} <span class="st st-${a.status}">${STATUS_TEXT[a.status] || ""}</span>${ok}</span>`;
    const noteText = LANG === "th" ? (a.note_th !== undefined ? a.note_th : a.note) : a.note;
    const note = noteText ? `<span class="small muted"${LANG === "th" && a.note_th !== undefined ? " data-notr" : ""}>${esc(noteText)}</span>` : "";
    let input;
    if (f.options.length) {
      const has = !a.value || f.options.includes(a.value);
      input = `<select data-attr="${esc(f.key)}"><option value="">（留空）</option>` +
        (has ? "" : `<option selected>${esc(a.value)}</option>`) +
        f.options.map((o) => `<option ${o === a.value ? "selected" : ""}>${esc(o)}</option>`).join("") + "</select>";
    } else {
      input = `<input data-attr="${esc(f.key)}" value="${esc(a.value || "")}">`;
    }
    return `<div class="attr attr-${a.status}" title="${esc(f.tip)}">${lab}${input}${note}</div>`;
  }).join("");
}
function setAttr(k, v) {
  const f = FIELDS.find((x) => x.key === k);
  const prev = P.attributes[k] || {};
  P.attributes[k] = { value: v, status: v ? "manual" : (f && f.required ? "missing" : "empty"),
    note: v ? "手动设置，下次同类目自动套用" : "", label_zh: prev.label_zh };
  markDirty();
}
function onAttrEdit(e) {
  const k = e.target.dataset.attr; if (!k) return;
  setAttr(k, e.target.value);
  renderAttrs();
}
$("#attr-form").addEventListener("change", onAttrEdit);
$("#attr-form").addEventListener("input", (e) => { if (e.target.tagName === "INPUT") { const k = e.target.dataset.attr; if (k) setAttr(k, e.target.value); } });
$("#attr-form").addEventListener("blur", (e) => { if (e.target.tagName === "INPUT" && e.target.dataset.attr) renderAttrs(); }, true);
$("#attr-form").addEventListener("click", (e) => {
  const k = e.target.dataset.confirm; if (!k) return;
  e.preventDefault();
  setAttr(k, (P.attributes[k] || {}).value || "");
  renderAttrs();
});
$("#btn-confirm-all").addEventListener("click", () => {
  if (!FIELDS) return;
  let n = 0;
  for (const f of FIELDS) {
    const a = P.attributes[f.key];
    if (a && a.status === "check" && a.value) { setAttr(f.key, a.value); n++; }
  }
  renderAttrs();
  toast(n ? `已确认 ${n} 项` : "没有需要确认的项");
});
$("#cat-info").addEventListener("click", (e) => {
  if (e.target.id !== "btn-cat-ok") return;
  P.category.status = "manual";
  markDirty();
  renderCategory();
});
$("#cat-select").addEventListener("change", async () => {
  const id = $("#cat-select").value;
  const cat = CATS.find((c) => c.id === id);
  P.category = { ...P.category, id, cat_id: cat ? cat.cat_id : "", status: "manual" };
  markDirty();
  if (!id) { P.attributes = {}; return renderCategory(); }
  const btn = $("#btn-fill-attrs");
  await busy(btn, async () => {
    const r = await apiJob(`/api/products/${P.id}/fill-attrs`, { json: P });
    P = r.product; dirty = false; $("#ed-dirty").textContent = "";
    renderPackage(); await renderCategory(); runCheck();
    if (!r.used_ai) toast("没有设置 AI 密钥，只按规则和记住的值填写了属性", true);
  });
});
$("#btn-ai-cat").addEventListener("click", async (e) => {
  if (!P.name_zh) return toast("先填写产品名称和用途", true);
  let url = `/api/products/${P.id}/ai-category`;
  if (P.category.status === "manual" && P.category.id) {
    if (confirm("你已手动选过类目。点「确定」让 AI 重新选类目；点「取消」保留你的类目，只让 AI 填属性。")) url += "?override=1";
  }
  await busy(e.target, async () => {
    P = await apiJob(url, { json: P });
    dirty = false; $("#ed-dirty").textContent = "";
    for (const k of ["length", "width", "height"]) $(`[data-f="package.${k}"]`).value = P.package[k] ?? "";
    renderPackage(); await renderCategory(); runCheck();
    const red = Object.values(P.attributes).filter((a) => a.status === "check" || a.status === "missing").length;
    toast(P.category.id ? `已匹配：${$("#cat-select").selectedOptions[0].textContent}。${red ? red + " 项标红请确认" : "属性已全部填好"}`
      : "现有模板里没有合适的类目，请看建议的类目路径并下载对应模板", !P.category.id);
  });
});
$("#btn-fill-attrs").addEventListener("click", async (e) => {
  if (!P.category.id) return toast("先选择类目", true);
  await busy(e.target, async () => {
    const r = await apiJob(`/api/products/${P.id}/fill-attrs`, { json: P });
    P = r.product; dirty = false; $("#ed-dirty").textContent = "";
    renderPackage(); await renderCategory(); runCheck();
    toast("属性已重新填写（手动改过的保留不变）");
  });
});

// ---------------- Shopee 类目 ----------------
let spTimer = null;
function renderShopeeCat() {
  const sc = P.shopee_category || {};
  let h = "";
  if (!sc.id) h = '<span class="bad">还没有选择 Shopee 类目</span>';
  else {
    const st = sc.status === "manual" ? '<span class="st st-manual">手动选择</span>'
      : sc.status === "auto" ? '<span class="st st-auto">规则/记住</span>'
      : `<span class="st ${sc.status === "check" ? "st-check" : "st-ai"}">AI 匹配 · 把握 ${Math.round((sc.confidence || 0) * 100)}%</span>`;
    h = `${st}${sc.status === "check" ? ' <button class="mini" id="btn-sp-ok">✓ 确认类目</button>' : ""}
      <div><b data-notr>${esc(sc.name || "")}</b> <span class="muted">（${esc(sc.id)}）</span></div>
      <div class="muted" data-notr>${esc(sc.path || "")}</div>`;
    const reason = LANG === "th" ? (sc.reason_th || "") : (sc.reason || "");
    if (reason) h += `<div data-notr>${esc(reason)}</div>`;
  }
  $("#sp-info").innerHTML = h;
  $("#sp-search").classList.toggle("is-red", !sc.id || sc.status === "check");
  renderSpCascade();
  renderSpAttrs();
}
// v2.25：Shopee 类目属性（必填的要补；批量上传的基础模板里没有这几栏，上传后在 Shopee 后台填）
const SP_ATTRS = {};
async function renderSpAttrs() {
  const box = $("#sp-attrs"); if (!box) return;
  const cid = (P.shopee_category || {}).id;
  if (!cid) { box.innerHTML = ""; return; }
  if (!SP_ATTRS[cid]) { try { SP_ATTRS[cid] = (await api(`/api/shopee/attrs?id=${encodeURIComponent(cid)}`)).attrs; } catch { SP_ATTRS[cid] = []; } }
  if ((P.shopee_category || {}).id !== cid) return;
  const all = SP_ATTRS[cid];
  const show = all.filter((a) => a.required).concat(all.filter((a) => !a.required).slice(0, 6));
  if (!show.length) { box.innerHTML = ""; return; }
  const have = P.shopee_attrs || {};
  const th = LANG === "th";
  box.innerHTML = `<div class="sp-attrs"><div class="row between wrap"><b>Shopee 属性</b>
      <button class="mini" id="btn-sp-attrs">🤖 AI 填 Shopee 属性</button></div>
    <table class="grid small"><tbody>${show.map((a) => {
      const v = have[String(a.id)] || {};
      const lab = `${a.required ? '<span class="bad">*</span> ' : ""}<span data-notr>${esc(th ? a.th || a.en : a.en)}</span>${!th && a.th ? ` <span class="muted" data-notr>${esc(a.th)}</span>` : ""}`;
      const ctl = a.values.length && !a.free
        ? `<select data-spattr="${a.id}" data-notr><option value="">—</option>${a.values.map((o) => `<option value="${o[0]}" ${String(v.value_id) === String(o[0]) ? "selected" : ""}>${esc(o[1])}${o[2] && o[2] !== o[1] ? " / " + esc(o[2]) : ""}</option>`).join("")}</select>`
        : `<input data-spattr="${a.id}" value="${esc(v.value || "")}" data-notr list="spl-${a.id}"><datalist id="spl-${a.id}">${a.values.map((o) => `<option value="${esc(o[1])}">`).join("")}</datalist>`;
      return `<tr class="${a.required && !v.value ? "is-red" : ""}"><td>${lab}</td><td>${ctl}</td></tr>`;
    }).join("")}</tbody></table>
    <div class="muted">${all.some((a) => a.required) ? "带 * 的是必填：批量上传模板里没有这几栏，上传后在 Shopee 后台照这里填。" : "这个类目没有必填属性；填上常用属性有助于搜索。"}</div></div>`;
}
document.addEventListener("change", (e) => {
  const id = e.target.dataset && e.target.dataset.spattr; if (!id || !P) return;
  const a = (SP_ATTRS[(P.shopee_category || {}).id] || []).find((x) => String(x.id) === id); if (!a) return;
  P.shopee_attrs = P.shopee_attrs || {};
  const val = e.target.value;
  if (!val) delete P.shopee_attrs[id];
  else if (e.target.tagName === "SELECT") { const o = a.values.find((x) => String(x[0]) === val) || []; P.shopee_attrs[id] = { en: a.en, th: a.th, value: o[1] || val, value_th: o[2] || "", value_id: o[0] }; }
  else P.shopee_attrs[id] = { en: a.en, th: a.th, value: val, value_th: "", value_id: null };
  markDirty(); renderSpAttrs();
});
document.addEventListener("click", async (e) => {
  if (e.target.id !== "btn-sp-attrs") return;
  await busy(e.target, async () => {
    const r = await apiJob(`/api/products/${P.id}/shopee-attrs`, { json: P });
    P.shopee_attrs = { ...(P.shopee_attrs || {}), ...(r.values || {}) };
    markDirty(); renderSpAttrs();
    toast(`AI 填了 ${Object.keys(r.values || {}).length} 个 Shopee 属性，检查后保存`);
  });
});
const SP_TOP_ZH = { "Home & Living": "家居生活", "Home Appliances": "家用电器", "Hobbies & Collections": "爱好收藏",
  "Computers & Accessories": "电脑及配件", "Mobile & Gadgets": "手机及数码", "Automobiles": "汽车", "Motorcycles": "摩托车",
  "Spare Parts and Accessories for Vehicles": "汽车零配件", "Stationery": "文具办公", "Sports & Outdoors": "运动户外",
  "Pets": "宠物", "Mom & Baby": "母婴", "Baby & Kids Fashion": "童装", "Beauty": "美妆", "Health": "健康",
  "Fashion Accessories": "时尚配饰", "Women Clothes": "女装", "Men Clothes": "男装", "Women Shoes": "女鞋", "Men Shoes": "男鞋",
  "Women Bags": "女包", "Men Bags": "男包", "Travel & Luggage": "旅行箱包", "Watches": "手表", "Audio": "音响耳机",
  "Cameras & Drones": "相机无人机", "Gaming & Consoles": "游戏机", "Food & Beverage": "食品饮料", "Books & Magazines": "图书杂志",
  "Tickets, Vouchers & Services": "票券服务", "Muslim Fashion": "穆斯林服饰" };
let SP_TREE = null;
function pickShopee(id, path, name) {
  P.shopee_category = { id: String(id), path: path || "", name: name || (path || "").split(" > ").slice(-2).join(" > "), status: "manual" };
  $("#sp-results").innerHTML = ""; $("#sp-search").value = "";
  markDirty(); renderShopeeCat(); renderSpCascade(); scheduleCheck();
}
async function spSearch() {
  const v = $("#sp-search").value.trim();
  if (!v) { $("#sp-results").innerHTML = ""; return; }
  $("#sp-results").innerHTML = '<div class="muted">搜索中…</div>';
  try {
    const res = await api(`/api/shopee/categories?q=${encodeURIComponent(v)}`);
    $("#sp-results").innerHTML = res.length ? res.map((c) => `<div data-spid="${esc(c.id)}" data-path="${esc(c.path)}" data-name="${esc(c.name)}" data-notr>${c.restricted ? "⚠ " : ""}<b>${esc(c.name)}</b> <span class="muted">${esc(c.path)}（${esc(c.id)}）</span></div>`).join("")
      : '<div class="muted">没有找到，换个词试试，或用下面的逐级选择</div>';
  } catch (err) { $("#sp-results").innerHTML = `<div class="bad">${esc(err.message)}</div>`; }
}
$("#sp-search").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); spSearch(); } });
$("#sp-search").addEventListener("input", () => {
  clearTimeout(spTimer);
  const v = $("#sp-search").value.trim();
  // 英文/数字边打边搜；中文、泰文按回车再搜（需要 AI 翻译关键词）
  if (v.length >= 2 && /^[\x00-\x7f]+$/.test(v)) spTimer = setTimeout(spSearch, 350);
});
$("#sp-results").addEventListener("click", (e) => {
  const d = e.target.closest("[data-spid]"); if (!d) return;
  pickShopee(d.dataset.spid, d.dataset.path, d.dataset.name);
});
async function renderSpCascade() {
  if (!SP_TREE) { try { SP_TREE = await api("/api/shopee/tree"); } catch { return; } }
  const cur = ((P && P.shopee_category && P.shopee_category.path) || "").split(" > ");
  const box = $("#sp-cascade"); let html = "", prefix = [];
  for (let lvl = 0; lvl < 5; lvl++) {
    const kids = new Map();
    for (const [id, path] of SP_TREE) {
      const parts = path.split(" > ");
      if (parts.length <= lvl || prefix.some((p, i) => parts[i] !== p)) continue;
      const name = parts[lvl];
      if (!kids.has(name)) kids.set(name, parts.length === lvl + 1 ? id : null);
    }
    if (!kids.size) break;
    const sel = cur[lvl] && kids.has(cur[lvl]) && prefix.length === lvl ? cur[lvl] : "";
    html += `<select data-lvl="${lvl}" data-notr><option value="">${lvl === 0 ? "— 一级类目 —" : "— 选择 —"}</option>${[...kids.keys()].sort().map((n) =>
      `<option value="${esc(n)}" ${n === sel ? "selected" : ""}>${esc(n)}${lvl === 0 && SP_TOP_ZH[n] ? "（" + SP_TOP_ZH[n] + "）" : ""}</option>`).join("")}</select>`;
    if (!sel) break;
    prefix.push(sel);
    if (kids.get(sel)) break;   // 已经是最末级
  }
  box.innerHTML = html;
}
$("#sp-cascade").addEventListener("change", (e) => {
  const lvl = Number(e.target.dataset.lvl);
  const parts = [...$$("#sp-cascade select")].slice(0, lvl + 1).map((s) => s.value);
  if (!parts[lvl]) { P.shopee_category = P.shopee_category || {}; renderSpCascadeFrom(parts.slice(0, lvl)); return; }
  const path = parts.join(" > ");
  const leaf = SP_TREE.find(([, p]) => p === path);
  if (leaf) { pickShopee(leaf[0], leaf[1]); return; }
  renderSpCascadeFrom(parts);
});
function renderSpCascadeFrom(parts) {
  // 临时按已选的上级展开下一级（还没选到最末级时不改产品类目）
  const save = P.shopee_category;
  P.shopee_category = { ...(save || {}), path: parts.join(" > ") };
  renderSpCascade().then(() => { P.shopee_category = save; });
}
$("#sp-info").addEventListener("click", (e) => {
  if (e.target.id !== "btn-sp-ok") return;
  P.shopee_category.status = "manual"; markDirty(); renderShopeeCat();
});
$("#btn-ai-sp").addEventListener("click", async (e) => {
  if (!P.name_zh) return toast("先填写产品名称和用途", true);
  await busy(e.target, async () => {
    P = await apiJob(`/api/products/${P.id}/ai-shopee-category`, { json: P });
    dirty = false; $("#ed-dirty").textContent = "";
    if (P.shopee_category && P.shopee_category.id && !P.shopee_category.name) {
      const r = await api(`/api/shopee/categories?id=${P.shopee_category.id}`);
      P.shopee_category.name = r[0] ? r[0].name : "";
    }
    renderShopeeCat(); runCheck();
  });
});

// 上架检查
function scheduleCheck() { clearTimeout(checkTimer); checkTimer = setTimeout(runCheck, 800); }
async function runCheck() {
  if (!P) return;
  const [r, rs] = await Promise.all([api(`/api/products/${P.id}/check`, { json: P }), api(`/api/products/${P.id}/check-shopee`, { json: P })]);
  const li = (arr, cls) => arr.map((m) => `<li class="${cls}">${esc(m)}</li>`).join("");
  const box = (x) => (x.errors.length || x.warnings.length)
    ? `<ul class="msgs">${li(x.errors, "bad")}${li(x.warnings, "warn")}</ul>`
    : '<p class="ok">全部检查通过，可以导出。</p>';
  $("#check-box").innerHTML = box(r);
  $("#check-box-sp").innerHTML = box(rs);
  $("#ed-status").innerHTML = statusBadge(r.errors.length, r.warnings.length);
}
$("#btn-check").addEventListener("click", runCheck);

async function saveProduct(quiet = false) {
  if (!P) return;
  try {
    try { P = await api(`/api/products/${P.id}`, { json: P }); }
    catch (e) {
      if (e.status !== 409) throw e;
      // 打开后被别人 / 运营写回改过：问一下，不悄悄覆盖
      if (!confirm(TR("save.conflict", { msg: e.message }))) throw new Error(TR("save.not_saved"));
      P = await api(`/api/products/${P.id}?force=1`, { json: P });
    }
    dirty = false;
    $("#ed-dirty").textContent = "";
    $$("#var-table .c-sku").forEach((td, i) => { if (P.variants[i]) td.firstChild && (td.firstChild.textContent = P.variants[i].sku); });
    if (!quiet) toast("已保存");
    runCheck();
  } catch (e) { toast(e.message, true); }
}
$("#btn-save").addEventListener("click", async () => { await saveProduct(false); if (!dirty) setEdEdit(false); });
$("#btn-ed-edit").addEventListener("click", () => setEdEdit(true));
$("#btn-ed-cancel").addEventListener("click", async () => {
  if (dirty && !confirm("放弃这次的修改？")) return;
  P = await api(`/api/products/${P.id}`); dirty = false; ED_EDIT = false; await renderEditor();
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "s" && ED_EDIT) { e.preventDefault(); saveProduct(false); }
});
window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });

// ---------------- 导出 ----------------
let TPL_SYNC_T = null;
async function renderTplSync() {
  const box = $("#tpl-sync"); if (!box) return;
  let st; try { st = await api("/api/templates/sync"); } catch { box.innerHTML = ""; return; }
  const r = st.running || {};
  box.innerHTML = !st.files ? "" : r.on
    ? `<span class="warn">⏳ 正在下载 Lazada 全部类目模板：${r.done} / ${r.total}</span>`
    : `${st.downloaded >= st.files ? '<span class="ok">✓ Lazada 全部类目模板已下载</span>' : `<span class="warn">Lazada 类目模板已下载 ${st.downloaded} / ${st.files} 个文件</span>`}
       · 有模板的类目 <b>${st.categories_with_template ?? "…"}</b> / ${st.categories_total}
       ${st.downloaded < st.files ? '<button class="mini primary" id="btn-tpl-sync">下载剩下的模板</button>' : '<button class="mini" id="btn-tpl-sync" data-force="1">重新下载全部</button>'}
       ${st.parsing ? '<span class="muted">（正在整理新下载的模板，第一次要几分钟）</span>' : ""}
       ${(st.errors || []).length ? `<div class="bad small">下载失败：${esc(st.errors.join("；"))}</div>` : ""}`;
  clearTimeout(TPL_SYNC_T);
  if (r.on || st.parsing) TPL_SYNC_T = setTimeout(renderTplSync, r.on ? 4000 : 10000);
}
document.addEventListener("click", async (e) => {
  if (e.target.id !== "btn-tpl-sync") return;
  if (e.target.dataset.force && !confirm("重新下载全部 Lazada 类目模板（约 160 个文件）？")) return;
  try { api("/api/templates/sync?async=1", { json: { force: !!e.target.dataset.force } }); setTimeout(renderTplSync, 1500); } catch (err) { toast(err.message, true); }
});
// v2.27：类目模板库搬到 设置 → 商品与上架
async function renderTplLib() {
  renderTplSync();
  await loadCats();
  const byFile = {};
  CATS.forEach((c) => (byFile[c.template] = byFile[c.template] || []).push(c));
  const files = Object.keys(byFile).sort();
  $("#tpl-count").textContent = CATS.length ? `（${CATS.length} 个类目 · ${files.length} 个模板文件）` : "";
  $("#btn-tpl-manage").textContent = TPL_MANAGE ? "完成管理" : "管理模板";
  $("#tpl-list").innerHTML = files.length ? files.map((f) => `
    <div class="tpl-file">
      <div class="row between"><b data-notr>📄 ${esc(f)}</b>
        <span><span class="muted small">${byFile[f].length} 个类目</span>
        ${TPL_MANAGE ? ` <button class="danger" data-deltpl="${esc(f)}">删除这个模板文件</button>` : ""}</span></div>
      <table class="grid"><tbody>${byFile[f].map((c) => `
        <tr><td><span data-notr>${esc(catName(c))}</span>${c.needs_license ? ' <span class="warn small">需TISI许可证</span>' : ""}<br><span class="muted small" data-notr>${esc(c.path)}</span></td>
        <td class="small" style="width:110px">${esc(c.cat_id)}</td></tr>`).join("")}</tbody></table>
    </div>`).join("") : '<p class="muted">还没有模板</p>';
  if (TPL_MANAGE) $("#tpl-details").open = true;
  if (!PRODUCT_LIST.length) { try { PRODUCT_LIST = await api("/api/products"); } catch { /* 忽略 */ } }
}
// 上架状态按平台自己的商品状态（Lazada：Pending QC → Active / QC Rejected / Inactive；Shopee：审核中 → 在售 / 违规 / 已下架）
const LST_ZH = { none: "未导出", pending: "待上传", failed: "上传失败", uploaded: "平台审核中", rejected: "审核不通过",
  live: "已上线", inactive: "平台已下架", update: "有修改待同步" };
const LST_PLAT = { lazada: { uploaded: "Pending QC", live: "Active", rejected: "QC Rejected", inactive: "Inactive" },
  shopee: { uploaded: "Reviewing", live: "Live", rejected: "Violation", inactive: "Unlisted" } };
const LST_RANK = { failed: 0, rejected: 1, update: 2, pending: 3, none: 4, uploaded: 5, inactive: 6, live: 7 };
const ON_PLAT = ["uploaded", "live", "rejected", "inactive", "update"];
function lstBadge(x, plat) {
  const st = (x && x.status) || "none";
  const pn = plat && (LST_PLAT[plat] || {})[st];
  const tip = [pn ? `${plat === "shopee" ? "Shopee" : "Lazada"}: ${pn}` : "", (x && x.note) || ""].filter(Boolean).join(" · ");
  return `<span class="lst lst-${st}" title="${esc(tip)}">${LST_ZH[st] || st}${(st === "failed" || st === "rejected") && x.note ? " ⓘ" : ""}</span>`;
}
let TPL_MANAGE = false;
let PRODUCT_LIST = [];
$("#btn-tpl-manage").addEventListener("click", () => { TPL_MANAGE = !TPL_MANAGE; renderTplLib(); });
$("#tpl-list").addEventListener("click", async (e) => {
  const t = e.target.dataset.deltpl; if (!t) return;
  const cats = CATS.filter((c) => c.template === t);
  const ids = new Set(cats.map((c) => c.id));
  const used = PRODUCT_LIST.filter((p) => ids.has(p.category_id));
  let msg = `确定删除模板文件「${t}」？\n\n里面的 ${cats.length} 个类目会一起移除。`;
  if (used.length) msg += `\n\n⚠ 有 ${used.length} 个产品正在使用这些类目：${used.slice(0, 8).map((p) => p.id).join("、")}${used.length > 8 ? "…" : ""}\n删除后这些产品需要重新选类目。`;
  msg += "\n\n（文件会移到 templates_lazada\\_deleted 文件夹，可以找回。）";
  if (!confirm(msg)) return;
  if (used.length && !confirm(`再次确认：删除后 ${used.length} 个产品将无法导出，直到重新选类目。继续删除？`)) return;
  try {
    await api(`/api/templates/${encodeURIComponent(t)}`, { method: "DELETE" });
    toast("模板已移到 _deleted 文件夹");
  } catch (err) { toast(err.message, true); }
  renderTplLib();
});
$("#tpl-input").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try {
    const r = await api("/api/templates", { method: "POST", body: fd });
    toast(`模板已添加，包含类目：${r.categories.join("、")}`);
    await renderTplLib();
  } catch (err) { toast(err.message, true); }
  e.target.value = "";
});

// ---------------- 设置 ----------------
// 设置页的字段在 core/settings_schema.py（按模块分开）
let COLORS = {};
async function loadConfig() {
  try { COLORS = await api("/api/colors"); } catch { COLORS = {}; }
  const r = await api("/api/config");
  CFG = r.config; CFG_REMBG = r.rembg; window.IN_DOCKER = !!r.docker;
  $("#ver").textContent = "v" + r.version;
  if (r.version !== APP_JS_VERSION && !$(".ver-warn")) {
    const b = document.createElement("div");
    b.className = "ver-warn";
    b.textContent = r.docker
      ? `网页（v${APP_JS_VERSION}）和后台程序（v${r.version}）版本不一致：先按 Ctrl+F5 强制刷新；还不行到 Container Station 重启容器 3d-ops。`
      : `网页（v${APP_JS_VERSION}）和后台程序（v${r.version}）版本不一致：先按 Ctrl+F5 强制刷新；还不行请关闭所有黑色窗口，再重新双击 2_start.bat。`;
    document.body.prepend(b);
  }
  const thUi = window.I18N && I18N.lang === "th";
  $("#color-list").innerHTML = Object.keys(COLORS).map((zh) => `<option value="${esc(thUi && COLORS[zh].th ? COLORS[zh].th : zh)}">${esc(COLORS[zh].code || "")} · ${esc(thUi ? zh : COLORS[zh].th || "")}</option>`).join("");
  return r;
}
const PRINTERS_CARD = () => `<div class="card cfg-group"><h3>打印机与 OrcaSlicer 配置文件</h3>
      <p class="muted small">「每小时克数」用于估算打印时长。OrcaSlicer 自动切片会用下面三项配置：点「自动匹配配置」会按打印机名称自动选好 OrcaSlicer 自带的配置（不需要先在 OrcaSlicer 里保存预设）；也可以在输入框里点一下从列表里选。产品材质不是 PLA 时，会自动换成对应材质的耗材配置。估算校准系数：<b>${CFG.est_calibration}</b>（已用 ${CFG.est_calibration_n} 次真实切片校准）</p>
      <p class="small">同一机型的打印机共用切片文件和打印方案，排单时互为备用：一台停用或连不上，任务会自动转到其他机器。每台机器有一个<b>机器编码</b>（例如 P1S-01），建议打印出来贴在机器上，生产看板、任务和打印记录都按编码显示。</p>
      <div class="row gap wrap pr-bulk">
        <label class="small">批量添加<select id="pr-add-model">${(window.PR_MODELS || []).map((m) => `<option value="${esc(m.name)}" data-notr>${esc(m.name)}</option>`).join("")}<option value="">其他机型（自己填名称）</option></select></label>
        <label class="small">台数<input id="pr-add-n" type="number" min="1" max="50" value="1" style="width:60px"></label>
        <button id="pr-add" class="mini">＋ 添加</button>
        <span class="small muted">共 ${(CFG.printers || []).length} 台：${prCountByModel()}</span></div>
      <table class="grid" id="printer-table"><thead><tr><th>机器编码</th><th>机型</th><th>备注（位置等）</th><th>类型</th><th>启用</th><th>每小时克数</th><th title="发送切片文件前核对：文件的喷嘴直径要和这里一样">喷嘴 mm</th><th title="填了就核对切片文件用的热床板；不填不核对">现在装的热床板</th><th>打印机配置 (machine)</th><th>工艺配置 (process)</th><th>耗材配置 (filament)</th><th></th></tr></thead><tbody>
      ${(CFG.printers || []).map((p, i) => printerRow(p, i)).join("")}
      </tbody></table>
      <datalist id="dl-machine"></datalist>
      <datalist id="dl-models">${(window.PR_MODELS || []).map((m) => `<option value="${esc(m.name)}">`).join("")}</datalist>
      <div class="row gap wrap"><button id="btn-automatch" class="primary">自动匹配配置</button><button id="btn-find-profiles">查找 OrcaSlicer 和配置文件</button>${window.IN_DOCKER ? "" : '<button id="btn-pick-orca">手动选择程序…</button>'}<span id="profiles-info" class="muted small"></span></div>
      <pre id="slice-log" class="small hidden" style="white-space:pre-wrap;background:#f3f4f6;padding:8px;border-radius:6px;max-height:260px;overflow:auto"></pre>
    </div>`;
const COLORS_CARD = () => `<div class="card cfg-group"><h3>颜色代码表</h3>
      <p class="muted small">每行一个颜色：中文, 代码, 泰文, 英文[, 渲染颜色#RRGGBB]。代码用 1-6 位大写字母/数字，会出现在 SKU 里（例 3DP0001-WH）。已导出的 SKU 不受影响。</p>
      <textarea data-c="color_table" rows="12" class="mono" data-notr>${esc((CFG.color_table || []).map((c) => (Array.isArray(c) ? c.join(", ") : String(c))).join("\n"))}</textarea></div>`;
// 设置页按模块分开（v2.18）：结构来自服务器 /api/settings/schema，以后加模块 / 加设置不用改这里
let CFG_SCHEMA = null, CFG_MOD = "general", INV_ITEMS_CFG = [];
try { CFG_MOD = localStorage.getItem("cfg_mod") || "general"; } catch { /* 忽略 */ }
function cfgField(f) {
  const k = f.key, lab = f.label, t = f.type;
  if (t === "bool") return `<label>${lab}<select data-c="${k}"><option value="true" ${CFG[k] ? "selected" : ""}>是</option><option value="false" ${CFG[k] ? "" : "selected"}>否</option></select></label>`;
  if (Array.isArray(t)) return `<label>${lab}<select data-c="${k}">${t.map((o) => `<option ${o === CFG[k] ? "selected" : ""}>${o}</option>`).join("")}</select></label>`;
  if (t === "list") return `<label>${lab}<input data-c="${k}" value="${esc(Array.isArray(CFG[k]) ? CFG[k].join(", ") : String(CFG[k] ?? ""))}" data-notr></label>`;
  return `<label>${lab}<input data-c="${k}" type="${t === "password" ? "password" : "text"}" value="${esc(CFG[k] ?? "")}"></label>`;
}
// v2.22.1：某一项显示出错只影响那一项，不再让整个设置页变空白
function cfgSafe(fn, what) {
  try { return fn(); } catch (e) {
    console.error("settings render", what, e);
    return `<div class="warn small">${window.I18N && I18N.lang === "th" ? "รายการนี้แสดงผลผิดพลาด" : "这一项显示出错"}（<span data-notr>${esc(what)}</span>）：<span data-notr>${esc(e.message || e)}</span></div>`;
  }
}
function packRuleRow(r = {}) {
  return `<tr><td><select data-pr="item_id" data-notr><option value="">—</option>${INV_ITEMS_CFG.map((it) => `<option value="${it.id}" ${+r.item_id === it.id ? "selected" : ""}>${esc(it.code)} · ${esc(it.name_zh)}</option>`).join("")}</select></td>
    <td><input data-pr="qty" type="number" step="any" value="${r.qty ?? 1}" style="width:70px"></td>
    <td><select data-pr="per"><option value="order" ${r.per !== "item" ? "selected" : ""}>每单</option><option value="item" ${r.per === "item" ? "selected" : ""}>每件商品</option></select></td>
    <td><button class="mini danger" data-prdel-pack>✕</button></td></tr>`;
}
function cfgSpecial(name) {
  if (name === "printers") return PRINTERS_CARD();
  if (name === "colors") return COLORS_CARD();
  if (name === "accel") return window.ACCEL ? ACCEL.card() : "";
  if (name === "remote") return `<div class="card cfg-group" id="sys-remote"><div class="row between"><h3>外网访问（Tailscale）</h3><div class="lockbar" id="sys-remote-bar"></div></div><div id="sys-remote-body" class="small">…</div></div>`;
  if (name === "components") return `<div class="card cfg-group" id="cfg-comps" data-lock-skip><div class="row between"><h3>组件安装情况</h3><button class="mini" id="cfg-comps-reload">重新检查</button></div><div id="cfg-comps-body" class="small">…</div></div>`;
  if (name === "pack_rules") return `<div class="card cfg-group"><h3>发货自动扣包材：扣哪些</h3>
      <p class="muted small">打开上面的开关后，订单从「待发货」变成「已发货」时，按这里的规则从库存领用包材（库存管理里记「发货包材」）。物品要先在「库存 → 库存管理」建好（分类：包材）。</p>
      <table class="grid small" id="pack-rules"><thead><tr><th>包材</th><th>数量</th><th>按</th><th></th></tr></thead><tbody>${(CFG.inv_pack_rules || []).map(packRuleRow).join("")}</tbody></table>
      <button class="mini" id="pack-add">＋ 加一行</button></div>`;
  return "";
}
function collectPackRules() {
  return [...$$("#pack-rules tbody tr")].map((tr) => ({ item_id: tr.querySelector('[data-pr="item_id"]').value, qty: tr.querySelector('[data-pr="qty"]').value,
    per: tr.querySelector('[data-pr="per"]').value })).filter((r) => r.item_id);
}
document.addEventListener("click", (e) => {
  if (e.target.id === "pack-add") $("#pack-rules tbody").insertAdjacentHTML("beforeend", packRuleRow());
  if (e.target.dataset && e.target.dataset.prdelPack !== undefined) e.target.closest("tr").remove();
  const m = e.target.closest && e.target.closest("[data-cfgtab]");
  if (m) cfgShowMod(m.dataset.cfgtab);
  const g = e.target.closest && e.target.closest("[data-goto-cfg]");
  if (g) { e.preventDefault(); CFG_MOD = g.dataset.gotoCfg; goTab("settings"); }
});
// v2.27：设置按大分类；每张卡片单独「✏ 修改」→ 保存；其它地方的设置（账号、对接、客服、模板、组件）也都搬到这里
function cfgShowMod(id) {
  if (cfgEditingOther(null) && !confirm("有一张卡片正在修改还没保存，确定切换？（没保存的修改会丢掉）")) return;
  cfgStopEdits();
  CFG_MOD = id; try { localStorage.setItem("cfg_mod", CFG_MOD); } catch { /* 忽略 */ }
  $$("[data-cfgtab]").forEach((x) => x.classList.toggle("on", x.dataset.cfgtab === CFG_MOD));
  $$("[data-cfgmod]").forEach((x) => x.classList.toggle("hidden", x.dataset.cfgmod !== CFG_MOD));
  $$("[data-cfgext]").forEach((x) => x.classList.toggle("hidden", x.dataset.cfgext !== CFG_MOD));
  $("#cost-summary").classList.toggle("hidden", CFG_MOD !== "cost");
  cfgLoadExt(CFG_MOD);
}
function cfgLoadExt(id) {
  const err = (e) => toast(e.message || String(e), true);
  if (window.MODKIT) MODKIT.settings(id).catch(err);   // v2.29：模块管理 + 模块自己的设置卡片
  if (id === "accounts") { loadUsers(); if (window.EXTKEYS) EXTKEYS.load(); }
  if (id === "goods") renderTplLib().catch(err);
  if (id === "production" && window.PROD && PROD.connSettings) PROD.connSettings($("#cfg-prconn")).catch(err);
  if (id === "ai" && window.OPS) OPS.show("users");
  if (id === "general" && window.SYS) SYS.loadRemote().catch(() => {});
  if (id === "addons" && window.SYS) SYS.loadComps().catch(() => {});
}
function cfgEditingOther(id) {
  return Object.entries(LOCKS).some(([k, v]) => k.startsWith("cfg-") && k !== id && v.editing && v.changed && v.changed());
}
function cfgStopEdits() {
  Object.entries(LOCKS).forEach(([k, v]) => { if (k.startsWith("cfg-") && v.editing) { v.editing = false; if (v.apply) v.apply(); } });
}
async function saveCfgCard(card) {
  const body = {};
  card.querySelectorAll("[data-c]").forEach((el) => (body[el.dataset.c] = el.value));
  if (card.querySelector("#printer-table")) body.printers = collectPrinters();
  if (card.querySelector("#pack-rules")) body.inv_pack_rules = collectPackRules();
  if (!Object.keys(body).length) return;
  const r = await api("/api/config", { json: body });
  CFG = r.config; renderSummary(r.summary); await loadConfig(); toast("已保存");
  $$("#printer-table tbody tr").forEach((tr, i) => {
    const p = (CFG.printers || [])[i]; const inp = tr.querySelector('[data-p="code"]');
    if (p && inp) inp.value = p.code || "";
  });
}
function cfgLockCards() {
  $$("#cfg-form .cfg-group").forEach((card, i) => {
    if (card.hasAttribute("data-lock-skip") || card.id === "sys-remote" || !card.querySelector("[data-c], #printer-table, #pack-rules")) return;
    const h = card.querySelector("h3"); if (!h) return;
    const mod = card.closest("[data-cfgmod]").dataset.cfgmod;
    let bar = card.querySelector(":scope > .row > .lockbar");
    if (!bar) {
      const row = document.createElement("div"); row.className = "row between cfg-head";
      h.replaceWith(row); row.appendChild(h);
      bar = document.createElement("div"); bar.className = "lockbar"; row.appendChild(bar);
    }
    const id = `cfg-${mod}-${i}`;
    if (LOCKS[id]) LOCKS[id].editing = false;
    lockBox(card, { id, bar, label: "✏ 修改", keep: "[data-test], #btn-find-profiles, .cfg-head",
      onEdit: () => {
        if (cfgEditingOther(id) && !confirm("另一张卡片还没保存，先放弃那边的修改？")) { LOCKS[id].editing = false; LOCKS[id].apply(); return; }
        Object.entries(LOCKS).forEach(([k, v]) => { if (k.startsWith("cfg-") && k !== id && v.editing) { v.editing = false; v.apply(); } });
      },
      onSave: () => saveCfgCard(card), onCancel: () => renderSettings() });
  });
}
async function renderSettings() {
  const r = await loadConfig();
  if (!window.PR_MODELS) { try { window.PR_MODELS = (await api("/api/printer-models")).models; } catch { window.PR_MODELS = []; } }
  if (!CFG_SCHEMA) CFG_SCHEMA = (await api("/api/settings/schema")).modules;
  try { INV_ITEMS_CFG = (await api("/api/inv/items")).items.filter((x) => x.category !== "filament" && x.category !== "goods"); } catch { INV_ITEMS_CFG = []; }
  if (!CFG_SCHEMA.some((m) => m.id === CFG_MOD)) CFG_MOD = CFG_SCHEMA[0].id;
  renderSummary(r.summary);
  $("#cost-summary").classList.toggle("hidden", CFG_MOD !== "cost");
  const th = window.I18N && I18N.lang === "th";
  $("#cfg-form").innerHTML = `<div class="chips cfg-mods" style="margin-bottom:10px">${CFG_SCHEMA.map((m) => `<span class="chip ${m.id === CFG_MOD ? "on" : ""}" data-cfgtab="${m.id}">${esc(th ? m.th : m.zh)}</span>`).join("")}</div>` +
    CFG_SCHEMA.map((m) => `<div class="cfg-mod ${m.id === CFG_MOD ? "" : "hidden"}" data-cfgmod="${m.id}">` +
      m.groups.map((g) => `<div class="card cfg-group"><h3>${g.title}</h3><div class="form3">${g.fields.map((f) => cfgSafe(() => cfgField(f), f.key)).join("")}</div></div>`).join("") +
      (m.special || []).map((n) => cfgSafe(() => cfgSpecial(n), n)).join("") + "</div>").join("");
  $$("[data-cfgext]").forEach((x) => x.classList.toggle("hidden", x.dataset.cfgext !== CFG_MOD));
  cfgLockCards();
  cfgLoadExt(CFG_MOD);
}
function renderSummary(s) {
  if (!s) { $("#cost-summary").innerHTML = ""; return; }
  $("#cost-summary").innerHTML = `
    <div>材料成本<b>${s.thb_per_gram} 铢/克</b></div>
    <div>每打印小时成本<b>${s.machine_hour_cost} 铢</b></div>
    <div>每月固定成本<b>${s.fixed_monthly} 铢</b></div>
    <div>每月总机时<b>${s.monthly_machine_hours} 小时</b></div>
    <div class="muted small" style="max-width:360px">机时成本 = 电费 + 固定成本 ÷ 每月总机时。开机率越高，每小时分摊越低。</div>`;
}
const PLATES = [["", "不核对"], ["Textured PEI Plate", "纹理 PEI 板"], ["Smooth PEI Plate", "光面 PEI 板"], ["Cool Plate", "低温板"],
  ["Engineering Plate", "工程板"], ["High Temp Plate", "高温板"], ["SuperTack Plate", "超粘板"]];
function printerRow(p, i) {
  return `<tr data-i="${i}">
        <td><input data-p="code" value="${esc(p.code || "")}" placeholder="自动编号" style="width:84px" class="mono" data-notr></td>
        <td><input data-p="name" list="dl-models" value="${esc(p.name)}" style="min-width:140px" data-notr></td>
        <td><input data-p="note" value="${esc(p.note || "")}" style="width:100px" data-notr></td>
        <td><select data-p="tech" style="width:90px"><option value="fdm" ${p.tech !== "resin" ? "selected" : ""}>FDM</option>${p.tech === "resin" || !window.MODKIT || MODKIT.enabled("resin") ? `<option value="resin" ${p.tech === "resin" ? "selected" : ""}>光固化</option>` : ""}</select></td>
        <td><input type="checkbox" data-p="enabled" ${p.enabled === false ? "" : "checked"}></td>
        <td><input data-p="g_per_h" value="${esc(p.g_per_h)}" style="width:60px"></td>
        <td>${p.tech === "resin" ? '<input type="hidden" data-p="nozzle" value="0.4"><span class="muted small">—</span>' : `<input data-p="nozzle" value="${esc(p.nozzle ?? 0.4)}" style="width:52px">`}</td>
        <td>${p.tech === "resin" ? '<input type="hidden" data-p="plate" value="">' : `<select data-p="plate">${PLATES.map(([v, l]) => `<option value="${v}" ${(p.plate || "") === v ? "selected" : ""}>${l}</option>`).join("")}</select>`}</td>
        <td><input data-p="orca_machine" list="dl-machine" value="${esc(p.orca_machine || "")}" placeholder="自动" style="min-width:180px"></td>
        <td><input data-p="orca_process" list="dl-process-${i}" value="${esc(p.orca_process || "")}" placeholder="自动" style="min-width:180px"><datalist id="dl-process-${i}"></datalist></td>
        <td><input data-p="orca_filament" list="dl-filament-${i}" value="${esc(p.orca_filament || "")}" placeholder="自动" style="min-width:160px"><datalist id="dl-filament-${i}"></datalist></td>
        <td class="nowrap">${p.tech === "resin" ? '<span class="small muted">光固化：电脑上切好上传</span>' : `<button data-test="${i}">测试切片</button>`} <button class="mini danger" data-prdel>删除</button></td></tr>`;
}
function prCountByModel() {
  const n = {}; (CFG.printers || []).forEach((p) => (n[p.name] = (n[p.name] || 0) + 1));
  return Object.entries(n).map(([k, v]) => `<span data-notr>${esc(k)}</span> × ${v}`).join("，");
}
// 打印机配置下拉：点输入框时按这一行选的打印机加载兼容的工艺/耗材
let PRESET_MACHINES = null;
document.addEventListener("focusin", async (e) => {
  const k = e.target.dataset && e.target.dataset.p;
  if (!k || !k.startsWith("orca_")) return;
  const tr = e.target.closest("tr"); const i = tr.dataset.i;
  try {
    if (k === "orca_machine") {
      if (!PRESET_MACHINES) PRESET_MACHINES = (await api("/api/slicer/presets")).machines;
      $("#dl-machine").innerHTML = PRESET_MACHINES.map((n) => `<option value="${esc(n)}">`).join("");
      return;
    }
    const m = tr.querySelector('[data-p="orca_machine"]').value.trim();
    if (!m) return;
    const r = await api("/api/slicer/presets?machine=" + encodeURIComponent(m));
    $(`#dl-process-${i}`).innerHTML = r.processes.map((n) => `<option value="${esc(n)}">`).join("");
    $(`#dl-filament-${i}`).innerHTML = r.filaments.map((n) => `<option value="${esc(n)}">`).join("");
  } catch { /* 没装 OrcaSlicer 时忽略 */ }
});
function collectPrinters() {
  return $$("#printer-table tbody tr").map((tr) => {
    const o = {}; tr.querySelectorAll("[data-p]").forEach((el) => (o[el.dataset.p] = el.type === "checkbox" ? el.checked : el.value)); return o;
  });
}
$("#cfg-form").addEventListener("change", (e) => {
  // 选了常用机型：自动填每小时克数
  if (e.target.dataset && e.target.dataset.p === "name") {
    const m = (window.PR_MODELS || []).find((x) => x.name === e.target.value);
    const tr = e.target.closest("tr");
    const g = tr.querySelector('[data-p="g_per_h"]');
    if (m && g) g.value = m.g_per_h || 20;
    const t = tr.querySelector('[data-p="tech"]');
    if (m && t) t.value = m.tech || "fdm";
  }
});
$("#cfg-form").addEventListener("click", async (e) => {
  if (e.target.id === "pr-add") {
    const model = $("#pr-add-model").value, n = Math.max(1, Math.min(50, +$("#pr-add-n").value || 1));
    const m = (window.PR_MODELS || []).find((x) => x.name === model);
    const tb = $("#printer-table tbody");
    for (let k = 0; k < n; k++) {
      const i = tb.children.length;
      tb.insertAdjacentHTML("beforeend", printerRow({ name: model || "", g_per_h: m ? (m.g_per_h || 20) : 20, enabled: true, tech: (m && m.tech) || "fdm" }, i));
    }
    toast(`已添加 ${n} 行，点「保存」后自动编号`);
    return;
  }
  if (e.target.dataset && e.target.dataset.prdel !== undefined) {
    const tr = e.target.closest("tr");
    const code = tr.querySelector('[data-p="code"]').value || "新打印机";
    if ($$("#printer-table tbody tr").length <= 1) { toast("至少要保留一台打印机", true); return; }
    if (!confirm(`删除打印机 ${code}？\n排给它的任务会自动转到其他机器；打印记录保留。点「保存」后生效。`)) return;
    tr.remove();
    return;
  }
  if (e.target.id === "btn-automatch") {
    await busy(e.target, async () => {
      const r = await api("/api/slicer/automatch", { json: { printers: collectPrinters(), force: true } });
      CFG.printers = r.printers;
      $$("#printer-table tbody tr").forEach((tr, i) => {
        for (const k of ["orca_machine", "orca_process", "orca_filament"]) tr.querySelector(`[data-p="${k}"]`).value = r.printers[i][k] || "";
      });
      $("#profiles-info").textContent = `OrcaSlicer：${r.orca || "没有找到"}`;
      if (r.missing.length) toast(`这些打印机没能自动匹配，请手动选择打印机配置：${r.missing.join("、")}`, true);
      else toast("已自动匹配并保存，可以点「测试切片」");
    });
  }
  if (e.target.id === "btn-find-profiles") {
    await busy(e.target, async () => {
      const r = await api("/api/slicer/info");
      const n = r.presets && r.presets.machine !== undefined ? r.presets.machine + r.presets.process + r.presets.filament : 0;
      $("#profiles-info").textContent = `OrcaSlicer：${r.orca || "没有找到"}；找到 ${n} 个配置文件（在输入框里点一下即可选择）`;
      const inp = document.querySelector('[data-c="orca_path"]');
      if (r.orca) { CFG.orca_path = r.orca; if (inp) inp.value = r.orca; }
      const log = $("#slice-log");
      if (!r.orca) {
        log.classList.remove("hidden");
        log.textContent = "没有自动找到 OrcaSlicer，请点「手动选择程序…」，在弹出的窗口里找到 orca-slicer.exe（或桌面上的 OrcaSlicer 快捷方式）。\n\n查找过程：\n" + (r.tried || []).join("\n");
      }
    });
  }
  if (e.target.id === "btn-pick-orca") {
    await busy(e.target, async () => {
      toast("请在电脑上弹出的窗口里选择 orca-slicer.exe（窗口可能在浏览器后面）");
      const r = await api("/api/slicer/pick", { json: {} });
      const inp = document.querySelector('[data-c="orca_path"]');
      CFG.orca_path = r.orca; if (inp) inp.value = r.orca;
      $("#profiles-info").textContent = `OrcaSlicer：${r.orca}`;
      toast("已保存 OrcaSlicer 路径");
    });
  }
  const t = e.target.dataset.test;
  if (t !== undefined) {
    await busy(e.target, async () => {
      await api("/api/config", { json: { printers: collectPrinters() } });
      const log = $("#slice-log"); log.classList.remove("hidden");
      try {
        const r = await api("/api/slicer/test", { json: { printer: Number(t) } });
        log.textContent = `✓ 测试成功：20mm 立方体 ${r.grams} g，${r.hours} h\n\n${r.log || ""}`;
      } catch (err) { log.textContent = "✗ " + err.message; }
    });
  }
});
// ---------------- 账号 ----------------
let ME = null;
const ROLE_ZH = { owner: "老板", listing: "上架客服", production: "生产打包" };
async function loadMe() {
  const r = await api("/api/me");
  ME = r.user;
  document.body.dataset.role = ME.role;
  $$("#subnav .tab[data-roles]").forEach((b) => b.classList.toggle("role-hidden", !b.dataset.roles.split(",").includes(ME.role)));
  // 老板给员工精简过页面：只显示勾选的（工作台一直显示）
  if (ME.role !== "owner" && ME.tabs && ME.tabs.length)
    $$("#subnav .tab").forEach((b) => { if (b.dataset.tab !== "dashboard" && !b.classList.contains("ghost") && !ME.tabs.includes(b.dataset.tab)) b.classList.add("role-hidden"); });
  $$("#modnav .mod").forEach((m) => m.classList.toggle("hidden", !visibleTabs(m.dataset.mod).length));
  if (r.login_required) {
    $("#me-box").innerHTML = `<span data-notr>${esc(ME.display_name)}</span><span>（${ROLE_ZH[ME.role] || ME.role}）</span>
      <a id="me-pw">改密码</a><a id="me-out">退出</a>`;
  } else {
    $("#me-box").innerHTML = "";
  }
  // v2.26：外网（Tailscale）打开时标出来；老板看到有新版本时顶部提示
  if (/^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(location.hostname) || /\.ts\.net$/.test(location.hostname))
    $("#ver").insertAdjacentHTML("afterend", ' <span class="chip ok small" title="通过 Tailscale 外网访问">🌐 外网</span>');
  if (ME.role === "owner") {
    api("/api/system/update").then((u) => {
      if (u.available && !$("#upd-badge")) $("#ver").insertAdjacentHTML("afterend", ` <a id="upd-badge" class="chip warn small" href="#">🆕 新版本 v${esc(u.latest)}</a>`);
    }).catch(() => {});
  }
}
document.addEventListener("click", (e) => {
  if (e.target.id !== "upd-badge") return;
  e.preventDefault(); showTab("system");
});
document.addEventListener("click", async (e) => {
  if (e.target.id === "me-out") {
    if (dirty && P) await saveProduct(true);
    await api("/api/auth/logout", { json: {} }); location.href = "/login";
  }
  if (e.target.id === "me-pw") {
    const old = prompt("原密码"); if (old == null) return;
    const nw = prompt("新密码（至少 6 位）"); if (!nw) return;
    try { await api("/api/me/password", { json: { old, new: nw } }); toast("密码已修改"); } catch (err) { toast(err.message, true); }
  }
});
// 切换界面语言时记到账号上（下次在别的电脑登录也是这个语言）
$("#lang-select").addEventListener("change", (e) => {
  try { navigator.sendBeacon("/api/me/lang", new Blob([JSON.stringify({ lang: e.target.value })], { type: "application/json" })); } catch { /* 忽略 */ }
});
function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), z = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())} ${z(d.getHours())}:${z(d.getMinutes())}`;
}
let USERS_PERMS = [];
// 某个角色能看到的页面（按菜单里的 data-roles）
function roleTabs(role) {
  return $$("#subnav .tab").filter((b) => !b.classList.contains("ghost") && b.dataset.tab !== "dashboard" &&
    (!b.dataset.roles || b.dataset.roles.split(",").includes(role)))
    .map((b) => [b.dataset.tab, ($(`#modnav .mod[data-mod="${b.dataset.mod}"]`) || {}).textContent + " · " + b.textContent]);
}
function tabsPicker(u) {
  const all = roleTabs(u.role), on = u.tabs && u.tabs.length ? u.tabs : all.map((x) => x[0]);
  const n = all.filter((x) => on.includes(x[0])).length;
  return `<details class="tabs-pick"><summary>${n === all.length ? "全部" : `${n} / ${all.length} 个`}页面</summary>
    ${all.map(([k, lab]) => `<label class="row small perm-cb"><input type="checkbox" data-tabcb="${k}" ${on.includes(k) ? "checked" : ""} disabled> ${esc(lab)}</label>`).join("")}
    <div class="muted small">只影响菜单显示，权限仍按角色</div></details>`;
}
async function loadUsers() {
  const r = await api("/api/users");
  USERS_PERMS = r.perm_list || [];
  $("#users-table tbody").innerHTML = r.users.map((u) => `<tr data-uid="${u.id}">
    <td data-notr><b>${esc(u.username)}</b></td>
    <td><input data-u="display_name" value="${esc(u.display_name)}" style="width:110px" data-notr disabled></td>
    <td><select data-u="role" disabled>${Object.keys(ROLE_ZH).map((k) => `<option value="${k}" ${k === u.role ? "selected" : ""}>${ROLE_ZH[k]}</option>`).join("")}</select></td>
    <td><select data-u="lang" data-notr disabled><option value="zh" ${u.lang === "zh" ? "selected" : ""}>中文</option><option value="th" ${u.lang === "th" ? "selected" : ""}>ภาษาไทย</option></select></td>
    <td><input type="checkbox" data-u="active" ${u.active ? "checked" : ""} disabled></td>
    <td class="small">${u.role === "owner" ? '<span class="muted">全部权限</span>' : (USERS_PERMS || []).map(([k, lab]) =>
      `<label class="row small perm-cb"><input type="checkbox" data-perm="${k}" ${u.perms && u.perms[k] ? "checked" : ""} disabled> ${esc(lab)}</label>`).join("")}</td>
    <td class="small">${u.role === "owner" ? '<span class="muted">全部页面</span>' : tabsPicker(u)}</td>
    <td class="small muted">${fmtTime(u.last_login)}</td>
    <td class="nowrap"><button class="mini" data-act="edit-user">✏ 修改</button><button class="mini primary hidden" data-act="save-user">💾 保存</button>
      <button class="mini hidden" data-act="cancel-user">取消</button> <button class="mini" data-act="reset-pw">重设密码</button></td></tr>`).join("");
}
async function loadAudit() {
  const q = new URLSearchParams({ user: $("#lg-user").value, days: $("#lg-days").value, q: $("#lg-q").value.trim(),
    hide_login: $("#lg-hidelogin").checked ? "1" : "", limit: 2000 });
  const r = await api("/api/audit?" + q);
  const cur = $("#lg-user").value;
  $("#lg-user").innerHTML = '<option value="">全部账号</option>' + r.users.map((u) => `<option ${u === cur ? "selected" : ""} data-notr>${esc(u)}</option>`).join("");
  const days = {};
  r.items.forEach((a) => (days[fmtTime(a.ts).slice(0, 10)] = days[fmtTime(a.ts).slice(0, 10)] || []).push(a));
  const keys = Object.keys(days);
  $("#audit-days").innerHTML = keys.map((d, i) => {
    const rows = days[d];
    const who = [...new Set(rows.map((a) => a.username))].slice(0, 6).join("、");
    return `<details class="card log-day" ${i === 0 ? "open" : ""}><summary><b>${d}</b> <span class="muted small">${rows.length} 条 · <span data-notr>${esc(who)}</span></span></summary>
      <table class="grid small"><thead><tr><th>时间</th><th>账号</th><th>操作</th><th>对象</th><th>详情</th></tr></thead><tbody>
      ${rows.map((a) => `<tr><td class="nowrap">${fmtTime(a.ts).slice(11)}</td><td data-notr>${esc(a.username)}</td><td>${esc(a.action)}</td>
        <td class="mono" data-notr>${esc(a.target || "")}</td><td class="small" data-notr>${esc(a.detail || "")}</td></tr>`).join("")}</tbody></table></details>`;
  }).join("") || '<p class="muted">没有记录</p>';
}
$("#btn-audit-reload").addEventListener("click", loadAudit);
["#lg-user", "#lg-days", "#lg-hidelogin"].forEach((k) => $(k).addEventListener("change", loadAudit));
{ let t = null; $("#lg-q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(loadAudit, 300); }); }
$("#lg-expand").addEventListener("click", () => $$("#audit-days details").forEach((d) => (d.open = true)));
$("#lg-collapse").addEventListener("click", () => $$("#audit-days details").forEach((d) => (d.open = false)));
$("#users-table").addEventListener("click", async (e) => {
  const act = e.target.dataset.act; if (!act) return;
  const tr = e.target.closest("tr"), uid = tr.dataset.uid;
  try {
    if (act === "edit-user" || act === "cancel-user") {
      if (act === "cancel-user") return loadUsers();
      tr.querySelectorAll("[data-u], [data-perm], [data-tabcb]").forEach((el) => (el.disabled = false));
      const tp = tr.querySelector(".tabs-pick"); if (tp) tp.open = true;
      tr.classList.add("is-editing");
      ["edit-user", "save-user", "cancel-user"].forEach((a) => tr.querySelector(`[data-act="${a}"]`).classList.toggle("hidden", a === "edit-user"));
      return;
    }
    if (act === "save-user") {
      const body = {};
      tr.querySelectorAll("[data-u]").forEach((el) => (body[el.dataset.u] = el.type === "checkbox" ? el.checked : el.value));
      const pm = {}; tr.querySelectorAll("[data-perm]").forEach((el) => (pm[el.dataset.perm] = el.checked));
      if (Object.keys(pm).length) body.perms = pm;
      const tcb = tr.querySelectorAll("[data-tabcb]");
      if (tcb.length) {
        const on = [...tcb].filter((el) => el.checked).map((el) => el.dataset.tabcb);
        if (!on.length) { toast("至少要勾选一个页面", true); return; }
        body.tabs = on.length === tcb.length ? [] : on;
      }
      await api(`/api/users/${uid}`, { json: body }); toast("已保存"); loadUsers();
    }
    if (act === "reset-pw") {
      const pw = prompt("新密码（至少 6 位）"); if (!pw) return;
      await api(`/api/users/${uid}`, { json: { password: pw } }); toast("密码已重设，请告诉员工新密码");
    }
  } catch (err) { toast(err.message, true); }
});
$("#btn-nu").addEventListener("click", async (e) => {
  await busy(e.target, async () => {
    const r = await api("/api/users", { json: { username: $("#nu-username").value, display_name: $("#nu-name").value,
      role: $("#nu-role").value, lang: $("#nu-lang").value, password: $("#nu-pw").value } });
    ["#nu-username", "#nu-name", "#nu-pw"].forEach((k) => ($(k).value = ""));
    toast(`已创建账号 ${r.user.username}。以后打开系统需要登录。`); loadUsers(); loadMe();
  });
});

// ---------------- 启动 ----------------
(async () => {
  // v2.31：等页面上所有的 js（包括模块的）都加载完再开始
  if (document.readyState === "loading") await new Promise((r) => document.addEventListener("DOMContentLoaded", r, { once: true }));
  try { await loadMe(); } catch (e) { toast(e.message, true); return; }
  if (window.MODKIT) await MODKIT.init();             // v2.29：模块的菜单
  try { await loadConfig(); } catch (e) { toast(e.message, true); }
  await renderEditor();
  const want = (location.hash || "").slice(1);
  const ok = want && $(`#subnav .tab[data-tab="${want}"]`) && !$(`#subnav .tab[data-tab="${want}"]`).classList.contains("role-hidden");
  showTab(ok ? want : (ME && ME.role === "production" ? "production" : "dashboard"));
})();


// ---------------- AI 打印建议 + 产品描述 ----------------
const ORIENT_LABEL = { bottom: "原始方向（底面朝下）", top: "倒放（顶面朝下）", front: "前面朝下平放", back: "背面朝下平放", left: "左侧朝下平放", right: "右侧朝下平放" };
const SUPPORT_LABEL = { none: "不需要支撑", tree: "树状支撑（自动）", normal: "普通支撑（自动）" };
function L(x) {   // 双语字段按界面语言显示
  if (!x) return "";
  if (typeof x === "string") return x;
  return (window.I18N && I18N.lang === "th" && x.th) ? x.th : (x.zh || x.th || "");
}
function renderAdvice() {
  const a = P && P.print_advice, box = $("#advice-out");
  if (!box) return;
  if (!a) { box.innerHTML = ""; return; }
  $("#advice-prompt").value = a.prompt || "";
  const an = a.analysis || {};
  const rows = (an.orientations || []).map((o) => `<tr class="${o.key === a.orientation.pick ? "best" : ""}"><td>${ORIENT_LABEL[o.key] || o.key}${o.key === a.orientation.pick ? " ✓" : ""}</td>
    <td>${o.overhang_cm2}</td><td>${o.contact_cm2}</td><td>${o.height_mm}</td></tr>`).join("");
  const list = (arr) => (arr || []).filter((x) => L(x)).map((x) => `<li data-notr>${esc(L(x))}</li>`).join("");
  box.innerHTML = `<div class="advice">
    <div class="row between wrap gap"><div><b>AI 判断：</b><span data-notr>${esc(L(a.product_guess))}</span></div><span class="muted small">${esc(a.created_at || "")}</span></div>
    <h5>产品描述（用途 / 卖点）</h5>
    <div data-notr class="small" style="white-space:pre-wrap">${esc(a.features_zh || "")}</div>
    ${a.features_warning ? '<div class="warn small">描述里提到了制造方式，填入后请删掉</div>' : ""}
    <div class="row gap wrap" style="margin-top:4px">
      <button class="mini" id="adv-fill-feat">填入「用途/卖点」（替换）</button>
      <button class="mini" id="adv-add-feat">追加到「用途/卖点」</button>
      ${a.name_zh_suggest ? `<button class="mini" id="adv-fill-name">产品名称用「<span data-notr>${esc(a.name_zh_suggest)}</span>」</button>` : ""}
    </div>
    <h5>打印建议</h5>
    <div class="kv">
      <div>材质<b data-notr>${esc(a.material.pick)}</b>${a.material.alternatives.length ? `<span class="muted small">备选：${esc(a.material.alternatives.join(" / "))}</span>` : ""}</div>
      <div>摆放方向<b>${ORIENT_LABEL[a.orientation.pick] || a.orientation.pick}</b></div>
      <div>层高<b>${a.layer_height_mm} mm</b></div>
      <div>壁数 / 顶底层<b>${a.walls} / ${a.top_bottom_layers}</b></div>
      <div>填充<b>${a.infill_pct}% <span data-notr>${esc(a.infill_pattern)}</span></b></div>
      <div>支撑<b>${SUPPORT_LABEL[a.supports] || a.supports}</b></div>
      <div>帽檐 (brim)<b>${a.brim ? "需要帽檐" : "不需要帽檐"}</b></div>
    </div>
    <div class="row gap wrap" style="margin-top:6px">
      ${String(P.material || "PLA").toUpperCase() !== a.material.pick ? `<button class="mini" id="adv-material">产品材质改为 <span data-notr>${esc(a.material.pick)}</span></button>` : ""}
      <label class="row gap small"><input type="checkbox" id="adv-applied" ${a.applied ? "checked" : ""}> 估算和 OrcaSlicer 自动切片按这些参数（填充率、壁数、层高、支撑、帽檐）</label>
    </div>
    <ul class="small">
      ${L(a.material.why) ? `<li><b>材质：</b><span data-notr>${esc(L(a.material.why))}</span></li>` : ""}
      ${L(a.orientation.why) ? `<li><b>方向：</b><span data-notr>${esc(L(a.orientation.why))}</span></li>` : ""}
      ${L(a.settings_why) ? `<li><b>参数：</b><span data-notr>${esc(L(a.settings_why))}</span></li>` : ""}
      ${L(a.support_why) ? `<li><b>支撑：</b><span data-notr>${esc(L(a.support_why))}</span></li>` : ""}
      ${L(a.temp_speed) ? `<li><b>温度/速度：</b><span data-notr>${esc(L(a.temp_speed))}</span></li>` : ""}
      ${L(a.strength) ? `<li><b>强度/耐用：</b><span data-notr>${esc(L(a.strength))}</span></li>` : ""}
    </ul>
    ${list(a.risks) ? `<h5>可能的问题和预防</h5><ul class="small">${list(a.risks)}</ul>` : ""}
    ${list(a.quality_tips) ? `<h5>提升质量的小技巧</h5><ul class="small">${list(a.quality_tips)}</ul>` : ""}
    ${list(a.post_process) ? `<h5>后处理</h5><ul class="small">${list(a.post_process)}</ul>` : ""}
    ${rows ? `<details><summary class="small">模型几何分析（6 个摆放方向）</summary>
      <table class="grid orient-table small"><thead><tr><th>方向</th><th>悬空面积 cm²</th><th>底面接触 cm²</th><th>高度 mm</th></tr></thead><tbody>${rows}</tbody></table>
      ${an.tall_thin ? '<div class="warn small">模型细高，打印时容易倒，建议加帽檐或换方向</div>' : ""}</details>` : ""}
  </div>`;
}
async function imageToDataUrl(url, size = 768) {
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
  const c = document.createElement("canvas"); c.width = c.height = size;
  const g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, size, size);
  const k = Math.min(size / img.width, size / img.height);
  g.drawImage(img, (size - img.width * k) / 2, (size - img.height * k) / 2, img.width * k, img.height * k);
  return c.toDataURL("image/jpeg", 0.85);
}
$("#btn-advice").addEventListener("click", async (e) => {
  if (!P) return;
  if (dirty) await saveProduct(true);
  await busy(e.target, async () => {
    $("#advice-prog").textContent = "AI 分析中（约 20-60 秒）…";
    try {
      let analysis = null, image = "";
      if (VIEWER && VIEWER.model && P.model) {
        analysis = VIEWER.analyze();
        const cur = $("#view-chips").dataset.cur || colorList()[0] || "", ci = colorInfo(cur);
        VIEWER.setColor(ci.hex, ci.code);
        image = VIEWER.shot({ size: 768 });
      } else if ((P.images || []).length) {
        image = await imageToDataUrl(imgSrc(P.images[0]));
      }
      const r = await apiJob(`/api/products/${P.id}/print-advice`, { json: { analysis, prompt: $("#advice-prompt").value.trim(), image } });
      P = r.product; renderAdvice();
      toast("已生成打印建议");
    } finally { $("#advice-prog").textContent = ""; }
  });
});
$("#advice-out").addEventListener("click", async (e) => {
  const id = e.target.closest("button") && e.target.closest("button").id;
  const a = P && P.print_advice; if (!id || !a) return;
  const setF = (k, v) => { P[k] = v; const el = document.querySelector(`[data-f="${k}"]`); if (el) el.value = v; markDirty(); };
  if (id === "adv-fill-feat") { if (P.features_zh && !confirm("替换现有的用途/卖点？")) return; setF("features_zh", a.features_zh); toast("已填入，记得保存"); }
  if (id === "adv-add-feat") { setF("features_zh", ((P.features_zh || "").trim() + "\n" + a.features_zh).trim()); toast("已追加，记得保存"); }
  if (id === "adv-fill-name") { setF("name_zh", a.name_zh_suggest); toast("已填入，记得保存"); }
  if (id === "adv-material") { setF("material", a.material.pick); await saveProduct(true); renderAdvice(); toast("材质已修改并保存"); }
});
$("#advice-out").addEventListener("change", async (e) => {
  if (e.target.id !== "adv-applied") return;
  if (dirty) await saveProduct(true);
  try {
    const r = await api(`/api/products/${P.id}/print-advice/apply`, { json: { applied: e.target.checked } });
    P = r.product; renderEstimate();
    toast(e.target.checked ? "估算已按建议参数更新；OrcaSlicer 自动切片也会用这些参数" : "已恢复默认参数");
  } catch (err) { toast(err.message, true); }
});

// ---- 真实打印质感（层纹 / 顶面走线 / 表面效果 / 地面阴影） ----
function plPref(k, v) { try { if (v === undefined) return localStorage.getItem("pl_" + k); localStorage.setItem("pl_" + k, v); } catch { /* 无痕模式 */ } return null; }
(function initPrintLook() {
  const on = plPref("on"), sh = plPref("shadow"), sf = plPref("surface");
  if (on !== null) $("#pl-on").checked = on === "1";
  if (sh !== null) $("#pl-shadow").checked = sh === "1";
  if (sf) $("#pl-surface").value = sf;
})();
function printOpts() {
  const r = (P && P.recipe) || {};
  const lv = $("#pl-layer").value;
  return { on: $("#pl-on").checked, shadow: $("#pl-shadow").checked, surface: $("#pl-surface").value,
    material: (P && P.material) || "PLA", orient: r.orientation || "bottom", layer: lv === "auto" ? (+r.layer_height || 0.2) : +lv };
}
["#pl-on", "#pl-shadow", "#pl-surface", "#pl-layer"].forEach((k) => $(k).addEventListener("change", (e) => {
  const t = e.target;
  if (t.id !== "pl-layer") plPref(t.id.slice(3), t.type === "checkbox" ? (t.checked ? "1" : "0") : t.value);
  if (VIEWER && VIEWER.model) VIEWER.setPrint(printOpts());
}));

$("#viewer-safe").addEventListener("change", (e) => {
  if (!VIEWER) return;
  VIEWER.setSafe(e.target.checked);
  toast(e.target.checked ? "已切换到兼容显示模式" : "已切换到标准显示模式");
});

// ---------------- 图片点击放大查看（v2.18）：编辑页图片、白底图；← → 切换，Esc / 点空白关闭 ----------------
(function () {
  let LIST = [], IDX = 0, box = null;
  function draw() {
    const img = box.querySelector("img");
    img.src = LIST[IDX];
    box.querySelector(".lb-n").textContent = LIST.length > 1 ? `${IDX + 1} / ${LIST.length}` : "";
    box.querySelectorAll(".lb-nav").forEach((b) => b.classList.toggle("hidden", LIST.length < 2));
  }
  function open(list, idx) {
    LIST = list; IDX = idx;
    if (!box) {
      box = document.createElement("div");
      box.className = "lightbox";
      box.innerHTML = '<img alt=""><button class="lb-nav lb-prev" aria-label="prev">‹</button><button class="lb-nav lb-next" aria-label="next">›</button>' +
        '<button class="lb-close" aria-label="close">✕</button><a class="lb-open" target="_blank" rel="noopener">↗</a><div class="lb-n"></div>';
      document.body.appendChild(box);
      box.addEventListener("click", (e) => {
        if (e.target.classList.contains("lb-prev")) { IDX = (IDX + LIST.length - 1) % LIST.length; draw(); }
        else if (e.target.classList.contains("lb-next")) { IDX = (IDX + 1) % LIST.length; draw(); }
        else if (e.target === box || e.target.classList.contains("lb-close")) close();
      });
    }
    box.querySelector(".lb-open").href = LIST[IDX];
    box.classList.add("on");
    draw();
  }
  function close() { if (box) box.classList.remove("on"); }
  document.addEventListener("keydown", (e) => {
    if (!box || !box.classList.contains("on")) return;
    if (e.key === "Escape") close();
    else if (e.key === "ArrowLeft") { IDX = (IDX + LIST.length - 1) % LIST.length; draw(); }
    else if (e.key === "ArrowRight") { IDX = (IDX + 1) % LIST.length; draw(); }
  });
  document.addEventListener("click", (e) => {
    const img = e.target.closest("#img-grid .img-card > img, #white-box .img-card > img, img[data-zoom]");
    if (!img) return;
    const scope = img.closest("#img-grid, #white-box") || document;
    const all = [...scope.querySelectorAll(scope === document ? "img[data-zoom]" : ".img-card > img")];
    open(all.map((x) => x.dataset.full || x.src), Math.max(0, all.indexOf(img)));
  });
  window.LIGHTBOX = { open, close };
})();
