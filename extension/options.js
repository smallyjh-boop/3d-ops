const TH = {
  server: "ที่อยู่ในวง LAN (NAS หรือคอมพิวเตอร์)", key: "API Key",
  server2: "ที่อยู่ภายนอก (Tailscale ไม่บังคับ)", s2help: "ใช้ตอนไม่อยู่ร้าน: ติดตั้ง Tailscale และล็อกอินบัญชีเดียวกัน ถ้าที่อยู่ LAN ใช้ไม่ได้จะสลับมาใช้อันนี้อัตโนมัติ",
  keyhelp: "ในระบบบริหารจัดการ 3D: ระบบ → ตั้งค่า → บัญชีและสิทธิ์ →「คีย์ส่วนขยายของพนักงาน」สร้างใหม่ (พนักงานคนละอัน)", lang: "ภาษาของแผง",
  save: "บันทึกและทดสอบ",
};
const $ = (id) => document.getElementById(id);
function tr(lang) { document.querySelectorAll("[data-t]").forEach((e) => { if (lang === "th" && TH[e.dataset.t]) e.textContent = TH[e.dataset.t]; }); }
chrome.storage.sync.get({ server: "", server2: "", key: "", lang: "zh" }, (d) => { $("server").value = d.server; $("server2").value = d.server2; $("key").value = d.key; $("lang").value = d.lang; tr(d.lang); });
$("save").onclick = async () => {
  let server = $("server").value.trim().replace(/\/+$/, "");
  if (server && !/^https?:\/\//.test(server)) server = "http://" + server;
  let server2 = $("server2").value.trim().replace(/\/+$/, "");
  if (server2 && !/^https?:\/\//.test(server2)) server2 = "http://" + server2;
  await chrome.storage.sync.set({ server, server2, key: $("key").value.trim(), lang: $("lang").value });
  await chrome.storage.local.remove("active");
  $("server").value = server; $("server2").value = server2;
  $("st").textContent = "…";
  chrome.runtime.sendMessage({ type: "api", path: "/api/v1/cs/ping" }, (r) => {
    if (r && r.ok) { $("st").className = "ok"; chrome.storage.local.get({ active: "" }, (l) => { $("st").textContent = `✓ 已连接（${r.data.user}）· 待回复 ${r.data.stats.open}` + (l.active && server2 && l.active === server2 ? " · 外网" : ""); }); }
    else { $("st").className = "bad"; $("st").textContent = "✗ " + ((r && r.error) === "NO_CONFIG" ? "请填写地址和密钥" : (r && r.error) || "连接失败（检查地址、密钥；在店外用要填外网地址并打开 Tailscale）"); }
  });
};
