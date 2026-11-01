"use strict";
// 规格 ↔ 3D 模型（v2.22）：主模型是哪个文件；每个规格（大号 / 小号 / 套装…）用哪个模型。
// 用在：商品详情的 3D 模型卡片、文件管理的模型库、打印方案（选规格）。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const g = (v) => (v == null || v === "" ? "—" : `${Math.round(v * 10) / 10} g`);
  const sz = (s) => (s && s.length ? UX.sizeText(s, "×") : "");

  async function mount(el, pid, opts = {}) {
    if (!el || !pid) return;
    el.dataset.pid = pid;
    el._opts = opts;
    let d;
    try { d = await api(`/api/products/${encodeURIComponent(pid)}/spec-models`); } catch (e) { el.innerHTML = `<p class="bad small">${esc(e.message)}</p>`; return; }
    if (el.dataset.pid !== pid) return;     // 等结果时已经换了产品：旧产品的数据不要
    el._d = d;
    const lib = d.library.filter((x) => x.ok);
    const opt = (sel) => `<option value="">${Z("用主模型", "ใช้โมเดลหลัก")}${d.main ? ` · ${esc(d.main.name)}` : ""}</option>` +
      lib.filter((x) => !x.is_main).map((x) => `<option value="${esc(x.id)}" ${x.id === sel ? "selected" : ""}>${esc(x.name)}${x.size ? ` · ${sz(x.size)}` : ""}</option>`).join("");
    const others = lib.filter((x) => !x.is_main);
    const usedIds = new Set(d.specs.map((x) => x.entry_id).filter(Boolean));
    const free = others.filter((x) => !usedIds.has(x.id) && !x.parts_of);
    const hasParts = lib.some((x) => (x.parts || []).length > 1);
    const byId = Object.fromEntries(d.library.map((x) => [x.id, x]));
    const mainE = d.main && byId[d.main.lib_id];
    const multiParts = (s) => { const e = (s && s.entry_id && byId[s.entry_id]) || mainE; return e && (e.parts || []).length > 1 && !e.parts_of; };
    const mc = d.library.filter((x) => x.colors && x.colors.multicolor && (x.is_main || d.specs.some((s) => s.entry_id === x.id)));
    const notOwn = d.specs.filter((x) => !x.entry_id).length;
    el.innerHTML = `<div class="spm">
      <div class="row between wrap gap"><b>${Z("规格用哪个模型", "แต่ละแบบใช้โมเดลไหน")}</b>
        <span class="small">${Z("主模型", "โมเดลหลัก")}：<b data-notr>${esc(d.main ? d.main.name : Z("还没有", "ยังไม่มี"))}</b>${d.main && d.main.size ? ` <span class="muted">${sz(d.main.size)}</span>` : ""}
        ${others.length ? ` · <select data-spm-main data-notr><option value="">${Z("换成模型库里的…", "เปลี่ยนเป็นไฟล์อื่นในคลัง…")}</option>${others.map((x) => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("")}</select>` : ""}</span></div>
      ${d.has_specs ? `<table class="grid small"><thead><tr><th>${Z("规格", "แบบ")}</th><th>${Z("用的模型", "โมเดลที่ใช้")}</th><th>${Z("模型估算", "ประมาณจากโมเดล")}</th><th>${Z("变体里的克数", "กรัมในตัวเลือก")}</th><th>${Z("切片文件", "ไฟล์สไลซ์")}</th><th></th></tr></thead><tbody>` +
        d.specs.map((s) => `<tr><td data-notr><b>${esc(s.spec)}</b> <span class="muted">(${s.variants})</span></td>
          <td class="spm-mcell"><select data-spm-spec="${esc(s.spec)}" data-notr>${opt(s.entry_id)}</select>
            <div class="spm-acts">${multiParts(s) ? `<button class="mini" data-spm-flat="${esc(s.spec)}" title="${Z("每个组件按程序推荐的方向平放，排在一盘里（不叠在一起），并让 AI 检查能不能打出来", "วางแต่ละชิ้นตามทิศที่แนะนำ แล้วให้ AI ตรวจ")}">📐 ${Z("分体平放", "วางแยกชิ้น")}</button>` : ""}
            ${hasParts ? `<button class="mini" data-spm-parts="${esc(s.spec)}" title="${Z("这个规格只用模型文件里的某几个组件（例如一个 3MF 里有好几种组合）", "แบบนี้ใช้เฉพาะบางชิ้นส่วนในไฟล์")}">🧩 ${Z("选组件", "เลือกชิ้นส่วน")}</button>` : ""}
            <button class="mini" data-spm-up="${esc(s.spec)}" title="${Z("给这个规格上传一个新模型文件，传完自动用它", "อัปโหลดไฟล์โมเดลใหม่ให้แบบนี้")}">⬆ ${Z("上传 / 换模型", "อัปโหลด / เปลี่ยน")}</button></div></td>
          <td class="nowrap">${s.own ? g((s.est || {}).grams) : (d.main && d.main.estimate ? g(d.main.estimate.grams) : "—")}</td>
          <td class="nowrap">${g(s.grams)}</td><td>${s.files}</td>
          <td class="nowrap"><button class="mini" data-spm-fill="${esc(s.spec)}">${Z("按模型填克数", "ใส่กรัมตามโมเดล")}</button>
            ${opts.recipe !== false ? `<button class="mini" data-spm-recipe="${esc(s.spec)}">${Z("打印方案", "แผนการพิมพ์")}</button>` : ""}</td></tr>`).join("") + "</tbody></table>"
        : ""}
      ${mc.length ? `<div class="warn-box small">🎨 <b>${Z("多色模型", "โมเดลหลายสี")}</b>：${mc.some((x) => x.colors.painted)
          ? Z("涂色的多色模型：程序切会丢掉涂色，请在电脑上用 Bambu Studio 打开模型文件切片，再上传切片文件。", "โมเดลลงสีหลายสี: ระบบสไลซ์จะทำให้สีหาย ให้สไลซ์ใน Bambu Studio แล้วอัปโหลดไฟล์")
          : Z("不同零件不同颜色：到上面「🧩 打印方案」摆盘、给每个零件选 AMS 槽，再点「按这一盘切片」。", "แต่ละชิ้นคนละสี: ไปที่ \"🧩 แผนการพิมพ์\" ด้านบน จัดวางและเลือกช่อง AMS ให้แต่ละชิ้น แล้วกด \"สไลซ์ถาดนี้\"")}
        ${mc.map((x) => `<div><span data-notr>${esc(x.name)}</span>：<span data-notr>${esc(x.color_guide)}</span></div>`).join("")}</div>` : ""}
      ${!d.has_specs && mainE && (mainE.parts || []).length > 1 ? `<div class="row gap wrap" style="margin:6px 0"><button class="mini" data-spm-flat="">📐 ${Z("主模型分体平放", "วางแยกชิ้นโมเดลหลัก")}</button>
        <span class="small muted">${Z(`主模型有 ${mainE.parts.length} 个组件：每个按推荐方向平放排一盘，并让 AI 检查`, `มี ${mainE.parts.length} ชิ้น`)}</span></div>` : ""}
      ${hasParts && notOwn && d.has_specs ? `<div class="row gap wrap" style="margin:6px 0"><button class="primary mini" data-spm-autoparts>🔗 ${Z("按组件名自动对应规格", "จับคู่แบบกับชิ้นส่วนตามชื่ออัตโนมัติ")}</button>
        <span class="small muted">${Z(`模型文件里有多个组件：组件名里有规格名（例如组件「1x3」↔ 规格「1×3」）就自动对应；对不上的用「🧩 选组件」手动选`, "ไฟล์มีหลายชิ้นส่วน: ชื่อชิ้นส่วนตรงกับชื่อแบบจะจับคู่ให้อัตโนมัติ")}</span></div>` : ""}
      ${free.length ? `<div class="row gap wrap" style="margin:6px 0"><button class="primary mini" data-spm-auto>🪄 ${Z("按模型自动加规格", "เพิ่มแบบอัตโนมัติจากโมเดล")}</button>
        <span class="small muted">${Z(`模型库里有 ${free.length} 个模型还没对应规格：每个加成一个规格（按尺寸起名，例如 12cm），每个颜色一行，克数按模型估算，以后可以改名`,
          `มี ${free.length} โมเดลที่ยังไม่ได้ใช้กับแบบไหน: เพิ่มเป็นแบบละไฟล์ (ตั้งชื่อตามขนาด เช่น 12cm)`)}</span></div>` : ""}
      <input type="file" data-spm-file accept=".stl,.3mf,.obj" class="hidden">
      <p class="muted small">${d.has_specs
        ? Z("不同规格（大小 / 型号 / 套装）是不同的模型时，在这里给每个规格选模型库里的文件；没选的用主模型。选了自己模型的规格有自己的打印方案和切片文件，生产时按订单的 SKU 自动用对的模型。只卖一个模型的话，把要卖的设为主模型就行，其他文件留在模型库不影响。",
          "ถ้าแต่ละแบบ (ขนาด/รุ่น/เซ็ต) ใช้โมเดลต่างกัน ให้เลือกไฟล์จากคลังโมเดลให้แต่ละแบบ ไม่เลือก = ใช้โมเดลหลัก แบบที่มีโมเดลของตัวเองจะมีแผนการพิมพ์และไฟล์สไลซ์ของตัวเอง ตอนผลิตระบบใช้โมเดลที่ถูกต้องตาม SKU อัตโนมัติ")
        : Z("这个产品没有规格（变体的第二个选项，例如 大号 / 小号）。几个型号用不同模型的话，先在变体表加规格，再回来选模型。模型库里有好几个文件但只卖一个：把要卖的设为主模型。",
          "สินค้านี้ยังไม่มีแบบ (ตัวเลือกที่สอง เช่น ใหญ่/เล็ก) ถ้าหลายรุ่นใช้โมเดลต่างกัน ให้เพิ่มแบบในตารางตัวเลือกก่อน ถ้ามีหลายไฟล์แต่ขายแค่อันเดียว ให้ตั้งอันที่ขายเป็นโมเดลหลัก")}
        ${lib.length <= 1 ? Z(" 模型库里现在只有一个文件：要给规格指定别的模型，先在「📚 模型库」上传。", " ตอนนี้คลังมีไฟล์เดียว: อัปโหลดไฟล์อื่นที่「📚 คลังโมเดล」ก่อน") : ""}</p></div>`;
  }

  async function refresh(el) { await mount(el, el.dataset.pid, el._opts || {}); }

  // 商品编辑页开着同一个商品：把服务器上改过的变体同步到页面（不然再点保存会把新规格冲掉）
  function syncEditor(pid, prod) {
    if (!prod || typeof P === "undefined" || !P || P.id !== pid) return;
    for (const k of ["variants", "specs", "variation2_name_zh", "copy", "edit_rev", "model_lib"]) if (k in prod) P[k] = prod[k];
    const f = document.querySelector('[data-f="variation2_name_zh"]'); if (f) f.value = P.variation2_name_zh || "";
    if (typeof renderVariants === "function") renderVariants();
    if (typeof refreshPricing === "function") refreshPricing();
  }
  document.addEventListener("change", async (e) => {
    const t = e.target;
    const el = t.closest && t.closest("[data-pid]");
    if (!el || !el.querySelector(".spm")) return;
    const pid = el.dataset.pid;
    if (t.dataset.spmFile !== undefined && t.files && t.files[0]) {
      const spec = t.dataset.spec, fd = new FormData();
      fd.append("files", t.files[0]); fd.append("spec", spec);
      try {
        await busyToast(Z(`正在给「${spec}」上传模型…`, `กำลังอัปโหลดโมเดลให้「${spec}」…`), () => apiJob(`/api/products/${encodeURIComponent(pid)}/models`, { method: "POST", body: fd }));
        toast(Z(`「${spec}」已换成新模型。可以点「按模型填克数」，原来的切片文件要重新切片`, `「${spec}」ใช้โมเดลใหม่แล้ว`), false, 7000);
        try { syncEditor(pid, await api(`/api/products/${encodeURIComponent(pid)}`)); } catch { /* 忽略 */ }
        await refresh(el);
        if (el._opts && el._opts.onChange) el._opts.onChange();
      } catch (err) { toast(err.message, true); }
      return;
    }
    if (t.dataset.spmSpec !== undefined) {
      try {
        await api(`/api/products/${encodeURIComponent(pid)}/spec-models`, { json: { spec: t.dataset.spmSpec, entry_id: t.value } });
        toast(Z(`规格「${t.dataset.spmSpec}」的模型已改。这个规格原来的切片文件要重新切片或复核`, `เปลี่ยนโมเดลของแบบ「${t.dataset.spmSpec}」แล้ว ไฟล์สไลซ์เดิมต้องสไลซ์หรือตรวจใหม่`), false, 6000);
        await refresh(el);
        if (el._opts && el._opts.onChange) el._opts.onChange();
      } catch (err) { toast(err.message, true); refresh(el); }
    }
    if (t.dataset.spmMain !== undefined && t.value) {
      const name = t.selectedOptions[0].textContent;
      if (!confirm(Z(`把「${name}」设为主模型？3D 预览、商品图、估算都会换成它；主模型原来的切片文件会退回草稿。`, `ตั้ง「${name}」เป็นโมเดลหลัก? ไฟล์สไลซ์ของโมเดลหลักเดิมจะกลับเป็นร่าง`))) { t.value = ""; return; }
      try {
        await busyToast(Z("正在设为主模型…", "กำลังตั้งเป็นโมเดลหลัก…"), () => apiJob(`/api/products/${encodeURIComponent(pid)}/models/current`,
          { json: { items: [{ id: t.value, part: null, qty: 1, orient: "bottom" }] } }));
        toast(Z("已设为主模型", "ตั้งเป็นโมเดลหลักแล้ว"));
        await refresh(el);
        if (el._opts && el._opts.onChange) el._opts.onChange(true);
      } catch (err) { toast(err.message, true); }
    }
  });
  document.addEventListener("click", async (e) => {
    const t = e.target;
    const el = t.closest && t.closest("[data-pid]");
    if (!el || !el.querySelector(".spm")) return;
    const pid = el.dataset.pid;
    if (t.dataset.spmAutoparts !== undefined) {
      try {
        const r = await busyToast(Z("正在按组件名对应规格…", "กำลังจับคู่…"), () => apiJob(`/api/products/${encodeURIComponent(pid)}/spec-models/auto-parts`, { json: {} }));
        const n = Object.keys(r.done).length;
        toast(n ? Z(`已对应 ${n} 个规格。点「按模型填克数」更新克数；对不上的用「🧩 选组件」`, `จับคู่แล้ว ${n} แบบ`) : Z("组件名里没找到规格名，请用「🧩 选组件」手动选", "ไม่พบชื่อที่ตรงกัน"), !n, 8000);
        await refresh(el);
        if (el._opts && el._opts.onChange) el._opts.onChange();
      } catch (err) { toast(err.message, true); }
    }
    if (t.dataset.spmParts !== undefined) partsPicker(el, pid, t.dataset.spmParts);
    if (t.dataset.spmFlat !== undefined) {
      const spec = t.dataset.spmFlat;
      if (!confirm(Z(`把「${spec || "主模型"}」的每个组件按推荐方向平放排成一盘？原来的模型文件留在模型库，这个规格原来的切片文件要重新切片。`, "วางแต่ละชิ้นแยกกันตามทิศที่แนะนำ?"))) return;
      try {
        const r = await busyToast(Z("正在分体平放并让 AI 检查…", "กำลังจัดวางและให้ AI ตรวจ…"), () => apiJob(`/api/products/${encodeURIComponent(pid)}/spec-models/flatten`, { json: { spec } }));
        await refresh(el);
        if (el._opts && el._opts.onChange) el._opts.onChange(!spec);
        showCheck(spec, r.check);
      } catch (err) { toast(err.message, true); }
    }
    if (t.dataset.spmAuto !== undefined) {
      if (typeof P !== "undefined" && P && P.id === pid && typeof dirty !== "undefined" && dirty)
        return toast(Z("商品有没保存的修改：先点「保存」，再自动加规格", "มีการแก้ไขที่ยังไม่บันทึก กรุณาบันทึกก่อน"), true);
      try {
        const r = await busyToast(Z("正在按模型加规格…", "กำลังเพิ่มแบบ…"), () => api(`/api/products/${encodeURIComponent(pid)}/spec-models/auto`, { json: {} }));
        toast(Z(`已加规格：${r.added.join("、")}。记得检查价格，规格名可以在变体表「规格改名」`, `เพิ่มแบบแล้ว: ${r.added.join(", ")}`), false, 8000);
        syncEditor(pid, r.product);
        refresh(el);
        if (el._opts && el._opts.onChange) el._opts.onChange();
      } catch (err) { toast(err.message, true); }
    }
    if (t.dataset.spmUp !== undefined) {
      if (typeof P !== "undefined" && P && P.id === pid && typeof dirty !== "undefined" && dirty)
        return toast(Z("商品有没保存的修改：先点「保存」，再换模型", "มีการแก้ไขที่ยังไม่บันทึก กรุณาบันทึกก่อน"), true);
      const inp = el.querySelector("[data-spm-file]");
      inp.dataset.spec = t.dataset.spmUp; inp.value = ""; inp.click();
    }
    if (t.dataset.spmFill) {
      try {
        const r = await api(`/api/products/${encodeURIComponent(pid)}/spec-models/fill`, { json: { spec: t.dataset.spmFill } });
        toast(Z(`已按模型估算填入 ${r.filled} 个变体的克数和时长（标「估」，切片后可换成准确值）`, `ใส่กรัมและเวลาให้ ${r.filled} ตัวเลือกแล้ว (ค่าประมาณ)`));
        if (typeof P !== "undefined" && P && P.id === pid && typeof renderVariants === "function") {
          P.variants = r.product.variants; renderVariants(); if (typeof refreshPricing === "function") refreshPricing();
        }
        refresh(el);
      } catch (err) { toast(err.message, true); }
    }
    if (t.dataset.spmRecipe !== undefined && window.RECIPE) {
      const box = document.querySelector("#recipe-box");
      const wrap = document.querySelector("#recipe-wrap");
      if (el._opts && el._opts.openRecipe) el._opts.openRecipe(t.dataset.spmRecipe);
      else if (box && wrap && typeof P !== "undefined" && P && P.id === pid) { wrap.open = true; RECIPE.mount(box, pid, t.dataset.spmRecipe); box.scrollIntoView({ behavior: "smooth" }); }
    }
  });

  function partsPicker(el, pid, spec) {
    PICK = { el, pid };
    const d = el._d;
    const files = d.library.filter((x) => x.ok && (x.parts || []).length > 1);
    MODAL.open(`<div class="row between"><h3>${Z("规格", "แบบ")}「<span data-notr>${esc(spec)}</span>」${Z("用哪些组件", "ใช้ชิ้นส่วนไหน")}</h3><button class="mini" data-spm-pclose>${Z("关闭", "ปิด")}</button></div>
      <p class="small muted">${Z("勾选这个规格要打印的组件和数量，会组合成一个模型存进模型库，并指定给这个规格（主模型不变）。", "เลือกชิ้นส่วนและจำนวน ระบบจะรวมเป็นโมเดลให้แบบนี้")}</p>
      ${files.map((f) => `<div class="card-sub"><b data-notr>${esc(f.name)}</b><table class="grid small"><tbody>
        ${f.parts.map((x) => { const k = `${f.id}|${x.index}`; return `<tr><td><label class="row gap"><input type="checkbox" data-spmp="${k}"> <span data-notr>${esc(x.name || "#" + (x.index + 1))}</span></label></td>
          <td class="muted">${sz(x.size)}</td><td>${Z("数量", "จำนวน")} <input data-spmq="${k}" type="number" min="1" value="1" style="width:56px"></td></tr>`; }).join("")}
        </tbody></table></div>`).join("")}
      <div class="row gap" style="margin-top:8px"><button class="primary" data-spm-parts-ok="${esc(spec)}">${Z("确定", "ตกลง")}</button></div>`);
    // 组件名里有规格名的先勾上
    const key = String(spec).toLowerCase().replace(/×/g, "x").replace(/[\s_-]+/g, "");
    document.querySelectorAll("[data-spmp]").forEach((x) => {
      const n = x.parentElement.textContent.toLowerCase().replace(/×/g, "x").replace(/[\s_-]+/g, "");
      if (key && new RegExp(`(^|[^0-9.])${key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}([^0-9]|$)`).test(n)) x.checked = true;
    });
  }
  function showCheck(spec, c) {
    const LVC = { "低": "ok", "中": "warn", "高": "bad" };
    const risky = c && c.overall && c.overall.level !== "低";
    MODAL.open(`<div class="row between"><h3>📐 ${Z("分体平放完成", "จัดวางเสร็จ")} · <span data-notr>${esc(spec || Z("主模型", "โมเดลหลัก"))}</span></h3><button class="mini" data-spm-pclose>${Z("关闭", "ปิด")}</button></div>
      ${!c || c.error ? `<p class="small warn">${Z("AI 检查没做成", "AI ตรวจไม่สำเร็จ")}：<span data-notr>${esc((c && c.error) || "")}</span></p>` : `
      <p><b>${Z("AI 判断能不能打出来", "AI ประเมิน")}</b>：<span class="${LVC[c.overall.level] || ""}">${esc(c.overall.level)}${Z("风险", "ความเสี่ยง")}</span> · ${esc(TH() ? c.overall.th || c.overall.zh : c.overall.zh)}</p>
      <table class="grid small"><tbody>${(c.items || []).map((x) => `<tr><td data-notr>${esc(x.name)}</td><td class="${LVC[x.level] || ""}">${esc(x.level)}</td>
        <td>${esc(TH() ? x.risk_th || x.risk_zh : x.risk_zh)}</td><td>${esc(TH() ? x.fix_th || x.fix_zh : x.fix_zh)}</td></tr>`).join("")}</tbody></table>
      ${c.settings_zh ? `<p class="small">${Z("建议设置", "การตั้งค่าที่แนะนำ")}：${esc(TH() ? c.settings_th || c.settings_zh : c.settings_zh)}</p>` : ""}`}
      <div class="${risky ? "warn-box" : "muted"} small">${Z("零件多、风险中 / 高的盘，建议在电脑上用 Bambu Studio 打开模型检查摆放、切片，再把切片文件上传（打印方案 → 上传切片文件），比程序自动切更稳。",
        "ถ้าชิ้นเยอะหรือความเสี่ยงปานกลาง/สูง แนะนำให้สไลซ์ใน Bambu Studio บนคอมพิวเตอร์แล้วอัปโหลด")}</div>`);
  }
  let PICK = {};
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (!t.dataset) return;
    if (t.dataset.spmPclose !== undefined) MODAL.close();
    const pid = PICK.pid;
    if (t.dataset.spmPartsOk !== undefined) {
      const spec = t.dataset.spmPartsOk;
      const items = [...document.querySelectorAll("[data-spmp]")].filter((x) => x.checked).map((x) => {
        const [id, part] = x.dataset.spmp.split("|");
        const q = document.querySelector(`[data-spmq="${x.dataset.spmp}"]`);
        return { id, part: +part, qty: Math.max(1, +(q && q.value) || 1) };
      });
      if (!items.length) return toast(Z("先勾选组件", "เลือกชิ้นส่วนก่อน"), true);
      try {
        await busyToast(Z("正在组合模型…", "กำลังรวมโมเดล…"), () => apiJob(`/api/products/${encodeURIComponent(pid)}/spec-models/parts`, { json: { spec, items } }));
        MODAL.close();
        toast(Z(`「${spec}」已改用选中的组件。可以点「按模型填克数」`, `「${spec}」ใช้ชิ้นส่วนที่เลือกแล้ว`), false, 6000);
        await refresh(PICK.el);
        if (PICK.el._opts && PICK.el._opts.onChange) PICK.el._opts.onChange();
      } catch (err) { toast(err.message, true); }
    }
  });

  window.SPECMODEL = { mount, refresh };
})();
