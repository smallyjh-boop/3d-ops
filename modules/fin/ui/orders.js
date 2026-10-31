"use strict";
// 财务 → 订单利润（v2.32 订单明细；v2.49 和订单模块的「每单利润」并成一张表，可以按订单 / 平台 / 店铺 / SKU / 天看）。
// 数字卡片 → 图（每天利润 / 各组利润）→ 表；点一单看完整计算；导出 Excel。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const F = { platform: "", shop: "", settle: "", q: "" };
  let GROUP = "order";
  try { GROUP = localStorage.getItem("fin_od_group") || "order"; } catch { /* 忽略 */ }
  let LAST = null;
  const TONE = { paid: "ok-pill", settled: "", pending: "warn-pill", overdue: "bad-pill" };
  const filt = () => Object.entries(F).filter(([, v]) => v).map(([k, v]) => `&${k}=${encodeURIComponent(v)}`).join("");
  const GROUPS = { order: ["按订单", "ตามคำสั่งซื้อ"], platform: ["按平台", "ตามแพลตฟอร์ม"], shop: ["按店铺", "ตามร้าน"], sku: ["按 SKU", "ตาม SKU"], day: ["按天", "รายวัน"] };
  const SETTLE_TH = { paid: "เงินเข้าแล้ว", settled: "สรุปยอดแล้ว", pending: "รอรับเงิน", overdue: "เกินกำหนด" };
  const SRC_TH = { api: "API", import: "นำเข้าไฟล์", order: "ตารางออเดอร์", estimate: "ประมาณ" };

  function setGroup(g) { if (GROUPS[g]) { GROUP = g; try { localStorage.setItem("fin_od_group", g); } catch { /* 忽略 */ } } }

  async function render(box) {
    const { m, n0, pct, PLAT, q, head, exportBtn } = window.FIN;
    const meta = FIN.meta() || {};
    const top = head(Z("订单利润", "กำไรรายคำสั่งซื้อ"),
      Z("按下单日期；不含取消、退款、未付款、报价单。利润 = 收入 − 平台扣费 − 生产成本（材料 + 机时 + 包材 + 失败损耗），没扣广告费等支出（整个店的利润看「总览」）。平台还没结算的订单扣费按扣点估算（标「估」）。",
        "ตามวันที่สั่งซื้อ ไม่รวมยกเลิก คืนเงิน ยังไม่จ่าย ใบเสนอราคา กำไร = รายได้ − ค่าธรรมเนียม − ต้นทุนผลิต ยังไม่หักค่าโฆษณา คำสั่งซื้อที่ยังไม่สรุปยอดใช้ค่าธรรมเนียมประมาณ (「ประมาณ」)"),
      exportBtn()) + UX.tabs(Object.entries(GROUPS).map(([k, v]) => [k, Z(v[0], v[1])]), GROUP, "fin-od-group");
    if (GROUP !== "order") return renderGroup(box, top);
    const r = await api(`/api/fin/orders?${q()}${filt()}`);
    LAST = r;
    const t = r.total, c = r.counts;
    const shops = [...new Set((meta.shops || []).map((s) => s.shop).filter(Boolean))];
    const loss = r.rows.filter((x) => x.profit < 0).length;
    const byDay = {};
    r.rows.forEach((x) => { const d = fmtTime(x.order_time).slice(0, 10); byDay[d] = (byDay[d] || 0) + x.profit; });
    const days = Object.keys(byDay).sort();
    const settleName = (k) => (TH() ? SETTLE_TH[k] : r.settle_zh[k]) || k;
    box.innerHTML = top +
      UX.kpis([
        { label: Z("订单", "คำสั่งซื้อ"), value: n0(t.orders) },
        { label: Z("收入", "รายได้"), value: m(t.revenue) },
        { label: Z("平台扣费", "ค่าธรรมเนียม"), value: m(t.fee), sub: t.revenue ? pct(Math.round(t.fee / t.revenue * 1000) / 10) : "" },
        { label: Z("生产成本", "ต้นทุนผลิต"), value: m(t.cost) },
        { label: Z("利润", "กำไร"), value: m(t.profit), sub: pct(t.margin), tone: t.profit < 0 ? "bad" : "ok", spark: days.map((d) => byDay[d]) },
        { label: Z("亏本订单", "คำสั่งซื้อที่ขาดทุน"), value: n0(loss), tone: loss ? "bad" : "" },
      ]) +
      UX.card({ title: Z("每天的订单利润", "กำไรจากคำสั่งซื้อรายวัน"), body: UX.columns(days.map((d) => ({ label: d, value: byDay[d], text: m(byDay[d]), tone: byDay[d] < 0 ? "bad" : "ok" })),
        { h: 90, from: days[0] || "", to: days[days.length - 1] || "", empty: Z("这段时间没有订单", "ไม่มีคำสั่งซื้อในช่วงนี้") }) }) +
      `<div class="card"><div class="row gap wrap fin-od-f">
        <select data-od="platform"><option value="">${Z("全部平台", "ทุกแพลตฟอร์ม")}</option>${Object.keys(PLAT).map((p) => `<option value="${p}" ${F.platform === p ? "selected" : ""}>${esc(PLAT[p])}</option>`).join("")}</select>
        <select data-od="shop" data-notr><option value="">${Z("全部店铺", "ทุกร้าน")}</option>${shops.map((s) => `<option ${F.shop === s ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
        <input data-od="q" placeholder="${Z("订单号 / 快递单号 / 买家", "เลขคำสั่งซื้อ / เลขพัสดุ / ผู้ซื้อ")}" value="${esc(F.q)}" style="width:200px" data-notr>
        <span class="chips">${[["", Z("全部", "ทั้งหมด"), c.paid + c.settled + c.pending + c.overdue], ["paid", settleName("paid"), c.paid], ["settled", settleName("settled"), c.settled], ["pending", settleName("pending"), c.pending], ["overdue", settleName("overdue"), c.overdue]]
          .filter(([k, , n]) => !k || n || F.settle === k).map(([k, l, n]) => `<span class="chip ${F.settle === k ? "on" : ""}" data-odset="${k}">${esc(l)} <span class="muted small">${n}</span></span>`).join("")}</span>
        <a class="btn mini-btn" href="/api/fin/orders/export?${q()}${filt()}" download style="margin-left:auto">⬇ ${Z("导出订单利润 Excel", "ส่งออก Excel")}</a></div>
      ${r.rows.length ? `<div class="fin-scroll"><table class="grid small fin-od"><thead><tr><th>${Z("下单", "วันที่")}</th><th>${Z("订单号", "เลขคำสั่งซื้อ")}</th><th>${Z("平台 / 店铺", "แพลตฟอร์ม / ร้าน")}</th><th>${Z("商品", "สินค้า")}</th>
        <th class="num">${Z("收入", "รายได้")}</th><th class="num">${Z("平台扣费", "ค่าธรรมเนียม")}</th><th class="num">${Z("到账", "ยอดรับ")}</th>
        <th class="num">${Z("生产成本", "ต้นทุนผลิต")}</th><th class="num">${Z("利润", "กำไร")}</th><th class="num">%</th><th>${Z("回款", "รับเงิน")}</th></tr></thead><tbody>` +
        r.rows.map((x, i) => `<tr data-odrow="${i}" class="fin-click"><td class="nowrap">${fmtTime(x.order_time).slice(0, 10)}</td>
          <td class="mono" data-notr>${esc(x.order_no)}${x.missing_data ? ` <span class="warn" title="${Z("有商品没对上 SKU 或缺少克数，成本偏低", "มีสินค้าไม่ตรง SKU หรือไม่มีกรัม")}">⚠</span>` : ""}</td>
          <td class="nowrap">${esc(PLAT[x.platform] || x.platform)} <span class="muted" data-notr>${esc(x.shop)}</span></td>
          <td class="fin-skus">${(x.sku_list || []).slice(0, 3).map((s) => `<span class="mono fin-sku" data-p360="${esc(s)}" data-notr>${esc(s)}</span>`).join(" ")}${(x.sku_list || []).length > 3 ? ` <span class="muted">+${x.sku_list.length - 3}</span>` : ""}</td>
          <td class="num">${m(x.revenue)}</td><td class="num">${m(x.fee)}${x.fee_source === "estimate" ? ` <small class="muted">${Z("估", "ประมาณ")}</small>` : ""}</td>
          <td class="num ${x.net_estimated ? "muted" : ""}" title="${esc((TH() ? SRC_TH : r.source_zh || {})[x.source] || "")}">${m(x.net)}</td>
          <td class="num" title="${Z("材料", "วัสดุ")} ${m(x.material)} · ${Z("机时", "ค่าเครื่อง")} ${m(x.machine)} · ${Z("包材", "แพ็ก")} ${m(x.packaging)} · ${Z("损耗", "สูญเสีย")} ${m(x.failure)}">${m(x.cost)}</td>
          <td class="num ${x.profit < 0 ? "bad" : ""}"><b>${m(x.profit)}</b></td><td class="num">${pct(x.margin)}</td>
          <td class="nowrap"><span class="pill ${TONE[x.settle] || ""}">${esc(settleName(x.settle))}</span></td></tr>`).join("") + "</tbody></table></div>"
        : UX.empty(Z("这段时间没有订单", "ไม่มีคำสั่งซื้อในช่วงนี้"))}</div>`;
  }

  async function renderGroup(box, top) {
    const { m, n0, pct, PLAT, q } = window.FIN;
    const by = GROUP;
    const r = await api(`/api/fin/breakdown?by=${by}&${q()}`);
    const t = r.total;
    const rows = r.rows || [];
    const name = (x) => (by === "platform" ? (PLAT[x.key] || x.key) : x.key);
    const sorted = rows.slice().sort((a, b) => b.profit - a.profit);
    const chartRows = by === "day" ? null : (sorted.length > 14 ? sorted.slice(0, 10).concat(sorted.slice(-4)) : sorted);
    box.innerHTML = top +
      UX.kpis([
        { label: Z("订单", "คำสั่งซื้อ"), value: n0(t.orders) }, { label: Z("件数", "ชิ้น"), value: n0(t.qty) },
        { label: Z("收入", "รายได้"), value: m(t.revenue) }, { label: Z("平台扣费", "ค่าธรรมเนียม"), value: m(t.fee) },
        { label: Z("生产成本", "ต้นทุนผลิต"), value: m(t.cost) },
        { label: Z("利润", "กำไร"), value: m(t.profit), sub: pct(t.margin), tone: t.profit < 0 ? "bad" : "ok" },
      ]) +
      UX.card({ title: by === "day" ? Z("每天利润", "กำไรรายวัน") : Z("谁赚钱、谁亏钱", "อะไรได้กำไร อะไรขาดทุน"),
        help: Z("绿 = 利润率 15% 以上，黄 = 低于 15%，红 = 亏本。产品 / SKU 按商品金额比例分摊订单的扣费和成本。", "เขียว = อัตรากำไร ≥ 15% เหลือง = ต่ำกว่า 15% แดง = ขาดทุน"),
        body: by === "day" ? UX.columns(rows.map((x) => ({ label: x.key, value: x.profit, text: m(x.profit), tone: x.profit < 0 ? "bad" : "ok" })), { h: 100, from: rows.length ? rows[0].key : "", to: rows.length ? rows[rows.length - 1].key : "" })
          : UX.bars(chartRows.map((x) => ({ label: by === "sku" && x.name ? `${x.key} ${x.name}` : name(x), value: x.profit, text: `${m(x.profit)} · ${pct(x.margin)}`,
            tone: x.profit < 0 ? "bad" : x.margin != null && x.margin < 15 ? "warn" : "ok" })), { empty: Z("这段时间没有订单", "ไม่มีคำสั่งซื้อในช่วงนี้") }) }) +
      UX.card({ body: rows.length ? `<div class="fin-scroll"><table class="grid small"><thead><tr><th>${Z(GROUPS[by][0].replace("按", "").trim(), GROUPS[by][1])}</th>${by === "sku" ? `<th>${Z("名称", "ชื่อ")}</th>` : ""}
        <th class="num">${Z("订单", "คำสั่งซื้อ")}</th><th class="num">${Z("件数", "ชิ้น")}</th><th class="num">${Z("收入", "รายได้")}</th><th>${Z("占比", "สัดส่วน")}</th><th class="num">${Z("平台扣费", "ค่าธรรมเนียม")}</th>
        <th class="num">${Z("生产成本", "ต้นทุนผลิต")}</th><th class="num">${Z("利润", "กำไร")}</th><th class="num">${Z("利润率", "อัตรากำไร")}</th></tr></thead><tbody>` +
        (by === "day" ? rows.slice().reverse() : rows).map((x) => `<tr><td class="${by === "sku" ? "mono" : ""}" ${by === "sku" ? `data-p360="${esc(x.key)}"` : ""} data-notr>${esc(name(x))}</td>${by === "sku" ? `<td data-notr>${esc(x.name || "")}</td>` : ""}
          <td class="num">${x.orders}</td><td class="num">${x.qty}</td><td class="num">${m(x.revenue)}</td>
          <td class="nowrap"><div class="fin-share"><i style="width:${Math.min(100, x.share || 0)}%"></i></div><span class="small muted">${pct(x.share)}</span></td>
          <td class="num">${m(x.fee)}${x.est_fee ? ` <span class="warn small" title="${Z("有订单按扣点估算", "บางคำสั่งซื้อเป็นค่าประมาณ")}">*</span>` : ""}</td><td class="num">${m(x.cost)}</td>
          <td class="num ${x.profit < 0 ? "bad" : ""}"><b>${m(x.profit)}</b></td><td class="num ${x.margin != null && x.margin < 15 ? "warn" : ""}">${pct(x.margin)}</td></tr>`).join("") +
        "</tbody></table></div>" : UX.empty(Z("这段时间没有订单", "ไม่มีคำสั่งซื้อในช่วงนี้")) });
  }

  function detail(x) {
    const { m, pct, PLAT } = window.FIN;
    const L = (zh, th, v, cls = "") => `<tr><td>${Z(zh, th)}</td><td class="num ${cls}">${v}</td></tr>`;
    const mv = (v) => (v == null ? '<span class="muted">—</span>' : m(v));
    const settleName = (k) => (TH() ? SETTLE_TH[k] : LAST.settle_zh[k]) || k;
    MODAL.open(`<h3>${Z("订单", "คำสั่งซื้อ")} <span class="mono" data-notr>${esc(x.order_no)}</span> <span class="muted small">${esc(PLAT[x.platform] || x.platform)} <span data-notr>${esc(x.shop)}</span> · ${fmtTime(x.order_time)}</span></h3>
      <p class="small">${(x.sku_list || []).map((s) => `<span class="mono fin-sku" data-p360="${esc(s)}" data-notr>${esc(s)}</span>`).join(" ")} <span class="muted" data-notr>${esc(x.skus)}</span></p>
      <div class="lanes two"><table class="grid small"><tbody>
        <tr><th colspan="2">${Z("收入", "รายได้")}</th></tr>
        ${L("订单金额", "ยอดสั่งซื้อ", mv(x.order_total))}${L("买家运费", "ค่าส่งที่ลูกค้าจ่าย", mv(x.buyer_shipping))}
        ${L("平台优惠（平台出钱）", "ส่วนลดแพลตฟอร์ม", mv(x.platform_discount))}${L("店铺优惠（卖家出钱）", "ส่วนลดร้าน", mv(x.seller_discount))}
        <tr><th colspan="2">${Z("平台扣费", "ค่าธรรมเนียมแพลตฟอร์ม")} <span class="muted small">${esc((LAST.fee_src_zh || {})[x.fee_source] || x.fee_source)}</span></th></tr>
        ${L("佣金", "ค่าคอมมิชชั่น", mv(x.commission))}${L("服务费", "ค่าบริการ", mv(x.service_fee))}${L("支付手续费", "ค่าธรรมเนียมชำระเงิน", mv(x.payment_fee))}
        ${L("扣费合计", "รวมค่าธรรมเนียม", `<b>${m(x.fee)}</b>`)}
        ${L("实际到账", "ยอดรับจริง", x.settlement == null ? `<span class="muted">${Z("平台还没结算", "แพลตฟอร์มยังไม่สรุปยอด")}</span>` : `<b>${m(x.settlement)}</b>`)}
      </tbody></table><table class="grid small"><tbody>
        <tr><th colspan="2">${Z("成本", "ต้นทุน")}</th></tr>
        ${L("材料", "วัสดุ", m(x.material))}${L(`机时（${x.hours} h，电费 + 固定成本分摊）`, `ค่าเครื่อง (${x.hours} ชม.)`, m(x.machine))}
        ${L("包材", "วัสดุแพ็ก", m(x.packaging))}${L("失败损耗", "สูญเสียจากพิมพ์เสีย", m(x.failure))}${L("生产成本合计", "รวมต้นทุนผลิต", `<b>${m(x.cost)}</b>`)}
        <tr><th colspan="2">${Z("利润", "กำไร")}</th></tr>
        ${L("收入 − 平台扣费 − 生产成本", "รายได้ − ค่าธรรมเนียม − ต้นทุน", `<b>${m(x.profit)}</b>`, x.profit < 0 ? "bad" : "ok")}${L("利润率", "อัตรากำไร", pct(x.margin))}
        ${L("回款状态", "สถานะรับเงิน", esc(settleName(x.settle)) + (x.paid_at ? ` <span class="muted small">${esc(x.paid_at)}</span>` : ""))}
        ${L("到账数据来源", "ที่มาของยอดรับ", esc((TH() ? SRC_TH : LAST.source_zh || {})[x.source] || x.source || ""))}
      </tbody></table></div>
      ${x.missing_data ? `<p class="warn small">${Z("有商品没对上 SKU 或缺少克数 / 时长，成本偏低。", "มีสินค้าที่ไม่ตรง SKU หรือไม่มีกรัม/เวลา ต้นทุนอาจต่ำกว่าจริง")}</p>` : ""}
      <div class="row gap">${window.OPS && OPS.openOrder ? `<button data-fin-openorder="${x.id}">${Z("打开订单", "เปิดคำสั่งซื้อ")}</button>` : ""}<button data-mclose>${Z("关闭", "ปิด")}</button></div>`).classList.add("wide");
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest && e.target.closest("[data-fin-openorder]")) {
      const id = +e.target.closest("[data-fin-openorder]").dataset.finOpenorder;
      if (window.MODAL) MODAL.close();
      if (window.OPS && OPS.openOrder) OPS.openOrder(id);
      return;
    }
    if (!e.target.closest || !e.target.closest("#fin-od")) return;
    const tab = e.target.closest("[data-ux-tab]");
    if (tab && tab.closest("[data-ux-group='fin-od-group']")) { setGroup(tab.dataset.uxTab); FIN.reload(); return; }
    const s = e.target.closest("[data-odset]");
    if (s) { F.settle = s.dataset.odset; FIN.reload(); return; }
    if (e.target.closest("[data-p360]")) return;          // 点 SKU：交给商品抽屉
    const tr = e.target.closest("[data-odrow]");
    if (tr && LAST) detail(LAST.rows[+tr.dataset.odrow]);
  });
  document.addEventListener("change", (e) => {
    const k = e.target.closest && e.target.closest("#fin-od") && e.target.dataset.od;
    if (k) { F[k] = e.target.value.trim(); FIN.reload(); }
  });
  window.FIN_ORDERS = { render, setGroup };
})();
