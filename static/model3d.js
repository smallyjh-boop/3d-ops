// 3D 模型预览与商品图渲染（three.js，浏览器本地运行，不需要安装别的软件）
import * as THREE from "three";
import { STLLoader } from "/static/vendor/three/STLLoader.js";
import { ThreeMFLoader } from "/static/vendor/three/3MFLoader.js";
import { OrbitControls } from "/static/vendor/three/OrbitControls.js";
import { toCreasedNormals } from "/static/vendor/three/BufferGeometryUtils.js";
import { RoomEnvironment } from "/static/vendor/three/RoomEnvironment.js";

const FINISH = {   // 按颜色代码设定材质效果
  GD: { metalness: 0.85, roughness: 0.3 },
  SV: { metalness: 0.85, roughness: 0.3 },
  CL: { transmission: 0.7, roughness: 0.15, thickness: 2 },
  GW: { emissive: 0x9bff7a, emissiveIntensity: 0.15 },
  RB: { rainbow: true },
  MC: { rainbow: true },
};

// ---- 真实打印质感（v2.14）：不用 AI，按打印规律在着色器里画出层纹、顶面走线 ----
// 层纹：沿打印方向每一层一道圆弧形的料丝（法线起伏 + 凹槽稍暗）；顶面：±45° 走线，按层交替方向；
// 线比屏幕像素还细时自动淡出，避免摩尔纹。打印方向（up）按打印方案的摆放方向换算到画面坐标。
const PRINT_UP = { bottom: [0, 1, 0], top: [0, -1, 0], front: [0, 0, -1], back: [0, 0, 1], left: [1, 0, 0], right: [-1, 0, 0] };
// 表面效果：粗糙度 / 金属感 / 清漆 / 光泽
const SURFACE = {
  matte: { roughness: 0.62, metalness: 0, sheen: 0 },          // 哑光 PLA / ABS / ASA
  satin: { roughness: 0.48, metalness: 0, sheen: 0.25 },       // TPU / 普通 PLA 稍亮
  glossy: { roughness: 0.28, metalness: 0, clearcoat: 0.35, clearcoatRoughness: 0.25 },   // PETG
  silk: { roughness: 0.22, metalness: 0.28, sheen: 0.6, sheenRoughness: 0.3 },            // 丝绸 PLA
  carbon: { roughness: 0.82, metalness: 0, sheen: 0 },         // 碳纤维（很哑）
  resin: { roughness: 0.32, metalness: 0, clearcoat: 0.2, clearcoatRoughness: 0.3 },      // 光固化树脂（看不到层纹）
};
function autoSurface(material) {
  const m = String(material || "PLA").toUpperCase();
  if (m.startsWith("RESIN")) return "resin";
  if (m.includes("CF")) return "carbon";
  if (m.startsWith("PETG") || m.startsWith("PC")) return "glossy";
  if (m.startsWith("TPU")) return "satin";
  if (m.includes("SILK")) return "silk";
  return "matte";
}
function applyPrintShader(mat, P) {
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.uLayer = { value: P.layer };
    sh.uniforms.uLine = { value: P.line };
    sh.uniforms.uAmp = { value: P.amp };
    sh.uniforms.uUp = { value: new THREE.Vector3(...P.up) };
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vPW;")
      .replace("#include <project_vertex>", "#include <project_vertex>\nvPW = (modelMatrix * vec4(transformed, 1.0)).xyz;");
    const head = `uniform float uLayer; uniform float uLine; uniform float uAmp; uniform vec3 uUp; varying vec3 vPW;
float pBead(float t) { return 1.0 - abs(2.0 * t - 1.0); }
// 层纹在屏幕上太密（小于约 3 像素一层）时，改成每 2^n 层画一条、强度减弱：远看也能看出是打印件，又不会出摩尔纹（v2.19）
vec2 pLayers(float ly) {
  float fw = max(fwidth(ly), 1e-5);
  float lvl = max(0.0, ceil(log2(fw / 0.3)));
  float m = exp2(min(lvl, 6.0));
  float l2 = ly / m;
  float fade = 1.0 - smoothstep(0.3, 0.75, fwidth(l2));
  return vec2(l2, fade * (lvl > 0.0 ? 0.16 : 1.0));
}`;
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", "#include <common>\n" + head)
      .replace("#include <color_fragment>", `#include <color_fragment>
      {
        vec2 pl = pLayers(dot(vPW, uUp) / uLayer);
        float fadeL = pl.y;
        float tt = fract(pl.x);
        diffuseColor.rgb *= 1.0 - 0.10 * fadeL * pow(abs(2.0 * tt - 1.0), 6.0);
      }`)
      .replace("#include <normal_fragment_maps>", `#include <normal_fragment_maps>
      {
        vec3 nw = normalize((vec4(normal, 0.0) * viewMatrix).xyz);
        float ny = dot(nw, uUp);
        // 侧面：层纹
        float side = 1.0 - smoothstep(0.6, 0.9, abs(ny));
        float ly = dot(vPW, uUp) / uLayer;
        vec2 pl = pLayers(ly);
        float fadeL = pl.y;
        float sl = 1.0 - 2.0 * fract(pl.x);
        vec3 tUp = uUp - nw * ny;
        float tl = length(tUp);
        if (tl > 1e-4) nw += (tUp / tl) * sl * uAmp * side * fadeL;
        // 顶面：±45° 走线（每层换方向）
        float top = smoothstep(0.88, 0.98, ny);
        if (top > 0.0) {
          vec3 ax = abs(uUp.y) > 0.5 ? vec3(1.0, 0.0, 0.0) : vec3(0.0, 1.0, 0.0);
          vec3 e1 = normalize(cross(uUp, ax)), e2 = cross(uUp, e1);
          float layerIdx = floor(ly + 0.5);
          vec3 dir = normalize(mod(layerIdx, 2.0) < 0.5 ? e1 + e2 : e1 - e2);
          vec3 perp = normalize(cross(uUp, dir));
          float u = dot(vPW, perp) / uLine;
          float fadeT = 1.0 - smoothstep(0.3, 0.75, fwidth(u));
          nw += perp * (1.0 - 2.0 * fract(u)) * uAmp * 0.7 * top * fadeT;
        }
        normal = normalize((viewMatrix * vec4(normalize(nw), 0.0)).xyz);
      }`);
  };
  mat.customProgramCacheKey = () => `print2-${P.layer}-${P.line}-${P.amp}-${P.up.join(",")}`;
}

const _t = (k, zh) => { try { return window.TR ? window.TR(k) : zh; } catch { return zh; } };   // 界面语言（泰文）
const BIG_TRIS = 150000;   // 超过这么多三角面算「大模型」：先快速显示，平滑效果后台再算

class Viewer {
  constructor(container) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.NeutralToneMapping || THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xffffff);
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.envTex = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environment = this.envTex;
    this.scene.environmentIntensity = 0.75;
    // 兼容模式：部分显卡/驱动处理环境光会出错（模型全黑），改用普通材质+灯光
    try { this.safe = localStorage.getItem("viewer_safe") === "1"; } catch { this.safe = false; }

    this.camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100000);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = false;
    this.controls.addEventListener("change", () => {
      const v = this.camera.position.clone().sub(this.controls.target);
      this._placeLights(Math.atan2(v.x, v.z));
      this._checkLod();
      this.redraw();
    });

    const hemi = new THREE.HemisphereLight(0xffffff, 0xb8b8b8, 0.45);
    this.hemi = hemi;
    this.scene.add(hemi);
    this.sun = new THREE.DirectionalLight(0xffffff, 1.6);
    this.sun.castShadow = false;
    this.sun.shadow.mapSize.set(2048, 2048);
    this.sun.shadow.radius = 6;
    this.sun.shadow.bias = -0.0005;
    this.scene.add(this.sun);
    this.scene.add(this.sun.target);
    this.ground = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.ShadowMaterial({ opacity: 0.2 }));
    this.fill = new THREE.DirectionalLight(0xffffff, 0.5);   // 补光，减轻暗面
    this.scene.add(this.fill);
    this.ground.rotation.x = -Math.PI / 2;
    this.ground.receiveShadow = true;
    this.ground.visible = false;   // 不要地面阴影：商品图、场景图都是干净的产品
    this.scene.add(this.ground);

    if (this.safe) { this.scene.environment = null; this.hemi.intensity = 1.1; this.fill.intensity = 0.8; }
    this.print = { on: false, layer: 0.2, surface: "auto", material: "PLA", orient: "bottom", shadow: false };
    this.model = null;
    this.box = null;
    this._pending = false;
    this._resize();
    new ResizeObserver(() => this._resize()).observe(container);
  }

  // 只在画面有变化时重绘（不持续占用显卡）
  redraw() {
    if (this._pending) return;
    this._pending = true;
    requestAnimationFrame(() => { this._pending = false; this.renderer.render(this.scene, this.camera); });
  }

  _resize() {
    const w = this.container.clientWidth || 400, h = this.container.clientHeight || 400;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.redraw();
  }

  // 读模型时盖在 3D 区域上的进度提示（大文件下载要几秒，让人知道在干什么）；msg 为空 = 去掉
  _busy(msg) {
    let el = this._busyEl;
    if (!msg) { if (el) el.remove(); this._busyEl = null; return; }
    if (!el) {
      if (getComputedStyle(this.container).position === "static") this.container.style.position = "relative";
      el = this._busyEl = document.createElement("div");
      el.style.cssText = "position:absolute;left:8px;bottom:8px;max-width:calc(100% - 16px);padding:5px 10px;border-radius:6px;" +
        "background:rgba(30,30,30,.72);color:#fff;font-size:12px;line-height:1.4;pointer-events:none;z-index:5";
      this.container.appendChild(el);
    }
    el.textContent = msg;
  }

  // 下载并显示进度（MB）。服务器给了压缩数据时浏览器拿不到总大小，就只显示已下载多少。
  async _fetchBuf(url, label) {
    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok || !res.body || !window.ReadableStream) return { res, buf: res.ok ? await res.arrayBuffer() : null };
    const total = res.headers.get("Content-Encoding") ? 0 : +res.headers.get("Content-Length") || 0;
    const reader = res.body.getReader(), chunks = [];
    let got = 0, last = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value); got += value.length;
      const now = performance.now();
      if (label && now - last > 150) {
        last = now;
        this._busy(`${label} ${(got / 1048576).toFixed(1)}${total ? " / " + (total / 1048576).toFixed(1) : ""} MB…`);
      }
    }
    const out = new Uint8Array(got);
    let o = 0;
    for (const c of chunks) { out.set(c, o); o += c.length; }
    return { res, buf: out.buffer };
  }

  // 打开得慢（超过 2 秒）就报给服务器记日志，方便排查是慢在下载、解析还是显示
  _report(kind, url) {
    const t = this.lastTiming;
    if (!t || t.total < 2000) return;
    try {
      fetch("/api/client-timing", { method: "POST", headers: { "Content-Type": "application/json" }, credentials: "same-origin",
        body: JSON.stringify({ kind, url: String(url || "").split("?")[0], ...t }) }).catch(() => {});
    } catch { /* 不影响使用 */ }
  }

  // fallback：浏览器读不了的 3MF（拓竹 / Orca 项目文件，模型放在别的文件里）改用服务器转好的 STL
  async load(url, ext, fallback, opt = {}) {
    if (String(ext || "").toLowerCase().replace(/^\./, "") === "3mf" && fallback) {
      try { return await this.load(url, ext, null, opt); }
      catch (e) { console.warn("3MF 浏览器读不了，改用服务器转换：", e && e.message); return this.load(fallback, "stl", null, opt); }
    }
    const T0 = performance.now(), tm = {};
    if (!opt.quiet) this._busy(_t("v3d.downloading", "正在下载模型") + "…");
    let res, buf;
    try { ({ res, buf } = await this._fetchBuf(url, opt.quiet ? "" : (opt.label || _t("v3d.downloading", "正在下载模型")))); }
    catch (e) { this._busy(""); throw e; }
    if (!res.ok) { this._busy(""); throw new Error(res.status === 404 ? "服务器上找不到这个模型文件" : res.status === 403 ? "没有权限读取模型文件" : `下载模型失败（HTTP ${res.status}）`); }
    tm.download = performance.now() - T0;
    if (buf.byteLength < 84) { this._busy(""); throw new Error("模型文件是空的或者不完整"); }
    ext = String(ext || "").toLowerCase().replace(/^\./, "");
    if (!opt.quiet) { this._busy(_t("v3d.parsing", "正在解析模型…")); await new Promise((r) => setTimeout(r, 0)); }
    try { return this._parseInstall(buf, ext, tm, T0, opt, url); } finally { if (!opt.quiet) this._busy(""); }
  }

  _parseInstall(buf, ext, tm, T0, opt, url) {
    if (ext === "obj") throw new Error("OBJ 文件暂时不能 3D 预览（可以看缩略图，或设为 3D 模型后看）");
    let obj;
    if (ext === "3mf") {
      obj = new ThreeMFLoader().parse(buf);
      let n = 0;
      obj.traverse((m) => { if (m.isMesh && m.geometry && m.geometry.attributes.position) n += m.geometry.attributes.position.count; });
      if (!n) throw new Error("3MF 里没有读到模型");
    } else {
      let geo;
      try { geo = new STLLoader().parse(buf); } catch (e) { throw new Error("STL 文件读不了（可能损坏）：" + e.message); }
      if (!geo.attributes.position || !geo.attributes.position.count) throw new Error("STL 文件里没有三角面（文件可能损坏或不是 STL）");
      geo.computeVertexNormals();
      obj = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial());
    }
    tm.parse = performance.now() - T0 - tm.download;
    tm.bytes = buf.byteLength;
    const met = this._install(obj, tm, T0, opt);
    this._report(opt.keepView ? "完整模型" : "直接打开", url);
    return met;
  }

  // 快速预览：先用服务器精简过的模型（面数少、体积小，几乎马上出来），放大看细节 / 出商品图时再换完整模型。
  // full = { url, ext, fallback }：完整模型的地址。返回服务器算好的完整模型尺寸 / 体积（和完整模型一样准）。
  async loadFast(previewUrl, full) {
    const T0 = performance.now(), tm = {};
    const url = previewUrl + (previewUrl.includes("?") ? "&" : "?") + "nowait=1";
    let res = null, buf = null;
    this._busy(_t("v3d.loading_preview", "正在加载 3D 预览") + "…");
    try { ({ res, buf } = await this._fetchBuf(url, _t("v3d.loading_preview", "正在加载 3D 预览"))); } catch { res = null; }
    if (res && res.status === 202) {
      // 大模型第一次打开：服务器还在后台生成快速预览，这次先读完整模型（和以前一样慢），下次打开就快了
      return this.load(full.url, full.ext, full.fallback, { label: _t("v3d.first_big", "第一次打开这个大模型，正在下载完整文件（后台同时生成快速预览，下次打开就快了）") });
    }
    if (!res || !res.ok || !buf) { this._busy(""); return this.load(full.url, full.ext, full.fallback); }     // 服务器老版本 / 出错：直接读完整模型
    tm.download = performance.now() - T0;
    const dv = new DataView(buf);
    if (buf.byteLength < 16 || String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3)) !== "3DPV") { this._busy(""); return this.load(full.url, full.ext, full.fallback); }
    const nv = dv.getUint32(4, true), nt = dv.getUint32(8, true), fullTris = dv.getUint32(12, true);
    const pos = new Float32Array(buf, 16, nv * 3);
    const idx = new Uint32Array(buf, 16 + nv * 12, nt * 3);
    const jl = dv.getUint32(16 + nv * 12 + nt * 12, true);
    const info = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20 + nv * 12 + nt * 12, jl)));
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos.slice(), 3));
    geo.setIndex(new THREE.BufferAttribute(idx.slice(), 1));
    // v2.19：不能直接用合并过顶点的网格算法线——棱角会被抹圆（看起来像软塑料）。
    // 拆开成独立三角面：面数不多的马上算「35° 以内平滑、棱角锐利」的法线；面数多的先显示平面法线，后台再换成锐利棱角的
    const flat = geo.toNonIndexed();
    flat.computeVertexNormals();
    tm.parse = performance.now() - T0 - tm.download;
    tm.bytes = buf.byteLength; tm.preview = true; tm.fullTriangles = fullTris;
    const met = this._install(new THREE.Mesh(flat, new THREE.MeshPhysicalMaterial()), tm, T0, {});
    this._busy("");
    this._report("快速预览", previewUrl);
    this._full = info.reduced ? full : null;       // 精简过才需要以后换完整模型
    this._fullPromise = null;
    return info.metrics || met;
  }

  // 换成完整模型（不动镜头）。放大看细节、出商品图前调用；已经是完整模型就什么都不做。
  async ensureFull() {
    if (!this._full) return;
    if (!this._fullPromise) {
      const f = this._full;
      this._fullPromise = this.load(f.url, f.ext, f.fallback, { keepView: true, label: _t("v3d.full", "正在换成完整模型（看细节用）") })
        .then(() => { this._full = null; })
        .catch((e) => { console.warn("完整模型读不了，继续用预览模型：", e && e.message); this._full = null; });
    }
    return this._fullPromise;
  }

  _install(obj, tm, T0, opt = {}) {
    const old = this.model;
    // 3D 打印模型是 Z 轴朝上，three.js 是 Y 轴朝上
    const holder = new THREE.Group();
    obj.rotation.x = -Math.PI / 2;
    holder.add(obj);
    holder.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(holder);
    const c = box.getCenter(new THREE.Vector3());
    const wrap = new THREE.Group();   // 把模型放到地面中央
    wrap.add(holder);
    holder.position.set(-c.x, -box.min.y, -c.z);
    wrap.updateMatrixWorld(true);
    let tris = 0;
    wrap.traverse((m) => { if (m.isMesh && m.geometry.attributes.position) tris += (m.geometry.index ? m.geometry.index.count : m.geometry.attributes.position.count) / 3; });
    const big = tris > BIG_TRIS || opt.smooth === false;
    const deferred = [];
    wrap.traverse((m) => {
      if (m.isMesh) {
        // 3MF 文件里没有法线，不计算的话模型在灯光下是全黑的
        // 平滑法线：曲面上不再看到一块块三角面（35° 以内的面平滑过渡，棱角保持锐利）
        // 大模型（几十万面）先用简单法线马上显示，平滑法线放到后台算好再换上，不让人干等
        let g = m.geometry;
        if (g.attributes.color) g.deleteAttribute("color");
        if (big) {
          if (!g.attributes.normal) g.computeVertexNormals();
          if (opt.smooth !== false) deferred.push(m);
        } else {
          try { g = toCreasedNormals(g, THREE.MathUtils.degToRad(35)); }
          catch (e) { if (g.index) g = g.toNonIndexed(); g.computeVertexNormals(); }
        }
        m.geometry = g;
        m.castShadow = !!(this.print && this.print.shadow);
        m.receiveShadow = false;
        m.material = this._mat({ color: new THREE.Color(0xdddddd), roughness: 0.55, metalness: 0 });
      }
    });
    if (old) {
      this.scene.remove(old);
      old.traverse((m) => { if (m.isMesh) { m.geometry.dispose(); if (m.material) m.material.dispose(); } });
    }
    this.model = wrap;
    this._full = null;
    this.scene.add(wrap);
    this.box = new THREE.Box3().setFromObject(wrap);
    const size = this.box.getSize(new THREE.Vector3());
    const span = Math.max(size.x, size.y, size.z);
    this.ground.scale.set(span * 20, span * 20, 1);
    this.span = span;
    const cam = this.sun.shadow.camera;
    cam.left = cam.bottom = -span * 1.5; cam.right = cam.top = span * 1.5;
    cam.near = 0.1; cam.far = span * 10;
    cam.updateProjectionMatrix();
    if (opt.keepView) { this._checkLod(); if (this._lastColor) this.setColor(...this._lastColor); else this.redraw(); }
    else this.view(35, 22);
    tm.prepare = performance.now() - T0 - tm.download - tm.parse;
    const met = this.metrics();
    tm.metrics = performance.now() - T0 - tm.download - tm.parse - tm.prepare;
    tm.total = performance.now() - T0;
    tm.triangles = Math.round(tris); tm.smoothLater = deferred.length > 0;
    this.lastTiming = tm;
    if (deferred.length) {           // 后台算平滑法线：分批做，每批之间让浏览器喘口气
      const model = wrap;
      const run = () => {
        const m = deferred.shift();
        if (!m || this.model !== model) return;
        try { m.geometry = toCreasedNormals(m.geometry, THREE.MathUtils.degToRad(35)); } catch { /* 保持简单法线 */ }
        this.redraw();
        if (deferred.length) setTimeout(run, 30);
      };
      setTimeout(run, 400);
    }
    return met;
  }

  metrics() {
    let vol = 0, area = 0;
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
    const ab = new THREE.Vector3(), ac = new THREE.Vector3();
    this.model.traverse((m) => {
      if (!m.isMesh) return;
      const g = m.geometry, pos = g.attributes.position, idx = g.index;
      const n = idx ? idx.count : pos.count;
      for (let i = 0; i < n; i += 3) {
        const i0 = idx ? idx.getX(i) : i, i1 = idx ? idx.getX(i + 1) : i + 1, i2 = idx ? idx.getX(i + 2) : i + 2;
        a.fromBufferAttribute(pos, i0).applyMatrix4(m.matrixWorld);
        b.fromBufferAttribute(pos, i1).applyMatrix4(m.matrixWorld);
        c.fromBufferAttribute(pos, i2).applyMatrix4(m.matrixWorld);
        vol += a.dot(b.clone().cross(c)) / 6;
        area += ab.subVectors(b, a).cross(ac.subVectors(c, a)).length() / 2;
      }
    });
    const s = this.box.getSize(new THREE.Vector3());
    // size：宽(X) × 深(Z) × 高(Y)，单位毫米
    return { volume_mm3: Math.abs(vol), area_mm2: area, size: [+s.x.toFixed(1), +s.z.toFixed(1), +s.y.toFixed(1)] };
  }

  // 打印方向分析：6 个摆放方向（哪一面朝下），计算悬空面积、底面接触面积、打印高度
  analyze() {
    if (!this.model) return null;
    const dirs = [
      { key: "bottom", label: "原始方向（底面朝下）", d: new THREE.Vector3(0, -1, 0) },
      { key: "top", label: "倒放（顶面朝下）", d: new THREE.Vector3(0, 1, 0) },
      { key: "front", label: "前面朝下平放", d: new THREE.Vector3(0, 0, 1) },
      { key: "back", label: "背面朝下平放", d: new THREE.Vector3(0, 0, -1) },
      { key: "left", label: "左侧朝下平放", d: new THREE.Vector3(-1, 0, 0) },
      { key: "right", label: "右侧朝下平放", d: new THREE.Vector3(1, 0, 0) },
    ];
    const tris = [];
    const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
    const ab = new THREE.Vector3(), ac = new THREE.Vector3();
    this.model.traverse((m) => {
      if (!m.isMesh) return;
      const g = m.geometry, pos = g.attributes.position, idx = g.index;
      const n = idx ? idx.count : pos.count;
      for (let i = 0; i < n; i += 3) {
        const i0 = idx ? idx.getX(i) : i, i1 = idx ? idx.getX(i + 1) : i + 1, i2 = idx ? idx.getX(i + 2) : i + 2;
        a.fromBufferAttribute(pos, i0).applyMatrix4(m.matrixWorld);
        b.fromBufferAttribute(pos, i1).applyMatrix4(m.matrixWorld);
        c.fromBufferAttribute(pos, i2).applyMatrix4(m.matrixWorld);
        const nrm = ab.subVectors(b, a).cross(ac.subVectors(c, a));
        const area2 = nrm.length();
        if (area2 < 1e-9) continue;
        nrm.divideScalar(area2);
        tris.push([nrm.x, nrm.y, nrm.z, area2 / 2, (a.x + b.x + c.x) / 3, (a.y + b.y + c.y) / 3, (a.z + b.z + c.z) / 3,
          Math.min(a.x, b.x, c.x), Math.min(a.y, b.y, c.y), Math.min(a.z, b.z, c.z), Math.max(a.x, b.x, c.x), Math.max(a.y, b.y, c.y), Math.max(a.z, b.z, c.z)]);
      }
    });
    let total = 0; tris.forEach((t) => (total += t[3]));
    const res = dirs.map(({ key, label, d }) => {
      const up = d.clone().negate();
      // 各三角形沿「向上」方向的最低点
      let minH = Infinity, maxH = -Infinity;
      for (const t of tris) {
        const lo = Math.min(up.x * (up.x >= 0 ? t[7] : t[10]), up.x * (up.x >= 0 ? t[10] : t[7])) +
          Math.min(up.y * (up.y >= 0 ? t[8] : t[11]), up.y * (up.y >= 0 ? t[11] : t[8])) +
          Math.min(up.z * (up.z >= 0 ? t[9] : t[12]), up.z * (up.z >= 0 ? t[12] : t[9]));
        const hi = Math.max(up.x * t[7], up.x * t[10]) + Math.max(up.y * t[8], up.y * t[11]) + Math.max(up.z * t[9], up.z * t[12]);
        if (lo < minH) minH = lo; if (hi > maxH) maxH = hi;
      }
      let over = 0, contact = 0, steep = 0;
      for (const t of tris) {
        const dot = t[0] * up.x + t[1] * up.y + t[2] * up.z;
        const h = t[4] * up.x + t[5] * up.y + t[6] * up.z - minH;
        if (dot < -0.98 && h < 0.3) { contact += t[3]; continue; }
        if (dot < -0.707) over += t[3];          // 超过 45° 的悬空面，需要支撑
        else if (dot < -0.5) steep += t[3];      // 30-45° 的陡峭面，可能下垂
      }
      return { key, label, height_mm: +(maxH - minH).toFixed(1), overhang_cm2: +(over / 100).toFixed(1),
        steep_cm2: +(steep / 100).toFixed(1), contact_cm2: +(contact / 100).toFixed(1),
        overhang_pct: +(over / total * 100).toFixed(1) };
    });
    // 评分：支撑越少越好，接触面太小不稳，高度越高越慢
    const span = this.span || 100;
    res.forEach((r) => {
      r.score = +(r.overhang_cm2 * 3 + r.steep_cm2 + (r.contact_cm2 < 1 ? 8 : r.contact_cm2 < 3 ? 3 : 0) + r.height_mm / span * 2).toFixed(2);
    });
    const sorted = [...res].sort((x, y) => x.score - y.score);
    const s = this.box.getSize(new THREE.Vector3());
    const base = res[0];
    return {
      size_mm: [+s.x.toFixed(1), +s.z.toFixed(1), +s.y.toFixed(1)],
      surface_cm2: +(total / 100).toFixed(1),
      orientations: res, best: sorted[0].key,
      tall_thin: base.height_mm / Math.max(1, Math.min(s.x, s.z)) > 3,
      triangles: tris.length,
    };
  }

  _mat(o) {
    let mat;
    if (this.safe) {
      mat = new THREE.MeshStandardMaterial({ color: o.color, roughness: Math.max(0.35, o.roughness ?? 0.5),
        metalness: Math.min(0.3, o.metalness || 0), emissive: o.emissive || new THREE.Color(0),
        emissiveIntensity: o.emissiveIntensity || 0, side: THREE.DoubleSide, transparent: !!o.transmission, opacity: o.transmission ? 0.75 : 1 });
    } else {
      mat = new THREE.MeshPhysicalMaterial({ clearcoat: 0, ...o, side: THREE.DoubleSide });
    }
    const pr = this.print;
    // 层纹：一直画（v2.19：平时预览也要看得出是打印件）；放大看细节、出大图（商品图）时用完整强度，
    // 平时稍淡一点。线条太密时着色器自己会淡出（不会出摩尔纹），显卡负担很小
    if (pr && pr.on && o.printable !== false) {
      const resin = this._surface() === "resin";
      const layer = resin ? 0.05 : Math.max(0.04, +pr.layer || 0.2);
      const k = (this._near || this._hd) ? 1 : 0.75;
      applyPrintShader(mat, { layer, line: resin ? 0.05 : 0.42, amp: (resin ? 0.08 : 0.38) * k, up: PRINT_UP[pr.orient] || PRINT_UP.bottom });
    }
    return mat;
  }

  // 镜头离模型够近（放大看细节）时切到细节档，拉远了切回普通档
  _checkLod() {
    if (!this.box) return;
    const r = this.box.getBoundingSphere(new THREE.Sphere()).radius || 1;
    const d = this.camera.position.distanceTo(this.controls.target);
    if (this._full && d < r * 3.0) this.ensureFull();
    if (!this.print || !this.print.on) return;
    const near = d < r * (this._near ? 3.4 : 3.0);        // 有一点回差，免得在边界来回切
    if (near && this._full) this.ensureFull();        // 放大看细节：换完整模型
    if (near !== this._near) { this._near = near; this._refreshMat(); }
  }
  _refreshMat() { if (this.model && this._lastColor) this.setColor(...this._lastColor); }

  _surface() {
    const pr = this.print || {};
    return !pr.surface || pr.surface === "auto" ? autoSurface(pr.material) : pr.surface;
  }

  // 真实打印质感：on 开关；layer 层高 mm；surface auto/matte/satin/glossy/silk/carbon/resin；material 产品材料；
  // orient 打印方案的摆放方向（决定层纹方向）；shadow 地面接触阴影
  setPrint(o = {}) {
    this.print = { ...this.print, ...o };
    if (this.print.on && this.box) {
      const r = this.box.getBoundingSphere(new THREE.Sphere()).radius || 1;
      this._near = this.camera.position.distanceTo(this.controls.target) < r * 3.0;
    }
    const sh = !!this.print.shadow;
    this.sun.castShadow = sh;
    this.ground.visible = sh;
    if (this.model) this.model.traverse((m) => { if (m.isMesh) m.castShadow = sh; });
    if (this._lastColor) this.setColor(...this._lastColor);
    else this.redraw();
  }

  setSafe(on) {
    this.safe = !!on;
    try { localStorage.setItem("viewer_safe", on ? "1" : "0"); } catch { /* 忽略 */ }
    this.scene.environment = on ? null : this.envTex;
    this.hemi.intensity = on ? 1.1 : 0.45;
    this.fill.intensity = on ? 0.8 : 0.5;
    if (this._lastColor) this.setColor(...this._lastColor);
    else this.redraw();
  }

  // 检查模型是不是被画成了全黑（显卡不支持时），是的话自动切到兼容模式
  checkBlack() {
    if (!this.model || this.safe || !this._lastColor) return false;
    const want = new THREE.Color(this._lastColor[0]);
    if (want.r + want.g + want.b < 0.6) return false;   // 本来就是深色
    this.renderer.render(this.scene, this.camera);
    const c = this.box.getCenter(new THREE.Vector3()).project(this.camera);
    const el = this.renderer.domElement, w = el.width, h = el.height;
    const tmp = document.createElement("canvas"); tmp.width = w; tmp.height = h;
    const g = tmp.getContext("2d"); g.drawImage(el, 0, 0);
    const cx = Math.round((c.x + 1) / 2 * w), cy = Math.round((1 - c.y) / 2 * h);
    const d = g.getImageData(Math.max(0, cx - 10), Math.max(0, cy - 10), 20, 20).data;
    let sum = 0, n = 0;
    for (let i = 0; i < d.length; i += 4) { if (d[i + 3] > 0) { sum += d[i] + d[i + 1] + d[i + 2]; n++; } }
    const avg = n ? sum / n / 3 : 255;
    if (avg < 25) { this.setSafe(true); return true; }
    return false;
  }

  setColor(hex, code) {
    this._lastColor = [hex, code];
    if (!this.model) return;
    const f = FINISH[code] || {};
    const base = new THREE.Color(hex);
    const hsl = base.getHSL({});
    if (hsl.l > 0.82) { base.setHSL(hsl.h, hsl.s, 0.82); hex = "#" + base.getHexString(); }   // 浅色产品在白底上保留轮廓
    this.model.traverse((m) => {
      if (!m.isMesh) return;
      const sf = this.print && this.print.on ? (SURFACE[this._surface()] || {}) : {};
      const mat = this._mat({
        ...sf,
        color: new THREE.Color(hex), roughness: f.roughness ?? sf.roughness ?? 0.5, metalness: f.metalness ?? sf.metalness ?? 0,
        transmission: f.transmission || 0, thickness: f.thickness || 0,
        emissive: f.emissive ? new THREE.Color(f.emissive) : new THREE.Color(0), emissiveIntensity: f.emissiveIntensity || 0,
      });
      m.castShadow = !!(this.print && this.print.shadow);
      if (f.rainbow) {
        const g = m.geometry, pos = g.attributes.position;
        const colors = new Float32Array(pos.count * 3);
        const v = new THREE.Vector3(), col = new THREE.Color();
        const h0 = this.box.min.y, h1 = this.box.max.y;
        for (let i = 0; i < pos.count; i++) {
          v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld);
          col.setHSL(((v.y - h0) / (h1 - h0 || 1)) * 0.8, 0.75, 0.55);
          colors.set([col.r, col.g, col.b], i * 3);
        }
        g.setAttribute("color", new THREE.BufferAttribute(colors, 3));
        mat.vertexColors = true;
        mat.color.set(0xffffff);
      }
      m.material = mat;
    });
    this.redraw();
  }

  view(azimuthDeg, elevationDeg, margin = 1.18) {
    if (!this.box) return;
    const sphere = this.box.getBoundingSphere(new THREE.Sphere());
    const fov = THREE.MathUtils.degToRad(this.camera.fov);
    const dist = (sphere.radius * margin) / Math.sin(fov / 2);
    const az = THREE.MathUtils.degToRad(azimuthDeg), el = THREE.MathUtils.degToRad(elevationDeg);
    const t = sphere.center;
    this.camera.position.set(t.x + dist * Math.cos(el) * Math.sin(az), t.y + dist * Math.sin(el), t.z + dist * Math.cos(el) * Math.cos(az));
    this._placeLights(az);
    this.controls.target.copy(t);
    this.camera.lookAt(t);
    this.controls.update();
    this._checkLod();
    this.redraw();
  }

  // 主光跟着相机：从相机左上方 30° 打光，影子落在产品后方，不会拉出长影
  _placeLights(az) {
    const d = (this.span || 100) * 3, la = az - THREE.MathUtils.degToRad(35), el = THREE.MathUtils.degToRad(62);
    this.sun.position.set(d * Math.cos(el) * Math.sin(la), d * Math.sin(el), d * Math.cos(el) * Math.cos(la));
    this.sun.target.position.set(0, 0, 0);
    const fa = az + THREE.MathUtils.degToRad(70);
    this.fill.position.set(d * Math.sin(fa), d * 0.4, d * Math.cos(fa));
  }

  // 渲染一张方图（默认 1200×1200），dims=true 时加尺寸标注
  // transparent=true：透明背景 PNG（保留阴影），用于场景图合成
  shot({ size = 1200, dims = false, unit = "cm", transparent = false, shadow = 0, fill = 0 } = {}) {
    // 出大图（≥800 像素，商品图）用细节档；小图（AI 分析用的快照等）用普通档
    const wantHd = !!(this.print && this.print.on && size >= 800);
    if (wantHd !== this._hd) { this._hd = wantHd; this._refreshMat(); }
    try { return this._shot({ size, dims, unit, transparent, shadow, fill }); }
    finally { if (this._hd) { this._hd = false; this._refreshMat(); } }
  }

  _shot({ size, dims, unit, transparent, shadow, fill }) {
    const r = this.renderer, oldSize = r.getSize(new THREE.Vector2()), oldRatio = r.getPixelRatio();
    const oldAspect = this.camera.aspect, oldBg = this.scene.background, oldOp = this.ground.material.opacity;
    // 超采样：先按 2 倍尺寸渲染再缩小，边缘更顺滑、更清晰
    const maxSide = Math.min(4096, r.capabilities.maxTextureSize || 4096);
    const ss = Math.max(1, Math.min(2, Math.floor(maxSide / size)));
    r.setPixelRatio(1);
    r.setSize(size * ss, size * ss, false);
    this.camera.aspect = 1;
    this.camera.updateProjectionMatrix();
    if (transparent) { this.scene.background = null; r.setClearColor(0x000000, 0); this.ground.visible = shadow > 0; this.ground.material.opacity = shadow; }
    r.render(this.scene, this.camera);
    if (transparent) {
      const out = document.createElement("canvas");
      out.width = out.height = size;
      const octx = out.getContext("2d"); octx.imageSmoothingQuality = "high";
      octx.drawImage(r.domElement, 0, 0, size, size);
      this.scene.background = oldBg; this.ground.material.opacity = oldOp; this.ground.visible = !!(this.print && this.print.shadow);
      r.setPixelRatio(oldRatio); r.setSize(oldSize.x, oldSize.y, false);
      this.camera.aspect = oldAspect; this.camera.updateProjectionMatrix(); this.redraw();
      return out.toDataURL("image/png");
    }
    const out = document.createElement("canvas");
    out.width = out.height = size;
    const ctx = out.getContext("2d");
    ctx.imageSmoothingQuality = "high";
    ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, size, size);
    const box = fill > 0 && !dims ? this._contentBox(r.domElement) : null;
    if (box) {
      // 产品放大到占画面 fill 比例并居中（电商主图要求产品占满画面）
      const k = (size * fill) / Math.max(box.w, box.h);
      const w = box.w * k, h = box.h * k;
      ctx.drawImage(r.domElement, box.x, box.y, box.w, box.h, (size - w) / 2, (size - h) / 2, w, h);
    } else {
      ctx.drawImage(r.domElement, 0, 0, size, size);
    }
    if (dims) this._drawDims(ctx, size, unit);
    r.setPixelRatio(oldRatio);
    r.setSize(oldSize.x, oldSize.y, false);
    this.camera.aspect = oldAspect;
    this.camera.updateProjectionMatrix();
    this.redraw();
    return out.toDataURL("image/jpeg", 0.95);
  }

  // 找出画面里非白色（产品）的范围
  _contentBox(canvas) {
    const W = canvas.width, H = canvas.height, step = 2;
    const tmp = document.createElement("canvas"); tmp.width = W; tmp.height = H;
    const g = tmp.getContext("2d"); g.drawImage(canvas, 0, 0);
    const d = g.getImageData(0, 0, W, H).data;
    let x0 = W, y0 = H, x1 = -1, y1 = -1;
    for (let y = 0; y < H; y += step) for (let x = 0; x < W; x += step) {
      const i = (y * W + x) * 4;
      if (d[i] < 245 || d[i + 1] < 245 || d[i + 2] < 245) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    }
    if (x1 < 0) return null;
    return { x: Math.max(0, x0 - step), y: Math.max(0, y0 - step), w: Math.min(W, x1 + step) - Math.max(0, x0 - step), h: Math.min(H, y1 + step) - Math.max(0, y0 - step) };
  }

  _drawDims(ctx, size, unit) {
    const b = this.box, s = b.getSize(new THREE.Vector3());
    const pad = Math.max(s.x, s.y, s.z) * 0.08;
    const P = (x, y, z) => {
      const v = new THREE.Vector3(x, y, z).project(this.camera);
      return [(v.x + 1) / 2 * size, (1 - v.y) / 2 * size];
    };
    const fmt = (mm) => unit === "mm" ? `${Math.round(mm)} mm` : `${(mm / 10).toFixed(mm < 100 ? 1 : 0)} cm`;
    const line = (p1, p2, label) => {
      ctx.strokeStyle = "#1f2937"; ctx.fillStyle = "#1f2937"; ctx.lineWidth = Math.max(2, size / 400);
      ctx.beginPath(); ctx.moveTo(...p1); ctx.lineTo(...p2); ctx.stroke();
      for (const [a, c] of [[p1, p2], [p2, p1]]) {   // 两端箭头
        const ang = Math.atan2(c[1] - a[1], c[0] - a[0]), L = size / 60;
        ctx.beginPath(); ctx.moveTo(...a);
        ctx.lineTo(a[0] + L * Math.cos(ang + 0.45), a[1] + L * Math.sin(ang + 0.45));
        ctx.lineTo(a[0] + L * Math.cos(ang - 0.45), a[1] + L * Math.sin(ang - 0.45));
        ctx.closePath(); ctx.fill();
      }
      const mx = (p1[0] + p2[0]) / 2, my = (p1[1] + p2[1]) / 2;
      ctx.font = `600 ${Math.round(size / 26)}px "Segoe UI", Tahoma, sans-serif`;
      const w = ctx.measureText(label).width + size / 40, h = size / 18;
      ctx.fillStyle = "rgba(255,255,255,0.92)"; ctx.fillRect(mx - w / 2, my - h / 2, w, h);
      ctx.strokeStyle = "#1f2937"; ctx.lineWidth = 1.5; ctx.strokeRect(mx - w / 2, my - h / 2, w, h);
      ctx.fillStyle = "#111827"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(label, mx, my);
    };
    // 宽：前下边；深：右下边；高：左前竖边（相机在右前方）
    line(P(b.min.x, 0, b.max.z + pad), P(b.max.x, 0, b.max.z + pad), fmt(s.x));
    line(P(b.max.x + pad, 0, b.min.z), P(b.max.x + pad, 0, b.max.z), fmt(s.z));
    line(P(b.min.x - pad, 0, b.max.z), P(b.min.x - pad, s.y, b.max.z), fmt(s.y));
  }
}

window.Model3D = { Viewer, THREE };
window.dispatchEvent(new Event("model3d-ready"));
