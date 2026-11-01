// v2.53 截图：编辑产品页 ③（收起的摘要、规格切换 + 概览表、组装视图的零件选择 + 爆炸图、摆盘画布）。
// 用法：node tests/ui/shot253.js --base http://127.0.0.1:端口 --out 截图文件夹 [--lang zh|th] [--pid 3DP0002]
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
  const t0 = Date.now();
  await pg.evaluate((id) => openProduct(id), PID);
  await pg.waitForSelector("#m3-top .m3-specs", { timeout: 20000 });
  const loadMs = Date.now() - t0;
  await pg.waitForTimeout(2500);
  const shot = async (name, sel) => {
    const r = await pg.evaluate((s) => { const e = document.querySelector(s); if (!e) return null;
      document.querySelectorAll("body *").forEach((x) => { const p = getComputedStyle(x).position; if ((p === "fixed" || p === "sticky") && !e.contains(x)) x.style.visibility = "hidden"; });
      const b = e.getBoundingClientRect();
      return { x: b.left + scrollX, y: b.top + scrollY, width: b.width, height: b.height }; }, sel);
    await pg.screenshot({ path: path.join(OUT, `${LANG}_${name}.png`), fullPage: true, ...(r ? { clip: r } : {}) });
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
    for (const el of root.querySelectorAll("[title]")) if (R.test(el.title) && !el.closest("[data-notr],.hidden")) out.push("title: " + el.title.slice(0, 60));
    return out;
  }, [sel, HAN.source]);
  const bad = new Set();
  const lazy = await pg.evaluate(() => ({ asm: !!window.ASM, planCanvas: !!document.querySelector("#plan-box canvas") }));
  await pg.evaluate(() => document.querySelector("#model-card").scrollIntoView());
  await shot("1_section3_collapsed", "#model-card");
  if (LANG === "th") (await han("#model-card")).forEach((x) => bad.add(x));
  // 规格切换 + 概览：点「无盖」那一行
  await pg.evaluate(() => { const r = document.querySelector('#m3-top tr[data-m3-row="无盖"]'); if (r) r.click(); });
  await pg.waitForTimeout(2500);
  await shot("2_spec_switch_overview", "#m3-top");
  // 回主模型，打开组装视图
  await pg.evaluate(() => document.querySelector('#m3-top [data-m3-spec=""]').click());
  await pg.waitForTimeout(1500);
  await pg.evaluate(() => document.querySelector("#btn-asm").click());
  await pg.waitForSelector("#asm-box .asm-pick", { timeout: 30000 });
  await pg.waitForTimeout(3000);
  await shot("3_assembly_picker", "#asm-box");
  if (LANG === "th") (await han("#asm-box")).forEach((x) => bad.add(x));
  await pg.evaluate(() => document.querySelector('#asm-box [data-asm="explode"]').click());
  await pg.waitForTimeout(2500);
  await shot("4_assembly_exploded", "#asm-box");
  await pg.evaluate(() => document.querySelector('#asm-box [data-asm="explode"]').click());
  await pg.waitForTimeout(500);
  // 自动组合（几何）
  await pg.evaluate(() => document.querySelector('#asm-box [data-asm="auto"]').click());
  await pg.waitForTimeout(6000);
  await shot("5_assembly_auto", "#asm-box");
  if (LANG === "th") (await han("#asm-box")).forEach((x) => bad.add(x));
  // 打印方案
  await pg.evaluate(() => { const b = document.querySelector('#plan-sum [data-m3="plan"]'); b.scrollIntoView(); b.click(); });
  await pg.waitForSelector("#plan-box canvas", { timeout: 30000 });
  await pg.waitForTimeout(2000);
  await shot("6_plan_open", "#plan-sec");
  if (LANG === "th") (await han("#plan-sec")).forEach((x) => bad.add(x));
  // 「大号」= 主模型 × 150%
  await pg.evaluate(() => document.querySelector('#m3-top [data-m3-spec="大号"]').click());
  await pg.waitForTimeout(4000);
  await shot("7_scaled_spec", "#model-card");
  if (LANG === "th") (await han("#model-card")).forEach((x) => bad.add(x));
  console.log(JSON.stringify({ lang: LANG, load_ms: loadMs, lazy_on_load: lazy, errors: errs, th_chinese: [...bad] }, null, 1));
  await b.close();
})().catch((e) => { console.error(e); process.exit(2); });
