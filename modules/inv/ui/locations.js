"use strict";
// 库存模块：货位管理（v2.33）。区-货架-格，按货位记数量；入库自动上架、出库自动扣、移库、货位核对、货位标签。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const num = (v, d = 2) => (v == null || v === "" ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const itName = (it) => (TH() && it.name_th ? it.name_th : it.name_zh) || "";
  let LOCS = [], BOX = null;

  async function loadLocs() { const r = await api("/api/inv/locations"); LOCS = r.locations; return r; }
  const locOpts = (sel = 0, withNone = "") => (withNone ? `<option value="0">${esc(withNone)}</option>` : "") +
    LOCS.map((l) => `<option value="${l.id}" ${+sel === l.id ? "selected" : ""} data-notr>${esc(l.code)}${l.items ? "" : Z(" ·空", " ·ว่าง")}</option>`).join("");

  async function render(box) {
    BOX = box;
    const r = await loadLocs();
    const zones = {};
    LOCS.forEach((l) => (zones[l.zone] = zones[l.zone] || []).push(l));
    box.innerHTML = `<div class="row gap wrap" style="margin-bottom:8px">
        <input id="loc-scan" placeholder="扫货位条码 / 输入货位编号" style="width:220px" autocomplete="off" data-notr>
        <button class="primary" id="loc-bulk">＋ 批量建货位</button><button id="loc-new">＋ 单个货位</button>
        <a class="btn" target="_blank" href="/print/inv-locations">🏷 打印全部货位标签</a>
        ${r.unplaced ? `<button class="warn-btn" id="loc-unplaced">未上架的物品（${r.unplaced}）</button>` : '<span class="small ok">✓ 所有库存都放在货位上了</span>'}</div>
      <p class="small muted">货位编号 = 区-货架-格（例如 A-01-03）。入库时自动放进推荐货位（物品已经在的货位 → 物品资料里的默认货位 → 这个分类默认的区里的空格），出库、打印扣料、发货扣包材时自动从货位扣。在 设置 → 库存与采购 → 货位 里设置每个分类放哪个区。</p>
      ${LOCS.length ? Object.entries(zones).map(([z, ls]) => `<div class="card"><h3 data-notr>${esc(Z(`${z} 区`, `โซน ${z}`))} <span class="muted small">${esc(Z(`${ls.length} 个货位 · 空 ${ls.filter((l) => !l.items).length}`, `${ls.length} ช่อง · ว่าง ${ls.filter((l) => !l.items).length}`))}</span></h3>
        <div class="loc-grid">${ls.map((l) => `<button class="loc-cell ${l.items ? "on" : ""}" data-loc="${l.id}" title="${esc(l.note || "")}"><b data-notr>${esc(l.code)}</b>
          <span class="small" data-notr>${l.items ? Z(`${l.items} 种`, `${l.items} รายการ`) : Z("空", "ว่าง")}</span></button>`).join("")}</div></div>`).join("")
        : '<div class="card"><p class="muted">还没有货位。点「＋ 批量建货位」，例如 A 区 3 个货架、每个 6 格，一次建好 18 个，再打印标签贴上。</p></div>'}`;
    const sc = $("#loc-scan");
    sc.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter" || !sc.value.trim()) return;
      try { const d = await api(`/api/inv/locations/find?code=${encodeURIComponent(sc.value.trim())}`); sc.value = ""; detail(d.location.id, d); }
      catch (err) { toast(err.message, true); }
    });
  }

  async function bulk() {
    const m = MODAL.open(`<h3>批量建货位</h3><p class="small muted">按「区-货架-格」生成编号，已经有的跳过。例如 A 区、3 个货架、每个 6 格 → A-01-01 … A-03-06。</p>
      <div class="form4"><label>区（字母）<input id="lb-zone" value="A" maxlength="3" data-notr></label><label>货架数<input id="lb-sh" type="number" value="3" min="1" max="99"></label>
      <label>每个货架几格<input id="lb-c" type="number" value="6" min="1" max="99"></label></div>
      <div class="row gap"><button class="primary" id="lb-ok">建好</button><button data-mclose>取消</button></div>`);
    m.querySelector("#lb-ok").onclick = () => busy(m.querySelector("#lb-ok"), async () => {
      const r = await api("/api/inv/locations/bulk", { json: { zone: m.querySelector("#lb-zone").value, shelves: m.querySelector("#lb-sh").value, cells: m.querySelector("#lb-c").value } });
      toast(`建好了 ${r.made.length} 个货位`); MODAL.close(); render(BOX);
    });
  }
  async function newLoc() {
    const m = MODAL.open(`<h3>新货位</h3><div class="form4"><label>编号（例如 B-01-02）<input id="ln-code" data-notr></label><label>备注（位置说明）<input id="ln-note"></label></div>
      <div class="row gap"><button class="primary" id="ln-ok">保存</button><button data-mclose>取消</button></div>`);
    m.querySelector("#ln-ok").onclick = () => busy(m.querySelector("#ln-ok"), async () => {
      await api("/api/inv/locations", { json: { code: m.querySelector("#ln-code").value, note: m.querySelector("#ln-note").value } });
      toast("已保存"); MODAL.close(); render(BOX);
    });
  }

  async function detail(lid, pre) {
    const d = pre || await api(`/api/inv/locations/${lid}`);
    if (!LOCS.length) await loadLocs();
    const L = d.location;
    const m = MODAL.open(`<h3>货位 <span class="mono" data-notr>${esc(L.code)}</span> <span class="muted small" data-notr>${esc(L.note || "")}</span></h3>
      ${d.items.length ? `<table class="grid small"><thead><tr><th>编码</th><th>名称</th><th>这个货位</th><th>总库存</th><th>核对（数到几个）</th><th>移到</th><th></th></tr></thead><tbody>
        ${d.items.map((it) => `<tr data-iid="${it.id}"><td class="mono" data-notr>${esc(it.code)}</td><td data-notr>${esc(itName(it))}</td><td><b>${num(it.loc_qty)}</b> <span data-notr>${esc(it.unit)}</span></td>
          <td>${num(it.qty)}</td><td><input type="number" step="any" min="0" data-cnt style="width:80px" placeholder="${num(it.loc_qty)}"></td>
          <td class="nowrap"><select data-to>${locOpts(0, "取下（未上架）").replace(`value="${L.id}"`, `value="${L.id}" disabled`)}</select>
            <input type="number" step="any" min="0" data-mq value="${it.loc_qty}" style="width:70px"></td><td><button class="mini" data-mv>移</button></td></tr>`).join("")}</tbody></table>
        <div class="row gap" style="margin-top:6px"><button class="primary" id="loc-chk">保存核对</button>
          <span class="small muted">只填数过的。少了的记回「未上架」；多了的从「未上架」补，再多就提示去盘点调账。</span></div>`
        : '<p class="muted">这个货位是空的。</p>'}
      <div class="row gap" style="margin-top:8px"><a class="btn" target="_blank" href="/print/inv-locations?ids=${L.id}">🏷 打印这个货位的标签</a>
        ${d.items.length ? "" : '<button class="danger" id="loc-del">删除货位</button>'}<button data-mclose>关闭</button></div>
      ${d.log.length ? `<details class="small"><summary>最近记录</summary><table class="grid small">${d.log.map((g) => `<tr><td class="nowrap">${fmtTime(g.ts)}</td>
        <td data-notr>${esc(g.code)} ${esc(g.name_zh)}</td><td>${g.to_loc === L.id ? "+" : "−"}${num(g.qty)}</td><td>${esc(g.reason || "")}</td><td data-notr>${esc(g.username || "")}</td></tr>`).join("")}</table></details>` : ""}`);
    m.classList.add("wide");
    m.onclick = async (e) => {
      try {
        if (e.target.dataset.mv !== undefined) {
          const tr = e.target.closest("tr");
          await api("/api/inv/locations/move", { json: { item_id: +tr.dataset.iid, from_loc: L.id, to_loc: +tr.querySelector("[data-to]").value, qty: tr.querySelector("[data-mq]").value } });
          toast("已移库"); detail(L.id); if (BOX) render(BOX);
        }
        if (e.target.id === "loc-chk") {
          const counts = {};
          m.querySelectorAll("tr[data-iid]").forEach((tr) => { const v = tr.querySelector("[data-cnt]").value; if (v !== "") counts[tr.dataset.iid] = v; });
          if (!Object.keys(counts).length) return toast("先填数到的数量", true);
          const r = await api(`/api/inv/locations/${L.id}/check`, { json: { counts } });
          toast(r.notes.length ? r.notes.map((x) => x.note).join("；") : "核对完成，和账上一样", !!r.notes.length, 8000);
          detail(L.id, r.detail);
        }
        if (e.target.id === "loc-del") {
          if (!confirm(`删除货位 ${L.code}？`)) return;
          await api(`/api/inv/locations/${L.id}`, { method: "DELETE" }); toast("已删除"); MODAL.close(); if (BOX) render(BOX);
        }
      } catch (err) { toast(err.message, true); }
    };
  }

  async function unplacedModal() {
    const r = await api("/api/inv/locations/unplaced");
    if (!LOCS.length) await loadLocs();
    const m = MODAL.open(`<h3>未上架的物品</h3><p class="small muted">有库存、但还没放到货位上的数量。按推荐货位一键上架，或者一行一行选货位。</p>
      <table class="grid small"><thead><tr><th>编码</th><th>名称</th><th>未上架</th><th>上架到</th><th></th></tr></thead><tbody>
      ${r.items.map((x) => `<tr data-iid="${x.item.id}"><td class="mono" data-notr>${esc(x.item.code)}</td><td data-notr>${esc(itName(x.item))}</td>
        <td><b>${num(x.unplaced)}</b> <span data-notr>${esc(x.item.unit)}</span></td>
        <td><select data-to>${locOpts(x.suggest ? x.suggest.id : 0)}</select> ${x.suggest ? `<span class="small muted">${esc(x.suggest.why)}</span>` : '<span class="small warn">没有空货位了</span>'}</td>
        <td><button class="mini" data-up="${x.unplaced}">上架</button></td></tr>`).join("") || '<tr><td colspan="5" class="muted">没有</td></tr>'}</tbody></table>
      <div class="row gap" style="margin-top:8px"><button class="primary" id="loc-all">全部按推荐上架</button><button data-mclose>关闭</button></div>`);
    m.classList.add("wide");
    m.onclick = async (e) => {
      try {
        if (e.target.dataset.up) {
          const tr = e.target.closest("tr");
          await api("/api/inv/locations/move", { json: { item_id: +tr.dataset.iid, from_loc: 0, to_loc: +tr.querySelector("[data-to]").value, qty: e.target.dataset.up } });
          tr.remove(); toast("已上架");
        }
        if (e.target.id === "loc-all") {
          const x = await api("/api/inv/locations/putaway", { json: {} });
          toast(`已上架 ${x.done.length} 个物品`); MODAL.close(); if (BOX) render(BOX);
        }
      } catch (err) { toast(err.message, true); }
    };
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest || !e.target.closest("#tab-inventory")) return;
    const c = e.target.closest("[data-loc]"); if (c) return detail(+c.dataset.loc).catch((er) => toast(er.message, true));
    if (e.target.id === "loc-bulk") return bulk();
    if (e.target.id === "loc-new") return newLoc();
    if (e.target.id === "loc-unplaced") return unplacedModal().catch((er) => toast(er.message, true));
  });
  window.INVLOC = { render, detail, loadLocs, list: () => LOCS };
})();
