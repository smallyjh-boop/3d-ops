"use strict";
// 商品模块：Lazada 类目与属性、Shopee 类目、检查、保存产品。v2.34 从 static/app.js 搬过来，代码没改。
// ---------------- 类目与属性 ----------------
async function loadCats() { CATS = await api("/api/categories"); }
function fillCatSelect(cur, known) {
  // v2.25：全部类目约 2900 个，用搜索框筛选（名称、泰文路径、类目ID）
  const q = (($("#cat-filter") || {}).value || "").trim().toLowerCase();
  const words = q.split(/\s+/).filter(Boolean);
  let list = CATS;
  if (words.length) list = CATS.filter((c) => { const t = `${catName(c)} ${c.path || ""} ${c.cat_id}`.toLowerCase(); return words.every((w) => t.includes(w)); });
  const found = list.length;
  // v2.36.1：只放前 600 个选项；当前类目排在 600 名之后（全部模板下载完约 2900 个）会被截掉，下拉框显示「未选择」→ 当前类目总是放进去
  list = list.slice(0, 600);
  const curCat = cur ? CATS.find((c) => c.id === cur) : null;
  if (curCat && !list.includes(curCat)) list = [curCat].concat(list);
  $("#cat-select").innerHTML = `<option value="">${words.length ? `— 找到 ${found} 个 —` : "— 未选择 —"}</option>` +
    list.map((c) => `<option value="${esc(c.id)}" ${c.id === cur ? "selected" : ""} title="${esc(c.path || "")}">${esc(catName(c))}（${esc(c.cat_id)}）${c.needs_license ? " ⚠需TISI许可证" : ""}</option>`).join("") +
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
  if (!CATS.length) info = '<span class="bad">还没有类目：在 设置 → AI 与对接 → 店铺对接 授权 Lazada 店铺（类目从接口拉），或者上传类目模板。</span>';
  else if (c.status === "manual") info = '<span class="st st-manual">手动选择</span>';
  else if (c.id) info = `<span class="st ${c.status === "check" ? "st-check" : "st-ai"}">AI 匹配 · 把握 ${Math.round((c.confidence || 0) * 100)}%</span>`;
  if (c.id && c.status === "check") info += ` <button class="mini" id="btn-cat-ok">✓ 确认类目</button>`;
  const reason = LANG === "th" ? (c.reason_th || "") : c.reason;
  if (reason) info += `<div data-notr>${esc(reason)}</div>`;
  if (c.suggest_id && !CATS.some((x) => x.cat_id === c.suggest_id)) {      // 没接 Lazada 接口时才会有（接了接口所有类目都能选）
    info += `<div class="warn">AI 建议的理想类目还没有模板：<b data-notr>${esc(LANG === "th" ? c.suggest_path : (c.suggest_path_zh || ""))}</b><br><span class="muted">${esc(c.suggest_path)}（类目ID ${esc(c.suggest_id)}）</span><br>全部类目模板下载完以后（进度在「导出上架表格」页）重新点 AI 匹配类目就行。</div>`;
  }
  // v2.45.1：推荐类目（Lazada 推荐 + AI 选的，都不要许可证），点「用这个」直接换
  const opts = (c.options || []).filter((o) => o.id !== c.id);
  if (opts.length) info += `<div class="cat-opts"><div class="small muted">也可以放这些类目（都不需要许可证）：</div>${opts.map((o) =>
    `<div class="row gap small"><button class="mini" data-catpick="${esc(o.id)}">用这个</button><span data-notr>${esc(o.path)}</span> <span class="muted">(${esc(o.cat_id)})</span></div>`).join("")}</div>`;
  $("#cat-info").innerHTML = info;
  FIELDS = null;
  if (c.id && known) {
    try {
      const cf = await api(`/api/category-fields?id=${encodeURIComponent(c.id)}`);
      FIELDS = cf.fields;
      // v2.45：属性来自哪里；要许可证的类目提醒
      $("#cat-info").insertAdjacentHTML("beforeend", (cf.source === "api" ? ' <span class="pill tag-pill" title="类目属性、选项、必填项是从 Lazada 接口拉的最新的">属性来自 Lazada 接口</span>' : "") +
        (cf.needs_license ? '<div class="bad small">⚠ 这个类目上架要 TISI 等许可证：没有许可证请换一个相近的类目（再点一次 AI 匹配会避开）</div>' : ""));
    } catch { FIELDS = null; }
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
      input = `<select data-attr="${esc(f.key)}" data-i18n-ok><option value="">（留空）</option>` +  // 选项是 Lazada 的泰文原值
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
      : ((P.category.options || []).length ? "AI 没把握，请从右边推荐的类目里选一个" : "没找到合适的类目，请在上面搜索类目手动选择"), !P.category.id);
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
// v2.45.1：推荐类目「用这个」
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-catpick]"); if (!b || !P) return;
  const sel = $("#cat-select");
  if (![...sel.options].some((o) => o.value === b.dataset.catpick)) {
    const c = CATS.find((x) => x.id === b.dataset.catpick);
    sel.insertAdjacentHTML("beforeend", `<option value="${esc(b.dataset.catpick)}">${esc(c ? catName(c) : b.dataset.catpick)}</option>`);
  }
  sel.value = b.dataset.catpick;
  sel.dispatchEvent(new Event("change"));
});
