// 测试用（t_curate2501.py 调用）：在无头 Chromium 里打开保存的模型网站列表页（不联网），载入扩展的站点包解释器
// （extension/cur_sites_builtin.js + cur_sites.js），用 CuratorSites.listCards 读卡片，打印 JSON。
// 用法：node cards_check.js <扩展目录> <样例 HTML> <假装的页面地址>
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");
(async () => {
  const [extDir, html, url] = process.argv.slice(2);
  const b = await chromium.launch();
  try {
    const pg = await b.newPage();
    await pg.route("**/*", (r) => (r.request().url() === url ? r.fulfill({ status: 200, contentType: "text/html", body: fs.readFileSync(html, "utf-8") }) : r.abort()));
    await pg.goto(url);
    for (const f of ["cur_sites_builtin.js", "cur_sites.js"]) await pg.addScriptTag({ content: fs.readFileSync(path.join(extDir, f), "utf-8") });
    const out = await pg.evaluate(async () => {
      const sites = await globalThis.CuratorSites.load();
      const site = globalThis.CuratorSites.siteForHost(sites, location.hostname);
      return globalThis.CuratorSites.listCards(site, document).map((c) => ({ url: c.url, title: c.title, thumb: c.thumb, thumb_w: c.thumb_w, author: c.author }));
    });
    process.stdout.write(JSON.stringify(out));
  } finally { await b.close(); }
})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
