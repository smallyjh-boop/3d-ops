"use strict";
// 运营分析（v2.46）：今日待办（列表画法在内核 static/home.js 的 TODO_UI）、运营看板、商品生命周期、Lazada 数据。
// 界面文字用 Z(中文, 泰文) 直接写两种语言。
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const m = (v) => (v == null ? "—" : (v < 0 ? "-฿" : "฿") + Math.abs(Number(v)).toLocaleString(undefined, { maximumFractionDigits: 2 }));
  const n0 = (v) => (v == null ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 1 }));
  const pct = (v) => (v == null ? "—" : `${v}%`);
  const neg = (v) => (v != null && v < 0 ? "bad" : "");
  const PLAT = (p) => ({ lazada: "Lazada", shopee: "Shopee", tiktok: "TikTok", manual: Z("私下成交", "ขายตรง") }[p] || p || Z("其他", "อื่นๆ"));
  const day = (ts) => (ts ? fmtTime(ts).slice(0, 10) : "—");
  const BOX = { ops_todo: "ops-todo", ops_dash: "ops-dash", ops_life: "ops-life", ops_lazada: "ops-lz" };
  const own = () => typeof ME === "undefined" || !ME || ME.role === "owner";
  let CUR = "";

  async function show(tab) {
    if (!BOX[tab]) {           // v2.48：第二期的页面在 market.js / plan.js
      const o = Object.values(window.OPSB || {}).find((x) => x.tabs.includes(tab));
      return o ? o.show(tab) : undefined;
    }
    CUR = tab;
    const box = $("#" + BOX[tab]);
    if (!box) return;
    if (!box.innerHTML) box.innerHTML = `<p class="muted">${Z("加载中…", "กำลังโหลด…")}</p>`;
    try {
      if (tab === "ops_todo") return await todoPage(box);
      if (tab === "ops_dash") return await dashPage(box);
      if (tab === "ops_life") return await lifePage(box);
      if (tab === "ops_lazada") return await lzPage(box);
    } catch (e) { box.innerHTML = `<p class="bad">${esc(e.message)}</p>`; }
  }
  document.addEventListener("click", (e) => {
    const r = e.target.closest("[data-ops-reload]");
    if (r) busy(r, () => show(r.dataset.opsReload));
    const g = e.target.closest("[data-ops-go]");
    if (g) goTab(g.dataset.opsGo);
  });

  // ---------------- 今日待办 ----------------
  let SHOW_DONE = false;
  async function todoPage(box) {
    const d = await api("/api/todo" + (SHOW_DONE ? "?all=1" : ""));
    const open = d.items.filter((i) => !i.state).length;
    box.innerHTML = `<div class="row gap wrap" style="margin-bottom:8px"><b>${Z(`待办 ${open} 条`, `งานค้าง ${open} รายการ`)}</b>
        <label class="small"><input type="checkbox" data-todo-done ${SHOW_DONE ? "checked" : ""}> ${Z(`显示已完成 / 忽略的（${d.hidden}）`, `แสดงที่เสร็จ / ข้ามแล้ว (${d.hidden})`)}</label>
        <span class="muted small">${Z("完成 = 已经处理了；忽略 = 这件事不用管。同一件事以后有变化会重新出现。", "เสร็จ = จัดการแล้ว; ข้าม = ไม่ต้องสนใจ ถ้ามีการเปลี่ยนแปลงจะขึ้นมาใหม่")}</span></div>
      ${d.errors && d.errors.length ? `<div class="warn-box small">${d.errors.map((x) => `${esc(x.source)}：${esc(x.error)}`).join("<br>")}</div>` : ""}
      <div id="ops-todo-list"></div>${own() ? '<div id="ops-alerts" style="margin-top:16px"></div>' : ""}`;
    TODO_UI.render($("#ops-todo-list", box), d);
    $("#ops-todo-list", box).onclick = (e) => TODO_UI.act(e, () => show("ops_todo"));
    $("[data-todo-done]", box).onchange = (e) => { SHOW_DONE = e.target.checked; show("ops_todo"); };
    if (own()) await alertsCard($("#ops-alerts", box));
  }

  async function alertsCard(box) {
    const a = await api("/api/oa/alerts");
    const ch = a.channels.length ? a.channels.map((c) => (c === "line" ? "LINE" : "Telegram")).join(" + ") : Z("没有", "ยังไม่มี");
    box.innerHTML = `<div class="card"><h3>${Z("手机提醒", "แจ้งเตือนมือถือ")}</h3>
      <p class="small">${Z("今日待办里重要的事（超时未发货、差评、亏本订单、耗材不够、接口出错……）推到手机，同一件事只推一次。",
        "เรื่องสำคัญในงานวันนี้ (ส่งเกินเวลา รีวิวแย่ ออเดอร์ขาดทุน วัสดุไม่พอ API ผิดพลาด…) ส่งเข้ามือถือ เรื่องเดียวกันส่งครั้งเดียว")}</p>
      <p>${Z("状态", "สถานะ")}：<b class="${a.on ? "" : "warn"}">${a.on ? Z("开着", "เปิดอยู่") : Z("关着", "ปิดอยู่")}</b> · ${Z("推送到", "ส่งไปที่")}：<b>${esc(ch)}</b>
        <span class="muted small">${Z("（开关、LINE 设置在「设置 → 运营分析」）", "(เปิด/ปิดและตั้งค่า LINE ที่「ตั้งค่า → วิเคราะห์การขาย」)")}</span></p>
      <div class="row gap wrap"><button class="mini" data-al-test>${Z("发一条测试消息", "ส่งข้อความทดสอบ")}</button>
        <button class="mini" data-al-run>${Z("现在检查并推送", "ตรวจและส่งตอนนี้")}</button></div>
      <h4>${Z("哪些来源推送（不勾 = 只在待办里看，不推到手机）", "แหล่งที่ส่งแจ้งเตือน (ไม่ติ๊ก = ดูในงานวันนี้อย่างเดียว)")}</h4>
      <div class="row gap wrap">${a.sources.map((s) => `<label><input type="checkbox" data-al-src="${esc(s.id)}" ${a.muted.includes(s.id) ? "" : "checked"}> ${esc(Z(s.zh, s.th))}</label>`).join("")}</div>
      <h4>${Z("最近推送", "แจ้งเตือนล่าสุด")}</h4>
      <table class="grid"><tbody>${a.recent.slice(0, 30).map((r) => `<tr><td class="nowrap small">${fmtTime(r.ts)}</td><td>${esc(r.text)}</td>
        <td class="small nowrap">${r.sent ? Z("已推送", "ส่งแล้ว") : `<span class="bad" title="${esc(r.send_error || "")}">${Z("没推出去", "ยังส่งไม่ได้")}</span>`}</td></tr>`).join("")
        || `<tr><td class="muted">${Z("还没有", "ยังไม่มี")}</td></tr>`}</tbody></table></div>`;
    box.onclick = async (e) => {
      const t = e.target.closest("[data-al-test]");
      if (t) return busy(t, async () => { await api("/api/oa/alerts/test", { json: {} }); toast(Z("测试消息发出去了", "ส่งข้อความทดสอบแล้ว")); });
      const r = e.target.closest("[data-al-run]");
      if (r) return busy(r, async () => { const x = await api("/api/oa/alerts/run", { json: {} }); toast(Z(`新记 ${x.collected} 条，推送 ${x.sent} 条`, `บันทึกใหม่ ${x.collected} ส่ง ${x.sent}`)); alertsCard(box); });
    };
    box.onchange = async (e) => {
      const c = e.target.closest("[data-al-src]");
      if (c) await api("/api/oa/alerts/muted", { json: { source: c.dataset.alSrc, muted: !c.checked } });
    };
  }

  // ---------------- 运营看板 ----------------
  function kpi(label, s, cmp) {
    let delta = "";
    if (cmp && cmp.revenue) {
      const d = ((s.revenue - cmp.revenue) / cmp.revenue) * 100;
      delta = `<small class="${d >= 0 ? "ok" : "bad"}">${d >= 0 ? "▲" : "▼"} ${Math.abs(d).toFixed(0)}% ${Z("比前 7 天", "เทียบ 7 วันก่อน")}</small>`;
    }
    return `<div class="tile"><span>${label}</span><b>${m(s.revenue)}</b>
      <small>${Z("订单", "ออเดอร์")} ${s.n} · ${Z("利润", "กำไร")} <span class="${neg(s.profit)}">${m(s.profit)}</span>${s.margin != null ? ` · ${s.margin}%` : ""}</small>
      ${s.aftersales ? `<small>${Z("售后损失", "ความเสียหายหลังการขาย")} ${m(s.aftersales)} → ${Z("扣除后", "หลังหัก")} ${m(s.profit_after_aftersales)}</small>` : ""}${delta}</div>`;
  }
  function chart(days) {
    const W = 640, H = 140, P = 4;
    const mx = Math.max(1, ...days.map((d) => Math.max(d.revenue, 0)));
    const mn = Math.min(0, ...days.map((d) => d.profit));
    const span = mx - mn || 1, bw = (W - P * 2) / days.length;
    const y = (v) => H - P - ((v - mn) / span) * (H - P * 2);
    const bars = days.map((d, i) => `<rect x="${P + i * bw + bw * 0.15}" y="${y(Math.max(0, d.revenue))}" width="${bw * 0.7}" height="${Math.max(1, y(0) - y(Math.max(0, d.revenue)))}" class="${d.profit < 0 ? "oa-neg" : "oa-rev"}"><title>${d.day} ${Z("销售额", "ยอดขาย")} ${m(d.revenue)} · ${Z("利润", "กำไร")} ${m(d.profit)} · ${Z("订单", "ออเดอร์")} ${d.orders}</title></rect>`).join("");
    return `<svg viewBox="0 0 ${W} ${H}" class="oa-chart" preserveAspectRatio="none"><line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" class="oa-zero"/>${bars}</svg>
      <div class="small muted">${days[0].day} ~ ${days[days.length - 1].day} · ${Z("红色 = 当天亏损", "สีแดง = วันนั้นขาดทุน")}</div>`;
  }
  const card = (title, body, extra = "") => `<div class="card"><h3>${title}${extra ? ` <span class="muted small">${extra}</span>` : ""}</h3>${body}</div>`;
  const tbl = (head, rows, empty) => rows.length ? `<table class="grid"><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`
    : `<p class="muted">${empty || Z("没有", "ไม่มี")}</p>`;

  async function dashPage(box) {
    const d = await api("/api/oa/dashboard");
    const s = d.summary, sh = d.shipping, h = d.health, lz = d.lazada || {};
    const warn = [];
    if (h.orders_fee_estimated) warn.push(Z(`近 30 天 ${h.orders_fee_estimated}/${h.orders_30d} 单的平台费是按扣点估算的（设置里扣点 ${pct(Math.round((d.fee_rate_setting || 0) * 1000) / 10)}）：Lazada 财务流水拉下来以后按真实扣费算。`,
      `${h.orders_fee_estimated}/${h.orders_30d} ออเดอร์ใน 30 วันใช้ค่าธรรมเนียมประมาณ (ตั้งไว้ ${pct(Math.round((d.fee_rate_setting || 0) * 1000) / 10)}): ดึงรายการการเงิน Lazada แล้วจะใช้ค่าจริง`));
    if (h.orders_missing_data) warn.push(Z(`${h.orders_missing_data} 单商品没对上 SKU 或缺克数，成本偏低。`, `${h.orders_missing_data} ออเดอร์จับคู่ SKU ไม่ได้หรือไม่มีกรัม ต้นทุนจะต่ำกว่าจริง`));
    if ((lz.errors || []).length) warn.push(Z(`Lazada 数据有 ${lz.errors.length} 项拉不下来，看「Lazada 数据」页。`, `ข้อมูล Lazada ดึงไม่ได้ ${lz.errors.length} รายการ ดูที่หน้า「ข้อมูล Lazada」`));
    const fn = d.fin_net;
    const plat = d.platforms.map((p) => `<tr><td>${esc(PLAT(p.key))}</td><td class="num">${p.orders}</td><td class="num">${m(p.revenue)}</td><td class="num ${neg(p.profit)}">${m(p.profit)}</td><td class="num">${pct(p.margin)}</td></tr>`);
    const skus = d.skus.map((p) => `<tr><td><span class="mono" data-notr>${esc(p.key)}</span><div class="small muted" data-notr>${esc(p.name || "")}</div></td><td class="num">${p.qty}</td><td class="num">${m(p.revenue)}</td><td class="num ${neg(p.profit)}">${m(p.profit)}</td></tr>`);
    const loss = d.loss_orders.map((o) => `<tr><td>${esc(PLAT(o.platform))} <span class="mono" data-notr>${esc(o.order_no)}</span><div class="small muted">${day(o.order_time)}</div></td><td class="num">${m(o.revenue)}</td>
      <td class="num">${m(o.fee)}${o.fee_estimated ? ` <span class="warn small">${Z("估", "ประมาณ")}</span>` : ""}</td><td class="num">${m(o.cost)}</td><td class="num bad">${m(o.profit)}</td></tr>`);
    const ship = [...sh.overdue.map((o) => [o, "bad", Z("超时未发货", "เลยเวลาส่ง")]), ...sh.soon.map((o) => [o, "warn", Z("快到期", "ใกล้ครบกำหนด")])]
      .map(([o, c, l]) => `<div class="small"><span class="${c}">${l}</span> ${esc(PLAT(o.platform))} <span class="mono" data-notr>${esc(o.order_no)}</span>${o.hold ? ` <span class="warn">${Z("待审核", "รอตรวจ")}</span>` : ""}
        · ${o.hours_left < 0 ? Z(`已超 ${-o.hours_left} 小时`, `เกินมา ${-o.hours_left} ชั่วโมง`) : Z(`剩 ${o.hours_left} 小时`, `เหลือ ${o.hours_left} ชั่วโมง`)}</div>`).join("");
    const price = d.pricing.map((p) => `<tr><td><span class="mono" data-notr>${esc(p.sku)}</span><div class="small muted" data-notr>${esc(p.name)} ${esc(p.variant || "")}</div></td>
      <td class="num ${p.erp_low ? "bad" : ""}">${m(p.price)}</td><td>${p.platform_prices.map((x) => `${esc(PLAT(x.platform))} <b class="bad">${m(x.price)}</b>`).join("<br>") || "—"}</td>
      <td class="num">${m(p.floor_price)}</td><td class="num">${m(p.unit_cost)}</td></tr>`);
    const pr = d.production;
    const fees = (lz.fees || {});
    box.innerHTML = `${warn.length ? `<div class="warn-box small">${warn.join("<br>")}</div>` : ""}
      <div class="tiles">${kpi(Z("今天", "วันนี้"), s.today)}${kpi(Z("昨天", "เมื่อวาน"), s.yesterday)}${kpi(Z("近 7 天", "7 วันล่าสุด"), s.d7, s.prev7)}${kpi(Z("近 30 天", "30 วันล่าสุด"), s.d30)}
        ${fn ? `<div class="tile" data-ops-go="fin_overview"><span>${Z("近 30 天净利润（财务口径）", "กำไรสุทธิ 30 วัน (ตามบัญชี)")}</span><b class="${neg(fn.net)}">${m(fn.net)}</b>
          <small>${Z("扣了支出、固定费用、售后损失", "หักค่าใช้จ่าย ค่าคงที่ และความเสียหายหลังการขาย")}${fn.net_margin != null ? ` · ${fn.net_margin}%` : ""}</small></div>` : ""}</div>
      ${card(Z("近 30 天每日销售额", "ยอดขายรายวัน 30 วัน"), chart(d.daily))}
      <div class="lanes two">
        ${card(Z("发货时效", "ความตรงเวลาในการส่ง"), `<p class="small">${Z("待发货", "รอส่ง")} <b>${sh.to_ship}</b> · ${Z("超时", "เกินเวลา")} <b class="${sh.overdue_n ? "bad" : ""}">${sh.overdue_n}</b>
          · ${Z("快到期", "ใกล้ครบ")} <b>${sh.soon_n}</b> · ${Z("待审核", "รอตรวจ")} ${sh.on_hold} · ${Z("没有最晚发货时间", "ไม่มีกำหนดส่ง")} ${sh.no_deadline}</p>
          <p class="small">${Z("近 30 天准时发货率", "อัตราส่งตรงเวลา 30 วัน")} <b>${pct(sh.on_time_rate)}</b>（${Z("晚发", "ส่งช้า")} ${sh.late_30d} / ${sh.shipped_30d}）· ${Z("平均下单到发货", "เฉลี่ยสั่งถึงส่ง")} ${n0(sh.avg_ship_hours)} ${Z("小时", "ชม.")}</p>
          ${ship || `<p class="muted small">${Z("全部正常", "ปกติทั้งหมด")}</p>`}`)}
        ${card(Z("售后与拒收（近 30 天）", "หลังการขายและปฏิเสธรับ (30 วัน)"), `<table class="grid"><tbody>
          <tr><td>${Z("售后登记", "บันทึกหลังการขาย")}</td><td class="num">${d.aftersales.count} ${Z("单", "รายการ")} · ${Z("损失", "เสียหาย")} <b class="${d.aftersales.loss ? "bad" : ""}">${m(d.aftersales.loss)}</b></td></tr>
          <tr><td>${Z("货到付款拒收率", "อัตราปฏิเสธรับ COD")}</td><td class="num">${d.cod.cod_fail_rate == null ? "—" : `<b class="${d.cod.cod_fail_rate >= 10 ? "bad" : ""}">${d.cod.cod_fail_rate}%</b> (${d.cod.cod_failed}/${d.cod.cod_orders})`}</td></tr>
          <tr><td>${Z("拒收 / 派送失败", "ปฏิเสธรับ / ส่งไม่สำเร็จ")}</td><td class="num">${d.cod.delivery_failed}</td></tr>
          <tr><td>${Z("Lazada 退货退款申请", "คำขอคืนสินค้า/เงิน Lazada")}</td><td class="num">${(lz.reverse || {}).n || 0} · ${Z("退款", "คืนเงิน")} ${m((lz.reverse || {}).refund || 0)}</td></tr>
          </tbody></table>`)}
        ${card(Z("按平台（近 30 天）", "ตามแพลตฟอร์ม (30 วัน)"), tbl([Z("平台", "แพลตฟอร์ม"), Z("订单", "ออเดอร์"), Z("销售额", "ยอดขาย"), Z("利润", "กำไร"), Z("利润率", "อัตรากำไร")], plat))}
        ${card(Z("利润最高的 SKU（近 30 天）", "SKU กำไรสูงสุด (30 วัน)"), tbl(["SKU", Z("件数", "ชิ้น"), Z("销售额", "ยอดขาย"), Z("利润", "กำไร")], skus))}
        ${card(Z("亏本订单（近 30 天）", "ออเดอร์ขาดทุน (30 วัน)"), tbl([Z("订单", "ออเดอร์"), Z("销售额", "ยอดขาย"), Z("平台费", "ค่าธรรมเนียม"), Z("成本", "ต้นทุน"), Z("利润", "กำไร")], loss, Z("没有亏本订单", "ไม่มีออเดอร์ขาดทุน")), String(d.loss_orders.length))}
        ${card(Z("售价低于最低价", "ราคาต่ำกว่าราคาขั้นต่ำ"), tbl(["SKU", Z("ERP 售价", "ราคา ERP"), Z("平台上实际卖", "ราคาขายจริงบนแพลตฟอร์ม"), Z("最低价", "ราคาขั้นต่ำ"), Z("成本", "ต้นทุน")], price, Z("全部正常", "ปกติทั้งหมด")), String(d.pricing.length))}
        ${card("Lazada", `<table class="grid"><tbody>
          <tr><td>${Z("评价（近 30 天）", "รีวิว (30 วัน)")}</td><td class="num">${(lz.reviews || {}).n || 0} · ${Z("平均", "เฉลี่ย")} ${(lz.reviews || {}).avg ?? "—"} ★</td></tr>
          <tr><td>${Z("差评 / 没回复", "รีวิวแย่ / ยังไม่ตอบ")}</td><td class="num">${(lz.reviews || {}).bad || 0} / <b class="${(lz.reviews || {}).bad_open ? "bad" : ""}">${(lz.reviews || {}).bad_open || 0}</b></td></tr>
          <tr><td>${Z("真实扣点（财务流水）", "ค่าธรรมเนียมจริง (รายการการเงิน)")}</td><td class="num">${fees.rate == null ? "—" : `<b>${fees.rate}%</b>`} · ${Z("设置里", "ที่ตั้งไว้")} ${pct(Math.round((d.fee_rate_setting || 0) * 1000) / 10)}</td></tr>
          </tbody></table><button class="mini" data-ops-go="ops_lazada">${Z("看详情", "ดูรายละเอียด")}</button>`)}
        ${card(Z("生产与耗材", "การผลิตและวัสดุ"), (pr ? `<p class="small">${Z("排队", "คิว")} ${pr.queue_jobs} ${Z("个任务", "งาน")} / ${pr.queue_pcs} ${Z("件", "ชิ้น")} · ${n0(pr.queue_hours)} ${Z("打印小时", "ชม.พิมพ์")}
          ${pr.days_of_work != null ? ` · ${Z("约", "ประมาณ")} ${pr.days_of_work} ${Z("天的活", "วันงาน")}` : ""} · ${Z("待后处理", "รอเก็บงาน")} ${pr.post}</p>` : "")
          + (d.materials.map((x) => `<div class="small ${x.short ? "bad" : "warn"}">${esc(x.material)} ${esc(x.color)} · ${Z("剩", "เหลือ")} ${n0(x.kg)} kg · ${x.short ? Z("不够打待打印的单", "ไม่พอพิมพ์งานที่รอ") : Z(`约 ${n0(x.days_left)} 天用完`, `หมดในราว ${n0(x.days_left)} วัน`)}</div>`).join("") || `<p class="muted small">${Z("耗材够用", "วัสดุพอใช้")}</p>`))}
        ${marketCard(d.market || {})}
        ${card(Z("数据健康", "ความครบของข้อมูล"), `<table class="grid"><tbody>${[
          [Z("SKU 总数", "จำนวน SKU"), h.skus], [Z("缺克数或时长的 SKU", "SKU ที่ไม่มีกรัมหรือเวลาพิมพ์"), h.skus_missing_cost],
          [Z("成本数据不全的订单（30 天）", "ออเดอร์ที่ข้อมูลต้นทุนไม่ครบ (30 วัน)"), h.orders_missing_data],
          [Z("平台费是估算的订单（30 天）", "ออเดอร์ที่ค่าธรรมเนียมเป็นการประมาณ (30 วัน)"), `${h.orders_fee_estimated} / ${h.orders_30d}`],
          [Z("没对上产品的 SKU", "SKU ที่จับคู่สินค้าไม่ได้"), h.unknown_skus.join(", ") || 0],
          [Z("Lazada 数据上次同步", "ซิงค์ข้อมูล Lazada ล่าสุด"), lz.last_ok ? fmtTime(lz.last_ok) : "—"]]
          .map(([k, v]) => `<tr><td>${k}</td><td class="num" data-notr>${esc(v)}</td></tr>`).join("")}</tbody></table>
          <p class="small muted">${d.breakdown_source === "fin" ? Z("利润和「财务」模块同一个算法（平台、SKU 的数直接取自财务）。", "กำไรใช้วิธีคิดเดียวกับโมดูลการเงิน") : ""}</p>`)}
      </div>`;
  }

  // v2.48：看板上的「市场与计划」卡片（第二期：卖家后台流量、竞品动态、计划进度、下一个大促）
  function marketCard(mk) {
    const t = mk.traffic, nc = mk.next_campaign;
    const parts = [];
    if (nc) parts.push(`<p class="small">${Z("下一个大促", "แคมเปญถัดไป")}：<b data-notr>${esc(Z(nc.name, nc.name_th))}</b> ${nc.start}（${Z(`还有 ${nc.days_left} 天`, `อีก ${nc.days_left} วัน`)}）
      · ${Z("预计", "คาด")} ${n0(nc.expected_orders)} ${Z("单/天", "ออเดอร์/วัน")}${nc.over_capacity ? ` <b class="bad">${Z("超过产能", "เกินกำลังผลิต")}</b>` : ""} <button class="mini" data-ops-go="ops_cal">${Z("日历", "ปฏิทิน")}</button></p>`);
    if ((mk.plans || []).length) parts.push(`<p class="small">${Z("进行中的计划", "แผนที่กำลังทำ")}：${mk.plans.map((p) => `<span class="mono" data-notr>${esc(p.sku)}</span> <b class="${p.status === "far" ? "bad" : p.status === "behind" ? "warn" : "ok"}">${esc(Z(p.status_label, p.status_th))}</b> ${p.cum_actual}/${p.cum_target}`).join(" · ")}
      <button class="mini" data-ops-go="ops_plans">${Z("计划", "แผน")}</button></p>`);
    if ((mk.comp_events || []).length) parts.push(`<h4>${Z("竞品动态（近 7 天）", "ความเคลื่อนไหวคู่แข่ง (7 วัน)")}</h4>` + mk.comp_events.map((e) => `<div class="small" data-notr>${esc(Z(e.text, e.text_th || e.text))}</div>`).join(""));
    if (t) parts.push(`<h4>${Z("卖家后台流量（访客最多）", "ทราฟฟิกหลังร้าน (ผู้เข้าชมมากสุด)")} <span class="small muted">${fmtTime(t.last_ts)}</span></h4>`
      + t.top.map((r) => `<div class="small"><span class="mono" data-notr>${esc(r.sku || r.name || "")}</span> ${Z("访客", "ผู้เข้าชม")} ${n0(r.visitors)} · ${Z("订单", "ออเดอร์")} ${n0(r.orders)} · ${Z("转化", "อัตราซื้อ")} ${r.conversion != null ? r.conversion + "%" : "—"}</div>`).join("")
      + (t.low_conv.length ? `<div class="small warn">${Z("转化率最低", "อัตราซื้อต่ำสุด")}：${t.low_conv.map((r) => `<span data-notr>${esc(r.sku || r.name || "")}</span> ${r.conversion}%`).join(" · ")}</div>` : "")
      + `<button class="mini" data-ops-go="ops_traffic">${Z("流量数据", "ข้อมูลทราฟฟิก")}</button>`);
    if (!parts.length) return "";
    return card(Z("市场与计划", "ตลาดและแผน"), parts.join(""));
  }

  // ---------------- 商品生命周期 ----------------
  let LIFE = null, STAGE = "", LPLAT = "", LQ = "";
  async function lifePage(box) {
    LIFE = await api("/api/oa/lifecycle");
    const r = LIFE.rules;
    box.innerHTML = `<div class="chips" id="oa-stage"></div>
      <div class="row gap wrap" style="margin:6px 0"><select id="oa-lplat"><option value="">${Z("全部平台", "ทุกแพลตฟอร์ม")}</option><option value="lazada">Lazada</option><option value="shopee">Shopee</option></select>
        <input id="oa-lq" placeholder="${Z("SKU / 名称", "SKU / ชื่อ")}" value="${esc(LQ)}"></div>
      <div id="oa-ltable"></div>
      <p class="small muted">${Z(`测款规则：测款期 ${r.test_days} 天 · 再测截止 ${r.retest_days} 天 · 近 30 天卖 ≥ ${r.hero_qty_30d} 件算主推 · ${r.decline_days} 天零销量算衰退 · ${r.delist_days} 天零销量建议下架（设置 → 运营分析 可改）。测款期从第一次在售算，标「估」的是按上传 / 导出时间估的。`,
        `กติกาทดสอบ: ช่วงทดสอบ ${r.test_days} วัน · ทดสอบใหม่ถึง ${r.retest_days} วัน · ขาย ≥ ${r.hero_qty_30d} ชิ้น/30 วัน = สินค้าหลัก · ไม่มียอด ${r.decline_days} วัน = ขายลดลง · ไม่มียอด ${r.delist_days} วัน = ควรปิดการขาย (แก้ได้ที่ ตั้งค่า → วิเคราะห์การขาย) "ประมาณ" = คิดจากเวลาอัปโหลด/ส่งออก`)}</p>`;
    $("#oa-lplat", box).value = LPLAT;
    $("#oa-lplat", box).onchange = (e) => { LPLAT = e.target.value; lifeRender(); };
    $("#oa-lq", box).oninput = (e) => { LQ = e.target.value; lifeRender(); };
    $("#oa-stage", box).onclick = (e) => { const b = e.target.closest("[data-stage]"); if (b) { STAGE = b.dataset.stage; lifeRender(); } };
    lifeRender();
  }
  function lifeRender() {
    const L = LIFE;
    const lab = (k) => Z(L.stages[k].label, L.stages[k].th);
    $("#oa-stage").innerHTML = [["", Z("全部", "ทั้งหมด"), L.rows.length], ...L.stage_order.filter((k) => L.counts[k]).map((k) => [k, lab(k), L.counts[k]])]
      .map(([k, l, n]) => `<button class="chip ${k === STAGE ? "on" : ""}" data-stage="${k}">${esc(l)} <b>${n}</b></button>`).join("");
    const q = LQ.toLowerCase();
    const rows = L.rows.filter((r) => (!STAGE || r.stage === STAGE) && (!LPLAT || r.platform === LPLAT) && (!q || `${r.sku} ${r.name}`.toLowerCase().includes(q)));
    const lv = { bad: "bad", warn: "warn", ok: "ok", good: "ok", info: "", mute: "muted" };
    $("#oa-ltable").innerHTML = tbl(["SKU", Z("平台", "แพลตฟอร์ม"), Z("阶段", "ช่วง"), Z("在售天数", "วันที่ขาย"), Z("7 天", "7 วัน"), Z("30 天", "30 วัน"), Z("累计", "รวม"),
      Z("30 天利润", "กำไร 30 วัน"), Z("售价", "ราคา"), Z("访客 / 转化（后台）", "ผู้เข้าชม / อัตราซื้อ"), Z("建议动作", "สิ่งที่ควรทำ")],
      rows.slice(0, 600).map((r) => `<tr><td><span class="mono" data-notr>${esc(r.sku)}</span><div class="small muted" data-notr>${esc(r.name)} ${esc(r.variant || "")}</div></td>
        <td>${esc(PLAT(r.platform))}</td><td><b class="${lv[r.level] || ""}">${esc(Z(r.stage_label, r.stage_th))}</b></td>
        <td class="num">${r.days_live == null ? "—" : r.days_live}${r.start_estimated && r.days_live != null ? ` <span class="warn small">${Z("估", "ประมาณ")}</span>` : ""}</td>
        <td class="num">${r.qty_7d}</td><td class="num">${r.qty_30d}</td><td class="num">${r.qty_total}</td><td class="num ${neg(r.profit_30d)}">${m(r.profit_30d)}</td>
        <td class="num ${r.below_floor ? "bad" : ""}" title="${Z("最低价", "ราคาขั้นต่ำ")} ${m(r.floor_price)} · ${Z("成本", "ต้นทุน")} ${m(r.unit_cost)}">${m(r.price)}</td>
        <td class="num small" title="${esc((r.traffic && r.traffic.period_text) || "")}">${r.traffic ? `${n0(r.traffic.visitors)}${r.traffic.conversion != null ? ` / ${r.traffic.conversion}%` : ""}` : "—"}</td>
        <td class="small">${esc(Z(r.action, r.action_th))}</td></tr>`), Z("没有符合的商品", "ไม่มีสินค้าที่ตรง"))
      + (rows.length > 600 ? `<p class="small muted">${Z(`只显示前 600 行（共 ${rows.length}）`, `แสดง 600 แถวแรก (ทั้งหมด ${rows.length})`)}</p>` : "");
  }

  // ---------------- Lazada 数据 ----------------
  let LZ_DAYS = 30, RV_FILTER = "bad";
  async function lzPage(box) {
    const d = await api(`/api/oa/lazada?days=${LZ_DAYS}`);
    if (!d.shops.length) {
      box.innerHTML = `<p class="warn">${Z("还没有开着的 Lazada 店铺：先到「设置 → AI 与对接 → 店铺对接」接上 Lazada。", "ยังไม่มีร้าน Lazada ที่เปิดใช้: ไปเชื่อมที่「ตั้งค่า → AI และการเชื่อมต่อ → เชื่อมต่อร้าน」ก่อน")}</p>`;
      return;
    }
    const st = d.status.map((s) => `<tr><td data-notr>${esc(s.shop)}</td><td>${esc(Z(s.zh, s.th))}</td><td class="small">${s.last_ok ? fmtTime(s.last_ok) : "—"}</td>
      <td class="small">${s.error ? `<span class="bad">${esc(s.error)}</span>${s.hint ? `<div><b>${Z("怎么办", "ต้องทำอะไร")}：</b>${esc(Z(s.hint, s.hint_th || s.hint))}</div>` : ""}` : (s.last_ok ? `<span class="ok">${Z("正常", "ปกติ")}</span>` : Z("还没同步过", "ยังไม่เคยซิงค์"))}</td></tr>`);
    const every = Number(d.sync_min || 0);
    let html = `<div class="row gap wrap" style="margin-bottom:8px">
        <select data-lz-days>${[7, 30, 90].map((x) => `<option value="${x}" ${x === LZ_DAYS ? "selected" : ""}>${Z(`近 ${x} 天`, `${x} วันล่าสุด`)}</option>`).join("")}</select>
        ${own() ? `<button data-lz-sync>${Z("立即同步", "ซิงค์ตอนนี้")}</button>` : ""}
        <span class="small muted">${every ? Z(`每 ${every} 分钟自动同步一次`, `ซิงค์อัตโนมัติทุก ${every} นาที`) : Z("自动同步关着（设置 → 运营分析）", "ปิดซิงค์อัตโนมัติ (ตั้งค่า → วิเคราะห์การขาย)")}</span></div>
      ${card(Z("同步状态", "สถานะการซิงค์"), tbl([Z("店铺", "ร้าน"), Z("数据", "ข้อมูล"), Z("上次成功", "สำเร็จล่าสุด"), Z("情况", "สถานะ")], st)
        + `<p class="small muted">${Z("用的是「店铺对接」里授权的 Lazada 应用。显示没有权限时：到 open.lazada.com 的 App Console 给应用申请对应的 API 权限，批下来后重新授权店铺。",
          "ใช้แอป Lazada ที่อนุญาตไว้ใน「เชื่อมต่อร้าน」 ถ้าขึ้นว่าไม่มีสิทธิ์: ขอสิทธิ์ API ใน App Console ที่ open.lazada.com แล้วอนุญาตร้านใหม่")}</p>`)}`;
    if (own() && d.fees) {
      const f = d.fees;
      html += card(Z("真实扣点（财务流水）", "ค่าธรรมเนียมจริง (รายการการเงิน)"), `<p>${Z("商品金额", "ยอดสินค้า")} ${m(f.item_amount)} · ${Z("平台扣了", "แพลตฟอร์มหัก")} <b>${m(f.deducted)}</b>
        · ${Z("扣点", "อัตรา")} <b>${pct(f.rate)}</b>${f.credits ? ` · ${Z("平台补贴 / 返还", "เงินคืน/อุดหนุน")} ${m(f.credits)}` : ""}</p>`
        + tbl([Z("费用名", "รายการ"), Z("金额", "จำนวน"), Z("占商品金额", "% ของยอดสินค้า"), Z("行数", "แถว")],
          f.fees.map((x) => `<tr><td data-notr>${esc(x.fee_name)}</td><td class="num ${neg(x.amount)}">${m(x.amount)}</td><td class="num">${pct(x.rate)}</td><td class="num">${x.lines}</td></tr>`))
        + `<p class="small muted">${Z("拉到了商品金额那一行的订单，流水自动记进「财务 → 平台对账」，利润按真实扣费算。", "ออเดอร์ที่มีแถวยอดสินค้าแล้ว จะบันทึกเข้า「การเงิน → กระทบยอดแพลตฟอร์ม」อัตโนมัติ และคิดกำไรจากค่าธรรมเนียมจริง")}</p>`);
    }
    const rv = d.reviews.filter((r) => RV_FILTER === "all" || (RV_FILTER === "bad" ? r.rating != null && r.rating <= 3 : !r.reply));
    html += card(Z("评价", "รีวิว"), `<div class="chips">${[["bad", Z("差评（≤ 3 星）", "รีวิวแย่ (≤ 3 ดาว)")], ["open", Z("没回复", "ยังไม่ตอบ")], ["all", Z("全部", "ทั้งหมด")]]
        .map(([k, l]) => `<button class="chip ${k === RV_FILTER ? "on" : ""}" data-rv-f="${k}">${l}</button>`).join("")}</div>`
      + tbl([Z("时间", "เวลา"), Z("商品", "สินค้า"), Z("星", "ดาว"), Z("内容", "ข้อความ"), Z("回复", "คำตอบ")], rv.map((r) => `<tr>
        <td class="small nowrap">${fmtTime(r.created)}<div class="muted" data-notr>${esc(r.shop)}</div></td>
        <td class="small" data-notr>${esc(r.item_name || r.item_id)}${r.product_code ? `<div class="muted mono">${esc(r.product_code)}</div>` : ""}<div class="muted">${Z("订单", "ออเดอร์")} ${esc(r.order_id)}</div></td>
        <td class="num ${r.rating != null && r.rating <= 3 ? "bad" : ""}"><b>${r.rating ?? "—"}</b>★</td><td data-notr>${esc(r.content || "")}${r.images ? ` <span class="muted small">📷${r.images}</span>` : ""}</td>
        <td class="small">${r.reply ? `<span data-notr>${esc(r.reply)}</span>${r.reply_by ? `<div class="muted">${esc(r.reply_by)} ${fmtTime(r.replied_at)}</div>` : ""}`
          : (r.can_reply ? `<textarea rows="2" maxlength="500" data-rv-text="${esc(r.review_id)}" placeholder="${Z("写回复（泰文）", "เขียนคำตอบ")}"></textarea>
            <button class="mini" data-rv-send="${esc(r.review_id)}" data-shop="${r.shop_id}">${Z("回复", "ตอบ")}</button>` : `<span class="muted">${Z("不能回复", "ตอบไม่ได้")}</span>`)}</td></tr>`),
        Z("没有评价", "ไม่มีรีวิว")));
    if (own() && d.reverse) {
      html += card(Z("退货退款", "คืนสินค้า / คืนเงิน"), tbl([Z("时间", "เวลา"), Z("订单", "ออเดอร์"), Z("类型", "ประเภท"), "SKU", Z("原因", "เหตุผล"), Z("状态", "สถานะ"), Z("退款", "คืนเงิน")],
        d.reverse.map((r) => `<tr><td class="small nowrap">${fmtTime(r.created)}</td><td class="mono" data-notr>${esc(r.order_no)}</td>
          <td>${esc({ RETURN: Z("退货退款", "คืนสินค้า"), ONLY_REFUND: Z("仅退款", "คืนเงินอย่างเดียว"), CANCEL: Z("取消", "ยกเลิก") }[(r.request_type || "").toUpperCase()] || r.request_type)}</td>
          <td class="mono small" data-notr>${esc(r.seller_sku)}</td><td class="small" data-notr>${esc(r.reason)}</td>
          <td class="small ${r.open ? "warn" : "muted"}" data-notr>${esc(r.status)}</td><td class="num">${m(r.refund_amount)}</td></tr>`), Z("没有退货退款", "ไม่มีการคืนสินค้า")));
    }
    if (own() && d.performance) {
      html += card(Z("店铺表现", "ประสิทธิภาพร้าน"), d.performance.map((p) => `<h4 data-notr>${esc(p.shop)} <span class="small muted">${fmtTime(p.at)}</span></h4>`
        + tbl([Z("指标", "ตัวชี้วัด"), Z("现在", "ตอนนี้"), Z("要求", "เกณฑ์")], p.metrics.map((x) => `<tr><td data-notr>${esc(x.name)}</td>
          <td class="num ${x.ok === false ? "bad" : x.ok ? "ok" : ""}"><b>${esc(x.value)}</b></td><td class="num" data-notr>${esc(x.target || "")}</td></tr>`))).join("")
        || `<p class="muted">${Z("还没同步过", "ยังไม่เคยซิงค์")}</p>`);
    }
    box.innerHTML = html;
    box.onchange = (e) => { const s = e.target.closest("[data-lz-days]"); if (s) { LZ_DAYS = Number(s.value); show("ops_lazada"); } };
    box.onclick = async (e) => {
      const f = e.target.closest("[data-rv-f]");
      if (f) { RV_FILTER = f.dataset.rvF; return show("ops_lazada"); }
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

  window.OPSA = { show };
})();
