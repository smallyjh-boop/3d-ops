"use strict";
// 打印方案 + 切片文件（编辑产品页和「生产 → 打印方案」里都用这个面板）
// 左边实时 3D 预览（改参数马上看到摆放、悬空、支撑示意、一盘排版），右边参数；切片文件可以打开 3D 切片预览。
(function () {
  const H = () => window.OPSH;
  const PATTERNS = ["gyroid", "grid", "cubic", "crosshatch", "rectilinear", "honeycomb", "lightning"];
  const LVL = { error: "❌", warn: "⚠️", info: "💡", ok: "✅" };
  const TH = () => window.I18N && I18N.lang === "th";
  let R = null, PID = null, BOX = null, LIVE = null, DIRTY = false, LIVE_T = null, SPEC = "", FILES_ONLY = false;   // SPEC：看哪个规格（v2.22，规格有自己的模型时）
  const sq = () => (SPEC ? `?spec=${encodeURIComponent(SPEC)}` : "");

  const gv = (fn) => { if (window.GVIEW) fn(window.GVIEW); else window.addEventListener("gview-ready", () => fn(window.GVIEW), { once: true }); };

  // v2.55 filesOnly（或 el 上 data-files-only="1"）：只显示模型文件 + 切片文件（放在统一的打印方案编辑器下面）
  async function mount(el, pid, spec, opts) {
    if (pid !== PID) SPEC = "";
    if (spec !== undefined) SPEC = spec || "";
    BOX = el; PID = pid;
    FILES_ONLY = !!((opts && opts.filesOnly) || (el && el.dataset && el.dataset.filesOnly === "1"));
    if (!pid) { disposeLive(); el.innerHTML = ""; return; }
    el.innerHTML = `<p class="muted small">${TH() ? "กำลังโหลด…" : "读取中…"}</p>`;
    try { R = await api(`/api/products/${encodeURIComponent(pid)}/recipe${sq()}`); SPEC = R.spec || ""; } catch (e) { el.innerHTML = `<p class="bad">${esc(e.message)}</p>`; return; }
    DIRTY = false;
    render();
  }
  function disposeLive() { if (LIVE) { LIVE.dispose(); LIVE = null; } }
  function checksHtml(list) {
    return (list || []).map((c) => `<div class="chk chk-${c.level}">${LVL[c.level] || ""} ${esc(c.zh)}</div>`).join("");
  }
  function orientCards() {
    const os = R.orientations || [];
    if (!os.length) return '<p class="muted small">没有 3D 模型，无法分析方向（上传模型后可以按方案自动切片）。</p>';
    const best = [...os].sort((a, b) => a.score - b.score)[0].key;
    const ai = R.advice && R.advice.orientation ? R.advice.orientation.pick : null;
    return `<div class="orients">${os.map((o) => `<label class="orient ${o.key === R.recipe.orientation ? "on" : ""}">
      <input type="radio" name="rc-orient" value="${o.key}" ${o.key === R.recipe.orientation ? "checked" : ""} hidden>
      <b>${esc(R.orient_zh[o.key] || o.key)}</b>
      <span class="small">尺寸 ${UX.sizeText(o.size_mm, "×")}</span>
      <span class="small">贴平台 ${o.contact_cm2} cm² · 悬空 ${o.overhang_cm2} cm²</span>
      <span class="small">${o.key === best ? '<span class="pill ok-pill">程序推荐</span>' : ""} ${o.key === ai ? '<span class="pill tag-pill">AI 建议</span>' : ""}</span>
    </label>`).join("")}</div>`;
  }
  function matBadge(m, bad) { return m ? `<span class="mat-badge ${bad ? "bad" : ""}" data-notr>${esc(m)}</span>` : ""; }

  function setupRows() {
    const r = R.recipe;
    return R.printers.map((name, i) => {
      const st = (R.setup || [])[i] || {};
      const chosen = (r.filament || {})[name] || "";
      if (st.error) return `<tr><td data-notr>${esc(name)}</td><td colspan="3" class="small muted">${esc(st.error)}</td></tr>`;
      const mm = st.material_match;
      return `<tr><td data-notr>${esc(name)}</td>
        <td><select data-fil="${esc(name)}" data-pi="${(R.printer_idx || [])[i] ?? i}" class="fil-sel" data-notr>
          <option value="">${esc("自动：" + (st.auto ? st.filament : "按材料自动选"))}</option>
          ${chosen ? `<option value="${esc(chosen)}" selected>${esc(chosen)}</option>` : ""}</select></td>
        <td class="small">${(chosen && st.chosen_type) ? matBadge(st.chosen_type, mm === "diff") : st.filament_type ? matBadge(st.filament_type, mm === "diff") : ""} ${mm === "diff" ? '<span class="bad">和产品材料不一致</span>' : ""}
          ${(st.warnings || []).map((w) => `<div class="${w.level === "error" ? "bad" : "warn"}" data-notr>${esc(TH() ? w.th : w.zh)}</div>`).join("")}</td>
        <td class="small nowrap">🔥 ${st.nozzle_temp ?? "-"}°C · ▭ ${st.bed_temp ?? "-"}°C${st.temp_custom ? ' <span class="pill tag-pill">自定</span>' : ""}</td></tr>`;
    }).join("");
  }

  function uploadHtml() {
    return CAN("files.upload") ? `<div class="rc-upload">
        <label class="filebtn primary-file">⬆ 上传电脑上切好的文件（可多选）<input type="file" data-rc="upload" accept=".3mf,.gcode,.gco,.pm5s,.pm5,.pm7,.pm7m,.pm4n,.pm4u,.pm3,.pm3m,.pm3r,.pwmx,.pwma,.pwmb,.pwmo,.pwms,.pws,.pw0,.pwx,.dlp,.dl2p,.pmx2,.pwc,.ctb,.cbddlp,.goo,.prz,.jxs" multiple hidden></label>
        <label class="small">用于<select data-u="printer"><option value="auto">自动识别打印机</option>${R.printers.map((n) => `<option data-notr>${esc(n)}</option>`).join("")}<option value="*">任何打印机</option></select></label>
        <label class="small">一盘<input data-u="per" type="number" min="1" placeholder="自动" style="width:70px">个</label>
        ${/^RESIN/.test(R.material) ? `<label class="small">打印时长<input data-u="hours" type="number" min="0" step="0.1" placeholder="自动读" style="width:80px">小时</label>
        <label class="small">树脂<input data-u="ml" type="number" min="0" step="0.1" placeholder="自动读" style="width:80px">ml</label>
        <div class="small muted">光固化：在 Photon Workshop / Chitubox / Lychee 里切好后上传（M5s 是 .pm5s 文件）。Anycubic 的文件会自动读出打印时长和树脂用量，
          其他格式读不出来时请在这里填（切片软件里能看到）。<b>一盘放几个请一定填</b>（光固化读不出个数）。</div>` :
        `<div class="small muted">Bambu Studio / OrcaSlicer 用「导出切片文件（Export plate sliced file）」得到 .gcode.3mf；Creality Print 导出 .gcode。
          打印机和一盘几个会从文件里自动认出来，认不出时再手动选。上传后是草稿，在 3D 切片预览里检查后复核。</div>`}</div>` : "";
  }
  function render() {
    disposeLive();
    setTimeout(() => {
      const el = BOX && BOX.querySelector(".rc-spm-body");
      if (el && window.SPECMODEL) SPECMODEL.mount(el, PID, { onChange: () => mount(BOX, PID), openRecipe: (sp) => mount(BOX, PID, sp) });
    }, 0);
    const r = R.recipe;
    const tr = R.temp_range[R.material] || [];
    const own = (R.specs || []).filter((x) => x.own);
    const specBar = own.length ? `<div class="rc-specs chips small"><span class="muted">${TH() ? "แบบ" : "规格"}：</span>
        <span class="chip ${!R.spec ? "on" : ""}" data-rc-spec="">${TH() ? "โมเดลหลัก" : "主模型"}${(R.specs || []).some((x) => !x.own) ? ` <span class="muted" data-notr>(${esc((R.specs || []).filter((x) => !x.own).map((x) => x.spec).join("、"))})</span>` : ""}</span>
        ${own.map((x) => `<span class="chip ${R.spec === x.spec ? "on" : ""}" data-rc-spec="${esc(x.spec)}" data-notr>${esc(x.spec)}</span>`).join("")}
        <span class="muted">${TH() ? "แต่ละแบบที่มีโมเดลของตัวเองมีแผนการพิมพ์และไฟล์สไลซ์แยก" : "有自己模型的规格，打印方案和切片文件分开管理"}</span></div>` : "";
    const spmBox = (R.specs || []).length ? `<details class="rc-spm small" ${own.length ? "" : ""}><summary>${TH() ? "แต่ละแบบใช้โมเดลไหน" : "规格用哪个模型"}
        <span class="muted">${own.length ? "" : (TH() ? "(ตอนนี้ทุกแบบใช้โมเดลหลัก)" : "（现在所有规格都用主模型）")}</span></summary><div class="rc-spm-body"></div></details>` : "";
    if (FILES_ONLY) {           // v2.55：参数在上面的打印方案编辑器里改，这里只放模型文件和切片文件
      BOX.innerHTML = spmBox + `<div class="rc rc-files-only">
        <h4>${TH() ? "ไฟล์โมเดล" : "模型文件"}</h4>
        <div class="rc-model">${modelBox()}</div>
        <h4>${TH() ? "ไฟล์สไลซ์" : "切片文件"}${R.spec ? ` <span class="muted small" data-notr>· ${esc(R.spec)}</span>` : ""}</h4>
        <div class="small muted">${TH() ? "สไลซ์ตามแผนการพิมพ์: กด「✂ สไลซ์ถาดนี้」ในแต่ละถาดด้านบน หรืออัปโหลดไฟล์ที่สไลซ์ในคอมพิวเตอร์ ตรวจในตัวอย่าง 3D แล้วยืนยัน → ทดลองพิมพ์" : "按打印方案切片：在上面每一盘点「✂ 按这一盘切片」；或者上传电脑上切好的文件。在 3D 切片预览里检查后复核 → 试打验证。"}</div>
        ${uploadHtml()}
        <div class="rc-files">${R.files.length ? R.files.map(fileCard).join("") : `<p class="muted small">${TH() ? "ยังไม่มีไฟล์สไลซ์" : "还没有切片文件"}</p>`}</div></div>`;
      return;
    }
    BOX.innerHTML = specBar + spmBox + `
    <div class="rc">
      <div class="row between wrap"><h4>打印方案 <span class="muted small">${r.updated_at ? "更新于 " + fmtTime(r.updated_at) + (r.updated_by ? " · " + esc(r.updated_by) : "") : (r.from_ai ? "（根据 AI 打印建议生成的草稿，请确认后保存）" : "（还没保存过）")}</span></h4>
        <div class="lockbar rc-lockbar"></div></div>
      ${R.model_error ? `<p class="bad small">模型读取失败：${esc(R.model_error)}</p>` : ""}
      <div class="rc-edit">
      <div class="rc-mat">
        <label><b>打印材料</b><select data-r="material" class="mat-sel" data-notr>${R.materials.concat(R.materials.includes(R.material) ? [] : [R.material]).map((m) => `<option ${m === R.material ? "selected" : ""}>${esc(m)}</option>`).join("")}</select></label>
        <div class="small">这个产品用什么材料打印。切片会用对应的耗材配置（温度、速度），开始打印前也会和打印机里装的料核对。<span class="rc-mat-note warn"></span>
          ${/^RESIN/.test(R.material) ? '<div class="resin-box small" style="margin-top:6px">🧪 <b>光固化树脂件</b>：下面的支撑、填充、温度等是 FDM 参数，不用管。支撑、摆放、层高在 Photon Workshop / Chitubox 里设置，切好后在最下面「上传电脑上切好的文件」。排产时只会分配给光固化打印机。</div>' : ""}</div>
      </div>
      <div class="small muted">摆放方向（哪一面贴热床）：</div>
      ${orientCards()}
      <div class="rc-top">
        ${R.has_model ? `<div class="rc-live">
          <div class="rc-live-3d"></div>
          <div class="rc-live-bar small"><label>预览打印机<select data-lp data-notr>${R.printers.map((n, i) => `<option value="${i}">${esc(n)}</option>`).join("")}</select></label>
            <span class="lg"><i style="background:#3b82f6"></i>贴热床</span><span class="lg"><i style="background:#e53935"></i>悬空（没加支撑）</span>
            <span class="lg"><i style="background:#fa8c1a"></i>悬空（有支撑）</span><span class="lg"><i style="background:#10b981"></i>支撑示意</span></div>
          <div class="rc-live-info small"></div>
          <div class="small muted">实时预览按当前填写的参数显示（不用保存）。支撑和排版是示意，实际以「切片预览」为准。</div>
        </div>` : ""}
        <div class="rc-form">
          <div class="form4">
            <label>支撑<select data-r="supports">${Object.entries(R.support_zh).map(([k, v]) => `<option value="${k}" ${k === r.supports ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
            <label>支撑角度 °（悬空小于这个角度就加支撑）<input data-r="support_angle" type="number" min="10" max="80" value="${r.support_angle ?? 30}"></label>
            <label class="row" style="align-self:end"><input type="checkbox" data-r="support_build_plate_only" ${r.support_build_plate_only ? "checked" : ""}> 支撑只从热床长（不长在零件上）</label>
            <label>层高 mm<input data-r="layer_height" type="number" step="0.04" min="0.08" max="0.32" value="${r.layer_height}"></label>
            <label>壁数（外墙圈数）<input data-r="walls" type="number" min="1" max="8" value="${r.walls}"></label>
            <label>顶 / 底层数<input data-r="top_bottom" type="number" min="2" max="10" value="${r.top_bottom}"></label>
            <label>填充率 %<input data-r="infill_pct" type="number" min="0" max="100" value="${r.infill_pct}"></label>
            <label>填充图案<select data-r="infill_pattern" data-notr>${PATTERNS.map((p) => `<option ${p === r.infill_pattern ? "selected" : ""}>${p}</option>`).join("")}</select></label>
            <label class="row" style="align-self:end"><input type="checkbox" data-r="brim" ${r.brim ? "checked" : ""}> 帽檐（防翘边、防倒）</label>
            <label>热床板<select data-r="bed_type">${Object.entries(R.bed_types).map(([k, v]) => `<option value="${k}" ${k === r.bed_type ? "selected" : ""}>${esc(v)}</option>`).join("")}</select></label>
            <label>一盘默认放几个<input data-r="per_plate" type="number" min="1" value="${r.per_plate}"></label>
            <label>零件间距 mm<input data-r="gap_mm" type="number" min="2" max="30" value="${r.gap_mm}"></label>
            <label>喷嘴温度 °C（空 = 按耗材配置）<input data-r="nozzle_temp" type="number" min="0" max="320" value="${r.nozzle_temp || ""}" placeholder="${tr.length ? tr[0] + "–" + tr[1] : ""}"></label>
            <label>热床温度 °C（空 = 按耗材配置）<input data-r="bed_temp" type="number" min="0" max="120" value="${r.bed_temp || ""}"></label>
          </div>
          <details class="rc-setup" open><summary class="small"><b>切片配置（每台打印机用哪个耗材配置）</b></summary>
            <table class="tbl small"><thead><tr><th>打印机</th><th>耗材配置</th><th>材料</th><th>温度</th></tr></thead><tbody>${setupRows()}</tbody></table>
            <div class="small muted">一般选「自动」即可（按材料选通用配置）。用了自己在 OrcaSlicer 里调好的耗材配置时，在这里选它。</div>
          </details>
        </div>
      </div>
      <label>给生产员工的注意事项（会显示在生产工单上，例如：取件时小心细的部分、去支撑用斜口钳）<textarea data-r="notes" rows="2" data-notr>${esc(r.notes || "")}</textarea></label>
      </div>
      <div class="row gap wrap"><span class="rc-dirty bad small hidden">● 有修改还没保存</span><span class="small">${esc(R.summary_zh)}</span></div>
      ${R.checks ? `<div class="checks">${checksHtml(R.checks)}</div>` : ""}
      ${R.advice && R.advice.risks && R.advice.risks.length ? `<details class="small"><summary>AI 打印建议里的风险提醒</summary>${R.advice.risks.map((x) => `<div>· ${esc(L(x))}</div>`).join("")}</details>` : ""}

      <h4>模型文件</h4>
      <div class="rc-model">${modelBox()}</div>

      <h4>切片文件</h4>
      <div class="row gap wrap">
        ${R.has_model ? `<label>打印机<select data-s="printer">${R.printers.map((n, i) => `<option value="${(R.printer_idx || [])[i] ?? i}" data-notr>${esc(n)}</option>`).join("")}</select></label>
        <label>一盘几个<input data-s="count" type="number" min="1" value="${r.per_plate}" style="width:80px"></label>
        <button data-rc="slice" class="primary">按方案切片</button>` : '<span class="muted small">没有 3D 模型，可以直接上传电脑上切好的文件 ↓</span>'}
      </div>
      ${uploadHtml()}
      <div class="rc-files">${R.files.length ? R.files.map(fileCard).join("") : '<p class="muted small">还没有切片文件</p>'}</div>
    </div>`;
    lockBox($(".rc-edit", BOX), { id: "recipe", bar: $(".rc-lockbar", BOX), label: "✏ 修改打印方案", keep: "[data-lp]",
      onSave: async () => { await save(null); toast("打印方案已保存。改了方案要重新切片、重新复核"); },
      onCancel: () => { DIRTY = false; render(); } });
    if (!window.GVIEW) gv(() => { if (BOX && R && BOX.isConnected) render(); });
    if (R.has_model && window.GVIEW) {
      gv((G) => {
        const box = $(".rc-live-3d", BOX);
        if (!box) return;
        LIVE = new G.ModelView(box);
        liveUpdate();
      });
    }
  }

  function formState() {
    const o = {};
    $$("[data-r]", BOX).forEach((x) => (o[x.dataset.r] = x.type === "checkbox" ? x.checked : x.value));
    const ch = $('input[name="rc-orient"]:checked', BOX);
    o.orientation = ch ? ch.value : R.recipe.orientation;
    o.filament = {};
    $$("[data-fil]", BOX).forEach((x) => { if (x.value) o.filament[x.dataset.fil] = x.value; });
    return o;
  }
  function liveUpdate() {
    if (!LIVE) return;
    const s = formState();
    const pi = +(($("[data-lp]", BOX) || {}).value || 0);
    const pp = (R.per_printer || [])[pi] || {};
    const bed = pp.bed_mm || [256, 256, 250];
    LIVE.update({
      pid: PID, spec: R.spec || "", ver: (R.model && R.model.uploaded_at) || (R.model && R.model.file), orient: s.orientation, bed: [bed[0], bed[1]], heightMax: bed[2], count: s.per_plate, gap: s.gap_mm, brim: s.brim,
      supports: s.supports, supportAngle: +s.support_angle || 30,
      onInfo: (i) => {
        const el = $(".rc-live-info", BOX);
        if (!el) return;
        if (i.error) { el.innerHTML = `<span class="bad">${esc(i.error)}</span>`; return; }
        const warn = [];
        if (i.tooTall) warn.push(`<span class="bad">模型比这台打印机的打印高度（${bed[2]} mm）还高</span>`);
        if (s.supports === "none" && i.overhang_cm2 > 2) warn.push(`<span class="bad">红色是悬空面（约 ${i.overhang_cm2.toFixed(1)} cm²），不加支撑可能会塌</span>`);
        if (i.contact_cm2 < 1 && !s.brim) warn.push('<span class="warn">贴热床的面积很小，建议开帽檐</span>');
        if (+s.per_plate > i.capacity) warn.push(`<span class="bad">一盘放不下 ${s.per_plate} 个，这台打印机估计最多 ${i.capacity} 个</span>`);
        el.innerHTML = `尺寸 ${UX.sizeText(i.size, "×")} · 贴热床 ${i.contact_cm2.toFixed(1)} cm² · 悬空 ${i.overhang_cm2.toFixed(1)} cm²（按 ${+s.support_angle || 30}°）
          · 这台打印机一盘估计最多 <b>${i.capacity}</b> 个 · 预览 ${i.count} 个${warn.length ? "<br>" + warn.join("<br>") : ""}`;
      },
    });
  }
  function markDirty() {
    DIRTY = true;
    const d = $(".rc-dirty", BOX); if (d) d.classList.remove("hidden");
    const mat = $('[data-r="material"]', BOX);
    const note = $(".rc-mat-note", BOX);
    if (mat && note) note.textContent = mat.value !== R.material ? ` 材料改成 ${mat.value}：保存后产品材料也会改，原来的切片文件不能再用（会提示材料不对），请重新切片。` : "";
    clearTimeout(LIVE_T); LIVE_T = setTimeout(liveUpdate, 120);
  }

  function resinBox(f) {
    const ri = (f.report || {}).resin || {};
    const bits = [ri.layers ? ri.layers + " 层" : "", ri.layer_height_mm ? "层高 " + ri.layer_height_mm + "mm" : "", ri.height_mm ? "高 " + ri.height_mm + "mm" : "",
      ri.exposure_s ? "曝光 " + ri.exposure_s + "s" : "", ri.volume_ml ? ri.volume_ml + " ml" : ""].filter(Boolean).join(" · ");
    return `<div class="fprev resin-box"><div class="small"><b>🧪 光固化文件</b> ${bits ? `<span class="muted">（文件里读到：${esc(bits)}）</span>` : '<span class="warn">文件里没读出数据，请手填</span>'}</div>
      <div class="form3 small">
        <label>一盘几个<input data-rz="per_plate" type="number" min="1" value="${f.per_plate}"></label>
        <label>每盘小时<input data-rz="hours" type="number" min="0" step="0.1" value="${f.hours ?? ""}"></label>
        <label>每盘克数（树脂）<input data-rz="grams" type="number" min="0" step="0.1" value="${f.grams ?? ""}"></label></div>
      <button class="mini" data-rc="rz-save">保存</button>
      <div class="small muted">光固化一盘的时间主要看高度，放满和放一个差不多：尽量一盘放满。打完要清洗 + 二次固化。</div></div>`;
  }
  // v2.32：切片文件是哪个机型的（发到打印机前一定核对机型、喷嘴、热床板，对不上不能发）
  function machineLine(f) {
    const m = f.machine;
    if (!m) return "";
    if (m.need_confirm) {
      return `<div class="chk chk-error">⚠ 认不出这个文件是哪台机型切的${m.profile ? `（文件里写的是「<span data-notr>${esc(m.profile)}</span>」）` : "（文件里没有打印机信息）"}，确认之前不能用来打印。
        ${H().isOwner() ? '<button class="mini" data-rc="confirm-printer">确认机型</button>' : '<span class="small">请老板确认机型</span>'}</div>`;
    }
    return `<div class="small ${m.ok_for.length ? "ok" : "bad"}">🛡 机型：<b data-notr>${esc(m.model)}</b>（${esc(m.source)}）
      ${m.nozzle ? ` · 喷嘴 ${esc(m.nozzle)} mm` : ""}${m.plate ? ` · ${esc(m.plate)}` : ""}
      · ${m.ok_for.length ? `能发到：<span data-notr>${m.ok_for.map(esc).join("、")}</span>` : "设置里没有能用这个文件的打印机（机型 / 喷嘴 / 热床板对不上）"}</div>`;
  }
  function fileCard(f) {
    const rp = f.report || {};
    const p = rp.params || {};
    const st = f.status || "draft";
    const mm = p.material ? (window.GVIEW ? GVIEW.sameMat(p.material, R.material) : (p.material === R.material ? "same" : "diff")) : null;
    return `<details class="fcard fst-${st}" data-fid="${f.id}" ${st === "draft" ? "open" : ""}>
      <summary><span class="pill fpill-${st}">${esc(R.status_zh[st] || st)}</span>
        ${matBadge(p.material || "?", mm === "diff")}
        ${f.printer === "*" ? "<b>任何打印机</b>" : `<b data-notr>${esc(f.printer)}</b>`} · 一盘 ${f.per_plate} 个 · v${f.version || 1}
        ${f.sku ? `· <span class="mono" data-notr>${esc(f.sku)}</span>` : ""}
        <span class="muted small">${f.grams ? H().num(f.grams, 1) + "g" : ""} ${f.hours ? "· " + H().num(f.hours, 2) + "h" : ""}
          ${rp.layers ? "· " + rp.layers + " 层" : ""} ${rp.support_pct != null ? "· 支撑 " + rp.support_pct + "%" : ""}
          ${p.nozzle_temp != null ? `· 🔥${p.nozzle_temp}° ▭${p.bed_temp ?? "-"}°` : ""}</span>
        ${f.active ? "" : '<span class="pill bad-pill">已停用</span>'}</summary>
      <div class="fbody">
        ${machineLine(f)}
        ${mm === "diff" ? `<div class="chk chk-error">❌ 材料不对：这个文件是 ${esc(p.material)}，产品材料是 ${esc(R.material)}</div>` : ""}
        <div class="fgrid">
          ${f.kind === "resin" ? resinBox(f) : `<div class="fprev">
            <button class="primary" data-rc="gv">🔍 3D 切片预览</button>
            <div class="small muted">看每一层的外墙、填充、支撑，确认支撑加对了、摆放没问题</div>
            <div data-prev="${f.id}"><button class="mini" data-rc="prev">第一层排版俯视图</button></div>
          </div>`}
          <div>
            <div class="small">${f.recipe ? esc(recipeLine(f.recipe)) : '<span class="muted">上传的文件（参数以切片软件里的为准）</span>'}</div>
            <div class="small muted" data-notr>${esc(f.filename)} · ${f.source === "recipe" ? "按方案切片" : "上传"} · ${fmtTime(f.created_at)} ${esc(f.username || "")}</div>
            <details class="fparams" ${st === "draft" ? "open" : ""}><summary class="small"><b>切片参数</b>（材料、温度、层高、支撑…）</summary>
              ${window.GVIEW ? GVIEW.paramRows(p, f.recipe) : ""}</details>
            ${rp.outside ? '<div class="chk chk-error">❌ 有零件超出热床</div>' : ""}
            <div class="checks">${checksHtml(f.checks)}</div>
            ${f.ai_review ? `<div class="ai-box"><b>AI 检查：</b>${f.ai_review.ok ? "✅" : "⚠️"} ${esc(L(f.ai_review.summary))}
              ${(f.ai_review.issues || []).map((x) => `<div>· ${esc(L(x))}</div>`).join("")}
              ${(f.ai_review.check_points || []).length ? `<div class="small muted">人工复核时看：${f.ai_review.check_points.map((x) => esc(L(x))).join("；")}</div>` : ""}</div>` : ""}
            ${f.reviewed_at ? `<div class="small ok">✔ ${esc(f.reviewed_by || "")} 复核于 ${fmtTime(f.reviewed_at)}</div>` : ""}
            ${f.verified_at ? `<div class="small ok">✔ ${esc(f.verified_by || "")} 试打合格 ${fmtTime(f.verified_at)}${f.actual_grams ? ` · 实际 ${f.actual_grams}g` : ""}${f.actual_hours ? ` · ${f.actual_hours}h` : ""}</div>` : ""}
            ${f.verify_note ? `<div class="small" data-notr>${esc(f.verify_note)}</div>` : ""}
            ${f.photo ? `<a href="/api/print-files/photo/${esc(f.photo)}" target="_blank" class="small">试打照片</a>` : ""}
            ${f.note ? `<div class="small muted" data-notr>${esc(f.note)}</div>` : ""}
          </div>
        </div>
        ${st === "draft" ? `<div class="review"><b>人工复核</b>（先打开「3D 切片预览」逐层看，再对照上面的切片参数和检查结果，逐项确认）：
          ${R.review_items.map(([k, lab]) => `<label class="row"><input type="checkbox" data-ri="${k}"> ${esc(lab)}${k === "material" && p.material ? `（文件：${esc(p.material)}${p.nozzle_temp != null ? " " + p.nozzle_temp + "°C" : ""}）` : ""}</label>`).join("")}
          <div class="row gap"><button class="primary" data-rc="review">确认复核，可以生产</button><button data-rc="ai">让 AI 检查</button></div></div>` : ""}
        ${st === "reviewed" ? `<div class="review"><b>试打结果</b>（第一次打这个文件后填写）
          <div class="row gap wrap"><label class="small">实际克数<input data-v="actual_grams" type="number" style="width:80px"></label>
            <label class="small">实际时长 h<input data-v="actual_hours" type="number" step="0.1" style="width:80px"></label>
            <label class="small">说明<input data-v="note" style="width:180px" data-notr></label>
            <label class="filebtn mini-file">照片<input type="file" data-v="photo" accept="image/*" capture="environment" hidden></label></div>
          <div class="row gap"><button class="primary" data-rc="verify-ok">✔ 试打合格</button><button class="danger" data-rc="verify-bad">✗ 不合格（退回草稿）</button>
            <button data-rc="ai">让 AI 检查</button></div></div>` : ""}
        <div class="row gap wrap fact">
          <a class="btn mini-btn" href="/api/print-files/${f.id}/download">⬇ 下载</a>
          ${window.TRIAL && TRIAL.can() && f.kind !== "resin" ? `<button class="mini" data-tr-check="${esc(PID)}" data-tr-spec="${esc(f.spec || "")}" data-tr-plate="${esc(f.plate_id || "p1")}" data-tr-file="${f.id}" title="不打印：核对机型 / 喷嘴 / 热床板、克数、零件位置">🔍 检查</button>
            <button class="mini" data-tr-trial="${esc(PID)}" data-tr-spec="${esc(f.spec || "")}" data-tr-plate="${esc(f.plate_id || "p1")}" data-tr-file="${f.id}" data-tr-src="file">🧪 试打</button>` : ""}
          ${CAN("files.upload") ? '<label class="filebtn mini-file" title="上传新版本，旧版本自动停用">替换<input type="file" data-rc="replace" accept=".3mf,.gcode,.gco,.pm5s,.pm5,.pm7,.pwmx,.pwma,.pwmb,.pm3,.pm4n,.ctb,.goo,.prz" hidden></label>' : ""}
          <button class="mini" data-rc="toggle">${f.active ? "停用" : "启用"}</button>
          ${CAN("files.delete") ? '<button class="mini danger" data-rc="del">删除</button>' : ""}
        </div>
      </div></details>`;
  }
  function modelBox() {
    const m = R.model;
    const size = (b) => (b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");
    const up = CAN("files.upload");
    if (!m) {
      return `<div class="row gap wrap"><span class="muted small">这个产品还没有 3D 模型（有模型才能按方案自动切片）。</span>
        ${up ? '<label class="filebtn">⬆ 上传模型（.stl / .3mf）<input type="file" data-rc="model-up" accept=".stl,.3mf" hidden></label>' : ""}
        <button class="primary-lite" data-rc="lib">📚 模型库 / 摆盘</button></div>`;
    }
    const z = m.metrics && m.metrics.size;
    const dims = z ? (Array.isArray(z) ? z : [z.x, z.y, z.z]).map((v) => UX.num(v)).join("×") + " mm" : "";
    return `<div class="fcard rc-mfile"><div class="row gap wrap">
        <b>📦 <span data-notr>${esc(m.orig_name || m.file)}</span></b>
        <span class="small muted">${size(m.size)}${dims ? " · " + dims : ""} · ${fmtTime(m.uploaded_at)}${m.uploaded_by ? " · " + esc(m.uploaded_by) : ""}${m.history ? ` · 旧版本 ${m.history} 个（在「生产 → 文件管理」里）` : ""}</span>
        <span class="fm-acts"><a class="btn mini-btn" href="/api/products/${encodeURIComponent(PID)}/model/download">⬇ 下载</a>
          ${up && CAN("models.change") ? '<label class="filebtn mini-file" title="换成新的模型文件（旧的会保留在旧版本里）">替换<input type="file" data-rc="model-up" accept=".stl,.3mf" hidden></label>' : ""}
          <button class="mini primary-lite" data-rc="lib" title="选哪个文件当 3D 模型、多个组件合并、每个零件单独选摆放方向、预览摆盘">📚 模型库 / 摆盘</button>
          ${CAN("models.delete") ? '<button class="mini danger" data-rc="model-del">删除</button>' : ""}</span></div>
      ${m.parts_of ? `<div class="small">由 <span data-notr>${m.parts_of.map((d) => esc(d.label) + " ×" + d.qty).join("、")}</span> 合并；每个零件的方向已经在模型库里摆好，下面「摆放方向」一般选「原始方向（底面朝下）」。</div>` : ""}
      <div class="small muted">替换模型后，下面已有的切片文件会自动退回「草稿」，需要重新切片或复核。</div></div>`;
  }
  async function modelUpload(input) {
    const f = input.files[0];
    input.value = "";
    if (!f) return;
    if (R.model && !confirm(`用「${f.name}」替换现在的模型？已有的切片文件会退回草稿，需要重新切片或复核。`)) return;
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await busyToast(TR("busy.model_upload"), () => apiJob(`/api/products/${encodeURIComponent(PID)}/model`, { method: "POST", body: fd }));
      toast(r._model_replaced ? `模型已替换${r._files_reset ? `，${r._files_reset} 个切片文件退回草稿` : ""}` : "模型已上传", !!r._files_reset, 8000);
      await mount(BOX, PID);
    } catch (err) { toast(err.message, true); }
  }
  async function replaceSlice(input) {
    const f = input.files[0];
    input.value = "";
    if (!f) return;
    const fid = input.closest("[data-fid]").dataset.fid;
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await api(`/api/print-files/${fid}/replace`, { method: "POST", body: fd });
      toast(`已上传新版本 v${r.version}（旧版本已停用），请检查后复核`, false, 6000);
      await mount(BOX, PID);
      gv((G) => G.openFile(r.id, { material: R.material }));
    } catch (err) { toast(err.message, true); }
  }
  function recipeLine(r) {
    return `${R.orient_zh[r.orientation] || r.orientation} · ${R.support_zh[r.supports] || r.supports}${r.supports !== "none" && r.support_angle ? " " + r.support_angle + "°" : ""} · 层高 ${r.layer_height} · ${r.walls} 层壁 · 填充 ${r.infill_pct}%${r.brim ? " · 帽檐" : ""}${r.bed_type && r.bed_type !== "auto" ? " · " + (R.bed_types[r.bed_type] || r.bed_type) : ""}${r.nozzle_temp ? " · 喷嘴 " + r.nozzle_temp + "°C" : ""}${r.bed_temp ? " · 热床 " + r.bed_temp + "°C" : ""}`;
  }
  function L(x) { return !x ? "" : typeof x === "string" ? x : (window.I18N && I18N.lang === "th" && x.th ? x.th : x.zh || x.th || ""); }

  async function loadFilaments(sel) {
    if (sel.dataset.loaded) return;
    sel.dataset.loaded = "1";
    const mat = ($('[data-r="material"]', BOX) || {}).value || R.material;
    try {
      const d = await api(`/api/products/${encodeURIComponent(PID)}/filaments?printer=${sel.dataset.pi}&material=${encodeURIComponent(mat)}`);
      const cur = sel.value;
      const opts = [`<option value="">${esc("自动：" + (d.auto || "按材料自动选"))}</option>`]
        .concat((d.items || []).map((x) => `<option value="${esc(x.name)}" ${x.name === cur ? "selected" : ""}>${esc(x.name)}${x.user ? " ★" : ""}</option>`));
      if (cur && !(d.items || []).some((x) => x.name === cur)) opts.push(`<option value="${esc(cur)}" selected>${esc(cur)}（不是 ${esc(mat)}？）</option>`);
      sel.innerHTML = opts.join("");
      if (d.error) toast(d.error, true);
    } catch (err) { toast(err.message, true); delete sel.dataset.loaded; }
  }

  async function save(btn) {
    const o = formState();
    o.spec = SPEC;
    const go = async () => { R = await api(`/api/products/${encodeURIComponent(PID)}/recipe${sq()}`, { json: o }); DIRTY = false; render(); };
    if (btn) await busy(btn, go); else await go();
    // 编辑产品页里的「材质」同步（不然再保存产品时会改回去）
    try {
      if (typeof P !== "undefined" && P && P.id === PID) {
        P.material = R.material;
        const el = document.querySelector('[data-f="material"]');
        if (el) el.value = R.material;
      }
    } catch { /* 不在编辑页 */ }
  }

  document.addEventListener("focusin", (e) => { if (BOX && BOX.contains(e.target) && e.target.dataset && e.target.dataset.fil != null) loadFilaments(e.target); });
  document.addEventListener("mousedown", (e) => { if (BOX && BOX.contains(e.target) && e.target.dataset && e.target.dataset.fil != null) loadFilaments(e.target); });
  document.addEventListener("input", (e) => {
    if (!BOX || !BOX.contains(e.target)) return;
    if (e.target.dataset.r != null) markDirty();
  });
  document.addEventListener("change", (e) => {
    if (!BOX || !BOX.contains(e.target)) return;
    if (e.target.name === "rc-orient") {
      $$(".orient", BOX).forEach((o) => o.classList.toggle("on", o.querySelector("input").checked));
      markDirty();
    }
    if (e.target.dataset.r != null || e.target.dataset.fil != null) markDirty();
    if (e.target.dataset.r === "material") $$("[data-fil]", BOX).forEach((x) => { x.value = ""; delete x.dataset.loaded; });
    if (e.target.dataset.lp != null) liveUpdate();
    if (e.target.dataset.rc === "upload") upload(e.target);
    if (e.target.dataset.rc === "model-up") modelUpload(e.target);
    if (e.target.dataset.rc === "replace") replaceSlice(e.target);
  });
  document.addEventListener("click", async (e) => {
    if (!BOX || !BOX.contains(e.target)) return;
    const sp = e.target.closest("[data-rc-spec]");
    if (sp) {
      if (DIRTY && !confirm("打印方案有修改还没保存，切换规格会丢掉修改。继续？")) return;
      mount(BOX, PID, sp.dataset.rcSpec).catch((err) => toast(err.message, true));
      return;
    }
    const b = e.target.closest("[data-rc]");
    if (!b || b.tagName === "INPUT") return;
    const act = b.dataset.rc;
    const card = b.closest("[data-fid]");
    const fid = card && card.dataset.fid;
    try {
      if (act === "save") {
        await save(b);
        toast("打印方案已保存。改了方案要重新切片、重新复核");
      }
      if (act === "slice") {
        const printer = $('[data-s="printer"]', BOX).value, count = $('[data-s="count"]', BOX).value;
        if (DIRTY) { await save(b); toast("已先保存打印方案"); }
        const nf = await busy($('[data-rc="slice"]', BOX) || b, () => apiJob(`/api/products/${encodeURIComponent(PID)}/recipe/slice`, { json: { printer, count, spec: SPEC } }),
          TR("busy.slicing"));
        toast(nf && nf.report && nf.report.note ? nf.report.note + "。请在 3D 切片预览里检查，然后复核" : "切片完成，请在 3D 切片预览里检查支撑和摆放，然后复核", !!(nf && nf.report && nf.report.note), 8000);
        ((nf && nf.warnings) || []).forEach((w) => toast(TH() ? w.th : w.zh, true, 10000));   // 耗材配置和材料不一致已自动换 / 填充图案改了
        await mount(BOX, PID);
        if (nf && nf.id) gv((G) => G.openFile(nf.id, { material: R.material }));
      }
      if (act === "gv") gv((G) => G.openFile(+fid, { material: R.material }));
      if (act === "confirm-printer") {
        const names = [...new Set(((CFG && CFG.printers) || []).map((p) => p.name).filter(Boolean))];
        const m = MODAL.open(`<h3>这个切片文件是给哪台机型的？</h3>
          <p class="small">文件里读不出打印机信息。请打开切片软件确认这个文件是用哪台打印机的配置切的，<b>选错会损坏机器</b>。确认后只能发到这个机型。</p>
          <select id="cp-model" data-notr>${names.map((n) => `<option>${esc(n)}</option>`).join("")}</select>
          <div class="row gap" style="margin-top:10px"><button class="primary" id="cp-ok">确认</button><button data-mclose>取消</button></div>`);
        m.querySelector("#cp-ok").onclick = async () => {
          try {
            await api(`/api/print-files/${fid}/confirm-printer`, { json: { printer: m.querySelector("#cp-model").value } });
            MODAL.close(); toast("已确认机型"); await mount(BOX, PID, SPEC);
          } catch (err) { toast(err.message, true); }
        };
      }
      if (act === "rz-save") {
        const body = {};
        card.querySelectorAll("[data-rz]").forEach((x) => { if (x.value !== "") body[x.dataset.rz] = +x.value; });
        await api(`/api/print-files/${fid}`, { json: body });
        toast("已保存");
        await mount(BOX, PID);
      }
      if (act === "prev") {
        const f = await api(`/api/print-files/${fid}`);
        $(`[data-prev="${fid}"]`, BOX).innerHTML = (f.report && f.report.preview) || '<span class="muted small">没有预览</span>';
      }
      if (act === "ai") {
        await busy(b, () => apiJob(`/api/print-files/${fid}/ai-review`, { json: {} }));
        await mount(BOX, PID);
      }
      if (act === "review") {
        const items = {};
        card.querySelectorAll("[data-ri]").forEach((x) => (items[x.dataset.ri] = x.checked));
        await api(`/api/print-files/${fid}/review`, { json: { items } });
        toast("已复核，可以用于生产（显示「未试打」）");
        await mount(BOX, PID);
      }
      if (act === "verify-ok" || act === "verify-bad") {
        const fd = new FormData();
        fd.append("ok", act === "verify-ok" ? "1" : "0");
        card.querySelectorAll("[data-v]").forEach((x) => { if (x.type === "file") { if (x.files[0]) fd.append("photo", x.files[0]); } else fd.append(x.dataset.v, x.value); });
        if (act === "verify-bad" && !confirm("标记不合格？这个文件会退回草稿，不能再用于生产。")) return;
        await api(`/api/print-files/${fid}/verify`, { method: "POST", body: fd });
        toast(act === "verify-ok" ? "已标记试打合格" : "已退回草稿");
        await mount(BOX, PID);
      }
      if (act === "toggle") {
        const f = R.files.find((x) => String(x.id) === fid);
        await api(`/api/print-files/${fid}`, { json: { active: f.active ? 0 : 1 } });
        await mount(BOX, PID);
      }
      if (act === "lib") { if (window.FILES && FILES.openLib) FILES.openLib(PID); return; }
      if (act === "model-del") {
        if (!confirmDelete(`产品 ${PID} 的模型文件（会放进「旧版本」，老板还能恢复）`)) return;
        await api(`/api/products/${encodeURIComponent(PID)}/model`, { method: "DELETE" });
        toast("模型已删除"); await mount(BOX, PID);
      }
      if (act === "del") {
        if (!confirmDelete("这个切片文件（只是不想用可以点「停用」，删除后找不回来）")) return;
        await api(`/api/print-files/${fid}`, { method: "DELETE" });
        await mount(BOX, PID);
      }
    } catch (err) { toast(err.message, true); }
  });
  async function upload(input) {
    const files = [...input.files];
    input.value = "";
    if (!files.length) return;
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    fd.append("product_id", PID);
    fd.append("printer", $('[data-u="printer"]', BOX).value || "auto");
    fd.append("per_plate", $('[data-u="per"]', BOX).value || "auto");
    if ($('[data-u="hours"]', BOX)) { fd.append("hours", $('[data-u="hours"]', BOX).value); fd.append("ml", $('[data-u="ml"]', BOX).value); }
    toast("正在上传…", false, 30000);
    try {
      const r = await api("/api/print-files", { method: "POST", body: fd });
      const rs = r.results || [];
      const ok = rs.filter((x) => x.ok), bad = rs.filter((x) => !x.ok);
      toast(`已上传 ${ok.length} 个：${ok.map((x) => `${x.printer === "*" ? "任何打印机" : x.printer} 一盘 ${x.per_plate} 个${x.material ? " " + x.material : ""}`).join("；")}` +
        (bad.length ? `。失败：${bad.map((x) => x.file + "（" + x.error + "）").join("；")}` : "") + "。请在 3D 切片预览里检查后复核", bad.length > 0, 10000);
      await mount(BOX, PID);
      const manual = ok.filter((x) => x.kind === "resin" && ((x.detected || {}).need_manual || (x.detected || {}).per_plate_unknown));
      if (manual.length) toast("光固化文件：有的数据没读出来（打印时长 / 树脂用量 / 一盘几个），请在下面文件卡片里填好再复核", true, 10000);
      if (ok[0] && ok[0].kind !== "resin") gv((G) => G.openFile(ok[0].id, { material: R.material }));
    } catch (err) { toast(err.message, true); }
  }
  // 在模型库里换了 3D 模型 / 合并摆盘后，打印方案马上刷新
  window.addEventListener("model-changed", (e) => { if (BOX && BOX.isConnected && PID && e.detail === PID) mount(BOX, PID).catch(() => {}); });
  window.addEventListener("plan-sliced", (e) => { if (BOX && BOX.isConnected && PID && e.detail === PID) mount(BOX, PID).catch(() => {}); });   // v2.55 编辑器里按盘切片后刷新切片文件
  window.RECIPE = { mount };
})();
