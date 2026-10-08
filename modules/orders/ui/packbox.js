"use strict";
// 订单模块：纸箱（v2.35，泰国邮政标准纸箱）——订单详情、打包核对页里显示 / 改这单用哪个纸箱。
// 默认按产品自动选（订单里最大的那个），改了就记在订单上；发货出库时库存模块按这个扣纸箱。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  let CAT = null;
  async function load() {
    if (!CAT) { try { CAT = (await api("/api/pack-boxes")).boxes; } catch { CAT = []; } }
    return CAT;
  }
  function html(o, id) {
    const bx = o.box || {}, sug = bx.suggest || "";
    const sugTxt = sug === "none" ? Z("不用纸箱", "ไม่ใช้กล่อง") : sug ? sug : Z("产品没设纸箱", "สินค้ายังไม่ได้ตั้งกล่อง");
    return `<span class="pb-wrap"><b>📦 ${esc(Z("纸箱", "กล่อง"))}</b> <select id="${id}" class="pb-sel" data-oid="${o.id}" data-notr>
      <option value="" ${bx.auto ? "selected" : ""}>${esc(Z("按产品自动", "อัตโนมัติตามสินค้า"))}（${esc(sugTxt)}）</option>
      ${(CAT || []).map((b) => `<option value="${esc(b.code)}" ${!bx.auto && bx.code === b.code ? "selected" : ""}>${esc(TH() ? b.th : b.zh)}</option>`).join("")}
      <option value="none" ${!bx.auto && bx.code === "none" ? "selected" : ""}>${esc(Z("不用纸箱（快递袋等）", "ไม่ใช้กล่อง (ถุงไปรษณีย์ ฯลฯ)"))}</option></select></span>`;
  }
  async function change(sel) {
    const r = await api(`/api/orders/${sel.dataset.oid}/pack-box`, { json: { box: sel.value } });
    toast(Z(`这单用：${r.box.label_zh}`, `ออเดอร์นี้ใช้: ${r.box.label_th}`));
    return r.box;
  }
  document.addEventListener("change", (e) => {
    if (!e.target.classList || !e.target.classList.contains("pb-sel")) return;
    change(e.target).catch((err) => toast(err.message, true));
  });
  window.PACKBOX = { load, html, change };
})();
