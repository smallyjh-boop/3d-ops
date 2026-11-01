"use strict";
// v2.49 「运营」大菜单的 4 个页面：页面头 + 一条共用的筛选条（时间段 / 平台 / 店铺 / 搜索）+ 页签（UX.tabs）。
// 每个页签就是一个页面 id（菜单说明书里的 ghost 菜单），旧链接（待办里的 ops_comp、ops_lazada……）照样能打开到对的页签。
// 页签的内容：ops.js（总览、店铺与评价、商品表现、待确认的建议）、market.js（竞品、竞店、找新品）、plan.js（计划、营销日历）。
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  // 页面：{标题, 说明, 页签:[[页面 id, 中文, 泰文]], 筛选条有哪些}
  const PAGES = {
    ops_overview: { zh: "经营概况", th: "ภาพรวมธุรกิจ", subs: [["ops_dash", "总览", "ภาพรวม"], ["ops_lazada", "店铺与评价", "ร้านและรีวิว"]], f: ["range", "platform", "shop"],
      help: ["卖了多少、赚了多少、平台扣了多少、店铺表现和评价。上面的时间段、平台、店铺对这一页所有的数都有效。", "ขายได้เท่าไร กำไรเท่าไร แพลตฟอร์มหักเท่าไร ประสิทธิภาพร้านและรีวิว ตัวกรองด้านบนใช้กับทุกตัวเลขในหน้านี้"] },
    ops_goods: { zh: "商品表现", th: "ผลงานสินค้า", subs: [["ops_life", "商品表现", "ผลงานสินค้า"], ["ops_sugg", "待确认的建议", "คำแนะนำรอยืนยัน"]], f: ["platform", "q"],
      help: ["每个 SKU 在每个平台一行：处在哪个阶段（测款 / 成长 / 主推 / 衰退……）、访客和转化、卖了多少、建议做什么。「待确认的建议」是运营分析系统想改的标题、售价、上下架。", "แต่ละ SKU ต่อแพลตฟอร์มหนึ่งแถว: อยู่ช่วงไหน ผู้เข้าชมและอัตราซื้อ ขายได้เท่าไร ควรทำอะไร「คำแนะนำรอยืนยัน」คือสิ่งที่ระบบวิเคราะห์อยากแก้"] },
    ops_market: { zh: "市场与竞争", th: "ตลาดและคู่แข่ง", subs: [["ops_comp", "竞品", "สินค้าคู่แข่ง"], ["ops_shops", "竞店", "ร้านคู่แข่ง"], ["ops_radar", "找新品（爆款雷达）", "หาสินค้าใหม่ (เรดาร์)"]], f: ["platform", "q"],
      help: ["竞品的价格和销量、竞店的上新和起量、平台上值得做的新品机会。数据靠浏览器扩展采集。", "ราคาและยอดขายของสินค้าคู่แข่ง สินค้าใหม่ของร้านคู่แข่ง และโอกาสสินค้าใหม่ ข้อมูลเก็บด้วยส่วนขยายเบราว์เซอร์"] },
    ops_plan: { zh: "计划与活动", th: "แผนและแคมเปญ", subs: [["ops_plans", "爆款 / 上量计划", "แผนสินค้าขายดี"], ["ops_cal", "营销日历", "ปฏิทินการตลาด"]], f: ["platform", "q"],
      help: ["给想推的商品定每天卖多少的目标，按天看进度；大促日历和要提前准备的事。", "ตั้งเป้าขายต่อวันให้สินค้าที่อยากดัน ดูความคืบหน้ารายวัน ปฏิทินแคมเปญและสิ่งที่ต้องเตรียม"] },
  };
  const ALIAS = { ops_traffic: "ops_life", opschg: "ops_sugg" };      // 旧页面 id → 现在的页签
  const PAGE_OF = {};
  Object.entries(PAGES).forEach(([p, d]) => d.subs.forEach(([s]) => { PAGE_OF[s] = p; }));
  Object.entries(ALIAS).forEach(([a, s]) => { PAGE_OF[a] = PAGE_OF[s]; });
  const LAST = {};

  // ---------------- 共用的筛选条（几个页面共用一份，记在这台电脑上） ----------------
  const KEY = "ops_filter_v1";
  let FL = { range: "30", from: "", to: "", platform: "", shop: "", q: "" };
  try { Object.assign(FL, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch { /* 没有就用默认 */ }
  FL.q = "";
  let OPTS = { platforms: ["lazada", "shopee", "tiktok"], shops: [] };
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify({ ...FL, q: "" })); } catch { /* 忽略 */ } };
  const RANGES = () => [["today", Z("今天", "วันนี้")], ["7", Z("7 天", "7 วัน")], ["30", Z("30 天", "30 วัน")], ["month", Z("本月", "เดือนนี้")], ["custom", Z("自定义", "กำหนดเอง")]];
  const PLAT = (p) => ({ lazada: "Lazada", shopee: "Shopee", tiktok: "TikTok", manual: Z("私下成交", "ขายตรง") }[p] || p);
  function days(f) {
    f = f || FL;
    const t = new Date();
    if (f.range === "today") return 1;
    if (f.range === "month") return t.getDate();
    if (f.range === "custom" && f.from) return Math.max(1, Math.round((t - new Date(f.from + "T00:00:00")) / 86400000) + 1);
    return Number(f.range) || 30;
  }
  function fbar(page) {
    const f = PAGES[page].f;
    const plats = [...new Set([...(OPTS.platforms || []), ...(FL.platform ? [FL.platform] : [])])];
    const shops = (OPTS.shops || []).filter((s) => !FL.platform || s.platform === FL.platform);
    return `<div class="ops-fbar">
      ${f.includes("range") ? `<span class="seg">${RANGES().map(([k, l]) => `<button data-of-range="${k}" class="${FL.range === k ? "on" : ""}">${l}</button>`).join("")}</span>
        ${FL.range === "custom" ? `<span class="ops-cust"><input type="date" data-of="from" value="${esc(FL.from)}"> ~ <input type="date" data-of="to" value="${esc(FL.to)}"></span>` : ""}` : ""}
      ${f.includes("platform") ? `<select data-of="platform"><option value="">${Z("全部平台", "ทุกแพลตฟอร์ม")}</option>${plats.map((p) => `<option value="${esc(p)}" ${p === FL.platform ? "selected" : ""}>${esc(PLAT(p))}</option>`).join("")}</select>` : ""}
      ${f.includes("shop") && shops.length ? `<select data-of="shop" data-notr><option value="">${Z("全部店铺", "ทุกร้าน")}</option>${shops.map((s) => `<option value="${esc(s.shop)}" ${s.shop === FL.shop ? "selected" : ""}>${esc(s.shop)}</option>`).join("")}</select>` : ""}
      ${f.includes("q") ? `<input data-of="q" type="search" placeholder="${Z("搜索 SKU / 名称", "ค้นหา SKU / ชื่อ")}" value="${esc(FL.q)}" style="width:180px">` : ""}
      <span class="ops-fsp"></span><button class="mini" data-of-reload>⟳ ${Z("刷新", "รีเฟรช")}</button></div>`;
  }

  // ---------------- 页面框架 ----------------
  function frame(page, sub) {
    const P = PAGES[page];
    const sec = $("#tab-" + page);
    if (!sec) return null;
    let top = sec.querySelector(".ops-hub");
    if (!top) { top = document.createElement("div"); top.className = "ops-hub"; sec.prepend(top); }
    const subs = P.subs.filter(([s]) => { const b = $(`#subnav .tab[data-tab="${s}"]`); return !b || !b.classList.contains("role-hidden"); });
    top.innerHTML = UX.head(Z(P.zh, P.th), "", Z(...P.help)) + fbar(page) + (subs.length > 1 ? UX.tabs(subs.map(([s, zh, th]) => [s, Z(zh, th)]), sub, page) : "");
    sec.querySelectorAll(".ops-sub").forEach((x) => x.classList.toggle("hidden", x.dataset.sub !== sub));
    return sec;
  }
  function subOf(tab) {
    if (PAGES[tab]) {
      const subs = PAGES[tab].subs.filter(([s]) => { const b = $(`#subnav .tab[data-tab="${s}"]`); return !b || !b.classList.contains("role-hidden"); });
      const last = LAST[tab];
      return subs.some(([s]) => s === last) ? last : (subs[0] || PAGES[tab].subs[0])[0];
    }
    return ALIAS[tab] || tab;
  }
  let CUR = { page: "", sub: "" };
  async function show(tab) {
    const page = PAGES[tab] ? tab : PAGE_OF[tab];
    if (!page) return;
    const sub = subOf(tab);
    LAST[page] = sub;
    CUR = { page, sub };
    frame(page, sub);
    await render();
  }
  async function render() {
    const { sub } = CUR;
    if (["ops_dash", "ops_lazada", "ops_life", "ops_sugg"].includes(sub)) await OPSA.show(sub);
    else {
      const o = Object.values(window.OPSB || {}).find((x) => x.tabs.includes(sub));
      if (o) await o.show(sub);
    }
    rowFilter();
  }
  // 竞品 / 竞店 / 雷达 / 计划 的表格：平台和搜索在页面上直接筛（不用再问服务器）
  function rowFilter() {
    const { page, sub } = CUR;
    if (!["ops_market", "ops_plan"].includes(page)) return;
    const box = document.querySelector(`#tab-${page} .ops-sub[data-sub="${sub}"]`);
    if (!box) return;
    const q = (FL.q || "").trim().toLowerCase(), pl = FL.platform ? PLAT(FL.platform).toLowerCase() : "";
    const rows = [...box.querySelectorAll("table.grid tbody tr"), ...(sub === "ops_plans" ? box.querySelectorAll(":scope > div > .card, :scope > .card") : [])];
    rows.forEach((r) => {
      const t = r.textContent.toLowerCase();
      r.classList.toggle("oa-fhide", !!((q && !t.includes(q)) || (pl && /lazada|shopee|tiktok/.test(t) && !t.includes(pl))));
    });
  }

  let qT = null;
  document.addEventListener("click", (e) => {
    const sec = e.target.closest("[data-ops-page]");
    if (!sec) return;
    const t = e.target.closest(".ux-tabs[data-ux-group^='ops_'] [data-ux-tab]");
    if (t) return goTab(t.dataset.uxTab);
    const r = e.target.closest("[data-of-range]");
    if (r) {
      FL.range = r.dataset.ofRange;
      if (FL.range === "custom" && !FL.from) { const d = new Date(Date.now() - 29 * 86400000); FL.from = d.toISOString().slice(0, 10); FL.to = new Date().toISOString().slice(0, 10); }
      save(); frame(CUR.page, CUR.sub); return render();
    }
    const rl = e.target.closest("[data-of-reload]");
    if (rl) busy(rl, render);
  });
  document.addEventListener("change", (e) => {
    const i = e.target.closest("[data-ops-page] [data-of]");
    if (!i || i.dataset.of === "q") return;
    FL[i.dataset.of] = i.value;
    if (i.dataset.of === "platform") FL.shop = "";
    save(); frame(CUR.page, CUR.sub); render();
  });
  document.addEventListener("input", (e) => {
    const i = e.target.closest("[data-ops-page] [data-of='q']");
    if (!i) return;
    FL.q = i.value;
    clearTimeout(qT);
    qT = setTimeout(() => {
      if (CUR.sub === "ops_life" && window.OPSA) OPSA.rerender("ops_life");
      else if (CUR.sub === "ops_sugg") OPSA.show("ops_sugg");
      else rowFilter();
    }, 250);
  });
  // v2.51：页面里点店铺名（各店铺对比）→ 改筛选条再重画（和自己在下拉框里选一样，记在这台电脑上）
  function set(patch) {
    Object.assign(FL, patch || {});
    if (FL.shop && !(OPTS.shops || []).some((x) => x.shop === FL.shop)) OPTS = { ...OPTS, shops: [...(OPTS.shops || []), { platform: FL.platform || "", shop: FL.shop }] };
    save(); frame(CUR.page, CUR.sub); return render();
  }
  window.OPSHUB = { show, set, pages: PAGES, pageOf: (t) => PAGE_OF[t] || (PAGES[t] ? t : ""), filter: () => ({ ...FL }), days, options(o) {
    if (!o) return;
    const before = JSON.stringify(OPTS);
    OPTS = { platforms: o.platforms && o.platforms.length ? o.platforms : OPTS.platforms, shops: o.shops || [] };
    if (JSON.stringify(OPTS) !== before && CUR.page) {      // 店铺列表第一次拿到：把筛选条重画一下（不重新加载数据）
      const sec = $("#tab-" + CUR.page), bar = sec && sec.querySelector(".ops-fbar");
      if (bar) bar.outerHTML = fbar(CUR.page);
    }
  } };
})();
