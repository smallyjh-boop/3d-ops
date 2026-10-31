"use strict";
// 运营分析：经营概况（总览 / 店铺与评价）、商品表现（生命周期 + 流量 / 待确认的建议）。
// v2.49 重做成图形化：数字卡片 → 图表 → 明细（static/ux.js）；页面框架、筛选条、页签在 hub.js；今日待办搬到右上角 🔔（static/shell.js）。
// 界面文字用 Z(中文, 泰文) 直接写两种语言。
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const m = (v) => (v == null ? "—" : (v < 0 ? "-฿" : "฿") + Math.abs(Number(v)).toLocaleString(undefined, { maximumFractionDigits: 2 }));
  const m0 = (v) => (v == null ? "—" : (v < 0 ? "-฿" : "฿") + Math.abs(Number(v)).toLocaleString(undefined, { maximumFractionDigits: 0 }));
  const n0 = (v) => (v == null ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 }));
  const pct = (v) => (v == null ? "—" : `${v}%`);
  const neg = (v) => (v != null && v < 0 ? "bad" : "");
  const PLAT = (p) => ({ lazada: "Lazada", shopee: "Shopee", tiktok: "TikTok", manual: Z("私下成交", "ขายตรง") }[p] || p || Z("其他", "อื่นๆ"));
  const day = (ts) => (ts ? fmtTime(ts).slice(0, 10) : "—");
  const hm = (ts) => (ts ? fmtTime(ts).slice(11, 16) : "");
  const own = () => typeof ME === "undefined" || !ME || ME.role === "owner";
  const F = () => (window.OPSHUB ? OPSHUB.filter() : { range: "30" });
  const tbl = (head, rows, empty) => (rows.length ? `<div class="oa-wrap"><table class="grid"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`
    : UX.empty(empty || Z("没有", "ไม่มี")));
  const delta = (a, b) => (b ? Math.round(((a - b) / Math.abs(b)) * 100) : null);
  const dTxt = (d) => (d == null ? "" : `${d >= 0 ? "▲" : "▼"} ${Math.abs(d) > 999 ? ">999" : Math.abs(d)}%`);     // 和上一段同样长的时间比
  const BOX = { ops_dash: "ops-dash", ops_lazada: "ops-lz", ops_life: "ops-life", ops_sugg: "ops-sugg" };

  async function show(tab) {
    if (!BOX[tab]) {           // 竞品 / 雷达 / 竞店在 market.js，计划 / 日历在 plan.js
      const o = Object.values(window.OPSB || {}).find((x) => x.tabs.includes(tab));
      return o ? o.show(tab) : undefined;
    }
    const box = $("#" + BOX[tab]);
    if (!box) return;
    if (!box.innerHTML) box.innerHTML = `<p class="muted">${Z("加载中…", "กำลังโหลด…")}</p>`;
    try {
      if (tab === "ops_dash") return await dashPage(box);
      if (tab === "ops_lazada") return await lzPage(box);
      if (tab === "ops_life") return await lifePage(box);
      if (tab === "ops_sugg") return await suggPage(box);
    } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
  }
  document.addEventListener("click", (e) => {
    const g = e.target.closest("[data-ops-go]");
    if (g) goTab(g.dataset.opsGo);
  });
  const qs = (o) => new URLSearchParams(Object.entries(o).filter(([, v]) => v != null && v !== "")).toString();
  const daysOf = (f) => (window.OPSHUB ? OPSHUB.days(f) : 30);

  // ---------------- Lazada 小工具：同步状态一个点、店铺表现进度条、费用条形图 ----------------
  function syncDot(st) {
    if (!st || !st.length) return null;
    const bad = st.filter((s) => s.error), ok = st.filter((s) => !s.error && s.last_ok);
    const last = Math.max(0, ...st.map((s) => s.last_ok || 0));
    if (bad.length) {
      const why = bad.map((s) => `${s.shop} · ${Z(s.zh, s.th)}：${Z(s.hint || s.error, s.hint_th || s.hint || s.error)}`).join("\n");
      return { tone: "bad", html: UX.dot("bad", Z(`${bad.length} 项出错`, `ผิดพลาด ${bad.length} รายการ`)), sub: Z(`${ok.length} 项正常`, `ปกติ ${ok.length} รายการ`), help: why };
    }
    if (!ok.length) return { tone: "warn", html: UX.dot("warn", Z("还没同步过", "ยังไม่เคยซิงค์")), sub: "" };
    return { tone: "ok", html: UX.dot("ok", Z(`${ok.length} 项正常 · ${hm(last)}`, `ปกติ ${ok.length} รายการ · ${hm(last)}`)), sub: day(last) };
  }
  function perfCount(perf) {
    const all = (perf || []).flatMap((p) => p.metrics.filter((x) => x.ok != null));
    return { ok: all.filter((x) => x.ok).length, n: all.length };
  }
  function perfMeters(perf) {
    if (!perf || !perf.length) return UX.empty(Z("还没同步过店铺表现", "ยังไม่เคยซิงค์ประสิทธิภาพร้าน"));
    return perf.map((p) => `${perf.length > 1 ? `<h4 data-notr>${esc(p.shop)}</h4>` : ""}
      <div class="ux-meter ux-meter-h"><span class="ux-meter-l"></span><span class="small muted">${Z("竖线 = 平台要求", "เส้นตั้ง = เกณฑ์แพลตฟอร์ม")}</span><span class="ux-meter-v small muted">${Z("现在", "ตอนนี้")}</span><span class="ux-meter-r">${Z("要求", "เกณฑ์")}</span></div>
      ${p.metrics.map((x) => (x.v != null && x.t != null ? UX.meter({ label: Z(x.zh, x.th), value: x.v, target: x.t, better: x.better, text: x.value, targetText: x.target })
        : `<div class="ux-meter ${x.ok === false ? "ux-bad" : x.ok ? "ux-ok" : "ux-none"}"><span class="ux-meter-l">${esc(Z(x.zh, x.th))}</span><span></span>
          <span class="ux-meter-v" data-notr>${esc(x.value)}</span><span class="ux-meter-r" data-notr>${esc(x.target || "")} ${x.ok === false ? "✗" : x.ok ? "✓" : ""}</span></div>`)).join("")}
      <div class="small muted">${Z("更新于", "อัปเดต")} ${fmtTime(p.at)}</div>`).join("");
  }
  function feeBars(f) {
    if (!f || !f.fees || !f.fees.length) return UX.empty(Z("还没有财务流水", "ยังไม่มีรายการการเงิน"));
    return UX.bars(f.fees.filter((x) => x.amount).slice(0, 12).map((x) => ({ label: x.fee_name, value: Math.abs(x.amount), tone: x.amount > 0 ? "ok" : "",
      text: `${m0(x.amount)}${x.rate != null ? ` · ${x.rate}%` : ""}` })));
  }
  const reviewRow = (r) => `<div class="oa-li"><span class="${r.rating != null && r.rating <= 3 ? "bad" : "ok"}"><b>${r.rating ?? "—"}★</b></span>
    <span class="oa-li-t" data-notr>${esc(r.content || "")}${r.content ? "" : `<span class="muted">${Z("（没写内容）", "(ไม่มีข้อความ)")}</span>`}
      <span class="small muted">${esc(r.item_name || r.item_id || "")} · ${day(r.created)}</span></span>
    ${r.reply ? `<span class="small ok">${Z("已回复", "ตอบแล้ว")}</span>` : `<span class="small warn">${Z("没回复", "ยังไม่ตอบ")}</span>`}</div>`;
  const RTYPE = (t) => ({ RETURN: Z("退货退款", "คืนสินค้า"), ONLY_REFUND: Z("仅退款", "คืนเงินอย่างเดียว"), CANCEL: Z("取消", "ยกเลิก") }[(t || "").toUpperCase()] || t || "");
  const reverseRow = (r) => `<div class="oa-li"><span class="small">${esc(RTYPE(r.request_type))}</span>
    <span class="oa-li-t"><span class="mono" data-notr>${esc(r.order_no)}</span> <span class="small muted" data-notr>${esc(r.reason || "")}</span>
      <span class="small muted">${day(r.created)} · <span data-notr>${esc(r.status || "")}</span></span></span><b class="num">${m(r.refund_amount)}</b></div>`;

  // ---------------- 经营概况 → 总览 ----------------
  async function dashPage(box) {
    const f = F();
    const d = await api("/api/oa/dashboard?" + qs({ range: f.range, from: f.from, to: f.to, platform: f.platform, shop: f.shop }));
    if (window.OPSHUB) OPSHUB.options(d.filters);
    const k = d.kpi, p = d.kpi_prev, lz = d.lazada || {}, h = d.health, sh = d.shipping;
    const days = d.daily || [];
    const inP = days.filter((x) => x.day >= d.period.from);
    const showLz = !f.platform || f.platform === "lazada";
    const fees = lz.fees || {};
    const setRate = Math.round((d.fee_rate_setting || 0) * 1000) / 10;
    const rv = lz.reviews || {}, rs = lz.reverse || {};
    const sd = syncDot(lz.status);
    const pc = perfCount(lz.performance);
    const estNote = h.orders_fee_estimated ? Z(`近 30 天 ${h.orders_fee_estimated}/${h.orders_30d} 单的平台费是按扣点估算的；Lazada 财务流水拉下来以后按真实扣费算。`,
      `${h.orders_fee_estimated}/${h.orders_30d} ออเดอร์ใน 30 วันใช้ค่าธรรมเนียมประมาณ ดึงรายการการเงิน Lazada แล้วจะใช้ค่าจริง`) : "";
    const kp1 = [
      { icon: "💰", label: Z("销售额", "ยอดขาย"), value: m0(k.revenue), spark: inP.length > 1 ? inP.map((x) => x.revenue) : days.map((x) => x.revenue), sub: dTxt(delta(k.revenue, p.revenue)), help: Z("▲▼ = 和前面同样长的一段时间比", "▲▼ = เทียบกับช่วงก่อนหน้าที่ยาวเท่ากัน") },
      { icon: "📈", label: Z("利润", "กำไร"), value: m0(k.profit), tone: k.profit < 0 ? "bad" : "ok", spark: (inP.length > 1 ? inP : days).map((x) => x.profit),
        sub: dTxt(delta(k.profit, p.profit)), help: Z("每单利润 = 收入 − 平台费 − 生产成本，和「财务」同一个算法。", "กำไรต่อออเดอร์ = รายได้ − ค่าธรรมเนียม − ต้นทุนผลิต คิดแบบเดียวกับโมดูลการเงิน") + (estNote ? "\n" + estNote : "") },
      { icon: "🧾", label: Z("订单", "ออเดอร์"), value: k.n, spark: (inP.length > 1 ? inP : days).map((x) => x.orders), sub: Z(`客单价 ${m0(k.aov)}`, `เฉลี่ย/ออเดอร์ ${m0(k.aov)}`) },
      { icon: "％", label: Z("利润率", "อัตรากำไร"), value: pct(k.margin), tone: k.margin != null && k.margin < 10 ? "warn" : "", sub: p.margin != null ? Z(`上一段 ${p.margin}%`, `ช่วงก่อน ${p.margin}%`) : "" },
    ];
    if (d.fin_net) kp1.push({ icon: "🏦", label: Z("30 天净利润", "กำไรสุทธิ 30 วัน"), value: m0(d.fin_net.net), tone: d.fin_net.net < 0 ? "bad" : "", go: "tab:fin_overview",
      sub: d.fin_net.net_margin != null ? `${d.fin_net.net_margin}%` : "", help: Z("财务口径：扣了支出、固定费用、售后损失", "ตามบัญชี: หักค่าใช้จ่าย ค่าคงที่ และความเสียหายหลังการขาย") });
    const kp2 = showLz && lz.shops ? [
      sd ? { icon: "🔄", label: Z("Lazada 同步", "ซิงค์ Lazada"), value: sd.html, html: true, tone: sd.tone === "bad" ? "bad" : "", sub: sd.sub, help: sd.help, go: "tab:ops_lazada" } : null,
      { icon: "🏷", label: Z("真实扣点", "ค่าธรรมเนียมจริง"), value: fees.rate == null ? "—" : `${fees.rate}%`, tone: fees.rate != null && fees.rate > setRate + 1 ? "warn" : "",
        sub: Z(`设置里 ${setRate}%`, `ที่ตั้งไว้ ${setRate}%`), help: Z("Lazada 财务流水里平台扣的钱 ÷ 商品金额。比设置里的高很多时，到「设置 → 成本」改扣点。", "เงินที่แพลตฟอร์มหัก ÷ ยอดสินค้า จากรายการการเงิน Lazada ถ้าสูงกว่าที่ตั้งไว้มาก ให้แก้ที่「ตั้งค่า → ต้นทุน」") },
      { icon: "⭐", label: Z("评价", "รีวิว"), value: rv.avg != null ? `${rv.avg} ★` : "—", tone: rv.bad_open ? "bad" : "", go: "tab:ops_lazada",
        sub: Z(`${rv.n || 0} 条 · 差评 ${rv.bad || 0} · 没回复 ${rv.bad_open || 0}`, `${rv.n || 0} รีวิว · แย่ ${rv.bad || 0} · ยังไม่ตอบ ${rv.bad_open || 0}`) },
      { icon: "↩️", label: Z("退货退款", "คืนสินค้า/เงิน"), value: rs.n || 0, tone: rs.n ? "warn" : "", sub: m0(rs.refund || 0), go: "tab:ops_lazada" },
      pc.n ? { icon: "🏪", label: Z("店铺表现", "ประสิทธิภาพร้าน"), value: Z(`${pc.ok}/${pc.n} 达标`, `ผ่าน ${pc.ok}/${pc.n}`), tone: pc.ok < pc.n ? "bad" : "ok", go: "tab:ops_lazada" } : null,
    ] : [];
    const cols = UX.columns(days.map((x) => ({ label: x.day, value: Math.max(0, x.revenue), text: `${m0(x.revenue)} · ${Z("利润", "กำไร")} ${m0(x.profit)} · ${x.orders} ${Z("单", "ออเดอร์")}`,
      tone: x.profit < 0 ? "bad" : x.day < d.period.from ? "info" : "" })), { h: 140, from: days.length ? days[0].day : "", to: days.length ? days[days.length - 1].day : "" });
    const plat = UX.bars(d.platforms.map((x) => ({ label: PLAT(x.key), value: x.revenue, text: `${m0(x.revenue)} · ${x.orders}${Z("单", "")}`, tone: x.profit < 0 ? "bad" : "" })),
      { empty: Z("这段时间没有订单", "ช่วงนี้ไม่มีออเดอร์") });
    const skus = d.skus.slice(0, 10).map((x) => `<tr><td><span class="mono" data-p360="${esc(x.key)}" data-notr>${esc(x.key)}</span><div class="small muted" data-notr>${esc(x.name || "")}</div></td>
      <td class="num">${x.qty}</td><td class="num">${m0(x.revenue)}</td><td class="num ${neg(x.profit)}">${m0(x.profit)}</td></tr>`);
    const loss = d.loss_orders.slice(0, 10).map((o) => `<tr><td>${esc(PLAT(o.platform))} <span class="mono" data-notr>${esc(o.order_no)}</span><div class="small muted">${day(o.order_time)}</div></td>
      <td class="num">${m0(o.revenue)}</td><td class="num">${m0(o.fee)}${o.fee_estimated ? ` <span class="warn small">${Z("估", "ประมาณ")}</span>` : ""}</td><td class="num">${m0(o.cost)}</td><td class="num bad">${m0(o.profit)}</td></tr>`);
    const price = d.pricing.slice(0, 10).map((x) => `<tr><td><span class="mono" data-p360="${esc(x.sku)}" data-notr>${esc(x.sku)}</span><div class="small muted" data-notr>${esc(x.name)} ${esc(x.variant || "")}</div></td>
      <td class="num ${x.erp_low ? "bad" : ""}">${m(x.price)}</td><td>${x.platform_prices.map((y) => `${esc(PLAT(y.platform))} <b class="bad">${m(y.price)}</b>`).join("<br>") || "—"}</td>
      <td class="num">${m(x.floor_price)}</td></tr>`);
    const ship = [...sh.overdue.map((o) => [o, "bad", Z("超时", "เลยเวลา")]), ...sh.soon.map((o) => [o, "warn", Z("快到期", "ใกล้ครบ")])].slice(0, 8)
      .map(([o, c, l]) => `<div class="oa-li"><span class="${c} small">${l}</span><span class="oa-li-t"><span>${esc(PLAT(o.platform))} <span class="mono" data-notr>${esc(o.order_no)}</span></span></span>
        <span class="small">${o.hours_left < 0 ? Z(`超 ${-o.hours_left} 小时`, `เกิน ${-o.hours_left} ชม.`) : Z(`剩 ${o.hours_left} 小时`, `เหลือ ${o.hours_left} ชม.`)}</span></div>`).join("");
    const pr = d.production;
    box.innerHTML = `${UX.kpis(kp1)}${kp2.filter(Boolean).length ? UX.kpis(kp2) : ""}
      ${UX.card({ title: Z("每日销售额", "ยอดขายรายวัน"), help: Z("柱子 = 每天销售额（鼠标放上去看利润、单数）；红色 = 当天亏损；灰色 = 选的时间段之前（对比用）", "แท่ง = ยอดขายต่อวัน (ชี้เมาส์ดูกำไร/ออเดอร์) สีแดง = วันนั้นขาดทุน สีเทา = ก่อนช่วงที่เลือก"), body: cols })}
      ${showLz && lz.shops ? `<div class="oa-grid2">
        ${UX.card({ title: Z("店铺表现", "ประสิทธิภาพร้าน"), right: `<button class="mini" data-ops-go="ops_lazada">${Z("全部", "ทั้งหมด")}</button>`, body: perfMeters(lz.performance) })}
        ${UX.card({ title: Z("平台扣了哪些钱", "แพลตฟอร์มหักอะไรบ้าง"), help: Z("Lazada 财务流水按费用名分；绿色 = 平台补贴 / 返还", "แยกตามชื่อค่าธรรมเนียมจากรายการการเงิน Lazada สีเขียว = เงินคืน/อุดหนุน"),
          right: fees.item_amount ? `<span class="small muted">${Z("商品金额", "ยอดสินค้า")} ${m0(fees.item_amount)} · ${Z("扣了", "หัก")} ${m0(fees.deducted)}</span>` : "", body: feeBars(fees) })}
        ${UX.card({ title: Z("最新评价", "รีวิวล่าสุด"), right: `<button class="mini" data-ops-go="ops_lazada">${Z("全部", "ทั้งหมด")}</button>`,
          body: (lz.reviews_recent || []).length ? lz.reviews_recent.map(reviewRow).join("") : UX.empty(Z("这段时间没有评价", "ช่วงนี้ไม่มีรีวิว")) })}
        ${UX.card({ title: Z("退货退款", "คืนสินค้า / คืนเงิน"), right: `<button class="mini" data-ops-go="ops_lazada">${Z("全部", "ทั้งหมด")}</button>`,
          body: (lz.reverse_recent || []).length ? lz.reverse_recent.map(reverseRow).join("") : UX.empty(Z("这段时间没有退货退款", "ช่วงนี้ไม่มีการคืนสินค้า")) })}
      </div>` : ""}
      <div class="oa-grid2">
        ${UX.card({ title: Z("按平台", "ตามแพลตฟอร์ม"), help: Z("销售额 · 订单数；红色 = 亏损", "ยอดขาย · จำนวนออเดอร์ สีแดง = ขาดทุน"), body: plat })}
        ${UX.card({ title: Z("发货时效", "ความตรงเวลาในการส่ง"), right: `<span class="small muted">${Z("准时率", "ส่งตรงเวลา")} <b>${pct(sh.on_time_rate)}</b></span>`,
          body: UX.kpis([{ label: Z("待发货", "รอส่ง"), value: sh.to_ship, go: "tab:orders" }, { label: Z("超时", "เลยเวลา"), value: sh.overdue_n, tone: sh.overdue_n ? "bad" : "ok" },
            { label: Z("快到期", "ใกล้ครบ"), value: sh.soon_n, tone: sh.soon_n ? "warn" : "" }]) + (ship || UX.empty(Z("全部正常", "ปกติทั้งหมด"))) })}
        ${UX.card({ title: Z("利润最高的 SKU", "SKU กำไรสูงสุด"), body: tbl(["SKU", Z("件数", "ชิ้น"), Z("销售额", "ยอดขาย"), Z("利润", "กำไร")], skus, Z("这段时间没有订单", "ช่วงนี้ไม่มีออเดอร์")) })}
        ${UX.card({ title: Z("亏本订单", "ออเดอร์ขาดทุน"), tone: d.loss_orders.length ? "bad" : "", right: d.loss_orders.length ? `<b class="bad">${d.loss_orders.length}</b>` : "",
          body: tbl([Z("订单", "ออเดอร์"), Z("销售额", "ยอดขาย"), Z("平台费", "ค่าธรรมเนียม"), Z("成本", "ต้นทุน"), Z("利润", "กำไร")], loss, Z("没有亏本订单", "ไม่มีออเดอร์ขาดทุน")) })}
        ${UX.card({ title: Z("售价低于最低价", "ราคาต่ำกว่าราคาขั้นต่ำ"), tone: d.pricing.length ? "warn" : "",
          body: tbl(["SKU", Z("ERP 售价", "ราคา ERP"), Z("平台上实际卖", "ราคาจริงบนแพลตฟอร์ม"), Z("最低价", "ราคาขั้นต่ำ")], price, Z("全部正常", "ปกติทั้งหมด")) })}
        ${UX.card({ title: Z("生产与耗材", "การผลิตและวัสดุ"), body: (pr ? UX.kpis([{ label: Z("排队", "คิว"), value: pr.queue_jobs, sub: `${pr.queue_pcs} ${Z("件", "ชิ้น")} · ${n0(pr.queue_hours)} ${Z("小时", "ชม.")}`, go: "tab:production" },
            { label: Z("约几天的活", "งานราวกี่วัน"), value: pr.days_of_work ?? "—" }, { label: Z("待后处理", "รอเก็บงาน"), value: pr.post }]) : "")
          + (d.materials.map((x) => `<div class="small ${x.short ? "bad" : "warn"}">${esc(x.material)} ${esc(x.color)} · ${Z("剩", "เหลือ")} ${n0(x.kg)} kg · ${x.short ? Z("不够打待打印的单", "ไม่พอพิมพ์งานที่รอ") : Z(`约 ${n0(x.days_left)} 天用完`, `หมดในราว ${n0(x.days_left)} วัน`)}</div>`).join("") || UX.empty(Z("耗材够用", "วัสดุพอใช้"))) })}
      </div>
      ${marketCard(d.market || {})}
      <details class="card oa-det"><summary><b>${Z("数据健康", "ความครบของข้อมูล")}</b> <span class="small muted">${h.orders_missing_data ? Z(`${h.orders_missing_data} 单成本数据不全`, `${h.orders_missing_data} ออเดอร์ข้อมูลต้นทุนไม่ครบ`) : ""}</span></summary>
        ${UX.bars([[Z("SKU 总数", "จำนวน SKU"), h.skus], [Z("缺克数或时长的 SKU", "SKU ที่ไม่มีกรัมหรือเวลาพิมพ์"), h.skus_missing_cost, "warn"],
          [Z("成本数据不全的订单（30 天）", "ออเดอร์ข้อมูลต้นทุนไม่ครบ (30 วัน)"), h.orders_missing_data, "warn"],
          [Z("平台费是估算的订单（30 天）", "ออเดอร์ค่าธรรมเนียมประมาณ (30 วัน)"), h.orders_fee_estimated, "warn"]].map(([l, v, t]) => ({ label: l, value: v || 0, tone: v ? t : "" })))}
        ${h.unknown_skus.length ? `<p class="small">${Z("没对上产品的 SKU", "SKU ที่จับคู่สินค้าไม่ได้")}：<span class="mono" data-notr>${esc(h.unknown_skus.join(", "))}</span></p>` : ""}
        <p class="small muted">${d.breakdown_source === "fin" ? Z("利润和「财务」模块同一个算法（平台、SKU 的数直接取自财务）。", "กำไรใช้วิธีคิดเดียวกับโมดูลการเงิน") : ""}</p></details>`;
  }

  // 市场与计划（下一个大促、进行中的计划、竞品动态、流量）
  function marketCard(mk) {
    const t = mk.traffic, nc = mk.next_campaign;
    const parts = [];
    if (nc) parts.push(`<div class="oa-li"><span>📅</span><span class="oa-li-t"><b data-notr>${esc(Z(nc.name, nc.name_th))}</b> <span class="small muted">${nc.start} · ${Z(`还有 ${nc.days_left} 天`, `อีก ${nc.days_left} วัน`)} · ${Z("预计", "คาด")} ${n0(nc.expected_orders)} ${Z("单/天", "ออเดอร์/วัน")}</span></span>
      ${nc.over_capacity ? `<b class="bad small">${Z("超过产能", "เกินกำลังผลิต")}</b>` : ""}<button class="mini" data-ops-go="ops_cal">${Z("日历", "ปฏิทิน")}</button></div>`);
    (mk.plans || []).slice(0, 4).forEach((p) => parts.push(`<div class="oa-li"><span>🚀</span><span class="oa-li-t"><span class="mono" data-p360="${esc(p.sku)}" data-notr>${esc(p.sku)}</span> <span class="small muted">${p.cum_actual}/${p.cum_target}</span></span>
      ${UX.dot(p.status === "far" ? "bad" : p.status === "behind" ? "warn" : "ok", Z(p.status_label, p.status_th))}<button class="mini" data-ops-go="ops_plans">${Z("计划", "แผน")}</button></div>`));
    (mk.comp_events || []).slice(0, 4).forEach((e) => parts.push(`<div class="oa-li"><span>👀</span><span class="oa-li-t small" data-notr>${esc(Z(e.text, e.text_th || e.text))}</span><button class="mini" data-ops-go="ops_comp">${Z("竞品", "คู่แข่ง")}</button></div>`));
    if (!parts.length) return "";
    return UX.card({ title: Z("市场与计划", "ตลาดและแผน"), body: parts.join("") });
  }

  // ---------------- 经营概况 → 店铺与评价（Lazada 数据） ----------------
  let RV_FILTER = "bad";
  async function lzPage(box) {
    const days = daysOf(F());
    const d = await api(`/api/oa/lazada?days=${Math.max(1, Math.min(90, days))}`);
    if (!d.shops.length) {
      box.innerHTML = UX.empty(Z("还没有开着的 Lazada 店铺：先到「设置 → AI 与对接 → 店铺对接」接上 Lazada。", "ยังไม่มีร้าน Lazada ที่เปิดใช้: ไปเชื่อมที่「ตั้งค่า → AI และการเชื่อมต่อ → เชื่อมต่อร้าน」ก่อน"));
      return;
    }
    const sd = syncDot(d.status);
    const every = Number(d.sync_min || 0);
    const st = d.status.map((s) => `<div class="oa-li">${UX.dot(s.error ? "bad" : s.last_ok ? "ok" : "warn", "")}<span class="oa-li-t"><span data-notr>${esc(s.shop)}</span> · ${esc(Z(s.zh, s.th))}
        ${s.error ? `<span class="small bad" data-notr>${esc(s.error)}</span>${s.hint ? `<span class="small"><b>${Z("怎么办", "ต้องทำอะไร")}：</b>${esc(Z(s.hint, s.hint_th || s.hint))}</span>` : ""}` : ""}</span>
      <span class="small muted">${s.last_ok ? fmtTime(s.last_ok) : Z("还没同步过", "ยังไม่เคยซิงค์")}</span></div>`).join("");
    const rv = d.reviews.filter((r) => RV_FILTER === "all" || (RV_FILTER === "bad" ? r.rating != null && r.rating <= 3 : !r.reply));
    const nBad = d.reviews.filter((r) => r.rating != null && r.rating <= 3).length, nOpen = d.reviews.filter((r) => !r.reply).length;
    let html = UX.card({ title: Z("同步状态", "สถานะการซิงค์"), help: Z("用的是「店铺对接」里授权的 Lazada 应用。显示没有权限时：到 open.lazada.com 的 App Console 给应用申请对应的 API 权限，批下来后重新授权店铺。",
        "ใช้แอป Lazada ที่อนุญาตไว้ใน「เชื่อมต่อร้าน」 ถ้าขึ้นว่าไม่มีสิทธิ์: ขอสิทธิ์ API ใน App Console ที่ open.lazada.com แล้วอนุญาตร้านใหม่"),
      right: `${sd ? sd.html : ""} <span class="small muted">${every ? Z(`每 ${every} 分钟自动同步`, `ซิงค์อัตโนมัติทุก ${every} นาที`) : Z("自动同步关着", "ปิดซิงค์อัตโนมัติ")}</span>
        ${own() ? `<button class="mini" data-lz-sync>${Z("立即同步", "ซิงค์ตอนนี้")}</button>` : ""}`,
      body: `<details ${sd && sd.tone === "bad" ? "open" : ""}><summary class="small muted">${Z("每一项的情况", "รายละเอียดแต่ละรายการ")}</summary>${st}</details>` });
    if (own() && d.performance) html += UX.card({ title: Z("店铺表现", "ประสิทธิภาพร้าน"), body: perfMeters(d.performance) });
    if (own() && d.fees) {
      const f = d.fees;
      html += UX.card({ title: Z("真实扣点（财务流水）", "ค่าธรรมเนียมจริง (รายการการเงิน)"), help: Z("拉到了商品金额那一行的订单，流水自动记进「财务 → 平台对账」，利润按真实扣费算。", "ออเดอร์ที่มีแถวยอดสินค้าแล้ว จะบันทึกเข้า「การเงิน → กระทบยอดแพลตฟอร์ม」อัตโนมัติ และคิดกำไรจากค่าธรรมเนียมจริง"),
        body: UX.kpis([{ label: Z("商品金额", "ยอดสินค้า"), value: m0(f.item_amount) }, { label: Z("平台扣了", "แพลตฟอร์มหัก"), value: m0(f.deducted) },
          { label: Z("扣点", "อัตรา"), value: pct(f.rate) }, f.credits ? { label: Z("补贴 / 返还", "เงินคืน/อุดหนุน"), value: m0(f.credits), tone: "ok" } : null]) + feeBars(f) });
    }
    html += UX.card({ title: Z("评价", "รีวิว"), right: UX.tabs([["bad", Z("差评（≤ 3 星）", "รีวิวแย่ (≤ 3 ดาว)"), nBad], ["open", Z("没回复", "ยังไม่ตอบ"), nOpen], ["all", Z("全部", "ทั้งหมด"), d.reviews.length]], RV_FILTER, "rv"),
      body: tbl([Z("时间", "เวลา"), Z("商品", "สินค้า"), Z("星", "ดาว"), Z("内容", "ข้อความ"), Z("回复", "คำตอบ")], rv.map((r) => `<tr>
        <td class="small nowrap">${fmtTime(r.created)}<div class="muted" data-notr>${esc(r.shop)}</div></td>
        <td class="small" data-notr><span ${r.product_code ? `data-p360="${esc(r.product_code)}"` : ""}>${esc(r.item_name || r.item_id)}</span>${r.product_code ? `<div class="muted mono">${esc(r.product_code)}</div>` : ""}<div class="muted">${Z("订单", "ออเดอร์")} ${esc(r.order_id)}</div></td>
        <td class="num ${r.rating != null && r.rating <= 3 ? "bad" : ""}"><b>${r.rating ?? "—"}</b>★</td><td data-notr>${esc(r.content || "")}${r.images ? ` <span class="muted small">📷${r.images}</span>` : ""}</td>
        <td class="small">${r.reply ? `<span data-notr>${esc(r.reply)}</span>${r.reply_by ? `<div class="muted">${esc(r.reply_by)} ${fmtTime(r.replied_at)}</div>` : ""}`
          : (r.can_reply ? `<textarea rows="2" maxlength="500" data-rv-text="${esc(r.review_id)}" placeholder="${Z("写回复（泰文）", "เขียนคำตอบ")}"></textarea>
            <button class="mini" data-rv-send="${esc(r.review_id)}" data-shop="${r.shop_id}">${Z("回复", "ตอบ")}</button>` : `<span class="muted">${Z("不能回复", "ตอบไม่ได้")}</span>`)}</td></tr>`),
        Z("没有评价", "ไม่มีรีวิว")) });
    if (own() && d.reverse) {
      html += UX.card({ title: Z("退货退款", "คืนสินค้า / คืนเงิน"), body: tbl([Z("时间", "เวลา"), Z("订单", "ออเดอร์"), Z("类型", "ประเภท"), "SKU", Z("原因", "เหตุผล"), Z("状态", "สถานะ"), Z("退款", "คืนเงิน")],
        d.reverse.map((r) => `<tr><td class="small nowrap">${fmtTime(r.created)}</td><td class="mono" data-notr>${esc(r.order_no)}</td><td>${esc(RTYPE(r.request_type))}</td>
          <td class="mono small" data-p360="${esc(r.seller_sku)}" data-notr>${esc(r.seller_sku)}</td><td class="small" data-notr>${esc(r.reason)}</td>
          <td class="small ${r.open ? "warn" : "muted"}" data-notr>${esc(r.status)}</td><td class="num">${m(r.refund_amount)}</td></tr>`), Z("这段时间没有退货退款", "ช่วงนี้ไม่มีการคืนสินค้า")) });
    }
    box.innerHTML = html;
    box.onclick = async (e) => {
      const f = e.target.closest('[data-ux-group="rv"] [data-ux-tab]');
      if (f) { RV_FILTER = f.dataset.uxTab; return show("ops_lazada"); }
      const sy = e.target.closest("[data-lz-sync]");
      if (sy) {
        return busy(sy, async () => {
          const r = await apiJob("/api/oa/lazada/sync", { json: {} });
          const bad = (r.shops || []).flatMap((s) => Object.values(s.kinds || {}).filter((k) => k.error));
          toast(bad.length ? Z(`同步完了，${bad.length} 项出错（看同步状态）`, `ซิงค์เสร็จ มีข้อผิดพลาด ${bad.length} รายการ`) : Z("同步完了", "ซิงค์เสร็จแล้ว"), !!bad.length);
          show("ops_lazada");
        });
      }
      const b = e.target.closest("[data-rv-send]");
      if (b) {
        const ta = box.querySelector(`[data-rv-text="${CSS.escape(b.dataset.rvSend)}"]`);
        return busy(b, async () => {
          await api("/api/oa/reviews/reply", { json: { shop_id: Number(b.dataset.shop), review_id: b.dataset.rvSend, content: ta ? ta.value : "" } });
          toast(Z("回复发到 Lazada 了（平台审核后显示）", "ส่งคำตอบไป Lazada แล้ว (แสดงหลังแพลตฟอร์มตรวจ)"));
          show("ops_lazada");
        });
      }
    };
  }

  // ---------------- 商品表现（生命周期 + 卖家后台流量） ----------------
  let LIFE = null, TRF = null, STAGE = "";
  const LV = { bad: "bad", warn: "warn", ok: "ok", good: "ok", info: "info", mute: "" };
  async function lifePage(box) {
    [LIFE, TRF] = await Promise.all([api("/api/oa/lifecycle"), api("/api/oa/traffic").catch(() => null)]);
    box.onclick = (e) => {
      const s = e.target.closest('[data-ux-group="stage"] [data-ux-tab]');
      if (s) { STAGE = s.dataset.uxTab; lifeRender(box); }
    };
    lifeRender(box);
  }
  function lifeRender(box) {
    const L = LIFE, f = F();
    const lab = (k) => Z(L.stages[k].label, L.stages[k].th);
    const q = (f.q || "").toLowerCase();
    const base = L.rows.filter((r) => (!f.platform || r.platform === f.platform) && (!q || `${r.sku} ${r.name} ${r.variant || ""}`.toLowerCase().includes(q)));
    const cnt = {};
    base.forEach((r) => { cnt[r.stage] = (cnt[r.stage] || 0) + 1; });
    if (STAGE && !cnt[STAGE]) STAGE = "";
    const rows = base.filter((r) => !STAGE || r.stage === STAGE);
    const onSale = base.filter((r) => ["testing", "retest", "growing", "hero", "declining", "delist"].includes(r.stage)).length;
    const withT = base.filter((r) => r.traffic).length;
    const showProfit = own() && L.rows.some((r) => r.profit_30d !== undefined);
    const r0 = L.rules;
    const head = ["SKU", Z("平台", "แพลตฟอร์ม"), Z("阶段", "ช่วง"), Z("访客", "ผู้เข้าชม"), Z("转化", "อัตราซื้อ"), Z("7 天", "7 วัน"), Z("30 天", "30 วัน"),
      ...(showProfit ? [Z("30 天利润", "กำไร 30 วัน")] : []), Z("建议动作", "สิ่งที่ควรทำ")];
    const body = rows.slice(0, 500).map((r) => `<tr><td><span class="mono oa-sku" data-p360="${esc(r.sku)}" data-notr>${esc(r.sku)}</span><div class="small muted" data-notr>${esc(r.name)} ${esc(r.variant || "")}</div></td>
      <td class="small">${esc(PLAT(r.platform))}</td>
      <td><span class="oa-stage ux-${LV[r.level] || ""}">${esc(Z(r.stage_label, r.stage_th))}</span>${r.days_live != null ? `<div class="small muted">${Z(`${Math.round(r.days_live)} 天`, `${Math.round(r.days_live)} วัน`)}${r.start_estimated ? Z("（估）", " (ประมาณ)") : ""}</div>` : ""}</td>
      <td class="num">${r.traffic ? n0(r.traffic.visitors) : "—"}</td>
      <td class="num ${r.traffic && r.traffic.conversion != null && r.traffic.conversion < 1.5 && (r.traffic.visitors || 0) >= 50 ? "warn" : ""}">${r.traffic && r.traffic.conversion != null ? r.traffic.conversion + "%" : "—"}</td>
      <td class="num">${r.qty_7d || ""}</td><td class="num"><b>${r.qty_30d || ""}</b></td>
      ${showProfit ? `<td class="num ${neg(r.profit_30d)}">${r.profit_30d ? m0(r.profit_30d) : ""}${r.below_floor ? ` <span class="bad small" title="${Z("售价低于最低价", "ราคาต่ำกว่าขั้นต่ำ")}">⚠</span>` : ""}</td>` : ""}
      <td class="small">${esc(Z(r.action, r.action_th))}</td></tr>`);
    const unmatched = TRF ? TRF.rows.filter((r) => !r.sku) : [];
    box.innerHTML = UX.kpis([
      { label: Z("在售", "กำลังขาย"), value: onSale, sub: Z(`共 ${base.length} 行`, `ทั้งหมด ${base.length} แถว`) },
      { label: Z("主推", "สินค้าหลัก"), value: cnt.hero || 0, tone: "ok", help: Z(`近 30 天卖到 ${r0.hero_qty_30d} 件以上`, `ขาย ≥ ${r0.hero_qty_30d} ชิ้นใน 30 วัน`) },
      { label: Z("测款中", "ช่วงทดสอบ"), value: (cnt.testing || 0) + (cnt.retest || 0), help: Z(`测款期 ${r0.test_days} 天，再测到 ${r0.retest_days} 天`, `ทดสอบ ${r0.test_days} วัน ทดสอบใหม่ถึง ${r0.retest_days} วัน`) },
      { label: Z("要处理", "ต้องจัดการ"), value: (cnt.rejected || 0) + (cnt.delist || 0) + (cnt.declining || 0) + (cnt.erp_off || 0), tone: (cnt.rejected || cnt.delist) ? "bad" : "",
        help: Z("审核不通过、建议下架、衰退、ERP 已下架", "ไม่ผ่านการตรวจ ควรปิดการขาย ขายลดลง ปิดใน ERP แล้ว") },
      { label: Z("有流量数据", "มีข้อมูลทราฟฟิก"), value: withT, help: Z("浏览器扩展在卖家后台采集的访客、转化率，按卖家 SKU 对上", "ผู้เข้าชมและอัตราซื้อที่ส่วนขยายเก็บจากหลังร้าน จับคู่ด้วย Seller SKU") },
    ]) + UX.tabs([["", Z("全部", "ทั้งหมด"), base.length], ...L.stage_order.filter((k) => cnt[k]).map((k) => [k, lab(k), cnt[k]])], STAGE, "stage")
      + tbl(head, body, Z("没有符合的商品", "ไม่มีสินค้าที่ตรง"))
      + (rows.length > 500 ? `<p class="small muted">${Z(`只显示前 500 行（共 ${rows.length}）`, `แสดง 500 แถวแรก (ทั้งหมด ${rows.length})`)}</p>` : "")
      + `<p class="small muted">${Z(`测款规则：测款期 ${r0.test_days} 天 · 再测截止 ${r0.retest_days} 天 · ${r0.decline_days} 天零销量算衰退 · ${r0.delist_days} 天零销量建议下架`,
        `กติกา: ทดสอบ ${r0.test_days} วัน · ทดสอบใหม่ถึง ${r0.retest_days} วัน · ไม่มียอด ${r0.decline_days} วัน = ขายลดลง · ${r0.delist_days} วัน = ควรปิดการขาย`)} ${UX.help(Z("在「设置 → 运营分析」可以改。测款期从第一次在售算，标「估」的是按上传 / 导出时间估的。",
          "แก้ได้ที่ ตั้งค่า → วิเคราะห์การขาย ช่วงทดสอบนับจากวันแรกที่ขาย \"ประมาณ\" = คิดจากเวลาอัปโหลด/ส่งออก"))}</p>`
      + (TRF ? `<details class="card oa-det"><summary><b>${Z("采集的后台页面", "หน้าหลังร้านที่เก็บมา")}</b> <span class="small muted">${TRF.pages.length}${unmatched.length ? Z(` · ${unmatched.length} 个商品没对上 SKU`, ` · ${unmatched.length} สินค้าจับคู่ SKU ไม่ได้`) : ""}</span>
          ${UX.help(Z("员工用浏览器扩展打开卖家中心的「商品表现 / 流量 / 关键词」页面，扩展自动采集，AI 识别成每个商品的访客、加购、订单、转化率。对不上 SKU 的：在平台后台把「卖家 SKU」填成 ERP 的 SKU。不保存平台密码、cookie 和买家信息。",
            "พนักงานเปิดหน้า「ประสิทธิภาพสินค้า / ทราฟฟิก / คีย์เวิร์ด」ในหลังร้านด้วยส่วนขยาย ระบบเก็บอัตโนมัติ AI อ่านเป็นผู้เข้าชม ใส่ตะกร้า ออเดอร์ อัตราซื้อ ที่จับคู่ไม่ได้: ตั้ง Seller SKU ให้ตรงกับ SKU ใน ERP ไม่เก็บรหัสผ่าน คุกกี้ หรือข้อมูลผู้ซื้อ"))}</summary>
          ${unmatched.length ? `<h4>${Z("没对上 SKU 的商品", "สินค้าที่จับคู่ SKU ไม่ได้")}</h4>` + tbl([Z("商品", "สินค้า"), Z("平台", "แพลตฟอร์ม"), Z("访客", "ผู้เข้าชม"), Z("订单", "ออเดอร์"), Z("转化", "อัตราซื้อ")],
            unmatched.slice(0, 50).map((r) => `<tr><td class="small" data-notr>${esc((r.name || "").slice(0, 60))}${r.seller_sku ? ` · <span class="mono">${esc(r.seller_sku)}</span>` : ""}</td><td>${esc(PLAT(r.platform))}</td>
              <td class="num">${n0(r.visitors)}</td><td class="num">${n0(r.orders)}</td><td class="num">${r.conversion != null ? r.conversion + "%" : "—"}</td></tr>`)) : ""}
          ${tbl([Z("时间", "เวลา"), Z("平台", "แพลตฟอร์ม"), Z("页面", "หน้า"), Z("商品行数", "จำนวนสินค้า")], TRF.pages.slice(0, 40).map((p) => `<tr><td class="small nowrap">${fmtTime(p.ts)}</td><td>${esc(PLAT(p.platform))}</td>
            <td class="small oa-url">${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener" data-notr>${esc((p.title || p.url || "").slice(0, 80))}</a>` : ""}</td><td class="num">${p.n_rows}</td></tr>`), Z("还没有采集过卖家后台数据", "ยังไม่เคยเก็บข้อมูลหลังร้าน"))}</details>` : "");
  }

  // ---------------- 商品表现 → 待确认的建议（运营写回：对接模块 /api/ops/changes，原来的「商品 → 运营改动」） ----------------
  let SG_ST = "pending";
  const FNAME = { title_th: ["泰文标题", "ชื่อภาษาไทย"], attributes: ["类目属性", "คุณสมบัติหมวดหมู่"], price: ["售价", "ราคาขาย"], active: ["上下架", "เปิด/ปิดขาย"] };
  const SG = { applied: ["已生效", "มีผลแล้ว", "ok"], pending: ["待确认", "รอยืนยัน", "warn"], rejected: ["已拒绝", "ปฏิเสธแล้ว", ""], reverted: ["已撤回", "ย้อนกลับแล้ว", ""] };
  const val = (k, v) => (k === "active" ? (v ? Z("上架", "เปิดขาย") : Z("下架", "ปิดขาย")) : k === "price" ? `฿${v}` : (typeof v === "object" && v !== null ? JSON.stringify(v) : String(v ?? Z("（空）", "(ว่าง)"))));
  function diff(c) {
    return Object.keys(c.after || {}).map((k) => {
      const nm = FNAME[k] ? Z(...FNAME[k]) : k;
      if (k === "attributes") {
        return Object.keys(c.after.attributes || {}).map((a) => `<div class="oa-diff"><b>${nm}</b> <span class="mono" data-notr>${esc(a)}</span>
          <span class="oc-old" data-notr>${esc(val("", c.before.attributes && c.before.attributes[a]))}</span> → <span class="oc-new" data-notr>${esc(val("", c.after.attributes[a]))}</span></div>`).join("");
      }
      return `<div class="oa-diff"><b>${nm}</b> <span class="oc-old" data-notr>${esc(val(k, (c.before || {})[k]))}</span> → <span class="oc-new" data-notr>${esc(val(k, c.after[k]))}</span></div>`;
    }).join("");
  }
  async function suggPage(box) {
    if (window.MODKIT && !MODKIT.enabled("link")) { box.innerHTML = UX.empty(Z("「店铺与系统对接」模块没开：没有运营写回的建议", "ไม่ได้เปิดโมดูลเชื่อมต่อ: ไม่มีคำแนะนำ")); return; }
    const f = F();
    const r = await api("/api/ops/changes?" + qs({ status: SG_ST, q: f.q }));
    const n = r.counts || {};
    const own_ = own();
    box.innerHTML = UX.kpis([
      { label: Z("待确认", "รอยืนยัน"), value: n.pending || 0, tone: n.pending ? "warn" : "ok" },
      { label: Z("已生效", "มีผลแล้ว"), value: n.applied || 0 }, { label: Z("已撤回", "ย้อนกลับแล้ว"), value: n.reverted || 0 }, { label: Z("已拒绝", "ปฏิเสธแล้ว"), value: n.rejected || 0 },
      { label: Z("写回方式", "วิธีเขียนกลับ"), value: r.mode === "confirm" ? Z("人工确认", "ยืนยันเอง") : Z("自动生效", "มีผลอัตโนมัติ"), html: false,
        help: Z("运营分析系统通过接口改泰文标题、属性、售价、上下架。在「设置 → AI 与对接 → 运营分析系统写回」切换：自动生效 / 只做建议（在这里确认后才生效）。硬性限制：售价不能低于最低价；每个 SKU 每天最多改 1 次价；只能下架不能删除。改过的产品要重新导出上传到平台才会生效。",
          "ระบบวิเคราะห์แก้ชื่อไทย คุณสมบัติ ราคา เปิด/ปิดขาย ผ่าน API สลับได้ที่「ตั้งค่า → AI และการเชื่อมต่อ」: มีผลอัตโนมัติ / แค่แนะนำ (ยืนยันที่นี่) ข้อจำกัด: ราคาต้องไม่ต่ำกว่าราคาขั้นต่ำ แก้ราคาได้วันละครั้งต่อ SKU ปิดขายได้แต่ลบไม่ได้ สินค้าที่แก้ต้องส่งออกและอัปโหลดใหม่") },
    ]) + UX.tabs([["pending", Z("待确认", "รอยืนยัน"), n.pending || 0], ["applied", Z("已生效", "มีผลแล้ว")], ["reverted", Z("已撤回", "ย้อนกลับแล้ว")], ["rejected", Z("已拒绝", "ปฏิเสธแล้ว")], ["", Z("全部", "ทั้งหมด")]], SG_ST, "sg")
      + (r.changes.length ? `<div class="oa-sugg">${r.changes.map((c) => {
        const st = SG[c.status] || [c.status, c.status, ""];
        return `<div class="card oa-sg"><div class="oa-sg-h"><span class="mono" data-p360="${esc(c.sku || c.product_id)}" data-notr>${esc(c.product_id)}${c.sku ? " · " + esc(c.sku) : ""}</span>
            ${UX.dot(st[2], Z(st[0], st[1]))}<span class="small muted">${fmtTime(c.ts)}${c.key_name ? ` · <span data-notr>${esc(c.key_name)}</span>` : ""}${c.decided_by ? ` · <span data-notr>${esc(c.decided_by)}</span>` : ""}</span></div>
          ${diff(c)}${c.reason ? `<div class="small"><b>${Z("原因", "เหตุผล")}：</b><span data-notr>${esc(c.reason)}</span></div>` : ""}
          ${own_ ? `<div class="row gap" style="margin-top:6px">${c.status === "pending" ? `<button class="mini primary" data-oc="approve" data-id="${c.id}">${Z("通过", "อนุมัติ")}</button><button class="mini" data-oc="reject" data-id="${c.id}">${Z("拒绝", "ปฏิเสธ")}</button>` : ""}
            ${c.status === "applied" ? `<button class="mini" data-oc="revert" data-id="${c.id}">↶ ${Z("撤回", "ย้อนกลับ")}</button>` : ""}</div>` : ""}</div>`;
      }).join("")}</div>` : UX.empty(SG_ST === "pending" ? Z("没有待确认的建议", "ไม่มีคำแนะนำรอยืนยัน") : Z("没有记录", "ไม่มีรายการ")));
    box.onclick = async (e) => {
      const t = e.target.closest('[data-ux-group="sg"] [data-ux-tab]');
      if (t) { SG_ST = t.dataset.uxTab; return show("ops_sugg"); }
      const b = e.target.closest("[data-oc]");
      if (!b) return;
      const a = b.dataset.oc;
      const msg = { approve: Z("通过这条修改？会马上写进产品资料。", "อนุมัติการแก้ไขนี้? จะบันทึกลงข้อมูลสินค้าทันที"), reject: Z("拒绝这条修改？", "ปฏิเสธการแก้ไขนี้?"),
        revert: Z("撤回这条修改？产品会恢复到改之前的值。", "ย้อนกลับการแก้ไขนี้? สินค้าจะกลับเป็นค่าก่อนแก้") }[a];
      if (!confirm(msg)) return;
      await busy(b, () => api(`/api/ops/changes/${b.dataset.id}/${a}`, { json: {} }));
      toast({ approve: Z("已通过", "อนุมัติแล้ว"), reject: Z("已拒绝", "ปฏิเสธแล้ว"), revert: Z("已撤回", "ย้อนกลับแล้ว") }[a]);
      show("ops_sugg");
    };
  }

  window.OPSA = { show, rerender: (tab) => { if (tab === "ops_life" && LIFE) lifeRender($("#ops-life")); else show(tab); } };
})();
