"use strict";
// 手机 / 平板 App 模块（完整网页版里一打开就加载）：
// · 平板（触屏）：宽表格超出卡片时套一层 <div class="tbl-scroll">，在卡片里横着滑，不把整个页面撑宽
// · 安卓 App 里（首页 <html class="in-app">，见 web/system.py）：顶部加「📱 扫码」（打开手机扫码页 /m）；
//   电脑才有的东西（加速器、桌面版下载）由 style.css 的 html.in-app 规则藏起来
(function () {
  const inApp = document.documentElement.classList.contains("in-app") || /3DOpsApp/.test(navigator.userAgent);
  const touch = window.matchMedia && matchMedia("(pointer:coarse)").matches;

  if (inApp) {
    const top = document.querySelector("header.top");
    if (top && !document.getElementById("m-app-chip")) {
      const a = document.createElement("a");
      a.id = "m-app-chip"; a.className = "m-app-chip"; a.href = "/m";
      a.textContent = "📱 扫码";
      a.title = "手机扫码页（验货、发货交接、库存、货位）";
      const g = document.createElement("a");
      g.id = "m-app-set"; g.className = "m-app-chip"; g.href = "#"; g.textContent = "⚙"; g.title = "App 设置（服务器地址、手机版 / 网页版）";
      g.addEventListener("click", (e) => { e.preventDefault(); try { window.Android3D.openSettings(); } catch { /* 老版本 App */ } });
      const lang = document.getElementById("lang-select");
      if (lang) { lang.before(a); lang.before(g); } else { top.appendChild(a); top.appendChild(g); }
    }
  }
  // App 里：网页版「打包核对」「发货交接」的摄像头扫码用 App 的原生摄像头（WebView 里没有 BarcodeDetector）
  if (inApp && window.Android3D) {
    let on = false;
    const toggle = () => { on = !on; try { on ? Android3D.startScan() : Android3D.stopScan(); } catch { on = false; } };
    document.addEventListener("click", (e) => {
      const b = e.target.closest && e.target.closest("#btn-pk-cam, #m-ho-cam");
      if (!b) return;
      e.preventDefault(); e.stopImmediatePropagation();
      toggle();
    }, true);
    // 扫到的码送进现在看得到的扫码框（打包核对 / 发货交接），模拟按回车
    window.onNativeScan = (code) => {
      const inp = ["#pk-code", "#ho-code"].map((s) => document.querySelector(s)).find((x) => x && x.offsetParent);
      if (!inp) return;
      inp.value = code;
      inp.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    };
    const addHoCam = () => {
      const ho = document.getElementById("ho-code");
      if (ho && !document.getElementById("m-ho-cam")) {
        const b = document.createElement("button"); b.id = "m-ho-cam"; b.type = "button"; b.textContent = "📷 摄像头扫码";
        ho.after(b);
      }
    };
    addHoCam();
    new MutationObserver(addHoCam).observe(document.body, { childList: true, subtree: true });
    window.addEventListener("pagehide", () => { try { Android3D.stopScan(); } catch { /* 忽略 */ } });
  }
  if (!touch && !inApp) return;

  // 宽表格：超出父元素时套一层可以横着滑的盒子
  let pending = false;
  function wrapAll() {
    pending = false;
    document.querySelectorAll("main table.grid").forEach((t) => {
      const p = t.parentElement;
      if (!p || p.classList.contains("tbl-scroll") || !t.offsetParent) return;
      if (getComputedStyle(t).display === "block") return;         // 窄屏的旧规则已经让表格自己横着滑
      if (t.offsetWidth <= p.clientWidth + 2) return;
      const w = document.createElement("div");
      w.className = "tbl-scroll";
      p.insertBefore(w, t);
      w.appendChild(t);
    });
  }
  const later = () => { if (!pending) { pending = true; requestAnimationFrame(() => setTimeout(wrapAll, 60)); } };
  const start = () => {
    new MutationObserver(later).observe(document.querySelector("main") || document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class"] });
    window.addEventListener("resize", later);
    later();
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
