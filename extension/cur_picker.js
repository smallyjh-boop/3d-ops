// 选品 · 模型网站上的推荐分和「＋采集」（扩展 3.1，从「3D选品工具」扩展的 picker.js 搬过来）。
// 列表页：每张模型卡片左上角一个「＋采集」和推荐分（读卡片上的下载 / 点赞 / 打印数，交给 ERP 打分：规则 + AI 判断泰国市场）；
// 详情页：右上角一个大的「＋采集」；右下角面板看采集队列、筛选（最低分、隐藏不推荐 / 已采集）。
// 点「＋采集」= 进 ERP 的采集队列，后台（cur_bg.js）一个个在后台标签页读详情页。巡逻时（?cur_watch=1）只读卡片，不加按钮。
(async () => {
  if (window.__CUR_PICKER || window.top !== window) return;
  window.__CUR_PICKER = true;
  const params = new URLSearchParams(location.search);
  if (params.has('cur_collect')) return;
  const WATCH = params.has('cur_watch');
  const SITES = await globalThis.CuratorSites.load();
  const SITE = globalThis.CuratorSites.siteForHost(SITES, location.hostname);
  if (!SITE || SITE.enabled === false) return;
  let LANG = 'zh';
  try { LANG = (await chrome.storage.sync.get({lang: 'zh'})).lang || 'zh'; } catch {}
  const Z = (zh, th) => (LANG === 'th' ? th : zh);
  const RE = globalThis.CuratorSites.detailRegex(SITE), IDG = SITE.detail.id_group || 2;
  const canon = href => {
    try {
      const u = new URL(href, location.href);
      if (u.hostname !== location.hostname) return '';
      const m = decodeURIComponent(u.pathname).match(RE);
      return m ? u.origin + m[1] : '';
    } catch { return ''; }
  };
  const idOf = url => { try { const m = decodeURIComponent(new URL(url, location.href).pathname).match(RE); return m ? m[IDG] : url; } catch { return url; } };
  const states = {}, buttons = {}, info = {}, roots = {}, scores = {}, badges = {}, urlOf = {};
  let filt = {min: 0, hideDone: false, hideEx: true};
  let needLogin = false, queue = null;

  // ---- 读卡片上的热度数字
  const LABELS = [['downloads', /download|下载/i], ['makes', /make|print(ed)?\b|打印|制作/i], ['likes', /like|heart|favou?rite|赞|喜欢/i],
    ['boosts', /boost|助力/i], ['collects', /collect|bookmark|收藏/i], ['views', /view|eye|浏览/i], ['comments', /comment|评论/i], ['rating', /rating|star|评分/i]];
  let pageNums = null;
  function nextData() {
    if (pageNums) return pageNums;
    pageNums = {};
    try {
      const raw = document.getElementById('__NEXT_DATA__')?.textContent;
      if (!raw) return pageNums;
      const walk = (o, d) => {
        if (!o || typeof o !== 'object' || d > 9) return;
        if (Array.isArray(o)) { o.forEach(x => walk(x, d + 1)); return; }
        const id = o.id || o.designId;
        if (id && ('downloadCount' in o || 'likeCount' in o || 'printCount' in o)) {
          pageNums[String(id)] = {downloads: o.downloadCount, likes: o.likeCount, makes: o.printCount, collects: o.collectionCount, boosts: o.boostCnt || o.boostCount};
        }
        for (const v of Object.values(o)) if (v && typeof v === 'object') walk(v, d + 1);
      };
      walk(JSON.parse(raw), 0);
    } catch {}
    return pageNums;
  }
  function readMetrics(root, id) {
    const out = {};
    const fromPage = nextData()[id];
    if (fromPage) for (const [k, v] of Object.entries(fromPage)) if (v !== undefined && v !== null) out[k] = String(v);
    let n = 0;
    for (const el of root.querySelectorAll('span,div,p,small,b,strong,li')) {
      if (el.children.length > 2 || el.closest('.cur-tag')) continue;
      const t = (el.textContent || '').trim();
      if (!/^\d[\d,.]*\s*[kKmM万]?$/.test(t) || t.length > 9) continue;
      if ([...el.children].some(c => /^\d/.test((c.textContent || '').trim()))) continue;
      let hint = '';
      for (let p = el, i = 0; p && i < 3 && p !== root; p = p.parentElement, i++) {
        hint += ' ' + [p.getAttribute('aria-label'), p.getAttribute('title'), p.getAttribute('class'), p.getAttribute('data-testid')].filter(Boolean).join(' ');
        const svg = p.querySelector('svg,img,i');
        if (svg && svg !== el) hint += ' ' + [svg.getAttribute('aria-label'), svg.getAttribute('class'), svg.getAttribute('alt'), svg.getAttribute('data-icon')].filter(Boolean).join(' ');
      }
      const lab = LABELS.find(([, re]) => re.test(hint));
      const key = lab ? lab[0] : (/\./.test(t) && parseFloat(t) <= 5 && !/[kKmM]/.test(t) ? 'rating' : 'n' + (++n));
      if (!out[key]) out[key] = t;
      if (n > 5) break;
    }
    return out;
  }
  // 一张卡片只放一个按钮：从链接往上找「只包含这一个模型」的最大的块
  function cardRoot(a, id) {
    let el = a;
    while (el.parentElement && el.parentElement !== document.body) {
      const p = el.parentElement;
      const ids = new Set([...p.querySelectorAll('a[href]')].map(x => canon(x.getAttribute('href'))).filter(Boolean).map(idOf));
      if (ids.size > 1 || (ids.size === 1 && !ids.has(id))) break;
      el = p;
      if (el.offsetHeight > 700) break;
    }
    return el;
  }

  if (WATCH) {
    // 关注巡逻：后台标签页里往下翻几屏，读出每张卡片（链接、标题、图、热度、作者），不加按钮
    window.__curatorCards = async (scrolls) => {
      const sleep = ms => new Promise(r => setTimeout(r, ms));
      for (let i = 0; i < (scrolls || 1); i++) { window.scrollTo(0, document.body.scrollHeight); await sleep(2500); }
      window.scrollTo(0, 0);
      const out = [], seen = new Set();
      for (const a of document.querySelectorAll('a[href]')) {
        if (!a.querySelector('img')) continue;
        const url = canon(a.getAttribute('href'));
        const id = url && idOf(url);
        if (!url || seen.has(id)) continue;
        seen.add(id);
        const root = cardRoot(a, id);
        const img = root.querySelector('img');
        const who = [...root.querySelectorAll('a[href]')].find(x => /\/@[^/]+|\/user\/|\/designer\//.test(x.getAttribute('href') || '') && !x.querySelector('img'));
        const tl = [...root.querySelectorAll('a[href]')].find(x => !x.querySelector('img') && canon(x.getAttribute('href')) === url && (x.innerText || '').trim().length > 3);
        const title = (tl?.innerText || '').trim() || img?.alt || (root.innerText || '').split('\n').map(x => x.trim()).find(x => x.length > 3) || '';
        out.push({url, title: title.slice(0, 200), thumb: img?.currentSrc || img?.src || '', author: (who?.innerText || '').trim().slice(0, 80), metrics: readMetrics(root, id)});
        if (out.length >= 80) break;
      }
      const text = document.body?.innerText || '';
      return {items: out, url: location.href, snippet: out.length ? '' : text.slice(0, 1500)};
    };
    return;
  }

  const css = document.createElement('style');
  css.textContent = `.cur-pick{position:absolute;z-index:2147483000;top:6px;left:6px;font:600 12px/1 system-ui,sans-serif;padding:6px 9px;border-radius:999px;border:0;cursor:pointer;white-space:nowrap;
    background:#0f6fde;color:#fff;box-shadow:0 2px 8px #0004;opacity:.95}.cur-pick:hover{opacity:1}
    .cur-pick.done{background:#e2e8f0;color:#334155}.cur-pick.wait{background:#7c3aed}.cur-pick.err{background:#b91c1c}
    .cur-panel{position:fixed;z-index:2147483001;right:14px;bottom:14px;width:310px;background:#1d2330;color:#fff;border-radius:12px;padding:10px 12px;font:13px/1.45 system-ui,"Noto Sans Thai",sans-serif;box-shadow:0 6px 24px #0005}
    .cur-panel.min .cur-body{display:none}.cur-panel a{color:#93c5fd}.cur-head{display:flex;justify-content:space-between;align-items:center;gap:6px;cursor:pointer}
    .cur-panel button.b{padding:3px 8px;border:0;border-radius:6px;font:600 12px system-ui;cursor:pointer;background:#374151;color:#fff}
    .cur-list{max-height:240px;overflow:auto;margin:6px 0}.cur-item{display:flex;gap:6px;align-items:center;padding:4px 0;border-top:1px solid #ffffff1a}
    .cur-item .t{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.cur-item .s{font-size:11px;color:#cbd5e1;white-space:nowrap}
    .cur-msg{color:#cbd5e1;margin-top:4px}
    .cur-tag{position:absolute;z-index:2147483000;top:6px;left:6px;display:flex;gap:4px;align-items:center;flex-wrap:wrap;max-width:calc(100% - 12px)}
    .cur-tag .cur-pick{position:static}
    .cur-score{font:700 11px/1 system-ui,sans-serif;padding:5px 7px;border-radius:999px;background:#475569;color:#fff;box-shadow:0 2px 8px #0004;white-space:nowrap}
    .cur-score.hi{background:#15803d}.cur-score.mid{background:#b45309}.cur-score.ex{background:#b91c1c}
    .cur-dim{opacity:.22;filter:grayscale(.7);transition:opacity .2s}
    .cur-fab{position:fixed;z-index:2147483000;top:84px;right:24px;display:flex;gap:6px;align-items:center;padding:6px;border-radius:999px;background:#1d2330e6;box-shadow:0 4px 18px #0005}
    .cur-fab .cur-pick{position:static;font-size:14px;padding:9px 14px}.cur-fab .cur-score{font-size:12px;padding:7px 9px}
    .cur-filter{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-top:6px;font-size:12px;color:#e5e7eb}.cur-filter select{font-size:12px;padding:1px}`;
  document.documentElement.appendChild(css);

  const panel = document.createElement('div');
  panel.className = 'cur-panel min';
  panel.innerHTML = `<div class="cur-head"><b>🧩 ${Z('ERP 选品 · 采集队列', 'ERP คัดเลือก · คิวเก็บข้อมูล')}</b><span class="cnt"></span></div><div class="cur-body"><div class="cur-filter"></div><div class="cur-list"></div><div class="cur-ctl"></div><div class="cur-msg"></div></div>`;
  panel.querySelector('.cur-head').onclick = () => panel.classList.toggle('min');
  const say = t => { panel.querySelector('.cur-msg').textContent = t || ''; };
  const STATE = {waiting: Z('等待中', 'รอ'), running: Z('正在读取', 'กำลังอ่าน'), done: Z('已采集', 'เก็บแล้ว'), failed: Z('失败', 'ไม่สำเร็จ'), canceled: Z('已取消', 'ยกเลิก')};

  function label(btn, id) {
    const s = states[id]?.state;
    btn.classList.remove('done', 'wait', 'err');
    if (s === 'imported' || s === 'done') btn.classList.add('done');
    else if (s === 'waiting' || s === 'running') btn.classList.add('wait');
    else if (s === 'failed') btn.classList.add('err');
    btn.textContent = s === 'imported' || s === 'done' ? Z('✓ 已采集', '✓ เก็บแล้ว') : s === 'running' ? Z('⏳ 读取中', '⏳ กำลังอ่าน') : s === 'waiting' ? Z('⏳ 排队中', '⏳ รอคิว')
      : s === 'failed' ? Z('！失败', '！ไม่สำเร็จ') : Z('＋ 采集', '＋ เก็บ');
    btn.title = s === 'imported' ? Z('已经在 ERP 的选品库里', 'อยู่ในคลังคัดเลือกของ ERP แล้ว') : Z('点一下，把这个模型加入 ERP 的采集队列', 'คลิกเพื่อเพิ่มโมเดลนี้เข้าคิวเก็บข้อมูลของ ERP');
  }
  const relabel = () => { Object.entries(buttons).forEach(([id, list]) => list.forEach(b => label(b, id))); applyFilter(); };

  function renderQueue() {
    const q = queue;
    const head = panel.querySelector('.cnt');
    if (needLogin) { head.textContent = Z('未连接', 'ยังไม่เชื่อมต่อ'); say(Z('扩展还没连上 ERP：点浏览器右上角的扩展图标，填 ERP 地址和员工密钥。', 'ส่วนขยายยังไม่ได้เชื่อมต่อ ERP: คลิกไอคอนส่วนขยาย กรอกที่อยู่ ERP และคีย์พนักงาน')); return; }
    if (!q) return;
    head.textContent = q.paused ? Z('⏸ 已暂停', '⏸ หยุด') : (q.waiting ? Z(`等待 ${q.waiting} 个`, `รอ ${q.waiting}`) : Z('空闲', 'ว่าง'));
    const list = panel.querySelector('.cur-list');
    list.innerHTML = '';
    const rows = [...q.active, ...q.recent.slice(0, 3)];
    if (!rows.length) { const d = document.createElement('div'); d.className = 'cur-msg'; d.textContent = Z('队列是空的。点模型图片左上角的「＋ 采集」加入。', 'คิวว่าง กด「＋ เก็บ」ที่มุมซ้ายบนของรูปโมเดล'); list.append(d); }
    rows.forEach((r, n) => {
      const el = document.createElement('div'); el.className = 'cur-item';
      const t = document.createElement('a'); t.className = 't'; t.href = r.url; t.target = '_blank';
      t.textContent = r.title || r.url.replace(/^https?:\/\/[^/]+/, '');
      t.title = r.message || t.textContent;
      const s = document.createElement('span'); s.className = 's'; s.textContent = STATE[r.state] || r.state;
      el.append(t, s);
      const act = (lbl, action, tip) => { const b = document.createElement('button'); b.className = 'b'; b.textContent = lbl; b.title = tip; b.onclick = () => send({type: 'cur-action', id: r.id, action}); el.append(b); };
      if (r.state === 'waiting') { if (n > 0 && q.active[n - 1]?.state === 'waiting') act('↑', 'up', Z('往前移', 'เลื่อนขึ้น')); act('✕', 'cancel', Z('取消', 'ยกเลิก')); }
      else if (r.state === 'failed') act(Z('重试', 'ลองใหม่'), 'retry', Z('重新采集', 'เก็บใหม่'));
      list.append(el);
    });
    const ctl = panel.querySelector('.cur-ctl');
    ctl.innerHTML = '';
    const b1 = document.createElement('button'); b1.className = 'b'; b1.textContent = q.paused ? Z('▶ 继续', '▶ ทำต่อ') : Z('⏸ 暂停', '⏸ หยุด');
    b1.onclick = () => send({type: 'cur-action', id: 0, action: q.paused ? 'resume' : 'pause'});
    const a = document.createElement('a'); a.href = '#'; a.textContent = Z('在 ERP 里看「选品」', 'ดู「คัดเลือกสินค้า」ใน ERP'); a.style.marginLeft = '8px';
    a.onclick = (e) => { e.preventDefault(); chrome.runtime.sendMessage({type: 'open', path: '/#cur_cand'}); };
    ctl.append(b1, a);
  }

  async function send(msg) {
    const res = await chrome.runtime.sendMessage(msg).catch(err => ({ok: false, error: String(err?.message || err)}));
    if (!res || !res.ok) {
      if (res && res.error === 'NO_CONFIG') { needLogin = true; renderQueue(); return null; }
      say((res && res.error) || Z('扩展后台没响应', 'ส่วนขยายไม่ตอบ'));
      return null;
    }
    needLogin = false;
    const d = res.data || {};
    if (d.active) { queue = d; syncStatesFromQueue(); renderQueue(); }
    return d;
  }
  function syncStatesFromQueue() {
    for (const r of [...(queue?.active || []), ...(queue?.recent || [])]) {
      const id = idOf(r.url);
      if (buttons[id] && states[id]?.state !== 'imported') states[id] = {state: r.state === 'canceled' ? '' : r.state, item: r.id};
    }
    relabel();
  }
  async function collect(url) {
    const id = idOf(url);
    states[id] = {state: 'waiting'}; relabel();
    const res = await send({type: 'cur-collect', item: {url, title: info[id]?.title || '', thumb: info[id]?.thumb || ''}});
    if (!res) { delete states[id]; relabel(); return; }
    const sk = Object.values(res.skipped || {})[0];
    if (sk === 'imported') { states[id] = {state: 'imported'}; relabel(); say(Z('这个模型已经在 ERP 的选品库里了。', 'โมเดลนี้อยู่ในคลังคัดเลือกแล้ว')); }
    else say(res.added ? Z('已加入采集队列，后台会按顺序读取。', 'เข้าคิวแล้ว จะอ่านตามลำดับเบื้องหลัง') : Z('已经在队列里了。', 'อยู่ในคิวแล้ว'));
    panel.classList.remove('min');
  }
  let pend = new Set(), qt = 0;
  function queryStatus(urls) {
    urls.forEach(u => u && pend.add(u));
    clearTimeout(qt);
    qt = setTimeout(async () => {
      const list = [...pend]; pend = new Set();
      if (!list.length) return;
      const res = await send({type: 'cur-status', urls: list});
      if (!res) return;
      for (const u of list) { const st = res.states?.[u]; if (st) states[idOf(u)] = st; }
      relabel();
    }, 600);
  }

  function paintScore(id) {
    const b = badges[id], sc = scores[id];
    if (!b || !sc) return;
    b.className = 'cur-score ' + (sc.excluded ? 'ex' : sc.score >= 70 ? 'hi' : sc.score >= 50 ? 'mid' : '');
    b.textContent = sc.excluded ? Z('✕ 不推荐', '✕ ไม่แนะนำ') : `${Z('推荐', 'แนะนำ')} ${Math.round(sc.score)}${sc.est ? ' · ' + sc.est : ''}${sc.single === false ? Z(' · 多色', ' · หลายสี') : ''}`;
    const P = {demand: Z('泰国需求', 'ความต้องการไทย'), production: Z('生产效率', 'การผลิต'), competition: Z('竞争少', 'แข่งน้อย'), popularity: Z('原站热度', 'ความนิยม'), listing: Z('上架难度', 'ลงขายง่าย')};
    b.title = [sc.excluded ? Z('排除：', 'คัดออก: ') + (LANG === 'th' && sc.excluded_th ? sc.excluded_th : sc.excluded) : '', sc.category ? Z('类目：', 'หมวด: ') + (LANG === 'th' && sc.category_th ? sc.category_th : sc.category) : '',
      Object.entries(sc.parts || {}).map(([k, v]) => `${P[k] || k} ${v}`).join(' · '), sc.reason ? 'AI: ' + (LANG === 'th' && sc.reason_th ? sc.reason_th : sc.reason) : (sc.ai ? '' : Z('AI 判断中，稍后自动更新', 'AI กำลังประเมิน')),
      (sc.keywords || []).length ? Z('泰文搜索词：', 'คำค้นภาษาไทย: ') + sc.keywords.join(', ') : ''].filter(Boolean).join('\n');
  }
  let scoreTries = 0, scoreTimer = 0;
  async function requestScores(urls) {
    const items = urls.map(u => { const id = idOf(u); return {url: u, title: info[id]?.title || '', thumb: info[id]?.thumb || '', metrics: info[id]?.metrics || {}}; });
    for (let i = 0; i < items.length; i += 60) {
      const res = await send({type: 'cur-score', items: items.slice(i, i + 60)});
      if (!res || !res.scores) continue;
      for (const [u, sc] of Object.entries(res.scores)) { scores[idOf(u)] = sc; paintScore(idOf(u)); }
    }
    applyFilter();
    const waiting = Object.keys(badges).filter(id => scores[id] && !scores[id].ai && !scores[id].excluded);
    clearTimeout(scoreTimer);
    if (waiting.length && scoreTries++ < 12) scoreTimer = setTimeout(() => requestScores(waiting.map(id => urlOf[id]).filter(Boolean)), 20000);
  }
  function applyFilter() {
    for (const id of Object.keys(roots)) {
      const sc = scores[id], st = states[id]?.state;
      let ok = true;
      if (sc && sc.score < filt.min) ok = false;
      if (filt.hideEx && sc?.excluded) ok = false;
      if (filt.hideDone && (st === 'imported' || st === 'done')) ok = false;
      roots[id].classList.toggle('cur-dim', !ok);
    }
  }
  function renderFilter() {
    const box = panel.querySelector('.cur-filter');
    box.innerHTML = `${Z('最低分', 'คะแนนขั้นต่ำ')} <select class="fmin">${[0, 50, 60, 70, 80].map(v => `<option ${v === filt.min ? 'selected' : ''}>${v}</option>`).join('')}</select>
      <label><input type="checkbox" class="fex" ${filt.hideEx ? 'checked' : ''}>${Z('隐藏不推荐', 'ซ่อนที่ไม่แนะนำ')}</label><label><input type="checkbox" class="fdone" ${filt.hideDone ? 'checked' : ''}>${Z('隐藏已采集', 'ซ่อนที่เก็บแล้ว')}</label>`;
    const save = () => { filt = {min: +box.querySelector('.fmin').value, hideEx: box.querySelector('.fex').checked, hideDone: box.querySelector('.fdone').checked};
      chrome.storage.local.set({curFilter: filt}); applyFilter(); };
    box.querySelectorAll('select,input').forEach(x => x.addEventListener('change', save));
  }
  function addButton(a, url) {
    const id = idOf(url);
    const root = cardRoot(a, id);
    if (root.dataset.curPick) return null;
    root.dataset.curPick = id;
    const img = root.querySelector('img');
    info[id] = {title: (root.innerText || '').split('\n').map(x => x.trim()).find(x => x.length > 3) || img?.alt || '', thumb: img?.currentSrc || img?.src || ''};
    const box = img?.parentElement || root;
    if (getComputedStyle(box).position === 'static') box.style.position = 'relative';
    roots[id] = root; urlOf[id] = url;
    const wrap = document.createElement('div'); wrap.className = 'cur-tag';
    const badge = document.createElement('span'); badge.className = 'cur-score'; badge.textContent = '…';
    badges[id] = badge;
    const btn = document.createElement('button');
    btn.type = 'button'; btn.className = 'cur-pick';
    btn.addEventListener('click', ev => {
      ev.preventDefault(); ev.stopPropagation(); ev.stopImmediatePropagation();
      const s = states[id]?.state;
      if (s === 'imported' || s === 'done' || s === 'waiting' || s === 'running') { panel.classList.remove('min'); return; }
      collect(url);
    }, true);
    ['mousedown', 'mouseup', 'pointerdown', 'pointerup', 'touchstart', 'click'].forEach(t => wrap.addEventListener(t, ev => { if (ev.target !== btn) { ev.stopPropagation(); if (t === 'click') ev.preventDefault(); } }, true));
    ['mousedown', 'mouseup', 'pointerdown', 'pointerup', 'touchstart'].forEach(t => btn.addEventListener(t, ev => ev.stopPropagation(), true));
    wrap.append(btn, badge);
    box.appendChild(wrap);
    info[id].metrics = readMetrics(root, id);
    (buttons[id] = buttons[id] || []).push(btn);
    label(btn, id);
    return url;
  }
  function scan() {
    const found = [];
    for (const a of document.querySelectorAll('a[href]')) {
      if (a.closest('[data-cur-pick]') || !a.querySelector('img')) continue;
      const url = canon(a.getAttribute('href'));
      if (url && idOf(url) !== idOf(canon(location.href) || '-')) { const r = addButton(a, url); if (r) found.push(r); }
    }
    const here = canon(location.href);
    if (!here) document.querySelector('.cur-fab')?.remove();
    if (here && document.querySelector('.cur-fab')?.dataset.url !== here) {
      const id = idOf(here);
      info[id] = {title: document.querySelector('h1')?.innerText?.trim() || document.title, thumb: document.querySelector('meta[property="og:image"]')?.content || '',
                  metrics: readMetrics(document.querySelector('main') || document.body, id)};
      document.querySelector('.cur-fab')?.remove();
      const fab = document.createElement('div'); fab.className = 'cur-fab'; fab.dataset.url = here;
      const fb = document.createElement('button'); fb.type = 'button'; fb.className = 'cur-pick';
      fb.onclick = () => { const s = states[id]?.state; if (!s || s === 'failed') collect(here); else panel.classList.remove('min'); };
      const badge = document.createElement('span'); badge.className = 'cur-score'; badge.textContent = '…';
      badges[id] = badge; urlOf[id] = here;
      fab.append(fb, badge);
      document.body.appendChild(fab);
      (buttons[id] = buttons[id] || []).push(fb);
      label(fb, id);
      found.push(here);
      requestScores([here]);
    }
    if (found.length) {
      if (!panel.isConnected) document.body.appendChild(panel);
      queryStatus(found);
      requestScores(found.filter(u => roots[idOf(u)]));
    }
  }

  const st = await chrome.storage.local.get(['curPicker', 'curFilter']).catch(() => ({}));
  if (st.curPicker === false) return;
  if (st.curFilter) filt = {...filt, ...st.curFilter};
  renderFilter();
  let t = 0;
  const kick = () => { clearTimeout(t); t = setTimeout(scan, 800); };
  new MutationObserver(muts => { if (muts.some(m => [...m.addedNodes].some(n => n.nodeType === 1 && !n.closest?.('.cur-tag,.cur-panel,.cur-fab')))) kick(); })
    .observe(document.documentElement, {childList: true, subtree: true});
  setTimeout(scan, 1200);
  send({type: 'cur-queue'});
  setInterval(() => { if (!document.hidden && panel.isConnected) send({type: 'cur-queue'}); }, 8000);
})();
