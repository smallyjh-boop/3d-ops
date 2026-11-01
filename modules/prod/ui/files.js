"use strict";
// 文件管理：所有产品的 3D 模型 + 切片文件，统一查看、预览、下载、替换、删除
(function () {
  const H = () => window.OPSH;
  const Z = (zh, th) => (window.I18N && I18N.lang === "th" ? th : zh);
  let D = null;
  const SEL = new Set();
  const size = (b) => (b == null ? "" : b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");
  const isOwner = () => window.OPSH && OPSH.isOwner();

  function show(name) { if (name === "files") load(); }
  function dims(m) {
    const z = m.metrics && m.metrics.size;
    if (!z) return "";
    const a = Array.isArray(z) ? z : [z.x, z.y, z.z];
    const t = UX.sizeText(a, "×"); return t ? ` · ${t}` : "";
  }

  async function load() {
    const q = encodeURIComponent($("#fm-q").value.trim());
    D = await api(`/api/files?q=${q}&kind=${$("#fm-kind").value}&status=${$("#fm-status").value}&printer=${encodeURIComponent($("#fm-printer").value)}`);
    const pr = $("#fm-printer");
    if (pr.options.length <= 1) pr.innerHTML = '<option value="">全部打印机</option>' + D.printers.map((n) => `<option data-notr>${esc(n)}</option>`).join("");
    const t = D.totals;
    $("#fm-bulk-models").closest("label").classList.toggle("hidden", !CAN("files.upload"));
    $("#fm-bulk-slices").closest("label").classList.toggle("hidden", !CAN("files.upload"));
    $("#fm-sum").innerHTML = `${t.products} 个产品 · 模型文件 <b>${t.models}</b> 个（${size(t.model_bytes)}）· 切片文件 <b>${t.slices}</b> 个（${size(t.slice_bytes)}）`;
    render();
  }
  function sliceRow(f, pid) {
    const st = f.status || "draft";
    return `<div class="fm-slice ${f.active ? "" : "off"}" data-fid="${f.id}" data-pid="${esc(pid)}">
      <span class="pill fpill-${st}">${esc(D.status_zh[st] || st)}</span>
      ${f.material ? `<span class="mat-badge" data-notr>${esc(f.material)}</span>` : ""}
      ${f.printer === "*" ? "<span>任何打印机</span>" : `<span data-notr>${esc(f.printer)}</span>`}${f.spec ? ` · 规格 <b data-notr>${esc(f.spec)}</b>` : ""}${f.plate ? ` · 🧩 <b>${Z("盘", "เพลท")} ${f.plate.no}/${f.plate.total}${f.plate.name ? ` · <span data-notr>${esc(f.plate.name)}</span>` : ""}</b>` : ""} · 一盘 ${f.per_plate} ${f.plate ? Z("套", "ชุด") : "个"} · v${f.version || 1}
      ${f.sku ? `<span class="mono small" data-notr>${esc(f.sku)}</span>` : ""}
      <span class="small muted">${f.grams ? H().num(f.grams, 0) + "g · " : ""}${f.hours ? H().num(f.hours, 1) + "h · " : ""}${size(f.size)} · ${fmtTime(f.created_at).slice(0, 10)}${f.active ? "" : " · 已停用"}</span>
      <span class="fm-acts">
        <button class="mini" data-fa="gv" title="3D 切片预览">🔍</button>
        ${window.TRIAL && TRIAL.can() && f.kind !== "resin" ? `<button class="mini" data-tr-trial="${esc(pid)}" data-tr-spec="${esc(f.spec || "")}" data-tr-plate="${esc(f.plate_id || "p1")}" data-tr-file="${f.id}" data-tr-src="file" title="${Z("用这个文件试打（可以是还没验证的）", "ทดลองพิมพ์ด้วยไฟล์นี้ (ยังไม่ผ่านการตรวจก็ได้)")}">🧪 ${Z("试打", "ทดลอง")}</button>` : ""}
        <a class="btn mini-btn" href="/api/print-files/${f.id}/download" title="下载">⬇</a>
        ${CAN("files.upload") ? '<label class="filebtn mini-file" title="上传新版本替换（旧版本停用）">替换<input type="file" data-fa="rep-slice" accept=".3mf,.gcode,.gco" hidden></label>' : ""}
        <button class="mini" data-fa="toggle">${f.active ? "停用" : "启用"}</button>
        ${CAN("files.delete") ? '<button class="mini danger" data-fa="del-slice">删除</button>' : ""}
      </span>
      ${f.note && /模型已更换/.test(f.note) ? `<div class="small warn" data-notr>${esc(f.note)}</div>` : ""}</div>`;
  }
  function render() {
    const rows = D.rows;
    $("#fm-table tbody").innerHTML = rows.map((r) => {
      const m = r.model;
      return `<tr data-pid="${esc(r.id)}" class="${SEL.has(r.id) ? "sel" : ""}">
        <td><input type="checkbox" data-fsel="${esc(r.id)}" ${SEL.has(r.id) ? "checked" : ""}></td>
        <td>${r.thumb ? `<img class="thumb" src="${esc(r.thumb)}" alt="" loading="lazy">` : ""}</td>
        <td><b data-notr>${esc(r.id)}</b> <span class="mat-badge" data-notr>${esc(r.material)}</span><div data-notr>${esc(r.name_zh)}</div>
          <button class="linkbtn" data-fa="recipe">打印方案 →</button></td>
        <td class="fm-model">${m ? `<div><b>📦 <span data-notr>${esc(m.orig_name || m.file)}</span></b></div>
            <div class="small muted">${size(m.size)} · ${m.uploaded_at ? fmtTime(m.uploaded_at).slice(0, 16) : ""}${m.uploaded_by ? " · " + esc(m.uploaded_by) : ""}
              ${dims(m)}</div>
            <div class="fm-acts"><button class="mini" data-fa="mview">👁 预览</button>
              <a class="btn mini-btn" href="/api/products/${encodeURIComponent(r.id)}/model/download">⬇ 下载</a>
              ${CAN("models.change") ? '<label class="filebtn mini-file">替换<input type="file" data-fa="rep-model" accept=".stl,.3mf" hidden></label>' : ""}
              ${m.history ? `<button class="mini" data-fa="hist">旧版本 ${m.history}</button>` : ""}
              <button class="mini primary-lite" data-fa="lib" title="这个产品的全部模型文件：看尺寸、选哪个当 3D 模型、多个组件合并">📚 模型库 ${r.lib_count || 0}</button>
              ${CAN("models.delete") ? '<button class="mini danger" data-fa="del-model">删除</button>' : ""}</div>`
          : `<span class="muted small">没有模型</span> ${CAN("files.upload") ? '<label class="filebtn mini-file">上传模型<input type="file" data-fa="rep-model" accept=".stl,.3mf" hidden></label>' : ""}
             ${r.lib_count ? `<button class="mini primary-lite" data-fa="lib">📚 模型库 ${r.lib_count}（还没选 3D 模型）</button>` : ""}`}</td>
        <td class="fm-slices">${r.slices.length ? r.slices.map((f) => sliceRow(f, r.id)).join("") : '<span class="muted small">没有切片文件</span>'}
          ${CAN("files.upload") ? '<div><label class="filebtn mini-file" title="上传电脑上切好的文件，打印机和一盘几个自动识别">⬆ 上传切片文件<input type="file" data-fa="up-slice" accept=".3mf,.gcode,.gco,.pm5s,.pm5,.pm7,.pwmx,.pwma,.pwmb,.pm3,.pm4n,.ctb,.goo,.prz" multiple hidden></label></div>' : ""}</td>
      </tr>`;
    }).join("") || '<tr><td colspan="5" class="muted">没有符合条件的产品</td></tr>';
    $("#fm-all").checked = rows.length > 0 && rows.every((r) => SEL.has(r.id));
    $("#fm-selinfo").textContent = SEL.size ? `已勾选 ${SEL.size} 个产品` : "勾选产品后可以一起下载";
    $("#fm-bulk").classList.toggle("on", SEL.size > 0);
  }

  async function upload(url, file, extra) {
    const fd = new FormData();
    fd.append("file", file);
    Object.entries(extra || {}).forEach(([k, v]) => fd.append(k, v));
    return api(url, { method: "POST", body: fd });
  }
  function modelPreview(pid) {
    const el = MODAL.open(`<div class="row between"><h3>模型预览 · <span data-notr>${esc(pid)}</span></h3><button class="mini" data-mclose>关闭</button></div>
      <div id="fm-mv" style="min-height:360px"></div><p class="small muted">按原始方向（底面朝下）显示。摆放方向、支撑等在「打印方案」里设置。</p>`);
    $("#modal-in").classList.add("wide");
    const go = (G) => { const v = new G.ModelView($("#fm-mv", el)); v.update({ pid, orient: "bottom", bed: [256, 256], count: 1, gap: 6, supports: "none", supportAngle: 30 }); };
    if (window.GVIEW) go(window.GVIEW); else window.addEventListener("gview-ready", () => go(window.GVIEW), { once: true });
  }
  // ---------------- 模型库（v2.13） ----------------
  const ORIGIN = { curator: ["选品", "tag-pill"], upload: ["上传", ""], merged: ["合并", "warn-pill"] };
  const mm = (s) => (s ? UX.sizeText(s) : "");
  const estTxt = (i) => {
    if (!i) return "";
    if (i.sliced_result && (i.sliced_result.grams || i.sliced_result.hours)) return `<b>${H().num(i.sliced_result.grams, 0) || "?"} g · ${H().num(i.sliced_result.hours, 1) || "?"} h</b> <span class="small muted">（文件里的切片数据）</span>`;
    const e = i.est || {};
    return `${i.volume_cm3 != null ? H().num(i.volume_cm3, 1) + " cm³" : ""}${e.grams ? ` · 估 ${H().num(e.grams, 0)} g` : ""}${e.hours ? ` · ${H().num(e.hours, 1)} h` : ""}`;
  };
  const fitTxt = (f) => (!f ? "" : f.too_big.length ? `<div class="small bad">放不下：<span data-notr>${f.too_big.map(esc).join("、")}</span></div>`
    : f.ok.length ? '<div class="small ok">所有打印机都放得下</div>' : "");
  let LIB = null, LIBPID = null, LIBVIEW = null;
  const ORI = { bottom: "底面朝下（原始）", top: "倒放（顶面朝下）", front: "前面朝下", back: "背面朝下", left: "左侧朝下", right: "右侧朝下" };
  const LV = { ok: ["ok-pill", "没问题"], warn: ["warn-pill", "注意"], bad: ["bad-pill", "空打风险高"] };
  function oriSel(src) {
    const os = (src && src.orients) || [];
    if (!os.length) return '<span class="muted small">—</span>';
    return `<select data-mlori>${os.map((o) => `<option value="${o.key}" ${o.key === src.best ? "selected" : ""}>${ORI[o.key] || o.key}${o.key === src.best ? "（推荐）" : ""}${o.level === "bad" ? " ⚠" : ""}</option>`).join("")}</select>`;
  }
  // v2.52：风险按编号翻译（以前误用了 L()，表格里显示成「risk.contact_warn」）；编号没有翻译时显示中文原文
  function riskText(r) {
    if (!r.code || !window.TR) return r.text || r.code || "";
    const t = TR(r.code, r.vars || {});
    return t && t !== r.code ? t : (r.text || r.code);
  }
  function riskHtml(src, key) {
    const o = ((src && src.orients) || []).find((x) => x.key === key);
    if (!o) return "";
    const lv = LV[o.level] || LV.ok;
    return `<span class="pill ${lv[0]}">${lv[1]}</span> <span class="small muted">${esc(TR("lib.orient_line", { size: mm(o.size_mm), c: o.contact_cm2, o: o.overhang_cm2 }))}</span>` +
      (o.risks || []).map((r) => `<div class="small ${r.level === "bad" ? "bad" : "warn"}">${r.level === "bad" ? "⚠" : "•"} ${esc(riskText(r))}</div>`).join("");
  }
  function srcOf(id, part) {
    const i = LIB.items.find((y) => y.id === id) || {};
    return part == null ? i.info : ((i.info || {}).parts || [])[part];
  }
  // ---- 预览摆盘：按勾选的零件 / 数量 / 方向排好一盘，在虚拟热床上显示 ----
  let PV = null, PVT = null, PVLAST = null;
  const bedOf = () => { const n = ($("#ml-bed") || {}).value; return (LIB && LIB.beds && LIB.beds[n]) || [256, 256, 250]; };
  function pvSoon() { clearTimeout(PVT); PVT = setTimeout(() => preview(false).catch(() => {}), 500); }
  function pvClose() { PVLAST = null; if (PV) { try { PV.dispose(); } catch { /* 忽略 */ } } PV = null; const b = $("#ml-pv"); if (b) { b.classList.add("hidden"); b.innerHTML = ""; } }
  async function preview(scroll, only) {
    const sel = libSel();
    const items = only || (sel.length ? sel : PVLAST || []);
    PVLAST = items;
    const box = $("#ml-pv");
    if (!box || !$("#ml-body")) return;
    if (!items.length) { if (scroll) toast("先勾选要一起打的文件或组件", true); return; }
    if (!window.GVIEW) throw new Error("3D 预览组件没有加载（刷新页面再试）");
    if (!PV) {
      box.classList.remove("hidden");
      box.innerHTML = `<div class="row between"><b>👁 预览摆盘（按选的方向，蓝 = 贴热床，红 = 悬空没支撑，橙 = 悬空有支撑）</b>
        <span class="row gap"><label class="small"><input type="checkbox" id="ml-pv-sup" checked> 开支撑</label><button class="mini" data-ml="pv-close">收起</button></span></div>
        <div id="ml-pv-3d"></div><div id="ml-pv-info" class="small"></div>`;
      PV = new window.GVIEW.ModelView($("#ml-pv-3d"));
    }
    const res = await fetch(`/api/products/${encodeURIComponent(LIBPID)}/models/layout-preview`, { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ items, bed_w: bedOf()[0] }) });
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.error || res.statusText); }
    const raw = new Float32Array(await res.arrayBuffer());
    const bed = bedOf();
    const sup = $("#ml-pv-sup") && $("#ml-pv-sup").checked;
    PV.update({ raw, fitKey: JSON.stringify(items), bed: [bed[0], bed[1]], heightMax: bed[2], count: 1, gap: 6, supports: sup ? "auto" : "none", supportAngle: 30,
      onInfo: (i) => {
        if (!$("#ml-pv-info")) return;
        if (i.error) { $("#ml-pv-info").innerHTML = `<span class="bad">${esc(i.error)}</span>`; return; }
        const big = i.size[0] > bed[0] || i.size[1] > bed[1];
        $("#ml-pv-info").innerHTML = esc(TR("pv.info", { size: mm(i.size), c: H().num(i.contact_cm2, 1), o: H().num(i.overhang_cm2, 1) })) +
          (big ? ` · <b class="bad">${esc(TR("pv.too_big"))}</b>` : "") +
          (i.tooTall ? ` · <b class="bad">${esc(TR("pv.too_tall"))}</b>` : "") +
          (!big && !i.tooTall ? ` · <span class="ok">${esc(TR("pv.fits"))}</span>` : "");
      } });
    if (scroll) box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  async function openLib(pid) {
    pvClose();
    LIBPID = pid;
    try { LIB = await api(`/api/products/${encodeURIComponent(pid)}/models`); } catch (err) { toast(err.message, true); return; }
    const el = MODAL.open(`<div class="row between"><h3>📚 模型库 · <span data-notr>${esc(pid)}</span></h3><button class="mini" data-mclose>关闭</button></div>
      <div id="ml-body"></div>`);
    $("#modal-in").classList.add("wide", "xwide");
    el.addEventListener("click", libClick);
    el.addEventListener("input", libSum);
    el.addEventListener("change", libChange);
    renderLib();
    const mo = $("#modal");
    if (mo && !mo.dataset.pvHook) { mo.dataset.pvHook = "1"; new MutationObserver(() => { if (PV && !document.getElementById("ml-pv-3d")) pvClose(); }).observe(mo, { childList: true, subtree: true }); }
  }
  function renderLib() {
    if (PV) pvClose();
    if (!$("#ml-body")) return;          // 模型库窗口已经关了
    const L = LIB, up = CAN("files.upload"), chg = up && CAN("models.change");
    const cur = L.current;
    const row = (i) => {
      const inf = i.info || {};
      const can = inf.ok;
      const thumb = inf.thumb ? `<img class="ml-thumb" src="/api/products/${encodeURIComponent(LIBPID)}/models/${i.id}/thumb" alt="">` : `<span class="ml-ext">${esc((i.ext || "").toUpperCase())}</span>`;
      const parts = (inf.parts || []).map((p) => `<tr class="ml-part" data-mid="${i.id}" data-part="${p.index}">
          <td>${can ? `<input type="checkbox" data-mlsel>` : ""}</td><td></td>
          <td class="small">└ <span data-notr>${esc(p.name)}</span></td><td></td>
          <td class="nowrap small">${mm(p.size)}${fitTxt(p.fit)}</td>
          <td class="ml-ori">${can ? oriSel(p) : ""}<div data-mlrisk>${can ? riskHtml(p, p.best) : ""}</div></td><td class="small">${estTxt(p)}</td>
          <td><input type="number" min="1" max="99" value="1" data-mlqty style="width:56px"></td><td></td></tr>`).join("");
      return `<tr data-mid="${i.id}" class="${i.current ? "ml-cur" : ""}">
        <td>${can ? `<input type="checkbox" data-mlsel>` : ""}</td>
        <td>${thumb}</td>
        <td><b data-notr>${esc(i.orig_name)}</b> ${i.current ? '<span class="pill ok-pill">当前 3D 模型</span>' : ""}
          ${ORIGIN[i.origin] ? `<span class="pill ${ORIGIN[i.origin][1]}">${ORIGIN[i.origin][0]}</span>` : ""}${inf.sliced ? ' <span class="pill tag-pill">含切片数据</span>' : ""}
          <div class="small muted">${size(i.bytes)}${inf.triangles ? ` · ${inf.triangles.toLocaleString()} 面` : ""}${(inf.parts || []).length ? ` · <b>${inf.parts.length} 个组件</b>` : ""}${i.added_by ? ` · <span data-notr>${esc(i.added_by)}</span>` : ""}</div>
          ${i.parts_of ? `<div class="small muted">由 <span data-notr>${i.parts_of.map((d) => esc(d.label) + " ×" + d.qty).join("、")}</span> 合并</div>` : ""}
          ${!can ? `<div class="small warn">${esc(inf.reason || "")}</div>` : ""}</td>
        <td class="small" data-notr>${(i.spec_models || []).length ? esc(i.spec_models.join("、")) : (i.current && L.specs.length ? '<span class="muted">主模型</span>' : '<span class="muted">—</span>')}</td>
        <td class="nowrap">${can ? mm(inf.size) : ""}${can ? fitTxt(inf.fit) : ""}</td>
        <td class="ml-ori">${can ? oriSel(inf) : ""}<div data-mlrisk>${can ? riskHtml(inf, inf.best) : ""}</div></td>
        <td>${can ? estTxt(inf) : ""}</td>
        <td>${can ? '<input type="number" min="1" max="99" value="1" data-mlqty style="width:56px">' : ""}</td>
        <td class="nowrap">${can ? '<button class="mini" data-ml="view">👁</button>' : ""}
          ${can && chg ? `<button class="mini primary-lite" data-ml="use">${i.current ? "换方向" : "设为 3D 模型"}</button>` : ""}
          <a class="btn mini-btn" href="/api/products/${encodeURIComponent(LIBPID)}/models/${i.id}/download" title="下载">⬇</a>
          ${CAN("models.delete") && !i.current ? '<button class="mini danger" data-ml="del">删除</button>' : ""}</td></tr>${parts}`;
    };
    $("#ml-body").innerHTML = `
      <p class="small muted">这个产品的全部模型文件（选品来的、自己上传的、合并出来的）都在这里，放在这个产品自己的文件夹里。<b>「3D 模型」</b>是切片、估算克数和时长、3D 预览用的那一个： 单个文件点「设为 3D 模型」；套件 / 多个组件：勾选要一起打的文件或组件、填好每个几件，点下面「合并成一套」，会自动摆在一盘上（不重叠），一起切片。 想自己摆盘：勾选后「下载勾选的文件」，在切片软件里摆好切好，再到文件管理「⬆ 上传切片文件」上传整盘（一盘几个按「套」算）。</p>
      <div class="row gap wrap">${up ? `<label class="filebtn primary-file">⬆ 上传模型文件<input type="file" id="ml-up" multiple accept=".stl,.3mf,.obj,.step,.stp,.zip" hidden></label>` : ""}
        <button class="mini" data-ml="reanalyze">重新分析尺寸</button>
        <span class="small">当前 3D 模型：${cur ? `<b data-notr>${esc(cur.orig_name || cur.file)}</b> ${mm((cur.metrics || {}).size)}` : '<span class="warn">还没选</span>'}</span>
        <span class="small muted">打印机：<span data-notr>${Object.entries(L.beds).map(([n, b]) => `${esc(n)} ${b.join("×")}`).join("；")}</span></span></div>
      <div id="ml-specs" class="card-sub"></div>
      <div style="overflow:auto"><table class="grid small ml-table"><thead><tr><th></th><th></th><th>文件</th><th>对应规格</th><th>尺寸（长×宽×高）</th><th>摆放方向 / 空打风险</th><th>体积 / 估重 / 估时（${esc(L.material)}）</th><th>数量</th><th></th></tr></thead>
        <tbody>${L.items.map(row).join("") || '<tr><td colspan="9" class="muted">模型库是空的，上传模型文件吧</td></tr>'}</tbody></table></div>
      <div class="ml-bar"><span id="ml-sum" class="small muted">勾选文件或组件</span>
        <input id="ml-name" placeholder="合并后的名字（可空）" style="width:180px">
        <label class="small">打印机<select id="ml-bed">${Object.entries(L.beds).map(([n, b]) => `<option value="${esc(n)}" data-notr>${esc(n)}</option>`).join("")}</select></label>
        <button data-ml="pv" title="按勾选的零件、数量和方向排好一盘，用 3D 显示真实摆放效果（蓝 = 贴热床，红 / 橙 = 悬空要支撑）">👁 预览摆盘</button>
        <button data-ml="ai" title="把勾选的零件和摆放方向交给 AI，判断会不会空打 / 打飞，给出支撑、帽檐、速度建议">🤖 AI 检查摆盘</button>
        ${chg ? '<button class="primary" data-ml="merge">合并成一套，设为 3D 模型</button>' : ""}
        <button data-ml="dl">⬇ 下载勾选的文件</button></div>
      <p class="small muted">每个文件 / 组件可以单独选摆放方向（默认是系统算出来最稳的，标「推荐」）；红色 ⚠ 表示这个方向容易打飞、空打，最好换方向或开支撑和帽檐。合并时每个零件按选的方向转好再摆盘。</p>
      <div id="ml-pv" class="ml-view hidden"></div>
      <div id="ml-ai"></div>
      <div id="ml-view" class="ml-view hidden"></div>`;
    libSum();
    if (window.SPECMODEL) SPECMODEL.mount($("#ml-specs"), LIBPID, { recipe: false, onChange: async () => { LIB = await api(`/api/products/${encodeURIComponent(LIBPID)}/models`); renderLib(); } });
  }
  function libSel() {
    return [...document.querySelectorAll("#ml-body [data-mlsel]:checked")].map((c) => {
      const tr = c.closest("tr");
      const o = tr.querySelector("[data-mlori]");
      return { id: tr.dataset.mid, part: tr.dataset.part === undefined ? null : +tr.dataset.part, qty: +(tr.querySelector("[data-mlqty]") || {}).value || 1, orient: o ? o.value : "bottom" };
    });
  }
  function libSum() {
    const s = libSel();
    if (!$("#ml-sum")) return;
    if (!s.length) { $("#ml-sum").textContent = "勾选文件或组件（同一个文件不要同时勾整体和它的组件）"; return; }
    let g = 0, h = 0;
    s.forEach((x) => {
      const i = LIB.items.find((y) => y.id === x.id) || {};
      const src = x.part == null ? i.info : ((i.info || {}).parts || [])[x.part];
      const e = (src && (src.sliced_result || src.est)) || {};
      g += (e.grams || 0) * x.qty; h += (e.hours || 0) * x.qty;
    });
    const n = s.reduce((a, x) => a + x.qty, 0);
    $("#ml-sum").innerHTML = `已选 <b>${n}</b> 件，合计约 <b>${H().num(g, 0)} g · ${H().num(h, 1)} h</b>（估算）`;
  }
  async function libChange(e) {
    const t = e.target;
    if (t.id === "ml-up") {
      if (!t.files.length) return;
      const fd = new FormData();
      [...t.files].forEach((f) => fd.append("files", f));
      try { LIB = await busyToast(TR("busy.model_upload"), () => apiJob(`/api/products/${encodeURIComponent(LIBPID)}/models`, { method: "POST", body: fd })); toast("已上传"); renderLib(); load(); }
      catch (err) { toast(err.message, true); }
      return;
    }
    if (t.dataset.mlspec !== undefined) {
      const id = t.closest("tr").dataset.mid;
      try { LIB = await api(`/api/products/${encodeURIComponent(LIBPID)}/models/${id}/spec`, { json: { spec: t.value } }); toast("已对应规格"); renderLib(); }
      catch (err) { toast(err.message, true); }
      return;
    }
    if (t.dataset.mlori !== undefined) {
      const tr = t.closest("tr");
      tr.querySelector("[data-mlrisk]").innerHTML = riskHtml(srcOf(tr.dataset.mid, tr.dataset.part === undefined ? null : +tr.dataset.part), t.value);
      if (PV) pvSoon();
      return;
    }
    if (t.dataset.mlsel !== undefined || t.dataset.mlqty !== undefined || t.id === "ml-bed" || t.id === "ml-pv-sup") libSum();
    if (PV && (t.dataset.mlsel !== undefined || t.dataset.mlqty !== undefined || t.dataset.mlori !== undefined || t.id === "ml-bed" || t.id === "ml-pv-sup")) pvSoon();
  }
  async function libClick(e) {
    const b = e.target.closest("[data-ml]");
    if (!b) return;
    const a = b.dataset.ml, tr = b.closest("tr"), id = tr && tr.dataset.mid;
    const base = `/api/products/${encodeURIComponent(LIBPID)}/models`;
    try {
      if (a === "view") {
        const i = LIB.items.find((x) => x.id === id);
        const box = $("#ml-view");
        box.classList.remove("hidden");
        box.innerHTML = `<div class="row between"><b data-notr>${esc(i.orig_name)}</b><span id="ml-vmsg" class="small muted">加载中…</span><button class="mini" data-ml="closeview">收起</button></div><div id="ml-canvas" style="height:360px"></div>`;
        box.scrollIntoView({ behavior: "smooth" });
        try {
          if (!window.Model3D) throw new Error("3D 预览组件没有加载（刷新页面再试）");
          const v = new window.Model3D.Viewer($("#ml-canvas"));
          // 先显示精简预览（快），放大看细节时自动换完整模型
          await v.loadFast(`${base}/${id}/preview`, i.ext === "obj" ? { url: `${base}/${id}/stl`, ext: "stl" }
            : { url: `${base}/${id}/download?inline=1`, ext: i.ext === "3mf" ? "3mf" : "stl", fallback: `${base}/${id}/stl` });
          LIBVIEW = v;
          $("#ml-vmsg").textContent = "鼠标拖动旋转，滚轮缩放";
        } catch (err) {
          $("#ml-vmsg").innerHTML = `<span class="bad">预览失败：${esc(err.message || String(err))}</span>`;
          if (i.info && i.info.thumb) $("#ml-canvas").innerHTML = `<img src="${base}/${id}/thumb" style="max-height:340px" alt="">`;
        }
        return;
      }
      if (a === "closeview") { $("#ml-view").classList.add("hidden"); $("#ml-view").innerHTML = ""; LIBVIEW = null; return; }
      if (a === "reanalyze") { await busy(b, async () => { LIB = await apiJob(`${base}/reanalyze`, { json: {} }); }); renderLib(); return; }
      if (a === "use" || a === "merge") {
        const o = tr && tr.querySelector("[data-mlori]");
        const items = a === "use" ? [{ id, part: null, qty: 1, orient: o ? o.value : "bottom" }] : libSel();
        if (!items.length) { toast("先勾选文件或组件", true); return; }
        const risky = items.filter((x) => { const s_ = srcOf(x.id, x.part); const r = ((s_ || {}).orients || []).find((y) => y.key === x.orient); return r && r.level === "bad"; });
        if (risky.length && !confirm(TR("lib.risky_confirm", { n: risky.length }))) return;
        if (a === "merge" && items.length === 1 && items[0].part == null && items[0].qty === 1 && !confirm("只勾了一个文件、数量 1，就直接设为 3D 模型？")) return;
        if (!confirm("换 3D 模型后，这个产品已有的切片文件会退回「草稿」，需要重新切片或复核。继续？")) return;
        await busy(b, async () => {
          LIB = await apiJob(`${base}/current`, { json: { items, name: $("#ml-name").value.trim(), bed_w: bedOf()[0] } });
          toast((LIB.merged ? "已合并成一套并设为 3D 模型" : "已设为 3D 模型") + (LIB.files_reset ? `，${LIB.files_reset} 个切片文件退回草稿` : ""));
        });
        // 已经设好了；下面只是刷新界面，出错不影响结果（记到运行日志，方便排查）
        const quiet = (err2) => { if (window.reportError3D) window.reportError3D(err2, "模型库刷新"); };
        try { renderLib(); } catch (err2) { quiet(err2); }
        load().catch(quiet);
        try { window.dispatchEvent(new CustomEvent("model-changed", { detail: LIBPID })); } catch (err2) { quiet(err2); }
        const cur = LIB.items.find((x) => x.current);     // 设好后马上显示真实摆盘效果
        if (cur && $("#ml-pv")) await preview(true, [{ id: cur.id, part: null, qty: 1, orient: "bottom" }]).catch(quiet);
        return;
      }
      if (a === "ai") {
        const items = libSel();
        if (!items.length) { toast("先勾选要一起打的文件或组件", true); return; }
        await busy(b, async () => {
          $("#ml-ai").innerHTML = '<div class="card small muted">AI 正在分析…</div>';
          try {
            const r = await apiJob(`${base}/ai-check`, { json: { items } });
            const lc = (v) => (v === "高" ? "bad" : v === "中" ? "warn" : "ok"), lt = (v) => ({ 低: "低风险", 中: "中风险", 高: "高风险" }[v] || v || "");
            const th = window.I18N && I18N.lang === "th", T = (x, k) => (th && x[k + "_th"] ? x[k + "_th"] : x[k + "_zh"] || "");
            const ov = r.overall || {};
            $("#ml-ai").innerHTML = `<div class="card ml-aibox"><div class="row between"><b>🤖 AI 摆盘检查 · <span class="${lc(ov.level)}">${esc(lt(ov.level))}</span></b><button class="mini" data-ml="ai-close">收起</button></div>
              <p data-notr>${esc((th && ov.th) || ov.zh || "")}</p>
              ${(r.items || []).map((x) => `<div class="small"><b data-notr>${esc(x.name)}</b> · <span class="${lc(x.level)}">${esc(lt(x.level))}</span> — <span data-notr>${esc(T(x, "risk"))}${T(x, "fix") ? `<br>→ ${esc(T(x, "fix"))}` : ""}</span>${x.suggest_orient && ORI[x.suggest_orient] ? `（建议方向：${ORI[x.suggest_orient]}）` : ""}</div>`).join("")}
              ${T(r, "settings") ? `<p class="small"><b>切片设置建议：</b><span data-notr>${esc(T(r, "settings"))}</span></p>` : ""}
              <p class="small muted">AI 的判断仅供参考，以切片软件里的实际预览为准。</p></div>`;
          } catch (err) { $("#ml-ai").innerHTML = `<div class="card small bad">${esc(err.message)}</div>`; }
        });
        return;
      }
      if (a === "pv") { await busy(b, () => preview(true)); return; }
      if (a === "pv-close") { pvClose(); return; }
      if (a === "ai-close") { $("#ml-ai").innerHTML = ""; return; }
      if (a === "dl") {
        const ids = [...new Set(libSel().map((x) => x.id))];
        if (!ids.length) { toast("先勾选文件", true); return; }
        ids.forEach((x, k) => setTimeout(() => { const l = document.createElement("a"); l.href = `${base}/${x}/download`; l.download = ""; document.body.appendChild(l); l.click(); l.remove(); }, k * 400));
        return;
      }
      if (a === "del") {
        if (!confirmDelete("这个模型文件（会移到旧版本里，还能找回）")) return;
        LIB = await api(`${base}/${id}`, { method: "DELETE" }); toast("已删除"); renderLib(); load();
      }
    } catch (err) { toast(err.message, true); if (!err.status && window.reportError3D) window.reportError3D(err, "模型库 " + a); }
  }

  async function history(pid) {
    const d = await api(`/api/products/${encodeURIComponent(pid)}/model/history`);
    const el = MODAL.open(`<div class="row between"><h3>旧版本模型 · <span data-notr>${esc(pid)}</span></h3><button class="mini" data-mclose>关闭</button></div>
      <p class="small muted">每次替换模型，旧文件都会留在这里（最近 5 个）。恢复后，现在的模型也会进旧版本。</p>
      <table class="grid small"><thead><tr><th>文件</th><th>替换时间</th><th>大小</th><th></th></tr></thead><tbody>
      ${d.history.map((h) => `<tr><td data-notr>${esc(h.orig_name)}</td><td>${esc(h.replaced_at.replace(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2}).*/, "$1-$2-$3 $4:$5"))}</td><td>${size(h.size)}</td>
        <td><a class="btn mini-btn" href="/api/products/${encodeURIComponent(pid)}/model/history/${encodeURIComponent(h.name)}">⬇ 下载</a>
          ${CAN("models.change") ? `<button class="mini" data-restore="${esc(h.name)}">恢复成这个</button>` : ""}</td></tr>`).join("")}</tbody></table>`);
    el.onclick = async (e) => {
      const b = e.target.closest("[data-restore]");
      if (!b) return;
      if (!confirm("恢复这个旧模型？这个产品的切片文件会退回草稿，需要重新切片或复核。")) return;
      try { const r = await api(`/api/products/${encodeURIComponent(pid)}/model/restore`, { json: { name: b.dataset.restore } }); MODAL.close(); toast(`已恢复${r.files_reset ? `，${r.files_reset} 个切片文件退回草稿` : ""}`); load(); }
      catch (err) { toast(err.message, true); }
    };
  }

  // ---------------- 事件 ----------------
  document.addEventListener("click", async (e) => {
    if (!e.target.closest("#tab-files")) return;
    const b = e.target.closest("[data-fa]");
    const cb = e.target.closest("[data-fsel]");
    try {
      if (cb) { cb.checked ? SEL.add(cb.dataset.fsel) : SEL.delete(cb.dataset.fsel); render(); return; }
      if (e.target.id === "fm-zip") { if (SEL.size) location.href = `/api/files/zip?ids=${[...SEL].map(encodeURIComponent).join(",")}`; return; }
      if (e.target.id === "fm-clear") { SEL.clear(); render(); return; }
      if (!b || b.tagName === "INPUT") return;
      const tr = b.closest("[data-pid]");
      const pid = tr && tr.dataset.pid;
      const fid = b.closest("[data-fid]") && b.closest("[data-fid]").dataset.fid;
      const a = b.dataset.fa;
      if (a === "lib") { openLib(pid); return; }
      if (a === "recipe") {
        if (window.PROD_OPEN_RECIPE) return window.PROD_OPEN_RECIPE(pid);
        showTab("recipes"); return;
      }
      if (a === "mview") return modelPreview(pid);
      if (a === "hist") return history(pid);
      if (a === "gv") { if (window.GVIEW) GVIEW.openFile(+fid); return; }
      if (a === "toggle") {
        const f = D.rows.find((r) => r.id === pid).slices.find((x) => String(x.id) === fid);
        await api(`/api/print-files/${fid}`, { json: { active: f.active ? 0 : 1 } }); return load();
      }
      if (a === "del-slice") {
        if (!confirmDelete("这个切片文件（只是不想用可以点「停用」，删除后找不回来）")) return;
        await api(`/api/print-files/${fid}`, { method: "DELETE" }); return load();
      }
      if (a === "del-model") {
        if (!confirmDelete(`产品 ${pid} 的模型文件（会放进「旧版本」，老板还能恢复）`)) return;
        await api(`/api/products/${encodeURIComponent(pid)}/model`, { method: "DELETE" }); return load();
      }
    } catch (err) { toast(err.message, true); }
  });
  document.addEventListener("change", async (e) => {
    if (!e.target.closest("#tab-files")) return;
    const t = e.target;
    try {
      if (t.id === "fm-all") { D.rows.forEach((r) => (t.checked ? SEL.add(r.id) : SEL.delete(r.id))); render(); return; }
      if (["fm-kind", "fm-status", "fm-printer"].includes(t.id)) return load();
      if (t.id === "fm-bulk-slices" || t.dataset.fa === "up-slice") {
        const files = [...t.files]; t.value = "";
        if (!files.length) return;
        const fd = new FormData(); files.forEach((f) => fd.append("files", f));
        if (t.dataset.fa === "up-slice") fd.append("product_id", t.closest("[data-pid]").dataset.pid);
        toast("正在上传…", false, 30000);
        const r = await api("/api/print-files", { method: "POST", body: fd });
        const rs = r.results || [];
        const ok = rs.filter((x) => x.ok), bad = rs.filter((x) => !x.ok);
        toast(`上传 ${ok.length} 个切片文件（${ok.map((x) => `${x.product_id} · ${x.printer === "*" ? "任何打印机" : x.printer}${x.detected && x.detected.spec ? ` · 规格 ${x.detected.spec}` : ""} · 一盘 ${x.per_plate} 个`).join("；")}）` +
          (bad.length ? `，${bad.length} 个失败：${bad.map((x) => x.file + "（" + x.error + "）").join("；")}` : "") + "。都是草稿，检查后复核", bad.length > 0, 12000);
        return load();
      }
      if (t.id === "fm-bulk-models") {
        const files = [...t.files]; t.value = "";
        if (!files.length) return;
        const fd = new FormData(); files.forEach((f) => fd.append("files", f));
        toast("正在上传…", false, 30000);
        const r = await api("/api/files/models", { method: "POST", body: fd });
        const ok = r.results.filter((x) => x.ok), bad = r.results.filter((x) => !x.ok);
        toast(`上传 ${ok.length} 个${bad.length ? `，${bad.length} 个失败：${bad.map((x) => x.file + "（" + x.error + "）").join("；")}` : ""}`, bad.length > 0, 10000);
        return load();
      }
      const a = t.dataset.fa;
      if (a === "rep-model" || a === "rep-slice") {
        const f = t.files[0]; t.value = "";
        if (!f) return;
        const pid = t.closest("[data-pid]").dataset.pid;
        if (a === "rep-model") {
          if (/替换/.test(t.closest("label").textContent) && !confirm(`用「${f.name}」替换产品 ${pid} 现在的 3D 模型？已有的切片文件会退回草稿，需要重新切片或复核（旧模型会进「旧版本」）。`)) return;
          const fd = new FormData(); fd.append("file", f);
          const r = await busyToast(TR("busy.model_upload"), () => apiJob(`/api/products/${encodeURIComponent(pid)}/model`, { method: "POST", body: fd }));
          toast(r._model_replaced ? `模型已替换（旧的在「旧版本」里）${r._files_reset ? `，${r._files_reset} 个切片文件退回草稿，请重新切片或复核` : ""}` : "模型已上传", !!r._files_reset, 8000);
        } else {
          const fid = t.closest("[data-fid]").dataset.fid;
          const r = await upload(`/api/print-files/${fid}/replace`, f);
          toast(`已上传新版本 v${r.version}（旧版本已停用），请检查后复核`, false, 6000);
        }
        return load();
      }
    } catch (err) { toast(err.message, true); }
  });
  let QT = null;
  document.addEventListener("input", (e) => { if (e.target.id === "fm-q") { clearTimeout(QT); QT = setTimeout(() => load().catch((err) => toast(err.message, true)), 300); } });

  window.FILES = { show, load, openLib };
})();
