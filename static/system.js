"use strict";
// 系统检查与在线升级（只有老板）
(function () {
  const ICON = { ok: "✅", warn: "⚠️", err: "❌" };
  function show(name) { if (name === "system") { load(); loadErrs().catch(() => {}); loadI18n().catch(() => {}); loadGh().catch(() => {}); } }

  // ---- v2.26 在线更新（GitHub） ----
  function renderGh(st) {
    const when = st.checked_at ? new Date(st.checked_at * 1000).toLocaleString() : "还没检查过";
    let h = `<div>现在的版本 <b>v${esc(st.current)}</b> · 仓库 <span data-notr>${esc(st.repo || "（没填）")}</span> · 令牌 ${st.token_set ? "已填" : '<span class="warn">没填（私有仓库要填）</span>'} · 上次检查：${esc(when)}</div>`;
    if (st.busy && st.busy.on) h += `<div class="warn">⏳ ${esc(st.busy.step)}…</div>`;
    if (st.error) h += `<div class="bad">❌ ${esc(st.error)}</div>`;
    else if (st.available) {
      h += `<div class="ok" style="margin-top:6px">🆕 有新版本 <b>v${esc(st.latest)}</b></div>` + (st.notes || []).map((n) =>
        `<div style="margin-top:4px"><b>v${esc(n.version)}</b> ${esc(n.title)}${n.points.length ? `<ul class="gh-notes">${n.points.map((x) => `<li data-notr>${esc(x)}</li>`).join("")}</ul>` : ""}</div>`).join("");
    } else if (st.latest) h += `<div class="ok">✓ 已经是最新版本</div>`;
    $("#sys-gh-body").innerHTML = h;
    $("#sys-gh-apply").classList.toggle("hidden", !st.available);
    $("#sys-gh-apply").dataset.ver = st.latest || "";
  }
  async function loadGh() { renderGh(await api("/api/system/update")); }
  $("#sys-gh-check").addEventListener("click", (e) => busy(e.target, async () => renderGh(await api("/api/system/update/check", { json: {} }))));
  $("#sys-gh-apply").addEventListener("click", async (e) => {
    const v = e.target.dataset.ver;
    if (!confirm(`从 GitHub 下载 v${v} 并升级？\n升级前会自动备份当前程序，数据不会动；升级后程序自动重启，大约 30 秒到几分钟。`)) return;
    $("#sys-gh-body").innerHTML = "⏳ 正在下载和安装新版本…（不要关闭这个页面）";
    try {
      const r = await api("/api/system/update/apply", { json: {} });
      $("#sys-gh-body").innerHTML = `✅ v${esc(r.from)} → v${esc(r.to)}：更新了 ${r.files} 个文件，旧程序已备份为 ${esc(r.app_backup)}` +
        (r.restart === "auto" ? "<div>程序正在自动重启…</div>" : "<div><b>请关闭黑色窗口，再双击 2_start.bat 重新启动，新版本才会生效。</b></div>");
      if (r.restart === "auto") waitBack(r.to, "#sys-gh-body");
    } catch (err) { $("#sys-gh-body").innerHTML = `<span class="bad">❌ ${esc(err.message)}</span>`; }
  });

  // ---- v2.26 外网访问（Tailscale） ----
  const isTs = (h) => /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(h) || /\.ts\.net$/.test(h);
  async function loadRemote() {
    const box = $("#sys-remote-body"); if (!box) return;
    const r = await api("/api/system/remote");
    const here = location.origin;
    const lan = isTs(location.hostname) ? "" : here;
    const guess = `http://${r.tailscale_ips[0] || "100.81.34.58"}${location.port ? ":" + location.port : ""}`;
    box.innerHTML = `
      <div>现在打开的地址：<b data-notr>${esc(here)}</b> ${isTs(location.hostname) ? '<span class="chip ok">🌐 外网（Tailscale）</span>' : '<span class="chip">局域网</span>'}</div>
      ${r.tailscale_ips.length ? `<div>NAS 上检测到 Tailscale 地址：<b data-notr>${esc(r.tailscale_ips.join("、"))}</b></div>` : ""}
      <div class="row gap wrap" style="margin-top:6px"><label>外网地址 <input id="sys-remote-url" size="32" value="${esc(r.remote_url || guess)}" placeholder="http://100.81.34.58:8790" data-notr></label>
        <button class="mini" id="sys-remote-test">测试这台设备能不能打开</button></div>
      <div id="sys-remote-res"></div>
      <ol class="muted small" style="margin:8px 0 0 18px">
        <li>NAS 上装好 Tailscale（威联通 App Center 搜 Tailscale）并登录；它显示的 100.x.x.x 地址就是 NAS 的外网地址，后面加上端口 <b>:${esc(location.port || r.port || "8790")}</b>。</li>
        <li>手机 / 外面的电脑装 Tailscale（手机在应用商店搜），登录<b>同一个账号</b>，打开连接开关。</li>
        <li>浏览器打开上面的外网地址，用平时的账号密码登录。员工要在外面用，也装 Tailscale，你在 Tailscale 后台把他的设备加进来（或分享 NAS 给他）。</li>
        <li>浏览器 AI 客服扩展（2.8.0）：设置里「外网地址」填这个地址，在店外会自动切换。${lan ? `局域网地址填 <b data-notr>${esc(lan)}</b>。` : ""}</li>
      </ol>
      <p class="muted small">Tailscale 是加密的点对点连接，只有登录了你账号（或你授权）的设备能连上，不需要在路由器上开端口，比直接暴露到公网安全。</p>`;
    lockBox(box, { id: "cfg-general-remote", bar: $("#sys-remote-bar"), label: "✏ 修改", keep: "#sys-remote-test",
      onCancel: () => { LOCKS["cfg-general-remote"].editing = false; loadRemote(); },
      onSave: async () => {
        const r2 = await api("/api/system/remote", { json: { remote_url: $("#sys-remote-url").value } });
        $("#sys-remote-url").value = r2.remote_url; toast("已保存");
      } });
  }

  // ---- v2.27 组件与插件：装了没装都在这里 ----
  const COMP_NAMES = ["依赖组件", "抠图组件（可选）", "去水印增强模型 LaMa（可选）", "泰语字体（卖点图）", "OrcaSlicer"];
  async function loadComps() {
    const box = $("#cfg-comps-body"); if (!box) return;
    const r = await api("/api/system/check");
    const items = r.items.filter((x) => COMP_NAMES.includes(x.name));
    let ext = null;
    try { ext = await api("/api/cs/extension/info"); } catch { ext = null; }
    box.innerHTML = `<table class="grid small sys-tbl"><tbody>${items.map((x) => `<tr class="st-${x.status}"><td class="nowrap">${ICON[x.status]} ${esc(x.name)}</td>
        <td>${esc(x.detail)}</td><td>${x.fix ? `<span class="muted">怎么处理：</span>${esc(x.fix)}` : ""}
        ${x.action ? ` <button class="mini primary" data-sys-act="${esc(x.action)}">安装</button>` : ""}</td></tr>`).join("")}
      ${ext ? `<tr class="st-ok"><td class="nowrap">✅ 浏览器 AI 客服扩展</td><td>最新版本 ${esc(ext.latest)}${ext.in_use && ext.in_use.length ? " · 在用：" + ext.in_use.map((u) => `<span data-notr>${esc(u.name)}</span> ${esc(u.version || "?")}`).join("，") : ""}</td><td>下载和安装方法在下面</td></tr>` : ""}
      </tbody></table>`;
  }
  document.addEventListener("click", async (e) => {
    if (e.target.id === "cfg-comps-reload") return busy(e.target, loadComps);
    if (e.target.id === "sys-remote-test") {
      let u = $("#sys-remote-url").value.trim().replace(/\/+$/, "");
      if (!u) return toast("先填外网地址", true);
      if (!/^https?:\/\//.test(u)) u = "http://" + u;
      $("#sys-remote-res").innerHTML = "⏳ 测试中…";
      const ac = new AbortController(); const t = setTimeout(() => ac.abort(), 8000);
      try {
        const j = await (await fetch(u + "/api/version", { signal: ac.signal, cache: "no-store" })).json();
        $("#sys-remote-res").innerHTML = `<span class="ok">✓ 这台设备能通过外网地址打开（v${esc(j.version)}）</span>`;
      } catch {
        $("#sys-remote-res").innerHTML = '<span class="bad">✗ 这台设备打不开这个地址：检查这台设备的 Tailscale 有没有打开、是不是同一个账号，地址和端口对不对</span>';
      } finally { clearTimeout(t); }
    }
  });
  async function loadI18n() {
    const r = await api("/api/system/i18n");
    $("#sys-i18n").innerHTML = `<h3>${esc(TR("tr.title"))}</h3><p class="small muted">${esc(TR("tr.intro"))}</p>
      <div class="row gap wrap"><a class="btn" href="/api/system/i18n/export">${esc(TR("tr.export"))}</a>
        <label class="filebtn">${esc(TR("tr.import"))}<input type="file" id="sys-i18n-file" accept=".xlsx" hidden></label>
        ${r.count ? `<button class="mini" id="sys-i18n-reset">${esc(TR("tr.reset"))}</button>` : ""}
        <span class="small">${r.count ? esc(TR("tr.status", { n: r.count })) : ""}</span></div>`;
  }
  document.addEventListener("change", async (e) => {
    if (e.target.id !== "sys-i18n-file") return;
    const f = e.target.files[0]; e.target.value = "";
    if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try { const r = await api("/api/system/i18n/import", { method: "POST", body: fd }); toast(TR("tr.imported", { n: r.imported }), false, 6000); loadI18n(); }
    catch (err) { toast(err.message, true); }
  });
  document.addEventListener("click", async (e) => {
    if (e.target.id !== "sys-i18n-reset") return;
    if (!confirm(TR("tr.reset_confirm"))) return;
    try { await api("/api/system/i18n/reset", { json: {} }); loadI18n(); } catch (err) { toast(err.message, true); }
  });
  async function loadErrs() {
    const r = await api("/api/system/errors?n=40");
    $("#sys-errlist").innerHTML = r.items.length ? `<table class="grid small"><thead><tr><th>时间</th><th>类型</th><th>内容</th></tr></thead><tbody>${r.items.map((x) =>
      `<tr><td class="nowrap">${esc(x.time)}</td><td class="nowrap">${x.level === "ERROR" ? '<span class="bad">程序出错</span>' : '<span class="warn">页面出错 / 警告</span>'}</td>
        <td data-notr>${esc(x.text)}${x.detail ? `<details><summary class="muted">详细</summary><pre class="sys-pre">${esc(x.detail)}</pre></details>` : ""}</td></tr>`).join("")}</tbody></table>`
      : '<p class="ok">最近没有错误 ✅</p>';
  }

  async function load() {
    $("#sys-items").innerHTML = '<p class="muted">正在检查…</p>';
    const r = await api("/api/system/check");
    $("#sys-sum").innerHTML = `<span class="chip ok">正常 ${r.summary.ok}</span><span class="chip warn">建议处理 ${r.summary.warn}</span>
      <span class="chip err">需要处理 ${r.summary.err}</span><span class="muted small">v${esc(r.version)} · ${r.docker ? "NAS 版" : "电脑版"}</span>`;
    $("#sys-restart").classList.toggle("hidden", !r.docker);
    const groups = {};
    r.items.forEach((x) => (groups[x.group] = groups[x.group] || []).push(x));
    $("#sys-items").innerHTML = Object.entries(groups).map(([g, xs]) => `<div class="card"><h3>${esc(g)}</h3>
      <table class="grid small sys-tbl"><tbody>${xs.map((x) => `<tr class="st-${x.status}"><td class="nowrap">${ICON[x.status]} ${esc(x.name)}</td>
        <td>${esc(x.detail)}</td><td>${x.fix ? `<span class="muted">怎么处理：</span>${esc(x.fix)}` : ""}
        ${x.action ? ` <button class="mini primary" data-sys-act="${esc(x.action)}">安装</button>` : ""}</td></tr>`).join("")}</tbody></table></div>`).join("");
  }

  async function waitBack(want, box) {
    box = box || "#sys-upres";
    // NAS 重启时程序会断开几十秒；新依赖要安装的话会更久
    const t0 = Date.now();
    while (Date.now() - t0 < 15 * 60 * 1000) {
      await new Promise((ok) => setTimeout(ok, 4000));
      try {
        const r = await fetch("/api/version", { cache: "no-store" });
        if (r.ok) {
          const j = await r.json();
          if (!want || j.version === want) { toast(`已升级到 v${j.version}，页面马上刷新`, false, 4000); setTimeout(() => location.reload(), 1500); return; }
        }
      } catch { /* 还在重启 */ }
      $(box).innerHTML = `正在重启…已等待 ${Math.round((Date.now() - t0) / 1000)} 秒（有新依赖要安装时可能要几分钟）`;
    }
    $(box).innerHTML = "等了很久还没启动好：请到 Container Station 里看容器日志";
  }

  $("#sys-recheck").addEventListener("click", (e) => busy(e.target, load));
  $("#sys-errs").addEventListener("click", (e) => busy(e.target, loadErrs));
  document.addEventListener("click", async (e) => {
    const act = e.target.dataset && e.target.dataset.sysAct;
    if (!act) return;
    if (act === "install_lama") {
      if (!confirm("下载去水印增强模型 LaMa？需要联网下载约 208MB（从 Hugging Face），期间系统可以照常使用。")) return;
      await api("/api/imgtool/install-lama", { json: {} });
      toast("开始下载了，过几分钟点「重新检查」看结果", false, 8000);
      if ($("#sys-items") && $("#sys-items").offsetParent) load(); else loadComps();
      return;
    }
    if (act !== "install_rembg") return;
    if (!confirm("安装抠图组件？需要联网下载约 200MB，大约 5–15 分钟，期间系统可以照常使用。")) return;
    await api("/api/system/install-rembg", { json: {} });
    toast("开始安装了，过 5–15 分钟点「重新检查」看结果", false, 8000);
    if ($("#sys-items") && $("#sys-items").offsetParent) load(); else loadComps();
  });
  $("#sys-upfile").addEventListener("change", async (e) => {
    const f = e.target.files[0]; e.target.value = "";
    if (!f) return;
    if (!confirm(`用「${f.name}」升级？\n升级前会自动备份当前程序，数据不会动。`)) return;
    const fd = new FormData(); fd.append("file", f);
    if ($("#sys-force").checked) fd.append("force", "1");
    $("#sys-upres").innerHTML = "正在上传和升级…";
    try {
      const r = await api("/api/system/upgrade", { method: "POST", body: fd });
      const lines = [`✅ v${r.from} → v${r.to}：更新了 ${r.files} 个文件，旧程序已备份为 ${r.app_backup}`];
      if (r.new_packages.length) lines.push("新增依赖：" + r.new_packages.join(", "));
      if (r.pip) lines.push(r.pip);
      if (r.skipped.length) lines.push("Windows 启动脚本（.bat）没有在线替换，不影响使用");
      if (r.restart === "auto") lines.push("程序正在自动重启…");
      else lines.push("<b>请关闭黑色窗口，再双击 2_start.bat 重新启动，新版本才会生效。</b>");
      $("#sys-upres").innerHTML = lines.map((x) => `<div>${x.startsWith("<b>") ? x : esc(x)}</div>`).join("");
      if (r.restart === "auto") waitBack(r.to);
    } catch (err) { $("#sys-upres").innerHTML = `<span class="err">❌ ${esc(err.message)}</span>`; }
  });
  $("#sys-restart").addEventListener("click", async () => {
    if (!confirm("重启程序？大约 10–30 秒，期间大家都暂时打不开。")) return;
    await api("/api/system/restart", { json: {} });
    $("#sys-upres").innerHTML = "正在重启…";
    waitBack(null);
  });
  window.SYS = { show, load, loadRemote, loadComps };
})();
