"use strict";
// v2.53「返回」回到原来的地方（全系统）。
// 每次换页面（showTab）都在浏览器历史里记一条（history.pushState），离开一个页面时把它的样子记下来：
//   页面、滚动位置、页面里的筛选 / 搜索框（有 id 的输入框）、页签（UX.tabs）、模块自己登记的状态（文件夹、第几页…）、
//   刚点的是哪一行（回来时闪一下）。
// 「← 返回」按钮（NAV.back）、浏览器后退键、安卓返回手势都走浏览器历史：回到上一条，恢复当时的样子，刚编辑的那一行闪一下。
// 没有上一条（直接打开链接 / 新标签页）：回到合理的上级页面（各按钮自己给，例如编辑页 → 产品库）。
// 抽屉 / 弹窗（订单详情、商品 360、待办、弹窗）也记一条：返回手势先关掉它，而不是离开页面。
// 记录放在 sessionStorage（刷新页面以后还在，关掉标签页就没了）；存储用不了时照常工作，只是刷新后不记得。
//
// 模块怎么用：
//   NAV.keep("页面id" 或 [..], { get() { return {…状态} }, set(st) { …恢复（在页面显示之前调用） } })
//   NAV.mark({ hl: "要闪的编号" })        —— 打开详情之前调用（openProduct 已经自动做了）
//   NAV.back("上级页面")                  —— 「← 返回」按钮
//   NAV.overlay(元素, { open(el), hl() }) —— 抽屉 / 弹窗（默认看 class="hidden"）
//   NAV.view("前缀", { open(arg), close() }) + NAV.enter("前缀", arg) / NAV.leave("前缀") —— 页面里的详情（例如盘点单）
(function () {
  const PFX = "nav3d:";
  const ROWS = "tr, li, .cur-ic, .cur-card, .ux-row, [data-nav-row]";
  const NO_FORM = new Set(["edit", "settings"]);
  const ss = {
    get(k) { try { return JSON.parse(sessionStorage.getItem(PFX + k)); } catch { return null; } },
    set(k, v) { try { sessionStorage.setItem(PFX + k, JSON.stringify(v)); } catch { /* 存不了：只是刷新后不记得 */ } },
    del(k) { try { sessionStorage.removeItem(PFX + k); } catch { /* 忽略 */ } },
  };
  const curTab = () => (typeof CUR_TAB !== "undefined" ? CUR_TAB : null);
  const curP = () => (typeof P !== "undefined" ? P : null);

  let SID = null;          // 这一串历史的编号（每次新打开页面换一个）
  let CUR = 0;             // 现在在第几条
  let TABNAV = 0;          // 现在这个页面的那一条（上面可能还叠着抽屉 / 弹窗的条目）
  let ENTRY_PID = null;    // 编辑页这一条是哪个产品
  let SNAPS = {};          // 第几条 → 离开时的样子
  let READY = false;
  let MARK = null;         // 下一次离开页面时额外记的（要闪的编号、回来要重新打开的商品 360）
  let LAST_CLICK = null;   // 最后点的是哪一行
  let PEND = null;         // 正在恢复的页面：{ tab, snap }
  let DEPTH = 0;           // showTab 里面又调用 showTab（页面跳转 / 旧页面 id）：换掉这一条，不新记
  let backPending = false, backTimer = null;
  const queue = [];        // 等自己发出的「后退」完成后再做的历史操作
  const PAGES = {};        // 页面 id → { get, set, form }
  const OVS = [];          // 打开着的抽屉 / 页面里的详情：{ key, nav, tab, close, hl, sel, y }
  const VIEWS = {};        // 前缀 → { open(arg), close() }

  const save = () => {
    const keep = {};
    Object.keys(SNAPS).map(Number).filter((i) => i <= CUR + 1 && i > CUR - 60).forEach((i) => (keep[i] = SNAPS[i]));
    SNAPS = keep;
    ss.set("s:" + SID, SNAPS);
  };
  const st = (tab, extra) => {
    const o = { sid: SID, nav: CUR, tab };
    if (tab === "edit" && curP()) o.pid = curP().id;
    return Object.assign(o, extra || {});
  };
  function doHist(fn) {
    if (backPending) { queue.push(fn); return; }
    try { fn(); } catch (e) { console.error("nav", e); }
  }
  function flush() {
    backPending = false; clearTimeout(backTimer);
    queue.splice(0).forEach((f) => { try { f(); } catch (e) { console.error("nav", e); } });
  }
  // 自己发出的后退 / 跳转（关掉抽屉、取消离开）：对应的 popstate 不当成用户的后退
  function selfGo(delta) {
    backPending = true;
    clearTimeout(backTimer);
    backTimer = setTimeout(flush, 1500);          // 万一没收到 popstate，也不卡住
    history.go(delta);
  }

  // ---------------- 页面的样子 ----------------
  function panelOf(tab) {
    const pid = (typeof PANEL_OF !== "undefined" && PANEL_OF[tab]) || tab;
    return document.getElementById("tab-" + pid);
  }
  const skipEl = (el) => /^(file|password|hidden|button|submit|reset|image)$/.test(el.type || "") || el.disabled ||
    !!el.closest(".is-editing,[data-lock-skip],[data-nav-skip],.modal,.drawer");
  function formOf(panel) {
    if (!panel) return null;
    const out = {};
    let n = 0;
    panel.querySelectorAll("input[id],select[id],textarea[id]").forEach((el) => {
      if (n >= 80 || skipEl(el)) return;
      const v = el.type === "checkbox" || el.type === "radio" ? el.checked : el.value;
      if (typeof v === "string" && v.length > 300) return;
      out[el.id] = v; n++;
    });
    return n ? out : null;
  }
  function applyForm(panel, f) {
    if (!panel || !f) return;
    Object.entries(f).forEach(([id, v]) => {
      const el = document.getElementById(id);
      if (!el || !panel.contains(el) || skipEl(el)) return;
      if (el.type === "checkbox" || el.type === "radio") { if (el.checked !== v) el.checked = !!v; return; }
      if (el.value === v) return;
      if (el.tagName === "SELECT" && ![...el.options].some((o) => o.value === v)) return;
      el.value = v;
    });
  }
  // 页面里的页签（UX.tabs）：按组记住选的是哪个
  function uxOf(panel) {
    if (!panel) return null;
    const out = {};
    panel.querySelectorAll(".ux-tabs").forEach((g, i) => {
      const on = g.querySelector(".ux-tab.on");
      if (on && on.dataset.uxTab != null) out[g.dataset.uxGroup || "#" + i] = on.dataset.uxTab;
    });
    return Object.keys(out).length ? out : null;
  }
  function applyUx(panel, ux) {
    if (!panel || !ux) return;
    panel.querySelectorAll(".ux-tabs").forEach((g, i) => {
      const want = ux[g.dataset.uxGroup || "#" + i];
      if (want == null) return;
      if (document.querySelector(`#subnav .tab[data-tab="${cssq(want)}"]`)) return;     // 这种页签是换页面（自己就是一条历史）
      const on = g.querySelector(".ux-tab.on");
      if (on && on.dataset.uxTab === want) return;
      const b = [...g.querySelectorAll("[data-ux-tab]")].find((x) => x.dataset.uxTab === want);
      if (b) b.click();
    });
  }
  const cssq = (v) => String(v).replace(/["\\]/g, "\\$&");
  const ID_SKIP = /^data-(notr|i18n|lk|ux|tip|help|roles|mod|module|ready|needmod|parent|nav-skip|p360-act|act)/;
  function idAttr(el) {
    for (const a of el.attributes || []) {
      if (!a.name.startsWith("data-") || ID_SKIP.test(a.name)) continue;
      const v = a.value;
      if (v && v.length <= 80 && /[\w\u0E00-\u0E7F\u4e00-\u9fff]/.test(v) && v !== "1" && v !== "true") return a;
    }
    return null;
  }
  // 点的是哪一行：存一个回来时能找到它的选择器
  function selFor(t, panel) {
    const row = t.closest && t.closest(ROWS);
    if (!row || !panel.contains(row)) return null;
    const own = idAttr(row);
    if (row.id) return "#" + CSS.escape(row.id);
    if (own) return `${row.tagName.toLowerCase()}[${own.name}="${cssq(own.value)}"]`;
    for (let el = t; el && el !== row; el = el.parentElement) {
      const a = idAttr(el);
      if (a) return `[${a.name}="${cssq(a.value)}"]`;
    }
    const d = [...row.querySelectorAll("*")].find((x) => idAttr(x));
    if (d) { const a = idAttr(d); return `[${a.name}="${cssq(a.value)}"]`; }
    return null;
  }
  document.addEventListener("click", (e) => {
    const tab = curTab(), panel = tab && panelOf(tab), t = e.target;
    if (!panel || !t || !t.closest || !panel.contains(t)) return;
    const sel = selFor(t, panel);
    if (sel) LAST_CLICK = { tab, sel, t: Date.now() };
  }, true);

  function capture() {
    const tab = curTab();
    if (!tab) return null;
    const s = { tab, y: Math.round(window.scrollY || 0) };
    if (tab === "edit") s.pid = ENTRY_PID || (curP() && curP().id);
    const panel = panelOf(tab), pg = PAGES[tab];
    if (pg && pg.get) { try { s.st = pg.get(); } catch (e) { console.error("nav get", tab, e); } }
    if (!NO_FORM.has(tab) && !(pg && pg.form === false)) { const f = formOf(panel); if (f) s.f = f; }
    const ux = uxOf(panel); if (ux) s.ux = ux;
    if (LAST_CLICK && LAST_CLICK.tab === tab && Date.now() - LAST_CLICK.t < 30000) s.sel = LAST_CLICK.sel;
    if (MARK && Date.now() - MARK.t < 20000) { const { t: _t, ...m } = MARK; Object.assign(s, m); }
    MARK = null;
    return s;
  }

  // ---------------- 恢复 ----------------
  // 页面显示之前：模块登记的状态、筛选框的值（页面显示时按它们加载）
  function applyPending(tab) {
    if (!PEND || PEND.tab !== tab || !PEND.snap) return;
    const s = PEND.snap, pg = PAGES[tab];
    if (pg && pg.set && s.st !== undefined && !PEND.setDone) { try { pg.set(s.st); PEND.setDone = true; } catch (e) { console.error("nav set", tab, e); } }
    if (s.f && !(pg && pg.form === false)) applyForm(panelOf(tab), s.f);
  }
  const frame = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
  let restoreSeq = 0;
  async function visuals(tab, snap, opt = {}) {
    if (!snap) return;
    const my = ++restoreSeq;
    const alive = () => my === restoreSeq && curTab() === tab;
    let stop = false;
    const stopper = () => { stop = true; };
    ["wheel", "touchstart", "keydown", "mousedown"].forEach((k) => window.addEventListener(k, stopper, { once: true, passive: true }));
    try {
      await frame();
      if (!alive()) return;
      applyUx(panelOf(tab), snap.ux);
      // 滚动：内容是慢慢加载出来的，等页面够高了再滚
      const y = snap.y || 0;
      for (let i = 0; i < 40 && y > 0 && !stop && alive(); i++) {
        const max = document.documentElement.scrollHeight - window.innerHeight;
        window.scrollTo(0, Math.min(y, Math.max(0, max)));
        if (max >= y - 2 && Math.abs(window.scrollY - y) < 3) break;
        await new Promise((r) => setTimeout(r, 100));
      }
      if (opt.noHl || !alive()) return;
      // 刚才那一行：闪一下（不在屏幕里就滚过去）
      let el = null;
      for (let i = 0; i < 30 && alive(); i++) {
        el = findTarget(panelOf(tab), snap);
        if (el) break;
        await new Promise((r) => setTimeout(r, 120));
      }
      if (el && alive()) flash(el, !stop);
    } finally {
      ["wheel", "touchstart", "keydown", "mousedown"].forEach((k) => window.removeEventListener(k, stopper));
    }
  }
  function byValue(root, v) {
    const q = v.includes('"') ? (v.includes("'") ? null : `'${v}'`) : `"${v}"`;
    if (!q) return null;
    try {
      const r = document.evaluate(`.//*[not(self::option)][@*=${q}]`, root, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      let first = null;
      for (let i = 0; i < r.snapshotLength; i++) {
        const el = r.snapshotItem(i);
        if (el.getClientRects().length) { const row = el.closest(ROWS); if (row && root.contains(row)) return row; first = first || el; }
      }
      return first;
    } catch { return null; }
  }
  function findTarget(panel, snap) {
    if (!panel) return null;
    if (snap.hl != null && snap.hl !== "") { const el = byValue(panel, String(snap.hl)); if (el) return el; }
    if (snap.sel) {
      try {
        const els = [...panel.querySelectorAll(snap.sel)].filter((x) => x.getClientRects().length);
        for (const x of els) { const row = x.closest(ROWS); if (row && panel.contains(row)) return row; }
      } catch { /* 选择器不对：忽略 */ }
    }
    return null;
  }
  function flash(el, scroll) {
    if (scroll) {
      const r = el.getBoundingClientRect();
      if (r.bottom < 60 || r.top > window.innerHeight - 20) el.scrollIntoView({ block: "center" });
    }
    el.classList.remove("nav-hl");
    void el.offsetWidth;
    el.classList.add("nav-hl");
    setTimeout(() => el.classList.remove("nav-hl"), 2600);
  }

  // 按历史的一条恢复：换到那个页面（编辑页：重新打开那个产品），恢复样子
  async function navTo(s, snap) {
    PEND = { tab: s.tab, snap };
    applyPending(s.tab);              // 已经在页面里的输入框（内核页面 / 已经加载的模块）
    let ok;
    try {
      if (s.tab === "edit" && s.pid && (!curP() || curP().id !== s.pid) && typeof openProduct === "function") ok = await openProduct(s.pid, false, { nav: "none" });
      else ok = await goTab(s.tab, { nav: "none" });
    } finally { if (PEND && PEND.tab === s.tab) PEND = null; }
    return ok !== false;
  }

  // ---------------- 换页面（app.js showTab 调用） ----------------
  function before(name, opt) {
    DEPTH++;
    if (!READY) return "replace";
    if (opt && opt.nav) return opt.nav;
    const prev = curTab();
    const p = curP();
    const sameEdit = name === "edit" && prev === "edit" && p && ENTRY_PID && p.id !== ENTRY_PID;
    const mode = DEPTH > 1 || inShow > 0 || !prev || (prev === name && !sameEdit) ? "replace" : "push";
    if (mode === "push") { const s = capture(); if (s) { SNAPS[TABNAV] = s; save(); } }
    return mode;
  }
  function after(name, mode) {
    DEPTH = Math.max(0, DEPTH - 1);
    const p = curP();
    const pid = name === "edit" && p ? p.id : null;
    if (mode === "none") { ENTRY_PID = pid; updBack(); return; }
    if (!SID) { try { history.replaceState(null, "", "#" + name); } catch { /* 忽略 */ } return; }
    doHist(() => {
      if (mode === "push") {
        // 页面里的详情（盘点单）属于原来的页面：换页面时不再算「打开着」
        for (let i = OVS.length - 1; i >= 0; i--) if (!OVS[i].el) OVS.splice(i, 1);
        CUR += 1; TABNAV = CUR;
        Object.keys(SNAPS).forEach((k) => { if (+k >= CUR) delete SNAPS[k]; });
        history.pushState(st(name), "", "#" + name);
        save();
      } else {
        const h = history.state;
        if (h && h.sid === SID && h.ov) return;            // 现在这一条是抽屉的：不动
        history.replaceState(st(name, { nav: CUR }), "", "#" + name);
      }
      updBack();
    });
    ENTRY_PID = pid;
  }
  let inShow = 0;      // 模块的 show() 同步执行时又换页面 = 跳转（旧页面 id → 新页面），换掉这一条
  function showing(fn) { inShow++; try { return fn(); } finally { inShow--; } }

  // ---------------- 浏览器后退 / 前进 / 安卓返回手势 ----------------
  window.addEventListener("popstate", (e) => { onPop(e.state).catch((err) => console.error("nav pop", err)); });
  async function onPop(s) {
    if (!READY) return;
    if (backPending) {                       // 自己发出的后退：只同步位置
      if (s && s.sid === SID) { CUR = s.nav; if (!s.ov) TABNAV = s.nav; }
      flush();
      return;
    }
    if (!s || s.sid !== SID) return onForeign();
    const from = CUR, dir = s.nav < from ? -1 : 1;
    // 先关掉这一条以上的抽屉 / 详情
    let closed = 0;
    for (let i = OVS.length - 1; i >= 0; i--) {
      const o = OVS[i];
      if (o.nav != null && o.nav > s.nav) { OVS.splice(i, 1); closed++; closeOv(o, true); }
    }
    if (s.ov) {
      CUR = s.nav;
      if (OVS.some((o) => o.nav === s.nav)) return;              // 回到了还开着的抽屉
      const [pre, arg] = String(s.ov).split(":");
      const v = VIEWS[pre];
      if (v && v.open && arg != null && s.tab === curTab()) {  // 页面里的详情：前进时重新打开
        const rec = { key: s.ov, nav: s.nav, tab: s.tab, close: v.close, y: window.scrollY, sel: null };
        OVS.push(rec);
        try { await v.open(arg); } catch (err) { console.error(err); }
        return;
      }
      if (dir < 0) history.back(); else history.forward();     // 已经关掉的抽屉：跳过这一条
      return;
    }
    if (s.dead) { CUR = s.nav; if (dir < 0) history.back(); else history.forward(); return; }
    const same = s.tab === curTab() && (s.tab !== "edit" || !s.pid || (curP() && curP().id === s.pid));
    if (same && (closed || s.nav === TABNAV)) { CUR = s.nav; TABNAV = s.nav; return; }
    const leaving = TABNAV, snapNow = capture();
    const oldCur = CUR, oldTab = TABNAV;
    CUR = s.nav; TABNAV = s.nav;
    const snap = SNAPS[s.nav] && SNAPS[s.nav].tab === s.tab ? SNAPS[s.nav] : null;
    const ok = await navTo(s, snap);
    if (!ok) {                                 // 有没保存的修改，用户选了留下：回到原来那一条
      CUR = oldCur; TABNAV = oldTab;
      selfGo(oldCur - s.nav);
      return;
    }
    if (snapNow) SNAPS[leaving] = snapNow;
    save();
    visuals(s.tab, snap);
    if (snap && snap.p360 && window.P360) setTimeout(() => { if (curTab() === s.tab) P360.open(snap.p360); }, 50);
  }
  // 没有记录的一条（点了 <a href="#xxx">、地址栏改了 #页面）
  function onForeign() {
    const want = (location.hash || "").slice(1);
    const btn = want && document.querySelector(`#subnav .tab[data-tab="${cssq(want)}"]`);
    if (btn && !btn.classList.contains("role-hidden")) {
      const s = capture();
      if (s) SNAPS[TABNAV] = s;
      CUR += 1; TABNAV = CUR;
      history.replaceState(st(want, { nav: CUR }), "", "#" + want);
      save();
      goTab(want, { nav: "none" });
      return;
    }
    selfGo(-1);                                // <a href="#">：不要这一条
  }

  // ---------------- 抽屉 / 弹窗 ----------------
  // o.open(el) → 是否打开着（默认：没有 class hidden）；o.hl() → 关掉后要闪的编号
  function overlay(el, o = {}) {
    if (!el || el._navOv) return;
    el._navOv = true;
    const key = o.key || el.id || "ov";
    const isOpen = o.open || ((x) => !x.classList.contains("hidden"));
    let rec = null;
    const check = () => {
      const open = isOpen(el);
      if (open && !rec) {
        if (!READY || !SID) return;
        const tab = curTab();
        const panel = tab && panelOf(tab);
        rec = { key, el, tab, nav: null, hl: o.hl, close: o.close, y: window.scrollY,
          sel: LAST_CLICK && LAST_CLICK.tab === tab && Date.now() - LAST_CLICK.t < 3000 ? LAST_CLICK.sel : null, panel };
        OVS.push(rec);
        const r = rec;
        doHist(() => {
          if (!OVS.includes(r)) return;                 // 还没记就关掉了
          CUR += 1; r.nav = CUR;
          history.pushState(st(curTab(), { nav: CUR, ov: key }), "", location.hash);
        });
      } else if (!open && rec) {
        const r = rec; rec = null;
        const i = OVS.indexOf(r);
        if (i < 0) return;                              // 是后退关掉的（onPop 已经处理）
        OVS.splice(i, 1);
        closeOv(r, false);
      }
    };
    el._navRec = () => rec;
    el._navForget = () => { rec = null; };
    new MutationObserver(check).observe(el, { attributes: true, attributeFilter: ["class", "style", "hidden"] });
    check();
  }
  // byPop：浏览器后退关的（要把它关掉）；否则是页面上的按钮关的（历史里那一条退掉）
  function closeOv(o, byPop) {
    if (byPop) {
      try {
        if (o.el) { if (o.el._navForget) o.el._navForget(); if (o.close) o.close(); else defaultClose(o.el); }
        else if (o.close) { Promise.resolve(o.close()).then(() => { if (o.y) window.scrollTo(0, o.y); }).catch((e) => console.error(e)); }
      } catch (e) { console.error(e); }
    } else if (o.nav != null && o.nav === CUR) {
      try { history.replaceState(Object.assign({}, history.state, { dead: true }), "", location.hash); } catch { /* 忽略 */ }
      CUR = o.nav - 1;
      selfGo(-1);
    }
    // 关掉后：刚才那一行闪一下（还在同一个页面时）
    const tab = o.tab;
    setTimeout(() => {
      if (curTab() !== tab) return;
      let id = null;
      try { id = o.hl ? o.hl() : null; } catch { id = null; }
      const el = findTarget(panelOf(tab), { hl: id, sel: o.sel });
      if (el) flash(el, true);
    }, 60);
  }
  function defaultClose(el) {
    if (el.id === "modal" && window.MODAL) return MODAL.close();
    el.classList.add("hidden");
  }

  // ---------------- 页面里的详情（例如盘点单）----------------
  function view(pre, o) { VIEWS[pre] = o; }
  function enter(pre, arg) {
    if (!READY || !SID) return;
    const key = pre + ":" + arg;
    const top = OVS[OVS.length - 1];
    if (top && !top.el && top.key.startsWith(pre + ":")) {           // 已经在一个详情里：换成这个
      top.key = key;
      if (top.nav === CUR) doHist(() => history.replaceState(Object.assign({}, history.state, { ov: key }), "", location.hash));
      return;
    }
    const tab = curTab();
    const rec = { key, tab, nav: null, close: VIEWS[pre] && VIEWS[pre].close, y: window.scrollY,
      sel: LAST_CLICK && LAST_CLICK.tab === tab && Date.now() - LAST_CLICK.t < 3000 ? LAST_CLICK.sel : null };
    OVS.push(rec);
    doHist(() => {
      if (!OVS.includes(rec)) return;
      CUR += 1; rec.nav = CUR;
      history.pushState(st(tab, { nav: CUR, ov: key }), "", location.hash);
    });
    window.scrollTo(0, 0);
  }
  // 详情里的「← 返回列表」：有记录就后退（和返回手势一样），没有就直接关
  function leave(pre) {
    const i = OVS.map((o) => !o.el && o.key.startsWith(pre + ":")).lastIndexOf(true);
    const rec = i >= 0 ? OVS[i] : null;
    if (rec && rec.nav != null && rec.nav === CUR) { history.back(); return true; }
    if (rec) OVS.splice(i, 1);
    const v = VIEWS[pre];
    if (v && v.close) v.close();
    if (rec) setTimeout(() => { const el = findTarget(panelOf(rec.tab), { sel: rec.sel }); if (el) flash(el, true); }, 80);
    return false;
  }

  // ---------------- 「← 返回」 ----------------
  function prevSnap() {
    const ks = Object.keys(SNAPS).map(Number).filter((k) => k < TABNAV).sort((a, b) => b - a);
    return ks.length ? SNAPS[ks[0]] : null;
  }
  function canBack() { return READY && TABNAV > 0 && !!prevSnap(); }
  function back(fallback) {
    if (canBack()) { history.go(-(CUR - TABNAV + 1)); return true; }
    if (fallback && typeof goTab === "function") goTab(fallback, { nav: "replace" });
    return false;
  }
  // 返回按钮上写回到哪里：「← 返回 采集箱」
  function backLabel(fallback) {
    const s = canBack() ? prevSnap() : null;
    const tab = s ? s.tab : fallback;
    const b = tab && document.querySelector(`#subnav .tab[data-tab="${cssq(tab)}"]`);
    const name = b ? b.textContent.trim() : "";
    const th = window.I18N && I18N.lang === "th";
    return (th ? "← กลับ" : "← 返回") + (name ? " " + name : "");
  }

  // 带 data-nav-back="上级页面" 的按钮：点了就返回；按钮上写回到哪里
  function updBack() { document.querySelectorAll("[data-nav-back]").forEach((b) => { b.textContent = backLabel(b.dataset.navBack); }); }
  document.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest("[data-nav-back]");
    if (b) { e.preventDefault(); back(b.dataset.navBack); }
  });

  function keep(tabs, o) {
    (Array.isArray(tabs) ? tabs : [tabs]).forEach((t) => { PAGES[t] = o; });
    // 模块脚本是第一次打开页面时才加载的：正在恢复这个页面就马上用上
    if (PEND && PAGES[PEND.tab] === o) applyPending(PEND.tab);
  }
  function mark(o) { MARK = Object.assign({}, MARK && Date.now() - MARK.t < 20000 ? MARK : {}, o, { t: Date.now() }); }

  // ---------------- 启动（app.js 调用）：刷新页面后接上原来的历史 ----------------
  async function start(first) {
    const s = history.state;
    if (s && s.sid && typeof s.nav === "number") {
      SID = s.sid; CUR = TABNAV = s.nav;
      SNAPS = ss.get("s:" + SID) || {};
    } else {
      SID = Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
      CUR = TABNAV = 0; SNAPS = {};
      const ids = (ss.get("ids") || []).filter((x) => x !== SID);
      ids.push(SID);
      while (ids.length > 3) ss.del("s:" + ids.shift());
      ss.set("ids", ids);
    }
    READY = true;
    if (s && s.ov) {                         // 刷新时开着抽屉：抽屉没了，退回到页面那一条
      CUR = TABNAV = Math.max(0, s.nav - 1);
      selfGo(-1);
    }
    const tab = s && s.tab === first ? s.tab : first;
    const snap = SNAPS[TABNAV] && SNAPS[TABNAV].tab === tab ? SNAPS[TABNAV] : null;
    if (s && s.tab === "edit" && s.pid && first === "edit") {   // 刷新时在编辑页：重新打开那个产品
      try {
        if (typeof openProduct !== "function" && window.MODKIT) await MODKIT.load("goods").catch(() => {});
        if (typeof openProduct === "function") { await openProduct(s.pid, false, { nav: "replace" }); return; }
      } catch (e) { console.error("nav reopen", e); }
    }
    PEND = snap ? { tab, snap } : null;
    applyPending(tab);
    try { await showTab(tab, { nav: "replace" }); } finally { PEND = null; }
    visuals(tab, snap, { noHl: true });
  }
  window.addEventListener("pagehide", () => { if (!READY) return; const s = capture(); if (s) { SNAPS[TABNAV] = s; save(); } });

  window.NAV = { start, before, after, showing, applyPending, keep, mark, back, canBack, backLabel, overlay, view, enter, leave,
    capture, _state: () => ({ SID, CUR, TABNAV, SNAPS, OVS: OVS.map((o) => ({ key: o.key, nav: o.nav })) }) };
})();
