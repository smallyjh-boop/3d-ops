"use strict";
// 电脑网页 / 平板（完整网页版）：打包核对、发货交接、货位页的扫码框旁边加「📷 拍照识别」：
// 认出来的码填进扫码框，模拟按回车（和扫码枪扫进去一样）。安卓 App 里摄像头认出的文字（onNativeScan(文字, "text")）先认成系统里的码再送进去。
(function () {
  const BOXES = ["#pk-code", "#ho-code", "#loc-scan"];
  const Z = (zh, th) => (window.RECOG ? RECOG.Z(zh, th) : zh);
  function feed(inp, code) {
    inp.value = code;
    inp.focus();
    inp.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  }
  function add() {
    for (const sel of BOXES) {
      const inp = document.querySelector(sel);
      if (!inp || inp.dataset.recog) continue;
      inp.dataset.recog = "1";
      const b = document.createElement("button");
      b.type = "button"; b.className = "recog-desk-btn";
      b.textContent = "📷 " + Z("拍照识别", "ถ่ายรูปจดจำ");
      b.title = Z("没有条码的产品拍一下就知道是哪个 SKU；货位牌、面单拍照读字", "สินค้าไม่มีบาร์โค้ดถ่ายรูปก็รู้ SKU; ถ่ายป้ายตำแหน่ง ใบปะหน้า เพื่ออ่านตัวอักษร");
      b.addEventListener("click", (e) => {
        e.preventDefault();
        if (!window.RECOG) return;
        const onPick = (code) => feed(inp, code);
        if (sel === "#pk-code") RECOG.menu({ src: "pack", onPick });
        else if (sel === "#loc-scan") RECOG.menu({ src: "loc", onPick });
        else RECOG.ocr({ src: "handover", onPick });            // 发货交接：扫的是面单 → 直接读字
      });
      inp.after(b);
    }
  }
  let pend = false;
  const later = () => { if (!pend) { pend = true; setTimeout(() => { pend = false; add(); }, 300); } };
  const start = () => {
    add();
    new MutationObserver(later).observe(document.body, { childList: true, subtree: true });
    // App 里：摄像头认出的文字 → 系统里的码 → 再交给原来的处理（打包核对 / 发货交接的扫码框）
    const prev = window.onNativeScan;
    if (prev && !prev._recog) {
      const wrapped = (code, kind) => {
        if (kind === "text") { if (window.RECOG) RECOG.text(code).then((c) => { if (c) prev(c); }); return; }
        prev(code);
      };
      wrapped._recog = true;
      window.onNativeScan = wrapped;
      const A = window.Android3D;
      if (A && A.setTextPatterns) {
        fetch("/api/mobile/code-patterns", { credentials: "same-origin" }).then((r) => (r.ok ? r.text() : null))
          .then((t) => { if (t) A.setTextPatterns(t); }).catch(() => {});
      }
    }
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
