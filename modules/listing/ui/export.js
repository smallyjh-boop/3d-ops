"use strict";
// 上架导出模块：导出上架表格页（选产品、分组、导出 Lazada / Shopee 表格、上架批次和状态）。v2.31 从 app.js 搬过来。
// 和 app.js 共用的：PRODUCT_LIST（产品列表）、lstBadge / LST_*（上架状态小标签，产品库也用）、api / esc / toast 等工具函数。
// v2.43：上架工作台——一次看一个平台；流程条（待完善 → 可上架 → 审核中 → 已上线，问题单独一组）点哪段筛哪段；
// 左边分组；表格分页；点「⚠ 缺 N 项」原地展开缺什么、能修的直接修；勾选后底部出现操作条，按当前阶段给该用的按钮。
// 平台、状态、分组的值还放在隐藏的 #exp-plat / #exp-status / #exp-group 里（导出、标状态的老代码在用）。
async function loadExport() {
  await loadCats();
  const nf = new Set(CATS.map((c) => c.template)).size;
  $("#exp-tplinfo").textContent = CATS.length ? `${CATS.length} 个类目 · ${nf} 个模板文件` : "还没有模板";
  const [list, g] = await Promise.all([api("/api/products"), api("/api/groups").catch(() => ({ groups: [] }))]);
  PRODUCT_LIST = list; EXP_GROUPS = g.groups || [];
  const ids = new Set(list.map((p) => p.id));
  [...EXP_SEL].forEach((x) => { if (!ids.has(x)) EXP_SEL.delete(x); });
  $("#exp-addgroup").innerHTML = '<option value="">（选分组）</option>' + EXP_GROUPS.map((x) => `<option value="${x.id}" data-notr>${esc(x.name)}</option>`).join("");
  $("#exp-group").innerHTML = '<option value="">全部</option><option value="none">未分组</option>' + EXP_GROUPS.map((x) => `<option value="${x.id}">${x.id}</option>`).join("");
  $("#exp-group").value = LW.group;
  renderExpList();
  loadBatches();
}
let EXP_GROUPS = [];
const EXP_SEL = new Set();
const LW = { plat: "lazada", stage: "", group: "", page: 1, open: new Set(), view: "main", autoStage: "" };
const LW_STAGES = [["todo", "待完善", "资料还没补齐（红色项）"], ["ready", "可上架", "检查通过、还没上到平台"], ["review", "审核中", "已推送 / 已上传，平台在审核"], ["live", "已上线", "平台审核通过、在售"]];
const LW_ISSUES = [["rejected", "审核不通过"], ["failed", "上传失败"], ["update", "有修改待同步"], ["inactive", "平台已下架"], ["pending", "表格待上传"]];
const lwSt = (p) => ((LW.plat === "shopee" ? p.sp : p.lz) || {}).status || "none";
const lwErr = (p) => (LW.plat === "shopee" ? p.sp_errors : p.errors) || 0;
function stageOf(p) {
  const st = lwSt(p);
  if (st === "uploaded") return "review";
  if (st === "live") return "live";
  if (st === "none") return lwErr(p) ? "todo" : "ready";
  return st;                       // rejected / failed / update / inactive / pending
}
function lwBase() {
  // 分组 + 搜索（不含阶段）：流程条的数字按这个算
  const q = $("#exp-q").value.trim().toLowerCase();
  return PRODUCT_LIST.filter((p) => {
    if (LW.group === "none" && (p.groups || []).length) return false;
    if (LW.group && LW.group !== "none" && !(p.groups || []).map(String).includes(LW.group)) return false;
    if (q && !`${p.id} ${p.name_zh} ${p.category} ${p.category_th} ${(p.skus || []).join(" ")}`.toLowerCase().includes(q)) return false;
    return true;
  });
}
function expFiltered() {
  let rows = lwBase();
  if (LW.stage === "issues") rows = rows.filter((p) => LW_ISSUES.some(([k]) => stageOf(p) === k));
  else if (LW.stage) rows = rows.filter((p) => stageOf(p) === LW.stage);
  const by = $("#exp-sort").value;
  const key = {
    id: (p) => p.id, id_desc: (p) => p.id, name: (p) => p.name_zh || "", cat: (p) => (p.category || "") + p.id,
    status: (p) => LST_RANK[lwSt(p)] + p.id, updated: (p) => -(p.updated_at || 0),
  }[by] || ((p) => p.id);
  rows = rows.sort((a, b) => { const x = key(a), y = key(b); return x < y ? -1 : x > y ? 1 : 0; });
  if (by === "id_desc") rows.reverse();
  return rows;
}
function renderFlow(base) {
  const cnt = {};
  base.forEach((p) => { const s = stageOf(p); cnt[s] = (cnt[s] || 0) + 1; });
  const chip = (k, zh, tip, cls = "") => `<button class="lw-chip ${cls} ${LW.stage === k ? "on" : ""}" data-stage="${k}" title="${tip || ""}"><span>${zh}</span> <b>${cnt[k] || 0}</b></button>`;
  const issues = LW_ISSUES.filter(([k]) => cnt[k]).map(([k, zh]) => chip(k, zh, "", "warn"));
  $("#lw-flow").innerHTML = `<button class="lw-chip ${LW.stage === "" ? "on" : ""}" data-stage=""><span>全部</span> <b>${base.length}</b></button><span class="lw-arrow">｜</span>` +
    LW_STAGES.map(([k, zh, tip]) => chip(k, zh, tip)).join('<span class="lw-arrow">→</span>') +
    (issues.length ? `<span class="lw-arrow">｜</span><span class="small muted">需处理</span> ${issues.join("")}` : "") +
    (LW.plat === "lazada" ? '<span class="lw-flow-r"><button class="mini" id="lw-qc" title="接口推送过的产品，向 Lazada 查审核结果（平时每 30 分钟自动查一次）">🔄 同步 Lazada 审核状态</button></span>' : "");
}
function renderGroupsLW() {
  const all = PRODUCT_LIST.length, none = PRODUCT_LIST.filter((p) => !(p.groups || []).length).length;
  const g = (id, name, n) => `<div class="grp ${LW.group === id && !LW.autoStage ? "on" : ""}" data-g="${id}"><span data-notr>${esc(name)}</span> <span class="muted">${n}</span></div>`;
  // v2.44.1：按状态自动分组（推送、平台审核结果回来后自动换组，不用手动挪）
  const cnt = {};
  PRODUCT_LIST.forEach((p) => { const k = stageOf(p); cnt[k] = (cnt[k] || 0) + 1; });
  const issues = LW_ISSUES.reduce((a, [k]) => a + (cnt[k] || 0), 0);
  const a = (k, zh, n) => `<div class="grp ${LW.autoStage === k ? "on" : ""}" data-auto="${k}"><span>${zh}</span> <span class="muted">${n}</span></div>`;
  $("#lw-grp").innerHTML = `<div class="small muted lw-grp-h">按状态（自动）</div>` +
    LW_STAGES.map(([k, zh]) => a(k, zh, cnt[k] || 0)).join("") + a("issues", "需处理", issues) +
    `<div class="small muted lw-grp-h">我的分组</div>` + g("", "全部产品", all) + g("none", "未分组", none) + EXP_GROUPS.map((x) => g(String(x.id), x.name, x.count)).join("");
}
function renderExpList() {
  $("#exp-plat").value = LW.plat;
  $$("#lw-plat button").forEach((b) => b.classList.toggle("on", b.dataset.plat === LW.plat));
  renderGroupsLW();
  const base = lwBase();
  renderFlow(base);
  const rows = expFiltered();
  const size = +$("#lw-psize").value || 50, pages = Math.max(1, Math.ceil(rows.length / size));
  LW.page = Math.min(Math.max(1, LW.page), pages);
  const shown = rows.slice((LW.page - 1) * size, LW.page * size);
  $("#exp-sum").textContent = `${rows.length} 个产品`;
  const gname = Object.fromEntries(EXP_GROUPS.map((x) => [x.id, x.name]));
  const row = (p) => {
    const e = lwErr(p), w = (LW.plat === "shopee" ? p.sp_warnings : p.warnings) || 0, st = (LW.plat === "shopee" ? p.sp : p.lz) || {};
    const chk = e ? `<button class="lw-iss-btn bad" data-iss="${esc(p.id)}">⚠ 缺 ${e} 项 ▾</button>` :
      `<button class="lw-iss-btn ok" data-iss="${esc(p.id)}">✓ 可上架${w ? ` · ${w} 条提醒` : ""} ▾</button>`;
    return `<tr class="${EXP_SEL.has(p.id) ? "sel" : ""}" data-pid="${esc(p.id)}"><td><input type="checkbox" class="exp-p" value="${esc(p.id)}" ${EXP_SEL.has(p.id) ? "checked" : ""}></td>
      <td>${p.thumb ? `<img class="thumb" src="${esc(p.thumb)}" alt="" loading="lazy">` : ""}</td>
      <td class="mono nowrap" data-notr><span data-p360="${esc(p.id)}">${esc(p.id)}</span>${p.exported ? " 🔒" : ""}</td>
      <td class="lib-name"><span data-notr>${esc(p.name_zh)}</span>${p.active === false ? ' <span class="pill bad-pill">已下架</span>' : ""}
        <div class="small">${(p.groups || []).map((g) => gname[g] ? `<span class="pill tag-pill" data-notr>${esc(gname[g])}</span>` : "").join(" ")}</div></td>
      <td class="small">${p.category ? `<span data-notr>${esc(LANG === "th" ? p.category_th || p.category : p.category)}</span>` : '<span class="bad">未选类目</span>'}</td>
      <td class="small nowrap">${(p.skus || []).length} SKU</td>
      <td>${chk}</td>
      <td class="nowrap">${lstBadge(st, LW.plat)}${LW.plat === "lazada" && p.lz_item ? ' <span class="small muted" title="用接口推送的">⚡</span>' : ""}${st.note ? `<div class="small muted clamp2" data-notr title="${esc(st.note)}">${esc(st.note)}</div>` : ""}</td>
      <td><button class="mini" data-edit="${esc(p.id)}">编辑</button></td></tr>` +
      (LW.open.has(p.id) ? `<tr class="lw-iss-row"><td></td><td colspan="8"><div class="lw-iss" data-for="${esc(p.id)}">…</div></td></tr>` : "");
  };
  if (!rows.length) {
    $("#exp-products").innerHTML = `<p class="muted">${LW.stage ? "这一段没有产品" : "没有符合条件的产品"}</p>`;
  } else {
    $("#exp-products").innerHTML = `<table class="grid lw-table"><thead><tr><th><input type="checkbox" data-secall="page" title="勾选这一页"></th><th></th><th>编码</th><th>名称 / 分组</th><th>类目</th><th>SKU</th><th>检查</th><th>${LW.plat === "shopee" ? "Shopee" : "Lazada"} 状态</th><th></th></tr></thead>
      <tbody>${shown.map(row).join("")}</tbody></table>`;
    LW.open.forEach((pid) => { if (shown.some((p) => p.id === pid)) loadIssues(pid); });
  }
  $("#lw-pager").innerHTML = pages > 1 ? `<button class="mini" data-pg="${LW.page - 1}" ${LW.page <= 1 ? "disabled" : ""}>上一页</button><span>${LW.page} / ${pages}</span>
    <button class="mini" data-pg="${LW.page + 1}" ${LW.page >= pages ? "disabled" : ""}>下一页</button>` : "";
  updExpN();
}
function updExpN() {
  $("#exp-n").textContent = EXP_SEL.size;
  $("#lw-bar").classList.toggle("hidden", !EXP_SEL.size);
  const n = expFiltered().length;
  $("#lw-selall").textContent = `勾选全部 ${n} 个`;
  $("#lw-selall").classList.toggle("hidden", n <= EXP_SEL.size);
  $("#lw-ungroup").classList.toggle("hidden", !LW.group || LW.group === "none");
  renderActs();
}
function renderActs() {
  // 按选中产品所在的阶段给按钮（选了好几段时都给）
  const sel = PRODUCT_LIST.filter((p) => EXP_SEL.has(p.id));
  const has = (...ks) => sel.some((p) => ks.includes(stageOf(p)));
  const lz = LW.plat === "lazada", b = [];
  if (has("todo", "rejected", "failed")) b.push('<button class="primary mini" data-act="aifill" title="AI 选类目、填类目属性、补空着的文案（后台做，任务中心看进度）">✨ AI 补齐资料</button>');
  if (lz && has("ready", "todo", "failed", "rejected")) b.push('<button class="primary mini" data-act="push">⚡ 推送到 Lazada</button>');
  if (lz && has("live", "update", "review", "inactive")) b.push('<button class="mini primary-lite" data-act="push" title="把 ERP 里改过的标题、详情、属性、图片、价格、库存更新到 Lazada">⚡ 更新到 Lazada</button>');
  if (lz && has("review")) b.push('<button class="mini" data-act="qc">🔄 查审核结果</button>');
  if (!lz && has("ready", "todo", "failed", "rejected", "update")) b.push('<button class="primary mini" data-act="xls-sp" title="Shopee 还没有接口：生成表格到 Shopee 卖家中心批量上传">生成 Shopee 导入表格</button>');
  if (has("pending")) b.push('<span class="small muted">表格待上传：到平台上传后在「更多」里标状态</span>');
  $("#lw-acts").innerHTML = b.join(" ");
}
async function loadIssues(pid) {
  const box = $(`.lw-iss[data-for="${CSS.escape(pid)}"]`); if (!box) return;
  let r;
  try { r = await api(`/api/listing/issues/${encodeURIComponent(pid)}?platform=${LW.plat}`); } catch (e) { box.innerHTML = `<span class="bad">${esc(e.message)}</span>`; return; }
  const btn = (x) => ({
    ai: `<button class="mini" data-fix="ai" data-pid="${esc(pid)}">✨ AI 补</button>`,
    confirm_cat: `<button class="mini" data-fix="confirm_cat" data-pid="${esc(pid)}">✓ 确认类目「<span data-notr>${esc(r.category)}</span>」</button>`,
    confirm_attr: "", confirm_pkg: `<button class="mini" data-fix="confirm_pkg" data-pid="${esc(pid)}">✓ 尺寸没问题（${esc(r.package.length)}×${esc(r.package.width)}×${esc(r.package.height)} cm）</button>`,
    edit: `<button class="mini" data-edit="${esc(pid)}">去编辑</button>`,
    host: `<button class="mini" data-host="${esc(pid)}" title="导出表格才需要；推送到 Lazada 不用">⬆ 上传图床</button>`,
  })[x.fix] || "";
  const attrs = r.check_attrs.length ? `<div class="lw-attrs"><b>AI 填的属性，看一眼对不对：</b> ${r.check_attrs.map((a) => `<span class="pill" data-notr>${esc(a.label)}：${esc(a.value)}</span>`).join(" ")}
      <button class="mini" data-fix="confirm_attr" data-pid="${esc(pid)}">✓ 全部没问题</button> <button class="mini" data-edit="${esc(pid)}">有不对的，去改</button></div>` : "";
  const errs = r.errors.filter((x) => x.fix !== "confirm_attr");
  box.innerHTML = (errs.length ? `<ul class="lw-iss-list">${errs.map((x) => `<li class="bad"><span>${esc(x.text)}</span> ${btn(x)}</li>`).join("")}</ul>` : "") + attrs +
    (r.warnings.length ? `<details class="small"><summary class="muted">${r.warnings.length} 条提醒（不影响上架）</summary><ul class="lw-iss-list">${r.warnings.map((x) => `<li class="warn"><span>${esc(x.text)}</span> ${["ai", "host"].includes(x.fix) ? btn(x) : ""}</li>`).join("")}</ul></details>` : "") +
    (!r.errors.length && !r.warnings.length ? '<span class="ok small">全部检查通过</span>' : "");
}
async function aiFill(ids, el) {
  if (!ids.length) return;
  await busy(el, async () => {
    const r = await apiJob("/api/listing/ai-fill", { json: { product_ids: ids, platform: LW.plat } }, (s, j) => { if (j && j.stage) el.textContent = `✨ AI 补齐中 ${j.stage}`; });
    toast(`AI 补齐了 ${r.done.length} 个产品` + (r.failed.length ? `；${r.failed.length} 个失败：${r.failed[0].id} ${r.failed[0].error}` : ""), !!r.failed.length);
    await loadExport();
  });
}
async function qcSync(ids, el) {
  await busy(el, async () => {
    const r = await api("/api/listing/lazada/status-sync", { json: { product_ids: ids || null } });
    toast(`查了 ${r.checked} 个接口推送的产品，${r.changed.length} 个状态有变化` + (r.failed.length ? `；${r.failed.length} 个没查到` : ""), !!r.failed.length);
    await loadExport();
  });
}
$("#lw-plat").addEventListener("click", (e) => { const b = e.target.closest("[data-plat]"); if (!b) return; LW.plat = b.dataset.plat; LW.stage = ""; LW.page = 1; renderExpList(); });
$("#lw-view").addEventListener("click", (e) => {
  const b = e.target.closest("[data-view]"); if (!b) return;
  LW.view = b.dataset.view;
  $$("#lw-view button").forEach((x) => x.classList.toggle("on", x === b));
  $("#lw-main").classList.toggle("hidden", LW.view !== "main");
  $("#lw-batches").classList.toggle("hidden", LW.view !== "batches");
  $("#lw-stock").classList.toggle("hidden", LW.view !== "stock");
  if (LW.view === "batches") loadBatches();
  if (LW.view === "stock" && window.loadStockPending) loadStockPending();
});
$("#lw-flow").addEventListener("click", (e) => {
  if (e.target.closest("#lw-qc")) return qcSync(null, e.target.closest("#lw-qc"));
  const b = e.target.closest("[data-stage]"); if (!b) return;
  LW.stage = b.dataset.stage; LW.autoStage = ""; LW.page = 1; renderExpList();
});
$("#lw-grp").addEventListener("click", (e) => {
  const au = e.target.closest("[data-auto]");
  if (au) { LW.autoStage = au.dataset.auto; LW.stage = au.dataset.auto; LW.group = ""; LW.page = 1; return renderExpList(); }
  const d = e.target.closest("[data-g]"); if (!d) return;
  LW.autoStage = ""; LW.group = d.dataset.g; $("#exp-group").value = LW.group; LW.page = 1; renderExpList();
});
$("#lw-pager").addEventListener("click", (e) => { const b = e.target.closest("[data-pg]"); if (!b) return; LW.page = +b.dataset.pg; renderExpList(); });
["#exp-sort", "#lw-psize"].forEach((k) => $(k).addEventListener("change", () => { LW.page = 1; renderExpList(); }));
{ let t = null; $("#exp-q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { LW.page = 1; renderExpList(); }, 250); }); }
$("#exp-products").addEventListener("change", (e) => {
  const t = e.target;
  if (t.classList.contains("exp-p")) { t.checked ? EXP_SEL.add(t.value) : EXP_SEL.delete(t.value); t.closest("tr").classList.toggle("sel", t.checked); updExpN(); return; }
  if (t.dataset.secall) {
    $$("#exp-products .exp-p").forEach((c) => { c.checked = t.checked; t.checked ? EXP_SEL.add(c.value) : EXP_SEL.delete(c.value); c.closest("tr").classList.toggle("sel", t.checked); });
    updExpN();
  }
});
$("#exp-products").addEventListener("click", async (e) => {
  const t = e.target.closest("button"); if (!t) return;
  if (t.dataset.iss) { const id = t.dataset.iss; LW.open.has(id) ? LW.open.delete(id) : LW.open.add(id); return renderExpList(); }
  if (t.dataset.edit) return openProduct(t.dataset.edit, true);
  if (t.dataset.fix === "ai") return aiFill([t.dataset.pid], t);
  if (t.dataset.host) {
    return busy(t, async () => {
      const r = await apiJob(`/api/products/${encodeURIComponent(t.dataset.host)}/images/host`, { method: "POST" }, (s, j) => { if (j && j.stage) t.textContent = `上传中 ${j.stage}`; });
      toast(`已上传 ${r.uploaded} 张到图床` + ((r.failed || []).length ? `；${r.failed.length} 张失败：${r.failed[0]}` : ""), !!(r.failed || []).length);
      await loadExport();
    });
  }
  if (t.dataset.fix) {
    try { await api(`/api/listing/fix/${encodeURIComponent(t.dataset.pid)}`, { json: { action: t.dataset.fix, platform: LW.plat } }); toast("已确认"); await loadExport(); }
    catch (err) { toast(err.message, true); }
  }
});
$("#lw-selall").addEventListener("click", () => { expFiltered().forEach((p) => EXP_SEL.add(p.id)); renderExpList(); });
$("#lw-clear").addEventListener("click", () => { EXP_SEL.clear(); renderExpList(); });
$("#lw-acts").addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]"); if (!b) return;
  const ids = [...EXP_SEL];
  if (b.dataset.act === "aifill") return aiFill(ids, b);
  if (b.dataset.act === "push") return lzPush(b);
  if (b.dataset.act === "qc") return qcSync(ids, b);
  if (b.dataset.act === "xls-sp") return $("#btn-export-sp").click();
});
$("#exp-newgroup").addEventListener("click", async () => {
  const n = prompt("新分组名称（例如：猫咪系列、10 月第 1 批、节日礼物）"); if (!n) return;
  try { await api("/api/groups", { json: { name: n } }); await loadExport(); toast("已新建分组"); } catch (err) { toast(err.message, true); }
});
$("#exp-addgroup").addEventListener("change", async (e) => {
  const g = e.target.value; if (!g || !EXP_SEL.size) return;
  if (!confirm(`把已选的 ${EXP_SEL.size} 个产品加入这个分组？`)) { e.target.value = ""; return; }
  await api("/api/groups/assign", { json: { ids: [...EXP_SEL], group: +g, add: true } });
  toast("已加入分组"); e.target.value = ""; loadExport();
});
$("#lw-ungroup").addEventListener("click", async () => {
  if (!LW.group || LW.group === "none" || !EXP_SEL.size) return;
  if (!confirm(`把已选的 ${EXP_SEL.size} 个产品移出当前分组？`)) return;
  await api("/api/groups/assign", { json: { ids: [...EXP_SEL], group: +LW.group, add: false } });
  toast("已移出分组"); loadExport();
});
$$(".exp-actions [data-mark]").forEach((b) => b.addEventListener("click", async () => {
  if (!EXP_SEL.size) return toast("先勾选产品", true);
  const plat = LW.plat, st = b.dataset.mark;
  let note = null;
  if (st === "failed") { note = prompt("失败原因（可空），例如：类目属性缺失、图片不合格、价格被拦截"); if (note === null) return; }
  if (st === "rejected") { note = prompt("平台给的不通过原因（可空），例如：图片有水印、类目错误、违禁词"); if (note === null) return; }
  await api("/api/listing/status", { json: { ids: [...EXP_SEL], platform: plat, status: st, note } });
  toast(`已把 ${EXP_SEL.size} 个产品的 ${plat === "shopee" ? "Shopee" : "Lazada"} 状态改成「${LST_ZH[st]}」`);
  loadExport();
}));
async function loadBatches() {
  const r = await api(`/api/listing/batches?platform=${$("#bt-plat").value}`);
  $("#exp-batches").innerHTML = r.batches.map((b) => {
    const c = b.counts;
    // v2.41 复审：挪到别的批次的产品不算在这一批里（不然这一批永远不会「完成」）
    const done = (c.live || 0) + (c.inactive || 0) + (c.moved || 0) === b.items.length && b.items.length > (c.moved || 0);
    return `<details class="batch ${done ? "batch-done" : ""}" data-bid="${b.id}"><summary>
        <span class="pill ${b.platform === "shopee" ? "plat-shopee" : "plat-lazada"}">${b.platform === "shopee" ? "Shopee" : "Lazada"}</span>
        <b data-notr>${esc(b.name)}</b> <span class="muted small">${fmtTime(b.created_at)} · ${b.items.length} 个产品 · <span data-notr>${esc(b.username || "")}</span></span>
        <span class="small">${["pending", "failed", "uploaded", "rejected", "live", "inactive", "update"].filter((k) => c[k]).map((k) => `<span class="lst lst-${k}">${LST_ZH[k]} ${c[k]}</span>`).join("")}${c.moved ? `<span class="lst lst-none" title="后来在别的批次重新导出了"><span>移到别的批次</span> ${c.moved}</span>` : ""}</span></summary>
      <div class="batch-body">
        <div class="row gap wrap">${b.files.map((f) => `<a class="btn mini-btn" href="/api/export/${encodeURIComponent(f.file)}">⬇ ${esc(f.file)}</a>`).join("")}</div>
        <div class="row gap wrap" style="margin:8px 0">${c.pending ? '<button class="primary mini" data-bt="ok">⬆ 整批上传成功（待上传的改成「平台审核中」）</button>' : ""}
          ${c.pending || c.uploaded ? '<button class="primary mini" data-bt="live">✔ 整批审核通过（改成「已上线」）</button>' : ""}
          <button class="mini" data-bt="rename">改名</button><button class="mini danger" data-bt="del">删除批次记录</button></div>
        <table class="grid small"><tbody>${b.items.map((i) => `<tr><td class="mono" data-notr>${esc(i.id)}</td><td data-notr>${esc(i.name)}</td>
          <td>${lstBadge(i, b.platform)}${i.other_batch ? ' <span class="muted">（已在其他批次重新导出）</span>' : ""}${i.note ? ` <span class="muted" data-notr>${esc(i.note)}</span>` : ""}</td>
          <td class="nowrap">${i.other_batch ? "" : `<button class="mini" data-bti="uploaded" data-pid="${esc(i.id)}">审核中</button><button class="mini" data-bti="live" data-pid="${esc(i.id)}">✔ 上线</button><button class="mini" data-bti="rejected" data-pid="${esc(i.id)}">✗ 不通过</button><button class="mini" data-bti="failed" data-pid="${esc(i.id)}">上传失败</button>`}</td></tr>`).join("")}</tbody></table>
      </div></details>`;
  }).join("") || '<p class="muted small">还没有批次。导出表格后会自动生成。</p>';
}
$("#bt-plat").addEventListener("change", loadBatches);
$("#exp-batches").addEventListener("click", async (e) => {
  const t = e.target, box = t.closest("[data-bid]"); if (!box) return;
  const bid = box.dataset.bid;
  const plat = box.querySelector(".plat-shopee") ? "shopee" : "lazada";
  try {
    if (t.dataset.bt === "ok") { const r = await api(`/api/listing/batches/${bid}`, { json: { status: "uploaded" } }); toast(`${r.changed} 个产品已标记为「平台审核中」`); return loadExport(); }
    if (t.dataset.bt === "live") { const r = await api(`/api/listing/batches/${bid}`, { json: { status: "live" } }); toast(`${r.changed} 个产品已标记为「已上线」`); return loadExport(); }
    if (t.dataset.bt === "rename") { const n = prompt("批次名称"); if (!n) return; await api(`/api/listing/batches/${bid}`, { json: { name: n } }); return loadBatches(); }
    if (t.dataset.bt === "del") { if (!confirm("只删除这条批次记录（产品状态和导出的文件都不变）。继续？")) return; await api(`/api/listing/batches/${bid}`, { method: "DELETE" }); return loadBatches(); }
    if (t.dataset.bti) {
      let note = null;
      if (t.dataset.bti === "failed") { note = prompt("失败原因（可空）"); if (note === null) return; }
      if (t.dataset.bti === "rejected") { note = prompt("平台给的不通过原因（可空）"); if (note === null) return; }
      await api("/api/listing/status", { json: { ids: [t.dataset.pid], platform: plat, status: t.dataset.bti, note } });
      const open = [...$$("#exp-batches details[open]")].map((d) => d.dataset.bid);
      await loadExport();
      open.forEach((id) => { const d = $(`#exp-batches [data-bid="${id}"]`); if (d) d.open = true; });
    }
  } catch (err) { toast(err.message, true); }
});

async function doExport(e, url, note) {
  const ids = [...EXP_SEL];
  if (!ids.length) return toast("先勾选要导出的产品", true);
  const platform = url.includes("shopee") ? "shopee" : "lazada";
  const up = PRODUCT_LIST.filter((p) => ids.includes(p.id) && ["uploaded", "live", "rejected", "inactive"].includes(((platform === "shopee" ? p.sp : p.lz) || {}).status));
  if (up.length && !confirm(`其中 ${up.length} 个产品在 ${platform === "shopee" ? "Shopee" : "Lazada"} 上已经有了（${up.slice(0, 6).map((p) => p.id).join("、")}${up.length > 6 ? "…" : ""}）。\n再导出新建会生成重复商品（平台不允许重复铺货）。审核不通过的请在平台后台修改后重新提交。确定继续？`)) return;
  // 按分组分别导出：每个分组一个批次
  const parts = [];
  if ($("#exp-split").checked) {
    const gname = Object.fromEntries(EXP_GROUPS.map((x) => [String(x.id), x.name]));
    const by = {};
    ids.forEach((id) => { const p = PRODUCT_LIST.find((x) => x.id === id); const g = ((p && p.groups) || []).map(String).find((x) => gname[x]) || ""; (by[g] = by[g] || []).push(id); });
    Object.entries(by).forEach(([g, list]) => parts.push({ ids: list, name: `${$("#exp-batch").value.trim() || (platform === "shopee" ? "Shopee" : "Lazada")} · ${g ? gname[g] : "未分组"}`, group: g }));
  } else parts.push({ ids, name: $("#exp-batch").value.trim(), group: $("#exp-addgroup").value });
  await busy(e.target, async () => {
    const list = (arr, cls) => arr.length ? `<ul class="msgs">${arr.map((m) => `<li class="${cls}">${esc(m)}</li>`).join("")}</ul>` : "";
    let html = "";
    for (const part of parts) {
      const r = await api(url, { json: { product_ids: part.ids, force: $("#exp-force").checked, batch_name: part.name, group_id: part.group || "" } });
      html += (r.ok
        ? `<p class="ok">✅ ${r.batch ? `批次「<span data-notr>${esc(r.batch.name)}</span>」：` : ""}已生成 ${r.rows} 行（一行一个 SKU），${r.batch && r.batch.items ? r.batch.items.length : part.ids.length} 个产品已改成「待上传」：</p><ul>${r.files.map((f) =>
            `<li><a href="/api/export/${encodeURIComponent(f.file)}">下载 ${esc(f.file)}</a> <span class="muted small">${f.rows} 行 · ${f.categories.map(esc).join("、")}</span></li>`).join("")}</ul>`
        : `<p class="bad">${parts.length > 1 ? `「<span data-notr>${esc(part.name)}</span>」` : ""}有红色项未处理，没有生成文件：</p>`) + list(r.errors, "bad") + list(r.warnings, "warn");
    }
    $("#exp-result").innerHTML = html + `<p class="muted small">${note}上传成功后，到「批次记录」里点「整批上传成功」。</p>`;
    EXP_SEL.clear();
    await loadExport();
  });
}
$("#btn-export").addEventListener("click", (e) => doExport(e, "/api/export", "Lazada 卖家中心 → 批量管理 → 逐个上传这些文件。导出后这些产品的 SKU 已锁定。"));
$("#btn-export-sp").addEventListener("click", (e) => doExport(e, "/api/export/shopee", "Shopee 卖家中心 → 我的产品 → 批量功能 → 批量上传 → 上传文件。上传后 Shopee 可能要求补充品牌等属性（在 Shopee 后台补）。"));
// v2.41.2：直接推送到 Lazada（接口）：平台上还没有就新建，推过的就更新。v2.43：后台跑，任务中心看进度
async function lzPush(el) {
  const ids = [...EXP_SEL];
  if (!ids.length) return toast("先勾选要推送的产品", true);
  const xls = PRODUCT_LIST.filter((p) => ids.includes(p.id) && ["uploaded", "live", "rejected", "inactive"].includes((p.lz || {}).status) && !p.lz_item);
  if (xls.length && !confirm(`其中 ${xls.length} 个产品已经用表格传到 Lazada 了（${xls.slice(0, 6).map((p) => p.id).join("、")}${xls.length > 6 ? "…" : ""}）。\n再推送会新建一个重复的商品。确定继续？`)) return;
  if (!confirm(`把 ${ids.length} 个产品推送到 Lazada？平台上还没有的会新建，推送过的会更新（标题、详情、属性、图片、价格、库存）。`)) return;
  await busy(el, async () => {
    const list = (arr, cls) => arr.length ? `<ul class="msgs">${arr.map((m) => `<li class="${cls}">${esc(m)}</li>`).join("")}</ul>` : "";
    const label = el.textContent;
    const r = await apiJob("/api/listing/lazada/push", { json: { product_ids: ids, force: $("#exp-force").checked } },
      (s, j) => { if (j && j.stage) el.textContent = `⚡ 推送中 ${j.stage}`; });
    el.textContent = label;
    let html = "";
    if (r.errors.length && !r.ok.length && !r.failed.length) html = `<p class="bad">有红色项未处理，没有推送（点产品的「⚠ 缺 N 项」看缺什么）：</p>`;
    if (r.ok.length) html += `<p class="ok">✅ 已推送 ${r.ok.length} 个产品（新建 ${r.ok.filter((x) => x.created).length}，更新 ${r.ok.filter((x) => !x.created).length}），状态改成「平台审核中」。审核结果每 30 分钟自动同步。</p>`;
    if (r.failed.length) html += `<p class="bad">${r.failed.length} 个推送失败（勾选后可以再推一次；原因看不懂就把「下载推送内容」的文件发给开发者）：</p>` +
      `<ul class="msgs">${r.failed.map((x) => `<li class="bad"><span data-notr>${esc(x.id)}：${esc(x.error)}</span> <a class="small" href="/api/listing/lazada/last/${encodeURIComponent(x.id)}">下载推送内容</a></li>`).join("")}</ul>`;
    $("#exp-result").innerHTML = html + list(r.errors, "bad") + list(r.warnings, "warn");
    EXP_SEL.clear();
    r.failed.forEach((x) => EXP_SEL.add(x.id));           // 失败的留着勾选，改好直接再推
    await loadExport();
  });
}
