"use strict";
// 电脑网页 / 平板（完整网页版）：打包核对、发货交接、货位、移库、盘点、采购到货、料卷的扫码框旁边加「📷 拍照识别 / 拍照读字」；商品 360 里看 / 管参考照片。
// 认出来的码填进扫码框，模拟按回车（和扫码枪扫进去一样）。安卓 App 里摄像头认出的文字（onNativeScan(文字, "text")）先认成系统里的码再送进去。
(function () {
  // 扫码框：mode = menu（问拍产品还是读字）/ ocr（只读字：面单、货位、料卷）；enter = 填进去以后模拟回车
  const BOXES = [
    { sel: "#pk-code", mode: "menu", enter: true, src: "pack" },          // 订单 → 打包核对
    { sel: "#ho-code", mode: "ocr", enter: true, src: "handover" },       // 订单 → 发货交接（面单）
    { sel: "#loc-scan", mode: "menu", enter: true, src: "loc" },          // 库存 → 货位
    { sel: "#mv-scan", mode: "ocr", enter: true, src: "move" },           // 库存 → 移库（扫货位牌）
    { sel: "#rc-scan", mode: "menu", enter: true, src: "receive" },       // 采购 → 到货入库（物品 / 单号）
    { sel: "#sp-scan", mode: "ocr", enter: true, src: "spool" },          // 生产 → 料卷
    { sel: "[data-add]", mode: "menu", enter: false, src: "stocktake" },  // 库存 → 盘点：多出来的物品编码
  ];
  const Z = (zh, th) => (window.RECOG ? RECOG.Z(zh, th) : zh);
  function feed(inp, code, enter) {
    inp.value = code;
    inp.focus();
    inp.dispatchEvent(new Event("input", { bubbles: true }));
    if (enter) inp.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  }
  function add() {
    for (const bx of BOXES) {
      document.querySelectorAll(bx.sel).forEach((inp) => {
        if (inp.dataset.recog || inp.tagName !== "INPUT") return;
        inp.dataset.recog = "1";
        const b = document.createElement("button");
        b.type = "button"; b.className = "recog-desk-btn mini";
        b.textContent = "📷 " + (bx.mode === "ocr" ? Z("拍照读字", "ถ่ายรูปอ่านตัวอักษร") : Z("拍照识别", "ถ่ายรูปจดจำ"));
        b.title = Z("没有条码的产品拍一下就知道是哪个 SKU；货位牌、面单拍照读字", "สินค้าไม่มีบาร์โค้ดถ่ายรูปก็รู้ SKU; ถ่ายป้ายตำแหน่ง ใบปะหน้า เพื่ออ่านตัวอักษร");
        b.addEventListener("click", (e) => {
          e.preventDefault();
          if (!window.RECOG) return;
          const onPick = (code) => feed(inp, code, bx.enter);
          if (bx.mode === "ocr") RECOG.ocr({ src: bx.src, onPick }); else RECOG.menu({ src: bx.src, onPick });
        });
        inp.after(b);
      });
    }
    p360();
  }
  // 商品 360 抽屉：最后加一块「拍照识别的参考照片」（老板 / 上架才看得到；没有就不显示）
  let p360Target = "";
  window.addEventListener("click", (e) => {                   // 点了哪个商品的 360（抽屉自己的点击不经过 window.P360.open）
    const el = e.target.closest && e.target.closest("[data-p360]");
    if (el && el.dataset.p360) p360Target = el.dataset.p360;
  }, true);
  function p360() {
    if (window.P360 && P360.open && !P360.open._recog) {
      const o = P360.open;
      const w = function (t, ...a) { p360Target = String(t || ""); return o.call(this, t, ...a); };
      w._recog = true;
      P360.open = w;
    }
    const body = document.querySelector(".p360-body");
    const first = body && body.firstElementChild;
    if (!first || !p360Target || first.matches(".p360-loading, .p360-err") || body.querySelector("[data-recog-learned]")) return;
    if (typeof ME !== "undefined" && ME && !["owner", "listing"].includes(ME.role)) return;
    const box = document.createElement("div");
    box.dataset.recogLearned = p360Target;
    box.style.cssText = "margin:10px 0";
    body.appendChild(box);
    if (window.RECOG) RECOG.learned(box, p360Target, { quiet: true, title: "📷 " + Z("拍照识别：员工确认过的参考照片", "ถ่ายรูปจดจำ: รูปอ้างอิงที่พนักงานยืนยัน") });
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
