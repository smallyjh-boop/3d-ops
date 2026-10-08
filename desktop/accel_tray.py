"""3D 运营管理系统 · 电脑加速（托盘版，v2.28.1）：没有黑色窗口，只在右下角托盘。

· 图标右下角小圆点：绿 = 在线，黄 = 连接中，灰 = 暂停，红 = 连不上。
· 托盘菜单：打开系统（浏览器）、暂停加速、也帮别人加速、开机自动启动、运行记录、修改 NAS 地址和密钥、退出。
· 「我的加速器」包里已经带好 NAS 地址和自己账号的密钥；共享加速电脑第一次打开会弹窗填地址和密钥。
· NAS 升级后自动下载同版本程序并重启自己。

启动：pythonw accel_tray.py
"""
import json
import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
sys.path.insert(0, APP)
sys.path.insert(0, HERE)
LOCK_PORT = 38792
RUN_NAME = "3D-Ops-Accelerator"
LOGF = os.path.join(APP, "data", "worker.log")
S = {"w": None, "icon": None, "quitting": False, "err": ""}


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


def pyw():
    exe = sys.executable
    if exe.lower().endswith("python.exe") and os.path.exists(exe[:-10] + "pythonw.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return exe


def restart():
    import subprocess
    subprocess.Popen([pyw(), os.path.join(HERE, "accel_tray.py"), "--restarted"],
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    os._exit(0)


# ---------------- 开机自动启动 ----------------
def autostart_get():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except Exception:  # noqa: BLE001
        return False


def autostart_set(on):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{pyw()}" "{os.path.join(HERE, "accel_tray.py")}"')
            else:
                try:
                    winreg.DeleteValue(k, RUN_NAME)
                except FileNotFoundError:
                    pass
    except Exception:  # noqa: BLE001
        pass


# ---------------- 设置窗口（共享加速电脑第一次、或者菜单「修改 NAS 地址和密钥」） ----------------
def setup_dialog(c):
    """返回新的设置（取消返回 None）。"""
    try:
        import tkinter as tk
    except Exception:  # noqa: BLE001
        return None
    import platform
    res = {}
    root = tk.Tk()
    root.title("3D Ops 加速器 · 设置")
    try:
        root.iconbitmap(os.path.join(HERE, "accel.ico"))
    except Exception:  # noqa: BLE001
        pass
    root.resizable(False, False)
    f = tk.Frame(root, padx=16, pady=12)
    f.pack()
    tk.Label(f, text="NAS 上 3D 运营管理系统的地址（例 http://192.168.31.200:8790）", anchor="w").grid(row=0, column=0, sticky="w")
    e1 = tk.Entry(f, width=52)
    e1.insert(0, c.get("server") or "")
    e1.grid(row=1, column=0, pady=(0, 8))
    tk.Label(f, text="电脑加速密钥（系统 → 设置 → 组件与插件 →「生成密钥」，lh_ 开头）", anchor="w").grid(row=2, column=0, sticky="w")
    e2 = tk.Entry(f, width=52, show="•")
    e2.grid(row=3, column=0, pady=(0, 8))
    tk.Label(f, text="这台电脑的名字", anchor="w").grid(row=4, column=0, sticky="w")
    e3 = tk.Entry(f, width=52)
    e3.insert(0, c.get("name") or platform.node())
    e3.grid(row=5, column=0, pady=(0, 10))
    msg = tk.Label(f, text="", fg="#c62828")
    msg.grid(row=6, column=0, sticky="w")

    def ok():
        s = e1.get().strip().rstrip("/")
        if s and not s.startswith("http"):
            s = "http://" + s
        k = e2.get().strip() or c.get("key", "")
        if not s or not k.startswith("lh_"):
            msg.config(text="地址和密钥都要填（密钥 lh_ 开头）")
            return
        res.update(server=s, key=k, name=(e3.get().strip() or platform.node())[:40])
        root.destroy()
    b = tk.Frame(f)
    b.grid(row=7, column=0, sticky="e")
    tk.Button(b, text="保存并开始", command=ok, width=12).pack(side="left", padx=4)
    tk.Button(b, text="取消", command=root.destroy, width=8).pack(side="left")
    root.mainloop()
    return res or None


# ---------------- 加速 ----------------
def start_worker(c):
    import platform
    import worker as W
    os.makedirs(os.path.dirname(LOGF), exist_ok=True)
    _log = W.log

    def log(msg):
        _log(msg)
        try:
            if os.path.exists(LOGF) and os.path.getsize(LOGF) > 2_000_000:
                os.replace(LOGF, LOGF + ".old")
            with open(LOGF, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
        except OSError:
            pass
    W.log = log

    class TrayWorker(W.Worker):
        def update(self):
            log(f"NAS 是 v{self.server_version}：下载更新…")
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
            log("更新好了，重新启动…")
            restart()

    name = c.get("name") or ((c["name_prefix"] + "@" + platform.node())[:40] if c.get("name_prefix") else platform.node())
    w = TrayWorker(c["server"], c["key"], name, c.get("slots") or max(1, min(2, (os.cpu_count() or 2) // 4)))
    w.paused = bool(c.get("paused"))
    w.share = bool(c.get("share"))
    w.no_install = bool(c.get("no_install"))
    S["w"] = w

    def run():
        try:
            w.loop()
        except Exception as e:  # noqa: BLE001
            S["err"] = str(e)[:100]
            log(f"加速出错：{e}")
    threading.Thread(target=run, daemon=True, name="worker").start()
    return w


def state():
    w = S["w"]
    if S["err"]:
        return "出错"
    if not w:
        return "连接中"
    if w.paused:
        return "暂停"
    return "在线" if w.server_version else "连接中"


# ---------------- 托盘 ----------------
def tray(c):
    import pystray
    import trayicon
    import worker as W

    def save():
        W.save_conf(c)

    def opt(k):
        def f(icon, item):
            c[k] = not c.get(k)
            save()
            if S["w"]:
                setattr(S["w"], k, bool(c[k]))
            refresh_now()
        return f

    def open_system(icon, item):
        import webbrowser
        webbrowser.open(c.get("server") or "")

    def open_log(icon, item):
        try:
            os.startfile(LOGF)          # noqa
        except Exception:  # noqa: BLE001
            pass

    def change(icon, item):
        n = setup_dialog(dict(c))
        if n:
            c.update(n)
            c.pop("name_prefix", None)
            save()
            restart()

    def quit_all(icon, item):
        S["quitting"] = True
        icon.stop()
        os._exit(0)

    def title():
        w = S["w"]
        st = state()
        cur = f" · 正在{w.current}" if w and w.current else ""
        inst = f" · {w.installing}" if w and w.installing else ""
        return f"3D Ops 加速器：{st}{cur}{inst}\n已做 {w.done if w else 0} 件"[:120]

    personal = bool(c.get("name_prefix"))
    items = [pystray.MenuItem(lambda it: title().split("\n")[0], lambda i, it: None, enabled=False),
             pystray.MenuItem("打开 3D 运营管理系统（浏览器）", open_system, default=True),
             pystray.Menu.SEPARATOR,
             pystray.MenuItem("暂停加速", opt("paused"), checked=lambda it: bool(c.get("paused")))]
    if personal:
        items.append(pystray.MenuItem("也帮别人加速（同事的活）", opt("share"), checked=lambda it: bool(c.get("share"))))
    items += [pystray.MenuItem("开机自动启动", lambda i, it: autostart_set(not autostart_get()), checked=lambda it: autostart_get()),
              pystray.MenuItem("运行记录", open_log),
              pystray.MenuItem("修改 NAS 地址和密钥…", change),
              pystray.Menu.SEPARATOR,
              pystray.MenuItem("退出加速器", quit_all)]
    icon = pystray.Icon("3d-ops-accel", trayicon.image("accel.png", state()), "3D Ops 加速器", pystray.Menu(*items))
    S["icon"] = icon
    last = {"st": None}

    def refresh_now():
        try:
            st = state()
            if st != last["st"]:
                icon.icon = trayicon.image("accel.png", st)
                last["st"] = st
            icon.title = title()
            icon.update_menu()
        except Exception:  # noqa: BLE001
            pass

    def loop():
        time.sleep(1)
        if not c.get("tray_tip"):
            c["tray_tip"] = 1
            save()
            try:
                icon.notify("加速器在右下角后台运行：切片、读模型、抠图会交给这台电脑做。右键图标可以暂停或退出。", "3D Ops 加速器")
            except Exception:  # noqa: BLE001
                pass
        while not S["quitting"]:
            refresh_now()
            time.sleep(4)
    threading.Thread(target=loop, daemon=True).start()
    return icon


def lock_listener(sock):
    while True:
        try:
            cl, _ = sock.accept()
            with cl:
                m = cl.recv(16)
                if m == b"restart":
                    restart()
                elif m == b"show" and S["icon"]:
                    S["icon"].notify("加速器已经在运行了（右下角托盘图标）", "3D Ops 加速器")
        except Exception:  # noqa: BLE001
            time.sleep(1)


def main():
    sock = single_instance(wait=8 if "--restarted" in sys.argv else 0)
    if not sock:
        return
    threading.Thread(target=lock_listener, args=(sock,), daemon=True).start()
    import worker as W
    c = W.load_conf()
    if not c.get("server") or not c.get("key"):
        n = setup_dialog(c)
        if not n:
            return
        c.update(n)
        W.save_conf(c)
    if "autostart_done" not in c:            # 第一次运行：默认开机自动启动
        autostart_set(True)
        c["autostart_done"] = 1
        W.save_conf(c)
    start_worker(c)
    tray(c).run()


if __name__ == "__main__":
    main()
