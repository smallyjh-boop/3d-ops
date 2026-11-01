"use strict";
// 采购单（v2.51）：列表 / 看板、新建和修改（供应商下拉 +「＋新供应商」「管理」、人民币 + 汇率、运费 / 税 / 其他费用）、
// 详情（状态、在途倒计时、到手单价、分次付款、到货差异、退货、退款）、物品采购资料（供应商、购买链接、起订量、价格历史、比价）、
// AI 识别订单开单。共用的小工具在 purchase.js 的 window.PURK。
(function () {
  const K = window.PURK;
  const { Z, TH, num, thb, money, itName, uLab, daysTo, ST, ST_TONE, CAT, ISS, pop } = K;
  const can = (k) => K.can(k);
  const hasMoney = () => K.hasMoney();
  const sups = () => (K.meta() || {}).suppliers || [];
  const PLATS = ["1688", "淘宝", "拼多多", "Shopee", "Lazada", "TikTok", "线下", "其他"];
  const platLab = (p) => (TH() ? ({ "淘宝": "Taobao", "拼多多": "Pinduoduo", "线下": "หน้าร้าน", "其他": "อื่นๆ" }[p] || p) : p);
  const METH = () => ({ "转账": Z("转账", "โอนเงิน"), "现金": Z("现金", "เงินสด"), "信用卡": Z("信用卡", "บัตรเครดิต"), "平台付款": Z("平台付款", "จ่ายผ่านแพลตฟอร์ม"),
    "支付宝": Z("支付宝", "Alipay"), "其他": Z("其他", "อื่นๆ") });

  // ---------------- 列表 / 看板 ----------------
  const FILTERS = () => [["open", Z("进行中", "กำลังดำเนินการ")], ["draft", Z("草稿", "ร่าง")], ["transit", Z("在途", "กำลังส่ง")], ["overdue", Z("过期没到", "เลยกำหนด")],
    ["unpaid", Z("未付清", "ยังจ่ายไม่ครบ")], ["paid", Z("已付清", "จ่ายครบแล้ว")], ["done", Z("完成", "เสร็จสิ้น")], ["", Z("全部", "ทั้งหมด")]];
  let ANA = null;
  async function renderList(box, F) {
    const qs = new URLSearchParams({ status: F.status || "", supplier: F.supplier || "", q: F.q || "" });
    const r = await api(`/api/inv/po?${qs}`);
    const save = () => { try { localStorage.setItem("pur_po_filter", JSON.stringify(F)); } catch { /* 忽略 */ } };
    const bar = `<div class="row between wrap gap pur-bar"><div class="row gap wrap"><span class="chips">${FILTERS().filter(([k]) => hasMoney() || !["unpaid", "paid"].includes(k))
        .map(([k, t]) => `<span class="chip ${F.status === k ? "on" : ""}" data-pf="${k}">${t}</span>`).join("")}</span>
        <select id="pf-sup" data-notr class="pur-sel"><option value="">${Z("全部供应商", "ผู้ขายทั้งหมด")}</option>${sups().map((s) => `<option value="${s.id}" ${String(F.supplier) === String(s.id) ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select>
        <input id="pf-q" placeholder="${Z("单号 / 物流单号 / 物品", "เลขใบ / เลขพัสดุ / รายการ")}" value="${esc(F.q || "")}" class="pur-q"></div>
        <span class="chips"><span class="chip ${F.view !== "board" ? "on" : ""}" data-pv="list">☰ ${Z("列表", "รายการ")}</span><span class="chip ${F.view === "board" ? "on" : ""}" data-pv="board">▦ ${Z("看板", "บอร์ด")}</span></span></div>`;
    let body;
    if (!r.po.length) body = UX.empty(F.status === "open" ? Z("没有进行中的采购单。点「＋ 新采购单」，或者在「补货建议」里一键生成。", "ไม่มีใบสั่งซื้อที่กำลังดำเนินการ กด「＋ ใบสั่งซื้อใหม่」 หรือสร้างจาก「แนะนำเติมสต็อก」") : Z("没有采购单", "ไม่มีใบสั่งซื้อ"));
    else if (F.view === "board") body = board(r.po);
    else body = `<div class="pur-scroll"><table class="grid small pur-po"><thead><tr><th>${Z("单号", "เลขที่")}</th><th>${Z("供应商", "ผู้ขาย")}</th><th>${Z("状态", "สถานะ")}</th><th>${Z("到货", "การส่ง")}</th>
      <th>${Z("物品", "รายการ")}</th>${hasMoney() ? `<th>${Z("金额", "ยอดเงิน")}</th><th>${Z("付款", "การจ่าย")}</th>` : ""}<th>${Z("创建", "สร้าง")}</th></tr></thead><tbody>${r.po.map(row).join("")}</tbody></table></div>`;
    let charts = "";
    if (hasMoney() && r.po.length) {
      try {
        if (!ANA || Date.now() - ANA.t > 60000) ANA = { t: Date.now(), d: await api("/api/inv/pur/analytics") };
        const mo = ANA.d.months, fk = ANA.d.filament_kg;
        charts = `<div class="pur-grid2 pur-charts">${UX.card({ title: Z("每月采购（到货）", "จัดซื้อรายเดือน (รับเข้า)"), right: `<b>${thb(mo[mo.length - 1].spend)}</b>`,
          body: UX.columns(mo.map((x) => ({ label: x.month, value: x.spend, text: thb(x.spend) })), { h: 70, from: mo[0].month, to: mo[mo.length - 1].month }) })}
          ${UX.card({ title: Z("按供应商（近 12 个月）", "ตามผู้ขาย (12 เดือน)"), body: UX.bars(ANA.d.by_supplier.slice(0, 4).map((x) => ({ label: x.name || Z("没有采购单的入库", "รับเข้าโดยไม่มีใบสั่งซื้อ"), value: x.spend, text: thb(x.spend), raw: !!x.name }))) })}
          ${UX.card({ title: Z("耗材每公斤到手价", "ฟิลาเมนต์ถึงมือต่อ kg"), right: `<b>${(fk.filter((x) => x.thb_kg).slice(-1)[0] || {}).thb_kg ? thb(fk.filter((x) => x.thb_kg).slice(-1)[0].thb_kg) + "/kg" : "—"}</b>`,
          body: UX.columns(fk.map((x) => ({ label: x.month, value: x.thb_kg || 0, text: x.thb_kg ? thb(x.thb_kg) : "—" })), { h: 70, from: mo[0].month, to: mo[mo.length - 1].month }) })}</div>`;
      } catch { charts = ""; }
    }
    box.innerHTML = charts + bar + body;
    box.querySelectorAll("[data-pf]").forEach((c) => c.addEventListener("click", () => { F.status = c.dataset.pf; save(); K.renderTab(); }));
    box.querySelectorAll("[data-pv]").forEach((c) => c.addEventListener("click", () => { F.view = c.dataset.pv; save(); K.renderTab(); }));
    box.querySelector("#pf-sup").onchange = (e) => { F.supplier = e.target.value; save(); K.renderTab(); };
    let tm = null;
    box.querySelector("#pf-q").addEventListener("input", (e) => { clearTimeout(tm); tm = setTimeout(() => { F.q = e.target.value.trim(); save(); K.renderTab().then(() => { const q = document.getElementById("pf-q"); if (q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); } }); }, 350); });
  }
  function eta(p) {
    if (p.status === "draft") return `<span class="muted">${p.expected_date ? esc(p.expected_date) : "—"}</span>`;
    if (!["ordered", "partial"].includes(p.status)) return p.received_at ? `<span class="muted small">${fmtTime(p.received_at).slice(0, 10)}</span>` : "";
    const d = daysTo(p.expected_date);
    const t = d == null ? `<span class="muted">${Z("在途", "กำลังส่ง")}</span>` : d < 0 ? `<b class="bad">${Z(`晚 ${-d} 天`, `ช้า ${-d} วัน`)}</b>` : d === 0 ? `<b class="warn">${Z("今天到", "ถึงวันนี้")}</b>` : `${Z(`还有 ${d} 天`, `อีก ${d} วัน`)}`;
    return `${t}${p.tracking ? `<div class="small muted mono" data-notr>${esc(p.tracking)}</div>` : ""}`;
  }
  const lineNames = (p) => `<span data-notr>${p.lines.slice(0, 2).map((l) => esc(itName(l))).join("、")}</span>${p.lines.length > 2 ? ` <span class="muted">+${p.lines.length - 2}</span>` : ""}`;
  function payCell(p) {
    if (p.total === undefined || p.status === "draft") return `<span class="muted">—</span>`;
    const pct = p.total > 0 ? Math.min(100, Math.round(100 * p.paid / p.total)) : 0;
    return `<div class="pur-pay"><i style="width:${pct}%" class="${p.pay_status === "paid" ? "ok" : ""}"></i></div><div class="small ${p.unpaid > 0.01 && p.status !== "draft" ? "warn" : "muted"}">${p.pay_status === "paid" ? Z("已付清", "จ่ายครบ") : `${Z("已付", "จ่ายแล้ว")} ${thb(p.paid)}`}</div>`;
  }
  function row(p) {
    return `<tr class="pur-click" data-po="${p.id}"><td class="mono" data-notr>${esc(p.no)}${p.source === "ai" ? " 🤖" : ""}</td><td data-notr>${esc((p.supplier || {}).name || "—")}</td>
      <td>${UX.dot(ST_TONE[p.status], ST()[p.status] || p.status)}${p.issues_open ? ` <span class="warn small" title="${Z("到货差异", "ของไม่ตรง")}">⚠${p.issues_open}</span>` : ""}</td>
      <td class="nowrap">${eta(p)}</td><td>${lineNames(p)}</td>
      ${hasMoney() ? `<td class="nowrap">${thb(p.total)}${p.currency === "CNY" ? `<div class="small muted">¥${num(p.total_cur)}</div>` : ""}</td><td>${payCell(p)}</td>` : ""}
      <td class="nowrap small muted">${fmtTime(p.created_at).slice(0, 10)}</td></tr>`;
  }
  function board(list) {
    const cols = [["draft", ["draft"]], ["ordered", ["ordered"]], ["partial", ["partial"]], ["received", ["received"]], ["done", ["done", "returned", "cancelled"]]];
    return `<div class="pur-board">${cols.map(([k, sts]) => {
      const ps = list.filter((p) => sts.includes(p.status));
      return `<div class="pur-col"><div class="pur-col-h">${UX.dot(ST_TONE[k], ST()[k])} <b>${ps.length}</b></div>${ps.map((p) => `<div class="pur-card" data-po="${p.id}">
        <div class="row between"><b class="mono small" data-notr>${esc(p.no)}</b>${hasMoney() && p.total !== undefined ? `<span class="small">${thb(p.total)}</span>` : ""}</div>
        <div class="small" data-notr>${esc((p.supplier || {}).name || "—")}</div><div class="small">${lineNames(p)}</div>
        <div class="small">${["ordered", "partial"].includes(p.status) ? eta(p) : (p.status !== k ? ST()[p.status] : "")}</div>
        ${hasMoney() && p.status !== "draft" && p.unpaid > 0.01 ? `<div class="small warn">${Z("未付", "ค้างจ่าย")} ${thb(p.unpaid)}</div>` : ""}</div>`).join("") || `<p class="ux-empty">—</p>`}</div>`;
    }).join("")}</div>`;
  }

  // ---------------- 供应商：下拉、新建、管理 ----------------
  function supOptions(sel) {
    return `<option value="">${Z("— 选供应商 —", "— เลือกผู้ขาย —")}</option>` + sups().filter((s) => s.active || s.id === +sel)
      .map((s) => `<option value="${s.id}" data-cur="${esc(s.currency || "THB")}" data-lead="${s.lead_days ?? ""}" ${s.id === +sel ? "selected" : ""}>${esc(s.name)}${s.platform ? ` · ${esc(platLab(s.platform))}` : ""}</option>`).join("");
  }
  async function reloadSups() { const r = await api("/api/inv/suppliers?all=1"); (K.meta() || {}).suppliers = r.suppliers; return r.suppliers; }
  function supForm(s, done) {
    s = s || { active: 1 };
    const f = (k, l, t = "text", ex = "") => `<label>${l}<input data-s="${k}" type="${t}" value="${esc(s[k] ?? "")}" ${ex} data-notr></label>`;
    const p = pop(`<h3>${s.id ? Z("修改供应商", "แก้ไขผู้ขาย") : Z("新供应商", "ผู้ขายใหม่")}</h3><div class="form3">${f("name", Z("名称", "ชื่อ"))}
      <label>${Z("平台", "แพลตฟอร์ม")}<select data-s="platform"><option value="">—</option>${PLATS.map((x) => `<option value="${x}" ${s.platform === x ? "selected" : ""}>${esc(platLab(x))}</option>`).join("")}</select></label>
      <label>${Z("货币", "สกุลเงิน")}<select data-s="currency"><option value="">${Z("按平台自动", "ตามแพลตฟอร์ม")}</option><option value="CNY" ${s.currency === "CNY" ? "selected" : ""}>${Z("人民币 ¥", "หยวน ¥")}</option><option value="THB" ${s.currency === "THB" ? "selected" : ""}>${Z("泰铢 ฿", "บาท ฿")}</option></select></label>
      ${f("lead_days", Z("一般几天到货", "ปกติกี่วันถึง"), "number", 'step="any" min="0"')}${f("link", Z("店铺链接", "ลิงก์ร้าน"))}${f("contact", Z("联系人", "ผู้ติดต่อ"))}${f("phone", Z("电话 / 微信", "โทร / WeChat"))}${f("note", Z("备注", "หมายเหตุ"))}
      ${s.id ? `<label>${Z("启用", "ใช้งาน")}<select data-s="active"><option value="1" ${s.active ? "selected" : ""}>${Z("是", "ใช่")}</option><option value="0" ${s.active ? "" : "selected"}>${Z("否", "ไม่")}</option></select></label>` : ""}</div>
      <div class="row gap"><button class="primary" id="sf-ok">${Z("保存", "บันทึก")}</button><button data-pclose>${Z("取消", "ยกเลิก")}</button></div>`);
    p.el.querySelector('[data-s="name"]').focus();
    p.el.querySelector("#sf-ok").onclick = (e) => busy(e.target, async () => {
      const d = { id: s.id }; p.el.querySelectorAll("[data-s]").forEach((el) => (d[el.dataset.s] = el.value));
      const r = await api("/api/inv/suppliers", { json: d });
      await reloadSups(); p.close(); toast(Z("已保存", "บันทึกแล้ว"));
      if (done) done(r.supplier);
    });
  }
  async function manageSuppliers(onChange) {
    await K.ensureMeta();
    const list = await reloadSups();
    const p = pop(`<div class="row between"><h3>🏪 ${Z("供应商", "ผู้ขาย")}</h3><div class="row gap">${can("inv.in") ? `<button class="primary mini" id="sm-new">＋ ${Z("新供应商", "ผู้ขายใหม่")}</button>` : ""}<button class="mini" data-pclose>✕</button></div></div>
      <div class="pur-scroll"><table class="grid small"><thead><tr><th>${Z("名称", "ชื่อ")}</th><th>${Z("平台", "แพลตฟอร์ม")}</th><th>${Z("货币", "สกุลเงิน")}</th><th>${Z("到货天数", "วันรอของ")}</th><th>${Z("联系", "ติดต่อ")}</th><th></th></tr></thead><tbody>
      ${list.map((s) => `<tr class="${s.active ? "" : "muted"}"><td data-notr><b>${esc(s.name)}</b></td><td>${s.link ? `<a href="${esc(s.link)}" target="_blank" rel="noopener" data-notr>${esc(platLab(s.platform) || "🔗")}</a>` : `<span data-notr>${esc(platLab(s.platform || ""))}</span>`}</td>
        <td>${esc(s.currency || "")}</td><td>${s.lead_days ?? ""}</td><td class="small" data-notr>${esc([s.contact, s.phone].filter(Boolean).join(" "))}</td>
        <td class="nowrap">${can("inv.in") ? `<button class="mini" data-se="${s.id}">${Z("修改", "แก้ไข")}</button><button class="mini danger" data-sd="${s.id}" title="${Z("没用过的直接删，用过的停用", "ที่ยังไม่เคยใช้จะลบ ที่เคยใช้จะปิดใช้งาน")}">✕</button>` : ""}</td></tr>`).join("") ||
        `<tr><td colspan="6" class="muted">${Z("还没有供应商", "ยังไม่มีผู้ขาย")}</td></tr>`}</tbody></table></div>`, "wide");
    const again = () => { p.close(); manageSuppliers(onChange); if (onChange) onChange(); };
    const nb = p.el.querySelector("#sm-new"); if (nb) nb.onclick = () => supForm(null, again);
    p.el.addEventListener("click", async (e) => {
      const ed = e.target.closest("[data-se]"); if (ed) return supForm(list.find((x) => x.id === +ed.dataset.se), again);
      const dl = e.target.closest("[data-sd]");
      if (dl) {
        const s = list.find((x) => x.id === +dl.dataset.sd);
        if (!confirm(Z(`删除供应商「${s.name}」？（用过的会改成停用）`, `ลบผู้ขาย「${s.name}」? (ที่เคยใช้จะเปลี่ยนเป็นปิดใช้งาน)`))) return;
        const r = await api(`/api/inv/pur/suppliers/${s.id}/delete`, { json: {} });
        toast(r.deleted ? Z("已删除", "ลบแล้ว") : Z("用过了，已停用", "เคยใช้แล้ว เปลี่ยนเป็นปิดใช้งาน"));
        again();
      }
    });
  }
  // 供应商下拉旁边的两个按钮：「＋新供应商」「管理」
  function supButtons() {
    return can("inv.in") ? `<span class="pur-supbtns"><button type="button" class="mini" data-sup-new>＋${Z("新供应商", "ผู้ขายใหม่")}</button><button type="button" class="mini" data-sup-man>${Z("管理", "จัดการ")}</button></span>` : "";
  }
  function bindSupButtons(scope, sel) {
    const refresh = (pick) => { const v = pick ? pick.id : sel.value; sel.innerHTML = supOptions(v); sel.value = v || ""; sel.dispatchEvent(new Event("change", { bubbles: true })); };
    const n = scope.querySelector("[data-sup-new]"); if (n) n.onclick = () => supForm(null, refresh);
    const m = scope.querySelector("[data-sup-man]"); if (m) m.onclick = () => manageSuppliers(() => refresh());
  }

  // ---------------- 新建 / 修改采购单 ----------------
  let ITEMS = null;
  async function items(force) { if (!ITEMS || force) ITEMS = (await api("/api/inv/pur/items")).items; return ITEMS; }
  async function form(po, pre) {
    await K.ensureMeta();
    const its = await items(true);
    const p = po || pre || { lines: [{}], ship_fee: 0, other_fee: 0, tax_fee: 0, currency: "THB" };
    const fx0 = (K.meta() || {}).fx || 4.5;
    const opts = (sel) => `<option value="">${Z("选物品", "เลือกรายการ")}</option>` + its.map((it) => `<option value="${it.id}" ${+sel === it.id ? "selected" : ""}>${esc(it.code)} · ${esc(itName(it))}</option>`).join("");
    const row = (l = {}) => `<tr><td><select data-l="item_id" data-notr class="pur-item">${opts(l.item_id)}</select> <a class="pur-buy hidden" target="_blank" rel="noopener" title="${Z("打开购买链接", "เปิดลิงก์ซื้อ")}">🛒</a></td>
      <td class="nowrap"><span class="po-q"><input data-l="qty" type="number" step="any" min="0" value="${l.rolls ? "" : (l.qty ?? "")}" class="pur-num"> <span class="muted po-unit"></span></span>
        <span class="po-roll hidden"><input data-l="rolls" type="number" step="1" min="0" value="${l.rolls ?? ""}" class="pur-num" style="width:56px"> ${Z("卷", "ม้วน")} ×
          <input data-l="net_g" type="number" value="${l.net_g ?? 1000}" style="width:64px"> g</span></td>
      <td class="nowrap"><input data-l="price" type="number" step="any" min="0" value="${l.unit_cost != null ? (l.rolls ? +(l.unit_cost * (l.net_g || 1000)).toFixed(4) : l.unit_cost) : ""}" class="pur-num"> <span class="muted small po-pu"></span></td>
      <td><input data-l="note" value="${esc(l.note || "")}" class="pur-note" data-notr></td><td><button type="button" class="mini danger" data-rm>✕</button></td></tr>`;
    const m = MODAL.open(`<h3>${po ? `${Z("采购单", "ใบสั่งซื้อ")} <span class="mono" data-notr>${esc(po.no)}</span>` : Z("新采购单", "ใบสั่งซื้อใหม่")}</h3>
      <div class="form4 pur-form">
        <label class="pur-supl">${Z("供应商", "ผู้ขาย")}<span class="row gap"><select id="pf-sup" data-notr>${supOptions(p.supplier_id)}</select>${supButtons()}</span></label>
        <label>${Z("货币", "สกุลเงิน")}<select id="pf-cur"><option value="THB" ${p.currency !== "CNY" ? "selected" : ""}>${Z("泰铢 ฿", "บาท ฿")}</option><option value="CNY" ${p.currency === "CNY" ? "selected" : ""}>${Z("人民币 ¥", "หยวน ¥")}</option></select></label>
        <label class="pf-fx">${Z("汇率（1 元 = ? 铢）", "อัตรา (1 หยวน = ? บาท)")}<input id="pf-fx" type="number" step="any" min="0" value="${p.currency === "CNY" ? (p.fx_rate || fx0) : fx0}"></label>
        <label>${Z("预计到货", "คาดว่าถึง")}<input id="pf-exp" type="date" value="${esc(p.expected_date || "")}"></label>
        <label>${Z("平台订单号", "เลขออเดอร์")}<input id="pf-ref" value="${esc(p.order_ref || "")}" data-notr></label>
        <label>${Z("物流公司", "บริษัทขนส่ง")}<input id="pf-car" value="${esc(p.carrier || "")}" data-notr></label>
        <label>${Z("物流单号", "เลขพัสดุ")}<input id="pf-trk" value="${esc(p.tracking || "")}" data-notr></label>
        <label><span>${Z("供应商运费", "ค่าส่งของผู้ขาย")} <span class="pf-cs">฿</span></span><input id="pf-ship" type="number" step="any" min="0" value="${p.ship_fee || 0}"></label>
        <label>${Z("进口税 / 关税（฿）", "ภาษีนำเข้า (฿)")}<input id="pf-tax" type="number" step="any" min="0" value="${p.tax_fee || 0}"></label>
        <label>${Z("国际运费 / 其他（฿）", "ค่าขนส่งระหว่างประเทศ / อื่นๆ (฿)")}<input id="pf-other" type="number" step="any" min="0" value="${p.other_fee || 0}"></label>
        <label class="pur-wide">${Z("备注", "หมายเหตุ")}<input id="pf-note" value="${esc(p.note || "")}" data-notr></label></div>
      <p class="small muted">${Z("耗材按卷填（卷数 × 每卷克数），单价填每卷的价格。运费、税、其他费用到货时按金额分摊进每个物品的到手单价；人民币按这里的汇率折成泰铢。",
        "ฟิลาเมนต์กรอกเป็นม้วน (จำนวนม้วน × กรัมต่อม้วน) ราคาใส่ต่อม้วน ค่าส่ง ภาษี ค่าอื่นๆ จะเฉลี่ยเข้าต้นทุนถึงมือของแต่ละรายการตอนรับของ หยวนแปลงเป็นบาทตามอัตรานี้")}</p>
      <div class="pur-scroll"><table class="grid small" id="pf-lines"><thead><tr><th>${Z("物品", "รายการ")}</th><th>${Z("数量", "จำนวน")}</th><th>${Z("单价", "ราคา")} <span class="pf-cs">฿</span></th><th>${Z("备注", "หมายเหตุ")}</th><th></th></tr></thead>
        <tbody>${(p.lines && p.lines.length ? p.lines : [{}]).map(row).join("")}</tbody></table></div>
      <button type="button" class="mini" id="pf-add">＋ ${Z("加一行", "เพิ่มแถว")}</button> <span id="pf-sum" class="small"></span>
      <div class="row gap" style="margin-top:10px"><button class="primary" id="pf-save">${Z("保存草稿", "บันทึกร่าง")}</button><button id="pf-save-order">${Z("保存并下单", "บันทึกและสั่งซื้อ")}</button><button data-mclose>${Z("取消", "ยกเลิก")}</button></div>`);
    m.classList.add("wide");
    const tb = m.querySelector("#pf-lines tbody"), supSel = m.querySelector("#pf-sup"), curSel = m.querySelector("#pf-cur");
    bindSupButtons(m, supSel);
    const cur = () => curSel.value;
    const linkOf = (it) => it && (it.links.find((x) => x.supplier_id === +supSel.value) || null);
    const sync = (tr, fill) => {
      const it = its.find((x) => x.id === +tr.querySelector('[data-l="item_id"]').value);
      const fil = it && it.category === "filament";
      tr.querySelector(".po-roll").classList.toggle("hidden", !fil);
      tr.querySelector(".po-q").classList.toggle("hidden", !!fil);
      tr.querySelector(".po-unit").textContent = it ? uLab(it.unit) : "";
      tr.querySelector(".po-pu").textContent = fil ? Z("/卷", "/ม้วน") : (it ? "/" + uLab(it.unit) : "");
      const lk = linkOf(it), buy = tr.querySelector(".pur-buy"), url = lk && lk.urls && lk.urls[0];
      buy.classList.toggle("hidden", !url); if (url) buy.href = url;
      if (fill && it) {
        const pr = tr.querySelector('[data-l="price"]');
        const net = +tr.querySelector('[data-l="net_g"]').value || (lk && lk.net_g) || 1000;
        if (lk && lk.net_g && fil) tr.querySelector('[data-l="net_g"]').value = lk.net_g;
        let v = null;
        if (lk && lk.price != null) v = lk.price * ((lk.currency || "THB") === cur() ? 1 : (cur() === "CNY" ? 1 / (+m.querySelector("#pf-fx").value || fx0) : (+m.querySelector("#pf-fx").value || fx0)));
        else if (it.avg_cost) v = it.avg_cost / (cur() === "CNY" ? (+m.querySelector("#pf-fx").value || fx0) : 1);
        if (v != null && !pr.value) pr.value = +(fil ? v * net : v).toFixed(fil ? 2 : 4);
      }
    };
    const sum = () => {
      let g = 0;
      [...tb.rows].forEach((tr) => { const v = (k) => +(tr.querySelector(`[data-l="${k}"]`).value || 0);
        const it = its.find((x) => x.id === +tr.querySelector('[data-l="item_id"]').value);
        g += (it && it.category === "filament" ? v("rolls") : v("qty")) * v("price"); });
      const fx = cur() === "CNY" ? (+m.querySelector("#pf-fx").value || fx0) : 1;
      const ship = +m.querySelector("#pf-ship").value || 0, tax = +m.querySelector("#pf-tax").value || 0, oth = +m.querySelector("#pf-other").value || 0;
      const tot = (g + ship) * fx + tax + oth;
      m.querySelectorAll(".pf-cs").forEach((x) => (x.textContent = cur() === "CNY" ? "¥" : "฿"));
      m.querySelector(".pf-fx").classList.toggle("hidden", cur() !== "CNY");
      m.querySelector("#pf-sum").innerHTML = `${Z("货款", "ค่าสินค้า")} <b>${money(g, cur())}</b>${cur() === "CNY" ? ` + ${Z("运费", "ค่าส่ง")} ¥${num(ship)} → ${thb((g + ship) * fx, 2)}` : ship ? ` + ${Z("运费", "ค่าส่ง")} ${thb(ship)}` : ""}${tax ? ` + ${Z("税", "ภาษี")} ${thb(tax)}` : ""}${oth ? ` + ${Z("其他", "อื่นๆ")} ${thb(oth)}` : ""} = <b>${thb(tot, 2)}</b>${g > 0 && tot > g * fx ? ` <span class="muted">（${Z("分摊比例", "สัดส่วนเฉลี่ย")} +${num(100 * (tot / (g * fx) - 1), 1)}%）</span>` : ""}`;
    };
    [...tb.rows].forEach((tr) => sync(tr, false)); sum();
    supSel.addEventListener("change", () => {
      const o = supSel.selectedOptions[0];
      if (o && o.dataset.cur && !po) { curSel.value = o.dataset.cur; }
      if (o && o.dataset.lead && !m.querySelector("#pf-exp").value) { const d = new Date(); d.setDate(d.getDate() + Math.ceil(+o.dataset.lead)); m.querySelector("#pf-exp").value = d.toISOString().slice(0, 10); }
      [...tb.rows].forEach((tr) => sync(tr, false)); sum();
    });
    m.querySelector("#pf-add").onclick = () => { tb.insertAdjacentHTML("beforeend", row()); if (window.I18N && I18N.translate) I18N.translate(tb.lastElementChild); };
    m.onclick = (e) => { if (e.target.dataset.rm !== undefined && tb.rows.length > 1) { e.target.closest("tr").remove(); sum(); } };
    m.onchange = (e) => { const tr = e.target.closest("tr"); if (tr && tr.closest("#pf-lines")) sync(tr, e.target.dataset.l === "item_id"); sum(); };
    m.oninput = sum;
    const save = (andOrder) => async () => {
      const lines = [...tb.rows].map((tr) => {
        const g = (k) => tr.querySelector(`[data-l="${k}"]`).value;
        const it = its.find((x) => x.id === +g("item_id"));
        if (!it) return null;
        const d = { item_id: it.id, note: g("note") };
        if (it.category === "filament") { d.rolls = g("rolls"); d.net_g = g("net_g") || 1000; if (g("price") !== "") d.unit_cost = +g("price") / (+d.net_g || 1000); }
        else { d.qty = g("qty"); if (g("price") !== "") d.unit_cost = g("price"); }
        return d;
      }).filter(Boolean);
      const body = { id: po ? po.id : undefined, supplier_id: supSel.value, currency: cur(), fx_rate: m.querySelector("#pf-fx").value, expected_date: m.querySelector("#pf-exp").value,
        ship_fee: m.querySelector("#pf-ship").value, tax_fee: m.querySelector("#pf-tax").value, other_fee: m.querySelector("#pf-other").value,
        order_ref: m.querySelector("#pf-ref").value, carrier: m.querySelector("#pf-car").value, tracking: m.querySelector("#pf-trk").value, note: m.querySelector("#pf-note").value };
      if (!po || po.status === "draft") body.lines = lines;
      let r = await api("/api/inv/po", { json: body });
      if (andOrder) r = await api(`/api/inv/po/${r.po.id}/order`, { json: {} });
      toast(andOrder ? Z("已下单，在途中", "สั่งซื้อแล้ว กำลังขนส่ง") : Z("已保存", "บันทึกแล้ว"));
      MODAL.close(); K.setTab("po"); await K.render();
      if (!andOrder) view(r.po.id);
    };
    m.querySelector("#pf-save").onclick = (e) => busy(e.target, save(false));
    m.querySelector("#pf-save-order").onclick = (e) => busy(e.target, save(true));
    if (!po && po !== undefined && pre && pre.lines) [...tb.rows].forEach((tr) => sync(tr, false));
  }

  // ---------------- 采购单详情 ----------------
  const FLOW = ["draft", "ordered", "partial", "received", "done"];
  async function view(id) {
    const po = (await api(`/api/inv/po/${id}`)).po;
    const open = po.status === "ordered" || po.status === "partial";
    const step = FLOW.indexOf(po.status);
    const flow = `<div class="pur-flow">${FLOW.map((s, i) => `<span class="${i < step ? "past" : i === step ? "cur" : ""}">${ST()[s]}</span>`).join("<i>›</i>")}
      ${["cancelled", "returned"].includes(po.status) ? `<span class="cur bad">${ST()[po.status]}</span>` : ""}</div>`;
    const d = daysTo(po.expected_date);
    const etaTxt = open && d != null ? (d < 0 ? `<b class="bad">${Z(`晚了 ${-d} 天`, `ช้า ${-d} วัน`)}</b>` : d === 0 ? `<b class="warn">${Z("今天到", "ถึงวันนี้")}</b>` : Z(`还有 ${d} 天`, `อีก ${d} วัน`)) : "";
    const money_ = po.total !== undefined;
    const cs = po.currency === "CNY";
    const lines = po.lines.map((l) => {
      const roll = !!l.rolls, net = l.net_g || 1000;
      const q = (v) => (roll ? `${num(v / net, 2)} ${Z("卷", "ม้วน")} · ${num(v / 1000, 2)} kg` : `${num(v)} ${esc(uLab(l.unit))}`);      // v2.55：卷数旁边带公斤
      return `<tr><td data-notr><a href="#" data-item-links="${l.item_id}"><b>${esc(itName(l))}</b></a><div class="small muted">${esc(l.code)}${l.location ? ` · 📍${esc(l.location)}` : ""}</div></td>
        <td class="nowrap">${q(l.qty)}</td><td class="nowrap">${q(l.received || 0)}${l.returned ? `<div class="small warn">${Z("退", "คืน")} ${q(l.returned)}</div>` : ""}</td>
        ${money_ ? `<td class="nowrap">${money(roll ? l.unit_cost * net : l.unit_cost, po.currency, 4)}${roll ? Z("/卷", "/ม้วน") : ""}</td><td class="nowrap">${thb(roll ? l.landed * net : l.landed, 2)}${roll ? Z("/卷", "/ม้วน") : ""}</td>
        <td class="nowrap">${money((l.qty || 0) * (l.unit_cost || 0), po.currency)}</td>` : ""}</tr>`;
    }).join("");
    const pays = (po.payments || []).map((x) => `<tr><td class="nowrap">${esc(x.day)}</td><td class="${x.amount < 0 ? "ok" : ""}">${thb(x.amount, 2)}</td><td>${esc(METH()[x.method] || x.method || "")}</td><td class="muted" data-notr>${esc(x.note || "")}</td><td class="small muted" data-notr>${esc(x.username || "")}</td></tr>`).join("");
    const iss = (po.issues || []).map((x) => {
      const l = po.lines.find((y) => y.id === x.line_id) || {};
      return `<tr class="${x.status === "open" ? "" : "muted"}"><td data-notr>${esc(itName(l))}</td><td>${esc(ISS()[x.kind] || x.kind)}</td><td>${l.rolls ? `${num(x.qty / (l.net_g || 1000))} ${Z("卷", "ม้วน")}` : num(x.qty)}</td>
        <td class="small" data-notr>${esc(x.note || "")}${x.resolution ? ` → ${esc(x.resolution)}` : ""}</td><td>${x.status === "open" ? (can("inv.in") ? `<button class="mini" data-iss-ok="${x.id}">${Z("处理好了", "จัดการแล้ว")}</button>` : Z("没处理", "ยังไม่จัดการ")) : "✓"}</td></tr>`;
    }).join("");
    const m = MODAL.open(`<div class="row between wrap"><h3>${Z("采购单", "ใบสั่งซื้อ")} <span class="mono" data-notr>${esc(po.no)}</span> ${po.source === "ai" ? "🤖" : ""}</h3><button data-mclose>✕</button></div>
      ${flow}
      <div class="pur-info small"><div><span class="muted">${Z("供应商", "ผู้ขาย")}</span> <b data-notr>${esc((po.supplier || {}).name || "—")}</b>${(po.supplier || {}).link ? ` <a href="${esc(po.supplier.link)}" target="_blank" rel="noopener">🔗</a>` : ""}</div>
        ${cs ? `<div><span class="muted">${Z("货币", "สกุลเงิน")}</span> ¥ · ${Z("汇率", "อัตรา")} ${num(po.fx_rate, 4)}</div>` : ""}
        <div><span class="muted">${Z("预计到货", "คาดว่าถึง")}</span> ${esc(po.expected_date || "—")} ${etaTxt}</div>
        ${po.order_ref ? `<div><span class="muted">${Z("平台订单号", "เลขออเดอร์")}</span> <span class="mono" data-notr>${esc(po.order_ref)}</span></div>` : ""}
        <div><span class="muted">${Z("物流", "ขนส่ง")}</span> <span class="mono" data-notr>${esc([po.carrier, po.tracking].filter(Boolean).join(" ") || "—")}</span></div>
        ${po.note ? `<div><span class="muted">${Z("备注", "หมายเหตุ")}</span> <span data-notr>${esc(po.note)}</span></div>` : ""}</div>
      <div class="pur-scroll"><table class="grid small"><thead><tr><th>${Z("物品", "รายการ")}</th><th>${Z("订了", "สั่ง")}</th><th>${Z("已到", "ถึงแล้ว")}</th>
        ${money_ ? `<th>${Z("单价", "ราคา")}</th><th>${Z("到手单价", "ต้นทุนถึงมือ")} ${UX.help(Z("单价 × 汇率 × (1 + 运费、税、其他费用按金额分摊的比例)，到货入库按这个记成本", "ราคา × อัตรา × (1 + สัดส่วนค่าส่ง ภาษี ค่าอื่นๆ เฉลี่ยตามมูลค่า) รับเข้าคลังด้วยต้นทุนนี้"))}</th><th>${Z("金额", "ยอด")}</th>` : ""}</tr></thead><tbody>${lines}</tbody></table></div>
      ${money_ ? `<div class="pur-money small"><span>${Z("货款", "ค่าสินค้า")} ${thb(po.goods_total, 2)}${cs ? ` (¥${num(po.goods_total_cur)})` : ""}</span>
        ${po.fees_counted && po.ship_fee ? `<span>+ ${Z("运费", "ค่าส่ง")} ${money(po.ship_fee, po.currency)}</span>` : ""}${po.fees_counted && po.tax_fee ? `<span>+ ${Z("税", "ภาษี")} ${thb(po.tax_fee)}</span>` : ""}
        ${po.fees_counted && po.other_fee ? `<span>+ ${Z("其他", "อื่นๆ")} ${thb(po.other_fee)}</span>` : ""}<span>= <b>${thb(po.total, 2)}</b></span>
        <span>· ${Z("已付", "จ่ายแล้ว")} <b>${thb(po.paid, 2)}</b></span>${po.unpaid > 0.01 ? `<span class="warn">· ${Z("还欠", "ค้าง")} <b>${thb(po.unpaid, 2)}</b></span>` : ""}
        ${po.paid > po.total + 0.01 ? `<span class="warn">· ${Z("多付了", "จ่ายเกิน")} ${thb(po.paid - po.total, 2)}</span>` : ""}</div>` : ""}
      ${pays ? `<h4>${Z("付款记录", "ประวัติการจ่ายเงิน")}</h4><table class="grid small"><tbody>${pays}</tbody></table>` : ""}
      ${money_ && can("inv.pay") && po.status !== "draft" ? `<div class="pur-payf row gap wrap"><b>${Z("记付款", "บันทึกการจ่ายเงิน")}</b>
        <input type="number" step="any" min="0" id="pv-amt" value="${po.unpaid > 0.01 ? po.unpaid.toFixed(2) : ""}" placeholder="${Z("金额 ฿", "จำนวน ฿")}" class="pur-num">
        <select id="pv-meth">${Object.entries(METH()).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
        <input type="date" id="pv-day" value="${new Date().toISOString().slice(0, 10)}"><input id="pv-pnote" placeholder="${Z("备注", "หมายเหตุ")}" class="pur-note" data-notr>
        <button class="primary mini" id="pv-pay">${Z("记付款", "บันทึกจ่าย")}</button>${po.paid > 0 ? `<button class="mini" id="pv-refund" title="${Z("供应商退回的钱（记成负的付款）", "เงินที่ผู้ขายคืน (บันทึกเป็นยอดจ่ายติดลบ)")}">${Z("供应商退款", "ผู้ขายคืนเงิน")}</button>` : ""}
        ${UX.help(Z("可以分几次付。每笔都会自动记到「财务 → 收支与现金流」。", "จ่ายหลายงวดได้ ทุกงวดบันทึกใน「การเงิน → รายรับรายจ่ายและกระแสเงินสด」อัตโนมัติ"))}</div>` : ""}
      ${iss ? `<h4>${Z("到货差异", "ของไม่ตรง")}</h4><table class="grid small"><tbody>${iss}</tbody></table>` : ""}
      ${po.docs && po.docs.length ? `<p class="small muted">${Z("入库单", "ใบรับเข้า")}：<span data-notr>${po.docs.map((x) => esc(x.no)).join("、")}</span></p>` : ""}
      <div class="row gap wrap" style="margin-top:10px">
        ${po.status === "draft" && can("inv.in") ? `<button id="pv-edit">${Z("修改", "แก้ไข")}</button><button class="primary" id="pv-order">${Z("下单（变在途）", "สั่งซื้อ (กำลังส่ง)")}</button>` : ""}
        ${open && can("inv.in") ? `<button class="primary" id="pv-rcv">📥 ${Z("到货入库", "รับของ")}</button><button id="pv-edit2">${Z("改物流 / 预计到货", "แก้ขนส่ง / วันถึง")}</button>` : ""}
        ${po.status === "partial" && can("inv.in") ? `<button id="pv-close">${Z("结单（剩下的不要了）", "ปิดใบ (ที่เหลือไม่เอาแล้ว)")}</button>` : ""}
        ${po.status === "received" && can("inv.in") ? `<button id="pv-done">${Z("标记完成", "ทำเครื่องหมายเสร็จ")}</button>` : ""}
        ${["partial", "received", "done"].includes(po.status) && can("inv.in") ? `<button id="pv-ret">${Z("退货给供应商", "คืนของให้ผู้ขาย")}</button>` : ""}
        ${(po.docs && po.docs.length) ? `<a class="btn" target="_blank" href="/print/pur-labels?po=${encodeURIComponent(po.no)}${TH() ? "&lang=th" : ""}">🏷 ${Z("打印物品标签", "พิมพ์ป้ายสินค้า")}</a>` : ""}
        ${["draft", "ordered", "partial"].includes(po.status) && can("inv.in") ? `<button class="danger" id="pv-cancel">${Z("取消采购单", "ยกเลิกใบสั่งซื้อ")}</button>` : ""}</div>`);
    m.classList.add("wide");
    const reopen = async (msg) => { toast(msg || Z("已完成", "เสร็จแล้ว")); await K.render(); await view(po.id); };
    const act = (a, body) => async () => { await api(`/api/inv/po/${po.id}/${a}`, { json: body || {} }); await reopen(); };
    const on = (sel, fn) => { const b = m.querySelector(sel); if (b) b.onclick = (e) => busy(e.target, fn); };
    on("#pv-edit", async () => { MODAL.close(); await form(po); });
    on("#pv-edit2", async () => { MODAL.close(); await form(po); });
    on("#pv-order", act("order"));
    on("#pv-rcv", async () => { MODAL.close(); await K.receiveDialog(po.id); });
    on("#pv-close", async () => { if (confirm(Z("结单后剩下没到的不再等了？", "ปิดใบแล้วที่ยังไม่ถึงจะไม่รอแล้ว?"))) await act("close")(); });
    on("#pv-done", act("done"));
    on("#pv-cancel", async () => { if (confirm(Z("取消这张采购单？", "ยกเลิกใบสั่งซื้อนี้?"))) await act("cancel")(); });
    on("#pv-pay", async () => {
      await api(`/api/inv/po/${po.id}/pay`, { json: { amount: m.querySelector("#pv-amt").value, method: m.querySelector("#pv-meth").value, day: m.querySelector("#pv-day").value, note: m.querySelector("#pv-pnote").value } });
      await reopen(Z("已记付款（财务也记了）", "บันทึกการจ่ายแล้ว (การเงินบันทึกด้วย)"));
    });
    on("#pv-refund", async () => {
      const a = prompt(Z("供应商退了多少钱（฿）", "ผู้ขายคืนเงินเท่าไร (฿)"), po.paid > po.total ? (po.paid - po.total).toFixed(2) : "");
      if (!a) return;
      await api(`/api/inv/po/${po.id}/refund`, { json: { amount: a, method: m.querySelector("#pv-meth").value, note: m.querySelector("#pv-pnote").value } });
      await reopen();
    });
    on("#pv-ret", async () => returnDialog(po));
    m.addEventListener("click", (e) => {
      const io = e.target.closest("[data-iss-ok]");
      if (!io) return;
      e.stopPropagation();
      const res = prompt(Z("怎么处理的（供应商补发 / 退款 / 不追了…）", "จัดการอย่างไร (ผู้ขายส่งเพิ่ม / คืนเงิน / ไม่ตามแล้ว…)"), "");
      if (res == null) return;
      busy(io, async () => { await api(`/api/inv/pur/issues/${io.dataset.issOk}/resolve`, { json: { resolution: res } }); await reopen(); });
    });
  }
  function returnDialog(po) {
    const ls = po.lines.filter((l) => (l.received || 0) - (l.returned || 0) > 1e-9);
    const p = pop(`<h3>${Z("退货给供应商", "คืนของให้ผู้ขาย")}</h3><p class="small muted">${Z("从库存出库（按到手成本，不算支出）。供应商退的钱在采购单里点「供应商退款」记。", "ตัดออกจากสต็อก (ตามต้นทุนถึงมือ ไม่นับเป็นค่าใช้จ่าย) เงินที่ผู้ขายคืนบันทึกที่「ผู้ขายคืนเงิน」ในใบสั่งซื้อ")}</p>
      <table class="grid small"><tbody>${ls.map((l) => { const can_ = (l.received || 0) - (l.returned || 0), roll = !!l.rolls;
        return `<tr><td data-notr>${esc(itName(l))}</td><td>${Z("可退", "คืนได้")} ${roll ? `${num(can_ / (l.net_g || 1000))} ${Z("卷", "ม้วน")}` : `${num(can_)} ${esc(uLab(l.unit))}`}</td>
          <td><input type="number" min="0" step="${roll ? 1 : "any"}" data-ret="${l.id}" class="pur-num"></td></tr>`; }).join("")}</tbody></table>
      <input id="ret-note" placeholder="${Z("原因", "เหตุผล")}" style="width:100%" data-notr>
      <div class="row gap" style="margin-top:8px"><button class="primary" id="ret-ok">${Z("确认退货", "ยืนยันคืนของ")}</button><button data-pclose>${Z("取消", "ยกเลิก")}</button></div>`);
    p.el.querySelector("#ret-ok").onclick = (e) => busy(e.target, async () => {
      const qtys = {}; p.el.querySelectorAll("[data-ret]").forEach((x) => { if (+x.value > 0) qtys[x.dataset.ret] = x.value; });
      await api(`/api/inv/po/${po.id}/return`, { json: { qtys, note: p.el.querySelector("#ret-note").value } });
      p.close(); toast(Z("已退货", "คืนของแล้ว")); await K.render(); await view(po.id);
    });
  }

  // ---------------- 物品采购资料：供应商、链接、价格历史、比价 ----------------
  async function itemDialog(id) {
    await K.ensureMeta();
    const r = await api(`/api/inv/pur/items/${id}/links`);
    const it = r.item, fil = it.category === "filament";
    const pr = (x) => (x.price == null ? "—" : fil ? `${money(x.price * (x.net_g || 1000), x.currency)}${Z("/卷", "/ม้วน")}` : money(x.price, x.currency, 4));
    const hist = r.history || [];
    const h = hist.filter((x) => x.landed).slice().reverse();
    const p = pop(`<div class="row between"><h3>🛒 <span data-notr>${esc(itName(it))}</span> <span class="small muted mono" data-notr>${esc(it.code)}</span></h3><button class="mini" data-pclose>✕</button></div>
      <p class="small muted">${Z("首选供应商用来生成采购单、算到货天数；补货建议和采购单里的单价按这里的写。到货后自动更新最近单价。", "ผู้ขายหลักใช้สร้างใบสั่งซื้อและคิดวันรอของ ราคาในคำแนะนำและใบสั่งซื้อใช้จากที่นี่ รับของแล้วอัปเดตราคาล่าสุดอัตโนมัติ")}</p>
      <div class="pur-scroll"><table class="grid small"><thead><tr><th>${Z("首选", "หลัก")}</th><th>${Z("供应商", "ผู้ขาย")}</th><th>${Z("购买链接", "ลิงก์ซื้อ")}</th>${hasMoney() ? `<th>${Z("单价", "ราคา")}</th><th>${Z("到手价", "ถึงมือ")}</th>` : ""}
        <th>${Z("起订量", "ขั้นต่ำ")}</th><th>${Z("包装数", "ต่อแพ็ก")}</th><th>${Z("到货天数", "วันรอของ")}</th><th></th></tr></thead><tbody>
      ${r.links.map((x) => `<tr class="${x.cheapest ? "pur-best" : ""}"><td><input type="radio" name="pref" data-pref="${x.supplier_id}" ${x.preferred ? "checked" : ""} ${can("inv.in") ? "" : "disabled"}></td>
        <td data-notr><b>${esc((x.supplier || {}).name || "")}</b>${x.cheapest ? ` <span class="ok small">${Z("最便宜", "ถูกสุด")}</span>` : ""}</td>
        <td class="nowrap">${(x.urls || []).map((u, i) => `<a class="btn mini" href="${esc(u)}" target="_blank" rel="noopener" data-notr>🛒 ${esc(platLab(x.platforms[i]) || Z("链接", "ลิงก์"))}</a>`).join(" ") || "—"}</td>
        ${hasMoney() ? `<td class="nowrap">${pr(x)}</td><td class="nowrap">${x.compare ? thb(fil ? x.compare * (x.net_g || 1000) : x.compare, 2) + (fil ? Z("/卷", "/ม้วน") : "") : "—"}</td>` : ""}
        <td>${x.moq ?? ""}</td><td>${x.pack_qty ?? ""}</td><td>${x.lead ?? ""}</td>
        <td class="nowrap">${can("inv.in") ? `<button class="mini" data-le="${x.id}">${Z("修改", "แก้ไข")}</button><button class="mini danger" data-ld="${x.id}">✕</button>` : ""}</td></tr>`).join("") ||
        `<tr><td colspan="9" class="muted">${Z("还没有供应商。加一个，以后补货建议、开采购单就知道去哪买。", "ยังไม่มีผู้ขาย เพิ่มไว้ คำแนะนำและใบสั่งซื้อจะรู้ว่าซื้อที่ไหน")}</td></tr>`}</tbody></table></div>
      ${can("inv.in") ? `<button class="mini primary" id="il-add">＋ ${Z("加供应商 / 链接", "เพิ่มผู้ขาย / ลิงก์")}</button>` : ""}
      ${hasMoney() && hist.length ? `<h4>${Z("价格历史（到手单价）", "ประวัติราคา (ต้นทุนถึงมือ)")}</h4>${h.length > 1 ? `<div class="pur-hspark">${UX.spark(h.map((x) => x.landed), { h: 40 })}</div>` : ""}
        <table class="grid small"><tbody>${hist.slice(0, 12).map((x) => `<tr><td class="nowrap">${esc(x.day || "")}</td><td data-notr>${esc(x.supplier_name || "")}</td>
          <td class="nowrap">${money(fil ? x.unit_price * 1000 : x.unit_price, x.currency, 4)}${fil ? "/kg" : ""}</td><td class="nowrap">${x.landed ? thb(fil ? x.landed * 1000 : x.landed, 2) + (fil ? "/kg" : "") : ""}</td>
          <td class="small muted" data-notr>${esc(x.po_no || (x.source === "manual" ? Z("手动", "กรอกเอง") : ""))}</td></tr>`).join("")}</tbody></table>` : ""}`, "wide");
    const again = async () => { p.close(); await itemDialog(id); ITEMS = null; };
    const ab = p.el.querySelector("#il-add"); if (ab) ab.onclick = () => linkForm(it, null, again);
    p.el.addEventListener("click", async (e) => {
      const le = e.target.closest("[data-le]"); if (le) return linkForm(it, r.links.find((x) => x.id === +le.dataset.le), again);
      const ld = e.target.closest("[data-ld]");
      if (ld && confirm(Z("删掉这个供应商的记录？", "ลบข้อมูลผู้ขายนี้?"))) { await api(`/api/inv/pur/links/${ld.dataset.ld}/delete`, { json: {} }); again(); }
    });
    p.el.addEventListener("change", async (e) => {
      const pf = e.target.closest("[data-pref]");
      if (pf) { await api(`/api/inv/pur/items/${id}/preferred`, { json: { supplier_id: pf.dataset.pref } }); toast(Z("已设成首选", "ตั้งเป็นผู้ขายหลักแล้ว")); again(); }
    });
  }
  function linkForm(it, x, done) {
    x = x || {};
    const fil = it.category === "filament";
    const p = pop(`<h3>${x.id ? Z("修改", "แก้ไข") : Z("加供应商", "เพิ่มผู้ขาย")} · <span data-notr>${esc(itName(it))}</span></h3>
      <div class="form3"><label class="pur-supl">${Z("供应商", "ผู้ขาย")}<span class="row gap"><select id="lf-sup" data-notr>${supOptions(x.supplier_id)}</select>${supButtons()}</span></label>
        <label>${Z("货币", "สกุลเงิน")}<select id="lf-cur"><option value="">${Z("跟供应商一样", "ตามผู้ขาย")}</option><option value="CNY" ${x.currency === "CNY" ? "selected" : ""}>¥</option><option value="THB" ${x.currency === "THB" ? "selected" : ""}>฿</option></select></label>
        <label>${fil ? Z("每卷价格", "ราคาต่อม้วน") : Z("单价", "ราคาต่อหน่วย")}<input id="lf-price" type="number" step="any" min="0" value="${x.price != null ? +(fil ? x.price * (x.net_g || 1000) : x.price).toFixed(4) : ""}"></label>
        ${fil ? `<label>${Z("每卷克数", "กรัมต่อม้วน")}<input id="lf-net" type="number" value="${x.net_g || 1000}"></label>` : ""}
        <label>${fil ? Z("起订量（卷）", "ขั้นต่ำ (ม้วน)") : Z("起订量", "ขั้นต่ำ")}<input id="lf-moq" type="number" step="any" min="0" value="${x.moq ?? ""}"></label>
        <label>${fil ? Z("一箱几卷", "ม้วนต่อกล่อง") : Z("包装数（一包几个）", "จำนวนต่อแพ็ก")}<input id="lf-pack" type="number" step="any" min="0" value="${x.pack_qty ?? ""}"></label>
        <label>${Z("到货天数", "วันรอของ")}<input id="lf-lead" type="number" step="any" min="0" value="${x.lead_days ?? ""}" placeholder="${Z("空 = 用供应商的", "ว่าง = ใช้ของผู้ขาย")}"></label>
        <label class="pur-wide">${Z("购买链接（一行一个：1688 / 淘宝 / 拼多多 / Shopee / Lazada）", "ลิงก์ซื้อ (บรรทัดละลิงก์: 1688 / Taobao / Pinduoduo / Shopee / Lazada)")}<textarea id="lf-urls" rows="2" data-notr>${esc((x.urls || []).join("\n"))}</textarea></label>
        <label>${Z("备注", "หมายเหตุ")}<input id="lf-note" value="${esc(x.note || "")}" data-notr></label>
        <label class="pur-chk"><span><input type="checkbox" id="lf-pref" ${x.preferred || !x.id ? "checked" : ""}> ${Z("设成首选", "ตั้งเป็นผู้ขายหลัก")}</span></label></div>
      <div class="row gap"><button class="primary" id="lf-ok">${Z("保存", "บันทึก")}</button><button data-pclose>${Z("取消", "ยกเลิก")}</button></div>`, "wide");
    bindSupButtons(p.el, p.el.querySelector("#lf-sup"));
    p.el.querySelector("#lf-ok").onclick = (e) => busy(e.target, async () => {
      const g = (s) => (p.el.querySelector(s) || {}).value;
      const d = { id: x.id, item_id: it.id, supplier_id: g("#lf-sup"), currency: g("#lf-cur"), moq: g("#lf-moq"), pack_qty: g("#lf-pack"), lead_days: g("#lf-lead"),
        urls: g("#lf-urls"), note: g("#lf-note"), preferred: p.el.querySelector("#lf-pref").checked };
      if (fil) { d.net_g = g("#lf-net"); d.price_roll = g("#lf-price"); } else d.price = g("#lf-price");
      await api("/api/inv/pur/links", { json: d });
      p.close(); toast(Z("已保存", "บันทึกแล้ว")); if (done) done();
    });
  }

  // ---------------- AI 识别订单开单 ----------------
  function quick() {
    const m = MODAL.open(`<h3>🤖 ${Z("识别订单开单", "อ่านออเดอร์เปิดใบสั่งซื้อ")}</h3>
      <p class="small muted">${Z("把 1688 / 淘宝 / 拼多多 / Shopee / Lazada 的订单详情复制进来，或者上传订单截图。AI 读出供应商、商品、数量、单价、运费、订单号 / 物流单号，你确认后变成采购单草稿。",
        "คัดลอกรายละเอียดออเดอร์จาก 1688 / Taobao / Pinduoduo / Shopee / Lazada มาวาง หรืออัปโหลดภาพหน้าจอ AI จะอ่านผู้ขาย สินค้า จำนวน ราคา ค่าส่ง เลขออเดอร์ / เลขพัสดุ ตรวจแล้วเป็นใบสั่งซื้อร่าง")}</p>
      <textarea id="qk-text" rows="7" style="width:100%" placeholder="${Z("粘贴订单文字…", "วางข้อความออเดอร์…")}" data-notr></textarea>
      <div class="row gap wrap" style="margin-top:6px"><label class="btn">📷 ${Z("上传截图", "อัปโหลดภาพ")}<input type="file" id="qk-img" accept="image/*" hidden></label><span id="qk-fn" class="small muted" data-notr></span>
        <button class="primary" id="qk-go">${Z("识别", "อ่าน")}</button><button data-mclose>${Z("取消", "ยกเลิก")}</button></div><div id="qk-draft"></div>`);
    m.classList.add("wide");
    const img = m.querySelector("#qk-img");
    img.onchange = () => { m.querySelector("#qk-fn").textContent = img.files[0] ? img.files[0].name : ""; };
    m.addEventListener("paste", (e) => {
      const f = [...(e.clipboardData || {}).files || []].find((x) => x.type.startsWith("image/"));
      if (f) { const dt = new DataTransfer(); dt.items.add(f); img.files = dt.files; m.querySelector("#qk-fn").textContent = f.name || "📋"; }
    });
    m.querySelector("#qk-go").onclick = (e) => busy(e.target, async () => {
      const fd = new FormData(); fd.append("text", m.querySelector("#qk-text").value); if (img.files[0]) fd.append("image", img.files[0]);
      const r = await api("/api/inv/pur/quick/parse", { method: "POST", body: fd });
      await draftForm(m.querySelector("#qk-draft"), r.draft);
    });
  }
  async function draftForm(box, d) {
    const its = await items(true);
    const catOpts = (v) => ["filament", "part", "pack", "tool", "other"].map((k) => `<option value="${k}" ${k === v ? "selected" : ""}>${CAT()[k]}</option>`).join("");
    const itemOpts = (l) => `<option value="">${Z("＋ 新建物品", "＋ สร้างรายการใหม่")}</option>` +
      (l.candidates.length ? `<optgroup label="${Z("最像的", "ใกล้เคียงที่สุด")}">${l.candidates.map((c) => `<option value="${c.id}" ${c.id === l.item_id ? "selected" : ""}>${esc(c.code)} · ${esc(itName(c))} (${Math.round(c.score * 100)}%)</option>`).join("")}</optgroup>` : "") +
      `<optgroup label="${Z("全部物品", "ทุกรายการ")}">${its.map((it) => `<option value="${it.id}" ${it.id === l.item_id && !l.candidates.some((c) => c.id === it.id) ? "selected" : ""}>${esc(it.code)} · ${esc(itName(it))}</option>`).join("")}</optgroup>`;
    const cs = d.currency === "CNY" ? "¥" : "฿";
    box.innerHTML = `<hr><h4>${Z("确认采购单草稿", "ตรวจใบสั่งซื้อร่าง")}</h4>
      <div class="form4"><label class="pur-supl">${Z("供应商", "ผู้ขาย")}<span class="row gap"><select id="qd-sup" data-notr>${supOptions(d.supplier_id)}</select>${supButtons()}</span>
          ${!d.supplier_id && d.supplier_name ? `<span class="small">${Z("没找到，新建：", "ไม่พบ สร้างใหม่:")} <input id="qd-sname" value="${esc(d.supplier_name)}" data-notr style="width:140px"></span>` : ""}</label>
        <label>${Z("货币", "สกุลเงิน")}<select id="qd-cur"><option value="CNY" ${d.currency === "CNY" ? "selected" : ""}>¥</option><option value="THB" ${d.currency !== "CNY" ? "selected" : ""}>฿</option></select></label>
        <label>${Z("汇率", "อัตรา")}<input id="qd-fx" type="number" step="any" value="${d.fx_rate}"></label>
        <label>${Z("运费", "ค่าส่ง")} (${cs})<input id="qd-ship" type="number" step="any" value="${d.ship_fee || 0}"></label>
        <label>${Z("平台订单号", "เลขออเดอร์")}<input id="qd-ref" value="${esc(d.order_ref)}" data-notr></label>
        <label>${Z("物流公司", "บริษัทขนส่ง")}<input id="qd-car" value="${esc(d.carrier)}" data-notr></label><label>${Z("物流单号", "เลขพัสดุ")}<input id="qd-trk" value="${esc(d.tracking)}" data-notr></label></div>
      <div class="pur-scroll"><table class="grid small" id="qd-lines"><thead><tr><th>${Z("订单上的商品", "สินค้าในออเดอร์")}</th><th>${Z("对应的库存物品", "รายการในสต็อก")}</th><th>${Z("数量", "จำนวน")}</th><th>${Z("单价", "ราคา")} (${cs})</th><th>${Z("不要", "ไม่เอา")}</th></tr></thead><tbody>
      ${d.lines.map((l, i) => `<tr data-qi="${i}"><td data-notr><b>${esc(l.name)}</b><div class="small muted">${esc(l.spec || "")}</div></td>
        <td><select data-q="item" data-notr class="pur-item">${itemOpts(l)}</select>
          <div class="qd-new ${l.item_id ? "hidden" : ""} row gap wrap small"><input data-q="nname" value="${esc((l.new_item || {}).name_zh || l.name)}" data-notr style="width:180px"><select data-q="ncat">${catOpts((l.new_item || {}).category)}</select></div></td>
        <td class="nowrap"><input data-q="qty" type="number" step="any" value="${l.qty}" class="pur-num"> <span class="muted small qd-u"></span></td>
        <td><input data-q="price" type="number" step="any" value="${l.unit_price ?? ""}" class="pur-num"></td><td><input type="checkbox" data-q="skip"></td></tr>`).join("")}</tbody></table></div>
      <p class="small muted">${Z("耗材的数量是卷数，单价是每卷的价格。", "ฟิลาเมนต์: จำนวนเป็นม้วน ราคาต่อม้วน")}</p>
      <button class="primary" id="qd-ok">${Z("生成采购单草稿", "สร้างใบสั่งซื้อร่าง")}</button>`;
    if (window.I18N && I18N.translate) I18N.translate(box);
    bindSupButtons(box, box.querySelector("#qd-sup"));
    const syncRow = (tr) => {
      const v = tr.querySelector('[data-q="item"]').value, it = its.find((x) => x.id === +v);
      tr.querySelector(".qd-new").classList.toggle("hidden", !!v);
      tr.querySelector(".qd-u").textContent = it ? (it.category === "filament" ? Z("卷", "ม้วน") : uLab(it.unit)) : "";
    };
    box.querySelectorAll("[data-qi]").forEach(syncRow);
    box.addEventListener("change", (e) => { const tr = e.target.closest("[data-qi]"); if (tr) syncRow(tr); });
    box.querySelector("#qd-ok").onclick = (e) => busy(e.target, async () => {
      const lines = [...box.querySelectorAll("[data-qi]")].map((tr) => {
        const l = d.lines[+tr.dataset.qi], g = (k) => tr.querySelector(`[data-q="${k}"]`);
        return { name: l.name, item_id: g("item").value ? +g("item").value : null, qty: g("qty").value, unit_price: g("price").value, net_g: l.net_g,
          skip: g("skip").checked, new_item: { name_zh: g("nname").value, category: g("ncat").value, unit: g("ncat").value === "filament" ? "g" : "个" } };
      });
      const sn = box.querySelector("#qd-sname");
      const body = { supplier_id: box.querySelector("#qd-sup").value || null, supplier_name: sn ? sn.value : "", platform: d.platform, currency: box.querySelector("#qd-cur").value,
        fx_rate: box.querySelector("#qd-fx").value, ship_fee: box.querySelector("#qd-ship").value, order_ref: box.querySelector("#qd-ref").value,
        carrier: box.querySelector("#qd-car").value, tracking: box.querySelector("#qd-trk").value, lines };
      const r = await api("/api/inv/pur/quick/create", { json: body });
      toast(Z("已生成采购单草稿", "สร้างใบสั่งซื้อร่างแล้ว"));
      MODAL.close(); K.setTab("po"); K.PO_FILTER.status = "draft"; await K.render(); await view(r.po.id);
    });
  }

  window.PURPO = { renderList, form, view, manageSuppliers, itemDialog, quick };
})();
