"use strict";
// 工作台、数据备份（打包核对在订单模块 pack.js，售后在 aftersales.js）
(function () {
  const H = () => window.OPSH;
  function show(name) {
    if (name === "dashboard") loadDash();
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
    $("#dash").innerHTML = `<div id="dash-todo"></div>${cs ? '<div id="dash-cs"></div>' : ""}
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
    window.TODO_UI.card($("#dash-todo"));         // v2.46 今日待办
    if (cs && window.MODKIT) MODKIT.load("cs").then(() => window.CSREC && CSREC.dash($("#dash-cs"))).catch(() => {});   // v2.30：客服是模块
  }
  // （v2.24 客服报告在上面：loadDash 末尾填）

  // ---------------- 今日待办（v2.46，core/todo.py）：工作台上的卡片，运营分析模块的「今日待办」页面也用这里画列表 ----------------
  const TTH = () => window.I18N && I18N.lang === "th";
  const TZ = (zh, th) => (TTH() ? th : zh);
  const tr = (s) => (window.I18N && I18N.t ? I18N.t(s) : s);
  function todoRows(items, limit) {
    return items.slice(0, limit || items.length).map((i) => `<div class="todo-it lv-${esc(i.level)}${i.state ? " is-done" : ""}">
      <div class="todo-tx"><b ${i.tab ? `data-todo-go="${esc(i.tab)}"` : ""}>${esc(TTH() ? (i.title_th || tr(i.title)) : i.title)}</b>
        ${i.detail ? `<div class="small muted">${esc(TTH() ? (i.detail_th || tr(i.detail)) : i.detail)}</div>` : ""}</div>
      <div class="todo-bt nowrap">${i.state ? `<span class="small muted">${i.state === "done" ? TZ("已完成", "เสร็จแล้ว") : TZ("已忽略", "ข้ามแล้ว")}</span>
        <button class="mini" data-todo-k="${esc(i.key)}" data-todo-s="">${TZ("恢复", "คืนค่า")}</button>`
        : `<button class="mini" data-todo-k="${esc(i.key)}" data-todo-s="done">${TZ("完成", "เสร็จ")}</button><button class="mini" data-todo-k="${esc(i.key)}" data-todo-s="ignored">${TZ("忽略", "ข้าม")}</button>`}</div></div>`).join("");
  }
  // 按分组画（完整页面用）；limit = 每组最多几条（工作台卡片用总条数）
  function todoRender(box, d, opts = {}) {
    const items = d.items || [];
    let html = "";
    if (opts.flat) html = todoRows(items, opts.limit);
    else {
      for (const g of d.groups || []) {
        const its = items.filter((i) => i.group === g.zh);
        if (its.length) html += `<div class="todo-grp"><h4>${esc(TZ(g.zh, g.th))} <span class="muted">· ${its.length}</span></h4>${todoRows(its)}</div>`;
      }
    }
    box.innerHTML = html || `<p class="muted">${TZ("今天没有待办 🎉", "วันนี้ไม่มีงานค้าง 🎉")}</p>`;
  }
  async function todoAct(e, reload) {
    const b = e.target.closest("[data-todo-k]");
    if (b) {
      await busy(b, () => api("/api/todo/state", { json: { key: b.dataset.todoK, state: b.dataset.todoS } }));
      return reload();
    }
    const g = e.target.closest("[data-todo-go]");
    if (g && g.dataset.todoGo) goTab(g.dataset.todoGo);
  }
  async function todoCard(box) {
    if (!box) return;
    let d;
    try { d = await api("/api/todo"); } catch { box.innerHTML = ""; return; }
    const n = (d.items || []).length;
    const bad = (d.items || []).filter((i) => i.level === "bad").length;
    const full = $('#subnav .tab[data-tab="ops_todo"]');
    box.innerHTML = `<div class="card todo-card"><h3>${TZ("今日待办", "งานวันนี้")} <span class="muted small">${n}${bad ? ` · <span class="bad">${TZ("紧急", "ด่วน")} ${bad}</span>` : ""}${d.hidden ? ` · ${TZ("已完成 / 忽略", "เสร็จ / ข้าม")} ${d.hidden}` : ""}</span>
      ${full && !full.classList.contains("role-hidden") ? `<button class="mini" data-todo-go="ops_todo">${TZ("全部待办", "ดูทั้งหมด")}</button>` : ""}</h3><div class="todo-list"></div></div>`;
    todoRender($(".todo-list", box), d, { flat: true, limit: 8 });
    if (n > 8) $(".todo-list", box).insertAdjacentHTML("beforeend", `<div class="small muted">${TZ(`还有 ${n - 8} 条`, `อีก ${n - 8} รายการ`)}</div>`);
    box.onclick = (e) => todoAct(e, () => todoCard(box));
  }
  window.TODO_UI = { render: todoRender, act: todoAct, card: todoCard };
  $("#btn-dash-reload").addEventListener("click", (e) => busy(e.target, loadDash));
  $("#dash").addEventListener("click", (e) => { const g = e.target.closest("[data-go]"); if (g) showTab(g.dataset.go); });

  // v2.32：打包核对搬到订单模块（modules/orders/ui/pack.js）

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
