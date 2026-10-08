"""电脑加速（v2.20）和任务中心的接口。

  电脑上的加速程序（worker.py）用「电脑加速」密钥（scope = worker）调用：
    POST /api/v1/accel/hello                报到（每 15 秒），带上会做哪些活、CPU / 显卡
    GET  /api/v1/accel/next?name=&caps=     领活（最多等 25 秒，没活回 204）
    GET  /api/v1/accel/task/<id>/file/<名>  下载输入文件
    POST /api/v1/accel/task/<id>/done       传回结果（表单：result = JSON，其余是文件）
    POST /api/v1/accel/task/<id>/fail       做不了 {error, final}（final = 文件本身有问题，NAS 不用再试）
    GET  /api/v1/accel/package              下载和 NAS 同版本的程序（电脑上自动更新用）
  网页用：GET /api/accel/status  POST /api/accel/key（老板）  GET /api/bg/list  POST /api/bg/<id>/retry  POST /api/bg/clear
"""
import io
import json
import zipfile

from flask import g

from web.common import *  # noqa: F401,F403
from core import accel, bgjobs


def _wname():
    return (request.args.get("name") or (request.get_json(silent=True) or {}).get("name") or g.user.get("display_name") or "PC")[:40]


@app.post("/api/v1/accel/hello")
def accel_hello():
    b = request.get_json(force=True) or {}
    from core import desktop
    kname = (g.user or {}).get("display_name") or ""
    user = desktop.user_of_key(kname)
    if user:
        desktop.touch(kname, str(b.get("version") or ""))
    return jsonify(accel.hello(b.get("name") or _wname(), b, request.remote_addr or "", user))


@app.get("/api/v1/accel/next")
def accel_next():
    caps = [c for c in (request.args.get("caps") or "").split(",") if c]
    try:
        wait = float(request.args.get("wait") or 25)
    except ValueError:
        wait = 25
    t = accel.next_task(_wname(), caps, wait)
    if not t:
        return "", 204
    return jsonify(t)


@app.get("/api/v1/accel/task/<tid>/file/<name>")
def accel_file(tid, name):
    p = accel.task_file(tid, name)
    if not p or not os.path.exists(p):
        return err("任务已经取消或文件不存在", 404)
    return send_file(p, as_attachment=True, download_name=name)


@app.post("/api/v1/accel/task/<tid>/done")
def accel_done(tid):
    request.max_content_length = 1024 * 1024 * 1024        # 切好的 3MF 可能比较大
    try:
        res = json.loads(request.form.get("result") or "{}")
    except ValueError:
        return err("result 不是 JSON")
    files = {k: request.files[k] for k in request.files}
    if not accel.task_done(tid, _wname(), res, files):
        return err("任务已经取消（等太久 NAS 自己做了）", 410)
    return jsonify({"ok": True})


@app.post("/api/v1/accel/task/<tid>/fail")
def accel_fail(tid):
    b = request.get_json(force=True) or {}
    accel.task_fail(tid, _wname(), b.get("error") or "出错", bool(b.get("final")))
    return jsonify({"ok": True})


PKG_DIRS = ("core", "web", "desktop")
PKG_FILES = ("app.py", "worker.py", "requirements.txt", "check_env.py")
# 电脑上用的启动脚本（NAS 上可能没有这几个文件，下载时用这里的内容补上）
BAT_TEXT = {'4_start_worker.bat': '@echo off\ncd /d "%~dp0"\ntitle 3D Ops - PC accelerator - keep this window open\nchcp 65001 >nul\nset PYTHONIOENCODING=utf-8\nif exist ".venv\\Scripts\\python.exe" goto check\necho Not installed yet, running setup first...\ncall 1_setup.bat\nif not exist ".venv\\Scripts\\python.exe" exit /b 1\n:check\n".venv\\Scripts\\python.exe" -c "import numpy, requests, PIL" 2>nul || ".venv\\Scripts\\python.exe" -m pip install -q -r requirements.txt\n:loop\n".venv\\Scripts\\python.exe" worker.py\nif errorlevel 3 if not errorlevel 4 goto updated\nif errorlevel 2 if not errorlevel 3 goto nosetup\necho.\necho Accelerator stopped. Restarting in 10 seconds - close this window to quit.\ntimeout /t 10 /nobreak >nul\ngoto loop\n:updated\necho Updated from NAS, restarting...\ntimeout /t 2 /nobreak >nul\ngoto loop\n:nosetup\npause\nexit /b 2\n',
    '5_worker_autostart.bat': '@echo off\ncd /d "%~dp0"\ntitle 3D Ops - accelerator auto start\nset "S=%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\3dops_accelerator.bat"\nif exist "%S%" goto remove\n> "%S%" echo @echo off\n>> "%S%" echo start "3D Ops accelerator" /min "%~dp04_start_worker.bat"\necho.\necho DONE. The PC accelerator will start automatically (minimized) when Windows starts.\necho Run this file again to turn auto start OFF.\npause\nexit /b 0\n:remove\ndel "%S%"\necho.\necho Auto start is now OFF. Run this file again to turn it back ON.\npause\nexit /b 0\n',
    '1_setup.bat': '@echo off\ncd /d "%~dp0"\ntitle 3D Ops - Setup\necho.\necho ===== Step 1/3: Find Python =====\nset "PYCMD="\n\npy -3 --version >nul 2>nul\nif not errorlevel 1 set "PYCMD=py -3"\nif defined PYCMD goto found\n\npython --version >nul 2>nul\nif not errorlevel 1 set "PYCMD=python"\nif defined PYCMD goto found\n\nfor /d %%D in ("%LocalAppData%\\Programs\\Python\\Python3*") do if exist "%%~D\\python.exe" set PYCMD="%%~D\\python.exe"\nif defined PYCMD goto found\nfor /d %%D in ("%ProgramFiles%\\Python3*") do if exist "%%~D\\python.exe" set PYCMD="%%~D\\python.exe"\nif defined PYCMD goto found\nfor /d %%D in ("C:\\Python3*") do if exist "%%~D\\python.exe" set PYCMD="%%~D\\python.exe"\nif defined PYCMD goto found\n\necho.\necho [ERROR] Python not found on this computer.\necho Please install Python 3.12 from python.org - Downloads - Windows.\necho IMPORTANT: on the first installer screen, tick "Add python.exe to PATH".\necho Then double-click 1_setup.bat again.\necho.\npause\nexit /b 1\n\n:found\necho Using: %PYCMD%\n%PYCMD% --version\n%PYCMD% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"\nif errorlevel 1 goto tooold\necho Python version OK.\ngoto venv\n\n:tooold\necho [ERROR] Python is too old. Need 3.10 or newer, 3.12 recommended.\npause\nexit /b 1\n\n:venv\necho.\necho ===== Step 2/3: Create environment .venv =====\nif exist ".venv\\Scripts\\python.exe" goto install\n%PYCMD% -m venv .venv\nif errorlevel 1 goto venvfail\ngoto install\n\n:venvfail\necho [ERROR] Could not create .venv - please send a screenshot of this window.\npause\nexit /b 1\n\n:install\necho.\necho ===== Step 3/3: Install packages =====\n".venv\\Scripts\\python.exe" -m pip install --upgrade pip\n".venv\\Scripts\\python.exe" -m pip install -r requirements.txt\nif errorlevel 1 goto pipfail\necho.\necho ===== Environment check =====\n".venv\\Scripts\\python.exe" check_env.py\necho.\necho DONE. From now on, double-click 2_start.bat to start.\npause\nexit /b 0\n\n:pipfail\necho [ERROR] Package install failed. Check internet and run again.\necho If it still fails, send a screenshot of this window.\npause\nexit /b 1\n',
    '3_install_bg_removal.bat': '@echo off\ncd /d "%~dp0"\ntitle Install background removal - optional\nif not exist ".venv\\Scripts\\python.exe" goto nosetup\necho Installing rembg, about 200MB, please wait a few minutes...\n".venv\\Scripts\\python.exe" -m pip install "rembg[cpu]"\nif errorlevel 1 goto fail\necho.\necho DONE. The first background removal will download a model file, about 170MB.\npause\nexit /b 0\n:nosetup\necho Please run 1_setup.bat first.\npause\nexit /b 1\n:fail\necho [ERROR] Install failed - please send a screenshot of this window.\npause\nexit /b 1\n'}

PKG_BATS = ("1_setup.bat", "3_install_bg_removal.bat", "4_start_worker.bat", "5_worker_autostart.bat")


def _package(with_bats):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for d in PKG_DIRS:
            for root, dirs, files in os.walk(os.path.join(BASE_DIR, d)):
                dirs[:] = [x for x in dirs if x != "__pycache__" and not x.startswith(".")]
                for f in files:
                    if f.endswith((".pyc", ".pyo")):
                        continue
                    fp = os.path.join(root, f)
                    z.write(fp, os.path.relpath(fp, BASE_DIR))
        for f in PKG_FILES + (PKG_BATS if with_bats else ()):
            fp = os.path.join(BASE_DIR, f)
            if os.path.exists(fp):
                z.write(fp, f)
            elif f in BAT_TEXT:          # 旧的在线升级不更新 .bat：用程序里带的内容（v2.20.1）
                z.writestr(f, BAT_TEXT[f].replace("\n", "\r\n"))
    buf.seek(0)
    return buf


@app.get("/api/v1/accel/package")
def accel_package():
    """电脑上的加速程序自动更新：和 NAS 一样的程序代码（不含 .bat，正在运行的 .bat 被覆盖会出错）。"""
    return send_file(_package(False), mimetype="application/zip", as_attachment=True, download_name=f"3d-ops-worker-{VERSION}.zip")


@app.get("/api/accel/package")
def accel_package_full():
    """下载电脑加速程序：解压到电脑上，双击 4_start_worker.bat。
    v2.28：?personal=1（员工下载时一定是）= 「我的加速器」：包里带好 NAS 地址和只属于这个账号的密钥，双击就能用，只做自己的活。
    老板不带 personal 下载 = 共享加速电脑（自己在设置里生成密钥填进去，谁的活都做）。"""
    import json as _json
    u = auth.current_user()
    if not u or u.get("id", -1) == -1:
        return err("请先登录", 401)
    personal = request.args.get("personal") == "1" or not auth.is_owner()
    buf = _package(True)
    if not personal:
        return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=f"3d-ops-worker-{VERSION}.zip")
    import secrets
    from core import desktop
    r = desktop.pair(u, secrets.token_hex(16), "浏览器+加速器")
    out = io.BytesIO()
    with zipfile.ZipFile(buf) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for it in zin.infolist():
            z.writestr(it, zin.read(it.filename))
        z.writestr("data/worker.json", _json.dumps({"server": request.host_url.rstrip("/"), "key": r["key"],
                                                     "name_prefix": (u.get("display_name") or u.get("username") or "")[:14]}, ensure_ascii=False))
    out.seek(0)
    db.audit(_uname(), "下载我的加速器", VERSION)
    return send_file(out, mimetype="application/zip", as_attachment=True, download_name=f"3d-ops-accelerator-{VERSION}.zip")


@app.get("/api/accel/status")
def accel_status():
    return jsonify(accel.status())


@app.post("/api/accel/key")
def accel_key():
    if not auth.is_owner() and auth.current_user():
        return err("只有老板可以生成密钥", 403)
    from core import integrations
    raw = integrations.create_key((request.get_json(silent=True) or {}).get("name") or "电脑加速", "worker")
    db.audit(_uname(), "电脑加速·生成密钥", "", raw[:9])
    return jsonify({"ok": True, "key": raw})


# ---------------- 任务中心 ----------------
def _see_all():
    u = auth.current_user()
    return not u or auth.is_owner()


@app.get("/api/bg/list")
def bg_list():
    u = None if (_see_all() and request.args.get("all") == "1") else _uname()
    return jsonify({"jobs": bgjobs.list_jobs(u), "counts": bgjobs.counts(u), "accel": _accel_brief()})


def _accel_brief():
    ws = [w for w in accel.workers() if w["online"]]
    return {"online": [w["name"] for w in ws], "enabled": accel.enabled()}


@app.post("/api/bg/<jid>/retry")
def bg_retry(jid):
    if not _see_all() and bgjobs.owner_of(jid) != _uname():
        return err("不是你的任务", 403)
    j = bgjobs.retry(jid)
    if not j:
        return err("这个任务不能重试（已经过期或没有失败）", 400)
    return jsonify({"ok": True, "job": j["id"]})


@app.post("/api/bg/clear")
def bg_clear():
    bgjobs.clear(None if (_see_all() and request.args.get("all") == "1") else _uname())
    return jsonify({"ok": True})
