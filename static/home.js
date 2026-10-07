"use strict";
// 工作台、打包核对、售后、数据备份
(function () {
  const H = () => window.OPSH;
  function show(name) {
    if (name === "dashboard") loadDash();
    if (name === "pack") { setTimeout(() => $("#pk-code").focus(), 50); }
    if (name === "backup") loadBackups();
  }

  // ---------------- 工作台 ----------------
  const tile = (label, val, cls = "", tab = "") => `<div class="tile ${cls}" ${tab ? `data-go="${tab}"` : ""}><span>${label}</span><b>${val}</b></div>`;
  async function loadDash() {
    const d = await api("/api/dashboard");
    let cs = null;   // 客服（有客服页面的人才看得到）
    const csTab = $('#subnav .tab[data-tab="cs"]');
    if (csTab && !csTab.classList.contains("role-hidden")) { try { cs = await api("/api/cs/stats"); } catch { /* 没有权限 */ } }
    const h = H();
    const own = h.isOwner();
    const prs = d.printers.map((p) => `<div class="dp ${p.enabled === false ? "lane-off" : ""}"><b class="pcode" data-notr>${esc(p.code || "")}</b> <span class="small muted" data-notr>${esc(p.name)}</span> ${h.stChip({ state: p.state, progress: p.progress, remaining_min: p.remaining_min }, p.state_zh)}
      ${p.file && p.state === "printing" ? `<div class="small muted" data-notr>${esc(p.file)}</div>` : ""}</div>`).join("");
    const list = (title, items, fmt, tab) => items.length ? `<div class="card"><h3>${title}</h3>${items.map(fmt).join("")}
      ${tab ? `<button class="mini" data-go="${tab}">去处理</button>` : ""}</div>` : "";
    $("#dash").innerHTML = `${cs ? '<div id="dash-cs"></div>' : ""}
      <div class="tiles">
        ${tile("待发货订单", d.orders_active, "", "orders")}
        ${tile("已超时", d.overdue.length, d.overdue.length ? "bad" : "", "orders")}
        ${tile("今天要发", d.due_today, d.due_today ? "warn" : "", "orders")}
        ${tile("打包好待发", d.ready_to_ship, "", "pack")}
        ${tile("异常订单", d.exceptions, d.exceptions ? "warn" : "", "orders")}
        ${tile("今天新订单", d.new_today)}
        ${cs ? tile("客服超时未回复", cs.overdue, cs.overdue ? "bad" : "", "cs") : ""}
        ${cs ? tile("客服需人工", cs.human, cs.human ? "warn" : "", "cs") : ""}
        ${tile("排队任务", `${d.queue_jobs}<small> 个 / ${d.queue_pcs} 件</small>`, "", "production")}
        ${tile("正在打印", d.runs, "", "production")}
        ${tile("待后处理", d.post, "", "production")}
        ${tile("今天失败", d.fails_today, d.fails_today ? "bad" : "", "quality")}
        ${tile("待审核订单", d.review || 0, d.review ? "warn" : "", "orders")}
        ${tile("24 小时内要发", d.urgent || 0, d.urgent ? "warn" : "", "orders")}
        ${tile("售后处理中", d.aftersales_open, d.aftersales_open ? "warn" : "", "aftersales")}
        ${d.aftersales_overdue ? tile("售后快到期 / 超期", d.aftersales_overdue, "bad", "aftersales") : ""}
        ${own && d.today ? tile("今天收入 / 利润", `${h.money(d.today.revenue)}<small> / ${h.money(d.today.profit)}</small>`, "", "fin_overview") : ""}
        ${own && d.week ? tile("近 7 天收入 / 利润", `${h.money(d.week.revenue)}<small> / ${h.money(d.week.profit)}</small>`, "", "fin_overview") : ""}
      </div>
      <div class="card"><h3>打印机</h3><div class="dps">${prs || '<span class="muted">没有打印机</span>'}</div></div>
      <div class="lanes two">
        ${list("⚠ 已超过最晚发货时间", d.overdue, (o) => `<div class="small"><span class="mono" data-notr>${esc(o.order_no)}</span> 最晚 ${h.short(o.ship_by)}</div>`, "orders")}
        ${list("⚠ 打印机报警", d.alerts, (a) => `<div class="small">${esc(h.printerName(a.printer))} · <span class="mono" data-notr>${esc(a.sku || "")}</span>：${esc(a.alert)}</div>`, "production")}
        ${list("耗材提醒", d.material_alerts || [], (a) => `<div class="small ${a.level === "bad" ? "bad" : ""}">${a.level === "bad" ? "⚠ " : ""}${esc(a.text)}</div>`, "materials")}
        ${list("耗材该买了", d.low_material, (m) => `<div class="small">${esc(m.material)} ${h.colorTxt(m.color)} ${m.short ? '<b class="bad">不够打待打印的单</b>' : `还能用 ${h.num(m.days_left, 0)} 天`}</div>`, "materials")}
        ${list("耗材该烘干了（防潮）", d.humid, (m) => `<div class="small">${esc(m.material)} ${h.colorTxt(m.color)} 开封/烘干后 ${m.days} 天</div>`, "materials")}
        ${list("打印机该保养了", d.maintenance, (m) => `<div class="small" data-notr>${esc(m.printer)}：${esc(m.label)}</div>`, "printers")}
        ${list("建议备货", d.stock_suggest, (s) => `<div class="small"><span class="mono" data-notr>${esc(s.sku)}</span> 建议打 ${s.suggest} 个</div>`, "stock")}
      </div>`;
    if (cs && window.CSREC) CSREC.dash($("#dash-cs"));
  }
  // （v2.24 客服报告在上面：loadDash 末尾填）
  $("#btn-dash-reload").addEventListener("click", (e) => busy(e.target, loadDash));
  $("#dash").addEventListener("click", (e) => { const g = e.target.closest("[data-go]"); if (g) showTab(g.dataset.go); });

  // ---------------- 打包核对 ----------------
  let PK = null;   // {order, need:{sku:qty}, got:{sku:qty}}
  function beep(ok) {
    try {
      const a = new (window.AudioContext || window.webkitAudioContext)(), o = a.createOscillator(), g = a.createGain();
      o.frequency.value = ok ? 880 : 220; o.connect(g); g.connect(a.destination); g.gain.value = 0.15; o.start(); setTimeout(() => { o.stop(); a.close(); }, ok ? 120 : 400);
    } catch { /* 没有声音也行 */ }
  }
  function renderPack(msg = "", bad = false) {
    const h = H();
    if (!PK) { $("#pk-out").innerHTML = msg ? `<p class="${bad ? "bad" : ""}">${esc(msg)}</p>` : '<p class="muted">等待扫描订单号…</p>'; return; }
    const o = PK.order;
    const all = Object.keys(PK.need).every((k) => (PK.got[k] || 0) >= PK.need[k]);
    const notReady = o.jobs.filter((j) => !["post", "packed", "done"].includes(j.status));
    $("#pk-out").innerHTML = `${msg ? `<p class="${bad ? "bad big-msg" : "ok"}">${esc(msg)}</p>` : ""}
      <h3>订单 <span class="mono" data-notr>${esc(o.order_no)}</span> <span class="muted small">${esc(h.PLAT[o.platform] || o.platform)} · <span data-notr>${esc(o.receiver || o.buyer || "")}</span></span></h3>
      ${o.custom_note ? `<div class="note-flag" data-notr>✎ ${esc(o.custom_note)}</div>` : ""}
      ${o.buyer_note ? `<div class="small" data-notr>💬 ${esc(o.buyer_note)}</div>` : ""}
      <table class="grid pk-table"><thead><tr><th>SKU</th><th>商品</th><th>颜色</th><th>要装</th><th>已扫</th><th></th></tr></thead><tbody>
      ${o.items.map((i) => { const k = (i.sku || "").toUpperCase(), got = PK.got[k] || 0, need = PK.need[k] || 0;
        return `<tr class="${got >= need ? "pk-ok" : ""}"><td class="mono" data-notr><b>${esc(i.sku)}</b></td><td data-notr>${esc(i.name || "")}</td><td>${h.colorTxt(i.color)}</td>
        <td><b>${i.qty}</b></td><td><b>${Math.min(got, need)}</b></td><td><button class="mini" data-pkplus="${esc(k)}">+1</button></td></tr>`; }).join("")}</tbody></table>
      ${notReady.length ? `<p class="warn small">注意：这个订单还有 ${notReady.length} 个生产任务没打完（${notReady.map((j) => esc(j.sku) + " " + esc(j.status_zh)).join("、")}）</p>` : ""}
      <div class="row gap"><button class="big primary" id="pk-done" ${all ? "" : "disabled"}>✅ 打包完成</button>
        <a class="btn" target="_blank" href="/print/labels?type=${o.label_file ? "platform" : "self"}&ids=${o.id}">🏷 打印面单</a></div>`;
  }
  async function scan(code) {
    code = code.trim();
    if (!code) return;
    if (PK) {
      const k = code.toUpperCase();
      if (PK.need[k] !== undefined) {
        if ((PK.got[k] || 0) >= PK.need[k]) { beep(false); renderPack(`${code} 已经够了，多扫了！`, true); return; }
        PK.got[k] = (PK.got[k] || 0) + 1; beep(true); renderPack(`✔ ${code}`); return;
      }
    }
    try {
      const o = await api(`/api/pack/lookup?code=${encodeURIComponent(code)}`);
      PK = { order: o, need: {}, got: {} };
      o.items.forEach((i) => { const k = (i.sku || "").toUpperCase(); PK.need[k] = (PK.need[k] || 0) + (i.qty || 1); });
      beep(true); renderPack("订单已找到，请逐个扫描商品条码");
    } catch (err) {
      beep(false);
      renderPack(PK ? `「${code}」不是这个订单里的商品！` : err.message, true);
    }
  }
  $("#pk-code").addEventListener("keydown", (e) => { if (e.key === "Enter") { scan(e.target.value); e.target.value = ""; } });
  $("#btn-pk-reset").addEventListener("click", () => { PK = null; renderPack(); $("#pk-code").focus(); });
  $("#pk-out").addEventListener("click", async (e) => {
    if (e.target.dataset.pkplus) { scan(e.target.dataset.pkplus); return; }
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
  renderPack();

  // 售后已移到 aftersales.js（window.AS）
  const asDialog = (order) => window.AS && window.AS.dialog(order);

  // ---------------- 数据备份 ----------------
  async function loadBackups() {
    const r = await api("/api/backups");
    $("#bk-table tbody").innerHTML = r.items.map((b) => `<tr><td class="mono" data-notr>${esc(b.name)}</td><td>${fmtTime(b.ts)}</td>
      <td>${(b.size / 1048576).toFixed(1)} MB</td><td class="nowrap"><a class="btn mini-btn" href="/api/backups/${encodeURIComponent(b.name)}">下载</a>
      <button class="mini" data-bkv="${esc(b.name)}">检查</button></td></tr>`).join("")
      || '<tr><td colspan="4" class="muted">还没有备份</td></tr>';
  }
  $("#bk-table").addEventListener("click", (e) => {
    const n = e.target.dataset.bkv; if (!n) return;
    busy(e.target, async () => {
      const r = await api(`/api/backups/${encodeURIComponent(n)}/verify`, { json: {} });
      toast((r.ok ? "✅ 备份可以正常恢复：" : "❌ ") + r.message, !r.ok, 8000);
    });
  });
  $("#btn-backup-now").addEventListener("click", (e) => busy(e.target, async () => { await api("/api/backups", { json: {} }); toast("备份完成"); loadBackups(); }));

  window.HOME = { show, asDialog, loadDash };
})();
