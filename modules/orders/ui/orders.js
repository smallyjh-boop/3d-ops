"use strict";
// 订单模块：订单列表（ERP 式）、修改订单、批量填运单号、导入、手工单、订单详情、每单利润。
// v2.34 从 static/ops.js 搬进模块；公用的小工具（PLAT、money、colorTxt、打印机名……）在内核 app.js 的 window.OPSH，
// API 密钥在内核（window.INTG_UI），「打开了哪个页面」由内核 showTab 通知各页面脚本。
(function () {
  const { PLAT, KIND_ZH, JOB_ZH, role, isOwner, money, num, day, short, colorTxt, today, printerName } = window.OPSH;
  let ORD_STATUS = {};
  let IMP = null;          // 当前导入预览

  function show(name) {
    if (name === "orders") loadOrders();
    if (name === "profit") loadProfit();
  }

  // ================= 订单（ERP 式）=================
  const OF = { tab: "waiting", page: 1 };
  let ORD_PAGE = null;
  const SEL = new Set();
  const STAGE_ZH = { none: "", waiting: "待生产", producing: "生产中", ready: "已打包待发", out: "已出库" };
  function ordFilters() {
    return { tab: OF.tab, page: OF.page, q: $("#ord-q").value.trim(), platform: $("#ord-platform").value, shop: $("#ord-shop").value,
      kind: $("#ord-kind").value, tag: $("#ord-tag").value, label: $("#ord-label").value, date_from: $("#ord-from").value, date_to: $("#ord-to").value,
      pay: $("#ord-pay").value, carrier: $("#ord-carrier").value, buyer_key: OF.buyer_key || "",
      sort: $("#ord-sort").value, page_size: 50 };
  }
  const qs = (o) => Object.entries(o).filter(([, v]) => v !== "" && v != null).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  async function loadOrders() {
    const r = await api("/api/orders?" + qs(ordFilters()));
    ORD_PAGE = r;
    ORD_STATUS = r.status_zh || {};
    $("#ord-tabs").innerHTML = (OF.buyer_key ? `<span class="pill tag-pill">只看这个买家的订单 <a class="link" id="ord-buyer-x">✕</a></span> ` : "") +
      r.tabs.map(([k, v]) => `<button class="otab ${k === OF.tab ? "on" : ""} ${["exception", "review", "urgent", "delivery_failed"].includes(k) && r.counts[k] ? "warnt" : ""}" data-otab="${k}">${esc(v)}
      <b>${r.counts[k] || 0}</b></button>`).join("");
    const fill = (sel, list, first) => { const cur = $(sel).value; $(sel).innerHTML = `<option value="">${first}</option>` +
      list.map((x) => `<option ${x === cur ? "selected" : ""} data-notr>${esc(x)}</option>`).join(""); };
    fill("#ord-shop", r.shops, "全部店铺");
    fill("#ord-tag", r.tags, "全部标签");
    fill("#ord-carrier", r.carriers || [], "全部物流");
    $("#ord-table tbody").innerHTML = r.orders.map((o) => {
      const items = o.items.map((i) => `<div class="${i.product_id ? "" : "bad"}"><span class="mono" data-notr>${esc(i.sku || "?")}</span> ×${i.qty} ${colorTxt(i.color)}</div>`).join("");
      const notes = (o.custom_note ? `<div class="note-flag" data-notr>✎ ${esc(o.custom_note)}</div>` : "") +
        (o.buyer_note ? `<div class="small muted" data-notr>💬 ${esc(o.buyer_note)}</div>` : "");
      const tags = (o.tags || "").split(",").filter(Boolean).map((t) => `<span class="pill tag-pill" data-notr>${esc(t)}</span>`).join(" ");
      const exc = (o.exceptions || []).map((x) => `<div class="bad small">⚠ ${esc(x)}</div>`).join("");
      const late = o.ship_by && o.ship_by < Date.now() / 1000 && ["waiting", "producing", "none"].includes(o.stage) && o.status === "to_ship";
      const hold = o.hold && o.status === "to_ship" ? `<div class="hold-flag small">⏸ 待审核：<span>${esc(o.hold_reason || "")}</span></div>` : "";
      return `<tr class="clickable ${SEL.has(o.id) ? "sel" : ""}" data-oid="${o.id}">
        <td><input type="checkbox" data-sel="${o.id}" ${SEL.has(o.id) ? "checked" : ""}></td>
        <td><b class="mono" data-notr>${esc(o.order_no)}</b>${o.priority ? ' <span class="pill bad-pill">加急</span>' : ""}
          <div class="small muted">${esc(PLAT[o.platform] || o.platform)} <span data-notr>${esc(o.shop || "")}</span>${KIND_ZH[o.kind] ? " · " + KIND_ZH[o.kind] : ""}</div></td>
        <td class="nowrap small">下单 ${short(o.order_time)}${o.ship_by ? `<div class="${late ? "bad" : "muted"}">最晚 ${short(o.ship_by)}</div>` : ""}
          ${o.status === "to_ship" && !["ready", "out"].includes(o.stage) ? countdown(o.ship_by) : ""}
          ${o.planned_done ? `<div class="muted">预计做完 ${short(o.planned_done)}</div>` : ""}</td>
        <td><span data-notr>${esc(o.receiver || o.buyer || "")}</span>${buyerPills(o)}${o.tracking_no ? `<div class="small mono muted" data-notr>${esc(o.tracking_no)}</div>` : ""}
          ${o.label_printed_at ? '<div class="small ok">🏷 已打面单</div>' : o.label_file ? '<div class="small">🏷 有平台面单</div>' : ""}</td>
        <td>${items}${notes}</td>
        <td class="c-cost nowrap">${money(o.order_total)}</td>
        <td><span class="ost ost-${esc(o.status)}">${esc(o.status_zh)}</span>${STAGE_ZH[o.stage] && o.status === "to_ship" ? `<div class="small">${STAGE_ZH[o.stage]}</div>` : ""}
          <div class="small">${progress(o.job_counts)}</div></td>
        <td>${hold}${exc}${tags}</td>
        <td class="nowrap">${role() !== "production" && CAN("orders.edit") ? `<button class="mini primary-lite" data-oedit="${o.id}">修改</button>` : ""}
          ${CAN("orders.delete") ? `<button class="mini danger" data-odel="${o.id}">删除</button>` : ""}</td></tr>`;
    }).join("") || '<tr><td colspan="9" class="muted">没有符合条件的订单。导入订单：点右上角「导入订单表格」。</td></tr>';
    const pages = Math.max(1, Math.ceil(r.total / r.page_size));
    $("#ord-pager").innerHTML = `<span class="small muted">共 ${r.total} 个订单</span>` + (pages > 1 ?
      `<button class="mini" data-pg="${r.page - 1}" ${r.page <= 1 ? "disabled" : ""}>上一页</button><span class="small">${r.page} / ${pages}</span>
       <button class="mini" data-pg="${r.page + 1}" ${r.page >= pages ? "disabled" : ""}>下一页</button>` : "") +
      (r.total > r.orders.length ? ` <button class="mini" id="ord-selall-filter">勾选全部 ${r.total} 个</button>` : "");
    $("#ord-all").checked = r.orders.length && r.orders.every((o) => SEL.has(o.id));
    $('#ord-bulk [data-bulk="delete"]').classList.toggle("hidden", !CAN("orders.delete"));
    updSel();
  }
  async function printLabels(ids) {
    const r = await api("/api/labels/check", { json: { ids } });
    if (r.have.length) window.open(`/print/labels?type=platform&ids=${r.have.join(",")}`, "_blank");
    if (r.missing.length) {
      const msg = r.have.length ? `另外 ${r.missing.length} 个订单没有平台面单，打印自制面单吗？` :
        `选中的 ${r.missing.length} 个订单没有平台面单（还没上传平台面单 PDF）。打印自制面单吗？`;
      if (confirm(msg)) window.open(`/print/labels?type=self&ids=${r.missing.join(",")}`, "_blank");
    }
    setTimeout(loadOrders, 1500);
  }
  $("#label-file").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await api("/api/labels/import", { method: "POST", body: fd });
      toast(`面单 PDF 共 ${r.pages} 页，对应上 ${r.matched} 个订单` + (r.unmatched_pages.length ? `；第 ${r.unmatched_pages.slice(0, 20).join("、")} 页没找到订单。${r.hint}` : ""), !!r.unmatched_pages.length);
      loadOrders();
    } catch (err) { toast(err.message, true); }
  });
  function updSel() {
    $("#ord-selinfo").textContent = SEL.size ? `已勾选 ${SEL.size} 个订单` : "勾选订单后批量处理";
    $("#ord-bulk").classList.toggle("on", SEL.size > 0);
  }
  function progress(jc) {
    const n = Object.values(jc || {}).reduce((a, b) => a + b, 0);
    if (!n) return "";
    return ["todo", "printing", "post", "packed", "done"].filter((k) => jc[k]).map((k) =>
      `<span class="jst jst-${k}">${JOB_ZH[k]} ${jc[k]}</span>`).join(" ");
  }
  // 发货倒计时：剩几小时 / 超时几小时
  function countdown(t) {
    if (!t) return "";
    const h = (t - Date.now() / 1000) / 3600;
    const txt = (x) => (x >= 48 ? `${Math.floor(x / 24)} 天` : x >= 1 ? `${Math.floor(x)} 小时` : `${Math.max(1, Math.round(x * 60))} 分钟`);
    if (h < 0) return `<span class="cd cd-over">超时 ${txt(-h)}</span>`;
    return `<span class="cd ${h < 6 ? "cd-hot" : h < 24 ? "cd-warn" : "cd-ok"}">剩 ${txt(h)}</span>`;
  }
  const BT = { vip: ["VIP", "ok-pill"], wholesale: ["批发客户", "tag-pill"], watch: ["需留意", "warn-pill"], blacklist: ["黑名单", "bad-pill"], new: ["新客", ""] };
  function buyerPills(o) {
    const out = [];
    if (o.is_cod) out.push('<span class="pill cod-pill">COD 货到付款</span>');
    (o.buyer_tags || []).forEach((t) => {
      const [k, n] = t.split(":");
      if (k === "refused") out.push(`<span class="pill bad-pill">拒收过 ${n} 次</span>`);
      else if (k === "repeat") out.push(`<span class="pill">回头客 ${n} 单</span>`);
      else if (BT[k] && k !== "new") out.push(`<span class="pill ${BT[k][1]}">${BT[k][0]}</span>`);
      else if (k === "new" && o.is_cod) out.push('<span class="pill warn-pill">新客</span>');
    });
    return out.length ? `<div class="bpills">${out.join(" ")}</div>` : "";
  }
  let qTimer = null;
  const reload1 = () => { OF.page = 1; loadOrders(); };
  $("#ord-q").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(reload1, 300); });
  ["#ord-platform", "#ord-shop", "#ord-kind", "#ord-tag", "#ord-label", "#ord-from", "#ord-to", "#ord-sort", "#ord-pay", "#ord-carrier"].forEach((k) => $(k).addEventListener("change", reload1));
  $("#btn-ord-reset").addEventListener("click", () => {
    OF.buyer_key = "";
    ["#ord-q", "#ord-platform", "#ord-shop", "#ord-kind", "#ord-tag", "#ord-label", "#ord-from", "#ord-to", "#ord-pay", "#ord-carrier"].forEach((k) => ($(k).value = ""));
    $("#ord-sort").value = "time_desc"; reload1();
  });
  $("#ord-tabs").addEventListener("click", (e) => {
    if (e.target.id === "ord-buyer-x") { OF.buyer_key = ""; reload1(); return; }
    const b = e.target.closest("[data-otab]");
    if (!b) return;
    OF.tab = b.dataset.otab; OF.page = 1; SEL.clear(); loadOrders();
  });
  $("#ord-pager").addEventListener("click", (e) => {
    if (e.target.dataset.pg) { OF.page = +e.target.dataset.pg; loadOrders(); }
    if (e.target.id === "ord-selall-filter") { ORD_PAGE.ids_all.forEach((i) => SEL.add(i)); loadOrders(); }
  });
  $("#ord-all").addEventListener("change", (e) => {
    (ORD_PAGE ? ORD_PAGE.orders : []).forEach((o) => (e.target.checked ? SEL.add(o.id) : SEL.delete(o.id)));
    loadOrders();
  });
  $("#ord-table").addEventListener("click", (e) => {
    const cb = e.target.closest("[data-sel]");
    if (cb) {
      const id = +cb.dataset.sel;
      cb.checked ? SEL.add(id) : SEL.delete(id);
      cb.closest("tr").classList.toggle("sel", cb.checked);
      updSel();
      return;
    }
    if (e.target.closest("td") && e.target.closest("td").cellIndex === 0) return;
    if (e.target.dataset.oedit) { editOrder(+e.target.dataset.oedit); return; }
    if (e.target.dataset.odel) {
      const id = +e.target.dataset.odel;
      if (!confirmDelete("这个订单（还没开始的生产任务也会删除）")) return;
      api("/api/orders/batch", { json: { ids: [id], action: "delete" } }).then(() => { SEL.delete(id); toast("已删除"); loadOrders(); }).catch((err) => toast(err.message, true));
      return;
    }
    const tr = e.target.closest("tr[data-oid]");
    if (tr) openOrder(+tr.dataset.oid);
  });

  const MONEY_ZH = { item_amount: "商品总额", buyer_shipping: "买家付的运费", platform_discount: "平台优惠", seller_discount: "卖家优惠",
    commission: "佣金", service_fee: "服务费", payment_fee: "支付手续费", settlement: "结算到账" };
  // ---- 修改订单（基本信息 + 商品明细） ----
  async function editOrder(oid) {
    let o;
    try { o = await api(`/api/orders/${oid}`); } catch (err) { toast(err.message, true); return; }
    let skus = [];
    try { const r = await api("/api/skus"); skus = Array.isArray(r) ? r : (r.skus || []); } catch { skus = []; }
    const locked = (o.jobs || []).some((j) => j.status !== "todo" || j.qty_done > 0 || j.run_id);
    const manual = !["lazada", "shopee", "tiktok"].includes(o.platform) || o.source === "manual";
    const itemRow = (i) => `<tr><td><input data-it="sku" list="oe-skus" value="${esc(i.sku || "")}" data-notr ${locked ? "readonly" : ""}></td>
      <td><input data-it="name" value="${esc(i.name || "")}" data-notr ${locked ? "readonly" : ""}></td>
      <td><input data-it="qty" type="number" min="1" value="${i.qty || 1}" style="width:70px" ${locked ? "readonly" : ""}></td>
      <td><input data-it="unit_price" type="number" step="0.01" value="${i.unit_price ?? ""}" style="width:90px" ${locked ? "readonly" : ""}></td>
      <td>${locked ? "" : '<button class="mini danger" data-itdel>✕</button>'}</td></tr>`;
    const el = MODAL.open(`<div class="row between"><h3>修改订单 <span class="mono" data-notr>${esc(o.order_no)}</span></h3><button class="mini" data-mclose>关闭</button></div>
      <datalist id="oe-skus" data-notr>${skus.map((x) => `<option value="${esc(x.sku)}">${esc((x.name || "") + " " + (x.color || ""))}</option>`).join("")}</datalist>
      <div class="form3">
        <label>订单号<input id="oe-no" value="${esc(o.order_no)}" data-notr ${manual ? "" : "readonly title='平台订单号不能改'"}></label>
        <label>买家<input id="oe-buyer" value="${esc(o.buyer || "")}" data-notr></label>
        <label>类型<select id="oe-kind">${Object.entries(KIND_ZH).map(([k, v]) => `<option value="${k}" ${k === (o.kind || "normal") ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
        <label>下单时间<input id="oe-time" type="datetime-local" value="${o.order_time ? fmtTime(o.order_time).replace(" ", "T") : ""}"></label>
        <label>最晚发货<input id="oe-shipby" type="datetime-local" value="${o.ship_by ? fmtTime(o.ship_by).replace(" ", "T") : ""}"></label>
        <label>订单状态<select id="oe-status">${Object.entries(ORD_STATUS).map(([k, v]) => `<option value="${k}" ${k === o.status ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
      </div>
      <h4>商品</h4>
      ${locked ? '<p class="warn small">这个订单已经开始打印，商品不能再改（可以改备注，或取消后重新下单）。</p>' : ""}
      <table class="grid small" id="oe-items"><thead><tr><th>SKU</th><th>品名（可空，自动按 SKU）</th><th>数量</th><th class="c-final">单价 ฿</th><th></th></tr></thead>
        <tbody>${(o.items || []).map(itemRow).join("")}</tbody></table>
      ${locked ? "" : '<button class="mini" id="oe-add">＋ 加一行商品</button>'}
      <div class="form3 c-final">
        <label>订单金额 ฿（空 = 不变，改商品时按差额调整）<input id="oe-total" type="number" step="0.01" value="" placeholder="${o.order_total ?? ""}"></label>
        <label>运费 ฿<input id="oe-ship" type="number" step="0.01" value="${o.shipping_fee ?? ""}"></label>
        <label>平台费 ฿<input id="oe-fee" type="number" step="0.01" value="${o.platform_fee ?? ""}"></label>
      </div>
      ${isOwner() ? `<details class="c-final"><summary class="small">金额明细（有就填，利润按真实扣费算）</summary><div class="form4">
        ${Object.entries(MONEY_ZH).map(([k, v]) => `<label>${v} ฿<input data-money="${k}" type="number" step="0.01" value="${o[k] ?? ""}"></label>`).join("")}</div></details>` : ""}
      <label>买家留言<textarea id="oe-bnote" rows="2" data-notr>${esc(o.buyer_note || "")}</textarea></label>
      <label>卖家备注<textarea id="oe-snote" rows="2" data-notr>${esc(o.seller_note || "")}</textarea></label>
      <label>定制要求 / 内部备注（生产任务上会显示）<textarea id="oe-cnote" rows="2" data-notr>${esc(o.custom_note || "")}</textarea></label>
      <div class="form3">
        <label>收件人<input id="oe-receiver" value="${esc(o.receiver || "")}" data-notr></label>
        <label>电话<input id="oe-phone" value="${esc(o.phone || "")}" data-notr></label>
        <label>邮编<input id="oe-postcode" value="${esc(o.postcode || "")}" data-notr></label>
        <label class="span2">地址<input id="oe-address" value="${esc(o.address || "")}" data-notr></label>
        <label>物流公司<input id="oe-carrier" value="${esc(o.carrier || "")}" data-notr></label>
        <label>运单号<input id="oe-track" value="${esc(o.tracking_no || "")}" data-notr></label>
        <label>货到付款 ฿<input id="oe-cod" type="number" value="${o.cod ?? ""}"></label>
      </div>
      <div class="row gap"><button class="big primary" id="oe-save">保存修改</button></div>`);
    $("#modal-in").classList.add("wide");
    el.onchange = (e) => {     // 选了 SKU：自动填品名和售价（空着的时候）
      if (e.target.dataset.it !== "sku") return;
      const x = skus.find((k) => k.sku.toUpperCase() === e.target.value.trim().toUpperCase());
      const tr = e.target.closest("tr");
      if (!x) return;
      if (!tr.querySelector('[data-it="name"]').value) tr.querySelector('[data-it="name"]').value = x.name || "";
      if (tr.querySelector('[data-it="unit_price"]').value === "" && x.price != null) tr.querySelector('[data-it="unit_price"]').value = x.price;
    };
    el.onclick = async (e) => {
      if (e.target.id === "oe-add") { $("#oe-items tbody", el).insertAdjacentHTML("beforeend", itemRow({ qty: 1 })); return; }
      if (e.target.dataset.itdel != null) { e.target.closest("tr").remove(); return; }
      if (e.target.id !== "oe-save") return;
      const v = (id) => $(id, el).value;
      if (v("#oe-status") !== o.status && ["cancelled", "delivery_failed"].includes(v("#oe-status")) && !confirm(`把订单状态改成「${ORD_STATUS[v("#oe-status")]}」？`)) return;
      const body = {
        order_no: v("#oe-no").trim(), buyer: v("#oe-buyer"), kind: v("#oe-kind"), status: v("#oe-status"),
        order_time: v("#oe-time").replace("T", " "), ship_by: v("#oe-shipby").replace("T", " "),
        buyer_note: v("#oe-bnote"), seller_note: v("#oe-snote"), custom_note: v("#oe-cnote"),
        receiver: v("#oe-receiver"), phone: v("#oe-phone"), postcode: v("#oe-postcode"), address: v("#oe-address"),
        carrier: v("#oe-carrier"), tracking_no: v("#oe-track"), cod: v("#oe-cod"),
      };
      if (isOwner()) {
        if (v("#oe-total") !== "") body.order_total = v("#oe-total");
        body.shipping_fee = v("#oe-ship"); body.platform_fee = v("#oe-fee");
        $$("[data-money]", el).forEach((i) => (body[i.dataset.money] = i.value));
      }
      if (!locked) {
        body.items = $$("#oe-items tbody tr", el).map((tr) => {
          const g = (k) => tr.querySelector(`[data-it="${k}"]`).value;
          return { sku: g("sku").trim(), name: g("name").trim(), qty: +g("qty") || 1, unit_price: g("unit_price") === "" ? null : +g("unit_price") };
        }).filter((x) => x.sku);
        if (!body.items.length) { toast("至少要有一个商品", true); return; }
      }
      await busy(e.target, async () => {
        await api(`/api/orders/${oid}/edit`, { json: body });
        MODAL.close(); toast("订单已修改"); loadOrders();
      });
    };
  }
  $("#ord-bulk").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-bulk]");
    if (!b) return;
    const ids = [...SEL];
    const [act, val] = b.dataset.bulk.split(":");
    if (act === "export") { location.href = "/api/orders/export?" + (ids.length ? "ids=" + ids.join(",") : qs({ ...ordFilters(), page: "" })); return; }
    if (!ids.length) { toast("请先勾选订单", true); return; }
    if (act === "pick" || act === "pack") { window.open(`/print/orders?type=${act}&ids=${ids.join(",")}`, "_blank"); return; }
    if (act === "label") { printLabels(ids); return; }
    let value = val;
    if (act === "hold") {
      value = prompt("挂起原因（例如：等买家确认颜色 / 疑似重复下单）", "等买家确认");
      if (value === null) return;
    }
    if (act === "status" && ["cancelled", "delivery_failed"].includes(val) && !CAN("orders.cancel")) { toast("你的账号没有「取消订单 / 标记拒收」的权限，请老板在 系统 → 设置 → 账号与权限 里开通", true); return; }
    if (act === "status" && val === "delivery_failed" && !confirm(`把这 ${ids.length} 个订单标记为「拒收/派送失败」？会自动登记售后，等包裹退回验货。`)) return;
    if (act === "tag_add" || act === "tag_remove") {
      value = prompt(act === "tag_add" ? "要加的标签（例如：VIP、催单、待确认设计）" : "要去掉的标签");
      if (!value) return;
    }
    if (act === "status" && val === "cancelled" && !confirm(`确定取消这 ${ids.length} 个订单？还没开始打印的任务会删除。`)) return;
    if (act === "delete" && !confirmDelete(`这 ${ids.length} 个订单`)) return;
    await busy(b, async () => {
      const r = await api("/api/orders/batch", { json: { ids, action: act, value: act === "priority" ? +val : value } });
      toast(`已处理 ${r.done} 个订单`);
      if (act === "delete") SEL.clear();
      await loadOrders();
    });
  });
  // ---- 批量填运单号 ----
  $("#btn-ord-track").addEventListener("click", () => {
    const el = MODAL.open(`<div class="row between"><h3>批量填运单号</h3><button class="mini" data-mclose>关闭</button></div>
      <p class="small muted">每行一个订单：<b>订单号, 运单号</b>（也可以加第三列物流公司）。用逗号、Tab 或空格分开都行，可以直接从 Excel 复制两列粘贴进来。</p>
      <textarea id="tr-text" rows="10" class="mono" placeholder="1234567890, TH0123456789&#10;1234567891, TH0123456790, Flash Express" data-notr></textarea>
      <label class="row"><input type="checkbox" id="tr-ship"> 同时把待发货的订单标记为「已发货」</label>
      <button class="primary" id="tr-go">导入</button><div id="tr-out" class="small"></div>`);
    $("#tr-go", el).onclick = (e) => busy(e.target, async () => {
      const r = await api("/api/orders/tracking-import", { json: { text: $("#tr-text", el).value, mark_shipped: $("#tr-ship", el).checked } });
      $("#tr-out", el).innerHTML = `<p class="ok">已填 ${r.updated} 个订单的运单号。</p>` +
        (r.not_found.length ? `<p class="bad">找不到这些订单号：<span data-notr>${r.not_found.map(esc).join("、")}</span></p>` : "") +
        (r.bad_lines.length ? `<p class="warn">第 ${r.bad_lines.join("、")} 行格式不对（要 订单号,运单号）</p>` : "");
      loadOrders();
    });
  });

  // ---- 导入 ----
  $("#ord-file").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    try {
      IMP = await api("/api/orders/import/preview", { method: "POST", body: fd });
    } catch (err) { toast(err.message, true); return; }
    $("#ord-result").classList.add("hidden");
    $("#ord-manual").classList.add("hidden");
    $("#imp-file").textContent = f.name;
    $("#imp-info").innerHTML = `共 ${IMP.rows} 行。` + (IMP.profile
      ? `<b class="ok">已识别为「<span data-notr>${esc(IMP.profile)}</span>」格式，列已自动对应好，直接点「确认导入」。</b>`
      : "请检查每一列对应的内容（必选：订单号、SKU）。已经自动猜好了，不对的改一下。");
    $("#imp-platform").value = IMP.platform || "";
    $("#imp-profile").value = IMP.profile || "";
    const opts = (cur) => `<option value="">（不用）</option>` + Object.entries(IMP.fields).map(([k, v]) =>
      `<option value="${k}" ${k === cur ? "selected" : ""}>${esc(v)}</option>`).join("");
    $("#imp-map tbody").innerHTML = IMP.headers.map((h, ci) => {
      if (!h && !IMP.sample.some((r) => r[ci])) return "";
      const sam = IMP.sample.slice(0, 3).map((r) => r[ci]).filter(Boolean).map((x) => esc(String(x).slice(0, 40))).join(" | ");
      const cur = IMP.mapping[String(ci)] || "";
      return `<tr class="${cur ? "mapped" : ""}"><td data-notr><b>${esc(h || "(第" + (ci + 1) + "列)")}</b></td><td class="small muted" data-notr>${sam}</td>
        <td><select data-ci="${ci}">${opts(cur)}</select></td></tr>`;
    }).join("");
    $("#ord-import").classList.remove("hidden");
    $("#ord-import").scrollIntoView({ behavior: "smooth" });
  });
  $("#imp-map").addEventListener("change", (e) => {
    const s = e.target.closest("select[data-ci]");
    if (!s) return;
    // 一个字段只能对应一列
    if (s.value) $$("#imp-map select[data-ci]").forEach((o) => { if (o !== s && o.value === s.value) { o.value = ""; o.closest("tr").classList.remove("mapped"); } });
    s.closest("tr").classList.toggle("mapped", !!s.value);
  });
  $("#btn-imp-cancel").addEventListener("click", () => { $("#ord-import").classList.add("hidden"); IMP = null; });
  $("#btn-imp-commit").addEventListener("click", (e) => busy(e.target, async () => {
    const mapping = {};
    $$("#imp-map select[data-ci]").forEach((s) => { if (s.value) mapping[s.dataset.ci] = s.value; });
    const r = await api("/api/orders/import/commit", { json: { token: IMP.token, mapping, platform: $("#imp-platform").value,
      profile: $("#imp-profile").value.trim() } });
    $("#ord-import").classList.add("hidden");
    IMP = null;
    const un = r.unmatched || [];
    $("#ord-result").innerHTML = `<div class="row between"><h3>导入完成</h3><button class="mini" onclick="this.closest('.card').classList.add('hidden')">关闭</button></div>
      <p>新订单 <b>${r.orders_new}</b> 个，更新 <b>${r.orders_updated}</b> 个，商品 ${r.items} 行。新生产任务 <b>${(r.jobs || {}).created || 0}</b> 个。
      ${(r.jobs || {}).cancelled ? `取消了 ${r.jobs.cancelled} 个还没打印的任务（订单已取消）。` : ""}
      ${r.skipped_items_locked ? `<span class="muted">${r.skipped_items_locked} 个订单已经在生产，商品明细没有改动。</span>` : ""}
      ${r.status_kept ? `<span class="muted">${r.status_kept} 个订单表格里的状态比系统里旧（例如系统里已发货、表格还是待发货），状态没改。</span>` : ""}
      ${r.held ? `<b class="warn">${r.held} 个新订单命中审单规则，已挂起到「待审核」（不会排产），请去看一下。</b>` : ""}</p>
      ${un.length ? `<p class="bad">以下 SKU 在产品库里找不到（不会生成生产任务，利润也算不准）：</p>
        <p data-notr>${un.map((u) => `<span class="pill bad-pill mono">${esc(u.sku)} ×${u.rows}</span>`).join(" ")}</p>
        <p class="muted small">处理方法：在产品库里把这个 SKU 填到对应产品的变体上（或新建产品），然后点「重新匹配 SKU」。</p>` : ""}`;
    $("#ord-result").classList.remove("hidden");
    toast("导入完成");
    loadOrders();
  }));
  $("#btn-ord-rematch").addEventListener("click", (e) => busy(e.target, async () => {
    const r = await api("/api/orders/rematch", { json: {} });
    toast(`新匹配上 ${r.matched} 行商品`);
    loadOrders();
  }));

  // ---- 手工订单 ----
  let SKUS = [];
  async function loadSkus() {
    try { SKUS = await api("/api/skus"); } catch { SKUS = []; }
    $("#sku-list").innerHTML = SKUS.map((s) => `<option value="${esc(s.sku)}">${esc(s.name)} ${esc(s.color)}</option>`).join("");
  }
  function manRow() {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><input data-k="sku" list="sku-list" style="width:150px" data-notr></td><td class="small" data-name data-notr></td>
      <td><input data-k="qty" type="number" min="1" value="1" style="width:70px"></td>
      <td class="c-final"><input data-k="unit_price" type="number" min="0" style="width:90px"></td>
      <td><button class="danger mini-x">✕</button></td>`;
    $("#man-items tbody").appendChild(tr);
  }
  $("#btn-ord-manual").addEventListener("click", async () => {
    $("#ord-import").classList.add("hidden");
    $("#ord-manual").classList.remove("hidden");
    $("#man-items tbody").innerHTML = "";
    ["#man-buyer", "#man-no", "#man-shipby", "#man-total", "#man-note", "#man-receiver", "#man-phone", "#man-postcode",
      "#man-address", "#man-carrier", "#man-track", "#man-cod"].forEach((k) => ($(k).value = ""));
    $("#man-priority").checked = false;
    manRow();
    await loadSkus();
  });
  $("#btn-man-cancel").addEventListener("click", () => $("#ord-manual").classList.add("hidden"));
  $("#btn-man-add").addEventListener("click", manRow);
  $("#man-items").addEventListener("click", (e) => { if (e.target.classList.contains("mini-x")) e.target.closest("tr").remove(); });
  $("#man-items").addEventListener("change", (e) => {
    if (e.target.dataset.k !== "sku") return;
    const tr = e.target.closest("tr"), s = SKUS.find((x) => x.sku.toUpperCase() === e.target.value.trim().toUpperCase());
    tr.querySelector("[data-name]").innerHTML = s ? `${esc(s.name)} ${colorTxt(s.color)}` : (e.target.value ? '<span class="bad">产品库里没有这个 SKU</span>' : "");
    const up = tr.querySelector('[data-k="unit_price"]');
    if (s && s.price && !up.value) up.value = s.price;
  });
  $("#btn-man-save").addEventListener("click", (e) => busy(e.target, async () => {
    const items = $$("#man-items tbody tr").map((tr) => {
      const o = {};
      tr.querySelectorAll("[data-k]").forEach((i) => (o[i.dataset.k] = i.value.trim()));
      return o;
    }).filter((i) => i.sku);
    if (!items.length) throw new Error("请至少填一个商品 SKU");
    const o = await api("/api/orders/manual", { json: {
      kind: $("#man-kind").value, buyer: $("#man-buyer").value, platform: $("#man-platform").value,
      order_no: $("#man-no").value, ship_by: $("#man-shipby").value, order_total: $("#man-total").value,
      priority: $("#man-priority").checked ? 1 : 0, custom_note: $("#man-note").value, items,
      receiver: $("#man-receiver").value, phone: $("#man-phone").value, postcode: $("#man-postcode").value,
      address: $("#man-address").value, carrier: $("#man-carrier").value, tracking_no: $("#man-track").value, cod: $("#man-cod").value } });
    $("#ord-manual").classList.add("hidden");
    toast(`已保存订单 ${o.order_no}`);
    OF.tab = "all";
    await loadOrders();
    openOrder(o.id);
  }));

  // ---- 订单详情 ----
  const SHIPM = { pickup: "上门揽收", dropoff: "送到网点", self: "自己送 / 其他" };
  const LEVELS = { "": "普通", vip: "VIP", wholesale: "批发客户", watch: "需留意", blacklist: "黑名单" };
  function buyerBox(o) {
    const b = o.buyer_profile;
    if (!b) return "";
    const canEdit = role() !== "production";
    const risky = b.level === "blacklist" || b.refused;
    return `<details class="buyer-box ${risky ? "risky" : ""}" ${risky ? "open" : ""}><summary><b>买家</b> <span data-notr>${esc(b.name || o.buyer || "")}</span>
        ${b.level ? `<span class="pill ${(BT[b.level] || [])[1] || ""}">${esc(LEVELS[b.level] || b.level)}</span>` : ""}
        <span class="small muted">共 ${b.orders} 单${b.completed ? ` · 已发/完成 ${b.completed}` : ""}</span>
        ${b.refused ? `<span class="pill bad-pill">拒收 ${b.refused} 次</span>` : ""}${b.returned ? `<span class="pill warn-pill">退货 ${b.returned} 次</span>` : ""}
        ${b.orders <= 1 ? '<span class="pill">第一次买</span>' : ""}</summary>
      <div class="small muted">${b.spent != null ? `累计消费 ${money(b.spent)} · ` : ""}首次下单 ${day(b.first)} · 最近 ${day(b.last)} · 平台 ${esc((b.platforms || []).join(", "))}</div>
      ${canEdit ? `<div class="row gap wrap"><label>分类<select id="od-blevel">${Object.entries(LEVELS).map(([k, v]) => `<option value="${k}" ${k === b.level ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
        <label style="flex:1">备注<input id="od-bnote" value="${esc(b.note || "")}" data-notr></label><button class="mini" id="od-buyer-save">保存</button>
        <button class="mini" id="od-buyer-orders">看他的全部订单</button></div>` : (b.note ? `<div class="small" data-notr>${esc(b.note)}</div>` : "")}
    </details>`;
  }
  const FEE_ZH = { commission: "佣金", service_fee: "服务费", payment_fee: "支付手续费", seller_discount: "卖家优惠", platform_discount: "平台优惠（平台出）", settlement: "结算到账" };
  function feeDetail(pr) {
    const d = pr.fee_detail || {};
    const src = { settlement: "平台费 = 订单金额 − 结算到账", detail: "平台费 = 佣金 + 服务费 + 支付手续费 + 卖家优惠", import: "平台费按导入的「平台费用」",
      estimate: "平台费按设置里的扣点估算（导入时带上佣金 / 结算金额会更准）" }[pr.fee_source] || "";
    return `<p class="small muted">${src}${Object.keys(d).length ? "：" + Object.entries(d).map(([k, v]) => `${FEE_ZH[k] || k} ${money(v)}`).join(" · ") : ""}</p>`;
  }
  // v2.35：发货出库——这单用哪个纸箱、发货时扣了什么（一张出库单）
  const U_TH = { "个": "ชิ้น", "卷": "ม้วน", "张": "แผ่น", "件": "ชิ้น", "米": "เมตร", "瓶": "ขวด", "盒": "กล่อง", "套": "ชุด", "g": "g" };
  function outBox(o) {
    const TH = window.I18N && I18N.lang === "th";
    const box = window.PACKBOX ? PACKBOX.html(o, "od-box") : "";
    const out = o.out;
    return `<h4>发货出库</h4><div class="row gap wrap small">${box}</div>
      ${out ? `<p class="small">出库单 <a href="#" class="mono" data-invdoc="${out.doc_id}" data-notr>${esc(out.no)}</a> · ${fmtTime(out.ts)}${out.status === "void" ? ' <span class="muted">（已作废）</span>' : ""}</p>
        <table class="grid small"><thead><tr><th>编码</th><th>名称</th><th>扣了</th><th>货位</th></tr></thead><tbody>
        ${out.lines.map((l) => `<tr><td class="mono" data-notr>${esc(l.code)}</td><td data-notr>${esc(TH && l.name_th ? l.name_th : l.name_zh)}</td>
          <td>${num(l.qty, 2)} <span data-notr>${esc((TH && U_TH[l.unit]) || l.unit || "")}</span></td><td class="mono" data-notr>${esc(l.location || "")}</td></tr>`).join("")}</tbody></table>`
        : `<p class="small muted">${["shipped", "completed"].includes(o.status) ? "这单没有出库记录（库存模块没开、发货出库关着，或者是导入时就已经发货的旧订单）。" : "发货时自动扣：用库存发的成品、上面这个纸箱、设置里每单 / 每件的包材，记成一张出库单。"}</p>`}`;
  }
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("[data-invdoc]");
    if (!a) return;
    e.preventDefault();
    if (window.INV && INV.docView) INV.docView(+a.dataset.invdoc).catch((er) => toast(er.message, true));
  });

  async function openOrder(oid) {
    let o;
    try { o = await api(`/api/orders/${oid}`); } catch (err) { toast(err.message, true); return; }
    if (window.PACKBOX) await PACKBOX.load();
    const d = $("#ord-detail");
    const pr = o.profit;
    const canEdit = role() !== "production";
    d.innerHTML = `<div class="drawer-in">
      <div class="row between"><h3>订单 <span class="mono" data-notr>${esc(o.order_no)}</span></h3>
        <div class="row gap">${canEdit ? '<div class="lockbar" id="od-lockbar"></div>' : ""}<button class="mini" data-x>关闭</button></div></div>
      <p class="small">${esc(PLAT[o.platform] || o.platform)} ${KIND_ZH[o.kind] ? "· " + KIND_ZH[o.kind] : ""} · 下单 ${fmtTime(o.order_time)}
        ${o.ship_by ? " · 最晚发货 " + fmtTime(o.ship_by) : ""} · 买家 <span data-notr>${esc(o.buyer || "-")}</span>
        ${o.tracking_no ? ` · 运单 <span class="mono" data-notr>${esc(o.tracking_no)}</span>` : ""}</p>
      ${o.hold && o.status === "to_ship" ? `<div class="hold-box"><b>⏸ 待审核（挂起中，不会排产）</b><div class="small">${esc(o.hold_reason || "")}</div>
        ${canEdit ? '<div class="row gap"><button class="primary" id="od-approve">✔ 审核通过，开始排产</button></div>' : ""}</div>`
        : o.status === "to_ship" && canEdit ? `<div class="row gap small muted">${o.reviewed_by ? `已审核（${esc(o.reviewed_by)}）` : ""}
          ${(o.review_flags || []).length ? `<span class="warn">规则提示：${esc(o.review_flags.join("；"))}</span>` : ""}
          <button class="mini" id="od-hold">⏸ 挂起</button></div>` : ""}
      ${buyerBox(o)}
      ${o.buyer_note ? `<p class="small">买家留言：<b data-notr>${esc(o.buyer_note)}</b></p>` : ""}
      ${o.seller_note ? `<p class="small">卖家备注：<span data-notr>${esc(o.seller_note)}</span></p>` : ""}
      <table class="grid small"><thead><tr><th>SKU</th><th>商品</th><th>颜色</th><th>数量</th><th class="c-final">金额</th><th>克数/时长</th></tr></thead><tbody>
      ${o.items.map((i) => `<tr><td class="mono" data-notr>${esc(i.sku)}</td><td data-notr>${esc(i.name || "")}${i.variation ? ` <span class="muted">(${esc(i.variation)})</span>` : ""}</td>
        <td>${colorTxt(i.color)}</td><td>${i.qty}</td><td class="c-final">${money(i.item_total)}</td>
        <td>${i.product_id ? (i.grams ? `${num(i.grams, 1)}g / ${num(i.hours)}h` : '<span class="warn">缺克数，请切片</span>') : '<span class="bad">没对上产品</span>'}</td></tr>`).join("")}
      </tbody></table>
      <label>定制要求 / 内部备注（生产任务上会显示）<textarea id="od-note" rows="3" data-notr ${canEdit ? "" : "readonly"}>${esc(o.custom_note || "")}</textarea></label>
      <details class="ship-box" ${o.receiver || o.address ? "" : ""} open><summary><b>收件与物流</b>
          ${o.label_printed_at ? `<span class="small ok">🏷 面单已打印 ${fmtTime(o.label_printed_at)}</span>` : o.label_file ? '<span class="small">🏷 有平台面单</span>' : ""}</summary>
        <div class="form3">
          <label>收件人<input id="od-receiver" value="${esc(o.receiver || "")}" data-notr ${canEdit ? "" : "readonly"}></label>
          <label>电话<input id="od-phone" value="${esc(o.phone || "")}" data-notr ${canEdit ? "" : "readonly"}></label>
          <label>邮编<input id="od-postcode" value="${esc(o.postcode || "")}" data-notr ${canEdit ? "" : "readonly"}></label>
          <label class="span2">地址<input id="od-address" value="${esc(o.address || "")}" data-notr ${canEdit ? "" : "readonly"}></label>
          <label>物流公司<input id="od-carrier" list="carrier-list" value="${esc(o.carrier || "")}" data-notr ${canEdit ? "" : "readonly"}></label>
          <label>货到付款 ฿<input id="od-cod" type="number" min="0" value="${o.cod ?? ""}" ${canEdit ? "" : "readonly"}></label>
          <label>发货方式<select id="od-shipm" ${canEdit ? "" : "disabled"}><option value="">（未设置）</option>${Object.entries(SHIPM).map(([k, v]) =>
            `<option value="${k}" ${k === o.ship_method ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
          <label>付款方式<span class="ro-val">${o.is_cod ? '<span class="pill cod-pill">货到付款 COD</span>' : o.payment ? `<span data-notr>${esc(o.payment)}</span>` : "在线已付"}</span></label>
          ${o.handover_id ? `<label>交接单<input value="#${o.handover_id}" readonly></label>` : ""}
        </div>
        <div class="row gap"><a class="btn" target="_blank" href="/print/labels?type=${o.label_file ? "platform" : "self"}&ids=${o.id}">🏷 打印面单</a>
          ${o.label_file ? `<a class="btn" target="_blank" href="/print/labels?type=platform&raw=1&ids=${o.id}" title="不加信息，原样打印平台给的 PDF">原样平台面单</a><a class="btn" target="_blank" href="/print/labels?type=self&ids=${o.id}">打印自制面单</a>` : ""}</div>
      </details>
      <div class="form3">
        <label>运单号<input id="od-track" value="${esc(o.tracking_no || "")}" data-notr ${canEdit ? "" : "readonly"}></label>
        <label>标签（逗号分隔）<input id="od-tags" value="${esc(o.tags || "")}" data-notr ${canEdit ? "" : "readonly"}></label>
        <label>最晚发货<input id="od-shipby" type="datetime-local" value="${o.ship_by ? fmtTime(o.ship_by).replace(" ", "T") : ""}" ${canEdit ? "" : "readonly"}></label>
      </div>
      <div class="row gap wrap">
        <label class="row"><input type="checkbox" id="od-priority" ${o.priority ? "checked" : ""} ${canEdit ? "" : "disabled"}> 加急（优先排单）</label>
        <label>订单状态<select id="od-status" ${canEdit ? "" : "disabled"}>${Object.entries(ORD_STATUS).map(([k, v]) => `<option value="${k}" ${k === o.status ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>

        <a class="btn" target="_blank" href="/print/orders?type=pack&ids=${o.id}">打印装箱单</a>
        ${canEdit ? '<button id="od-as">登记售后</button>' : ""}
        ${canEdit && CAN("orders.edit") ? '<button id="od-edit">✏ 修改订单（商品 / 金额 / 买家…）</button>' : ""}
        ${CAN("orders.delete") ? '<button class="danger" id="od-del">删除订单</button>' : ""}
      </div>
      <h4>生产任务</h4>
      ${o.jobs.length ? `<table class="grid small"><thead><tr><th>#</th><th>SKU</th><th>颜色</th><th>数量</th><th>已打盘数</th><th>打印机</th><th>状态</th><th>预计完成</th></tr></thead><tbody>
        ${o.jobs.map((j) => `<tr><td>${j.id}</td><td class="mono" data-notr>${esc(j.sku)}</td><td>${colorTxt(j.color)}</td><td>${j.qty}</td><td>${j.plates_done || 0}</td>
          <td data-notr>${esc(printerName(j.printer))}</td><td><span class="jst jst-${j.status}">${esc(JOB_ZH[j.status] || j.status)}</span>${j.fails ? ` <span class="bad small">失败 ${j.fails} 次</span>` : ""}${j.stock_n ? ` <span class="pill tag-pill">📦 ${(window.I18N && I18N.lang === "th") ? "ใช้สต็อก" : "用库存"} ×${j.stock_n}</span>` : ""}</td>
          <td class="small">${j.status === "todo" || j.status === "printing" ? short(j.planned_end) : ""}</td></tr>`).join("")}</tbody></table>`
        : '<p class="muted small">没有生产任务（订单不是待发货状态，或商品没对上产品）。</p>'}
      ${outBox(o)}
      ${pr ? `<h4>利润</h4><div class="summary small">
        <div>收入<b>${money(pr.revenue)}</b></div><div>平台费${pr.fee_estimated ? "（估）" : ""}<b>${money(pr.fee)}</b></div>
        <div>材料<b>${money(pr.material)}</b></div><div>机时<b>${money(pr.machine)}</b></div><div>包材+损耗<b>${money(pr.packaging + pr.failure)}</b></div>
        <div>利润<b class="${pr.profit < 0 ? "bad" : "ok"}">${money(pr.profit)}</b></div></div>
        ${feeDetail(pr)}
        ${pr.missing_data ? '<p class="warn small">有商品缺少克数/时长或没对上产品，成本偏低。</p>' : ""}` : ""}
      ${(o.aftersales || []).length ? `<h4>售后</h4>${o.aftersales.map((a) => `<div class="small">${fmtTime(a.created_at)} · <b>${esc(a.kind_zh)}</b> · ${esc(a.reason || "")}
        ${a.loss && isOwner() ? " · 损失 " + money(a.loss) : ""} · <span class="pill ${a.done ? "ok-pill" : a.overdue ? "bad-pill" : "warn-pill"}">${esc(a.stage_zh)}</span>
        <span data-notr>${esc(a.note || "")}</span> <a class="link" data-asopen="${a.id}">查看 / 处理</a></div>`).join("")}` : ""}
      <details class="log-box"><summary><b>操作记录</b> <span class="muted small">${(o.log || []).length} 条</span></summary>
      <table class="grid small"><tbody>${(o.log || []).map((l) => `<tr><td class="nowrap">${fmtTime(l.ts)}</td><td data-notr>${esc(l.username || "")}</td>
        <td>${esc(l.action)}</td><td class="small" data-notr>${esc(l.detail || "")}</td></tr>`).join("") || '<tr><td class="muted">没有记录</td></tr>'}</tbody></table></details>
    </div>`;
    d.classList.remove("hidden");
    d.querySelector("[data-x]").onclick = () => d.classList.add("hidden");
    if (canEdit) lockBox(d.querySelector(".drawer-in"), { id: "order-detail", bar: d.querySelector("#od-lockbar"), label: "✏ 修改",
      keep: "[data-x], #od-as, #od-edit, #od-del, .log-box, details > summary, #od-approve, #od-hold, .buyer-box, [data-asopen], .pb-wrap, .pb-sel, [data-invdoc]",
      onCancel: () => openOrder(oid),
      onSave: async () => {
        const nst = $("#od-status").value;
        if (nst !== o.status && ["cancelled", "delivery_failed"].includes(nst) && !confirm(`把订单状态改成「${ORD_STATUS[nst]}」？${nst === "cancelled" ? "还没开始打印的任务会删除。" : "会自动登记售后。"}`)) throw new Error("已取消保存");
        await api(`/api/orders/${oid}`, { json: { custom_note: $("#od-note").value, priority: $("#od-priority").checked ? 1 : 0,
          status: $("#od-status").value, tracking_no: $("#od-track").value.trim(), tags: $("#od-tags").value,
          receiver: $("#od-receiver").value.trim(), phone: $("#od-phone").value.trim(), postcode: $("#od-postcode").value.trim(),
          address: $("#od-address").value.trim(), carrier: $("#od-carrier").value.trim(), cod: $("#od-cod").value, ship_method: $("#od-shipm").value,
          ship_by: $("#od-shipby").value ? $("#od-shipby").value.replace("T", " ") : "" } });
        toast("已保存");
        loadOrders();
        openOrder(oid);
      } });
    const asb = d.querySelector("#od-as");
    if (asb) asb.onclick = () => window.AS && AS.dialog(o);
    d.querySelectorAll("[data-asopen]").forEach((a) => (a.onclick = () => window.AS && AS.open(+a.dataset.asopen)));
    const rv = async (action, reason = "") => {
      try { await api(`/api/orders/${oid}/review`, { json: { action, reason } }); toast(action === "approve" ? "已审核通过，开始排产" : "已挂起"); loadOrders(); openOrder(oid); }
      catch (err) { toast(err.message, true); }
    };
    const ap = d.querySelector("#od-approve");
    if (ap) ap.onclick = () => rv("approve");
    const hd = d.querySelector("#od-hold");
    if (hd) hd.onclick = () => { const r = prompt("挂起原因", "等买家确认"); if (r !== null) rv("hold", r); };
    const bx = d.querySelector(".buyer-box");
    if (bx) bx.addEventListener("click", async (e) => {
      if (e.target.id === "od-buyer-orders") { d.classList.add("hidden"); OF.buyer_key = o.buyer_key; OF.tab = "all"; showTab("orders"); reload1(); return; }
      if (e.target.id !== "od-buyer-save") return;
      try {
        await api("/api/buyers", { json: { key: o.buyer_key, level: $("#od-blevel").value, note: $("#od-bnote").value } });
        toast("买家档案已保存"); loadOrders();
      } catch (err) { toast(err.message, true); }
    });
    const ed = d.querySelector("#od-edit");
    if (ed) ed.onclick = () => { d.classList.add("hidden"); editOrder(o.id); };
    const del = d.querySelector("#od-del");
    if (del) del.onclick = async () => {
      if (!confirmDelete("这个订单（它的生产任务也会一起删除）")) return;
      try { await api(`/api/orders/${oid}`, { method: "DELETE" }); d.classList.add("hidden"); toast("已删除"); loadOrders(); }
      catch (err) { toast(err.message, true); }
    };
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#ord-detail").classList.add("hidden"); });
  $("#ord-detail").addEventListener("click", (e) => { if (e.target.id === "ord-detail") e.target.classList.add("hidden"); });

  // ================= 利润 =================
  async function loadProfit() {
    const r = await api(`/api/profit?days=${$("#pf-days").value}`);
    const t = r.total;
    $("#pf-summary").innerHTML = `<div>订单<b>${t.orders}</b></div><div>收入<b>${money(t.revenue)}</b></div>
      <div>平台费<b>${money(t.fee)}</b></div><div>生产成本<b>${money(t.cost)}</b></div><div>其他支出<b>${money(t.expenses)}</b></div>
      <div>售后损失<b class="${t.aftersales ? "bad" : ""}">${money(t.aftersales || 0)}</b></div>
      <div>利润<b class="${t.profit < 0 ? "bad" : "ok"}">${money(t.profit)}</b></div><div>利润率<b>${r.margin === null ? "-" : r.margin + "%"}</b></div>`;
    $("#pf-warn").innerHTML = r.missing_data_orders ? `<p class="card warn small">${r.missing_data_orders} 个订单有商品没对上产品或缺少克数，这些订单的成本偏低、利润偏高。到订单页点「重新匹配 SKU」或给产品切片。</p>` : "";
    $("#pf-days-t tbody").innerHTML = r.days.map((d) => `<tr><td class="nowrap">${d.day}</td><td>${d.orders}</td><td>${money(d.revenue)}</td>
      <td>${money(d.fee)}</td><td>${money(d.material)}</td><td>${money(d.machine)}</td><td>${money(d.packaging)}</td><td>${money(d.failure)}</td>
      <td>${d.expenses ? money(d.expenses) : ""}</td><td>${d.aftersales ? money(d.aftersales) : ""}</td><td><b class="${d.profit < 0 ? "bad" : "ok"}">${money(d.profit)}</b></td></tr>`).join("")
      || '<tr><td colspan="11" class="muted">这段时间没有订单</td></tr>';
    const rate = (p, rv) => (rv ? (p / rv * 100).toFixed(1) + "%" : "-");
    $("#pf-plat tbody").innerHTML = r.platforms.map((p) => `<tr><td>${esc(PLAT[p.platform] || p.platform)}</td><td>${p.orders}</td>
      <td>${money(p.revenue)}</td><td>${money(p.profit)}</td><td>${rate(p.profit, p.revenue)}</td></tr>`).join("");
    $("#pf-sku tbody").innerHTML = r.skus.map((s) => `<tr><td class="mono" data-notr>${esc(s.sku)}</td><td data-notr>${esc(s.name)}</td>
      <td>${s.qty}</td><td>${money(s.revenue)}</td><td class="${s.profit < 0 ? "bad" : ""}">${money(s.profit)}</td><td>${rate(s.profit, s.revenue)}</td></tr>`).join("");
    if (!window.MODKIT || MODKIT.enabled("fin")) loadExpenses().catch(() => {});   // v2.30：其他支出属于财务模块
  }
  function renderExpenses(items) {
    $("#ex-table tbody").innerHTML = items.map((x) => `<tr><td>${esc(x.day)}</td><td>${esc(x.kind)}</td><td>${money(x.amount)}</td>
      <td data-notr>${esc(x.note || "")}</td><td><button class="danger mini-x" data-exdel="${x.id}">✕</button></td></tr>`).join("")
      || '<tr><td colspan="5" class="muted">没有记录</td></tr>';
  }
  async function loadExpenses() { renderExpenses((await api("/api/expenses")).items); }
  $("#pf-days").addEventListener("change", loadProfit);
  $("#btn-ex-add").addEventListener("click", (e) => busy(e.target, async () => {
    const amt = $("#ex-amount").value;
    if (!amt) throw new Error("请填写金额");
    await api("/api/expenses", { json: { day: $("#ex-day").value || today(), kind: $("#ex-kind").value, amount: amt, note: $("#ex-note").value } });
    $("#ex-amount").value = ""; $("#ex-note").value = "";
    toast("已记录");
    loadProfit();
  }));
  $("#ex-table").addEventListener("click", async (e) => {
    const id = e.target.dataset.exdel;
    if (!id || !confirm("删除这笔支出？")) return;
    try { await api(`/api/expenses/${id}`, { method: "DELETE" }); loadProfit(); } catch (err) { toast(err.message, true); }
  });
  $("#ex-day").value = today();


  const filterBuyer = (key) => { OF.buyer_key = key; OF.tab = "all"; OF.page = 1; showTab("orders"); };
  window.OPS = { show, loadOrders, loadMaterials: () => window.MATERIALS && MATERIALS.load(), loadProfit, openOrder, loadSkus, filterBuyer,
    loadIntegrations: () => window.INTG_UI && INTG_UI.load() };
})();
