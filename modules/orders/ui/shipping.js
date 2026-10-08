"use strict";
// 发货交接（扫运单号 → 交给快递，批量标记已发货）+ 买家档案
(function () {
  const H = () => window.OPSH;
  let CUR = null;   // 当前交接单
  function show(name) {
    if (name === "handover") { loadHO(); setTimeout(() => CUR && $("#ho-code").focus(), 50); }
    if (name === "buyers") loadBuyers();
  }

  // ---------------- 发货交接 ----------------
  function beep(ok) {
    try {
      const a = new (window.AudioContext || window.webkitAudioContext)(), o = a.createOscillator(), g = a.createGain();
      o.frequency.value = ok ? 880 : 220; o.connect(g); g.connect(a.destination); g.gain.value = 0.15; o.start(); setTimeout(() => { o.stop(); a.close(); }, ok ? 120 : 450);
    } catch { /* 没声音也行 */ }
  }
  function renderCur(msg = "", bad = false) {
    if (!CUR) { $("#ho-cur").classList.add("hidden"); return; }
    $("#ho-cur").classList.remove("hidden");
    const closed = !!CUR.closed_at;
    $("#ho-info").innerHTML = `交接单 <b>#${CUR.id}</b> · <span data-notr>${esc(CUR.carrier || "未填物流")}</span> · ${esc(CUR.method_zh || "")}
      · 已扫 <b class="big-n">${CUR.count}</b> 件${CUR.cod_total ? ` · 货到付款合计 ${H().money(CUR.cod_total)}` : ""}
      ${closed ? ` · <span class="ok">已于 ${fmtTime(CUR.closed_at)} 交接完成</span>` : ""}`;
    if (msg !== null) $("#ho-msg").innerHTML = msg ? `<span class="${bad ? "bad big-msg" : "ok"}">${esc(msg)}</span>` : "";
    $("#ho-table tbody").innerHTML = CUR.orders.map((o, i) => `<tr><td>${i + 1}</td><td class="mono" data-notr><b>${esc(o.tracking_no || "（无运单号）")}</b></td>
      <td class="mono" data-notr>${esc(o.order_no)}</td><td>${esc(H().PLAT[o.platform] || o.platform || "")}</td><td>${o.n_items}</td>
      <td>${o.cod ? H().money(o.cod) : ""}</td><td>${esc(o.status_zh)}</td>
      <td>${closed ? "" : `<button class="mini" data-horm="${o.id}">移出</button>`}</td></tr>`).join("") || '<tr><td colspan="8" class="muted">扫描包裹上的运单号…</td></tr>';
    $("#ho-code").disabled = closed;
    $("#ho-close").disabled = closed || !CUR.count;
    $("#ho-del").classList.toggle("hidden", closed);
    $("#ho-print").href = `/print/handover?id=${CUR.id}`;
  }
  async function loadHO() {
    const r = await api("/api/handovers");
    $("#ho-list tbody").innerHTML = r.items.map((h) => `<tr><td>#${h.id}</td><td data-notr>${esc(h.carrier || "")}</td><td>${esc(h.method_zh || "")}</td>
      <td>${h.count}</td><td class="small">${fmtTime(h.created_at)} <span data-notr>${esc(h.username || "")}</span></td>
      <td class="small">${h.closed_at ? fmtTime(h.closed_at) : '<span class="warn">进行中</span>'}</td>
      <td class="nowrap"><button class="mini" data-hoopen="${h.id}">${h.closed_at ? "查看" : "继续扫"}</button>
        <a class="btn mini-btn" target="_blank" href="/print/handover?id=${h.id}">打印</a></td></tr>`).join("")
      || '<tr><td colspan="7" class="muted">还没有交接记录</td></tr>';
    if (CUR) { try { CUR = await api(`/api/handovers/${CUR.id}`); } catch { CUR = null; } renderCur(null); }
  }
  $("#ho-open").addEventListener("click", (e) => busy(e.target, async () => {
    CUR = await api("/api/handovers", { json: { carrier: $("#ho-carrier").value.trim(), method: $("#ho-method").value } });
    renderCur(""); loadHO(); $("#ho-code").focus();
  }));
  $("#ho-code").addEventListener("keydown", async (e) => {
    if (e.key !== "Enter" || !CUR) return;
    const code = e.target.value.trim();
    e.target.value = "";
    if (!code) return;
    try {
      const r = await api(`/api/handovers/${CUR.id}/scan`, { json: { code } });
      CUR = r.handover;
      beep(!r.warn.length);
      renderCur(`✔ ${r.order.order_no}` + (r.warn.length ? `（注意：${r.warn.join("；")}）` : ""), !!r.warn.length);
      loadHO();
    } catch (err) { beep(false); renderCur(err.message, true); }
  });
  $("#ho-table").addEventListener("click", async (e) => {
    const id = e.target.dataset.horm;
    if (!id) return;
    try { CUR = await api(`/api/handovers/${CUR.id}/remove`, { json: { order_id: +id } }); renderCur("已移出"); } catch (err) { toast(err.message, true); }
  });
  $("#ho-close").addEventListener("click", (e) => {
    if (!CUR || !confirm(`确认这 ${CUR.count} 件包裹已经交给快递？这些订单会全部标记为「已发货」。`)) return;
    busy(e.target, async () => {
      const r = await api(`/api/handovers/${CUR.id}/close`, { json: {} });
      CUR = r.handover; toast(`交接完成：${r.count} 件，标记已发货 ${r.shipped} 个订单`); renderCur(""); loadHO();
    });
  });
  $("#ho-del").addEventListener("click", async () => {
    if (!CUR || !confirmDelete("这张交接单（订单不受影响，只是不在这张单里了）")) return;
    try { await api(`/api/handovers/${CUR.id}`, { method: "DELETE" }); CUR = null; renderCur(); loadHO(); } catch (err) { toast(err.message, true); }
  });
  $("#ho-list").addEventListener("click", async (e) => {
    const id = e.target.dataset.hoopen;
    if (!id) return;
    try { CUR = await api(`/api/handovers/${id}`); renderCur(""); if (!CUR.closed_at) $("#ho-code").focus(); } catch (err) { toast(err.message, true); }
  });

  // ---------------- 买家档案 ----------------
  const LV_CLS = { vip: "ok-pill", wholesale: "tag-pill", watch: "warn-pill", blacklist: "bad-pill" };
  let LEVELS = null;
  async function loadBuyers() {
    const lv = $("#by-level").value;
    const q = new URLSearchParams({ q: $("#by-q").value.trim(), level: lv.startsWith("__") ? "" : lv, risky: lv === "__risky" ? "1" : "" });
    const r = await api("/api/buyers?" + q);
    if (!LEVELS) {
      LEVELS = Object.fromEntries(["", "vip", "wholesale", "watch", "blacklist"].filter((k) => k in r.levels).map((k) => [k, r.levels[k]]));
      $("#by-level").insertAdjacentHTML("beforeend", Object.entries(LEVELS).filter(([k]) => k).map(([k, v]) => `<option value="${k}">只看「${esc(v)}」</option>`).join(""));
    }
    $("#by-table tbody").innerHTML = r.items.map((b) => `<tr data-bkey="${esc(b.key)}">
      <td><b data-notr>${esc(b.name || "")}</b><div class="small muted" data-notr>${esc(b.key_show)}</div></td>
      <td><select data-blevel>${Object.entries(LEVELS).map(([k, v]) => `<option value="${k}" ${k === b.level ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
        ${b.level ? `<span class="pill ${LV_CLS[b.level] || ""}">${esc(b.level_zh)}</span>` : ""}</td>
      <td>${b.orders}</td><td>${b.refused ? `<b class="bad">${b.refused}</b>` : 0}</td><td>${b.returned || 0}</td>
      <td class="c-cost">${b.spent != null ? H().money(b.spent) : ""}</td><td class="small">${b.last ? fmtTime(b.last).slice(0, 10) : ""}</td>
      <td><input data-bnote value="${esc(b.note || "")}" style="width:180px" data-notr></td>
      <td class="nowrap"><button class="mini" data-bsave>保存</button> <button class="mini" data-borders>订单</button></td></tr>`).join("")
      || '<tr><td colspan="9" class="muted">还没有需要关注的买家</td></tr>';
  }
  $("#by-level").addEventListener("change", loadBuyers);
  { let t = null; $("#by-q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(loadBuyers, 300); }); }
  $("#by-table").addEventListener("click", async (e) => {
    const tr = e.target.closest("[data-bkey]");
    if (!tr) return;
    if (e.target.dataset.bsave !== undefined) {
      try {
        await api("/api/buyers", { json: { key: tr.dataset.bkey, level: tr.querySelector("[data-blevel]").value, note: tr.querySelector("[data-bnote]").value } });
        toast("已保存"); loadBuyers();
      } catch (err) { toast(err.message, true); }
    }
    if (e.target.dataset.borders !== undefined && window.OPS) OPS.filterBuyer(tr.dataset.bkey);
  });

  window.SHIP = { show, loadHO, loadBuyers };
})();
