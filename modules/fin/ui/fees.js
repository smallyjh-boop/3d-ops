"use strict";
// 财务 → 平台费率（v2.53）：数字卡片 → 走势图 → 店铺 × 类目表（每个费用项的比例、合计、来源 实际 / 默认、样本订单、更新时间）→ 默认费率（可改）。
// 费率由平台结算流水算出来（Lazada 接口、Shopee 导入的报表），样本不够就退回店铺整体，再退回这里的默认值。
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const E = (s) => UX.esc(s);
  const pc = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);
  const rate = (pct, fixed) => (pct || fixed ? `${pc(pct)}${fixed ? ` + ฿${fixed}` : ""}` : "—");
  const ITEMS = ["commission", "payment", "shipping", "campaign", "other"];
  const ITEM_NAME = { commission: ["佣金", "คอมมิชชั่น"], payment: ["支付手续费", "ค่าชำระเงิน"], shipping: ["运费差额", "ส่วนต่างค่าส่ง"],
    campaign: ["活动 / 优惠券", "แคมเปญ/คูปอง"], other: ["其他", "อื่นๆ"], default: ["默认扣点", "ค่าเริ่มต้น"] };
  const PLAT = { lazada: "Lazada", shopee: "Shopee" };
  let D = null, PF = "", BOX = null;
  try { PF = localStorage.getItem("fin_fee_plat") || ""; } catch { /* 忽略 */ }

  const when = (t) => (t ? fmtTime(t).slice(0, 16) : "—");
  const src = (s, th) => `<span class="${s === "actual" ? "ok" : "muted"}">${Z(s === "actual" ? "实际" : "默认", s === "actual" ? "จริง" : "ค่าเริ่มต้น")}</span>`;

  function kpis() {
    const k = D.kpis, sp = D.shopee;
    const card = (p) => ({ label: Z(`${PLAT[p]} 综合费率`, `ค่าธรรมเนียมรวม ${PLAT[p]}`), value: rate(k[p].pct, k[p].fixed), tone: k[p].source === "actual" ? "ok" : "",
      sub: k[p].source === "actual" ? Z(`实际 · 近 30/90 天 ${k[p].orders} 单`, `จริง · 30/90 วัน ${k[p].orders} ออเดอร์`)
        : Z(`默认 ${pc(k[p].default_pct)} · 结算数据不够`, `ค่าเริ่มต้น ${pc(k[p].default_pct)} · ข้อมูลไม่พอ`),
      help: Z("该平台默认店铺现在用的费率：有足够的结算数据就用实际费率，否则用下面设置的默认值。", "อัตราที่ร้านเริ่มต้นของแพลตฟอร์มใช้อยู่ ถ้าข้อมูลพอใช้อัตราจริง ไม่พอใช้ค่าเริ่มต้นด้านล่าง") });
    const shopLv = D.rows.filter((r) => r.category === "*");
    const act = D.rows.filter((r) => r.category !== "*" && r.enough).length;
    const all = D.rows.filter((r) => r.category !== "*").length;
    return UX.kpis([card("lazada"), card("shopee"),
      { label: Z("店铺 × 类目 用实际费率", "ร้าน × หมวด ที่ใช้อัตราจริง"), value: `${act} / ${all}`, sub: Z(`样本 ≥ ${D.min_orders} 单才算实际`, `ต้องมีอย่างน้อย ${D.min_orders} ออเดอร์`) },
      { label: Z("店铺数据", "ร้านที่มีข้อมูล"), value: shopLv.length, sub: Z("有结算流水的店铺", "ร้านที่มีรายการชำระเงิน") },
      { label: Z("Shopee 报表", "รายงาน Shopee"), value: sp.last_import ? Z(`${sp.days} 天前`, `${sp.days} วันก่อน`) : Z("没导入过", "ยังไม่เคยนำเข้า"),
        tone: sp.stale ? "warn" : "ok", sub: Z("超过 7 天会进今日待办", "เกิน 7 วันจะเข้ารายการงานวันนี้"), go: "tab:fin_settle" }]);
  }

  function trend() {
    const keys = Object.keys(D.trend || {});
    if (!keys.length) return UX.empty(Z("还没有费率走势（算过几天之后才有）", "ยังไม่มีแนวโน้ม (ต้องคำนวณหลายวันก่อน)"));
    return `<div class="ux-kpis">${keys.map((k) => {
      const [p, shop] = k.split("|"); const pts = D.trend[k]; const last = pts[pts.length - 1];
      return UX.kpis([{ label: `${PLAT[p] || p}${shop ? " · " + shop : ""}`, value: rate(last.pct, last.fixed), spark: pts.map((x) => x.pct * 100),
        sub: `${pts[0].day} ~ ${last.day}` }]);
    }).join("")}</div>`;
  }

  function undoBox() {
    const bs = D.recalc_batches || [];
    if (!bs.length) return "";
    return UX.card({ tone: "", title: Z("最近一次「重算建议价」可撤销", "ล้างราคาที่ตั้งเอง ย้อนกลับได้"),
      body: bs.map((b) => `<div class="row gap"><span>${E(PLAT[b.platform] || b.platform)} · <span data-notr>${E(b.shop || "—")}</span> · ${when(b.at)} · <span data-notr>${E(b.by || "")}</span> ·
        ${Z(`${b.products} 个产品 ${b.n} 个变体的手动价被清掉`, `ล้างราคาที่ตั้งเอง ${b.products} สินค้า ${b.n} ตัวเลือก`)}</span>
        <button class="mini" data-fe-undo="${E(b.batch)}">${Z("撤销（恢复手动价）", "ย้อนกลับ (คืนราคาที่ตั้งเอง)")}</button></div>`).join("") });
  }

  function eventsBox() {
    if (!D.events.length) return "";
    const g = {};
    D.events.forEach((e) => { (g[`${e.platform}|${e.shop}`] = g[`${e.platform}|${e.shop}`] || []).push(e); });
    return Object.keys(g).map((k) => {
      const [p, shop] = k.split("|"); const a = D.affected[k] || { n: 0, names: [] };
      const chg = g[k].map((e) => `${Z(ITEM_NAME[e.item][0], ITEM_NAME[e.item][1])} ${pc(e.old)} → ${pc(e.new)}`).join("；");
      return UX.card({ tone: a.below_cost ? "bad" : "warn", title: Z(`${PLAT[p]} 费率变了 · ${shop || "全部店铺"}`, `อัตรา ${PLAT[p]} เปลี่ยน · ${shop || "ทุกร้าน"}`),
        body: `<p>${E(chg)}</p><p class="small">${a.n ? Z(`按新费率有 ${a.n} 个产品利润低于最低加价率${a.below_cost ? `，其中 ${a.below_cost} 个已经亏本` : ""}：`, `มี ${a.n} สินค้ากำไรต่ำกว่าเกณฑ์${a.below_cost ? ` ขาดทุน ${a.below_cost} รายการ` : ""}: `) : Z("目前没有产品因此低于最低加价率。", "ตอนนี้ไม่มีสินค้าที่ต่ำกว่าเกณฑ์")}
          <span data-notr>${E((a.names || []).join("、"))}</span></p>
          <div class="row gap">${a.n ? `<button class="mini primary" data-fe-recalc="${E(k)}">${Z("按新费率重算建议价", "คำนวณราคาแนะนำใหม่ตามอัตราใหม่")}</button>` : ""}
          <button class="mini" data-fe-ack="${E(k)}">${Z("知道了", "รับทราบ")}</button></div>` });
    }).join("");
  }

  function table() {
    const rows = D.rows.filter((r) => !PF || r.platform === PF);
    if (!rows.length) return UX.empty(Z("还没有结算流水可算。Lazada 接口同步后、Shopee 导入报表后这里会出现。", "ยังไม่มีรายการชำระเงิน จะแสดงหลังซิงค์ Lazada หรือนำเข้ารายงาน Shopee"));
    return `<div class="tbl-scroll"><table class="grid"><thead><tr><th>${Z("平台 · 店铺", "แพลตฟอร์ม · ร้าน")}</th><th>${Z("类目", "หมวดหมู่")}</th>
      ${ITEMS.map((k) => `<th>${Z(ITEM_NAME[k][0], ITEM_NAME[k][1])}</th>`).join("")}<th>${Z("合计", "รวม")}</th><th>${Z("来源", "ที่มา")}</th>
      <th>${Z("样本订单 30/90 天", "ออเดอร์ 30/90 วัน")}</th><th>${Z("更新时间", "อัปเดต")}</th></tr></thead><tbody>${rows.map((r) => {
      const by = {}; (r.items || []).forEach((x) => { by[x.key] = x; });
      const cat = r.category === "*" ? `<b>${Z("全部类目（店铺整体）", "ทุกหมวด (ทั้งร้าน)")}</b>` : (r.category === "-" ? Z("未分类", "ไม่มีหมวด") : `<span data-notr>${E(r.cat_label || r.category)}</span>`);
      return `<tr class="${r.category === "*" ? "fe-shop" : ""}"><td data-notr>${E(PLAT[r.platform] || r.platform)} · ${E(r.shop || "—")}</td><td>${cat}</td>
        ${ITEMS.map((k) => `<td class="num" title="${E(((by[k] || {}).names || []).map((n) => TH() ? thName(n) : zhName(n)).join("、"))}">${by[k] ? rate(by[k].pct, by[k].fixed) : "—"}</td>`).join("")}
        <td class="num"><b>${rate(r.pct, r.fixed)}</b></td><td>${src(r.source)}${r.category !== "*" && r.used === "shop" ? `<div class="small muted">${Z("用店铺整体", "ใช้อัตราทั้งร้าน")}</div>` : ""}</td>
        <td class="num ${r.enough ? "" : "warn"}">${r.orders30} / ${r.orders90}</td><td class="small muted">${when(r.updated_at)}</td></tr>`;
    }).join("")}</tbody></table></div>
    <div class="small muted">${Z(`样本不到 ${D.min_orders} 单的店铺 × 类目 → 用店铺整体费率；店铺整体也不够 → 用下面的默认值。`, `ถ้าตัวอย่างไม่ถึง ${D.min_orders} ออเดอร์ ใช้อัตราทั้งร้าน และถ้ายังไม่พอใช้ค่าเริ่มต้นด้านล่าง`)}</div>`;
  }
  // 费用名鼠标提示：中文界面显示中文名，泰文界面显示泰文名（运营模块 fee_label 的同一套）
  const NAMES = {};
  const zhName = (n) => (NAMES[n] ? NAMES[n].zh : n);
  const thName = (n) => (NAMES[n] ? NAMES[n].th : n);

  function defaults() {
    const d = D.defaults;
    const cats = D.categories.map((c) => `<option value="${E(c.category)}">${E(c.label)}</option>`).join("");
    return `<div class="row gap wrap">${["lazada", "shopee"].map((p) => `<label>${PLAT[p]} ${Z("默认扣点 %", "ค่าเริ่มต้น %")}
        <input type="number" step="0.1" min="0" max="89" data-fe-def="${p}" value="${(d.platform[p] * 100).toFixed(1)}" style="width:6rem"></label>`).join("")}
      <label>${Z("样本至少几单才算「实际」", "ขั้นต่ำกี่ออเดอร์ถึงนับเป็น「จริง」")} <input type="number" min="1" data-fe-min value="${D.min_orders}" style="width:5rem"></label>
      <button class="mini primary" data-fe-save>${Z("保存", "บันทึก")}</button></div>
      <h4>${Z("类目默认费率（可选，没有真实数据时优先于平台默认）", "ค่าเริ่มต้นตามหมวด (ไม่บังคับ ใช้ก่อนค่าเริ่มต้นของแพลตฟอร์มเมื่อไม่มีข้อมูลจริง)")}</h4>
      <table class="grid"><tbody>${d.categories.map((c) => `<tr><td data-notr>${E(PLAT[c.platform] || c.platform)}</td><td data-notr>${E(c.cat_label || c.category)}</td><td class="num">${pc(c.rate)}</td>
        <td><button class="mini" data-fe-delcat="${E(c.platform)}|${E(c.category)}">${Z("删除", "ลบ")}</button></td></tr>`).join("")}</tbody></table>
      <div class="row gap wrap"><select data-fe-cplat>${["lazada", "shopee"].map((p) => `<option value="${p}">${PLAT[p]}</option>`).join("")}</select>
        <select data-fe-ccat data-notr>${cats}</select><input type="number" step="0.1" min="0" max="89" data-fe-crate placeholder="%" style="width:5rem">
        <button class="mini" data-fe-addcat>${Z("添加 / 修改", "เพิ่ม/แก้ไข")}</button></div>`;
  }

  function shopeeBox() {
    const s = D.shopee;
    return `<p>${s.last_import ? Z(`上次导入 ${s.days} 天前（${when(s.last_import)}）。`, `นำเข้าล่าสุด ${s.days} วันก่อน (${when(s.last_import)})`) : Z("还没导入过 Shopee 结算报表，费率现在用默认值。", "ยังไม่เคยนำเข้ารายงาน Shopee ตอนนี้ใช้ค่าเริ่มต้น")}
      ${s.stale ? `<span class="warn">${Z("超过 7 天了：请到 Shopee 卖家中心 → 我的收入 → 已拨款 下载收入报表，再导入。", "เกิน 7 วัน: ดาวน์โหลดรายงานรายได้จาก Shopee Seller Centre แล้วนำเข้า")}</span>` : ""}
      <button class="mini" data-ux-go="tab:fin_settle">${Z("去导入", "ไปนำเข้า")}</button></p>
      <p class="small muted">${Z("Shopee 还没有接口，费率来自导入的报表；以后有接口了会自动接上。导入后任何费用项变化超过 0.5 个百分点会提醒你。", "Shopee ยังไม่มี API อัตราคำนวณจากรายงานที่นำเข้า ถ้ามีการเปลี่ยนเกิน 0.5 จุดจะแจ้งเตือน")}</p>`;
  }

  function paint() {
    BOX.innerHTML = UX.head(Z("平台费率", "อัตราค่าธรรมเนียมแพลตฟอร์ม"),
      `<select data-fe-plat><option value="">${Z("全部平台", "ทุกแพลตฟอร์ม")}</option>${Object.keys(PLAT).map((p) => `<option value="${p}" ${PF === p ? "selected" : ""}>${PLAT[p]}</option>`).join("")}</select>
       <button class="mini" data-fe-refresh>${Z("立即重算", "คำนวณใหม่")}</button>`,
      Z("用平台结算流水算出来的真实费率，成本 / 定价 / 利润估算都用它。每天自动重算一次。", "อัตราจริงจากรายการชำระเงิน ใช้ในต้นทุน/ราคา/กำไร คำนวณใหม่อัตโนมัติทุกวัน"))
      + kpis() + eventsBox() + undoBox()
      + UX.card({ title: Z("费率走势（近 30 天口径）", "แนวโน้มอัตรา (30 วัน)"), body: trend() })
      + UX.card({ title: Z("店铺 × 类目", "ร้าน × หมวดหมู่"), body: table() })
      + UX.card({ title: Z("默认费率", "อัตราเริ่มต้น"), body: defaults(), help: Z("平台默认就是「设置」里的平台扣点，改这里也会同步过去。", "ค่าเริ่มต้นของแพลตฟอร์มคือค่าในหน้าตั้งค่า แก้ที่นี่จะซิงค์กัน") })
      + UX.card({ title: Z("Shopee 报表导入", "นำเข้ารายงาน Shopee"), body: shopeeBox() });
  }

  async function render(box) {
    BOX = box;
    D = await api("/api/fin/fees");
    Object.assign(NAMES, D.fee_names || {});
    paint();
  }

  document.addEventListener("click", async (e) => {
    const t = e.target.closest && e.target.closest("[data-fe-refresh],[data-fe-save],[data-fe-addcat],[data-fe-delcat],[data-fe-recalc],[data-fe-undo],[data-fe-ack]");
    if (!t || !BOX || !BOX.contains(t)) return;
    const reload = async () => { D = await api("/api/fin/fees"); paint(); };
    try {
      if (t.hasAttribute("data-fe-refresh")) { await busy(t, async () => { await api("/api/fin/fees/refresh", { json: {} }); await reload(); }); return; }
      if (t.hasAttribute("data-fe-save")) {
        for (const i of BOX.querySelectorAll("[data-fe-def]")) await api("/api/fin/fees/defaults", { json: { platform: i.dataset.feDef, rate: Number(i.value) / 100 } });
        await api("/api/fin/fees/min_orders", { json: { min_orders: Number($("[data-fe-min]", BOX).value) } });
        toast(Z("已保存", "บันทึกแล้ว")); return reload();
      }
      if (t.hasAttribute("data-fe-addcat")) {
        const sel = $("[data-fe-ccat]", BOX); const v = $("[data-fe-crate]", BOX).value;
        if (!sel.value || v === "") return toast(Z("请选类目并填比例", "เลือกหมวดและใส่อัตรา"), true);
        await api("/api/fin/fees/defaults", { json: { platform: $("[data-fe-cplat]", BOX).value, category: sel.value, rate: Number(v) / 100, label: sel.selectedOptions[0].textContent } });
        return reload();
      }
      if (t.dataset.feDelcat) { const [p, c] = t.dataset.feDelcat.split("|"); await api("/api/fin/fees/defaults", { json: { platform: p, category: c, rate: "" } }); return reload(); }
      if (t.dataset.feRecalc) {
        const [p, shop] = t.dataset.feRecalc.split("|");
        const pv = await api("/api/fin/fees/recalc/preview", { json: { platform: p, shop } });
        const clr = pv.plan.filter((a) => a.action === "clear"), mk = pv.plan.filter((a) => a.action === "mark");
        if (!pv.plan.length) { toast(Z("没有带手动价、又低于最低加价率的产品，不需要改", "ไม่มีสินค้าที่ตั้งราคาเองและต่ำกว่าเกณฑ์"), true); return; }
        const line = (a) => `  ${a.id} ${a.name}：` + a.variants.map((v) => `${v.sku || "#" + v.idx} ฿${v.manual_price}→${v.suggested}`).join("，");
        const msg = [
          clr.length ? Z(`清掉手动价（回到建议价，可撤销）：${clr.length} 个产品`, `ล้างราคาที่ตั้งเอง (กลับเป็นราคาแนะนำ ย้อนกลับได้): ${clr.length} สินค้า`) : "",
          ...clr.slice(0, 12).map(line), clr.length > 12 ? `  … ${Z("还有", "อีก")} ${clr.length - 12}` : "",
          mk.length ? Z(`只标「要改价」、不动手动价（还挂在别的平台，手动价是共用的）：${mk.length} 个产品`, `ติดป้าย「ต้องแก้ราคา」เท่านั้น ไม่แตะราคาที่ตั้งเอง (ขายในแพลตฟอร์มอื่นด้วย): ${mk.length} สินค้า`) : "",
          ...mk.slice(0, 12).map((a) => `  ${a.id} ${a.name}（${a.also_on.join("/")}）`), mk.length > 12 ? `  … ${Z("还有", "อีก")} ${mk.length - 12}` : "",
        ].filter(Boolean).join("\n");
        if (!confirm(msg)) return;
        const r = await api("/api/fin/fees/recalc", { json: { platform: p, shop } });
        toast(Z(`已处理 ${r.products} 个产品（清手动价 ${r.variants} 个变体，只标要改价 ${r.marked.length} 个产品）`, `จัดการแล้ว ${r.products} สินค้า (ล้างราคา ${r.variants} ตัวเลือก ติดป้ายอย่างเดียว ${r.marked.length})`)); return reload();
      }
      if (t.dataset.feUndo) {
        const r = await api("/api/fin/fees/recalc/undo", { json: { batch: t.dataset.feUndo } });
        toast(Z(`已恢复 ${r.restored} 个变体的手动价${r.skipped ? `，${r.skipped} 个已被改过没动` : ""}`, `คืนราคาแล้ว ${r.restored} ตัวเลือก${r.skipped ? ` ข้าม ${r.skipped}` : ""}`)); return reload();
      }
      if (t.dataset.feAck) { const [p, shop] = t.dataset.feAck.split("|"); await api("/api/fin/fees/ack", { json: { platform: p, shop } }); return reload(); }
    } catch (err) { toast(err.message, true); }
  });
  document.addEventListener("change", (e) => {
    if (e.target.matches && e.target.matches("[data-fe-plat]") && BOX && BOX.contains(e.target)) {
      PF = e.target.value; try { localStorage.setItem("fin_fee_plat", PF); } catch { /* 忽略 */ }
      paint();
    }
  });
  window.FIN_FEES = { render };
})();
