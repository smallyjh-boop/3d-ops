// 切片预览（3D 挤出路径：外墙/填充/支撑…，可按层查看）+ 打印方案实时预览（摆放方向、悬空、支撑示意、一盘排版）
import * as THREE from "three";
import { OrbitControls } from "/static/vendor/three/OrbitControls.js";

const tr = (s) => (window.I18N && I18N.t ? I18N.t(s) : s);
const e = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- 通用 3D 场景（Z 朝上的打印坐标 → three.js 的 Y 朝上） ----------
class Stage {
  constructor(box, { height } = {}) {
    this.box = box;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    box.appendChild(this.renderer.domElement);
    this.renderer.domElement.style.display = "block";
    this.renderer.domElement.style.touchAction = "none";
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xf4f6f9);
    this.camera = new THREE.PerspectiveCamera(35, 1, 0.5, 5000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.addEventListener("change", () => this.render());
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a94a6, 1.6));
    const d = new THREE.DirectionalLight(0xffffff, 1.4);
    d.position.set(-200, 400, 300);
    this.scene.add(d);
    this.world = new THREE.Group();            // 打印坐标系：x 右、y 后、z 上
    this.world.rotation.x = -Math.PI / 2;
    this.scene.add(this.world);
    this.fixedH = height;
    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(box);
    this.resize();
    const loop = () => {
      if (this.dead) return;
      if (!this.box.isConnected) { this.dispose(); return; }   // 面板已经关掉
      
      if (this.controls.update()) this.render();
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }
  resize() {
    const w = this.box.clientWidth || 300;
    const h = this.fixedH || this.box.clientHeight || 300;
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = w + "px";
    this.renderer.domElement.style.height = h + "px";
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.render();
  }
  render() { if (!this.dead) this.renderer.render(this.scene, this.camera); }
  setBed(w, d) {
    if (this.bed) { this.world.remove(this.bed); }
    const g = new THREE.Group();
    const plate = new THREE.Mesh(new THREE.PlaneGeometry(w, d), new THREE.MeshBasicMaterial({ color: 0xdfe4ea }));
    plate.position.set(w / 2, d / 2, -0.05);
    g.add(plate);
    const pts = [];
    for (let x = 0; x <= w + 0.01; x += 10) pts.push(x, 0, 0, x, d, 0);
    for (let y = 0; y <= d + 0.01; y += 10) pts.push(0, y, 0, w, y, 0);
    const lg = new THREE.BufferGeometry();
    lg.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
    g.add(new THREE.LineSegments(lg, new THREE.LineBasicMaterial({ color: 0xc3cad4 })));
    const ob = new THREE.BufferGeometry();
    ob.setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, w, 0, 0, w, d, 0, 0, d, 0, 0, 0, 0], 3));
    g.add(new THREE.Line(ob, new THREE.LineBasicMaterial({ color: 0x64748b })));
    // 前方标记（打印机正面）
    const fm = new THREE.Mesh(new THREE.PlaneGeometry(Math.min(40, w / 4), 3), new THREE.MeshBasicMaterial({ color: 0x64748b }));
    fm.position.set(w / 2, -4, 0);
    g.add(fm);
    this.bed = g;
    this.bedSize = [w, d];
    this.world.add(g);
  }
  fit(min, max, keepAngle) {
    const c = new THREE.Vector3((min[0] + max[0]) / 2, (min[2] + max[2]) / 2, -(min[1] + max[1]) / 2);
    const size = Math.max(max[0] - min[0], max[1] - min[1], (max[2] - min[2]) * 1.4, 20);
    const dist = size / (2 * Math.tan((this.camera.fov * Math.PI) / 360)) * 1.25;
    const dir = keepAngle ? this.camera.position.clone().sub(this.controls.target).normalize() : new THREE.Vector3(0.55, 0.62, 0.95).normalize();
    this.controls.target.copy(c);
    this.camera.position.copy(c.clone().add(dir.multiplyScalar(dist)));
    this.camera.near = dist / 100; this.camera.far = dist * 20;
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.render();
  }
  view(name) {
    const t = this.controls.target.clone();
    const dist = this.camera.position.distanceTo(t);
    const dirs = { iso: [0.55, 0.62, 0.95], top: [0, 1, 0.0001], front: [0, 0.15, 1], left: [-1, 0.15, 0], right: [1, 0.15, 0], bottom: [0, -1, 0.0001] };
    const d = new THREE.Vector3(...(dirs[name] || dirs.iso)).normalize().multiplyScalar(dist);
    this.camera.position.copy(t.add(d));
    this.controls.update();
    this.render();
  }
  dispose() {
    if (this.dead) return;
    this.dead = true;
    this._ro.disconnect();
    this.scene.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}

// ---------- 切片预览 ----------
function decodeToolpath(buf) {
  const dv = new DataView(buf);
  const hl = dv.getUint32(0, true);
  const head = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, hl)));
  const data = new Int16Array(buf, 4 + hl, (buf.byteLength - 4 - hl) >> 1);
  let off = 0;
  head.chunks = head.chunks.map(([layer, type, n]) => { const c = { layer, type, start: off, n }; off += n; return c; });
  return { head, data };
}

class ToolpathView {
  constructor(box) {
    this.stage = new Stage(box);
    this.visible = null;
  }
  load(tp, bed) {
    this.tp = tp;
    const { head } = tp;
    const used = new Set(head.chunks.map((c) => c.type));
    if (!this.visible) this.visible = new Set([...used]);
    this.layers = head.layers.length;
    // 统计每种类型的路径长度（大概占比）
    this.stats = {};
    const S = head.scale;
    for (const c of head.chunks) {
      let len = 0, px = null, py = null;
      for (let i = c.start; i < c.start + c.n; i += 2) {
        const x = tp.data[i], y = tp.data[i + 1];
        if (x === -32768) { px = null; continue; }
        if (px !== null) len += Math.hypot(x - px, y - py) * S;
        px = x; py = y;
      }
      this.stats[c.type] = (this.stats[c.type] || 0) + len;
    }
    const w = (bed && bed[0]) || 256, d = (bed && bed[1]) || 256;
    this.stage.setBed(w, d);
    this.build();
    // 视角对准零件
    const b = this.bbox;
    this.stage.fit([b[0], b[1], 0], [b[2], b[3], head.layers[head.layers.length - 1] || 10]);
  }
  build() {
    const { head, data } = this.tp;
    const S = head.scale;
    if (this.obj) { this.stage.world.remove(this.obj); this.obj.geometry.dispose(); this.obj.material.dispose(); }
    let segs = 0;
    for (const c of head.chunks) {
      if (!this.visible.has(c.type)) continue;
      let k = 0;
      for (let i = c.start; i < c.start + c.n; i += 2) { if (data[i] === -32768) { if (k > 1) segs += k - 1; k = 0; } else k++; }
    }
    const pos = new Int16Array(segs * 6);
    const col = new Uint8Array(segs * 6);
    const ends = new Uint32Array(this.layers);
    const zq = head.layers.map((z) => Math.round(z / S));
    const rgb = head.types.map((t) => { const c = new THREE.Color(t.color); return [c.r * 255, c.g * 255, c.b * 255]; });
    let v = 0, curLayer = 0;
    let minx = 1e9, miny = 1e9, maxx = -1e9, maxy = -1e9;
    for (const c of head.chunks) {
      while (curLayer < c.layer) { ends[curLayer++] = v; }
      if (!this.visible.has(c.type)) continue;
      const z = zq[c.layer];
      const [r, g, b] = rgb[c.type];
      let px = null, py = null;
      for (let i = c.start; i < c.start + c.n; i += 2) {
        const x = data[i], y = data[i + 1];
        if (x === -32768) { px = null; continue; }
        if (px !== null) {
          const o = v * 3;
          pos[o] = px; pos[o + 1] = py; pos[o + 2] = z; pos[o + 3] = x; pos[o + 4] = y; pos[o + 5] = z;
          col[o] = r; col[o + 1] = g; col[o + 2] = b; col[o + 3] = r; col[o + 4] = g; col[o + 5] = b;
          v += 2;
          if (c.type !== 11) { if (x < minx) minx = x; if (x > maxx) maxx = x; if (y < miny) miny = y; if (y > maxy) maxy = y; }
        }
        px = x; py = y;
      }
    }
    while (curLayer < this.layers) ends[curLayer++] = v;
    this.ends = ends;
    if (minx > maxx) { minx = 0; miny = 0; maxx = 100 / S; maxy = 100 / S; }
    this.bbox = [minx * S, miny * S, maxx * S, maxy * S];
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.BufferAttribute(col, 3, true));
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, 0, 0), 1e6);
    this.obj = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true }));
    this.obj.scale.set(S, S, S);
    this.obj.frustumCulled = false;
    this.stage.world.add(this.obj);
    this.setLayer(this.layer || this.layers, this.single);
  }
  setLayer(n, single) {
    this.layer = Math.max(1, Math.min(this.layers, n));
    this.single = !!single;
    const end = this.ends[this.layer - 1] || 0;
    const start = this.single && this.layer > 1 ? this.ends[this.layer - 2] : 0;
    this.obj.geometry.setDrawRange(start, end - start);
    this.stage.render();
  }
  toggle(type, on) { if (on) this.visible.add(type); else this.visible.delete(type); this.build(); }
  dispose() { this.stage.dispose(); }
}

function paramRows(p, recipe) {
  if (!p || !Object.keys(p).length) return `<p class="bad small">${tr("读不到这个文件的切片参数，请在切片软件里核对")}</p>`;
  const yes = (b) => (b == null ? "-" : b ? tr("开启") : tr("关闭"));
  const rows = [
    ["喷嘴温度", p.nozzle_temp != null ? `${p.nozzle_temp}°C${p.nozzle_temp_first && p.nozzle_temp_first !== p.nozzle_temp ? ` (${tr("首层")} ${p.nozzle_temp_first}°C)` : ""}` : "-", recipe && recipe.nozzle_temp],
    ["热床温度", p.bed_temp != null ? `${p.bed_temp}°C` : "-", recipe && recipe.bed_temp],
    ["热床板", p.bed_type_zh ? tr(p.bed_type_zh) : "-"],
    ["层高", p.layer_height != null ? `${p.layer_height} mm${p.first_layer ? ` (${tr("首层")} ${p.first_layer})` : ""}` : "-"],
    ["壁数", p.walls ?? "-"],
    ["顶 / 底层数", `${p.top_layers ?? "-"} / ${p.bottom_layers ?? "-"}`],
    ["填充", p.infill_pct != null ? `${p.infill_pct}% ${p.infill_pattern || ""}` : "-"],
    ["支撑", p.supports == null ? "-" : p.supports ? `${p.support_type || tr("开启")}${p.support_angle != null ? ` · ${tr("角度")} ${p.support_angle}°` : ""}${p.support_plate_only ? ` · ${tr("只从热床长")}` : ""}` : tr("不要支撑")],
    ["帽檐", p.brim == null ? "-" : p.brim ? `${tr("开启")}${p.brim_width ? " " + p.brim_width + "mm" : ""}` : tr("关闭")],
    ["外墙速度", p.outer_wall_speed != null ? `${p.outer_wall_speed} mm/s` : "-"],
    ["喷嘴直径", p.nozzle_mm != null ? `${p.nozzle_mm} mm` : "-"],
    ["换料塔", yes(p.prime_tower)],
    ["打印机配置", p.printer_profile || "-", null, true],
    ["工艺配置", p.process_profile || "-", null, true],
  ];
  return `<table class="gv-params">${rows.map(([k, v, , raw]) => `<tr><th>${e(tr(k))}</th><td ${raw ? "data-notr" : ""}>${e(v)}</td></tr>`).join("")}</table>`;
}

function matBanner(p, need) {
  const m = (p && p.material) || "?";
  const bad = need && p && p.material && window.GVIEW.sameMat(p.material, need) === "diff";
  return `<div class="gv-mat ${bad ? "bad" : ""}">
    ${p && p.color_hex ? `<span class="sw" style="background:${e(p.color_hex)}"></span>` : ""}
    <div><div class="gv-mat-big" data-notr>${e(m)}</div><div class="small" data-notr>${e((p && p.filament) || "")}</div>
    ${bad ? `<div class="bad small"><b>${e(tr("材料不对！"))}</b> ${e(tr("产品要用"))} ${e(need)}</div>` : ""}</div>
    <div class="gv-temps"><span>🔥 ${p && p.nozzle_temp != null ? p.nozzle_temp + "°C" : "-"}</span><span>▭ ${p && p.bed_temp != null ? p.bed_temp + "°C" : "-"}</span></div></div>`;
}

let OPEN = null;
async function openFile(fid, opt = {}) {
  closeView();
  const ov = document.createElement("div");
  ov.className = "gv";
  ov.innerHTML = `<div class="gv-in">
    <div class="gv-head"><b>${e(tr("切片预览"))}</b><span class="gv-hmat"></span><span class="small muted gv-title" data-notr></span><span style="flex:1"></span>
      <button class="mini" data-gv="close">${e(tr("关闭"))}</button></div>
    <div class="gv-body">
      <div class="gv-3dwrap"><div class="gv-3d"></div>
        <div class="gv-views">${[["iso", "斜视"], ["top", "俯视"], ["front", "正面"], ["left", "左侧"], ["bottom", "底部"]].map(([k, l]) => `<button class="mini" data-view="${k}">${e(tr(l))}</button>`).join("")}</div>
        <div class="gv-loading">${e(tr("正在读取切片文件…"))}</div>
        <div class="gv-layer"><input type="range" min="1" max="1" value="1" class="gv-range">
          <div class="row gap small"><span class="gv-lnum"></span><label class="row"><input type="checkbox" class="gv-single"> ${e(tr("只看这一层"))}</label>
          <button class="mini" data-step="-1">◀</button><button class="mini" data-step="1">▶</button></div></div></div>
      <aside class="gv-side"><div class="gv-matbox"></div><div class="gv-legend"></div><div class="gv-sum small"></div>
        <h4>${e(tr("切片参数"))}</h4><div class="gv-par"></div><div class="gv-checks"></div></aside>
    </div></div>`;
  document.body.appendChild(ov);
  const view = new ToolpathView(ov.querySelector(".gv-3d"));
  OPEN = { ov, view };
  const range = ov.querySelector(".gv-range"), single = ov.querySelector(".gv-single");
  const lnum = () => { ov.querySelector(".gv-lnum").textContent = `${tr("层数")} ${view.layer} / ${view.layers} · Z ${(view.tp.head.layers[view.layer - 1] || 0).toFixed(2)} mm`; };
  ov.addEventListener("click", (ev) => {
    const b = ev.target.closest("button");
    if (ev.target === ov || (b && b.dataset.gv === "close")) return closeView();
    if (!b) return;
    if (b.dataset.view) view.stage.view(b.dataset.view);
    if (b.dataset.step) { view.setLayer(view.layer + +b.dataset.step, single.checked); range.value = view.layer; lnum(); }
  });
  range.addEventListener("input", () => { view.setLayer(+range.value, single.checked); lnum(); });
  single.addEventListener("change", () => { view.setLayer(+range.value, single.checked); });
  ov.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeView(); });
  try {
    const [f, buf] = await Promise.all([
      api(`/api/print-files/${fid}`),
      fetch(`/api/print-files/${fid}/toolpath`, { credentials: "same-origin" }).then(async (r) => {
        if (!r.ok) { let m = r.statusText; try { m = (await r.json()).error || m; } catch { /* */ } throw new Error(m); }
        return r.arrayBuffer();
      }),
    ]);
    if (!OPEN || OPEN.view !== view) return;
    const tp = decodeToolpath(buf);
    view.load(tp, f.bed_mm || opt.bed);
    range.max = view.layers; range.value = view.layers; lnum();
    const rp = f.report || {}, p = rp.params || {};
    ov.querySelector(".gv-title").textContent = ` ${f.filename} · ${f.printer === "*" ? tr("任何打印机") : f.printer} · ${tr("一盘")} ${f.per_plate} ${tr("个")}`;
    const need = opt.material || f.product_material;
    ov.querySelector(".gv-matbox").innerHTML = matBanner(p, need);
    const hb = p.material && need && sameMat(p.material, need) === "diff";
    ov.querySelector(".gv-hmat").innerHTML = `<span class="mat-badge ${hb ? "bad" : ""}" data-notr>${e(p.material || "?")}</span>${p.nozzle_temp != null ? ` <span class="small">🔥${p.nozzle_temp}° ▭${p.bed_temp ?? "-"}°</span>` : ""}`;
    const tot = Object.values(view.stats).reduce((a, b) => a + b, 0) || 1;
    ov.querySelector(".gv-legend").innerHTML = tp.head.types.map((t, i) => view.stats[i] ? `<label class="row small">
      <input type="checkbox" data-ty="${i}" ${view.visible.has(i) ? "checked" : ""}><span class="sw" style="background:${t.color}"></span>${e(tr(t.zh))}
      <span class="muted">${view.stats[i] / tot < 0.01 ? "&lt;1" : Math.round((view.stats[i] / tot) * 100)}%</span></label>` : "").join("");
    ov.querySelector(".gv-legend").onchange = (ev) => { const t = ev.target.dataset.ty; if (t != null) { view.toggle(+t, ev.target.checked); } };
    ov.querySelector(".gv-sum").innerHTML = [f.grams ? `⚖ ${(+f.grams).toFixed(1)} g` : "", f.hours ? `⏱ ${(+f.hours).toFixed(2)} h` : "",
      rp.layers ? `${tr("层数")} ${rp.layers}` : "", rp.support_pct != null ? `${tr("支撑")} ${rp.support_pct}%` : ""].filter(Boolean).join(" · ");
    ov.querySelector(".gv-par").innerHTML = paramRows(p, f.recipe);
    const LV = { error: "❌", warn: "⚠️", info: "💡", ok: "✅" };
    ov.querySelector(".gv-checks").innerHTML = (f.checks || []).map((c) => `<div class="chk chk-${c.level}">${LV[c.level] || ""} ${e(tr(c.zh))}</div>`).join("");
  } catch (err) {
    ov.querySelector(".gv-loading").textContent = err.message || String(err);
    ov.querySelector(".gv-loading").classList.add("bad");
    return;
  }
  ov.querySelector(".gv-loading").remove();
}
function closeView() {
  if (!OPEN) return;
  OPEN.view.dispose();
  OPEN.ov.remove();
  OPEN = null;
}
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && OPEN) { ev.stopPropagation(); closeView(); } }, true);

// ---------- 打印方案实时预览（不用切片，改参数马上看到） ----------
class ModelView {
  constructor(box) {
    this.box = box;
    this.stage = new Stage(box, { height: Math.max(260, Math.min(420, Math.round((box.clientWidth || 600) * 0.6))) });
    this.cache = {};
    this.objs = [];
  }
  async mesh(pid, orient, ver, spec) {
    const k = pid + ":" + orient + ":" + (ver || "") + ":" + (spec || "");
    if (!this.cache[k]) {
      this.cache[k] = fetch(`/api/products/${encodeURIComponent(pid)}/mesh?orient=${orient}&v=${encodeURIComponent(ver || "")}${spec ? `&spec=${encodeURIComponent(spec)}` : ""}`, { credentials: "same-origin" })
        .then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || r.statusText); return r.arrayBuffer(); })
        .then((b) => new Float32Array(b));
      this.cache[k].catch(() => delete this.cache[k]);
    }
    return this.cache[k];
  }
  clear() {
    for (const o of this.objs) { this.stage.world.remove(o); o.traverse((x) => { if (x.geometry && !x.userData.shared) x.geometry.dispose(); if (x.material) x.material.dispose(); }); }
    this.objs = [];
  }
  async update(s) {
    const token = (this.token = (this.token || 0) + 1);
    let pos;
    try { pos = s.raw || await this.mesh(s.pid, s.orient, s.ver, s.spec); } catch (err) { if (s.onInfo) s.onInfo({ error: err.message }); return; }
    if (token !== this.token) return;
    // 尺寸
    let mnx = 1e9, mny = 1e9, mxx = -1e9, mxy = -1e9, mxz = 0;
    for (let i = 0; i < pos.length; i += 3) {
      const x = pos[i], y = pos[i + 1], z = pos[i + 2];
      if (x < mnx) mnx = x; if (x > mxx) mxx = x; if (y < mny) mny = y; if (y > mxy) mxy = y; if (z > mxz) mxz = z;
    }
    const fw = mxx - mnx, fd = mxy - mny;
    // 颜色：贴热床（蓝）、悬空要支撑（红/橙）、其他（灰）
    const cosT = Math.cos(((s.supportAngle || 30) * Math.PI) / 180);
    const nTri = pos.length / 9;
    const col = new Float32Array(pos.length);
    const over = [];
    let overArea = 0, contactArea = 0;
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), n = new THREE.Vector3();
    for (let t = 0; t < nTri; t++) {
      const o = t * 9;
      a.set(pos[o], pos[o + 1], pos[o + 2]); b.set(pos[o + 3], pos[o + 4], pos[o + 5]); c.set(pos[o + 6], pos[o + 7], pos[o + 8]);
      n.subVectors(b, a).cross(c.clone().sub(a));
      const area = n.length() / 2;
      if (area < 1e-9) continue;
      n.normalize();
      const zc = (a.z + b.z + c.z) / 3;
      let r = 0.78, g = 0.8, bl = 0.84;
      if (n.z < -0.98 && zc < 0.3) { r = 0.23; g = 0.51; bl = 0.96; contactArea += area; }
      else if (n.z < -cosT && zc > 0.3) {
        overArea += area;
        if (s.supports === "none") { r = 0.9; g = 0.2; bl = 0.2; } else { r = 0.98; g = 0.55; bl = 0.1; }
        if (over.length < 60000) over.push(o);
      }
      for (let k = 0; k < 3; k++) { col[o + k * 3] = r; col[o + k * 3 + 1] = g; col[o + k * 3 + 2] = bl; }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    geo.computeVertexNormals();
    // 支撑示意：悬空面往下投到热床的半透明柱子
    let supGeo = null;
    if (s.supports !== "none" && over.length) {
      const sp = new Float32Array(over.length * 9 * 4);
      let v = 0;
      const put = (x, y, z) => { sp[v++] = x; sp[v++] = y; sp[v++] = z; };
      for (const o of over) {
        const P = [[pos[o], pos[o + 1], pos[o + 2]], [pos[o + 3], pos[o + 4], pos[o + 5]], [pos[o + 6], pos[o + 7], pos[o + 8]]];
        for (let k = 0; k < 3; k++) {
          const p1 = P[k], p2 = P[(k + 1) % 3];
          put(p1[0], p1[1], p1[2]); put(p2[0], p2[1], p2[2]); put(p2[0], p2[1], 0);
          put(p1[0], p1[1], p1[2]); put(p2[0], p2[1], 0); put(p1[0], p1[1], 0);
        }
      }
      supGeo = new THREE.BufferGeometry();
      supGeo.setAttribute("position", new THREE.BufferAttribute(sp.subarray(0, v), 3));
    }
    // 一盘排版（按外框估算，实际以切片为准）
    const [bw, bd] = s.bed || [256, 256];
    const gap = (+s.gap || 6) + (s.brim ? 8 : 0), margin = 5;
    const fit = (w, d) => [Math.max(0, Math.floor((bw - 2 * margin + gap) / (w + gap))), Math.max(0, Math.floor((bd - 2 * margin + gap) / (d + gap)))];
    let [cx, cy] = fit(fw, fd);
    let rot = false;
    const [rx, ry] = fit(fd, fw);
    if (rx * ry > cx * cy) { [cx, cy] = [rx, ry]; rot = true; }
    const cap = (s.heightMax && mxz > s.heightMax) ? 0 : cx * cy;
    const count = Math.max(1, Math.min(+s.count || 1, Math.max(1, cap)));
    const w1 = rot ? fd : fw, d1 = rot ? fw : fd;
    const cols = Math.min(cx || 1, count), rows = Math.ceil(count / (cols || 1));
    const totW = cols * w1 + (cols - 1) * gap, totD = rows * d1 + (rows - 1) * gap;
    const x0 = (bw - totW) / 2, y0 = (bd - totD) / 2;
    if (token !== this.token) return;
    this.clear();
    this.stage.setBed(bw, bd);
    const mat = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.75, metalness: 0, side: THREE.DoubleSide });
    const supMat = new THREE.MeshBasicMaterial({ color: 0x10b981, transparent: true, opacity: 0.22, side: THREE.DoubleSide, depthWrite: false });
    const brimMat = new THREE.LineBasicMaterial({ color: 0x475569 });
    for (let i = 0; i < count; i++) {
      const gx = i % cols, gy = Math.floor(i / cols);
      const grp = new THREE.Group();
      const inner = new THREE.Group();
      const m = new THREE.Mesh(geo, mat); m.userData.shared = true; inner.add(m);
      if (supGeo) { const sm = new THREE.Mesh(supGeo, supMat); sm.userData.shared = true; inner.add(sm); }
      inner.position.set(-mnx - fw / 2, -mny - fd / 2, 0);
      const holder = new THREE.Group();
      holder.add(inner);
      if (rot) holder.rotation.z = Math.PI / 2;
      grp.add(holder);
      grp.position.set(x0 + gx * (w1 + gap) + w1 / 2, y0 + gy * (d1 + gap) + d1 / 2, 0);
      if (s.brim) {
        const bwid = 5, hw = w1 / 2 + bwid, hd = d1 / 2 + bwid;
        const lg = new THREE.BufferGeometry();
        lg.setAttribute("position", new THREE.Float32BufferAttribute([-hw, -hd, 0.1, hw, -hd, 0.1, hw, hd, 0.1, -hw, hd, 0.1, -hw, -hd, 0.1], 3));
        grp.add(new THREE.Line(lg, brimMat));
      }
      this.stage.world.add(grp);
      this.objs.push(grp);
    }
    const fk = `${bw}x${bd}:${s.orient}:${count}:${s.fitKey || ""}`;
    if (this.fitKey !== fk) {
      const pad = 15;
      this.stage.fit([Math.max(0, x0 - pad), Math.max(0, y0 - pad), 0], [Math.min(bw, x0 + totW + pad), Math.min(bd, y0 + totD + pad), Math.max(mxz, 20)]);
      this.fitKey = fk;
    }
    this.stage.render();
    if (s.onInfo) s.onInfo({ size: [fw, fd, mxz], overhang_cm2: overArea / 100, contact_cm2: contactArea / 100, capacity: cap, count, tooTall: !!(s.heightMax && mxz > s.heightMax) });
  }
  dispose() { this.clear(); this.stage.dispose(); }
}

const sameMat = (a, b) => {
  const n = (m) => String(m || "PLA").toUpperCase().replace(/[ _]/g, "").replace(/^PLA\+$|^PLAPLUS$/, "PLA").replace(/^PETG\+$/, "PETG");
  a = n(a); b = n(b);
  if (a === b) return "same";
  if (a.split("-")[0] === b.split("-")[0]) return "close";
  return "diff";
};

window.GVIEW = { openFile, close: closeView, ModelView, sameMat, paramRows, matBanner };
window.dispatchEvent(new Event("gview-ready"));
