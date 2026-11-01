"use strict";
// 手机页 /m（浏览器和安卓 App 里都一样）：扫码输入框旁边加「📷 识别」按钮 → 拍照识别产品 / 拍照读文字，
// 认出来的码像扫码一样送给当前页面（SCAN.feed(码, "photo")）：验货、库存、货位、查订单都不用改。
(function () {
  const Z = (zh, th) => (window.RECOG ? RECOG.Z(zh, th) : zh);
  let off = false;
  function add() {
    const f = document.getElementById("scan-form");
    if (!f || document.getElementById("recog-btn") || off) return;
    const b = document.createElement("button");
    b.type = "button"; b.id = "recog-btn";
    b.setAttribute("aria-label", Z("拍照识别产品", "ถ่ายรูปหาสินค้า"));
    b.title = Z("拍照识别产品 / 读文字", "ถ่ายรูปหาสินค้า / อ่านตัวอักษร");
    b.innerHTML = `📷<span style="font-size:12px;display:block;line-height:1">${Z("识别", "จดจำ")}</span>`;
    b.style.cssText = "min-width:58px;font-size:18px;padding:2px 6px;line-height:1.1";
    f.insertBefore(b, document.getElementById("scan-go"));
    b.addEventListener("click", (e) => {
      e.preventDefault();
      if (!window.RECOG) return;
      RECOG.menu({ src: window.SCAN && SCAN.isApp && SCAN.isApp() ? "app" : "m", onPick: (code) => { if (window.SCAN) SCAN.feed(code, "photo"); } });
    });
  }
  // 设置里关了拍照识别：不显示按钮（登录后才问得到；没登录时先显示，点了会提示）
  async function check() {
    try {
      const r = await fetch("/api/recog/status", { credentials: "same-origin" });
      if (r.status === 401) { setTimeout(check, 4000); return; }
      if (r.status === 404) { off = true; }
      else { const d = await r.json(); off = !(d && d.on); }
      const b = document.getElementById("recog-btn");
      if (off && b) b.remove();
      if (!off) add();
      sendPatterns(!off);
    } catch { setTimeout(check, 8000); }
  }
  // 安卓 App：把「像码的文字」的正则交给原生摄像头（ML Kit 文字识别只把像码的字送回来）；关了就给空表（App 只认条码）
  async function sendPatterns(on) {
    const A = window.Android3D;
    if (!A || !A.setTextPatterns) return;
    try {
      let txt = '{"patterns":[]}';
      if (on) { const r = await fetch("/api/mobile/code-patterns", { credentials: "same-origin" }); if (r.ok) txt = await r.text(); }
      A.setTextPatterns(txt);
    } catch { /* 老版本 App */ }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => { add(); check(); }); else { add(); check(); }
})();
