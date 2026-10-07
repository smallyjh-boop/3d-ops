"use strict";
// 场景图：把产品（3D 模型透明渲染 或 白底图自动抠图）放到背景照片上；也可以交给 AI 生成场景。
// 依赖 app.js 的全局：P, VIEWER, api, toast, busy, colorList, colorInfo, swatch, colorLabel, postRenders, imgSrc, saveProduct, dirty
(function () {
  const S = 1200;
  const cv = document.getElementById("scene-canvas");
  const ctx = cv.getContext("2d");
  const st = {
    lib: [], presets: [], bgPresets: [], bgPick: new Set(), bg: null, bgImg: null, libLoaded: false,
    src: "", colors: [], sprites: [],      // sprites: [{canvas, color}]
    x: 0.5, y: 0.8, scale: 0.42, shadow: false, loadedFor: "", aiPick: new Set(["desk"]),
  };
  let opened = false;

  const loadImg = (url) => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });

  // 裁掉透明边
  function trim(canvas) {
    const c = canvas.getContext("2d"), w = canvas.width, h = canvas.height;
    const d = c.getImageData(0, 0, w, h).data;
    let x0 = w, y0 = h, x1 = -1, y1 = -1;
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      if (d[(y * w + x) * 4 + 3] > 8) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    }
    if (x1 < 0) return canvas;
    const out = document.createElement("canvas");
    out.width = x1 - x0 + 1; out.height = y1 - y0 + 1;
    out.getContext("2d").drawImage(canvas, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
    return out;
  }

  // 白底图抠图：从四边开始把接近白色的连通区域变透明，边缘羽化
  function cutoutWhite(img) {
    const w = img.naturalWidth, h = img.naturalHeight;
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    const g = c.getContext("2d"); g.drawImage(img, 0, 0);
    const id = g.getImageData(0, 0, w, h), d = id.data;
    const isBg = (i) => d[i] > 232 && d[i + 1] > 232 && d[i + 2] > 232;
    const seen = new Uint8Array(w * h), stack = [];
    for (let x = 0; x < w; x++) { stack.push(x, (h - 1) * w + x); }
    for (let y = 0; y < h; y++) { stack.push(y * w, y * w + w - 1); }
    while (stack.length) {
      const p = stack.pop();
      if (seen[p]) continue;
      seen[p] = 1;
      if (!isBg(p * 4)) continue;
      d[p * 4 + 3] = 0;
      const x = p % w, y = (p / w) | 0;
      if (x > 0) stack.push(p - 1); if (x < w - 1) stack.push(p + 1);
      if (y > 0) stack.push(p - w); if (y < h - 1) stack.push(p + w);
    }
    // 羽化：透明区旁边的浅色像素半透明
    for (let y = 1; y < h - 1; y++) for (let x = 1; x < w - 1; x++) {
      const p = y * w + x, i = p * 4;
      if (d[i + 3] === 0) continue;
      if (d[i - 1] === 0 || d[i + 7] === 0 || d[i - w * 4 + 3] === 0 || d[i + w * 4 + 3] === 0) {
        const lum = (d[i] + d[i + 1] + d[i + 2]) / 3;
        if (lum > 200) d[i + 3] = 140;
      }
    }
    g.putImageData(id, 0, 0);
    return trim(c);
  }

  function sources() {
    const out = [];
    if (P && P.model && VIEWER && VIEWER.model) out.push({ v: "3d", t: "3D 模型（当前角度，可选颜色）" });
    (P && P.images || []).forEach((im, i) => { if (!im.scene) out.push({ v: "img:" + im.raw, t: `图 ${i + 1}${im.render ? "（渲染图）" : ""}` }); });
    return out;
  }

  async function buildSprites() {
    st.sprites = [];
    if (!st.src) return;
    if (st.src === "3d") {
      if (!VIEWER || !VIEWER.model) return;
      const list = $("#scene-multi").checked ? colorList() : [st.colors[0] || colorList()[0] || ""];
      for (const c of (list.length ? list : [""])) {
        const ci = colorInfo(c);
        VIEWER.setColor(ci.hex, ci.code);
        const url = VIEWER.shot({ size: 1400, transparent: true });
        const im = await loadImg(url);
        const cvs = document.createElement("canvas"); cvs.width = im.width; cvs.height = im.height;
        cvs.getContext("2d").drawImage(im, 0, 0);
        st.sprites.push({ canvas: trim(cvs), color: c, ownShadow: true });
      }
      const c0 = colorInfo(st.colors[0] || colorList()[0] || ""); VIEWER.setColor(c0.hex, c0.code);
    } else {
      const raw = st.src.slice(4);
      const im = (P.images || []).find((i) => i.raw === raw);
      if (!im) return;
      const img = await loadImg(imgSrc(im));
      st.sprites.push({ canvas: cutoutWhite(img), color: im.color || "", ownShadow: false });
    }
  }

  function layout() {
    // 每个产品：高度 = scale × 画面；多个并排时缩小一些
    const n = st.sprites.length || 1;
    const k = n === 1 ? 1 : n === 2 ? 0.8 : n <= 4 ? 0.62 : 0.5;
    const items = st.sprites.map((sp) => {
      const ar = sp.canvas.width / sp.canvas.height;
      let h = st.scale * S * k, w = h * ar;
      if (w > S * 0.9 / n * 1.15) { w = S * 0.9 / n * 1.15; h = w / ar; }
      return { sp, w, h };
    });
    const gap = S * 0.02, total = items.reduce((a, b) => a + b.w, 0) + gap * (n - 1);
    let x = st.x * S - total / 2;
    return items.map((it) => { const r = { ...it, x, y: st.y * S - it.h }; x += it.w + gap; return r; });
  }

  function draw() {
    ctx.clearRect(0, 0, S, S);
    if (st.bgImg) ctx.drawImage(st.bgImg, 0, 0, S, S);
    else { ctx.fillStyle = "#f3f4f6"; ctx.fillRect(0, 0, S, S); }
    const items = layout();
    for (const it of items) {
      if (st.shadow && !it.sp.ownShadow) {   // 白底图：画一个柔和的接地阴影
        ctx.save();
        const cx = it.x + it.w / 2, cy = it.y + it.h, rx = it.w * 0.45, ry = Math.max(8, it.w * 0.06);
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, rx);
        g.addColorStop(0, "rgba(0,0,0,0.32)"); g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.translate(cx, cy); ctx.scale(1, ry / rx); ctx.translate(-cx, -cy);
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, rx, 0, Math.PI * 2); ctx.fill();
        ctx.restore();
      }
      ctx.drawImage(it.sp.canvas, it.x, it.y, it.w, it.h);
    }
    if (!st.sprites.length) {
      ctx.fillStyle = "rgba(0,0,0,.45)"; ctx.font = "40px sans-serif"; ctx.textAlign = "center";
      ctx.fillText(window.I18N && I18N.lang === "th" ? "เลือกแหล่งรูปสินค้า" : "请选择产品来源", S / 2, S / 2);
    }
  }

  function renderBgPresets() {
    $("#bg-presets").innerHTML = st.bgPresets.map((p) => `<span class="chip ${st.bgPick.has(p.key) ? "on" : ""}" data-bgp="${p.key}">${esc(p.name)}</span>`).join("");
  }

  function renderBgs() {
    if (!st.lib.length) {
      $("#scene-bgs").innerHTML = '<div class="muted small" style="grid-column:1/-1">背景库还是空的：上传自己拍的背景照片，或在下面用 AI 生成电商常用背景。</div>';
      return;
    }
    $("#scene-bgs").innerHTML = st.lib.map((b) => `<div class="scene-bg ${st.bg && st.bg.id === b.id ? "on" : ""}" data-bg="${esc(b.id)}" title="${esc(b.name)}">
      <img src="${esc(b.url)}" loading="lazy" alt="">${b.builtin ? "" : `<button class="x" data-delbg="${esc(b.id)}">✕</button>`}<span ${b.builtin || b.ai ? "" : "data-notr"}>${esc(b.name)}</span></div>`).join("");
  }

  function renderColors() {
    const cols = colorList();
    const show = st.src === "3d";
    $("#scene-color-row").classList.toggle("hidden", !show || !cols.length);
    if (!st.colors.length || !cols.includes(st.colors[0])) st.colors = [cols[0] || ""];
    $("#scene-colors").innerHTML = cols.map((c) => `<span class="chip ${c === st.colors[0] ? "on" : ""}" data-sc="${esc(c)}" data-notr>${swatch(c)}${esc(colorLabel(c))}</span>`).join("");
  }

  function renderAiChips() {
    $("#ai-scenes").innerHTML = st.presets.map((p) => `<span class="chip ${st.aiPick.has(p.key) ? "on" : ""}" data-ai="${p.key}">${esc(p.name)}</span>`).join("");
  }

  async function refreshSprites() { await buildSprites(); draw(); }

  async function setBg(b) {
    st.bg = b;
    st.bgImg = b ? await loadImg(b.url) : null;
    if (b) { st.y = b.floor_y || 0.8; st.scale = b.scale || 0.42; st.x = 0.5; $("#scene-scale").value = Math.round(st.scale * 100); }
    renderBgs(); draw();
  }

  async function open() {
    if (!P) return;
    if (!st.libLoaded) {
      const r = await api("/api/scenes");
      st.lib = r.library; st.presets = r.presets; st.bgPresets = r.bg_presets || []; st.libLoaded = true;
      renderAiChips(); renderBgPresets();
      await setBg(st.lib[0] || null);
    }
    refreshSourceList();
    if (st.loadedFor !== P.id + "/" + st.src) { st.loadedFor = P.id + "/" + st.src; await refreshSprites(); }
  }

  function refreshSourceList() {
    const srcs = sources();
    const sel = $("#scene-src");
    const keep = srcs.some((s) => s.v === st.src) ? st.src : (srcs[0] ? srcs[0].v : "");
    sel.innerHTML = srcs.length ? srcs.map((s) => `<option value="${esc(s.v)}" ${s.v === keep ? "selected" : ""}>${esc(s.t)}</option>`).join("")
      : '<option value="">（先上传 3D 模型或产品图片）</option>';
    st.src = keep;
    renderColors();
  }

  window.sceneRefresh = async () => {
    if (!opened || !P) return;
    refreshSourceList();
    const key = P.id + "/" + st.src;
    if (st.loadedFor !== key) { st.loadedFor = key; await refreshSprites(); }
  };

  $("#scene-details").addEventListener("toggle", async (e) => {
    opened = e.target.open;
    if (opened) { try { await open(); } catch (err) { toast(err.message, true); } }
  });
  $("#scene-src").addEventListener("change", async (e) => { st.src = e.target.value; renderColors(); await refreshSprites(); });
  $("#scene-colors").addEventListener("click", async (e) => {
    const c = e.target.closest("[data-sc]"); if (!c) return;
    st.colors = [c.dataset.sc]; renderColors(); await refreshSprites();
  });
  $("#scene-multi").addEventListener("change", refreshSprites);
  $("#scene-scale").addEventListener("input", (e) => { st.scale = e.target.value / 100; draw(); });
  $("#btn-scene-center").addEventListener("click", () => { st.x = 0.5; st.y = (st.bg && st.bg.floor_y) || 0.8; draw(); });
  $("#scene-bgs").addEventListener("click", async (e) => {
    const del = e.target.dataset.delbg;
    if (del) {
      e.stopPropagation();
      if (!confirm("删除这张背景？（所有产品都不能再用它）")) return;
      const r = await api(`/api/scenes/${encodeURIComponent(del)}`, { method: "DELETE" });
      st.lib = r.library; if (st.bg && st.bg.id === del) await setBg(st.lib[0] || null); else renderBgs();
      return;
    }
    const b = e.target.closest("[data-bg]"); if (!b) return;
    await setBg(st.lib.find((x) => x.id === b.dataset.bg));
  });
  $("#scene-upload").addEventListener("change", async (e) => {
    const fd = new FormData(); [...e.target.files].forEach((f) => fd.append("files", f));
    try {
      const r = await api("/api/scenes", { method: "POST", body: fd });
      st.lib = r.library; await setBg(st.lib.find((x) => x.id === r.added[r.added.length - 1]));
      toast("背景已上传，所有产品都可以用");
    } catch (err) { toast(err.message, true); }
    e.target.value = "";
  });
  $("#btn-scene-floor").addEventListener("click", async () => {
    if (!st.bg) return;
    if (st.bg.builtin) return toast("内置背景不能修改，只能修改自己上传的背景", true);
    const r = await api(`/api/scenes/${encodeURIComponent(st.bg.id)}`, { json: { floor_y: +st.y.toFixed(3), scale: +st.scale.toFixed(3) } });
    st.lib = r.library; st.bg = st.lib.find((x) => x.id === st.bg.id); toast("已记住：以后用这张背景时产品默认放在这里");
  });

  // 拖动 / 滚轮缩放
  let drag = null;
  const pt = (e) => { const r = cv.getBoundingClientRect(); return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height]; };
  cv.addEventListener("pointerdown", (e) => { const [x, y] = pt(e); drag = { x, y, sx: st.x, sy: st.y }; cv.setPointerCapture(e.pointerId); cv.style.cursor = "grabbing"; });
  cv.addEventListener("pointermove", (e) => {
    if (!drag) return; const [x, y] = pt(e);
    st.x = Math.min(0.95, Math.max(0.05, drag.sx + x - drag.x)); st.y = Math.min(1, Math.max(0.1, drag.sy + y - drag.y)); draw();
  });
  cv.addEventListener("pointerup", () => { drag = null; cv.style.cursor = "grab"; });
  cv.addEventListener("wheel", (e) => {
    e.preventDefault();
    st.scale = Math.min(0.95, Math.max(0.08, st.scale * (e.deltaY < 0 ? 1.06 : 0.94)));
    $("#scene-scale").value = Math.round(st.scale * 100); draw();
  }, { passive: false });

  $("#btn-scene-add").addEventListener("click", async (e) => {
    if (!st.sprites.length) return toast("请先选择产品来源", true);
    if (dirty) await saveProduct(true);
    await busy(e.target, async () => {
      draw();
      const color = st.sprites.length === 1 ? st.sprites[0].color : "";
      const n = await postRenders([{ data: cv.toDataURL("image/jpeg", 0.92), kind: "scene", color }], { replace_renders: false });
      toast(`已添加 ${n} 张场景图（在图片列表里，可调整顺序）。记得点「上传图床」。`);
    });
  });

  $("#bg-presets").addEventListener("click", (e) => {
    const c = e.target.closest("[data-bgp]"); if (!c) return;
    const k = c.dataset.bgp; st.bgPick.has(k) ? st.bgPick.delete(k) : st.bgPick.add(k); renderBgPresets();
  });
  $("#btn-bg-ai").addEventListener("click", async (e) => {
    const picks = [...st.bgPick];
    if (!picks.length) return toast("请先点选要生成的背景（可多选）", true);
    await busy(e.target, async () => {
      let ok = 0;
      for (let i = 0; i < picks.length; i++) {
        $("#bg-ai-prog").textContent = `AI 正在生成背景 ${i + 1}/${picks.length}（每张约 20-60 秒）…`;
        try {
          const r = await apiJob("/api/scenes/ai", { json: { preset: picks[i] } });
          st.lib = r.library; ok++;
          await setBg(st.lib.find((x) => x.id === r.added));
        } catch (err) { toast(err.message, true); break; }
      }
      st.bgPick.clear(); renderBgPresets();
      $("#bg-ai-prog").textContent = ok ? `已生成 ${ok} 张背景，已加入背景库，所有产品都能用。不满意的点背景右上角 ✕ 删除。` : "";
    });
  });
  $("#ai-scenes").addEventListener("click", (e) => {
    const c = e.target.closest("[data-ai]"); if (!c) return;
    const k = c.dataset.ai; st.aiPick.has(k) ? st.aiPick.delete(k) : st.aiPick.add(k); renderAiChips();
  });
  $("#btn-scene-ai").addEventListener("click", async (e) => {
    if (!st.sprites.length) return toast("请先选择产品来源", true);
    const picks = [...st.aiPick];
    const extra = $("#ai-scene-extra").value.trim();
    if (!picks.length && !extra) return toast("请至少选一个场景，或在补充要求里写场景", true);
    if (dirty) await saveProduct(true);
    // 交给 AI 的产品图：透明背景，只放一个产品（多颜色时用第一个）
    const sp = st.sprites[0].canvas;
    const pad = document.createElement("canvas"); const m = Math.max(sp.width, sp.height) * 1.25;
    pad.width = pad.height = Math.round(m);
    pad.getContext("2d").drawImage(sp, (m - sp.width) / 2, (m - sp.height) / 2);
    const data = pad.toDataURL("image/png");
    await busy(e.target, async () => {
      const list = picks.length ? picks : [extra];
      let ok = 0;
      for (let i = 0; i < list.length; i++) {
        $("#scene-ai-prog").textContent = `AI 正在生成 ${i + 1}/${list.length}（每张约 20-60 秒）…`;
        try {
          const r = await apiJob(`/api/products/${P.id}/scene-ai`, { json: { image: data, scene: list[i], extra: picks.length ? extra : "", color: st.sprites[0].color } });
          P = r.product; ok += r.added; renderImages();
        } catch (err) { toast(err.message, true); break; }
      }
      $("#scene-ai-prog").textContent = ok ? `已生成 ${ok} 张场景图，请检查产品外观是否和实物一致，不一致的请删除。` : "";
    });
  });
})();
