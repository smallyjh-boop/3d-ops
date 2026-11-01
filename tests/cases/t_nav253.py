# v2.53「返回」回到原来的地方（全系统）：static/nav.js 接进首页和各个入口；有 Node + Playwright 时起一个测试服务器，
# 用 tests/ui/nav_check.js 真的点一遍（采集箱 文件夹 + 搜索 + 滚动 → 编辑 → 返回 / 浏览器后退 / 刷新后返回、产品库、订单抽屉、
# 商品 360、盘点单、待办、直接打开编辑页、手机页 /m）
import os as _os
T = _os.environ["T3D_TMP"]; APP = _os.environ["T3D_APP"]
import os, re, shutil, socket, subprocess, sys, time, urllib.request
D = T + "/v253nav"; shutil.rmtree(D, ignore_errors=True); shutil.copytree(T + "/v13", D)
import sqlite3
c0 = sqlite3.connect(D + "/app.db"); c0.execute("delete from users"); c0.commit(); c0.close()      # 没有账号 = 不用登录就能打开首页
os.environ["LH_DATA_DIR"] = D; sys.path.insert(0, APP)
E_ = 0
def ok(b, m):
    global E_; print(("OK  " if b else "ERR ") + m); E_ += (not b)
def src(p):
    return open(os.path.join(APP, p), encoding="utf-8").read()

import app as A
C = A.app.test_client()

# ---------- 首页接上 nav.js（在 app.js 前面），文件能下载 ----------
html = C.get("/").get_data(as_text=True)
i_nav, i_app = html.find("/static/nav.js"), html.find("/static/app.js")
ok(0 < i_nav < i_app, "index loads nav.js before app.js")
r = C.get("/static/nav.js")
ok(r.status_code == 200 and b"window.NAV" in r.data, "static nav.js served")
r.close()

# ---------- 内核：换页面记历史、后退恢复、模块页面恢复前放回状态 ----------
appjs, modkit, nav = src("static/app.js"), src("static/modkit.js"), src("static/nav.js")
ok("NAV.before(name, opt)" in appjs and "NAV.after(name, navMode)" in appjs, "showTab records history through NAV")
ok("NAV.start(first)" in appjs, "startup continues the session history (reload)")
ok("NAV.applyPending(name)" in modkit and "NAV.showing(" in modkit, "module pages get their state back before show()")
for k in ("pushState", "popstate", "sessionStorage", "nav-hl", "data-nav-back"):
    ok(k in nav, f"nav.js has {k}")
ok("try { return JSON.parse(sessionStorage" in nav and "catch" in nav, "sessionStorage wrapped in try/catch")
ok(".nav-hl" in src("static/style.css"), "highlight style")

# ---------- 各个入口 ----------
ok('data-nav-back="library"' in src("modules/goods/ui/page.html"), "editor ← 返回 uses NAV (fallback 产品库)")
lib = src("modules/goods/ui/library.js")
ok('$("#btn-ed-back").addEventListener' not in lib and "NAV.mark({ hl: id })" in lib, "openProduct marks the item to highlight")
ok("NAV.keep(" in src("modules/curate/ui/curate.js"), "采集箱 / 候选池 / 队列 remember folder + search + filters")
ok("NAV.overlay($(\"#ord-detail\")" in src("modules/orders/ui/orders.js") and "NAV.keep(\"orders\"" in src("modules/orders/ui/orders.js"), "order drawer + order list state")
ok("NAV.keep(\"export\"" in src("modules/listing/ui/export.js") and "NAV.keep(\"online\"" in src("modules/listing/ui/online.js"), "上架工作台 / 在线商品 state")
ok("NAV.keep(\"purchase\"" in src("modules/pur/ui/purchase.js"), "采购 state")
ok("NAV.view(\"st\"" in src("modules/inv/ui/stocktake.js"), "盘点单 = in-page detail with history")
ok("NAV.overlay(ROOT" in src("static/p360.js") and "p360: HIST[POS]" in src("static/p360.js"), "商品 360 drawer + reopen after editing")
sh = src("static/shell.js")
ok("NAV.overlay(drawer" in sh and "NAV.overlay(gs" in sh and 'await goTab("library");\n        if (await waitFor' not in sh, "待办 / 搜索 drawers; search opens the editor directly")
ok("NAV.overlay($(\"#modal\")" in src("static/modal.js"), "modals close on browser back")
m = src("modules/mobile/ui/m.js")
ok("history.length > 1" not in m and "md: MD" in m, "/m ‹ back uses its own history depth (no leaving the app)")

# ---------- 真的点一遍（Node + Playwright）----------
node = shutil.which("node")
nodepath = os.pathsep.join(x for x in [os.environ.get("NODE_PATH", ""), "/opt/node-tools/node_modules"] if x)
have_pw = node and subprocess.run([node, "-e", "require('playwright')"], capture_output=True, env={**os.environ, "NODE_PATH": nodepath}).returncode == 0
if not have_pw:
    print("OK  (no Node + Playwright here: browser flows skipped)")
else:
    from core import db
    db.release()
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    tl = os.path.join(APP, "templates_lazada")
    before = set(os.listdir(tl)) if os.path.isdir(tl) else set()
    D2 = T + "/v253nav_ui"; shutil.rmtree(D2, ignore_errors=True); shutil.copytree(T + "/v13", D2)
    os.makedirs(D2 + "/tmp", exist_ok=True)
    env = dict(os.environ, PYTHONPATH=APP, PYTHONIOENCODING="utf-8", LH_NO_MODULE_STARTUP="1", LH_NO_TPL_SYNC="1", LH_NO_UPDATE_CHECK="1", LH_NO_PRESETS="1")
    env.pop("LH_DATA_DIR", None); env.pop("LH_DOCKER", None)
    log = open(T + "/v253nav_server.log", "w")
    srv = subprocess.Popen([sys.executable, os.path.join(APP, "tests", "ui", "i18n_server.py"), D2, str(port)], cwd=T, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        base = f"http://127.0.0.1:{port}"
        up = False
        for _ in range(160):
            try:
                urllib.request.urlopen(base + "/login", timeout=2); up = True; break
            except Exception:  # noqa: BLE001
                if srv.poll() is not None:
                    break
                time.sleep(0.5)
        ok(up, "test server up")
        if up:
            out = subprocess.run([node, os.path.join(APP, "tests", "ui", "nav_check.js"), "--base", base], capture_output=True, text=True,
                                 timeout=600, env={**os.environ, "NODE_PATH": nodepath})
            txt = (out.stdout or "") + (out.stderr or "")
            for line in txt.splitlines():
                if line.startswith(("OK  ", "ERR ")):
                    print(line.replace("ERR ", "ERR ui: ", 1) if line.startswith("ERR") else line)
            ok(out.returncode == 0 and "NAV ERRORS 0" in txt, "browser flows pass" + ("" if out.returncode == 0 else ": " + txt[-800:].replace("Traceback", "trace")))
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()
        for f in (set(os.listdir(tl)) - before) if os.path.isdir(tl) else []:
            if f.startswith("lazada_auto_") and f.endswith(".xlsx"):
                try:
                    os.remove(os.path.join(tl, f))
                except OSError:
                    pass
        shutil.rmtree(D2, ignore_errors=True)
shutil.rmtree(D, ignore_errors=True)
print("ERRORS", E_)
