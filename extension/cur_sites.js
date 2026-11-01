// 选品 · 站点规则解释器（扩展 3.1，从「3D选品工具」扩展 2.0 搬过来）：哪个模型网站怎么认链接、怎么读详情页、怎么换真实下载地址，
// 全部来自 ERP 的「站点包」（只是数据，不含代码；GET /api/v1/curate/ext/sites）。后台每 10 分钟问一次，存到 chrome.storage.local.curSiteRules；
// 还没连上 ERP 时用随扩展带的内置规则（cur_sites_builtin.js）。内容脚本和后台都用它。
(() => {
  if (globalThis.CuratorSites) return;
  const clean = (s, max = 9000) => String(s ?? '').replace(/\s+/g, ' ').trim().slice(0, max);
  const cleanBlock = (s, max = 9000) => String(s ?? '').replace(/\r/g, '').replace(/[ \t ]+/g, ' ').replace(/ *\n */g, '\n').replace(/\n{3,}/g, '\n\n').trim().slice(0, max);
  const htmlToText = h => {
    if (!h) return '';
    if (typeof DOMParser === 'undefined') return String(h).replace(/<[^>]+>/g, ' ');
    const withBreaks = String(h).replace(/<(br|\/p|\/div|\/li|\/h\d)[^>]*>/gi, '$&\n');
    return new DOMParser().parseFromString(withBreaks, 'text/html').body.textContent || '';
  };
  const empty = v => v === undefined || v === null || v === '' || (Array.isArray(v) && !v.length);

  async function load() {
    let stored = null;
    try { stored = (await chrome.storage.local.get('curSiteRules')).curSiteRules; } catch {}
    const builtin = globalThis.__CURATOR_SITES_BUILTIN?.sites || [];
    const list = stored?.sites?.length ? stored.sites : builtin;
    return list.map(s => ({...s, enabled: s.enabled !== false}));
  }
  const hostIn = (host, domains) => (domains || []).some(d => host === d || host.endsWith('.' + d));
  const siteForHost = (sites, host) => sites.find(s => hostIn(String(host || '').toLowerCase(), s.domains));
  const detailRegex = site => new RegExp(site.detail.path, 'i');
  function detailMatch(site, href) {
    try {
      const u = new URL(href, typeof location !== 'undefined' ? location.href : undefined);
      if (!hostIn(u.hostname.toLowerCase(), site.domains)) return null;
      const m = decodeURIComponent(u.pathname).match(detailRegex(site));
      return m ? {canonical: u.origin + m[1], id: m[site.detail.id_group || 2]} : null;
    } catch { return null; }
  }

  // ---- 取值规则
  // 字符串："a.b|c|=常量|." —— 按顺序取第一个非空（. 是当前对象本身，= 开头是常量）
  // 对象：{path, each, filter, require, list, join, template, html, div, round, mb, ext, prefix, trim_slash, max}
  function getPath(obj, path, ctx) {
    if (path === '.') return obj;
    if (path.startsWith('=')) return path.slice(1);
    if (path.startsWith('$')) return ctx?.[path.slice(1)];
    let cur = obj;
    for (const k of path.split('.')) { if (cur === null || cur === undefined) return undefined; cur = cur[k]; }
    return cur;
  }
  function pick(obj, alts, ctx, scalar) {
    for (const p of String(alts).split('|')) {
      const v = getPath(obj, p.trim(), ctx);
      if (empty(v)) continue;
      if (scalar && typeof v === 'object') continue;
      return v;
    }
    return undefined;
  }
  function template(tpl, obj, ctx) {
    return String(tpl).replace(/\{([^}]+)\}/g, (_, p) => { const v = pick(obj, p, ctx, true); return v === undefined ? '' : String(v); });
  }
  function transform(v, spec) {
    if (v === undefined || v === null) return v;
    if (spec.html) v = cleanBlock(htmlToText(v));
    if (spec.div) v = (Number(v) || 0) / spec.div;
    if (spec.round !== undefined) { const f = 10 ** spec.round; v = Math.round((Number(v) || 0) * f) / f; }
    if (spec.mb) v = Number(v) ? Math.round(Number(v) / 1024 / 1024 * 10) / 10 + ' MB' : '';
    if (spec.ext) v = String(v).split('.').pop().toLowerCase();
    if (spec.trim_slash) v = String(v).replace(/^\/+/, '');
    if (spec.prefix && v !== '') v = spec.prefix + v;
    if (spec.max && typeof v === 'string') v = clean(v, spec.max);
    return v;
  }
  function resolve(spec, obj, ctx) {
    if (spec === undefined || spec === null) return undefined;
    if (typeof spec === 'string') { const v = pick(obj, spec, ctx, false); return typeof v === 'string' ? clean(v) : v; }
    if (spec.list) {
      let out = [];
      for (const sub of spec.list) { const v = resolve(sub, obj, ctx); if (Array.isArray(v)) out.push(...v); else if (!empty(v)) out.push(v); }
      out = out.filter(x => !empty(x) && typeof x !== 'object');
      return spec.join !== undefined ? transform(out.map(String).join(spec.join), spec) : out;
    }
    if (spec.template !== undefined) return transform(template(spec.template, obj, ctx), spec);
    let v = spec.path !== undefined ? pick(obj, spec.path, ctx, !spec.each) : obj;
    if (spec.each !== undefined) {
      let arr = Array.isArray(v) ? v : [];
      if (spec.require) arr = arr.filter(x => !empty(pick(x, spec.require, ctx, false)));
      const each = spec.each;
      const scalarEach = typeof each === 'string' || each.path !== undefined || each.template !== undefined || each.list !== undefined;
      let out = arr.map(item => {
        if (scalarEach) { const r = resolve(each, item, ctx); return typeof r === 'object' ? undefined : r; }
        const o = {};
        for (const [k, sub] of Object.entries(each)) { const r = resolve(sub, item, ctx); o[k] = r === undefined ? '' : r; }
        return o;
      }).filter(x => !empty(x));
      if (spec.filter) out = out.filter(o => spec.filter.some(k => o[k]));
      return out;
    }
    return transform(v, spec);
  }
  function mapFields(fields, obj, ctx) {
    const out = {};
    for (const [k, spec] of Object.entries(fields || {})) {
      const v = resolve(spec, obj, ctx);
      if (!empty(v)) out[k] = v;
    }
    return out;
  }

  // ---- 数据来源
  function nextData(source, id) {
    const el = typeof document !== 'undefined' && document.getElementById(source.element || '__NEXT_DATA__');
    if (!el) return null;
    let data; try { data = JSON.parse(el.textContent); } catch { return null; }
    const find = source.find || {};
    const idField = find.id_field || 'id';
    let found = null; const seen = new Set();
    (function walk(o, depth) {
      if (found || !o || typeof o !== 'object' || depth > 10 || seen.has(o)) return; seen.add(o);
      if (!Array.isArray(o) && (find.any_of || []).some(keys => keys.every(k => !empty(o[k]))) && (!id || String(o[idField]) === String(id))) { found = o; return; }
      for (const v of Object.values(o)) walk(v, depth + 1);
    })(data, 0);
    return found;
  }
  async function graphql(source, ctx) {
    const vars = {};
    for (const [k, v] of Object.entries(source.variables || {})) vars[k] = template(v, {}, ctx);
    const body = {query: source.query, variables: vars};
    if (source.operation) body.operationName = source.operation;
    const resp = await fetch(source.url, {method: 'POST', credentials: source.credentials || 'omit', headers: {'content-type': 'application/json'}, body: JSON.stringify(body)});
    if (!resp.ok) return null;
    const json = await resp.json();
    if (ctx?.rec) ctx.rec.push({match: source.url.replace(/^https?:\/\//, ''), body_contains: (String(source.query).match(/(?:query|mutation)\s+(\w+)/) || [])[1] || '', data: json});
    return source.root ? getPath(json, source.root) : json;
  }
  async function jsonApi(source, ctx) {
    const url = template(source.url, {}, ctx);
    const resp = await fetch(url, {credentials: source.credentials || 'omit'});
    if (!resp.ok) return null;
    const json = await resp.json();
    if (ctx?.rec) ctx.rec.push({match: url.replace(/^https?:\/\//, ''), body_contains: '', data: json});
    return source.root ? getPath(json, source.root) : json;
  }
  // 按站点规则读取：返回 {字段...}，以及每个来源是否成功（给改版报警用）
  async function extract(site, id, ctx) {
    const out = {}, used = [];
    for (const src of site.extract?.sources || []) {
      let obj = null;
      try {
        if (src.type === 'next_data') obj = nextData(src, id);
        else if (src.type === 'graphql') obj = await graphql(src, ctx);
        else if (src.type === 'json') obj = await jsonApi(src, ctx);
      } catch { obj = null; }
      if (!obj) { used.push(src.type + ':miss'); continue; }
      const got = mapFields(src.fields, obj, ctx);
      used.push(src.type + ':' + Object.keys(got).join(','));
      for (const [k, v] of Object.entries(got)) if (empty(out[k])) out[k] = v;
    }
    return {data: out, used};
  }

  // ---- 下载：文件链接要先换成真实地址的（如 Printables）
  async function resolveDownload(site, url) {
    for (const rule of site.download || []) {
      const m = url.match(new RegExp(rule.url_regex, 'i'));
      if (!m || !rule.graphql) continue;
      const g = rule.graphql;
      const vars = {};
      for (const [k, v] of Object.entries(g.variables || {})) vars[k] = String(v).replace(/\{(\d+)\}/g, (_, n) => m[+n] || '');
      const body = {query: g.query, variables: vars};
      if (g.operation) body.operationName = g.operation;
      const resp = await fetch(g.url, {method: 'POST', credentials: g.credentials || 'include', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
      const json = await resp.json().catch(() => ({}));
      const link = getPath(json, g.link);
      if (link) return link;
      const msgs = [];
      (function walk(o, d) { if (!o || typeof o !== 'object' || d > 6) return; if (Array.isArray(o.messages)) msgs.push(...o.messages); for (const v of Object.values(o)) walk(v, d + 1); })(json, 0);
      const why = json?.errors?.[0]?.message || msgs.join('，');
      throw new Error(`${site.name} 没有给下载地址` + (why ? '：' + why : rule.fail_hint ? `（${rule.fail_hint}）` : ''));
    }
    return url;
  }

  // ---- 列表页 / 搜索页的模型卡片（扩展 3.1.1）：卡片 = 包住一个模型链接的最大的块；标题 / 图 / 作者按站点包的 list 规则读，
  // 作者那一块（头像、作者名、店铺 logo）不算。以前取「卡片里第一行字 + 第一张图」，Printables 的卡片作者在最上面，就读成了作者名 + 头像。
  const DEF_AUTHOR = '/@[^/]+|/users?/|/designers?/|/profile/|/social/';
  const DEF_AVATAR = 'avatar|/users?/|/profiles?/|/logos?/|gravatar|/badges?/|/icons?/';
  const AUTHOR_AREA = '[class*="avatar" i],[class*="author" i],[class*="user-" i],[class*="userinfo" i],[class*="designer" i],[class*="creator" i],[class*="profile" i],[data-testid*="author" i],[data-testid*="user" i]';
  function canonFn(site, base) {
    const re = detailRegex(site);
    return href => {
      try {
        const u = new URL(href, base);
        if (!hostIn(u.hostname.toLowerCase(), site.domains)) return '';
        const m = decodeURIComponent(u.pathname).match(re);
        return m ? u.origin + m[1] : '';
      } catch { return ''; }
    };
  }
  function idFn(site, base) {
    const re = detailRegex(site), g = site.detail.id_group || 2;
    return url => { try { const m = decodeURIComponent(new URL(url, base).pathname).match(re); return m ? m[g] : url; } catch { return url; } };
  }
  // 一张卡片只算一个模型：从链接往上找「只包含这一个模型」的最大的块
  function cardRoot(a, id, canon, idOf, doc) {
    let el = a;
    const body = (doc || document).body;
    while (el.parentElement && el.parentElement !== body) {
      const p = el.parentElement;
      const ids = new Set([...p.querySelectorAll('a[href]')].map(x => canon(x.getAttribute('href'))).filter(Boolean).map(idOf));
      if (ids.size > 1 || (ids.size === 1 && !ids.has(id))) break;
      el = p;
      if (el.offsetHeight > 700) break;
    }
    return el;
  }
  const txt = el => clean((el && (el.innerText || el.textContent)) || '', 300);
  const imgSrc = img => img.currentSrc || img.src || img.getAttribute('data-src') || (img.getAttribute('srcset') || '').split(',')[0].trim().split(/\s+/)[0] || '';
  function readCard(site, root, url, canon, base) {
    const L = site.list || {};
    const authorRe = new RegExp(L.author_link || DEF_AUTHOR, 'i');
    const avatarRe = new RegExp(L.avatar || DEF_AVATAR, 'i');
    const links = [...root.querySelectorAll('a[href]')];
    const pathOf = a => { try { return new URL(a.getAttribute('href'), base).pathname; } catch { return ''; } };
    const authorLinks = links.filter(a => !canon(a.getAttribute('href')) && authorRe.test(pathOf(a)));
    const inAuthor = el => authorLinks.some(a => a.contains(el)) || !!(el.closest && el.closest(AUTHOR_AREA) && root.contains(el.closest(AUTHOR_AREA)) && el.closest(AUTHOR_AREA) !== root);
    const modelLinks = links.filter(a => canon(a.getAttribute('href')) === url);
    const author = txt(authorLinks.find(a => txt(a).length > 1));
    const bad = t => !t || t.length < 2 || (author && t.toLowerCase() === author.toLowerCase()) || t.startsWith('@') || /^\d[\d.,]*\s*[kKmM]?$/.test(t);
    let title = '';
    for (const sel of L.title || []) {
      for (const el of root.querySelectorAll(sel)) {
        if (inAuthor(el)) continue;
        const a = el.matches('a[href]') ? el : el.closest('a[href]') || el.querySelector('a[href]');
        if (a && root.contains(a) && canon(a.getAttribute('href')) && canon(a.getAttribute('href')) !== url) continue;
        const t = txt(el);
        if (!bad(t)) { title = t; break; }
      }
      if (title) break;
    }
    if (!title) for (const a of modelLinks) { if (inAuthor(a) || a.querySelector('img')) continue; const t = txt(a); if (!bad(t)) { title = t; break; } }
    if (!title) for (const a of modelLinks) { const t = clean(a.getAttribute('title') || a.getAttribute('aria-label') || '', 300); if (!bad(t)) { title = t; break; } }
    if (!title) { const h = [...root.querySelectorAll('h1,h2,h3,h4,h5,h6,[class*="title" i]')].find(h => !inAuthor(h) && !bad(txt(h))); title = h ? txt(h) : ''; }
    if (!title) { const im = modelLinks.map(a => a.querySelector('img')).find(Boolean); const t = clean(im?.alt || '', 300); title = bad(t) ? '' : t; }
    // 图：模型链接里的图优先，再按站点包的 image 规则，最后卡片里任何一张；头像 / logo / 太小的不要，挑最大的
    const imgOk = im => { const src = imgSrc(im); if (!/^https?:/i.test(src) || avatarRe.test(src) || inAuthor(im)) return false;
      const w = im.naturalWidth || im.width || 0; return !(w && w < 64); };
    const area = im => (im.width || im.naturalWidth || 1) * (im.height || im.naturalHeight || 1);
    let pool = modelLinks.flatMap(a => [...a.querySelectorAll('img')]).filter(imgOk);
    if (!pool.length) for (const sel of L.image || []) { pool = [...root.querySelectorAll(sel)].filter(imgOk); if (pool.length) break; }
    if (!pool.length) pool = [...root.querySelectorAll('img')].filter(imgOk);
    const im = pool.sort((a, b) => area(b) - area(a))[0];
    return {title: title.slice(0, 200), thumb: im ? imgSrc(im) : '', thumb_w: im ? (im.naturalWidth || im.width || 0) : 0, author: author.slice(0, 80)};
  }
  // 整页的模型卡片：[{url, id, link, root, title, thumb, thumb_w, author}]
  function listCards(site, doc, opts) {
    doc = doc || document;
    const base = doc.location ? doc.location.href : undefined;
    const canon = canonFn(site, base), idOf = idFn(site, base);
    const here = canon(base || '');
    const out = [], seen = new Set();
    for (const a of doc.querySelectorAll('a[href]')) {
      if (opts && opts.skip && opts.skip(a)) continue;
      const url = canon(a.getAttribute('href'));
      if (!url) continue;
      const id = idOf(url);
      if (seen.has(id) || (here && idOf(here) === id)) continue;
      // 卡片要有图（模型链接里或卡片里）：只有文字的链接（面包屑、评论里的链接）不算
      const root = cardRoot(a, id, canon, idOf, doc);
      if (!root.querySelector('img')) continue;
      const info = readCard(site, root, url, canon, base);
      if (!info.thumb && !a.querySelector('img')) continue;     // 只有作者头像、没有模型图的（导航栏、评论里的链接）不算卡片
      seen.add(id);
      out.push({url, id, link: a, root, ...info});
      if (opts && opts.max && out.length >= opts.max) break;
    }
    return out;
  }

  globalThis.CuratorSites = {load, siteForHost, detailRegex, detailMatch, hostIn, resolve, mapFields, extract, resolveDownload, template, clean, cleanBlock, htmlToText,
    canonFn, idFn, cardRoot, readCard, listCards};
})();
