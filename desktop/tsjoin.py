"""这台电脑自动加入你的 Tailscale 网络（v2.29，Windows）。桌面客户端和托盘加速器共用。

流程：用这台电脑的电脑加速密钥问 NAS 要「预授权密钥」（NAS 上 设置 → 通用 → 外网自动加入 填的）→
没装 Tailscale 就从官网下载安装（静默安装，开机后台运行）→ tailscale up --authkey 加入 → 告诉 NAS 结果。
需要管理员权限：会弹一次 Windows「是否允许更改」，点「是」。密钥只经过一个临时文件，用完马上删掉。

★ 对外：status()  join(server, worker_key, hostname, log=print)
"""
import json
import os
import re
import subprocess
import tempfile
import time

MSI_URL = "https://pkgs.tailscale.com/stable/tailscale-setup-latest-amd64.msi"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def exe():
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        p = os.path.join(base, "Tailscale", "tailscale.exe") if base else ""
        if p and os.path.isfile(p):
            return p
    return None


def status():
    """{installed, running, ips, error}"""
    e = exe()
    if not e:
        return {"installed": False, "running": False, "ips": []}
    try:
        r = subprocess.run([e, "status", "--json"], capture_output=True, text=True, timeout=10, creationflags=NOWIN)
        d = json.loads(r.stdout or "{}")
        ips = (d.get("Self") or {}).get("TailscaleIPs") or d.get("TailscaleIPs") or []
        return {"installed": True, "running": d.get("BackendState") == "Running", "ips": [i for i in ips if ":" not in i],
                "state": d.get("BackendState") or ""}
    except Exception as ex:  # noqa: BLE001
        return {"installed": True, "running": False, "ips": [], "error": str(ex)[:120]}


def _runas_wait(ps_file, timeout=900):
    """以管理员身份运行 PowerShell 脚本（弹 UAC），等它结束。返回 True = 运行了，False = 用户点了「否」。"""
    import ctypes
    from ctypes import wintypes

    class SEI(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                    ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR), ("lpDirectory", wintypes.LPCWSTR),
                    ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                    ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY), ("dwHotKey", wintypes.DWORD),
                    ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]
    sei = SEI()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = 0x00000040            # SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = "powershell.exe"
    sei.lpParameters = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{ps_file}"'
    sei.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        return False                  # 点了「否」或者没有权限
    ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, int(timeout * 1000))
    ctypes.windll.kernel32.CloseHandle(sei.hProcess)
    return True


def join(server, worker_key, hostname, log=print, require_auto=False):
    """返回 {ok, ips?, error?, already?, skip?}。require_auto：NAS 上没开「自动加入」就什么都不做（skip）。"""
    import requests
    h = {"Authorization": "Bearer " + worker_key}
    try:
        r = requests.get(server.rstrip("/") + "/api/v1/accel/tailscale", headers=h, timeout=15)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"连不上 NAS：{e}"}
    if r.status_code == 404:
        return {"ok": False, "error": (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("error")
                or "NAS 上还没有打开「外网自动加入」或没填预授权密钥"}
    if r.status_code != 200:
        return {"ok": False, "error": f"NAS 返回 HTTP {r.status_code}"}
    info = r.json()
    if require_auto and not info.get("auto"):
        return {"ok": False, "skip": True, "error": "NAS 上没有开「自动加入」"}
    st = status()
    if st.get("running"):
        _report(server, h, True, st.get("ips"), "已经在 Tailscale 网络里")
        return {"ok": True, "already": True, "ips": st.get("ips")}
    hostname = re.sub(r"[^a-z0-9-]", "-", (hostname or "3dops-pc").lower()).strip("-")[:60] or "3dops-pc"
    tmp = tempfile.mkdtemp(prefix="3dops_ts_")
    keyf, psf, logf = os.path.join(tmp, "k.txt"), os.path.join(tmp, "join.ps1"), os.path.join(tmp, "out.txt")
    with open(keyf, "w", encoding="ascii") as f:
        f.write(info["authkey"])
    msi = os.path.join(tmp, "tailscale.msi")
    ps = f"""$ErrorActionPreference = 'Continue'
$out = '{logf}'
try {{
  $exe = Join-Path $env:ProgramFiles 'Tailscale\\tailscale.exe'
  if (-not (Test-Path $exe)) {{
    [Net.ServicePointManager]::SecurityProtocol = 'Tls12'
    Invoke-WebRequest '{info.get("msi_url") or MSI_URL}' -OutFile '{msi}' -UseBasicParsing
    Start-Process msiexec.exe -ArgumentList '/i', '"{msi}"', '/qn', '/norestart', 'TS_UNATTENDEDMODE=always', 'TS_NOLAUNCH=1' -Wait
    Start-Sleep -Seconds 5
  }}
  $k = (Get-Content '{keyf}' -Raw).Trim()
  & $exe up --authkey=$k --unattended --hostname={hostname} 2>&1 | Out-File $out -Encoding utf8
}} catch {{ $_ | Out-File $out -Append -Encoding utf8 }}
finally {{ Remove-Item '{keyf}' -Force -ErrorAction SilentlyContinue; Remove-Item '{msi}' -Force -ErrorAction SilentlyContinue }}
"""
    with open(psf, "w", encoding="utf-8-sig") as f:
        f.write(ps)
    log("连接外网（Tailscale）：等你在弹出的窗口点「是」…")
    try:
        ran = _runas_wait(psf)
    finally:
        try:
            os.remove(keyf)
        except OSError:
            pass
    if not ran:
        _report(server, h, False, [], "用户没有允许（UAC 点了否）")
        return {"ok": False, "error": "没有允许管理员权限（弹窗点了「否」），以后可以在菜单里再点「连接外网」"}
    for _ in range(30):
        st = status()
        if st.get("running"):
            break
        time.sleep(2)
    detail = ""
    try:
        with open(logf, encoding="utf-8-sig", errors="replace") as f:
            detail = f.read()[-400:]
    except OSError:
        pass
    ok = bool(st.get("running"))
    _report(server, h, ok, st.get("ips"), "" if ok else (detail or st.get("error") or "没有连上"))
    try:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": ok, "ips": st.get("ips") or [], "error": "" if ok else (detail.strip() or "没有连上 Tailscale")}


def _report(server, h, ok, ips, msg):
    try:
        import requests
        requests.post(server.rstrip("/") + "/api/v1/accel/tailscale/joined", headers=h,
                      json={"ok": ok, "ips": ips or [], "msg": str(msg or "")[:300]}, timeout=10)
    except Exception:  # noqa: BLE001
        pass
