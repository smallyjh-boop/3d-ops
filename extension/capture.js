// v3.0：运营采集（从原来单独的「运营分析采集」插件并进来）。只在顶层页面运行。
// 前台（Lazada / Shopee / TikTok 商品页、搜索结果页、店铺页）：点右下角按钮或卡片上的「📊 采集」才读页面；
// 卖家中心的数据页（商品表现 / 流量 / 关键词）：打开后自动采一次（同一页 12 小时一次，插件设置里可以关）。
// 「今日巡逻」（patrol.html）发来的 oa-check / oa-scroll / oa-collect 也在这里处理。不自动翻页、不绕验证码。
// 数据发到 3D 运营管理系统的 /api/v1/ops/ext/…（用插件设置里的员工密钥，和 AI 客服同一把）。
(() => {
  if (window.top !== window || window.__lhOpsLoaded) return;
  window.__lhOpsLoaded = true;
  const host = location.hostname;
  const isBack = /sellercenter\.lazada|seller\.shopee|seller-th\.tiktok|seller\.tiktokshop|seller\.tiktokglobalshop/.test(host);
  const CHAT_URL = /(\/im\b|chat|message|webchat|inbox|customer-service)/i;      // 聊天页是 AI 客服的地盘，不放采集按钮
  const PRODUCT_RE = [/lazada\.co\.th\/.*-i\d+(-s\d+)?\.html/, /lazada\.co\.th\/.*[?&]itemId=\d+/, /shopee\.co\.th\/.*-i\.\d+\.\d+/,
                      /shopee\.co\.th\/product\/\d+\/\d+/, /tiktok\.com\/.*\/product\/\d+/];
  const isProductUrl = (u) => PRODUCT_RE.some((r) => r.test(u));
  const isFront = () => !isBack && isProductUrl(location.href);
  const isSearch = () => !isBack && !isFront() && ((/lazada\.co\.th\/(catalog|tag)\//.test(location.href) && /[?&]q=/.test(location.href))
    || (/shopee\.co\.th\/search/.test(location.href) && /[?&]keyword=/.test(location.href)));
  const SHOPEE_RESERVED = ["search", "product", "cart", "user", "buyer", "m", "mall", "flash_sale", "daily_discover", "verify", "checkout", "buyer_login", "seller", "events3", "deals", "top_products", "find_similar_products", "promotions"];
  function isShopUrl(href) {
    let u; try { u = new URL(href); } catch (e) { return false; }
    const seg = u.pathname.split("/").filter(Boolean);
    if (/lazada\.co\.th$/.test(u.hostname)) return /^\/shop\/[^/]+/.test(u.pathname) || (seg.length === 1 && (u.searchParams.get("from") === "wangpu" || /All-Products/.test(u.searchParams.get("q") || "")));
    if (/shopee\.co\.th$/.test(u.hostname)) return /^\/shop\/\d+/.test(u.pathname) || (seg.length === 1 && !SHOPEE_RESERVED.includes(seg[0].toLowerCase()) && !/-i\.\d+\.\d+|-cat\.|\.html$/.test(seg[0]));
    return false;
  }
  const isShop = () => !isBack && !isFront() && isShopUrl(location.href);
  const isBackPage = () => isBack && !CHAT_URL.test(location.pathname + location.hash);
  function shopLink() {
    const a = [...document.querySelectorAll("a[href]")].find((x) => isShopUrl(x.href) && (/\/shop\//.test(x.href) || /ดูร้านค้า|ไปที่ร้านค้า|View Shop|เข้าชมร้านค้า/.test(x.textContent)));
    if (!a) return null;
    const box = a.closest("[class*=seller], [class*=shop]") || a;
    return { url: a.href.split("#")[0], name: (a.textContent.trim() || (box.innerText || "").split("\n")[0] || "").slice(0, 80) };
  }
  // 验证码 / 风控页面：巡逻遇到就停
  function isCaptcha() {
    if (/punish|captcha|verify\/(traffic|captcha)|_____tmd_____|anti[-_]?bot/i.test(location.href)) return true;
    if (document.querySelector('iframe[src*="captcha"], iframe[src*="punish"], #nc_1_wrapper, .nc-container, [class*="captcha" i]')) return true;
    const t = ((document.body && document.body.innerText) || "").slice(0, 3000);
    return /slide to verify|please slide|เลื่อนเพื่อยืนยัน|ยืนยันว่าคุณไม่ใช่โรบอท|请拖动滑块|验证码|unusual traffic/i.test(t);
  }

  let LANG = "zh";
  const Z = (zh, th) => (LANG === "th" ? th : zh);
  chrome.storage.sync.get({ lang: "zh" }, (d) => { LANG = d.lang || "zh"; refresh(); });
  const rt = (m) => new Promise((ok) => { try { chrome.runtime.sendMessage(m, (r) => { void chrome.runtime.lastError; ok(r || { ok: false, error: Z("插件后台没响应，刷新页面再试", "ส่วนขยายไม่ตอบ รีเฟรชหน้าแล้วลองใหม่") }); }); } catch (e) { ok({ ok: false, error: String(e) }); } });
  async function call(path, body) {
    const r = await rt({ type: "api", path, body });
    if (r.ok) return r.data || { ok: false };
    const e = r.error === "NO_CONFIG" ? Z("还没设置：点插件图标，填系统地址和员工密钥", "ยังไม่ได้ตั้งค่า: กดไอคอนส่วนขยาย กรอกที่อยู่ระบบและคีย์") : r.error;
    return { ok: false, error: e };
  }
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const money = (v) => (v == null ? "-" : "฿" + Number(v).toLocaleString("th-TH", { maximumFractionDigits: 0 }));
  const num = (v, d = 1) => (v == null ? "-" : Number(v).toLocaleString("th-TH", { maximumFractionDigits: d }));
  const confPill = (c) => (c ? `<span class="pill ${c === "实测" ? "" : "w"}">${c === "实测" ? Z("实测", "วัดจริง") : Z("估", "ประมาณ")}</span>` : "");
  let SERVER = "";
  rt({ type: "cfg" }).then((r) => { SERVER = (r && r.ok && r.data && r.data.server) || ""; });

  // ---------- 对比栏（存在插件里，跨页面保留，最多 10 个）----------
  const getCmp = async () => ((await chrome.storage.local.get("oaCmp")).oaCmp || []);
  const setCmp = (ids) => chrome.storage.local.set({ oaCmp: ids.slice(-10) });
  async function addCmp(id) { const ids = (await getCmp()).filter((x) => x !== id); ids.push(id); await setCmp(ids); refreshTray(); }

  // ---------- 界面（Shadow DOM，不影响页面样式）----------
  const root = document.createElement("div");
  root.style.cssText = "all:initial;position:fixed;right:16px;bottom:90px;z-index:2147483645;";
  const sh = root.attachShadow({ mode: "closed" });
  sh.innerHTML = `<style>
    *{box-sizing:border-box;font-family:-apple-system,"Segoe UI","Noto Sans Thai","PingFang SC","Microsoft YaHei",sans-serif}
    .btn{background:#0f6fde;color:#fff;border:none;border-radius:22px;padding:10px 16px;font-size:14px;cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.2)}
    .btn.s{background:#fff;color:#0f6fde;border:1px solid #0f6fde}.btn:disabled{opacity:.6}
    .panel{display:none;width:360px;max-height:72vh;overflow:auto;background:#fff;color:#1d2330;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.25);padding:14px;margin-bottom:10px;font-size:13px;line-height:1.5}
    .panel.wide{width:min(760px,92vw)}.panel.on{display:block}.h{display:flex;align-items:center;gap:8px;margin-bottom:6px}.h b{flex:1;font-size:14px}.x{border:none;background:none;font-size:18px;cursor:pointer;color:#888}
    .kv{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:8px 0}.kv div{background:#f4f6f9;border-radius:8px;padding:6px 8px}.l{font-size:11px;color:#6b7280}.v{font-size:15px;font-weight:650}
    .s{font-size:11px;color:#6b7280}.pill{display:inline-block;padding:0 6px;border-radius:8px;font-size:11px;background:#dcfce7;color:#166534}.pill.w{background:#fef3c7;color:#92400e}
    .bad{color:#c62828}.good{color:#1b7f3b;font-weight:650}.row{display:flex;gap:6px;margin-top:8px;align-items:center}input{flex:1;min-width:0;padding:6px 8px;border:1px solid #cfd5dd;border-radius:8px;font-size:13px}
    .mini{border:1px solid #cfd5dd;background:#fff;border-radius:8px;padding:5px 10px;font-size:12px;cursor:pointer}.mini.p{background:#0f6fde;color:#fff;border-color:#0f6fde}
    a{color:#0f6fde}.err{color:#c62828}table{width:100%;border-collapse:collapse;font-size:12px}td,th{border-bottom:1px solid #eee;padding:4px 6px;text-align:left;vertical-align:top}
    .cmp th{position:sticky;left:0;background:#fff;color:#6b7280;font-weight:500;white-space:nowrap}.cmp td{min-width:110px}.wrap{overflow-x:auto}
    .bar{display:flex;gap:8px;justify-content:flex-end}
  </style><div class="panel" id="p"></div><div class="bar"><button class="btn s" id="tray" style="display:none"></button><button class="btn" id="b" style="display:none"></button></div>`;
  const P = sh.getElementById("p"), B = sh.getElementById("b"), T = sh.getElementById("tray");
  const show = (html, wide = false) => {
    P.innerHTML = `<div class="h"><b>${Z("3D 运营管理系统 · 运营采集", "ระบบบริหาร 3D · เก็บข้อมูลการขาย")}</b><button class="x" id="x">×</button></div>` + html;
    P.classList.toggle("wide", wide); P.classList.add("on"); sh.getElementById("x").onclick = () => P.classList.remove("on");
  };
  function mount() { if (!root.isConnected) document.documentElement.appendChild(root); }
  const openSys = () => (SERVER ? `<a href="${esc(SERVER)}" target="_blank">${Z("打开系统", "เปิดระบบ")}</a>` : "");

  // ---------- 图片 ----------
  function imgUrl(img) {
    const cands = [img.currentSrc, img.getAttribute("src"), img.dataset.src, img.dataset.original, img.dataset.ksLazyload, img.getAttribute("data-lazy-src"),
                   (img.getAttribute("srcset") || img.getAttribute("data-srcset") || "").split(",")[0].trim().split(" ")[0]];
    for (const c of cands) {
      if (!c || /^data:|\.svg(\?|$)|placeholder|blank\.(gif|png)|1x1/i.test(c)) continue;
      try { return new URL(c, location.href).href; } catch (e) { /* 忽略 */ }
    }
    return "";
  }
  function bestImg(r0) {
    let best = "", area = 0;
    for (const img of r0.querySelectorAll("img")) {
      const r = img.getBoundingClientRect(), a = r.width * r.height;
      if (a < 2500 || a <= area) continue;
      const u = imgUrl(img); if (u) { best = u; area = a; }
    }
    if (!best) { const i = [...r0.querySelectorAll("img")].map(imgUrl).find(Boolean); if (i) best = i; }
    return best;
  }
  const ogImage = () => (document.querySelector('meta[property="og:image"], meta[name="og:image"]') || {}).content || "";

  // ---------- 前台：商品页 ----------
  function collectFront() {
    const ld = [...document.querySelectorAll('script[type="application/ld+json"]')].map((s) => s.textContent).slice(0, 5);
    const sl = shopLink();
    return { url: location.href, title: document.title, text: (document.body.innerText || "").slice(0, 20000), ld, image: ogImage() || bestImg(document.body),
             shop_url: sl ? sl.url : null, shop_name: sl ? sl.name : null };
  }
  let SKUS = null;
  async function skus() { if (!SKUS) { const r = await call("/api/v1/ops/ext/ping"); SKUS = r.ok ? r.skus : []; } return SKUS; }
  function renderFront(r) {
    if (!r.ok) return show(`<div class="err">${esc(r.error)}</div>`);
    if (r.id) addCmp(r.id);
    const e = r.est || {};
    const cmp = (r.compare || []).map((g) => `<div class="s">${Z("对比", "เทียบ")} <b>${esc(g.sku)}</b>：${Z("我方", "ของเรา")} ${money(g.my_price)}，${Z("竞品中位", "ค่ากลางคู่แข่ง")} ${money(g.comp_price_median)}
      （${g.price_vs_median_pct > 0 ? "+" : ""}${num(g.price_vs_median_pct)}%）· ${Z("我方日销", "ขาย/วันของเรา")} ${num(g.my_daily, 2)} vs ${Z("竞品最高", "คู่แข่งสูงสุด")} ${num(g.comp_daily_top)}</div>`).join("");
    show(`<div style="display:flex;gap:10px;align-items:flex-start">${r.image ? `<img src="${esc(r.image)}" referrerpolicy="no-referrer" style="width:64px;height:64px;object-fit:cover;border-radius:8px;border:1px solid #eee;flex:none">` : ""}
      <div><div>${r.new ? Z("✅ 已加入竞品", "✅ เพิ่มคู่แข่งแล้ว") : Z(`✅ 已更新（第 ${e.n_snaps || 1} 次记录）`, `✅ อัปเดตแล้ว (ครั้งที่ ${e.n_snaps || 1})`)} ${r.how === "ai" ? "" : `<span class="pill w">${Z("规则识别", "อ่านด้วยกฎ")}</span>`} · ${Z("已放进对比栏", "ใส่ในแถบเปรียบเทียบแล้ว")}</div>
      <div class="s" style="margin:4px 0">${esc(r.title || "")}</div></div></div>
      <div class="kv">
        <div><div class="l">${Z("到手价", "ราคาสุทธิ")}</div><div class="v">${money(e.price_eff)}</div><div class="s">${e.voucher ? Z("券", "คูปอง") + " -" + money(e.voucher) + " · " : ""}${Z("已售", "ขายแล้ว")} ${esc(e.sold_text || "-")} · ${Z("评价", "รีวิว")} ${num(e.reviews, 0)}</div></div>
        <div><div class="l">${Z("日销", "ขาย/วัน")} ${confPill(e.confidence)}</div><div class="v">${num(e.daily)}</div><div class="s">${esc(e.daily == null ? Z(e.note, e.note_th) : Z(e.method, e.method_th))}</div></div>
        <div><div class="l">${Z("7 日销量 / 销售额", "ขาย 7 วัน / ยอดขาย")}</div><div class="v">${num(e.d7, 0)}</div><div class="s">${money(e.rev_7d)}</div></div>
        <div><div class="l">${Z("平台费 / 件", "ค่าธรรมเนียม / ชิ้น")}</div><div class="v">${money(e.fee_unit)}</div><div class="s">${e.fee_rate != null ? (e.fee_rate * 100).toFixed(1) + "%" : ""} ${esc(Z(e.fee_src || "", e.fee_src_th || ""))}</div></div>
        <div><div class="l">${Z("生产成本 / 件", "ต้นทุน / ชิ้น")}</div><div class="v">${money(e.unit_cost)}</div><div class="s">${esc(Z(e.cost_src || "", e.cost_src_th || ""))}</div></div>
        <div><div class="l">${Z("单件利润", "กำไร / ชิ้น")}</div><div class="v ${e.profit_unit < 0 ? "bad" : ""}">${money(e.profit_unit)}</div><div class="s">${e.margin != null ? e.margin + "%" : ""} · ${Z("7 日", "7 วัน")} ${money(e.profit_7d)}</div></div>
      </div>${cmp}
      <div class="row"><input id="sku" list="skl" placeholder="${Z("对比我方 SKU（逗号分隔）", "SKU ของเราที่จะเทียบ (คั่นด้วยจุลภาค)")}" value="${esc((r.skus || []).join(", "))}"><datalist id="skl"></datalist>
        <button class="mini p" id="save">${Z("保存", "บันทึก")}</button></div>
      <div class="row">${r.radar ? `<button class="mini" id="want">${Z("单品机会：要做", "โอกาสสินค้า: จะทำ")}</button><button class="mini" id="skip">${Z("不做", "ไม่ทำ")}</button>` : ""}${shopLink() ? `<button class="mini" id="wshop">🏪 ${Z("盯这家店", "เฝ้าร้านนี้")}</button>` : ""}
        <span style="flex:1"></span>${openSys()}</div>
      ${e.unit_cost == null ? `<div class="s" style="margin-top:6px">${Z("还没有生产成本：填上对比 SKU，或到系统「商品 → 竞品 → 详情」点「AI 估成本」。", "ยังไม่มีต้นทุน: กรอก SKU ที่จะเทียบ หรือกด「AI ประมาณต้นทุน」ในระบบ")}</div>` : ""}`);
    skus().then((list) => { const dl = sh.getElementById("skl"); if (dl) dl.innerHTML = (list || []).map((k) => `<option value="${esc(k.sku)}">${esc(k.name)} ${esc(k.color || "")}</option>`).join(""); });
    sh.getElementById("save").onclick = async () => renderFront({ ...(await call(`/api/v1/ops/ext/competitor/${r.id}`, { skus: sh.getElementById("sku").value })), how: r.how });
    const w = sh.getElementById("want"), k = sh.getElementById("skip"), ws = sh.getElementById("wshop");
    if (ws) ws.onclick = async () => { const x = await call("/api/v1/ops/ext/shop/watch", shopLink()); ws.textContent = x.ok ? Z(`已盯：${x.name || "这家店"}（巡逻时会看）`, `เฝ้าแล้ว: ${x.name || "ร้านนี้"}`) : x.error; };
    if (w) w.onclick = async () => { await call(`/api/v1/ops/ext/competitor/${r.id}`, { radar_status: "want" }); w.textContent = Z("已标记：要做", "ตั้งเป็น: จะทำ"); };
    if (k) k.onclick = async () => { await call(`/api/v1/ops/ext/competitor/${r.id}`, { radar_status: "skip" }); k.textContent = Z("已标记：不做", "ตั้งเป็น: ไม่ทำ"); };
  }

  // ---------- 列表页：每个商品卡片上一个「采集」标记 ----------
  const BADGE = "position:absolute;top:6px;left:6px;z-index:2147483644;padding:2px 8px;border-radius:10px;font:600 12px/18px -apple-system,'Noto Sans Thai','PingFang SC',sans-serif;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.25);";
  const STYLE = { new: "background:#0f6fde;color:#fff;", known: "background:#fff;color:#0f6fde;border:1px solid #0f6fde;", busy: "background:#888;color:#fff;", err: "background:#c62828;color:#fff;" };
  const cards = new Map();
  function cardOf(a) {
    let el = a, best = a;
    for (let i = 0; i < 8 && el.parentElement; i++) {
      const p = el.parentElement;
      const links = new Set([...p.querySelectorAll("a[href]")].map((x) => x.href.split("?")[0]).filter(isProductUrl));
      if (links.size > 1) break;
      best = p; el = p;
    }
    return best;
  }
  function setBadge(b, state, text) { b.dataset.oaState = state; b.style.cssText = BADGE + STYLE[state]; b.textContent = text; }
  function scanCards() {
    if (isBack) return;
    const found = [];
    for (const a of document.querySelectorAll("a[href]")) {
      const url = a.href;
      if (!isProductUrl(url) || a.dataset.lhOa) continue;
      a.dataset.lhOa = "1";
      const key = url.split("?")[0];
      if (key === location.href.split("?")[0] || cards.has(key)) continue;
      const card = cardOf(a);
      const r = card.getBoundingClientRect();
      if (r.width < 80 || r.height < 80) continue;
      if (getComputedStyle(card).position === "static") card.style.position = "relative";
      const b = document.createElement("span");
      setBadge(b, "new", Z("📊 采集", "📊 เก็บ"));
      b.addEventListener("click", (ev) => { ev.preventDefault(); ev.stopPropagation(); captureCard(url, card, b); }, true);
      ["mousedown", "mouseup", "pointerdown", "pointerup"].forEach((t) => b.addEventListener(t, (ev) => ev.stopPropagation(), true));
      card.appendChild(b);
      cards.set(key, { card, badge: b, url });
      found.push(url);
    }
    if (found.length) {
      mount();
      call("/api/v1/ops/ext/known", { urls: found }).then((r) => {
        if (!r.ok) return;
        for (const [u, id] of Object.entries(r.known || {})) { const c = cards.get(u.split("?")[0]); if (c && c.badge.dataset.oaState === "new") { setBadge(c.badge, "known", Z("✓ 已采集", "✓ เก็บแล้ว")); c.id = id; } }
      });
    }
  }
  function cardTitle(card, a) {
    const img = card.querySelector("img[alt]");
    const cand = [a && a.title, img && img.alt, ...(card.innerText || "").split("\n")].filter((x) => x && x.length > 8 && !/฿|ขาย|sold/i.test(x));
    return (cand[0] || "").slice(0, 200);
  }
  async function captureCard(url, card, b) {
    setBadge(b, "busy", Z("采集中…", "กำลังเก็บ…"));
    const r = await call("/api/v1/ops/ext/card", { url, title: cardTitle(card, card.querySelector("a[href]")), text: (card.innerText || "").slice(0, 3000), image: bestImg(card) });
    if (!r.ok) { setBadge(b, "err", Z("✕ 失败", "✕ ไม่สำเร็จ")); b.title = r.error || ""; show(`<div class="err">${esc(r.error)}</div>`); return; }
    const e = r.est || {};
    setBadge(b, "known", e.daily != null ? `✓ ${Z("日销", "ขาย/วัน")} ${num(e.daily)}` : `✓ ${money(e.price_eff)}`);
    renderFront(r);
  }

  // ---------- 横向对比 ----------
  async function refreshTray() {
    const ids = await getCmp();
    T.style.display = ids.length && !isBack ? "" : "none";
    T.textContent = Z(`横向对比（${ids.length}）`, `เปรียบเทียบ (${ids.length})`);
    if (ids.length && !isBack) mount();
  }
  T.onclick = async () => {
    const ids = await getCmp();
    const r = await call(`/api/v1/ops/ext/compare?ids=${encodeURIComponent(ids.join(","))}`);
    if (!r.ok) return show(`<div class="err">${esc(r.error)}</div>`);
    const rows = r.rows || [];
    const best = (f, hi = true) => { const v = rows.map((x) => x.est[f]).filter((x) => x != null); return v.length ? (hi ? Math.max(...v) : Math.min(...v)) : null; };
    const line = (label, f, fmt, hi) => {
      const b = hi == null ? null : best(f, hi);
      return `<tr><th>${label}</th>${rows.map((x) => { const v = x.est[f]; return `<td class="${b != null && v === b && rows.length > 1 ? "good" : ""}">${fmt(v, x)}</td>`; }).join("")}</tr>`;
    };
    show(`<div class="wrap"><table class="cmp">
      <tr><th></th>${rows.map((x) => `<td>${x.image ? `<img src="${esc(x.image)}" referrerpolicy="no-referrer" style="width:72px;height:72px;object-fit:cover;border-radius:8px;border:1px solid #eee;display:block;margin-bottom:4px">` : ""}<a href="${esc(x.url || "#")}" target="_blank">${esc((x.title || "#" + x.id).slice(0, 40))}</a><div class="s">${esc(x.platform)} · ${esc(x.shop || "")}</div>
        <button class="mini" data-rm="${x.id}">${Z("移出", "เอาออก")}</button></td>`).join("")}</tr>
      ${line(Z("到手价", "ราคาสุทธิ"), "price_eff", (v) => money(v), false)}
      ${line(Z("已售", "ขายแล้ว"), "sold_text", (v) => esc(v || "-"))}
      ${line(Z("评价 / 评分", "รีวิว / คะแนน"), "reviews", (v, x) => `${num(v, 0)} / ${num(x.est.rating)}`, true)}
      ${line(Z("日销", "ขาย/วัน"), "daily", (v, x) => `${num(v)} ${confPill(x.est.confidence)}`, true)}
      ${line(Z("7 日销售额", "ยอดขาย 7 วัน"), "rev_7d", (v) => money(v), true)}
      ${line(Z("平台费 / 件", "ค่าธรรมเนียม / ชิ้น"), "fee_unit", (v) => money(v), false)}
      ${line(Z("生产成本 / 件", "ต้นทุน / ชิ้น"), "unit_cost", (v) => money(v), false)}
      ${line(Z("单件利润", "กำไร / ชิ้น"), "profit_unit", (v, x) => `${money(v)}${x.est.margin != null ? `<div class="s">${x.est.margin}%</div>` : ""}`, true)}
      ${line(Z("30 日利润", "กำไร 30 วัน"), "profit_30d", (v) => money(v), true)}
      ${line(Z("每天要打印", "ต้องพิมพ์/วัน"), "print_hours_daily", (v) => (v == null ? "-" : v + Z(" 小时", " ชม.")))}
      ${line(Z("对比我方 SKU", "SKU ของเรา"), "x", (_v, x) => esc((x.skus || []).join(", ") || Z("选品雷达", "เรดาร์คัดสินค้า")))}
    </table></div>
    <div class="row"><button class="mini" id="clr">${Z("清空对比栏", "ล้างแถบเปรียบเทียบ")}</button><span style="flex:1"></span>${openSys()}</div>
    <div class="s" style="margin-top:6px">${Z("绿色 = 这一行里最好的（价格、成本越低越好，其他越高越好）。日销要隔天再采集一次才算得出。", "สีเขียว = ดีที่สุดในแถว (ราคา ต้นทุน ยิ่งต่ำยิ่งดี) ยอดขาย/วันต้องเก็บอีกครั้งวันถัดไป")}</div>`, true);
    sh.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = async () => { await setCmp((await getCmp()).filter((x) => x !== +b.dataset.rm)); refreshTray(); T.onclick(); }));
    sh.getElementById("clr").onclick = async () => { await setCmp([]); refreshTray(); P.classList.remove("on"); };
  };
  chrome.storage.onChanged.addListener((c) => { if (c.oaCmp) refreshTray(); if (c.lang) { LANG = c.lang.newValue || "zh"; refresh(); } });

  // ---------- 搜索结果页 ----------
  function collectSearch() {
    const seen = new Set(), out = [];
    for (const a of document.querySelectorAll("a[href]")) {
      const url = a.href, key = url.split("?")[0];
      if (!isProductUrl(url) || seen.has(key)) continue;
      const card = cardOf(a), r = card.getBoundingClientRect();
      if (r.width < 80 || r.height < 80) continue;
      seen.add(key);
      const c = card.cloneNode(true); c.querySelectorAll("span[data-oa-state]").forEach((x) => x.remove());
      out.push({ url, title: cardTitle(card, a), text: (c.innerText || c.textContent || "").slice(0, 1500), image: bestImg(card) });
      if (out.length >= 60) break;
    }
    const body = document.body.innerText || "";
    const m = body.match(/[\d,.]+\s*(?:k|K)?\s*(?:items? found|results?|รายการ|ผลลัพธ์)[^\n]{0,40}|(?:พบ|found)\s*[\d,.]+[^\n]{0,40}/i);
    return { url: location.href, title: document.title, cards: out, total_text: m ? m[0].slice(0, 80) : "", text: body.slice(0, 3000) };
  }
  function renderSearch(r) {
    if (!r.ok) return show(`<div class="err">${esc(r.error)}</div>`);
    const o = r.opportunity || {}, a = o.ai || {}, p = o.parts || {};
    show(`<div>${Z("✅ 已采集搜索结果", "✅ เก็บผลการค้นหาแล้ว")}：<b>${esc(r.keyword)}</b> · ${r.cards} ${Z("个商品", "สินค้า")}${r.total_results ? ` · ${Z("共", "ทั้งหมด")} ${num(r.total_results, 0)} ${Z("个结果", "ผลลัพธ์")}` : ""}</div>
      <div class="kv">
        <div><div class="l">${Z("机会分", "คะแนนโอกาส")}</div><div class="v ${o.score >= 70 ? "good" : ""}">${o.score ?? "-"}</div><div class="s">${Z("需求", "ความต้องการ")} ${p.demand ?? "-"} · ${Z("竞争少", "แข่งน้อย")} ${p.competition ?? "-"} · ${Z("能打印", "พิมพ์ได้")} ${p.printable ?? "-"} · ${Z("利润", "กำไร")} ${p.profit ?? "-"}</div></div>
        <div><div class="l">${Z("前 10 日销", "ขาย/วัน 10 อันดับ")} ${confPill(o.demand_conf)}</div><div class="v">${num(o.daily_top10)}</div><div class="s">${o.top3_share != null ? Z("前 3 家占 ", "3 ร้านแรก ") + Math.round(o.top3_share * 100) + "%" : ""}</div></div>
        <div><div class="l">${Z("到手价中位", "ราคากลาง")}</div><div class="v">${money(o.price_median)}</div><div class="s">${Z("成本", "ต้นทุน")} ${money(o.unit_cost)}</div></div>
        <div><div class="l">${Z("单件利润", "กำไร / ชิ้น")}</div><div class="v ${o.profit_unit < 0 ? "bad" : ""}">${money(o.profit_unit)}</div><div class="s">${o.margin != null ? o.margin + "%" : ""}</div></div>
      </div>
      ${o.ip_risk ? `<div class="err">${Z("侵权风险：", "เสี่ยงละเมิดลิขสิทธิ์: ")}${esc(a.ip_reason || "")}${Z("，不做", " ไม่ทำ")}</div>` : ""}
      ${a.summary ? `<div>AI：${esc(a.summary)}</div>` : ""}${a.design_idea ? `<div class="s">${Z("我们的版本：", "เวอร์ชันของเรา: ")}${esc(a.design_idea)}</div>` : ""}
      ${(o.notes || []).length ? `<div class="s" style="margin-top:4px">${esc(Z(o.notes, o.notes_th || o.notes).join("；"))}</div>` : ""}
      <div class="s" style="margin-top:6px">${Z("关键词已加进「爆款雷达」，以后巡逻会自动看这一页；隔天再采一次，日销就是实测的。", "คีย์เวิร์ดเข้า「เรดาร์สินค้าขายดี」แล้ว ตระเวนครั้งต่อไปจะดูหน้านี้เอง")}</div>
      <div class="row"><span style="flex:1"></span>${openSys()}</div>`);
  }
  // ---------- 店铺页 ----------
  function collectShop() {
    const s = collectSearch();
    return { url: location.href, title: document.title, text: (document.body.innerText || "").slice(0, 8000), cards: s.cards, logo: ogImage() };
  }
  function renderShop(r) {
    if (!r.ok) return show(`<div class="err">${esc(r.error)}</div>`);
    const m = r.metrics || {};
    show(`<div>${r.stats ? Z("✅ 已采集店铺", "✅ เก็บข้อมูลร้านแล้ว") : Z("✅ 已采集店铺商品", "✅ เก็บสินค้าของร้านแล้ว")} · ${r.items} ${Z("个商品", "สินค้า")}${r.how === "ai" ? "" : ` <span class="pill w">${Z("规则识别", "อ่านด้วยกฎ")}</span>`}</div>
      <div class="kv">
        <div><div class="l">${Z("粉丝", "ผู้ติดตาม")}</div><div class="v">${num(m.followers, 0)}</div><div class="s">${m.followers_7d != null ? (m.followers_7d >= 0 ? "+" : "") + m.followers_7d + " / 7d" : ""}</div></div>
        <div><div class="l">${Z("好评率 / 回复率", "คะแนนเชิงบวก / อัตราตอบ")}</div><div class="v">${m.positive_pct != null ? num(m.positive_pct, 0) + "%" : "-"} / ${m.response_rate != null ? num(m.response_rate, 0) + "%" : "-"}</div><div class="s">${esc(m.response_time || "")}</div></div>
        <div><div class="l">${Z("店铺日销（下限）", "ขาย/วัน (ขั้นต่ำ)")}</div><div class="v">${num(m.daily)}</div><div class="s">${m.daily == null ? Z("隔天再采一次才算得出", "เก็บอีกครั้งวันถัดไป") : m.daily_n + Z(" 个商品", " สินค้า")}</div></div>
        <div><div class="l">${Z("价格带", "ช่วงราคา")}</div><div class="v">${m.price_min != null ? money(m.price_min) + "–" + money(m.price_max) : "-"}</div><div class="s">${m.items_seen || 0} ${Z("个商品看得到", "สินค้าที่เห็น")}</div></div>
      </div>
      <div class="s">${Z("Lazada 店铺要「店铺资料」和「全部商品」两页都采一次，数据才全；已加入「竞店」，以后巡逻会自动看。", "ร้าน Lazada ต้องเก็บทั้งหน้า「ข้อมูลร้าน」และ「สินค้าทั้งหมด」 เพิ่มใน「ร้านคู่แข่ง」แล้ว")}</div>
      <div class="row"><span style="flex:1"></span>${openSys()}</div>`);
  }
  async function slowScroll(ms) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      window.scrollBy({ top: 300 + Math.random() * 400, behavior: "smooth" });
      await new Promise((ok) => setTimeout(ok, 1200 + Math.random() * 1800));
      if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 50) break;
    }
  }

  // ---------- 卖家中心数据页 ----------
  function tablesText() {
    const out = [];
    const els = [...document.querySelectorAll('table, [role="table"], [role="grid"]')];
    for (const t of els) {
      if (els.some((o) => o !== t && o.contains(t))) continue;
      const rows = [...t.querySelectorAll('tr, [role="row"]')].map((tr) =>
        [...tr.querySelectorAll('th, td, [role="cell"], [role="gridcell"], [role="columnheader"]')].map((c) => (c.innerText || c.textContent || "").replace(/\s+/g, " ").trim()).join("\t"));
      const txt = rows.filter((x) => x.trim()).join("\n");
      if (txt) out.push(txt);
    }
    return out.join("\n\n").slice(0, 14000);
  }
  function renderBack(r) {
    if (!r.ok) return show(`<div class="err">${esc(r.error)}</div>`);
    show(`<div>${Z("✅ 已采集", "✅ เก็บแล้ว")}：${esc(r.period_text || "")} · ${r.rows} ${Z("个商品（对上 ERP SKU", "สินค้า (จับคู่ SKU")} ${r.matched}${Z(" 个）", ")")}${r.keywords ? ` · ${r.keywords} ${Z("个关键词搜索量", "คีย์เวิร์ด")}` : ""}</div>
      ${r.rows ? `<table><tr><th>${Z("商品", "สินค้า")}</th><th>${Z("访客", "ผู้เข้าชม")}</th><th>${Z("订单", "ออเดอร์")}</th><th>${Z("转化", "อัตราซื้อ")}</th></tr>${(r.preview || []).map((x) => `<tr><td>${esc((x.seller_sku || x.name || "").slice(0, 26))}</td><td>${num(x.visitors, 0)}</td><td>${num(x.orders, 0)}</td><td>${x.conversion == null ? "-" : num(x.conversion) + "%"}</td></tr>`).join("")}</table>`
        : `<div class="s">${Z("这一页没有按商品的数据。请打开「商品数据 / 商品分析 / 流量」类页面再采集。", "หน้านี้ไม่มีข้อมูลรายสินค้า เปิดหน้า「ข้อมูลสินค้า / ทราฟฟิก」แล้วเก็บใหม่")}</div>`}
      <div class="s" style="margin-top:6px">${Z("对不上 SKU 的商品：在平台后台把「卖家 SKU」填成 ERP 的 SKU（如 3DP0001-WH）。", "สินค้าที่จับคู่ไม่ได้: ตั้ง Seller SKU ในหลังร้านให้ตรงกับ SKU ใน ERP (เช่น 3DP0001-WH)")}</div>
      <div class="row"><span style="flex:1"></span>${openSys()}</div>`);
  }
  const backData = (auto) => ({ url: location.href, title: document.title, tables: tablesText(), text: (document.body.innerText || "").slice(0, 16000), auto: !!auto });

  async function run() {
    B.disabled = true; const label = B.textContent; B.textContent = Z("采集中…", "กำลังเก็บ…");
    try {
      if (isBackPage()) renderBack(await call("/api/v1/ops/ext/backend", backData(false)));
      else if (isSearch()) renderSearch(await call("/api/v1/ops/ext/search", collectSearch()));
      else if (isShop()) renderShop(await call("/api/v1/ops/ext/shop", collectShop()));
      else renderFront(await call("/api/v1/ops/ext/competitor", collectFront()));
    } finally { B.disabled = false; B.textContent = label; }
  }
  B.onclick = run;
  const pageKind = () => (isBackPage() ? "back" : isFront() ? "front" : isSearch() ? "search" : isShop() ? "shop" : "");
  chrome.runtime.onMessage.addListener((m, _s, reply) => {
    if (!m || typeof m.type !== "string" || !m.type.startsWith("oa-")) return false;
    if (m.type === "oa-run") { if (pageKind()) { run(); reply({ ok: true }); } else reply({ ok: false }); return false; }
    // 巡逻控制台：看一眼是不是验证码、慢慢滚、读页面（发送由控制台做）
    if (m.type === "oa-check") { reply({ ok: true, captcha: isCaptcha(), url: location.href, kind: pageKind() }); return false; }
    if (m.type === "oa-scroll") { slowScroll(m.ms || 4000).then(() => reply({ ok: true, captcha: isCaptcha() })); return true; }
    if (m.type === "oa-collect") {
      if (isCaptcha()) { reply({ ok: false, captcha: true }); return false; }
      reply({ ok: true, data: m.kind === "search" ? collectSearch() : m.kind === "shop" ? collectShop() : collectFront() });
      return false;
    }
    return false;
  });

  // 卖家中心数据页自动采集：打开带数据表格的页面，停 8 秒后采一次；同一页 12 小时内不重复（插件设置里可以关）。只读你自己打开的这一页。
  const BACK_WORDS = /ผู้เข้าชม|Visitors|访客|ยอดเข้าชม|Page ?Views|การดูสินค้า|Conversion|อัตราการ(?:ซื้อ|แปลง)|Search Volume|ปริมาณการค้นหา|Impressions|การแสดงผล|Add to Cart|เพิ่มลงรถเข็น/i;
  async function autoBack() {
    if (!isBackPage()) return;
    const s = await chrome.storage.sync.get({ oa_auto_back: true });
    if (s.oa_auto_back === false) return;
    const o = await chrome.storage.local.get({ oaBackDone: {} });
    const key = location.host + location.pathname + location.hash.split("?")[0];
    const done = o.oaBackDone || {};
    if (Date.now() - (done[key] || 0) < 12 * 3600e3) return;
    const tt = tablesText();
    if (tt.split("\n").length < 4 || !BACK_WORDS.test(tt)) return;
    done[key] = Date.now();
    const keep = Object.entries(done).sort((a, b) => b[1] - a[1]).slice(0, 200);
    await chrome.storage.local.set({ oaBackDone: Object.fromEntries(keep) });
    const r = await call("/api/v1/ops/ext/backend", backData(true));
    const label = B.textContent;
    B.textContent = r.ok ? Z(`✅ 已自动采集 ${r.rows || 0} 个商品`, `✅ เก็บอัตโนมัติ ${r.rows || 0} สินค้า`) : Z("⚠️ 自动采集没成功，点我看看", "⚠️ เก็บอัตโนมัติไม่สำเร็จ กดดู");
    if (!r.ok) B.onclick = () => { renderBack(r); B.onclick = run; B.textContent = label; };
    else setTimeout(() => (B.textContent = label), 5000);
  }
  let autoTimer = null;
  function refresh() {
    const k = pageKind();
    if (k === "back") { clearTimeout(autoTimer); autoTimer = setTimeout(autoBack, 8000); }
    B.textContent = k === "back" ? Z("📥 采集本页数据", "📥 เก็บข้อมูลหน้านี้") : k === "search" ? Z("🔭 采集搜索结果", "🔭 เก็บผลการค้นหา")
      : k === "shop" ? Z("🏪 采集店铺", "🏪 เก็บข้อมูลร้าน") : Z("📊 采集竞品", "📊 เก็บข้อมูลคู่แข่ง");
    B.style.display = k ? "" : "none";
    if (k) mount();
    refreshTray();
  }
  let last = "";
  setInterval(() => { if (location.href !== last) { last = location.href; refresh(); } scanCards(); }, 1500);
  refresh(); scanCards();
})();
