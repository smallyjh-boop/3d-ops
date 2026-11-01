"use strict";
// 采购（v2.51 按 BigSeller 的思路重做）：一个页面三个页签 —— 补货建议 · 采购单 · 到货入库。
// 顶部数字卡片（在途金额、还没付清、本月到货、本月付款）→ 页签 → 每个页签：小图 / 筛选 → 明细表。说明都收在「?」里。
// 这个文件：页面框架、补货建议、到货入库、采购分析；采购单、供应商、物品采购资料、AI 识别订单在 po.js。
// 界面文字用 Z(中文, 泰文) 直接写两种语言；物品名、供应商名、单号这些原始数据加 data-notr。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const num = (v, d = 2) => (v == null || v === "" || isNaN(+v) ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const thb = (v, d = 0) => (v == null || v === "" ? "—" : (v < 0 ? "-฿" : "฿") + Math.abs(+v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const cny = (v, d = 2) => (v == null || v === "" ? "—" : "¥" + (+v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const money = (v, cur, d = 2) => (cur === "CNY" ? cny(v, d) : thb(v, d));
  const itName = (x) => ((TH() && x && x.name_th ? x.name_th : x && x.name_zh) || "");
  const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const daysTo = (s) => { if (!s) return null; const a = new Date(s + "T00:00:00"), b = new Date(ymd(new Date()) + "T00:00:00"); return Math.round((a - b) / 86400000); };
  const ST = () => ({ draft: Z("草稿", "ร่าง"), ordered: Z("已下单·在途", "สั่งแล้ว·กำลังส่ง"), partial: Z("部分到货", "ถึงบางส่วน"),
    received: Z("已入库", "รับเข้าคลังแล้ว"), done: Z("完成", "เสร็จสิ้น"), cancelled: Z("已取消", "ยกเลิกแล้ว"), returned: Z("已退货", "คืนของแล้ว") });
  const ST_TONE = { draft: "", ordered: "info", partial: "warn", received: "ok", done: "ok", cancelled: "", returned: "" };
  const CAT = () => ({ filament: Z("耗材", "ฟิลาเมนต์"), part: Z("备件", "อะไหล่"), pack: Z("包材", "วัสดุแพ็ก"), tool: Z("工具", "เครื่องมือ"),
    other: Z("其他", "อื่นๆ"), goods: Z("成品", "สินค้าสำเร็จรูป") });
  const uLab = (u) => (TH() ? ({ "个": "ชิ้น", "卷": "ม้วน", "张": "แผ่น", "件": "ชิ้น", "米": "เมตร", "瓶": "ขวด", "盒": "กล่อง", "套": "ชุด", "包": "ห่อ", "根": "เส้น", "支": "แท่ง", "把": "อัน" }[u] || u) : u) || "";
  const qtyText = (q, it) => (it && it.category === "filament" ? `${num((+q || 0) / 1000, 2)} kg` : `${num(q, 2)} ${uLab(it && it.unit)}`);

  let TAB = "suggest", META = null, SUG = null, SUG_ALL = false, SUG_EDIT = {};
  try { TAB = localStorage.getItem("pur_tab") || "suggest"; } catch { /* 忽略 */ }
  const root = () => document.getElementById("pur-root");
  const can = (k) => !!(META && META.perms && META.perms[k]);
  const hasMoney = () => !!(META && META.money);

  // ---------------- 小浮层（弹窗上面再开一个：新供应商、管理供应商、物品采购资料）----------------
  function pop(html, cls = "") {
    const el = document.createElement("div");
    el.className = "pur-pop";
    el.innerHTML = `<div class="pur-pop-in ${cls}">${html}</div>`;
    document.body.appendChild(el);
    const close = () => el.remove();
    el.addEventListener("click", (e) => { if (e.target === el || e.target.closest("[data-pclose]")) close(); });
    if (window.I18N && I18N.translate) I18N.translate(el);
    return { el: el.firstElementChild, close };
  }

  async function loadMeta() { META = await api("/api/inv/pur/overview"); return META; }

  // ---------------- 页面框架 ----------------
  const ALIAS = { po_suggest: "suggest", po_recv: "recv", po_suppliers: "po", po_pay: "po" };
  async function show(name) {
    if (ALIAS[name]) {
      TAB = ALIAS[name];
      if (name === "po_pay") PO_FILTER.status = "unpaid";
      const sup = name === "po_suppliers";
      if (typeof showTab === "function") { showTab("purchase"); if (sup) setTimeout(() => window.PURPO && PURPO.manageSuppliers(), 300); return; }
    }
    if (name !== "purchase") return;
    try { await render(); } catch (e) { if (root()) root().innerHTML = `<p class="bad" data-notr>${esc(e.message)}</p>`; }
  }
  const PO_FILTER = { status: "open", supplier: "", q: "", view: "list" };
  try { Object.assign(PO_FILTER, JSON.parse(localStorage.getItem("pur_po_filter") || "{}")); } catch { /* 忽略 */ }

  async function render() {
    if (!root()) return;
    await loadMeta();
    const s = META.summary, n = META.counts;
    const kp = hasMoney() ? [
      { label: Z("在途金额", "มูลค่าระหว่างขนส่ง"), value: thb(s.in_transit), sub: `${n.transit} ${Z("张在途", "ใบกำลังส่ง")}${s.overdue ? ` · ${s.overdue} ${Z("张过期", "ใบเลยกำหนด")}` : ""}`,
        tone: s.overdue ? "warn" : "", go: "pur:transit", help: Z("已下单还没到的货，按汇率折成泰铢、带上分摊的运费 / 税", "ของที่สั่งแล้วยังไม่ถึง คิดเป็นบาทตามอัตราแลกเปลี่ยน รวมค่าส่ง / ภาษีที่เฉลี่ยแล้ว") },
      { label: Z("还没付清", "ยังจ่ายไม่ครบ"), value: thb(s.unpaid), tone: s.unpaid > 0 ? "warn" : "ok", go: "pur:unpaid",
        help: Z("下了单的采购单还欠供应商的钱（结单 / 取消的按到了的货算）", "เงินที่ยังค้างผู้ขาย (ใบที่ปิดหรือยกเลิกคิดตามของที่ถึงจริง)") },
      { label: Z("本月到货", "ของถึงเดือนนี้"), value: thb(s.month_received), sub: s.month, help: Z("这个月到货入库的到手成本", "ต้นทุนถึงมือของที่รับเข้าคลังเดือนนี้") },
      { label: Z("本月付款", "จ่ายเงินเดือนนี้"), value: thb(s.month_paid), sub: s.month, help: Z("这个月付给供应商的钱（自动记到财务）", "เงินที่จ่ายผู้ขายเดือนนี้ (บันทึกในการเงินอัตโนมัติ)") },
    ] : [
      { label: Z("在途", "กำลังส่ง"), value: String(n.transit), sub: s.overdue ? `${s.overdue} ${Z("张过期", "ใบเลยกำหนด")}` : "", tone: s.overdue ? "warn" : "", go: "pur:transit" },
      { label: Z("进行中", "กำลังดำเนินการ"), value: String(s.open) },
    ];
    kp.push({ label: Z("要马上补货", "ต้องเติมด่วน"), value: String(n.suggest_red), sub: `${n.suggest} ${Z("种该补", "รายการควรเติม")}`, tone: n.suggest_red ? "bad" : (n.suggest ? "warn" : "ok"),
      go: "pur:suggest", help: Z("红色 = 现在下单也来不及到货；黄色 = 该下单了", "แดง = สั่งตอนนี้ก็มาไม่ทัน; เหลือง = ควรสั่งแล้ว") });
    if (n.issues) kp.push({ label: Z("到货差异没处理", "ของไม่ตรงยังไม่จัดการ"), value: String(n.issues), tone: "warn", go: "pur:recv" });
    const btns = `${can("inv.in") ? `<button class="primary" data-pur="new">＋ ${Z("新采购单", "ใบสั่งซื้อใหม่")}</button>
        <button data-pur="quick" title="${Z("贴 1688 / 淘宝 / 拼多多 / Shopee / Lazada 的订单文字或截图，AI 读成采购单", "วางข้อความหรือภาพออเดอร์ 1688 / Taobao / Pinduoduo / Shopee / Lazada ให้ AI อ่านเป็นใบสั่งซื้อ")}">🤖 ${Z("识别订单开单", "อ่านออเดอร์เปิดใบ")}</button>` : ""}
      <button data-pur="sup">🏪 ${Z("供应商", "ผู้ขาย")}</button>${hasMoney() ? `<button data-pur="ana">📊 ${Z("采购分析", "วิเคราะห์การจัดซื้อ")}</button>` : ""}
      <button data-pur="reload" title="${Z("刷新", "รีเฟรช")}">↻</button>`;
    root().innerHTML = UX.head(Z("采购", "จัดซื้อ"), btns, Z("补货建议按生产任务、近 30 天用量和订单量算；采购单从草稿到完成；到货入库可以用手机扫码（手机页 /m →「采购到货」）。",
      "คำแนะนำเติมสต็อกคิดจากงานผลิต การใช้ 30 วันล่าสุด และจำนวนออเดอร์; ใบสั่งซื้อตั้งแต่ร่างถึงเสร็จ; รับของเข้าคลังสแกนด้วยมือถือได้ (หน้ามือถือ /m →「รับของจัดซื้อ」)"))
      + UX.kpis(kp)
      + UX.tabs([["suggest", Z("补货建议", "แนะนำเติมสต็อก"), n.suggest || ""], ["po", Z("采购单", "ใบสั่งซื้อ"), s.open || ""],
        ["recv", Z("到货入库", "รับของเข้าคลัง"), (n.transit || "") + (n.issues ? " · ⚠" + n.issues : "")]], TAB, "pur")
      + `<div id="pur-body"></div>`;
    await renderTab();
  }
  async function renderTab() {
    try { localStorage.setItem("pur_tab", TAB); } catch { /* 忽略 */ }
    const box = document.getElementById("pur-body");
    if (!box) return;
    box.innerHTML = `<p class="muted small">${Z("加载中…", "กำลังโหลด…")}</p>`;
    try {
      if (TAB === "suggest") await renderSuggest(box);
      else if (TAB === "recv") await renderRecv(box);
      else if (window.PURPO) await PURPO.renderList(box, PO_FILTER);
    } catch (e) { box.innerHTML = `<p class="bad" data-notr>${esc(e.message)}</p>`; }
  }

  // ---------------- 补货建议 ----------------
  const WHY = () => ({ production: Z("生产任务要用", "งานผลิตต้องใช้"), usage: Z("按近 30 天用量", "ตามการใช้ 30 วัน"), orders: Z("按订单量", "ตามจำนวนออเดอร์"),
    reorder: Z("低于补货线", "ต่ำกว่าจุดสั่งซื้อ"), short: Z("已经不够", "ไม่พอแล้ว") });
  const URG = () => ({ red: Z("来不及", "ไม่ทัน"), yellow: Z("该下单", "ควรสั่ง"), green: Z("不急", "ยังไม่ด่วน") });
  const TONE = { red: "bad", yellow: "warn", green: "ok" };

  async function renderSuggest(box) {
    SUG = await api(`/api/inv/pur/suggest${SUG_ALL ? "?all=1" : ""}`);
    const rows = SUG.rows;
    const red = rows.filter((r) => r.urgency === "red").length, yel = rows.filter((r) => r.urgency === "yellow").length;
    const p = SUG.params;
    const help = Z(`还能用几天 = (库存 + 在途 − 生产任务要用的) ÷ 每天用量。每天用量：耗材 = 近 30 天扣料 ÷ 30；包材再乘订单量变化（现在 ×${SUG.trend}）；其他 = 近 30 天出库 ÷ 30。
建议买 = 每天用量 × (到货天数 + 安全 ${p.safety_days} 天 + 一次买 ${p.cover_days} 天) + 生产要用的 − 库存 − 在途，按起订量、包装数、整卷取整。
红 = 现在下单也来不及（还能用的天数 < 到货天数）；黄 = 该下单了（< 到货天数 + 安全天数，或低于补货线）。天数在 设置 → 库存 → 采购 里改。`,
    `ใช้ได้อีกกี่วัน = (สต็อก + ระหว่างขนส่ง − ที่งานผลิตต้องใช้) ÷ การใช้ต่อวัน การใช้ต่อวัน: ฟิลาเมนต์ = ที่ตัดใน 30 วัน ÷ 30; วัสดุแพ็กคูณการเปลี่ยนแปลงของออเดอร์ (ตอนนี้ ×${SUG.trend}); อื่นๆ = เบิกออก 30 วัน ÷ 30
ควรซื้อ = การใช้ต่อวัน × (วันรอของ + กันเผื่อ ${p.safety_days} วัน + ซื้อครั้งละ ${p.cover_days} วัน) + ที่งานผลิตต้องใช้ − สต็อก − ระหว่างขนส่ง ปัดตามขั้นต่ำ จำนวนต่อแพ็ก และม้วนเต็ม
แดง = สั่งตอนนี้ก็มาไม่ทัน (วันที่ใช้ได้ < วันรอของ); เหลือง = ควรสั่งแล้ว (< วันรอของ + วันกันเผื่อ หรือต่ำกว่าจุดสั่งซื้อ) แก้จำนวนวันที่ ตั้งค่า → สต็อก → จัดซื้อ`);
    const head = `<div class="row between wrap gap pur-bar">
        <div class="row gap wrap"><span class="chips"><span class="chip ${SUG_ALL ? "" : "on"}" data-sg-all="0">${Z("要补的", "ที่ควรเติม")} <b>${SUG_ALL ? "" : rows.length}</b></span>
          <span class="chip ${SUG_ALL ? "on" : ""}" data-sg-all="1">${Z("全部有用量的", "ทุกรายการที่มีการใช้")}</span></span>
          ${UX.dot("bad", `${URG().red} ${red}`)} ${UX.dot("warn", `${URG().yellow} ${yel}`)} ${UX.help(help)}</div>
        ${can("inv.in") && rows.length ? `<div class="row gap"><span class="small muted" id="sg-sum"></span><button class="primary" id="sg-po">${Z("选中的生成采购单（按供应商分开）", "สร้างใบสั่งซื้อจากที่เลือก (แยกตามผู้ขาย)")}</button></div>` : ""}</div>`;
    if (!rows.length) { box.innerHTML = head + UX.empty(Z("现在不用补货。物品有用量（打印扣料、领用、发货扣包材）或设了补货线才会出现在这里。", "ตอนนี้ยังไม่ต้องเติม รายการจะขึ้นเมื่อมีการใช้ (ตัดฟิลาเมนต์ เบิก ตัดวัสดุแพ็ก) หรือมีจุดสั่งซื้อ")); bindSuggest(box); return; }
    const sups = (META.suppliers || []).filter((x) => x.active);
    const tr = (r) => {
      const it = r.item, fil = it.category === "filament", e = SUG_EDIT[it.id] || {};
      const supSel = `<select data-sg-sup="${it.id}" data-notr class="pur-sel"><option value="">${Z("（没设供应商）", "(ยังไม่ได้ตั้งผู้ขาย)")}</option>${sups.map((x) => `<option value="${x.id}" ${+(e.sup ?? r.supplier_id) === x.id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>`;
      const days = r.days == null ? "—" : num(r.days, 1);
      const qtyIn = fil ? `<input type="number" min="0" step="1" data-sg-rolls="${it.id}" value="${e.rolls ?? (r.rolls || 0)}" class="pur-num"> ${Z("卷", "ม้วน")}`
        : `<input type="number" min="0" step="any" data-sg-qty="${it.id}" value="${e.qty ?? r.qty}" class="pur-num"> <span class="muted">${esc(uLab(it.unit))}</span>`;
      const link = r.link && r.link.urls && r.link.urls[0];
      return `<tr class="pur-u-${r.urgency}"><td><input type="checkbox" data-sg="${it.id}" ${r.urgency !== "green" && r.qty > 0 ? "checked" : ""}></td>
        <td><a href="#" data-item-links="${it.id}" data-notr><b>${esc(itName(it))}</b></a><div class="small muted"><span data-notr>${esc(it.code)}</span> · ${esc(CAT()[it.category] || it.category)}</div></td>
        <td>${UX.dot(TONE[r.urgency], URG()[r.urgency])}<div class="small muted">${Z("还能用", "ใช้ได้อีก")} <b>${days}</b> ${Z("天", "วัน")} · ${Z("到货", "รอของ")} ${num(r.lead, 0)} ${Z("天", "วัน")}</div>
          ${r.order_by && r.urgency !== "red" ? `<div class="small muted">${Z("最晚下单", "สั่งภายใน")} ${esc(r.order_by)}</div>` : ""}</td>
        <td class="nowrap">${qtyText(it.qty, it)}${r.transit ? `<div class="small muted">${Z("在途", "กำลังส่ง")} ${qtyText(r.transit, it)}</div>` : ""}${r.pending ? `<div class="small warn">${Z("生产要用", "งานผลิตใช้")} ${qtyText(r.pending, it)}</div>` : ""}</td>
        <td class="nowrap">${r.daily ? qtyText(r.daily, it) + Z("/天", "/วัน") : "—"}<div class="small muted">${r.why.map((w) => WHY()[w] || w).join(" · ")}</div></td>
        <td>${supSel}${r.link && (r.link.moq || r.link.pack_qty) ? `<div class="small muted">${r.link.moq ? `${Z("起订", "ขั้นต่ำ")} ${num(r.link.moq)}` : ""}${r.link.pack_qty ? ` · ${Z("每包", "ต่อแพ็ก")} ${num(r.link.pack_qty)}` : ""}</div>` : ""}</td>
        <td class="nowrap">${qtyIn}</td>
        ${hasMoney() ? `<td class="nowrap">${r.est_cost != null ? thb(r.est_cost) : "—"}${r.unit_price != null ? `<div class="small muted">${money(fil ? r.unit_price * (r.net_g || 1000) : r.unit_price, r.currency)}${fil ? Z("/卷", "/ม้วน") : ""}</div>` : ""}</td>` : ""}
        <td class="nowrap">${link ? `<a class="btn mini" href="${esc(link)}" target="_blank" rel="noopener" title="${Z("打开购买链接", "เปิดลิงก์ซื้อ")}">🛒</a>` : ""}<button class="mini" data-item-links="${it.id}" title="${Z("供应商、链接、价格历史", "ผู้ขาย ลิงก์ ประวัติราคา")}">${Z("资料", "ข้อมูล")}</button></td></tr>`;
    };
    box.innerHTML = head + `<div class="pur-scroll"><table class="grid small pur-sg"><thead><tr><th><input type="checkbox" id="sg-all"></th><th>${Z("物品", "รายการ")}</th><th>${Z("紧急程度", "ความด่วน")}</th>
      <th>${Z("库存", "สต็อก")}</th><th>${Z("每天用量", "ใช้ต่อวัน")}</th><th>${Z("供应商", "ผู้ขาย")}</th><th>${Z("建议买", "ควรซื้อ")}</th>${hasMoney() ? `<th>${Z("预计金额", "ประมาณการ")}</th>` : ""}<th></th></tr></thead>
      <tbody>${rows.map(tr).join("")}</tbody></table></div>`;
    bindSuggest(box);
    sgSum();
  }
  function sgRows() {
    return $$("#pur-body [data-sg]:checked").map((x) => {
      const id = +x.dataset.sg, r = SUG.rows.find((y) => y.item.id === id);
      const sup = ($(`[data-sg-sup="${id}"]`) || {}).value;
      const rolls = $(`[data-sg-rolls="${id}"]`), qty = $(`[data-sg-qty="${id}"]`);
      return { item_id: id, supplier_id: sup || null, rolls: rolls ? rolls.value : undefined, qty: qty ? qty.value : undefined, r };
    });
  }
  function sgSum() {
    const el = document.getElementById("sg-sum");
    if (!el) return;
    const sel = sgRows();
    const sups = new Set(sel.map((x) => x.supplier_id || "-"));
    let t = 0;
    sel.forEach((x) => {
      const r = x.r; if (!r || r.unit_price == null) return;
      const q = x.rolls !== undefined ? (+x.rolls || 0) * (r.net_g || 1000) : (+x.qty || 0);
      t += q * r.unit_price * (r.currency === "CNY" ? (META.fx || 4.5) : 1);
    });
    el.innerHTML = `${Z("选了", "เลือก")} <b>${sel.length}</b> ${Z("种", "รายการ")} → <b>${sups.size}</b> ${Z("张采购单", "ใบสั่งซื้อ")}${hasMoney() && t ? ` · ≈ <b>${thb(t)}</b>` : ""}`;
  }
  function bindSuggest(box) {
    box.querySelectorAll("[data-sg-all]").forEach((c) => c.addEventListener("click", () => { SUG_ALL = c.dataset.sgAll === "1"; renderTab(); }));
    const all = box.querySelector("#sg-all");
    if (all) all.onchange = () => { box.querySelectorAll("[data-sg]").forEach((x) => (x.checked = all.checked)); sgSum(); };
    box.addEventListener("change", (e) => {
      const t = e.target, id = t.dataset.sgSup || t.dataset.sgRolls || t.dataset.sgQty;
      if (id) { const s = (SUG_EDIT[id] = SUG_EDIT[id] || {}); if (t.dataset.sgSup !== undefined) s.sup = t.value; if (t.dataset.sgRolls !== undefined) s.rolls = t.value; if (t.dataset.sgQty !== undefined) s.qty = t.value; }
      sgSum();
    });
    const b = box.querySelector("#sg-po");
    if (b) b.onclick = () => busy(b, async () => {
      const sel = sgRows();
      if (!sel.length) throw new Error(Z("先勾选要买的物品", "เลือกรายการที่จะซื้อก่อน"));
      const r = await api("/api/inv/pur/suggest/po", { json: { rows: sel.map(({ r, ...x }) => x) } });
      SUG_EDIT = {};
      toast(Z(`已生成 ${r.po.length} 张采购单草稿`, `สร้างใบสั่งซื้อร่าง ${r.po.length} ใบ`));
      TAB = "po"; PO_FILTER.status = "draft"; await render();
    });
  }

  // ---------------- 到货入库 ----------------
  async function renderRecv(box) {
    const [t, iss] = await Promise.all([api("/api/inv/pur/transit"), api("/api/inv/pur/issues")]);
    const card = (p) => {
      const d = daysTo(p.expected_date);
      const cd = d == null ? `<span class="muted">${Z("没写预计到货", "ไม่ได้ระบุวันถึง")}</span>` : d < 0 ? `<span class="bad">${Z(`晚了 ${-d} 天`, `ช้า ${-d} วัน`)}</span>`
        : d === 0 ? `<span class="warn">${Z("今天到", "ถึงวันนี้")}</span>` : `<span>${Z(`还有 ${d} 天`, `อีก ${d} วัน`)}</span>`;
      const left = p.lines.filter((l) => (l.qty || 0) - (l.received || 0) > 1e-9);
      return `<div class="pur-rc ${d != null && d < 0 ? "late" : ""}"><div class="row between gap"><b class="mono" data-notr>${esc(p.no)}</b>${UX.dot(ST_TONE[p.status], ST()[p.status])}</div>
        <div class="small"><span data-notr>${esc(p.supplier || "—")}</span> · ${cd}${p.expected_date ? ` <span class="muted">(${esc(p.expected_date)})</span>` : ""}</div>
        ${p.tracking ? `<div class="small muted">${Z("运单", "เลขพัสดุ")} <span class="mono" data-notr>${esc(p.carrier || "")} ${esc(p.tracking)}</span></div>` : ""}
        <div class="small pur-rc-lines" data-notr>${left.slice(0, 3).map((l) => esc(itName(l))).join("、")}${left.length > 3 ? ` +${left.length - 3}` : ""}</div>
        <div class="row gap" style="margin-top:6px">${can("inv.in") ? `<button class="primary mini" data-rcv-po="${p.id}">📥 ${Z("到货入库", "รับของ")}</button>` : ""}<button class="mini" data-po="${p.id}">${Z("详情", "รายละเอียด")}</button></div></div>`;
    };
    box.innerHTML = `<div class="card pur-scan"><div class="row gap wrap"><b>📷 ${Z("扫码到货", "สแกนรับของ")}</b>
        <input id="rc-scan" placeholder="${Z("扫 / 输入 采购单号、物流单号、平台订单号或物品条码，回车", "สแกน / พิมพ์ เลขใบสั่งซื้อ เลขพัสดุ เลขออเดอร์ หรือบาร์โค้ดสินค้า แล้วกด Enter")}" autocomplete="off" data-notr>
        ${UX.help(Z("扫码枪对着这个框扫就行。手机上打开 /m →「采购到货」，可以拿着手机在货架边扫。", "ใช้เครื่องสแกนยิงที่ช่องนี้ได้เลย บนมือถือเปิด /m →「รับของจัดซื้อ」 สแกนข้างชั้นวางได้"))}</div><div id="rc-res" class="small"></div></div>
      ${UX.card({ title: Z("在途的采购单", "ใบสั่งซื้อระหว่างขนส่ง"), right: `<span class="muted small">${t.pos.length}</span>`,
        body: t.pos.length ? `<div class="pur-rcs">${t.pos.map(card).join("")}</div>` : UX.empty(Z("没有在途的采购单", "ไม่มีใบสั่งซื้อระหว่างขนส่ง")) })}
      ${UX.card({ title: Z("到货差异（少发 / 破损 / 发错 / 多发）", "ของไม่ตรง (ส่งขาด / เสียหาย / ส่งผิด / ส่งเกิน)"), tone: iss.issues.length ? "warn" : "",
        help: Z("到货时记下的问题。找供应商补发或退款后点「处理好了」。退款用采购单里的「供应商退款」记。", "ปัญหาที่บันทึกตอนรับของ ติดต่อผู้ขายให้ส่งเพิ่มหรือคืนเงินแล้วกด「จัดการแล้ว」 เงินคืนบันทึกที่「ผู้ขายคืนเงิน」ในใบสั่งซื้อ"),
        body: iss.issues.length ? `<div class="pur-scroll"><table class="grid small"><thead><tr><th>${Z("采购单", "ใบสั่งซื้อ")}</th><th>${Z("物品", "รายการ")}</th><th>${Z("问题", "ปัญหา")}</th><th>${Z("数量", "จำนวน")}</th><th>${Z("备注", "หมายเหตุ")}</th><th></th></tr></thead><tbody>
          ${iss.issues.map((x) => `<tr><td class="mono"><a href="#" data-po="${x.po_id}" data-notr>${esc(x.no)}</a></td><td data-notr>${esc(itName(x))}</td><td>${esc(ISS()[x.kind] || x.kind)}</td>
            <td>${qtyText(x.qty, { category: x.unit === "g" ? "filament" : "", unit: x.unit })}</td><td class="muted" data-notr>${esc(x.note || "")}</td>
            <td>${can("inv.in") ? `<button class="mini" data-iss-ok="${x.id}">${Z("处理好了", "จัดการแล้ว")}</button>` : ""}</td></tr>`).join("")}</tbody></table></div>` : UX.empty(Z("没有没处理的差异", "ไม่มีรายการค้าง")) })}`;
    const inp = box.querySelector("#rc-scan");
    inp.focus();
    inp.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter" || !inp.value.trim()) return;
      const code = inp.value.trim(); inp.value = "";
      const res = box.querySelector("#rc-res");
      try {
        const r = await api(`/api/inv/pur/scan?code=${encodeURIComponent(code)}`);
        if (r.type === "po") { res.innerHTML = ""; return receiveDialog(r.po.id); }
        if (r.type === "item") {
          if (r.pos.length === 1) { res.innerHTML = ""; return receiveDialog(r.pos[0].id); }
          res.innerHTML = r.pos.length ? `<span data-notr>${esc(itName(r.item))}</span> ${Z("在这些采购单里：", "อยู่ในใบสั่งซื้อเหล่านี้:")} ${r.pos.map((p) => `<button class="mini" data-rcv-po="${p.id}" data-notr>${esc(p.no)}</button>`).join(" ")}`
            : `<span class="warn"><span data-notr>${esc(itName(r.item))}</span> ${Z("没有在途的采购单", "ไม่มีใบสั่งซื้อที่กำลังส่ง")}</span>`;
          return;
        }
        res.innerHTML = `<span class="bad">${Z("不认识这个码", "ไม่รู้จักโค้ดนี้")}：<span data-notr>${esc(code)}</span></span>`;
      } catch (er) { res.innerHTML = `<span class="bad" data-notr>${esc(er.message)}</span>`; }
    });
  }
  const ISS = () => ({ short: Z("少发", "ส่งขาด"), damaged: Z("破损", "เสียหาย"), wrong: Z("发错", "ส่งผิด"), extra: Z("多发", "ส่งเกิน") });

  let LOCS = null;
  async function receiveDialog(id) {
    const po = (await api(`/api/inv/po/${id}`)).po;
    if (!["ordered", "partial"].includes(po.status)) return toast(Z("这张采购单不在途（要先下单）", "ใบสั่งซื้อนี้ไม่ได้อยู่ระหว่างขนส่ง (ต้องสั่งก่อน)"), true);
    if (LOCS === null) { try { LOCS = (await api("/api/inv/locations")).locations || []; } catch { LOCS = []; } }
    const lines = po.lines.filter((l) => (l.qty || 0) - (l.received || 0) > 1e-9);
    const row = (l) => {
      const left = (l.qty || 0) - (l.received || 0), roll = !!l.rolls, leftShow = roll ? left / (l.net_g || 1000) : left;
      return `<tr data-rl="${l.id}"><td data-notr><b>${esc(itName(l))}</b><div class="small muted">${esc(l.code)}</div></td>
        <td class="nowrap">${num(leftShow)} ${roll ? Z("卷", "ม้วน") : esc(uLab(l.unit))}</td>
        <td class="nowrap"><input type="number" min="0" step="${roll ? 1 : "any"}" max="${leftShow}" value="${num(leftShow, 3).replace(/,/g, "")}" data-r="qty" class="pur-num"> ${roll ? Z("卷", "ม้วน") : ""}</td>
        <td><div class="pur-iss"><select data-r="kind"><option value="">—</option>${Object.entries(ISS()).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>
          <input type="number" min="0" step="any" data-r="iq" class="pur-num" placeholder="${Z("数量", "จำนวน")}"><input data-r="note" placeholder="${Z("说明", "หมายเหตุ")}" class="pur-note" data-notr></div></td>
        <td><input data-r="loc" list="pur-locs" value="${esc(l.location || "")}" placeholder="${Z("货位", "ตำแหน่ง")}" class="pur-loc" data-notr></td></tr>`;
    };
    const m = MODAL.open(`<h3>📥 ${Z("到货入库", "รับของเข้าคลัง")} <span class="mono" data-notr>${esc(po.no)}</span></h3>
      <p class="small"><span data-notr>${esc((po.supplier || {}).name || "")}</span>${po.tracking ? ` · ${Z("运单", "เลขพัสดุ")} <span class="mono" data-notr>${esc(po.tracking)}</span>` : ""}</p>
      <div class="pur-scroll"><table class="grid small"><thead><tr><th>${Z("物品", "รายการ")}</th><th>${Z("还没到", "ยังไม่ถึง")}</th><th>${Z("这次到了", "ถึงรอบนี้")}</th>
        <th>${Z("差异（少发 / 破损…）", "ไม่ตรง (ขาด / เสีย…)")} ${UX.help(Z("少发、破损的不进库存，记下来找供应商；那一行还会留着「没到」，确定不会再来就点「结单」。", "ที่ขาดหรือเสียไม่เข้าสต็อก บันทึกไว้ติดตามผู้ขาย แถวนั้นจะยังค้าง「ยังไม่ถึง」 ถ้าไม่มาแล้วกด「ปิดใบ」"))}</th>
        <th>${Z("放到货位", "วางตำแหน่ง")}</th></tr></thead><tbody>${lines.map(row).join("")}</tbody></table></div>
      <datalist id="pur-locs" data-notr>${LOCS.map((l) => `<option value="${esc(l.code)}">${l.items ? "" : (TH() ? "ว่าง" : "空")}</option>`).join("")}</datalist>
      <label class="small pur-chk"><input type="checkbox" id="rc-print" checked> ${Z("入库后打印物品标签", "พิมพ์ป้ายสินค้าหลังรับเข้า")}</label>
      <div class="row gap" style="margin-top:8px"><button class="primary" id="rc-ok">✅ ${Z("确认入库", "ยืนยันรับเข้า")}</button><button data-mclose>${Z("取消", "ยกเลิก")}</button></div>`);
    m.classList.add("wide");
    m.querySelector("#rc-ok").onclick = (e) => busy(e.target, async () => {
      const qtys = {}, issues = [], locations = {};
      m.querySelectorAll("[data-rl]").forEach((tr) => {
        const lid = tr.dataset.rl, l = po.lines.find((x) => String(x.id) === lid);
        const g = (k) => tr.querySelector(`[data-r="${k}"]`).value.trim();
        if (g("qty") !== "" && +g("qty") > 0) qtys[lid] = g("qty");
        if (g("kind")) issues.push({ line_id: +lid, kind: g("kind"), qty: g("iq") || 0, note: g("note") });
        if (g("loc") && g("loc") !== (l.location || "")) locations[l.item_id] = g("loc");
      });
      const r = await api("/api/inv/pur/receive", { json: { po_id: po.id, qtys, issues, locations } });
      (r.warnings || []).forEach((w) => toast(w, true));
      toast(Z("已入库", "รับเข้าคลังแล้ว"));
      if (m.querySelector("#rc-print").checked && Object.keys(qtys).length) {
        const ls = Object.entries(qtys).map(([k, v]) => `${k}:${Math.ceil(+v)}`).join(",");
        window.open(`/print/pur-labels?po=${encodeURIComponent(po.no)}&lines=${ls}${TH() ? "&lang=th" : ""}`, "_blank");
      }
      MODAL.close(); render();
    });
  }

  // ---------------- 采购分析（弹窗）----------------
  async function analytics() {
    const r = await api("/api/inv/pur/analytics");
    const mo = r.months, last = mo[mo.length - 1] || {};
    const fk = r.filament_kg.filter((x) => x.thb_kg);
    const kp = UX.kpis([
      { label: Z("近 12 个月采购", "จัดซื้อ 12 เดือน"), value: thb(r.total_12m), help: Z("到货入库的到手成本（含分摊的运费 / 税）", "ต้นทุนถึงมือของที่รับเข้าคลัง (รวมค่าส่ง / ภาษีที่เฉลี่ย)") },
      { label: Z("本月采购", "จัดซื้อเดือนนี้"), value: thb(last.spend), sub: last.month, spark: mo.map((x) => x.spend) },
      { label: Z("耗材每公斤（最近）", "ฟิลาเมนต์ต่อ kg (ล่าสุด)"), value: fk.length ? thb(fk[fk.length - 1].thb_kg) : "—", spark: fk.map((x) => x.thb_kg),
        sub: `${Z("定价用", "ใช้คิดราคา")} ¥${num(r.filament_cny_kg)}/kg`, help: Z("每个月到货的耗材平均到手价（泰铢 / 公斤）；定价用的耗材价格在 设置 → 成本与定价", "ราคาถึงมือเฉลี่ยของฟิลาเมนต์ที่รับเข้าแต่ละเดือน (บาท / kg) ราคาฟิลาเมนต์ที่ใช้คิดราคาอยู่ที่ ตั้งค่า → ต้นทุนและราคา") },
    ]);
    const cols = UX.columns(mo.map((x) => ({ label: x.month, value: x.spend, text: thb(x.spend) })), { h: 110, from: mo[0].month, to: last.month });
    const payc = UX.columns(mo.map((x) => ({ label: x.month, value: x.paid, text: thb(x.paid), tone: "ok" })), { h: 110, from: mo[0].month, to: last.month });
    const cat = UX.bars(r.by_category.map((x) => ({ label: TH() ? x.th : x.zh, value: x.spend, text: thb(x.spend) })));
    const sup = UX.bars(r.by_supplier.map((x) => ({ label: x.name || Z("（没有采购单的入库）", "(รับเข้าโดยไม่มีใบสั่งซื้อ)"), value: x.spend, text: thb(x.spend), raw: !!x.name })));
    const filc = UX.columns(r.filament_kg.map((x) => ({ label: x.month, value: x.thb_kg || 0, text: x.thb_kg ? thb(x.thb_kg) + "/kg" : "—", tone: "" })), { h: 90, from: mo[0].month, to: last.month });
    const mat = r.filament_by_material.length ? `<div class="small">${r.filament_by_material.map((x) => `<span data-notr>${esc(x.material)}</span> ${thb(x.thb_kg)}/kg <span class="muted">(${num(x.kg, 1)} kg)</span>`).join(" · ")}</div>` : "";
    const ch = r.cheapest.length ? `<div class="pur-scroll"><table class="grid small"><thead><tr><th>${Z("物品", "รายการ")}</th><th>${Z("最便宜", "ถูกที่สุด")}</th><th>${Z("各供应商到手单价", "ราคาถึงมือแต่ละผู้ขาย")}</th><th>${Z("首选贵了", "ผู้ขายหลักแพงกว่า")}</th></tr></thead><tbody>
      ${r.cheapest.map((x) => { const pk = (v) => (x.category === "filament" ? thb(v * 1000, 1) + "/kg" : thb(v, 2)); return `<tr><td data-notr><a href="#" data-item-links="${x.item_id}">${esc(itName(x))}</a></td><td data-notr><b>${esc(x.best.name)}</b> ${pk(x.best.landed)}</td>
        <td class="small" data-notr>${x.options.map((o) => `${esc(o.name)} ${pk(o.landed)}${o.preferred ? " ★" : ""}`).join(" · ")}</td>
        <td>${x.saving_pct ? `<span class="warn">+${num(x.saving_pct, 1)}%</span>` : `<span class="ok">✓</span>`}</td></tr>`; }).join("")}</tbody></table></div>`
      : UX.empty(Z("物品有两个以上供应商（有价格）才能比价：在物品的「⋯ 采购资料」里加供应商", "ต้องมีผู้ขาย 2 รายขึ้นไป (มีราคา) ถึงจะเทียบได้: เพิ่มที่「⋯ ข้อมูลจัดซื้อ」ของรายการ"));
    const costs = r.costs.length ? `<div class="pur-costs">${r.costs.slice(0, 12).map((x) => `<div class="pur-cost">
      <div><b>${x.kind === "filament" ? Z("耗材（人民币/公斤）", "ฟิลาเมนต์ (หยวน/kg)") : `<span data-notr>${esc(TH() && x.name_th ? x.name_th : x.label)}</span>`}</b>
        <span class="small muted">${fmtTime(x.ts).slice(0, 10)}</span></div>
      <div class="small">${x.kind === "filament" ? `¥${num(x.old)} → ¥${num(x.new)}` : `${thb(x.old, 2)} → ${thb(x.new, 2)}`} <b class="${x.pct > 0 ? "bad" : "ok"}">${x.pct > 0 ? "+" : ""}${num(x.pct, 1)}%</b>
      ${x.applied ? ` · <span class="ok">${Z("已更新定价", "อัปเดตราคาแล้ว")}</span>` : ""}</div>
      <div>${x.state === "open" && META.owner && x.kind === "filament" && !x.applied ? `<button class="mini primary" data-cost="${x.id}" data-act="apply">${Z("写进定价", "ใช้คิดราคา")}</button>` : ""}
        ${x.state === "open" && META.owner ? `<button class="mini" data-cost="${x.id}" data-act="dismiss">${Z("知道了", "รับทราบ")}</button>` : ""}</div></div>`).join("")}</div>`
      : UX.empty(Z("还没有成本变化", "ยังไม่มีการเปลี่ยนต้นทุน"));
    const m = MODAL.open(`<div class="row between"><h3>📊 ${Z("采购分析", "วิเคราะห์การจัดซื้อ")}</h3><button data-mclose>✕</button></div>${kp}
      <div class="pur-grid2">${UX.card({ title: Z("每月采购（到货）", "จัดซื้อรายเดือน (รับเข้า)"), body: cols })}${UX.card({ title: Z("每月付款", "จ่ายเงินรายเดือน"), body: payc })}
        ${UX.card({ title: Z("按分类", "ตามหมวด"), body: cat })}${UX.card({ title: Z("按供应商", "ตามผู้ขาย"), body: sup })}
        ${UX.card({ title: Z("耗材每公斤到手价", "ราคาฟิลาเมนต์ถึงมือต่อ kg"), body: filc + mat })}
        ${UX.card({ title: Z("成本变化", "การเปลี่ยนต้นทุน"), help: Z("到货后耗材平均进价变化超过设置的百分比：自动更新定价用的耗材价格（设置里可以改成只提醒）；别的物品到手单价变化大也会记下来。", "หลังรับของ ถ้าราคาซื้อเฉลี่ยฟิลาเมนต์เปลี่ยนเกินเปอร์เซ็นต์ที่ตั้งไว้ จะอัปเดตราคาฟิลาเมนต์ที่ใช้คิดราคาอัตโนมัติ (ตั้งให้แค่เตือนได้) รายการอื่นที่ราคาเปลี่ยนมากก็บันทึกไว้"), body: costs })}</div>
      ${UX.card({ title: Z("最便宜的供应商", "ผู้ขายที่ถูกที่สุด"), help: Z("按最近一次到货的到手单价（摊了运费 / 税、按汇率折成泰铢）比，没到过货的按写的单价比。★ = 首选供应商", "เทียบด้วยราคาถึงมือครั้งล่าสุด (รวมค่าส่ง / ภาษี แปลงเป็นบาท) ถ้ายังไม่เคยรับของใช้ราคาที่กรอกไว้ ★ = ผู้ขายหลัก"), body: ch })}`);
    m.classList.add("wide");
    m.onclick = async (e) => {
      const b = e.target.closest("[data-cost]");
      if (b) { await busy(b, async () => { await api(`/api/inv/pur/costs/${b.dataset.cost}/${b.dataset.act}`, { json: {} }); toast(Z("已完成", "เสร็จแล้ว")); await analytics(); }); }
    };
  }

  // ---------------- 点击 ----------------
  document.addEventListener("click", (e) => {
    if (!e.target.closest || !(e.target.closest("#tab-purchase") || e.target.closest("#modal-in") || e.target.closest(".pur-pop"))) return;
    const t = e.target.closest("[data-ux-tab]");
    if (t && t.closest('[data-ux-group="pur"]')) { TAB = t.dataset.uxTab; t.parentElement.querySelectorAll(".ux-tab").forEach((x) => x.classList.toggle("on", x === t)); return renderTab(); }
    const a = e.target.closest("[data-pur]");
    if (a) {
      const k = a.dataset.pur;
      if (k === "reload") return render();
      if (k === "new") return window.PURPO && PURPO.form(null).catch((er) => toast(er.message, true));
      if (k === "quick") return window.PURPO && PURPO.quick();
      if (k === "sup") return window.PURPO && PURPO.manageSuppliers();
      if (k === "ana") return analytics().catch((er) => toast(er.message, true));
    }
    const il = e.target.closest("[data-item-links]");
    if (il) { e.preventDefault(); return window.PURPO && PURPO.itemDialog(+il.dataset.itemLinks); }
    const rp = e.target.closest("[data-rcv-po]");
    if (rp) return receiveDialog(+rp.dataset.rcvPo).catch((er) => toast(er.message, true));
    const p = e.target.closest("[data-po]");
    if (p) { e.preventDefault(); return window.PURPO && PURPO.view(+p.dataset.po).catch((er) => toast(er.message, true)); }
    const io = e.target.closest("[data-iss-ok]");
    if (io) {
      const res = prompt(Z("怎么处理的（供应商补发 / 退款 / 不追了…）", "จัดการอย่างไร (ผู้ขายส่งเพิ่ม / คืนเงิน / ไม่ตามแล้ว…)"), "");
      if (res == null) return;
      return busy(io, async () => { await api(`/api/inv/pur/issues/${io.dataset.issOk}/resolve`, { json: { resolution: res } }); toast(Z("已处理", "จัดการแล้ว")); render(); });
    }
  });
  document.addEventListener("ux-go", (e) => {
    const v = String(e.detail || "");
    if (!v.startsWith("pur:")) return;
    const k = v.slice(4);
    if (k === "suggest" || k === "recv") TAB = k;
    else { TAB = "po"; PO_FILTER.status = k; }
    render();
  });

  window.PURK = { ensureMeta: async () => META || loadMeta(), Z, TH, num, thb, cny, money, itName, uLab, qtyText, daysTo, ST, ST_TONE, CAT, ISS, pop, can, hasMoney, meta: () => META,
    render, renderTab, receiveDialog, PO_FILTER, setTab: (t) => { TAB = t; } };
  window.PURCHASE = { show, load: render };
})();
