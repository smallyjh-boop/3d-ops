"use strict";
// 库存模块：货位管理（v2.33 建，v2.34 改成「区+货架号-层-位」）。
// 页面按 区 → 货架 画：每个货架是一张小表，一行一层、一格一位；点格子打开货位（移库、核对、标签）。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const num = (v, d = 2) => (v == null || v === "" ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const itName = (it) => (TH() && it.name_th ? it.name_th : it.name_zh) || "";
  const pad = (n) => String(n).padStart(2, "0");
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
  // 货位下拉：按货架分组（<optgroup>），空的位后面标「空」
  const locOpts = (sel = 0, withNone = "") => {
    const opt = (l) => `<option value="${l.id}" ${+sel === l.id ? "selected" : ""}>${esc(l.code)}${l.items ? "" : Z(" ·空", " ·ว่าง")}</option>`;
    const by = {};
    LOCS.forEach((l) => (by[shelfOf(l) || "~"] = by[shelfOf(l) || "~"] || []).push(l));
    return (withNone ? `<option value="0">${esc(withNone)}</option>` : "") + Object.entries(by).map(([sc, ls]) =>
      `<optgroup label="${esc(sc === "~" ? Z("其他货位", "ช่องอื่นๆ") : `${sc}${GROUPS[sc] && GROUPS[sc].name ? " · " + GROUPS[sc].name : ""}`)}">${ls.map(opt).join("")}</optgroup>`).join("");
  };
  const nextShelf = (zone) => 1 + Math.max(0, ...LOCS.filter((l) => l.zone === zone && l.shelf != null).map((l) => l.shelf));
  const lang = () => (TH() ? "&lang=th" : "");

  function cell(l) {
    const t = l.top || [];
    const tip = [l.code, human(l.code), ...t.map((x) => `${x.code} ${itName(x)} ×${num(x.qty)}`), l.note || ""].filter(Boolean).join("\n");
    return `<button class="loc-cell ${l.items ? "on" : ""}" data-loc="${l.id}" data-code="${esc(l.code)}" title="${esc(tip)}" data-notr>
      <span class="pn" data-notr>${pad(l.pos)}</span>
      <span class="it" data-notr>${t.length ? `${esc(t[0].code)} ×${num(t[0].qty)}${l.items > 1 ? ` +${l.items - 1}` : ""}` : esc(Z("空", "ว่าง"))}</span></button>`;
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
        ${r.unplaced ? `<button class="warn-btn" id="loc-unplaced">${esc(Z(`未上架的物品（${r.unplaced}）`, `รายการที่ยังไม่เข้าช่อง (${r.unplaced})`))}</button>` : '<span class="small ok">✓ 所有库存都放在货位上了</span>'}</div>
      <p class="small muted">货位编号 = 区字母 + 货架号 - 层 - 位，例如 A1-02-03 就是 A区 1号货架 第2层 第3位。入库时自动放进推荐货位（物品已经在的货位 → 物品资料里的默认货位 → 放这个分类的货架里的空位），出库、打印扣料、发货扣包材时自动从货位扣。点货架上的 ✎ 设置这个货架放哪些分类。</p>
      ${zoneKeys.map((z) => {
        const g = GROUPS[z] || {};
        const shelves = Object.keys(zones[z]).sort((a, b) => parseInt(a.slice(z.length), 10) - parseInt(b.slice(z.length), 10));
        return `<div class="card loc-zone" data-zone="${esc(z)}"><h3 data-notr>${esc(Z(`${z} 区`, `โซน ${z}`))} <span class="small" data-notr>${esc(g.name || "")}</span> ${catChips(g)}
          <button class="mini" data-grp="${esc(z)}" title="区的名称 / 放哪些分类">✎</button>
          <span class="small muted" data-notr>${esc(Z(`${shelves.length} 个货架`, `${shelves.length} แร็ค`))}</span></h3>
          <div class="loc-shelves">${shelves.map((sc) => shelfCard(sc, zones[z][sc])).join("")}</div></div>`;
      }).join("")}
      ${other.length ? `<div class="card"><h3>其他货位 <span class="small muted">（编号不是「区+货架号-层-位」写法的，空了可以删掉）</span></h3>
        <div class="loc-row" style="grid-template-columns:repeat(auto-fill,minmax(92px,1fr))">${other.map((l) => `<button class="loc-cell ${l.items ? "on" : ""}" data-loc="${l.id}"><span class="pn" data-notr>${esc(l.code)}</span>
          <span class="it" data-notr>${esc(l.items ? Z(`${l.items} 种`, `${l.items} รายการ`) : Z("空", "ว่าง"))}</span></button>`).join("")}</div></div>` : ""}
      ${LOCS.length ? "" : '<div class="card"><p class="muted">还没有货位。点「＋ 新建货架」：选区（例如 A）、货架号（1）、几层（4）、每层几位（5），一次建好 A1-01-01 … A1-04-05 共 20 个货位，再打印标签贴上。</p></div>'}`;
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
      flash(d.locations.map((x) => document.querySelector(`.loc-cell[data-loc="${x.loc_id}"]`)));
      const where = d.locations.map((x) => `${x.code} ×${num(x.qty)}`).join(Z("、", ", "));
      toast(`${it.code} ${itName(it)}：${where || Z("还没放到货位上", "ยังไม่ได้เก็บเข้าช่อง")}${d.unplaced > 0 ? Z(`（未上架 ${num(d.unplaced)}）`, ` (ยังไม่เข้าช่อง ${num(d.unplaced)})`) : ""}`, false, 8000);
    }
  }

  function catBoxes(sel) {
    return `<div class="row gap wrap loc-catbox">${CATS.map((c) => `<label class="nowrap"><input type="checkbox" value="${esc(c.id)}" ${sel.includes(c.id) ? "checked" : ""}> <span data-notr>${esc(TH() ? c.th : c.zh)}</span></label>`).join("")}</div>`;
  }
  const pickedCats = (m) => [...m.querySelectorAll(".loc-catbox input:checked")].map((x) => x.value);

  async function bulk() {
    if (!LOCS.length) await loadLocs();
    const z0 = (LOCS[LOCS.length - 1] || {}).zone || "A";
    const m = MODAL.open(`<h3>新建货架</h3>
      <p class="small muted">一次生成这个货架的全部货位，编号 = 区字母 + 货架号 - 层 - 位。已经有的跳过（同一个货架号再建一次 = 补上缺的层和位）。</p>
      <div class="form4"><label>区（字母）<input id="lb-zone" value="${esc(z0)}" maxlength="2" style="text-transform:uppercase"></label>
        <label>货架号<input id="lb-shelf" type="number" value="${nextShelf(z0)}" min="1" max="99"></label>
        <label>几层<input id="lb-layers" type="number" value="4" min="1" max="20"></label>
        <label>每层几位<input id="lb-pos" type="number" value="5" min="1" max="50"></label></div>
      <div class="form4"><label>名称（可以不填）<input id="lb-name" maxlength="40" placeholder="例如 门口铁架"></label></div>
      <div class="small">这个货架放哪些分类（入库自动上架时优先放这里，可以不选）</div>${catBoxes([])}
      <p class="small ok" id="lb-prev" data-notr></p>
      <div class="row gap"><button class="primary" id="lb-ok">建好</button><button data-mclose>取消</button></div>`);
    const v = (id) => m.querySelector(id).value.trim();
    const prev = () => {
      const z = v("#lb-zone").toUpperCase(), s = +v("#lb-shelf"), L = +v("#lb-layers"), P = +v("#lb-pos");
      m.querySelector("#lb-prev").textContent = /^[A-Z]{1,2}$/.test(z) && s > 0 && L > 0 && P > 0
        ? Z(`将生成 ${z}${s}-01-01 … ${z}${s}-${pad(L)}-${pad(P)}，共 ${L * P} 个货位`, `จะสร้าง ${z}${s}-01-01 … ${z}${s}-${pad(L)}-${pad(P)} รวม ${L * P} ช่อง`) : "";
    };
    m.querySelector("#lb-zone").addEventListener("input", () => { m.querySelector("#lb-shelf").value = nextShelf(v("#lb-zone").toUpperCase()); prev(); });
    m.addEventListener("input", prev); prev();
    m.querySelector("#lb-ok").onclick = () => busy(m.querySelector("#lb-ok"), async () => {
      const r = await api("/api/inv/locations/bulk", { json: { zone: v("#lb-zone"), shelf: v("#lb-shelf"), layers: v("#lb-layers"), positions: v("#lb-pos"),
        name: v("#lb-name"), categories: pickedCats(m) } });
      toast(Z(`货架 ${r.shelf} 建好了：新增 ${r.made.length} 个货位`, `สร้างแร็ค ${r.shelf} แล้ว: เพิ่ม ${r.made.length} ช่อง`)); MODAL.close(); render(BOX);
    });
  }

  function groupModal(code) {
    const g = GROUPS[code] || { name: "", categories: [] };
    const isZone = /^[A-Z]{1,2}$/.test(code);
    const m = MODAL.open(`<h3>${isZone ? "区的设置" : "货架设置"} <span class="mono" data-notr>${esc(code)}</span></h3>
      <div class="form4"><label>名称（可以不填）<input id="lg-name" maxlength="40" value="${esc(g.name || "")}"></label></div>
      <div class="small">${isZone ? "放哪些分类：入库自动上架时，这些分类的物品先放到这个区的空位" : "放哪些分类：入库自动上架时，这些分类的物品先放到这个货架的空位"}</div>${catBoxes(g.categories || [])}
      <div class="row gap" style="margin-top:8px"><button class="primary" id="lg-ok">保存</button><button data-mclose>取消</button></div>`);
    m.querySelector("#lg-ok").onclick = () => busy(m.querySelector("#lg-ok"), async () => {
      await api("/api/inv/locations/group", { json: { code, name: m.querySelector("#lg-name").value.trim(), categories: pickedCats(m) } });
      toast("已保存"); MODAL.close(); render(BOX);
    });
  }

  async function detail(lid, pre) {
    const d = pre || await api(`/api/inv/locations/${lid}`);
    if (!LOCS.length) await loadLocs();
    const L = d.location;
    const m = MODAL.open(`<h3>货位 <span class="mono" data-notr>${esc(L.code)}</span> <span class="small" data-notr>${esc(human(L.code))}</span> <span class="muted small" data-notr>${esc(L.note || "")}</span></h3>
      ${d.items.length ? `<table class="grid small"><thead><tr><th>编码</th><th>名称</th><th>这个货位</th><th>总库存</th><th>核对（数到几个）</th><th>移到</th><th></th></tr></thead><tbody>
        ${d.items.map((it) => `<tr data-iid="${it.id}"><td class="mono" data-notr>${esc(it.code)}</td><td data-notr>${esc(itName(it))}</td><td><b>${num(it.loc_qty)}</b> <span data-notr>${esc(it.unit)}</span></td>
          <td>${num(it.qty)}</td><td><input type="number" step="any" min="0" data-cnt style="width:80px" placeholder="${num(it.loc_qty)}"></td>
          <td class="nowrap"><select data-to class="loc-to" data-notr>${locOpts(0, Z("取下（未上架）", "เอาออก (ยังไม่เข้าช่อง)")).replace(`value="${L.id}"`, `value="${L.id}" disabled`)}</select>
            <input type="number" step="any" min="0" data-mq value="${it.loc_qty}" style="width:70px"></td><td><button class="mini" data-mv>移</button></td></tr>`).join("")}</tbody></table>
        <div class="row gap" style="margin-top:6px"><button class="primary" id="loc-chk">保存核对</button>
          <span class="small muted">只填数过的。少了的记回「未上架」；多了的从「未上架」补，再多就提示去盘点调账。</span></div>`
        : '<p class="muted">这个货位是空的。</p>'}
      <div class="row gap" style="margin-top:8px"><a class="btn" target="_blank" href="/print/inv-locations?ids=${L.id}${lang()}">🏷 打印这个货位的标签</a>
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
          if (!confirm(Z(`删除货位 ${L.code}？`, `ลบช่อง ${L.code}?`))) return;
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
        <td><select data-to class="loc-to" data-notr>${locOpts(x.suggest ? x.suggest.id : 0)}</select> ${x.suggest ? `<span class="small muted" data-notr>${esc(whyText(x.suggest.why))}</span>` : '<span class="small warn">没有空货位了</span>'}</td>
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
          toast(Z(`已上架 ${x.done.length} 个物品`, `เก็บเข้าช่องแล้ว ${x.done.length} รายการ`)); MODAL.close(); if (BOX) render(BOX);
        }
      } catch (err) { toast(err.message, true); }
    };
  }
  // 推荐原因（后台写中文，泰文界面换成泰文）
  function whyText(w) {
    if (!TH()) return w;
    return String(w || "").replace("已经放在这里", "อยู่ที่นี่แล้ว").replace("物品资料里的默认货位", "ช่องเริ่มต้นในข้อมูลสินค้า")
      .replace(/物品资料里的默认位置 (\S+) 的空位/, "ช่องว่างใน $1 (ตำแหน่งเริ่มต้น)").replace(/(\S+) 放这个分类，空位/, "ช่องว่างใน $1 (หมวดนี้)").replace("空的货位", "ช่องว่าง");
  }

  async function act(fn, ok) { try { await fn(); if (ok) toast(ok); if (BOX) render(BOX); } catch (er) { toast(er.message, true); } }
  document.addEventListener("click", (e) => {
    if (!e.target.closest || !e.target.closest("#tab-inventory")) return;
    const t = e.target.closest("[data-loc],[data-grp],[data-addlayer],[data-addpos],[data-rmlayer],[data-rmshelf]");
    if (t && t.dataset.loc) return detail(+t.dataset.loc).catch((er) => toast(er.message, true));
    if (t && t.dataset.grp) return groupModal(t.dataset.grp);
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
    if (e.target.id === "loc-unplaced") return unplacedModal().catch((er) => toast(er.message, true));
  });
  window.INVLOC = { render, detail, loadLocs, list: () => LOCS, shelves: () => [...new Set(LOCS.map(shelfOf).filter(Boolean))] };
})();
