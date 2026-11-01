"use strict";
// 通用弹窗（v2.31 从 prod.js 搬到系统本身，各模块都用）：MODAL.open(html) / MODAL.close() / MODAL.onClose(fn)
// 弹窗里 data-mclose 的按钮、点空白处、按 Esc 都会关掉。
(function () {
  const hooks = [];
  function open(html) {
    $("#modal-in").innerHTML = html;
    $("#modal").classList.remove("hidden");
    return $("#modal-in");
  }
  function close() {
    const ctx = { wasRecipe: !!$("#rc-modal-box") };
    $("#modal-in").onchange = null; $("#modal-in").onclick = null; $("#modal-in").oninput = null;
    $("#modal").classList.add("hidden"); $("#modal-in").innerHTML = ""; $("#modal-in").classList.remove("wide");
    hooks.forEach((f) => { try { f(ctx); } catch (e) { console.error(e); } });
  }
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal" || e.target.closest("[data-mclose]")) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#modal").classList.contains("hidden")) close(); });
  window.MODAL = { open, close, onClose: (f) => hooks.push(f) };
  // v2.53：弹窗 = 一条浏览器历史：浏览器后退 / 安卓返回手势先关弹窗（不离开页面），关掉后刚才那一行闪一下
  if (window.NAV) NAV.overlay($("#modal"), { key: "modal" });
})();
