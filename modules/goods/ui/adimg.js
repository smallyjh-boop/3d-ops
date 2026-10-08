"use strict";
// 卖点图编辑器：在商品图上加大标题、卖点、角标。AI 只推荐文字，放不放、放哪里、写什么由人决定。
// 画面在 <canvas> 上合成（预览和导出用同一个绘制函数，所见即所得）。依赖 app.js 的全局：P, api, toast, busy, esc, MODAL, imgSrc, renderImages, saveProduct, dirty
(function () {
  const S = 1200;                       // 导出尺寸（服务器会再缩放到设置里的图片尺寸）
  const FONTS = [["Kanit", "Kanit（圆润醒目，推荐）"], ["Prompt", "Prompt（现代简洁）"], ["Mitr", "Mitr（可爱活泼）"], ["Sarabun", "Sarabun（正式清晰）"],
    ["Chakra Petch", "Chakra Petch（科技感）"], ["system", "系统字体"]];
  const FALLBACK = "'Leelawadee UI','Noto Sans Thai','Thonburi',Tahoma,'Microsoft YaHei','PingFang SC',sans-serif";
  const THEMES = {
    orange: { name: "橙色热卖", main: "#EE4D2D", accent: "#FFD23F", ink: "#1f1f1f", on: "#ffffff" },
    blue: { name: "蓝色清爽", main: "#1A73E8", accent: "#FFC400", ink: "#14213d", on: "#ffffff" },
    black: { name: "黑金质感", main: "#1E1E1E", accent: "#D4AF37", ink: "#1E1E1E", on: "#ffffff" },
    pink: { name: "粉色可爱", main: "#FF5C93", accent: "#FFE066", ink: "#3d1f2b", on: "#ffffff" },
    green: { name: "绿色自然", main: "#2E9E5B", accent: "#F5D547", ink: "#173a26", on: "#ffffff" },
    purple: { name: "紫色潮流", main: "#7B3FE4", accent: "#FFCF33", ink: "#24124a", on: "#ffffff" },
    red: { name: "红色大促", main: "#D7261E", accent: "#FFE14D", ink: "#2b0d0b", on: "#ffffff" },
    teal: { name: "青色清新", main: "#0E9F9A", accent: "#FFB703", ink: "#0b3134", on: "#ffffff" },
    kraft: { name: "原木手作", main: "#8B5E34", accent: "#F2C14E", ink: "#3a2614", on: "#ffffff" },
    mono: { name: "黑白极简", main: "#111827", accent: "#9CA3AF", ink: "#111827", on: "#ffffff" },
  };
  // 「按产品颜色」：从底图里取产品的主色，配一套协调的颜色（不用 AI）
  function autoPalette(img) {
    const c = document.createElement("canvas"), n = 64; c.width = c.height = n;
    const g = c.getContext("2d"); g.drawImage(img, 0, 0, n, n);
    const d = g.getImageData(0, 0, n, n).data, bins = {};
    for (let i = 0; i < d.length; i += 4) {
      const r = d[i], gg = d[i + 1], b = d[i + 2], mx = Math.max(r, gg, b), mn = Math.min(r, gg, b);
      if (mx > 235 && mn > 225) continue;                  // 白底
      if (mx - mn < 28) continue;                          // 灰色、黑色不当主色
      const k = `${r >> 5},${gg >> 5},${b >> 5}`;
      (bins[k] = bins[k] || [0, 0, 0, 0]);
      bins[k][0] += r; bins[k][1] += gg; bins[k][2] += b; bins[k][3]++;
    }
    const top = Object.values(bins).sort((a, b) => b[3] - a[3])[0];
    if (!top) return null;
    let [r, g2, b] = [top[0] / top[3], top[1] / top[3], top[2] / top[3]];
    // 转 HSL，主色压暗一点、加饱和，保证白字看得清
    r /= 255; g2 /= 255; b /= 255;
    const mx = Math.max(r, g2, b), mn = Math.min(r, g2, b); let h = 0; const l = (mx + mn) / 2, dd = mx - mn;
    if (dd) { h = mx === r ? ((g2 - b) / dd) % 6 : mx === g2 ? (b - r) / dd + 2 : (r - g2) / dd + 4; h *= 60; if (h < 0) h += 360; }
    const hsl = (H, S2, L2) => `hsl(${Math.round(H)},${Math.round(S2)}%,${Math.round(L2)}%)`;
    const toHex = (css) => { const t = document.createElement("canvas").getContext("2d"); t.fillStyle = css; return t.fillStyle; };
    return { name: "按产品颜色", main: toHex(hsl(h, 72, Math.min(42, Math.max(30, l * 100)))), accent: toHex(hsl((h + 180) % 360 > 30 && (h + 180) % 360 < 70 ? (h + 180) % 360 : 45, 95, 58)),
             ink: toHex(hsl(h, 40, 14)), on: "#ffffff" };
  }
  const TEMPLATES = {
    side: "卖点列表（左侧图标 + 短句）",
    callout: "引线标注（卖点指向产品部位）",
    cards: "卖点卡片（底部 2×2 宫格）",
    split: "左文右图（产品缩小靠右）",
    bottom: "底部色条（标题 + 卖点）",
    top: "顶部横幅 + 底部卖点",
    frame: "彩色相框 + 底部标题",
    gradient: "底部渐变 + 白字",
    promo: "大促（斜角飘带 + 大角标）",
    minimal: "极简（小标题 + 细线）",
    clean: "干净主图（只放角标）",
  };
  const KIND_ZH = { title: "大标题", sub: "副标题", point: "卖点", callout: "引线标注", badge: "圆形角标", tag: "标签", shape: "色块" };
  const ICON_ZH = { check: "✔ 对勾", truck: "🚚 快递", star: "★ 星", ruler: "📏 尺寸", palette: "🎨 颜色", gift: "🎁 礼物",
    shield: "🛡 保障", heart: "♥ 心", sparkle: "✦ 闪光", clock: "⏱ 时间", box: "📦 包装", leaf: "🍃 自然", home: "🏠 家居", tag: "🏷 标签", "": "无图标" };
  const ICONS = {
    check: "M5 12.5l4.5 4.5L19 7.5",
    truck: "M2 6h11v9H2z M13 9h4l3 3v3h-7z M5 17.5a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0 -3 0 M15.5 17.5a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0 -3 0",
    star: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z",
    ruler: "M3 15L15 3l6 6L9 21z M7 11l2 2 M10 8l2 2 M13 5l2 2",
    palette: "M12 3a9 9 0 1 0 0 18c1 0 1.5-.7 1.5-1.5 0-.9-.7-1.2-.7-2 0-.8.7-1.5 1.5-1.5H17a4 4 0 0 0 4-4c0-5-4-9-9-9z M7.5 11.5h.01 M10 7.5h.01 M14.5 7.5h.01",
    gift: "M3 9h18v4H3z M5 13h14v8H5z M12 9v12 M12 9C10 5 6 5 7.5 7.5 8.5 9 12 9 12 9s3.5 0 4.5-1.5C18 5 14 5 12 9z",
    shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z M8.5 12l2.5 2.5 4.5-5",
    heart: "M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10z",
    sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z M19 16l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z",
    clock: "M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0 M12 7v5l3 2",
    box: "M12 3l8 4.5v9L12 21l-8-4.5v-9z M4 7.5l8 4.5 8-4.5 M12 12v9",
    leaf: "M5 19C5 10 11 5 20 4c-1 9-6 15-15 15z M5 19l8-8",
    home: "M3 11l9-7 9 7 M5 10v10h14V10 M10 20v-6h4v6",
    tag: "M3 12V3h9l9 9-9 9z M7.5 7.5h.01",
  };
  const PATHS = {};
  const icon = (k) => PATHS[k] || (PATHS[k] = new Path2D(ICONS[k] || ICONS.check));

  let D = null;          // 当前设计稿
  let SEL = null;        // 选中的图层 id
  let BASE = null;       // 底图 Image
  let BOXES = [];        // 每个图层在画布上的范围（点选、拖动用）
  let HIST = [];
  let DIRTY = false;
  let SUG = null;        // AI 推荐（不会自动放到图上）
  let cv = null, ctx = null;
  const uid = () => Math.random().toString(36).slice(2, 9);
  const th = () => (D.theme === "auto" && D.palette) ? D.palette : (THEMES[D.theme] || THEMES.orange);
  let GUIDES = [];       // 拖动时的对齐参考线
  const pref = (k, v) => { try { if (v === undefined) return localStorage.getItem("ad_" + k); localStorage.setItem("ad_" + k, v); } catch { /* 无痕模式等 */ } return null; };

  // ---------------- 绘制 ----------------
  function fontStr(L) {
    const fam = D.font === "system" ? FALLBACK : `'${D.font}',${FALLBACK}`;
    return `${L.weight || 700} ${Math.round(L.size * S)}px ${fam}`;
  }
  const seg = (window.Intl && Intl.Segmenter) ? new Intl.Segmenter("th", { granularity: "word" }) : null;
  function words(t) { return seg ? [...seg.segment(t)].map((x) => x.segment) : t.split(/(\s+)/); }
  function wrap(text, maxW) {
    const out = [];
    for (const para of String(text || "").split("\n")) {
      let line = "";
      for (const w of words(para)) {
        const t = line + w;
        if (line && ctx.measureText(t).width > maxW) { out.push(line.trim()); line = w.trimStart(); } else line = t;
      }
      out.push(line.trim());
    }
    return out;
  }
  // 把颜色往白色混合 k（0–1），做浅色背景
  function shade(hex, k) {
    const t = document.createElement("canvas").getContext("2d"); t.fillStyle = hex; const h = t.fillStyle;
    const n = parseInt(h.slice(1), 16), r = n >> 16, gg = (n >> 8) & 255, b = n & 255, m = (v) => Math.round(v + (255 - v) * k);
    return `rgb(${m(r)},${m(gg)},${m(b)})`;
  }
  function rr(g, x, y, w, h, r) {
    r = Math.min(r, h / 2, w / 2);
    g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath();
  }
  function drawIcon(g, k, cx, cy, d, color) {
    g.save(); g.translate(cx - d / 2, cy - d / 2); g.scale(d / 24, d / 24);
    g.strokeStyle = color; g.lineWidth = 2.2; g.lineCap = "round"; g.lineJoin = "round"; g.stroke(icon(k)); g.restore();
  }
  function draw(g, opt = {}) {
    ctx = g;
    BOXES = [];
    g.clearRect(0, 0, S, S);
    g.fillStyle = "#fff"; g.fillRect(0, 0, S, S);
    const IM = D.img || {};
    if (IM.bg && IM.bg !== "none") {          // 底图缩小后露出来的背景
      if (IM.bg === "main") g.fillStyle = th().main;
      else if (IM.bg === "soft") { const gr = g.createLinearGradient(0, 0, 0, S); gr.addColorStop(0, "#ffffff"); gr.addColorStop(1, shade(th().main, 0.88)); g.fillStyle = gr; }
      else if (IM.bg === "theme") g.fillStyle = shade(th().main, 0.9);
      else if (IM.bg !== "main") g.fillStyle = IM.bg;
      g.fillRect(0, 0, S, S);
      if (IM.panel) { const [px, py, pw, ph] = IM.panel; g.fillStyle = "#ffffff"; rr(g, px * S, py * S, pw * S, ph * S, S * 0.025); g.fill(); }
    }
    if (BASE) {
      const sc = IM.scale || 1;
      const r = Math.max(S / BASE.naturalWidth, S / BASE.naturalHeight) * sc;
      const w = BASE.naturalWidth * r, h = BASE.naturalHeight * r;
      const cx = S / 2 + (IM.dx || 0) * S, cy = S / 2 + (IM.dy || 0) * S;
      if (IM.bg && IM.bg !== "none" && sc < 1) {     // 缩小的产品图：白底变透明感（正片叠底），融进背景
        g.save(); g.globalCompositeOperation = "multiply"; g.drawImage(BASE, cx - w / 2, cy - h / 2, w, h); g.restore();
      } else g.drawImage(BASE, cx - w / 2, cy - h / 2, w, h);
    }
    for (const L of D.layers) {
      if (L.hidden) continue;
      const box = drawLayer(g, L);
      if (box) BOXES.push({ id: L.id, ...box });
    }
    if (opt.select && GUIDES.length) {
      g.save(); g.strokeStyle = "#ec4899"; g.lineWidth = 2;
      GUIDES.forEach(([k, v]) => { g.beginPath(); if (k === "x") { g.moveTo(v * S, 0); g.lineTo(v * S, S); } else { g.moveTo(0, v * S); g.lineTo(S, v * S); } g.stroke(); });
      g.restore();
    }
    if (opt.select) {
      const b = BOXES.find((x) => x.id === SEL);
      if (b) { g.save(); g.setLineDash([10, 8]); g.strokeStyle = "#2563eb"; g.lineWidth = 3; g.strokeRect(b.x - 6, b.y - 6, b.w + 12, b.h + 12); g.restore(); }
      if (opt.guides) {   // 安全边距
        g.save(); g.setLineDash([4, 8]); g.strokeStyle = "rgba(37,99,235,.35)"; g.lineWidth = 2; g.strokeRect(S * 0.04, S * 0.04, S * 0.92, S * 0.92); g.restore();
      }
    }
  }
  function drawLayer(g, L) {
    const T = th();
    const x = L.x * S, y = L.y * S;
    if (L.kind === "shape") {
      const w = (L.w || 1) * S, h = (L.h || 0.2) * S;
      g.save(); g.globalAlpha = L.grad ? 1 : (L.opacity ?? 1);
      if (L.grad) { const gr = g.createLinearGradient(0, y, 0, y + h); gr.addColorStop(0, "rgba(0,0,0,0)"); gr.addColorStop(1, "rgba(0,0,0,0.78)"); g.fillStyle = gr; }
      else g.fillStyle = L.color || T.main;
      rr(g, x, y, w, h, (L.radius || 0) * S); g.fill(); g.restore();
      return { x, y, w, h };
    }
    g.font = fontStr(L);
    g.textBaseline = "alphabetic";
    const fs = L.size * S, lh = fs * 1.22;
    if (L.kind === "badge") {
      const lines = wrap(L.text, fs * 4.2);
      const tw = Math.max(...lines.map((t) => g.measureText(t).width), fs);
      const d = Math.max(tw + fs * 1.1, lines.length * lh + fs * 1.0);
      const cx = x, cy = y + d / 2;
      g.save(); g.fillStyle = L.bgColor || T.main; g.beginPath(); g.arc(cx, cy, d / 2, 0, Math.PI * 2); g.fill();
      g.strokeStyle = "rgba(255,255,255,.9)"; g.lineWidth = Math.max(3, fs * 0.08); g.beginPath(); g.arc(cx, cy, d / 2 - fs * 0.18, 0, Math.PI * 2); g.stroke();
      g.fillStyle = L.color || T.on; g.textAlign = "center";
      lines.forEach((t, i) => g.fillText(t, cx, cy - (lines.length * lh) / 2 + lh * (i + 0.78)));
      g.restore();
      return { x: cx - d / 2, y, w: d, h: d };
    }
    const maxW = (L.maxW || 0.8) * S;
    const ic = L.noIcon ? "" : L.icon;
    const iconD = ic ? fs * 1.45 : 0, gap = ic ? fs * 0.45 : 0;
    const lines = wrap(L.text, maxW - iconD - gap);
    const tw = Math.max(...lines.map((t) => g.measureText(t).width), 1);
    const padX = L.bg && L.bg !== "none" ? fs * 0.55 : 0, padY = L.bg && L.bg !== "none" ? fs * 0.32 : 0;
    const w = iconD + gap + tw + padX * 2, h = Math.max(lines.length * lh, iconD) + padY * 2;
    const left = L.align === "center" ? x - w / 2 : L.align === "right" ? x - w : x;
    g.save();
    if (L.bg === "solid" || L.bg === "pill") {
      g.fillStyle = L.bgColor || T.main; rr(g, left, y, w, h, L.bg === "pill" ? h / 2 : fs * 0.2); g.fill();
    } else if (L.bg === "soft") {
      g.fillStyle = "rgba(255,255,255,.88)"; g.shadowColor = "rgba(0,0,0,.12)"; g.shadowBlur = fs * 0.4; g.shadowOffsetY = fs * 0.08;
      rr(g, left, y, w, h, h / 2); g.fill(); g.shadowColor = "transparent";
    } else if (L.bg === "outline") {
      g.strokeStyle = L.bgColor || T.main; g.lineWidth = Math.max(3, fs * 0.09); rr(g, left, y, w, h, fs * 0.25); g.stroke();
    } else if (L.bg === "ribbon") {
      g.fillStyle = L.bgColor || T.main; g.beginPath(); g.moveTo(left, y); g.lineTo(left + w + fs * 0.5, y); g.lineTo(left + w, y + h / 2);
      g.lineTo(left + w + fs * 0.5, y + h); g.lineTo(left, y + h); g.closePath(); g.fill();
    }
    if (ic) {
      const cx = left + padX + iconD / 2, cy = y + h / 2;
      g.fillStyle = L.iconBg || T.main; g.beginPath(); g.arc(cx, cy, iconD / 2, 0, Math.PI * 2); g.fill();
      drawIcon(g, ic, cx, cy, iconD * 0.62, L.iconColor || T.on);
    }
    if (L.stroke) { g.lineWidth = fs * (L.strokeW || 0.14); g.strokeStyle = L.stroke; g.lineJoin = "round"; }
    const ty0 = y + padY + (h - padY * 2 - lines.length * lh) / 2;
    if (L.color2) {                           // 文字渐变（上 → 下）
      const gr = g.createLinearGradient(0, ty0, 0, ty0 + lines.length * lh); gr.addColorStop(0, L.color || T.ink); gr.addColorStop(1, L.color2); g.fillStyle = gr;
    } else g.fillStyle = L.color || T.ink;
    if (L.shadow) { g.shadowColor = "rgba(0,0,0,.35)"; g.shadowBlur = fs * 0.25; g.shadowOffsetY = fs * 0.06; }
    g.textAlign = "left";
    const tx = left + padX + iconD + gap;
    lines.forEach((t, i) => {
      const lx = L.align === "center" && !ic ? left + (w - g.measureText(t).width) / 2 : L.align === "right" && !ic ? left + w - padX - g.measureText(t).width : tx;
      const ly = ty0 + lh * (i + 0.8);
      if (L.stroke) g.strokeText(t, lx, ly);
      g.fillText(t, lx, ly);
    });
    g.restore();
    if (L.kind === "callout" && L.tx != null) {      // 引线：从文字框边上连到产品上的一个点
      const px = L.tx * S, py = L.ty * S;
      const ex = px < left ? left : px > left + w ? left + w : left + w / 2, ey = py < y ? y : py > y + h ? y + h : y + h / 2;
      g.save(); g.strokeStyle = L.lineColor || T.main; g.fillStyle = L.lineColor || T.main; g.lineWidth = Math.max(3, fs * 0.08);
      g.beginPath(); g.moveTo(ex, ey); g.lineTo(px, py); g.stroke();
      g.beginPath(); g.arc(px, py, fs * 0.22, 0, Math.PI * 2); g.fill();
      g.strokeStyle = "#fff"; g.lineWidth = Math.max(2, fs * 0.06); g.beginPath(); g.arc(px, py, fs * 0.22, 0, Math.PI * 2); g.stroke();
      g.restore();
      return { x: left, y, w, h, tx: px, ty: py };
    }
    return { x: left, y, w, h };
  }

  // ---------------- 模板（只摆位置，文字由人决定） ----------------
  function layer(kind, text, extra = {}) {
    const T = th();
    const base = { id: uid(), kind, text, x: 0.06, y: 0.06, size: 0.04, weight: 700, align: "left", bg: "none", icon: "", maxW: 0.6 };
    if (kind === "title") Object.assign(base, { size: 0.072, weight: 800, color: T.main, maxW: 0.7, stroke: "#ffffff" });
    if (kind === "sub") Object.assign(base, { size: 0.038, weight: 500, color: T.ink, maxW: 0.7 });
    if (kind === "point") Object.assign(base, { size: 0.036, weight: 600, color: T.ink, bg: "soft", icon: "check", maxW: 0.55 });
    if (kind === "badge") Object.assign(base, { size: 0.042, weight: 800, x: 0.86, y: 0.05, bgColor: T.main, color: T.on });
    if (kind === "tag") Object.assign(base, { size: 0.034, weight: 700, bg: "ribbon", color: T.on, bgColor: T.main, x: 0, y: 0.72 });
    if (kind === "callout") Object.assign(base, { size: 0.032, weight: 600, color: T.ink, bg: "soft", icon: "", maxW: 0.34, tx: 0.5, ty: 0.5 });
    if (kind === "shape") Object.assign(base, { x: 0, y: 0.8, w: 1, h: 0.2, color: T.main, opacity: 1, radius: 0 });
    return Object.assign(base, extra);
  }
  function applyTemplate(name) {
    const T = th();
    D.template = name;
    D.layers = D.layers.filter((l) => !l.auto);     // 模板自动加的色块先去掉
    D.img = { scale: 1, dx: 0, dy: 0, bg: "none" };
    D.layers.forEach((l) => { l.noIcon = (name === "minimal" || name === "callout") && (l.kind === "point" || l.kind === "callout"); });
    // 引线标注和普通卖点可以互相转换：换版式时文字不丢
    if (name === "callout") D.layers.forEach((l) => { if (l.kind === "point") l.kind = "callout"; });
    else D.layers.forEach((l) => { if (l.kind === "callout") l.kind = "point"; });
    const by = (k) => D.layers.filter((l) => l.kind === k);
    const pts = by("point");
    by("title").forEach((l) => Object.assign(l, { hidden: name === "clean" }));
    by("sub").forEach((l) => Object.assign(l, { hidden: name === "clean" }));
    pts.forEach((l) => (l.hidden = name === "clean"));
    by("badge").forEach((l, i) => Object.assign(l, { hidden: false, x: name === "clean" ? 0.13 : 0.86, y: 0.04 + i * 0.2, bgColor: T.main, color: T.on }));
    if (name === "side") {
      by("title").forEach((l) => Object.assign(l, { x: 0.06, y: 0.05, align: "left", color: T.main, stroke: "#ffffff", bg: "none" }));
      by("sub").forEach((l) => Object.assign(l, { x: 0.06, y: 0.15, align: "left", color: T.ink, bg: "none" }));
      pts.forEach((l, i) => Object.assign(l, { x: 0.05, y: 0.3 + i * 0.105, align: "left", bg: "soft", size: 0.034, maxW: 0.5, color: T.ink, iconBg: "", iconColor: "", hidden: false }));
    } else if (name === "bottom") {
      D.layers.unshift(layer("shape", "", { auto: true, x: 0, y: 0.78, w: 1, h: 0.22, color: T.main }));
      by("title").forEach((l) => Object.assign(l, { x: 0.5, y: 0.8, align: "center", color: T.on, stroke: "", bg: "none", maxW: 0.92, size: 0.062 }));
      by("sub").forEach((l) => Object.assign(l, { x: 0.5, y: 0.06, align: "center", color: T.ink, bg: "soft", maxW: 0.9 }));
      const n = Math.min(pts.length, 3);
      pts.forEach((l, i) => Object.assign(l, i < 3 ? { x: (i + 0.5) / n, y: 0.905, align: "center", bg: "none", size: 0.03, color: T.on, iconBg: T.accent, iconColor: T.ink, maxW: 0.32 } : { hidden: true }));
    } else if (name === "top") {
      D.layers.unshift(layer("shape", "", { auto: true, x: 0, y: 0, w: 1, h: 0.17, color: T.main }));
      by("title").forEach((l) => Object.assign(l, { x: 0.5, y: 0.025, align: "center", color: T.on, stroke: "", bg: "none", maxW: 0.92, size: 0.064 }));
      by("sub").forEach((l) => Object.assign(l, { x: 0.5, y: 0.11, align: "center", color: T.accent, bg: "none", maxW: 0.9, size: 0.032 }));
      const n = Math.min(pts.length, 3);
      pts.forEach((l, i) => Object.assign(l, i < 3 ? { x: (i + 0.5) / n, y: 0.86, align: "center", bg: "soft", size: 0.03, color: T.ink, iconBg: "", iconColor: "", maxW: 0.31 } : { hidden: true }));
      by("badge").forEach((l) => Object.assign(l, { y: 0.2 }));
    }
    else if (name === "callout") {
      D.img = { scale: 0.78, dx: 0, dy: 0.04, bg: "soft" };
      by("title").forEach((l) => Object.assign(l, { x: 0.5, y: 0.035, align: "center", color: T.main, stroke: "#ffffff", bg: "none", maxW: 0.9, size: 0.06 }));
      by("sub").forEach((l) => Object.assign(l, { x: 0.5, y: 0.12, align: "center", color: T.ink, bg: "none", maxW: 0.8, size: 0.032 }));
      const cs = by("callout");
      const spots = [[0.04, 0.24, 0.36, 0.36], [0.62, 0.3, 0.62, 0.42], [0.04, 0.62, 0.38, 0.62], [0.62, 0.7, 0.62, 0.66], [0.04, 0.84, 0.42, 0.8], [0.62, 0.86, 0.6, 0.8]];
      cs.forEach((l, i) => Object.assign(l, i < 6 ? { x: spots[i][0], y: spots[i][1], align: "left", bg: "soft", size: 0.03, maxW: 0.34, color: T.ink,
        tx: l.tx != null && l._placed ? l.tx : spots[i][2], ty: l.ty != null && l._placed ? l.ty : spots[i][3], hidden: false } : { hidden: true }));
    } else if (name === "cards") {
      D.img = { scale: 0.74, dx: 0, dy: -0.1, bg: "soft" };
      D.layers.unshift(layer("shape", "", { auto: true, x: 0.03, y: 0.66, w: 0.94, h: 0.31, color: "#ffffff", opacity: 0.92, radius: 0.03 }));
      by("title").forEach((l) => Object.assign(l, { x: 0.5, y: 0.035, align: "center", color: T.main, stroke: "#ffffff", bg: "none", maxW: 0.9, size: 0.06 }));
      by("sub").forEach((l) => Object.assign(l, { x: 0.5, y: 0.12, align: "center", color: T.ink, bg: "none", maxW: 0.8, size: 0.032 }));
      pts.forEach((l, i) => Object.assign(l, i < 4 ? { x: 0.07 + (i % 2) * 0.45, y: 0.69 + Math.floor(i / 2) * 0.135, align: "left", bg: "none", size: 0.03, maxW: 0.42, color: T.ink,
        iconBg: T.main, iconColor: T.on, hidden: false } : { hidden: true }));
    } else if (name === "split") {
      D.img = { scale: 0.72, dx: 0.17, dy: 0.04, bg: "theme" };
      D.layers.unshift(layer("shape", "", { auto: true, x: 0.035, y: 0.035, w: 0.4, h: 0.93, color: "#ffffff", opacity: 0.94, radius: 0.03 }));
      by("title").forEach((l) => Object.assign(l, { x: 0.065, y: 0.07, align: "left", color: T.main, stroke: "", bg: "none", maxW: 0.36, size: 0.058 }));
      by("sub").forEach((l) => Object.assign(l, { x: 0.065, y: 0.27, align: "left", color: T.ink, bg: "none", maxW: 0.36, size: 0.03 }));
      pts.forEach((l, i) => Object.assign(l, i < 5 ? { x: 0.06, y: 0.4 + i * 0.105, align: "left", bg: "none", size: 0.028, maxW: 0.37, color: T.ink, iconBg: T.main, iconColor: T.on, hidden: false } : { hidden: true }));
      by("badge").forEach((l, i) => Object.assign(l, { x: 0.88, y: 0.05 + i * 0.2 }));
    } else if (name === "frame") {
      D.img = { scale: 0.66, dx: 0, dy: -0.09, bg: "main", panel: [0.04, 0.04, 0.92, 0.74] };
      by("title").forEach((l) => Object.assign(l, { x: 0.5, y: 0.8, align: "center", color: T.on, stroke: "", bg: "none", maxW: 0.92, size: 0.062 }));
      by("sub").forEach((l) => Object.assign(l, { x: 0.5, y: 0.9, align: "center", color: T.accent, bg: "none", maxW: 0.9, size: 0.032 }));
      pts.forEach((l, i) => Object.assign(l, i < 3 ? { x: 0.07, y: 0.08 + i * 0.09, align: "left", bg: "pill", bgColor: T.main, size: 0.026, maxW: 0.5, color: T.on, iconBg: T.accent, iconColor: T.ink, hidden: false } : { hidden: true }));
    } else if (name === "gradient") {
      D.layers.unshift(layer("shape", "", { auto: true, x: 0, y: 0.6, w: 1, h: 0.4, color: T.ink, opacity: 0.0, grad: true }));
      by("title").forEach((l) => Object.assign(l, { x: 0.06, y: 0.68, align: "left", color: "#ffffff", stroke: "", bg: "none", maxW: 0.88, size: 0.066, shadow: true }));
      by("sub").forEach((l) => Object.assign(l, { x: 0.06, y: 0.79, align: "left", color: T.accent, bg: "none", maxW: 0.88, size: 0.034 }));
      const n = Math.min(pts.length, 3);
      pts.forEach((l, i) => Object.assign(l, i < 3 ? { x: 0.06 + i * (0.9 / n), y: 0.88, align: "left", bg: "none", size: 0.026, maxW: 0.9 / n - 0.02, color: "#ffffff", iconBg: T.accent, iconColor: T.ink, hidden: false } : { hidden: true }));
    } else if (name === "promo") {
      D.layers.unshift(layer("shape", "", { auto: true, x: 0, y: 0.84, w: 1, h: 0.16, color: T.main }));
      by("title").forEach((l) => Object.assign(l, { x: 0.5, y: 0.855, align: "center", color: T.on, stroke: "", bg: "none", maxW: 0.9, size: 0.06 }));
      by("sub").forEach((l) => Object.assign(l, { x: 0.06, y: 0.06, align: "left", color: T.ink, bg: "pill", bgColor: T.accent, maxW: 0.6, size: 0.034 }));
      pts.forEach((l, i) => Object.assign(l, i < 3 ? { x: 0.05, y: 0.62 - (2 - i) * 0.085, align: "left", bg: "soft", size: 0.028, maxW: 0.45, color: T.ink, iconBg: "", iconColor: "", hidden: false } : { hidden: true }));
      by("badge").forEach((l, i) => Object.assign(l, { x: 0.8, y: 0.08 + i * 0.24, size: 0.056, bgColor: T.main, color: T.on }));
      by("tag").forEach((l) => Object.assign(l, { y: 0.18 }));
    } else if (name === "minimal") {
      D.layers.unshift(layer("shape", "", { auto: true, x: 0.06, y: 0.135, w: 0.12, h: 0.006, color: T.main }));
      by("title").forEach((l) => Object.assign(l, { x: 0.06, y: 0.05, align: "left", color: T.ink, stroke: "", bg: "none", maxW: 0.8, size: 0.05, weight: 700 }));
      by("sub").forEach((l) => Object.assign(l, { x: 0.06, y: 0.155, align: "left", color: "#6b7280", bg: "none", maxW: 0.7, size: 0.028, weight: 400 }));
      pts.forEach((l, i) => Object.assign(l, i < 4 ? { x: 0.06, y: 0.8 + i * 0.045, align: "left", bg: "none", size: 0.024, maxW: 0.8, color: T.ink, weight: 500, hidden: false } : { hidden: true }));
    }
    by("tag").forEach((l) => Object.assign(l, { hidden: false, x: 0, y: name === "bottom" ? 0.66 : name === "promo" ? 0.18 : 0.72 }));
    if (name === "clean") toast("干净主图：只保留角标和标签，其他文字已隐藏（在右边列表里可以重新显示）", false, 5000);
  }
  function swapColors(old, T) {
    const swap = (c) => (c === old.main ? T.main : c === old.accent ? T.accent : c === old.ink ? T.ink : c);
    D.layers.forEach((l) => { ["color", "bgColor", "iconBg", "iconColor", "color2", "lineColor"].forEach((k) => { if (l[k]) l[k] = swap(l[k]); }); });
  }
  function applyTheme(key) {
    const old = th(); D.theme = key; swapColors(old, th());
  }

  // ---------------- 界面 ----------------
  function baseImages() { return (P.images || []).filter((im) => !im.ad); }
  function snapshot() { HIST.push(JSON.stringify(D)); if (HIST.length > 40) HIST.shift(); DIRTY = true; }
  function redraw() { draw(cv.getContext("2d"), { select: true, guides: true }); }
  async function loadBase(raw) {
    const im = (P.images || []).find((x) => x.raw === raw) || baseImages()[0];
    D.base = im ? im.raw : "";
    BASE = null;
    if (!im) return;
    await new Promise((ok) => { const i = new Image(); i.onload = () => { BASE = i; ok(); }; i.onerror = ok; i.src = imgSrc(im); });
  }

  async function open(opts = {}) {
    if (!P) return;
    if (dirty) await saveProduct(true);
    const ex = opts.design ? JSON.parse(JSON.stringify(opts.design)) : null;
    D = ex || { id: "", base: opts.base || (baseImages()[0] || {}).raw || "", template: pref("template") || "side",
                theme: pref("theme") || "orange", font: pref("font") || "Kanit", layers: [] };
    SEL = null; HIST = []; DIRTY = false; SUG = null;
    const el = MODAL.open(`<div id="ad-editor">
      <div class="row between"><h3>卖点图编辑器</h3><div class="row gap"><button class="mini" data-ad="undo">↶ 撤销</button><button class="mini" data-mclose>关闭</button></div></div>
      <p class="muted small">AI 只推荐文字，你勾选后才会放到图上；每一项都可以拖动位置、改文字、改大小和颜色。第 1 张主图建议保持干净（平台对主图文字有限制），卖点图放第 2 张以后。</p>
      <div class="ad-grid">
        <div class="ad-stage"><canvas id="ad-cv" width="${S}" height="${S}"></canvas>
          <div class="muted small">在图上按住拖动 · 方向键微调 · 虚线框是安全边距（文字别超出）</div></div>
        <div class="ad-side">
          <div class="ad-sec"><b>① 底图</b><div class="ad-bases">${baseImages().map((im) => `<img data-adbase="${esc(im.raw)}" src="${imgSrc(im)}" class="${im.raw === D.base ? "on" : ""}">`).join("") || '<span class="muted small">先上传商品图片</span>'}</div></div>
          <div class="ad-sec"><b>② 版式和风格</b>
            <div class="form2">
              <label>版式<select id="ad-tpl">${Object.entries(TEMPLATES).map(([k, v]) => `<option value="${k}" ${k === D.template ? "selected" : ""}>${v}</option>`).join("")}</select></label>
              <label>颜色<select id="ad-theme"><option value="auto" ${D.theme === "auto" ? "selected" : ""}>🎨 按产品颜色（自动配色）</option>${Object.entries(THEMES).map(([k, v]) => `<option value="${k}" ${k === D.theme ? "selected" : ""}>${v.name}</option>`).join("")}</select></label>
              <label>字体<select id="ad-font">${FONTS.map(([k, v]) => `<option value="${k}" ${k === D.font ? "selected" : ""}>${v}</option>`).join("")}</select></label>
            </div>
            <div id="ad-imgctl"></div></div>
          <div class="ad-sec"><b>③ 文字</b>
            <div class="row gap wrap"><button class="primary mini" data-ad="suggest">✨ AI 推荐卖点</button>
              ${Object.entries(KIND_ZH).map(([k, v]) => `<button class="mini" data-adadd="${k}">＋ ${v}</button>`).join("")}</div>
            <div id="ad-sug"></div>
            <div id="ad-layers"></div>
            <div id="ad-prop"></div></div>
          <div class="ad-sec"><label class="small"><input type="checkbox" id="ad-main"> 放到第 1 张（主图）</label>
            <div class="row gap wrap"><button class="primary" data-ad="save">💾 保存为商品图</button>
              <button data-ad="set" title="用 AI 推荐的卖点，按 4 种版式（卖点列表、引线标注、卖点卡片、左文右图）各出一张，分别用不同的底图">⚡ 一键出整套（4 张）</button></div></div>
        </div></div></div>`);
    el.classList.add("wide");
    cv = el.querySelector("#ad-cv");
    await loadBase(D.base);
    await fontsReady();
    renderLayers(); renderProp(); redraw();
    bindCanvas();
  }

  async function fontsReady() {
    if (!document.fonts || D.font === "system") return;
    try { await Promise.all([400, 500, 600, 700, 800].map((w) => document.fonts.load(`${w} 40px '${D.font}'`, "กขคสวัสดี"))); } catch { /* 用系统字体 */ }
  }

  function renderImgCtl() {
    const box = $("#ad-imgctl"); if (!box) return;
    const IM = D.img || {};
    box.innerHTML = `<div class="form2 small">
      <label>产品图大小<input type="range" min="40" max="150" data-adimg="scale" value="${Math.round((IM.scale || 1) * 100)}"></label>
      <label>背景（产品缩小后）<select data-adimg="bg">${[["none", "原图"], ["soft", "浅色渐变"], ["theme", "主题浅色"], ["#ffffff", "纯白"], ["#f3f4f6", "浅灰"]].map(([k, v]) => `<option value="${k}" ${k === (IM.bg || "none") ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <label>左右位置<input type="range" min="-40" max="40" data-adimg="dx" value="${Math.round((IM.dx || 0) * 100)}"></label>
      <label>上下位置<input type="range" min="-40" max="40" data-adimg="dy" value="${Math.round((IM.dy || 0) * 100)}"></label></div>`;
  }
  function renderLayers() {
    renderImgCtl();
    const box = $("#ad-layers"); if (!box) return;
    box.innerHTML = D.layers.length ? `<div class="small muted">图层（上面的盖住下面的；点一下选中）</div>` + [...D.layers].reverse().map((l) =>
      `<div class="ad-li ${l.id === SEL ? "on" : ""}" data-adsel="${l.id}"><span class="pill">${KIND_ZH[l.kind]}</span>
        <span class="ad-li-t" data-notr>${esc(l.kind === "shape" ? "（色块）" : (l.text || "（空）").slice(0, 26))}</span>
        <button class="mini" data-adhide="${l.id}" title="显示 / 隐藏">${l.hidden ? "🙈" : "👁"}</button></div>`).join("")
      : '<p class="small muted">还没有文字：点「AI 推荐卖点」挑选，或者点「＋ 大标题 / 卖点 …」自己写。</p>';
  }
  function renderProp() {
    const box = $("#ad-prop"); if (!box) return;
    const L = D.layers.find((l) => l.id === SEL);
    if (!L) { box.innerHTML = ""; return; }
    const T = th();
    const colorSel = (k, def) => `<input type="color" data-adp="${k}" value="${L[k] || def}">`;
    box.innerHTML = `<div class="ad-propbox"><div class="row between"><b>${KIND_ZH[L.kind]}</b>
        <div class="row gap"><button class="mini" data-ad="up" title="往上一层">▲</button><button class="mini" data-ad="down" title="往下一层">▼</button>
        <button class="mini" data-ad="dup">复制</button><button class="mini danger" data-ad="del">删除</button></div></div>
      ${L.kind === "shape" ? `<div class="form2">
          <label>宽 %<input type="range" min="5" max="100" data-adp="w" data-pct value="${Math.round((L.w || 1) * 100)}"></label>
          <label>高 %<input type="range" min="2" max="60" data-adp="h" data-pct value="${Math.round((L.h || 0.2) * 100)}"></label>
          <label>透明度<input type="range" min="10" max="100" data-adp="opacity" data-pct value="${Math.round((L.opacity ?? 1) * 100)}"></label>
          <label>圆角<input type="range" min="0" max="10" data-adp="radius" data-pct value="${Math.round((L.radius || 0) * 100)}"></label>
          <label>颜色 ${colorSel("color", T.main)}</label></div>` : `
        <label>文字（泰语；Enter 换行）<textarea data-adp="text" rows="2" data-notr>${esc(L.text || "")}</textarea></label>
        <div class="form2">
          <label>大小<input type="range" min="15" max="140" data-adp="size" data-k1000 value="${Math.round(L.size * 1000)}"></label>
          <label>粗细<select data-adp="weight">${[400, 500, 600, 700, 800].map((w) => `<option ${w === (L.weight || 700) ? "selected" : ""}>${w}</option>`).join("")}</select></label>
          ${L.kind !== "badge" ? `<label>对齐<select data-adp="align">${[["left", "左对齐"], ["center", "居中"], ["right", "右对齐"]].map(([k, v]) => `<option value="${k}" ${k === L.align ? "selected" : ""}>${v}</option>`).join("")}</select></label>
          <label>最大宽度 %<input type="range" min="15" max="95" data-adp="maxW" data-pct value="${Math.round((L.maxW || 0.6) * 100)}"></label>
          <label>底框<select data-adp="bg">${[["none", "不加底框"], ["soft", "白色圆角（推荐）"], ["pill", "胶囊色块"], ["solid", "方块色块"], ["outline", "描边框"], ["ribbon", "飘带"]].map(([k, v]) => `<option value="${k}" ${k === (L.bg || "none") ? "selected" : ""}>${v}</option>`).join("")}</select></label>
          <label>图标<select data-adp="icon">${Object.entries(ICON_ZH).map(([k, v]) => `<option value="${k}" ${k === (L.icon || "") ? "selected" : ""}>${v}</option>`).join("")}</select></label>` : ""}
          <label>文字颜色 ${colorSel("color", L.kind === "badge" ? T.on : T.ink)}</label>
          <label>底色 ${colorSel("bgColor", T.main)}</label>
          <label class="row small"><input type="checkbox" data-adp="stroke" ${L.stroke ? "checked" : ""}> 描边</label>
          ${L.stroke ? `<label>描边颜色 <input type="color" data-adp="strokeC" value="${L.stroke && L.stroke.startsWith("#") ? L.stroke : "#ffffff"}"></label>
            <label>描边粗细<input type="range" min="4" max="30" data-adp="strokeW" data-pct value="${Math.round((L.strokeW || 0.14) * 100)}"></label>` : ""}
          <label class="row small"><input type="checkbox" data-adp="shadow" ${L.shadow ? "checked" : ""}> 文字阴影</label>
          <label class="row small"><input type="checkbox" data-adp="grad" ${L.color2 ? "checked" : ""}> 渐变文字</label>
          ${L.color2 ? `<label>渐变到 <input type="color" data-adp="color2" value="${L.color2}"></label>` : ""}
          ${L.kind === "callout" ? `<label>引线颜色 ${colorSel("lineColor", T.main)}</label><div class="small muted">在图上拖动引线末端的圆点，指到产品的部位</div>` : ""}
        </div>`}</div>`;
  }

  function renderSug() {
    const box = $("#ad-sug"); if (!box) return;
    if (!SUG) { box.innerHTML = ""; return; }
    const row = (k, th, zh, extra = "") => `<label class="ad-sug-row"><input type="checkbox" data-sugk="${k}">
      <input data-sugt="${k}" value="${esc(th)}" data-notr>${extra}<span class="muted small" data-notr>${esc(zh || "")}</span></label>`;
    box.innerHTML = `<div class="ad-sugbox"><div class="small"><b>AI 推荐</b>（勾选要用的，可以先改文字，再点「放到图上」）</div>
      ${SUG.headline_th ? `<div class="small muted">大标题</div>${row("title", SUG.headline_th, SUG.headline_zh)}` : ""}
      ${SUG.sub_th ? `<div class="small muted">副标题</div>${row("sub", SUG.sub_th, SUG.sub_zh)}` : ""}
      ${SUG.badges.length ? `<div class="small muted">角标</div>${SUG.badges.map((b, i) => row("badge" + i, b, "")).join("")}` : ""}
      <div class="small muted">卖点</div>${SUG.points.map((p, i) => row("p" + i, p.th, p.zh,
        `<select data-sugi="p${i}" class="mini-sel">${Object.entries(ICON_ZH).filter(([k]) => k).map(([k, v]) => `<option value="${k}" ${k === p.icon ? "selected" : ""}>${v}</option>`).join("")}</select>`)).join("")}
      <div class="row gap"><button class="primary mini" data-ad="sug-add">放到图上</button><button class="mini" data-ad="sug-close">收起</button></div></div>`;
  }

  function addFromSug() {
    const box = $("#ad-sug");
    const picked = [...box.querySelectorAll("[data-sugk]:checked")].map((c) => c.dataset.sugk);
    if (!picked.length) { toast("先勾选要用的文字", true); return; }
    snapshot();
    for (const k of picked) {
      const text = box.querySelector(`[data-sugt="${k}"]`).value.trim();
      if (!text) continue;
      if (k === "title" || k === "sub") D.layers.push(layer(k, text));
      else if (k.startsWith("badge")) D.layers.push(layer("badge", text));
      else D.layers.push(layer("point", text, { icon: (box.querySelector(`[data-sugi="${k}"]`) || {}).value || "check" }));
    }
    applyTemplate(D.template);
    box.querySelectorAll("[data-sugk]:checked").forEach((c) => (c.checked = false));
    renderLayers(); redraw();
    toast(`已放上 ${picked.length} 项，可以拖动调整位置`);
  }

  // ---------------- 交互 ----------------
  function bindCanvas() {
    let drag = null;
    const pt = (e) => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * S / r.width, (e.clientY - r.top) * S / r.height]; };
    cv.addEventListener("pointerdown", (e) => {
      const [x, y] = pt(e);
      // 选中的引线标注：先看是不是按在引线末端的圆点上
      const cur = BOXES.find((b) => b.id === SEL && b.tx != null);
      if (cur && Math.hypot(x - cur.tx, y - cur.ty) < 30) {
        const L = D.layers.find((l) => l.id === SEL);
        snapshot(); drag = { L, target: true }; cv.setPointerCapture(e.pointerId); return;
      }
      const hit = [...BOXES].reverse().find((b) => x >= b.x - 8 && x <= b.x + b.w + 8 && y >= b.y - 8 && y <= b.y + b.h + 8);
      SEL = hit ? hit.id : null;
      renderLayers(); renderProp(); redraw();
      if (hit) {
        const L = D.layers.find((l) => l.id === hit.id);
        snapshot();
        drag = { L, x, y, lx: L.x, ly: L.y, box: { ...hit } };
        cv.setPointerCapture(e.pointerId);
      }
    });
    cv.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const [x, y] = pt(e);
      if (drag.target) { drag.L.tx = Math.min(1, Math.max(0, x / S)); drag.L.ty = Math.min(1, Math.max(0, y / S)); drag.L._placed = true; redraw(); return; }
      let dx = x - drag.x, dy = y - drag.y;
      // 对齐吸附：画面中线、安全边距、其他图层的边和中线
      const b = drag.box, TH = 12;
      const others = BOXES.filter((o) => o.id !== drag.L.id && !(o.w > S * 0.9 && o.h > S * 0.9));
      const xs = [S * 0.04, S * 0.5, S * 0.96, ...others.flatMap((o) => [o.x, o.x + o.w / 2, o.x + o.w])];
      const ys = [S * 0.04, S * 0.5, S * 0.96, ...others.flatMap((o) => [o.y, o.y + o.h / 2, o.y + o.h])];
      GUIDES = [];
      if (!e.altKey) {
        let best = null;
        for (const [off] of [[0], [b.w / 2], [b.w]]) for (const t of xs) { const d = t - (b.x + dx + off); if (Math.abs(d) < TH && (!best || Math.abs(d) < Math.abs(best[0]))) best = [d, t]; }
        if (best) { dx += best[0]; GUIDES.push(["x", best[1] / S]); }
        best = null;
        for (const [off] of [[0], [b.h / 2], [b.h]]) for (const t of ys) { const d = t - (b.y + dy + off); if (Math.abs(d) < TH && (!best || Math.abs(d) < Math.abs(best[0]))) best = [d, t]; }
        if (best) { dy += best[0]; GUIDES.push(["y", best[1] / S]); }
      }
      drag.L.x = Math.round((drag.lx + dx / S) * 1000) / 1000;
      drag.L.y = Math.round((drag.ly + dy / S) * 1000) / 1000;
      redraw();
    });
    cv.addEventListener("pointerup", () => { drag = null; if (GUIDES.length) { GUIDES = []; redraw(); } });
  }
  function onKey(e) {
    if (!$("#ad-editor") || !SEL || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    const L = D.layers.find((l) => l.id === SEL); if (!L) return;
    const st = e.shiftKey ? 0.02 : 0.004;
    const mv = { ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, -st], ArrowDown: [0, st] }[e.key];
    if (mv) { e.preventDefault(); snapshot(); L.x += mv[0]; L.y += mv[1]; redraw(); }
    if (e.key === "Delete") { snapshot(); D.layers = D.layers.filter((l) => l.id !== SEL); SEL = null; renderLayers(); renderProp(); redraw(); }
    if ((e.ctrlKey || e.metaKey) && e.key === "z") { e.preventDefault(); undo(); }
  }
  function undo() {
    const s = HIST.pop(); if (!s) { toast("没有可以撤销的了"); return; }
    D = JSON.parse(s); renderLayers(); renderProp(); redraw();
  }

  async function onClick(e) {
    if (!$("#ad-editor") || !e.target.closest("#ad-editor")) return;
    const t = e.target;
    if (t.dataset.adbase) { snapshot(); await loadBase(t.dataset.adbase); $$(".ad-bases img").forEach((i) => i.classList.toggle("on", i === t)); redraw(); return; }
    if (t.dataset.adadd) {
      snapshot();
      const k = t.dataset.adadd;
      const L = layer(k, k === "shape" ? "" : ({ title: "หัวข้อหลัก", sub: "ข้อความรอง", point: "จุดเด่นสินค้า", badge: "ขายดี", tag: "สั่งทำได้" })[k]);
      if (k !== "shape" && k !== "badge" && k !== "tag") { L.x = 0.08; L.y = 0.4; }
      D.layers.push(L); SEL = L.id; renderLayers(); renderProp(); redraw();
      const ta = $("#ad-prop textarea"); if (ta) { ta.focus(); ta.select(); }
      return;
    }
    const sel = t.closest("[data-adsel]");
    if (t.dataset.adhide) { snapshot(); const L = D.layers.find((l) => l.id === t.dataset.adhide); L.hidden = !L.hidden; renderLayers(); redraw(); return; }
    if (sel) { SEL = sel.dataset.adsel; renderLayers(); renderProp(); redraw(); return; }
    const a = t.dataset.ad;
    if (!a) return;
    const L = D.layers.find((l) => l.id === SEL);
    if (a === "undo") undo();
    if (a === "suggest") {
      await busy(t, async () => { SUG = await apiJob(`/api/products/${encodeURIComponent(P.id)}/ad/suggest`, { json: {} }); renderSug(); });
    }
    if (a === "sug-add") addFromSug();
    if (a === "sug-close") { SUG = null; renderSug(); }
    if (L && a === "del") { snapshot(); D.layers = D.layers.filter((l) => l !== L); SEL = null; renderLayers(); renderProp(); redraw(); }
    if (L && a === "dup") { snapshot(); const c = { ...L, id: uid(), y: L.y + 0.06, auto: false }; D.layers.push(c); SEL = c.id; renderLayers(); renderProp(); redraw(); }
    if (L && (a === "up" || a === "down")) {
      snapshot(); const i = D.layers.indexOf(L), j = a === "up" ? i + 1 : i - 1;
      if (j >= 0 && j < D.layers.length) { [D.layers[i], D.layers[j]] = [D.layers[j], D.layers[i]]; }
      renderLayers(); redraw();
    }
    if (a === "save") await save(t);
    if (a === "set") await busy(t, makeSet);
  }
  function onInput(e) {
    if (!$("#ad-editor") || !e.target.closest("#ad-editor")) return;
    const t = e.target;
    if (t.id === "ad-tpl") { snapshot(); applyTemplate(t.value); pref("template", t.value); renderLayers(); redraw(); return; }
    if (t.id === "ad-theme") {
      snapshot();
      if (t.value === "auto") { const pal = BASE && autoPalette(BASE); if (!pal) { toast("底图里找不到明显的产品颜色，换一张底图或选固定配色", true); t.value = D.theme; return; } const old = th(); D.palette = pal; D.theme = "auto"; swapColors(old, pal); }
      else applyTheme(t.value);
      pref("theme", t.value); renderProp(); redraw(); return;
    }
    if (t.dataset.adimg) {
      if (!t._snap) { snapshot(); t._snap = true; setTimeout(() => (t._snap = false), 800); }
      D.img = D.img || {};
      const k2 = t.dataset.adimg;
      D.img[k2] = k2 === "bg" ? t.value : +t.value / 100;
      redraw(); return;
    }
    if (t.id === "ad-font") { snapshot(); D.font = t.value; pref("font", t.value); fontsReady().then(redraw); return; }
    const k = t.dataset.adp; if (!k) return;
    const L = D.layers.find((l) => l.id === SEL); if (!L) return;
    if (!t._snap) { snapshot(); t._snap = true; setTimeout(() => (t._snap = false), 800); }
    let v = t.type === "checkbox" ? t.checked : t.value;
    if (t.dataset.pct !== undefined) v = +v / 100;
    if (t.dataset.k1000 !== undefined) v = +v / 1000;
    if (k === "weight") v = +v;
    if (k === "stroke") v = v ? "#ffffff" : "";
    if (k === "strokeC") { L.stroke = v; redraw(); return; }
    if (k === "grad") { L.color2 = v ? th().accent : ""; renderProp(); redraw(); return; }
    L[k] = v;
    redraw();
    if (k === "stroke" || k === "shadow") renderProp();
    if (k === "text") { const li = $(`[data-adsel="${L.id}"] .ad-li-t`); if (li) li.textContent = v.slice(0, 26) || "（空）"; }
  }

  // 一键出整套：同一组 AI 卖点，按 4 种版式各出一张（分别用不同的底图），全部存成商品图
  async function makeSet() {
    if (!SUG) { SUG = await apiJob(`/api/products/${encodeURIComponent(P.id)}/ad/suggest`, { json: {} }); renderSug(); }
    const bases = baseImages();
    if (!bases.length) throw new Error("先上传商品图片");
    const plans = ["side", "callout", "cards", "split"];
    if (!confirm(TR("ad.set_confirm", { plans: plans.map((k) => I18N.t(TEMPLATES[k].split("（")[0])).join("、") }))) return;
    const keepD = D, keepBase = BASE, keepSel = SEL;
    let n = 0;
    try {
      for (let i = 0; i < plans.length; i++) {
        D = { id: "", base: bases[i % bases.length].raw, template: plans[i], theme: keepD.theme, palette: keepD.palette, font: keepD.font, layers: [] };
        await loadBase(D.base);
        if (D.theme === "auto") D.palette = (BASE && autoPalette(BASE)) || keepD.palette;
        if (SUG.headline_th) D.layers.push(layer("title", SUG.headline_th));
        if (SUG.sub_th) D.layers.push(layer("sub", SUG.sub_th));
        (SUG.points || []).slice(0, plans[i] === "cards" ? 4 : 5).forEach((p2) => D.layers.push(layer("point", p2.th, { icon: p2.icon || "check" })));
        if ((SUG.badges || [])[0]) D.layers.push(layer("badge", SUG.badges[0]));
        applyTemplate(plans[i]);
        await fontsReady();
        const out = document.createElement("canvas"); out.width = S; out.height = S;
        draw(out.getContext("2d"), {});
        const r = await api(`/api/products/${encodeURIComponent(P.id)}/ad/save`, { json: { data: out.toDataURL("image/jpeg", 0.93), design: { ...D }, as_main: false } });
        P = r.product; n++;
      }
    } finally {
      D = keepD; BASE = keepBase; SEL = keepSel; ctx = cv.getContext("2d");
      renderLayers(); renderProp(); redraw();
      renderImages();
    }
    toast(TR("ad.set_done", { n }), false, 6000);
  }

  async function save(btn) {
    if (!D.layers.some((l) => !l.hidden && (l.text || l.kind === "shape"))) { toast("图上还没有文字", true); return; }
    const toMain = $("#ad-main") && $("#ad-main").checked;
    if (toMain) {
      const n = D.layers.filter((l) => !l.hidden && l.kind !== "badge" && l.kind !== "tag" && l.kind !== "shape").length;
      if (n > 1 && !confirm("主图上文字较多，平台可能会限流或要求修改（尤其 TikTok）。确定放到第 1 张？")) return;
    }
    await busy(btn, async () => {
      await fontsReady();
      const out = document.createElement("canvas"); out.width = S; out.height = S;
      draw(out.getContext("2d"), {});
      const data = out.toDataURL("image/jpeg", 0.93);
      const keep = { ...D, layers: D.layers };
      const r = await api(`/api/products/${encodeURIComponent(P.id)}/ad/save`, { json: { data, design: keep, as_main: toMain } });
      P = r.product; D.id = r.design_id; DIRTY = false;
      renderImages();
      toast("已保存为商品图（在「④ 图片」里，可以调整顺序）");
      ctx = cv.getContext("2d"); redraw();
    });
  }

  document.addEventListener("click", onClick);
  document.addEventListener("input", onInput);
  document.addEventListener("keydown", onKey);
  // 有没保存的修改时，点遮罩 / Esc 关闭前先确认
  const guard = (e) => {
    if (!$("#ad-editor") || !DIRTY) return;
    const closing = (e.type === "click" && (e.target.id === "modal" || e.target.closest("[data-mclose]"))) || (e.type === "keydown" && e.key === "Escape");
    if (closing && !confirm("卖点图还没保存，确定关闭？")) { e.stopImmediatePropagation(); e.preventDefault(); }
    else if (closing) DIRTY = false;
  };
  document.getElementById("modal").addEventListener("click", guard, true);
  document.addEventListener("keydown", guard, true);

  window.ADIMG = {
    open,
    edit(im) {
      const d = (P.ad_designs || {})[im.ad];
      if (!d) { toast("这张卖点图的设计稿找不到了，只能重新做", true); return open({}); }
      return open({ design: d });
    },
  };
})();
