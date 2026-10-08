"use strict";
// 商品模块：编辑产品（表单、关键词、规格与颜色、库存提示、价格、图片）。v2.34 从 static/app.js 搬过来，代码没改。
// 正在编辑的产品 P、dirty 等状态还在内核 app.js 开头（设置页、切换页面时也要用）。
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

// v2.35：包装纸箱（泰国邮政标准纸箱，core/inventory/boxes.py）。选了纸箱 → 包裹尺寸按纸箱填；没选时按包裹尺寸推荐一个
let PBOXES = [];
const pbTH = () => window.I18N && I18N.lang === "th";
(async () => {
  try { PBOXES = (await api("/api/pack-boxes")).boxes; } catch { PBOXES = []; }
  const sel = $("#pkg-boxsel"); if (!sel) return;
  sel.innerHTML = `<option value="">${pbTH() ? "ยังไม่ได้ตั้ง" : "没设"}</option>${PBOXES.map((b) => `<option value="${esc(b.code)}">${esc(pbTH() ? b.th : b.zh)}</option>`).join("")}` +
    `<option value="none">${pbTH() ? "ไม่ใช้กล่อง (ถุงไปรษณีย์ ฯลฯ)" : "不用纸箱（快递袋等）"}</option>`;
  if (P) renderPackage();
})();
function boxFit(pkg) {
  const need = [pkg && pkg.length, pkg && pkg.width, pkg && pkg.height].map(Number).sort((a, b) => a - b);
  if (need.some((x) => !(x > 0))) return "";
  const b = PBOXES.slice().sort((x, y) => x.vol - y.vol).find((x) => [x.w, x.l, x.h].sort((p, q) => p - q).every((v, i) => v >= need[i]));
  return b ? b.code : "";
}
function useBox(code) {
  const b = PBOXES.find((x) => x.code === code);
  P.pack_box = code;
  if (b) {
    P.package = { ...(P.package || {}), length: b.l, width: b.w, height: b.h };
    P.package_status = "manual";
    $$('#pkg-box [data-pkg]').forEach((el) => { const v = getPath(P, el.dataset.f); el.value = v == null ? "" : v; });
  }
  markDirty(); renderPackage();
}
$("#pkg-boxsel").addEventListener("input", (e) => { if (P && e.target.value && e.target.value !== "none") useBox(e.target.value); });
$("#pkg-box").addEventListener("click", (e) => { if (e.target.id === "pkg-boxuse" && P) { e.preventDefault(); useBox(e.target.dataset.code); } });
function renderPackage() {
  const sel = $("#pkg-boxsel");
  if (sel && PBOXES.length && sel.value !== (P.pack_box || "")) sel.value = P.pack_box || "";
  const fit = PBOXES.length && !P.pack_box ? boxFit(P.package) : "";
  if ($("#pkg-boxhint")) $("#pkg-boxhint").innerHTML = fit ? `${pbTH() ? "ตามขนาดพัสดุแนะนำ" : "按包裹尺寸推荐"} <b data-notr>${esc(fit)}</b> <button class="mini" id="pkg-boxuse" data-code="${esc(fit)}">${pbTH() ? "ใช้อันนี้" : "用这个"}</button>` : "";
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
