"use strict";
// 拖文件上传（网页版和桌面客户端都能用）：把文件拖进窗口，自动找到当前页面上对应的「上传」按钮。
// v2.30：桌面客户端相关的部分搬到了「桌面客户端」模块（modules/desk/ui/boot.js）。
(function () {
  const modal = (html) => { $("#modal-in").innerHTML = html; $("#modal").classList.remove("hidden"); return $("#modal-in"); };
  const closeModal = () => { const m = $("#modal-in"); m.onclick = null; m.onchange = null; m.innerHTML = ""; $("#modal").classList.add("hidden"); };

  // ---------------- 拖文件进窗口：自动找到这个页面上对应的「上传」按钮 ----------------
  const visible = (el) => !!(el && el.closest && !el.closest(".hidden") && el.closest(".panel:not(.hidden), #modal:not(.hidden)"));
  function acceptOk(input, f) {
    const acc = (input.getAttribute("accept") || "").toLowerCase().split(",").map((x) => x.trim()).filter(Boolean);
    if (!acc.length) return true;
    const n = f.name.toLowerCase(), t = (f.type || "").toLowerCase();
    return acc.some((a) => (a.startsWith(".") ? n.endsWith(a) : a.endsWith("/*") ? t.startsWith(a.slice(0, -1)) : t === a));
  }
  function labelOf(input) {
    const l = input.closest("label");
    return ((l && l.textContent) || input.id || "").replace(/\s+/g, " ").trim().slice(0, 30);
  }
  function feed(input, files) {
    const dt = new DataTransfer();
    (input.multiple ? files : files.slice(0, 1)).forEach((f) => dt.items.add(f));
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }
  let dragN = 0;
  const overlay = () => $("#drop-overlay") || document.body.appendChild(Object.assign(document.createElement("div"), { id: "drop-overlay", className: "hidden",
    innerHTML: '<div>松开鼠标上传到当前页面</div>' }));
  window.addEventListener("dragenter", (e) => {
    if (!e.dataTransfer || ![...e.dataTransfer.types].includes("Files")) return;
    dragN++; overlay().classList.remove("hidden");
  });
  window.addEventListener("dragleave", () => { dragN = Math.max(0, dragN - 1); if (!dragN) overlay().classList.add("hidden"); });
  window.addEventListener("dragover", (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) e.preventDefault(); });
  window.addEventListener("drop", (e) => {
    if (!e.dataTransfer || !e.dataTransfer.files.length) return;
    dragN = 0; overlay().classList.add("hidden");
    // 落在某个本来就能接文件的地方（有自己的拖放处理）就不管
    if (e.defaultPrevented) return;
    e.preventDefault();
    const files = [...e.dataTransfer.files];
    const inputs = $$('input[type="file"]').filter((i) => visible(i) && !i.disabled);
    // 每个文件找能接它的上传按钮；同一个文件有几个按钮能接（例如 .3mf 可以是模型也可以是切片文件）就让用户选
    const groups = new Map(), ask = [];
    // 几个按钮都能接时的默认：图片 → 产品图片；.gcode / .gcode.3mf → 切片文件；其它 .3mf / .stl → 模型
    const PREF = ["img-input", "model-input", "fm-bulk-models"];
    files.forEach((f) => {
      let ok = inputs.filter((i) => acceptOk(i, f));
      if (ok.length > 1) {
        const sliced = /\.gcode(\.3mf)?$|\.gco$/i.test(f.name);
        const want = sliced ? ok.filter((i) => /\.gcode/.test(i.getAttribute("accept") || "")) : ok.filter((i) => PREF.includes(i.id));
        if (want.length) ok = [want.sort((a, b) => PREF.indexOf(a.id) - PREF.indexOf(b.id))[0]];
      }
      if (ok.length === 1) { if (!groups.has(ok[0])) groups.set(ok[0], []); groups.get(ok[0]).push(f); }
      else if (ok.length > 1) ask.push([f, ok]);
    });
    groups.forEach((fs, input) => feed(input, fs));
    if (ask.length) {
      const opts = ask[0][1];
      const m = modal(`<h3>上传到哪里？</h3><p class="small muted" data-notr>${ask.map(([f]) => esc(f.name)).join("、")}</p>
        <div class="row gap wrap">${opts.map((i, k) => `<button data-dk="${k}">${esc(labelOf(i))}</button>`).join("")}<button data-mclose>取消</button></div>`);
      m.onclick = (ev) => {
        const k = ev.target.dataset && ev.target.dataset.dk; if (k == null) return;
        closeModal(); feed(opts[+k], ask.map(([f]) => f));
      };
    }
    if (!groups.size && !ask.length) toast("这个页面不能上传这种文件（先打开要上传的产品 / 页面）", true);
  });
})();
