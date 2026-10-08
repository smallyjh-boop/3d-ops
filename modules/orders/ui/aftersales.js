"use strict";
// 售后：流程阶段、处理期限、凭证照片 / 视频、责任、损失、退货验货（入库 / 报废）
(function () {
  let META = null;
  const H = () => window.OPSH;
  const own = () => H().isOwner();
  const STAGE_CLS = { new: "warn-pill", wait_return: "tag-pill", wait_platform: "tag-pill", received: "warn-pill",
    refunded: "ok-pill", reshipped: "ok-pill", rejected: "", closed: "" };
  // 每个阶段下一步常用的按钮
  const NEXT = { new: ["wait_return", "wait_platform", "refunded", "reshipped", "rejected"], wait_return: ["received", "closed"],
    wait_platform: ["refunded", "rejected", "wait_return"], received: ["refunded", "reshipped", "closed"],
    refunded: ["closed"], reshipped: ["closed"], rejected: ["closed"], closed: ["new"] };
  // 后台返回的 JSON 键会按字母排序，阶段按流程顺序排
  const ST_ORDER = ["new", "wait_return", "wait_platform", "received", "refunded", "reshipped", "rejected", "closed"];
  const KIND_ORDER = ["refund", "partial", "return", "reship", "cod_reject", "other"];
  const RESP_ORDER = ["", "production", "packing", "logistics", "design", "buyer", "platform"];
  const ordered = (obj, order) => [...order.filter((k) => k in obj).map((k) => [k, obj[k]]), ...Object.entries(obj).filter(([k]) => !order.includes(k))];
  const LOSS = { amount: "退款金额", reship_cost: "补发成本", return_shipping: "退回运费", penalty: "平台罚款 / 赔付", scrap_cost: "报废损失" };

  function show(name) { if (name === "aftersales") load(); }
  async function meta() { if (!META) META = await api("/api/aftersales?status=open&days=1"); return META; }

  function dueTxt(a) {
    if (!a.due_at) return "";
    if (a.done) return `<span class="small muted">${fmtTime(a.due_at).slice(5)}</span>`;
    const h = (a.due_at - Date.now() / 1000) / 3600;
    const t = (x) => (x >= 48 ? `${Math.floor(x / 24)} 天` : x >= 1 ? `${Math.floor(x)} 小时` : `${Math.max(1, Math.round(x * 60))} 分钟`);
    return `<span class="cd ${h < 0 ? "cd-over" : h < 24 ? "cd-hot" : "cd-ok"}">${h < 0 ? "超期 " + t(-h) : "剩 " + t(h)}</span>
      <div class="small muted">${fmtTime(a.due_at).slice(5)}</div>`;
  }

  async function load() {
    const m = await meta();
    const fillSel = (sel, obj, first) => {
      const cur = $(sel).value;
      $(sel).innerHTML = `<option value="">${first}</option>` + obj.map(([k, v]) => `<option value="${k || "none"}" ${(k || "none") === cur ? "selected" : ""}>${esc(v)}</option>`).join("");
    };
    fillSel("#as-stage", ordered(m.stages, ST_ORDER), "全部阶段");
    fillSel("#as-kind", ordered(m.kinds, KIND_ORDER), "全部类型");
    fillSel("#as-resp", ordered(m.resp, RESP_ORDER), "全部责任");
    const q = new URLSearchParams({ status: $("#as-status").value, stage: $("#as-stage").value, kind: $("#as-kind").value,
      resp: $("#as-resp").value, due: $("#as-due").value, q: $("#as-q").value.trim() });
    const r = await api("/api/aftersales?" + q);
    META = { ...META, ...r, items: undefined };
    const c = r.counts || {};
    $("#as-sum").innerHTML = `<div class="tiles">
      <div class="tile ${c.open ? "warn" : ""}" data-asf="open"><span>没处理完</span><b>${c.open || 0}</b></div>
      <div class="tile ${c.overdue ? "bad" : ""}" data-asf="overdue"><span>已超期</span><b>${c.overdue || 0}</b></div>
      <div class="tile ${c.due_soon ? "warn" : ""}" data-asf="soon"><span>24 小时内到期</span><b>${c.due_soon || 0}</b></div>
      ${["new", "wait_return", "wait_platform", "received"].map((k) => `<div class="tile" data-asstage="${k}"><span>${esc(r.stages[k])}</span><b>${(c.stages || {})[k] || 0}</b></div>`).join("")}
      ${r.loss_total != null ? `<div class="tile c-cost"><span>当前列表损失合计</span><b>${H().money(r.loss_total) || "฿0"}</b></div>` : ""}</div>`;
    $("#as-table tbody").innerHTML = r.items.map((a) => `<tr class="clickable ${a.overdue ? "row-bad" : ""}" data-asid="${a.id}">
      <td class="nowrap small">${fmtTime(a.created_at)}</td>
      <td><a class="link" data-oid="${a.order_id}"><span class="mono" data-notr>${esc(a.order_no || "")}</span></a>
        <div class="small muted">${esc(H().PLAT[a.platform] || a.platform || "")} <span data-notr>${esc(a.buyer || "")}</span></div></td>
      <td><b>${esc(a.kind_zh)}</b><div class="small">${esc(a.reason || "")}</div></td>
      <td><span class="pill ${STAGE_CLS[a.stage] || ""}">${esc(a.stage_zh)}</span>${a.inspected_at ? '<div class="small ok">已验货</div>' : ""}
        ${a.evidence.length ? `<div class="small muted">📎 ${a.evidence.length}</div>` : ""}</td>
      <td class="nowrap">${dueTxt(a)}</td>
      <td class="small">${esc(a.resp_zh || "")}${a.printer_codes ? `<div class="muted mono" data-notr>${esc(a.printer_codes)}</div>` : ""}</td>
      <td class="c-cost nowrap">${a.loss ? H().money(a.loss) : ""}</td>
      <td class="small" data-notr>${esc(a.note || "")}</td>
      <td class="nowrap"><button class="mini primary-lite" data-asopen="${a.id}">处理</button></td></tr>`).join("")
      || '<tr><td colspan="9" class="muted">没有售后记录</td></tr>';
  }
  ["#as-status", "#as-stage", "#as-kind", "#as-resp", "#as-due"].forEach((k) => $(k).addEventListener("change", load));
  { let t = null; $("#as-q").addEventListener("input", () => { clearTimeout(t); t = setTimeout(load, 300); }); }
  $("#as-reload").addEventListener("click", load);
  $("#as-sum").addEventListener("click", (e) => {
    const t = e.target.closest("[data-asf],[data-asstage]");
    if (!t) return;
    $("#as-stage").value = t.dataset.asstage || "";
    $("#as-status").value = t.dataset.asstage ? "" : "open";
    $("#as-due").value = t.dataset.asf === "overdue" ? "overdue" : t.dataset.asf === "soon" ? "soon" : "";
    load();
  });
  $("#as-table").addEventListener("click", (e) => {
    const a = e.target.closest("[data-oid]");
    if (a) { if (window.OPS) OPS.openOrder(+a.dataset.oid); return; }
    const tr = e.target.closest("[data-asid]");
    if (tr) open(+tr.dataset.asid);
  });

  // ---------- 登记售后 ----------
  async function dialog(order) {
    const m = await meta();
    const sel = (id, obj, cur = "") => `<select id="${id}">${ordered(obj, [...ST_ORDER, ...KIND_ORDER, ...RESP_ORDER]).map(([k, v]) => `<option value="${k}" ${k === cur ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
    const el = MODAL.open(`<div class="row between"><h3>登记售后 · <span class="mono" data-notr>${esc(order.order_no)}</span></h3><button class="mini" data-mclose>关闭</button></div>
      <div class="form3">
        <label>类型${sel("asd-kind", m.kinds)}</label>
        <label>原因<select id="asd-reason">${m.reasons.map((r) => `<option>${esc(r)}</option>`).join("")}</select></label>
        <label>责任方${sel("asd-resp", m.resp)}</label>
        <label>当前阶段${sel("asd-stage", m.stages, "new")}</label>
        <label>处理期限（空 = 自动）<input id="asd-due" type="datetime-local"></label>
        <label>订单状态改为<select id="asd-ostatus"><option value="">不改</option><option value="returned">退货/退款</option><option value="delivery_failed">拒收/派送失败</option><option value="completed">已完成</option></select></label>
        <label class="c-cost">退款金额 ฿<input id="asd-amount" type="number" min="0" step="0.01"></label>
        <label class="c-cost">平台罚款 / 赔付 ฿<input id="asd-penalty" type="number" min="0" step="0.01"></label>
        <label>买家寄回运单号<input id="asd-rtrack" data-notr></label>
      </div>
      <div id="asd-items" class="sd-box hidden"><b>补发哪些商品</b>（会自动生成补发生产任务，补发成本自动估算）
        ${order.items.map((i) => `<label class="row small"><span class="mono" data-notr>${esc(i.sku)}</span> ${H().colorTxt(i.color)} 原 ${i.qty} 个，补发
          <input type="number" min="0" max="${i.qty}" value="0" data-asitem="${i.id}" style="width:64px"> 个</label>`).join("")}</div>
      <label>说明<textarea id="asd-note" rows="2" data-notr></textarea></label>
      <label>凭证照片 / 视频（买家发来的、开箱视频、平台截图，可多选）<input type="file" id="asd-files" multiple accept="image/*,video/*,.pdf"></label>
      <button class="primary" id="asd-save">保存</button>`);
    const kindSel = $("#asd-kind", el), stageSel = $("#asd-stage", el);
    const autoStage = { return: "wait_return", cod_reject: "wait_return", reship: "new", refund: "new", partial: "new", other: "new" };
    kindSel.addEventListener("change", () => {
      $("#asd-items", el).classList.toggle("hidden", kindSel.value !== "reship");
      stageSel.value = autoStage[kindSel.value] || "new";
      if (kindSel.value === "cod_reject") { $("#asd-reason", el).value = "拒收 / 派送失败"; $("#asd-resp", el).value = "buyer"; $("#asd-ostatus", el).value = "delivery_failed"; }
    });
    $("#asd-save", el).onclick = () => busy($("#asd-save", el), async () => {
      const v = (id) => $(id, el).value;
      const r = await api("/api/aftersales", { json: { order_id: order.id, kind: v("#asd-kind"), reason: v("#asd-reason"),
        responsibility: v("#asd-resp"), stage: v("#asd-stage"), due_at: v("#asd-due").replace("T", " "), status: v("#asd-ostatus"),
        amount: v("#asd-amount"), penalty: v("#asd-penalty"), return_tracking: v("#asd-rtrack").trim(), note: v("#asd-note"),
        items: $$("[data-asitem]", el).map((x) => ({ item_id: +x.dataset.asitem, qty: +x.value })) } });
      const files = $("#asd-files", el).files;
      if (files.length) await upload(r.id, files);
      MODAL.close(); toast("已登记售后");
      if (window.OPS) { OPS.openOrder(order.id); OPS.loadOrders(); }
    });
  }

  async function upload(aid, files) {
    const fd = new FormData();
    [...files].forEach((f) => fd.append("files", f));
    return api(`/api/aftersales/${aid}/evidence`, { method: "POST", body: fd });
  }

  // ---------- 售后详情 / 处理 ----------
  async function open(aid) {
    let a, m;
    try { [a, m] = await Promise.all([api(`/api/aftersales/${aid}`), meta()]); } catch (err) { toast(err.message, true); return; }
    const isImg = (f) => /\.(jpe?g|png|webp|gif|heic)$/i.test(f);
    const isVid = (f) => /\.(mp4|mov|webm|m4v)$/i.test(f);
    const url = (f) => `/api/aftersales/${aid}/evidence/${encodeURIComponent(f)}`;
    const sel = (id, obj, cur = "") => `<select id="${id}">${ordered(obj, [...ST_ORDER, ...KIND_ORDER, ...RESP_ORDER]).map(([k, v]) => `<option value="${k}" ${k === (cur || "") ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>`;
    const canInspect = !a.inspected_at && ["wait_return", "received", "new"].includes(a.stage) && ["return", "cod_reject", "partial", "other", "refund"].includes(a.kind);
    const el = MODAL.open(`<div class="row between"><h3>售后 #${a.id} · ${esc(a.kind_zh)} · <a class="link" data-oid="${a.order_id}"><span class="mono" data-notr>${esc(a.order_no || "")}</span></a></h3>
        <button class="mini" data-mclose>关闭</button></div>
      <p class="small">${fmtTime(a.created_at)} 登记（<span data-notr>${esc(a.username || "")}</span>）· 原因：<b>${esc(a.reason || "")}</b>
        · 买家 <span data-notr>${esc(a.buyer || "")}</span>${a.cod ? " · 货到付款" : ""}</p>
      <div class="as-flow">${ordered(m.stages, ST_ORDER).map(([k, v]) => `<span class="as-step ${k === a.stage ? "on" : ""}">${esc(v)}</span>`).join("")}</div>
      <div class="row gap wrap"><span class="small">当前：<span class="pill ${STAGE_CLS[a.stage] || ""}">${esc(a.stage_zh)}</span> ${dueTxt(a)}</span>
        ${(NEXT[a.stage] || []).map((k) => `<button class="mini ${["refunded", "reshipped", "received"].includes(k) ? "primary-lite" : ""}" data-stage="${k}">→ ${esc(m.stages[k])}</button>`).join("")}</div>
      <div class="form3">
        <label>类型${sel("asx-kind", m.kinds, a.kind)}</label>
        <label>原因<select id="asx-reason">${[...new Set([...(m.reasons || []), a.reason || ""])].filter(Boolean).map((r) => `<option ${r === a.reason ? "selected" : ""}>${esc(r)}</option>`).join("")}</select></label>
        <label>处理期限<input id="asx-due" type="datetime-local" value="${a.due_at ? fmtTime(a.due_at).replace(" ", "T") : ""}"></label>
        <label>责任方${sel("asx-resp", m.resp, a.responsibility)}</label>
        <label>经手人<input id="asx-staff" value="${esc(a.staff || "")}" data-notr></label>
        <label>买家寄回运单号<input id="asx-rtrack" value="${esc(a.return_tracking || "")}" data-notr></label>
        <label>打印机（自动）<input id="asx-printers" value="${esc(a.printer_codes || "")}" data-notr></label>
        <label class="span2">切片文件版本（自动）<input id="asx-files" value="${esc(a.print_files || "")}" data-notr></label>
      </div>
      ${own() ? `<h4>损失（会从利润里扣）</h4><div class="form3">${Object.entries(LOSS).map(([k, v]) =>
        `<label>${v} ฿<input data-loss="${k}" type="number" step="0.01" min="0" value="${a[k] ?? ""}"></label>`).join("")}
        <div class="small muted" style="align-self:end">合计 <b>${H().money(a.loss) || "฿0"}</b><br>（订单已是退货/取消/拒收时，退款不重复扣）</div></div>` : ""}
      <label>说明<textarea id="asx-note" rows="2" data-notr>${esc(a.note || "")}</textarea></label>
      <button class="primary" id="asx-save">保存修改</button>
      <h4>凭证（照片 / 视频 / 截图）</h4>
      <div class="ev-grid">${a.evidence.map((f) => `<div class="ev">${isImg(f.file) ? `<a href="${url(f.file)}" target="_blank"><img src="${url(f.file)}" loading="lazy"></a>`
        : isVid(f.file) ? `<video src="${url(f.file)}" controls preload="metadata"></video>` : `<a class="btn" href="${url(f.file)}" target="_blank">📄 打开</a>`}
        <div class="small muted" data-notr>${esc(f.name)}</div><button class="mini danger" data-evdel="${esc(f.file)}">删除</button></div>`).join("") || '<span class="muted small">还没有凭证</span>'}</div>
      <label class="filebtn">⬆ 上传照片 / 视频<input type="file" id="asx-up" multiple accept="image/*,video/*,.pdf" hidden></label>
      <h4>退货验货</h4>
      ${a.inspected_at ? `<p class="small">${fmtTime(a.inspected_at)} 由 <span data-notr>${esc(a.inspected_by || "")}</span> 验货：
          ${a.inspect_items.map((x) => `<span class="mono" data-notr>${esc(x.sku)}</span> 入库 ${x.restock} / 报废 ${x.scrap}`).join("；")}
          ${a.inspect_note ? ` · <span data-notr>${esc(a.inspect_note)}</span>` : ""}</p>`
        : canInspect ? `<p class="small muted">包裹退回来后逐个检查：完好能再卖的「入库」（加到成品库存），坏了的「报废」（按生产成本记损失）。拒收件验完会自动关闭。</p>
          <table class="grid small"><thead><tr><th>SKU</th><th>商品</th><th>原数量</th><th>入库</th><th>报废</th></tr></thead><tbody>
          ${a.items.map((i) => `<tr><td class="mono" data-notr>${esc(i.sku)}</td><td data-notr>${esc(i.name || "")} ${H().colorTxt(i.color)}</td><td>${i.qty}</td>
            <td><input type="number" min="0" max="${i.qty}" value="${i.qty}" data-rs="${i.id}" style="width:64px"></td>
            <td><input type="number" min="0" max="${i.qty}" value="0" data-sc="${i.id}" style="width:64px"></td></tr>`).join("")}</tbody></table>
          <label>验货说明<input id="asx-inote" data-notr></label><button id="asx-inspect">✔ 验货完成</button>`
        : '<p class="small muted">这个售后不需要验货（或还没到这一步）。</p>'}
      <details class="log-box"><summary><b>处理记录</b> <span class="muted small">${a.log.length} 条</span></summary>
        <table class="grid small"><tbody>${a.log.map((l) => `<tr><td class="nowrap">${fmtTime(l.ts)}</td><td data-notr>${esc(l.username || "")}</td><td>${esc(l.action)}</td>
          <td data-notr>${esc(l.detail || "")}</td></tr>`).join("")}</tbody></table></details>`);
    $("#modal-in").classList.add("wide");
    const save = async (extra = {}) => {
      const v = (id) => $(id, el).value;
      const body = { kind: v("#asx-kind"), reason: v("#asx-reason"), due_at: v("#asx-due").replace("T", " "), responsibility: v("#asx-resp"),
        staff: v("#asx-staff"), return_tracking: v("#asx-rtrack").trim(), printer_codes: v("#asx-printers"), print_files: v("#asx-files"),
        note: v("#asx-note"), ...extra };
      if (extra.stage) delete body.due_at;   // 换阶段：期限按新阶段自动算
      $$("[data-loss]", el).forEach((i) => (body[i.dataset.loss] = i.value));
      await api(`/api/aftersales/${aid}`, { json: body });
    };
    el.onclick = async (e) => {
      const t = e.target;
      if (t.closest("[data-oid]")) { MODAL.close(); if (window.OPS) OPS.openOrder(+t.closest("[data-oid]").dataset.oid); return; }
      if (t.dataset.stage) {
        await busy(t, async () => { await save({ stage: t.dataset.stage }); toast("已更新"); open(aid); refresh(); });
        return;
      }
      if (t.id === "asx-save") { await busy(t, async () => { await save(); toast("已保存"); open(aid); refresh(); }); return; }
      if (t.dataset.evdel) {
        if (!confirmDelete("这个凭证文件")) return;
        try { await api(`/api/aftersales/${aid}/evidence/${encodeURIComponent(t.dataset.evdel)}`, { method: "DELETE" }); open(aid); } catch (err) { toast(err.message, true); }
        return;
      }
      if (t.id === "asx-inspect") {
        const items = a.items.map((i) => ({ item_id: i.id, restock: +$(`[data-rs="${i.id}"]`, el).value || 0, scrap: +$(`[data-sc="${i.id}"]`, el).value || 0 }));
        await busy(t, async () => {
          await api(`/api/aftersales/${aid}/inspect`, { json: { items, note: $("#asx-inote", el).value } });
          toast("验货完成"); open(aid); refresh();
        });
      }
    };
    $("#asx-up", el).addEventListener("change", async (e) => {
      if (!e.target.files.length) return;
      try { await upload(aid, e.target.files); toast("已上传"); open(aid); refresh(); } catch (err) { toast(err.message, true); }
    });
  }
  function refresh() {
    if (!$("#tab-aftersales").classList.contains("hidden")) load();
  }

  window.AS = { show, dialog, open, load };
})();
