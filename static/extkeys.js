"use strict";
// 设置 → 账号与权限：员工的扩展密钥（浏览器扩展用：AI 客服、运营写回…）。v2.30 从客服模块搬到内核。
(function () {
  const isOwner = () => window.OPSH && OPSH.isOwner();
  const TH = () => window.I18N && I18N.lang === "th";
  const Z = (zh, th) => (TH() ? th : zh);
  async function loadKeys() {
    const box = $("#ext-keys");
    if (!isOwner()) { box.innerHTML = '<p class="small muted">密钥由老板生成，请向老板要你自己的密钥。</p>'; return; }
    const d = await api("/api/integrations");
    box.innerHTML = `<h3>员工的扩展密钥（API 密钥）</h3>
      <p class="small muted">${Z("每个用扩展的员工建一个，名字用员工的登录账号名，填到扩展设置里。员工离职时删掉他的密钥即可。当前扩展版本", "สร้างให้พนักงานแต่ละคน ตั้งชื่อเป็นชื่อบัญชีเข้าระบบของพนักงาน ถ้าพนักงานลาออกให้ลบคีย์ เวอร์ชันส่วนขยายล่าสุด")} <b data-notr>${esc(d.ext_latest || "")}</b>：${Z("「扩展版本」显示旧版的，请重新下载扩展，解压覆盖原来的文件夹，再到 chrome://extensions 点扩展上的 ⟳ 重新加载。", "ถ้าเป็นเวอร์ชันเก่า ให้ดาวน์โหลดใหม่ แตกไฟล์ทับโฟลเดอร์เดิม แล้วกด ⟳ ที่ chrome://extensions")}</p>
      <div class="row gap wrap"><input id="ck-name" placeholder="员工名字，例如 Nok" style="width:200px" data-notr><button class="primary" data-xk="key-new">生成密钥</button></div>
      <div id="ck-out"></div>
      <table class="grid small"><thead><tr><th>名称</th><th>密钥开头</th><th>扩展版本</th><th>最后使用</th><th>次数</th><th></th></tr></thead><tbody>
      ${d.keys.map((k) => `<tr><td data-notr>${esc(k.name)}</td><td class="mono" data-notr>${esc(k.prefix)}…</td>
        <td>${!k.ext_version ? "-" : k.ext_version === d.ext_latest ? `<span class="ok" data-notr>${esc(k.ext_version)}</span>` : `<span class="warn">${esc(k.ext_version === "旧版" ? Z("旧版", "เวอร์ชันเก่า") : k.ext_version)} → ${Z("请更新扩展", "กรุณาอัปเดตส่วนขยาย")}</span>`}</td>
        <td>${k.last_used ? fmtTime(k.last_used) : "-"}</td><td>${k.uses || 0}</td>
        <td><button class="mini danger" data-xk="key-del" data-id="${k.id}">删除</button></td></tr>`).join("") || '<tr><td colspan="6" class="muted">还没有密钥</td></tr>'}</tbody></table>`;
  }
  document.addEventListener("click", async (e) => {
    const b = e.target.closest && e.target.closest("#ext-keys [data-xk]");
    if (!b) return;
    const a = b.dataset.xk, id = b.dataset.id;
    try {
      if (a === "key-new") {
        const name = $("#ck-name").value.trim() || "AI 客服扩展";
        const r = await api("/api/apikeys", { json: { name } });
        await loadKeys();
        $("#ck-out").innerHTML = `<p class="note-flag">新密钥（只显示这一次，请复制给员工）：<b class="mono" data-notr>${esc(r.key)}</b>
          <button class="mini" data-xk="key-copy" data-k="${esc(r.key)}">复制</button></p>`;
      }
      if (a === "key-copy") { try { await navigator.clipboard.writeText(b.dataset.k); toast("已复制"); } catch { toast(b.dataset.k, false, 20000); } }
      if (a === "key-del") { if (!confirm("删除这个密钥？用它的扩展会马上不能用。")) return; await api(`/api/apikeys/${id}`, { method: "DELETE" }); loadKeys(); }
    } catch (err) { toast(err.message, true); }
  });
  window.EXTKEYS = { load: () => loadKeys().catch((e) => toast(e.message, true)) };
})();
