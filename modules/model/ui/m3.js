"use strict";
// v2.53 编辑产品页 ③：规格切换（主模型 + 每个规格）+ 规格 × 状态概览表 + 展示 / 打印方案的一行摘要（默认收起）。
// 组装视图（three.js，assemble.js）和摆盘画布（plan.js）打开页面时不加载，点「查看 / 编辑」才打开，页面更快。
// 规格不只是大小：款式、带不带盖、2 个装、不同零件组合…… 每个规格有自己的展示（零件、数量、组装姿势）和打印方案（盘）；
// 「从某个规格复制」再改；「按主模型缩放 N%」= 展示和打印都按主模型缩放，不用另外的文件。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const n1 = (v) => (v == null || v === "" ? "—" : (Math.round(v * 10) / 10).toString());
  const enc = encodeURIComponent;
  const M = { pid: null, spec: "", st: null, asmOpen: false, planOpen: false };

  const css = `
  .m3-top{margin:6px 0 4px}
  .m3-specs{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:6px}
  .m3-specs .chip{cursor:pointer}
  .m3-ov{width:100%;border-collapse:collapse;font-size:13px;margin:4px 0}
  .m3-ov th,.m3-ov td{padding:4px 6px;border-bottom:1px solid #eef1f5;text-align:left;vertical-align:middle}
  .m3-ov tr[data-m3-row]{cursor:pointer}.m3-ov tr[data-m3-row]:hover{background:#f6f9fd}
  .m3-ov tr.on{background:#eaf3ff;box-shadow:inset 3px 0 0 #1565c0}
  .m3-tag{display:inline-block;border-radius:4px;padding:0 6px;font-size:12px;background:#eef1f5;color:#455}
  .m3-tag.ok{background:#e3f5ea;color:#18794e}.m3-tag.est{background:#fff3cd;color:#8a6100}.m3-tag.no{background:#fdecea;color:#b3261e}
  .m3-tag.inh{background:#f1f3f6;color:#667}
  .m3-tools{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font-size:13px;margin:4px 0 2px;padding:6px 8px;background:#f7f9fc;border-radius:8px}
  .m3-tools span{display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap}
  .m3-tools select{width:auto!important;max-width:220px;display:inline-block}.m3-tools input{width:72px!important;display:inline-block}
  .m3-sum{display:flex;gap:10px;align-items:center;flex-wrap:wrap;border:1px solid #e3e8ef;border-radius:10px;padding:6px 10px;margin:6px 0;background:#fff}
  .m3-sum img{width:64px;height:64px;object-fit:contain;border-radius:6px;background:#f6f8fb;border:1px solid #eef1f5}
  .m3-sum .m3-line{flex:1;min-width:220px}
  .m3-sum .m3-line b{font-size:14px}
  .m3-prog{font-size:13px;margin-top:4px}
  `;
  if (!document.getElementById("m3-css")) { const st = document.createElement("style"); st.id = "m3-css"; st.textContent = css; document.head.appendChild(st); }

  const specLabel = (s) => (s ? s : Z("主模型", "โมเดลหลัก"));
  const row = (s) => (M.st && M.st.specs.find((x) => x.spec === s)) || null;

  function dispText(d, short) {
    const n = d.parts;
    switch (d.mode) {
      case "explicit": return Z(`自己选的 ${n} 个零件`, `เลือกเอง ${n} ชิ้น`);
      case "merged": return Z(`自动拆回 ${n} 个零件`, `แยกกลับเป็น ${n} ชิ้นอัตโนมัติ`) + (short ? "" : Z("（主模型是合并的打印盘）", " (โมเดลหลักเป็นถาดที่รวมไว้)"));
      case "own": return Z(`规格自己的模型 · ${n} 个零件`, `โมเดลของแบบนี้ · ${n} ชิ้น`);
      case "inherit": return Z("跟主模型", "ตามโมเดลหลัก");
      case "scale": return Z(`主模型 × ${d.scale}%`, `โมเดลหลัก × ${d.scale}%`);
      case "none": return Z("没有模型", "ไม่มีโมเดล");
      default: return d.plain ? Z("主模型（原样）", "โมเดลหลัก (ตามไฟล์)") : Z(`按主模型 · ${n} 个零件`, `ตามโมเดลหลัก · ${n} ชิ้น`);
    }
  }
  function planTag(pl) {
    const m = {
      unsaved: ["no", Z("未保存", "ยังไม่บันทึก")], saved: ["est", Z("估", "ประมาณ")], sliced: ["ok", Z("已切片", "สไลซ์แล้ว")],
      partial: ["est", Z(`部分切片 ${pl.sliced}/${pl.plates}`, `สไลซ์บางส่วน ${pl.sliced}/${pl.plates}`)],
      follow: ["inh", Z(`主模型 × ${pl.scale}%`, `โมเดลหลัก × ${pl.scale}%`)], inherit: ["inh", Z("跟主模型", "ตามโมเดลหลัก")],
    }[pl.state] || ["", pl.state];
    return `<span class="m3-tag ${m[0]}">${m[1]}</span>`;
  }

  async function load() {
    if (!M.pid) return;
    const pid = M.pid;
    const st = await api(`/api/products/${enc(pid)}/model-status`);
    if (pid !== M.pid) return;          // 等结果时已经换了产品：旧产品的数据不要
    M.st = st;
    if (!row(M.spec)) M.spec = "";
  }
  function render() {
    const top = document.getElementById("m3-top");
    if (!top || !M.st) return;
    const specs = M.st.specs;
    const owner = specs.some((x) => x.plan.cost != null);
    const multi = specs.length > 1;
    top.innerHTML = `<div class="m3-specs"><b class="small">${Z("看哪个规格", "ดูแบบไหน")}：</b>
        ${specs.map((x) => `<span class="chip ${x.spec === M.spec ? "on" : ""}" data-m3-spec="${esc(x.spec)}" ${x.spec ? "data-notr" : ""}>${esc(specLabel(x.spec))}</span>`).join("")}
        <span class="small muted">${Z("规格不只是大小：款式、带不带盖、2 个装、不同零件…… 每个规格的展示和打印方案可以不一样", "แบบไม่ได้มีแค่ขนาด: สไตล์ มี/ไม่มีฝา แพ็ค 2 ชิ้น ชิ้นส่วนต่างกัน… แต่ละแบบตั้งการแสดงผลและแผนการพิมพ์แยกกันได้")}</span></div>
      ${multi || specs[0].plan.state !== "unsaved" ? `<table class="m3-ov"><thead><tr><th>${Z("规格", "แบบ")}</th><th>${Z("展示（组装）", "การแสดงผล (ประกอบ)")}</th><th>${Z("打印方案", "แผนการพิมพ์")}</th>
        <th>${Z("每件克数", "กรัม/ชิ้น")}</th><th>${Z("时长", "เวลา")}</th>${owner ? `<th>${Z("成本", "ต้นทุน")}</th>` : ""}</tr></thead><tbody>
        ${specs.map((x) => `<tr data-m3-row="${esc(x.spec)}" class="${x.spec === M.spec ? "on" : ""}">
          <td>${x.spec ? `<b data-notr>${esc(x.spec)}</b>` : `<b>${Z("主模型", "โมเดลหลัก")}</b>`}${x.variants != null ? ` <span class="muted small">(${x.variants})</span>` : ""}</td>
          <td><span class="m3-tag ${x.display.mode === "inherit" || x.display.mode === "scale" ? "inh" : x.display.set || x.display.posed ? "ok" : ""}">${(x.display.set || x.display.posed) && x.display.mode === "explicit" ? "✓ " : ""}${esc(dispText(x.display, true))}</span></td>
          <td>${planTag(x.plan)} <span class="small muted">${Z(`${x.plan.plates} 盘 · ${x.plan.items} 个零件`, `${x.plan.plates} ถาด · ${x.plan.items} ชิ้น`)}</span></td>
          <td class="nowrap">${n1(x.plan.grams)} g${x.plan.est && x.plan.grams ? ` <span class="m3-tag est">${Z("估", "ประมาณ")}</span>` : ""}</td>
          <td class="nowrap">${n1(x.plan.hours)} h</td>${owner ? `<td class="nowrap">${x.plan.cost != null ? "฿" + n1(x.plan.cost) : "—"}</td>` : ""}</tr>`).join("")}
        </tbody></table>` : ""}
      ${M.spec ? toolsHtml() : ""}`;
    renderSums();
  }
  function toolsHtml() {
    const x = row(M.spec); if (!x) return "";
    const others = M.st.specs.filter((s) => s.spec !== M.spec);
    const scaled = x.display.mode === "scale";
    return `<div class="m3-tools">
      <b data-notr>${esc(M.spec)}</b>
      <span>${Z("从", "คัดลอกจาก")} <select data-m3-from>${others.map((s) => `<option value="${esc(s.spec)}" ${s.spec ? "data-notr" : ""}>${esc(specLabel(s.spec))}</option>`).join("")}</select>
        <button class="mini" data-m3="copy" title="${Z("把那个规格的展示（零件、数量、组装姿势）和打印方案（盘）复制过来，再自己改", "คัดลอกการแสดงผลและแผนการพิมพ์ของแบบนั้นมา แล้วแก้เอง")}">${Z("复制过来（展示 + 打印方案）", "คัดลอกมา (แสดงผล + แผนพิมพ์)")}</button></span>
      <span class="muted">|</span>
      ${scaled ? `<span>${Z(`按主模型缩放 ${x.display.scale}%（展示和打印都跟着主模型）`, `ย่อ/ขยายจากโมเดลหลัก ${x.display.scale}% (แสดงผลและพิมพ์ตามโมเดลหลัก)`)}</span>
        <button class="mini" data-m3="unscale">${Z("取消缩放", "ยกเลิกการย่อ/ขยาย")}</button>`
        : `<span title="${Z("这个规格只是主模型放大 / 缩小：展示和打印都按主模型自动缩放，不用另外的文件", "แบบนี้แค่ย่อ/ขยายจากโมเดลหลัก ไม่ต้องใช้ไฟล์แยก")}">${Z("按主模型缩放", "ย่อ/ขยายจากโมเดลหลัก")}
        <input type="number" min="5" max="1000" step="1" value="100" data-m3-pct style="width:64px"> %</span>
        <button class="mini" data-m3="scale">${Z("应用", "ใช้")}</button>`}
    </div>`;
  }
  function renderSums() {
    const x = row(M.spec);
    const as = document.getElementById("asm-sum"), ps = document.getElementById("plan-sum");
    if (!x) { if (as) as.innerHTML = ""; if (ps) ps.innerHTML = ""; return; }
    const d = x.display, pl = x.plan, tag = M.spec ? ` · <span data-notr>${esc(M.spec)}</span>` : "";
    if (as) {
      const ok = d.mode === "explicit" && d.posed;
      const line = d.mode === "none" ? Z("还没有模型", "ยังไม่มีโมเดล")
        : Z(`组装：${d.parts} 个零件`, `ประกอบ: ${d.parts} ชิ้น`) + (ok ? " ✓" : "") + ` <span class="small muted">(${esc(dispText(d))})</span>`;
      as.innerHTML = d.mode === "none" ? "" : `<img loading="lazy" alt="" src="/api/products/${enc(M.pid)}/display/thumb?spec=${enc(M.spec)}&t=${d.token}">
        <div class="m3-line"><b>${line}</b>${tag}
          <div class="small muted">${d.auto && d.auto.conf != null ? Z(`自动组合置信度 ${Math.round(d.auto.conf * 100)}%`, `ความมั่นใจการประกอบอัตโนมัติ ${Math.round(d.auto.conf * 100)}%`) + " · " : ""}${d.updated_at ? Z("已保存 ", "บันทึกแล้ว ") + fmtTime(d.updated_at) : Z("组装好的样子用在 3D 预览、商品图；和打印方案无关", "แบบประกอบใช้ในตัวอย่าง 3D และรูปสินค้า ไม่เกี่ยวกับแผนการพิมพ์")}</div></div>
        <button class="primary-lite" id="btn-asm" data-ed-free>${M.asmOpen ? Z("收起组装视图", "ปิดมุมมองประกอบ") : "🧩 " + Z("查看 / 编辑组装", "ดู / แก้ไขการประกอบ")}</button>`;
    }
    if (ps) {
      const st = { unsaved: Z("未保存", "ยังไม่บันทึก"), inherit: Z("跟主模型的方案", "ใช้แผนของโมเดลหลัก"), follow: Z(`主模型 × ${pl.scale}%`, `โมเดลหลัก × ${pl.scale}%`) }[pl.state];
      const g = pl.grams ? `${pl.est ? Z("估 ", "ประมาณ ") : ""}${n1(pl.grams)} g · ${n1(pl.hours)} h` : "";
      const sl = M.st.slice_all;
      ps.innerHTML = `<img loading="lazy" alt="" src="/api/products/${enc(M.pid)}/print-plan/thumb?spec=${enc(M.spec)}&t=${enc(String(pl.updated_at || pl.state))}">
        <div class="m3-line"><b>${Z(`打印：${pl.plates} 盘 · ${pl.items} 个零件`, `พิมพ์: ${pl.plates} ถาด · ${pl.items} ชิ้น`)}${pl.state === "unsaved" || pl.state === "inherit" ? "" : " · " + Z("不重叠", "ไม่ซ้อนกัน")}${g ? " · " + g : ""}</b>${tag}
          ${st ? ` <span class="m3-tag ${pl.state === "unsaved" ? "no" : "inh"}">${st}</span>` : ""}${pl.state === "sliced" ? ` <span class="m3-tag ok">✂ ${Z("已切片", "สไลซ์แล้ว")}</span>` : ""}
          <div class="small muted">${pl.multicolor ? Z("多色 · 需要 AMS · ", "หลายสี · ต้องมี AMS · ") : ""}${Z("生产任务、成本、扣耗材都按打印方案", "งานผลิต ต้นทุน และการตัดสต็อกเส้นใช้ตามแผนการพิมพ์")}</div>
          <div class="m3-prog" data-m3-prog>${sl && sl.running ? progTxt(sl) : ""}</div></div>
        <div class="row gap wrap"><button class="primary-lite" data-m3="plan" data-ed-free>${M.planOpen ? Z("收起打印方案", "ปิดแผนการพิมพ์") : "🖨 " + Z("查看 / 编辑打印方案", "ดู / แก้ไขแผนการพิมพ์")}</button>
          <button class="mini" data-m3="slice-all" data-ed-free title="${Z("每个规格的每一盘按顺序切片（OrcaSlicer，后台），切完按方案填克数 / 时长", "สไลซ์ทุกถาดของทุกแบบตามลำดับ (เบื้องหลัง) แล้วใส่กรัม/เวลา")}">✂ ${Z("一键全部切片", "สไลซ์ทั้งหมด")}</button>
          ${window.TRIAL && TRIAL.can() ? `<button class="mini" data-ed-free data-tr-trial="${esc(M.pid)}" data-tr-spec="${esc(M.spec)}" data-tr-all="1" data-tr-src="editor">🧪 ${Z("试打", "ทดลองพิมพ์")}</button>` : ""}</div>
        <div class="tr-hist-box" data-tr-hist style="flex-basis:100%"></div>`;
      if (window.TRIAL) TRIAL.mount(ps.querySelector("[data-tr-hist]"), M.pid, true);
    }
  }
  function progTxt(sl) {
    if (!sl) return "";
    const cur = sl.current && typeof sl.current === "object" ? ` · ${esc(specLabel(sl.current.spec))} · ${Z("盘", "ถาด")} ${sl.current.no}/${sl.current.total}` : "";
    return `✂ ${Z("正在切片", "กำลังสไลซ์")} ${sl.done}/${sl.total}${cur}${sl.errors && sl.errors.length ? ` · <span class="bad">${Z(`${sl.errors.length} 盘没成功`, `${sl.errors.length} ถาดไม่สำเร็จ`)}</span>` : ""}`;
  }

  let LOADING = null;
  function switchTo(pid) {     // 打开了另一个产品：上一个产品的组装视图 / 打印方案编辑器要关掉，不能留在页面上
    M.pid = pid; M.spec = ""; M.asmOpen = false; M.planOpen = false; M.st = null; LOADING = null;
    if (window.ASM && ASM.current && ASM.current.pid !== pid) ASM.discard();
    const ab = document.getElementById("asm-box");
    if (ab && !(window.ASM && ASM.current)) { ab.innerHTML = ""; ab.classList.add("hidden"); }
    const pb = document.getElementById("plan-box");
    if (pb) pb.classList.add("hidden");
  }
  async function ensure(pid) {            // 3D 预览（model.js）要先知道这个规格的展示是什么
    if (M.pid !== pid) switchTo(pid);
    if (M.st) return M.st;
    if (!LOADING) LOADING = load().finally(() => { LOADING = null; });
    await LOADING;
    return M.st;
  }
  async function mount(pid) {
    if (M.pid !== pid) switchTo(pid);
    try { if (LOADING) await LOADING; await load(); render(); } catch (e) { const t = document.getElementById("m3-top"); if (t) t.innerHTML = `<p class="bad small">${esc(e.message)}</p>`; }
    const pb = document.getElementById("plan-box");
    if (pb) pb.classList.toggle("hidden", !M.planOpen);
  }
  async function refresh() { if (!M.pid) return; try { await load(); render(); } catch { /* 忽略 */ } }

  async function setSpec(s) {
    if (s === M.spec) return;
    if (window.ASM && ASM.current && ASM.current.dirty && !confirm(Z("组装有改动还没保存，切换规格会丢掉。继续？", "การประกอบยังไม่ได้บันทึก เปลี่ยนแบบจะหาย ดำเนินการต่อ?"))) return;
    if (window.PLAN && PLAN.dirty && PLAN.dirty() && !confirm(Z("打印方案有改动还没保存，切换规格会丢掉。继续？", "แผนการพิมพ์ยังไม่ได้บันทึก เปลี่ยนแบบจะหาย ดำเนินการต่อ?"))) return;
    M.spec = s;
    render();
    if (typeof renderModel === "function") renderModel().catch(() => {});        // 3D 预览按这个规格的展示
    if (M.asmOpen && window.ASM) { if (ASM.current) ASM.current.dirty = false; await openAsm(true); }
    if (M.planOpen && window.PLAN) await PLAN.open(M.spec);
  }

  async function openAsm(reopen) {
    const box = document.getElementById("asm-box");
    if (!box || typeof P === "undefined" || !P) return;
    if (M.asmOpen && !reopen) { if (window.ASM) ASM.close(); if (!(window.ASM && ASM.current)) { M.asmOpen = false; renderSums(); } return; }
    if (!window.ASM) await import("/m/model/assemble.js");
    M.asmOpen = true; renderSums();
    box.classList.remove("hidden");
    await window.ASM.open(box, P.id, { spec: M.spec, onSaved: afterSave, onClose: () => { M.asmOpen = false; renderSums(); } });
    if (!reopen) box.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  async function afterSave() {
    await refresh();
    if (typeof renderModel === "function") { if (typeof VIEWER_PID !== "undefined") VIEWER_PID = null; await renderModel().catch(() => {}); }
  }

  document.addEventListener("click", async (e) => {
    const top = e.target.closest("#m3-top, #asm-sum, #plan-sum");
    if (!top || typeof P === "undefined" || !P) return;
    const sp = e.target.closest("[data-m3-spec], tr[data-m3-row]");
    if (sp) { await setSpec(sp.dataset.m3Spec !== undefined ? sp.dataset.m3Spec : sp.dataset.m3Row); return; }
    if (e.target.id === "btn-asm") { try { await openAsm(); } catch (err) { toast(err.message || String(err), true); if (window.reportError3D) window.reportError3D(err, "组装视图"); } return; }
    const b = e.target.closest("[data-m3]"); if (!b) return;
    const a = b.dataset.m3;
    try {
      if (a === "plan") {
        if (!window.PLAN) return;
        if (M.planOpen) { if (PLAN.dirty() && !confirm(Z("打印方案有改动还没保存，收起会丢掉。继续？", "แผนการพิมพ์ยังไม่ได้บันทึก ปิดแล้วจะหาย ดำเนินการต่อ?"))) return; M.planOpen = false; PLAN.close(); renderSums(); return; }
        M.planOpen = true; renderSums();
        await busy(b, () => PLAN.open(M.spec));
        return;
      }
      if (a === "copy") {
        const from = (top.querySelector("[data-m3-from]") || {}).value || "";
        if (!confirm(Z(`把「${specLabel(from)}」的展示和打印方案复制到「${M.spec}」？这个规格现在的会被替换。`, `คัดลอกจาก「${specLabel(from)}」ไปยัง「${M.spec}」? ของเดิมจะถูกแทนที่`))) return;
        await busy(b, async () => {
          await api(`/api/products/${enc(M.pid)}/display/copy`, { json: { spec: M.spec, from } }).catch((err) => { if (!/还没有/.test(err.message)) throw err; });
          await api(`/api/products/${enc(M.pid)}/print-plan/copy`, { json: { spec: M.spec, from } });
        });
        toast(Z("已复制，可以接着改", "คัดลอกแล้ว แก้ต่อได้"));
        await afterChange();
        return;
      }
      if (a === "scale" || a === "unscale") {
        const pct = a === "scale" ? +((top.querySelector("[data-m3-pct]") || {}).value || 0) : null;
        if (a === "scale" && !(pct >= 5 && pct <= 1000)) { toast(Z("缩放要在 5% 到 1000% 之间", "ต้องอยู่ระหว่าง 5% ถึง 1000%"), true); return; }
        await busy(b, () => api(`/api/products/${enc(M.pid)}/spec-scale`, { json: { spec: M.spec, pct } }));
        toast(a === "scale" ? Z(`「${M.spec}」= 主模型 × ${pct}%（展示和打印方案）`, `「${M.spec}」= โมเดลหลัก × ${pct}%`) : Z("已取消缩放", "ยกเลิกแล้ว"));
        await afterChange();
        return;
      }
      if (a === "slice-all") {
        if (!confirm(Z("按顺序切每个规格的每一盘（OrcaSlicer，在后台，要几分钟）。切完按方案填各变体的克数 / 时长。开始？", "สไลซ์ทุกถาดของทุกแบบตามลำดับ (เบื้องหลัง อาจใช้หลายนาที) แล้วใส่กรัม/เวลาให้ตัวเลือก เริ่มเลย?"))) return;
        await busy(b, async () => {
          const r = await apiJob(`/api/products/${enc(M.pid)}/print-plan/slice-all`, { json: {} }, async () => {
            try { const s = await api(`/api/products/${enc(M.pid)}/model-status`); const el = document.querySelector("[data-m3-prog]"); if (el) el.innerHTML = progTxt(s.slice_all); } catch { /* 忽略 */ }
          });
          const okN = (r.results || []).length, bad = r.errors || [];
          toast(Z(`切好 ${okN} / ${r.total} 盘`, `สไลซ์แล้ว ${okN} / ${r.total} ถาด`) + (bad.length ? Z(`；没成功：${bad.map((x) => `${specLabel(x.spec)} ${x.no ? "#" + x.no : ""} ${x.error}`).join("；")}`, `; ไม่สำเร็จ ${bad.length}`) : ""), !!bad.length, bad.length ? 12000 : 5000);
        }, TR("busy.slicing"));
        await afterChange(true);
        return;
      }
    } catch (err) { toast(err.message || String(err), true); }
  });
  async function afterChange(variants) {
    await refresh();
    if (variants && typeof P !== "undefined" && P && P.id === M.pid) {
      try { const fresh = await api(`/api/products/${enc(M.pid)}`); P.variants = fresh.variants; P.print_plans = fresh.print_plans; P.edit_rev = fresh.edit_rev; if (window.renderVariants) renderVariants(); if (window.refreshPricing) refreshPricing(); } catch { /* 忽略 */ }
    }
    if (M.asmOpen && window.ASM) await openAsm(true);
    if (M.planOpen && window.PLAN) await PLAN.open(M.spec);
    if (typeof renderModel === "function") { if (typeof VIEWER_PID !== "undefined") VIEWER_PID = null; renderModel().catch(() => {}); }
  }
  window.addEventListener("model-changed", (e) => { if (e.detail === M.pid) refresh(); });
  window.M3 = { mount, ensure, refresh, render, afterSave, afterChange, get spec() { return M.spec; }, get pid() { return M.pid; },
    disp(spec) { const x = row(spec === undefined ? M.spec : spec); return x ? x.display : null; },
    get state() { return M; } };
})();
