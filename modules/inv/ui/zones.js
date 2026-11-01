"use strict";
// v2.53 一本库存按区管：库存页顶上的页签（库存 · 料卷 · 成品备货）、按区 / 分类的库存金额（数字卡片 → 图表）、
// 质检 · 退货 · 次品（待检区 / 退货区 / 次品区里的东西一个个处理）、料卷的货位（上架 / 称重盘点）。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const num = (v, d = 0) => (v == null || v === "" ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const nm = (x) => (TH() && x.name_th ? x.name_th : x.name_zh) || x.code || "";
  const ZT = {
    pick: ["拣货区", "โซนหยิบสินค้า"], reserve: ["备货区", "โซนสต็อกสำรอง"], staging: ["暂存区", "โซนพักสินค้า"], returns: ["退货区", "โซนสินค้าคืน"],
    defect: ["次品区", "โซนสินค้าชำรุด"], supply: ["耗材区", "โซนวัสดุสิ้นเปลือง"], pack: ["包材区", "โซนวัสดุแพ็ก"], production: ["生产区", "โซนผลิต"],
    qc: ["待检区", "โซนรอตรวจ"], unplaced: ["待上架", "รอจัดเก็บ"],
  };
  const ztName = (t) => (ZT[t] ? ZT[t][TH() ? 1 : 0] : t);
  const CATS = { filament: ["耗材", "วัสดุพิมพ์"], part: ["备件", "อะไหล่"], pack: ["包材", "วัสดุแพ็ค"], goods: ["成品", "สินค้าสำเร็จรูป"], tool: ["工具", "เครื่องมือ"], other: ["其他", "อื่นๆ"] };
  const catName = (c) => (CATS[c] ? CATS[c][TH() ? 1 : 0] : c);

  // ---------------- 页签：库存 · 料卷 · 成品备货（料卷、成品备货的页面还在生产模块，旧 id materials / stock 照样能开） ----------------
  const TOP = [["inventory", "库存", "สต็อก"], ["materials", "料卷", "ม้วนฟิลาเมนต์"], ["stock", "成品备货", "เตรียมสต็อกสินค้า"]];
  function strip(name) {
    if (!TOP.some((t) => t[0] === name)) return;
    TOP.forEach(([tab]) => {
      const p = document.getElementById("tab-" + tab);
      if (!p) return;
      let s = p.querySelector(":scope > .inv-top");
      if (!s) { s = document.createElement("div"); s.className = "inv-top"; p.prepend(s); }
      s.innerHTML = UX.tabs(TOP.filter(([t]) => t === "inventory" || document.getElementById("tab-" + t)).map(([t, zh, th]) => [t, Z(zh, th)]), name, "inv-top");
    });
    if (name === "materials") spoolExtras().catch(() => {});
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest('.inv-top [data-ux-tab]');
    if (b && window.goTab) goTab(b.dataset.uxTab);
  });

  // ---------------- 库存页上面：数字卡片 → 图表（按区、按分类的金额） ----------------
  async function overview(box) {
    let v;
    try { v = await api("/api/inv/value"); } catch { box.innerHTML = ""; return; }
    const money = v.total && v.total.value !== undefined;
    const zt = (v.ztypes || []).filter((x) => x.items);
    const top = zt.filter((x) => x.ztype !== "unplaced").sort((a, b) => (b.value || 0) - (a.value || 0))[0];
    const pend = zt.find((x) => x.ztype === "unplaced");
    box.innerHTML = UX.kpis([
      money ? { label: Z("库存金额", "มูลค่าสต็อก"), value: "฿" + num(v.total.value), sub: Z(`${v.total.items} 样物品`, `${v.total.items} รายการ`), icon: "💰" }
        : { label: Z("物品", "รายการ"), value: v.total.items, icon: "📦" },
      top ? { label: Z("最多的区", "โซนที่มากที่สุด"), value: ztName(top.ztype), sub: money ? "฿" + num(top.value) : Z(`${top.items} 样`, `${top.items} รายการ`) } : null,
      { label: Z("还够几天", "พอใช้อีกกี่วัน"), value: v.total.cover_days == null ? "—" : num(v.total.cover_days, 0) + Z(" 天", " วัน"),
        help: Z("按最近 30 天的用量 / 出货，库存还能撑几天（按金额加权）", "ตามการใช้ / ส่งออก 30 วันล่าสุด (ถ่วงน้ำหนักตามมูลค่า)") },
      { label: Z(`${v.slow_days} 天没动`, `ไม่เคลื่อนไหว ${v.slow_days} วัน`), value: v.total.slow_n, tone: v.total.slow_n ? "warn" : "",
        sub: money && v.total.slow_value ? "฿" + num(v.total.slow_value) : "" },
      pend ? { label: Z("待上架", "รอจัดเก็บ"), value: pend.items, tone: "warn", sub: money ? "฿" + num(pend.value) : "", go: "tab:inv_locations" } : null,
    ]) + `<div class="inv-charts">${UX.card({ title: Z("按区", "ตามโซน"), body: UX.bars(zt.map((x) => ({ label: ztName(x.ztype), value: money ? x.value : x.items,
      text: money ? "฿" + num(x.value) : x.items, tone: x.ztype === "defect" ? "bad" : ["qc", "returns", "unplaced", "staging"].includes(x.ztype) ? "warn" : "" }))) })}
      ${UX.card({ title: Z("按分类", "ตามหมวด"), body: UX.bars((v.categories || []).map((x) => ({ label: catName(x.category), value: money ? x.value : x.items,
        text: money ? "฿" + num(x.value) : x.items }))) })}
      ${(v.slow || []).length ? UX.card({ title: Z("很久没动的", "ไม่เคลื่อนไหวนาน"), body: `<table class="grid small"><tbody>${v.slow.slice(0, 6).map((x) =>
        `<tr><td class="mono" data-notr>${esc(x.code)}</td><td data-notr>${esc(nm(x))}</td><td>${x.idle_days}${Z(" 天", " วัน")}</td>${money ? `<td>฿${num(x.value)}</td>` : ""}</tr>`).join("")}</tbody></table>` }) : ""}</div>`;
  }

  // 库存表里「分布在」：A1-01-01 ×4 · 待检 QC1-01-01 ×1
  function split(it) {
    const xs = it.locs || [];
    if (!xs.length) return it.location ? `<a href="#" data-locgo-code="${esc(it.location)}" class="mono" data-notr>${esc(it.location)}</a>` : "";
    const q = (v) => (it.unit === "g" ? num(v) : num(v, 2));
    return xs.slice(0, 4).map((x) => `<span class="inv-loc z-${esc(x.ztype)}" title="${esc(ztName(x.ztype))}"><a href="#" data-locgo-code="${esc(x.code)}" class="mono" data-notr>${esc(x.code)}</a> ×${q(x.qty)}</span>`).join(" ")
      + (xs.length > 4 ? ` <span class="muted">+${xs.length - 4}</span>` : "");
  }
  function zoneSelect(zones, cur) {
    const opts = (zones || []).map((o) => `<option value="${esc(o.value)}" ${o.value === cur ? "selected" : ""}>${o.zone ? esc(o.zone) + " · " : ""}${esc(ztName(o.ztype))}${o.name ? " · " + esc(o.name) : ""}</option>`).join("");
    return `<select id="inv-zone"><option value="">${Z("全部区", "ทุกโซน")}</option>${opts}<option value="unplaced" ${cur === "unplaced" ? "selected" : ""}>${Z("待上架", "รอจัดเก็บ")}</option></select>`;
  }

  // ---------------- 质检 · 退货 · 次品 ----------------
  async function flows(box) {
    const [qc, rt, df] = await Promise.all(["qc", "returns", "defect"].map((z) => api("/api/inv/held/" + z).then((r) => r.items).catch(() => [])));
    const row = (z, x) => `<tr data-fz="${z}" data-fi="${x.item.id}" data-ff="${esc(x.from)}"><td class="mono" data-notr>${esc(x.item.code)}</td><td data-notr>${esc(nm(x.item))}</td>
      <td class="mono" data-notr>${esc(x.from)}</td><td><input type="number" class="fq" value="${x.qty}" min="0" max="${x.qty}" step="any" style="width:70px"></td>
      <td class="mono small" data-notr>${x.suggest && x.suggest[0] ? "→ " + esc(x.suggest[0].code) : ""}</td><td class="nowrap">${{
        qc: `<button class="mini primary" data-fa="pass">${Z("合格上架", "ผ่าน จัดเก็บ")}</button> <button class="mini" data-fa="fail">${Z("不合格 → 次品区", "ไม่ผ่าน → ชำรุด")}</button> <button class="mini danger" data-fa="scrap">${Z("报废", "ทิ้ง")}</button>`,
        returns: `<button class="mini primary" data-fa="restock">${Z("重新上架", "จัดเก็บใหม่")}</button> <button class="mini" data-fa="defect">${Z("次品区", "โซนชำรุด")}</button>`,
        defect: `<button class="mini" data-fa="rework">${Z("返工好了 → 重新质检", "ซ่อมแล้ว → ตรวจใหม่")}</button> <button class="mini danger" data-fa="scrap">${Z("报废", "ทิ้ง")}</button>`,
      }[z]}</td></tr>`;
    const tbl = (z, rows) => rows.length ? `<table class="grid small"><thead><tr><th>${Z("编码", "รหัส")}</th><th>${Z("名称", "ชื่อ")}</th><th>${Z("货位", "ตำแหน่ง")}</th><th>${Z("数量", "จำนวน")}</th><th>${Z("推荐", "แนะนำ")}</th><th></th></tr></thead><tbody>${rows.map((x) => row(z, x)).join("")}</tbody></table>` : UX.empty(Z("没有", "ไม่มี"));
    box.innerHTML = UX.kpis([
      { label: ztName("qc"), value: qc.length, tone: qc.length ? "warn" : "ok", icon: "🔍", help: Z("打印出来的成品先放这里，质检合格再上架", "สินค้าที่พิมพ์เสร็จวางที่นี่ก่อน ตรวจผ่านแล้วค่อยจัดเก็บ") },
      { label: ztName("returns"), value: rt.length, tone: rt.length ? "warn" : "ok", icon: "↩" },
      { label: ztName("defect"), value: df.length, tone: df.length ? "bad" : "ok", icon: "⚠" },
    ]) + UX.card({ title: Z("待检区：打印好的成品", "โซนรอตรวจ: สินค้าที่พิมพ์เสร็จ"), body: tbl("qc", qc) })
      + UX.card({ title: Z("退货区：检查后重新上架或放次品区", "โซนสินค้าคืน: ตรวจแล้วจัดเก็บใหม่หรือย้ายไปโซนชำรุด"),
        right: `<button class="mini" id="inv-ret-new">＋ ${Z("登记退货", "บันทึกสินค้าคืน")}</button>`, body: tbl("returns", rt) })
      + UX.card({ title: Z("次品区", "โซนชำรุด"), body: tbl("defect", df) });
    box.onclick = async (e) => {
      if (e.target.id === "inv-ret-new") {
        const code = prompt(Z("退回的商品编码 / SKU", "รหัสสินค้า / SKU ที่ส่งคืน")); if (!code) return;
        const q = prompt(Z("数量", "จำนวน"), "1"); if (!q) return;
        try { await api("/api/inv/returns/receive", { json: { code: code.trim(), qty: +q } }); toast(Z("已放进退货区", "ย้ายเข้าโซนสินค้าคืนแล้ว")); flows(box); } catch (er) { toast(er.message, true); }
        return;
      }
      const b = e.target.closest("[data-fa]"); if (!b) return;
      const tr = b.closest("tr"), z = tr.dataset.fz, a = b.dataset.fa;
      const body = { item_id: +tr.dataset.fi, from: tr.dataset.ff, qty: +tr.querySelector(".fq").value };
      if (a === "scrap" && !confirm(Z("报废这些？会从库存里扣掉。", "ทิ้งรายการนี้? จะตัดออกจากสต็อก"))) return;
      if (a === "scrap") body.note = Z("报废", "ทิ้ง");
      const url = z === "qc" ? (a === "pass" ? "/api/inv/qc/pass" : "/api/inv/qc/fail") : z === "returns" ? "/api/inv/returns/act" : "/api/inv/defect/act";
      if (z === "qc" && a !== "pass") body.action = a === "scrap" ? "scrap" : "defect";
      if (z !== "qc") body.act = a;
      await busy(b, async () => { const r = await api(url, { json: body }); toast(r.to ? `→ ${r.to}` : Z("已处理", "เรียบร้อย")); flows(box); });
    };
  }

  // ---------------- 料卷页：每卷的货位、上架、称重盘点 ----------------
  async function spoolExtras() {
    const tb = document.querySelector("#sp-table");
    if (!tb || !window.MODKIT || !MODKIT.enabled("inv")) return;
    const r = await api("/api/inv/spools?status=");
    const by = Object.fromEntries((r.items || []).map((s) => [s.code, s]));
    const th = tb.querySelector("thead tr");
    if (th && !th.querySelector(".sp-loc-h")) th.insertAdjacentHTML("beforeend", `<th class="sp-loc-h">${Z("货位", "ตำแหน่ง")}</th>`);
    tb.querySelectorAll("tbody tr[data-sid]").forEach((tr) => {
      if (tr.querySelector(".sp-loc")) return;
      const s = by[tr.dataset.sid];
      const loc = s && s.loc;
      tr.insertAdjacentHTML("beforeend", `<td class="sp-loc small nowrap">${loc ? `<span class="mono" data-notr title="${esc(TH() ? loc.human_th : loc.human_zh)}">${esc(loc.code)}</span>`
        : s && s.status !== "empty" ? `<span class="warn">${Z("待上架", "รอจัดเก็บ")}</span>` : ""}
        ${s && s.status !== "empty" ? ` <button class="mini" data-spz="put">📍</button> <button class="mini" data-spz="gross" title="${esc(Z("称重盘点：放秤上称整卷（含料盘）", "ตรวจนับด้วยการชั่ง: ชั่งทั้งม้วน (รวมแกน)"))}">⚖</button>` : ""}</td>`);
    });
    const box = document.getElementById("mat-alerts");
    if (box && !document.getElementById("sp-kpis")) box.insertAdjacentHTML("beforebegin", '<div id="sp-kpis"></div>');
    const k = document.getElementById("sp-kpis");
    const act = (r.items || []).filter((s) => s.status !== "empty");
    if (k) k.innerHTML = UX.kpis([
      { label: Z("料卷", "ม้วน"), value: act.length, icon: "🧵", sub: num(act.reduce((a, s) => a + Math.max(0, s.remaining_g || 0), 0) / 1000, 1) + " kg" },
      { label: Z("在机上", "อยู่บนเครื่อง"), value: act.filter((s) => s.status === "loaded").length },
      { label: Z("待上架", "รอจัดเก็บ"), value: act.filter((s) => !s.loc).length, tone: act.some((s) => !s.loc) ? "warn" : "ok", help: Z("扫料卷再扫货位放好；扫打印机 · 槽 = 上机", "สแกนม้วนแล้วสแกนตำแหน่ง; สแกนเครื่องพิมพ์ · ช่อง = ใส่เครื่อง") },
      { label: Z("提醒", "แจ้งเตือน"), value: (r.alerts || []).length, tone: (r.alerts || []).length ? "warn" : "ok" },
    ]);
  }
  document.addEventListener("click", async (e) => {
    const b = e.target.closest && e.target.closest("[data-spz]"); if (!b) return;
    const code = b.closest("[data-sid]").dataset.sid;
    try {
      if (b.dataset.spz === "put") {
        const to = prompt(Z("放到哪个货位？（扫货位码；扫打印机 · 槽 = 上机）", "วางที่ตำแหน่งไหน? (สแกนรหัสตำแหน่ง; สแกนเครื่องพิมพ์ · ช่อง = ใส่เครื่อง)")); if (!to) return;
        await api(`/api/inv/spools/${encodeURIComponent(code)}/put`, { json: { code: to.trim() } });
      } else {
        const g = prompt(Z("放秤上：整卷多少克（含空料盘）？", "ชั่งทั้งม้วนกี่กรัม (รวมแกนเปล่า)?")); if (!g) return;
        const r = await api(`/api/inv/spools/${encodeURIComponent(code)}/weigh`, { json: { gross: +g } });
        toast(Z(`剩 ${num(r.result.after)} g（${r.result.diff >= 0 ? "+" : ""}${num(r.result.diff)} g）`, `เหลือ ${num(r.result.after)} g (${r.result.diff >= 0 ? "+" : ""}${num(r.result.diff)} g)`));
      }
      if (window.MATERIALS) await MATERIALS.load();
      setTimeout(() => spoolExtras().catch(() => {}), 300);
    } catch (er) { toast(er.message, true); }
  });

  window.INVZ = { strip, overview, split, zoneSelect, flows, spoolExtras, ztName };
})();
