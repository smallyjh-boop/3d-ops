"use strict";
// 商品 360 抽屉（p360 模块 1.0）：任何页面上带 data-p360="SKU 或产品编号" 的元素，点一下从右边滑出这个商品的全部情况。
//   · 普通文字 / 单元格（<td data-p360>、<span data-p360>）：直接点开（选中文字复制时不打开）。
//   · 本身就是链接 / 按钮 / 整行（a、button、tr、[onclick]）带 data-p360：不抢它原来的点击，旁边自动加一个小「ⓘ」点开抽屉。
//   · 代码里也可以直接用：P360.open("3DP0015-WH")、P360.icon("3DP0015-WH")（返回「ⓘ」的 HTML）、P360.close()。
// Esc / × / 点灰色背景关闭；‹ › 在看过的商品之间前后切换。数据来自 GET /api/p360/<目标>（按角色去掉成本 / 价格）。
(function () {
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  const E = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const PLAT = { lazada: "Lazada", shopee: "Shopee", tiktok: "TikTok" };
  const PL2 = (p) => ({ lazada: "LZ", shopee: "SP", tiktok: "TT" }[p] || String(p || "").slice(0, 2).toUpperCase());
  const money = (v) => (v == null || v === "" ? "—" : "฿" + Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 }));
  const day = (ts) => {
    if (!ts) return "";
    const d = new Date(ts * 1000), z = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
  };
  const md = (ts) => day(ts).slice(5);
  const ONL = { live: ["在售", "ขายอยู่", "ok"], uploaded: ["审核中", "รอตรวจ", "info"], rejected: ["审核不通过", "ไม่ผ่านการตรวจ", "bad"],
    inactive: ["已下架", "ปิดการขาย", ""], deleted: ["已删除", "ลบแล้ว", ""] };
  const LST = { none: ["未导出", "ยังไม่ส่งออก", ""], pending: ["待上传", "รออัปโหลด", "info"], failed: ["上传失败", "อัปโหลดไม่สำเร็จ", "bad"],
    uploaded: ["审核中", "รอตรวจ", "info"], rejected: ["审核不通过", "ไม่ผ่านการตรวจ", "bad"], live: ["在售", "ขายอยู่", "ok"],
    inactive: ["已下架", "ปิดการขาย", ""], update: ["有修改待同步", "มีแก้ไขรอซิงก์", "warn"] };
  const ORD = { unpaid: "ยังไม่ชำระ", to_ship: "รอจัดส่ง", shipped: "จัดส่งแล้ว", completed: "สำเร็จ", cancelled: "ยกเลิก", returned: "คืนสินค้า",
    delivery_failed: "ส่งไม่สำเร็จ", quote: "ใบเสนอราคา", other: "อื่นๆ" };
  const JOB = { todo: "รอพิมพ์", printing: "กำลังพิมพ์", post: "เก็บงาน", packed: "แพ็กแล้ว", done: "ส่งแล้ว", failed: "พิมพ์เสีย" };
  const LEVEL = { good: "ok", ok: "ok", warn: "warn", bad: "bad", info: "info", mute: "" };

  let ROOT = null, HIST = [], POS = -1, SEQ = 0, LAST_FOCUS = null;

  // ---------------- 抽屉外框 ----------------
  function root() {
    if (ROOT) return ROOT;
    ROOT = document.createElement("div");
    ROOT.id = "p360";
    ROOT.className = "p360";
    ROOT.setAttribute("data-notr", "");
    ROOT.innerHTML = `<div class="p360-mask" data-p360-x></div>
      <aside class="p360-panel" role="dialog" aria-modal="true" aria-labelledby="p360-title" tabindex="-1">
        <div class="p360-bar">
          <button type="button" class="p360-nav" data-p360-back aria-label="back">‹</button>
          <button type="button" class="p360-nav" data-p360-fwd aria-label="forward">›</button>
          <span class="p360-bar-t" id="p360-title"></span>
          <button type="button" class="p360-close" data-p360-x aria-label="close">✕</button>
        </div>
        <div class="p360-body"></div>
      </aside>`;
    document.body.appendChild(ROOT);
    // v2.53：抽屉 = 一条浏览器历史，返回手势先关抽屉
    if (window.NAV) NAV.overlay(ROOT, { key: "p360", open: (x) => x.classList.contains("on"), close: () => close() });
    ROOT.addEventListener("click", onDrawerClick);
    return ROOT;
  }
  const isOpen = () => !!ROOT && ROOT.classList.contains("on");

  function navState() {
    const r = root();
    r.querySelector("[data-p360-back]").disabled = POS <= 0;
    r.querySelector("[data-p360-fwd]").disabled = POS >= HIST.length - 1;
    r.querySelector("[data-p360-back]").title = Z("上一个", "ก่อนหน้า");
    r.querySelector("[data-p360-fwd]").title = Z("下一个", "ถัดไป");
    r.querySelector("[data-p360-x]:not(.p360-mask)").title = Z("关闭（Esc）", "ปิด (Esc)");
  }

  function open(target, push = true) {
    target = String(target || "").trim();
    if (!target) return;
    const r = root();
    if (!isOpen()) LAST_FOCUS = document.activeElement;
    if (push) {
      if (HIST[POS] !== target) { HIST = HIST.slice(0, POS + 1); HIST.push(target); if (HIST.length > 30) HIST.shift(); }
      POS = HIST.lastIndexOf(target);
    }
    navState();
    r.classList.add("on");
    document.documentElement.classList.add("p360-lock");
    r.querySelector("#p360-title").textContent = target;
    r.querySelector(".p360-body").innerHTML = `<div class="p360-loading">${E(Z("正在读取…", "กำลังโหลด…"))}</div>`;
    r.querySelector(".p360-panel").focus({ preventScroll: true });
    load(target);
  }

  function close() {
    if (!ROOT) return;
    ROOT.classList.remove("on");
    document.documentElement.classList.remove("p360-lock");
    SEQ++;
    if (LAST_FOCUS && LAST_FOCUS.focus && document.contains(LAST_FOCUS)) { try { LAST_FOCUS.focus({ preventScroll: true }); } catch { /* 忽略 */ } }
  }

  function go(step) {
    const n = POS + step;
    if (n < 0 || n >= HIST.length) return;
    POS = n;
    open(HIST[POS], false);
  }

  async function load(target) {
    const my = ++SEQ;
    let d;
    try {
      const r = await fetch(`/api/p360/${encodeURIComponent(target)}`, { headers: { Accept: "application/json" } });
      d = await r.json().catch(() => ({}));
      if (r.status === 401 && d.login) { location.href = "/login"; return; }
      if (!r.ok || d.error) throw Object.assign(new Error(TH() && d.error_th ? d.error_th : d.error || `HTTP ${r.status}`), { nf: !!d.not_found });
    } catch (e) {
      if (my !== SEQ) return;
      ROOT.querySelector(".p360-body").innerHTML = `<div class="p360-err">${e.nf ? "🔍" : "⚠️"} ${E(e.message)}</div>`;
      return;
    }
    if (my !== SEQ) return;
    try {
      ROOT.querySelector(".p360-body").innerHTML = render(d);
      ROOT.querySelector("#p360-title").textContent = d.focus != null ? (d.variants[d.focus] || {}).sku || d.product.id : d.product.id;
      ROOT.querySelector(".p360-body").scrollTop = 0;
    } catch (e) {
      console.error("p360 render", e);
      ROOT.querySelector(".p360-body").innerHTML = `<div class="p360-err">⚠️ ${E(e.message)}</div>`;
    }
  }

  // ---------------- 小零件 ----------------
  const chip = (text, tone, title) => `<span class="p360-chip ${tone ? "p360-" + tone : ""}" ${title ? `title="${E(title)}"` : ""}>${E(text)}</span>`;
  const empty = (zh, th) => `<p class="ux-empty">${E(Z(zh, th))}</p>`;
  const stars = (n) => { n = Math.round(+n || 0); return `<span class="p360-stars" aria-label="${n}/5">${"★".repeat(n)}<i>${"★".repeat(Math.max(0, 5 - n))}</i></span>`; };
  function card(title, body, opts = {}) {
    if (body == null) return "";
    return `<section class="p360-card ${opts.tone ? "p360-card-" + opts.tone : ""}"><div class="p360-card-h"><h4>${E(title)}${opts.n != null ? ` <b>${E(opts.n)}</b>` : ""}</h4>${opts.right || ""}</div>${body}</section>`;
  }
  const col = (c) => (c && typeof colorLabel === "function" ? colorLabel(c) : c);          // 颜色按界面语言（泰文界面显示泰文颜色名）
  const varName = (v) => [col(v.opt1), TH() && v.opt2_th ? v.opt2_th : v.opt2].filter(Boolean).join(" · ");

  // ---------------- 内容 ----------------
  function render(d) {
    const p = d.product, vs = d.variants || [], f = d.focus;
    const name = TH() && p.title_th ? p.title_th : p.name_zh || p.title_th || p.id;
    const sub = TH() ? p.name_zh : p.title_th;
    const fv = f != null ? vs[f] : null;
    const role = d.role;
    // 头
    const lz = (p.listing || {}).lazada || {}, sp = (p.listing || {}).shopee || {};
    const lstChip = (k, st) => {
      if (!st || !st.status || st.status === "none") return "";
      const x = LST[st.status] || [st.status, st.status, ""];
      return chip(`${k} ${Z(x[0], x[1])}`, x[2], st.note || "");
    };
    // v2.50.1 选品采用的产品：模型文件数量 + 「⬇ 下载模型文件」
    const mf = p.model_files, mfs = (mf && mf.status) || {};
    const mfTxt = !mf ? "" : mf.n ? Z(`模型文件 ${mf.n} 个`, `ไฟล์โมเดล ${mf.n} ไฟล์`) + (mf.model ? "" : Z("（还没设 3D 模型）", " (ยังไม่ตั้งโมเดล 3D)"))
      : mfs.queued || mfs.downloading ? Z(`模型文件：等扩展下载 ${(mfs.queued || 0) + (mfs.downloading || 0)} 个`, `ไฟล์โมเดล: รอส่วนขยายดาวน์โหลด ${(mfs.queued || 0) + (mfs.downloading || 0)} ไฟล์`)
      : mfs.failed ? Z(`模型文件下载失败 ${mfs.failed} 个`, `ดาวน์โหลดไฟล์โมเดลไม่สำเร็จ ${mfs.failed} ไฟล์`) : Z("还没有模型文件", "ยังไม่มีไฟล์โมเดล");
    const mfH = !mf ? "" : `<div class="p360-mf small"><span class="${mf.n ? "" : mfs.failed ? "p360-bad" : "p360-warn"}">🧊 ${E(mfTxt)}</span>
      ${mf.can && role !== "production" ? `<button type="button" class="p360-mini" data-p360-act="dlmodel" data-id="${E(p.id)}">⬇ ${E(Z("下载模型文件", "ดาวน์โหลดไฟล์โมเดล"))}</button>` : ""}
      ${mf.can && mfs.ext && !mfs.ext.online && role !== "production" ? `<div class="p360-muted">${E(Z("要有一台装了扩展、登录了原站的 Chrome 开着", "ต้องมี Chrome ที่ติดตั้งส่วนขยายและล็อกอินเว็บต้นทางเปิดอยู่"))}</div>` : ""}</div>`;
    const head = `<div class="p360-head">
      ${p.image ? `<img class="p360-img" src="${E(p.image)}" alt="" data-zoom data-full="${E(p.image)}">` : `<div class="p360-img p360-noimg">📦</div>`}
      <div class="p360-h-main">
        <div class="p360-name" title="${E(name)}" data-notr>${E(name)}</div>
        ${sub && sub !== name ? `<div class="p360-sub" title="${E(sub)}" data-notr>${E(sub)}</div>` : ""}
        <div class="p360-chips">
          <span class="p360-chip p360-id ${f == null ? "on" : ""}" data-p360="${E(p.id)}" title="${E(Z("整个产品", "ทั้งสินค้า"))}">${E(p.id)}</span>
          ${vs.filter((v) => v.sku).slice(0, 12).map((v) => `<span class="p360-chip p360-sku ${fv && fv.sku === v.sku ? "on" : ""}" data-p360="${E(v.sku)}" title="${E(varName(v))}">${E(v.sku.replace(p.id + "-", "-"))}</span>`).join("")}
          ${vs.length > 12 ? chip(`+${vs.length - 12}`) : ""}
        </div>
        <div class="p360-chips">
          ${!p.active ? chip(Z("ERP 已下架", "ปิดใน ERP"), "warn") : ""}${p.draft ? chip(Z("草稿", "ฉบับร่าง"), "warn") : ""}${p.license_pending ? chip(Z("许可待核验", "รอตรวจสัญญาอนุญาต"), "bad") : ""}
          ${lstChip("LZ", lz)}${lstChip("SP", sp)}${p.model_files && p.model_files.inbox ? chip(Z("在采集箱", "อยู่ในกล่องเก็บ"), "info") : ""}
        </div>
        ${mfH}
      </div></div>
      <div class="p360-acts">
        <button type="button" class="primary" data-p360-act="edit" data-id="${E(p.id)}">✏️ ${E(Z("编辑产品", "แก้ไขสินค้า"))}</button>
        ${p.license_pending && role !== "production" ? `<button type="button" data-p360-act="license" data-id="${E(p.id)}">✔ ${E(Z("核验许可", "ตรวจสัญญาอนุญาต"))}</button>` : ""}
        ${role !== "production" && hasTab("export") ? `<button type="button" data-p360-act="export" data-id="${E(p.id)}">⬆️ ${E(Z("上架", "ลงขาย"))}</button>` : ""}
        ${d.online && hasTab("online") ? `<button type="button" data-p360-act="online" data-id="${E(fv ? fv.sku : p.id)}">🛒 ${E(Z("在线商品", "สินค้าออนไลน์"))}</button>` : ""}
      </div>`;
    // 数字
    const k = d.kpi || {};
    const st = k.stage;
    const kp = [
      { label: Z("库存（可用）", "สต็อก (พร้อมใช้)"), value: k.free, sub: k.stock !== k.free ? Z(`共 ${k.stock}，订单占 ${k.stock - k.free}`, `ทั้งหมด ${k.stock} จองแล้ว ${k.stock - k.free}`) : Z(`${vs.length} 个规格合计`, `รวม ${vs.length} ตัวเลือก`),
        tone: k.free ? "" : "warn" },
      { label: Z("30 天销量", "ยอดขาย 30 วัน"), value: k.sold_30d, sub: k.spark && k.spark.some((x) => x) ? "" : Z("件", "ชิ้น"), spark: k.spark && k.spark.some((x) => x) ? k.spark : null, tone: "info" },
    ];
    if (d.owner) {
      const rng = k.profit_min != null && k.profit_max != null && k.profit_min !== k.profit_max ? `${money(k.profit_min)} ~ ${money(k.profit_max)}` : (fv ? fv.sku : "");
      kp.push({ label: Z("单件利润", "กำไรต่อชิ้น"), value: k.profit_unit == null ? "—" : money(k.profit_unit), sub: rng,
        tone: k.profit_unit == null ? "" : k.profit_unit <= 0 ? "bad" : "ok" });
    }
    if (st) kp.push({ label: Z("阶段", "ระยะ"), value: Z(st.label, st.label_th), sub: `${PL2(st.platform)} · ${st.sku.replace(p.id + "-", "-")}`, tone: LEVEL[st.level] || "" });
    if (d.reviews) kp.push({ label: Z("评分", "คะแนนรีวิว"), value: k.rating != null ? `★ ${k.rating}` : "—", sub: k.reviews ? Z(`${k.reviews} 条评价`, `${k.reviews} รีวิว`) : Z("还没有评价", "ยังไม่มีรีวิว"),
      tone: k.rating == null ? "" : k.rating < 4 ? "warn" : "ok" });
    const kpis = window.UX ? `<div class="p360-k p360-k${kp.length}">${UX.kpis(kp)}</div>` : "";
    return head + kpis + [secStock(d), secOnline(d), secSales(d), secComp(d), secReviews(d), secPlans(d), secChanges(d), secJobs(d), secOrders(d)].join("");
  }

  function secStock(d) {
    const vs = d.variants || [];
    if (!vs.length) return "";
    const f = d.focus;
    const hasLoc = vs.some((v) => v.location);
    const th = `<tr><th>SKU</th><th>${E(Z("规格", "ตัวเลือก"))}</th><th class="r">${E(Z("可用", "พร้อมใช้"))}</th>${hasLoc ? `<th>${E(Z("货位", "ตำแหน่ง"))}</th>` : ""}
      ${d.prices ? `<th class="r">${E(Z("售价", "ราคา"))}</th>` : ""}${d.owner ? `<th class="r">${E(Z("最低价", "ราคาต่ำสุด"))}</th><th class="r">${E(Z("成本", "ต้นทุน"))}</th><th class="r">${E(Z("利润", "กำไร"))}</th>` : ""}</tr>`;
    const rows = vs.map((v, i) => `<tr class="${i === f ? "on" : ""}">
      <td class="mono">${v.sku ? `<span data-p360="${E(v.sku)}">${E(v.sku)}</span>` : "—"}</td>
      <td class="p360-vn">${v.image ? `<img src="${E(v.image)}" alt="" loading="lazy">` : ""}${E(varName(v) || "—")}</td>
      <td class="r"><b class="${v.free ? "" : "warn"}">${v.free ?? "—"}</b>${v.reserved ? `<span class="muted small"> / ${v.stock}</span>` : ""}${v.target ? `<div class="muted small">${E(Z("目标", "เป้า"))} ${v.target}</div>` : ""}</td>
      ${hasLoc ? `<td>${v.location ? `<span class="mono" title="${E(Z(v.location.zh, v.location.th))}">${E(v.location.code)}</span>` : '<span class="muted">—</span>'}</td>` : ""}
      ${d.prices ? `<td class="r">${money(v.price)}</td>` : ""}
      ${d.owner ? `<td class="r ${v.below_floor ? "bad" : "muted"}">${money(v.floor_price)}</td><td class="r muted">${money(v.cost)}</td><td class="r ${v.profit > 0 ? "ok" : "bad"}"><b>${money(v.profit)}</b></td>` : ""}
    </tr>`).join("");
    return card(Z("库存与货位", "สต็อกและตำแหน่ง"), `<div class="p360-tw"><table class="p360-t"><thead>${th}</thead><tbody>${rows}</tbody></table></div>`, { n: vs.length });
  }

  function secOnline(d) {
    if (!d.online) return "";
    const o = d.online;
    if (!o.length) return card(Z("平台在售", "บนแพลตฟอร์ม"), empty("还没有在店铺里找到这个商品（在线商品没同步过，或者还没上架）", "ยังไม่พบสินค้านี้ในร้าน (ยังไม่ซิงก์หรือยังไม่ลงขาย)"));
    const rows = o.map((x) => {
      const s = ONL[x.status] || [x.status_zh || x.status || "?", x.status || "?", ""];
      const pr = x.price_min != null ? (x.price_max != null && x.price_max !== x.price_min ? `${money(x.price_min)}~${money(x.price_max)}` : money(x.price_min)) : "";
      return `<div class="p360-li">
        <div class="p360-li-m"><b>${E(PLAT[x.platform] || x.platform)}</b> · ${E(x.shop || "—")} ${chip(Z(s[0], s[1]), s[2], x.raw_status || "")}
          <div class="small muted"><span class="mono">#${E(x.item_id)}</span>${x.skus && x.skus.length ? ` · ${x.skus.map((k) => `<span class="mono">${E(k.seller_sku)}</span>${k.qty != null ? ` ×${k.qty}` : ""}`).join(", ")}` : ""}</div>
          ${x.reason ? `<div class="small bad">${E(x.reason)}</div>` : ""}</div>
        <div class="p360-li-r">${pr ? `<b>${pr}</b>` : ""}${x.url ? ` <a href="${E(x.url)}" target="_blank" rel="noopener" title="${E(Z("打开平台页面", "เปิดหน้าสินค้า"))}">↗</a>` : ""}</div></div>`;
    }).join("");
    return card(Z("平台在售", "บนแพลตฟอร์ม"), rows, { n: o.length });
  }

  function secSales(d) {
    const s = d.sales || {};
    const days = s.days || [];
    const has = days.some((x) => x.qty);
    const cols = has && window.UX ? UX.columns(days.map((x) => ({ label: x.day, value: x.qty, text: Z(`${x.qty} 件`, `${x.qty} ชิ้น`) })), { h: 84, from: days[0].day.slice(5), to: days[days.length - 1].day.slice(5) })
      : empty("近 30 天没有卖出", "30 วันที่ผ่านมายังไม่มียอดขาย");
    const right = `<span class="small muted">${E(Z(`30 天 ${s.qty_30d || 0} 件`, `30 วัน ${s.qty_30d || 0} ชิ้น`))}${s.revenue_30d != null && s.revenue_30d ? ` · ${money(s.revenue_30d)}` : ""}</span>`;
    let tr = "";
    if (d.traffic && d.traffic.length) {
      tr = `<div class="p360-tw"><table class="p360-t small"><thead><tr><th>SKU</th><th class="r">${E(Z("访客", "ผู้เข้าชม"))}</th><th class="r">${E(Z("加购", "ใส่ตะกร้า"))}</th><th class="r">${E(Z("订单", "ออเดอร์"))}</th><th class="r">${E(Z("转化率", "คอนเวอร์ชัน"))}</th><th>${E(Z("周期", "ช่วง"))}</th></tr></thead><tbody>
        ${d.traffic.map((t) => `<tr><td class="mono">${E(t.sku)} <span class="muted">${E(PL2(t.platform))}</span></td><td class="r">${t.visitors ?? "—"}</td><td class="r">${t.add_to_cart ?? "—"}</td>
          <td class="r">${t.orders ?? "—"}</td><td class="r"><b class="${t.conversion != null && t.conversion < 1 ? "warn" : ""}">${t.conversion != null ? t.conversion + "%" : "—"}</b></td><td class="small muted">${E(t.period_text || "")}${t.ts ? ` · ${md(t.ts)}` : ""}</td></tr>`).join("")}</tbody></table></div>`;
    } else if (d.traffic) tr = `<p class="small muted">${E(Z("还没有流量数据（浏览器扩展在卖家后台采集）", "ยังไม่มีข้อมูลทราฟฟิก (เก็บจากหลังร้านผ่านส่วนขยาย)"))}</p>`;
    return card(Z("销量与流量", "ยอดขายและทราฟฟิก"), cols + tr, { right });
  }

  function secComp(d) {
    const c = d.comp;
    if (!c) return "";
    if (!c.rows.length) return card(Z("竞品", "คู่แข่ง"), empty("还没有关联竞品（运营 → 竞品，关联到这个 SKU）", "ยังไม่ได้ผูกสินค้าคู่แข่งกับ SKU นี้"));
    const sum = [];
    if (c.median != null) sum.push(`${Z("竞品中位价", "ราคากลางคู่แข่ง")} <b>${money(c.median)}</b>`);
    if (c.my_price != null) sum.push(`${Z("我们", "ของเรา")} <b>${money(c.my_price)}</b>${c.vs_median_pct != null ? ` <span class="${c.vs_median_pct > 15 ? "warn" : c.vs_median_pct < -15 ? "info" : "muted"}">(${c.vs_median_pct > 0 ? "+" : ""}${c.vs_median_pct}%)</span>` : ""}`);
    if (c.rank) sum.push(Z(`价格从低到高排第 <b>${c.rank.rank}</b> / ${c.rank.of}`, `ราคาต่ำ→สูง อันดับ <b>${c.rank.rank}</b> / ${c.rank.of}`));
    const bars = window.UX ? UX.bars([...c.rows.filter((x) => x.price != null).map((x) => ({ label: x.shop || x.title || "#" + x.id, value: x.price, text: money(x.price) })),
      ...(c.my_price != null ? [{ label: Z("★ 我们", "★ ของเรา"), value: c.my_price, text: money(c.my_price), tone: "ok" }] : [])].sort((a, b) => a.value - b.value)) : "";
    const list = c.rows.slice(0, 6).map((x) => `<div class="p360-li">
      ${x.image ? `<img class="p360-th" src="${E(x.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ""}
      <div class="p360-li-m"><div class="p360-clip" title="${E(x.title)}">${x.url ? `<a href="${E(x.url)}" target="_blank" rel="noopener">${E(x.title || x.url)}</a>` : E(x.title)}</div>
        <div class="small muted">${E(PLAT[x.platform] || x.platform || "")}${x.shop ? " · " + E(x.shop) : ""}${x.rating ? ` · ★${x.rating}` : ""}${x.reviews ? ` · ${x.reviews} ${E(Z("评价", "รีวิว"))}` : ""}${x.sold_text ? ` · ${E(Z("已售", "ขายแล้ว"))} ${E(x.sold_text)}` : ""}</div></div>
      <div class="p360-li-r"><b>${money(x.price)}</b></div></div>`).join("");
    return card(Z("竞品", "คู่แข่ง"), `<p class="small p360-sum">${sum.join(" · ")}</p>${bars}<div class="p360-gap"></div>${list}`, { n: c.rows.length });
  }

  function secReviews(d) {
    const r = d.reviews;
    if (!r) return "";
    if (!r.n) return card(Z("评价", "รีวิว"), empty("还没有评价（Lazada 评价每天同步）", "ยังไม่มีรีวิว (ซิงก์รีวิว Lazada ทุกวัน)"));
    const items = r.items.map((x) => `<div class="p360-rv ${x.rating && x.rating <= 3 ? "bad" : ""}">${stars(x.rating)} <span class="small muted">${md(x.created)}</span>
      ${x.reply ? `<span class="small ok">✓ ${E(Z("已回复", "ตอบแล้ว"))}</span>` : x.rating && x.rating <= 3 ? `<span class="small warn">${E(Z("未回复", "ยังไม่ตอบ"))}</span>` : ""}
      <div class="p360-rv-t">${E(x.content || Z("（没有文字）", "(ไม่มีข้อความ)"))}</div></div>`).join("");
    const right = `<span class="small">${stars(r.avg)} <b>${r.avg ?? "—"}</b> <span class="muted">· ${r.n}${r.bad ? ` · <span class="bad">${E(Z(`差评 ${r.bad}`, `รีวิวแย่ ${r.bad}`))}</span>` : ""}</span></span>`;
    return card(Z("评价", "รีวิว"), items, { right });
  }

  function secPlans(d) {
    const sg = d.suggestions || [], pl = d.plans, lc = d.lifecycle;
    if (!sg.length && !(pl && pl.length) && !(lc && lc.length)) {
      if (!pl && !lc) return "";
      return card(Z("计划与建议", "แผนและคำแนะนำ"), empty("没有进行中的计划，也没有建议", "ไม่มีแผนที่กำลังทำและไม่มีคำแนะนำ"));
    }
    const sgH = sg.map((s) => `<div class="p360-sg ${s.go ? "ux-go" : ""}" ${s.go ? `data-p360-go="${E(s.go)}"` : ""}>${window.UX ? UX.dot(s.tone, "") : ""}<span>${E(Z(s.zh, s.th))}</span>${s.go ? " ›" : ""}</div>`).join("");
    const lcH = lc && lc.length ? `<div class="p360-chips p360-mt">${lc.slice(0, 10).map((x) => chip(`${x.sku.replace((d.product.id || "") + "-", "-")} ${PL2(x.platform)} · ${Z(x.label, x.label_th)}`, LEVEL[x.level], Z(x.action, x.action_th))).join("")}</div>` : "";
    const plH = (pl || []).map((x) => {
      const m = window.UX ? UX.meter({ label: Z("近 7 天日销", "ยอด/วัน 7 วัน"), value: x.avg7, target: x.target_daily,
        text: x.avg7 != null ? Z(`${x.avg7}/天`, `${x.avg7}/วัน`) : null, targetText: Z(`目标 ${x.target_daily}/天`, `เป้า ${x.target_daily}/วัน`) }) : "";
      return `<div class="p360-plan"><div class="p360-plan-h"><b>${E(Z(x.kind_label, x.kind_th))}</b> <span class="mono small">${E(x.sku)}</span> ${chip(PLAT[x.platform] || x.platform || "")}</div>${m}<div class="small muted">${E(Z(`第 ${x.elapsed ?? 0} / ${x.days} 天`, `วันที่ ${x.elapsed ?? 0} / ${x.days}`))}${x.status_label ? ` · ${E(Z(x.status_label, x.status_th))}` : ""}${d.owner && x.actual_profit != null ? ` · ${E(Z("利润", "กำไร"))} ${money(x.actual_profit)}` : ""}</div>
        ${(x.tasks_due || []).map((t) => `<div class="small">☐ ${E(TH() && t.text_th ? t.text_th : t.text)}</div>`).join("")}</div>`;
    }).join("");
    return card(Z("计划与建议", "แผนและคำแนะนำ"), sgH + lcH + plH, { n: (pl || []).length || null });
  }

  function secChanges(d) {
    if (!d.changes) return "";
    const pend = d.pending || [];
    const all = [...pend, ...d.changes];
    if (!all.length) return card(Z("修改记录", "ประวัติการแก้ไข"), empty("还没有修改记录", "ยังไม่มีประวัติการแก้ไข"));
    const SRC = { ops: Z("运营系统", "ระบบวิเคราะห์"), audit: "", edit: "" };
    const ST = { pending: ["待确认", "รอยืนยัน", "warn"], applied: ["已生效", "มีผลแล้ว", "ok"], rejected: ["已拒绝", "ปฏิเสธแล้ว", ""], reverted: ["已撤回", "ถอนแล้ว", ""] };
    const rows = all.slice(0, 12).map((x) => `<div class="p360-ch"><span class="small muted p360-ch-d">${md(x.ts)}</span>
      <span class="p360-ch-m">${x.status && ST[x.status] ? chip(Z(ST[x.status][0], ST[x.status][1]), ST[x.status][2]) + " " : ""}${E(TH() && x.what_th ? x.what_th : x.what)}${x.sku ? ` <span class="mono small">${E(x.sku)}</span>` : ""}
        ${x.reason || x.detail ? `<div class="small muted">${E(x.reason || x.detail)}</div>` : ""}</span>
      <span class="small muted p360-ch-w">${E(x.who || SRC[x.source] || "")}</span></div>`).join("");
    return card(Z("修改记录", "ประวัติการแก้ไข"), rows, { tone: pend.length ? "warn" : "", n: pend.length ? Z(`${pend.length} 待确认`, `${pend.length} รอยืนยัน`) : null,
      right: pend.length ? `<button type="button" class="mini" data-p360-go="opschg">${E(Z("去确认", "ไปยืนยัน"))} ›</button>` : "" });
  }

  function secJobs(d) {
    const j = d.jobs || [];
    if (!j.length) return card(Z("生产中", "กำลังผลิต"), empty("没有在做的生产任务", "ไม่มีงานผลิตที่กำลังทำ"));
    const tone = { failed: "bad", printing: "info", post: "info", todo: "" };
    const rows = j.map((x) => `<div class="p360-li"><div class="p360-li-m"><span class="mono">${E(x.sku || "")}</span> ×${x.remaining}
        ${chip(Z(x.status_zh, JOB[x.status] || x.status_zh), tone[x.status])} <span class="small muted">${E(x.kind === "stock" ? Z("备货", "สต็อก") : x.kind === "reship" ? Z("补发", "ส่งใหม่") : x.order_no || "")}</span></div>
      <div class="p360-li-r small muted">${x.printer_code ? "🖨 " + E(x.printer_code) : ""} #${x.id}</div></div>`).join("");
    return card(Z("生产中", "กำลังผลิต"), rows, { n: j.length, right: hasTab("production") ? `<button type="button" class="mini" data-p360-go="production">${E(Z("生产看板", "บอร์ดผลิต"))} ›</button>` : "" });
  }

  function secOrders(d) {
    const o = d.orders || [];
    if (!o.length) return card(Z("最近订单", "ออเดอร์ล่าสุด"), empty("还没有订单", "ยังไม่มีออเดอร์"));
    const bad = ["cancelled", "returned", "delivery_failed"];
    const rows = o.map((x) => `<div class="p360-li p360-ord" data-p360-order="${x.id}" title="${E(Z("打开订单", "เปิดออเดอร์"))}">
      <div class="p360-li-m"><span class="mono">${E(x.order_no)}</span> <span class="small muted">${E(PLAT[x.platform] || x.platform || "")} · ${md(x.order_time)}</span>
        <div class="small"><span class="mono">${E(x.sku || "")}</span> ×${x.qty}${x.variation ? ` <span class="muted" data-notr>${E(col(x.variation))}</span>` : ""}</div></div>
      <div class="p360-li-r">${chip(Z(x.status_zh, ORD[x.status] || x.status_zh), bad.includes(x.status) ? "bad" : x.status === "to_ship" ? "warn" : "")}
        ${x.item_total != null ? `<div class="small">${money(x.item_total)}</div>` : ""}</div></div>`).join("");
    return card(Z("最近订单", "ออเดอร์ล่าสุด"), rows, { n: o.length });
  }

  function hasTab(t) {
    const b = document.querySelector(`#subnav .tab[data-tab="${t}"]`);
    return !!b && !b.classList.contains("role-hidden");
  }

  // ---------------- 抽屉里的点击 ----------------
  function setQuery(sel, v) {
    const i = document.querySelector(sel);
    if (!i) return;
    i.value = v;
    i.dispatchEvent(new Event("input", { bubbles: true }));
  }
  async function onDrawerClick(e) {
    const t = e.target;
    if (t.closest("[data-p360-x]")) { close(); return; }
    if (t.closest("[data-p360-back]")) { go(-1); return; }
    if (t.closest("[data-p360-fwd]")) { go(1); return; }
    const a = t.closest("[data-p360-act]");
    try {
      if (a) {
        const id = a.dataset.id;
        if (a.dataset.p360Act === "edit") {
          // v2.53：编辑页「← 返回」回到原来的页面，并重新打开这个商品 360
          if (window.NAV) NAV.mark({ hl: id, p360: HIST[POS] || id });
          close();
          if (typeof openProduct !== "function" && window.MODKIT) await MODKIT.load("goods").catch(() => {});
          if (typeof openProduct === "function") await openProduct(id);
          return;
        }
        if (a.dataset.p360Act === "license") {        // v2.50：许可核验（原站许可允许商用才点）
          if (!confirm(Z("确认已经打开原站看过许可证，可以商用？", "ยืนยันว่าเปิดดูสัญญาอนุญาตที่เว็บต้นทางแล้ว และใช้เชิงพาณิชย์ได้?"))) return;
          await api(`/api/products/${encodeURIComponent(id)}/license`, { json: { verified: true } });
          if (typeof toast === "function") toast(Z("许可已核验", "ตรวจสัญญาอนุญาตแล้ว"));
          await load(HIST[POS] || id); return;
        }
        if (a.dataset.p360Act === "dlmodel") {        // v2.50.1：选品采用的产品，让扩展从原站下载模型文件
          const r = await api(`/api/cur/products/${encodeURIComponent(id)}/download`, { json: {} });
          if (typeof toast === "function") toast(r.queued ? Z(`已排队 ${r.queued} 个文件`, `เข้าคิว ${r.queued} ไฟล์`) : r.busy ? Z("已经在下载了", "กำลังดาวน์โหลดอยู่แล้ว")
            : Z("已让扩展重新读原站详情页，读到文件后自动下载", "ให้ส่วนขยายอ่านหน้ารายละเอียดใหม่ เจอไฟล์แล้วจะดาวน์โหลดอัตโนมัติ"));
          await load(HIST[POS] || id); return;
        }
        if (a.dataset.p360Act === "export") { close(); await goTab("export"); setTimeout(() => setQuery("#exp-q", id), 50); return; }
        if (a.dataset.p360Act === "online") { close(); await goTab("online"); setTimeout(() => setQuery("#ol-q", id), 50); return; }
      }
      const g = t.closest("[data-p360-go]");
      if (g && typeof goTab === "function") { close(); await goTab(g.dataset.p360Go); return; }
      const od = t.closest("[data-p360-order]");
      if (od && typeof goTab === "function") {
        close();
        await goTab("orders");
        setTimeout(() => window.OPS && OPS.openOrder && OPS.openOrder(+od.dataset.p360Order), 100);
      }
    } catch (err) { if (typeof toast === "function") toast(err.message, true); }
  }

  // ---------------- 全局：点带 data-p360 的地方 ----------------
  const INTERACTIVE = "a,button,input,select,textarea,label,summary,tr,[onclick],[role=button],[contenteditable]";
  function selfInteractive(el) {
    return el.matches(INTERACTIVE) && !el.classList.contains("p360-i") && !el.closest(".p360");
  }
  document.addEventListener("click", (e) => {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    const el = e.target.closest && e.target.closest("[data-p360]");
    if (!el || !el.dataset.p360) return;
    if (selfInteractive(el)) return;                                    // 链接 / 按钮自己的事：旁边有「ⓘ」
    const inner = e.target.closest(INTERACTIVE);
    if (inner && el.contains(inner) && inner !== el && !inner.classList.contains("p360-i")) return;   // 点到里面的按钮 / 输入框
    const sel = window.getSelection && String(window.getSelection());
    if (sel && sel.trim().length > 1 && !el.classList.contains("p360-i")) return;        // 在选文字（复制 SKU）
    e.preventDefault();
    e.stopPropagation();
    open(el.dataset.p360);
  }, true);
  // 键盘：焦点在 data-p360 上按回车
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isOpen()) {
      if (document.querySelector(".lightbox.on")) return;               // 先关大图
      e.preventDefault(); close(); return;
    }
    if (isOpen() && e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) { e.preventDefault(); go(e.key === "ArrowLeft" ? -1 : 1); return; }
    if (e.key === "Enter" && e.target && e.target.matches && e.target.matches("[data-p360][tabindex]") && !selfInteractive(e.target)) {
      e.preventDefault(); open(e.target.dataset.p360);
    }
  });

  // 链接 / 按钮 / 整行上的 data-p360：自动在旁边加一个「ⓘ」（不抢它原来的点击）
  function icon(target) {
    return `<button type="button" class="p360-i" data-p360="${E(target)}" title="${E(Z("商品 360：库存、在售、销量、竞品…", "ข้อมูลสินค้า 360"))}" aria-label="360">ⓘ</button>`;
  }
  function addIcons(rootEl) {
    (rootEl || document).querySelectorAll("a[data-p360]:not([data-p360-i]),button[data-p360]:not([data-p360-i]):not(.p360-i),tr[data-p360]:not([data-p360-i]),[onclick][data-p360]:not([data-p360-i]),[role=button][data-p360]:not([data-p360-i])").forEach((el) => {
      if (el.closest(".p360")) return;
      el.setAttribute("data-p360-i", "");
      const b = document.createElement("template");
      b.innerHTML = icon(el.dataset.p360);
      const btn = b.content.firstChild;
      if (el.tagName === "TR") {
        const td = [...el.cells].find((c) => !c.querySelector("input,button,select") && c.textContent.trim());
        if (td) td.appendChild(btn);
      } else el.after(btn);
    });
  }
  let pending = false;
  const mo = new MutationObserver(() => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; addIcons(); });
  });
  function start() {
    addIcons();
    mo.observe(document.body, { childList: true, subtree: true });
  }
  if (document.body) start(); else document.addEventListener("DOMContentLoaded", start);

  window.P360 = { open, close, icon, refresh: () => HIST[POS] && open(HIST[POS], false) };
})();
