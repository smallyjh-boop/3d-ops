"use strict";
// 订单模块：打包核对（v2.32 从 home.js 搬过来，加了「每个产品怎么核对」）。
// 先扫面单条码（订单号 / 快递单号，按设置），再核对商品。每一行的核对方式由后台按产品给出：
//   scan 扫商品码（SKU 条码 / 内部商品标签）  tap 点「✓ 装好了」  none 不用核对
(function () {
  const H = () => window.OPSH;
  let PK = null;   // {order, need:{sku:qty}, got:{sku:qty}, mode:{sku:check}}
  const WAIT = { both: "等待扫描订单号或快递单号…", tracking: "等待扫描快递单号…", order: "等待扫描订单号…" };
  function beep(ok) {
    try {
      const a = new (window.AudioContext || window.webkitAudioContext)(), o = a.createOscillator(), g = a.createGain();
      o.frequency.value = ok ? 880 : 220; o.connect(g); g.connect(a.destination); g.gain.value = 0.15; o.start(); setTimeout(() => { o.stop(); a.close(); }, ok ? 120 : 400);
    } catch { /* 没有声音也行 */ }
  }
  const done = (k) => (PK.got[k] || 0) >= PK.need[k];
  function renderPack(msg = "", bad = false) {
    const h = H();
    if (!PK) {
      const key = (window.CFG && CFG.scan_order_key) || "both";
      $("#pk-out").innerHTML = msg ? `<p class="${bad ? "bad big-msg" : ""}">${esc(msg)}</p>` : `<p class="muted">${esc(WAIT[key] || WAIT.both)}</p>`;
      return;
    }
    const o = PK.order;
    const all = Object.keys(PK.need).every(done);
    const notReady = o.jobs.filter((j) => !["post", "packed", "done"].includes(j.status));
    const scanLeft = Object.keys(PK.need).some((k) => PK.mode[k] === "scan" && !done(k));
    $("#pk-out").innerHTML = `${msg ? `<p class="${bad ? "bad big-msg" : "ok"}">${esc(msg)}</p>` : ""}
      <h3>订单 <span class="mono" data-notr>${esc(o.order_no)}</span> <span class="muted small">${esc(h.PLAT[o.platform] || o.platform)} · <span data-notr>${esc(o.receiver || o.buyer || "")}</span></span></h3>
      ${o.status !== "to_ship" ? `<p class="bad big-msg">这个订单是「${esc(o.status_zh || o.status)}」，不是待发货，确认一下再打包</p>` : ""}
      ${o.hold ? '<p class="bad big-msg">这个订单还在「待审核」挂起中，先别打包</p>' : ""}
      ${o.custom_note ? `<div class="note-flag" data-notr>✎ ${esc(o.custom_note)}</div>` : ""}
      ${o.buyer_note ? `<div class="small" data-notr>💬 ${esc(o.buyer_note)}</div>` : ""}
      <table class="grid pk-table"><thead><tr><th></th><th>SKU</th><th>商品</th><th>颜色</th><th>要装</th><th>已核对</th><th>怎么核对</th></tr></thead><tbody>
      ${o.items.map((i) => { const k = (i.sku || "").toUpperCase(), got = PK.got[k] || 0, need = PK.need[k] || 0, m = PK.mode[k];
        const act = m === "scan" ? `<span class="small">扫商品码</span> <button class="mini" data-pkplus="${esc(k)}" title="条码坏了扫不出来时手动 +1">+1</button>`
          : m === "tap" ? (got >= need ? '<span class="ok">✓</span>' : `<button class="mini primary" data-pktap="${esc(k)}">✓ 装好了</button>`)
          : '<span class="small muted">不用核对</span>';
        return `<tr class="${got >= need ? "pk-ok" : ""}"><td>${i.img ? `<img class="pk-img" src="${esc(i.img)}" alt="" loading="lazy">` : ""}</td>
        <td class="mono" data-notr><b>${esc(i.sku)}</b></td><td data-notr>${esc(i.name || "")}</td><td>${h.colorTxt(i.color)}</td>
        <td><b>${i.qty}</b></td><td><b>${Math.min(got, need)}</b></td><td class="nowrap">${act}</td></tr>`; }).join("")}</tbody></table>
      <div class="pk-box">${window.PACKBOX ? PACKBOX.html(o, "pk-box-sel") : ""}</div>
      ${notReady.length ? `<p class="warn small">注意：这个订单还有 ${notReady.length} 个生产任务没打完（${notReady.map((j) => esc(j.sku) + " " + esc(j.status_zh)).join("、")}）</p>` : ""}
      ${scanLeft ? '<p class="small muted">还有要扫码的商品：扫 SKU 条码，或者后处理时贴的内部商品标签。</p>' : ""}
      <div class="row gap wrap"><button class="big primary" id="pk-done" ${all ? "" : "disabled"}>✅ 打包完成</button>
        <a class="btn" target="_blank" href="/print/labels?type=${o.label_file ? "platform" : "self"}&ids=${o.id}">🏷 打印面单</a>
        <a class="btn" target="_blank" href="/print/item-labels?ids=${o.id}" title="内部商品标签（SKU 条码），贴在袋子上，打包时扫">🏷 打印商品标签</a></div>`;
  }
  async function scan(code) {
    code = code.trim();
    if (!code) return;
    if (PK) {
      const k = code.toUpperCase();
      if (PK.need[k] !== undefined) {
        if (done(k)) { beep(false); renderPack(`${code} 已经够了，多扫了！`, true); return; }
        PK.got[k] = (PK.got[k] || 0) + 1; beep(true); renderPack(`✔ ${code}`); return;
      }
    }
    try {
      const o = await api(`/api/pack/lookup?code=${encodeURIComponent(code)}`);
      if (window.PACKBOX) await PACKBOX.load();
      PK = { order: o, need: {}, got: {}, mode: {} };
      o.items.forEach((i) => {
        const k = (i.sku || "").toUpperCase();
        PK.need[k] = (PK.need[k] || 0) + (i.qty || 1);
        // 同一个 SKU 出现在几行时，有一行要扫码就按扫码
        PK.mode[k] = PK.mode[k] === "scan" || i.check === "scan" ? "scan" : PK.mode[k] === "tap" || i.check === "tap" ? "tap" : (i.check || "tap");
      });
      Object.keys(PK.need).forEach((k) => { if (PK.mode[k] === "none") PK.got[k] = PK.need[k]; });
      beep(true);
      const anyScan = Object.values(PK.mode).includes("scan");
      renderPack(anyScan ? "订单已找到，请扫描商品条码 / 内部标签" : "订单已找到，对着图片核对后点「✓ 装好了」");
    } catch (err) {
      beep(false);
      renderPack(PK ? `「${code}」不是这个订单里的商品！` : err.message, true);
    }
  }
  $("#pk-code").addEventListener("keydown", (e) => { if (e.key === "Enter") { scan(e.target.value); e.target.value = ""; } });
  $("#btn-pk-reset").addEventListener("click", () => { PK = null; renderPack(); $("#pk-code").focus(); });
  $("#pk-out").addEventListener("click", async (e) => {
    if (e.target.dataset.pkplus) { scan(e.target.dataset.pkplus); return; }
    if (e.target.dataset.pktap) { const k = e.target.dataset.pktap; PK.got[k] = PK.need[k]; beep(true); renderPack(`✔ ${k}`); return; }
    if (e.target.id === "pk-done") {
      await busy(e.target, async () => {
        const r = await api("/api/pack/done", { json: { order_id: PK.order.id } });
        toast(`打包完成（${r.packed} 个任务标记为已打包）`); PK = null; renderPack(); $("#pk-code").focus();
      });
    }
  });
  let CAM = null;
  $("#btn-pk-cam").addEventListener("click", async () => {
    const v = $("#pk-video");
    if (CAM) { CAM.getTracks().forEach((t) => t.stop()); CAM = null; v.classList.add("hidden"); return; }
    if (!("BarcodeDetector" in window)) { toast("这个浏览器不支持摄像头扫码，请用手机 Chrome 或扫码枪", true); return; }
    try {
      CAM = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    } catch { toast("打不开摄像头（局域网 http 地址可能不允许，请用扫码枪或手动输入）", true); return; }
    v.srcObject = CAM; v.classList.remove("hidden"); await v.play();
    const det = new BarcodeDetector();
    let last = "", lastT = 0;
    const tick = async () => {
      if (!CAM) return;
      try {
        const codes = await det.detect(v);
        if (codes.length) { const c = codes[0].rawValue; if (c !== last || Date.now() - lastT > 2000) { last = c; lastT = Date.now(); scan(c); } }
      } catch { /* 下一帧 */ }
      requestAnimationFrame(tick);
    };
    tick();
  });
  function show(name) { if (name === "pack") { renderPack(); setTimeout(() => $("#pk-code").focus(), 50); } }
  renderPack();
  window.PACK = { show, scan };
})();
