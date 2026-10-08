"use strict";
// 财务 → 订单明细（v2.32）：每单一行，收入、平台费用拆分、到账、生产成本、利润、回款状态；点一行看完整计算；导出 Excel。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const F = { platform: "", shop: "", settle: "", q: "" };
  let LAST = null;
  const SETTLE_CLS = { settled: "ok-pill", pending: "warn-pill", overdue: "bad-pill" };
  const filt = () => Object.entries(F).filter(([, v]) => v).map(([k, v]) => `&${k}=${encodeURIComponent(v)}`).join("");

  async function render(box, barHtml, q, meta) {
    const { m, n0, pct, PLAT } = window.FIN;
    const r = await api(`/api/fin/orders?${q}${filt()}`);
    LAST = r;
    const t = r.total, c = r.counts;
    const shops = (meta && meta.shops) || [];
    box.innerHTML = barHtml + `<div class="row gap wrap fin-od-f" style="margin-bottom:8px">
        <select data-od="platform"><option value="">${Z("全部平台", "ทุกแพลตฟอร์ม")}</option>${Object.keys(PLAT).map((p) => `<option value="${p}" ${F.platform === p ? "selected" : ""}>${esc(PLAT[p])}</option>`).join("")}</select>
        <select data-od="shop" data-notr><option value="">${Z("全部店铺", "ทุกร้าน")}</option>${[...new Set(shops.map((s) => s.shop).filter(Boolean))].map((s) => `<option ${F.shop === s ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
        <span class="chips">${[["", Z("全部", "ทั้งหมด"), c.settled + c.pending + c.overdue], ["settled", r.settle_zh.settled, c.settled], ["pending", r.settle_zh.pending, c.pending], ["overdue", r.settle_zh.overdue, c.overdue]]
          .map(([k, l, n]) => `<span class="chip ${F.settle === k ? "on" : ""}" data-odset="${k}">${esc(l)} <span class="muted small">${n}</span></span>`).join("")}</span>
        <input data-od="q" placeholder="${Z("订单号 / 快递单号 / 买家", "เลขคำสั่งซื้อ / เลขพัสดุ / ผู้ซื้อ")}" value="${esc(F.q)}" style="width:200px" data-notr>
        <a class="btn mini-btn" href="/api/fin/orders/export?${q}${filt()}" download>⬇ ${Z("导出订单明细 Excel", "ส่งออกรายละเอียด Excel")}</a></div>
      <div class="card summary small"><div>${Z("订单", "คำสั่งซื้อ")}<b>${n0(t.orders)}</b></div><div>${Z("收入", "รายได้")}<b>${m(t.revenue)}</b></div>
        <div>${Z("平台扣费", "ค่าธรรมเนียม")}<b>${m(t.fee)}</b></div><div>${Z("到账", "ยอดรับ")}<b>${m(t.net)}</b></div>
        <div>${Z("生产成本", "ต้นทุนผลิต")}<b>${m(t.cost)}</b></div><div>${Z("利润", "กำไร")}<b class="${t.profit < 0 ? "bad" : "ok"}">${m(t.profit)}</b></div>
        <div>${Z("利润率", "อัตรากำไร")}<b>${pct(t.margin)}</b></div></div>
      <p class="small muted">${Z(`按下单日期；不含取消、退款、未付款、报价单。「到账」导入过结算表的是实际到账，没导入的是估算（灰色）。已发货超过 ${r.settle_days} 天还没回款算「超时未回款」。生产成本 = 材料 + 机时 + 包材 + 失败损耗。`,
        `ตามวันที่สั่งซื้อ ไม่รวมยกเลิก คืนเงิน ยังไม่จ่าย ใบเสนอราคา 「ยอดรับ」ที่นำเข้ารายงานแล้วเป็นยอดจริง ที่ยังไม่นำเข้าเป็นค่าประมาณ (สีเทา) ส่งแล้วเกิน ${r.settle_days} วันยังไม่ได้รับเงินถือว่า「ค้างรับเงิน」`)}</p>
      <div style="overflow-x:auto"><table class="grid small fin-od"><thead><tr><th>${Z("下单", "วันที่")}</th><th>${Z("订单号", "เลขคำสั่งซื้อ")}</th><th>${Z("平台 / 店铺", "แพลตฟอร์ม / ร้าน")}</th>
        <th class="num">${Z("收入", "รายได้")}</th><th class="num">${Z("平台扣费", "ค่าธรรมเนียม")}</th><th class="num">${Z("到账", "ยอดรับ")}</th>
        <th class="num">${Z("材料", "วัสดุ")}</th><th class="num">${Z("机时", "ค่าเครื่อง")}</th><th class="num">${Z("包材", "แพ็ก")}</th><th class="num">${Z("损耗", "สูญเสีย")}</th>
        <th class="num">${Z("利润", "กำไร")}</th><th class="num">%</th><th>${Z("回款", "รับเงิน")}</th></tr></thead><tbody>` +
      (r.rows.map((x, i) => `<tr data-odrow="${i}" style="cursor:pointer"><td class="nowrap">${fmtTime(x.order_time).slice(0, 10)}</td>
        <td class="mono" data-notr>${esc(x.order_no)}${x.missing_data ? ' <span class="warn" title="有商品没对上 SKU 或缺少克数，成本偏低">⚠</span>' : ""}</td>
        <td>${esc(PLAT[x.platform] || x.platform)} <span class="muted" data-notr>${esc(x.shop)}</span></td>
        <td class="num">${m(x.revenue)}</td><td class="num">${m(x.fee)}${x.fee_source === "estimate" ? ' <small class="muted">估</small>' : ""}</td>
        <td class="num ${x.net_estimated ? "muted" : ""}">${m(x.net)}</td><td class="num">${m(x.material)}</td><td class="num">${m(x.machine)}</td>
        <td class="num">${m(x.packaging)}</td><td class="num">${m(x.failure)}</td>
        <td class="num ${x.profit < 0 ? "bad" : ""}"><b>${m(x.profit)}</b></td><td class="num">${pct(x.margin)}</td>
        <td><span class="pill ${SETTLE_CLS[x.settle]}">${esc(r.settle_zh[x.settle])}</span></td></tr>`).join("") ||
        `<tr><td colspan="13" class="muted">${Z("这段时间没有订单", "ไม่มีคำสั่งซื้อในช่วงนี้")}</td></tr>`) + "</tbody></table></div>";
  }

  function detail(x) {
    const { m, pct, PLAT } = window.FIN;
    const L = (zh, th, v, cls = "") => `<tr><td>${Z(zh, th)}</td><td class="num ${cls}">${v}</td></tr>`;
    const mv = (v) => (v == null ? '<span class="muted">—</span>' : m(v));
    MODAL.open(`<h3>${Z("订单", "คำสั่งซื้อ")} <span class="mono" data-notr>${esc(x.order_no)}</span> <span class="muted small">${esc(PLAT[x.platform] || x.platform)} <span data-notr>${esc(x.shop)}</span> · ${fmtTime(x.order_time)}</span></h3>
      <p class="small" data-notr>${esc(x.skus)}</p>
      <div class="lanes two"><table class="grid small"><tbody>
        <tr><th colspan="2">${Z("收入", "รายได้")}</th></tr>
        ${L("订单金额", "ยอดสั่งซื้อ", mv(x.order_total))}${L("买家运费", "ค่าส่งที่ลูกค้าจ่าย", mv(x.buyer_shipping))}
        ${L("平台优惠（平台出钱）", "ส่วนลดแพลตฟอร์ม", mv(x.platform_discount))}${L("店铺优惠（卖家出钱）", "ส่วนลดร้าน", mv(x.seller_discount))}
        <tr><th colspan="2">${Z("平台扣费", "ค่าธรรมเนียมแพลตฟอร์ม")} <span class="muted small">${esc((LAST.fee_src_zh || {})[x.fee_source] || x.fee_source)}</span></th></tr>
        ${L("佣金", "ค่าคอมมิชชั่น", mv(x.commission))}${L("服务费", "ค่าบริการ", mv(x.service_fee))}${L("支付手续费", "ค่าธรรมเนียมชำระเงิน", mv(x.payment_fee))}
        ${L("扣费合计", "รวมค่าธรรมเนียม", `<b>${m(x.fee)}</b>`)}
        ${L("实际到账", "ยอดรับจริง", x.settlement == null ? `<span class="muted">${Z("还没导入结算表", "ยังไม่นำเข้า")}</span>` : `<b>${m(x.settlement)}</b>`)}
      </tbody></table><table class="grid small"><tbody>
        <tr><th colspan="2">${Z("成本", "ต้นทุน")}</th></tr>
        ${L("材料", "วัสดุ", m(x.material))}${L(`机时（${x.hours} h，电费 + 固定成本分摊）`, `ค่าเครื่อง (${x.hours} ชม.)`, m(x.machine))}
        ${L("包材", "วัสดุแพ็ก", m(x.packaging))}${L("失败损耗", "สูญเสียจากพิมพ์เสีย", m(x.failure))}${L("生产成本合计", "รวมต้นทุนผลิต", `<b>${m(x.cost)}</b>`)}
        <tr><th colspan="2">${Z("利润", "กำไร")}</th></tr>
        ${L("收入 − 平台扣费 − 生产成本", "รายได้ − ค่าธรรมเนียม − ต้นทุน", `<b>${m(x.profit)}</b>`, x.profit < 0 ? "bad" : "ok")}${L("利润率", "อัตรากำไร", pct(x.margin))}
        ${L("回款状态", "สถานะรับเงิน", esc(LAST.settle_zh[x.settle]))}
      </tbody></table></div>
      ${x.missing_data ? `<p class="warn small">${Z("有商品没对上 SKU 或缺少克数 / 时长，成本偏低。", "มีสินค้าที่ไม่ตรง SKU หรือไม่มีกรัม/เวลา ต้นทุนอาจต่ำกว่าจริง")}</p>` : ""}
      <div class="row gap"><button data-mclose>${Z("关闭", "ปิด")}</button></div>`).classList.add("wide");
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest || !e.target.closest("#fin-od")) return;
    const s = e.target.closest("[data-odset]");
    if (s) { F.settle = s.dataset.odset; FIN.reload(); return; }
    const tr = e.target.closest("[data-odrow]");
    if (tr && LAST) detail(LAST.rows[+tr.dataset.odrow]);
  });
  document.addEventListener("change", (e) => {
    const k = e.target.closest && e.target.closest("#fin-od") && e.target.dataset.od;
    if (k) { F[k] = e.target.value.trim(); FIN.reload(); }
  });
  window.FIN_ORDERS = { render };
})();
