"use strict";
// 运营改动：运营分析系统写回的标题 / 属性 / 售价 / 上下架记录，可以通过、拒绝、撤回
(function () {
  const F = { title_th: "泰文标题", attributes: "类目属性", price: "售价", active: "上下架" };
  const ST = { applied: ["已生效", "lst-live"], pending: ["待确认", "lst-pending"], rejected: ["已拒绝", "lst-none"], reverted: ["已撤回", "lst-none"] };
  function show(name) { if (name === "opschg") load(); }
  const val = (k, v) => k === "active" ? (v ? "上架" : "下架") : k === "price" ? `฿${v}` : (typeof v === "object" && v !== null ? JSON.stringify(v) : String(v ?? "（空）"));
  function diff(c) {
    return Object.keys(c.after || {}).map((k) => {
      if (k === "attributes") {
        return Object.keys(c.after.attributes).map((a) => `<div><b>${F[k]}</b> <span class="mono" data-notr>${esc(a)}</span>：
          <span class="oc-old" data-notr>${esc(val("", c.before.attributes && c.before.attributes[a]))}</span> → <span class="oc-new" data-notr>${esc(val("", c.after.attributes[a]))}</span></div>`).join("");
      }
      return `<div><b>${F[k] || k}</b>：<span class="oc-old" data-notr>${esc(val(k, (c.before || {})[k]))}</span> → <span class="oc-new" data-notr>${esc(val(k, c.after[k]))}</span></div>`;
    }).join("");
  }
  async function load() {
    const q = new URLSearchParams({ status: $("#oc-status").value, q: $("#oc-q").value.trim() });
    const r = await api("/api/ops/changes?" + q);
    const n = r.counts || {};
    $("#oc-mode").innerHTML = `当前方式：<b>${r.mode === "confirm" ? "只做建议，人工确认后生效" : "自动生效"}</b>（在设置页切换） · 待确认 <b class="${n.pending ? "bad" : ""}">${n.pending || 0}</b> · 已生效 ${n.applied || 0} · 已撤回 ${n.reverted || 0} · 已拒绝 ${n.rejected || 0}`;
    const own = typeof ME !== "undefined" && ME && ME.role === "owner";
    $("#oc-table tbody").innerHTML = r.changes.map((c) => {
      const st = ST[c.status] || [c.status, ""];
      return `<tr><td class="nowrap">${fmtTime(c.ts)}</td>
        <td class="mono" data-notr>${esc(c.product_id)}${c.sku ? `<br>${esc(c.sku)}` : ""}</td>
        <td class="oc-diff">${diff(c)}</td><td data-notr>${esc(c.reason || "")}</td>
        <td class="small muted" data-notr>${esc(c.key_name || "")}${c.source_action_id ? `<br>#${esc(c.source_action_id)}` : ""}</td>
        <td><span class="lst ${st[1]}">${st[0]}</span>${c.decided_by ? `<div class="small muted" data-notr>${esc(c.decided_by)}</div>` : ""}</td>
        <td class="nowrap">${own && c.status === "pending" ? `<button class="mini primary" data-oc="approve" data-id="${c.id}">通过</button><button class="mini" data-oc="reject" data-id="${c.id}">拒绝</button>` : ""}
          ${own && c.status === "applied" ? `<button class="mini" data-oc="revert" data-id="${c.id}">↶ 撤回</button>` : ""}</td></tr>`;
    }).join("") || '<tr><td colspan="7" class="muted">还没有记录</td></tr>';
  }
  $("#oc-reload").addEventListener("click", load);
  $("#oc-status").addEventListener("change", load);
  { let t = null; $("#oc-q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 300); }); }
  $("#oc-table").addEventListener("click", async (e) => {
    const a = e.target.dataset.oc; if (!a) return;
    const msg = { approve: "通过这条修改？会马上写进产品资料。", reject: "拒绝这条修改？", revert: "撤回这条修改？产品会恢复到改之前的值。" }[a];
    if (!confirm(msg)) return;
    try {
      await api(`/api/ops/changes/${e.target.dataset.id}/${a}`, { json: {} });
      toast({ approve: "已通过", reject: "已拒绝", revert: "已撤回" }[a]);
      load();
    } catch (err) { toast(err.message, true); }
  });
  window.OPSCHG = { show, load };
})();
