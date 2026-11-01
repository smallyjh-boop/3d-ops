"""桌面客户端（Windows）：在 Bambu Studio / OrcaSlicer 里编辑一盘（v2.56，T36）+ 切片软件自检。

· detect()：找两个软件（默认安装目录 + 注册表 Uninstall 项的 DisplayName / InstallLocation / DisplayVersion）和版本
· EditJob：下载编辑文件到 文档\\3D-Ops\\编辑中\\…，用对应软件打开（窗口最大化），后台线程监视文件：
  保存后（修改时间变了、2 秒内不再变、是完整的 zip）自动上传；完成 / 放弃时停止监视
· split_screen()：可选「左右分屏」（软件左半屏、客户端右半屏），用 ctypes 调 Windows API，失败不影响主流程
· 自检：selftest_checks() 把每一步结果整理成通过 / 不通过清单（中文 + 泰文）
检测 / 监视 / 上传的判断都写成纯函数（参数注入文件系统、注册表、时钟、HTTP），Linux 上的测试里模拟。
"""
import io
import ntpath
import os
import re
import subprocess
import threading
import time
import zipfile

APPS = {"bambu": "Bambu Studio", "orca": "OrcaSlicer"}
DEFAULT_EXE = {
    "bambu": [r"C:\Program Files\Bambu Studio\bambu-studio.exe", r"C:\Program Files (x86)\Bambu Studio\bambu-studio.exe"],
    "orca": [r"C:\Program Files\OrcaSlicer\orca-slicer.exe", r"C:\Program Files\OrcaSlicer\OrcaSlicer.exe",
             r"C:\Program Files (x86)\OrcaSlicer\orca-slicer.exe"],
}
EXE_NAMES = {"bambu": ("bambu-studio.exe", "BambuStudio.exe"), "orca": ("orca-slicer.exe", "OrcaSlicer.exe")}
DOWNLOAD = {"bambu": "https://bambulab.com/en/download/studio", "orca": "https://github.com/SoftFever/OrcaSlicer/releases"}
UNINSTALL_KEYS = [("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
                  ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
                  ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
STABLE_S = 2.0


# ---------------- 检测 ----------------
def app_of_name(display_name):
    """注册表 DisplayName → "bambu" / "orca" / None。"""
    n = str(display_name or "").lower()
    if "orca" in n and "slicer" in n:
        return "orca"
    if "bambu" in n and "studio" in n:
        return "bambu"
    return None


def read_registry():
    """Windows：所有 Uninstall 项 [{DisplayName, InstallLocation, DisplayVersion, DisplayIcon}]；别的系统返回 []。"""
    try:
        import winreg
    except ImportError:
        return []
    out = []
    roots = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    for root, path in UNINSTALL_KEYS:
        try:
            k = winreg.OpenKey(roots[root], path)
        except OSError:
            continue
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(k, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(k, sub) as sk:
                    d = {}
                    for name in ("DisplayName", "InstallLocation", "DisplayVersion", "DisplayIcon"):
                        try:
                            d[name] = str(winreg.QueryValueEx(sk, name)[0])
                        except OSError:
                            pass
                    if d.get("DisplayName"):
                        out.append(d)
            except OSError:
                continue
    return out


def _exe_from_entry(app, e, exists):
    cands = []
    loc = (e.get("InstallLocation") or "").strip().strip('"')
    if loc:
        cands += [ntpath.join(loc, n) for n in EXE_NAMES[app]]          # Windows 路径（测试在 Linux 上也按 Windows 拼）
    icon = (e.get("DisplayIcon") or "").split(",")[0].strip().strip('"')
    if icon.lower().endswith(".exe"):
        cands.insert(0, icon)
    return next((c for c in cands if exists(c)), None)


def detect(exists=os.path.isfile, registry=None):
    """{app: {path, version, source} 或 None}。registry = read_registry() 的结果（测试时传模拟的）。"""
    reg = read_registry() if registry is None else registry
    out = {}
    for app in APPS:
        found = None
        for e in reg:
            if app_of_name(e.get("DisplayName")) != app:
                continue
            exe = _exe_from_entry(app, e, exists)
            if exe:
                found = {"path": exe, "version": e.get("DisplayVersion") or "", "source": "registry", "name": e.get("DisplayName")}
                break
        if not found:
            exe = next((c for c in DEFAULT_EXE[app] if exists(c)), None)
            if exe:
                ver = next((e.get("DisplayVersion") for e in reg if app_of_name(e.get("DisplayName")) == app and e.get("DisplayVersion")), "")
                found = {"path": exe, "version": ver or "", "source": "default", "name": APPS[app]}
        out[app] = found
    return out


# ---------------- 文件 ----------------
def safe_name(s, n=120):
    return re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(s or "file")).strip(" .")[:n] or "file"


def edit_dir(home=None):
    return os.path.join(home or os.path.expanduser("~"), "Documents", "3D-Ops", "编辑中")


def is_valid_project(data_or_path):
    """完整的 3MF（zip 能读、CRC 对、有 3D/3dmodel.model）。软件正在写的时候读到的半个文件 → False。"""
    try:
        if isinstance(data_or_path, (bytes, bytearray)):
            z = zipfile.ZipFile(io.BytesIO(data_or_path))
        else:
            z = zipfile.ZipFile(data_or_path)
        with z:
            if z.testzip() is not None:
                return False
            return any(n.lower() == "3d/3dmodel.model" for n in z.namelist())
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        return False


class SaveWatcher:
    """判断「软件保存好了」：修改时间 / 大小和上次上传的不一样，并且连续 STABLE_S 秒没变，是完整的 3MF → 该上传了。
    step(now, stat) 是纯函数式的一步（stat = (mtime, size) 或 None），返回 True = 现在上传。"""

    def __init__(self, first_stat, stable=STABLE_S):
        self.done = first_stat          # 已经上传过 / 下载下来时的样子
        self.seen = first_stat
        self.since = None
        self.stable = stable

    def step(self, now, stat, valid=lambda: True):
        if stat is None or stat == self.done:
            self.seen, self.since = stat, None
            return False
        if stat != self.seen:
            self.seen, self.since = stat, now
            return False
        if self.since is not None and now - self.since >= self.stable and valid():
            self.done = stat
            self.since = None
            return True
        return False


def file_stat(path):
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


def upload(url, path, post=None, timeout=300):
    """把保存好的文件传回服务器。返回 (ok, 服务器回的 JSON / 错误)。"""
    if post is None:
        import requests
        post = requests.post
    with open(path, "rb") as f:
        data = f.read()
    try:
        r = post(url, data=data, headers={"Content-Type": "application/octet-stream"}, timeout=timeout)
        try:
            j = r.json()
        except Exception:  # noqa: BLE001
            j = {"error": f"HTTP {r.status_code}"}
        return r.status_code == 200, j
    except Exception as e:  # noqa: BLE001
        return False, {"error": str(e)}


# ---------------- 启动软件 / 分屏 ----------------
SW_MAXIMIZE = 3


def launch(exe, path, popen=None):
    """用切片软件打开文件，窗口最大化（Windows STARTUPINFO.wShowWindow = SW_MAXIMIZE）。返回进程。"""
    popen = popen or subprocess.Popen
    kw = {}
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = SW_MAXIMIZE
        kw["startupinfo"] = si
    return popen([exe, path], **kw)


def halves(work_area):
    """(左, 上, 右, 下) → (左半屏矩形, 右半屏矩形)，每个是 (x, y, w, h)。"""
    l, t, r, b = work_area
    w = (r - l) // 2
    return (l, t, w, b - t), (l + w, t, r - l - w, b - t)


def split_screen(pid, title_part="3D", timeout=15):
    """可选：软件窗口放左半屏，客户端窗口放右半屏（ctypes 调 Windows API）。返回 (ok, 说明)。失败不影响主流程。"""
    if os.name != "nt":
        return False, "只在 Windows 上能分屏"
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        rect = wintypes.RECT()
        u.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)          # SPI_GETWORKAREA
        left, right = halves((rect.left, rect.top, rect.right, rect.bottom))
        found = {"app": None, "me": None}
        cb_t = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _l):
            if not u.IsWindowVisible(hwnd):
                return True
            p = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            n = u.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(hwnd, buf, n + 1)
            if p.value == pid and n and not found["app"]:
                found["app"] = hwnd
            elif p.value == os.getpid() and title_part in buf.value and not found["me"]:
                found["me"] = hwnd
            return True
        end = time.time() + timeout
        while time.time() < end and not found["app"]:
            u.EnumWindows(cb_t(cb), 0)
            if not found["app"]:
                time.sleep(0.5)
        if not found["app"]:
            return False, "没找到切片软件的窗口"
        for hwnd, (x, y, w, h) in ((found["app"], left), (found["me"], right)):
            if hwnd:
                u.ShowWindow(hwnd, 9)                                     # SW_RESTORE（最大化的窗口先还原才能摆）
                u.SetWindowPos(hwnd, 0, x, y, w, h, 0x0040)                # SWP_SHOWWINDOW
        return True, "已左右分屏"
    except Exception as e:  # noqa: BLE001
        return False, f"分屏失败：{e}"


ALLOWED_PREFIX = ("/api/slicer-edit/", "/api/desktop/st/")


def allowed_path(p):
    p = str(p or "")
    return p.startswith(ALLOWED_PREFIX) and "://" not in p and ".." not in p and "\\" not in p


# ---------------- 一次编辑 ----------------
class EditJob:
    """一次编辑会话在这台电脑上的状态：文件、软件进程、监视线程、同步记录。"""

    def __init__(self, info, server, slicers, home=None, get=None, post=None, popen=None, clock=time.time, sleep=time.sleep):
        self.info = dict(info or {})
        self.sid = str(self.info.get("sid") or self.info.get("session", {}).get("id") or "")
        self.app = self.info.get("app") or "orca"
        self.server = server.rstrip("/") if server else ""
        self.slicers = slicers or {}
        self.home = home
        self._get, self._post, self._popen = get, post, popen
        self.clock, self.sleep = clock, sleep
        self.path = None
        self.proc = None
        self.stop_ev = threading.Event()
        self.state = {"sid": self.sid, "app": self.app, "status": "starting", "syncs": 0, "last_sync": None, "error": "",
                      "last_result": None, "path": ""}
        self.watcher = None

    def url(self, p):
        """只接受服务器上的编辑 / 自检地址（相对路径），不接受绝对地址（网页里的脚本不能让客户端把文件传到别处）。"""
        if not allowed_path(p):
            raise ValueError("地址不对 / ที่อยู่ไม่ถูกต้อง")
        return self.server + p

    def download(self):
        get = self._get
        if get is None:
            import requests
            get = requests.get
        d = os.path.join(edit_dir(self.home), safe_name(self.info.get("folder") or self.sid, 60))
        os.makedirs(d, exist_ok=True)
        self.path = os.path.join(d, safe_name(self.info.get("filename") or (self.sid + ".3mf")))
        r = get(self.url(self.info["download"]), timeout=600)
        if getattr(r, "status_code", 200) != 200:
            raise RuntimeError(f"下载失败 HTTP {r.status_code}")
        with open(self.path + ".part", "wb") as f:
            f.write(r.content)
        os.replace(self.path + ".part", self.path)
        self.state["path"] = self.path
        return self.path

    def start(self, watch=True):
        s = self.slicers.get(self.app)
        if not s or not s.get("path"):
            self.state.update(status="no_app", error=f"这台电脑没有装 {APPS.get(self.app, self.app)}")
            return self.state
        self.download()
        self.proc = launch(s["path"], self.path, self._popen)
        self.watcher = SaveWatcher(file_stat(self.path))
        self.state["status"] = "editing"
        if watch:
            threading.Thread(target=self.loop, daemon=True).start()
        return self.state

    def poll_once(self):
        """监视一步（测试里直接调）：保存好了就上传。返回 True = 这一步上传了。"""
        if not self.watcher or self.stop_ev.is_set():
            return False
        if self.watcher.step(self.clock(), file_stat(self.path), lambda: is_valid_project(self.path)):
            ok, j = upload(self.url(self.info["upload"]), self.path, self._post)
            if ok:
                self.state["syncs"] += 1
                self.state["last_sync"] = self.clock()
                self.state["last_result"] = {k: j.get(k) for k in ("confirm", "changes", "new_plates", "deleted", "check")}
                self.state["error"] = ""
            else:
                self.state["error"] = str(j.get("error") or "上传失败")
                if "结束" in self.state["error"] or "过期" in self.state["error"]:
                    self.stop("ended")
            return ok
        return False

    def loop(self):
        while not self.stop_ev.is_set():
            try:
                self.poll_once()
            except Exception as e:  # noqa: BLE001
                self.state["error"] = str(e)
            self.sleep(0.5)

    def stop(self, status="done"):
        self.stop_ev.set()
        self.state["status"] = status
        return self.state


# ---------------- 自检 ----------------
def L(zh, th):
    return {"zh": zh, "th": th}


def selftest_checks(detected, runs, split=None):
    """自检结果清单：[{key, ok, zh, th, detail}]。
    detected = detect() 的结果；runs = {app: {opened, uploaded, server: 服务器核对结果 {objects_ok, moved, slots_ok, colours_ok,
    settings_ok, errors}, error}}；split = (ok, 说明) 或 None（没试）。"""
    out = []

    def add(key, ok, zh, th, detail=""):
        out.append({"key": key, "ok": bool(ok), "zh": zh, "th": th, "detail": str(detail or "")})
    for app, name in APPS.items():
        d = (detected or {}).get(app)
        add(f"{app}.installed", bool(d), f"{name} 已安装" + (f"（{d.get('version')}）" if d and d.get("version") else ""),
            f"ติดตั้ง {name} แล้ว" + (f" ({d.get('version')})" if d and d.get("version") else ""),
            (d or {}).get("path") or f"没找到，下载：{DOWNLOAD[app]}")
        if not d:
            continue
        r = (runs or {}).get(app) or {}
        sv = r.get("server") or {}
        add(f"{app}.opened", r.get("opened"), f"{name} 能打开系统生成的项目文件", f"{name} เปิดไฟล์โปรเจกต์ที่ระบบสร้างได้", r.get("error") if not r.get("opened") else "")
        add(f"{app}.uploaded", r.get("uploaded"), f"{name} 保存后自动回传", f"{name} บันทึกแล้วส่งกลับอัตโนมัติ", r.get("error") if not r.get("uploaded") else "")
        if r.get("uploaded"):
            add(f"{app}.objects", sv.get("objects_ok"), "零件都对应上了（编号没丢）", "ชิ้นงานตรงกันครบ (รหัสไม่หาย)", sv.get("objects_detail"))
            add(f"{app}.moved", sv.get("moved"), "位置同步（挪过的零件读回来了）", "ตำแหน่งซิงก์ (ชิ้นที่ย้ายอ่านกลับมาได้)", sv.get("moved_detail"))
            add(f"{app}.slots", sv.get("slots_ok"), "颜色槽同步（每个零件的槽）", "ช่องสีซิงก์ (ช่องของแต่ละชิ้น)", sv.get("slots_detail"))
            add(f"{app}.colours", sv.get("colours_ok"), "耗材颜色 / 材料读回正确", "สี / วัสดุฟิลาเมนต์อ่านกลับถูกต้อง", sv.get("colours_detail"))
            add(f"{app}.settings", sv.get("settings_ok"), "打印机 / 工艺配置带进软件了", "โปรไฟล์เครื่องพิมพ์ / กระบวนการติดไปในโปรแกรม", sv.get("settings_detail"))
    if split is not None:
        add("split", split[0], "左右分屏", "แบ่งจอซ้ายขวา", split[1])
    return out
