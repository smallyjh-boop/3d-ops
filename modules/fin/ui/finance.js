"use strict";
// 电商财务（v2.21；v2.49 菜单 8 个并成 5 个、统一页面组件 UX）：总览（损益 + 利润分析图）· 订单利润（orders.js）· 平台对账（settle.js）·
// 收支与现金流（两个页签）· 税务。只有老板能看。界面文字用 Z(中文, 泰文) 直接写两种语言。
// 页面结构统一：顶部数字卡片 → 图表 → 明细表；说明收进「?」。
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const n0 = (v) => (v == null ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 }));
  const m = (v) => (v == null ? "—" : (v < 0 ? "-฿" : "฿") + Math.abs(Number(v)).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 }));
  const mk = (v) => (v == null ? "—" : Math.abs(v) >= 100000 ? (v < 0 ? "-฿" : "฿") + (Math.abs(v) / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 }) + "k" : m(Math.round(v)));
  const pct = (v) => (v == null ? "—" : `${v}%`);
  const cls = (v) => (v == null ? "" : v < 0 ? "bad" : "");
  const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;   // 本地日期（不用 UTC，泰国早上 7 点前会差一天）
  const today = () => ymd(new Date());
  const thisMonth = () => today().slice(0, 7);
  const PLAT = { lazada: "Lazada", shopee: "Shopee", tiktok: "TikTok", manual: Z("私下成交", "ขายตรง"), other: Z("其他", "อื่นๆ") };

  let PER = { mode: "month", month: thisMonth(), start: "", end: "" };
  let META = null, BY = "platform", CUR = "", BOOK_TAB = "book";
  try { const s = JSON.parse(localStorage.getItem("fin_per") || "null"); if (s && s.mode) PER = s; } catch { /* 忽略 */ }
  try { BOOK_TAB = localStorage.getItem("fin_book_tab") || "book"; } catch { /* 忽略 */ }

  const q = () => (PER.mode === "range" && PER.start ? `start=${PER.start}&end=${PER.end || today()}` : `month=${PER.month || thisMonth()}`);
  const TABS = { fin_orders: "fin-od", fin_overview: "fin-ov", fin_settle: "fin-st", fin_book: "fin-bk", fin_tax: "fin-tx" };
  // v2.49：旧菜单 → 新页面 + 页签（书签、首页卡片、别的模块里的链接还能用）
  const ALIAS = { fin_profit: ["fin_overview", () => { PROFIT_FOCUS = true; }], fin_cash: ["fin_book", () => { BOOK_TAB = "cash"; }],
    profit: ["fin_orders", () => { if (window.FIN_ORDERS) FIN_ORDERS.setGroup("day"); }] };
  let PROFIT_FOCUS = false;

  // 期间选择（放在页面头右边）
  function period(extra) {
    const mo = [];
    const d = new Date(); d.setDate(1);
    for (let i = 0; i < 18; i++) { mo.push(ymd(d).slice(0, 7)); d.setMonth(d.getMonth() - 1); }
    return `<span class="row gap wrap fin-bar">
      <select data-fin-month>${mo.map((x) => `<option ${PER.mode === "month" && PER.month === x ? "selected" : ""}>${x}</option>`).join("")}
        <option value="__range" ${PER.mode === "range" ? "selected" : ""}>${Z("自定义日期…", "กำหนดวันที่เอง…")}</option></select>
      <span class="${PER.mode === "range" ? "row gap" : "hidden"}" data-fin-range><input type="date" data-fin-start value="${PER.start || ""}"> ~ <input type="date" data-fin-end value="${PER.end || ""}">
        <button class="mini" data-fin-apply>${Z("确定", "ตกลง")}</button></span>
      <button class="mini" data-fin-q="ytd">${Z("今年", "ปีนี้")}</button><button class="mini" data-fin-q="30">${Z("近 30 天", "30 วัน")}</button>
      ${extra || ""}</span>`;
  }
  const exportBtn = () => `<a class="btn mini-btn" href="/api/fin/export?${q()}" download title="${Z("损益表、按平台 / 店铺 / 产品 / SKU / 日、收支明细、现金流", "งบกำไรขาดทุน แยกตามแพลตฟอร์ม/ร้าน/สินค้า/SKU/วัน รายรับรายจ่าย กระแสเงินสด")}">⬇ ${Z("导出 Excel（给会计）", "ส่งออก Excel (ให้นักบัญชี)")}</a>`;
  const head = (title, help, extra) => UX.head(title, period(extra), help);

  async function show(name) {
    if (ALIAS[name]) {
      const [real, fn] = ALIAS[name];
      fn();
      if (typeof showTab === "function") return showTab(real);     // 菜单高亮、地址栏都换成新页面
      name = real;
    }
    if (!TABS[name]) return;
    CUR = name;
    const box = $("#" + TABS[name]);
    if (!box) return;
    try {
      if (!META) META = await api("/api/fin/meta");
      if (name === "fin_orders") return window.FIN_ORDERS && await FIN_ORDERS.render(box);
      if (name === "fin_settle") return window.FIN_SETTLE && await FIN_SETTLE.render(box);
      if (name === "fin_overview") return await overview(box);
      if (name === "fin_book") return await bookCash(box);
      if (name === "fin_tax") return await tax(box);
    } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
  }
  const reload = () => show(CUR);

  // ---------------- 总览：数字卡片 → 图表（每天、按平台、利润分析）→ 损益表 ----------------
  function chg(v, good = true) {
    if (v == null) return "";
    const up = v >= 0;
    return `<span class="${(up === good) ? "ok" : "bad"}">${up ? "▲" : "▼"} ${Math.abs(v)}%</span>`;
  }
  function chart(days) {
    if (!days.length) return "";
    const W = 640, H = 150, P = 4;
    const mx = Math.max(1, ...days.map((d) => Math.max(d.revenue, 0)));
    const mn = Math.min(0, ...days.map((d) => d.profit));
    const span = mx - mn || 1;
    const bw = (W - P * 2) / days.length;
    const y = (v) => H - P - ((v - mn) / span) * (H - P * 2);
    const bars = days.map((d, i) => `<rect x="${P + i * bw + bw * 0.15}" y="${y(Math.max(0, d.revenue))}" width="${bw * 0.7}" height="${Math.max(1, y(0) - y(Math.max(0, d.revenue)))}" class="fc-rev"><title>${d.day} ${Z("收入", "รายได้")} ${m(d.revenue)} · ${Z("利润", "กำไร")} ${m(d.profit)}</title></rect>`).join("");
    const line = days.map((d, i) => `${P + i * bw + bw / 2},${y(d.profit)}`).join(" ");
    return `<svg viewBox="0 0 ${W} ${H}" class="fin-chart" preserveAspectRatio="none"><line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" class="fc-zero"/>${bars}
      <polyline points="${line}" class="fc-profit"/></svg>
      <div class="small muted"><span class="fc-key fc-rev"></span>${Z("每日收入", "รายได้รายวัน")} <span class="fc-key fc-profit"></span>${Z("每日订单利润", "กำไรจากคำสั่งซื้อรายวัน")} · ${days[0].day} ~ ${days[days.length - 1].day}</div>`;
  }
  function plTable(lines) {
    return `<table class="grid fin-pl"><tbody>${lines.map((l) => `<tr class="lv${l.level}"><td>${esc(TH() ? l.th : l.zh)}${l.est ? ` <span class="warn small">${Z("估", "ประมาณ")}</span>` : ""}</td>
      <td class="num ${cls(l.amount)}">${m(l.amount)}</td><td class="muted small">${esc(TH() ? (l.note_th || "") : (l.note || ""))}</td></tr>`).join("")}</tbody></table>`;
  }
  // 「平台 · 店铺」：平台代码换成名字，没写店铺的按界面语言
  const shopLabel = (k) => { const [p, ...r] = String(k || "").split(" · "); const sh = r.join(" · "); return `${PLAT[p] || p}${sh ? " · " + (sh === "（没写店铺）" ? Z("（没写店铺）", "(ไม่ระบุร้าน)") : sh) : ""}`; };
  const DIMS = { platform: ["平台", "แพลตฟอร์ม"], shop: ["店铺", "ร้านค้า"], product: ["产品", "สินค้า"], sku: ["SKU", "SKU"], month: ["按月", "รายเดือน"] };
  function profitBars(rows, by) {
    const top = rows.slice().sort((a, b) => b.profit - a.profit);
    const show = top.length > 14 ? top.slice(0, 10).concat(top.slice(-4)) : top;
    return UX.bars(show.map((r) => ({ label: by === "platform" ? (PLAT[r.key] || r.key) : by === "shop" ? shopLabel(r.key) : (r.name && by !== "month" ? `${r.key} ${r.name}` : r.key),
      raw: (by === "product" || by === "sku") && !/^（/.test(r.key),
      value: r.profit, text: `${m(r.profit)} · ${pct(r.margin)}`, tone: r.profit < 0 ? "bad" : r.margin != null && r.margin < 15 ? "warn" : "ok" })),
    { empty: Z("这段时间没有订单", "ไม่มีคำสั่งซื้อในช่วงนี้") });
  }
  async function overview(box) {
    const [r, pl, br] = await Promise.all([api(`/api/fin/overview?${q()}`), api(`/api/fin/pl?${q()}`), api(`/api/fin/breakdown?by=${BY}&${q()}`)]);
    const s = r.summary, c = r.change;
    const warn = [];
    if (s.fee_estimated) warn.push(Z(`平台扣费有 ${m(s.fee_estimated)} 是按扣点估算的（平台还没结算这些订单，或者没导入结算报表）。`, `ค่าธรรมเนียม ${m(s.fee_estimated)} เป็นการประมาณ (แพลตฟอร์มยังไม่สรุปยอดหรือยังไม่ได้นำเข้ารายงาน)`));
    if (s.missing_data_orders) warn.push(Z(`${s.missing_data_orders} 单商品没对上 SKU 或缺克数，成本偏低。`, `${s.missing_data_orders} คำสั่งซื้อจับคู่ SKU ไม่ได้หรือไม่มีกรัม ต้นทุนจะต่ำกว่าจริง`));
    if (s.fixed_estimated) warn.push(Z("有几项固定费用（房租、人工、折旧、维修）本期没记账，按设置估算了。", "ค่าใช้จ่ายคงที่บางรายการ (ค่าเช่า ค่าแรง ค่าเสื่อม ค่าซ่อม) งวดนี้ยังไม่ได้บันทึก จึงประมาณจากการตั้งค่า"));
    const vs = r.custom ? Z("和前一段同样长的期间比", "เทียบกับช่วงก่อนหน้า") : Z("和上个月比", "เทียบกับเดือนก่อน");
    const days = r.days || [];
    box.innerHTML = head(Z("财务总览", "ภาพรวมการเงิน"), Z(`${r.month}，按下单日期算（权责发生制）。箭头是${vs}。`, `${r.month} ตามวันที่สั่งซื้อ ลูกศร${vs}`), exportBtn()) +
      UX.kpis([
        { label: Z("销售收入", "ยอดขาย"), value: m(s.revenue), sub: chg(c.revenue), subHtml: true, spark: days.map((d) => d.revenue) },
        { label: Z("毛利", "กำไรขั้นต้น"), value: m(s.gross), sub: `${pct(s.gross_margin)} ${chg(c.gross)}`, subHtml: true },
        { label: Z("净利润（税前）", "กำไรสุทธิ (ก่อนภาษี)"), value: m(s.net), sub: `${pct(s.net_margin)} ${chg(c.net)}`, subHtml: true, tone: s.net < 0 ? "bad" : "ok",
          help: Z("收入 − 平台扣费 − 生产成本 − 支出 − 固定费用。详细看下面的损益表。", "รายได้ − ค่าธรรมเนียม − ต้นทุนผลิต − ค่าใช้จ่าย − ค่าใช้จ่ายคงที่ ดูงบกำไรขาดทุนด้านล่าง") },
        { label: Z("订单 / 客单价", "คำสั่งซื้อ / ต่อบิล"), value: `${n0(s.orders)} <small>/ ${m(s.aov)}</small>`, html: true, sub: chg(c.orders), subHtml: true, go: "tab:fin_orders" },
        { label: Z("平台扣费率", "อัตราค่าธรรมเนียม"), value: pct(s.fee_rate), sub: Z("点开看平台对账", "ดูการกระทบยอด"), go: "tab:fin_settle" },
        { label: Z("现金净流入", "เงินสดสุทธิ"), value: m(r.cash.net), tone: r.cash.net < 0 ? "warn" : "", go: "tab:fin_book" },
        { label: Z("对账异常", "รายการผิดปกติ"), value: n0(r.issues || 0), tone: r.issues ? "bad" : "ok", go: "tab:fin_settle",
          sub: r.reconcile && r.reconcile.unpaid_amount ? Z(`超时未回款 ${m(r.reconcile.unpaid_amount)}`, `ค้างรับ ${m(r.reconcile.unpaid_amount)}`) : Z("没有", "ไม่มี") },
      ]) +
      (warn.length ? `<div class="card warn-box small fin-warn">${warn.map((w) => `<div>⚠ ${esc(w)}</div>`).join("")}</div>` : "") +
      `<div class="lanes two">
        ${UX.card({ title: Z("每天的收入和利润", "รายได้และกำไรรายวัน"), body: chart(days) || UX.empty(Z("这段时间还没有订单", "ยังไม่มีคำสั่งซื้อ")) })}
        ${UX.card({ title: Z("按平台", "ตามแพลตฟอร์ม"), help: Z("条的长度 = 收入；右边是订单利润和利润率", "ความยาว = รายได้ ด้านขวาคือกำไรและอัตรากำไร"),
          body: UX.bars((r.platforms || []).map((p) => ({ label: PLAT[p.key] || p.key, value: p.revenue, text: `${m(p.revenue)} · ${Z("利润", "กำไร")} ${m(p.profit)}`, tone: p.profit < 0 ? "bad" : "" })),
            { empty: Z("没有订单", "ไม่มีคำสั่งซื้อ") }) })}
      </div>` +
      UX.card({ id: "fin-pa", title: Z("利润分析", "วิเคราะห์กำไร"),
        help: Z("订单利润 = 收入 − 平台扣费 − 生产成本（材料、机时分摊、包材、损耗），没扣广告费等支出。产品 / SKU 按商品金额比例分摊订单的扣费和成本。绿 = 利润率 15% 以上，黄 = 低于 15%，红 = 亏本。每单明细在「订单利润」。",
          "กำไรจากคำสั่งซื้อ = รายได้ − ค่าธรรมเนียม − ต้นทุนผลิต ยังไม่หักค่าโฆษณา เขียว = อัตรากำไร ≥ 15% เหลือง = ต่ำกว่า 15% แดง = ขาดทุน รายละเอียดดูที่「กำไรรายคำสั่งซื้อ」"),
        right: `<span class="muted small">${Z("订单利润合计", "กำไรรวม")} <b class="${cls(br.total.profit)}">${m(br.total.profit)}</b> · ${pct(br.total.margin)}</span>`,
        body: UX.tabs(Object.entries(DIMS).map(([k, v]) => [k, Z(v[0], v[1])]), BY, "fin-by") + profitBars(br.rows || [], BY) +
          `<p class="small" style="margin:8px 0 0"><a href="#" data-fin-goorders="${BY}">${Z("看完整表格 →", "ดูตารางเต็ม →")}</a></p>` }) +
      UX.card({ title: Z("损益表", "งบกำไรขาดทุน") + ` · ${pl.period}`, help: Z("生产成本只算材料、电费、包材、失败损耗；房租、人工、折旧算固定费用（记了账用记的，没记按设置估算），不会重复算。",
          "ต้นทุนการผลิตนับเฉพาะวัสดุ ค่าไฟ วัสดุแพ็ค ของเสีย; ค่าเช่า ค่าแรง ค่าเสื่อมนับเป็นค่าใช้จ่ายคงที่ ไม่นับซ้ำ"),
        body: plTable(pl.lines) + ((s.inventory_used || s.wht) ? `<p class="muted small">${s.inventory_used ? Z(`本期库存实际消耗（材料、包材等）${m(s.inventory_used)}，可以和上面的材料、包材对照。`, `สต็อกที่ใช้จริงงวดนี้ ${m(s.inventory_used)}`) : ""}
          ${s.wht ? Z(` 平台代扣税 ${m(s.wht)}（年底报所得税可以抵扣）。`, ` ภาษีหัก ณ ที่จ่ายโดยแพลตฟอร์ม ${m(s.wht)}`) : ""}</p>` : "") });
    if (PROFIT_FOCUS) { PROFIT_FOCUS = false; const el = $("#fin-pa"); if (el && el.scrollIntoView) el.scrollIntoView({ block: "start" }); }
  }

  // ---------------- 收支与现金流（两个页签）----------------
  async function bookCash(box) {
    const tabs = UX.tabs([["book", Z("收支记账", "บันทึกรายรับรายจ่าย")], ["cash", Z("现金流", "กระแสเงินสด")]], BOOK_TAB, "fin-book");
    const h = head(Z("收支与现金流", "รายรับรายจ่ายและกระแสเงินสด"),
      BOOK_TAB === "cash" ? Z("现金流按钱实际进出的日期算：平台回款（结算日期）、其他收入、老板投入、采购付款、支出。", "กระแสเงินสดตามวันที่เงินเข้าออกจริง")
        : Z("采购的付款在「采购」里记，会自动算进现金流，这里不用再记。房租、人工、设备折旧记在这里后，损益表就用实际数，不再按设置估算。", "การจ่ายค่าซื้อของบันทึกใน「จัดซื้อ」 จะนับในกระแสเงินสดอัตโนมัติ ไม่ต้องบันทึกซ้ำ"), exportBtn());
    return BOOK_TAB === "cash" ? cash(box, h + tabs) : book(box, h + tabs);
  }
  let BOOK_FORM = false;
  async function book(box, top) {
    const r = await api(`/api/fin/expenses?${q()}`);
    const cats = META.categories, vat = META.settings.vat_on;
    const outs = r.by_category.filter((x) => x.direction === "out");
    box.innerHTML = top +
      UX.kpis([
        { label: Z("支出合计", "รายจ่ายรวม"), value: m(r.total_out), tone: r.total_out ? "" : "" },
        { label: Z("收入合计", "รายรับรวม"), value: m(r.total_in) },
        { label: Z("笔数", "จำนวนรายการ"), value: n0(r.rows.length) },
        { label: Z("没票据的", "ไม่มีใบเสร็จ"), value: n0(r.rows.filter((x) => !x.has_receipt && x.direction === "out").length), tone: r.rows.some((x) => !x.has_receipt && x.direction === "out") ? "warn" : "" },
      ]) +
      `<div class="lanes two">${UX.card({ title: Z("支出按分类", "รายจ่ายตามหมวด"), body: UX.bars(outs.slice(0, 10).map((c) => ({ label: c.category, value: c.amount, text: m(c.amount) })), { empty: Z("这个期间还没有支出", "งวดนี้ยังไม่มีรายจ่าย") }) })}
      ${UX.card({ title: Z("记一笔", "บันทึกรายการ"), right: `<button class="mini" data-fb-toggle>${BOOK_FORM ? Z("收起", "ซ่อน") : "＋ " + Z("记一笔", "บันทึก")}</button>`,
        body: BOOK_FORM ? `<div class="form4">
          <label>${Z("方向", "ประเภท")}<select id="fb-dir"><option value="out">${Z("支出", "รายจ่าย")}</option><option value="in">${Z("收入", "รายรับ")}</option></select></label>
          <label>${Z("日期", "วันที่")}<input type="date" id="fb-day" value="${today()}"></label>
          <label>${Z("分类", "หมวด")}<select id="fb-cat">${cats.out.map((c) => `<option>${esc(c)}</option>`).join("")}</select></label>
          <label>${Z("金额（฿，含税）", "จำนวนเงิน (฿ รวม VAT)")}<input type="number" step="any" id="fb-amt"></label>
          ${vat ? `<label>${Z("其中 VAT", "ในนี้ VAT")}<input type="number" step="any" id="fb-vat" placeholder="${Z("有税票才填", "กรอกเมื่อมีใบกำกับภาษี")}"></label>
          <label class="row"><input type="checkbox" id="fb-inv"> ${Z("有正式税票", "มีใบกำกับภาษีเต็มรูป")}</label>` : ""}
          <label>${Z("收款方 / 付款方", "ผู้รับ/ผู้จ่าย")}<input id="fb-payee" data-notr></label>
          <label>${Z("付款方式", "วิธีชำระ")}<select id="fb-method">${["transfer", "cash", "card", "platform", "other"].concat(Object.keys(cats.methods)).filter((k, i, a) => cats.methods[k] && a.indexOf(k) === i).map((k) => `<option value="${k}">${esc(cats.methods[k])}</option>`).join("")}</select></label>
          <label>${Z("备注", "หมายเหตุ")}<input id="fb-note" data-notr></label>
          <label>${Z("票据（照片 / PDF，可空）", "ใบเสร็จ (รูป/PDF เว้นได้)")}<input type="file" id="fb-file" accept="image/*,.pdf"></label>
        </div><button class="primary" id="fb-save">${Z("记账", "บันทึก")}</button>`
          : `<p class="muted small">${Z("广告费、房租、工资、水电、维修、老板投入……都在这里记，可以附票据照片。", "ค่าโฆษณา ค่าเช่า ค่าแรง ค่าน้ำไฟ ค่าซ่อม เงินลงทุนเจ้าของ… บันทึกที่นี่ แนบรูปใบเสร็จได้")}</p>` })}</div>` +
      UX.card({ title: Z("明细", "รายการ"), body: r.rows.length ? `<div class="fin-scroll"><table class="grid small"><thead><tr><th>${Z("日期", "วันที่")}</th><th>${Z("分类", "หมวด")}</th><th class="num">${Z("金额", "จำนวนเงิน")}</th>${vat ? "<th>VAT</th>" : ""}
        <th>${Z("收款方", "ผู้รับ")}</th><th>${Z("方式", "วิธี")}</th><th>${Z("备注", "หมายเหตุ")}</th><th>${Z("票据", "ใบเสร็จ")}</th><th></th></tr></thead><tbody>` +
        r.rows.map((x) => `<tr><td class="nowrap">${esc(x.day)}</td><td>${x.direction === "in" ? `<span class="ok">${Z("收", "รับ")}</span> ` : ""}${esc(x.category)}</td>
          <td class="num ${x.direction === "in" ? "ok" : ""}">${x.direction === "in" ? "+" : ""}${m(x.amount)}</td>${vat ? `<td class="num">${x.vat ? m(x.vat) : ""}${x.tax_invoice ? " 🧾" : ""}</td>` : ""}
          <td data-notr>${esc(x.payee || "")}</td><td class="small">${esc(cats.methods[x.method] || "")}</td><td class="small" data-notr>${esc(x.note || "")}</td>
          <td>${x.has_receipt ? `<a href="/api/fin/expenses/${x.id}/receipt" target="_blank">📎</a>` : `<label class="filebtn mini">＋<input type="file" data-fb-rcpt="${x.id}" accept="image/*,.pdf" hidden></label>`}</td>
          <td><button class="mini danger" data-fb-del="${x.id}">${Z("删除", "ลบ")}</button></td></tr>`).join("") + "</tbody></table></div>"
        : UX.empty(Z("这个期间还没有记账", "งวดนี้ยังไม่มีรายการ")) });
  }
  async function cash(box, top) {
    const r = await api(`/api/fin/cashflow?${q()}`);
    const t = r.total;
    box.innerHTML = top +
      UX.kpis([
        { label: Z("平台回款", "เงินจากแพลตฟอร์ม"), value: m(t.settle_in), tone: "ok", go: "tab:fin_settle",
          help: Z("平台打到卡上的钱（按结算日期）：Lazada 接口自动拉，Shopee / TikTok 在「平台对账」导入报表。", "เงินที่แพลตฟอร์มโอน (ตามวันที่สรุปยอด)") },
        { label: Z("其他收入", "รายรับอื่น"), value: m(t.other_in) },
        { label: Z("老板投入", "เงินลงทุนเจ้าของ"), value: m(t.capital_in) },
        { label: Z("采购付款", "จ่ายค่าซื้อของ"), value: m(-t.purchase_out) },
        { label: Z("支出", "รายจ่าย"), value: m(-t.expense_out) },
        { label: Z("净流入", "เงินสดสุทธิ"), value: m(t.net), tone: t.net < 0 ? "bad" : "ok" },
      ]) +
      (r.has_settlements ? "" : `<p class="muted small">⚠ ${Z("还没有平台回款记录：Lazada 接通后自动有；Shopee / TikTok 到「平台对账」导入报表。", "ยังไม่มีข้อมูลเงินจากแพลตฟอร์ม")}</p>`) +
      UX.card({ title: Z("每天净流入", "เงินสดสุทธิรายวัน"), body: UX.columns(r.rows.map((x) => ({ label: x.key, value: x.net, text: m(x.net), tone: x.net < 0 ? "bad" : "ok" })),
        { h: 110, from: r.rows.length ? r.rows[0].key : "", to: r.rows.length ? r.rows[r.rows.length - 1].key : "", empty: Z("这个期间没有现金进出记录", "งวดนี้ไม่มีรายการเงินเข้าออก") }) }) +
      UX.card({ title: Z("明细", "รายการ"), body: r.rows.length ? `<div class="fin-scroll"><table class="grid small"><thead><tr><th>${r.monthly ? Z("月份", "เดือน") : Z("日期", "วันที่")}</th><th class="num">${Z("平台回款", "เงินจากแพลตฟอร์ม")}</th><th class="num">${Z("其他收入", "รายรับอื่น")}</th>
        <th class="num">${Z("老板投入", "เงินลงทุนเจ้าของ")}</th><th class="num">${Z("采购付款", "จ่ายค่าซื้อของ")}</th><th class="num">${Z("支出", "รายจ่าย")}</th><th class="num">${Z("净流入", "สุทธิ")}</th><th class="num">${Z("累计", "สะสม")}</th></tr></thead><tbody>` +
        r.rows.map((x) => `<tr><td>${esc(x.key)}</td><td class="num">${x.settle_in ? m(x.settle_in) : ""}</td><td class="num">${x.other_in ? m(x.other_in) : ""}</td><td class="num">${x.capital_in ? m(x.capital_in) : ""}</td>
          <td class="num">${x.purchase_out ? m(-x.purchase_out) : ""}</td><td class="num">${x.expense_out ? m(-x.expense_out) : ""}</td><td class="num ${cls(x.net)}">${m(x.net)}</td><td class="num ${cls(x.running)}">${m(x.running)}</td></tr>`).join("") +
        "</tbody></table></div>" : UX.empty(Z("这个期间没有现金进出记录", "งวดนี้ไม่มีรายการเงินเข้าออก")) });
  }

  // ---------------- 税务 ----------------
  async function tax(box) {
    const r = await api(`/api/fin/tax?${q()}`);
    const t = r.total;
    box.innerHTML = head(Z("税务", "ภาษี"), Z("这里是估算，以会计核对为准。", "ตัวเลขเป็นการประมาณ ให้นักบัญชีตรวจสอบ"), exportBtn()) +
      UX.kpis([
        r.vat_on ? { label: Z("VAT 应缴", "VAT ต้องชำระ"), value: m(t.payable), tone: t.payable > 0 ? "warn" : "ok",
          help: Z("每月 15 号前报 ภ.พ.30（网上申报 23 号前）。销项税 − 进项税（支出 + 平台费用）。", "ยื่น ภ.พ.30 ภายในวันที่ 15 ของเดือนถัดไป (ออนไลน์ภายในวันที่ 23)") }
          : { label: Z("VAT", "VAT"), value: Z("没注册", "ยังไม่จด"), sub: Z("设置 → 财务 里可以打开", "เปิดได้ที่ ตั้งค่า → การเงิน") },
        r.vat_on ? { label: Z("销项税", "ภาษีขาย"), value: m(t.out_vat) } : null,
        r.vat_on ? { label: Z("进项税", "ภาษีซื้อ"), value: m((t.in_vat_expenses || 0) + (t.in_vat_fees || 0)) } : null,
        { label: Z("平台代扣税（WHT）", "ภาษีหัก ณ ที่จ่าย"), value: m(t.wht), help: Z("平台从回款里代扣的所得税（来自结算明细的 WHT）。平台会开代扣凭证（50 ทวิ），年底报所得税时可以抵扣，记得在平台后台下载保存。",
          "ภาษีที่แพลตฟอร์มหักจากยอดโอน ใช้หักภาษีเงินได้ตอนสิ้นปีได้ อย่าลืมดาวน์โหลดหนังสือรับรอง 50 ทวิ") },
        { label: Z(`${r.year} 年销售额`, `ยอดขายปี ${r.year}`), value: m(r.year_sales), sub: r.vat_on ? "" : Z("一年超过 180 万铢要注册 VAT", "เกิน 1.8 ล้านบาทต่อปีต้องจด VAT") },
      ]) +
      (r.vat_on ? "" : UX.card({ title: Z("离 VAT 注册门槛还有多远", "ใกล้เกณฑ์จด VAT แค่ไหน"), body: UX.meter({ label: Z("今年销售额", "ยอดขายปีนี้"), value: r.year_sales, target: r.vat_threshold, better: "low",
        text: `${(r.year_sales / r.vat_threshold * 100).toFixed(1)}%`, targetText: "฿1,800,000" }) })) +
      (r.vat_on ? UX.card({ title: `VAT（${(r.vat_rate * 100).toFixed(0)}%）`, body: `<div class="fin-scroll"><table class="grid small"><thead><tr><th>${Z("月份", "เดือน")}</th><th class="num">${Z("销售额", "ยอดขาย")}</th>
          <th class="num">${Z("销项税", "ภาษีขาย")}</th><th class="num">${Z("进项税（支出）", "ภาษีซื้อ (รายจ่าย)")}</th><th class="num">${Z("进项税（平台费用）", "ภาษีซื้อ (ค่าธรรมเนียม)")}</th><th class="num">${Z("应缴", "ต้องชำระ")}</th></tr></thead><tbody>` +
          r.months.map((x) => `<tr><td>${x.month}</td><td class="num">${m(x.sales)}</td><td class="num">${m(x.out_vat)}</td><td class="num">${m(x.in_vat_expenses)}</td><td class="num">${m(x.in_vat_fees)}</td>
            <td class="num ${x.payable > 0 ? "warn" : ""}"><b>${m(x.payable)}</b></td></tr>`).join("") +
          `<tr class="lv2"><td>${Z("合计", "รวม")}</td><td class="num">${m(t.sales)}</td><td class="num">${m(t.out_vat)}</td><td class="num">${m(t.in_vat_expenses)}</td><td class="num">${m(t.in_vat_fees)}</td><td class="num"><b>${m(t.payable)}</b></td></tr></tbody></table></div>
          ${r.missing_invoice.length ? `<p class="small warn">${Z(`${r.missing_invoice.length} 笔 1000 铢以上的支出没有勾「有正式税票」，进项税抵扣不了：`, `${r.missing_invoice.length} รายการเกิน 1000 บาทยังไม่ได้ติ๊ก「มีใบกำกับภาษี」:`)}
            ${r.missing_invoice.slice(0, 10).map((x) => `${esc(x.day)} ${esc(x.category)} ${m(x.amount)}`).join("；")}</p>` : ""}` }) : "") +
      UX.card({ title: Z("平台代扣税（WHT）按月", "ภาษีหัก ณ ที่จ่ายรายเดือน"), body: r.months.some((x) => x.wht) ? `<table class="grid small"><thead><tr><th>${Z("月份", "เดือน")}</th><th class="num">${Z("代扣合计", "รวม")}</th><th>${Z("按平台", "ตามแพลตฟอร์ม")}</th></tr></thead><tbody>` +
        r.months.map((x) => `<tr><td>${x.month}</td><td class="num">${m(x.wht)}</td><td class="small">${Object.entries(x.wht_by_platform).map(([k, v]) => `${esc(PLAT[k] || k)} ${m(v)}`).join("、")}</td></tr>`).join("") +
        "</tbody></table>" : UX.empty(Z("这个期间没有代扣税记录", "งวดนี้ไม่มีภาษีหัก ณ ที่จ่าย")) });
  }

  // ---------------- 事件 ----------------
  function savePer() { try { localStorage.setItem("fin_per", JSON.stringify(PER)); } catch { /* 忽略 */ } }
  const ROOTS = "#fin-ov,#fin-od,#fin-st,#fin-bk,#fin-tx";
  document.addEventListener("change", async (e) => {
    const t = e.target;
    if (!t.closest || !t.closest(ROOTS)) return;
    if (t.matches("[data-fin-month]")) {
      if (t.value === "__range") { PER.mode = "range"; PER.start = PER.start || `${thisMonth()}-01`; PER.end = PER.end || today(); }
      else { PER = { mode: "month", month: t.value, start: "", end: "" }; }
      savePer(); return reload();
    }
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
    if (!t.closest || !t.closest(ROOTS)) return;
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
    const tab = t.closest("[data-ux-tab]");
    const grp = tab && tab.closest("[data-ux-group]");
    if (grp && grp.dataset.uxGroup === "fin-by") { BY = tab.dataset.uxTab; return reload(); }
    if (grp && grp.dataset.uxGroup === "fin-book") { BOOK_TAB = tab.dataset.uxTab; try { localStorage.setItem("fin_book_tab", BOOK_TAB); } catch { /* 忽略 */ } return reload(); }
    if (t.dataset.finGoorders) { e.preventDefault(); if (window.FIN_ORDERS) FIN_ORDERS.setGroup(t.dataset.finGoorders === "month" ? "day" : t.dataset.finGoorders === "product" ? "sku" : t.dataset.finGoorders); return goTab("fin_orders"); }
    if (t.dataset.fbToggle !== undefined) { BOOK_FORM = !BOOK_FORM; return reload(); }
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

  window.FIN = { show, reload, PLAT, shopLabel, m, mk, n0, pct, cls, Z, TH, q, period, exportBtn, head, meta: () => META, today };
})();
