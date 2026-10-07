// 任务中心 + 电脑加速（v2.20）
// · 右上角「任务」：所有耗时的操作（切片、上传模型、抠图、AI 文案…）都在后台做，这里看进度、读秒、在电脑还是 NAS 上做、失败重试；
//   离开页面也会继续做，做完弹提示（自己正在等的那个不重复提示）。
// · 设置 → 组件与插件：在线的电脑、下载加速程序、生成密钥。
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  let OPEN = false, ALL = false, LAST = {}, TIMER = null, DATA = { jobs: [], counts: {}, accel: {} };
  const me = () => (typeof ME !== "undefined" ? ME : null);
  const isOwner = () => !me() || me().role === "owner";
  const kindName = (k) => TR("task.k." + (k || "other"));

  function stText(j) {
    if (j.status === "done") return `<span class="ok">${TR("task.st.done")}</span>`;
    if (j.status === "error") return `<span class="bad">${TR("task.st.error")}</span>`;
    if (j.status === "queued" || j.stage === "queued") return `<span class="warn">${TR("task.st.queued")}</span>`;
    return `<span class="spin-dot"></span>${TR("task.st.running")}`;
  }
  function render() {
    const n = (DATA.counts.running || 0) + (DATA.counts.queued || 0);
    // 浮动的小按钮：修图、弹窗打开时顶栏被盖住，也能看到、点开任务中心
    let fl = $("#task-float");
    if (!fl) { fl = document.createElement("button"); fl.id = "task-float"; fl.className = "task-float hidden"; document.body.appendChild(fl); }
    fl.innerHTML = `⏱ ${TR("task.btn")} <b>${n}</b>`;
    fl.classList.toggle("hidden", !n);
    const badge = $("#task-n");
    if (badge) { badge.textContent = n; badge.classList.toggle("hidden", !n); }
    const btn = $("#task-btn");
    if (btn) btn.classList.toggle("on", n > 0);
    const box = $("#task-panel");
    if (!box || !OPEN) return;
    const ac = DATA.accel || {};
    const accLine = ac.enabled === false ? TR("task.accel_disabled")
      : (ac.online || []).length ? TR("task.accel_on", { names: ac.online.join("、") }) : TR("task.accel_off");
    box.innerHTML = `<div class="row between"><b>${TR("task.title")}</b><span class="row gap">
        ${isOwner() ? `<label class="small" style="white-space:nowrap;display:inline-flex;align-items:center;gap:4px"><input type="checkbox" id="task-all" ${ALL ? "checked" : ""}> ${TR("task.all")}</label>` : ""}
        <button class="mini" id="task-clear">${TR("task.clear")}</button><button class="mini" id="task-close">✕</button></span></div>
      <p class="small ${(ac.online || []).length ? "ok" : "muted"}" style="margin:4px 0 8px">${esc(accLine)}</p>` +
      (DATA.jobs.length ? DATA.jobs.map((j) => {
        const live = j.status === "running" || j.status === "queued";
        const where = typeof jobWhere === "function" ? jobWhere(j) : "";
        return `<div class="task-row ${j.status}" data-jid="${j.id}">
          <div class="row between"><span><b>${esc(kindName(j.kind))}</b>${j.link ? ` <span class="mono small" data-notr>${esc(j.link)}</span>` : ""}
            ${ALL && j.user ? ` <span class="muted small" data-notr>· ${esc(j.user)}</span>` : ""}</span>
            <span class="small">${stText(j)} · <span data-el="${live ? j.started : ""}">${TR("task.secs", { s: Math.round(j.elapsed) })}</span></span></div>
          ${live && where ? `<div class="small muted">${esc(where)}</div>` : ""}
          ${!live && j.where ? `<div class="small muted">${esc(jobWhere(j))}</div>` : ""}
          ${j.where === "NAS" && j.why_msg ? `<div class="small warn" data-notr>${esc(j.why_msg)}</div>` : ""}
          ${j.status === "error" ? `<div class="small bad" data-notr>${esc(String(j.error || "").slice(0, 300))}</div>` : ""}
          <div class="row gap">${j.status === "error" ? `<button class="mini" data-task-retry="${j.id}">${TR("task.retry")}</button>` : ""}
            ${j.link && /^[A-Za-z0-9_-]+$/.test(j.link) && j.status !== "running" ? `<button class="mini" data-task-open="${esc(j.link)}">${TR("task.open")}</button>` : ""}</div>
        </div>`;
      }).join("") : `<p class="muted small">${TR("task.none")}</p>`);
  }
  // 运行中的任务每秒更新读秒（不用每秒问服务器）
  setInterval(() => {
    if (!OPEN) return;
    document.querySelectorAll("#task-panel [data-el]").forEach((el) => {
      const t0 = +el.dataset.el; if (t0) el.textContent = TR("task.secs", { s: Math.round(Date.now() / 1000 - t0) });
    });
  }, 1000);

  async function poll() {
    clearTimeout(TIMER);
    try {
      const r = await api(`/api/bg/list${ALL ? "?all=1" : ""}`);
      DATA = r;
      for (const j of r.jobs) {
        const was = LAST[j.id];
        if (was && (was === "running" || was === "queued") && (j.status === "done" || j.status === "error") && !TASK_WATCH.has(j.id) && (!ALL || !me() || j.user === me().username)) {
          const label = kindName(j.kind) + (j.link ? " " + j.link : "");
          if (j.status === "done") toast(TR("task.done_toast", { label, s: Math.round(j.elapsed) }), false, 6000);
          else toast(TR("task.err_toast", { label, e: j.error || "" }), true);
        }
        LAST[j.id] = j.status;
      }
      render();
    } catch { /* 没登录 / 网络抖：下次再试 */ }
    const busy = (DATA.counts.running || 0) + (DATA.counts.queued || 0) > 0;
    TIMER = setTimeout(poll, OPEN || busy ? 3000 : 20000);
  }

  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (t.closest && t.closest("#task-btn, #task-float")) { OPEN = !OPEN; $("#task-panel").classList.toggle("hidden", !OPEN); render(); poll(); return; }
    if (t.id === "task-close") { OPEN = false; $("#task-panel").classList.add("hidden"); return; }
    if (t.id === "task-clear") { await api(`/api/bg/clear${ALL ? "?all=1" : ""}`, { json: {} }).catch(() => {}); poll(); return; }
    if (t.dataset && t.dataset.taskRetry) {
      try { await api(`/api/bg/${t.dataset.taskRetry}/retry`, { json: {} }); poll(); } catch (err) { toast(err.message, true); }
      return;
    }
    if (t.dataset && t.dataset.taskOpen) {
      OPEN = false; $("#task-panel").classList.add("hidden");
      if (typeof openProduct === "function") openProduct(t.dataset.taskOpen).catch((err) => toast(err.message, true));
    }
  });
  document.addEventListener("change", (e) => { if (e.target.id === "task-all") { ALL = e.target.checked; poll(); } });

  // ---------------- 设置 → 组件与插件 ----------------
  function ago(s) { return s < 90 ? TR("task.secs", { s }) : s < 7200 ? `${Math.round(s / 60)} min` : `${Math.round(s / 3600)} h`; }
  async function fillCard() {
    const box = $("#accel-card-body"); if (!box) return;
    let st;
    try { st = await api("/api/accel/status"); } catch (err) { box.innerHTML = `<span class="bad">${esc(err.message)}</span>`; return; }
    const ws = st.workers || [];
    box.innerHTML = (ws.length ? `<table class="grid small"><thead><tr><th>${TR("acc.h.name")}</th><th>${TR("acc.h.state")}</th><th>${TR("acc.h.can")}</th>
        <th>${TR("acc.h.hw")}</th><th>${TR("acc.h.count")}</th><th>${TR("acc.h.ver")}</th></tr></thead><tbody>` +
      ws.map((w) => `<tr><td data-notr><b>${esc(w.name)}</b><div class="muted">${esc(w.ip || "")} ${esc(w.os || "")}</div></td>
        <td>${w.online ? `<span class="ok">${w.busy ? TR("acc.busy", { n: w.busy }) : TR("acc.online")}</span>` : `<span class="muted">${TR("acc.offline", { ago: ago(w.ago) })}</span>`}</td>
        <td>${(w.caps || []).map((c) => TR("acc.k." + c)).join("、")}
          ${Object.entries(w.missing || {}).map(([k, v]) => `<div class="warn">${TR("acc.missing")}${TR("acc.k." + k)} — <span data-notr>${esc(v)}</span></div>`).join("")}
          ${w.installing ? `<div class="muted">${TR("acc.installing")}<span data-notr>${esc(w.installing)}</span></div>` : ""}</td>
        <td>${w.cpu ? TR("acc.cores", { n: w.cpu }) : ""}${w.gpu ? ` · <span data-notr>${esc(w.gpu)}</span>` : ""}</td>
        <td>${w.done || 0} / ${w.failed || 0}</td>
        <td data-notr>${esc(w.version || "")}${w.version_ok ? "" : ` <span class="warn">${TR("acc.ver_bad")}</span>`}</td></tr>`).join("") + "</tbody></table>"
      : `<p class="muted small">${TR("acc.none")}</p>`) +
      (Object.keys(st.last_local || {}).length ? `<p class="small"><b>${TR("acc.last_local")}</b>：` +
        Object.entries(st.last_local).map(([k, v]) => `${TR("acc.k." + (k === "mesh" ? "mesh" : k))} — ${TR("task.why." + (v.why || "no_pc"))}${v.msg ? ` <span class="muted" data-notr>(${esc(v.msg)})</span>` : ""}`).join("；") + "</p>" : "") +
      `<p class="small muted">${TR("acc.stats", { remote: st.stats.remote, local: st.stats.local, fallback: st.stats.fallback, slots: st.local_slots })}</p>` +
      ((st.recent || []).length ? `<details class="small"><summary>${TR("acc.recent")}</summary><table class="grid small">` +
        st.recent.map((r) => `<tr><td>${new Date(r.at * 1000).toLocaleTimeString()}</td><td>${esc(TR("acc.k." + (Object.keys(st.kinds).find((k) => st.kinds[k] === r.kind) || "mesh")))}</td>
          <td data-notr>${esc(r.worker || "")}</td><td>${TR("task.secs", { s: r.secs })}</td>
          <td>${r.status === "done" ? `<span class="ok">${TR("acc.r.ok")}</span>` : `<span class="warn">${TR("acc.r." + (["gave_up", "lost"].includes(r.status) ? r.status : "failed"))}</span>`}
          ${r.status === "failed" && r.msg ? ` <span class="muted" data-notr>${esc(r.msg)}</span>` : ""}</td></tr>`).join("") + "</table></details>" : "");
  }
  function card() {
    setTimeout(fillCard, 50);
    const url = location.origin;
    return `<div class="card cfg-group" id="accel-card" data-lock-skip><h3>${TR("acc.title")}</h3>
      <p class="small">${TR("acc.intro")}</p>
      <p class="small muted">${esc(TR("acc.steps", { url }))}</p>
      <div class="row gap" style="margin:6px 0">${isOwner() ? `<a class="btn mini" href="/api/accel/package" download>${TR("acc.download")}</a>
        <button class="mini" id="accel-key">${TR("acc.key")}</button>` : ""}<button class="mini" id="accel-refresh">${TR("acc.refresh")}</button></div>
      <div id="accel-key-out"></div><div id="accel-card-body" class="muted small">…</div></div>`;
  }
  document.addEventListener("click", async (e) => {
    if (e.target.id === "accel-refresh" || (e.target.closest && e.target.closest('[data-cfgtab="addons"]'))) fillCard();
    if (e.target.id === "accel-key") {
      try {
        const r = await api("/api/accel/key", { json: {} });
        $("#accel-key-out").innerHTML = `<p class="small">${TR("acc.key_done")} <input class="mono" readonly value="${esc(r.key)}" style="width:420px" data-notr onclick="this.select()"></p>`;
      } catch (err) { toast(err.message, true); }
    }
  });

  // 电脑加速卡片开着时每 10 秒刷新一次
  setInterval(() => { const c = $("#accel-card"); if (c && c.offsetParent) fillCard(); }, 10000);

  // 面板放到页面最外层（放在顶栏里会被修图、弹窗等盖住）
  const _p = $("#task-panel"); if (_p && _p.parentNode !== document.body) document.body.appendChild(_p);

  window.TASKS = { poke: () => { setTimeout(poll, 300); } };
  window.ACCEL = { card, refresh: fillCard };
  setTimeout(poll, 1500);
})();
