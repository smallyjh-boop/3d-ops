"use strict";
// 自动分组面板（v2.53，产品库 / 采集箱 / 候选池共用）：左边一列分组（手机上变成横向一排），点哪个就按哪个筛选，几个分组可以同时选（并起来）。
// 分组怎么分、个数是服务器按资料现算的；这里只负责画出来和点选。
//   GRP.html(spec)        → HTML。spec = { top:[{key,label,n,tone,sub}], sections:[{id,title,help,items:[{key,label,n,tone,raw,indent,sub}],open}], sel:{段落id:key}, views:[{id,name}], viewOn, foot }
//   GRP.bind(box, spec, onChange)   点击：sel 改了就调用 onChange(sel)；「保存为视图」「视图」「清除」由调用方用 data-grp-act 接
//   GRP.match(item, sel)  item.gk（分组键数组）是不是满足所有选中的分组
//   GRP.sels(sel)         选中的键数组
(function () {
  const E = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const sels = (sel) => Object.values(sel || {}).filter(Boolean);
  function match(item, sel) {
    const k = sels(sel);
    if (!k.length) return true;
    const g = item.gk || [];
    if (!item._gs || item._gsn !== g) { item._gs = new Set(g); item._gsn = g; }
    return k.every((x) => item._gs.has(x));
  }
  function chip(it, sec, sel, big) {
    const on = it.key ? sel[sec] === it.key : !sel[sec];
    return `<div class="grp3 ${big ? "grp3-big" : ""} ${it.tone ? "t-" + it.tone : ""} ${on ? "on" : ""} ${it.indent ? "ind" + it.indent : ""}" data-grp-k="${E(sec)}|${E(it.key || "")}" title="${E(it.title || "")}">
      <span class="grp3-l"${it.raw ? " data-notr" : ""}>${E(it.label)}</span><span class="grp3-n">${it.n == null ? "" : it.n}</span></div>`;
  }
  function html(spec) {
    const sel = spec.sel || {};
    let h = `<div class="grp3-top">${(spec.top || []).map((it) => chip(it, "top", sel, true)).join("")}</div>`;
    if (spec.shops && spec.shops.length) h += `<div class="grp3-shops">${spec.shops.map((it) => chip(it, "shop", sel, false)).join("")}</div>`;
    h += (spec.sections || []).map((s) => `<details class="grp3-sec" ${s.open === false ? "" : "open"}><summary>${E(s.title)}${s.help ? `<span class="grp3-help" title="${E(s.help)}">?</span>` : ""}</summary>
      <div class="grp3-items">${s.items.map((it) => chip(it, s.id, sel, false)).join("") || `<span class="small muted">${Z("暂时没有", "ยังไม่มี")}</span>`}${s.foot || ""}</div></details>`).join("");
    h += `<div class="grp3-views">${(spec.views || []).map((v) => `<span class="grp3-view ${spec.viewOn === v.id ? "on" : ""}" data-grp-view="${v.id}"><span data-notr>${E(v.name)}</span><a data-grp-vdel="${v.id}" title="${E(Z("删除视图", "ลบมุมมอง"))}">✕</a></span>`).join("")}</div>
      <div class="grp3-foot">${spec.foot || ""}</div>`;
    return h;
  }
  function bind(box, spec, onChange) {
    box.onclick = (e) => {
      const c = e.target.closest("[data-grp-k]");
      if (!c || !box.contains(c)) return;
      const raw = c.dataset.grpK, ix = raw.indexOf("|"), sec = raw.slice(0, ix), key = raw.slice(ix + 1);
      const sel = spec.sel;
      if (sec === "top" && !key) { delete sel.top; delete sel.shop; }
      else if ((sel[sec] || "") === key) delete sel[sec];
      else sel[sec] = key;
      if (sec === "top") delete sel.shop;
      onChange(sel);
    };
  }
  window.GRP = { html, bind, match, sels };
})();
