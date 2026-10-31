"use strict";
// v2.49 统一页面组件（所有页面用同一套）：数字卡片、条形图、走势小图、指标进度条、空状态、「?」说明、页签、筛选条。
// 页面结构统一为：顶部数字卡片 → 图表 → 明细表；没数据一行灰字；说明收进「?」；颜色：ok 绿 / warn 黄 / bad 红 / 默认中性。
// 全部返回 HTML 字符串（和各模块的模板字符串写法一致）；需要 esc() 的文字由这里转义，传进来的 html 参数不转义。
(function () {
  const E = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const TONES = { ok: "ux-ok", warn: "ux-warn", bad: "ux-bad", info: "ux-info", "": "" };

  /** 一组数字卡片：items = [{label, value, sub?, tone?, icon?, go?, help?, spark?:[数字]}] */
  function kpis(items) {
    return `<div class="ux-kpis">${(items || []).filter(Boolean).map((k) => `
      <div class="ux-kpi ${TONES[k.tone || ""] || ""} ${k.go ? "ux-go" : ""}" ${k.go ? `data-ux-go="${E(k.go)}"` : ""}>
        <div class="ux-kpi-l">${k.icon ? `<span class="ux-ic">${k.icon}</span>` : ""}${E(k.label)}${k.help ? help(k.help) : ""}</div>
        <div class="ux-kpi-v">${k.value == null || k.value === "" ? "—" : k.html ? k.value : E(k.value)}</div>
        ${k.sub ? `<div class="ux-kpi-s">${k.subHtml ? k.sub : E(k.sub)}</div>` : ""}
        ${k.spark && k.spark.length > 1 ? spark(k.spark, { tone: k.tone }) : ""}
      </div>`).join("")}</div>`;
  }

  /** 横向条形图：rows = [{label, value, text?, tone?}]，max 自动；opts.unit 显示单位 */
  function bars(rows, opts) {
    opts = opts || {};
    rows = (rows || []).filter((r) => r && r.value != null);
    if (!rows.length) return empty(opts.empty);
    const max = Math.max(...rows.map((r) => Math.abs(+r.value) || 0), 1e-9);
    return `<div class="ux-bars">${rows.map((r) => `<div class="ux-bar-row ${r.go ? "ux-go" : ""}" ${r.go ? `data-ux-go="${E(r.go)}"` : ""}>
        <span class="ux-bar-l" title="${E(r.label)}">${E(r.label)}</span>
        <span class="ux-bar-t"><i class="${TONES[r.tone || ""] || ""}" style="width:${Math.max(2, Math.round(100 * Math.abs(+r.value) / max))}%"></i></span>
        <span class="ux-bar-v">${E(r.text != null ? r.text : r.value)}${opts.unit ? E(opts.unit) : ""}</span></div>`).join("")}</div>`;
  }

  /** 走势小图（SVG 折线 + 面积）：values = [数字…]；opts.h 高度，opts.tone */
  function spark(values, opts) {
    opts = opts || {};
    const v = (values || []).map((x) => +x || 0);
    if (v.length < 2) return "";
    const w = 120, h = opts.h || 28, mn = Math.min(...v), mx = Math.max(...v), d = mx - mn || 1;
    const pts = v.map((y, i) => [Math.round((i / (v.length - 1)) * w * 10) / 10, Math.round((h - 2 - ((y - mn) / d) * (h - 4)) * 10) / 10]);
    const line = pts.map((p) => p.join(",")).join(" ");
    return `<svg class="ux-spark ${TONES[opts.tone || ""] || ""}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
      <polygon points="0,${h} ${line} ${w},${h}"></polygon><polyline points="${line}"></polyline></svg>`;
  }

  /** 柱状图（按天）：points = [{label, value, tone?}]；opts.h 高度 */
  function columns(points, opts) {
    opts = opts || {};
    points = points || [];
    if (!points.length) return empty(opts.empty);
    const max = Math.max(...points.map((p) => Math.abs(+p.value) || 0), 1e-9);
    return `<div class="ux-cols" style="height:${opts.h || 120}px">${points.map((p) => `<div class="ux-col" title="${E(p.label)}：${E(p.text != null ? p.text : p.value)}">
        <i class="${TONES[p.tone || ""] || ""}" style="height:${Math.max(1, Math.round(100 * Math.abs(+p.value) / max))}%"></i></div>`).join("")}</div>
      ${opts.from || opts.to ? `<div class="ux-cols-x"><span>${E(opts.from || "")}</span><span>${E(opts.to || "")}</span></div>` : ""}`;
  }

  /** 指标进度条（有要求线）：{label, value, target, better: "high"|"low", text?, targetText?}；value 为空 = 灰色没数据 */
  function meter(m) {
    const has = m.value != null && m.value !== "" && !isNaN(+m.value);
    const v = has ? +m.value : 0, t = +m.target || 0;
    const top = Math.max(v, t, 1) * 1.15;
    const ok = !has ? null : m.better === "low" ? v <= t : v >= t;
    return `<div class="ux-meter ${has ? (ok ? "ux-ok" : "ux-bad") : "ux-none"}">
      <span class="ux-meter-l">${E(m.label)}</span>
      <span class="ux-meter-t"><i style="width:${has ? Math.min(100, Math.round(100 * v / top)) : 0}%"></i><b style="left:${Math.min(100, Math.round(100 * t / top))}%" title="${E(m.targetText || t)}"></b></span>
      <span class="ux-meter-v">${has ? E(m.text != null ? m.text : v) : "—"}</span>
      <span class="ux-meter-r">${E(m.targetText || "")} ${has ? (ok ? "✓" : "✗") : ""}</span></div>`;
  }

  /** 空状态：一行灰字 */
  function empty(text) {
    return `<p class="ux-empty">${E(text || (window.I18N && I18N.lang === "th" ? "ยังไม่มีข้อมูล" : "暂时没有数据"))}</p>`;
  }

  /** 「?」说明：鼠标放上去 / 点一下显示 */
  function help(text) {
    return ` <span class="ux-help" tabindex="0" data-ux-help="${E(text)}">?</span>`;
  }

  /** 卡片：{title, right?(html), body(html), tone?, id?} */
  function card(c) {
    return `<section class="card ux-card ${TONES[c.tone || ""] || ""}" ${c.id ? `id="${E(c.id)}"` : ""}>
      ${c.title || c.right ? `<div class="ux-card-h"><h3>${E(c.title || "")}${c.help ? help(c.help) : ""}</h3><div class="ux-card-r">${c.right || ""}</div></div>` : ""}
      ${c.body || ""}</section>`;
  }

  /** 页签：items = [[key, 文字, 数量?]]，cur 当前；点击时页面自己监听 [data-ux-tab] */
  function tabs(items, cur, group) {
    return `<div class="ux-tabs" ${group ? `data-ux-group="${E(group)}"` : ""}>${(items || []).map(([k, t, n]) =>
      `<button class="ux-tab ${k === cur ? "on" : ""}" data-ux-tab="${E(k)}">${E(t)}${n != null && n !== "" ? ` <b>${E(n)}</b>` : ""}</button>`).join("")}</div>`;
  }

  /** 状态小圆点 + 文字：tone ok/warn/bad */
  function dot(tone, text) {
    return `<span class="ux-dot ${TONES[tone || ""] || ""}"><i></i>${E(text || "")}</span>`;
  }

  /** 页面头：标题 + 右边（筛选、按钮） */
  function head(title, right, helpText) {
    return `<div class="ux-head"><h2>${E(title)}${helpText ? help(helpText) : ""}</h2><div class="ux-head-r">${right || ""}</div></div>`;
  }

  // 「?」说明：点一下固定显示，再点或点别处关掉
  document.addEventListener("click", (e) => {
    const h = e.target.closest && e.target.closest(".ux-help");
    document.querySelectorAll(".ux-help.open").forEach((x) => { if (x !== h) x.classList.remove("open"); });
    if (h) { e.preventDefault(); e.stopPropagation(); h.classList.toggle("open"); }
  }, true);
  // 卡片 / 条形图上的 data-ux-go：跳到某个页面（goTab），或者 "tab:xxx|key" 交给页面自己处理
  document.addEventListener("click", (e) => {
    const g = e.target.closest && e.target.closest("[data-ux-go]");
    if (!g || e.target.closest("a,button:not([data-ux-go])")) return;
    const v = g.dataset.uxGo;
    if (v.startsWith("tab:") && window.goTab) window.goTab(v.slice(4));
    else document.dispatchEvent(new CustomEvent("ux-go", { detail: v }));
  });

  window.UX = { kpis, bars, spark, columns, meter, empty, help, card, tabs, dot, head, esc: E };
})();
