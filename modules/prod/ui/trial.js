"use strict";
// v2.53 没有订单也能生产 / 试打：
//   ➕ 生产（备货任务，任何入口）  🧪 试打  🔍 检查切片文件（不打印）  🧪 试打结果表单  试打记录  🧪 打印测试  看板的类型标签 / 筛选
// 别的页面只要放带 data-tr-* 的按钮就行，这个文件在 document 上统一接：
//   data-tr-stock="产品号,产品号" [data-tr-skus="SKU,SKU"] [data-tr-src="editor"]     ➕ 生产
//   data-tr-trial="产品号" [data-tr-sku] [data-tr-spec] [data-tr-plate] [data-tr-file] [data-tr-all] [data-tr-unv]   🧪 试打
//   data-tr-check="产品号" [data-tr-spec] [data-tr-plate]                                 🔍 检查切片文件
//   data-tr-res="任务号"                                                                    🧪 试打结果
// 对外：window.TRIAL = { stockDialog, trialDialog, checkDialog, resultForm, mount, filterBoard, printerTest, bulkTrial }
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const enc = encodeURIComponent;
  const E = (s) => (window.esc ? esc(s) : String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])));
  const ISSUES = [["翘边", "ขอบงอ"], ["支撑难拆", "ซัพพอร์ตแกะยาก"], ["拉丝", "เป็นเส้นใย"], ["尺寸不对", "ขนาดไม่ถูก"], ["颜色不对", "สีไม่ถูก"], ["掉层", "ชั้นหลุด"], ["其他", "อื่น ๆ"]];
  const KINDS = [["", "全部", "ทั้งหมด"], ["order", "订单", "ออเดอร์"], ["stock", "备货", "สต็อก"], ["trial", "试打", "ทดลองพิมพ์"], ["test", "测试", "ทดสอบ"]];
  const KIND_NAME = { order: ["订单", "ออเดอร์"], stock: ["备货", "สต็อก"], trial: ["试打", "ทดลองพิมพ์"], test: ["测试", "ทดสอบ"], reship: ["补发", "ส่งซ้ำ"] };
  const kindName = (k) => (KIND_NAME[k] ? Z(KIND_NAME[k][0], KIND_NAME[k][1]) : k);
  let KF = "";

  const css = `
  .pill.kind-order{background:#e8f0fe;color:#1a56c4}.pill.kind-stock{background:#e3f5ea;color:#18794e}
  .pill.kind-trial{background:#f3e8ff;color:#7a2fc0}.pill.kind-test{background:#fff3cd;color:#8a6100}.pill.kind-reship{background:#fdecea;color:#b3261e}
  .tr-kinds{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin:6px 0}
  .tr-kinds .chip{cursor:pointer}
  .tr-pend{border:1px solid #d9c2f5;background:#faf5ff;border-radius:10px;padding:6px 10px;margin:6px 0}
  .tr-box{border:1px solid #e3e8ef;border-radius:10px;padding:8px 10px;margin:8px 0}
  .tr-chk{display:flex;gap:8px;align-items:flex-start;padding:3px 0;font-size:14px}
  .tr-chk.error{color:#b3261e;font-weight:600}.tr-chk.warn{color:#8a6100}.tr-chk.ok{color:#18794e}
  .tr-prev{max-width:360px;width:100%}.tr-prev svg{width:100%;height:auto;border-radius:8px}
  .tr-issues{display:flex;flex-wrap:wrap;gap:6px 14px}
  .tr-ph{display:flex;gap:6px;flex-wrap:wrap}.tr-ph img{width:64px;height:64px;object-fit:cover;border-radius:6px;border:1px solid #e3e8ef}
  .tr-hist{font-size:13px}.tr-hist table{width:100%;border-collapse:collapse}.tr-hist td,.tr-hist th{padding:3px 6px;border-bottom:1px solid #eef1f5;text-align:left}
  .tr-ok{color:#18794e}.tr-bad{color:#b3261e}
  `;
  if (!document.getElementById("tr-css")) { const st = document.createElement("style"); st.id = "tr-css"; st.textContent = css; document.head.appendChild(st); }

  const modal = (html, wide) => { const el = MODAL.open(html); if (wide) el.classList.add("wide"); return el; };
  const reloadBoard = () => { if (window.PROD && $("#tab-production") && !$("#tab-production").classList.contains("hidden")) PROD.loadBoard().catch(() => {}); };
  const lbl = (c) => (TH() ? c.th : c.zh);

  // ---------------- ➕ 生产（备货任务） ----------------
  async function stockDialog(o) {
    o = o || {};
    const pids = (o.pids || []).filter(Boolean);
    let d;
    try { d = await api(`/api/trial/skus?pids=${enc(pids.join(","))}`); } catch (e) { toast(e.message, true); return; }
    if (!d.skus.length) { toast(Z("这些产品还没有 SKU（款式）", "สินค้าเหล่านี้ยังไม่มี SKU"), true); return; }
    const pre = new Set((o.skus || []).map((s) => String(s).toUpperCase()));
    const first = d.skus[0].sku.toUpperCase();
    const on = (x) => (pre.size ? pre.has(x.sku.toUpperCase()) : d.skus.length <= 1 || x.sku.toUpperCase() === first);
    const el = modal(`<div class="row between"><h3>➕ ${Z("生产（备货）", "ผลิต (เตรียมสต็อก)")}</h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      <p class="small muted">${Z("不用订单，直接做成品放库存：和订单任务走同一套流程（排单、核对切片文件、打印、质检、入库）。", "ผลิตเก็บสต็อกโดยไม่ต้องมีออเดอร์ ใช้ขั้นตอนเดียวกับงานออเดอร์ (จัดคิว ตรวจไฟล์ พิมพ์ ตรวจคุณภาพ เข้าสต็อก)")}</p>
      <div class="tr-box"><table class="grid"><thead><tr><th></th><th>SKU</th><th>${Z("规格 / 颜色", "แบบ / สี")}</th><th>${Z("现有库存", "สต็อกตอนนี้")}</th><th>${Z("数量", "จำนวน")}</th></tr></thead><tbody>
      ${d.skus.map((x) => `<tr><td><input type="checkbox" data-sk="${E(x.sku)}" ${on(x) ? "checked" : ""}></td><td class="mono" data-notr>${E(x.sku)}<div class="small muted" data-notr>${E(x.name)}</div></td>
        <td data-notr>${E([x.spec, x.colour].filter(Boolean).join(" · "))}</td><td>${x.stock}</td>
        <td><input type="number" min="1" value="1" style="width:70px" data-sq="${E(x.sku)}"></td></tr>`).join("")}</tbody></table></div>
      <div class="row gap wrap"><label class="row"><input type="checkbox" id="tr-prio"> ${Z("加急（排在普通任务前面）", "ด่วน (จัดคิวก่อนงานปกติ)")}</label>
        <label>${Z("打印机", "เครื่องพิมพ์")} <select id="tr-pr"><option value="">${Z("自动排单", "จัดคิวอัตโนมัติ")}</option>${d.printers.map((p) => `<option value="${p.index}" data-notr>${E(p.label)}</option>`).join("")}</select></label></div>
      <button class="big primary" id="tr-go">${Z("生成备货任务", "สร้างงานเตรียมสต็อก")}</button>`, true);
    $("#tr-go", el).onclick = () => busy($("#tr-go", el), async () => {
      const items = $$("[data-sk]", el).filter((x) => x.checked).map((x) => ({ sku: x.dataset.sk, qty: +($(`[data-sq="${x.dataset.sk}"]`, el).value || 1) }));
      if (!items.length) { toast(Z("请勾选要生产的 SKU", "กรุณาเลือก SKU ที่จะผลิต"), true); return; }
      const r = await api("/api/jobs/stock", { json: { items, priority: $("#tr-prio", el).checked ? 1 : 0, printer: $("#tr-pr", el).value, source: o.source || "" } });
      MODAL.close();
      toast(Z(`已生成 ${r.jobs.length} 个备货任务，在生产看板里`, `สร้างงานเตรียมสต็อก ${r.jobs.length} งาน ดูได้ที่บอร์ดผลิต`) + (r.errors.length ? "。" + r.errors.join("；") : ""), !!r.errors.length);
      reloadBoard();
      if (o.done) o.done(r);
    });
  }

  // ---------------- 🧪 试打 ----------------
  async function trialDialog(o) {
    o = o || {};
    const q = `pid=${enc(o.pid)}&spec=${enc(o.spec || "")}&plate=${enc(o.plate || "")}&sku=${enc(o.sku || "")}`;
    let d;
    try { d = await api(`/api/trial/printers?${q}`); } catch (e) { toast(e.message, true); return; }
    const many = (d.plates || []).length > 1 && !o.plate;
    const el = modal(`<div class="row between"><h3>🧪 ${Z("试打", "ทดลองพิมพ์")} · <span class="mono" data-notr>${E(o.pid)}</span></h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      <p class="small muted">${Z("试打任务排在最前面，可以用还没试打验证的文件（试打就是为了验证它）；机型 / 喷嘴 / 热床板 / AMS 的核对照旧，对不上的文件不能用。打完以后填「试打结果」。",
        "งานทดลองพิมพ์จัดคิวก่อนเสมอ ใช้ไฟล์ที่ยังไม่ผ่านการทดลองได้ แต่การตรวจรุ่นเครื่อง หัวฉีด แผ่นฐาน AMS ยังเหมือนเดิม")}</p>
      ${many ? `<label class="row"><input type="checkbox" id="tr-all" checked> ${Z(`这个产品有 ${d.plates.length} 盘：每一盘各建一个试打任务（自动选同机型的空闲打印机）`, `สินค้านี้มี ${d.plates.length} เพลท: สร้างงานทดลองพิมพ์ทีละเพลท (เลือกเครื่องรุ่นเดียวกันที่ว่าง)`)}</label>` : ""}
      <div id="tr-prbox">${d.model ? `<div class="small">${Z("这一盘用的机型", "รุ่นเครื่องของเพลทนี้")}：<b data-notr>${E(d.model)}</b></div>` : ""}
        <label>${Z("打印机", "เครื่องพิมพ์")} <select id="tr-pr">${d.printers.map((p) => `<option value="${p.index}" data-notr>${E(p.label)}${p.idle ? "" : " · " + Z("忙", "ไม่ว่าง")}</option>`).join("")}</select></label></div>
      ${o.file ? `<div class="small">📄 ${Z("用文件", "ใช้ไฟล์")} #${E(o.file)}</div>` : `<div class="small muted">${Z("这一盘没有切片文件时，现在按打印方案切片（需要 OrcaSlicer，大约 10 秒到 1 分钟）。", "ถ้าเพลทนี้ยังไม่มีไฟล์สไลซ์ จะสไลซ์ตามแผนการพิมพ์ให้ตอนนี้ (ต้องมี OrcaSlicer ใช้เวลาราว 10 วินาที–1 นาที)")}</div>`}
      <button class="big primary" id="tr-go">🧪 ${Z("建试打任务", "สร้างงานทดลองพิมพ์")}</button>`);
    const sync = () => { const a = $("#tr-all", el); $("#tr-prbox", el).classList.toggle("hidden", !!(a && a.checked)); };
    el.onchange = sync; sync();
    $("#tr-go", el).onclick = () => busy($("#tr-go", el), async () => {
      const all = !!($("#tr-all", el) || {}).checked || !!o.all;
      const body = { product_id: o.pid, sku: o.sku || "", spec: o.spec == null ? undefined : o.spec, plate_id: o.plate || "", file_id: o.file || undefined,
        printer: all ? "" : $("#tr-pr", el).value, all_plates: all, only_unverified: !!o.unv, source: o.src || "" };
      const r = await apiJob("/api/trial", { json: body });
      MODAL.close();
      const n = r.trials ? r.trials.length : 1;
      toast(Z(`已建 ${n} 个试打任务，在生产看板里（排在最前面）`, `สร้างงานทดลองพิมพ์ ${n} งาน ดูที่บอร์ดผลิต (จัดคิวก่อน)`) + (r.trials && r.skipped.length ? Z(`；${r.skipped.length} 盘已经验证过，跳过`, `; ข้าม ${r.skipped.length} เพลทที่ผ่านแล้ว`) : "")
        + (r.errors && r.errors.length ? "。" + r.errors.join("；") : ""), !!(r.errors && r.errors.length), 7000);
      reloadBoard();
      if (o.done) o.done(r);
    });
  }
  // 商品库批量：每个产品每一盘（还没试打验证的）各建一个试打任务
  async function bulkTrial(pids, src) {
    if (!pids.length) { toast(Z("请先勾选产品", "กรุณาเลือกสินค้าก่อน"), true); return; }
    if (!confirm(Z(`给选中的 ${pids.length} 个产品建试打任务？每个产品每一盘（还没试打验证的）各一个，自动选同机型的空闲打印机。没有切片文件的盘会现在切片。`,
      `สร้างงานทดลองพิมพ์ให้สินค้า ${pids.length} รายการ? ทีละเพลทที่ยังไม่ผ่านการทดลอง เลือกเครื่องรุ่นเดียวกันที่ว่าง เพลทที่ไม่มีไฟล์จะสไลซ์ให้`))) return;
    let made = 0, skipped = 0; const errs = [];
    for (const pid of pids) {
      try {
        const r = await apiJob("/api/trial", { json: { product_id: pid, all_plates: true, only_unverified: true, source: src || "library" } });
        made += (r.trials || [r]).length; skipped += (r.skipped || []).length;
        (r.errors || []).forEach((x) => errs.push(`${pid} ${x}`));
      } catch (e) { errs.push(`${pid}：${e.message}`); }
    }
    toast(Z(`已建 ${made} 个试打任务` + (skipped ? `，${skipped} 盘已验证跳过` : ""), `สร้างงานทดลองพิมพ์ ${made} งาน` + (skipped ? ` ข้าม ${skipped} เพลท` : "")) + (errs.length ? "。" + errs.slice(0, 3).join("；") : ""), !!errs.length, 9000);
    reloadBoard();
  }

  // ---------------- 🔍 检查切片文件（不打印） ----------------
  function checkHtml(r) {
    const ic = { error: "❌", warn: "⚠️", ok: "✅" };
    return `<div class="tr-box"><div class="row between wrap"><b>${r.ok ? "✅ " + Z("可以打", "พิมพ์ได้") : "❌ " + Z("有问题，先别打", "มีปัญหา อย่าเพิ่งพิมพ์")}</b>
        <span class="small muted" data-notr>${E(r.printer_label)} · ${Z("盘", "เพลท")} ${r.plate.no}/${r.plate.total}${r.plate.name ? " · " + E(r.plate.name) : ""}${r.file ? " · #" + r.file.id + " " + E(r.file.filename) : ""}${r.sliced_now ? " · " + Z("刚切的", "เพิ่งสไลซ์") : ""}</span></div>
      ${r.checks.map((c) => `<div class="tr-chk ${c.level}"><span>${ic[c.level]}</span><span>${E(lbl(c))}</span></div>`).join("")}
      ${r.preview_svg ? `<div class="small muted" style="margin-top:6px">${Z("第一层预览（红色方块 = 拓竹废料口）", "ตัวอย่างชั้นแรก (สี่เหลี่ยมแดง = ช่องทิ้งเศษของ Bambu)")}</div><div class="tr-prev">${r.preview_svg}</div>` : ""}
      ${r.grams ? `<div class="small muted">${Z("切片", "สไลซ์")} ${r.grams} g · ${r.hours || "?"} h${r.est_grams ? ` · ${Z("估算", "ประมาณ")} ${r.est_grams} g · ${r.est_hours || "?"} h` : ""}</div>` : ""}</div>`;
  }
  async function checkDialog(o) {
    const q = `pid=${enc(o.pid)}&spec=${enc(o.spec || "")}&plate=${enc(o.plate || "")}`;
    let d;
    try { d = await api(`/api/trial/printers?${q}`); } catch (e) { toast(e.message, true); return; }
    const el = modal(`<div class="row between"><h3>🔍 ${Z("检查切片文件", "ตรวจไฟล์สไลซ์")} · <span class="mono" data-notr>${E(o.pid)}</span></h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      <p class="small muted">${Z("不打印，只检查：机型 / 喷嘴 / 热床板、克数和时长、零件是不是都在热床上（有没有压到拓竹废料口）、颜色槽。这一盘没有文件时先切片。", "ไม่พิมพ์ แค่ตรวจ: รุ่นเครื่อง หัวฉีด แผ่นฐาน น้ำหนัก/เวลา ชิ้นงานอยู่บนฐานทั้งหมดไหม (ไม่ทับช่องทิ้งเศษ) ช่องสี ถ้าเพลทนี้ไม่มีไฟล์จะสไลซ์ก่อน")}</p>
      <div class="row gap wrap"><label>${Z("打印机", "เครื่องพิมพ์")} <select id="tr-pr">${d.printers.map((p) => `<option value="${p.index}" data-notr>${E(p.label)}${p.idle ? "" : " · " + Z("忙", "ไม่ว่าง")}</option>`).join("")}</select></label>
        <button class="primary" id="tr-run">🔍 ${Z("检查", "ตรวจ")}</button></div>
      <div id="tr-res"></div>`);
    const run = async () => {
      let r;
      try { r = await apiJob("/api/trial/check-file", { json: { product_id: o.pid, spec: o.spec == null ? undefined : o.spec, plate_id: o.plate || "", printer: $("#tr-pr", el).value, file_id: o.file || undefined } }); }
      catch (e) { toast(e.message, true); return; }
      $("#tr-res", el).innerHTML = checkHtml(r) + `<div class="row gap wrap">${r.ok ? `<button class="big primary" id="tr-try">🧪 ${Z("试打这一盘", "ทดลองพิมพ์เพลทนี้")}</button>` : ""}</div>`;
      const t = $("#tr-try", el);
      if (t) t.onclick = () => { MODAL.close(); trialDialog({ pid: o.pid, spec: o.spec, plate: r.plate.id, file: r.file && r.file.id, src: "check" }); };
    };
    $("#tr-run", el).onclick = (e) => busy(e.target, run);
  }

  // ---------------- 🧪 试打结果 ----------------
  function photoThumbs(names) {
    return (names || []).length ? `<div class="tr-ph">${names.map((n) => `<a href="/api/print-files/photo/${E(n)}" target="_blank"><img src="/api/print-files/photo/${E(n)}" alt="" loading="lazy"></a>`).join("")}</div>` : "";
  }
  async function resultForm(jobId, done) {
    let t;
    try { t = await api(`/api/trial/job/${jobId}`); } catch (e) { toast(e.message, true); return; }
    const pl = t.plate_total > 1 ? `${Z("盘", "เพลท")} ${t.plate_no}/${t.plate_total}${t.plate_name ? " · " + t.plate_name : ""}` : "";
    const el = modal(`<div class="row between"><h3>🧪 ${Z("试打结果", "ผลการทดลองพิมพ์")} · <span class="mono" data-notr>${E(t.sku || t.product_id)}</span></h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      ${pl ? `<div class="small" data-notr>🧩 ${E(pl)}</div>` : ""}
      <div class="row gap"><label class="row big"><input type="radio" name="tr-ok" value="1" checked> ✅ ${Z("成功", "สำเร็จ")}</label><label class="row big"><input type="radio" name="tr-ok" value="0"> ❌ ${Z("失败", "ล้มเหลว")}</label></div>
      <div class="tr-box"><b>${Z("有什么问题", "มีปัญหาอะไร")}</b> <span class="small muted">${Z("（成功也可以勾，记下来改进）", "(สำเร็จก็ติ๊กได้ เพื่อบันทึกไว้ปรับปรุง)")}</span>
        <div class="tr-issues">${ISSUES.map(([zh, th]) => `<label class="row"><input type="checkbox" data-iss="${zh}"> ${Z(zh, th)}</label>`).join("")}</div>
        <label>${Z("说明", "หมายเหตุ")}<input id="tr-note" data-notr></label></div>
      <div class="row gap wrap"><label>${Z("实际克数（含冲刷）", "น้ำหนักจริง (รวมล้างสี)")} g <input id="tr-g" type="number" step="0.1" style="width:90px" value="${t.prefill.grams ?? ""}"></label>
        <label>${Z("实际时长", "เวลาจริง")} h <input id="tr-h" type="number" step="0.01" style="width:90px" value="${t.prefill.hours ?? ""}"></label>
        ${t.plate_total > 1 ? "" : `<label title="${Z("去掉支撑后，一件成品放秤上称的克数：写进产品的实物数据（净重 = 实称），上架用", "ชั่งชิ้นงาน 1 ชิ้นหลังแกะซัพพอร์ต: บันทึกเป็นน้ำหนักสุทธิ (ชั่งจริง) ใช้ตอนลงขาย")}">⚖ ${Z("称重（一件成品，克）", "ชั่งน้ำหนัก (1 ชิ้น, กรัม)")} <input id="tr-w" type="number" step="0.1" min="0" style="width:90px"></label>`}</div>
      <div class="small muted">${Z("已按打印批次 / 文件预填，可以改成打印机报告或称重的实际值；成功后会写回款式，成本跟着更新。", "เติมไว้ให้จากรอบพิมพ์ / ไฟล์ แก้เป็นค่าจริงจากเครื่องหรือที่ชั่งได้ เมื่อสำเร็จจะบันทึกกลับไปที่ตัวเลือกสินค้า ต้นทุนจะปรับตาม")}</div>
      <div id="tr-dest" class="tr-box"><b>${Z("这批成品去哪", "ชิ้นงานนี้ไปไหน")}</b>
        ${t.dests.map((d, i) => `<label class="row"><input type="radio" name="tr-dest" value="${d.key}" ${i === 0 ? "checked" : ""}> ${{ stock: Z("合格入库（→ 待检区 → 质检合格才可售）", "ผ่าน เข้าสต็อก (→ โซนรอตรวจ → ผ่านตรวจจึงขายได้)"), sample: Z("当样品（不卖，记录）", "เป็นตัวอย่าง (ไม่ขาย บันทึกไว้)"), scrap: Z("报废", "ทิ้ง") }[d.key]}</label>`).join("")}
        ${t.can_stock ? "" : `<div class="small muted">${Z("这个产品要打好几盘才是一整件，单独一盘不能入库。", "สินค้านี้ต้องพิมพ์หลายเพลทจึงครบชิ้น เพลทเดียวเข้าสต็อกไม่ได้")}</div>`}</div>
      <label class="filebtn mini-file">📷 ${Z("拍照 / 选照片", "ถ่ายรูป / เลือกรูป")}<input type="file" id="tr-ph" accept="image/*" capture="environment" multiple hidden></label> <span id="tr-phn" class="small muted"></span>
      <div><button class="big primary" id="tr-save">${Z("保存试打结果", "บันทึกผล")}</button></div>`, true);
    const sync = () => { const ok = $('input[name="tr-ok"]:checked', el).value === "1"; $("#tr-dest", el).classList.toggle("hidden", !ok); };
    el.onchange = (e) => { sync(); if (e.target.id === "tr-ph") $("#tr-phn", el).textContent = e.target.files.length + " " + Z("张", "รูป"); };
    $("#tr-save", el).onclick = () => busy($("#tr-save", el), async () => {
      const ok = $('input[name="tr-ok"]:checked', el).value === "1";
      const fd = new FormData();
      fd.append("ok", ok ? "1" : "0");
      $$("[data-iss]", el).filter((x) => x.checked).forEach((x) => fd.append("issues", x.dataset.iss));
      fd.append("note", $("#tr-note", el).value);
      fd.append("grams", $("#tr-g", el).value); fd.append("hours", $("#tr-h", el).value);
      if ($("#tr-w", el) && ok) fd.append("weighed", $("#tr-w", el).value);
      if (ok) fd.append("dest", ($('input[name="tr-dest"]:checked', el) || {}).value || "");
      [...$("#tr-ph", el).files].forEach((f) => fd.append("photo", f));
      const r = await api(`/api/trial/job/${jobId}/result`, { method: "POST", body: fd });
      MODAL.close();
      toast(ok ? Z("试打合格：文件已标记「已试打验证」，克数 / 时长已写回款式", "ผ่านการทดลอง: ไฟล์ถูกตั้งเป็น「ผ่านการทดลองพิมพ์」แล้ว บันทึกน้ำหนัก/เวลากลับไปที่สินค้า")
        : Z("已记录失败。" + r.hint, "บันทึกความล้มเหลวแล้ว ลองแก้แผนการพิมพ์ / สไลซ์ใหม่ แล้วกด「ลองอีกครั้ง」"), !ok, 8000);
      reloadBoard();
      if (!ok) failFollow(r);
      if (done) done(r);
    });
  }
  function failFollow(r) {
    if (confirm(Z("失败了。去调整打印方案（摆放 / 方向 / 支撑）重新切片后，再点「再试一次」。\n\n现在就用同样的设置再试一次？", "ล้มเหลว ปรับแผนการพิมพ์ (การวาง / ทิศทาง / ซัพพอร์ต) แล้วสไลซ์ใหม่ จากนั้นกด「ลองอีกครั้ง」\n\nลองอีกครั้งด้วยการตั้งค่าเดิมเลยไหม?"))) {
      busyToast(Z("再试一次", "ลองอีกครั้ง"), () => apiJob(`/api/trial/${r.id}/retry`, { json: {} })).then(() => { toast(Z("已建新的试打任务", "สร้างงานทดลองพิมพ์ใหม่แล้ว")); reloadBoard(); }).catch((e) => toast(e.message, true));
    }
  }

  // ---------------- 试打记录（商品 360 / 编辑页 / 打印方案） ----------------
  function histHtml(h, withRetry) {
    if (!h.rows.length) return `<div class="small muted">${Z("还没有试打记录", "ยังไม่มีบันทึกการทดลองพิมพ์")}</div>`;
    const st = { success: [Z("成功", "สำเร็จ"), "tr-ok"], fail: [Z("失败", "ล้มเหลว"), "tr-bad"], queued: [Z("排队 / 打印中", "รอคิว / กำลังพิมพ์"), ""], await: [Z("等结果", "รอผล"), ""] };
    return `<div class="tr-hist"><div><b>${Z("试打", "ทดลองพิมพ์")} ${h.count}</b> ${Z("次", "ครั้ง")} · ${Z("成功率", "อัตราสำเร็จ")} <b>${h.rate == null ? "—" : h.rate + "%"}</b>
      ${h.issues.length ? ` · ${Z("常见问题", "ปัญหาที่พบบ่อย")}：${h.issues.map(([k, n]) => `${E(TH() ? (ISSUES.find((x) => x[0] === k) || [0, k])[1] : k)}×${n}`).join("、")}` : ""}
      ${h.waiting ? ` · <span class="pill kind-trial">${Z(`${h.waiting} 个进行中`, `${h.waiting} งานค้าง`)}</span>` : ""}</div>
      ${photoThumbs(h.photos)}
      <table><thead><tr><th>${Z("时间", "เวลา")}</th><th>${Z("盘", "เพลท")}</th><th>${Z("结果", "ผล")}</th><th>${Z("问题", "ปัญหา")}</th><th>g / h</th><th></th></tr></thead><tbody>
      ${h.rows.slice(0, 8).map((t) => `<tr><td>${E(t.created_at ? fmtTime(t.created_at).slice(0, 10) : "")}</td><td data-notr>${t.plate_total > 1 ? t.plate_no + "/" + t.plate_total + (t.plate_name ? " " + E(t.plate_name) : "") : "—"}</td>
        <td class="${st[t.status][1]}">${st[t.status][0]}${t.dest_zh ? " · " + Z(t.dest_zh, { stock: "เข้าสต็อก", sample: "ตัวอย่าง", scrap: "ทิ้ง" }[t.dest]) : ""}</td>
        <td data-notr>${E((t.issues || []).join("、"))}${t.note ? " " + E(t.note) : ""}</td><td>${t.grams ?? ""}${t.hours ? " / " + t.hours : ""}</td>
        <td>${t.status === "fail" && withRetry ? `<button class="mini" data-tr-retry="${t.id}">${Z("再试一次", "ลองอีกครั้ง")}</button>` : ""}${t.status === "await" ? `<button class="mini" data-tr-res="${t.job_id}">${Z("填结果", "กรอกผล")}</button>` : ""}</td></tr>`).join("")}
      </tbody></table></div>`;
  }
  async function mount(el, pid, withRetry) {
    if (!el) return;
    try { const h = await api(`/api/trial/history?pid=${enc(pid)}`); el.innerHTML = histHtml(h, withRetry !== false); } catch (e) { el.innerHTML = `<span class="small muted">${E(e.message)}</span>`; }
  }
  async function retry(id) {
    await busyToast(Z("再试一次", "ลองอีกครั้ง"), () => apiJob(`/api/trial/${id}/retry`, { json: {} }));
    toast(Z("已建新的试打任务", "สร้างงานทดลองพิมพ์ใหม่แล้ว")); reloadBoard();
  }

  // ---------------- 打印机 🧪 打印测试 ----------------
  async function printerTest(idx, btn, pid) {
    const msg = Z("给这台打印机切一个 20 mm 立方体并打印，用来检查：连接、发送、开始、打完回报。\n\n请确认：热床已经清空、料盘里装了 PLA。\n确定开始？", "สไลซ์ลูกบาศก์ 20 มม. แล้วพิมพ์บนเครื่องนี้ เพื่อทดสอบการเชื่อมต่อ การส่ง การเริ่ม และการรายงานเมื่อเสร็จ\n\nกรุณายืนยัน: ฐานพิมพ์ว่าง และมีเส้น PLA ในเครื่อง\nเริ่มเลยไหม?");
    if (!confirm(msg)) return;
    await busy(btn, async () => {
      try {
        const r = await apiJob(`/api/printers/${idx}/print-test`, { json: { confirm: { bed_clear: true, material: true }, printer_id: pid || undefined } });
        toast(Z(`已发送并开始：${r.printer}。打完以后看板上会自动结束这个测试`, `ส่งและเริ่มพิมพ์แล้ว: ${r.printer} เมื่อเสร็จบอร์ดจะปิดงานทดสอบให้เอง`), false, 8000);
      } catch (e) {
        if (/料盘里读到的是/.test(e.message) && confirm(e.message + "\n\n" + Z("料盘读数不准、已经确认装的是对的，仍然发送？", "ค่าที่อ่านจากถาดไม่แม่น ยืนยันว่าถูกแล้ว ส่งต่อไหม?"))) {
          const r = await apiJob(`/api/printers/${idx}/print-test`, { json: { confirm: { bed_clear: true, material: true, tray_override: true }, printer_id: pid || undefined } });
          toast(Z("已发送并开始：", "ส่งและเริ่มพิมพ์แล้ว: ") + r.printer);
        } else throw e;
      }
    });
  }

  // ---------------- 看板：类型标签筛选 / 等结果提示 / ➕ 新建任务 ----------------
  function filterBoard(b) {
    const bar = $("#prod-kindbar");
    const count = {};
    const all = [].concat(...b.lanes.map((l) => l.queue.concat(l.runs.flatMap((r) => r.jobs))), b.unassigned, b.post, b.packed);
    all.forEach((j) => { const k = j.kind || "order"; count[k] = (count[k] || 0) + 1; });
    if (bar) {
      bar.innerHTML = `<b class="small">${Z("类型", "ประเภท")}：</b>` + KINDS.map(([k, zh, th]) => `<span class="chip ${KF === k ? "on" : ""}" data-knd="${k}"><span class="pill kind-${k || "order"}" ${k ? "" : 'style="background:#eef1f5;color:#455"'}>${Z(zh, th)}</span>${k ? " " + (count[k] || 0) : ""}</span>`).join("");
    }
    if (KF) {
      const keep = (j) => (j.kind || "order") === KF;
      b.lanes.forEach((l) => { l.queue = l.queue.filter(keep); l.runs = l.runs.filter((r) => r.jobs.some(keep)); });
      b.unassigned = b.unassigned.filter(keep); b.post = b.post.filter(keep); b.packed = b.packed.filter(keep);
    }
    // 打完、等着填试打结果的
    api("/api/trial/pending").then((p) => {
      const box = $("#prod-trial-pending"); if (!box) return;
      box.innerHTML = p.rows.length ? `<div class="tr-pend">🧪 <b>${Z(`${p.rows.length} 个试打打完了，等你填试打结果`, `มี ${p.rows.length} งานทดลองพิมพ์ที่พิมพ์เสร็จ รอกรอกผล`)}</b>
        ${p.rows.map((t) => `<button class="mini" data-tr-res="${t.job_id}"><span data-notr>${E(t.sku || t.product_id)}</span>${t.plate_total > 1 ? " " + Z("盘", "เพลท") + t.plate_no : ""} →</button>`).join(" ")}</div>` : "";
    }).catch(() => {});
    return b;
  }
  async function newTaskDialog() {
    let all;
    try { all = await api("/api/skus"); } catch (e) { toast(e.message, true); return; }
    const el = modal(`<div class="row between"><h3>➕ ${Z("新建任务", "สร้างงานใหม่")}</h3><button class="mini" data-mclose>${Z("关闭", "ปิด")}</button></div>
      <p class="small muted">${Z("不用订单：搜 SKU / 品名，选中后「生产」（备货）或「试打」。", "ไม่ต้องมีออเดอร์: ค้นหา SKU / ชื่อสินค้า แล้วเลือก「ผลิต」(เตรียมสต็อก) หรือ「ทดลองพิมพ์」")}</p>
      <input id="tr-q" placeholder="${Z("搜 SKU / 品名", "ค้นหา SKU / ชื่อ")}" data-notr style="width:100%">
      <div id="tr-list" class="tr-box" style="max-height:300px;overflow:auto"></div>`);
    const draw = () => {
      const q = $("#tr-q", el).value.trim().toLowerCase();
      const rows = all.filter((x) => !q || (x.sku + " " + (x.name || "") + " " + (x.pid || "")).toLowerCase().includes(q)).slice(0, 40);
      $("#tr-list", el).innerHTML = rows.map((x) => `<div class="row between gap" style="padding:3px 0;border-bottom:1px solid #eef1f5"><span data-notr><b class="mono">${E(x.sku)}</b> ${E(x.name || "")}</span>
        <span class="nowrap"><button class="mini" data-nt-stock="${E(x.pid)}" data-nt-sku="${E(x.sku)}">➕ ${Z("生产", "ผลิต")}</button> <button class="mini" data-nt-trial="${E(x.pid)}" data-nt-sku="${E(x.sku)}">🧪 ${Z("试打", "ทดลอง")}</button></span></div>`).join("")
        || `<span class="muted small">${Z("没有匹配的 SKU", "ไม่พบ SKU")}</span>`;
    };
    $("#tr-q", el).oninput = draw; draw();
    el.onclick = (e) => {
      const s = e.target.closest("[data-nt-stock]"), t = e.target.closest("[data-nt-trial]");
      if (s) { MODAL.close(); stockDialog({ pids: [s.dataset.ntStock], skus: [s.dataset.ntSku], source: "board" }); }
      if (t) { MODAL.close(); trialDialog({ pid: t.dataset.ntTrial, sku: t.dataset.ntSku, src: "board" }); }
    };
  }

  // ---------------- 统一接按钮 ----------------
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-tr-stock],[data-tr-trial],[data-tr-check],[data-tr-res],[data-tr-retry],[data-knd],#btn-prod-new,[data-tr-ptest]");
    if (!t) return;
    const d = t.dataset;
    if (t.id === "btn-prod-new") { e.preventDefault(); newTaskDialog(); return; }
    if (d.knd !== undefined && t.classList.contains("chip")) { KF = d.knd; reloadBoard(); return; }
    if (d.trStock !== undefined) { e.preventDefault(); e.stopPropagation(); stockDialog({ pids: d.trStock.split(",").filter(Boolean), skus: (d.trSkus || "").split(",").filter(Boolean), source: d.trSrc || "" }); return; }
    if (d.trTrial !== undefined) {
      e.preventDefault(); e.stopPropagation();
      trialDialog({ pid: d.trTrial, sku: d.trSku || "", spec: d.trSpec, plate: d.trPlate || "", file: d.trFile || "", all: d.trAll === "1", unv: d.trUnv === "1", src: d.trSrc || "" }); return;
    }
    if (d.trCheck !== undefined) { e.preventDefault(); e.stopPropagation(); checkDialog({ pid: d.trCheck, spec: d.trSpec, plate: d.trPlate || "", file: d.trFile || "" }); return; }
    if (d.trRes !== undefined) { e.preventDefault(); e.stopPropagation(); resultForm(+d.trRes); return; }
    if (d.trRetry !== undefined) { e.preventDefault(); e.stopPropagation(); retry(+d.trRetry).catch((x) => toast(x.message, true)); return; }
    if (d.trPtest !== undefined) { e.preventDefault(); e.stopPropagation(); printerTest(+d.trPtest, t, d.trPid || ""); return; }
  });

  const can = () => typeof ME === "undefined" || !ME || ["owner", "production"].includes(ME.role);
  window.TRIAL = { can, stockDialog, trialDialog, checkDialog, resultForm, mount, histHtml, filterBoard, printerTest, bulkTrial, newTaskDialog, kindName };
})();
