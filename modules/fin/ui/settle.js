"use strict";
// 财务 → 平台对账（v2.49 自动化）：顶部每个平台的数据状态（Lazada 接口自动 / Shopee、TikTok 要导入）→ 数字卡片 → 回款进度图 →
// 问题页签（扣费比预计多 / 超时未回款 / 平台有但系统没有 / 系统有但平台没结算）→ 每单可展开看费用拆分、标「已核对」→ 导入记录（收起）。
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  let PSEL = "", VIEW = "", LAST = null, STP = null, PREV_HTML = "";
  const OPEN = {};          // 展开的订单：key → 明细（null = 加载中）
  try { PSEL = localStorage.getItem("fin_st_plat") || ""; } catch { /* 忽略 */ }
  const SRC = { api: ["接口", "API"], import: ["导入表格", "นำเข้าไฟล์"], order: ["订单表", "ตารางออเดอร์"], estimate: ["估算", "ประมาณ"] };
  const STATE_TONE = { paid: "ok-pill", settled: "", pending: "warn-pill", overdue: "bad-pill", unsettled: "bad-pill" };
  const HOWTO = {
    lazada: ["Lazada 卖家中心 → 财务（Finance）→ 账户对账单（Account Statement / Transaction Overview）→ 选日期 → 导出。每笔费用一行的表格可以直接导。",
      "Lazada Seller Center → การเงิน (Finance) → Account Statement / Transaction Overview → เลือกวันที่ → ส่งออก"],
    shopee: ["Shopee 卖家中心 → 我的收入（My Income）→ 已拨款（Released）→ 选日期 → 导出收入报表（Income Report）。每单一行，有「Total Released Amount」。",
      "Shopee Seller Centre → รายได้ของฉัน (My Income) → โอนแล้ว (Released) → เลือกวันที่ → ส่งออกรายงานรายได้"],
    tiktok: ["TikTok Shop 卖家中心 → 财务（Finance）→ 结算（Settlements / Statements）→ 选日期 → 导出。每单一行，有「Total settlement amount」。",
      "TikTok Shop Seller Center → การเงิน (Finance) → การชำระเงิน (Settlements) → เลือกวันที่ → ส่งออก"],
  };
  const keyOf = (x) => `${x.platform}|${x.order_no}`;

  function hm(t) {
    if (!t) return "—";
    const d = new Date(t * 1000);
    const s = fmtTime(t);
    return d.toDateString() === new Date().toDateString() ? s.slice(11, 16) : s.slice(5, 16);
  }
  function ago(days) {
    if (days == null) return Z("还没导入过", "ยังไม่เคยนำเข้า");
    if (days <= 0) return Z("今天导入过", "นำเข้าวันนี้");
    return Z(`上次导入 ${days} 天前`, `นำเข้าล่าสุด ${days} วันก่อน`);
  }

  function platCard(p) {
    const { PLAT } = window.FIN;
    const nm = PLAT[p.platform] || p.platform;
    const imp = `<label class="filebtn mini">📄 ${Z("导入报表", "นำเข้ารายงาน")}<input type="file" data-st-file="${p.platform}" accept=".xlsx,.xlsm,.csv,.txt" hidden></label>`;
    const how = UX.help(Z(HOWTO[p.platform][0], HOWTO[p.platform][1]) + "\n" + Z("每单一行（有到账金额）或每笔费用一行都可以，重复导入不会重复记。", "ใช้ได้ทั้งแบบหนึ่งแถวต่อคำสั่งซื้อและหนึ่งแถวต่อค่าธรรมเนียม นำเข้าซ้ำจะไม่นับซ้ำ"));
    if (p.mode === "api") {
      const errs = (p.errors || []).concat(((p.payout || {}).errors) || []);
      const bad = errs.length > 0;
      const pay = p.payout || {};
      return `<div class="fin-pcard ${bad ? "ux-bad" : "ux-ok"}">
        <div class="fin-pcard-h"><b>${esc(nm)}</b>${UX.dot(bad ? "bad" : "ok", bad ? Z("接口出错", "API ผิดพลาด") : Z("接口自动 ✓", "อัตโนมัติผ่าน API ✓"))}</div>
        <div class="small">${Z("上次", "ล่าสุด")} <b>${hm(p.last_ok)}</b> · ${p.next_at ? `${Z("下次", "ครั้งถัดไป")} ~${hm(p.next_at)}` : Z("只手动同步", "ซิงค์เองเท่านั้น")}</div>
        <div class="small muted">${Z(`结算单 ${pay.count || 0} 期`, `ใบสรุปยอด ${pay.count || 0} งวด`)}${pay.last_ok ? ` · ${hm(pay.last_ok)}` : ""}
          ${UX.help(Z("财务流水（每单的商品金额、佣金、手续费…）由「运营分析」每小时自动拉；结算单（GetPayoutStatus）告诉我们哪一期已经打款到卡上。", "รายการการเงินดึงอัตโนมัติทุกชั่วโมง ใบสรุปยอด (GetPayoutStatus) บอกว่างวดไหนโอนเงินแล้ว"))}</div>
        ${errs.slice(0, 2).map((x) => `<div class="small bad" data-notr>${esc(x.shop || "")}：${esc((TH() && x.hint_th) || x.hint || x.error)}</div>`).join("")}
        <div class="row gap"><button class="mini primary" data-st-sync>${Z("立即同步", "ซิงค์ตอนนี้")}</button>${imp}${how}</div></div>`;
    }
    const tone = p.stale ? "ux-warn" : p.last_import ? "ux-ok" : "";
    const note = p.platform === "lazada" ? (p.ops_off ? Z("「运营分析」模块关着，接口不拉流水", "โมดูลวิเคราะห์การขายปิดอยู่") : Z("还没对接店铺（设置 → 店铺对接），先导入表格", "ยังไม่ได้เชื่อมต่อร้าน นำเข้าไฟล์ไปก่อน")) : "";
    return `<div class="fin-pcard ${tone}">
      <div class="fin-pcard-h"><b>${esc(nm)}</b>${UX.dot(p.stale ? "warn" : p.last_import ? "ok" : "", Z("需要导入", "ต้องนำเข้า"))}</div>
      <div class="small">${ago(p.import_days)}${p.stale ? ` · <span class="warn">${Z(`超过 ${p.remind_days} 天`, `เกิน ${p.remind_days} วัน`)}</span>` : ""}</div>
      <div class="small muted">${note || (p.orders_60d ? Z(`近 60 天 ${p.orders_60d} 单`, `60 วัน ${p.orders_60d} คำสั่งซื้อ`) : Z("近 60 天没有订单", "60 วันไม่มีคำสั่งซื้อ"))}</div>
      <div class="row gap">${imp}${how}</div></div>`;
  }

  function moneyCell(v, cls = "") { return `<td class="num ${cls}">${window.FIN.m(v)}</td>`; }

  function stateName(r, s) { return (TH() ? r.state_th : r.state_zh)[s] || s; }
  function srcTag(s) { const v = SRC[s] || [s, s]; return `<span class="fin-src fin-src-${esc(s)}">${esc(Z(v[0], v[1]))}</span>`; }
  function checkBtn(x) {
    if (x.checked) return `<button class="mini fin-checked" data-st-check="0" data-plat="${esc(x.platform)}" data-no="${esc(x.order_no)}" title="${esc((x.checked.by || "") + " " + fmtTime(x.checked.at))}">✓ ${Z("已核对", "ตรวจแล้ว")}</button>`;
    if (x.state && !x.issue && !["overdue", "unsettled"].includes(x.state)) return "";      // 没问题的单不用核对
    return `<button class="mini" data-st-check="1" data-plat="${esc(x.platform)}" data-no="${esc(x.order_no)}" title="${Z("核对过了，不再算异常", "ตรวจแล้ว ไม่นับเป็นรายการผิดปกติ")}">${Z("标已核对", "ตรวจแล้ว")}</button>`;
  }

  function subRow(x, cols) {
    const { m } = window.FIN;
    const d = OPEN[keyOf(x)];
    if (d === undefined) return "";
    if (d === null) return `<tr class="fin-sub"><td colspan="${cols}"><span class="muted small">${Z("加载中…", "กำลังโหลด…")}</span></td></tr>`;
    const cats = (d.cats || []).filter((c) => c.cat !== "item");
    const item = (d.cats || []).find((c) => c.cat === "item");
    const of = d.order_fees || {};
    const ofL = [["commission", "佣金", "ค่าคอมมิชชั่น"], ["service_fee", "服务费", "ค่าบริการ"], ["payment_fee", "支付手续费", "ค่าธรรมเนียมชำระเงิน"],
      ["seller_discount", "店铺优惠", "ส่วนลดร้าน"], ["platform_fee", "平台费", "ค่าธรรมเนียม"]].filter(([k]) => of[k] != null);
    return `<tr class="fin-sub"><td colspan="${cols}"><div class="fin-brk">
      <div><div class="small muted">${Z("平台结算明细（按费用分类）", "รายละเอียดการสรุปยอด (ตามประเภท)")}</div>
        ${d.cats && d.cats.length ? `<table class="grid small fin-brk-t"><tbody>
          ${item ? `<tr><td>${esc(Z(item.zh, item.th))}</td><td class="num">${m(item.amount)}</td></tr>` : ""}
          ${cats.map((c) => `<tr><td>${esc(Z(c.zh, c.th))}</td><td class="num ${c.amount < 0 ? "bad" : ""}">${m(c.amount)}</td></tr>`).join("")}
          <tr class="lv2"><td><b>${Z("到账合计", "ยอดรับรวม")}</b></td><td class="num"><b>${m(d.net)}</b></td></tr>
          ${d.wht ? `<tr><td class="muted">${Z("其中代扣税 WHT", "ภาษีหัก ณ ที่จ่าย")}</td><td class="num muted">${m(d.wht)}</td></tr>` : ""}</tbody></table>`
          : UX.empty(Z("平台还没有这单的结算记录（扣费按扣点估算）", "ยังไม่มีข้อมูลการสรุปยอดของคำสั่งซื้อนี้"))}</div>
      <div><div class="small muted">${Z("订单表里的金额", "ยอดในตารางออเดอร์")}</div>
        <table class="grid small fin-brk-t"><tbody>
          <tr><td>${Z("订单金额", "ยอดสั่งซื้อ")}</td><td class="num">${m(d.revenue)}</td></tr>
          ${ofL.map(([k, zh, th]) => `<tr><td>${Z(zh, th)}</td><td class="num">${m(of[k])}</td></tr>`).join("")}
          <tr><td>${Z("预计到账", "ยอดที่คาด")}</td><td class="num">${m(x.expected)} <span class="muted small">(${Z("扣点", "อัตรา")} ${x.rate}%)</span></td></tr>
        </tbody></table>
        ${x.statement ? `<div class="small muted">${Z("结算单", "ใบสรุปยอด")} <span class="mono" data-notr>${esc(x.statement)}</span>${x.paid_at ? ` · ${Z("到账", "เงินเข้า")} ${esc(x.paid_at)}` : ""}</div>` : ""}
        ${d.lines && d.lines.length ? `<details class="small"><summary>${Z(`原始明细 ${d.lines.length} 行`, `รายการดิบ ${d.lines.length} แถว`)}</summary>
          <table class="grid small"><tbody>${d.lines.map((l) => `<tr><td class="nowrap">${esc(l.day || "")}</td><td data-notr>${esc(l.fee_name || "")}</td><td class="num">${m(l.amount)}</td><td>${srcTag(l.src)}</td></tr>`).join("")}</tbody></table></details>` : ""}
        ${d.order_id && window.OPS && OPS.openOrder ? `<button class="mini" data-st-order="${d.order_id}">${Z("打开订单", "เปิดคำสั่งซื้อ")}</button>` : ""}
      </div></div></td></tr>`;
  }

  function orderTable(r, rows, kind) {
    const { m, PLAT, pct } = window.FIN;
    if (!rows.length) return UX.empty(Z("没有", "ไม่มี"));
    const cols = 11;
    const last = kind === "diff" ? Z("少了", "ขาดไป") : kind === "unpaid" || kind === "unsettled" ? Z("已过天数", "ผ่านไป (วัน)") : Z("预计到账", "ยอดที่คาด");
    return `<div class="fin-scroll"><table class="grid small fin-st-t"><thead><tr><th></th><th>${Z("下单日", "วันสั่งซื้อ")}</th><th>${Z("平台 · 店铺", "แพลตฟอร์ม · ร้าน")}</th><th>${Z("订单号", "เลขคำสั่งซื้อ")}</th>
      <th class="num">${Z("订单金额", "ยอดสั่งซื้อ")}</th><th class="num">${Z("到账", "ยอดที่ได้รับ")}</th><th class="num">${Z("扣费", "ค่าธรรมเนียม")}</th><th class="num">${last}</th>
      <th>${Z("状态", "สถานะ")}</th><th>${Z("来源", "ที่มา")}</th><th></th></tr></thead><tbody>` +
      rows.map((x) => {
        const open = OPEN[keyOf(x)] !== undefined;
        const lastV = kind === "diff" ? `<td class="num bad">${m(x.diff)}</td>` : kind === "unpaid" || kind === "unsettled" ? `<td class="num warn">${x.days}</td>` : moneyCell(x.expected, "muted");
        return `<tr class="fin-click ${x.checked ? "fin-done" : ""}" data-st-row="${esc(keyOf(x))}"><td class="fin-caret">${open ? "▾" : "▸"}</td><td class="nowrap">${esc(x.day)}</td>
          <td class="nowrap">${esc(PLAT[x.platform] || x.platform)} <span class="muted" data-notr>${esc(x.shop || "")}</span></td>
          <td class="mono" data-notr>${esc(x.order_no)}</td>${moneyCell(x.revenue)}
          <td class="num ${x.net == null ? "muted" : ""}">${x.net == null ? "—" : m(x.net)}</td>
          <td class="num">${x.fee == null ? "—" : `${m(x.fee)} <span class="muted">${pct(x.fee_rate)}</span>`}</td>${lastV}
          <td class="nowrap"><span class="pill ${STATE_TONE[x.state] || ""}">${esc(stateName(r, x.state))}</span>${x.issue === "diff" && kind !== "diff" ? ` <span class="pill bad-pill">${Z("扣费异常", "หักเกิน")}</span>` : ""}${x.paid_at ? ` <span class="muted small">${esc(x.paid_at.slice(5))}</span>` : ""}</td>
          <td>${srcTag(x.source)}</td><td class="nowrap">${checkBtn(x)}</td></tr>${subRow(x, cols)}`;
      }).join("") + "</tbody></table></div>";
  }

  function unknownTable(rows) {
    const { m, PLAT } = window.FIN;
    if (!rows.length) return UX.empty(Z("没有", "ไม่มี"));
    return `<div class="fin-scroll"><table class="grid small"><thead><tr><th>${Z("结算日", "วันที่สรุปยอด")}</th><th>${Z("平台 · 店铺", "แพลตฟอร์ม · ร้าน")}</th><th>${Z("订单号", "เลขคำสั่งซื้อ")}</th><th class="num">${Z("到账", "ยอดที่ได้รับ")}</th><th>${Z("来源", "ที่มา")}</th><th></th></tr></thead><tbody>` +
      rows.map((x) => `<tr class="${x.checked ? "fin-done" : ""}"><td class="nowrap">${esc(x.day || "")}</td><td>${esc(PLAT[x.platform] || x.platform)} <span class="muted" data-notr>${esc(x.shop || "")}</span></td>
        <td class="mono" data-notr>${esc(x.order_no)}</td>${moneyCell(x.amount)}<td>${srcTag(x.source)}</td><td class="nowrap">${checkBtn(x)}</td></tr>`).join("") + "</tbody></table></div>";
  }

  function history(bs) {
    const { m, PLAT } = window.FIN;
    if (!bs.length) return "";
    return `<details class="card fin-hist"><summary><b>${Z("导入记录", "ประวัติการนำเข้า")}</b> <span class="muted small">${bs.length}</span></summary>
      <div class="fin-scroll"><table class="grid small"><thead><tr><th>${Z("时间", "เวลา")}</th><th>${Z("平台", "แพลตฟอร์ม")}</th><th>${Z("文件", "ไฟล์")}</th>
        <th>${Z("行（新）", "แถว (ใหม่)")}</th><th>${Z("订单", "คำสั่งซื้อ")}</th><th class="num">${Z("合计", "รวม")}</th><th>${Z("日期", "วันที่")}</th><th></th></tr></thead><tbody>` +
      bs.map((b) => `<tr><td class="nowrap">${fmtTime(b.created_at)}</td><td>${esc(PLAT[b.platform] || b.platform)} <span data-notr>${esc(b.shop || "")}</span></td>
        <td>${srcTag(b.source)} <span data-notr>${esc(b.filename || "")}</span></td><td>${b.rows} (${b.new_rows})</td><td>${b.orders}</td><td class="num">${m(b.total)}</td>
        <td class="small nowrap">${esc(b.date_from || "")} ~ ${esc(b.date_to || "")}</td>
        <td>${b.source === "api" ? "" : `<button class="mini danger" data-fin-delbatch="${b.id}">${Z("删除", "ลบ")}</button>`}</td></tr>`).join("") + "</tbody></table></div></details>";
  }

  async function render(box) {
    const { m, n0, pct, PLAT, q, head } = window.FIN;
    const r = await api(`/api/fin/reconcile?${q()}${PSEL ? `&platform=${PSEL}` : ""}`);
    LAST = r;
    const t = r.total, ic = t.issue_counts;
    const views = [["diff", Z("扣费比预计多", "หักมากกว่าที่คาด"), ic.diff], ["unpaid", Z("超时未回款", "ค้างรับเงินเกินกำหนด"), ic.unpaid],
      ["unknown", Z("平台有但系统没有", "มีในแพลตฟอร์มแต่ไม่มีในระบบ"), ic.unknown], ["unsettled", Z("系统有但平台没结算", "มีในระบบแต่แพลตฟอร์มไม่สรุปยอด"), ic.unsettled],
      ["all", Z("全部订单", "ทุกคำสั่งซื้อ"), r.rows.length]];
    if (!VIEW || !views.some((v) => v[0] === VIEW)) VIEW = (views.find((v) => v[2]) || ["all"])[0];
    const byState = {};
    r.rows.forEach((x) => { const s = byState[x.state] || (byState[x.state] = { n: 0, amt: 0 }); s.n++; s.amt += x.net != null ? x.net : x.revenue; });
    const order = ["paid", "settled", "pending", "overdue", "unsettled"];
    const tone = { paid: "ok", settled: "", pending: "warn", overdue: "bad", unsettled: "bad" };
    const feeHigh = t.fee_rate != null && t.fee_rate > t.cfg_rate + 1;
    const list = VIEW === "all" ? r.rows : r[VIEW] || [];
    box.innerHTML = head(Z("平台对账", "กระทบยอดแพลตฟอร์ม"),
      Z(`系统自动把每个订单和平台的结算记录对上，标出：已到账（钱到卡上了）、已结算（平台算好了，还没打款）、待回款、超时未回款（发货超过 ${r.settings.days} 天还没回款）、平台没结算。` +
        `「扣费比预计多」= 到账比「订单金额 × (1 − 设置里的扣点)」少 ${r.settings.tolerance} 铢以上。天数、容差、多少天没导入提醒在 设置 → 财务 改。`,
        `ระบบจับคู่คำสั่งซื้อกับข้อมูลการสรุปยอดของแพลตฟอร์มอัตโนมัติ: เงินเข้าแล้ว / สรุปยอดแล้ว (ยังไม่โอน) / รอรับเงิน / เกินกำหนด (ส่งแล้วเกิน ${r.settings.days} วัน) / แพลตฟอร์มไม่สรุปยอด` +
        ` 「หักมากกว่าที่คาด」= ได้รับน้อยกว่า「ยอดสั่งซื้อ × (1 − อัตรา)」เกิน ${r.settings.tolerance} บาท ปรับได้ที่ ตั้งค่า → การเงิน`)) +
      `<div class="fin-pcards">${(r.platforms || []).map(platCard).join("")}</div>` +
      `<div id="fin-st-prev">${PREV_HTML}</div>` +
      UX.tabs([["", Z("全部平台", "ทุกแพลตฟอร์ม")], ["lazada", "Lazada"], ["shopee", "Shopee"], ["tiktok", "TikTok"]], PSEL, "fin-st-plat") +
      UX.kpis([
        { label: Z("应收", "ยอดที่ควรได้รับ"), value: m(t.receivable), sub: Z(`${n0(t.orders)} 单已发货`, `${n0(t.orders)} คำสั่งซื้อที่ส่งแล้ว`),
          help: Z("这段时间已发货 / 已完成订单的订单金额合计。", "ยอดสั่งซื้อรวมของคำสั่งซื้อที่ส่งแล้ว/สำเร็จในช่วงนี้") },
        { label: Z("已到账", "เงินเข้าแล้ว"), value: m(t.arrived), tone: "ok", sub: t.receivable ? `${Math.round(t.arrived / t.receivable * 100)}%` : "" },
        { label: Z("平台实际扣费", "ค่าธรรมเนียมจริง"), value: m(t.fees), tone: feeHigh ? "warn" : "", sub: `${Z("实际", "จริง")} ${pct(t.fee_rate)} · ${Z("设置", "ตั้งไว้")} ${pct(t.cfg_rate)}`,
          help: Z("只算平台已经结算的订单：订单金额 − 到账。和设置里的扣点比，高出 1 个百分点以上标黄。", "นับเฉพาะคำสั่งซื้อที่สรุปยอดแล้ว: ยอดสั่งซื้อ − ยอดที่ได้รับ") },
        { label: Z("待回款", "รอรับเงิน"), value: m(t.pending), sub: t.settled_amount ? Z(`其中已结算 ${m(t.settled_amount)}`, `สรุปยอดแล้ว ${m(t.settled_amount)}`) : "",
          help: Z("还没到账的钱：平台结算了的按结算金额，没结算的按扣点估算。", "เงินที่ยังไม่เข้า: สรุปยอดแล้วใช้ยอดจริง ยังไม่สรุปใช้ค่าประมาณ") },
        { label: Z("异常单数", "รายการผิดปกติ"), value: n0(t.issues), tone: t.issues ? "bad" : "ok", sub: t.unpaid_amount ? Z(`超时 ${m(t.unpaid_amount)}`, `ค้าง ${m(t.unpaid_amount)}`) : "",
          help: Z("下面四个页签加起来（标了「已核对」的不算）。", "รวมสี่แท็บด้านล่าง (ไม่นับที่ตรวจแล้ว)") },
      ]) +
      UX.card({ title: Z("回款进度", "ความคืบหน้าการรับเงิน"), help: Z("条的长度 = 订单数；右边是金额（到账了的按到账，没到账的按订单金额）。", "ความยาว = จำนวนคำสั่งซื้อ ด้านขวาคือยอดเงิน"),
        right: t.adjustments ? `<span class="small muted">${Z("没有订单号的调整", "รายการปรับที่ไม่มีเลขคำสั่งซื้อ")} ${m(t.adjustments)}</span>` : "",
        body: UX.bars(order.filter((s) => byState[s]).map((s) => ({ label: stateName(r, s), value: byState[s].n, text: `${byState[s].n} · ${m(Math.round(byState[s].amt))}`, tone: tone[s] })),
          { empty: Z("这段时间没有已发货的平台订单", "ไม่มีคำสั่งซื้อที่ส่งแล้วในช่วงนี้") }) }) +
      `<div class="card">${UX.tabs(views.map(([k, l, n]) => [k, l, n]), VIEW, "fin-st-view")}
        ${VIEW === "unknown" ? unknownTable(list) + (list.length ? `<p class="muted small">${Z("这些订单号系统里找不到（订单还没导入？），导入订单后会自动对上；确实不是我们的单可以标「已核对」。", "เลขคำสั่งซื้อเหล่านี้ไม่มีในระบบ นำเข้าคำสั่งซื้อแล้วจะจับคู่อัตโนมัติ")}</p>` : "")
          : orderTable(r, list, VIEW) + (VIEW === "unsettled" && list.length ? `<p class="muted small">${Z("平台的结算数据已经覆盖到这些订单之后的日子，偏偏没有它们：可能被平台取消 / 退货了，去平台后台查一下。", "ข้อมูลของแพลตฟอร์มครอบคลุมถึงหลังวันที่เหล่านี้แล้วแต่ไม่มีคำสั่งซื้อนี้: อาจถูกยกเลิก/คืนสินค้า")}</p>` : "")
          + (VIEW === "unpaid" && list.length ? `<p class="muted small">${Z("没有结算记录的：Shopee / TikTok 导入最新的报表；Lazada 点「立即同步」。结算了没打款的：等平台打款，或者问平台。", "ไม่มีข้อมูลสรุปยอด: นำเข้ารายงานล่าสุดหรือกดซิงค์")}</p>` : "")}
      </div>` + history(r.batches || []);
  }

  // ---------------- 导入表格 ----------------
  async function preview(file, plat) {
    const { PLAT } = window.FIN;
    const fd = new FormData(); fd.append("file", file);
    STP = await api("/api/fin/settle/preview", { method: "POST", body: fd });
    const meta = FIN.meta() || {};
    const shops = [...new Set((meta.shops || []).filter((s) => !plat || s.platform === plat).map((s) => s.shop).filter(Boolean))];
    const sel = (f) => `<select data-fin-map="${f}"><option value="">—</option>${STP.headers.map((h, i) => `<option value="${i}" ${STP.mapping[f] === i ? "selected" : ""}>${esc(h || `#${i + 1}`)}</option>`).join("")}</select>`;
    const FZ = { order_no: ["订单号", "เลขคำสั่งซื้อ"], net: ["到账金额（每单一行的表格）", "ยอดที่ได้รับ (หนึ่งแถวต่อคำสั่งซื้อ)"], amount: ["金额（每笔费用一行的表格）", "จำนวนเงิน (หนึ่งแถวต่อค่าธรรมเนียม)"],
      fee_name: ["费用名称 / 类型", "ชื่อ/ประเภทค่าธรรมเนียม"], date: ["结算日期", "วันที่ชำระ"], wht: ["代扣税（WHT）", "ภาษีหัก ณ ที่จ่าย (WHT)"], vat: ["费用里的 VAT", "VAT ในค่าธรรมเนียม"], ref: ["结算单号", "เลขที่รายการ"] };
    const p0 = plat || STP.platform;
    PREV_HTML = `<div class="card ux-card"><div class="ux-card-h"><h3>${Z("导入结算报表", "นำเข้ารายงานการชำระเงิน")} · <span data-notr>${esc(file.name)}</span> <span class="muted small">${Z(`${STP.rows} 行`, `${STP.rows} แถว`)}</span></h3>
        <div class="ux-card-r"><button class="mini" data-st-cancel>${Z("取消", "ยกเลิก")}</button></div></div>
      <div class="form4"><label>${Z("平台", "แพลตฟอร์ม")}<select id="fin-st-plat">${["lazada", "shopee", "tiktok", "other"].map((p) => `<option value="${p}" ${p0 === p ? "selected" : ""}>${PLAT[p]}</option>`).join("")}</select></label>
        <label>${Z("店铺（可空）", "ร้าน (เว้นได้)")}<input id="fin-st-shop" list="fin-shops" data-notr><datalist id="fin-shops">${shops.map((s) => `<option value="${esc(s)}">`).join("")}</datalist></label></div>
      <details ${Object.keys(STP.mapping).length < 3 ? "open" : ""}><summary class="small">${Z("每一列是什么（已经自动认好，认错了在这里改）", "แต่ละคอลัมน์คืออะไร (จับคู่อัตโนมัติแล้ว แก้ได้ที่นี่)")}</summary>
        <div class="form4">${Object.keys(FZ).map((f) => `<label>${Z(FZ[f][0], FZ[f][1])}${sel(f)}</label>`).join("")}</div>
        <p class="small muted">${Z("「到账金额」和「金额」选一个：每单一行的表格选到账金额；Lazada 那种每笔费用一行的选金额（按订单号加起来）。", "เลือก「ยอดที่ได้รับ」หรือ「จำนวนเงิน」อย่างใดอย่างหนึ่ง")}</p>
        <div class="fin-scroll" style="max-height:220px"><table class="grid small"><thead><tr>${STP.headers.map((h) => `<th data-notr>${esc(h)}</th>`).join("")}</tr></thead><tbody>${STP.sample.map((row) => `<tr>${row.map((c) => `<td data-notr>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></details>
      <button class="primary" id="fin-st-go" style="margin-top:6px">${Z("导入", "นำเข้า")}</button></div>`;
    const el = $("#fin-st-prev");
    if (el) { el.innerHTML = PREV_HTML; el.scrollIntoView({ block: "nearest" }); }
  }

  async function toggle(k) {
    if (OPEN[k] !== undefined) { delete OPEN[k]; return FIN.reload(); }
    OPEN[k] = null;
    FIN.reload();
    const [p, no] = [k.slice(0, k.indexOf("|")), k.slice(k.indexOf("|") + 1)];
    try { OPEN[k] = await api(`/api/fin/reconcile/order?platform=${encodeURIComponent(p)}&order_no=${encodeURIComponent(no)}`); }
    catch (e) { delete OPEN[k]; toast(e.message, true); }
    FIN.reload();
  }

  document.addEventListener("change", async (e) => {
    const t = e.target;
    if (!t.closest || !t.closest("#fin-st")) return;
    if (t.dataset.stFile && t.files[0]) { try { await preview(t.files[0], t.dataset.stFile); } catch (err) { toast(err.message, true); } t.value = ""; }
  });
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (!t.closest || !t.closest("#fin-st")) return;
    const tab = t.closest("[data-ux-tab]");
    const grp = tab && tab.closest("[data-ux-group]");
    if (grp && grp.dataset.uxGroup === "fin-st-plat") { PSEL = tab.dataset.uxTab; try { localStorage.setItem("fin_st_plat", PSEL); } catch { /* 忽略 */ } return FIN.reload(); }
    if (grp && grp.dataset.uxGroup === "fin-st-view") { VIEW = tab.dataset.uxTab; return FIN.reload(); }
    const ck = t.closest("[data-st-check]");
    if (ck) {
      try { await api("/api/fin/reconcile/check", { json: { platform: ck.dataset.plat, order_no: ck.dataset.no, checked: ck.dataset.stCheck === "1" } }); FIN.reload(); }
      catch (err) { toast(err.message, true); }
      return;
    }
    if (t.closest("[data-st-order]")) { if (window.OPS && OPS.openOrder) OPS.openOrder(+t.closest("[data-st-order]").dataset.stOrder); return; }
    const row = t.closest("[data-st-row]");
    if (row && !t.closest("button,a,label,input,details")) return toggle(row.dataset.stRow);
    if (t.closest("[data-st-sync]")) {
      const b = t.closest("[data-st-sync]");
      await busy(b, async () => {
        const r = await api("/api/fin/settle/sync", { method: "POST", json: {} });
        const errs = [];
        ((r.finance && r.finance.shops) || []).forEach((s) => { const f = s.kinds && s.kinds.finance; if (f && f.error) errs.push(`${s.shop}: ${f.hint || f.error}`); });
        (r.payouts || []).forEach((p) => { if (p.error) errs.push(`${p.shop}: ${p.hint || p.error}`); });
        const n = ((r.finance && r.finance.shops) || []).reduce((a, s) => a + ((s.kinds && s.kinds.finance && s.kinds.finance.new) || 0), 0);
        if (errs.length) toast(errs.join("\n"), true, 9000);
        else toast(Z(`同步好了：新流水 ${n} 行，结算单 ${(r.payouts || []).reduce((a, p) => a + (p.payouts || 0), 0)} 期`, `ซิงค์แล้ว: รายการใหม่ ${n} แถว`));
        FIN.reload();
      });
      return;
    }
    if (t.closest("[data-st-cancel]")) { STP = null; PREV_HTML = ""; return FIN.reload(); }
    if (t.dataset.finDelbatch) {
      if (!confirm(Z("删除这次导入的结算数据？对应订单的到账金额会清掉。", "ลบข้อมูลการนำเข้านี้? ยอดที่ได้รับของคำสั่งซื้อจะถูกล้าง"))) return;
      try { await api(`/api/fin/settle/batches/${t.dataset.finDelbatch}`, { method: "DELETE" }); FIN.reload(); } catch (err) { toast(err.message, true); }
      return;
    }
    if (t.id === "fin-st-go" && STP) {
      const mapping = {};
      document.querySelectorAll("#fin-st [data-fin-map]").forEach((s) => { if (s.value !== "") mapping[s.dataset.finMap] = +s.value; });
      await busy(t, async () => {
        const r = await api("/api/fin/settle/import", { json: { token: STP.token, mapping, platform: $("#fin-st-plat").value, shop: $("#fin-st-shop").value.trim() } });
        toast(Z(`导入 ${r.new_rows} 行（重复 ${r.dup_rows} 行跳过），${r.orders} 个订单，对上 ${r.matched} 个`, `นำเข้า ${r.new_rows} แถว (ซ้ำ ${r.dup_rows}) ${r.orders} คำสั่งซื้อ จับคู่ได้ ${r.matched}`), false, 8000);
        STP = null; PREV_HTML = ""; FIN.reload();
      });
    }
  });

  window.FIN_SETTLE = { render };
})();
