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
  await loadWB();
  renderExpList();
  loadBatches();
}
let EXP_GROUPS = [];
const EXP_SEL = new Set();
const LW = { plat: "lazada", stage: "", group: "", page: 1, open: new Set(), view: "main", autoStage: "", shop: 0, sel: {}, vid: 0 };
let WB = { gk: {}, marks: {}, n: {}, shops: [], views: [], total: 0 };      // v2.53 上架工作台的自动分类（服务器按平台 + 店铺现算）
async function loadWB() {
  try { WB = await api(`/api/listing/wb?platform=${LW.plat}&shop=${LW.shop}`); } catch (e) { toast(e.message, true); }
}
const wbOf = (p) => ({ gk: WB.gk[p.id] || [] });
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
  // 自动分类 + 搜索
  const q = $("#exp-q").value.trim().toLowerCase();
  return PRODUCT_LIST.filter((p) => {
    if (!GRP.match(wbOf(p), LW.sel)) return false;
    if (q && !`${p.id} ${p.name_zh} ${p.category} ${p.category_th} ${(p.skus || []).join(" ")}`.toLowerCase().includes(q)) return false;
    return true;
  });
}
function expFiltered() {
  let rows = lwBase();
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
  $("#lw-flow").innerHTML = LW.plat === "lazada" ? '<span class="lw-flow-r"><button class="mini" id="lw-qc" title="接口推送过的产品，向 Lazada 查审核结果（平时每 30 分钟自动查一次）">🔄 同步 Lazada 审核状态</button></span>' : "";
}
const WB_PG = [["none", "未上架", ""], ["todo", "资料不全", "bad"], ["ready", "可推送", "ok"], ["pushing", "推送中", ""], ["review", "审核中", ""], ["rejected", "被拒", "bad"], ["live", "在售", "ok"], ["down", "已下架", ""]];
const WB_TD = [["rejected", "被拒（带原因）"], ["noattr", "类目属性没填"], ["badimg", "图片不合规（没有白底图）"], ["longtitle", "标题太长"], ["belowcost", "售价低于成本"], ["mismatch", "平台价格或库存和系统对不上"], ["nostock", "在售但没库存"]];
const WB_SL = [["hot", "热销"], ["slow", "滞销"], ["new", "新上架"], ["lowmargin", "利润低"]];
function renderGroupsLW() {
  const n = WB.n || {}, one = (arr, p, tone) => arr.map(([k, zh, t]) => ({ key: p + k, label: zh, n: n[p + k] || 0, tone: n[p + k] ? (tone || t || "") : "" }));
  const spec = {
    sel: LW.sel, views: WB.views, viewOn: LW.vid,
    top: [{ key: "", label: "全部", n: WB.total || 0 }, { key: "pg:ready", label: "可推送", n: n["pg:ready"] || 0, tone: "ok" }, { key: "pg:live", label: "在售", n: n["pg:live"] || 0, tone: "ok" }, { key: "opp:1", label: "铺货机会", n: n["opp:1"] || 0, tone: "warn" }],
    sections: [
      { id: "pg", title: "1. 进度", help: "按这个平台 / 店铺的状态自动归类，平台状态一变自动换组", items: one(WB_PG, "pg:") },
      { id: "td", title: "2. 待处理", help: "一个产品可以同时在几个里面；修好就自动离开", items: one(WB_TD, "td:", "warn") },
      { id: "sl", title: "3. 表现（这个店铺近 30 天）", help: "标准和产品库一样（产品库 → ⚙ 分组标准）", items: one(WB_SL, "sl:") },
      { id: "opp", title: "4. 铺货机会", help: "别的店铺卖得出去、这个店铺还没上。勾选后点「上到这个店铺」", items: [{ key: "opp:1", label: "别的店铺卖得好，这里还没上", n: n["opp:1"] || 0, tone: "warn" }] },
      { id: "mk", title: "5. 手动标记", help: "做完自动取消：要上架=上架后；要改价=价格改了后；要改图=图片换了后", items: [["list", "要上架"], ["price", "要改价"], ["img", "要改图"]].map(([k, zh]) => ({ key: "mk:" + k, label: zh, n: n["mk:" + k] || 0 })) },
    ],
    foot: '<a class="small" data-lw-gclear>清除选择</a> · <a class="small" data-lw-saveview>⭐ 保存为视图</a>',
  };
  const box = $("#lw-gp");
  box.innerHTML = GRP.html(spec);
  GRP.bind(box, spec, () => { LW.vid = 0; LW.page = 1; renderExpList(); });
  const sh = $("#lw-shop");
  sh.innerHTML = '<option value="0">全部店铺</option>' + (WB.shops || []).map((x) => `<option value="${x.id}" data-notr>${esc(x.name)}</option>`).join("");
  sh.value = String(LW.shop);
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
        <div class="small">${wbPills(p)} ${(p.groups || []).map((g) => gname[g] ? `<span class="pill tag-pill" data-notr>${esc(gname[g])}</span>` : "").join(" ")}</div></td>
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
  if (lz && LW.shop && sel.some((p) => (WB.gk[p.id] || []).includes("opp:1"))) b.push('<button class="primary mini" data-act="pushshop" title="别的店铺卖得好、这个店铺还没上的：用现有的推送流程上到这个店铺">⚡ 上到这个店铺</button>');
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
$("#lw-plat").addEventListener("click", (e) => { const b = e.target.closest("[data-plat]"); if (!b) return; LW.plat = b.dataset.plat; LW.stage = ""; LW.shop = 0; LW.sel = {}; LW.vid = 0; LW.page = 1; loadWB().then(renderExpList); });
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
$("#lw-shop").addEventListener("change", (e) => { LW.shop = +e.target.value || 0; LW.vid = 0; LW.sel = {}; LW.page = 1; loadWB().then(renderExpList); });
$("#lw-gp").addEventListener("click", async (e) => {
  const t = e.target;
  try {
    if (t.closest("[data-lw-gclear]")) { LW.sel = {}; LW.vid = 0; LW.page = 1; return renderExpList(); }
    if (t.closest("[data-lw-saveview]")) {
      const nm = prompt("视图名称（例如：这个店铺要推送的）"); if (!nm) return;
      const r = await api("/api/goods/views", { json: { name: nm, scope: "wb", state: { plat: LW.plat, shop: LW.shop, sel: { ...LW.sel }, q: $("#exp-q").value } } });
      WB.views = r.views; toast("已保存视图"); return renderExpList();
    }
    const vd = t.closest("[data-grp-vdel]");
    if (vd) { e.stopPropagation(); const r = await api(`/api/goods/views/${vd.dataset.grpVdel}?scope=wb`, { method: "DELETE" }); WB.views = r.views; if (LW.vid === +vd.dataset.grpVdel) LW.vid = 0; return renderExpList(); }
    const v = t.closest("[data-grp-view]");
    if (v) {
      const x = WB.views.find((y) => y.id === +v.dataset.grpView); if (!x) return;
      const st = x.state || {};
      LW.plat = st.plat || LW.plat; LW.shop = st.shop || 0; await loadWB(); LW.sel = { ...(st.sel || {}) }; LW.vid = x.id; $("#exp-q").value = st.q || ""; LW.page = 1;
      return renderExpList();
    }
  } catch (err) { toast(err.message, true); }
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
async function wbMark(mark, on) {
  if (!EXP_SEL.size) return toast("先勾选产品", true);
  let note = "";
  if (on) { note = prompt("备注（可以不填）", ""); if (note === null) return; }
  const r = await api("/api/goods/marks", { json: { ids: [...EXP_SEL], mark, on, note: on ? note : undefined, scope: "wb" } });
  toast(`${on ? "已标记" : "已取消标记"} ${r.changed} 个产品`); await loadExport();
}
const wbPills = (p) => {
  const k = ((WB.gk[p.id] || []).find((x) => x.startsWith("pg:")) || "").slice(3), it = WB_PG.find((x) => x[0] === k);
  const m = WB.marks[p.id] || {};
  return (it ? `<span class="pill ${it[2] === "ok" ? "ok-pill" : it[2] === "bad" ? "bad-pill" : "tag-pill"}">${it[1]}</span>` : "") +
    Object.keys(m).map((x) => ` <span class="pill warn-pill" ${m[x].note ? `title="${esc(m[x].note)}"` : ""}>${{ list: "要上架", price: "要改价", img: "要改图" }[x]}</span>`).join("") +
    ((WB.gk[p.id] || []).includes("opp:1") ? ' <span class="pill tag-pill">铺货机会</span>' : "");
};
$("#lw-mk").addEventListener("click", (e) => {
  const b = e.target.closest("[data-wbmk]"); if (!b) return;
  wbMark(b.dataset.wbmk === "off" ? "list" : b.dataset.wbmk, b.dataset.wbmk !== "off").then(async () => { if (b.dataset.wbmk === "off") { await wbMark("price", false); await wbMark("img", false); } }).catch((er) => toast(er.message, true));
});
$("#lw-acts").addEventListener("click", (e) => {
  const b = e.target.closest("[data-act]"); if (!b) return;
  const ids = [...EXP_SEL];
  if (b.dataset.act === "aifill") return aiFill(ids, b);
  if (b.dataset.act === "push") return lzPush(b);
  if (b.dataset.act === "pushshop") return lzPush(b, LW.shop);
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
async function lzPush(el, shopId) {
  const ids = [...EXP_SEL];
  if (!ids.length) return toast("先勾选要推送的产品", true);
  const xls = PRODUCT_LIST.filter((p) => ids.includes(p.id) && ["uploaded", "live", "rejected", "inactive"].includes((p.lz || {}).status) && !p.lz_item);
  if (xls.length && !confirm(`其中 ${xls.length} 个产品已经用表格传到 Lazada 了（${xls.slice(0, 6).map((p) => p.id).join("、")}${xls.length > 6 ? "…" : ""}）。\n再推送会新建一个重复的商品。确定继续？`)) return;
  if (!confirm(`把 ${ids.length} 个产品推送到 Lazada？平台上还没有的会新建，推送过的会更新（标题、详情、属性、图片、价格、库存）。`)) return;
  await busy(el, async () => {
    const list = (arr, cls) => arr.length ? `<ul class="msgs">${arr.map((m) => `<li class="${cls}">${esc(m)}</li>`).join("")}</ul>` : "";
    const label = el.textContent;
    const r = await apiJob("/api/listing/lazada/push", { json: { product_ids: ids, force: $("#exp-force").checked, shop_id: shopId || undefined } },
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
// v2.53：从上架工作台打开产品编辑，「← 返回」回到这里：平台、阶段、分组、第几页和离开时一样（搜索框等由 NAV 按 id 自动记）
if (window.NAV) {
  NAV.keep("export", {
    get: () => ({ plat: LW.plat, stage: LW.stage, group: LW.group, page: LW.page, view: LW.view, autoStage: LW.autoStage, shop: LW.shop, sel: { ...LW.sel }, vid: LW.vid }),
    set: (s) => { if (s) Object.assign(LW, s); },
  });
}
