"use strict";
// 采购（v2.18）：采购单（草稿 → 下单·在途 → 到货入库）、付款、补货建议、供应商、财务记录
(function () {
  let VIEW = "open", META = null, SUP = [], ALLSUP = [];
  const TH = () => window.I18N && I18N.lang === "th";
  const num = (v, d = 2) => (v == null || v === "" ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const itName = (x) => (TH() && x.name_th ? x.name_th : x.name_zh) || "";
  const can = (k) => !!(META && META.perms && META.perms[k]);
  const ST_CLS = { draft: "warn", ordered: "", partial: "warn", received: "ok", cancelled: "muted" };
  const PAY_ZH = { paid: "已付清", partial: "部分付款", unpaid: "未付款" };

  async function load() {
    META = await api("/api/inv/meta");
    SUP = (await api("/api/inv/suppliers")).suppliers;
    $$("#tab-purchase [data-perm]").forEach((b) => b.classList.toggle("hidden", !can(b.dataset.perm)));
    render();
  }
  // v2.21：采购是单独的模块，几个页面共用这一个页面：采购单（进行中 / 全部）、补货建议、供应商、付款记录
  const TAB_VIEW = { po_suggest: "suggest", po_suppliers: "suppliers", po_pay: "finance" };
  const VIEW_TAB = { suggest: "po_suggest", suppliers: "po_suppliers", finance: "po_pay", open: "purchase", all: "purchase" };
  function show(name) {
    if (name !== "purchase" && !TAB_VIEW[name]) return;
    if (TAB_VIEW[name]) VIEW = TAB_VIEW[name];
    else if (!["open", "all"].includes(VIEW)) VIEW = "open";
    load().catch((e) => toast(e.message, true));
  }
  function setView(v) {        // 换到别的页面：菜单也跟着换
    VIEW = v;
    if (typeof CUR_TAB !== "undefined" && VIEW_TAB[v] !== CUR_TAB) return goTab(VIEW_TAB[v]);
    render();
  }
  async function summary() {
    try {
      const r = await api("/api/inv/po-summary");
      $("#po-sum").innerHTML = `<div>进行中<b>${r.open}</b></div><div>在途金额<b>฿${num(r.in_transit)}</b></div><div>还没付清<b class="${r.unpaid ? "warn" : ""}">฿${num(r.unpaid)}</b></div>
        <div>本月到货<b>฿${num(r.month_received)}</b></div><div>本月付款<b>฿${num(r.month_paid)}</b></div>`;
    } catch { $("#po-sum").innerHTML = ""; }
  }
  function render() {
    $$("#po-views [data-pv]").forEach((b) => b.classList.toggle("on", b.dataset.pv === VIEW));
    $("#po-views").classList.toggle("hidden", !["open", "all"].includes(VIEW));
    summary();
    if (VIEW === "suggest") return renderSuggest();
    if (VIEW === "suppliers") return renderSuppliers();
    if (VIEW === "finance") return renderFinance();
    return renderList(VIEW === "open" ? "open" : "");
  }

  // ---------------- 采购单列表 ----------------
  async function renderList(status) {
    const r = await api(`/api/inv/po?status=${status}`);
    window.PO_STATUS = r.status; window.PO_METHODS = r.methods;
    $("#po-body").innerHTML = `<table class="grid small"><thead><tr><th>单号</th><th>供应商</th><th>状态</th><th>预计到货</th><th>行数</th><th>金额</th><th>付款</th><th>创建</th><th></th></tr></thead><tbody>` +
      (r.po.map((p) => `<tr><td class="mono" data-notr>${esc(p.no)}</td><td data-notr>${esc((p.supplier || {}).name || "—")}</td>
        <td><span class="${ST_CLS[p.status] || ""}">${esc(r.status[p.status] || p.status)}</span></td><td>${esc(p.expected_date || "")}</td>
        <td>${p.lines.length}</td><td>฿${num(p.total)}</td><td>${PAY_ZH[p.pay_status]}${p.paid ? ` <span class="muted">฿${num(p.paid)}</span>` : ""}</td>
        <td class="nowrap">${fmtTime(p.created_at)}</td><td><button class="mini" data-po="${p.id}">打开</button></td></tr>`).join("") ||
        `<tr><td colspan="9" class="muted">${status === "open" ? "没有进行中的采购单" : "还没有采购单"}</td></tr>`) + "</tbody></table>";
  }

  // ---------------- 新建 / 编辑采购单 ----------------
  async function poForm(po) {
    const items = (await api("/api/inv/items")).items;
    const opts = (sel) => `<option value="">${TH() ? "เลือกรายการ" : "选物品"}</option>` + items.map((it) => `<option value="${it.id}" data-cat="${esc(it.category)}" data-unit="${esc(it.unit)}" data-cost="${it.avg_cost || ""}" ${+sel === it.id ? "selected" : ""}>${esc(it.code)} · ${esc(itName(it))}</option>`).join("");
    const row = (l = {}) => `<tr><td><select data-l="item_id" data-notr>${opts(l.item_id)}</select></td>
      <td class="nowrap"><input data-l="qty" type="number" step="any" value="${l.rolls ? "" : (l.qty ?? "")}" style="width:80px"> <span class="muted po-unit"></span>
        <span class="po-roll ${l.rolls ? "" : "hidden"}"><input data-l="rolls" type="number" step="1" value="${l.rolls ?? ""}" style="width:50px"> <span>${TH() ? "ม้วน" : "卷"}</span> ×
          <input data-l="net_g" type="number" value="${l.net_g ?? 1000}" style="width:60px"> g <input data-l="brand" value="${esc(l.brand || "")}" style="width:70px" data-notr></span></td>
      <td><input data-l="unit_cost" type="number" step="any" value="${l.unit_cost ?? ""}" style="width:80px"></td>
      <td><input data-l="note" value="${esc(l.note || "")}" style="width:110px" data-notr></td><td><button class="mini danger" data-rm>✕</button></td></tr>`;
    const p = po || { lines: [{}], ship_fee: 0, other_fee: 0 };
    const m = MODAL.open(`<h3>${po ? `采购单 <span data-notr>${esc(po.no)}</span>` : "新采购单"}</h3>
      <div class="form4"><label>供应商<select id="pf-sup" data-notr><option value="">—</option>${SUP.map((s) => `<option value="${s.id}" ${s.id === p.supplier_id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
        <label>预计到货日期<input id="pf-exp" type="date" value="${esc(p.expected_date || "")}"></label>
        <label>运费（฿）<input id="pf-ship" type="number" step="any" value="${p.ship_fee || 0}"></label>
        <label>其他费用（฿）<input id="pf-other" type="number" step="any" value="${p.other_fee || 0}"></label>
        <label>备注<input id="pf-note" value="${esc(p.note || "")}" data-notr></label></div>
      <p class="muted small">耗材可以按卷填（卷数 × 每卷克数），单价填每克的价格；其他物品按自己的单位。运费和其他费用到货时按金额分摊进单价。</p>
      <table class="grid small" id="pf-lines"><thead><tr><th>物品</th><th>数量</th><th>单价（฿）</th><th>备注</th><th></th></tr></thead><tbody>${p.lines.map(row).join("")}</tbody></table>
      <button class="mini" id="pf-add">＋ 加一行</button> <span id="pf-sum" class="small"></span>
      <div class="row gap" style="margin-top:8px"><button class="primary" id="pf-save">保存草稿</button><button id="pf-save-order">保存并下单</button><button data-mclose>取消</button></div>`);
    m.classList.add("wide");
    const tb = m.querySelector("#pf-lines tbody");
    const sync = (tr) => {
      const o = tr.querySelector('[data-l="item_id"]').selectedOptions[0];
      const fil = o && o.dataset.cat === "filament";
      tr.querySelector(".po-roll").classList.toggle("hidden", !fil);
      tr.querySelector('[data-l="qty"]').classList.toggle("hidden", fil && tr.querySelector('[data-l="rolls"]').value !== "");
      tr.querySelector(".po-unit").textContent = o && !fil ? (o.dataset.unit || "") : (fil ? "g" : "");
      const uc = tr.querySelector('[data-l="unit_cost"]'); if (o && !uc.value && o.dataset.cost) uc.value = Number(o.dataset.cost).toFixed(fil ? 4 : 2);
    };
    const sum = () => {
      let t = 0;
      [...tb.rows].forEach((tr) => { const g = (k) => tr.querySelector(`[data-l="${k}"]`).value;
        const q = g("rolls") ? (+g("rolls")) * (+g("net_g") || 1000) : +g("qty"); t += (q || 0) * (+g("unit_cost") || 0); });
      t += (+m.querySelector("#pf-ship").value || 0) + (+m.querySelector("#pf-other").value || 0);
      m.querySelector("#pf-sum").innerHTML = `合计 <b>฿${num(t)}</b>`;
    };
    [...tb.rows].forEach(sync); sum();
    m.querySelector("#pf-add").onclick = () => { tb.insertAdjacentHTML("beforeend", row()); };
    m.onclick = (e) => { if (e.target.dataset.rm !== undefined && tb.rows.length > 1) { e.target.closest("tr").remove(); sum(); } };
    m.onchange = (e) => { const tr = e.target.closest("tr"); if (tr && tr.closest("#pf-lines")) sync(tr); sum(); };
    m.oninput = sum;
    const save = (andOrder) => async () => {
      const lines = [...tb.rows].map((tr) => { const d = {}; tr.querySelectorAll("[data-l]").forEach((el) => { if (el.value !== "" && !el.closest(".hidden")) d[el.dataset.l] = el.value; }); return d; }).filter((d) => d.item_id);
      const body = { id: po ? po.id : undefined, supplier_id: m.querySelector("#pf-sup").value, expected_date: m.querySelector("#pf-exp").value,
        ship_fee: m.querySelector("#pf-ship").value, other_fee: m.querySelector("#pf-other").value, note: m.querySelector("#pf-note").value };
      if (!po || po.status === "draft") body.lines = lines;
      let r = await api("/api/inv/po", { json: body });
      if (andOrder) r = await api(`/api/inv/po/${r.po.id}/order`, { method: "POST" });
      toast(andOrder ? "已下单，在途中" : "已保存"); MODAL.close(); setView("open");
    };
    m.querySelector("#pf-save").onclick = (e) => busy(e.target, save(false));
    m.querySelector("#pf-save-order").onclick = (e) => busy(e.target, save(true));
  }

  // ---------------- 采购单详情：下单、到货、付款 ----------------
  async function poView(id) {
    const po = (await api(`/api/inv/po/${id}`)).po;
    const open = po.status === "ordered" || po.status === "partial";
    const lines = po.lines.map((l) => {
      const left = Math.max(0, (l.qty || 0) - (l.received || 0));
      const roll = l.rolls ? ` <span class="muted" data-notr>（${l.rolls} ${TH() ? "ม้วน" : "卷"} × ${num(l.net_g, 0)} g）</span>` : "";
      return `<tr><td data-notr>${esc(l.code)} ${esc(itName(l))}</td><td>${num(l.qty)} ${esc(l.unit)}${roll}</td><td>฿${num(l.unit_cost, 4)}</td>
        <td>฿${num((l.qty || 0) * (l.unit_cost || 0))}</td><td>${num(l.received || 0)}</td>
        <td>${open && left > 0 ? `<input type="number" step="any" data-rcv="${l.id}" placeholder="${l.rolls ? num(left / (l.net_g || 1000), 2) + (TH() ? " ม้วน" : " 卷") : num(left)}" style="width:80px">` : ""}</td></tr>`;
    }).join("");
    const m = MODAL.open(`<h3>采购单 <span data-notr>${esc(po.no)}</span> <span class="${ST_CLS[po.status] || ""}">${esc(window.PO_STATUS ? PO_STATUS[po.status] : po.status_zh)}</span></h3>
      <p class="small"><span data-notr>${esc((po.supplier || {}).name || "")}</span>${po.expected_date ? ` · <span>预计到货</span> ${esc(po.expected_date)}` : ""}${po.tracking ? ` · <span>运单</span> <span data-notr>${esc(po.tracking)}</span>` : ""}
        ${po.note ? ` · <span data-notr>${esc(po.note)}</span>` : ""}</p>
      <table class="grid small"><thead><tr><th>物品</th><th>数量</th><th>单价</th><th>金额</th><th>已到</th><th>${open ? "这次到货" : ""}</th></tr></thead><tbody>${lines}</tbody></table>
      <p class="small"><span>货款</span> ฿${num(po.goods_total)} + <span>运费</span> ฿${num(po.ship_fee)} + <span>其他</span> ฿${num(po.other_fee)} = <b>฿${num(po.total)}</b> ·
        <span>已付</span> <b>฿${num(po.paid)}</b>（<span>${PAY_ZH[po.pay_status]}</span>）</p>
      ${po.payments.length ? `<div class="small muted">${po.payments.map((x) => `${esc(x.day)} ฿${num(x.amount)} <span data-notr>${esc(x.method || "")} ${esc(x.note || "")}</span>`).join("<br>")}</div>` : ""}
      ${po.docs && po.docs.length ? `<p class="small">入库单：<span data-notr>${po.docs.map((d) => esc(d.no)).join("、")}</span></p>` : ""}
      <div class="row gap wrap" style="margin-top:8px">
        ${po.status === "draft" && can("inv.in") ? '<button id="pv-edit">修改</button><button class="primary" id="pv-order">下单（变在途）</button>' : ""}
        ${open && can("inv.in") ? '<button class="primary" id="pv-rcv">到货入库（填了数量的行）</button><button id="pv-rcv-all">全部到货</button>' : ""}
        ${po.status === "partial" && can("inv.in") ? '<button id="pv-close">结单（剩下的不要了）</button>' : ""}
        ${open && can("inv.in") ? '<button id="pv-track">填运单号</button>' : ""}
        ${po.status !== "cancelled" && can("inv.pay") && po.pay_status !== "paid" ? '<button id="pv-pay">记付款</button>' : ""}
        ${["draft", "ordered"].includes(po.status) && can("inv.in") ? '<button class="danger" id="pv-cancel">取消采购单</button>' : ""}
        <button data-mclose>关闭</button></div>`);
    m.classList.add("wide");
    const act = (a, body) => async () => { await api(`/api/inv/po/${po.id}/${a}`, { json: body || {} }); toast("已完成"); MODAL.close(); render(); };
    const on = (sel, fn) => { const b = m.querySelector(sel); if (b) b.onclick = (e) => busy(e.target, fn); };
    on("#pv-edit", async () => { MODAL.close(); await poForm(po); });
    on("#pv-order", act("order"));
    on("#pv-rcv", async () => {
      const q = {}; m.querySelectorAll("[data-rcv]").forEach((el) => { if (el.value !== "") q[el.dataset.rcv] = el.value; });
      if (!Object.keys(q).length) throw new Error("先在「这次到货」填数量（耗材按卷的行填卷数）");
      await act("receive", { qtys: q })();
    });
    on("#pv-rcv-all", async () => { if (confirm("剩下的全部到货入库？")) await act("receive", {})(); });
    on("#pv-close", async () => { if (confirm("结单后剩下没到的不再等了？")) await act("close")(); });
    on("#pv-cancel", async () => { if (confirm("取消这张采购单？")) await act("cancel")(); });
    on("#pv-track", async () => { const t = prompt("运单号", po.tracking || ""); if (t != null) await act("tracking", { tracking: t })(); });
    on("#pv-pay", async () => {
      const left = Math.max(0, po.total - po.paid);
      const a = prompt(`付款金额（฿），还没付 ${num(left)}`, left.toFixed(2)); if (a == null) return;
      const meth = prompt(`付款方式（${(window.PO_METHODS || []).join(" / ")}）`, "转账"); if (meth == null) return;
      await act("pay", { amount: a, method: meth })();
    });
  }

  // ---------------- 补货建议 ----------------
  async function renderSuggest() {
    const r = await api("/api/inv/suggest");
    const sname = (id) => (SUP.find((s) => s.id === id) || {}).name || "（没设默认供应商）";
    $("#po-body").innerHTML = (r.items.length && can("inv.in") ? `<div class="row gap" style="margin-bottom:6px"><button class="primary" id="sg-po">选中的生成采购单（按供应商分开）</button></div>` : "") +
      `<table class="grid small"><thead><tr><th><input type="checkbox" id="sg-all" checked></th><th>物品</th><th>现有</th><th>在途</th><th>建议买</th><th>默认供应商</th><th>原因</th></tr></thead><tbody>` +
      (r.items.map((x) => `<tr><td><input type="checkbox" data-sg="${x.item.id}" checked></td><td data-notr>${esc(x.item.code)} ${esc(itName(x.item))}</td>
        <td>${num(x.item.qty)} ${esc(x.item.unit)}</td><td>${x.transit ? num(x.transit) : ""}</td>
        <td><b>${x.rolls ? x.rolls + (TH() ? " ม้วน" : " 卷") : num(x.qty) + " " + esc(x.item.unit)}</b></td><td data-notr>${esc(sname(x.item.supplier_id))}</td>
        <td class="muted" data-notr>${esc(x.why)}</td></tr>`).join("") || '<tr><td colspan="7" class="muted">现在不用补货（物品要先设「补货线」）</td></tr>') + "</tbody></table>";
    const all = $("#sg-all"); if (all) all.onchange = () => $$("[data-sg]").forEach((x) => (x.checked = all.checked));
    const b = $("#sg-po");
    if (b) b.onclick = () => busy(b, async () => {
      const ids = $$("[data-sg]:checked").map((x) => +x.dataset.sg);
      if (!ids.length) throw new Error("先勾选");
      const rr = await api("/api/inv/suggest/po", { json: { item_ids: ids } });
      toast(TH() ? `สร้างใบสั่งซื้อร่าง ${rr.po.length} ใบ` : `已生成 ${rr.po.length} 张采购单草稿`); setView("open");
    });
  }

  // ---------------- 供应商 ----------------
  async function renderSuppliers() {
    const r = await api("/api/inv/suppliers?all=1");
    ALLSUP = r.suppliers;
    $("#po-body").innerHTML = `<table class="grid small"><thead><tr><th>名称</th><th>联系人</th><th>电话</th><th>平台 / 渠道</th><th>到货天数</th><th>备注</th><th></th></tr></thead><tbody>` +
      (r.suppliers.map((s) => `<tr class="${s.active ? "" : "muted"}"><td data-notr>${esc(s.name)}</td><td data-notr>${esc(s.contact || "")}</td><td data-notr>${esc(s.phone || "")}</td>
        <td data-notr>${s.link ? `<a href="${esc(s.link)}" target="_blank" rel="noopener">${esc(s.platform || "链接")}</a>` : esc(s.platform || "")}</td>
        <td>${s.lead_days ?? ""}</td><td class="muted" data-notr>${esc(s.note || "")}</td><td><button class="mini" data-sup="${s.id}">修改</button></td></tr>`).join("") ||
        '<tr><td colspan="7" class="muted">还没有供应商（点「＋ 供应商」添加）</td></tr>') + "</tbody></table>";
  }
  function supForm(s) {
    s = s || { active: 1 };
    const f = (k, l, t = "text") => `<label>${l}<input data-s="${k}" type="${t}" value="${esc(s[k] ?? "")}" data-notr></label>`;
    const m = MODAL.open(`<h3>${s.id ? "修改供应商" : "新供应商"}</h3><div class="form3">${f("name", "名称")}${f("contact", "联系人")}${f("phone", "电话")}
      ${f("platform", "平台 / 渠道（Shopee 店、1688、线下…）")}${f("link", "店铺 / 购买链接")}${f("lead_days", "一般几天到货", "number")}${f("note", "备注")}
      ${s.id ? `<label><span>启用</span><select data-s="active"><option value="1" ${s.active ? "selected" : ""}>是</option><option value="0" ${s.active ? "" : "selected"}>否</option></select></label>` : ""}</div>
      <div class="row gap"><button class="primary" id="sf-ok">保存</button><button data-mclose>取消</button></div>`);
    m.querySelector("#sf-ok").onclick = (e) => busy(e.target, async () => {
      const d = { id: s.id }; m.querySelectorAll("[data-s]").forEach((el) => (d[el.dataset.s] = el.value));
      await api("/api/inv/suppliers", { json: d }); toast("已保存"); MODAL.close(); await load(); setView("suppliers");
    });
  }

  // ---------------- 财务记录 ----------------
  async function renderFinance() {
    const r = await api("/api/inv/finance");
    const mo = r.month;
    $("#po-body").innerHTML = `<div class="card-sub small"><b><span>本月</span> <span data-notr>${esc(mo.month)}</span></b> · <span>采购到货</span> ฿${num(mo.purchases_received)} · <span>付款</span> ฿${num(mo.payments)} ·
        <span>库存消耗</span> ฿${num(mo.consumption_total)}
        <div class="muted">${mo.consumption_by_category.map((x) => `<span data-notr>${esc(x.label)}</span> ฿${num(x.amount)}`).join(" · ")}</div>
        <div class="muted">这些付款会自动算进「财务 → 现金流」。外部财务软件用「财务」权限的 API 密钥读取：GET /api/v1/finance/events、/api/v1/finance/inventory?month=YYYY-MM（见接口说明）。</div></div>
      <table class="grid small"><thead><tr><th>时间</th><th>类型</th><th>金额</th><th>单号</th><th>方式</th><th>说明</th><th>经手</th></tr></thead><tbody>` +
      (r.events.map((x) => `<tr><td class="nowrap">${esc(x.day)}</td><td>${esc(x.kind_zh)}</td><td>฿${num(x.amount)}</td><td class="mono" data-notr>${esc(x.ref_no || "")}</td>
        <td data-notr>${esc(x.method || "")}</td><td class="muted" data-notr>${esc(x.note || "")}</td><td data-notr>${esc(x.username || "")}</td></tr>`).join("") ||
        '<tr><td colspan="7" class="muted">还没有记录</td></tr>') + "</tbody></table>";
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#tab-purchase")) return;
    const v = e.target.closest("[data-pv]"); if (v) return setView(v.dataset.pv);
    const p = e.target.closest("[data-po]"); if (p) return poView(+p.dataset.po).catch((er) => toast(er.message, true));
    const s = e.target.closest("[data-sup]"); if (s) return supForm(ALLSUP.find((x) => x.id === +s.dataset.sup) || null);
    if (e.target.id === "po-new") return poForm(null).catch((er) => toast(er.message, true));
    if (e.target.id === "sup-new") return supForm(null);
    if (e.target.id === "po-reload") return load();
  });
  window.PURCHASE = { show, load };
})();
