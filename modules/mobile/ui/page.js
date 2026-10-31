"use strict";
// 设置 → 组件与插件 → 安卓 App：NAS 上的安装包（从 GitHub 取 / 手动上传）、手机怎么下载安装、手机扫码页地址。
(function () {
  const owner = () => typeof ME === "undefined" || !ME || ME.role === "owner";
  const mb = (n) => (n / 1048576).toFixed(1) + " MB";

  async function settings(box) {
    let s;
    try { s = await api("/api/mobile/apk"); } catch (e) { box.innerHTML = `<div class="card"><p class="bad small">${esc(e.message)}</p></div>`; return; }
    const base = location.origin;
    const lt = s.latest;
    const newer = lt && (!s.have || lt.version !== s.version);
    box.innerHTML = `<div class="card" id="m-apk-card"><div class="row between wrap gap"><h3>📱 安卓 App（手机 / 平板）</h3>
        ${s.have ? `<a class="btn primary" href="/apk">⬇ 下载 App <span data-notr>v${esc(s.version)}</span></a>` : ""}</div>
      <p class="small">平板打开完整的网页版（和电脑一样，只是没有电脑加速、桌面版下载这些电脑才有的东西）；手机打开扫码干活的页面：查订单、扫码发货交接、验货、库存、盘点、货位。
        App 里摄像头一直开着、像扫码枪一样连续扫；蓝牙 / USB 扫码枪也能直接用。</p>
      <table class="grid small"><tbody>
        <tr><td class="nowrap">NAS 上的安装包</td><td>${s.have ? `<b data-notr>v${esc(s.version)}</b> · ${mb(s.size)} · ${s.source === "github" ? "从 GitHub 取的" : "手动上传的"} · <span data-notr>${esc(s.by || "")}</span> ${fmtTime(s.at)}`
          : '<span class="warn">还没有：点下面「从 GitHub 取最新版」，或者上传 APK</span>'}</td></tr>
        <tr><td class="nowrap">GitHub 上最新的</td><td>${lt ? `<span data-notr>v${esc(lt.version)}</span> · ${esc((lt.published_at || "").slice(0, 10))}${newer ? ' <span class="warn">（比 NAS 上的新）</span>' : ' <span class="ok">✓ 已经是最新</span>'}`
          : s.error ? `<span class="muted" data-notr>${esc(s.error)}</span>` : '<span class="muted">还没检查</span>'}
          <span class="muted small">· GitHub: <span data-notr>${esc(s.repo || "—")}</span>（设置 → 通用 → 在线更新）</span></td></tr>
        <tr><td class="nowrap">手机下载地址</td><td><b class="mono" data-notr>${esc(base)}/apk</b> <button class="mini" data-mcopy="${esc(base)}/apk">📋 复制</button></td></tr>
        <tr><td class="nowrap">手机扫码页</td><td><a class="mono" href="/m" target="_blank" data-notr>${esc(base)}/m</a>
          <span class="muted small">（浏览器也能打开；局域网 http 地址浏览器不给开摄像头，要用 App 或扫码枪）</span></td></tr>
      </tbody></table>
      ${owner() ? `<div class="row gap wrap"><button class="mini primary" id="m-apk-fetch">⬇ 从 GitHub 取最新版</button><button class="mini" id="m-apk-check">检查更新</button>
        <label class="filebtn mini-btn small">⬆ 上传 APK<input type="file" id="m-apk-file" accept=".apk,application/vnd.android.package-archive" hidden></label></div>` : ""}
      <h4>怎么安装（每台手机 / 平板做一次）</h4>
      <ol class="small">
        <li>手机连上店里的 Wi-Fi，用浏览器打开 <b class="mono" data-notr>${esc(base)}/apk</b>，下载安装包。</li>
        <li>打开下载好的文件安装：手机提示「禁止安装未知来源应用」时，点「设置」，允许这个浏览器安装应用，再返回安装。</li>
        <li>第一次打开 App 填服务器地址：<b class="mono" data-notr>${esc(base)}</b>（默认已经填好 <span class="mono" data-notr>http://192.168.31.200:8790</span>），点「连接」，再用自己的账号登录。</li>
        <li>App 第一次扫码时会问能不能用摄像头，点「允许」。</li>
        <li>平板自动打开完整网页版，手机自动打开扫码页；点 App 顶部的 ⚙ 可以换服务器地址、切换「手机版 / 网页版」（连不上服务器时也会出来）。</li>
      </ol>
      <p class="small muted">App 有新版本时：在这里点「从 GitHub 取最新版」，再让员工用上面的地址重新下载安装（直接覆盖，登录和地址都还在）。</p></div>`;
    box.querySelectorAll("[data-mcopy]").forEach((b) => (b.onclick = async () => {
      try { await navigator.clipboard.writeText(b.dataset.mcopy); toast("已复制"); } catch { prompt("复制这个地址", b.dataset.mcopy); }
    }));
    const f = box.querySelector("#m-apk-fetch");
    if (f) f.onclick = () => busy(f, async () => { await api("/api/mobile/apk/fetch", { json: {} }); toast("已取到最新版"); settings(box); });
    const c = box.querySelector("#m-apk-check");
    if (c) c.onclick = () => busy(c, async () => { await api("/api/mobile/apk/check", { json: {} }); settings(box); });
    const up = box.querySelector("#m-apk-file");
    if (up) up.onchange = async () => {
      const file = up.files[0]; up.value = "";
      if (!file) return;
      const m = file.name.match(/(\d+\.\d+(?:\.\d+)?)/);
      const ver = prompt("这个安装包的版本号", m ? m[1] : "");
      if (ver === null) return;
      const fd = new FormData(); fd.append("file", file); fd.append("version", ver);
      try { await busyToast("上传中…", () => api("/api/mobile/apk/upload", { method: "POST", body: fd })); toast("已上传"); settings(box); }
      catch (e) { toast(e.message, true); }
    };
  }
  window.MODS = window.MODS || {};
  window.MODS.mobile = Object.assign(window.MODS.mobile || {}, { settings });
})();
