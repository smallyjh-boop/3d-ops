"use strict";
// 识别测试页（系统 → 识别测试）+ 设置 → 组件与插件 里的「拍照识别」卡片。
// 测试：上传一批实物照片（文件名用 SKU 开头就自动知道正确答案，例如 3DP0001-WH_1.jpg；也可以手填）→ 每张认成什么、排第几、
// 前 1 / 前 3 的准确率；认对 / 认错的都可以一键「设为参考图」（系统越用越准）。另外有「拍照读文字」测试。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const pct = (x) => (x == null ? "—" : Math.round(x * 100) + "%");
  const owner = () => typeof ME === "undefined" || !ME || ME.role === "owner";
  let ROWS = [];

  function statusHtml(s) {
    const r = s.refs || {}, u = s.usage || {}, j = r.job || {}, m = r.model || {};
    return `<table class="grid small"><tbody>
      <tr><td class="nowrap">${Z("识别图", "ภาพอ้างอิง")}</td><td>${Z(`${r.built || 0} / ${r.products || 0} 个产品已建好，共 ${r.refs || 0} 张参考图（${r.skus || 0} 个 SKU）`,
        `สร้างแล้ว ${r.built || 0} / ${r.products || 0} สินค้า รวม ${r.refs || 0} ภาพ (${r.skus || 0} SKU)`)}
        <span class="muted">· ${Z("产品图", "รูปสินค้า")} ${(r.kinds || {}).img || 0} · ${Z("3D 多角度图", "ภาพ 3D หลายมุม")} ${(r.kinds || {}).render || 0} · ${Z("员工确认的照片", "รูปที่พนักงานยืนยัน")} ${(r.kinds || {}).photo || 0}</span>
        ${j.running ? `<div class="warn">${Z(`正在生成… ${j.done}/${j.total}`, `กำลังสร้าง… ${j.done}/${j.total}`)}</div>` : ""}
        ${j.error ? `<div class="bad small" data-notr>${esc(j.error)}</div>` : ""}</td></tr>
      <tr><td class="nowrap">${Z("抠图小模型", "โมเดลตัดพื้นหลังขนาดเล็ก")}</td><td>${m.active ? `<span class="ok">✓ ${Z("在用（照片里的产品抠得准，识别准很多）", "ใช้อยู่ (ตัดสินค้าในรูปได้แม่น จดจำแม่นขึ้นมาก)")}</span>`
        : `<span class="warn">${m.onnxruntime ? Z("没有下载（4.6 MB）：识别准确率会低不少", "ยังไม่ได้ดาวน์โหลด (4.6 MB): ความแม่นยำจะต่ำลงมาก") : Z("缺少 onnxruntime（装「抠图组件」时会装上）", "ไม่มี onnxruntime (จะติดตั้งพร้อม「ส่วนประกอบตัดพื้นหลัง」)")}</span>
          ${owner() && m.onnxruntime ? ` <button class="mini primary" id="rcg-dl">⬇ ${Z("下载", "ดาวน์โหลด")}</button>` : ""}`}</td></tr>
      <tr><td class="nowrap">${Z("AI 看图", "AI ดูรูป")}</td><td>${s.ai && s.ai.available ? `<span class="ok">✓ ${Z("能用", "ใช้ได้")}</span>` : `<span class="muted">${esc(Z(s.ai && s.ai.why || "", I18N.t ? I18N.t(s.ai && s.ai.why || "") : ""))}</span>`}
        <span class="muted"> · ${Z(`今天 ${u.today_ai || 0} 次 / 近 30 天 ${u.d30_ai || 0} 次（每次约 1~2 千 token，大约 0.1~0.3 铢，看你用的 AI 价格）`,
          `วันนี้ ${u.today_ai || 0} ครั้ง / 30 วัน ${u.d30_ai || 0} ครั้ง (ครั้งละประมาณ 1-2 พัน token ราว 0.1-0.3 บาท ขึ้นกับราคา AI ที่ใช้)`)}</span></td></tr>
      <tr><td class="nowrap">${Z("拍照读文字", "ถ่ายรูปอ่านตัวอักษร")}</td><td>${(s.ocr_engines || []).length ? `<span class="ok">✓ ${Z("本地 OCR", "OCR ในเครื่อง")}</span> <span data-notr>${esc(s.ocr_engines.join(", "))}</span>`
        : `<span class="muted">${Z("没有本地 OCR：用 AI 看图读字（NAS 上装 rapidocr_onnxruntime 就能本地读，不花钱）", "ไม่มี OCR ในเครื่อง: ใช้ AI อ่าน (ติดตั้ง rapidocr_onnxruntime บน NAS จะอ่านในเครื่องได้ ไม่เสียเงิน)")}</span>`}</td></tr>
      <tr><td class="nowrap">${Z("近 30 天", "30 วันล่าสุด")}</td><td>${Z(`识别 ${u.d30 || 0} 次；员工确认了 ${u.d30_confirmed || 0} 次，其中第一个就对的 ${u.d30_top1 || 0} 次`,
        `จดจำ ${u.d30 || 0} ครั้ง พนักงานยืนยัน ${u.d30_confirmed || 0} ครั้ง ถูกตั้งแต่อันแรก ${u.d30_top1 || 0} ครั้ง`)}</td></tr>
    </tbody></table>`;
  }

  async function bindStatus(box, again) {
    const dl = box.querySelector("#rcg-dl");
    if (dl) dl.onclick = () => busy(dl, async () => { await api("/api/recog/model/download", { json: {} }); toast(Z("已下载，正在重建识别图", "ดาวน์โหลดแล้ว กำลังสร้างภาพอ้างอิงใหม่")); again(); });
    const b = box.querySelector("#rcg-build");
    if (b) b.onclick = () => busy(b, async () => { await api("/api/recog/build", { json: { force: true } }); toast(Z("开始生成（后台）", "เริ่มสร้าง (เบื้องหลัง)")); setTimeout(again, 1500); });
  }

  // ---------------- 设置卡片 ----------------
  async function settings(box) {
    let s;
    try { s = await api("/api/recog/status"); } catch (e) { box.innerHTML = `<div class="card"><p class="bad small" data-notr>${esc(e.message)}</p></div>`; return; }
    box.innerHTML = `<div class="card"><div class="row between wrap gap"><h3>📷 ${Z("拍照识别（产品 / 文字）", "ถ่ายรูปจดจำ (สินค้า / ตัวอักษร)")}</h3>
        <a class="btn" href="#" id="rcg-go">${Z("打开识别测试", "เปิดหน้าทดสอบการจดจำ")}</a></div>
      <p class="small">${Z("手机页、App、打包核对的 📷 按钮：拍实物找产品 / SKU（本地比对 + AI 看图），拍货位牌、面单读字。开关、AI 用量、把握线在上面的「拍照识别」设置里。",
        "ปุ่ม 📷 ในหน้ามือถือ แอป และตรวจแพ็ก: ถ่ายของจริงหาสินค้า / SKU (เทียบในระบบ + AI ดูรูป) ถ่ายป้ายตำแหน่ง ใบปะหน้าเพื่ออ่านตัวอักษร เปิด/ปิด จำนวนการใช้ AI และเกณฑ์ความมั่นใจอยู่ในการตั้งค่า「ถ่ายรูปจดจำ」ด้านบน")}</p>
      ${statusHtml(s)}</div>`;
    box.querySelector("#rcg-go").onclick = (e) => { e.preventDefault(); goTab("recog_test"); };
    bindStatus(box, () => settings(box));
  }

  // ---------------- 识别测试页 ----------------
  async function show() {
    const root = $("#rcg-page");
    if (!root) return;
    let s;
    try { s = await api("/api/recog/status"); } catch (e) { root.innerHTML = `<div class="card"><p class="bad" data-notr>${esc(e.message)}</p></div>`; return; }
    root.innerHTML = `<div class="card"><div class="row between wrap gap"><h3>📷 ${Z("识别测试：拍实物照片，看系统认得准不准", "ทดสอบการจดจำ: ถ่ายรูปของจริง ดูว่าระบบจำได้แม่นไหม")}</h3>
        <button class="mini" id="rcg-build">🔄 ${Z("重新生成识别图", "สร้างภาพอ้างอิงใหม่")}</button></div>
      ${statusHtml(s)}</div>
      <div class="card"><h3>📦 ${Z("拍照找产品", "ถ่ายรูปหาสินค้า")}</h3>
      <p class="small">${Z("选一批实物照片（一张一个产品，像员工平时拍的那样）。文件名用 SKU 开头（例如 3DP0001-WH_1.jpg）就自动知道正确答案，也可以在表格里填。认对 / 认错的都可以点「设为参考图」：以后就更准。",
        "เลือกรูปของจริงหลายรูป (รูปละหนึ่งสินค้า ถ่ายแบบที่พนักงานถ่ายปกติ) ถ้าชื่อไฟล์ขึ้นต้นด้วย SKU (เช่น 3DP0001-WH_1.jpg) ระบบจะรู้คำตอบที่ถูกเอง หรือกรอกในตารางก็ได้ กด「ตั้งเป็นภาพอ้างอิง」ได้ทั้งที่ถูกและผิด ต่อไปจะแม่นขึ้น")}</p>
      <div class="row gap wrap"><label class="filebtn mini-btn">📁 ${Z("选照片（可以多选）", "เลือกรูป (เลือกได้หลายรูป)")}<input type="file" id="rcg-files" accept="image/*" multiple hidden></label>
        <label class="small"><input type="checkbox" id="rcg-ai" ${s.ai && s.ai.available ? "checked" : "disabled"}> ${Z("也用 AI 看图（每张算一次 AI 调用）", "ใช้ AI ดูรูปด้วย (นับเป็นการใช้ AI รูปละครั้ง)")}</label>
        <button class="mini" id="rcg-clear">${Z("清空结果", "ล้างผล")}</button></div>
      <div id="rcg-sum" class="row gap wrap" style="margin:8px 0"></div>
      <div style="overflow:auto"><table class="grid small" id="rcg-tbl"><thead><tr><th>${Z("照片", "รูป")}</th><th>${Z("正确的 SKU", "SKU ที่ถูก")}</th>
        <th>${Z("系统认成（前 3）", "ระบบจำเป็น (3 อันดับแรก)")}</th><th>${Z("结果", "ผล")}</th><th>${Z("用时", "เวลา")}</th><th></th></tr></thead><tbody></tbody></table></div></div>
      <div class="card"><h3>🔤 ${Z("拍照读文字（货位牌 / 面单 / 标签）", "ถ่ายรูปอ่านตัวอักษร (ป้ายตำแหน่ง / ใบปะหน้า / ฉลาก)")}</h3>
        <div class="row gap wrap"><label class="filebtn mini-btn">📁 ${Z("选照片", "เลือกรูป")}<input type="file" id="rcg-ocr" accept="image/*" multiple hidden></label>
        <span class="small muted">${Z("或者输入一段文字试试容错：", "หรือพิมพ์ข้อความลองดูการแก้คำผิด:")}</span>
        <input id="rcg-txt" placeholder="A1-O2-O3 / 3DPOOO1 WH" style="width:220px" data-notr><button class="mini" id="rcg-txt-go">${Z("认", "ตรวจ")}</button></div>
        <div id="rcg-ocr-out" style="margin-top:8px"></div></div>
      <div class="card"><div class="row between wrap gap"><h3>🧠 ${Z("员工确认过的参考照片", "รูปอ้างอิงที่พนักงานยืนยันแล้ว")}</h3>
        <span class="row gap"><input id="rcg-lq" placeholder="${Z("SKU 或产品编号（空 = 全部）", "SKU หรือรหัสสินค้า (ว่าง = ทั้งหมด)")}" style="width:220px" data-notr><button class="mini" id="rcg-lgo">${Z("查看", "ดู")}</button></span></div>
        <p class="small muted">${Z("员工在手机上点「就是它」的照片会变成参考图。认错存错了的：删掉，或者改到正确的 SKU（参考图马上重算）。",
          "รูปที่พนักงานกด「ใช่อันนี้」บนมือถือจะกลายเป็นภาพอ้างอิง ถ้าบันทึกผิด: ลบ หรือเปลี่ยนเป็น SKU ที่ถูก (คำนวณภาพอ้างอิงใหม่ทันที)")}</p>
        <div id="rcg-learned"></div></div>`;
    bindStatus(root, show);
    const lg = () => window.RECOG && RECOG.learned($("#rcg-learned"), $("#rcg-lq").value.trim());
    $("#rcg-lgo").onclick = lg;
    $("#rcg-lq").onkeydown = (e) => { if (e.key === "Enter") lg(); };
    lg();
    $("#rcg-files").onchange = async (e) => {
      const files = [...e.target.files]; e.target.value = "";
      for (const f of files) await testOne(f);
    };
    $("#rcg-clear").onclick = () => { ROWS = []; render(); };
    $("#rcg-ocr").onchange = async (e) => {
      const files = [...e.target.files]; e.target.value = "";
      const out = $("#rcg-ocr-out");
      for (const f of files) {
        const fd = new FormData(); fd.append("photo", f, f.name); fd.append("src", "test");
        let r;
        try { r = await api("/api/recog/ocr", { method: "POST", body: fd }); } catch (er) { out.insertAdjacentHTML("afterbegin", `<p class="bad small" data-notr>${esc(f.name)}: ${esc(er.message)}</p>`); continue; }
        out.insertAdjacentHTML("afterbegin", `<div class="row gap" style="align-items:flex-start;border-bottom:1px solid #eee;padding:6px 0">
          <img src="${URL.createObjectURL(f)}" style="width:120px;max-height:90px;object-fit:contain">
          <div class="small"><div><b>${Z("条码", "บาร์โค้ด")}</b> <span data-notr>${esc((r.barcodes || []).join(", ") || "—")}</span></div>
          <div><b>${Z("文字", "ข้อความ")}</b> (<span data-notr>${esc(r.engine || "—")}</span>) <span data-notr>${esc((r.lines || []).join(" / ") || "—")}</span></div>
          <div><b>${Z("认成", "จำเป็น")}</b> ${(r.candidates || []).slice(0, 3).map((c) => `<span class="pill" data-notr>${esc(c.code)} ${pct(c.conf)}</span>`).join(" ") || "—"}</div>
          ${r.error ? `<div class="muted" data-notr>${esc(r.error)}</div>` : ""}</div></div>`);
      }
    };
    $("#rcg-txt-go").onclick = async () => {
      const v = $("#rcg-txt").value.trim();
      if (!v) return;
      try {
        const r = await api(`/api/recog/text?q=${encodeURIComponent(v)}`);
        $("#rcg-ocr-out").insertAdjacentHTML("afterbegin", `<p class="small"><span data-notr>${esc(v)}</span> → ${(r.candidates || []).map((c) => `<span class="pill" data-notr>${esc(c.code)} ${pct(c.conf)}</span>`).join(" ") || Z("没有像的码", "ไม่มีโค้ดที่คล้าย")}</p>`);
      } catch (er) { toast(er.message, true); }
    };
    render();
  }

  async function testOne(f, truth) {
    const fd = new FormData();
    fd.append("photo", f, f.name); fd.append("ai", $("#rcg-ai") && $("#rcg-ai").checked ? "1" : "0");
    if (truth) fd.append("truth", truth);
    const row = { name: f.name, url: URL.createObjectURL(f), file: f, busy: true };
    ROWS.unshift(row); render();
    try { Object.assign(row, await api("/api/recog/test", { method: "POST", body: fd })); } catch (e) { row.error = e.message; }
    row.busy = false; render();
  }

  function render() {
    const tb = $("#rcg-tbl tbody");
    if (!tb) return;
    const done = ROWS.filter((r) => !r.busy && !r.error && r.truth);
    const n1 = done.filter((r) => r.rank === 1).length, n3 = done.filter((r) => r.rank && r.rank <= 3).length;
    $("#rcg-sum").innerHTML = ROWS.length ? `<span class="pill">${Z("照片", "รูป")} ${ROWS.length}</span>
      <span class="pill">${Z("有正确答案的", "มีคำตอบที่ถูก")} ${done.length}</span>
      ${done.length ? `<span class="pill ok">${Z("第一个就对", "ถูกตั้งแต่อันแรก")} ${pct(n1 / done.length)}</span><span class="pill">${Z("前 3 里有", "อยู่ใน 3 อันดับแรก")} ${pct(n3 / done.length)}</span>` : ""}` : "";
    tb.innerHTML = ROWS.map((r, k) => {
      const c = (r.candidates || []).slice(0, 3);
      const res = r.busy ? `<span class="muted">${Z("识别中…", "กำลังจดจำ…")}</span>` : r.error ? `<span class="bad" data-notr>${esc(r.error)}</span>`
        : !r.truth ? `<span class="muted">${Z("没有正确答案", "ไม่มีคำตอบที่ถูก")}</span>`
        : r.rank === 1 ? `<b class="ok">✓ ${Z("对", "ถูก")}</b>` : r.rank ? `<b class="warn">${Z(`第 ${r.rank} 个`, `อันดับ ${r.rank}`)}</b>` : `<b class="bad">✗ ${Z("没认出", "จำไม่ได้")}</b>`;
      return `<tr><td><img src="${r.url}" style="width:84px;height:84px;object-fit:cover;border-radius:6px"><div class="small muted" data-notr>${esc(r.name)}</div></td>
        <td><input data-truth="${k}" value="${esc(r.truth || "")}" placeholder="SKU" style="width:130px" data-notr>${r.truth_info ? `<div class="small" data-notr>${esc(r.truth_info.name_zh)} ${esc(r.truth_info.opt1_zh || "")}</div>` : ""}</td>
        <td>${c.map((x) => `<div class="row gap" style="align-items:center;margin:2px 0">${x.img ? `<img src="${esc(x.img)}" style="width:40px;height:40px;object-fit:contain">` : ""}
          <span data-notr><b>${esc(x.sku)}</b> ${esc(x.opt1_zh || "")}</span> <span class="pill">${pct(x.conf)}</span>${x.ai ? ' <span class="pill">AI</span>' : ""}</div>`).join("")}
          ${r.ai && r.ai.used && !r.ai.ok ? `<div class="small muted" data-notr>AI: ${esc(r.ai.why || "")}</div>` : ""}</td>
        <td>${res}</td><td class="small">${r.ms ? (r.ms / 1000).toFixed(1) + "s" : ""}</td>
        <td>${r.rid && (r.truth || c.length) ? `<button class="mini" data-learn="${k}">${Z("设为参考图", "ตั้งเป็นภาพอ้างอิง")}</button>` : ""}${r.learned ? ` <span class="ok">✓</span>` : ""}</td></tr>`;
    }).join("");
    tb.querySelectorAll("[data-truth]").forEach((el) => (el.onchange = () => {
      const r = ROWS[+el.dataset.truth];
      const v = el.value.trim();
      if (!v || !r.file) return;
      ROWS.splice(+el.dataset.truth, 1);
      testOne(r.file, v);
    }));
    tb.querySelectorAll("[data-learn]").forEach((el) => (el.onclick = () => busy(el, async () => {
      const r = ROWS[+el.dataset.learn];
      const sku = r.truth || (r.candidates && r.candidates[0] && r.candidates[0].sku);
      const d = await api("/api/recog/confirm", { json: { rid: r.rid, sku } });
      r.learned = d.learned; toast(Z(`已设为 ${sku} 的参考图`, `ตั้งเป็นภาพอ้างอิงของ ${sku} แล้ว`)); render();
    })));
  }

  window.MODS = window.MODS || {};
  window.MODS.recog = Object.assign(window.MODS.recog || {}, { show, settings });
})();
