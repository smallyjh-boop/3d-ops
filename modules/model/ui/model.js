"use strict";
// 3D 模型模块：编辑产品页的 3D 预览、渲染商品图、估算克数和时长、AI 打印建议、真实打印质感。
// v2.34 从 static/app.js 搬过来，代码没改。
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


// ---------------- AI 打印建议 + 产品描述 ----------------
const ORIENT_LABEL = { bottom: "原始方向（底面朝下）", top: "倒放（顶面朝下）", front: "前面朝下平放", back: "背面朝下平放", left: "左侧朝下平放", right: "右侧朝下平放" };
const SUPPORT_LABEL = { none: "不需要支撑", tree: "树状支撑（自动）", normal: "普通支撑（自动）" };
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
