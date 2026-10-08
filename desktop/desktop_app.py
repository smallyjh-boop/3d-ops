"""3D 运营管理系统 · 桌面客户端（v2.28，Windows）。

一个窗口 = 和网页版一模一样的系统界面（用 Windows 自带的 Edge 内核 WebView2，不另带浏览器，启动快）；
右下角托盘图标 = 自带的电脑加速（切片、读大模型、3D 预览、抠图、去水印在这台电脑上做，只做自己账号的活）。

· 自动连 NAS：局域网地址连不上就换外网地址（Tailscale），一直在后台检查，断了自动切换。
· 登录一次记住；点 ✕ 是收到托盘（加速继续跑），托盘菜单「退出」才真正关。
· 开机自动启动（托盘菜单可以关），只开托盘不弹窗口。
· 自动更新：NAS 升级后，下次连上自动下载同版本程序并重启自己。
· 网页里多出来的桌面功能（modules/desk/ui/boot.js + static/dragdrop.js）：拖文件进窗口上传、在本机用切片软件打开、系统通知、加速状态。

启动：pythonw desktop_app.py [--tray]（--tray = 开机自启，只在托盘）
"""
import json
import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)                    # 程序目录（core、web、worker.py 在这里）
ROOT = os.environ.get("LH_DESKTOP_ROOT") or os.path.dirname(APP)   # 安装目录（%LOCALAPPDATA%\\3D-Ops-Desktop）
sys.path.insert(0, APP)
sys.path.insert(0, HERE)
CONF = os.path.join(ROOT, "desktop.json")
SERVERS = os.path.join(ROOT, "server.json")
LOCK_PORT = 38791
VERSION = "0"
try:
    import re
    with open(os.path.join(APP, "app.py"), encoding="utf-8") as _f:
        VERSION = re.search(r'^VERSION\s*=\s*"([^"]+)"', _f.read(), re.M).group(1)
except Exception:  # noqa: BLE001
    pass


# ---------------- 设置 ----------------
def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_conf(c):
    try:
        with open(CONF + ".tmp", "w", encoding="utf-8") as f:
            json.dump(c, f, ensure_ascii=False, indent=1)
        os.replace(CONF + ".tmp", CONF)
    except OSError:
        pass


C = load(CONF, {})
if not C.get("device_id"):
    import uuid
    C["device_id"] = uuid.uuid4().hex
    save_conf(C)


def servers():
    lst = list(C.get("servers") or []) + list(load(SERVERS, {}).get("servers") or [])
    out = []
    for s in lst:
        s = str(s or "").strip().rstrip("/")
        if s and s not in out:
            out.append(s)
    return out


# ---------------- 只开一个（第二次双击 = 把窗口叫出来） ----------------
def single_instance(wait=0):
    end = time.time() + wait
    while True:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", LOCK_PORT))
            s.listen(2)
            return s
        except OSError:
            s.close()
            if time.time() < end:
                time.sleep(0.3)
                continue
            try:
                with socket.create_connection(("127.0.0.1", LOCK_PORT), timeout=2) as c:
                    c.sendall(b"restart" if "--installed" in sys.argv else b"show")   # 重新安装后：让旧的重启成新版本
            except OSError:
                pass
            return None


# ---------------- 找 NAS ----------------
def probe(url, timeout=2.0):
    import urllib.request
    try:
        with urllib.request.urlopen(url + "/api/version", timeout=timeout) as r:
            return json.loads(r.read().decode()).get("version") or "?"
    except Exception:  # noqa: BLE001
        return None


def pick_server(timeout=2.0):
    """所有地址一起试，按顺序（局域网在前）取第一个连得上的。"""
    lst = servers()
    res = {}
    ts = [threading.Thread(target=lambda u=u: res.__setitem__(u, probe(u, timeout)), daemon=True) for u in lst]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout + 0.5)
    return next((u for u in lst if res.get(u)), None)


# ---------------- 加速 ----------------
class Accel:
    def __init__(self):
        self.w = None
        self.state = "未配对"          # 未配对 / 连接中 / 在线 / 暂停 / 出错
        self.thread = None

    def start(self, server):
        if not C.get("key") or not server:
            return
        if self.w:
            self.w.server = server
            return
        self.thread = threading.Thread(target=self._run, args=(server,), daemon=True, name="accel")
        self.thread.start()

    def _run(self, server):
        import platform
        try:
            import worker as W
        except Exception as e:  # noqa: BLE001
            self.state = f"出错：{e}"
            return

        class DesktopWorker(W.Worker):
            def update(self):
                W.log(f"NAS 是 v{self.server_version}：下载更新…")
                r = self.s.get(self.server + "/api/v1/accel/package", timeout=180)
                r.raise_for_status()
                import io
                import zipfile
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    for n in z.namelist():
                        if n.endswith("/") or n.startswith(("/", "..")) or ".." in n.split("/") or n.lower().endswith(".bat"):
                            continue
                        dest = os.path.join(APP, n)
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with open(dest + ".upd", "wb") as f:
                            f.write(z.read(n))
                        os.replace(dest + ".upd", dest)
                W.log("更新好了，重新启动…")
                restart()

        slots = C.get("slots") or max(1, min(2, (os.cpu_count() or 2) // 4))
        self.w = DesktopWorker(server, C["key"], C.get("worker_name") or platform.node(), slots)
        self.w.desktop = True
        self.w.paused = bool(C.get("paused"))
        self.w.share = bool(C.get("share"))
        self.w.no_install = bool(C.get("no_install"))
        self.w.auto_update = True
        self.state = "连接中"
        threading.Thread(target=ts_auto, daemon=True).start()
        try:
            self.w.loop()
        except Exception as e:  # noqa: BLE001
            self.state = f"出错：{str(e)[:80]}"

    def info(self):
        try:
            import worker as W
            logs = W.LOG[-40:]
        except Exception:  # noqa: BLE001
            logs = []
        w = self.w
        if not C.get("key"):
            st = "未配对"
        elif not w:
            st = self.state
        elif w.paused:
            st = "暂停"
        elif w.server_version:
            st = "在线"
        else:
            st = "连接中"
        return {"state": st, "done": w.done if w else 0, "failed": w.failed if w else 0, "current": (w.current if w else "") or "",
                "caps": (w.caps if w else []), "installing": (w.installing if w else ""), "log": logs,
                "paused": bool(C.get("paused")), "share": bool(C.get("share")), "name": C.get("worker_name") or ""}


ACCEL = Accel()


# ---------------- 外网自动加入（Tailscale，v2.29 模块） ----------------
TS = {"busy": False, "last": None}


def ts_join(require_auto=False):
    if os.name != "nt" or TS["busy"] or not C.get("key") or not STATE.get("server"):
        return {"ok": False, "error": "现在不能连接（没配对 / 没连上 NAS）"}
    import tsjoin
    TS["busy"] = True
    try:
        r = tsjoin.join(STATE["server"], C["key"], f"3dops-{_pc_name()}-{C.get('user') or ''}",
                        log=lambda m: API.notify("连接外网（Tailscale）", m), require_auto=require_auto)
    finally:
        TS["busy"] = False
    TS["last"] = r
    if not r.get("skip"):
        C["ts_tried"] = 1
        save_conf(C)
        API.notify("连接外网（Tailscale）", ("已连上，在店外也能用了" + (f"（{r['ips'][0]}）" if r.get("ips") else "")) if r.get("ok")
                   else r.get("error") or "没有连上")
    return r


def ts_auto():
    """配对好、第一次连上 NAS 以后：NAS 上开了「自动加入」就自动连一次（只试一次，以后从菜单点）。"""
    for _ in range(120):
        if ACCEL.w and ACCEL.w.server_version:
            break
        time.sleep(1)
    if C.get("ts_tried") or os.name != "nt":
        return
    try:
        import tsjoin
        if tsjoin.status().get("running"):
            C["ts_tried"] = 1
            save_conf(C)
            return
        ts_join(require_auto=True)
    except Exception:  # noqa: BLE001
        pass
STATE = {"server": None, "window": None, "tray": None, "quitting": False}


def restart():
    import subprocess
    exe = sys.executable
    if exe.lower().endswith("python.exe") and os.path.exists(exe[:-10] + "pythonw.exe"):
        exe = exe[:-10] + "pythonw.exe"
    subprocess.Popen([exe, os.path.join(HERE, "desktop_app.py"), "--restarted"] + (["--tray"] if not STATE.get("shown") else []),
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    os._exit(0)


# ---------------- 网页里能调用的（window.pywebview.api.*） ----------------
class Api:
    def info(self):
        return {"desktop": True, "version": VERSION, "device_id": C["device_id"], "device_name": _pc_name(),
                "paired_user": C.get("user") or "", "server": STATE["server"], "servers": servers(),
                "autostart": autostart_get(), "accel": ACCEL.info()}

    def paired(self, server, key, worker_name, user):
        C.update(key=key, worker_name=worker_name, user=user)
        if server and server not in (C.get("servers") or []):
            C["servers"] = [server] + list(C.get("servers") or [])
        save_conf(C)
        if ACCEL.w:                      # 换了账号：用新密钥重新开始
            restart()
        ACCEL.start(STATE["server"] or server)
        return True

    def set_option(self, k, v):
        if k in ("paused", "share"):
            C[k] = bool(v)
            save_conf(C)
            if ACCEL.w:
                setattr(ACCEL.w, k, bool(v))
        if k == "autostart":
            autostart_set(bool(v))
        return self.info()

    def notify(self, title, msg=""):
        t = STATE.get("tray")
        try:
            if t:
                t.notify(str(msg or "")[:250], str(title or "3D 运营")[:60])
        except Exception:  # noqa: BLE001
            pass
        return True

    def open_window(self, url, title="3D 运营管理系统"):
        import webview
        if url.startswith("/"):
            url = STATE["server"] + url
        webview.create_window(str(title)[:80], url, width=1100, height=820, js_api=API)
        return True

    def open_external(self, url):
        import webbrowser
        if str(url).startswith(("http://", "https://")):
            webbrowser.open(url)
        return True

    def open_local(self, path):
        """「在本机打开」：网页先拿一次性下载码，这里直接下载到 文档\\3D-Ops，再用默认程序（Bambu Studio / Orca）打开。"""
        import re
        import requests
        if not str(path).startswith("/api/desktop/dl/"):
            return {"ok": False, "error": "地址不对"}
        r = requests.get(STATE["server"] + path, timeout=600, stream=True)
        if r.status_code != 200:
            return {"ok": False, "error": f"下载失败 HTTP {r.status_code}"}
        cd = r.headers.get("Content-Disposition", "")
        m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
        from urllib.parse import unquote
        name = re.sub(r'[\\/:*?"<>|]', "_", unquote(m.group(1)) if m else "file")[:120]
        d = os.path.join(os.path.expanduser("~"), "Documents", "3D-Ops")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        with open(p + ".part", "wb") as f:
            for ch in r.iter_content(1 << 16):
                f.write(ch)
        os.replace(p + ".part", p)
        try:
            os.startfile(p)          # noqa  Windows：用关联的程序打开
        except Exception as e:  # noqa: BLE001
            return {"ok": True, "path": p, "error": f"文件已保存，但没有能打开它的程序：{e}"}
        return {"ok": True, "path": p}

    def show_folder(self):
        d = os.path.join(os.path.expanduser("~"), "Documents", "3D-Ops")
        os.makedirs(d, exist_ok=True)
        try:
            os.startfile(d)          # noqa
        except Exception:  # noqa: BLE001
            pass
        return True

    def ts_join(self):
        threading.Thread(target=ts_join, daemon=True).start()
        return True

    def ts_status(self):
        try:
            import tsjoin
            st = tsjoin.status() if os.name == "nt" else {"installed": False, "running": False, "ips": []}
        except Exception as e:  # noqa: BLE001
            st = {"error": str(e)}
        return {**st, "busy": TS["busy"], "last": TS["last"]}

    def switch_server(self):
        threading.Thread(target=watch_once, args=(True,), daemon=True).start()
        return True


API = Api()


def _pc_name():
    import platform
    return (os.environ.get("COMPUTERNAME") or platform.node() or "PC")[:24]


# ---------------- 开机自动启动（当前用户，注册表 Run） ----------------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "3D-Ops-Desktop"


def _cmdline():
    exe = sys.executable
    if exe.lower().endswith("python.exe") and os.path.exists(exe[:-10] + "pythonw.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return f'"{exe}" "{os.path.join(HERE, "desktop_app.py")}" --tray'


def autostart_get():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except Exception:  # noqa: BLE001
        return False


def autostart_set(on):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, _cmdline())
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
    except Exception:  # noqa: BLE001
        pass


# ---------------- 窗口 ----------------
OFFLINE_HTML = """<!doctype html><meta charset=utf-8><body style="font:15px system-ui,'Microsoft YaHei';background:#0f172a;color:#e2e8f0;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0"><div style="max-width:520px;line-height:1.7">
<h2 style="margin:0 0 8px">连不上 NAS</h2><div>试过的地址：<br><code>%s</code></div>
<p>在店里：检查电脑和 NAS 是不是同一个网络、NAS 有没有开。<br>在外面：打开这台电脑上的 Tailscale（登录同一个账号）。</p>
<p>每 5 秒自动重试…</p></div>"""


def show_window():
    w = STATE["window"]
    if not w:
        return
    STATE["shown"] = True
    try:
        w.show()
        w.restore()
    except Exception:  # noqa: BLE001
        pass


def watch_once(force=False):
    cur = STATE["server"]
    if cur and not force and probe(cur, 3):
        return
    new = pick_server(2.5)
    w = STATE["window"]
    if new and new != cur:
        STATE["server"] = new
        C["last_server"] = new
        save_conf(C)
        if w:
            path = "/"
            try:
                u = w.get_current_url() or ""
                if cur and u.startswith(cur):
                    path = u[len(cur):] or "/"
            except Exception:  # noqa: BLE001
                pass
            w.load_url(new + path)
        if ACCEL.w:
            ACCEL.w.server = new
        else:
            ACCEL.start(new)
    elif not new and w and not cur:
        w.load_html(OFFLINE_HTML % "<br>".join(servers() or ["（还没有地址）"]))


def watcher():
    while not STATE["quitting"]:
        try:
            watch_once()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5 if not STATE["server"] else 20)


def on_started():
    """窗口出来以后再做慢的事：找 NAS、开托盘、开加速。"""
    threading.Thread(target=tray, daemon=True).start()
    if not STATE["server"]:
        watch_once(True)
    ACCEL.start(STATE["server"])
    threading.Thread(target=watcher, daemon=True).start()


def tray():
    try:
        import pystray
    except Exception:  # noqa: BLE001
        return
    import trayicon
    img = trayicon.image("icon.png", ACCEL.info()["state"])

    def title():
        a = ACCEL.info()
        extra = f" · 正在{a['current']}" if a["current"] else ""
        return f"3D 运营管理系统 v{VERSION}\n电脑加速：{a['state']}{extra} · 已做 {a['done']} 件"[:120]

    def toggle_pause(icon, item):
        API.set_option("paused", not C.get("paused"))

    def toggle_share(icon, item):
        API.set_option("share", not C.get("share"))

    def toggle_auto(icon, item):
        autostart_set(not autostart_get())

    def quit_all(icon, item):
        STATE["quitting"] = True
        icon.stop()
        try:
            if STATE["window"]:
                STATE["window"].destroy()
        finally:
            os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("打开 3D 运营管理系统", lambda i, it: show_window(), default=True),
        pystray.MenuItem("暂停电脑加速", toggle_pause, checked=lambda it: bool(C.get("paused"))),
        pystray.MenuItem("也帮别人加速（同事的活）", toggle_share, checked=lambda it: bool(C.get("share"))),
        pystray.MenuItem("开机自动启动", toggle_auto, checked=lambda it: autostart_get()),
        pystray.MenuItem("打开文件夹（在本机打开的文件）", lambda i, it: API.show_folder()),
        pystray.MenuItem("连接外网（Tailscale）", lambda i, it: API.ts_join()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出（加速也停止）", quit_all))
    icon = pystray.Icon("3d-ops", img, "3D 运营管理系统", menu)
    STATE["tray"] = icon

    def refresh():
        last = None
        while not STATE["quitting"]:
            try:
                st = ACCEL.info()["state"]
                if st != last:
                    icon.icon = trayicon.image("icon.png", st)
                    last = st
                icon.title = title()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(5)
    threading.Thread(target=refresh, daemon=True).start()
    icon.run()


def lock_listener(sock):
    while True:
        try:
            c, _ = sock.accept()
            with c:
                m = c.recv(16)
                if m == b"show":
                    show_window()
                elif m == b"restart":
                    restart()
        except Exception:  # noqa: BLE001
            time.sleep(1)


def main():
    tray_only = "--tray" in sys.argv
    sock = single_instance(wait=8 if "--restarted" in sys.argv else 0)
    if not sock:
        return
    threading.Thread(target=lock_listener, args=(sock,), daemon=True).start()
    import webview
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    # 先用上次连上的地址马上开窗口（快）；连不上的话后台换地址
    last = C.get("last_server") if C.get("last_server") in servers() else None
    STATE["server"] = last
    g = C.get("win") or {}
    url = (last + "/") if last else None
    w = webview.create_window("3D 运营管理系统", url=url, html=None if url else "<body style='background:#0f172a'></body>",
                              js_api=API, width=g.get("w", 1360), height=g.get("h", 860), x=g.get("x"), y=g.get("y"),
                              min_size=(900, 600), hidden=tray_only, text_select=True)
    STATE["window"] = w
    STATE["shown"] = not tray_only

    def closing():
        if STATE["quitting"]:
            return True
        try:
            C["win"] = {"w": w.width, "h": w.height, "x": w.x, "y": w.y}
            save_conf(C)
        except Exception:  # noqa: BLE001
            pass
        if STATE.get("tray"):
            w.hide()                    # ✕ = 收到托盘，加速继续
            if not C.get("tray_tip"):
                C["tray_tip"] = 1
                save_conf(C)
                API.notify("还在后台运行", "电脑加速继续工作。右下角托盘图标可以打开窗口或退出。")
            return False
        return True
    w.events.closing += closing
    storage = os.path.join(ROOT, "webview")
    webview.start(on_started, gui="edgechromium", private_mode=False, storage_path=storage, debug=bool(C.get("debug")))
    STATE["quitting"] = True
    os._exit(0)


if __name__ == "__main__":
    main()
