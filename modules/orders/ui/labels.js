"use strict";
// 订单模块：设置 → 订单与售后 里的两张卡片
//   ① 自制面单模板预览（v2.33）：各家快递的版式预览、测试打印
//   ② 平台面单：自定义加信息（v2.34，modules/orders/waybill）：面单来源、模板（信息区放什么）、实时预览
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);

  async function selfCard(box) {
    let r;
    try { r = await api("/api/label-templates"); } catch (e) { box.innerHTML = `<p class="bad small">${esc(e.message)}</p>`; return; }
    const size = (window.CFG && CFG.label_size) || "100x150";
    box.innerHTML = `<div class="card"><div class="row between wrap"><h3>面单模板预览</h3>
        <label class="small">预览尺寸 <select id="lt-size">${r.sizes.map((s) => `<option value="${s.id}" ${s.id === size ? "selected" : ""}>${esc(s.zh)}</option>`).join("")}</select></label></div>
      <p class="small muted">自己发快递、手工单、私下成交打印「自制面单」时，按订单的「物流」自动选对应快递的版式（在上面的「自制面单模板」里可以固定用一家）。平台订单走平台物流时，快递员认的是平台出的面单，平台单请优先打印平台面单。分拣线路码系统拿不到，用大字邮编代替。</p>
      <div class="lt-grid" id="lt-grid"></div></div>`;
    const draw = () => {
      const sz = $("#lt-size").value;
      $("#lt-grid").innerHTML = r.carriers.map((c) => `<div class="lt-card"><div class="row between"><b data-notr>${esc(c.name)}</b>
          <a class="mini btn" target="_blank" href="/print/label-preview?carrier=${c.id}&size=${sz}">打开 / 测试打印</a></div>
        <div class="lt-fr"><iframe loading="lazy" src="/print/label-preview?carrier=${c.id}&size=${sz}" title="${esc(c.name)}"></iframe></div></div>`).join("");
    };
    $("#lt-size").onchange = draw;
    draw();
  }

  async function waybillCard(box, plat = "") {
    let r;
    try { r = await api("/api/waybill/status"); } catch (e) { box.innerHTML = `<p class="bad small">${esc(e.message)}</p>`; return; }
    const base = r.template, own = plat ? r.by_platform[plat] : null, t = own || base;
    const owner = typeof ME !== "undefined" && ME && ME.role === "owner";
    const L = (x) => esc(TH() ? x.th || x.zh : x.zh);
    const colName = Object.fromEntries(r.cols.map((c) => [c.id, L(c)]));
    // v2.46：编辑哪一套——通用（纸张、版式、裁边…都在这里）或某个平台（只有内容：样式、列、显示哪些信息、字号、文字）
    const tabs = `<div class="seg wb-tabs"><button data-wbplat="" class="${plat ? "" : "on"}">通用</button>${r.platforms.map((x) =>
      `<button data-wbplat="${x.id}" class="${plat === x.id ? "on" : ""}">${esc(x.zh)}${r.by_platform[x.id] ? " ✎" : ""}</button>`).join("")}</div>`;
    const colsRow = (cols) => cols.map((c, i) => `<div class="wb-col" data-col="${c.id}"><label class="wb-opt"><input type="checkbox" ${c.on ? "checked" : ""}> ${colName[c.id]}</label>
      <button class="mini" data-colmv="-1" ${i ? "" : "disabled"}>↑</button><button class="mini" data-colmv="1" ${i < cols.length - 1 ? "" : "disabled"}>↓</button></div>`).join("");
    box.innerHTML = `<div class="card" id="wb-card"><div class="row between wrap"><h3>平台面单：自定义加信息 / 商品清单</h3>
        <label class="wb-opt"><input type="checkbox" id="wb-on" ${base.enabled ? "checked" : ""} ${plat ? "disabled" : ""}> <b>打印平台面单时按这个模板排</b></label></div>
      <p class="small muted">平台面单上的条码、运单号、分拣码、收寄件人是平台和快递定的，不能改；能改的是面单放多大、裁不裁白边，以及在旁边加一块自己的信息（商品清单、拣货、打包核对、防止重复贴）。关掉 = 原样打印平台的 PDF。开之前先点「测试打印」，用快递的扫码枪扫一下面单条码，确认能扫出来。</p>
      ${r.renderer ? "" : '<p class="bad small">缺少 PDF 转图片组件（pypdfium2）：NAS 重启一次容器会自动安装；Windows 重新双击 1_setup.bat。装好之前平台面单照常原样打印。</p>'}
      ${plat ? "" : `<table class="grid small wb-src"><thead><tr><th>面单来源</th><th>状态</th><th>说明</th></tr></thead><tbody>
        ${r.sources.map((s) => `<tr><td data-notr>${L(s)}</td><td>${s.ready ? `<span class="ok">${esc(Z("✓ 可以用", "✓ ใช้ได้"))}</span>` : `<span class="muted">${esc(Z("未接入", "ยังไม่เชื่อมต่อ"))}</span>`}</td>
          <td class="small" data-notr>${esc(TH() ? s.note_th || s.note_zh : s.note_zh)}</td></tr>`).join("")}</tbody></table>`}
      <div class="row gap wrap" style="margin:8px 0"><span class="small muted">编辑哪一套：</span>${tabs}</div>
      ${plat ? `<p class="small"><label class="wb-opt"><input type="checkbox" id="wb-same" ${own ? "" : "checked"}> 和通用模板一样（不单独设）</label>
        <span class="muted">（纸张、版式、裁边、转向所有平台共用，在「通用」里改）</span></p>` : ""}
      <div class="wb-grid"><div class="wb-form ${plat && !own ? "wb-dim" : ""}">
        ${plat ? "" : `<div class="wb-row"><span class="wb-k">版式</span><div>${r.layouts.map((x) => `<label class="wb-opt"><input type="radio" name="wb-layout" value="${x.id}" ${base.layout === x.id ? "checked" : ""}> <span data-notr>${L(x)}</span></label>`).join("")}
          <div class="small muted">接在面单下面时，打印前会检查：哪一单商品多到放不下，会问你这次要不要改成单独打一张（不改设置）。</div></div></div>
        <div class="wb-row"><span class="wb-k">纸张</span><select id="wb-paper" data-notr>${r.papers.map((x) => `<option value="${x.id}" ${base.paper === x.id ? "selected" : ""}>${L(x)}</option>`).join("")}</select></div>
        <div class="wb-row"><span class="wb-k">信息区最少留</span><input id="wb-info" type="number" min="8" max="70" value="${base.info_mm}" style="width:70px"> <span class="small">毫米（「面单下面加信息」用：面单宽度占满纸，剩下的高度都给信息区；面单太长时才缩小面单，给信息区留够这么高）</span></div>`}
        <div class="wb-row"><span class="wb-k">样式</span><div>${r.styles.map((x) => `<label class="wb-opt"><input type="radio" name="wb-style" value="${x.id}" ${t.style === x.id ? "checked" : ""}> <span data-notr>${L(x)}</span></label>`).join("")}</div></div>
        <div class="wb-row wb-tbl ${t.style === "table" ? "" : "hidden"}"><span class="wb-k">清单的列</span><div><div class="wb-cols">${colsRow(t.cols)}</div>
          <label class="wb-opt"><input type="checkbox" id="wb-qc" ${t.qty_circle ? "checked" : ""}> 数量大于 1 画圈（打包时不会看漏）</label>
          <label class="wb-opt">商品名最多 <select id="wb-nl">${[1, 2, 3].map((n) => `<option ${t.name_lines === n ? "selected" : ""}>${n}</option>`).join("")}</select> 行</label>
          <div class="small muted">图片列：热敏纸打照片会糊，一般不开；开了每行高一点。</div></div></div>
        <div class="wb-row"><span class="wb-k">字号</span><input id="wb-font" type="number" min="7" max="14" value="${t.font}" style="width:70px"> <span>pt</span></div>
        <div class="wb-row"><span class="wb-k">显示</span><div class="wb-fields">${r.fields.map((x) => `<label class="wb-opt"><input type="checkbox" value="${x.id}" ${t.fields.includes(x.id) ? "checked" : ""}> <span data-notr>${L(x)}</span></label>`).join("")}</div></div>
        <div class="wb-row"><span class="wb-k">商品排序</span><select id="wb-sort"><option value="loc" ${t.sort === "loc" ? "selected" : ""}>按货位（拣货走一趟）</option><option value="sku" ${t.sort === "sku" ? "selected" : ""}>按 SKU</option></select></div>
        <div class="wb-row"><span class="wb-k">自定义文字</span><input id="wb-text" maxlength="80" value="${esc(t.text)}" placeholder="例如：易碎品 轻拿轻放 / ของเปราะบาง" style="flex:1" data-notr></div>
        ${plat ? "" : `<div class="wb-row"><label class="wb-opt"><input type="checkbox" id="wb-crop" ${base.crop ? "checked" : ""}> 自动裁掉面单的白边（A4 纸上的小面单也能放大）</label></div>
        <div class="wb-row"><label class="wb-opt"><input type="checkbox" id="wb-rot" ${base.rotate ? "checked" : ""}> 面单是横的就转成竖的</label></div>`}
        <div class="row gap wrap" style="margin-top:8px">${owner ? '<button class="primary" id="wb-save">保存</button>' : '<span class="small muted">只有老板能改模板</span>'}
          <a class="btn" id="wb-test" target="_blank" href="/print/waybill-preview">打开预览 / 测试打印</a></div>
      </div><div class="wb-prev"><div class="wb-fr"><iframe id="wb-fr" title="preview"></iframe></div></div></div></div>`;
    const card = $("#wb-card");
    const cols = () => [...card.querySelectorAll(".wb-col")].map((x) => ({ id: x.dataset.col, on: x.querySelector("input").checked }));
    const content = () => ({
      style: (card.querySelector("[name=wb-style]:checked") || {}).value, cols: cols(), qty_circle: $("#wb-qc").checked, name_lines: +$("#wb-nl").value,
      font: +$("#wb-font").value, sort: $("#wb-sort").value, text: $("#wb-text").value,
      fields: [...card.querySelectorAll(".wb-fields input:checked")].map((x) => x.value),
    });
    const cur = () => plat ? content() : ({
      ...content(), enabled: $("#wb-on").checked, layout: (card.querySelector("[name=wb-layout]:checked") || {}).value, paper: $("#wb-paper").value,
      info_mm: +$("#wb-info").value, crop: $("#wb-crop").checked, rotate: $("#wb-rot").checked,
    });
    let timer = 0;
    const draw = () => {
      const same = plat && $("#wb-same").checked;
      const url = `/print/waybill-preview?tpl=${encodeURIComponent(JSON.stringify(same ? {} : cur()))}${plat && !same ? `&platform=${plat}` : ""}`;
      $("#wb-fr").src = url; $("#wb-test").href = url;
      card.querySelector(".wb-tbl").classList.toggle("hidden", (card.querySelector("[name=wb-style]:checked") || {}).value !== "table");
      card.querySelector(".wb-form").classList.toggle("wb-dim", !!same);
    };
    card.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(draw, 350); });
    card.addEventListener("change", () => { clearTimeout(timer); timer = setTimeout(draw, 150); });
    card.addEventListener("click", (e) => {
      const tb = e.target.closest("[data-wbplat]");
      if (tb) return waybillCard(box, tb.dataset.wbplat);
      const mv = e.target.closest("[data-colmv]");
      if (mv) {
        const row = mv.closest(".wb-col"), list = card.querySelector(".wb-cols"), c = cols(), i = c.findIndex((x) => x.id === row.dataset.col), j = i + +mv.dataset.colmv;
        if (j < 0 || j >= c.length) return;
        [c[i], c[j]] = [c[j], c[i]];
        list.innerHTML = colsRow(c);
        draw();
      }
    });
    const sv = $("#wb-save");
    if (sv) sv.onclick = () => busy(sv, async () => {
      const same = plat && $("#wb-same").checked;
      const x = await api(`/api/waybill/template${plat ? `?platform=${plat}` : ""}`, { json: same ? { same: true } : cur() });
      if (plat) toast(same ? Z("已保存：这个平台和通用模板一样", "บันทึกแล้ว: ใช้แบบเดียวกับแบบทั่วไป") : Z("已保存：这个平台用自己的内容", "บันทึกแล้ว: แพลตฟอร์มนี้ใช้แบบของตัวเอง"));
      else toast(x.template.enabled ? Z("已保存：打印平台面单会按这个模板排", "บันทึกแล้ว: พิมพ์ใบปะหน้าแพลตฟอร์มตามแบบนี้") : Z("已保存（没开：平台面单原样打印）", "บันทึกแล้ว (ปิดอยู่: พิมพ์ใบปะหน้าตามต้นฉบับ)"));
      waybillCard(box, plat);
    });
    draw();
  }

  async function settings(box, cat) {
    if (cat !== "orders") return;
    box.innerHTML = '<div id="lt-self"></div><div id="lt-wb"></div>';
    await Promise.all([selfCard($("#lt-self")), waybillCard($("#lt-wb"))]);
  }
  window.MODS = window.MODS || {};
  window.MODS.orders = Object.assign(window.MODS.orders || {}, { settings });
})();
