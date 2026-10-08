"""桌面客户端（v2.28）：下载安装包、登录后自动配对（每台电脑一把电脑加速密钥）、老板看 / 停用桌面端。"""
import io
import zipfile

from web.common import *  # noqa: F401,F403
from core import desktop


@app.post("/api/desktop/pair")
def desktop_pair():
    u = auth.current_user()
    if not u or u.get("id", -1) == -1:
        return err("请先登录", 401)
    b = request.get_json(silent=True) or {}
    try:
        r = desktop.pair(u, b.get("device_id"), b.get("device_name"))
    except ValueError as e:
        return err(str(e))
    db.audit(u.get("username", ""), "桌面端配对", str(b.get("device_name") or "")[:40], str(b.get("device_id") or "")[:8])
    return jsonify({"ok": True, **r, "server_version": VERSION})


@app.get("/api/desktop/devices")
def desktop_devices():
    return jsonify({"devices": desktop.devices()})


@app.post("/api/desktop/devices/<did>/revoke")
def desktop_revoke(did):
    if not desktop.revoke(did):
        return err("找不到这台电脑", 404)
    db.audit(_uname(), "停用桌面端", did[:8])
    return jsonify({"ok": True})


# ---- 「在本机打开」：网页拿一个 2 分钟有效的一次性下载码，桌面端直接下载（不用经过网页传大文件） ----
import re as _re
import secrets as _secrets
import time as _time
_DL = {}
DL_OK = (r"/api/print-files/\d+/download", r"/api/products/[^/]{1,60}/model/download")


@app.post("/api/desktop/dltoken")
def desktop_dltoken():
    u = auth.current_user()
    if not u or u.get("id", -1) == -1:
        return err("请先登录", 401)
    path = str((request.get_json(silent=True) or {}).get("path") or "").split("?")[0]
    if not any(_re.fullmatch(p, path) for p in DL_OK):
        return err("这个文件不能在本机打开")
    now = _time.time()
    for k in [k for k, v in _DL.items() if v["exp"] < now]:
        _DL.pop(k, None)
    tok = _secrets.token_urlsafe(24)
    _DL[tok] = {"path": path, "user": dict(u), "exp": now + 120}
    return jsonify({"url": "/api/desktop/dl/" + tok})


@app.get("/api/desktop/dl/<tok>")
def desktop_dl(tok):
    from flask import g
    t = _DL.pop(tok, None)
    if not t or t["exp"] < _time.time():
        return err("下载码过期了，请再点一次", 404)
    g.user = t["user"]
    endpoint, args = app.url_map.bind("").match(t["path"], method="GET")
    return app.view_functions[endpoint](**args)


INSTALL_BAT = r'''@echo off
chcp 65001 >nul
title 3D Ops Desktop - Install
cd /d "%~dp0"
set "DEST=%LOCALAPPDATA%\3D-Ops-Desktop"
echo.
echo   Installing 3D Ops Desktop to %DEST% ...
echo.
if not exist "%DEST%" mkdir "%DEST%"
xcopy /e /i /y /q "%~dp0app" "%DEST%\app" >nul
copy /y "%~dp0server.json" "%DEST%\server.json" >nul
set "PYCMD="
if exist "%DEST%\.venv\Scripts\pythonw.exe" goto deps
py -3.12 --version >nul 2>nul && set "PYCMD=py -3.12"
if not defined PYCMD py -3.13 --version >nul 2>nul && set "PYCMD=py -3.13"
if not defined PYCMD py -3.11 --version >nul 2>nul && set "PYCMD=py -3.11"
if not defined PYCMD if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set PYCMD="%LocalAppData%\Programs\Python\Python312\python.exe"
if defined PYCMD goto venv
echo   Python not found - downloading Python 3.12 (about 25 MB) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '%TEMP%\py312.exe'"
if not exist "%TEMP%\py312.exe" goto pyfail
"%TEMP%\py312.exe" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=1 Include_test=0
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set PYCMD="%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYCMD goto pyfail
:venv
echo   Creating environment ...
%PYCMD% -m venv "%DEST%\.venv"
if not exist "%DEST%\.venv\Scripts\pythonw.exe" goto pyfail
:deps
echo   Installing components (first time 3-10 minutes, needs internet) ...
"%DEST%\.venv\Scripts\python.exe" -m pip install -q --upgrade pip
"%DEST%\.venv\Scripts\python.exe" -m pip install -q -r "%DEST%\app\desktop\requirements-desktop.txt"
if errorlevel 1 goto pipfail
"%DEST%\.venv\Scripts\python.exe" "%DEST%\app\desktop\setup_shortcuts.py"
echo.
echo   DONE. Starting 3D Ops Desktop ...
start "" "%DEST%\.venv\Scripts\pythonw.exe" "%DEST%\app\desktop\desktop_app.py"
timeout /t 3 /nobreak >nul
exit /b 0
:pyfail
echo.
echo   [ERROR] Could not install Python automatically.
echo   Please install Python 3.12 from python.org, then run this file again.
pause
exit /b 1
:pipfail
echo.
echo   [ERROR] Installing components failed. Check internet and run this file again.
pause
exit /b 1
'''


@app.get("/api/desktop/package")
def desktop_package():
    """桌面客户端安装包：解压后双击「安装.bat」。里面带好 NAS 地址（局域网 + 外网），装好登录就能用。"""
    u = auth.current_user()
    if not u or u.get("id", -1) == -1:
        return err("请先登录", 401)
    import json
    from web.accel import PKG_DIRS, PKG_FILES
    cfg = load_config()
    here = request.host_url.rstrip("/")
    servers = [here] + [x for x in [str(cfg.get("remote_url") or "").rstrip("/")] if x and x != here]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for d in PKG_DIRS:
            for root, dirs, files in os.walk(os.path.join(BASE_DIR, d)):
                dirs[:] = [x for x in dirs if x != "__pycache__" and not x.startswith(".")]
                for f in files:
                    if f.endswith((".pyc", ".pyo")):
                        continue
                    fp = os.path.join(root, f)
                    z.write(fp, "3D-Ops-Desktop/app/" + os.path.relpath(fp, BASE_DIR).replace(os.sep, "/"))
        for f in PKG_FILES:
            fp = os.path.join(BASE_DIR, f)
            if os.path.exists(fp):
                z.write(fp, "3D-Ops-Desktop/app/" + f)
        z.writestr("3D-Ops-Desktop/server.json", json.dumps({"servers": servers, "version": VERSION}, ensure_ascii=False))
        z.writestr("3D-Ops-Desktop/Install.bat", INSTALL_BAT.replace("\n", "\r\n"))
    buf.seek(0)
    db.audit(u.get("username", ""), "下载桌面客户端", VERSION)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=f"3D-Ops-Desktop-{VERSION}.zip")
