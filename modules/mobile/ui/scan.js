"use strict";
// 手机页的「扫码枪」：一直开着的摄像头小窗（屏幕上面 1/4）连续识别条码 / 二维码，像扫码枪一样把码送给当前页面。
// 码从哪来（都走 SCAN.feed）：
//   native  安卓 App 里：原生摄像头（CameraX + ML Kit）识别，App 调 window.onNativeScan(code)
//   cam     普通浏览器：BarcodeDetector（要 https 或 localhost；局域网 http 地址浏览器不给开摄像头 → 提示装 App / 用扫码枪）
//   wedge   蓝牙 / USB 扫码枪（模拟键盘：很快地打一串字再按回车）
//   manual  手动输入框
// 去重：摄像头一直对着同一个码时只算一次——同一个码 2 秒内一直看得到就不重复（拿开 2 秒再对准才算第二次）。
// 反馈：成功「嘀」+ 短震；警告两声；出错长鸣 + 长震 + 屏幕闪红。
(function () {
  const DEDUP_MS = 2000;
  const seen = {};                 // 摄像头：码 → 最后一次看到的时间
  let handler = null, stream = null, det = null, timer = null, running = false, wantOn = true;
  const app = () => window.Android3D || null;
  const isApp = () => { try { return !!(app() && app().isApp()); } catch { return false; } };

  // ---------------- 反馈 ----------------
  let actx = null;
  function tone(freq, ms, vol = 0.2, delay = 0) {
    try {
      actx = actx || new (window.AudioContext || window.webkitAudioContext)();
      const o = actx.createOscillator(), g = actx.createGain();
      o.type = "square"; o.frequency.value = freq; g.gain.value = vol;
      o.connect(g); g.connect(actx.destination);
      const t = actx.currentTime + delay / 1000;
      o.start(t); o.stop(t + ms / 1000);
    } catch { /* 没有声音也行 */ }
  }
  function vib(p) { try { if (navigator.vibrate) navigator.vibrate(p); } catch { /* 忽略 */ } }
  function flash(cls) {
    const f = document.getElementById("flash");
    if (!f) return;
    f.className = ""; void f.offsetWidth; f.className = cls;
  }
  function feedback(kind) {
    const a = app();
    if (a && isApp()) {
      try { a.beep(kind === "ok" ? "ok" : kind === "warn" ? "warn" : "error"); } catch { /* 老版本 App */ try { a.beep(kind === "ok"); } catch { /* 忽略 */ } }
    } else if (kind === "ok") { tone(1800, 90); vib(60); }
    else if (kind === "warn") { tone(900, 120); tone(900, 120, 0.2, 180); vib([80, 80, 80]); }
    else { tone(220, 700, 0.3); vib([500, 120, 500]); }
    flash(kind === "ok" ? "f-ok" : kind === "warn" ? "f-warn" : "f-bad");
  }

  // ---------------- 码送到页面 ----------------
  function feed(code, src) {
    code = String(code || "").replace(/[\r\n\t]+/g, "").trim();
    if (!code) return;
    if (src === "cam" || src === "native") {
      const now = Date.now(), last = seen[code] || 0;
      seen[code] = now;
      if (now - last < DEDUP_MS) return;
    }
    const st = document.getElementById("cam-last");
    if (st) st.textContent = code;
    if (handler) {
      try { handler(code, src); } catch (e) { console.error(e); }
    }
  }
  window.onNativeScan = (code) => feed(code, "native");

  // ---------------- 扫码枪（键盘输入） ----------------
  // 扫码枪很快（每个字 < 50 毫秒）打一串字再回车；人打字慢。在别的输入框里扫到的也接住（把打进去的字还原）。
  let buf = "", lastKey = 0, startVal = null, burstEl = null;
  const isText = (el) => el && ((el.tagName === "INPUT" && !["checkbox", "radio", "button", "submit", "file", "range"].includes(el.type)) || el.tagName === "TEXTAREA");
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    const now = performance.now(), gap = now - lastKey;
    lastKey = now;
    const el = document.activeElement;
    if (e.key === "Enter") {
      const code = buf; buf = "";
      if (code.length < 2 || gap > 80) return;
      if (el && el.id === "scan-in") return;                      // 手动输入框自己处理回车
      if (isText(el) && code.length < 4) return;                  // 在数量框里快速打两三个字：当成人在输入
      e.preventDefault();
      if (isText(el) && el === burstEl && startVal !== null) el.value = startVal;   // 扫进了数量框之类的：还原
      feed(code, "wedge");
      return;
    }
    if (!e.key || e.key.length !== 1) return;
    if (gap > 50 || !buf) { buf = ""; startVal = isText(el) ? el.value : null; burstEl = el; }
    buf += e.key;
  }, true);

  // ---------------- 摄像头 ----------------
  function msg(html) {
    const m = document.getElementById("cam-msg"), box = camBox();
    if (m) { m.innerHTML = html || ""; m.classList.toggle("hidden", !html); }
    if (box) box.classList.toggle("cam-na", !!html);           // 用不了摄像头：收成一行提示，不占 1/4 屏幕
  }
  function camBox() { return document.getElementById("cam"); }
  async function start() {
    wantOn = true;
    try { localStorage.setItem("m3d_cam", "1"); } catch { /* 忽略 */ }
    const box = camBox();
    if (isApp()) {                    // App 里用原生摄像头（在网页上面的那一条）
      if (box) box.classList.add("hidden");
      document.body.classList.add("native-cam");
      try { app().startScan(); running = true; } catch (e) { console.error(e); }
      render();
      return;
    }
    if (box) box.classList.remove("hidden");
    if (running) return;
    const T = window.MT || ((k) => k);
    if (!("BarcodeDetector" in window)) { msg(T("cam.nodetector")); render(); return; }
    if (!window.isSecureContext || !navigator.mediaDevices) { msg(T("cam.insecure")); render(); return; }
    try {
      const fm = await BarcodeDetector.getSupportedFormats();
      const want = ["code_128", "code_39", "code_93", "ean_13", "ean_8", "upc_a", "upc_e", "itf", "codabar", "qr_code", "data_matrix", "pdf417", "aztec"];
      det = new BarcodeDetector({ formats: want.filter((f) => fm.includes(f)) });
      stream = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } } });
    } catch (e) { msg(T("cam.denied") + ` <span class="muted">(${String(e && e.name || e)})</span>`); render(); return; }
    const v = document.getElementById("cam-video");
    v.srcObject = stream;
    try { await v.play(); } catch { /* 静音视频一般能播 */ }
    msg("");
    running = true;
    try { if (navigator.wakeLock) navigator.wakeLock.request("screen").catch(() => {}); } catch { /* 忽略 */ }
    const tick = async () => {
      if (!running) return;
      if (v.readyState >= 2 && !document.hidden) {
        try { const codes = await det.detect(v); for (const c of codes) feed(c.rawValue, "cam"); } catch { /* 下一帧 */ }
      }
      timer = setTimeout(tick, 110);
    };
    tick();
    render();
  }
  function stop(remember = true) {
    if (remember) { wantOn = false; msg(""); try { localStorage.setItem("m3d_cam", "0"); } catch { /* 忽略 */ } }
    running = false;
    clearTimeout(timer);
    if (isApp()) { try { app().stopScan(); } catch { /* 忽略 */ } document.body.classList.remove("native-cam"); }
    if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
    const box = camBox();
    if (box && !isApp()) box.classList.add("cam-off");
    render();
  }
  function render() {
    const box = camBox(), b = document.getElementById("cam-toggle");
    if (box) box.classList.toggle("cam-off", !running);
    if (b) b.dataset.on = running ? "1" : "";
    document.dispatchEvent(new CustomEvent("scan-state", { detail: { running, app: isApp() } }));
  }
  function camWanted() { try { return localStorage.getItem("m3d_cam") !== "0"; } catch { return true; } }
  // 切到后台时关摄像头省电，回来再开
  document.addEventListener("visibilitychange", () => {
    if (isApp()) return;            // App 自己管（onPause / onResume）
    if (document.hidden && running) { stop(false); wantOn = true; } else if (!document.hidden && wantOn && camWanted() && !running) start();
  });

  window.SCAN = {
    feed, start, stop, isApp, feedback,
    ok: () => feedback("ok"), warn: () => feedback("warn"), bad: () => feedback("error"),
    on: (fn) => { handler = fn; },
    running: () => running,
    wanted: camWanted,
    toggle: () => (running ? stop() : start()),
  };
})();
