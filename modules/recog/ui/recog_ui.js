"use strict";
// 拍照识别的公用界面（手机页 /m、电脑网页、安卓 App 里都用这一份）：
//   RECOG.menu({src, onPick})     📷 → 选「拍照识别产品」或「拍照读文字」
//   RECOG.product({src, onPick})  拍照 → /api/recog/identify → 前 3 个（带图、把握）→ 点「就是它」→ onPick(SKU)；「都不是」→ 手动搜
//   RECOG.ocr({src, onPick})      拍照 → /api/recog/ocr → 认出的码 → 点一下 → onPick(码)
//   RECOG.text(文字) → Promise<码 | null>   App 的 ML Kit 认出来的文字 → 系统里的码（没把握时让人点）
// 自己画一个底部弹层（.rcg-*），不依赖页面的样式；中文 / 泰文跟着页面语言。
(function () {
  if (window.RECOG) return;
  const TH = () => { try { if (window.I18N && I18N.lang) return I18N.lang === "th"; return localStorage.getItem("ui_lang") === "th"; } catch { return false; } };
  const Z = (zh, th) => (TH() ? th : zh);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (x) => Math.round((x || 0) * 100) + "%";
  const TYPE = {
    location: ["货位", "ตำแหน่ง"], "location?": ["货位（系统里没有）", "ตำแหน่ง (ไม่มีในระบบ)"], shelf: ["货架", "ชั้นวาง"], zone: ["区", "โซน"],
    order: ["订单号", "เลขออเดอร์"], tracking: ["快递单号", "เลขพัสดุ"], sku: ["SKU", "SKU"], item: ["物品编码", "รหัสสิ่งของ"],
  };
  const typeName = (t) => (TYPE[t] ? Z(TYPE[t][0], TYPE[t][1]) : t);

  // ---------------- 样式 + 弹层 ----------------
  function css() {
    if (document.getElementById("rcg-css")) return;
    const s = document.createElement("style");
    s.id = "rcg-css";
    s.textContent = `
.rcg-ov{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:10050;display:flex;align-items:flex-end;justify-content:center}
.rcg-box{background:#fff;color:#111;width:100%;max-width:560px;max-height:92vh;overflow:auto;border-radius:16px 16px 0 0;padding:14px 14px calc(14px + env(safe-area-inset-bottom));box-shadow:0 -4px 24px rgba(0,0,0,.25);font:15px/1.4 system-ui,-apple-system,"Segoe UI",sans-serif}
@media (min-width:700px){.rcg-ov{align-items:center}.rcg-box{border-radius:14px}}
.rcg-box h3{margin:0 0 8px;font-size:18px}
.rcg-row{display:flex;gap:8px;align-items:center}
.rcg-col{display:flex;flex-direction:column;gap:8px}
.rcg-btn{border:1px solid #cbd5e1;background:#f8fafc;color:#111;border-radius:10px;padding:12px 14px;font-size:16px;cursor:pointer;text-align:center}
.rcg-btn.pri{background:#2563eb;border-color:#2563eb;color:#fff;font-weight:600}
.rcg-btn.big{padding:16px;font-size:17px}
.rcg-btn.sm{padding:6px 10px;font-size:14px}
.rcg-q{width:96px;height:96px;object-fit:cover;border-radius:10px;border:1px solid #e2e8f0;flex:none}
.rcg-c{display:flex;gap:10px;align-items:center;border:2px solid #e2e8f0;border-radius:12px;padding:8px;cursor:pointer;background:#fff;width:100%;text-align:left;color:#111;font:inherit}
.rcg-c.top{border-color:#16a34a;background:#f0fdf4}
.rcg-c img,.rcg-c .noimg{width:72px;height:72px;object-fit:contain;border-radius:8px;background:#f1f5f9;flex:none}
.rcg-c .g{flex:1;min-width:0}
.rcg-c .sku{font-family:ui-monospace,Menlo,monospace;font-weight:700}
.rcg-c .nm{font-size:13px;color:#475569;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rcg-bar{height:6px;border-radius:3px;background:#e2e8f0;margin-top:4px;overflow:hidden}
.rcg-bar i{display:block;height:100%;background:#16a34a}
.rcg-bar.lo i{background:#f59e0b}
.rcg-pc{font-weight:700;font-size:15px;min-width:44px;text-align:right}
.rcg-muted{color:#64748b;font-size:13px}
.rcg-warn{background:#fef3c7;border-radius:8px;padding:6px 10px;font-size:14px}
.rcg-in{width:100%;box-sizing:border-box;font-size:16px;padding:10px;border:1px solid #cbd5e1;border-radius:10px}
.rcg-spin{display:inline-block;width:18px;height:18px;border:3px solid #cbd5e1;border-top-color:#2563eb;border-radius:50%;animation:rcgs 1s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes rcgs{to{transform:rotate(360deg)}}
.rcg-tag{display:inline-block;font-size:11px;background:#e0e7ff;color:#3730a3;border-radius:6px;padding:0 5px;margin-left:4px;vertical-align:middle}
#recog-btn{flex:none}`;
    document.head.appendChild(s);
  }
  let ov = null;
  function open(html) {
    css();
    if (!ov) {
      ov = document.createElement("div");
      ov.className = "rcg-ov";
      ov.id = "rcg-ov";
      ov.innerHTML = '<div class="rcg-box" id="rcg-box"></div>';
      ov.addEventListener("click", (e) => { if (e.target === ov || e.target.closest("[data-rcg-close]")) close(); });
      document.body.appendChild(ov);
    }
    ov.style.display = "flex";
    const b = ov.querySelector("#rcg-box");
    b.innerHTML = html;
    return b;
  }
  function close() { if (ov) { ov.style.display = "none"; ov.querySelector("#rcg-box").innerHTML = ""; } }

  async function call(url, opts = {}) {
    const o = { credentials: "same-origin", ...opts };
    if (o.json !== undefined) { o.method = "POST"; o.headers = { "Content-Type": "application/json" }; o.body = JSON.stringify(o.json); delete o.json; }
    let r;
    try { r = await fetch(url, o); } catch { throw new Error(Z("连不上服务器", "เชื่อมต่อเซิร์ฟเวอร์ไม่ได้")); }
    let d = null;
    try { d = await r.json(); } catch { /* 不是 JSON */ }
    if (!r.ok || (d && d.error)) {
      let m = (d && d.error) || `HTTP ${r.status}`;
      if (TH() && window.I18N && I18N.t) m = I18N.t(m);
      throw new Error(m);
    }
    return d;
  }

  // 拍照（手机直接开相机；电脑选文件）→ 压到 1280 像素的 JPEG（上传快）
  function pick() {
    return new Promise((done) => {
      let inp = document.getElementById("rcg-file");
      if (!inp) {
        inp = document.createElement("input");
        inp.type = "file"; inp.accept = "image/*"; inp.id = "rcg-file"; inp.hidden = true;
        inp.setAttribute("capture", "environment");
        inp.addEventListener("click", (e) => e.stopPropagation());
        document.body.appendChild(inp);
      }
      inp.value = "";
      inp.onchange = () => { const f = inp.files && inp.files[0]; inp.onchange = null; done(f || null); };
      inp.click();
    });
  }
  async function shrink(file) {
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
      const s = Math.min(1, 1280 / Math.max(bmp.width, bmp.height));
      const c = document.createElement("canvas");
      c.width = Math.round(bmp.width * s); c.height = Math.round(bmp.height * s);
      c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
      const blob = await new Promise((ok) => c.toBlob(ok, "image/jpeg", 0.88));
      return blob || file;
    } catch { return file; }
  }
  function beep(kind) { try { if (window.SCAN && SCAN.feedback) SCAN.feedback(kind); } catch { /* 忽略 */ } }

  // ---------------- 📷 选哪一种 ----------------
  function menu(o = {}) {
    const b = open(`<h3>📷 ${Z("拍照识别", "ถ่ายรูปจดจำ")}</h3>
      <div class="rcg-col">
        <button class="rcg-btn pri big" data-k="p">📦 ${Z("拍照识别产品", "ถ่ายรูปหาสินค้า")}<div class="rcg-muted" style="color:#dbeafe">${Z("没有条码的产品：拍实物，系统找出是哪个 SKU", "สินค้าไม่มีบาร์โค้ด: ถ่ายรูปของจริง ระบบหาว่าเป็น SKU ไหน")}</div></button>
        <button class="rcg-btn big" data-k="t">🔤 ${Z("拍照读文字", "ถ่ายรูปอ่านตัวอักษร")}<div class="rcg-muted">${Z("货位牌、面单、标签上的字（条码坏了也行）", "ป้ายตำแหน่ง ใบปะหน้า ฉลาก (บาร์โค้ดเสียก็ได้)")}</div></button>
        <button class="rcg-btn" data-rcg-close>${Z("取消", "ยกเลิก")}</button></div>`);
    b.querySelector('[data-k="p"]').onclick = () => product(o);
    b.querySelector('[data-k="t"]').onclick = () => ocr(o);
  }

  // ---------------- 拍照找产品 ----------------
  function candHtml(c, k, top, bare) {
    const lo = (c.conf || 0) < 0.6;
    return `<button class="rcg-c ${top ? "top" : ""}" data-sku="${esc(c.sku)}" data-k="${k}">
      ${c.img ? `<img src="${esc(c.img)}" alt="" loading="lazy">` : '<span class="noimg"></span>'}
      <span class="g"><span class="sku" data-notr>${esc(c.sku)}</span>${c.ai ? `<span class="rcg-tag">AI</span>` : ""}
        <div class="nm" data-notr>${esc(TH() && c.title_th ? c.title_th : c.name_zh)}</div>
        <div class="nm" data-notr>${esc([c.opt1_zh, c.opt2_zh].filter(Boolean).join(" · "))}</div>
        ${bare ? "" : `<div class="rcg-bar ${lo ? "lo" : ""}"><i style="width:${pct(c.conf)}"></i></div>`}</span>
      ${bare ? "" : `<span class="rcg-pc">${pct(c.conf)}</span>`}</button>`;
  }
  async function product(o = {}) {
    const f = o.file || await pick();
    if (!f) { close(); return; }
    const url = URL.createObjectURL(f);
    open(`<div class="rcg-row"><img class="rcg-q" src="${url}" alt=""><div><span class="rcg-spin"></span>${Z("正在识别…", "กำลังจดจำ…")}
      <div class="rcg-muted">${Z("先在本地比对，再请 AI 看图（几秒钟）", "เทียบในระบบก่อน แล้วให้ AI ดูรูป (ไม่กี่วินาที)")}</div></div></div>`);
    let r;
    try {
      const fd = new FormData();
      fd.append("photo", await shrink(f), "photo.jpg");
      fd.append("src", o.src || "");
      r = await call("/api/recog/identify", { method: "POST", body: fd });
    } catch (e) {
      beep("error");
      const b = open(`<h3>${Z("识别不了", "จดจำไม่ได้")}</h3><p class="rcg-warn" data-notr>${esc(e.message)}</p>
        <div class="rcg-col"><button class="rcg-btn pri" data-a="again">📷 ${Z("再拍一张", "ถ่ายใหม่")}</button><button class="rcg-btn" data-rcg-close>${Z("关闭", "ปิด")}</button></div>`);
      b.querySelector('[data-a="again"]').onclick = () => product({ ...o, file: null });
      return;
    }
    showResult(r, url, o);
  }
  function showResult(r, url, o) {
    const c = r.candidates || [];
    const top3 = c.slice(0, 3);
    const sure = !r.need_pick && top3.length;
    const aiLine = r.ai && r.ai.used
      ? (r.ai.ok ? `🤖 ${Z("AI 看过", "AI ดูแล้ว")}${r.ai.reason ? `：<span data-notr>${esc(r.ai.reason)}</span>` : ""}` : `🤖 ${Z("AI 没看成，只用本地比对", "AI ดูไม่ได้ ใช้การเทียบในระบบอย่างเดียว")}`)
      : `${Z("只用本地比对", "ใช้การเทียบในระบบอย่างเดียว")}`;
    const b = open(`<div class="rcg-row" style="margin-bottom:8px"><img class="rcg-q" src="${url || esc(r.photo)}" alt="">
        <div><h3>${sure ? Z("是这个吗？", "ใช่อันนี้ไหม?") : Z("像这几个，点对的那个", "คล้ายพวกนี้ กดอันที่ถูก")}</h3>
        <div class="rcg-muted">${aiLine}</div></div></div>
      ${!top3.length ? `<p class="rcg-warn">${Z("没找到像的产品", "ไม่พบสินค้าที่คล้าย")}</p>` : ""}
      ${!sure && top3.length ? `<p class="rcg-warn">${Z("把握不够：请看清楚再点", "ยังไม่แน่ใจ: ดูให้ดีก่อนกด")}</p>` : ""}
      <div class="rcg-col" id="rcg-cands">${top3.map((x, k) => candHtml(x, k, k === 0 && sure)).join("")}</div>
      <div class="rcg-row" style="margin-top:10px"><button class="rcg-btn" style="flex:1" data-a="none">${Z("都不是", "ไม่ใช่สักอัน")}</button>
        <button class="rcg-btn" style="flex:1" data-a="again">📷 ${Z("再拍一张", "ถ่ายใหม่")}</button>
        <button class="rcg-btn" data-rcg-close>✕</button></div>
      <div id="rcg-man"></div>`);
    if (sure) beep("ok"); else beep("warn");
    b.querySelectorAll("#rcg-cands [data-sku]").forEach((el) => (el.onclick = () => choose(r, el.dataset.sku, o)));
    b.querySelector('[data-a="again"]').onclick = () => product({ ...o, file: null });
    b.querySelector('[data-a="none"]').onclick = () => manual(r, o, b.querySelector("#rcg-man"));
  }
  function choose(r, sku, o) {
    call("/api/recog/confirm", { json: { rid: r.rid, sku } }).catch(() => { /* 记不上也不影响 */ });
    close();
    if (o.onPick) o.onPick(sku, "photo");
  }
  function manual(r, o, box) {
    box.innerHTML = `<div style="margin-top:10px"><input class="rcg-in" id="rcg-q" placeholder="${Z("输入 SKU / 产品名搜索", "พิมพ์ SKU / ชื่อสินค้าเพื่อค้นหา")}" autocomplete="off">
      <div class="rcg-col" id="rcg-sres" style="margin-top:8px"></div></div>`;
    const q = box.querySelector("#rcg-q");
    let t = null;
    q.oninput = () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        const v = q.value.trim();
        const res = box.querySelector("#rcg-sres");
        if (!v) { res.innerHTML = ""; return; }
        try {
          const d = await call(`/api/recog/search?q=${encodeURIComponent(v)}`);
          res.innerHTML = d.items.length ? d.items.slice(0, 12).map((x, k) => candHtml(x, k, false, true)).join("")
            : `<p class="rcg-muted">${Z("没找到", "ไม่พบ")}</p>`;
          res.querySelectorAll("[data-sku]").forEach((el) => (el.onclick = () => choose(r, el.dataset.sku, o)));
        } catch (e) { res.innerHTML = `<p class="rcg-warn" data-notr>${esc(e.message)}</p>`; }
      }, 250);
    };
    q.focus();
    call("/api/recog/confirm", { json: { rid: r.rid, sku: "" } }).catch(() => {});
  }

  // ---------------- 拍照读文字 ----------------
  async function ocr(o = {}) {
    const f = o.file || await pick();
    if (!f) { close(); return; }
    const url = URL.createObjectURL(f);
    open(`<div class="rcg-row"><img class="rcg-q" src="${url}" alt=""><div><span class="rcg-spin"></span>${Z("正在读字…", "กำลังอ่านตัวอักษร…")}</div></div>`);
    let r;
    try {
      const fd = new FormData();
      fd.append("photo", await shrink(f), "photo.jpg");
      fd.append("src", o.src || "");
      r = await call("/api/recog/ocr", { method: "POST", body: fd });
    } catch (e) {
      beep("error");
      const b = open(`<h3>${Z("读不了", "อ่านไม่ได้")}</h3><p class="rcg-warn" data-notr>${esc(e.message)}</p>
        <div class="rcg-col"><button class="rcg-btn pri" data-a="again">📷 ${Z("再拍一张", "ถ่ายใหม่")}</button><button class="rcg-btn" data-rcg-close>${Z("关闭", "ปิด")}</button></div>`);
      b.querySelector('[data-a="again"]').onclick = () => ocr({ ...o, file: null });
      return;
    }
    const c = r.candidates || [];
    const b = open(`<div class="rcg-row" style="margin-bottom:8px"><img class="rcg-q" src="${url}" alt="">
        <div><h3>${c.length ? Z("认出来的码，点一下用它", "โค้ดที่อ่านได้ กดเพื่อใช้") : Z("没认出系统里的码", "ไม่พบโค้ดในระบบ")}</h3>
        <div class="rcg-muted">${r.barcodes && r.barcodes.length ? Z("条码", "บาร์โค้ด") + ` <span data-notr>${esc(r.barcodes.join(", "))}</span> · ` : ""}
          ${r.lines && r.lines.length ? Z("文字", "ข้อความ") + ` <span data-notr>${esc(r.lines.slice(0, 6).join(" / "))}</span>` : ""}
          ${r.error ? `<div data-notr>${esc(TH() && window.I18N && I18N.t ? I18N.t(r.error) : r.error)}</div>` : ""}</div></div></div>
      <div class="rcg-col" id="rcg-codes">${c.slice(0, 5).map((x) => `<button class="rcg-c ${x === r.best ? "top" : ""}" data-code="${esc(x.code)}">
        <span class="g"><span class="sku" data-notr>${esc(x.code)}</span> <span class="rcg-tag">${esc(typeName(x.type))}</span>
        <div class="rcg-bar ${x.conf < 0.8 ? "lo" : ""}"><i style="width:${pct(x.conf)}"></i></div></span><span class="rcg-pc">${pct(x.conf)}</span></button>`).join("")}</div>
      <div class="rcg-row" style="margin-top:10px"><button class="rcg-btn" style="flex:1" data-a="again">📷 ${Z("再拍一张", "ถ่ายใหม่")}</button>
        <button class="rcg-btn" style="flex:1" data-rcg-close>${Z("关闭", "ปิด")}</button></div>`);
    beep(c.length && c[0].conf >= 0.8 ? "ok" : "warn");
    b.querySelectorAll("[data-code]").forEach((el) => (el.onclick = () => { close(); if (o.onPick) o.onPick(el.dataset.code, "ocr"); }));
    b.querySelector('[data-a="again"]').onclick = () => ocr({ ...o, file: null });
  }

  // ---------------- App 里 ML Kit 认出来的文字 ----------------
  const asked = {};
  async function text(raw) {
    raw = String(raw || "").trim();
    if (!raw) return null;
    let d;
    try { d = await call(`/api/recog/text?q=${encodeURIComponent(raw)}`); } catch { return null; }
    if (d.best) return d.best.code;
    const c = (d.candidates || []).filter((x) => x.conf >= 0.6);
    if (!c.length) return null;
    const now = Date.now();
    if (asked[raw] && now - asked[raw] < 15000) return null;         // 同一段字 15 秒内只问一次
    asked[raw] = now;
    return new Promise((done) => {
      const b = open(`<h3>🔤 ${Z("摄像头读到文字", "กล้องอ่านตัวอักษรได้")}：<span data-notr>${esc(raw)}</span></h3>
        <p class="rcg-muted">${Z("是哪一个？", "อันไหน?")}</p>
        <div class="rcg-col">${c.slice(0, 4).map((x) => `<button class="rcg-c" data-code="${esc(x.code)}"><span class="g"><span class="sku" data-notr>${esc(x.code)}</span>
          <span class="rcg-tag">${esc(typeName(x.type))}</span></span><span class="rcg-pc">${pct(x.conf)}</span></button>`).join("")}
          <button class="rcg-btn" data-a="no">${Z("都不是", "ไม่ใช่สักอัน")}</button></div>`);
      b.querySelectorAll("[data-code]").forEach((el) => (el.onclick = () => { close(); done(el.dataset.code); }));
      b.querySelector('[data-a="no"]').onclick = () => { close(); done(null); };
    });
  }

  window.RECOG = { menu, product, ocr, text, close, Z, TH };
})();
