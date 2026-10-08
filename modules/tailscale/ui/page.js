"use strict";
// 外网自动加入（Tailscale）：设置 → 通用 里的说明卡片（第一次怎么设置、访问规则、哪些电脑加入了）
(function () {
  async function settings(box) {
    let s;
    try { s = await api("/api/m/tailscale/status"); } catch (e) { box.innerHTML = `<p class="bad small">${esc(e.message)}</p>`; return; }
    const okKey = s.key_set && s.key_ok;
    box.innerHTML = `<h3>外网自动加入：怎么设置（只做一次）</h3>
      <p class="small">${okKey ? '<span class="ok">✓ 已填预授权密钥</span>' : s.key_set ? '<span class="warn">预授权密钥看起来不对（应该是 tskey-auth- 开头）</span>' : '<span class="warn">还没有填预授权密钥：员工电脑不会自动加入</span>'}
        <span class="muted" data-notr>· ${esc(s.tag)} · NAS ${esc(s.nas)}</span>${s.remote_url ? "" : ' <span class="warn">（先在上面「外网访问」填 NAS 的 Tailscale 地址）</span>'}</p>
      <ol class="small">
        <li>打开 Tailscale 网页后台的「访问规则」页面，把下面这段规则整个替换进去，保存。作用：你自己的设备照常全部互通；打了标签的员工电脑只能打开 NAS 上的这个系统，看不到你网络里别的东西。
          <a href="https://login.tailscale.com/admin/acls" target="_blank" rel="noopener">打开访问规则页面 ↗</a></li>
        <li>打开「Keys」页面 → Generate auth key：勾选 Reusable（可重复使用）、有效期选最长（90 天）、Tags 选「设备标签」里的标签（默认 tag:3dops），生成后复制（tskey-auth- 开头）。
          <a href="https://login.tailscale.com/admin/settings/keys" target="_blank" rel="noopener">打开 Keys 页面 ↗</a></li>
        <li>点上面「外网自动加入（Tailscale）」卡片的「✏ 修改」，把密钥粘贴进「预授权密钥」，保存。</li>
        <li>以后员工在店里装桌面客户端 / 加速器并登录，就会自动加入（弹一次「是否允许更改」点「是」）。密钥过期了重新生成一把填进来就行，已经加入的电脑不受影响。</li>
      </ol>
      <div class="row between"><b class="small">访问规则（复制到 Tailscale 后台）</b><button class="mini" id="ts-copy">📋 复制</button></div>
      <pre class="sys-pre" id="ts-acl" data-notr>${esc(s.acl)}</pre>
      <p class="small muted">员工离职或电脑丢了：在 Tailscale 后台 Machines 里删掉那台电脑，再到 设置 → 组件与插件 → 桌面客户端 里停用它。</p>
      <h4>已经连过的电脑</h4>
      ${s.joins.length ? `<table class="grid small"><thead><tr><th>电脑</th><th>加入结果</th><th>Tailscale 地址</th><th>加入时间</th></tr></thead><tbody>${s.joins.map((j) => `<tr><td data-notr>${esc(j.name)}</td>
        <td>${j.ok ? '<span class="ok">✓ 已加入</span>' : `<span class="bad">没成功</span> <span class="muted" data-notr>${esc(j.msg)}</span>`}</td><td data-notr>${esc((j.ips || []).join(", "))}</td><td class="nowrap">${fmtTime(j.at)}</td></tr>`).join("")}</tbody></table>`
        : '<p class="small muted">还没有电脑自动加入过。</p>'}`;
    box.querySelector("#ts-copy").onclick = async () => {
      try { await navigator.clipboard.writeText(s.acl); toast("已复制"); }
      catch { const r = document.createRange(); r.selectNodeContents(box.querySelector("#ts-acl")); getSelection().removeAllRanges(); getSelection().addRange(r); toast("已选中，按 Ctrl+C 复制"); }
    };
  }
  window.MODS.tailscale = { settings };
})();
