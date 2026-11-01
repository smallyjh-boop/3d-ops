"use strict";
// v2.52 打印方案（生产用）：每个规格一份，一份 = 一盘或几盘。每盘：打印机、层高、AMS 槽（材料 + 颜色）、零件（方向、用哪个槽、位置）。
// 手动摆盘：按打印机热床大小画俯视图，每个零件是它的俯视轮廓，可以拖动、旋转、复制；「自动排列」后再微调；重叠 / 超出热床标红。
// 款式（白款 / 黑款…）= 配色方案（每个槽装什么颜色）。保存后生产任务、成本、扣耗材都按这里。服务器在 modules/model/printplan.py。
// v2.53：编辑页里默认收起（m3.js 显示一行摘要，点「查看 / 编辑」才打开）；规格由 ③ 顶部切换；撤销 / 重做（Ctrl+Z / Ctrl+Y）；
// 「从组装生成打印方案」（展示里的零件平放、自动排盘）。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  let S = null;          // {pid, spec, d(服务器数据), plan(正在改的), fps, sel: {pl, uid}, colour, dirty, undo: [], redo: []}
  let BOX = null;

  const css = `
  .ed-sec{border:1px solid var(--line,#e3e6eb);border-radius:10px;padding:10px 12px;margin:10px 0;background:var(--card,#fff)}
  .ed-sec-plan{border-color:#c9dcf5;background:linear-gradient(#f6faff,#fff 120px)}
  .ed-sec-h{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:8px}
  .ed-sec-tag{font-weight:700;border-radius:6px;padding:2px 10px;font-size:14px}
  .ed-sec-tag.show{background:#fff3e0;color:#a35b00}.ed-sec-tag.plan{background:#e3f0ff;color:#0b5cad}
  .pp-bar{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:4px 0 8px}
  .pp-plate{border:1px solid #dfe5ee;border-radius:10px;padding:8px 10px;margin:8px 0;background:#fff}
  .pp-ph{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between}
  .pp-ph label{font-size:13px}
  .pp-grid{display:grid;grid-template-columns:minmax(260px,480px) minmax(280px,1fr);gap:12px;margin-top:6px}
  @media (max-width:1100px){.pp-grid{grid-template-columns:1fr}}
  .pp-cv{width:100%;max-width:520px;touch-action:none;border-radius:8px;background:#fafbfc;cursor:grab;display:block}
  .pp-cv:focus{outline:2px solid #6aa7ee}
  .pp-tools{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0}
  .pp-tools button{padding:3px 8px}
  .pp-st{font-size:13px;margin:4px 0}.pp-st.ok{color:#18794e}.pp-st.bad{color:#c62828;font-weight:600}
  .pp-slots{width:100%;border-collapse:collapse;font-size:13px}.pp-slots td,.pp-slots th{padding:3px 4px;border-bottom:1px solid #eef1f5;text-align:left}
  .pp-sw{display:inline-block;width:14px;height:14px;border-radius:4px;border:1px solid rgba(0,0,0,.25);vertical-align:-2px;margin-right:4px}
  .pp-items{max-height:260px;overflow:auto;border:1px solid #eef1f5;border-radius:8px}
  .pp-items table{width:100%;border-collapse:collapse;font-size:12.5px}.pp-items td{padding:3px 4px;border-bottom:1px solid #f1f3f6;vertical-align:middle}
  .pp-items tr.on{background:#eaf3ff}.pp-items tr.bad td:first-child{border-left:3px solid #e53935}
  .pp-items select{max-width:130px}
  .pp-use{font-size:13px;background:#f7f9fc;border-radius:8px;padding:6px 8px;margin-top:6px}
  .pp-use table{border-collapse:collapse}.pp-use td,.pp-use th{padding:2px 8px 2px 0;text-align:left}
  .pp-est{font-size:11px;border-radius:4px;padding:0 4px;background:#fff3cd;color:#8a6100;margin-left:4px}
  .pp-sch td,.pp-sch th{padding:3px 6px}
  .pp-acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
  .pp-3d{height:300px;margin-top:6px}
  .asm-box{border:1px solid #f0d9b5;border-radius:10px;padding:8px;margin-top:8px;background:#fffdf8}
  `;
  if (!document.getElementById("pp-css")) { const st = document.createElement("style"); st.id = "pp-css"; st.textContent = css; document.head.appendChild(st); }

  const clone = (o) => JSON.parse(JSON.stringify(o));
  const uid = () => "i" + Math.random().toString(16).slice(2, 8);
  const hexOf = (name) => { try { return (window.colorInfo ? colorInfo(name || "") : { hex: "#cfcfcf" }).hex || "#cfcfcf"; } catch { return "#cfcfcf"; } };
  const colourNames = () => Object.keys(window.COLORS || {});
  const cl = (c) => { if (!c || !TH()) return c; try { const i = window.colorInfo ? colorInfo(c) : null; return (i && i.th) || c; } catch { return c; } };   // 颜色名：泰文界面显示泰文名
  const n1 = (v) => (v == null ? "-" : (Math.round(v * 10) / 10).toString());
  const bedOf = (name) => { const m = (S.d.printers || []).find((x) => x.name === name); return (m && m.bed) || [256, 256, 256]; };
  const prModel = (name) => (S.d.printers || []).find((x) => x.name === name) || {};
  const plateOf = (id) => S.plan.plates.find((x) => x.id === id);
  const libOf = (id) => (S.d.library || []).find((x) => x.id === id);
  function labelOf(it) {
    const e = libOf(it.id);
    if (!e) return it.id;
    if (it.part == null) return e.name;
    const pt = (e.parts || []).find((x) => x.index === it.part);
    return `${e.name} / ${pt ? pt.name : "#" + (it.part + 1)}`;
  }
  // 这个款式下每个槽的颜色（配色方案 > 槽的固定颜色 > 款式颜色）
  function slotColour(pl, slot) {
    const sch = (S.plan.schemes || {})[S.colour] || {};
    const s = (pl.slots || []).find((x) => x.slot === slot) || {};
    return sch[String(slot)] || s.colour || S.colour || "";
  }

  // ---------------- 几何（和服务器 printplan.py 一样的算法） ----------------
  function poly(fp, x, y, rot) {
    const a = (rot || 0) * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
    const h = fp.hull && fp.hull.length >= 3 ? fp.hull : [[-fp.w / 2, -fp.d / 2], [fp.w / 2, -fp.d / 2], [fp.w / 2, fp.d / 2], [-fp.w / 2, fp.d / 2]];
    return h.map(([px, py]) => [x + px * c - py * s, y + px * s + py * c]);
  }
  function overlap(a, b) {
    let depth = Infinity;
    for (const P of [a, b]) {
      for (let i = 0; i < P.length; i++) {
        const [x1, y1] = P[i], [x2, y2] = P[(i + 1) % P.length];
        let ax = y1 - y2, ay = x2 - x1; const ln = Math.hypot(ax, ay); if (ln < 1e-9) continue; ax /= ln; ay /= ln;
        const pa = a.map(([x, y]) => x * ax + y * ay), pb = b.map(([x, y]) => x * ax + y * ay);
        const d = Math.min(Math.max(...pa), Math.max(...pb)) - Math.max(Math.min(...pa), Math.min(...pb));
        if (d <= 0) return 0;
        depth = Math.min(depth, d);
      }
    }
    return depth === Infinity ? 0 : depth;
  }
  function check(pl) {
    const bed = bedOf(pl.printer), res = {}, polys = {};
    const ex = prModel(pl.printer).exclude, exr = ex ? [[ex[0], ex[1]], [ex[2], ex[1]], [ex[2], ex[3]], [ex[0], ex[3]]] : null;   // v2.53 拓竹废料口
    for (const it of pl.items) {
      const f = S.fps[it.uid]; if (!f || it.x == null) continue;
      const pg = poly(f, it.x, it.y, it.rot); polys[it.uid] = pg;
      res[it.uid] = { out: pg.some(([x, y]) => x < -0.5 || y < -0.5 || x > bed[0] + 0.5 || y > bed[1] + 0.5) || f.h > bed[2] + 0.5 || (exr ? overlap(pg, exr) > 0.3 : false), overlap: [] };
    }
    const ids = Object.keys(polys);
    for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
      if (overlap(polys[ids[i]], polys[ids[j]]) > 0.3) { res[ids[i]].overlap.push(ids[j]); res[ids[j]].overlap.push(ids[i]); }
    }
    return res;
  }

  // ---------------- 撤销 / 重做（v2.53） ----------------
  function mark() {                    // 改之前调用：记下现在的样子
    if (!S || !S.plan) return;
    const snap = JSON.stringify(S.plan);
    if (S.undo.length && S.undo[S.undo.length - 1] === snap) return;
    S.undo.push(snap); if (S.undo.length > 80) S.undo.shift();
    S.redo = [];
  }
  async function undoRedo(back) {
    if (!S) return;
    const from = back ? S.undo : S.redo, to = back ? S.redo : S.undo;
    if (!from.length) { toast(back ? Z("没有可以撤销的", "ไม่มีอะไรให้ย้อน") : Z("没有可以重做的", "ไม่มีอะไรให้ทำซ้ำ")); return; }
    to.push(JSON.stringify(S.plan));
    S.plan = JSON.parse(from.pop());
    S.dirty = true;
    if (S.sel && !plateOf(S.sel.pl)) S.sel = { pl: (S.plan.plates[0] || {}).id, uid: null };
    try { await fpFor(S.plan.plates.flatMap((pl) => pl.items)); } catch { /* 忽略 */ }
    render();
  }

  // ---------------- 读取 / 保存 ----------------
  async function mount(el, pid, spec) {
    BOX = el;
    if (!pid) { el.innerHTML = ""; S = null; return; }
    if (!S || S.pid !== pid) S = { pid, spec: "", colour: "", undo: [], redo: [] };
    if (spec !== undefined) S.spec = spec || "";
    el.innerHTML = `<p class="muted small">${Z("读取打印方案…", "กำลังโหลดแผนการพิมพ์…")}</p>`;
    try { load(await api(`/api/products/${encodeURIComponent(pid)}/print-plan?spec=${encodeURIComponent(S.spec)}`)); }
    catch (e) { el.innerHTML = `<p class="bad small">${esc(e.message)}</p>`; }
  }
  function load(d, draft) {
    S.d = d; S.plan = clone(d.plan); S.fps = clone(d.footprints || {}); S.dirty = !!draft;
    if (!draft) { S.undo = []; S.redo = []; }
    if (!d.colours.includes(S.colour)) S.colour = d.colours[0] || "";
    if (!S.sel || !plateOf(S.sel.pl)) S.sel = { pl: (S.plan.plates[0] || {}).id, uid: null };
    render();
  }
  async function save(btn) {
    const run = async () => {
      const d = await api(`/api/products/${encodeURIComponent(S.pid)}/print-plan`, { json: { spec: S.spec, plan: S.plan } });
      load(d);
      toast(Z("打印方案已保存", "บันทึกแผนการพิมพ์แล้ว"));
      if (window.M3) M3.refresh();
      if (typeof P !== "undefined" && P && P.id === S.pid) {     // 成本按颜色拆分：变体的多色用量刷新
        try { const fresh = await api(`/api/products/${encodeURIComponent(S.pid)}`); P.variants.forEach((v, i) => { const f = (fresh.variants || []).find((x) => x.sku && x.sku === v.sku) || fresh.variants[i]; if (f) { v.colour_usage = f.colour_usage; v.purge_g = f.purge_g; } }); P.print_plans = fresh.print_plans; P.edit_rev = fresh.edit_rev; if (window.refreshPricing) refreshPricing(); } catch { /* 忽略 */ }
      }
    };
    try { if (btn) await busy(btn, run); else await run(); } catch (e) { toast(e.message, true); }
  }
  async function fpFor(items) {
    const need = items.filter((it) => !S.fps[it.uid] || S.fps[it.uid]._k !== `${it.id}/${it.part}/${it.orient}`);
    if (!need.length) return;
    const r = await api(`/api/products/${encodeURIComponent(S.pid)}/print-plan/footprint`, { json: { items: need.map((it) => ({ id: it.id, part: it.part, orient: it.orient })) } });
    need.forEach((it, k) => { S.fps[it.uid] = { ...r.items[k], _k: `${it.id}/${it.part}/${it.orient}` }; });
  }
  async function arrange(pl) {
    const r = await api(`/api/products/${encodeURIComponent(S.pid)}/print-plan/check`, { json: { plate: pl, arrange: true } });
    const byUid = Object.fromEntries(r.plate.items.map((x) => [x.uid, x]));
    pl.items.forEach((it) => { const n = byUid[it.uid]; if (n) { it.x = n.x; it.y = n.y; it.rot = n.rot; } });
    Object.assign(S.fps, r.footprints);
    pl.manual = true; S.dirty = true;
    if (r.missed) toast(Z(`有 ${r.missed} 个零件这一盘放不下（标红），减少数量或分成两盘`, `มี ${r.missed} ชิ้นวางไม่พอในถาดนี้ (สีแดง) ลดจำนวนหรือแบ่งเป็น 2 ถาด`), true);
  }

  // ---------------- 画面 ----------------
  function render() {
    const d = S.d;
    const specBar = `<div class="pp-bar small"><b>${S.spec ? `<span data-notr>${esc(S.spec)}</span>` : Z("主模型", "โมเดลหลัก")}</b>
      ${d.state === "inherit" ? `<span class="m3-tag inh">${Z("这个规格现在用主模型的打印方案；在这里改好保存后，这个规格用自己的方案", "แบบนี้ตอนนี้ใช้แผนของโมเดลหลัก ถ้าแก้และบันทึกที่นี่ แบบนี้จะใช้แผนของตัวเอง")}</span>` : ""}
      ${d.follow ? `<span class="m3-tag inh">${Z(`按主模型缩放 ${d.scale}%：盘和零件跟着主模型的方案，保存后改成这个规格自己的方案`, `ย่อ/ขยายจากโมเดลหลัก ${d.scale}%: ถ้าบันทึกจะเป็นแผนของแบบนี้เอง`)}</span>` : ""}
      <span class="pp-tools" style="margin-left:auto">
        <button class="mini" data-pp="undo" title="Ctrl+Z">↶ ${Z("撤销", "ย้อน")}</button><button class="mini" data-pp="redo" title="Ctrl+Y">↷ ${Z("重做", "ทำซ้ำ")}</button>
        <button class="mini primary-lite" data-pp="from-display" title="${Z("展示（组装）里的零件，每个按推荐方向平放，自动排盘（一盘放不下自动分盘），当草稿再改", "นำชิ้นงานจากการประกอบ วางราบตามทิศที่แนะนำ แล้วจัดถาดอัตโนมัติ (ร่าง)")}">🧩→🖨 ${Z("从组装生成打印方案", "สร้างแผนพิมพ์จากการประกอบ")}</button></span></div>`;
    const colBar = d.colours.length ? `<div class="pp-bar small"><span class="muted">${Z("看哪个款式（颜色）", "ดูแบบสีไหน")}：</span>
      ${d.colours.map((c) => `<span class="chip ${S.colour === c ? "on" : ""}" data-pp-col="${esc(c)}"><i class="pp-sw" style="background:${hexOf(c)}"></i><span data-notr>${esc(cl(c))}</span></span>`).join("")}</div>` : "";
    if (!(d.library || []).length) {
      BOX.innerHTML = specBar + `<p class="muted small">${Z("还没有模型文件。先上传 3D 模型（或在「📚 模型库」上传），再来排打印方案。", "ยังไม่มีไฟล์โมเดล อัปโหลดโมเดล 3D ก่อน แล้วค่อยวางแผนการพิมพ์")}</p>`;
      return;
    }
    BOX.innerHTML = `${specBar}${colBar}
      ${d.plan.default ? `<div class="small muted">${Z("还没保存过：下面是按现在的 3D 模型自动生成的一盘（单色）。改好后点「保存打印方案」。", "ยังไม่เคยบันทึก: ด้านล่างเป็นถาดที่สร้างอัตโนมัติจากโมเดลปัจจุบัน (สีเดียว) แก้แล้วกด「บันทึกแผนการพิมพ์」")}</div>` : ""}
      ${(d.warnings || []).map((w) => `<div class="small warn">${esc(w)}</div>`).join("")}
      <div id="pp-plates">${S.plan.plates.map(plateHtml).join("")}</div>
      <div class="row gap wrap small"><button class="mini" data-pp="add-plate">＋ ${Z("再加一盘（例如零件太多 / 盖子单独打）", "เพิ่มอีกถาด (เช่น ชิ้นเยอะ / ฝาพิมพ์แยก)")}</button></div>
      ${schemeHtml()}
      ${usageHtml()}
      <div class="pp-acts">
        <button class="primary" data-pp="save">💾 ${Z("保存打印方案", "บันทึกแผนการพิมพ์")}</button>
        <button data-pp="fill" title="${Z("按这个方案算的克数（含换色冲刷废料）和时长，填进这个规格每个颜色的变体", "ใส่กรัม (รวมเศษล้างสี) และเวลาตามแผนนี้ลงในตัวเลือกทุกสีของแบบนี้")}">${Z("按方案填克数 / 时长到变体", "ใส่กรัม / เวลาตามแผนลงตัวเลือก")}</button>
        <span class="small muted">${S.dirty ? `<b class="warn">${Z("有改动，还没保存", "มีการแก้ไข ยังไม่ได้บันทึก")}</b>` : (d.plan.updated_at ? Z("已保存 ", "บันทึกแล้ว ") + fmtTime(d.plan.updated_at) : "")}</span></div>`;
    S.plan.plates.forEach((pl) => draw(pl));
  }
  function plateHtml(pl, k) {
    const pm = prModel(pl.printer), multi = new Set(pl.slots.map((s) => slotColour(pl, s.slot))).size > 1;
    const bed = bedOf(pl.printer);
    const opts = (S.d.library || []).flatMap((e) => [`<option value="${e.id}|">${esc(e.name)}${e.multicolor ? " 🎨" : ""}${(e.parts || []).length > 1 ? Z("（整个）", " (ทั้งหมด)") : ""}</option>`,
      ...((e.parts || []).length > 1 ? e.parts.map((p) => `<option value="${e.id}|${p.index}">└ ${esc(p.name)}</option>`) : [])]).join("");
    const ck = check(pl);
    const nbad = Object.values(ck).filter((x) => x.out || x.overlap.length).length;
    const painted = pl.items.some((it) => { const e = libOf(it.id); return e && e.multicolor && it.part == null; });
    return `<div class="pp-plate" data-pl="${pl.id}">
      <div class="pp-ph"><b>${Z("第", "ถาดที่ ")}${k + 1}${Z(" 盘", "")}</b>
        <label>${Z("打印机", "เครื่องพิมพ์")} <select data-ppf="printer" data-notr>${S.d.printers.map((m) => `<option ${m.name === pl.printer ? "selected" : ""}>${esc(m.name)}</option>`).join("")}</select></label>
        <span class="small muted" data-notr>${bed[0]}×${bed[1]}×${bed[2]} mm</span>
        <label>${Z("层高", "ความสูงชั้น")} <select data-ppf="layer_height">${[0.08, 0.12, 0.16, 0.2, 0.24, 0.28].map((v) => `<option value="${v}" ${Math.abs(v - pl.layer_height) < 1e-6 ? "selected" : ""}>${v.toFixed(2)} mm</option>`).join("")}</select></label>
        <label title="${Z("这一盘打出来是几套成品（例如钥匙扣一盘 8 个 = 8 套）", "ถาดนี้ได้สินค้ากี่ชุด (เช่น พวงกุญแจ 8 ชิ้น = 8 ชุด)")}">${Z("这一盘出几套", "ถาดนี้ได้กี่ชุด")} <input type="number" min="1" max="200" value="${pl.sets}" data-ppf="sets" style="width:56px"></label>
        <span>${S.plan.plates.length > 1 ? `<button class="mini danger" data-pp="del-plate">${Z("删掉这一盘", "ลบถาดนี้")}</button>` : ""}</span></div>
      ${multi && pm.multicolor === false ? `<div class="small bad">⚠ ${Z("这台打印机没有 AMS，不能打多色。多色的盘请选拓竹 P1S 这类有 AMS 的打印机（设置 → 打印机「有 AMS / 多色」）", "เครื่องนี้ไม่มี AMS พิมพ์หลายสีไม่ได้ เลือกเครื่องที่มี AMS เช่น Bambu P1S")}</div>` : ""}
      <div class="pp-grid">
        <div>
          <canvas class="pp-cv" tabindex="0" data-cv="${pl.id}" aria-label="${Z("热床俯视图：拖动零件摆位置", "มุมมองจากด้านบนของฐาน: ลากชิ้นงานเพื่อจัดวาง")}"></canvas>
          <div class="pp-tools">
            <button class="mini primary-lite" data-pp="arrange" title="${Z("按大小排得最紧，一盘放最多", "เรียงให้แน่นที่สุด วางได้มากที่สุด")}">✨ ${Z("自动排列（省空间）", "จัดเรียงอัตโนมัติ (ประหยัดพื้นที่)")}</button>
            <button class="mini primary-lite" data-pp="kit" title="${Z("按组装关系摆：一起拼的零件放在一起、按组装顺序、朝向一致，员工和买家一看就懂（按原站说明 / 零件名；AI 开着时让 AI 分组）", "จัดตามความสัมพันธ์การประกอบ: ชิ้นที่ประกอบด้วยกันวางคู่กัน เรียงตามลำดับ (ตามคำอธิบาย / ชื่อชิ้นงาน / AI)")}">🧩 ${Z("组合摆盘（按说明 / AI）", "จัดเป็นชุด (ตามคำอธิบาย / AI)")}</button>
            <button class="mini" data-pp="rot" data-a="-15" title="${Z("选中的零件逆时针转 15°（也可以按住 Shift 滚轮）", "หมุนชิ้นที่เลือกทวนเข็ม 15°")}">⟲ 15°</button>
            <button class="mini" data-pp="rot" data-a="15">⟳ 15°</button>
            <button class="mini" data-pp="rot" data-a="90">↻ 90°</button>
            <button class="mini" data-pp="dup" title="${Z("复制选中的零件（数量在旁边填）", "คัดลอกชิ้นที่เลือก (ใส่จำนวนด้านข้าง)")}">⧉ ${Z("复制", "คัดลอก")}</button>
            <input type="number" min="1" max="50" value="1" data-pp-dupn style="width:46px" title="${Z("复制几个", "คัดลอกกี่ชิ้น")}">
            <button class="mini danger" data-pp="del-item">✕ ${Z("删除", "ลบ")}</button>
            <button class="mini" data-pp="3d">👁 3D</button>
          </div>
          <div class="pp-st ${nbad ? "bad" : "ok"}" data-st="${pl.id}">${statusTxt(pl, ck)}</div>
          ${S.kit && S.kit[pl.id] ? `<div class="small pp-kit">🧩 <b>${S.kit[pl.id].source === "ai" ? Z("AI 组合摆盘", "AI จัดเป็นชุด") : Z("按零件名组合摆盘", "จัดเป็นชุดตามชื่อชิ้นงาน")}</b>
            <span class="pp-est">${Z("仅供参考，可手动调整", "ใช้อ้างอิงเท่านั้น ปรับเองได้")}</span> <span data-notr>${esc((TH() ? S.kit[pl.id].note_th : S.kit[pl.id].note_zh) || "")}</span>
            ${(S.kit[pl.id].groups || []).length ? `<div class="muted">${S.kit[pl.id].groups.map((g, i) => `${Z("组", "กลุ่ม")} ${i + 1}: <span data-notr>${esc(g.name)}</span> (${g.uids.map((u) => pl.items.findIndex((x) => x.uid === u) + 1).filter((n) => n > 0).join(", ")})`).join(" · ")}</div>` : ""}</div>` : ""}
          <div class="small muted">${Z("拖动零件挪位置；选中后用按钮或 Shift + 滚轮旋转，方向键微调（1 mm）。", "ลากชิ้นงานเพื่อย้าย เลือกแล้วใช้ปุ่มหรือ Shift + ล้อเมาส์เพื่อหมุน ปุ่มลูกศรเลื่อนทีละ 1 mm")}
            ${pl.manual ? `<span class="pill tag-pill">${Z("手动摆盘", "จัดวางเอง")}</span>` : `<span class="pill">${Z("自动排列", "จัดเรียงอัตโนมัติ")}</span>`}</div>
          <div class="pp-3d hidden" data-3d="${pl.id}"></div>
        </div>
        <div>
          <div class="small"><b>${Z("AMS 耗材槽", "ช่องเส้นพลาสติก AMS")}</b> <span class="muted">${Z("（单色只用槽 1；多色每种颜色一个槽，最多 4 个）", "(สีเดียวใช้ช่อง 1; หลายสีใช้ช่องละสี สูงสุด 4)")}</span></div>
          <table class="pp-slots"><thead><tr><th>${Z("槽", "ช่อง")}</th><th>${Z("材料", "วัสดุ")}</th><th>${Z("颜色", "สี")}</th><th>${Z("这个款式装", "แบบนี้ใส่")}</th><th></th></tr></thead><tbody>
          ${pl.slots.map((s) => `<tr data-slot="${s.slot}"><td><b>${s.slot}</b></td>
            <td><select data-pps="material" data-notr>${["PLA", "PETG", "TPU", "ABS", "ASA", "PLA-CF", "PETG-CF"].concat([s.material]).filter((v, i, a) => v && a.indexOf(v) === i).map((m) => `<option ${m === s.material ? "selected" : ""}>${esc(m)}</option>`).join("")}</select></td>
            <td><select data-pps="colour"><option value="">${Z("跟着款式颜色", "ตามสีของแบบ")}</option>${colourNames().concat(s.colour && !colourNames().includes(s.colour) ? [s.colour] : []).map((c) => `<option value="${esc(c)}" ${c === s.colour ? "selected" : ""} data-notr>${esc(cl(c))}</option>`).join("")}</select></td>
            <td class="nowrap"><i class="pp-sw" style="background:${hexOf(slotColour(pl, s.slot))}"></i><span data-notr>${esc(cl(slotColour(pl, s.slot)) || "—")}</span></td>
            <td>${s.slot > 1 && !s.file_slot ? `<button class="mini" data-pp="del-slot" title="${Z("去掉这个槽（用它的零件改回槽 1）", "เอาช่องนี้ออก")}">✕</button>` : ""}</td></tr>`).join("")}
          </tbody></table>
          ${pl.slots.length < (S.d.slot_max || 4) && !painted ? `<button class="mini" data-pp="add-slot">＋ ${Z("加一个颜色槽（多色）", "เพิ่มช่องสี (หลายสี)")}</button>` : ""}
          ${painted ? `<div class="small muted">🎨 ${Z("涂色的多色 3MF（MakerWorld / 拓竹）按文件原样打，槽的颜色从文件里读；要改涂色请在 Bambu Studio 里改好再上传。", "ไฟล์ 3MF ที่ลงสีหลายสี (MakerWorld / Bambu) พิมพ์ตามไฟล์ สีของช่องอ่านจากไฟล์ ถ้าจะแก้สีให้แก้ใน Bambu Studio แล้วอัปโหลดใหม่")}</div>` : ""}
          <div class="small" style="margin-top:8px"><b>${Z("零件", "ชิ้นงาน")}</b> <span class="muted">(${pl.items.length})</span>
            <select data-pp-add data-notr><option value="">${Z("＋ 加零件…", "＋ เพิ่มชิ้นงาน…")}</option>${opts}</select></div>
          <div class="pp-items"><table><tbody>${pl.items.map((it, i) => itemRow(pl, it, i, ck)).join("") || `<tr><td class="muted">${Z("这一盘还没有零件", "ถาดนี้ยังไม่มีชิ้นงาน")}</td></tr>`}</tbody></table></div>
          <div class="pp-acts">
            <a class="btn mini-btn" href="/api/products/${encodeURIComponent(S.pid)}/print-plan/export?spec=${encodeURIComponent(S.spec)}&plate=${pl.id}&colour=${encodeURIComponent(S.colour)}" data-pp-dl title="${Z("按摆好的位置、每个零件带耗材槽的 3MF，拓竹 Studio / OrcaSlicer 打开就是摆好分好色的（先保存）", "ไฟล์ 3MF ตามตำแหน่งที่จัดไว้ แต่ละชิ้นกำหนดช่องสีแล้ว (บันทึกก่อน)")}">⬇ ${Z("下载这一盘（3MF）", "ดาวน์โหลดถาดนี้ (3MF)")}</a>
            <button class="mini" data-pp="slice" title="${Z("按摆好的位置切片（多色时每个槽一份耗材配置、开擦料塔），切好存成切片文件给生产用。需要 OrcaSlicer", "สไลซ์ตามตำแหน่งที่จัดไว้ ต้องมี OrcaSlicer")}">✂ ${Z("按这一盘切片", "สไลซ์ถาดนี้")}</button>
            ${window.TRIAL && TRIAL.can() ? `<button class="mini" data-tr-check="${esc(S.pid)}" data-tr-spec="${esc(S.spec)}" data-tr-plate="${esc(pl.id)}" title="${Z("不打印：用这一盘现有的切片文件（没有就先切片）核对机型 / 喷嘴 / 热床板、克数、零件是否都在热床上、颜色槽，并画第一层预览", "ไม่พิมพ์: ตรวจไฟล์สไลซ์ของเพลทนี้ (ไม่มีจะสไลซ์ก่อน) รุ่นเครื่อง หัวฉีด แผ่นฐาน น้ำหนัก ตำแหน่งชิ้นงาน ช่องสี พร้อมภาพชั้นแรก")}">🔍 ${Z("检查切片文件", "ตรวจไฟล์สไลซ์")}</button>
            <button class="mini" data-tr-trial="${esc(S.pid)}" data-tr-spec="${esc(S.spec)}" data-tr-plate="${esc(pl.id)}" data-tr-src="plan" title="${Z("选一台同机型的空闲打印机，用这一盘的文件试打（没有文件先切片）", "เลือกเครื่องรุ่นเดียวกันที่ว่าง ทดลองพิมพ์ด้วยไฟล์ของเพลทนี้ (ไม่มีไฟล์จะสไลซ์ก่อน)")}">🧪 ${Z("试打这一盘", "ทดลองพิมพ์เพลทนี้")}</button>` : ""}
            ${CAN("models.change") ? `<button class="mini" data-pp="merge" title="${Z("按摆好的位置合并成一个模型：主模型 → 设为 3D 模型；规格 → 指定给这个规格", "รวมเป็นโมเดลเดียวตามตำแหน่งที่จัดไว้")}">${Z("合并成一套（设为模型）", "รวมเป็นชุด (ตั้งเป็นโมเดล)")}</button>` : ""}
          </div>
          ${pl.sliced ? `<div class="small ok">✂ ${Z("已切片", "สไลซ์แล้ว")}：${(pl.sliced.filaments || []).map((f) => `${Z("槽", "ช่อง")} ${f.slot} ${n1(f.grams)} g`).join(" · ")}${pl.sliced.purge_g ? ` · ${Z("冲刷", "ล้างสี")} ${n1(pl.sliced.purge_g)} g` : ""}${pl.sliced.hours ? ` · ${n1(pl.sliced.hours)} h` : ""}</div>` : ""}
        </div>
      </div></div>`;
  }
  function itemRow(pl, it, i, ck) {
    const c = ck[it.uid] || {}, bad = c.out || (c.overlap || []).length;
    const e = libOf(it.id) || {}, painted = e.multicolor && it.part == null;
    return `<tr data-uid="${it.uid}" class="${S.sel.uid === it.uid ? "on" : ""} ${bad ? "bad" : ""}">
      <td class="nowrap"><b>${i + 1}</b></td>
      <td><span data-notr title="${esc(labelOf(it))}">${esc(labelOf(it).slice(-28))}</span>${bad ? `<div class="small bad">${c.out ? Z("超出热床", "เกินฐาน") : ""} ${(c.overlap || []).length ? Z("重叠", "ซ้อนกัน") : ""}</div>` : ""}</td>
      <td><select data-ppi="orient" title="${Z("摆放方向（哪一面贴热床）", "ทิศการวาง (ด้านไหนติดฐาน)")}">${Object.keys(S.d.orient_zh).map((k) => `<option value="${k}" ${k === it.orient ? "selected" : ""}>${esc(oriTxt(k))}</option>`).join("")}</select></td>
      <td>${painted ? `<span class="small muted">🎨 ${Z("文件自带颜色", "สีตามไฟล์")}</span>` : `<select data-ppi="slot" title="${Z("这个零件用哪个槽（颜色）", "ชิ้นนี้ใช้ช่องไหน (สี)")}">${pl.slots.map((s) => `<option value="${s.slot}" ${s.slot === it.slot ? "selected" : ""}>${Z("槽", "ช่อง")} ${s.slot} · ${esc(cl(slotColour(pl, s.slot)) || "")}</option>`).join("")}</select>`}</td>
      <td class="nowrap small muted">${S.fps[it.uid] ? `${n1(S.fps[it.uid].w)}×${n1(S.fps[it.uid].d)}×${n1(S.fps[it.uid].h)}` : ""}</td></tr>`;
  }
  function oriTxt(k) {
    const zh = { bottom: "底面朝下", top: "倒放", front: "前面朝下", back: "背面朝下", left: "左侧朝下", right: "右侧朝下" };
    const th = { bottom: "ฐานลง", top: "คว่ำ", front: "ด้านหน้าลง", back: "ด้านหลังลง", left: "ด้านซ้ายลง", right: "ด้านขวาลง" };
    return Z(zh[k] || k, th[k] || k);
  }
  function statusTxt(pl, ck) {
    const v = Object.values(ck), out = v.filter((x) => x.out).length, ov = v.filter((x) => x.overlap.length).length;
    if (!pl.items.length) return Z("这一盘是空的", "ถาดนี้ว่าง");
    if (!out && !ov) return "✓ " + Z(`${pl.items.length} 个零件，不重叠、都在热床内`, `${pl.items.length} ชิ้น ไม่ซ้อนกัน อยู่ในฐานทั้งหมด`);
    return "✗ " + [out ? Z(`${out} 个超出热床`, `${out} ชิ้นเกินฐาน`) : "", ov ? Z(`${ov} 个互相重叠`, `${ov} ชิ้นซ้อนกัน`) : ""].filter(Boolean).join(Z("，", ", ")) + Z("（红色）", " (สีแดง)");
  }
  function schemeHtml() {
    const multi = S.plan.plates.some((pl) => pl.slots.length > 1);
    if (!multi || !S.d.colours.length) return "";
    const maxS = Math.max(...S.plan.plates.map((pl) => pl.slots.length));
    const sl = Array.from({ length: maxS }, (_, i) => i + 1);
    const cn = colourNames();
    return `<details class="card-sub pp-schbox" open><summary class="small"><b>${Z("配色方案（每个款式的槽 → 颜色）", "การจับคู่สี (ช่อง → สี ของแต่ละแบบ)")}</b>
      <span class="muted">${Z("例如 白款：槽 1 白、槽 2 黑；黑款：槽 1 黑、槽 2 白。空着 = 用槽的颜色（或款式颜色）", "เช่น แบบขาว: ช่อง 1 ขาว ช่อง 2 ดำ; ว่าง = ใช้สีของช่อง")}</span></summary>
      <table class="grid small pp-sch"><thead><tr><th>${Z("款式", "แบบ")}</th>${sl.map((n) => `<th>${Z("槽", "ช่อง")} ${n}</th>`).join("")}</tr></thead><tbody>
      ${S.d.colours.map((c) => `<tr data-sch="${esc(c)}"><td class="nowrap"><i class="pp-sw" style="background:${hexOf(c)}"></i><span data-notr>${esc(cl(c))}</span></td>
        ${sl.map((n) => { const v = ((S.plan.schemes || {})[c] || {})[String(n)] || ""; return `<td><select data-sch-slot="${n}"><option value="">—</option>${cn.concat(v && !cn.includes(v) ? [v] : []).map((x) => `<option value="${esc(x)}" ${x === v ? "selected" : ""} data-notr>${esc(cl(x))}</option>`).join("")}</select></td>`; }).join("")}</tr>`).join("")}
      </tbody></table></details>`;
  }
  function usageHtml() {
    const u = (S.d.usage || {})[S.colour] || (S.d.usage || {})[""];
    if (!u) return "";
    const est = `<span class="pp-est">${Z("估", "ประมาณ")}</span>`;
    const cost = u.cost;
    const rows = (u.colours || []).map((c) => {
      const pc = cost && cost.per_colour ? cost.per_colour.find((x) => x.colour === c.colour && x.material === c.material) : null;
      return `<tr><td class="nowrap"><i class="pp-sw" style="background:${hexOf(c.colour)}"></i><span data-notr>${esc(cl(c.colour) || Z("（款式颜色）", "(สีของแบบ)"))}</span></td>
        <td data-notr>${esc(c.material)}</td><td>${n1(c.grams)} g</td><td>${c.purge_g ? `+ ${n1(c.purge_g)} g ${Z("冲刷", "ล้างสี")}` : ""}</td>${pc ? `<td>฿${n1(pc.cost)}</td>` : ""}</tr>`;
    }).join("");
    return `<div class="pp-use"><b>${Z("每件用料", "วัสดุต่อชิ้น")}${S.colour ? ` · <span data-notr>${esc(cl(S.colour))}</span>` : ""}</b>${u.est ? est : ""}
      ${u.multicolor ? ` <span class="pill warn-pill">${Z("多色 · 需要 AMS", "หลายสี · ต้องมี AMS")}</span>` : ""}
      <table>${rows}</table>
      <div>${Z("合计", "รวม")} <b>${n1(u.grams)} g</b>${u.purge_g ? `（${Z("含换色冲刷", "รวมล้างสี")} ${n1(u.purge_g)} g${u.est ? est : ""}）` : ""} · ${Z("时长", "เวลา")} <b>${n1(u.hours)} h</b>${u.multicolor ? ` <span class="muted">${Z("（含换色时间）", "(รวมเวลาเปลี่ยนสี)")}</span>` : ""}
      ${cost ? ` · ${Z("成本", "ต้นทุน")} <b>฿${n1(cost.total)}</b> <span class="muted">（${Z("材料", "วัสดุ")} ${n1(cost.material)} + ${Z("机时", "เวลาเครื่อง")} ${n1(cost.machine)} + ${Z("包材 / 损耗", "บรรจุภัณฑ์ / สูญเสีย")} ${n1(cost.packaging + cost.failure)}）</span>` : ""}</div>
      ${u.est ? `<div class="small muted">${Z(`「估」= 没有切片结果，按模型体积估克数；换色冲刷按每次 ${S.d.purge.g} g、${S.d.purge.s} 秒估（设置 → 成本与定价）。切片后用切片软件算的准确值。`, `「ประมาณ」= ยังไม่ได้สไลซ์ ประมาณจากปริมาตร; ล้างสีประมาณครั้งละ ${S.d.purge.g} g, ${S.d.purge.s} วินาที`)}</div>` : ""}</div>`;
  }

  // ---------------- 俯视图（canvas） ----------------
  function scaleOf(cv, bed) {
    const w = cv.clientWidth || 400;
    return { k: (w - 20) / bed[0], pad: 10 };
  }
  function draw(pl) {
    const cv = BOX && BOX.querySelector(`[data-cv="${pl.id}"]`);
    if (!cv) return;
    const bed = bedOf(pl.printer);
    const { k, pad } = scaleOf(cv, bed);
    const W = cv.clientWidth || 400, H = Math.round(bed[1] * k + pad * 2);
    const dpr = window.devicePixelRatio || 1;
    cv.style.height = H + "px"; cv.width = W * dpr; cv.height = H * dpr;
    const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const X = (x) => pad + x * k, Y = (y) => pad + (bed[1] - y) * k;
    g.clearRect(0, 0, W, H);
    g.fillStyle = "#eef1f5"; g.fillRect(X(0), Y(bed[1]), bed[0] * k, bed[1] * k);
    g.strokeStyle = "#dde2e9"; g.lineWidth = 1;
    for (let v = 10; v < bed[0]; v += 10) { g.globalAlpha = v % 50 ? 0.5 : 1; g.beginPath(); g.moveTo(X(v), Y(0)); g.lineTo(X(v), Y(bed[1])); g.stroke(); }
    for (let v = 10; v < bed[1]; v += 10) { g.globalAlpha = v % 50 ? 0.5 : 1; g.beginPath(); g.moveTo(X(0), Y(v)); g.lineTo(X(bed[0]), Y(v)); g.stroke(); }
    g.globalAlpha = 1; g.strokeStyle = "#5b6b80"; g.lineWidth = 2; g.strokeRect(X(0), Y(bed[1]), bed[0] * k, bed[1] * k);
    const ex = prModel(pl.printer).exclude;
    if (ex) {          // 拓竹左前角的废料口：不能放零件
      g.fillStyle = "rgba(120,130,145,.35)"; g.fillRect(X(ex[0]), Y(ex[3]), (ex[2] - ex[0]) * k, (ex[3] - ex[1]) * k);
      g.strokeStyle = "#8a97a8"; g.lineWidth = 1; g.strokeRect(X(ex[0]), Y(ex[3]), (ex[2] - ex[0]) * k, (ex[3] - ex[1]) * k);
    }
    g.fillStyle = "#8a97a8"; g.font = "11px sans-serif"; g.fillText(`${bed[0]} × ${bed[1]} mm`, X(0) + 4 + (ex ? (ex[2] - ex[0]) * k : 0), Y(0) - 4);
    const ck = check(pl);
    pl.items.forEach((it, i) => {
      const f = S.fps[it.uid]; if (!f || it.x == null) return;
      const pg = poly(f, it.x, it.y, it.rot), c = ck[it.uid] || {}, bad = c.out || c.overlap.length, on = S.sel.uid === it.uid;
      g.beginPath(); pg.forEach(([x, y], j) => (j ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)))); g.closePath();
      const e = libOf(it.id) || {};
      g.fillStyle = bad ? "rgba(229,57,53,.45)" : (e.multicolor && it.part == null ? "rgba(140,120,220,.55)" : hexOf(slotColour(pl, it.slot)));
      g.globalAlpha = bad ? 1 : 0.85; g.fill(); g.globalAlpha = 1;
      g.lineWidth = on ? 3 : 1.5; g.strokeStyle = bad ? "#c62828" : on ? "#1565c0" : "#37474f"; g.stroke();
      g.fillStyle = "#111"; g.font = "bold 12px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
      g.fillStyle = "rgba(255,255,255,.85)"; g.beginPath(); g.arc(X(it.x), Y(it.y), 9, 0, Math.PI * 2); g.fill();
      g.fillStyle = "#111"; g.fillText(String(i + 1), X(it.x), Y(it.y));
      g.textAlign = "start"; g.textBaseline = "alphabetic";
    });
  }
  function hit(pl, mx, my) {
    for (let i = pl.items.length - 1; i >= 0; i--) {
      const it = pl.items[i], f = S.fps[it.uid]; if (!f || it.x == null) continue;
      const pg = poly(f, it.x, it.y, it.rot);
      let inside = false;
      for (let a = 0, b = pg.length - 1; a < pg.length; b = a++) {
        const [xa, ya] = pg[a], [xb, yb] = pg[b];
        if ((ya > my) !== (yb > my) && mx < ((xb - xa) * (my - ya)) / (yb - ya) + xa) inside = !inside;
      }
      if (inside) return it;
    }
    return null;
  }
  function toBed(cv, pl, ev) {
    const bed = bedOf(pl.printer), { k, pad } = scaleOf(cv, bed), r = cv.getBoundingClientRect();
    return [(ev.clientX - r.left - pad) / k, bed[1] - (ev.clientY - r.top - pad) / k];
  }
  function refreshPlate(pl) {          // 拖动时只重画这一盘的图和状态，不重做整个面板
    draw(pl);
    const ck = check(pl), st = BOX.querySelector(`[data-st="${pl.id}"]`);
    if (st) { st.textContent = statusTxt(pl, ck); st.className = "pp-st " + (Object.values(ck).some((x) => x.out || x.overlap.length) ? "bad" : "ok"); }
    BOX.querySelectorAll(`[data-pl="${pl.id}"] .pp-items tr[data-uid]`).forEach((tr) => {
      const c = ck[tr.dataset.uid] || {}; tr.classList.toggle("bad", !!(c.out || (c.overlap || []).length)); tr.classList.toggle("on", tr.dataset.uid === S.sel.uid);
    });
  }
  let DRAG = null;
  function onDown(ev) {
    const cv = ev.target.closest("[data-cv]"); if (!cv || !S) return;
    const pl = plateOf(cv.dataset.cv), [mx, my] = toBed(cv, pl, ev), it = hit(pl, mx, my);
    S.sel = { pl: pl.id, uid: it ? it.uid : null };
    if (it) { DRAG = { cv, pl, it, dx: mx - it.x, dy: my - it.y, moved: false, snap: JSON.stringify(S.plan) }; cv.setPointerCapture(ev.pointerId); cv.style.cursor = "grabbing"; }
    cv.focus();
    refreshPlate(pl);
  }
  function onMove(ev) {
    if (!DRAG) return;
    const [mx, my] = toBed(DRAG.cv, DRAG.pl, ev);
    DRAG.it.x = Math.round((mx - DRAG.dx) * 2) / 2; DRAG.it.y = Math.round((my - DRAG.dy) * 2) / 2; DRAG.moved = true;
    refreshPlate(DRAG.pl);
  }
  function onUp() {
    if (!DRAG) return;
    DRAG.cv.style.cursor = "";
    if (DRAG.moved) {
      DRAG.pl.manual = true; S.dirty = true;
      if (!S.undo.length || S.undo[S.undo.length - 1] !== DRAG.snap) { S.undo.push(DRAG.snap); S.redo = []; }
    }
    DRAG = null;
  }
  function rotSel(a) {
    const pl = plateOf(S.sel.pl), it = pl && pl.items.find((x) => x.uid === S.sel.uid);
    if (!it) { toast(Z("先在图上点一下要转的零件", "คลิกเลือกชิ้นงานบนภาพก่อน"), true); return false; }
    mark();
    it.rot = (((it.rot || 0) + a) % 360 + 360) % 360; pl.manual = true; S.dirty = true; refreshPlate(pl); return true;
  }

  // ---------------- 事件 ----------------
  function wire() {
    if (!BOX || BOX.dataset.ppWired) return;
    BOX.dataset.ppWired = "1";
    BOX.addEventListener("pointerdown", onDown);
    BOX.addEventListener("pointermove", onMove);
    BOX.addEventListener("pointerup", onUp);
    BOX.addEventListener("pointercancel", onUp);
    BOX.addEventListener("wheel", (ev) => {
      if (!ev.shiftKey || !ev.target.closest("[data-cv]") || !S.sel.uid) return;
      ev.preventDefault(); rotSel(ev.deltaY > 0 ? 5 : -5);
    }, { passive: false });
    BOX.addEventListener("keydown", (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && !ev.target.closest("input,select,textarea")) {
        const k = ev.key.toLowerCase();
        if (k === "z" || k === "y") { ev.preventDefault(); undoRedo(k === "z" && !ev.shiftKey); return; }
      }
      const cv = ev.target.closest("[data-cv]"); if (!cv || !S.sel.uid) return;
      const pl = plateOf(cv.dataset.cv), it = pl.items.find((x) => x.uid === S.sel.uid); if (!it) return;
      const mv = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] }[ev.key];
      if (mv) { ev.preventDefault(); if (!ev.repeat) mark(); it.x += mv[0]; it.y += mv[1]; pl.manual = true; S.dirty = true; refreshPlate(pl); }
      else if (ev.key === "r" || ev.key === "R") { ev.preventDefault(); rotSel(90); }
      else if (ev.key === "Delete") { ev.preventDefault(); mark(); pl.items = pl.items.filter((x) => x !== it); S.sel.uid = null; S.dirty = true; render(); }
    });
    BOX.addEventListener("click", async (ev) => {
      const cc = ev.target.closest("[data-pp-col]");
      if (cc) { S.colour = cc.dataset.ppCol; render(); return; }
      const row = ev.target.closest("tr[data-uid]");
      if (row && !ev.target.closest("select")) { S.sel = { pl: row.closest("[data-pl]").dataset.pl, uid: row.dataset.uid }; refreshPlate(plateOf(S.sel.pl)); }
      if (ev.target.closest("[data-pp-dl]") && S.dirty) { ev.preventDefault(); toast(Z("先保存打印方案再下载", "บันทึกแผนการพิมพ์ก่อนดาวน์โหลด"), true); return; }
      const b = ev.target.closest("[data-pp]"); if (!b) return;
      const a = b.dataset.pp, plEl = b.closest("[data-pl]"), pl = plEl ? plateOf(plEl.dataset.pl) : null;
      try {
        if (a === "save") return save(b);
        if (a === "undo" || a === "redo") { await undoRedo(a === "undo"); return; }
        if (a === "from-display") {
          if (S.dirty && !confirm(Z("现在的改动会被替换（可以撤销）。继续？", "การแก้ไขตอนนี้จะถูกแทนที่ (ย้อนได้) ดำเนินการต่อ?"))) return;
          await busy(b, async () => {
            const r = await apiJob(`/api/products/${encodeURIComponent(S.pid)}/print-plan/from-display`, { json: { spec: S.spec } });
            const undo = S.undo.concat([JSON.stringify(S.plan)]);
            load(r, true); S.undo = undo; S.redo = [];
            render();
            toast(Z(`已按组装的零件生成 ${r.plan.plates.length} 盘（草稿），检查后点「保存打印方案」`, `สร้าง ${r.plan.plates.length} ถาดจากการประกอบแล้ว (ร่าง) ตรวจแล้วกดบันทึก`));
          });
          return;
        }
        if (["add-plate", "del-plate", "add-slot", "del-slot", "arrange", "kit", "del-item", "dup"].includes(a)) mark();
        if (a === "add-plate") {
          const base = S.plan.plates[S.plan.plates.length - 1];
          S.plan.plates.push({ id: "p" + Date.now().toString(36).slice(-5), name: "", printer: base.printer, layer_height: base.layer_height, sets: 1,
            slots: [{ slot: 1, material: base.slots[0].material, colour: "" }], items: [], manual: false });
          S.dirty = true; render(); return;
        }
        if (a === "del-plate") { if (!confirm(Z("删掉这一盘？", "ลบถาดนี้?"))) return; S.plan.plates = S.plan.plates.filter((x) => x !== pl); S.dirty = true; render(); return; }
        if (a === "add-slot") { pl.slots.push({ slot: pl.slots.length + 1, material: pl.slots[0].material, colour: "" }); S.dirty = true; render(); return; }
        if (a === "del-slot") {
          const n = +b.closest("tr").dataset.slot;
          pl.slots = pl.slots.filter((s) => s.slot !== n).map((s, i) => ({ ...s, slot: i + 1 }));
          pl.items.forEach((it) => { if (it.slot === n) it.slot = 1; else if (it.slot > n) it.slot -= 1; });
          Object.values(S.plan.schemes || {}).forEach((m) => { const o = { ...m }; Object.keys(m).forEach((k) => delete m[k]); Object.entries(o).forEach(([k, v]) => { const kk = +k; if (kk < n) m[k] = v; else if (kk > n) m[String(kk - 1)] = v; }); });
          S.dirty = true; render(); return;
        }
        if (a === "arrange") { await busy(b, () => arrange(pl)); if (S.kit) delete S.kit[pl.id]; render(); return; }
        if (a === "kit") {
          await busy(b, async () => {
            const r = await apiJob(`/api/products/${encodeURIComponent(S.pid)}/print-plan/kit`, { json: { plate: pl, ai: true } });
            const byUid = Object.fromEntries(r.plate.items.map((x) => [x.uid, x]));
            pl.items.forEach((it) => { const n = byUid[it.uid]; if (n) { it.x = n.x; it.y = n.y; it.rot = n.rot; } });
            Object.entries(r.footprints || {}).forEach(([k, v]) => { S.fps[k] = { ...v, _k: S.fps[k] && S.fps[k]._k }; });
            pl.manual = true; S.dirty = true;
            S.kit = S.kit || {}; S.kit[pl.id] = r;
          });
          render(); return;
        }
        if (a === "rot") { rotSel(+b.dataset.a); return; }
        if (a === "del-item") {
          if (!S.sel.uid || S.sel.pl !== pl.id) { toast(Z("先在图上点一下要删的零件", "คลิกเลือกชิ้นงานที่จะลบก่อน"), true); return; }
          pl.items = pl.items.filter((x) => x.uid !== S.sel.uid); S.sel.uid = null; S.dirty = true; render(); return;
        }
        if (a === "dup") {
          const it = pl.items.find((x) => x.uid === S.sel.uid);
          if (!it || S.sel.pl !== pl.id) { toast(Z("先在图上点一下要复制的零件", "คลิกเลือกชิ้นงานที่จะคัดลอกก่อน"), true); return; }
          const n = Math.max(1, Math.min(50, +(plEl.querySelector("[data-pp-dupn]") || {}).value || 1));
          for (let k = 0; k < n; k++) { const c = { ...it, uid: uid(), x: null, y: null }; pl.items.push(c); S.fps[c.uid] = S.fps[it.uid]; }
          await busy(b, () => (pl.manual ? placeNew(pl) : arrange(pl)));
          S.dirty = true; render(); return;
        }
        if (a === "3d") { await view3d(pl, b); return; }
        if (a === "fill") {
          if (S.dirty) await save();
          await busy(b, async () => {
            const r = await api(`/api/products/${encodeURIComponent(S.pid)}/print-plan/fill`, { json: { spec: S.spec } });
            if (typeof P !== "undefined" && P && P.id === S.pid && r.product) { P.variants = r.product.variants; P.edit_rev = r.product.edit_rev; if (window.renderVariants) renderVariants(); if (window.refreshPricing) refreshPricing(); }
            toast(Z(`已填 ${r.n} 个变体的克数 / 时长`, `ใส่กรัม / เวลาให้ ${r.n} ตัวเลือกแล้ว`));
            if (window.M3) M3.refresh();
          });
          return;
        }
        if (a === "slice" || a === "merge") {
          if (S.dirty) { toast(Z("先保存打印方案", "บันทึกแผนการพิมพ์ก่อน"), true); return; }
          if (a === "merge" && !confirm(S.spec ? Z(`按摆好的位置合并成一个模型，指定给规格「${S.spec}」？这个规格原来的切片文件会退回草稿。`, `รวมเป็นโมเดลเดียวและกำหนดให้แบบ「${S.spec}」?`)
            : Z("按摆好的位置合并成一个模型，设为 3D 模型（只影响打印；展示不变，还是原来的零件）？这个产品已有的切片文件会退回草稿。", "รวมเป็นโมเดลเดียวและตั้งเป็นโมเดล 3D (มีผลกับการพิมพ์เท่านั้น การแสดงผลไม่เปลี่ยน)? ไฟล์สไลซ์เดิมจะกลับเป็นร่าง"))) return;
          await busy(b, async () => {
            const r = await apiJob(`/api/products/${encodeURIComponent(S.pid)}/print-plan/${a}`, { json: { spec: S.spec, plate_id: pl.id, colour: S.colour } });
            if (a === "merge") { toast(Z("已合并", "รวมแล้ว")); window.dispatchEvent(new CustomEvent("model-changed", { detail: S.pid })); }
            else toast(Z("切片完成，已存成切片文件（草稿，复核后生产用）", "สไลซ์เสร็จ บันทึกเป็นไฟล์สไลซ์แล้ว (ร่าง)") + (r.file_id ? ` #${r.file_id}` : ""));
            await mount(BOX, S.pid, S.spec);
            if (window.M3) M3.refresh();
          }, a === "slice" ? TR("busy.slicing") : undefined);
          return;
        }
      } catch (e) { toast(e.message, true); }
    });
    BOX.addEventListener("change", async (ev) => {
      const t = ev.target, plEl = t.closest("[data-pl]"), pl = plEl ? plateOf(plEl.dataset.pl) : null;
      try {
        if ((t.dataset.ppf || t.dataset.pps || t.dataset.ppi || t.dataset.schSlot || (t.dataset.ppAdd !== undefined && t.value))) {
          // 改之前记下（下拉框已经变了：用改之前的方案）
          if (S._pre) { if (!S.undo.length || S.undo[S.undo.length - 1] !== S._pre) { S.undo.push(S._pre); S.redo = []; } }
        }
        if (t.dataset.ppf && pl) {
          pl[t.dataset.ppf] = t.dataset.ppf === "printer" ? t.value : +t.value;
          S.dirty = true; render(); return;
        }
        if (t.dataset.pps && pl) {
          const s = pl.slots.find((x) => x.slot === +t.closest("tr").dataset.slot); s[t.dataset.pps] = t.value; S.dirty = true; render(); return;
        }
        if (t.dataset.ppi && pl) {
          const it = pl.items.find((x) => x.uid === t.closest("tr").dataset.uid);
          if (t.dataset.ppi === "slot") { it.slot = +t.value; S.dirty = true; render(); return; }
          it.orient = t.value; await fpFor([it]); S.dirty = true; render(); return;
        }
        if (t.dataset.ppAdd !== undefined && pl) {
          if (!t.value) return;
          const [id, part] = t.value.split("|"), e = libOf(id);
          const pp = part === "" ? null : +part, src = pp == null ? e : (e.parts || []).find((x) => x.index === pp) || {};
          const it = { uid: uid(), id, part: pp, orient: src.best || "bottom", slot: 1, x: null, y: null, rot: 0 };
          if (e.multicolor && pp == null && e.colors) {      // 涂色 3MF：槽按文件里的颜色
            const used = e.colors.used || [];
            const fl = (e.colors.filaments || []).filter((f) => !used.length || used.includes(f.slot)).slice(0, S.d.slot_max || 4);
            if (fl.length > pl.slots.length) pl.slots = fl.map((f, i) => ({ slot: i + 1, file_slot: f.slot, material: (f.type || pl.slots[0].material || "PLA").toUpperCase(), colour: f.name || "", hex: f.hex }));
          }
          pl.items.push(it); t.value = "";
          await fpFor([it]);
          if (pl.manual) await placeNew(pl); else await arrange(pl);
          S.sel = { pl: pl.id, uid: it.uid }; S.dirty = true; render(); return;
        }
        if (t.dataset.schSlot) {
          const c = t.closest("tr").dataset.sch; S.plan.schemes = S.plan.schemes || {};
          const m = (S.plan.schemes[c] = S.plan.schemes[c] || {});
          if (t.value) m[t.dataset.schSlot] = t.value; else delete m[t.dataset.schSlot];
          S.dirty = true; render(); return;
        }
      } catch (e) { toast(e.message, true); }
    });
    BOX.addEventListener("focusin", (ev) => { if (S && S.plan && ev.target.closest("select,input")) S._pre = JSON.stringify(S.plan); });
    window.addEventListener("resize", () => { if (S && S.plan && BOX && BOX.isConnected) S.plan.plates.forEach(draw); });
  }
  // 手动摆过的盘里新加的零件：找一个空地方放（从左下往右上找，不和别的重叠）
  async function placeNew(pl) {
    await fpFor(pl.items);
    const bed = bedOf(pl.printer);
    for (const it of pl.items.filter((x) => x.x == null)) {
      const f = S.fps[it.uid]; let done = false;
      for (let y = 5 + f.d / 2; y <= bed[1] - f.d / 2 && !done; y += 5) {
        for (let x = 5 + f.w / 2; x <= bed[0] - f.w / 2 && !done; x += 5) {
          it.x = x; it.y = y;
          const c = check(pl)[it.uid];
          if (c && !c.out && !c.overlap.length) done = true;
        }
      }
      if (!done) { it.x = bed[0] + f.w; it.y = f.d / 2; }
    }
  }
  let V3 = null;
  async function view3d(pl, b) {
    const box = BOX.querySelector(`[data-3d="${pl.id}"]`);
    if (!box.classList.contains("hidden")) { box.classList.add("hidden"); if (V3) { try { V3.dispose(); } catch { /* 忽略 */ } V3 = null; } box.innerHTML = ""; return; }
    if (!window.GVIEW) { toast(Z("3D 组件没有加载（刷新页面再试）", "ยังไม่ได้โหลดส่วน 3D (รีเฟรชหน้า)"), true); return; }
    box.classList.remove("hidden");
    await busy(b, async () => {
      const items = pl.items.map((it) => ({ id: it.id, part: it.part, qty: 1, orient: it.orient, x: it.x, y: it.y, rot: it.rot }));
      const bed = bedOf(pl.printer);
      const res = await fetch(`/api/products/${encodeURIComponent(S.pid)}/models/layout-preview`, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items, bed_w: bed[0] }) });
      if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.error || res.statusText); }
      const raw = new Float32Array(await res.arrayBuffer());
      if (V3) { try { V3.dispose(); } catch { /* 忽略 */ } }
      box.innerHTML = "";
      V3 = new window.GVIEW.ModelView(box);
      V3.update({ raw, fitKey: JSON.stringify(items), bed: [bed[0], bed[1]], heightMax: bed[2], count: 1, gap: 6, supports: "none", supportAngle: 30 });
    });
  }

  // v2.53：编辑页打开时不读方案（收起，m3.js 显示一行摘要）；点「查看 / 编辑打印方案」才 open
  async function mountEditor(force) {
    if (typeof P === "undefined" || !P) return;
    const el = document.getElementById("plan-box");
    if (!el) return;
    const same = S && S.pid === P.id && BOX === el && el.childElementCount;
    if (!same || force) { el.innerHTML = ""; el.classList.add("hidden"); if (!same) S = null; }
    if (window.M3) await M3.mount(P.id);
    if (force && window.M3 && M3.state.planOpen) await open(M3.spec);
  }
  async function open(spec) {
    const el = document.getElementById("plan-box");
    if (!el || typeof P === "undefined" || !P) return;
    BOX = el; wire();
    el.classList.remove("hidden");
    if (S && S.pid === P.id) S.sel = null;
    await mount(el, P.id, spec || "");
  }
  function close() {
    const el = document.getElementById("plan-box");
    if (el) { el.classList.add("hidden"); el.innerHTML = ""; }
    if (S) { S.dirty = false; S.plan = null; }
  }
  window.PLAN = { mount: async (el, pid, spec) => { BOX = el; wire(); await mount(el, pid, spec); }, mountEditor, open, close,
    dirty: () => !!(S && S.dirty && S.plan), check, poly, overlap };
  // 编辑页：打开产品 / 换了 3D 模型时刷新
  window.addEventListener("model-changed", (e) => { if (typeof P !== "undefined" && P && e.detail === P.id && window.M3 && M3.state.planOpen) open(M3.spec).catch(() => {}); });
})();
