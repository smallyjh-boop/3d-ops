// v2.55 截图：统一的打印方案编辑器（编辑产品页 ③：多选 + 选中后的工具条 + 方向卡片 + 每盘参数 / 检查）、
// 「生产 → 打印方案」窗口（同一个编辑器 + 模型文件 / 切片文件）。
// 用法：node tests/ui/shot255.js --base http://127.0.0.1:端口 --out 截图文件夹 [--lang zh|th] [--pid 3DP0002]
// 服务器用 tests/ui/i18n_server.py 起（账号 boss / secret123）。页面报错、泰文界面里的中文都打印出来。
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const BASE = arg("--base", "http://127.0.0.1:8799"), OUT = arg("--out", "."), LANG = arg("--lang", "zh"), PID = arg("--pid", "3DP0002");
const HAN = /[一-鿿]/;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await chromium.launch({ args: ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"] });
  const ctx = await b.newContext({ viewport: { width: 1400, height: 1000 } });
  await ctx.addInitScript((l) => { try { localStorage.setItem("ui_lang", l); } catch (e) { /* */ } }, LANG);
  const pg = await ctx.newPage();
  const errs = [];
  pg.on("pageerror", (e) => errs.push(String(e.stack || e).slice(0, 400)));
  pg.on("dialog", (d) => d.accept());
  await pg.goto(BASE + "/login");
  await pg.fill("#username", "boss"); await pg.fill("#password", "secret123"); await pg.click("#btn");
  await pg.waitForTimeout(2500);
  await pg.evaluate((id) => openProduct(id), PID);
  await pg.waitForSelector("#m3-top .m3-specs", { timeout: 20000 });
  await pg.waitForTimeout(2000);
  const shot = async (name, sel) => {
    const r = await pg.evaluate((s) => { const e = document.querySelector(s); if (!e) return null;
      document.querySelectorAll("body *").forEach((x) => { const p = getComputedStyle(x).position; if ((p === "fixed" || p === "sticky") && !e.contains(x) && !x.contains(e)) { x.dataset.shotHid = "1"; x.style.visibility = "hidden"; } });
      const b = e.getBoundingClientRect();
      return { x: b.left + scrollX, y: b.top + scrollY, width: b.width, height: b.height }; }, sel);
    await pg.screenshot({ path: path.join(OUT, `${LANG}_${name}.png`), fullPage: true, ...(r ? { clip: r } : {}) });
    await pg.evaluate(() => document.querySelectorAll("[data-shot-hid]").forEach((x) => { x.style.visibility = ""; delete x.dataset.shotHid; }));
  };
  const han = async (sel) => pg.evaluate(([s, re]) => {
    const R = new RegExp(re), out = [];
    const root = document.querySelector(s); if (!root) return out;
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n; while ((n = w.nextNode())) {
      const t = n.nodeValue.trim(); if (!t || !R.test(t)) continue;
      if (n.parentElement.closest("[data-notr],script,style,textarea,[data-i18n-ok]")) continue;
      if (n.parentElement.closest(".hidden")) continue;
      out.push(t.slice(0, 80));
    }
    for (const el of root.querySelectorAll("[title],[placeholder]")) { const t = el.title || el.placeholder || ""; if (R.test(t) && !el.closest("[data-notr],.hidden")) out.push("attr: " + t.slice(0, 60)); }
    return out;
  }, [sel, HAN.source]);
  const bad = new Set();
  // 打开打印方案
  await pg.evaluate(() => { const x = document.querySelector('#plan-sum [data-m3="plan"]'); x.scrollIntoView(); x.click(); });
  await pg.waitForSelector("#plan-box canvas", { timeout: 30000 });
  await pg.waitForTimeout(1500);
  // 框选：在画布空白处从左下拖到中间（选中几个零件），再 Ctrl+点 加一个
  const cv = await pg.$("#plan-box canvas");
  await cv.scrollIntoViewIfNeeded();
  const bb = await cv.boundingBox();
  await pg.mouse.move(bb.x + 4, bb.y + bb.height - 4);
  await pg.mouse.down();
  await pg.mouse.move(bb.x + bb.width * 0.75, bb.y + bb.height * 0.55, { steps: 8 });
  await pg.mouse.up();
  await pg.waitForTimeout(1500);
  const nsel = await pg.evaluate(() => PLAN.state.sel.uids.length);
  // 打开第一盘的参数面板
  await pg.evaluate(() => { const d = document.querySelector("#plan-box details.pe-prm"); if (d) d.open = true; });
  await pg.waitForTimeout(800);
  await shot("1_editor_multiselect", "#plan-sec");
  if (LANG === "th") (await han("#plan-sec")).forEach((x) => bad.add(x));
  // 只选一个零件：方向卡片
  await pg.evaluate(() => { const r = document.querySelector('#plan-box .pp-items tr[data-uid]'); r.click(); });
  await pg.waitForTimeout(2500);
  await shot("2_editor_one_part_orient_cards", "#plan-box .pp-plate");
  if (LANG === "th") (await han("#plan-box")).forEach((x) => bad.add(x));
  // 快捷键：Ctrl+D 复制、M 镜像
  await pg.focus("#plan-box canvas");
  await pg.keyboard.press("Control+d");
  await pg.waitForTimeout(1500);
  await pg.focus("#plan-box canvas");
  await pg.keyboard.press("m");
  await pg.waitForTimeout(1500);
  const after = await pg.evaluate(() => ({ n: PLAN.state.plan.plates[0].items.length, mirror: PLAN.state.plan.plates[0].items.filter((x) => x.mirror).length, dirty: PLAN.dirty() }));
  // 生产 → 打印方案窗口
  await pg.evaluate(() => { PLAN.state.dirty = false; });
  await pg.evaluate(() => showTab("production"));
  await pg.waitForTimeout(1200);
  await pg.evaluate((id) => window.PROD_OPEN_RECIPE(id), PID);
  await pg.waitForSelector("#rc-plan-box canvas", { timeout: 30000 });
  await pg.waitForSelector("#rc-modal-box .rc-files-only", { timeout: 30000 });
  await pg.waitForTimeout(2000);
  const modalSel = await pg.evaluate(() => { const e = document.querySelector("#rc-plan-box"); const m = e.closest(".modal, .modal-box, [role=dialog]") || e.parentElement; m.id = m.id || "shot-modal"; return "#" + m.id; });
  await pg.evaluate((s) => { const m = document.querySelector(s); m.style.maxHeight = "none"; m.style.overflow = "visible"; m.style.position = "absolute"; m.style.height = "auto"; m.style.top = "0"; m.querySelectorAll(".modal-in").forEach((x) => { x.style.maxHeight = "none"; x.style.overflow = "visible"; }); let p = m.parentElement; while (p && p !== document.body) { p.style.maxHeight = "none"; p.style.overflow = "visible"; p.style.position = "static"; p = p.parentElement; } }, modalSel);
  await pg.waitForTimeout(500);
  await shot("3_production_modal", modalSel);
  if (LANG === "th") (await han(modalSel)).forEach((x) => bad.add(x));
  console.log(JSON.stringify({ lang: LANG, box_selected: nsel, after_keys: after, errors: errs, th_chinese: [...bad] }, null, 1));
  await b.close();
})().catch((e) => { console.error(e); process.exit(2); });
