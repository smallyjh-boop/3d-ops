"use strict";
// v2.50.1 选品采用的产品（P.source.source === "curate"）在编辑页上：
//   · 来源卡片里「模型文件」：⬇ 从原站下载模型文件 / 上传模型文件、已下载的文件（下载到电脑、删除）、下载状态、扩展不在线的提醒
//   · ③ 3D 模型：还没有模型文件时也一直显示一块「还没有模型文件」+ 同样的按钮；文件到了第一个 STL / 3MF 自动当 3D 模型，这里自动刷新预览
//   · ④ 图片：还在用原站图片时提醒「原站图片，可能有水印……」
// 接口都是选品模块的（/api/cur/products/<编号>/…）；选品模块关着时什么都不显示。
(function () {
  const Z = (zh, th) => (window.I18N && I18N.lang === "th" ? th : zh);
  let ST = null, PID = null, TIMER = null, SIG = "";
  const hasP = () => typeof P !== "undefined" && !!P;      // P / dirty / VIEWER_PID 是内核的全局 let（不在 window 上）
  const isCur = () => hasP() && !!(P.source && P.source.source === "curate");
  const kb = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
  // 扩展不在线的提醒：只在还有要从原站下载 / 读的（或一个文件都没有）时显示
  const needExt = (f) => !!(f.queued || f.downloading || f.collect === "waiting" || f.collect === "running" || !f.ok);
  const extLine = (s) => (s && s.status && s.status.ext && !s.status.ext.online && needExt(s.status)
    ? `<div class="cur-ext-off small">⚠ ${Z("要有一台装了扩展、登录了原站的 Chrome 开着，才能从原站下载（现在没有在线的扩展）", "ต้องมี Chrome ที่ติดตั้งส่วนขยายและล็อกอินเว็บต้นทางเปิดอยู่จึงจะดาวน์โหลดได้ (ตอนนี้ไม่มีส่วนขยายออนไลน์)")}</div>` : "");

  function statusText(s) {
    if (!s) return "";
    const f = s.status || {};
    const parts = [];
    if (f.ok) parts.push(`<span class="ok">✓ ${Z(`已下载 ${f.ok} 个`, `ดาวน์โหลดแล้ว ${f.ok} ไฟล์`)}</span>`);
    if (f.downloading) parts.push(`<span class="info-t">⏳ ${Z(`下载中 ${f.downloading} 个`, `กำลังดาวน์โหลด ${f.downloading} ไฟล์`)}</span>`);
    if (f.queued) parts.push(`<span class="info-t">⏳ ${f.ext && f.ext.online ? Z(`排队下载 ${f.queued} 个`, `รอดาวน์โหลด ${f.queued} ไฟล์`) : Z(`等扩展下载 ${f.queued} 个`, `รอส่วนขยายดาวน์โหลด ${f.queued} ไฟล์`)}</span>`);
    if (f.failed) parts.push(`<span class="bad">✕ ${Z(`失败 ${f.failed} 个`, `ไม่สำเร็จ ${f.failed} ไฟล์`)}</span>${(f.errors || []).length ? ` <span class="muted" data-notr>${esc(f.errors[0].slice(0, 140))}</span>` : ""}`);
    if (!parts.length) {
      if (f.collect === "waiting" || f.collect === "running") parts.push(`<span class="info-t">⏳ ${Z("等扩展读原站详情页（读到文件链接后自动下载）", "รอส่วนขยายอ่านหน้ารายละเอียด (เจอลิงก์ไฟล์แล้วจะดาวน์โหลดอัตโนมัติ)")}</span>`);
      else if (f.links) parts.push(`<span class="muted">${Z(`原站有 ${f.links} 个文件还没下载`, `เว็บต้นทางมี ${f.links} ไฟล์ยังไม่ได้ดาวน์โหลด`)}</span>`);
      else parts.push(`<span class="muted">${Z("还没有模型文件", "ยังไม่มีไฟล์โมเดล")}</span>`);
    }
    return parts.join(" · ");
  }
  const buttons = () => `<button class="mini primary-lite" data-cf-dl>⬇ ${Z("从原站下载模型文件", "ดาวน์โหลดไฟล์โมเดลจากเว็บต้นทาง")}</button>
    <label class="filebtn mini">⬆ ${Z("上传模型文件", "อัปโหลดไฟล์โมเดล")}<input type="file" data-cf-up multiple accept=".stl,.3mf,.zip,.obj,.step,.stp" hidden></label>`;

  function filesBox() {
    const s = ST;
    if (!s) return `<div class="small muted">${Z("正在读取模型文件…", "กำลังอ่านไฟล์โมเดล…")}</div>`;
    const list = (s.files || []).map((f) => `<div class="cur-fl"><span data-notr>📄 ${esc(f.orig_name || f.name)}</span> <span class="muted small">${kb(f.bytes || 0)}</span>
      ${f.current ? `<span class="pill tag-pill">${Z("3D 模型", "โมเดล 3D")}</span>` : ""}
      <a class="mini btn" href="/files/${encodeURIComponent(P.id)}/source_files/${encodeURIComponent(f.name)}" download title="${esc(Z("下载到电脑", "ดาวน์โหลดลงเครื่อง"))}">⬇</a>
      ${f.current ? "" : `<button class="mini ghost" data-cf-del="${esc(f.name)}" title="${esc(Z("删除这个文件（挪到历史，可以找回）", "ลบไฟล์นี้ (ย้ายไปประวัติ กู้คืนได้)"))}">✕</button>`}</div>`).join("");
    return `<div class="cur-files"><div class="row between wrap gap"><b class="small">${Z("模型文件", "ไฟล์โมเดล")}</b><div class="row gap wrap">${buttons()}</div></div>
      <div class="small">${statusText(s)}</div>${extLine(s)}${list ? `<div class="cur-flist">${list}</div>` : ""}</div>`;
  }

  function modelBox() {
    const el = $("#model-empty");
    if (!el) return;
    if (!el.dataset.orig) el.dataset.orig = el.innerHTML;
    if (!isCur() || P.model) {
      el.innerHTML = el.dataset.orig; el.classList.remove("cur-model-empty");
      el.classList.toggle("muted", true); el.classList.toggle("small", true);
      return;
    }
    el.classList.add("cur-model-empty"); el.classList.remove("muted", "small");
    el.innerHTML = `<div class="cur-me-in"><div class="cur-me-ico">🧊</div><div class="cur-me-t">${Z("还没有模型文件", "ยังไม่มีไฟล์โมเดล")}</div>
      <div class="small">${ST ? statusText(ST) : ""}</div>
      <div class="small muted">${Z("文件到了以后第一个 STL / 3MF 自动当 3D 模型，这里会自动显示 360° 预览、估算克数和打印时长。", "พอไฟล์มาถึง STL / 3MF ไฟล์แรกจะเป็นโมเดล 3D อัตโนมัติ และแสดงพรีวิว 360° ประมาณกรัมและเวลาพิมพ์ที่นี่")}</div>
      <div class="row gap wrap" style="justify-content:center;margin-top:8px">${buttons()}</div>${extLine(ST)}</div>`;
  }

  function imagesWarn() {
    const box = $("#img-src-warn");
    if (!box || !hasP()) return;
    const n = (P.images || []).filter((i) => i.from === "source" && !i.edited).length;
    box.innerHTML = n ? `<div class="warnbox small">⚠ ${Z(`有 ${n} 张是原站图片，可能有水印，建议换成自己拍的或去水印（「🎨 修图」→ 去水印）。原站图片也可能有版权，上架检查会提醒。`,
      `มี ${n} รูปเป็นรูปจากเว็บต้นทาง อาจมีลายน้ำ แนะนำให้เปลี่ยนเป็นรูปที่ถ่ายเองหรือลบลายน้ำ (「🎨 แต่งรูป」→ ลบลายน้ำ) รูปจากเว็บต้นทางอาจมีลิขสิทธิ์ การตรวจก่อนลงขายจะเตือน`)}</div>` : "";
    document.querySelectorAll("#img-grid .img-card").forEach((card) => {
      const im = (P.images || []).find((i) => i.raw === card.dataset.raw);
      const tagbox = card.querySelector("div");
      if (im && im.from === "source" && !im.edited && tagbox && !tagbox.querySelector(".src-img-tag")) {
        tagbox.insertAdjacentHTML("afterbegin", `<span class="tag src-img-tag" title="${esc(Z("原站图片，可能有水印", "รูปจากเว็บต้นทาง อาจมีลายน้ำ"))}">${Z("原站图", "รูปต้นทาง")}</span>`);
      }
    });
  }

  function paint() {
    const fb = $("#ed-curfiles");
    if (fb) fb.innerHTML = isCur() ? filesBox() : "";
    modelBox();
  }

  async function load(force) {
    if (!isCur()) { ST = null; PID = null; stopPoll(); modelBox(); return; }
    if (PID !== P.id) { ST = null; PID = P.id; SIG = ""; }
    paint();
    try {
      const s = await api(`/api/cur/products/${encodeURIComponent(P.id)}/files`);
      if (!hasP() || P.id !== PID) return;
      const sig = JSON.stringify([s.files.map((f) => f.name), s.model, s.status.ok, s.updated_at]);
      const changed = SIG && sig !== SIG;
      ST = s; SIG = sig;
      if (changed && !force) await refreshProduct(s);
      paint();
      const st = s.status || {};
      const busyNow = st.queued || st.downloading || st.collect === "waiting" || st.collect === "running" || (s.files.length && !s.model);
      if (busyNow) startPoll(); else stopPoll();
    } catch (e) { ST = null; paint(); stopPoll(); }
  }

  // 文件到了 / 3D 模型设好了：没有没保存的修改就整个重新载入；有的话只换 3D 模型和文件列表（不丢正在改的内容）
  async function refreshProduct(s) {
    const fresh = await api(`/api/products/${encodeURIComponent(P.id)}`);
    if (!hasP() || fresh.id !== P.id) return;
    if (!dirty) {
      P = fresh;
      if (typeof VIEWER_PID !== "undefined") VIEWER_PID = null;
      await renderEditor();
    } else {
      P.model = fresh.model; P.model_lib = fresh.model_lib; P.source_files = fresh.source_files; P.edit_rev = fresh.edit_rev;
      window.dispatchEvent(new CustomEvent("model-changed", { detail: P.id }));
    }
    if (s.model) toast(Z("模型文件到了，3D 预览已更新", "ไฟล์โมเดลมาแล้ว อัปเดตพรีวิว 3D แล้ว"));
  }

  function startPoll() {
    if (TIMER) return;
    TIMER = setInterval(() => {
      const tab = $("#tab-edit");
      if (!hasP() || P.id !== PID || !tab || tab.classList.contains("hidden")) return stopPoll();
      load();
    }, 12000);
  }
  function stopPoll() { if (TIMER) { clearInterval(TIMER); TIMER = null; } }

  document.addEventListener("click", async (e) => {
    if (!e.target.closest("#ed-curfiles, #model-empty")) return;
    const dl = e.target.closest("[data-cf-dl]"), del = e.target.closest("[data-cf-del]");
    if (dl) {
      return busy(dl, async () => {
        const r = await api(`/api/cur/products/${encodeURIComponent(P.id)}/download`, { json: {} });
        toast(r.queued ? Z(`已排队 ${r.queued} 个文件，扩展会用原站的登录状态下载`, `เข้าคิว ${r.queued} ไฟล์ ส่วนขยายจะดาวน์โหลดด้วยการล็อกอินเว็บต้นทาง`)
          : r.busy ? Z("已经在下载了", "กำลังดาวน์โหลดอยู่แล้ว")
          : Z("还没有文件链接：已让扩展重新读原站详情页，读到后自动下载", "ยังไม่มีลิงก์ไฟล์: ให้ส่วนขยายอ่านหน้ารายละเอียดใหม่ เจอแล้วจะดาวน์โหลดอัตโนมัติ"));
        if (r.status && r.status.ext && !r.status.ext.online) toast(Z("现在没有在线的扩展：要有一台装了扩展、登录了原站的 Chrome 开着", "ตอนนี้ไม่มีส่วนขยายออนไลน์: ต้องมี Chrome ที่ติดตั้งส่วนขยายและล็อกอินเว็บต้นทางเปิดอยู่"), true);
        await load(true); startPoll();
      });
    }
    if (del) {
      if (!confirm(Z("删除这个模型文件？（挪到产品的历史文件夹，可以找回；以后也能再从原站下载）", "ลบไฟล์โมเดลนี้? (ย้ายไปโฟลเดอร์ประวัติ กู้คืนได้)"))) return;
      return busy(del, async () => { await api(`/api/cur/products/${encodeURIComponent(P.id)}/files/delete`, { json: { name: del.dataset.cfDel } }); await load(true); });
    }
  });
  document.addEventListener("change", async (e) => {
    const inp = e.target.closest("[data-cf-up]");
    if (!inp || !inp.files.length || !hasP()) return;
    const fd = new FormData();
    [...inp.files].forEach((f) => fd.append("file", f));
    try {
      if (dirty) await saveProduct(true);
      await busyToast(Z("正在上传模型文件…", "กำลังอัปโหลดไฟล์โมเดล…"), () => api(`/api/cur/products/${encodeURIComponent(P.id)}/upload`, { method: "POST", body: fd }));
      toast(Z("已上传，正在分析（尺寸、克数、时长、规格），第一个 STL / 3MF 自动当 3D 模型", "อัปโหลดแล้ว กำลังวิเคราะห์ ไฟล์ STL / 3MF แรกจะเป็นโมเดล 3D อัตโนมัติ"));
      SIG = "-"; await load(); startPoll();
    } catch (err) { toast(err.message, true); }
    inp.value = "";
  });
  window.addEventListener("model-changed", () => { if (isCur()) load(true); });

  window.CURSRC = { render: () => { paint(); load(true); }, images: imagesWarn };
})();
