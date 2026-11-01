"use strict";
// 仓库 → 货位页的「列表」和「按商品」两种看法（v2.55）。货位图在 locations.js。
// 一行一个货位 / 一行一个商品；筛选、排序、搜索、分页都在服务端做（/api/inv/loc/list、/api/inv/loc/items），页面只画当前这一页（50 / 100 / 200 行）。
// 商品的数量文字一律用接口给的 qty_text / qty_text_th（modules/inv/qtytext.py），这里不自己拼单位。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const num = (v, d = 2) => (v == null || v === "" ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const nm = (x) => (TH() && x.name_th ? x.name_th : x.name_zh) || x.code || "";
  const qt = (x) => (TH() ? x.qty_text_th || x.qty_text : x.qty_text) || num(x.qty);
  const L = () => window.INVLOC;
  const can = (k) => !window.INV || !INV.can || INV.can(k);
  const ST = () => ({ empty: Z("空", "ว่าง"), partial: Z("有货", "มีของ"), full: Z("满", "เต็ม"), over: Z("超容量", "เกินความจุ") });
  const FLAG = () => ({ scattered: Z("太分散", "กระจายเกินไป"), unplaced: Z("没上架", "ยังไม่ได้จัดเก็บ"), noloc: Z("没货位", "ไม่มีตำแหน่ง"), low: Z("低于补货线", "ต่ำกว่าจุดสั่งซื้อ") });
  const DAY = 86400;
  let SIZE = 50;
  try { SIZE = +localStorage.getItem("inv_loc_size255") || 50; } catch { /* 忽略 */ }
  if (![50, 100, 200].includes(SIZE)) SIZE = 50;

  const S = {
    list: { q: "", zone: "", shelf: "", status: "", has: "", category: "", below_min: "", sort: "code", dir: "asc", page: 1 },
    item: { q: "", zone: "", shelf: "", category: "", flag: "", has: "", sort: "name", dir: "asc", page: 1 },
  };
  const KEYS = { list: ["q", "zone", "shelf", "status", "has", "category", "below_min", "sort", "dir", "page"], item: ["q", "zone", "shelf", "category", "flag", "has", "sort", "dir", "page"] };
  const FILTER_KEYS = { list: ["q", "zone", "shelf", "status", "has", "category", "below_min"], item: ["q", "zone", "shelf", "category", "flag", "has"] };
  const SEL = new Set();          // 列表里勾选的货位编号（翻页、换排序都保留）
  let SELALL = 0;                 // 「选中全部符合条件的」时的个数
  let SUM = null, KIND = "list", TOKEN = 0, LAST = null, TIMER = null;
  const SHELVES = {};             // 库区 → 货架汇总（筛选里选货架用）

  const imgOf = (x) => {
    if (x.img) return `<img class="lv-img" src="${esc(x.img)}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'lv-img lv-noimg'}))">`;
    if (x.category === "filament" && x.color) return `<span class="lv-img lv-sw" style="background:${esc(colorHex(x.color))}"></span>`;
    return `<span class="lv-img lv-noimg">${esc((x.category === "goods" ? "▣" : x.category === "pack" ? "▤" : x.category === "part" ? "⚙" : "◻"))}</span>`;
  };
  function colorHex(zh) { try { return (typeof COLORS !== "undefined" && COLORS[zh] && COLORS[zh].hex) || "#94a3b8"; } catch { return "#94a3b8"; } }
  function ago(ts) {
    if (!ts) return "";
    const s = Date.now() / 1000 - ts;
    if (s < 3600) return Z(`${Math.max(1, Math.round(s / 60))} 分钟前`, `${Math.max(1, Math.round(s / 60))} นาทีที่แล้ว`);
    if (s < DAY) return Z(`${Math.round(s / 3600)} 小时前`, `${Math.round(s / 3600)} ชม.ที่แล้ว`);
    const d = Math.round(s / DAY);
    return d < 60 ? Z(`${d} 天前`, `${d} วันที่แล้ว`) : Z(`${Math.round(d / 30)} 个月前`, `${Math.round(d / 30)} เดือนที่แล้ว`);
  }
  const when = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : "");
  const qs = (kind, extra) => {
    const s = S[kind], p = new URLSearchParams();
    KEYS[kind].forEach((k) => { if (s[k] !== "" && s[k] != null) p.set(k, s[k]); });
    p.set("size", SIZE);
    Object.entries(extra || {}).forEach(([k, v]) => p.set(k, v));
    return p.toString();
  };

  // ---------------- 工具条 ----------------
  function toolbar(kind) {
    const s = S[kind];
    const zones = (SUM && SUM.zones) || [];
    const cats = L().cats();
    const sel = (id, val, opts, cls = "") => `<select id="${id}" class="${cls}" data-notr>${opts.map(([v, t]) => `<option value="${esc(v)}" ${String(v) === String(val) ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
    const shelfOpts = [["", Z("全部货架", "ทุกแร็ค")], ...((SHELVES[s.zone] || []).map((x) => [x.shelf, `${x.shelf}${x.name ? " · " + x.name : ""}`]))];
    const ztn = (t) => L().ztName(t);
    return `<div class="lv-bar row gap wrap">
      <input id="lv-q" type="search" class="lv-qin" value="${esc(s.q)}" autocomplete="off" data-notr
        placeholder="${esc(kind === "list" ? Z("搜索：货位编号 / 商品名称 / SKU / 条码", "ค้นหา: รหัสตำแหน่ง / ชื่อสินค้า / SKU / บาร์โค้ด") : Z("搜索：商品名称 / SKU / 条码 / 货位", "ค้นหา: ชื่อสินค้า / SKU / บาร์โค้ด / ตำแหน่ง"))}">
      ${sel("lv-zone", s.zone, [["", Z("全部库区", "ทุกโซน")], ...zones.map((z) => [z.zone, `${z.zone} · ${ztn(z.ztype)}${z.name ? " · " + z.name : ""}`])])}
      <select id="lv-shelf" ${s.zone ? "" : "disabled"} data-notr>${shelfOpts.map(([v, t]) => `<option value="${esc(v)}" ${v === s.shelf ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
      ${kind === "list" ? sel("lv-status", s.status, [["", Z("全部状态", "ทุกสถานะ")], ["empty", Z("空", "ว่าง")], ["partial", Z("有货", "มีของ")], ["full", Z("满", "เต็ม")], ["over", Z("超容量", "เกินความจุ")], ["low", Z("低于补货线", "ต่ำกว่าจุดสั่งซื้อ")]])
        : sel("lv-flag", s.flag, [["", Z("全部商品", "ทุกสินค้า")], ["scattered", Z("太分散", "กระจายเกินไป")], ["unplaced", Z("没上架", "ยังไม่ได้จัดเก็บ")], ["noloc", Z("没有货位", "ไม่มีตำแหน่ง")], ["low", Z("低于补货线", "ต่ำกว่าจุดสั่งซื้อ")]])}
      ${sel("lv-cat", s.category, [["", Z("全部分类", "ทุกหมวด")], ...cats.map((c) => [c.id, TH() ? c.th : c.zh])])}
      ${sel("lv-has", s.has, [["", kind === "list" ? Z("空 / 非空", "ว่าง / ไม่ว่าง") : Z("有货 / 没货", "มี / ไม่มี")], ["nonempty", kind === "list" ? Z("只看有货的", "เฉพาะที่มีของ") : Z("只看有库存的", "เฉพาะที่มีสต็อก")], ["empty", kind === "list" ? Z("只看空的", "เฉพาะที่ว่าง") : Z("只看没库存的", "เฉพาะที่ไม่มีสต็อก")]])}
      ${kind === "list" ? `<label class="small nowrap lv-chk"><input type="checkbox" id="lv-min" ${s.below_min ? "checked" : ""}> ${esc(Z("低于最低数量", "ต่ำกว่าขั้นต่ำ"))}</label>` : ""}
      <button class="mini" id="lv-clear">${esc(Z("清除筛选", "ล้างตัวกรอง"))}</button></div>
      <div id="lv-sel"></div><div id="lv-body"></div>`;
  }

  // ---------------- 列表：一行一个货位 ----------------
  const itemLine = (x) => `<div class="lv-it"><span class="lv-imgw">${imgOf(x)}</span><span class="lv-itx"><span class="lv-nm" data-notr>${esc(nm(x))}</span>
    <span class="lv-sku mono" data-notr>${esc(x.code)}${x.primary ? " ★" : ""}${x.low ? ' <b class="bad">⚠</b>' : ""}</span></span><b class="lv-q" data-notr>${esc(qt(x))}</b></div>`;
  function contents(l) {
    const its = l.items || [];
    if (!its.length) return `<span class="muted">${esc(Z("空", "ว่าง"))}</span>`;
    const more = its.slice(2);
    const extra = Math.max(0, (l.n_items || its.length) - 2);
    return its.slice(0, 2).map(itemLine).join("") +
      (extra ? `<button type="button" class="lv-more" data-more="${l.id}">${esc(Z(`+${extra} 种`, `+${extra} รายการ`))}</button><div class="lv-rest hidden" data-rest="${l.id}">${more.map(itemLine).join("")}</div>` : "");
  }
  function capCell(l) {
    if (l.capacity == null) return `<b data-notr>${num(l.total)}</b> <span class="muted small">${esc(Z("不限", "ไม่จำกัด"))}</span>`;
    const pct = l.util == null ? 0 : Math.min(100, l.util);
    return `<b data-notr>${num(l.total)} / ${num(l.capacity)}</b> <span class="small muted" data-notr>${num(l.util, 0)}%</span>
      <span class="lv-meter"><i class="${l.state === "over" ? "ux-bad" : l.state === "full" ? "ux-info" : "ux-ok"}" style="width:${Math.max(2, pct)}%"></i></span>`;
  }
  function stateCell(l) {
    const S_ = ST();
    return `<span class="lg-in st-${esc(l.state)}">${esc(S_[l.state] || "")}</span>${l.below_min ? ` <span class="lv-tag warn" title="${esc(Z(`低于最低数量 ${num(l.min_qty)}`, `ต่ำกว่าขั้นต่ำ ${num(l.min_qty)}`))}">⚠ ${esc(Z("低于补货线", "ต่ำกว่าจุดสั่งซื้อ"))}</span>` : ""}`;
  }
  const th = (kind, key, zh, thai, cls = "") => {
    const s = S[kind], on = s.sort === key;
    return `<th class="lv-th ${cls}" data-sort="${key}" title="${esc(Z("点一下排序", "คลิกเพื่อเรียง"))}">${esc(Z(zh, thai))}<i class="lv-arr">${on ? (s.dir === "desc" ? "▼" : "▲") : ""}</i></th>`;
  };
  function listTable(r) {
    const all = r.rows.length && r.rows.every((l) => SEL.has(l.code));
    const rows = r.rows.map((l) => `<tr class="lv-row ${l.low ? "lv-low" : ""}" data-lid="${l.id}" data-code="${esc(l.code)}">
      <td class="lv-ck"><input type="checkbox" data-pick="${esc(l.code)}" ${SEL.has(l.code) ? "checked" : ""}></td>
      <td class="nowrap"><b class="mono lv-code" data-notr>${esc(l.code)}</b>${l.fixed_item ? " 📌" : ""}</td>
      <td class="nowrap small" data-notr><b>${esc(l.zone)}</b> <span class="loc-zt zt-${esc(l.ztype)}">${esc(L().ztName(l.ztype))}</span></td>
      <td class="nowrap small" data-notr>${esc(l.shelf_code || "")} · ${esc(Z(`${l.layer} 层`, `ชั้น ${l.layer}`))} · ${esc(Z(`${l.pos} 位`, `ช่อง ${l.pos}`))}</td>
      <td class="lv-cont">${contents(l)}</td><td class="nowrap lv-cap">${capCell(l)}</td><td class="nowrap">${stateCell(l)}</td>
      <td class="nowrap small muted" title="${esc(when(l.last_move))}" data-notr>${esc(ago(l.last_move))}</td></tr>`).join("");
    return `<div class="lv-wrap"><table class="grid lv-tbl"><thead><tr><th class="lv-ck"><input type="checkbox" id="lv-all" ${all ? "checked" : ""}></th>
      ${th("list", "code", "货位", "ตำแหน่ง")}${th("list", "zone", "库区", "โซน")}<th>${esc(Z("货架 / 层 / 位", "แร็ค / ชั้น / ช่อง"))}</th>
      ${th("list", "contents", "里面的商品", "สินค้าในช่อง")}${th("list", "util", "容量 / 占用", "ความจุ / การใช้")}${th("list", "state", "状态", "สถานะ")}${th("list", "last_move", "最后动", "เคลื่อนไหวล่าสุด")}
      </tr></thead><tbody>${rows || `<tr><td colspan="8">${UX.empty(Z("没有符合条件的货位", "ไม่มีตำแหน่งที่ตรงเงื่อนไข"))}</td></tr>`}</tbody></table></div>`;
  }

  // ---------------- 按商品：一行一个商品 ----------------
  function distribution(x) {
    if (!x.locs.length) return `<span class="muted">${esc(Z("没有货位", "ไม่มีตำแหน่ง"))}</span>`;
    const chip = (d) => `<span class="lv-dist" data-loccode="${esc(d.code)}" data-notr><b class="mono">${esc(d.code)}</b> ×${esc(qt(d))}${d.primary ? " ★" : ""}</span>`;
    const first = x.locs.slice(0, 3), rest = x.locs.slice(3);
    return first.map(chip).join(" · ") + (rest.length ? ` <button type="button" class="lv-more" data-more="i${x.id}">${esc(Z(`+${rest.length} 处`, `+${rest.length} ที่`))}</button>
      <div class="lv-rest hidden" data-rest="i${x.id}">${rest.map(chip).join(" · ")}</div>` : "");
  }
  function itemTable(r) {
    const F = FLAG();
    const rows = r.rows.map((x) => `<tr class="lv-row ${x.low ? "lv-low" : ""}" data-iid="${x.id}">
      <td class="lv-imgc">${imgOf(x)}</td>
      <td><span class="lv-nm" data-notr>${esc(nm(x))}</span><span class="lv-sku mono" data-notr>${esc(x.code)}</span></td>
      <td class="nowrap small">${esc(catName(x.category))}</td><td class="nowrap"><b data-notr>${esc(qt(x))}</b></td>
      <td class="lv-dists">${distribution(x)}</td>
      <td class="lv-flags">${x.flags.filter((f) => f !== "low" || x.low).map((f) => `<span class="lv-tag ${f === "scattered" || f === "unplaced" || f === "low" ? "warn" : "muted"}">${esc(F[f])}${f === "unplaced" ? " " + esc(TH() ? x.unplaced_text_th : x.unplaced_text) : f === "scattered" ? ` ${x.nloc}` : ""}</span>`).join(" ")}</td></tr>`).join("");
    return `<div class="lv-wrap"><table class="grid lv-tbl"><thead><tr><th class="lv-imgc"></th>${th("item", "name", "商品", "สินค้า")}${th("item", "category", "分类", "หมวด")}
      ${th("item", "qty", "总数", "รวม")}${th("item", "locs", "分布在哪些货位", "กระจายอยู่ที่ตำแหน่ง")}<th>${esc(Z("标记", "ธง"))}</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="6">${UX.empty(Z("没有符合条件的商品", "ไม่มีสินค้าที่ตรงเงื่อนไข"))}</td></tr>`}</tbody></table></div>`;
  }
  const catName = (id) => { const c = (L().cats() || []).find((x) => x.id === id); return c ? (TH() ? c.th : c.zh) : id; };

  // ---------------- 翻页 ----------------
  function pager(r) {
    const from = r.total ? (r.page - 1) * r.size + 1 : 0, to = Math.min(r.total, r.page * r.size);
    const b = (a, t, dis) => `<button class="mini" data-pg="${a}" ${dis ? "disabled" : ""}>${t}</button>`;
    return `<div class="lv-pager row gap wrap between"><span class="small muted" data-notr>${esc(Z(`共 ${num(r.total, 0)} 条 · 第 ${from}–${to} 条`, `ทั้งหมด ${num(r.total, 0)} รายการ · ${from}–${to}`))}</span>
      <span class="row gap">${b("first", "«", r.page <= 1)}${b("prev", "‹", r.page <= 1)}<span class="small" data-notr>${r.page} / ${r.pages}</span>${b("next", "›", r.page >= r.pages)}${b("last", "»", r.page >= r.pages)}
      <select id="lv-size" data-notr>${[50, 100, 200].map((n) => `<option value="${n}" ${n === r.size ? "selected" : ""}>${esc(Z(`每页 ${n}`, `${n} ต่อหน้า`))}</option>`).join("")}</select></span></div>`;
  }

  // ---------------- 批量条 ----------------
  function selBar() {
    const box = document.getElementById("lv-sel"); if (!box) return;
    if (KIND !== "list" || !SEL.size) { box.innerHTML = ""; return; }
    const n = SEL.size;
    const more = LAST && LAST.total > n && !SELALL && LAST.rows.every((l) => SEL.has(l.code))
      ? ` <a href="#" data-selall="1">${esc(Z(`选中全部 ${num(LAST.total, 0)} 个符合条件的货位`, `เลือกทั้งหมด ${num(LAST.total, 0)} ตำแหน่งที่ตรงเงื่อนไข`))}</a>` : "";
    box.innerHTML = `<div class="lv-selbar row gap wrap"><b data-notr>${esc(Z(`已选 ${num(n, 0)} 个货位`, `เลือกแล้ว ${num(n, 0)} ตำแหน่ง`))}</b>${more}
      ${can("inv.in") ? `<button class="mini" data-bulk="move">${esc(Z("↔ 移库", "↔ ย้าย"))}</button>` : ""}
      <button class="mini" data-bulk="labels">${esc(Z("🏷 打印标签", "🏷 พิมพ์ป้าย"))}</button>
      ${can("inv.in") ? `<button class="mini" data-bulk="props">${esc(Z("⚙ 货位设置", "⚙ ตั้งค่าช่อง"))}</button>` : ""}
      ${can("inv.out") ? `<button class="mini" data-bulk="stocktake">${esc(Z("🧮 加入盘点", "🧮 เพิ่มในการตรวจนับ"))}</button>` : ""}
      <button class="mini" data-bulk="clear">${esc(Z("清除选择", "ล้างที่เลือก"))}</button></div>`;
  }
  async function codesToAct(max) {
    if (SELALL && LAST) {
      const r = await api(`/api/inv/loc/codes?${qs("list")}`);
      return r.codes.slice(0, max || 3000);
    }
    return [...SEL];
  }
  async function bulk(act) {
    if (act === "clear") { SEL.clear(); SELALL = 0; return refresh(); }
    const codes = await codesToAct(act === "move" ? 500 : 3000);
    if (!codes.length) return;
    if (act === "labels") {
      const lang = TH() ? "&lang=th" : "";
      const url = SELALL ? `/print/inv-locations?flt=1&${qs("list").replace(/&?(sort|dir|page|size)=[^&]*/g, "")}${lang}` : `/print/inv-locations?codes=${encodeURIComponent(codes.join(","))}${lang}`;
      return void window.open(url, "_blank");
    }
    if (act === "stocktake") {
      try { const d = (await api("/api/inv/stocktake", { json: { area: codes.join(",") } })).doc; if (window.INV && INV.openStocktake) INV.openStocktake(d.id); }
      catch (e) { toast(e.message, true); }
      return;
    }
    if (act === "props") {
      const m = MODAL.open(`<h3>${esc(Z(`货位设置（${codes.length} 个货位）`, `ตั้งค่าช่อง (${codes.length} ตำแหน่ง)`))}</h3>
        <p class="small muted">${esc(Z("只改填了的项，不填的保持原样。", "แก้เฉพาะช่องที่กรอก ช่องที่เว้นไว้ไม่เปลี่ยน"))}</p>${L().propsForm({ mixed: undefined, size: "" }, true)}
        <div class="row gap" style="margin-top:8px"><button class="primary" id="bp-ok">${esc(Z("保存", "บันทึก"))}</button><button data-mclose>${esc(Z("取消", "ยกเลิก"))}</button></div>`);
      m.querySelector("#bp-ok").onclick = () => busy(m.querySelector("#bp-ok"), async () => {
        const p = L().readProps(m, true);
        await api("/api/inv/locations/props", { json: { codes, props: p } });
        toast(Z("已保存", "บันทึกแล้ว")); MODAL.close(); refresh(true);
      });
      return;
    }
    if (act === "move") {
      const m = MODAL.open(`<h3>${esc(Z(`↔ 移库（${codes.length} 个货位）`, `↔ ย้ายตำแหน่ง (${codes.length} ช่อง)`))}</h3>
        <p class="small muted">${esc(Z("把选中的货位里的东西全部搬到下面这个货位（搬不了的会列出原因，别的照搬）。", "ย้ายของทั้งหมดในช่องที่เลือกไปยังช่องนี้ (ที่ย้ายไม่ได้จะแสดงเหตุผล ที่เหลือย้ายตามปกติ)"))}</p>
        <label>${esc(Z("目标货位", "ช่องปลายทาง"))} ${L().locPick('id="bm-to" data-notr', "", Z("选货位", "เลือกช่อง"))}</label>
        <label class="small nowrap"><input type="checkbox" id="bm-force"> ${esc(Z("超容量也放", "วางแม้เกินความจุ"))}</label><div id="bm-res"></div>
        <div class="row gap" style="margin-top:8px"><button class="primary" id="bm-ok">${esc(Z("搬过去", "ย้าย"))}</button><button data-mclose>${esc(Z("关闭", "ปิด"))}</button></div>`);
      m.querySelector("#bm-ok").onclick = () => busy(m.querySelector("#bm-ok"), async () => {
        const to = m.querySelector("#bm-to").value.trim();
        if (!to) return toast(Z("先选要移到的货位", "เลือกช่องปลายทางก่อน"), true);
        const r = await api("/api/inv/loc/bulk", { json: { action: "move", codes, to, force: m.querySelector("#bm-force").checked } });
        m.querySelector("#bm-res").innerHTML = `<p class="small">${esc(Z(`搬了 ${r.done} 个货位（${r.moved} 种商品）到 ${r.to}`, `ย้าย ${r.done} ช่อง (${r.moved} รายการ) ไป ${r.to}`))}</p>` +
          (r.errors.length ? `<ul class="small bad" data-notr>${r.errors.slice(0, 20).map((e) => `<li>${esc(e.code)}：${esc(e.error)}</li>`).join("")}</ul>` : "");
        toast(Z(`已搬 ${r.done} 个货位`, `ย้ายแล้ว ${r.done} ช่อง`), !!r.errors.length);
        SEL.clear(); SELALL = 0; refresh(true);
      });
    }
  }

  // ---------------- 读数据 + 画 ----------------
  async function load() {
    const body = document.getElementById("lv-body"); if (!body) return;
    const my = ++TOKEN;
    body.classList.add("lv-busy");
    let r;
    try { r = await api(`/api/inv/loc/${KIND === "list" ? "list" : "items"}?${qs(KIND)}`); }
    catch (e) { if (my === TOKEN) { body.classList.remove("lv-busy"); toast(e.message, true); } return; }
    if (my !== TOKEN) return;
    LAST = r;
    S[KIND].page = r.page;
    body.classList.remove("lv-busy");
    body.innerHTML = (KIND === "list" ? listTable(r) : itemTable(r)) + pager(r);
    selBar();
  }
  async function fillShelves(zone) {
    if (!zone || SHELVES[zone]) return;
    try { SHELVES[zone] = (await api(`/api/inv/loc/map?zone=${encodeURIComponent(zone)}`)).shelves || []; } catch { SHELVES[zone] = []; }
  }
  function refresh(summaryToo) {
    if (summaryToo && window.INVLOC) INVLOC.reloadSummary();
    return load();
  }

  function render(kind, box, summary) {
    KIND = kind; SUM = summary; SELALL = 0;
    box.innerHTML = toolbar(kind);
    const s = S[kind];
    const upd = (patch, now) => {
      Object.assign(s, patch, { page: patch.page || 1 });
      if ("zone" in patch) { s.shelf = ""; fillShelves(s.zone).then(() => { const sh = document.getElementById("lv-shelf"); if (sh) { sh.disabled = !s.zone; sh.innerHTML = [["", Z("全部货架", "ทุกแร็ค")], ...((SHELVES[s.zone] || []).map((x) => [x.shelf, `${x.shelf}${x.name ? " · " + x.name : ""}`]))].map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join(""); } }); }
      if ("q" in patch && !now) { clearTimeout(TIMER); TIMER = setTimeout(load, 250); } else { clearTimeout(TIMER); load(); }
    };
    box.oninput = (e) => { if (e.target.id === "lv-q") upd({ q: e.target.value.trim() }); };
    box.onchange = (e) => {
      const t = e.target;
      if (t.id === "lv-zone") upd({ zone: t.value }); else if (t.id === "lv-shelf") upd({ shelf: t.value });
      else if (t.id === "lv-status") upd({ status: t.value }); else if (t.id === "lv-flag") upd({ flag: t.value });
      else if (t.id === "lv-cat") upd({ category: t.value }); else if (t.id === "lv-has") upd({ has: t.value });
      else if (t.id === "lv-min") upd({ below_min: t.checked ? "1" : "" });
      else if (t.id === "lv-size") { SIZE = +t.value; try { localStorage.setItem("inv_loc_size255", SIZE); } catch { /* 忽略 */ } upd({}); }
      else if (t.id === "lv-all") { LAST.rows.forEach((l) => (t.checked ? SEL.add(l.code) : SEL.delete(l.code))); SELALL = 0; box.querySelectorAll("[data-pick]").forEach((c) => { c.checked = t.checked; }); selBar(); }
      else if (t.dataset.pick) { t.checked ? SEL.add(t.dataset.pick) : SEL.delete(t.dataset.pick); SELALL = 0; selBar(); const a = document.getElementById("lv-all"); if (a) a.checked = LAST.rows.every((l) => SEL.has(l.code)); }
    };
    box.onclick = (e) => {
      const t = e.target;
      if (t.closest(".lv-ck")) return;
      const sb = t.closest("[data-sort]");
      if (sb) { const k = sb.dataset.sort; s.dir = s.sort === k && s.dir === "asc" ? "desc" : "asc"; s.sort = k; s.page = 1; return void load().then(() => 0); }
      const pg = t.closest("[data-pg]");
      if (pg) { const a = pg.dataset.pg, last = LAST.pages; s.page = a === "first" ? 1 : a === "prev" ? s.page - 1 : a === "next" ? s.page + 1 : last; return void load(); }
      if (t.id === "lv-clear") { FILTER_KEYS[kind].forEach((k) => { s[k] = ""; }); s.page = 1; SEL.clear(); return void render(kind, box, SUM) || load(); }
      const sa = t.closest("[data-selall]");
      if (sa) { e.preventDefault(); SELALL = LAST.total; SEL.clear(); return void api(`/api/inv/loc/codes?${qs("list")}`).then((r) => { r.codes.forEach((c) => SEL.add(c)); SELALL = r.total; selBar(); document.querySelector("#lv-sel b").textContent = Z(`已选 ${num(r.total, 0)} 个货位（全部符合条件的）`, `เลือกแล้ว ${num(r.total, 0)} ตำแหน่ง (ทั้งหมดที่ตรงเงื่อนไข)`); }); }
      const bk = t.closest("[data-bulk]");
      if (bk) return void bulk(bk.dataset.bulk).catch((er) => toast(er.message, true));
      const mo = t.closest("[data-more]");
      if (mo) { e.stopPropagation(); const rest = box.querySelector(`[data-rest="${mo.dataset.more}"]`); if (rest) { rest.classList.toggle("hidden"); mo.classList.toggle("on"); } return; }
      const lc = t.closest("[data-loccode]");
      if (lc) return void openCode(lc.dataset.loccode);
      const row = t.closest("tr.lv-row");
      if (row && row.dataset.lid) return void L().detail(+row.dataset.lid).catch((er) => toast(er.message, true));
      if (row && row.dataset.iid && window.INV) return void INV.itemModal(+row.dataset.iid).catch((er) => toast(er.message, true));
    };
    fillShelves(s.zone).then(() => { if (s.zone) { const sh = document.getElementById("lv-shelf"); if (sh) { sh.disabled = false; sh.innerHTML = [["", Z("全部货架", "ทุกแร็ค")], ...((SHELVES[s.zone] || []).map((x) => [x.shelf, `${x.shelf}${x.name ? " · " + x.name : ""}`]))].map(([v, t]) => `<option value="${esc(v)}" ${v === s.shelf ? "selected" : ""}>${esc(t)}</option>`).join(""); } } });
    return load();
  }
  function openCode(code) {
    return api(`/api/inv/locations/find?code=${encodeURIComponent(code)}`).then((d) => d.location && L().detail(d.location.id)).catch((er) => toast(er.message, true));
  }
  // 扫码 / 外面要看某个商品：切到「按商品」并搜它（INVLOC 调）
  function focusItem(code) { S.item.q = code; S.item.page = 1; }

  window.INVLV = { render, refresh, focusItem, filters: S, selection: () => [...SEL] };
})();
