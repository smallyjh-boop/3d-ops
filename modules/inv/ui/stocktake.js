"use strict";
// 仓库 → 盘点（v2.52 从库存页搬出来）：按库区 / 货架 / 货位开盘点单（手机一个货位一个货位数），或者按分类整盘；
// 差异汇总，确认后按实盘调整库存（还是原来的盘点单）。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const num = (v, d = 2) => (v == null || v === "" ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const itName = (it) => (TH() && it.name_th ? it.name_th : it.name_zh) || "";
  const can = (k) => !window.INV || !INV.can || INV.can(k);
  const U_TH = { "个": "ชิ้น", "卷": "ม้วน", "张": "แผ่น", "件": "ชิ้น", "米": "เมตร", "瓶": "ขวด", "盒": "กล่อง", "套": "ชุด" };
  const uLab = (u) => (TH() && U_TH[u]) || u || "";
  let DOC = null, CATS = [];
  const BOX = () => $("#st-page");
  const areaTxt = (d) => ((d.ref || "").startsWith("area:") ? d.ref.slice(5) : "");
  const sign = (v) => (v > 0 ? "+" : "") + num(v);

  async function page() {
    if (DOC) return open(DOC);
    const box = BOX(); if (!box) return;
    if (window.INVLOC && !INVLOC.list().length) await INVLOC.loadLocs().catch(() => {});
    const [r, meta] = await Promise.all([api("/api/inv/docs?kind=stocktake"), api("/api/inv/meta")]);
    CATS = meta.categories || [];
    const docs = r.docs, open_ = docs.filter((d) => d.status === "draft");
    const monthStart = new Date(new Date().getFullYear(), new Date().getMonth(), 1).getTime() / 1000;
    const zones = window.INVLOC ? INVLOC.zones() : [], shelves = window.INVLOC ? INVLOC.shelves() : [];
    const catName = (id) => { const c = CATS.find((x) => x.id === id); return c ? (TH() ? c.th : c.zh) : id; };
    box.innerHTML = UX.head(Z("盘点", "ตรวจนับ"), "", Z("按货位盘点：选库区 / 货架开单，手机扫货位 → 扫物品（一件扫一下，或者直接填数）→ 这个货位数完，一个一个货位往下走；电脑上也能填。确认后按「实盘 − 账面」调整库存，货位上的数也改成数到的。盘点期间照常出入库也没关系。",
        "ตรวจนับตามตำแหน่ง: เลือกโซน / แร็คเปิดใบ บนมือถือสแกนตำแหน่ง → สแกนสินค้า (สแกนทีละชิ้นหรือกรอกจำนวน) → เสร็จช่องนี้แล้วไปช่องถัดไป กรอกบนคอมก็ได้ ยืนยันแล้วปรับสต็อกตาม「นับได้ − ในระบบ」 ระหว่างนับรับเข้าจ่ายออกได้ตามปกติ")) +
      UX.kpis([
        { label: Z("进行中", "กำลังนับ"), value: open_.length, tone: open_.length ? "warn" : "", icon: "🧮" },
        { label: Z("本月完成", "เสร็จเดือนนี้"), value: docs.filter((d) => d.status === "done" && (d.done_at || d.created_at) >= monthStart).length, icon: "✅" },
        { label: Z("最近一次", "ครั้งล่าสุด"), value: docs.find((d) => d.status === "done") ? fmtTime(docs.find((d) => d.status === "done").done_at || docs.find((d) => d.status === "done").created_at).slice(0, 10) : "—", icon: "📅" },
      ]) +
      (can("inv.out") ? UX.card({ title: Z("开始盘点", "เริ่มตรวจนับ"), body: `<div class="row gap wrap st-new">
          <select id="st-mode"><option value="area">${esc(Z("按货位（库区 / 货架）", "ตามตำแหน่ง (โซน / แร็ค)"))}</option><option value="cat">${esc(Z("按分类（整个分类）", "ตามหมวด (ทั้งหมวด)"))}</option></select>
          <select id="st-area" data-notr>${zones.map((z) => `<option value="${esc(z)}">${esc(Z(`${z} 区`, `โซน ${z}`))} · ${esc(INVLOC.ztName(INVLOC.zoneInfo(z).ztype))}</option>`).join("")}
            ${shelves.map((s) => `<option value="${esc(s)}">${esc(Z("货架 ", "แร็ค "))}${esc(s)}</option>`).join("")}</select>
          <select id="st-cat" class="hidden"><option value="">${esc(Z("全部分类", "ทุกหมวด"))}</option>${CATS.map((c) => `<option value="${esc(c.id)}">${esc(TH() ? c.th : c.zh)}</option>`).join("")}</select>
          <button class="primary" id="st-go">${esc(Z("开始盘点", "เริ่มตรวจนับ"))}</button></div>
          ${zones.length ? "" : `<p class="small muted">${esc(Z("还没有货位：先在「货位」里建货架，或者按分类盘点。", "ยังไม่มีตำแหน่ง: สร้างแร็คในหน้า「ตำแหน่ง」ก่อน หรือนับตามหมวด"))}</p>`}` }) : "") +
      UX.card({ title: Z("盘点单", "ใบตรวจนับ"), body: `<div class="tbl-x"><table class="grid small"><thead><tr><th>${esc(Z("单号", "เลขที่"))}</th><th>${esc(Z("范围", "ขอบเขต"))}</th><th>${esc(Z("状态", "สถานะ"))}</th><th>${esc(Z("时间", "เวลา"))}</th><th>${esc(Z("经手", "ผู้ทำ"))}</th><th></th></tr></thead><tbody>` +
        (docs.map((d) => `<tr><td class="mono" data-notr>${esc(d.no)}</td><td>${areaTxt(d) ? `📍 <span class="mono" data-notr>${esc(areaTxt(d))}</span>` : esc(d.category ? catName(d.category) : Z("全部", "ทั้งหมด"))}</td>
          <td>${d.status === "draft" ? `<span class="warn">${esc(Z("进行中", "กำลังนับ"))}</span>` : esc(Z("已确认", "ยืนยันแล้ว"))}</td><td class="nowrap">${fmtTime(d.created_at)}</td><td data-notr>${esc(d.created_by || "")}</td>
          <td><button class="mini" data-stdoc="${d.id}">${esc(d.status === "draft" ? Z("继续", "ทำต่อ") : Z("查看", "ดู"))}</button></td></tr>`).join("") ||
          `<tr><td colspan="6">${UX.empty(Z("还没有盘点记录", "ยังไม่มีการตรวจนับ"))}</td></tr>`) + "</tbody></table></div>" });
    const mode = $("#st-mode");
    if (mode) {
      if (!zones.length) mode.value = "cat";
      const sync = () => { $("#st-area").classList.toggle("hidden", mode.value !== "area"); $("#st-cat").classList.toggle("hidden", mode.value === "area"); };
      mode.onchange = sync; sync();
      $("#st-go").onclick = (e) => busy(e.target, async () => {
        const body = mode.value === "area" ? { area: $("#st-area").value } : { category: $("#st-cat").value };
        if (mode.value === "area" && !body.area) return toast(Z("先建货位", "สร้างตำแหน่งก่อน"), true);
        const d = (await api("/api/inv/stocktake", { json: body })).doc;
        open(d.id);
      });
    }
  }

  async function open(id) {
    DOC = id;
    const box = BOX(); if (!box) return;
    const d = (await api(`/api/inv/stocktake/${id}`)).doc;
    const draft = d.status === "draft";
    const head = `<div class="row gap wrap st-bar"><button class="mini" id="st-back">${esc(Z("← 返回列表", "← กลับ"))}</button><b class="mono" data-notr>${esc(d.no)}</b>
      <span>${areaTxt(d) ? `📍 <span class="mono" data-notr>${esc(areaTxt(d))}</span>` : ""}</span>
      <span class="${draft ? "warn" : "ok"}">${esc(draft ? Z("进行中", "กำลังนับ") : Z("已确认", "ยืนยันแล้ว"))}</span></div>`;
    if (!d.by_location) return openPlain(box, d, head);
    const p = d.progress;
    const diffRows = d.locs.flatMap((l) => l.rows.filter((x) => x.diff).map((x) => ({ ...x, loc: l.code })));
    box.innerHTML = head + UX.kpis([
      { label: Z("货位数完", "นับช่องแล้ว"), value: `${p.done} / ${p.total}`, tone: p.done === p.total ? "ok" : "warn", icon: "🗄" },
      { label: Z("有差异", "มีส่วนต่าง"), value: p.diffs, tone: p.diffs ? "bad" : "ok", icon: "⚠" },
      { label: Z("盘盈", "นับได้เกิน"), value: sign(p.plus), tone: p.plus ? "warn" : "", icon: "➕" },
      { label: Z("盘亏", "นับได้ขาด"), value: num(p.minus), tone: p.minus ? "bad" : "", icon: "➖" },
    ]) + (diffRows.length ? UX.card({ title: Z("差异汇总", "สรุปส่วนต่าง"), tone: "warn", body: `<div class="tbl-x"><table class="grid small"><thead><tr><th>${esc(Z("货位", "ตำแหน่ง"))}</th><th>${esc(Z("物品", "รายการ"))}</th><th>${esc(Z("账面", "ในระบบ"))}</th><th>${esc(Z("实盘", "นับได้"))}</th><th>${esc(Z("差异", "ส่วนต่าง"))}</th></tr></thead><tbody>
        ${diffRows.map((x) => `<tr><td class="mono" data-notr>${esc(x.loc)}</td><td data-notr><b class="mono">${esc(x.code)}</b> ${esc(itName(x))}</td><td>${num(x.book)}</td><td>${num(x.counted)}</td>
          <td class="${x.diff < 0 ? "bad" : "ok"}"><b>${sign(x.diff)}</b></td></tr>`).join("")}</tbody></table></div>` }) : "") +
      (draft ? `<div class="row gap wrap st-bar">${can("inv.adjust") ? `<button class="danger" id="st-ok">${esc(Z("✅ 确认盘点（调整库存）", "✅ ยืนยันตรวจนับ (ปรับสต็อก)"))}</button>` : `<span class="muted small">${esc(Z("数完让老板确认", "นับเสร็จแล้วให้เจ้าของยืนยัน"))}</span>`}
        <span class="small muted">${esc(Z("没数的货位不调整", "ช่องที่ยังไม่นับจะไม่ปรับ"))}</span></div>` : "") +
      `<div class="st-locs">${d.locs.map((l) => `<div class="card st-loc ${l.done ? "done" : ""}" data-sl="${esc(l.code)}">
        <div class="row between"><b class="mono" data-notr>${esc(l.code)}</b><span class="small">${l.done ? `✓ <span data-notr>${esc(l.by)}</span>` : `<span class="muted">${esc(Z("还没数", "ยังไม่นับ"))}</span>`}${l.diffs ? ` · <b class="bad">${esc(Z(`${l.diffs} 个差异`, `ต่าง ${l.diffs}`))}</b>` : ""}</span></div>
        <table class="grid small"><tbody>${l.rows.map((x) => `<tr data-iid="${x.item_id}"><td data-notr><b class="mono">${esc(x.code)}</b><div class="small muted">${esc(itName(x))}</div></td>
          <td class="nowrap small">${esc(Z("账面", "ในระบบ"))} ${num(x.book)}</td>
          <td>${draft ? `<input type="number" min="0" step="any" data-c value="${x.counted ?? ""}" class="loc-mq" placeholder="—">` : num(x.counted)}</td>
          <td class="${x.diff ? (x.diff < 0 ? "bad" : "ok") : ""}">${x.diff == null || !x.diff ? "" : sign(x.diff)}</td></tr>`).join("") || `<tr><td class="muted">${esc(Z("空货位", "ช่องว่าง"))}</td></tr>`}</tbody></table>
        ${draft ? `<div class="row gap" style="margin-top:6px"><input data-add placeholder="${esc(Z("多出来的物品编码", "รหัสสินค้าที่เจอเพิ่ม"))}" class="st-add" data-notr><button class="mini primary" data-save>${esc(Z("这个货位数完了", "ช่องนี้นับเสร็จ"))}</button></div>` : ""}</div>`).join("")}</div>`;
    $("#st-back").onclick = () => { DOC = null; page(); };
    const ok = $("#st-ok");
    if (ok) ok.onclick = () => {
      if (!confirm(Z("确认盘点？数过的货位按实盘数调整库存。", "ยืนยันตรวจนับ? ช่องที่นับแล้วจะปรับสต็อกตามจำนวนจริง"))) return;
      busy(ok, async () => { await api(`/api/inv/stocktake/${d.id}/confirm`, { json: {} }); toast(Z("盘点已确认", "ยืนยันตรวจนับแล้ว")); open(d.id); });
    };
    box.querySelectorAll("[data-save]").forEach((b) => b.addEventListener("click", () => busy(b, async () => {
      const card = b.closest("[data-sl]"), counts = {};
      card.querySelectorAll("tr[data-iid]").forEach((tr) => { const v = tr.querySelector("[data-c]").value; if (v !== "") counts[tr.dataset.iid] = v; });
      const add = card.querySelector("[data-add]").value.trim();
      if (add) { const q = prompt(Z(`${add} 数到几个？`, `${add} นับได้กี่ชิ้น?`), "1"); if (q == null) return; counts[add] = q; }
      await api(`/api/inv/stocktake/${d.id}/loc`, { json: { code: card.dataset.sl, counts, complete: true } });
      toast(Z(`${card.dataset.sl} 已保存`, `บันทึก ${card.dataset.sl} แล้ว`)); open(d.id);
    })));
  }

  // 按分类整盘（原来的表格）
  function openPlain(box, d, head) {
    const draft = d.status === "draft";
    box.innerHTML = head + `<div class="row gap wrap st-bar">${draft ? `<button class="primary" id="st-save">${esc(Z("保存已填的数", "บันทึกที่กรอกแล้ว"))}</button>
        ${can("inv.adjust") ? `<button class="danger" id="st-ok">${esc(Z("确认盘点（调整库存）", "ยืนยันตรวจนับ (ปรับสต็อก)"))}</button>` : `<span class="muted small">${esc(Z("填完让老板确认", "กรอกเสร็จแล้วให้เจ้าของยืนยัน"))}</span>`}` : ""}</div>
      <div class="tbl-x"><table class="grid small" id="st-tbl"><thead><tr><th>${esc(Z("编码", "รหัส"))}</th><th>${esc(Z("名称", "ชื่อ"))}</th><th>${esc(Z("开单时账面", "ในระบบตอนเปิด"))}</th><th>${esc(Z("现在账面", "ในระบบตอนนี้"))}</th><th>${esc(Z("实盘数", "นับได้"))}</th><th>${esc(Z("差异", "ส่วนต่าง"))}</th><th>${esc(Z("货位", "ตำแหน่ง"))}</th></tr></thead><tbody>` +
      d.lines.map((l) => `<tr><td class="mono" data-notr>${esc(l.code)}</td><td data-notr>${esc(itName(l))}</td>
        <td>${num(l.expected)}</td><td>${num(l.now_qty)} <span data-notr>${esc(uLab(l.unit))}</span></td>
        <td>${draft ? `<input type="number" step="any" data-line="${l.id}" value="${l.counted ?? ""}" class="loc-mq">` : num(l.counted)}</td>
        <td class="${l.diff ? (l.diff < 0 ? "bad" : "ok") : ""}">${l.diff == null ? (draft ? "" : num(l.qty)) : sign(l.diff)}</td><td class="mono" data-notr>${esc(l.location || "")}</td></tr>`).join("") + "</tbody></table></div>";
    const counts = () => { const o = {}; $$("#st-tbl [data-line]").forEach((el) => { o[el.dataset.line] = el.value === "" ? null : el.value; }); return o; };
    $("#st-back").onclick = () => { DOC = null; page(); };
    const sv = $("#st-save");
    if (sv) sv.onclick = () => busy(sv, async () => { await api(`/api/inv/stocktake/${d.id}/save`, { json: { counts: counts() } }); toast(Z("已保存", "บันทึกแล้ว")); open(d.id); });
    const okb = $("#st-ok");
    if (okb) okb.onclick = () => { if (!confirm(Z("确认盘点？有差异的会按实盘数调整库存。", "ยืนยันตรวจนับ? รายการที่ต่างจะปรับสต็อกตามจำนวนจริง"))) return;
      busy(okb, async () => { await api(`/api/inv/stocktake/${d.id}/save`, { json: { counts: counts() } }); await api(`/api/inv/stocktake/${d.id}/confirm`, { method: "POST" }); toast(Z("盘点已确认", "ยืนยันตรวจนับแล้ว")); open(d.id); }); };
  }

  document.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest("#tab-inv_stocktake [data-stdoc]");
    if (b) open(+b.dataset.stdoc).catch((er) => toast(er.message, true));
  });
  // 别的地方打开一张盘点单（库存页的单据、货位页的「盘点这个货架」）：先记下单号，再切到盘点页
  function openFromOutside(id) {
    DOC = id;
    const panel = $("#tab-inv_stocktake");
    if (panel && !panel.classList.contains("hidden")) return open(id).catch((e) => toast(e.message, true));
    goTab("inv_stocktake");
  }
  window.INVST = { page, open: openFromOutside };
})();
