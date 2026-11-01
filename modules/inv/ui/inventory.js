"use strict";
// 库存管理（v2.17）：耗材、备件、包材……都是「物品」；数量只能靠单据变（采购入库 / 领用 / 报废 / 调整 / 盘点），每笔都有流水。
(function () {
  let META = null, VIEW = "items", CAT = "";
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const num = (v, d = 0) => (v == null || v === "" ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const catName = (id) => { const c = (META.categories || []).find((x) => x.id === id); return c ? (TH() ? c.th : c.zh) : id; };
  const itName = (it) => (TH() && it.name_th ? it.name_th : it.name_zh) || "";
  function qtyText(it, q = it.qty) {
    if (it.unit === "g") {
      const kg = (q || 0) / 1000;
      return `<b>${num(q)}</b> g <span class="muted">≈ ${num(kg, 2)} kg</span>`;
    }
    return `<b>${num(q, 2)}</b> <span data-notr>${esc(uLab(it.unit))}</span>`;
  }
  const can = (k) => !!(META && META.perms && META.perms[k]);
  const U_TH = { "个": "ชิ้น", "卷": "ม้วน", "张": "แผ่น", "件": "ชิ้น", "米": "เมตร", "瓶": "ขวด", "盒": "กล่อง", "套": "ชุด" };
  const uLab = (u) => (TH() && U_TH[u]) || u || "";

  let SUPS = [];
  async function load() {
    META = await api("/api/inv/meta");
    if (window.INVLOC) INVLOC.loadLocs().catch(() => {});      // v2.33：物品资料里选默认货位用
    try { SUPS = (await api("/api/inv/suppliers")).suppliers; } catch { SUPS = []; }
    render();
  }
  function show(name) {
    if (window.INVZ && ["inventory", "materials", "stock"].includes(name)) INVZ.strip(name);   // v2.53：库存 · 料卷 · 成品备货 页签
    if (name === "inventory") load().catch((e) => toast(e.message, true));
  }

  function render() {
    const box = $("#inv-body"); if (!box) return;
    $$("#inv-views [data-iv]").forEach((b) => b.classList.toggle("on", b.dataset.iv === VIEW));
    $$("#inv-actions [data-perm]").forEach((b) => b.classList.toggle("hidden", !can(b.dataset.perm)));
    const seeMoney = can("inv.pay") || can("inv.in");      // v2.39：支出统计只给有金额权限的人
    $$('#inv-views [data-iv="expense"]').forEach((b) => b.classList.toggle("hidden", !seeMoney));
    if (VIEW === "expense" && !seeMoney) VIEW = "items";
    const al = META.alerts || [];
    $("#inv-alerts").innerHTML = al.length ? `<div class="warnbox small"><b>低于补货线</b>：` +
      al.map((a) => `<span class="chip" data-notr>${esc(TH() && a.name_th ? a.name_th : a.name_zh)} ${num(a.qty, 1)}/${num(a.reorder_point, 1)} ${esc(uLab(a.unit))}</span>`).join(" ") + "</div>" : "";
    if (VIEW === "locations" || VIEW === "stocktake") { const go = VIEW === "locations" ? "inv_locations" : "inv_stocktake"; VIEW = "items"; return goTab(go); }  // v2.52：搬成自己的页面
    if (VIEW === "items" || VIEW === "catalog") return renderItems();
    if (VIEW === "boxes") return renderBoxes().catch((e) => toast(e.message, true));
    if (VIEW === "docs") return renderDocs();
    if (VIEW === "moves") return renderMoves();
    if (VIEW === "expense") return renderExpense();
    if (VIEW === "flows" && window.INVZ) return INVZ.flows(box).catch((e) => toast(e.message, true));   // v2.53：质检 · 退货 · 次品
  }

  // ---------------- 库存 / 物品资料（v2.32：按同行的做法分开，没入过库的不堆在库存里） ----------------
  let SUB = "all";      // 物品资料里：all 全部 / zero 没库存 / inactive 已停用
  let ZONE = "", LOCQ = "";   // v2.53：按区 / 货位筛选
  const CAT_COLS = {    // 每个分类显示自己需要的列
    filament: ["brand", "qty", "transit", "reorder", "cost", "value", "loc"],
    goods: ["qty", "cost", "value", "loc"],
    "": ["brand", "qty", "transit", "reorder", "cost", "value", "loc"],
  };
  async function renderItems() {
    const catalog = VIEW === "catalog";
    const view = catalog ? SUB : "stock";
    const q = ($("#inv-q") || {}).value || "";
    const r = await api(`/api/inv/items?view=${view}&category=${encodeURIComponent(CAT)}&q=${encodeURIComponent(q)}` +
      (catalog ? "" : `&zone=${encodeURIComponent(ZONE)}&loc=${encodeURIComponent(LOCQ)}`));
    const cnt = r.counts || {};
    const key = catalog ? "all" : "stock";
    const sum = (k) => Object.values(cnt).reduce((s, x) => s + (x[k] || 0), 0);
    const chips = [`<span class="chip ${CAT ? "" : "on"}" data-cat="">全部 <span class="muted small">${sum(key)}</span></span>`].concat(
      (META.categories || []).filter((c) => catalog || (cnt[c.id] || {}).stock).map((c) => `<span class="chip ${CAT === c.id ? "on" : ""}" data-cat="${esc(c.id)}">${esc(TH() ? c.th : c.zh)}
        <span class="muted small">${(cnt[c.id] || {})[key] || 0}</span>${!catalog && (cnt[c.id] || {}).low ? ` <span class="bad small">⚠${cnt[c.id].low}</span>` : ""}</span>`)).join("");
    const total = r.items.reduce((s, x) => s + (x.value || 0), 0);
    const cols = CAT_COLS[CAT] || CAT_COLS[""];
    const money = !r.items.length || r.items.some((x) => x.avg_cost !== undefined);   // v2.39：没有金额权限时不显示金额列
    const has = (k) => cols.includes(k) && (k !== "transit" || r.items.some((x) => x.transit)) && (money || (k !== "cost" && k !== "value"));
    const zeroN = CAT ? ((cnt[CAT] || {}).zero || 0) : sum("zero");
    const head = `<tr><th>编码</th><th>名称</th>${CAT ? "" : "<th>分类</th>"}${has("brand") ? "<th>品牌 / 规格</th>" : ""}<th>库存</th>
      ${has("transit") ? "<th>在途</th>" : ""}${has("reorder") ? "<th>补货线</th>" : ""}${has("cost") ? "<th>平均单价</th>" : ""}${has("value") ? "<th>金额</th>" : ""}
      ${has("loc") ? `<th>${catalog || !window.INVZ ? "货位" : "分布在"}</th>` : ""}${catalog ? "<th>状态</th>" : ""}<th></th></tr>`;
    const row = (it) => `<tr class="${it.low ? "inv-low" : ""} ${it.active ? "" : "muted"}"><td class="mono" data-notr${it.category === "goods" ? ` data-p360="${esc(it.code)}"` : ""}>${esc(it.code)}</td>
        <td data-notr>${it.category === "filament" ? `<span class="sw" style="background:${esc(colorHex(it.color))}"></span>` : ""}${esc(itName(it))}</td>
        ${CAT ? "" : `<td>${esc(catName(it.category))}</td>`}${has("brand") ? `<td class="muted" data-notr>${esc([it.brand, it.spec].filter(Boolean).join(" · "))}</td>` : ""}
        <td class="nowrap">${qtyText(it)}${it.low ? ' <span class="bad">⚠</span>' : ""}</td>
        ${has("transit") ? `<td>${it.transit ? num(it.transit, 1) : ""}</td>` : ""}
        ${has("reorder") ? `<td>${it.reorder_point == null ? "" : num(it.reorder_point, 1)}</td>` : ""}
        ${has("cost") ? `<td>${it.avg_cost ? "฿" + num(it.avg_cost, it.unit === "g" ? 3 : 2) : ""}</td>` : ""}${has("value") ? `<td>${it.value ? "฿" + num(it.value, 0) : ""}</td>` : ""}
        ${has("loc") && !catalog && window.INVZ ? `<td class="small">${INVZ.split(it)}${it.unplaced > 1e-9 ? ` <span class="warn" title="${esc(Z("待上架", "รอจัดเก็บ"))}">📥${num(it.unplaced, 2)}</span>` : ""}</td>` : ""}
        ${has("loc") && (catalog || !window.INVZ) ? `<td class="mono small" data-notr>${it.location ? `<a href="#" data-locgo-code="${esc(it.location)}">${esc(it.location)}</a>` : ""}${it.loc_n > 1 ? ` <span class="muted" title="${esc(Z(`放在 ${it.loc_n} 个货位`, `อยู่ ${it.loc_n} ช่อง`))}">+${it.loc_n - 1}</span>` : ""}${it.unplaced > 1e-9 ? ` <span class="warn" title="${esc(Z("待上架", "รอจัดเก็บ"))}">📥${num(it.unplaced, 2)}</span>` : ""}</td>` : ""}
        ${catalog ? `<td class="small">${!it.active ? "已停用" : it.stocked ? (Math.abs(it.qty) > 1e-9 ? "有库存" : '<span class="muted">用完了</span>') : '<span class="muted">还没入过库</span>'}</td>` : ""}
        <td class="nowrap"><button class="mini" data-item="${it.id}">查看</button></td></tr>`;
    $("#inv-body").innerHTML = (!catalog && window.INVZ ? '<div id="inv-ov"></div>' : "") + `<div class="row gap wrap" style="margin-bottom:8px"><div class="chips" id="inv-cats">${chips}</div>
        <input id="inv-q" placeholder="搜索编码 / 名称 / 品牌" value="${esc(q)}" style="width:200px">
        ${!catalog && window.INVZ ? INVZ.zoneSelect(r.zones, ZONE) + `<input id="inv-locq" placeholder="${esc(Z("货位（A1、A1-02…）", "ตำแหน่ง (A1, A1-02…)"))}" value="${esc(LOCQ)}" style="width:130px" data-notr>` : ""}
        ${catalog ? `<select id="inv-sub"><option value="all" ${SUB === "all" ? "selected" : ""}>全部物品</option><option value="zero" ${SUB === "zero" ? "selected" : ""}>没有库存的</option>
          <option value="inactive" ${SUB === "inactive" ? "selected" : ""}>已停用的</option></select>` : money ? `<span class="muted small">库存金额 <b>฿${num(total, 0)}</b></span>` : ""}</div>
      <div class="inv-scroll"><table class="grid small"><thead>${head}</thead><tbody>` +
      (r.items.map(row).join("") || `<tr><td colspan="12" class="muted">${catalog ? "没有物品（点「＋ 新物品」建档）" : "现在没有库存。买了东西用「＋ 采购入库」，物品资料在「物品资料」里"}</td></tr>`) + "</tbody></table></div>" +
      (!catalog && zeroN ? `<p class="small muted"><span>没有库存的物品（从没入过库或已经用完）不显示在这里，请看</span> <a href="#" data-goiv="catalog">物品资料</a>（<b data-notr>${zeroN}</b>）</p>` : "");
    const qi = $("#inv-q"); let t = null;
    qi.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => renderItems().then(() => { const n = $("#inv-q"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }), 300); });
    const sb = $("#inv-sub"); if (sb) sb.onchange = () => { SUB = sb.value; renderItems(); };
    const zs = $("#inv-zone"); if (zs) zs.onchange = () => { ZONE = zs.value; renderItems(); };
    const lq = $("#inv-locq"); if (lq) lq.onchange = () => { LOCQ = lq.value.trim().toUpperCase(); renderItems(); };
    const ov = $("#inv-ov"); if (ov) INVZ.overview(ov).catch(() => {});
  }
  function colorHex(zh) { try { return (typeof COLORS !== "undefined" && COLORS[zh] && COLORS[zh].hex) || "#ccc"; } catch { return "#ccc"; } }

  // ---------------- 物品档案（新建 / 修改 / 查看流水） ----------------
  async function itemModal(id) {
    const r = id ? await api(`/api/inv/items/${id}`) : { item: { category: CAT || "part", unit: CAT === "filament" ? "g" : "个", active: 1 }, moves: [] };
    const it = r.item, fil = it.category === "filament", edit = can("inv.in");
    const f = (k, label, extra = "") => `<label>${label}<input data-k="${k}" value="${esc(it[k] ?? "")}" ${extra} ${edit ? "" : "disabled"}></label>`;
    const m = MODAL.open(`<h3>${id ? `<span data-notr>${esc(it.code)} ${esc(itName(it))}</span>` : "新物品"}</h3>
      <div class="form4">
        <label>分类<select data-k="category" ${id || !edit ? "disabled" : ""}>${(META.categories || []).filter((c) => id || c.id !== "goods").map((c) => `<option value="${esc(c.id)}" ${c.id === it.category ? "selected" : ""}>${esc(TH() ? c.th : c.zh)}</option>`).join("")}</select></label>
        ${f("name_zh", "名称（中文）")}${f("name_th", "名称（泰文）")}
        <label>单位<select data-k="unit" data-notr ${edit ? "" : "disabled"}>${(META.units || []).map((u) => `<option value="${esc(u)}" ${u === it.unit ? "selected" : ""}>${esc(uLab(u))}</option>`).join("")}</select></label>
        <span class="inv-fil ${fil ? "" : "hidden"}">${f("material", "材料（PLA / PETG…）", id ? "disabled" : "")}</span>
        <span class="inv-fil ${fil ? "" : "hidden"}">${f("color", "颜色（和产品颜色一致）", `list="color-list" ${id ? "disabled" : ""}`)}</span>
        <span class="inv-fil ${fil ? "" : "hidden"}">${f("loss_rate", "损耗率（空 = 用设置里的）", 'type="number" step="0.01"')}</span>
        ${f("brand", "品牌")}${f("spec", "规格")}${f("reorder_point", "补货线（低于就提醒）", 'type="number" step="any"')}
        ${f("reorder_qty", "每次补多少（空 = 自动）", 'type="number" step="any"')}
        <label>默认供应商<span class="row gap"><select data-k="supplier_id" data-notr ${edit ? "" : "disabled"}><option value="">—</option>${(SUPS || []).map((x) => `<option value="${x.id}" ${x.id === it.supplier_id ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select>
          ${id && window.MODKIT && MODKIT.enabled("pur") ? `<button type="button" class="mini" id="inv-pur" title="${TH() ? "ผู้ขาย ลิงก์ซื้อ ประวัติราคา" : "供应商、购买链接、价格历史、比价"}">🛒 ${TH() ? "ข้อมูลจัดซื้อ" : "采购资料"}</button>` : ""}</span></label>
        ${f("location", "货位（例如 A1-02-03，空 = 没有货位）", 'list="loc-dl" data-notr')}<datalist id="loc-dl" data-notr>${((window.INVLOC && INVLOC.list()) || []).map((l) => `<option value="${esc(l.code)}">${esc(INVLOC.human ? INVLOC.human(l.code) : "")}${l.items ? "" : (TH() ? " ·ว่าง" : " ·空")}</option>`).join("")}</datalist>${f("link", "购买链接")}${f("note", "备注")}
        <label>${Z("尺寸等级（放哪种货位）", "ขนาด (ใช้ช่องแบบไหน)")}<select data-k="size" ${edit ? "" : "disabled"}><option value="">${Z("不限", "ไม่จำกัด")}</option>
          ${["S", "M", "L", "XL"].map((x) => `<option value="${x}" ${((r.locs || {}).size || "") === x ? "selected" : ""}>${x} · ${esc(Z({ S: "小", M: "中", L: "大", XL: "特大" }[x], { S: "เล็ก", M: "กลาง", L: "ใหญ่", XL: "ใหญ่พิเศษ" }[x]))}</option>`).join("")}</select></label>
      </div>
      ${id && r.loc ? `<p class="small">📍 ${r.loc.code ? `<a href="#" data-locgo="${r.loc.id}" class="mono" data-notr>${esc(r.loc.code)}</a> <span data-notr>${esc(TH() ? r.loc.human_th : r.loc.human_zh)}</span> <span class="muted">${Z("（主货位）", "(ตำแหน่งหลัก)")}</span>`
        : `<span class="warn">还没有货位</span>${r.loc.suggest ? ` <span data-notr>（${esc(TH() ? "แนะนำ" : "推荐放")} <b class="mono">${esc(r.loc.suggest)}</b>）</span>` : ""}`}</p>` : ""}
      ${id && r.locs && (r.locs.locations.length > 1 || r.locs.unplaced > 1e-9) ? `<p class="small" data-notr>${esc(Z("放在：", "อยู่ที่: "))}${r.locs.locations.map((x) => `<a href="#" data-locgo="${x.id}" class="mono">${esc(x.code)}</a> ×${num(x.qty, 2)}`).join(" · ")}
        ${r.locs.unplaced > 1e-9 ? ` · <span class="warn">${esc(Z("待上架", "รอจัดเก็บ"))} ${num(r.locs.unplaced, 2)}</span>` : ""}</p>` : ""}
      ${id ? `<p class="small">${it.avg_cost === undefined ? (TH() ? `สต็อก ${qtyText(it)}` : `库存 ${qtyText(it)}`) : TH() ? `สต็อก ${qtyText(it)} · ราคาเฉลี่ย ฿${num(it.avg_cost, fil ? 3 : 2)} · มูลค่า ฿${num(it.value, 0)}` : `库存 ${qtyText(it)} · 平均单价 ฿${num(it.avg_cost, fil ? 3 : 2)} · 金额 ฿${num(it.value, 0)}`}
        ${edit ? `<label class="small"><input type="checkbox" data-k="active" ${it.active ? "checked" : ""}> 启用</label>` : ""}</p>` : ""}
      <div class="row gap">${edit ? '<button class="primary" id="inv-it-save">保存</button>' : ""}<button data-mclose>关闭</button></div>
      ${id ? `<h4>最近流水</h4>${movesTable(r.moves, false)}` : ""}`);
    m.classList.add("wide");
    const cs = m.querySelector('[data-k="category"]');
    cs.onchange = () => { const isF = cs.value === "filament"; m.querySelectorAll(".inv-fil").forEach((x) => x.classList.toggle("hidden", !isF)); if (isF) m.querySelector('[data-k="unit"]').value = "g"; };
    const pb = m.querySelector("#inv-pur");          // v2.51：物品的采购资料（采购模块）
    if (pb) pb.onclick = () => MODKIT.load("pur").then(() => window.PURPO && PURPO.itemDialog(id)).catch((e) => toast(e.message, true));
    const sv = m.querySelector("#inv-it-save");
    if (sv) sv.onclick = () => busy(sv, async () => {
      const d = { id: id || undefined };
      m.querySelectorAll("[data-k]").forEach((el) => { if (!el.disabled || el.dataset.k === "category") d[el.dataset.k] = el.type === "checkbox" ? (el.checked ? 1 : 0) : el.value; });
      if (id) delete d.category;
      if (d.category !== "filament") { delete d.material; delete d.color; delete d.loss_rate; }
      await api("/api/inv/items", { json: d });
      if (!id) { VIEW = "catalog"; SUB = "all"; }      // 新建的物品还没入库：在「物品资料」里
      toast(id ? "已保存" : "已建档（入库后会出现在「库存」里）"); MODAL.close(); load();
    });
  }

  // ---------------- 开单 ----------------
  const KIND_HINT = { purchase: "买来的东西入库：数量 + 单价（耗材可以按卷填）", return: "领用了没用完退回来", issue: "换喷嘴、用包材、试打……手动出库，可以写用在哪台打印机",
    scrap: "坏了、受潮、过期（要写原因）", adjust: "个别数字不对时直接改：正数加、负数减（要写原因）" };
  async function docModal(kind, pre) {
    if (!META) META = await api("/api/inv/meta");
    const all = (await api("/api/inv/items")).items;
    const opts = all.map((it) => `<option value="${it.id}" data-cat="${esc(it.category)}" data-unit="${esc(it.unit)}">${esc(it.code)} · ${esc(itName(it))}</option>`).join("");
    const row = () => `<tr><td><select data-l="item_id" data-notr><option value="">${TH() ? "เลือกรายการ" : "选物品"}</option>${opts}</select></td>
      <td><input data-l="qty" type="number" step="any" style="width:90px"> <span class="muted inv-unit"></span></td>
      ${kind === "purchase" ? `<td><input data-l="unit_cost" type="number" step="any" style="width:80px" placeholder="${TH() ? "ราคา" : "单价"}"></td>
        <td class="inv-roll hidden nowrap"><input data-l="rolls" type="number" step="1" style="width:50px" placeholder="${TH() ? "ม้วน" : "卷"}"> × <input data-l="net_g" type="number" value="1000" style="width:60px"> g
          <input data-l="brand" placeholder="${TH() ? "แบรนด์" : "品牌"}" style="width:70px"></td>` : ""}
      <td><input data-l="note" placeholder="${TH() ? "หมายเหตุ" : "备注"}" style="width:120px"></td><td><button class="mini danger" data-rmline>✕</button></td></tr>`;
    const m = MODAL.open(`<h3>${esc((META.doc_kinds || {})[kind])}</h3><p class="muted small">${KIND_HINT[kind] || ""}</p>
      <table class="grid small" id="inv-lines"><thead><tr><th>物品</th><th>数量</th>${kind === "purchase" ? "<th>单价（฿ / 单位）</th><th>耗材按卷</th>" : ""}<th>备注</th><th></th></tr></thead>
        <tbody>${row()}</tbody></table>
      <button class="mini" id="inv-addline">＋ 加一行</button>
      <div class="form4" style="margin-top:8px">
        ${kind === "issue" ? `<label>用在哪台打印机（可空）<select id="inv-printer"><option value="">—</option>${(META.printers || []).map((p) => `<option>${esc(p)}</option>`).join("")}</select></label>` : ""}
        <label>${kind === "scrap" || kind === "adjust" ? "原因（必填）" : "备注"}<input id="inv-note"></label></div>
      <div class="row gap"><button class="primary" id="inv-doc-ok">确认生效</button><button data-mclose>取消</button></div>`);
    m.classList.add("wide");
    const tb = m.querySelector("#inv-lines tbody");
    if (pre && pre.item_id) {                     // v2.35：从货位弹窗点「入库 / 出库」→ 物品先选好
      const sel = tb.querySelector('[data-l="item_id"]');
      sel.value = String(pre.item_id); sel.dispatchEvent(new Event("change", { bubbles: true }));
      const q = tb.querySelector('[data-l="qty"]'); if (q) setTimeout(() => q.focus(), 50);
    }
    m.querySelector("#inv-addline").onclick = () => tb.insertAdjacentHTML("beforeend", row());
    m.onclick = (e) => { if (e.target.dataset.rmline !== undefined && tb.rows.length > 1) e.target.closest("tr").remove(); };
    m.onchange = (e) => {
      if (e.target.dataset.l !== "item_id") return;
      const o = e.target.selectedOptions[0], tr = e.target.closest("tr");
      tr.querySelector(".inv-unit").textContent = o ? uLab(o.dataset.unit || "") : "";
      const rc = tr.querySelector(".inv-roll"); if (rc) rc.classList.toggle("hidden", !(o && o.dataset.cat === "filament"));
      const uc = tr.querySelector('[data-l="unit_cost"]'); if (uc) uc.placeholder = o && o.dataset.cat === "filament" ? "฿ / g" : (TH() ? "ราคา" : "单价");
    };
    const ok = m.querySelector("#inv-doc-ok");
    ok.onclick = () => busy(ok, async () => {
      const lines = [...tb.rows].map((tr) => { const d = {}; tr.querySelectorAll("[data-l]").forEach((el) => { if (el.value !== "") d[el.dataset.l] = el.value; }); return d; })
        .filter((d) => d.item_id);
      if (!lines.length) throw new Error("至少选一个物品");
      const r = await api("/api/inv/docs", { json: { kind, lines, note: m.querySelector("#inv-note").value, printer: (m.querySelector("#inv-printer") || {}).value || "" } });
      toast(`已生效：${r.doc.no}`); MODAL.close(); load();
    });
  }

  // ---------------- 纸箱（v2.35：泰国邮政标准纸箱，用量统计方便整箱采购）----------------
  async function renderBoxes() {
    const r = await api("/api/inv/boxes");
    $("#inv-body").innerHTML = `<p class="small muted">发货用的纸箱统一用邮政标准规格：在「编辑产品 → 包装纸箱」给每个产品选一种，订单发货时自动扣（打包页可以改）。
      第一次用到的规格会自动建档；这里看每种纸箱还有多少、最近用得多快，提前补货。</p>
      <table class="grid small" id="inv-box-t"><thead><tr><th>规格</th><th>尺寸 cm</th><th>库存</th><th>近 30 天用了</th><th>本月用了</th><th>每天约</th><th>还够</th><th>补货线</th><th>货位</th><th></th></tr></thead><tbody>
      ${r.boxes.map((b) => { const it = b.item; const low = it && it.reorder_point != null && it.qty <= it.reorder_point;
        return `<tr class="${low ? "inv-low" : ""} ${it ? "" : "muted"}"><td class="mono" data-notr><b>${esc(b.code)}</b></td><td data-notr>${esc(b.size)}</td>
        <td>${it ? `<b>${num(it.qty)}</b>${low ? ' <span class="bad">⚠</span>' : ""}` : '<span class="small">还没建档</span>'}</td>
        <td>${it ? num(b.used30) : ""}</td><td>${it ? num(b.used_month) : ""}</td><td>${it && b.daily ? num(b.daily, 1) : ""}</td>
        <td>${it && it.qty <= 0 ? `<span class="bad">${TH() ? "หมดแล้ว" : "没有了"}</span>` : it && b.days_left != null ? `<span class="${b.days_left < 7 ? "warn" : ""}">${b.days_left} ${TH() ? "วัน" : "天"}</span>` : ""}</td><td>${it && it.reorder_point != null ? num(it.reorder_point) : ""}</td>
        <td class="mono small" data-notr>${it ? esc(it.location || "") : ""}</td>
        <td class="nowrap">${it ? `${can("inv.in") ? `<button class="mini" data-boxin="${it.id}">＋ 入库</button>` : ""}<button class="mini" data-item="${it.id}">查看</button>`
          : can("inv.in") ? `<button class="mini" data-boxmk="${esc(b.code)}">建档</button>` : ""}</td></tr>`; }).join("")}</tbody></table>`;
  }

  // ---------------- 单据列表 ----------------
  async function renderDocs() {
    const r = await api("/api/inv/docs?days=180");
    $("#inv-body").innerHTML = `<table class="grid small"><thead><tr><th>单号</th><th>类型</th><th>状态</th><th>时间</th><th>经手</th><th>行数</th><th>金额</th><th>备注</th><th></th></tr></thead><tbody>` +
      (r.docs.map((d) => `<tr><td class="mono" data-notr>${esc(d.no)}</td><td>${esc(META.doc_kinds[d.kind] || d.kind)}</td>
        <td>${d.status === "void" ? '<span class="muted">已作废</span>' : d.status === "draft" ? '<span class="warn">草稿</span>' : "已生效"}</td>
        <td class="nowrap">${fmtTime(d.created_at)}</td><td data-notr>${esc(d.created_by || "")}</td><td>${d.lines_n}</td>
        <td>${d.amount ? "฿" + num(Math.abs(d.amount), 2) : ""}</td><td class="muted" data-notr>${esc(d.note || "")}</td>
        <td><button class="mini" data-doc="${d.id}">查看</button></td></tr>`).join("") || '<tr><td colspan="9" class="muted">还没有单据</td></tr>') + "</tbody></table>";
  }
  async function docView(id) {
    if (!META) META = await api("/api/inv/meta");          // 从订单详情直接打开出库单时，库存页可能还没打开过
    const d = (await api(`/api/inv/docs/${id}`)).doc;
    if (d.kind === "stocktake" && window.INVST) return INVST.open(d.id);      // v2.52：盘点在自己的页面      // v2.52：盘点在自己的页面
    const m = MODAL.open(`<h3><span data-notr>${esc(d.no)}</span> ${esc(META.doc_kinds[d.kind] || d.kind)}${d.status === "void" ? ' <span class="muted">（已作废）</span>' : ""}</h3>
      <p class="small muted"><span data-notr>${esc(d.created_by || "")}</span> · ${fmtTime(d.created_at)}${d.printer ? ` · <span data-notr>${esc(d.printer)}</span>` : ""}
        ${d.note ? ` · <span data-notr>${esc(d.note)}</span>` : ""}</p>
      <table class="grid small"><thead><tr><th>物品</th><th>数量</th>${d.kind === "stocktake" ? "<th>账面</th><th>实盘</th>" : "<th>单价</th>"}<th>备注</th></tr></thead><tbody>` +
      d.lines.map((l) => `<tr><td data-notr>${esc(l.code)} ${esc(TH() && l.name_th ? l.name_th : l.name_zh)}</td><td>${num(l.qty, 2)} <span data-notr>${esc(uLab(l.unit))}</span></td>
        ${d.kind === "stocktake" ? `<td>${num(l.expected, 2)}</td><td>${l.counted == null ? "" : num(l.counted, 2)}</td>` : `<td>${l.unit_cost == null ? "" : "฿" + num(l.unit_cost, 3)}</td>`}
        <td class="muted" data-notr>${esc(l.note || "")}</td></tr>`).join("") + `</tbody></table>
      <div class="row gap" style="margin-top:8px">${d.status === "done" && d.kind !== "stocktake" && can("inv.adjust") ? '<button class="danger" id="inv-void">作废（冲回）</button>' : ""}<button data-mclose>关闭</button></div>`);
    const v = m.querySelector("#inv-void");
    if (v) v.onclick = () => { if (!confirm("作废这张单？数量和金额都会冲回。")) return; busy(v, async () => { await api(`/api/inv/docs/${d.id}/void`, { method: "POST" }); toast("已作废"); MODAL.close(); load(); }); };
  }

  // ---------------- 流水 ----------------
  function movesTable(ms, withItem = true) {
    return `<table class="grid small"><thead><tr><th>时间</th>${withItem ? "<th>物品</th>" : ""}<th>类型</th><th>数量</th><th>结存</th><th>金额</th><th>说明</th><th>经手</th></tr></thead><tbody>` +
      (ms.map((x) => `<tr><td class="nowrap">${fmtTime(x.ts)}</td>${withItem ? `<td data-notr>${esc(x.code)} ${esc(TH() && x.name_th ? x.name_th : x.name_zh)}</td>` : ""}
        <td>${esc((META.kinds || {})[x.kind] || x.kind)}</td><td class="${x.qty < 0 ? "bad" : "ok"}">${x.qty > 0 ? "+" : ""}${num(x.qty, 2)} <span data-notr>${esc(uLab(x.unit))}</span></td>
        <td>${num(x.balance, 2)}</td><td>${x.amount ? "฿" + num(x.amount, 2) : ""}</td><td class="muted" data-notr>${esc(x.reason || "")}${x.printer ? " · " + esc(x.printer) : ""}</td>
        <td data-notr>${esc(x.username || "")}</td></tr>`).join("") || `<tr><td colspan="8" class="muted">没有记录</td></tr>`) + "</tbody></table>";
  }
  async function renderMoves() {
    const k = ($("#inv-mk") || {}).value || "";
    const r = await api(`/api/inv/moves?days=90&limit=500${k ? "&kind=" + k : ""}`);
    $("#inv-body").innerHTML = `<div class="row gap" style="margin-bottom:6px"><select id="inv-mk"><option value="">全部类型</option>${Object.entries(META.kinds).map(([a, b]) => `<option value="${a}" ${a === k ? "selected" : ""}>${esc(b)}</option>`).join("")}</select>
      <span class="muted small">最近 90 天</span></div>` + movesTable(r.moves);
    $("#inv-mk").onchange = renderMoves;
  }

  // ---------------- 支出统计 ----------------
  async function renderExpense() {
    const g = ($("#inv-eg") || {}).value || "category", p = ($("#inv-ep") || {}).value || "30";
    const now = new Date(), start = p === "month" ? new Date(now.getFullYear(), now.getMonth(), 1) : p === "last" ? new Date(now.getFullYear(), now.getMonth() - 1, 1) : new Date(Date.now() - Number(p) * 86400000);
    const end = p === "last" ? new Date(now.getFullYear(), now.getMonth(), 1) : new Date(Date.now() + 60000);
    const r = await api(`/api/inv/expense?group=${g}&start=${start.getTime() / 1000}&end=${end.getTime() / 1000}`);
    const lab = (x) => g === "category" ? catName(x.key) : g === "kind" ? ((META.kinds || {})[x.key] || x.key) : (TH() && x.label_th ? x.label_th : x.label);
    $("#inv-body").innerHTML = `<div class="row gap wrap" style="margin-bottom:6px">
        <select id="inv-ep"><option value="30" ${p === "30" ? "selected" : ""}>最近 30 天</option><option value="month" ${p === "month" ? "selected" : ""}>本月</option>
          <option value="last" ${p === "last" ? "selected" : ""}>上个月</option><option value="365" ${p === "365" ? "selected" : ""}>最近一年</option></select>
        <select id="inv-eg">${[["category", "按分类"], ["kind", "按类型"], ["item", "按物品"], ["printer", "按打印机"], ["month", "按月份"]].map(([a, b]) => `<option value="${a}" ${a === g ? "selected" : ""}>${b}</option>`).join("")}</select>
        <span>合计 <b>฿${num(r.total, 2)}</b></span></div>
      <p class="muted small">支出 = 生产消耗 + 生产损耗 + 打印失败 + 领用 + 报废 + 盘亏（盘盈抵减），按平均单价算金额。</p>
      <table class="grid small"><thead><tr><th></th><th>数量</th><th>金额</th><th>占比</th></tr></thead><tbody>` +
      (r.rows.map((x) => `<tr><td data-notr>${esc(lab(x))}</td><td data-notr>${g === "item" ? num(x.qty, 1) + " " + esc(uLab(x.unit)) : ""}</td><td>฿${num(x.amount, 2)}</td>
        <td>${r.total ? Math.round(100 * x.amount / r.total) + "%" : ""}</td></tr>`).join("") || '<tr><td colspan="4" class="muted">这段时间没有支出</td></tr>') + "</tbody></table>";
    $("#inv-ep").onchange = renderExpense; $("#inv-eg").onchange = renderExpense;
  }

  // ---------------- 事件 ----------------
  document.addEventListener("click", (e) => {     // 物品弹窗 / 列表里点货位编号 → 打开货位（v2.33）
    const lg = e.target.closest && e.target.closest("#modal-in [data-locgo], #tab-inventory [data-locgo-code]");
    if (!lg || !window.INVLOC) return;
    e.preventDefault();
    if (lg.dataset.locgo) return INVLOC.detail(+lg.dataset.locgo).catch((er) => toast(er.message, true));
    api(`/api/inv/locations/find?code=${encodeURIComponent(lg.dataset.locgoCode)}`).then((d) => d.location && INVLOC.detail(d.location.id, d)).catch((er) => toast(er.message, true));
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#tab-inventory")) return;
    const gv = e.target.closest("[data-goiv]"); if (gv) { e.preventDefault(); VIEW = gv.dataset.goiv; SUB = "zero"; return render(); }
    const v = e.target.closest("[data-iv]"); if (v) { VIEW = v.dataset.iv; return render(); }
    const c = e.target.closest("[data-cat]"); if (c && c.closest("#inv-cats")) { CAT = c.dataset.cat; return renderItems(); }
    const it = e.target.closest("[data-item]"); if (it) return itemModal(Number(it.dataset.item)).catch((er) => toast(er.message, true));
    const dk = e.target.closest("[data-newdoc]"); if (dk) return docModal(dk.dataset.newdoc).catch((er) => toast(er.message, true));
    const dv = e.target.closest("[data-doc]"); if (dv) return docView(Number(dv.dataset.doc)).catch((er) => toast(er.message, true));
    const bi = e.target.closest("[data-boxin]"); if (bi) return docModal("purchase", { item_id: +bi.dataset.boxin }).catch((er) => toast(er.message, true));
    const bm = e.target.closest("[data-boxmk]");
    if (bm) return busy(bm, async () => { await api(`/api/inv/boxes/${encodeURIComponent(bm.dataset.boxmk)}/item`, { method: "POST" }); toast(TH() ? "สร้างแล้ว" : "已建档"); renderBoxes(); });
    if (e.target.id === "inv-new-item") return itemModal(null).catch((er) => toast(er.message, true));
    if (e.target.id === "inv-reload") return load();
    if (e.target.id === "inv-presets") return busy(e.target, async () => { const r = await api("/api/inv/presets", { method: "POST" }); toast(TH() ? `เพิ่ม ${r.added} รายการ` : `新建了 ${r.added} 个常用物品`); load(); });
  });
  function openStocktake(id) { if (window.INVST) INVST.open(id); }
  window.INV = { show, load, docModal, itemModal, openStocktake, can, docView };
})();
