// 界面语言检查（Node + Playwright）：登录后把每个大菜单 → 每个子菜单 → 页面里的页签、常用弹窗 / 抽屉、手机页都点一遍，
// 收集看得见的文字：
//   泰文界面：带中文字的文字（不在 [data-notr] 里的 = 漏翻）
//   中文界面：带泰文字的系统文字、直接显示出来的英文代码（例如 order_status、product、custom）
// 不算问题：[data-notr] 里的原始数据（买家消息、产品名、备注）；中文界面里 [data-i18n-ok] 标出的「中泰对照」例子
// 用法：node tests/ui/i18n_sweep.js --base http://127.0.0.1:8799 [--lang th,zh] [--out report.json] [--users boss,nok,lek] [--zhusers boss]
//        [--pass secret123] [--wait 900] [--quick] [--audit] [--visited]
// 一般不直接用，跑 python tests/ui/i18n_check.py（自己准备数据、起服务器、出报告）或回归测试 t_i18n_sweep。
"use strict";
const { chromium } = require("playwright");
const fs = require("fs");

const ARGS = {};
for (let i = 2; i < process.argv.length; i++) {
  const a = process.argv[i];
  if (a.startsWith("--")) ARGS[a.slice(2)] = process.argv[i + 1] && !process.argv[i + 1].startsWith("--") ? process.argv[++i] : "1";
}
const BASE = ARGS.base || "http://127.0.0.1:8799";
const LANGS = (ARGS.lang || "th,zh").split(",");
const USERS = (ARGS.users || "boss,nok,lek").split(",");
const ZH_USERS = ARGS.zhusers ? ARGS.zhusers.split(",") : USERS;      // 中文界面只查哪几个账号（回归测试只查老板，省时间）
const PASS = ARGS.pass || "secret123";
const QUICK = !!ARGS.quick;
const WAIT = +(ARGS.wait || 900);

// ---- 在页面里跑：收集看得见的问题文字 ----
const COLLECT = ([lang, audit]) => {
  const CJK = /[㐀-䶿一-鿿]/;
  const THAI = /[ก-ฺเ-๛]/;   // 泰文字母（不算 ฿）
  // 直接显示出来的英文代码：snake_case 或几个常见状态码
  const CODE = /^[a-z][a-z0-9]*(_[a-z0-9]+)+$/;
  const WORDS = new Set(["product", "custom", "pending", "done", "draft", "open", "closed", "waiting", "todo", "new", "paid", "shipped",
    "cancelled", "canceled", "refunded", "active", "archived", "manual", "auto", "owner", "listing", "production", "buyer", "seller",
    "wholesale", "price", "unknown", "ignored", "failed", "queued", "running", "ok", "error", "warn", "info", "bad", "rent", "pack",
    "material", "filament", "resin", "unpaid", "delivered", "returned", "lost", "packed", "printing", "ready"]);
  const RAW_SEL = "[data-notr], script, style, textarea, code, pre, kbd, [contenteditable=true], .rte-body, svg";
  // 整块 data-notr、文字自己按语言写（Z(中, 泰)）的地方：里面照样查，只跳过里面再标了 data-notr 的原始数据
  const OWN = new Set(["p360"]);
  const rawOf = (el) => { const r = el.closest(RAW_SEL); return !!r && !(OWN.has(r.id) && r.matches("[data-notr]")); };
  const vis = (el) => {
    if (!el || !el.getClientRects().length) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== "hidden" && cs.display !== "none" && +cs.opacity !== 0;
  };
  const path = (el) => {
    const out = [];
    for (let e = el; e && e !== document.body && out.length < 4; e = e.parentElement) {
      let s = e.tagName.toLowerCase();
      if (e.id) { s += "#" + e.id; out.unshift(s); break; }
      const cl = [...e.classList].filter((c) => !/^(on|active|hidden)$/.test(c)).slice(0, 2);
      if (cl.length) s += "." + cl.join(".");
      out.unshift(s);
    }
    return out.join(" > ");
  };
  const bad = (s) => {
    s = (s || "").trim();
    if (!s) return "";
    if (lang === "th") {
      if (CJK.test(s)) return "zh";
    } else if (THAI.test(s)) return "th";
    if (CODE.test(s) || WORDS.has(s)) return "code";
    return "";
  };
  const res = [];
  const seen = new Set();
  const add = (kind, text, el, where) => {
    if (kind === "th" && el.closest("[data-i18n-ok]")) return;   // 故意中泰对照的例子（例如「中文 | ไทย」的写法说明）
    const k = kind + "|" + text;
    if (seen.has(k)) return;
    seen.add(k);
    res.push({ kind, text: text.trim().slice(0, 160), where, path: path(el) });
  };
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
  let n;
  while ((n = w.nextNode())) {
    if (n.nodeType === 1) {
      if (rawOf(n)) continue;
      for (const a of ["placeholder", "title"]) {
        const v = n.getAttribute(a);
        const k = v && bad(v);
        if (k && k !== "code" && n.tagName !== "OPTION" && vis(n)) add(k, v, n, a);
      }
      if ((n.tagName === "INPUT" && /^(button|submit)$/.test(n.type)) && vis(n)) { const k = bad(n.value); if (k) add(k, n.value, n, "value"); }
      if (n.tagName === "OPTION") {
        const sel = n.closest("select");
        const k = sel && vis(sel) && !rawOf(sel) && bad(n.textContent);
        if (k) add(k, n.textContent, sel, "option");
      }
      continue;
    }
    const el = n.parentElement;
    // --audit：列出 data-notr 里带中文的文字（看看有没有把系统文字也标成了原始数据；只供人工看，不算问题）
    if (audit && lang === "th" && el && el.closest("[data-notr]") && !el.closest("script, style, textarea") && vis(el) && CJK.test(n.nodeValue)) add("notr", n.nodeValue, el, "text");
    if (!el || el.tagName === "OPTION" || rawOf(el) || !vis(el)) continue;
    const k = bad(n.nodeValue);
    if (k) add(k, n.nodeValue, el, "text");
  }
  return res;
};

// 页面里的页签（点一遍）
const INNER = ".ux-tab, [data-ux-tab], [data-cfgtab], [data-otab], [data-iv], [data-cview], [data-lst-tab], #lw-view [data-view], .seg > button, .ops-tabs button, [data-sub-tab], [data-fintab]";

const REPORT = { base: BASE, pages: {}, errors: [], visited: [] };
let TOTAL = 0;
function record(lang, user, page, items) {
  const key = `${lang} · ${user} · ${page}`;
  const g = (REPORT._seen = REPORT._seen || {});
  const fresh = items.filter((x) => {
    const k = lang + "|" + x.kind + "|" + x.text;
    if (g[k]) return false;
    g[k] = 1;
    return true;
  });
  if (fresh.length) { REPORT.pages[key] = (REPORT.pages[key] || []).concat(fresh); TOTAL += fresh.filter((x) => x.kind !== "notr").length; }
}

async function settle(pg, ms) {
  try { await pg.waitForLoadState("networkidle", { timeout: 4000 }); } catch { /* 有长连接 */ }
  await pg.waitForTimeout(ms == null ? WAIT : ms);
}

async function collect(pg, lang, user, page) {
  REPORT.visited.push(`${lang} · ${user} · ${page}`);
  try { record(lang, user, page, await pg.evaluate(COLLECT, [lang, !!ARGS.audit])); } catch (e) { REPORT.errors.push(`${user} ${page}: collect ${e.message.split("\n")[0]}`); }
}

async function login(browser, user, lang) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: lang === "th" ? "th-TH" : "zh-CN" });
  await ctx.addInitScript((l) => { try { localStorage.setItem("ui_lang", l); } catch (e) { /* */ } }, lang);
  const pg = await ctx.newPage();
  pg.on("pageerror", (e) => REPORT.errors.push(`${lang} ${user}: pageerror ${String(e.message || e).slice(0, 200)}`));
  pg.on("dialog", (d) => {
    const m = d.message();
    if (lang === "th" && /[\u3400-\u9fff]/.test(m)) record(lang, user, "dialog", [{ kind: "zh", text: m.slice(0, 160), where: "dialog", path: d.type() }]);
    d.dismiss().catch(() => {});
  });
  await pg.goto(BASE + "/login");
  await pg.fill("#username", user);
  await pg.fill("#password", PASS);
  await pg.click("#btn");
  await pg.waitForURL((u) => !String(u).includes("/login"), { timeout: 15000 }).catch(() => {});
  await settle(pg, 1500);
  return pg;
}

async function innerTabs(pg, lang, user, page, scope) {
  const sel = `${scope} :is(${INNER})`;
  const n = await pg.locator(sel).count();
  const done = new Set();
  for (let i = 0; i < Math.min(n, 40); i++) {
    const loc = pg.locator(sel).nth(i);
    let key;
    try {
      if (!(await loc.isVisible())) continue;
      key = await loc.evaluate((b) => Object.entries(b.dataset).map(([k, v]) => k + "=" + v).join(",") || b.textContent.trim().slice(0, 20));
      if (done.has(key)) continue;
      done.add(key);
      await loc.click({ timeout: 3000 });
      await settle(pg, 600);
      await collect(pg, lang, user, `${page} › ${key}`);
    } catch (e) { /* 点不了就算了 */ }
  }
}

// 页面里的「打开详情 / 新建」：点第一个，弹窗 / 抽屉里的文字也查一遍，然后关掉（不保存）
const OPENERS = ["[data-oid]", "[data-c-open]", "[data-po]", "[data-iid]", "[data-item]", "[data-doc]", "[data-sup]", "[data-loc]", "[data-edit]", "[data-hid]", "[data-cid]", "PLUS"];
async function closeAll(pg) {
  await pg.evaluate(() => {
    if (window.MODAL && !document.querySelector("#modal").classList.contains("hidden")) MODAL.close();
    if (window.P360) P360.close();
    if (window.SHELL) SHELL.closeTodo();
    document.querySelectorAll(".modal:not(#modal):not(.hidden), .sheet:not(.hidden)").forEach((m) => { const c = m.querySelector("[data-mclose], .close, [data-close]"); if (c) c.click(); else m.classList.add("hidden"); });
  }).catch(() => {});
}
async function openers(pg, lang, user, page, tab) {
  for (const sel of OPENERS) {
    const handle = await pg.evaluateHandle((sel) => {
      const panel = document.querySelector(".panel:not(.hidden)");
      if (!panel) return null;
      const all = sel === "PLUS" ? [...panel.querySelectorAll("button")].filter((b) => /^\s*[+＋➕]\s*[^\d\s]/.test(b.textContent)) : [...panel.querySelectorAll(sel)];
      return all.find((e) => e.getClientRects().length && !e.disabled) || null;
    }, sel);
    const el = handle.asElement();
    if (!el) continue;
    const before = await pg.evaluate(() => location.hash);
    try { await el.click({ timeout: 2000 }); } catch (e) { continue; }
    await settle(pg, 700);
    const opened = await pg.evaluate(() => !!document.querySelector("#modal:not(.hidden), .p360.on, .sh-drawer:not(.hidden), .modal:not(.hidden), .sheet:not(.hidden)"));
    const moved = (await pg.evaluate(() => location.hash)) !== before;
    if (opened || moved) await collect(pg, lang, user, `${page} ⧉ ${sel}`);
    await closeAll(pg);
    if (moved && tab) { await pg.evaluate((t) => goTab(t), tab).catch(() => {}); await settle(pg, 500); }
  }
}

async function sweepMain(pg, lang, user) {
  await collect(pg, lang, user, "home");
  const mods = await pg.$$eval("#modnav .mod", (bs) => bs.filter((b) => b.getClientRects().length).map((b) => b.dataset.mod));
  for (const mod of mods) {
    await pg.click(`#modnav .mod[data-mod="${mod}"]`).catch(() => {});
    await settle(pg);
    const tabs = await pg.$$eval("#subnav .tab", (bs) => bs.filter((b) => !b.classList.contains("hidden") && b.getClientRects().length).map((b) => b.dataset.tab));
    for (const tab of tabs.length ? tabs : [null]) {
      if (tab) {
        await pg.evaluate((t) => goTab(t), tab).catch(() => {});
        await settle(pg);
      }
      const page = `${mod}/${tab || "-"}`;
      await collect(pg, lang, user, page);
      if (!QUICK) {
        await innerTabs(pg, lang, user, page, ".panel:not(.hidden)");
        await openers(pg, lang, user, page, tab);
      }
      // 回到这个页面（有的页签会跳到别的页面）
    }
  }
}

async function sweepPopups(pg, lang, user) {
  // 🔔 待办抽屉
  if (await pg.evaluate(() => !!window.SHELL)) {
    await pg.evaluate(() => SHELL.openTodo()).catch(() => {});
    await settle(pg);
    await collect(pg, lang, user, "drawer: to-do");
    await innerTabs(pg, lang, user, "drawer: to-do", ".sh-drawer:not(.hidden)");
    await pg.evaluate(() => SHELL.closeTodo()).catch(() => {});
    // 🔍 搜索
    await pg.evaluate(() => SHELL.openSearch()).catch(() => {});
    await pg.waitForTimeout(300);
    for (const q of ["3DP", "Mali", "LZ"]) {
      const inp = pg.locator("#gs-q").first();
      if (await inp.count()) { await inp.fill(q).catch(() => {}); await settle(pg); await collect(pg, lang, user, `search: ${q}`); }
    }
    await pg.keyboard.press("Escape").catch(() => {});
    await pg.waitForTimeout(300);
  }
  // 产品 360 抽屉
  const pid = await pg.evaluate(async () => { try { const r = await api("/api/products"); const l = r.items || r.products || r; return (l[0] || {}).id; } catch (e) { return null; } });
  if (pid && (await pg.evaluate(() => !!window.P360))) {
    await pg.evaluate((id) => P360.open(id), pid).catch(() => {});
    await settle(pg, 1500);
    await collect(pg, lang, user, "drawer: product 360");
    await pg.evaluate(() => P360.close()).catch(() => {});
  }
  // 订单详情
  if (await pg.evaluate(() => !!(window.OPS && OPS.openOrder))) {
    const oid = await pg.evaluate(async () => { try { const r = await api("/api/orders?limit=5"); return ((r.items || r.orders || [])[0] || {}).id; } catch (e) { return null; } });
    if (oid) {
      await pg.evaluate((id) => OPS.openOrder(id), oid).catch(() => {});
      await settle(pg, 1200);
      await collect(pg, lang, user, "modal: order detail");
      await innerTabs(pg, lang, user, "modal: order detail", "#modal");
      await pg.evaluate(() => window.MODAL && MODAL.close && MODAL.close()).catch(() => {});
      await pg.keyboard.press("Escape").catch(() => {});
    }
  }
  // 客服聊天：打开第一个会话
  if (await pg.evaluate(() => !!document.querySelector('#subnav .tab[data-tab="cs"]:not(.role-hidden)'))) {
    await pg.evaluate(() => goTab("cs")).catch(() => {});
    await settle(pg, 1200);
    const conv = pg.locator("#tab-cs [data-cid], #tab-cs [data-conv], #tab-cs .cs-item").first();
    if (await conv.count()) {
      await conv.click().catch(() => {});
      await settle(pg, 1200);
      await collect(pg, lang, user, "cs: conversation open");
    }
  }
  // 产品编辑页
  if (pid && (await pg.evaluate(() => typeof openProduct === "function"))) {
    await pg.evaluate((id) => openProduct(id), pid).catch(() => {});
    await settle(pg, 1500);
    await collect(pg, lang, user, "goods/edit (product editor)");
  }
}

async function sweepMobile(browser, lang, user) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true });
  await ctx.addInitScript((l) => { try { localStorage.setItem("ui_lang", l); } catch (e) { /* */ } }, lang);
  const pg = await ctx.newPage();
  pg.on("pageerror", (e) => REPORT.errors.push(`${lang} ${user} /m: pageerror ${String(e.message || e).slice(0, 200)}`));
  await pg.goto(BASE + "/m");
  await settle(pg);
  await collect(pg, lang, user, "/m login");
  const u = pg.locator("#lg-u").first();
  if (await u.count()) {
    await u.fill(user);
    await pg.locator("input[type=password]").first().fill(PASS);
    await pg.locator("input[type=password]").first().press("Enter");
    await settle(pg, 1500);
  }
  await collect(pg, lang, user, "/m home");
  const tiles = await pg.$$eval("#view [data-go]", (bs) => bs.map((b) => b.dataset.go));
  for (const t of [...new Set(tiles)]) {
    await pg.click(`#view [data-go="${t}"]`).catch(() => {});
    await settle(pg);
    await collect(pg, lang, user, `/m ${t}`);
    await pg.click("#back").catch(() => {});
    await settle(pg, 400);
  }
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch();
  const t0 = Date.now();
  for (const lang of LANGS) {
    for (const user of lang === "zh" ? ZH_USERS : USERS) {
      let pg;
      try { pg = await login(browser, user, lang); } catch (e) { REPORT.errors.push(`${lang} ${user}: login ${e.message}`); continue; }
      if (!(await pg.evaluate(() => typeof goTab === "function").catch(() => false))) { REPORT.errors.push(`${lang} ${user}: not logged in`); await pg.context().close(); continue; }
      await sweepMain(pg, lang, user);
      await sweepPopups(pg, lang, user);
      await pg.context().close();
      if (user === USERS[0]) await sweepMobile(browser, lang, user);
    }
  }
  await browser.close();
  delete REPORT._seen;
  REPORT.total = TOTAL;
  REPORT.seconds = Math.round((Date.now() - t0) / 1000);
  if (ARGS.out) fs.writeFileSync(ARGS.out, JSON.stringify(REPORT, null, 1));
  for (const [page, items] of Object.entries(REPORT.pages)) {
    console.log(`\n== ${page} (${items.length})`);
    for (const x of items) console.log(`  [${x.kind}] ${x.text}   <${x.where} ${x.path}>`);
  }
  if (REPORT.errors.length) console.log("\nJS / sweep errors:\n  " + REPORT.errors.join("\n  "));
  if (ARGS.visited) console.log("\nvisited:\n  " + REPORT.visited.join("\n  "));
  console.log(`\nI18N_SWEEP total=${TOTAL} pages=${Object.keys(REPORT.pages).length} visited=${REPORT.visited.length} errors=${REPORT.errors.length} ${REPORT.seconds}s`);
})().catch((e) => { console.error(e); process.exit(2); });
