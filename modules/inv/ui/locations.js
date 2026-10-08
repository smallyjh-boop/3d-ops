"use strict";
// 库存模块：货位（v2.35：一个物品一个货位，数量只记在物品上）。
// 页面按 区 → 货架 画：一行一层、一格一位，格子里写放了什么、现在还有多少；点格子：入库 / 出库 / 换货位 / 放物品 / 盘点。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const num = (v, d = 2) => (v == null || v === "" ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const itName = (it) => (TH() && it.name_th ? it.name_th : it.name_zh) || "";
  const pad = (n) => String(n).padStart(2, "0");
  const U_TH = { "个": "ชิ้น", "卷": "ม้วน", "张": "แผ่น", "件": "ชิ้น", "米": "เมตร", "瓶": "ขวด", "盒": "กล่อง", "套": "ชุด" };
  const uLab = (u) => (TH() && U_TH[u]) || u || "";
  let LOCS = [], GROUPS = {}, CATS = [], BOTTOM = true, BOX = null;

  async function loadLocs() {
    const r = await api("/api/inv/locations");
    LOCS = r.locations; GROUPS = r.groups || {}; CATS = r.categories || []; BOTTOM = r.layer_bottom !== false;
    return r;
  }
  const shelfOf = (l) => (l.shelf != null ? `${l.zone}${l.shelf}` : "");
  const human = (code) => {
    const m = /^([A-Z]{1,2})(\d{1,2})-(\d{2})-(\d{2})$/.exec(code || "");
    if (!m) return code || "";
    return Z(`${m[1]}区 ${+m[2]}号货架 第${+m[3]}层 第${+m[4]}位`, `โซน ${m[1]} แร็ค ${+m[2]} ชั้น ${+m[3]} ช่อง ${+m[4]}`);
  };
  const catName = (id) => { const c = CATS.find((x) => x.id === id); return c ? (TH() ? c.th : c.zh) : id; };
  const catChips = (g) => (g && g.categories && g.categories.length
    ? `<span class="loc-cats" data-notr>${esc(Z("放：", "เก็บ: "))}${g.categories.map((c) => esc(catName(c))).join(Z("、", ", "))}</span>` : "");
  // 货位下拉：按货架分组，空格后面标「空」
  const locOpts = (sel = "", withNone = "") => {
    const opt = (l) => `<option value="${esc(l.code)}" ${sel === l.code ? "selected" : ""}>${esc(l.code)}${l.items ? "" : Z(" ·空", " ·ว่าง")}</option>`;
    const by = {};
    LOCS.forEach((l) => (by[shelfOf(l) || "~"] = by[shelfOf(l) || "~"] || []).push(l));
    return (withNone ? `<option value="">${esc(withNone)}</option>` : "") + Object.entries(by).map(([sc, ls]) =>
      `<optgroup label="${esc(sc === "~" ? Z("其他货位", "ช่องอื่นๆ") : `${sc}${GROUPS[sc] && GROUPS[sc].name ? " · " + GROUPS[sc].name : ""}`)}">${ls.map(opt).join("")}</optgroup>`).join("");
  };
  const nextShelf = (zone) => 1 + Math.max(0, ...LOCS.filter((l) => l.zone === zone && l.shelf != null).map((l) => l.shelf));
  const lang = () => (TH() ? "&lang=th" : "");
  const can = (k) => !window.INV || !INV.can || INV.can(k);

  // 格子：空 / 有货 / 放了东西但用完了（灰）/ 低于补货线（橙）
  function cell(l) {
    const t = l.top || [];
    const st = !l.items ? "" : l.low ? "low" : l.qty > 1e-9 ? "on" : "zero";
    const tip = [l.code, human(l.code), ...t.map((x) => `${x.code} ${itName(x)} ×${num(x.qty)} ${uLab(x.unit)}`), l.note || ""].filter(Boolean).join("\n");
    return `<button class="loc-cell ${st}" data-loc="${l.id}" data-code="${esc(l.code)}" title="${esc(tip)}" data-notr>
      <span class="pn">${pad(l.pos)}</span>
      <span class="it">${t.length ? `${esc(t[0].code)} ×${num(t[0].qty)}${l.items > 1 ? ` +${l.items - 1}` : ""}` : esc(Z("空", "ว่าง"))}</span></button>`;
  }

  function shelfCard(sc, ls) {
    const g = GROUPS[sc] || {};
    const layers = [...new Set(ls.map((l) => l.layer))].sort((a, b) => (BOTTOM ? b - a : a - b));
    const maxPos = Math.max(...ls.map((l) => l.pos));
    const topLayer = Math.max(...ls.map((l) => l.layer));
    const empty = ls.filter((l) => !l.items).length;
    return `<div class="loc-shelf" data-shelf="${esc(sc)}">
      <div class="loc-sh-head"><b class="mono" data-notr>${esc(sc)}</b> <span data-notr>${esc(g.name || "")}</span>
        <span class="small muted" data-notr>${esc(Z(`${layers.length} 层 · ${ls.length} 位 · 空 ${empty}`, `${layers.length} ชั้น · ${ls.length} ช่อง · ว่าง ${empty}`))}</span> ${catChips(g)}
        <span class="loc-sh-tools"><button class="mini" data-grp="${esc(sc)}" title="名称 / 放哪些分类">✎</button>
          <a class="btn mini" target="_blank" href="/print/inv-locations?shelf=${encodeURIComponent(sc)}${lang()}" title="打印这个货架的货位标签">🏷</a>
          ${can("inv.out") ? `<button class="mini" data-stk="${esc(sc)}" title="数一数这个货架上的东西">🧮 盘点</button>` : ""}
          <button class="mini" data-addlayer="${esc(sc)}">＋ 加一层</button>${empty === ls.length ? `<button class="mini danger" data-rmshelf="${esc(sc)}">删除货架</button>` : ""}</span></div>
      <table class="loc-rack"><tbody>${layers.map((ly) => {
        const row = ls.filter((l) => l.layer === ly).sort((a, b) => a.pos - b.pos);
        const allEmpty = row.every((l) => !l.items);
        return `<tr><th class="nowrap" data-notr>${esc(Z(`第 ${ly} 层`, `ชั้น ${ly}`))}</th>
          <td><div class="loc-row" style="grid-template-columns:repeat(${Math.max(maxPos, row.length)},minmax(74px,1fr))">${row.map(cell).join("")}</div></td>
          <td class="nowrap"><button class="mini" data-addpos="${esc(sc)}" data-layer="${ly}" title="这一层加一位">＋</button>${allEmpty && layers.length > 1 && ly === topLayer ? `<button class="mini" data-rmlayer="${esc(sc)}" data-layer="${ly}" title="删掉最上面这一层（空的才能删）">−</button>` : ""}</td></tr>`;
      }).join("")}</tbody></table>
      ${BOTTOM ? `<div class="small muted loc-floor" data-notr>${esc(Z("地面", "พื้น"))}</div>` : ""}</div>`;
  }

  async function render(box) {
    BOX = box;
    const r = await loadLocs();
    const zones = {}, other = [];
    LOCS.forEach((l) => {
      if (l.shelf == null) return other.push(l);
      ((zones[l.zone] = zones[l.zone] || {})[shelfOf(l)] = zones[l.zone][shelfOf(l)] || []).push(l);
    });
    const zoneKeys = Object.keys(zones).sort();
    box.innerHTML = `<div class="row gap wrap" style="margin-bottom:8px">
        <input id="loc-scan" placeholder="扫货位 / 货架 / 物品条码，或输入编号" style="width:260px" autocomplete="off">
        <button class="primary" id="loc-bulk">＋ 新建货架</button>
        <a class="btn" target="_blank" href="/print/inv-locations?x=1${lang()}">🏷 打印全部货位标签</a>
        <a class="btn" target="_blank" href="/print/inv-locations?kind=shelf${lang()}">🪧 打印货架牌</a>
        ${r.unassigned ? `<button class="warn-btn" id="loc-unassigned">${esc(Z(`没货位的物品（${r.unassigned}）`, `รายการที่ยังไม่มีช่องเก็บ (${r.unassigned})`))}</button>` : '<span class="small ok">✓ 有库存的物品都有货位</span>'}</div>
      <p class="small muted">一个物品放一个货位，数量就是库存数：入库、出库、打印扣料、发货、盘点之后，货架上自动跟着变。在物品资料里选货位，或者点格子「放物品」，是同一件事。新物品第一次入库时自动放到它这个分类的货架的空格。</p>
      <div class="row gap wrap small loc-legend"><span class="lg on">有货</span><span class="lg zero">用完了</span><span class="lg low">低于补货线</span><span class="lg">${Z("空", "ว่าง")}</span></div>
      ${zoneKeys.map((z) => {
        const g = GROUPS[z] || {};
        const shelves = Object.keys(zones[z]).sort((a, b) => parseInt(a.slice(z.length), 10) - parseInt(b.slice(z.length), 10));
        return `<div class="card loc-zone" data-zone="${esc(z)}"><h3 data-notr>${esc(Z(`${z} 区`, `โซน ${z}`))} <span class="small" data-notr>${esc(g.name || "")}</span> ${catChips(g)}
          <button class="mini" data-grp="${esc(z)}" title="区的名称 / 放哪些分类">✎</button>
          <span class="small muted" data-notr>${esc(Z(`${shelves.length} 个货架`, `${shelves.length} แร็ค`))}</span></h3>
          <div class="loc-shelves">${shelves.map((sc) => shelfCard(sc, zones[z][sc])).join("")}</div></div>`;
      }).join("")}
      ${other.length ? `<div class="card"><h3>其他货位 <span class="small muted">（编号不是「区+货架号-层-位」写法的，空了可以删掉）</span></h3>
        <div class="loc-row" style="grid-template-columns:repeat(auto-fill,minmax(92px,1fr))">${other.map((l) => `<button class="loc-cell ${l.items ? "on" : ""}" data-loc="${l.id}" data-notr><span class="pn">${esc(l.code)}</span>
          <span class="it">${esc(l.items ? Z(`${l.items} 种`, `${l.items} รายการ`) : Z("空", "ว่าง"))}</span></button>`).join("")}</div></div>` : ""}
      ${LOCS.length ? "" : '<div class="card"><p class="muted">还没有货位。点「＋ 新建货架」：选区（例如 A）、从几号货架开始、建几个、几层、每层几位，一次建好，再打印标签贴上。</p></div>'}`;
    const sc = $("#loc-scan");
    sc.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter" || !sc.value.trim()) return;
      try { const d = await api(`/api/inv/locations/find?code=${encodeURIComponent(sc.value.trim())}`); sc.value = ""; found(d); }
      catch (err) { toast(err.message, true); }
    });
  }

  function flash(els) {
    document.querySelectorAll(".loc-hl").forEach((x) => x.classList.remove("loc-hl"));
    els = [...els].filter(Boolean);
    els.forEach((x) => x.classList.add("loc-hl"));
    if (els[0]) els[0].scrollIntoView({ block: "center", behavior: "smooth" });
    setTimeout(() => els.forEach((x) => x.classList.remove("loc-hl")), 6000);
  }
  function found(d) {
    if (d.type === "location") return detail(d.location.id, d);
    if (d.type === "shelf") return flash([document.querySelector(`.loc-shelf[data-shelf="${d.code}"]`)]);
    if (d.type === "zone") return flash([document.querySelector(`.loc-zone[data-zone="${d.code}"]`)]);
    if (d.type === "item") {
      const it = d.item;
      if (d.location) flash([document.querySelector(`.loc-cell[data-loc="${d.location.id}"]`)]);
      toast(`${it.code} ${itName(it)}：${d.location ? `${d.location.code}（${human(d.location.code)}）` : Z("还没有货位", "ยังไม่มีช่องเก็บ")} · ${Z("库存", "สต็อก")} ${num(it.qty)}`, false, 8000);
    }
  }

  function catBoxes(sel) {
    return `<div class="row gap wrap loc-catbox">${CATS.map((c) => `<label class="nowrap"><input type="checkbox" value="${esc(c.id)}" ${sel.includes(c.id) ? "checked" : ""}> <span data-notr>${esc(TH() ? c.th : c.zh)}</span></label>`).join("")}</div>`;
  }
  const pickedCats = (m) => [...m.querySelectorAll(".loc-catbox input:checked")].map((x) => x.value);

  // ---------------- 新建货架（可以一次建几个）----------------
  async function bulk() {
    if (!LOCS.length) await loadLocs();
    const z0 = (LOCS[LOCS.length - 1] || {}).zone || "A";
    const m = MODAL.open(`<h3>新建货架</h3>
      <p class="small muted">一次生成货架的全部格子，编号 = 区字母 + 货架号 - 层 - 位。已经有的格子跳过（同一个货架号再建一次 = 补上缺的层和位）。</p>
      <div class="form4"><label>区（字母）<input id="lb-zone" value="${esc(z0)}" maxlength="2" style="text-transform:uppercase"></label>
        <label>从几号货架开始<input id="lb-shelf" type="number" value="${nextShelf(z0)}" min="1" max="99"></label>
        <label>建几个货架<input id="lb-count" type="number" value="1" min="1" max="20"></label>
        <label>每个几层<input id="lb-layers" type="number" value="4" min="1" max="20"></label>
        <label>每层几位<input id="lb-pos" type="number" value="5" min="1" max="50"></label>
        <label>名称（可以不填）<input id="lb-name" maxlength="40" placeholder="例如 门口铁架"></label></div>
      <div class="small">这些货架放哪些分类（新物品第一次入库时自动放到这里，可以不选）</div>${catBoxes([])}
      <p class="small ok" id="lb-prev" data-notr></p>
      <div class="row gap"><button class="primary" id="lb-ok">建好</button><button data-mclose>取消</button></div>`);
    const v = (id) => m.querySelector(id).value.trim();
    const prev = () => {
      if (!m.querySelector("#lb-zone")) return;          // 已经换成别的弹窗了
      const z = v("#lb-zone").toUpperCase(), s = +v("#lb-shelf"), n = Math.max(1, +v("#lb-count") || 1), L = +v("#lb-layers"), P = +v("#lb-pos");
      const last = s + n - 1;
      m.querySelector("#lb-prev").textContent = /^[A-Z]{1,2}$/.test(z) && s > 0 && L > 0 && P > 0
        ? Z(`将生成 ${n > 1 ? `${z}${s} … ${z}${last}（${n} 个货架）` : `${z}${s}`}，每个 ${L} 层 × ${P} 位，共 ${n * L * P} 个货位：${z}${s}-01-01 … ${z}${last}-${pad(L)}-${pad(P)}`,
          `จะสร้าง ${n > 1 ? `${z}${s} … ${z}${last} (${n} แร็ค)` : `${z}${s}`} แร็คละ ${L} ชั้น × ${P} ช่อง รวม ${n * L * P} ช่อง: ${z}${s}-01-01 … ${z}${last}-${pad(L)}-${pad(P)}`) : "";
    };
    m.querySelector("#lb-zone").addEventListener("input", () => { m.querySelector("#lb-shelf").value = nextShelf(v("#lb-zone").toUpperCase()); prev(); });
    m.oninput = prev; prev();             // 弹窗框是共用的：用 oninput（关掉时清空），不用 addEventListener（会一直留着）
    m.querySelector("#lb-ok").onclick = () => busy(m.querySelector("#lb-ok"), async () => {
      const r = await api("/api/inv/locations/bulk", { json: { zone: v("#lb-zone"), shelf: v("#lb-shelf"), count: v("#lb-count"), layers: v("#lb-layers"),
        positions: v("#lb-pos"), name: v("#lb-name"), categories: pickedCats(m) } });
      toast(Z(`建好了：${r.shelves.join("、")}，新增 ${r.made.length} 个货位`, `สร้างแล้ว: ${r.shelves.join(", ")} เพิ่ม ${r.made.length} ช่อง`)); MODAL.close(); render(BOX);
    });
  }

  function groupModal(code) {
    const g = GROUPS[code] || { name: "", categories: [] };
    const isZone = /^[A-Z]{1,2}$/.test(code);
    const m = MODAL.open(`<h3>${isZone ? "区的设置" : "货架设置"} <span class="mono" data-notr>${esc(code)}</span></h3>
      <div class="form4"><label>名称（可以不填）<input id="lg-name" maxlength="40" value="${esc(g.name || "")}"></label></div>
      <div class="small">${isZone ? "放哪些分类：新物品第一次入库时，先放到这个区的空格" : "放哪些分类：新物品第一次入库时，先放到这个货架的空格"}</div>${catBoxes(g.categories || [])}
      <div class="row gap" style="margin-top:8px"><button class="primary" id="lg-ok">保存</button><button data-mclose>取消</button></div>`);
    m.querySelector("#lg-ok").onclick = () => busy(m.querySelector("#lg-ok"), async () => {
      await api("/api/inv/locations/group", { json: { code, name: m.querySelector("#lg-name").value.trim(), categories: pickedCats(m) } });
      toast("已保存"); MODAL.close(); render(BOX);
    });
  }

  // ---------------- 点格子：里面的东西 + 入库 / 出库 / 换货位 / 放物品 / 盘点 ----------------
  async function detail(lid, pre) {
    const d = pre || await api(`/api/inv/locations/${lid}`);
    if (!LOCS.length) await loadLocs();
    const L = d.location;
    const all = (await api("/api/inv/items")).items;
    const others = all.filter((it) => it.location !== L.code)
      .sort((a, b) => (a.location ? 1 : 0) - (b.location ? 1 : 0) || String(a.code).localeCompare(String(b.code)));
    const m = MODAL.open(`<h3>货位 <span class="mono" data-notr>${esc(L.code)}</span> <span class="small" data-notr>${esc(human(L.code))}</span> <span class="muted small" data-notr>${esc(L.note || "")}</span></h3>
      ${d.items.length ? `<table class="grid small"><thead><tr><th>编码</th><th>名称</th><th>库存</th><th></th><th>换到</th></tr></thead><tbody>
        ${d.items.map((it) => `<tr data-iid="${it.id}" class="${it.low ? "inv-low" : ""}"><td class="mono" data-notr>${esc(it.code)}</td><td data-notr>${esc(itName(it))}</td>
          <td class="nowrap"><b>${num(it.qty)}</b> <span data-notr>${esc(uLab(it.unit))}</span>${it.low ? ' <span class="bad">⚠</span>' : ""}</td>
          <td class="nowrap">${can("inv.in") ? '<button class="mini" data-dk="purchase">＋ 入库</button>' : ""}${can("inv.out") ? '<button class="mini" data-dk="issue">− 出库</button>' : ""}</td>
          <td class="nowrap">${can("inv.in") ? `<select data-to class="loc-to" data-notr>${locOpts(L.code, Z("拿下来（没有货位）", "เอาออก (ไม่มีช่องเก็บ)"))}</select><button class="mini" data-mv>${Z("换", "ย้าย")}</button>` : ""}</td></tr>`).join("")}</tbody></table>`
        : '<p class="muted">这个货位是空的。</p>'}
      ${can("inv.in") ? `<div class="row gap wrap" style="margin-top:8px"><span class="small">放物品到这里：</span>
        <select id="loc-put" data-notr style="max-width:340px"><option value="">${esc(Z("选物品", "เลือกรายการ"))}</option>${others.map((it) => `<option value="${it.id}">${esc(it.code)} · ${esc(itName(it))}${it.location ? ` （${Z("现在在", "อยู่ที่")} ${esc(it.location)}）` : ""}</option>`).join("")}</select>
        <button class="mini primary" id="loc-put-ok">${Z("放", "วาง")}</button></div>` : ""}
      <div class="row gap" style="margin-top:10px">${d.items.length && can("inv.out") ? '<button id="loc-stk">🧮 盘点这个货位</button>' : ""}
        <a class="btn" target="_blank" href="/print/inv-locations?ids=${L.id}${lang()}">🏷 打印这个货位的标签</a>
        ${d.items.length ? "" : '<button class="danger" id="loc-del">删除货位</button>'}<button data-mclose>关闭</button></div>`);
    m.classList.add("wide");
    const again = async () => { await loadLocs(); detail(L.id); if (BOX) render(BOX); };
    m.onclick = async (e) => {
      try {
        const tr = e.target.closest("tr[data-iid]");
        if (e.target.dataset.dk && tr && window.INV) {
          MODAL.close();
          return INV.docModal(e.target.dataset.dk, { item_id: +tr.dataset.iid });
        }
        if (e.target.dataset.mv !== undefined && tr) {
          const to = tr.querySelector("[data-to]").value;
          await api("/api/inv/locations/assign", { json: { item_id: +tr.dataset.iid, code: to } });
          toast(to ? Z(`已换到 ${to}`, `ย้ายไป ${to} แล้ว`) : Z("已拿下来", "เอาออกแล้ว")); return again();
        }
        if (e.target.id === "loc-put-ok") {
          const sel = m.querySelector("#loc-put"), iid = +sel.value;
          if (!iid) return toast(Z("先选物品", "เลือกรายการก่อน"), true);
          const it = others.find((x) => x.id === iid);
          if (it && it.location && !confirm(Z(`${it.code} 现在在 ${it.location}，一个物品只放一个货位，换到 ${L.code}？`, `${it.code} อยู่ที่ ${it.location} ย้ายมา ${L.code}?`))) return;
          await api("/api/inv/locations/assign", { json: { item_id: iid, code: L.code } });
          toast(Z("已放好", "วางแล้ว")); return again();
        }
        if (e.target.id === "loc-stk") { MODAL.close(); return stocktake(L.code); }
        if (e.target.id === "loc-del") {
          if (!confirm(Z(`删除货位 ${L.code}？`, `ลบช่อง ${L.code}?`))) return;
          await api(`/api/inv/locations/${L.id}`, { method: "DELETE" }); toast("已删除"); MODAL.close(); if (BOX) render(BOX);
        }
      } catch (err) { toast(err.message, true); }
    };
  }

  async function stocktake(area) {
    try {
      const d = (await api("/api/inv/stocktake", { json: { area } })).doc;
      if (window.INV && INV.openStocktake) INV.openStocktake(d.id);
    } catch (e) { toast(e.message, true); }
  }

  // ---------------- 没货位的物品 ----------------
  async function unassignedModal() {
    const r = await api("/api/inv/locations/unassigned");
    if (!LOCS.length) await loadLocs();
    const m = MODAL.open(`<h3>没货位的物品</h3><p class="small muted">有库存、但还没有货位的物品。按推荐一键放好，或者一行一行选。</p>
      <table class="grid small"><thead><tr><th>编码</th><th>名称</th><th>库存</th><th>放到</th><th></th></tr></thead><tbody>
      ${r.items.map((x) => `<tr data-iid="${x.item.id}"><td class="mono" data-notr>${esc(x.item.code)}</td><td data-notr>${esc(itName(x.item))}</td>
        <td><b>${num(x.item.qty)}</b> <span data-notr>${esc(uLab(x.item.unit))}</span></td>
        <td><select data-to class="loc-to" data-notr>${locOpts(x.suggest || "", Z("选货位", "เลือกช่อง"))}</select>${x.suggest ? "" : ' <span class="small warn">没有合适的空格</span>'}</td>
        <td><button class="mini" data-put>${Z("放", "วาง")}</button></td></tr>`).join("") || '<tr><td colspan="5" class="muted">没有</td></tr>'}</tbody></table>
      <div class="row gap" style="margin-top:8px"><button class="primary" id="loc-all">全部按推荐放</button><button data-mclose>关闭</button></div>`);
    m.classList.add("wide");
    m.onclick = async (e) => {
      try {
        if (e.target.dataset.put !== undefined) {
          const tr = e.target.closest("tr"), code = tr.querySelector("[data-to]").value;
          if (!code) return toast(Z("先选货位", "เลือกช่องก่อน"), true);
          await api("/api/inv/locations/assign", { json: { item_id: +tr.dataset.iid, code } });
          tr.remove(); toast(Z("已放好", "วางแล้ว")); await loadLocs();
        }
        if (e.target.id === "loc-all") {
          const x = await api("/api/inv/locations/assign-all", { json: {} });
          toast(Z(`已放好 ${x.done.length} 个物品`, `วางแล้ว ${x.done.length} รายการ`)); MODAL.close(); if (BOX) render(BOX);
        }
      } catch (err) { toast(err.message, true); }
    };
  }

  async function act(fn, ok) { try { await fn(); if (ok) toast(ok); if (BOX) render(BOX); } catch (er) { toast(er.message, true); } }
  document.addEventListener("click", (e) => {
    if (!e.target.closest || !e.target.closest("#tab-inventory")) return;
    const t = e.target.closest("[data-loc],[data-grp],[data-addlayer],[data-addpos],[data-rmlayer],[data-rmshelf],[data-stk]");
    if (t && t.dataset.loc) return detail(+t.dataset.loc).catch((er) => toast(er.message, true));
    if (t && t.dataset.grp) return groupModal(t.dataset.grp);
    if (t && t.dataset.stk) return stocktake(t.dataset.stk);
    if (t && t.dataset.addlayer) return act(() => api("/api/inv/locations/add", { json: { shelf: t.dataset.addlayer } }), Z("加了一层", "เพิ่มชั้นแล้ว"));
    if (t && t.dataset.addpos) return act(() => api("/api/inv/locations/add", { json: { shelf: t.dataset.addpos, layer: +t.dataset.layer } }), Z("加了一位", "เพิ่มช่องแล้ว"));
    if (t && t.dataset.rmlayer) {
      if (!confirm(Z(`删掉货架 ${t.dataset.rmlayer} 的第 ${t.dataset.layer} 层？`, `ลบชั้น ${t.dataset.layer} ของแร็ค ${t.dataset.rmlayer}?`))) return;
      return act(() => api("/api/inv/locations/remove", { json: { shelf: t.dataset.rmlayer, layer: +t.dataset.layer } }), Z("已删除", "ลบแล้ว"));
    }
    if (t && t.dataset.rmshelf) {
      if (!confirm(Z(`删除整个货架 ${t.dataset.rmshelf}（里面都是空的）？`, `ลบแร็ค ${t.dataset.rmshelf} ทั้งหมด (ว่างทั้งหมด)?`))) return;
      return act(() => api("/api/inv/locations/remove", { json: { shelf: t.dataset.rmshelf } }), Z("已删除", "ลบแล้ว"));
    }
    if (e.target.id === "loc-bulk") return bulk();
    if (e.target.id === "loc-unassigned") return unassignedModal().catch((er) => toast(er.message, true));
  });
  window.INVLOC = { render, detail, loadLocs, list: () => LOCS, shelves: () => [...new Set(LOCS.map(shelfOf).filter(Boolean))], human, stocktake };
})();
