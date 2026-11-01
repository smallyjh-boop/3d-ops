"use strict";
// 仓库 → 货位（v2.33 建；v2.35 一物一位；v2.52 仓库 → 库区 → 货架 → 层 → 位，按货位记数量，参考 BigSeller WMS）。
// 页面：数字卡片（货位、占用率、空位、满 / 超容量、待上架、补货任务）→ 各库区利用率 → 页签：货位图 / 待上架 / 补货·移库 / 提醒。
// 货位图按 库区 → 货架 画：一行一层、一格一位，颜色 = 空 / 有货 / 满 / 超容量；点格子看里面有什么、移库、上架、设置容量 / 固定物品。
// 待上架、补货·移库、提醒三个页签在 wms.js。
// v2.55：三种看法 列表 | 按商品 | 货位图（默认列表，记住上次选的）。列表 / 按商品在 locviews.js（服务端分页 / 筛选 / 排序 / 搜索）；
// 货位图只画选中的库区 / 货架（货位多的时候），别的库区、货架只显示一行汇总；点一行 / 一格 → 右边抽屉（里面的商品、出入库记录、操作）。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const num = (v, d = 2) => (v == null || v === "" ? "" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
  const itName = (it) => (TH() && it.name_th ? it.name_th : it.name_zh) || "";
  const pad = (n) => String(n).padStart(2, "0");
  const U_TH = { "个": "ชิ้น", "卷": "ม้วน", "张": "แผ่น", "件": "ชิ้น", "米": "เมตร", "瓶": "ขวด", "盒": "กล่อง", "套": "ชุด" };
  const uLab = (u) => (TH() && U_TH[u]) || u || "";
  let LOCS = [], GROUPS = {}, CATS = [], BOTTOM = true, WHS = [], ZT = {}, SIZES = {}, PENDING = 0;
  let MAP = null, SUB = "list", WH = "", ZONE = "", SHELF = "";
  let BIG = false, ZONES_ALL = [], MAXSHELF = {}, SHELVES_BIG = [];
  const OPEN = new Set(), CACHE = {};            // 货位图：展开的货架、读过的货架格子
  const VIEWS = ["list", "item", "map"];
  try { const v = localStorage.getItem("inv_loc_view255"); if (VIEWS.includes(v)) SUB = v; } catch { /* 忽略 */ }
  const BOX = () => $("#loc-page");

  async function loadLocs() {
    const r = await api("/api/inv/locations");
    LOCS = r.locations; GROUPS = r.groups || {}; CATS = r.categories || []; BOTTOM = r.layer_bottom !== false;
    BIG = !!r.big; ZONES_ALL = r.zones || []; MAXSHELF = r.max_shelf || {}; SHELVES_BIG = r.shelves || [];
    WHS = r.warehouses || []; ZT = r.ztypes || {}; SIZES = r.sizes || {}; PENDING = r.unassigned || 0;
    return r;
  }
  const shelfOf = (l) => (l.shelf != null ? `${l.zone}${l.shelf}` : "");
  const human = (code) => {
    const m = /^([A-Z]{1,2})(\d{1,2})-(\d{2})-(\d{2})$/.exec(code || "");
    if (!m) return code || "";
    return Z(`${m[1]}区 ${+m[2]}号货架 第${+m[3]}层 第${+m[4]}位`, `โซน ${m[1]} แร็ค ${+m[2]} ชั้น ${+m[3]} ช่อง ${+m[4]}`);
  };
  const ztName = (t) => (ZT[t] ? (TH() ? ZT[t][1] : ZT[t][0]) : "");
  const sizeName = (s) => (SIZES[s] ? `${s} · ${TH() ? SIZES[s][1] : SIZES[s][0]}` : "");
  const whLabel = (n) => (n === "默认仓库" ? Z("默认仓库", "คลังเริ่มต้น") : n || "");      // 系统建的默认仓库名跟着界面语言
  const whName = (id) => whLabel((WHS.find((w) => w.id === id) || {}).name || "");
  const zoneInfo = (z) => { const g = GROUPS[z] || {}; return { ztype: g.ztype || "pick", warehouse: g.warehouse || (WHS[0] || {}).id, name: g.name || "", categories: g.categories || [] }; };
  const catName = (id) => { const c = CATS.find((x) => x.id === id); return c ? (TH() ? c.th : c.zh) : id; };
  const catChips = (g) => (g && g.categories && g.categories.length
    ? `<span class="loc-cats" data-notr>${esc(Z("放：", "เก็บ: "))}${g.categories.map((c) => esc(catName(c))).join(Z("、", ", "))}</span>` : "");
  const locOpts = (sel = "", withNone = "", skip = "") => {
    const opt = (l) => `<option value="${esc(l.code)}" ${sel === l.code ? "selected" : ""}>${esc(l.code)}${l.items ? "" : Z(" ·空", " ·ว่าง")}</option>`;
    const by = {};
    LOCS.filter((l) => l.code !== skip).forEach((l) => (by[shelfOf(l) || "~"] = by[shelfOf(l) || "~"] || []).push(l));
    return (withNone ? `<option value="">${esc(withNone)}</option>` : "") + Object.entries(by).map(([sc, ls]) =>
      `<optgroup label="${esc(sc === "~" ? Z("其他货位", "ช่องอื่นๆ") : `${sc}${GROUPS[sc] && GROUPS[sc].name ? " · " + GROUPS[sc].name : ""}`)}">${ls.map(opt).join("")}</optgroup>`).join("");
  };
  const nextShelf = (zone) => 1 + (MAXSHELF[zone] || Math.max(0, ...LOCS.filter((l) => l.zone === zone && l.shelf != null).map((l) => l.shelf)));
  const allShelves = () => (BIG ? SHELVES_BIG : [...new Set(LOCS.map(shelfOf).filter(Boolean))]);
  // 选货位：货位少 = 下拉框；货位多（2 万个）= 输入框边打边联想（/api/inv/loc/suggest）。attrs 是 id / class 等属性
  const locPick = (attrs, sel = "", withNone = "", skip = "") => (BIG
    ? `<input ${attrs} list="loc-dl-pick" value="${esc(sel)}" placeholder="${esc(withNone || Z("货位编号", "รหัสตำแหน่ง"))}" autocomplete="off" data-locpick><datalist id="loc-dl-pick" data-notr></datalist>`
    : `<select ${attrs}>${locOpts(sel, withNone, skip)}</select>`);
  let SUGT = null;
  document.addEventListener("input", (e) => {
    const t = e.target;
    if (!BIG || !t || !t.matches || !t.matches("[data-locpick], input[list='loc-dl']")) return;
    clearTimeout(SUGT);
    SUGT = setTimeout(async () => {
      try {
        const r = await api(`/api/inv/loc/suggest?q=${encodeURIComponent(t.value.trim())}&limit=40`);
        const dl = document.getElementById(t.getAttribute("list")); if (!dl) return;
        dl.innerHTML = r.locations.map((l) => `<option value="${esc(l.code)}">${esc(l.code)}${l.empty ? Z(" ·空", " ·ว่าง") : ""}</option>`).join("");
      } catch { /* 联想失败不影响输入 */ }
    }, 200);
  });
  const lang = () => (TH() ? "&lang=th" : "");
  const can = (k) => !window.INV || !INV.can || INV.can(k);
  const STATE = () => ({ empty: Z("空", "ว่าง"), partial: Z("有货", "มีของ"), full: Z("满", "เต็ม"), over: Z("超容量", "เกินความจุ") });

  // 格子：颜色 = 空 / 有货 / 满 / 超容量；物品低于补货线加 ⚠。v2.55：格子里有第一个商品的小图 + 名称前几个字，鼠标放上去看全部
  const nIt = (l) => (Array.isArray(l.items) ? l.items.length : l.items || 0);
  const qtx = (x) => (TH() ? x.qty_text_th || x.qty_text : x.qty_text) || num(x.qty);
  function cell(l) {
    const t = Array.isArray(l.items) ? l.items : [];
    const cap = l.capacity != null ? ` / ${num(l.capacity)}` : "";
    const tip = [l.code, human(l.code), `${STATE()[l.state] || ""}${l.capacity != null ? ` · ${Z("容量", "ความจุ")} ${num(l.capacity)}` : ""}`,
      ...t.map((x) => `${x.code} ${itName(x)} × ${qtx(x)}`), l.fixed_item ? Z("固定货位", "ตำแหน่งตายตัว") : "", l.note || ""].filter(Boolean).join("\n");
    const first = t.find((x) => x.qty > 1e-9) || t[0];
    const thumb = first && first.img ? `<img class="cell-img" src="${esc(first.img)}" alt="" loading="lazy">` : "";
    const nm_ = first ? Array.from(itName(first) || first.code).slice(0, 5).join("") : "";
    return `<button class="loc-cell st-${esc(l.state || "empty")}${l.low ? " low" : ""}" data-loc="${l.id}" data-code="${esc(l.code)}" title="${esc(tip)}" data-notr>
      <span class="pn">${pad(l.pos)}${l.fixed_item ? " 📌" : ""}${l.mixed === 0 ? " ①" : ""}</span>
      ${thumb}<span class="it">${first ? `${esc(nm_)}${t.length > 1 ? ` +${t.length - 1}` : ""}` : esc(Z("空", "ว่าง"))}</span>
      ${first ? `<span class="cq">${esc(qtx(first))}</span>` : ""}
      ${l.capacity != null ? `<span class="cap">${num(l.total)}${cap}</span>` : ""}${l.low ? '<span class="lw">⚠</span>' : ""}</button>`;
  }

  function shelfCard(sc, ls) {
    const g = GROUPS[sc] || {};
    const layers = [...new Set(ls.map((l) => l.layer))].sort((a, b) => (BOTTOM ? b - a : a - b));
    const maxPos = Math.max(...ls.map((l) => l.pos));
    const topLayer = Math.max(...ls.map((l) => l.layer));
    const empty = ls.filter((l) => !nIt(l)).length;
    return `<div class="loc-shelf" data-shelf="${esc(sc)}">
      <div class="loc-sh-head"><b class="mono" data-notr>${esc(sc)}</b> <span data-notr>${esc(g.name || "")}</span>
        <span class="small muted" data-notr>${esc(Z(`${layers.length} 层 · ${ls.length} 位 · 空 ${empty}`, `${layers.length} ชั้น · ${ls.length} ช่อง · ว่าง ${empty}`))}</span> ${catChips(g)}
        <span class="loc-sh-tools"><button class="mini" data-grp="${esc(sc)}" title="${esc(Z("名称 / 放哪些分类 / 这个货架的货位设置", "ชื่อ / หมวดที่เก็บ / ตั้งค่าช่องของแร็คนี้"))}">✎</button>
          <a class="btn mini" target="_blank" href="/print/inv-locations?shelf=${encodeURIComponent(sc)}${lang()}" title="${esc(Z("打印这个货架的货位标签", "พิมพ์ป้ายช่องของแร็คนี้"))}">🏷</a>
          ${can("inv.out") ? `<button class="mini" data-stk="${esc(sc)}" title="${esc(Z("按货位盘点这个货架", "ตรวจนับแร็คนี้ตามตำแหน่ง"))}">🧮</button>` : ""}
          <button class="mini" data-addlayer="${esc(sc)}">${esc(Z("＋ 加一层", "＋ เพิ่มชั้น"))}</button>${empty === ls.length ? `<button class="mini danger" data-rmshelf="${esc(sc)}">${esc(Z("删除货架", "ลบแร็ค"))}</button>` : ""}</span></div>
      <div class="loc-rack-wrap"><table class="loc-rack"><tbody>${layers.map((ly) => {
        const row = ls.filter((l) => l.layer === ly).sort((a, b) => a.pos - b.pos);
        const allEmpty = row.every((l) => !nIt(l));
        return `<tr><th class="nowrap" data-notr>${esc(Z(`第 ${ly} 层`, `ชั้น ${ly}`))}</th>
          <td><div class="loc-row" style="grid-template-columns:repeat(${Math.max(maxPos, row.length)},minmax(var(--cellw,78px),1fr))">${row.map(cell).join("")}</div></td>
          <td class="nowrap"><button class="mini" data-addpos="${esc(sc)}" data-layer="${ly}" title="${esc(Z("这一层加一位", "เพิ่มช่องในชั้นนี้"))}">＋</button>${allEmpty && layers.length > 1 && ly === topLayer ? `<button class="mini" data-rmlayer="${esc(sc)}" data-layer="${ly}" title="${esc(Z("删掉最上面这一层（空的才能删）", "ลบชั้นบนสุด (ว่างเท่านั้น)"))}">−</button>` : ""}</td></tr>`;
      }).join("")}</tbody></table></div>
      ${BOTTOM ? `<div class="small muted loc-floor" data-notr>${esc(Z("地面", "พื้น"))}</div>` : ""}</div>`;
  }

  // ---------------- 页面 ----------------
  async function page() {
    const box = BOX(); if (!box) return;
    const [, m] = await Promise.all([loadLocs(), api("/api/inv/loc/summary")]);
    MAP = m;
    const st = m.stats, al = m.alerts;
    const nAl = (al.idle || 0) + (al.spread || 0);
    const whOpts = WHS.length > 1 ? `<select id="loc-wh" data-notr><option value="">${esc(Z("全部仓库", "ทุกคลัง"))}</option>${WHS.map((w) => `<option value="${w.id}" ${String(w.id) === WH ? "selected" : ""}>${esc(whLabel(w.name))}</option>`).join("")}</select>` : "";
    box.innerHTML = UX.head(Z("货位", "ตำแหน่งจัดเก็บ"), `
        <input id="loc-scan" placeholder="${esc(Z("扫货位 / 货架 / 物品条码", "สแกนตำแหน่ง / แร็ค / สินค้า"))}" autocomplete="off" class="loc-scan">
        ${can("inv.in") ? `<button class="primary" id="loc-bulk">${esc(Z("＋ 新建货架", "＋ สร้างแร็ค"))}</button><button id="loc-wh-btn">${esc(Z("🏬 仓库", "🏬 คลัง"))}</button>
        <button id="loc-move">${esc(Z("↔ 移库", "↔ ย้ายตำแหน่ง"))}</button>` : ""}
        <button id="loc-print">${esc(Z("🏷 打印标签", "🏷 พิมพ์ป้าย"))}</button>`,
      Z("仓库 → 库区 → 货架 → 层 → 位。一个物品可以放几个货位（拣货位 + 备货区），每个货位记自己的数量；入库按推荐自动上架（设置里可以改成扫货位确认），出库先扣待上架、再从拣货位扣。三种看法：列表（一行一个货位）、按商品（一行一个商品）、货位图（看位置）；点一行看里面有什么、移库、设容量。",
        "คลัง → โซน → แร็ค → ชั้น → ช่อง สินค้าหนึ่งอย่างวางได้หลายช่อง (ช่องหยิบ + โซนสำรอง) แต่ละช่องเก็บจำนวนของตัวเอง รับเข้าแล้ววางตามคำแนะนำอัตโนมัติ (ตั้งค่าให้สแกนยืนยันได้) จ่ายออกหักจากรอจัดเก็บก่อน แล้วหักจากช่องหยิบ สามมุมมอง: รายการ (หนึ่งแถวต่อช่อง) ตามสินค้า (หนึ่งแถวต่อสินค้า) แผนผัง (ดูตำแหน่ง) คลิกแถวเพื่อดูของในช่อง ย้าย ตั้งความจุ")) +
      UX.kpis([
        { label: Z("货位", "ตำแหน่ง"), value: num(st.total, 0), sub: Z(`${st.zones} 个库区 · ${WHS.length} 个仓库`, `${st.zones} โซน · ${WHS.length} คลัง`), icon: "🗄" },
        { label: Z("占用率", "อัตราใช้งาน"), value: `${num(st.util, 1)}%`, sub: Z(`有货 ${num(st.used, 0)} / ${num(st.total, 0)}`, `มีของ ${num(st.used, 0)} / ${num(st.total, 0)}`), tone: st.util >= 90 ? "warn" : "", icon: "📊",
          help: Z("有东西的货位 ÷ 全部货位", "ช่องที่มีของ ÷ ช่องทั้งหมด") },
        { label: Z("空货位", "ช่องว่าง"), value: num(st.empty, 0), tone: st.total && st.empty === 0 ? "bad" : "", icon: "⬜" },
        { label: Z("满 / 超容量", "เต็ม / เกินความจุ"), value: `${st.full} / ${st.over}`, tone: st.over ? "bad" : "", icon: "📦",
          help: Z("设了容量的货位才算满不满（货位设置里填容量）", "นับเฉพาะช่องที่ตั้งความจุไว้") },
        { label: Z("待上架", "รอจัดเก็บ"), value: num(st.pending, 0), tone: st.pending ? "warn" : "ok", go: "loc:pending", icon: "📥",
          help: Z("到了货、还没放到货位上的物品", "ของมาถึงแล้วแต่ยังไม่ได้วางในตำแหน่ง") },
        { label: Z("补货任务", "งานเติมสินค้า"), value: num(st.tasks, 0), tone: st.tasks ? "warn" : "ok", go: "loc:tasks", icon: "🔁",
          help: Z("拣货区的货位低于「最低数量」→ 从备货区搬（货位设置里填最低数量）", "ช่องหยิบต่ำกว่า「ขั้นต่ำ」→ ย้ายจากโซนสำรอง") },
      ]) +
      UX.card({ title: Z("各库区利用率", "อัตราใช้งานแต่ละโซน"), help: Z("有货的货位占这个库区全部货位的比例；括号里是设了容量的货位装了多满", "สัดส่วนช่องที่มีของในโซน ในวงเล็บคือช่องที่ตั้งความจุไว้เต็มแค่ไหน"),
        body: utilBars(m.zones) }) +
      `<div class="row between wrap gap loc-subbar">${UX.tabs([["list", Z("📋 列表", "📋 รายการ")], ["item", Z("📦 按商品", "📦 ตามสินค้า")], ["map", Z("🗺 货位图", "🗺 แผนผัง")],
        ["pending", Z("待上架", "รอจัดเก็บ"), st.pending || ""], ["tasks", Z("补货 · 移库", "เติม · ย้าย"), st.tasks || ""], ["alerts", Z("提醒", "แจ้งเตือน"), nAl || ""]], SUB, "loc")}${SUB === "map" ? whOpts : ""}</div>
      <div id="loc-sub"></div>`;
    const sc = $("#loc-scan");
    sc.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter" || !sc.value.trim()) return;
      try { const d = await api(`/api/inv/locations/find?code=${encodeURIComponent(sc.value.trim())}`); sc.value = ""; found(d); }
      catch (err) { toast(err.message, true); }
    });
    const wh = $("#loc-wh"); if (wh) wh.onchange = () => { WH = wh.value; renderSub(); };
    renderSub();
  }

  // 利用率条：按 0–100% 画（UX.bars 是按最大值比例画的，这里要绝对百分比）
  function utilBars(zones) {
    if (!zones.length) return UX.empty(Z("还没有货位", "ยังไม่มีตำแหน่ง"));
    return `<div class="ux-bars">${zones.map((z) => {
      const pct = z.total ? Math.round(100 * z.used / z.total) : 0;
      const tone = z.over ? "ux-bad" : pct >= 90 ? "ux-warn" : "ux-ok";
      return `<div class="ux-bar-row"><span class="ux-bar-l" data-notr>${esc(`${z.zone} · ${ztName(z.ztype)}${z.name ? " · " + z.name : ""}`)}</span>
        <span class="ux-bar-t"><i class="${tone}" style="width:${Math.max(2, pct)}%"></i></span>
        <span class="ux-bar-v" data-notr>${pct}% · ${z.used}/${z.total}${z.cap ? ` · ${esc(Z("容量", "ความจุ"))} ${Math.round(100 * z.cap_used / z.cap)}%` : ""}</span></div>`;
    }).join("")}</div>`;
  }

  function renderSub() {
    if (VIEWS.includes(SUB)) { try { localStorage.setItem("inv_loc_view255", SUB); } catch { /* 忽略 */ } }
    const box = $("#loc-sub"); if (!box) return;
    if (SUB === "list" || SUB === "item") return window.INVLV.render(SUB, box, MAP).catch((e) => toast(e.message, true));
    if (SUB === "alerts" && window.INVWMS) return api("/api/inv/wms/map").then((m) => INVWMS.render(SUB, box, m)).catch((e) => toast(e.message, true));
    if (SUB !== "map" && window.INVWMS) return INVWMS.render(SUB, box, MAP).catch((e) => toast(e.message, true));
    return renderMap(box).catch((e) => toast(e.message, true));
  }

  // 货位图：货位不多（≤ 400）一次画全部；货位多只画选中的库区，库区里的货架先是一行汇总，点开才画格子
  async function renderMap(box) {
    const S = STATE();
    const zlist = (MAP.zones || []).filter((z) => !WH || String(z.wh) === WH);
    const small = ((MAP.stats || {}).total || 0) <= 400;
    const legend = `<div class="row gap wrap small loc-legend" data-notr><span class="lg st-empty">${esc(S.empty)}</span><span class="lg st-partial">${esc(S.partial)}</span>
        <span class="lg st-full">${esc(S.full)}</span><span class="lg st-over">${esc(S.over)}</span><span class="lg low">⚠ ${esc(Z("低于补货线", "ต่ำกว่าจุดสั่งซื้อ"))}</span>
        <span class="muted">📌 ${esc(Z("固定货位", "ตำแหน่งตายตัว"))} · ① ${esc(Z("不混放", "ไม่ปนกัน"))}</span></div>`;
    if (!zlist.length) { box.innerHTML = `<div class="card">${UX.empty(Z("还没有货位。点「＋ 新建货架」：选库区（例如 A）、类型、从几号货架开始、建几个、几层、每层几位，一次建好，再打印标签贴上。",
      "ยังไม่มีตำแหน่ง กด「＋ สร้างแร็ค」เลือกโซน (เช่น A) ประเภท เริ่มจากแร็คที่เท่าไร กี่แร็ค กี่ชั้น ชั้นละกี่ช่อง แล้วพิมพ์ป้ายไปติด"))}</div>`; return; }
    const zchips = (withAll) => `<div class="chips loc-zchips">${[...(withAll ? [["", Z("全部库区", "ทุกโซน")]] : []), ...zlist.map((z) => [z.zone, `${z.zone} · ${ztName(z.ztype)}${small ? "" : ` · ${num(z.total, 0)}`}`])].map(([k, t]) =>
      `<span class="chip ${ZONE === k ? "on" : ""}" data-zf="${esc(k)}" data-notr>${esc(t)}</span>`).join("")}</div>`;
    const zoneHead = (z, extra) => {
      const g = GROUPS[z] || {}, zi = zoneInfo(z);
      return `<div class="loc-zone-h"><h3 data-notr>${esc(Z(`${z} 区`, `โซน ${z}`))} <span class="loc-zt zt-${esc(zi.ztype)}">${esc(ztName(zi.ztype))}</span>
            <span class="small" data-notr>${esc(g.name || "")}</span> ${catChips(g)}</h3>
          <span class="small muted" data-notr>🏬 ${esc(whName(zi.warehouse))} · ${esc(extra)}</span>
          <span class="loc-sh-tools">${can("inv.in") ? `<button class="mini" data-grp="${esc(z)}">${esc(Z("✎ 库区设置", "✎ ตั้งค่าโซน"))}</button>` : ""}
            <a class="btn mini" target="_blank" href="/print/inv-locations?zone=${encodeURIComponent(z)}${lang()}">🏷</a>
            ${can("inv.out") ? `<button class="mini" data-stk="${esc(z)}">${esc(Z("🧮 盘点这个区", "🧮 ตรวจนับโซนนี้"))}</button>` : ""}</span></div>`;
    };
    const byShelf = (locs) => {
      const o = {};
      locs.forEach((l) => { if (l.shelf != null) (o[shelfOf(l)] = o[shelfOf(l)] || []).push(l); });
      return o;
    };
    const shelfNo = (sc, z) => parseInt(sc.slice(z.length), 10);
    if (small) {
      const r = await api("/api/inv/loc/map?every=1");
      const zones = {}, other = [];
      r.locations.forEach((l) => {
        if (WH && String(zoneInfo(l.zone).warehouse) !== WH) return;
        if (l.shelf == null) return other.push(l);
        ((zones[l.zone] = zones[l.zone] || {})[shelfOf(l)] = zones[l.zone][shelfOf(l)] || []).push(l);
      });
      const zoneKeys = Object.keys(zones).sort();
      if (ZONE && !zones[ZONE]) ZONE = "";
      box.innerHTML = `${zoneKeys.length > 1 ? zchips(true) : ""}${legend}
        ${zoneKeys.filter((z) => !ZONE || z === ZONE).map((z) => {
          const shelves = Object.keys(zones[z]).sort((a, b) => shelfNo(a, z) - shelfNo(b, z));
          return `<div class="card loc-zone" data-zone="${esc(z)}">${zoneHead(z, Z(`${shelves.length} 个货架`, `${shelves.length} แร็ค`))}
            <div class="loc-shelves">${shelves.map((sc) => shelfCard(sc, zones[z][sc])).join("")}</div></div>`;
        }).join("")}
        ${other.length && !ZONE ? `<div class="card"><h3>${esc(Z("其他货位", "ตำแหน่งอื่นๆ"))} <span class="small muted">${esc(Z("（编号不是「区+货架号-层-位」写法的，空了可以删掉）", "(รหัสที่ไม่ใช่รูปแบบ โซน+แร็ค-ชั้น-ช่อง ถ้าว่างลบได้)"))}</span></h3>
          <div class="loc-row" style="grid-template-columns:repeat(auto-fill,minmax(92px,1fr))">${other.map((l) => `<button class="loc-cell st-${esc(l.state || "empty")}" data-loc="${l.id}" data-notr><span class="pn">${esc(l.code)}</span>
            <span class="it">${esc(nIt(l) ? Z(`${nIt(l)} 种`, `${nIt(l)} รายการ`) : Z("空", "ว่าง"))}</span></button>`).join("")}</div></div>` : ""}`;
      return;
    }
    // 货位多：选中的库区 + 货架汇总行（点开才画格子）
    if (!ZONE || !zlist.find((z) => z.zone === ZONE)) ZONE = zlist[0].zone;
    const z = ZONE, zs = zlist.find((x) => x.zone === z);
    const r = await api(`/api/inv/loc/map?zone=${encodeURIComponent(z)}${zs.total <= 300 ? "&expand=all" : ""}`);
    const all = r.locations ? byShelf(r.locations) : {};
    Object.entries(all).forEach(([k, v]) => { CACHE[k] = v; });
    if (zs.total <= 300) (r.shelves || []).forEach((x) => OPEN.add(x.shelf));
    const rows = (r.shelves || []).map((sh) => {
      const open = OPEN.has(sh.shelf);
      const pct = sh.total ? Math.round(100 * sh.used / sh.total) : 0;
      return `<div class="lv-shelf ${open ? "open" : ""}" data-shelfwrap="${esc(sh.shelf)}"><div class="lv-shelfrow" data-shexp="${esc(sh.shelf)}"><span class="lv-caret">${open ? "▾" : "▸"}</span>
          <b class="mono" data-notr>${esc(sh.shelf)}</b> <span data-notr>${esc(sh.name || "")}</span> ${catChips({ categories: sh.categories })}
          <span class="small muted" data-notr>${esc(Z(`${sh.layers} 层 · ${sh.total} 位 · 有货 ${sh.used} · 空 ${sh.empty}`, `${sh.layers} ชั้น · ${sh.total} ช่อง · มีของ ${sh.used} · ว่าง ${sh.empty}`))}</span>
          ${sh.over ? `<span class="bad small">${esc(Z(`超容量 ${sh.over}`, `เกินความจุ ${sh.over}`))}</span>` : ""}
          <span class="lv-meter"><i class="ux-ok" style="width:${Math.max(2, pct)}%"></i></span></div>
        ${open && CACHE[sh.shelf] ? shelfCard(sh.shelf, CACHE[sh.shelf]) : open ? `<div class="muted small">${esc(Z("读取中…", "กำลังโหลด…"))}</div>` : ""}</div>`;
    }).join("");
    box.innerHTML = `${zchips(false)}${legend}<div class="card loc-zone" data-zone="${esc(z)}">${zoneHead(z, Z(`${(r.shelves || []).length} 个货架 · ${num(zs.total, 0)} 个货位 · 有货 ${num(zs.used, 0)}`, `${(r.shelves || []).length} แร็ค · ${num(zs.total, 0)} ช่อง · มีของ ${num(zs.used, 0)}`))}
        <p class="small muted">${esc(Z("货位很多：只画选中的库区，货架先显示一行汇总，点一行展开它的格子。", "ตำแหน่งมาก: วาดเฉพาะโซนที่เลือก แร็คแสดงเป็นแถวสรุป คลิกเพื่อกางช่อง"))}</p>
        <div class="lv-shelflist">${rows || UX.empty(Z("这个库区还没有货架", "โซนนี้ยังไม่มีแร็ค"))}</div></div>`;
  }
  async function toggleShelf(sc) {
    if (OPEN.has(sc)) OPEN.delete(sc);
    else {
      OPEN.add(sc);
      if (!CACHE[sc]) { const r = await api(`/api/inv/loc/map?zone=${encodeURIComponent(ZONE)}&shelf=${encodeURIComponent(sc)}`); CACHE[sc] = r.locations || []; }
    }
    const wrap = document.querySelector(`[data-shelfwrap="${sc}"]`);
    if (!wrap) return renderSub();
    const open = OPEN.has(sc);
    wrap.classList.toggle("open", open);
    wrap.querySelector(".lv-caret").textContent = open ? "▾" : "▸";
    const old = wrap.querySelector(":scope > .loc-shelf, :scope > .muted.small"); if (old) old.remove();
    if (open) wrap.insertAdjacentHTML("beforeend", shelfCard(sc, CACHE[sc]));
  }

  function flash(els) {
    document.querySelectorAll(".loc-hl").forEach((x) => x.classList.remove("loc-hl"));
    els = [...els].filter(Boolean);
    els.forEach((x) => x.classList.add("loc-hl"));
    if (els[0]) els[0].scrollIntoView({ block: "center", behavior: "smooth" });
    setTimeout(() => els.forEach((x) => x.classList.remove("loc-hl")), 6000);
  }
  async function toView(v) {
    if (SUB !== v) { SUB = v; await page(); }
  }
  async function found(d) {
    if (d.type === "location") return detail(d.location.id, d);
    if (d.type === "item") {                       // 扫商品：切到「按商品」，搜它，直接看它放在哪些货位
      const it = d.item;
      if (window.INVLV) INVLV.focusItem(it.code);
      SUB = "item"; await page();
      const ls = d.locations || [];
      return toast(`${it.code} ${itName(it)}：${ls.length ? ls.map((x) => `${x.code} ×${num(x.qty)}`).join("、") : Z("还没有货位", "ยังไม่มีช่องเก็บ")}${d.unplaced > 1e-9 ? ` · ${Z("待上架", "รอจัดเก็บ")} ${num(d.unplaced)}` : ""}`, false, 8000);
    }
    const z = d.type === "zone" ? d.code : String(d.code).replace(/\d+$/, "");
    ZONE = z; if (d.type === "shelf") OPEN.add(d.code);
    SUB = "map"; await page();
    if (d.type === "shelf" && !CACHE[d.code]) await toggleShelf(d.code).then(() => toggleShelf(d.code)).catch(() => {});
    if (d.type === "shelf") return flash([document.querySelector(`.loc-shelf[data-shelf="${d.code}"]`)]);
    if (d.type === "zone") return flash([document.querySelector(`.loc-zone[data-zone="${d.code}"]`)]);
  }

  function catBoxes(sel) {
    return `<div class="row gap wrap loc-catbox">${CATS.map((c) => `<label class="nowrap"><input type="checkbox" value="${esc(c.id)}" ${sel.includes(c.id) ? "checked" : ""}> <span data-notr>${esc(TH() ? c.th : c.zh)}</span></label>`).join("")}</div>`;
  }
  const pickedCats = (m) => [...m.querySelectorAll(".loc-catbox input:checked")].map((x) => x.value);
  const ztOpts = (sel) => Object.keys(ZT).map((k) => `<option value="${k}" ${k === sel ? "selected" : ""}>${esc(ztName(k))}</option>`).join("");
  const whOptsSel = (sel) => WHS.map((w) => `<option value="${w.id}" ${w.id === sel ? "selected" : ""}>${esc(whLabel(w.name))}</option>`).join("");
  const sizeOpts = (sel) => `<option value="">${esc(Z("不限", "ไม่จำกัด"))}</option>` + Object.keys(SIZES).map((k) => `<option value="${k}" ${k === sel ? "selected" : ""}>${esc(sizeName(k))}</option>`).join("");
  // 货位设置的几个输入框（一个货位 / 整个货架共用）
  function propsForm(l, many) {
    return `<div class="form4 loc-props">
      <label>${esc(Z("容量（数量，空 = 不限）", "ความจุ (จำนวน ว่าง = ไม่จำกัด)"))}<input type="number" min="0" step="any" data-p="capacity" value="${l.capacity ?? ""}"></label>
      <label>${esc(Z("尺寸等级", "ขนาดช่อง"))}<select data-p="size">${sizeOpts(l.size || "")}</select></label>
      <label>${esc(Z("混放", "ปนกันได้ไหม"))}<select data-p="mixed"><option value="1" ${l.mixed !== 0 ? "selected" : ""}>${esc(Z("可以放几种物品", "วางได้หลายอย่าง"))}</option>
        <option value="0" ${l.mixed === 0 ? "selected" : ""}>${esc(Z("只放一种（不混放）", "อย่างเดียว (ไม่ปน)"))}</option></select></label>
      <label>${esc(Z("最低数量（拣货位，低于就补货）", "ขั้นต่ำ (ช่องหยิบ ต่ำกว่านี้ให้เติม)"))}<input type="number" min="0" step="any" data-p="min_qty" value="${l.min_qty ?? ""}"></label>
      ${many ? "" : `<label>${esc(Z("固定货位：只放这个物品（编码，空 = 不固定）", "ตำแหน่งตายตัว: วางเฉพาะสินค้านี้ (รหัส ว่าง = ไม่กำหนด)"))}<input data-p="fixed_item" value="${esc((l.fixed && l.fixed.code) || "")}" data-notr></label>
      <label>${esc(Z("备注", "หมายเหตุ"))}<input data-p="note" maxlength="100" value="${esc(l.note || "")}" data-notr></label>`}</div>`;
  }
  const readProps = (m, many) => {
    const o = {};
    m.querySelectorAll("[data-p]").forEach((el) => { if (!many || el.value !== "" || el.dataset.p === "mixed") o[el.dataset.p] = el.value; });
    return o;
  };

  // ---------------- 新建货架（可以一次建几个）----------------
  async function bulk() {
    await loadLocs();
    const z0 = ZONES_ALL[ZONES_ALL.length - 1] || (LOCS[LOCS.length - 1] || {}).zone || "A";
    const m = MODAL.open(`<h3>${esc(Z("新建货架", "สร้างแร็ค"))}</h3>
      <p class="small muted">${esc(Z("一次生成货架的全部格子，编号 = 区字母 + 货架号 - 层 - 位。已经有的格子跳过（同一个货架号再建一次 = 补上缺的层和位）。", "สร้างทุกช่องของแร็คในครั้งเดียว รหัส = ตัวอักษรโซน + เลขแร็ค - ชั้น - ช่อง ช่องที่มีแล้วข้ามไป"))}</p>
      <div class="form4"><label>${esc(Z("库区（字母）", "โซน (ตัวอักษร)"))}<input id="lb-zone" value="${esc(z0)}" maxlength="2" style="text-transform:uppercase" data-notr></label>
        <label>${esc(Z("库区类型", "ประเภทโซน"))}<select id="lb-zt">${ztOpts(zoneInfo(z0).ztype)}</select></label>
        <label>${esc(Z("仓库", "คลัง"))}<select id="lb-wh" data-notr>${whOptsSel(zoneInfo(z0).warehouse)}</select></label>
        <label>${esc(Z("从几号货架开始", "เริ่มจากแร็คที่"))}<input id="lb-shelf" type="number" value="${nextShelf(z0)}" min="1" max="99"></label>
        <label>${esc(Z("建几个货架", "สร้างกี่แร็ค"))}<input id="lb-count" type="number" value="1" min="1" max="20"></label>
        <label>${esc(Z("每个几层", "แร็คละกี่ชั้น"))}<input id="lb-layers" type="number" value="4" min="1" max="20"></label>
        <label>${esc(Z("每层几位", "ชั้นละกี่ช่อง"))}<input id="lb-pos" type="number" value="5" min="1" max="50"></label>
        <label>${esc(Z("每个货位的容量（可以不填）", "ความจุต่อช่อง (เว้นได้)"))}<input id="lb-cap" type="number" min="0" step="any"></label>
        <label>${esc(Z("名称（可以不填）", "ชื่อ (เว้นได้)"))}<input id="lb-name" maxlength="40" placeholder="${esc(Z("例如 门口铁架", "เช่น ชั้นเหล็กหน้าประตู"))}" data-notr></label></div>
      <div class="small">${esc(Z("这些货架放哪些分类（新物品自动上架时先放这里，可以不选）", "แร็คนี้เก็บหมวดไหน (สินค้าใหม่จะถูกวางที่นี่ก่อน เว้นได้)"))}</div>${catBoxes([])}
      <p class="small ok" id="lb-prev" data-notr></p>
      <div class="row gap"><button class="primary" id="lb-ok">${esc(Z("建好", "สร้าง"))}</button><button data-mclose>${esc(Z("取消", "ยกเลิก"))}</button></div>`);
    const v = (id) => m.querySelector(id).value.trim();
    const prev = () => {
      if (!m.querySelector("#lb-zone")) return;
      const z = v("#lb-zone").toUpperCase(), s = +v("#lb-shelf"), n = Math.max(1, +v("#lb-count") || 1), L = +v("#lb-layers"), P = +v("#lb-pos");
      const last = s + n - 1;
      m.querySelector("#lb-prev").textContent = /^[A-Z]{1,2}$/.test(z) && s > 0 && L > 0 && P > 0
        ? Z(`将生成 ${n > 1 ? `${z}${s} … ${z}${last}（${n} 个货架）` : `${z}${s}`}，每个 ${L} 层 × ${P} 位，共 ${n * L * P} 个货位：${z}${s}-01-01 … ${z}${last}-${pad(L)}-${pad(P)}`,
          `จะสร้าง ${n > 1 ? `${z}${s} … ${z}${last} (${n} แร็ค)` : `${z}${s}`} แร็คละ ${L} ชั้น × ${P} ช่อง รวม ${n * L * P} ช่อง: ${z}${s}-01-01 … ${z}${last}-${pad(L)}-${pad(P)}`) : "";
    };
    m.querySelector("#lb-zone").addEventListener("input", () => {
      const z = v("#lb-zone").toUpperCase();
      m.querySelector("#lb-shelf").value = nextShelf(z);
      if (GROUPS[z]) { m.querySelector("#lb-zt").value = zoneInfo(z).ztype; m.querySelector("#lb-wh").value = zoneInfo(z).warehouse; }
      prev();
    });
    m.oninput = prev; prev();
    m.querySelector("#lb-ok").onclick = () => busy(m.querySelector("#lb-ok"), async () => {
      const r = await api("/api/inv/locations/bulk", { json: { zone: v("#lb-zone"), shelf: v("#lb-shelf"), count: v("#lb-count"), layers: v("#lb-layers"),
        positions: v("#lb-pos"), name: v("#lb-name"), categories: pickedCats(m), ztype: v("#lb-zt"), warehouse: v("#lb-wh"),
        props: v("#lb-cap") ? { capacity: v("#lb-cap") } : null } });
      toast(Z(`建好了：${r.shelves.join("、")}，新增 ${r.made.length} 个货位`, `สร้างแล้ว: ${r.shelves.join(", ")} เพิ่ม ${r.made.length} ช่อง`)); MODAL.close(); page();
    });
  }

  // 库区 / 货架设置
  function groupModal(code) {
    const g = GROUPS[code] || { name: "", categories: [] };
    const isZone = /^[A-Z]{1,2}$/.test(code);
    const zi = isZone ? zoneInfo(code) : null;
    const sample = isZone ? null : LOCS.find((l) => shelfOf(l) === code) || {};
    const m = MODAL.open(`<h3>${esc(isZone ? Z("库区设置", "ตั้งค่าโซน") : Z("货架设置", "ตั้งค่าแร็ค"))} <span class="mono" data-notr>${esc(code)}</span></h3>
      <div class="form4"><label>${esc(Z("名称（可以不填）", "ชื่อ (เว้นได้)"))}<input id="lg-name" maxlength="40" value="${esc(g.name || "")}" data-notr></label>
        ${isZone ? `<label>${esc(Z("库区类型", "ประเภทโซน"))}<select id="lg-zt">${ztOpts(zi.ztype)}</select></label>
          <label>${esc(Z("仓库", "คลัง"))}<select id="lg-wh" data-notr>${whOptsSel(zi.warehouse)}</select></label>` : ""}</div>
      ${isZone ? `<p class="small muted">${esc(Z("拣货区：订单拣货从这里拿；备货区：整箱存放，拣货位低了从这里补；暂存区 / 退货区 / 次品区：不自动上架；耗材区：耗材、包材、备件。",
        "โซนหยิบ: หยิบตามออเดอร์ / โซนสำรอง: เก็บทั้งลัง เติมช่องหยิบจากที่นี่ / พัก / คืน / ชำรุด: ไม่วางอัตโนมัติ / วัสดุ: ฟิลาเมนต์ วัสดุแพ็ก อะไหล่"))}</p>` : ""}
      <div class="small">${esc(isZone ? Z("放哪些分类：新物品自动上架时，先放到这个区的空位", "เก็บหมวดไหน: สินค้าใหม่จะถูกวางในช่องว่างของโซนนี้ก่อน") : Z("放哪些分类：新物品自动上架时，先放到这个货架的空位", "เก็บหมวดไหน: สินค้าใหม่จะถูกวางในช่องว่างของแร็คนี้ก่อน"))}</div>${catBoxes(g.categories || [])}
      ${isZone ? "" : `<h4>${esc(Z("这个货架所有货位的设置（不填的不改）", "ตั้งค่าทุกช่องของแร็คนี้ (ช่องที่ไม่กรอกไม่เปลี่ยน)"))}</h4>${propsForm({ mixed: sample.mixed, size: "" }, true)}`}
      <div class="row gap" style="margin-top:8px"><button class="primary" id="lg-ok">${esc(Z("保存", "บันทึก"))}</button><button data-mclose>${esc(Z("取消", "ยกเลิก"))}</button></div>`);
    m.querySelector("#lg-ok").onclick = () => busy(m.querySelector("#lg-ok"), async () => {
      await api("/api/inv/locations/group", { json: { code, name: m.querySelector("#lg-name").value.trim(), categories: pickedCats(m),
        ztype: isZone ? m.querySelector("#lg-zt").value : undefined, warehouse: isZone ? m.querySelector("#lg-wh").value : undefined } });
      if (!isZone) {
        const p = readProps(m, true);
        if (Object.keys(p).length) await api("/api/inv/locations/props", { json: { area: code, props: p } });
      }
      toast(Z("已保存", "บันทึกแล้ว")); MODAL.close(); page();
    });
  }

  async function warehouseModal() {
    await loadLocs();
    const m = MODAL.open(`<h3>${esc(Z("仓库", "คลังสินค้า"))}</h3>
      <p class="small muted">${esc(Z("仓库 → 库区 → 货架 → 层 → 位。只有一个地方放东西就用「默认仓库」；有第二个仓库时在这里加，再在库区设置里选它属于哪个仓库。",
        "คลัง → โซน → แร็ค → ชั้น → ช่อง ถ้ามีที่เก็บที่เดียวใช้「คลังเริ่มต้น」 ถ้ามีคลังที่สองเพิ่มที่นี่ แล้วเลือกในตั้งค่าโซน"))}</p>
      <table class="grid small"><thead><tr><th>${esc(Z("名称", "ชื่อ"))}</th><th>${esc(Z("库区", "โซน"))}</th><th></th></tr></thead><tbody>
      ${WHS.map((w) => `<tr data-wid="${w.id}"><td><input value="${esc(whLabel(w.name))}" data-wn data-notr></td>
        <td data-notr>${esc(Object.keys(GROUPS).filter((z) => /^[A-Z]{1,2}$/.test(z) && zoneInfo(z).warehouse === w.id).join(" "))}</td>
        <td><button class="mini" data-wsave>${esc(Z("改名", "เปลี่ยนชื่อ"))}</button></td></tr>`).join("")}</tbody></table>
      <div class="row gap" style="margin-top:8px"><input id="wh-new" placeholder="${esc(Z("新仓库的名字", "ชื่อคลังใหม่"))}" data-notr style="max-width:220px">
        <button class="primary" id="wh-add">${esc(Z("＋ 加仓库", "＋ เพิ่มคลัง"))}</button><button data-mclose>${esc(Z("关闭", "ปิด"))}</button></div>`);
    m.onclick = async (e) => {
      try {
        if (e.target.dataset.wsave !== undefined) {
          const tr = e.target.closest("tr");
          await api("/api/inv/warehouses", { json: { id: +tr.dataset.wid, name: tr.querySelector("[data-wn]").value } }); toast(Z("已保存", "บันทึกแล้ว"));
        }
        if (e.target.id === "wh-add") {
          await api("/api/inv/warehouses", { json: { name: m.querySelector("#wh-new").value } }); toast(Z("已添加", "เพิ่มแล้ว")); warehouseModal();
        }
      } catch (er) { toast(er.message, true); }
    };
  }

  function printModal() {
    const zones = ZONES_ALL.length ? ZONES_ALL : [...new Set(LOCS.map((l) => l.zone))].sort();
    const shelves = allShelves();
    const m = MODAL.open(`<h3>${esc(Z("打印货位标签", "พิมพ์ป้ายตำแหน่ง"))}</h3>
      <div class="form4"><label>${esc(Z("范围", "ขอบเขต"))}<select id="pl-area" data-notr><option value="">${esc(Z("全部货位", "ทุกตำแหน่ง"))}</option>
        ${zones.map((z) => `<option value="zone=${esc(z)}">${esc(Z(`${z} 区`, `โซน ${z}`))} · ${esc(ztName(zoneInfo(z).ztype))}</option>`).join("")}
        ${shelves.map((s) => `<option value="shelf=${esc(s)}">${esc(Z("货架 ", "แร็ค "))}${esc(s)}</option>`).join("")}
        ${WHS.length > 1 ? WHS.map((w) => `<option value="warehouse=${w.id}">🏬 ${esc(whLabel(w.name))}</option>`).join("") : ""}</select></label>
        <label>${esc(Z("样式", "แบบ"))}<select id="pl-fmt"><option value="bar">${esc(Z("条码 + 编号", "บาร์โค้ด + รหัส"))}</option><option value="qr">${esc(Z("二维码 + 编号 + 库区", "QR + รหัส + โซน"))}</option>
          <option value="shelf">${esc(Z("货架牌（每个货架一张）", "ป้ายแร็ค (แร็คละใบ)"))}</option></select></label></div>
      <p class="small muted">${esc(Z("标签 50×30 毫米，热敏标签机直接打。扫条码和扫二维码都认得。", "ป้าย 50×30 มม. พิมพ์ด้วยเครื่องพิมพ์ความร้อน สแกนได้ทั้งบาร์โค้ดและ QR"))}</p>
      <div class="row gap"><a class="btn primary" id="pl-go" target="_blank">${esc(Z("🏷 打印", "🏷 พิมพ์"))}</a><button data-mclose>${esc(Z("关闭", "ปิด"))}</button></div>`);
    const upd = () => {
      const a = m.querySelector("#pl-area").value, f = m.querySelector("#pl-fmt").value;
      m.querySelector("#pl-go").href = `/print/inv-locations?${a || "x=1"}${f === "qr" ? "&fmt=qr" : f === "shelf" ? "&kind=shelf" : ""}${lang()}`;
    };
    m.onchange = upd; upd();
  }

  // ---------------- 点一行 / 一格：右边抽屉（里面的商品、出入库记录、移库 / 上架 / 设置 / 盘点）----------------
  let DR = null;
  function closeDrawer() { if (DR) { DR.remove(); DR = null; } }
  function openDrawer(html) {
    closeDrawer();
    DR = document.createElement("div");
    DR.className = "lv-drawer-wrap";
    DR.innerHTML = `<div class="lv-dr-mask" data-drclose></div><aside class="lv-drawer" role="dialog"><button type="button" class="lv-dr-x" data-drclose aria-label="${esc(Z("关闭", "ปิด"))}">✕</button><div class="lv-dr-in">${html}</div></aside>`;
    document.body.appendChild(DR);
    DR.addEventListener("click", (e) => { if (e.target.closest("[data-drclose],[data-mclose]")) closeDrawer(); });
    return DR.querySelector(".lv-dr-in");
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && DR && !document.querySelector("#modal-in")) closeDrawer(); });
  const LOGK = () => ({ putaway: Z("上架", "จัดเก็บ"), move: Z("移库", "ย้าย"), replenish: Z("补货", "เติม"), pick: Z("拣货", "หยิบ"), out: Z("出库", "จ่ายออก"), in: Z("入库", "รับเข้า") });
  function logTable(log) {
    if (!log.length) return `<p class="muted small">${esc(Z("还没有出入库记录。", "ยังไม่มีประวัติเข้า-ออก"))}</p>`;
    const K = LOGK();
    return `<div class="lv-wrap"><table class="grid small"><thead><tr><th>${esc(Z("时间", "เวลา"))}</th><th></th><th>${esc(Z("商品", "สินค้า"))}</th><th>${esc(Z("数量", "จำนวน"))}</th><th>${esc(Z("来源 → 去向", "จาก → ไป"))}</th><th>${esc(Z("类型", "ประเภท"))}</th></tr></thead><tbody>
      ${log.map((x) => `<tr><td class="nowrap small" data-notr>${esc(new Date(x.ts * 1000).toLocaleString())}</td><td class="${x.dir === "in" ? "ok" : "bad"}">${x.dir === "in" ? "＋" : "−"}</td>
        <td data-notr><b class="mono">${esc(x.code)}</b> ${esc(itName(x))}</td><td class="nowrap" data-notr>${esc(qtx(x))}</td>
        <td class="small mono" data-notr>${esc(x.from || Z("待上架", "รอจัดเก็บ"))} → ${esc(x.to || "")}</td><td class="small">${esc(K[x.kind] || x.kind || "")}${x.user ? ` · <span data-notr>${esc(x.user)}</span>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
  }
  const imgTag = (x) => (x.img ? `<img class="lv-img" src="${esc(x.img)}" alt="" loading="lazy">` : x.category === "filament" && x.color ? `<span class="lv-img lv-sw" style="background:${esc(swatch(x.color))}"></span>` : '<span class="lv-img lv-noimg">▣</span>');
  const swatch = (zh) => { try { return (typeof COLORS !== "undefined" && COLORS[zh] && COLORS[zh].hex) || "#94a3b8"; } catch { return "#94a3b8"; } };

  async function detail(lid, pre) {
    if (!LOCS.length && !BIG) await loadLocs();
    const d = await api(`/api/inv/loc/${pre && pre.location ? pre.location.id : lid}/drawer`);
    const L = d.location;
    const pend = can("inv.in") ? (await api("/api/inv/wms/pending")).items : [];
    const S = STATE();
    const m = openDrawer(`<h3>${esc(Z("货位", "ตำแหน่ง"))} <span class="mono" data-notr>${esc(L.code)}</span> <span class="small" data-notr>${esc(human(L.code))}</span></h3>
      <p class="small"><span class="loc-zt zt-${esc(L.ztype || "pick")}">${esc(ztName(L.ztype || "pick"))}</span> <span class="lg-in st-${esc(L.state)}">${esc(S[L.state] || "")}</span>
        <span data-notr>🏬 ${esc(whLabel(L.warehouse_name))}</span>
        ${L.capacity != null ? ` · ${esc(Z("容量", "ความจุ"))} <b>${num(L.total)} / ${num(L.capacity)}</b>` : ""}${L.size ? ` · ${esc(sizeName(L.size))}` : ""}
        ${L.mixed === 0 ? ` · ${esc(Z("不混放", "ไม่ปนกัน"))}` : ""}${L.fixed ? ` · 📌 <span data-notr>${esc(Z("固定给 ", "ตายตัวสำหรับ "))}${esc(L.fixed.code)}</span>` : ""}
        ${L.min_qty != null ? ` · ${esc(Z("最低", "ขั้นต่ำ"))} ${num(L.min_qty)}` : ""} <span class="muted" data-notr>${esc(L.note || "")}</span></p>
      <h4>${esc(Z("里面的商品", "สินค้าในช่อง"))}</h4>
      ${d.items.length ? `<table class="grid small lv-dr-tbl"><thead><tr><th></th><th>${esc(Z("商品", "สินค้า"))}</th><th>${esc(Z("这里有", "ที่นี่มี"))}</th><th>${esc(Z("总库存", "สต็อกรวม"))}</th><th></th></tr></thead><tbody>
        ${d.items.map((it) => `<tr data-iid="${it.id}" class="${it.low ? "inv-low" : ""}"><td class="lv-imgc">${imgTag(it)}</td>
          <td data-notr><span class="lv-nm"${it.category === "goods" ? ` data-p360="${esc(it.code)}"` : ""}>${esc(itName(it))}</span><span class="lv-sku mono">${esc(it.code)}${it.primary ? " ★" : ""}</span></td>
          <td class="nowrap"><b data-notr>${esc(qtx(it))}</b>${it.low ? ' <span class="bad">⚠</span>' : ""}</td><td class="nowrap" data-notr>${esc(TH() ? it.total_text_th || it.total_text : it.total_text)}</td>
          <td class="nowrap">${can("inv.in") ? `<button class="mini" data-dk="purchase">${esc(Z("＋ 入库", "＋ รับเข้า"))}</button>` : ""}${can("inv.out") ? `<button class="mini" data-dk="issue">${esc(Z("− 出库", "− จ่ายออก"))}</button>` : ""}
            ${can("inv.in") ? `<div class="lv-mvrow"><input type="number" min="0" step="any" data-mq value="${it.qty > 1e-9 ? +(+it.qty).toFixed(3) : ""}" class="loc-mq" title="${esc(Z("数量", "จำนวน"))}">
            ${locPick('data-to class="loc-to" data-notr', "", Z("选货位", "เลือกช่อง"), L.code)}<button class="mini" data-mv ${it.qty > 1e-9 ? "" : "disabled"}>${esc(Z("移", "ย้าย"))}</button></div>` : ""}</td></tr>`).join("")}</tbody></table>
        <p class="small muted">★ ${esc(Z("= 这个物品的主货位（拣货先到这里拿）", "= ตำแหน่งหลักของสินค้านี้ (หยิบที่นี่ก่อน)"))}</p>`
        : `<p class="muted">${esc(Z("这个货位是空的。", "ตำแหน่งนี้ว่าง"))}</p>`}
      ${can("inv.in") && pend.length ? `<div class="row gap wrap loc-putbar"><span class="small">${esc(Z("把待上架的放到这里：", "วางของที่รอจัดเก็บที่นี่:"))}</span>
        <select id="loc-put" data-notr>${pend.map((x) => `<option value="${x.item.id}" data-q="${x.qty}">${esc(x.item.code)} · ${esc(itName(x.item))} · ${esc(Z("待上架", "รอ"))} ${num(x.qty)}</option>`).join("")}</select>
        <input type="number" id="loc-put-q" min="0" step="any" class="loc-mq" value="${pend[0] ? +(+pend[0].qty).toFixed(3) : ""}">
        <button class="mini primary" id="loc-put-ok">${esc(Z("上架", "จัดเก็บ"))}</button></div>` : ""}
      <h4>${esc(Z("出入库记录", "ประวัติเข้า-ออก"))} <span class="small muted">${esc(Z("（最近 60 条）", "(60 รายการล่าสุด)"))}</span></h4>${logTable(d.log)}
      ${can("inv.in") ? `<details class="loc-set"><summary>${esc(Z("⚙ 货位设置（容量、尺寸、混放、固定物品、最低数量）", "⚙ ตั้งค่าช่อง (ความจุ ขนาด ปนกัน สินค้าตายตัว ขั้นต่ำ)"))}</summary>
        ${propsForm(L, false)}<button class="primary mini" id="loc-props-ok">${esc(Z("保存设置", "บันทึกการตั้งค่า"))}</button></details>` : ""}
      <div class="row gap wrap" style="margin-top:10px">${can("inv.out") ? `<button id="loc-stk">${esc(Z("🧮 盘点这个货位", "🧮 ตรวจนับช่องนี้"))}</button>` : ""}
        <a class="btn" target="_blank" href="/print/inv-locations?ids=${L.id}${lang()}">${esc(Z("🏷 条码标签", "🏷 ป้ายบาร์โค้ด"))}</a>
        <a class="btn" target="_blank" href="/print/inv-locations?ids=${L.id}&fmt=qr${lang()}">${esc(Z("🏷 二维码标签", "🏷 ป้าย QR"))}</a>
        ${d.items.length ? "" : `<button class="danger" id="loc-del">${esc(Z("删除货位", "ลบตำแหน่ง"))}</button>`}<button data-mclose>${esc(Z("关闭", "ปิด"))}</button></div>`);
    const again = async () => { await loadLocs(); detail(L.id); if (BOX() && !BOX().closest(".hidden")) page(); };
    const ps = m.querySelector("#loc-put");
    if (ps) ps.onchange = () => { m.querySelector("#loc-put-q").value = +(+ps.selectedOptions[0].dataset.q).toFixed(3); };
    m.onclick = async (e) => {
      try {
        const tr = e.target.closest("tr[data-iid]");
        if (e.target.dataset.dk && tr && window.INV) { closeDrawer(); return INV.docModal(e.target.dataset.dk, { item_id: +tr.dataset.iid }); }
        if (e.target.dataset.mv !== undefined && tr) {
          const to = tr.querySelector("[data-to]").value;
          if (!to) return toast(Z("先选要移到的货位", "เลือกช่องปลายทางก่อน"), true);
          await move(L.code, to, [{ item_id: +tr.dataset.iid, qty: tr.querySelector("[data-mq]").value }]);
          return again();
        }
        if (e.target.id === "loc-put-ok") {
          await putaway(+ps.value, L.code, m.querySelector("#loc-put-q").value);
          return again();
        }
        if (e.target.id === "loc-props-ok") {
          await api("/api/inv/locations/props", { json: { codes: [L.code], props: readProps(m, false) } });
          toast(Z("已保存", "บันทึกแล้ว")); return again();
        }
        if (e.target.id === "loc-stk") { closeDrawer(); return stocktake(L.code); }
        if (e.target.id === "loc-del") {
          if (!confirm(Z(`删除货位 ${L.code}？`, `ลบช่อง ${L.code}?`))) return;
          await api(`/api/inv/locations/${L.id}`, { method: "DELETE" }); toast(Z("已删除", "ลบแล้ว")); closeDrawer(); page();
        }
      } catch (err) { toast(err.message, true); }
    };
  }

  // 移库 / 上架（超容量时问一下要不要硬放）
  async function move(from, to, lines, extra) {
    const go = (force) => api("/api/inv/wms/move", { json: { from, to, lines, force, ...(extra || {}) } });
    try { await go(false); }
    catch (er) {
      if (!/放不下|เต็ม/.test(er.message) || !confirm(Z(`${er.message}\n还是要放进去吗？`, `${er.message}\nยังจะวางไหม?`))) throw er;
      await go(true);
    }
    toast(Z(`已移到 ${to}`, `ย้ายไป ${to} แล้ว`));
  }
  async function putaway(itemId, code, qty) {
    const go = (force) => api("/api/inv/wms/putaway", { json: { item_id: itemId, code, qty, force } });
    try { await go(false); }
    catch (er) {
      if (!/放不下/.test(er.message) || !confirm(Z(`${er.message}\n还是要放进去吗？`, `${er.message}\nยังจะวางไหม?`))) throw er;
      await go(true);
    }
    toast(Z(`已上架到 ${code}`, `จัดเก็บที่ ${code} แล้ว`));
  }

  async function stocktake(area) {
    try {
      const d = (await api("/api/inv/stocktake", { json: { area } })).doc;
      if (window.INV && INV.openStocktake) INV.openStocktake(d.id);
    } catch (e) { toast(e.message, true); }
  }

  async function act(fn, ok) { try { await fn(); if (ok) toast(ok); page(); } catch (er) { toast(er.message, true); } }
  document.addEventListener("click", (e) => {
    if (!e.target.closest || !e.target.closest("#tab-inv_locations")) return;
    const tb = e.target.closest("[data-ux-tab]");
    if (tb && tb.closest('[data-ux-group="loc"]')) { SUB = tb.dataset.uxTab; return page(); }
    const zf = e.target.closest("[data-zf]"); if (zf) { ZONE = zf.dataset.zf; return renderSub(); }
    const se = e.target.closest("[data-shexp]"); if (se) return toggleShelf(se.dataset.shexp).catch((er) => toast(er.message, true));
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
    if (e.target.id === "loc-wh-btn") return warehouseModal().catch((er) => toast(er.message, true));
    if (e.target.id === "loc-print") return printModal();
    if (e.target.id === "loc-move" && window.INVWMS) return INVWMS.moveModal().catch((er) => toast(er.message, true));
  });
  document.addEventListener("ux-go", (e) => {
    const v = e.detail || "";
    if (v.startsWith("loc:") && !$("#tab-inv_locations").classList.contains("hidden")) { SUB = v.slice(4); page(); }
  });

  // 页面切换（modkit 调 MODS.inv.show）
  window.MODS = window.MODS || {};
  const prevShow = window.MODS.inv && window.MODS.inv.show;
  window.MODS.inv = Object.assign(window.MODS.inv || {}, {
    show(name) {
      if (name === "inv_locations" || name === "locations") return page().catch((e) => toast(e.message, true));
      if ((name === "inv_stocktake" || name === "stocktake") && window.INVST) return INVST.page().catch((e) => toast(e.message, true));
      if (prevShow) return prevShow(name);
    },
  });
  window.INVLOC = { render: page, page, detail, loadLocs, list: () => LOCS, shelves: allShelves, human, stocktake,
    move, putaway, locOpts, locPick, ztName, groups: () => GROUPS, zones: () => (ZONES_ALL.length ? ZONES_ALL : [...new Set(LOCS.map((l) => l.zone))].sort()), zoneInfo,
    cats: () => CATS, propsForm, readProps, big: () => BIG, reloadSummary: () => page().catch((e) => toast(e.message, true)), closeDrawer };
})();
