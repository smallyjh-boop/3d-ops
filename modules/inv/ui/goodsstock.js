"use strict";
// v2.54 成品备货（仓库 → 库存 → 成品备货）：数字卡片 → 图表 → 左边自动分组 + 右边一张表（所有成品）。
// 目标数量自动算（销量 × 常备天数 + 安全库存），不用手工敲；缺口一键补货：自产 → 生产单，外购 → 采购单草稿。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const num = (v, d = 0) => (v == null || v === "" ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const E = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ZT = { pick: ["拣货区", "โซนหยิบ"], reserve: ["备货区", "โซนสำรอง"], qc: ["待检区", "โซนรอตรวจ"], returns: ["退货区", "โซนคืน"], defect: ["次品区", "โซนชำรุด"], staging: ["暂存区", "โซนพัก"] };
  const ztn = (t) => (ZT[t] ? ZT[t][TH() ? 1 : 0] : t);
  let D = null, SEL = {}, Q = "", SORT = "gap", PICK = new Set(), TIMER = null;
  const canEdit = () => !window.ME || ME.role === "owner" || ME.role === "production";
  const typeTag = (r) => (r.type === "buy"
    ? `<span class="gs-tag gs-buy" title="${E(Z("外购：走采购补货", "ซื้อมา: เติมผ่านจัดซื้อ"))}">🛒 ${Z("外购", "ซื้อมา")}</span>`
    : `<span class="gs-tag gs-own" title="${E(Z("自产：走生产单补货", "ผลิตเอง: เติมผ่านใบสั่งผลิต"))}">🖨 ${Z("自产", "ผลิตเอง")}</span>`);

  async function load() {
    const root = document.getElementById("gs-root");
    if (!root) return;
    try { D = await api("/api/inv/gs"); } catch (e) { root.innerHTML = `<p class="muted">${E(e.message)}</p>`; return; }
    PICK = new Set([...PICK].filter((s) => D.rows.some((r) => r.sku === s)));
    render();
    clearInterval(TIMER);
    TIMER = setInterval(() => { if (!document.hidden && root.isConnected && !root.closest(".hidden") && !document.querySelector("#modal:not(.hidden)")) load().catch(() => {}); }, 60000);
  }

  function groupSpec() {
    const g = D.groups || {};
    const it = (key, zh, th, tone) => ({ key, label: Z(zh, th), n: g[key] || 0, tone: g[key] && tone ? tone : "" });
    return {
      sel: SEL,
      top: [{ key: "", label: Z("全部", "ทั้งหมด"), n: D.rows.length }],
      sections: [
        { id: "st", title: Z("1. 库存状态", "1. สถานะสต็อก"), help: Z("一个 SKU 可以同时在几个里面；补上、卖掉后自动换组", "SKU หนึ่งอยู่ได้หลายกลุ่ม เปลี่ยนกลุ่มอัตโนมัติ"),
          items: [it("out", "缺货", "ของหมด", "bad"), it("below", "低于目标", "ต่ำกว่าเป้า", "warn"), it("over", "积压", "สต็อกเกิน", "warn"),
            it("put", "待上架", "รอจัดเก็บ", "warn"), it("qc", "质检中", "รอตรวจ", ""), it("slow", "很久没动", "ไม่เคลื่อนไหวนาน", "warn")] },
        { id: "src", title: Z("2. 来源", "2. แหล่งที่มา"), items: [it("own", "🖨 自产", "🖨 ผลิตเอง"), it("buy", "🛒 外购", "🛒 ซื้อมา")] },
        { id: "cat", title: Z("3. 分类", "3. หมวดหมู่"), items: (D.cats || []).map((c) => ({ key: "cat:" + c.name, label: c.name === "none" ? Z("没分类", "ไม่มีหมวด") : c.name, n: c.n, raw: c.name !== "none" })) },
      ],
      foot: `<a class="small" data-grp-clear>${E(Z("清除选择", "ล้างการเลือก"))}</a>`,
    };
  }

  function visible() {
    const q = Q.trim().toLowerCase();
    let rows = D.rows.filter((r) => GRP.match(r, SEL) && (!q || [r.sku, r.name, r.color, r.spec, r.category, ...r.locs.map((l) => l.code)].join(" ").toLowerCase().includes(q)));
    const key = { gap: (r) => [-r.gap, r.sku], sku: (r) => [r.sku], stock: (r) => [r.qty, r.sku], cover: (r) => [r.cover_days == null ? 9e9 : r.cover_days, r.sku], sold: (r) => [-r.sold, r.sku], value: (r) => [-r.value, r.sku] }[SORT];
    return rows.sort((a, b) => { const x = key(a), y = key(b); return x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : x[1] < y[1] ? -1 : 1; });
  }

  function render() {
    const root = document.getElementById("gs-root");
    const k = D.kpis, g = D.groups || {};
    const ok = D.rows.filter((r) => !["out", "below", "over"].some((x) => r.gk.includes(x))).length;
    const top = [...D.rows].filter((r) => r.gap > 0).sort((a, b) => b.gap - a.gap).slice(0, 6);
    root.innerHTML = `
      <div class="row between wrap gap"><h2>${E(Z("成品备货", "เตรียมสต็อกสินค้า"))}</h2>
        <div class="row gap wrap">
          ${canEdit() ? `<button class="primary" id="gs-fill">⚡ ${E(Z("一键补货", "เติมสต็อกอัตโนมัติ"))}${k.gap_units ? ` <b>${k.gap_units}</b>` : ""}</button>
            <button id="gs-add">➕ ${E(Z("从产品库添加", "เพิ่มจากคลังสินค้า"))}</button>` : ""}
          <button id="gs-reload">${E(Z("刷新", "รีเฟรช"))}</button></div></div>
      <p class="muted small">${E(Z("目标数量自动算：近 " + D.settings.gs_sales_days + " 天销量 × 常备 " + D.settings.stock_cover_days + " 天 + 安全库存 " + D.settings.gs_safety + "，也可以手动改（点目标数字）。自产的补货会生成「生产单」，外购的生成采购单草稿。",
        "เป้าหมายคำนวณอัตโนมัติ: ยอดขาย " + D.settings.gs_sales_days + " วัน × เก็บ " + D.settings.stock_cover_days + " วัน + สำรอง " + D.settings.gs_safety + " แก้เองได้ (กดที่ตัวเลขเป้า) ผลิตเอง = สร้างใบสั่งผลิต ซื้อมา = สร้างใบสั่งซื้อฉบับร่าง"))}</p>
      ${UX.kpis([
        { label: Z("成品总数", "สินค้ารวม"), value: num(k.units), sub: Z(`${k.skus} 个 SKU`, `${k.skus} SKU`), icon: "📦" },
        { label: Z("库存金额", "มูลค่าสต็อก"), value: "฿" + num(k.value), icon: "💰" },
        { label: Z("低于目标", "ต่ำกว่าเป้า"), value: k.below, tone: k.below ? "warn" : "ok", sub: k.gap_units ? Z(`共差 ${k.gap_units} 件`, `ขาดรวม ${k.gap_units} ชิ้น`) : "" },
        { label: Z("缺货", "ของหมด"), value: k.out, tone: k.out ? "bad" : "ok" },
        { label: Z("待上架", "รอจัดเก็บ"), value: k.put, tone: k.put ? "warn" : "", sub: k.put_units ? Z(`${num(k.put_units)} 件`, `${num(k.put_units)} ชิ้น`) : "" },
        { label: Z("很久没动", "ไม่เคลื่อนไหวนาน"), value: k.slow, tone: k.slow ? "warn" : "" },
      ])}
      <div class="inv-charts">
        ${UX.card({ title: Z("库存状态", "สถานะสต็อก"), body: UX.bars([
          { label: Z("正常", "ปกติ"), value: ok, tone: "ok" }, { label: Z("低于目标", "ต่ำกว่าเป้า"), value: g.below || 0, tone: "warn" },
          { label: Z("缺货", "ของหมด"), value: g.out || 0, tone: "bad" }, { label: Z("积压", "สต็อกเกิน"), value: g.over || 0, tone: "warn" },
          { label: Z("质检中", "รอตรวจ"), value: g.qc || 0 }]) })}
        ${UX.card({ title: Z("缺口最大的", "ขาดมากที่สุด"), body: UX.bars(top.map((r) => ({ label: r.sku, raw: true, value: r.gap, text: "−" + r.gap, tone: "warn" })), { empty: Z("都达到目标了", "ถึงเป้าทั้งหมดแล้ว") }) })}
      </div>
      <div class="lib-wrap gs-wrap">
        <aside class="lib-groups card"><div id="gs-groups"></div></aside>
        <div class="lib-main">
          <div class="row gap wrap gs-tools">
            <input id="gs-q" type="search" placeholder="${E(Z("搜 SKU / 名称 / 货位", "ค้นหา SKU / ชื่อ / ช่องเก็บ"))}" value="${E(Q)}" data-notr>
            <select id="gs-sort">${[["gap", "缺口大的在前", "ขาดมากก่อน"], ["stock", "库存少的在前", "สต็อกน้อยก่อน"], ["cover", "能卖天数少的在前", "ขายได้กี่วันน้อยก่อน"], ["sold", "销量高的在前", "ขายดีก่อน"], ["value", "金额高的在前", "มูลค่าสูงก่อน"], ["sku", "SKU", "SKU"]]
              .map(([v, zh, th]) => `<option value="${v}" ${SORT === v ? "selected" : ""}>${E(Z(zh, th))}</option>`).join("")}</select>
            <span class="muted small" id="gs-count"></span>
            <span class="gs-bulk ${PICK.size ? "" : "hidden"}" id="gs-bulk">${bulkHtml()}</span></div>
          <div class="gs-scroll"><table class="grid gs-table" id="gs-table"><thead><tr><th><input type="checkbox" id="gs-all"></th><th></th>
            <th>${E(Z("商品", "สินค้า"))}</th><th>${E(Z("库存（可卖 / 待检 / 次品）", "สต็อก (ขายได้ / รอตรวจ / ชำรุด)"))}</th><th>${E(Z("货位", "ช่องเก็บ"))}</th><th>${E(Z("目标", "เป้า"))}</th><th>${E(Z("缺口", "ขาด"))}</th>
            <th>${E(Z("近 " + D.settings.gs_sales_days + " 天销量", "ยอดขาย " + D.settings.gs_sales_days + " วัน"))}</th><th>${E(Z("能卖几天", "ขายได้กี่วัน"))}</th><th>${E(Z("在做", "กำลังทำ"))}</th><th></th></tr></thead><tbody></tbody></table></div>
        </div></div>`;
    const spec = groupSpec();
    const box = document.getElementById("gs-groups");
    box.innerHTML = GRP.html(spec);
    GRP.bind(box, spec, () => { render(); });
    rows();
    bind(root);
  }

  function bulkHtml() {
    return `<b>${PICK.size}</b> ${E(Z("个已选", "รายการที่เลือก"))}：
      <button class="mini" data-gs-b="fill">⚡ ${E(Z("补货", "เติม"))}</button><button class="mini" data-gs-b="target">${E(Z("改目标", "แก้เป้า"))}</button>
      <button class="mini" data-gs-b="auto">${E(Z("目标改回自动", "เป้าอัตโนมัติ"))}</button><button class="mini" data-gs-b="own">🖨 ${E(Z("标自产", "ผลิตเอง"))}</button>
      <button class="mini" data-gs-b="buy">🛒 ${E(Z("标外购", "ซื้อมา"))}</button><button class="mini" data-gs-b="label">🏷 ${E(Z("标签", "ป้าย"))}</button>
      <button class="mini" data-gs-b="remove">${E(Z("移出", "นำออก"))}</button>`;
  }

  function locsHtml(r) {
    const l = (r.locs || []).map((x) => `<span class="gs-loc gs-z-${x.ztype}" title="${E(ztn(x.ztype))}" data-notr>${E(x.code)}<i>${num(x.qty)}</i></span>`).join("");
    const u = r.unplaced > 0 ? `<span class="gs-loc gs-z-unplaced">${E(Z("待上架", "รอจัดเก็บ"))}<i>${num(r.unplaced)}</i></span>` : "";
    return (l + u) || `<span class="muted small">—</span>`;
  }

  function rows() {
    const vis = visible();
    document.getElementById("gs-count").textContent = Z(`${vis.length} / ${D.rows.length} 个`, `${vis.length} / ${D.rows.length} รายการ`);
    document.querySelector("#gs-table tbody").innerHTML = vis.map((r) => `<tr data-sku="${E(r.sku)}" class="${r.free <= 0 ? "gs-out" : r.gap > 0 ? "gs-low" : ""}">
      <td><input type="checkbox" data-gs-pick="${E(r.sku)}" ${PICK.has(r.sku) ? "checked" : ""}></td>
      <td>${r.img ? `<img class="gs-img" src="${E(r.img)}" alt="" loading="lazy">` : '<div class="gs-img gs-noimg"></div>'}</td>
      <td><div class="mono" data-notr ${r.in_library ? `data-p360="${E(r.sku)}"` : ""}>${E(r.sku)}</div><div class="small" data-notr>${E(r.name)}</div>
        <div class="small">${typeTag(r)} ${r.color ? `<span data-notr>${E(r.color)}</span>` : ""} ${r.spec ? `<span data-notr>${E(r.spec)}</span>` : ""}${r.category ? ` <span class="muted" data-notr>· ${E(r.category)}</span>` : ""}</div></td>
      <td><b>${num(r.free)}</b> <span class="muted small">${E(Z("可卖", "ขายได้"))}</span>
        ${r.qc ? `<div class="small gs-warn">🔍 ${num(r.qc)} ${E(Z("待检", "รอตรวจ"))}</div>` : ""}${r.defect ? `<div class="small gs-bad">⚠ ${num(r.defect)} ${E(Z("次品", "ชำรุด"))}</div>` : ""}${r.returns ? `<div class="small gs-warn">↩ ${num(r.returns)} ${E(Z("退货区", "โซนคืน"))}</div>` : ""}
        ${r.reserved ? `<div class="small muted">${E(Z(`订单占 ${r.reserved}`, `จองแล้ว ${r.reserved}`))}</div>` : ""}</td>
      <td class="gs-locs">${locsHtml(r)}</td>
      <td>${canEdit() ? `<a class="gs-target" data-gs-target="${E(r.sku)}" title="${E(Z("点一下改目标", "กดเพื่อแก้เป้า"))}">${num(r.target)}</a>` : num(r.target)}${r.auto ? ` <span class="muted small">${E(Z("自动", "อัตโนมัติ"))}</span>` : ` <span class="gs-man small">${E(Z("手动", "กำหนดเอง"))}</span>`}</td>
      <td>${r.gap ? `<b class="gs-bad">${r.gap}</b>` : '<span class="muted">0</span>'}</td>
      <td>${num(r.sold)}${r.daily ? `<div class="small muted">${E(Z(`每天 ${r.daily}`, `วันละ ${r.daily}`))}</div>` : ""}</td>
      <td>${r.cover_days == null ? '<span class="muted">—</span>' : `<span class="${r.cover_days < 3 ? "gs-bad" : ""}">${num(r.cover_days, 1)}</span>`}</td>
      <td>${r.making ? `<span class="pill">${r.type === "buy" ? "🛒" : "🖨"} ${r.making}</span>` : '<span class="muted">—</span>'}</td>
      <td class="gs-act">${canEdit() && r.gap ? `<button class="mini primary" data-gs-fill1="${E(r.sku)}">⚡</button>` : ""}<button class="mini" data-gs-loc="${E(r.sku)}" title="${E(Z("货位：移库 / 上架", "ช่องเก็บ: ย้าย / จัดเก็บ"))}">📍</button>
        <button class="mini" data-gs-label="${E(r.sku)}" title="${E(Z("打印标签", "พิมพ์ป้าย"))}">🏷</button></td></tr>`).join("")
      || `<tr><td colspan="11" class="muted">${E(Z("没有成品。点「➕ 从产品库添加」把要备货的商品加进来（数量、目标都是自动的）", "ยังไม่มีสินค้า กด「➕ เพิ่มจากคลังสินค้า」เพื่อเพิ่มสินค้าที่ต้องการเตรียมสต็อก (จำนวนและเป้าเป็นอัตโนมัติ)"))}</td></tr>`;
    const all = document.getElementById("gs-all");
    all.checked = vis.length > 0 && vis.every((r) => PICK.has(r.sku));
  }

  function bind(root) {
    document.getElementById("gs-reload").onclick = (e) => busy(e.target, load);
    const f = document.getElementById("gs-fill"); if (f) f.onclick = () => fillModal([], "");
    const a = document.getElementById("gs-add"); if (a) a.onclick = addModal;
    const q = document.getElementById("gs-q");
    q.oninput = () => { Q = q.value; rows(); };
    document.getElementById("gs-sort").onchange = (e) => { SORT = e.target.value; rows(); };
    document.getElementById("gs-all").onchange = (e) => { visible().forEach((r) => (e.target.checked ? PICK.add(r.sku) : PICK.delete(r.sku))); rows(); bulkRefresh(); };
    const tb = document.getElementById("gs-table");
    tb.onclick = (e) => {
      const t = e.target;
      if (t.dataset.gsFill1) return fillModal([t.dataset.gsFill1], "");
      if (t.dataset.gsLoc) return locModal(t.dataset.gsLoc);
      if (t.dataset.gsLabel) return window.open("/print/gs-labels?skus=" + encodeURIComponent(t.dataset.gsLabel), "_blank");
      if (t.dataset.gsTarget) return targetModal([t.dataset.gsTarget]);
    };
    tb.onchange = (e) => { const s = e.target.dataset.gsPick; if (s) { e.target.checked ? PICK.add(s) : PICK.delete(s); bulkRefresh(); } };
    document.getElementById("gs-bulk").onclick = (e) => { const b = e.target.dataset.gsB; if (b) bulk(b).catch((x) => toast(x.message, true)); };
  }
  function bulkRefresh() { const b = document.getElementById("gs-bulk"); b.classList.toggle("hidden", !PICK.size); b.innerHTML = bulkHtml(); }

  async function bulk(act) {
    const skus = [...PICK];
    if (!skus.length) return;
    if (act === "fill") return fillModal(skus, "");
    if (act === "target") return targetModal(skus);
    if (act === "label") return window.open("/print/gs-labels?skus=" + encodeURIComponent(skus.join(",")), "_blank");
    if (act === "auto") await api("/api/inv/gs/target", { json: { skus, target: "" } });
    else if (act === "own" || act === "buy") await api("/api/inv/gs/src", { json: { skus, src: act } });
    else if (act === "remove") { if (!confirm(Z(`把 ${skus.length} 个 SKU 移出成品备货？（有库存的只清掉目标，不会删库存）`, `นำ ${skus.length} SKU ออก? (ที่มีสต็อกจะล้างเฉพาะเป้า ไม่ลบสต็อก)`))) return; await api("/api/inv/gs/remove", { json: { skus } }); PICK.clear(); }
    toast(Z("已保存", "บันทึกแล้ว"));
    await load();
  }

  function targetModal(skus) {
    const one = skus.length === 1 ? D.rows.find((r) => r.sku === skus[0]) : null;
    const m = MODAL.open(`<h3>${E(Z("改目标数量", "แก้เป้าหมาย"))} ${one ? `<span class="mono" data-notr>${E(one.sku)}</span>` : E(Z(`（${skus.length} 个 SKU）`, `(${skus.length} SKU)`))}</h3>
      <p class="small muted">${E(Z("目标一般不用填，系统按销量自动算。只有想固定一个数（例如展会前多备）才手动填。", "ปกติไม่ต้องกรอก ระบบคำนวณจากยอดขาย กรอกเมื่ออยากกำหนดตัวเลขเอง"))}</p>
      <label>${E(Z("目标数量", "เป้าหมาย"))}<input type="number" min="0" id="gs-t-v" value="${one && !one.auto ? one.target : ""}" placeholder="${E(Z("留空 = 自动", "เว้นว่าง = อัตโนมัติ"))}"></label>
      ${one ? `<p class="small muted">${E(Z(`自动算出来是：${one.auto ? one.target : "—"}（近 ${one.days} 天卖了 ${one.sold} 件）`, `คำนวณอัตโนมัติ: ${one.auto ? one.target : "—"} (ขาย ${one.sold} ชิ้นใน ${one.days} วัน)`))}</p>` : ""}
      <div class="row gap"><button class="primary" id="gs-t-ok">${E(Z("保存", "บันทึก"))}</button><button data-mclose>${E(Z("取消", "ยกเลิก"))}</button></div>`);
    m.querySelector("#gs-t-ok").onclick = (e) => busy(e.target, async () => {
      await api("/api/inv/gs/target", { json: { skus, target: m.querySelector("#gs-t-v").value } });
      MODAL.close(); toast(Z("已保存", "บันทึกแล้ว")); await load();
    });
  }

  // ---------------- 从产品库添加 ----------------
  async function addModal() {
    const m = MODAL.open(`<div class="row between"><h3>${E(Z("从产品库添加成品", "เพิ่มสินค้าจากคลัง"))}</h3><button class="mini" data-mclose>${E(Z("关闭", "ปิด"))}</button></div>
      <p class="small muted">${E(Z("选产品（每个规格 / 颜色都会加进来），或者按分类 / 标签整组加。加进来后数量 0、目标自动，缺货会提示补货。", "เลือกสินค้า (ทุกสี/ขนาดจะถูกเพิ่ม) หรือเพิ่มทั้งกลุ่มตามหมวด/แท็ก เพิ่มแล้วจำนวน 0 เป้าอัตโนมัติ"))}</p>
      <div class="row gap wrap"><input id="gs-pq" type="search" placeholder="${E(Z("搜产品 / SKU / 分类", "ค้นหาสินค้า / SKU / หมวด"))}" data-notr>
        <select id="gs-pcat"></select><select id="gs-ptag"></select>
        <label class="row small"><input type="checkbox" id="gs-pbuy"> 🛒 ${E(Z("这些是外购的", "เป็นของซื้อมา"))}</label></div>
      <div id="gs-plist" class="gs-plist"></div>
      <div class="row gap wrap"><button class="primary" id="gs-padd">${E(Z("加入选中的产品", "เพิ่มสินค้าที่เลือก"))}</button><button id="gs-pgroup">${E(Z("按所选分类 / 标签整组加入", "เพิ่มทั้งกลุ่มตามหมวด/แท็กที่เลือก"))}</button></div>`);
    let P = null;
    const draw = () => {
      m.querySelector("#gs-plist").innerHTML = P.products.map((p) => `<label class="gs-prow"><input type="checkbox" data-pid="${E(p.id)}" ${p.in === p.skus.length ? "disabled" : ""}>
        ${p.img ? `<img class="gs-img" src="${E(p.img)}" alt="" loading="lazy">` : '<div class="gs-img gs-noimg"></div>'}
        <span><b class="mono" data-notr>${E(p.id)}</b> <span data-notr>${E(p.name)}</span><br><span class="small muted" data-notr>${E(p.category || "")}</span>
        <span class="small">${E(Z(`${p.skus.length} 个规格，已加 ${p.in}`, `${p.skus.length} แบบ เพิ่มแล้ว ${p.in}`))}</span></span></label>`).join("") || `<p class="muted">${E(Z("没有找到产品", "ไม่พบสินค้า"))}</p>`;
    };
    const fetchP = async () => {
      P = await api("/api/inv/gs/products?q=" + encodeURIComponent(m.querySelector("#gs-pq").value.trim()));
      const cs = m.querySelector("#gs-pcat"), ts = m.querySelector("#gs-ptag");
      if (!cs.options.length) {
        cs.innerHTML = `<option value="">${E(Z("按分类…", "ตามหมวด…"))}</option>` + P.categories.map((c) => `<option value="${E(c)}" data-notr>${E(c)}</option>`).join("");
        ts.innerHTML = `<option value="">${E(Z("按标签…", "ตามแท็ก…"))}</option>` + P.tags.map((t) => `<option value="${E(t.id)}" data-notr>${E(t.name)}</option>`).join("");
      }
      draw();
    };
    let tm; m.querySelector("#gs-pq").oninput = () => { clearTimeout(tm); tm = setTimeout(() => fetchP().catch(() => {}), 300); };
    const done = async (r) => {
      toast(Z(`加了 ${r.added.length} 个，已有 ${r.existed.length} 个${r.missing.length ? `，找不到 ${r.missing.length} 个` : ""}`, `เพิ่ม ${r.added.length} มีอยู่แล้ว ${r.existed.length}${r.missing.length ? ` ไม่พบ ${r.missing.length}` : ""}`));
      MODAL.close(); await load();
    };
    m.querySelector("#gs-padd").onclick = (e) => busy(e.target, async () => {
      const ids = [...m.querySelectorAll("[data-pid]:checked")].map((x) => x.dataset.pid);
      if (!ids.length) throw new Error(Z("先勾选产品", "เลือกสินค้าก่อน"));
      await done(await api("/api/inv/gs/add", { json: { product_ids: ids, src: m.querySelector("#gs-pbuy").checked ? "buy" : null } }));
    });
    m.querySelector("#gs-pgroup").onclick = (e) => busy(e.target, async () => {
      const cat = m.querySelector("#gs-pcat").value, tag = m.querySelector("#gs-ptag").value;
      if (!cat && !tag) throw new Error(Z("先选一个分类或标签", "เลือกหมวดหรือแท็กก่อน"));
      await done(await api("/api/inv/gs/add", { json: { group: cat ? { category: cat } : { tag }, src: m.querySelector("#gs-pbuy").checked ? "buy" : null } }));
    });
    fetchP().catch((e) => toast(e.message, true));
  }

  // ---------------- 一键补货 ----------------
  async function fillModal(skus, group) {
    let r;
    try { r = await api("/api/inv/gs/plan", { json: { skus, group } }); } catch (e) { toast(e.message, true); return; }
    if (!r.plan.length) { toast(Z("现在没有需要补的（都达到目标了）", "ไม่มีที่ต้องเติม (ถึงเป้าทั้งหมดแล้ว)")); return; }
    const own = r.plan.filter((x) => x.type === "own"), buy = r.plan.filter((x) => x.type === "buy");
    const tbl = (arr) => `<table class="grid small"><thead><tr><th></th><th>${E(Z("商品", "สินค้า"))}</th><th>${E(Z("缺口", "ขาด"))}</th><th>${E(Z("补多少", "เติม"))}</th></tr></thead><tbody>${arr.map((x) => `<tr>
      <td><input type="checkbox" data-fl="${E(x.sku)}" checked></td><td><span class="mono" data-notr>${E(x.sku)}</span> <span data-notr>${E(x.name)} ${E(x.color)}</span></td><td>${x.gap}</td>
      <td><input type="number" min="1" value="${x.qty}" style="width:70px" data-fq="${E(x.sku)}">${x.per_plate > 1 ? ` <span class="muted small">${E(Z(`一盘 ${x.per_plate} 个，凑整盘`, `เพลทละ ${x.per_plate} ชิ้น ปัดเต็มเพลท`))}</span>` : ""}</td></tr>`).join("")}</tbody></table>`;
    const m = MODAL.open(`<div class="row between"><h3>⚡ ${E(Z("一键补货", "เติมสต็อกอัตโนมัติ"))}</h3><button class="mini" data-mclose>${E(Z("关闭", "ปิด"))}</button></div>
      ${own.length ? `<h4>🖨 ${E(Z(`自产 ${own.length} 个 → 生成一张生产单`, `ผลิตเอง ${own.length} รายการ → สร้างใบสั่งผลิต 1 ใบ`))}</h4>${tbl(own)}
        <div class="row gap wrap small"><label class="row"><input type="checkbox" id="gs-f-rel" checked> ${E(Z("马上下达（变成打印任务）", "สั่งผลิตทันที (สร้างงานพิมพ์)"))}</label>
          <label class="row"><input type="checkbox" id="gs-f-pri"> ${E(Z("加急", "ด่วน"))}</label></div>` : ""}
      ${buy.length ? `<h4>🛒 ${E(Z(`外购 ${buy.length} 个 → 生成采购单草稿（按供应商分）`, `ซื้อมา ${buy.length} รายการ → สร้างใบสั่งซื้อฉบับร่าง (แยกตามผู้ขาย)`))}</h4>${tbl(buy)}` : ""}
      <div class="row gap"><button class="primary" id="gs-f-ok">${E(Z("确认补货", "ยืนยัน"))}</button><button data-mclose>${E(Z("取消", "ยกเลิก"))}</button></div>`);
    m.querySelector("#gs-f-ok").onclick = (e) => busy(e.target, async () => {
      const lines = [...m.querySelectorAll("[data-fl]:checked")].map((c) => ({ sku: c.dataset.fl, qty: +m.querySelector(`[data-fq="${CSS.escape(c.dataset.fl)}"]`).value || 0 })).filter((l) => l.qty > 0);
      if (!lines.length) throw new Error(Z("先勾选要补的", "เลือกรายการก่อน"));
      const rel = m.querySelector("#gs-f-rel"), pri = m.querySelector("#gs-f-pri");
      const res = await api("/api/inv/gs/replenish", { json: { lines, release: rel ? rel.checked : false, priority: pri && pri.checked ? 1 : 0 } });
      MODAL.close();
      const bits = [];
      if (res.po) bits.push(Z(`生产单 ${res.po.no}（${res.po.status_zh}）`, `ใบสั่งผลิต ${res.po.no} (${res.po.status_th})`));
      if (res.purchase && res.purchase.length) bits.push(Z(`采购单草稿 ${res.purchase.map((p) => p.no).join("、")}`, `ใบสั่งซื้อร่าง ${res.purchase.map((p) => p.no).join(", ")}`));
      toast(Z("已生成：", "สร้างแล้ว: ") + bits.join(" · "));
      await load();
      if (res.po && window.goTab) goTab("po");
    });
  }

  // ---------------- 货位：快速移库 / 上架 ----------------
  async function locModal(sku) {
    const r = D.rows.find((x) => x.sku === sku) || {};
    let o;
    try { o = await api("/api/inv/gs/locs?sku=" + encodeURIComponent(sku)); } catch (e) { toast(e.message, true); return; }
    if (!o.item_id) { toast(Z("这个 SKU 还没有库存档案", "SKU นี้ยังไม่มีข้อมูลสต็อก"), true); return; }
    const hum = (x) => (TH() ? x.human_th : x.human_zh) || "";
    const m = MODAL.open(`<div class="row between"><h3>📍 <span class="mono" data-notr>${E(sku)}</span> <span class="small" data-notr>${E(r.name || "")}</span></h3><button class="mini" data-mclose>${E(Z("关闭", "ปิด"))}</button></div>
      <table class="grid small"><thead><tr><th>${E(Z("货位", "ช่องเก็บ"))}</th><th>${E(Z("区", "โซน"))}</th><th>${E(Z("数量", "จำนวน"))}</th><th>${E(Z("移到", "ย้ายไป"))}</th></tr></thead><tbody>
      ${o.locations.map((x) => `<tr><td class="mono" data-notr>${E(x.code)}<div class="small muted" data-notr>${E(hum(x))}</div></td><td>${E(ztn(x.ztype))}</td><td>${num(x.qty)}</td>
        <td><input class="gs-mv-to" placeholder="${E(Z("目标货位 如 R1-01-01", "ช่องปลายทาง"))}" data-notr style="width:140px"> <input type="number" min="1" max="${x.qty}" value="${x.qty}" style="width:60px" class="gs-mv-q">
          <button class="mini" data-mv="${E(x.code)}">${E(Z("移库", "ย้าย"))}</button></td></tr>`).join("") || `<tr><td colspan="4" class="muted">${E(Z("还没放进货位", "ยังไม่ได้เก็บเข้าช่อง"))}</td></tr>`}</tbody></table>
      ${o.unplaced > 0 ? `<div class="gs-put"><b>${E(Z(`待上架 ${num(o.unplaced)} 件`, `รอจัดเก็บ ${num(o.unplaced)} ชิ้น`))}</b>
        <div class="small muted">${E(Z("推荐：先拣货区，再备货区", "แนะนำ: โซนหยิบก่อน แล้วโซนสำรอง"))}</div>
        ${o.plan.map((p) => `<button class="mini ${p.reason === "same" ? "primary" : ""}" data-put="${E(p.code)}" data-q="${p.qty}"><span data-notr>${E(p.code)}</span> × ${num(p.qty)} · ${E(ztn(p.ztype))}</button>`).join(" ") || `<span class="muted small">${E(Z("没有合适的空位，先去货位页建货架", "ไม่มีช่องว่าง ไปสร้างชั้นวางที่หน้าช่องเก็บ"))}</span>`}
        <div class="row gap small" style="margin-top:6px"><input id="gs-put-to" placeholder="${E(Z("或扫 / 输入货位", "หรือสแกน/พิมพ์ช่อง"))}" data-notr style="width:150px"><button class="mini" id="gs-put-go">${E(Z("上架", "จัดเก็บ"))}</button></div></div>` : ""}
      <p class="small"><a href="/print/gs-labels?skus=${encodeURIComponent(sku)}" target="_blank">🏷 ${E(Z("打印标签", "พิมพ์ป้าย"))}</a></p>`);
    const done = async () => { MODAL.close(); toast(Z("已保存", "บันทึกแล้ว")); await load(); };
    m.onclick = (e) => {
      const b = e.target;
      if (b.dataset.mv) {
        const tr = b.closest("tr"), to = tr.querySelector(".gs-mv-to").value.trim().toUpperCase();
        if (!to) return toast(Z("填目标货位", "กรอกช่องปลายทาง"), true);
        busy(b, async () => { await api("/api/inv/wms/move", { json: { from: b.dataset.mv, to, lines: [{ item_id: o.item_id, qty: +tr.querySelector(".gs-mv-q").value }] } }); await done(); });
      } else if (b.dataset.put) {
        busy(b, async () => { await api("/api/inv/wms/putaway", { json: { item_id: o.item_id, code: b.dataset.put, qty: +b.dataset.q || undefined } }); await done(); });
      } else if (b.id === "gs-put-go") {
        const to = m.querySelector("#gs-put-to").value.trim().toUpperCase();
        if (to) busy(b, async () => { await api("/api/inv/wms/putaway", { json: { item_id: o.item_id, code: to } }); await done(); });
      }
    };
  }

  window.GS = { load };
})();
