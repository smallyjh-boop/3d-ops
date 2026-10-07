"use strict";
// 搜索优化（v2.23）：编辑页的搜索分 + AI 搜索优化（先出对比，勾选确认才替换）；产品库批量优化和逐个确认。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const plain = (h) => String(h || "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  const LV = { good: "ok", ok: "warn", bad: "bad" };

  // ---------------- 编辑页：搜索分 ----------------
  let T = null, SEQ = 0;
  function schedule() { clearTimeout(T); T = setTimeout(renderPanel, 600); }
  async function renderPanel() {
    const box = document.querySelector("#seo-panel");
    if (!box || typeof P === "undefined" || !P || !P.id) return;
    const seq = ++SEQ;
    let r;
    try { r = await api(`/api/products/${encodeURIComponent(P.id)}/seo`, { json: P }); } catch { return; }
    if (seq !== SEQ) return;
    const bad = r.items.filter((x) => !x.ok);
    const rv = P.seo_review;
    const LVC = { "高": "bad", "中": "warn", "低": "muted" };
    const rvHtml = rv ? `<div class="seo-ai"><div class="row between wrap gap"><div><b>🤖 ${Z("AI 评分", "คะแนนจาก AI")}</b> <span class="seo-score ${rv.score >= 80 ? "" : rv.score >= 60 ? "warn" : "bad"}">${rv.score ?? "—"}</span>
          <span class="small">${esc(TH() ? rv.summary_th || rv.summary_zh : rv.summary_zh)}</span></div><span class="small muted">${fmtTime(rv.at).slice(5, 16)}</span></div>
        ${(rv.items || []).map((x, i) => `<div class="seo-sug small"><span class="${LVC[x.level] || ""}">●</span> <b>${esc(x.label)}</b>：${esc(TH() ? x.problem_th || x.problem_zh : x.problem_zh)}
          ${x.suggestion_zh ? `<div class="muted">→ ${esc(x.suggestion_zh)}</div>` : ""}
          ${x.new_value ? `<div class="seo-nv" data-notr>${esc(String(x.new_value).replace(/<[^>]+>/g, " ").slice(0, 300))}</div><button class="mini primary" data-seo-use="${i}">${Z("采用这条", "ใช้ข้อนี้")}</button>` : ""}</div>`).join("")}</div>` : "";
    box.innerHTML = `<div class="row between wrap gap">
        <div><b>${Z("搜索分", "คะแนนการค้นหา")}</b> <span class="seo-score ${LV[r.level]}">${r.score}</span>
          <span class="small muted">${Z("标题、关键词、详情、标签越完整，被搜到的机会越大", "ชื่อ คำค้น รายละเอียด แท็ก ยิ่งครบยิ่งถูกค้นเจอ")}</span></div>
        ${P.seo_undo ? `<button class="mini" id="btn-seo-undo" title="${Z("恢复成上次 AI 搜索优化之前的样子", "ย้อนกลับเป็นก่อนปรับปรุงครั้งล่าสุด")}">↩ ${Z("撤销上次优化", "ย้อนกลับ")}（${fmtTime(P.seo_undo.at).slice(5, 16)}）</button>` : ""}
      </div>
      <div class="row gap wrap" style="margin:4px 0"><button class="mini" id="btn-seo-review">🤖 ${Z("AI 打分和建议", "ให้ AI ให้คะแนนและแนะนำ")}</button>
        <span class="small muted">${Z("按现在的内容（包括你手工改的）打分，给出具体可以采用的修改", "ให้คะแนนตามเนื้อหาตอนนี้ พร้อมคำแนะนำที่กดใช้ได้")}</span></div>
      ${rvHtml}
      ${bad.length ? `<ul class="seo-miss small">${bad.map((x) => `<li>✗ ${esc(Z(x.zh, x.th))}</li>`).join("")}</ul>` : `<div class="small ok">✓ ${Z("各项都达标", "ผ่านทุกข้อ")}</div>`}
      ${r.wait_days ? `<div class="small warn">${Z(`已上架的商品最近改过标题：建议 ${r.wait_days} 天后再改（频繁改标题可能影响排名）`, `เพิ่งเปลี่ยนชื่อไป แนะนำรออีก ${r.wait_days} วัน`)}</div>` : ""}`;
  }

  // ---------------- 对比确认 ----------------
  function cell(k, v) {
    if (v == null || v === "") return `<span class="muted">${Z("（空）", "(ว่าง)")}</span>`;
    if (k === "description_th" || k === "description_en") return `<div class="seo-desc">${String(v).replace(/<(?!\/?(p|ul|ol|li|strong|b|br)\b)[^>]*>/gi, "")}</div>`;
    if (Array.isArray(v)) return esc(v.join(" · "));
    if (typeof v === "object") return esc(Object.entries(v).map(([a, b]) => `${a}=${b}`).join("，"));
    return `<span style="white-space:pre-wrap">${esc(String(v))}</span>${k.startsWith("title") ? ` <span class="muted small">${String(v).length} ${Z("字", "ตัว")}</span>` : ""}`;
  }
  function reviewHtml(v, i, n) {
    return `<div class="row between wrap gap"><h3>${Z("搜索优化 · 确认", "ปรับปรุงการค้นหา · ยืนยัน")} <span data-notr>${esc(v.id)}</span> <span class="muted small" data-notr>${esc(v.name_zh || "")}</span></h3>
        <div class="row gap">${n > 1 ? `<span class="small muted">${i + 1} / ${n}</span><button class="mini" data-seo-nav="-1" ${i ? "" : "disabled"}>‹</button><button class="mini" data-seo-nav="1" ${i < n - 1 ? "" : "disabled"}>›</button>` : ""}
        <button class="mini" data-seo-close>${Z("关闭", "ปิด")}</button></div></div>
      <p class="small">${Z("搜索分", "คะแนน")} <b>${v.score_before}</b> → <b class="ok">${v.score_after}</b>。${Z("勾选要采用的项，其他保持不变。", "เลือกรายการที่จะใช้ ที่เหลือคงเดิม")}
        ${v.wait_days ? `<span class="warn">${Z(`这个商品已上架、最近改过标题，建议 ${v.wait_days} 天后再换标题（可以先只换详情和标签）。`, `สินค้านี้เพิ่งเปลี่ยนชื่อ แนะนำรออีก ${v.wait_days} วัน`)}</span>` : ""}</p>
      <table class="grid small seo-diff"><thead><tr><th style="width:28px"><input type="checkbox" data-seo-all checked></th><th style="width:120px">${Z("项目", "รายการ")}</th><th>${Z("现在", "ตอนนี้")}</th><th>${Z("AI 优化后", "หลังปรับปรุง")}</th></tr></thead><tbody>
      ${v.rows.map((r) => `<tr><td><input type="checkbox" data-seo-f="${r.key}" ${v.wait_days && r.key.startsWith("title") && r.key !== "title_en" ? "" : "checked"}></td><td>${esc(r.label)}</td>
        <td data-notr>${cell(r.key, r.old)}</td><td data-notr>${cell(r.key, r.new)}${r.zh ? `<div class="muted small seo-zh">${Z("中文", "จีน")}：${esc(plain(r.zh)).slice(0, 600)}</div>` : ""}</td></tr>`).join("")}
      </tbody></table>
      <div class="row gap" style="margin-top:10px"><button class="primary" data-seo-apply>${Z("采用勾选的", "ใช้รายการที่เลือก")}</button>
        <button data-seo-discard>${Z("不要这次的优化", "ไม่ใช้ครั้งนี้")}</button></div>`;
  }
  let LIST = [], IDX = 0, ON_DONE = null;
  function show() {
    if (!LIST.length) { MODAL.close(); if (ON_DONE) ON_DONE(); return; }
    IDX = Math.max(0, Math.min(IDX, LIST.length - 1));
    MODAL.open(reviewHtml(LIST[IDX], IDX, LIST.length));
    $("#modal-in").classList.add("wide", "xwide");
  }
  function review(list, onDone) { LIST = list; IDX = 0; ON_DONE = onDone; show(); }
  document.addEventListener("change", (e) => {
    if (e.target.dataset && e.target.dataset.seoAll !== undefined) $$("[data-seo-f]").forEach((x) => (x.checked = e.target.checked));
  });
  document.addEventListener("click", async (e) => {
    const t = e.target.closest && e.target.closest("[data-seo-close],[data-seo-nav],[data-seo-apply],[data-seo-discard],[data-seo-review]");
    if (!t) return;
    if (t.dataset.seoReview !== undefined) {
      if (typeof dirty !== "undefined" && dirty) return toast(Z("先保存商品，再确认优化", "บันทึกสินค้าก่อน"), true);
      const r = await api(`/api/products/${encodeURIComponent(P.id)}/seo`, { json: P });
      if (r.proposal) review([r.proposal], afterEditorApply);
      return;
    }
    if (t.dataset.seoClose !== undefined) { MODAL.close(); if (ON_DONE) ON_DONE(); return; }
    if (t.dataset.seoNav) { IDX += +t.dataset.seoNav; show(); return; }
    const v = LIST[IDX];
    try {
      if (t.dataset.seoDiscard !== undefined) {
        await api(`/api/products/${encodeURIComponent(v.id)}/seo-apply`, { json: { discard: true } });
        toast(Z("已放弃这次的优化", "ยกเลิกแล้ว"));
      } else {
        const fields = $$("[data-seo-f]").filter((x) => x.checked).map((x) => x.dataset.seoF);
        if (!fields.length) return toast(Z("没有勾选任何项", "ยังไม่ได้เลือก"), true);
        const r = await api(`/api/products/${encodeURIComponent(v.id)}/seo-apply`, { json: { fields } });
        toast(Z(`已采用 ${r.changed.length} 项，搜索分 ${r.score}`, `ใช้แล้ว ${r.changed.length} รายการ คะแนน ${r.score}`));
      }
      LIST.splice(IDX, 1);
      show();
    } catch (err) { toast(err.message, true); }
  });
  async function afterEditorApply() {
    if (typeof P === "undefined" || !P) return;
    P = await api(`/api/products/${encodeURIComponent(P.id)}`);
    if (typeof renderEditor === "function") await renderEditor();
  }

  // 编辑页：AI 搜索优化（v2.24：直接生效，关键词扩展合并在里面；可以撤销）
  async function optimizeOne(btn) {
    if (!P.name_zh) return toast(Z("先填写产品名称", "กรอกชื่อสินค้าก่อน"), true);
    if (typeof dirty !== "undefined" && dirty) { try { await saveProduct(true); } catch (err) { return toast(err.message, true); } }
    await busy(btn, async () => {
      const r = await apiJob(`/api/products/${encodeURIComponent(P.id)}/seo-optimize`, { json: { product: P } });
      P = r.product;
      if (typeof dirty !== "undefined") dirty = false;
      if (typeof renderEditor === "function") await renderEditor();
      toast(Z(`搜索优化完成：搜索分 ${r.score_before} → ${r.score_after}，更新了 ${r.changed.length} 项`, `ปรับปรุงแล้ว: คะแนน ${r.score_before} → ${r.score_after}`) +
        (r.kept_titles ? Z(`（这个商品已上架、最近改过标题，这次没换标题，${r.wait_days} 天后再换）`, ` (ไม่เปลี่ยนชื่อ รออีก ${r.wait_days} วัน)`) : "") +
        Z("。不满意可以点「↩ 撤销」", " ไม่พอใจกด「↩ ย้อนกลับ」ได้"), false, 10000);
    });
  }
  async function reviewOne(btn) {
    await busy(btn, async () => {
      const rv = await apiJob(`/api/products/${encodeURIComponent(P.id)}/seo-review`, { json: P });
      P.seo_review = rv;
      renderPanel();
    });
  }
  async function undoOne(btn) {
    if (!confirm(Z("撤销上次的 AI 搜索优化，恢复成优化前的标题、详情、标签和关键词？", "ย้อนกลับเป็นก่อนปรับปรุง?"))) return;
    await busy(btn, async () => {
      const r = await api(`/api/products/${encodeURIComponent(P.id)}/seo-undo`, { json: {} });
      P = r.product;
      if (typeof dirty !== "undefined") dirty = false;
      if (typeof renderEditor === "function") await renderEditor();
      toast(Z("已撤销", "ย้อนกลับแล้ว"));
    });
  }

  // ---------------- 产品库：批量 ----------------
  async function batch(ids, btn) {
    const msg = ids.length
      ? Z(`对选中的 ${ids.length} 个产品做 AI 搜索优化？直接更新标题、关键词、详情和标签（每个产品都可以在编辑页撤销）。`, `ปรับปรุง ${ids.length} สินค้า? อัปเดตทันที (ย้อนกลับได้)`)
      : Z("对搜索分低于 80 的所有产品做 AI 搜索优化？在后台做，直接更新（每个产品都可以在编辑页撤销）。", "ปรับปรุงทุกสินค้าที่คะแนนต่ำกว่า 80? อัปเดตทันที");
    if (!confirm(msg)) return;
    await busy(btn, async () => {
      const r = await apiJob("/api/products/seo-batch", { json: { ids } });
      toast(Z(`已优化 ${r.done.length} / ${r.total} 个${r.skipped && r.skipped.length ? `（${r.skipped.length} 个已上架、最近改过标题的没换标题）` : ""}`, `ปรับปรุงแล้ว ${r.done.length} / ${r.total}`) +
        (r.failed.length ? Z(`；${r.failed.length} 个失败：${r.failed[0].error}`, ` ; ล้มเหลว ${r.failed.length}`) : ""), !!r.failed.length, 10000);
      if (typeof loadLibrary === "function") loadLibrary();
    });
  }
  async function reviewAll() {
    const r = await api("/api/products/seo-proposals");
    if (!r.proposals.length) return toast(Z("没有待确认的优化", "ไม่มีรายการรอยืนยัน"));
    review(r.proposals, () => { if (typeof loadLibrary === "function") loadLibrary(); });
  }
  document.addEventListener("click", (e) => {
    const id = e.target.id;
    if (id === "btn-seo") optimizeOne(e.target);
    if (id === "btn-seo-undo") undoOne(e.target);
    if (id === "btn-seo-review") reviewOne(e.target);
    const use = e.target.dataset && e.target.dataset.seoUse;
    if (use !== undefined && P && P.seo_review) {
      const x = P.seo_review.items[+use];
      if (!x || !x.new_value) return;
      P.copy = P.copy || {};
      P.copy[x.field] = x.new_value;
      x.used = true;
      markDirty();
      if (typeof renderEditor === "function") renderEditor();
      toast(Z(`已改「${x.label}」，检查后点「保存」`, `แก้「${x.label}」แล้ว ตรวจแล้วกดบันทึก`));
    }
    if (id === "btn-seo-batch") batch([], e.target);
    if (id === "btn-seo-sel") batch([...(window.LIB_SEL_IDS ? window.LIB_SEL_IDS() : [])], e.target);
    if (id === "btn-seo-review") reviewAll();
  });

  function badge(p) {
    if (p.seo == null) return "";
    const lv = p.seo >= 80 ? "ok" : p.seo >= 60 ? "warn" : "bad";
    return ` <span class="seo-score sm ${lv}" title="${Z("搜索分", "คะแนนการค้นหา")}">${p.seo}</span>`;
  }

  window.SEO = { renderPanel, schedule, review, badge };
})();
