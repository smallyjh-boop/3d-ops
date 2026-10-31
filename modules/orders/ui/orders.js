"use strict";
// 订单模块：订单列表（ERP 式）、修改订单、批量填运单号、导入、手工单、订单详情、每单利润。
// v2.34 从 static/ops.js 搬进模块；公用的小工具（PLAT、money、colorTxt、打印机名……）在内核 app.js 的 window.OPSH，
// API 密钥在内核（window.INTG_UI），「打开了哪个页面」由内核 showTab 通知各页面脚本。
(function () {
  const { PLAT, KIND_ZH, JOB_ZH, role, isOwner, money, num, day, short, colorTxt, today, printerName } = window.OPSH;
  let ORD_STATUS = {};
  let IMP = null;          // 当前导入预览

  function show(name) {
    if (name === "orders") { if (PRESETS === null) loadPresets(); loadOrders(); }
    if (name === "profit") loadProfit();
  }

  // ================= 订单列表（v2.50：BigSeller 式）=================
  // 左边工作流队列（带数字，一条聚合 SQL）· 常用筛选 + 「更多筛选」· 保存筛选 · 批量搜索 · 勾选后浮出的批量操作条
  const Z = (zh, th) => (window.I18N && I18N.lang === "th" ? th : zh);
  const ls = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { return null; } return v; };
  const OF = { tab: ls("ord_queue") || "to_produce", page: 1, nos: "", match: "exact" };
  let ORD_PAGE = null;
  const SEL = new Set();
  const STAGE_ZH = { none: "", waiting: "待生产", producing: "生产中", ready: "已打包待发", out: "已出库" };
  const Q_TXT = {
    all: ["全部", "ทั้งหมด"], review: ["待审核", "รอตรวจ"], to_produce: ["待生产", "รอผลิต"], producing: ["生产中", "กำลังผลิต"],
    to_pack: ["待打包", "รอแพ็ก"], to_label: ["待打单", "รอพิมพ์ใบปะหน้า"], to_pickup: ["待揽收", "รอขนส่งรับ"], shipped: ["已交运", "ส่งแล้ว"],
    completed: ["已完成", "สำเร็จ"], exception: ["异常", "ผิดปกติ"], urgent: ["即将超时", "ใกล้หมดเวลาส่ง"], shelf: ["搁置", "พักไว้"],
    cancelled: ["取消", "ยกเลิก"], unpaid: ["未付款", "ยังไม่ชำระ"], aftersale: ["售后", "หลังการขาย"], rts_failed: ["安排发货失败", "แจ้งส่ง Lazada ไม่สำเร็จ"],
    quote: ["报价", "ใบเสนอราคา"],
    // 旧页签名（旧链接）
    waiting: ["待生产", "รอผลิต"], ready: ["待发货", "รอส่ง"], returned: ["退货退款", "คืนสินค้า/คืนเงิน"], delivery_failed: ["拒收/派送失败", "ปฏิเสธรับ/ส่งไม่สำเร็จ"],
  };
  const Q_HELP = {
    review: ["新订单命中审单规则（定制留言、风险买家货到付款、可能重复下单……），挂起等人工审核，不排产", "ออเดอร์ใหม่ที่ตรงกฎตรวจ (ข้อความสั่งทำ ลูกค้าเสี่ยง COD อาจสั่งซ้ำ) พักไว้รอคนตรวจ ยังไม่ผลิต"],
    to_produce: ["审核通过，生产任务还没开始（或者 SKU 没对上产品，排不了产）", "ตรวจผ่านแล้ว งานผลิตยังไม่เริ่ม (หรือ SKU ไม่ตรงสินค้า)"],
    producing: ["有生产任务在打印 / 后处理", "มีงานกำลังพิมพ์ / เก็บงาน"], to_pack: ["全部打印好了，等打包", "พิมพ์ครบแล้ว รอแพ็ก"],
    to_label: ["打包好了（或者不用生产），还没打面单", "แพ็กแล้ว (หรือไม่ต้องผลิต) ยังไม่พิมพ์ใบปะหน้า"],
    to_pickup: ["面单打好了，等快递揽收 / 交接", "พิมพ์ใบปะหน้าแล้ว รอขนส่งมารับ / ส่งมอบ"], shipped: ["已经交给快递", "ส่งให้ขนส่งแล้ว"],
    completed: ["买家已签收", "ลูกค้าได้รับแล้ว"], exception: ["SKU 没对上、缺克数、快超时、排产来不及、打印失败……", "SKU ไม่ตรง ขาดน้ำหนัก ใกล้หมดเวลา ผลิตไม่ทัน พิมพ์ล้มเหลว"],
    urgent: ["24 小时内要发货还没打包好（含已超时）", "ต้องส่งภายใน 24 ชม. แต่ยังแพ็กไม่เสร็จ (รวมเกินเวลา)"], shelf: ["人工搁置（暂时不处理，不排产）", "พักไว้ (ยังไม่ทำ ไม่ผลิต)"],
    aftersale: ["退货退款、拒收 / 派送失败，或者有没处理完的售后", "คืนสินค้า/คืนเงิน ปฏิเสธรับ หรือมีงานหลังการขายค้าง"],
    rts_failed: ["在 ERP 里发货了，Lazada 上「安排发货」没成功（原因在订单的操作记录里）。勾选后「发货 ▾ → 安排发货」重试", "ส่งใน ERP แล้ว แต่แจ้งพร้อมส่งใน Lazada ไม่สำเร็จ เลือกแล้วกด「จัดส่ง ▾ → แจ้งพร้อมส่ง」เพื่อลองใหม่"],
  };
  const QMAIN = ["review", "to_produce", "producing", "to_pack", "to_label", "to_pickup", "shipped", "completed"];
  const QMORE = ["exception", "urgent", "shelf", "cancelled", "unpaid", "aftersale", "rts_failed", "quote"];
  const QHOT = new Set(["review", "exception", "urgent", "rts_failed"]);
  const PKG_TXT = { single: ["单品单件", "ชิ้นเดียว"], multi: ["单品多件", "สินค้าเดียวหลายชิ้น"], mixed: ["多品混装", "หลายสินค้า"] };
  const FLAG_C = { red: "#ef4444", orange: "#f97316", yellow: "#eab308", green: "#22c55e", blue: "#3b82f6", purple: "#a855f7" };
  const FLAG_TXT = { red: ["红", "แดง"], orange: ["橙", "ส้ม"], yellow: ["黄", "เหลือง"], green: ["绿", "เขียว"], blue: ["蓝", "น้ำเงิน"], purple: ["紫", "ม่วง"] };
  const DOC_TXT = { label: ["面单", "ใบปะหน้า", "面", "ปะ"], pick: ["拣货单", "ใบหยิบสินค้า", "拣", "หยิบ"], pack: ["装箱单", "ใบแพ็กสินค้า", "装", "แพ็ก"],
    invoice: ["发票", "ใบเสร็จ", "票", "ใบเสร็จ"] };
  const qt = (k) => Z(...(Q_TXT[k] || [k, k]));
  const MORE_IDS = ["#ord-kind", "#ord-printed", "#ord-pkg", "#ord-pay", "#ord-carrier", "#ord-tag", "#ord-flag"];
  function ordFilters() {
    return { tab: OF.tab, page: OF.page, q: $("#ord-q").value.trim(), platform: $("#ord-platform").value, shop: $("#ord-shop").value,
      kind: $("#ord-kind").value, tag: $("#ord-tag").value, printed: $("#ord-printed").value, pkg: $("#ord-pkg").value, flag: $("#ord-flag").value,
      date_from: $("#ord-from").value, date_to: $("#ord-to").value, pay: $("#ord-pay").value, carrier: $("#ord-carrier").value,
      risk: $("#ord-risk").checked ? 1 : "", loss: isOwner() && $("#ord-loss").checked ? 1 : "",
      nos: OF.nos, match: OF.nos ? OF.match : "", buyer_key: OF.buyer_key || "", sort: $("#ord-sort").value, page_size: 50 };
  }
  const qs = (o) => Object.entries(o).filter(([, v]) => v !== "" && v != null).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");

  function queuesHtml(r) {
    const c = r.counts || {};
    const item = (k, i) => {
      const n = c[k] || 0, h = Q_HELP[k];
      return `<button class="oq ${k === OF.tab ? "on" : ""} ${QHOT.has(k) && n ? "hot" : ""} ${!n ? "zero" : ""}" data-otab="${k}" ${h ? `title="${esc(Z(...h))}"` : ""}>
        ${i != null ? `<i class="oq-step">${i + 1}</i>` : ""}<span>${esc(qt(k))}</span><b>${n}</b></button>`;
    };
    return `<div class="oq-h"><span>${Z("订单队列", "คิวออเดอร์")}</span><button class="oq-fold" data-oqfold title="${Z("收起 / 展开", "ย่อ / ขยาย")}">«</button></div>
      <button class="oq oq-all ${OF.tab === "all" ? "on" : ""}" data-otab="all"><span>${qt("all")}</span><b>${c.all || 0}</b></button>
      <div class="oq-g">${QMAIN.map((k, i) => item(k, i)).join("")}</div>
      <div class="oq-sep"></div><div class="oq-g oq-g2">${QMORE.map((k) => item(k)).join("")}</div>`;
  }

  function moreCount() {
    return MORE_IDS.filter((k) => $(k).value).length + ($("#ord-risk").checked ? 1 : 0) + (isOwner() && $("#ord-loss").checked ? 1 : 0)
      + ($("#ord-sort").value !== "auto" ? 1 : 0);
  }

  async function loadOrders() {
    const f = ordFilters();
    const r = await api("/api/orders?" + qs(f));
    ORD_PAGE = r;
    ORD_STATUS = r.status_zh || {};
    if (!Q_TXT[OF.tab] && OF.tab !== "all") OF.tab = "all";
    $("#ord-queues").innerHTML = queuesHtml(r);
    const chips = [];
    if (OF.buyer_key) chips.push(`<span class="pill tag-pill">${Z("只看这个买家的订单", "เฉพาะออเดอร์ของลูกค้านี้")} <a class="link" id="ord-buyer-x">✕</a></span>`);
    if (OF.nos) chips.push(`<span class="pill tag-pill">${Z("批量搜索", "ค้นหาหลายเลข")} ${OF.nos.split(/[\s,，;；、]+/).filter(Boolean).length} · ${OF.match === "fuzzy" ? Z("模糊", "ใกล้เคียง") : Z("精确", "ตรงทุกตัว")} <a class="link" id="ord-nos-x">✕</a></span>`);
    if (!["all"].includes(OF.tab) && Q_TXT[OF.tab]) chips.unshift(`<b class="ord-qname">${esc(qt(OF.tab))}</b>${Q_HELP[OF.tab] ? UX.help(Z(...Q_HELP[OF.tab])) : ""}`);
    $("#ord-tabs").innerHTML = chips.join(" ");
    $("#ord-nos-miss").innerHTML = (r.nos_missing || []).length ? `<span class="bad">${Z(`${r.nos_missing.length} 个没找到：`, `ไม่พบ ${r.nos_missing.length} รายการ: `)}<span class="mono" data-notr>${r.nos_missing.slice(0, 30).map(esc).join(", ")}</span></span>` : "";
    const fill = (sel, list, first) => { const cur = $(sel).value; $(sel).innerHTML = `<option value="">${first}</option>` +
      list.map((x) => `<option ${x === cur ? "selected" : ""} data-notr>${esc(x)}</option>`).join(""); };
    fill("#ord-shop", r.shops, "全部店铺");
    fill("#ord-tag", r.tags, "全部标签");
    fill("#ord-carrier", r.carriers || [], "全部物流");
    const mc = moreCount();
    $("#ord-more-n").textContent = mc ? mc : "";
    $("#ord-table tbody").innerHTML = r.orders.map(rowHtml).join("") ||
      `<tr class="ord-empty"><td colspan="7">${UX.empty(Z("没有符合条件的订单", "ไม่มีออเดอร์ตามเงื่อนไข"))}</td></tr>`;
    const pages = Math.max(1, Math.ceil(r.total / r.page_size));
    $("#ord-pager").innerHTML = `<span class="small muted">共 ${r.total} 个订单</span>` + (pages > 1 ?
      `<button class="mini" data-pg="${r.page - 1}" ${r.page <= 1 ? "disabled" : ""}>上一页</button><span class="small">${r.page} / ${pages}</span>
       <button class="mini" data-pg="${r.page + 1}" ${r.page >= pages ? "disabled" : ""}>下一页</button>` : "") +
      (r.total > r.orders.length ? ` <button class="mini" id="ord-selall-filter">勾选全部 ${r.total} 个</button>` : "");
    $("#ord-all").checked = r.orders.length && r.orders.every((o) => SEL.has(o.id));
    updSel();
  }

  function itemsHtml(o) {
    const its = o.items || [];
    const show = its.slice(0, 3);
    const one = (i) => `<div class="oi ${i.product_id ? "" : "bad"}">${i.img ? `<img class="oi-img" src="${esc(i.img)}" alt="" loading="lazy"${i.product_id ? ` data-p360="${esc(i.sku)}"` : ""}>` : `<span class="oi-img oi-noimg"></span>`}
      <div class="oi-t"><span class="mono" data-notr${i.product_id ? ` data-p360="${esc(i.sku)}"` : ""}>${esc(i.sku || "?")}</span> <b class="oi-q ${(i.qty || 1) > 1 ? "multi" : ""}">×${i.qty || 1}</b>
        <div class="small muted oi-n" data-notr>${esc((i.name || "").slice(0, 40))}${i.variation ? ` · ${esc(i.variation)}` : ""}</div></div></div>`;
    const pk = PKG_TXT[o.pkg];
    return show.map(one).join("") + (its.length > 3 ? `<div class="small muted">${Z(`还有 ${its.length - 3} 种商品…`, `อีก ${its.length - 3} รายการ…`)}</div>` : "") +
      (pk ? `<span class="pkg pkg-${o.pkg}">${esc(Z(pk[0], pk[1]))}</span>` : "") +
      (o.custom_note ? `<div class="note-flag" data-notr>✎ ${esc(o.custom_note)}</div>` : "") +
      (o.buyer_note ? `<div class="small muted" data-notr>💬 ${esc(o.buyer_note)}</div>` : "");
  }

  function printsHtml(o) {
    const p = o.prints || {};
    return `<div class="pbs">${["label", "pick", "pack", "invoice"].map((k) => {
      const t = DOC_TXT[k], n = p[k] || 0;
      return `<span class="pb ${n ? "on" : ""}" title="${esc(Z(t[0], t[1]))}${n ? ` ×${n}` : ` · ${Z("未打印", "ยังไม่พิมพ์")}`}">${esc(Z(t[2], t[3]))}${n > 1 ? `<sup>${n}</sup>` : ""}</span>`;
    }).join("")}</div>`;
  }

  function rowHtml(o) {
    const tags = (o.tags || "").split(",").filter(Boolean).map((t) => `<span class="pill ${t.startsWith("⚠") ? "bad-pill" : "tag-pill"}" data-notr>${esc(t)}</span>`).join(" ");
    const exc = (o.exceptions || []).map((x) => `<div class="bad small">⚠ ${esc(x)}</div>`).join("");
    const active = o.status === "to_ship";
    const late = o.ship_by && o.ship_by < Date.now() / 1000 && ["waiting", "producing", "none"].includes(o.stage) && active;
    const hold = o.hold && active ? `<div class="hold-flag small">${o.queue === "shelf" ? "⏸ " + Z("搁置", "พักไว้") : "⏸ " + Z("待审核", "รอตรวจ")}：<span>${esc(o.hold_reason || "")}</span></div>` : "";
    const fl = o.flag && FLAG_C[o.flag] ? `<i class="oflag" style="background:${FLAG_C[o.flag]}" title="${esc(Z(...FLAG_TXT[o.flag]))}${o.flag_note ? " · " + esc(o.flag_note) : ""}"></i>` : "";
    const pst = o.status_raw && o.status_raw !== "手工" && String(o.status_raw).toLowerCase() !== o.status ? `<div class="small muted ord-pst" title="${Z("平台上的状态", "สถานะบนแพลตฟอร์ม")}">${esc(PLAT[o.platform] || o.platform || "")}: <span data-notr>${esc(o.status_raw)}</span></div>` : "";
    const pr = o.est_profit;
    return `<tr class="clickable ${SEL.has(o.id) ? "sel" : ""} ${o.flag ? "flag-" + esc(o.flag) : ""}" data-oid="${o.id}">
      <td class="ck"><input type="checkbox" data-sel="${o.id}" ${SEL.has(o.id) ? "checked" : ""}></td>
      <td class="oc-no">${fl}<b class="mono" data-notr>${esc(o.order_no)}</b>${o.priority ? ` <span class="pill bad-pill">${Z("加急", "ด่วน")}</span>` : ""}
        <div class="small muted">${esc(PLAT[o.platform] || o.platform)} <span data-notr>${esc(o.shop || "")}</span>${KIND_ZH[o.kind] && o.kind !== "normal" ? " · " + KIND_ZH[o.kind] : ""}</div>
        <div class="small muted">${Z("下单", "สั่ง")} ${short(o.order_time)}</div>
        ${o.flag_note ? `<div class="small oflag-note" data-notr>${esc(o.flag_note)}</div>` : ""}
        ${role() !== "production" && CAN("orders.edit") ? `<button class="mini primary-lite oc-edit" data-oedit="${o.id}">修改</button>` : ""}</td>
      <td class="oc-items">${itemsHtml(o)}</td>
      <td class="oc-buyer"><span data-notr>${esc(o.receiver || o.buyer || "")}</span>${buyerPills(o)}
        ${o.tracking_no ? `<div class="small mono muted" data-notr>${esc(o.tracking_no)}</div>` : ""}${o.carrier ? `<div class="small muted" data-notr>${esc(o.carrier)}</div>` : ""}</td>
      <td class="oc-time nowrap small">${active && !["ready", "out"].includes(o.stage) ? countdown(o.ship_by) : ""}
        ${o.ship_by ? `<div class="${late ? "bad" : "muted"}">${Z("最晚", "ส่งภายใน")} ${short(o.ship_by)}</div>` : ""}
        ${o.planned_done && active ? `<div class="muted">${Z("预计做完", "คาดว่าเสร็จ")} ${short(o.planned_done)}</div>` : ""}</td>
      <td class="c-cost oc-money nowrap">${money(o.order_total)}${pr ? `<div class="small ${pr.profit < 0 ? "bad" : "ok"}" title="${Z("估算利润 = 收入 − 平台费 − 材料机时包材", "กำไรประมาณ")}">${Z("利润", "กำไร")} ${money(pr.profit)}${pr.est ? "*" : ""}</div>` : ""}</td>
      <td class="oc-st"><span class="ost ost-${esc(o.status)}">${esc(o.status_zh)}</span>${active && Q_TXT[o.queue] ? ` <span class="oqs oqs-${esc(o.queue)}">${esc(qt(o.queue))}</span>` : ""}
        ${pst}<div class="small">${progress(o.job_counts)}</div>${printsHtml(o)}${hold}${exc}${tags}</td></tr>`;
  }

  // v2.43：订单详情里的生产任务按钮（和生产看板一样的操作）
  let OD_CUR = null;
  function jobActs(j) {
    const prs = (CFG && CFG.printers) || [];
    const mv = j.status === "todo" && !j.run_id && prs.length > 1 ? `<select class="mini" data-jmv="${j.id}"><option value="">换打印机…</option>${prs.map((p, i) => i === j.printer || p.enabled === false ? "" :
      `<option value="${i}" data-notr>${esc((p.code ? p.code + " · " : "") + p.name)}</option>`).join("")}</select>` : "";
    return ({
      todo: j.run_id ? "" : (j.stock_free > 0 && j.remaining > 0 ? `<button class="mini" data-juse="${j.id}" data-n="${Math.min(j.stock_free, j.remaining)}" title="先占住，发货出库时才扣库存">📦 用库存（可用 ${j.stock_free}）</button>` : "") +
        `<button class="mini" data-js="post" data-jid="${j.id}" title="不用在系统里点开始打印，已经打好了：扣耗材，进入待打包">✔ 已打好</button>${mv}`,
      post: `<button class="mini primary-lite" data-js="packed" data-jid="${j.id}">📦 已打包</button><button class="mini" data-js="todo" data-jid="${j.id}">退回重打</button>`,
      packed: `<button class="mini" data-js="post" data-jid="${j.id}">退回待打包</button>`,
    })[j.status] || "";
  }
  document.addEventListener("click", async (e) => {
    const t = e.target.closest(".od-jobs button"); if (!t) return;
    const oid = OD_CUR;
    try {
      if (t.dataset.juse) {
        const n = prompt("用成品库存出几个？", t.dataset.n); if (!n) return;
        await api(`/api/jobs/${t.dataset.juse}/use-stock`, { json: { n: +n } }); toast("已用库存（先占住，发货出库时扣库存）");
      } else if (t.dataset.js) {
        if (t.dataset.js === "post" && !confirm("这个任务已经打好了？（会按打印方案扣耗材）")) return;
        if (t.dataset.js === "todo" && !confirm("退回重打？已打好的件作废，重新排单。")) return;
        await busy(t, () => api(`/api/jobs/${t.dataset.jid}`, { json: { status: t.dataset.js } }));
      } else return;
      if (oid) openOrder(oid); loadOrders();
    } catch (err) { toast(err.message, true); }
  });
  document.addEventListener("change", async (e) => {
    const s = e.target.closest(".od-jobs select[data-jmv]"); if (!s || s.value === "") return;
    try { await api(`/api/jobs/${s.dataset.jmv}`, { json: { printer: s.value } }); toast("已换打印机"); if (OD_CUR) openOrder(OD_CUR); }
    catch (err) { toast(err.message, true); }
  });
  async function printLabels(ids) {
    const r = await api("/api/labels/check", { json: { ids } });
    if ((r.blocked || []).length) alert(`这些订单已取消 / 退货，不打面单、不要发货：\n${r.blocked.map((b) => `${b.order_no}（${b.status_zh}）`).join("\n")}`);
    let lay = "";
    if ((r.overflow || []).length && confirm(`${r.overflow.length} 个订单商品太多，面单下面放不下商品清单（${r.overflow.slice(0, 5).map((x) => x.order_no).join("、")}${r.overflow.length > 5 ? "…" : ""}）。\n这次改成「面单 + 单独一张商品清单」打印吗？（只这一次，不改设置）`)) lay = "&layout=page";
    if (r.have.length) window.open(`/print/labels?type=platform&ids=${r.have.join(",")}${lay}`, "_blank");
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
    $("#ord-tools").open = false;
    const fd = new FormData();
    fd.append("file", f);
    try {
      const r = await api("/api/labels/import", { method: "POST", body: fd });
      toast(`面单 PDF 共 ${r.pages} 页，对应上 ${r.matched} 个订单` + (r.unmatched_pages.length ? `；第 ${r.unmatched_pages.slice(0, 20).join("、")} 页没找到订单。${r.hint}` : ""), !!r.unmatched_pages.length);
      loadOrders();
    } catch (err) { toast(err.message, true); }
  });

  // ---- 勾选后浮出的批量操作条（没勾选时不出现）----
  const dd = (label, items) => {
    const its = items.filter(Boolean);
    return its.length ? `<details class="odd odd-up"><summary>${label} ▾</summary><div class="odd-menu">${its.join("")}</div></details>` : "";
  };
  const bi = (act, zh, th, cls = "") => `<button data-bulk="${act}" class="${cls}">${Z(zh, th)}</button>`;
  function bulkHtml() {
    const prodOn = !window.MODKIT || MODKIT.enabled("prod");
    const linkOn = !window.MODKIT || MODKIT.enabled("link");
    const prodRole = role() === "production";
    return `<span class="fb-n">${Z("已选", "เลือก")} <b>${SEL.size}</b> ${Z("个订单", "ออเดอร์")}</span>
      <button class="mini" data-bulk="clear">✕ ${Z("清除", "ล้าง")}</button>
      ${prodRole ? "" : bi("approve", "✔ 审核通过", "✔ ตรวจผ่าน", "primary-lite btn-edit-only")}
      ${dd("🖨 " + Z("打印", "พิมพ์"), [bi("label", "面单", "ใบปะหน้า"), bi("pick", "拣货单", "ใบหยิบสินค้า"), bi("pack", "装箱单", "ใบแพ็กสินค้า"),
        prodRole ? "" : bi("invoice", "发票 / 收据", "ใบเสร็จ / ใบแจ้งหนี้"), bi("itemlabels", "内部商品标签", "ป้ายสินค้าภายใน")])}
      ${prodOn ? dd("🏭 " + Z("生产", "ผลิต"), [bi("jobs:use_stock", "用库存发", "ใช้สต็อก"), bi("jobs:printed", "标记已打好", "พิมพ์เสร็จแล้ว"), bi("jobs:packed", "标记已打包", "แพ็กแล้ว")]) : ""}
      ${dd("🚚 " + Z("发货", "จัดส่ง"), [linkOn && !prodRole ? bi("rts", "安排发货（Lazada）", "แจ้งพร้อมส่ง (Lazada)") : "", bi("handover", "加入交接单", "เพิ่มในใบส่งมอบ"),
        prodRole ? "" : bi("status:shipped", "标记已发货", "ทำเครื่องหมายส่งแล้ว"), prodRole ? "" : bi("status:completed", "标记已完成", "ทำเครื่องหมายสำเร็จ"),
        prodRole ? "" : bi("ship_method:pickup", "上门揽收", "ขนส่งเข้ารับ"), prodRole ? "" : bi("ship_method:dropoff", "送到网点", "ส่งที่สาขา"),
        prodRole ? "" : bi("status:delivery_failed", "标记拒收 / 派送失败", "ปฏิเสธรับ / ส่งไม่สำเร็จ", "danger")])}
      ${prodRole ? "" : dd(Z("更多", "เพิ่มเติม"), [bi("flag", "🎨 颜色标记", "🎨 ทำสี"), bi("tag_add", "加标签", "เพิ่มแท็ก"), bi("tag_remove", "去标签", "ลบแท็ก"),
        bi("priority:1", "加急", "ด่วน"), bi("priority:0", "取消加急", "ยกเลิกด่วน"), bi("shelve", "⏸ 搁置", "⏸ พักไว้"), bi("hold", "挂起到待审核", "พักรอตรวจ"),
        bi("export", "导出 Excel", "ส่งออก Excel"), bi("status:cancelled", "取消订单", "ยกเลิกออเดอร์", "danger"),
        CAN("orders.delete") ? bi("delete", "删除", "ลบ", "danger") : ""])}`;
  }
  function updSel() {
    const bar = $("#ord-bulk");
    bar.classList.toggle("hidden", SEL.size === 0);
    if (SEL.size) bar.innerHTML = bulkHtml();
    $("#tab-orders").classList.toggle("has-sel", SEL.size > 0);
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
    if (o.risk_reason && !(o.buyer_tags || []).includes("blacklist")) out.push(`<span class="pill bad-pill" title="${esc(o.risk_reason)}">⚠ ${Z("风险买家", "ลูกค้าความเสี่ยงสูง")}</span>`);
    (o.buyer_tags || []).forEach((t) => {
      const [k, n] = t.split(":");
      if (k === "refused") out.push(`<span class="pill bad-pill">拒收过 ${n} 次</span>`);
      else if (k === "returned") out.push(`<span class="pill warn-pill">${Z(`退货 ${n} 次`, `คืนสินค้า ${n} ครั้ง`)}</span>`);
      else if (k === "repeat") out.push(`<span class="pill">回头客 ${n} 单</span>`);
      else if (k === "blacklist") out.push(`<span class="pill bad-pill" title="${esc(o.risk_reason || "")}">${BT[k][0]}</span>`);
      else if (BT[k] && k !== "new") out.push(`<span class="pill ${BT[k][1]}">${BT[k][0]}</span>`);
      else if (k === "new" && o.is_cod) out.push('<span class="pill warn-pill">新客</span>');
    });
    return out.length ? `<div class="bpills">${out.join(" ")}</div>` : "";
  }

  // ---- 筛选 ----
  let qTimer = null;
  const reload1 = () => { OF.page = 1; loadOrders(); };
  $("#ord-q").addEventListener("input", () => { clearTimeout(qTimer); qTimer = setTimeout(reload1, 300); });
  ["#ord-platform", "#ord-shop", "#ord-from", "#ord-to", "#ord-sort", "#ord-risk", "#ord-loss", ...MORE_IDS].forEach((k) => $(k).addEventListener("change", reload1));
  $("#ord-more-btn").addEventListener("click", () => { const m = $("#ord-more"); m.classList.toggle("hidden"); ls("ord_more", m.classList.contains("hidden") ? "0" : "1"); });
  if (ls("ord_more") === "1") $("#ord-more").classList.remove("hidden");
  $("#ord-nos-btn").addEventListener("click", () => { $("#ord-nos-box").classList.toggle("hidden"); if (!$("#ord-nos-box").classList.contains("hidden")) $("#ord-nos").focus(); });
  $("#ord-match").addEventListener("click", (e) => {
    const b = e.target.closest("[data-m]"); if (!b) return;
    $$("#ord-match button").forEach((x) => x.classList.toggle("on", x === b));
    OF.match = b.dataset.m; if (OF.nos) reload1();
  });
  $("#ord-nos-go").addEventListener("click", () => { OF.nos = $("#ord-nos").value.trim(); if (OF.nos) { OF.tab = "all"; SEL.clear(); } reload1(); });
  $("#ord-nos-clear").addEventListener("click", () => { $("#ord-nos").value = ""; OF.nos = ""; reload1(); });
  function resetFilters() {
    OF.buyer_key = ""; OF.nos = ""; $("#ord-nos").value = "";
    ["#ord-q", "#ord-platform", "#ord-shop", "#ord-from", "#ord-to", ...MORE_IDS].forEach((k) => ($(k).value = ""));
    $("#ord-risk").checked = false; $("#ord-loss").checked = false;
    $("#ord-sort").value = "auto";
  }
  $("#btn-ord-reset").addEventListener("click", () => { resetFilters(); reload1(); });
  $("#ord-tabs").addEventListener("click", (e) => {
    if (e.target.id === "ord-buyer-x") { OF.buyer_key = ""; reload1(); }
    if (e.target.id === "ord-nos-x") { OF.nos = ""; $("#ord-nos").value = ""; reload1(); }
  });
  $("#ord-queues").addEventListener("click", (e) => {
    if (e.target.closest("[data-oqfold]")) { const w = $("#ord-wrap"); w.classList.toggle("oq-folded"); ls("ord_fold", w.classList.contains("oq-folded") ? "1" : "0"); return; }
    const b = e.target.closest("[data-otab]");
    if (!b) return;
    OF.tab = b.dataset.otab; OF.page = 1; SEL.clear(); ls("ord_queue", OF.tab);
    if ($("#ord-wrap").classList.contains("oq-folded") && window.innerWidth > 1200) $("#ord-wrap").classList.remove("oq-folded");
    loadOrders();
  });
  if (ls("ord_fold") === "1") $("#ord-wrap").classList.add("oq-folded");
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
    if (e.target.closest("td.ck")) return;
    if (e.target.closest("[data-p360]")) return;          // 点 SKU / 图片 = 产品 360（p360.js 处理）
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
  // 下拉菜单（<details>）：开一个关掉别的，点外面关
  document.addEventListener("click", (e) => {
    const d = e.target.closest && e.target.closest("details.odd");
    $$("details.odd[open]").forEach((x) => { if (x !== d) x.open = false; });
    if (d && e.target.closest(".odd-menu button, .odd-menu label")) setTimeout(() => { if (!e.target.closest("label.filebtn")) d.open = false; }, 0);
  });
  $("#ord-tools").addEventListener("click", (e) => {
    if (e.target.closest('[data-tool="export"]')) location.href = "/api/orders/export?" + qs({ ...ordFilters(), page: "" });
  });

  // ---- 保存筛选（每个账号自己的，存在服务器上）----
  let PRESETS = null;
  const PRESET_EL = { q: "#ord-q", platform: "#ord-platform", shop: "#ord-shop", date_from: "#ord-from", date_to: "#ord-to", kind: "#ord-kind",
    printed: "#ord-printed", pkg: "#ord-pkg", pay: "#ord-pay", carrier: "#ord-carrier", tag: "#ord-tag", flag: "#ord-flag", sort: "#ord-sort" };
  function renderPresets() {
    $("#ord-presets").innerHTML = `<span class="small muted">${Z("我的筛选", "ตัวกรองของฉัน")}</span>` +
      PRESETS.map((p) => `<span class="ochip"><button class="ochip-b" data-preset="${p.id}" data-notr>${esc(p.name)}</button><button class="ochip-x" data-pdel="${p.id}" title="${Z("删除", "ลบ")}">✕</button></span>`).join("") +
      `<button class="mini" id="ord-psave">＋ ${Z("保存筛选", "บันทึกตัวกรอง")}</button>`;
  }
  async function loadPresets() { PRESETS = []; try { PRESETS = (await api("/api/orders/presets")).items || []; } catch { PRESETS = []; } renderPresets(); }
  $("#ord-presets").addEventListener("click", async (e) => {
    try {
      if (e.target.id === "ord-psave") {
        const name = prompt(Z("给这个筛选起个名字（例如：Lazada 待打单 单品单件）", "ตั้งชื่อตัวกรองนี้"));
        if (!name) return;
        const f = ordFilters(); delete f.page; delete f.page_size; delete f.buyer_key;
        PRESETS = (await api("/api/orders/presets", { json: { name, filters: f } })).items; renderPresets(); toast(Z("已保存筛选", "บันทึกตัวกรองแล้ว"));
      } else if (e.target.dataset.pdel) {
        if (!confirm(Z("删除这个筛选？", "ลบตัวกรองนี้?"))) return;
        PRESETS = (await api(`/api/orders/presets/${e.target.dataset.pdel}/delete`, { json: {} })).items; renderPresets();
      } else if (e.target.dataset.preset) {
        const p = PRESETS.find((x) => x.id === +e.target.dataset.preset); if (!p) return;
        const f = p.filters || {};
        resetFilters();
        Object.entries(PRESET_EL).forEach(([k, sel]) => { if (f[k] != null) { const el = $(sel); if (el.tagName === "SELECT" && ![...el.options].some((o) => o.value === String(f[k]))) el.insertAdjacentHTML("beforeend", `<option data-notr>${esc(f[k])}</option>`); el.value = f[k]; } });
        if (!$("#ord-sort").value) $("#ord-sort").value = "auto";
        $("#ord-risk").checked = !!f.risk; $("#ord-loss").checked = !!f.loss;
        OF.nos = f.nos || ""; $("#ord-nos").value = OF.nos; OF.match = f.match || "exact";
        $$("#ord-match button").forEach((x) => x.classList.toggle("on", x.dataset.m === OF.match));
        if (f.tab) { OF.tab = f.tab; ls("ord_queue", OF.tab); }
        if (MORE_IDS.some((k) => $(k).value) || f.risk || f.loss) $("#ord-more").classList.remove("hidden");
        SEL.clear(); reload1();
      }
    } catch (err) { toast(err.message, true); }
  });
  $("#ord-help").outerHTML = UX.help(Z("从 BigSeller / Lazada / Shopee / TikTok 后台导出订单表格直接导入，或者开了接口的店铺自动同步。左边是订单的工作流：待审核 → 待生产 → 生产中 → 待打包 → 待打单 → 待揽收 → 已交运 → 已完成；下面一组是要特别处理的。勾选订单后下面会浮出批量操作条。",
    "นำเข้าตารางออเดอร์จาก BigSeller / Lazada / Shopee / TikTok หรือซิงค์อัตโนมัติจากร้านที่เชื่อม API ด้านซ้ายคือขั้นตอนงาน: รอตรวจ → รอผลิต → กำลังผลิต → รอแพ็ก → รอพิมพ์ใบปะหน้า → รอขนส่งรับ → ส่งแล้ว → สำเร็จ เลือกออเดอร์แล้วจะมีแถบคำสั่งด้านล่าง"));

  const MONEY_ZH = { item_amount: "商品总额", buyer_shipping: "买家付的运费", platform_discount: "平台优惠", seller_discount: "卖家优惠",
    commission: "佣金", service_fee: "服务费", payment_fee: "支付手续费", settlement: "结算到账" };
  // ---- 修改订单（基本信息 + 商品明细） ----
  async function editOrder(oid) {
    let o;
    try { o = await api(`/api/orders/${oid}`); } catch (err) { toast(err.message, true); return; }
    let skus = [];
    try { const r = await api("/api/skus"); skus = Array.isArray(r) ? r : (r.skus || []); } catch { skus = []; }
    const locked = (o.jobs || []).some((j) => (j.kind || "order") === "order" && (j.run_id || (j.qty_done || 0) > (j.stock_n || 0) || !["todo", "post"].includes(j.status)));   // v2.40：只用库存发的不算开始；补发任务不算
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
    if (act === "clear") { SEL.clear(); loadOrders(); return; }
    if (act === "export") { location.href = "/api/orders/export?" + (ids.length ? "ids=" + ids.join(",") : qs({ ...ordFilters(), page: "" })); return; }
    if (!ids.length) { toast("请先勾选订单", true); return; }
    if (act === "pick" || act === "pack" || act === "invoice") { window.open(`/print/orders?type=${act}&ids=${ids.join(",")}`, "_blank"); setTimeout(loadOrders, 1500); return; }
    if (act === "itemlabels") { window.open(`/print/item-labels?ids=${ids.join(",")}`, "_blank"); return; }
    if (act === "label") { printLabels(ids); return; }
    if (act === "jobs") {             // v2.43：订单页直接处理生产任务
      const zh = { use_stock: "用成品库存发", printed: "标记已打好（扣耗材）", packed: "标记已打包" }[val];
      if (!confirm(`这 ${ids.length} 个订单的生产任务：${zh}？`)) return;
      await busy(b, async () => {
        const r = await api("/api/jobs/bulk", { json: { order_ids: ids, action: val } });
        toast(`${zh}：${r.done} 个任务` + (r.skipped.length ? `；${r.skipped.length} 个没做成：${r.skipped.slice(0, 3).join("；")}` : ""), !!r.skipped.length);
        await loadOrders();
      });
      return;
    }
    if (act === "rts") {              // v2.50：Lazada「安排发货」（失败的进「安排发货失败」队列）
      if (!confirm(Z(`在 Lazada 上给这 ${ids.length} 个订单「安排发货」？（只是通知平台可以来揽收，ERP 里的状态不变）`, `แจ้งพร้อมส่งใน Lazada สำหรับ ${ids.length} ออเดอร์?`))) return;
      await busy(b, async () => {
        const r = await api("/api/orders/rts", { json: { ids } });
        toast(Z(`安排发货成功 ${r.done} 个`, `แจ้งพร้อมส่งสำเร็จ ${r.done}`) + (r.errors.length ? `；${r.errors.length} ✗：${r.errors.slice(0, 3).join("；")}` : ""), !!r.errors.length);
        await loadOrders();
      });
      return;
    }
    if (act === "handover") {         // v2.50：放进交接单（按物流 + 发货方式）
      await busy(b, async () => {
        const r = await api("/api/orders/handover-add", { json: { ids } });
        toast(Z(`已放进交接单 ${r.added} 个`, `เพิ่มในใบส่งมอบ ${r.added}`) + (r.errors.length ? `；${r.errors.length} ✗：${r.errors.slice(0, 3).join("；")}` : ""), !!r.errors.length);
        if (r.added && confirm(Z("去「发货交接」页核对件数、交接完成？", "ไปหน้า「ส่งมอบพัสดุ」เลยไหม?"))) showTab("handover");
        else await loadOrders();
      });
      return;
    }
    if (act === "flag") {             // v2.50：颜色标记
      flagDialog(ids);
      return;
    }
    let value = val;
    if (act === "hold" || act === "shelve") {
      value = prompt(act === "shelve" ? Z("搁置原因（例如：等买家补款 / 缺货等料）", "เหตุผลที่พักไว้") : "挂起原因（例如：等买家确认颜色 / 疑似重复下单）",
        act === "shelve" ? Z("暂时不处理", "ยังไม่ทำ") : "等买家确认");
      if (value === null) return;
    }
    if (act === "status" && ["cancelled", "delivery_failed", "returned"].includes(val) && !CAN("orders.cancel")) { toast("你的账号没有「取消订单 / 标记退货、拒收」的权限，请老板在 系统 → 设置 → 账号与权限 里开通", true); return; }
    if (act === "status" && val === "delivery_failed" && !confirm(`把这 ${ids.length} 个订单标记为「拒收/派送失败」？会自动登记售后，等包裹退回验货。`)) return;
    if (act === "tag_add" || act === "tag_remove") {
      value = prompt(act === "tag_add" ? "要加的标签（例如：VIP、催单、待确认设计）" : "要去掉的标签");
      if (!value) return;
    }
    if (act === "status" && val === "cancelled" && !confirm(`确定取消这 ${ids.length} 个订单？还没开始打印的任务会删除。`)) return;
    if (act === "delete" && !confirmDelete(`这 ${ids.length} 个订单`)) return;
    await busy(b, async () => {
      const r = await api("/api/orders/batch", { json: { ids, action: act, value: act === "priority" ? +val : value } });
      toast(`已处理 ${r.done} 个订单` + ((r.errors || []).length ? `；${r.errors.length} 个没做成：${r.errors.slice(0, 3).join("；")}` : ""), !!(r.errors || []).length);
      if (act === "delete") SEL.clear();
      await loadOrders();
    });
  });
  function flagDialog(ids, cur = "", note = "") {
    const el = MODAL.open(`<div class="row between"><h3>${Z("颜色标记", "ทำสีออเดอร์")}</h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      <p class="small muted">${Z(`给 ${ids.length} 个订单做个颜色记号（自己约定颜色的意思，例如红 = 要先打、蓝 = 等买家回复），可以按颜色筛选。`, `ทำสีให้ ${ids.length} ออเดอร์ (ตกลงความหมายเอง) แล้วกรองตามสีได้`)}</p>
      <div class="row gap wrap ofl-pick">${Object.keys(FLAG_C).map((k) => `<button class="ofl ${k === cur ? "on" : ""}" data-fl="${k}"><i style="background:${FLAG_C[k]}"></i>${esc(Z(...FLAG_TXT[k]))}</button>`).join("")}
        <button class="ofl" data-fl="">✕ ${Z("去掉", "ลบสี")}</button></div>
      <label>${Z("备注（可空）", "หมายเหตุ (เว้นว่างได้)")}<input id="ofl-note" value="${esc(note)}" maxlength="200" data-notr></label>`);
    el.onclick = async (e) => {
      const b = e.target.closest("[data-fl]"); if (!b) return;
      try {
        await api("/api/orders/flag", { json: { ids, color: b.dataset.fl, note: $("#ofl-note", el).value } });
        MODAL.close(); toast(Z("已标记", "ทำสีแล้ว")); loadOrders(); if (OD_CUR && ids.length === 1 && ids[0] === OD_CUR && !$("#ord-detail").classList.contains("hidden")) openOrder(OD_CUR);
      } catch (err) { toast(err.message, true); }
    };
  }
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

  // v2.50：这单每种单据打了几次
  function docPrints(o) {
    const p = o.prints || {};
    if (o.label_printed_at && !p.label) p.label = { n: 1, last_at: o.label_printed_at };
    return `<div class="pbs od-pbs">${["label", "pick", "pack", "invoice"].map((k) => {
      const t = DOC_TXT[k], x = p[k];
      return `<span class="pb pb-wide ${x ? "on" : ""}">${esc(Z(t[0], t[1]))} ${x ? `×${x.n} <span class="muted">${short(x.last_at)}</span>` : `<span class="muted">${Z("未打", "ยังไม่พิมพ์")}</span>`}</span>`;
    }).join("")}</div>`;
  }

  // v2.50：客服聊天「从聊天建单」（modules/cs/ui/cs.js 调用）：买家 / 平台 / 店铺从会话带过来，商品从「买家提到的商品」预填
  async function orderFromChat(conv, sugg, submit) {
    let skus = [];
    try { const r = await api("/api/skus"); skus = Array.isArray(r) ? r : (r.skus || []); } catch { skus = []; }
    const pre = (sugg || []).map((p) => skus.find((s) => s.pid === p.id)).filter(Boolean);
    const row = (s) => `<tr><td><input data-k="sku" list="ofc-skus" value="${esc((s && s.sku) || "")}" data-notr style="width:150px"></td>
      <td class="small" data-nm data-notr>${s ? esc(`${s.name} ${s.color || ""}`) : ""}</td>
      <td><input data-k="qty" type="number" min="1" value="1" style="width:64px"></td>
      <td class="c-final"><input data-k="unit_price" type="number" min="0" step="0.01" value="${s && s.price != null ? s.price : ""}" style="width:90px"></td>
      <td><button class="mini danger" data-rm>✕</button></td></tr>`;
    const el = MODAL.open(`<div class="row between"><h3>🧾 ${Z("从聊天建单", "สร้างออเดอร์จากแชท")}</h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      <p class="small muted">${Z("买家、平台、店铺从这个会话带过来；商品按买家提到的产品预填，改一下数量和价格。建好后会话自动关联这个订单。", "ข้อมูลลูกค้า แพลตฟอร์ม ร้าน มาจากแชทนี้ สินค้าเติมจากที่ลูกค้าพูดถึง แก้จำนวนและราคาได้ สร้างแล้วจะผูกกับแชทอัตโนมัติ")}</p>
      <datalist id="ofc-skus">${skus.map((x) => `<option value="${esc(x.sku)}">${esc((x.name || "") + " " + (x.color || ""))}</option>`).join("")}</datalist>
      <div class="form3">
        <label>${Z("类型", "ประเภท")}<select id="ofc-kind"><option value="manual">${Z("私下成交（正式订单，马上排产）", "ขายตรง (ออเดอร์จริง เริ่มผลิตเลย)")}</option>
          <option value="custom">${Z("定制单", "งานสั่งทำ")}</option><option value="wholesale">${Z("批发/大单", "ขายส่ง/ล็อตใหญ่")}</option>
          <option value="quote">${Z("报价单（先不排产，不算收入）", "ใบเสนอราคา (ยังไม่ผลิต)")}</option></select></label>
        <label>${Z("买家", "ลูกค้า")}<input id="ofc-buyer" value="${esc(conv.buyer || "")}" data-notr></label>
        <label>${Z("平台 · 店铺", "แพลตฟอร์ม · ร้าน")}<input value="${esc((PLAT[conv.platform] || conv.platform || "") + (conv.shop ? " · " + conv.shop : ""))}" readonly data-notr></label>
        <label>${Z("收件人", "ผู้รับ")}<input id="ofc-receiver" data-notr></label>
        <label>${Z("电话", "โทร")}<input id="ofc-phone" data-notr></label>
        <label>${Z("邮编", "รหัสไปรษณีย์")}<input id="ofc-postcode" data-notr></label>
        <label class="span2">${Z("地址", "ที่อยู่")}<input id="ofc-address" data-notr></label>
      </div>
      <table class="grid small" id="ofc-items"><thead><tr><th>SKU</th><th>${Z("商品", "สินค้า")}</th><th>${Z("数量", "จำนวน")}</th><th class="c-final">${Z("单价 ฿", "ราคา ฿")}</th><th></th></tr></thead>
        <tbody>${(pre.length ? pre : [null]).map(row).join("")}</tbody></table>
      <button class="mini" id="ofc-add">＋ ${Z("加一行", "เพิ่มแถว")}</button>
      <label>${Z("定制要求 / 备注（生产任务上会显示）", "รายละเอียดสั่งทำ / หมายเหตุ (แสดงในงานผลิต)")}<textarea id="ofc-note" rows="2" data-notr></textarea></label>
      <div class="row gap"><button class="primary" id="ofc-go">${Z("建单", "สร้างออเดอร์")}</button></div>`);
    el.onchange = (e) => {
      if (e.target.dataset.k !== "sku") return;
      const x = skus.find((k) => k.sku.toUpperCase() === e.target.value.trim().toUpperCase());
      const tr = e.target.closest("tr");
      tr.querySelector("[data-nm]").textContent = x ? `${x.name} ${x.color || ""}` : "";
      const up = tr.querySelector('[data-k="unit_price"]');
      if (x && x.price != null && !up.value) up.value = x.price;
    };
    el.onclick = async (e) => {
      if (e.target.id === "ofc-add") { $("#ofc-items tbody", el).insertAdjacentHTML("beforeend", row(null)); return; }
      if (e.target.dataset.rm != null) { e.target.closest("tr").remove(); return; }
      if (e.target.id !== "ofc-go") return;
      const items = $$("#ofc-items tbody tr", el).map((tr) => {
        const g = (k) => tr.querySelector(`[data-k="${k}"]`).value.trim();
        return { sku: g("sku"), qty: +g("qty") || 1, unit_price: g("unit_price") === "" ? null : +g("unit_price") };
      }).filter((x) => x.sku);
      if (!items.length) { toast(Z("请至少填一个商品 SKU", "กรุณาใส่ SKU อย่างน้อยหนึ่งรายการ"), true); return; }
      const v = (id) => $(id, el).value.trim();
      await busy(e.target, async () => {
        await submit({ kind: v("#ofc-kind"), buyer: v("#ofc-buyer"), items, note: v("#ofc-note"),
          ship: { receiver: v("#ofc-receiver"), phone: v("#ofc-phone"), postcode: v("#ofc-postcode"), address: v("#ofc-address") } });
        MODAL.close();
      });
    };
  }

  async function openOrder(oid) {
    OD_CUR = oid;
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
        ${o.tracking_no ? ` · 运单 <span class="mono" data-notr>${esc(o.tracking_no)}</span>` : ""}
        ${o.status_raw && o.status_raw !== "手工" && String(o.status_raw).toLowerCase() !== o.status ? ` · ${Z("平台状态", "สถานะบนแพลตฟอร์ม")} <span class="mono" data-notr>${esc(o.status_raw)}</span>` : ""}</p>
      ${docPrints(o)}
      ${o.hold && o.status === "to_ship" ? `<div class="hold-box"><b>⏸ 待审核（挂起中，不会排产）</b><div class="small">${esc(o.hold_reason || "")}</div>
        ${canEdit ? '<div class="row gap"><button class="primary" id="od-approve">✔ 审核通过，开始排产</button></div>' : ""}</div>`
        : o.status === "to_ship" && canEdit ? `<div class="row gap small muted">${o.reviewed_by ? `已审核（${esc(o.reviewed_by)}）` : ""}
          ${(o.review_flags || []).length ? `<span class="warn">规则提示：${esc(o.review_flags.join("；"))}</span>` : ""}
          <button class="mini" id="od-hold">⏸ 挂起</button></div>` : ""}
      ${o.risk && o.risk.risky ? `<div class="risk-box">⚠ <b>${Z("风险买家", "ลูกค้าความเสี่ยงสูง")}</b> <span>${esc(o.risk.reason)}</span>
        ${o.is_cod ? `<span class="small">${Z("（货到付款，发货前最好先联系买家确认）", "(COD ควรติดต่อยืนยันกับลูกค้าก่อนส่ง)")}</span>` : ""}</div>` : ""}
      ${o.flag && FLAG_C[o.flag] ? `<div class="small oflag-line"><i class="oflag" style="background:${FLAG_C[o.flag]}"></i>${esc(Z(...FLAG_TXT[o.flag]))}${o.flag_note ? ` · <span data-notr>${esc(o.flag_note)}</span>` : ""}</div>` : ""}
      ${buyerBox(o)}
      ${o.buyer_note ? `<p class="small">买家留言：<b data-notr>${esc(o.buyer_note)}</b></p>` : ""}
      ${o.seller_note ? `<p class="small">卖家备注：<span data-notr>${esc(o.seller_note)}</span></p>` : ""}
      <table class="grid small"><thead><tr><th>SKU</th><th>商品</th><th>颜色</th><th>数量</th><th class="c-final">金额</th><th>克数/时长</th></tr></thead><tbody>
      ${o.items.map((i) => `<tr><td class="mono" data-notr${i.product_id ? ` data-p360="${esc(i.sku)}"` : ""}>${esc(i.sku)}</td><td data-notr>${esc(i.name || "")}${i.variation ? ` <span class="muted">(${esc(i.variation)})</span>` : ""}</td>
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
        ${canEdit ? `<a class="btn" target="_blank" href="/print/orders?type=invoice&ids=${o.id}">${Z("打印发票", "พิมพ์ใบเสร็จ")}</a>
          <button id="od-flag">🎨 ${Z("颜色标记", "ทำสี")}</button>` : ""}
        ${canEdit ? '<button id="od-as">登记售后</button>' : ""}
        ${canEdit && CAN("orders.edit") ? '<button id="od-edit">✏ 修改订单（商品 / 金额 / 买家…）</button>' : ""}
        ${CAN("orders.delete") ? '<button class="danger" id="od-del">删除订单</button>' : ""}
      </div>
      <h4>生产任务</h4>
      ${o.jobs.length ? `<table class="grid small od-jobs"><thead><tr><th>#</th><th>SKU</th><th>颜色</th><th>数量</th><th>已打盘数</th><th>打印机</th><th>状态</th><th>预计完成</th></tr></thead><tbody>
        ${o.jobs.map((j) => `<tr><td>${j.id}</td><td class="mono" data-notr${j.sku ? ` data-p360="${esc(j.sku)}"` : ""}>${esc(j.sku)}</td><td>${colorTxt(j.color)}</td><td>${j.qty}</td><td>${j.plates_done || 0}</td>
          <td data-notr>${esc(printerName(j.printer))}</td><td><span class="jst jst-${j.status}">${esc(JOB_ZH[j.status] || j.status)}</span>${j.fails ? ` <span class="bad small">失败 ${j.fails} 次</span>` : ""}${j.stock_n ? ` <span class="pill tag-pill">📦 ${(window.I18N && I18N.lang === "th") ? "ใช้สต็อก" : "用库存"} ×${j.stock_n}</span>` : ""}</td>
          <td class="small">${j.status === "todo" || j.status === "printing" ? short(j.planned_end) : ""}</td></tr>` +
          (jobActs(j) ? `<tr class="od-job-acts"><td></td><td colspan="7"><div class="row gap wrap">${jobActs(j)}</div></td></tr>` : "")).join("")}</tbody></table>
        <p class="small muted">开始打印、打印中的那一盘请在「生产」页操作。</p>`
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
      <div id="od-photos"></div>
      <details class="log-box"><summary><b>操作记录</b> <span class="muted small">${(o.log || []).length} 条</span></summary>
      <table class="grid small"><tbody>${(o.log || []).map((l) => `<tr><td class="nowrap">${fmtTime(l.ts)}</td><td data-notr>${esc(l.username || "")}</td>
        <td>${esc(l.action)}</td><td class="small" data-notr>${esc(l.detail || "")}</td></tr>`).join("") || '<tr><td class="muted">没有记录</td></tr>'}</tbody></table></details>
    </div>`;
    d.classList.remove("hidden");
    d.querySelector("[data-x]").onclick = () => d.classList.add("hidden");
    if (window.MODKIT && MODKIT.enabled("mobile")) {        // v2.46：手机验货时拍的打包照片（手机 / 平板 App 模块）
      api(`/api/mobile/orders/${oid}/photos`).then((r) => {
        const b = d.querySelector("#od-photos");
        if (b && r.photos.length) b.innerHTML = `<h4>打包照片</h4><div class="row gap wrap">${r.photos.map((p) => `<a href="${esc(p.url)}" target="_blank"
          title="${esc(p.user)} ${fmtTime(p.at)}"><img src="${esc(p.url)}" alt="" loading="lazy" style="width:96px;height:96px;object-fit:cover;border-radius:6px"></a>`).join("")}</div>`;
      }).catch(() => {});
    }
    if (canEdit) lockBox(d.querySelector(".drawer-in"), { id: "order-detail", bar: d.querySelector("#od-lockbar"), label: "✏ 修改",
      keep: "[data-x], #od-as, #od-edit, #od-del, #od-flag, .log-box, details > summary, #od-approve, #od-hold, .buyer-box, [data-asopen], .pb-wrap, .pb-sel, [data-invdoc]",
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
    const flb = d.querySelector("#od-flag");
    if (flb) flb.onclick = () => flagDialog([o.id], o.flag || "", o.flag_note || "");
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
    $("#pf-sku tbody").innerHTML = r.skus.map((s) => `<tr><td class="mono" data-notr data-p360="${esc(s.sku)}">${esc(s.sku)}</td><td data-notr>${esc(s.name)}</td>
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
  window.OPS = { show, loadOrders, orderFromChat, loadMaterials: () => window.MATERIALS && MATERIALS.load(), loadProfit, openOrder, loadSkus, filterBuyer,
    loadIntegrations: () => window.INTG_UI && INTG_UI.load() };
})();
