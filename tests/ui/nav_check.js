// v2.53「返回」回到原来的地方（Node + Playwright）：
//   1. 选品 → 采集箱（选文件夹 + 搜索 + 往下滚）→ 编辑 →「← 返回」→ 还是那个文件夹 / 搜索 / 滚动位置，刚编辑的那张卡片闪一下
//   2. 同样的流程用浏览器后退键；在编辑页刷新后「← 返回」也回得去
//   3. 产品库（搜索）→ 编辑 → 返回：搜索框还在，那一行闪一下
//   4. 订单 → 订单详情抽屉 → 浏览器后退：先关抽屉（还在订单页，那一单闪一下），再后退回到上一个页面
//   5. 商品 360 抽屉 → 编辑 → 返回：回到原来的页面，并重新打开商品 360
//   6. 盘点单（页面里的详情）→ 浏览器后退 → 列表；直接打开编辑页（没有上一页）→ 返回 = 产品库
//   7. 手机页 /m：‹ 返回 = 上一个画面；直接打开的画面 ‹ 返回 = 首页（不会退出 App）
// 用法：node tests/ui/nav_check.js --base http://127.0.0.1:8799 [--user boss] [--pass secret123]
// 一般不直接用：回归测试 tests/cases/t_nav253.py 会准备数据、起服务器再调用它。输出 OK / ERR 行。
"use strict";
const { chromium } = require("playwright");

const A = process.argv.slice(2);
const arg = (k, d) => (A.includes("--" + k) ? A[A.indexOf("--" + k) + 1] : d);
const BASE = arg("base", "http://127.0.0.1:8799");
const USER = arg("user", "boss"), PASS = arg("pass", "secret123");
let NERR = 0;
const ok = (b, m) => { console.log((b ? "OK  " : "ERR ") + m); if (!b) NERR++; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(pg, fn, arg2, ms = 8000) {
  try { await pg.waitForFunction(fn, arg2, { timeout: ms, polling: 100 }); return true; } catch { return false; }
}
const tab = (pg) => pg.evaluate(() => CUR_TAB);

async function login(browser, vp) {
  const ctx = await browser.newContext({ viewport: vp || { width: 1000, height: 360 }, locale: "zh-CN" });
  await ctx.addInitScript(() => { try { localStorage.setItem("ui_lang", "zh"); } catch (e) { /* */ } });
  const pg = await ctx.newPage();
  pg.on("pageerror", (e) => ok(false, "pageerror " + String(e.message || e).slice(0, 200)));
  pg.on("dialog", (d) => d.accept().catch(() => {}));
  await pg.goto(BASE + "/login");
  await pg.fill("#username", USER);
  await pg.fill("#password", PASS);
  await pg.click("#btn");
  await pg.waitForURL((u) => !String(u).includes("/login"), { timeout: 15000 }).catch(() => {});
  await waitFor(pg, () => window.NAV && typeof CUR_TAB !== "undefined" && CUR_TAB && window.MODKIT);
  await sleep(800);
  return { ctx, pg };
}
// 等「回来了」：页面对、恢复动作做完（闪的那一行出现）
async function waitBack(pg, want, hlText) {
  const ok1 = await waitFor(pg, (w) => CUR_TAB === w, want);
  if (!ok1) return false;
  if (!hlText) { await sleep(700); return true; }
  return waitFor(pg, (t) => [...document.querySelectorAll(".nav-hl")].some((x) => x.textContent.includes(t)), hlText, 6000);
}

async function curateFlow(pg) {
  // 准备：新建文件夹，把采集箱里的产品放进去；页面要能滚动（窗口矮）
  const d = await pg.evaluate(async () => {
    const inb = await api("/api/cur/inbox?folder=all");
    const ids = inb.rows.map((r) => r.product_id);
    const name = "NAV253 文件夹 " + Date.now();
    await api("/api/groups", { json: { name } });
    const gid = (await api("/api/groups")).groups.find((x) => x.name === name).id;
    await api("/api/groups/assign", { json: { ids, group: +gid, add: true } });
    return { ids, gid };
  });
  ok(d.ids.length >= 1, `inbox has products ${d.ids}`);
  const pid = d.ids[0];
  await pg.evaluate(() => goTab("cur_inbox"));
  await waitFor(pg, () => document.querySelector("#tab-curate [data-i-folder]"));
  await pg.click(`#tab-curate [data-i-folder="g:${d.gid}"]`);
  await waitFor(pg, (g) => { const x = document.querySelector("#tab-curate .cur-fo.on"); return x && x.dataset.iFolder === "g:" + g; }, d.gid);
  await pg.fill("#tab-curate [data-i-q]", pid);
  await waitFor(pg, (p) => { const c = document.querySelectorAll("#tab-curate .cur-ic"); return c.length >= 1 && [...c].every((x) => x.textContent.includes(p)); }, pid);
  await sleep(300);
  let y = await pg.evaluate(() => { const m = document.documentElement.scrollHeight - innerHeight; const y = Math.max(0, Math.min(m, Math.round(m * 0.7))); scrollTo(0, y); return Math.round(scrollY); });
  ok(y > 40, `inbox page scrolled (${y})`);
  const check = async (how) => {
    const s = await pg.evaluate(() => ({ tab: CUR_TAB, folder: (document.querySelector("#tab-curate .cur-fo.on") || {}).dataset?.iFolder,
      q: (document.querySelector("#tab-curate [data-i-q]") || {}).value, y: Math.round(scrollY),
      hl: [...document.querySelectorAll("#tab-curate .nav-hl")].map((x) => x.textContent.slice(0, 80)) }));
    ok(s.tab === "cur_inbox", `${how}: back in 采集箱 (${s.tab})`);
    ok(s.folder === "g:" + d.gid, `${how}: same folder (${s.folder})`);
    ok(s.q === pid, `${how}: same search (${s.q})`);
    ok(Math.abs(s.y - y) <= 4, `${how}: same scroll (${s.y} vs ${y})`);
    ok(s.hl.some((t) => t.includes(pid)), `${how}: edited card highlighted ${JSON.stringify(s.hl)}`);
  };
  const openEdit = async () => {
    // 点「编辑」时页面滚到的位置（采集箱会定时刷新卡片，按钮可能刚好被换掉：重试）
    for (let i = 0; i < 5; i++) {
      try {
        y = await pg.evaluate((p) => { const b = document.querySelector(`#tab-curate [data-c-prod="${p}"]`); b.scrollIntoView({ block: "nearest" }); return Math.round(scrollY); }, pid);
        await pg.click(`#tab-curate [data-c-prod="${pid}"]`, { timeout: 5000 });
        break;
      } catch (e) { await sleep(500); }
    }
    const okE = await waitFor(pg, (p) => CUR_TAB === "edit" && P && P.id === p, pid);
    ok(okE, "opened product editor from 采集箱");
    await sleep(500);
  };
  // ① 「← 返回」按钮
  await openEdit();
  const lab = await pg.textContent("#btn-ed-back");
  ok(/采集箱/.test(lab), `back button says where it goes: ${lab}`);
  await pg.click("#btn-ed-back");
  await waitBack(pg, "cur_inbox", pid);
  await check("返回按钮");
  // ② 浏览器后退键（安卓返回手势一样）
  await openEdit();
  await pg.goBack();
  await waitBack(pg, "cur_inbox", pid);
  await check("浏览器后退");
  // ③ 在编辑页刷新，再返回
  await openEdit();
  await pg.reload();
  const reopened = await waitFor(pg, (p) => window.NAV && typeof CUR_TAB !== "undefined" && CUR_TAB === "edit" && P && P.id === p, pid, 15000);
  ok(reopened, "reload in editor keeps the same product open");
  await sleep(800);
  await pg.click("#btn-ed-back");
  await waitBack(pg, "cur_inbox", pid);
  await check("刷新后返回");
  return pid;
}

async function libraryFlow(pg) {
  await pg.evaluate(() => goTab("library"));
  await waitFor(pg, () => document.querySelectorAll("#lib-table tbody tr[data-id]").length > 0);
  const id = await pg.evaluate(() => document.querySelector("#lib-table tbody tr[data-id]").dataset.id);
  await pg.fill("#lib-q", id);
  await sleep(300);
  await pg.click(`#lib-table [data-edit="${id}"]`);
  ok(await waitFor(pg, (p) => CUR_TAB === "edit" && P && P.id === p, id), "library → editor");
  await sleep(400);
  ok(/产品库/.test(await pg.textContent("#btn-ed-back")), "back button says 产品库");
  await pg.click("#btn-ed-back");
  await waitBack(pg, "library", id);
  const s = await pg.evaluate(() => ({ q: $("#lib-q").value, hl: [...document.querySelectorAll("#lib-table .nav-hl")].map((x) => x.dataset.id) }));
  ok(s.q === id && s.hl.includes(id), `library search kept + row highlighted ${JSON.stringify(s)}`);
  return id;
}

async function orderFlow(pg) {
  await pg.evaluate(() => goTab("orders"));
  await waitFor(pg, () => document.querySelector("#ord-queues [data-otab='all'], [data-otab='all']"));
  await pg.click("[data-otab='all']");
  const has = await waitFor(pg, () => document.querySelectorAll("tr[data-oid]").length > 0, null, 6000);
  if (!has) { ok(true, "no orders in test data — order drawer flow skipped"); return; }
  const oid = await pg.evaluate(() => document.querySelector("tr[data-oid]").dataset.oid);
  await pg.click(`tr[data-oid="${oid}"] td:nth-child(3)`);
  ok(await waitFor(pg, () => !document.querySelector("#ord-detail").classList.contains("hidden")), "order detail drawer opened");
  await sleep(300);
  await pg.goBack();
  ok(await waitFor(pg, () => document.querySelector("#ord-detail").classList.contains("hidden")), "browser back closes the order drawer");
  await sleep(300);
  ok(await tab(pg) === "orders", "still on the orders page after closing the drawer");
  ok(await waitFor(pg, (o) => !!document.querySelector(`tr[data-oid="${o}"].nav-hl`), oid, 3000), "that order row highlighted");
  await pg.goBack();
  ok(await waitFor(pg, () => CUR_TAB === "library"), "second back → the page before orders (产品库)");
  ok(await pg.evaluate(() => $("#lib-q").value !== ""), "产品库 search still there");
}

async function p360Flow(pg, pid) {
  await pg.evaluate(() => goTab("cur_inbox"));
  await waitFor(pg, () => CUR_TAB === "cur_inbox" && document.querySelector("#tab-curate .cur-ic"));
  await sleep(500);
  await pg.evaluate((p) => P360.open(p), pid);
  await waitFor(pg, () => document.querySelector(".p360.on [data-p360-act='edit']"));
  await pg.click(".p360.on [data-p360-act='edit']");
  ok(await waitFor(pg, (p) => CUR_TAB === "edit" && P && P.id === p, pid), "商品 360 → editor");
  await sleep(500);
  await pg.click("#btn-ed-back");
  ok(await waitFor(pg, () => CUR_TAB === "cur_inbox"), "editor → back to 采集箱 (under the 360 drawer)");
  ok(await waitFor(pg, () => !!document.querySelector(".p360.on")), "商品 360 drawer reopened");
  await pg.goBack();
  ok(await waitFor(pg, () => !document.querySelector(".p360.on")), "browser back closes 商品 360");
  ok(await tab(pg) === "cur_inbox", "still in 采集箱");
}

async function stocktakeFlow(pg) {
  await pg.evaluate(() => goTab("inv_stocktake"));
  const has = await waitFor(pg, () => document.querySelector("#tab-inv_stocktake [data-stdoc]"), null, 8000);
  if (!has) { ok(true, "no stocktake doc — flow skipped"); return; }
  await pg.click("#tab-inv_stocktake [data-stdoc]");
  ok(await waitFor(pg, () => document.querySelector("#st-back")), "stocktake doc opened");
  await pg.goBack();
  ok(await waitFor(pg, () => !document.querySelector("#st-back") && document.querySelector("#tab-inv_stocktake [data-stdoc]")), "browser back → stocktake list");
  ok(await tab(pg) === "inv_stocktake", "still on 盘点");
  await pg.click("#tab-inv_stocktake [data-stdoc]");
  await waitFor(pg, () => document.querySelector("#st-back"));
  await pg.click("#st-back");
  ok(await waitFor(pg, () => !document.querySelector("#st-back") && document.querySelector("#tab-inv_stocktake [data-stdoc]")), "← 返回列表 → list");
  ok(await waitFor(pg, () => !!document.querySelector("#tab-inv_stocktake .nav-hl"), null, 3000), "that stocktake row highlighted");
}

async function todoFlow(pg) {
  // 🔔 待办 → 点一条去对应页面 → 浏览器后退：回到原来的页面（待办抽屉那一条跳过）
  await pg.evaluate(() => goTab("library"));
  await waitFor(pg, () => CUR_TAB === "library");
  await sleep(400);
  await pg.evaluate(() => SHELL.openTodo());
  const has = await waitFor(pg, () => document.querySelector(".sh-drawer:not(.hidden) [data-todo-go]"), null, 8000);
  if (!has) { ok(true, "no todo items — flow skipped"); return; }
  const go = await pg.evaluate(() => { const b = [...document.querySelectorAll(".sh-drawer [data-todo-go]")].find((x) => x.dataset.todoGo !== "library"); if (b) b.click(); return b ? b.dataset.todoGo : null; });
  if (!go) { ok(true, "no todo pointing elsewhere — flow skipped"); return; }
  ok(await waitFor(pg, () => CUR_TAB !== "library" && document.querySelector(".sh-drawer").classList.contains("hidden")), `todo → ${go}`);
  await sleep(600);
  await pg.goBack();
  ok(await waitFor(pg, () => CUR_TAB === "library"), "back from the todo target → 产品库");
  ok(await pg.evaluate(() => document.querySelector(".sh-drawer").classList.contains("hidden")), "todo drawer stays closed");
}

async function deepLink(browser, pid) {
  // 新标签页直接打开编辑页（没有上一页）：返回 = 产品库
  const { ctx, pg } = await login(browser);
  await pg.evaluate((p) => openProduct(p, false, { nav: "replace" }), pid);
  ok(await waitFor(pg, () => CUR_TAB === "edit"), "deep link: editor open");
  await sleep(400);
  ok(await pg.evaluate(() => !NAV.canBack()), "deep link: no previous page");
  await pg.click("#btn-ed-back");
  ok(await waitFor(pg, () => CUR_TAB === "library"), "deep link: back → 产品库 (fallback)");
  await ctx.close();
}

async function mobile(browser) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 700 }, isMobile: true });
  await ctx.addInitScript(() => { try { localStorage.setItem("ui_lang", "zh"); } catch (e) { /* */ } });
  const pg = await ctx.newPage();
  pg.on("pageerror", (e) => ok(false, "/m pageerror " + String(e.message || e).slice(0, 200)));
  await pg.goto(BASE + "/m");
  await waitFor(pg, () => document.querySelector("#lg-u"));
  await pg.fill("#lg-u", USER);
  await pg.fill("#lg-p", PASS);
  await pg.press("#lg-p", "Enter");
  await waitFor(pg, () => document.querySelector("#view [data-go]"));
  const tiles = await pg.$$eval("#view [data-go]", (bs) => bs.map((b) => b.dataset.go));
  const t = tiles.find((x) => x !== "home") || tiles[0];
  await pg.click(`#view [data-go="${t}"]`);
  await waitFor(pg, (x) => location.hash.startsWith("#/" + x), t);
  await sleep(400);
  await pg.click("#back");
  ok(await waitFor(pg, () => location.hash === "#/home" || location.hash === "" || location.hash === "#/"), "/m ‹ back → previous screen (home)");
  // 直接打开某个画面：‹ 返回 = 首页，不离开 /m
  await pg.goto(BASE + "/m#/" + t);
  await waitFor(pg, () => !document.querySelector("#back").classList.contains("hidden"));
  await sleep(500);
  await pg.click("#back");
  await sleep(800);
  ok(pg.url().includes("/m"), `/m deep link ‹ back stays in /m (${pg.url()})`);
  ok(await pg.evaluate(() => document.querySelector("#back").classList.contains("hidden")), "/m deep link ‹ back → home");
  await ctx.close();
}

(async () => {
  const browser = await chromium.launch();
  try {
    const { ctx, pg } = await login(browser);
    let pid = null;
    for (const [name, fn] of [["curate", () => curateFlow(pg)], ["library", () => libraryFlow(pg)], ["orders", () => orderFlow(pg)],
      ["p360", () => p360Flow(pg, pid)], ["stocktake", () => stocktakeFlow(pg)], ["todo", () => todoFlow(pg)]]) {
      try { const r = await fn(); if (name === "curate") pid = r; } catch (e) { ok(false, `${name} flow crashed: ${String(e.message || e).split("\n")[0]}`); }
    }
    await ctx.close();
    try { await deepLink(browser, pid); } catch (e) { ok(false, "deep link crashed: " + String(e.message || e).split("\n")[0]); }
    try { await mobile(browser); } catch (e) { ok(false, "mobile crashed: " + String(e.message || e).split("\n")[0]); }
  } finally { await browser.close(); }
  console.log(`NAV ERRORS ${NERR}`);
  process.exit(NERR ? 1 : 0);
})().catch((e) => { console.log("ERR crashed " + String(e && e.stack || e)); process.exit(1); });
