"use strict";
const APP_JS_VERSION = "2.41.1";   // 必须和 app.py 的 VERSION 一致
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
  // 各页面脚本自己处理「打开了哪个页面」（v2.34：原来写在 ops.js 里，现在内核统一通知）
  ["OPS", "PROD", "HOME", "FILES", "SYS", "AS", "SHIP", "PACK", "INV"].forEach((k) => { if (window[k] && window[k].show) window[k].show(name); });
  if (name === "materials" && window.MATERIALS) MATERIALS.load();   // v2.31：耗材料卷在生产模块
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
  if (name === "pack_rules") return `<div class="card cfg-group"><h3>发货出库：另外每单 / 每件要扣的包材</h3>
      <p class="muted small">纸箱按产品设（编辑产品 → 包装纸箱，用邮政标准规格），这里只填纸箱以外的：胶带、气泡袋、快递袋、感谢卡、面单纸……订单变成「已发货」时，和成品、纸箱一起记在这单的出库单里。物品要先在「库存 → 库存管理」建好（分类：包材）。</p>
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
  if (id === "ai" && window.INTG_UI) INTG_UI.load().catch((e) => toast(e.message, true));
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


// 双语字段按界面语言显示（各模块都用）
function L(x) {   // 双语字段按界面语言显示
  if (!x) return "";
  if (typeof x === "string") return x;
  return (window.I18N && I18N.lang === "th" && x.th) ? x.th : (x.zh || x.th || "");
}

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

// ---------------- 公用小工具（订单、生产、客服、工作台……各模块都用；v2.34 从 ops.js 搬到内核）----------------
(function () {
  const PLAT = { lazada: "Lazada", shopee: "Shopee", tiktok: "TikTok", manual: "手工", wholesale: "批发站", chat: "聊天成交", other: "其他" };
  const KIND_ZH = { normal: "", manual: "私下成交", wholesale: "批发/大单", custom: "定制单", quote: "报价" };
  const JOB_ZH = { todo: "待打印", printing: "打印中", post: "后处理", packed: "已打包", done: "已发货", failed: "打印失败" };
  const role = () => (typeof ME !== "undefined" && ME ? ME.role : "owner");
  const isOwner = () => role() === "owner";
  const money = (v) => (v === null || v === undefined || v === "") ? "" : "฿" + Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
  const num = (v, d = 2) => (v === null || v === undefined || v === "") ? "" : String(Number(Number(v).toFixed(d)));
  const day = (ts) => (ts ? fmtTime(ts).slice(0, 10) : "");
  const short = (ts) => (ts ? fmtTime(ts).slice(5) : "");
  const colorTxt = (c) => (c ? `${swatch(c, "var-sw")}<span data-notr>${esc(colorLabel(c))}</span>` : "");
  const today = () => { const d = new Date(), z = (n) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`; };

  function printerName(i) {          // 结果常放在 data-notr 里，所以这里直接按界面语言给
    const th = window.I18N && I18N.lang === "th";
    if (i === null || i === undefined) return th ? "ยังไม่ได้กำหนด" : "未分配";
    const p = (CFG && CFG.printers && CFG.printers[i]);
    return p ? `${p.code || "#" + (i + 1)} · ${p.name || ""}` : (i == null ? "" : `${th ? "เครื่องพิมพ์" : "打印机"}${i + 1}`);
  }
  function stChip(st, zh) {
    if (!st || !st.state || st.state === "none") return '<span class="pill pst-none">未连接</span>';
    const pr = st.state === "printing" && st.progress != null ? ` ${st.progress}%` : "";
    const rm = st.state === "printing" && st.remaining_min ? ` · 剩 ${Math.floor(st.remaining_min / 60)}h${st.remaining_min % 60}m` : "";
    return `<span class="pill pst-${st.state}">${esc(zh)}${pr}${rm}</span>`;
  }
  function trayHtml(st) {
    const t = (st && st.trays) || [];
    if (!t.length) return "";
    return `<div class="trays">${t.map((x) => `<span class="tray ${String(st.tray_now) === String(x.slot) ? "on" : ""}" title="${esc(x.type || "")}">
      <span class="sw" style="background:${esc(x.hex || "#ccc")}"></span>${esc(x.label)} <span class="muted">${esc(x.type || "")}${x.remain != null && x.remain >= 0 ? " " + x.remain + "%" : ""}</span></span>`).join("")}</div>`;
  }
  window.OPSH = { PLAT, KIND_ZH, JOB_ZH, money, num, day, short, colorTxt, stChip, trayHtml, printerName, today, isOwner, role };
})();

// ---------------- API 密钥（老板；设置 → 账号）：v2.34 从 ops.js 搬到内核 ----------------
(function () {
  const { day, isOwner } = window.OPSH;
  // v2.30：店铺对接、3D选品工具对接搬到了「对接」模块（modules/link/ui/settings.js）
  let INTG = null;
  async function loadIntegrations() {
    if (!isOwner()) return;
    INTG = await api("/api/integrations");
    $("#intg-keys tbody").innerHTML = INTG.keys.map((k) => `<tr><td data-notr>${esc(k.name)}</td><td class="mono" data-notr>${esc(k.prefix)}…</td>
      <td>${k.scope === "read" ? '<span class="pill ok-pill">只读</span>' : k.scope === "ops" ? '<span class="pill warn-pill">运营写回</span>' : k.scope === "catalog" ? '<span class="pill tag-pill">建产品</span>' : k.scope === "wholesale" ? '<span class="pill tag-pill">批发站</span>' : k.scope === "chat" ? '<span class="pill tag-pill">AI 接待</span>' : "完整"}</td>
      <td class="nowrap">${day(k.created_at)}</td><td class="nowrap">${k.last_used ? fmtTime(k.last_used) : "-"}</td><td>${k.uses || 0}</td>
      <td><input type="checkbox" data-keyact="${k.id}" ${k.active ? "checked" : ""}></td>
      <td><button class="danger mini-x" data-keydel="${k.id}">删除</button></td></tr>`).join("") || '<tr><td colspan="8" class="muted">还没有密钥</td></tr>';
    document.dispatchEvent(new CustomEvent("intg-loaded", { detail: INTG }));   // 对接模块用（店铺列表、选品工具密钥）
  }
  $("#intg").addEventListener("click", async (e) => {
    const t = e.target, d = t.dataset;
    try {
      if (t.id === "btn-key-new") {
        const r = await api("/api/apikeys", { json: { name: $("#key-name").value || "API", scope: $("#key-scope") ? $("#key-scope").value : ($("#key-readonly").checked ? "read" : "full") } });
        $("#key-name").value = "";
        if ($("#key-readonly")) $("#key-readonly").checked = false;
        $("#key-new-out").innerHTML = `<p class="note-flag">新密钥（只显示这一次，请复制保存）：<b class="mono" data-notr>${esc(r.key)}</b></p>`;
        return loadIntegrations();
      }
      if (d.keydel) { if (!confirm("删除这个密钥？用它的程序会马上不能用。")) return; await api(`/api/apikeys/${d.keydel}`, { method: "DELETE" }); return loadIntegrations(); }
    } catch (err) { toast(err.message, true); }
  });
  $("#intg").addEventListener("change", async (e) => {
    const id = e.target.dataset.keyact;
    if (!id) return;
    try { await api(`/api/apikeys/${id}`, { json: { active: e.target.checked } }); toast(e.target.checked ? "已启用" : "已停用"); }
    catch (err) { toast(err.message, true); }
  });
  window.INTG_UI = { load: loadIntegrations };
})();
