"use strict";
// v2.53 AI 场景图：类目模板（泰国家居风格）→ AI 写提示词（看产品图）→ 一次出几张候选 → AI 质检打分 → 员工挑满意的加入商品图。
// 多尺寸（1:1 / 3:4 / 4:3 / 16:9 / 9:16）；先估费用、做完显示实际费用（按 AI 用量记录）。
// 另外：产品列表勾选后「批量场景图」（后台排队、进度、可取消）。
// 依赖 app.js / editor.js / scene.js 的全局：P, api, apiJob, toast, busy, esc, renderImages, saveProduct, dirty, sceneCutout, sceneColor, LIB_SEL, MODAL
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const money = (v) => (+v || 0).toFixed(2);
  const G = { tpl: null, sel: "", aspect: "1:1", n: 2, qa: true, aiPrompt: true, cands: [], pick: new Set(), ready: null, suggest: [], last: null };

  async function templates() {
    if (!G.tpl) G.tpl = await api("/api/scenes/templates");
    return G.tpl;
  }

  async function open() {
    const box = document.getElementById("scene-gen");
    if (!box || !P) return;
    try {
      await templates();
      const r = await api(`/api/products/${encodeURIComponent(P.id)}/scene-cands`);
      G.cands = r.cands || []; G.ready = r.ready; G.suggest = r.suggest || [];
      if (!G.sel || !G.tpl.templates.some((t) => t.key === G.sel)) G.sel = G.suggest[0] || (G.tpl.templates[0] || {}).key || "";
      G.pick.clear();
      render(); estimate();
    } catch (e) { box.innerHTML = `<p class="bad small" data-notr>${esc(e.message)}</p>`; }
  }

  const readyLine = (r) => !r ? "" : `<div class="small">${r.image ? `<span class="ok">✓ ${Z("出图 AI", "AI สร้างรูป")}</span>` : `<span class="bad">✗ ${Z("出图 AI 没设置", "ยังไม่ได้ตั้งค่า AI สร้างรูป")}</span>`}
    · ${r.prompt ? `<span class="ok">✓</span>` : `<span class="muted">✗</span>`} ${Z("AI 写提示词", "AI เขียนพรอมต์")}
    · ${r.qa ? `<span class="ok">✓</span>` : `<span class="muted">✗</span>`} ${Z("AI 看图质检", "AI ตรวจรูป")}
    · <a href="#" data-sg-conf>${Z("AI 接口设置", "ตั้งค่าการเชื่อมต่อ AI")}</a></div>`;

  function qaBadge(q) {
    if (!q) return `<span class="pill">${Z("未质检", "ยังไม่ตรวจ")}</span>`;
    if (q.score == null) return `<span class="pill" title="${esc(q.error || "")}">${Z("质检出错", "ตรวจผิดพลาด")}</span>`;
    const bad = q.ok === false;
    const issues = [!q.shape_ok && Z("形状不对", "รูปทรงไม่ตรง"), !q.color_ok && Z("颜色不对", "สีไม่ตรง"), !q.no_text && Z("有文字 / 水印", "มีตัวอักษร / ลายน้ำ"),
      !q.realistic && Z("不真实", "ไม่สมจริง")].filter(Boolean);
    return `<span class="pill ${bad ? "warn-pill" : ""}" title="${esc(TH() ? q.issues_th || "" : q.issues_zh || "")}">${bad ? "⚠" : "✓"} ${q.score}</span>${issues.length ? `<div class="small bad">${issues.join(" · ")}</div>` : ""}`;
  }

  function render() {
    const box = document.getElementById("scene-gen");
    const T = G.tpl.templates;
    box.innerHTML = `<div class="small"><b>${Z("AI 场景图（一次出几张，挑满意的）", "รูปฉาก AI (สร้างหลายรูป เลือกที่ชอบ)")}</b></div>
      ${readyLine(G.ready)}
      <div class="small">${Z("场景模板（★ = 按类目推荐）", "เทมเพลตฉาก (★ = แนะนำตามหมวดหมู่)")}：</div>
      <div class="chips" id="sg-tpls">${T.map((t) => `<span class="chip ${t.key === G.sel ? "on" : ""}" data-sgt="${esc(t.key)}" data-notr>${G.suggest.includes(t.key) ? "★ " : ""}${esc(TH() ? t.th || t.zh : t.zh)}</span>`).join("")}</div>
      <div class="row gap wrap small" style="margin-top:4px">
        <span>${Z("尺寸", "ขนาด")}</span>${G.tpl.aspects.map((a) => `<span class="chip ${a === G.aspect ? "on" : ""}" data-sga="${a}">${a}</span>`).join("")}
        <label>${Z("张数", "จำนวน")} <select id="sg-n">${[1, 2, 3, 4, 5, 6].slice(0, G.tpl.max_n).map((x) => `<option ${x === G.n ? "selected" : ""}>${x}</option>`).join("")}</select></label>
        <label class="row gap"><input type="checkbox" id="sg-aip" ${G.aiPrompt ? "checked" : ""}> ${Z("AI 写提示词", "AI เขียนพรอมต์")}</label>
        <label class="row gap"><input type="checkbox" id="sg-qa" ${G.qa ? "checked" : ""}> ${Z("AI 质检", "AI ตรวจรูป")}</label></div>
      <input id="sg-extra" placeholder="${Z("补充要求（可空），例：泰式风格、圣诞节氛围、放在白色书桌上", "ความต้องการเพิ่มเติม (เว้นว่างได้) เช่น สไตล์ไทย, บรรยากาศคริสต์มาส, วางบนโต๊ะสีขาว")}">
      <div class="row gap wrap" style="margin-top:6px"><button id="sg-go" ${G.ready && !G.ready.image ? "disabled" : ""}>✨ ${Z("生成候选", "สร้างรูปตัวเลือก")}</button>
        <span id="sg-est" class="muted small"></span><span id="sg-prog" class="muted small"></span></div>
      <p class="muted small">${Z("能「参考图改图」的出图 AI 会照着产品抠图画；不能改图的只生成空场景，再把真实产品贴上去，产品不会走样。",
        "AI สร้างรูปที่「แก้รูปจากรูปอ้างอิง」ได้จะวาดตามรูปสินค้าที่ตัดพื้นหลัง ถ้าแก้รูปไม่ได้จะสร้างฉากว่างแล้ววางสินค้าจริงลงไป สินค้าจะไม่ผิดรูป")}</p>
      ${G.cands.length ? `<div class="row between wrap"><b class="small">${Z(`候选 ${G.cands.length} 张`, `ตัวเลือก ${G.cands.length} รูป`)}</b>
        <button class="primary mini" id="sg-add" ${G.pick.size ? "" : "disabled"}>${Z(`把选中的 ${G.pick.size} 张加入商品图`, `เพิ่ม ${G.pick.size} รูปที่เลือกเข้ารูปสินค้า`)}</button></div>
      <div class="sg-grid" id="sg-cands">${G.cands.slice().reverse().map((c) => `<div class="sg-cand ${G.pick.has(c.id) ? "on" : ""} ${c.qa && c.qa.ok === false ? "bad" : ""}" data-sgc="${c.id}">
          <img src="${esc(c.url)}" alt="" style="aspect-ratio:${c.aspect.replace(":", "/")}">
          <div class="small row between"><span>${qaBadge(c.qa)}</span><span>${c.aspect} · ${c.mode === "edit" ? Z("改图", "แก้รูป") : Z("合成", "ซ้อนรูป")}${c.picked ? " · ✓" : ""}</span>
          <button class="x" data-sgdel="${c.id}" title="${Z("删除", "ลบ")}">✕</button></div></div>`).join("")}</div>` : ""}`;
  }

  async function estimate() {
    const el = document.getElementById("sg-est");
    if (!el) return;
    try {
      const r = await api("/api/scenes/estimate", { json: { products: 1, n: G.n, qa: G.qa, ai_prompt: G.aiPrompt } });
      el.textContent = Z(`预计约 ${money(r.total)} 铢`, `ประมาณ ${money(r.total)} บาท`);
    } catch { el.textContent = ""; }
  }

  document.addEventListener("click", async (e) => {
    const box = e.target.closest && e.target.closest("#scene-gen");
    if (!box) return;
    const t = e.target.closest("[data-sgt]"), a = e.target.closest("[data-sga]");
    if (e.target.closest("[data-sg-conf]")) { e.preventDefault(); goTab("ai_conf"); return; }
    if (t) { G.sel = t.dataset.sgt; render(); estimate(); return; }
    if (a) { G.aspect = a.dataset.sga; render(); estimate(); return; }
    const del = e.target.closest("[data-sgdel]");
    if (del) {
      e.stopPropagation();
      const r = await api(`/api/products/${encodeURIComponent(P.id)}/scene-cands/${del.dataset.sgdel}`, { method: "DELETE" });
      G.cands = r.cands; G.pick.delete(del.dataset.sgdel); render(); return;
    }
    const c = e.target.closest("[data-sgc]");
    if (c) { G.pick.has(c.dataset.sgc) ? G.pick.delete(c.dataset.sgc) : G.pick.add(c.dataset.sgc); render(); return; }
    if (e.target.id === "sg-add") {
      await busy(e.target, async () => {
        if (typeof dirty !== "undefined" && dirty && typeof saveProduct === "function") await saveProduct(true);
        const r = await api(`/api/products/${encodeURIComponent(P.id)}/scene-cands/pick`, { json: { ids: [...G.pick], color: window.sceneColor ? sceneColor() : "" } });
        P = r.product; G.cands = r.cands; G.pick.clear(); renderImages(); render();
        toast(Z(`已加入 ${r.added} 张场景图（在图片列表里，可调整顺序）`, `เพิ่มรูปฉาก ${r.added} รูปแล้ว (อยู่ในรายการรูป จัดลำดับได้)`));
      });
      return;
    }
    if (e.target.id === "sg-go") {
      const extra = (document.getElementById("sg-extra").value || "").trim();
      await busy(e.target, async () => {
        if (typeof dirty !== "undefined" && dirty && typeof saveProduct === "function") await saveProduct(true);
        const prog = document.getElementById("sg-prog");
        prog.textContent = Z(`AI 正在生成 ${G.n} 张（每张约 20-60 秒）…`, `AI กำลังสร้าง ${G.n} รูป (รูปละประมาณ 20-60 วินาที)…`);
        try {
          const r = await apiJob(`/api/products/${encodeURIComponent(P.id)}/scene-gen`, { json: { template: G.sel, aspect: G.aspect, n: G.n, qa: G.qa, ai_prompt: G.aiPrompt, extra,
            image: window.sceneCutout ? sceneCutout() : "" } });
          G.cands = r.all || G.cands; G.last = r;
          (r.cands || []).forEach((x) => { if (!x.qa || x.qa.ok !== false) G.pick.add(x.id); });
          render();
          const p2 = document.getElementById("sg-prog");
          if (p2) p2.textContent = Z(`已生成 ${r.cands.length} 张，实际费用 ${money(r.cost)} 铢${r.errors && r.errors.length ? `（${r.errors.length} 张失败）` : ""}。质检有 ⚠ 的建议不用。`,
            `สร้างแล้ว ${r.cands.length} รูป ค่าใช้จ่ายจริง ${money(r.cost)} บาท${r.errors && r.errors.length ? ` (ล้มเหลว ${r.errors.length} รูป)` : ""} รูปที่มี ⚠ ไม่แนะนำให้ใช้`);
        } catch (err) { prog.textContent = ""; toast(err.message, true); }
      });
    }
  });
  document.addEventListener("change", (e) => {
    if (!e.target.closest || !e.target.closest("#scene-gen")) return;
    if (e.target.id === "sg-n") { G.n = +e.target.value; estimate(); }
    if (e.target.id === "sg-qa") { G.qa = e.target.checked; estimate(); }
    if (e.target.id === "sg-aip") { G.aiPrompt = e.target.checked; estimate(); }
  });

  // ---------------- 批量（产品列表勾选） ----------------
  let timer = null;
  async function batchDialog(ids) {
    const T = (await templates()).templates;
    const m = MODAL.open(`<div class="row between"><h3>🖼 ${Z("批量 AI 场景图", "รูปฉาก AI แบบกลุ่ม")}</h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      <div id="sgb-body"><p class="small">${Z(`已勾选 ${ids.length} 个产品。每个产品出几张候选（存起来，打开产品页「场景图」里挑），也可以自动把质检最高的一张加进商品图。`,
        `เลือกไว้ ${ids.length} สินค้า แต่ละสินค้าสร้างรูปตัวเลือกหลายรูป (เก็บไว้ เลือกได้ในหน้าสินค้า「รูปฉาก」) หรือเพิ่มรูปที่ตรวจได้คะแนนสูงสุดเข้ารูปสินค้าอัตโนมัติ`)}</p>
      <div class="form2">
        <label>${Z("场景模板", "เทมเพลตฉาก")}<select id="sgb-tpl"><option value="">${Z("按类目自动推荐", "แนะนำอัตโนมัติตามหมวดหมู่")}</option>${T.map((t) => `<option value="${esc(t.key)}" data-notr>${esc(TH() ? t.th || t.zh : t.zh)}</option>`).join("")}</select></label>
        <label>${Z("尺寸", "ขนาด")}<select id="sgb-aspect">${G.tpl.aspects.map((a) => `<option>${a}</option>`).join("")}</select></label>
        <label>${Z("每个产品几张", "จำนวนต่อสินค้า")}<select id="sgb-n">${[1, 2, 3, 4].map((x) => `<option ${x === 2 ? "selected" : ""}>${x}</option>`).join("")}</select></label>
        <label>${Z("补充要求", "ความต้องการเพิ่มเติม")}<input id="sgb-extra"></label></div>
      <div class="row gap wrap small"><label class="row gap"><input type="checkbox" id="sgb-aip" checked> ${Z("AI 写提示词", "AI เขียนพรอมต์")}</label>
        <label class="row gap"><input type="checkbox" id="sgb-qa" checked> ${Z("AI 质检", "AI ตรวจรูป")}</label>
        <label class="row gap"><input type="checkbox" id="sgb-auto"> ${Z("自动加入质检最高的一张", "เพิ่มรูปที่คะแนนสูงสุดอัตโนมัติ")}</label></div>
      <p><b id="sgb-est"></b></p>
      <div class="row gap"><button class="primary" id="sgb-go">${Z("开始（后台）", "เริ่ม (เบื้องหลัง)")}</button></div></div>
      <div id="sgb-prog"></div>`);
    const opts = () => ({ ids, template: $("#sgb-tpl").value, aspect: $("#sgb-aspect").value, n: +$("#sgb-n").value, extra: $("#sgb-extra").value.trim(),
      ai_prompt: $("#sgb-aip").checked, qa: $("#sgb-qa").checked, auto_add: $("#sgb-auto").checked });
    const est = async () => {
      try {
        const r = await api("/api/scenes/estimate", { json: { ...opts(), products: ids.length } });
        $("#sgb-est").textContent = Z(`预计费用约 ${money(r.total)} 铢（${r.count} 张图）`, `ค่าใช้จ่ายประมาณ ${money(r.total)} บาท (${r.count} รูป)`);
      } catch (e) { $("#sgb-est").textContent = e.message; }
    };
    m.onchange = est; est();
    m.onclick = async (e) => {
      if (e.target.id === "sgb-go") {
        await busy(e.target, async () => { await api("/api/scenes/batch", { json: opts() }); $("#sgb-body").classList.add("hidden"); poll(); });
      } else if (e.target.id === "sgb-cancel") {
        await api("/api/scenes/batch/cancel", { json: {} }); poll();
      }
    };
    const s = await api("/api/scenes/batch");
    if (s.running) { $("#sgb-body").classList.add("hidden"); poll(); }
  }

  async function poll() {
    clearTimeout(timer);
    const box = document.getElementById("sgb-prog");
    if (!box) return;
    const s = await api("/api/scenes/batch").catch(() => null);
    if (!s || !s.items) return;
    const st = { queued: Z("排队", "รอคิว"), running: Z("生成中", "กำลังสร้าง"), done: Z("完成", "เสร็จ"), error: Z("失败", "ล้มเหลว"), cancelled: Z("已取消", "ยกเลิกแล้ว") };
    box.innerHTML = UX.kpis([
      { label: Z("进度", "ความคืบหน้า"), value: `${s.done} / ${s.total}`, tone: s.running ? "info" : "ok" },
      { label: Z("失败", "ล้มเหลว"), value: s.failed, tone: s.failed ? "bad" : "" },
      { label: Z("预计 / 实际（铢）", "ประมาณ / จริง (บาท)"), value: `${money(s.estimate)} / ${money(s.cost)}` },
    ]) + `<div class="ux-meter"><span class="ux-meter-t"><i style="width:${Math.round(100 * s.done / Math.max(1, s.total))}%"></i></span></div>
      ${s.running ? `<button class="danger mini" id="sgb-cancel">${s.cancel ? Z("正在取消…", "กำลังยกเลิก…") : Z("取消", "ยกเลิก")}</button>` : `<p class="ok">${Z("这一批做完了。打开产品页「场景图」挑候选。", "ชุดนี้เสร็จแล้ว เปิดหน้าสินค้า「รูปฉาก」เพื่อเลือกรูป")}</p>`}
      <table class="grid small"><tbody>${s.items.map((it) => `<tr><td data-notr>${esc(it.pid)}</td><td>${st[it.status] || it.status}</td><td>${it.n ? Z(`${it.n} 张`, `${it.n} รูป`) : ""}${it.added ? " · " + Z("已加入", "เพิ่มแล้ว") : ""}</td>
        <td class="bad" data-notr>${esc(it.error || "")}</td></tr>`).join("")}</tbody></table>`;
    if (s.running) timer = setTimeout(poll, 2000);
  }

  window.SCENEGEN = { open, batch: batchDialog };
  const bb = document.getElementById("btn-lib-scene");
  if (bb) bb.addEventListener("click", () => {
    if (typeof LIB_SEL === "undefined" || !LIB_SEL.size) return toast(Z("请先勾选产品", "กรุณาเลือกสินค้าก่อน"), true);
    batchDialog([...LIB_SEL]).catch((e) => toast(e.message, true));
  });
})();
