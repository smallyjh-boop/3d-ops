"use strict";
// 订单模块：设置 → 订单与售后 里的「面单模板」卡片（v2.33）：各家快递的版式预览、测试打印。
(function () {
  async function settings(box, cat) {
    if (cat !== "orders") return;
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
  window.MODS = window.MODS || {};
  window.MODS.orders = Object.assign(window.MODS.orders || {}, { settings });
})();
