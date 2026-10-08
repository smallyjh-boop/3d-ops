"use strict";
// 电商财务（v2.21）：总览 / 损益、利润分析、平台结算对账、收支记账、现金流、税务。只有老板能看。
// 界面文字用 Z(中文, 泰文) 直接写两种语言。
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const n0 = (v) => (v == null ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }));
  const m = (v) => (v == null ? "—" : (v < 0 ? "-฿" : "฿") + Math.abs(Number(v)).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 }));
  const pct = (v) => (v == null ? "—" : `${v}%`);
  const cls = (v) => (v == null ? "" : v < 0 ? "bad" : "");
  const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;   // 本地日期（不用 UTC，泰国早上 7 点前会差一天）
  const today = () => ymd(new Date());
  const thisMonth = () => today().slice(0, 7);
  const PLAT = { lazada: "Lazada", shopee: "Shopee", tiktok: "TikTok", manual: Z("私下成交", "ขายตรง"), other: Z("其他", "อื่นๆ") };

  let PER = { mode: "month", month: thisMonth(), start: "", end: "" };
  let META = null, BY = "platform", RC_VIEW = "diff", PREV = null, CUR = "";
  try { const s = JSON.parse(localStorage.getItem("fin_per") || "null"); if (s && s.mode) PER = s; } catch { /* 忽略 */ }

  const q = () => (PER.mode === "range" && PER.start ? `start=${PER.start}&end=${PER.end || today()}` : `month=${PER.month || thisMonth()}`);
  const TABS = { fin_orders: "fin-od", fin_overview: "fin-ov", fin_profit: "fin-pa", fin_settle: "fin-st", fin_book: "fin-bk", fin_cash: "fin-cf", fin_tax: "fin-tx" };

  function bar(id) {
    const mo = [];
    const d = new Date(); d.setDate(1);
    for (let i = 0; i < 18; i++) { mo.push(ymd(d).slice(0, 7)); d.setMonth(d.getMonth() - 1); }
    return `<div class="row gap wrap fin-bar" style="margin:6px 0 12px">
      <select data-fin-month style="min-width:120px">${mo.map((x) => `<option ${PER.mode === "month" && PER.month === x ? "selected" : ""}>${x}</option>`).join("")}
        <option value="__range" ${PER.mode === "range" ? "selected" : ""}>${Z("自定义日期…", "กำหนดวันที่เอง…")}</option></select>
      <span class="${PER.mode === "range" ? "" : "hidden"}" data-fin-range><input type="date" data-fin-start value="${PER.start || ""}"> ~ <input type="date" data-fin-end value="${PER.end || ""}">
        <button class="mini" data-fin-apply>${Z("确定", "ตกลง")}</button></span>
      <button class="mini" data-fin-q="ytd">${Z("今年", "ปีนี้")}</button><button class="mini" data-fin-q="30">${Z("近 30 天", "30 วันล่าสุด")}</button>
      <a class="btn mini-btn" href="/api/fin/export?${q()}" download>⬇ ${Z("导出 Excel（给会计）", "ส่งออก Excel (ให้นักบัญชี)")}</a>
      <span class="muted small">${id === "fin-cf" ? Z("按钱实际进出的日期", "ตามวันที่เงินเข้าออกจริง") : id === "fin-bk" ? "" : Z("按下单日期", "ตามวันที่สั่งซื้อ")}</span></div>`;
  }

  async function show(name) {
    if (!TABS[name]) return;
    CUR = name;
    const box = $("#" + TABS[name]);
    if (!box) return;
    try {
      if (!META) META = await api("/api/fin/meta");
      if (name === "fin_orders") return window.FIN_ORDERS && await FIN_ORDERS.render(box, bar("fin-od"), q(), META);   // v2.32 订单明细（orders.js）
      if (name === "fin_overview") return await overview(box);
      if (name === "fin_profit") return await analysis(box);
      if (name === "fin_settle") return await settle(box);
      if (name === "fin_book") return await book(box);
      if (name === "fin_cash") return await cash(box);
      if (name === "fin_tax") return await tax(box);
    } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
  }
  const reload = () => show(CUR);

  // ---------------- 总览 + 损益表 ----------------
  function chg(v, good = true) {
    if (v == null) return "";
    const up = v >= 0;
    return ` <small class="${(up === good) ? "ok" : "bad"}">${up ? "▲" : "▼"} ${Math.abs(v)}%</small>`;
  }
  function chart(days) {
    if (!days.length) return "";
    const W = 640, H = 150, P = 4;
    const mx = Math.max(1, ...days.map((d) => Math.max(d.revenue, 0)));
    const mn = Math.min(0, ...days.map((d) => d.profit));
    const span = mx - mn || 1;
    const bw = (W - P * 2) / days.length;
    const y = (v) => H - P - ((v - mn) / span) * (H - P * 2);
    const bars = days.map((d, i) => `<rect x="${P + i * bw + bw * 0.15}" y="${y(Math.max(0, d.revenue))}" width="${bw * 0.7}" height="${Math.max(1, y(0) - y(Math.max(0, d.revenue)))}" class="fc-rev"><title>${d.day} ${Z("收入", "รายได้")} ${m(d.revenue)}</title></rect>`).join("");
    const line = days.map((d, i) => `${P + i * bw + bw / 2},${y(d.profit)}`).join(" ");
    return `<svg viewBox="0 0 ${W} ${H}" class="fin-chart" preserveAspectRatio="none"><line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" class="fc-zero"/>${bars}
      <polyline points="${line}" class="fc-profit"/></svg>
      <div class="small muted"><span class="fc-key fc-rev"></span>${Z("每日收入", "รายได้รายวัน")} <span class="fc-key fc-profit"></span>${Z("每日订单利润", "กำไรจากคำสั่งซื้อรายวัน")} · ${days[0].day} ~ ${days[days.length - 1].day}</div>`;
  }
  function plTable(lines) {
    return `<table class="grid fin-pl"><tbody>${lines.map((l) => `<tr class="lv${l.level}"><td>${esc(TH() ? l.th : l.zh)}${l.est ? ` <span class="warn small">${Z("估", "ประมาณ")}</span>` : ""}</td>
      <td class="num ${cls(l.amount)}">${m(l.amount)}</td><td class="muted small">${esc(TH() ? (l.note_th || "") : (l.note || ""))}</td></tr>`).join("")}</tbody></table>`;
  }
  async function overview(box) {
    const r = await api(`/api/fin/overview?month=${PER.mode === "month" ? PER.month : thisMonth()}`);
    const pl = await api(`/api/fin/pl?${q()}`);
    const s = r.summary, c = r.change;
    const warn = [];
    if (s.fee_estimated) warn.push(Z(`平台扣费有 ${m(s.fee_estimated)} 是按扣点估算的：到「平台对账」导入平台的结算报表，就按真实扣费算。`, `ค่าธรรมเนียม ${m(s.fee_estimated)} เป็นการประมาณ: นำเข้ารายงานการชำระเงินที่「กระทบยอดแพลตฟอร์ม」เพื่อใช้ค่าจริง`));
    if (s.missing_data_orders) warn.push(Z(`${s.missing_data_orders} 单商品没对上 SKU 或缺克数，成本偏低。`, `${s.missing_data_orders} คำสั่งซื้อจับคู่ SKU ไม่ได้หรือไม่มีกรัม ต้นทุนจะต่ำกว่าจริง`));
    if (r.unpaid_count) warn.push(Z(`${r.unpaid_count} 单超时未回款（${m(r.reconcile.unpaid_amount)}）。`, `${r.unpaid_count} คำสั่งซื้อยังไม่ได้รับเงินเกินกำหนด (${m(r.reconcile.unpaid_amount)})`));
    if (r.diff_count) warn.push(Z(`${r.diff_count} 单平台扣费比预计多（共多 ${m(r.reconcile.diff_amount)}）。`, `${r.diff_count} คำสั่งซื้อถูกหักค่าธรรมเนียมมากกว่าที่คาด (รวม ${m(r.reconcile.diff_amount)})`));
    if (s.fixed_estimated) warn.push(Z("固定费用（房租、人工、折旧）本期没记账，按设置估算了。", "ค่าใช้จ่ายคงที่ (ค่าเช่า ค่าแรง ค่าเสื่อม) งวดนี้ยังไม่ได้บันทึก จึงประมาณจากการตั้งค่า"));
    const tile = (label, val, sub = "", klass = "", go = "") => `<div class="tile ${klass}" ${go ? `data-go="${go}"` : ""}><span>${label}</span><b>${val}${sub}</b></div>`;
    box.innerHTML = bar("fin-ov") +
      `<div class="tiles">
        ${tile(Z("销售收入", "ยอดขาย"), m(s.revenue), chg(c.revenue))}
        ${tile(Z("毛利", "กำไรขั้นต้น") + ` · ${pct(s.gross_margin)}`, m(s.gross), chg(c.gross))}
        ${tile(Z("净利润（税前）", "กำไรสุทธิ (ก่อนภาษี)") + ` · ${pct(s.net_margin)}`, m(s.net), chg(c.net), s.net < 0 ? "bad" : "")}
        ${tile(Z("订单 / 客单价", "คำสั่งซื้อ / ยอดต่อบิล"), `${n0(s.orders)}<small> / ${m(s.aov)}</small>`, chg(c.orders))}
        ${tile(Z("平台扣费率", "อัตราค่าธรรมเนียม"), pct(s.fee_rate), "", "", "fin_settle")}
        ${tile(Z("现金净流入", "เงินสดสุทธิ"), m(r.cash.net), "", r.cash.net < 0 ? "warn" : "", "fin_cash")}
        ${tile(Z("超时未回款", "ยังไม่ได้รับเงิน"), m(r.reconcile.unpaid_amount), "", r.unpaid_count ? "warn" : "", "fin_settle")}
      </div>
      <p class="muted small">${Z(`${r.month} · 箭头是和上个月比`, `${r.month} · ลูกศรเทียบกับเดือนก่อน`)}</p>
      ${warn.length ? `<div class="card warn-box small">${warn.map((w) => `<div>⚠ ${esc(w)}</div>`).join("")}</div>` : ""}
      <div class="lanes two">
        <div class="card"><h3>${Z("损益表", "งบกำไรขาดทุน")} <span class="muted small">${esc(pl.period)}</span></h3>${plTable(pl.lines)}
          <p class="muted small">${Z("生产成本只算材料、电费、包材、失败损耗；房租、人工、折旧算固定费用（记了账用记的，没记按设置估算），不会重复算。看单个商品赚不赚钱用「每单利润」。",
            "ต้นทุนการผลิตนับเฉพาะวัสดุ ค่าไฟ วัสดุแพ็ค ของเสีย; ค่าเช่า ค่าแรง ค่าเสื่อมนับเป็นค่าใช้จ่ายคงที่ (บันทึกแล้วใช้ยอดจริง ไม่บันทึกใช้ค่าประมาณ) ไม่นับซ้ำ ดูกำไรรายสินค้าที่「กำไรต่อคำสั่งซื้อ」")}
            ${s.inventory_used ? Z(` 本期库存实际消耗（材料、包材等）${m(s.inventory_used)}，可以和上面的材料、包材对照。`, ` สต็อกที่ใช้จริงงวดนี้ ${m(s.inventory_used)} เทียบกับวัสดุและวัสดุแพ็คด้านบนได้`) : ""}
            ${s.wht ? Z(` 平台代扣税 ${m(s.wht)}（年底报所得税可以抵扣）。`, ` ภาษีหัก ณ ที่จ่ายโดยแพลตฟอร์ม ${m(s.wht)} (นำไปหักภาษีเงินได้ตอนสิ้นปีได้)`) : ""}</p></div>
        <div>
          <div class="card"><h3>${Z("每天的收入和利润", "รายได้และกำไรรายวัน")}</h3>${chart(r.days) || `<p class="muted small">${Z("这个月还没有订单", "เดือนนี้ยังไม่มีคำสั่งซื้อ")}</p>`}</div>
          <div class="card"><h3>${Z("按平台", "ตามแพลตฟอร์ม")}</h3>${dimTable(r.platforms, "platform", true)}</div>
          <div class="card"><h3>${Z("赚钱最多的产品", "สินค้าที่ทำเงินมากที่สุด")}</h3>${dimTable(r.top_products.slice().sort((a, b) => b.profit - a.profit), "product", true)}</div>
        </div></div>`;
  }

  // ---------------- 利润分析 ----------------
  const DIMS = { platform: ["平台", "แพลตฟอร์ม"], shop: ["店铺", "ร้านค้า"], product: ["产品", "สินค้า"], sku: ["SKU", "SKU"], day: ["按日", "รายวัน"], month: ["按月", "รายเดือน"] };
  function dimTable(rows, by, compact) {
    if (!rows || !rows.length) return `<p class="muted small">${Z("没有数据", "ไม่มีข้อมูล")}</p>`;
    const name = (r) => (by === "platform" ? (PLAT[r.key] || r.key) : r.key);
    return `<table class="grid small"><thead><tr><th>${Z(DIMS[by][0], DIMS[by][1])}</th>${by === "product" || by === "sku" ? `<th>${Z("名称", "ชื่อ")}</th>` : ""}
      <th>${Z("订单", "คำสั่งซื้อ")}</th>${compact ? "" : `<th>${Z("件数", "ชิ้น")}</th>`}<th>${Z("收入", "รายได้")}</th>${compact ? "" : `<th>${Z("占比", "สัดส่วน")}</th><th>${Z("平台扣费", "ค่าธรรมเนียม")}</th><th>${Z("生产成本", "ต้นทุนผลิต")}</th>`}
      <th>${Z("利润", "กำไร")}</th><th>${Z("利润率", "อัตรากำไร")}</th></tr></thead><tbody>` +
      rows.map((r) => `<tr><td class="${by === "sku" || by === "product" ? "mono" : ""}" data-notr>${esc(name(r))}</td>${by === "product" || by === "sku" ? `<td data-notr>${esc(r.name || "")}</td>` : ""}
        <td>${r.orders}</td>${compact ? "" : `<td>${r.qty}</td>`}<td class="num">${m(r.revenue)}</td>
        ${compact ? "" : `<td><div class="fin-share"><i style="width:${Math.min(100, r.share || 0)}%"></i></div><span class="small muted">${pct(r.share)}</span></td>
        <td class="num">${m(r.fee)}${r.est_fee ? ` <span class="warn small" title="${Z("有订单按扣点估算", "บางคำสั่งซื้อเป็นค่าประมาณ")}">*</span>` : ""}</td><td class="num">${m(r.cost)}</td>`}
        <td class="num ${cls(r.profit)}">${m(r.profit)}</td><td class="${r.margin != null && r.margin < 15 ? "warn" : ""}">${pct(r.margin)}</td></tr>`).join("") + "</tbody></table>";
  }
  async function analysis(box) {
    const r = await api(`/api/fin/breakdown?by=${BY}&${q()}`);
    const t = r.total;
    box.innerHTML = bar("fin-pa") + `<div class="chips" style="margin-bottom:8px">${Object.entries(DIMS).map(([k, v]) => `<span class="chip ${k === BY ? "on" : ""}" data-fin-by="${k}">${Z(v[0], v[1])}</span>`).join("")}</div>
      <div class="card summary small"><div>${Z("订单", "คำสั่งซื้อ")}<b>${n0(t.orders)}</b></div><div>${Z("件数", "ชิ้น")}<b>${n0(t.qty)}</b></div><div>${Z("收入", "รายได้")}<b>${m(t.revenue)}</b></div>
        <div>${Z("平台扣费", "ค่าธรรมเนียม")}<b>${m(t.fee)}</b></div><div>${Z("生产成本", "ต้นทุนผลิต")}<b>${m(t.cost)}</b></div><div>${Z("订单利润", "กำไรจากคำสั่งซื้อ")}<b class="${cls(t.profit)}">${m(t.profit)}</b></div><div>${Z("利润率", "อัตรากำไร")}<b>${pct(t.margin)}</b></div></div>
      <div class="card">${dimTable(r.rows, BY, false)}</div>
      <p class="muted small">${Z("订单利润 = 收入 − 平台扣费 − 生产成本（材料、机时分摊、包材、损耗），没扣广告费等支出；整个店的利润看「总览」的损益表。产品 / SKU 按商品金额比例分摊订单的扣费和成本。* = 有订单的扣费是按扣点估算的。利润率低于 15% 标黄。",
        "กำไรจากคำสั่งซื้อ = รายได้ − ค่าธรรมเนียม − ต้นทุนผลิต (วัสดุ ค่าเครื่อง วัสดุแพ็ค ของเสีย) ยังไม่หักค่าโฆษณาและค่าใช้จ่ายอื่น ดูกำไรทั้งร้านที่งบกำไรขาดทุนใน「ภาพรวม」 * = บางคำสั่งซื้อใช้ค่าธรรมเนียมประมาณ อัตรากำไรต่ำกว่า 15% เป็นสีเหลือง")}</p>`;
  }

  // ---------------- 平台结算对账 ----------------
  async function settle(box) {
    const r = await api(`/api/fin/reconcile?${q()}`);
    const t = r.total;
    const views = { diff: [Z("扣费比预计多", "หักมากกว่าที่คาด"), r.diff.length], unpaid: [Z("超时未回款", "ยังไม่ได้รับเงิน"), r.unpaid.length],
      unknown: [Z("系统里没有的订单", "ไม่มีในระบบ"), r.unknown.length], settled: [Z("已回款", "ได้รับเงินแล้ว"), r.settled.length] };
    box.innerHTML = bar("fin-st") +
      `<div class="card"><h3>${Z("导入平台结算报表", "นำเข้ารายงานการชำระเงินของแพลตฟอร์ม")}</h3>
        <p class="small muted">${Z("Lazada：卖家中心 → 财务 → 账户对账单（Account Statement / Transaction）导出；Shopee：我的收入 → 已拨款 → 导出收入报表；TikTok：财务 → 结算 → 导出。表格每单一行（有到账金额）或每笔费用一行都可以，重复导入不会重复记。导入后对上的订单按真实到账算利润。",
          "Lazada: Seller Center → การเงิน → Account Statement/Transaction ส่งออก; Shopee: รายได้ของฉัน → โอนแล้ว → ส่งออกรายงาน; TikTok: การเงิน → การชำระเงิน → ส่งออก ใช้ได้ทั้งแบบหนึ่งแถวต่อคำสั่งซื้อและหนึ่งแถวต่อค่าธรรมเนียม นำเข้าซ้ำจะไม่นับซ้ำ")}</p>
        <label class="filebtn">📄 ${Z("选择表格（.xlsx / .csv）", "เลือกไฟล์ (.xlsx / .csv)")}<input type="file" id="fin-st-file" accept=".xlsx,.xlsm,.csv,.txt" hidden></label>
        <div id="fin-st-prev"></div></div>
      <div class="card summary small"><div>${Z("期间订单", "คำสั่งซื้อในงวด")}<b>${n0(t.orders)}</b></div><div>${Z("已回款", "ได้รับเงินแล้ว")}<b>${n0(t.settled)}</b></div>
        <div>${Z("到账", "ยอดที่ได้รับ")}<b>${m(t.net)}</b></div><div>${Z("平台实际扣费", "ค่าธรรมเนียมจริง")}<b>${m(t.fees)} <small>${pct(t.fee_rate)}</small></b></div>
        <div>${Z("超时未回款", "ยังไม่ได้รับเงิน")}<b class="${t.unpaid_amount ? "warn" : ""}">${m(t.unpaid_amount)}</b></div>
        ${t.adjustments ? `<div>${Z("没有订单号的调整", "รายการปรับที่ไม่มีเลขคำสั่งซื้อ")}<b>${m(t.adjustments)}</b></div>` : ""}</div>
      <div class="chips" style="margin:8px 0">${Object.entries(views).map(([k, v]) => `<span class="chip ${k === RC_VIEW ? "on" : ""}" data-fin-rc="${k}">${v[0]} ${v[1]}</span>`).join("")}</div>
      <div class="card">${rcTable(r)}</div>
      <p class="muted small">${Z(`「扣费比预计多」= 到账比「订单金额 × (1 − 设置里的扣点)」少 ${r.settings.tolerance} 铢以上（检查是不是被多扣、罚款、优惠券算到卖家）；「超时未回款」= 已发货 / 已完成超过 ${r.settings.days} 天还没有回款记录（可能还没导入结算表，或平台没打款）。天数和容差在 设置 → 财务 改。`,
        `「หักมากกว่าที่คาด」= ได้รับน้อยกว่า「ยอดสั่งซื้อ × (1 − อัตราค่าธรรมเนียม)」เกิน ${r.settings.tolerance} บาท; 「ยังไม่ได้รับเงิน」= ส่งแล้ว/สำเร็จเกิน ${r.settings.days} วันแต่ยังไม่มีข้อมูลการรับเงิน ปรับได้ที่ ตั้งค่า → การเงิน`)}</p>
      <div class="card"><h3>${Z("导入记录", "ประวัติการนำเข้า")}</h3>${r.batches.length ? `<table class="grid small"><thead><tr><th>${Z("时间", "เวลา")}</th><th>${Z("平台", "แพลตฟอร์ม")}</th><th>${Z("文件", "ไฟล์")}</th>
        <th>${Z("行（新）", "แถว (ใหม่)")}</th><th>${Z("订单", "คำสั่งซื้อ")}</th><th>${Z("合计", "รวม")}</th><th>${Z("日期", "วันที่")}</th><th></th></tr></thead><tbody>` +
        r.batches.map((b) => `<tr><td class="nowrap">${fmtTime(b.created_at)}</td><td>${esc(PLAT[b.platform] || b.platform)} <span data-notr>${esc(b.shop || "")}</span></td><td data-notr>${esc(b.filename || "")}</td>
          <td>${b.rows} (${b.new_rows})</td><td>${b.orders}</td><td class="num">${m(b.total)}</td><td class="small">${esc(b.date_from || "")} ~ ${esc(b.date_to || "")}</td>
          <td><button class="mini danger" data-fin-delbatch="${b.id}">${Z("删除", "ลบ")}</button></td></tr>`).join("") + "</tbody></table>" : `<p class="muted small">${Z("还没导入过", "ยังไม่เคยนำเข้า")}</p>`}</div>`;
  }
  function rcTable(r) {
    const rows = r[RC_VIEW] || [];
    if (!rows.length) return `<p class="muted small">${Z("没有", "ไม่มี")}</p>`;
    if (RC_VIEW === "unknown") {
      return `<table class="grid small"><thead><tr><th>${Z("平台", "แพลตฟอร์ม")}</th><th>${Z("订单号", "เลขคำสั่งซื้อ")}</th><th>${Z("到账", "ยอดที่ได้รับ")}</th><th>${Z("日期", "วันที่")}</th></tr></thead><tbody>` +
        rows.map((x) => `<tr><td>${esc(PLAT[x.platform] || x.platform)}</td><td class="mono" data-notr>${esc(x.order_no)}</td><td class="num">${m(x.amount)}</td><td>${esc(x.day || "")}</td></tr>`).join("") +
        `</tbody></table><p class="muted small">${Z("这些订单还没导入到系统（订单 → 导入订单表格），导入后会自动对上。", "คำสั่งซื้อเหล่านี้ยังไม่ได้นำเข้าระบบ นำเข้าแล้วจะจับคู่อัตโนมัติ")}</p>`;
    }
    const unpaid = RC_VIEW === "unpaid";
    return `<table class="grid small"><thead><tr><th>${Z("下单日", "วันสั่งซื้อ")}</th><th>${Z("平台 · 店铺", "แพลตฟอร์ม · ร้าน")}</th><th>${Z("订单号", "เลขคำสั่งซื้อ")}</th><th>${Z("订单金额", "ยอดสั่งซื้อ")}</th>
      ${unpaid ? `<th>${Z("已过天数", "ผ่านไป (วัน)")}</th>` : `<th>${Z("到账", "ยอดที่ได้รับ")}</th><th>${Z("扣费", "ค่าธรรมเนียม")}</th><th>${Z("预计到账", "ยอดที่คาด")}</th><th>${Z("少了", "ขาดไป")}</th>`}</tr></thead><tbody>` +
      rows.map((x) => `<tr><td>${esc(x.day)}</td><td>${esc(PLAT[x.platform] || x.platform)} <span data-notr>${esc(x.shop || "")}</span></td>
        <td class="mono"><a data-fin-order="${x.id}" data-notr>${esc(x.order_no)}</a></td><td class="num">${m(x.revenue)}</td>
        ${unpaid ? `<td class="warn">${x.days}</td>` : `<td class="num">${m(x.net)}</td><td class="num">${m(x.fee)} <span class="muted">${pct(x.fee_rate)}</span></td><td class="num">${m(x.expected)}</td>
        <td class="num ${x.diff > r.settings.tolerance ? "bad" : ""}">${m(x.diff)}</td>`}</tr>`).join("") + "</tbody></table>";
  }
  let STP = null;
  async function settlePreview(file) {
    const fd = new FormData(); fd.append("file", file);
    STP = await api("/api/fin/settle/preview", { method: "POST", body: fd });
    const shops = [...new Set((META.shops || []).map((s) => s.shop).filter(Boolean))];
    const sel = (f) => `<select data-fin-map="${f}"><option value="">—</option>${STP.headers.map((h, i) => `<option value="${i}" ${STP.mapping[f] === i ? "selected" : ""}>${esc(h || `#${i + 1}`)}</option>`).join("")}</select>`;
    const FZ = { order_no: ["订单号", "เลขคำสั่งซื้อ"], net: ["到账金额（每单一行的表格）", "ยอดที่ได้รับ (หนึ่งแถวต่อคำสั่งซื้อ)"], amount: ["金额（每笔费用一行的表格）", "จำนวนเงิน (หนึ่งแถวต่อค่าธรรมเนียม)"],
      fee_name: ["费用名称 / 类型", "ชื่อ/ประเภทค่าธรรมเนียม"], date: ["结算日期", "วันที่ชำระ"], wht: ["代扣税（WHT）", "ภาษีหัก ณ ที่จ่าย (WHT)"], vat: ["费用里的 VAT", "VAT ในค่าธรรมเนียม"], ref: ["结算单号", "เลขที่รายการ"] };
    $("#fin-st-prev").innerHTML = `<div class="small" style="margin-top:8px"><b data-notr>${esc(file.name)}</b> · ${Z(`${STP.rows} 行`, `${STP.rows} แถว`)}</div>
      <div class="form4" style="margin:6px 0"><label>${Z("平台", "แพลตฟอร์ม")}<select id="fin-st-plat">${["lazada", "shopee", "tiktok", "other"].map((p) => `<option value="${p}" ${STP.platform === p ? "selected" : ""}>${PLAT[p]}</option>`).join("")}</select></label>
        <label>${Z("店铺（可空）", "ร้าน (เว้นได้)")}<input id="fin-st-shop" list="fin-shops" data-notr><datalist id="fin-shops">${shops.map((s) => `<option value="${esc(s)}">`).join("")}</datalist></label></div>
      <div class="form4">${Object.keys(FZ).map((f) => `<label>${Z(FZ[f][0], FZ[f][1])}${sel(f)}</label>`).join("")}</div>
      <p class="small muted">${Z("「到账金额」和「金额」选一个：每单一行的表格选到账金额；Lazada 那种每笔费用一行的选金额（按订单号加起来）。", "เลือก「ยอดที่ได้รับ」หรือ「จำนวนเงิน」อย่างใดอย่างหนึ่ง")}</p>
      <div style="overflow:auto;max-height:220px"><table class="grid small"><thead><tr>${STP.headers.map((h) => `<th data-notr>${esc(h)}</th>`).join("")}</tr></thead><tbody>${STP.sample.map((r) => `<tr>${r.map((c) => `<td data-notr>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
      <button class="primary" id="fin-st-go" style="margin-top:6px">${Z("导入", "นำเข้า")}</button>`;
  }

  // ---------------- 收支记账 ----------------
  async function book(box) {
    const r = await api(`/api/fin/expenses?${q()}`);
    const cats = META.categories, vat = META.settings.vat_on;
    box.innerHTML = bar("fin-bk") +
      `<div class="card"><h3>${Z("记一笔", "บันทึกรายการ")}</h3>
        <div class="form4">
          <label>${Z("方向", "ประเภท")}<select id="fb-dir"><option value="out">${Z("支出", "รายจ่าย")}</option><option value="in">${Z("收入", "รายรับ")}</option></select></label>
          <label>${Z("日期", "วันที่")}<input type="date" id="fb-day" value="${today()}"></label>
          <label>${Z("分类", "หมวด")}<select id="fb-cat">${cats.out.map((c) => `<option>${esc(c)}</option>`).join("")}</select></label>
          <label>${Z("金额（฿，含税）", "จำนวนเงิน (฿ รวม VAT)")}<input type="number" step="any" id="fb-amt"></label>
          ${vat ? `<label>${Z("其中 VAT", "ในนี้ VAT")}<input type="number" step="any" id="fb-vat" placeholder="${Z("有税票才填", "กรอกเมื่อมีใบกำกับภาษี")}"></label>
          <label class="row"><input type="checkbox" id="fb-inv"> ${Z("有正式税票", "มีใบกำกับภาษีเต็มรูป")}</label>` : ""}
          <label>${Z("收款方 / 付款方", "ผู้รับ/ผู้จ่าย")}<input id="fb-payee" data-notr></label>
          <label>${Z("付款方式", "วิธีชำระ")}<select id="fb-method">${Object.entries(cats.methods).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
          <label>${Z("备注", "หมายเหตุ")}<input id="fb-note" data-notr></label>
          <label>${Z("票据（照片 / PDF，可空）", "ใบเสร็จ (รูป/PDF เว้นได้)")}<input type="file" id="fb-file" accept="image/*,.pdf"></label>
        </div>
        <button class="primary" id="fb-save">${Z("记账", "บันทึก")}</button>
        <p class="muted small">${Z("采购的付款在「采购」里记，会自动算进现金流，这里不用再记。房租、人工、设备折旧记在这里后，损益表就用实际数，不再按设置估算。",
          "การจ่ายค่าซื้อของบันทึกใน「จัดซื้อ」 จะนับในกระแสเงินสดอัตโนมัติ ไม่ต้องบันทึกซ้ำ")}</p></div>
      <div class="card summary small"><div>${Z("支出合计", "รายจ่ายรวม")}<b>${m(r.total_out)}</b></div><div>${Z("收入合计", "รายรับรวม")}<b>${m(r.total_in)}</b></div>
        ${r.by_category.slice(0, 6).map((c) => `<div>${esc(c.category)}<b>${m(c.amount)}</b></div>`).join("")}</div>
      <div class="card"><table class="grid small"><thead><tr><th>${Z("日期", "วันที่")}</th><th>${Z("分类", "หมวด")}</th><th>${Z("金额", "จำนวนเงิน")}</th>${vat ? "<th>VAT</th>" : ""}
        <th>${Z("收款方", "ผู้รับ")}</th><th>${Z("方式", "วิธี")}</th><th>${Z("备注", "หมายเหตุ")}</th><th>${Z("票据", "ใบเสร็จ")}</th><th></th></tr></thead><tbody>` +
        (r.rows.map((x) => `<tr><td class="nowrap">${esc(x.day)}</td><td>${x.direction === "in" ? `<span class="ok">${Z("收", "รับ")}</span> ` : ""}${esc(x.category)}</td>
          <td class="num ${x.direction === "in" ? "ok" : ""}">${x.direction === "in" ? "+" : ""}${m(x.amount)}</td>${vat ? `<td class="num">${x.vat ? m(x.vat) : ""}${x.tax_invoice ? " 🧾" : ""}</td>` : ""}
          <td data-notr>${esc(x.payee || "")}</td><td class="small">${esc(cats.methods[x.method] || "")}</td><td class="small" data-notr>${esc(x.note || "")}</td>
          <td>${x.has_receipt ? `<a href="/api/fin/expenses/${x.id}/receipt" target="_blank">📎</a>` : `<label class="filebtn mini">＋<input type="file" data-fb-rcpt="${x.id}" accept="image/*,.pdf" hidden></label>`}</td>
          <td><button class="mini danger" data-fb-del="${x.id}">${Z("删除", "ลบ")}</button></td></tr>`).join("") ||
          `<tr><td colspan="9" class="muted">${Z("这个期间还没有记账", "งวดนี้ยังไม่มีรายการ")}</td></tr>`) + "</tbody></table></div>";
  }

  // ---------------- 现金流 ----------------
  async function cash(box) {
    const r = await api(`/api/fin/cashflow?${q()}`);
    const t = r.total;
    box.innerHTML = bar("fin-cf") +
      (r.has_settlements ? "" : `<div class="card warn-box small">⚠ ${Z("还没导入平台结算报表：平台回款要到「平台对账」导入后才有。", "ยังไม่ได้นำเข้ารายงานการชำระเงิน: ยอดเงินจากแพลตฟอร์มจะแสดงหลังนำเข้าที่「กระทบยอดแพลตฟอร์ม」")}</div>`) +
      `<div class="card summary small"><div>${Z("平台回款", "เงินจากแพลตฟอร์ม")}<b>${m(t.settle_in)}</b></div><div>${Z("其他收入", "รายรับอื่น")}<b>${m(t.other_in)}</b></div>
        <div>${Z("老板投入", "เงินลงทุนเจ้าของ")}<b>${m(t.capital_in)}</b></div><div>${Z("采购付款", "จ่ายค่าซื้อของ")}<b>${m(-t.purchase_out)}</b></div>
        <div>${Z("支出", "รายจ่าย")}<b>${m(-t.expense_out)}</b></div><div>${Z("净流入", "เงินสดสุทธิ")}<b class="${cls(t.net)}">${m(t.net)}</b></div></div>
      <div class="card"><table class="grid small"><thead><tr><th>${r.monthly ? Z("月份", "เดือน") : Z("日期", "วันที่")}</th><th>${Z("平台回款", "เงินจากแพลตฟอร์ม")}</th><th>${Z("其他收入", "รายรับอื่น")}</th>
        <th>${Z("老板投入", "เงินลงทุนเจ้าของ")}</th><th>${Z("采购付款", "จ่ายค่าซื้อของ")}</th><th>${Z("支出", "รายจ่าย")}</th><th>${Z("净流入", "สุทธิ")}</th><th>${Z("累计", "สะสม")}</th></tr></thead><tbody>` +
        (r.rows.map((x) => `<tr><td>${esc(x.key)}</td><td class="num">${x.settle_in ? m(x.settle_in) : ""}</td><td class="num">${x.other_in ? m(x.other_in) : ""}</td><td class="num">${x.capital_in ? m(x.capital_in) : ""}</td>
          <td class="num">${x.purchase_out ? m(-x.purchase_out) : ""}</td><td class="num">${x.expense_out ? m(-x.expense_out) : ""}</td><td class="num ${cls(x.net)}">${m(x.net)}</td><td class="num ${cls(x.running)}">${m(x.running)}</td></tr>`).join("") ||
          `<tr><td colspan="8" class="muted">${Z("这个期间没有现金进出记录", "งวดนี้ไม่มีรายการเงินเข้าออก")}</td></tr>`) + "</tbody></table></div>";
  }

  // ---------------- 税务 ----------------
  async function tax(box) {
    const r = await api(`/api/fin/tax?${q()}`);
    const t = r.total;
    const pctY = Math.min(100, (r.year_sales / r.vat_threshold) * 100);
    box.innerHTML = bar("fin-tx") +
      (r.vat_on ? `<div class="card"><h3>VAT（${(r.vat_rate * 100).toFixed(0)}%）</h3><table class="grid small"><thead><tr><th>${Z("月份", "เดือน")}</th><th>${Z("销售额", "ยอดขาย")}</th>
          <th>${Z("销项税", "ภาษีขาย")}</th><th>${Z("进项税（支出）", "ภาษีซื้อ (รายจ่าย)")}</th><th>${Z("进项税（平台费用）", "ภาษีซื้อ (ค่าธรรมเนียม)")}</th><th>${Z("应缴", "ต้องชำระ")}</th></tr></thead><tbody>` +
          r.months.map((x) => `<tr><td>${x.month}</td><td class="num">${m(x.sales)}</td><td class="num">${m(x.out_vat)}</td><td class="num">${m(x.in_vat_expenses)}</td><td class="num">${m(x.in_vat_fees)}</td>
            <td class="num ${x.payable > 0 ? "warn" : ""}"><b>${m(x.payable)}</b></td></tr>`).join("") +
          `<tr class="lv2"><td>${Z("合计", "รวม")}</td><td class="num">${m(t.sales)}</td><td class="num">${m(t.out_vat)}</td><td class="num">${m(t.in_vat_expenses)}</td><td class="num">${m(t.in_vat_fees)}</td><td class="num"><b>${m(t.payable)}</b></td></tr></tbody></table>
          <p class="muted small">${Z("每月 15 号前报 ภ.พ.30（网上申报 23 号前）。这里是估算，以会计核对为准。平台费用里的 VAT 来自导入的结算表（有 VAT 列才有）。", "ยื่น ภ.พ.30 ภายในวันที่ 15 ของเดือนถัดไป (ออนไลน์ภายในวันที่ 23) ตัวเลขนี้เป็นการประมาณ ให้นักบัญชีตรวจสอบ")}</p>
          ${r.missing_invoice.length ? `<p class="small warn">${Z(`${r.missing_invoice.length} 笔 1000 铢以上的支出没有勾「有正式税票」，进项税抵扣不了：`, `${r.missing_invoice.length} รายการเกิน 1000 บาทยังไม่ได้ติ๊ก「มีใบกำกับภาษี」:`)}
            ${r.missing_invoice.slice(0, 10).map((x) => `${esc(x.day)} ${esc(x.category)} ${m(x.amount)}`).join("；")}</p>` : ""}</div>`
        : `<div class="card"><h3>VAT</h3><p class="small">${Z("还没注册 VAT（设置 → 财务 里可以打开）。报表按含税价算，不拆销项税。", "ยังไม่ได้จดทะเบียน VAT (เปิดได้ที่ ตั้งค่า → การเงิน) รายงานคิดตามราคารวมภาษี")}</p>
          <p class="small">${Z(`${r.year} 年到现在的销售额 ${m(r.year_sales)}；一年超过 180 万铢就要注册 VAT。`, `ยอดขายปี ${r.year} ถึงตอนนี้ ${m(r.year_sales)}; เกิน 1.8 ล้านบาทต่อปีต้องจดทะเบียน VAT`)}</p>
          <div class="fin-share big"><i style="width:${pctY}%" class="${pctY > 80 ? "warn" : ""}"></i></div><p class="small muted">${pctY.toFixed(1)}% / ฿1,800,000</p></div>`) +
      `<div class="card"><h3>${Z("平台代扣税（WHT）", "ภาษีหัก ณ ที่จ่ายโดยแพลตฟอร์ม (WHT)")}</h3><table class="grid small"><thead><tr><th>${Z("月份", "เดือน")}</th><th>${Z("代扣合计", "รวม")}</th><th>${Z("按平台", "ตามแพลตฟอร์ม")}</th></tr></thead><tbody>` +
        r.months.map((x) => `<tr><td>${x.month}</td><td class="num">${m(x.wht)}</td><td class="small">${Object.entries(x.wht_by_platform).map(([k, v]) => `${esc(PLAT[k] || k)} ${m(v)}`).join("、")}</td></tr>`).join("") +
        `</tbody></table><p class="muted small">${Z("平台从回款里代扣的所得税（来自导入的结算表的 WHT 列）。平台会开代扣凭证（50 ทวิ），年底报个人 / 公司所得税时可以抵扣，记得在平台后台下载保存。",
          "ภาษีที่แพลตฟอร์มหักจากยอดโอน (จากคอลัมน์ WHT ในรายงานที่นำเข้า) แพลตฟอร์มจะออกหนังสือรับรอง 50 ทวิ ใช้หักภาษีเงินได้ตอนสิ้นปีได้ อย่าลืมดาวน์โหลดเก็บไว้")}</p></div>`;
  }

  // ---------------- 事件 ----------------
  function savePer() { try { localStorage.setItem("fin_per", JSON.stringify(PER)); } catch { /* 忽略 */ } }
  document.addEventListener("change", async (e) => {
    const t = e.target;
    if (t.matches && t.matches("[data-fin-month]")) {
      if (t.value === "__range") { PER.mode = "range"; PER.start = PER.start || `${thisMonth()}-01`; PER.end = PER.end || today(); }
      else { PER = { mode: "month", month: t.value, start: "", end: "" }; }
      savePer(); return reload();
    }
    if (t.id === "fin-st-file" && t.files[0]) { try { await settlePreview(t.files[0]); } catch (err) { toast(err.message, true); } t.value = ""; return; }
    if (t.id === "fb-dir") {
      const cats = META.categories[t.value === "in" ? "in" : "out"];
      $("#fb-cat").innerHTML = cats.map((c) => `<option>${esc(c)}</option>`).join("");
    }
    if (t.dataset && t.dataset.fbRcpt && t.files[0]) {
      const fd = new FormData(); fd.append("file", t.files[0]);
      try { await api(`/api/fin/expenses/${t.dataset.fbRcpt}/receipt`, { method: "POST", body: fd }); toast(Z("票据已上传", "อัปโหลดใบเสร็จแล้ว")); reload(); } catch (err) { toast(err.message, true); }
    }
  });
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (!t.closest || !t.closest("#fin-ov,#fin-pa,#fin-st,#fin-bk,#fin-cf,#fin-tx")) return;
    if (t.dataset.finApply !== undefined) {
      const bx = t.closest(".fin-bar");
      PER = { mode: "range", start: $("[data-fin-start]", bx).value, end: $("[data-fin-end]", bx).value || today(), month: "" };
      savePer(); return reload();
    }
    if (t.dataset.finQ) {
      const d = new Date();
      PER = t.dataset.finQ === "ytd" ? { mode: "range", start: `${d.getFullYear()}-01-01`, end: today() }
        : { mode: "range", start: ymd(new Date(Date.now() - 29 * 86400000)), end: today() };
      savePer(); return reload();
    }
    const go = t.closest("[data-go]");
    if (go && go.closest("#fin-ov")) return goTab(go.dataset.go);
    if (t.dataset.finBy) { BY = t.dataset.finBy; return reload(); }
    if (t.dataset.finRc) { RC_VIEW = t.dataset.finRc; return reload(); }
    if (t.dataset.finOrder && window.OPS && OPS.openOrder) { OPS.openOrder(+t.dataset.finOrder); return; }
    if (t.dataset.finDelbatch) {
      if (!confirm(Z("删除这次导入的结算数据？对应订单的到账金额会清掉。", "ลบข้อมูลการนำเข้านี้? ยอดที่ได้รับของคำสั่งซื้อจะถูกล้าง"))) return;
      try { await api(`/api/fin/settle/batches/${t.dataset.finDelbatch}`, { method: "DELETE" }); reload(); } catch (err) { toast(err.message, true); }
      return;
    }
    if (t.id === "fin-st-go" && STP) {
      const mapping = {};
      document.querySelectorAll("[data-fin-map]").forEach((s) => { if (s.value !== "") mapping[s.dataset.finMap] = +s.value; });
      await busy(t, async () => {
        const r = await api("/api/fin/settle/import", { json: { token: STP.token, mapping, platform: $("#fin-st-plat").value, shop: $("#fin-st-shop").value.trim() } });
        toast(Z(`导入 ${r.new_rows} 行（重复 ${r.dup_rows} 行跳过），${r.orders} 个订单，对上 ${r.matched} 个`, `นำเข้า ${r.new_rows} แถว (ซ้ำ ${r.dup_rows}) ${r.orders} คำสั่งซื้อ จับคู่ได้ ${r.matched}`), false, 8000);
        STP = null; reload();
      });
      return;
    }
    if (t.id === "fb-save") {
      const body = { direction: $("#fb-dir").value, day: $("#fb-day").value, category: $("#fb-cat").value, amount: $("#fb-amt").value,
        vat: $("#fb-vat") ? $("#fb-vat").value : 0, tax_invoice: $("#fb-inv") ? $("#fb-inv").checked : false,
        payee: $("#fb-payee").value.trim(), method: $("#fb-method").value, note: $("#fb-note").value.trim() };
      await busy(t, async () => {
        const r = await api("/api/fin/expenses", { json: body });
        const f = $("#fb-file").files[0];
        if (f) { const fd = new FormData(); fd.append("file", f); await api(`/api/fin/expenses/${r.row.id}/receipt`, { method: "POST", body: fd }); }
        toast(Z("已记账", "บันทึกแล้ว"));
        reload();
      });
      return;
    }
    if (t.dataset.fbDel) {
      if (!confirm(Z("删除这条记录？", "ลบรายการนี้?"))) return;
      try { await api(`/api/fin/expenses/${t.dataset.fbDel}`, { method: "DELETE" }); reload(); } catch (err) { toast(err.message, true); }
    }
  });

  window.FIN = { show, reload, PLAT, m, n0, pct };
})();
