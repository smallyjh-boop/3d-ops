// 面单 PDF 转交（v2.9）：卖家中心 / BigSeller 网页里生成 PDF 再点下载时，网页常常下载完就马上把这个临时文件删了，
// 插件后台再去拿就拿不到。所以在点下载的那一下先读一份 PDF 交给插件后台暂存——只是先放在插件里，
// 员工在通知或插件弹窗里点「发送到系统」才会发出去。只读 PDF；不读网页上的别的东西，不改网页。
(() => {
  if (window.__lhPdfGrab) return;
  window.__lhPdfGrab = true;
  let on = true;
  try {
    chrome.storage.sync.get({ label_forward: true }, (d) => { on = d.label_forward !== false; });
    chrome.storage.onChanged.addListener((ch, area) => { if (area === "sync" && ch.label_forward) on = ch.label_forward.newValue !== false; });
  } catch (e) { /* 扩展刚更新过，旧页面里的脚本失效了 */ }

  function b64(ab) {
    const b = new Uint8Array(ab);
    let s = "";
    for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
    return btoa(s);
  }

  document.addEventListener("click", (e) => {
    if (!on) return;
    const a = e.target && e.target.closest && e.target.closest("a[href^='blob:']");
    if (!a) return;
    const url = a.href;
    // 要在点击的这一下就开始读（网页可能紧接着就删掉这个临时文件）
    fetch(url).then((r) => (r.ok ? r.arrayBuffer() : null)).then((ab) => {
      if (!ab || ab.byteLength < 200 || ab.byteLength > 30 * 1024 * 1024) return;
      const head = String.fromCharCode.apply(null, new Uint8Array(ab, 0, Math.min(1024, ab.byteLength)));
      if (!head.includes("%PDF-")) return;
      chrome.runtime.sendMessage({ type: "label-blob", url, name: a.getAttribute("download") || "", b64: b64(ab) }, () => void chrome.runtime.lastError);
    }).catch(() => {});
  }, true);
})();
