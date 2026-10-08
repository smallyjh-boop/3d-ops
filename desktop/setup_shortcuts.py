"""安装时运行：桌面和开始菜单的快捷方式、开机自动启动（只开托盘）。"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def shortcut(path, target, args, icon, workdir):
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');$s.TargetPath='%s';$s.Arguments='%s';"
          "$s.IconLocation='%s';$s.WorkingDirectory='%s';$s.Description='3D 运营管理系统';$s.Save()") % (
        path.replace("'", "''"), target.replace("'", "''"), args.replace("'", "''"), icon.replace("'", "''"), workdir.replace("'", "''"))
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], check=False,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def main():
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    app = os.path.join(HERE, "desktop_app.py")
    icon = os.path.join(HERE, "icon.ico")
    home = os.path.expanduser("~")
    desk = os.path.join(home, "Desktop")
    try:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)   # 真正的桌面（可能被 OneDrive 移走）
        if buf.value:
            desk = buf.value
    except Exception:  # noqa: BLE001
        pass
    menu = os.path.join(os.environ.get("APPDATA", home), "Microsoft", "Windows", "Start Menu", "Programs")
    for d in (desk, menu):
        if os.path.isdir(d):
            shortcut(os.path.join(d, "3D Ops.lnk"), exe, f'"{app}"', icon, HERE)
    import desktop_app
    desktop_app.autostart_set(True)
    print("   Shortcuts created; auto start ON.")


if __name__ == "__main__":
    main()
