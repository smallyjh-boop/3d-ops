"use strict";
// v2.28 桌面客户端 + 拖文件上传（网页版也能用拖文件）
// 桌面端（pywebview）里多出来：登录后自动配对加速、加速状态、系统通知、在本机用切片软件打开、新窗口打开打印页。
(function () {
  let DESK = null;          // window.pywebview.api（只有桌面端有）
  let INFO = null;
  const modal = (html) => { $("#modal-in").innerHTML = html; $("#modal").classList.remove("hidden"); return $("#modal-in"); };
  const closeModal = () => { const m = $("#modal-in"); m.onclick = null; m.onchange = null; m.innerHTML = ""; $("#modal").classList.add("hidden"); };

  // ---------------- 拖文件进窗口：自动找到这个页面上对应的「上传」按钮 ----------------
  const visible = (el) => !!(el && el.closest && !el.closest(".hidden") && el.closest(".panel:not(.hidden), #modal:not(.hidden)"));
  function acceptOk(input, f) {
    const acc = (input.getAttribute("accept") || "").toLowerCase().split(",").map((x) => x.trim()).filter(Boolean);
    if (!acc.length) return true;
    const n = f.name.toLowerCase(), t = (f.type || "").toLowerCase();
    return acc.some((a) => (a.startsWith(".") ? n.endsWith(a) : a.endsWith("/*") ? t.startsWith(a.slice(0, -1)) : t === a));
  }
  function labelOf(input) {
    const l = input.closest("label");
    return ((l && l.textContent) || input.id || "").replace(/\s+/g, " ").trim().slice(0, 30);
  }
  function feed(input, files) {
    const dt = new DataTransfer();
    (input.multiple ? files : files.slice(0, 1)).forEach((f) => dt.items.add(f));
    input.files = dt.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }
  let dragN = 0;
  const overlay = () => $("#drop-overlay") || document.body.appendChild(Object.assign(document.createElement("div"), { id: "drop-overlay", className: "hidden",
    innerHTML: '<div>松开鼠标上传到当前页面</div>' }));
  window.addEventListener("dragenter", (e) => {
    if (!e.dataTransfer || ![...e.dataTransfer.types].includes("Files")) return;
    dragN++; overlay().classList.remove("hidden");
  });
  window.addEventListener("dragleave", () => { dragN = Math.max(0, dragN - 1); if (!dragN) overlay().classList.add("hidden"); });
  window.addEventListener("dragover", (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) e.preventDefault(); });
  window.addEventListener("drop", (e) => {
    if (!e.dataTransfer || !e.dataTransfer.files.length) return;
    dragN = 0; overlay().classList.add("hidden");
    // 落在某个本来就能接文件的地方（有自己的拖放处理）就不管
    if (e.defaultPrevented) return;
    e.preventDefault();
    const files = [...e.dataTransfer.files];
    const inputs = $$('input[type="file"]').filter((i) => visible(i) && !i.disabled);
    // 每个文件找能接它的上传按钮；同一个文件有几个按钮能接（例如 .3mf 可以是模型也可以是切片文件）就让用户选
    const groups = new Map(), ask = [];
    // 几个按钮都能接时的默认：图片 → 产品图片；.gcode / .gcode.3mf → 切片文件；其它 .3mf / .stl → 模型
    const PREF = ["img-input", "model-input", "fm-bulk-models"];
    files.forEach((f) => {
      let ok = inputs.filter((i) => acceptOk(i, f));
      if (ok.length > 1) {
        const sliced = /\.gcode(\.3mf)?$|\.gco$/i.test(f.name);
        const want = sliced ? ok.filter((i) => /\.gcode/.test(i.getAttribute("accept") || "")) : ok.filter((i) => PREF.includes(i.id));
        if (want.length) ok = [want.sort((a, b) => PREF.indexOf(a.id) - PREF.indexOf(b.id))[0]];
      }
      if (ok.length === 1) { if (!groups.has(ok[0])) groups.set(ok[0], []); groups.get(ok[0]).push(f); }
      else if (ok.length > 1) ask.push([f, ok]);
    });
    groups.forEach((fs, input) => feed(input, fs));
    if (ask.length) {
      const opts = ask[0][1];
      const m = modal(`<h3>上传到哪里？</h3><p class="small muted" data-notr>${ask.map(([f]) => esc(f.name)).join("、")}</p>
        <div class="row gap wrap">${opts.map((i, k) => `<button data-dk="${k}">${esc(labelOf(i))}</button>`).join("")}<button data-mclose>取消</button></div>`);
      m.onclick = (ev) => {
        const k = ev.target.dataset && ev.target.dataset.dk; if (k == null) return;
        closeModal(); feed(opts[+k], ask.map(([f]) => f));
      };
    }
    if (!groups.size && !ask.length) toast("这个页面不能上传这种文件（先打开要上传的产品 / 页面）", true);
  });

  // 顶部「💻 下载桌面版」：常用电脑装桌面客户端；偶尔用的电脑用浏览器 + 只装加速器
  document.addEventListener("click", (e) => {
    if (!e.target.closest || !e.target.closest("#desk-dl")) return;
    e.preventDefault();
    modal(`<h3>💻 在这台电脑上怎么用？</h3>
      <div class="card"><div class="row between wrap gap"><b>常用的电脑：装桌面客户端（推荐）</b><a class="btn primary" href="/api/desktop/package">⬇ 下载桌面客户端</a></div>
        <p class="small">一个窗口就是整个系统，自带电脑加速（只做你自己的活），拖文件上传，模型 / 切片文件用本机软件打开，新消息弹 Windows 通知，开机自动启动。<br>
        解压后双击 <b>Install.bat</b>，装好用自己的账号登录就行。</p></div>
      <div class="card"><div class="row between wrap gap"><b>偶尔用的电脑：浏览器 + 只装加速器</b><a class="btn" href="/api/accel/package?personal=1">⬇ 下载我的加速器</a></div>
        <p class="small">系统照常用浏览器打开；加速器在后台帮你做切片、读大模型、抠图（只做你自己的活）。<br>
        解压后双击 <b>Install.bat</b>（里面已经带好 NAS 地址和你的密钥，不用填）。装好后在右下角托盘后台运行、开机自动启动，右键图标可以暂停 / 退出。</p></div>
      <div class="row gap"><button data-mclose>关闭</button></div>`);
  });

  // ---------------- 下面都是桌面端才有的 ----------------
  function sameOrigin(u) { try { return new URL(u, location.href).origin === location.origin; } catch { return false; } }
  async function init() {
    if (DESK || !(window.pywebview && window.pywebview.api)) return;
    DESK = window.pywebview.api;
    document.body.classList.add("is-desktop");
    window.IS_DESKTOP = true;
    try { INFO = await DESK.info(); } catch { INFO = null; }
    // 系统通知：网页的 Notification 换成 Windows 托盘通知（窗口收起来也能看到）
    const N = function (title, opt) { try { DESK.notify(String(title || ""), String((opt && opt.body) || "")); } catch { /* 忽略 */ } this.close = () => {}; };
    N.permission = "granted"; N.requestPermission = async () => "granted";
    window.Notification = N;
    // 新窗口：系统自己的页面（打印单、面单）开桌面窗口；外面的网站用电脑默认浏览器
    const _open = window.open;
    window.open = (u, name, feat) => {
      if (!u) return _open.call(window, u, name, feat);
      if (sameOrigin(u)) { DESK.open_window(new URL(u, location.href).pathname + new URL(u, location.href).search, document.title); return null; }
      DESK.open_external(String(u)); return null;
    };
    document.addEventListener("click", async (e) => {
      const a = e.target.closest && e.target.closest("a[href]");
      if (!a) return;
      const href = a.getAttribute("href");
      const path = (() => { try { return new URL(href, location.href).pathname; } catch { return ""; } })();
      // 模型 / 切片文件：在本机用 Bambu Studio / Orca 打开（按住 Shift 点 = 照常下载）
      if (sameOrigin(href) && !e.shiftKey && (/^\/api\/print-files\/\d+\/download$/.test(path) || /^\/api\/products\/[^/]+\/model\/download$/.test(path))) {
        e.preventDefault();
        try {
          const t = await api("/api/desktop/dltoken", { json: { path } });
          toast("正在下载并用本机程序打开…");
          const r = await DESK.open_local(t.url);
          if (!r.ok) toast(r.error || "打开失败", true);
          else toast(r.error || "已用本机程序打开（文件在「文档\\3D-Ops」）", !!r.error, 5000);
        } catch (err) { toast(err.message, true); }
        return;
      }
      if (a.target === "_blank") {
        e.preventDefault();
        if (sameOrigin(href)) DESK.open_window(path + new URL(href, location.href).search, a.textContent.trim() || document.title);
        else DESK.open_external(new URL(href, location.href).href);
      }
    }, true);
    pairIfNeeded();
    renderChip();
    setInterval(renderChip, 10000);
  }
  window.addEventListener("pywebviewready", init);
  if (window.pywebview && window.pywebview.api) setTimeout(init, 0);

  // 登录后自动配对：这台电脑 + 这个账号 → 电脑加速密钥（只做自己的活）
  async function pairIfNeeded() {
    const getMe = () => (typeof ME !== "undefined" && ME) || null;
    for (let i = 0; i < 60 && !getMe(); i++) await new Promise((r) => setTimeout(r, 500));
    const me0 = getMe();
    if (!me0 || !INFO) return;
    const me = me0.username || "local";
    if (INFO.paired_user === me && INFO.accel && INFO.accel.state !== "未配对") return;
    try {
      const r = await api("/api/desktop/pair", { json: { device_id: INFO.device_id, device_name: INFO.device_name } });
      await DESK.paired(location.origin, r.key, r.worker_name, me);
      INFO = await DESK.info();
      renderChip();
    } catch (err) { console.warn("desktop pair", err); }
  }

  // 顶部：电脑加速状态（点开：暂停 / 帮别人加速 / 开机启动 / 日志）
  const ST_ICON = { 在线: "🟢", 连接中: "🟡", 暂停: "⏸", 未配对: "⚪" };
  async function renderChip() {
    if (!DESK) return;
    try { INFO = await DESK.info(); } catch { return; }
    const a = INFO.accel || {};
    let chip = $("#desk-chip");
    if (!chip) {
      chip = document.createElement("button");
      chip.id = "desk-chip"; chip.className = "chip small desk-chip";
      const v = $("#ver"); if (v) v.after(chip);
      chip.addEventListener("click", openPanel);
    }
    chip.textContent = `${ST_ICON[a.state] || "🔴"} 本机加速${a.current ? "：" + a.current : a.state === "在线" ? "" : "：" + a.state}`;
    const th = window.I18N && I18N.lang === "th";
    chip.title = th ? `ทำแล้ว ${a.done || 0} ชิ้น${a.failed ? ` ล้มเหลว ${a.failed}` : ""}` : `已做 ${a.done || 0} 件${a.failed ? `，失败 ${a.failed}` : ""}`;
  }
  async function openPanel() {
    INFO = await DESK.info();
    const a = INFO.accel || {};
    const m = modal(`<h3>本机：电脑加速 · 桌面客户端 v${esc(INFO.version)}</h3>
      <p class="small">状态：<b>${esc(a.state)}</b>${a.current ? ` · 正在${esc(a.current)}` : ""} · 已做 <b>${a.done || 0}</b> 件${a.failed ? ` · 失败 ${a.failed}` : ""}
        ${a.installing ? `<br><span class="warn">${esc(a.installing)}</span>` : ""}<br>
        <span class="muted">这台电脑：<span data-notr>${esc(a.name || INFO.device_name)}</span> · 连接：<span data-notr>${esc(INFO.server || "")}</span></span></p>
      <p class="small muted">切片、读大模型、3D 预览、抠图、去水印会先交给你自己这台电脑做（比 NAS 快）；电脑关了 / 暂停时 NAS 自己做。</p>
      <div class="small desk-opts">
        <label class="row gap"><input type="checkbox" data-dopt="paused" ${a.paused ? "checked" : ""}> 暂停电脑加速（这台电脑很忙时）</label>
        <label class="row gap"><input type="checkbox" data-dopt="share" ${a.share ? "checked" : ""}> 也帮别人加速（同事的活也可以在这台电脑做）</label>
        <label class="row gap"><input type="checkbox" data-dopt="autostart" ${INFO.autostart ? "checked" : ""}> 开机自动启动（只在右下角托盘，不弹窗口）</label>
      </div>
      <details class="small"><summary>运行记录</summary><pre class="sys-pre" data-notr>${esc((a.log || []).join("\n") || "（还没有）")}</pre></details>
      <div class="row gap" style="margin-top:8px"><button data-dfolder>打开「在本机打开」的文件夹</button><button data-dswitch>重新连接 NAS</button><button data-mclose>关闭</button></div>`);
    m.onchange = async (e) => {
      const k = e.target.dataset && e.target.dataset.dopt; if (!k) return;
      INFO = await DESK.set_option(k, e.target.checked); renderChip();
    };
    m.onclick = (e) => {
      if (e.target.dataset.dfolder !== undefined) DESK.show_folder();
      if (e.target.dataset.dswitch !== undefined) { DESK.switch_server(); toast("正在重新找 NAS…"); }
    };
  }
  // 设置 → 组件与插件：桌面客户端（下载、每台电脑的状态，老板可以停用）
  async function loadDevices() {
    const box = $("#cfg-desk-body"); if (!box) return;
    let d = { devices: [] }, ws = [];
    try { d = await api("/api/desktop/devices"); } catch { /* 员工看不到列表 */ }
    try { ws = (await api("/api/accel/status")).workers || []; } catch { ws = []; }
    const on = (x) => ws.find((w) => w.online && w.name && w.name.endsWith("@" + x.pc) && (w.user || "") === x.user);
    box.innerHTML = d.devices.length ? `<table class="grid small"><thead><tr><th>电脑</th><th>账号</th><th>加速</th><th>版本</th><th>最近连接</th><th></th></tr></thead><tbody>${d.devices.map((x) => {
      const w = on(x);
      return `<tr><td data-notr>${esc(x.pc)}</td><td data-notr>${esc(x.display || x.user)}</td><td>${w ? (w.paused ? "⏸ 暂停" : "🟢 在线") + (w.share ? " · 帮别人" : "") : '<span class="muted">不在线</span>'}</td>
        <td>${esc(x.version || "")}</td><td class="nowrap">${x.last ? fmtTime(x.last) : ""}</td><td><button class="mini danger" data-desk-revoke="${esc(x.id)}">停用</button></td></tr>`; }).join("")}</tbody></table>`
      : '<p class="muted small">还没有电脑装桌面客户端。</p>';
  }
  document.addEventListener("click", async (e) => {
    const id = e.target.dataset && e.target.dataset.deskRevoke; if (!id) return;
    if (!confirm("停用这台电脑的桌面客户端？（它的加速密钥会作废；那台电脑重新登录就会重新配对）")) return;
    try { await api(`/api/desktop/devices/${encodeURIComponent(id)}/revoke`, { json: {} }); loadDevices(); } catch (err) { toast(err.message, true); }
  });
  window.DESKTOP = { info: () => INFO, loadDevices };
})();
