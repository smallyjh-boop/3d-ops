"use strict";
// 工作台、数据备份（打包核对在订单模块 pack.js，售后在 aftersales.js）
(function () {
  const H = () => window.OPSH;
  function show(name) {
    if (name === "dashboard") loadDash();
    if (name === "backup") loadBackups();
  }

  // ---------------- 工作台（v2.49 按角色：老板 / 上架客服 / 生产打包；统一用 static/ux.js 的卡片） ----------------
  const ZT = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (ZT() ? th : zh);
  const tabOk = (t) => { const b = $(`#subnav .tab[data-tab="${t}"]`); return !!b && !b.classList.contains("role-hidden"); };
  const go = (t) => (tabOk(t) ? "tab:" + t : "");
  const roleOf = () => (typeof ME !== "undefined" && ME ? ME.role : "owner");
  async function loadDash() {
    const role = roleOf();
    const [d, todo, cs] = await Promise.all([
      api("/api/dashboard"),
      api("/api/todo").catch(() => ({ items: [], groups: [] })),
      tabOk("cs") ? api("/api/cs/stats").catch(() => null) : Promise.resolve(null),     // 客服（有客服页面的人才看得到）
    ]);
    const h = H();
    const own = h.isOwner();
    const items = (todo.items || []).filter((i) => !i.state);
    const tr7 = d.trend || [];
    const today = d.today_cal || {};
    const csUn = cs ? (cs.overdue || 0) : null;
    const sum7 = (k) => tr7.reduce((a, x) => a + (x[k] || 0), 0);
    let kp = [];
    if (own) {
      kp = [
        { icon: "🧾", label: Z("今天订单", "ออเดอร์วันนี้"), value: today.orders ?? d.new_today, spark: tr7.map((x) => x.orders), go: go("orders"),
          sub: Z(`近 7 天 ${sum7("orders")} 单`, `7 วัน ${sum7("orders")} ออเดอร์`) },
        { icon: "💰", label: Z("今天销售额", "ยอดขายวันนี้"), value: h.money(today.revenue || 0), spark: tr7.map((x) => x.revenue), go: go("ops_overview") || go("fin_overview"),
          sub: Z(`近 7 天 ${h.money(sum7("revenue"))}`, `7 วัน ${h.money(sum7("revenue"))}`) },
        { icon: "📈", label: Z("今天利润", "กำไรวันนี้"), value: h.money(today.profit || 0), spark: tr7.map((x) => x.profit), tone: (today.profit || 0) < 0 ? "bad" : "ok",
          go: go("fin_overview") || go("ops_overview"), sub: Z(`近 7 天 ${h.money(sum7("profit"))}`, `7 วัน ${h.money(sum7("profit"))}`),
          help: Z("扣了平台费、生产成本、当天的支出和售后损失，和「财务」同一个算法", "หักค่าธรรมเนียม ต้นทุนผลิต ค่าใช้จ่ายและความเสียหายหลังการขายของวันนั้น คิดแบบเดียวกับโมดูลการเงิน") },
        cs ? { icon: "💬", label: Z("客服超时未回复", "แชทค้างตอบ"), value: csUn, tone: csUn ? "bad" : "ok", go: go("csdash") || go("cs"),
          sub: Z(`需人工 ${cs.human || 0}`, `ต้องตอบเอง ${cs.human || 0}`) } : null,
        { icon: "📦", label: Z("待发货", "รอจัดส่ง"), value: d.orders_active, tone: d.overdue.length ? "bad" : d.due_today ? "warn" : "", go: go("orders"),
          sub: Z(`已超时 ${d.overdue.length} · 今天要发 ${d.due_today}`, `เลยเวลา ${d.overdue.length} · ส่งวันนี้ ${d.due_today}`) },
      ];
    } else if (role === "production") {
      kp = [
        { icon: "🖨", label: Z("排队打印", "คิวพิมพ์"), value: d.queue_jobs, sub: Z(`${d.queue_pcs} 件`, `${d.queue_pcs} ชิ้น`), go: go("production") },
        { icon: "⏳", label: Z("正在打印", "กำลังพิมพ์"), value: d.runs, go: go("production") },
        { icon: "🧹", label: Z("待后处理", "รอเก็บงาน"), value: d.post, tone: d.post ? "warn" : "", go: go("production") },
        { icon: "📦", label: Z("待打包", "รอแพ็ก"), value: d.packed || 0, go: go("pack"), help: Z("打印、后处理都完成了，等着装箱的生产任务", "งานพิมพ์ที่เสร็จและเก็บงานแล้ว รอแพ็ก") },
        { icon: "🚚", label: Z("今天要发", "ต้องส่งวันนี้"), value: d.due_today, tone: d.overdue.length ? "bad" : d.due_today ? "warn" : "", go: go("handover") || go("orders"),
          sub: Z(`已超时 ${d.overdue.length} · 打包好待发 ${d.ready_to_ship}`, `เลยเวลา ${d.overdue.length} · แพ็กแล้วรอส่ง ${d.ready_to_ship}`) },
        { icon: "⚠", label: Z("今天失败", "พิมพ์เสียวันนี้"), value: d.fails_today, tone: d.fails_today ? "bad" : "ok", go: go("quality") },
      ];
    } else {
      kp = [
        cs ? { icon: "💬", label: Z("客服超时未回复", "แชทค้างตอบ"), value: csUn, tone: csUn ? "bad" : "ok", go: go("cs"), sub: Z(`需人工 ${cs.human || 0}`, `ต้องตอบเอง ${cs.human || 0}`) } : null,
        d.to_list != null ? { icon: "🛒", label: Z("待上架", "รอลงขาย"), value: d.to_list, tone: d.to_list ? "warn" : "ok", go: go("export"),
          sub: d.drafts ? Z(`草稿 ${d.drafts}`, `ฉบับร่าง ${d.drafts}`) : "", help: Z("没导出 / 没推到平台过的在售产品", "สินค้าที่ยังไม่เคยส่งออก/ส่งขึ้นแพลตฟอร์ม") } : null,
        d.sugg_pending != null ? { icon: "💡", label: Z("待确认的建议", "คำแนะนำรอยืนยัน"), value: d.sugg_pending, tone: d.sugg_pending ? "warn" : "", go: go("ops_sugg") } : null,
        { icon: "🔎", label: Z("待审核订单", "ออเดอร์รอตรวจ"), value: d.review || 0, tone: d.review ? "warn" : "", go: go("orders") },
        { icon: "🧾", label: Z("售后处理中", "หลังการขายที่ค้าง"), value: d.aftersales_open, tone: d.aftersales_overdue ? "bad" : "", go: go("aftersales"),
          sub: d.aftersales_overdue ? Z(`快到期 / 超期 ${d.aftersales_overdue}`, `ใกล้/เกินกำหนด ${d.aftersales_overdue}`) : "" },
      ];
    }
    // 要马上处理：🔔 里紧急 / 注意的前几条
    const top = items.filter((i) => i.level !== "info").slice(0, 6);
    const todoCard = UX.card({ title: Z("要马上处理", "ต้องจัดการด่วน"), right: items.length ? `<button class="mini" data-home-bell>🔔 ${Z(`全部待办 ${items.length}`, `งานทั้งหมด ${items.length}`)}</button>` : "",
      body: top.length ? `<div class="home-todo">${top.map(todoItem).join("")}</div>` : UX.empty(Z("没有紧急的事 🎉", "ไม่มีเรื่องด่วน 🎉")) });
    let side = "";
    if (own) {
      // 异常：超时订单、差评、亏本、耗材、接口出错……（按待办分组和订单 / 生产数据数一下）
      const cnt = (g, lv) => items.filter((i) => i.group === g && (!lv || i.level === lv)).length;
      const an = [
        [Z("超时未发货", "เลยเวลาส่ง"), d.overdue.length, "bad", "orders"],
        [Z("差评没回复", "รีวิวแย่ยังไม่ตอบ"), cnt("评价"), "bad", "ops_lazada"],
        [Z("亏本订单", "ออเดอร์ขาดทุน"), cnt("利润"), "warn", "ops_dash"],
        [Z("耗材不够 / 该补货", "วัสดุไม่พอ / ควรเติม"), (d.low_material || []).length, (d.low_material || []).some((m) => m.short) ? "bad" : "warn", "materials"],
        [Z("平台接口出错", "API แพลตฟอร์มผิดพลาด"), cnt("平台接口", "bad"), "bad", "ops_lazada"],
        [Z("打印机报警", "เครื่องพิมพ์แจ้งเตือน"), (d.alerts || []).length, "bad", "production"],
        [Z("售后快到期 / 超期", "หลังการขายใกล้/เกินกำหนด"), d.aftersales_overdue || 0, "warn", "aftersales"],
      ].filter((x) => x[1]);
      side = UX.card({ title: Z("异常", "ความผิดปกติ"), help: Z("数字来自待办和订单 / 生产数据；点一行去处理", "ตัวเลขจากงานที่ต้องทำและข้อมูลออเดอร์/การผลิต กดแถวเพื่อไปจัดการ"),
        body: an.length ? UX.bars(an.map(([l, n, t, tab]) => ({ label: l, value: n, tone: t, go: go(tab) }))) : UX.empty(Z("一切正常", "ทุกอย่างปกติ")) });
    } else if (cs) side = '<div id="dash-cs"></div>';
    const prs = d.printers.map((p) => `<div class="dp ${p.enabled === false ? "lane-off" : ""}"><b class="pcode" data-notr>${esc(p.code || "")}</b> <span class="small muted" data-notr>${esc(p.name)}</span> ${h.stChip({ state: p.state, progress: p.progress, remaining_min: p.remaining_min }, p.state_zh)}
      ${p.file && p.state === "printing" ? `<div class="small muted" data-notr>${esc(p.file)}</div>` : ""}</div>`).join("");
    const list = (title, arr, fmt, tab) => (arr && arr.length ? UX.card({ title, right: tab && tabOk(tab) ? `<button class="mini" data-go="${tab}">${Z("去处理", "ไปจัดการ")}</button>` : "",
      body: `<div class="home-list">${arr.map(fmt).join("")}</div>` }) : "");
    const prodCards = [
      list(Z("⚠ 打印机报警", "⚠ เครื่องพิมพ์แจ้งเตือน"), d.alerts, (a) => `<div class="small">${esc(h.printerName(a.printer))} · <span class="mono" data-notr>${esc(a.sku || "")}</span>：${esc(a.alert)}</div>`, "production"),
      list(Z("耗材提醒", "แจ้งเตือนวัสดุ"), d.material_alerts || [], (a) => `<div class="small ${a.level === "bad" ? "bad" : ""}">${a.level === "bad" ? "⚠ " : ""}${esc(a.text)}</div>`, "materials"),
      list(Z("耗材该买了", "ควรซื้อวัสดุ"), d.low_material, (m) => `<div class="small">${esc(m.material)} ${h.colorTxt(m.color)} ${m.short ? `<b class="bad">${Z("不够打待打印的单", "ไม่พอพิมพ์งานที่รอ")}</b>` : Z(`还能用 ${h.num(m.days_left, 0)} 天`, `ใช้ได้อีก ${h.num(m.days_left, 0)} วัน`)}</div>`, "materials"),
      list(Z("耗材该烘干了（防潮）", "ควรอบวัสดุ (กันชื้น)"), d.humid, (m) => `<div class="small">${esc(m.material)} ${h.colorTxt(m.color)} ${Z(`开封/烘干后 ${m.days} 天`, `เปิด/อบแล้ว ${m.days} วัน`)}</div>`, "materials"),
      list(Z("打印机该保养了", "เครื่องพิมพ์ถึงเวลาบำรุง"), d.maintenance, (m) => `<div class="small" data-notr>${esc(m.printer)}：${esc(m.label)}</div>`, "printers"),
      list(Z("建议备货", "แนะนำเตรียมสต็อก"), d.stock_suggest, (x) => `<div class="small"><span class="mono" data-p360="${esc(x.sku)}" data-notr>${esc(x.sku)}</span> ${Z(`建议打 ${x.suggest} 个`, `แนะนำพิมพ์ ${x.suggest} ชิ้น`)}</div>`, "stock"),
    ].filter(Boolean);
    let showPrinters = role !== "listing" && d.printers.length;
    if (!side && showPrinters) { side = UX.card({ title: Z("打印机", "เครื่องพิมพ์"), body: `<div class="home-prs">${prs}</div>` }); showPrinters = false; }    // 生产：打印机放在待办旁边
    $("#dash").innerHTML = `${UX.kpis(kp)}
      <div class="home-grid ${side ? "" : "one"}">${todoCard}${side || ""}</div>
      ${own && cs ? '<div id="dash-cs" style="margin-top:14px"></div>' : ""}
      ${showPrinters ? UX.card({ title: Z("打印机", "เครื่องพิมพ์"), body: `<div class="home-prs">${prs}</div>` }) : ""}
      ${role !== "listing" && prodCards.length ? `<div class="lanes two">${prodCards.join("")}</div>` : ""}`;
    if (cs && $("#dash-cs") && window.MODKIT) MODKIT.load("cs").then(() => window.CSREC && CSREC.dash($("#dash-cs"))).catch(() => {});   // v2.30：客服是模块
  }
  function todoItem(i) {
    const title = ZT() ? (i.title_th || tr(i.title)) : i.title;
    const det = i.detail ? (ZT() ? (i.detail_th || tr(i.detail)) : i.detail) : "";
    return `<div class="sh-it lv-${esc(i.level)}"><div class="sh-it-t"><b data-notr>${esc(title)}</b>${det ? `<div class="small muted" data-notr>${esc(det)}</div>` : ""}</div>
      <div class="sh-it-b">${i.tab ? `<button class="mini primary" data-todo-go="${esc(i.tab)}">${Z("去处理", "ไปจัดการ")}</button>` : ""}
        <button class="mini" data-todo-k="${esc(i.key)}" data-todo-s="done">${Z("完成", "เสร็จ")}</button></div></div>`;
  }

  // （v2.24 客服报告在上面：loadDash 末尾填）

  // ---------------- 待办列表画法（v2.46，core/todo.py）；v2.49 起主要在右上角 🔔 抽屉（static/shell.js），这里留给别的页面用 ----------------
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
    box.innerHTML = `<div class="card todo-card"><h3>${TZ("待办", "งานที่ต้องทำ")} <span class="muted small">${n}${bad ? ` · <span class="bad">${TZ("紧急", "ด่วน")} ${bad}</span>` : ""}${d.hidden ? ` · ${TZ("已完成 / 忽略", "เสร็จ / ข้าม")} ${d.hidden}` : ""}</span>
      <button class="mini" data-todo-go="ops_todo">${TZ("全部待办", "ดูทั้งหมด")}</button></h3><div class="todo-list"></div></div>`;
    todoRender($(".todo-list", box), d, { flat: true, limit: 8 });
    if (n > 8) $(".todo-list", box).insertAdjacentHTML("beforeend", `<div class="small muted">${TZ(`还有 ${n - 8} 条`, `อีก ${n - 8} รายการ`)}</div>`);
    box.onclick = (e) => todoAct(e, () => todoCard(box));
  }
  window.TODO_UI = { render: todoRender, act: todoAct, card: todoCard };
  $("#btn-dash-reload").addEventListener("click", (e) => busy(e.target, loadDash));
  $("#dash").addEventListener("click", async (e) => {
    const g = e.target.closest("[data-go]");
    if (g) return showTab(g.dataset.go);
    if (e.target.closest("[data-home-bell]")) return window.SHELL && SHELL.openTodo();
    const k = e.target.closest("[data-todo-k]");
    if (k) { await busy(k, () => api("/api/todo/state", { json: { key: k.dataset.todoK, state: k.dataset.todoS } })); if (window.SHELL) SHELL.poll(); return loadDash(); }
    const t = e.target.closest("[data-todo-go]");
    if (t) goTab(t.dataset.todoGo);
  });

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
