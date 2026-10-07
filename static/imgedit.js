"use strict";
// 修图（v2.14）：裁剪 / 尺寸、调色、去背景、去水印 / 杂物、背景与阴影、批量处理。
// 裁剪、调色、背景合成在浏览器里做；去背景、去水印在服务器上跑（rembg / LaMa / OpenCV，不用 AI 接口）。
(function () {
  const RATIOS = { "1:1": 1, "3:4": 3 / 4, "4:3": 4 / 3, "16:9": 16 / 9, free: 0 };
  let S = null;   // 当前会话：{ pid, raw, work: canvas, hist: [], tool, crop, mask, adj, dirty }

  // ---------------- 小工具 ----------------
  const mk = (w, h) => { const c = document.createElement("canvas"); c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h)); return c; };
  const clone = (c) => { const o = mk(c.width, c.height); o.getContext("2d").drawImage(c, 0, 0); return o; };
  const loadImg = (src) => new Promise((ok, bad) => { const im = new Image(); im.onload = () => ok(im); im.onerror = () => bad(new Error("图片加载失败")); im.src = src; });
  async function toCanvas(src) { const im = await loadImg(src); const c = mk(im.naturalWidth, im.naturalHeight); c.getContext("2d").drawImage(im, 0, 0); return c; }
  function hasAlpha(c) {
    const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    for (let i = 3; i < d.length; i += 4 * 7) if (d[i] < 250) return true;
    return false;
  }
  // 产品范围：透明图看不透明像素；白底图看「不是接近白色」的像素
  function contentBox(c) {
    const W = c.width, H = c.height, d = c.getContext("2d").getImageData(0, 0, W, H).data, alpha = hasAlpha(c), st = Math.max(1, Math.round(Math.max(W, H) / 800));
    let x0 = W, y0 = H, x1 = -1, y1 = -1;
    for (let y = 0; y < H; y += st) for (let x = 0; x < W; x += st) {
      const i = (y * W + x) * 4;
      const on = alpha ? d[i + 3] > 20 : (d[i] < 238 || d[i + 1] < 238 || d[i + 2] < 238);
      if (on) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    }
    if (x1 < 0) return null;
    return { x: Math.max(0, x0 - st), y: Math.max(0, y0 - st), w: Math.min(W, x1 + st + 1) - Math.max(0, x0 - st), h: Math.min(H, y1 + st + 1) - Math.max(0, y0 - st) };
  }

  // ---------------- 调色 ----------------
  function adjust(src, a) {
    const out = mk(src.width, src.height), g = out.getContext("2d");
    g.filter = `brightness(${1 + a.bright / 100}) contrast(${1 + a.contrast / 100}) saturate(${1 + a.sat / 100})`;
    g.drawImage(src, 0, 0);
    g.filter = "none";
    if (a.warm || a.sharp) {
      const id = g.getImageData(0, 0, out.width, out.height), d = id.data;
      if (a.warm) {
        const k = a.warm / 100 * 0.12;
        for (let i = 0; i < d.length; i += 4) { d[i] = Math.min(255, d[i] * (1 + k)); d[i + 2] = Math.min(255, d[i + 2] * (1 - k)); }
      }
      if (a.sharp) sharpen(id, out.width, out.height, a.sharp / 100);
      g.putImageData(id, 0, 0);
    }
    return out;
  }
  function sharpen(id, W, H, amt) {
    const d = id.data, src = new Uint8ClampedArray(d);
    const k = amt * 0.9;
    for (let y = 1; y < H - 1; y++) for (let x = 1; x < W - 1; x++) {
      const i = (y * W + x) * 4;
      for (let c = 0; c < 3; c++) {
        const v = src[i + c] * (1 + 4 * k) - k * (src[i + c - 4] + src[i + c + 4] + src[i + c - W * 4] + src[i + c + W * 4]);
        d[i + c] = v;
      }
    }
  }
  // 一键提亮白底：把接近白色的背景拉到纯白，整体亮度同比例提高
  function autoWhite(src) {
    const out = clone(src), g = out.getContext("2d"), id = g.getImageData(0, 0, out.width, out.height), d = id.data;
    const hist = [new Uint32Array(256), new Uint32Array(256), new Uint32Array(256)];
    let n = 0;
    for (let i = 0; i < d.length; i += 16) { if (d[i + 3] < 200) continue; hist[0][d[i]]++; hist[1][d[i + 1]]++; hist[2][d[i + 2]]++; n++; }
    const pct = (h) => { let s = 0; for (let v = 255; v >= 0; v--) { s += h[v]; if (s > n * 0.04) return Math.max(v, 150); } return 255; };
    const top = [pct(hist[0]), pct(hist[1]), pct(hist[2])];
    for (let i = 0; i < d.length; i += 4) for (let c = 0; c < 3; c++) d[i + c] = Math.min(255, d[i + c] * 255 / top[c]);
    g.putImageData(id, 0, 0);
    return out;
  }

  // ---------------- 尺寸 / 构图 ----------------
  // 按比例补边（不裁掉产品）；fill：产品占画面比例（自动居中时用）
  function fitTo(src, ratio, side, opt = {}) {
    let W, H;
    if (ratio >= 1) { W = side; H = Math.round(side / ratio); } else { H = side; W = Math.round(side * ratio); }
    const out = mk(W, H), g = out.getContext("2d");
    const transparent = opt.keepAlpha && hasAlpha(src);
    if (!transparent) { g.fillStyle = opt.bg || "#ffffff"; g.fillRect(0, 0, W, H); }
    let b = { x: 0, y: 0, w: src.width, h: src.height };
    let fill = 1;
    if (opt.center) { b = contentBox(src) || b; fill = opt.fill || 0.85; }
    const k = Math.min(W * fill / b.w, H * fill / b.h);
    const w = b.w * k, h = b.h * k;
    g.imageSmoothingQuality = "high";
    g.drawImage(src, b.x, b.y, b.w, b.h, (W - w) / 2, (H - h) / 2, w, h);
    return out;
  }
  function rotate90(src) { const o = mk(src.height, src.width), g = o.getContext("2d"); g.translate(o.width, 0); g.rotate(Math.PI / 2); g.drawImage(src, 0, 0); return o; }
  function flipH(src) { const o = mk(src.width, src.height), g = o.getContext("2d"); g.translate(o.width, 0); g.scale(-1, 1); g.drawImage(src, 0, 0); return o; }
  function scaleTo(src, side) {
    if (!side || Math.max(src.width, src.height) === side) return src;
    const k = side / Math.max(src.width, src.height), o = mk(src.width * k, src.height * k), g = o.getContext("2d");
    g.imageSmoothingQuality = "high"; g.drawImage(src, 0, 0, o.width, o.height); return o;
  }

  // ---------------- 背景与阴影（透明产品图合成） ----------------
  function compose(src, o) {
    const side = Math.max(src.width, src.height);
    const W = o.square ? side : src.width, H = o.square ? side : src.height;
    const out = mk(W, H), g = out.getContext("2d");
    if (o.bg === "gradient") { const gr = g.createLinearGradient(0, 0, 0, H); gr.addColorStop(0, o.c1); gr.addColorStop(1, o.c2); g.fillStyle = gr; g.fillRect(0, 0, W, H); }
    else if (o.bg !== "transparent") { g.fillStyle = o.bg === "custom" ? o.c1 : o.bg; g.fillRect(0, 0, W, H); }
    const b = contentBox(src) || { x: 0, y: 0, w: src.width, h: src.height };
    const k = Math.min(W * o.fill / b.w, H * o.fill / b.h), w = b.w * k, h = b.h * k, x = (W - w) / 2, y = (H - h) / 2 + (o.shadow === "ground" ? -h * 0.02 : 0);
    if (o.shadow === "ground") {
      g.save(); g.translate(W / 2, y + h); g.scale(1, 0.12);
      const r = w * 0.48, gr = g.createRadialGradient(0, 0, 0, 0, 0, r);
      gr.addColorStop(0, `rgba(0,0,0,${0.38 * o.shadowK})`); gr.addColorStop(0.6, `rgba(0,0,0,${0.15 * o.shadowK})`); gr.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = gr; g.beginPath(); g.arc(0, 0, r, 0, Math.PI * 2); g.fill(); g.restore();
    }
    if (o.shadow === "drop") { g.save(); g.shadowColor = `rgba(0,0,0,${0.35 * o.shadowK})`; g.shadowBlur = side * 0.03; g.shadowOffsetX = side * 0.012; g.shadowOffsetY = side * 0.02; }
    g.imageSmoothingQuality = "high";
    g.drawImage(src, b.x, b.y, b.w, b.h, x, y, w, h);
    if (o.shadow === "drop") g.restore();
    return out;
  }

  // ---------------- 界面 ----------------
  function html() {
    return `<div class="ie-wrap" id="ie-wrap"><div class="ie-box">
      <div class="row between"><h3>🎨 修图</h3><span class="row gap"><span id="ie-size" class="small muted"></span><button class="mini" data-ie="close">关闭</button></span></div>
      <div class="ie-main">
        <div class="ie-stage-wrap"><div class="ie-stage" id="ie-stage"><canvas id="ie-cv"></canvas><canvas id="ie-ov"></canvas></div>
          <div class="row gap wrap" style="margin-top:6px"><button class="mini" data-ie="undo">↶ 撤销</button><button class="mini" data-ie="reset">还原到打开时</button>
            <label class="small row gap"><input type="checkbox" id="ie-compare"> 按住看原图</label></div></div>
        <div class="ie-side">
          <div class="ie-tabs">
            <button data-tool="crop" class="on">✂ 裁剪尺寸</button><button data-tool="adj">🎨 调色</button><button data-tool="bg">🪄 去背景</button>
            <button data-tool="fix">🩹 去水印 / 杂物</button><button data-tool="comp">🖼 背景与阴影</button><button data-tool="batch">⚡ 批量</button></div>
          <div id="ie-panel"></div>
        </div>
      </div>
      <div class="row gap wrap ie-foot"><span class="small muted" id="ie-msg"></span>
        <button data-ie="save-new">保存为新图片</button><button class="primary" data-ie="save-rep">替换原图</button></div>
    </div></div>`;
  }
  const PANELS = {
    crop: () => `<p class="small muted">电商主图一般用 1:1（Lazada / Shopee 建议 800–1200 像素以上）。拖动框选要保留的部分，拖右下角改大小。</p>
      <div class="row gap wrap">比例 ${Object.keys(RATIOS).map((k) => `<button class="mini ${S.crop.ratio === k ? "primary-lite" : ""}" data-ratio="${k}">${k === "free" ? "自由" : k}</button>`).join("")}</div>
      <label class="small">输出尺寸（长边）<select id="ie-side">${[0, 800, 1000, 1200, 1500, 2000].map((v) => `<option value="${v}" ${+S.crop.side === v ? "selected" : ""}>${v ? v + " 像素" : "保持原尺寸"}</option>`).join("")}</select></label>
      <div class="row gap wrap"><button class="primary" data-ie="crop-apply">✂ 按框裁剪</button><button data-ie="pad">补白边到这个比例（不裁产品）</button></div>
      <div class="row gap wrap"><button data-ie="center">产品自动居中放大</button><label class="small">占画面<input type="number" id="ie-fill" value="85" min="50" max="98" style="width:60px">%</label></div>
      <div class="row gap wrap"><button class="mini" data-ie="rot">↻ 旋转 90°</button><button class="mini" data-ie="flip">⇋ 左右翻转</button></div>`,
    adj: () => `${[["bright", "亮度"], ["contrast", "对比度"], ["sat", "饱和度"], ["warm", "色温（冷 ← → 暖）"], ["sharp", "锐化"]].map(([k, n]) =>
        `<label class="ie-slider">${n}<input type="range" data-adj="${k}" min="${k === "sharp" ? 0 : -100}" max="100" value="${S.adj[k]}"><span>${S.adj[k]}</span></label>`).join("")}
      <div class="row gap wrap"><button class="primary" data-ie="adj-apply">应用调色</button><button data-ie="adj-zero">归零</button></div>
      <div class="row gap wrap"><button data-ie="white">☀ 一键提亮白底</button><span class="small muted">白底拍得发灰时用：背景拉成纯白，产品颜色同比例提亮</span></div>`,
    bg: () => `<p class="small muted">在服务器上用开源模型抠图（不用 AI 接口、不花钱）。抠完背景是透明的，可以到「背景与阴影」换白底、加阴影。</p>
      <label class="small">模型<select id="ie-bgm"><option value="isnet">标准（快）</option><option value="birefnet">精细 BiRefNet（头发丝、镂空更好，慢一些，第一次要下载模型）</option></select></label>
      <button class="primary" data-ie="rmbg">🪄 去背景</button>
      ${S.st && !S.st.rembg ? '<p class="small warn">抠图组件还没安装：老板在 系统 →「系统检查与升级」→ 抠图组件 点「安装」</p>' : ""}`,
    fix: () => `<p class="small muted">用画笔把要去掉的水印、文字、杂物、灰尘涂满（红色），再点「去除」。只改涂到的地方，其他像素不变。</p>
      <label class="ie-slider">画笔大小<input type="range" id="ie-brush" min="4" max="160" value="${S.brush}"><span>${S.brush}</span></label>
      <div class="row gap wrap"><button class="primary" data-ie="fix-go">🩹 去除涂抹的地方</button><button data-ie="fix-clear">清除涂抹</button></div>
      <p class="small">现在用：<b>${S.st ? ({ lama: "LaMa 修复模型（效果最好）", opencv: "OpenCV 修复（适合小面积）", basic: "基础填充（只适合很小的点）" }[S.st.inpaint] || "") : "…"}</b></p>
      ${S.st && S.st.inpaint !== "lama" ? '<p class="small muted">大面积、复杂背景效果不理想时：老板在 系统 →「系统检查与升级」里安装「去水印增强模型 LaMa」。</p>' : ""}
      <p class="small muted">只用在自己的照片或有授权的图片上。用别人带水印的图会被平台当成盗图处理。</p>`,
    comp: () => `<p class="small muted">用于去过背景（透明）的产品图：换背景、加阴影、产品居中。${S.work && !hasAlpha(S.work) ? '<b class="warn">这张图没有透明背景，先用「去背景」。</b>' : ""}</p>
      <label class="small">背景<select id="ie-bgc"><option value="#ffffff">纯白</option><option value="#f3f4f6">浅灰</option><option value="transparent">透明（PNG）</option><option value="custom">自选颜色</option><option value="gradient">渐变</option></select></label>
      <div class="row gap"><input type="color" id="ie-c1" value="#fef3c7"><input type="color" id="ie-c2" value="#fde68a"></div>
      <label class="small">阴影<select id="ie-sh"><option value="ground">贴地阴影（自然）</option><option value="drop">投影</option><option value="none">不要阴影</option></select></label>
      <label class="ie-slider">阴影深浅<input type="range" id="ie-shk" min="0" max="100" value="60"><span>60</span></label>
      <label class="small">产品占画面<input type="number" id="ie-cfill" value="85" min="40" max="98" style="width:60px">%</label>
      <label class="small row gap"><input type="checkbox" id="ie-square" checked> 做成 1:1 方图</label>
      <button class="primary" data-ie="comp-go">生成</button>`,
    batch: () => `<p class="small muted">把同一套处理一次用到这个产品的多张图（卖点图除外），处理后替换原图（原图有备份，可以恢复）。</p>
      <div class="ie-batch">${(S.getP().images || []).filter((im) => !im.ad).map((im) => `<label class="ie-bimg"><input type="checkbox" data-braw="${esc(im.raw)}" ${im.raw === S.raw ? "checked" : ""}>
        <img src="/files/${S.pid}/${im.processed ? "out" : "raw"}/${encodeURIComponent(im.file)}?t=${S.getP().updated_at}" alt=""></label>`).join("")}</div>
      <label class="small row gap"><input type="checkbox" id="ie-b-white" checked> 一键提亮白底</label>
      <label class="small row gap"><input type="checkbox" id="ie-b-adj"> 用「调色」里现在的数值</label>
      <label class="small row gap"><input type="checkbox" id="ie-b-sq" checked> 补成 1:1 方图，产品居中占 <input type="number" id="ie-b-fill" value="85" min="50" max="98" style="width:56px">%</label>
      <label class="small">长边<select id="ie-b-side"><option value="1200">1200 像素</option><option value="1000">1000 像素</option><option value="800">800 像素</option><option value="0">不改</option></select></label>
      <button class="primary" data-ie="batch-go">⚡ 开始批量处理</button><div id="ie-bprog" class="small"></div>`,
  };

  function setTool(t) {
    S.tool = t;
    document.querySelectorAll("#ie-wrap [data-tool]").forEach((b) => b.classList.toggle("on", b.dataset.tool === t));
    $("#ie-panel").innerHTML = PANELS[t]();
    if (t === "crop" && !S.crop.box) resetCrop();
    drawOverlay();
    if (t === "adj") preview();
    else draw();
  }
  function resetCrop() {
    const W = S.work.width, H = S.work.height, r = RATIOS[S.crop.ratio];
    let w = W, h = H;
    if (r) { if (W / H > r) w = H * r; else h = W / r; }
    S.crop.box = { x: (W - w) / 2, y: (H - h) / 2, w, h };
  }
  function fitStage() {
    const cv = $("#ie-cv"), ov = $("#ie-ov"), st = $("#ie-stage");
    const maxW = Math.min(720, st.parentElement.clientWidth || 720), maxH = Math.min(620, window.innerHeight - 220);
    const k = Math.min(maxW / S.work.width, maxH / S.work.height, 1);
    S.k = k;
    for (const c of [cv, ov]) { c.width = Math.round(S.work.width * k); c.height = Math.round(S.work.height * k); }
    st.style.width = cv.width + "px"; st.style.height = cv.height + "px";
    $("#ie-size").textContent = `${S.work.width} × ${S.work.height}`;
  }
  function draw(src) {
    const cv = $("#ie-cv");
    if (!cv) return;
    const img = src || S.work;
    if (cv.width !== Math.round(img.width * S.k) || cv.height !== Math.round(img.height * S.k)) fitStage();
    const g = cv.getContext("2d");
    g.clearRect(0, 0, cv.width, cv.height);
    g.imageSmoothingQuality = "high";
    g.drawImage(img, 0, 0, cv.width, cv.height);
    drawOverlay();
  }
  function drawOverlay() {
    const ov = $("#ie-ov");
    if (!ov) return;
    const g = ov.getContext("2d"), k = S.k;
    g.clearRect(0, 0, ov.width, ov.height);
    if (S.tool === "crop" && S.crop.box) {
      const b = S.crop.box;
      g.fillStyle = "rgba(0,0,0,0.45)";
      g.fillRect(0, 0, ov.width, ov.height);
      g.clearRect(b.x * k, b.y * k, b.w * k, b.h * k);
      g.strokeStyle = "#fff"; g.lineWidth = 2; g.strokeRect(b.x * k, b.y * k, b.w * k, b.h * k);
      g.strokeStyle = "rgba(255,255,255,0.5)"; g.lineWidth = 1;
      for (let i = 1; i < 3; i++) { g.beginPath(); g.moveTo((b.x + b.w * i / 3) * k, b.y * k); g.lineTo((b.x + b.w * i / 3) * k, (b.y + b.h) * k); g.stroke();
        g.beginPath(); g.moveTo(b.x * k, (b.y + b.h * i / 3) * k); g.lineTo((b.x + b.w) * k, (b.y + b.h * i / 3) * k); g.stroke(); }
      g.fillStyle = "#fff"; g.fillRect((b.x + b.w) * k - 7, (b.y + b.h) * k - 7, 14, 14);
    }
    if (S.tool === "fix" && S.mask) g.drawImage(S.maskView(), 0, 0, ov.width, ov.height);
  }

  function push(newCanvas, msg) {
    S.hist.push(S.work);
    if (S.hist.length > 15) S.hist.shift();
    S.work = newCanvas;
    S.dirty = true;
    S.crop.box = null;
    S.mask = null;
    fitStage();
    if (S.tool === "crop") resetCrop();
    draw();
    if (msg) $("#ie-msg").textContent = msg;
  }
  function preview() {
    if (S.tool !== "adj") return;
    const small = scaleTo(S.work, Math.min(900, Math.max(S.work.width, S.work.height)));
    draw(adjust(small, S.adj));
  }

  // 画笔遮罩（原图尺寸）
  function initMask() {
    if (S.mask) return;
    S.mask = mk(S.work.width, S.work.height);
    S.maskView = () => {
      const v = mk(S.mask.width, S.mask.height), g = v.getContext("2d");
      g.drawImage(S.mask, 0, 0); g.globalCompositeOperation = "source-in"; g.fillStyle = "rgba(239,68,68,0.55)"; g.fillRect(0, 0, v.width, v.height);
      return v;
    };
  }
  function paint(x, y, last) {
    initMask();
    const g = S.mask.getContext("2d");
    g.strokeStyle = g.fillStyle = "#fff"; g.lineCap = "round"; g.lineJoin = "round"; g.lineWidth = S.brush / S.k;
    g.beginPath();
    if (last) { g.moveTo(last[0], last[1]); g.lineTo(x, y); g.stroke(); }
    else { g.arc(x, y, S.brush / S.k / 2, 0, Math.PI * 2); g.fill(); }
    drawOverlay();
  }

  function bindStage() {
    const ov = $("#ie-ov");
    let drag = null;
    const pos = (e) => { const r = ov.getBoundingClientRect(); return [(e.clientX - r.left) / S.k, (e.clientY - r.top) / S.k]; };
    ov.addEventListener("pointerdown", (e) => {
      const [x, y] = pos(e);
      ov.setPointerCapture(e.pointerId);
      if (S.tool === "fix") { drag = { mode: "paint", last: [x, y] }; paint(x, y); return; }
      if (S.tool !== "crop" || !S.crop.box) return;
      const b = S.crop.box, hs = 14 / S.k;
      if (Math.abs(x - (b.x + b.w)) < hs && Math.abs(y - (b.y + b.h)) < hs) drag = { mode: "size", x, y, b: { ...b } };
      else if (x > b.x && x < b.x + b.w && y > b.y && y < b.y + b.h) drag = { mode: "move", x, y, b: { ...b } };
      else drag = { mode: "new", x, y, b: { x, y, w: 1, h: 1 } };
    });
    ov.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const [x, y] = pos(e), W = S.work.width, H = S.work.height;
      if (drag.mode === "paint") { paint(x, y, drag.last); drag.last = [x, y]; return; }
      const r = RATIOS[S.crop.ratio], b = { ...drag.b };
      if (drag.mode === "move") { b.x = Math.min(Math.max(0, drag.b.x + x - drag.x), W - b.w); b.y = Math.min(Math.max(0, drag.b.y + y - drag.y), H - b.h); }
      else {
        const ox = drag.mode === "new" ? drag.x : b.x, oy = drag.mode === "new" ? drag.y : b.y;
        let w = Math.max(20, Math.min(W - ox, x - ox)), h = Math.max(20, Math.min(H - oy, y - oy));
        if (r) { if (w / h > r) w = h * r; else h = w / r; if (ox + w > W) { w = W - ox; h = w / r; } if (oy + h > H) { h = H - oy; w = h * r; } }
        b.x = ox; b.y = oy; b.w = w; b.h = h;
      }
      S.crop.box = b;
      drawOverlay();
    });
    const end = () => { drag = null; };
    ov.addEventListener("pointerup", end); ov.addEventListener("pointercancel", end);
    const cmp = $("#ie-compare");
    ov.addEventListener("pointerdown", () => { if (cmp.checked && S.tool !== "fix" && S.tool !== "crop") draw(S.orig); });
    ov.addEventListener("pointerup", () => { if (cmp.checked && S.tool !== "fix" && S.tool !== "crop") { if (S.tool === "adj") preview(); else draw(); } });
  }

  async function onClick(e) {
    const t = e.target.closest("[data-tool]");
    if (t) { setTool(t.dataset.tool); return; }
    const r = e.target.closest("[data-ratio]");
    if (r) { S.crop.ratio = r.dataset.ratio; resetCrop(); setTool("crop"); return; }
    const b = e.target.closest("[data-ie]");
    if (!b) return;
    const a = b.dataset.ie;
    try {
      if (a === "close") { if (S.dirty && !confirm("修改还没保存，关闭吗？")) return; close(); return; }
      if (a === "undo") { if (!S.hist.length) return; S.work = S.hist.pop(); S.crop.box = null; S.mask = null; fitStage(); if (S.tool === "crop") resetCrop(); draw(); return; }
      if (a === "reset") { if (!confirm("放弃全部修改，回到打开时的样子？")) return; S.hist = []; S.work = clone(S.orig); S.dirty = false; S.crop.box = null; S.mask = null; fitStage(); if (S.tool === "crop") resetCrop(); draw(); return; }
      if (a === "crop-apply") {
        const bx = S.crop.box; if (!bx) return;
        let o = mk(bx.w, bx.h); o.getContext("2d").drawImage(S.work, bx.x, bx.y, bx.w, bx.h, 0, 0, o.width, o.height);
        o = scaleTo(o, +$("#ie-side").value);
        push(o, "已裁剪");
        return;
      }
      if (a === "pad" || a === "center") {
        const ratio = RATIOS[S.crop.ratio] || 1, side = +$("#ie-side").value || Math.max(S.work.width, S.work.height);
        push(fitTo(S.work, ratio, side, { center: a === "center", fill: (+$("#ie-fill").value || 85) / 100, keepAlpha: true }), a === "center" ? "产品已居中" : "已补边");
        return;
      }
      if (a === "rot") { push(rotate90(S.work)); return; }
      if (a === "flip") { push(flipH(S.work)); return; }
      if (a === "adj-apply") { await busy(b, async () => { await new Promise((ok) => setTimeout(ok, 30)); push(adjust(S.work, S.adj), "已应用调色"); }); S.adj = { bright: 0, contrast: 0, sat: 0, warm: 0, sharp: 0 }; setTool("adj"); return; }
      if (a === "adj-zero") { S.adj = { bright: 0, contrast: 0, sat: 0, warm: 0, sharp: 0 }; setTool("adj"); return; }
      if (a === "white") { push(autoWhite(S.work), "已提亮白底"); return; }
      if (a === "rmbg") {
        await busy(b, async () => {
          $("#ie-msg").textContent = "正在去背景…（大图要十几秒）";
          const res = await apiJob("/api/imgtool/removebg", { json: { data: S.work.toDataURL("image/png"), model: $("#ie-bgm").value } });
          push(await toCanvas(res.data), "已去背景（透明）。到「背景与阴影」可以换白底、加阴影");
        });
        return;
      }
      if (a === "fix-clear") { S.mask = null; drawOverlay(); return; }
      if (a === "fix-go") {
        if (!S.mask) { toast("先用画笔涂出要去掉的地方", true); return; }
        await busy(b, async () => {
          $("#ie-msg").textContent = "正在去除…";
          const blk = mk(S.mask.width, S.mask.height), g = blk.getContext("2d");
          g.fillStyle = "#000"; g.fillRect(0, 0, blk.width, blk.height); g.drawImage(S.mask, 0, 0);
          const alpha = hasAlpha(S.work);
          const res = await apiJob("/api/imgtool/inpaint", { json: { data: S.work.toDataURL(alpha ? "image/png" : "image/jpeg", 0.95), mask: blk.toDataURL("image/png") } });
          push(await toCanvas(res.data), TR("ie.fixed", { m: ({ lama: "LaMa", opencv: "OpenCV", basic: TR("ie.basic") })[res.method] || res.method }));
        });
        return;
      }
      if (a === "comp-go") {
        if (!hasAlpha(S.work)) { toast("这张图没有透明背景，先用「去背景」", true); return; }
        push(compose(S.work, { bg: $("#ie-bgc").value, c1: $("#ie-c1").value, c2: $("#ie-c2").value, shadow: $("#ie-sh").value,
          shadowK: (+$("#ie-shk").value || 0) / 100, fill: (+$("#ie-cfill").value || 85) / 100, square: $("#ie-square").checked }), "已生成");
        return;
      }
      if (a === "batch-go") { await busy(b, runBatch); return; }
      if (a === "save-new" || a === "save-rep") {
        if (a === "save-rep" && !confirm("替换原图？原图会备份，以后可以在图片上点「恢复原图」。")) return;
        await busy(b, async () => {
          const alpha = hasAlpha(S.work);
          const data = alpha ? S.work.toDataURL("image/png") : S.work.toDataURL("image/jpeg", 0.93);
          const np = await api(`/api/products/${encodeURIComponent(S.pid)}/images/edited`, { json: { raw: S.raw, data, mode: a === "save-rep" ? "replace" : "new" } });
          S.dirty = false;
          toast(a === "save-rep" ? "已替换原图" : "已保存为新图片");
          if (S.onSaved) S.onSaved(np);
          close();
        });
      }
    } catch (err) { toast(err.message, true); }
  }
  async function runBatch() {
    const raws = [...document.querySelectorAll("#ie-wrap [data-braw]:checked")].map((x) => x.dataset.braw);
    if (!raws.length) { toast("先勾选图片", true); return; }
    if (!confirm(TR("ie.batch_confirm", { n: raws.length }))) return;
    const prog = $("#ie-bprog");
    for (let i = 0; i < raws.length; i++) {
      const im = (S.getP().images || []).find((x) => x.raw === raws[i]);
      if (!im) continue;
      prog.textContent = TR("ie.batch_progress", { i: i + 1, n: raws.length });
      let c = await toCanvas(`/files/${S.pid}/${im.processed ? "out" : "raw"}/${encodeURIComponent(im.file)}?t=${Date.now()}`);
      if ($("#ie-b-adj").checked) c = adjust(c, S.adj);
      if ($("#ie-b-white").checked) c = autoWhite(c);
      const side = +$("#ie-b-side").value;
      if ($("#ie-b-sq").checked) c = fitTo(c, 1, side || Math.max(c.width, c.height), { center: true, fill: (+$("#ie-b-fill").value || 85) / 100 });
      else c = scaleTo(c, side);
      const alpha = hasAlpha(c);
      const np = await api(`/api/products/${encodeURIComponent(S.pid)}/images/edited`, { json: { raw: im.raw, data: alpha ? c.toDataURL("image/png") : c.toDataURL("image/jpeg", 0.93), mode: "replace" } });
      if (S.onSaved) S.onSaved(np);
    }
    prog.textContent = TR("ie.batch_done", { n: raws.length });
    toast(TR("ie.batch_toast", { n: raws.length }));
  }
  function onInput(e) {
    const t = e.target;
    if (t.dataset.adj) { S.adj[t.dataset.adj] = +t.value; t.nextElementSibling.textContent = t.value; clearTimeout(S.pt); S.pt = setTimeout(preview, 60); return; }
    if (t.id === "ie-brush") { S.brush = +t.value; t.nextElementSibling.textContent = t.value; return; }
    if (t.id === "ie-shk") t.nextElementSibling.textContent = t.value;
  }
  function onKey(e) {
    if (!S) return;
    if (e.key === "Escape") { e.stopPropagation(); if (!S.dirty || confirm("修改还没保存，关闭吗？")) close(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); $("#ie-wrap [data-ie=undo]").click(); }
  }
  function close() {
    const w = $("#ie-wrap"); if (w) w.remove();
    document.removeEventListener("keydown", onKey, true);
    S = null;
  }

  // opts: { pid, raw, src, onSaved }
  async function open(opts) {
    if (S) close();
    const work = await toCanvas(opts.src);
    S = { pid: opts.pid, raw: opts.raw, onSaved: opts.onSaved, getP: opts.getP || (() => ({ images: [] })), work, orig: clone(work), hist: [], tool: "crop", crop: { ratio: "1:1", side: 1200, box: null },
      adj: { bright: 0, contrast: 0, sat: 0, warm: 0, sharp: 0 }, brush: 28, mask: null, k: 1, st: null };
    document.body.insertAdjacentHTML("beforeend", html());
    const w = $("#ie-wrap");
    w.addEventListener("click", onClick);
    w.addEventListener("input", onInput);
    document.addEventListener("keydown", onKey, true);
    fitStage();
    bindStage();
    setTool("crop");
    api("/api/imgtool/status").then((st) => { if (S) { S.st = st; if (["bg", "fix"].includes(S.tool)) setTool(S.tool); } }).catch(() => {});
  }
  window.IMGEDIT = { open, _t: { adjust, autoWhite, fitTo, compose, contentBox } };
})();
