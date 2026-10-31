// 选品 · 模型详情页读取（扩展 3.1，从「3D选品工具」扩展 2.0 的 extract.js 搬过来）：
// 通用部分（标题、描述、作者、标签、许可、图片、文件链接、分类）对所有网站一样；各网站特有的读法来自站点包（cur_sites.js 解释）。
// 后台采集时（cur_bg.js）在后台标签页里调用 window.__modelCatalogExtract()，结果交给 ERP（POST /api/v1/curate/ext/result）。
(() => {
  if (window.__modelCatalogExtract) return;
  const S = () => globalThis.CuratorSites;

  const clean = (s, max = 9000) => (s || '').replace(/\s+/g, ' ').trim().slice(0, max);
  const cleanBlock = (s, max = 9000) => (s || '').replace(/\r/g, '').replace(/[ \t ]+/g, ' ').replace(/ *\n */g, '\n').replace(/\n{3,}/g, '\n\n').trim().slice(0, max);
  const meta = key => document.querySelector(`meta[property="${key}"],meta[name="${key}"]`)?.content?.trim() || '';
  const BAD_IMAGE = /(avatar|logo|icon|badge|profile|promo|banner|advert|emoji|flag|placeholder|sprite|qrcode)/i;
  const absolute = v => { try { return new URL(v, location.href).href; } catch { return ''; } };
  let SITES = [], SITE = null;

  // 图片去重 / 换原图：按所有站点包里的 image_rules
  function imageRule(host) {
    for (const s of SITES) for (const r of s.image_rules || []) { try { if (new RegExp(r.host, 'i').test(host)) return r; } catch {} }
    return null;
  }
  const imageHosts = () => new Set(SITES.flatMap(s => s.image_hosts || []).map(h => h.toLowerCase()));
  function uniqueImages(urls) {
    const seen = new Set(); const out = [];
    for (const raw of urls) {
      const src = absolute(raw);
      if (!/^https:\/\//i.test(src) || BAD_IMAGE.test(src)) continue;
      let key = src, output = src;
      try {
        const u = new URL(src);
        const r = imageRule(u.hostname);
        if (r?.unwrap_param) {
          const original = u.searchParams.get(r.unwrap_param);
          if (original) { try { const p = new URL(original); if (p.protocol === 'https:' && (r.unwrap_hosts || []).includes(p.hostname)) { key = p.origin + p.pathname; output = p.href; } } catch {} }
        }
        if (r?.key_replace) key = u.origin + u.pathname.replace(new RegExp(r.key_replace[0], 'i'), r.key_replace[1]);
        if (r?.strip_query) { key = u.origin + u.pathname; output = key; }
      } catch { continue; }
      if (!seen.has(key)) { seen.add(key); out.push(output); }
    }
    return out;
  }

  // ---- 区域排除：相关推荐、评论、Remix、Makes、页头页脚等
  const EXCLUDE_AREA = 'header,footer,nav,aside,[class*="comment" i],[id*="comment" i],[data-testid*="comment" i],[class*="related" i],[class*="recommend" i],[class*="remix" i],[class*="suggest" i],[class*="similar" i],[class*="more-from" i],[class*="moreFrom" i],[class*="user-make" i],[class*="makes-list" i],[class*="advert" i]';
  function inExcludedArea(node) { return Boolean(node.closest?.(EXCLUDE_AREA)); }
  const modelIdOf = href => (SITE && S().detailMatch(SITE, href)?.id) || '';
  function linksToOtherModel(node, id) {
    const a = node.closest?.('a[href]'); if (!a) return false;
    const other = modelIdOf(a.href); return Boolean(other) && other !== id;
  }
  function imageCandidates(img) {
    const out = [img.currentSrc, img.src];
    for (const name of ['data-src', 'data-original', 'data-lazy-src', 'data-image', 'data-url', 'data-full-image', 'data-zoom-src']) out.push(img.getAttribute?.(name));
    for (const value of [img.getAttribute?.('srcset'), img.getAttribute?.('data-srcset')]) if (value) for (const part of value.split(',')) out.push(part.trim().split(/\s+/)[0]);
    const picture = img.closest?.('picture');
    if (picture) for (const s of picture.querySelectorAll('source[srcset]')) for (const part of s.getAttribute('srcset').split(',')) out.push(part.trim().split(/\s+/)[0]);
    return out.filter(Boolean);
  }
  function domGalleryImages(id) {
    const gallerySel = 'img[alt*="Carousel image representing"],img[alt*="Thumbnail representing"],[aria-label*="Carousel image representing"],[aria-label*="Thumbnail representing"],[class*="gallery" i] img,[class*="carousel" i] img,[class*="swiper" i] img,[class*="slider" i] img,[data-testid*="gallery" i] img,[class*="media-viewer" i] img,[class*="image-viewer" i] img';
    let nodes = [...document.querySelectorAll(gallerySel)].filter(n => !inExcludedArea(n) && !linksToOtherModel(n, id));
    if (!nodes.length) {
      const root = document.querySelector('main') || document.body;
      nodes = [...root.querySelectorAll('img')].filter(img => !inExcludedArea(img) && !linksToOtherModel(img, id) && !(img.complete && img.naturalWidth && img.naturalWidth < 300));
    }
    const hosts = imageHosts();
    const cands = [];
    for (const n of nodes) {
      if (n.matches('img')) cands.push(...imageCandidates(n));
      const bg = getComputedStyle(n).backgroundImage || '';
      for (const m of bg.matchAll(/url\(["']?(.*?)["']?\)/gi)) cands.push(m[1]);
      const link = n.closest('a[href]');
      if (link) { try { const lu = new URL(link.href); if (/\.(jpe?g|png|webp)(\?|$)/i.test(lu.pathname) || (hosts.has(lu.hostname) && imageRule(lu.hostname))) cands.push(link.href); } catch {} }
    }
    return uniqueImages(cands);
  }

  function pageFiles(id) {
    const out = [];
    const extra = SITE?.extract?.page_files ? new RegExp(SITE.extract.page_files, 'i') : null;
    for (const a of document.querySelectorAll('a[href]')) {
      if (inExcludedArea(a)) continue;
      const href = a.href;
      const name = clean(a.getAttribute('download') || a.innerText || '', 120);
      if ((extra && extra.test(href)) || /\.(3mf|stl|step|stp|obj|zip)(\?|$)/i.test(href)) out.push({name: name || href.split('/').pop(), url: href, size: '', kind: ''});
    }
    if (id) for (const f of SITE?.extract?.extra_files || []) {
      const ctx = {id, origin: location.origin};
      out.push({name: S().template(f.name, {}, ctx), url: S().template(f.url, {}, ctx), size: '', kind: f.kind || ''});
    }
    const seen = new Set();
    return out.filter(f => !seen.has(f.url) && seen.add(f.url)).slice(0, 60);
  }

  // 原站分类：面包屑或分类链接（用于自动匹配 ERP 类目）
  function pageCategory() {
    const names = [];
    const junk = new RegExp('^(home|首页|models?|3d models?|explore|' + SITES.map(s => s.name.toLowerCase().replace(/[^a-z0-9 ]/g, '')).filter(Boolean).join('|') + ')$', 'i');
    const push = t => { t = clean(t, 60); if (t && !junk.test(t) && !names.includes(t)) names.push(t); };
    for (const a of document.querySelectorAll('nav[aria-label*="readcrumb" i] a, [class*="breadcrumb" i] a, ol[itemtype*="BreadcrumbList"] a')) push(a.innerText);
    if (!names.length) {
      const sel = SITE?.extract?.category_links || 'a[href*="category" i]';
      for (const a of document.querySelectorAll(sel)) { if (!inExcludedArea(a)) push(a.innerText); if (names.length >= 3) break; }
    }
    return names.slice(0, 4).join(' > ');
  }

  function readTitle() {
    const heading = clean(document.querySelector('h1')?.innerText, 500);
    const pageTitle = clean(meta('og:title') || document.title, 500);
    return /^(model details|模型详情|description|summary)$/i.test(heading) ? (pageTitle || heading) : (heading || pageTitle);
  }

  window.__modelCatalogExtract = async function (opts) {
    const rec = null;
    SITES = await S().load();
    SITE = S().siteForHost(SITES, location.hostname) || null;
    const current = new URL(location.href.split('#')[0]);
    for (const k of ['codex_model_catalog', 'codex_queue_id', 'codex_server', 'codex_collect']) current.searchParams.delete(k);
    const platform = SITE ? SITE.name : '其他';
    const id = modelIdOf(location.href);
    const mainText = document.querySelector('main')?.innerText || document.body?.innerText || '';
    const lines = mainText.split(/\n+/).map(x => x.trim()).filter(Boolean);
    const starts = ['description', 'summary', '模型介绍', '模型描述', '简介', '描述'];
    const stops = ['tags', 'license', 'files', 'makes & comments', 'remixes', 'collections', '模型标签', '许可', '文件', '相关模型', 'comments', 'print profiles', '打印配置'];
    const start = lines.findIndex(x => starts.includes(x.toLowerCase()));
    let detail = '';
    if (start >= 0) { let end = lines.findIndex((x, i) => i > start && stops.includes(x.toLowerCase())); if (end < 0) end = Math.min(lines.length, start + 60); detail = lines.slice(start + 1, end).join('\n'); }
    let title = readTitle();
    let description = cleanBlock(detail || document.querySelector('#thing-summary,[class*="thing-summary"],[class*="model-description"]')?.innerText || meta('og:description') || meta('description') || '');
    const authorLinks = [...document.querySelectorAll('a[href]')].filter(a => /\/(?:@[^/]+|[^/]+\/designs|users\/|profile\/)/i.test(a.getAttribute('href') || '') && !inExcludedArea(a));
    let author = clean(authorLinks.map(a => a.innerText).find(x => x && x.trim() && x.trim() !== title) || '', 300);
    let tags = [...new Set([...document.querySelectorAll('a[href]')].filter(a => !inExcludedArea(a) && (/\/(?:tag|tags)(?:[:/])/i.test(a.href) || /tag[:=]/i.test(a.href))).map(a => clean(a.innerText, 100)).filter(Boolean))];
    const licenseLink = [...document.querySelectorAll('a[href]')].find(a => /creativecommons\.org\/licenses|creativecommons\.org\/publicdomain|opensource\.org\/licenses/i.test(a.href));
    const licenseMatch = (document.body?.innerText || '').match(/\b(CC0|CC BY(?:-NC|-ND|-SA)*(?:\s*\d(?:\.\d)*)?|Creative Commons\s*-\s*[A-Za-z -]+|All Rights Reserved|Standard Digital File License|GNU - GPL|GNU - LGPL|BSD License)\b/i);
    let licenseName = clean(licenseMatch?.[0] || licenseLink?.innerText || '', 200);

    // 站点规则读取 + 过渡期旧代码对比
    let rule = {}, used = [], engine = 'page', diffs = [];
    if (SITE) {
      try { ({data: rule, used} = await S().extract(SITE, id, {id, origin: location.origin, rec})); } catch (e) { used = ['error:' + (e?.message || e)]; }
      engine = 'rules';
    }
    let images = rule.images || [], profiles = rule.profiles || [], files = rule.files || [], method = SITE ? `${SITE.id}-rules-v${SITE.version}` : 'page';
    if (engine === 'legacy') method = `${SITE.id}-legacy`;
    if (rule.title) title = rule.title;
    if (rule.description) description = rule.description;
    if (rule.author) author = rule.author;
    if ((rule.tags || []).length) tags = rule.tags;
    if (rule.license) licenseName = rule.license;
    let sourceCategory = rule.category || '';
    if (!images.length) { images = domGalleryImages(id); method += '+gallery'; }
    if (!images.length && meta('og:image')) { images = [meta('og:image')]; method += '+og'; }
    images = uniqueImages(images).slice(0, 50);
    if (!files.length) files = pageFiles(id);
    if (!sourceCategory) sourceCategory = pageCategory();

    const downloadAnchor = [...document.querySelectorAll('a[href]')].find(a => {
      if (!/download|files/i.test((a.innerText || '') + ' ' + a.href) || inExcludedArea(a)) return false;
      try { const t = new URL(a.href); return !/\.(?:jpe?g|png|gif|webp|svg)(?:$|\?)/i.test(t.href) && !imageRule(t.hostname); } catch { return false; }
    });
    const downloadButton = [...document.querySelectorAll('button,[role="button"]')].find(b => /download|下载/i.test(b.innerText || b.getAttribute('aria-label') || ''));
    return {
      platform, source_url: current.href, source_model_id: id, title, author,
      description_original: description, tags: tags.join(', '),
      image_url: images[0] || '', image_urls: images, print_profiles: profiles, model_files: files, capture_method: method, source_category: sourceCategory,
      download_url: downloadAnchor?.href || '', license_name: licenseName, license_url: licenseLink?.href || '',
      notes: downloadButton && !downloadAnchor ? `页面提供“${clean(downloadButton.innerText || downloadButton.getAttribute('aria-label'), 100)}”按钮；请在原站完成下载操作。` : '',
      site_report: SITE ? {site: SITE.id, version: SITE.version, engine, diffs, used} : null,
    };
  };

})();
